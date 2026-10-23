"""Phase 4 LLM header proposer: strict parsing and fail-closed behavior."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


llm = _load("issue56_reviewed_header_llm_proposer")
review = _load("issue56_reviewed_header_review")


def _item(binding, reasons=("multi_level_header_path",), decision="ambiguous"):
    return {"proposer_version": "structural_v1", "binding": binding, "decision": decision,
            "reasons": list(reasons), "label": "交貨日", "value_kinds": {"date": 3},
            "sample_values": ["2026/05/14"]}


def _reply(*decisions):
    return json.dumps({"decisions": [{"id": i, "decision": d} for i, d in enumerate(decisions)]})


class LlmHeaderProposerTests(unittest.TestCase):
    def test_eligibility_matches_review_policy(self):
        self.assertEqual(llm.LLM_ELIGIBLE_REASONS, review.LLM_ELIGIBLE_REASONS)
        items = [_item("a"), _item("b", ["duplicate_label_in_header_row"]), _item("c", decision="not_header"),
                 _item("d", ["label_too_short", "multi_level_header_path"])]
        self.assertEqual([item["binding"] for item in llm.eligible(items)], ["a", "d"])

    def test_valid_reply_is_mapped_by_id(self):
        items = [_item("a"), _item("b")]
        reply = json.dumps({"decisions": [{"id": 1, "decision": "not_header"},
                                          {"id": 0, "decision": "header_confirmed"}]})
        result = llm.classify_batch(items, lambda payload: reply, model="m")
        self.assertEqual([(r["binding"], r["decision"]) for r in result],
                         [("a", "header_confirmed"), ("b", "not_header")])

    def test_malformed_or_failed_replies_fail_closed(self):
        items = [_item("a"), _item("b")]
        bad_replies = [None, "not json", _reply("header_confirmed"), _reply("header_confirmed", "yes"),
                       json.dumps({"decisions": [{"id": 0, "decision": "header_confirmed"},
                                                 {"id": 0, "decision": "header_confirmed"}]})]
        for reply in bad_replies:
            with self.subTest(reply=reply):
                result = llm.classify_batch(items, lambda payload, r=reply: r, model="m")
                self.assertEqual({r["decision"] for r in result}, {"ambiguous"})

        def boom(payload):
            raise TimeoutError("provider")
        self.assertEqual({r["decision"] for r in llm.classify_batch(items, boom, model="m")}, {"ambiguous"})

    def test_payload_marks_labels_as_data_and_pins_schema_size(self):
        payload = llm.build_payload([_item("a"), _item("b")], model="m")
        self.assertIn("untrusted data", payload["instructions"])
        self.assertEqual(payload["text"]["format"]["schema"]["properties"]["decisions"]["minItems"], 2)
        self.assertNotIn("binding", payload["input"][0]["content"])

    def test_run_is_resumable_and_bounded(self):
        items = [_item(str(i)) for i in range(5)]
        calls = []

        def call(payload):
            calls.append(payload)
            count = payload["text"]["format"]["schema"]["properties"]["decisions"]["minItems"]
            return _reply(*["header_confirmed"] * count)

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            first = llm.run(items, out, call, model="m", batch_size=2, max_batches=1)
            self.assertEqual((first["batches_written"], first["merged"]), (1, 2))
            second = llm.run(items, out, call, model="m", batch_size=2, max_batches=None)
            self.assertEqual((second["batches_written"], second["merged"]), (2, 5))
            self.assertEqual(len(calls), 3)
            self.assertEqual(second["header_confirmed"], 5)


if __name__ == "__main__":
    unittest.main()
