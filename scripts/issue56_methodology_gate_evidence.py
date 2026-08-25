#!/usr/bin/env python3
"""Author immutable Issue #56 methodology-gate evidence envelopes.

This command does not promote methodology authority and does not execute UAT.
It consumes already sealed, production-classified dependencies, derives the
four gate results, builds the dependency manifests required by the production
validator, and writes one atomic, no-overwrite output directory.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
for import_root in (ROOT, PYTHON_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_core.methodology_authority import (  # noqa: E402
    methodology_gate_dependency_manifest_path,
    validate_methodology_gate_dependency_manifest,
)
from scripts.issue56_execution_fingerprint import (  # noqa: E402
    load_and_validate_bundle,
)


INPUT_ARTIFACT_ID = "formowl_methodology_gate_evidence_authoring_input_v1"
ENVELOPE_ARTIFACT_ID = "formowl_methodology_gate_evidence_v3"
DEPENDENCY_MANIFEST_ARTIFACT_ID = "formowl_methodology_gate_dependency_manifest_v1"
REPORT_ARTIFACT_ID = "formowl_methodology_gate_evidence_authoring_report_v1"
REJECTION_ARTIFACT_ID = "formowl_methodology_gate_evidence_authoring_rejection_v1"
BUNDLE_ARTIFACT_ID = "formowl_methodology_gate_evidence_authoring_bundle_v1"
SCHEMA_VERSION = 1

GATE_IDS = (
    "evaluation_reports_bind_execution_fingerprint",
    "real_user_end_answer_acceptance",
    "same_pipeline_real_source_ablation",
    "source_completeness_compared_with_raw_oracle",
)
VALIDATOR_IDS = {
    "source_completeness_compared_with_raw_oracle": "raw_source_completeness_validator_v1",
    "evaluation_reports_bind_execution_fingerprint": "execution_report_binding_validator_v1",
    "same_pipeline_real_source_ablation": "same_pipeline_real_source_ablation_validator_v1",
    "real_user_end_answer_acceptance": "real_user_end_answer_acceptance_validator_v1",
}
RESULT_ARTIFACT_IDS = {
    "source_completeness_compared_with_raw_oracle": ("formowl_raw_source_completeness_result_v1"),
    "evaluation_reports_bind_execution_fingerprint": ("formowl_execution_report_binding_result_v1"),
    "same_pipeline_real_source_ablation": ("formowl_same_pipeline_real_source_ablation_result_v1"),
    "real_user_end_answer_acceptance": "formowl_real_user_end_answer_result_v1",
}
COMMON_STRUCTURED_ARTIFACT_IDS = {
    "case_manifest": "formowl_methodology_case_manifest_dependency_v1",
    "configuration_manifest": "formowl_methodology_configuration_manifest_dependency_v1",
    "source_inventory_manifest": "formowl_methodology_source_inventory_dependency_v1",
}
GATE_STRUCTURED_ARTIFACT_IDS = {
    "raw_source_oracle_manifest": "formowl_methodology_raw_source_oracle_dependency_v1",
    "observation_reconciliation_report": (
        "formowl_methodology_observation_reconciliation_dependency_v1"
    ),
    "evaluation_report_index": "formowl_methodology_evaluation_report_index_dependency_v1",
    "evaluation_report": "formowl_methodology_evaluation_report_dependency_v1",
    "ablation_arm_result": "formowl_methodology_ablation_arm_result_dependency_v1",
    "final_answer_acceptance_report": ("formowl_methodology_final_answer_acceptance_dependency_v1"),
}
STRUCTURED_ARTIFACT_IDS = {
    **COMMON_STRUCTURED_ARTIFACT_IDS,
    **GATE_STRUCTURED_ARTIFACT_IDS,
}
OPAQUE_ROLES = frozenset({"model_artifact", "package_lock", "source_item"})
COMMON_ROLES = frozenset(
    {
        "case_manifest",
        "configuration_manifest",
        "model_artifact",
        "package_lock",
        "source_inventory_manifest",
        "source_item",
    }
)
GATE_ROLES = {
    "source_completeness_compared_with_raw_oracle": frozenset(
        {"observation_reconciliation_report", "raw_source_oracle_manifest"}
    ),
    "evaluation_reports_bind_execution_fingerprint": frozenset(
        {"evaluation_report", "evaluation_report_index"}
    ),
    "same_pipeline_real_source_ablation": frozenset({"ablation_arm_result"}),
    "real_user_end_answer_acceptance": frozenset({"final_answer_acceptance_report"}),
}
DISALLOWED_STATES = frozenset(
    {
        "blocked",
        "diagnostic",
        "diagnostic_only",
        "failed",
        "partial",
        "preflight",
        "preflight_only",
    }
)
DISALLOWED_PATH_TOKENS = frozenset({".test-tmp", "blocked", "diagnostic", "preflight", "tmp"})
ABLATION_ARM_IDS = ("kg_only", "kg_plus_ontology_hybrid_v2")

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_JSON_BYTES = 8 * 1024 * 1024
_INPUT_KEYS = {
    "artifact_id",
    "authority_id",
    "execution_fingerprint",
    "execution_binding",
    "source_manifest_path",
    "common_dependencies",
    "gates",
    "manifest_fingerprint",
}
_EXECUTION_BINDING_REFERENCE_KEYS = {
    "path",
    "byte_sha256",
    "bundle_fingerprint",
    "complete_execution_fingerprint",
}
_REFERENCE_KEYS = {"role", "path"}
_GATE_INPUT_KEYS = {"gate_id", "dependencies"}


class GateEvidenceError(RuntimeError):
    """Fail-closed error with a stable, public-safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class Dependency:
    role: str
    relative_path: Path
    byte_sha256: str
    artifact_id: str | None
    internal_fingerprint: str | None
    artifact: dict[str, Any] | None

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "path": self.relative_path.as_posix(),
            "artifact_id": self.artifact_id,
            "byte_sha256": self.byte_sha256,
            "internal_fingerprint_field": (
                "artifact_fingerprint" if self.artifact is not None else None
            ),
            "internal_fingerprint": self.internal_fingerprint,
        }


@dataclass(frozen=True)
class GateArtifacts:
    gate_id: str
    result_relative_path: Path
    result: dict[str, Any]
    result_bytes: bytes
    dependency_manifest_relative_path: Path
    dependency_manifest: dict[str, Any]
    dependency_manifest_bytes: bytes
    envelope_relative_path: Path
    envelope: dict[str, Any]
    envelope_bytes: bytes
    dependency_count: int


@dataclass(frozen=True)
class ExecutionBinding:
    relative_path: Path
    byte_sha256: str
    bundle_fingerprint: str
    complete_execution_fingerprint: str
    source_completeness_report_sha256: str
    source_completeness_report_fingerprint: str
    source_binding_fingerprint: str
    source_item_count: int
    observation_count: int
    unexplained_loss_count: int


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _with_fingerprint(payload: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    result = dict(payload)
    result.pop(field_name, None)
    result[field_name] = _canonical_fingerprint(result)
    return result


def _has_fingerprint(payload: Mapping[str, Any], field_name: str) -> bool:
    value = payload.get(field_name)
    if not _is_sha256(value):
        return False
    unhashed = dict(payload)
    unhashed.pop(field_name, None)
    return value == _canonical_fingerprint(unhashed)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _safe_relative_path(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise GateEvidenceError("unsafe_artifact_path")
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise GateEvidenceError("unsafe_artifact_path")
    for part in path.parts:
        lowered = part.lower()
        tokens = {token for token in re.split(r"[^a-z0-9.]+", lowered) if token}
        if lowered in DISALLOWED_PATH_TOKENS or tokens.intersection(DISALLOWED_PATH_TOKENS):
            raise GateEvidenceError("unsafe_artifact_path")
    return path


def _resolve_regular_file(repository_root: Path, relative_path: Path) -> Path:
    try:
        resolved_root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise GateEvidenceError("repository_root_unavailable") from exc
    candidate = resolved_root
    for part in relative_path.parts:
        candidate /= part
        if candidate.is_symlink():
            raise GateEvidenceError("artifact_symlink_rejected")
    try:
        mode = candidate.stat().st_mode
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise GateEvidenceError("artifact_missing") from exc
    if not stat.S_ISREG(mode):
        raise GateEvidenceError("artifact_not_regular_file")
    return resolved


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise GateEvidenceError("structured_artifact_too_large")
        value = json.loads(path.read_bytes())
    except GateEvidenceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateEvidenceError("structured_artifact_invalid") from exc
    if not isinstance(value, dict):
        raise GateEvidenceError("structured_artifact_invalid")
    return value


def _contains_disallowed_state(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if (
                normalized
                in {
                    "allow_blocked",
                    "diagnostic_only",
                    "diagnostic_subset_only",
                    "preflight_only",
                }
                and item is True
            ):
                return True
            if (
                (
                    normalized == "status"
                    or normalized.endswith("_status")
                    or normalized.endswith("_classification")
                    or normalized.endswith("_mode")
                    or normalized.endswith("_phase")
                )
                and isinstance(item, str)
                and item.lower() in DISALLOWED_STATES
            ):
                return True
            if _contains_disallowed_state(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_disallowed_state(item) for item in value)
    return False


def _load_authoring_input(
    repository_root: Path,
    input_manifest_relative: Path,
) -> dict[str, Any]:
    input_path = _resolve_regular_file(repository_root, input_manifest_relative)
    payload = _read_json_file(input_path)
    if (
        set(payload) != _INPUT_KEYS
        or payload.get("artifact_id") != INPUT_ARTIFACT_ID
        or not isinstance(payload.get("authority_id"), str)
        or not payload["authority_id"]
        or not _is_sha256(payload.get("execution_fingerprint"))
        or not _has_fingerprint(payload, "manifest_fingerprint")
        or _contains_disallowed_state(payload)
    ):
        raise GateEvidenceError("authoring_input_unsealed_or_invalid")
    source_manifest_relative = _safe_relative_path(payload.get("source_manifest_path"))
    _resolve_regular_file(repository_root, source_manifest_relative)
    execution_binding = payload.get("execution_binding")
    if (
        not isinstance(execution_binding, dict)
        or set(execution_binding) != _EXECUTION_BINDING_REFERENCE_KEYS
        or not _is_sha256(execution_binding.get("byte_sha256"))
        or not _is_sha256(execution_binding.get("bundle_fingerprint"))
        or not _is_sha256(execution_binding.get("complete_execution_fingerprint"))
    ):
        raise GateEvidenceError("execution_binding_reference_invalid")
    execution_binding_relative = _safe_relative_path(execution_binding.get("path"))
    _resolve_regular_file(repository_root, execution_binding_relative)

    common = payload.get("common_dependencies")
    gates = payload.get("gates")
    if not isinstance(common, list) or not isinstance(gates, list):
        raise GateEvidenceError("authoring_input_schema_invalid")
    _validate_references(common, expected_roles=COMMON_ROLES)
    gate_ids: list[str] = []
    for gate in gates:
        if not isinstance(gate, dict) or set(gate) != _GATE_INPUT_KEYS:
            raise GateEvidenceError("authoring_input_schema_invalid")
        gate_id = gate.get("gate_id")
        if gate_id not in GATE_IDS:
            raise GateEvidenceError("authoring_input_gate_invalid")
        dependencies = gate.get("dependencies")
        if not isinstance(dependencies, list):
            raise GateEvidenceError("authoring_input_schema_invalid")
        _validate_references(dependencies, expected_roles=GATE_ROLES[gate_id])
        gate_ids.append(gate_id)
    if gate_ids != sorted(GATE_IDS):
        raise GateEvidenceError("all_four_gates_required")
    return payload


def _load_execution_binding(
    *,
    repository_root: Path,
    reference: Mapping[str, Any],
    authority_execution_fingerprint: str,
) -> ExecutionBinding:
    relative_path = _safe_relative_path(reference.get("path"))
    path = _resolve_regular_file(repository_root, relative_path)
    byte_sha256 = _sha256_file(path)
    if byte_sha256 != reference.get("byte_sha256"):
        raise GateEvidenceError("execution_binding_byte_sha256_mismatch")
    try:
        bundle = load_and_validate_bundle(path)
    except Exception as exc:
        raise GateEvidenceError("execution_binding_bundle_invalid") from exc
    execution_binding = bundle["execution_binding"]
    binding_fingerprints = execution_binding["bound_fingerprints"]
    counts = bundle["counts"]
    if (
        bundle.get("execution_binding_status") != "passed"
        or bundle.get("bundle_fingerprint") != reference.get("bundle_fingerprint")
        or bundle.get("execution_fingerprint") != reference.get("complete_execution_fingerprint")
        or binding_fingerprints.get("authority_execution") != authority_execution_fingerprint
        or counts.get("source_item_count", 0) <= 0
        or counts.get("observation_count") != counts.get("source_item_count")
        or counts.get("unexplained_loss_count") != 0
    ):
        raise GateEvidenceError("execution_binding_bundle_mismatched")
    return ExecutionBinding(
        relative_path=relative_path,
        byte_sha256=byte_sha256,
        bundle_fingerprint=str(bundle["bundle_fingerprint"]),
        complete_execution_fingerprint=str(bundle["execution_fingerprint"]),
        source_completeness_report_sha256=str(
            execution_binding["source_completeness_report_sha256"]
        ),
        source_completeness_report_fingerprint=str(
            execution_binding["source_completeness_report_fingerprint"]
        ),
        source_binding_fingerprint=str(bundle["source_binding_fingerprint"]),
        source_item_count=int(counts["source_item_count"]),
        observation_count=int(counts["observation_count"]),
        unexplained_loss_count=int(counts["unexplained_loss_count"]),
    )


def _validate_references(
    references: list[Any],
    *,
    expected_roles: frozenset[str],
) -> None:
    if not references:
        raise GateEvidenceError("dependency_role_missing")
    sort_keys: list[tuple[str, str]] = []
    seen_paths: set[str] = set()
    seen_roles: set[str] = set()
    for reference in references:
        if not isinstance(reference, dict) or set(reference) != _REFERENCE_KEYS:
            raise GateEvidenceError("dependency_reference_invalid")
        role = reference.get("role")
        if not isinstance(role, str) or role not in expected_roles:
            raise GateEvidenceError("dependency_role_invalid")
        path = _safe_relative_path(reference.get("path"))
        key = (role, path.as_posix())
        if path.as_posix() in seen_paths:
            raise GateEvidenceError("dependency_path_duplicated")
        seen_paths.add(path.as_posix())
        seen_roles.add(role)
        sort_keys.append(key)
    if sort_keys != sorted(sort_keys):
        raise GateEvidenceError("dependencies_must_be_sorted")
    if not expected_roles.issubset(seen_roles):
        raise GateEvidenceError("dependency_role_missing")


def _load_dependency(
    repository_root: Path,
    reference: Mapping[str, Any],
) -> Dependency:
    role = str(reference["role"])
    relative_path = _safe_relative_path(reference["path"])
    path = _resolve_regular_file(repository_root, relative_path)
    byte_sha256 = _sha256_file(path)
    if role in OPAQUE_ROLES:
        return Dependency(
            role=role,
            relative_path=relative_path,
            byte_sha256=byte_sha256,
            artifact_id=None,
            internal_fingerprint=None,
            artifact=None,
        )
    expected_artifact_id = STRUCTURED_ARTIFACT_IDS.get(role)
    if expected_artifact_id is None:
        raise GateEvidenceError("dependency_role_invalid")
    artifact = _read_json_file(path)
    if artifact.get("artifact_id") != expected_artifact_id or not _has_fingerprint(
        artifact, "artifact_fingerprint"
    ):
        raise GateEvidenceError("dependency_unsealed")
    if _contains_disallowed_state(artifact):
        raise GateEvidenceError("dependency_disallowed_state")
    return Dependency(
        role=role,
        relative_path=relative_path,
        byte_sha256=byte_sha256,
        artifact_id=expected_artifact_id,
        internal_fingerprint=str(artifact["artifact_fingerprint"]),
        artifact=artifact,
    )


def _dependency_by_role(
    dependencies: Sequence[Dependency],
    role: str,
) -> list[Dependency]:
    return [dependency for dependency in dependencies if dependency.role == role]


def _one_payload(
    dependencies: Sequence[Dependency],
    role: str,
) -> tuple[Dependency, dict[str, Any]]:
    matches = _dependency_by_role(dependencies, role)
    if len(matches) != 1 or matches[0].artifact is None:
        raise GateEvidenceError("gate_dependency_cardinality_invalid")
    payload = matches[0].artifact.get("payload")
    if not isinstance(payload, dict):
        raise GateEvidenceError("gate_dependency_payload_invalid")
    return matches[0], payload


def _derive_result(
    *,
    gate_id: str,
    execution_fingerprint: str,
    source_manifest_sha256: str,
    dependencies: Sequence[Dependency],
) -> dict[str, Any]:
    common = {
        "artifact_id": RESULT_ARTIFACT_IDS[gate_id],
        "execution_fingerprint": execution_fingerprint,
        "source_manifest_sha256": source_manifest_sha256,
        "status": "passed",
    }
    if gate_id == "source_completeness_compared_with_raw_oracle":
        _, payload = _one_payload(dependencies, "observation_reconciliation_report")
        result = {
            **common,
            **{
                key: payload.get(key)
                for key in (
                    "raw_source_unit_count",
                    "emitted_observation_unit_count",
                    "policy_redacted_unit_count",
                    "unexplained_loss_unit_count",
                    "loss_taxonomy_counts",
                )
            },
        }
    elif gate_id == "evaluation_reports_bind_execution_fingerprint":
        reports = _dependency_by_role(dependencies, "evaluation_report")
        if not reports:
            raise GateEvidenceError("future_real_evidence_missing")
        hashes = sorted(report.byte_sha256 for report in reports)
        result = {
            **common,
            "report_count": len(reports),
            "bound_report_count": len(reports),
            "unbound_report_count": 0,
            "report_hashes": hashes,
        }
    elif gate_id == "same_pipeline_real_source_ablation":
        arms = _dependency_by_role(dependencies, "ablation_arm_result")
        arm_payloads: dict[str, tuple[Dependency, dict[str, Any]]] = {}
        for arm in arms:
            if arm.artifact is None or not isinstance(arm.artifact.get("payload"), dict):
                raise GateEvidenceError("gate_dependency_payload_invalid")
            payload = arm.artifact["payload"]
            arm_id = payload.get("arm_id")
            if arm_id not in ABLATION_ARM_IDS or arm_id in arm_payloads:
                raise GateEvidenceError("ablation_arm_set_invalid")
            arm_payloads[str(arm_id)] = (arm, payload)
        if set(arm_payloads) != set(ABLATION_ARM_IDS):
            raise GateEvidenceError("future_real_evidence_missing")
        first = arm_payloads[ABLATION_ARM_IDS[0]][1]
        result = {
            **common,
            "arm_ids": list(ABLATION_ARM_IDS),
            "case_count": first.get("case_count"),
            "completed_case_count": first.get("completed_case_count"),
            "adjudicated_case_count": first.get("adjudicated_case_count"),
            "same_source_manifest": True,
            "same_case_manifest": True,
            "same_evaluation_policy": True,
            "result_hashes_by_arm": {
                arm_id: arm_payloads[arm_id][0].byte_sha256 for arm_id in ABLATION_ARM_IDS
            },
        }
    else:
        _, payload = _one_payload(dependencies, "final_answer_acceptance_report")
        excluded = {
            "acceptance_scope",
            "case_manifest_sha256",
            "evaluation_policy_fingerprint",
            "execution_status",
            "quality_gate_status",
        }
        result = {
            **common,
            **{key: value for key, value in payload.items() if key not in excluded},
        }
    return _with_fingerprint(result, "result_fingerprint")


def _validate_execution_binding_dependencies(
    *,
    execution_binding: ExecutionBinding,
    source_manifest: Mapping[str, Any],
    common_dependencies: Sequence[Dependency],
    gate_dependencies: Mapping[str, Sequence[Dependency]],
) -> None:
    inventories = _dependency_by_role(common_dependencies, "source_inventory_manifest")
    if len(inventories) != 1 or inventories[0].artifact is None:
        raise GateEvidenceError("execution_binding_source_inventory_missing")
    inventory_payload = inventories[0].artifact.get("payload")
    if (
        not isinstance(inventory_payload, dict)
        or inventory_payload.get("source_item_count") != execution_binding.source_item_count
        or source_manifest.get("source_item_count") != execution_binding.source_item_count
    ):
        raise GateEvidenceError("execution_binding_source_inventory_mismatch")

    source_dependencies = gate_dependencies["source_completeness_compared_with_raw_oracle"]
    _, reconciliation_payload = _one_payload(
        source_dependencies,
        "observation_reconciliation_report",
    )
    if (
        reconciliation_payload.get("raw_source_unit_count") != execution_binding.source_item_count
        or reconciliation_payload.get("emitted_observation_unit_count")
        != execution_binding.observation_count
        or reconciliation_payload.get("unexplained_loss_unit_count")
        != execution_binding.unexplained_loss_count
    ):
        raise GateEvidenceError("execution_binding_source_completeness_mismatch")

    evaluation_dependencies = gate_dependencies["evaluation_reports_bind_execution_fingerprint"]
    reports = _dependency_by_role(evaluation_dependencies, "evaluation_report")
    indexes = _dependency_by_role(evaluation_dependencies, "evaluation_report_index")
    if len(indexes) != 1 or not reports or indexes[0].artifact is None:
        raise GateEvidenceError("execution_binding_evaluation_inventory_invalid")
    index_payload = indexes[0].artifact.get("payload")
    report_hashes = sorted(report.byte_sha256 for report in reports)
    report_paths = sorted(report.relative_path.as_posix() for report in reports)
    if (
        not isinstance(index_payload, dict)
        or index_payload.get("report_count") != len(reports)
        or index_payload.get("report_hashes") != report_hashes
        or index_payload.get("report_paths") != report_paths
    ):
        raise GateEvidenceError("execution_binding_evaluation_inventory_invalid")


def _build_gate_artifacts(
    *,
    output_root: Path,
    authority_id: str,
    gate_id: str,
    execution_fingerprint: str,
    source_manifest_relative: Path,
    source_manifest_sha256: str,
    dependencies: Sequence[Dependency],
) -> GateArtifacts:
    gate_root = output_root / gate_id
    result_relative = gate_root / "result.json"
    dependency_manifest_relative = methodology_gate_dependency_manifest_path(result_relative)
    envelope_relative = gate_root / "evidence-v3.json"
    result = _derive_result(
        gate_id=gate_id,
        execution_fingerprint=execution_fingerprint,
        source_manifest_sha256=source_manifest_sha256,
        dependencies=dependencies,
    )
    result_bytes = _canonical_json_bytes(result)
    result_sha256 = _sha256_bytes(result_bytes)
    entries = sorted(
        (dependency.manifest_entry() for dependency in dependencies),
        key=lambda item: (str(item["role"]), str(item["path"])),
    )
    dependency_manifest = _with_fingerprint(
        {
            "artifact_id": DEPENDENCY_MANIFEST_ARTIFACT_ID,
            "gate_id": gate_id,
            "execution_fingerprint": execution_fingerprint,
            "source_manifest_path": source_manifest_relative.as_posix(),
            "source_manifest_sha256": source_manifest_sha256,
            "result_artifact_path": result_relative.as_posix(),
            "result_artifact_sha256": result_sha256,
            "dependencies": entries,
        },
        "manifest_fingerprint",
    )
    dependency_manifest_bytes = _canonical_json_bytes(dependency_manifest)
    dependency_manifest_sha256 = _sha256_bytes(dependency_manifest_bytes)
    envelope = _with_fingerprint(
        {
            "artifact_id": ENVELOPE_ARTIFACT_ID,
            "schema_version": SCHEMA_VERSION,
            "authority_id": authority_id,
            "gate_id": gate_id,
            "execution_fingerprint": execution_fingerprint,
            "validator_id": VALIDATOR_IDS[gate_id],
            "source_manifest_path": source_manifest_relative.as_posix(),
            "source_manifest_sha256": source_manifest_sha256,
            "result_artifact_path": result_relative.as_posix(),
            "result_artifact_sha256": result_sha256,
            "dependency_manifest_path": dependency_manifest_relative.as_posix(),
            "dependency_manifest_sha256": dependency_manifest_sha256,
            "dependency_manifest_fingerprint": dependency_manifest["manifest_fingerprint"],
            "dependency_count": len(entries),
            "status": "passed",
            "evidence_classification": "production",
            "promotion_status": "not_performed",
        },
        "envelope_fingerprint",
    )
    return GateArtifacts(
        gate_id=gate_id,
        result_relative_path=result_relative,
        result=result,
        result_bytes=result_bytes,
        dependency_manifest_relative_path=dependency_manifest_relative,
        dependency_manifest=dependency_manifest,
        dependency_manifest_bytes=dependency_manifest_bytes,
        envelope_relative_path=envelope_relative,
        envelope=envelope,
        envelope_bytes=_canonical_json_bytes(envelope),
        dependency_count=len(entries),
    )


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _mirror_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        if source.stat().st_size > 16 * 1024 * 1024:
            raise GateEvidenceError("validation_mirror_link_unavailable") from None
        shutil.copyfile(source, destination)


def _validate_with_production_contract(
    *,
    repository_root: Path,
    source_manifest_relative: Path,
    source_manifest: dict[str, Any],
    source_manifest_path: Path,
    execution_fingerprint: str,
    dependencies: Sequence[Dependency],
    gate_artifacts: Sequence[GateArtifacts],
) -> None:
    with tempfile.TemporaryDirectory(prefix="issue56-gate-evidence-validator-") as temp_dir:
        mirror_root = Path(temp_dir)
        _mirror_file(
            source_manifest_path,
            mirror_root / source_manifest_relative,
        )
        mirrored: set[Path] = {source_manifest_relative}
        for dependency in dependencies:
            if dependency.relative_path in mirrored:
                continue
            _mirror_file(
                repository_root / dependency.relative_path,
                mirror_root / dependency.relative_path,
            )
            mirrored.add(dependency.relative_path)
        for artifacts in gate_artifacts:
            _write_bytes(
                mirror_root / artifacts.result_relative_path,
                artifacts.result_bytes,
            )
            _write_bytes(
                mirror_root / artifacts.dependency_manifest_relative_path,
                artifacts.dependency_manifest_bytes,
            )
            valid = validate_methodology_gate_dependency_manifest(
                repository_root=mirror_root,
                gate_id=artifacts.gate_id,
                source_manifest_path=mirror_root / source_manifest_relative,
                result_artifact_path=mirror_root / artifacts.result_relative_path,
                source_manifest=source_manifest,
                result_artifact=artifacts.result,
                execution_fingerprint=execution_fingerprint,
            )
            if not valid:
                raise GateEvidenceError("production_dependency_validation_failed")


def _atomic_write_bundle(
    *,
    repository_root: Path,
    output_root: Path,
    artifacts: Sequence[GateArtifacts],
) -> None:
    destination = repository_root / output_root
    destination_parent = destination.parent
    destination_parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise GateEvidenceError("output_exists")
    lock_path = destination_parent / f".{destination.name}.authoring.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise GateEvidenceError("output_locked") from exc
    stage_path: Path | None = None
    try:
        os.close(lock_fd)
        if destination.exists() or destination.is_symlink():
            raise GateEvidenceError("output_exists")
        stage_path = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.stage-",
                dir=destination_parent,
            )
        )
        for gate in artifacts:
            for relative_path, value in (
                (
                    gate.result_relative_path.relative_to(output_root),
                    gate.result_bytes,
                ),
                (
                    gate.dependency_manifest_relative_path.relative_to(output_root),
                    gate.dependency_manifest_bytes,
                ),
                (
                    gate.envelope_relative_path.relative_to(output_root),
                    gate.envelope_bytes,
                ),
            ):
                _write_bytes(stage_path / relative_path, value)
        os.rename(stage_path, destination)
        stage_path = None
    except GateEvidenceError:
        raise
    except OSError as exc:
        raise GateEvidenceError("atomic_write_failed") from exc
    finally:
        if stage_path is not None:
            shutil.rmtree(stage_path, ignore_errors=True)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def author_gate_evidence_bundle(
    *,
    repository_root: Path,
    input_manifest_relative: Path,
    output_root: Path,
    preflight_only: bool,
) -> dict[str, Any]:
    """Validate sealed inputs and optionally persist the four-gate bundle."""

    repository_root = repository_root.resolve(strict=True)
    input_manifest_relative = _safe_relative_path(input_manifest_relative.as_posix())
    output_root = _safe_relative_path(output_root.as_posix())
    output_path = repository_root / output_root
    if output_path.exists() or output_path.is_symlink():
        raise GateEvidenceError("output_exists")

    authoring_input = _load_authoring_input(
        repository_root,
        input_manifest_relative,
    )
    source_manifest_relative = _safe_relative_path(authoring_input["source_manifest_path"])
    source_manifest_path = _resolve_regular_file(
        repository_root,
        source_manifest_relative,
    )
    source_manifest = _read_json_file(source_manifest_path)
    execution_fingerprint = authoring_input["execution_fingerprint"]
    if (
        source_manifest.get("artifact_id") != "formowl_methodology_source_manifest_v1"
        or source_manifest.get("execution_fingerprint") != execution_fingerprint
        or source_manifest.get("source_kind") != "real_source"
        or not _has_fingerprint(source_manifest, "manifest_fingerprint")
        or _contains_disallowed_state(source_manifest)
    ):
        raise GateEvidenceError("source_manifest_unsealed_or_mismatched")
    source_manifest_sha256 = _sha256_file(source_manifest_path)
    execution_binding = _load_execution_binding(
        repository_root=repository_root,
        reference=authoring_input["execution_binding"],
        authority_execution_fingerprint=execution_fingerprint,
    )

    common_dependencies = [
        _load_dependency(repository_root, reference)
        for reference in authoring_input["common_dependencies"]
    ]
    all_dependencies: dict[Path, Dependency] = {
        dependency.relative_path: dependency for dependency in common_dependencies
    }
    gate_dependencies_by_id: dict[str, list[Dependency]] = {}
    gate_artifacts: list[GateArtifacts] = []
    for gate_input in authoring_input["gates"]:
        gate_dependencies = [
            _load_dependency(repository_root, reference) for reference in gate_input["dependencies"]
        ]
        dependencies = [*common_dependencies, *gate_dependencies]
        gate_dependencies_by_id[gate_input["gate_id"]] = gate_dependencies
        if len({item.relative_path for item in dependencies}) != len(dependencies):
            raise GateEvidenceError("dependency_path_duplicated")
        for dependency in gate_dependencies:
            all_dependencies[dependency.relative_path] = dependency
        gate_artifacts.append(
            _build_gate_artifacts(
                output_root=output_root,
                authority_id=authoring_input["authority_id"],
                gate_id=gate_input["gate_id"],
                execution_fingerprint=execution_fingerprint,
                source_manifest_relative=source_manifest_relative,
                source_manifest_sha256=source_manifest_sha256,
                dependencies=dependencies,
            )
        )

    _validate_with_production_contract(
        repository_root=repository_root,
        source_manifest_relative=source_manifest_relative,
        source_manifest=source_manifest,
        source_manifest_path=source_manifest_path,
        execution_fingerprint=execution_fingerprint,
        dependencies=tuple(all_dependencies.values()),
        gate_artifacts=gate_artifacts,
    )
    _validate_execution_binding_dependencies(
        execution_binding=execution_binding,
        source_manifest=source_manifest,
        common_dependencies=common_dependencies,
        gate_dependencies=gate_dependencies_by_id,
    )

    envelope_hashes = {item.gate_id: _sha256_bytes(item.envelope_bytes) for item in gate_artifacts}
    bundle_fingerprint = _canonical_fingerprint(
        {
            "artifact_id": BUNDLE_ARTIFACT_ID,
            "execution_fingerprint": execution_fingerprint,
            "complete_execution_fingerprint": (execution_binding.complete_execution_fingerprint),
            "execution_binding_bundle_sha256": execution_binding.byte_sha256,
            "envelope_hashes": envelope_hashes,
        }
    )
    if not preflight_only:
        _atomic_write_bundle(
            repository_root=repository_root,
            output_root=output_root,
            artifacts=gate_artifacts,
        )
    return {
        "artifact_id": REPORT_ARTIFACT_ID,
        "status": "passed",
        "authoring_status": ("preflight_completed" if preflight_only else "authoring_completed"),
        "promotion_status": "not_performed",
        "complete_execution_fingerprint": execution_binding.complete_execution_fingerprint,
        "execution_binding_bundle_sha256": execution_binding.byte_sha256,
        "execution_binding_bundle_fingerprint": execution_binding.bundle_fingerprint,
        "source_completeness_report_sha256": (execution_binding.source_completeness_report_sha256),
        "source_completeness_report_fingerprint": (
            execution_binding.source_completeness_report_fingerprint
        ),
        "gate_count": len(gate_artifacts),
        "result_artifact_count": len(gate_artifacts),
        "dependency_manifest_count": len(gate_artifacts),
        "envelope_count": len(gate_artifacts),
        "dependency_entry_count": sum(item.dependency_count for item in gate_artifacts),
        "bundle_fingerprint": bundle_fingerprint,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Author sealed Issue #56 methodology gate evidence.",
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--author", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = author_gate_evidence_bundle(
            repository_root=args.repository_root,
            input_manifest_relative=args.input_manifest,
            output_root=args.output_root,
            preflight_only=args.preflight_only,
        )
    except GateEvidenceError as exc:
        rejection = {
            "artifact_id": REJECTION_ARTIFACT_ID,
            "status": "blocked",
            "rejection_status": exc.reason_code,
            "error_count": 1,
            "error_fingerprint": _canonical_fingerprint({"reason_code": exc.reason_code}),
        }
        print(json.dumps(rejection, ensure_ascii=True, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
