#!/usr/bin/env python3
"""Fail-closed atomic promotion foundation for methodology authority manifests."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_core.methodology_authority import (  # noqa: E402
    AUTHORITY_RELATIVE_PATH,
    MethodologyAuthorityResult,
    check_methodology_authority,
    methodology_gate_dependency_manifest_path,
    validate_methodology_gate_dependency_manifest,
)

_EXECUTABLE_GATE_IDS = frozenset(
    {
        "source_completeness_compared_with_raw_oracle",
        "evaluation_reports_bind_execution_fingerprint",
        "same_pipeline_real_source_ablation",
        "real_user_end_answer_acceptance",
    }
)
_CLAIM_ARTIFACT_ID = "formowl_methodology_authority_promotion_claim_v1"
_RECEIPT_ARTIFACT_ID = "formowl_methodology_authority_promotion_receipt_v1"
_REPORT_ARTIFACT_ID = "formowl_methodology_authority_promotion_report_v1"
_SCHEMA_VERSION = 1
_GATE_EVIDENCE_ARTIFACT_ID = "formowl_methodology_gate_evidence_v3"
_GATE_EVIDENCE_SCHEMA_VERSION = 1
_GATE_EVIDENCE_KEYS = {
    "artifact_id",
    "schema_version",
    "authority_id",
    "gate_id",
    "execution_fingerprint",
    "validator_id",
    "source_manifest_path",
    "source_manifest_sha256",
    "result_artifact_path",
    "result_artifact_sha256",
    "dependency_manifest_path",
    "dependency_manifest_sha256",
    "dependency_manifest_fingerprint",
    "dependency_count",
    "execution_binding",
    "status",
    "evidence_classification",
    "promotion_status",
    "envelope_fingerprint",
}
_GATE_DEPENDENCY_MANIFEST_KEYS = {
    "artifact_id",
    "gate_id",
    "execution_fingerprint",
    "source_manifest_path",
    "source_manifest_sha256",
    "result_artifact_path",
    "result_artifact_sha256",
    "dependencies",
    "manifest_fingerprint",
}
_GATE_DEPENDENCY_MANIFEST_ARTIFACT_ID = "formowl_methodology_gate_dependency_manifest_v1"
_GATE_VALIDATOR_IDS = {
    "source_completeness_compared_with_raw_oracle": "raw_source_completeness_validator_v1",
    "evaluation_reports_bind_execution_fingerprint": "execution_report_binding_validator_v1",
    "same_pipeline_real_source_ablation": "same_pipeline_real_source_ablation_validator_v1",
    "real_user_end_answer_acceptance": "real_user_end_answer_acceptance_validator_v1",
}


class MethodologyAuthorityPromotionError(RuntimeError):
    """Fail-closed promotion error with one stable public reason code."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class _GateBinding:
    gate_id: str
    evidence_relative_path: Path
    evidence_byte_sha256: str
    dependency_manifest_relative_path: Path
    dependency_manifest_byte_sha256: str
    source_manifest_byte_sha256: str
    result_artifact_byte_sha256: str

    def to_safe_dict(self) -> dict[str, str]:
        return {
            "gate_id": self.gate_id,
            "evidence_byte_sha256": self.evidence_byte_sha256,
            "dependency_manifest_byte_sha256": (self.dependency_manifest_byte_sha256),
            "source_manifest_byte_sha256": self.source_manifest_byte_sha256,
            "result_artifact_byte_sha256": self.result_artifact_byte_sha256,
        }


@dataclass(frozen=True)
class _PromotionPreflight:
    repository_root: Path
    authority_relative_path: Path
    authority_path: Path
    current_authority_bytes: bytes
    current_authority_sha256: str
    current_authority_mode: int
    candidate_authority_path: Path
    candidate_authority_bytes: bytes
    candidate_authority_sha256: str
    candidate_result: MethodologyAuthorityResult
    gate_bindings: tuple[_GateBinding, ...]
    evidence_binding_fingerprint: str
    claim_path: Path
    receipt_path: Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        gate_evidence = _parse_gate_path_arguments(args.gate_evidence, "gate evidence")
        gate_dependencies = _parse_gate_path_arguments(
            args.gate_dependency_manifest,
            "gate dependency manifest",
        )
        preflight = preflight_methodology_authority_promotion(
            repository_root=args.repository_root,
            authority_relative_path=args.authority,
            expected_current_authority_sha256=(args.expected_current_authority_sha256),
            candidate_authority_relative_path=args.candidate_authority,
            gate_evidence_relative_paths=gate_evidence,
            gate_dependency_manifest_relative_paths=gate_dependencies,
            claim_relative_path=args.claim_path,
            receipt_relative_path=args.receipt_path,
        )
        if args.preflight_only:
            report = _preflight_report(preflight)
        else:
            report = promote_methodology_authority(preflight)
    except MethodologyAuthorityPromotionError as exc:
        print(
            json.dumps(
                {
                    "artifact_id": _REPORT_ARTIFACT_ID,
                    "schema_version": _SCHEMA_VERSION,
                    "status": "blocked",
                    "reason_code": exc.reason_code,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def preflight_methodology_authority_promotion(
    *,
    repository_root: Path,
    authority_relative_path: Path,
    expected_current_authority_sha256: str,
    candidate_authority_relative_path: Path,
    gate_evidence_relative_paths: Mapping[str, Path],
    gate_dependency_manifest_relative_paths: Mapping[str, Path],
    claim_relative_path: Path,
    receipt_relative_path: Path,
) -> _PromotionPreflight:
    """Validate all immutable inputs without claiming or writing authority state."""

    _require_sha256(
        expected_current_authority_sha256,
        "expected_current_authority_sha256_invalid",
    )
    root = _resolved_repository_root(repository_root)
    authority_path = _resolve_existing_regular_file(
        root,
        authority_relative_path,
        "current_authority_unavailable",
    )
    candidate_path = _resolve_existing_regular_file(
        root,
        candidate_authority_relative_path,
        "candidate_authority_unavailable",
    )
    if authority_path == candidate_path:
        raise MethodologyAuthorityPromotionError(
            "candidate_authority_must_not_be_current_authority"
        )
    claim_path = _resolve_output_path(root, claim_relative_path, "claim_path_invalid")
    receipt_path = _resolve_output_path(
        root,
        receipt_relative_path,
        "receipt_path_invalid",
    )
    protected_paths = {
        authority_path,
        candidate_path,
        claim_path,
        receipt_path,
    }
    if len(protected_paths) != 4:
        raise MethodologyAuthorityPromotionError("promotion_paths_must_be_distinct")
    if claim_path.exists():
        raise MethodologyAuthorityPromotionError("promotion_claim_already_exists")
    if receipt_path.exists():
        raise MethodologyAuthorityPromotionError("promotion_receipt_already_exists")

    current_bytes = _read_bytes(authority_path, "current_authority_unreadable")
    current_sha256 = _sha256_bytes(current_bytes)
    if current_sha256 != expected_current_authority_sha256:
        raise MethodologyAuthorityPromotionError("current_authority_byte_seal_mismatch")
    candidate_bytes = _read_bytes(candidate_path, "candidate_authority_unreadable")
    candidate_sha256 = _sha256_bytes(candidate_bytes)
    if candidate_sha256 == current_sha256:
        raise MethodologyAuthorityPromotionError("candidate_authority_is_not_a_change")

    current_result = check_methodology_authority(
        repository_root=root,
        authority_path=authority_path,
    )
    if not current_result.authority_valid:
        raise MethodologyAuthorityPromotionError("current_authority_invalid")
    if current_result.methodology_ready:
        raise MethodologyAuthorityPromotionError("current_authority_already_ready")

    candidate_payload = _read_json_object(
        candidate_path,
        "candidate_authority_invalid_json",
    )
    candidate_result = check_methodology_authority(
        repository_root=root,
        authority_path=candidate_path,
    )
    if not candidate_result.authority_valid:
        raise MethodologyAuthorityPromotionError("candidate_authority_invalid")
    if not candidate_result.methodology_ready:
        raise MethodologyAuthorityPromotionError("candidate_authority_not_ready")
    if (
        candidate_result.execution_fingerprint is None
        or candidate_result.authority_state_fingerprint is None
        or candidate_result.authority_id != current_result.authority_id
    ):
        raise MethodologyAuthorityPromotionError("candidate_authority_runtime_binding_mismatch")
    if set(gate_evidence_relative_paths) != _EXECUTABLE_GATE_IDS:
        raise MethodologyAuthorityPromotionError("gate_evidence_set_mismatch")
    if set(gate_dependency_manifest_relative_paths) != _EXECUTABLE_GATE_IDS:
        raise MethodologyAuthorityPromotionError("gate_dependency_manifest_set_mismatch")

    candidate_gate_evidence = _candidate_gate_evidence_paths(candidate_payload)
    bindings: list[_GateBinding] = []
    for gate_id in sorted(_EXECUTABLE_GATE_IDS):
        evidence_relative = gate_evidence_relative_paths[gate_id]
        dependency_relative = gate_dependency_manifest_relative_paths[gate_id]
        if candidate_gate_evidence.get(gate_id) != evidence_relative:
            raise MethodologyAuthorityPromotionError("candidate_gate_evidence_input_mismatch")
        evidence_path = _resolve_existing_regular_file(
            root,
            evidence_relative,
            "gate_evidence_unavailable",
        )
        dependency_path = _resolve_existing_regular_file(
            root,
            dependency_relative,
            "gate_dependency_manifest_unavailable",
        )
        evidence = _read_json_object(evidence_path, "gate_evidence_invalid_json")
        binding = _validate_gate_binding(
            repository_root=root,
            authority_id=candidate_result.authority_id,
            gate_id=gate_id,
            evidence_relative_path=evidence_relative,
            evidence_path=evidence_path,
            evidence=evidence,
            dependency_manifest_relative_path=dependency_relative,
            dependency_manifest_path=dependency_path,
            execution_fingerprint=candidate_result.execution_fingerprint,
        )
        bindings.append(binding)

    evidence_binding_payload = [binding.to_safe_dict() for binding in bindings]
    evidence_binding_fingerprint = _sha256_json(evidence_binding_payload)
    current_mode = stat.S_IMODE(authority_path.stat().st_mode)
    return _PromotionPreflight(
        repository_root=root,
        authority_relative_path=authority_relative_path,
        authority_path=authority_path,
        current_authority_bytes=current_bytes,
        current_authority_sha256=current_sha256,
        current_authority_mode=current_mode,
        candidate_authority_path=candidate_path,
        candidate_authority_bytes=candidate_bytes,
        candidate_authority_sha256=candidate_sha256,
        candidate_result=candidate_result,
        gate_bindings=tuple(bindings),
        evidence_binding_fingerprint=evidence_binding_fingerprint,
        claim_path=claim_path,
        receipt_path=receipt_path,
    )


def promote_methodology_authority(
    preflight: _PromotionPreflight,
) -> dict[str, Any]:
    """Consume one claim and atomically replace the authority exactly once."""

    _fault_checkpoint("before_claim")
    claim_payload = _claim_payload(preflight)
    claim_bytes = _canonical_json_bytes(claim_payload)
    _write_exclusive_file(preflight.claim_path, claim_bytes, 0o600)
    claim_byte_sha256 = _sha256_bytes(claim_bytes)
    _fault_checkpoint("after_claim")

    stage_path = preflight.authority_path.with_name(
        f".{preflight.authority_path.name}." f"{preflight.candidate_authority_sha256[7:23]}.staged"
    )
    if stage_path.exists():
        raise MethodologyAuthorityPromotionError("authority_stage_already_exists")
    replaced = False
    try:
        _write_exclusive_file(
            stage_path,
            preflight.candidate_authority_bytes,
            preflight.current_authority_mode,
        )
        _fault_checkpoint("after_stage_fsync")
        _fault_checkpoint("before_stale_current_recheck")
        _recheck_current_authority(preflight)
        _fault_checkpoint("before_authority_replace")
        os.replace(stage_path, preflight.authority_path)
        replaced = True
        _fsync_directory(preflight.authority_path.parent)
        _fault_checkpoint("after_authority_replace")
        if (
            _sha256_bytes(
                _read_bytes(
                    preflight.authority_path,
                    "promoted_authority_unreadable",
                )
            )
            != preflight.candidate_authority_sha256
        ):
            raise MethodologyAuthorityPromotionError("promoted_authority_byte_seal_mismatch")
        post_result = check_methodology_authority(
            repository_root=preflight.repository_root,
            authority_path=preflight.authority_path,
        )
        if not post_result.authority_valid or not post_result.methodology_ready:
            raise MethodologyAuthorityPromotionError("post_promotion_require_ready_failed")
        if (
            post_result.execution_fingerprint != preflight.candidate_result.execution_fingerprint
            or post_result.authority_state_fingerprint
            != preflight.candidate_result.authority_state_fingerprint
        ):
            raise MethodologyAuthorityPromotionError("post_promotion_authority_binding_mismatch")
        _fault_checkpoint("after_post_ready_check")
        receipt_payload = _receipt_payload(
            preflight,
            claim_byte_sha256=claim_byte_sha256,
            post_result=post_result,
        )
        receipt_bytes = _canonical_json_bytes(receipt_payload)
        _publish_immutable_file(
            preflight.receipt_path,
            receipt_bytes,
            mode=0o600,
        )
        receipt_byte_sha256 = _sha256_bytes(receipt_bytes)
        _fault_checkpoint("after_receipt_publish")
    except BaseException:
        if not replaced and stage_path.exists():
            stage_path.unlink()
            _fsync_directory(stage_path.parent)
        raise
    return _promotion_report(
        preflight,
        claim_byte_sha256=claim_byte_sha256,
        receipt_byte_sha256=receipt_byte_sha256,
        receipt_fingerprint=receipt_payload["receipt_fingerprint"],
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--promote", action="store_true")
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--authority", type=Path, default=AUTHORITY_RELATIVE_PATH)
    parser.add_argument(
        "--expected-current-authority-sha256",
        required=True,
    )
    parser.add_argument("--candidate-authority", type=Path, required=True)
    parser.add_argument(
        "--gate-evidence",
        action="append",
        default=[],
        metavar="GATE_ID=REPO_RELATIVE_PATH",
    )
    parser.add_argument(
        "--gate-dependency-manifest",
        action="append",
        default=[],
        metavar="GATE_ID=REPO_RELATIVE_PATH",
    )
    parser.add_argument(
        "--claim-path",
        type=Path,
        default=Path("docs/methodology-authority.promotion.claim.json"),
    )
    parser.add_argument(
        "--receipt-path",
        type=Path,
        default=Path("docs/methodology-authority.promotion.receipt.json"),
    )
    return parser


def _parse_gate_path_arguments(
    values: Sequence[str],
    label: str,
) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        gate_id, separator, raw_path = value.partition("=")
        if (
            separator != "="
            or gate_id not in _EXECUTABLE_GATE_IDS
            or not raw_path
            or gate_id in parsed
        ):
            raise MethodologyAuthorityPromotionError(f"{label.replace(' ', '_')}_argument_invalid")
        parsed[gate_id] = _require_relative_path(
            Path(raw_path),
            f"{label.replace(' ', '_')}_path_invalid",
        )
    return parsed


def _candidate_gate_evidence_paths(
    candidate_payload: Mapping[str, Any],
) -> dict[str, Path]:
    raw_gates = candidate_payload.get("required_gates")
    if not isinstance(raw_gates, list):
        raise MethodologyAuthorityPromotionError("candidate_gate_set_invalid")
    paths: dict[str, Path] = {}
    for gate in raw_gates:
        if not isinstance(gate, Mapping):
            raise MethodologyAuthorityPromotionError("candidate_gate_set_invalid")
        gate_id = gate.get("gate_id")
        if gate_id not in _EXECUTABLE_GATE_IDS:
            continue
        evidence = gate.get("evidence")
        if not isinstance(evidence, list) or len(evidence) != 1:
            raise MethodologyAuthorityPromotionError("candidate_gate_evidence_must_be_single")
        paths[str(gate_id)] = _require_relative_path(
            Path(str(evidence[0])),
            "candidate_gate_evidence_path_invalid",
        )
    if set(paths) != _EXECUTABLE_GATE_IDS:
        raise MethodologyAuthorityPromotionError("candidate_gate_set_invalid")
    return paths


def _validate_gate_binding(
    *,
    repository_root: Path,
    authority_id: str,
    gate_id: str,
    evidence_relative_path: Path,
    evidence_path: Path,
    evidence: Mapping[str, Any],
    dependency_manifest_relative_path: Path,
    dependency_manifest_path: Path,
    execution_fingerprint: str,
) -> _GateBinding:
    if (
        set(evidence) != _GATE_EVIDENCE_KEYS
        or evidence.get("artifact_id") != _GATE_EVIDENCE_ARTIFACT_ID
        or evidence.get("schema_version") != _GATE_EVIDENCE_SCHEMA_VERSION
        or evidence.get("authority_id") != authority_id
        or evidence.get("gate_id") != gate_id
        or evidence.get("execution_fingerprint") != execution_fingerprint
        or evidence.get("validator_id") != _GATE_VALIDATOR_IDS[gate_id]
        or evidence.get("status") != "passed"
        or evidence.get("evidence_classification") != "production"
        or evidence.get("promotion_status") != "not_performed"
        or not _has_internal_fingerprint(evidence, "envelope_fingerprint")
    ):
        raise MethodologyAuthorityPromotionError("gate_evidence_binding_invalid")
    source_relative = _require_relative_path(
        Path(str(evidence.get("source_manifest_path", ""))),
        "gate_source_manifest_path_invalid",
    )
    result_relative = _require_relative_path(
        Path(str(evidence.get("result_artifact_path", ""))),
        "gate_result_artifact_path_invalid",
    )
    dependency_relative = _require_relative_path(
        Path(str(evidence.get("dependency_manifest_path", ""))),
        "gate_dependency_manifest_path_invalid",
    )
    expected_dependency_relative = methodology_gate_dependency_manifest_path(result_relative)
    if (
        dependency_relative != expected_dependency_relative
        or dependency_manifest_relative_path != expected_dependency_relative
    ):
        raise MethodologyAuthorityPromotionError("gate_dependency_manifest_path_mismatch")
    if dependency_manifest_path != repository_root / expected_dependency_relative:
        raise MethodologyAuthorityPromotionError("gate_dependency_manifest_path_mismatch")
    source_path = _resolve_existing_regular_file(
        repository_root,
        source_relative,
        "gate_source_manifest_unavailable",
    )
    result_path = _resolve_existing_regular_file(
        repository_root,
        result_relative,
        "gate_result_artifact_unavailable",
    )
    source_bytes = _read_bytes(source_path, "gate_source_manifest_unreadable")
    result_bytes = _read_bytes(result_path, "gate_result_artifact_unreadable")
    dependency_manifest_bytes = _read_bytes(
        dependency_manifest_path,
        "gate_dependency_manifest_unreadable",
    )
    if evidence.get("source_manifest_sha256") != _sha256_bytes(source_bytes):
        raise MethodologyAuthorityPromotionError("gate_source_manifest_byte_seal_mismatch")
    if evidence.get("result_artifact_sha256") != _sha256_bytes(result_bytes):
        raise MethodologyAuthorityPromotionError("gate_result_artifact_byte_seal_mismatch")
    if evidence.get("dependency_manifest_sha256") != _sha256_bytes(dependency_manifest_bytes):
        raise MethodologyAuthorityPromotionError("gate_dependency_manifest_byte_seal_mismatch")
    source_manifest = _json_object_from_bytes(
        source_bytes,
        "gate_source_manifest_invalid_json",
    )
    result_artifact = _json_object_from_bytes(
        result_bytes,
        "gate_result_artifact_invalid_json",
    )
    dependency_manifest = _json_object_from_bytes(
        dependency_manifest_bytes,
        "gate_dependency_manifest_invalid_json",
    )
    dependencies = dependency_manifest.get("dependencies")
    if (
        set(dependency_manifest) != _GATE_DEPENDENCY_MANIFEST_KEYS
        or dependency_manifest.get("artifact_id") != _GATE_DEPENDENCY_MANIFEST_ARTIFACT_ID
        or dependency_manifest.get("gate_id") != gate_id
        or dependency_manifest.get("execution_fingerprint") != execution_fingerprint
        or dependency_manifest.get("source_manifest_path") != source_relative.as_posix()
        or dependency_manifest.get("source_manifest_sha256")
        != evidence.get("source_manifest_sha256")
        or dependency_manifest.get("result_artifact_path") != result_relative.as_posix()
        or dependency_manifest.get("result_artifact_sha256")
        != evidence.get("result_artifact_sha256")
        or not _has_internal_fingerprint(
            dependency_manifest,
            "manifest_fingerprint",
        )
        or evidence.get("dependency_manifest_fingerprint")
        != dependency_manifest.get("manifest_fingerprint")
        or type(evidence.get("dependency_count")) is not int
        or evidence["dependency_count"] <= 0
        or not isinstance(dependencies, list)
        or evidence["dependency_count"] != len(dependencies)
    ):
        raise MethodologyAuthorityPromotionError("gate_dependency_manifest_binding_invalid")
    if not validate_methodology_gate_dependency_manifest(
        repository_root=repository_root,
        gate_id=gate_id,
        source_manifest_path=source_path,
        result_artifact_path=result_path,
        source_manifest=source_manifest,
        result_artifact=result_artifact,
        execution_fingerprint=execution_fingerprint,
    ):
        raise MethodologyAuthorityPromotionError("gate_production_dependency_validation_failed")
    _validate_execution_binding_reference(
        repository_root=repository_root,
        reference=evidence.get("execution_binding"),
        dependencies=dependencies,
    )
    return _GateBinding(
        gate_id=gate_id,
        evidence_relative_path=evidence_relative_path,
        evidence_byte_sha256=_sha256_bytes(_read_bytes(evidence_path, "gate_evidence_unreadable")),
        dependency_manifest_relative_path=dependency_manifest_relative_path,
        dependency_manifest_byte_sha256=_sha256_bytes(
            _read_bytes(
                dependency_manifest_path,
                "gate_dependency_manifest_unreadable",
            )
        ),
        source_manifest_byte_sha256=_sha256_bytes(source_bytes),
        result_artifact_byte_sha256=_sha256_bytes(result_bytes),
    )


def _validate_execution_binding_reference(
    *,
    repository_root: Path,
    reference: Any,
    dependencies: Sequence[Any],
) -> None:
    binding_entries = [
        entry
        for entry in dependencies
        if isinstance(entry, Mapping)
        and entry.get("role") == "execution_binding_bundle"
    ]
    if len(binding_entries) != 1:
        raise MethodologyAuthorityPromotionError("gate_execution_binding_bundle_mismatch")
    binding_entry = binding_entries[0]
    bundle_path = _resolve_existing_regular_file(
        repository_root,
        Path(str(binding_entry.get("path", ""))),
        "gate_execution_binding_bundle_unavailable",
    )
    bundle = _read_json_object(bundle_path, "gate_execution_binding_bundle_unreadable")
    expected_reference = {
        "role": "execution_binding_bundle",
        "path": binding_entry.get("path"),
        "byte_sha256": binding_entry.get("byte_sha256"),
        "bundle_fingerprint": binding_entry.get("internal_fingerprint"),
        "complete_execution_fingerprint": bundle.get("execution_fingerprint"),
    }
    if reference != expected_reference:
        raise MethodologyAuthorityPromotionError("gate_execution_binding_bundle_mismatch")


def _claim_payload(preflight: _PromotionPreflight) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_id": _CLAIM_ARTIFACT_ID,
        "schema_version": _SCHEMA_VERSION,
        "status": "consumed",
        "authority_id": preflight.candidate_result.authority_id,
        "expected_current_authority_sha256": (preflight.current_authority_sha256),
        "candidate_authority_sha256": preflight.candidate_authority_sha256,
        "execution_fingerprint": (preflight.candidate_result.execution_fingerprint),
        "candidate_authority_state_fingerprint": (
            preflight.candidate_result.authority_state_fingerprint
        ),
        "evidence_binding_fingerprint": (preflight.evidence_binding_fingerprint),
    }
    payload["claim_fingerprint"] = _sha256_json(payload)
    return payload


def _receipt_payload(
    preflight: _PromotionPreflight,
    *,
    claim_byte_sha256: str,
    post_result: MethodologyAuthorityResult,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_id": _RECEIPT_ARTIFACT_ID,
        "schema_version": _SCHEMA_VERSION,
        "status": "passed",
        "authority_id": post_result.authority_id,
        "previous_authority_sha256": preflight.current_authority_sha256,
        "promoted_authority_sha256": preflight.candidate_authority_sha256,
        "claim_byte_sha256": claim_byte_sha256,
        "execution_fingerprint": post_result.execution_fingerprint,
        "authority_state_fingerprint": post_result.authority_state_fingerprint,
        "evidence_binding_fingerprint": (preflight.evidence_binding_fingerprint),
        "gate_bindings": [binding.to_safe_dict() for binding in preflight.gate_bindings],
    }
    payload["receipt_fingerprint"] = _sha256_json(payload)
    return payload


def _preflight_report(preflight: _PromotionPreflight) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_id": _REPORT_ARTIFACT_ID,
        "schema_version": _SCHEMA_VERSION,
        "status": "preflight_passed_no_write",
        "current_authority_sha256": preflight.current_authority_sha256,
        "candidate_authority_sha256": preflight.candidate_authority_sha256,
        "execution_fingerprint": (preflight.candidate_result.execution_fingerprint),
        "candidate_authority_state_fingerprint": (
            preflight.candidate_result.authority_state_fingerprint
        ),
        "evidence_binding_fingerprint": (preflight.evidence_binding_fingerprint),
        "validated_gate_count": len(preflight.gate_bindings),
    }
    payload["report_fingerprint"] = _sha256_json(payload)
    return payload


def _promotion_report(
    preflight: _PromotionPreflight,
    *,
    claim_byte_sha256: str,
    receipt_byte_sha256: str,
    receipt_fingerprint: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_id": _REPORT_ARTIFACT_ID,
        "schema_version": _SCHEMA_VERSION,
        "status": "promoted",
        "previous_authority_sha256": preflight.current_authority_sha256,
        "promoted_authority_sha256": preflight.candidate_authority_sha256,
        "claim_byte_sha256": claim_byte_sha256,
        "receipt_byte_sha256": receipt_byte_sha256,
        "receipt_fingerprint": receipt_fingerprint,
        "execution_fingerprint": (preflight.candidate_result.execution_fingerprint),
        "authority_state_fingerprint": (preflight.candidate_result.authority_state_fingerprint),
        "evidence_binding_fingerprint": (preflight.evidence_binding_fingerprint),
    }
    payload["report_fingerprint"] = _sha256_json(payload)
    return payload


def _recheck_current_authority(preflight: _PromotionPreflight) -> None:
    current_path = _resolve_existing_regular_file(
        preflight.repository_root,
        preflight.authority_relative_path,
        "stale_current_authority_unavailable",
    )
    current_bytes = _read_bytes(current_path, "stale_current_authority_unreadable")
    if (
        current_bytes != preflight.current_authority_bytes
        or _sha256_bytes(current_bytes) != preflight.current_authority_sha256
    ):
        raise MethodologyAuthorityPromotionError("stale_current_authority_recheck_failed")


def _write_exclusive_file(path: Path, content: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError as exc:
        reason = (
            "promotion_claim_already_exists"
            if path.name.endswith("claim.json")
            else "exclusive_output_already_exists"
        )
        raise MethodologyAuthorityPromotionError(reason) from exc
    try:
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != mode:
            os.fchmod(descriptor, mode)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("exclusive file write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _publish_immutable_file(path: Path, content: bytes, *, mode: int) -> None:
    temp_path = path.with_name(f".{path.name}.{_sha256_bytes(content)[7:23]}.staged")
    if temp_path.exists():
        raise MethodologyAuthorityPromotionError("receipt_stage_already_exists")
    _write_exclusive_file(temp_path, content, mode)
    try:
        try:
            os.link(temp_path, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise MethodologyAuthorityPromotionError("promotion_receipt_already_exists") from exc
        _fsync_directory(path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()
            _fsync_directory(path.parent)


def _resolved_repository_root(value: Path) -> Path:
    try:
        resolved = value.resolve(strict=True)
    except OSError as exc:
        raise MethodologyAuthorityPromotionError("repository_root_unavailable") from exc
    if not resolved.is_dir():
        raise MethodologyAuthorityPromotionError("repository_root_invalid")
    return resolved


def _resolve_existing_regular_file(
    repository_root: Path,
    relative_path: Path,
    reason_code: str,
) -> Path:
    relative = _require_relative_path(relative_path, reason_code)
    candidate = repository_root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise MethodologyAuthorityPromotionError(reason_code)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repository_root)
    except (OSError, ValueError) as exc:
        raise MethodologyAuthorityPromotionError(reason_code) from exc
    if not resolved.is_file():
        raise MethodologyAuthorityPromotionError(reason_code)
    return resolved


def _resolve_output_path(
    repository_root: Path,
    relative_path: Path,
    reason_code: str,
) -> Path:
    relative = _require_relative_path(relative_path, reason_code)
    parent = repository_root
    for part in relative.parts[:-1]:
        parent /= part
        if parent.is_symlink():
            raise MethodologyAuthorityPromotionError(reason_code)
    try:
        resolved_parent = parent.resolve(strict=True)
        resolved_parent.relative_to(repository_root)
    except (OSError, ValueError) as exc:
        raise MethodologyAuthorityPromotionError(reason_code) from exc
    if not resolved_parent.is_dir():
        raise MethodologyAuthorityPromotionError(reason_code)
    target = resolved_parent / relative.name
    if target.is_symlink():
        raise MethodologyAuthorityPromotionError(reason_code)
    return target


def _require_relative_path(path: Path, reason_code: str) -> Path:
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise MethodologyAuthorityPromotionError(reason_code)
    if any(part in {"", "."} for part in path.parts):
        raise MethodologyAuthorityPromotionError(reason_code)
    return path


def _read_bytes(path: Path, reason_code: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise MethodologyAuthorityPromotionError(reason_code) from exc


def _read_json_object(path: Path, reason_code: str) -> dict[str, Any]:
    return _json_object_from_bytes(_read_bytes(path, reason_code), reason_code)


def _json_object_from_bytes(content: bytes, reason_code: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MethodologyAuthorityPromotionError(reason_code) from exc
    if not isinstance(payload, dict):
        raise MethodologyAuthorityPromotionError(reason_code)
    return payload


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _sha256_json(payload: Any) -> str:
    return _sha256_bytes(_canonical_json_bytes(payload))


def _has_internal_fingerprint(
    payload: Mapping[str, Any],
    field_name: str,
) -> bool:
    fingerprint = payload.get(field_name)
    if not isinstance(fingerprint, str):
        return False
    unsigned = dict(payload)
    unsigned.pop(field_name, None)
    return fingerprint == _sha256_json(unsigned)


def _require_sha256(value: str, reason_code: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise MethodologyAuthorityPromotionError(reason_code)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fault_checkpoint(_name: str) -> None:
    """Test-only patch seam; the CLI exposes no crash or bypass option."""


if __name__ == "__main__":
    raise SystemExit(main())
