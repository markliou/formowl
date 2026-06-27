#!/usr/bin/env python3
"""Tests for scoped ontology and different-user KG fusion recovery experiments."""

from __future__ import annotations

from copy import deepcopy
import unittest

import scoped_ontology_integration_recovery as ontology
import user_graph_fusion_recovery as fusion


class ScopedOntologyIntegrationRecoveryTest(unittest.TestCase):
    def test_default_fixture_passes_scoped_ontology_controls(self) -> None:
        report = ontology.build_report()

        self.assertTrue(report["passed"])
        self.assertTrue(
            report["claim_boundary"]["supports_scoped_ontology_integration_method_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_company_wide_ontology_claim"])
        self.assertFalse(report["claim_boundary"]["supports_llm_direct_type_commit_claim"])
        self.assertEqual(report["metrics"]["schema_violation_count"], 0)

    def test_candidate_missing_ontology_revision_pin_fails(self) -> None:
        fixture = ontology.default_fixture()
        fixture["candidate_type_rows"][0]["ontology_revision_id"] = "ontology_rev_stale"

        report = ontology.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("candidate type row ontology revision mismatch", report["blockers"])

    def test_relation_schema_violation_fails(self) -> None:
        fixture = ontology.default_fixture()
        fixture["relation_rows"][0]["target_type_id"] = "type:meeting_decision"

        report = ontology.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("typed relation target type violates schema", report["blockers"])

    def test_unreviewed_llm_direct_type_commit_fails(self) -> None:
        fixture = ontology.default_fixture()
        fixture["candidate_type_rows"][0]["llm_direct_commit"] = True

        report = ontology.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("candidate type row allows LLM direct commit", report["blockers"])

    def test_unscoped_extension_type_fails(self) -> None:
        fixture = ontology.default_fixture()
        fixture["scoped_extension_types"][0]["type_id"] = "type:invoice_escalation"
        fixture["candidate_type_rows"][0]["proposed_type_id"] = "type:invoice_escalation"

        report = ontology.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("scoped extension type id is not scoped", report["blockers"])


class UserGraphFusionRecoveryTest(unittest.TestCase):
    def test_default_fixture_passes_candidate_only_permissioned_fusion_controls(self) -> None:
        report = fusion.build_report()

        self.assertTrue(report["passed"])
        self.assertTrue(
            report["claim_boundary"]["supports_different_user_kg_fusion_method_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_full_automatic_kg_merge_claim"])
        self.assertFalse(report["claim_boundary"]["supports_raw_data_fusion_without_grants_claim"])
        self.assertEqual(report["metrics"]["distinct_user_count"], 2)
        self.assertEqual(report["metrics"]["cross_user_edge_leak_count"], 0)

    def test_silent_canonical_merge_fails(self) -> None:
        fixture = fusion.default_fixture()
        fixture["fusion_candidates"][0]["canonical_merge_executed"] = True

        report = fusion.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("fusion candidate executed canonical merge", report["blockers"])

    def test_raw_access_granted_by_entity_match_fails(self) -> None:
        fixture = fusion.default_fixture()
        fixture["fusion_candidates"][0]["raw_access_granted_by_match"] = True

        report = fusion.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("fusion candidate grants raw access by match", report["blockers"])

    def test_revoked_grant_after_index_leak_fails(self) -> None:
        fixture = fusion.default_fixture()
        fixture["effective_view_checks"][1]["observed_visible_atom_ids"] = ["atom_account_orion"]
        fixture["revocation_probe"]["visible_after_revocation_count"] = 1
        fixture["revocation_probe"]["passed"] = False

        report = fusion.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("revoked grant still exposes graph atoms", report["blockers"])
        self.assertIn("revocation-after-index probe exposed revoked atoms", report["blockers"])

    def test_private_atom_leak_fails(self) -> None:
        fixture = fusion.default_fixture()
        fixture["effective_view_checks"][0]["observed_private_atom_ids"] = [
            "atom_private_invoice_note"
        ]

        report = fusion.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("effective view leaked private atoms", report["blockers"])

    def test_private_atom_leak_through_visible_lists_fails(self) -> None:
        fixture = fusion.default_fixture()
        fixture["effective_view_checks"][0]["expected_visible_atom_ids"].append(
            "atom_private_invoice_note"
        )
        fixture["effective_view_checks"][0]["observed_visible_atom_ids"].append(
            "atom_private_invoice_note"
        )

        report = fusion.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("effective view visible atom list includes private atoms", report["blockers"])

    def test_missing_conflict_surface_fails(self) -> None:
        fixture = deepcopy(fusion.default_fixture())
        fixture["fusion_candidates"][0]["conflict_id"] = ""

        report = fusion.build_report(fixture)

        self.assertFalse(report["passed"])
        self.assertIn("fusion candidate does not surface conflict id", report["blockers"])


if __name__ == "__main__":
    unittest.main()
