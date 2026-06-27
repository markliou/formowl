#!/usr/bin/env python3
"""Generate non-evidence work packets for real human annotation.

The generated manifest and work orders are assignment material for future human
reviewers. They do not contain reviewer answers or a canonical results packet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import human_annotation_adjudication_validator as validator


ROOT = Path(__file__).resolve().parent
WORK_PACKETS = ROOT / "work_packets"
DEFAULT_OUTPUT_PATH = WORK_PACKETS / "human_annotation_work_packet_preview.json"
CANONICAL_PACKET_PATH = validator.INPUTS / "human_annotation_results_v1.json"
REAL_ROOT = validator.INPUTS / "human_annotation_real"
FORMOWL_OBSERVATION_PREFIX = "formowl://observation/"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,96}$")
FORBIDDEN_TEXT_MARKERS = (
    "file://",
    "s3://",
    "gs://",
    "object://",
    "postgres://",
    "postgresql://",
    "mysql://",
    "\\",
    "../",
    "/tmp/",
    "inputs/test_",
    "results/",
    "templates/",
    "template_only",
    "do_not_submit_as_evidence",
)

DEFAULT_ANNOTATION_TASK_ID = "kg_eval_human_annotation_v1"
DEFAULT_ITEMS = [
    {
        "item_id": "ann_finance_table_revenue_001",
        "task_id": "evidence_supported_claim",
        "source_ref": "formowl://observation/obs_finance_table_revenue_001",
        "source_observation_id": "obs_finance_table_revenue_001",
    },
    {
        "item_id": "ann_meeting_decision_001",
        "task_id": "business_decision_candidate",
        "source_ref": "formowl://observation/obs_meeting_decision_001",
        "source_observation_id": "obs_meeting_decision_001",
    },
]
DEFAULT_FIRST_PASS_REVIEWERS = ["human_reviewer_alpha", "human_reviewer_beta"]
DEFAULT_ADJUDICATOR_ID = "human_adjudicator_gamma"


class WorkPacketError(ValueError):
    """Raised when a work packet would be unsafe or non-deterministic."""


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ensure_safe_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkPacketError(f"{field_name} must be a non-empty string")
    if not SAFE_ID_RE.match(value):
        raise WorkPacketError(f"{field_name} must be a safe FormOwl identifier")
    lowered = value.lower()
    if any(marker in lowered for marker in ("test_", "fixture", "template")):
        raise WorkPacketError(f"{field_name} must not use test fixture or template markers")
    return value


def _reject_forbidden_text(value: str, field_name: str) -> None:
    lowered = value.lower()
    if value.startswith(("/", "\\")):
        raise WorkPacketError(f"{field_name} must not expose a raw path")
    if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
        raise WorkPacketError(f"{field_name} must not expose raw, test, result, or template sources")


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    item_id = _ensure_safe_identifier(item.get("item_id"), "item_id")
    task_id = _ensure_safe_identifier(item.get("task_id"), "task_id")
    source_observation_id = _ensure_safe_identifier(
        item.get("source_observation_id"),
        "source_observation_id",
    )
    source_ref = item.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        raise WorkPacketError("source_ref must be a non-empty string")
    _reject_forbidden_text(source_ref, "source_ref")
    if not source_ref.startswith(FORMOWL_OBSERVATION_PREFIX):
        raise WorkPacketError("source_ref must be a FormOwl observation locator")
    if source_ref != f"{FORMOWL_OBSERVATION_PREFIX}{source_observation_id}":
        raise WorkPacketError("source_ref must bind exactly to source_observation_id")
    return {
        "item_id": item_id,
        "task_id": task_id,
        "source_ref": source_ref,
        "source_observation_id": source_observation_id,
    }


def normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise WorkPacketError("items must be a non-empty list")
    normalized = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise WorkPacketError("each annotation item must be an object")
        row = _normalize_item(item)
        if row["item_id"] in seen:
            raise WorkPacketError("item_id values must be distinct")
        seen.add(row["item_id"])
        normalized.append(row)
    return normalized


def normalize_reviewers(first_pass_reviewer_ids: list[str], adjudicator_id: str) -> tuple[list[str], str]:
    if not isinstance(first_pass_reviewer_ids, list) or len(first_pass_reviewer_ids) != 2:
        raise WorkPacketError("exactly two first-pass reviewer ids are required")
    reviewers = [
        _ensure_safe_identifier(reviewer_id, "first_pass_reviewer_id")
        for reviewer_id in first_pass_reviewer_ids
    ]
    if len(set(reviewers)) != 2:
        raise WorkPacketError("first-pass reviewer ids must be distinct")
    adjudicator = _ensure_safe_identifier(adjudicator_id, "adjudicator_id")
    if adjudicator in reviewers:
        raise WorkPacketError("adjudicator id must be distinct from first-pass reviewers")
    return reviewers, adjudicator


def build_manifest_artifact(
    *,
    annotation_task_id: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    task_id = _ensure_safe_identifier(annotation_task_id, "annotation_task_id")
    manifest_rows = [
        validator.with_row_hash(
            {
                "item_id": item["item_id"],
                "task_id": item["task_id"],
                "source_ref": item["source_ref"],
                "source_observation_id": item["source_observation_id"],
            }
        )
        for item in items
    ]
    return {
        "artifact_type": "human_annotation_manifest_v1",
        "annotation_task_id": task_id,
        "item_count": len(manifest_rows),
        "items": manifest_rows,
    }


def _work_order_id(role: str, reviewer_id: str, item_id: str) -> str:
    digest = sha256_json({"role": role, "reviewer_id": reviewer_id, "item_id": item_id})[:12]
    return f"wo_{role}_{digest}"


def build_work_orders_artifact(
    *,
    annotation_task_id: str,
    manifest_artifact: dict[str, Any],
    first_pass_reviewer_ids: list[str],
    adjudicator_id: str,
) -> dict[str, Any]:
    _ensure_safe_identifier(annotation_task_id, "annotation_task_id")
    reviewers, adjudicator = normalize_reviewers(first_pass_reviewer_ids, adjudicator_id)
    manifest_items = manifest_artifact.get("items", [])
    if not isinstance(manifest_items, list) or not manifest_items:
        raise WorkPacketError("manifest items are required before work-order generation")
    work_order_rows: list[dict[str, Any]] = []
    for item in manifest_items:
        if not isinstance(item, dict) or item.get("row_sha256") != validator.row_hash(item):
            raise WorkPacketError("manifest row hash mismatch")
        for reviewer_id in reviewers:
            work_order_rows.append(
                validator.with_row_hash(
                    {
                        "work_order_id": _work_order_id("first_pass", reviewer_id, item["item_id"]),
                        "reviewer_id": reviewer_id,
                        "role": "first_pass",
                        "item_id": item["item_id"],
                        "manifest_row_sha256": item["row_sha256"],
                    }
                )
            )
        work_order_rows.append(
            validator.with_row_hash(
                {
                    "work_order_id": _work_order_id("adjudicator", adjudicator, item["item_id"]),
                    "reviewer_id": adjudicator,
                    "role": "adjudicator",
                    "item_id": item["item_id"],
                    "manifest_row_sha256": item["row_sha256"],
                }
            )
        )
    return {
        "artifact_type": "human_annotation_work_orders_v1",
        "work_orders": work_order_rows,
    }


def build_work_packet(
    *,
    items: list[dict[str, Any]] | None = None,
    annotation_task_id: str = DEFAULT_ANNOTATION_TASK_ID,
    first_pass_reviewer_ids: list[str] | None = None,
    adjudicator_id: str = DEFAULT_ADJUDICATOR_ID,
) -> dict[str, Any]:
    normalized_items = normalize_items(items if items is not None else list(DEFAULT_ITEMS))
    reviewers, adjudicator = normalize_reviewers(
        first_pass_reviewer_ids if first_pass_reviewer_ids is not None else list(DEFAULT_FIRST_PASS_REVIEWERS),
        adjudicator_id,
    )
    manifest = build_manifest_artifact(
        annotation_task_id=annotation_task_id,
        items=normalized_items,
    )
    work_orders = build_work_orders_artifact(
        annotation_task_id=annotation_task_id,
        manifest_artifact=manifest,
        first_pass_reviewer_ids=reviewers,
        adjudicator_id=adjudicator,
    )
    packet = {
        "work_packet_type": "human_annotation_work_packet_preview_v1",
        "work_packet_state": "operator_assignment_only",
        "evidence_state": "non_evidence",
        "annotation_task_id": annotation_task_id,
        "safe_output_root": "work_packets/",
        "forbidden_output_roots": [
            "inputs/human_annotation_real/",
            "inputs/test_*",
            "results/",
            "templates/",
        ],
        "artifact_boundary": {
            "accepts_human_responses": False,
            "creates_downstream_evidence_artifacts": False,
            "writes_canonical_packet": False,
            "touches_real_evidence_root": False,
            "counts_as_acceptance_gate": False,
        },
        "canonical_packet_not_written": str(CANONICAL_PACKET_PATH.relative_to(ROOT)),
        "real_evidence_root_not_written": str(REAL_ROOT.relative_to(ROOT)),
        "manifest_artifact": manifest,
        "work_orders_artifact": work_orders,
        "validator_expectation": {
            "authoritative_validator_must_be_run_separately": True,
            "this_packet_is_sufficient_for_human_gate": False,
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
