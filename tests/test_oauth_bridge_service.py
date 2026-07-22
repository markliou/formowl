from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, tzinfo
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlparse
import unittest

from cryptography.fernet import Fernet

import _paths  # noqa: F401
from formowl_auth import (
    CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
    ExternalIdentity,
    FormOwlOAuthBridge,
    FormOwlSigningKeySet,
    FormOwlTokenCodec,
    GoogleIdentity,
    OAuthAccessDenied,
    OAuthBridgeConfig,
    OAuthClientAuthorization,
    OAuthInvitation,
    OAuthTokenSession,
)
from formowl_auth.security import hash_oauth_value, normalize_verified_email, pkce_s256_challenge
from formowl_contract import User, WorkspaceMember
from formowl_gateway.operator import OperatorDirectory
from oauth_harness import (
    DeterministicRng,
    FailureInjected,
    FakeClock,
    TransactionAwareMemoryRepository,
    generate_ephemeral_formowl_signing_key,
)


_VERIFIER = "v" * 43


class DetachedTimezone(tzinfo):
    def utcoffset(self, value: datetime | None) -> timedelta | None:
        del value
        return None


class StubGoogleClient:
    def __init__(self, identity: GoogleIdentity) -> None:
        self.identity = identity
        self.last_state: str | None = None
        self.last_nonce: str | None = None
        self.authenticated_codes: list[str] = []

    def build_authorization_url(self, *, google_state: str, google_nonce: str) -> str:
        self.last_state = google_state
        self.last_nonce = google_nonce
        return "https://accounts.google.test/authorize?" + urlencode(
            {"state": google_state, "nonce": google_nonce}
        )

    async def authenticate_code(
        self,
        google_code: str,
        *,
        expected_nonce_hash: str,
        now,
    ) -> GoogleIdentity:
        del now
        if self.last_nonce is None:
            raise AssertionError("authorization must start before the callback")
        if expected_nonce_hash != hash_oauth_value("google_nonce", self.last_nonce):
            raise AssertionError("callback nonce was not bound to the stored transaction")
        self.authenticated_codes.append(google_code)
        return self.identity


class BridgeFixture:
    def __init__(
        self,
        signing_key,
        *,
        seed: str = "oauth-service",
        chatgpt_client_id: str = "chatgpt-client",
        chatgpt_redirect_uri: str = "https://chatgpt.com/connector/oauth/callback",
    ) -> None:
        self.clock = FakeClock()
        self.repository = TransactionAwareMemoryRepository()
        self.rng = DeterministicRng(seed)
        self.config = OAuthBridgeConfig(
            issuer="https://auth.example.test",
            resource="https://auth.example.test/mcp",
            chatgpt_client_id=chatgpt_client_id,
            chatgpt_redirect_uri=chatgpt_redirect_uri,
            google_client_id="google-client",
            google_client_secret="google-secret",
            google_redirect_uri="https://auth.example.test/oauth/google/callback",
            state_encryption_key=Fernet.generate_key().decode("ascii"),
        )
        self.google_client = StubGoogleClient(
            GoogleIdentity(
                issuer="https://accounts.google.com",
                subject="google-subject-001",
                email="person@example.test",
                email_verified=True,
                display_name="Safe Person",
            )
        )
        self.authorized_owner_bootstrap_services = {
            "operator_service_001",
            "operator_service_002",
        }
        self.bridge = FormOwlOAuthBridge(
            config=self.config,
            repository=self.repository,
            google_client=self.google_client,  # type: ignore[arg-type]
            token_codec=FormOwlTokenCodec(
                issuer=self.config.issuer,
                client_id=self.config.chatgpt_client_id,
                key_set=FormOwlSigningKeySet([signing_key]),
            ),
            random_bytes=self.rng.bytes,
            owner_bootstrap_operator_authorizer=(
                self.authorized_owner_bootstrap_services.__contains__
            ),
        )

    def seed_owner(self, *, role: str = "owner") -> None:
        with self.repository.transaction() as unit:
            self.repository.insert_user(
                User(
                    user_id="owner_001",
                    display_name="Workspace Owner",
                    email="owner@example.test",
                    status="active",
                    created_at=self.clock.now_iso(),
                )
            )
            self.repository.insert_workspace_member(
                WorkspaceMember(
                    workspace_id="workspace_001",
                    user_id="owner_001",
                    role=role,
                ),
                created_at=self.clock.now_iso(),
            )
            unit.commit()

    def seed_invitation(
        self,
        *,
        email: str = "person@example.test",
        intended_user_id: str | None = None,
    ) -> None:
        invitation = OAuthInvitation(
            invitation_id="invite_001",
            normalized_email=normalize_verified_email(email),
            workspace_id="workspace_001",
            role="member",
            status="pending",
            expires_at=(self.clock.now() + timedelta(hours=1)).isoformat(),
            created_at=self.clock.now_iso(),
            intended_user_id=intended_user_id,
        )
        with self.repository.transaction() as unit:
            self.repository.insert_invitation(invitation)
            unit.commit()

    def bootstrap_owner(
        self,
        *,
        email: str = "person@example.test",
        idempotency_key: str = "bootstrap-key-001",
        operator_service_id: str = "operator_service_001",
    ) -> OAuthInvitation:
        return self.bridge.bootstrap_owner_invitation(
            workspace_id="workspace_001",
            email=email,
            expires_at=self.clock.now() + timedelta(hours=1),
            idempotency_key=idempotency_key,
            operator_service_id=operator_service_id,
            now=self.clock.now(),
        )

    def authorization_request(self, *, client_state: str = "chatgpt-state") -> dict[str, str]:
        return {
            "client_id": self.config.chatgpt_client_id,
            "redirect_uri": self.config.chatgpt_redirect_uri,
            "response_type": "code",
            "resource": self.config.resource,
            "scope": "formowl.use",
            "state": client_state,
            "code_challenge": pkce_s256_challenge(_VERIFIER),
            "code_challenge_method": "S256",
        }

    def start_authorization(self, *, client_state: str = "chatgpt-state") -> str:
        self.bridge.start_authorization(
            self.authorization_request(client_state=client_state),
            now=self.clock.now(),
        )
        if self.google_client.last_state is None:
            raise AssertionError("Google state was not generated")
        return self.google_client.last_state

    def complete_callback(self, state: str, *, google_code: str = "google-code") -> dict[str, str]:
        return asyncio.run(
            self.bridge.complete_google_callback(
                google_state=state,
                google_code=google_code,
                now=self.clock.now(),
            )
        )

    def complete_denial(self, state: str) -> dict[str, str]:
        return self.bridge.complete_google_denial(
            google_state=state,
            now=self.clock.now(),
        )

    def token_request(self, code: str) -> dict[str, str]:
        return {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.config.chatgpt_client_id,
            "redirect_uri": self.config.chatgpt_redirect_uri,
            "code_verifier": _VERIFIER,
            "resource": self.config.resource,
        }

    def authorize(self, *, client_state: str = "chatgpt-state") -> tuple[str, str]:
        state = self.start_authorization(client_state=client_state)
        callback = self.complete_callback(state)
        query = parse_qs(urlparse(callback["redirect_uri"]).query)
        return state, query["code"][0]

    def login(self) -> tuple[str, str, dict[str, object]]:
        state, code = self.authorize()
        token = self.bridge.exchange_authorization_code(
            self.token_request(code),
            now=self.clock.now(),
        )
        return state, code, token


class OAuthBridgeServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.signing_key = generate_ephemeral_formowl_signing_key(kid="service-test-key")

    def fixture(
        self,
        *,
        seed: str = "oauth-service",
        chatgpt_client_id: str = "chatgpt-client",
        chatgpt_redirect_uri: str = "https://chatgpt.com/connector/oauth/callback",
    ) -> BridgeFixture:
        return BridgeFixture(
            self.signing_key,
            seed=seed,
            chatgpt_client_id=chatgpt_client_id,
            chatgpt_redirect_uri=chatgpt_redirect_uri,
        )

    def test_start_authorization_rejects_detached_timezone_without_mutation(self) -> None:
        fixture = self.fixture(seed="detached-timezone")
        snapshot = fixture.repository.snapshot_bytes()
        detached_now = datetime(2026, 7, 14, 4, 0, tzinfo=DetachedTimezone())

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            fixture.bridge.start_authorization(
                fixture.authorization_request(),
                now=detached_now,
            )

        fixture.repository.assert_unchanged(snapshot)

    def test_discovery_only_rejects_every_oauth_state_writer_before_transaction(
        self,
    ) -> None:
        fixture = self.fixture(
            seed="discovery-only-writers",
            chatgpt_redirect_uri=CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
        )
        snapshot = fixture.repository.snapshot_bytes()
        operations = (
            (
                "provision_invitation",
                lambda: fixture.bridge.provision_invitation(
                    email="person@example.test",
                    workspace_id="workspace_001",
                    role="member",
                    invited_by_user_id="owner_001",
                    operator_service_id="operator_service_001",
                    expires_at=fixture.clock.now() + timedelta(hours=1),
                    now=fixture.clock.now(),
                ),
            ),
            (
                "bootstrap_owner_invitation",
                lambda: fixture.bridge.bootstrap_owner_invitation(
                    workspace_id="workspace_001",
                    email="person@example.test",
                    expires_at=fixture.clock.now() + timedelta(hours=1),
                    idempotency_key="discovery-bootstrap",
                    operator_service_id="operator_service_001",
                    now=fixture.clock.now(),
                ),
            ),
            (
                "start_authorization",
                lambda: fixture.bridge.start_authorization(
                    fixture.authorization_request(),
                    now=fixture.clock.now(),
                ),
            ),
            (
                "complete_google_callback",
                lambda: asyncio.run(
                    fixture.bridge.complete_google_callback(
                        google_state="discovery-google-state",
                        google_code="discovery-google-code",
                        now=fixture.clock.now(),
                    )
                ),
            ),
            (
                "complete_google_denial",
                lambda: fixture.bridge.complete_google_denial(
                    google_state="discovery-google-state",
                    now=fixture.clock.now(),
                ),
            ),
            (
                "exchange_authorization_code",
                lambda: fixture.bridge.exchange_authorization_code(
                    fixture.token_request("discovery-authorization-code"),
                    now=fixture.clock.now(),
                ),
            ),
            (
                "record_mcp_authorization_decision",
                lambda: fixture.bridge.record_mcp_authorization_decision(
                    principal=None,
                    request_id="request_discovery",
                    tool_call_id="tool_call_discovery",
                    tool_name="whoami",
                    workspace_id=None,
                    allowed=False,
                    reason_code="authentication_required",
                    now=fixture.clock.now(),
                ),
            ),
            (
                "record_oauth_denial",
                lambda: fixture.bridge.record_oauth_denial(
                    event="authorization",
                    reason_code="discovery_only",
                    now=fixture.clock.now(),
                    oauth_client_id=fixture.config.chatgpt_client_id,
                ),
            ),
            (
                "record_mcp_http_authentication_denial",
                lambda: fixture.bridge.record_mcp_http_authentication_denial(
                    raw_token=None,
                    request_id="request_discovery_http",
                    reason_code="authentication_required",
                    required_scope="formowl.use",
                    resource=fixture.config.resource,
                    now=fixture.clock.now(),
                ),
            ),
            (
                "revoke_token_session",
                lambda: fixture.bridge.revoke_token_session(
                    "oauthsid_discovery",
                    principal=object(),  # type: ignore[arg-type]
                    actor_context=object(),  # type: ignore[arg-type]
                    reason_code="discovery_only",
                    now=fixture.clock.now(),
                ),
            ),
            (
                "revoke_token_session_as_operator",
                lambda: fixture.bridge.revoke_token_session_as_operator(
                    "oauthsid_discovery",
                    operator_service_id="operator_service_001",
                    reason_code="discovery_only",
                    now=fixture.clock.now(),
                ),
            ),
        )

        with patch.object(
            fixture.repository,
            "transaction",
            side_effect=AssertionError("discovery-only reached repository transaction"),
        ) as transaction:
            for operation_name, operation in operations:
                with self.subTest(operation=operation_name):
                    with self.assertRaises(OAuthAccessDenied) as denied:
                        operation()
                    self.assertEqual(denied.exception.error, "access_denied")
                    self.assertEqual(denied.exception.reason_code, "discovery_only")
                    self.assertEqual(denied.exception.http_status, 403)

        transaction.assert_not_called()
        fixture.repository.assert_unchanged(snapshot)
        self.assertEqual(fixture.repository.write_operations, [])
        self.assertEqual(fixture.google_client.authenticated_codes, [])

    def test_predefined_client_id_is_exact_for_authorization_and_token_exchange(
        self,
    ) -> None:
        fixture = self.fixture(
            seed="exact-predefined-client",
            chatgpt_client_id="formowl-chatgpt-campaign-001",
        )
        fixture.seed_owner()
        fixture.seed_invitation()
        initial_snapshot = fixture.repository.snapshot_bytes()
        invalid_authorization = {
            **fixture.authorization_request(),
            "client_id": "formowl-chatgpt-campaign-002",
        }

        with self.assertRaises(OAuthAccessDenied) as denied:
            fixture.bridge.start_authorization(
                invalid_authorization,
                now=fixture.clock.now(),
            )

        self.assertEqual(denied.exception.reason_code, "oauth_client_invalid")
        fixture.repository.assert_unchanged(initial_snapshot)

        _, code = fixture.authorize()
        before_invalid_exchange = fixture.repository.snapshot_bytes()
        invalid_token_request = {
            **fixture.token_request(code),
            "client_id": "formowl-chatgpt-campaign-002",
        }

        with self.assertRaises(OAuthAccessDenied) as denied:
            fixture.bridge.exchange_authorization_code(
                invalid_token_request,
                now=fixture.clock.now(),
            )

        self.assertEqual(denied.exception.reason_code, "token_client_invalid")
        fixture.repository.assert_unchanged(before_invalid_exchange)
        self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])

        token = fixture.bridge.exchange_authorization_code(
            fixture.token_request(code),
            now=fixture.clock.now(),
        )

        self.assertEqual(token["token_type"], "Bearer")
        sessions = fixture.repository.list("oauth_token_sessions")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["client_id"], fixture.config.chatgpt_client_id)

    def test_direct_start_authorization_persists_hash_only_transaction_and_is_atomic(
        self,
    ) -> None:
        fixture = self.fixture(seed="direct-start-authorization")
        client_state = "sensitive-chatgpt-client-state"
        request = fixture.authorization_request(client_state=client_state)

        result = fixture.bridge.start_authorization(
            request,
            now=fixture.clock.now(),
        )

        self.assertEqual(set(result), {"authorization_url", "transaction_id"})
        self.assertEqual(
            fixture.google_client.last_state,
            parse_qs(urlparse(result["authorization_url"]).query)["state"][0],
        )
        self.assertEqual(
            fixture.google_client.last_nonce,
            parse_qs(urlparse(result["authorization_url"]).query)["nonce"][0],
        )
        transactions = fixture.repository.list("oauth_transactions")
        self.assertEqual(len(transactions), 1)
        transaction = transactions[0]
        self.assertEqual(transaction["transaction_id"], result["transaction_id"])
        self.assertEqual(transaction["status"], "pending")
        self.assertEqual(transaction["client_id"], fixture.config.chatgpt_client_id)
        self.assertEqual(transaction["redirect_uri"], fixture.config.chatgpt_redirect_uri)
        self.assertEqual(transaction["resource"], fixture.config.resource)
        self.assertEqual(transaction["scopes"], ["formowl.use"])
        self.assertEqual(transaction["code_challenge"], request["code_challenge"])
        self.assertEqual(transaction["code_challenge_method"], "S256")
        self.assertEqual(
            transaction["google_state_hash"],
            hash_oauth_value("google_state", str(fixture.google_client.last_state)),
        )
        self.assertEqual(
            transaction["google_nonce_hash"],
            hash_oauth_value("google_nonce", str(fixture.google_client.last_nonce)),
        )
        self.assertNotEqual(transaction["encrypted_client_state"], client_state)
        audits = fixture.repository.list("audit_log")
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit["action"], "oauth_authorization_started")
        self.assertEqual(audit["actor_type"], "external_unauthenticated")
        self.assertIsNone(audit.get("actor_user_id"))
        self.assertIsNone(audit.get("actor_service_id"))
        self.assertEqual(audit["target_type"], "oauth_transaction")
        self.assertEqual(audit["target_id"], transaction["transaction_id"])
        self.assertEqual(audit["session_id"], transaction["transaction_id"])
        self.assertEqual(audit["oauth_client_id"], fixture.config.chatgpt_client_id)
        self.assertEqual(audit["reason_code"], "authorization_started")
        self.assertEqual(audit["status"], "ok")
        self.assertEqual(
            audit["metadata"],
            {
                "event_stage": "authorization",
                "provider": "google",
                "scopes": ["formowl.use"],
            },
        )
        self.assertEqual(fixture.repository.list("users"), [])
        self.assertEqual(fixture.repository.list("workspace_members"), [])
        self.assertEqual(fixture.repository.list("external_identities"), [])
        self.assertEqual(fixture.repository.list("oauth_authorization_codes"), [])
        self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])
        persisted = str({"transaction": transaction, "audit": audit})
        for forbidden in (
            client_state,
            str(fixture.google_client.last_state),
            str(fixture.google_client.last_nonce),
            fixture.config.google_client_secret,
        ):
            self.assertNotIn(forbidden, persisted)

        invalid = self.fixture(seed="direct-start-invalid")
        invalid_request = invalid.authorization_request()
        invalid_request["client_id"] = "attacker-client"
        invalid_snapshot = invalid.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            invalid.bridge.start_authorization(
                invalid_request,
                now=invalid.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "oauth_client_invalid")
        invalid.repository.assert_unchanged(invalid_snapshot)
        self.assertIsNone(invalid.google_client.last_state)
        self.assertIsNone(invalid.google_client.last_nonce)

        failing = self.fixture(seed="direct-start-audit-failure")
        failing_snapshot = failing.repository.snapshot_bytes()
        failing.repository.inject_failure_at(2)
        with self.assertRaises(FailureInjected):
            failing.bridge.start_authorization(
                failing.authorization_request(),
                now=failing.clock.now(),
            )
        failing.repository.assert_unchanged(failing_snapshot)
        self.assertEqual(failing.repository.list("oauth_transactions"), [])
        self.assertEqual(failing.repository.list("audit_log"), [])

    def test_authorization_scope_rejects_non_space_separators_without_mutation(
        self,
    ) -> None:
        for case_index, scope in enumerate(
            ("formowl.use\t", "formowl.use\n"),
            start=1,
        ):
            with self.subTest(scope=repr(scope)):
                fixture = self.fixture(seed=f"authorization-scope-separator-{case_index}")
                request = fixture.authorization_request()
                request["scope"] = scope
                snapshot = fixture.repository.snapshot_bytes()

                with self.assertRaises(OAuthAccessDenied) as caught:
                    fixture.bridge.start_authorization(
                        request,
                        now=fixture.clock.now(),
                    )

                self.assertEqual(caught.exception.error, "invalid_scope")
                self.assertEqual(caught.exception.reason_code, "scope_invalid")
                fixture.repository.assert_unchanged(snapshot)
                self.assertIsNone(fixture.google_client.last_state)
                self.assertIsNone(fixture.google_client.last_nonce)

    def test_invitation_provisioning_requires_active_workspace_owner_and_is_atomic(self) -> None:
        fixture = self.fixture()
        fixture.seed_owner()

        invitation = fixture.bridge.provision_invitation(
            email=" Person@Example.TEST ",
            workspace_id="workspace_001",
            role="member",
            invited_by_user_id="owner_001",
            operator_service_id="operator_service_001",
            expires_at=fixture.clock.now() + timedelta(hours=1),
            now=fixture.clock.now(),
        )

        self.assertEqual(invitation.normalized_email, "person@example.test")
        self.assertEqual(fixture.repository.audit_event_count, 1)
        audit = fixture.repository.list("audit_log")[0]
        self.assertEqual(audit["action"], "oauth_invitation_create")
        self.assertEqual(audit["actor_type"], "service")
        self.assertEqual(audit["actor_service_id"], "operator_service_001")
        self.assertIsNone(audit.get("actor_user_id"))
        self.assertEqual(audit["workspace_id"], "workspace_001")
        self.assertEqual(audit["status"], "ok")
        self.assertEqual(audit["reason_code"], "invitation_created")
        self.assertEqual(
            audit["metadata"],
            {
                "event_stage": "invitation",
                "lineage_source": "owner_approval",
                "approval_user_id": "owner_001",
            },
        )

        denied = self.fixture(seed="member-inviter")
        denied.seed_owner(role="member")
        before = denied.repository.mutable_state_snapshot_bytes()
        audit_count = denied.repository.audit_event_count
        with self.assertRaises(OAuthAccessDenied) as caught:
            denied.bridge.provision_invitation(
                email="person@example.test",
                workspace_id="workspace_001",
                role="member",
                invited_by_user_id="owner_001",
                operator_service_id="operator_service_001",
                expires_at=denied.clock.now() + timedelta(hours=1),
                now=denied.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "invitation_owner_required")
        denied.repository.assert_mutable_state_unchanged(before)
        self.assertEqual(denied.repository.audit_event_count, audit_count + 1)
        denial_audit = denied.repository.list("audit_log")[-1]
        self.assertEqual(denial_audit["actor_type"], "service")
        self.assertEqual(denial_audit["actor_service_id"], "operator_service_001")
        self.assertEqual(denial_audit["status"], "denied")
        self.assertEqual(denial_audit["reason_code"], "invitation_owner_required")
        self.assertEqual(denial_audit["metadata"]["approval_user_id"], "owner_001")

    def test_invitation_operator_denial_and_audit_failure_are_fail_closed(self) -> None:
        unauthorized = self.fixture(seed="invitation-operator-denied")
        unauthorized.seed_owner()
        mutable_snapshot = unauthorized.repository.mutable_state_snapshot_bytes()
        audit_count = unauthorized.repository.audit_event_count

        with self.assertRaises(OAuthAccessDenied) as caught:
            unauthorized.bridge.provision_invitation(
                email="person@example.test",
                workspace_id="workspace_001",
                role="member",
                invited_by_user_id="owner_001",
                operator_service_id="operator_service_denied",
                expires_at=unauthorized.clock.now() + timedelta(hours=1),
                now=unauthorized.clock.now(),
            )

        self.assertEqual(caught.exception.error, "access_denied")
        self.assertEqual(caught.exception.reason_code, "operator_unauthorized")
        self.assertEqual(caught.exception.http_status, 403)
        unauthorized.repository.assert_mutable_state_unchanged(mutable_snapshot)
        self.assertEqual(unauthorized.repository.audit_event_count, audit_count + 1)
        audit = unauthorized.repository.list("audit_log")[-1]
        self.assertEqual(audit["actor_type"], "external_unauthenticated")
        self.assertIsNone(audit.get("actor_user_id"))
        self.assertIsNone(audit.get("actor_service_id"))
        self.assertEqual(audit["status"], "denied")
        self.assertEqual(audit["reason_code"], "operator_unauthorized")

        unauditable = self.fixture(seed="invitation-operator-audit-failure")
        unauditable.seed_owner()
        snapshot = unauditable.repository.snapshot_bytes()
        unauditable.repository.inject_failure_at(1)
        with self.assertRaises(OAuthAccessDenied) as unavailable:
            unauditable.bridge.provision_invitation(
                email="person@example.test",
                workspace_id="workspace_001",
                role="member",
                invited_by_user_id="owner_001",
                operator_service_id="operator_service_denied",
                expires_at=unauditable.clock.now() + timedelta(hours=1),
                now=unauditable.clock.now(),
            )
        self.assertEqual(unavailable.exception.error, "server_error")
        self.assertEqual(unavailable.exception.reason_code, "invitation_audit_unavailable")
        self.assertEqual(unavailable.exception.http_status, 500)
        unauditable.repository.assert_unchanged(snapshot)

        rollback = self.fixture(seed="invitation-persistence-audit-failure")
        rollback.seed_owner()
        snapshot = rollback.repository.snapshot_bytes()
        rollback.repository.inject_failure_at(2)
        with self.assertRaises(OAuthAccessDenied) as unavailable:
            rollback.bridge.provision_invitation(
                email="person@example.test",
                workspace_id="workspace_001",
                role="member",
                invited_by_user_id="owner_001",
                operator_service_id="operator_service_001",
                expires_at=rollback.clock.now() + timedelta(hours=1),
                now=rollback.clock.now(),
            )
        self.assertEqual(unavailable.exception.error, "server_error")
        self.assertEqual(
            unavailable.exception.reason_code,
            "invitation_persistence_unavailable",
        )
        self.assertEqual(unavailable.exception.http_status, 500)
        rollback.repository.assert_unchanged(snapshot)

    def test_owner_bootstrap_is_atomic_idempotent_and_creates_no_fake_user(self) -> None:
        fixture = self.fixture(seed="owner-bootstrap")

        invitation = fixture.bootstrap_owner()

        self.assertEqual(invitation.role, "owner")
        self.assertEqual(invitation.status, "pending")
        self.assertIsNone(invitation.intended_user_id)
        self.assertEqual(fixture.repository.list("users"), [])
        self.assertEqual(fixture.repository.list("workspace_members"), [])
        self.assertEqual(len(fixture.repository.list("oauth_owner_bootstraps")), 1)
        self.assertEqual(len(fixture.repository.list("oauth_invitations")), 1)
        audits = [
            audit
            for audit in fixture.repository.list("audit_log")
            if audit.get("action") == "oauth_owner_bootstrap_created"
        ]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["actor_type"], "service")
        self.assertEqual(audits[0]["actor_service_id"], "operator_service_001")
        self.assertIsNone(audits[0].get("actor_user_id"))
        self.assertEqual(audits[0]["metadata"], {"event_stage": "owner_bootstrap"})
        self.assertNotIn("bootstrap-key-001", str(audits[0]))
        self.assertNotIn("person@example.test", str(audits[0]))

        snapshot = fixture.repository.snapshot_bytes()
        retried = fixture.bootstrap_owner()
        self.assertEqual(retried, invitation)
        fixture.repository.assert_unchanged(snapshot)

        conflicts = (
            ({"email": "other@example.test"}, "owner_bootstrap_invitation_conflict"),
            ({"idempotency_key": "different-key"}, "owner_bootstrap_conflict"),
            ({"operator_service_id": "operator_service_002"}, "owner_bootstrap_conflict"),
        )
        for overrides, reason_code in conflicts:
            with self.subTest(overrides=overrides):
                conflict_snapshot = fixture.repository.snapshot_bytes()
                with self.assertRaises(OAuthAccessDenied) as caught:
                    fixture.bootstrap_owner(**overrides)
                self.assertEqual(caught.exception.reason_code, reason_code)
                fixture.repository.assert_unchanged(conflict_snapshot)

        for operator_service_id in ("operator_service_denied", "operator_service_001"):
            with self.subTest(operator_service_id=operator_service_id):
                if operator_service_id == "operator_service_001":
                    fixture.authorized_owner_bootstrap_services.remove(operator_service_id)
                authority_snapshot = fixture.repository.snapshot_bytes()
                with self.assertRaises(OAuthAccessDenied) as caught:
                    fixture.bootstrap_owner(operator_service_id=operator_service_id)
                self.assertEqual(
                    caught.exception.reason_code,
                    "owner_bootstrap_operator_unauthorized",
                )
                fixture.repository.assert_unchanged(authority_snapshot)

    def test_owner_bootstrap_rejects_nonempty_conflicts_and_rolls_back_every_write(
        self,
    ) -> None:
        nonempty = self.fixture(seed="owner-bootstrap-nonempty")
        nonempty.seed_owner()
        nonempty_snapshot = nonempty.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            nonempty.bootstrap_owner()
        self.assertEqual(caught.exception.reason_code, "owner_bootstrap_workspace_not_empty")
        nonempty.repository.assert_unchanged(nonempty_snapshot)

        incompatible = self.fixture(seed="owner-bootstrap-incompatible")
        with incompatible.repository.transaction() as unit:
            incompatible.repository.insert_invitation(
                OAuthInvitation(
                    invitation_id="invite_incompatible",
                    normalized_email="other@example.test",
                    workspace_id="workspace_001",
                    role="owner",
                    status="pending",
                    expires_at=(incompatible.clock.now() + timedelta(hours=1)).isoformat(),
                    created_at=incompatible.clock.now_iso(),
                )
            )
            unit.commit()
        incompatible_snapshot = incompatible.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            incompatible.bootstrap_owner()
        self.assertEqual(caught.exception.reason_code, "owner_bootstrap_invitation_conflict")
        incompatible.repository.assert_unchanged(incompatible_snapshot)

        for write_index in (1, 2, 3):
            with self.subTest(write_index=write_index):
                failing = self.fixture(seed=f"owner-bootstrap-write-{write_index}")
                snapshot = failing.repository.snapshot_bytes()
                failing.repository.inject_failure_at(write_index)
                with self.assertRaises(FailureInjected):
                    failing.bootstrap_owner()
                failing.repository.assert_unchanged(snapshot)
                self.assertEqual(failing.repository.list("users"), [])
                self.assertEqual(failing.repository.list("workspace_members"), [])

    def test_bootstrapped_owner_google_login_creates_real_user_and_completes_bootstrap(
        self,
    ) -> None:
        fixture = self.fixture(seed="owner-bootstrap-google-login")
        invitation = fixture.bootstrap_owner()
        self.assertEqual(fixture.repository.list("users"), [])

        state = fixture.start_authorization(client_state="bootstrap-client-state")
        callback = fixture.complete_callback(state)

        self.assertIn("code", parse_qs(urlparse(callback["redirect_uri"]).query))
        users = fixture.repository.list("users")
        memberships = fixture.repository.list("workspace_members")
        self.assertEqual(len(users), 1)
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0]["user_id"], users[0]["user_id"])
        self.assertEqual(memberships[0]["workspace_id"], "workspace_001")
        self.assertEqual(memberships[0]["role"], "owner")
        stored_invitation = fixture.repository.get_invitation(invitation.invitation_id)
        self.assertIsNotNone(stored_invitation)
        assert stored_invitation is not None
        self.assertEqual(stored_invitation.status, "accepted")
        bootstrap = fixture.repository.get_owner_bootstrap("workspace_001")
        self.assertIsNotNone(bootstrap)
        assert bootstrap is not None
        self.assertEqual(bootstrap.status, "completed")
        self.assertEqual(bootstrap.completed_at, fixture.clock.now_iso())

        completed_snapshot = fixture.repository.snapshot_bytes()
        retried = fixture.bootstrap_owner()
        self.assertEqual(retried.status, "accepted")
        self.assertEqual(retried.invitation_id, invitation.invitation_id)
        fixture.repository.assert_unchanged(completed_snapshot)

        with self.assertRaises(OAuthAccessDenied) as caught:
            fixture.bootstrap_owner(idempotency_key="different-after-completion")
        self.assertEqual(caught.exception.reason_code, "owner_bootstrap_conflict")
        fixture.repository.assert_unchanged(completed_snapshot)

    def test_bootstrap_completion_write_failure_rolls_back_google_identity_atomically(
        self,
    ) -> None:
        probe = self.fixture(seed="owner-bootstrap-completion-probe")
        probe.bootstrap_owner()
        probe_state = probe.start_authorization()
        operation_offset = len(probe.repository.write_operations)
        probe.complete_callback(probe_state)
        callback_operations = probe.repository.write_operations[operation_offset:]
        completion_write_index = callback_operations.index("complete_owner_bootstrap") + 1

        fixture = self.fixture(seed="owner-bootstrap-completion-failure")
        invitation = fixture.bootstrap_owner()
        state = fixture.start_authorization()
        snapshot = fixture.repository.snapshot_bytes()
        fixture.repository.inject_failure_at(completion_write_index)

        with self.assertRaises(FailureInjected):
            fixture.complete_callback(state)

        fixture.repository.assert_unchanged(snapshot)
        self.assertEqual(fixture.repository.list("users"), [])
        self.assertEqual(fixture.repository.list("workspace_members"), [])
        stored_invitation = fixture.repository.get_invitation(invitation.invitation_id)
        self.assertIsNotNone(stored_invitation)
        assert stored_invitation is not None
        self.assertEqual(stored_invitation.status, "pending")
        bootstrap = fixture.repository.get_owner_bootstrap("workspace_001")
        self.assertIsNotNone(bootstrap)
        assert bootstrap is not None
        self.assertEqual(bootstrap.status, "pending")

    def test_bootstrap_login_rejects_incompatible_state_without_partial_identity(
        self,
    ) -> None:
        fixture = self.fixture(seed="owner-bootstrap-invalid-state")
        fixture.bootstrap_owner()
        bootstrap_payload = fixture.repository.get(
            "oauth_owner_bootstraps",
            "workspace_001",
        )
        assert bootstrap_payload is not None
        bootstrap_payload["normalized_email"] = "other@example.test"
        with fixture.repository.transaction() as unit:
            fixture.repository.put(
                "oauth_owner_bootstraps",
                "workspace_001",
                bootstrap_payload,
                operation="seed_incompatible_owner_bootstrap",
            )
            unit.commit()

        state = fixture.start_authorization()
        snapshot = fixture.repository.snapshot_bytes()

        with self.assertRaises(OAuthAccessDenied) as caught:
            fixture.complete_callback(state)

        self.assertEqual(caught.exception.reason_code, "owner_bootstrap_state_invalid")
        fixture.repository.assert_unchanged(snapshot)
        self.assertEqual(fixture.repository.list("users"), [])
        self.assertEqual(fixture.repository.list("workspace_members"), [])
        self.assertEqual(fixture.repository.list("external_identities"), [])

    def test_first_login_binds_invitation_and_resolves_exact_actor_and_whoami(self) -> None:
        fixture = self.fixture()
        fixture.seed_owner()
        fixture.seed_invitation()

        _state, raw_code, token_response = fixture.login()
        principal = fixture.bridge.authenticate_access_token(
            str(token_response["access_token"]),
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )
        actor = fixture.bridge.resolve_actor_context(principal, now=fixture.clock.now())

        self.assertEqual(len(fixture.repository.list("users")), 2)
        self.assertEqual(len(fixture.repository.list("external_identities")), 1)
        self.assertEqual(len(fixture.repository.list("oauth_client_authorizations")), 1)
        self.assertEqual(len(fixture.repository.list("oauth_token_sessions")), 1)
        invitation = fixture.repository.get("oauth_invitations", "invite_001")
        self.assertEqual(invitation["status"], "accepted")
        self.assertNotIn("current_workspace_id", principal.to_dict())
        self.assertEqual(actor.current_workspace_id, "workspace_001")
        self.assertEqual(actor.current_workspace_role, "member")
        self.assertEqual(
            fixture.bridge.whoami_payload(actor),
            {
                "user_id": principal.user_id,
                "display_name": "Safe Person",
                "current_workspace": {
                    "workspace_id": "workspace_001",
                    "role": "member",
                },
                "auth_mode": "google_oidc_oauth",
            },
        )
        self.assertEqual(token_response["resource"], fixture.config.resource)
        self.assertEqual(token_response["scope"], "formowl.use")
        self.assertNotIn(raw_code, str(fixture.repository.list("audit_log")))
        self.assertNotIn(_VERIFIER, str(fixture.repository.list("audit_log")))
        self.assertNotIn("google-code", str(fixture.repository.list("audit_log")))
        self.assertTrue(
            {
                "oauth_external_identity_created",
                "oauth_invitation_accepted",
                "google_authentication_succeeded",
                "oauth_authorization_code_issued",
                "oauth_token_session_issued",
            }.issubset({row["action"] for row in fixture.repository.list("audit_log")})
        )

    def test_direct_whoami_payload_is_minimal_and_side_effect_free(self) -> None:
        fixture = self.fixture(seed="direct-whoami")
        fixture.seed_owner()
        fixture.seed_invitation()
        _state, _code, token_response = fixture.login()
        principal = fixture.bridge.authenticate_access_token(
            str(token_response["access_token"]),
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )
        actor = fixture.bridge.resolve_actor_context(principal, now=fixture.clock.now())
        snapshot = fixture.repository.snapshot_bytes()
        audit_count = fixture.repository.audit_event_count

        payload = fixture.bridge.whoami_payload(actor)

        self.assertEqual(
            payload,
            {
                "user_id": principal.user_id,
                "display_name": "Safe Person",
                "current_workspace": {
                    "workspace_id": "workspace_001",
                    "role": "member",
                },
                "auth_mode": "google_oidc_oauth",
            },
        )
        rendered = str(payload)
        for forbidden in (
            "email",
            "external_identity_id",
            "oauth_client_id",
            "oauth_token_session_id",
            "session_id",
            "active_grants",
            "pending_access_requests",
            str(token_response["access_token"]),
            "google-subject-001",
        ):
            self.assertNotIn(forbidden, rendered)
        fixture.repository.assert_unchanged(snapshot)
        self.assertEqual(fixture.repository.audit_event_count, audit_count)

        invalid_contexts = (
            replace(actor, auth_mode="manual_trusted_internal"),
            replace(actor, current_workspace_id=None),
            replace(actor, current_workspace_role=None),
        )
        for invalid_actor in invalid_contexts:
            with (
                self.subTest(invalid_actor=invalid_actor),
                self.assertRaises(OAuthAccessDenied) as caught,
            ):
                fixture.bridge.whoami_payload(invalid_actor)
            self.assertEqual(caught.exception.error, "access_denied")
            self.assertEqual(caught.exception.reason_code, "workspace_membership_inactive")
            self.assertEqual(caught.exception.http_status, 403)
            fixture.repository.assert_unchanged(snapshot)
            self.assertEqual(fixture.repository.audit_event_count, audit_count)

    def test_reconnect_same_subject_updates_profile_without_rebinding_user(self) -> None:
        fixture = self.fixture()
        fixture.seed_owner()
        fixture.seed_invitation()
        _state, _code, first_token = fixture.login()
        first_principal = fixture.bridge.authenticate_access_token(
            str(first_token["access_token"]),
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )
        fixture.google_client.identity = GoogleIdentity(
            issuer="https://accounts.google.com",
            subject="google-subject-001",
            email="renamed@example.test",
            email_verified=True,
            display_name="Renamed Person",
        )

        _second_state, second_code = fixture.authorize(client_state="second-state")
        second_token = fixture.bridge.exchange_authorization_code(
            fixture.token_request(second_code),
            now=fixture.clock.now(),
        )
        second_principal = fixture.bridge.authenticate_access_token(
            str(second_token["access_token"]),
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )

        self.assertEqual(second_principal.user_id, first_principal.user_id)
        self.assertEqual(
            second_principal.external_identity_id, first_principal.external_identity_id
        )
        self.assertEqual(len(fixture.repository.list("users")), 2)
        self.assertEqual(len(fixture.repository.list("external_identities")), 1)
        self.assertEqual(
            fixture.repository.get("users", first_principal.user_id)["email"],
            "renamed@example.test",
        )
        self.assertEqual(
            fixture.repository.get(
                "external_identities",
                first_principal.external_identity_id,
            )["email"],
            "renamed@example.test",
        )

    def test_different_subject_expiry_replay_and_code_replay_fail_without_partial_state(
        self,
    ) -> None:
        fixture = self.fixture()
        fixture.seed_owner()
        fixture.seed_invitation()
        first_state, first_code, _token = fixture.login()

        replay_snapshot = fixture.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            fixture.complete_callback(first_state, google_code="replayed-google-code")
        self.assertEqual(caught.exception.reason_code, "oauth_state_replayed")
        fixture.repository.assert_unchanged(replay_snapshot)

        code_snapshot = fixture.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            fixture.bridge.exchange_authorization_code(
                fixture.token_request(first_code),
                now=fixture.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "authorization_code_replayed")
        fixture.repository.assert_unchanged(code_snapshot)

        fixture.google_client.identity = GoogleIdentity(
            issuer="https://accounts.google.com",
            subject="different-google-subject",
            email="person@example.test",
            email_verified=True,
            display_name="Different Subject",
        )
        state = fixture.start_authorization(client_state="different-subject")
        different_subject_snapshot = fixture.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            fixture.complete_callback(state)
        self.assertEqual(caught.exception.reason_code, "invitation_missing")
        fixture.repository.assert_unchanged(different_subject_snapshot)

        expired = self.fixture(seed="expired-transaction")
        expired.seed_owner()
        expired.seed_invitation()
        expired_state = expired.start_authorization()
        expired.clock.advance(minutes=11)
        expired_snapshot = expired.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            expired.complete_callback(expired_state)
        self.assertEqual(caught.exception.reason_code, "oauth_transaction_expired")
        expired.repository.assert_unchanged(expired_snapshot)

        expired_code = self.fixture(seed="expired-code")
        expired_code.seed_owner()
        expired_code.seed_invitation()
        _state, code = expired_code.authorize()
        expired_code.clock.advance(minutes=6)
        expired_code_snapshot = expired_code.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            expired_code.bridge.exchange_authorization_code(
                expired_code.token_request(code),
                now=expired_code.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "authorization_code_expired")
        expired_code.repository.assert_unchanged(expired_code_snapshot)

    def test_callback_client_state_decryption_failures_leave_repository_byte_identical(
        self,
    ) -> None:
        wrong_key = self.fixture(seed="wrong-state-key")
        wrong_key.seed_owner()
        wrong_key.seed_invitation()
        wrong_key_state = wrong_key.start_authorization()
        wrong_config = replace(
            wrong_key.config,
            state_encryption_key=Fernet.generate_key().decode("ascii"),
        )
        wrong_bridge = FormOwlOAuthBridge(
            config=wrong_config,
            repository=wrong_key.repository,
            google_client=wrong_key.google_client,  # type: ignore[arg-type]
            token_codec=wrong_key.bridge.token_codec,
            random_bytes=wrong_key.rng.bytes,
        )
        wrong_key_snapshot = wrong_key.repository.snapshot_bytes()

        with self.assertRaises(OAuthAccessDenied) as caught:
            asyncio.run(
                wrong_bridge.complete_google_callback(
                    google_state=wrong_key_state,
                    google_code="must-not-reach-google",
                    now=wrong_key.clock.now(),
                )
            )

        self.assertEqual(caught.exception.reason_code, "oauth_client_state_invalid")
        wrong_key.repository.assert_unchanged(wrong_key_snapshot)
        self.assertEqual(wrong_key.google_client.authenticated_codes, [])

        tampered = self.fixture(seed="tampered-state-ciphertext")
        tampered.seed_owner()
        tampered.seed_invitation()
        tampered_state = tampered.start_authorization()
        transaction = tampered.repository.list("oauth_transactions")[0]
        transaction["encrypted_client_state"] = "tampered-" + transaction["encrypted_client_state"]
        tampered.repository.put(
            "oauth_transactions",
            transaction["transaction_id"],
            transaction,
            operation="test_tamper_encrypted_client_state",
        )
        tampered_snapshot = tampered.repository.snapshot_bytes()

        with self.assertRaises(OAuthAccessDenied) as caught:
            tampered.complete_callback(
                tampered_state,
                google_code="must-not-reach-google",
            )

        self.assertEqual(caught.exception.reason_code, "oauth_client_state_invalid")
        tampered.repository.assert_unchanged(tampered_snapshot)
        self.assertEqual(tampered.google_client.authenticated_codes, [])
        self.assertEqual(tampered.repository.list("external_identities"), [])
        self.assertEqual(tampered.repository.list("oauth_client_authorizations"), [])
        self.assertEqual(tampered.repository.list("oauth_authorization_codes"), [])
        self.assertEqual(tampered.repository.list("oauth_token_sessions"), [])
        self.assertEqual(
            tampered.repository.list("oauth_transactions")[0]["status"],
            "pending",
        )

    def test_callback_rejects_initial_transaction_config_binding_mismatches_before_google(
        self,
    ) -> None:
        persisted_cases = (
            ("client_id", "other-client"),
            ("redirect_uri", "https://evil.example/callback"),
            ("resource", "https://evil.example/mcp"),
            ("scopes", ["other.scope"]),
        )
        for field_name, field_value in persisted_cases:
            with self.subTest(source="persisted", field_name=field_name):
                fixture = self.fixture(seed=f"callback-initial-persisted-{field_name}")
                fixture.seed_owner()
                fixture.seed_invitation()
                state = fixture.start_authorization()
                transaction = fixture.repository.list("oauth_transactions")[0]
                transaction[field_name] = field_value
                fixture.repository.put(
                    "oauth_transactions",
                    transaction["transaction_id"],
                    transaction,
                    operation=f"test_misbind_callback_{field_name}",
                )
                snapshot = fixture.repository.snapshot_bytes()

                with self.assertRaises(OAuthAccessDenied) as caught:
                    fixture.complete_callback(
                        state,
                        google_code=f"must-not-reach-google-{field_name}",
                    )

                self.assertEqual(caught.exception.error, "server_error")
                self.assertEqual(
                    caught.exception.reason_code,
                    "oauth_transaction_binding_invalid",
                )
                self.assertEqual(caught.exception.http_status, 500)
                rendered = str(caught.exception)
                self.assertNotIn(state, rendered)
                self.assertNotIn(
                    f"must-not-reach-google-{field_name}",
                    rendered,
                )
                fixture.repository.assert_unchanged(snapshot)
                self.assertEqual(fixture.google_client.authenticated_codes, [])
                stored = fixture.repository.list("oauth_transactions")[0]
                self.assertEqual(stored["status"], "pending")
                self.assertIsNone(stored.get("consumed_at"))
                self.assertEqual(fixture.repository.list("external_identities"), [])
                self.assertEqual(
                    fixture.repository.list("oauth_client_authorizations"),
                    [],
                )
                self.assertEqual(fixture.repository.list("oauth_authorization_codes"), [])
                self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])

        method = self.fixture(seed="callback-initial-code-challenge-method")
        method.seed_owner()
        method.seed_invitation()
        method_state = method.start_authorization()
        method_hash = hash_oauth_value("google_state", method_state)
        method_transaction = method.repository.get_transaction_by_state_hash(method_hash)
        assert method_transaction is not None
        invalid_method = replace(method_transaction, code_challenge_method="plain")
        method_snapshot = method.repository.snapshot_bytes()

        with (
            patch.object(
                method.repository,
                "get_transaction_by_state_hash",
                return_value=invalid_method,
            ),
            self.assertRaises(OAuthAccessDenied) as caught,
        ):
            method.complete_callback(
                method_state,
                google_code="must-not-reach-google-code-challenge-method",
            )

        self.assertEqual(caught.exception.error, "server_error")
        self.assertEqual(
            caught.exception.reason_code,
            "oauth_transaction_binding_invalid",
        )
        self.assertEqual(caught.exception.http_status, 500)
        rendered = str(caught.exception)
        self.assertNotIn(method_state, rendered)
        self.assertNotIn(
            "must-not-reach-google-code-challenge-method",
            rendered,
        )
        method.repository.assert_unchanged(method_snapshot)
        self.assertEqual(method.google_client.authenticated_codes, [])
        stored = method.repository.list("oauth_transactions")[0]
        self.assertEqual(stored["status"], "pending")
        self.assertIsNone(stored.get("consumed_at"))
        self.assertEqual(method.repository.list("external_identities"), [])
        self.assertEqual(method.repository.list("oauth_client_authorizations"), [])
        self.assertEqual(method.repository.list("oauth_authorization_codes"), [])
        self.assertEqual(method.repository.list("oauth_token_sessions"), [])

        config_cases = (
            (
                "client_id",
                lambda config: replace(
                    config,
                    chatgpt_client_id="current-other-client",
                ),
            ),
            (
                "redirect_uri",
                lambda config: replace(
                    config,
                    chatgpt_redirect_uri="https://chatgpt.com/connector/oauth/other",
                ),
            ),
            (
                "resource",
                lambda config: replace(
                    config,
                    issuer="https://other-auth.example.test",
                    resource="https://other-auth.example.test/mcp",
                    google_redirect_uri=("https://other-auth.example.test/oauth/google/callback"),
                ),
            ),
        )
        for field_name, config_factory in config_cases:
            with self.subTest(source="current_config", field_name=field_name):
                fixture = self.fixture(seed=f"callback-initial-config-{field_name}")
                fixture.seed_owner()
                fixture.seed_invitation()
                state = fixture.start_authorization()
                bridge = FormOwlOAuthBridge(
                    config=config_factory(fixture.config),
                    repository=fixture.repository,
                    google_client=fixture.google_client,  # type: ignore[arg-type]
                    token_codec=fixture.bridge.token_codec,
                    random_bytes=fixture.rng.bytes,
                )
                snapshot = fixture.repository.snapshot_bytes()

                with self.assertRaises(OAuthAccessDenied) as caught:
                    asyncio.run(
                        bridge.complete_google_callback(
                            google_state=state,
                            google_code=f"must-not-reach-google-config-{field_name}",
                            now=fixture.clock.now(),
                        )
                    )

                self.assertEqual(caught.exception.error, "server_error")
                self.assertEqual(
                    caught.exception.reason_code,
                    "oauth_transaction_binding_invalid",
                )
                self.assertEqual(caught.exception.http_status, 500)
                rendered = str(caught.exception)
                self.assertNotIn(state, rendered)
                self.assertNotIn(
                    f"must-not-reach-google-config-{field_name}",
                    rendered,
                )
                fixture.repository.assert_unchanged(snapshot)
                self.assertEqual(fixture.google_client.authenticated_codes, [])
                stored = fixture.repository.list("oauth_transactions")[0]
                self.assertEqual(stored["status"], "pending")
                self.assertIsNone(stored.get("consumed_at"))
                self.assertEqual(fixture.repository.list("external_identities"), [])
                self.assertEqual(
                    fixture.repository.list("oauth_client_authorizations"),
                    [],
                )
                self.assertEqual(fixture.repository.list("oauth_authorization_codes"), [])
                self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])

    def test_callback_rejects_every_locked_transaction_immutable_field_change_atomically(
        self,
    ) -> None:
        race_cases = (
            ("transaction_id", "oauthtx_raced"),
            ("google_state_hash", "a" * 64),
            ("encrypted_client_state", "changed-ciphertext"),
            ("google_nonce_hash", "b" * 64),
            ("client_id", "race-client"),
            ("redirect_uri", "https://evil.example/race"),
            ("resource", "https://evil.example/race-mcp"),
            ("scopes", ("race.scope",)),
            ("code_challenge", "A" * 43),
            ("code_challenge_method", "plain"),
            ("created_at", "2026-07-12T03:59:00+00:00"),
            ("expires_at", "2026-07-12T05:00:00+00:00"),
        )
        for field_name, field_value in race_cases:
            with self.subTest(field_name=field_name):
                fixture = self.fixture(seed=f"callback-locked-race-{field_name}")
                fixture.seed_owner()
                fixture.seed_invitation()
                state = fixture.start_authorization()
                state_hash = hash_oauth_value("google_state", state)
                initial = fixture.repository.get_transaction_by_state_hash(state_hash)
                assert initial is not None
                locked = replace(initial, **{field_name: field_value})
                snapshot = fixture.repository.snapshot_bytes()

                def get_transaction(
                    requested_state_hash: str,
                    *,
                    for_update: bool = False,
                ):
                    self.assertEqual(requested_state_hash, state_hash)
                    return locked if for_update else initial

                with (
                    patch.object(
                        fixture.repository,
                        "get_transaction_by_state_hash",
                        side_effect=get_transaction,
                    ),
                    self.assertRaises(OAuthAccessDenied) as caught,
                ):
                    fixture.complete_callback(
                        state,
                        google_code=f"race-google-code-{field_name}",
                    )

                self.assertEqual(caught.exception.error, "server_error")
                self.assertEqual(
                    caught.exception.reason_code,
                    "oauth_transaction_binding_invalid",
                )
                self.assertEqual(caught.exception.http_status, 500)
                rendered = str(caught.exception)
                self.assertNotIn(state, rendered)
                self.assertNotIn(
                    f"race-google-code-{field_name}",
                    rendered,
                )
                self.assertEqual(
                    fixture.google_client.authenticated_codes,
                    [f"race-google-code-{field_name}"],
                )
                fixture.repository.assert_unchanged(snapshot)
                stored = fixture.repository.list("oauth_transactions")[0]
                self.assertEqual(stored["status"], "pending")
                self.assertIsNone(stored.get("consumed_at"))
                self.assertEqual(fixture.repository.list("external_identities"), [])
                self.assertEqual(
                    fixture.repository.list("oauth_client_authorizations"),
                    [],
                )
                self.assertEqual(fixture.repository.list("oauth_authorization_codes"), [])
                self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])

    def test_google_authorization_denial_fails_transaction_and_preserves_identity_state(
        self,
    ) -> None:
        fixture = self.fixture(seed="google-authorization-denial")
        fixture.seed_owner()
        fixture.seed_invitation()
        client_state = "chatgpt-denial-state"
        state = fixture.start_authorization(client_state=client_state)
        protected_tables = (
            "users",
            "workspace_members",
            "oauth_invitations",
            "external_identities",
            "oauth_client_authorizations",
            "oauth_authorization_codes",
            "oauth_token_sessions",
        )
        protected_before = {table: fixture.repository.list(table) for table in protected_tables}
        audit_before = fixture.repository.audit_event_count
        audit_ids_before = {audit["audit_log_id"] for audit in fixture.repository.list("audit_log")}

        result = fixture.complete_denial(state)

        parsed = urlparse(result["redirect_uri"])
        configured = urlparse(fixture.config.chatgpt_redirect_uri)
        self.assertEqual(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.fragment),
            (
                configured.scheme,
                configured.netloc,
                configured.path,
                configured.params,
                configured.fragment,
            ),
        )
        self.assertEqual(
            parse_qs(parsed.query),
            {"error": ["access_denied"], "state": [client_state]},
        )
        transaction = fixture.repository.list("oauth_transactions")[0]
        self.assertEqual(transaction["status"], "failed")
        self.assertEqual(transaction["consumed_at"], fixture.clock.now_iso())
        self.assertEqual(fixture.repository.audit_event_count, audit_before + 1)
        new_audits = [
            audit
            for audit in fixture.repository.list("audit_log")
            if audit["audit_log_id"] not in audit_ids_before
        ]
        self.assertEqual(len(new_audits), 1)
        audit = new_audits[0]
        self.assertEqual(audit["action"], "google_authentication_failed")
        self.assertEqual(audit["reason_code"], "google_authorization_denied")
        self.assertEqual(audit["target_type"], "oauth_transaction")
        self.assertEqual(audit["target_id"], transaction["transaction_id"])
        self.assertEqual(audit["session_id"], transaction["transaction_id"])
        self.assertEqual(audit["oauth_client_id"], fixture.config.chatgpt_client_id)
        self.assertEqual(
            audit["metadata"],
            {"event_stage": "google_callback", "provider": "google"},
        )
        self.assertEqual(
            {table: fixture.repository.list(table) for table in protected_tables},
            protected_before,
        )
        self.assertEqual(fixture.google_client.authenticated_codes, [])
        self.assertNotIn(state, str(audit))
        self.assertNotIn(client_state, str(audit))

    def test_google_authorization_denial_replay_invalid_state_and_write_failures_are_atomic(
        self,
    ) -> None:
        fixture = self.fixture(seed="google-denial-replay")
        state = fixture.start_authorization()
        fixture.complete_denial(state)
        replay_snapshot = fixture.repository.snapshot_bytes()

        with self.assertRaises(OAuthAccessDenied) as replayed:
            fixture.complete_denial(state)

        self.assertEqual(replayed.exception.reason_code, "oauth_state_replayed")
        fixture.repository.assert_unchanged(replay_snapshot)

        invalid = self.fixture(seed="google-denial-invalid-state")
        invalid.start_authorization()
        invalid_snapshot = invalid.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as rejected:
            invalid.complete_denial("wrong-google-state")
        self.assertEqual(rejected.exception.reason_code, "oauth_state_invalid")
        invalid.repository.assert_unchanged(invalid_snapshot)

        binding_cases = (
            ("redirect_uri", "https://evil.example/callback"),
            ("client_id", "other-client"),
            ("resource", "https://auth.example.test/other-resource"),
            ("scopes", ["other.scope"]),
        )
        for field_name, field_value in binding_cases:
            with self.subTest(field_name=field_name):
                misbound = self.fixture(seed=f"google-denial-misbound-{field_name}")
                misbound_state = misbound.start_authorization()
                transaction = misbound.repository.list("oauth_transactions")[0]
                transaction[field_name] = field_value
                misbound.repository.put(
                    "oauth_transactions",
                    transaction["transaction_id"],
                    transaction,
                    operation=f"test_misbind_denial_{field_name}",
                )
                snapshot = misbound.repository.snapshot_bytes()

                with self.assertRaises(OAuthAccessDenied) as binding_denial:
                    misbound.complete_denial(misbound_state)

                self.assertEqual(
                    binding_denial.exception.reason_code,
                    "oauth_transaction_binding_invalid",
                )
                misbound.repository.assert_unchanged(snapshot)
                self.assertEqual(misbound.google_client.authenticated_codes, [])

        for write_index in (1, 2):
            with self.subTest(write_index=write_index):
                failing = self.fixture(seed=f"google-denial-write-{write_index}")
                failing_state = failing.start_authorization()
                snapshot = failing.repository.snapshot_bytes()
                failing.repository.inject_failure_at(write_index)

                with self.assertRaises(FailureInjected):
                    failing.complete_denial(failing_state)

                failing.repository.assert_unchanged(snapshot)
                self.assertEqual(failing.google_client.authenticated_codes, [])
                self.assertEqual(
                    failing.repository.list("oauth_transactions")[0]["status"],
                    "pending",
                )

    def test_revoked_or_disabled_binding_and_removed_membership_fail_closed(self) -> None:
        cases = (
            ("token", "token_session_revoked"),
            ("client", "client_authorization_revoked"),
            ("identity", "external_identity_disabled"),
            ("user", "formowl_user_disabled"),
        )
        for mutation, reason_code in cases:
            with self.subTest(mutation=mutation):
                fixture = self.fixture(seed=f"revocation-{mutation}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, _code, token = fixture.login()
                session = fixture.repository.list("oauth_token_sessions")[0]
                if mutation == "token":
                    principal = fixture.bridge.authenticate_access_token(
                        str(token["access_token"]),
                        required_scope="formowl.use",
                        resource=fixture.config.resource,
                        now=fixture.clock.now(),
                    )
                    actor_context = fixture.bridge.resolve_actor_context(
                        principal,
                        now=fixture.clock.now(),
                    )
                    fixture.bridge.revoke_token_session(
                        session["token_session_id"],
                        principal=principal,
                        actor_context=actor_context,
                        reason_code="operator_revoked",
                        now=fixture.clock.now(),
                    )
                elif mutation == "client":
                    authorization = fixture.repository.get(
                        "oauth_client_authorizations",
                        session["oauth_client_authorization_id"],
                    )
                    authorization["revoked_at"] = fixture.clock.now_iso()
                    fixture.repository.put(
                        "oauth_client_authorizations",
                        authorization["oauth_client_authorization_id"],
                        authorization,
                        operation="test_revoke_client",
                    )
                elif mutation == "identity":
                    identity = fixture.repository.get(
                        "external_identities",
                        session["external_identity_id"],
                    )
                    identity["status"] = "disabled"
                    fixture.repository.put(
                        "external_identities",
                        identity["external_identity_id"],
                        identity,
                        operation="test_disable_identity",
                    )
                else:
                    user = fixture.repository.get("users", session["user_id"])
                    user["status"] = "disabled"
                    fixture.repository.put(
                        "users",
                        user["user_id"],
                        user,
                        operation="test_disable_user",
                    )
                with self.assertRaises(OAuthAccessDenied) as caught:
                    fixture.bridge.authenticate_access_token(
                        str(token["access_token"]),
                        required_scope="formowl.use",
                        resource=fixture.config.resource,
                        now=fixture.clock.now(),
                    )
                self.assertEqual(caught.exception.reason_code, reason_code)

        membership = self.fixture(seed="removed-membership")
        membership.seed_owner()
        membership.seed_invitation()
        _state, _code, token = membership.login()
        principal = membership.bridge.authenticate_access_token(
            str(token["access_token"]),
            required_scope="formowl.use",
            resource=membership.config.resource,
            now=membership.clock.now(),
        )
        key = membership.repository._workspace_member_key(
            principal.user_id,
            "workspace_001",
        )
        row = membership.repository.get("workspace_members", key)
        row["removed_at"] = membership.clock.now_iso()
        membership.repository.put(
            "workspace_members",
            key,
            row,
            operation="test_remove_membership",
        )
        with self.assertRaises(OAuthAccessDenied) as caught:
            membership.bridge.resolve_actor_context(principal, now=membership.clock.now())
        self.assertEqual(caught.exception.reason_code, "workspace_membership_inactive")

    def test_operator_membership_removal_survives_restart_and_requires_relink(self) -> None:
        fixture = self.fixture(seed="operator-membership-lifecycle")
        fixture.seed_owner()
        fixture.bridge.provision_invitation(
            email="person@example.test",
            workspace_id="workspace_001",
            role="member",
            invited_by_user_id="owner_001",
            operator_service_id="operator_service_001",
            expires_at=fixture.clock.now() + timedelta(hours=1),
            now=fixture.clock.now(),
        )
        _state, _code, first_token = fixture.login()
        first_principal = fixture.bridge.authenticate_access_token(
            str(first_token["access_token"]),
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )

        directory = OperatorDirectory(
            repository=fixture.repository,
            expected_operator_service_id="operator_service_001",
        )
        removed = directory.remove_workspace_member(
            user_id=first_principal.user_id,
            workspace_id="workspace_001",
            operator_service_id="operator_service_001",
            now=fixture.clock.now(),
        )
        self.assertTrue(removed["membership_removed"])
        old_session = fixture.repository.get_token_session(first_principal.token_session_id)
        self.assertIsNotNone(old_session)
        self.assertEqual(old_session.revocation_reason, "workspace_membership_removed")

        with self.assertRaises(OAuthAccessDenied) as removed_denial:
            fixture.bridge.authenticate_access_token(
                str(first_token["access_token"]),
                required_scope="formowl.use",
                resource=fixture.config.resource,
                now=fixture.clock.now(),
            )
        self.assertEqual(removed_denial.exception.reason_code, "token_session_revoked")

        restarted_bridge = FormOwlOAuthBridge(
            config=fixture.config,
            repository=fixture.repository,
            google_client=fixture.google_client,  # type: ignore[arg-type]
            token_codec=FormOwlTokenCodec(
                issuer=fixture.config.issuer,
                client_id=fixture.config.chatgpt_client_id,
                key_set=FormOwlSigningKeySet([self.signing_key]),
            ),
            random_bytes=DeterministicRng("operator-membership-restart").bytes,
            owner_bootstrap_operator_authorizer=(
                fixture.authorized_owner_bootstrap_services.__contains__
            ),
        )
        with self.assertRaises(OAuthAccessDenied) as restart_denial:
            restarted_bridge.authenticate_access_token(
                str(first_token["access_token"]),
                required_scope="formowl.use",
                resource=fixture.config.resource,
                now=fixture.clock.now(),
            )
        self.assertEqual(restart_denial.exception.reason_code, "token_session_revoked")

        restarted_directory = OperatorDirectory(
            repository=fixture.repository,
            expected_operator_service_id="operator_service_001",
        )
        restored = restarted_directory.restore_workspace_member(
            user_id=first_principal.user_id,
            workspace_id="workspace_001",
            operator_service_id="operator_service_001",
            now=fixture.clock.now() + timedelta(minutes=1),
        )
        self.assertTrue(restored["membership_restored"])
        with self.assertRaises(OAuthAccessDenied) as restored_old_session:
            restarted_bridge.authenticate_access_token(
                str(first_token["access_token"]),
                required_scope="formowl.use",
                resource=fixture.config.resource,
                now=fixture.clock.now(),
            )
        self.assertEqual(
            restored_old_session.exception.reason_code,
            "token_session_revoked",
        )

        fixture.bridge = restarted_bridge
        _new_state, _new_code, second_token = fixture.login()
        second_principal = restarted_bridge.authenticate_access_token(
            str(second_token["access_token"]),
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )
        actor = restarted_bridge.resolve_actor_context(
            second_principal,
            now=fixture.clock.now(),
        )

        self.assertEqual(second_principal.user_id, first_principal.user_id)
        self.assertEqual(
            second_principal.external_identity_id,
            first_principal.external_identity_id,
        )
        self.assertNotEqual(
            second_principal.token_session_id,
            first_principal.token_session_id,
        )
        self.assertEqual(actor.current_workspace_id, "workspace_001")
        self.assertEqual(actor.current_workspace_role, "member")
        sessions = fixture.repository.list_token_sessions(
            first_principal.user_id,
            "workspace_001",
        )
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sum(session.revoked_at is None for session in sessions), 1)
        lifecycle_audits = [
            row
            for row in fixture.repository.list("audit_log")
            if row["action"]
            in {
                "operator_workspace_member_remove",
                "operator_workspace_member_restore",
            }
        ]
        self.assertEqual(len(lifecycle_audits), 2)
        self.assertTrue(all(row["actor_type"] == "service" for row in lifecycle_audits))
        self.assertTrue(
            all(row["actor_service_id"] == "operator_service_001" for row in lifecycle_audits)
        )

    def test_client_authorization_binding_is_revalidated_for_token_and_actor_context(
        self,
    ) -> None:
        successful = self.fixture(seed="authorization-binding-success")
        successful.seed_owner()
        successful.seed_invitation()
        _state, _code, token = successful.login()
        success_snapshot = successful.repository.snapshot_bytes()
        principal = successful.bridge.authenticate_access_token(
            str(token["access_token"]),
            required_scope="formowl.use",
            resource=successful.config.resource,
            now=successful.clock.now(),
        )
        actor = successful.bridge.resolve_actor_context(
            principal,
            now=successful.clock.now(),
        )
        self.assertEqual(actor.current_workspace_id, "workspace_001")
        self.assertNotIn("current_workspace_id", principal.to_dict())
        successful.repository.assert_unchanged(success_snapshot)

        mutations = (
            ("oauth_client_authorization_id", "clientauth_tampered"),
            ("client_id", "other-client"),
            ("user_id", "other-user"),
            ("external_identity_id", "extid_other"),
            ("granted_scopes", ["other.scope"]),
            ("default_workspace_id", "workspace_other"),
        )
        for field_name, value in mutations:
            with self.subTest(field_name=field_name):
                fixture = self.fixture(seed=f"authorization-binding-{field_name}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, _code, token = fixture.login()
                principal = fixture.bridge.authenticate_access_token(
                    str(token["access_token"]),
                    required_scope="formowl.use",
                    resource=fixture.config.resource,
                    now=fixture.clock.now(),
                )
                session = fixture.repository.list("oauth_token_sessions")[0]
                authorization_key = session["oauth_client_authorization_id"]
                authorization = fixture.repository.get(
                    "oauth_client_authorizations",
                    authorization_key,
                )
                authorization[field_name] = value
                fixture.repository.put(
                    "oauth_client_authorizations",
                    authorization_key,
                    authorization,
                    operation=f"test_misbind_{field_name}",
                )
                snapshot = fixture.repository.snapshot_bytes()
                audit_count = fixture.repository.audit_event_count

                with self.assertRaises(OAuthAccessDenied) as authenticated:
                    fixture.bridge.authenticate_access_token(
                        str(token["access_token"]),
                        required_scope="formowl.use",
                        resource=fixture.config.resource,
                        now=fixture.clock.now(),
                    )
                self.assertEqual(
                    authenticated.exception.reason_code,
                    "client_authorization_binding_invalid",
                )
                with self.assertRaises(OAuthAccessDenied) as resolved:
                    fixture.bridge.resolve_actor_context(
                        principal,
                        now=fixture.clock.now(),
                    )
                self.assertEqual(
                    resolved.exception.reason_code,
                    "client_authorization_binding_invalid",
                )
                fixture.repository.assert_unchanged(snapshot)
                self.assertEqual(fixture.repository.audit_event_count, audit_count)

    def test_code_exchange_rejects_each_misbound_authorization_field_atomically(self) -> None:
        cases = (
            ("client_id", "other-client", "authorization_client_mismatch"),
            ("user_id", "other-user", "authorization_user_mismatch"),
            (
                "external_identity_id",
                "extid_other",
                "authorization_identity_mismatch",
            ),
            ("granted_scopes", ["other.scope"], "authorization_scope_mismatch"),
        )
        for field_name, value, reason_code in cases:
            with self.subTest(field_name=field_name):
                fixture = self.fixture(seed=f"code-binding-{field_name}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, code = fixture.authorize()
                authorization_payload = fixture.repository.list("oauth_client_authorizations")[0]
                authorization_payload[field_name] = value
                misbound = OAuthClientAuthorization.from_dict(authorization_payload)
                snapshot = fixture.repository.snapshot_bytes()
                audit_count = fixture.repository.audit_event_count

                with patch.object(
                    fixture.repository,
                    "get_client_authorization",
                    return_value=misbound,
                ):
                    with self.assertRaises(OAuthAccessDenied) as caught:
                        fixture.bridge.exchange_authorization_code(
                            fixture.token_request(code),
                            now=fixture.clock.now(),
                        )

                self.assertEqual(caught.exception.reason_code, reason_code)
                fixture.repository.assert_unchanged(snapshot)
                self.assertEqual(fixture.repository.audit_event_count, audit_count)
                self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])
                authorization_code = fixture.repository.list("oauth_authorization_codes")[0]
                self.assertIsNone(authorization_code.get("consumed_at"))

    def test_pkce_verifier_matrix_fails_closed_before_code_consumption(self) -> None:
        fixture = self.fixture(seed="pkce-verifier-matrix")
        fixture.seed_owner()
        fixture.seed_invitation()
        _state, code = fixture.authorize()
        cases = (
            ("x" * 42, "pkce_verifier_invalid"),
            ("x" * 129, "pkce_verifier_invalid"),
            ("x" * 42 + "!", "pkce_verifier_invalid"),
            ("x" * 42 + "密", "pkce_verifier_invalid"),
            ("w" * 43, "pkce_verifier_mismatch"),
        )
        for verifier, reason_code in cases:
            with self.subTest(reason_code=reason_code, verifier_length=len(verifier)):
                request = fixture.token_request(code)
                request["code_verifier"] = verifier
                snapshot = fixture.repository.snapshot_bytes()
                audit_count = fixture.repository.audit_event_count

                with self.assertRaises(OAuthAccessDenied) as caught:
                    fixture.bridge.exchange_authorization_code(
                        request,
                        now=fixture.clock.now(),
                    )

                self.assertEqual(caught.exception.error, "invalid_grant")
                self.assertEqual(caught.exception.reason_code, reason_code)
                self.assertNotIn(verifier, str(caught.exception))
                self.assertNotIn(code, str(caught.exception))
                fixture.repository.assert_unchanged(snapshot)
                self.assertEqual(fixture.repository.audit_event_count, audit_count)
                self.assertIsNone(
                    fixture.repository.list("oauth_authorization_codes")[0].get("consumed_at")
                )
                self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])

        token = fixture.bridge.exchange_authorization_code(
            fixture.token_request(code),
            now=fixture.clock.now(),
        )
        self.assertEqual(token["token_type"], "Bearer")

    def test_token_exchange_locks_membership_before_session_issuance(self) -> None:
        fixture = self.fixture(seed="token-membership-lock")
        fixture.seed_owner()
        fixture.seed_invitation()
        _state, code = fixture.authorize()
        lock_observations: list[tuple[bool, int, object]] = []
        original_get_membership = fixture.repository.get_active_workspace_member

        def get_locked_membership(
            user_id: str,
            workspace_id: str,
            *,
            for_update: bool = False,
        ):
            stored_code = fixture.repository.list("oauth_authorization_codes")[0]
            lock_observations.append(
                (
                    for_update,
                    len(fixture.repository.list("oauth_token_sessions")),
                    stored_code.get("consumed_at"),
                )
            )
            return original_get_membership(
                user_id,
                workspace_id,
                for_update=for_update,
            )

        with patch.object(
            fixture.repository,
            "get_active_workspace_member",
            side_effect=get_locked_membership,
        ):
            token = fixture.bridge.exchange_authorization_code(
                fixture.token_request(code),
                now=fixture.clock.now(),
            )

        self.assertEqual(lock_observations, [(True, 0, None)])
        self.assertEqual(token["token_type"], "Bearer")
        sessions = fixture.repository.list("oauth_token_sessions")
        self.assertEqual(len(sessions), 1)
        self.assertIsNone(sessions[0].get("revoked_at"))
        self.assertIsNotNone(fixture.repository.list("oauth_authorization_codes")[0]["consumed_at"])
        self.assertEqual(
            [
                audit["action"]
                for audit in fixture.repository.list("audit_log")
                if audit["action"] == "oauth_token_session_issued"
            ],
            ["oauth_token_session_issued"],
        )

    def test_external_identity_user_and_google_issuer_binding_is_revalidated(self) -> None:
        mutations = (
            ("user_id", "owner_001"),
            ("issuer", "https://issuer.example.test"),
        )
        for field_name, value in mutations:
            with self.subTest(path="token_and_actor", field_name=field_name):
                fixture = self.fixture(seed=f"identity-binding-{field_name}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, _code, token = fixture.login()
                principal = fixture.bridge.authenticate_access_token(
                    str(token["access_token"]),
                    required_scope="formowl.use",
                    resource=fixture.config.resource,
                    now=fixture.clock.now(),
                )
                identity = fixture.repository.list("external_identities")[0]
                identity[field_name] = value
                fixture.repository.put(
                    "external_identities",
                    identity["external_identity_id"],
                    identity,
                    operation=f"test_misbind_identity_{field_name}",
                )
                snapshot = fixture.repository.snapshot_bytes()
                audit_count = fixture.repository.audit_event_count

                with self.assertRaises(OAuthAccessDenied) as authenticated:
                    fixture.bridge.authenticate_access_token(
                        str(token["access_token"]),
                        required_scope="formowl.use",
                        resource=fixture.config.resource,
                        now=fixture.clock.now(),
                    )
                self.assertEqual(
                    authenticated.exception.reason_code,
                    "client_authorization_binding_invalid",
                )
                with self.assertRaises(OAuthAccessDenied) as resolved:
                    fixture.bridge.resolve_actor_context(
                        principal,
                        now=fixture.clock.now(),
                    )
                self.assertEqual(
                    resolved.exception.reason_code,
                    "client_authorization_binding_invalid",
                )
                fixture.repository.assert_unchanged(snapshot)
                self.assertEqual(fixture.repository.audit_event_count, audit_count)

            with self.subTest(path="code_exchange", field_name=field_name):
                fixture = self.fixture(seed=f"code-identity-binding-{field_name}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, code = fixture.authorize()
                identity = fixture.repository.list("external_identities")[0]
                identity[field_name] = value
                fixture.repository.put(
                    "external_identities",
                    identity["external_identity_id"],
                    identity,
                    operation=f"test_misbind_code_identity_{field_name}",
                )
                snapshot = fixture.repository.snapshot_bytes()
                with self.assertRaises(OAuthAccessDenied) as caught:
                    fixture.bridge.exchange_authorization_code(
                        fixture.token_request(code),
                        now=fixture.clock.now(),
                    )
                self.assertEqual(
                    caught.exception.reason_code,
                    "authorization_identity_mismatch",
                )
                fixture.repository.assert_unchanged(snapshot)
                self.assertIsNone(
                    fixture.repository.list("oauth_authorization_codes")[0].get("consumed_at")
                )

        provider = self.fixture(seed="identity-provider-binding")
        provider.seed_owner()
        provider.seed_invitation()
        _state, _code, token = provider.login()
        principal = provider.bridge.authenticate_access_token(
            str(token["access_token"]),
            required_scope="formowl.use",
            resource=provider.config.resource,
            now=provider.clock.now(),
        )
        identity_payload = provider.repository.list("external_identities")[0]
        identity_payload["provider"] = "other-provider"
        misbound_provider = ExternalIdentity(**identity_payload)
        snapshot = provider.repository.snapshot_bytes()
        with patch.object(
            provider.repository,
            "get_external_identity",
            return_value=misbound_provider,
        ):
            with self.assertRaises(OAuthAccessDenied) as authenticated:
                provider.bridge.authenticate_access_token(
                    str(token["access_token"]),
                    required_scope="formowl.use",
                    resource=provider.config.resource,
                    now=provider.clock.now(),
                )
            with self.assertRaises(OAuthAccessDenied) as resolved:
                provider.bridge.resolve_actor_context(
                    principal,
                    now=provider.clock.now(),
                )
        self.assertEqual(
            authenticated.exception.reason_code,
            "client_authorization_binding_invalid",
        )
        self.assertEqual(
            resolved.exception.reason_code,
            "client_authorization_binding_invalid",
        )
        provider.repository.assert_unchanged(snapshot)

    def test_token_session_ids_are_bound_to_jwt_principal_and_authorization(self) -> None:
        jwt_binding = self.fixture(seed="token-session-jwt-binding")
        jwt_binding.seed_owner()
        jwt_binding.seed_invitation()
        _state, _code, token = jwt_binding.login()
        session_key = jwt_binding.repository.list("oauth_token_sessions")[0]["token_session_id"]
        session = jwt_binding.repository.get("oauth_token_sessions", session_key)
        session["token_session_id"] = "oauthsid_tampered"
        jwt_binding.repository.put(
            "oauth_token_sessions",
            session_key,
            session,
            operation="test_misbind_token_session_id",
        )
        snapshot = jwt_binding.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            jwt_binding.bridge.authenticate_access_token(
                str(token["access_token"]),
                required_scope="formowl.use",
                resource=jwt_binding.config.resource,
                now=jwt_binding.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "token_session_binding_invalid")
        jwt_binding.repository.assert_unchanged(snapshot)

        principal_binding = self.fixture(seed="token-session-principal-binding")
        principal_binding.seed_owner()
        principal_binding.seed_invitation()
        _state, _code, token = principal_binding.login()
        principal = principal_binding.bridge.authenticate_access_token(
            str(token["access_token"]),
            required_scope="formowl.use",
            resource=principal_binding.config.resource,
            now=principal_binding.clock.now(),
        )
        session = principal_binding.repository.get(
            "oauth_token_sessions",
            principal.token_session_id,
        )
        session["token_session_id"] = "oauthsid_tampered"
        principal_binding.repository.put(
            "oauth_token_sessions",
            principal.token_session_id,
            session,
            operation="test_misbind_principal_session_id",
        )
        snapshot = principal_binding.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            principal_binding.bridge.resolve_actor_context(
                principal,
                now=principal_binding.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "principal_session_mismatch")
        principal_binding.repository.assert_unchanged(snapshot)

        authorization_binding = self.fixture(seed="session-authorization-id-binding")
        authorization_binding.seed_owner()
        authorization_binding.seed_invitation()
        _state, _code, token = authorization_binding.login()
        session_key = authorization_binding.repository.list("oauth_token_sessions")[0][
            "token_session_id"
        ]
        session = authorization_binding.repository.get(
            "oauth_token_sessions",
            session_key,
        )
        session["oauth_client_authorization_id"] = "clientauth_missing"
        authorization_binding.repository.put(
            "oauth_token_sessions",
            session_key,
            session,
            operation="test_misbind_session_authorization_id",
        )
        snapshot = authorization_binding.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            authorization_binding.bridge.authenticate_access_token(
                str(token["access_token"]),
                required_scope="formowl.use",
                resource=authorization_binding.config.resource,
                now=authorization_binding.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "client_authorization_revoked")
        authorization_binding.repository.assert_unchanged(snapshot)

    def test_revocation_authority_allows_self_and_current_workspace_owner_with_audit(
        self,
    ) -> None:
        for authority in ("self", "workspace_owner"):
            with self.subTest(authority=authority):
                fixture = self.fixture(seed=f"revocation-{authority}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, _code, member_token = fixture.login()
                session = fixture.repository.list("oauth_token_sessions")[0]
                token = member_token
                if authority == "workspace_owner":
                    with fixture.repository.transaction() as unit:
                        fixture.repository.insert_invitation(
                            OAuthInvitation(
                                invitation_id="invite_owner_revoker",
                                normalized_email="owner@example.test",
                                workspace_id="workspace_001",
                                role="owner",
                                status="pending",
                                expires_at=(fixture.clock.now() + timedelta(hours=1)).isoformat(),
                                created_at=fixture.clock.now_iso(),
                                intended_user_id="owner_001",
                            )
                        )
                        unit.commit()
                    fixture.google_client.identity = GoogleIdentity(
                        issuer="https://accounts.google.com",
                        subject="google-owner-revoker",
                        email="owner@example.test",
                        email_verified=True,
                        display_name="Workspace Owner",
                    )
                    _owner_state, _owner_code, token = fixture.login()
                principal = fixture.bridge.authenticate_access_token(
                    str(token["access_token"]),
                    required_scope="formowl.use",
                    resource=fixture.config.resource,
                    now=fixture.clock.now(),
                )
                actor_context = fixture.bridge.resolve_actor_context(
                    principal,
                    now=fixture.clock.now(),
                )
                audit_before = fixture.repository.audit_event_count

                fixture.bridge.revoke_token_session(
                    session["token_session_id"],
                    principal=principal,
                    actor_context=actor_context,
                    reason_code="operator_revoked",
                    now=fixture.clock.now(),
                )

                revoked = fixture.repository.get(
                    "oauth_token_sessions",
                    session["token_session_id"],
                )
                self.assertEqual(revoked["revocation_reason"], "operator_revoked")
                self.assertIsNotNone(revoked["revoked_at"])
                self.assertEqual(fixture.repository.audit_event_count, audit_before + 1)
                audits = [
                    audit
                    for audit in fixture.repository.list("audit_log")
                    if audit.get("action") == "oauth_token_session_revoked"
                ]
                self.assertEqual(len(audits), 1)
                audit = audits[0]
                self.assertEqual(audit["actor_user_id"], principal.user_id)
                self.assertEqual(audit["actor_type"], "user")
                self.assertIsNone(audit.get("actor_service_id"))
                self.assertEqual(audit["target_id"], session["token_session_id"])
                self.assertEqual(audit["workspace_id"], "workspace_001")
                self.assertEqual(audit["reason_code"], "operator_revoked")
                self.assertNotIn(str(token["access_token"]), str(audit))

    def test_revocation_authority_denies_nonowners_removed_and_disabled_without_writes(
        self,
    ) -> None:
        cases = (
            ("forged_context", "token_revocation_principal_invalid"),
            ("member", "token_revocation_forbidden"),
            ("removed_member", "workspace_membership_inactive"),
            ("disabled_member", "formowl_user_disabled"),
        )
        for name, reason_code in cases:
            with self.subTest(name=name):
                fixture = self.fixture(seed=f"revocation-denied-{name}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, _code, token = fixture.login()
                session = fixture.repository.list("oauth_token_sessions")[0]
                principal = fixture.bridge.authenticate_access_token(
                    str(token["access_token"]),
                    required_scope="formowl.use",
                    resource=fixture.config.resource,
                    now=fixture.clock.now(),
                )
                actor_context = fixture.bridge.resolve_actor_context(
                    principal,
                    now=fixture.clock.now(),
                )
                owner_session = OAuthTokenSession.from_dict(
                    {
                        **session,
                        "token_session_id": "oauthsid_owner_target",
                        "user_id": "owner_001",
                        "token_jti_hash": hash_oauth_value(
                            "token_jti",
                            f"owner-target-{name}",
                        ),
                    }
                )
                with fixture.repository.transaction() as unit:
                    fixture.repository.insert_token_session(owner_session)
                    unit.commit()
                attempted_actor_context = actor_context
                if name == "forged_context":
                    attempted_actor_context = replace(
                        actor_context,
                        user=fixture.repository.get_user("owner_001"),
                    )
                elif name == "removed_member":
                    membership_key = fixture.repository._workspace_member_key(
                        principal.user_id,
                        "workspace_001",
                    )
                    membership = fixture.repository.get(
                        "workspace_members",
                        membership_key,
                    )
                    membership["removed_at"] = fixture.clock.now_iso()
                    fixture.repository.put(
                        "workspace_members",
                        membership_key,
                        membership,
                        operation="test_remove_revocation_owner",
                    )
                elif name == "disabled_member":
                    user = fixture.repository.get("users", principal.user_id)
                    user["status"] = "disabled"
                    fixture.repository.put(
                        "users",
                        principal.user_id,
                        user,
                        operation="test_disable_revocation_user",
                    )
                snapshot = fixture.repository.snapshot_bytes()
                audit_count = fixture.repository.audit_event_count

                with self.assertRaises(OAuthAccessDenied) as caught:
                    fixture.bridge.revoke_token_session(
                        owner_session.token_session_id,
                        principal=principal,
                        actor_context=attempted_actor_context,
                        reason_code="unauthorized_attempt",
                        now=fixture.clock.now(),
                    )

                self.assertEqual(caught.exception.reason_code, reason_code)
                fixture.repository.assert_unchanged(snapshot)
                self.assertEqual(fixture.repository.audit_event_count, audit_count)

    def test_revocation_missing_replay_and_audit_failure_are_atomic(self) -> None:
        missing = self.fixture(seed="revocation-missing")
        missing.seed_owner()
        missing.seed_invitation()
        _state, _code, missing_token = missing.login()
        missing_principal = missing.bridge.authenticate_access_token(
            str(missing_token["access_token"]),
            required_scope="formowl.use",
            resource=missing.config.resource,
            now=missing.clock.now(),
        )
        missing_actor_context = missing.bridge.resolve_actor_context(
            missing_principal,
            now=missing.clock.now(),
        )
        missing_snapshot = missing.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            missing.bridge.revoke_token_session(
                "oauthsid_missing",
                principal=missing_principal,
                actor_context=missing_actor_context,
                reason_code="operator_revoked",
                now=missing.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "token_session_missing")
        missing.repository.assert_unchanged(missing_snapshot)

        replay = self.fixture(seed="revocation-replay")
        replay.seed_owner()
        replay.seed_invitation()
        _state, _code, replay_token = replay.login()
        session = replay.repository.list("oauth_token_sessions")[0]
        replay_principal = replay.bridge.authenticate_access_token(
            str(replay_token["access_token"]),
            required_scope="formowl.use",
            resource=replay.config.resource,
            now=replay.clock.now(),
        )
        replay_actor_context = replay.bridge.resolve_actor_context(
            replay_principal,
            now=replay.clock.now(),
        )
        replay.bridge.revoke_token_session(
            session["token_session_id"],
            principal=replay_principal,
            actor_context=replay_actor_context,
            reason_code="operator_revoked",
            now=replay.clock.now(),
        )
        replay_snapshot = replay.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            replay.bridge.revoke_token_session(
                session["token_session_id"],
                principal=replay_principal,
                actor_context=replay_actor_context,
                reason_code="operator_revoked",
                now=replay.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "token_session_inactive")
        replay.repository.assert_unchanged(replay_snapshot)

        audit_failure = self.fixture(seed="revocation-audit-failure")
        audit_failure.seed_owner()
        audit_failure.seed_invitation()
        _state, _code, audit_failure_token = audit_failure.login()
        session = audit_failure.repository.list("oauth_token_sessions")[0]
        audit_failure_principal = audit_failure.bridge.authenticate_access_token(
            str(audit_failure_token["access_token"]),
            required_scope="formowl.use",
            resource=audit_failure.config.resource,
            now=audit_failure.clock.now(),
        )
        audit_failure_actor_context = audit_failure.bridge.resolve_actor_context(
            audit_failure_principal,
            now=audit_failure.clock.now(),
        )
        audit_failure_snapshot = audit_failure.repository.snapshot_bytes()
        audit_failure.repository.inject_failure_at(2)
        with self.assertRaises(FailureInjected):
            audit_failure.bridge.revoke_token_session(
                session["token_session_id"],
                principal=audit_failure_principal,
                actor_context=audit_failure_actor_context,
                reason_code="operator_revoked",
                now=audit_failure.clock.now(),
            )
        audit_failure.repository.assert_unchanged(audit_failure_snapshot)

    def test_operator_revocation_is_deployment_authorized_audited_and_atomic(self) -> None:
        fixture = self.fixture(seed="operator-revocation")
        fixture.seed_owner()
        fixture.seed_invitation()
        _state, _code, _token = fixture.login()
        session = fixture.repository.list("oauth_token_sessions")[0]

        fixture.bridge.revoke_token_session_as_operator(
            session["token_session_id"],
            operator_service_id="operator_service_001",
            reason_code="operator_revoked",
            now=fixture.clock.now(),
        )

        revoked = fixture.repository.get_token_session(session["token_session_id"])
        self.assertIsNotNone(revoked)
        self.assertEqual(revoked.revocation_reason, "operator_revoked")
        revocation_audits = [
            row
            for row in fixture.repository.list("audit_log")
            if row["action"] == "oauth_token_session_revoked"
        ]
        self.assertEqual(len(revocation_audits), 1)
        audit = revocation_audits[0]
        self.assertEqual(audit["actor_type"], "service")
        self.assertEqual(audit["actor_service_id"], "operator_service_001")
        self.assertIsNone(audit.get("actor_user_id"))
        self.assertEqual(audit["external_identity_id"], session["external_identity_id"])
        self.assertEqual(audit["oauth_token_session_id"], session["token_session_id"])
        self.assertNotIn("access_token", str(audit))
        persisted_after_first = fixture.repository.snapshot_bytes()
        with (
            patch.object(
                fixture.repository,
                "get_token_session",
                return_value=OAuthTokenSession.from_dict(session),
            ),
            self.assertRaises(OAuthAccessDenied) as caught,
        ):
            fixture.bridge.revoke_token_session_as_operator(
                session["token_session_id"],
                operator_service_id="operator_service_001",
                reason_code="competing_different_reason",
                now=fixture.clock.now(),
            )
        self.assertEqual(caught.exception.reason_code, "token_session_revoked")
        fixture.repository.assert_unchanged(persisted_after_first)
        persisted_session = fixture.repository.get_token_session(session["token_session_id"])
        self.assertIsNotNone(persisted_session)
        self.assertEqual(persisted_session.revocation_reason, "operator_revoked")
        self.assertEqual(
            len(
                [
                    row
                    for row in fixture.repository.list("audit_log")
                    if row["action"] == "oauth_token_session_revoked"
                ]
            ),
            1,
        )
        self.assertNotIn(
            "competing_different_reason",
            str(fixture.repository.list("audit_log")),
        )

        denied = self.fixture(seed="operator-revocation-denied")
        denied.seed_owner()
        denied.seed_invitation()
        _state, _code, _token = denied.login()
        denied_session = denied.repository.list("oauth_token_sessions")[0]
        denied_snapshot = denied.repository.snapshot_bytes()
        with self.assertRaises(OAuthAccessDenied) as caught:
            denied.bridge.revoke_token_session_as_operator(
                denied_session["token_session_id"],
                operator_service_id="operator_service_removed",
                reason_code="operator_revoked",
                now=denied.clock.now(),
            )
        self.assertEqual(
            caught.exception.reason_code,
            "token_revocation_operator_unauthorized",
        )
        denied.repository.assert_unchanged(denied_snapshot)

        rollback = self.fixture(seed="operator-revocation-rollback")
        rollback.seed_owner()
        rollback.seed_invitation()
        _state, _code, _token = rollback.login()
        rollback_session = rollback.repository.list("oauth_token_sessions")[0]
        rollback_snapshot = rollback.repository.snapshot_bytes()
        rollback.repository.inject_failure_at(2)
        with self.assertRaises(FailureInjected):
            rollback.bridge.revoke_token_session_as_operator(
                rollback_session["token_session_id"],
                operator_service_id="operator_service_001",
                reason_code="operator_revoked",
                now=rollback.clock.now(),
            )
        rollback.repository.assert_unchanged(rollback_snapshot)

    def test_self_revocation_requires_current_workspace_membership(self) -> None:
        fixture = self.fixture(seed="self-revocation-removed")
        fixture.seed_owner()
        fixture.seed_invitation()
        _state, _code, token = fixture.login()
        session = fixture.repository.list("oauth_token_sessions")[0]
        principal = fixture.bridge.authenticate_access_token(
            str(token["access_token"]),
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )
        actor_context = fixture.bridge.resolve_actor_context(
            principal,
            now=fixture.clock.now(),
        )
        membership_key = fixture.repository._workspace_member_key(
            session["user_id"],
            session["current_workspace_id"],
        )
        membership = fixture.repository.get("workspace_members", membership_key)
        membership["removed_at"] = fixture.clock.now_iso()
        fixture.repository.put(
            "workspace_members",
            membership_key,
            membership,
            operation="test_remove_self_revocation_membership",
        )
        snapshot = fixture.repository.snapshot_bytes()

        with self.assertRaises(OAuthAccessDenied) as caught:
            fixture.bridge.revoke_token_session(
                session["token_session_id"],
                principal=principal,
                actor_context=actor_context,
                reason_code="self_revoked",
                now=fixture.clock.now(),
            )

        self.assertEqual(caught.exception.reason_code, "workspace_membership_inactive")
        fixture.repository.assert_unchanged(snapshot)

    def test_first_login_and_token_exchange_roll_back_after_every_repository_write(self) -> None:
        baseline = self.fixture(seed="callback-baseline")
        baseline.seed_owner()
        baseline.seed_invitation()
        baseline_state = baseline.start_authorization()
        baseline.repository.write_operations.clear()
        baseline.repository.inject_failure_at(None)
        baseline.complete_callback(baseline_state)
        callback_write_count = len(baseline.repository.write_operations)
        self.assertGreaterEqual(callback_write_count, 10)

        for write_index in range(1, callback_write_count + 1):
            with self.subTest(stage="callback", write_index=write_index):
                fixture = self.fixture(seed=f"callback-{write_index}")
                fixture.seed_owner()
                fixture.seed_invitation()
                state = fixture.start_authorization()
                snapshot = fixture.repository.snapshot_bytes()
                fixture.repository.write_operations.clear()
                fixture.repository.inject_failure_at(write_index)
                with self.assertRaises(FailureInjected):
                    fixture.complete_callback(state)
                fixture.repository.assert_unchanged(snapshot)

        token_baseline = self.fixture(seed="token-baseline")
        token_baseline.seed_owner()
        token_baseline.seed_invitation()
        _state, token_code = token_baseline.authorize()
        token_baseline.repository.write_operations.clear()
        token_baseline.repository.inject_failure_at(None)
        token_baseline.bridge.exchange_authorization_code(
            token_baseline.token_request(token_code),
            now=token_baseline.clock.now(),
        )
        token_write_count = len(token_baseline.repository.write_operations)
        self.assertEqual(token_write_count, 3)

        for write_index in range(1, token_write_count + 1):
            with self.subTest(stage="token", write_index=write_index):
                fixture = self.fixture(seed=f"token-{write_index}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, code = fixture.authorize()
                snapshot = fixture.repository.snapshot_bytes()
                fixture.repository.write_operations.clear()
                fixture.repository.inject_failure_at(write_index)
                with self.assertRaises(FailureInjected):
                    fixture.bridge.exchange_authorization_code(
                        fixture.token_request(code),
                        now=fixture.clock.now(),
                    )
                fixture.repository.assert_unchanged(snapshot)

    def test_authorization_code_insert_failure_rolls_back_without_issuance_partial_state(
        self,
    ) -> None:
        baseline = self.fixture(seed="authorization-code-insert-baseline")
        baseline.seed_owner()
        baseline.seed_invitation()
        baseline_state = baseline.start_authorization()
        baseline.repository.write_operations.clear()
        baseline_result = baseline.complete_callback(baseline_state)
        raw_code = parse_qs(urlparse(baseline_result["redirect_uri"]).query)["code"][0]
        stored_codes = baseline.repository.list("oauth_authorization_codes")
        self.assertEqual(len(stored_codes), 1)
        self.assertEqual(
            stored_codes[0]["code_hash"],
            hash_oauth_value("authorization_code", raw_code),
        )
        self.assertNotIn(raw_code, str(stored_codes[0]))
        insert_write_index = (
            baseline.repository.write_operations.index("insert_authorization_code") + 1
        )

        fixture = self.fixture(seed="authorization-code-insert-failure")
        fixture.seed_owner()
        fixture.seed_invitation()
        state = fixture.start_authorization()
        snapshot = fixture.repository.snapshot_bytes()
        fixture.repository.write_operations.clear()
        fixture.repository.inject_failure_at(insert_write_index)

        with self.assertRaises(FailureInjected):
            fixture.complete_callback(state)

        fixture.repository.assert_unchanged(snapshot)
        self.assertEqual(fixture.repository.list("oauth_authorization_codes"), [])
        self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])
        self.assertFalse(
            any(
                audit.get("action") == "oauth_authorization_code_issued"
                for audit in fixture.repository.list("audit_log")
            )
        )
        self.assertEqual(
            fixture.repository.list("oauth_transactions")[0]["status"],
            "pending",
        )

    def test_client_authorization_insert_failure_rolls_back_identity_and_audit_state(
        self,
    ) -> None:
        baseline = self.fixture(seed="client-authorization-insert-baseline")
        baseline.seed_owner()
        baseline.seed_invitation()
        baseline_state = baseline.start_authorization()
        baseline.repository.write_operations.clear()
        baseline.complete_callback(baseline_state)
        authorization = baseline.repository.list("oauth_client_authorizations")[0]
        identity = baseline.repository.list("external_identities")[0]
        transaction = baseline.repository.list("oauth_transactions")[0]
        invitation = baseline.repository.get("oauth_invitations", "invite_001")
        self.assertEqual(authorization["client_id"], transaction["client_id"])
        self.assertEqual(
            authorization["external_identity_id"],
            identity["external_identity_id"],
        )
        self.assertEqual(authorization["user_id"], identity["user_id"])
        self.assertEqual(authorization["granted_scopes"], transaction["scopes"])
        self.assertEqual(
            authorization["default_workspace_id"],
            invitation["workspace_id"],
        )
        self.assertIsNone(authorization.get("revoked_at"))
        insert_write_index = (
            baseline.repository.write_operations.index("insert_client_authorization") + 1
        )

        fixture = self.fixture(seed="client-authorization-insert-failure")
        fixture.seed_owner()
        fixture.seed_invitation()
        state = fixture.start_authorization()
        snapshot = fixture.repository.snapshot_bytes()
        fixture.repository.write_operations.clear()
        fixture.repository.inject_failure_at(insert_write_index)

        with self.assertRaises(FailureInjected):
            fixture.complete_callback(state)

        fixture.repository.assert_unchanged(snapshot)
        self.assertEqual(fixture.repository.list("external_identities"), [])
        self.assertEqual(fixture.repository.list("oauth_client_authorizations"), [])
        self.assertEqual(fixture.repository.list("oauth_authorization_codes"), [])
        self.assertEqual(fixture.repository.list("oauth_token_sessions"), [])
        self.assertEqual(len(fixture.repository.list("users")), 1)
        self.assertEqual(
            fixture.repository.get("oauth_invitations", "invite_001")["status"],
            "pending",
        )
        self.assertEqual(
            fixture.repository.list("oauth_transactions")[0]["status"],
            "pending",
        )
        self.assertFalse(
            any(
                audit.get("action")
                in {
                    "oauth_external_identity_created",
                    "oauth_invitation_accepted",
                    "google_authentication_succeeded",
                    "oauth_authorization_code_issued",
                }
                for audit in fixture.repository.list("audit_log")
            )
        )

    def test_audit_decisions_and_denials_preserve_safe_lineage(self) -> None:
        fixture = self.fixture()
        fixture.seed_owner()
        fixture.seed_invitation()
        _state, _code, token = fixture.login()
        principal = fixture.bridge.authenticate_access_token(
            str(token["access_token"]),
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )

        allowed = fixture.bridge.record_mcp_authorization_decision(
            principal=principal,
            request_id="request_001",
            tool_call_id="toolcall_001",
            tool_name="whoami",
            workspace_id="workspace_001",
            allowed=True,
            reason_code="workspace_member",
            now=fixture.clock.now(),
        )
        denial = fixture.bridge.record_oauth_denial(
            event="token_exchange",
            reason_code="pkce_verifier_mismatch",
            oauth_client_id=fixture.config.chatgpt_client_id,
            now=fixture.clock.now(),
        )
        http_denial = fixture.bridge.record_mcp_http_authentication_denial(
            raw_token=None,
            request_id="mcp_req_001",
            reason_code="authorization_header_invalid",
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )

        self.assertEqual(allowed.external_identity_id, principal.external_identity_id)
        self.assertEqual(allowed.oauth_token_session_id, principal.token_session_id)
        self.assertEqual(allowed.request_id, "request_001")
        self.assertEqual(allowed.tool_call_id, "toolcall_001")
        self.assertEqual(denial.actor_type, "external_unauthenticated")
        self.assertEqual(denial.reason_code, "pkce_verifier_mismatch")
        self.assertEqual(http_denial.action, "mcp_http_authentication_denied")
        self.assertEqual(http_denial.request_id, "mcp_req_001")
        self.assertEqual(http_denial.reason_code, "authorization_header_invalid")
        self.assertIsNone(http_denial.actor_user_id)
        self.assertIsNone(http_denial.oauth_token_session_id)
        self.assertEqual(http_denial.metadata["lineage_source"], "untrusted_bearer")
        rendered = str([allowed.to_dict(), denial.to_dict(), http_denial.to_dict()])
        for forbidden in ("google-secret", "access_token", "code_verifier", "/tmp/"):
            self.assertNotIn(forbidden, rendered)

    def test_direct_mcp_authorization_decision_persists_safe_lineage_and_is_atomic(
        self,
    ) -> None:
        fixture = self.fixture(seed="direct-mcp-decision")
        fixture.seed_owner()
        fixture.seed_invitation()
        _state, _code, token_response = fixture.login()
        principal = fixture.bridge.authenticate_access_token(
            str(token_response["access_token"]),
            required_scope="formowl.use",
            resource=fixture.config.resource,
            now=fixture.clock.now(),
        )
        mutable_snapshot = fixture.repository.mutable_state_snapshot_bytes()
        audit_count = fixture.repository.audit_event_count

        allowed = fixture.bridge.record_mcp_authorization_decision(
            principal=principal,
            request_id="request_direct_allowed",
            tool_call_id="toolcall_direct_allowed",
            tool_name="whoami",
            workspace_id="workspace_001",
            allowed=True,
            reason_code="workspace_member",
            now=fixture.clock.now(),
        )
        denied = fixture.bridge.record_mcp_authorization_decision(
            principal=None,
            request_id="request_direct_denied",
            tool_call_id="toolcall_direct_denied",
            tool_name="open_upload_session",
            workspace_id=None,
            allowed=False,
            reason_code="authentication_required",
            now=fixture.clock.now(),
        )

        fixture.repository.assert_mutable_state_unchanged(mutable_snapshot)
        self.assertEqual(fixture.repository.audit_event_count, audit_count + 2)
        persisted = fixture.repository.list("audit_log")
        persisted_by_id = {row["audit_log_id"]: row for row in persisted}
        self.assertEqual(persisted_by_id[allowed.audit_log_id], allowed.to_dict())
        self.assertEqual(persisted_by_id[denied.audit_log_id], denied.to_dict())
        self.assertEqual(allowed.action, "mcp_authorization_allowed")
        self.assertEqual(allowed.actor_type, "user")
        self.assertEqual(allowed.actor_user_id, principal.user_id)
        self.assertEqual(allowed.external_identity_id, principal.external_identity_id)
        self.assertEqual(allowed.oauth_client_id, principal.oauth_client_id)
        self.assertEqual(allowed.oauth_token_session_id, principal.token_session_id)
        self.assertEqual(allowed.workspace_id, "workspace_001")
        self.assertEqual(allowed.request_id, "request_direct_allowed")
        self.assertEqual(allowed.tool_call_id, "toolcall_direct_allowed")
        self.assertEqual(allowed.status, "ok")
        self.assertEqual(
            allowed.metadata,
            {
                "event_stage": "mcp_authorization",
                "workspace_decision": "allowed",
            },
        )
        self.assertEqual(denied.action, "mcp_authorization_denied")
        self.assertEqual(denied.actor_type, "external_unauthenticated")
        self.assertIsNone(denied.actor_user_id)
        self.assertIsNone(denied.external_identity_id)
        self.assertIsNone(denied.oauth_client_id)
        self.assertIsNone(denied.oauth_token_session_id)
        self.assertIsNone(denied.workspace_id)
        self.assertEqual(denied.session_id, "request_direct_denied")
        self.assertEqual(denied.status, "permission_denied")
        self.assertEqual(
            denied.metadata,
            {
                "event_stage": "mcp_authorization",
                "workspace_decision": "denied",
            },
        )
        rendered = str([allowed.to_dict(), denied.to_dict()])
        for forbidden in (
            str(token_response["access_token"]),
            "person@example.test",
            "Safe Person",
            "google-subject-001",
            fixture.config.resource,
            fixture.config.google_client_secret,
        ):
            self.assertNotIn(forbidden, rendered)

        invalid_snapshot = fixture.repository.snapshot_bytes()
        with self.assertRaises(ValueError):
            fixture.bridge.record_mcp_authorization_decision(
                principal=principal,
                request_id="request_invalid",
                tool_call_id="toolcall_invalid",
                tool_name="whoami/../../secret",
                workspace_id="workspace_001",
                allowed=False,
                reason_code="invalid_tool",
                now=fixture.clock.now(),
            )
        fixture.repository.assert_unchanged(invalid_snapshot)

        failing = self.fixture(seed="direct-mcp-decision-audit-failure")
        failing.seed_owner()
        failing.seed_invitation()
        _state, _code, failing_token = failing.login()
        failing_principal = failing.bridge.authenticate_access_token(
            str(failing_token["access_token"]),
            required_scope="formowl.use",
            resource=failing.config.resource,
            now=failing.clock.now(),
        )
        failing_snapshot = failing.repository.snapshot_bytes()
        failing.repository.inject_failure_at(1)
        with self.assertRaises(FailureInjected):
            failing.bridge.record_mcp_authorization_decision(
                principal=failing_principal,
                request_id="request_audit_failure",
                tool_call_id="toolcall_audit_failure",
                tool_name="whoami",
                workspace_id="workspace_001",
                allowed=True,
                reason_code="workspace_member",
                now=failing.clock.now(),
            )
        failing.repository.assert_unchanged(failing_snapshot)

    def test_http_denial_lineage_requires_verified_token_and_server_session(self) -> None:
        expired = self.fixture(seed="http-denial-expired")
        expired.seed_owner()
        expired.seed_invitation()
        _state, _code, expired_token = expired.login()
        expired_session = expired.repository.list("oauth_token_sessions")[0]
        expired.clock.advance(hours=2)

        expired_audit = expired.bridge.record_mcp_http_authentication_denial(
            raw_token=str(expired_token["access_token"]),
            request_id="mcp_req_expired",
            reason_code="token_expired",
            required_scope="formowl.use",
            resource=expired.config.resource,
            now=expired.clock.now(),
        )

        self.assertEqual(expired_audit.actor_type, "user")
        self.assertEqual(expired_audit.actor_user_id, expired_session["user_id"])
        self.assertEqual(
            expired_audit.external_identity_id,
            expired_session["external_identity_id"],
        )
        self.assertEqual(expired_audit.oauth_client_id, expired_session["client_id"])
        self.assertEqual(
            expired_audit.oauth_token_session_id,
            expired_session["token_session_id"],
        )
        self.assertEqual(
            expired_audit.workspace_id,
            expired_session["current_workspace_id"],
        )
        self.assertEqual(expired_audit.metadata["lineage_source"], "verified_token_session")

        revoked = self.fixture(seed="http-denial-revoked")
        revoked.seed_owner()
        revoked.seed_invitation()
        _state, _code, revoked_token = revoked.login()
        revoked_session = revoked.repository.list("oauth_token_sessions")[0]
        revoked_principal = revoked.bridge.authenticate_access_token(
            str(revoked_token["access_token"]),
            required_scope="formowl.use",
            resource=revoked.config.resource,
            now=revoked.clock.now(),
        )
        revoked_actor_context = revoked.bridge.resolve_actor_context(
            revoked_principal,
            now=revoked.clock.now(),
        )
        revoked.bridge.revoke_token_session(
            revoked_session["token_session_id"],
            principal=revoked_principal,
            actor_context=revoked_actor_context,
            reason_code="operator_revoked",
            now=revoked.clock.now(),
        )

        revoked_audit = revoked.bridge.record_mcp_http_authentication_denial(
            raw_token=str(revoked_token["access_token"]),
            request_id="mcp_req_revoked",
            reason_code="token_session_revoked",
            required_scope="formowl.use",
            resource=revoked.config.resource,
            now=revoked.clock.now(),
        )

        self.assertEqual(revoked_audit.actor_user_id, revoked_session["user_id"])
        self.assertEqual(
            revoked_audit.oauth_token_session_id,
            revoked_session["token_session_id"],
        )
        self.assertEqual(revoked_audit.metadata["lineage_source"], "verified_token_session")

        forged = self.fixture(seed="http-denial-forged")
        forged_audit = forged.bridge.record_mcp_http_authentication_denial(
            raw_token="invalid.jwt.value",
            request_id="mcp_req_forged",
            reason_code="token_expired",
            required_scope="formowl.use",
            resource=forged.config.resource,
            now=forged.clock.now(),
        )
        self.assertEqual(forged_audit.actor_type, "external_unauthenticated")
        self.assertIsNone(forged_audit.actor_user_id)
        self.assertIsNone(forged_audit.external_identity_id)
        self.assertIsNone(forged_audit.oauth_client_id)
        self.assertIsNone(forged_audit.oauth_token_session_id)
        self.assertIsNone(forged_audit.workspace_id)
        self.assertEqual(forged_audit.metadata["lineage_source"], "untrusted_bearer")
        rendered = str([expired_audit.to_dict(), revoked_audit.to_dict(), forged_audit.to_dict()])
        self.assertNotIn(str(expired_token["access_token"]), rendered)
        self.assertNotIn(str(revoked_token["access_token"]), rendered)
        self.assertNotIn("invalid.jwt.value", rendered)

    def test_http_denial_lineage_covers_verified_server_side_account_revocations(
        self,
    ) -> None:
        cases = (
            ("identity", "external_identity_disabled"),
            ("user", "formowl_user_disabled"),
            ("client", "client_authorization_revoked"),
        )
        for mutation, reason_code in cases:
            with self.subTest(mutation=mutation):
                fixture = self.fixture(seed=f"http-denial-{mutation}")
                fixture.seed_owner()
                fixture.seed_invitation()
                _state, _code, token = fixture.login()
                session = fixture.repository.list("oauth_token_sessions")[0]
                if mutation == "identity":
                    row = fixture.repository.get(
                        "external_identities",
                        session["external_identity_id"],
                    )
                    row["status"] = "disabled"
                    fixture.repository.put(
                        "external_identities",
                        row["external_identity_id"],
                        row,
                        operation="test_disable_identity_for_http_audit",
                    )
                elif mutation == "user":
                    row = fixture.repository.get("users", session["user_id"])
                    row["status"] = "disabled"
                    fixture.repository.put(
                        "users",
                        row["user_id"],
                        row,
                        operation="test_disable_user_for_http_audit",
                    )
                else:
                    row = fixture.repository.get(
                        "oauth_client_authorizations",
                        session["oauth_client_authorization_id"],
                    )
                    row["revoked_at"] = fixture.clock.now_iso()
                    fixture.repository.put(
                        "oauth_client_authorizations",
                        row["oauth_client_authorization_id"],
                        row,
                        operation="test_revoke_client_for_http_audit",
                    )

                with self.assertRaises(OAuthAccessDenied) as caught:
                    fixture.bridge.authenticate_access_token(
                        str(token["access_token"]),
                        required_scope="formowl.use",
                        resource=fixture.config.resource,
                        now=fixture.clock.now(),
                    )
                self.assertEqual(caught.exception.reason_code, reason_code)

                audit = fixture.bridge.record_mcp_http_authentication_denial(
                    raw_token=str(token["access_token"]),
                    request_id=f"mcp_req_{mutation}",
                    reason_code=reason_code,
                    required_scope="formowl.use",
                    resource=fixture.config.resource,
                    now=fixture.clock.now(),
                )

                self.assertEqual(audit.actor_type, "user")
                self.assertEqual(audit.actor_user_id, session["user_id"])
                self.assertEqual(audit.external_identity_id, session["external_identity_id"])
                self.assertEqual(audit.oauth_client_id, session["client_id"])
                self.assertEqual(audit.oauth_token_session_id, session["token_session_id"])
                self.assertEqual(audit.workspace_id, session["current_workspace_id"])
                self.assertEqual(audit.metadata["lineage_source"], "verified_token_session")
                self.assertNotIn(str(token["access_token"]), str(audit.to_dict()))

        unproven = self.fixture(seed="http-denial-unproven-state")
        unproven.seed_owner()
        unproven.seed_invitation()
        _state, _code, unproven_token = unproven.login()
        audit = unproven.bridge.record_mcp_http_authentication_denial(
            raw_token=str(unproven_token["access_token"]),
            request_id="mcp_req_unproven",
            reason_code="formowl_user_disabled",
            required_scope="formowl.use",
            resource=unproven.config.resource,
            now=unproven.clock.now(),
        )
        self.assertEqual(audit.actor_type, "external_unauthenticated")
        self.assertIsNone(audit.actor_user_id)
        self.assertIsNone(audit.oauth_token_session_id)

        misbound = self.fixture(seed="http-denial-misbound-session")
        misbound.seed_owner()
        misbound.seed_invitation()
        _state, _code, misbound_token = misbound.login()
        session = misbound.repository.list("oauth_token_sessions")[0]
        row = misbound.repository.get("oauth_token_sessions", session["token_session_id"])
        row["user_id"] = "user_forged"
        misbound.repository.put(
            "oauth_token_sessions",
            row["token_session_id"],
            row,
            operation="test_misbind_http_audit_session",
        )
        audit = misbound.bridge.record_mcp_http_authentication_denial(
            raw_token=str(misbound_token["access_token"]),
            request_id="mcp_req_misbound",
            reason_code="external_identity_disabled",
            required_scope="formowl.use",
            resource=misbound.config.resource,
            now=misbound.clock.now(),
        )
        self.assertEqual(audit.actor_type, "external_unauthenticated")
        self.assertIsNone(audit.actor_user_id)
        self.assertIsNone(audit.external_identity_id)
        self.assertIsNone(audit.oauth_client_id)
        self.assertIsNone(audit.oauth_token_session_id)
        self.assertIsNone(audit.workspace_id)

        rejected_claim_reasons = (
            "required_scope_missing",
            "token_resource_invalid",
            "token_session_missing",
        )
        for case_index, reason_code in enumerate(rejected_claim_reasons, start=1):
            with self.subTest(reason_code=reason_code):
                request_id = f"mcp_req_case_{case_index:02d}"
                audit = unproven.bridge.record_mcp_http_authentication_denial(
                    raw_token=str(unproven_token["access_token"]),
                    request_id=request_id,
                    reason_code=reason_code,
                    required_scope="formowl.use",
                    resource=unproven.config.resource,
                    now=unproven.clock.now(),
                )
                self.assertEqual(audit.request_id, request_id)
                self.assertEqual(audit.session_id, request_id)
                self.assertEqual(audit.actor_type, "external_unauthenticated")
                self.assertIsNone(audit.actor_user_id)
                self.assertIsNone(audit.external_identity_id)
                self.assertIsNone(audit.oauth_client_id)
                self.assertIsNone(audit.oauth_token_session_id)
                self.assertIsNone(audit.workspace_id)

    def test_http_authentication_denial_audit_failure_rolls_back(self) -> None:
        fixture = self.fixture()
        snapshot = fixture.repository.snapshot_bytes()
        fixture.repository.inject_failure_at(1)

        with self.assertRaises(FailureInjected):
            fixture.bridge.record_mcp_http_authentication_denial(
                raw_token=None,
                request_id="mcp_req_rollback",
                reason_code="authorization_header_invalid",
                required_scope="formowl.use",
                resource=fixture.config.resource,
                now=fixture.clock.now(),
            )

        fixture.repository.assert_unchanged(snapshot)

        trusted = self.fixture(seed="mcp-http-denial-trusted-rollback")
        trusted.seed_owner()
        trusted.seed_invitation()
        _state, _code, token = trusted.login()
        session = trusted.repository.list("oauth_token_sessions")[0]
        user = trusted.repository.get("users", session["user_id"])
        user["status"] = "disabled"
        trusted.repository.put(
            "users",
            user["user_id"],
            user,
            operation="test_disable_user_for_audit_rollback",
        )
        trusted_snapshot = trusted.repository.snapshot_bytes()
        trusted.repository.inject_failure_at(1)

        with self.assertRaises(FailureInjected):
            trusted.bridge.record_mcp_http_authentication_denial(
                raw_token=str(token["access_token"]),
                request_id="mcp_req_trusted_rollback",
                reason_code="formowl_user_disabled",
                required_scope="formowl.use",
                resource=trusted.config.resource,
                now=trusted.clock.now(),
            )

        trusted.repository.assert_unchanged(trusted_snapshot)


if __name__ == "__main__":
    unittest.main()
