from __future__ import annotations

import json
from pathlib import Path
import unittest

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from formowl_contract import PermissionScope
from formowl_ingestion.extractors import PlainTextObservationExtractor
from formowl_ingestion.folder_inbox import scan_local_data_resource_folder
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
)


class LocalFolderIngestionTests(unittest.TestCase):
    def test_local_folder_scan_registers_new_asset(self) -> None:
        context = _LocalFolderContext.create("local-folder-registers-new-asset")

        first = context.scan()
        result = context.scan(previous_snapshots=first.stability_snapshots_by_token())

        self.assertEqual(result.items[0].status, "registered")
        self.assertEqual(len(context.asset_store.list()), 1)
        asset = context.asset_store.list()[0]
        self.assertEqual(result.items[0].asset_id, asset.asset_id)
        self.assertTrue(asset.object_uri.startswith("formowl://object/"))
        self.assertEqual(asset.source_ref["source_system"], "local_folder_inbox")
        self.assertEqual(asset.source_ref["source_type"], "file_content")
        self.assertEqual(asset.source_ref["source_id"], asset.content_hash)

    def test_local_folder_scan_is_idempotent_for_same_content(self) -> None:
        context = _LocalFolderContext.create("local-folder-idempotent-asset")

        first = context.scan()
        second = context.scan(previous_snapshots=first.stability_snapshots_by_token())
        third = context.scan(previous_snapshots=second.stability_snapshots_by_token())

        self.assertEqual(second.items[0].asset_id, third.items[0].asset_id)
        self.assertEqual(len(context.asset_store.list()), 1)
        self.assertEqual(len(list(context.object_root.glob("objects/**/payload.bin"))), 1)
        self.assertIn("existing_asset", third.items[0].warnings)

    def test_local_folder_scan_does_not_create_duplicate_jobs_for_same_content(self) -> None:
        context = _LocalFolderContext.create("local-folder-idempotent-job")

        first = context.scan(extractor_names=["plain_text_extractor"])
        second = context.scan(
            previous_snapshots=first.stability_snapshots_by_token(),
            extractor_names=["plain_text_extractor"],
        )
        third = context.scan(
            previous_snapshots=second.stability_snapshots_by_token(),
            extractor_names=["plain_text_extractor"],
        )

        self.assertEqual(second.items[0].ingestion_job_id, third.items[0].ingestion_job_id)
        self.assertEqual(len(context.job_store.list()), 1)
        self.assertIn("existing_job", third.items[0].warnings)

    def test_local_folder_scan_defers_unstable_file_with_zero_side_effects(self) -> None:
        context = _LocalFolderContext.create("local-folder-unstable-zero-side-effects")
        audit_store = FileAuditLogStore(context.temp_dir)

        result = context.scan(
            extractor_adapters=[PlainTextObservationExtractor()],
            run_configured_extractors=True,
            audit_store=audit_store,
        )

        self.assertEqual(result.items[0].status, "deferred_unstable")
        self.assertEqual(context.asset_store.list(), [])
        self.assertEqual(context.job_store.list(), [])
        self.assertEqual(context.run_store.list(), [])
        self.assertEqual(context.observation_store.list(), [])
        self.assertEqual(audit_store.list(), [])
        self.assertEqual(list(context.object_root.glob("objects/**/payload.bin")), [])
        self.assertEqual(list(context.object_root.glob("objects/**/metadata.json")), [])

    def test_local_folder_scan_fails_if_file_changes_before_object_copy(self) -> None:
        context = _LocalFolderContext.create("local-folder-copy-race-zero-side-effects")
        audit_store = FileAuditLogStore(context.temp_dir)
        context.object_store = _MutatingObjectStore(context.object_store.backend_registry)

        first = context.scan()
        result = context.scan(
            previous_snapshots=first.stability_snapshots_by_token(),
            audit_store=audit_store,
        )

        public_payload = json.dumps(result.to_dict(), sort_keys=True)
        self.assertEqual(result.items[0].status, "failed")
        self.assertIn("stable_file_ingestion_failed", result.items[0].warnings)
        self.assertEqual(context.asset_store.list(), [])
        self.assertEqual(context.job_store.list(), [])
        self.assertEqual(context.run_store.list(), [])
        self.assertEqual(context.observation_store.list(), [])
        self.assertEqual(audit_store.list(), [])
        self.assertEqual(list(context.object_root.glob("objects/**/payload.bin")), [])
        self.assertEqual(list(context.object_root.glob("objects/**/metadata.json")), [])
        self.assertNotIn(str(context.inbox_dir), public_payload)
        self.assertNotIn(str(context.source_path), public_payload)
        self.assertNotIn(context.source_path.name, public_payload)

    def test_local_folder_ingestion_creates_ingestion_job(self) -> None:
        context = _LocalFolderContext.create("local-folder-creates-job")

        first = context.scan(extractor_names=["plain_text_extractor"])
        result = context.scan(
            previous_snapshots=first.stability_snapshots_by_token(),
            extractor_names=["plain_text_extractor"],
        )

        self.assertEqual(result.items[0].status, "queued")
        self.assertEqual(len(context.job_store.list()), 1)
        job = context.job_store.list()[0]
        self.assertEqual(result.items[0].ingestion_job_id, job.ingestion_job_id)
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.extractor_names, ["plain_text_extractor"])

    def test_local_folder_ingestion_runs_deterministic_text_extractor(self) -> None:
        context = _LocalFolderContext.create("local-folder-runs-text-extractor")

        first = context.scan(
            extractor_adapters=[PlainTextObservationExtractor()],
            run_configured_extractors=True,
        )
        result = context.scan(
            previous_snapshots=first.stability_snapshots_by_token(),
            extractor_adapters=[PlainTextObservationExtractor()],
            run_configured_extractors=True,
        )

        self.assertEqual(result.items[0].status, "ingested")
        self.assertEqual(len(context.run_store.list()), 1)
        run = context.run_store.list()[0]
        self.assertEqual(run.extractor_name, "plain_text_extractor")
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(result.items[0].extractor_run_ids, [run.extractor_run_id])

    def test_local_folder_ingestion_persists_observation(self) -> None:
        context = _LocalFolderContext.create(
            "local-folder-persists-observation",
            content="# Inbox Note\n\nUse observations before graph governance.\n",
            filename="inbox-note.md",
        )

        first = context.scan(
            extractor_adapters=[PlainTextObservationExtractor()],
            run_configured_extractors=True,
        )
        result = context.scan(
            previous_snapshots=first.stability_snapshots_by_token(),
            extractor_adapters=[PlainTextObservationExtractor()],
            run_configured_extractors=True,
        )

        self.assertEqual(result.items[0].observation_count, 2)
        observations = context.observation_store.list()
        self.assertEqual(
            [observation.text for observation in observations],
            [
                "# Inbox Note",
                "Use observations before graph governance.",
            ],
        )
        self.assertEqual(
            observations[0].payload["source_ref"]["source_system"], "local_folder_inbox"
        )

    def test_local_folder_public_output_redacts_local_path(self) -> None:
        context = _LocalFolderContext.create("local-folder-public-redaction")

        first = context.scan(
            extractor_adapters=[PlainTextObservationExtractor()],
            run_configured_extractors=True,
        )
        result = context.scan(
            previous_snapshots=first.stability_snapshots_by_token(),
            extractor_adapters=[PlainTextObservationExtractor()],
            run_configured_extractors=True,
        )

        public_payload = json.dumps(result.to_dict(), sort_keys=True)
        object_payload_path = context.object_store.resolve_object_path(result.items[0].object_uri)
        self.assertNotIn(str(context.inbox_dir), public_payload)
        self.assertNotIn(str(context.source_path), public_payload)
        self.assertNotIn(str(context.object_root), public_payload)
        self.assertNotIn(str(object_payload_path), public_payload)
        self.assertNotIn(context.source_path.name, public_payload)
        self.assertNotIn("source_file_token", public_payload)
        self.assertNotIn(result.items[0].source_file_token, public_payload)
        self.assertIn("formowl://object/", public_payload)

    def test_local_folder_audit_records_actor_workspace_action_for_successful_ingestion(
        self,
    ) -> None:
        context = _LocalFolderContext.create("local-folder-audit-success")
        audit_store = FileAuditLogStore(context.temp_dir)

        first = context.scan(
            extractor_adapters=[PlainTextObservationExtractor()],
            run_configured_extractors=True,
            audit_store=audit_store,
        )
        result = context.scan(
            previous_snapshots=first.stability_snapshots_by_token(),
            extractor_adapters=[PlainTextObservationExtractor()],
            run_configured_extractors=True,
            audit_store=audit_store,
        )

        self.assertEqual(result.items[0].status, "ingested")
        logs = audit_store.list()
        self.assertEqual(
            {log.action for log in logs}, {"asset_registered", "ingestion_job_created"}
        )
        for log in logs:
            self.assertEqual(log.actor_user_id, context.actor_user_id)
            self.assertEqual(log.workspace_id, context.workspace_id)
            self.assertEqual(log.session_id, context.session_id)
            self.assertEqual(log.status, "ok")


class _LocalFolderContext:
    def __init__(
        self,
        *,
        temp_dir,
        inbox_dir,
        source_path,
        object_root,
        storage_backend_id: str,
        object_store: FileObjectStore,
        asset_store: AssetStore,
        job_store: JobStore,
        run_store: ExtractorRunStore,
        observation_store: ObservationStore,
    ) -> None:
        self.temp_dir = temp_dir
        self.inbox_dir = inbox_dir
        self.source_path = source_path
        self.object_root = object_root
        self.storage_backend_id = storage_backend_id
        self.object_store = object_store
        self.asset_store = asset_store
        self.job_store = job_store
        self.run_store = run_store
        self.observation_store = observation_store
        self.workspace_id = "workspace_formowl"
        self.actor_user_id = "user_yifan"
        self.session_id = "session_001"
        self.permission_scope = PermissionScope.project("project_formowl")

    @classmethod
    def create(
        cls,
        test_dir_name: str,
        *,
        filename: str = "inbox-note.txt",
        content: str = "Use the shared folder inbox.\n",
    ) -> "_LocalFolderContext":
        temp_dir = _paths.fresh_test_dir(test_dir_name)
        inbox_dir = temp_dir / "trusted-inbox"
        inbox_dir.mkdir(parents=True)
        source_path = inbox_dir / filename
        source_path.write_text(content, encoding="utf-8")
        object_root = temp_dir / "object-root"
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            object_root,
            workspace_scope="workspace_formowl",
        )
        return cls(
            temp_dir=temp_dir,
            inbox_dir=inbox_dir,
            source_path=source_path,
            object_root=object_root,
            storage_backend_id=backend.storage_backend_id,
            object_store=FileObjectStore(registry),
            asset_store=AssetStore(temp_dir),
            job_store=JobStore(temp_dir),
            run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
        )

    def scan(self, **kwargs):
        return scan_local_data_resource_folder(
            self.inbox_dir,
            object_store=self.object_store,
            asset_store=self.asset_store,
            job_store=self.job_store,
            storage_backend_id=self.storage_backend_id,
            workspace_id=self.workspace_id,
            owner_user_id=self.actor_user_id,
            requested_by=self.actor_user_id,
            permission_scope=self.permission_scope,
            extractor_run_store=self.run_store,
            observation_store=self.observation_store,
            created_at="2026-06-29T00:00:00+00:00",
            registered_at="2026-06-29T00:00:00+00:00",
            job_created_at="2026-06-29T00:00:00+00:00",
            started_at="2026-06-29T00:01:00+00:00",
            completed_at="2026-06-29T00:01:00+00:00",
            actor_user_id=self.actor_user_id,
            session_id=self.session_id,
            **kwargs,
        )


class _MutatingObjectStore(FileObjectStore):
    def copy_local_file(self, source_path, **kwargs):
        Path(source_path).write_text("changed while scanner was copying\n", encoding="utf-8")
        return super().copy_local_file(source_path, **kwargs)


if __name__ == "__main__":
    unittest.main()
