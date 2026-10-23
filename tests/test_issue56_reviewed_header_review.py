"""Acceptance policy of the phase 3 reviewed-header review tool."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "issue56_reviewed_header_review.py"
_SPEC = importlib.util.spec_from_file_location("issue56_reviewed_header_review", _PATH)
review = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(review)

COLUMN = "sha256:" + "c" * 64
COLUMNS = {(COLUMN, False)}


def _proposal(binding, decision, reasons=(), column=COLUMN, inline=False):
    return {"proposer_version": "structural_v1", "binding": binding, "column_hash": column,
            "inline_table": inline, "decision": decision, "reasons": list(reasons)}


def _llm(binding, decision="header_confirmed"):
    return {"proposer_version": "llm_v1", "binding": binding, "decision": decision}


class ReviewedHeaderReviewPolicyTests(unittest.TestCase):
    def test_structural_policy_approves_only_confirmed_indexed_columns(self):
        structural = [
            _proposal("b1", "header_confirmed"),
            _proposal("b2", "not_header", ["label_too_long"]),
            _proposal("b3", "ambiguous", ["multi_level_header_path"]),
            _proposal("b4", "header_confirmed", column="sha256:" + "e" * 64),
            _proposal("b5", "header_confirmed", inline=True),
        ]
        approvals, counts = review.select_approvals("structural_accept_v1", structural, [_llm("b3")], COLUMNS)
        self.assertEqual(approvals, [{"binding": "b1", "column_hash": COLUMN}])
        self.assertEqual(counts["rejected_not_header"], 1)
        self.assertEqual(counts["left_ambiguous"], 1)
        self.assertEqual(counts["skipped_unindexed_or_conflict"], 2)

    def test_llm_policy_resolves_only_eligible_ambiguity(self):
        structural = [
            _proposal("b1", "ambiguous", ["multi_level_header_path"]),
            _proposal("b2", "ambiguous", ["label_too_short", "duplicate_label_in_header_row"]),
            _proposal("b3", "not_header", ["label_is_value_shaped"]),
            _proposal("b4", "ambiguous", ["label_too_short"]),
        ]
        llm = [_llm("b1"), _llm("b2"), _llm("b3"), _llm("b4", "not_header")]
        approvals, counts = review.select_approvals("structural_llm_accept_v1", structural, llm, COLUMNS)
        self.assertEqual([item["binding"] for item in approvals], ["b1"])
        self.assertEqual(counts["approved_llm"], 1)
        self.assertEqual(counts["rejected_not_header"], 1)
        self.assertEqual(counts["left_ambiguous"], 2)

    def test_duplicate_bindings_are_never_approved(self):
        structural = [_proposal("b1", "header_confirmed"), _proposal("b1", "header_confirmed")]
        approvals, counts = review.select_approvals("structural_accept_v1", structural, [], COLUMNS)
        self.assertEqual(approvals, [])
        self.assertEqual(counts["skipped_unindexed_or_conflict"], 2)

    def test_unknown_policy_and_proposer_reject(self):
        with self.assertRaises(ValueError):
            review.select_approvals("accept_everything", [], [], COLUMNS)
        bad = {**_proposal("b1", "header_confirmed"), "proposer_version": "other"}
        with self.assertRaises(ValueError):
            review.select_approvals("structural_accept_v1", [bad], [], COLUMNS)


if __name__ == "__main__":
    unittest.main()
