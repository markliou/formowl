#!/usr/bin/env python3
"""Generate non-evidence work orders for collecting the remaining KG evidence.

The output is an operator checklist, not an acceptance artifact. It does not
create artifacts, write assembly manifests, promote canonical packets, or mark
any gate complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import real_evidence_preflight as preflight


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CHECKLIST_PATH = ROOT / "remaining_evidence_checklist.json"
OUTPUT_PATH = RESULTS / "real_evidence_collection_work_orders.json"
ASSEMBLY_MANIFEST_GENERATORS = {
    "fair_external_baseline_comparison": "fair_external_baseline_assembly_manifest_generator.py",
    "annotation_adjudication_protocol": "human_annotation_assembly_manifest_generator.py",
    "multimodal_semantic_validation": "enterprise_multimodal_assembly_manifest_generator.py",
    "production_adapter_paths": "production_adapter_assembly_manifest_generator.py",
}
HUMAN_RESPONSE_INTAKE_WORK_PACKET = "work_packets/human_annotation_work_packet_preview.json"
HUMAN_RESPONSE_PACKET_PLACEHOLDER = "OPERATOR_RESPONSE_PACKET_JSON"
HUMAN_RESPONSE_INTAKE_OUTPUT_DIR = "inputs/human_annotation_real/OPERATOR_RUN_ID"
HUMAN_RESPONSE_INTAKE_MANIFEST_OUTPUT = (
    "work_packets/annotation_adjudication_protocol_candidate_manifest.json"
)
ENTERPRISE_RESPONSE_INTAKE_WORK_PACKET = (
    "work_packets/enterprise_multimodal_collection_packet_preview.json"
)
ENTERPRISE_RESPONSE_PACKET_PLACEHOLDER = "OPERATOR_ENTERPRISE_RESPONSE_PACKET_JSON"
ENTERPRISE_RESPONSE_INTAKE_OUTPUT_DIR = "inputs/enterprise_multimodal_real/OPERATOR_RUN_ID"
ENTERPRISE_RESPONSE_INTAKE_MANIFEST_OUTPUT = (
    "work_packets/multimodal_semantic_validation_candidate_manifest.json"
)
PRODUCTION_RESPONSE_INTAKE_WORK_PACKET = (
    "work_packets/production_adapter_collection_packet_preview.json"
)
PRODUCTION_RESPONSE_PACKET_PLACEHOLDER = "OPERATOR_PRODUCTION_ADAPTER_RESPONSE_PACKET_JSON"
PRODUCTION_RESPONSE_INTAKE_OUTPUT_DIR = "inputs/production_adapter_real/OPERATOR_RUN_ID"
PRODUCTION_RESPONSE_INTAKE_MANIFEST_OUTPUT = (
    "work_packets/production_adapter_paths_candidate_manifest.json"
)
FAIR_RESPONSE_INTAKE_WORK_PACKET = "work_packets/fair_baseline_run_work_packet_preview.json"
FAIR_RESPONSE_PACKET_PLACEHOLDER = "OPERATOR_FAIR_BASELINE_RESPONSE_PACKET_JSON"
FAIR_RESPONSE_INTAKE_OUTPUT_DIR = "inputs/fair_baseline_real/OPERATOR_RUN_ID"
FAIR_RESPONSE_INTAKE_MANIFEST_OUTPUT = (
    "work_packets/fair_external_baseline_comparison_candidate_manifest.json"
)
RESPONSE_INTAKE_MANIFEST_OUTPUTS = {
    "fair_external_baseline_comparison": FAIR_RESPONSE_INTAKE_MANIFEST_OUTPUT,
    "annotation_adjudication_protocol": HUMAN_RESPONSE_INTAKE_MANIFEST_OUTPUT,
    "multimodal_semantic_validation": ENTERPRISE_RESPONSE_INTAKE_MANIFEST_OUTPUT,
    "production_adapter_paths": PRODUCTION_RESPONSE_INTAKE_MANIFEST_OUTPUT,
}
ACCEPTANCE_SHAPED_STATES = {
    "pass",
    "passed",
    "ready",
    "overall_ready",
    "ready_for_acceptance",
    "complete",
    "completed",
    "success",
    "succeeded",
}


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _copy_list(row: dict[str, Any], key: str) -> list[Any]:
    value = row.get(key, [])
    return list(value) if isinstance(value, list) else []


def _non_authoritative_state(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() in ACCEPTANCE_SHAPED_STATES:
        return "non_blocked_state_not_authoritative_in_work_order_report"
    return value


def _preflight_gate(preflight_report: dict[str, Any], gate_id: str) -> dict[str, Any]:
    for row in preflight_report.get("gates", []):
        if isinstance(row, dict) and row.get("gate_id") == gate_id:
            return row
    return {}


def _gate_config(gate_id: str) -> dict[str, Any]:
    return preflight.EXPECTED_GATES[gate_id]


def _common_commands(row: dict[str, Any], gate_config: dict[str, Any]) -> dict[str, Any]:
    assembler = gate_config["assembler_module"]
    validator = row["validator_module"]
    manifest_path = f"work_orders/{row['gate_id']}_assembly_manifest.json"
    candidate_manifest_path = RESPONSE_INTAKE_MANIFEST_OUTPUTS[row["gate_id"]]
    commands = {
        "assembly_manifest_path": manifest_path,
        "candidate_manifest_path": candidate_manifest_path,
        "validate_candidate_packet": (
            f"python3 {assembler} --assembly-manifest {candidate_manifest_path} --validate"
        ),
        "run_gate_validator_after_manual_packet_review": f"python3 {validator}",
        "rerun_total_acceptance": "python3 kg_total_acceptance_suite.py",
        "rerun_objective_audit": "python3 kg_objective_completion_audit.py",
        "rerun_preflight": "python3 real_evidence_preflight.py",
        "operator_followup_after_validation": (
            "manual governance approval is required outside this work-order generator before "
            "any canonical packet update can affect acceptance"
        ),
    }
    generator = ASSEMBLY_MANIFEST_GENERATORS.get(row["gate_id"])
    if generator:
        commands["generate_non_evidence_assembly_manifest_scaffold"] = (
            f"python3 {generator} --output {manifest_path}"
        )
    if row["gate_id"] == "fair_external_baseline_comparison":
        commands["seal_fair_baseline_responses_into_candidate_artifacts"] = (
            "python3 fair_baseline_response_intake.py "
            f"--work-packet {FAIR_RESPONSE_INTAKE_WORK_PACKET} "
            f"--response-packet {FAIR_RESPONSE_PACKET_PLACEHOLDER} "
            f"--output-dir {FAIR_RESPONSE_INTAKE_OUTPUT_DIR} "
            f"--assembly-manifest-output {FAIR_RESPONSE_INTAKE_MANIFEST_OUTPUT}"
        )
    if row["gate_id"] == "annotation_adjudication_protocol":
        commands["seal_human_responses_into_candidate_artifacts"] = (
            "python3 human_annotation_response_intake.py "
            f"--work-packet {HUMAN_RESPONSE_INTAKE_WORK_PACKET} "
            f"--response-packet {HUMAN_RESPONSE_PACKET_PLACEHOLDER} "
            f"--output-dir {HUMAN_RESPONSE_INTAKE_OUTPUT_DIR} "
            f"--assembly-manifest-output {HUMAN_RESPONSE_INTAKE_MANIFEST_OUTPUT}"
        )
    if row["gate_id"] == "multimodal_semantic_validation":
        commands["seal_enterprise_responses_into_candidate_artifacts"] = (
            "python3 enterprise_multimodal_response_intake.py "
            f"--work-packet {ENTERPRISE_RESPONSE_INTAKE_WORK_PACKET} "
            f"--response-packet {ENTERPRISE_RESPONSE_PACKET_PLACEHOLDER} "
            f"--output-dir {ENTERPRISE_RESPONSE_INTAKE_OUTPUT_DIR} "
            f"--assembly-manifest-output {ENTERPRISE_RESPONSE_INTAKE_MANIFEST_OUTPUT}"
        )
    if row["gate_id"] == "production_adapter_paths":
        commands["seal_production_adapter_responses_into_candidate_artifacts"] = (
            "python3 production_adapter_response_intake.py "
            f"--work-packet {PRODUCTION_RESPONSE_INTAKE_WORK_PACKET} "
            f"--response-packet {PRODUCTION_RESPONSE_PACKET_PLACEHOLDER} "
            f"--output-dir {PRODUCTION_RESPONSE_INTAKE_OUTPUT_DIR} "
            f"--assembly-manifest-output {PRODUCTION_RESPONSE_INTAKE_MANIFEST_OUTPUT}"
        )
    return commands


def _common_safety(row: dict[str, Any], gate_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_packet_must_be_created_only_by_assembler": row["input_packet"],
        "real_artifacts_must_live_under": gate_config["real_root_rel"],
        "assembly_manifest_must_not_live_under_real_artifact_root": True,
        "forbidden_sources": [
            "templates/",
            "inputs/test_*",
            "results/",
            "symlinks",
            "malformed JSON",
            "raw filesystem paths",
            "NAS/SMB/NFS/WebDAV paths",
            "object-store or database URIs",
            "worker scratch paths",
            "lost /tmp artifacts",
        ],
        "operator_must_not_claim": _copy_list(row, "must_not_claim"),
    }


def _fair_tasks(row: dict[str, Any]) -> dict[str, Any]:
    source_ids_by_baseline = row.get("required_source_ids_by_baseline", {})
    if not isinstance(source_ids_by_baseline, dict):
        source_ids_by_baseline = {}
    return {
        "source_lock": {
            "required_source_lock_sha256": row.get("required_source_lock_sha256"),
            "per_baseline_source_ids_required": True,
        },
        "baseline_package_runs": [
            {
                "baseline_id": baseline_id,
                "required_source_ids": list(source_ids_by_baseline.get(baseline_id, []))
                if isinstance(source_ids_by_baseline.get(baseline_id), list)
                else [],
                "required_artifact_fields": _copy_list(row, "required_artifacts_per_baseline"),
                "required_equalized_hashes": _copy_list(row, "required_equalized_hashes"),
                "minimum_controls": [
                    "real_package_execution == true",
                    "mock_or_dry_run == false",
                    "synthetic_corpus == false",
                    "package_source_url matches locked baseline reference",
                    "source_ids match locked literature protocol references",
                    "config artifact content binds fairness policy fields",
                ],
            }
            for baseline_id in _copy_list(row, "required_baselines")
        ],
        "human_answer_adjudication": _copy_list(row, "required_human_evidence"),
        "graph_quality_validation": _copy_list(row, "required_graph_quality_evidence"),
        "permission_probe_evidence": _copy_list(row, "required_permission_probe_evidence"),
        "run_artifact_content_contract": _copy_list(row, "required_run_artifact_content_contract"),
        "response_packet_contract": {
            "response_packet_type": "fair_baseline_response_intake_v1",
            "response_packet_placeholder": FAIR_RESPONSE_PACKET_PLACEHOLDER,
            "work_packet_path": FAIR_RESPONSE_INTAKE_WORK_PACKET,
            "candidate_output_dir": FAIR_RESPONSE_INTAKE_OUTPUT_DIR,
            "assembly_manifest_output": FAIR_RESPONSE_INTAKE_MANIFEST_OUTPUT,
            "writes_canonical_packet": False,
            "canonical_packet_not_written": row["input_packet"],
            "promotes_evidence": False,
            "counts_as_acceptance_gate": False,
            "required_controls": [
                "operator_run_id matches the candidate output directory final segment",
                "candidate output dir is exactly inputs/fair_baseline_real/<operator_run_id> outside tests",
                "response packet top-level fields and baseline-run wrapper fields are allowlisted",
                "human adjudication, graph-quality, and permission-probe wrapper fields are allowlisted",
                "raw/internal field names are rejected throughout response payloads",
                "candidate artifact parent directories are preflighted before writes",
                "after-open partial output writes are cleaned up",
                "created candidate artifacts and optional candidate manifests are rolled back when assembly or validation raises after writes",
                "operator supplied real package run artifacts for every baseline",
                "operator supplied non-synthetic run environment",
                "operator supplied human answer-quality adjudication",
                "operator supplied graph-quality validation",
                "operator supplied permission probes for every baseline",
                "candidate packet validates before any manual governance promotion",
                "intake custody receipt binds response packet, candidate packet, and artifact hashes",
                "intake custody receipt binds optional assembly manifest hash when emitted",
            ],
        },
    }


def _human_tasks(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "required_artifacts": _copy_list(row, "required_artifacts"),
        "human_controls": _copy_list(row, "required_human_controls"),
        "response_packet_contract": {
            "response_packet_type": "human_annotation_response_intake_v1",
            "response_packet_placeholder": HUMAN_RESPONSE_PACKET_PLACEHOLDER,
            "work_packet_path": HUMAN_RESPONSE_INTAKE_WORK_PACKET,
            "candidate_output_dir": HUMAN_RESPONSE_INTAKE_OUTPUT_DIR,
            "assembly_manifest_output": HUMAN_RESPONSE_INTAKE_MANIFEST_OUTPUT,
            "writes_canonical_packet": False,
            "canonical_packet_not_written": row["input_packet"],
            "promotes_evidence": False,
            "counts_as_acceptance_gate": False,
            "required_controls": [
                "operator_run_id matches the candidate output directory final segment",
                "two independent first-pass human reviewer submissions",
                "human adjudicator distinct from first-pass reviewers",
                "at least one first-pass disagreement",
                "adjudication rows exactly cover disagreed items",
                "generated_by_llm == false for every submission and adjudication row",
                "template_source is null for every submission and adjudication row",
                "unsupported response packet fields and raw/internal field names are rejected",
                "intake custody receipt binds response packet, candidate packet, and artifact hashes",
                "intake custody receipt binds optional assembly manifest hash when emitted",
            ],
        },
        "custody_controls": [
            "two independent first-pass submissions are sealed before adjudication",
            "adjudicator is human and distinct from first-pass reviewers",
            "confusion matrix is derived from sealed submissions and final adjudication",
            "custody receipt binds every artifact hash",
        ],
    }


def _enterprise_tasks(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "required_modalities": _copy_list(row, "required_modalities"),
        "required_artifacts": _copy_list(row, "required_artifacts"),
        "controls": _copy_list(row, "required_controls"),
        "response_packet_contract": {
            "response_packet_type": "enterprise_multimodal_response_intake_v1",
            "response_packet_placeholder": ENTERPRISE_RESPONSE_PACKET_PLACEHOLDER,
            "work_packet_path": ENTERPRISE_RESPONSE_INTAKE_WORK_PACKET,
            "candidate_output_dir": ENTERPRISE_RESPONSE_INTAKE_OUTPUT_DIR,
            "assembly_manifest_output": ENTERPRISE_RESPONSE_INTAKE_MANIFEST_OUTPUT,
            "writes_canonical_packet": False,
            "canonical_packet_not_written": row["input_packet"],
            "promotes_evidence": False,
            "counts_as_acceptance_gate": False,
            "required_controls": [
                "operator supplied pilot manifest artifact",
                "operator supplied validation artifacts for every required modality",
                "operator supplied human adjudication artifact",
                "operator supplied business decision review artifact",
                "operator supplied permission probe artifact",
                "candidate packet validates before any manual governance promotion",
                "intake custody receipt binds response packet, candidate packet, and artifact hashes",
                "intake custody receipt binds optional assembly manifest hash when emitted",
            ],
        },
        "per_modality_rows": [
            {
                "modality": modality,
                "minimum_controls": [
                    "real enterprise source row",
                    "not synthetic or demo",
                    "not text-proxy-only",
                    "FormOwl locator bound to asset id",
                    "validation row bound to source asset hash",
                ],
            }
            for modality in _copy_list(row, "required_modalities")
        ],
    }


def _production_tasks(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "required_components": _copy_list(row, "required_components"),
        "required_artifacts": _copy_list(row, "required_artifacts"),
        "required_audit_actions": _copy_list(row, "required_audit_actions"),
        "controls": _copy_list(row, "required_controls"),
        "response_packet_contract": {
            "response_packet_type": "production_adapter_response_intake_v1",
            "response_packet_placeholder": PRODUCTION_RESPONSE_PACKET_PLACEHOLDER,
            "work_packet_path": PRODUCTION_RESPONSE_INTAKE_WORK_PACKET,
            "candidate_output_dir": PRODUCTION_RESPONSE_INTAKE_OUTPUT_DIR,
            "assembly_manifest_output": PRODUCTION_RESPONSE_INTAKE_MANIFEST_OUTPUT,
            "writes_canonical_packet": False,
            "canonical_packet_not_written": row["input_packet"],
            "promotes_evidence": False,
            "counts_as_acceptance_gate": False,
            "required_controls": [
                "operator_run_id matches the candidate output directory final segment",
                "candidate output dir is exactly inputs/production_adapter_real/<operator_run_id> outside tests",
                "response packet top-level fields and adapter wrapper fields are allowlisted",
                "raw/internal field names are rejected throughout response payloads",
                "candidate artifact parent directories are preflighted before writes",
                "after-open partial output writes are cleaned up",
                "created candidate artifacts and optional candidate manifests are rolled back when assembly or validation raises after writes",
                "operator supplied non-synthetic deployment manifest",
                "operator supplied component artifacts for every required adapter",
                "operator supplied human-reviewed false-merge labels for candidate adapters",
                "operator supplied audit trail with every required action",
                "operator supplied permission probe artifact",
                "operator supplied rollback smoke artifact",
                "candidate packet validates before any manual governance promotion",
                "intake custody receipt binds response packet, candidate packet, and artifact hashes",
                "intake custody receipt binds optional assembly manifest hash when emitted",
            ],
        },
        "per_component_rows": [
            {
                "component_id": component_id,
                "minimum_controls": [
                    "non_synthetic_deployment == true",
                    "synthetic_or_demo == false",
                    "permission_filter_enabled == true",
                    "raw_path_exposed == false",
                    "canonical_write_enabled == false",
                ],
            }
            for component_id in _copy_list(row, "required_components")
        ],
    }


def gate_tasks(row: dict[str, Any]) -> dict[str, Any]:
    gate_id = row["gate_id"]
    if gate_id == "fair_external_baseline_comparison":
        return _fair_tasks(row)
    if gate_id == "annotation_adjudication_protocol":
        return _human_tasks(row)
    if gate_id == "multimodal_semantic_validation":
        return _enterprise_tasks(row)
    if gate_id == "production_adapter_paths":
        return _production_tasks(row)
    return {}


def build_work_order(
    checklist_row: dict[str, Any],
    *,
    preflight_report: dict[str, Any],
) -> dict[str, Any]:
    gate_id = checklist_row["gate_id"]
    gate_config = _gate_config(gate_id)
    preflight_row = _preflight_gate(preflight_report, gate_id)
    return {
        "work_order_id": f"collect_{gate_id}",
        "gate_id": gate_id,
        "requirement_id": checklist_row["requirement_id"],
        "collection_status": _non_authoritative_state(
            preflight_row.get("collection_state", "unknown")
        ),
        "canonical_input_packet": checklist_row["input_packet"],
        "required_packet_artifact_id": checklist_row["required_packet_artifact_id"],
        "required_evidence_kind": checklist_row["required_evidence_kind"],
        "real_artifact_root": gate_config["real_root_rel"],
        "validator_module": checklist_row["validator_module"],
        "assembler_module": gate_config["assembler_module"],
        "current_blockers": _copy_list(checklist_row, "current_blockers"),
        "operator_tasks": gate_tasks(checklist_row),
        "commands": _common_commands(checklist_row, gate_config),
        "safety": _common_safety(checklist_row, gate_config),
        "preflight_snapshot": {
            "current_total_gate_state": _non_authoritative_state(
                preflight_row.get("current_total_gate_state")
            ),
            "validator_status": _non_authoritative_state(preflight_row.get("validator_status")),
            "packet_state": _non_authoritative_state(
                preflight_row.get("packet_surface", {}).get("packet_state")
            ),
            "real_root_file_count": preflight_row.get("real_root_scan", {}).get("file_count"),
            "real_root_candidate_artifact_count": preflight_row.get("real_root_scan", {}).get(
                "candidate_artifact_count"
            ),
            "real_root_disappeared_file_count": preflight_row.get("real_root_scan", {}).get(
                "disappeared_file_count"
            ),
            "root_ready": preflight_row.get("real_root_scan", {}).get("root_ready"),
        },
        "work_order_authority": {
            "accepts_evidence": False,
            "promotes_evidence": False,
            "writes_assembly_manifest": False,
            "writes_canonical_packet": False,
            "counts_as_acceptance_gate": False,
        },
    }


def _checklist_gate_ids(remaining: list[Any]) -> list[Any]:
    return [row.get("gate_id") for row in remaining if isinstance(row, dict)]


def _per_gate_preflight_contract(
    preflight_report: dict[str, Any], expected_gate_ids: list[str]
) -> dict[str, Any]:
    rows = [row for row in preflight_report.get("gates", []) if isinstance(row, dict)]
    row_ids = [row.get("gate_id") for row in rows]
    details: dict[str, Any] = {}
    valid = len(rows) == len(expected_gate_ids) and row_ids == expected_gate_ids
    for gate_id in expected_gate_ids:
        matching = [row for row in rows if row.get("gate_id") == gate_id]
        if len(matching) != 1:
            details[gate_id] = {
                "status": "invalid",
                "reason": "expected exactly one preflight gate row",
                "row_count": len(matching),
            }
            valid = False
            continue
        row = matching[0]
        packet_surface = row.get("packet_surface")
        real_root_scan = row.get("real_root_scan")
        gate_checks = {
            "validator_status_blocked": row.get("validator_status") == "blocked",
            "current_total_gate_state_blocked": row.get("current_total_gate_state") == "blocked",
            "packet_surface_is_object": isinstance(packet_surface, dict),
            "real_root_scan_is_object": isinstance(real_root_scan, dict),
            "packet_state_present": isinstance(packet_surface, dict)
            and isinstance(packet_surface.get("packet_state"), str),
            "real_root_file_count_is_int": isinstance(real_root_scan, dict)
            and isinstance(real_root_scan.get("file_count"), int)
            and not isinstance(real_root_scan.get("file_count"), bool),
            "real_root_candidate_artifact_count_is_int": isinstance(real_root_scan, dict)
            and isinstance(real_root_scan.get("candidate_artifact_count"), int)
            and not isinstance(real_root_scan.get("candidate_artifact_count"), bool),
            "real_root_disappeared_file_count_is_int": isinstance(real_root_scan, dict)
            and isinstance(real_root_scan.get("disappeared_file_count"), int)
            and not isinstance(real_root_scan.get("disappeared_file_count"), bool),
            "real_root_ready_is_bool": isinstance(real_root_scan, dict)
            and isinstance(real_root_scan.get("root_ready"), bool),
            "current_absence_visible": isinstance(real_root_scan, dict)
            and real_root_scan.get("file_count") == 0
            and real_root_scan.get("candidate_artifact_count") == 0
            and real_root_scan.get("disappeared_file_count") == 0
            and real_root_scan.get("root_ready") is False,
        }
        details[gate_id] = {
            "status": "valid" if all(gate_checks.values()) else "invalid",
            "checks": gate_checks,
        }
        if not all(gate_checks.values()):
            valid = False
    return {
        "valid": valid,
        "row_gate_ids": row_ids,
        "expected_gate_ids": expected_gate_ids,
        "details": details,
    }


def _sync_status(
    *,
    checklist: dict[str, Any],
    preflight_report: dict[str, Any],
    remaining: list[Any],
    blocked_gate_ids: list[Any],
    candidate_work_order_gate_ids: list[str],
) -> dict[str, Any]:
    checklist_gate_ids = _checklist_gate_ids(remaining)
    expected_gate_ids = list(preflight.EXPECTED_GATES)
    per_gate_contract = _per_gate_preflight_contract(preflight_report, expected_gate_ids)
    sync = {
        "checklist_present": bool(checklist),
        "preflight_state": _non_authoritative_state(preflight_report.get("preflight_state")),
        "checklist_sync_status": _non_authoritative_state(
            preflight_report.get("checklist_sync", {}).get("status")
        ),
        "checklist_remaining_gate_ids": checklist_gate_ids,
        "preflight_blocked_gate_ids": blocked_gate_ids,
        "candidate_work_order_gate_ids": candidate_work_order_gate_ids,
        "checklist_remaining_gate_ids_match_preflight_blocked_gates": checklist_gate_ids
        == blocked_gate_ids,
        "checklist_remaining_gate_ids_match_expected_gates": checklist_gate_ids
        == expected_gate_ids,
        "candidate_work_order_gate_ids_match_checklist_remaining_gates": candidate_work_order_gate_ids
        == checklist_gate_ids,
        "candidate_work_order_gate_ids_match_preflight_blocked_gates": candidate_work_order_gate_ids
        == blocked_gate_ids,
        "per_gate_preflight_contract_valid": per_gate_contract["valid"],
        "per_gate_preflight_contract": per_gate_contract,
    }
    synchronized = (
        sync["checklist_present"]
        and preflight_report.get("preflight_state") == "blocked"
        and sync["checklist_sync_status"] == "synchronized"
        and sync["checklist_remaining_gate_ids_match_preflight_blocked_gates"]
        and sync["checklist_remaining_gate_ids_match_expected_gates"]
        and sync["candidate_work_order_gate_ids_match_checklist_remaining_gates"]
        and sync["candidate_work_order_gate_ids_match_preflight_blocked_gates"]
        and sync["per_gate_preflight_contract_valid"]
    )
    sync["status"] = "synchronized" if synchronized else "drifted"
    sync["normal_work_orders_withheld"] = not synchronized
    return sync


def build_report(
    *,
    checklist_override: dict[str, Any] | None = None,
    preflight_report_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checklist = checklist_override if checklist_override is not None else load_json(CHECKLIST_PATH)
    preflight_report = (
        preflight_report_override
        if preflight_report_override is not None
        else preflight.build_report()
    )
    remaining = checklist.get("remaining_gates", [])
    blocked_gate_ids = preflight_report.get("summary", {}).get("blocked_gate_ids", [])
    candidate_rows = [
        row
        for row in remaining
        if isinstance(row, dict) and row.get("gate_id") in preflight.EXPECTED_GATES
    ]
    candidate_work_order_gate_ids = [row["gate_id"] for row in candidate_rows]
    sync = _sync_status(
        checklist=checklist,
        preflight_report=preflight_report,
        remaining=remaining,
        blocked_gate_ids=blocked_gate_ids,
        candidate_work_order_gate_ids=candidate_work_order_gate_ids,
    )
    work_orders = (
        [build_work_order(row, preflight_report=preflight_report) for row in candidate_rows]
        if sync["status"] == "synchronized"
        else []
    )
    work_order_gate_ids = [row["gate_id"] for row in work_orders]
    report = {
        "artifact_id": "kg_real_evidence_collection_work_orders_v1",
        "workspace": ".formowl/kg-eval",
        "source_checklist": "remaining_evidence_checklist.json",
        "source_preflight": "results/real_evidence_preflight.json",
        "work_order_state": (
            "collection_blocked_until_real_evidence_exists"
            if sync["status"] == "synchronized"
            else "withheld_due_to_checklist_or_preflight_drift"
        ),
        "work_order_authority": {
            "accepts_evidence": False,
            "promotes_evidence": False,
            "writes_assembly_manifests": False,
            "writes_canonical_packets": False,
            "counts_as_acceptance_gate": False,
            "replaces_authoritative_validators": False,
        },
        "summary": {
            "work_order_count": len(work_orders),
            "work_order_gate_ids": work_order_gate_ids,
            "preflight_state": _non_authoritative_state(preflight_report.get("preflight_state")),
            "preflight_blocked_gate_ids": blocked_gate_ids,
            "checklist_sync_status": _non_authoritative_state(
                preflight_report.get("checklist_sync", {}).get("status")
            ),
            "total_acceptance_state": _non_authoritative_state(
                preflight_report.get("summary", {}).get("total_acceptance_state")
            ),
            "gate_status_sha256": preflight_report.get("summary", {}).get("gate_status_sha256"),
        },
        "sync": sync,
        "global_safety_invariants": [
            "Do not copy templates into canonical inputs.",
            "Do not use inputs/test_* fixtures as real evidence.",
            "Do not store assembly manifests under inputs/*_real.",
            "Do not expose raw filesystem, NAS, object-store, database, or worker paths.",
            "Use validate-only command guidance from this report.",
            "Do not claim production readiness, top-tier validation, or completed human work from work orders.",
        ],
        "work_orders": work_orders,
    }
    report["report_sha256"] = sha256_json(
        {
            "work_order_gate_ids": work_order_gate_ids,
            "work_order_state": report["work_order_state"],
            "sync": sync,
            "gate_status_sha256": report["summary"]["gate_status_sha256"],
            "work_orders": work_orders,
        }
    )
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description=__doc__)


def main(argv: list[str] | None = None) -> None:
    build_arg_parser().parse_args([] if argv is None else argv)
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
