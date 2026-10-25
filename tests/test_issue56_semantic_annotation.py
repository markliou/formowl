from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
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
