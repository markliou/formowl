#!/usr/bin/env python3
"""Tests for external literature and baseline protocol recovery."""

from __future__ import annotations

from copy import deepcopy
import unittest

import external_literature_baseline_protocol_recovery as literature


class ExternalLiteratureBaselineProtocolRecoveryTest(unittest.TestCase):
    def test_default_literature_protocol_passes_without_overclaiming_runs(self) -> None:
        report = literature.build_report()

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["metrics"]["baseline_count"], 3)
        self.assertEqual(
            report["metrics"]["comparison_axis_count"], len(literature.REQUIRED_COMPARISON_AXES)
        )
        self.assertEqual(
            report["metrics"]["required_source_count"], len(literature.REQUIRED_SOURCE_IDS)
        )
        source_ids = {source["source_id"] for source in report["sources"]}
        self.assertIn("hipporag2_paper", source_ids)
        self.assertIn(
            "hipporag2_paper",
            literature.REQUIRED_SOURCE_IDS_BY_BASELINE["hipporag"],
        )
        source_lock_rows = literature.required_baseline_source_lock_rows()
        self.assertIn(
            {
                "source_id": "hipporag2_paper",
                "source_type": "paper",
                "year": 2025,
                "url": literature.REQUIRED_SOURCE_URLS["hipporag2_paper"],
            },
            source_lock_rows,
        )
        self.assertEqual(
            literature.required_baseline_source_lock_sha256(),
            literature.sha256_json(source_lock_rows),
        )
        hipporag = next(row for row in report["baselines"] if row["baseline_id"] == "hipporag")
        self.assertIn("hipporag2_paper", hipporag["source_ids"])
        self.assertTrue(
            report["claim_boundary"]["supports_external_recent_literature_comparison_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_fair_external_baseline_run_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_package_execution_claim"])
        self.assertFalse(
            report["claim_boundary"]["supports_human_adjudicated_answer_quality_claim"]
        )

    def test_missing_required_baseline_fails(self) -> None:
        fixture = literature.default_fixture()
        fixture["baselines"] = [
            row for row in fixture["baselines"] if row["baseline_id"] != "hipporag"
        ]

        report = literature.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("required baseline coverage mismatch", report["blockers"])

    def test_baseline_without_official_source_fails(self) -> None:
        fixture = literature.default_fixture()
        for row in fixture["baselines"]:
            if row["baseline_id"] == "lightrag":
                row["source_ids"] = ["lightrag_paper"]

        report = literature.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("lightrag official package/source evidence missing", report["blockers"])

    def test_required_source_url_mismatch_fails(self) -> None:
        fixture = literature.default_fixture()
        for source in fixture["sources"]:
            if source["source_id"] == "lightrag_repo":
                source["url"] = "https://example.com/not-the-official-lightrag-repository"

        report = literature.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn(
            "lightrag_repo source URL does not match locked reference", report["blockers"]
        )

    def test_non_recent_source_fails(self) -> None:
        fixture = literature.default_fixture()
        for source in fixture["sources"]:
            if source["source_id"] == "hipporag_paper":
                source["year"] = 2021

        report = literature.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("hipporag_paper is not a recent 2024-2026 source", report["blockers"])

    def test_missing_comparison_axis_fails(self) -> None:
        fixture = literature.default_fixture()
        fixture["comparison_axes"].remove("permission_and_user_graph_safety")

        report = literature.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("comparison axes are missing or not in the locked order", report["blockers"])

    def test_missing_axis_entry_for_each_baseline_fails(self) -> None:
        fixture = literature.default_fixture()
        for row in fixture["baselines"]:
            if row["baseline_id"] == "microsoft_graphrag":
                row["comparison"].pop("ontology_or_schema_grounding")

        report = literature.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn(
            "microsoft_graphrag comparison axis missing: ontology_or_schema_grounding",
            report["blockers"],
        )

    def test_literature_review_cannot_claim_real_baseline_execution(self) -> None:
        fixture = literature.default_fixture()
        fixture["claim_boundary"]["supports_fair_external_baseline_run_claim"] = True
        fixture["claim_boundary"]["supports_real_package_execution_claim"] = True

        report = literature.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn(
            "claim boundary overclaims unsupported evidence: supports_fair_external_baseline_run_claim",
            report["blockers"],
        )
        self.assertIn(
            "claim boundary overclaims unsupported evidence: supports_real_package_execution_claim",
            report["blockers"],
        )

    def test_protocol_cannot_count_papers_as_enterprise_validation(self) -> None:
        fixture = literature.default_fixture()
        fixture["fair_baseline_protocol"]["paper_claims_count_as_enterprise_validation"] = True
        fixture["fair_baseline_protocol"]["offline_matrix_counts_as_human_adjudication"] = True

        report = literature.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn(
            "fair baseline protocol permits unsupported evidence: paper_claims_count_as_enterprise_validation",
            report["blockers"],
        )
        self.assertIn(
            "fair baseline protocol permits unsupported evidence: offline_matrix_counts_as_human_adjudication",
            report["blockers"],
        )

    def test_protocol_hash_changes_when_source_or_baseline_changes(self) -> None:
        report = literature.build_report()
        fixture = literature.default_fixture()
        mutated = deepcopy(fixture)
        mutated["baselines"][0]["comparison"]["retrieval_strategy"] = (
            "degraded summary-only retrieval"
        )

        mutated_report = literature.build_report(mutated)

        self.assertNotEqual(report["protocol_sha256"], mutated_report["protocol_sha256"])


if __name__ == "__main__":
    unittest.main()
