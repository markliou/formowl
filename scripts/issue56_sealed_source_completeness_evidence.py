#!/usr/bin/env python3
"""Rebind sealed Issue #56 source-completeness evidence.

This command does not parse PST content, run UAT, promote methodology
authority, or inspect evaluation prompts.  It validates an already sealed
native parser/export inventory, two independently sealed source-complete
Observation snapshots, the approved workspace-only identity attestation, and
the production source manifest.  It then authors only the two safe structured
dependencies needed by the raw-source-completeness methodology gate plus a
hash/count/status-only verification report.

The source inventory dependency and source manifest are external owner
artifacts.  Their byte seals are inputs so this command can be rerun
deterministically after an integrated execution fingerprint is frozen.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
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

from formowl_contract import (  # noqa: E402
    Observation,
    SourceInventory,
    SourceInventoryProcessingState,
    assert_no_public_raw_references,
    sha256_json,
)


ARTIFACT_ID = "formowl_issue56_sealed_source_completeness_verification_v1"
RAW_ORACLE_ARTIFACT_ID = "formowl_methodology_raw_source_oracle_dependency_v1"
RECONCILIATION_ARTIFACT_ID = "formowl_methodology_observation_reconciliation_dependency_v1"
SOURCE_INVENTORY_ARTIFACT_ID = "formowl_methodology_source_inventory_dependency_v1"
SOURCE_MANIFEST_ARTIFACT_ID = "formowl_methodology_source_manifest_v1"
GATE_ID = "source_completeness_compared_with_raw_oracle"
ALGORITHM_ID = "issue56_sealed_native_inventory_observation_reconciliation_v1"
SCHEMA_VERSION = 1
RAW_ORACLE_FILENAME = "raw-source-oracle.json"
RECONCILIATION_FILENAME = "observation-reconciliation.json"
SAFE_REPORT_FILENAME = "verification-report.safe.json"
WORKSPACE_ONLY_MODE = "workspace_only_v1"

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_STABLE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{2,255}\Z")
_MAX_JSON_BYTES = 512 * 1024 * 1024
_OUTPUT_ROOT_PREFIX = Path("evidence/production")
_LOSS_TAXONOMY_KEYS = (
    "deduplication_or_occurrence_lineage_loss",
    "extractor_failure",
    "normalization_loss",
    "unknown_unexplained_loss",
    "unsupported_source_feature",
)


class SourceCompletenessEvidenceError(RuntimeError):
    """Fail-closed error with a stable, public-safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class SourceCompletenessArtifacts:
    raw_oracle: dict[str, Any]
    reconciliation: dict[str, Any]
    safe_report: dict[str, Any]


def _load_script_module(module_name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SourceCompletenessEvidenceError("owner_validator_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


rebind = _load_script_module(
    "issue56_source_complete_snapshot_rebind_for_completeness",
    "scripts/issue56_source_complete_snapshot_rebind.py",
)
identity_attestation = _load_script_module(
    "issue56_identity_scope_attestation_for_completeness",
    "scripts/issue56_identity_scope_attestation.py",
)
execution_bundle_owner = _load_script_module(
    "issue56_execution_fingerprint_for_source_completeness",
    "scripts/issue56_execution_fingerprint.py",
)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SourceCompletenessEvidenceError("sealed_input_unavailable") from exc
    return f"sha256:{digest.hexdigest()}"


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


def _with_fingerprint(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    result = dict(value)
    result.pop(field_name, None)
    result[field_name] = _canonical_fingerprint(result)
    return result


def _has_fingerprint(value: Mapping[str, Any], field_name: str) -> bool:
    expected = value.get(field_name)
    if not _is_sha256(expected):
        return False
    unsealed = dict(value)
    unsealed.pop(field_name, None)
    return expected == _canonical_fingerprint(unsealed)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _require_sha256(value: Any, reason_code: str) -> str:
    if not _is_sha256(value):
        raise SourceCompletenessEvidenceError(reason_code)
    return str(value)


def _require_stable_id(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or _STABLE_ID_RE.fullmatch(value) is None:
        raise SourceCompletenessEvidenceError(reason_code)
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _read_regular_bytes(
    path: Path,
    *,
    expected_sha256: str,
    reason_code: str,
) -> bytes:
    _require_sha256(expected_sha256, f"{reason_code}_expected_sha256_invalid")
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise SourceCompletenessEvidenceError(f"{reason_code}_unavailable") from exc
    if not stat.S_ISREG(mode) or path.is_symlink():
        raise SourceCompletenessEvidenceError(f"{reason_code}_not_regular")
    if path.stat().st_size > _MAX_JSON_BYTES:
        raise SourceCompletenessEvidenceError(f"{reason_code}_too_large")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SourceCompletenessEvidenceError(f"{reason_code}_unavailable") from exc
    if _sha256_bytes(raw) != expected_sha256:
        raise SourceCompletenessEvidenceError(f"{reason_code}_byte_seal_mismatch")
    return raw


def _read_json(
    path: Path,
    *,
    expected_sha256: str,
    reason_code: str,
) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular_bytes(
        path,
        expected_sha256=expected_sha256,
        reason_code=reason_code,
    )
    try:
        value = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SourceCompletenessEvidenceError(f"{reason_code}_json_invalid") from exc
    if type(value) is not dict:
        raise SourceCompletenessEvidenceError(f"{reason_code}_json_invalid")
    _reject_tenant_dimension(value)
    return value, raw


def _reject_tenant_dimension(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() == "tenant_id":
                raise SourceCompletenessEvidenceError("tenant_dimension_forbidden")
            _reject_tenant_dimension(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_tenant_dimension(item)


def _resolve_repository_file(repository_root: Path, value: Any) -> tuple[Path, Path]:
    if not isinstance(value, str) or not value:
        raise SourceCompletenessEvidenceError("source_path_invalid")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise SourceCompletenessEvidenceError("source_path_invalid")
    candidate = repository_root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise SourceCompletenessEvidenceError("source_path_symlink_rejected")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repository_root)
    except (OSError, ValueError) as exc:
        raise SourceCompletenessEvidenceError("source_path_unavailable") from exc
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise SourceCompletenessEvidenceError("source_path_not_regular")
    return relative, resolved


def _validate_structured_source_inventory(
    artifact: Mapping[str, Any],
    *,
    artifact_byte_sha256: str,
    repository_root: Path,
    source_asset_path: Path,
    source_asset_sha256: str,
    raw_source_unit_count: int,
) -> None:
    if (
        set(artifact)
        != {
            "artifact_id",
            "artifact_fingerprint",
            "dependency_paths",
            "payload",
        }
        or artifact.get("artifact_id") != SOURCE_INVENTORY_ARTIFACT_ID
        or not _has_fingerprint(artifact, "artifact_fingerprint")
    ):
        raise SourceCompletenessEvidenceError("source_inventory_dependency_invalid")
    payload = artifact.get("payload")
    if (
        not isinstance(payload, Mapping)
        or set(payload)
        != {
            "source_count",
            "source_hashes",
            "source_item_count",
            "source_paths",
        }
        or payload.get("source_count") != 1
        or payload.get("source_item_count") != raw_source_unit_count
        or payload.get("source_hashes") != [source_asset_sha256]
        or not isinstance(payload.get("source_paths"), list)
        or len(payload["source_paths"]) != 1
        or artifact.get("dependency_paths") != sorted(payload["source_paths"])
    ):
        raise SourceCompletenessEvidenceError("source_inventory_dependency_binding_mismatch")
    _, bound_source_path = _resolve_repository_file(
        repository_root,
        payload["source_paths"][0],
    )
    if (
        bound_source_path != source_asset_path
        or _sha256_file(bound_source_path) != source_asset_sha256
    ):
        raise SourceCompletenessEvidenceError("source_inventory_source_asset_mismatch")
    _require_sha256(artifact_byte_sha256, "source_inventory_byte_sha256_invalid")


def _validate_source_manifest(
    artifact: Mapping[str, Any],
    *,
    execution_fingerprint: str,
    source_asset_sha256: str,
    raw_source_unit_count: int,
) -> None:
    if (
        artifact.get("artifact_id") != SOURCE_MANIFEST_ARTIFACT_ID
        or artifact.get("execution_fingerprint") != execution_fingerprint
        or artifact.get("source_kind") != "real_source"
        or artifact.get("source_count") != 1
        or artifact.get("source_item_count") != raw_source_unit_count
        or artifact.get("source_hashes") != [source_asset_sha256]
        or not _has_fingerprint(artifact, "manifest_fingerprint")
    ):
        raise SourceCompletenessEvidenceError("source_manifest_binding_mismatch")


def _validate_complete_execution_bundle_binding(
    *,
    bundle_path: Path,
    expected_bundle_sha256: str,
    source_report: Mapping[str, Any],
    source_report_sha256: str,
    source_manifest: Mapping[str, Any],
    authority_execution_fingerprint: str,
) -> None:
    binding_error = SourceCompletenessEvidenceError
    try:
        bundle = execution_bundle_owner.load_and_validate_bundle(bundle_path)
        report_binding = execution_bundle_owner.source_completeness_report_binding(
            source_report
        )
    except execution_bundle_owner.ExecutionFingerprintValidationError as exc:
        raise binding_error("execution_binding_bundle_invalid") from exc
    sealed_bundle, _ = _read_json(
        bundle_path,
        expected_sha256=expected_bundle_sha256,
        reason_code="execution_binding_bundle",
    )
    if bundle != sealed_bundle:
        raise binding_error("execution_binding_bundle_invalid")
    bundle = sealed_bundle

    execution_binding = bundle["execution_binding"]
    execution_bound = execution_binding["bound_fingerprints"]
    bundle_bound = bundle["bound_fingerprints"]
    actual_bindings = (
        execution_binding["source_completeness_report_sha256"],
        execution_binding["source_completeness_report_fingerprint"],
        bundle["source_binding_fingerprint"],
        execution_binding["source_binding_fingerprint"],
        bundle_bound.get("source_snapshot"),
        execution_bound.get("source_snapshot"),
        bundle_bound.get("source_inventory"),
        execution_bound.get("source_inventory"),
        bundle_bound.get("completeness_report"),
    )
    expected_bindings = (
        source_report_sha256,
        source_report["report_fingerprint"],
        report_binding["source_binding_fingerprint"],
        report_binding["source_binding_fingerprint"],
        report_binding["source_snapshot_fingerprint"],
        report_binding["source_snapshot_fingerprint"],
        report_binding["source_inventory_fingerprint"],
        report_binding["source_inventory_fingerprint"],
        report_binding["completeness_report_fingerprint"],
    )
    if actual_bindings != expected_bindings:
        raise binding_error("execution_binding_bundle_source_binding_mismatch")

    source_count = source_report["counts"]["source_inventory_item_count"]
    if (
        bundle["counts"].get("source_item_count") != source_count
        or bundle["counts"].get("observation_count") != source_count
        or bundle["counts"].get("unexplained_loss_count") != 0
        or source_report["counts"]["observation_count"] != source_count
        or source_report["counts"]["unexplained_loss_count"] != 0
    ):
        raise binding_error("execution_binding_bundle_source_counts_mismatch")
    if (
        execution_bound.get("authority_execution")
        != authority_execution_fingerprint
        or source_manifest.get("execution_fingerprint")
        != authority_execution_fingerprint
        or source_manifest.get("source_item_count") != source_count
        or source_manifest.get("source_hashes")
        != [source_report["source_asset_sha256"]]
    ):
        raise binding_error("execution_binding_bundle_source_manifest_mismatch")


def _validate_snapshot_report_binding(
    *,
    snapshot: Mapping[str, Any],
    report: Mapping[str, Any],
    reason_prefix: str,
) -> None:
    expected = {
        "source_asset_sha256": snapshot["source_asset_sha256"],
        "native_manifest_fingerprint": snapshot["native_manifest_fingerprint"],
        "asset_binding_fingerprint": snapshot["asset_binding_fingerprint"],
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "source_ref_fingerprint": snapshot["source_ref_fingerprint"],
        "parser_fingerprint": snapshot["parser_fingerprint"],
        "source_inventory_fingerprint": sha256_json(snapshot["source_inventory"]),
        "observation_snapshot_fingerprint": sha256_json(snapshot["observations"]),
        "message_lineage_fingerprint": snapshot["lineage_rollups"]["message_lineage_fingerprint"],
        "attachment_lineage_fingerprint": snapshot["lineage_rollups"][
            "attachment_lineage_fingerprint"
        ],
        "folder_lineage_fingerprint": snapshot["lineage_rollups"]["folder_lineage_fingerprint"],
        "unsupported_lineage_fingerprint": snapshot["lineage_rollups"][
            "unsupported_lineage_fingerprint"
        ],
        "snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "counts": snapshot["counts"],
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise SourceCompletenessEvidenceError(f"{reason_prefix}_snapshot_report_binding_mismatch")


def _native_raw_unit_counts(manifest: Mapping[str, Any]) -> dict[str, int]:
    messages = manifest["messages"]
    unsupported = manifest["unsupported_non_message_records"]
    folder_ids = {str(message["pst_folder_node_id"]) for message in messages} | {
        str(record["pst_folder_node_id"]) for record in unsupported
    }
    attachment_count = sum(len(message["attachments"]) for message in messages)
    return {
        "folder_occurrence_count": len(folder_ids),
        "message_occurrence_count": len(messages),
        "attachment_occurrence_count": attachment_count,
        "unsupported_preserved_occurrence_count": len(unsupported),
        "raw_source_unit_count": (
            len(folder_ids) + len(messages) + attachment_count + len(unsupported)
        ),
    }


def _typed_policy_redaction_count(
    source_inventory: SourceInventory,
    *,
    observation_item_ids: set[str],
) -> int:
    redacted_count = 0
    for item in source_inventory.items:
        if item.source_inventory_item_id in observation_item_ids:
            continue
        if item.processing_state != SourceInventoryProcessingState.INTENTIONALLY_EXCLUDED:
            continue
        if (
            not item.exclusion_policy_id
            or not item.exclusion_policy_version
            or not item.exclusion_authorized_actor_id
            or not item.exclusion_reason
            or not item.exclusion_out_of_scope_proof_fingerprint
        ):
            raise SourceCompletenessEvidenceError("policy_redaction_contract_invalid")
        redacted_count += 1
    return redacted_count


def _derive_accounting(
    *,
    manifest: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    raw_counts = _native_raw_unit_counts(manifest)
    source_inventory = SourceInventory.from_dict(snapshot["source_inventory"])
    observations = [Observation.from_dict(row) for row in snapshot["observations"]]
    observation_item_ids = {
        str(observation.location.get("source_inventory_item_id") or "")
        for observation in observations
    }
    policy_redacted_count = _typed_policy_redaction_count(
        source_inventory,
        observation_item_ids=observation_item_ids,
    )
    emitted_count = len(observation_item_ids)
    raw_count = raw_counts["raw_source_unit_count"]
    unexplained_count = raw_count - emitted_count - policy_redacted_count
    if unexplained_count < 0:
        raise SourceCompletenessEvidenceError("observation_count_exceeds_raw_inventory")

    snapshot_counts = snapshot["counts"]
    extractor_failure = int(snapshot_counts.get("failed_record_count", 0))
    normalization_loss = int(snapshot_counts.get("missing_content_hash_count", 0))
    lineage_loss = max(
        int(snapshot_counts.get("missing_source_inventory_binding_count", 0)),
        int(snapshot_counts.get("missing_parent_lineage_count", 0)),
    )
    unsupported_loss = max(
        0,
        raw_counts["unsupported_preserved_occurrence_count"]
        - int(snapshot_counts.get("unsupported_preserved_occurrence_count", 0)),
    )
    classified = extractor_failure + normalization_loss + lineage_loss + unsupported_loss
    unknown_loss = max(0, unexplained_count - classified)
    taxonomy = {
        "deduplication_or_occurrence_lineage_loss": lineage_loss,
        "extractor_failure": extractor_failure,
        "normalization_loss": normalization_loss,
        "unknown_unexplained_loss": unknown_loss,
        "unsupported_source_feature": unsupported_loss,
    }
    if sum(taxonomy.values()) != unexplained_count:
        raise SourceCompletenessEvidenceError("loss_taxonomy_overlap_or_gap")
    return {
        **raw_counts,
        "emitted_observation_unit_count": emitted_count,
        "policy_redacted_unit_count": policy_redacted_count,
        "unexplained_loss_unit_count": unexplained_count,
        "loss_taxonomy_counts": taxonomy,
    }


def _cross_bind_source_snapshots(
    *,
    existing_snapshot: Mapping[str, Any],
    existing_report: Mapping[str, Any],
    approved_snapshot: Mapping[str, Any],
    approved_report: Mapping[str, Any],
) -> None:
    snapshot_fields = (
        "source_asset_sha256",
        "native_manifest_fingerprint",
        "asset_binding_fingerprint",
        "permission_fingerprint",
        "source_ref_fingerprint",
        "parser_fingerprint",
        "counts",
        "lineage_rollups",
    )
    if any(
        existing_snapshot.get(field) != approved_snapshot.get(field) for field in snapshot_fields
    ):
        raise SourceCompletenessEvidenceError("source_snapshot_cross_binding_mismatch")
    report_fields = (
        "source_asset_sha256",
        "native_manifest_fingerprint",
        "asset_binding_fingerprint",
        "permission_fingerprint",
        "source_ref_fingerprint",
        "parser_fingerprint",
        "message_lineage_fingerprint",
        "attachment_lineage_fingerprint",
        "folder_lineage_fingerprint",
        "unsupported_lineage_fingerprint",
        "counts",
    )
    if any(existing_report.get(field) != approved_report.get(field) for field in report_fields):
        raise SourceCompletenessEvidenceError("source_report_cross_binding_mismatch")


def _validate_attestation_binding(
    *,
    private_attestation: Mapping[str, Any],
    safe_attestation: Mapping[str, Any],
    approved_snapshot: Mapping[str, Any],
    expected_workspace_id: str,
    expected_approver_actor: str,
    expected_identity_scope_fingerprint: str,
) -> None:
    scope = private_attestation["identity_scope"]
    approval = private_attestation["approval"]
    asset_binding = private_attestation["asset_binding"]
    authorization = approved_snapshot["authorization_binding"]
    expected = {
        "mode": WORKSPACE_ONLY_MODE,
        "workspace_id": expected_workspace_id,
    }
    if scope != expected or approval.get("approver_actor") != expected_approver_actor:
        raise SourceCompletenessEvidenceError("identity_scope_binding_mismatch")
    if (
        safe_attestation.get("identity_scope_fingerprint") != expected_identity_scope_fingerprint
        or asset_binding.get("asset_id") != authorization.get("source_asset_id")
        or asset_binding.get("asset_content_hash") != approved_snapshot.get("source_asset_sha256")
        or private_attestation.get("source_fingerprint")
        != approved_snapshot.get("snapshot_fingerprint")
        or private_attestation.get("permission_fingerprint")
        != approved_snapshot.get("permission_fingerprint")
    ):
        raise SourceCompletenessEvidenceError("attestation_source_binding_mismatch")


def _gate_dependency(
    *,
    artifact_id: str,
    execution_fingerprint: str,
    source_manifest_sha256: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return _with_fingerprint(
        {
            "artifact_id": artifact_id,
            "gate_id": GATE_ID,
            "execution_fingerprint": execution_fingerprint,
            "source_manifest_sha256": source_manifest_sha256,
            "status": "passed",
            "evidence_classification": "production",
            "dependency_paths": [],
            "payload": dict(payload),
        },
        "artifact_fingerprint",
    )


def _build_safe_report(
    *,
    execution_fingerprint: str,
    source_manifest_sha256: str,
    source_inventory_sha256: str,
    source_asset_sha256: str,
    native_manifest_sha256: str,
    native_manifest_fingerprint: str,
    existing_snapshot_sha256: str,
    existing_report_sha256: str,
    existing_snapshot: Mapping[str, Any],
    existing_report: Mapping[str, Any],
    approved_snapshot_sha256: str,
    approved_report_sha256: str,
    approved_snapshot: Mapping[str, Any],
    approved_report: Mapping[str, Any],
    attestation_private_sha256: str,
    attestation_safe_sha256: str,
    attested_asset_fingerprint: str,
    identity_scope_fingerprint: str,
    workspace_id: str,
    approver_actor: str,
    raw_oracle_sha256: str,
    raw_oracle_fingerprint: str,
    reconciliation_sha256: str,
    reconciliation_fingerprint: str,
    accounting: Mapping[str, Any],
) -> dict[str, Any]:
    counts = {
        "attachment_occurrence_count": accounting["attachment_occurrence_count"],
        "emitted_observation_unit_count": accounting["emitted_observation_unit_count"],
        "folder_occurrence_count": accounting["folder_occurrence_count"],
        "message_occurrence_count": accounting["message_occurrence_count"],
        "policy_redacted_unit_count": accounting["policy_redacted_unit_count"],
        "preserved_unsupported_unit_count": accounting["unsupported_preserved_occurrence_count"],
        "raw_source_unit_count": accounting["raw_source_unit_count"],
        "unexplained_loss_unit_count": accounting["unexplained_loss_unit_count"],
    }
    report = _with_fingerprint(
        {
            "artifact_id": ARTIFACT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": "passed",
            "source_completeness_gate_status": "eligible_for_gate_evidence_authoring",
            "promotion_status": "not_performed",
            "claim_boundary_status": "source_completeness_dependencies_only",
            "identity_scope_mode": WORKSPACE_ONLY_MODE,
            "tenant_dimension_status": "absent_not_fabricated",
            "execution_fingerprint": execution_fingerprint,
            "source_manifest_sha256": source_manifest_sha256,
            "source_inventory_dependency_sha256": source_inventory_sha256,
            "source_asset_sha256": source_asset_sha256,
            "native_manifest_byte_sha256": native_manifest_sha256,
            "native_manifest_fingerprint": native_manifest_fingerprint,
            "existing_snapshot_byte_sha256": existing_snapshot_sha256,
            "existing_snapshot_fingerprint": existing_snapshot["snapshot_fingerprint"],
            "existing_report_byte_sha256": existing_report_sha256,
            "existing_report_fingerprint": existing_report["report_fingerprint"],
            "approved_snapshot_byte_sha256": approved_snapshot_sha256,
            "approved_snapshot_fingerprint": approved_snapshot["snapshot_fingerprint"],
            "approved_report_byte_sha256": approved_report_sha256,
            "approved_report_fingerprint": approved_report["report_fingerprint"],
            "attestation_private_byte_sha256": attestation_private_sha256,
            "attestation_safe_byte_sha256": attestation_safe_sha256,
            "attested_asset_fingerprint": attested_asset_fingerprint,
            "identity_scope_fingerprint": identity_scope_fingerprint,
            "workspace_fingerprint": sha256_json(workspace_id),
            "approver_actor_fingerprint": sha256_json(approver_actor),
            "asset_binding_fingerprint": approved_snapshot["asset_binding_fingerprint"],
            "parser_fingerprint": approved_snapshot["parser_fingerprint"],
            "permission_fingerprint": approved_snapshot["permission_fingerprint"],
            "source_ref_fingerprint": approved_snapshot["source_ref_fingerprint"],
            "message_lineage_fingerprint": approved_report["message_lineage_fingerprint"],
            "attachment_lineage_fingerprint": approved_report["attachment_lineage_fingerprint"],
            "folder_lineage_fingerprint": approved_report["folder_lineage_fingerprint"],
            "unsupported_lineage_fingerprint": approved_report["unsupported_lineage_fingerprint"],
            "raw_oracle_dependency_sha256": raw_oracle_sha256,
            "raw_oracle_dependency_fingerprint": raw_oracle_fingerprint,
            "reconciliation_dependency_sha256": reconciliation_sha256,
            "reconciliation_dependency_fingerprint": reconciliation_fingerprint,
            "algorithm_fingerprint": sha256_json(ALGORITHM_ID),
            "counts": counts,
            "loss_taxonomy_counts": dict(accounting["loss_taxonomy_counts"]),
            "validation_statuses": {
                "attestation_binding": "passed",
                "native_export_coverage": "passed",
                "raw_source_byte_seal": "passed",
                "source_inventory_dependency_binding": "passed",
                "source_manifest_binding": "passed",
                "source_snapshot_cross_binding": "passed",
                "source_snapshot_internal_validation": "passed",
            },
        },
        "artifact_fingerprint",
    )
    _validate_safe_report(report)
    return report


def _validate_safe_report(report: Mapping[str, Any]) -> None:
    if (
        report.get("artifact_id") != ARTIFACT_ID
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("status") != "passed"
        or report.get("source_completeness_gate_status") != "eligible_for_gate_evidence_authoring"
        or report.get("promotion_status") != "not_performed"
        or report.get("identity_scope_mode") != WORKSPACE_ONLY_MODE
        or report.get("tenant_dimension_status") != "absent_not_fabricated"
        or not _has_fingerprint(report, "artifact_fingerprint")
    ):
        raise SourceCompletenessEvidenceError("safe_report_contract_invalid")
    counts = report.get("counts")
    taxonomy = report.get("loss_taxonomy_counts")
    if (
        not isinstance(counts, Mapping)
        or any(type(value) is not int or value < 0 for value in counts.values())
        or not isinstance(taxonomy, Mapping)
        or tuple(sorted(taxonomy)) != tuple(sorted(_LOSS_TAXONOMY_KEYS))
        or any(type(value) is not int or value < 0 for value in taxonomy.values())
        or counts.get("raw_source_unit_count")
        != counts.get("emitted_observation_unit_count")
        + counts.get("policy_redacted_unit_count")
        + counts.get("unexplained_loss_unit_count")
        or counts.get("unexplained_loss_unit_count") != 0
        or sum(taxonomy.values()) != 0
    ):
        raise SourceCompletenessEvidenceError("safe_report_accounting_invalid")
    _reject_tenant_dimension(report)
    serialized = json.dumps(report, ensure_ascii=True, sort_keys=True).casefold()
    if any(
        token in serialized
        for token in (
            "answer_oracle",
            "query_text",
            "raw_path",
            "relative_output_path",
            "source_payload",
            ".test-tmp",
        )
    ):
        raise SourceCompletenessEvidenceError("safe_report_private_data_exposed")
    assert_no_public_raw_references(
        report,
        "issue56_sealed_source_completeness_verification",
    )


def _write_file_exclusive(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _persist_atomic(
    *,
    repository_root: Path,
    output_root: Path,
    files: Mapping[str, bytes],
) -> None:
    if (
        output_root.is_absolute()
        or ".." in output_root.parts
        or len(output_root.parts) < len(_OUTPUT_ROOT_PREFIX.parts) + 1
        or output_root.parts[: len(_OUTPUT_ROOT_PREFIX.parts)] != _OUTPUT_ROOT_PREFIX.parts
    ):
        raise SourceCompletenessEvidenceError("output_root_not_production_scoped")
    destination = repository_root / output_root
    if destination.exists() or destination.is_symlink():
        raise SourceCompletenessEvidenceError("immutable_output_already_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock_path = destination.parent / f".{destination.name}.lock"
    try:
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SourceCompletenessEvidenceError("immutable_output_locked") from exc
    stage_path: Path | None = None
    try:
        os.close(lock_fd)
        stage_path = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.stage-",
                dir=destination.parent,
            )
        )
        for name, value in sorted(files.items()):
            _write_file_exclusive(stage_path / name, value)
        os.rename(stage_path, destination)
        stage_path = None
    except SourceCompletenessEvidenceError:
        raise
    except OSError as exc:
        raise SourceCompletenessEvidenceError("atomic_output_failed") from exc
    finally:
        if stage_path is not None:
            shutil.rmtree(stage_path, ignore_errors=True)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def author_sealed_source_completeness_evidence(
    *,
    repository_root: Path,
    source_asset_path: Path,
    expected_source_asset_sha256: str,
    native_manifest_path: Path,
    expected_native_manifest_sha256: str,
    native_export_root: Path,
    existing_snapshot_path: Path,
    expected_existing_snapshot_sha256: str,
    existing_report_path: Path,
    expected_existing_report_sha256: str,
    approved_snapshot_path: Path,
    expected_approved_snapshot_sha256: str,
    approved_report_path: Path,
    expected_approved_report_sha256: str,
    attestation_private_path: Path,
    expected_attestation_private_sha256: str,
    attestation_safe_path: Path,
    expected_attestation_safe_sha256: str,
    expected_identity_scope_fingerprint: str,
    expected_workspace_id: str,
    expected_approver_actor: str,
    source_inventory_dependency_path: Path,
    expected_source_inventory_dependency_sha256: str,
    execution_binding_bundle_path: Path,
    expected_execution_binding_bundle_sha256: str,
    source_manifest_path: Path,
    expected_source_manifest_sha256: str,
    execution_fingerprint: str,
    output_root: Path,
) -> SourceCompletenessArtifacts:
    """Validate sealed evidence and atomically author safe gate dependencies."""

    repository_root = repository_root.resolve(strict=True)
    _require_sha256(expected_source_asset_sha256, "source_asset_sha256_invalid")
    _require_sha256(execution_fingerprint, "execution_fingerprint_invalid")
    _require_sha256(
        expected_identity_scope_fingerprint,
        "identity_scope_fingerprint_invalid",
    )
    _require_stable_id(expected_workspace_id, "workspace_id_invalid")
    _require_stable_id(expected_approver_actor, "approver_actor_invalid")

    source_asset_path = source_asset_path.resolve(strict=True)
    source_asset_path.relative_to(repository_root)
    if source_asset_path.is_symlink() or not stat.S_ISREG(source_asset_path.stat().st_mode):
        raise SourceCompletenessEvidenceError("source_asset_not_regular")
    if _sha256_file(source_asset_path) != expected_source_asset_sha256:
        raise SourceCompletenessEvidenceError("source_asset_byte_seal_mismatch")

    native_manifest, _ = _read_json(
        native_manifest_path,
        expected_sha256=expected_native_manifest_sha256,
        reason_code="native_manifest",
    )
    try:
        validated_native_manifest = rebind._load_native_private_manifest(
            native_manifest_path,
            export_root=native_export_root,
        )
    except RuntimeError as exc:
        raise SourceCompletenessEvidenceError(str(exc)) from exc
    if validated_native_manifest != native_manifest:
        raise SourceCompletenessEvidenceError("native_manifest_round_trip_mismatch")
    if native_manifest.get("source_asset_sha256") != expected_source_asset_sha256:
        raise SourceCompletenessEvidenceError("native_manifest_source_asset_mismatch")

    existing_snapshot, _ = _read_json(
        existing_snapshot_path,
        expected_sha256=expected_existing_snapshot_sha256,
        reason_code="existing_snapshot",
    )
    existing_report, _ = _read_json(
        existing_report_path,
        expected_sha256=expected_existing_report_sha256,
        reason_code="existing_report",
    )
    approved_snapshot, _ = _read_json(
        approved_snapshot_path,
        expected_sha256=expected_approved_snapshot_sha256,
        reason_code="approved_snapshot",
    )
    approved_report, _ = _read_json(
        approved_report_path,
        expected_sha256=expected_approved_report_sha256,
        reason_code="approved_report",
    )
    try:
        rebind._validate_native_authorized_snapshot(existing_snapshot)
        rebind._validate_native_authorized_report(existing_report)
        rebind._validate_native_authorized_snapshot(approved_snapshot)
        rebind._validate_native_authorized_report(approved_report)
    except RuntimeError as exc:
        raise SourceCompletenessEvidenceError(str(exc)) from exc
    _validate_snapshot_report_binding(
        snapshot=existing_snapshot,
        report=existing_report,
        reason_prefix="existing",
    )
    _validate_snapshot_report_binding(
        snapshot=approved_snapshot,
        report=approved_report,
        reason_prefix="approved",
    )
    _cross_bind_source_snapshots(
        existing_snapshot=existing_snapshot,
        existing_report=existing_report,
        approved_snapshot=approved_snapshot,
        approved_report=approved_report,
    )
    if approved_snapshot.get("native_manifest_fingerprint") != native_manifest.get(
        "manifest_fingerprint"
    ):
        raise SourceCompletenessEvidenceError("native_manifest_snapshot_binding_mismatch")

    accounting = _derive_accounting(
        manifest=native_manifest,
        snapshot=approved_snapshot,
    )
    if accounting["unexplained_loss_unit_count"] != 0:
        raise SourceCompletenessEvidenceError("unexplained_source_loss")
    if (
        approved_snapshot["counts"]["source_inventory_item_count"]
        != accounting["raw_source_unit_count"]
    ):
        raise SourceCompletenessEvidenceError("source_inventory_raw_count_mismatch")

    private_attestation_bytes = _read_regular_bytes(
        attestation_private_path,
        expected_sha256=expected_attestation_private_sha256,
        reason_code="attestation_private",
    )
    try:
        private_attestation = identity_attestation.load_identity_scope_attestation(
            attestation_private_path,
            expected_sha256=expected_attestation_private_sha256,
        )
    except RuntimeError as exc:
        raise SourceCompletenessEvidenceError(str(exc)) from exc
    safe_attestation, _ = _read_json(
        attestation_safe_path,
        expected_sha256=expected_attestation_safe_sha256,
        reason_code="attestation_safe",
    )
    try:
        identity_attestation.validate_safe_identity_scope_report(
            safe_attestation,
            private_artifact_bytes=private_attestation_bytes,
        )
    except RuntimeError as exc:
        raise SourceCompletenessEvidenceError(str(exc)) from exc
    _validate_attestation_binding(
        private_attestation=private_attestation,
        safe_attestation=safe_attestation,
        approved_snapshot=approved_snapshot,
        expected_workspace_id=expected_workspace_id,
        expected_approver_actor=expected_approver_actor,
        expected_identity_scope_fingerprint=expected_identity_scope_fingerprint,
    )

    source_inventory_dependency, _ = _read_json(
        source_inventory_dependency_path,
        expected_sha256=expected_source_inventory_dependency_sha256,
        reason_code="source_inventory_dependency",
    )
    _validate_structured_source_inventory(
        source_inventory_dependency,
        artifact_byte_sha256=expected_source_inventory_dependency_sha256,
        repository_root=repository_root,
        source_asset_path=source_asset_path,
        source_asset_sha256=expected_source_asset_sha256,
        raw_source_unit_count=accounting["raw_source_unit_count"],
    )
    source_manifest, _ = _read_json(
        source_manifest_path,
        expected_sha256=expected_source_manifest_sha256,
        reason_code="source_manifest",
    )
    _validate_source_manifest(
        source_manifest,
        execution_fingerprint=execution_fingerprint,
        source_asset_sha256=expected_source_asset_sha256,
        raw_source_unit_count=accounting["raw_source_unit_count"],
    )
    _validate_complete_execution_bundle_binding(
        bundle_path=execution_binding_bundle_path,
        expected_bundle_sha256=expected_execution_binding_bundle_sha256,
        source_report=existing_report,
        source_report_sha256=expected_existing_report_sha256,
        source_manifest=source_manifest,
        authority_execution_fingerprint=execution_fingerprint,
    )

    raw_oracle = _gate_dependency(
        artifact_id=RAW_ORACLE_ARTIFACT_ID,
        execution_fingerprint=execution_fingerprint,
        source_manifest_sha256=expected_source_manifest_sha256,
        payload={
            "raw_source_unit_count": accounting["raw_source_unit_count"],
            "source_inventory_sha256": expected_source_inventory_dependency_sha256,
        },
    )
    raw_oracle_bytes = _canonical_json_bytes(raw_oracle)
    raw_oracle_sha256 = _sha256_bytes(raw_oracle_bytes)
    reconciliation = _gate_dependency(
        artifact_id=RECONCILIATION_ARTIFACT_ID,
        execution_fingerprint=execution_fingerprint,
        source_manifest_sha256=expected_source_manifest_sha256,
        payload={
            "raw_source_unit_count": accounting["raw_source_unit_count"],
            "emitted_observation_unit_count": accounting["emitted_observation_unit_count"],
            "policy_redacted_unit_count": accounting["policy_redacted_unit_count"],
            "unexplained_loss_unit_count": accounting["unexplained_loss_unit_count"],
            "loss_taxonomy_counts": accounting["loss_taxonomy_counts"],
            "raw_source_oracle_sha256": raw_oracle_sha256,
            "source_inventory_sha256": expected_source_inventory_dependency_sha256,
        },
    )
    reconciliation_bytes = _canonical_json_bytes(reconciliation)
    reconciliation_sha256 = _sha256_bytes(reconciliation_bytes)
    safe_report = _build_safe_report(
        execution_fingerprint=execution_fingerprint,
        source_manifest_sha256=expected_source_manifest_sha256,
        source_inventory_sha256=expected_source_inventory_dependency_sha256,
        source_asset_sha256=expected_source_asset_sha256,
        native_manifest_sha256=expected_native_manifest_sha256,
        native_manifest_fingerprint=native_manifest["manifest_fingerprint"],
        existing_snapshot_sha256=expected_existing_snapshot_sha256,
        existing_report_sha256=expected_existing_report_sha256,
        existing_snapshot=existing_snapshot,
        existing_report=existing_report,
        approved_snapshot_sha256=expected_approved_snapshot_sha256,
        approved_report_sha256=expected_approved_report_sha256,
        approved_snapshot=approved_snapshot,
        approved_report=approved_report,
        attestation_private_sha256=expected_attestation_private_sha256,
        attestation_safe_sha256=expected_attestation_safe_sha256,
        attested_asset_fingerprint=private_attestation["asset_binding"]["asset_fingerprint"],
        identity_scope_fingerprint=expected_identity_scope_fingerprint,
        workspace_id=expected_workspace_id,
        approver_actor=expected_approver_actor,
        raw_oracle_sha256=raw_oracle_sha256,
        raw_oracle_fingerprint=raw_oracle["artifact_fingerprint"],
        reconciliation_sha256=reconciliation_sha256,
        reconciliation_fingerprint=reconciliation["artifact_fingerprint"],
        accounting=accounting,
    )
    safe_report_bytes = _canonical_json_bytes(safe_report)
    _persist_atomic(
        repository_root=repository_root,
        output_root=output_root,
        files={
            RAW_ORACLE_FILENAME: raw_oracle_bytes,
            RECONCILIATION_FILENAME: reconciliation_bytes,
            SAFE_REPORT_FILENAME: safe_report_bytes,
        },
    )
    destination = repository_root / output_root
    persisted = {
        RAW_ORACLE_FILENAME: json.loads((destination / RAW_ORACLE_FILENAME).read_bytes()),
        RECONCILIATION_FILENAME: json.loads((destination / RECONCILIATION_FILENAME).read_bytes()),
        SAFE_REPORT_FILENAME: json.loads((destination / SAFE_REPORT_FILENAME).read_bytes()),
    }
    if (
        persisted[RAW_ORACLE_FILENAME] != raw_oracle
        or persisted[RECONCILIATION_FILENAME] != reconciliation
        or persisted[SAFE_REPORT_FILENAME] != safe_report
    ):
        raise SourceCompletenessEvidenceError("atomic_output_round_trip_failed")
    return SourceCompletenessArtifacts(
        raw_oracle=raw_oracle,
        reconciliation=reconciliation,
        safe_report=safe_report,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebind sealed Issue #56 source-completeness evidence",
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--source-asset", type=Path, required=True)
    parser.add_argument("--expected-source-asset-sha256", required=True)
    parser.add_argument("--native-manifest", type=Path, required=True)
    parser.add_argument("--expected-native-manifest-sha256", required=True)
    parser.add_argument("--native-export-root", type=Path, required=True)
    parser.add_argument("--existing-snapshot", type=Path, required=True)
    parser.add_argument("--expected-existing-snapshot-sha256", required=True)
    parser.add_argument("--existing-report", type=Path, required=True)
    parser.add_argument("--expected-existing-report-sha256", required=True)
    parser.add_argument("--approved-snapshot", type=Path, required=True)
    parser.add_argument("--expected-approved-snapshot-sha256", required=True)
    parser.add_argument("--approved-report", type=Path, required=True)
    parser.add_argument("--expected-approved-report-sha256", required=True)
    parser.add_argument("--attestation-private", type=Path, required=True)
    parser.add_argument("--expected-attestation-private-sha256", required=True)
    parser.add_argument("--attestation-safe", type=Path, required=True)
    parser.add_argument("--expected-attestation-safe-sha256", required=True)
    parser.add_argument("--expected-identity-scope-fingerprint", required=True)
    parser.add_argument("--expected-workspace-id", required=True)
    parser.add_argument("--expected-approver-actor", required=True)
    parser.add_argument("--source-inventory-dependency", type=Path, required=True)
    parser.add_argument("--expected-source-inventory-dependency-sha256", required=True)
    parser.add_argument("--execution-binding-bundle", type=Path, required=True)
    parser.add_argument("--expected-execution-binding-bundle-sha256", required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--expected-source-manifest-sha256", required=True)
    parser.add_argument("--execution-fingerprint", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        artifacts = author_sealed_source_completeness_evidence(
            repository_root=args.repository_root,
            source_asset_path=args.source_asset,
            expected_source_asset_sha256=args.expected_source_asset_sha256,
            native_manifest_path=args.native_manifest,
            expected_native_manifest_sha256=args.expected_native_manifest_sha256,
            native_export_root=args.native_export_root,
            existing_snapshot_path=args.existing_snapshot,
            expected_existing_snapshot_sha256=args.expected_existing_snapshot_sha256,
            existing_report_path=args.existing_report,
            expected_existing_report_sha256=args.expected_existing_report_sha256,
            approved_snapshot_path=args.approved_snapshot,
            expected_approved_snapshot_sha256=args.expected_approved_snapshot_sha256,
            approved_report_path=args.approved_report,
            expected_approved_report_sha256=args.expected_approved_report_sha256,
            attestation_private_path=args.attestation_private,
            expected_attestation_private_sha256=args.expected_attestation_private_sha256,
            attestation_safe_path=args.attestation_safe,
            expected_attestation_safe_sha256=args.expected_attestation_safe_sha256,
            expected_identity_scope_fingerprint=args.expected_identity_scope_fingerprint,
            expected_workspace_id=args.expected_workspace_id,
            expected_approver_actor=args.expected_approver_actor,
            source_inventory_dependency_path=args.source_inventory_dependency,
            expected_source_inventory_dependency_sha256=(
                args.expected_source_inventory_dependency_sha256
            ),
            execution_binding_bundle_path=args.execution_binding_bundle,
            expected_execution_binding_bundle_sha256=(
                args.expected_execution_binding_bundle_sha256
            ),
            source_manifest_path=args.source_manifest,
            expected_source_manifest_sha256=args.expected_source_manifest_sha256,
            execution_fingerprint=args.execution_fingerprint,
            output_root=args.output_root,
        )
    except (OSError, ValueError, SourceCompletenessEvidenceError) as exc:
        reason = (
            exc.reason_code
            if isinstance(exc, SourceCompletenessEvidenceError)
            else "source_completeness_authoring_failed"
        )
        print(
            json.dumps(
                {
                    "artifact_id": ARTIFACT_ID,
                    "status": "failed",
                    "reason_code": reason,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "artifact_id": ARTIFACT_ID,
                "status": "passed",
                "raw_oracle_dependency_fingerprint": artifacts.raw_oracle["artifact_fingerprint"],
                "reconciliation_dependency_fingerprint": artifacts.reconciliation[
                    "artifact_fingerprint"
                ],
                "verification_fingerprint": artifacts.safe_report["artifact_fingerprint"],
                "counts": artifacts.safe_report["counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
