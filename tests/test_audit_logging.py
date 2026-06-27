from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore, record_permission_denied
from formowl_contract import EvidenceSnapshot, PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.jobs import create_ingestion_job
from formowl_ingestion.storage import AssetStore, FileObjectStore, JobStore, StorageBackendRegistry
from formowl_project_mcp.storage import FileEvidenceSnapshotStore


class AuditLoggingTests(unittest.TestCase):
    def test_core_identity_and_ingestion_events_are_audited(self) -> None:
        temp_dir = _paths.fresh_test_dir("audit-logging")
        created_at = "2026-06-17T10:00:00+00:00"
        workspace_id = "workspace_formowl"
        actor_user_id = "user_yifan"
        session_id = "session_001"
        permission_scope = PermissionScope.project("project_formowl")
        source_ref = SourceRef(
            source_system="local",
            source_type="file",
            source_id="meeting-notes.txt",
            source_key="meeting-notes.txt",
        )
        source_path = temp_dir / "incoming" / "meeting-notes.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("Use audited source registration.\n", encoding="utf-8")

        audit_store = FileAuditLogStore(temp_dir)
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope=workspace_id,
        )
        asset = register_asset_from_local_file(
            source_path,
            object_store=FileObjectStore(registry),
            asset_store=AssetStore(temp_dir),
            storage_backend_id=backend.storage_backend_id,
            workspace_id=workspace_id,
            owner_user_id=actor_user_id,
            permission_scope=permission_scope,
            source_ref=source_ref,
            created_at=created_at,
            registered_at=created_at,
            audit_store=audit_store,
            actor_user_id=actor_user_id,
            session_id=session_id,
        )
        job = create_ingestion_job(
            asset=asset,
            job_store=JobStore(temp_dir),
            requested_by=actor_user_id,
            extractor_names=["plain_text_extractor"],
            created_at=created_at,
            audit_store=audit_store,
            actor_user_id=actor_user_id,
            session_id=session_id,
        )

        evidence_store = FileEvidenceSnapshotStore(temp_dir)
        evidence_store.save_snapshot(
            {
                "snapshot": EvidenceSnapshot(
                    evidence_snapshot_id="ev_001",
                    mcp_server="project-mcp",
                    tool_name="get_work_item_context",
                    captured_at=created_at,
                    permission_scope=permission_scope,
                    source_refs=[source_ref],
                ),
                "request_payload": {},
                "response_payload": {"ok": True},
                "normalized_markdown": "Evidence",
            }
        )
        self.assertIsNotNone(
            evidence_store.get_snapshot(
                "ev_001",
                audit_store=audit_store,
                actor_user_id=actor_user_id,
                session_id=session_id,
                workspace_id=workspace_id,
                timestamp=created_at,
            )
        )
        record_permission_denied(
            audit_store,
            actor_user_id=actor_user_id,
            target_type="asset",
            target_id="asset_private",
            workspace_id=workspace_id,
            session_id=session_id,
            timestamp=created_at,
            reason="grant_required",
        )

        logs = [audit_log.to_dict() for audit_log in audit_store.list()]
        actions = {log["action"] for log in logs}
        self.assertEqual(
            actions,
            {
                "asset_registered",
                "ingestion_job_created",
                "evidence_fetched",
                "permission_denied",
            },
        )
        self.assertIn(asset.asset_id, {log["target_id"] for log in logs})
        self.assertIn(job.ingestion_job_id, {log["target_id"] for log in logs})
        for log in logs:
            self.assertEqual(log["actor_user_id"], actor_user_id)
            self.assertEqual(log["workspace_id"], workspace_id)
            self.assertEqual(log["session_id"], session_id)
            self.assertIn("target_type", log)
            self.assertIn("target_id", log)
            self.assertIn("status", log)
            self.assertEqual(log["timestamp"], created_at)


if __name__ == "__main__":
    unittest.main()
