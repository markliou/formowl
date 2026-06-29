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
EXPERIMENT_README = SCRIPT_PATH.parent / "README.md"
RUNTIME_DOC = SCRIPT_PATH.parents[2] / "docs" / "kg-bert-runtime.md"
METHOD_DOC = SCRIPT_PATH.parents[2] / "docs" / "kg-research-method.md"
ROOT_README = SCRIPT_PATH.parents[2] / "README.md"


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

    def test_bert_type_gate_uses_pair_core_supertypes(self) -> None:
        module = _load_module()
        pair = module.DATASET[-1]

        self.assertEqual(pair.pair_id, "negative_person_project_same_label")
        self.assertEqual(module._core_supertype_for_pair(pair, side="left"), "Person")
        self.assertEqual(module._core_supertype_for_pair(pair, side="right"), "Project")
        self.assertEqual(
            module._semantic_status(predicted_same=False, type_gate_passed=False),
            "type_mismatch",
        )

    def test_missing_sentence_transformer_dependency_is_preserved_as_data(self) -> None:
        module = _load_module()

        run = module.run_sentence_transformer(
            threshold=0.70,
            model_name="sentence-transformers/bert-base-nli-mean-tokens",
            model_profile=module.MODEL_PROFILES["legacy_cpu_bert"],
        )

        if run["package_status"]["available"]:
            self.skipTest("sentence_transformers is installed in this environment")
        self.assertEqual(run["status"], "blocked_missing_dependency")
        self.assertTrue(run["uses_neural_networks"])
        self.assertIsNone(run["metrics"])
        self.assertIn("sentence_transformers", run["blocker"])
        self.assertEqual(run["model_profile"]["profile_id"], "legacy_cpu_bert")

    def test_model_profiles_preserve_cpu_legacy_and_gpu_default(self) -> None:
        module = _load_module()

        cpu_profile = module.MODEL_PROFILES["legacy_cpu_bert"].to_dict()
        gpu_profile = module.MODEL_PROFILES["gpu_bge_large_en_v1_5"].to_dict()

        self.assertEqual(
            cpu_profile["default_model"],
            "sentence-transformers/bert-base-nli-mean-tokens",
        )
        self.assertIsNone(cpu_profile["minimum_gpu"])
        self.assertEqual(cpu_profile["default_threshold"], 0.70)
        self.assertEqual(gpu_profile["default_model"], "BAAI/bge-large-en-v1.5")
        self.assertEqual(gpu_profile["default_threshold"], 0.62)
        self.assertEqual(gpu_profile["minimum_gpu"], "NVIDIA GeForce GTX 1080 Ti")
        self.assertEqual(gpu_profile["minimum_vram_gb"], 11)

    def test_public_enterprise_benchmark_manifest_is_large_and_multisource(self) -> None:
        module = _load_module()

        manifest = module.load_public_enterprise_benchmark_manifest()

        self.assertEqual(
            manifest["artifact_id"],
            "formowl_kg_public_enterprise_benchmark_manifest_v1",
        )
        self.assertGreaterEqual(manifest["minimum_pair_count_for_model_selection"], 10_000)
        self.assertGreaterEqual(
            manifest["recommended_pair_count_for_stakeholder_claim"],
            50_000,
        )
        self.assertGreaterEqual(manifest["target_source_record_floor"], 1_000_000)
        self.assertEqual(
            set(manifest["source_family_targets"]),
            {
                "mail_conversation",
                "office_document",
                "financial_qa",
                "financial_report",
                "contract_document",
            },
        )
        self.assertTrue(manifest["claim_boundary"]["benchmark_sources_selected"])
        self.assertFalse(manifest["claim_boundary"]["large_benchmark_executed_by_this_artifact"])
        self.assertTrue(manifest["labeled_pair_generation"]["type_gate_regression_required"])

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
            self.assertTrue(payload["claim_boundary"]["stakeholder_evidence_artifact"])
            self.assertFalse(payload["claim_boundary"]["stakeholder_grade_claim"])
            self.assertEqual(payload["dataset"]["pair_count"], 16)
            self.assertTrue(payload["dataset"]["claim_boundary"]["small_fixture_only"])
            self.assertFalse(
                payload["dataset"]["claim_boundary"]["model_selection_sufficient_by_itself"]
            )
            self.assertEqual(
                payload["public_enterprise_benchmark"]["artifact_id"],
                "formowl_kg_public_enterprise_benchmark_manifest_v1",
            )
            self.assertEqual(
                payload["environment"]["default_model_profile"]["profile_id"],
                "gpu_bge_large_en_v1_5",
            )
            self.assertEqual(
                payload["environment"]["default_model_profile"]["default_model"],
                "BAAI/bge-large-en-v1.5",
            )
            self.assertEqual(payload["runs"][1]["threshold"], 0.62)
            self.assertEqual(payload["runs"][0]["status"], "completed")
            self.assertIn(payload["runs"][1]["status"], {"blocked_missing_dependency", "completed"})
            self.assertIn("torch", payload["environment"])
            self.assertIn("torch_status", payload["runs"][1])
            if payload["runs"][1]["status"] != "completed":
                self.assertEqual(payload["comparison"]["status"], "incomplete")

    def test_experiment_readme_points_active_commands_to_current_artifacts(self) -> None:
        readme = EXPERIMENT_README.read_text(encoding="utf-8")
        runtime_doc = RUNTIME_DOC.read_text(encoding="utf-8")
        method_doc = METHOD_DOC.read_text(encoding="utf-8")
        root_readme = ROOT_README.read_text(encoding="utf-8")

        self.assertIn(
            "kg_bert_ablation_2026-06-29_devcontainer_bge_manifest_no_bert_dependency.json",
            readme,
        )
        self.assertNotIn(
            "kg_bert_ablation_2026-06-29_devcontainer_no_bert_dependency.json",
            readme,
        )
        self.assertIn("kg_bert_ablation_bge_large_gpu_cu126_host.json", readme)
        self.assertNotIn(
            "--output experiments/kg_bert_ablation/results/kg_bert_ablation_bert_gpu",
            readme,
        )
        for document in (readme, runtime_doc, method_doc):
            self.assertIn(
                "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json",
                document,
            )
            self.assertIn("0.623245", document)
            self.assertIn("model-selection evidence", document)
        for document in (readme, runtime_doc, method_doc):
            self.assertIn(
                "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json",
                document,
            )
            self.assertIn("0.758664", document)
            self.assertIn("kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json", document)
            self.assertIn("0.757744", document)
            self.assertIn("candidate-only", document)
        for document in (readme, runtime_doc, method_doc, root_readme):
            self.assertIn("0.758664", document)
            self.assertIn("0.757744", document)
            self.assertIn("candidate-only", document)


if __name__ == "__main__":
    unittest.main()
