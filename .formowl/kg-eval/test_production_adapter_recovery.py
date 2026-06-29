#!/usr/bin/env python3
"""Tests for production adapter recovery controls."""

from __future__ import annotations

import unittest

import production_adapter_recovery as production


class ProductionAdapterRecoveryTest(unittest.TestCase):
    def test_default_fixture_passes_controls_without_production_claim(self) -> None:
        report = production.build_report()

        self.assertTrue(report["passed"])
        self.assertTrue(
            report["claim_boundary"]["supports_production_adapter_control_fixture_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        self.assertFalse(report["metrics"]["non_synthetic_deployment_present"])

    def test_missing_required_audit_control_fails(self) -> None:
        fixture = production.default_fixture()
        fixture["audit_events"] = [
            row
            for row in fixture["audit_events"]
            if row["action"] != "raw_asset_read_guard_rejected"
        ]

        report = production.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("production audit control sequence mismatch", report["blockers"])

    def test_empty_fixture_fails(self) -> None:
        report = production.build_report({})

        self.assertFalse(report["passed"])
        self.assertIn(
            "production fixture request/resource/policy binding missing", report["blockers"]
        )
        self.assertIn("production audit events missing", report["blockers"])

    def test_empty_request_resource_policy_binding_fails(self) -> None:
        fixture = production.default_fixture()
        fixture["request_id"] = None
        fixture["resource_ref"] = None
        fixture["policy_id"] = None
        for row in fixture["audit_events"]:
            row["request_id"] = None
            row["resource_ref"] = None
            row["policy_id"] = None
            row["row_sha256"] = production.row_hash(row)

        report = production.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production fixture request/resource/policy binding missing", report["blockers"]
        )

    def test_revoked_grant_not_denied_fails(self) -> None:
        fixture = production.default_fixture()
        row = next(
            row
            for row in fixture["audit_events"]
            if row["action"] == "revoked_grant_blocks_content"
        )
        row["decision"] = "allow"
        row["row_sha256"] = production.row_hash(row)

        report = production.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("revoked grant control does not deny content", report["blockers"])

    def test_canonical_or_raw_guard_allows_fails(self) -> None:
        fixture = production.default_fixture()
        for action in ("canonical_merge_guard_rejected", "raw_asset_read_guard_rejected"):
            row = next(row for row in fixture["audit_events"] if row["action"] == action)
            row["decision"] = "allow"
            row["row_sha256"] = production.row_hash(row)

        report = production.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn(
            "canonical_merge_guard_rejected is not an explicit deny guard", report["blockers"]
        )
        self.assertIn(
            "raw_asset_read_guard_rejected is not an explicit deny guard", report["blockers"]
        )

    def test_wiki_projection_published_fails(self) -> None:
        fixture = production.default_fixture()
        row = next(
            row
            for row in fixture["audit_events"]
            if row["action"] == "wiki_projection_draft_not_published"
        )
        row["published"] = True
        row["row_sha256"] = production.row_hash(row)

        report = production.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("wiki projection control did not remain draft-only", report["blockers"])

    def test_fixture_overclaim_flags_fail(self) -> None:
        fixture = production.default_fixture()
        fixture["claim_boundary"]["supports_production_ready_claim"] = True
        fixture["claim_boundary"]["supports_raw_access_claim"] = True

        report = production.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter fixture overclaims supports_production_ready_claim",
            report["blockers"],
        )
        self.assertIn(
            "production adapter fixture overclaims supports_raw_access_claim",
            report["blockers"],
        )


if __name__ == "__main__":
    unittest.main()
