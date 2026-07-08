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
        self.assertEqual(safe["mention_only_count"], 4)
        self.assertEqual(safe["candidate_frame_count"], 21)
        self.assertGreaterEqual(safe["candidate_frame_type_count"], 6)
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

    def test_validate_report_rejects_missing_mention_only_coverage(self) -> None:
        module = _load_module()
        report = copy.deepcopy(module.run_experiment())
        report["safe_outputs"]["mention_only_count"] = 3

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.mention_only_count must cover every scenario",
            validation["blockers"],
        )

    def test_validate_report_rejects_case_without_mention_only_coverage(self) -> None:
        module = _load_module()
        report = copy.deepcopy(module.run_experiment())
        report["safe_outputs"]["case_rows"][0]["mention_only_count"] = 0

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.case_rows must include mention-only coverage for every scenario",
            validation["blockers"],
        )

    def test_validate_report_rejects_stale_fixture_bound_hashes(self) -> None:
        module = _load_module()
        report = copy.deepcopy(module.run_experiment())
        report["safe_outputs"]["fixture_hash"] = "sha256:stale_fixture"
        report["safe_outputs"]["case_row_hash"] = "sha256:stale_case_rows"

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.fixture_hash must match current fixture",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.case_row_hash must match current fixture",
            validation["blockers"],
        )

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

    def test_cli_validate_report_uses_requested_fixture(self) -> None:
        module = _load_module()
        temp_dir = _paths.fresh_test_dir("ontology-v2-coordination-custom-fixture-cli")
        fixture = json.loads(module.DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))
        fixture["cases"][0]["body_lines"][-1] = fixture["cases"][0]["body_lines"][-1].replace(
            "background collateral only",
            "background collateral only for custom fixture",
        )
        custom_fixture_path = temp_dir / "custom-fixture.json"
        custom_fixture_path.write_text(
            json.dumps(fixture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = temp_dir / "custom-report.json"
        default_validation_path = temp_dir / "default-validation.json"
        custom_validation_path = temp_dir / "custom-validation.json"

        self.assertEqual(
            module.main(["--fixture", str(custom_fixture_path), "--output", str(report_path)]),
            0,
        )
        self.assertEqual(
            module.main(
                [
                    "--validate-report",
                    str(report_path),
                    "--output",
                    str(default_validation_path),
                ]
            ),
            1,
        )
        self.assertEqual(
            module.main(
                [
                    "--fixture",
                    str(custom_fixture_path),
                    "--validate-report",
                    str(report_path),
                    "--output",
                    str(custom_validation_path),
                ]
            ),
            0,
        )
        validation = json.loads(custom_validation_path.read_text(encoding="utf-8"))
        self.assertTrue(validation["passed"], validation["blockers"])


if __name__ == "__main__":
    unittest.main()
