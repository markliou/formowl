from __future__ import annotations

import copy
from collections import UserDict
from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

import _paths  # noqa: F401
from formowl_auth import (
    ExternalIdentity,
    FileAuditLogStore,
    OAuthAccessDenied,
    OAuthAuthorizationCode,
    OAuthBridgeConfig,
    OAuthClientAuthorization,
    OAuthInvitation,
    OAuthOwnerBootstrap,
    OAuthPrincipal,
    OAuthTokenSession,
    OAuthTransaction,
    assert_connected_auth_mode,
    sanitize_oauth_audit_metadata,
    write_audit_log,
    write_oauth_audit_event,
)
from formowl_auth.models import (
    _mapping,
    _optional_safe_ids,
    _optional_timestamps,
    _required_safe_ids,
    _required_string,
    _validate_code_challenge,
    _validate_hash,
    _validate_scopes,
    _validate_timestamp,
)
from formowl_auth.security import (
    decrypt_client_state,
    encrypt_client_state,
    generate_opaque_value,
    generate_safe_id,
    hash_oauth_value,
    normalize_verified_email,
    oauth_hash_matches,
    pkce_s256_challenge,
    validate_pkce_verifier,
)
from formowl_contract import (
    AuditLog,
    ContractValidationError,
    SessionIdentity,
    validate_audit_log,
)
from oauth_harness import DeterministicRng, FakeClock


class _CopySideEffectProbe:
    def __init__(self, secret: str, calls: list[str]) -> None:
        self._secret = secret
        self._calls = calls

    def __copy__(self) -> object:
        self._calls.append("copy")
        raise RuntimeError(self._secret)

    def __deepcopy__(self, _memo: object) -> object:
        self._calls.append("deepcopy")
        raise RuntimeError(self._secret)


class _CopySideEffectString(str):
    def __new__(
        cls,
        value: str,
        secret: str,
        calls: list[str],
    ) -> "_CopySideEffectString":
        instance = super().__new__(cls, value)
        instance._secret = secret
        instance._calls = calls
        return instance

    def __copy__(self) -> object:
        self._calls.append("copy")
        raise RuntimeError(self._secret)

    def __deepcopy__(self, _memo: object) -> object:
        self._calls.append("deepcopy")
        raise RuntimeError(self._secret)


class _MappingSideEffectProbe(Mapping[str, object]):
    def __init__(self, secret: str, calls: list[str]) -> None:
        self._secret = secret
        self._calls = calls
        self._source_state = {"sentinel": "unchanged"}

    def __getitem__(self, _key: str) -> object:
        self._calls.append("getitem")
        raise RuntimeError(self._secret)

    def __iter__(self):  # type: ignore[no-untyped-def]
        self._calls.append("iter")
        raise RuntimeError(self._secret)

    def __len__(self) -> int:
        self._calls.append("len")
        raise RuntimeError(self._secret)


class _HashCollisionKey:
    def __init__(self, target: str, secret: str, calls: list[str]) -> None:
        self._target = target
        self._secret = secret
        self._calls = calls

    def __hash__(self) -> int:
        return hash(self._target)

    def __eq__(self, _other: object) -> bool:
        self._calls.append("eq")
        raise RuntimeError(self._secret)


class OAuthContractsAndSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.rng = DeterministicRng("oauth-contract-tests")
        self.now = self.clock.now()
        self.now_iso = self.now.isoformat()
        self.later_iso = (self.now + timedelta(minutes=5)).isoformat()

    def test_shared_session_and_audit_contracts_support_oauth_without_breaking_manual(self) -> None:
        oauth_session = SessionIdentity(
            session_id="oauthsid_001",
            selected_user_id="user_001",
            selected_at=self.now_iso,
            selection_method="google_oidc_oauth",
        )
        pre_auth = AuditLog(
            audit_log_id="audit_pre_auth",
            actor_user_id=None,
            actor_type="external_unauthenticated",
            action="google_authentication_failed",
            target_type="oauth_request",
            target_id="oauthdeny_001",
            session_id="oauthdeny_001",
            timestamp=self.now_iso,
            oauth_client_id="chatgpt_client",
            request_id="request_001",
            reason_code="google_signature_invalid",
            status="permission_denied",
            metadata={"event_stage": "google_callback", "provider": "google"},
        )

        self.assertEqual(
            SessionIdentity.from_dict(oauth_session.to_dict()).to_dict(),
            oauth_session.to_dict(),
        )
        self.assertEqual(AuditLog.from_dict(pre_auth.to_dict()).to_dict(), pre_auth.to_dict())

        old_payload = {
            "audit_log_id": "audit_old",
            "actor_user_id": "user_001",
            "action": "actor_selected",
            "target_type": "user",
            "target_id": "user_001",
            "session_id": "session_001",
            "timestamp": self.now_iso,
        }
        restored = AuditLog.from_dict(old_payload)
        self.assertEqual(restored.actor_type, "user")
        self.assertEqual(restored.actor_user_id, "user_001")

    def test_audit_contract_and_oauth_allowlist_reject_secrets_paths_and_sql(self) -> None:
        for metadata in (
            {"access_token": "secret-value"},
            {"state": "raw-state"},
            {"event_stage": "/tmp/private"},
            {"event_stage": "select value from hidden_table"},
        ):
            with self.subTest(metadata=metadata):
                with self.assertRaises((ContractValidationError, ValueError)):
                    AuditLog(
                        audit_log_id="audit_bad",
                        actor_user_id=None,
                        actor_type="external_unauthenticated",
                        action="oauth_denied",
                        target_type="oauth_request",
                        target_id="request_001",
                        session_id="request_001",
                        timestamp=self.now_iso,
                        metadata=metadata,
                    ).to_dict()

        with self.assertRaises(ValueError):
            sanitize_oauth_audit_metadata({"email": "person@example.test"})
        self.assertEqual(
            sanitize_oauth_audit_metadata(
                {"event_stage": "token_exchange", "scopes": ["formowl.use"]}
            ),
            {"event_stage": "token_exchange", "scopes": ["formowl.use"]},
        )

    def test_sanitize_oauth_audit_metadata_preserves_allowlisted_lineage(self) -> None:
        metadata = {
            "event_stage": "mcp_authorization",
            "provider": "google",
            "scopes": ("formowl.use", "formowl.read"),
            "membership_role": "member",
            "workspace_decision": "allowed",
            "identity_status": "active",
            "client_authorization_status": "active",
            "token_session_status": "active",
            "lineage_source": "verified_token_session",
            "approval_user_id": "user_admin",
            "http_status": 200,
            "replay_rejected": False,
        }
        original = copy.deepcopy(metadata)

        sanitized = sanitize_oauth_audit_metadata(metadata)

        self.assertEqual(
            sanitized,
            {
                **metadata,
                "scopes": ["formowl.use", "formowl.read"],
            },
        )
        self.assertEqual(metadata, original)
        self.assertIsNot(sanitized, metadata)

    def test_sanitize_oauth_audit_metadata_rejects_unsafe_values_without_mutation(
        self,
    ) -> None:
        invalid_metadata = (
            (
                {"event_stage": "authorization", 1: "private"},
                "OAuth audit metadata contains unsupported keys",
                ("event_stage", "authorization", "1", "private"),
            ),
            (
                {"email": "person@example.test"},
                "OAuth audit metadata contains unsupported keys",
                ("email", "person@example.test"),
            ),
            (
                {"event_stage": "/tmp/private"},
                "OAuth audit metadata contains an unsafe value",
                ("event_stage", "/tmp/private"),
            ),
            (
                {"event_stage": "select value from hidden_table"},
                "OAuth audit metadata contains an unsafe value",
                ("event_stage", "select value from hidden_table"),
            ),
            (
                {"http_status": -1},
                "OAuth audit metadata contains an unsafe value",
                ("http_status", "-1"),
            ),
            (
                {"scopes": ["formowl.use", "unsafe scope"]},
                "OAuth audit metadata contains an unsafe value",
                ("scopes", "formowl.use", "unsafe scope"),
            ),
            (
                {"event_stage": True},
                "OAuth audit metadata contains an unsafe value",
                ("event_stage", "true"),
            ),
            (
                {"http_status": False},
                "OAuth audit metadata contains an unsafe value",
                ("http_status", "false"),
            ),
            (
                {"http_status": 99},
                "OAuth audit metadata contains an unsafe value",
                ("http_status", "99"),
            ),
            (
                {"http_status": 600},
                "OAuth audit metadata contains an unsafe value",
                ("http_status", "600"),
            ),
            (
                {"replay_rejected": 200},
                "OAuth audit metadata contains an unsafe value",
                ("replay_rejected", "200"),
            ),
            (
                {"scopes": "formowl.use"},
                "OAuth audit metadata contains an unsafe value",
                ("scopes", "formowl.use"),
            ),
            (
                {"approval_user_id": 0},
                "OAuth audit metadata contains an unsafe value",
                ("approval_user_id", "0"),
            ),
        )
        for metadata, expected_message, forbidden_fragments in invalid_metadata:
            with self.subTest(metadata=metadata):
                original = copy.deepcopy(metadata)
                with self.assertRaises(ValueError) as caught:
                    sanitize_oauth_audit_metadata(metadata)
                self.assertEqual(str(caught.exception), expected_message)
                rendered_error = str(caught.exception).casefold()
                for forbidden in forbidden_fragments:
                    self.assertNotIn(forbidden.casefold(), rendered_error)
                self.assertEqual(metadata, original)

        with self.assertRaises(ValueError) as caught:
            sanitize_oauth_audit_metadata(["event_stage", "authorization"])  # type: ignore[arg-type]
        self.assertEqual(str(caught.exception), "OAuth audit metadata must be an object")
        self.assertNotIn("event_stage", str(caught.exception))
        self.assertNotIn("authorization", str(caught.exception))

    def test_owner_bootstrap_and_service_audit_contracts_are_explicit(self) -> None:
        bootstrap = OAuthOwnerBootstrap(
            workspace_id="workspace_001",
            normalized_email="person@example.test",
            idempotency_key_hash=hash_oauth_value(
                "owner_bootstrap_idempotency",
                "private-idempotency-key",
            ),
            invitation_id="invite_bootstrap_001",
            operator_service_id="operator_service_001",
            status="pending",
            created_at=self.now_iso,
        )
        service_audit = AuditLog(
            audit_log_id="audit_bootstrap_001",
            actor_user_id=None,
            actor_type="service",
            actor_service_id="operator_service_001",
            action="oauth_owner_bootstrap_created",
            target_type="oauth_owner_bootstrap",
            target_id="invite_bootstrap_001",
            session_id="invite_bootstrap_001",
            workspace_id="workspace_001",
            timestamp=self.now_iso,
            status="ok",
            reason_code="owner_bootstrap_created",
            metadata={"event_stage": "owner_bootstrap"},
        )

        self.assertEqual(
            OAuthOwnerBootstrap.from_dict(bootstrap.to_dict()),
            bootstrap,
        )
        bootstrap_payload = bootstrap.to_dict()
        invalid_bootstraps = (
            {**bootstrap_payload, "normalized_email": "Person@example.test"},
            {**bootstrap_payload, "operator_service_id": "unsafe service id"},
            {**bootstrap_payload, "completed_at": self.now_iso},
            {**bootstrap_payload, "status": "completed", "completed_at": None},
        )
        for invalid_bootstrap in invalid_bootstraps:
            with self.subTest(invalid_bootstrap=invalid_bootstrap):
                with self.assertRaises(ContractValidationError):
                    OAuthOwnerBootstrap.from_dict(invalid_bootstrap)

        self.assertEqual(AuditLog.from_dict(service_audit.to_dict()), service_audit)
        store = FileAuditLogStore(_paths.fresh_test_dir("oauth-service-audit"))
        self.assertEqual(store.create(service_audit), service_audit)
        written = write_oauth_audit_event(
            store,
            audit_log_id="audit_bootstrap_002",
            actor_user_id=None,
            actor_type="service",
            actor_service_id="operator_service_001",
            action="oauth_owner_bootstrap_created",
            target_type="oauth_owner_bootstrap",
            target_id="invite_bootstrap_001",
            session_id="invite_bootstrap_001",
            workspace_id="workspace_001",
            timestamp=self.now_iso,
            status="ok",
            reason_code="owner_bootstrap_created",
            metadata={"event_stage": "owner_bootstrap"},
        )
        self.assertEqual(written.actor_service_id, "operator_service_001")
        with self.assertRaises(ContractValidationError):
            write_oauth_audit_event(
                store,
                audit_log_id="audit_bootstrap_invalid",
                actor_user_id=None,
                actor_type="service",
                actor_service_id=None,
                action="oauth_owner_bootstrap_created",
                target_type="oauth_owner_bootstrap",
                target_id="invite_bootstrap_001",
                session_id="invite_bootstrap_001",
                workspace_id="workspace_001",
                timestamp=self.now_iso,
                status="ok",
                reason_code="owner_bootstrap_created",
                metadata={"event_stage": "owner_bootstrap"},
            )
        rendered = str(service_audit.to_dict())
        self.assertNotIn("private-idempotency-key", rendered)
        self.assertNotIn("person@example.test", rendered)

        invalid_actors = (
            {"actor_type": "user", "actor_user_id": None, "actor_service_id": None},
            {
                "actor_type": "user",
                "actor_user_id": "user_001",
                "actor_service_id": "service_001",
            },
            {"actor_type": "service", "actor_user_id": None, "actor_service_id": None},
            {
                "actor_type": "service",
                "actor_user_id": "user_001",
                "actor_service_id": "service_001",
            },
            {
                "actor_type": "external_unauthenticated",
                "actor_user_id": None,
                "actor_service_id": "service_001",
            },
        )
        base = service_audit.to_dict()
        for mutation in invalid_actors:
            with self.subTest(mutation=mutation):
                with self.assertRaises(ContractValidationError):
                    AuditLog.from_dict({**base, **mutation})

    def test_write_oauth_audit_event_persists_safe_lineage_only(self) -> None:
        for index, token_session_status in enumerate(("active", "expired", "revoked")):
            with self.subTest(token_session_status=token_session_status):
                metadata = {
                    "event_stage": "token_exchange",
                    "scopes": ["formowl.use"],
                    "token_session_status": token_session_status,
                }
                sanitized = sanitize_oauth_audit_metadata(metadata)
                self.assertEqual(sanitized, metadata)
                contract_payload = {
                    "audit_log_id": f"audit_contract_status_{index}",
                    "actor_user_id": "user_001",
                    "action": "oauth_token_session_issued",
                    "target_type": "oauth_token_session",
                    "target_id": f"oauthsid_{index}",
                    "session_id": f"oauthsid_{index}",
                    "timestamp": self.now_iso,
                    "status": "ok",
                    "workspace_id": "workspace_001",
                    "metadata": sanitized,
                }
                self.assertEqual(
                    validate_audit_log(copy.deepcopy(contract_payload))["metadata"],
                    metadata,
                )
                self.assertEqual(
                    AuditLog.from_dict(copy.deepcopy(contract_payload)).metadata,
                    metadata,
                )

                direct_store = FileAuditLogStore(
                    _paths.fresh_test_dir(f"oauth-audit-direct-{token_session_status}")
                )
                direct_audit = write_audit_log(
                    direct_store,
                    **copy.deepcopy(contract_payload),
                )
                self.assertEqual(direct_store.get(direct_audit.audit_log_id), direct_audit)
                self.assertEqual(direct_audit.metadata, metadata)

                oauth_store = FileAuditLogStore(
                    _paths.fresh_test_dir(f"oauth-audit-event-{token_session_status}")
                )
                oauth_audit = write_oauth_audit_event(
                    oauth_store,
                    audit_log_id=f"audit_oauth_status_{index}",
                    actor_user_id="user_001",
                    action="oauth_token_session_issued",
                    target_type="oauth_token_session",
                    target_id=f"oauthsid_{index}",
                    session_id=f"oauthsid_{index}",
                    timestamp=self.now_iso,
                    status="ok",
                    workspace_id="workspace_001",
                    external_identity_id="extid_001",
                    oauth_client_id="chatgpt_client",
                    oauth_token_session_id=f"oauthsid_{index}",
                    request_id=f"request_{index}",
                    tool_call_id=f"toolcall_{index}",
                    reason_code="token_session_issued",
                    metadata=metadata,
                )
                self.assertEqual(oauth_store.get(oauth_audit.audit_log_id), oauth_audit)
                self.assertEqual(oauth_audit.metadata, metadata)
                rendered = str(oauth_audit.to_dict()).lower()
                for forbidden in ("access_token", "code_verifier", "/tmp/", "select "):
                    self.assertNotIn(forbidden, rendered)

    def test_token_session_status_rejects_non_lifecycle_codes_without_write_or_echo(
        self,
    ) -> None:
        for index, attack in enumerate(("access_token_private", "client_secret_backup")):
            with self.subTest(attack=attack):
                metadata = {"token_session_status": attack}
                original_metadata = copy.deepcopy(metadata)
                with self.assertRaises(ValueError) as caught:
                    sanitize_oauth_audit_metadata(metadata)
                self.assertEqual(
                    str(caught.exception),
                    "OAuth audit metadata contains an unsafe value",
                )
                self.assertNotIn(attack, str(caught.exception))
                self.assertEqual(metadata, original_metadata)

                attacked = {
                    "audit_log_id": f"audit_token_status_attack_{index}",
                    "actor_user_id": "user_001",
                    "action": "oauth_token_session_issued",
                    "target_type": "oauth_token_session",
                    "target_id": f"oauthsid_attack_{index}",
                    "session_id": f"oauthsid_attack_{index}",
                    "timestamp": self.now_iso,
                    "status": "ok",
                    "workspace_id": "workspace_001",
                    "metadata": metadata,
                }
                for decoder in (AuditLog.from_dict, validate_audit_log):
                    with self.subTest(decoder=decoder.__qualname__):
                        candidate = copy.deepcopy(attacked)
                        with self.assertRaises(ContractValidationError) as caught:
                            decoder(candidate)
                        self.assertNotIn(attack, str(caught.exception))
                        self.assertEqual(candidate, attacked)

                for writer_name, writer in (
                    ("write_audit_log", write_audit_log),
                    ("write_oauth_audit_event", write_oauth_audit_event),
                ):
                    with self.subTest(writer=writer_name):
                        store = FileAuditLogStore(
                            _paths.fresh_test_dir(f"oauth-token-status-{index}-{writer_name}")
                        )
                        candidate = copy.deepcopy(attacked)
                        with self.assertRaises((ContractValidationError, ValueError)) as caught:
                            writer(store, **candidate)
                        self.assertNotIn(attack, str(caught.exception))
                        self.assertEqual(candidate, attacked)
                        self.assertEqual(list(store.base_dir.iterdir()), [])

    def test_file_audit_writers_clean_atomic_failure_and_hide_backend_detail(
        self,
    ) -> None:
        for writer_name in ("write_audit_log", "write_oauth_audit_event"):
            with self.subTest(writer=writer_name):
                store = FileAuditLogStore(
                    _paths.fresh_test_dir(f"oauth-audit-atomic-{writer_name}")
                )
                common = {
                    "audit_log_id": f"audit_atomic_{writer_name}",
                    "actor_user_id": "user_001",
                    "action": "oauth_token_session_issued",
                    "target_type": "oauth_token_session",
                    "target_id": "oauthsid_001",
                    "session_id": "oauthsid_001",
                    "timestamp": self.now_iso,
                    "status": "ok",
                    "workspace_id": "workspace_001",
                }
                writer = (
                    write_audit_log if writer_name == "write_audit_log" else write_oauth_audit_event
                )
                record_path = store.base_dir / f"{common['audit_log_id']}.json"
                previous_bytes = b'{"authority":"previous"}\n'
                record_path.write_bytes(previous_bytes)
                with (
                    patch(
                        "formowl_core.json_files.os.replace",
                        side_effect=OSError("private audit path /secret/audit"),
                    ),
                    self.assertRaises(RuntimeError) as caught,
                ):
                    writer(store, **common)

                self.assertEqual(str(caught.exception), "audit log persistence failed")
                self.assertNotIn("/secret/audit", str(caught.exception))
                self.assertEqual(record_path.read_bytes(), previous_bytes)
                self.assertEqual(list(store.base_dir.iterdir()), [record_path])
                self.assertFalse(record_path.with_suffix(f"{record_path.suffix}.tmp").exists())
                self.assertEqual(
                    list(store.base_dir.glob(f".{record_path.name}.*.bak")),
                    [],
                )

    def test_owner_bootstrap_codecs_reject_unknown_caller_fields_without_echo(
        self,
    ) -> None:
        payload = OAuthOwnerBootstrap(
            workspace_id="workspace_001",
            normalized_email="person@example.test",
            idempotency_key_hash=hash_oauth_value(
                "owner_bootstrap_idempotency",
                "private-idempotency-key",
            ),
            invitation_id="invite_bootstrap_001",
            operator_service_id="operator_service_001",
            status="pending",
            created_at=self.now_iso,
        ).to_dict()
        attacked = {
            **payload,
            "access_token": "private-token",
        }
        original = copy.deepcopy(attacked)

        with self.assertRaises(ContractValidationError) as caught:
            OAuthOwnerBootstrap.from_dict(attacked)

        self.assertEqual(str(caught.exception), "OAuthOwnerBootstrap contains unsupported fields")
        self.assertNotIn("access_token", str(caught.exception))
        self.assertNotIn("private-token", str(caught.exception))
        self.assertEqual(attacked, original)

        invalid_record = OAuthOwnerBootstrap(
            **{
                **payload,
                "operator_service_id": "/secret/operator",
            }
        )
        with self.assertRaises(ContractValidationError) as caught:
            invalid_record.to_dict()
        self.assertNotIn("/secret/operator", str(caught.exception))

    def test_audit_decoders_reject_unknown_caller_fields_without_mutation_or_echo(
        self,
    ) -> None:
        payload = AuditLog(
            audit_log_id="audit_closed_schema_001",
            actor_user_id=None,
            actor_type="service",
            actor_service_id="operator_service_001",
            action="oauth_owner_bootstrap_created",
            target_type="oauth_owner_bootstrap",
            target_id="invite_bootstrap_001",
            session_id="invite_bootstrap_001",
            workspace_id="workspace_001",
            timestamp=self.now_iso,
            status="ok",
        ).to_dict()
        attacked = {
            **payload,
            "access_token": "private-token",
        }

        for decoder in (AuditLog.from_dict, validate_audit_log):
            with self.subTest(decoder=decoder.__qualname__):
                candidate = copy.deepcopy(attacked)
                with self.assertRaises(ContractValidationError) as caught:
                    decoder(candidate)
                self.assertEqual(
                    str(caught.exception),
                    "AuditLog contains unsupported fields",
                )
                self.assertNotIn("access_token", str(caught.exception))
                self.assertNotIn("private-token", str(caught.exception))
                self.assertEqual(candidate, attacked)

    def test_audit_top_level_fields_reject_unsafe_values_without_write_or_echo(
        self,
    ) -> None:
        base = {
            "audit_log_id": "audit_top_level_001",
            "actor_user_id": "user_001",
            "action": "oauth_token_session_issued",
            "target_type": "oauth_token_session",
            "target_id": "oauthsid_001",
            "session_id": "oauthsid_001",
            "timestamp": self.now_iso,
            "status": "ok",
            "workspace_id": "workspace_001",
            "oauth_token_session_id": "oauthsid_001",
            "request_id": "request_001",
            "reason_code": "token_session_issued",
        }
        validated_base = validate_audit_log(copy.deepcopy(base))
        restored_base = AuditLog.from_dict(copy.deepcopy(base))
        self.assertEqual(validated_base["action"], "oauth_token_session_issued")
        self.assertEqual(validated_base["target_type"], "oauth_token_session")
        self.assertEqual(restored_base.oauth_token_session_id, "oauthsid_001")
        self.assertEqual(restored_base.reason_code, "token_session_issued")
        attacks = (
            ("action", "/secret/audit"),
            ("target_type", "select value from hidden_table"),
            ("request_id", "postgresql://private/audit"),
            ("reason_code", "access_token=private-token"),
            ("status", "Bearer private-token"),
            ("session_id", "access_token_private"),
            ("request_id", "client_secret_backup"),
            ("timestamp", "not-a-timestamp"),
        )

        for field_name, unsafe_value in attacks:
            attacked = {**base, field_name: unsafe_value}
            for decoder in (AuditLog.from_dict, validate_audit_log):
                with self.subTest(field=field_name, decoder=decoder.__qualname__):
                    candidate = copy.deepcopy(attacked)
                    with self.assertRaises(ContractValidationError) as caught:
                        decoder(candidate)
                    self.assertNotIn(unsafe_value, str(caught.exception))
                    self.assertEqual(candidate, attacked)

            for writer_name, writer in (
                ("write_audit_log", write_audit_log),
                ("write_oauth_audit_event", write_oauth_audit_event),
            ):
                with self.subTest(field=field_name, writer=writer_name):
                    store = FileAuditLogStore(
                        _paths.fresh_test_dir(f"audit-top-level-{field_name}-{writer_name}")
                    )
                    with self.assertRaises(ContractValidationError) as caught:
                        writer(store, **attacked)
                    self.assertNotIn(unsafe_value, str(caught.exception))
                    self.assertEqual(list(store.base_dir.iterdir()), [])

    def test_generic_audit_metadata_rejects_secret_variants_without_write_or_echo(
        self,
    ) -> None:
        safe_metadata = {
            "note": "safe-note",
            "accessTokenCount": 2,
            "token_count": 3,
            "revoked_token_session_count": 4,
            "membership_state": "removed",
            "nested": {
                "labels": ["token_session_issued", "formowl.use"],
                "token_session_issued": True,
                "metrics": [
                    {"accessTokenCount": 1},
                    {"token_count": 2},
                    {"revokedTokenSessionCount": 3},
                ],
            },
        }
        base = {
            "audit_log_id": "audit_metadata_001",
            "actor_user_id": "user_001",
            "action": "oauth_token_session_issued",
            "target_type": "oauth_token_session",
            "target_id": "oauthsid_001",
            "session_id": "oauthsid_001",
            "timestamp": self.now_iso,
            "status": "ok",
            "workspace_id": "workspace_001",
            "metadata": safe_metadata,
        }
        self.assertEqual(
            validate_audit_log(copy.deepcopy(base))["metadata"],
            safe_metadata,
        )
        self.assertEqual(
            AuditLog.from_dict(copy.deepcopy(base)).metadata,
            safe_metadata,
        )

        benign_scalars = (
            "safe-note",
            "token_session_issued",
            "notbearer private words without credential syntax",
            "embedded_access_tokenized=value",
        )
        for index, scalar in enumerate(benign_scalars):
            metadata = {"note": scalar}
            benign = {**base, "audit_log_id": f"audit_benign_{index}", "metadata": metadata}
            self.assertEqual(
                validate_audit_log(copy.deepcopy(benign))["metadata"],
                metadata,
            )
            self.assertEqual(
                AuditLog.from_dict(copy.deepcopy(benign)).metadata,
                metadata,
            )
            store = FileAuditLogStore(_paths.fresh_test_dir(f"audit-metadata-benign-{index}"))
            write_audit_log(store, **benign)
            self.assertEqual(len(list(store.base_dir.iterdir())), 1)

        attacks = (
            {"note": "prefix?access_token=private-token"},
            {"note": "prefix(access_token=private-token)"},
            {"note": 'json:{"access_token":"private-token"}'},
            {"note": "x=Bearer private-token"},
            {"note": "Bearer private-token"},
            {"accessToken": "private-token"},
            {"access.token": "private-token"},
            {"clientSecretBackup": "private-token"},
            {"access.token.backup": "private-token"},
            {"accessTokenCount": "private-token"},
            {"accessTokenCount": {"value": "private-token"}},
            {"accessTokenCount": True},
            {"accessTokenCount": -1},
            {"tokenBackup": "private-token"},
            {"token.value": "private-token"},
            {"tokenValue": {"value": "private-token"}},
            {"token_count": "private-token"},
            {"token_count": {"value": "private-token"}},
            {"token_count": True},
            {"token_count": -1},
            {"revoked_token_session_count": "private-token"},
            {"revoked_token_session_count": {"value": "private-token"}},
            {"revoked_token_session_count": True},
            {"revoked_token_session_count": -1},
            {"revoked_token_session_count": 1.0},
            {"revoked_token_value_count": 1},
            {"revoked_token_session_secret_count": 1},
            {"revoked_token_session_count_backup": 1},
            {"membership_state": "private-token"},
            {"membership_state": True},
            {"membership_state": 1},
            {"membership_state": {"value": "removed"}},
            {"membership_state": "/tmp/private"},
            {"membership_state": "access_token=private-token"},
            {"token_session_issued": "private-token"},
            {"token_session_issued": 1},
            {"token_session_status": True},
            {"token_session_status": 1},
            {"token_session_status": {"value": "active"}},
            {"token_session_status": "unsafe scope"},
            {"token_session_status": "/tmp/private"},
            {"token_session_status": "access_token=private-token"},
        )
        for index, metadata in enumerate(attacks):
            attacked = {**base, "metadata": metadata}
            for decoder in (AuditLog.from_dict, validate_audit_log):
                with self.subTest(metadata=metadata, decoder=decoder.__qualname__):
                    candidate = copy.deepcopy(attacked)
                    with self.assertRaises(ContractValidationError) as caught:
                        decoder(candidate)
                    self.assertNotIn("private-token", str(caught.exception))
                    self.assertEqual(candidate, attacked)

            with self.subTest(metadata=metadata, writer="write_audit_log"):
                store = FileAuditLogStore(_paths.fresh_test_dir(f"audit-metadata-{index}"))
                candidate = copy.deepcopy(attacked)
                with self.assertRaises(ContractValidationError) as caught:
                    write_audit_log(store, **candidate)
                self.assertNotIn("private-token", str(caught.exception))
                self.assertEqual(candidate, attacked)
                self.assertEqual(list(store.base_dir.iterdir()), [])

    def test_internal_oauth_records_round_trip_and_keep_workspace_server_side(self) -> None:
        records = [
            ExternalIdentity(
                external_identity_id="extid_001",
                provider="google",
                issuer="https://accounts.google.com",
                subject="google-subject-001",
                user_id="user_001",
                email="person@example.test",
                email_verified=True,
                status="active",
                created_at=self.now_iso,
                last_authenticated_at=self.now_iso,
            ),
            OAuthInvitation(
                invitation_id="invite_001",
                normalized_email="person@example.test",
                workspace_id="workspace_001",
                role="member",
                status="pending",
                expires_at=self.later_iso,
                created_at=self.now_iso,
            ),
            OAuthClientAuthorization(
                oauth_client_authorization_id="clientauth_001",
                client_id="chatgpt_client",
                external_identity_id="extid_001",
                user_id="user_001",
                granted_scopes=("formowl.use",),
                default_workspace_id="workspace_001",
                created_at=self.now_iso,
            ),
            OAuthTransaction(
                transaction_id="oauthtx_001",
                google_state_hash="sha256:" + "1" * 64,
                encrypted_client_state="encrypted-state",
                google_nonce_hash="sha256:" + "2" * 64,
                client_id="chatgpt_client",
                redirect_uri="https://chatgpt.com/connector/oauth/callback",
                resource="https://auth.example.test/mcp",
                scopes=("formowl.use",),
                code_challenge="A" * 43,
                code_challenge_method="S256",
                created_at=self.now_iso,
                expires_at=self.later_iso,
            ),
            OAuthAuthorizationCode(
                code_hash="sha256:" + "3" * 64,
                transaction_id="oauthtx_001",
                user_id="user_001",
                external_identity_id="extid_001",
                client_id="chatgpt_client",
                redirect_uri="https://chatgpt.com/connector/oauth/callback",
                resource="https://auth.example.test/mcp",
                scopes=("formowl.use",),
                code_challenge="A" * 43,
                created_at=self.now_iso,
                expires_at=self.later_iso,
            ),
            OAuthTokenSession(
                token_session_id="oauthsid_001",
                user_id="user_001",
                external_identity_id="extid_001",
                oauth_client_authorization_id="clientauth_001",
                client_id="chatgpt_client",
                current_workspace_id="workspace_001",
                resource="https://auth.example.test/mcp",
                scopes=("formowl.use",),
                token_jti_hash="sha256:" + "4" * 64,
                issued_at=self.now_iso,
                expires_at=self.later_iso,
            ),
        ]

        for record in records:
            with self.subTest(record=type(record).__name__):
                self.assertEqual(
                    type(record).from_dict(record.to_dict()).to_dict(),
                    record.to_dict(),
                )

        principal = OAuthPrincipal(
            user_id="user_001",
            external_identity_id="extid_001",
            oauth_client_id="chatgpt_client",
            token_session_id="oauthsid_001",
            scopes=("formowl.use",),
            resource="https://auth.example.test/mcp",
        )
        self.assertNotIn("workspace", str(principal.to_dict()).lower())
        self.assertEqual(records[-1].current_workspace_id, "workspace_001")

    def test_external_identity_to_dict_is_exact_and_fails_closed_without_leak_or_side_effects(
        self,
    ) -> None:
        expected = {
            "external_identity_id": "extid_lineage_001",
            "provider": "google",
            "issuer": "https://accounts.google.com",
            "subject": "google-subject-lineage-001",
            "user_id": "user_lineage_001",
            "email": "lineage@example.test",
            "email_verified": True,
            "status": "active",
            "created_at": self.now_iso,
            "last_authenticated_at": self.later_iso,
        }
        identity = ExternalIdentity(**expected)

        payload = identity.to_dict()

        self.assertEqual(payload, expected)
        self.assertIsNot(payload, expected)
        payload["subject"] = "mutated-output"
        self.assertEqual(identity.subject, expected["subject"])

        secret = "private-token-value"
        string_fields = (
            "external_identity_id",
            "provider",
            "issuer",
            "subject",
            "user_id",
            "email",
            "status",
            "created_at",
            "last_authenticated_at",
        )
        runtime_type_cases: list[tuple[str, object, list[str]]] = []
        for field in string_fields:
            hook_calls: list[str] = []
            runtime_type_cases.append(
                (
                    field,
                    _CopySideEffectString(expected[field], secret, hook_calls),
                    hook_calls,
                )
            )
        email_verified_hook_calls: list[str] = []
        runtime_type_cases.append(
            (
                "email_verified",
                _CopySideEffectProbe(secret, email_verified_hook_calls),
                email_verified_hook_calls,
            )
        )

        for field, invalid_value, hook_calls in runtime_type_cases:
            invalid_identity = ExternalIdentity(**{**expected, field: invalid_value})
            original_state = dict(vars(invalid_identity))

            with self.subTest(runtime_type_field=field):
                with self.assertRaises(ContractValidationError) as caught:
                    invalid_identity.to_dict()

                self.assertEqual(str(caught.exception), "ExternalIdentity is invalid")
                self.assertNotIn(secret, str(caught.exception))
                self.assertEqual(vars(invalid_identity), original_state)
                self.assertEqual(hook_calls, [])

        legacy_hook_calls: list[str] = []
        malformed_email = "not-an-email"
        noncanonical_email = " Lineage@Example.TEST "
        invalid_cases = (
            ("malformed_email", {"email": malformed_email}, (malformed_email,)),
            (
                "noncanonical_email",
                {"email": noncanonical_email},
                (noncanonical_email,),
            ),
            ("provider_object", {"provider": {"access_token": secret}}, (secret,)),
            ("email_verified_string", {"email_verified": secret}, (secret,)),
            ("created_at_value", {"created_at": secret}, (secret,)),
            (
                "subject_deepcopy_probe",
                {"subject": _CopySideEffectProbe(secret, legacy_hook_calls)},
                (secret,),
            ),
        )
        for case_name, overrides, private_values in invalid_cases:
            invalid_identity = ExternalIdentity(**{**expected, **overrides})
            original_state = dict(vars(invalid_identity))

            with self.subTest(case=case_name):
                with self.assertRaises(ContractValidationError) as caught:
                    invalid_identity.to_dict()

                self.assertEqual(str(caught.exception), "ExternalIdentity is invalid")
                for private_value in private_values:
                    self.assertNotIn(private_value, str(caught.exception))
                self.assertEqual(vars(invalid_identity), original_state)
                self.assertEqual(legacy_hook_calls, [])

    def test_oauth_record_serializers_are_exact_and_fail_before_copy_hooks(self) -> None:
        records = (
            (
                OAuthInvitation(
                    invitation_id="invite_exact_001",
                    normalized_email="person@example.test",
                    workspace_id="workspace_exact_001",
                    role="member",
                    status="pending",
                    expires_at=self.later_iso,
                    created_at=self.now_iso,
                ),
                {
                    "invitation_id": "invite_exact_001",
                    "normalized_email": "person@example.test",
                    "workspace_id": "workspace_exact_001",
                    "role": "member",
                    "status": "pending",
                    "expires_at": self.later_iso,
                    "created_at": self.now_iso,
                    "intended_user_id": None,
                    "accepted_at": None,
                    "accepted_external_identity_id": None,
                },
                "invitation_id",
                None,
            ),
            (
                OAuthOwnerBootstrap(
                    workspace_id="workspace_exact_001",
                    normalized_email="person@example.test",
                    idempotency_key_hash="sha256:" + "0" * 64,
                    invitation_id="invite_exact_001",
                    operator_service_id="operator_exact_001",
                    status="pending",
                    created_at=self.now_iso,
                ),
                {
                    "workspace_id": "workspace_exact_001",
                    "normalized_email": "person@example.test",
                    "idempotency_key_hash": "sha256:" + "0" * 64,
                    "invitation_id": "invite_exact_001",
                    "operator_service_id": "operator_exact_001",
                    "status": "pending",
                    "created_at": self.now_iso,
                    "completed_at": None,
                },
                "operator_service_id",
                None,
            ),
            (
                OAuthClientAuthorization(
                    oauth_client_authorization_id="clientauth_exact_001",
                    client_id="chatgpt_client",
                    external_identity_id="extid_exact_001",
                    user_id="user_exact_001",
                    granted_scopes=("formowl.use",),
                    default_workspace_id="workspace_exact_001",
                    created_at=self.now_iso,
                ),
                {
                    "oauth_client_authorization_id": "clientauth_exact_001",
                    "client_id": "chatgpt_client",
                    "external_identity_id": "extid_exact_001",
                    "user_id": "user_exact_001",
                    "granted_scopes": ["formowl.use"],
                    "default_workspace_id": "workspace_exact_001",
                    "created_at": self.now_iso,
                    "revoked_at": None,
                },
                "client_id",
                "granted_scopes",
            ),
            (
                OAuthTransaction(
                    transaction_id="oauthtx_exact_001",
                    google_state_hash="sha256:" + "1" * 64,
                    encrypted_client_state="encrypted-state",
                    google_nonce_hash="sha256:" + "2" * 64,
                    client_id="chatgpt_client",
                    redirect_uri="https://chatgpt.com/connector/oauth/callback",
                    resource="https://auth.example.test/mcp",
                    scopes=("formowl.use",),
                    code_challenge="A" * 43,
                    code_challenge_method="S256",
                    created_at=self.now_iso,
                    expires_at=self.later_iso,
                ),
                {
                    "transaction_id": "oauthtx_exact_001",
                    "google_state_hash": "sha256:" + "1" * 64,
                    "encrypted_client_state": "encrypted-state",
                    "google_nonce_hash": "sha256:" + "2" * 64,
                    "client_id": "chatgpt_client",
                    "redirect_uri": "https://chatgpt.com/connector/oauth/callback",
                    "resource": "https://auth.example.test/mcp",
                    "scopes": ["formowl.use"],
                    "code_challenge": "A" * 43,
                    "code_challenge_method": "S256",
                    "created_at": self.now_iso,
                    "expires_at": self.later_iso,
                    "status": "pending",
                    "consumed_at": None,
                },
                "encrypted_client_state",
                "scopes",
            ),
            (
                OAuthAuthorizationCode(
                    code_hash="sha256:" + "3" * 64,
                    transaction_id="oauthtx_exact_001",
                    user_id="user_exact_001",
                    external_identity_id="extid_exact_001",
                    client_id="chatgpt_client",
                    redirect_uri="https://chatgpt.com/connector/oauth/callback",
                    resource="https://auth.example.test/mcp",
                    scopes=("formowl.use",),
                    code_challenge="A" * 43,
                    created_at=self.now_iso,
                    expires_at=self.later_iso,
                ),
                {
                    "code_hash": "sha256:" + "3" * 64,
                    "transaction_id": "oauthtx_exact_001",
                    "user_id": "user_exact_001",
                    "external_identity_id": "extid_exact_001",
                    "client_id": "chatgpt_client",
                    "redirect_uri": "https://chatgpt.com/connector/oauth/callback",
                    "resource": "https://auth.example.test/mcp",
                    "scopes": ["formowl.use"],
                    "code_challenge": "A" * 43,
                    "created_at": self.now_iso,
                    "expires_at": self.later_iso,
                    "consumed_at": None,
                },
                "transaction_id",
                "scopes",
            ),
            (
                OAuthTokenSession(
                    token_session_id="oauthsid_exact_001",
                    user_id="user_exact_001",
                    external_identity_id="extid_exact_001",
                    oauth_client_authorization_id="clientauth_exact_001",
                    client_id="chatgpt_client",
                    current_workspace_id="workspace_exact_001",
                    resource="https://auth.example.test/mcp",
                    scopes=("formowl.use",),
                    token_jti_hash="sha256:" + "4" * 64,
                    issued_at=self.now_iso,
                    expires_at=self.later_iso,
                ),
                {
                    "token_session_id": "oauthsid_exact_001",
                    "user_id": "user_exact_001",
                    "external_identity_id": "extid_exact_001",
                    "oauth_client_authorization_id": "clientauth_exact_001",
                    "client_id": "chatgpt_client",
                    "current_workspace_id": "workspace_exact_001",
                    "resource": "https://auth.example.test/mcp",
                    "scopes": ["formowl.use"],
                    "token_jti_hash": "sha256:" + "4" * 64,
                    "issued_at": self.now_iso,
                    "expires_at": self.later_iso,
                    "revoked_at": None,
                    "revocation_reason": None,
                },
                "token_session_id",
                "scopes",
            ),
            (
                OAuthPrincipal(
                    user_id="user_exact_001",
                    external_identity_id="extid_exact_001",
                    oauth_client_id="chatgpt_client",
                    token_session_id="oauthsid_exact_001",
                    scopes=("formowl.use",),
                    resource="https://auth.example.test/mcp",
                ),
                {
                    "user_id": "user_exact_001",
                    "external_identity_id": "extid_exact_001",
                    "oauth_client_id": "chatgpt_client",
                    "token_session_id": "oauthsid_exact_001",
                    "scopes": ["formowl.use"],
                    "resource": "https://auth.example.test/mcp",
                },
                "resource",
                "scopes",
            ),
        )
        secret = "private-serializer-secret"

        for record, expected, attacked_field, scope_field in records:
            record_type = type(record)
            with self.subTest(record=record_type.__name__, case="success"):
                payload = record.to_dict()
                self.assertEqual(payload, expected)
                self.assertEqual(set(payload), set(expected))
                self.assertIsNot(payload, expected)
                if scope_field is not None:
                    self.assertIs(type(payload[scope_field]), list)
                    payload[scope_field].append("formowl.read")
                    self.assertEqual(getattr(record, scope_field), ("formowl.use",))

            hook_calls: list[str] = []
            invalid_value = _CopySideEffectString(
                str(getattr(record, attacked_field)),
                secret,
                hook_calls,
            )
            invalid_record = record_type(
                **{
                    **vars(record),
                    attacked_field: invalid_value,
                }
            )
            original_state = dict(vars(invalid_record))

            with self.subTest(record=record_type.__name__, case="exact_runtime_type"):
                with self.assertRaises(ContractValidationError) as caught:
                    invalid_record.to_dict()

                self.assertEqual(
                    str(caught.exception),
                    f"{record_type.__name__} is invalid",
                )
                self.assertNotIn(secret, str(caught.exception))
                self.assertEqual(vars(invalid_record), original_state)
                self.assertEqual(hook_calls, [])

    def test_oauth_access_denied_requires_exact_types_and_revalidates_safe_payload(
        self,
    ) -> None:
        expected = {
            "error": "invalid_token",
            "reason_code": "token_expired",
            "http_status": 401,
        }
        denial = OAuthAccessDenied(**expected)
        payload = denial.to_safe_dict()
        self.assertEqual(payload, expected)
        self.assertIsNot(payload, expected)
        payload["reason_code"] = "mutated"
        self.assertEqual(denial.reason_code, "token_expired")

        secret = "private-denial-secret"
        exact_type_cases = (
            (
                "error",
                _CopySideEffectString("invalid_token", secret, []),
            ),
            (
                "reason_code",
                _CopySideEffectString("token_expired", secret, []),
            ),
            ("http_status", 401.0),
        )
        for field, invalid_value in exact_type_cases:
            hook_calls = getattr(invalid_value, "_calls", [])
            candidate = {**expected, field: invalid_value}
            with self.subTest(constructor_field=field):
                with self.assertRaises(ValueError) as caught:
                    OAuthAccessDenied(**candidate)
                self.assertNotIn(secret, str(caught.exception))
                self.assertEqual(hook_calls, [])

        mutated_cases = (
            (
                "error",
                _CopySideEffectString("invalid_token", secret, []),
            ),
            ("error", "unsafe_error"),
            (
                "reason_code",
                _CopySideEffectString("token_expired", secret, []),
            ),
            ("reason_code", "unsafe reason"),
            ("http_status", 401.0),
            ("http_status", 418),
        )
        for field, invalid_value in mutated_cases:
            hook_calls = getattr(invalid_value, "_calls", [])
            mutated = OAuthAccessDenied(**expected)
            setattr(mutated, field, invalid_value)
            original_state = dict(vars(mutated))
            with self.subTest(mutated_field=field, invalid_value=invalid_value):
                with self.assertRaises(ValueError) as caught:
                    mutated.to_safe_dict()
                self.assertNotIn(secret, str(caught.exception))
                self.assertEqual(vars(mutated), original_state)
                self.assertEqual(hook_calls, [])

    def test_oauth_model_helpers_are_exact_direct_and_non_mutating(self) -> None:
        payload = {
            "required": "value",
            "required_id": "record_001",
            "optional_id": None,
            "optional_timestamp": None,
        }
        copied = _mapping(payload, "OAuthRecord")
        self.assertEqual(copied, payload)
        self.assertIsNot(copied, payload)
        copied["required"] = "mutated"
        self.assertEqual(payload["required"], "value")

        mapping_sources = (
            ("mapping_proxy", MappingProxyType(dict(payload))),
            ("user_dict", UserDict(payload)),
            ("dict_subclass", type("OAuthRecordDictSubclass", (dict,), {})(payload)),
        )
        for source_name, source in mapping_sources:
            original = dict(source)
            with self.subTest(mapping_source=source_name):
                detached = _mapping(source, "OAuthRecord")
                self.assertIs(type(detached), dict)
                self.assertEqual(detached, original)
                detached["required"] = "mutated"
                self.assertEqual(dict(source), original)

        invitation_payload = OAuthInvitation(
            invitation_id="invite_mapping_001",
            normalized_email="person@example.test",
            workspace_id="workspace_mapping_001",
            role="member",
            status="pending",
            expires_at=self.later_iso,
            created_at=self.now_iso,
        ).to_dict()
        for source_name, source in (
            ("mapping_proxy", MappingProxyType(dict(invitation_payload))),
            ("user_dict", UserDict(invitation_payload)),
        ):
            original = dict(source)
            with self.subTest(public_from_dict_mapping=source_name):
                restored = OAuthInvitation.from_dict(source)
                rendered = restored.to_dict()
                self.assertEqual(rendered, original)
                rendered["role"] = "viewer"
                self.assertEqual(dict(source), original)

        self.assertIsNone(_required_string(payload, "required", "OAuthRecord"))
        self.assertIsNone(_required_safe_ids(payload, ("required_id",), "OAuthRecord"))
        self.assertIsNone(_optional_safe_ids(payload, ("optional_id",), "OAuthRecord"))
        self.assertIsNone(_validate_hash("sha256:" + "a" * 64, "OAuthRecord.hash"))
        self.assertIsNone(_validate_code_challenge("A" * 43, "OAuthRecord.code_challenge"))
        self.assertIsNone(_validate_timestamp(self.now_iso, "OAuthRecord.created_at"))
        self.assertIsNone(_optional_timestamps(payload, ("optional_timestamp",), "OAuthRecord"))

        secret = "private-helper-secret"
        mapping_calls: list[str] = []
        hostile_mapping = _MappingSideEffectProbe(secret, mapping_calls)
        with self.assertRaises(ContractValidationError) as caught:
            _mapping(hostile_mapping, "OAuthRecord")
        self.assertEqual(str(caught.exception), "OAuthRecord must be an object")
        self.assertNotIn(secret, str(caught.exception))
        self.assertTrue(mapping_calls)
        self.assertEqual(hostile_mapping._source_state, {"sentinel": "unchanged"})

        public_mapping_calls: list[str] = []
        hostile_public_mapping = _MappingSideEffectProbe(secret, public_mapping_calls)
        with self.assertRaises(ContractValidationError) as caught:
            OAuthInvitation.from_dict(hostile_public_mapping)
        self.assertEqual(str(caught.exception), "OAuthInvitation must be an object")
        self.assertNotIn(secret, str(caught.exception))
        self.assertTrue(public_mapping_calls)
        self.assertEqual(
            hostile_public_mapping._source_state,
            {"sentinel": "unchanged"},
        )

        helper_mapping_cases = (
            lambda value: _required_string(value, "required", "OAuthRecord"),
            lambda value: _required_safe_ids(
                value,
                ("required_id",),
                "OAuthRecord",
            ),
            lambda value: _optional_safe_ids(
                value,
                ("optional_id",),
                "OAuthRecord",
            ),
            lambda value: _optional_timestamps(
                value,
                ("optional_timestamp",),
                "OAuthRecord",
            ),
        )
        for index, helper in enumerate(helper_mapping_cases):
            calls: list[str] = []
            with self.subTest(hostile_mapping_helper=index):
                with self.assertRaises(ContractValidationError) as caught:
                    helper(_MappingSideEffectProbe(secret, calls))
                self.assertNotIn(secret, str(caught.exception))
                self.assertEqual(calls, [])

        collision_cases = (
            (
                "required_string",
                "required",
                lambda value: _required_string(value, "required", "OAuthRecord"),
            ),
            (
                "required_safe_ids",
                "required_id",
                lambda value: _required_safe_ids(
                    value,
                    ("required_id",),
                    "OAuthRecord",
                ),
            ),
            (
                "optional_safe_ids",
                "optional_id",
                lambda value: _optional_safe_ids(
                    value,
                    ("optional_id",),
                    "OAuthRecord",
                ),
            ),
            (
                "optional_timestamps",
                "optional_timestamp",
                lambda value: _optional_timestamps(
                    value,
                    ("optional_timestamp",),
                    "OAuthRecord",
                ),
            ),
        )
        sentinel = object()
        for helper_name, target_key, helper in collision_cases:
            calls: list[str] = []
            malicious_key = _HashCollisionKey(target_key, secret, calls)
            source = {malicious_key: sentinel}
            calls.clear()
            with self.subTest(malicious_dict_key_helper=helper_name):
                with self.assertRaises(ContractValidationError) as caught:
                    helper(source)
                self.assertEqual(
                    str(caught.exception),
                    "OAuth record validation input is invalid",
                )
                self.assertNotIn(secret, str(caught.exception))
                self.assertEqual(calls, [])
                items = tuple(source.items())
                self.assertEqual(len(items), 1)
                self.assertIs(items[0][0], malicious_key)
                self.assertIs(items[0][1], sentinel)

        exact_string_cases = (
            lambda value: _required_string(
                {"required": value},
                "required",
                "OAuthRecord",
            ),
            lambda value: _required_safe_ids(
                {"required_id": value},
                ("required_id",),
                "OAuthRecord",
            ),
            lambda value: _optional_safe_ids(
                {"optional_id": value},
                ("optional_id",),
                "OAuthRecord",
            ),
            lambda value: _validate_hash(value, "OAuthRecord.hash"),
            lambda value: _validate_code_challenge(
                value,
                "OAuthRecord.code_challenge",
            ),
            lambda value: _validate_timestamp(value, "OAuthRecord.created_at"),
            lambda value: _optional_timestamps(
                {"optional_timestamp": value},
                ("optional_timestamp",),
                "OAuthRecord",
            ),
        )
        exact_values = (
            "value",
            "record_001",
            "record_001",
            "sha256:" + "a" * 64,
            "A" * 43,
            self.now_iso,
            self.now_iso,
        )
        for index, (helper, value) in enumerate(zip(exact_string_cases, exact_values)):
            calls: list[str] = []
            invalid_value = _CopySideEffectString(value, secret, calls)
            with self.subTest(exact_string_helper=index):
                with self.assertRaises(ContractValidationError) as caught:
                    helper(invalid_value)
                self.assertNotIn(secret, str(caught.exception))
                self.assertEqual(calls, [])

        invalid_scalar_cases = (
            lambda: _required_string({"required": ""}, "required", "OAuthRecord"),
            lambda: _required_safe_ids(
                {"required_id": "unsafe id"},
                ("required_id",),
                "OAuthRecord",
            ),
            lambda: _optional_safe_ids(
                {"optional_id": "unsafe id"},
                ("optional_id",),
                "OAuthRecord",
            ),
            lambda: _validate_hash("sha256:not-a-hash", "OAuthRecord.hash"),
            lambda: _validate_code_challenge(
                "short",
                "OAuthRecord.code_challenge",
            ),
            lambda: _validate_timestamp(
                "2026-07-15T00:00:00",
                "OAuthRecord.created_at",
            ),
            lambda: _optional_timestamps(
                {"optional_timestamp": "not-a-timestamp"},
                ("optional_timestamp",),
                "OAuthRecord",
            ),
        )
        for index, invalid_case in enumerate(invalid_scalar_cases):
            with self.subTest(invalid_scalar_helper=index):
                with self.assertRaises(ContractValidationError):
                    invalid_case()

    def test_internal_oauth_record_decoders_reject_unknown_fields_without_leak_or_construction(
        self,
    ) -> None:
        records = [
            ExternalIdentity(
                external_identity_id="extid_001",
                provider="google",
                issuer="https://accounts.google.com",
                subject="google-subject-001",
                user_id="user_001",
                email="person@example.test",
                email_verified=True,
                status="active",
                created_at=self.now_iso,
                last_authenticated_at=self.now_iso,
            ),
            OAuthInvitation(
                invitation_id="invite_001",
                normalized_email="person@example.test",
                workspace_id="workspace_001",
                role="member",
                status="pending",
                expires_at=self.later_iso,
                created_at=self.now_iso,
            ),
            OAuthClientAuthorization(
                oauth_client_authorization_id="clientauth_001",
                client_id="chatgpt_client",
                external_identity_id="extid_001",
                user_id="user_001",
                granted_scopes=("formowl.use",),
                default_workspace_id="workspace_001",
                created_at=self.now_iso,
            ),
            OAuthTransaction(
                transaction_id="oauthtx_001",
                google_state_hash="sha256:" + "1" * 64,
                encrypted_client_state="encrypted-state",
                google_nonce_hash="sha256:" + "2" * 64,
                client_id="chatgpt_client",
                redirect_uri="https://chatgpt.com/connector/oauth/callback",
                resource="https://auth.example.test/mcp",
                scopes=("formowl.use",),
                code_challenge="A" * 43,
                code_challenge_method="S256",
                created_at=self.now_iso,
                expires_at=self.later_iso,
            ),
            OAuthAuthorizationCode(
                code_hash="sha256:" + "3" * 64,
                transaction_id="oauthtx_001",
                user_id="user_001",
                external_identity_id="extid_001",
                client_id="chatgpt_client",
                redirect_uri="https://chatgpt.com/connector/oauth/callback",
                resource="https://auth.example.test/mcp",
                scopes=("formowl.use",),
                code_challenge="A" * 43,
                created_at=self.now_iso,
                expires_at=self.later_iso,
            ),
            OAuthTokenSession(
                token_session_id="oauthsid_001",
                user_id="user_001",
                external_identity_id="extid_001",
                oauth_client_authorization_id="clientauth_001",
                client_id="chatgpt_client",
                current_workspace_id="workspace_001",
                resource="https://auth.example.test/mcp",
                scopes=("formowl.use",),
                token_jti_hash="sha256:" + "4" * 64,
                issued_at=self.now_iso,
                expires_at=self.later_iso,
            ),
        ]

        for record in records:
            record_type = type(record)
            valid_payload = record.to_dict()
            for unknown_key in ("access_token", 7):
                with self.subTest(record=record_type.__name__, unknown_key=unknown_key):
                    attacked = copy.deepcopy(valid_payload)
                    attacked[unknown_key] = "private-token"
                    original = copy.deepcopy(attacked)
                    with self.assertRaises(ContractValidationError) as caught:
                        record_type.from_dict(attacked)

                    self.assertEqual(
                        str(caught.exception),
                        f"{record_type.__name__} contains unsupported fields",
                    )
                    rendered_error = str(caught.exception).casefold()
                    self.assertNotIn("access_token", rendered_error)
                    self.assertNotIn("private-token", rendered_error)
                    self.assertEqual(attacked, original)

                    constructed: list[bool] = []

                    def reject_construction(_self: object, **_kwargs: object) -> None:
                        constructed.append(True)

                    probe_type = type(
                        f"{record_type.__name__}ConstructionProbe",
                        (record_type,),
                        {"__init__": reject_construction},
                    )
                    with self.assertRaises(ContractValidationError):
                        probe_type.from_dict(attacked)
                    self.assertEqual(constructed, [])

    def test_validate_scopes_accepts_non_empty_unique_list_and_tuple(self) -> None:
        for scopes in (["formowl.use"], ("formowl.use", "formowl.read")):
            with self.subTest(scopes=scopes):
                self.assertIsNone(_validate_scopes(scopes, "OAuthRecord.scopes"))

    def test_scope_bearing_oauth_decoders_reject_unhashable_items_without_leak_or_mutation(
        self,
    ) -> None:
        records_and_fields = (
            (
                OAuthClientAuthorization(
                    oauth_client_authorization_id="clientauth_001",
                    client_id="chatgpt_client",
                    external_identity_id="extid_001",
                    user_id="user_001",
                    granted_scopes=("formowl.use",),
                    default_workspace_id="workspace_001",
                    created_at=self.now_iso,
                ),
                "granted_scopes",
            ),
            (
                OAuthTransaction(
                    transaction_id="oauthtx_001",
                    google_state_hash="sha256:" + "1" * 64,
                    encrypted_client_state="encrypted-state",
                    google_nonce_hash="sha256:" + "2" * 64,
                    client_id="chatgpt_client",
                    redirect_uri="https://chatgpt.com/connector/oauth/callback",
                    resource="https://auth.example.test/mcp",
                    scopes=("formowl.use",),
                    code_challenge="A" * 43,
                    code_challenge_method="S256",
                    created_at=self.now_iso,
                    expires_at=self.later_iso,
                ),
                "scopes",
            ),
            (
                OAuthAuthorizationCode(
                    code_hash="sha256:" + "3" * 64,
                    transaction_id="oauthtx_001",
                    user_id="user_001",
                    external_identity_id="extid_001",
                    client_id="chatgpt_client",
                    redirect_uri="https://chatgpt.com/connector/oauth/callback",
                    resource="https://auth.example.test/mcp",
                    scopes=("formowl.use",),
                    code_challenge="A" * 43,
                    created_at=self.now_iso,
                    expires_at=self.later_iso,
                ),
                "scopes",
            ),
            (
                OAuthTokenSession(
                    token_session_id="oauthsid_001",
                    user_id="user_001",
                    external_identity_id="extid_001",
                    oauth_client_authorization_id="clientauth_001",
                    client_id="chatgpt_client",
                    current_workspace_id="workspace_001",
                    resource="https://auth.example.test/mcp",
                    scopes=("formowl.use",),
                    token_jti_hash="sha256:" + "4" * 64,
                    issued_at=self.now_iso,
                    expires_at=self.later_iso,
                ),
                "scopes",
            ),
        )
        invalid_scope_cases = (
            (
                "nested_object",
                [{"access_token": "private-token"}],
                "contains an invalid scope",
                ("access_token", "private-token"),
            ),
            (
                "nested_array",
                [["private-token"]],
                "contains an invalid scope",
                ("private-token",),
            ),
            (
                "duplicate",
                ["formowl.use", "formowl.use"],
                "must not contain duplicates",
                ("formowl.use",),
            ),
            (
                "unsafe_scope",
                ["unsafe scope private-token"],
                "contains an invalid scope",
                ("unsafe scope", "private-token"),
            ),
        )

        for record, scope_field in records_and_fields:
            record_type = type(record)
            for case_name, invalid_scopes, expected_suffix, forbidden_values in invalid_scope_cases:
                attacked = record.to_dict()
                attacked[scope_field] = copy.deepcopy(invalid_scopes)
                original = copy.deepcopy(attacked)

                with self.subTest(record=record_type.__name__, case=case_name):
                    with self.assertRaises(ContractValidationError) as caught:
                        record_type.from_dict(attacked)

                    rendered_error = str(caught.exception)
                    self.assertEqual(
                        rendered_error,
                        f"{record_type.__name__}.{scope_field} {expected_suffix}",
                    )
                    for forbidden_value in forbidden_values:
                        self.assertNotIn(forbidden_value, rendered_error)
                    self.assertEqual(attacked, original)

    def test_oauth_config_rejects_untrusted_urls_and_manual_connected_mode(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        config = OAuthBridgeConfig(
            issuer="https://auth.example.test",
            resource="https://auth.example.test/mcp",
            chatgpt_client_id="chatgpt_client",
            chatgpt_redirect_uri="https://chatgpt.com/connector/oauth/callback",
            google_client_id="google_client",
            google_client_secret="google_secret",
            google_redirect_uri="https://auth.example.test/oauth/google/callback",
            state_encryption_key=key,
        )
        self.assertTrue(config.to_public_dict()["secrets_redacted"])
        self.assertNotIn("google_secret", repr(config))
        self.assertNotIn(key, repr(config))

        assert_connected_auth_mode(auth_mode="oauth_google", connected=True)
        assert_connected_auth_mode(auth_mode="manual_trusted_internal", connected=False)
        with self.assertRaises(ContractValidationError):
            assert_connected_auth_mode(auth_mode="manual_trusted_internal", connected=True)

        invalid_urls = (
            ("issuer", "http://auth.example.test"),
            ("resource", "https://other.example.test/mcp"),
            ("chatgpt_redirect_uri", "https://chatgpt.com/*"),
            ("google_redirect_uri", "https://other.example.test/oauth/google/callback"),
        )
        base = {
            "issuer": config.issuer,
            "resource": config.resource,
            "chatgpt_client_id": config.chatgpt_client_id,
            "chatgpt_redirect_uri": config.chatgpt_redirect_uri,
            "google_client_id": config.google_client_id,
            "google_client_secret": "google_secret",
            "google_redirect_uri": config.google_redirect_uri,
            "state_encryption_key": key,
        }
        for field, value in invalid_urls:
            with self.subTest(field=field):
                with self.assertRaises(ContractValidationError):
                    OAuthBridgeConfig(**{**base, field: value})

        loopback = OAuthBridgeConfig(
            issuer="http://127.0.0.1:8765",
            resource="http://127.0.0.1:8765/mcp",
            chatgpt_client_id="inspector_client",
            chatgpt_redirect_uri="http://127.0.0.1:9000/callback",
            google_client_id="google_client",
            google_client_secret="google_secret",
            google_redirect_uri="http://127.0.0.1:8765/oauth/google/callback",
            state_encryption_key=key,
            allow_loopback_http=True,
        )
        self.assertTrue(loopback.allow_loopback_http)
        with self.assertRaises(ContractValidationError):
            OAuthBridgeConfig(**{**base, "issuer": "http://192.168.1.2"})

    def test_oauth_security_primitives_cover_rfc7636_and_secret_separation(self) -> None:
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        self.assertEqual(
            pkce_s256_challenge(verifier),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        )
        self.assertEqual(validate_pkce_verifier(verifier), verifier)
        with self.assertRaises(ContractValidationError):
            validate_pkce_verifier("short")

        value = generate_opaque_value(random_bytes=self.rng.bytes)
        self.assertEqual(len(value), 43)
        state_hash = hash_oauth_value("google_state", value)
        nonce_hash = hash_oauth_value("google_nonce", value)
        self.assertNotEqual(state_hash, nonce_hash)
        self.assertNotIn(value, state_hash)
        self.assertNotIn(value, nonce_hash)
        self.assertTrue(oauth_hash_matches("google_state", value, state_hash))
        self.assertFalse(oauth_hash_matches("google_state", value, None))
        safe_id = generate_safe_id("oauthtx", random_bytes=self.rng.bytes)
        self.assertTrue(safe_id.startswith("oauthtx_"))

        key = Fernet.generate_key().decode("ascii")
        encrypted = encrypt_client_state("chatgpt-client-state", key)
        self.assertNotIn("chatgpt-client-state", encrypted)
        self.assertEqual(decrypt_client_state(encrypted, key), "chatgpt-client-state")
        with self.assertRaises(ContractValidationError):
            decrypt_client_state(encrypted[:-2] + "xx", key)

        self.assertEqual(normalize_verified_email(" Person@Example.TEST "), "person@example.test")
        for invalid in ("missing-at", "a@b\n.test", "a@b.test\x00"):
            with self.assertRaises(ContractValidationError):
                normalize_verified_email(invalid)

        invalid_state_key = "invalid-state-key-must-remain-private"
        invalid_cases = (
            lambda: generate_opaque_value(random_bytes=self.rng.bytes, size=31),
            lambda: generate_opaque_value(random_bytes=lambda _size: b"short"),
            lambda: generate_safe_id("Unsafe-Prefix", random_bytes=self.rng.bytes),
            lambda: hash_oauth_value("Unsafe-Kind", value),
            lambda: hash_oauth_value("google_state", ""),
            lambda: oauth_hash_matches("Unsafe-Kind", value, state_hash),
            lambda: pkce_s256_challenge("short"),
            lambda: encrypt_client_state("", key),
            lambda: encrypt_client_state("private-client-state", invalid_state_key),
        )
        for invalid_case in invalid_cases:
            with self.subTest(invalid_case=invalid_case):
                with self.assertRaises((ContractValidationError, ValueError)) as caught:
                    invalid_case()
                rendered = str(caught.exception)
                self.assertNotIn("private-client-state", rendered)
                self.assertNotIn(invalid_state_key, rendered)


if __name__ == "__main__":
    unittest.main()
