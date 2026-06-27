#!/usr/bin/env python3
"""Real human annotation/adjudication evidence validator.

This validator is the intake gate for the broad annotation objective. It accepts
only a supplied ``inputs/human_annotation_results_v1.json`` packet; deterministic
fixtures from ``annotation_protocol_recovery.py`` are not counted as human
completion evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"
RESULTS = ROOT / "results"
PACKET_PATH = INPUTS / "human_annotation_results_v1.json"
REAL_ARTIFACT_ROOT = "inputs/human_annotation_real"
REAL_ARTIFACT_ROOT_PATH = ROOT / REAL_ARTIFACT_ROOT
REAL_ARTIFACT_ROOT_PARTS = tuple(Path(REAL_ARTIFACT_ROOT).parts)

HEX64_CHARS = set("0123456789abcdef")
PACKET_ALLOWED_FIELDS = {
    "artifact_id",
    "evidence_kind",
    "recovered_after_tmp_loss",
    "manifest_artifact",
    "manifest_artifact_sha256",
    "work_orders_artifact",
    "work_orders_artifact_sha256",
    "first_pass_submission_artifacts",
    "adjudication_artifact",
    "adjudication_artifact_sha256",
    "confusion_matrix_artifact",
    "confusion_matrix_artifact_sha256",
    "custody_receipt_artifact",
    "custody_receipt_artifact_sha256",
    "claim_boundary",
}
CLAIM_BOUNDARY_ALLOWED_FIELDS = {
    "supports_human_annotation_completed_claim",
    "supports_human_adjudication_completed_claim",
    "supports_confusion_matrix_claim",
    "supports_custody_receipt_claim",
    "supports_synthetic_label_generation_claim",
    "supports_template_as_human_evidence_claim",
    "supports_production_ready_claim",
    "supports_top_tier_scientific_validation_claim",
}


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strong_hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in HEX64_CHARS for char in value)
        and len(set(value)) > 1
    )


def row_hash(row: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in row.items() if key != "row_sha256"})


def with_row_hash(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["row_sha256"] = row_hash(payload)
    return payload


def _is_test_or_sandbox_path_parts(parts: tuple[str, ...]) -> bool:
    return any(
        part == "assembler_test"
        or part.startswith("test_")
        or part.endswith("_test")
        or part.startswith("preflight_test")
        or part == "validator_fixture"
        for part in parts
    )


def _is_template_path_parts(parts: tuple[str, ...]) -> bool:
    return any(part == "templates" or part.endswith(".template.json") for part in parts)


def _path_has_symlink_component(path: Path) -> bool:
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def safe_relative_artifact_path(
    value: object,
    *,
    allow_test_artifacts: bool = False,
) -> Path | None:
    if artifact_path_rejection_reason(value, allow_test_artifacts=allow_test_artifacts):
        return None
    path = Path(str(value))
    candidate = (ROOT / path).resolve()
    try:
        candidate.relative_to(REAL_ARTIFACT_ROOT_PATH.resolve())
    except ValueError:
        return None
    return candidate


def artifact_path_rejection_reason(
    value: object,
    *,
    allow_test_artifacts: bool = False,
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "path missing or malformed"
    if value.startswith(("/", "\\", "file://", "s3://", "gs://", "object://")):
        return f"path must be under {REAL_ARTIFACT_ROOT}"
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        return f"path must be under {REAL_ARTIFACT_ROOT}"
    if (
        len(path.parts) <= len(REAL_ARTIFACT_ROOT_PARTS)
        or path.parts[: len(REAL_ARTIFACT_ROOT_PARTS)] != REAL_ARTIFACT_ROOT_PARTS
    ):
        return f"path must be under {REAL_ARTIFACT_ROOT}"
    real_root_relative_parts = path.parts[len(REAL_ARTIFACT_ROOT_PARTS) :]
    if _is_template_path_parts(real_root_relative_parts):
        return f"template artifacts are not accepted under {REAL_ARTIFACT_ROOT}"
    if not allow_test_artifacts and _is_test_or_sandbox_path_parts(real_root_relative_parts):
        return f"test or sandbox artifacts are not accepted under {REAL_ARTIFACT_ROOT}"
    if _path_has_symlink_component(path):
        return f"artifact symlinks are not accepted under {REAL_ARTIFACT_ROOT}"
    candidate = (ROOT / path).resolve()
    try:
        resolved_relative_parts = candidate.relative_to(REAL_ARTIFACT_ROOT_PATH.resolve()).parts
    except ValueError:
        return f"path must be under {REAL_ARTIFACT_ROOT}"
    if _is_template_path_parts(resolved_relative_parts):
        return f"template artifacts are not accepted under {REAL_ARTIFACT_ROOT}"
    if not allow_test_artifacts and _is_test_or_sandbox_path_parts(resolved_relative_parts):
        return f"test or sandbox artifacts are not accepted under {REAL_ARTIFACT_ROOT}"
    return None


def artifact_matches_sha256(
    path_value: object,
    digest_value: object,
    *,
    allow_test_artifacts: bool = False,
) -> bool:
    path = safe_relative_artifact_path(
        path_value,
        allow_test_artifacts=allow_test_artifacts,
    )
    return (
        path is not None
        and strong_hex64(digest_value)
        and path.exists()
        and sha256_file(path) == digest_value
    )


def load_artifact(
    path_value: object,
    digest_value: object,
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    if not artifact_matches_sha256(
        path_value,
        digest_value,
        allow_test_artifacts=allow_test_artifacts,
    ):
        return {}
    path = safe_relative_artifact_path(
        path_value,
        allow_test_artifacts=allow_test_artifacts,
    )
    if path is None:
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def load_input_packet() -> dict[str, Any]:
    if PACKET_PATH.is_symlink():
        return {"__input_packet_error": "human annotation results packet symlink not accepted"}
    if not PACKET_PATH.exists():
        return {}
    loaded = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _load_required_artifact(
    packet: dict[str, Any],
    artifact_field: str,
    expected_type: str,
    blockers: list[str],
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    digest_field = f"{artifact_field}_sha256"
    path_blocker = artifact_path_rejection_reason(
        packet.get(artifact_field),
        allow_test_artifacts=allow_test_artifacts,
    )
    if path_blocker:
        if path_blocker == "path missing or malformed":
            blockers.append(f"{artifact_field} missing or hash mismatch")
        else:
            blockers.append(f"{artifact_field} {path_blocker}")
        return {}
    if not artifact_matches_sha256(
        packet.get(artifact_field),
        packet.get(digest_field),
        allow_test_artifacts=allow_test_artifacts,
    ):
        blockers.append(f"{artifact_field} missing or hash mismatch")
        return {}
    artifact = load_artifact(
        packet.get(artifact_field),
        packet.get(digest_field),
        allow_test_artifacts=allow_test_artifacts,
    )
    if artifact.get("artifact_type") != expected_type:
        blockers.append(f"{artifact_field} artifact type mismatch")
    return artifact


def _validate_manifest(
    manifest: dict[str, Any], blockers: list[str]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    rows = manifest.get("items")
    if not isinstance(rows, list) or not rows:
        blockers.append("human annotation manifest items missing")
        rows = []
    by_item: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("human annotation manifest item hash mismatch")
            continue
        item_id = row.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            blockers.append("human annotation manifest item id missing")
            continue
        if item_id in by_item:
            blockers.append("duplicate human annotation manifest item id")
        by_item[item_id] = row
        for field in ("task_id", "source_ref", "source_observation_id"):
            if not isinstance(row.get(field), str) or not row[field]:
                blockers.append(f"{item_id} manifest {field} missing")
    if manifest.get("item_count") != len(rows):
        blockers.append("human annotation manifest item count mismatch")
    return by_item, rows


def _validate_work_orders(
    work_orders: dict[str, Any],
    manifest_by_item: dict[str, dict[str, Any]],
    blockers: list[str],
) -> dict[str, dict[str, Any]]:
    rows = work_orders.get("work_orders")
    if not isinstance(rows, list) or not rows:
        blockers.append("human annotation work orders missing")
        rows = []
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("human annotation work-order hash mismatch")
            continue
        work_order_id = row.get("work_order_id")
        if not isinstance(work_order_id, str) or not work_order_id:
            blockers.append("human annotation work-order id missing")
            continue
        if work_order_id in by_id:
            blockers.append("duplicate human annotation work-order id")
        by_id[work_order_id] = row
        manifest_row = manifest_by_item.get(row.get("item_id"))
        if not manifest_row or row.get("manifest_row_sha256") != manifest_row.get("row_sha256"):
            blockers.append("human annotation work-order manifest binding mismatch")
        if row.get("role") not in {"first_pass", "adjudicator"}:
            blockers.append("human annotation work-order role invalid")
        if not isinstance(row.get("reviewer_id"), str) or not row["reviewer_id"]:
            blockers.append("human annotation work-order reviewer missing")
    return by_id


def _validate_first_pass_submissions(
    packet: dict[str, Any],
    work_order_by_id: dict[str, dict[str, Any]],
    manifest_by_item: dict[str, dict[str, Any]],
    blockers: list[str],
    *,
    allow_test_artifacts: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[str]]:
    submission_refs = packet.get("first_pass_submission_artifacts")
    if not isinstance(submission_refs, list) or len(submission_refs) < 2:
        blockers.append("two independent first-pass human submission artifacts are not present")
        submission_refs = []

    all_rows: list[dict[str, Any]] = []
    rows_by_item: dict[str, list[dict[str, Any]]] = {}
    artifact_hashes: list[str] = []
    reviewers: set[str] = set()
    for ref in submission_refs:
        if not isinstance(ref, dict):
            blockers.append("first-pass submission artifact reference malformed")
            continue
        path_blocker = artifact_path_rejection_reason(
            ref.get("artifact"),
            allow_test_artifacts=allow_test_artifacts,
        )
        if path_blocker:
            if path_blocker == "path missing or malformed":
                blockers.append("first-pass submission artifact missing or hash mismatch")
            else:
                blockers.append(f"first-pass submission artifact {path_blocker}")
            continue
        if not artifact_matches_sha256(
            ref.get("artifact"),
            ref.get("artifact_sha256"),
            allow_test_artifacts=allow_test_artifacts,
        ):
            blockers.append("first-pass submission artifact missing or hash mismatch")
            continue
        artifact_hashes.append(ref["artifact_sha256"])
        artifact = load_artifact(
            ref.get("artifact"),
            ref.get("artifact_sha256"),
            allow_test_artifacts=allow_test_artifacts,
        )
        if artifact.get("artifact_type") != "human_first_pass_submission_v1":
            blockers.append("first-pass submission artifact type mismatch")
        reviewer_id = artifact.get("reviewer_id")
        reviewers.add(reviewer_id)
        if ref.get("reviewer_id") != reviewer_id:
            blockers.append("first-pass submission reviewer reference mismatch")
        if artifact.get("reviewer_type") != "human":
            blockers.append("first-pass submission reviewer is not human")
        if artifact.get("independent_first_pass") is not True:
            blockers.append("first-pass submission is not independent")
        if artifact.get("sealed") is not True:
            blockers.append("first-pass submission is not sealed")
        if (
            artifact.get("generated_by_llm") is not False
            or artifact.get("template_source") is not None
        ):
            blockers.append("first-pass submission is synthetic or template-derived")
        rows = artifact.get("rows")
        if not isinstance(rows, list) or not rows:
            blockers.append("first-pass submission rows missing")
            rows = []
        for row in rows:
            if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
                blockers.append("first-pass submission row hash mismatch")
                continue
            if row.get("reviewer_id") != reviewer_id:
                blockers.append("first-pass row reviewer mismatch")
            if row.get("generated_by_llm") is not False or row.get("template_source") is not None:
                blockers.append("first-pass row is synthetic or template-derived")
            work_order = work_order_by_id.get(row.get("work_order_id"))
            if not work_order:
                blockers.append("first-pass row references unknown work order")
            elif (
                work_order.get("role") != "first_pass"
                or work_order.get("reviewer_id") != reviewer_id
            ):
                blockers.append("first-pass row work-order binding mismatch")
            elif work_order.get("item_id") != row.get("item_id"):
                blockers.append("first-pass row work-order item mismatch")
            manifest_row = manifest_by_item.get(row.get("item_id"))
            if not manifest_row or row.get("manifest_row_sha256") != manifest_row.get("row_sha256"):
                blockers.append("first-pass row manifest binding mismatch")
            rows_by_item.setdefault(row.get("item_id"), []).append(row)
            all_rows.append(row)
        expected_set_hash = sha256_json(
            sorted(row.get("row_sha256") for row in rows if isinstance(row, dict))
        )
        if artifact.get("submission_set_sha256") != expected_set_hash:
            blockers.append("first-pass submission set hash mismatch")

    if len(reviewers) < 2:
        blockers.append("first-pass human reviewer identities are not distinct")
    for item_id in manifest_by_item:
        rows = rows_by_item.get(item_id, [])
        item_reviewers = {row.get("reviewer_id") for row in rows}
        if len(rows) != 2 or len(item_reviewers) != 2:
            blockers.append(f"{item_id} does not have two distinct first-pass human labels")
    return all_rows, rows_by_item, artifact_hashes


def _expected_disagreements(rows_by_item: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    disagreements = []
    for item_id, rows in rows_by_item.items():
        if len(rows) == 2 and rows[0].get("label") != rows[1].get("label"):
            ordered = sorted(rows, key=lambda row: str(row.get("reviewer_id")))
            disagreements.append(
                {
                    "item_id": item_id,
                    "first_row_sha256": ordered[0]["row_sha256"],
                    "second_row_sha256": ordered[1]["row_sha256"],
                }
            )
    return sorted(disagreements, key=lambda row: row["item_id"])


def _validate_adjudication(
    adjudication: dict[str, Any],
    work_order_by_id: dict[str, dict[str, Any]],
    manifest_by_item: dict[str, dict[str, Any]],
    rows_by_item: dict[str, list[dict[str, Any]]],
    blockers: list[str],
) -> tuple[list[dict[str, Any]], str]:
    if adjudication.get("opened_after_first_pass_seal") is not True:
        blockers.append("adjudication opened before first-pass seal")
    if adjudication.get("adjudicator_type") != "human":
        blockers.append("adjudicator is not human")
    if (
        adjudication.get("generated_by_llm") is not False
        or adjudication.get("template_source") is not None
    ):
        blockers.append("adjudication artifact is synthetic or template-derived")
    expected_disagreements = _expected_disagreements(rows_by_item)
    disagreement_sha = sha256_json(expected_disagreements)
    if adjudication.get("sealed_disagreement_set") != expected_disagreements:
        blockers.append("adjudication sealed disagreement set does not match first-pass rows")
    if adjudication.get("sealed_disagreement_set_sha256") != disagreement_sha:
        blockers.append("adjudication sealed disagreement set hash mismatch")
    if not expected_disagreements:
        blockers.append("human annotation packet does not exercise adjudication disagreement")
    first_pass_reviewers = {
        row.get("reviewer_id") for rows in rows_by_item.values() for row in rows
    }
    adjudicator_id = adjudication.get("adjudicator_id")
    if not isinstance(adjudicator_id, str) or not adjudicator_id:
        blockers.append("adjudicator id missing")
    if adjudicator_id in first_pass_reviewers:
        blockers.append("adjudicator is not distinct from first-pass reviewers")
    rows = adjudication.get("rows")
    if not isinstance(rows, list):
        blockers.append("adjudication rows missing")
        rows = []
    adjudicated_items = []
    disagreement_items = {row["item_id"] for row in expected_disagreements}
    for row in rows:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("adjudication row hash mismatch")
            continue
        if row.get("adjudicator_id") != adjudicator_id:
            blockers.append("adjudication row adjudicator mismatch")
        if row.get("generated_by_llm") is not False or row.get("template_source") is not None:
            blockers.append("adjudication row is synthetic or template-derived")
        work_order = work_order_by_id.get(row.get("work_order_id"))
        if not work_order:
            blockers.append("adjudication row references unknown work order")
        elif (
            work_order.get("role") != "adjudicator"
            or work_order.get("reviewer_id") != adjudicator_id
        ):
            blockers.append("adjudication row work-order binding mismatch")
        elif work_order.get("item_id") != row.get("item_id"):
            blockers.append("adjudication row work-order item mismatch")
        manifest_row = manifest_by_item.get(row.get("item_id"))
        if not manifest_row or row.get("manifest_row_sha256") != manifest_row.get("row_sha256"):
            blockers.append("adjudication row manifest binding mismatch")
        if row.get("sealed_disagreement_set_sha256") != disagreement_sha:
            blockers.append("adjudication row disagreement-set binding mismatch")
        adjudicated_items.append(row.get("item_id"))
    duplicate_items = {
        item_id for item_id in adjudicated_items if adjudicated_items.count(item_id) > 1
    }
    if duplicate_items:
        blockers.append("duplicate adjudication row for disagreement item")
    if set(adjudicated_items) != disagreement_items or len(adjudicated_items) != len(
        disagreement_items
    ):
        blockers.append("adjudication rows do not cover exactly the sealed disagreement set")
    return rows, disagreement_sha


def _validate_confusion_matrix(
    matrix: dict[str, Any],
    manifest_rows: list[dict[str, Any]],
    adjudication_rows: list[dict[str, Any]],
    rows_by_item: dict[str, list[dict[str, Any]]],
    adjudication_artifact_sha256: object,
    blockers: list[str],
) -> None:
    if matrix.get("adjudication_artifact_sha256") != adjudication_artifact_sha256:
        blockers.append("confusion matrix adjudication artifact binding mismatch")
    final_by_item = {row.get("item_id"): row.get("final_label") for row in adjudication_rows}
    counts: dict[str, int] = {}
    for item in manifest_rows:
        item_id = item.get("item_id")
        label = final_by_item.get(item_id)
        if label is None:
            first_pass_rows = rows_by_item.get(item_id, [])
            first_pass_labels = {
                row.get("label")
                for row in first_pass_rows
                if isinstance(row.get("label"), str) and row.get("label")
            }
            if len(first_pass_rows) != 2 or len(first_pass_labels) != 1:
                blockers.append("confusion matrix cannot derive first-pass consensus for item")
                continue
            label = next(iter(first_pass_labels))
        if not isinstance(label, str) or not label:
            blockers.append("confusion matrix cannot derive final label for item")
            continue
        counts[label] = counts.get(label, 0) + 1
    if matrix.get("item_count") != len(manifest_rows):
        blockers.append("confusion matrix item count mismatch")
    if matrix.get("final_label_counts") != counts:
        blockers.append("confusion matrix final label counts mismatch")
    if matrix.get("generated_by_llm") is not False:
        blockers.append("confusion matrix is synthetic or agent generated")


def _validate_custody(
    custody: dict[str, Any],
    packet: dict[str, Any],
    first_pass_hashes: list[str],
    blockers: list[str],
) -> None:
    if custody.get("complete") is not True:
        blockers.append("custody receipt is not complete")
    if custody.get("human_packet_complete") is not True:
        blockers.append("custody receipt does not certify human packet completion")
    expected = {
        "manifest_artifact_sha256": packet.get("manifest_artifact_sha256"),
        "work_orders_artifact_sha256": packet.get("work_orders_artifact_sha256"),
        "first_pass_submission_artifact_sha256s": sorted(first_pass_hashes),
        "adjudication_artifact_sha256": packet.get("adjudication_artifact_sha256"),
        "confusion_matrix_artifact_sha256": packet.get("confusion_matrix_artifact_sha256"),
    }
    for field, expected_value in expected.items():
        if custody.get(field) != expected_value:
            blockers.append(f"custody receipt {field} mismatch")
    if not strong_hex64(custody.get("response_packet_sha256")):
        blockers.append("custody receipt response_packet_sha256 missing")
    if not strong_hex64(custody.get("custody_receipt_sha256")):
        blockers.append("custody receipt hash missing")


def _validate_claim_boundary(packet: dict[str, Any], blockers: list[str]) -> None:
    claims = packet.get("claim_boundary")
    if not isinstance(claims, dict):
        blockers.append("human annotation packet claim boundary missing")
        claims = {}
    unsupported_fields = sorted(set(claims) - CLAIM_BOUNDARY_ALLOWED_FIELDS)
    if unsupported_fields:
        blockers.append(
            "human annotation packet claim boundary has unsupported fields: "
            + ", ".join(unsupported_fields)
        )
    for flag in (
        "supports_human_annotation_completed_claim",
        "supports_human_adjudication_completed_claim",
        "supports_confusion_matrix_claim",
        "supports_custody_receipt_claim",
    ):
        if claims.get(flag) is not True:
            blockers.append(f"human annotation packet missing claim: {flag}")
    for flag in (
        "supports_synthetic_label_generation_claim",
        "supports_template_as_human_evidence_claim",
        "supports_production_ready_claim",
        "supports_top_tier_scientific_validation_claim",
    ):
        if claims.get(flag) is not False:
            blockers.append(f"human annotation packet overclaims unsupported claim: {flag}")


def validate_packet(
    packet: dict[str, Any],
    *,
    allow_test_artifacts: bool = False,
) -> list[str]:
    blockers: list[str] = []
    if isinstance(packet.get("__input_packet_error"), str):
        return [packet["__input_packet_error"]]
    if not packet:
        return [
            "human annotation results packet missing",
            "two independent first-pass human submissions are not present",
            "adjudication-open receipt, final adjudication, confusion matrix, and custody receipt are not present",
        ]
    if packet.get("artifact_id") != "human_annotation_results_v1":
        blockers.append("human annotation results packet artifact id mismatch")
    if packet.get("evidence_kind") != "real_human_annotation_adjudication":
        blockers.append("human annotation results evidence kind mismatch")
    unsupported_fields = sorted(set(packet) - PACKET_ALLOWED_FIELDS)
    if unsupported_fields:
        blockers.append(
            "human annotation results packet has unsupported fields: "
            + ", ".join(unsupported_fields)
        )
    if packet.get("recovered_after_tmp_loss") is not False:
        blockers.append("human annotation packet cannot rely on lost /tmp artifacts")
    _validate_claim_boundary(packet, blockers)

    manifest = _load_required_artifact(
        packet,
        "manifest_artifact",
        "human_annotation_manifest_v1",
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    work_orders = _load_required_artifact(
        packet,
        "work_orders_artifact",
        "human_annotation_work_orders_v1",
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    adjudication = _load_required_artifact(
        packet,
        "adjudication_artifact",
        "human_final_adjudication_v1",
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    matrix = _load_required_artifact(
        packet,
        "confusion_matrix_artifact",
        "annotation_confusion_matrix_v1",
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    custody = _load_required_artifact(
        packet,
        "custody_receipt_artifact",
        "annotation_custody_receipt_v1",
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )

    manifest_by_item, manifest_rows = _validate_manifest(manifest, blockers)
    work_order_by_id = _validate_work_orders(work_orders, manifest_by_item, blockers)
    first_pass_rows, rows_by_item, first_pass_hashes = _validate_first_pass_submissions(
        packet,
        work_order_by_id,
        manifest_by_item,
        blockers,
        allow_test_artifacts=allow_test_artifacts,
    )
    adjudication_rows, disagreement_sha = _validate_adjudication(
        adjudication,
        work_order_by_id,
        manifest_by_item,
        rows_by_item,
        blockers,
    )
    if adjudication.get("manifest_artifact_sha256") != packet.get("manifest_artifact_sha256"):
        blockers.append("adjudication manifest artifact binding mismatch")
    if adjudication.get("first_pass_rows_sha256") != sha256_json(first_pass_rows):
        blockers.append("adjudication first-pass rows binding mismatch")
    if adjudication.get("sealed_disagreement_set_sha256") != disagreement_sha:
        blockers.append("adjudication disagreement hash binding mismatch")
    _validate_confusion_matrix(
        matrix,
        manifest_rows,
        adjudication_rows,
        rows_by_item,
        packet.get("adjudication_artifact_sha256"),
        blockers,
    )
    _validate_custody(custody, packet, first_pass_hashes, blockers)
    return sorted(set(blockers))


def build_report(
    packet: dict[str, Any] | None = None,
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    packet = load_input_packet() if packet is None else packet
    blockers = validate_packet(packet, allow_test_artifacts=allow_test_artifacts)
    first_pass_refs = (
        packet.get("first_pass_submission_artifacts", []) if isinstance(packet, dict) else []
    )
    report = {
        "artifact_id": "human_annotation_adjudication_validator_recovery_v1",
        "input_packet": "inputs/human_annotation_results_v1.json",
        "passed": not blockers,
        "blockers": blockers,
        "metrics": {
            "first_pass_submission_artifact_count": len(first_pass_refs)
            if isinstance(first_pass_refs, list)
            else 0,
            "manifest_artifact_present": bool(packet.get("manifest_artifact"))
            if isinstance(packet, dict)
            else False,
            "adjudication_artifact_present": bool(packet.get("adjudication_artifact"))
            if isinstance(packet, dict)
            else False,
            "confusion_matrix_artifact_present": bool(packet.get("confusion_matrix_artifact"))
            if isinstance(packet, dict)
            else False,
            "custody_receipt_artifact_present": bool(packet.get("custody_receipt_artifact"))
            if isinstance(packet, dict)
            else False,
        },
        "claim_boundary": {
            "supports_human_annotation_completed_claim": not blockers,
            "supports_human_adjudication_completed_claim": not blockers,
            "supports_confusion_matrix_claim": not blockers,
            "supports_custody_receipt_claim": not blockers,
            "supports_synthetic_label_generation_claim": False,
            "supports_template_as_human_evidence_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }
    if packet:
        report["packet_sha256"] = sha256_json(packet)
    return report


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "human_annotation_adjudication_validator.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
