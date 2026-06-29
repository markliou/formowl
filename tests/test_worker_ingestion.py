from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extractors import PlainTextObservationExtractor
from formowl_ingestion.jobs import create_ingestion_job
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
)
from formowl_worker import IngestionWorker


class IngestionWorkerTests(unittest.TestCase):
    def test_worker_runs_pending_job_without_changing_job_contract(self) -> None:
        context = _WorkerContext.create(
            "worker-ingestion-runs-pending",
            allowed_workers=["worker_local"],
        )
        asset = context.register_text_asset()
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_names=["plain_text_extractor"],
            created_at="2026-06-29T00:00:00+00:00",
        )
        worker = context.worker(
            worker_id="worker_local",
            extractor_adapters=[PlainTextObservationExtractor()],
        )

        result = worker.run_once(
            started_at="2026-06-29T00:01:00+00:00",
            completed_at="2026-06-29T00:01:00+00:00",
        )

        completed = context.job_store.get(job.ingestion_job_id)
        self.assertEqual(result.processed_job_ids, [job.ingestion_job_id])
        self.assertEqual(result.succeeded_job_ids, [job.ingestion_job_id])
        self.assertEqual(result.failed_job_ids, [])
        self.assertEqual(result.skipped_job_ids, [])
        self.assertEqual(completed.status, "succeeded")
        self.assertEqual(len(completed.extractor_run_ids), 1)
        self.assertEqual(len(completed.observation_ids), 1)
        self.assertNotIn("lease_owner", completed.to_dict())
        self.assertNotIn("worker_scratch", completed.to_dict())

        rendered_result = json.dumps(result.to_dict(), sort_keys=True)
        self.assertNotIn(str(context.source_path), rendered_result)
        self.assertNotIn("object-root", rendered_result)

    def test_worker_skips_backend_that_does_not_allow_worker_without_mutating_job(
        self,
    ) -> None:
        context = _WorkerContext.create(
            "worker-ingestion-not-allowed",
            allowed_workers=["worker_gpu"],
        )
        asset = context.register_text_asset()
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_names=["plain_text_extractor"],
            created_at="2026-06-29T00:00:00+00:00",
        )
        worker = context.worker(
            worker_id="worker_cpu",
            extractor_adapters=[PlainTextObservationExtractor()],
        )

        result = worker.run_once(
            started_at="2026-06-29T00:01:00+00:00",
            completed_at="2026-06-29T00:01:00+00:00",
        )

        self.assertEqual(result.processed_job_ids, [])
        self.assertEqual(result.skipped_job_ids, [job.ingestion_job_id])
        self.assertEqual(result.warnings, [f"worker_not_allowed:{job.ingestion_job_id}"])
        self.assertEqual(context.job_store.get(job.ingestion_job_id).to_dict(), job.to_dict())
        self.assertEqual(context.run_store.list(), [])
        self.assertEqual(context.observation_store.list(), [])

    def test_worker_failed_job_uses_existing_failure_path_without_raw_result_leak(self) -> None:
        context = _WorkerContext.create("worker-ingestion-missing-adapter")
        asset = context.register_text_asset()
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_names=["missing_extractor"],
            created_at="2026-06-29T00:00:00+00:00",
        )
        worker = context.worker(worker_id="worker_local", extractor_adapters=[])

        result = worker.run_once(
            started_at="2026-06-29T00:01:00+00:00",
            completed_at="2026-06-29T00:01:00+00:00",
        )

        completed = context.job_store.get(job.ingestion_job_id)
        self.assertEqual(result.processed_job_ids, [job.ingestion_job_id])
        self.assertEqual(result.failed_job_ids, [job.ingestion_job_id])
        self.assertEqual(completed.status, "failed")
        self.assertIn("extractor adapter was not provided", completed.error)

        rendered_result = json.dumps(result.to_dict(), sort_keys=True)
        self.assertNotIn(str(context.source_path), rendered_result)
        self.assertNotIn("object-root", rendered_result)


class _WorkerContext:
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
    ) -> None:
        self.temp_dir = temp_dir
        self.source_path = source_path
        self.storage_backend_id = storage_backend_id
        self.object_store = object_store
        self.asset_store = asset_store
        self.job_store = job_store
        self.run_store = run_store
        self.observation_store = observation_store

    @classmethod
    def create(
        cls,
        test_dir_name: str,
        *,
        allowed_workers: list[str] | None = None,
    ) -> "_WorkerContext":
        temp_dir = _paths.fresh_test_dir(test_dir_name)
        source_path = temp_dir / "incoming" / "notes.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("Worker boundary runs extraction outside MCP.\n", encoding="utf-8")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
            allowed_workers=allowed_workers,
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
        )

    def register_text_asset(self):
        return register_asset_from_local_file(
            self.source_path,
            object_store=self.object_store,
            asset_store=self.asset_store,
            storage_backend_id=self.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=SourceRef(
                source_system="local",
                source_type="file",
                source_id="notes.txt",
                source_key="notes.txt",
            ),
            mime_type="text/plain",
            created_at="2026-06-29T00:00:00+00:00",
            registered_at="2026-06-29T00:00:00+00:00",
        )

    def worker(self, *, worker_id: str, extractor_adapters):
        return IngestionWorker(
            worker_id=worker_id,
            asset_store=self.asset_store,
            job_store=self.job_store,
            object_store=self.object_store,
            extractor_run_store=self.run_store,
            observation_store=self.observation_store,
            extractor_adapters=extractor_adapters,
        )


if __name__ == "__main__":
    unittest.main()
