from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "experiments" / "kg_bert_ablation" / "run_ablation.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("kg_bert_ablation_run", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load kg_bert_ablation runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class KGBertAblationExperimentTests(unittest.TestCase):
    def test_lexical_baseline_records_candidate_only_metrics(self) -> None:
        module = _load_module()

        run = module.run_lexical_baseline(0.70)

        self.assertEqual(run["run_id"], "non_bert_lexical_baseline_v1")
        self.assertEqual(run["status"], "completed")
        self.assertFalse(run["uses_neural_networks"])
        self.assertIn("f1", run["metrics"])
        self.assertFalse(any(row["status"] == "type_mismatch" for row in run["pair_results"][:-1]))
        self.assertEqual(run["pair_results"][-1]["status"], "type_mismatch")

    def test_missing_sentence_transformer_dependency_is_preserved_as_data(self) -> None:
        module = _load_module()

        run = module.run_sentence_transformer(
            threshold=0.70,
            model_name="sentence-transformers/bert-base-nli-mean-tokens",
        )

        if run["package_status"]["available"]:
            self.skipTest("sentence_transformers is installed in this environment")
        self.assertEqual(run["status"], "blocked_missing_dependency")
        self.assertTrue(run["uses_neural_networks"])
        self.assertIsNone(run["metrics"])
        self.assertIn("sentence_transformers", run["blocker"])

    def test_report_writer_persists_baseline_and_blocked_bert_result(self) -> None:
        module = _load_module()
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "result.json"

            with patch("builtins.print"):
                exit_code = module.main(["--output", str(output_path)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["artifact_id"], "formowl_kg_bert_ablation_result_v1")
            self.assertTrue(payload["claim_boundary"]["candidate_only"])
            self.assertFalse(payload["claim_boundary"]["canonical_graph_write_allowed"])
            self.assertFalse(payload["claim_boundary"]["raw_access_allowed"])
            self.assertEqual(payload["dataset"]["pair_count"], 16)
            self.assertEqual(payload["runs"][0]["status"], "completed")
            self.assertIn(payload["runs"][1]["status"], {"blocked_missing_dependency", "completed"})
            self.assertIn("torch", payload["environment"])
            self.assertIn("torch_status", payload["runs"][1])
            if payload["runs"][1]["status"] != "completed":
                self.assertEqual(payload["comparison"]["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
