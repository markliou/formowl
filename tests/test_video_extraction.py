from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors import FixtureVideoSceneExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)


class VideoExtractionTests(unittest.TestCase):
    def test_video_fixture_creates_scene_and_keyframe_observations(self) -> None:
        temp_dir = _paths.fresh_test_dir("video-extraction")
        source_path = temp_dir / "incoming" / "demo.mp4"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(
            "scene|0.0|12.5|Presenter introduces the upload workflow.\n"
            "keyframe|6.0|180|Upload task card is visible.\n"
            "scene|12.5|22.0|Presenter reviews generated observations.\n",
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
            source_id="demo.mp4",
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
            mime_type="video/mp4",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )

        stored = run_extractor(
            asset=asset,
            object_store=object_store,
            extractor_run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            adapter=FixtureVideoSceneExtractor(),
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(stored.extractor_run.status, "succeeded")
        self.assertEqual(stored.extractor_run.extractor_type, "video_scene_detection")
        self.assertEqual(
            [item.observation_type for item in stored.observations],
            [
                "video_scene",
                "keyframe",
                "video_scene",
            ],
        )
        self.assertEqual(stored.observations[0].location["start_sec"], 0.0)
        self.assertEqual(stored.observations[0].location["end_sec"], 12.5)
        self.assertEqual(stored.observations[1].location["timestamp_sec"], 6.0)
        self.assertEqual(stored.observations[1].location["frame_index"], 180)
        self.assertEqual(stored.observations[1].payload["source_ref"], source_ref.to_dict())
        self.assertNotIn(str(source_path), json.dumps(stored.observations[0].to_dict()))

        persisted = ObservationStore(temp_dir).get(stored.observations[1].observation_id)
        self.assertEqual(persisted.to_dict(), stored.observations[1].to_dict())


if __name__ == "__main__":
    unittest.main()
