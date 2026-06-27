#!/usr/bin/env python3
"""Seal enterprise multimodal operator responses into candidate artifacts.

This helper bridges non-evidence collection packets and the authoritative
enterprise multimodal validator. It writes candidate artifacts only under the
real enterprise multimodal root and never promotes canonical packets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import enterprise_multimodal_packet_assembler as assembler
import enterprise_multimodal_validation_validator as validator


ROOT = Path(__file__).resolve().parent
REAL_ROOT = validator.REAL_ARTIFACT_ROOT_PATH
REAL_ROOT_PARTS = tuple(Path(validator.REAL_ARTIFACT_ROOT).parts)
WORK_PACKETS = ROOT / "work_packets"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,96}$")
ARTIFACT_FILENAMES = {
    "pilot_manifest_artifact": "pilot_manifest.json",
    "human_adjudication_artifact": "human_adjudication.json",
    "business_decision_review_artifact": "business_decision_review.json",
    "permission_probe_artifact": "permission_probe.json",
}
RESPONSE_PACKET_ALLOWED_FIELDS = {
    "response_packet_type",
    "operator_run_id",
    "validation_artifacts",
    *ARTIFACT_FILENAMES,
}
CUSTODY_RECEIPT_FILENAME = "response_custody_receipt.json"


class IntakeError(ValueError):
    """Raised when enterprise multimodal intake would be unsafe or invalid."""


def _artifact_json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def sha256_artifact_payload(payload: object) -> str:
    return hashlib.sha256(_artifact_json_text(payload).encode("utf-8")).hexdigest()


def load_json_file(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise IntakeError("input JSON must be an object")
    return loaded


def _relative_artifact_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _artifact_ref(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _ensure_safe_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f"{field_name} must be a non-empty string")
    if not SAFE_ID_RE.match(value):
        raise IntakeError(f"{field_name} must be a safe identifier")
    lowered = value.lower()
    if any(marker in lowered for marker in ("test_", "fixture", "template")):
        raise IntakeError(f"{field_name} must not use test fixture or template markers")
    return value


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
        raise IntakeError("output_dir escapes the real enterprise multimodal root") from exc
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


def _validated_work_packet(work_packet: dict[str, Any]) -> None:
    if work_packet.get("work_packet_type") != "enterprise_multimodal_collection_packet_preview_v1":
        raise IntakeError("work packet type mismatch")
    boundary = work_packet.get("artifact_boundary")
    if not isinstance(boundary, dict):
        raise IntakeError("work packet artifact boundary missing")
    for field in (
        "creates_real_source_rows",
        "creates_real_validation_rows",
        "creates_human_review_results",
        "creates_business_review_results",
        "creates_permission_probe_results",
        "writes_assembly_manifest",
        "writes_canonical_packet",
        "touches_real_evidence_root",
        "counts_as_acceptance_gate",
    ):
        if boundary.get(field) is not False:
            raise IntakeError(f"work packet {field} must be false")


def _validate_response_packet_fields(response_packet: dict[str, Any]) -> None:
    unsupported = sorted(set(response_packet) - RESPONSE_PACKET_ALLOWED_FIELDS)
    if unsupported:
        raise IntakeError("response packet has unsupported fields: " + ", ".join(unsupported))


def _reject_raw_internal_fields(payload: Any, *, label: str) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and key in validator.FORBIDDEN_SOURCE_FIELDS:
                raise IntakeError(f"{label} contains raw/internal artifact field: {key}")
            _reject_raw_internal_fields(value, label=label)
    elif isinstance(payload, list):
        for value in payload:
            _reject_raw_internal_fields(value, label=label)


def _artifact_payload(response_packet: dict[str, Any], field: str) -> dict[str, Any]:
    payload = response_packet.get(field)
    if not isinstance(payload, dict):
        raise IntakeError(f"{field} must be a JSON object")
    try:
        assembler.reject_template_or_placeholder_payload(payload, label=field)
        assembler.reject_raw_internal_payload(payload, label=field)
    except assembler.AssemblyError as exc:
        raise IntakeError(str(exc)) from exc
    _reject_raw_internal_fields(payload, label=field)
    return payload


def _validation_payloads(response_packet: dict[str, Any]) -> list[dict[str, Any]]:
    entries = response_packet.get("validation_artifacts")
    if not isinstance(entries, list):
        raise IntakeError("validation_artifacts must be a list")
    by_modality: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise IntakeError("validation artifact entry must be a JSON object")
        unsupported = sorted(set(entry) - {"modality", "artifact"})
        if unsupported:
            raise IntakeError("validation artifact entry has unsupported fields")
        modality = entry.get("modality")
        if modality not in validator.REQUIRED_MODALITIES:
            raise IntakeError("validation artifact modality is unsupported")
        if modality in by_modality:
            raise IntakeError("validation artifacts must be distinct by modality")
        artifact = entry.get("artifact")
        if not isinstance(artifact, dict):
            raise IntakeError("validation artifact payload must be a JSON object")
        try:
            assembler.reject_template_or_placeholder_payload(artifact, label="validation artifact")
            assembler.reject_raw_internal_payload(artifact, label="validation artifact")
        except assembler.AssemblyError as exc:
            raise IntakeError(str(exc)) from exc
        _reject_raw_internal_fields(artifact, label="validation artifact")
        by_modality[modality] = artifact
    missing = sorted(set(validator.REQUIRED_MODALITIES) - set(by_modality))
    if missing:
        raise IntakeError("validation artifacts missing modalities: " + ", ".join(missing))
    return [
        {"modality": modality, "artifact": by_modality[modality]}
        for modality in validator.REQUIRED_MODALITIES
    ]


def _planned_paths(output_dir: Path, validation_payloads: list[dict[str, Any]]) -> dict[str, Path]:
    paths = {field: output_dir / filename for field, filename in ARTIFACT_FILENAMES.items()}
    for row in validation_payloads:
        modality = row["modality"]
        paths[f"validation::{modality}"] = output_dir / f"validation_{modality}.json"
    paths["response_custody_receipt"] = output_dir / CUSTODY_RECEIPT_FILENAME
    return paths


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
        if key.startswith("validation::"):
            row["modality"] = key.split("::", 1)[1]
            row["artifact_field"] = "validation_artifact"
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
    _validated_work_packet(work_packet)
    if response_packet.get("response_packet_type") != "enterprise_multimodal_response_intake_v1":
        raise IntakeError("response packet type mismatch")
    _validate_response_packet_fields(response_packet)
    run_id = _ensure_safe_identifier(response_packet.get("operator_run_id"), "operator_run_id")
    output_path = safe_real_output_dir(output_dir, allow_test_artifacts=allow_test_artifacts)
    if output_path.name != run_id:
        raise IntakeError("output_dir final segment must match operator_run_id")
    assembly_manifest_path = (
        safe_work_packet_output_path(assembly_manifest_output)
        if assembly_manifest_output is not None
        else None
    )

    validation_payloads = _validation_payloads(response_packet)
    payloads: dict[str, object] = {
        "pilot_manifest_artifact": _artifact_payload(response_packet, "pilot_manifest_artifact"),
        "human_adjudication_artifact": _artifact_payload(
            response_packet,
            "human_adjudication_artifact",
        ),
        "business_decision_review_artifact": _artifact_payload(
            response_packet,
            "business_decision_review_artifact",
        ),
        "permission_probe_artifact": _artifact_payload(
            response_packet, "permission_probe_artifact"
        ),
    }
    for row in validation_payloads:
        payloads[f"validation::{row['modality']}"] = row["artifact"]

    planned_paths = _planned_paths(output_path, validation_payloads)
    if assembly_manifest_path is not None:
        planned_paths["assembly_manifest"] = assembly_manifest_path
    _ensure_no_overwrite(planned_paths)
    _ensure_parent_dirs_available(planned_paths)

    assembly_manifest = {
        "artifact_id": "enterprise_multimodal_validation_packet_v1",
        "evidence_kind": "real_enterprise_multimodal_validation",
        "recovered_after_tmp_loss": False,
        "pilot_manifest_artifact": _artifact_ref(planned_paths["pilot_manifest_artifact"]),
        "validation_artifacts": [
            {
                "modality": row["modality"],
                "artifact": _artifact_ref(planned_paths[f"validation::{row['modality']}"]),
            }
            for row in validation_payloads
        ],
        "human_adjudication_artifact": _artifact_ref(planned_paths["human_adjudication_artifact"]),
        "business_decision_review_artifact": _artifact_ref(
            planned_paths["business_decision_review_artifact"]
        ),
        "permission_probe_artifact": _artifact_ref(planned_paths["permission_probe_artifact"]),
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
    response_packet_sha = sha256_artifact_payload(response_packet)
    candidate_packet_sha = validator.sha256_json(packet)
    custody_receipt = {
        "artifact_type": "enterprise_multimodal_response_custody_receipt_v1",
        "operator_run_id": run_id,
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
            "supports_real_enterprise_multimodal_claim": False,
            "supports_multimodal_human_adjudication_completed_claim": False,
            "supports_cross_modal_permission_probe_claim": False,
            "supports_business_decision_review_claim": False,
            "supports_canonical_packet_written_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }
    try:
        _write_json(planned_paths["response_custody_receipt"], custody_receipt)
        created_paths.append(planned_paths["response_custody_receipt"])
    except (IntakeError, OSError) as exc:
        _cleanup_created_outputs(created_paths, output_path)
        if isinstance(exc, IntakeError):
            raise
        raise IntakeError(str(exc)) from exc
    custody_receipt_sha = validator.sha256_file(planned_paths["response_custody_receipt"]) or ""
    return {
        "intake_packet_type": "enterprise_multimodal_response_intake_result_v1",
        "evidence_state": "candidate_artifacts_written",
        "writes_canonical_packet": False,
        "canonical_packet_not_written": str(assembler.CANONICAL_PACKET_PATH.relative_to(ROOT)),
        "output_dir": str(output_path.relative_to(ROOT)),
        "operator_run_id": run_id,
        "response_packet_sha256": response_packet_sha,
        "custody_receipt_artifact": _artifact_ref(planned_paths["response_custody_receipt"]),
        "custody_receipt_sha256": custody_receipt_sha,
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
            "supports_real_enterprise_multimodal_claim": False,
            "supports_multimodal_human_adjudication_completed_claim": False,
            "supports_cross_modal_permission_probe_claim": False,
            "supports_business_decision_review_claim": False,
            "supports_canonical_packet_written_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-packet", required=True, help="enterprise collection work packet JSON"
    )
    parser.add_argument(
        "--response-packet",
        required=True,
        help="real enterprise multimodal response packet JSON",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="safe relative path under inputs/enterprise_multimodal_real/",
    )
    parser.add_argument(
        "--assembly-manifest-output",
        help="optional safe relative output path under work_packets/",
    )
    parser.add_argument("--allow-test-artifacts", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    result = build_intake_artifacts(
        work_packet=load_json_file(Path(args.work_packet)),
        response_packet=load_json_file(Path(args.response_packet)),
        output_dir=args.output_dir,
        assembly_manifest_output=args.assembly_manifest_output,
        allow_test_artifacts=args.allow_test_artifacts,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
