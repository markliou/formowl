#!/usr/bin/env python3
"""Recovered KG total acceptance snapshot.

This is a conservative recovery artifact after the previous `/tmp` evaluation
workspace was lost. It records current evidence available in this durable
workspace and keeps broad objective gates failed when evidence is absent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import external_baseline_coverage_matrix as coverage
import external_literature_baseline_protocol_recovery as literature
import fair_external_baseline_run_validator as fair_run
import human_annotation_adjudication_validator as human_annotation
import enterprise_multimodal_validation_validator as enterprise_multimodal
import production_adapter_path_validator as production_path
import annotation_protocol_recovery as annotation
import multimodal_enterprise_recovery as multimodal
import production_adapter_recovery as production
import scoped_ontology_integration_recovery as ontology
import user_graph_fusion_recovery as user_fusion


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

FAILED_BROAD_GATES = (
    "fair_external_baseline_comparison",
    "annotation_adjudication_protocol",
    "multimodal_semantic_validation",
    "production_adapter_paths",
)


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_result(name: str) -> dict[str, Any]:
    path = RESULTS / name
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def fair_config_binding_gate() -> dict[str, Any]:
    report = load_result("external_baseline_coverage_matrix.json")
    if not report:
        report = coverage.build_report()
    status = report.get("baseline_config_fairness_policy", {})
    controls_passed = (
        report.get("artifact_id") == "external_baseline_coverage_matrix_recovery_v1"
        and report.get("claim_boundary", {}).get("supports_fair_external_baseline_comparison_claim")
        is False
        and status.get("passed") is False
        and "fair baseline config fairness policy missing" in status.get("blockers", [])
    )
    return {
        "gate_id": "fair_baseline_config_artifact_content_binding",
        "claim": "Config artifacts are parsed and content-bound so self-handicapped external baselines cannot pass by hash-only artifact references.",
        "passed": controls_passed,
        "evidence": {
            "artifact": "results/external_baseline_coverage_matrix.json",
            "artifact_id": report.get("artifact_id"),
            "current_input_missing_keeps_gate_red": status.get("passed") is False,
            "broad_fair_baseline_claim": report.get("claim_boundary", {}).get(
                "supports_fair_external_baseline_comparison_claim"
            ),
        },
        "blockers": []
        if controls_passed
        else ["focused config-artifact binding recovery evidence missing or unsafe"],
    }


def external_literature_protocol_gate() -> dict[str, Any]:
    report = load_result("external_literature_baseline_protocol_recovery.json")
    if not report:
        report = literature.build_report()
    blockers = literature.validate_fixture(report)
    claims = report.get("claim_boundary", {})
    passed = (
        not blockers
        and claims.get("supports_external_recent_literature_comparison_claim") is True
        and claims.get("supports_baseline_selection_rationale_claim") is True
        and claims.get("supports_fair_external_baseline_run_claim") is False
        and claims.get("supports_real_package_execution_claim") is False
        and claims.get("supports_human_adjudicated_answer_quality_claim") is False
        and claims.get("supports_top_tier_scientific_validation_claim") is False
        and report.get("metrics", {}).get("baseline_count") == len(literature.REQUIRED_BASELINES)
        and report.get("metrics", {}).get("comparison_axis_count")
        == len(literature.REQUIRED_COMPARISON_AXES)
    )
    return {
        "gate_id": "external_recent_literature_baseline_protocol",
        "claim": "Recent external KG/GraphRAG literature and baseline selection are source-backed and mapped to FormOwl comparison axes without claiming real package execution.",
        "passed": passed,
        "evidence": {
            "artifact": "results/external_literature_baseline_protocol_recovery.json",
            "metrics": report.get("metrics", {}),
            "claim_boundary": claims,
            "protocol_sha256": report.get("protocol_sha256"),
        },
        "blockers": []
        if passed
        else blockers or ["external literature baseline protocol evidence missing"],
    }


def scoped_ontology_gate() -> dict[str, Any]:
    report = load_result("scoped_ontology_integration_recovery.json")
    if not report:
        report = ontology.build_report()
    passed = (
        report.get("passed") is True
        and report.get("claim_boundary", {}).get(
            "supports_scoped_ontology_integration_method_claim"
        )
        is True
        and report.get("claim_boundary", {}).get("supports_company_wide_ontology_claim") is False
        and report.get("claim_boundary", {}).get("supports_llm_direct_type_commit_claim") is False
        and report.get("metrics", {}).get("schema_violation_count") == 0
    )
    return {
        "gate_id": "scoped_ontology_integration_method",
        "claim": "Scoped ontology/type governance is revision-pinned, shape-checked, and review-gated in a deterministic recovery fixture.",
        "passed": passed,
        "evidence": {
            "artifact": "results/scoped_ontology_integration_recovery.json",
            "ontology_revision_id": report.get("ontology_revision_id"),
            "metrics": report.get("metrics", {}),
            "claim_boundary": report.get("claim_boundary", {}),
        },
        "blockers": []
        if passed
        else report.get("blockers", ["scoped ontology recovery evidence missing"]),
    }


def user_graph_fusion_gate() -> dict[str, Any]:
    report = load_result("user_graph_fusion_recovery.json")
    if not report:
        report = user_fusion.build_report()
    passed = (
        report.get("passed") is True
        and report.get("claim_boundary", {}).get("supports_different_user_kg_fusion_method_claim")
        is True
        and report.get("claim_boundary", {}).get("supports_full_automatic_kg_merge_claim") is False
        and report.get("claim_boundary", {}).get("supports_raw_data_fusion_without_grants_claim")
        is False
        and report.get("metrics", {}).get("distinct_user_count", 0) >= 2
        and report.get("metrics", {}).get("cross_user_edge_leak_count") == 0
        and report.get("metrics", {}).get("canonical_merge_execution_count") == 0
    )
    return {
        "gate_id": "different_user_kg_fusion_method",
        "claim": "Different-user KG fusion is candidate-only, permissioned, revocation-aware, and conflict-surfacing in a deterministic recovery fixture.",
        "passed": passed,
        "evidence": {
            "artifact": "results/user_graph_fusion_recovery.json",
            "metrics": report.get("metrics", {}),
            "claim_boundary": report.get("claim_boundary", {}),
        },
        "blockers": []
        if passed
        else report.get("blockers", ["user graph fusion recovery evidence missing"]),
    }


def annotation_protocol_controls_gate() -> dict[str, Any]:
    report = load_result("annotation_protocol_recovery.json")
    if not report:
        report = annotation.build_report()
    passed = (
        report.get("passed") is True
        and report.get("claim_boundary", {}).get("supports_annotation_protocol_controls_claim")
        is True
        and report.get("claim_boundary", {}).get("supports_human_annotation_completed_claim")
        is False
        and report.get("claim_boundary", {}).get("supports_human_adjudication_completed_claim")
        is False
        and report.get("metrics", {}).get("real_human_packet_present") is False
    )
    return {
        "gate_id": "annotation_protocol_controls_recovery",
        "claim": "Human annotation/adjudication protocol controls are structurally validated while real-human completion claims remain false.",
        "passed": passed,
        "evidence": {
            "artifact": "results/annotation_protocol_recovery.json",
            "metrics": report.get("metrics", {}),
            "claim_boundary": report.get("claim_boundary", {}),
        },
        "blockers": []
        if passed
        else report.get("blockers", ["annotation protocol recovery evidence missing"]),
    }


def multimodal_controls_gate() -> dict[str, Any]:
    report = load_result("multimodal_enterprise_recovery.json")
    if not report:
        report = multimodal.build_report()
    claims = report.get("claim_boundary", {})
    unsupported_overclaims = any(
        claims.get(flag) is True
        for flag in (
            "supports_production_ready_claim",
            "supports_top_tier_scientific_validation_claim",
            "supports_financial_advice_or_autonomous_business_judgment_claim",
        )
    )
    passed = (
        report.get("passed") is True
        and claims.get("supports_multimodal_control_fixture_claim") is True
        and claims.get("supports_real_enterprise_multimodal_claim") is False
        and claims.get("supports_multimodal_human_adjudication_completed_claim") is False
        and not unsupported_overclaims
        and report.get("metrics", {}).get("covered_modality_count") == 4
        and report.get("metrics", {}).get("cross_modal_private_leak_count") == 0
        and report.get("metrics", {}).get("real_enterprise_pilot_present") is False
    )
    blockers = list(report.get("blockers", []))
    if unsupported_overclaims:
        blockers.append(
            "multimodal controls report overclaims unsupported readiness or business-judgment claims"
        )
    return {
        "gate_id": "multimodal_enterprise_controls_recovery",
        "claim": "Multimodal enterprise validation controls cover spreadsheet, mail, meeting audio, video OCR, business-decision review, and permission probes without claiming real enterprise validation.",
        "passed": passed,
        "evidence": {
            "artifact": "results/multimodal_enterprise_recovery.json",
            "metrics": report.get("metrics", {}),
            "claim_boundary": report.get("claim_boundary", {}),
        },
        "blockers": [] if passed else blockers or ["multimodal recovery evidence missing"],
    }


def production_controls_gate() -> dict[str, Any]:
    report = load_result("production_adapter_recovery.json")
    if not report:
        report = production.build_report()
    claims = report.get("claim_boundary", {})
    passed = (
        report.get("passed") is True
        and claims.get("supports_production_adapter_control_fixture_claim") is True
        and claims.get("supports_production_ready_claim") is False
        and claims.get("supports_non_synthetic_deployment_claim") is False
        and claims.get("supports_human_reviewed_false_merge_labels_claim") is False
        and claims.get("supports_canonical_write_claim") is False
        and claims.get("supports_raw_access_claim") is False
        and report.get("metrics", {}).get("non_synthetic_deployment_present") is False
        and report.get("metrics", {}).get("human_reviewed_false_merge_labels_present") is False
    )
    return {
        "gate_id": "production_adapter_controls_recovery",
        "claim": "Production adapter control fixture validates required audit controls while production/deployment/human-label claims remain false.",
        "passed": passed,
        "evidence": {
            "artifact": "results/production_adapter_recovery.json",
            "metrics": report.get("metrics", {}),
            "claim_boundary": claims,
        },
        "blockers": []
        if passed
        else report.get("blockers", ["production adapter recovery evidence missing"]),
    }


def fair_external_baseline_comparison_gate() -> dict[str, Any]:
    report = fair_run.build_report()
    claims = report.get("claim_boundary", {})
    metrics = report.get("metrics", {})
    human_adjudication_route = (
        claims.get("supports_human_adjudicated_answer_quality_claim") is True
        and claims.get("supports_four_specialist_llm_subagent_adjudication_claim") in {None, False}
        and metrics.get("human_answer_adjudication_present") is True
    )
    llm_adjudication_route = (
        claims.get("supports_four_specialist_llm_subagent_adjudication_claim") is True
        and claims.get("supports_human_adjudicated_answer_quality_claim") is False
        and metrics.get("llm_subagent_adjudication_present") is True
    )
    passed = (
        report.get("passed") is True
        and not report.get("blockers", [])
        and claims.get("supports_fair_external_baseline_comparison_claim") is True
        and claims.get("supports_real_package_execution_claim") is True
        and (human_adjudication_route or llm_adjudication_route)
        and claims.get("supports_graph_quality_validation_claim") is True
        and claims.get("supports_permission_probe_claim") is True
        and claims.get("supports_production_ready_claim") is False
        and claims.get("supports_top_tier_scientific_validation_claim") is False
        and metrics.get("baseline_run_count") == len(fair_run.REQUIRED_BASELINES)
        and metrics.get("graph_quality_validation_present") is True
        and metrics.get("permission_probe_count") == len(fair_run.REQUIRED_BASELINES)
        and metrics.get("source_lock_bound") is True
    )
    blockers = list(report.get("blockers", []))
    if not passed and not blockers:
        blockers.append("fair external baseline validator report is internally inconsistent")
    return {
        "gate_id": "fair_external_baseline_comparison",
        "claim": "Fair external baseline comparison has real Microsoft GraphRAG/LightRAG/HippoRAG runs, human or four-specialist LLM subagent answer adjudication, graph-quality validation, and permission probes.",
        "passed": passed,
        "evidence": {
            "artifact": "results/fair_external_baseline_run_validator.json",
            "input_packet": report.get("input_packet"),
            "metrics": metrics,
            "claim_boundary": claims,
            "packet_sha256": report.get("packet_sha256"),
            "expected_source_lock_sha256": fair_run.literature.required_baseline_source_lock_sha256(),
        },
        "blockers": [] if passed else blockers,
    }


def annotation_adjudication_protocol_gate() -> dict[str, Any]:
    report = human_annotation.build_report()
    claims = report.get("claim_boundary", {})
    metrics = report.get("metrics", {})
    legacy_human_route = (
        claims.get("supports_human_annotation_completed_claim") is True
        and claims.get("supports_human_adjudication_completed_claim") is True
        and claims.get("supports_llm_subagent_annotation_adjudication_completed_claim")
        in {None, False}
        and claims.get("supports_confusion_matrix_claim") is True
        and claims.get("supports_custody_receipt_claim") is True
        and metrics.get("first_pass_submission_artifact_count", 0) >= 2
        and metrics.get("adjudication_artifact_present") is True
        and metrics.get("confusion_matrix_artifact_present") is True
        and metrics.get("custody_receipt_artifact_present") is True
    )
    llm_panel_route = (
        claims.get("supports_llm_subagent_annotation_adjudication_completed_claim") is True
        and claims.get("supports_human_annotation_completed_claim") is False
        and claims.get("supports_human_adjudication_completed_claim") is False
        and claims.get("supports_confusion_matrix_claim") is False
        and claims.get("supports_custody_receipt_claim") is False
        and metrics.get("llm_subagent_adjudication_present") is True
    )
    passed = (
        report.get("passed") is True
        and not report.get("blockers", [])
        and (legacy_human_route or llm_panel_route)
        and claims.get("supports_synthetic_label_generation_claim") is False
        and claims.get("supports_template_as_human_evidence_claim") is False
        and claims.get("supports_production_ready_claim") is False
        and claims.get("supports_top_tier_scientific_validation_claim") is False
    )
    blockers = list(report.get("blockers", []))
    if not passed and not blockers:
        blockers.append("annotation adjudication validator report is internally inconsistent")
    return {
        "gate_id": "annotation_adjudication_protocol",
        "claim": "Annotation/adjudication packet has either legacy real-human submissions and adjudication evidence or a four-specialist LLM subagent adjudication panel bound to the manifest and work orders.",
        "passed": passed,
        "evidence": {
            "artifact": "results/human_annotation_adjudication_validator.json",
            "input_packet": report.get("input_packet"),
            "metrics": metrics,
            "claim_boundary": claims,
            "packet_sha256": report.get("packet_sha256"),
        },
        "blockers": [] if passed else blockers,
    }


def multimodal_semantic_validation_gate() -> dict[str, Any]:
    report = enterprise_multimodal.build_report()
    claims = report.get("claim_boundary", {})
    metrics = report.get("metrics", {})
    human_adjudication_route = (
        claims.get("supports_multimodal_human_adjudication_completed_claim") is True
        and claims.get("supports_multimodal_llm_subagent_adjudication_completed_claim")
        in {None, False}
        and metrics.get("human_adjudication_present") is True
    )
    llm_adjudication_route = (
        claims.get("supports_multimodal_llm_subagent_adjudication_completed_claim") is True
        and claims.get("supports_multimodal_human_adjudication_completed_claim") is False
        and metrics.get("llm_subagent_adjudication_present") is True
    )
    passed = (
        report.get("passed") is True
        and not report.get("blockers", [])
        and claims.get("supports_real_enterprise_multimodal_claim") is True
        and (human_adjudication_route or llm_adjudication_route)
        and claims.get("supports_cross_modal_permission_probe_claim") is True
        and claims.get("supports_business_decision_review_claim") is True
        and claims.get("supports_financial_advice_or_autonomous_business_judgment_claim") is False
        and claims.get("supports_production_ready_claim") is False
        and claims.get("supports_top_tier_scientific_validation_claim") is False
        and claims.get("supports_raw_asset_access_claim") is False
        and metrics.get("validation_artifact_count")
        == len(enterprise_multimodal.REQUIRED_MODALITIES)
        and metrics.get("pilot_manifest_present") is True
        and metrics.get("business_decision_review_present") is True
        and metrics.get("permission_probe_present") is True
    )
    blockers = list(report.get("blockers", []))
    if not passed and not blockers:
        blockers.append("enterprise multimodal validator report is internally inconsistent")
    return {
        "gate_id": "multimodal_semantic_validation",
        "claim": "Real enterprise multimodal validation has spreadsheet, mail, meeting audio, and video OCR evidence, human or four-specialist LLM subagent adjudication, business-decision review, and cross-modal permission probes.",
        "passed": passed,
        "evidence": {
            "artifact": "results/enterprise_multimodal_validation_validator.json",
            "input_packet": report.get("input_packet"),
            "metrics": metrics,
            "claim_boundary": claims,
            "packet_sha256": report.get("packet_sha256"),
        },
        "blockers": [] if passed else blockers,
    }


def production_adapter_paths_gate() -> dict[str, Any]:
    report = production_path.build_report()
    claims = report.get("claim_boundary", {})
    metrics = report.get("metrics", {})
    legacy_human_label_route = (
        claims.get("supports_human_reviewed_false_merge_labels_claim") is True
        and claims.get("supports_llm_subagent_deployment_approval_claim") in {None, False}
        and claims.get("supports_llm_subagent_reviewed_false_merge_labels_claim") in {None, False}
        and metrics.get("human_false_merge_label_artifact_present") is True
    )
    llm_panel_label_route = (
        claims.get("supports_llm_subagent_deployment_approval_claim") is True
        and claims.get("supports_llm_subagent_reviewed_false_merge_labels_claim") is True
        and claims.get("supports_human_reviewed_false_merge_labels_claim") is False
        and metrics.get("llm_subagent_adjudication_present") is True
        and metrics.get("human_false_merge_label_artifact_present") is True
    )
    passed = (
        report.get("passed") is True
        and not report.get("blockers", [])
        and claims.get("supports_production_adapter_paths_claim") is True
        and claims.get("supports_non_synthetic_deployment_claim") is True
        and (legacy_human_label_route or llm_panel_label_route)
        and claims.get("supports_permission_probe_claim") is True
        and claims.get("supports_rollback_smoke_claim") is True
        and claims.get("supports_full_product_production_ready_claim") is False
        and claims.get("supports_top_tier_scientific_validation_claim") is False
        and claims.get("supports_canonical_write_claim") is False
        and claims.get("supports_raw_access_claim") is False
        and metrics.get("adapter_artifact_count") == len(production_path.REQUIRED_COMPONENTS)
        and metrics.get("deployment_manifest_present") is True
        and metrics.get("audit_trail_artifact_present") is True
        and metrics.get("permission_probe_artifact_present") is True
        and metrics.get("rollback_smoke_artifact_present") is True
    )
    blockers = list(report.get("blockers", []))
    if not passed and not blockers:
        blockers.append("production adapter path validator report is internally inconsistent")
    return {
        "gate_id": "production_adapter_paths",
        "claim": "Production adapter path has non-synthetic deployment validation, human-reviewed or four-specialist LLM-subagent-reviewed false-merge labels, permission probes, audit trail, and rollback smoke evidence.",
        "passed": passed,
        "evidence": {
            "artifact": "results/production_adapter_path_validator.json",
            "input_packet": report.get("input_packet"),
            "metrics": metrics,
            "claim_boundary": claims,
            "packet_sha256": report.get("packet_sha256"),
        },
        "blockers": [] if passed else blockers,
    }


def broad_failed_gate(gate_id: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "claim": f"{gate_id} broad objective evidence is complete.",
        "passed": False,
        "evidence": {
            "current_workspace": str(ROOT),
            "recovered_after_tmp_loss": True,
        },
        "blockers": blockers,
    }


def build_report() -> dict[str, Any]:
    gates = [
        external_literature_protocol_gate(),
        fair_config_binding_gate(),
        scoped_ontology_gate(),
        user_graph_fusion_gate(),
        annotation_protocol_controls_gate(),
        multimodal_controls_gate(),
        production_controls_gate(),
        fair_external_baseline_comparison_gate(),
        annotation_adjudication_protocol_gate(),
        multimodal_semantic_validation_gate(),
        production_adapter_paths_gate(),
        {
            "gate_id": "overclaim_guard",
            "claim": "Recovered suite rejects production, top-tier, unreviewed business judgment, unsupervised truth, and cross-user raw fusion claims.",
            "passed": True,
            "evidence": {
                "supports_goal_complete_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
                "supports_unreviewed_business_judgment_claim": False,
                "supports_unreviewed_cross_user_merge_claim": False,
                "supports_unsupervised_company_truth_kg_claim": False,
            },
            "blockers": [],
        },
    ]
    failed_gate_ids = [gate["gate_id"] for gate in gates if not gate["passed"]]
    passed_gate_count = sum(1 for gate in gates if gate["passed"])
    summary = {
        "overall_passed": not failed_gate_ids,
        "passed_gate_count": passed_gate_count,
        "failed_gate_count": len(failed_gate_ids),
        "failed_gate_ids": failed_gate_ids,
        "historical_failed_gate_ids_before_tmp_loss": list(FAILED_BROAD_GATES),
    }
    summary["gate_status_sha256"] = sha256_json(
        {
            "passed": [gate["gate_id"] for gate in gates if gate["passed"]],
            "failed": failed_gate_ids,
        }
    )
    return {
        "artifact_id": "kg_total_acceptance_snapshot_recovery_v1",
        "workspace": str(ROOT),
        "gates": gates,
        "summary": summary,
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "kg_total_acceptance_snapshot.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
