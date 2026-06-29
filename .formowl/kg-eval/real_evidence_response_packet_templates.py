#!/usr/bin/env python3
"""Generate non-evidence operator response-packet templates.

These templates are only starting points for human/operators to fill the first
missing response packets. They are deliberately rejected by response-intake
helpers as-is because they carry template-only fields and placeholder values.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import enterprise_multimodal_validation_validator as enterprise_validator
import fair_external_baseline_run_validator as fair_validator
import llm_subagent_adjudication as llm_panel
import production_adapter_path_validator as production_validator
import public_reproducible_evidence as public_evidence


ROOT = Path(__file__).resolve().parent
WORK_PACKETS = ROOT / "work_packets"

TEMPLATE_PATHS = {
    "fair_external_baseline_comparison": (
        WORK_PACKETS / "fair_baseline_response_packet.template.json"
    ),
    "annotation_adjudication_protocol": (
        WORK_PACKETS / "human_annotation_response_packet.template.json"
    ),
    "multimodal_semantic_validation": (
        WORK_PACKETS / "enterprise_multimodal_response_packet.template.json"
    ),
    "production_adapter_paths": (WORK_PACKETS / "production_adapter_response_packet.template.json"),
}


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _template_boundary() -> dict[str, bool]:
    return {
        "accepts_evidence": False,
        "promotes_evidence": False,
        "writes_candidate_artifacts": False,
        "writes_canonical_packets": False,
        "counts_as_acceptance_gate": False,
    }


def _template_header(gate_id: str) -> dict[str, Any]:
    return {
        "template_only": True,
        "do_not_submit_as_evidence": True,
        "gate_id": gate_id,
        "claim_boundary": _template_boundary(),
        "operator_instructions": [
            "Copy this template to inputs/*_real/<operator_run_id>/operator_response_packet.json.",
            "Replace every OPERATOR_* placeholder with real reviewed values.",
            "Remove template_only, do_not_submit_as_evidence, gate_id, claim_boundary, and operator_instructions before intake.",
            "For public reproducible mode, replace public_evidence_manifest_artifact with URL/license/snapshot/hash-bound sources; for private operator evidence, remove evidence_source_mode and public_evidence_manifest_artifact.",
            "Run real_evidence_submission_manifest.py before candidate intake.",
        ],
    }


def _llm_panel_template(target: str) -> dict[str, Any]:
    return {
        "artifact_type": llm_panel.PANEL_ARTIFACT_TYPE,
        "panel_id": "OPERATOR_PANEL_ID",
        "adjudication_target": target,
        "completed": True,
        "final_decision": "PASS",
        "human_adjudication_claimed": False,
        "input_artifact_sha256s": ["OPERATOR_REVIEWED_INPUT_ARTIFACT_64_HEX_SHA256"],
        "rubric_sha256": "OPERATOR_PANEL_RUBRIC_64_HEX_SHA256",
        "specialist_subagents": [
            {
                "subagent_id": f"OPERATOR_{specialty.upper()}_SUBAGENT_ID",
                "specialty": specialty,
                "professional_role": llm_panel.REQUIRED_PROFESSIONAL_ROLES[specialty],
                "model_name": "OPERATOR_MODEL_NAME",
                "model_version": "OPERATOR_MODEL_VERSION",
                "prompt_sha256": "OPERATOR_DISTINCT_PROMPT_64_HEX_SHA256",
                "rubric_sha256": "OPERATOR_PANEL_RUBRIC_64_HEX_SHA256",
                "run_id": f"OPERATOR_{specialty.upper()}_RUN_ID",
                "temperature": 0,
                "independent": True,
                "decision": "PASS",
                "blocking_findings": [],
                "reviewed_artifact_sha256s": ["OPERATOR_REVIEWED_INPUT_ARTIFACT_64_HEX_SHA256"],
                "output_sha256": "OPERATOR_DISTINCT_OUTPUT_64_HEX_SHA256",
            }
            for specialty in llm_panel.REQUIRED_SPECIALTIES
        ],
        "panel_decision_sha256": "OPERATOR_PANEL_DECISION_64_HEX_SHA256",
    }


def _public_evidence_manifest_template(gate_id: str) -> dict[str, Any]:
    sources = [
        {
            "source_id": "OPERATOR_PUBLIC_SOURCE_ID",
            "source_url": "https://OPERATOR_PUBLIC_SOURCE_URL",
            "source_type": "OPERATOR_PUBLIC_SOURCE_TYPE",
            "source_usage_role": "OPERATOR_PUBLIC_SOURCE_USAGE_ROLE",
            "license": "OPERATOR_PUBLIC_LICENSE",
            "version_or_snapshot": "OPERATOR_PUBLIC_VERSION_OR_SNAPSHOT",
            "retrieved_at": "OPERATOR_RETRIEVED_AT_UTC",
            "content_sha256": "OPERATOR_PUBLIC_SOURCE_CONTENT_64_HEX_SHA256",
            "archive_sha256": "OPERATOR_PUBLIC_SOURCE_ARCHIVE_64_HEX_SHA256",
            "derived_artifact_sha256s": ["OPERATOR_DERIVED_CANDIDATE_ARTIFACT_64_HEX_SHA256"],
            "publicly_accessible": True,
            "permission_allows_research_evaluation": True,
            "non_synthetic": True,
            "raw_private_payload": False,
        }
    ]
    return public_evidence.build_manifest(
        gate_id=gate_id,
        retrieved_at="OPERATOR_RETRIEVED_AT_UTC",
        public_sources=sources,
        covered_artifact_sha256s=["OPERATOR_DERIVED_CANDIDATE_ARTIFACT_64_HEX_SHA256"],
    )


def _fair_baseline_template() -> dict[str, Any]:
    payload = _template_header("fair_external_baseline_comparison")
    payload.update(
        {
            "response_packet_type": "fair_baseline_response_intake_v1",
            "operator_run_id": "OPERATOR_RUN_ID",
            "evidence_source_mode": public_evidence.PUBLIC_MODE,
            "public_evidence_manifest_artifact": _public_evidence_manifest_template(
                "fair_external_baseline_comparison"
            ),
            "run_environment": {
                "container_image_digest_sha256": "OPERATOR_64_HEX_CONTAINER_DIGEST",
                "non_synthetic_benchmark_context": True,
                "run_manifest_sha256": "OPERATOR_64_HEX_RUN_MANIFEST",
                "uses_mocked_llm_or_retrieval": False,
                "uses_real_external_packages": True,
            },
            "source_lock_sha256": "OPERATOR_EXPECTED_SOURCE_LOCK_SHA256",
            "baseline_runs": [
                {
                    "baseline_id": baseline_id,
                    "package_source_url": "OPERATOR_LOCKED_PACKAGE_SOURCE_URL",
                    "package_version": "OPERATOR_PACKAGE_VERSION",
                    "source_ids": ["OPERATOR_LOCKED_SOURCE_ID"],
                    "real_package_execution": True,
                    "mock_or_dry_run": False,
                    "synthetic_corpus": False,
                    "uses_mocked_llm_or_retrieval": False,
                    "run_manifest_sha256": "OPERATOR_64_HEX_RUN_MANIFEST",
                    "package_lock_artifact": {"artifact_type": "fair_baseline_package_lock_v1"},
                    "config_artifact": {"artifact_type": "fair_baseline_config_v1"},
                    "index_build_log_artifact": {
                        "artifact_type": "fair_baseline_index_build_log_v1"
                    },
                    "query_run_log_artifact": {"artifact_type": "fair_baseline_query_run_log_v1"},
                    "answer_output_artifact": {"artifact_type": "fair_baseline_answer_output_v1"},
                    "graph_output_artifact": {"artifact_type": "fair_baseline_graph_output_v1"},
                    "permission_probe_artifact": {
                        "artifact_type": "fair_baseline_permission_probe_v1"
                    },
                }
                for baseline_id in fair_validator.REQUIRED_BASELINES
            ],
            "llm_subagent_adjudication": _llm_panel_template("fair_external_baseline_comparison"),
            "graph_quality_validation": {
                "completed": True,
                "human_reviewed": False,
                "llm_subagent_reviewed": True,
                "per_baseline_rows": [
                    {
                        "baseline_id": baseline_id,
                        "graph_output_artifact_sha256": "OPERATOR_64_HEX_GRAPH_OUTPUT",
                        "reviewed_entity_count": "OPERATOR_POSITIVE_INTEGER",
                        "reviewed_relation_count": "OPERATOR_POSITIVE_INTEGER",
                    }
                    for baseline_id in fair_validator.REQUIRED_BASELINES
                ],
            },
            "permission_probes": [
                {
                    "baseline_id": baseline_id,
                    "permission_probe_artifact_sha256": "OPERATOR_64_HEX_PERMISSION_PROBE",
                    "private_content_leak_count": 0,
                    "raw_asset_access_count": 0,
                    **{probe: True for probe in fair_validator.REQUIRED_PERMISSION_PROBES},
                }
                for baseline_id in fair_validator.REQUIRED_BASELINES
            ],
        }
    )
    return payload


def _human_annotation_template() -> dict[str, Any]:
    payload = _template_header("annotation_adjudication_protocol")
    payload.update(
        {
            "response_packet_type": "human_annotation_response_intake_v1",
            "operator_run_id": "OPERATOR_RUN_ID",
            "evidence_source_mode": public_evidence.PUBLIC_MODE,
            "public_evidence_manifest_artifact": _public_evidence_manifest_template(
                "annotation_adjudication_protocol"
            ),
            "annotation_task_id": "OPERATOR_ANNOTATION_TASK_ID",
            "llm_subagent_adjudication_artifact": _llm_panel_template(
                "annotation_adjudication_protocol"
            ),
        }
    )
    return payload


def _enterprise_multimodal_template() -> dict[str, Any]:
    payload = _template_header("multimodal_semantic_validation")
    payload.update(
        {
            "response_packet_type": "enterprise_multimodal_response_intake_v1",
            "operator_run_id": "OPERATOR_RUN_ID",
            "evidence_source_mode": public_evidence.PUBLIC_MODE,
            "public_evidence_manifest_artifact": _public_evidence_manifest_template(
                "multimodal_semantic_validation"
            ),
            "pilot_manifest_artifact": {"artifact_type": "enterprise_multimodal_pilot_manifest_v1"},
            "validation_artifacts": [
                {
                    "modality": modality,
                    "artifact": {
                        "artifact_type": "enterprise_multimodal_validation_artifact_v1",
                        "modality": modality,
                    },
                }
                for modality in enterprise_validator.REQUIRED_MODALITIES
            ],
            "llm_subagent_adjudication_artifact": _llm_panel_template(
                "multimodal_semantic_validation"
            ),
            "business_decision_review_artifact": {
                "artifact_type": "enterprise_business_decision_review_v1",
                "human_reviewed": False,
                "llm_subagent_reviewed": True,
            },
            "permission_probe_artifact": {
                "artifact_type": "enterprise_multimodal_permission_probe_v1"
            },
        }
    )
    return payload


def _production_adapter_template() -> dict[str, Any]:
    payload = _template_header("production_adapter_paths")
    payload.update(
        {
            "response_packet_type": "production_adapter_response_intake_v1",
            "operator_run_id": "OPERATOR_RUN_ID",
            "evidence_source_mode": public_evidence.PUBLIC_MODE,
            "public_evidence_manifest_artifact": _public_evidence_manifest_template(
                "production_adapter_paths"
            ),
            "deployment_manifest_artifact": {
                "artifact_type": "production_adapter_deployment_manifest_v1"
            },
            "adapter_artifacts": [
                {
                    "component_id": component_id,
                    "artifact": {
                        "artifact_type": "production_adapter_component_artifact_v1",
                        "component_id": component_id,
                    },
                }
                for component_id in production_validator.REQUIRED_COMPONENTS
            ],
            "human_false_merge_label_artifact": {
                "artifact_type": "production_adapter_false_merge_labels_v1",
                "reviewer_type": "four_specialist_llm_subagent_panel",
                "llm_subagent_panel_reviewed": True,
            },
            "llm_subagent_adjudication_artifact": _llm_panel_template("production_adapter_paths"),
            "audit_trail_artifact": {"artifact_type": "production_adapter_audit_trail_v1"},
            "permission_probe_artifact": {
                "artifact_type": "production_adapter_permission_probe_v1"
            },
            "rollback_smoke_artifact": {"artifact_type": "production_adapter_rollback_smoke_v1"},
        }
    )
    return payload


def build_templates() -> dict[str, dict[str, Any]]:
    return {
        "fair_external_baseline_comparison": _fair_baseline_template(),
        "annotation_adjudication_protocol": _human_annotation_template(),
        "multimodal_semantic_validation": _enterprise_multimodal_template(),
        "production_adapter_paths": _production_adapter_template(),
    }


def emit_templates() -> dict[str, Any]:
    templates = build_templates()
    written: list[str] = []
    WORK_PACKETS.mkdir(parents=True, exist_ok=True)
    for gate_id, payload in templates.items():
        path = TEMPLATE_PATHS[gate_id]
        path.write_text(_json_text(payload), encoding="utf-8")
        written.append(str(path.relative_to(ROOT)))
    return {
        "artifact_id": "kg_real_evidence_response_packet_templates_v1",
        "mode": "emit",
        "written_templates": written,
        "authority": _template_boundary(),
    }


def check_templates() -> dict[str, Any]:
    expected = build_templates()
    stale: list[str] = []
    missing: list[str] = []
    for gate_id, payload in expected.items():
        path = TEMPLATE_PATHS[gate_id]
        if not path.exists():
            missing.append(str(path.relative_to(ROOT)))
            continue
        if path.read_text(encoding="utf-8") != _json_text(payload):
            stale.append(str(path.relative_to(ROOT)))
    return {
        "artifact_id": "kg_real_evidence_response_packet_templates_check_v1",
        "mode": "check",
        "up_to_date": not missing and not stale,
        "missing_templates": missing,
        "stale_templates": stale,
        "authority": _template_boundary(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-templates", action="store_true")
    parser.add_argument("--check-templates", action="store_true")
    args = parser.parse_args(argv)

    if args.emit_templates == args.check_templates:
        parser.error("exactly one of --emit-templates or --check-templates is required")

    report = emit_templates() if args.emit_templates else check_templates()
    print(_json_text(report), end="")
    return 0 if report.get("up_to_date", True) else 1


if __name__ == "__main__":
    sys.exit(main())
