from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import _paths  # noqa: F401

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "kg_first_cross_resource_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("kg_first_cross_resource_smoke", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load KG-first cross-resource smoke")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_module()


class KgFirstCrossResourceSmokeScriptTests(unittest.TestCase):
    def test_deterministic_mail_slide_project_smoke_passes(self) -> None:
        report = smoke.build_report()
        validation = smoke.validate_report(report)

        self.assertEqual(validation, {"status": "ok", "errors": []})
        self.assertTrue(report["metrics"]["smoke_passed"])
        self.assertEqual(
            report["safe_outputs"]["full_evidence_modalities"],
            ["mail", "project", "slide"],
        )
        self.assertEqual(
            report["safe_outputs"]["fallback_reason"],
            "graph_evidence_incomplete_fallback_used",
        )
        self.assertLess(report["safe_outputs"]["fallback_evidence_coverage"], 1.0)
        self.assertEqual(
            report["safe_outputs"]["fallback_matched_vector_ids"],
            ["vec_optoma_project_fallback"],
        )
        self.assertEqual(
            report["safe_outputs"]["fallback_seed_source_observation_ids"],
            ["obs_optoma_project_fallback"],
        )
        self.assertEqual(
            report["safe_outputs"]["fallback_seed_source_asset_ids"],
            ["asset_optoma_project_fallback"],
        )
        self.assertEqual(report["safe_outputs"]["full_matched_vector_ids"], [])
        self.assertEqual(report["metrics"]["kg_first_primary_vector_search_count"], 0)
        self.assertEqual(report["metrics"]["fallback_vector_search_count"], 1)
        self.assertEqual(report["safe_outputs"]["negative_graph_object_ids"], [])
        self.assertEqual(
            report["safe_outputs"]["negative_fallback_reason"],
            "graph_miss_fallback_used",
        )
        self.assertEqual(report["metrics"]["irrelevant_query_vector_search_count"], 1)
        self.assertFalse(report["claim_boundary"]["supports_canonical_graph_write_claim"])

    def test_validator_rejects_missing_fallback_seed(self) -> None:
        report = smoke.build_report()
        report["metrics"]["fallback_candidate_seed_count"] = 0

        validation = smoke.validate_report(report)

        self.assertEqual(validation["status"], "error")
        self.assertIn("missing_candidate_seed", validation["errors"])

    def test_validator_rejects_unproven_fallback_lineage(self) -> None:
        report = smoke.build_report()
        report["safe_outputs"]["fallback_reason"] = "graph_miss_fallback_used"
        report["safe_outputs"]["fallback_evidence_coverage"] = 1.0
        report["safe_outputs"]["fallback_matched_vector_ids"] = []
        report["safe_outputs"]["fallback_seed_source_observation_ids"] = ["obs_unrelated"]
        report["safe_outputs"]["fallback_seed_source_asset_ids"] = [
            "asset_untrusted_vector_metadata"
        ]

        validation = smoke.validate_report(report)

        self.assertEqual(validation["status"], "error")
        self.assertIn("invalid_fallback_reason", validation["errors"])
        self.assertIn("invalid_fallback_evidence_coverage", validation["errors"])
        self.assertIn("invalid_fallback_vector_lineage", validation["errors"])
        self.assertIn("invalid_fallback_seed_lineage", validation["errors"])
        self.assertIn("invalid_fallback_seed_asset_lineage", validation["errors"])

    def test_fixture_and_semantic_hashes_are_stable_across_repeated_builds(self) -> None:
        first = smoke.build_report()
        second = smoke.build_report()

        self.assertEqual(first["fixture_hash"], second["fixture_hash"])
        self.assertEqual(first["semantic_hash"], second["semantic_hash"])
        self.assertEqual(smoke.validate_report(first), {"status": "ok", "errors": []})
        self.assertEqual(smoke.validate_report(second), {"status": "ok", "errors": []})

    def test_validator_rejects_fixture_or_semantic_hash_tampering(self) -> None:
        report = smoke.build_report()
        report["fixture_hash"] = "sha256:tampered"

        validation = smoke.validate_report(report)

        self.assertEqual(validation["status"], "error")
        self.assertIn("invalid_fixture_hash", validation["errors"])
        self.assertIn("invalid_semantic_hash", validation["errors"])

    def test_validator_rejects_missing_kg_first_order_or_negative_control(self) -> None:
        report = smoke.build_report()
        report["metrics"]["kg_first_primary_vector_search_count"] = 1
        report["safe_outputs"]["full_matched_vector_ids"] = ["vec_optoma_project_fallback"]
        report["safe_outputs"]["negative_graph_object_ids"] = ["node_employee_handbook_distractor"]
        report["safe_outputs"]["negative_fallback_reason"] = None

        validation = smoke.validate_report(report)

        self.assertEqual(validation["status"], "error")
        self.assertIn("primary_vector_search_detected", validation["errors"])
        self.assertIn("unexpected_primary_vector_lineage", validation["errors"])
        self.assertIn("unexpected_negative_graph_hit", validation["errors"])
        self.assertIn("invalid_negative_fallback_reason", validation["errors"])

    def test_validator_rejects_canonical_or_production_overclaim(self) -> None:
        report = smoke.build_report()
        report["claim_boundary"]["supports_canonical_graph_write_claim"] = True
        report["claim_boundary"]["supports_production_readiness_claim"] = True

        validation = smoke.validate_report(report)

        self.assertEqual(validation["status"], "error")
        self.assertIn(
            "unsafe_claim:supports_canonical_graph_write_claim",
            validation["errors"],
        )
        self.assertIn(
            "unsafe_claim:supports_production_readiness_claim",
            validation["errors"],
        )

    def test_validator_rejects_raw_internal_leak(self) -> None:
        report = smoke.build_report()
        report["safe_outputs"]["debug"] = "/srv/private/customer.pst"

        validation = smoke.validate_report(report)

        self.assertEqual(validation["status"], "error")
        self.assertIn("raw_internal_leak", validation["errors"])


if __name__ == "__main__":
    unittest.main()
