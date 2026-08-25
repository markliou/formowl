#!/usr/bin/env python3
"""Create or validate an immutable Issue #56 identity-scope attestation.

This operator-facing tool records an explicit decision; it never chooses a
scope, invents a tenant, reads mail content, or mutates source/runtime state.
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = 1
PRIVATE_ARTIFACT_ID = "formowl_issue56_identity_scope_attestation_private_v1"
SAFE_REPORT_ARTIFACT_ID = "formowl_issue56_identity_scope_attestation_safe_report_v1"
ERROR_ARTIFACT_ID = "formowl_issue56_identity_scope_attestation_rejection_v1"
PRIVATE_ARTIFACT_FILENAME = "identity-scope-attestation.private.json"
SAFE_REPORT_FILENAME = "identity-scope-attestation.safe.json"
POLICY_ID = "issue56_operator_approved_identity_scope_attestation_v1"
TENANT_WORKSPACE_MODE = "tenant_workspace_v1"
WORKSPACE_ONLY_MODE = "workspace_only_v1"
SPEC_OPERATOR_APPROVAL_KIND = "spec_operator_explicit_v1"

_APPROVED_MODES = frozenset({TENANT_WORKSPACE_MODE, WORKSPACE_ONLY_MODE})
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_STABLE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{2,255}")
_PLACEHOLDERS = frozenset(
    {
        "n/a",
        "na",
        "none",
        "null",
        "placeholder",
        "tbd",
        "todo",
        "unknown",
        "unset",
    }
)
_MAX_INPUT_BYTES = 1024 * 1024
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class IdentityScopeAttestationError(RuntimeError):
    """Fail-closed error carrying one stable public reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


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


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _fingerprint_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


POLICY_FINGERPRINT = _fingerprint_json(
    {
        "policy_id": POLICY_ID,
        "approved_modes": sorted(_APPROVED_MODES),
        "tenant_workspace_v1": {
            "tenant_id_required": True,
            "spec_approval_id_allowed": False,
        },
        "workspace_only_v1": {
            "tenant_field_allowed": False,
            "operator_approval_required": True,
            "spec_approval_id_required": True,
            "approval_kind": SPEC_OPERATOR_APPROVAL_KIND,
        },
        "required_bindings": [
            "workspace_id",
            "asset_id",
            "asset_content_hash",
            "asset_fingerprint",
            "source_fingerprint",
            "permission_fingerprint",
            "approver_actor",
            "authority_source",
            "approved_at",
            "reason",
        ],
        "approved_at_default_allowed": False,
        "placeholder_allowed": False,
        "overwrite_allowed": False,
        "force_or_bypass_allowed": False,
    }
)


def build_identity_scope_attestation(
    *,
    mode: str,
    workspace_id: str,
    tenant_id: str | None,
    asset_id: str,
    asset_content_hash: str,
    source_fingerprint: str,
    permission_fingerprint: str,
    approver_actor: str,
    authority_source: str,
    approved_at: str,
    reason: str,
    operator_approved: bool,
    spec_approval_id: str | None,
) -> dict[str, Any]:
    """Build one private attestation from explicit operator-supplied fields."""

    _validate_mode_inputs(
        mode=mode,
        tenant_id=tenant_id,
        operator_approved=operator_approved,
        spec_approval_id=spec_approval_id,
    )
    workspace_id = _require_stable_id(workspace_id, "workspace_id")
    asset_id = _require_stable_id(asset_id, "asset_id")
    asset_content_hash = _require_sha256(asset_content_hash, "asset_content_hash_invalid")
    source_fingerprint = _require_sha256(source_fingerprint, "source_fingerprint_invalid")
    permission_fingerprint = _require_sha256(
        permission_fingerprint,
        "permission_fingerprint_invalid",
    )
    approver_actor = _require_stable_id(approver_actor, "approver_actor")
    authority_source = _require_stable_id(authority_source, "authority_source")
    approved_at = _require_explicit_timestamp(approved_at)
    reason = _require_reason(reason)

    identity_scope: dict[str, Any] = {
        "mode": mode,
        "workspace_id": workspace_id,
    }
    if mode == TENANT_WORKSPACE_MODE:
        identity_scope["tenant_id"] = _require_stable_id(tenant_id, "tenant_id")
    asset_fingerprint = _fingerprint_json(
        {
            "asset_id": asset_id,
            "asset_content_hash": asset_content_hash,
            "workspace_id": workspace_id,
            "permission_fingerprint": permission_fingerprint,
        }
    )
    approval: dict[str, Any] = {
        "operator_approved": True,
        "approver_actor": approver_actor,
        "authority_source": authority_source,
        "approved_at": approved_at,
        "reason": reason,
    }
    if mode == WORKSPACE_ONLY_MODE:
        approval.update(
            {
                "approval_kind": SPEC_OPERATOR_APPROVAL_KIND,
                "spec_approval_id": _require_stable_id(
                    spec_approval_id,
                    "spec_approval_id",
                ),
            }
        )

    artifact: dict[str, Any] = {
        "artifact_id": PRIVATE_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "approved",
        "policy_id": POLICY_ID,
        "policy_fingerprint": POLICY_FINGERPRINT,
        "identity_scope": identity_scope,
        "asset_binding": {
            "asset_id": asset_id,
            "asset_content_hash": asset_content_hash,
            "asset_fingerprint": asset_fingerprint,
        },
        "source_fingerprint": source_fingerprint,
        "permission_fingerprint": permission_fingerprint,
        "approval": approval,
    }
    artifact["attestation_fingerprint"] = _payload_fingerprint(
        artifact,
        "attestation_fingerprint",
    )
    validate_private_identity_scope_attestation(artifact)
    return artifact


def build_safe_identity_scope_report(
    artifact: Mapping[str, Any],
    *,
    private_artifact_bytes: bytes,
) -> dict[str, Any]:
    """Project one validated private attestation to hash/count/status fields."""

    validate_private_identity_scope_attestation(artifact)
    if _canonical_json_bytes(artifact) != private_artifact_bytes:
        raise IdentityScopeAttestationError("attestation_private_bytes_noncanonical")
    scope = artifact["identity_scope"]
    approval = artifact["approval"]
    mode = scope["mode"]
    report: dict[str, Any] = {
        "artifact_id": SAFE_REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "attestation_status": "approved",
        "immutability_status": "sealed_no_overwrite",
        "identity_scope_mode_status": mode,
        "tenant_dimension_status": (
            "explicitly_bound" if mode == TENANT_WORKSPACE_MODE else "not_modeled_not_fabricated"
        ),
        "operator_approval_status": "passed_explicit",
        "spec_approval_status": (
            "passed_explicit" if mode == WORKSPACE_ONLY_MODE else "not_required_for_mode"
        ),
        "policy_fingerprint": artifact["policy_fingerprint"],
        "attestation_fingerprint": artifact["attestation_fingerprint"],
        "private_artifact_byte_sha256": _sha256_bytes(private_artifact_bytes),
        "identity_scope_fingerprint": _fingerprint_json(scope),
        "workspace_fingerprint": _fingerprint_json(scope["workspace_id"]),
        "asset_id_fingerprint": _fingerprint_json(artifact["asset_binding"]["asset_id"]),
        "asset_content_hash": artifact["asset_binding"]["asset_content_hash"],
        "asset_fingerprint": artifact["asset_binding"]["asset_fingerprint"],
        "source_fingerprint": artifact["source_fingerprint"],
        "permission_fingerprint": artifact["permission_fingerprint"],
        "approver_actor_fingerprint": _fingerprint_json(approval["approver_actor"]),
        "authority_source_fingerprint": _fingerprint_json(approval["authority_source"]),
        "approved_at_fingerprint": _fingerprint_json(approval["approved_at"]),
        "reason_fingerprint": _fingerprint_json(approval["reason"]),
        "counts": {
            "approved_scope_count": 1,
            "asset_binding_count": 1,
            "operator_approval_count": 1,
            "spec_approval_count": int(mode == WORKSPACE_ONLY_MODE),
            "tenant_binding_count": int(mode == TENANT_WORKSPACE_MODE),
            "workspace_binding_count": 1,
        },
    }
    report["report_fingerprint"] = _payload_fingerprint(report, "report_fingerprint")
    validate_safe_identity_scope_report(
        report,
        private_artifact_bytes=private_artifact_bytes,
    )
    return report


def validate_private_identity_scope_attestation(
    artifact: Mapping[str, Any],
) -> None:
    """Validate schema, approval semantics, bindings, and self fingerprint."""

    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "policy_id",
        "policy_fingerprint",
        "identity_scope",
        "asset_binding",
        "source_fingerprint",
        "permission_fingerprint",
        "approval",
        "attestation_fingerprint",
    }
    if set(artifact) != expected_keys:
        raise IdentityScopeAttestationError("attestation_fields_invalid")
    if (
        artifact.get("artifact_id") != PRIVATE_ARTIFACT_ID
        or artifact.get("schema_version") != SCHEMA_VERSION
        or artifact.get("status") != "approved"
        or artifact.get("policy_id") != POLICY_ID
        or artifact.get("policy_fingerprint") != POLICY_FINGERPRINT
    ):
        raise IdentityScopeAttestationError("attestation_contract_invalid")
    if artifact.get("attestation_fingerprint") != _payload_fingerprint(
        artifact,
        "attestation_fingerprint",
    ):
        raise IdentityScopeAttestationError("attestation_self_fingerprint_invalid")

    scope = _require_mapping(artifact.get("identity_scope"), "identity_scope_invalid")
    mode = scope.get("mode")
    if mode == TENANT_WORKSPACE_MODE:
        if set(scope) != {"mode", "workspace_id", "tenant_id"}:
            raise IdentityScopeAttestationError("tenant_workspace_scope_fields_invalid")
        _require_stable_id(scope.get("tenant_id"), "tenant_id")
    elif mode == WORKSPACE_ONLY_MODE:
        if set(scope) != {"mode", "workspace_id"} or "tenant_id" in scope:
            raise IdentityScopeAttestationError("workspace_only_tenant_fabrication")
    else:
        raise IdentityScopeAttestationError("identity_scope_mode_invalid")
    workspace_id = _require_stable_id(scope.get("workspace_id"), "workspace_id")

    asset = _require_mapping(artifact.get("asset_binding"), "asset_binding_invalid")
    if set(asset) != {"asset_id", "asset_content_hash", "asset_fingerprint"}:
        raise IdentityScopeAttestationError("asset_binding_invalid")
    asset_id = _require_stable_id(asset.get("asset_id"), "asset_id")
    asset_content_hash = _require_sha256(
        asset.get("asset_content_hash"),
        "asset_content_hash_invalid",
    )
    permission_fingerprint = _require_sha256(
        artifact.get("permission_fingerprint"),
        "permission_fingerprint_invalid",
    )
    _require_sha256(artifact.get("source_fingerprint"), "source_fingerprint_invalid")
    if asset.get("asset_fingerprint") != _fingerprint_json(
        {
            "asset_id": asset_id,
            "asset_content_hash": asset_content_hash,
            "workspace_id": workspace_id,
            "permission_fingerprint": permission_fingerprint,
        }
    ):
        raise IdentityScopeAttestationError("asset_fingerprint_invalid")

    approval = _require_mapping(artifact.get("approval"), "approval_invalid")
    common_approval_keys = {
        "operator_approved",
        "approver_actor",
        "authority_source",
        "approved_at",
        "reason",
    }
    expected_approval_keys = (
        common_approval_keys
        if mode == TENANT_WORKSPACE_MODE
        else common_approval_keys | {"approval_kind", "spec_approval_id"}
    )
    if set(approval) != expected_approval_keys or approval.get("operator_approved") is not True:
        raise IdentityScopeAttestationError("operator_approval_missing")
    _require_stable_id(approval.get("approver_actor"), "approver_actor")
    _require_stable_id(approval.get("authority_source"), "authority_source")
    _require_explicit_timestamp(approval.get("approved_at"))
    _require_reason(approval.get("reason"))
    if mode == WORKSPACE_ONLY_MODE and (
        approval.get("approval_kind") != SPEC_OPERATOR_APPROVAL_KIND
        or not _require_stable_id(approval.get("spec_approval_id"), "spec_approval_id")
    ):
        raise IdentityScopeAttestationError("workspace_only_spec_approval_missing")


def validate_safe_identity_scope_report(
    report: Mapping[str, Any],
    *,
    private_artifact_bytes: bytes,
) -> None:
    """Validate the safe report and its private byte binding."""

    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "attestation_status",
        "immutability_status",
        "identity_scope_mode_status",
        "tenant_dimension_status",
        "operator_approval_status",
        "spec_approval_status",
        "policy_fingerprint",
        "attestation_fingerprint",
        "private_artifact_byte_sha256",
        "identity_scope_fingerprint",
        "workspace_fingerprint",
        "asset_id_fingerprint",
        "asset_content_hash",
        "asset_fingerprint",
        "source_fingerprint",
        "permission_fingerprint",
        "approver_actor_fingerprint",
        "authority_source_fingerprint",
        "approved_at_fingerprint",
        "reason_fingerprint",
        "counts",
        "report_fingerprint",
    }
    if set(report) != expected_keys:
        raise IdentityScopeAttestationError("safe_report_fields_invalid")
    if (
        report.get("artifact_id") != SAFE_REPORT_ARTIFACT_ID
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("status") != "passed"
        or report.get("attestation_status") != "approved"
        or report.get("immutability_status") != "sealed_no_overwrite"
        or report.get("operator_approval_status") != "passed_explicit"
    ):
        raise IdentityScopeAttestationError("safe_report_status_invalid")
    for key, value in report.items():
        if key.endswith("_fingerprint") or key.endswith("_sha256") or key.endswith("_hash"):
            _require_sha256(value, "safe_report_hash_invalid")
    if report.get("private_artifact_byte_sha256") != _sha256_bytes(private_artifact_bytes):
        raise IdentityScopeAttestationError("safe_report_private_byte_seal_mismatch")
    private = _decode_json_object(
        private_artifact_bytes,
        "safe_report_private_artifact_invalid",
    )
    validate_private_identity_scope_attestation(private)
    # Bind every public projection explicitly without recursively rebuilding it.
    scope = private["identity_scope"]
    approval = private["approval"]
    expected_bindings = {
        "policy_fingerprint": private["policy_fingerprint"],
        "attestation_fingerprint": private["attestation_fingerprint"],
        "identity_scope_fingerprint": _fingerprint_json(scope),
        "workspace_fingerprint": _fingerprint_json(scope["workspace_id"]),
        "asset_id_fingerprint": _fingerprint_json(private["asset_binding"]["asset_id"]),
        "asset_content_hash": private["asset_binding"]["asset_content_hash"],
        "asset_fingerprint": private["asset_binding"]["asset_fingerprint"],
        "source_fingerprint": private["source_fingerprint"],
        "permission_fingerprint": private["permission_fingerprint"],
        "approver_actor_fingerprint": _fingerprint_json(approval["approver_actor"]),
        "authority_source_fingerprint": _fingerprint_json(approval["authority_source"]),
        "approved_at_fingerprint": _fingerprint_json(approval["approved_at"]),
        "reason_fingerprint": _fingerprint_json(approval["reason"]),
    }
    if any(report.get(key) != value for key, value in expected_bindings.items()):
        raise IdentityScopeAttestationError("safe_report_private_binding_drift")
    mode = scope["mode"]
    expected_statuses = {
        "identity_scope_mode_status": mode,
        "tenant_dimension_status": (
            "explicitly_bound" if mode == TENANT_WORKSPACE_MODE else "not_modeled_not_fabricated"
        ),
        "spec_approval_status": (
            "passed_explicit" if mode == WORKSPACE_ONLY_MODE else "not_required_for_mode"
        ),
    }
    if any(report.get(key) != value for key, value in expected_statuses.items()):
        raise IdentityScopeAttestationError("safe_report_scope_status_drift")
    expected_counts = {
        "approved_scope_count": 1,
        "asset_binding_count": 1,
        "operator_approval_count": 1,
        "spec_approval_count": int(mode == WORKSPACE_ONLY_MODE),
        "tenant_binding_count": int(mode == TENANT_WORKSPACE_MODE),
        "workspace_binding_count": 1,
    }
    if report.get("counts") != expected_counts:
        raise IdentityScopeAttestationError("safe_report_count_drift")
    if report.get("report_fingerprint") != _payload_fingerprint(
        report,
        "report_fingerprint",
    ):
        raise IdentityScopeAttestationError("safe_report_fingerprint_invalid")
    _assert_hash_count_status_only(report)


def create_identity_scope_attestation_artifacts(
    *,
    output_root: Path,
    mode: str,
    workspace_id: str,
    tenant_id: str | None,
    asset_id: str,
    asset_content_hash: str,
    source_fingerprint: str,
    permission_fingerprint: str,
    approver_actor: str,
    authority_source: str,
    approved_at: str,
    reason: str,
    operator_approved: bool,
    spec_approval_id: str | None,
    _write_staged_file: Callable[[Path, bytes], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build and atomically publish one immutable private/safe pair."""

    if output_root.exists() or output_root.is_symlink():
        raise IdentityScopeAttestationError("immutable_output_already_exists")
    private = build_identity_scope_attestation(
        mode=mode,
        workspace_id=workspace_id,
        tenant_id=tenant_id,
        asset_id=asset_id,
        asset_content_hash=asset_content_hash,
        source_fingerprint=source_fingerprint,
        permission_fingerprint=permission_fingerprint,
        approver_actor=approver_actor,
        authority_source=authority_source,
        approved_at=approved_at,
        reason=reason,
        operator_approved=operator_approved,
        spec_approval_id=spec_approval_id,
    )
    private_bytes = _canonical_json_bytes(private)
    safe = build_safe_identity_scope_report(
        private,
        private_artifact_bytes=private_bytes,
    )
    safe_bytes = _canonical_json_bytes(safe)
    _persist_atomic_artifact_directory(
        output_root=output_root,
        files={
            PRIVATE_ARTIFACT_FILENAME: private_bytes,
            SAFE_REPORT_FILENAME: safe_bytes,
        },
        write_staged_file=_write_staged_file or _write_file_exclusive,
    )
    persisted_private = load_identity_scope_attestation(
        output_root / PRIVATE_ARTIFACT_FILENAME,
        expected_sha256=_sha256_bytes(private_bytes),
    )
    persisted_safe_bytes = _read_regular_file(
        output_root / SAFE_REPORT_FILENAME,
        maximum_bytes=_MAX_INPUT_BYTES,
        reason_code="safe_report_round_trip_failed",
    )
    persisted_safe = _decode_json_object(
        persisted_safe_bytes,
        "safe_report_round_trip_failed",
    )
    validate_safe_identity_scope_report(
        persisted_safe,
        private_artifact_bytes=private_bytes,
    )
    if persisted_private != private or persisted_safe != safe:
        raise IdentityScopeAttestationError("attestation_round_trip_failed")
    return persisted_private, persisted_safe


def load_identity_scope_attestation(
    path: Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    """Load one exact sealed private attestation for downstream intake."""

    _require_sha256(expected_sha256, "expected_attestation_sha256_invalid")
    raw = _read_regular_file(
        path,
        maximum_bytes=_MAX_INPUT_BYTES,
        reason_code="identity_scope_attestation_unavailable",
    )
    if _sha256_bytes(raw) != expected_sha256:
        raise IdentityScopeAttestationError("identity_scope_attestation_byte_seal_mismatch")
    artifact = _decode_json_object(raw, "identity_scope_attestation_json_invalid")
    if _canonical_json_bytes(artifact) != raw:
        raise IdentityScopeAttestationError("identity_scope_attestation_noncanonical")
    validate_private_identity_scope_attestation(artifact)
    return artifact


def _validate_mode_inputs(
    *,
    mode: str,
    tenant_id: str | None,
    operator_approved: bool,
    spec_approval_id: str | None,
) -> None:
    if mode not in _APPROVED_MODES:
        raise IdentityScopeAttestationError("identity_scope_mode_invalid")
    if operator_approved is not True:
        raise IdentityScopeAttestationError("operator_approval_missing")
    if mode == TENANT_WORKSPACE_MODE:
        _require_stable_id(tenant_id, "tenant_id")
        if spec_approval_id is not None:
            raise IdentityScopeAttestationError("tenant_mode_spec_approval_not_allowed")
    elif tenant_id is not None:
        raise IdentityScopeAttestationError("workspace_only_tenant_fabrication")
    elif spec_approval_id is None:
        raise IdentityScopeAttestationError("workspace_only_spec_approval_missing")


def _require_mapping(value: Any, reason_code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IdentityScopeAttestationError(reason_code)
    return value


def _require_sha256(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise IdentityScopeAttestationError(reason_code)
    return value


def _require_stable_id(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not _STABLE_ID_RE.fullmatch(value)
        or value.strip().casefold() in _PLACEHOLDERS
    ):
        raise IdentityScopeAttestationError(f"{field_name}_invalid")
    return value


def _require_reason(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value.strip()) < 12
        or value.strip().casefold() in _PLACEHOLDERS
        or "\x00" in value
    ):
        raise IdentityScopeAttestationError("reason_invalid")
    return value


def _require_explicit_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise IdentityScopeAttestationError("approved_at_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IdentityScopeAttestationError("approved_at_invalid") from exc
    if parsed.utcoffset() is None:
        raise IdentityScopeAttestationError("approved_at_timezone_missing")
    return value


def _payload_fingerprint(value: Mapping[str, Any], field_name: str) -> str:
    return _fingerprint_json({key: item for key, item in value.items() if key != field_name})


def _decode_json_object(raw: bytes, reason_code: str) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise IdentityScopeAttestationError(reason_code) from exc
    if type(value) is not dict:
        raise IdentityScopeAttestationError(reason_code)
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _read_regular_file(path: Path, *, maximum_bytes: int, reason_code: str) -> bytes:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
            raise OSError
        return path.read_bytes()
    except OSError as exc:
        raise IdentityScopeAttestationError(reason_code) from exc


def _persist_atomic_artifact_directory(
    *,
    output_root: Path,
    files: Mapping[str, bytes],
    write_staged_file: Callable[[Path, bytes], None],
) -> None:
    if output_root.exists() or output_root.is_symlink():
        raise IdentityScopeAttestationError("immutable_output_already_exists")
    try:
        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output_root.name}.staging-",
                dir=output_root.parent,
            )
        )
    except OSError as exc:
        raise IdentityScopeAttestationError("attestation_staging_unavailable") from exc
    try:
        for filename, payload in files.items():
            write_staged_file(staging / filename, payload)
        _fsync_directory(staging)
        _rename_directory_no_replace(staging, output_root)
        _fsync_directory(output_root.parent)
    except IdentityScopeAttestationError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise IdentityScopeAttestationError("atomic_attestation_persistence_failed") from exc


def _write_file_exclusive(path: Path, payload: bytes) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    except OSError as exc:
        raise IdentityScopeAttestationError("staged_attestation_write_failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _rename_directory_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise IdentityScopeAttestationError("atomic_no_replace_unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise IdentityScopeAttestationError("immutable_output_already_exists")
    raise IdentityScopeAttestationError("atomic_no_replace_failed")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _assert_hash_count_status_only(value: Any, *, key: str = "root") -> None:
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            if child_key in {"artifact_id", "schema_version"}:
                continue
            if child_key == "counts":
                if not isinstance(child, Mapping) or any(
                    not isinstance(item, int) or isinstance(item, bool) or item < 0
                    for item in child.values()
                ):
                    raise IdentityScopeAttestationError("safe_report_counts_invalid")
                continue
            if child_key.endswith(("_fingerprint", "_sha256", "_hash")):
                _require_sha256(child, "safe_report_hash_invalid")
                continue
            if child_key.endswith("_status") or child_key == "status":
                if not isinstance(child, str) or not child:
                    raise IdentityScopeAttestationError("safe_report_status_invalid")
                continue
            raise IdentityScopeAttestationError("safe_report_non_safe_field")
        return
    raise IdentityScopeAttestationError(f"safe_report_{key}_invalid")


def _safe_error_payload(reason_code: str) -> dict[str, Any]:
    return {
        "artifact_id": ERROR_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "reason_fingerprint": _fingerprint_json(reason_code),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--mode", choices=sorted(_APPROVED_MODES), required=True)
    create.add_argument("--workspace-id", required=True)
    create.add_argument("--tenant-id")
    create.add_argument("--asset-id", required=True)
    create.add_argument("--asset-content-hash", required=True)
    create.add_argument("--source-fingerprint", required=True)
    create.add_argument("--permission-fingerprint", required=True)
    create.add_argument("--approver-actor", required=True)
    create.add_argument("--authority-source", required=True)
    create.add_argument("--approved-at", required=True)
    create.add_argument("--reason", required=True)
    create.add_argument("--operator-approved", action="store_true")
    create.add_argument("--spec-approval-id")
    create.add_argument("--output-root", type=Path, required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--attestation", type=Path, required=True)
    validate.add_argument("--expected-attestation-sha256", required=True)
    validate.add_argument("--safe-report", type=Path, required=True)
    validate.add_argument("--expected-safe-report-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            _, safe = create_identity_scope_attestation_artifacts(
                output_root=args.output_root,
                mode=args.mode,
                workspace_id=args.workspace_id,
                tenant_id=args.tenant_id,
                asset_id=args.asset_id,
                asset_content_hash=args.asset_content_hash,
                source_fingerprint=args.source_fingerprint,
                permission_fingerprint=args.permission_fingerprint,
                approver_actor=args.approver_actor,
                authority_source=args.authority_source,
                approved_at=args.approved_at,
                reason=args.reason,
                operator_approved=args.operator_approved,
                spec_approval_id=args.spec_approval_id,
            )
        else:
            private = load_identity_scope_attestation(
                args.attestation,
                expected_sha256=args.expected_attestation_sha256,
            )
            safe_bytes = _read_regular_file(
                args.safe_report,
                maximum_bytes=_MAX_INPUT_BYTES,
                reason_code="safe_report_unavailable",
            )
            _require_sha256(
                args.expected_safe_report_sha256,
                "expected_safe_report_sha256_invalid",
            )
            if _sha256_bytes(safe_bytes) != args.expected_safe_report_sha256:
                raise IdentityScopeAttestationError("safe_report_byte_seal_mismatch")
            safe = _decode_json_object(safe_bytes, "safe_report_json_invalid")
            validate_safe_identity_scope_report(
                safe,
                private_artifact_bytes=_canonical_json_bytes(private),
            )
    except IdentityScopeAttestationError as exc:
        print(
            json.dumps(
                _safe_error_payload(exc.reason_code),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    print(json.dumps(safe, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
