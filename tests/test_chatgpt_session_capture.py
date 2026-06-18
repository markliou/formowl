from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from formowl_contract import ContractValidationError, PermissionScope
from formowl_ingestion.chatgpt import (
    ChatGptSessionCapture,
    ChatGptSessionCaptureStore,
    capture_current_chatgpt_session,
)
from formowl_ingestion.storage import (
    AssetStore,
    FileObjectStore,
    JobStore,
    StorageBackendRegistry,
)


class ChatGptSessionCaptureTests(unittest.TestCase):
    def test_capture_current_chatgpt_session_creates_capture_asset_job_and_audit(self) -> None:
        temp_dir = _paths.fresh_test_dir("chatgpt-session-capture")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        audit_store = FileAuditLogStore(temp_dir)
        capture_store = ChatGptSessionCaptureStore(temp_dir)
        asset_store = AssetStore(temp_dir)
        job_store = JobStore(temp_dir)
        object_store = FileObjectStore(registry)
        permission_scope = PermissionScope.project("project_formowl")

        result = capture_current_chatgpt_session(
            messages=[
                {
                    "message_id": "msg_001",
                    "role": "user",
                    "content": "Save this conversation into FormOwl.",
                },
                {
                    "message_id": "msg_002",
                    "role": "assistant",
                    "content": "I will capture it as a governed source artifact.",
                },
            ],
            capture_store=capture_store,
            object_store=object_store,
            asset_store=asset_store,
            job_store=job_store,
            audit_store=audit_store,
            storage_backend_id=backend.storage_backend_id,
            actor_user_id="user_yifan",
            session_id="session_001",
            workspace_id="workspace_formowl",
            permission_scope=permission_scope,
            source_account_id="chatgpt:yifan@example.test",
            source_account_metadata={"account_status": "connected"},
            visibility_scope="workspace",
            capture_method="manual_export",
            captured_at="2026-06-17T10:00:00+00:00",
            ingested_at="2026-06-17T10:01:00+00:00",
            extractor_names=["plain_text_extractor"],
            project_id="project_formowl",
        )

        capture = result.capture
        asset = result.asset
        ingestion_job = result.ingestion_job
        self.assertTrue(capture.capture_id.startswith("cap_"))
        self.assertEqual(capture.source_system, "chatgpt")
        self.assertEqual(capture.source_account_id, "chatgpt:yifan@example.test")
        self.assertEqual(capture.source_account_metadata, {"account_status": "connected"})
        self.assertEqual(capture.permission_scope, permission_scope.to_dict())
        self.assertEqual(capture.asset_id, asset.asset_id)
        self.assertEqual(capture.ingestion_job_id, ingestion_job.ingestion_job_id)
        self.assertEqual(capture.processing_status, "queued")
        self.assertEqual(asset.source_ref["source_system"], "chatgpt")
        self.assertEqual(asset.mime_type, "text/markdown")
        self.assertEqual(ingestion_job.status, "pending")
        self.assertEqual(ingestion_job.extractor_names, ["plain_text_extractor"])

        stored_capture = capture_store.get(capture.capture_id)
        self.assertEqual(stored_capture.to_dict(), capture.to_dict())
        self.assertEqual(asset_store.get(asset.asset_id).to_dict(), asset.to_dict())
        self.assertEqual(
            job_store.get(ingestion_job.ingestion_job_id).to_dict(),
            ingestion_job.to_dict(),
        )
        self.assertNotIn("formowl-chatgpt-capture", json.dumps(capture.to_dict(), sort_keys=True))

        object_path = object_store.resolve_object_path(asset.object_uri)
        self.assertIn("Save this conversation", object_path.read_text(encoding="utf-8"))

        self.assertEqual(
            {audit_log.action for audit_log in audit_store.list()},
            {"chatgpt_session_captured", "asset_registered", "ingestion_job_created"},
        )

    def test_capture_current_chatgpt_session_requires_messages(self) -> None:
        temp_dir = _paths.fresh_test_dir("chatgpt-session-capture-validation")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )

        with self.assertRaises(ValueError):
            capture_current_chatgpt_session(
                messages=[],
                capture_store=ChatGptSessionCaptureStore(temp_dir),
                object_store=FileObjectStore(registry),
                asset_store=AssetStore(temp_dir),
                job_store=JobStore(temp_dir),
                audit_store=FileAuditLogStore(temp_dir),
                storage_backend_id=backend.storage_backend_id,
                actor_user_id="user_yifan",
                session_id="session_001",
                workspace_id="workspace_formowl",
                permission_scope=PermissionScope.project("project_formowl"),
                source_account_id="chatgpt:yifan@example.test",
                visibility_scope="workspace",
                capture_method="manual_export",
                captured_at="2026-06-17T10:00:00+00:00",
                ingested_at="2026-06-17T10:01:00+00:00",
                extractor_names=["plain_text_extractor"],
            )

    def test_capture_current_chatgpt_session_invalid_extractors_leave_no_state(self) -> None:
        invalid_cases = [
            [],
            [""],
            ["plain_text_extractor", ""],
            ["plain_text_extractor", "plain_text_extractor"],
            ["plain_text_extractor", 123],
        ]

        for extractor_names in invalid_cases:
            with self.subTest(extractor_names=extractor_names):
                temp_dir = _paths.fresh_test_dir("chatgpt-session-capture-invalid-extractors")
                object_root = temp_dir / "object-root"
                registry = StorageBackendRegistry(temp_dir)
                backend = registry.register_local_backend(
                    object_root,
                    workspace_scope="workspace_formowl",
                )
                audit_store = FileAuditLogStore(temp_dir)
                capture_store = ChatGptSessionCaptureStore(temp_dir)
                asset_store = AssetStore(temp_dir)
                job_store = JobStore(temp_dir)

                with self.assertRaises(ValueError):
                    capture_current_chatgpt_session(
                        messages=[
                            {
                                "message_id": "msg_001",
                                "role": "user",
                                "content": "This capture should fail before persistence.",
                            }
                        ],
                        capture_store=capture_store,
                        object_store=FileObjectStore(registry),
                        asset_store=asset_store,
                        job_store=job_store,
                        audit_store=audit_store,
                        storage_backend_id=backend.storage_backend_id,
                        actor_user_id="user_yifan",
                        session_id="session_001",
                        workspace_id="workspace_formowl",
                        permission_scope=PermissionScope.project("project_formowl"),
                        source_account_id="chatgpt:yifan@example.test",
                        visibility_scope="workspace",
                        capture_method="manual_export",
                        captured_at="2026-06-17T10:00:00+00:00",
                        ingested_at="2026-06-17T10:01:00+00:00",
                        extractor_names=extractor_names,  # type: ignore[list-item]
                    )

                self.assertEqual(capture_store.list(), [])
                self.assertEqual(asset_store.list(), [])
                self.assertEqual(job_store.list(), [])
                self.assertEqual(audit_store.list(), [])
                self.assertEqual(list(object_root.glob("objects/**/payload.bin")), [])
                self.assertEqual(
                    list(object_root.glob("scratch/chatgpt-session-captures/*.md")),
                    [],
                )

    def test_capture_current_chatgpt_session_invalid_inputs_leave_no_state(self) -> None:
        cases = [
            ("permission_scope", {"scope_type": "project"}),
            ("permission_scope", {"scope_type": 123, "visibility": []}),
            ("visibility_scope", ""),
            ("storage_backend_id", "missing_backend"),
            ("project_id", 123),
            ("customer_id", []),
            (
                "messages",
                [{"message_id": "msg_001", "role": "user", "content": ["bad"]}],
            ),
            (
                "messages",
                [{"message_id": 123, "role": "user", "content": "bad"}],
            ),
            (
                "messages",
                [{"message_id": "msg_001", "role": 123, "content": "bad"}],
            ),
        ]

        for field_name, invalid_value in cases:
            with self.subTest(field_name=field_name):
                temp_dir = _paths.fresh_test_dir(f"chatgpt-session-capture-invalid-{field_name}")
                object_root = temp_dir / "object-root"
                registry = StorageBackendRegistry(temp_dir)
                backend = registry.register_local_backend(
                    object_root,
                    workspace_scope="workspace_formowl",
                )
                audit_store = FileAuditLogStore(temp_dir)
                capture_store = ChatGptSessionCaptureStore(temp_dir)
                asset_store = AssetStore(temp_dir)
                job_store = JobStore(temp_dir)
                kwargs = {
                    "messages": [
                        {
                            "message_id": "msg_001",
                            "role": "user",
                            "content": "This capture should fail before persistence.",
                        }
                    ],
                    "capture_store": capture_store,
                    "object_store": FileObjectStore(registry),
                    "asset_store": asset_store,
                    "job_store": job_store,
                    "audit_store": audit_store,
                    "storage_backend_id": backend.storage_backend_id,
                    "actor_user_id": "user_yifan",
                    "session_id": "session_001",
                    "workspace_id": "workspace_formowl",
                    "permission_scope": PermissionScope.project("project_formowl"),
                    "source_account_id": "chatgpt:yifan@example.test",
                    "visibility_scope": "workspace",
                    "capture_method": "manual_export",
                    "captured_at": "2026-06-17T10:00:00+00:00",
                    "ingested_at": "2026-06-17T10:01:00+00:00",
                    "extractor_names": ["plain_text_extractor"],
                }
                kwargs[field_name] = invalid_value

                with self.assertRaises((ContractValidationError, FileNotFoundError)):
                    capture_current_chatgpt_session(**kwargs)

                self.assertEqual(capture_store.list(), [])
                self.assertEqual(asset_store.list(), [])
                self.assertEqual(job_store.list(), [])
                self.assertEqual(audit_store.list(), [])
                self.assertEqual(list(object_root.glob("objects/**/payload.bin")), [])
                self.assertEqual(
                    list(object_root.glob("scratch/chatgpt-session-captures/*.md")),
                    [],
                )

    def test_chatgpt_session_capture_from_dict_rejects_malformed_typed_fields(self) -> None:
        cases = [
            ("source_account_id", 123),
            ("source_account_metadata", ["connected"]),
            ("permission_scope", {"scope_type": "project"}),
            ("permission_scope", {"scope_type": 123, "visibility": []}),
            (
                "permission_scope",
                {
                    "scope_type": "project",
                    "visibility": "workspace",
                    "scope_id": 123,
                },
            ),
            (
                "permission_scope",
                {
                    "scope_type": "project",
                    "visibility": "workspace",
                    "inherited_from": [],
                },
            ),
            ("asset_object_uri", r"C:\workspace\object-root\payload.bin"),
            ("asset_object_uri", "/tmp/object-root/payload.bin"),
            ("asset_object_uri", "file:///tmp/object-root/payload.bin"),
        ]

        for field_name, invalid_value in cases:
            payload = _valid_capture_payload()
            payload[field_name] = invalid_value
            with self.subTest(field_name=field_name):
                with self.assertRaises(ContractValidationError):
                    ChatGptSessionCapture.from_dict(payload)

def _valid_capture_payload() -> dict[str, object]:
    return {
        "capture_id": "cap_001",
        "source_system": "chatgpt",
        "source_account_id": "chatgpt:yifan@example.test",
        "source_account_identity_hash": "sha256:identity",
        "capture_method": "manual_export",
        "captured_by": "user_yifan",
        "captured_at": "2026-06-17T10:00:00+00:00",
        "ingested_at": "2026-06-17T10:01:00+00:00",
        "workspace_id": "workspace_formowl",
        "visibility_scope": "workspace",
        "permission_scope": PermissionScope.project("project_formowl").to_dict(),
        "source_account_metadata": {"account_status": "connected"},
        "manifest_hash": "sha256:manifest",
        "audit_log_id": "audit_001",
        "asset_id": "asset_001",
        "ingestion_job_id": "job_001",
    }


if __name__ == "__main__":
    unittest.main()
