"""Decision rules of the phase 2 reviewed-header structural proposer."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "issue56_reviewed_header_proposer.py"
_SPEC = importlib.util.spec_from_file_location("issue56_reviewed_header_proposer", _PATH)
proposer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(proposer)


def _decide(label, values=("Japan", "China", "Taiwan"), **overrides):
    kinds = {}
    for value in values:
        kind = proposer._value_kind(value)
        kinds[kind] = kinds.get(kind, 0) + 1
    options = dict(kinds=kinds, values=list(values), duplicate_label=False,
                   header_path_depth=0, column_indexed=True)
    options.update(overrides)
    return proposer.decide(label, **options)


class ReviewedHeaderProposerTests(unittest.TestCase):
    def test_ordinary_labels_are_confirmed_in_any_language(self):
        for label in ("COO", "交貨日", "Delivery Date", "PO\n            "):
            with self.subTest(label=label):
                self.assertEqual(_decide(label)[0], "header_confirmed")

    def test_value_shaped_or_sentence_labels_are_not_headers(self):
        self.assertEqual(_decide("2026-03-04")[0], "not_header")
        self.assertEqual(_decide("45000")[0], "not_header")
        self.assertEqual(_decide("跟代理商購買 45000pcs-NTD 0.84 ，但因交期延誤所以改向原廠下單")[0], "not_header")
        self.assertEqual(_decide("Japan", values=("Japan", "Japan", "China"))[0], "not_header")
        self.assertEqual(_decide("2025/03/01", header_path_depth=2), ("not_header", ["label_is_value_shaped"]))
        self.assertEqual(_decide("SP.Z6L02G004", values=("SP.Z6L07G002", "SP.Z6LS7G001", "x"))[0], "not_header")
        self.assertEqual(_decide("Core P/N", values=("09.HSMRCG191", "43.F1E16G301"))[0], "header_confirmed")
        self.assertEqual(_decide("CRI_PN", values=("03.00003G40Q", "02.10640G107"))[0], "header_confirmed")

    def test_uncertain_structure_is_ambiguous_not_rejected(self):
        self.assertEqual(_decide("COO", duplicate_label=True), ("ambiguous", ["duplicate_label_in_header_row"]))
        self.assertEqual(_decide("COO", header_path_depth=2)[0], "ambiguous")
        self.assertEqual(_decide("COO", values=("Japan",))[0], "ambiguous")
        self.assertEqual(_decide("column_3")[0], "ambiguous")
        self.assertEqual(_decide("[redacted_path] x")[0], "ambiguous")
        self.assertEqual(_decide("COO", column_indexed=False)[0], "ambiguous")
        self.assertEqual(_decide("c")[0], "ambiguous")
        self.assertEqual(_decide("交期")[0], "header_confirmed")

    def test_value_kind(self):
        self.assertEqual(proposer._value_kind(" "), "blank")
        self.assertEqual(proposer._value_kind("1,200.5"), "number")
        self.assertEqual(proposer._value_kind("2026/05/14"), "date")
        self.assertEqual(proposer._value_kind("MURATA"), "text")


if __name__ == "__main__":
    unittest.main()
