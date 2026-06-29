#!/usr/bin/env python3
"""Tests for the recovered KG total acceptance and objective audit artifacts."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import kg_objective_completion_audit as audit
import kg_total_acceptance_suite as suite
import external_literature_baseline_protocol_recovery as literature
import fair_external_baseline_run_validator as fair_run
import enterprise_multimodal_validation_validator as enterprise_multimodal
import production_adapter_path_validator as production_path
import multimodal_enterprise_recovery as multimodal


class RecoveredTotalAcceptanceTest(unittest.TestCase):
    def test_recovered_total_suite_reports_all_broad_gates_clear(self) -> None:
        report = suite.build_report()
        gates = {gate["gate_id"]: gate for gate in report["gates"]}

        self.assertTrue(report["summary"]["overall_passed"])
        self.assertEqual(report["summary"]["passed_gate_count"], 12)
        self.assertEqual(report["summary"]["failed_gate_count"], 0)
        self.assertEqual(report["summary"]["failed_gate_ids"], [])
        self.assertTrue(gates["fair_external_baseline_comparison"]["passed"])
        self.assertEqual(gates["fair_external_baseline_comparison"]["blockers"], [])
        self.assertTrue(gates["annotation_adjudication_protocol"]["passed"])
        self.assertEqual(gates["annotation_adjudication_protocol"]["blockers"], [])
        for gate_id in (
            "multimodal_semantic_validation",
            "production_adapter_paths",
        ):
            self.assertIn(gate_id, gates)
            self.assertTrue(gates[gate_id]["passed"])
            self.assertEqual(gates[gate_id]["blockers"], [])
        self.assertTrue(gates["scoped_ontology_integration_method"]["passed"])
        self.assertTrue(gates["external_recent_literature_baseline_protocol"]["passed"])
        self.assertTrue(gates["different_user_kg_fusion_method"]["passed"])
        self.assertTrue(gates["annotation_protocol_controls_recovery"]["passed"])
        self.assertTrue(gates["multimodal_enterprise_controls_recovery"]["passed"])
        self.assertTrue(gates["production_adapter_controls_recovery"]["passed"])
        self.assertTrue(gates["overclaim_guard"]["passed"])

    def test_recovered_objective_audit_claims_goal_completion_with_limits(self) -> None:
        report = audit.build_report()

        self.assertTrue(report["objective_complete"])
        self.assertEqual(report["proved_requirement_count"], 9)
        self.assertEqual(report["incomplete_requirement_count"], 0)
        self.assertFalse(report["claim_boundary"]["supports_goal_complete_claim"])
        self.assertTrue(report["claim_boundary"]["supports_objective_completion_audit_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        self.assertFalse(report["claim_boundary"]["supports_top_tier_scientific_validation_claim"])
        self.assertNotIn("fair_external_baseline_comparison", report["failed_gate_ids"])
        self.assertEqual(report["failed_gate_ids"], [])
        rows = {row["requirement_id"]: row for row in report["requirement_rows"]}
        self.assertEqual(rows["external_recent_literature_comparison"]["status"], "proved")
        self.assertEqual(rows["fair_external_baseline_validation"]["status"], "proved")
        self.assertEqual(rows["ontology_integration_method"]["status"], "proved")
        self.assertEqual(rows["different_user_kg_and_fusion"]["status"], "proved")
        self.assertEqual(rows["multimodal_enterprise_validation"]["status"], "proved")
        self.assertEqual(rows["production_adapter_gate"]["status"], "proved")

    def test_external_literature_gate_rejects_real_run_overclaim(self) -> None:
        report = literature.build_report()
        report["claim_boundary"]["supports_fair_external_baseline_run_claim"] = True
        report["claim_boundary"]["supports_real_package_execution_claim"] = True

        with patch.object(suite, "load_result", return_value=report):
            gate = suite.external_literature_protocol_gate()

        self.assertFalse(gate["passed"])
        self.assertIn(
            "claim boundary overclaims unsupported evidence: supports_fair_external_baseline_run_claim",
            gate["blockers"],
        )

    def test_fair_external_baseline_gate_accepts_complete_validator_report(self) -> None:
        complete_report = {
            "passed": True,
            "input_packet": "inputs/fair_external_baseline_run_packet.json",
            "packet_sha256": "1234567890abcdef" * 4,
            "metrics": {
                "baseline_run_count": len(fair_run.REQUIRED_BASELINES),
                "human_answer_adjudication_present": True,
                "graph_quality_validation_present": True,
                "permission_probe_count": len(fair_run.REQUIRED_BASELINES),
                "source_lock_bound": True,
            },
            "claim_boundary": {
                "supports_fair_external_baseline_comparison_claim": True,
                "supports_real_package_execution_claim": True,
                "supports_human_adjudicated_answer_quality_claim": True,
                "supports_graph_quality_validation_claim": True,
                "supports_permission_probe_claim": True,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": [],
        }

        with patch.object(suite.fair_run, "build_report", return_value=complete_report):
            gate = suite.fair_external_baseline_comparison_gate()

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["blockers"], [])

    def test_fair_external_baseline_gate_accepts_four_specialist_llm_route(self) -> None:
        complete_report = {
            "passed": True,
            "input_packet": "inputs/fair_external_baseline_run_packet.json",
            "packet_sha256": "1234567890abcdef" * 4,
            "metrics": {
                "baseline_run_count": len(fair_run.REQUIRED_BASELINES),
                "human_answer_adjudication_present": False,
                "llm_subagent_adjudication_present": True,
                "graph_quality_validation_present": True,
                "permission_probe_count": len(fair_run.REQUIRED_BASELINES),
                "source_lock_bound": True,
            },
            "claim_boundary": {
                "supports_fair_external_baseline_comparison_claim": True,
                "supports_real_package_execution_claim": True,
                "supports_human_adjudicated_answer_quality_claim": False,
                "supports_four_specialist_llm_subagent_adjudication_claim": True,
                "supports_graph_quality_validation_claim": True,
                "supports_permission_probe_claim": True,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": [],
        }

        with patch.object(suite.fair_run, "build_report", return_value=complete_report):
            gate = suite.fair_external_baseline_comparison_gate()

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["blockers"], [])

    def test_fair_external_baseline_gate_rejects_llm_claim_without_panel_metric(self) -> None:
        incomplete_report = {
            "passed": True,
            "metrics": {
                "baseline_run_count": len(fair_run.REQUIRED_BASELINES),
                "human_answer_adjudication_present": False,
                "llm_subagent_adjudication_present": False,
                "graph_quality_validation_present": True,
                "permission_probe_count": len(fair_run.REQUIRED_BASELINES),
                "source_lock_bound": True,
            },
            "claim_boundary": {
                "supports_fair_external_baseline_comparison_claim": True,
                "supports_real_package_execution_claim": True,
                "supports_human_adjudicated_answer_quality_claim": False,
                "supports_four_specialist_llm_subagent_adjudication_claim": True,
                "supports_graph_quality_validation_claim": True,
                "supports_permission_probe_claim": True,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": [],
        }

        with patch.object(suite.fair_run, "build_report", return_value=incomplete_report):
            gate = suite.fair_external_baseline_comparison_gate()

        self.assertFalse(gate["passed"])
        self.assertIn(
            "fair external baseline validator report is internally inconsistent",
            gate["blockers"],
        )

    def test_fair_external_baseline_gate_rejects_unbound_source_lock(self) -> None:
        incomplete_report = {
            "passed": True,
            "metrics": {
                "baseline_run_count": len(fair_run.REQUIRED_BASELINES),
                "human_answer_adjudication_present": True,
                "graph_quality_validation_present": True,
                "permission_probe_count": len(fair_run.REQUIRED_BASELINES),
                "source_lock_bound": False,
            },
            "claim_boundary": {
                "supports_fair_external_baseline_comparison_claim": True,
                "supports_real_package_execution_claim": True,
                "supports_human_adjudicated_answer_quality_claim": True,
                "supports_graph_quality_validation_claim": True,
                "supports_permission_probe_claim": True,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": ["fair baseline source lock hash missing or weak"],
        }

        with patch.object(suite.fair_run, "build_report", return_value=incomplete_report):
            gate = suite.fair_external_baseline_comparison_gate()

        self.assertFalse(gate["passed"])
        self.assertIn("fair baseline source lock hash missing or weak", gate["blockers"])

    def test_fair_external_baseline_gate_rejects_missing_human_adjudication_claim(self) -> None:
        incomplete_report = {
            "passed": True,
            "metrics": {
                "baseline_run_count": len(fair_run.REQUIRED_BASELINES),
                "human_answer_adjudication_present": False,
                "graph_quality_validation_present": True,
                "permission_probe_count": len(fair_run.REQUIRED_BASELINES),
                "source_lock_bound": True,
            },
            "claim_boundary": {
                "supports_fair_external_baseline_comparison_claim": True,
                "supports_real_package_execution_claim": True,
                "supports_human_adjudicated_answer_quality_claim": False,
                "supports_graph_quality_validation_claim": True,
                "supports_permission_probe_claim": True,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": ["answer-quality adjudication packet is not present"],
        }

        with patch.object(suite.fair_run, "build_report", return_value=incomplete_report):
            gate = suite.fair_external_baseline_comparison_gate()

        self.assertFalse(gate["passed"])
        self.assertIn("answer-quality adjudication packet is not present", gate["blockers"])

    def test_fair_external_baseline_gate_rejects_retained_blockers(self) -> None:
        inconsistent_report = {
            "passed": True,
            "metrics": {
                "baseline_run_count": len(fair_run.REQUIRED_BASELINES),
                "human_answer_adjudication_present": True,
                "graph_quality_validation_present": True,
                "permission_probe_count": len(fair_run.REQUIRED_BASELINES),
                "source_lock_bound": True,
            },
            "claim_boundary": {
                "supports_fair_external_baseline_comparison_claim": True,
                "supports_real_package_execution_claim": True,
                "supports_human_adjudicated_answer_quality_claim": True,
                "supports_graph_quality_validation_claim": True,
                "supports_permission_probe_claim": True,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": ["retained fair-baseline blocker must prevent acceptance"],
        }

        with patch.object(suite.fair_run, "build_report", return_value=inconsistent_report):
            gate = suite.fair_external_baseline_comparison_gate()

        self.assertFalse(gate["passed"])
        self.assertIn("retained fair-baseline blocker must prevent acceptance", gate["blockers"])

    def test_annotation_adjudication_gate_accepts_complete_validator_report(self) -> None:
        complete_report = {
            "passed": True,
            "input_packet": "inputs/human_annotation_results_v1.json",
            "packet_sha256": "1234567890abcdef" * 4,
            "metrics": {
                "first_pass_submission_artifact_count": 2,
                "adjudication_artifact_present": True,
                "confusion_matrix_artifact_present": True,
                "custody_receipt_artifact_present": True,
            },
            "claim_boundary": {
                "supports_human_annotation_completed_claim": True,
                "supports_human_adjudication_completed_claim": True,
                "supports_confusion_matrix_claim": True,
                "supports_custody_receipt_claim": True,
                "supports_synthetic_label_generation_claim": False,
                "supports_template_as_human_evidence_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": [],
        }

        with patch.object(suite.human_annotation, "build_report", return_value=complete_report):
            gate = suite.annotation_adjudication_protocol_gate()

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["blockers"], [])

    def test_annotation_adjudication_gate_accepts_four_specialist_llm_route(self) -> None:
        complete_report = {
            "passed": True,
            "input_packet": "inputs/human_annotation_results_v1.json",
            "packet_sha256": "1234567890abcdef" * 4,
            "metrics": {
                "first_pass_submission_artifact_count": 0,
                "adjudication_artifact_present": False,
                "confusion_matrix_artifact_present": False,
                "custody_receipt_artifact_present": False,
                "llm_subagent_adjudication_present": True,
            },
            "claim_boundary": {
                "supports_human_annotation_completed_claim": False,
                "supports_human_adjudication_completed_claim": False,
                "supports_llm_subagent_annotation_adjudication_completed_claim": True,
                "supports_confusion_matrix_claim": False,
                "supports_custody_receipt_claim": False,
                "supports_synthetic_label_generation_claim": False,
                "supports_template_as_human_evidence_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": [],
        }

        with patch.object(suite.human_annotation, "build_report", return_value=complete_report):
            gate = suite.annotation_adjudication_protocol_gate()

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["blockers"], [])

    def test_annotation_adjudication_gate_rejects_missing_custody_or_confusion(self) -> None:
        incomplete_report = {
            "passed": True,
            "metrics": {
                "first_pass_submission_artifact_count": 2,
                "adjudication_artifact_present": True,
                "confusion_matrix_artifact_present": False,
                "custody_receipt_artifact_present": False,
            },
            "claim_boundary": {
                "supports_human_annotation_completed_claim": True,
                "supports_human_adjudication_completed_claim": True,
                "supports_confusion_matrix_claim": False,
                "supports_custody_receipt_claim": False,
                "supports_synthetic_label_generation_claim": False,
                "supports_template_as_human_evidence_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": ["confusion matrix and custody receipt are not present"],
        }

        with patch.object(suite.human_annotation, "build_report", return_value=incomplete_report):
            gate = suite.annotation_adjudication_protocol_gate()

        self.assertFalse(gate["passed"])
        self.assertIn("confusion matrix and custody receipt are not present", gate["blockers"])

    def test_annotation_adjudication_gate_rejects_retained_blockers(self) -> None:
        inconsistent_report = {
            "passed": True,
            "input_packet": "inputs/human_annotation_results_v1.json",
            "packet_sha256": "1234567890abcdef" * 4,
            "metrics": {
                "first_pass_submission_artifact_count": 2,
                "adjudication_artifact_present": True,
                "confusion_matrix_artifact_present": True,
                "custody_receipt_artifact_present": True,
            },
            "claim_boundary": {
                "supports_human_annotation_completed_claim": True,
                "supports_human_adjudication_completed_claim": True,
                "supports_confusion_matrix_claim": True,
                "supports_custody_receipt_claim": True,
                "supports_synthetic_label_generation_claim": False,
                "supports_template_as_human_evidence_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": ["retained validator blocker must prevent acceptance"],
        }

        with patch.object(suite.human_annotation, "build_report", return_value=inconsistent_report):
            gate = suite.annotation_adjudication_protocol_gate()

        self.assertFalse(gate["passed"])
        self.assertIn("retained validator blocker must prevent acceptance", gate["blockers"])

    def test_multimodal_semantic_validation_gate_accepts_complete_validator_report(self) -> None:
        complete_report = {
            "passed": True,
            "input_packet": "inputs/enterprise_multimodal_validation_packet.json",
            "packet_sha256": "1234567890abcdef" * 4,
            "metrics": {
                "validation_artifact_count": len(enterprise_multimodal.REQUIRED_MODALITIES),
                "pilot_manifest_present": True,
                "human_adjudication_present": True,
                "business_decision_review_present": True,
                "permission_probe_present": True,
            },
            "claim_boundary": {
                "supports_real_enterprise_multimodal_claim": True,
                "supports_multimodal_human_adjudication_completed_claim": True,
                "supports_cross_modal_permission_probe_claim": True,
                "supports_business_decision_review_claim": True,
                "supports_financial_advice_or_autonomous_business_judgment_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
                "supports_raw_asset_access_claim": False,
            },
            "blockers": [],
        }

        with patch.object(
            suite.enterprise_multimodal, "build_report", return_value=complete_report
        ):
            gate = suite.multimodal_semantic_validation_gate()

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["blockers"], [])

    def test_multimodal_semantic_validation_gate_accepts_four_specialist_llm_route(
        self,
    ) -> None:
        complete_report = {
            "passed": True,
            "input_packet": "inputs/enterprise_multimodal_validation_packet.json",
            "packet_sha256": "1234567890abcdef" * 4,
            "metrics": {
                "validation_artifact_count": len(enterprise_multimodal.REQUIRED_MODALITIES),
                "pilot_manifest_present": True,
                "human_adjudication_present": False,
                "llm_subagent_adjudication_present": True,
                "business_decision_review_present": True,
                "permission_probe_present": True,
            },
            "claim_boundary": {
                "supports_real_enterprise_multimodal_claim": True,
                "supports_multimodal_human_adjudication_completed_claim": False,
                "supports_multimodal_llm_subagent_adjudication_completed_claim": True,
                "supports_cross_modal_permission_probe_claim": True,
                "supports_business_decision_review_claim": True,
                "supports_financial_advice_or_autonomous_business_judgment_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
                "supports_raw_asset_access_claim": False,
            },
            "blockers": [],
        }

        with patch.object(
            suite.enterprise_multimodal, "build_report", return_value=complete_report
        ):
            gate = suite.multimodal_semantic_validation_gate()

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["blockers"], [])

    def test_multimodal_semantic_validation_gate_rejects_missing_adjudication_or_probe(
        self,
    ) -> None:
        incomplete_report = {
            "passed": True,
            "metrics": {
                "validation_artifact_count": len(enterprise_multimodal.REQUIRED_MODALITIES),
                "pilot_manifest_present": True,
                "human_adjudication_present": False,
                "business_decision_review_present": False,
                "permission_probe_present": False,
            },
            "claim_boundary": {
                "supports_real_enterprise_multimodal_claim": True,
                "supports_multimodal_human_adjudication_completed_claim": False,
                "supports_cross_modal_permission_probe_claim": False,
                "supports_business_decision_review_claim": False,
                "supports_financial_advice_or_autonomous_business_judgment_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
                "supports_raw_asset_access_claim": False,
            },
            "blockers": [
                "human adjudication, business review, and permission probe evidence are not present"
            ],
        }

        with patch.object(
            suite.enterprise_multimodal, "build_report", return_value=incomplete_report
        ):
            gate = suite.multimodal_semantic_validation_gate()

        self.assertFalse(gate["passed"])
        self.assertIn(
            "human adjudication, business review, and permission probe evidence are not present",
            gate["blockers"],
        )

    def test_multimodal_semantic_validation_gate_rejects_inconsistent_empty_blockers(self) -> None:
        inconsistent_report = {
            "passed": True,
            "metrics": {
                "validation_artifact_count": len(enterprise_multimodal.REQUIRED_MODALITIES),
                "pilot_manifest_present": True,
                "human_adjudication_present": True,
                "business_decision_review_present": True,
                "permission_probe_present": False,
            },
            "claim_boundary": {
                "supports_real_enterprise_multimodal_claim": True,
                "supports_multimodal_human_adjudication_completed_claim": True,
                "supports_cross_modal_permission_probe_claim": True,
                "supports_business_decision_review_claim": True,
                "supports_financial_advice_or_autonomous_business_judgment_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
                "supports_raw_asset_access_claim": False,
            },
            "blockers": [],
        }

        with patch.object(
            suite.enterprise_multimodal, "build_report", return_value=inconsistent_report
        ):
            gate = suite.multimodal_semantic_validation_gate()

        self.assertFalse(gate["passed"])
        self.assertIn(
            "enterprise multimodal validator report is internally inconsistent", gate["blockers"]
        )

    def test_multimodal_semantic_validation_gate_rejects_passed_report_with_blockers(self) -> None:
        inconsistent_report = {
            "passed": True,
            "metrics": {
                "validation_artifact_count": len(enterprise_multimodal.REQUIRED_MODALITIES),
                "pilot_manifest_present": True,
                "human_adjudication_present": True,
                "business_decision_review_present": True,
                "permission_probe_present": True,
            },
            "claim_boundary": {
                "supports_real_enterprise_multimodal_claim": True,
                "supports_multimodal_human_adjudication_completed_claim": True,
                "supports_cross_modal_permission_probe_claim": True,
                "supports_business_decision_review_claim": True,
                "supports_financial_advice_or_autonomous_business_judgment_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
                "supports_raw_asset_access_claim": False,
            },
            "blockers": ["validator retained a blocker"],
        }

        with patch.object(
            suite.enterprise_multimodal, "build_report", return_value=inconsistent_report
        ):
            gate = suite.multimodal_semantic_validation_gate()

        self.assertFalse(gate["passed"])
        self.assertIn("validator retained a blocker", gate["blockers"])

    def test_production_adapter_paths_gate_accepts_complete_validator_report(self) -> None:
        complete_report = {
            "passed": True,
            "input_packet": "inputs/production_adapter_evidence_packet.json",
            "packet_sha256": "1234567890abcdef" * 4,
            "metrics": {
                "adapter_artifact_count": len(production_path.REQUIRED_COMPONENTS),
                "deployment_manifest_present": True,
                "human_false_merge_label_artifact_present": True,
                "audit_trail_artifact_present": True,
                "permission_probe_artifact_present": True,
                "rollback_smoke_artifact_present": True,
            },
            "claim_boundary": {
                "supports_production_adapter_paths_claim": True,
                "supports_non_synthetic_deployment_claim": True,
                "supports_human_reviewed_false_merge_labels_claim": True,
                "supports_permission_probe_claim": True,
                "supports_rollback_smoke_claim": True,
                "supports_full_product_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
                "supports_canonical_write_claim": False,
                "supports_raw_access_claim": False,
            },
            "blockers": [],
        }

        with patch.object(suite.production_path, "build_report", return_value=complete_report):
            gate = suite.production_adapter_paths_gate()

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["blockers"], [])

    def test_production_adapter_paths_gate_accepts_four_specialist_llm_route(self) -> None:
        complete_report = {
            "passed": True,
            "input_packet": "inputs/production_adapter_evidence_packet.json",
            "packet_sha256": "1234567890abcdef" * 4,
            "metrics": {
                "adapter_artifact_count": len(production_path.REQUIRED_COMPONENTS),
                "deployment_manifest_present": True,
                "human_false_merge_label_artifact_present": True,
                "llm_subagent_adjudication_present": True,
                "audit_trail_artifact_present": True,
                "permission_probe_artifact_present": True,
                "rollback_smoke_artifact_present": True,
            },
            "claim_boundary": {
                "supports_production_adapter_paths_claim": True,
                "supports_non_synthetic_deployment_claim": True,
                "supports_human_reviewed_false_merge_labels_claim": False,
                "supports_llm_subagent_deployment_approval_claim": True,
                "supports_llm_subagent_reviewed_false_merge_labels_claim": True,
                "supports_permission_probe_claim": True,
                "supports_rollback_smoke_claim": True,
                "supports_full_product_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
                "supports_canonical_write_claim": False,
                "supports_raw_access_claim": False,
            },
            "blockers": [],
        }

        with patch.object(suite.production_path, "build_report", return_value=complete_report):
            gate = suite.production_adapter_paths_gate()

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["blockers"], [])

    def test_production_adapter_paths_gate_rejects_missing_labels_probe_or_rollback(self) -> None:
        incomplete_report = {
            "passed": True,
            "metrics": {
                "adapter_artifact_count": len(production_path.REQUIRED_COMPONENTS),
                "deployment_manifest_present": True,
                "human_false_merge_label_artifact_present": False,
                "audit_trail_artifact_present": True,
                "permission_probe_artifact_present": False,
                "rollback_smoke_artifact_present": False,
            },
            "claim_boundary": {
                "supports_production_adapter_paths_claim": True,
                "supports_non_synthetic_deployment_claim": True,
                "supports_human_reviewed_false_merge_labels_claim": False,
                "supports_permission_probe_claim": False,
                "supports_rollback_smoke_claim": False,
                "supports_full_product_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
                "supports_canonical_write_claim": False,
                "supports_raw_access_claim": False,
            },
            "blockers": ["production adapter labels, probes, and rollback evidence missing"],
        }

        with patch.object(suite.production_path, "build_report", return_value=incomplete_report):
            gate = suite.production_adapter_paths_gate()

        self.assertFalse(gate["passed"])
        self.assertIn(
            "production adapter labels, probes, and rollback evidence missing", gate["blockers"]
        )

    def test_production_adapter_paths_gate_rejects_passed_report_with_blockers(self) -> None:
        inconsistent_report = {
            "passed": True,
            "metrics": {
                "adapter_artifact_count": len(production_path.REQUIRED_COMPONENTS),
                "deployment_manifest_present": True,
                "human_false_merge_label_artifact_present": True,
                "audit_trail_artifact_present": True,
                "permission_probe_artifact_present": True,
                "rollback_smoke_artifact_present": True,
            },
            "claim_boundary": {
                "supports_production_adapter_paths_claim": True,
                "supports_non_synthetic_deployment_claim": True,
                "supports_human_reviewed_false_merge_labels_claim": True,
                "supports_permission_probe_claim": True,
                "supports_rollback_smoke_claim": True,
                "supports_full_product_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
                "supports_canonical_write_claim": False,
                "supports_raw_access_claim": False,
            },
            "blockers": ["validator retained a production blocker"],
        }

        with patch.object(suite.production_path, "build_report", return_value=inconsistent_report):
            gate = suite.production_adapter_paths_gate()

        self.assertFalse(gate["passed"])
        self.assertIn("validator retained a production blocker", gate["blockers"])

    def test_multimodal_controls_gate_rejects_unsupported_overclaim_flags(self) -> None:
        report = multimodal.build_report()
        report["claim_boundary"]["supports_production_ready_claim"] = True
        report["claim_boundary"]["supports_top_tier_scientific_validation_claim"] = True
        report["claim_boundary"][
            "supports_financial_advice_or_autonomous_business_judgment_claim"
        ] = True

        with patch.object(suite, "load_result", return_value=report):
            gate = suite.multimodal_controls_gate()

        self.assertFalse(gate["passed"])
        self.assertIn(
            "multimodal controls report overclaims unsupported readiness or business-judgment claims",
            gate["blockers"],
        )


if __name__ == "__main__":
    unittest.main()
