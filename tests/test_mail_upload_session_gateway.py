from __future__ import annotations

import unittest
from typing import Any

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from formowl_gateway import SemanticGatewaySession, SemanticMcpGateway, SemanticMcpJsonRpcGateway
from formowl_ingestion.storage import UploadSessionStore
from formowl_mail import build_mail_upload_session_handler, validate_mail_upload_session_task


class MailUploadSessionGatewayTests(unittest.TestCase):
    def test_jsonrpc_open_upload_session_creates_session_bound_mail_task_card(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-session-gateway")
        upload_store = UploadSessionStore(temp_dir)
        audit_store = FileAuditLogStore(temp_dir)
        gateway = _mail_upload_jsonrpc_gateway(upload_store, audit_store)

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_upload_session",
                "method": "tools/call",
                "params": {
                    "name": "open_upload_session",
                    "arguments": {
                        "intent": "Upload my PST for project mail evidence reading.",
                        "intended_asset_type": "pst",
                        "owner_scope_type": "project",
                        "owner_scope_id": "project_formowl",
                        "project_id": "project_formowl",
                        "visibility_scope": "workspace",
                    },
                },
            }
        )

        self.assertFalse(result["result"]["isError"])
        payload = result["result"]["content"][0]["json"]["data"]
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["validation"]["passed"], True)
        self.assertEqual(
            payload["claim_boundary"]["supports_chatgpt_mail_upload_task_card_claim"],
            True,
        )
        self.assertEqual(payload["claim_boundary"]["supports_real_upload_iframe_claim"], False)
        task_card = payload["upload_task_card"]
        self.assertEqual(task_card["card_type"], "mail_archive_upload_task")
        self.assertEqual(task_card["current_user_id"], "user_yifan")
        self.assertEqual(task_card["workspace_id"], "workspace_formowl")
        self.assertEqual(task_card["intended_asset_type"], "pst")
        self.assertEqual(task_card["ingestion_profile"], "mail_archive_phase1")
        self.assertEqual(task_card["accepted_file_types"], ["pst", "ost", "msg", "eml", "mbox"])
        self.assertEqual(task_card["next_required_action"], "upload_prepared_mail_archive")
        self.assertTrue(
            task_card["upload_surface_locator"].startswith("formowl_upload_session:upload_")
        )
        persisted = upload_store.get(payload["upload_session_id"])
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted.actor_user_id, "user_yifan")
        self.assertEqual(persisted.session_id, "session_001")
        self.assertEqual(persisted.workspace_id, "workspace_formowl")
        self.assertEqual(persisted.project_id, "project_formowl")
        self.assertEqual(persisted.ingestion_profile, "mail_archive_phase1")
        self.assertEqual(
            persisted.source_preparation_state,
            "mail_archive_export_guidance_attached",
        )
        self.assertEqual(persisted.processing_status, "waiting_for_upload")
        audit_logs = audit_store.list()
        self.assertEqual(len(audit_logs), 1)
        self.assertEqual(audit_logs[0].action, "upload_session_created")
        self.assertEqual(audit_logs[0].target_id, persisted.upload_session_id)
        rendered = str(result).lower()
        self.assertNotIn("storage_backend_id", rendered)
        self.assertNotIn("worker_queue", rendered)
        self.assertNotIn("parser_path", rendered)
        self.assertNotIn("bucket_name", rendered)
        self.assertNotIn("select *", rendered)

    def test_jsonrpc_session_context_overrides_forged_public_identity(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-session-forged-identity")
        upload_store = UploadSessionStore(temp_dir)
        audit_store = FileAuditLogStore(temp_dir)
        gateway = _mail_upload_jsonrpc_gateway(upload_store, audit_store)

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "forged_identity",
                "method": "tools/call",
                "params": {
                    "name": "open_upload_session",
                    "arguments": {
                        "requester_user_id": "attacker",
                        "session_id": "attacker_session",
                        "workspace_id": "attacker_workspace",
                        "intent": "Upload mail archive.",
                        "intended_asset_type": "mail_archive",
                    },
                },
            }
        )

        self.assertFalse(result["result"]["isError"])
        self.assertEqual(result["result"]["session"]["session_id"], "session_001")
        self.assertEqual(result["result"]["session"]["actor_user_id"], "user_yifan")
        self.assertEqual(result["result"]["session"]["workspace_id"], "workspace_formowl")
        payload = result["result"]["content"][0]["json"]["data"]
        task_card = payload["upload_task_card"]
        self.assertEqual(task_card["current_user_id"], "user_yifan")
        self.assertEqual(task_card["workspace_id"], "workspace_formowl")
        persisted = upload_store.get(payload["upload_session_id"])
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted.actor_user_id, "user_yifan")
        self.assertEqual(persisted.session_id, "session_001")
        self.assertEqual(persisted.workspace_id, "workspace_formowl")
        audit_logs = audit_store.list()
        self.assertEqual(len(audit_logs), 1)
        self.assertEqual(audit_logs[0].actor_user_id, "user_yifan")
        self.assertEqual(audit_logs[0].session_id, "session_001")
        self.assertNotIn("attacker", str(result))

    def test_user_infrastructure_controls_fail_before_session_or_audit_side_effects(self) -> None:
        cases = [
            {"worker_queue": "fast_mail_workers"},
            {"workerQueue": "fast_mail_workers"},
            {"parserName": "local_pst_parser"},
            {"storageBackend": "nas_mail_archive_pool"},
            {"parser": {"name": "local_pst_parser"}},
            {"backendId": "backend_private_mail"},
            {"backendName": "private_mail_backend"},
            {"storageBackendName": "nas_mail_archive_pool"},
            {"workerName": "fast_mail_worker"},
            {"parserId": "local_pst_parser"},
        ]

        for index, arguments in enumerate(cases, start=1):
            with self.subTest(index=index):
                temp_dir = _paths.fresh_test_dir(f"mail-upload-session-infra-controls-{index}")
                upload_store = UploadSessionStore(temp_dir)
                audit_store = FileAuditLogStore(temp_dir)
                gateway = _mail_upload_jsonrpc_gateway(upload_store, audit_store)

                result = gateway.handle_json_rpc(
                    {
                        "jsonrpc": "2.0",
                        "id": f"infra_control_{index}",
                        "method": "tools/call",
                        "params": {
                            "name": "open_upload_session",
                            "arguments": {
                                "intent": "Upload mail archive.",
                                "intended_asset_type": "pst",
                                **arguments,
                            },
                        },
                    }
                )

                self.assertTrue(result["result"]["isError"])
                self.assertEqual(upload_store.list(), [])
                self.assertEqual(audit_store.list(), [])
                rendered = str(result).lower()
                self.assertNotIn("fast_mail_workers", rendered)
                self.assertNotIn("local_pst_parser", rendered)
                self.assertNotIn("nas_mail_archive_pool", rendered)

    def test_non_mail_upload_request_fails_before_session_or_audit_side_effects(self) -> None:
        cases = [
            {"intended_asset_type": "document"},
            {"intendedAssetType": "document"},
            {"intended_asset_type": "pst", "ingestion_profile": "plain_text"},
            {"intended_asset_type": "pst", "ingestionProfile": "plain_text"},
            {"intended_asset_type": "pst", "owner_scope_type": "backend"},
            {"intended_asset_type": "pst", "owner_scope_type": "parser"},
            {"intended_asset_type": "pst", "owner_scope_type": "worker"},
            {"intended_asset_type": "pst", "visibility_scope": "backend"},
            {
                "intended_asset_type": "pst",
                "permission_scope": {
                    "scope_type": "project",
                    "scope_id": "other_project",
                    "visibility": "restricted",
                },
            },
            {
                "intended_asset_type": "pst",
                "permission_scope": {
                    "scope_type": "workspace",
                    "scope_id": "workspace_formowl",
                    "visibility": "public",
                },
            },
        ]

        for index, arguments in enumerate(cases, start=1):
            with self.subTest(index=index):
                temp_dir = _paths.fresh_test_dir(f"mail-upload-session-non-mail-{index}")
                upload_store = UploadSessionStore(temp_dir)
                audit_store = FileAuditLogStore(temp_dir)
                gateway = _mail_upload_jsonrpc_gateway(upload_store, audit_store)

                result = gateway.handle_json_rpc(
                    {
                        "jsonrpc": "2.0",
                        "id": f"non_mail_{index}",
                        "method": "tools/call",
                        "params": {
                            "name": "open_upload_session",
                            "arguments": {
                                "intent": "Upload a source file.",
                                **arguments,
                            },
                        },
                    }
                )

                self.assertTrue(result["result"]["isError"])
                self.assertEqual(upload_store.list(), [])
                self.assertEqual(audit_store.list(), [])
                self.assertNotIn("plain_text", str(result))
                self.assertNotIn("document", str(result))

    def test_audit_write_failure_leaves_no_upload_session_side_effect(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-session-audit-failure")
        upload_store = UploadSessionStore(temp_dir)
        audit_store = _FailingAuditLogStore(temp_dir)
        gateway = _mail_upload_jsonrpc_gateway(upload_store, audit_store)

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "audit_failure",
                "method": "tools/call",
                "params": {
                    "name": "open_upload_session",
                    "arguments": {
                        "intent": "Upload mail archive.",
                        "intended_asset_type": "pst",
                    },
                },
            }
        )

        self.assertTrue(result["result"]["isError"])
        self.assertEqual(upload_store.list(), [])
        self.assertNotIn("audit write failed", str(result).lower())

    def test_session_store_failure_rolls_back_chatgpt_upload_audit(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-session-store-failure")
        upload_store = _FailingUploadSessionStore(temp_dir)
        audit_store = FileAuditLogStore(temp_dir)
        gateway = _mail_upload_jsonrpc_gateway(upload_store, audit_store)  # type: ignore[arg-type]

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "store_failure",
                "method": "tools/call",
                "params": {
                    "name": "open_upload_session",
                    "arguments": {
                        "intent": "Upload mail archive.",
                        "intended_asset_type": "pst",
                    },
                },
            }
        )

        self.assertTrue(result["result"]["isError"])
        self.assertEqual(audit_store.list(), [])
        self.assertNotIn("upload session write failed", str(result).lower())

    def test_task_validator_rejects_real_upload_or_production_overclaim(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-session-validator")
        upload_store = UploadSessionStore(temp_dir)
        audit_store = FileAuditLogStore(temp_dir)
        gateway = _mail_upload_jsonrpc_gateway(upload_store, audit_store)
        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "valid_task",
                "method": "tools/call",
                "params": {
                    "name": "open_upload_session",
                    "arguments": {
                        "intent": "Upload mail archive.",
                        "intended_asset_type": "mail_archive",
                    },
                },
            }
        )
        payload = dict(result["result"]["content"][0]["json"]["data"])
        payload["claim_boundary"] = dict(payload["claim_boundary"])
        payload["claim_boundary"]["supports_real_upload_iframe_claim"] = True
        payload["claim_boundary"]["supports_production_ready_claim"] = True
        payload["validation"] = {
            "passed": True,
            "blockers": [],
            "claim_boundary": {
                "supports_chatgpt_mail_upload_task_card_claim": True,
                "supports_production_ready_claim": True,
            },
        }

        validation = validate_mail_upload_session_task(payload)

        self.assertFalse(validation["passed"])
        self.assertTrue(
            any("supports_real_upload_iframe_claim" in item for item in validation["blockers"])
        )
        self.assertTrue(
            any("supports_production_ready_claim" in item for item in validation["blockers"])
        )
        self.assertTrue(
            any("validation production claim" in item for item in validation["blockers"])
        )

    def test_task_validator_rejects_nested_unknown_public_keys(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-session-validator-extra-keys")
        upload_store = UploadSessionStore(temp_dir)
        audit_store = FileAuditLogStore(temp_dir)
        gateway = _mail_upload_jsonrpc_gateway(upload_store, audit_store)
        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "valid_task",
                "method": "tools/call",
                "params": {
                    "name": "open_upload_session",
                    "arguments": {
                        "intent": "Upload mail archive.",
                        "intended_asset_type": "mail_archive",
                    },
                },
            }
        )
        base_payload = result["result"]["content"][0]["json"]["data"]
        cases = [
            ("claim_boundary", "supports_full_issue_21_claim", True),
            ("source_preparation_guidance", "extra_claim", "done"),
            ("public_checks", "extra_ok", True),
            ("safe_outputs", "extra_hash", base_payload["safe_outputs"]["task_card_hash"]),
            ("upload_task_card", "extra_scope", "backend-free"),
        ]

        for section, key, value in cases:
            with self.subTest(section=section, key=key):
                payload = {
                    payload_key: (
                        dict(payload_value) if isinstance(payload_value, dict) else payload_value
                    )
                    for payload_key, payload_value in base_payload.items()
                }
                payload[section][key] = value

                validation = validate_mail_upload_session_task(payload)

                self.assertFalse(validation["passed"])
                self.assertTrue(any(section in item for item in validation["blockers"]))


def _mail_upload_jsonrpc_gateway(
    upload_store: UploadSessionStore,
    audit_store: FileAuditLogStore,
) -> SemanticMcpJsonRpcGateway:
    return SemanticMcpJsonRpcGateway(
        semantic_gateway=SemanticMcpGateway(
            upload_session_handler=build_mail_upload_session_handler(
                upload_session_store=upload_store,
                audit_store=audit_store,
                expires_at="2026-07-06T00:00:00+00:00",
                created_at="2026-07-05T10:00:00+00:00",
            )
        ),
        session=SemanticGatewaySession(
            session_id="session_001",
            actor_user_id="user_yifan",
            workspace_id="workspace_formowl",
        ),
    )


class _FailingAuditLogStore(FileAuditLogStore):
    def create(self, audit_log: Any) -> Any:
        raise RuntimeError("audit write failed")


class _FailingUploadSessionStore(UploadSessionStore):
    def create(self, upload_session: Any) -> Any:
        raise RuntimeError("upload session write failed")


if __name__ == "__main__":
    unittest.main()
