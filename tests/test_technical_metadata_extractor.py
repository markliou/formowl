from __future__ import annotations

from dataclasses import replace
import json
import unittest

import _paths  # noqa: F401
from formowl_contract import PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors import FileTechnicalMetadataExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)


class TechnicalMetadataExtractorTests(unittest.TestCase):
    def test_file_technical_metadata_extractor_creates_metadata_observation(self) -> None:
        temp_dir = _paths.fresh_test_dir("technical-metadata-extractor")
        source_path = temp_dir / "incoming" / "archive.bin"
        source_path.parent.mkdir(parents=True)
        source_path.write_bytes(b"\x00\x01technical metadata")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        object_store = FileObjectStore(registry)
        asset = register_asset_from_local_file(
            source_path,
            object_store=object_store,
            asset_store=AssetStore(temp_dir),
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=SourceRef(
                source_system="local",
                source_type="file",
                source_id="archive.bin",
            ),
            mime_type="application/octet-stream",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )

        stored = run_extractor(
            asset=asset,
            object_store=object_store,
            extractor_run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            adapter=FileTechnicalMetadataExtractor(),
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(stored.extractor_run.status, "succeeded")
        self.assertEqual(stored.extractor_run.extractor_type, "technical_metadata")
        self.assertEqual(len(stored.observations), 1)
        observation = stored.observations[0]
        metadata = observation.payload["metadata"]
        self.assertEqual(observation.observation_type, "technical_metadata")
        self.assertEqual(observation.modality, "file")
        self.assertEqual(metadata["mime_type"], "application/octet-stream")
        self.assertEqual(metadata["file_size"], source_path.stat().st_size)
        self.assertEqual(metadata["content_hash"], asset.content_hash)
        self.assertEqual(metadata["object_uri"], asset.object_uri)
        self.assertEqual(metadata["original_filename"], "archive.bin")
        self.assertEqual(observation.extracted_value, metadata)
        self.assertNotIn(str(source_path), json.dumps(observation.to_dict(), sort_keys=True))

        restarted_observation = ObservationStore(temp_dir).get(observation.observation_id)
        self.assertEqual(restarted_observation.to_dict(), observation.to_dict())

    def test_file_technical_metadata_warns_on_asset_file_size_mismatch(self) -> None:
        temp_dir = _paths.fresh_test_dir("technical-metadata-size-mismatch")
        source_path = temp_dir / "incoming" / "archive.bin"
        source_path.parent.mkdir(parents=True)
        source_path.write_bytes(b"technical metadata")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        object_store = FileObjectStore(registry)
        asset = register_asset_from_local_file(
            source_path,
            object_store=object_store,
            asset_store=AssetStore(temp_dir),
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=SourceRef(
                source_system="local",
                source_type="file",
                source_id="archive.bin",
            ),
            mime_type="application/octet-stream",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        mismatched_asset = replace(asset, file_size=asset.file_size + 1)

        stored = run_extractor(
            asset=mismatched_asset,
            object_store=object_store,
            extractor_run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            adapter=FileTechnicalMetadataExtractor(),
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(stored.extractor_run.status, "succeeded")
        self.assertEqual(stored.extractor_run.warnings, ["asset_file_size_mismatch"])
        metadata = stored.observations[0].payload["metadata"]
        self.assertEqual(metadata["file_size"], asset.file_size + 1)
        self.assertEqual(metadata["actual_file_size"], asset.file_size)


if __name__ == "__main__":
    unittest.main()
