from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import fcntl
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Observation, PermissionScope, sha256_json
from formowl_mail.semantic_plan import validated_authorized_semantic_source, AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
from scripts import build_native_table_records as export

SCOPE = PermissionScope(scope_type="workspace", scope_id="workspace_fictional", visibility="restricted")
SOURCE = validated_authorized_semantic_source(
    source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND, workspace_id="workspace_fictional",
    source_scope_ids=(SCOPE.scope_id,), authorized_permission_scopes=(SCOPE,),
)
STAMP = "2026-11-01T00:00:00+00:00"
JOB_HASH = sha256_json("fictional job")


def observation(key, kind, *, inline=False, location=None, payload=None, text=None):
    mail = kind.startswith("email_")
    return Observation(
        observation_id=key, extractor_run_id="run_mail" if mail or inline else "run_sheet",
        observation_type=kind, modality="mail" if mail else "document", location=location or {},
        confidence=1.0, permission_scope=SCOPE.to_dict(), created_at=STAMP,
        asset_id="asset_mail" if mail or inline else "asset_sheet", text=text, payload=payload or {},
    )


def group(*, inline=False, names=("Item", "Count"), role="data", row_index=7):
    mail = observation("mail_fictional", "email_message",
        location={"message_occurrence_id": "occurrence_fictional"},
        payload={"message_id": "<fictional@example.test>", "sent_at": "Sun, 1 Nov 2026 09:00:00 +0800",
                 "message_fingerprint": sha256_json("fictional mail")})
    parent = mail if inline else observation("attachment_fictional", "email_attachment_occurrence",
        location={"message_occurrence_id": "occurrence_fictional"},
        payload={"child_asset_id": "asset_sheet", "message_id": "<fictional@example.test>"})
    lineage = {"child_asset_id": "asset_sheet", "parent_attachment_observation_id": parent.observation_id}
    location = {"table_index": 2, "row_index": row_index, "sheet_name": "Fictional sheet"}
    if inline:
        lineage = {"source_family": "mail_inline_table", "parent_message_observation_id": mail.observation_id,
                   "parent_asset_id": mail.asset_id, "message_occurrence_id": "occurrence_fictional",
                   "mime_ordinal": 0, "table_ordinal": 2}
        location.update(lineage)
    row = observation(f"row_{inline}_{row_index}", "table_row", inline=inline, location=location,
        payload={"lineage": lineage, "table_structure": {"row_role": role, "structure_status": "candidate_only"}})
    cells = [observation(f"cell_{inline}_{row_index}_{index}", "table_cell", inline=inline,
        location={**location, "cell_index": index}, text=f"fictional-{index}",
        payload={"lineage": lineage, "table_structure": {"column_name": name, "structure_status": "candidate_only"}})
        for index, name in enumerate(names, start=1)]
    return row, cells, parent, mail


def projected(**kwargs):
    row, cells, parent, mail = group(**kwargs)
    return export.project_row(row, list(reversed(cells)), parent, mail, job_fingerprint=JOB_HASH,
        row_hash=sha256_json(row.to_dict()), cell_hashes={cell.observation_id: sha256_json(cell.to_dict()) for cell in cells})


def reader_fixture(*, inline=False):
    row, cells, parent, mail = group(inline=inline)
    items = {item.observation_id: item for item in (row, *cells, parent, mail)}
    helpers = {key: {"observation_id": key, "observation_hash": sha256_json(item.to_dict()),
                      "reference": {"job_index": 0}} for key, item in items.items()}
    def load(key, *, expected_observation_hash, expected_job_fingerprint):
        item = items[key]
        if expected_job_fingerprint != JOB_HASH or sha256_json(item.to_dict()) != expected_observation_hash:
            raise ContractValidationError("fictional hash mismatch")
        return item
    authority = SimpleNamespace(job_fingerprint=JOB_HASH, load_indexed_observation=load)
    runtime = SimpleNamespace(get_helper=helpers.get,
        helper_for_attachment_asset=lambda key: helpers[parent.observation_id],
        helper_for_mail_parent=lambda **kwargs: helpers[mail.observation_id])
    source_records = SimpleNamespace(runtime_store=runtime, _authority_for_helper=lambda helper: authority)
    revision = SimpleNamespace(authorized_source=SOURCE, source_records=source_records, job_authorities=(authority,))
    lookup = SimpleNamespace(_shards={}, _manifest={"counts": {}})
    with mock.patch.object(export, "_IngestionExactCellLookup", return_value=lookup):
        native = export.NativeRows(revision)
    key = sha256_json(export._table_row_key(row))
    refs = [["row", key, 0, row.observation_id, sha256_json(row.to_dict()), inline]]
    refs.extend(["cell", key, 0, cell.observation_id, sha256_json(cell.to_dict()), sha256_json("column"), inline] for cell in cells)
    return native, key, refs, items


class FakeNative:
    def __init__(self):
        self.data = {
            "00": [projected(inline=True, names=("Item", None), role="header")],
            "01": [projected(names=(None, None)), projected(names=(None, "Count"), row_index=8)],
            "02": [projected(inline=True, names=(None, None), row_index=9)],
        }
        # Make the last fully unnamed table a distinct table for the structural sample.
        self.data["02"][0]["table_id"] = sha256_json("fictional unnamed table")
        self.shards = sorted(self.data)
        rows = [row for values in self.data.values() for row in values]
        self.counts = {"table_row": len(rows), "table_cell": sum(len(row["cells"]) for row in rows)}
        self.calls = []

    def rows(self, shard):
        self.calls.append(shard)
        yield from self.data[shard]


class NativeTableRecordsTests(unittest.TestCase):
    def test_complete_header_preserves_order_original_date_and_hashes(self):
        row = projected(inline=True, role="header")
        self.assertEqual(row["header_signature"], ["Item", "Count"])
        self.assertEqual(row["named_cell_count"], 2)
        self.assertTrue(row["complete"])
        self.assertEqual([cell["cell_index"] for cell in row["cells"]], [1, 2])
        self.assertEqual(row["row_role"], "header")
        self.assertEqual(row["sent_at"], "Sun, 1 Nov 2026 09:00:00 +0800")
        self.assertEqual(row["mail_message_id"], "<fictional@example.test>")
        self.assertIsNone(row["attachment_observation_id"])
        self.assertTrue(all(cell["observation_hash"].startswith("sha256:") for cell in row["cells"]))

    def test_partial_blank_and_empty_headers_retain_all_cells(self):
        for names, expected in ((("Item", None), ["Item", None]), ((" ", None), [None, None]), ((), [])):
            with self.subTest(names=names):
                row = projected(names=names)
                self.assertEqual(row["header_signature"], expected)
                self.assertFalse(row["complete"])
                self.assertEqual(len(row["cells"]), len(names))
                self.assertEqual(row["named_cell_count"], sum(name is not None for name in expected))
                self.assertEqual(row["attachment_observation_id"], "attachment_fictional")
        self.assertIsNone(projected(names=(None, None))["header_signature_hash"])

    def test_redaction_applies_to_labels_and_cell_text_without_changing_hash(self):
        row, cells, parent, mail = group(names=("/tmp/fictional-private-label.txt",))
        cells[0] = replace(cells[0], text="/tmp/fictional-private-value.txt")
        cell_hash = sha256_json(cells[0].to_dict())
        result = export.project_row(row, cells, parent, mail, job_fingerprint=JOB_HASH,
            row_hash=sha256_json(row.to_dict()), cell_hashes={cells[0].observation_id: cell_hash})
        self.assertNotIn("/tmp/", result["cells"][0]["column_name"])
        self.assertNotIn("/tmp/", result["cells"][0]["text"])
        self.assertEqual(result["cells"][0]["observation_hash"], cell_hash)

    def test_real_lineage_validation_for_inline_and_attachment_groups(self):
        for inline in (False, True):
            with self.subTest(inline=inline):
                native, key, refs, _ = reader_fixture(inline=inline)
                result = native.project_group(key, refs)
                self.assertEqual(result["mail_message_id"], "<fictional@example.test>")
                self.assertEqual(result["source_family"], "mail_inline_table" if inline else "attachment_table")

    def test_changed_source_hash_and_duplicate_cell_positions_fail(self):
        native, key, refs, items = reader_fixture()
        altered = deepcopy(refs)
        altered[-1][4] = sha256_json("wrong cell hash")
        with self.assertRaises(ContractValidationError):
            native.project_group(key, altered)
        first_cell = refs[1][3]
        second_cell = refs[2][3]
        items[second_cell] = replace(items[second_cell], location=dict(items[first_cell].location))
        refs[2][4] = sha256_json(items[second_cell].to_dict())
        with self.assertRaises(ContractValidationError):
            native.project_group(key, refs)

    def test_partial_resume_matches_fresh_export_and_keeps_unnamed_tables(self):
        native = FakeNative()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "resumed"
            fresh = Path(temporary) / "fresh"
            partial = export.export_rows(native, output, {"pin": "fictional"}, max_shards=1)
            self.assertEqual(partial["status"], "in_progress")
            before = (output / "rows-00.jsonl").stat().st_mtime_ns
            result = export.export_rows(native, output, {"pin": "fictional"})
            self.assertEqual((output / "rows-00.jsonl").stat().st_mtime_ns, before)
            self.assertEqual(native.calls, ["00", "01", "02"])
            export.export_rows(FakeNative(), fresh, {"pin": "fictional"})
            for name in ("rows-00.jsonl", "rows-01.jsonl", "rows-02.jsonl", "header_signatures.jsonl"):
                self.assertEqual((output / name).read_bytes(), (fresh / name).read_bytes())
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["table_count"], 3)
            self.assertEqual(result["row_count"], 4)
            self.assertEqual(result["tables_without_named_cells"], 1)
            self.assertEqual(result["named_cell_ratio_row_distribution"], {"0": 2, "1-49%": 0, "50-99%": 2, "100%": 0})
            signatures = [json.loads(line) for line in (output / "header_signatures.jsonl").read_text().splitlines()]
            self.assertEqual(len(signatures), 2)
            self.assertTrue(all(any(name is not None for name in sig["column_names"]) for sig in signatures))

    def test_resume_rejects_changed_binding_and_corrupted_committed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            export.export_rows(FakeNative(), output, {"pin": "a"}, max_shards=1)
            with self.assertRaises(ContractValidationError):
                export.export_rows(FakeNative(), output, {"pin": "b"})
            with (output / "rows-00.jsonl").open("ab") as stream:
                stream.write(b"corrupted\n")
            with self.assertRaises(ContractValidationError):
                export.export_rows(FakeNative(), output, {"pin": "a"})

    def test_interrupted_shard_is_rebuilt_and_concurrent_writer_is_rejected(self):
        native = FakeNative()
        def interrupted(shard):
            yield native.data[shard][0]
            raise RuntimeError("fictional interruption")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with mock.patch.object(native, "rows", side_effect=interrupted):
                with self.assertRaises(RuntimeError):
                    export.export_rows(native, output, {"pin": "a"})
            self.assertFalse((output / "rows-00.jsonl").exists())
            self.assertTrue((output / "rows-00.jsonl.tmp").exists())
            result = export.export_rows(native, output, {"pin": "a"})
            self.assertEqual(result["row_count"], 4)
            with (output / ".export.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    export.export_rows(native, output, {"pin": "a"})

    def test_signature_samples_are_bounded_and_ratio_boundaries_are_exact(self):
        native = FakeNative()
        native.data = {"00": [projected(row_index=index) for index in range(10)]}
        native.shards = ["00"]
        native.counts = {"table_row": 10, "table_cell": 20}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = export.export_rows(native, output, {"pin": "a"})
            signature = json.loads((output / "header_signatures.jsonl").read_text())
            self.assertEqual(len(signature["sample_cells"]), 5)
            self.assertEqual(signature["row_count"], 10)
            self.assertEqual(result["complete_header_row_ratio"], 1)
        self.assertEqual([export.ratio_bucket(*pair) for pair in ((0, 0), (1, 3), (1, 2), (2, 2))],
                         ["0", "1-49%", "50-99%", "100%"])


if __name__ == "__main__":
    unittest.main()
