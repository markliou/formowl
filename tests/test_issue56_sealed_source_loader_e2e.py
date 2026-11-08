from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
from types import SimpleNamespace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    Observation,
    PermissionScope,
    SourceInventory,
    SourceInventoryItem,
    sha256_json,
    stable_resource_contract_id,
)
from formowl_gateway.issue56_diagnostic import Issue56SealedSourceDiagnosticInput
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
from formowl_mail import build_mail_evidence_bundle
from formowl_mail import issue56_sealed_source as sealed_source
from formowl_mail.query import source_occurrence_lineage_from_observation

from scripts import issue56_identity_scope_attestation as identity_attestation
from scripts import issue56_materialize_development_uat_observations as materializer
from scripts import issue56_prompt_mcp_hybrid_diagnostic as diagnostic_cli
from scripts import issue56_source_identifier_candidates as candidate_builder
import test_issue56_materialize_development_uat_observations_e2e as materializer_fixture


CREATED_AT = "2026-08-20T09:00:00+00:00"
WORKSPACE_PERMISSION_SCOPE = PermissionScope(
    scope_type="workspace",
    scope_id=sealed_source.WORKSPACE_ID,
    visibility="restricted",
)


class _PreparedPackage:
    def __init__(
        self,
        *,
        fixture: object,
        work_dir: Path,
        materialization_private_sha256: str,
        materialization_safe_sha256: str,
        attestation_root: Path,
        attestation_private_sha256: str,
        attestation_safe_sha256: str,
        identity_scope_fingerprint: str,
        candidate_root: Path,
        candidate_private_sha256: str,
        candidate_safe_sha256: str,
    ) -> None:
        self.fixture = fixture
        self.work_dir = work_dir
        self.materialization_private_sha256 = materialization_private_sha256
        self.materialization_safe_sha256 = materialization_safe_sha256
        self.attestation_root = attestation_root
        self.attestation_private_sha256 = attestation_private_sha256
        self.attestation_safe_sha256 = attestation_safe_sha256
        self.identity_scope_fingerprint = identity_scope_fingerprint
        self.candidate_root = candidate_root
        self.candidate_private_sha256 = candidate_private_sha256
        self.candidate_safe_sha256 = candidate_safe_sha256


class NativeColumnSchemaIndexTests(unittest.TestCase):
    def _revision(self):
        profile = gateway_loader.load_issue56_target_mail_tokenizer_profile()
        def h(number):
            return "sha256:" + f"{number:064x}"
        columns = [(" Ｌａｂ ID ", 2, False), ("lab id", 1, False),
                   ("LAB ID", 2, False), ("lab id", 3, True),
                   ("ＬＡＢ ID", 3, True), ("   ", 4, False),
                   ("\t", 5, True), ("Contract Ref", 6, True),
                   ("Measurement Ref", 7, False)]
        columns.extend((f"Fictional unrelated {i}", i + 20, False) for i in range(200))
        manifest = {"artifact_id": "formowl_issue56_ingestion_exact_cell_lookup_v1",
                    "schema_version": 1, "source_authority_fingerprint": h(900),
                    "tokenizer_profile_fingerprint": profile.profile_fingerprint,
                    "job_count": 0, "columns": [
                        {"field": field, "column_hash": h(number), "inline_table": inline,
                         "structure_status": "source_provided", "candidate_hashes": [h(901)]}
                        for field, number, inline in columns],
                    "shards": [], "counts": {"inline_authorized_row": 0, "attachment_authorized_row": 0}}
        manifest["manifest_fingerprint"] = sha256_json(manifest)
        return SimpleNamespace(exact_lookup_manifest=manifest,
            exact_lookup_directory=Path("/tmp/fictional-column-index"),
            safe_binding={"source_authority_fingerprint": h(900)}, job_authorities=(),
            source_records=None, authorized_source=object(),
            session=SimpleNamespace(authorized_observations=(), occurrence_lineages=()))

    def test_family_column_binding_matches_full_scan_and_normalizes_once_per_binding(self):
        import time
        lookup = gateway_loader._IngestionExactCellLookup(self._revision())
        normalize = gateway_loader.normalize_source_occurrence_structured_surface
        for field in ("lab id", " ", "contract ref", "measurement ref"):
            normalized = normalize(field)
            attachment = tuple(dict.fromkeys(item["column_hash"] for item in lookup._columns
                if normalize(item["field"]) == normalized and not item["inline_table"]))
            inline = tuple(dict.fromkeys(item["column_hash"] for item in lookup._columns
                if normalize(item["field"]) == normalized and item["inline_table"]))
            for families in (("attachment_table",), ("mail",), ("mail", "attachment_table")):
                expected = (attachment if families == ("attachment_table",) else
                    (inline or lookup._normalized_columns.get(normalized, ())) if families == ("mail",)
                    else (attachment or lookup._normalized_columns.get(normalized, ())))
                with self.subTest(field=field, families=families):
                    # Compare ordered tuples separately from the eventual set
                    # of value hashes, so source order/duplicate rules matter.
                    if hasattr(lookup, "_attachment_columns"):
                        self.assertEqual(lookup._attachment_columns.get(normalized, ()), attachment)
                        self.assertEqual(lookup._inline_columns.get(normalized, ()), inline)
                    bindings = (("unmatched first binding", "old"), (field, "fictional-value"))
                    with (mock.patch.object(gateway_loader, "bind_typed_identifier_to_source_schema", return_value=bindings),
                          mock.patch.object(lookup, "_read_matching_shard_records", return_value=()) as reads):
                        lookup.scan_source_rows(required_terms=("ZX-742",), query_text="fictional",
                            source_families=families, mail_import_session_id=None,
                            max_observations=128, deadline_monotonic=time.monotonic() + 2,
                            observation_callback=lambda *_: True, evidence_by_id={})
                    expected_hashes = {gateway_loader.source_occurrence_exact_cell_value_hash(column, "fictional-value")
                                       for column in expected}
                    observed = set().union(*(call.kwargs["matching_keys"] for call in reads.call_args_list))
                    self.assertEqual(observed, expected_hashes)
        with (mock.patch.object(gateway_loader, "bind_typed_identifier_to_source_schema",
                                return_value=(("lab id", "fictional-value"),) * 20),
              mock.patch.object(lookup, "_read_matching_shard_records", return_value=()),
              mock.patch.object(gateway_loader, "normalize_source_occurrence_structured_surface", wraps=normalize) as normalizations):
            lookup.scan_source_rows(required_terms=("ZX-742",), query_text="fictional",
                source_families=("attachment_table",), mail_import_session_id=None,
                max_observations=128, deadline_monotonic=time.monotonic() + 2,
                observation_callback=lambda *_: True, evidence_by_id={})
            self.assertLess(normalizations.call_count, 100,
                            "query must not renormalize the whole column inventory per binding")
        self.assertEqual(lookup._attachment_columns["lab id"],
                         ("sha256:" + f"{2:064x}", "sha256:" + f"{1:064x}"))
        with self.assertRaises(TypeError):
            lookup._attachment_columns["lab id"] = ()

    def test_schema_classifications_are_precomputed_without_changing_order(self):
        import time
        revision = self._revision()
        fields = ["PO Number", "Header PO No.", "Customer P/N", "customer p/n", "   ", "PO Number"]
        manifest = revision.exact_lookup_manifest
        for index, field in enumerate(fields):
            manifest["columns"].append({"field": field, "column_hash": "sha256:" + f"{index+600:064x}",
                "inline_table": False, "structure_status": "source_provided",
                "candidate_hashes": ["sha256:" + "f" * 64]})
        manifest.pop("manifest_fingerprint")
        manifest["manifest_fingerprint"] = sha256_json(manifest)
        lookup = gateway_loader._IngestionExactCellLookup(revision)
        all_fields = tuple(item["field"] for item in lookup._columns)
        expected_part = gateway_loader._part_identifier_schema_fields(all_fields)
        expected = (tuple(field for field in all_fields if field == "Header PO No."), expected_part, all_fields)
        with (mock.patch.object(gateway_loader, "_part_identifier_schema_fields", side_effect=AssertionError("query reclassified schema")),
              mock.patch.object(gateway_loader, "bind_typed_identifier_to_source_schema", return_value=()) as bind,
              mock.patch.object(lookup, "_read_matching_shard_records", return_value=())):
            for term in ("PO987654321", "987.ZZ", "ZX-742"):
                lookup.scan_source_rows(required_terms=(term,), query_text="fictional",
                    source_families=("attachment_table",), mail_import_session_id=None,
                    max_observations=128, deadline_monotonic=time.monotonic()+2,
                    observation_callback=lambda *_: True, evidence_by_id={})
        self.assertEqual(tuple(call.args[1] for call in bind.call_args_list), expected)

    def test_column_precomputation_keeps_constructor_binding_validation(self):
        revision = self._revision()
        revision.exact_lookup_manifest["manifest_fingerprint"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ContractValidationError, "binding is invalid"):
            gateway_loader._IngestionExactCellLookup(revision)
        revision = self._revision()
        manifest = revision.exact_lookup_manifest
        manifest["columns"][0]["inline_table"] = "not-a-bool"
        manifest.pop("manifest_fingerprint")
        manifest["manifest_fingerprint"] = sha256_json(manifest)
        with self.assertRaisesRegex(ContractValidationError, "column is invalid"):
            gateway_loader._IngestionExactCellLookup(revision)


class NativeShardVerifiedCacheTests(unittest.TestCase):
    def setUp(self):
        cls = gateway_loader._IngestionExactCellLookup
        if hasattr(cls, "_verified_shards"):
            cls._verified_shards.clear()
            cls._verified_shard_bytes = 0
            cls._cache_allocations = 0

    def _lookup(self, directory, payload, *, kind="row", count=None):
        lookup = object.__new__(gateway_loader._IngestionExactCellLookup)
        lookup._directory = Path(directory)
        folder = lookup._directory / ("rows" if kind == "row" else "values")
        folder.mkdir(exist_ok=True)
        (folder / "aa.jsonl").write_bytes(payload)
        lookup._shards = {(kind, "aa"): {
            "size_bytes": len(payload), "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "record_count": count if count is not None else len(payload.splitlines()),
        }}
        return lookup

    def test_native_shortlist_fixture_equality_across_wire_shapes(self):
        selected, other = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        for kind in ("row", "value"):
            record = (["row", selected, 0, "fictional-observation", other, False]
                      if kind == "row" else [selected, other, False])
            unrelated = (["cell", other, 0, "fictional-other", selected, False]
                         if kind == "row" else [other, selected, False])
            for ending in (b"\n", b"\r\n", b""):
                with self.subTest(kind=kind, ending=ending), tempfile.TemporaryDirectory() as directory:
                    canonical = json.dumps(record, separators=(",", ":")).encode()
                    escaped = canonical.replace(b"sha256:", b"\\u0073ha256:", 1)
                    payload = (json.dumps(unrelated).encode() + b"\n" + canonical + b"\r\n"
                               + b" \t" + escaped + ending)
                    lookup = self._lookup(directory, payload, kind=kind)
                    full = lookup._read_shard_records(kind, "aa", cache={})
                    expected = tuple(r for r in full if r[1 if kind == "row" else 0] == selected)
                    self.assertEqual(lookup._read_matching_shard_records(
                        kind, "aa", matching_keys={selected}), expected)
                    self.assertEqual(len(expected), 2)
                    self.assertIsNone(lookup._read_matching_shard_records(
                        kind, "aa", matching_keys={selected}, maximum_matching_records=1))

    def test_native_shortlist_preserves_seals_size_and_deadline(self):
        selected, other = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        line = json.dumps(["row", selected, 0, "fictional-observation", other, False]).encode()
        unrelated = json.dumps(["row", other, 0, "fictional-other", selected, False]).encode()
        with tempfile.TemporaryDirectory() as directory:
            payload = line + b"\n" + unrelated + b"\n"
            for key, value, message in (("sha256", "sha256:" + "0" * 64, "seal mismatch"),
                                        ("record_count", 1, "count mismatch"),
                                        ("record_count", 3, "count mismatch"),
                                        ("size_bytes", len(payload) - 1, "seal mismatch")):
                with self.subTest(binding=key, value=value):
                    lookup = self._lookup(directory, payload)
                    lookup._shards[("row", "aa")][key] = value
                    with self.assertRaisesRegex(ContractValidationError, message):
                        lookup._read_matching_shard_records("row", "aa", matching_keys={selected})
            for prefix in (line, unrelated):
                for ending in (b"\n", b""):
                    with self.subTest(oversized_selected=prefix == line, ending=ending):
                        lookup = self._lookup(directory, prefix + b" " * (16385 - len(prefix)) + ending)
                        with self.assertRaisesRegex(ContractValidationError, "oversized"):
                            lookup._read_matching_shard_records("row", "aa", matching_keys={selected})
            lookup = self._lookup(directory, line + b"\n" + b"not-json\n")
            with self.assertRaisesRegex(ContractValidationError, "shard is invalid"):
                lookup._read_matching_shard_records("row", "aa", matching_keys={selected})
            lookup = self._lookup(directory, payload)
            checks = 0
            def expire():
                nonlocal checks
                checks += 1
                if checks == 2:
                    raise RuntimeError("fictional deadline")
            with self.assertRaisesRegex(RuntimeError, "fictional deadline"):
                lookup._read_matching_shard_records("row", "aa", matching_keys={selected}, check=expire)
            # A warm absent-key search must poll even before merge yields a
            # selected record; no selected-record callback can save this case.
            lookup._read_matching_shard_records("row", "aa", matching_keys={selected})
            checks = 0
            with self.assertRaisesRegex(RuntimeError, "fictional deadline"):
                lookup._read_matching_shard_records("row", "aa", matching_keys={"sha256:" + "c" * 64}, check=expire)

    def test_prefix_partition_preserves_collisions_duplicates_and_file_order(self):
        cls = gateway_loader._IngestionExactCellLookup
        keys = ["sha256:aa123" + f"{n:059x}" for n in (1,2,3)]
        other = "sha256:aafff" + "0" * 59
        records = [["row", key, 0, f"fictional-{i}", other, False]
                   for i, key in enumerate((keys[1], other, keys[0], keys[1], keys[2], keys[0]))]
        payload = b"".join(json.dumps(record).encode()+b"\n" for record in records)
        with tempfile.TemporaryDirectory() as directory:
            lookup = self._lookup(directory, payload)
            for selected in ({keys[0],keys[1]}, {keys[2]}, {"sha256:aa123"+"f"*59}, {other}):
                expected = tuple(record for record in records if record[1] in selected)
                self.assertEqual(lookup._read_matching_shard_records("row", "aa", matching_keys=selected), expected)
            selected = {keys[0], keys[1]}
            self.assertEqual(lookup._read_matching_shard_records("row", "aa", matching_keys=selected),
                             tuple(record for record in records if record[1] in selected))
            entry = next(iter(cls._verified_shards.values()))
            prefix = entry["prefix_index"]
            self.assertEqual(len(prefix), 4097*4+len(records)*4)
            ordinals = [int.from_bytes(prefix[i:i+4], "big") for i in range(4097*4,len(prefix),4)]
            self.assertEqual(sorted(ordinals), list(range(len(records))))
            self.assertEqual(ordinals, [0, 2, 3, 4, 5, 1])
            prefix = None
            self.assertIsNone(lookup._read_matching_shard_records("row", "aa", matching_keys=set(keys), maximum_matching_records=1))
            # Retired readers keep both arrays charged until the last unpin.
            original_charge = cls._verified_shard_bytes
            entry["readers"] += 1
            cls._drop_cache_entry(next(iter(cls._verified_shards)))
            self.assertEqual(cls._verified_shard_bytes, original_charge)
            cls._unpin_cache_entry(entry)
            self.assertIsNone(entry["index"])
            self.assertIsNone(entry["prefix_index"])
            self.assertEqual(cls._verified_shard_bytes, 0)
            build = lookup._build_prefix_index
            def interrupted(index, check=None):
                calls = 0
                def abort():
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise RuntimeError("fictional prefix build interruption")
                return build(index, abort)
            with mock.patch.object(lookup, "_build_prefix_index", side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError, "prefix build interruption"):
                    lookup._read_matching_shard_records("row", "aa", matching_keys=set(keys))
            self.assertFalse(cls._verified_shards)
            self.assertEqual(cls._verified_shard_bytes, 0)

    def test_verified_cache_warm_reads_and_identity_change_fail_closed(self):
        selected, other = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        record = ["row", selected, 0, "fictional-observation", other, False]
        unrelated = ["cell", other, 0, "fictional-other", selected, False]
        payload = json.dumps(record).encode() + b"\n" + (json.dumps(unrelated).encode() + b"\n") * 500
        with tempfile.TemporaryDirectory() as directory:
            lookup = self._lookup(directory, payload)
            self.assertEqual(lookup._read_matching_shard_records("row", "aa", matching_keys={selected}), (record,))
            original = gateway_loader.hashlib.sha256
            with mock.patch.object(gateway_loader.hashlib, "sha256", wraps=original) as hashes:
                self.assertEqual(lookup._read_matching_shard_records("row", "aa", matching_keys={selected}), (record,))
            self.assertFalse(any(not call.args for call in hashes.call_args_list),
                             "warm use must read sealed selected lines without hashing the full shard")
            # Another owner instance reuses the same process verification;
            # do not rewrite the already verified file during this assertion.
            second = object.__new__(gateway_loader._IngestionExactCellLookup)
            second._directory, second._shards = lookup._directory, dict(lookup._shards)
            with mock.patch.object(gateway_loader.hashlib, "sha256", wraps=original) as hashes:
                self.assertEqual(second._read_matching_shard_records("row", "aa", matching_keys={selected}), (record,))
            self.assertFalse(any(not call.args for call in hashes.call_args_list))
            path = Path(directory) / "rows/aa.jsonl"
            before = path.stat()
            path.write_bytes(payload.replace(b"fictional-other", b"fictional-otHer", 1))
            # Ensure a metadata delta even on a filesystem with coarse ctime.
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
            with self.assertRaisesRegex(ContractValidationError, "seal mismatch"):
                lookup._read_matching_shard_records("row", "aa", matching_keys={selected})
            self.assertFalse(gateway_loader._IngestionExactCellLookup._verified_shards)

    def test_verified_cache_periodic_bound_and_interrupted_admission(self):
        cls = gateway_loader._IngestionExactCellLookup
        selected, other = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        record = ["row", selected, 0, "fictional-observation", other, False]
        payload = json.dumps(record).encode() + b"\n"
        with tempfile.TemporaryDirectory() as directory:
            lookup = self._lookup(directory, payload)
            scan = lookup._scan_matching_shard_records
            with (mock.patch.object(cls, "_CACHE_REVERIFY_USES", 2),
                  mock.patch.object(lookup, "_scan_matching_shard_records", wraps=scan) as reads):
                for _ in range(3):
                    self.assertEqual(lookup._read_matching_shard_records("row", "aa", matching_keys={selected}), (record,))
                self.assertEqual(reads.call_count, 2)
            with (mock.patch.object(gateway_loader.time, "monotonic", return_value=10**12),
                  mock.patch.object(lookup, "_scan_matching_shard_records", wraps=scan) as reads):
                lookup._read_matching_shard_records("row", "aa", matching_keys={selected})
                self.assertEqual(reads.call_count, 1)
            cls._verified_shards.clear()
            cls._verified_shard_bytes = 0
            checks = 0
            def interrupted():
                nonlocal checks
                checks += 1
                if checks == 4:
                    raise RuntimeError("fictional interrupted verification")
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                lookup._read_matching_shard_records("row", "aa", matching_keys={selected}, check=interrupted)
            self.assertFalse(cls._verified_shards)
            with mock.patch.object(cls, "_CACHE_MAX_BYTES", 10000):
                for index in range(4):
                    child = Path(directory) / str(index)
                    child.mkdir()
                    item = self._lookup(child, payload)
                    item._read_matching_shard_records("row", "aa", matching_keys={selected})
                self.assertLessEqual(cls._verified_shard_bytes, 10000)
                self.assertLess(len(cls._verified_shards), 4)
            cls._verified_shards.clear()
            cls._verified_shard_bytes = 0
            with mock.patch.object(cls, "_CACHE_ENTRY_MAX_BYTES", 1):
                for _ in range(2):
                    lookup._read_matching_shard_records("row", "aa", matching_keys={selected})
                self.assertFalse(cls._verified_shards)

    def test_verified_cache_rejects_symlink_and_selected_line_change(self):
        cls = gateway_loader._IngestionExactCellLookup
        selected, other = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        record = ["row", selected, 0, "fictional-observation", other, False]
        payload = json.dumps(record).encode() + b"\n"
        with tempfile.TemporaryDirectory() as directory:
            lookup = self._lookup(directory, payload)
            lookup._read_matching_shard_records("row", "aa", matching_keys={selected})
            path = Path(directory) / "rows/aa.jsonl"
            original_identity = cls._shard_identity(path.stat())
            path.write_bytes(payload.replace(b"fictional-observation", b"fictional-Observation"))
            # Even forged cheap metadata cannot replace the selected-line seal.
            with mock.patch.object(cls, "_shard_identity", return_value=original_identity):
                with self.assertRaisesRegex(ContractValidationError, "seal mismatch"):
                    lookup._read_matching_shard_records("row", "aa", matching_keys={selected})
            self.assertFalse(cls._verified_shards)
            target = Path(directory) / "target.jsonl"
            target.write_bytes(payload)
            path.unlink()
            path.symlink_to(target)
            with self.assertRaisesRegex(ContractValidationError, "unavailable"):
                lookup._read_matching_shard_records("row", "aa", matching_keys={selected})



class NativeShardCacheLifecycleTests(unittest.TestCase):
    _lookup = NativeShardVerifiedCacheTests._lookup

    def _fixture(self, directory):
        key, other = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        record = ["row", key, 0, "fictional-cache", other, False]
        payload = json.dumps(record).encode() + b"\n"
        lookup = self._lookup(directory, payload)
        (Path(directory) / "rows/bb.jsonl").write_bytes(payload)
        lookup._shards[("row", "bb")] = dict(lookup._shards[("row", "aa")])
        return lookup, key, record

    def test_startup_seals_every_shard_and_failure_never_ready(self):
        cls = gateway_loader._IngestionExactCellLookup
        with tempfile.TemporaryDirectory() as directory:
            lookup, key, record = self._fixture(directory)
            before = cls.cache_receipt()
            lease = lookup.start_cache()
            try:
                after = cls.cache_receipt()
                self.assertEqual(after["prewarm_success"] - before["prewarm_success"], 2)
                self.assertEqual(after["background_workers"], 1)
                second = object.__new__(cls)
                second._directory, second._shards = lookup._directory, dict(lookup._shards)
                second.start_cache()
                self.assertEqual(cls.cache_receipt()["background_workers"], 1)
                self.assertEqual(cls.cache_receipt()["prewarm_success"], after["prewarm_success"])
                second.close_cache()
                self.assertEqual(cls.cache_receipt()["background_workers"], 1)
                self.assertEqual(lookup._read_matching_shard_records("row", "bb", matching_keys={key}), (record,))
                self.assertEqual(cls.cache_receipt()["hit_success"] - after["hit_success"], 1)
            finally:
                lease.close_cache()
            self.assertEqual(cls.cache_receipt()["background_workers"], 0)
        with tempfile.TemporaryDirectory() as directory:
            lookup, _, _ = self._fixture(directory)
            lookup._shards[("row", "bb")]["sha256"] = "sha256:" + "0" * 64
            with self.assertRaises(ContractValidationError):
                lookup.start_cache()
            self.assertEqual(cls.cache_receipt()["managed_shards"], 0)
            self.assertEqual(cls.cache_receipt()["background_workers"], 0)
        with tempfile.TemporaryDirectory() as directory:
            lookup, _, _ = self._fixture(directory)
            (Path(directory) / "rows/aa.jsonl").unlink()
            with self.assertRaisesRegex(ContractValidationError, "shard is unavailable"):
                lookup._verify_cache_shard("row", "aa", matching_keys=set(), origin="prewarm")
            with self.assertRaisesRegex(ContractValidationError, "startup is unavailable"):
                lookup.start_cache()
            self.assertEqual(cls.cache_receipt()["managed_shards"], 0)
            self.assertEqual(cls.cache_receipt()["background_workers"], 0)

    def test_background_refresh_is_nonblocking_and_expiry_fails_closed(self):
        import threading
        import time
        cls = gateway_loader._IngestionExactCellLookup
        with tempfile.TemporaryDirectory() as directory:
            lookup, key, record = self._fixture(directory)
            lease = lookup.start_cache()
            entered, release = threading.Event(), threading.Event()
            scan = lookup._scan_matching_shard_records
            def paused(*args, **kwargs):
                if threading.current_thread().name == "formowl-native-shard-cache":
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError("fictional background gate timed out")
                return scan(*args, **kwargs)
            try:
                with mock.patch.object(lookup, "_scan_matching_shard_records", side_effect=paused):
                    with cls._verified_shard_lock:
                        for entry in cls._verified_shards.values():
                            entry["verified_at"] = time.monotonic() - 250
                    cls._cache_wake.set()
                    self.assertTrue(entered.wait(2))
                    with cls._verified_shard_lock:
                        active_key, token = next(iter(cls._cache_inflight.items()))
                        context = cls._managed_shards[active_key]
                    with self.assertRaisesRegex(ContractValidationError, "in progress"):
                        lookup._verify_cache_shard(context["kind"], context["shard"],
                            matching_keys=set(), origin="reverify", expected_context=context)
                    self.assertFalse(token["cancelled"])
                    self.assertFalse(context["failed"])
                    deadline = time.monotonic() + 0.5
                    def check():
                        if time.monotonic() >= deadline:
                            raise RuntimeError("fictional query blocked by background scan")
                    self.assertEqual(lookup._read_matching_shard_records("row", "aa", matching_keys={key}, check=check), (record,))
                    with cls._verified_shard_lock:
                        for entry in cls._verified_shards.values():
                            entry["verified_at"] = time.monotonic() - 301
                    with self.assertRaises(ContractValidationError):
                        lookup._read_matching_shard_records("row", "bb", matching_keys={key}, check=check)
                    self.assertGreater(cls.cache_receipt()["expired_reject"], 0)
                    release.set()
            finally:
                release.set()
                lease.close_cache()


    def test_background_failure_quarantines_once_and_invalidated_generation_cannot_publish(self):
        import threading
        import time
        cls = gateway_loader._IngestionExactCellLookup
        with tempfile.TemporaryDirectory() as directory:
            lookup, key, _ = self._fixture(directory)
            lease = lookup.start_cache()
            entered, release = threading.Event(), threading.Event()
            scan = lookup._scan_matching_shard_records
            def paused(*args, **kwargs):
                result = scan(*args, **kwargs)
                if threading.current_thread().name == "formowl-native-shard-cache":
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError("fictional publication gate timed out")
                return result
            try:
                with mock.patch.object(lookup, "_scan_matching_shard_records", side_effect=paused):
                    with cls._verified_shard_lock:
                        cache_key = next(iter(cls._verified_shards))
                        cls._verified_shards[cache_key]["uses"] = 64
                    before = cls.cache_receipt()["reverify_success"]
                    cls._cache_wake.set()
                    self.assertTrue(entered.wait(2))
                    path = Path(cache_key)
                    info = path.stat()
                    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
                    with self.assertRaisesRegex(ContractValidationError, "identity changed"):
                        lookup._read_matching_shard_records("row", "aa", matching_keys={key})
                    # Remove the lease while verification is in flight. The old
                    # generation must never publish or revive a closed lease.
                    cls._cache_stop.set()
                    release.set()
                    lease.close_cache()
                    self.assertNotIn(cache_key, cls._verified_shards)
                    self.assertEqual(cls.cache_receipt()["reverify_success"], before)
            finally:
                release.set()
                lease.close_cache()
        with tempfile.TemporaryDirectory() as directory:
            lookup, key, _ = self._fixture(directory)
            lease = lookup.start_cache()
            try:
                with mock.patch.object(lookup, "_scan_matching_shard_records", side_effect=RuntimeError("fictional failure")) as scans:
                    with cls._verified_shard_lock:
                        cache_key = next(iter(cls._verified_shards))
                        context = cls._managed_shards[cache_key]
                        cls._verified_shards[cache_key]["uses"] = 64
                    cls._cache_wake.set()
                    until = time.monotonic() + 2
                    while not context["failed"] and time.monotonic() < until:
                        time.sleep(0.01)
                    self.assertTrue(context["failed"])
                    cls._cache_wake.set()
                    time.sleep(0.05)
                    self.assertEqual(scans.call_count, 1)
                    with self.assertRaisesRegex(ContractValidationError, "unavailable"):
                        lookup._read_matching_shard_records("row", "aa", matching_keys={key})
            finally:
                lease.close_cache()


class Issue56SealedSourceLoaderE2ETests(unittest.TestCase):
    def test_recovery_summary_distinguishes_unread_terms_from_observed_zero(self):
        for observed, complete in ((0, False), (0, True), (3, False), (3, True)):
            with self.subTest(observed=observed, complete=complete):
                summary = gateway_loader._build_source_recovery_summary(
                    query_text="clienta 甲社專案", source_family_scope=("mail",),
                    required_terms=("clienta", "甲社專案"), initial_status="pending_review",
                    initial_warnings=("retrieval_projection_unavailable",), initial_evidence_count=0,
                    result_status="pending_review", double_check=SimpleNamespace(scan=SimpleNamespace(
                        complete=complete, scanned_observation_count=observed,
                        stop_reason=None if complete else "indexed_token_scope")), evidence=(),
                    required_term_observation_count=observed, required_term_hit_counts={"clienta": 0, "甲社專案": 0},
                    joint_candidate_count=0, source_authority_fingerprint=sha256_json("source"),
                    source_session_binding_fingerprint=sha256_json("session"), warnings=("used",), recheck_variant=None,
                    date_priority_phase={"attempted": True, "candidate_count": 0, "sql_complete": True},
                )
                for item in summary["required_term_hit_counts"]:
                    self.assertEqual(item["count"], 0 if observed else None)
                    self.assertEqual(item["status"], ("complete" if complete else "partial") if observed else "unavailable")
                self.assertEqual(summary["date_priority"]["candidate_count_scope"], "indexed_token_intersection")
                self.assertEqual(summary["date_priority"]["source_completeness"], "unknown")
                self.assertEqual(summary["joint_candidate_count_state"], "complete_zero" if complete else "unknown")

    def test_source_start_parent_map_has_separate_finite_cap_and_preserves_seals(self) -> None:
        from test_issue56_uat_handler_composition import _source_start_preparation_fixture

        self.assertEqual(sealed_source._MAX_SAFE_BYTES, 16 * 1024 * 1024)
        self.assertEqual(sealed_source._MAX_INGESTION_PARENT_BINDING_BYTES, 256 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(Path(directory))
            parent = next(item for item in fixture.observations
                          if item.observation_type == "email_message")
            parent_path = fixture.directory / "sidecar-parent-binding.json"
            preparation_path = fixture.directory / "preparation.json"
            # Exercise the sealed JSON byte-intake contract with genuine
            # completed-job parent records; whitespace scales file size only.
            parent_json = json.dumps({"parents": [parent.to_dict()]}, sort_keys=True).encode()
            core = {**fixture.preparation_core, "sidecar_parent_binding_sha256": "sha256:" + "0" * 64}
            preparation_size = len(json.dumps({
                **core, "preparation_fingerprint": sha256_json(core),
            }, sort_keys=True).encode())
            generic_cap = max(preparation_size, (fixture.directory / "exact-cells" / "manifest.json").stat().st_size) + 128
            parent_bytes = parent_json + b" " * generic_cap
            dedicated_cap = len(parent_bytes) + 128
            self.assertGreater(len(parent_bytes), generic_cap)
            self.assertLess(len(parent_bytes), dedicated_cap)
            parent_path.write_bytes(parent_bytes)
            core["sidecar_parent_binding_sha256"] = "sha256:" + hashlib.sha256(parent_bytes).hexdigest()
            preparation_bytes = json.dumps({
                **core, "preparation_fingerprint": sha256_json(core),
            }, sort_keys=True).encode()
            preparation_path.write_bytes(preparation_bytes)
            preparation_hash = "sha256:" + hashlib.sha256(preparation_bytes).hexdigest()

            with (
                mock.patch.object(sealed_source, "_MAX_SAFE_BYTES", generic_cap),
                mock.patch.object(sealed_source, "_MAX_INGESTION_PARENT_BINDING_BYTES", dedicated_cap),
            ):
                revision = sealed_source.load_issue56_ingestion_revision(
                    fixture.directory, expected_revision_sha256=preparation_hash,
                )
                self.assertTrue(revision.safe_binding["source_start"])
                self.assertEqual(revision.safe_binding["source_revision_sha256"], preparation_hash)
                self.assertEqual(tuple(item.job_fingerprint for item in revision.job_authorities),
                                 tuple(item.job_fingerprint for item in fixture.authorities))
                self.assertEqual(revision.source_records.observation_references,
                                 fixture.snapshot["observation_references"])

                with self.subTest(invalid="expected_hash_mismatch"):
                    parent_path.write_bytes(parent_bytes[:-1] + b"\n")
                    with self.assertRaisesRegex(sealed_source.Issue56SealedSourceLoadError,
                                                "^ingestion_parent_binding_byte_seal_mismatch$"):
                        sealed_source.load_issue56_ingestion_revision(
                            fixture.directory, expected_revision_sha256=preparation_hash,
                        )
                    parent_path.write_bytes(parent_bytes)

                with self.subTest(invalid="symlink"):
                    target = parent_path.with_name("parent-target.json")
                    parent_path.rename(target)
                    parent_path.symlink_to(target)
                    with self.assertRaisesRegex(sealed_source.Issue56SealedSourceLoadError,
                                                "^ingestion_parent_binding_unavailable$"):
                        sealed_source.load_issue56_ingestion_revision(
                            fixture.directory, expected_revision_sha256=preparation_hash,
                        )
                    parent_path.unlink()
                    target.rename(parent_path)

                with self.subTest(invalid="dedicated_cap_plus_one"):
                    parent_path.write_bytes(parent_bytes + b" " * (dedicated_cap + 1 - len(parent_bytes)))
                    self.assertEqual(parent_path.stat().st_size, dedicated_cap + 1)
                    with self.assertRaisesRegex(sealed_source.Issue56SealedSourceLoadError,
                                                "^ingestion_parent_binding_unavailable$"):
                        sealed_source.load_issue56_ingestion_revision(
                            fixture.directory, expected_revision_sha256=preparation_hash,
                        )
                    parent_path.write_bytes(parent_bytes)

                with self.subTest(invalid="generic_metadata_cap_unchanged"):
                    oversized_preparation = preparation_bytes + b" " * (generic_cap + 1 - len(preparation_bytes))
                    preparation_path.write_bytes(oversized_preparation)
                    self.assertLess(len(oversized_preparation), dedicated_cap)
                    with self.assertRaisesRegex(sealed_source.Issue56SealedSourceLoadError,
                                                "^ingestion_preparation_unavailable$"):
                        sealed_source.load_issue56_ingestion_revision(
                            fixture.directory,
                            expected_revision_sha256="sha256:" + hashlib.sha256(oversized_preparation).hexdigest(),
                        )

    def test_source_start_discovery_allows_chat_without_inventing_mail_selectors(self) -> None:
        from formowl_gateway.issue56_uat_runtime import (
            _query_agent_runtime_context,
            create_issue56_temporary_lan_query_service,
        )
        from formowl_mail.human_uat_orchestrator import (
            CodexResponsesConversationModel,
            _UatTurnRequestContractBinder,
        )
        from test_issue56_codex_provider_bridge import _decision
        import test_issue56_uat_handler_composition as composition_fixture

        register_asset = composition_fixture.register_asset_from_local_file
        for upload_selector_available, families in (
            (False, ("mail", "document_text")),
            (True, ("mail", "document_text")),
            (False, ("document_text",)),
        ):
            with self.subTest(upload_selector_available=upload_selector_available, families=families):
                with tempfile.TemporaryDirectory() as directory:
                    def register_source(*args, **kwargs):
                        if not upload_selector_available:
                            # Real registration, extraction and job seals; a
                            # captured source need not be an upload session.
                            kwargs.pop("source_ref", None)
                        return register_asset(*args, **kwargs)

                    with mock.patch.object(
                        composition_fixture,
                        "register_asset_from_local_file",
                        side_effect=register_source,
                    ):
                        fixture = composition_fixture._source_start_preparation_fixture(
                            Path(directory), families=families,
                        )
                    revision = sealed_source.load_issue56_ingestion_revision(
                        fixture.directory,
                        expected_revision_sha256=fixture.preparation_sha256,
                    )
                    selectors = revision.source_records.authorized_mail_import_session_ids
                    self.assertEqual(len(selectors), int(upload_selector_available))
                    model = CodexResponsesConversationModel(
                        base_url="https://provider.example.test/v1",
                        api_key="synthetic-direct-provider-key",
                    )
                    with (
                        mock.patch.object(
                            model, "_request_response",
                            return_value={
                                "status": "completed",
                                "output_text": _decision(answer_text="Hello"),
                            },
                        ) as request_response,
                        create_issue56_temporary_lan_query_service(
                            model, ingestion_revision=revision,
                        ) as service,
                        mock.patch.object(service, "_call") as mcp_call,
                    ):
                        session_id, _ = service.ensure_browser_session(None)
                        result = service.ask("Hello", session_id=session_id)
                        self.assertEqual(result["status"], "complete")
                        self.assertEqual(result["answer"], "Hello")
                        request_response.assert_called_once()
                        request = request_response.call_args.args[0]
                        # The configured catalog stays on the wire for a stable
                        # prompt-cache prefix; tool_choice "none" forbids any call.
                        self.assertEqual(request["tool_choice"], "none")
                        self.assertTrue({tool["name"] for tool in request["tools"]} <= {
                            "query_effective_graph_view", "query_mail_evidence",
                            "clarify_public_terminology",
                        })
                        mcp_call.assert_not_called()
                        self.assertEqual(service.request_count, 0)

                        discoveries = (
                            (
                                "Find mail evidence",
                                "query_mail_evidence" if selectors
                                else "query_effective_graph_view",
                            ),
                            ("Find document evidence", "query_effective_graph_view"),
                        ) if "mail" in families else (
                            ("Find document evidence", "query_effective_graph_view"),
                        )
                        for prompt, tool_name in discoveries:
                            descriptor, capabilities = _query_agent_runtime_context(
                                service._application, user_text=prompt,
                            )
                            self.assertEqual(descriptor["name"], tool_name)
                            self.assertEqual(capabilities["source_families"], list(families))
                            self.assertEqual(capabilities.get("selector_count", 0), len(selectors))
                            if selectors:
                                self.assertEqual(
                                    capabilities["authorized_mail_import_session_ids"],
                                    list(selectors),
                                )
                                self.assertEqual(
                                    capabilities["mail_selector_kind"], "mail_import_session_id",
                                )
                            else:
                                self.assertNotIn("authorized_mail_import_session_ids", capabilities)
                                self.assertNotIn("mail_selector_kind", capabilities)
                            core = dict(capabilities)
                            fingerprint = core.pop("capability_fingerprint")
                            self.assertEqual(fingerprint, sha256_json(core))
                            binder = _UatTurnRequestContractBinder(
                                user_text=prompt, authorized_capability_summary=capabilities,
                            )
                            if selectors:
                                self.assertEqual(binder.bind_mail_selector(
                                    mail_import_session_id=None, mail_evidence_bundle_id=None,
                                ), (selectors[0], None))
                            else:
                                for selector in (None, "unbound-session"):
                                    with self.assertRaisesRegex(
                                        ContractValidationError, "selector is unavailable",
                                    ):
                                        binder.bind_mail_selector(
                                            mail_import_session_id=selector,
                                            mail_evidence_bundle_id=None,
                                        )

    def test_capability_families_use_the_indexed_runtime_authorized_scope(self) -> None:
        class _RuntimeStore:
            def reopen(self, seal):
                self.asserted_seal = seal
                return {
                    "view_metadata": {
                        "source_families": ["mail"],
                    },
                }

        session = SimpleNamespace(
            index=SimpleNamespace(
                _runtime_store=_RuntimeStore(),
                _runtime_store_seal="sealed-revision",
            ),
        )

        self.assertEqual(
            gateway_loader._authorized_runtime_source_families(session),
            ("mail",),
        )

    def test_mock_index_does_not_reopen_storage_for_capability_families(self) -> None:
        runtime_store = mock.Mock()
        runtime_store.reopen.side_effect = TypeError("mock metadata is not subscriptable")
        session = SimpleNamespace(
            index=SimpleNamespace(
                _runtime_store=runtime_store,
                _runtime_store_seal="sealed-revision",
            ),
        )

        self.assertEqual(
            gateway_loader._authorized_runtime_source_families(session),
            (),
        )
        runtime_store.reopen.assert_not_called()

    def test_projection_open_failure_falls_through_to_authorized_source_reader(self) -> None:
        runtime_store = mock.Mock()
        runtime_store.reopen.side_effect = RuntimeError("projection is unavailable")
        source_reader = object()
        authorized_source = object()
        source_binding = sha256_json("source-session")
        revision = SimpleNamespace(
            session=SimpleNamespace(
                index=SimpleNamespace(
                    _runtime_store=runtime_store,
                    _runtime_store_seal="sha256:" + ("a" * 64),
                ),
                source_session_binding_fingerprint=source_binding,
            ),
            source_records=source_reader,
            authorized_source=authorized_source,
        )
        fallback_handler = mock.Mock(name="source_fallback_handler")
        with mock.patch.object(
            gateway_loader,
            "_build_source_start_semantic_handler",
            return_value=fallback_handler,
        ) as build_fallback:
            returned = gateway_loader.build_issue56_production_semantic_retrieval_handler(
                ingestion_revision=revision,
            )

        self.assertIs(returned, fallback_handler)
        build_fallback.assert_called_once_with(revision, mail_tool=False)
        runtime_store.reopen.assert_called_once_with(
            "sha256:" + ("a" * 64),
        )

    def test_mail_selector_uses_owner_source_ref_without_mime_allowlist(self) -> None:
        content_hash = "sha256:" + ("a" * 64)
        mail_asset = SimpleNamespace(
            asset_id="asset_mail_nonstandard_mime",
            content_hash=content_hash,
            mime_type="application/x-owner-defined-mail",
            owner_user_id="user_yifan",
            workspace_id="workspace_formowl",
            source_ref={
                "source_system": "formowl_upload_session",
                "source_type": "mail_archive_upload",
                "source_id": "upload-session-mail-001",
                "source_key": "upload-session-mail-001",
            },
        )
        non_mail_asset = SimpleNamespace(
            asset_id="asset_document",
            content_hash=content_hash,
            mime_type="application/x-owner-defined-document",
            owner_user_id="user_yifan",
            workspace_id="workspace_formowl",
            source_ref={
                "source_system": "formowl_upload_session",
                "source_type": "document_upload",
                "source_id": "upload-session-document-001",
                "source_key": "upload-session-document-001",
            },
        )

        def records_for(asset):
            authority = SimpleNamespace(asset=asset)
            records = object.__new__(sealed_source.IngestionRevisionSourceRecords)
            records.job_authorities = (authority,)
            return records

        mail_selectors = records_for(mail_asset).authorized_mail_import_session_ids
        self.assertEqual(
            mail_selectors,
            (
                stable_resource_contract_id(
                    "mailimport",
                    "MailImportSession",
                    {
                        "upload_session_id": "upload-session-mail-001",
                        "workspace_id": "workspace_formowl",
                        "owner_user_id": "user_yifan",
                        "source_asset_id": "asset_mail_nonstandard_mime",
                        "archive_sha256": content_hash,
                    },
                ),
            ),
        )
        self.assertEqual(
            records_for(non_mail_asset).authorized_mail_import_session_ids,
            (),
        )

    def test_ingestion_revision_uses_its_bounded_larger_source_cap(self) -> None:
        seal = "sha256:" + ("0" * 64)
        manifest = {
            "artifact_id": "formowl_issue56_ingestion_revision_v1",
            "requester_user_id": sealed_source.APPROVER_ACTOR,
            "workspace_id": sealed_source.WORKSPACE_ID,
            "snapshot_sha256": seal,
            "index_manifest_sha256": seal,
        }
        calls: list[dict[str, object]] = []

        def read_json(path, **kwargs):
            calls.append({"path": path, **kwargs})
            if len(calls) == 1:
                return b"{}", manifest
            if len(calls) == 2:
                return b"{}", {"observations": [], "bundles": [], "source_binding": {}}
            raise RuntimeError("stop after cap inspection")

        with tempfile.TemporaryDirectory() as revision_root:
            revision_directory = Path(revision_root)
            # The loader selects the source-start preparation when the
            # finalized revision marker is absent.  Keep this fixture on the
            # finalized-revision branch so the cap assertions exercise the
            # intended snapshot/index reads without mocking branch selection.
            (revision_directory / "revision.json").write_bytes(b"fixture")
            with (
                mock.patch.object(
                    sealed_source, "_read_sealed_json", side_effect=read_json
                ),
                self.assertRaisesRegex(RuntimeError, "stop after cap inspection"),
            ):
                sealed_source.load_issue56_ingestion_revision(
                    revision_directory,
                    expected_revision_sha256=seal,
                )

        self.assertEqual(sealed_source._MAX_SOURCE_BYTES, 1024 * 1024 * 1024)
        self.assertEqual(
            sealed_source._MAX_INGESTION_REVISION_SOURCE_BYTES,
            4 * 1024 * 1024 * 1024,
        )
        self.assertEqual(
            [call["maximum_bytes"] for call in calls],
            [
                sealed_source._MAX_SAFE_BYTES,
                sealed_source._MAX_INGESTION_REVISION_SOURCE_BYTES,
                sealed_source._MAX_INGESTION_REVISION_SOURCE_BYTES,
            ],
        )

    def test_typed_exact_request_fails_closed_without_exact_result(self) -> None:
        loaded = mock.Mock()
        loaded.safe_binding = {}
        # The production handler constructs its sealed fallback reader while
        # composing the handler.  Keep this mock seam minimally valid for that
        # reader, while the exact request below still proves that no fallback
        # can turn an unavailable exact result into an answer.
        loaded.observations = ()
        loaded.query_bundle.mail_import_session.mail_import_session_id = (
            "synthetic_mail_import_session"
        )
        loaded.session.source_session_binding_fingerprint = sha256_json(
            "source_session"
        )
        loaded.effective_graph_view.requester_user_id = sealed_source.APPROVER_ACTOR
        loaded.effective_graph_view.visible_edges = (
            mock.Mock(edge_id="source_edge", relation_type="source_backed"),
        )
        routed_session = mock.Mock(
            requester_user_id=sealed_source.APPROVER_ACTOR,
            workspace_id=sealed_source.WORKSPACE_ID,
            selected_source_scope_ids=(),
            authorized_source_scope_ids=(),
            authorized_observation_hashes=(),
            authorized_observations=(),
            occurrence_lineages=(),
            source_session_binding_fingerprint=sha256_json(
                "source_session"
            ),
            source_occurrence_providers=(),
            _source_occurrence_provider_provenance_seal=None,
        )
        query_agent_payload = {
            "status": "unsupported",
            "context_bundle": {
                "citation_hashes": [],
                "lineage_fingerprints": [],
            },
        }

        with (
            mock.patch.object(
                gateway_loader,
                "_load_approved_sealed_source",
                return_value=loaded,
            ),
            mock.patch.object(
                gateway_loader,
                "_validated_owner_safe_binding",
                return_value={},
            ),
            mock.patch.object(
                gateway_loader,
                "_build_mail_source_occurrence_providers",
                return_value=(),
            ),
            mock.patch.object(
                gateway_loader,
                "attach_authorized_source_occurrence_providers",
                return_value=routed_session,
            ),
            mock.patch.object(
                gateway_loader,
                "execute_bounded_adaptive_query",
                return_value=(
                    mock.Mock(exact_result=None),
                    (),
                    query_agent_payload,
                ),
            ),
        ):
            handler = gateway_loader.build_issue56_production_semantic_retrieval_handler()
            with self.assertRaisesRegex(
                ContractValidationError,
                "production exact inventory result is unavailable",
            ):
                handler(
                    {
                        "query_text": "synthetic exact request",
                        "requester_user_id": sealed_source.APPROVER_ACTOR,
                        "session_id": "session",
                        "workspace_id": sealed_source.WORKSPACE_ID,
                        "exact_inventory_kind": "synthetic_exact_inventory",
                    }
                )

    def test_sealed_package_builds_existing_session_graph_and_gateway_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = _prepare_package(root)
            loaded = sealed_source.load_issue56_sealed_source(**_loader_kwargs(package))

            self.assertEqual(len(loaded.observations), 456)
            self.assertEqual(loaded.index.authorized_bundle_count, 1)
            self.assertEqual(loaded.index.denied_bundle_count, 0)
            self.assertEqual(
                loaded.graph_build.graph_policy_id,
                sealed_source.SOURCE_GRAPH_POLICY_ID,
            )
            self.assertEqual(
                loaded.graph_build.identifier_mention_count,
                loaded.identifier_mention_batch.occurrence_count,
            )
            self.assertGreater(loaded.graph_build.edge_count, 0)
            self.assertEqual(
                loaded.safe_binding["counts"]["selected_observation_count"],
                456,
            )
            self.assertEqual(
                loaded.safe_binding["counts"]["authorized_observation_count"],
                456,
            )
            self.assertEqual(loaded.safe_binding["counts"]["overflow_count"], 0)
            precompute = loaded.safe_binding["lineage_crosswalk_precompute"]
            self.assertEqual(precompute["status"], "passed")
            self.assertEqual(precompute["cache_status"], "primed")
            self.assertEqual(precompute["helper_invocation_count"], 1)
            self.assertGreaterEqual(precompute["elapsed_ms"], 0)
            self.assertEqual(
                precompute["index_fingerprint"],
                loaded.safe_binding["index_fingerprint"],
            )
            self.assertEqual(
                precompute["graph_revision_fingerprint"],
                loaded.safe_binding["graph_revision_fingerprint"],
            )
            self.assertEqual(
                precompute["source_session_binding_fingerprint"],
                loaded.session.source_session_binding_fingerprint,
            )
            relation_precompute = loaded.safe_binding["relation_projection_base_precompute"]
            self.assertEqual(relation_precompute["status"], "passed")
            self.assertEqual(relation_precompute["cache_status"], "primed")
            self.assertEqual(relation_precompute["helper_invocation_count"], 1)
            self.assertGreaterEqual(relation_precompute["elapsed_ms"], 0)
            self.assertEqual(
                relation_precompute["index_fingerprint"],
                loaded.safe_binding["index_fingerprint"],
            )
            self.assertEqual(
                relation_precompute["graph_revision_fingerprint"],
                loaded.safe_binding["graph_revision_fingerprint"],
            )

            rendered_safe = json.dumps(
                dict(loaded.safe_binding),
                ensure_ascii=True,
                sort_keys=True,
            )
            self.assertNotIn(str(root), rendered_safe)
            self.assertNotIn("CASE-", rendered_safe)
            self.assertNotIn("obs_body_", rendered_safe)
            self.assertNotIn('"tenant_id"', rendered_safe)

            environment = _loader_environment(package)
            resolved = diagnostic_cli.resolve_sealed_source_loader(gateway_loader.LOADER_SPEC)
            self.assertIs(
                resolved,
                gateway_loader.load_issue56_sealed_source_diagnostic_input,
            )
            with (
                mock.patch.dict(os.environ, environment, clear=False),
                mock.patch.object(
                    gateway_loader,
                    "load_issue56_sealed_source",
                    return_value=loaded,
                ) as core_loader,
            ):
                diagnostic_input = resolved()
            core_loader.assert_called_once()
            self.assertIsInstance(
                diagnostic_input,
                Issue56SealedSourceDiagnosticInput,
            )
            self.assertEqual(diagnostic_input.observation_count, 456)
            self.assertEqual(
                diagnostic_input.loader_contract_fingerprint,
                gateway_loader.LOADER_CONTRACT_FINGERPRINT,
            )
            self.assertEqual(
                diagnostic_input.lineage_crosswalk_precompute.crosswalk_fingerprint,
                precompute["crosswalk_fingerprint"],
            )
            self.assertEqual(
                diagnostic_input.lineage_crosswalk_precompute.helper_invocation_count,
                1,
            )
            self.assertEqual(
                diagnostic_input.relation_projection_base_precompute.precompute_fingerprint,
                relation_precompute["precompute_fingerprint"],
            )
            self.assertEqual(
                diagnostic_input.relation_projection_base_precompute.helper_invocation_count,
                1,
            )
            self.assertTrue(diagnostic_input.allowed_relation_types)

            expanded = sealed_source.load_issue56_sealed_source(
                **_loader_kwargs(package),
                include_participant_authorization_observations=True,
            )
            selected_hashes = tuple(
                sorted(
                    (
                        observation.observation_id,
                        sha256_json(observation.to_dict()),
                    )
                    for observation in expanded.observations
                )
            )
            self.assertEqual(expanded.session.retrieval_observation_hashes, selected_hashes)
            self.assertTrue(
                set(selected_hashes).issubset(
                    set(expanded.session.authorized_observation_hashes)
                )
            )
            self.assertEqual(
                expanded.safe_binding["counts"]["selected_observation_count"],
                len(expanded.observations),
            )
            self.assertGreater(
                expanded.safe_binding["counts"]["authorized_observation_count"],
                len(expanded.observations),
            )
            self.assertEqual(
                expanded.safe_binding["counts"]["graph_source_observation_count"],
                len(expanded.observations),
            )

    def test_gateway_rejects_owner_precompute_safe_binding_drift(self) -> None:
        index_fingerprint = sha256_json("index")
        graph_revision_fingerprint = sha256_json("graph")
        source_session_binding_fingerprint = sha256_json("authorized source set")
        tokenizer_profile_fingerprint = sha256_json("tokenizer")
        relation_counts = {
            "authorized_observation_count": 1,
            "candidate_count": 1,
            "projected_node_count": 2,
            "observation_bound_node_group_count": 1,
            "adjacency_node_count": 2,
            "adjacency_transition_count": 2,
            "authorized_index_vocabulary_hash_count": 1,
            "authorized_graph_vocabulary_hash_count": 1,
        }
        relation_payload = {
            "cache_binding_fingerprint": sha256_json("cache"),
            "graph_revision_fingerprint": graph_revision_fingerprint,
            "index_fingerprint": index_fingerprint,
            "tokenizer_profile_fingerprint": tokenizer_profile_fingerprint,
            "authorized_observation_set_fingerprint": sha256_json("authorized"),
            "candidate_set_fingerprint": sha256_json("candidates"),
            **relation_counts,
        }
        binding = {
            "status": "passed",
            "identity_scope_mode_status": sealed_source.IDENTITY_SCOPE_MODE,
            "tenant_dimension_status": "not_modeled_not_fabricated",
            "index_fingerprint": index_fingerprint,
            "graph_revision_fingerprint": graph_revision_fingerprint,
            "candidate_admission_profile_fingerprint": tokenizer_profile_fingerprint,
            "source_asset_fingerprint": sha256_json("asset"),
            "counts": {
                "authorized_observation_count": 1,
                "graph_observation_node_count": 1,
                "graph_entity_node_count": 1,
                "graph_edge_count": 1,
            },
            "lineage_crosswalk_precompute": {
                "index_fingerprint": index_fingerprint,
                "graph_revision_fingerprint": graph_revision_fingerprint,
                "source_session_binding_fingerprint": (
                    source_session_binding_fingerprint
                ),
                "cache_key_fingerprint": sha256_json(
                    {
                        "artifact_id": (
                            "formowl_issue56_evidence_identity_lineage_cache_key_v1"
                        ),
                        "index_fingerprint": index_fingerprint,
                        "graph_revision_fingerprint": graph_revision_fingerprint,
                        "source_session_binding_fingerprint": (
                            source_session_binding_fingerprint
                        ),
                    }
                ),
                "counts": {"authorized_evidence_count": 1},
            },
            "relation_projection_base_precompute": {
                "artifact_id": "formowl_issue56_relation_projection_base_precompute_v1",
                "schema_version": 1,
                "status": "passed",
                "cache_status": "primed",
                "helper_invocation_count": 1,
                "elapsed_ms": 1.0,
                "cache_binding_fingerprint": relation_payload["cache_binding_fingerprint"],
                "graph_revision_fingerprint": graph_revision_fingerprint,
                "index_fingerprint": index_fingerprint,
                "candidate_admission_profile_fingerprint": (tokenizer_profile_fingerprint),
                "authorized_observation_set_fingerprint": relation_payload[
                    "authorized_observation_set_fingerprint"
                ],
                "candidate_set_fingerprint": relation_payload["candidate_set_fingerprint"],
                "counts": relation_counts,
                "precompute_fingerprint": sha256_json(
                    {
                        "artifact_id": ("formowl_issue56_relation_projection_base_precompute_v1"),
                        **relation_payload,
                    }
                ),
            },
        }
        binding["binding_fingerprint"] = sha256_json(binding)
        gateway_loader._validated_owner_safe_binding(
            binding,
            source_session_binding_fingerprint=(
                source_session_binding_fingerprint
            ),
        )

        different_authorization_cache_key = sha256_json(
            {
                "artifact_id": (
                    "formowl_issue56_evidence_identity_lineage_cache_key_v1"
                ),
                "index_fingerprint": index_fingerprint,
                "graph_revision_fingerprint": graph_revision_fingerprint,
                "source_session_binding_fingerprint": sha256_json(
                    "different authorized source set"
                ),
            }
        )
        self.assertNotEqual(
            binding["lineage_crosswalk_precompute"]["cache_key_fingerprint"],
            different_authorization_cache_key,
        )
        wrong_cache_key = deepcopy(binding)
        wrong_cache_key["lineage_crosswalk_precompute"]["cache_key_fingerprint"] = (
            different_authorization_cache_key
        )
        wrong_cache_key["binding_fingerprint"] = sha256_json(
            {
                key: value
                for key, value in wrong_cache_key.items()
                if key != "binding_fingerprint"
            }
        )
        with self.assertRaisesRegex(
            Exception,
            "owner precompute binding mismatch",
        ):
            gateway_loader._validated_owner_safe_binding(
                wrong_cache_key,
                source_session_binding_fingerprint=(
                    source_session_binding_fingerprint
                ),
            )

        drifted = deepcopy(binding)
        drifted["lineage_crosswalk_precompute"]["graph_revision_fingerprint"] = sha256_json(
            "drifted"
        )
        with self.assertRaisesRegex(
            Exception,
            "owner safe binding seal mismatch",
        ):
            gateway_loader._validated_owner_safe_binding(
                drifted,
                source_session_binding_fingerprint=(
                    source_session_binding_fingerprint
                ),
            )

        cross_binding_drift = deepcopy(binding)
        cross_binding_drift["relation_projection_base_precompute"]["graph_revision_fingerprint"] = (
            sha256_json("different graph")
        )
        cross_binding_drift["binding_fingerprint"] = sha256_json(
            {
                key: value
                for key, value in cross_binding_drift.items()
                if key != "binding_fingerprint"
            }
        )
        with self.assertRaisesRegex(
            Exception,
            "owner relation projection precompute binding mismatch",
        ):
            gateway_loader._validated_owner_safe_binding(
                cross_binding_drift,
                source_session_binding_fingerprint=(
                    source_session_binding_fingerprint
                ),
            )

    def test_fixed_identity_mismatches_fail_before_source_loading(self) -> None:
        missing = Path("/not/read/by/fixed-identity-validation")
        base = {
            "retrieval_snapshot_path": missing,
            "expected_retrieval_snapshot_sha256": sha256_json("missing"),
            "bundle_artifact_path": missing,
            "expected_bundle_artifact_sha256": sha256_json("missing"),
            "retrieval_report_path": missing,
            "expected_retrieval_report_sha256": sha256_json("missing"),
            "materialized_work_dir": missing,
            "expected_materialization_artifact_sha256": sha256_json("missing"),
            "expected_materialization_safe_report_sha256": sha256_json("missing"),
            "identity_scope_attestation_path": missing,
            "expected_identity_scope_attestation_sha256": sha256_json("missing"),
            "identity_scope_safe_report_path": missing,
            "expected_identity_scope_safe_report_sha256": sha256_json("missing"),
            "source_identifier_candidate_artifact_path": missing,
            "expected_source_identifier_candidate_artifact_sha256": sha256_json("missing"),
            "source_identifier_candidate_safe_report_path": missing,
            "expected_source_identifier_candidate_safe_report_sha256": sha256_json("missing"),
            "expected_identity_scope_fingerprint": sha256_json("scope"),
            "identity_scope_mode": sealed_source.IDENTITY_SCOPE_MODE,
            "workspace_id": sealed_source.WORKSPACE_ID,
            "approver_actor": sealed_source.APPROVER_ACTOR,
            "requester_user_id": sealed_source.APPROVER_ACTOR,
        }
        mutations = (
            ("identity_scope_mode", "tenant_workspace_v1", "identity_scope_mode_mismatch"),
            ("workspace_id", "workspace_other", "workspace_binding_mismatch"),
            ("approver_actor", "user_other", "approver_binding_mismatch"),
            ("requester_user_id", "user_other", "requester_approver_binding_mismatch"),
        )
        for field_name, value, reason in mutations:
            with self.subTest(field_name=field_name):
                kwargs = {**base, field_name: value}
                with self.assertRaisesRegex(
                    sealed_source.Issue56SealedSourceLoadError,
                    f"^{reason}$",
                ):
                    sealed_source.load_issue56_sealed_source(**kwargs)

    def test_materialized_record_and_candidate_safe_seal_tamper_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = _prepare_package(root)
            record_path = next(
                (package.work_dir / materializer.OBSERVATION_RELATIVE_DIRECTORY).glob("*.json")
            )
            record_path.write_bytes(record_path.read_bytes() + b" ")
            with self.assertRaisesRegex(
                sealed_source.Issue56SealedSourceLoadError,
                "materialization_observation_record_byte_seal_mismatch",
            ):
                sealed_source.load_issue56_sealed_source(**_loader_kwargs(package))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = _prepare_package(root)
            safe_path = package.candidate_root / candidate_builder.SAFE_REPORT_FILENAME
            safe_path.write_bytes(safe_path.read_bytes() + b" ")
            with self.assertRaisesRegex(
                sealed_source.Issue56SealedSourceLoadError,
                "^source_identifier_candidate_safe_report_byte_seal_mismatch$",
            ):
                sealed_source.load_issue56_sealed_source(**_loader_kwargs(package))

    def test_any_tenant_id_key_is_rejected_before_candidate_use(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = _prepare_package(root)
            attestation_path = (
                package.attestation_root / identity_attestation.PRIVATE_ARTIFACT_FILENAME
            )
            private = json.loads(attestation_path.read_text(encoding="utf-8"))
            private["identity_scope"]["tenant_id"] = "forbidden"
            private["attestation_fingerprint"] = _payload_fingerprint(
                private,
                "attestation_fingerprint",
            )
            attestation_path.write_bytes(_json_bytes(private))
            kwargs = _loader_kwargs(package)
            kwargs["expected_identity_scope_attestation_sha256"] = _sha256_path(attestation_path)
            with self.assertRaisesRegex(
                sealed_source.Issue56SealedSourceLoadError,
                "^identity_scope_attestation_tenant_id_forbidden$",
            ):
                sealed_source.load_issue56_sealed_source(**kwargs)

    def test_gateway_environment_is_complete_and_never_accepts_tenant(self) -> None:
        required_names = set(gateway_loader._ENVIRONMENT_FIELDS.values())
        self.assertNotIn("FORMOWL_ISSUE56_TENANT_ID", required_names)
        self.assertTrue(all("TENANT" not in name for name in required_names))
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                Exception,
                "sealed source loader environment is incomplete",
            ):
                gateway_loader.load_issue56_sealed_source_diagnostic_input()

    def test_direct_identifier_provider_preserves_authorized_occurrence_lineage(
        self,
    ) -> None:
        shared_identifier = "CASE-7777"
        shared_identifier_hash = sha256_json(shared_identifier.casefold())
        with tempfile.TemporaryDirectory() as temp_dir:
            package = _prepare_package(
                Path(temp_dir),
                shared_direct_identifier=shared_identifier,
            )
            loaded = sealed_source.load_issue56_sealed_source(
                **_loader_kwargs(package),
                include_participant_authorization_observations=True,
            )
            matching_mentions = tuple(
                mention
                for mention in loaded.identifier_mention_batch.candidate_mentions
                if mention.normalized_label == shared_identifier_hash
            )
            source_occurrence_count = sum(
                observation.text is not None
                and shared_identifier.casefold() in observation.text.casefold()
                for observation in (
                    Observation.from_dict(row)
                    for row in package.fixture.snapshot["parsed_mail_observations"]
                )
            )
            self.assertGreater(source_occurrence_count, len(matching_mentions))

            with mock.patch.dict(
                os.environ,
                _loader_environment(package),
                clear=False,
            ):
                providers = gateway_loader._build_mail_source_occurrence_providers(
                    loaded,
                    safe_binding=loaded.safe_binding,
                )
            matching_providers = tuple(
                provider
                for provider in providers
                if any(
                    shared_identifier_hash in binding[:2]
                    for occurrence in provider.occurrences
                    for binding in occurrence.value_bindings
                )
            )
            direct_identifier_providers = tuple(
                provider
                for provider in providers
                if provider.provider_id
                == "mail_message_occurrence_direct_source_identifier_provider_v1"
            )
            self.assertEqual(len(direct_identifier_providers), 1)
            self.assertEqual(len(matching_providers), 1)
            provider = matching_providers[0]
            self.assertIs(provider, direct_identifier_providers[0])
            authorized_hash_by_id = dict(loaded.session.authorized_observation_hashes)
            lineage_by_id = {
                lineage.source_observation_id: lineage
                for lineage in loaded.session.occurrence_lineages
            }
            retrieval_occurrence_ids = {
                lineage_by_id[observation_id].occurrence_id
                for observation_id, _ in loaded.session.retrieval_observation_hashes
            }
            authorized_occurrence_ids = {
                lineage.occurrence_id for lineage in loaded.session.occurrence_lineages
            }
            projected_occurrence_ids = {
                lineage_by_id[observation_id].occurrence_id
                for mention in loaded.identifier_mention_batch.candidate_mentions
                if mention.mention_type == "protected_identifier:business_identifier"
                for observation_id in mention.source_observation_ids
            }
            self.assertLess(
                len(retrieval_occurrence_ids),
                len(authorized_occurrence_ids),
            )
            self.assertEqual(
                authorized_occurrence_ids,
                {
                    occurrence.message_occurrence_id
                    for occurrence in loaded.source_bundle.message_occurrences
                },
            )
            self.assertEqual(
                provider.unresolved_count,
                len(authorized_occurrence_ids - projected_occurrence_ids),
            )
            expected_references = {
                (
                    authorized_hash_by_id[observation_id],
                    lineage_by_id[observation_id].lineage_fingerprint,
                )
                for mention in matching_mentions
                for observation_id in mention.source_observation_ids
            }
            actual_references = {
                (citation_hash, lineage_fingerprint)
                for occurrence in provider.occurrences
                for (
                    normalized_hash,
                    variant_hash,
                    citation_hash,
                    lineage_fingerprint,
                ) in occurrence.value_bindings
                if shared_identifier_hash in {normalized_hash, variant_hash}
            }
            self.assertEqual(actual_references, expected_references)
            self.assertEqual(
                sum(
                    any(shared_identifier_hash in binding[:2] for binding in occurrence.value_bindings)
                    for occurrence in provider.occurrences
                ),
                len(matching_mentions),
            )

            routed_session = replace(
                loaded.session,
                source_occurrence_providers=providers,
            )
            cursor = None
            while True:
                result = routed_session.query(
                    query_text=f"list all {shared_identifier} messages",
                    effective_graph_view=loaded.effective_graph_view,
                    exact_inventory_kind="mail_message_occurrence",
                    exact_field="message_occurrence.direct_source_identifier_v1",
                    page_size=100,
                    cursor=cursor,
                )
                assert result.exact_result is not None
                page = result.exact_result.source_occurrence_page
                assert page is not None
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            self.assertEqual(result.status, "incomplete")
            self.assertEqual(page["coverage_status"], "incomplete")
            self.assertGreater(page["unresolved_count"], 0)

            source_observation = next(
                observation
                for observation in loaded.session.authorized_observations
                if observation.observation_type == "email_message"
            )
            extra_occurrence_id = (
                str(source_observation.location["message_occurrence_id"])
                + "_authorization_only"
            )
            extra_payload = dict(source_observation.payload or {})
            extra_payload["message_occurrence_id"] = extra_occurrence_id
            extra_payload["message_fingerprint"] = sha256_json(extra_occurrence_id)
            extra_location = dict(source_observation.location)
            extra_location["message_occurrence_id"] = extra_occurrence_id
            extra_observation = Observation.from_dict(
                {
                    **source_observation.to_dict(),
                    "observation_id": (
                        source_observation.observation_id + "_authorization_only"
                    ),
                    "location": extra_location,
                    "payload": extra_payload,
                }
            )
            assert loaded.session.authorized_source is not None
            extra_lineage = source_occurrence_lineage_from_observation(
                extra_observation,
                authorized_source=loaded.session.authorized_source,
            )
            extra_observation_hash = sha256_json(extra_observation.to_dict())
            expanded_session = replace(
                loaded.session,
                authorized_observations=tuple(
                    sorted(
                        (*loaded.session.authorized_observations, extra_observation),
                        key=lambda observation: observation.observation_id,
                    )
                ),
                authorized_observation_hashes=tuple(
                    sorted(
                        (
                            *loaded.session.authorized_observation_hashes,
                            (extra_observation.observation_id, extra_observation_hash),
                        )
                    )
                ),
                occurrence_lineages=tuple(
                    sorted(
                        (*loaded.session.occurrence_lineages, extra_lineage),
                        key=lambda lineage: lineage.source_observation_id,
                    )
                ),
            )
            with mock.patch.dict(
                os.environ,
                _loader_environment(package),
                clear=False,
            ):
                with self.assertRaisesRegex(
                    Exception,
                    "production direct source identifier occurrence scope is invalid",
                ):
                    gateway_loader._build_mail_source_occurrence_providers(
                        replace(loaded, session=expanded_session),
                        safe_binding=loaded.safe_binding,
                    )

    def test_participant_mailbox_lists_are_strict_and_partitioned(self) -> None:
        headers = {
            1: {
                "from": '"Display, One" <alpha@example.invalid>, beta@example.invalid',
                "sender": "Sender Person <sender@example.invalid>",
                "to": "Team: gamma@example.invalid, delta@example.invalid;",
                "cc": "Copy Person <copy@example.invalid>",
            },
            2: {
                "from": "clean@example.invalid",
                "to": "valid@example.invalid, not-an-address",
            },
            3: {"from": "nonmatch@example.invalid"},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            package = _prepare_package(
                Path(temp_dir),
                participant_headers=headers,
            )
            loaded = sealed_source.load_issue56_sealed_source(
                **_loader_kwargs(package),
                include_participant_authorization_observations=True,
            )
            with mock.patch.dict(
                os.environ,
                _loader_environment(package),
                clear=False,
            ):
                providers = gateway_loader._build_mail_source_occurrence_providers(
                    loaded,
                    safe_binding=loaded.safe_binding,
                )

            participants = {
                provider.normalized_field: provider
                for provider in providers
                if provider.provider_id == "mail_source_occurrence_provider_v1"
            }
            authorized_count = len(
                {lineage.occurrence_id for lineage in loaded.session.occurrence_lineages}
            )
            for provider in participants.values():
                self.assertEqual(
                    len(provider.occurrences) + provider.unresolved_count,
                    authorized_count,
                )
            expected_addresses_by_field = {
                "participant.from.local_part": {
                    "alpha@example.invalid",
                    "beta@example.invalid",
                },
                "participant.sender.local_part": {"sender@example.invalid"},
                "participant.to.local_part": {
                    "gamma@example.invalid",
                    "delta@example.invalid",
                },
                "participant.cc.local_part": {"copy@example.invalid"},
            }
            authorized_by_hash = {
                sha256_json(observation.to_dict()): observation
                for observation in loaded.session.authorized_observations
            }
            for field, expected_addresses in expected_addresses_by_field.items():
                expected_hashes = {sha256_json(address) for address in expected_addresses}
                matching_bindings = {
                    binding
                    for occurrence in participants[field].occurrences
                    for binding in occurrence.value_bindings
                    if binding[1] in expected_hashes
                }
                self.assertEqual(
                    {binding[1] for binding in matching_bindings},
                    expected_hashes,
                )
                for _, _, citation_hash, lineage_fingerprint in matching_bindings:
                    observation = authorized_by_hash[citation_hash]
                    lineage = source_occurrence_lineage_from_observation(
                        observation,
                        authorized_source=loaded.session.authorized_source,
                    )
                    self.assertEqual(
                        lineage.occurrence_id,
                        "message_occurrence_0001",
                    )
                    self.assertEqual(
                        lineage.lineage_fingerprint,
                        lineage_fingerprint,
                    )
            hashes_by_field = {
                field: {
                    value_hash
                    for occurrence in provider.occurrences
                    for binding in occurrence.value_bindings
                    for value_hash in binding[:2]
                }
                for field, provider in participants.items()
            }
            clean_hash = sha256_json("clean@example.invalid")
            malformed_partial_hash = sha256_json("valid@example.invalid")
            self.assertIn(clean_hash, hashes_by_field["participant.from.local_part"])
            self.assertNotIn(clean_hash, hashes_by_field["participant.any.local_part"])
            self.assertNotIn(
                malformed_partial_hash,
                hashes_by_field["participant.to.local_part"],
            )
            self.assertNotIn(
                malformed_partial_hash,
                hashes_by_field["participant.any.local_part"],
            )
            self.assertIn(
                sha256_json("nonmatch@example.invalid"),
                hashes_by_field["participant.from.local_part"],
            )
            self.assertNotIn(
                sha256_json("display, one"),
                hashes_by_field["participant.from.local_part"],
            )
            self.assertNotIn(
                sha256_json("team"),
                hashes_by_field["participant.to.local_part"],
            )



def _prepare_package(
    root: Path,
    *,
    shared_direct_identifier: str | None = None,
    participant_headers: dict[int, dict[str, str]] | None = None,
) -> _PreparedPackage:
    fixture = _write_workspace_fixture(
        root / "source",
        shared_direct_identifier=shared_direct_identifier,
        participant_headers=participant_headers,
    )
    work_dir = root / "materialized"
    materialized = materializer.materialize_development_uat_observations(
        **materializer_fixture._build_kwargs(fixture, work_dir)
    )
    materialization_private_sha256 = _sha256_path(materialized.private_artifact_path)
    materialization_safe_sha256 = _sha256_path(materialized.safe_report_path)

    snapshot = fixture.snapshot
    attestation_root = root / "identity"
    _, safe_attestation = identity_attestation.create_identity_scope_attestation_artifacts(
        output_root=attestation_root,
        mode=identity_attestation.WORKSPACE_ONLY_MODE,
        workspace_id=sealed_source.WORKSPACE_ID,
        tenant_id=None,
        asset_id=snapshot["source_inventory"]["source_asset_id"],
        asset_content_hash=snapshot["source_asset_sha256"],
        source_fingerprint=snapshot["source_snapshot_fingerprint"],
        permission_fingerprint=snapshot["permission_fingerprint"],
        approver_actor=sealed_source.APPROVER_ACTOR,
        authority_source="issue56_fixture_explicit_operator_approval",
        approved_at=CREATED_AT,
        reason="Synthetic sealed-source loader contract fixture approval.",
        operator_approved=True,
        spec_approval_id="issue56_fixture_workspace_only_spec_approval",
    )
    attestation_private_path = attestation_root / identity_attestation.PRIVATE_ARTIFACT_FILENAME
    attestation_safe_path = attestation_root / identity_attestation.SAFE_REPORT_FILENAME

    candidate_root = root / "candidates"
    candidates = candidate_builder.build_source_identifier_candidate_artifacts(
        retrieval_snapshot_path=fixture.snapshot_path,
        expected_retrieval_snapshot_sha256=fixture.snapshot_sha256,
        retrieval_report_path=fixture.report_path,
        expected_retrieval_report_sha256=fixture.report_sha256,
        identity_scope_attestation_path=attestation_private_path,
        expected_identity_scope_attestation_sha256=_sha256_path(attestation_private_path),
        materialized_work_dir=work_dir,
        expected_materialization_artifact_sha256=(materialization_private_sha256),
        expected_materialization_safe_report_sha256=(materialization_safe_sha256),
        output_root=candidate_root,
    )
    return _PreparedPackage(
        fixture=fixture,
        work_dir=work_dir,
        materialization_private_sha256=materialization_private_sha256,
        materialization_safe_sha256=materialization_safe_sha256,
        attestation_root=attestation_root,
        attestation_private_sha256=_sha256_path(attestation_private_path),
        attestation_safe_sha256=_sha256_path(attestation_safe_path),
        identity_scope_fingerprint=safe_attestation["identity_scope_fingerprint"],
        candidate_root=candidate_root,
        candidate_private_sha256=_sha256_path(candidates.private_artifact_path),
        candidate_safe_sha256=_sha256_path(candidates.safe_report_path),
    )


def _write_workspace_fixture(
    root: Path,
    *,
    shared_direct_identifier: str | None = None,
    participant_headers: dict[int, dict[str, str]] | None = None,
) -> object:
    fixture = materializer_fixture._write_fixture(root, body_count=500)
    snapshot = deepcopy(fixture.snapshot)
    manifest = deepcopy(fixture.manifest)
    old_inventory = SourceInventory.from_dict(snapshot["source_inventory"])
    item_id_map: dict[str, str] = {}
    new_items: list[SourceInventoryItem] = []
    for old_item in old_inventory.items:
        new_item = SourceInventoryItem.create(
            source_asset_id=old_item.source_asset_id,
            structure_kind=old_item.structure_kind,
            content_type=old_item.content_type,
            ordinal=old_item.ordinal,
            processing_state=old_item.processing_state,
            raw_retention_state=old_item.raw_retention_state,
            source_fingerprint=old_item.source_fingerprint,
            parser_fingerprint=old_item.parser_fingerprint,
            permission_scope=WORKSPACE_PERMISSION_SCOPE.to_dict(),
            location=old_item.location,
        )
        item_id_map[old_item.source_inventory_item_id] = new_item.source_inventory_item_id
        new_items.append(new_item)
    new_inventory = SourceInventory.create(
        source_asset_id=old_inventory.source_asset_id,
        items=new_items,
        source_fingerprint=old_inventory.source_fingerprint,
        parser_fingerprint=old_inventory.parser_fingerprint,
        created_at=old_inventory.created_at,
    )

    observations: list[Observation] = []
    for raw_observation in snapshot["parsed_mail_observations"]:
        row = deepcopy(raw_observation)
        if shared_direct_identifier is not None and row["observation_type"] == "email_body_segment":
            ordinal = int(str(row["observation_id"]).rsplit("_", 1)[1])
            if ordinal == 1 or ordinal > 200:
                row["text"] = (
                    f"Synthetic evidence segment {ordinal:04d} "
                    f"references {shared_direct_identifier}."
                )
        row["permission_scope"] = WORKSPACE_PERMISSION_SCOPE.to_dict()
        row["location"]["source_inventory_item_id"] = item_id_map[
            row["location"]["source_inventory_item_id"]
        ]
        observations.append(Observation.from_dict(row))
    message_by_ordinal = {
        int(observation.observation_id.rsplit("_", 1)[1]): observation
        for observation in observations
        if observation.observation_type == "email_message"
    }
    for ordinal, headers in sorted((participant_headers or {}).items()):
        message = message_by_ordinal[ordinal]
        for header_index, (header_name, header_value) in enumerate(
            sorted(headers.items()),
            start=1,
        ):
            location = {
                **message.location,
                "header_index": header_index,
                "header_name": header_name,
            }
            observations.append(
                Observation.from_dict(
                    {
                        "observation_id": (
                            f"obs_participant_header_{ordinal:04d}_{header_index:02d}"
                        ),
                        "asset_id": message.asset_id,
                        "extractor_run_id": message.extractor_run_id,
                        "observation_type": "email_header",
                        "modality": "mail",
                        "location": location,
                        "text": f"{header_name}: {header_value}",
                        "payload": {
                            **location,
                            "header_name": header_name,
                            "header_value": header_value,
                            "message_fingerprint": (message.payload or {})[
                                "message_fingerprint"
                            ],
                            "canonical_fact_status": "not_asserted",
                        },
                        "confidence": 1.0,
                        "permission_scope": message.permission_scope,
                        "created_at": CREATED_AT,
                    }
                )
            )

    bundle = build_mail_evidence_bundle(
        observations,
        workspace_id=sealed_source.WORKSPACE_ID,
        owner_user_id=sealed_source.APPROVER_ACTOR,
        source_asset_id=old_inventory.source_asset_id,
        archive_sha256=snapshot["source_asset_sha256"],
        producer_type="server_side_parser",
        parser_name="fixture_parser",
        parser_version="1",
        upload_session_id="upload_issue56_sealed_source_loader",
        created_at=materializer_fixture.CREATED_AT,
        started_at=materializer_fixture.CREATED_AT,
        completed_at=materializer_fixture.CREATED_AT,
    )
    bundle_payload = bundle.to_dict()
    bundle_artifact = {
        "artifact_id": "formowl_issue56_native_mail_evidence_bundle_v1",
        "schema_version": 1,
        "status": "passed",
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": sha256_json(new_inventory.to_dict()),
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "bundle": bundle_payload,
        "bundle_fingerprint": sha256_json(bundle_payload),
    }
    bundle_artifact["artifact_fingerprint"] = _payload_fingerprint(
        bundle_artifact,
        "artifact_fingerprint",
    )

    snapshot["source_inventory"] = new_inventory.to_dict()
    snapshot["source_inventory_fingerprint"] = sha256_json(new_inventory.to_dict())
    snapshot["permission_fingerprint"] = sha256_json(WORKSPACE_PERMISSION_SCOPE.to_dict())
    snapshot["parsed_mail_observations"] = [observation.to_dict() for observation in observations]
    added_header_count = len(observations) - len(
        fixture.snapshot["parsed_mail_observations"]
    )
    snapshot["counts"]["parsed_header_observation_count"] += added_header_count
    snapshot["counts"]["parsed_observation_count"] += added_header_count
    snapshot["counts"]["retrieval_snapshot_observation_count"] += added_header_count
    snapshot["parsed_observation_fingerprint"] = sha256_json(snapshot["parsed_mail_observations"])
    snapshot["mail_evidence_bundle_fingerprint"] = bundle_artifact["bundle_fingerprint"]
    snapshot["snapshot_fingerprint"] = _payload_fingerprint(
        snapshot,
        "snapshot_fingerprint",
    )

    report = deepcopy(fixture.retrieval_report)
    report["counts"] = deepcopy(snapshot["counts"])
    report_bindings = {
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "parsed_observation_fingerprint": snapshot["parsed_observation_fingerprint"],
        "mail_evidence_bundle_fingerprint": bundle_artifact["bundle_fingerprint"],
        "candidate_admission_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
    }
    report.update(report_bindings)
    report["report_fingerprint"] = _payload_fingerprint(
        report,
        "report_fingerprint",
    )

    observation_by_id = {observation.observation_id: observation for observation in observations}
    for case in manifest["cases"]:
        case["requester_user_id"] = sealed_source.APPROVER_ACTOR
        selected = [
            observation_by_id[observation_id]
            for observation_id in case["required_source_observation_ids"]
        ]
        case["source_evidence_binding"]["required_observation_hashes"] = sorted(
            sha256_json(observation.to_dict()) for observation in selected
        )
        case["private_fingerprint"] = _payload_fingerprint(
            case,
            "private_fingerprint",
        )

    snapshot_bytes = _json_bytes(snapshot)
    bundle_bytes = _json_bytes(bundle_artifact)
    report_bytes = _json_bytes(report)
    manifest["mail_evidence_bundle_id"] = bundle.mail_evidence_bundle_id
    manifest["mail_import_session_id"] = bundle.mail_import_session.mail_import_session_id
    manifest["archive_sha256"] = bundle.mail_import_session.archive_sha256
    manifest["source_bindings"].update(
        {
            "bundle_artifact_byte_hash": _sha256_bytes(bundle_bytes),
            "bundle_artifact_fingerprint": bundle_artifact["artifact_fingerprint"],
            "mail_evidence_bundle_fingerprint": bundle_artifact["bundle_fingerprint"],
            "retrieval_snapshot_byte_hash": _sha256_bytes(snapshot_bytes),
            "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
            "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
            "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
            "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
            "permission_fingerprint": snapshot["permission_fingerprint"],
            "tokenizer_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
            "index_fingerprint": snapshot["index_fingerprint"],
            "retrieval_report_byte_hash": _sha256_bytes(report_bytes),
        }
    )
    manifest["manifest_fingerprint"] = _payload_fingerprint(
        manifest,
        "manifest_fingerprint",
    )
    fixture.snapshot_path.write_bytes(snapshot_bytes)
    fixture.bundle_path.write_bytes(bundle_bytes)
    fixture.report_path.write_bytes(report_bytes)
    fixture.manifest_path.write_bytes(_json_bytes(manifest))
    return materializer_fixture._Fixture(
        snapshot_path=fixture.snapshot_path,
        bundle_path=fixture.bundle_path,
        report_path=fixture.report_path,
        manifest_path=fixture.manifest_path,
        snapshot=snapshot,
        bundle_artifact=bundle_artifact,
        retrieval_report=report,
        manifest=manifest,
    )


def _loader_kwargs(package: _PreparedPackage) -> dict[str, object]:
    fixture = package.fixture
    return {
        "retrieval_snapshot_path": fixture.snapshot_path,
        "expected_retrieval_snapshot_sha256": fixture.snapshot_sha256,
        "bundle_artifact_path": fixture.bundle_path,
        "expected_bundle_artifact_sha256": fixture.bundle_sha256,
        "retrieval_report_path": fixture.report_path,
        "expected_retrieval_report_sha256": fixture.report_sha256,
        "materialized_work_dir": package.work_dir,
        "expected_materialization_artifact_sha256": (package.materialization_private_sha256),
        "expected_materialization_safe_report_sha256": (package.materialization_safe_sha256),
        "identity_scope_attestation_path": (
            package.attestation_root / identity_attestation.PRIVATE_ARTIFACT_FILENAME
        ),
        "expected_identity_scope_attestation_sha256": (package.attestation_private_sha256),
        "identity_scope_safe_report_path": (
            package.attestation_root / identity_attestation.SAFE_REPORT_FILENAME
        ),
        "expected_identity_scope_safe_report_sha256": (package.attestation_safe_sha256),
        "source_identifier_candidate_artifact_path": (
            package.candidate_root / candidate_builder.PRIVATE_ARTIFACT_FILENAME
        ),
        "expected_source_identifier_candidate_artifact_sha256": (package.candidate_private_sha256),
        "source_identifier_candidate_safe_report_path": (
            package.candidate_root / candidate_builder.SAFE_REPORT_FILENAME
        ),
        "expected_source_identifier_candidate_safe_report_sha256": (package.candidate_safe_sha256),
        "expected_identity_scope_fingerprint": (package.identity_scope_fingerprint),
        "identity_scope_mode": sealed_source.IDENTITY_SCOPE_MODE,
        "workspace_id": sealed_source.WORKSPACE_ID,
        "approver_actor": sealed_source.APPROVER_ACTOR,
        "requester_user_id": sealed_source.APPROVER_ACTOR,
    }


def _loader_environment(package: _PreparedPackage) -> dict[str, str]:
    kwargs = _loader_kwargs(package)
    return {
        environment_name: str(kwargs[field_name])
        for field_name, environment_name in gateway_loader._ENVIRONMENT_FIELDS.items()
    }


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _payload_fingerprint(
    payload: dict[str, object],
    fingerprint_field: str,
) -> str:
    return sha256_json({key: value for key, value in payload.items() if key != fingerprint_field})


def _sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())




class CandidateFactPartialVerificationTests(unittest.TestCase):
    def _bound(self, root, *, subject=False):
        from test_issue56_uat_handler_composition import CandidateFactRuntimeTests
        revision, config, digest, _, observations = CandidateFactRuntimeTests()._fixture(
            root, subject_only=subject, filler_count=0, fixture_code="code019")
        return sealed_source.bind_issue56_candidate_fact_exports(
            revision, configuration_path=config, expected_sha256=digest), observations

    @staticmethod
    def _arguments():
        return {"query_text": "ZX-742 target date", "required_terms": ["ZX-742"],
                "requester_user_id": gateway_loader.APPROVER_ACTOR,
                "workspace_id": gateway_loader.WORKSPACE_ID,
                "session_id": "rc19-fictional-007", "page_size": 10}

    def _run(self, bound, *, allowed=None, clock=None, turn_deadline=None, drop_table=False):
        from contextlib import ExitStack
        from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
        original = bound.source_records.scan_authorized_observations
        def scan(**kwargs):
            if kwargs.get("preferred_observation_hashes"):
                callback = kwargs["observation_callback"]
                def filtered(observation, scope):
                    if allowed is None or sha256_json(observation.to_dict()) in allowed:
                        return callback(observation, scope)
                    return True
                kwargs["observation_callback"] = filtered
            return original(**kwargs)
        trace = _SourcePhaseTrace({})
        with ExitStack() as stack:
            stack.enter_context(_source_phase_trace_scope(trace))
            if allowed is not None:
                stack.enter_context(mock.patch.object(bound.source_records, "scan_authorized_observations", side_effect=scan))
            if clock is not None:
                stack.enter_context(mock.patch.object(gateway_loader.time, "monotonic", side_effect=lambda: clock[0]))
                token = gateway_loader._SOURCE_EVIDENCE_DEADLINE.set(turn_deadline)
                stack.callback(gateway_loader._SOURCE_EVIDENCE_DEADLINE.reset, token)
                def expire_after_verified(**kwargs):
                    if kwargs.get("preferred_observation_hashes"):
                        # One real source passes the actual projection/guard callback.
                        first = clock[2]
                        kwargs["observation_callback"](first, clock[3])
                        clock[0] = clock[1]
                        raise gateway_loader._SourceEvidenceDeadlineExceeded()
                    return original(**kwargs)
                stack.enter_context(mock.patch.object(bound.source_records, "scan_authorized_observations", side_effect=expire_after_verified))
            if drop_table:
                from formowl_mail import human_uat_orchestrator
                compact = human_uat_orchestrator.compact_evidence_for_model
                def without_table(payload, **kwargs):
                    payload = compact(payload, **kwargs)
                    return {**payload, "evidence": [item for item in payload.get("evidence", ())
                            if item.get("source_type") != "candidate_fact_table"]}
                stack.enter_context(mock.patch.object(human_uat_orchestrator, "compact_evidence_for_model", side_effect=without_table))
            result = gateway_loader._build_source_start_semantic_handler(bound, mail_tool=False)(self._arguments())
        tables = [item for item in result.get("evidence", ()) if item.get("source_type") == "candidate_fact_table"]
        details = json.loads(trace.snapshot())["details"]
        status = next((item for item in details if item.get("candidate_fact_status")), {})
        flags = status["pre_group_reason_flags"]
        self.assertEqual(set(flags), {
            "deadline_before_hydration", "deadline_during_hydration", "source_admission_rejected",
            "projection_incomplete", "source_limit", "all_sources_verified", "presentation_deadline"})
        self.assertTrue(all(type(value) is bool for value in flags.values()))
        self.assertEqual(sum(flags.values()), 1)
        return result, tables, status

    def test_partial_verification_has_whole_rows_and_disclosure(self):
        with tempfile.TemporaryDirectory() as directory:
            bound, observations = self._bound(Path(directory))
            result, tables, status = self._run(bound, allowed={sha256_json(observations[0].to_dict())})
            self.assertEqual(len(tables), 1)
            display = json.loads(tables[0]["snippet"].split("\n", 1)[1])
            self.assertEqual([row["item"] for row in display["rows"]], ["0"])
            self.assertIn("Shown 1 of 2", display["disclosure"])
            self.assertIn("withheld", display["disclosure"])
            self.assertEqual(result["coverage"]["status"], "incomplete")
            self.assertEqual(status["selected_row_count"], 2)
            self.assertEqual(status["admitted_row_count"], 1)
            self.assertEqual(status["fitted_row_count"], 1)
            self.assertEqual(status["shown_row_count"], 1)
            # Optional native fallback applies a mail permission guard to
            # these withheld non-native targets before checking their type.
            self.assertEqual(next(key for key, value in status["pre_group_reason_flags"].items() if value), "source_admission_rejected")
            self.assertEqual(status["rejected_row_count"], 0)
            from formowl_mail.human_uat_orchestrator import evidence_citation_ids
            self.assertTrue(set(tables[0]["source_context"]["required_citation_hashes"]).issubset(evidence_citation_ids(result)))

    def test_rejected_source_row_does_not_suppress_independent_valid_row(self):
        with tempfile.TemporaryDirectory() as directory:
            bound, _ = self._bound(Path(directory))
            rows = deepcopy(list(bound.candidate_fact_rows))
            rows[1]["fields"]["target_date"][0]["evidence_spans"][0]["quote"] = "invalid-019"
            result, tables, status = self._run(replace(bound, candidate_fact_rows=tuple(rows)))
            self.assertEqual(len(tables), 1)
            display = json.loads(tables[0]["snippet"].split("\n", 1)[1])
            self.assertEqual([row["item"] for row in display["rows"]], ["0"])
            self.assertNotIn("invalid-019", json.dumps(result))
            self.assertEqual(status["rejected_row_count"], 1)
            self.assertEqual(next(key for key, value in status["pre_group_reason_flags"].items() if value), "source_admission_rejected")

    def test_all_verified_preserves_rows_values_and_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            bound, observations = self._bound(Path(directory))
            result, tables, status = self._run(bound)
            self.assertEqual(len(tables), 1)
            display = json.loads(tables[0]["snippet"].split("\n", 1)[1])
            self.assertEqual([row["item"] for row in display["rows"]], ["0", "1"])
            self.assertNotIn("disclosure", display)
            self.assertEqual(set(result["citations"]), {sha256_json(o.to_dict()) for o in observations})
            self.assertEqual(status["selected_row_count"], status["admitted_row_count"])
            self.assertEqual(status["fitted_row_count"], status["shown_row_count"])

    def test_none_verified_declines(self):
        with tempfile.TemporaryDirectory() as directory:
            bound, _ = self._bound(Path(directory))
            _, tables, status = self._run(bound, allowed=set())
            self.assertFalse(tables)
            self.assertEqual(status["admitted_row_count"], 0)
            self.assertEqual(status["shown_row_count"], 0)
            self.assertEqual(status["rejected_row_count"], 0)  # Hidden scanner subcause is unknown.
            with mock.patch.object(gateway_loader, "authorized_permission_scope_matches", return_value=False):
                _, denied, denied_status = self._run(bound)
            self.assertFalse(denied)
            self.assertEqual(denied_status["rejected_row_count"], 2)

    def test_subject_identity_is_part_of_whole_row_source_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            bound, observations = self._bound(Path(directory), subject=True)
            arguments = self._arguments()
            arguments["required_terms"] = ["ZX-007"]
            with mock.patch.object(self, "_arguments", return_value=arguments):
                _, missing, _ = self._run(bound, allowed={sha256_json(observations[0].to_dict())})
                self.assertFalse(missing)
                _, tables, _ = self._run(bound, allowed={sha256_json(observations[0].to_dict()), sha256_json(observations[3].to_dict())})
            self.assertEqual(len(tables), 1)
            display = json.loads(tables[0]["snippet"].split("\n", 1)[1])
            self.assertEqual(len(display["rows"]), 1)
            self.assertIn("subject", display["rows"][0])

    def test_source_expiry_uses_only_existing_absolute_presentation_window(self):
        for expired in (False, True):
            with self.subTest(absolute_expired=expired), tempfile.TemporaryDirectory() as directory:
                bound, observations = self._bound(Path(directory))
                scope = bound.authorized_source.source_scope_ids[0]
                clock = [0.0, 101.0 if expired else 3.0, observations[0], scope]
                _, tables, status = self._run(bound, clock=clock, turn_deadline=100.0)
                self.assertEqual(bool(tables), not expired)
                self.assertEqual(status["shown_row_count"], 0 if expired else 1)
                self.assertIn(next(key for key, value in status["pre_group_reason_flags"].items() if value), {"deadline_during_hydration", "presentation_deadline"})

    def test_constructed_table_is_not_reported_shown_if_presentation_declines(self):
        with tempfile.TemporaryDirectory() as directory:
            bound, observations = self._bound(Path(directory))
            _, tables, status = self._run(bound, allowed={sha256_json(observations[0].to_dict())}, drop_table=True)
            self.assertFalse(tables)
            self.assertEqual(status["fitted_row_count"], 1)
            self.assertEqual(status["shown_row_count"], 0)


if __name__ == "__main__":
    unittest.main()
