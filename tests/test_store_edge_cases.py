from __future__ import annotations

from dataclasses import replace
import unittest

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from formowl_contract import (
    Asset,
    AuditLog,
    ContractValidationError,
    ExtractorRun,
    IngestionJob,
    Observation,
    PermissionScope,
    SourceRef,
    UploadSession,
)
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    JobStore,
    ObservationStore,
    UploadSessionStore,
)


class StoreEdgeCaseTests(unittest.TestCase):
    def test_record_stores_reject_path_traversal_ids_on_create_and_get(self) -> None:
        temp_dir = _paths.fresh_test_dir("store-edge-safe-record-ids")
        records = _valid_store_records()
        unsafe_cases = [
            (AssetStore, replace(records.asset, asset_id="../asset_escape"), "asset_id"),
            (JobStore, replace(records.job, ingestion_job_id="../job_escape"), "job_id"),
            (
                ExtractorRunStore,
                replace(records.run, extractor_run_id="../run_escape"),
                "run_id",
            ),
            (
                ObservationStore,
                replace(records.observation, observation_id="../obs_escape"),
                "observation_id",
            ),
            (
                UploadSessionStore,
                replace(records.upload_session, upload_session_id="../upload_escape"),
                "upload_session_id",
            ),
        ]

        for store_type, invalid_record, field_name in unsafe_cases:
            store = store_type(temp_dir)
            with self.subTest(store_type=store_type.__name__, field_name=field_name):
                with self.assertRaises(ValueError):
                    store.create(invalid_record)
                with self.assertRaises(ValueError):
                    store.get("../escape")
                self.assertEqual(store.list(), [])

    def test_job_store_rejects_non_string_error_payload(self) -> None:
        temp_dir = _paths.fresh_test_dir("store-edge-job-error-type")
        records = _valid_store_records()
        invalid_job = records.job.to_dict()
        invalid_job["status"] = "failed"
        invalid_job["error"] = 123

        with self.assertRaises(ContractValidationError):
            IngestionJob.from_dict(invalid_job)
        with self.assertRaises(ContractValidationError):
            JobStore(temp_dir).create(invalid_job)

        self.assertEqual(JobStore(temp_dir).list(), [])

    def test_job_store_rejects_malformed_extractor_name_payloads(self) -> None:
        invalid_cases = [
            [],
            [""],
            ["plain_text_extractor", "plain_text_extractor"],
        ]

        for extractor_names in invalid_cases:
            temp_dir = _paths.fresh_test_dir(
                f"store-edge-job-extractor-names-{len(str(extractor_names))}"
            )
            invalid_job = _valid_store_records().job.to_dict()
            invalid_job["extractor_names"] = extractor_names

            with self.subTest(extractor_names=extractor_names):
                with self.assertRaises(ContractValidationError):
                    IngestionJob.from_dict(invalid_job)
                with self.assertRaises(ContractValidationError):
                    JobStore(temp_dir).create(invalid_job)

                self.assertEqual(JobStore(temp_dir).list(), [])

    def test_job_and_run_stores_reject_malformed_timestamp_payloads(self) -> None:
        cases = [
            (
                JobStore,
                "job",
                lambda records: records.job.to_dict(),
                "started_at",
                "",
            ),
            (
                JobStore,
                "job",
                lambda records: records.job.to_dict(),
                "completed_at",
                "not-a-timestamp",
            ),
            (
                ExtractorRunStore,
                "run",
                lambda records: records.run.to_dict(),
                "started_at",
                "not-a-timestamp",
            ),
            (
                ExtractorRunStore,
                "run",
                lambda records: records.run.to_dict(),
                "completed_at",
                "",
            ),
        ]

        for store_type, record_kind, payload_factory, field_name, invalid_value in cases:
            temp_dir = _paths.fresh_test_dir(
                f"store-edge-{record_kind}-{field_name}-{len(str(invalid_value))}"
            )
            invalid_payload = payload_factory(_valid_store_records())
            invalid_payload[field_name] = invalid_value

            with self.subTest(
                store_type=store_type.__name__,
                field_name=field_name,
                invalid_value=invalid_value,
            ):
                with self.assertRaises(ContractValidationError):
                    store_type(temp_dir).create(invalid_payload)

                self.assertEqual(store_type(temp_dir).list(), [])

    def test_run_store_rejects_non_string_optional_model_fields(self) -> None:
        invalid_cases = [
            ("model_name", 123),
            ("model_version", ["v1"]),
            ("prompt_hash", {"hash": "sha256:prompt"}),
        ]

        for field_name, invalid_value in invalid_cases:
            temp_dir = _paths.fresh_test_dir(f"store-edge-run-{field_name}")
            invalid_run = _valid_store_records().run.to_dict()
            invalid_run[field_name] = invalid_value

            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                with self.assertRaises(ContractValidationError):
                    ExtractorRun.from_dict(invalid_run)
                with self.assertRaises(ContractValidationError):
                    ExtractorRunStore(temp_dir).create(invalid_run)

                self.assertEqual(ExtractorRunStore(temp_dir).list(), [])

    def test_observation_store_rejects_non_string_text_and_caption(self) -> None:
        invalid_cases = [
            ("text", ["not", "text"]),
            ("caption", {"caption": "not text"}),
        ]

        for field_name, invalid_value in invalid_cases:
            temp_dir = _paths.fresh_test_dir(f"store-edge-observation-{field_name}")
            invalid_observation = _valid_store_records().observation.to_dict()
            invalid_observation[field_name] = invalid_value

            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                with self.assertRaises(ContractValidationError):
                    Observation.from_dict(invalid_observation)
                with self.assertRaises(ContractValidationError):
                    ObservationStore(temp_dir).create(invalid_observation)

                self.assertEqual(ObservationStore(temp_dir).list(), [])

    def test_audit_log_store_accepts_dicts_persists_after_restart_and_rejects_unsafe_ids(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("store-edge-audit-log")
        audit_log = AuditLog(
            audit_log_id="audit_001",
            actor_user_id="user_yifan",
            action="asset_registered",
            target_type="asset",
            target_id="asset_001",
            session_id="session_001",
            workspace_id="workspace_formowl",
            status="ok",
            timestamp="2026-06-17T10:00:00+00:00",
            metadata={"source": "unit_test"},
        )

        store = FileAuditLogStore(temp_dir)
        self.assertEqual(store.create(audit_log.to_dict()).to_dict(), audit_log.to_dict())

        restarted = FileAuditLogStore(temp_dir)
        self.assertEqual(restarted.get("audit_001").to_dict(), audit_log.to_dict())
        self.assertEqual(
            [item.to_dict() for item in restarted.list()],
            [audit_log.to_dict()],
        )

        invalid = audit_log.to_dict()
        invalid["audit_log_id"] = "../audit_escape"
        with self.assertRaises(ValueError):
            restarted.create(invalid)
        with self.assertRaises(ValueError):
            restarted.get("../audit_escape")
        self.assertEqual(len(restarted.list()), 1)


class _StoreRecords:
    def __init__(
        self,
        *,
        asset: Asset,
        job: IngestionJob,
        run: ExtractorRun,
        observation: Observation,
        upload_session: UploadSession,
    ) -> None:
        self.asset = asset
        self.job = job
        self.run = run
        self.observation = observation
        self.upload_session = upload_session


def _valid_store_records() -> _StoreRecords:
    created_at = "2026-06-17T10:00:00+00:00"
    permission_scope = PermissionScope.project("project_formowl")
    source_ref = SourceRef(
        source_system="local",
        source_type="file",
        source_id="source.txt",
    )
    asset = Asset(
        asset_id="asset_001",
        storage_backend_id="storage_local_001",
        object_uri="formowl://object/storage_local_001/workspace_formowl/hash001",
        content_hash="sha256:abc123",
        file_size=12,
        mime_type="text/plain",
        created_at=created_at,
        registered_at=created_at,
        owner_user_id="user_yifan",
        workspace_id="workspace_formowl",
        permission_scope=permission_scope,
        lifecycle_state="active",
        source_ref=source_ref,
        original_filename="source.txt",
    )
    job = IngestionJob(
        ingestion_job_id="job_001",
        asset_id=asset.asset_id,
        status="pending",
        requested_by="user_yifan",
        workspace_id="workspace_formowl",
        permission_scope=permission_scope,
        created_at=created_at,
        extractor_names=["plain_text_extractor"],
    )
    run = ExtractorRun(
        extractor_run_id="run_001",
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
        observation_id="obs_001",
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
    upload_session = UploadSession(
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
    )
    return _StoreRecords(
        asset=asset,
        job=job,
        run=run,
        observation=observation,
        upload_session=upload_session,
    )


if __name__ == "__main__":
    unittest.main()
