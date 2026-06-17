from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import ExtractionInput, ExtractionResult
from formowl_ingestion.extractors import PlainTextObservationExtractor
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
)


class IngestionWorkflowTests(unittest.TestCase):
    def test_asset_to_job_to_run_to_observation_persists_after_restart(self) -> None:
        context = _WorkflowContext.create(
            "ingestion-workflow",
            filename="meeting-notes.md",
            content="# Meeting Notes\n\nUse observations before graph governance.\n",
        )

        asset = register_asset_from_local_file(
            context.source_path,
            object_store=context.object_store,
            asset_store=context.asset_store,
            storage_backend_id=context.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=context.permission_scope,
            source_ref=context.source_ref,
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_names=["plain_text_extractor"],
            config={"mode": "block"},
            created_at="2026-06-17T10:00:00+00:00",
        )
        recording_extractor = _RecordingTextExtractor(context.job_store, job.ingestion_job_id)

        completed = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id,
            asset_store=context.asset_store,
            job_store=context.job_store,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            extractor_adapters=[recording_extractor],
            config={"mode": "block"},
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertTrue(asset.asset_id.startswith("asset_"))
        self.assertTrue(asset.object_uri.startswith("formowl://object/"))
        self.assertTrue(asset.content_hash.startswith("sha256:"))
        self.assertEqual(asset.file_size, context.source_path.stat().st_size)
        self.assertEqual(asset.permission_scope, context.permission_scope.to_dict())
        self.assertEqual(asset.source_ref, context.source_ref.to_dict())
        self.assertEqual(context.asset_store.get(asset.asset_id).to_dict(), asset.to_dict())
        self.assertNotIn(str(context.source_path), json.dumps(asset.to_dict(), sort_keys=True))

        self.assertEqual(job.status, "pending")
        self.assertEqual(recording_extractor.seen_job_statuses, ["running"])
        self.assertEqual(completed.status, "succeeded")
        self.assertEqual(completed.started_at, "2026-06-17T10:01:00+00:00")
        self.assertEqual(completed.completed_at, "2026-06-17T10:01:00+00:00")
        self.assertEqual(completed.error, None)
        self.assertEqual(len(completed.extractor_run_ids), 1)
        self.assertEqual(len(completed.observation_ids), 2)

        restarted_assets = AssetStore(context.temp_dir)
        restarted_jobs = JobStore(context.temp_dir)
        restarted_runs = ExtractorRunStore(context.temp_dir)
        restarted_observations = ObservationStore(context.temp_dir)
        run = restarted_runs.get(completed.extractor_run_ids[0])
        observations = [restarted_observations.get(item) for item in completed.observation_ids]

        self.assertEqual(restarted_assets.get(asset.asset_id).to_dict(), asset.to_dict())
        self.assertEqual(
            restarted_jobs.get(job.ingestion_job_id).to_dict(),
            completed.to_dict(),
        )
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.input_hash, asset.content_hash)
        self.assertEqual(run.extractor_name, "plain_text_extractor")
        self.assertEqual(
            [item.text for item in observations],
            [
                "# Meeting Notes",
                "Use observations before graph governance.",
            ],
        )
        for observation in observations:
            self.assertEqual(observation.asset_id, asset.asset_id)
            self.assertEqual(observation.permission_scope, context.permission_scope.to_dict())
            self.assertEqual(observation.payload["source_ref"], context.source_ref.to_dict())

    def test_failed_ingestion_job_records_error_without_observations(self) -> None:
        context = _WorkflowContext.create(
            "ingestion-workflow-failed",
            filename="archive.bin",
            content="not a text asset",
        )
        asset = register_asset_from_local_file(
            context.source_path,
            object_store=context.object_store,
            asset_store=context.asset_store,
            storage_backend_id=context.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=context.permission_scope,
            source_ref=context.source_ref,
            mime_type="application/octet-stream",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_adapters=[PlainTextObservationExtractor()],
            created_at="2026-06-17T10:00:00+00:00",
        )

        failed = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id,
            asset_store=context.asset_store,
            job_store=context.job_store,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            extractor_adapters=[PlainTextObservationExtractor()],
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(failed.status, "failed")
        self.assertIn("does not support asset MIME type", failed.error)
        self.assertEqual(failed.extractor_run_ids, [])
        self.assertEqual(failed.observation_ids, [])
        self.assertEqual(context.observation_store.list(), [])
        self.assertEqual(context.job_store.get(job.ingestion_job_id).to_dict(), failed.to_dict())


class _RecordingTextExtractor(PlainTextObservationExtractor):
    def __init__(self, job_store: JobStore, ingestion_job_id: str) -> None:
        super().__init__()
        self.job_store = job_store
        self.ingestion_job_id = ingestion_job_id
        self.seen_job_statuses: list[str] = []

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        job = self.job_store.get(self.ingestion_job_id)
        self.seen_job_statuses.append(job.status if job is not None else "missing")
        return super().extract(extraction_input)


class _WorkflowContext:
    def __init__(
        self,
        *,
        temp_dir,
        source_path,
        storage_backend_id: str,
        object_store: FileObjectStore,
        asset_store: AssetStore,
        job_store: JobStore,
        run_store: ExtractorRunStore,
        observation_store: ObservationStore,
        permission_scope: PermissionScope,
        source_ref: SourceRef,
    ) -> None:
        self.temp_dir = temp_dir
        self.source_path = source_path
        self.storage_backend_id = storage_backend_id
        self.object_store = object_store
        self.asset_store = asset_store
        self.job_store = job_store
        self.run_store = run_store
        self.observation_store = observation_store
        self.permission_scope = permission_scope
        self.source_ref = source_ref

    @classmethod
    def create(
        cls,
        test_dir_name: str,
        *,
        filename: str,
        content: str,
    ) -> "_WorkflowContext":
        temp_dir = _paths.fresh_test_dir(test_dir_name)
        source_path = temp_dir / "incoming" / filename
        source_path.parent.mkdir(parents=True)
        source_path.write_text(content, encoding="utf-8")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        return cls(
            temp_dir=temp_dir,
            source_path=source_path,
            storage_backend_id=backend.storage_backend_id,
            object_store=FileObjectStore(registry),
            asset_store=AssetStore(temp_dir),
            job_store=JobStore(temp_dir),
            run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=SourceRef(
                source_system="local",
                source_type="file",
                source_id=filename,
                source_key=filename,
            ),
        )


if __name__ == "__main__":
    unittest.main()
