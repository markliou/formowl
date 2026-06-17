from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_core import sha256_prefixed
from formowl_ingestion.storage import FileObjectStore, StorageBackendRegistry


class FileObjectStoreTests(unittest.TestCase):
    def test_copies_local_file_to_formowl_object_locator_and_verifies_hash(self) -> None:
        temp_dir = _paths.fresh_test_dir("object-store-copy")
        source_path = temp_dir / "incoming" / "note.txt"
        source_path.parent.mkdir(parents=True)
        payload = b"source-preserving object bytes\n"
        source_path.write_bytes(payload)

        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        store = FileObjectStore(registry)

        stored = store.copy_local_file(
            source_path,
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
            expected_content_hash=sha256_prefixed(payload),
        )

        self.assertTrue(stored.object_uri.startswith("formowl://object/"))
        self.assertEqual(stored.content_hash, sha256_prefixed(payload))
        self.assertEqual(stored.file_size, len(payload))
        self.assertTrue(store.verify_object(stored.object_uri))
        self.assertEqual(store.get_object(stored.object_uri), stored)

        public_json = json.dumps(
            {
                "object": stored.to_dict(),
                "envelope": store.object_mcp_envelope(stored.object_uri),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertIn("formowl://object/", public_json)
        self.assertNotIn(str(source_path), public_json)
        self.assertNotIn(str((temp_dir / "object-root").resolve()), public_json)

    def test_verify_object_detects_hash_mismatch_after_stored_bytes_change(self) -> None:
        temp_dir = _paths.fresh_test_dir("object-store-hash-mismatch")
        source_path = temp_dir / "incoming" / "note.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original bytes\n", encoding="utf-8")

        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        store = FileObjectStore(registry)
        stored = store.copy_local_file(
            source_path,
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
        )

        payload_path = store.resolve_object_path(stored.object_uri)
        self.assertIsNotNone(payload_path)
        payload_path.write_text("changed bytes\n", encoding="utf-8")

        self.assertFalse(store.verify_object(stored.object_uri))

    def test_rejects_expected_hash_mismatch_before_copying(self) -> None:
        temp_dir = _paths.fresh_test_dir("object-store-expected-hash-mismatch")
        source_path = temp_dir / "incoming" / "note.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original bytes\n", encoding="utf-8")

        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        store = FileObjectStore(registry)

        with self.assertRaises(ValueError):
            store.copy_local_file(
                source_path,
                storage_backend_id=backend.storage_backend_id,
                workspace_id="workspace_formowl",
                expected_content_hash="sha256:not-the-real-hash",
            )

        self.assertEqual(list((temp_dir / "object-root").glob("objects/**/*")), [])


if __name__ == "__main__":
    unittest.main()
