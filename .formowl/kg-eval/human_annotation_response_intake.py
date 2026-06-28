#!/usr/bin/env python3
"""Seal real human annotation responses into validator-shaped artifacts.

This intake helper is the missing bridge between non-evidence work packets and
the authoritative human annotation validator. It does not create labels, accept
LLM-generated responses, or promote canonical packets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import human_annotation_adjudication_validator as validator
import human_annotation_packet_assembler as assembler


ROOT = Path(__file__).resolve().parent
REAL_ROOT = validator.REAL_ARTIFACT_ROOT_PATH
REAL_ROOT_PARTS = tuple(Path(validator.REAL_ARTIFACT_ROOT).parts)
WORK_PACKETS = ROOT / "work_packets"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,96}$")
SAFE_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,64}$")
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
ARTIFACT_FILENAMES = {
    "manifest_artifact": "manifest.json",
    "work_orders_artifact": "work_orders.json",
    "adjudication_artifact": "adjudication.json",
    "confusion_matrix_artifact": "confusion_matrix.json",
    "custody_receipt_artifact": "custody_receipt.json",
}
RESPONSE_PACKET_ALLOWED_FIELDS = {
    "response_packet_type",
    "operator_run_id",
    "annotation_task_id",
    "first_pass_submissions",
    "adjudication",
}
FIRST_PASS_SUBMISSION_ALLOWED_FIELDS = {
    "reviewer_id",
    "reviewer_type",
    "independent_first_pass",
    "generated_by_llm",
    "template_source",
    "human_attestation",
    "rows",
}
FIRST_PASS_ROW_ALLOWED_FIELDS = {
    "item_id",
    "label",
    "generated_by_llm",
    "template_source",
}
ADJUDICATION_ALLOWED_FIELDS = {
    "adjudicator_id",
    "reviewer_type",
    "opened_after_first_pass_seal",
    "generated_by_llm",
    "template_source",
    "human_attestation",
    "rows",
}
ADJUDICATION_ROW_ALLOWED_FIELDS = {
    "item_id",
    "final_label",
    "generated_by_llm",
    "template_source",
}
RAW_INTERNAL_FIELD_NAMES = {
    "absolute_path",
    "backend_path",
    "database_uri",
    "db_uri",
    "file_path",
    "filesystem_path",
    "local_path",
    "nas_path",
    "nfs_path",
    "object_store_uri",
    "object_store_url",
    "raw_path",
    "raw_paths",
    "raw_sql",
    "s3_uri",
    "scratch_path",
    "sql",
    "storage_uri",
    "worker_scratch_path",
}
CUSTODY_RECEIPT_FILENAME = "response_custody_receipt.json"


class IntakeError(ValueError):
    """Raised when human response intake would be unsafe or invalid."""


def _ensure_safe_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f"{field_name} must be a non-empty string")
    if not SAFE_ID_RE.match(value):
        raise IntakeError(f"{field_name} must be a safe identifier")
    lowered = value.lower()
    if any(marker in lowered for marker in ("test_", "fixture", "template")):
        raise IntakeError(f"{field_name} must not use test fixture or template markers")
    return value


def _ensure_safe_label(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f"{field_name} must be a non-empty string")
    if not SAFE_LABEL_RE.match(value):
        raise IntakeError(f"{field_name} must be a safe label")
    lowered = value.lower()
    if any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
        raise IntakeError(f"{field_name} must not expose raw, test, result, or template sources")
    return value


def _reject_forbidden_text(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        return
    lowered = value.lower()
    if value.startswith(("/", "\\")) or any(marker in lowered for marker in FORBIDDEN_TEXT_MARKERS):
        raise IntakeError(f"{field_name} must not expose raw, test, result, or template sources")


def _is_test_or_sandbox_path_parts(parts: tuple[str, ...]) -> bool:
    return any(
        part == "assembler_test"
        or part == "sandbox"
        or part.startswith("sandbox_")
        or part.endswith("_sandbox")
        or part.startswith("test_")
        or part.endswith("_test")
        or part.startswith("preflight_test")
        or part == "validator_fixture"
        for part in parts
    )


def safe_real_output_dir(path_value: str, *, allow_test_artifacts: bool = False) -> Path:
    if not isinstance(path_value, str) or not path_value.strip():
        raise IntakeError("output_dir must be a non-empty string")
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise IntakeError("output_dir must be a safe relative path")
    if (
        len(path.parts) <= len(REAL_ROOT_PARTS)
        or path.parts[: len(REAL_ROOT_PARTS)] != REAL_ROOT_PARTS
    ):
        raise IntakeError(f"output_dir must live under {validator.REAL_ARTIFACT_ROOT}")
    real_root_relative_parts = path.parts[len(REAL_ROOT_PARTS) :]
    if any(
        part == "templates" or part.endswith(".template.json") for part in real_root_relative_parts
    ):
        raise IntakeError("output_dir must not use template paths")
    if not allow_test_artifacts and _is_test_or_sandbox_path_parts(real_root_relative_parts):
        raise IntakeError("output_dir must not use test or sandbox paths")
    if not allow_test_artifacts and len(real_root_relative_parts) != 1:
        raise IntakeError(
            f"output_dir must be exactly {validator.REAL_ARTIFACT_ROOT}/<operator_run_id>"
        )
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise IntakeError("output_dir symlinks are not accepted")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(REAL_ROOT.resolve())
    except ValueError as exc:
        raise IntakeError("output_dir escapes the real human annotation root") from exc
    return resolved


def safe_work_packet_output_path(path_value: str) -> Path:
    if not isinstance(path_value, str) or not path_value.strip():
        raise IntakeError("assembly manifest output path must be a non-empty string")
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise IntakeError("assembly manifest output path must be a safe relative path")
    if not path.parts or path.parts[0] != "work_packets":
        raise IntakeError("assembly manifest output path must live under work_packets/")
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise IntakeError("assembly manifest output symlinks are not accepted")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(WORK_PACKETS.resolve())
    except ValueError as exc:
        raise IntakeError("assembly manifest output escapes work_packets/") from exc
    return resolved


def load_json_file(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise IntakeError("input JSON must be an object")
    return loaded


def _artifact_ref(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _relative_artifact_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _reject_symlink_components(path: Path, field_name: str) -> None:
    rel_path = path.relative_to(ROOT)
    current = ROOT
    for part in rel_path.parts:
        current = current / part
        if current.is_symlink():
            raise IntakeError(f"{field_name} symlinks are not accepted")


def _write_json(path: Path, payload: object) -> None:
    _reject_symlink_components(path, "intake output")
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(path, "intake output")
    created = False
    try:
        with path.open("x", encoding="utf-8") as handle:
            created = True
            handle.write(_artifact_json_text(payload))
    except FileExistsError as exc:
        raise IntakeError(
            f"intake output would overwrite existing artifact: {_relative_artifact_path(path)}"
        ) from exc
    except Exception as exc:
        if created:
            try:
                if path.is_symlink() or path.is_file():
                    path.unlink()
            except FileNotFoundError:
                pass
        raise IntakeError(f"intake output write failed: {_relative_artifact_path(path)}") from exc


def _cleanup_created_outputs(created_paths: list[Path], output_path: Path) -> None:
    for path in reversed(created_paths):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
        except FileNotFoundError:
            pass
    output_dirs = {
        path.parent
        for path in created_paths
        if path.parent == output_path or output_path in path.parents
    }
    output_dirs.add(output_path)
    for path in sorted(output_dirs, key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass


def _ensure_parent_dirs_available(paths: dict[str, Path]) -> None:
    for path in paths.values():
        try:
            rel_parent = path.parent.relative_to(ROOT)
        except ValueError as exc:
            raise IntakeError("intake output parent escapes workspace") from exc
        current = ROOT
        for part in rel_parent.parts:
            current = current / part
            if current.is_symlink():
                raise IntakeError("intake output parent symlinks are not accepted")
            if current.exists() and not current.is_dir():
                raise IntakeError("intake output parent must be a directory")


def _validate_allowed_fields(
    payload: dict[str, Any],
    allowed_fields: set[str],
    label: str,
) -> None:
    unsupported = sorted(set(payload) - allowed_fields)
    if unsupported:
        raise IntakeError(f"{label} has unsupported fields: " + ", ".join(unsupported))


def _reject_raw_internal_fields(payload: Any, *, label: str) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and key in RAW_INTERNAL_FIELD_NAMES:
                raise IntakeError(f"{label} contains raw/internal field: {key}")
            _reject_raw_internal_fields(value, label=label)
    elif isinstance(payload, list):
        for value in payload:
            _reject_raw_internal_fields(value, label=label)


def _artifact_json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def sha256_artifact_payload(payload: object) -> str:
    return hashlib.sha256(_artifact_json_text(payload).encode("utf-8")).hexdigest()


def _validated_work_packet(work_packet: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if work_packet.get("work_packet_type") != "human_annotation_work_packet_preview_v1":
        raise IntakeError("work packet type mismatch")
    boundary = work_packet.get("artifact_boundary")
    if not isinstance(boundary, dict):
        raise IntakeError("work packet artifact boundary missing")
    if boundary.get("writes_canonical_packet") is not False:
        raise IntakeError("work packet must not write canonical packets")
    if boundary.get("counts_as_acceptance_gate") is not False:
        raise IntakeError("work packet must not count as acceptance evidence")
    manifest = work_packet.get("manifest_artifact")
    work_orders = work_packet.get("work_orders_artifact")
    if not isinstance(manifest, dict) or not isinstance(work_orders, dict):
        raise IntakeError("work packet must include manifest and work-orders artifacts")
    blockers: list[str] = []
    manifest_by_item, _manifest_rows = validator._validate_manifest(manifest, blockers)
    validator._validate_work_orders(work_orders, manifest_by_item, blockers)
    if blockers:
        raise IntakeError(
            "work packet manifest/work-orders failed validator contract: " + "; ".join(blockers)
        )
    return manifest, work_orders


def _manifest_maps(
    manifest: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    blockers: list[str] = []
    manifest_by_item, manifest_rows = validator._validate_manifest(manifest, blockers)
    if blockers:
        raise IntakeError("manifest failed validator contract: " + "; ".join(blockers))
    return manifest_by_item, manifest_rows


def _work_order_maps(
    work_orders: dict[str, Any],
    manifest_by_item: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    blockers: list[str] = []
    by_id = validator._validate_work_orders(work_orders, manifest_by_item, blockers)
    if blockers:
        raise IntakeError("work orders failed validator contract: " + "; ".join(blockers))
    return by_id


def _human_attestation_is_present(value: object, field_name: str) -> None:
    if not isinstance(value, str) or len(value.strip()) < 12:
        raise IntakeError(f"{field_name} must include a human attestation")
    _reject_forbidden_text(value, field_name)


def _validate_submission_header(
    submission: dict[str, Any],
    expected_role: str,
    *,
    id_field: str = "reviewer_id",
) -> str:
    allowed_fields = (
        FIRST_PASS_SUBMISSION_ALLOWED_FIELDS
        if id_field == "reviewer_id"
        else ADJUDICATION_ALLOWED_FIELDS
    )
    _validate_allowed_fields(submission, allowed_fields, expected_role)
    _reject_raw_internal_fields(submission, label=expected_role)
    reviewer_id = _ensure_safe_identifier(submission.get(id_field), f"{expected_role} {id_field}")
    if submission.get("reviewer_type") != "human":
        raise IntakeError(f"{expected_role} reviewer_type must be human")
    if submission.get("generated_by_llm") is not False:
        raise IntakeError(f"{expected_role} generated_by_llm must be false")
    if submission.get("template_source") is not None:
        raise IntakeError(f"{expected_role} template_source must be null")
    _human_attestation_is_present(
        submission.get("human_attestation"), f"{expected_role} human_attestation"
    )
    return reviewer_id


def _first_pass_work_order(
    work_order_by_id: dict[str, dict[str, Any]],
    *,
    reviewer_id: str,
    item_id: str,
) -> dict[str, Any]:
    matches = [
        row
        for row in work_order_by_id.values()
        if row.get("role") == "first_pass"
        and row.get("reviewer_id") == reviewer_id
        and row.get("item_id") == item_id
    ]
    if len(matches) != 1:
        raise IntakeError(f"first-pass work order missing for {reviewer_id}/{item_id}")
    return matches[0]


def _adjudication_work_order(
    work_order_by_id: dict[str, dict[str, Any]],
    *,
    adjudicator_id: str,
    item_id: str,
) -> dict[str, Any]:
    matches = [
        row
        for row in work_order_by_id.values()
        if row.get("role") == "adjudicator"
        and row.get("reviewer_id") == adjudicator_id
        and row.get("item_id") == item_id
    ]
    if len(matches) != 1:
        raise IntakeError(f"adjudication work order missing for {adjudicator_id}/{item_id}")
    return matches[0]


def build_first_pass_artifacts(
    *,
    response_packet: dict[str, Any],
    manifest_by_item: dict[str, dict[str, Any]],
    work_order_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    submissions = response_packet.get("first_pass_submissions")
    if not isinstance(submissions, list) or len(submissions) != 2:
        raise IntakeError("exactly two first-pass submissions are required")
    artifacts: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    rows_by_item: dict[str, list[dict[str, Any]]] = {}
    reviewers: set[str] = set()
    for submission in submissions:
        if not isinstance(submission, dict):
            raise IntakeError("first-pass submission must be an object")
        reviewer_id = _validate_submission_header(submission, "first_pass")
        if reviewer_id in reviewers:
            raise IntakeError("first-pass reviewers must be distinct")
        reviewers.add(reviewer_id)
        if submission.get("independent_first_pass") is not True:
            raise IntakeError("first-pass submission must be independent")
        rows = submission.get("rows")
        if not isinstance(rows, list) or len(rows) != len(manifest_by_item):
            raise IntakeError(f"{reviewer_id} must label every manifest item exactly once")
        seen_items: set[str] = set()
        sealed_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise IntakeError("first-pass row must be an object")
            _validate_allowed_fields(row, FIRST_PASS_ROW_ALLOWED_FIELDS, "first-pass row")
            _reject_raw_internal_fields(row, label="first-pass row")
            item_id = _ensure_safe_identifier(row.get("item_id"), "first_pass item_id")
            if item_id in seen_items:
                raise IntakeError(f"{reviewer_id} submitted duplicate item labels")
            if item_id not in manifest_by_item:
                raise IntakeError(f"{reviewer_id} submitted unknown item_id")
            seen_items.add(item_id)
            label = _ensure_safe_label(row.get("label"), "first_pass label")
            if row.get("generated_by_llm") is not False:
                raise IntakeError("first-pass row generated_by_llm must be false")
            if row.get("template_source") is not None:
                raise IntakeError("first-pass row template_source must be null")
            work_order = _first_pass_work_order(
                work_order_by_id,
                reviewer_id=reviewer_id,
                item_id=item_id,
            )
            sealed_row = validator.with_row_hash(
                {
                    "submission_id": f"sub_{reviewer_id}_{item_id}",
                    "reviewer_id": reviewer_id,
                    "work_order_id": work_order["work_order_id"],
                    "item_id": item_id,
                    "manifest_row_sha256": manifest_by_item[item_id]["row_sha256"],
                    "label": label,
                    "generated_by_llm": False,
                    "template_source": None,
                }
            )
            sealed_rows.append(sealed_row)
            all_rows.append(sealed_row)
            rows_by_item.setdefault(item_id, []).append(sealed_row)
        if set(seen_items) != set(manifest_by_item):
            raise IntakeError(f"{reviewer_id} must label every manifest item")
        artifacts.append(
            {
                "artifact_type": "human_first_pass_submission_v1",
                "reviewer_id": reviewer_id,
                "reviewer_type": "human",
                "independent_first_pass": True,
                "sealed": True,
                "generated_by_llm": False,
                "template_source": None,
                "rows": sealed_rows,
                "submission_set_sha256": validator.sha256_json(
                    sorted(row["row_sha256"] for row in sealed_rows)
                ),
            }
        )
    for item_id, rows in rows_by_item.items():
        if len(rows) != 2 or len({row["reviewer_id"] for row in rows}) != 2:
            raise IntakeError(f"{item_id} requires two distinct first-pass labels")
    return artifacts, all_rows, rows_by_item


def _expected_disagreements_or_error(
    rows_by_item: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    disagreements = validator._expected_disagreements(rows_by_item)
    if not disagreements:
        raise IntakeError(
            "human annotation intake must include at least one first-pass disagreement"
        )
    return disagreements


def build_adjudication_artifact(
    *,
    response_packet: dict[str, Any],
    manifest_by_item: dict[str, dict[str, Any]],
    work_order_by_id: dict[str, dict[str, Any]],
    first_pass_rows: list[dict[str, Any]],
    rows_by_item: dict[str, list[dict[str, Any]]],
    manifest_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    adjudication = response_packet.get("adjudication")
    if not isinstance(adjudication, dict):
        raise IntakeError("adjudication response is required")
    adjudicator_id = _validate_submission_header(
        adjudication,
        "adjudication",
        id_field="adjudicator_id",
    )
    if adjudication.get("opened_after_first_pass_seal") is not True:
        raise IntakeError("adjudication must open after first-pass seal")
    first_pass_reviewers = {row["reviewer_id"] for row in first_pass_rows}
    if adjudicator_id in first_pass_reviewers:
        raise IntakeError("adjudicator must be distinct from first-pass reviewers")
    disagreements = _expected_disagreements_or_error(rows_by_item)
    disagreement_items = {row["item_id"] for row in disagreements}
    disagreement_sha = validator.sha256_json(disagreements)
    response_rows = adjudication.get("rows")
    if not isinstance(response_rows, list) or len(response_rows) != len(disagreement_items):
        raise IntakeError("adjudication rows must cover exactly the disagreement set")
    seen_items: set[str] = set()
    sealed_rows: list[dict[str, Any]] = []
    for row in response_rows:
        if not isinstance(row, dict):
            raise IntakeError("adjudication row must be an object")
        _validate_allowed_fields(row, ADJUDICATION_ROW_ALLOWED_FIELDS, "adjudication row")
        _reject_raw_internal_fields(row, label="adjudication row")
        item_id = _ensure_safe_identifier(row.get("item_id"), "adjudication item_id")
        if item_id not in disagreement_items:
            raise IntakeError("adjudication row references item outside disagreement set")
        if item_id in seen_items:
            raise IntakeError("duplicate adjudication row")
        seen_items.add(item_id)
        final_label = _ensure_safe_label(row.get("final_label"), "adjudication final_label")
        if row.get("generated_by_llm") is not False:
            raise IntakeError("adjudication row generated_by_llm must be false")
        if row.get("template_source") is not None:
            raise IntakeError("adjudication row template_source must be null")
        work_order = _adjudication_work_order(
            work_order_by_id,
            adjudicator_id=adjudicator_id,
            item_id=item_id,
        )
        sealed_rows.append(
            validator.with_row_hash(
                {
                    "adjudication_id": f"adj_{adjudicator_id}_{item_id}",
                    "adjudicator_id": adjudicator_id,
                    "work_order_id": work_order["work_order_id"],
                    "item_id": item_id,
                    "manifest_row_sha256": manifest_by_item[item_id]["row_sha256"],
                    "final_label": final_label,
                    "sealed_disagreement_set_sha256": disagreement_sha,
                    "generated_by_llm": False,
                    "template_source": None,
                }
            )
        )
    if seen_items != disagreement_items:
        raise IntakeError("adjudication rows must cover exactly the disagreement set")
    return (
        {
            "artifact_type": "human_final_adjudication_v1",
            "opened_after_first_pass_seal": True,
            "adjudicator_id": adjudicator_id,
            "adjudicator_type": "human",
            "generated_by_llm": False,
            "template_source": None,
            "manifest_artifact_sha256": manifest_sha256,
            "first_pass_rows_sha256": validator.sha256_json(first_pass_rows),
            "sealed_disagreement_set": disagreements,
            "sealed_disagreement_set_sha256": disagreement_sha,
            "rows": sealed_rows,
        },
        sealed_rows,
        disagreement_sha,
    )


def build_confusion_matrix_artifact(
    *,
    manifest_rows: list[dict[str, Any]],
    adjudication_rows: list[dict[str, Any]],
    rows_by_item: dict[str, list[dict[str, Any]]],
    adjudication_sha256: str,
) -> dict[str, Any]:
    final_by_item = {row["item_id"]: row["final_label"] for row in adjudication_rows}
    counts: dict[str, int] = {}
    for item in manifest_rows:
        item_id = item["item_id"]
        label = final_by_item.get(item_id)
        if label is None:
            labels = {row["label"] for row in rows_by_item.get(item_id, [])}
            if len(labels) != 1:
                raise IntakeError(f"{item_id} has no consensus or adjudication final label")
            label = next(iter(labels))
        counts[label] = counts.get(label, 0) + 1
    return {
        "artifact_type": "annotation_confusion_matrix_v1",
        "adjudication_artifact_sha256": adjudication_sha256,
        "item_count": len(manifest_rows),
        "final_label_counts": counts,
        "generated_by_llm": False,
    }


def build_custody_receipt_artifact(
    *,
    manifest_sha256: str,
    work_orders_sha256: str,
    first_pass_sha256s: list[str],
    adjudication_sha256: str,
    confusion_matrix_sha256: str,
    response_packet_sha256: str,
) -> dict[str, Any]:
    receipt = {
        "artifact_type": "annotation_custody_receipt_v1",
        "complete": True,
        "human_packet_complete": True,
        "response_packet_sha256": response_packet_sha256,
        "manifest_artifact_sha256": manifest_sha256,
        "work_orders_artifact_sha256": work_orders_sha256,
        "first_pass_submission_artifact_sha256s": sorted(first_pass_sha256s),
        "adjudication_artifact_sha256": adjudication_sha256,
        "confusion_matrix_artifact_sha256": confusion_matrix_sha256,
    }
    receipt["custody_receipt_sha256"] = validator.sha256_json(receipt)
    return receipt


def _planned_paths(output_dir: Path, first_pass_artifacts: list[dict[str, Any]]) -> dict[str, Path]:
    paths = {field: output_dir / filename for field, filename in ARTIFACT_FILENAMES.items()}
    for artifact in first_pass_artifacts:
        reviewer_id = artifact["reviewer_id"]
        paths[f"first_pass::{reviewer_id}"] = output_dir / f"first_pass_{reviewer_id}.json"
    paths["response_custody_receipt"] = output_dir / CUSTODY_RECEIPT_FILENAME
    return paths


def _ensure_no_overwrite(paths: dict[str, Path]) -> None:
    existing = [
        _relative_artifact_path(path)
        for path in paths.values()
        if path.exists() or path.is_symlink()
    ]
    if existing:
        raise IntakeError(
            "intake output would overwrite existing artifacts: " + ", ".join(sorted(existing))
        )


def _artifact_receipts(paths: dict[str, Path]) -> list[dict[str, str]]:
    receipts = []
    for key, path in sorted(paths.items()):
        if key == "response_custody_receipt":
            continue
        row: dict[str, str] = {
            "field": key,
            "path": _artifact_ref(path),
            "sha256": validator.sha256_file(path) or "",
        }
        if key.startswith("first_pass::"):
            row["reviewer_id"] = key.split("::", 1)[1]
            row["artifact_field"] = "first_pass_submission_artifact"
        receipts.append(row)
    return receipts


def build_intake_artifacts(
    *,
    work_packet: dict[str, Any],
    response_packet: dict[str, Any],
    output_dir: str,
    assembly_manifest_output: str | None = None,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    _validate_allowed_fields(response_packet, RESPONSE_PACKET_ALLOWED_FIELDS, "response packet")
    _reject_raw_internal_fields(response_packet, label="response packet")
    _reject_forbidden_text(response_packet.get("response_packet_type"), "response_packet_type")
    if response_packet.get("response_packet_type") != "human_annotation_response_intake_v1":
        raise IntakeError("response packet type mismatch")
    run_id = _ensure_safe_identifier(response_packet.get("operator_run_id"), "operator_run_id")
    output_path = safe_real_output_dir(output_dir, allow_test_artifacts=allow_test_artifacts)
    if output_path.name != run_id:
        raise IntakeError("output_dir final segment must match operator_run_id")
    assembly_manifest_path = (
        safe_work_packet_output_path(assembly_manifest_output)
        if assembly_manifest_output is not None
        else None
    )
    manifest, work_orders = _validated_work_packet(work_packet)
    if response_packet.get("annotation_task_id") != work_packet.get("annotation_task_id"):
        raise IntakeError("response packet annotation_task_id mismatch")
    response_packet_sha = sha256_artifact_payload(response_packet)
    manifest_by_item, manifest_rows = _manifest_maps(manifest)
    work_order_by_id = _work_order_maps(work_orders, manifest_by_item)
    first_pass_artifacts, first_pass_rows, rows_by_item = build_first_pass_artifacts(
        response_packet=response_packet,
        manifest_by_item=manifest_by_item,
        work_order_by_id=work_order_by_id,
    )
    planned_paths = _planned_paths(output_path, first_pass_artifacts)
    if assembly_manifest_path is not None:
        planned_paths["assembly_manifest"] = assembly_manifest_path
    _ensure_no_overwrite(planned_paths)
    _ensure_parent_dirs_available(planned_paths)

    manifest_sha = sha256_artifact_payload(manifest)
    work_orders_sha = sha256_artifact_payload(work_orders)
    adjudication, adjudication_rows, _disagreement_sha = build_adjudication_artifact(
        response_packet=response_packet,
        manifest_by_item=manifest_by_item,
        work_order_by_id=work_order_by_id,
        first_pass_rows=first_pass_rows,
        rows_by_item=rows_by_item,
        manifest_sha256=manifest_sha,
    )
    adjudication_sha = sha256_artifact_payload(adjudication)
    confusion_matrix = build_confusion_matrix_artifact(
        manifest_rows=manifest_rows,
        adjudication_rows=adjudication_rows,
        rows_by_item=rows_by_item,
        adjudication_sha256=adjudication_sha,
    )
    confusion_matrix_sha = sha256_artifact_payload(confusion_matrix)

    payloads: dict[str, object] = {
        "manifest_artifact": manifest,
        "work_orders_artifact": work_orders,
        "adjudication_artifact": adjudication,
        "confusion_matrix_artifact": confusion_matrix,
    }
    first_pass_manifest_refs = []
    first_pass_sha256s = []
    for artifact in first_pass_artifacts:
        reviewer_id = artifact["reviewer_id"]
        path = planned_paths[f"first_pass::{reviewer_id}"]
        digest = sha256_artifact_payload(artifact)
        first_pass_sha256s.append(digest)
        payloads[f"first_pass::{reviewer_id}"] = artifact
        first_pass_manifest_refs.append(
            {
                "reviewer_id": reviewer_id,
                "artifact": _artifact_ref(path),
            }
        )
    custody = build_custody_receipt_artifact(
        manifest_sha256=manifest_sha,
        work_orders_sha256=work_orders_sha,
        first_pass_sha256s=first_pass_sha256s,
        adjudication_sha256=adjudication_sha,
        confusion_matrix_sha256=confusion_matrix_sha,
        response_packet_sha256=response_packet_sha,
    )
    payloads["custody_receipt_artifact"] = custody

    assembly_manifest = {
        "manifest_artifact": _artifact_ref(planned_paths["manifest_artifact"]),
        "work_orders_artifact": _artifact_ref(planned_paths["work_orders_artifact"]),
        "first_pass_artifacts": first_pass_manifest_refs,
        "adjudication_artifact": _artifact_ref(planned_paths["adjudication_artifact"]),
        "confusion_matrix_artifact": _artifact_ref(planned_paths["confusion_matrix_artifact"]),
        "custody_receipt_artifact": _artifact_ref(planned_paths["custody_receipt_artifact"]),
    }
    created_paths: list[Path] = []
    try:
        for key, payload in payloads.items():
            _write_json(planned_paths[key], payload)
            created_paths.append(planned_paths[key])
        if assembly_manifest_path is not None:
            _write_json(assembly_manifest_path, assembly_manifest)
            created_paths.append(assembly_manifest_path)

        packet = assembler.assemble_packet(
            **assembly_manifest,
            allow_test_artifacts=allow_test_artifacts,
        )
        validation_report = assembler.validate_candidate(
            packet,
            allow_test_artifacts=allow_test_artifacts,
        )
    except (assembler.AssemblyError, IntakeError, OSError) as exc:
        _cleanup_created_outputs(created_paths, output_path)
        if isinstance(exc, IntakeError):
            raise
        raise IntakeError(str(exc)) from exc

    validation_summary = {
        "candidate_packet_validator_passed": validation_report.get("passed") is True,
        "blocker_count": len(validation_report.get("blockers", []))
        if isinstance(validation_report.get("blockers"), list)
        else 0,
        "metrics": validation_report.get("metrics", {}),
        "authoritative_validator_report_embedded": False,
        "counts_as_acceptance_gate": False,
    }
    candidate_packet_sha = validator.sha256_json(packet)
    response_custody_receipt = {
        "artifact_type": "human_annotation_response_custody_receipt_v1",
        "operator_run_id": run_id,
        "annotation_task_id": response_packet["annotation_task_id"],
        "response_packet_type": response_packet["response_packet_type"],
        "response_packet_sha256": response_packet_sha,
        "candidate_packet_sha256": candidate_packet_sha,
        "candidate_packet_validator_passed": validation_summary[
            "candidate_packet_validator_passed"
        ],
        "blocker_count": validation_summary["blocker_count"],
        "written_artifacts": _artifact_receipts(planned_paths),
        "assembly_manifest_output": str(assembly_manifest_path.relative_to(ROOT))
        if assembly_manifest_path is not None
        else None,
        "assembly_manifest_sha256": validator.sha256_file(assembly_manifest_path)
        if assembly_manifest_path is not None
        else None,
        "writes_canonical_packet": False,
        "canonical_packet_not_written": str(assembler.CANONICAL_PACKET_PATH.relative_to(ROOT)),
        "counts_as_acceptance_gate": False,
        "claim_boundary": {
            "supports_human_annotation_completed_claim": False,
            "supports_human_adjudication_completed_claim": False,
            "supports_canonical_packet_written_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }
    try:
        _write_json(planned_paths["response_custody_receipt"], response_custody_receipt)
        created_paths.append(planned_paths["response_custody_receipt"])
    except (IntakeError, OSError) as exc:
        _cleanup_created_outputs(created_paths, output_path)
        if isinstance(exc, IntakeError):
            raise
        raise IntakeError(str(exc)) from exc
    response_custody_receipt_sha = (
        validator.sha256_file(planned_paths["response_custody_receipt"]) or ""
    )
    return {
        "intake_packet_type": "human_annotation_response_intake_result_v1",
        "evidence_state": "candidate_artifacts_written",
        "writes_canonical_packet": False,
        "canonical_packet_not_written": str(assembler.CANONICAL_PACKET_PATH.relative_to(ROOT)),
        "output_dir": str(output_path.relative_to(ROOT)),
        "operator_run_id": run_id,
        "response_packet_sha256": response_packet_sha,
        "custody_receipt_artifact": _artifact_ref(planned_paths["response_custody_receipt"]),
        "custody_receipt_sha256": response_custody_receipt_sha,
        "assembly_manifest": assembly_manifest,
        "assembly_manifest_output": str(assembly_manifest_path.relative_to(ROOT))
        if assembly_manifest_path is not None
        else None,
        "assembly_manifest_sha256": validator.sha256_file(assembly_manifest_path)
        if assembly_manifest_path is not None
        else None,
        "candidate_packet_sha256": candidate_packet_sha,
        "validation_report": validation_summary,
        "claim_boundary": {
            "candidate_packet_validator_passed": validation_summary[
                "candidate_packet_validator_passed"
            ],
            "supports_human_annotation_completed_claim": False,
            "supports_human_adjudication_completed_claim": False,
            "supports_canonical_packet_written_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-packet", required=True, help="human annotation work packet JSON")
    parser.add_argument("--response-packet", required=True, help="real human response packet JSON")
    parser.add_argument(
        "--output-dir", required=True, help="safe relative path under inputs/human_annotation_real/"
    )
    parser.add_argument(
        "--assembly-manifest-output",
        help="optional safe relative output path under work_packets/",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    result = build_intake_artifacts(
        work_packet=load_json_file(Path(args.work_packet)),
        response_packet=load_json_file(Path(args.response_packet)),
        output_dir=args.output_dir,
        assembly_manifest_output=args.assembly_manifest_output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
