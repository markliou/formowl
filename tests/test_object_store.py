from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import json
import os
from pathlib import Path
from threading import Event, current_thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_core import sha256_prefixed
from formowl_ingestion.storage import FileObjectStore, StorageBackendRegistry
from formowl_ingestion.storage.objects import _hash_file


class FileObjectStoreTests(unittest.TestCase):
    def _verification_fixture(self, name, payload=b"original bytes"):
        root = _paths.fresh_test_dir(name)
        source = root / "source.bin"
        source.write_bytes(payload)
        registry = StorageBackendRegistry(root)
        backend = registry.register_local_backend(
            root / "object-root", workspace_scope="workspace_formowl"
        )
        facts = []
        store = FileObjectStore(registry, verification_observer=facts.append)
        stored = store.copy_local_file(
            source, storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace_formowl",
        )
        return root, store, stored, store.resolve_object_path(stored.object_uri), facts

    def test_metadata_temporary_is_private_during_write_and_preserves_published_mode(self):
        for existing, mask in ((True, 0o022), (False, 0o022), (False, 0o027), (False, 0o077)):
            with self.subTest(existing=existing, umask=oct(mask)):
                root, store, stored, payload, _ = self._verification_fixture(
                    f"object-metadata-private-{existing}-{mask}",
                )
                metadata = payload.with_name("metadata.json")
                original = metadata.read_bytes()
                if existing:
                    metadata.chmod(0o640)
                else:
                    metadata.unlink()
                written, release = Event(), Event()
                opening_modes = []
                original_open, original_fdopen = Path.open, os.fdopen

                @contextmanager
                def paused_write(handle):
                    with handle:
                        opening_modes.append(os.fstat(handle.fileno()).st_mode & 0o777)

                        def write(text):
                            result = handle.write(text)
                            handle.flush()  # Observe actual staged bytes, before final chmod/replace.
                            written.set()
                            if not release.wait(5):
                                raise AssertionError("metadata writer was not released")
                            return result

                        yield SimpleNamespace(write=write, flush=handle.flush, fileno=handle.fileno)

                def paused_path_open(path, *args, **kwargs):
                    handle = original_open(path, *args, **kwargs)
                    mode = args[0] if args else kwargs.get("mode", "r")
                    if path.parent == metadata.parent and path.name.endswith(".tmp") and "x" in mode:
                        return paused_write(handle)
                    return handle

                def paused_fdopen(*args, **kwargs):
                    return paused_write(original_fdopen(*args, **kwargs))

                prior_mask = os.umask(mask)
                try:
                    with patch.object(Path, "open", paused_path_open), \
                         patch("formowl_ingestion.storage.objects.os.fdopen", paused_fdopen), \
                         patch("formowl_ingestion.storage.objects.os.umask", side_effect=AssertionError("process umask changed")), \
                         ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(
                            store.copy_local_file, root / "source.bin",
                            storage_backend_id=stored.storage_backend_id,
                            workspace_id=stored.workspace_id, original_filename="updated.txt",
                        )
                        try:
                            self.assertTrue(written.wait(5), "metadata write was not reached")
                            staged = list(payload.parent.glob(".metadata.json.*.tmp"))
                            self.assertEqual(len(staged), 1)
                            staged_mode = staged[0].stat().st_mode & 0o777
                            self.assertIn(b"updated.txt", staged[0].read_bytes())
                            if existing:
                                self.assertEqual(metadata.read_bytes(), original)
                            else:
                                self.assertFalse(metadata.exists())
                        finally:
                            release.set()
                        updated = future.result(timeout=5)
                finally:
                    os.umask(prior_mask)
                self.assertEqual(opening_modes, [0o600])
                self.assertEqual(staged_mode, 0o600)
                self.assertEqual(metadata.stat().st_mode & 0o777, 0o640 if existing else 0o666 & ~mask)
                self.assertEqual(store.get_object(stored.object_uri), updated)
                self.assertTrue(store.verify_object(stored.object_uri, stored.content_hash))
                self.assertEqual({p.name for p in payload.parent.iterdir()}, {"payload.bin", "metadata.json"})

    def test_metadata_enospc_preserves_previous_record_and_cleans_partial_write(self):
        for existing in (True, False):
            with self.subTest(existing=existing):
                root, store, stored, payload, facts = self._verification_fixture(
                    f"object-metadata-enospc-{existing}",
                )
                metadata = payload.with_name("metadata.json")
                original = metadata.read_bytes()
                if not existing:
                    metadata.unlink()
                original_fdopen = os.fdopen

                @contextmanager
                def failing_write(handle):
                    with handle:
                        def write(text):
                            handle.write(text[:len(text) // 2])
                            handle.flush()  # Partial bytes really reach the filesystem.
                            raise OSError(errno.ENOSPC, "synthetic metadata write exhausted space")
                        yield SimpleNamespace(write=write, flush=handle.flush, fileno=handle.fileno)

                def open_with_enospc(*args, **kwargs):
                    return failing_write(original_fdopen(*args, **kwargs))

                with patch("formowl_ingestion.storage.objects.os.fdopen", open_with_enospc):
                    with self.assertRaises(OSError) as error:
                        store.copy_local_file(root / "source.bin", storage_backend_id=stored.storage_backend_id,
                                              workspace_id=stored.workspace_id, original_filename="updated.txt")
                self.assertEqual(error.exception.errno, errno.ENOSPC)
                self.assertEqual(payload.read_bytes(), b"original bytes")
                if existing:
                    self.assertEqual(metadata.read_bytes(), original)
                    self.assertTrue(store.verify_object(stored.object_uri, stored.content_hash))
                    self.assertEqual(store.get_object(stored.object_uri), stored)
                else:
                    self.assertFalse(metadata.exists())
                    self.assertIsNone(store.get_object(stored.object_uri))
                    self.assertFalse(store.verify_object(stored.object_uri))
                    self.assertEqual(facts[-1]["reason_code"], "metadata_unavailable")
                self.assertEqual({path.name for path in payload.parent.iterdir()},
                                 {"payload.bin", "metadata.json"} if existing else {"payload.bin"})

    def test_metadata_recopy_remains_verifiable_while_writer_is_open(self):
        root, store, stored, payload, facts = self._verification_fixture("object-metadata-reader-writer")
        opened, release = Event(), Event()
        original_fdopen = os.fdopen

        def paused_open(*args, **kwargs):
            handle = original_fdopen(*args, **kwargs)
            opened.set()
            if not release.wait(5):
                handle.close()
                raise AssertionError("metadata writer was not released")
            return handle

        with patch("formowl_ingestion.storage.objects.os.fdopen", paused_open), ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(store.copy_local_file, root / "source.bin",
                                     storage_backend_id=stored.storage_backend_id,
                                     workspace_id=stored.workspace_id, original_filename="updated.txt")
            try:
                self.assertTrue(opened.wait(5), "metadata writer did not open")
                verified_during_write = store.verify_object(stored.object_uri, stored.content_hash)
                during_write_facts = dict(facts[-1])
            finally:
                release.set()
            updated = future.result(timeout=5)
        self.assertTrue(verified_during_write, during_write_facts)
        self.assertEqual(store.get_object(stored.object_uri), updated)
        self.assertTrue(store.verify_object(stored.object_uri, stored.content_hash))
        self.assertEqual(payload.read_bytes(), b"original bytes")

    def test_atomic_metadata_publication_errors_keep_old_record_and_mode(self):
        root, store, stored, payload, _ = self._verification_fixture("object-metadata-publication-errors")
        metadata = payload.with_name("metadata.json")
        metadata.chmod(0o640)
        original = metadata.read_bytes()
        original_open = os.open

        def no_space_to_create(path, flags, *args, **kwargs):
            if Path(path).parent == metadata.parent and flags & os.O_EXCL:
                raise OSError(errno.ENOSPC, "synthetic directory entry exhaustion")
            return original_open(path, flags, *args, **kwargs)

        for stage in ("create", "fsync", "replace"):
            with self.subTest(stage=stage):
                injection = (patch("formowl_ingestion.storage.objects.os.open", no_space_to_create) if stage == "create" else
                             patch("formowl_ingestion.storage.objects.os.fsync", side_effect=OSError(errno.ENOSPC, "synthetic sync failure"))
                             if stage == "fsync" else
                             patch.object(Path, "replace", side_effect=OSError(errno.ENOSPC, "synthetic publication failure")))
                with injection, self.assertRaises(OSError) as error:
                    store.copy_local_file(root / "source.bin", storage_backend_id=stored.storage_backend_id,
                                          workspace_id=stored.workspace_id, original_filename="updated.txt")
                self.assertEqual(error.exception.errno, errno.ENOSPC)
                self.assertEqual(metadata.read_bytes(), original)
                self.assertEqual(metadata.stat().st_mode & 0o777, 0o640)
                self.assertTrue(store.verify_object(stored.object_uri, stored.content_hash))
                self.assertEqual({path.name for path in payload.parent.iterdir()}, {"payload.bin", "metadata.json"})
        updated = store.copy_local_file(root / "source.bin", storage_backend_id=stored.storage_backend_id,
                                       workspace_id=stored.workspace_id, original_filename="updated.txt")
        self.assertEqual(store.get_object(stored.object_uri), updated)
        self.assertEqual(metadata.stat().st_mode & 0o777, 0o640)
        self.assertEqual(metadata.read_text(), json.dumps(updated.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        self.assertEqual((updated.object_uri, updated.content_hash, updated.file_size),
                         (stored.object_uri, stored.content_hash, stored.file_size))
        self.assertEqual(payload.read_bytes(), b"original bytes")

    def test_concurrent_metadata_writers_publish_whole_records(self):
        root, store, stored, payload, _ = self._verification_fixture("object-metadata-two-writers")
        opened = {name: Event() for name in ("first", "second")}
        release = {name: Event() for name in opened}
        writer_names = {}
        original_fdopen = os.fdopen

        def paused_open(*args, **kwargs):
            handle = original_fdopen(*args, **kwargs)
            name = writer_names.get(current_thread().ident)
            if name is not None:
                opened[name].set()
                if not release[name].wait(5):
                    handle.close()
                    raise AssertionError("metadata writer was not released")
            return handle

        def copy(name, filename):
            writer_names[current_thread().ident] = name
            return store.copy_local_file(root / "source.bin", storage_backend_id=stored.storage_backend_id,
                                         workspace_id=stored.workspace_id, original_filename=filename)

        with patch("formowl_ingestion.storage.objects.os.fdopen", paused_open), ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(copy, "first", "short.txt")
            try:
                self.assertTrue(opened["first"].wait(5))
                second = executor.submit(copy, "second", "a-much-longer-synthetic-name.txt")
                self.assertTrue(opened["second"].wait(5))
                release["second"].set()
                second_record = second.result(timeout=5)
                self.assertEqual(store.get_object(stored.object_uri), second_record)
                self.assertTrue(store.verify_object(stored.object_uri, stored.content_hash))
            finally:
                for event in release.values():
                    event.set()
            first_record = first.result(timeout=5)
        # The last completed writer supplies all metadata fields, without
        # trailing bytes from the longer record or a shared-temp collision.
        self.assertEqual(store.get_object(stored.object_uri), first_record)
        self.assertTrue(store.verify_object(stored.object_uri, stored.content_hash))
        self.assertEqual({path.name for path in payload.parent.iterdir()}, {"payload.bin", "metadata.json"})

    def test_verification_rejects_payload_replaced_after_open(self) -> None:
        temp_dir, store, stored, payload, facts = self._verification_fixture(
            "object-store-replaced-during-read"
        )
        replacement = temp_dir / "replacement.bin"
        replacement.write_bytes(b"different data")
        original_open = Path.open

        def replace_after_open(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            if path == payload and args == ("rb",):
                replacement.replace(payload)
            return handle

        with patch.object(Path, "open", replace_after_open):
            self.assertFalse(store.verify_object(stored.object_uri))
        self.assertEqual(facts[-1]["reason_code"], "path_changed_during_read")
        self.assertFalse(facts[-1]["path_stat_matches"])
        # The opened bytes really match the pin; they cannot authorize the new path.
        self.assertEqual(facts[-1]["actual_content_hash"], stored.content_hash)
        self.assertEqual(payload.read_bytes(), b"different data")

    def test_verification_rejects_same_size_write_even_with_restored_mtime(self) -> None:
        _, store, stored, payload, facts = self._verification_fixture("object-store-write-during-read")
        original_open = Path.open
        timestamp = payload.stat()

        @contextmanager
        def mutating_read(handle):
            with handle:
                def read(size):
                    chunk = handle.read(size)
                    if chunk:
                        with original_open(payload, "wb") as writer:
                            writer.write(b"modified bytes")
                        os.utime(payload, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
                    return chunk
                yield SimpleNamespace(read=read, fileno=handle.fileno)

        def open_with_mutation(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            return mutating_read(handle) if path == payload and args == ("rb",) else handle

        with patch.object(Path, "open", open_with_mutation):
            self.assertFalse(store.verify_object(stored.object_uri))
        self.assertEqual(facts[-1]["reason_code"], "file_changed_during_read")
        self.assertFalse(facts[-1]["file_stat_stable"])
        self.assertEqual(facts[-1]["actual_content_hash"], stored.content_hash)
        self.assertEqual(payload.stat().st_size, stored.file_size)
        self.assertEqual(payload.stat().st_mtime_ns, timestamp.st_mtime_ns)

    def test_verification_rechecks_governed_symlink_target_after_hashing(self) -> None:
        root, store, stored, payload, facts = self._verification_fixture("object-store-symlink-swap")
        first = payload.with_name("first.bin")
        second = payload.with_name("second.bin")
        payload.replace(first)
        second.write_bytes(b"different data")
        payload.symlink_to(first.name)
        original_open = Path.open

        def swap_symlink_after_open(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            if path == first and args == ("rb",):
                replacement = payload.with_name("new-link")
                replacement.symlink_to(second.name)
                replacement.replace(payload)
            return handle

        with patch.object(Path, "open", swap_symlink_after_open):
            self.assertFalse(store.verify_object(stored.object_uri))
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["reason_code"], "path_changed_during_read")
        self.assertFalse(facts[0]["path_stat_matches"])
        self.assertTrue(facts[0]["file_stat_stable"])
        self.assertEqual(facts[0]["actual_content_hash"], stored.content_hash)
        self.assertEqual(payload.read_bytes(), b"different data")
        self.assertNotIn(str(root), json.dumps(facts))

    def test_verification_reports_same_call_hash_and_size_mismatches_without_writes(self) -> None:
        root, store, stored, payload, facts = self._verification_fixture("object-store-safe-diagnostic")
        metadata = payload.with_name("metadata.json").read_bytes()
        for altered, reason in ((b"different data", "hash_mismatch"), (b"short", "size_mismatch")):
            with self.subTest(reason=reason):
                payload.write_bytes(altered)
                with patch("formowl_ingestion.storage.objects._hash_file", wraps=_hash_file) as reader:
                    self.assertFalse(store.verify_object(stored.object_uri, stored.content_hash))
                self.assertEqual(reader.call_count, 1)
                diagnostic = facts[-1]
                self.assertEqual(diagnostic["reason_code"], reason)
                self.assertEqual(diagnostic["expected_content_hash"], stored.content_hash)
                self.assertEqual(diagnostic["actual_content_hash"], sha256_prefixed(altered))
                self.assertEqual(diagnostic["expected_file_size"], stored.file_size)
                self.assertEqual(diagnostic["actual_file_size"], len(altered))
                self.assertTrue(diagnostic["read_completed"])
                self.assertTrue(diagnostic["file_stat_stable"])
                self.assertTrue(diagnostic["path_stat_matches"])
                self.assertNotIn(str(root), json.dumps(diagnostic))
                self.assertEqual(payload.read_bytes(), altered)
                self.assertEqual(payload.with_name("metadata.json").read_bytes(), metadata)
        facts.clear()
        self.assertFalse(store.verify_object(stored.object_uri, str(root / "secret")))
        self.assertNotIn(str(root), json.dumps(facts))

    def test_partial_read_failure_keeps_byte_count_and_never_reports_a_complete_digest(self) -> None:
        root, store, stored, payload, facts = self._verification_fixture("object-store-read-failure")
        original_open = Path.open

        @contextmanager
        def failing_read(handle):
            with handle:
                calls = 0
                def read(size):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return handle.read(4)
                    raise OSError(f"private read failure: {root}")
                yield SimpleNamespace(read=read, fileno=handle.fileno)

        def open_with_failure(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            return failing_read(handle) if path == payload and args == ("rb",) else handle

        with patch.object(Path, "open", open_with_failure):
            self.assertFalse(store.verify_object(stored.object_uri))
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["reason_code"], "payload_read_failed")
        self.assertEqual(facts[0]["actual_file_size"], 4)
        self.assertIsNone(facts[0]["actual_content_hash"])
        self.assertFalse(facts[0]["read_completed"])
        self.assertNotIn(str(root), json.dumps(facts))

    def test_hash_file_preserves_all_bytes_across_block_boundaries_and_short_reads(self) -> None:
        root = _paths.fresh_test_dir("object-store-hash-boundaries")
        original_open = Path.open
        source = root / "source.bin"
        for content in (b"", b"a" * (1024 * 1024), bytes(range(256)) * 8192 + b"tail"):
            with self.subTest(size=len(content)):
                source.write_bytes(content)
                expected = ("sha256:" + hashlib.sha256(content).hexdigest(), len(content))
                self.assertEqual(_hash_file(source), expected)

                @contextmanager
                def short_reads(handle):
                    with handle:
                        yield SimpleNamespace(read=lambda size: handle.read(min(size, 8191)),
                                              fileno=handle.fileno)

                def open_with_short_reads(path, *args, **kwargs):
                    handle = original_open(path, *args, **kwargs)
                    return short_reads(handle) if path == source and args == ("rb",) else handle

                with patch.object(Path, "open", open_with_short_reads):
                    self.assertEqual(_hash_file(source), expected)

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
