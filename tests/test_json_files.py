from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import _paths  # noqa: F401

from formowl_core import json_files


class JsonFilesTests(unittest.TestCase):
    def test_write_json_atomic_rejects_predictable_symlink_without_touching_victim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-json-atomic-") as value:
            root = Path(value)
            output_directory = root / "records"
            output_directory.mkdir()
            destination = output_directory / "record.json"
            destination.write_bytes(b"prior-destination")
            victim = root / "external-victim.json"
            victim.write_bytes(b"external-victim")
            temporary = destination.with_suffix(f"{destination.suffix}.tmp")
            temporary.symlink_to(victim)

            with self.assertRaises(FileExistsError):
                json_files.write_json_atomic(destination, {"status": "new"})

            self.assertEqual(destination.read_bytes(), b"prior-destination")
            self.assertEqual(victim.read_bytes(), b"external-victim")
            self.assertTrue(temporary.is_symlink())
            self.assertEqual(temporary.resolve(), victim)

    def test_write_json_atomic_rejects_non_regular_predictable_temp_targets(self) -> None:
        for target_kind in ("directory", "fifo"):
            with (
                self.subTest(target_kind=target_kind),
                tempfile.TemporaryDirectory(prefix="formowl-json-atomic-nonregular-") as value,
            ):
                root = Path(value)
                destination = root / "record.json"
                destination.write_bytes(b"prior-destination")
                temporary = destination.with_suffix(f"{destination.suffix}.tmp")
                if target_kind == "directory":
                    temporary.mkdir()
                else:
                    os.mkfifo(temporary)

                with self.assertRaises(FileExistsError):
                    json_files.write_json_atomic(destination, {"status": "new"})

                self.assertEqual(destination.read_bytes(), b"prior-destination")
                self.assertTrue(temporary.exists())

    def test_write_json_atomic_cleans_owned_temp_and_preserves_prior_on_replace_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-json-atomic-failure-") as value:
            root = Path(value)
            destination = root / "record.json"
            destination.write_bytes(b"prior-destination")
            temporary = destination.with_suffix(f"{destination.suffix}.tmp")

            with (
                mock.patch.object(json_files.os, "replace", side_effect=OSError("replace failed")),
                self.assertRaises(OSError),
            ):
                json_files.write_json_atomic(destination, {"status": "new"})

            self.assertEqual(destination.read_bytes(), b"prior-destination")
            self.assertFalse(temporary.exists())

    def test_write_json_atomic_replaces_with_canonical_json_and_fsyncs_file_and_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-json-atomic-success-") as value:
            destination = Path(value) / "record.json"
            with mock.patch.object(json_files.os, "fsync", wraps=os.fsync) as fsync:
                json_files.write_json_atomic(destination, {"b": 2, "a": 1})

            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"a": 1, "b": 2})
            self.assertEqual(fsync.call_count, 2)
            self.assertFalse(destination.with_suffix(f"{destination.suffix}.tmp").exists())

    def test_write_json_atomic_restores_prior_destination_when_directory_fsync_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="formowl-json-atomic-fsync-failure-") as value:
            root = Path(value)
            destination = root / "record.json"
            destination.write_bytes(b"prior-destination")
            real_fsync = os.fsync
            call_count = 0

            def fail_post_replace_directory_fsync(descriptor: int) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 3:
                    raise OSError("directory fsync failed")
                real_fsync(descriptor)

            with (
                mock.patch.object(
                    json_files.os,
                    "fsync",
                    side_effect=fail_post_replace_directory_fsync,
                ),
                self.assertRaises(OSError),
            ):
                json_files.write_json_atomic(destination, {"status": "new"})

            self.assertEqual(call_count, 4)
            self.assertEqual(destination.read_bytes(), b"prior-destination")
            self.assertFalse(destination.with_suffix(f"{destination.suffix}.tmp").exists())
            self.assertEqual([path.name for path in root.iterdir()], [destination.name])


if __name__ == "__main__":
    unittest.main()
