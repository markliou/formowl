from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from formowl_contract import PermissionScope, SourceRef
from formowl_ingestion.storage import AssetStore, FileObjectStore, StorageBackendRegistry
from formowl_ingestion.uploads import upload_asset_reference


class UploadAssetReferenceTests(unittest.TestCase):
    def test_controlled_upload_asset_reference_registers_asset_permission_and_audit(self) -> None:
        temp_dir = _paths.fresh_test_dir("upload-asset-reference")
        source_path = temp_dir / "trusted-import" / "meeting-notes.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("Controlled imports still become assets.\n", encoding="utf-8")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        audit_store = FileAuditLogStore(temp_dir)
        source_ref = SourceRef(
            source_system="migration",
            source_type="trusted_file_reference",
            source_id="batch-001/meeting-notes.txt",
            source_key="batch-001/meeting-notes.txt",
        )
        permission_scope = PermissionScope.project("project_formowl")

        asset = upload_asset_reference(
            source_path,
            object_store=FileObjectStore(registry),
            asset_store=AssetStore(temp_dir),
            audit_store=audit_store,
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            actor_user_id="user_yifan",
            session_id="session_001",
            permission_scope=permission_scope,
            source_ref=source_ref,
            controlled_import_reason="migration batch 001",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )

        self.assertEqual(asset.permission_scope, permission_scope.to_dict())
        self.assertEqual(asset.source_ref, source_ref.to_dict())
        self.assertTrue(asset.object_uri.startswith("formowl://object/"))
        self.assertNotIn(str(source_path), json.dumps(asset.to_dict(), sort_keys=True))

        audit_logs = audit_store.list()
        actions = [audit_log.action for audit_log in audit_logs]
        self.assertEqual(set(actions), {"asset_registered", "asset_reference_uploaded"})
        for audit_log in audit_logs:
            self.assertEqual(audit_log.actor_user_id, "user_yifan")
            self.assertEqual(audit_log.workspace_id, "workspace_formowl")
            self.assertEqual(audit_log.target_id, asset.asset_id)
            self.assertEqual(audit_log.status, "ok")
        reference_log = next(
            audit_log for audit_log in audit_logs if audit_log.action == "asset_reference_uploaded"
        )
        self.assertEqual(
            reference_log.metadata,
            {"controlled_import_reason": "migration batch 001"},
        )

    def test_controlled_upload_asset_reference_requires_reason(self) -> None:
        temp_dir = _paths.fresh_test_dir("upload-asset-reference-validation")
        source_path = temp_dir / "trusted-import" / "meeting-notes.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("Controlled imports need a reason.\n", encoding="utf-8")
        object_root = temp_dir / "object-root"
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            object_root,
            workspace_scope="workspace_formowl",
        )
        asset_store = AssetStore(temp_dir)
        audit_store = FileAuditLogStore(temp_dir)

        with self.assertRaises(ValueError):
            upload_asset_reference(
                source_path,
                object_store=FileObjectStore(registry),
                asset_store=asset_store,
                audit_store=audit_store,
                storage_backend_id=backend.storage_backend_id,
                workspace_id="workspace_formowl",
                owner_user_id="user_yifan",
                actor_user_id="user_yifan",
                session_id="session_001",
                permission_scope=PermissionScope.project("project_formowl"),
                source_ref=SourceRef(
                    source_system="migration",
                    source_type="trusted_file_reference",
                    source_id="batch-001/meeting-notes.txt",
                ),
                controlled_import_reason="",
            )

        self.assertEqual(asset_store.list(), [])
        self.assertEqual(audit_store.list(), [])
        self.assertEqual(list(object_root.glob("objects/**/payload.bin")), [])
        self.assertEqual(list(object_root.glob("objects/**/metadata.json")), [])


if __name__ == "__main__":
    unittest.main()
