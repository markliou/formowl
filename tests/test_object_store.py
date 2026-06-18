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

    def test_malformed_object_uris_do_not_resolve_or_echo_raw_paths(self) -> None:
        temp_dir = _paths.fresh_test_dir("object-store-malformed-uri")
        registry = StorageBackendRegistry(temp_dir)
        registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        store = FileObjectStore(registry)
        raw_path = str((temp_dir / "secret" / "payload.bin").resolve())
        malformed_uris = [
            raw_path,
            "file:///tmp/payload.bin",
            "formowl://object/storage_local_001/../" + ("0" * 64),
            "formowl://object/storage_local_001/workspace_formowl/not-a-sha",
            "formowl://object/storage_local_001/workspace_formowl/" + ("0" * 64) + "/extra",
        ]

        for object_uri in malformed_uris:
            with self.subTest(object_uri=object_uri):
                self.assertIsNone(store.get_object(object_uri))
                self.assertIsNone(store.resolve_object_path(object_uri))
                self.assertFalse(store.verify_object(object_uri))
                envelope = store.object_mcp_envelope(object_uri)
                self.assertEqual(envelope["status"], "not_found")
                self.assertNotIn("object_uri", envelope["data"])
                self.assertNotIn(raw_path, json.dumps(envelope, sort_keys=True))

    def test_not_found_envelope_keeps_safe_formowl_locator_for_missing_object(self) -> None:
        temp_dir = _paths.fresh_test_dir("object-store-safe-not-found")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        store = FileObjectStore(registry)
        missing_uri = f"formowl://object/{backend.storage_backend_id}/workspace_formowl/{'0' * 64}"

        envelope = store.object_mcp_envelope(missing_uri)

        self.assertEqual(envelope["status"], "not_found")
        self.assertEqual(envelope["data"], {"object_uri": missing_uri})
        self.assertIsNone(store.resolve_object_path(missing_uri))
        self.assertFalse(store.verify_object(missing_uri))

    def test_unsafe_object_locator_segments_fail_before_payload_write(self) -> None:
        temp_dir = _paths.fresh_test_dir("object-store-unsafe-segments")
        source_path = temp_dir / "incoming" / "note.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("original bytes\n", encoding="utf-8")

        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        store = FileObjectStore(registry)
        unsafe_cases = [
            {"storage_backend_id": "../escape", "workspace_id": "workspace_formowl"},
            {"storage_backend_id": "..", "workspace_id": "workspace_formowl"},
            {"storage_backend_id": backend.storage_backend_id, "workspace_id": "../escape"},
            {"storage_backend_id": backend.storage_backend_id, "workspace_id": ".."},
        ]

        for kwargs in unsafe_cases:
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    store.copy_local_file(source_path, **kwargs)

        self.assertEqual(list((temp_dir / "object-root").glob("objects/**/*")), [])

    def test_rejects_path_like_original_filename_before_payload_write(self) -> None:
        temp_dir = _paths.fresh_test_dir("object-store-original-filename-path")
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
                original_filename=str(source_path.resolve()),
            )

        self.assertEqual(list((temp_dir / "object-root").glob("objects/**/payload.bin")), [])
        self.assertEqual(list((temp_dir / "object-root").glob("objects/**/metadata.json")), [])


if __name__ == "__main__":
    unittest.main()
