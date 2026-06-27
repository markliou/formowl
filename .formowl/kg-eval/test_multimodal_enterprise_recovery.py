#!/usr/bin/env python3
"""Tests for multimodal enterprise recovery controls."""

from __future__ import annotations

import unittest

import multimodal_enterprise_recovery as multimodal


class MultimodalEnterpriseRecoveryTest(unittest.TestCase):
    def test_default_fixture_passes_controls_without_enterprise_claim(self) -> None:
        report = multimodal.build_report()

        self.assertTrue(report["passed"])
        self.assertTrue(report["claim_boundary"]["supports_multimodal_control_fixture_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_enterprise_multimodal_claim"])
        self.assertFalse(report["claim_boundary"]["supports_multimodal_human_adjudication_completed_claim"])
        self.assertEqual(report["metrics"]["covered_modality_count"], 4)
        self.assertFalse(report["metrics"]["real_enterprise_pilot_present"])

    def test_missing_required_modality_fails(self) -> None:
        fixture = multimodal.default_fixture()
        fixture["source_artifacts"] = [
            row for row in fixture["source_artifacts"] if row["modality"] != "video_ocr"
        ]

        report = multimodal.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("missing required modalities: video_ocr", report["blockers"])

    def test_text_proxy_only_source_fails(self) -> None:
        fixture = multimodal.default_fixture()
        fixture["source_artifacts"][0]["text_proxy_only"] = True

        report = multimodal.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("source artifact is text-proxy-only", report["blockers"])

    def test_validation_row_source_hash_mismatch_fails(self) -> None:
        fixture = multimodal.default_fixture()
        fixture["validation_rows"][0]["source_artifact_sha256"] = "9" * 64
        fixture["validation_rows"][0]["row_sha256"] = multimodal.row_hash(
            fixture["validation_rows"][0]
        )

        report = multimodal.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("validation row source artifact hash mismatch", report["blockers"])

    def test_business_decision_without_human_review_requirement_fails(self) -> None:
        fixture = multimodal.default_fixture()
        fixture["business_decision_rows"][0]["adjudication_status"] = "auto_accepted"
        fixture["business_decision_rows"][0]["autonomous_business_judgment"] = True
        fixture["business_decision_rows"][0]["row_sha256"] = multimodal.row_hash(
            fixture["business_decision_rows"][0]
        )

        report = multimodal.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("business decision row does not require human review", report["blockers"])
        self.assertIn("business decision row allows autonomous judgment", report["blockers"])

    def test_cross_modal_permission_leak_fails(self) -> None:
        fixture = multimodal.default_fixture()
        fixture["permission_probe"]["cross_modal_private_leak_count"] = 1
        fixture["permission_probe"]["raw_asset_access_observed"] = True

        report = multimodal.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("cross-modal permission probe leaks private content", report["blockers"])
        self.assertIn("cross-modal permission probe exposes raw asset access", report["blockers"])


if __name__ == "__main__":
    unittest.main()
