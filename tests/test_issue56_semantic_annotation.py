from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import _paths  # noqa: F401

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "issue56_semantic_annotation.py"
_spec = importlib.util.spec_from_file_location("issue56_semantic_annotation", _SCRIPT)
annotation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(annotation)


class ChunkTests(unittest.TestCase):
    def test_groups_stay_in_order_within_budget_and_never_split_an_observation(self) -> None:
        items = [("a", 40), ("b", 50), ("c", 300), ("d", 10), ("e", 10)]
        self.assertEqual(annotation.chunks(items, 100), [["a", "b"], ["c"], ["d", "e"]])

    def test_empty_input_has_no_chunks(self) -> None:
        self.assertEqual(annotation.chunks([], 100), [])

    def test_regroup_keeps_whole_observations_and_original_unit_coverage(self) -> None:
        unit = {"unit_id": "original", "observation_ids": ["head", "a", "b", "c"],
                "focus_observation_ids": ["a", "b", "c"], "parent": "message"}
        sources = {oid: SimpleNamespace(text="x" * n, payload={}, observation_type="paragraph")
                   for oid, n in [("a", 30), ("b", 30), ("c", 200)]}
        parts = annotation.regroup_unit(unit, 80, sources.__getitem__)
        self.assertEqual([p["focus_observation_ids"] for p in parts], [["a", "b"], ["c"]])
        self.assertEqual([p["original_unit_id"] for p in parts], ["original", "original"])
        self.assertTrue(parts[1]["oversize_observation_ids"] == ["c"])
        self.assertEqual(parts[1]["observation_ids"], ["head", "c"])
        self.assertEqual(parts[0]["parent"], "message")

    def test_regroup_carries_first_table_row_as_context_and_changes_membership_id(self) -> None:
        unit = {"unit_id": "attachment", "kind": "attachment", "observation_ids": ["header", "data"],
                "focus_observation_ids": ["header", "data"]}
        source = {oid: SimpleNamespace(text="x" * 60, payload={}, observation_type="table_row")
                  for oid in ["header", "data"]}
        small = annotation.regroup_unit(unit, 80, source.__getitem__)
        large = annotation.regroup_unit(unit, 200, source.__getitem__)
        self.assertEqual(small[1]["observation_ids"], ["header", "data"])
        self.assertEqual(small[1]["focus_observation_ids"], ["data"])
        self.assertNotEqual(small[0]["unit_id"], large[0]["unit_id"])

    def test_regroup_refuses_changed_source_pin(self) -> None:
        from formowl_contract import sha256_json
        root = _paths.fresh_test_dir("regroup-pins")
        observation = SimpleNamespace(to_dict=lambda: {"text": "changed"}, text="changed", payload={},
                                      observation_type="paragraph")
        unit = {"unit_id": "original", "store": "test-store", "observation_ids": ["a"],
                "focus_observation_ids": ["a"], "expected_observation_hashes": {"a": sha256_json("old")}}
        (root / "units").write_text(json.dumps(unit) + "\n")
        with patch("formowl_ingestion.storage.records.ObservationStore") as store:
            store.return_value.get.return_value = observation
            with self.assertRaisesRegex(ValueError, "pin"):
                annotation.regroup_command(SimpleNamespace(
                    units=str(root / "units"), output=str(root / "output"), focus_chars=80))


class DispatchTests(unittest.TestCase):
    def test_removed_lane_finishes_current_unit_then_stops(self) -> None:
        root = _paths.fresh_test_dir("annotation-remove-lane")
        config = root / "urls.json"
        config.write_text(json.dumps(["http://lane-a:1"]))
        work = queue.Queue()
        for value in range(3):
            work.put(value)
        received, replacement = [], threading.Event()

        def process(url, value):
            received.append((url, value))
            if value == 0:
                config.write_text(json.dumps(["http://lane-b:2"]))
                self.assertTrue(replacement.wait(3))
            else:
                replacement.set()

        annotation.dispatch(work, process, "http://lane-a:1", str(config))
        self.assertEqual([v for url, v in received if url == "http://lane-a:1"], [0])
        self.assertEqual(sorted(v for _, v in received), [0, 1, 2])

    def test_resume_binds_scope_and_reader_policy_but_allows_new_urls(self) -> None:
        root = _paths.fresh_test_dir("annotation-run-pins")
        units = root / "units.jsonl"
        units.write_text('{"unit_id":"a","focus_chars":1500}\n')
        args = SimpleNamespace(units=str(units), run_id="run_pins", model="local-model",
                               source_revision="source", ontology_revision="ontology", num_ctx=32768,
                               urls="http://lane-a:1")
        annotation.bind_run(args, root)
        args.urls = "http://lane-b:2"
        annotation.bind_run(args, root)
        units.write_text('{"unit_id":"a","focus_chars":3500}\n')
        with self.assertRaisesRegex(ValueError, "NEW run id"):
            annotation.bind_run(args, root)

    def test_dynamic_file_adds_one_lane_without_repeating_work(self) -> None:
        root = _paths.fresh_test_dir("annotation-lanes")
        config = root / "urls.json"
        config.write_text(json.dumps(["http://lane-a:1"]))
        work = queue.Queue()
        for value in range(3):
            work.put(value)
        received, second = [], threading.Event()

        def process(url, value):
            received.append((url, value))
            if value == 0:
                config.write_text(json.dumps(["http://lane-a:1", "http://lane-b:2"]))
                self.assertTrue(second.wait(3))
            else:
                second.set()

        annotation.dispatch(work, process, "http://lane-a:1", str(config))
        self.assertEqual(sorted(v for _, v in received), [0, 1, 2])
        self.assertTrue(any(url == "http://lane-b:2" for url, _ in received))

    def test_source_io_failure_is_raised_in_main_thread(self) -> None:
        work = queue.Queue()
        work.put("a")
        work.put("b")

        def process(url, value):
            raise OSError("source-file.json")

        with self.assertRaisesRegex(OSError, "source-file.json"):
            annotation.dispatch(work, process, "http://lane-a:1")
        self.assertEqual(work.qsize(), 1)


class DocumentScopeTests(unittest.TestCase):
    @staticmethod
    def _write_lookup_manifest(lookup: Path) -> None:
        digest = hashlib.sha256(lookup.read_bytes()).hexdigest()
        lookup.with_name("source-lookup-manifest.json").write_text(json.dumps({
            "sqlite_sha256": f"sha256:{digest}",
            "source_revision_sha256": "sha256:" + "a" * 64,
        }))

    def test_document_scope_selects_only_hash_bound_document_helpers(self) -> None:
        temp_dir = _paths.fresh_test_dir("semantic-annotation-document-scope")
        lookup = temp_dir / "source-lookup.sqlite"
        with sqlite3.connect(lookup) as connection:
            connection.execute(
                "CREATE TABLE helpers (job_index INTEGER, observation_id TEXT, "
                "observation_hash TEXT, source_family TEXT)"
            )

        raw = {
            "heading": {
                "observation_id": "obs-heading", "asset_id": "asset-doc",
                "modality": "text", "observation_type": "heading", "text": "Heading",
                "location": {"block_index": 0},
            },
            "paragraph": {
                "observation_id": "obs-paragraph", "asset_id": "asset-doc",
                "modality": "text", "observation_type": "paragraph",
                "text": "Paragraph text.", "location": {"block_index": 1},
            },
            "mail": {
                "observation_id": "obs-mail", "asset_id": "asset-mail",
                "modality": "mail", "observation_type": "email_message", "text": "Mail",
                "location": {},
            },
        }
        observations = {
            key: SimpleNamespace(
                observation_id=value["observation_id"], asset_id=value["asset_id"],
                modality=value["modality"], observation_type=value["observation_type"],
                text=value["text"], location=value["location"],
                to_dict=lambda value=value: value,
            )
            for key, value in raw.items()
        }
        from formowl_contract import sha256_json

        with sqlite3.connect(lookup) as connection:
            connection.executemany(
                "INSERT INTO helpers VALUES (?, ?, ?, ?)",
                [
                    (0, "obs-heading", sha256_json(raw["heading"]), "document_text"),
                    (0, "obs-paragraph", sha256_json(raw["paragraph"]), "document_text"),
                    (0, "obs-mail", sha256_json(raw["mail"]), "mail"),
                ],
            )
        self._write_lookup_manifest(lookup)
        job = SimpleNamespace(
            status="succeeded", asset_id="asset-doc",
            observation_ids=["obs-heading", "obs-paragraph", "obs-mail"],
        )
        job_store = SimpleNamespace(get=lambda job_id: job if job_id == "job-doc" else None)
        observation_store = SimpleNamespace(get=lambda oid: next(
            (value for value in observations.values() if value.observation_id == oid), None
        ))
        with (
            patch("formowl_ingestion.storage.records.JobStore", return_value=job_store),
            patch("formowl_ingestion.storage.records.ObservationStore", return_value=observation_store),
        ):
            units, counts = annotation.build_document_scope(
                [("/source", "job-doc", None)], 10, lookup,
            )

        self.assertEqual(counts["source_family"], "document_text")
        self.assertEqual(counts["source_observations"], 2)
        self.assertEqual(counts["documents"], 1)
        self.assertEqual(counts["observation_types"], {"heading": 1, "paragraph": 1})
        self.assertEqual(counts["average_text_length_chars"], 11.0)
        self.assertEqual(len(units), 2)
        self.assertTrue(all(unit["kind"] == "document_text" for unit in units))
        self.assertEqual(
            {oid for unit in units for oid in unit["observation_ids"]},
            {"obs-heading", "obs-paragraph"},
        )

    def test_document_scope_rejects_a_stale_helper_hash(self) -> None:
        temp_dir = _paths.fresh_test_dir("semantic-annotation-document-stale-helper")
        lookup = temp_dir / "source-lookup.sqlite"
        with sqlite3.connect(lookup) as connection:
            connection.execute(
                "CREATE TABLE helpers (job_index INTEGER, observation_id TEXT, "
                "observation_hash TEXT, source_family TEXT)"
            )
            connection.execute(
                "INSERT INTO helpers VALUES (0, 'obs-heading', 'stale', 'document_text')"
            )
        self._write_lookup_manifest(lookup)
        raw = {"observation_id": "obs-heading", "asset_id": "asset-doc",
               "modality": "text", "observation_type": "heading", "text": "Heading",
               "location": {"block_index": 0}}
        observation = SimpleNamespace(
            **{key: value for key, value in raw.items() if key != "location"},
            location=raw["location"], to_dict=lambda: raw,
        )
        job = SimpleNamespace(status="succeeded", asset_id="asset-doc", observation_ids=["obs-heading"])
        with (
            patch("formowl_ingestion.storage.records.JobStore", return_value=SimpleNamespace(get=lambda _: job)),
            patch("formowl_ingestion.storage.records.ObservationStore",
                  return_value=SimpleNamespace(get=lambda _: observation)),
            self.assertRaisesRegex(Exception, "document scope helper binding is invalid"),
        ):
            annotation.build_document_scope([("/source", "job-doc", None)], 100, lookup)


class ReportTests(unittest.TestCase):
    def test_partial_candidate_retention_never_counts_as_complete_coverage(self) -> None:
        import contextlib
        import io
        root = _paths.fresh_test_dir("annotation-partial-report")
        (root / "units.jsonl").write_text(json.dumps({"unit_id": "a"}) + "\n")
        (root / "progress.jsonl").write_text(json.dumps({"run": "r", "unit": "a", "status": "pending",
            "validation_status": "partial", "atoms": 2, "rejected_atom_count": 1,
            "rejected_relation_count": 0, "rejected_reasons": {"exact_span_mismatch": 1},
            "reason": "candidate_validation_partial", "ledger": "sem_partial"}) + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            annotation.main(["report", "--units", str(root / "units.jsonl"), "--output", str(root), "--run-id", "r"])
        report = json.loads(out.getvalue())
        self.assertFalse(report["scope_complete"])
        self.assertEqual(report["original_units_annotated"], 0)
        self.assertEqual(report["partial_units"], 1)
        self.assertEqual(report["partial_candidate_atoms"], 2)
        self.assertEqual(report["rejected_atom_count"], 1)

    def test_original_unit_needs_every_regrouped_child(self) -> None:
        import contextlib
        import io
        root = _paths.fresh_test_dir("annotation-original-report")
        (root / "units.jsonl").write_text("".join(json.dumps(
            {"unit_id": u, "original_unit_id": "original"}) + "\n" for u in ["a", "b"]))
        (root / "progress.jsonl").write_text(json.dumps(
            {"run": "r", "unit": "a", "status": "annotated", "ledger": "ledger_a"}) + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            annotation.main(["report", "--units", str(root / "units.jsonl"), "--output", str(root),
                             "--run-id", "r"])
        report = json.loads(out.getvalue())
        self.assertEqual(report["original_unit_count"], 1)
        self.assertEqual(report["original_units_annotated"], 0)
        self.assertFalse(report["scope_complete"])

    def test_annotated_read_stands_and_gaps_keep_their_latest_reason(self) -> None:
        import contextlib
        import io
        import json

        temp_dir = _paths.fresh_test_dir("semantic-annotation-report")
        (temp_dir / "units.jsonl").write_text("".join(json.dumps({"unit_id": u}) + "\n" for u in "abcd"))
        rows = [("r1", "a", "annotated", None), ("r1", "b", "failed", "exact_span_mismatch"),
                ("r2", "b", "failed", "provider_incomplete"), ("r2", "a", "failed", "x"),
                ("r1", "c", "failed", "exact_span_mismatch"), ("r2", "c", "annotated", None),
                ("other", "d", "annotated", None)]
        (temp_dir / "progress.jsonl").write_text("".join(json.dumps(
            {"run": r, "unit": u, "status": s, "reason": why, "atoms": 2, "ledger": f"sem_{r}_{u}"}) + "\n"
            for r, u, s, why in rows))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            annotation.main(["report", "--units", str(temp_dir / "units.jsonl"), "--output", str(temp_dir),
                             "--run-id", "r1", "--run-id", "r2"])
        report = json.loads(out.getvalue())
        self.assertEqual(report["status_counts"], {"annotated": 2, "failed": 1, "not_attempted": 1})
        self.assertEqual(report["gap_reasons"], {"provider_incomplete": 1})
        self.assertEqual(report["candidate_atoms"], 4)
        self.assertFalse(report["scope_complete"])


if __name__ == "__main__":
    unittest.main()
