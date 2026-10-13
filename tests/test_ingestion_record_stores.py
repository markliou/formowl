from __future__ import annotations

from dataclasses import replace
import errno
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

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
from formowl_ingestion.storage import records


class ObservationLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _paths.fresh_test_dir("observation-layout")
        self.store = ObservationStore(self.root)
        self.collection = self.root / "ingestion" / "observations"

    @staticmethod
    def observation(record_id: str, text: str = "Synthetic paragraph.") -> Observation:
        return Observation(
            observation_id=record_id, asset_id="asset_layout", extractor_run_id="run_layout",
            observation_type="paragraph", modality="text", text=text,
            location={"line_start": 1, "line_end": 1}, confidence=1.0,
            permission_scope=PermissionScope.project("project_layout"),
            created_at="2026-06-17T10:00:00+00:00",
        )

    def shard_path(self, record_id: str) -> Path:
        bucket = hashlib.sha256(record_id.encode("utf-8")).hexdigest()[:2]
        return self.collection / "_shards" / bucket / f"{record_id}.json"

    def test_new_records_and_legacy_updates_never_need_a_new_flat_file_entry(self) -> None:
        legacy = self.observation("obs_legacy")
        legacy_path = self.collection / "obs_legacy.json"
        records._write_json(legacy_path, legacy.to_dict())
        legacy_bytes = legacy_path.read_bytes()
        open_path = Path.open

        def no_flat_entry(path, mode="r", *args, **kwargs):
            if (path.parent == self.collection and any(flag in mode for flag in "wax")
                    and not path.exists()):
                raise OSError(errno.ENOSPC, "synthetic flat directory full")
            return open_path(path, mode, *args, **kwargs)

        with patch.object(Path, "open", no_flat_entry):
            for record_id in ("obs_alpha", "obs_beta", "obs_gamma"):
                observation = self.observation(record_id)
                self.store.create(observation)
                self.assertTrue(self.shard_path(record_id).is_file())
                self.assertEqual(self.store.get(record_id).to_dict(), observation.to_dict())
            self.store.create(legacy)
            self.assertEqual(legacy_path.read_bytes(), legacy_bytes)
            updated = replace(legacy, text="Changed synthetic paragraph.")
            self.store.create(updated)
            self.assertEqual(records._read_json(legacy_path), updated.to_dict())
        self.assertEqual(list(self.collection.glob("*.json")), [legacy_path])
        self.assertFalse(self.shard_path(legacy.observation_id).exists())
        self.assertEqual(list(self.collection.rglob("*.tmp")), [])

    def test_explicit_flat_export_layout_preserves_existing_record_locations(self) -> None:
        export = ObservationStore(self.root, write_layout="flat")
        flat, sharded = self.observation("obs_flat"), self.observation("obs_sharded")
        export.create(flat)
        flat_path = self.collection / "obs_flat.json"
        self.assertTrue(flat_path.is_file())
        self.assertFalse((self.collection / "_shards").exists())
        self.store.create(sharded)
        self.assertTrue(self.shard_path(sharded.observation_id).is_file())
        for store in (export, self.store):
            store.create(flat)
            store.create(sharded)
            self.assertEqual([item.to_dict() for item in store.list()],
                             [flat.to_dict(), sharded.to_dict()])
        self.assertFalse(self.shard_path(flat.observation_id).exists())
        self.assertFalse((self.collection / "obs_sharded.json").exists())
        with self.assertRaisesRegex(ValueError, "write layout"):
            ObservationStore(self.root / "invalid", write_layout="unknown")
        self.assertFalse((self.root / "invalid").exists())

    def test_mixed_layout_restart_preserves_records_and_id_order(self) -> None:
        legacy = self.observation("obs_z_legacy")
        legacy_path = self.collection / f"{legacy.observation_id}.json"
        records._write_json(legacy_path, legacy.to_dict())
        before = legacy_path.read_bytes()
        new = self.observation("obs_a_new")
        self.store.create(new)
        restarted = ObservationStore(self.root)
        self.assertEqual(restarted.get(legacy.observation_id).to_dict(), legacy.to_dict())
        self.assertEqual(restarted.get(new.observation_id).to_dict(), new.to_dict())
        self.assertEqual([item.to_dict() for item in restarted.list()], [new.to_dict(), legacy.to_dict()])
        self.assertEqual(legacy_path.read_bytes(), before)
        self.assertFalse(self.shard_path(legacy.observation_id).exists())
        self.assertFalse((self.collection / f"{new.observation_id}.json").exists())

    def test_keyed_reads_and_id_validation_never_scan_or_write(self) -> None:
        legacy, sharded = self.observation("obs_legacy"), self.observation("obs_sharded")
        records._write_json(self.collection / "obs_legacy.json", legacy.to_dict())
        records._write_json(self.shard_path(sharded.observation_id), sharded.to_dict())
        empty = ObservationStore(self.root / "empty")
        with (
            patch.object(Path, "glob", side_effect=AssertionError("enumeration")),
            patch.object(Path, "rglob", side_effect=AssertionError("enumeration")),
            patch.object(Path, "iterdir", side_effect=AssertionError("enumeration")),
            patch.object(Path, "mkdir", side_effect=AssertionError("query write")),
            patch.object(records, "_write_json", side_effect=AssertionError("query write")),
            patch.object(records, "_read_json", wraps=records._read_json) as reads,
        ):
            self.store = ObservationStore(self.root, create_directory=False)
            absent = ObservationStore(self.root / "absent", create_directory=False)
            self.assertIsNone(absent.get("obs_absent"))
            self.assertEqual(self.store.get(legacy.observation_id).to_dict(), legacy.to_dict())
            self.assertEqual(self.store.get(sharded.observation_id).to_dict(), sharded.to_dict())
            self.assertIsNone(self.store.get("obs_absent"))
            self.assertIsNone(empty.get("obs_absent"))
            self.assertEqual(reads.call_count, 2)
            self.assertEqual({call.args[0] for call in reads.call_args_list}, {
                self.collection / "obs_legacy.json", self.shard_path(sharded.observation_id),
            })
            with patch.object(Path, "stat", side_effect=AssertionError("validation I/O")):
                self.store.validate_observation_id("obs_safe")
                with self.assertRaises(ValueError):
                    self.store.validate_observation_id("../escape")
        self.assertFalse((self.root / "empty" / "ingestion" / "observations" / "_shards").exists())

    def test_updates_keep_the_existing_physical_location(self) -> None:
        for record_id, path in (
            ("obs_legacy", self.collection / "obs_legacy.json"),
            ("obs_sharded", self.shard_path("obs_sharded")),
        ):
            with self.subTest(record_id=record_id):
                records._write_json(path, self.observation(record_id).to_dict())
                updated = self.observation(record_id, "Updated synthetic paragraph.")
                self.store.create(updated)
                self.assertEqual(records._read_json(path), updated.to_dict())
                self.assertEqual(self.store.get(record_id).to_dict(), updated.to_dict())
                other = (self.shard_path(record_id) if path.parent == self.collection
                         else self.collection / f"{record_id}.json")
                self.assertFalse(other.exists())

    def test_duplicate_identity_fails_closed_without_changing_either_record(self) -> None:
        for duplicate_text in ("Synthetic paragraph.", "Conflicting synthetic paragraph."):
            with self.subTest(duplicate_text=duplicate_text):
                record_id = "obs_duplicate"
                paths = [self.collection / f"{record_id}.json", self.shard_path(record_id)]
                records._write_json(paths[0], self.observation(record_id).to_dict())
                records._write_json(paths[1], self.observation(record_id, duplicate_text).to_dict())
                before = [path.read_bytes() for path in paths]
                for action in (lambda: self.store.get(record_id), self.store.list,
                               lambda: self.store.create(self.observation(record_id))):
                    with self.assertRaisesRegex(ValueError, "duplicate record identity"):
                        action()
                self.assertEqual([path.read_bytes() for path in paths], before)

    def test_list_rejects_a_record_in_the_wrong_bucket(self) -> None:
        record_id = "obs_misplaced"
        right = self.shard_path(record_id)
        wrong_bucket = "00" if right.parent.name != "00" else "01"
        records._write_json(right.parent.parent / wrong_bucket / right.name,
                            self.observation(record_id).to_dict())
        with self.assertRaisesRegex(ValueError, "sharded record location"):
            self.store.list()


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
