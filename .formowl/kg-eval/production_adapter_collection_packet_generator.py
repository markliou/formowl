#!/usr/bin/env python3
"""Generate non-evidence collection packets for production adapter validation.

The generated packet is operator assignment material for future production
adapter evidence collection. It does not create deployment manifests, adapter
artifacts, human labels, audit events, permission probe results, rollback smoke
results, assembly manifests, or the canonical production adapter packet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import production_adapter_packet_assembler as assembler
import production_adapter_path_validator as validator


ROOT = Path(__file__).resolve().parent
WORK_PACKETS = ROOT / "work_packets"
DEFAULT_OUTPUT_PATH = WORK_PACKETS / "production_adapter_collection_packet_preview.json"
CANONICAL_PACKET_PATH = validator.PACKET_PATH
REAL_ROOT = assembler.REAL_INPUT_ROOT
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,96}$")

FORBIDDEN_TEXT_MARKERS = (
    "file://",
    "s3://",
    "gs://",
    "object://",
    "postgres://",
    "postgresql://",
    "jdbc:",
    "redis://",
    "mongodb://",
    "mysql://",
    "mssql://",
    "nas://",
    "smb://",
    "nfs://",
    "webdav://",
    "minio://",
    "\\",
    "../",
    "/tmp/",
    "inputs/test_",
    "results/",
    "templates/",
    "template_only",
    "do_not_submit_as_evidence",
)

DEFAULT_COMPONENT_KINDS = {
    "postgres_metadata_store": "metadata_store",
    "pgvector_index": "vector_index",
    "retrieval_gateway": "access_checked_retrieval",
    "semantic_gateway": "mcp_semantic_gateway",
    "rapidfuzz_candidate_adapter": "candidate_entity_linkage",
    "splink_candidate_adapter": "candidate_record_linkage",
    "wiki_projection_adapter": "draft_only_projection",
}


class WorkPacketError(ValueError):
    """Raised when a work packet would be unsafe or evidence-shaped."""


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ensure_safe_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkPacketError(f"{field_name} must be a non-empty string")
    if not SAFE_ID_RE.match(value):
        raise WorkPacketError(f"{field_name} must be a safe identifier")
    lowered = value.lower()
    if any(marker in lowered for marker in ("test_", "fixture", "template")):
        raise WorkPacketError(f"{field_name} must not use test fixture or template markers")
    return value


def _reject_forbidden_text(value: str, field_name: str) -> None:
    lowered = value.lower()
    if value.startswith(("/", "\\")):
        raise WorkPacketError(f"{field_name} must not expose a raw path")
    if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
        raise WorkPacketError(
            f"{field_name} must not expose raw, test, result, or template sources"
        )
    if ":" in value and "://" in value:
        raise WorkPacketError(f"{field_name} must not expose URI-like sources")


def _safe_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkPacketError(f"{field_name} must be a non-empty string")
    _reject_forbidden_text(value, field_name)
    return value


def _safe_text_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise WorkPacketError(f"{field_name} must be a non-empty list")
    normalized = [_safe_text(item, field_name) for item in value]
    if len(set(normalized)) != len(normalized):
        raise WorkPacketError(f"{field_name} values must be distinct")
    return normalized


def normalize_component_kinds(component_kinds: dict[str, str] | None = None) -> dict[str, str]:
    source = component_kinds if component_kinds is not None else DEFAULT_COMPONENT_KINDS
    if not isinstance(source, dict) or not source:
        raise WorkPacketError("component kinds must be a non-empty mapping")
    missing = sorted(set(validator.REQUIRED_COMPONENTS) - set(source))
    extra = sorted(set(source) - set(validator.REQUIRED_COMPONENTS))
    if missing:
        raise WorkPacketError("component kinds missing components: " + ", ".join(missing))
    if extra:
        raise WorkPacketError("component kinds contain unsupported components: " + ", ".join(extra))
    normalized: dict[str, str] = {}
    for component_key in validator.REQUIRED_COMPONENTS:
        _ensure_safe_identifier(component_key, "component_key")
        normalized[component_key] = _ensure_safe_identifier(source[component_key], "component_kind")
    return normalized


def build_component_collection_plan(
    component_kinds: dict[str, str] | None = None,
) -> dict[str, Any]:
    normalized = normalize_component_kinds(component_kinds)
    rows = []
    for component_key in validator.REQUIRED_COMPONENTS:
        row = {
            "component_key": component_key,
            "collection_task_id": f"collect_{component_key}",
            "component_kind": normalized[component_key],
            "minimum_collection_checks": [
                "capture package or image digest outside this packet",
                "capture configuration digest outside this packet",
                "capture policy digest outside this packet",
                "verify permission filtering before content return",
                "verify canonical graph writes stay disabled on evidence path",
                "verify no raw internal endpoint or path appears in public artifacts",
            ],
        }
        row["row_sha256"] = sha256_json(row)
        rows.append(row)
    return {
        "plan_type": "production_adapter_component_collection_plan_v1",
        "required_component_count": len(validator.REQUIRED_COMPONENTS),
        "component_rows": rows,
        "later_real_packet_requirements": [
            "deployment must be four-specialist LLM-subagent-approved and non-synthetic; legacy human approval remains a backward-compatible route",
            "component artifacts must cover every required adapter exactly once",
            "adapter stack digest must bind every component artifact",
            "component evidence must not expose raw paths or backend connection strings",
        ],
    }


def build_audit_collection_plan() -> dict[str, Any]:
    rows = []
    for sequence, action_name in enumerate(validator.REQUIRED_AUDIT_ACTIONS):
        row = {
            "audit_action_name": action_name,
            "expected_sequence": sequence,
            "expected_control_outcome": validator.EXPECTED_AUDIT_DECISIONS[action_name],
            "collection_task_id": f"collect_audit_{sequence:02d}_{action_name}",
        }
        if action_name in {
            "revoked_grant_blocks_content",
            "private_candidate_redacted",
            "entity_match_without_grant_denied",
            "raw_asset_read_guard_rejected",
            "canonical_merge_guard_rejected",
        }:
            row["required_guard_review"] = "explicit_denial_with_reason"
        if action_name == "wiki_projection_draft_not_published":
            row["required_guard_review"] = "draft_only_projection"
        if action_name == "rollback_smoke_completed":
            row["required_guard_review"] = "rollback_verified"
        row["row_sha256"] = sha256_json(row)
        rows.append(row)
    return {
        "plan_type": "production_adapter_audit_collection_plan_v1",
        "required_action_count": len(validator.REQUIRED_AUDIT_ACTIONS),
        "audit_action_rows": rows,
        "later_real_packet_requirements": [
            "audit rows must bind one request, one resource reference, and one policy",
            "audit rows must preserve the required action order",
            "deny guards must include denial reasons",
            "revoked grant audit must bind revoked grant state",
            "wiki projection must remain draft-only",
        ],
    }


def build_review_and_probe_collection_plan() -> dict[str, Any]:
    false_merge_rows = []
    for adapter_key in validator.FALSE_MERGE_ADAPTERS:
        row = {
            "adapter_key": adapter_key,
            "collection_task_id": f"collect_false_merge_review_{adapter_key}",
            "minimum_review_checks": [
                "collect four-specialist LLM subagent panel identity outside this packet",
                "bind candidate-pair digest outside this packet",
                "bind two source-candidate digests outside this packet",
                "ensure all four fixed professional roles independently pass; legacy human review remains a backward-compatible route",
            ],
        }
        row["row_sha256"] = sha256_json(row)
        false_merge_rows.append(row)
    return {
        "plan_type": "production_adapter_review_probe_collection_plan_v1",
        "false_merge_review_rows": false_merge_rows,
        "permission_probe_checks": [
            "revoked grant content denied",
            "private content not returned",
            "raw asset access denied",
            "entity match does not grant access",
            "canonical merge without review denied",
            "private leak count remains zero",
            "raw asset access count remains zero",
            "entity match access count remains zero",
            "canonical write count remains zero",
        ],
        "rollback_smoke_checks": [
            "migration rollback verified",
            "partial failure rollback verified",
            "audit append-only behavior verified",
            "idempotent retry verified",
        ],
        "later_real_packet_requirements": [
            "false-merge labels must be reviewed by the four-specialist LLM subagent panel for RapidFuzz and Splink adapters; legacy human-reviewed labels remain a backward-compatible route",
            "permission probes must cover every required component",
            "rollback smoke must be tied to the same deployment evidence",
        ],
    }


def build_work_packet(
    *,
    component_kinds: dict[str, str] | None = None,
) -> dict[str, Any]:
    packet = {
        "work_packet_type": "production_adapter_collection_packet_preview_v1",
        "work_packet_state": "operator_assignment_only",
        "evidence_state": "non_evidence",
        "safe_output_root": "work_packets/",
        "forbidden_output_roots": [
            "inputs/production_adapter_real/",
            "inputs/test_*",
            "results/",
            "templates/",
        ],
        "artifact_boundary": {
            "creates_deployment_manifest": False,
            "creates_component_evidence": False,
            "creates_human_label_results": False,
            "creates_audit_events": False,
            "creates_permission_probe_results": False,
            "creates_rollback_smoke_results": False,
            "writes_assembly_manifest": False,
            "writes_canonical_packet": False,
            "touches_real_evidence_root": False,
            "counts_as_acceptance_gate": False,
        },
        "canonical_packet_not_written": str(CANONICAL_PACKET_PATH.relative_to(ROOT)),
        "real_evidence_root_not_written": str(REAL_ROOT.relative_to(ROOT)),
        "component_collection_plan": build_component_collection_plan(component_kinds),
        "audit_collection_plan": build_audit_collection_plan(),
        "review_probe_collection_plan": build_review_and_probe_collection_plan(),
        "validator_expectation": {
            "authoritative_validator_must_be_run_separately": True,
            "this_packet_is_sufficient_for_production_adapter_gate": False,
        },
    }
    packet["work_packet_sha256"] = sha256_json(packet)
    return packet


def safe_output_path(path_value: str) -> Path:
    if not isinstance(path_value, str) or not path_value.strip():
        raise WorkPacketError("output path must be a non-empty string")
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise WorkPacketError("output path must be a safe relative path")
    if not path.parts or path.parts[0] != "work_packets":
        raise WorkPacketError("output path must live under work_packets/")
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise WorkPacketError("output path symlinks are not accepted")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(WORK_PACKETS.resolve())
    except ValueError as exc:
        raise WorkPacketError("output path escapes the work packet root") from exc
    return resolved


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH.relative_to(ROOT)),
        help="safe relative output path under work_packets/",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    output_path = safe_output_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    packet = build_work_packet()
    output_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
