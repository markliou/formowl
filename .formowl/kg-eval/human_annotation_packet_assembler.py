#!/usr/bin/env python3
"""Assemble real human annotation evidence packets from supplied artifacts.

This helper computes artifact SHA256 references and optionally validates the
assembled packet in memory. It does not generate labels, row hashes,
adjudication rows, confusion matrices, or custody receipts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import human_annotation_adjudication_validator as validator


ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"
REAL_INPUT_PREFIX = ("inputs", "human_annotation_real")
REAL_INPUT_ROOT = INPUTS / "human_annotation_real"
CANONICAL_PACKET_PATH = INPUTS / "human_annotation_results_v1.json"
TEMPLATE_MARKERS = {"template_only", "do_not_submit_as_evidence"}
MANIFEST_ALLOWED_FIELDS = {
    "manifest_artifact",
    "work_orders_artifact",
    "first_pass_artifacts",
    "adjudication_artifact",
    "confusion_matrix_artifact",
    "custody_receipt_artifact",
}


class AssemblyError(ValueError):
    """Raised when supplied artifacts cannot be safely assembled."""


def load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssemblyError("artifact payload must be a JSON object")
    return loaded


def _is_test_or_sandbox_path_parts(parts: tuple[str, ...]) -> bool:
    return any(
        part == "assembler_test"
        or part.startswith("test_")
        or part.endswith("_test")
        or part.startswith("preflight_test")
        or part == "validator_fixture"
        for part in parts
    )


def safe_real_artifact_path(path_value: str, *, allow_test_artifacts: bool = False) -> Path:
    if not isinstance(path_value, str) or not path_value.strip():
        raise AssemblyError("artifact path must be a non-empty string")
    path = Path(path_value)
    if path.name.endswith(".template.json") or "templates" in path.parts:
        raise AssemblyError("template artifact paths are not accepted")
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise AssemblyError("artifact path must be a safe relative path")
    if path.parts[:2] != REAL_INPUT_PREFIX:
        raise AssemblyError("artifact path must live under inputs/human_annotation_real")
    real_root_relative_parts = path.parts[len(REAL_INPUT_PREFIX) :]
    if not allow_test_artifacts and _is_test_or_sandbox_path_parts(real_root_relative_parts):
        raise AssemblyError("test or sandbox artifact paths are not accepted")
    unresolved = ROOT / path
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise AssemblyError("artifact symlinks are not accepted")
    if unresolved.is_symlink():
        raise AssemblyError("artifact symlinks are not accepted")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(REAL_INPUT_ROOT.resolve())
    except ValueError as exc:
        raise AssemblyError("artifact path escapes the real human annotation input root") from exc
    if resolved.is_symlink():
        raise AssemblyError("artifact symlinks are not accepted")
    if not resolved.is_file():
        raise AssemblyError("artifact path does not exist")
    return resolved


def artifact_ref(path_value: str, *, allow_test_artifacts: bool = False) -> tuple[str, str]:
    path = safe_real_artifact_path(path_value, allow_test_artifacts=allow_test_artifacts)
    payload = load_json(path)
    if TEMPLATE_MARKERS & set(payload):
        raise AssemblyError("template markers are not accepted in real artifacts")
    return str(path.relative_to(ROOT)), validator.sha256_file(path) or ""


def first_pass_ref(
    reviewer_id: str,
    artifact: str,
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, str]:
    if not isinstance(reviewer_id, str) or not reviewer_id:
        raise AssemblyError("first-pass reviewer id must be a non-empty string")
    artifact_path, artifact_sha = artifact_ref(
        artifact,
        allow_test_artifacts=allow_test_artifacts,
    )
    return {
        "reviewer_id": reviewer_id,
        "artifact": artifact_path,
        "artifact_sha256": artifact_sha,
    }


def assemble_packet(
    *,
    manifest_artifact: str,
    work_orders_artifact: str,
    first_pass_artifacts: list[dict[str, str]],
    adjudication_artifact: str,
    confusion_matrix_artifact: str,
    custody_receipt_artifact: str,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    if len(first_pass_artifacts) < 2:
        raise AssemblyError("at least two first-pass artifacts are required")
    reviewer_ids = [entry.get("reviewer_id", "") for entry in first_pass_artifacts]
    if len(set(reviewer_ids)) != len(reviewer_ids):
        raise AssemblyError("first-pass reviewer ids must be distinct")

    manifest_path, manifest_sha = artifact_ref(
        manifest_artifact,
        allow_test_artifacts=allow_test_artifacts,
    )
    work_orders_path, work_orders_sha = artifact_ref(
        work_orders_artifact,
        allow_test_artifacts=allow_test_artifacts,
    )
    adjudication_path, adjudication_sha = artifact_ref(
        adjudication_artifact,
        allow_test_artifacts=allow_test_artifacts,
    )
    matrix_path, matrix_sha = artifact_ref(
        confusion_matrix_artifact,
        allow_test_artifacts=allow_test_artifacts,
    )
    custody_path, custody_sha = artifact_ref(
        custody_receipt_artifact,
        allow_test_artifacts=allow_test_artifacts,
    )
    first_pass_refs = [
        first_pass_ref(
            entry.get("reviewer_id", ""),
            entry.get("artifact", ""),
            allow_test_artifacts=allow_test_artifacts,
        )
        for entry in first_pass_artifacts
    ]

    return {
        "artifact_id": "human_annotation_results_v1",
        "evidence_kind": "real_human_annotation_adjudication",
        "recovered_after_tmp_loss": False,
        "manifest_artifact": manifest_path,
        "manifest_artifact_sha256": manifest_sha,
        "work_orders_artifact": work_orders_path,
        "work_orders_artifact_sha256": work_orders_sha,
        "first_pass_submission_artifacts": first_pass_refs,
        "adjudication_artifact": adjudication_path,
        "adjudication_artifact_sha256": adjudication_sha,
        "confusion_matrix_artifact": matrix_path,
        "confusion_matrix_artifact_sha256": matrix_sha,
        "custody_receipt_artifact": custody_path,
        "custody_receipt_artifact_sha256": custody_sha,
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
    }


def validate_candidate(
    packet: dict[str, Any],
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    return validator.build_report(packet, allow_test_artifacts=allow_test_artifacts)


def _targets_canonical_packet(path: Path) -> bool:
    if path.resolve() == CANONICAL_PACKET_PATH.resolve():
        return True
    try:
        return (
            path.exists()
            and CANONICAL_PACKET_PATH.exists()
            and path.samefile(CANONICAL_PACKET_PATH)
        )
    except OSError:
        return False


def promote_packet(
    packet: dict[str, Any],
    *,
    output_path: Path = CANONICAL_PACKET_PATH,
    allow_test_artifacts: bool = False,
) -> None:
    if allow_test_artifacts and _targets_canonical_packet(output_path):
        raise AssemblyError("test artifact packets cannot be promoted to canonical input")
    report = validate_candidate(packet, allow_test_artifacts=allow_test_artifacts)
    if report.get("passed") is not True:
        raise AssemblyError("candidate packet failed validation and cannot be promoted")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> dict[str, Any]:
    loaded = load_json(path)
    if set(loaded) - MANIFEST_ALLOWED_FIELDS:
        raise AssemblyError("assembly manifest has unsupported fields")
    return loaded


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assembly-manifest", required=True, help="JSON manifest listing real artifact paths"
    )
    parser.add_argument(
        "--validate", action="store_true", help="validate the assembled packet in memory"
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="write inputs/human_annotation_results_v1.json only if validation passes",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    assembly_manifest = load_manifest(Path(args.assembly_manifest))
    packet = assemble_packet(**assembly_manifest)
    report = validate_candidate(packet) if args.validate or args.promote else None
    if args.promote:
        promote_packet(packet)
    output = {"packet": packet}
    if report is not None:
        output["validation_report"] = report
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
