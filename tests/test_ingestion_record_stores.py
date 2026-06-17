from __future__ import annotations

from dataclasses import replace
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    Asset,
    ContractValidationError,
    ExtractorRun,
    IngestionJob,
    Observation,
    PermissionScope,
    SourceRef,
)
from formowl_ingestion.storage import AssetStore, ExtractorRunStore, JobStore, ObservationStore


class IngestionRecordStoreTests(unittest.TestCase):
    def test_create_get_list_records_persist_after_store_restart(self) -> None:
        temp_dir = _paths.fresh_test_dir("ingestion-record-stores")
        created_at = "2026-06-17T10:00:00+00:00"
        permission_scope = PermissionScope.project("project_formowl")

        asset = Asset(
            asset_id="asset_record_001",
            storage_backend_id="storage_local_001",
            object_uri="formowl://object/storage_local_001/workspace_formowl/hash001",
            content_hash="sha256:abc123",
            file_size=42,
            mime_type="text/plain",
            created_at=created_at,
            registered_at=created_at,
            owner_user_id="user_yifan",
            workspace_id="workspace_formowl",
            permission_scope=permission_scope,
            lifecycle_state="active",
            source_ref=SourceRef(
                source_system="local",
                source_type="file",
                source_id="meeting-notes.txt",
            ),
            original_filename="meeting-notes.txt",
        )
        job = IngestionJob(
            ingestion_job_id="job_record_001",
            asset_id=asset.asset_id,
            status="succeeded",
            requested_by="user_yifan",
            workspace_id="workspace_formowl",
            permission_scope=permission_scope,
            created_at=created_at,
            extractor_names=["plain_text_extractor"],
            extractor_run_ids=["run_record_001"],
            observation_ids=["obs_record_001"],
            started_at=created_at,
            completed_at=created_at,
        )
        run = ExtractorRun(
            extractor_run_id="run_record_001",
            asset_id=asset.asset_id,
            extractor_name="plain_text_extractor",
            extractor_version="0.1.0",
            extractor_type="document_structure",
            input_hash=asset.content_hash,
            config_hash="sha256:config",
            status="succeeded",
            started_at=created_at,
            completed_at=created_at,
        )
        observation = Observation(
            observation_id="obs_record_001",
            asset_id=asset.asset_id,
            extractor_run_id=run.extractor_run_id,
            observation_type="paragraph",
            modality="text",
            text="A persisted observation.",
            location={"line_start": 1, "line_end": 1},
            confidence=1.0,
            permission_scope=permission_scope,
            created_at=created_at,
        )

        self.assertEqual(AssetStore(temp_dir).create(asset).to_dict(), asset.to_dict())
        self.assertEqual(JobStore(temp_dir).create(job).to_dict(), job.to_dict())
        self.assertEqual(ExtractorRunStore(temp_dir).create(run).to_dict(), run.to_dict())
        self.assertEqual(
            ObservationStore(temp_dir).create(observation).to_dict(),
            observation.to_dict(),
        )

        restarted_asset_store = AssetStore(temp_dir)
        restarted_job_store = JobStore(temp_dir)
        restarted_run_store = ExtractorRunStore(temp_dir)
        restarted_observation_store = ObservationStore(temp_dir)

        self.assertEqual(restarted_asset_store.get(asset.asset_id).to_dict(), asset.to_dict())
        self.assertEqual(
            restarted_job_store.get(job.ingestion_job_id).to_dict(),
            job.to_dict(),
        )
        self.assertEqual(
            restarted_run_store.get(run.extractor_run_id).to_dict(),
            run.to_dict(),
        )
        self.assertEqual(
            restarted_observation_store.get(observation.observation_id).to_dict(),
            observation.to_dict(),
        )
        self.assertEqual(
            [item.to_dict() for item in restarted_asset_store.list()],
            [asset.to_dict()],
        )
        self.assertEqual(
            [item.to_dict() for item in restarted_job_store.list()],
            [job.to_dict()],
        )
        self.assertEqual(
            [item.to_dict() for item in restarted_run_store.list()],
            [run.to_dict()],
        )
        self.assertEqual(
            [item.to_dict() for item in restarted_observation_store.list()],
            [observation.to_dict()],
        )

    def test_create_accepts_dict_payloads_and_validates_contracts(self) -> None:
        temp_dir = _paths.fresh_test_dir("ingestion-record-stores-dict-validation")
        created_at = "2026-06-17T10:00:00+00:00"
        permission_scope = PermissionScope.project("project_formowl")
        job = IngestionJob(
            ingestion_job_id="job_record_001",
            asset_id="asset_record_001",
            status="pending",
            requested_by="user_yifan",
            workspace_id="workspace_formowl",
            permission_scope=permission_scope,
            created_at=created_at,
            extractor_names=["plain_text_extractor"],
        )

        self.assertEqual(JobStore(temp_dir).create(job.to_dict()).to_dict(), job.to_dict())

        invalid_job = replace(job, status="unknown")  # type: ignore[arg-type]
        with self.assertRaises(ContractValidationError):
            JobStore(temp_dir).create(invalid_job)

    def test_missing_records_return_none(self) -> None:
        temp_dir = _paths.fresh_test_dir("ingestion-record-stores-missing")

        self.assertIsNone(AssetStore(temp_dir).get("asset_missing"))
        self.assertIsNone(JobStore(temp_dir).get("job_missing"))
        self.assertIsNone(ExtractorRunStore(temp_dir).get("run_missing"))
        self.assertIsNone(ObservationStore(temp_dir).get("obs_missing"))


if __name__ == "__main__":
    unittest.main()
