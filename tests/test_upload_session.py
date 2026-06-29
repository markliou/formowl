from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from formowl_contract import ContractValidationError, PermissionScope, UploadSession
from formowl_ingestion.storage import UploadSessionStore
from formowl_ingestion.uploads import create_upload_session


class UploadSessionTests(unittest.TestCase):
    def test_create_upload_session_records_intent_scope_permission_and_audit(self) -> None:
        temp_dir = _paths.fresh_test_dir("upload-session")
        created_at = "2026-06-17T10:00:00+00:00"
        permission_scope = PermissionScope.project("project_formowl")
        audit_store = FileAuditLogStore(temp_dir)
        upload_store = UploadSessionStore(temp_dir)

        upload_session = create_upload_session(
            upload_session_store=upload_store,
            audit_store=audit_store,
            actor_user_id="user_yifan",
            session_id="session_001",
            workspace_id="workspace_formowl",
            owner_scope_type="project",
            owner_scope_id="project_formowl",
            project_id="project_formowl",
            intent="Upload meeting notes for source-backed extraction.",
            intended_asset_type="document",
            ingestion_profile="plain_text",
            visibility_scope="workspace",
            permission_scope=permission_scope,
            expires_at="2026-06-18T10:00:00+00:00",
            created_at=created_at,
        )

        self.assertTrue(upload_session.upload_session_id.startswith("upload_"))
        self.assertEqual(upload_session.actor_user_id, "user_yifan")
        self.assertEqual(
            upload_session.intent, "Upload meeting notes for source-backed extraction."
        )
        self.assertEqual(upload_session.permission_scope, permission_scope.to_dict())
        self.assertEqual(upload_session.status, "pending")
        self.assertEqual(upload_session.processing_status, "waiting_for_upload")
        self.assertTrue(upload_session.audit_log_id.startswith("audit_"))
        self.assertEqual(
            upload_store.get(upload_session.upload_session_id).to_dict(),
            upload_session.to_dict(),
        )

        audit_logs = audit_store.list()
        self.assertEqual(len(audit_logs), 1)
        self.assertEqual(audit_logs[0].action, "upload_session_created")
        self.assertEqual(audit_logs[0].target_id, upload_session.upload_session_id)
        self.assertEqual(audit_logs[0].actor_user_id, "user_yifan")
        self.assertEqual(audit_logs[0].workspace_id, "workspace_formowl")
        self.assertEqual(audit_logs[0].status, "ok")
        self.assertEqual(audit_logs[0].timestamp, created_at)

    def test_upload_session_store_rejects_missing_intent_actor_permission_or_audit(self) -> None:
        temp_dir = _paths.fresh_test_dir("upload-session-validation")
        created_at = "2026-06-17T10:00:00+00:00"
        permission_scope = PermissionScope.project("project_formowl")
        valid = UploadSession(
            upload_session_id="upload_001",
            actor_user_id="user_yifan",
            workspace_id="workspace_formowl",
            owner_scope_type="project",
            owner_scope_id="project_formowl",
            intent="Upload source material.",
            intended_asset_type="document",
            ingestion_profile="plain_text",
            visibility_scope="workspace",
            permission_scope=permission_scope,
            expires_at="2026-06-18T10:00:00+00:00",
            source_preparation_state="not_started",
            processing_status="waiting_for_upload",
            status="pending",
            created_at=created_at,
            audit_log_id="audit_001",
        ).to_dict()

        store = UploadSessionStore(temp_dir)
        self.assertEqual(store.create(valid).to_dict(), valid)

        for required_field in ("intent", "actor_user_id", "permission_scope", "audit_log_id"):
            invalid = dict(valid)
            invalid.pop(required_field)
            with self.subTest(required_field=required_field):
                with self.assertRaises(ContractValidationError):
                    store.create(invalid)

        invalid_status = dict(valid)
        invalid_status["upload_session_id"] = "upload_invalid_status"
        invalid_status["status"] = "registered"
        with self.assertRaises(ContractValidationError):
            store.create(invalid_status)

    def test_create_upload_session_invalid_input_leaves_no_session_or_ok_audit(self) -> None:
        cases = [
            {"status": "registered", "expected_error": ContractValidationError},
            {"session_id": None, "expected_error": ValueError},
            {"actor_user_id": 123, "expected_error": ValueError},
            {
                "permission_scope": {"scope_type": 123, "visibility": []},
                "expected_error": ContractValidationError,
            },
            {"created_at": "", "expected_error": ContractValidationError},
        ]

        for index, case in enumerate(cases, start=1):
            with self.subTest(case=index):
                temp_dir = _paths.fresh_test_dir(f"upload-session-helper-invalid-input-{index}")
                audit_store = FileAuditLogStore(temp_dir)
                upload_store = UploadSessionStore(temp_dir)
                kwargs = {
                    "upload_session_store": upload_store,
                    "audit_store": audit_store,
                    "actor_user_id": "user_yifan",
                    "session_id": "session_001",
                    "workspace_id": "workspace_formowl",
                    "owner_scope_type": "project",
                    "owner_scope_id": "project_formowl",
                    "intent": "Upload meeting notes for source-backed extraction.",
                    "intended_asset_type": "document",
                    "ingestion_profile": "plain_text",
                    "visibility_scope": "workspace",
                    "permission_scope": PermissionScope.project("project_formowl"),
                    "expires_at": "2026-06-18T10:00:00+00:00",
                    "created_at": "2026-06-17T10:00:00+00:00",
                }
                expected_error = case["expected_error"]
                kwargs.update(
                    {key: value for key, value in case.items() if key != "expected_error"}
                )

                with self.assertRaises(expected_error):
                    create_upload_session(**kwargs)  # type: ignore[arg-type]

                self.assertEqual(upload_store.list(), [])
                self.assertEqual(audit_store.list(), [])


if __name__ == "__main__":
    unittest.main()
