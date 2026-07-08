from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import _paths  # noqa: F401

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "ontology_v2_coordination_frame_experiment.py"
)


def _load_module(module_name: str = "ontology_v2_coordination_frame_experiment"):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ontology v2 experiment script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class OntologyV2CoordinationFrameExperimentTests(unittest.TestCase):
    def test_default_fixture_experiment_improves_competency_answerability(self) -> None:
        module = _load_module()

        report = module.run_experiment()

        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
        safe = report["safe_outputs"]
        self.assertEqual(safe["scenario_count"], 4)
        self.assertGreaterEqual(safe["domain_pack_count"], 6)
        self.assertEqual(safe["competency_question_count"], 10)
        self.assertEqual(safe["total_question_case_count"], 40)
        self.assertEqual(safe["v1_answerable_count"], 16)
        self.assertEqual(safe["v2_answerable_count"], 40)
        self.assertEqual(safe["v2_delta_answerable_count"], 24)
        self.assertEqual(safe["v2_arm"], "ontology_v2_coordination_frame_path")
        self.assertFalse(report["claim_boundary"]["supports_canonical_kg_write_claim"])
        self.assertFalse(report["claim_boundary"]["supports_wiki_projection_claim"])
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("deliver revised quotation", rendered)
        self.assertNotIn("archive.pst", rendered)
        self.assertNotIn("C:/", rendered)

    def test_validate_report_rejects_stale_answerability_counts(self) -> None:
        module = _load_module()
        report = copy.deepcopy(module.run_experiment())
        report["safe_outputs"]["v2_answerable_count"] -= 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("safe_outputs.v2_delta_answerable_count mismatch", validation["blockers"])

    def test_cli_run_and_validate_report(self) -> None:
        module = _load_module()
        temp_dir = _paths.fresh_test_dir("ontology-v2-coordination-cli")
        report_path = temp_dir / "report.json"
        validation_path = temp_dir / "validation.json"

        run_exit = module.main(["--output", str(report_path)])
        validate_exit = module.main(
            [
                "--validate-report",
                str(report_path),
                "--output",
                str(validation_path),
            ]
        )

        self.assertEqual(run_exit, 0)
        self.assertEqual(validate_exit, 0)
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertTrue(validation["passed"], validation["blockers"])


if __name__ == "__main__":
    unittest.main()
