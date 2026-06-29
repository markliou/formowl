from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors import FixtureAudioTranscriptExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)


class AudioExtractionTests(unittest.TestCase):
    def test_audio_fixture_creates_transcript_segments_with_time_locators(self) -> None:
        temp_dir = _paths.fresh_test_dir("audio-extraction")
        source_path = temp_dir / "incoming" / "meeting.wav"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(
            "0.0|4.5|speaker_01|We should preserve source references.\n"
            "4.5|8.0|speaker_02|Agreed, observations are intermediate records.\n",
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
            source_id="meeting.wav",
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
            mime_type="audio/wav",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )

        stored = run_extractor(
            asset=asset,
            object_store=object_store,
            extractor_run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            adapter=FixtureAudioTranscriptExtractor(),
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(stored.extractor_run.status, "succeeded")
        self.assertEqual(stored.extractor_run.extractor_type, "asr")
        self.assertEqual(len(stored.observations), 2)
        first = stored.observations[0]
        self.assertEqual(first.observation_type, "transcript_segment")
        self.assertEqual(first.modality, "audio")
        self.assertEqual(first.location["start_sec"], 0.0)
        self.assertEqual(first.location["end_sec"], 4.5)
        self.assertEqual(first.location["speaker"], "speaker_01")
        self.assertEqual(first.payload["source_ref"], source_ref.to_dict())
        self.assertNotIn(str(source_path), json.dumps(first.to_dict(), sort_keys=True))

        persisted = ObservationStore(temp_dir).get(first.observation_id)
        self.assertEqual(persisted.to_dict(), first.to_dict())


if __name__ == "__main__":
    unittest.main()
