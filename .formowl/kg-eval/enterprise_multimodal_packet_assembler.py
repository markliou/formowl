#!/usr/bin/env python3
"""Assemble real enterprise multimodal validation packets from supplied artifacts.

This helper computes artifact SHA256 references and optionally validates the
assembled packet in memory. It does not generate or repair enterprise pilot
rows, validation rows, adjudication rows, business-decision review rows,
permission probes, claim flags, or row hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import enterprise_multimodal_validation_validator as validator
import public_reproducible_evidence as public_evidence


ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"
REAL_INPUT_PREFIX = ("inputs", "enterprise_multimodal_real")
REAL_INPUT_ROOT = INPUTS / "enterprise_multimodal_real"
CANONICAL_PACKET_PATH = INPUTS / "enterprise_multimodal_validation_packet.json"
TEMPLATE_MARKERS = {"template_only", "do_not_submit_as_evidence"}
PLACEHOLDER_MARKERS = ("fill-with-real", "path-to-real")
POSITIVE_CLAIMS = {
    "supports_real_enterprise_multimodal_claim",
    "supports_cross_modal_permission_probe_claim",
    "supports_business_decision_review_claim",
}
ROUTE_CLAIMS = {
    "supports_multimodal_human_adjudication_completed_claim",
    "supports_multimodal_llm_subagent_adjudication_completed_claim",
    public_evidence.CLAIM_FIELD,
}
NEGATIVE_CLAIMS = validator.CLAIM_BOUNDARY_ALLOWED_FIELDS - POSITIVE_CLAIMS - ROUTE_CLAIMS
MANIFEST_ALLOWED_FIELDS = {
    "artifact_id",
    "evidence_kind",
    "recovered_after_tmp_loss",
    "pilot_manifest_artifact",
    "validation_artifacts",
    "human_adjudication_artifact",
    "llm_subagent_adjudication_artifact",
    "business_decision_review_artifact",
    "permission_probe_artifact",
    "claim_boundary",
    "evidence_source_mode",
    "public_evidence_manifest_artifact",
}
MANIFEST_COMMON_REQUIRED_FIELDS = {
    "artifact_id",
    "evidence_kind",
    "recovered_after_tmp_loss",
    "pilot_manifest_artifact",
    "validation_artifacts",
    "business_decision_review_artifact",
    "permission_probe_artifact",
    "claim_boundary",
}
VALIDATION_REF_ALLOWED_FIELDS = {"modality", "artifact"}


class AssemblyError(ValueError):
    """Raised when supplied artifacts cannot be safely assembled."""


def load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssemblyError("artifact payload must be a JSON object")
    return loaded


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
    elif validator.raw_source_value(payload):
        raise AssemblyError(f"{label} contains raw/internal artifact value")


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
        raise AssemblyError("artifact path must live under inputs/enterprise_multimodal_real")
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
        raise AssemblyError(
            "artifact path escapes the real enterprise multimodal input root"
        ) from exc
    if resolved.is_symlink():
        raise AssemblyError("artifact symlinks are not accepted")
    if not resolved.is_file():
        raise AssemblyError("artifact path does not exist")
    return resolved


def artifact_ref(path_value: str, *, allow_test_artifacts: bool = False) -> tuple[str, str]:
    path = safe_real_artifact_path(path_value, allow_test_artifacts=allow_test_artifacts)
    payload = load_json(path)
    reject_template_or_placeholder_payload(payload, label="artifact")
    reject_raw_internal_payload(payload, label="artifact")
    return str(path.relative_to(ROOT)), validator.sha256_file(path) or ""


def validation_ref(
    entry: dict[str, Any],
    *,
    allow_test_artifacts: bool = False,
) -> dict[str, str]:
    if set(entry) - VALIDATION_REF_ALLOWED_FIELDS:
        raise AssemblyError("validation artifact reference has unsupported fields")
    modality = entry.get("modality")
    if modality not in validator.REQUIRED_MODALITIES:
        raise AssemblyError("validation artifact modality is unsupported")
    artifact_path, artifact_sha = artifact_ref(
        entry.get("artifact", ""),
        allow_test_artifacts=allow_test_artifacts,
    )
    return {
        "modality": modality,
        "artifact": artifact_path,
        "artifact_sha256": artifact_sha,
    }


def validate_claim_boundary(
    claim_boundary: Any,
    *,
    llm_route: bool,
    public_mode: bool,
) -> dict[str, bool]:
    if not isinstance(claim_boundary, dict):
        raise AssemblyError("claim boundary must be supplied by the assembly manifest")
    unsupported_fields = sorted(set(claim_boundary) - validator.CLAIM_BOUNDARY_ALLOWED_FIELDS)
    if unsupported_fields:
        raise AssemblyError("claim boundary has unsupported fields")
    required_fields = validator.CLAIM_BOUNDARY_ALLOWED_FIELDS - ROUTE_CLAIMS
    missing_fields = sorted(required_fields - set(claim_boundary))
    if missing_fields:
        raise AssemblyError("claim boundary is missing required fields")
    for field in POSITIVE_CLAIMS:
        if claim_boundary.get(field) is not True:
            raise AssemblyError("claim boundary must explicitly support required enterprise claims")
    if llm_route:
        if (
            claim_boundary.get("supports_multimodal_llm_subagent_adjudication_completed_claim")
            is not True
        ):
            raise AssemblyError("claim boundary must explicitly support LLM subagent adjudication")
        if (
            claim_boundary.get("supports_multimodal_human_adjudication_completed_claim")
            is not False
        ):
            raise AssemblyError("claim boundary must not claim human adjudication for LLM route")
    else:
        if claim_boundary.get("supports_multimodal_human_adjudication_completed_claim") is not True:
            raise AssemblyError("claim boundary must explicitly support human adjudication")
        if claim_boundary.get(
            "supports_multimodal_llm_subagent_adjudication_completed_claim"
        ) not in {
            None,
            False,
        }:
            raise AssemblyError("claim boundary must not claim LLM adjudication for human route")
    for field in NEGATIVE_CLAIMS:
        if claim_boundary.get(field) is not False:
            raise AssemblyError("claim boundary overclaims unsupported claims")
    if public_mode:
        if claim_boundary.get(public_evidence.CLAIM_FIELD) is not True:
            raise AssemblyError("claim boundary must explicitly support public evidence")
    elif claim_boundary.get(public_evidence.CLAIM_FIELD) is True:
        raise AssemblyError("claim boundary must not claim public evidence on private route")
    return dict(claim_boundary)


def validate_evidence_source_mode(
    evidence_source_mode: str | None,
    public_evidence_manifest_artifact: str | None,
) -> str | None:
    if evidence_source_mode is None and public_evidence_manifest_artifact is None:
        return None
    if evidence_source_mode not in public_evidence.ALLOWED_MODES:
        raise AssemblyError("evidence source mode is unsupported")
    if (
        evidence_source_mode == public_evidence.PUBLIC_MODE
        and not public_evidence_manifest_artifact
    ):
        raise AssemblyError("public evidence mode requires a public evidence manifest")
    if evidence_source_mode == public_evidence.PRIVATE_MODE and public_evidence_manifest_artifact:
        raise AssemblyError("operator-private mode must not include a public evidence manifest")
    return evidence_source_mode


def assemble_packet(
    *,
    artifact_id: str,
    evidence_kind: str,
    recovered_after_tmp_loss: bool,
    pilot_manifest_artifact: str,
    validation_artifacts: list[dict[str, Any]],
    human_adjudication_artifact: str | None = None,
    llm_subagent_adjudication_artifact: str | None = None,
    business_decision_review_artifact: str,
    permission_probe_artifact: str,
    claim_boundary: dict[str, bool] | None = None,
    evidence_source_mode: str | None = None,
    public_evidence_manifest_artifact: str | None = None,
    allow_test_artifacts: bool = False,
) -> dict[str, Any]:
    if artifact_id != "enterprise_multimodal_validation_packet_v1":
        raise AssemblyError("artifact id mismatch")
    if evidence_kind != "real_enterprise_multimodal_validation":
        raise AssemblyError("evidence kind mismatch")
    if recovered_after_tmp_loss is not False:
        raise AssemblyError("packet cannot rely on lost /tmp artifacts")
    llm_route = llm_subagent_adjudication_artifact is not None
    evidence_mode = validate_evidence_source_mode(
        evidence_source_mode,
        public_evidence_manifest_artifact,
    )
    if llm_route == (human_adjudication_artifact is not None):
        raise AssemblyError("enterprise multimodal packet must use exactly one adjudication route")
    if not isinstance(validation_artifacts, list):
        raise AssemblyError("validation artifacts must be a list")
    validation_refs = [
        validation_ref(entry, allow_test_artifacts=allow_test_artifacts)
        for entry in validation_artifacts
    ]
    modalities = [entry["modality"] for entry in validation_refs]
    if sorted(modalities) != sorted(validator.REQUIRED_MODALITIES):
        raise AssemblyError("validation artifacts must cover each required modality exactly once")

    pilot_path, pilot_sha = artifact_ref(
        pilot_manifest_artifact,
        allow_test_artifacts=allow_test_artifacts,
    )
    business_path, business_sha = artifact_ref(
        business_decision_review_artifact,
        allow_test_artifacts=allow_test_artifacts,
    )
    permission_path, permission_sha = artifact_ref(
        permission_probe_artifact,
        allow_test_artifacts=allow_test_artifacts,
    )

    packet = {
        "artifact_id": artifact_id,
        "evidence_kind": evidence_kind,
        "recovered_after_tmp_loss": recovered_after_tmp_loss,
        "pilot_manifest_artifact": pilot_path,
        "pilot_manifest_artifact_sha256": pilot_sha,
        "validation_artifacts": validation_refs,
        "business_decision_review_artifact": business_path,
        "business_decision_review_artifact_sha256": business_sha,
        "permission_probe_artifact": permission_path,
        "permission_probe_artifact_sha256": permission_sha,
        "claim_boundary": validate_claim_boundary(
            claim_boundary,
            llm_route=llm_route,
            public_mode=evidence_mode == public_evidence.PUBLIC_MODE,
        ),
    }
    if evidence_mode is not None:
        packet["evidence_source_mode"] = evidence_mode
    if evidence_mode == public_evidence.PUBLIC_MODE:
        assert public_evidence_manifest_artifact is not None
        public_path, public_sha = artifact_ref(
            public_evidence_manifest_artifact,
            allow_test_artifacts=allow_test_artifacts,
        )
        packet["public_evidence_manifest_artifact"] = public_path
        packet["public_evidence_manifest_artifact_sha256"] = public_sha
    if llm_route:
        assert llm_subagent_adjudication_artifact is not None
        panel_path, panel_sha = artifact_ref(
            llm_subagent_adjudication_artifact,
            allow_test_artifacts=allow_test_artifacts,
        )
        packet["llm_subagent_adjudication_artifact"] = panel_path
        packet["llm_subagent_adjudication_artifact_sha256"] = panel_sha
    else:
        assert human_adjudication_artifact is not None
        adjudication_path, adjudication_sha = artifact_ref(
            human_adjudication_artifact,
            allow_test_artifacts=allow_test_artifacts,
        )
        packet["human_adjudication_artifact"] = adjudication_path
        packet["human_adjudication_artifact_sha256"] = adjudication_sha
    return packet


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
    if output_path.exists() or output_path.is_symlink():
        raise AssemblyError("canonical packet output already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.tmp")
    if temp_path.exists() or temp_path.is_symlink():
        raise AssemblyError("canonical packet temporary output already exists")
    try:
        with temp_path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(packet, indent=2, sort_keys=True) + "\n")
        try:
            os.link(temp_path, output_path)
        except FileExistsError as exc:
            raise AssemblyError("canonical packet output already exists") from exc
    except Exception:
        if temp_path.exists() or temp_path.is_symlink():
            temp_path.unlink()
        raise
    else:
        temp_path.unlink()


def load_manifest(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    raw = path.read_bytes()
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise AssemblyError("assembly manifest sha256 mismatch")
    loaded = json.loads(raw.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise AssemblyError("assembly manifest must be a JSON object")
    reject_template_or_placeholder_payload(loaded, label="assembly manifest")
    unsupported_fields = sorted(set(loaded) - MANIFEST_ALLOWED_FIELDS)
    if unsupported_fields:
        raise AssemblyError("assembly manifest has unsupported fields")
    missing_fields = sorted(MANIFEST_COMMON_REQUIRED_FIELDS - set(loaded))
    if missing_fields:
        raise AssemblyError("assembly manifest is missing required fields")
    if ("human_adjudication_artifact" in loaded) == (
        "llm_subagent_adjudication_artifact" in loaded
    ):
        raise AssemblyError("assembly manifest must supply exactly one adjudication route")
    return loaded


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assembly-manifest", required=True, help="JSON manifest listing real artifact paths"
    )
    parser.add_argument(
        "--assembly-manifest-sha256",
        help="expected sha256 of the assembly manifest bytes approved for promotion",
    )
    parser.add_argument(
        "--validate", action="store_true", help="validate the assembled packet in memory"
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="write inputs/enterprise_multimodal_validation_packet.json only if validation passes",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    assembly_manifest = load_manifest(
        Path(args.assembly_manifest),
        expected_sha256=args.assembly_manifest_sha256,
    )
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
