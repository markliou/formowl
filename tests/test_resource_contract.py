from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    Asset,
    AssetMetadata,
    ContractValidationError,
    ExtractorRun,
    IngestionJob,
    Observation,
    PermissionScope,
    SemanticMetadata,
    SourceRef,
    StorageBackend,
)


class ResourceContractTests(unittest.TestCase):
    def test_resource_contract_models_round_trip(self) -> None:
        created_at = "2026-06-17T10:00:00+00:00"
        permission_scope = PermissionScope.project("project_formowl")
        source_ref = SourceRef(
            source_system="local",
            source_type="file",
            source_id="meeting-notes.txt",
            source_key="meeting-notes.txt",
        )

        models = [
            StorageBackend(
                storage_backend_id="storage_local_001",
                type="local_fs",
                display_name="Local test object store",
                access_mode="read_write",
                trust_level="trusted_internal",
                workspace_scope="workspace_formowl",
                health_status="healthy",
                root_prefix="formowl://storage/storage_local_001",
                allowed_workers=["worker_local"],
            ),
            Asset(
                asset_id="asset_001",
                storage_backend_id="storage_local_001",
                object_uri="formowl://asset/asset_001/original",
                content_hash="sha256:abc123",
                file_size=42,
                mime_type="text/plain",
                created_at=created_at,
                registered_at=created_at,
                owner_user_id="user_yifan",
                workspace_id="workspace_formowl",
                permission_scope=permission_scope,
                lifecycle_state="active",
                source_ref=source_ref,
                original_filename="meeting-notes.txt",
            ),
            AssetMetadata(
                asset_id="asset_001",
                metadata_type="technical",
                metadata={"mime_type": "text/plain", "line_count": 2},
                extractor_run_id="run_001",
                created_at=created_at,
            ),
            IngestionJob(
                ingestion_job_id="job_001",
                asset_id="asset_001",
                status="pending",
                requested_by="user_yifan",
                workspace_id="workspace_formowl",
                permission_scope=permission_scope,
                created_at=created_at,
                extractor_names=["plain_text_extractor"],
            ),
            ExtractorRun(
                extractor_run_id="run_001",
                asset_id="asset_001",
                extractor_name="plain_text_extractor",
                extractor_version="0.1.0",
                extractor_type="document_structure",
                input_hash="sha256:abc123",
                config_hash="sha256:def456",
                status="succeeded",
                started_at=created_at,
                completed_at=created_at,
            ),
            Observation(
                observation_id="obs_001",
                asset_id="asset_001",
                extractor_run_id="run_001",
                observation_type="paragraph",
                modality="text",
                text="A source-preserving note.",
                location={"line_start": 1, "line_end": 1},
                confidence=1.0,
                permission_scope=permission_scope,
                created_at=created_at,
            ),
            SemanticMetadata(
                semantic_metadata_id="sem_001",
                source_observation_ids=["obs_001"],
                metadata_type="topic",
                value={"label": "source preservation"},
                confidence=0.8,
                extractor_run_id="run_001",
                requires_review=True,
                created_at=created_at,
            ),
        ]

        for model in models:
            data = model.to_dict()
            round_tripped = type(model).from_dict(data).to_dict()
            self.assertEqual(round_tripped, data)

    def test_resource_contract_to_dict_validates_required_fields(self) -> None:
        created_at = "2026-06-17T10:00:00+00:00"
        permission_scope = PermissionScope.project("project_formowl")

        with self.assertRaises(ContractValidationError):
            Asset(
                asset_id="",
                storage_backend_id="storage_local_001",
                object_uri="formowl://asset/asset_001/original",
                content_hash="sha256:abc123",
                file_size=42,
                mime_type="text/plain",
                created_at=created_at,
                registered_at=created_at,
                owner_user_id="user_yifan",
                workspace_id="workspace_formowl",
                permission_scope=permission_scope,
                lifecycle_state="active",
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            Observation(
                observation_id="obs_001",
                extractor_run_id="run_001",
                observation_type="paragraph",
                modality="text",
                text="A source-preserving note.",
                location={"line_start": 1, "line_end": 1},
                confidence=1.2,
                permission_scope=permission_scope,
                created_at=created_at,
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            SemanticMetadata(
                semantic_metadata_id="sem_001",
                source_observation_ids=[],
                metadata_type="topic",
                value={"label": "source preservation"},
                confidence=0.8,
                extractor_run_id="run_001",
                requires_review=True,
            ).to_dict()


if __name__ == "__main__":
    unittest.main()
