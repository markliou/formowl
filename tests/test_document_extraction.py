from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors import FixtureDocumentParserExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)


class DocumentExtractionTests(unittest.TestCase):
    def test_document_fixture_creates_paragraph_table_and_page_locators(self) -> None:
        temp_dir = _paths.fresh_test_dir("document-extraction")
        source_path = temp_dir / "incoming" / "project-brief.pdf"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(
            "# Project Brief\n\n"
            "The first page introduces the project.\n\n"
            "| Risk | Owner |\n| Scope creep | PM |\n"
            "\f"
            "Follow-up paragraph on page two.\n",
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
            source_id="project-brief.pdf",
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
            mime_type="application/pdf",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )

        stored = run_extractor(
            asset=asset,
            object_store=object_store,
            extractor_run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            adapter=FixtureDocumentParserExtractor(),
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(stored.extractor_run.status, "succeeded")
        self.assertEqual(stored.extractor_run.extractor_type, "document_structure")
        by_type = _observations_by_type(stored.observations)
        self.assertEqual(by_type["heading"][0].location["page"], 1)
        self.assertEqual(by_type["paragraph"][0].location["paragraph_index"], 1)
        self.assertEqual(by_type["table"][0].location["table_index"], 1)
        self.assertEqual(by_type["table"][0].payload["rows"][1], ["Scope creep", "PM"])
        self.assertEqual(stored.observations[-1].location["page"], 2)
        self.assertEqual(stored.observations[-1].location["block_index"], 1)
        for observation in stored.observations:
            self.assertEqual(observation.asset_id, asset.asset_id)
            self.assertEqual(observation.payload["source_ref"], source_ref.to_dict())
            self.assertNotIn(str(source_path), json.dumps(observation.to_dict(), sort_keys=True))

        persisted = ObservationStore(temp_dir).get(by_type["table"][0].observation_id)
        self.assertEqual(persisted.to_dict(), by_type["table"][0].to_dict())


def _observations_by_type(observations):
    by_type = {}
    for observation in observations:
        by_type.setdefault(observation.observation_type, []).append(observation)
    return by_type


if __name__ == "__main__":
    unittest.main()
