from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "graph_resolution_package_adapters_smoke.py"
)


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "graph_resolution_package_adapters_smoke",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load graph resolution package-adapter smoke script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GraphResolutionPackageAdaptersSmokeScriptTests(unittest.TestCase):
    def test_containerized_rapid_fuzz_adapter_smoke_valid_report_passes(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()

        validation = smoke.validate_report(report)

        self.assertTrue(validation["passed"])
        self.assertTrue(smoke.containerized_rapid_fuzz_adapter_smoke(report))

    def test_containerized_splink_adapter_smoke_valid_report_passes(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()

        validation = smoke.validate_report(report)

        self.assertTrue(validation["passed"])
        self.assertTrue(smoke.containerized_splink_adapter_smoke(report))

    def test_smoke_report_rejects_non_containerized_artifact(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["metrics"]["containerized_smoke_executed"] = False
        report["claim_boundary"]["supports_containerized_rapidfuzz_adapter_smoke_claim"] = False

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required metric failed: containerized_smoke_executed",
            validation["blockers"],
        )

    def test_smoke_report_rejects_production_or_canonical_overclaim(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["claim_boundary"]["supports_production_adapter_ready_claim"] = True
        report["claim_boundary"]["supports_canonical_graph_write_claim"] = True

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "forbidden claim true: supports_production_adapter_ready_claim",
            validation["blockers"],
        )
        self.assertIn(
            "forbidden claim true: supports_canonical_graph_write_claim",
            validation["blockers"],
        )

    def test_smoke_report_rejects_raw_path_or_sql_leak(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["safe_outputs"]["debug"] = "/workspace/private/customer.xlsx"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("public artifact leaks raw paths or SQL", validation["blockers"])

    def test_smoke_report_rejects_human_label_overclaim(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["claim_boundary"]["supports_human_reviewed_false_merge_labels_claim"] = True

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "forbidden claim true: supports_human_reviewed_false_merge_labels_claim",
            validation["blockers"],
        )


def _valid_report() -> dict:
    return {
        "artifact_id": "main_repo_graph_resolution_package_adapters_smoke_v1",
        "repo_reference": "main_repo_workspace",
        "repo_path_redacted": True,
        "image_reference": "formowl-dev:local",
        "safe_outputs": {
            "rapidfuzz_candidate_statuses": [
                {
                    "fusion_candidate_id": "fusion_rapid_fixture",
                    "status": "same_as_candidate",
                    "confidence": 1.0,
                }
            ],
            "splink_candidate_statuses": [
                {
                    "fusion_candidate_id": "fusion_splink_fixture",
                    "status": "same_as_candidate",
                    "confidence": 1.0,
                },
                {
                    "fusion_candidate_id": "fusion_splink_review_fixture",
                    "status": "below_threshold",
                    "confidence": 0.725,
                },
            ],
        },
        "metrics": {
            "containerized_smoke_executed": True,
            "rapidfuzz_package_imported": True,
            "splink_package_imported": True,
            "rapidfuzz_candidate_count": 1,
            "rapidfuzz_same_as_candidate_count": 1,
            "splink_candidate_count": 2,
            "splink_same_as_candidate_count": 1,
            "splink_clerical_review_item_count": 1,
            "human_clerical_review_queue_exported": True,
            "all_candidates_candidate_only": True,
            "no_raw_access_grants": True,
            "canonical_merge_guard_rejects": True,
            "raw_asset_read_guard_rejects": True,
            "no_canonical_writes": True,
            "raw_access_expanded": False,
            "raw_storage_path_exposed": False,
        },
        "claim_boundary": {
            "supports_main_repo_graph_resolution_package_adapter_smoke_claim": True,
            "supports_containerized_rapidfuzz_adapter_smoke_claim": True,
            "supports_containerized_splink_adapter_smoke_claim": True,
            "supports_fusion_candidate_generation_claim": True,
            "supports_human_clerical_review_queue_export_claim": True,
            "supports_human_reviewed_false_merge_labels_claim": False,
            "supports_splink_model_quality_claim": False,
            "supports_enterprise_scale_entity_resolution_claim": False,
            "supports_production_adapter_ready_claim": False,
            "supports_end_to_end_gateway_claim": False,
            "supports_canonical_graph_write_claim": False,
            "supports_raw_access_claim": False,
        },
    }


if __name__ == "__main__":
    unittest.main()
