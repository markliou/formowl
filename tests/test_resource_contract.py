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
    stable_asset_id,
    stable_asset_metadata_hash,
    stable_extractor_run_id,
    stable_ingestion_job_id,
    stable_observation_id,
    stable_resource_contract_hash,
    stable_resource_contract_id,
    stable_semantic_metadata_id,
    stable_storage_backend_id,
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
                asset_id="asset_001",
                storage_backend_id="storage_local_001",
                object_uri="formowl://asset/asset_001/original",
                content_hash="sha256:abc123",
                file_size=-1,
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

    def test_resource_contract_validators_reject_non_string_list_entries(self) -> None:
        created_at = "2026-06-17T10:00:00+00:00"
        permission_scope = PermissionScope.project("project_formowl")

        with self.assertRaises(ContractValidationError):
            StorageBackend(
                storage_backend_id="storage_local_001",
                type="local_fs",
                display_name="Local test object store",
                access_mode="read_write",
                trust_level="trusted_internal",
                workspace_scope="workspace_formowl",
                health_status="healthy",
                allowed_workers=["worker_local", 42],
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            IngestionJob(
                ingestion_job_id="job_001",
                asset_id="asset_001",
                status="pending",
                requested_by="user_yifan",
                workspace_id="workspace_formowl",
                permission_scope=permission_scope,
                created_at=created_at,
                extractor_names=["plain_text_extractor", 42],
            ).to_dict()

        with self.assertRaises(ContractValidationError):
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
                warnings=["partial_extraction", 42],
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            SemanticMetadata(
                semantic_metadata_id="sem_001",
                source_observation_ids=["obs_001", 42],
                metadata_type="topic",
                value={"label": "source preservation"},
                confidence=0.8,
                extractor_run_id="run_001",
                requires_review=True,
            ).to_dict()

    def test_resource_contract_hashes_are_canonical(self) -> None:
        left = stable_resource_contract_hash("Observation", {"b": 2, "a": 1})
        right = stable_resource_contract_hash("Observation", {"a": 1, "b": 2})
        self.assertEqual(left, right)
        self.assertTrue(left.startswith("sha256:"))

        self.assertEqual(
            stable_resource_contract_id("obs", "Observation", {"b": 2, "a": 1}),
            stable_resource_contract_id("obs", "Observation", {"a": 1, "b": 2}),
        )

    def test_resource_contract_ids_are_stable_from_identity_payloads(self) -> None:
        created_at = "2026-06-17T10:00:00+00:00"
        later_registered_at = "2026-06-17T11:00:00+00:00"
        permission_scope = PermissionScope.project("project_formowl")
        source_ref = SourceRef(
            source_system="local",
            source_type="file",
            source_id="meeting-notes.txt",
        )
        storage_backend_id = stable_storage_backend_id(
            backend_type="local_fs",
            workspace_scope="workspace_formowl",
            root_prefix="formowl://storage/local",
        )
        asset_id = stable_asset_id(
            storage_backend_id=storage_backend_id,
            object_uri="formowl://asset/source/meeting-notes.txt",
            content_hash="sha256:abc123",
            workspace_id="workspace_formowl",
            source_ref=source_ref,
        )

        first_asset = Asset(
            asset_id=asset_id,
            storage_backend_id=storage_backend_id,
            object_uri="formowl://asset/source/meeting-notes.txt",
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
        )
        second_asset = Asset(
            asset_id=stable_asset_id(
                storage_backend_id=storage_backend_id,
                object_uri="formowl://asset/source/meeting-notes.txt",
                content_hash="sha256:abc123",
                workspace_id="workspace_formowl",
                source_ref=source_ref,
            ),
            storage_backend_id=storage_backend_id,
            object_uri="formowl://asset/source/meeting-notes.txt",
            content_hash="sha256:abc123",
            file_size=42,
            mime_type="text/plain",
            created_at=created_at,
            registered_at=later_registered_at,
            owner_user_id="user_yifan",
            workspace_id="workspace_formowl",
            permission_scope=permission_scope,
            lifecycle_state="active",
            source_ref=source_ref,
        )

        self.assertEqual(first_asset.asset_id, second_asset.asset_id)
        self.assertTrue(first_asset.asset_id.startswith("asset_"))

        job_id = stable_ingestion_job_id(
            asset_id=asset_id,
            requested_by="user_yifan",
            workspace_id="workspace_formowl",
            extractor_names=["plain_text_extractor"],
            config_hash="sha256:config",
        )
        self.assertTrue(job_id.startswith("job_"))

        first_run_id = stable_extractor_run_id(
            asset_id=asset_id,
            extractor_name="plain_text_extractor",
            extractor_version="0.1.0",
            extractor_type="document_structure",
            input_hash="sha256:abc123",
            config_hash="sha256:config",
        )
        second_run_id = stable_extractor_run_id(
            asset_id=asset_id,
            extractor_name="plain_text_extractor",
            extractor_version="0.1.0",
            extractor_type="document_structure",
            input_hash="sha256:abc123",
            config_hash="sha256:config",
        )
        changed_config_run_id = stable_extractor_run_id(
            asset_id=asset_id,
            extractor_name="plain_text_extractor",
            extractor_version="0.1.0",
            extractor_type="document_structure",
            input_hash="sha256:abc123",
            config_hash="sha256:changed-config",
        )
        self.assertEqual(first_run_id, second_run_id)
        self.assertNotEqual(first_run_id, changed_config_run_id)

        first_observation_id = stable_observation_id(
            asset_id=asset_id,
            extractor_run_id=first_run_id,
            observation_type="paragraph",
            modality="text",
            text="A source-preserving note.",
            location={"line_end": 1, "line_start": 1},
        )
        second_observation_id = stable_observation_id(
            asset_id=asset_id,
            extractor_run_id=first_run_id,
            observation_type="paragraph",
            modality="text",
            text="A source-preserving note.",
            location={"line_start": 1, "line_end": 1},
        )
        self.assertEqual(first_observation_id, second_observation_id)
        self.assertTrue(first_observation_id.startswith("obs_"))

        self.assertEqual(
            stable_semantic_metadata_id(
                source_observation_ids=[first_observation_id],
                metadata_type="topic",
                value={"label": "source preservation"},
                extractor_run_id=first_run_id,
            ),
            stable_semantic_metadata_id(
                source_observation_ids=[first_observation_id],
                metadata_type="topic",
                value={"label": "source preservation"},
                extractor_run_id=first_run_id,
            ),
        )

        self.assertEqual(
            stable_asset_metadata_hash(
                asset_id=asset_id,
                metadata_type="technical",
                metadata={"line_count": 2, "mime_type": "text/plain"},
                extractor_run_id=first_run_id,
            ),
            stable_asset_metadata_hash(
                asset_id=asset_id,
                metadata_type="technical",
                metadata={"mime_type": "text/plain", "line_count": 2},
                extractor_run_id=first_run_id,
            ),
        )


if __name__ == "__main__":
    unittest.main()
