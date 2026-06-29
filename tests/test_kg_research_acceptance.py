from __future__ import annotations

import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_graph.research_acceptance import (
    AcceptanceItem,
    report_to_json,
    run_kg_research_acceptance_suite,
)


class KGResearchAcceptanceTests(unittest.TestCase):
    def test_acceptance_suite_marks_passed_failed_and_blocked_items(self) -> None:
        report = run_kg_research_acceptance_suite()
        data = report.to_dict()
        statuses = {item["requirement_id"]: item["status"] for item in data["items"]}
        expected_statuses = {
            "external_recent_literature_comparison": "passed",
            "ontology_integration_method": "passed",
            "multi_user_kg_fusion_experiment": "passed",
            "multimodal_enterprise_resource_validation": "passed",
            "review_adjudication_claim_boundary": "passed",
            "production_adapter_candidate_only_boundary": "passed",
            "production_adapter_readiness": "failed",
            "metrics_ablations_error_analysis": "passed",
            "latency_scalability_enterprise_claims": "blocked",
        }

        self.assertEqual(statuses, expected_statuses)
        self.assertEqual(data["known_failed_requirement_ids"], ["production_adapter_readiness"])
        self.assertEqual(
            data["known_blocked_requirement_ids"],
            ["latency_scalability_enterprise_claims"],
        )
        self.assertEqual(data["unexpected_failed_requirement_ids"], [])
        self.assertEqual(data["unexpected_blocked_requirement_ids"], [])
        self.assertEqual(data["missing_expected_limit_requirement_ids"], [])
        self.assertEqual(data["overall_status"], "passed_with_explicit_limits")
        metrics_item = _item(data, "metrics_ablations_error_analysis")
        self.assertEqual(metrics_item["metrics"]["ablation_count"], 4)
        self.assertEqual(metrics_item["metrics"]["error_case_count"], 4)
        self.assertEqual(
            set(metrics_item["metrics"]["error_cases"]),
            {
                "same_label_different_core_supertype",
                "hidden_endpoint_visible_without_grant",
                "package_output_treated_as_truth",
                "alignment_without_provenance",
            },
        )

    def test_acceptance_suite_fails_overall_on_unexpected_failed_requirement(self) -> None:
        unexpected_item = AcceptanceItem(
            requirement_id="external_recent_literature_comparison",
            status="failed",
            summary="Simulated literature regression.",
            evidence=["docs/kg-research-method.md"],
            metrics={},
        )

        with patch(
            "formowl_graph.research_acceptance._literature_item", return_value=unexpected_item
        ):
            data = run_kg_research_acceptance_suite().to_dict()

        self.assertEqual(data["overall_status"], "failed")
        self.assertIn(
            "external_recent_literature_comparison",
            data["unexpected_failed_requirement_ids"],
        )

    def test_acceptance_report_is_json_and_does_not_leak_raw_backend_text(self) -> None:
        rendered = report_to_json(run_kg_research_acceptance_suite())
        data = json.loads(rendered)
        self.assertEqual(data["suite_id"], "kg_research_acceptance_suite_v1")

        forbidden = (
            "/home/",
            "/tmp/",
            "/workspace/",
            "postgres://",
            "postgresql://",
            "SELECT ",
            "raw_path",
            "worker_scratch",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, rendered)

    def test_acceptance_script_default_succeeds_and_strict_fails_on_known_limits(self) -> None:
        default = subprocess.run(
            [sys.executable, "scripts/kg_research_acceptance_suite.py"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertIn("kg_research_acceptance_suite_v1", default.stdout)

        strict = subprocess.run(
            [sys.executable, "scripts/kg_research_acceptance_suite.py", "--strict"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(strict.returncode, 1)
        self.assertIn("production_adapter_readiness", strict.stdout)


def _item(data: dict[str, object], requirement_id: str) -> dict[str, object]:
    items = data["items"]
    if not isinstance(items, list):
        raise AssertionError("items must be a list")
    for item in items:
        if isinstance(item, dict) and item.get("requirement_id") == requirement_id:
            return item
    raise AssertionError(f"missing acceptance item {requirement_id}")


if __name__ == "__main__":
    unittest.main()
