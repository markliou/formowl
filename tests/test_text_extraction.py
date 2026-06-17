from __future__ import annotations

from pathlib import Path
import unittest

import _paths  # noqa: F401
from formowl_contract import Asset, PermissionScope, SourceRef, stable_asset_id
from formowl_ingestion.extraction import (
    ExtractorAdapter,
    extraction_config_hash,
    run_extractor,
)
from formowl_ingestion.extractors import PlainTextObservationExtractor
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)


class TextExtractionTests(unittest.TestCase):
    def test_plain_text_adapter_declares_extractor_metadata(self) -> None:
        adapter = PlainTextObservationExtractor()

        self.assertIsInstance(adapter, ExtractorAdapter)
        self.assertEqual(adapter.name(), "plain_text_extractor")
        self.assertEqual(adapter.version(), "0.1.0")
        self.assertEqual(adapter.extractor_type(), "document_structure")
        self.assertIn("text/plain", adapter.supported_mime_types())
        self.assertIn("text/markdown", adapter.supported_mime_types())
        self.assertEqual(
            extraction_config_hash({"b": 2, "a": 1}),
            extraction_config_hash({"a": 1, "b": 2}),
        )

    def test_markdown_asset_produces_line_range_observations_with_source_refs(self) -> None:
        context = _TextExtractionContext.create(
            "text-extraction-markdown",
            filename="meeting-notes.md",
            mime_type="text/markdown",
            content="# Decision Notes\n\nUse observations first.\nKeep graph governance separate.\n",
        )

        result = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=PlainTextObservationExtractor(),
            config={"mode": "block"},
            started_at="2026-06-17T10:00:00+00:00",
            completed_at="2026-06-17T10:00:00+00:00",
        )

        self.assertEqual(result.extractor_run.status, "succeeded")
        self.assertEqual(result.extractor_run.extractor_run_id[:4], "run_")
        self.assertEqual(result.extractor_run.input_hash, context.asset.content_hash)
        self.assertEqual(result.extractor_run.extractor_name, "plain_text_extractor")
        self.assertEqual(result.extractor_run.extractor_version, "0.1.0")
        self.assertEqual(result.extractor_run.extractor_type, "document_structure")
        self.assertEqual(len(result.observations), 2)

        heading, paragraph = result.observations
        self.assertEqual(heading.observation_type, "heading")
        self.assertEqual(heading.text, "# Decision Notes")
        self.assertEqual(heading.location, {"line_start": 1, "line_end": 1})
        self.assertEqual(paragraph.observation_type, "paragraph")
        self.assertEqual(paragraph.text, "Use observations first.\nKeep graph governance separate.")
        self.assertEqual(paragraph.location, {"line_start": 3, "line_end": 4})

        for observation in result.observations:
            self.assertEqual(observation.asset_id, context.asset.asset_id)
            self.assertEqual(observation.extractor_run_id, result.extractor_run.extractor_run_id)
            self.assertEqual(observation.modality, "text")
            self.assertEqual(observation.confidence, 1.0)
            self.assertEqual(observation.payload["source_ref"], context.source_ref.to_dict())
            self.assertNotIn("object_path", observation.to_dict())
            self.assertNotIn("object_path", observation.payload)

        self.assertEqual(
            context.run_store.get(result.extractor_run.extractor_run_id).to_dict(),
            result.extractor_run.to_dict(),
        )
        restarted_observation_store = ObservationStore(context.temp_dir)
        self.assertEqual(
            _sort_observations([item.to_dict() for item in restarted_observation_store.list()]),
            _sort_observations([item.to_dict() for item in result.observations]),
        )

    def test_text_extraction_writes_only_observation_records(self) -> None:
        context = _TextExtractionContext.create(
            "text-extraction-observations-only",
            filename="source.txt",
            mime_type="text/plain",
            content="Resource extraction stops at observations.\n",
        )

        result = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=PlainTextObservationExtractor(),
            started_at="2026-06-17T10:00:00+00:00",
            completed_at="2026-06-17T10:00:00+00:00",
        )

        self.assertEqual(len(result.observations), 1)
        self.assertEqual(context.run_store.list(), [result.extractor_run])
        self.assertEqual(
            [item.to_dict() for item in context.observation_store.list()],
            [item.to_dict() for item in result.observations],
        )
        self.assertFalse(hasattr(result, "semantic_metadata"))
        self.assertFalse(hasattr(result, "candidate_atoms"))
        self.assertFalse(hasattr(result, "canonical_atoms"))

    def test_changed_config_or_version_creates_new_run_without_replacing_old_runs(self) -> None:
        context = _TextExtractionContext.create(
            "text-extraction-rerun",
            filename="source.txt",
            mime_type="text/plain",
            content="First block.\n\nSecond block.\n",
        )

        first = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=PlainTextObservationExtractor(),
            config={"mode": "block"},
            started_at="2026-06-17T10:00:00+00:00",
            completed_at="2026-06-17T10:00:00+00:00",
        )
        changed_config = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=PlainTextObservationExtractor(),
            config={"mode": "block", "line_window": 1},
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )
        changed_version = run_extractor(
            asset=context.asset,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=PlainTextObservationExtractor(version="0.1.1"),
            config={"mode": "block", "line_window": 1},
            started_at="2026-06-17T10:02:00+00:00",
            completed_at="2026-06-17T10:02:00+00:00",
        )

        run_ids = [run.extractor_run_id for run in context.run_store.list()]
        self.assertEqual(
            set(run_ids),
            {
                first.extractor_run.extractor_run_id,
                changed_config.extractor_run.extractor_run_id,
                changed_version.extractor_run.extractor_run_id,
            },
        )
        self.assertEqual(len(set(run_ids)), 3)
        self.assertEqual(len(context.observation_store.list()), 6)
        for stored_run in context.run_store.list():
            self.assertEqual(stored_run.status, "succeeded")


class _TextExtractionContext:
    def __init__(
        self,
        *,
        temp_dir: Path,
        object_store: FileObjectStore,
        run_store: ExtractorRunStore,
        observation_store: ObservationStore,
        asset: Asset,
        source_ref: SourceRef,
    ) -> None:
        self.temp_dir = temp_dir
        self.object_store = object_store
        self.run_store = run_store
        self.observation_store = observation_store
        self.asset = asset
        self.source_ref = source_ref

    @classmethod
    def create(
        cls,
        test_dir_name: str,
        *,
        filename: str,
        mime_type: str,
        content: str,
    ) -> "_TextExtractionContext":
        temp_dir = _paths.fresh_test_dir(test_dir_name)
        source_path = temp_dir / filename
        source_path.write_text(content, encoding="utf-8")

        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-store-root",
            workspace_scope="workspace_formowl",
            display_name="Local test backend",
        )
        object_store = FileObjectStore(registry)
        stored = object_store.copy_local_file(
            source_path,
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            original_filename=filename,
        )
        permission_scope = PermissionScope.project("project_formowl")
        source_ref = SourceRef(
            source_system="local",
            source_type="file",
            source_id=filename,
            source_key=filename,
        )
        asset = Asset(
            asset_id=stable_asset_id(
                storage_backend_id=stored.storage_backend_id,
                object_uri=stored.object_uri,
                content_hash=stored.content_hash,
                workspace_id=stored.workspace_id,
                source_ref=source_ref,
            ),
            storage_backend_id=stored.storage_backend_id,
            object_uri=stored.object_uri,
            content_hash=stored.content_hash,
            file_size=stored.file_size,
            mime_type=mime_type,
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
            owner_user_id="user_yifan",
            workspace_id=stored.workspace_id,
            permission_scope=permission_scope,
            lifecycle_state="active",
            source_ref=source_ref,
            original_filename=filename,
        )
        AssetStore(temp_dir).create(asset)
        return cls(
            temp_dir=temp_dir,
            object_store=object_store,
            run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            asset=asset,
            source_ref=source_ref,
        )


def _sort_observations(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        records,
        key=lambda item: int(item["location"]["line_start"]),  # type: ignore[index]
    )


if __name__ == "__main__":
    unittest.main()
