from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors import FixtureOcrExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)


class OcrExtractionTests(unittest.TestCase):
    def test_ocr_fixture_creates_text_observations_with_page_and_bbox_locators(self) -> None:
        temp_dir = _paths.fresh_test_dir("ocr-extraction")
        source_path = temp_dir / "incoming" / "whiteboard.png"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(
            "1|10,20,200,60|Launch checklist\n" "1|10,80,220,120|Verify provenance\n",
            encoding="utf-8",
        )
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        object_store = FileObjectStore(registry)
        source_ref = SourceRef(
            source_system="local",
            source_type="file",
            source_id="whiteboard.png",
        )
        asset = register_asset_from_local_file(
            source_path,
            object_store=object_store,
            asset_store=AssetStore(temp_dir),
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=source_ref,
            mime_type="image/png",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )

        stored = run_extractor(
            asset=asset,
            object_store=object_store,
            extractor_run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            adapter=FixtureOcrExtractor(),
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(stored.extractor_run.status, "succeeded")
        self.assertEqual(stored.extractor_run.extractor_type, "ocr")
        self.assertEqual(
            [item.text for item in stored.observations],
            [
                "Launch checklist",
                "Verify provenance",
            ],
        )
        self.assertEqual(stored.observations[0].location["page"], 1)
        self.assertEqual(stored.observations[0].location["bbox"], [10, 20, 200, 60])
        self.assertEqual(stored.observations[1].payload["source_ref"], source_ref.to_dict())
        self.assertNotIn(str(source_path), json.dumps(stored.observations[0].to_dict()))

        persisted = ObservationStore(temp_dir).get(stored.observations[0].observation_id)
        self.assertEqual(persisted.to_dict(), stored.observations[0].to_dict())


if __name__ == "__main__":
    unittest.main()
