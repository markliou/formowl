#!/usr/bin/env python3
"""Seal fair external-baseline operator responses into candidate artifacts.

This helper bridges non-evidence fair-baseline work packets and the
authoritative fair-baseline validator. It writes candidate artifacts only under
the real fair-baseline root and never promotes canonical packets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import fair_baseline_run_work_packet_generator as work_packet_generator
import fair_external_baseline_packet_assembler as assembler
import fair_external_baseline_run_validator as validator


ROOT = Path(__file__).resolve().parent
REAL_ROOT = validator.REAL_ARTIFACT_ROOT_PATH
REAL_ROOT_PARTS = tuple(Path(validator.REAL_ARTIFACT_ROOT).parts)
WORK_PACKETS = ROOT / "work_packets"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,96}$")
RUN_ARTIFACT_FILENAMES = {
    "package_lock_artifact": "package_lock.json",
    "config_artifact": "config.json",
    "index_build_log_artifact": "index_build_log.json",
    "query_run_log_artifact": "query_run_log.json",
    "answer_output_artifact": "answer_output.json",
    "graph_output_artifact": "graph_output.json",
    "permission_probe_artifact": "permission_probe.json",
}
RESPONSE_PACKET_ALLOWED_FIELDS = {
    "response_packet_type",
    "operator_run_id",
    "run_environment",
    "source_lock_sha256",
    "baseline_runs",
    "human_answer_adjudication",
    "graph_quality_validation",
    "permission_probes",
}
RUN_ENVIRONMENT_ALLOWED_FIELDS = {
    "container_image_digest_sha256",
    "non_synthetic_benchmark_context",
    "run_manifest_sha256",
    "uses_mocked_llm_or_retrieval",
    "uses_real_external_packages",
}
HUMAN_ANSWER_ADJUDICATION_ALLOWED_FIELDS = {
    "adjudicator_id",
    "artifact_id",
    "completed",
    "custody_receipt_sha256",
    "final_adjudication_sha256",
    "per_baseline_rows",
    "question_set_sha256",
    "reviewers",
    "synthetic_or_agent_generated",
}
HUMAN_ANSWER_REVIEWER_ALLOWED_FIELDS = {
    "independent_first_pass",
    "reviewer_id",
    "reviewer_type",
    "sealed_submission_sha256",
}
HUMAN_ANSWER_ROW_ALLOWED_FIELDS = {
    "answer_output_artifact_sha256",
    "baseline_id",
    "question_count",
}
GRAPH_QUALITY_VALIDATION_ALLOWED_FIELDS = {
    "completed",
    "human_reviewed",
    "per_baseline_rows",
}
GRAPH_QUALITY_ROW_ALLOWED_FIELDS = {
    "baseline_id",
    "graph_output_artifact_sha256",
    "reviewed_entity_count",
    "reviewed_relation_count",
}
PERMISSION_PROBE_ALLOWED_FIELDS = {
    "baseline_id",
    "permission_probe_artifact_sha256",
    "private_content_leak_count",
    "raw_asset_access_count",
    *validator.REQUIRED_PERMISSION_PROBES,
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
    """Raised when fair-baseline response intake would be unsafe or invalid."""


def _artifact_json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def sha256_artifact_payload(payload: object) -> str:
    return hashlib.sha256(_artifact_json_text(payload).encode("utf-8")).hexdigest()


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
        raise IntakeError("output_dir escapes the real fair-baseline root") from exc
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


def _validated_work_packet(work_packet: dict[str, Any]) -> None:
    if work_packet.get("work_packet_type") != "fair_baseline_run_work_packet_preview_v1":
        raise IntakeError("work packet type mismatch")
    boundary = work_packet.get("artifact_boundary")
    if not isinstance(boundary, dict):
        raise IntakeError("work packet artifact boundary missing")
    for field in (
        "executes_packages",
        "creates_run_artifacts",
        "creates_human_adjudication",
        "creates_graph_quality_review",
        "creates_permission_probe_results",
        "writes_canonical_packet",
        "touches_real_evidence_root",
        "counts_as_acceptance_gate",
    ):
        if boundary.get(field) is not False:
            raise IntakeError(f"work packet {field} must be false")
    source_lock = work_packet_generator.build_source_lock()
    if (
        work_packet.get("run_manifest_artifact", {}).get("source_lock_sha256")
        != source_lock["source_lock_sha256"]
    ):
        raise IntakeError("work packet source lock mismatch")


def _safe_payload(payload: object, field_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IntakeError(f"{field_name} must be a JSON object")
    try:
        assembler.reject_template_or_placeholder_payload(payload, label=field_name)
        assembler.reject_raw_internal_payload(payload, label=field_name)
    except assembler.AssemblyError as exc:
        raise IntakeError(str(exc)) from exc
    _reject_raw_internal_fields(payload, label=field_name)
    return payload


def _run_environment(response_packet: dict[str, Any]) -> dict[str, Any]:
    payload = _safe_payload(response_packet.get("run_environment"), "run_environment")
    _validate_allowed_fields(payload, RUN_ENVIRONMENT_ALLOWED_FIELDS, "run_environment")
    return payload


def _baseline_runs(response_packet: dict[str, Any]) -> list[dict[str, Any]]:
    entries = response_packet.get("baseline_runs")
    if not isinstance(entries, list):
        raise IntakeError("baseline_runs must be a list")
    by_baseline: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise IntakeError("baseline run entry must be a JSON object")
        try:
            assembler.reject_template_or_placeholder_payload(entry, label="baseline run")
            assembler.reject_raw_internal_payload(entry, label="baseline run")
        except assembler.AssemblyError as exc:
            raise IntakeError(str(exc)) from exc
        _reject_raw_internal_fields(entry, label="baseline run")
        unsupported = sorted(set(entry) - assembler.RUN_SOURCE_ALLOWED_FIELDS)
        if unsupported:
            raise IntakeError("baseline run has unsupported fields: " + ", ".join(unsupported))
        baseline_id = entry.get("baseline_id")
        if baseline_id not in validator.REQUIRED_BASELINES:
            raise IntakeError("baseline run id is unsupported")
        if baseline_id in by_baseline:
            raise IntakeError("baseline runs must be distinct by baseline_id")
        missing = sorted(assembler.RUN_SOURCE_ALLOWED_FIELDS - set(entry))
        if missing:
            raise IntakeError("baseline run is missing required fields")
        if entry.get("source_ids") != list(validator.REQUIRED_SOURCE_IDS_BY_BASELINE[baseline_id]):
            raise IntakeError(
                "baseline run source ids must match the locked literature source list"
            )
        by_baseline[baseline_id] = entry
    missing_baselines = sorted(set(validator.REQUIRED_BASELINES) - set(by_baseline))
    if missing_baselines:
        raise IntakeError("baseline runs missing baselines: " + ", ".join(missing_baselines))
    return [by_baseline[baseline_id] for baseline_id in validator.REQUIRED_BASELINES]


def _human_answer_adjudication(response_packet: dict[str, Any]) -> dict[str, Any]:
    payload = _safe_payload(
        response_packet.get("human_answer_adjudication"),
        "human_answer_adjudication",
    )
    _validate_allowed_fields(
        payload,
        HUMAN_ANSWER_ADJUDICATION_ALLOWED_FIELDS,
        "human_answer_adjudication",
    )
    reviewers = payload.get("reviewers")
    if not isinstance(reviewers, list):
        raise IntakeError("human_answer_adjudication reviewers must be a list")
    for reviewer in reviewers:
        if not isinstance(reviewer, dict):
            raise IntakeError("human_answer_adjudication reviewer must be a JSON object")
        _validate_allowed_fields(
            reviewer,
            HUMAN_ANSWER_REVIEWER_ALLOWED_FIELDS,
            "human_answer_adjudication reviewer",
        )
    rows = payload.get("per_baseline_rows")
    if not isinstance(rows, list):
        raise IntakeError("human_answer_adjudication per_baseline_rows must be a list")
    for row in rows:
        if not isinstance(row, dict):
            raise IntakeError("human_answer_adjudication row must be a JSON object")
        _validate_allowed_fields(
            row,
            HUMAN_ANSWER_ROW_ALLOWED_FIELDS,
            "human_answer_adjudication row",
        )
    return payload


def _graph_quality_validation(response_packet: dict[str, Any]) -> dict[str, Any]:
    payload = _safe_payload(
        response_packet.get("graph_quality_validation"),
        "graph_quality_validation",
    )
    _validate_allowed_fields(
        payload,
        GRAPH_QUALITY_VALIDATION_ALLOWED_FIELDS,
        "graph_quality_validation",
    )
    rows = payload.get("per_baseline_rows")
    if not isinstance(rows, list):
        raise IntakeError("graph_quality_validation per_baseline_rows must be a list")
    for row in rows:
        if not isinstance(row, dict):
            raise IntakeError("graph_quality_validation row must be a JSON object")
        _validate_allowed_fields(
            row,
            GRAPH_QUALITY_ROW_ALLOWED_FIELDS,
            "graph_quality_validation row",
        )
    return payload


def _permission_probes(response_packet: dict[str, Any]) -> list[dict[str, Any]]:
    permission_probes = response_packet.get("permission_probes")
    if not isinstance(permission_probes, list):
        raise IntakeError("permission_probes must be a list")
    try:
        assembler.reject_template_or_placeholder_payload(
            permission_probes, label="permission_probes"
        )
        assembler.reject_raw_internal_payload(permission_probes, label="permission_probes")
    except assembler.AssemblyError as exc:
        raise IntakeError(str(exc)) from exc
    _reject_raw_internal_fields(permission_probes, label="permission_probes")
    for row in permission_probes:
        if not isinstance(row, dict):
            raise IntakeError("permission_probe row must be a JSON object")
        _validate_allowed_fields(row, PERMISSION_PROBE_ALLOWED_FIELDS, "permission_probe row")
    return permission_probes


def _planned_paths(output_dir: Path, baseline_runs: list[dict[str, Any]]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for run in baseline_runs:
        baseline_id = str(run["baseline_id"])
        for field, filename in RUN_ARTIFACT_FILENAMES.items():
            paths[f"{baseline_id}::{field}"] = output_dir / baseline_id / filename
    paths["human_answer_adjudication"] = output_dir / "human_answer_adjudication.json"
    paths["graph_quality_validation"] = output_dir / "graph_quality_validation.json"
    paths["permission_probes"] = output_dir / "permission_probes.json"
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
        if "::" in key:
            baseline_id, artifact_field = key.split("::", 1)
            row["baseline_id"] = baseline_id
            row["artifact_field"] = artifact_field
        receipts.append(row)
    return receipts


def _assembly_baseline_runs(
    baseline_runs: list[dict[str, Any]],
    planned_paths: dict[str, Path],
) -> list[dict[str, Any]]:
    assembled = []
    for run in baseline_runs:
        baseline_id = str(run["baseline_id"])
        row = {
            key: run[key]
            for key in assembler.RUN_SOURCE_ALLOWED_FIELDS
            if key not in validator.RUN_ARTIFACT_FIELDS
        }
        for field in validator.RUN_ARTIFACT_FIELDS:
            row[field] = _artifact_ref(planned_paths[f"{baseline_id}::{field}"])
        assembled.append(row)
    return assembled


def build_intake_artifacts(
    *,
    work_packet: dict[str, Any],
    response_packet: dict[str, Any],
    output_dir: str,
    assembly_manifest_output: str | None = None,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    _validated_work_packet(work_packet)
    _validate_allowed_fields(response_packet, RESPONSE_PACKET_ALLOWED_FIELDS, "response packet")
    _reject_raw_internal_fields(response_packet, label="response packet")
    if response_packet.get("response_packet_type") != "fair_baseline_response_intake_v1":
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

    baseline_runs = _baseline_runs(response_packet)
    run_environment = _run_environment(response_packet)
    human_answer_adjudication = _human_answer_adjudication(response_packet)
    graph_quality_validation = _graph_quality_validation(response_packet)
    permission_probes = _permission_probes(response_packet)
    try:
        assembler.validate_source_lock_sha256(response_packet.get("source_lock_sha256"))
    except assembler.AssemblyError as exc:
        raise IntakeError(str(exc)) from exc

    planned_paths = _planned_paths(output_path, baseline_runs)
    if assembly_manifest_path is not None:
        planned_paths["assembly_manifest"] = assembly_manifest_path
    _ensure_no_overwrite(planned_paths)
    _ensure_parent_dirs_available(planned_paths)

    assembly_manifest = {
        "artifact_id": "fair_external_baseline_run_packet_v1",
        "evidence_kind": "non_synthetic_external_baseline_run",
        "recovered_after_tmp_loss": False,
        "run_environment": run_environment,
        "source_lock_sha256": response_packet.get("source_lock_sha256"),
        "baseline_runs": _assembly_baseline_runs(baseline_runs, planned_paths),
        "human_answer_adjudication": human_answer_adjudication,
        "graph_quality_validation": graph_quality_validation,
        "permission_probes": permission_probes,
        "claim_boundary": {
            "supports_fair_external_baseline_comparison_claim": True,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
            "supports_unreviewed_business_judgment_claim": False,
            "supports_unreviewed_canonical_merge_claim": False,
        },
    }
    created_paths: list[Path] = []
    try:
        for run in baseline_runs:
            baseline_id = str(run["baseline_id"])
            for field in validator.RUN_ARTIFACT_FIELDS:
                path = planned_paths[f"{baseline_id}::{field}"]
                _write_json(path, _safe_payload(run[field], field))
                created_paths.append(path)
        _write_json(planned_paths["human_answer_adjudication"], human_answer_adjudication)
        created_paths.append(planned_paths["human_answer_adjudication"])
        _write_json(planned_paths["graph_quality_validation"], graph_quality_validation)
        created_paths.append(planned_paths["graph_quality_validation"])
        _write_json(planned_paths["permission_probes"], permission_probes)
        created_paths.append(planned_paths["permission_probes"])
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
        "artifact_type": "fair_baseline_response_custody_receipt_v1",
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
            "supports_fair_external_baseline_comparison_claim": False,
            "supports_real_package_execution_claim": False,
            "supports_human_adjudicated_answer_quality_claim": False,
            "supports_graph_quality_validation_claim": False,
            "supports_permission_probe_claim": False,
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
        "intake_packet_type": "fair_baseline_response_intake_result_v1",
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
            "supports_fair_external_baseline_comparison_claim": False,
            "supports_real_package_execution_claim": False,
            "supports_human_adjudicated_answer_quality_claim": False,
            "supports_graph_quality_validation_claim": False,
            "supports_permission_probe_claim": False,
            "supports_canonical_packet_written_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-packet", required=True, help="fair baseline work packet JSON")
    parser.add_argument("--response-packet", required=True, help="real fair baseline response JSON")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="safe relative path under inputs/fair_baseline_real/",
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
