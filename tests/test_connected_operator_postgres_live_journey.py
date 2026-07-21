from __future__ import annotations

from contextlib import nullcontext, redirect_stderr
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401

from formowl_evidence import issue20_packet as issue20_packet_module


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "connected_operator_postgres_live_journey.py"
_HASH_A = "sha256:" + "a" * 64
_HASH_B = "sha256:" + "b" * 64
_HASH_C = "sha256:" + "c" * 64
_HASH_D = "sha256:" + "d" * 64
_HASH_E = "sha256:" + "e" * 64


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _portable_handoff_owner(module):
    return patch.multiple(
        module,
        _FAILURE_STAGE_HANDOFF_OWNER_UID=os.getuid(),
        _FAILURE_STAGE_HANDOFF_OWNER_GID=os.getgid(),
    )


def _report(
    module,
    *,
    secret_contract_hash: str = _HASH_C,
    runtime_image_id_hash: str = _HASH_B,
    schema_version: int = 2,
) -> dict[str, object]:
    output_labels = (
        {
            "lookup-user",
            "list-users",
            "lookup-token-session",
            "list-token-sessions",
        }
        if schema_version == 1
        else {
            "bootstrap-owner",
            "invite-member",
            "lookup-owner",
            "list-users",
            "list-member-sessions-before",
            "revoke-member-session",
            "lookup-member-session-after-revoke",
            "remove-member",
            "restore-member",
            "list-member-sessions-after-restore",
            "operator-audit-contract",
            "operator-rollback-state",
        }
    )
    counts = {
        "fresh_postgresql_database_count": 1,
        "generated_secret_count": 6,
        "idempotent_secret_rerun_count": 1,
        "migration_command_success_count": 1,
        "operator_cli_success_count": 4,
        "operator_cli_denial_count": 1,
        "operator_audit_total_count": 5,
        "operator_audit_allowed_count": 4,
        "operator_audit_denied_count": 1,
        "runtime_image_build_count": 1,
    }
    attestations = {
        "actual_connected_cli_executed": True,
        "clean_temporary_secret_set_used": True,
        "current_runtime_image_built_from_worktree": True,
        "fresh_postgresql_database_used": True,
        "google_credential_injected_outside_initializer": True,
        "inside_probe_used_installed_runtime_package": True,
        "operator_allow_and_deny_audits_persisted": True,
        "operator_outputs_excluded_sensitive_identity_and_backend_detail": True,
        "report_contains_only_safe_status_count_and_hash_evidence": True,
    }
    if schema_version == 2:
        counts.update(
            {
                "operator_cli_success_count": 10,
                "operator_cli_denial_count": 3,
                "operator_audit_total_count": 13,
                "operator_audit_allowed_count": 10,
                "operator_audit_denied_count": 3,
                "owner_bootstrap_success_count": 1,
                "member_invitation_success_count": 1,
                "member_approval_denial_count": 1,
                "explicit_token_revocation_count": 1,
                "last_owner_removal_denial_count": 1,
                "membership_remove_success_count": 1,
                "membership_restore_success_count": 1,
                "post_restore_active_session_count": 0,
                "post_restore_inactive_session_count": 2,
                "transaction_rollback_probe_count": 1,
                "transaction_rollback_preserved_state_count": 1,
            }
        )
        attestations.update(
            {
                "exact_operator_lifecycle_exercised": True,
                "member_approval_denial_audited": True,
                "membership_rollback_verified": True,
                "immutable_runtime_and_postgres_images_used": True,
            }
        )
    return {
        "artifact_id": module.ARTIFACT_ID,
        "schema_version": schema_version,
        "status": "passed",
        "implementation_contract_hash": module.issue20_implementation_contract_hash(ROOT),
        "runtime_image_id_hash": runtime_image_id_hash,
        "journey_script_hash": module._sha256_bytes(SCRIPT_PATH.read_bytes()),
        "secret_initialization_contract_hash": secret_contract_hash,
        "migration_result_hash": _HASH_D,
        "operator_output_hashes": {
            label: module._sha256_json({"operator_output": label})
            for label in sorted(output_labels)
        },
        "operator_denial_hash": _HASH_E,
        "counts": counts,
        "attestations": attestations,
    }


def _signed_report(
    module,
    *,
    report: dict[str, object] | None = None,
    private_key_byte: int = 17,
    nonce_byte: int = 34,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    body = _report(module) if report is None else deepcopy(report)
    signing_key = module.Ed25519PrivateKey.from_private_bytes(bytes([private_key_byte]) * 32)
    authority, signing_key = module.create_execution_authority(
        implementation_contract_hash=body["implementation_contract_hash"],
        runtime_image_id_hash=body["runtime_image_id_hash"],
        journey_script_hash=body["journey_script_hash"],
        campaign_nonce=bytes([nonce_byte]) * 32,
        signing_key=signing_key,
    )
    authority_pin = module.create_execution_authority_pin(authority)
    signed = module.attach_execution_receipt(
        body,
        authority,
        authority_pin,
        signing_key,
    )
    return signed, authority, authority_pin


class ConnectedOperatorPostgresLiveJourneyTests(unittest.TestCase):
    def test_report_contract_accepts_only_bound_hash_count_evidence(self) -> None:
        module = _load_module("connected_operator_live_report")
        report, authority, authority_pin = _signed_report(module)

        self.assertEqual(
            module.validate_report(
                report,
                trusted_execution_authority=authority,
                trusted_execution_authority_pin=authority_pin,
            ),
            {"passed": True, "blockers": []},
        )
        self.assertEqual(
            module.validate_report(_report(module, schema_version=1)),
            {"passed": True, "blockers": []},
        )

        probes = []
        wrong_count = deepcopy(report)
        wrong_count["counts"]["operator_audit_allowed_count"] = 3
        probes.append(wrong_count)
        raw_identity = deepcopy(report)
        raw_identity["debug"] = "operator-live@example.test"
        probes.append(raw_identity)
        raw_backend = deepcopy(report)
        raw_backend["operator_denial_hash"] = "postgresql://private-backend/formowl"
        probes.append(raw_backend)
        missing_attestation = deepcopy(report)
        missing_attestation["attestations"][
            "report_contains_only_safe_status_count_and_hash_evidence"
        ] = False
        probes.append(missing_attestation)
        stale_implementation = deepcopy(report)
        stale_implementation["implementation_contract_hash"] = _HASH_E
        probes.append(stale_implementation)

        for probe in probes:
            with self.subTest(probe=probe):
                validation = module.validate_report(
                    probe,
                    trusted_execution_authority=authority,
                    trusted_execution_authority_pin=authority_pin,
                )
                self.assertFalse(validation["passed"])
                self.assertTrue(validation["blockers"])

        self.assertFalse(
            module.validate_report(
                report,
                trusted_execution_authority=authority,
            )["passed"]
        )

    def test_schema_migration_candidate_cannot_replace_original_pre_run_pin(self) -> None:
        module = _load_module("connected_operator_live_pin_migration")
        _, _, original_pin = _signed_report(module)
        upgraded = _report(module, schema_version=1)
        current = _report(module, schema_version=2)
        upgraded.update(
            {
                "schema_version": 2,
                "implementation_contract_hash": current["implementation_contract_hash"],
                "runtime_image_id_hash": current["runtime_image_id_hash"],
                "journey_script_hash": current["journey_script_hash"],
                "operator_output_hashes": current["operator_output_hashes"],
                "counts": current["counts"],
                "attestations": current["attestations"],
            }
        )
        replacement_report, replacement_authority, replacement_pin = _signed_report(
            module,
            report=upgraded,
            private_key_byte=51,
            nonce_byte=68,
        )
        self.assertTrue(
            module.validate_report(
                replacement_report,
                trusted_execution_authority=replacement_authority,
                trusted_execution_authority_pin=replacement_pin,
            )["passed"]
        )
        rejected = module.validate_report(
            replacement_report,
            trusted_execution_authority=replacement_authority,
            trusted_execution_authority_pin=original_pin,
        )
        self.assertFalse(rejected["passed"])
        self.assertTrue(
            any("pin" in blocker for blocker in rejected["blockers"]),
            rejected,
        )

    def test_execution_authority_pin_is_exact_and_tamper_evident(self) -> None:
        module = _load_module("connected_operator_live_authority_pin")
        body = _report(module)
        signing_key = module.Ed25519PrivateKey.from_private_bytes(bytes([17]) * 32)
        authority, returned_signing_key = module.create_execution_authority(
            implementation_contract_hash=body["implementation_contract_hash"],
            runtime_image_id_hash=body["runtime_image_id_hash"],
            journey_script_hash=body["journey_script_hash"],
            campaign_nonce=bytes([34]) * 32,
            signing_key=signing_key,
        )

        self.assertIs(returned_signing_key, signing_key)
        self.assertEqual(module._execution_authority_blockers(authority), [])
        authority_pin = module.create_execution_authority_pin(authority)
        self.assertEqual(
            module.validate_execution_authority_pin(authority, authority_pin),
            {"passed": True, "blockers": []},
        )
        self.assertEqual(
            authority_pin["execution_authority_hash"],
            module._sha256_json(authority),
        )
        self.assertNotIn("signature_hex", authority)
        self.assertNotIn("private_key", json.dumps(authority, sort_keys=True))

        replacement_authority, _ = module.create_execution_authority(
            implementation_contract_hash=body["implementation_contract_hash"],
            runtime_image_id_hash=body["runtime_image_id_hash"],
            journey_script_hash=body["journey_script_hash"],
            campaign_nonce=bytes([35]) * 32,
            signing_key=signing_key,
        )
        replacement_validation = module.validate_execution_authority_pin(
            replacement_authority,
            authority_pin,
        )
        self.assertFalse(replacement_validation["passed"])
        self.assertTrue(
            any("pin binding mismatch" in blocker for blocker in replacement_validation["blockers"])
        )

        tampered_authority = deepcopy(authority)
        tampered_authority["receipt_public_key_hash"] = _HASH_E
        self.assertTrue(module._execution_authority_blockers(tampered_authority))
        with self.assertRaisesRegex(
            RuntimeError,
            "operator_journey_execution_authority_invalid",
        ):
            module.create_execution_authority_pin(tampered_authority)
        with self.assertRaisesRegex(
            RuntimeError,
            "operator_journey_execution_authority_invalid",
        ):
            module.create_execution_authority(
                implementation_contract_hash=body["implementation_contract_hash"],
                runtime_image_id_hash="invalid",
                journey_script_hash=body["journey_script_hash"],
            )

    def test_execution_receipt_binds_body_authority_pin_and_signature(self) -> None:
        module = _load_module("connected_operator_live_execution_receipt")
        body = _report(module)
        signing_key = module.Ed25519PrivateKey.from_private_bytes(bytes([17]) * 32)
        authority, signing_key = module.create_execution_authority(
            implementation_contract_hash=body["implementation_contract_hash"],
            runtime_image_id_hash=body["runtime_image_id_hash"],
            journey_script_hash=body["journey_script_hash"],
            campaign_nonce=bytes([34]) * 32,
            signing_key=signing_key,
        )
        authority_pin = module.create_execution_authority_pin(authority)

        payload = module._execution_receipt_payload(body, authority, authority_pin)
        signed = module.attach_execution_receipt(
            body,
            authority,
            authority_pin,
            signing_key,
        )
        receipt = signed["execution_receipt"]
        self.assertEqual(
            {key: receipt[key] for key in payload},
            payload,
        )
        self.assertEqual(
            module.validate_execution_receipt(signed, authority, authority_pin),
            {"passed": True, "blockers": []},
        )
        receipt_text = json.dumps(receipt, sort_keys=True)
        self.assertNotIn("postgresql://", receipt_text)
        self.assertNotIn("private_key", receipt_text)

        tampered_report = deepcopy(signed)
        tampered_report["counts"]["operator_cli_success_count"] = 9
        tampered_validation = module.validate_execution_receipt(
            tampered_report,
            authority,
            authority_pin,
        )
        self.assertFalse(tampered_validation["passed"])
        self.assertTrue(
            any(
                "receipt binding mismatch" in blocker for blocker in tampered_validation["blockers"]
            )
        )

        replacement_authority, _ = module.create_execution_authority(
            implementation_contract_hash=body["implementation_contract_hash"],
            runtime_image_id_hash=body["runtime_image_id_hash"],
            journey_script_hash=body["journey_script_hash"],
            campaign_nonce=bytes([35]) * 32,
            signing_key=signing_key,
        )
        replacement_pin = module.create_execution_authority_pin(replacement_authority)
        replacement_validation = module.validate_execution_receipt(
            signed,
            authority,
            replacement_pin,
        )
        self.assertFalse(replacement_validation["passed"])
        self.assertTrue(
            any("pin binding mismatch" in blocker for blocker in replacement_validation["blockers"])
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "operator_journey_execution_authority_pin_mismatch",
        ):
            module.attach_execution_receipt(
                body,
                authority,
                replacement_pin,
                signing_key,
            )

        invalid_body = deepcopy(body)
        invalid_body["operator_output_hashes"] = None
        with self.assertRaisesRegex(
            RuntimeError,
            "operator_journey_execution_receipt_invalid",
        ):
            module._execution_receipt_payload(invalid_body, authority, authority_pin)
        with self.assertRaisesRegex(
            RuntimeError,
            "operator_journey_execution_receipt_invalid",
        ):
            module.attach_execution_receipt(
                signed,
                authority,
                authority_pin,
                signing_key,
            )

    def test_report_body_validation_is_strict_side_effect_free_and_redacted(self) -> None:
        module = _load_module("connected_operator_live_report_body")
        report = _report(module)
        original = deepcopy(report)

        self.assertEqual(
            module._validate_report_body(report),
            {"passed": True, "blockers": []},
        )
        self.assertEqual(report, original)

        forbidden = deepcopy(report)
        forbidden["debug"] = "/tmp/formowl-operator/private-output.json"
        forbidden_original = deepcopy(forbidden)
        validation = module._validate_report_body(forbidden)
        self.assertFalse(validation["passed"])
        self.assertTrue(any("keys are invalid" in blocker for blocker in validation["blockers"]))
        self.assertTrue(any("forbidden text" in blocker for blocker in validation["blockers"]))
        self.assertEqual(forbidden, forbidden_original)

        stale = deepcopy(report)
        stale["journey_script_hash"] = _HASH_E
        stale_validation = module._validate_report_body(stale)
        self.assertFalse(stale_validation["passed"])
        self.assertTrue(
            any("script hash is stale" in blocker for blocker in stale_validation["blockers"])
        )

    def test_operator_v2_command_sequence_covers_lifecycle_and_denials(self) -> None:
        module = _load_module("connected_operator_live_v2_sequence")
        calls: list[tuple[list[str], str | None]] = []
        session_list_count = 0
        invalid_bootstrap = False

        def fake_cli(arguments, *, environ, expected_error=None):
            nonlocal session_list_count
            del environ
            rendered = list(arguments)
            calls.append((rendered, expected_error))
            if expected_error is not None:
                return None, subprocess.CompletedProcess(
                    rendered,
                    1,
                    "",
                    json.dumps({"error": expected_error, "status": "error"}),
                )
            command = rendered[0]
            if command == "bootstrap-owner":
                payload = {
                    "status": "ok",
                    "invitation_id": "invite_bootstrap_safe",
                    "workspace_id": (
                        "workspace_coherent_but_wrong"
                        if invalid_bootstrap
                        else module._BOOTSTRAP_WORKSPACE_ID
                    ),
                }
            elif command == "invite-user":
                payload = {
                    "status": "ok",
                    "invitation_id": "invite_member_safe",
                    "workspace_id": module._WORKSPACE_ID,
                    "role": "member",
                }
            elif command == "lookup-user":
                payload = {"status": "ok", "result_count": 1, "user": {}}
            elif command == "list-users":
                payload = {"status": "ok", "result_count": 2, "users": [{}, {}]}
            elif command == "list-token-sessions":
                session_list_count += 1
                payload = (
                    {
                        "status": "ok",
                        "result_count": 2,
                        "inactive_session_count": 0,
                        "token_sessions": [{}, {}],
                    }
                    if session_list_count == 1
                    else {
                        "status": "ok",
                        "result_count": 0,
                        "inactive_session_count": 2,
                        "token_sessions": [],
                    }
                )
            elif command == "revoke-token-session":
                payload = {"status": "ok", "token_session_revoked": True}
            elif command == "lookup-token-session":
                payload = {
                    "status": "ok",
                    "result_count": 1,
                    "inactive_session_count": 1,
                    "token_session": {
                        "token_session_id": module._MEMBER_SESSION_IDS[1],
                    },
                }
            elif command == "remove-workspace-member":
                payload = {"status": "ok", "membership_removed": True}
            elif command == "restore-workspace-member":
                payload = {
                    "status": "ok",
                    "membership_restored": True,
                    "role": "member",
                }
            else:
                raise AssertionError(rendered)
            return payload, subprocess.CompletedProcess(
                rendered,
                0,
                json.dumps(payload),
                "",
            )

        with patch.object(module, "_run_operator_cli", side_effect=fake_cli):
            outputs, denials, process_outputs = module._execute_operator_v2_commands({})

        self.assertEqual(len(outputs), 10)
        self.assertEqual(
            set(denials),
            {
                "member-approval-denied",
                "unauthorized-list-users",
                "last-owner-removal-denied",
            },
        )
        self.assertEqual(len(process_outputs), 26)
        self.assertEqual(
            [arguments[0] for arguments, _expected_error in calls],
            [
                "bootstrap-owner",
                "invite-user",
                "invite-user",
                "lookup-user",
                "list-users",
                "list-token-sessions",
                "revoke-token-session",
                "lookup-token-session",
                "list-users",
                "remove-workspace-member",
                "remove-workspace-member",
                "restore-workspace-member",
                "list-token-sessions",
            ],
        )
        self.assertEqual(
            [expected_error for _arguments, expected_error in calls if expected_error],
            [
                "connected_invitation_failed",
                "operator_unauthorized",
                "operator_last_owner_removal_denied",
            ],
        )

        invalid_bootstrap = True
        session_list_count = 0
        with (
            patch.object(module, "_run_operator_cli", side_effect=fake_cli),
            self.assertRaisesRegex(
                RuntimeError,
                "^operator_journey_bootstrap_invalid$",
            ),
        ):
            module._execute_operator_v2_commands({})

    def test_operator_v2_exact_audit_contract_is_closed(self) -> None:
        module = _load_module("connected_operator_live_v2_audits")
        bootstrap_invitation_id = "invite_operator_bootstrap_001"
        member_invitation_id = "invite_operator_member_001"
        rows = [
            {
                "action": action,
                "actor_type": actor_type,
                "actor_service_id": actor_service_id,
                "target_type": target_type,
                "target_id": target_id,
                "workspace_id": workspace_id,
                "status": status,
                "reason_code": reason_code,
                "event_count": event_count,
            }
            for (
                action,
                actor_type,
                actor_service_id,
                target_type,
                target_id,
                workspace_id,
                status,
                reason_code,
                event_count,
            ) in (
                (
                    "oauth_invitation_create",
                    "service",
                    "operator_live",
                    "workspace",
                    module._WORKSPACE_ID,
                    module._WORKSPACE_ID,
                    "denied",
                    "invitation_owner_required",
                    1,
                ),
                (
                    "oauth_invitation_create",
                    "service",
                    "operator_live",
                    "oauth_invitation",
                    member_invitation_id,
                    module._WORKSPACE_ID,
                    "ok",
                    "invitation_created",
                    1,
                ),
                (
                    "oauth_owner_bootstrap_created",
                    "service",
                    "operator_live",
                    "oauth_owner_bootstrap",
                    bootstrap_invitation_id,
                    module._BOOTSTRAP_WORKSPACE_ID,
                    "ok",
                    "owner_bootstrap_created",
                    1,
                ),
                (
                    "oauth_token_session_revoked",
                    "service",
                    "operator_live",
                    "oauth_token_session",
                    module._MEMBER_SESSION_IDS[0],
                    module._WORKSPACE_ID,
                    "ok",
                    "operator_journey_revoked",
                    1,
                ),
                (
                    "operator_token_session_list",
                    "service",
                    "operator_live",
                    "user",
                    module._MEMBER_USER_ID,
                    None,
                    "ok",
                    "operator_directory_allowed",
                    2,
                ),
                (
                    "operator_token_session_lookup",
                    "service",
                    "operator_live",
                    "oauth_token_session",
                    module._MEMBER_SESSION_IDS[1],
                    None,
                    "ok",
                    "operator_directory_allowed",
                    1,
                ),
                (
                    "operator_user_list",
                    "external_unauthenticated",
                    None,
                    "operator_directory",
                    "operator_directory",
                    None,
                    "denied",
                    "operator_unauthorized",
                    1,
                ),
                (
                    "operator_user_list",
                    "service",
                    "operator_live",
                    "workspace",
                    module._WORKSPACE_ID,
                    None,
                    "ok",
                    "operator_directory_allowed",
                    1,
                ),
                (
                    "operator_user_lookup",
                    "service",
                    "operator_live",
                    "user",
                    module._OWNER_USER_ID,
                    None,
                    "ok",
                    "operator_directory_allowed",
                    1,
                ),
                (
                    "operator_workspace_member_remove",
                    "service",
                    "operator_live",
                    "workspace_member",
                    f"{module._WORKSPACE_ID}:{module._OWNER_USER_ID}",
                    None,
                    "denied",
                    "operator_last_owner_removal_denied",
                    1,
                ),
                (
                    "operator_workspace_member_remove",
                    "service",
                    "operator_live",
                    "workspace_member",
                    f"{module._WORKSPACE_ID}:{module._MEMBER_USER_ID}",
                    None,
                    "ok",
                    "operator_directory_allowed",
                    1,
                ),
                (
                    "operator_workspace_member_restore",
                    "service",
                    "operator_live",
                    "workspace_member",
                    f"{module._WORKSPACE_ID}:{module._MEMBER_USER_ID}",
                    None,
                    "ok",
                    "operator_directory_allowed",
                    1,
                ),
            )
        ]

        class AuditConnection:
            def __init__(self) -> None:
                self.statement = None

            def query_all(self, statement):
                self.statement = statement
                return deepcopy(rows)

        class AuditRepository:
            def __init__(self) -> None:
                self.connection = AuditConnection()

        repository = AuditRepository()
        summary = module._operator_audit_summary(
            repository,
            bootstrap_invitation_id=bootstrap_invitation_id,
            member_invitation_id=member_invitation_id,
        )

        self.assertEqual(summary["total_count"], 13)
        self.assertEqual(summary["allowed_count"], 10)
        self.assertEqual(summary["denied_count"], 3)
        self.assertRegex(summary["contract_hash"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            repository.connection.statement.parameters,
            {"actions": list(module._OPERATOR_ACTIONS)},
        )
        self.assertIn(
            "target_type, target_id, workspace_id",
            repository.connection.statement.sql,
        )
        self.assertNotIn(
            "example.test",
            json.dumps(summary, sort_keys=True),
        )

        rows[0] = {**rows[0], "reason_code": "coherent_but_wrong"}
        with self.assertRaisesRegex(RuntimeError, "^operator_journey_audit_invalid$"):
            module._summarize_operator_audit_rows(
                rows,
                bootstrap_invitation_id=bootstrap_invitation_id,
                member_invitation_id=member_invitation_id,
            )

        rows[0] = {
            **rows[0],
            "reason_code": "invitation_owner_required",
            "workspace_id": module._BOOTSTRAP_WORKSPACE_ID,
            "target_id": module._BOOTSTRAP_WORKSPACE_ID,
        }
        with self.assertRaisesRegex(RuntimeError, "^operator_journey_audit_invalid$"):
            module._summarize_operator_audit_rows(
                rows,
                bootstrap_invitation_id=bootstrap_invitation_id,
                member_invitation_id=member_invitation_id,
            )

    def test_seed_operator_records_commits_exact_state_and_rolls_back_failure(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_seed_records")
        from test_connected_operator_directory import _OperatorRepository

        class JourneyRepository(_OperatorRepository):
            def __init__(self, *, fail_on: str | None = None) -> None:
                super().__init__()
                self.fail_on = fail_on

            def insert_user(self, value) -> None:
                self._insert("insert_user", self.users, value)

            def insert_workspace_member(self, value, *, created_at: str) -> None:
                self.assert_safe_timestamp(created_at)
                self._insert("insert_workspace_member", self.memberships, value)

            def insert_external_identity(self, value) -> None:
                self._insert("insert_external_identity", self.identities, value)

            def insert_client_authorization(self, value) -> None:
                self._insert("insert_client_authorization", self.authorizations, value)

            def insert_token_session(self, value) -> None:
                self._insert("insert_token_session", self.sessions, value)

            def _insert(self, name: str, collection: list, value) -> None:
                self.calls.append(name)
                if self.fail_on == name:
                    raise RuntimeError("injected_seed_failure")
                collection.append(value)

            def assert_safe_timestamp(self, value: str) -> None:
                self.assert_timestamp = value
                if not value.endswith("+00:00"):
                    raise RuntimeError("injected_seed_timestamp_invalid")

        repository = JourneyRepository()
        module._seed_operator_records(repository)

        self.assertEqual(repository.commit_count, 1)
        self.assertEqual(repository.rollback_count, 0)
        self.assertEqual(len(repository.users), 2)
        self.assertEqual(len(repository.memberships), 2)
        self.assertEqual(len(repository.identities), 2)
        self.assertEqual(len(repository.authorizations), 2)
        self.assertEqual(len(repository.sessions), 3)
        self.assertEqual(
            module._operator_member_state(repository),
            {
                "active_role": "member",
                "removed_role": None,
                "session_count": 2,
                "revoked_session_count": 0,
            },
        )
        self.assertEqual(
            {session.token_session_id for session in repository.sessions},
            {
                "oauthsid_operator_owner_001",
                *module._MEMBER_SESSION_IDS,
            },
        )
        for session in repository.sessions:
            issued_at = module.datetime.fromisoformat(session.issued_at)
            expires_at = module.datetime.fromisoformat(session.expires_at)
            self.assertLess(issued_at, expires_at)
            self.assertIsNone(session.revoked_at)

        failing_repository = JourneyRepository(fail_on="insert_external_identity")
        baseline_state = failing_repository.snapshot_state()
        with self.assertRaisesRegex(RuntimeError, "^injected_seed_failure$"):
            module._seed_operator_records(failing_repository)
        self.assertEqual(failing_repository.snapshot_state(), baseline_state)
        self.assertEqual(failing_repository.commit_count, 0)
        self.assertEqual(failing_repository.rollback_count, 1)
        self.assertEqual(failing_repository.audits, [])

    def test_operator_rollback_probe_preserves_state_audit_and_safe_output(self) -> None:
        module = _load_module("connected_operator_live_rollback_probe")
        from test_connected_operator_directory import _OperatorRepository

        class JourneyRepository(_OperatorRepository):
            def insert_user(self, value) -> None:
                self.users.append(value)

            def insert_workspace_member(self, value, *, created_at: str) -> None:
                del created_at
                self.memberships.append(value)

            def insert_external_identity(self, value) -> None:
                self.identities.append(value)

            def insert_client_authorization(self, value) -> None:
                self.authorizations.append(value)

            def insert_token_session(self, value) -> None:
                self.sessions.append(value)

        class AuditCountConnection:
            def __init__(self, repository: JourneyRepository) -> None:
                self.repository = repository
                self.query_count = 0

            def query_one(self, statement):
                self.query_count += 1
                self.last_statement = statement
                return {"event_count": len(self.repository.audits)}

        repository = JourneyRepository()
        repository.connection = AuditCountConnection(repository)
        module._seed_operator_records(repository)
        baseline_state = repository.snapshot_state()
        baseline_member_state = module._operator_member_state(repository)
        baseline_audit_count = len(repository.audits)
        baseline_commit_count = repository.commit_count
        baseline_rollback_count = repository.rollback_count

        audit_failing = module._AuditFailingRepository(repository)
        self.assertEqual(
            audit_failing.get_user(module._MEMBER_USER_ID).user_id,
            module._MEMBER_USER_ID,
        )
        with self.assertRaisesRegex(RuntimeError, "^injected_operator_audit_failure$"):
            audit_failing.append_audit_log(object())
        self.assertEqual(repository.snapshot_state(), baseline_state)
        self.assertEqual(len(repository.audits), baseline_audit_count)

        with patch.object(module.subprocess, "run") as process_run:
            result = module._run_operator_rollback_probe(repository)

        process_run.assert_not_called()
        self.assertEqual(
            result,
            {
                "probe_count": 1,
                "preserved_state_count": 1,
                "state_hash": module._sha256_json(baseline_member_state),
            },
        )
        self.assertRegex(result["state_hash"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("example.test", json.dumps(result, sort_keys=True))
        self.assertEqual(repository.snapshot_state(), baseline_state)
        self.assertEqual(module._operator_member_state(repository), baseline_member_state)
        self.assertEqual(len(repository.audits), baseline_audit_count)
        self.assertEqual(repository.commit_count, baseline_commit_count)
        self.assertEqual(repository.rollback_count, baseline_rollback_count + 1)
        self.assertEqual(repository.connection.query_count, 2)

    def test_preexisting_execution_authority_or_pin_is_rejected_before_docker(self) -> None:
        module = _load_module("connected_operator_live_existing_authority")
        for existing_names in (
            ("authority",),
            ("pin",),
            ("authority", "pin"),
        ):
            with self.subTest(existing_names=existing_names):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    output_path = root / "operator-live.json"
                    authority_path = root / "operator-authority.json"
                    authority_pin_path = root / "operator-authority-pin.json"
                    paths = {
                        "authority": authority_path,
                        "pin": authority_pin_path,
                    }
                    original_bytes: dict[str, bytes] = {}
                    for name in existing_names:
                        value = f"verifier-held-{name}".encode("utf-8")
                        paths[name].write_bytes(value)
                        paths[name].chmod(0o400)
                        original_bytes[name] = value

                    with (
                        patch.object(module, "_run_command") as run_command,
                        self.assertRaisesRegex(
                            RuntimeError,
                            "^operator_journey_execution_authority_already_exists$",
                        ),
                    ):
                        module.run_outer(
                            output_path,
                            postgres_image=module.PINNED_POSTGRES_IMAGE,
                            execution_authority_output_path=authority_path,
                            execution_authority_pin_output_path=authority_pin_path,
                        )

                    run_command.assert_not_called()
                    self.assertFalse(output_path.exists())
                    for name, value in original_bytes.items():
                        self.assertEqual(paths[name].read_bytes(), value)
                        self.assertEqual(paths[name].stat().st_mode & 0o777, 0o400)

    def test_partial_execution_authority_pair_locks_campaign_before_raw_run(self) -> None:
        module = _load_module("connected_operator_live_partial_authority")
        created = {
            "status": "ok",
            "secret_set_state": "created",
            "secret_file_count": 6,
            "created_file_count": 6,
            "initialization_contract_hash": _HASH_A,
            "google_client_secret_generated": False,
            "requires_operator_google_client_secret": True,
            "supports_connected_preflight_ready": False,
        }
        unchanged = {
            **created,
            "secret_set_state": "unchanged",
            "created_file_count": 0,
        }
        runtime_image_id = "sha256:" + "1" * 64
        calls: list[list[str]] = []
        init_call_count = 0
        original_write_secret = module._write_secret

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_path = root / "operator-live.json"
            authority_path = root / "operator-authority.json"
            authority_pin_path = root / "operator-authority-pin.json"

            def fake_run(command, *, environ=None, check=True):
                nonlocal init_call_count
                del environ, check
                rendered = list(command)
                calls.append(rendered)
                if rendered[:2] == ["docker", "build"]:
                    Path(rendered[rendered.index("--iidfile") + 1]).write_text(
                        runtime_image_id + "\n",
                        encoding="utf-8",
                    )
                if "init-secrets" in rendered:
                    init_call_count += 1
                    payload = created if init_call_count == 1 else unchanged
                    return subprocess.CompletedProcess(rendered, 0, json.dumps(payload), "")
                return subprocess.CompletedProcess(rendered, 0, "", "")

            def fail_pin_write(path: Path, value: bytes) -> None:
                if path == authority_pin_path:
                    raise OSError("synthetic pin persistence failure")
                original_write_secret(path, value)

            with (
                patch.object(module, "_run_command", side_effect=fake_run),
                patch.object(module, "_write_secret", side_effect=fail_pin_write),
                self.assertRaisesRegex(
                    RuntimeError,
                    "^operator_journey_execution_authority_pair_incomplete$",
                ),
            ):
                module.run_outer(
                    output_path,
                    postgres_image=module.PINNED_POSTGRES_IMAGE,
                    execution_authority_output_path=authority_path,
                    execution_authority_pin_output_path=authority_pin_path,
                )

            self.assertTrue(authority_path.is_file())
            self.assertEqual(authority_path.stat().st_mode & 0o777, 0o400)
            authority_bytes = authority_path.read_bytes()
            self.assertFalse(authority_pin_path.exists())
            self.assertFalse(output_path.exists())
            self.assertFalse(
                any(command[:3] == ["docker", "network", "create"] for command in calls)
            )
            self.assertFalse(any("--inside" in command for command in calls))
            self.assertFalse(any("POSTGRES_DB=formowl" in command for command in calls))

            with (
                patch.object(module, "_run_command") as retry_command,
                self.assertRaisesRegex(
                    RuntimeError,
                    "^operator_journey_execution_authority_already_exists$",
                ),
            ):
                module.run_outer(
                    output_path,
                    postgres_image=module.PINNED_POSTGRES_IMAGE,
                    execution_authority_output_path=authority_path,
                    execution_authority_pin_output_path=authority_pin_path,
                )

            retry_command.assert_not_called()
            self.assertEqual(authority_path.read_bytes(), authority_bytes)
            self.assertFalse(authority_pin_path.exists())

    def test_outer_flow_bootstraps_an_empty_directory_with_the_built_image(self) -> None:
        module = _load_module("connected_operator_live_outer")
        created = {
            "status": "ok",
            "secret_set_state": "created",
            "secret_file_count": 6,
            "created_file_count": 6,
            "initialization_contract_hash": _HASH_A,
            "google_client_secret_generated": False,
            "requires_operator_google_client_secret": True,
            "supports_connected_preflight_ready": False,
        }
        unchanged = {
            **created,
            "secret_set_state": "unchanged",
            "created_file_count": 0,
        }
        secret_contract_hash = module._sha256_json({"generated": created, "unchanged": unchanged})
        runtime_image_id = "sha256:" + "1" * 64
        runtime_image_id_hash = module._sha256_bytes(runtime_image_id.encode("utf-8"))
        calls: list[list[str]] = []
        init_call_count = 0

        with tempfile.TemporaryDirectory() as temporary:
            output_path = Path(temporary) / "operator-live.json"
            authority_path = Path(temporary) / "operator-authority.json"
            authority_pin_path = Path(temporary) / "operator-authority-pin.json"

            def fake_run(command, *, environ=None, check=True):
                nonlocal init_call_count
                rendered = list(command)
                calls.append(rendered)
                if rendered[:2] == ["docker", "build"]:
                    Path(rendered[rendered.index("--iidfile") + 1]).write_text(
                        runtime_image_id + "\n",
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(rendered, 0, "", "")
                if "init-secrets" in rendered:
                    init_call_count += 1
                    mount = rendered[rendered.index("-v") + 1]
                    secret_dir = Path(mount.split(":", 1)[0])
                    if init_call_count == 1:
                        self.assertTrue(secret_dir.is_dir())
                        self.assertEqual(list(secret_dir.iterdir()), [])
                        payload = created
                    else:
                        payload = unchanged
                    return subprocess.CompletedProcess(
                        rendered,
                        0,
                        json.dumps(payload),
                        "",
                    )
                if rendered[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(rendered, 0, "ready", "")
                if "--inside" in rendered:
                    self.assertTrue(authority_path.is_file())
                    self.assertTrue(authority_pin_path.is_file())
                    out_mount = next(
                        argument for argument in rendered if argument.endswith(":/out")
                    )
                    container_output = Path(out_mount.rsplit(":", 1)[0]) / output_path.name
                    container_output.write_text(
                        json.dumps(
                            _report(
                                module,
                                secret_contract_hash=secret_contract_hash,
                                runtime_image_id_hash=runtime_image_id_hash,
                            ),
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
                    container_output.chmod(0o444)
                return subprocess.CompletedProcess(rendered, 0, "", "")

            with (
                _portable_handoff_owner(module),
                patch.object(module, "_run_command", side_effect=fake_run),
            ):
                report = module.run_outer(
                    output_path,
                    postgres_image=module.PINNED_POSTGRES_IMAGE,
                    execution_authority_output_path=authority_path,
                    execution_authority_pin_output_path=authority_pin_path,
                )
            self.assertEqual(authority_path.stat().st_mode & 0o777, 0o400)
            self.assertEqual(authority_pin_path.stat().st_mode & 0o777, 0o400)
            self.assertEqual(
                json.loads(authority_path.read_text(encoding="utf-8"))["artifact_id"],
                module.EXECUTION_AUTHORITY_ARTIFACT_ID,
            )
            self.assertEqual(
                json.loads(authority_pin_path.read_text(encoding="utf-8"))["artifact_id"],
                module.EXECUTION_AUTHORITY_PIN_ARTIFACT_ID,
            )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(init_call_count, 2)
        init_commands = [command for command in calls if "init-secrets" in command]
        self.assertEqual(len(init_commands), 2)
        for command in init_commands:
            self.assertEqual(command[0:2], ["docker", "run"])
            self.assertIn(runtime_image_id, command)
            self.assertNotIn("compose", command)
            self.assertNotIn("connected-mcp", command)
        build_command = next(command for command in calls if command[:2] == ["docker", "build"])
        self.assertIn("--iidfile", build_command)
        self.assertNotIn("--tag", build_command)
        self.assertFalse(any(command[:3] == ["docker", "image", "inspect"] for command in calls))
        postgres_command = next(
            command
            for command in calls
            if command[:2] == ["docker", "run"] and "POSTGRES_DB=formowl" in command
        )
        self.assertEqual(postgres_command[-1], module.PINNED_POSTGRES_IMAGE)
        inside_command = next(command for command in calls if "--inside" in command)
        self.assertIn(runtime_image_id, inside_command)
        self.assertNotIn("--entrypoint", inside_command)
        self.assertIn("python", inside_command)
        self.assertIn(
            "/opt/formowl-connected-operator-journey.py",
            inside_command,
        )
        self.assertFalse(any(":/workspace" in argument for argument in inside_command))
        self.assertNotIn("--user", inside_command)
        self.assertIn("/run/formowl-secrets:size=1m,mode=0700", inside_command)
        for capability in module._LAUNCHER_CAPABILITIES:
            self.assertIn(capability, inside_command)
        self.assertIn(
            f"{module._RUNTIME_IMAGE_ID_ENV}={runtime_image_id}",
            inside_command,
        )
        runtime_image_id_index = inside_command.index("--runtime-image-id")
        self.assertEqual(inside_command[runtime_image_id_index + 1], runtime_image_id)
        inside_data_mount = next(
            argument for argument in inside_command if argument.endswith(":/data")
        )
        cleanup_command = next(
            command for command in calls if module._RUNTIME_DATA_CLEANUP_CODE in command
        )
        cleanup_data_dir = Path(inside_data_mount.rsplit(":", 1)[0])
        self.assertEqual(
            cleanup_command,
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "10001:10001",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--mount",
                f"type=bind,src={cleanup_data_dir},dst=/data",
                runtime_image_id,
                "python",
                "-c",
                module._RUNTIME_DATA_CLEANUP_CODE,
                "/data",
            ],
        )
        self.assertNotIn("--cap-add", cleanup_command)
        self.assertNotIn("--entrypoint", cleanup_command)
        self.assertNotIn("0:0", cleanup_command)
        self.assertNotIn("chown", module._RUNTIME_DATA_CLEANUP_CODE)
        self.assertNotIn("chmod", module._RUNTIME_DATA_CLEANUP_CODE)
        image_removal = ["docker", "image", "rm", "--force", runtime_image_id]
        self.assertEqual(
            calls[calls.index(cleanup_command) + 1],
            image_removal,
        )

    def test_runtime_data_cleanup_is_hardened_verified_then_removes_exact_image(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_hardened_cleanup")
        runtime_image_id = "sha256:" + "1" * 64
        events: list[str] = []
        calls: list[list[str]] = []

        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            data_dir.mkdir()
            expected_cleanup = [
                "docker",
                "run",
                "--rm",
                "--user",
                "10001:10001",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--mount",
                f"type=bind,src={data_dir},dst=/data",
                runtime_image_id,
                "python",
                "-c",
                module._RUNTIME_DATA_CLEANUP_CODE,
                "/data",
            ]
            expected_image_removal = [
                "docker",
                "image",
                "rm",
                "--force",
                runtime_image_id,
            ]

            def fake_run(command, *, environ=None, check=True):
                del environ, check
                rendered = list(command)
                calls.append(rendered)
                if rendered == expected_cleanup:
                    events.append("cleanup")
                elif rendered == expected_image_removal:
                    events.append("image_removal")
                return subprocess.CompletedProcess(rendered, 0, "", "")

            def verify_empty(path: Path) -> bool:
                self.assertEqual(path, data_dir)
                self.assertEqual(events, ["cleanup"])
                events.append("verified_empty")
                return True

            with (
                patch.object(module, "_run_command", side_effect=fake_run),
                patch.object(
                    module,
                    "_runtime_data_directory_is_empty",
                    side_effect=verify_empty,
                ),
            ):
                self.assertTrue(
                    module._cleanup_runtime_data_and_image(
                        data_dir,
                        runtime_image_id,
                    )
                )

        self.assertEqual(calls, [expected_cleanup, expected_image_removal])
        self.assertEqual(events, ["cleanup", "verified_empty", "image_removal"])

    def test_runtime_data_cleanup_payload_deletes_uid_10001_mode_0700_tree(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_cleanup_payload")
        runtime_uid = 10001
        runtime_gid = 10001

        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            temp_root.chmod(0o755)
            data_dir = temp_root / "data"
            data_dir.mkdir(mode=0o707)
            data_dir.chmod(0o707)
            owned_tree = data_dir / "owned"
            owned_tree.mkdir(mode=0o700)
            nested = owned_tree / "nested"
            nested.mkdir(mode=0o700)
            payload = nested / "payload.bin"
            payload.write_bytes(b"temporary runtime data")
            payload.chmod(0o600)
            try:
                for path in (payload, nested, owned_tree):
                    os.chown(path, runtime_uid, runtime_gid)
            except PermissionError as error:
                self.skipTest(
                    "canonical environment cannot create UID/GID 10001 cleanup fixture: " f"{error}"
                )

            switch_identity = None
            if os.geteuid() != runtime_uid or os.getegid() != runtime_gid:

                def switch_identity() -> None:
                    os.setgroups([])
                    os.setgid(runtime_gid)
                    os.setuid(runtime_uid)

            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        module._RUNTIME_DATA_CLEANUP_CODE,
                        str(data_dir),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    preexec_fn=switch_identity,
                )
            except subprocess.SubprocessError as error:
                self.skipTest("canonical environment cannot switch to UID/GID 10001: " f"{error}")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(data_dir.iterdir()), [])
            self.assertEqual(data_dir.stat().st_uid, os.geteuid())
            self.assertEqual(stat.S_IMODE(data_dir.stat().st_mode), 0o707)

    def test_outer_cleanup_preserves_primary_failure_and_still_removes_image(self) -> None:
        module = _load_module("connected_operator_live_primary_cleanup_failure")
        created = {
            "status": "ok",
            "secret_set_state": "created",
            "secret_file_count": 6,
            "created_file_count": 6,
            "initialization_contract_hash": _HASH_A,
            "google_client_secret_generated": False,
            "requires_operator_google_client_secret": True,
            "supports_connected_preflight_ready": False,
        }
        unchanged = {
            **created,
            "secret_set_state": "unchanged",
            "created_file_count": 0,
        }
        runtime_image_id = "sha256:" + "1" * 64
        primary_failure = RuntimeError("primary inner journey failure")
        calls: list[list[str]] = []
        cleanup_calls: list[bool] = []
        init_call_count = 0
        internal_temporary = tempfile.TemporaryDirectory()

        class RecordingTemporaryDirectory:
            name = internal_temporary.name

            def cleanup(self) -> None:
                cleanup_calls.append(True)
                internal_temporary.cleanup()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_path = root / "operator-live.json"
            authority_path = root / "operator-authority.json"
            authority_pin_path = root / "operator-authority-pin.json"
            diagnostic_path = root / "operator-failure-diagnostic.json"

            def fake_run(command, *, environ=None, check=True):
                nonlocal init_call_count
                del environ, check
                rendered = list(command)
                calls.append(rendered)
                if rendered[:2] == ["docker", "build"]:
                    Path(rendered[rendered.index("--iidfile") + 1]).write_text(
                        runtime_image_id + "\n",
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(rendered, 0, "", "")
                if "init-secrets" in rendered:
                    init_call_count += 1
                    payload = created if init_call_count == 1 else unchanged
                    return subprocess.CompletedProcess(rendered, 0, json.dumps(payload), "")
                if rendered[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(rendered, 0, "ready", "")
                if "--inside" in rendered:
                    raise primary_failure
                if rendered[:2] == ["docker", "stop"]:
                    return subprocess.CompletedProcess(
                        rendered,
                        1,
                        "",
                        "private postgres cleanup detail",
                    )
                if rendered[:3] == ["docker", "network", "rm"]:
                    return subprocess.CompletedProcess(
                        rendered,
                        1,
                        "",
                        "private network cleanup detail",
                    )
                if module._RUNTIME_DATA_CLEANUP_CODE in rendered:
                    return subprocess.CompletedProcess(
                        rendered,
                        1,
                        "",
                        "private runtime data cleanup detail",
                    )
                return subprocess.CompletedProcess(rendered, 0, "", "")

            with (
                patch.object(module, "_run_command", side_effect=fake_run),
                patch.object(
                    module.tempfile,
                    "TemporaryDirectory",
                    return_value=RecordingTemporaryDirectory(),
                ),
                self.assertRaises(RuntimeError) as raised,
            ):
                module.run_outer(
                    output_path,
                    postgres_image=module.PINNED_POSTGRES_IMAGE,
                    execution_authority_output_path=authority_path,
                    execution_authority_pin_output_path=authority_pin_path,
                    failure_diagnostic_output_path=diagnostic_path,
                )
            diagnostic_stage = json.loads(diagnostic_path.read_text(encoding="utf-8"))["stage"]
            self.assertFalse(output_path.exists())
            self.assertTrue(authority_path.is_file())
            self.assertTrue(authority_pin_path.is_file())

        self.assertIs(raised.exception, primary_failure)
        self.assertEqual(
            raised.exception.__notes__,
            [
                "operator_journey_postgres_cleanup_failed",
                "operator_journey_network_cleanup_failed",
                "operator_journey_runtime_cleanup_failed",
            ],
        )
        self.assertEqual(cleanup_calls, [True])
        expected_data_dir = Path(internal_temporary.name) / "data"
        cleanup_command = next(
            command for command in calls if module._RUNTIME_DATA_CLEANUP_CODE in command
        )
        self.assertEqual(
            cleanup_command,
            module._runtime_data_cleanup_command(expected_data_dir, runtime_image_id),
        )
        image_removal = ["docker", "image", "rm", "--force", runtime_image_id]
        self.assertEqual(calls[calls.index(cleanup_command) + 1], image_removal)
        stop_command = next(command for command in calls if command[:2] == ["docker", "stop"])
        network_command = next(
            command for command in calls if command[:3] == ["docker", "network", "rm"]
        )
        self.assertLess(calls.index(stop_command), calls.index(network_command))
        self.assertLess(calls.index(network_command), calls.index(cleanup_command))
        self.assertEqual(diagnostic_stage, "outer_inner_journey")

    def test_nonzero_stop_or_network_cleanup_fails_closed_before_report_publication(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_resource_cleanup_failure")
        created = {
            "status": "ok",
            "secret_set_state": "created",
            "secret_file_count": 6,
            "created_file_count": 6,
            "initialization_contract_hash": _HASH_A,
            "google_client_secret_generated": False,
            "requires_operator_google_client_secret": True,
            "supports_connected_preflight_ready": False,
        }
        unchanged = {
            **created,
            "secret_set_state": "unchanged",
            "created_file_count": 0,
        }
        secret_contract_hash = module._sha256_json({"generated": created, "unchanged": unchanged})
        runtime_image_id = "sha256:" + "1" * 64
        runtime_image_id_hash = module._sha256_bytes(runtime_image_id.encode("utf-8"))

        for cleanup_prefix in (
            ("docker", "stop"),
            ("docker", "network", "rm"),
        ):
            with self.subTest(cleanup_prefix=cleanup_prefix):
                calls: list[list[str]] = []
                init_call_count = 0
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    output_path = root / "operator-live.json"
                    authority_path = root / "operator-authority.json"
                    authority_pin_path = root / "operator-authority-pin.json"
                    diagnostic_path = root / "operator-failure-diagnostic.json"
                    stderr = io.StringIO()

                    def fake_run(command, *, environ=None, check=True):
                        nonlocal init_call_count
                        del environ, check
                        rendered = list(command)
                        calls.append(rendered)
                        if rendered[:2] == ["docker", "build"]:
                            Path(rendered[rendered.index("--iidfile") + 1]).write_text(
                                runtime_image_id + "\n",
                                encoding="utf-8",
                            )
                            return subprocess.CompletedProcess(rendered, 0, "", "")
                        if "init-secrets" in rendered:
                            init_call_count += 1
                            payload = created if init_call_count == 1 else unchanged
                            return subprocess.CompletedProcess(
                                rendered,
                                0,
                                json.dumps(payload),
                                "",
                            )
                        if rendered[:2] == ["docker", "exec"]:
                            return subprocess.CompletedProcess(rendered, 0, "ready", "")
                        if "--inside" in rendered:
                            out_mount = next(
                                argument for argument in rendered if argument.endswith(":/out")
                            )
                            container_output = Path(out_mount.rsplit(":", 1)[0]) / output_path.name
                            container_output.write_text(
                                json.dumps(
                                    _report(
                                        module,
                                        secret_contract_hash=secret_contract_hash,
                                        runtime_image_id_hash=runtime_image_id_hash,
                                    ),
                                    ensure_ascii=False,
                                    indent=2,
                                    sort_keys=True,
                                ),
                                encoding="utf-8",
                            )
                            container_output.chmod(0o444)
                        if tuple(rendered[: len(cleanup_prefix)]) == cleanup_prefix:
                            return subprocess.CompletedProcess(
                                rendered,
                                1,
                                "",
                                "private docker cleanup detail /private/runtime",
                            )
                        return subprocess.CompletedProcess(rendered, 0, "", "")

                    with (
                        _portable_handoff_owner(module),
                        patch.object(module, "_run_command", side_effect=fake_run),
                        redirect_stderr(stderr),
                    ):
                        exit_code = module.main(
                            [
                                "--output",
                                str(output_path),
                                "--execution-authority-output",
                                str(authority_path),
                                "--execution-authority-pin-output",
                                str(authority_pin_path),
                                "--failure-diagnostic-output",
                                str(diagnostic_path),
                            ]
                        )

                    self.assertEqual(exit_code, 1)
                    self.assertEqual(
                        json.loads(stderr.getvalue()),
                        {"error": "operator_journey_failed", "status": "error"},
                    )
                    self.assertFalse(output_path.exists())
                    self.assertEqual(
                        json.loads(diagnostic_path.read_text(encoding="utf-8")),
                        {
                            "artifact_id": module.FAILURE_DIAGNOSTIC_ARTIFACT_ID,
                            "failure_code": "stage_failed",
                            "schema_version": 1,
                            "stage": "outer_runtime_cleanup",
                            "status": "failed",
                        },
                    )
                    stop_command = next(
                        command for command in calls if command[:2] == ["docker", "stop"]
                    )
                    network_command = next(
                        command for command in calls if command[:3] == ["docker", "network", "rm"]
                    )
                    runtime_cleanup_command = next(
                        command for command in calls if module._RUNTIME_DATA_CLEANUP_CODE in command
                    )
                    image_removal_command = [
                        "docker",
                        "image",
                        "rm",
                        "--force",
                        runtime_image_id,
                    ]
                    self.assertLess(calls.index(stop_command), calls.index(network_command))
                    self.assertLess(
                        calls.index(network_command),
                        calls.index(runtime_cleanup_command),
                    )
                    self.assertEqual(
                        calls[calls.index(runtime_cleanup_command) + 1],
                        image_removal_command,
                    )
                    rendered_public = stderr.getvalue() + diagnostic_path.read_text(
                        encoding="utf-8"
                    )
                    self.assertNotIn("private docker cleanup detail", rendered_public)
                    self.assertNotIn("/private/", rendered_public)
                    with self.assertRaisesRegex(
                        issue20_packet_module.EvidencePacketError,
                        "^operator_evidence_report_invalid$",
                    ):
                        issue20_packet_module._operator_layer_from_report(
                            None,
                            operator_attested=True,
                            trusted_execution_authority=json.loads(
                                authority_path.read_text(encoding="utf-8")
                            ),
                            trusted_execution_authority_pin=json.loads(
                                authority_pin_path.read_text(encoding="utf-8")
                            ),
                        )
                    with (
                        patch.object(module, "_run_command") as retry_command,
                        self.assertRaisesRegex(
                            RuntimeError,
                            "^operator_journey_execution_authority_already_exists$",
                        ),
                    ):
                        module.run_outer(
                            output_path,
                            postgres_image=module.PINNED_POSTGRES_IMAGE,
                            execution_authority_output_path=authority_path,
                            execution_authority_pin_output_path=authority_pin_path,
                            failure_diagnostic_output_path=diagnostic_path,
                        )
                    retry_command.assert_not_called()
                    self.assertFalse(output_path.exists())

    def test_main_post_report_cleanup_failure_removes_success_artifact_and_writes_diagnostic(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_runtime_cleanup_failure")
        created = {
            "status": "ok",
            "secret_set_state": "created",
            "secret_file_count": 6,
            "created_file_count": 6,
            "initialization_contract_hash": _HASH_A,
            "google_client_secret_generated": False,
            "requires_operator_google_client_secret": True,
            "supports_connected_preflight_ready": False,
        }
        unchanged = {
            **created,
            "secret_set_state": "unchanged",
            "created_file_count": 0,
        }
        secret_contract_hash = module._sha256_json({"generated": created, "unchanged": unchanged})
        runtime_image_id = "sha256:" + "1" * 64
        runtime_image_id_hash = module._sha256_bytes(runtime_image_id.encode("utf-8"))
        private_failure = "private runtime data cleanup failure /private/data/path"
        private_temporary_failure = (
            "private temporary directory cleanup failure /private/scratch/path"
        )
        cleanup_kind = "runtime_data"
        init_call_count = 0
        calls: list[list[str]] = []

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_path = root / "operator-live.json"
            authority_path = root / "operator-authority.json"
            authority_pin_path = root / "operator-authority-pin.json"
            diagnostic_path = root / "operator-failure-diagnostic.json"
            stderr = io.StringIO()

            def fake_run(command, *, environ=None, check=True):
                nonlocal init_call_count
                del environ, check
                rendered = list(command)
                calls.append(rendered)
                if rendered[:2] == ["docker", "build"]:
                    Path(rendered[rendered.index("--iidfile") + 1]).write_text(
                        runtime_image_id + "\n",
                        encoding="utf-8",
                    )
                if "init-secrets" in rendered:
                    init_call_count += 1
                    payload = created if init_call_count == 1 else unchanged
                    return subprocess.CompletedProcess(
                        rendered,
                        0,
                        json.dumps(payload),
                        "",
                    )
                if rendered[:2] == ["docker", "exec"]:
                    return subprocess.CompletedProcess(rendered, 0, "ready", "")
                if "--inside" in rendered:
                    out_mount = next(
                        argument for argument in rendered if argument.endswith(":/out")
                    )
                    container_output = Path(out_mount.rsplit(":", 1)[0]) / output_path.name
                    container_output.write_text(
                        json.dumps(
                            _report(
                                module,
                                secret_contract_hash=secret_contract_hash,
                                runtime_image_id_hash=runtime_image_id_hash,
                            ),
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
                    container_output.chmod(0o444)
                if cleanup_kind == "runtime_data" and module._RUNTIME_DATA_CLEANUP_CODE in rendered:
                    return subprocess.CompletedProcess(rendered, 1, "", private_failure)
                return subprocess.CompletedProcess(rendered, 0, "", "")

            with (
                _portable_handoff_owner(module),
                patch.object(module, "_run_command", side_effect=fake_run),
                redirect_stderr(stderr),
            ):
                exit_code = module.main(
                    [
                        "--output",
                        str(output_path),
                        "--execution-authority-output",
                        str(authority_path),
                        "--execution-authority-pin-output",
                        str(authority_pin_path),
                        "--failure-diagnostic-output",
                        str(diagnostic_path),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(
                json.loads(stderr.getvalue()),
                {"error": "operator_journey_failed", "status": "error"},
            )
            self.assertFalse(output_path.exists())
            self.assertTrue(authority_path.is_file())
            self.assertTrue(authority_pin_path.is_file())
            self.assertTrue(diagnostic_path.is_file())
            self.assertEqual(
                json.loads(diagnostic_path.read_text(encoding="utf-8")),
                {
                    "artifact_id": module.FAILURE_DIAGNOSTIC_ARTIFACT_ID,
                    "failure_code": "stage_failed",
                    "schema_version": 1,
                    "stage": "outer_runtime_cleanup",
                    "status": "failed",
                },
            )
            self.assertEqual(calls[-1], ["docker", "image", "rm", "--force", runtime_image_id])
            rendered_public = stderr.getvalue() + diagnostic_path.read_text(encoding="utf-8")
            self.assertNotIn(private_failure, rendered_public)
            self.assertNotIn("/private/", rendered_public)
            with self.assertRaisesRegex(
                issue20_packet_module.EvidencePacketError,
                "^operator_evidence_report_invalid$",
            ):
                issue20_packet_module._operator_layer_from_report(
                    None,
                    operator_attested=True,
                    trusted_execution_authority=json.loads(
                        authority_path.read_text(encoding="utf-8")
                    ),
                    trusted_execution_authority_pin=json.loads(
                        authority_pin_path.read_text(encoding="utf-8")
                    ),
                )
            with (
                patch.object(module, "_run_command") as retry_command,
                self.assertRaisesRegex(
                    RuntimeError,
                    "^operator_journey_execution_authority_already_exists$",
                ),
            ):
                module.run_outer(
                    output_path,
                    postgres_image=module.PINNED_POSTGRES_IMAGE,
                    execution_authority_output_path=authority_path,
                    execution_authority_pin_output_path=authority_pin_path,
                    failure_diagnostic_output_path=diagnostic_path,
                )
            retry_command.assert_not_called()
            self.assertFalse(output_path.exists())

        cleanup_kind = "temporary_directory"
        init_call_count = 0
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_path = root / "operator-live.json"
            authority_path = root / "operator-authority.json"
            authority_pin_path = root / "operator-authority-pin.json"
            diagnostic_path = root / "operator-failure-diagnostic.json"
            stderr = io.StringIO()
            internal_temporary = tempfile.TemporaryDirectory()
            cleanup_calls: list[bool] = []

            class FailingTemporaryDirectory:
                name = internal_temporary.name

                def cleanup(self) -> None:
                    cleanup_calls.append(True)
                    raise RuntimeError(private_temporary_failure)

            try:
                with (
                    _portable_handoff_owner(module),
                    patch.object(module, "_run_command", side_effect=fake_run),
                    patch.object(
                        module.tempfile,
                        "TemporaryDirectory",
                        return_value=FailingTemporaryDirectory(),
                    ),
                    redirect_stderr(stderr),
                ):
                    exit_code = module.main(
                        [
                            "--output",
                            str(output_path),
                            "--execution-authority-output",
                            str(authority_path),
                            "--execution-authority-pin-output",
                            str(authority_pin_path),
                            "--failure-diagnostic-output",
                            str(diagnostic_path),
                        ]
                    )
            finally:
                internal_temporary.cleanup()

            self.assertEqual(exit_code, 1)
            self.assertEqual(cleanup_calls, [True])
            self.assertEqual(
                json.loads(stderr.getvalue()),
                {"error": "operator_journey_failed", "status": "error"},
            )
            self.assertFalse(output_path.exists())
            self.assertTrue(authority_path.is_file())
            self.assertTrue(authority_pin_path.is_file())
            self.assertEqual(
                json.loads(diagnostic_path.read_text(encoding="utf-8")),
                {
                    "artifact_id": module.FAILURE_DIAGNOSTIC_ARTIFACT_ID,
                    "failure_code": "stage_failed",
                    "schema_version": 1,
                    "stage": "outer_runtime_cleanup",
                    "status": "failed",
                },
            )
            self.assertEqual(calls[-1], ["docker", "image", "rm", "--force", runtime_image_id])
            rendered_public = stderr.getvalue() + diagnostic_path.read_text(encoding="utf-8")
            self.assertNotIn(private_temporary_failure, rendered_public)
            self.assertNotIn("/private/", rendered_public)

    def test_outer_report_handoff_rejects_untrusted_metadata_and_bytes(self) -> None:
        module = _load_module("connected_operator_live_outer_report_handoff")
        created = {
            "status": "ok",
            "secret_set_state": "created",
            "secret_file_count": 6,
            "created_file_count": 6,
            "initialization_contract_hash": _HASH_A,
            "google_client_secret_generated": False,
            "requires_operator_google_client_secret": True,
            "supports_connected_preflight_ready": False,
        }
        unchanged = {
            **created,
            "secret_set_state": "unchanged",
            "created_file_count": 0,
        }
        secret_contract_hash = module._sha256_json({"generated": created, "unchanged": unchanged})
        runtime_image_id = "sha256:" + "1" * 64
        runtime_image_id_hash = module._sha256_bytes(runtime_image_id.encode("utf-8"))
        real_os_read = module.os.read

        for case in (
            "wrong_mode",
            "wrong_owner",
            "hardlink",
            "symlink",
            "duplicate_key",
            "path_swap",
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output_path = root / "operator-live.json"
                authority_path = root / "operator-authority.json"
                authority_pin_path = root / "operator-authority-pin.json"
                init_call_count = 0
                mounted_report_path: Path | None = None
                canonical_payload = json.dumps(
                    _report(
                        module,
                        secret_contract_hash=secret_contract_hash,
                        runtime_image_id_hash=runtime_image_id_hash,
                    ),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")

                def fake_run(command, *, environ=None, check=True):
                    nonlocal init_call_count, mounted_report_path
                    del environ, check
                    rendered = list(command)
                    if rendered[:2] == ["docker", "build"]:
                        Path(rendered[rendered.index("--iidfile") + 1]).write_text(
                            runtime_image_id + "\n",
                            encoding="utf-8",
                        )
                    if "init-secrets" in rendered:
                        init_call_count += 1
                        payload = created if init_call_count == 1 else unchanged
                        return subprocess.CompletedProcess(
                            rendered,
                            0,
                            json.dumps(payload),
                            "",
                        )
                    if rendered[:2] == ["docker", "exec"]:
                        return subprocess.CompletedProcess(rendered, 0, "ready", "")
                    if "--inside" in rendered:
                        out_mount = next(
                            argument for argument in rendered if argument.endswith(":/out")
                        )
                        mounted_out = Path(out_mount.rsplit(":", 1)[0])
                        mounted_report_path = mounted_out / output_path.name
                        report_payload = canonical_payload
                        if case == "duplicate_key":
                            report_payload = report_payload.replace(
                                b'  "status": "passed"\n}',
                                b'  "status": "passed",\n  "status": "passed"\n}',
                                1,
                            )
                        if case == "symlink":
                            target = mounted_out / "untrusted-report-target.json"
                            target.write_bytes(report_payload)
                            target.chmod(0o444)
                            mounted_report_path.symlink_to(target)
                        else:
                            mounted_report_path.write_bytes(report_payload)
                            mounted_report_path.chmod(0o600 if case == "wrong_mode" else 0o444)
                            if case == "hardlink":
                                os.link(
                                    mounted_report_path,
                                    mounted_out / "untrusted-report-hardlink.json",
                                )
                    return subprocess.CompletedProcess(rendered, 0, "", "")

                path_swapped = False

                def read_with_optional_path_swap(descriptor: int, size: int) -> bytes:
                    nonlocal path_swapped
                    chunk = real_os_read(descriptor, size)
                    if case == "path_swap" and not path_swapped and mounted_report_path is not None:
                        descriptor_metadata = os.fstat(descriptor)
                        path_metadata = mounted_report_path.lstat()
                        is_report_descriptor = (
                            descriptor_metadata.st_dev,
                            descriptor_metadata.st_ino,
                        ) == (
                            path_metadata.st_dev,
                            path_metadata.st_ino,
                        )
                    else:
                        is_report_descriptor = False
                    if is_report_descriptor:
                        assert mounted_report_path is not None
                        replacement = mounted_report_path.with_name(
                            "untrusted-report-replacement.json"
                        )
                        replacement.write_bytes(canonical_payload)
                        replacement.chmod(0o444)
                        os.replace(replacement, mounted_report_path)
                        path_swapped = True
                    return chunk

                expected_handoff_uid = os.getuid() + (case == "wrong_owner")
                with (
                    patch.multiple(
                        module,
                        _FAILURE_STAGE_HANDOFF_OWNER_UID=expected_handoff_uid,
                        _FAILURE_STAGE_HANDOFF_OWNER_GID=os.getgid(),
                    ),
                    patch.object(module, "_run_command", side_effect=fake_run),
                    patch.object(module.os, "read", side_effect=read_with_optional_path_swap),
                    self.assertRaisesRegex(
                        RuntimeError,
                        "^operator_journey_report_invalid$",
                    ),
                ):
                    module.run_outer(
                        output_path,
                        postgres_image=module.PINNED_POSTGRES_IMAGE,
                        execution_authority_output_path=authority_path,
                        execution_authority_pin_output_path=authority_pin_path,
                    )

                self.assertFalse(output_path.exists())
                self.assertTrue(authority_path.is_file())
                self.assertTrue(authority_pin_path.is_file())
                self.assertEqual(authority_path.stat().st_mode & 0o777, 0o400)
                self.assertEqual(authority_pin_path.stat().st_mode & 0o777, 0o400)
                self.assertEqual(
                    {path.name for path in root.iterdir()},
                    {authority_path.name, authority_pin_path.name},
                )
                self.assertFalse(output_path.with_suffix(f"{output_path.suffix}.tmp").exists())
                self.assertEqual(
                    list(root.glob(f".{output_path.name}.*.bak")),
                    [],
                )
                self.assertEqual(init_call_count, 2)
                if case == "path_swap":
                    self.assertTrue(path_swapped)

    def test_missing_or_invalid_build_iid_stops_before_runtime_run(self) -> None:
        module = _load_module("connected_operator_live_invalid_iid")
        for name, iid_value in (
            ("missing", None),
            ("mutable_tag", "formowl-runtime:local"),
            ("short_digest", "sha256:runtime-image"),
        ):
            with self.subTest(name=name):
                calls: list[list[str]] = []
                with tempfile.TemporaryDirectory() as temporary:
                    output_path = Path(temporary) / "operator-live.json"

                    def fake_run(command, *, environ=None, check=True):
                        del environ, check
                        rendered = list(command)
                        calls.append(rendered)
                        if iid_value is not None:
                            Path(rendered[rendered.index("--iidfile") + 1]).write_text(
                                iid_value + "\n",
                                encoding="utf-8",
                            )
                        return subprocess.CompletedProcess(rendered, 0, "", "")

                    with (
                        patch.object(module, "_run_command", side_effect=fake_run),
                        self.assertRaises(RuntimeError),
                    ):
                        module.run_outer(
                            output_path,
                            postgres_image=module.PINNED_POSTGRES_IMAGE,
                        )

                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][:2], ["docker", "build"])
                self.assertFalse(any(command[:2] == ["docker", "run"] for command in calls))

    def test_mutable_postgres_override_is_rejected_before_docker(self) -> None:
        module = _load_module("connected_operator_live_postgres_drift")
        with (
            patch.object(module, "_run_command") as run_command,
            self.assertRaisesRegex(RuntimeError, "^operator_journey_postgres_image_invalid$"),
        ):
            module.run_outer(
                Path("/tmp/not-created-operator-live.json"),
                postgres_image="pgvector/pgvector:0.8.0-pg17",
            )
        run_command.assert_not_called()

    def test_inside_requires_exact_runtime_iid_authority_before_cli(self) -> None:
        module = _load_module("connected_operator_live_inside_iid")
        runtime_image_id = "sha256:" + "1" * 64
        base_environment = {
            module._IMPLEMENTATION_CONTRACT_HASH_ENV: _HASH_A,
            module._RUNTIME_IMAGE_ID_HASH_ENV: module._sha256_bytes(
                runtime_image_id.encode("utf-8")
            ),
            module._SECRET_CONTRACT_HASH_ENV: _HASH_C,
        }
        cases = (
            (
                "missing_cli",
                None,
                {**base_environment, module._RUNTIME_IMAGE_ID_ENV: runtime_image_id},
            ),
            ("missing_authority", runtime_image_id, base_environment),
            (
                "authority_mismatch",
                runtime_image_id,
                {
                    **base_environment,
                    module._RUNTIME_IMAGE_ID_ENV: "sha256:" + "2" * 64,
                },
            ),
            (
                "hash_mismatch",
                runtime_image_id,
                {
                    **base_environment,
                    module._RUNTIME_IMAGE_ID_ENV: runtime_image_id,
                    module._RUNTIME_IMAGE_ID_HASH_ENV: _HASH_B,
                },
            ),
        )
        for name, cli_image_id, environment in cases:
            with self.subTest(name=name):
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(module, "_run_operator_cli") as run_operator_cli,
                    self.assertRaises(RuntimeError),
                ):
                    module.run_inside(
                        Path("/tmp/not-created-inside-report.json"),
                        runtime_image_id=cli_image_id,
                    )
                run_operator_cli.assert_not_called()

    def test_inside_success_binds_runtime_and_emits_only_safe_report(self) -> None:
        module = _load_module("connected_operator_live_inside_success")
        runtime_image_id = "sha256:" + "1" * 64
        environment = {
            module._IMPLEMENTATION_CONTRACT_HASH_ENV: _HASH_A,
            module._RUNTIME_IMAGE_ID_ENV: runtime_image_id,
            module._RUNTIME_IMAGE_ID_HASH_ENV: module._sha256_bytes(
                runtime_image_id.encode("utf-8")
            ),
            module._SECRET_CONTRACT_HASH_ENV: _HASH_C,
        }
        output_labels = (
            "bootstrap-owner",
            "invite-member",
            "lookup-owner",
            "list-users",
            "list-member-sessions-before",
            "revoke-member-session",
            "lookup-member-session-after-revoke",
            "remove-member",
            "restore-member",
            "list-member-sessions-after-restore",
        )
        outputs = {
            label: {"result_hash": module._sha256_json({"label": label}), "status": "ok"}
            for label in output_labels
        }
        bootstrap_invitation_id = "invite_operator_bootstrap_success"
        member_invitation_id = "invite_operator_member_success"
        outputs["bootstrap-owner"]["invitation_id"] = bootstrap_invitation_id
        outputs["invite-member"]["invitation_id"] = member_invitation_id
        denial_hashes = {
            "last-owner-removal-denied": _HASH_A,
            "member-approval-denied": _HASH_B,
            "unauthorized-list-users": _HASH_C,
        }
        migration = {"migration_hash": _HASH_D, "status": "ok"}
        migration_process = subprocess.CompletedProcess(
            ["formowl-connected-mcp", "migrate"],
            0,
            json.dumps(migration),
            "",
        )

        class Config:
            database_dsn = "postgresql://private-operator-success"

        class Repository:
            def __init__(self) -> None:
                self.close_count = 0

            def close(self) -> None:
                self.close_count += 1

        seed_repository = Repository()
        verification_repository = Repository()
        repositories = [seed_repository, verification_repository]

        def connect(database_dsn: str):
            self.assertEqual(database_dsn, Config.database_dsn)
            return repositories.pop(0)

        with tempfile.TemporaryDirectory() as temporary:
            output_path = Path(temporary) / "inside-report.json"
            diagnostic_path = Path(temporary) / "inside-failure-diagnostic.json"
            with (
                patch.dict(os.environ, environment, clear=True),
                patch.object(module, "_require_nonroot_runtime") as require_nonroot,
                patch.object(
                    module,
                    "_run_operator_cli",
                    return_value=(migration, migration_process),
                ) as run_operator_cli,
                patch.object(module, "_seed_operator_records") as seed_records,
                patch.object(
                    module,
                    "_execute_operator_v2_commands",
                    return_value=(outputs, denial_hashes, []),
                ) as execute_commands,
                patch.object(
                    module,
                    "_run_operator_rollback_probe",
                    return_value={
                        "probe_count": 1,
                        "preserved_state_count": 1,
                        "state_hash": _HASH_E,
                    },
                ) as rollback_probe,
                patch.object(
                    module,
                    "_operator_audit_summary",
                    return_value={
                        "total_count": 13,
                        "allowed_count": 10,
                        "denied_count": 3,
                        "contract_hash": _HASH_D,
                    },
                ) as audit_summary,
                patch(
                    "formowl_auth.postgres.PostgreSQLOAuthRepository.connect",
                    side_effect=connect,
                ) as repository_connect,
                patch(
                    "formowl_gateway.runtime.ConnectedRuntimeConfig.from_env_and_secrets",
                    return_value=Config(),
                ) as load_config,
                patch.object(module.subprocess, "run") as process_run,
            ):
                report = module.run_inside(
                    output_path,
                    runtime_image_id=runtime_image_id,
                    failure_stage_handoff_output_path=diagnostic_path,
                )

            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")),
                report,
            )
            self.assertEqual(output_path.stat().st_mode & 0o777, 0o444)
            self.assertEqual(output_path.stat().st_nlink, 1)
            self.assertFalse(diagnostic_path.exists())

        require_nonroot.assert_called_once_with()
        run_operator_cli.assert_called_once_with(["migrate"], environ=environment)
        seed_records.assert_called_once_with(seed_repository)
        execute_commands.assert_called_once_with(environment)
        rollback_probe.assert_called_once_with(verification_repository)
        audit_summary.assert_called_once_with(
            verification_repository,
            bootstrap_invitation_id=bootstrap_invitation_id,
            member_invitation_id=member_invitation_id,
        )
        self.assertEqual(repository_connect.call_count, 2)
        load_config.assert_called_once_with(environment)
        process_run.assert_not_called()
        self.assertEqual(seed_repository.close_count, 1)
        self.assertEqual(verification_repository.close_count, 1)
        self.assertEqual(repositories, [])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["counts"]["operator_cli_success_count"], 10)
        self.assertEqual(report["counts"]["operator_cli_denial_count"], 3)
        self.assertEqual(report["counts"]["operator_audit_total_count"], 13)
        self.assertEqual(report["counts"]["operator_audit_allowed_count"], 10)
        self.assertEqual(report["counts"]["operator_audit_denied_count"], 3)
        self.assertEqual(report["counts"]["explicit_token_revocation_count"], 1)
        self.assertEqual(report["counts"]["post_restore_active_session_count"], 0)
        self.assertEqual(report["counts"]["post_restore_inactive_session_count"], 2)
        self.assertEqual(report["counts"]["transaction_rollback_probe_count"], 1)
        self.assertEqual(
            report["counts"]["transaction_rollback_preserved_state_count"],
            1,
        )
        self.assertTrue(report["attestations"]["operator_allow_and_deny_audits_persisted"])
        self.assertTrue(report["attestations"]["membership_rollback_verified"])
        rendered_report = json.dumps(report, sort_keys=True)
        self.assertNotIn(Config.database_dsn, rendered_report)
        self.assertNotIn("example.test", rendered_report)

    def test_inside_report_creation_failures_cleanup_exact_inode_and_allow_retry(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_inside_report_cleanup")
        runtime_image_id = "sha256:" + "1" * 64
        environment = {
            module._IMPLEMENTATION_CONTRACT_HASH_ENV: _HASH_A,
            module._RUNTIME_IMAGE_ID_ENV: runtime_image_id,
            module._RUNTIME_IMAGE_ID_HASH_ENV: module._sha256_bytes(
                runtime_image_id.encode("utf-8")
            ),
            module._SECRET_CONTRACT_HASH_ENV: _HASH_C,
        }
        outputs = {
            "bootstrap-owner": {
                "invitation_id": "invite_operator_bootstrap_cleanup",
                "status": "ok",
            },
            "invite-member": {
                "invitation_id": "invite_operator_member_cleanup",
                "status": "ok",
            },
        }
        migration = {"migration_hash": _HASH_D, "status": "ok"}
        migration_process = subprocess.CompletedProcess(
            ["formowl-connected-mcp", "migrate"],
            0,
            json.dumps(migration),
            "",
        )
        private_failure = "private report persistence failure /private/report/path"
        replacement_bytes = b"replacement-report-must-survive\n"
        real_fchmod = module.os.fchmod
        real_fstat = module.os.fstat
        real_fsync = module.os.fsync
        real_stat = module.os.stat
        real_write = module.os.write

        class Config:
            database_dsn = "postgresql://private-report-cleanup"

        class Repository:
            def close(self) -> None:
                return None

        def exercise(case: str, *, replacement: bool = False) -> None:
            counters = {"fchmod": 0, "fstat": 0, "fsync": 0, "stat": 0}
            pending_failures = (
                {"initial_stat", "identity_fstat"}
                if case == "identity_probes_exhausted"
                else {case}
            )
            replacement_installed = False
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output_path = root / "inside-report.json"

                def fail(stage: str) -> None:
                    nonlocal replacement_installed
                    if stage not in pending_failures:
                        return
                    pending_failures.remove(stage)
                    if replacement and not replacement_installed:
                        replacement_path = root / "replacement-report.json"
                        replacement_path.write_bytes(replacement_bytes)
                        os.replace(replacement_path, output_path)
                        replacement_installed = True
                    raise OSError(private_failure)

                def fchmod(descriptor: int, mode: int) -> None:
                    counters["fchmod"] += 1
                    fail("initial_fchmod" if counters["fchmod"] == 1 else "final_fchmod")
                    real_fchmod(descriptor, mode)

                def fstat(descriptor: int):
                    counters["fstat"] += 1
                    if counters["fchmod"] == 0:
                        fail("identity_fstat")
                    else:
                        fail("initial_fstat" if counters["fstat"] == 1 else "final_fstat")
                    return real_fstat(descriptor)

                def fsync(descriptor: int) -> None:
                    counters["fsync"] += 1
                    fail("persist_fsync" if counters["fsync"] == 1 else "final_fsync")
                    real_fsync(descriptor)

                def stat_path(
                    path: int | str | bytes | os.PathLike[str],
                    *args: object,
                    **kwargs: object,
                ):
                    if isinstance(path, int):
                        counters["stat"] += 1
                        fail("initial_stat")
                    return real_stat(path, *args, **kwargs)

                def write(descriptor: int, value: bytes | memoryview) -> int:
                    fail("write")
                    return real_write(descriptor, value)

                arguments = [
                    "--inside",
                    "--runtime-image-id",
                    runtime_image_id,
                    "--output",
                    str(output_path),
                ]
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(module, "_require_nonroot_runtime"),
                    patch.object(
                        module,
                        "_run_operator_cli",
                        return_value=(migration, migration_process),
                    ),
                    patch.object(module, "_seed_operator_records"),
                    patch.object(
                        module,
                        "_execute_operator_v2_commands",
                        return_value=(outputs, {}, []),
                    ),
                    patch.object(
                        module,
                        "_run_operator_rollback_probe",
                        return_value={
                            "probe_count": 1,
                            "preserved_state_count": 1,
                            "state_hash": _HASH_E,
                        },
                    ),
                    patch.object(
                        module,
                        "_operator_audit_summary",
                        return_value={
                            "total_count": 2,
                            "allowed_count": 2,
                            "denied_count": 0,
                            "contract_hash": _HASH_D,
                        },
                    ),
                    patch(
                        "formowl_auth.postgres.PostgreSQLOAuthRepository.connect",
                        side_effect=lambda _dsn: Repository(),
                    ),
                    patch(
                        "formowl_gateway.runtime.ConnectedRuntimeConfig.from_env_and_secrets",
                        return_value=Config(),
                    ),
                    patch.object(module, "_validate_report_body", return_value={"passed": True}),
                    patch.object(module.os, "fchmod", side_effect=fchmod),
                    patch.object(module.os, "fstat", side_effect=fstat),
                    patch.object(module.os, "fsync", side_effect=fsync),
                    patch.object(module.os, "stat", side_effect=stat_path),
                    patch.object(module.os, "write", side_effect=write),
                    redirect_stderr(io.StringIO()) as stderr,
                ):
                    self.assertEqual(module.main(arguments), 1)
                    self.assertEqual(
                        json.loads(stderr.getvalue()),
                        {"error": "operator_journey_failed", "status": "error"},
                    )
                    self.assertNotIn(private_failure, stderr.getvalue())
                    if case == "identity_probes_exhausted":
                        preserved_metadata = output_path.lstat()
                        preserved_identity = (
                            preserved_metadata.st_dev,
                            preserved_metadata.st_ino,
                            preserved_metadata.st_uid,
                            preserved_metadata.st_gid,
                        )
                        if replacement:
                            self.assertEqual(output_path.read_bytes(), replacement_bytes)
                        else:
                            self.assertTrue(stat.S_ISREG(preserved_metadata.st_mode))
                            self.assertEqual(
                                stat.S_IMODE(preserved_metadata.st_mode),
                                0o200,
                            )
                            self.assertEqual(preserved_metadata.st_nlink, 1)
                            self.assertEqual(preserved_metadata.st_size, 0)
                        self.assertEqual(list(root.iterdir()), [output_path])

                        stderr.seek(0)
                        stderr.truncate(0)
                        self.assertEqual(module.main(arguments), 1)
                        self.assertEqual(
                            json.loads(stderr.getvalue()),
                            {
                                "error": "operator_journey_failed",
                                "status": "error",
                            },
                        )
                        retry_metadata = output_path.lstat()
                        self.assertEqual(
                            (
                                retry_metadata.st_dev,
                                retry_metadata.st_ino,
                                retry_metadata.st_uid,
                                retry_metadata.st_gid,
                            ),
                            preserved_identity,
                        )
                        if replacement:
                            self.assertEqual(output_path.read_bytes(), replacement_bytes)
                        output_path.unlink()
                    elif replacement:
                        self.assertEqual(output_path.read_bytes(), replacement_bytes)
                        self.assertEqual(list(root.iterdir()), [output_path])
                        output_path.unlink()
                    else:
                        self.assertFalse(output_path.exists())
                        self.assertEqual(list(root.iterdir()), [])

                    stderr.seek(0)
                    stderr.truncate(0)
                    self.assertEqual(module.main(arguments), 0)
                    self.assertEqual(stderr.getvalue(), "")
                    self.assertEqual(
                        json.loads(output_path.read_text(encoding="utf-8"))["status"],
                        "passed",
                    )
                    self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o444)
                    self.assertEqual(list(root.iterdir()), [output_path])

        for case in (
            "initial_stat",
            "initial_fchmod",
            "initial_fstat",
            "write",
            "persist_fsync",
            "final_fchmod",
            "final_fstat",
            "final_fsync",
        ):
            with self.subTest(case=case):
                exercise(case)

        with self.subTest(case="initial_fstat_replacement"):
            exercise("initial_fstat", replacement=True)

        with self.subTest(case="initial_stat_replacement"):
            exercise("initial_stat", replacement=True)

        with self.subTest(case="identity_probes_exhausted"):
            exercise("identity_probes_exhausted")

        with self.subTest(case="identity_probes_exhausted_replacement"):
            exercise("identity_probes_exhausted", replacement=True)

    def test_nonroot_runtime_requires_all_five_capability_sets_zero(self) -> None:
        module = _load_module("connected_operator_live_nonroot_capabilities")
        valid_status = {
            "CapInh": "0000000000000000",
            "CapPrm": "0000000000000000",
            "CapEff": "0000000000000000",
            "CapBnd": "0000000000000000",
            "CapAmb": "0000000000000000",
            "NoNewPrivs": "1",
        }

        def status_text(values: dict[str, str]) -> str:
            return "\n".join(f"{key}:\t{value}" for key, value in values.items())

        with (
            patch.object(module.Path, "read_text", return_value=status_text(valid_status)),
            patch.object(module.os, "geteuid", return_value=10001),
            patch.object(module.os, "getegid", return_value=10001),
            patch.object(module.os, "getgroups", return_value=[]),
            patch.object(module.subprocess, "run") as process_run,
        ):
            module._require_nonroot_runtime()
        process_run.assert_not_called()
        self.assertEqual(
            valid_status,
            {
                "CapInh": "0000000000000000",
                "CapPrm": "0000000000000000",
                "CapEff": "0000000000000000",
                "CapBnd": "0000000000000000",
                "CapAmb": "0000000000000000",
                "NoNewPrivs": "1",
            },
        )

        for capability_field in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
            for invalid_kind, invalid_value in (
                ("missing", None),
                ("malformed", "not-hex"),
                ("nonzero", "0000000000000001"),
            ):
                with self.subTest(
                    capability_field=capability_field,
                    invalid_kind=invalid_kind,
                ):
                    invalid_status = dict(valid_status)
                    if invalid_value is None:
                        invalid_status.pop(capability_field)
                    else:
                        invalid_status[capability_field] = invalid_value
                    original_status = dict(invalid_status)
                    with (
                        patch.object(
                            module.Path,
                            "read_text",
                            return_value=status_text(invalid_status),
                        ),
                        patch.object(module.os, "geteuid", return_value=10001),
                        patch.object(module.os, "getegid", return_value=10001),
                        patch.object(module.os, "getgroups", return_value=[]),
                        patch.object(module.subprocess, "run") as process_run,
                        self.assertRaisesRegex(
                            RuntimeError,
                            "^operator_journey_runtime_security_invalid$",
                        ),
                    ):
                        module._require_nonroot_runtime()
                    process_run.assert_not_called()
                    self.assertEqual(invalid_status, original_status)

        identity_probes = (
            ("wrong_uid", 0, 10001, [], "1"),
            ("wrong_gid", 10001, 0, [], "1"),
            ("supplementary_groups", 10001, 10001, [10001], "1"),
            ("no_new_privileges_disabled", 10001, 10001, [], "0"),
        )
        for probe_name, uid, gid, groups, no_new_privileges in identity_probes:
            with self.subTest(probe_name=probe_name):
                invalid_status = {
                    **valid_status,
                    "NoNewPrivs": no_new_privileges,
                }
                with (
                    patch.object(
                        module.Path,
                        "read_text",
                        return_value=status_text(invalid_status),
                    ),
                    patch.object(module.os, "geteuid", return_value=uid),
                    patch.object(module.os, "getegid", return_value=gid),
                    patch.object(module.os, "getgroups", return_value=groups),
                    patch.object(module.subprocess, "run") as process_run,
                    self.assertRaisesRegex(
                        RuntimeError,
                        "^operator_journey_runtime_security_invalid$",
                    ),
                ):
                    module._require_nonroot_runtime()
                process_run.assert_not_called()

        for invalid_kind, read_value in (
            ("missing_no_new_privileges", status_text(valid_status).replace("NoNewPrivs:\t1", "")),
            ("malformed_status_line", "CapInh:\n"),
        ):
            with self.subTest(invalid_kind=invalid_kind):
                with (
                    patch.object(module.Path, "read_text", return_value=read_value),
                    patch.object(module.os, "geteuid", return_value=10001),
                    patch.object(module.os, "getegid", return_value=10001),
                    patch.object(module.os, "getgroups", return_value=[]),
                    patch.object(module.subprocess, "run") as process_run,
                    self.assertRaisesRegex(
                        RuntimeError,
                        "^operator_journey_runtime_security_invalid$",
                    ),
                ):
                    module._require_nonroot_runtime()
                process_run.assert_not_called()

        with (
            patch.object(module.Path, "read_text", side_effect=OSError("unavailable")),
            patch.object(module.os, "geteuid", return_value=10001),
            patch.object(module.os, "getegid", return_value=10001),
            patch.object(module.os, "getgroups", return_value=[]),
            patch.object(module.subprocess, "run") as process_run,
            self.assertRaisesRegex(
                RuntimeError,
                "^operator_journey_runtime_security_invalid$",
            ),
        ):
            module._require_nonroot_runtime()
        process_run.assert_not_called()

    def test_command_boundary_is_exact_and_redacts_process_failures(self) -> None:
        module = _load_module("connected_operator_live_command_boundary")
        command = ("synthetic-command", "--safe-argument")
        environment = {"FORMOWL_SAFE_SETTING": "safe-value"}
        safe_failure = subprocess.CompletedProcess(
            list(command),
            1,
            "",
            "\n".join(
                (
                    json.dumps({"error": "operator_unauthorized", "status": "error"}),
                    json.dumps(
                        {
                            "error": "postgresql://private-backend/formowl",
                            "status": "error",
                        }
                    ),
                )
            ),
        )
        self.assertEqual(
            module._safe_process_error(safe_failure),
            "operator_unauthorized",
        )
        private_failure = subprocess.CompletedProcess(
            list(command),
            1,
            "",
            "private traceback: /tmp/formowl-operator/private-output.json",
        )
        self.assertEqual(
            module._safe_process_error(private_failure),
            "operator_journey_command_failed",
        )
        identifier_shaped_private_failure = subprocess.CompletedProcess(
            list(command),
            1,
            "",
            json.dumps(
                {
                    "error": "child_private_context_identifier",
                    "status": "error",
                }
            ),
        )
        self.assertEqual(
            module._safe_process_error(identifier_shaped_private_failure),
            "operator_journey_command_failed",
        )

        with patch.object(
            module.subprocess,
            "run",
            return_value=safe_failure,
        ) as process_run:
            result = module._run_command(
                command,
                environ=environment,
                check=False,
            )
            self.assertIs(result, safe_failure)
            with self.assertRaisesRegex(RuntimeError, "^operator_unauthorized$"):
                module._run_command(
                    command,
                    environ=environment,
                )
        self.assertEqual(process_run.call_count, 2)
        process_run.assert_called_with(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(command, ("synthetic-command", "--safe-argument"))
        self.assertEqual(environment, {"FORMOWL_SAFE_SETTING": "safe-value"})

        with (
            patch.object(
                module.subprocess,
                "run",
                return_value=identifier_shaped_private_failure,
            ),
            self.assertRaisesRegex(
                RuntimeError,
                "^operator_journey_command_failed$",
            ),
        ):
            module._run_command(command, environ=environment)

        success_payload = {"result_count": 1, "status": "ok"}
        success_process = subprocess.CompletedProcess(
            ["formowl-connected-mcp", "list-users"],
            0,
            json.dumps(success_payload),
            "",
        )
        with patch.object(
            module,
            "_run_command",
            return_value=success_process,
        ) as run_command:
            payload, process = module._run_operator_cli(
                ["list-users"],
                environ=environment,
            )
        self.assertEqual(payload, success_payload)
        self.assertIs(process, success_process)
        run_command.assert_called_once_with(
            ["formowl-connected-mcp", "list-users"],
            environ=environment,
            check=False,
        )

        for stdout in ("not-json", json.dumps(["not", "an", "object"])):
            with (
                self.subTest(stdout=stdout),
                self.assertRaisesRegex(
                    RuntimeError,
                    "^operator_journey_output_invalid$",
                ),
            ):
                module._parse_json_output(
                    subprocess.CompletedProcess(
                        ["formowl-connected-mcp", "list-users"],
                        0,
                        stdout,
                        "",
                    )
                )
        with self.assertRaisesRegex(
            RuntimeError,
            "^operator_journey_command_failed$",
        ):
            module._parse_json_output(private_failure)

        denial_process = subprocess.CompletedProcess(
            ["formowl-connected-mcp", "list-users"],
            1,
            "",
            json.dumps({"error": "operator_unauthorized", "status": "error"}),
        )
        with patch.object(
            module,
            "_run_command",
            return_value=denial_process,
        ) as run_command:
            payload, process = module._run_operator_cli(
                ["list-users"],
                environ=environment,
                expected_error="operator_unauthorized",
            )
        self.assertIsNone(payload)
        self.assertIs(process, denial_process)
        run_command.assert_called_once_with(
            ["formowl-connected-mcp", "list-users"],
            environ=environment,
            check=False,
        )
        self.assertNotIn("private", json.dumps(payload))

        malformed_denial = subprocess.CompletedProcess(
            ["formowl-connected-mcp", "list-users"],
            1,
            "",
            "private malformed denial",
        )
        with (
            patch.object(module, "_run_command", return_value=malformed_denial),
            self.assertRaisesRegex(
                RuntimeError,
                "^operator_journey_denial_invalid$",
            ),
        ):
            module._run_operator_cli(
                ["list-users"],
                environ=environment,
                expected_error="operator_unauthorized",
            )

    def test_cli_failure_diagnostic_is_finite_redacted_and_public_error_stays_generic(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_failure_diagnostic")
        private_failure = (
            "private account token secret payload SQL URL backend detail " "/private/operator/path"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_path = root / "operator-live.json"
            authority_path = root / "operator-authority.json"
            authority_pin_path = root / "operator-authority-pin.json"
            diagnostic_path = root / "operator-failure-diagnostic.json"
            stderr = io.StringIO()

            with (
                patch.object(
                    module,
                    "_run_command",
                    side_effect=RuntimeError(private_failure),
                ) as run_command,
                redirect_stderr(stderr),
            ):
                exit_code = module.main(
                    [
                        "--output",
                        str(output_path),
                        "--execution-authority-output",
                        str(authority_path),
                        "--execution-authority-pin-output",
                        str(authority_pin_path),
                        "--failure-diagnostic-output",
                        str(diagnostic_path),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(run_command.call_count, 1)
            self.assertEqual(
                json.loads(stderr.getvalue()),
                {"error": "operator_journey_failed", "status": "error"},
            )
            self.assertEqual(
                json.loads(diagnostic_path.read_text(encoding="utf-8")),
                {
                    "artifact_id": module.FAILURE_DIAGNOSTIC_ARTIFACT_ID,
                    "failure_code": "stage_failed",
                    "schema_version": 1,
                    "stage": "outer_runtime_setup",
                    "status": "failed",
                },
            )
            self.assertEqual(len(module.FAILURE_DIAGNOSTIC_STAGES), 13)
            self.assertEqual(
                set(module.FAILURE_DIAGNOSTIC_STAGES),
                {
                    "inside_migration",
                    "inside_operator_commands",
                    "inside_report",
                    "inside_runtime_setup",
                    "inside_seed",
                    "inside_verification",
                    "outer_authority",
                    "outer_inner_journey",
                    "outer_postgresql",
                    "outer_report",
                    "outer_runtime_cleanup",
                    "outer_runtime_setup",
                    "outer_secret_set",
                },
            )
            self.assertFalse(output_path.exists())
            self.assertFalse(authority_path.exists())
            self.assertFalse(authority_pin_path.exists())
            rendered = stderr.getvalue() + diagnostic_path.read_text(encoding="utf-8")
            self.assertNotIn(private_failure, rendered)
            for forbidden in (
                "account",
                "token",
                "secret",
                "payload",
                "sql",
                "url",
                "backend",
                "/private/",
            ):
                self.assertNotIn(forbidden, rendered.lower())

        identifier_shaped_private_exception = "child_private_context_identifier"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_path = root / "operator-live.json"
            authority_path = root / "operator-authority.json"
            authority_pin_path = root / "operator-authority-pin.json"
            diagnostic_path = root / "operator-failure-diagnostic.json"
            stderr = io.StringIO()

            with (
                patch.object(
                    module,
                    "_run_command",
                    side_effect=RuntimeError(identifier_shaped_private_exception),
                ),
                redirect_stderr(stderr),
            ):
                exit_code = module.main(
                    [
                        "--output",
                        str(output_path),
                        "--execution-authority-output",
                        str(authority_path),
                        "--execution-authority-pin-output",
                        str(authority_pin_path),
                        "--failure-diagnostic-output",
                        str(diagnostic_path),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(
                json.loads(stderr.getvalue()),
                {"error": "operator_journey_failed", "status": "error"},
            )
            self.assertNotIn(identifier_shaped_private_exception, stderr.getvalue())

    def test_inside_failure_diagnostic_maps_migration_stage_without_private_detail(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_inside_failure_diagnostic")
        runtime_image_id = "sha256:" + "1" * 64
        environment = {
            module._IMPLEMENTATION_CONTRACT_HASH_ENV: _HASH_A,
            module._RUNTIME_IMAGE_ID_ENV: runtime_image_id,
            module._RUNTIME_IMAGE_ID_HASH_ENV: module._sha256_bytes(
                runtime_image_id.encode("utf-8")
            ),
            module._SECRET_CONTRACT_HASH_ENV: _HASH_C,
        }
        private_failure = "private account token SQL /private/operator/path"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_path = root / "inside-report.json"
            diagnostic_path = root / "inside-failure-diagnostic.json"
            with (
                patch.dict(os.environ, environment, clear=True),
                patch.object(module, "_require_nonroot_runtime"),
                patch.object(
                    module,
                    "_run_operator_cli",
                    side_effect=RuntimeError(private_failure),
                ),
                self.assertRaisesRegex(RuntimeError, "^private account token"),
            ):
                module.run_inside(
                    output_path,
                    runtime_image_id=runtime_image_id,
                    failure_stage_handoff_output_path=diagnostic_path,
                )

            self.assertFalse(output_path.exists())
            self.assertEqual(diagnostic_path.stat().st_mode & 0o777, 0o444)
            diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
            self.assertEqual(
                diagnostic,
                {
                    "artifact_id": module.FAILURE_DIAGNOSTIC_ARTIFACT_ID,
                    "failure_code": "stage_failed",
                    "schema_version": 1,
                    "stage": "inside_migration",
                    "status": "failed",
                },
            )
            self.assertNotIn(private_failure, json.dumps(diagnostic, sort_keys=True))

    def test_failure_stage_handoff_writer_never_masks_or_deletes_replacement(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_handoff_persistence")
        exact_document = {
            "artifact_id": module.FAILURE_DIAGNOSTIC_ARTIFACT_ID,
            "failure_code": "stage_failed",
            "schema_version": 1,
            "stage": "inside_seed",
            "status": "failed",
        }
        exact_payload = (
            json.dumps(
                exact_document,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "failure-stage-handoff.json"
            module._write_failure_stage_handoff(path, "inside_seed")
            self.assertEqual(path.read_bytes(), exact_payload)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
            self.assertEqual(path.stat().st_nlink, 1)

        for invalid_stage in (None, True, "outer_authority", "inside_private_backend"):
            with (
                self.subTest(invalid_stage=invalid_stage),
                tempfile.TemporaryDirectory() as temporary,
            ):
                path = Path(temporary) / "failure-stage-handoff.json"
                module._write_failure_stage_handoff(path, invalid_stage)
                self.assertFalse(path.exists())

        real_write = module.os.write
        for case in ("preexisting", "interrupted_write", "replacement_race"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "failure-stage-handoff.json"
                original_bytes = b"verifier-held-handoff\n"
                replacement_bytes = b"verifier-owned-replacement\n"
                if case == "preexisting":
                    path.write_bytes(original_bytes)
                    path.chmod(0o444)
                write_call_count = 0

                def fail_write(descriptor, value):
                    nonlocal write_call_count
                    write_call_count += 1
                    if write_call_count == 1:
                        partial_length = max(1, len(value) // 2)
                        return real_write(descriptor, value[:partial_length])
                    if case == "replacement_race":
                        path.unlink()
                        path.write_bytes(replacement_bytes)
                        path.chmod(0o444)
                    raise OSError("private handoff persistence failure")

                writer = (
                    patch.object(module.os, "write", side_effect=fail_write)
                    if case != "preexisting"
                    else nullcontext()
                )
                with writer:
                    module._write_failure_stage_handoff(path, "inside_seed")

                if case == "preexisting":
                    self.assertEqual(write_call_count, 0)
                    self.assertEqual(path.read_bytes(), original_bytes)
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
                elif case == "interrupted_write":
                    self.assertEqual(write_call_count, 2)
                    self.assertFalse(path.exists())
                else:
                    self.assertEqual(write_call_count, 2)
                    self.assertEqual(path.read_bytes(), replacement_bytes)
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)

    def test_failure_stage_handoff_validator_rejects_metadata_content_and_races(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_handoff_validation")
        exact_document = {
            "artifact_id": module.FAILURE_DIAGNOSTIC_ARTIFACT_ID,
            "failure_code": "stage_failed",
            "schema_version": 1,
            "stage": "inside_seed",
            "status": "failed",
        }

        def canonical_payload(document) -> bytes:
            return (
                json.dumps(
                    document,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")

        def write_handoff(
            path: Path,
            payload: bytes,
            *,
            mode: int = 0o444,
        ) -> None:
            path.write_bytes(payload)
            path.chmod(mode)

        exact_payload = canonical_payload(exact_document)
        invalid_cases = (
            ("wrong_mode", exact_payload, 0o400, 10001, 10001),
            ("wrong_uid", exact_payload, 0o444, 10002, 10001),
            ("wrong_gid", exact_payload, 0o444, 10001, 10002),
            ("short", b"\n", 0o444, 10001, 10001),
            ("oversize", b"x" * 2049, 0o444, 10001, 10001),
            ("malformed", b"{\n", 0o444, 10001, 10001),
            (
                "noncanonical",
                json.dumps(exact_document, sort_keys=True).encode("utf-8"),
                0o444,
                10001,
                10001,
            ),
            (
                "schema_bool",
                canonical_payload({**exact_document, "schema_version": True}),
                0o444,
                10001,
                10001,
            ),
            (
                "extra_key",
                canonical_payload({**exact_document, "private": "detail"}),
                0o444,
                10001,
                10001,
            ),
            (
                "outer_stage",
                canonical_payload({**exact_document, "stage": "outer_authority"}),
                0o444,
                10001,
                10001,
            ),
        )
        for case, payload, mode, uid, gid in invalid_cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "failure-stage-handoff.json"
                expected_uid = os.getuid() if uid == 10001 else os.getuid() + 1
                expected_gid = os.getgid() if gid == 10001 else os.getgid() + 1
                write_handoff(path, payload, mode=mode)
                with patch.multiple(
                    module,
                    _FAILURE_STAGE_HANDOFF_OWNER_UID=expected_uid,
                    _FAILURE_STAGE_HANDOFF_OWNER_GID=expected_gid,
                ):
                    self.assertIsNone(module._read_failure_stage_handoff(path))
                self.assertEqual(path.read_bytes(), payload)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "failure-stage-handoff.json"
            write_handoff(path, exact_payload)
            with _portable_handoff_owner(module):
                self.assertEqual(module._read_failure_stage_handoff(path), "inside_seed")
            self.assertEqual(path.read_bytes(), exact_payload)
            metadata = path.lstat()
            self.assertEqual(
                (
                    metadata.st_uid,
                    metadata.st_gid,
                    stat.S_IMODE(metadata.st_mode),
                    metadata.st_nlink,
                ),
                (os.getuid(), os.getgid(), 0o444, 1),
            )

        for case in ("directory", "symlink", "hardlink"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / "failure-stage-handoff.json"
                if case == "directory":
                    path.mkdir()
                elif case == "symlink":
                    target = root / "target.json"
                    write_handoff(target, exact_payload)
                    path.symlink_to(target)
                else:
                    write_handoff(path, exact_payload)
                    os.link(path, root / "handoff-hardlink.json")
                with _portable_handoff_owner(module):
                    self.assertIsNone(module._read_failure_stage_handoff(path))

        replacement_payload = canonical_payload({**exact_document, "stage": "inside_report"})
        real_open = module.os.open
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "failure-stage-handoff.json"
            write_handoff(path, exact_payload)
            replaced = False

            def replace_before_open(target, flags, *args, **kwargs):
                nonlocal replaced
                if Path(target) == path and (flags & os.O_ACCMODE) == os.O_RDONLY and not replaced:
                    replaced = True
                    path.unlink()
                    write_handoff(path, replacement_payload)
                return real_open(target, flags, *args, **kwargs)

            with (
                _portable_handoff_owner(module),
                patch.object(module.os, "open", side_effect=replace_before_open),
            ):
                self.assertIsNone(module._read_failure_stage_handoff(path))
            self.assertTrue(replaced)
            self.assertEqual(path.read_bytes(), replacement_payload)

        real_read = module.os.read
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "failure-stage-handoff.json"
            write_handoff(path, exact_payload)
            replaced = False

            def replace_during_read(descriptor, size):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    path.unlink()
                    write_handoff(path, replacement_payload)
                return real_read(descriptor, size)

            with (
                _portable_handoff_owner(module),
                patch.object(module.os, "read", side_effect=replace_during_read),
            ):
                self.assertIsNone(module._read_failure_stage_handoff(path))
            self.assertTrue(replaced)
            self.assertEqual(path.read_bytes(), replacement_payload)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "failure-stage-handoff.json"
            write_handoff(path, exact_payload)
            short_chunks = [exact_payload[: len(exact_payload) // 2], b""]

            def short_read(descriptor, size):
                del descriptor, size
                return short_chunks.pop(0)

            with (
                _portable_handoff_owner(module),
                patch.object(module.os, "read", side_effect=short_read),
            ):
                self.assertIsNone(module._read_failure_stage_handoff(path))
            self.assertEqual(path.read_bytes(), exact_payload)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "failure-stage-handoff.json"
            write_handoff(path, exact_payload)
            mutated = False

            def truncate_during_read(descriptor, size):
                nonlocal mutated
                if not mutated:
                    mutated = True
                    path.chmod(0o600)
                    path.write_bytes(exact_payload[:-1])
                    path.chmod(0o444)
                return real_read(descriptor, size)

            with (
                _portable_handoff_owner(module),
                patch.object(module.os, "read", side_effect=truncate_during_read),
            ):
                self.assertIsNone(module._read_failure_stage_handoff(path))
            self.assertTrue(mutated)
            self.assertEqual(path.read_bytes(), exact_payload[:-1])

    def test_failure_diagnostic_persistence_never_masks_or_replaces_original_failure(
        self,
    ) -> None:
        module = _load_module("connected_operator_live_diagnostic_persistence")
        private_failure = "private account token SQL /private/operator/path"
        real_write = module.os.write
        for case in ("preexisting", "interrupted_write"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output_path = root / "operator-live.json"
                authority_path = root / "operator-authority.json"
                authority_pin_path = root / "operator-authority-pin.json"
                diagnostic_path = root / "operator-failure-diagnostic.json"
                original_bytes = b"verifier-held-diagnostic\n"
                if case == "preexisting":
                    diagnostic_path.write_bytes(original_bytes)
                    diagnostic_path.chmod(0o400)
                stderr = io.StringIO()
                write_call_count = 0

                def interrupted_write(descriptor, value):
                    nonlocal write_call_count
                    write_call_count += 1
                    if write_call_count == 1:
                        partial_length = max(1, len(value) // 2)
                        return real_write(descriptor, value[:partial_length])
                    raise OSError("private diagnostic persistence failure")

                writer = (
                    patch.object(module.os, "write", side_effect=interrupted_write)
                    if case == "interrupted_write"
                    else nullcontext()
                )
                with (
                    patch.object(
                        module,
                        "_run_command",
                        side_effect=RuntimeError(private_failure),
                    ) as run_command,
                    writer,
                    redirect_stderr(stderr),
                ):
                    exit_code = module.main(
                        [
                            "--output",
                            str(output_path),
                            "--execution-authority-output",
                            str(authority_path),
                            "--execution-authority-pin-output",
                            str(authority_pin_path),
                            "--failure-diagnostic-output",
                            str(diagnostic_path),
                        ]
                    )

                self.assertEqual(exit_code, 1)
                self.assertEqual(run_command.call_count, 1)
                self.assertEqual(
                    json.loads(stderr.getvalue()),
                    {"error": "operator_journey_failed", "status": "error"},
                )
                self.assertFalse(output_path.exists())
                self.assertFalse(authority_path.exists())
                self.assertFalse(authority_pin_path.exists())
                if case == "preexisting":
                    self.assertEqual(diagnostic_path.read_bytes(), original_bytes)
                    self.assertEqual(diagnostic_path.stat().st_mode & 0o777, 0o400)
                else:
                    self.assertEqual(write_call_count, 2)
                    self.assertFalse(diagnostic_path.exists())
                self.assertNotIn(private_failure, stderr.getvalue())

    def test_failure_diagnostic_cleanup_preserves_replacement_race(self) -> None:
        module = _load_module("connected_operator_live_diagnostic_replacement_race")
        private_failure = "private account token SQL /private/operator/path"
        replacement_bytes = b"verifier-owned-replacement\n"
        real_write = module.os.write
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_path = root / "operator-live.json"
            authority_path = root / "operator-authority.json"
            authority_pin_path = root / "operator-authority-pin.json"
            diagnostic_path = root / "operator-failure-diagnostic.json"
            stderr = io.StringIO()
            write_call_count = 0

            def replace_path_then_fail(descriptor, value):
                nonlocal write_call_count
                write_call_count += 1
                if write_call_count == 1:
                    partial_length = max(1, len(value) // 2)
                    return real_write(descriptor, value[:partial_length])
                diagnostic_path.unlink()
                diagnostic_path.write_bytes(replacement_bytes)
                diagnostic_path.chmod(0o400)
                raise OSError("private diagnostic persistence failure")

            with (
                patch.object(
                    module,
                    "_run_command",
                    side_effect=RuntimeError(private_failure),
                ) as run_command,
                patch.object(module.os, "write", side_effect=replace_path_then_fail),
                redirect_stderr(stderr),
            ):
                exit_code = module.main(
                    [
                        "--output",
                        str(output_path),
                        "--execution-authority-output",
                        str(authority_path),
                        "--execution-authority-pin-output",
                        str(authority_pin_path),
                        "--failure-diagnostic-output",
                        str(diagnostic_path),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(run_command.call_count, 1)
            self.assertEqual(write_call_count, 2)
            self.assertEqual(
                json.loads(stderr.getvalue()),
                {"error": "operator_journey_failed", "status": "error"},
            )
            self.assertFalse(output_path.exists())
            self.assertFalse(authority_path.exists())
            self.assertFalse(authority_pin_path.exists())
            self.assertEqual(diagnostic_path.read_bytes(), replacement_bytes)
            self.assertEqual(diagnostic_path.stat().st_mode & 0o777, 0o400)
            self.assertNotIn(private_failure, stderr.getvalue())

    def test_outer_accepts_only_exact_inside_failure_diagnostic_stages(self) -> None:
        module = _load_module("connected_operator_live_inner_diagnostic_transfer")
        real_read_text = Path.read_text
        created = {
            "status": "ok",
            "secret_set_state": "created",
            "secret_file_count": 6,
            "created_file_count": 6,
            "initialization_contract_hash": _HASH_A,
            "google_client_secret_generated": False,
            "requires_operator_google_client_secret": True,
            "supports_connected_preflight_ready": False,
        }
        unchanged = {
            **created,
            "secret_set_state": "unchanged",
            "created_file_count": 0,
        }
        runtime_image_id = "sha256:" + "1" * 64
        private_cleanup_failure = "private cleanup failure /private/runtime/image"
        exact_inside = {
            "artifact_id": module.FAILURE_DIAGNOSTIC_ARTIFACT_ID,
            "failure_code": "stage_failed",
            "schema_version": 1,
            "stage": "inside_seed",
            "status": "failed",
        }
        cases = (
            ("exact_inside", exact_inside, "inside_seed"),
            ("missing", None, "outer_inner_journey"),
            ("malformed", "{", "outer_inner_journey"),
            (
                "unknown_stage",
                {**exact_inside, "stage": "inside_private_backend"},
                "outer_inner_journey",
            ),
            (
                "outer_stage_from_inner",
                {**exact_inside, "stage": "outer_authority"},
                "outer_inner_journey",
            ),
            (
                "extra_key",
                {**exact_inside, "private": "detail"},
                "outer_inner_journey",
            ),
            ("success_leftover", exact_inside, "outer_inner_journey"),
        )
        for case, inner_payload, expected_stage in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output_path = root / "operator-live.json"
                authority_path = root / "operator-authority.json"
                authority_pin_path = root / "operator-authority-pin.json"
                diagnostic_path = root / "operator-failure-diagnostic.json"
                init_call_count = 0
                inner_artifact_metadata: list[tuple[int, int, int]] = []

                def enforce_cross_uid_readability(path, *args, **kwargs):
                    metadata = path.lstat()
                    if (
                        metadata.st_uid == module._FAILURE_STAGE_HANDOFF_OWNER_UID
                        and stat.S_IMODE(metadata.st_mode) == 0o400
                    ):
                        raise PermissionError
                    return real_read_text(path, *args, **kwargs)

                def fake_run(command, *, environ=None, check=True):
                    nonlocal init_call_count
                    del environ, check
                    rendered = list(command)
                    if rendered[:2] == ["docker", "build"]:
                        Path(rendered[rendered.index("--iidfile") + 1]).write_text(
                            runtime_image_id + "\n",
                            encoding="utf-8",
                        )
                    if "init-secrets" in rendered:
                        init_call_count += 1
                        payload = created if init_call_count == 1 else unchanged
                        return subprocess.CompletedProcess(
                            rendered,
                            0,
                            json.dumps(payload),
                            "",
                        )
                    if rendered[:2] == ["docker", "exec"]:
                        return subprocess.CompletedProcess(rendered, 0, "ready", "")
                    if "--inside" in rendered:
                        out_mount = next(
                            argument for argument in rendered if argument.endswith(":/out")
                        )
                        mounted_out = Path(out_mount.rsplit(":", 1)[0])
                        if "--failure-stage-handoff-output" in rendered:
                            handoff_output = rendered[
                                rendered.index("--failure-stage-handoff-output") + 1
                            ]
                            inner_path = mounted_out / Path(handoff_output).name
                            inner_mode = 0o444
                        else:
                            inner_path = mounted_out / "failure-diagnostic.json"
                            inner_mode = 0o400
                        if inner_payload == "{":
                            inner_path.write_text("{", encoding="utf-8")
                        elif inner_payload is not None:
                            inner_path.write_text(
                                json.dumps(
                                    inner_payload,
                                    separators=(",", ":"),
                                    sort_keys=True,
                                )
                                + "\n",
                                encoding="utf-8",
                            )
                        if inner_payload is not None:
                            inner_path.chmod(inner_mode)
                            inner_metadata = inner_path.lstat()
                            inner_artifact_metadata.append(
                                (
                                    inner_metadata.st_uid,
                                    inner_metadata.st_gid,
                                    stat.S_IMODE(inner_metadata.st_mode),
                                )
                            )
                        return subprocess.CompletedProcess(
                            rendered,
                            0 if case == "success_leftover" else 1,
                            "",
                            json.dumps(
                                {
                                    "error": "operator_journey_command_failed",
                                    "status": "error",
                                },
                                sort_keys=True,
                            ),
                        )
                    if case == "exact_inside" and rendered == [
                        "docker",
                        "image",
                        "rm",
                        "--force",
                        runtime_image_id,
                    ]:
                        raise RuntimeError(private_cleanup_failure)
                    return subprocess.CompletedProcess(rendered, 0, "", "")

                with (
                    _portable_handoff_owner(module),
                    patch.object(module, "_run_command", side_effect=fake_run),
                    patch.object(
                        module.Path,
                        "read_text",
                        enforce_cross_uid_readability,
                    ),
                    self.assertRaisesRegex(
                        RuntimeError,
                        (
                            "^operator_journey_failure_stage_handoff_invalid$"
                            if case == "success_leftover"
                            else "^operator_journey_command_failed$"
                        ),
                    ),
                ):
                    module.run_outer(
                        output_path,
                        postgres_image=module.PINNED_POSTGRES_IMAGE,
                        execution_authority_output_path=authority_path,
                        execution_authority_pin_output_path=authority_pin_path,
                        failure_diagnostic_output_path=diagnostic_path,
                    )

                self.assertFalse(output_path.exists())
                self.assertTrue(authority_path.is_file())
                self.assertTrue(authority_pin_path.is_file())
                self.assertEqual(
                    json.loads(diagnostic_path.read_text(encoding="utf-8")),
                    {
                        "artifact_id": module.FAILURE_DIAGNOSTIC_ARTIFACT_ID,
                        "failure_code": "stage_failed",
                        "schema_version": 1,
                        "stage": expected_stage,
                        "status": "failed",
                    },
                )
                self.assertEqual(diagnostic_path.stat().st_mode & 0o777, 0o400)
                self.assertEqual(diagnostic_path.stat().st_uid, os.getuid())
                if inner_payload is not None:
                    self.assertEqual(
                        inner_artifact_metadata,
                        [(os.getuid(), os.getgid(), 0o444)],
                    )
                else:
                    self.assertEqual(inner_artifact_metadata, [])
                self.assertNotIn(
                    private_cleanup_failure,
                    diagnostic_path.read_text(encoding="utf-8"),
                )

    def test_failure_diagnostic_output_aliases_fail_closed_before_docker(self) -> None:
        module = _load_module("connected_operator_live_diagnostic_alias")
        for alias_kind in ("output", "authority", "pin", "symlink"):
            with self.subTest(alias_kind=alias_kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output_path = root / "operator-live.json"
                authority_path = root / "operator-authority.json"
                authority_pin_path = root / "operator-authority-pin.json"
                if alias_kind == "output":
                    diagnostic_path = output_path
                elif alias_kind == "authority":
                    diagnostic_path = authority_path
                elif alias_kind == "pin":
                    diagnostic_path = authority_pin_path
                else:
                    diagnostic_path = root / "operator-live-alias.json"
                    diagnostic_path.symlink_to(output_path)

                with (
                    patch.object(module, "_run_command") as run_command,
                    self.assertRaisesRegex(
                        RuntimeError,
                        "^operator_journey_execution_authority_output_invalid$",
                    ),
                ):
                    module.run_outer(
                        output_path,
                        postgres_image=module.PINNED_POSTGRES_IMAGE,
                        execution_authority_output_path=authority_path,
                        execution_authority_pin_output_path=authority_pin_path,
                        failure_diagnostic_output_path=diagnostic_path,
                    )

                run_command.assert_not_called()
                self.assertFalse(output_path.exists())
                self.assertFalse(authority_path.exists())
                self.assertFalse(authority_pin_path.exists())
                if alias_kind == "symlink":
                    self.assertTrue(diagnostic_path.is_symlink())
                else:
                    self.assertFalse(diagnostic_path.exists())

    def test_inside_failure_diagnostic_output_aliases_fail_closed_before_cli(self) -> None:
        module = _load_module("connected_operator_live_inside_diagnostic_alias")
        runtime_image_id = "sha256:" + "1" * 64
        for alias_kind in ("output", "symlink"):
            with self.subTest(alias_kind=alias_kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output_path = root / "operator-live.json"
                if alias_kind == "output":
                    diagnostic_path = output_path
                else:
                    diagnostic_path = root / "operator-live-alias.json"
                    diagnostic_path.symlink_to(output_path)

                with (
                    patch.object(module, "_run_operator_cli") as operator_cli,
                    patch.object(
                        module,
                        "_write_failure_stage_handoff",
                    ) as diagnostic_writer,
                    self.assertRaisesRegex(
                        RuntimeError,
                        "^operator_journey_failure_stage_handoff_output_invalid$",
                    ),
                ):
                    module.run_inside(
                        output_path,
                        runtime_image_id=runtime_image_id,
                        failure_stage_handoff_output_path=diagnostic_path,
                    )

                operator_cli.assert_not_called()
                diagnostic_writer.assert_not_called()
                self.assertFalse(output_path.exists())
                if alias_kind == "symlink":
                    self.assertTrue(diagnostic_path.is_symlink())
                else:
                    self.assertFalse(diagnostic_path.exists())

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_path = root / "inside-report.json"
            final_diagnostic_path = root / "final-diagnostic.json"
            handoff_path = root / "failure-stage-handoff.json"
            for case, arguments in (
                (
                    "inside_final_diagnostic",
                    [
                        "--inside",
                        "--runtime-image-id",
                        runtime_image_id,
                        "--output",
                        str(output_path),
                        "--failure-diagnostic-output",
                        str(final_diagnostic_path),
                    ],
                ),
                (
                    "outer_inner_handoff",
                    [
                        "--output",
                        str(output_path),
                        "--failure-stage-handoff-output",
                        str(handoff_path),
                    ],
                ),
            ):
                with (
                    self.subTest(case=case),
                    patch.object(module, "run_inside") as run_inside,
                    patch.object(module, "run_outer") as run_outer,
                    redirect_stderr(io.StringIO()) as stderr,
                ):
                    self.assertEqual(module.main(arguments), 1)
                    self.assertEqual(
                        json.loads(stderr.getvalue()),
                        {"error": "operator_journey_failed", "status": "error"},
                    )
                    run_inside.assert_not_called()
                    run_outer.assert_not_called()
            self.assertFalse(output_path.exists())
            self.assertFalse(final_diagnostic_path.exists())
            self.assertFalse(handoff_path.exists())

    def test_cli_validation_writes_only_safe_validation_result(self) -> None:
        module = _load_module("connected_operator_live_cli")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "report.json"
            authority_path = root / "authority.json"
            authority_pin_path = root / "authority-pin.json"
            output_path = root / "validation.json"
            report, authority, authority_pin = _signed_report(module)
            report_path.write_text(json.dumps(report), encoding="utf-8")
            authority_path.write_text(json.dumps(authority), encoding="utf-8")
            authority_pin_path.write_text(json.dumps(authority_pin), encoding="utf-8")

            exit_code = module.main(
                [
                    "--validate-report",
                    str(report_path),
                    "--trusted-execution-authority",
                    str(authority_path),
                    "--trusted-execution-authority-pin",
                    str(authority_pin_path),
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")),
                {"passed": True, "blockers": []},
            )

            invalid_report = deepcopy(report)
            invalid_report["debug"] = "/tmp/formowl-operator/private-output.json"
            report_path.write_text(json.dumps(invalid_report), encoding="utf-8")
            invalid_output_path = root / "invalid-validation.json"
            exit_code = module.main(
                [
                    "--validate-report",
                    str(report_path),
                    "--trusted-execution-authority",
                    str(authority_path),
                    "--trusted-execution-authority-pin",
                    str(authority_pin_path),
                    "--output",
                    str(invalid_output_path),
                ]
            )
            self.assertEqual(exit_code, 1)
            invalid_validation = json.loads(invalid_output_path.read_text(encoding="utf-8"))
            self.assertFalse(invalid_validation["passed"])
            self.assertTrue(invalid_validation["blockers"])
            self.assertNotIn(
                "/tmp/formowl-operator/private-output.json",
                json.dumps(invalid_validation, sort_keys=True),
            )


if __name__ == "__main__":
    unittest.main()
