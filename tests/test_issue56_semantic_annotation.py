from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

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
