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


if __name__ == "__main__":
    unittest.main()
