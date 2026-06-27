#!/usr/bin/env python3
"""Tests for annotation protocol recovery controls."""

from __future__ import annotations

import unittest

import annotation_protocol_recovery as annotation


class AnnotationProtocolRecoveryTest(unittest.TestCase):
    def test_default_fixture_passes_protocol_controls_without_human_completion_claim(self) -> None:
        report = annotation.build_report()

        self.assertTrue(report["passed"])
        self.assertTrue(report["claim_boundary"]["supports_annotation_protocol_controls_claim"])
        self.assertFalse(report["claim_boundary"]["supports_human_annotation_completed_claim"])
        self.assertFalse(report["claim_boundary"]["supports_human_adjudication_completed_claim"])
        self.assertFalse(report["metrics"]["real_human_packet_present"])

    def test_single_first_pass_reviewer_fails(self) -> None:
        fixture = annotation.default_fixture()
        fixture["first_pass_rows"] = [
            row
            for row in fixture["first_pass_rows"]
            if not (
                row["item_id"] == "ann_item_invoice_001" and row["reviewer_id"] == "reviewer_beta"
            )
        ]

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn(
            "ann_item_invoice_001 does not have two distinct first-pass reviewers",
            report["blockers"],
        )

    def test_duplicate_manifest_item_id_fails(self) -> None:
        fixture = annotation.default_fixture()
        duplicate_manifest = {
            "item_id": "ann_item_invoice_001",
            "task_id": "evidence_supported_claim",
            "source_ref": "obs_mail_invoice_duplicate",
            "gold_label": "needs_review",
        }
        duplicate_manifest["row_sha256"] = annotation.row_hash(duplicate_manifest)
        fixture["manifest_rows"].append(duplicate_manifest)
        fixture["manifest_sha256"] = annotation.sha256_json(fixture["manifest_rows"])
        for work_order in fixture["work_order_rows"]:
            if work_order["item_id"] == "ann_item_invoice_001":
                work_order["manifest_row_sha256"] = duplicate_manifest["row_sha256"]
                work_order["row_sha256"] = annotation.row_hash(work_order)
        fixture["adjudication_open_receipt"]["manifest_sha256"] = fixture["manifest_sha256"]
        fixture["custody_receipt"]["manifest_sha256"] = fixture["manifest_sha256"]

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("duplicate manifest item id", report["blockers"])

    def test_synthetic_first_pass_label_fails(self) -> None:
        fixture = annotation.default_fixture()
        fixture["first_pass_rows"][0]["generated_by_llm"] = True
        fixture["first_pass_rows"][0]["row_sha256"] = annotation.row_hash(
            fixture["first_pass_rows"][0]
        )

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("first-pass row is synthetic or template-derived", report["blockers"])

    def test_work_order_mismatch_fails(self) -> None:
        fixture = annotation.default_fixture()
        fixture["first_pass_rows"][0]["work_order_id"] = "wo_beta_item_invoice"
        fixture["first_pass_rows"][0]["row_sha256"] = annotation.row_hash(
            fixture["first_pass_rows"][0]
        )

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("first-pass row work-order binding mismatch", report["blockers"])

    def test_duplicate_work_order_id_fails(self) -> None:
        fixture = annotation.default_fixture()
        duplicate = {
            "work_order_id": "wo_alpha_item_invoice",
            "reviewer_id": "reviewer_delta",
            "role": "first_pass",
            "item_id": "ann_item_invoice_001",
            "manifest_row_sha256": fixture["manifest_rows"][0]["row_sha256"],
        }
        duplicate["row_sha256"] = annotation.row_hash(duplicate)
        fixture["work_order_rows"].insert(0, duplicate)

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("duplicate work-order id", report["blockers"])

    def test_first_pass_work_order_item_mismatch_fails(self) -> None:
        fixture = annotation.default_fixture()
        fixture["first_pass_rows"][0]["work_order_id"] = "wo_alpha_item_decision"
        fixture["first_pass_rows"][0]["row_sha256"] = annotation.row_hash(
            fixture["first_pass_rows"][0]
        )
        fixture["custody_receipt"]["first_pass_rows_sha256"] = annotation.sha256_json(
            fixture["first_pass_rows"]
        )

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("first-pass row work-order item mismatch", report["blockers"])

    def test_missing_adjudication_open_receipt_fails(self) -> None:
        fixture = annotation.default_fixture()
        fixture.pop("adjudication_open_receipt")

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("adjudication-open receipt missing", report["blockers"])

    def test_unbound_sealed_first_pass_submission_artifacts_fail(self) -> None:
        fixture = annotation.default_fixture()
        fixture["first_pass_submission_artifacts"] = [
            {
                "reviewer_id": "reviewer_delta",
                "sealed": True,
                "submission_row_sha256s": [],
                "submission_set_sha256": annotation.sha256_json([]),
            },
            {
                "reviewer_id": "reviewer_epsilon",
                "sealed": True,
                "submission_row_sha256s": [],
                "submission_set_sha256": annotation.sha256_json([]),
            },
        ]

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("sealed submission reviewer/submission binding mismatch", report["blockers"])
        self.assertIn("sealed submission reviewer set mismatch", report["blockers"])

    def test_adjudication_outside_disagreement_set_fails(self) -> None:
        fixture = annotation.default_fixture()
        extra = dict(fixture["adjudication_rows"][0])
        extra["adjudication_id"] = "adj_invoice"
        extra["item_id"] = "ann_item_invoice_001"
        extra["work_order_id"] = "wo_adjudicator_item_decision"
        extra["row_sha256"] = annotation.row_hash(extra)
        fixture["adjudication_rows"].append(extra)
        fixture["custody_receipt"]["adjudication_rows_sha256"] = annotation.sha256_json(
            fixture["adjudication_rows"]
        )

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn(
            "adjudication rows do not cover exactly the sealed disagreement set",
            report["blockers"],
        )

    def test_zero_disagreement_fixture_without_adjudication_exercise_fails(self) -> None:
        fixture = annotation.default_fixture()
        fixture["first_pass_rows"][2]["label"] = "needs_review"
        fixture["first_pass_rows"][2]["row_sha256"] = annotation.row_hash(
            fixture["first_pass_rows"][2]
        )
        alpha_hashes = [
            row["row_sha256"]
            for row in fixture["first_pass_rows"]
            if row["reviewer_id"] == "reviewer_alpha"
        ]
        beta_hashes = [
            row["row_sha256"]
            for row in fixture["first_pass_rows"]
            if row["reviewer_id"] == "reviewer_beta"
        ]
        fixture["first_pass_submission_artifacts"][0]["submission_row_sha256s"] = alpha_hashes
        fixture["first_pass_submission_artifacts"][0]["submission_set_sha256"] = (
            annotation.sha256_json(sorted(alpha_hashes))
        )
        fixture["first_pass_submission_artifacts"][1]["submission_row_sha256s"] = beta_hashes
        fixture["first_pass_submission_artifacts"][1]["submission_set_sha256"] = (
            annotation.sha256_json(sorted(beta_hashes))
        )
        fixture["disagreement_set"] = []
        fixture["adjudication_rows"] = []
        empty_disagreement_hash = annotation.sha256_json([])
        fixture["adjudication_open_receipt"]["sealed_disagreement_set_sha256"] = (
            empty_disagreement_hash
        )
        fixture["custody_receipt"]["first_pass_rows_sha256"] = annotation.sha256_json(
            fixture["first_pass_rows"]
        )
        fixture["custody_receipt"]["adjudication_rows_sha256"] = annotation.sha256_json([])
        fixture["custody_receipt"]["sealed_disagreement_set_sha256"] = empty_disagreement_hash

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn(
            "annotation protocol fixture does not exercise adjudication disagreement",
            report["blockers"],
        )

    def test_duplicate_conflicting_adjudication_rows_fail(self) -> None:
        fixture = annotation.default_fixture()
        duplicate = dict(fixture["adjudication_rows"][0])
        duplicate["adjudication_id"] = "adj_decision_conflict"
        duplicate["final_label"] = "supported"
        duplicate["row_sha256"] = annotation.row_hash(duplicate)
        fixture["adjudication_rows"].append(duplicate)
        fixture["custody_receipt"]["adjudication_rows_sha256"] = annotation.sha256_json(
            fixture["adjudication_rows"]
        )

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("duplicate adjudication row for sealed disagreement item", report["blockers"])

    def test_adjudication_work_order_item_mismatch_fails(self) -> None:
        fixture = annotation.default_fixture()
        invoice_manifest_row = next(
            row for row in fixture["manifest_rows"] if row["item_id"] == "ann_item_invoice_001"
        )
        work_order = next(
            row
            for row in fixture["work_order_rows"]
            if row["work_order_id"] == "wo_adjudicator_item_decision"
        )
        work_order["item_id"] = "ann_item_invoice_001"
        work_order["manifest_row_sha256"] = invoice_manifest_row["row_sha256"]
        work_order["row_sha256"] = annotation.row_hash(work_order)

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("adjudication row work-order item mismatch", report["blockers"])

    def test_custody_receipt_mismatch_fails(self) -> None:
        fixture = annotation.default_fixture()
        fixture["custody_receipt"]["first_pass_rows_sha256"] = "0" * 64

        report = annotation.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("custody receipt first-pass rows mismatch", report["blockers"])


if __name__ == "__main__":
    unittest.main()
