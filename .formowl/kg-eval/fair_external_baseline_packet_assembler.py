#!/usr/bin/env python3
"""Assemble real fair external-baseline run packets from supplied artifacts.

This helper computes per-baseline artifact SHA256 references and optionally
validates the assembled packet in memory. It does not generate or repair run
environment flags, package identities, equalized hashes, adjudication rows,
graph-quality rows, permission probes, claim flags, or artifact payloads.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import fair_external_baseline_run_validator as validator


ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"
REAL_INPUT_PREFIX = ("inputs", "fair_baseline_real")
REAL_INPUT_ROOT = INPUTS / "fair_baseline_real"
CANONICAL_PACKET_PATH = INPUTS / "fair_external_baseline_run_packet.json"
TEMPLATE_MARKERS = {"template_only", "do_not_submit_as_evidence"}
PLACEHOLDER_MARKERS = ("fill-with-real", "fill-with-", "path-to-real")
FORBIDDEN_RAW_PREFIXES = (
    "/",
    "\\",
    "file://",
    "s3://",
    "gs://",
    "object://",
    "nas://",
    "smb://",
    "nfs://",
    "webdav://",
    "minio://",
    "postgres://",
    "postgresql://",
    "jdbc:",
)
POSITIVE_CLAIMS = {"supports_fair_external_baseline_comparison_claim"}
NEGATIVE_CLAIMS = validator.CLAIM_BOUNDARY_ALLOWED_FIELDS - POSITIVE_CLAIMS
RUN_SOURCE_ALLOWED_FIELDS = {
    "baseline_id",
    "package_source_url",
    "source_ids",
    "package_version",
    "real_package_execution",
    "mock_or_dry_run",
    "synthetic_corpus",
    *validator.EQUALIZED_FIELDS,
    *validator.RUN_ARTIFACT_FIELDS,
}
MANIFEST_ALLOWED_FIELDS = {
    "artifact_id",
    "evidence_kind",
    "recovered_after_tmp_loss",
    "run_environment",
    "source_lock_sha256",
    "baseline_runs",
    "human_answer_adjudication",
    "graph_quality_validation",
    "permission_probes",
    "claim_boundary",
}


class AssemblyError(ValueError):
    """Raised when supplied artifacts cannot be safely assembled."""


def load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssemblyError("artifact payload must be a JSON object")
    return loaded


def raw_internal_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    if len(stripped) >= 3 and stripped[1:3] in {":\\", ":/"}:
        return True
    lowered = stripped.lower()
    if lowered.startswith(FORBIDDEN_RAW_PREFIXES):
        return True
    if ":" not in lowered:
        return False
    scheme = lowered.split(":", 1)[0]
    base_scheme = scheme.split("+", 1)[0]
    return base_scheme in {
        "file",
        "s3",
        "gs",
        "object",
        "nas",
        "smb",
        "nfs",
        "webdav",
        "minio",
        "postgres",
        "postgresql",
        "jdbc",
    }


def reject_template_or_placeholder_payload(payload: Any, *, label: str) -> None:
    if isinstance(payload, dict):
        if TEMPLATE_MARKERS & set(payload):
            raise AssemblyError(f"{label} contains template markers")
        for key, value in payload.items():
            if isinstance(key, str) and any(marker in key for marker in PLACEHOLDER_MARKERS):
                raise AssemblyError(f"{label} contains placeholder template values")
            reject_template_or_placeholder_payload(value, label=label)
    elif isinstance(payload, list):
        for value in payload:
            reject_template_or_placeholder_payload(value, label=label)
    elif isinstance(payload, str) and any(marker in payload for marker in PLACEHOLDER_MARKERS):
        raise AssemblyError(f"{label} contains placeholder template values")


def reject_raw_internal_payload(payload: Any, *, label: str) -> None:
    if isinstance(payload, dict):
        for value in payload.values():
            reject_raw_internal_payload(value, label=label)
    elif isinstance(payload, list):
        for value in payload:
            reject_raw_internal_payload(value, label=label)
    elif raw_internal_value(payload):
        raise AssemblyError(f"{label} contains raw/internal artifact value")


def reject_unsafe_artifact_text(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    if any(marker in text for marker in PLACEHOLDER_MARKERS):
        raise AssemblyError("artifact contains placeholder template values")
    if any(marker in text for marker in TEMPLATE_MARKERS):
        raise AssemblyError("artifact contains template markers")
    for token in text.replace("=", " ").split():
        if raw_internal_value(token.strip("'\"(),[]{}<>")):
            raise AssemblyError("artifact contains raw/internal artifact value")
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return
    reject_template_or_placeholder_payload(loaded, label="artifact")
    reject_raw_internal_payload(loaded, label="artifact")


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
    if (
        raw_internal_value(path_value)
        or "://" in path_value
        or "\\" in path_value
        or any(":" in part for part in path.parts)
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
    ):
        raise AssemblyError("artifact path must be a safe relative path")
    if path.parts[:2] != REAL_INPUT_PREFIX:
        raise AssemblyError("artifact path must live under inputs/fair_baseline_real")
    real_root_relative_parts = path.parts[len(REAL_INPUT_PREFIX) :]
    if not allow_test_artifacts and _is_test_or_sandbox_path_parts(real_root_relative_parts):
        raise AssemblyError("test or sandbox artifact paths are not accepted")
    unresolved = ROOT / path
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise AssemblyError("artifact symlinks are not accepted")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(REAL_INPUT_ROOT.resolve())
    except ValueError as exc:
        raise AssemblyError("artifact path escapes the real fair baseline input root") from exc
    if resolved.is_symlink():
        raise AssemblyError("artifact symlinks are not accepted")
    if not resolved.is_file():
        raise AssemblyError("artifact path does not exist")
    return resolved


def artifact_ref(path_value: str, *, allow_test_artifacts: bool = False) -> tuple[str, str]:
    path = safe_real_artifact_path(path_value, allow_test_artifacts=allow_test_artifacts)
    reject_unsafe_artifact_text(path)
    return str(path.relative_to(ROOT)), validator.sha256_file(path) or ""


def validate_claim_boundary(claim_boundary: Any) -> dict[str, bool]:
    if not isinstance(claim_boundary, dict):
        raise AssemblyError("claim boundary must be supplied by the assembly manifest")
    unsupported_fields = sorted(set(claim_boundary) - validator.CLAIM_BOUNDARY_ALLOWED_FIELDS)
    if unsupported_fields:
        raise AssemblyError("claim boundary has unsupported fields")
    missing_fields = sorted(validator.CLAIM_BOUNDARY_ALLOWED_FIELDS - set(claim_boundary))
    if missing_fields:
        raise AssemblyError("claim boundary is missing required fields")
    if claim_boundary.get("supports_fair_external_baseline_comparison_claim") is not True:
        raise AssemblyError("claim boundary must explicitly support required fair baseline claim")
    for field in NEGATIVE_CLAIMS:
        if claim_boundary.get(field) is not False:
            raise AssemblyError("claim boundary overclaims unsupported claims")
    return dict(claim_boundary)


def validate_source_lock_sha256(source_lock_sha256: Any) -> str:
    if source_lock_sha256 != validator.literature.required_baseline_source_lock_sha256():
        raise AssemblyError("source lock hash must match the literature baseline source lock")
    return str(source_lock_sha256)


def baseline_run(entry: dict[str, Any], *, allow_test_artifacts: bool = False) -> dict[str, Any]:
    reject_template_or_placeholder_payload(entry, label="baseline run")
    reject_raw_internal_payload(entry, label="baseline run")
    unsupported_fields = sorted(set(entry) - RUN_SOURCE_ALLOWED_FIELDS)
    if unsupported_fields:
        raise AssemblyError("baseline run has unsupported fields")
    missing_fields = sorted(RUN_SOURCE_ALLOWED_FIELDS - set(entry))
    if missing_fields:
        raise AssemblyError("baseline run is missing required fields")
    baseline_id = entry.get("baseline_id")
    if baseline_id not in validator.REQUIRED_BASELINES:
        raise AssemblyError("baseline run id is unsupported")
    if entry.get("source_ids") != list(validator.REQUIRED_SOURCE_IDS_BY_BASELINE[baseline_id]):
        raise AssemblyError("baseline run source ids must match the locked literature source list")
    run = {
        key: entry[key]
        for key in RUN_SOURCE_ALLOWED_FIELDS
        if key not in validator.RUN_ARTIFACT_FIELDS
    }
    for artifact_field in validator.RUN_ARTIFACT_FIELDS:
        artifact_path, artifact_sha = artifact_ref(
            entry[artifact_field],
            allow_test_artifacts=allow_test_artifacts,
        )
        run[artifact_field] = artifact_path
        run[f"{artifact_field}_sha256"] = artifact_sha
    return run


def assemble_packet(
    *,
    artifact_id: str,
    evidence_kind: str,
    recovered_after_tmp_loss: bool,
    run_environment: dict[str, Any],
    source_lock_sha256: str,
    baseline_runs: list[dict[str, Any]],
    human_answer_adjudication: dict[str, Any],
    graph_quality_validation: dict[str, Any],
    permission_probes: list[dict[str, Any]],
    claim_boundary: dict[str, bool] | None = None,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    if artifact_id != "fair_external_baseline_run_packet_v1":
        raise AssemblyError("artifact id mismatch")
    if evidence_kind != "non_synthetic_external_baseline_run":
        raise AssemblyError("evidence kind mismatch")
    if recovered_after_tmp_loss is not False:
        raise AssemblyError("packet cannot rely on lost /tmp artifacts")
    for label, value, expected_type in (
        ("run environment", run_environment, dict),
        ("human answer adjudication", human_answer_adjudication, dict),
        ("graph quality validation", graph_quality_validation, dict),
        ("permission probes", permission_probes, list),
        ("baseline runs", baseline_runs, list),
    ):
        if not isinstance(value, expected_type):
            raise AssemblyError(f"{label} must be supplied by the assembly manifest")
    for label, value in (
        ("run environment", run_environment),
        ("human answer adjudication", human_answer_adjudication),
        ("graph quality validation", graph_quality_validation),
        ("permission probes", permission_probes),
    ):
        reject_template_or_placeholder_payload(value, label=label)
        reject_raw_internal_payload(value, label=label)
    runs = [
        baseline_run(entry, allow_test_artifacts=allow_test_artifacts) for entry in baseline_runs
    ]
    baseline_ids = [entry["baseline_id"] for entry in runs]
    if sorted(baseline_ids) != sorted(validator.REQUIRED_BASELINES):
        raise AssemblyError("baseline runs must cover each required baseline exactly once")
    return {
        "artifact_id": artifact_id,
        "evidence_kind": evidence_kind,
        "recovered_after_tmp_loss": recovered_after_tmp_loss,
        "run_environment": dict(run_environment),
        "source_lock_sha256": validate_source_lock_sha256(source_lock_sha256),
        "baseline_runs": runs,
        "human_answer_adjudication": dict(human_answer_adjudication),
        "graph_quality_validation": dict(graph_quality_validation),
        "permission_probes": list(permission_probes),
        "claim_boundary": validate_claim_boundary(claim_boundary),
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
    reject_template_or_placeholder_payload(loaded, label="assembly manifest")
    unsupported_fields = sorted(set(loaded) - MANIFEST_ALLOWED_FIELDS)
    if unsupported_fields:
        raise AssemblyError("assembly manifest has unsupported fields")
    missing_fields = sorted(MANIFEST_ALLOWED_FIELDS - set(loaded))
    if missing_fields:
        raise AssemblyError("assembly manifest is missing required fields")
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
        help="write inputs/fair_external_baseline_run_packet.json only if validation passes",
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
