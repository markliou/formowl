#!/usr/bin/env python3
"""Run a clean-temp connected operator CLI journey against live PostgreSQL."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "python").is_dir():
    sys.path.insert(0, str(ROOT / "python"))

from formowl_core import write_json_atomic  # noqa: E402
from formowl_evidence import issue20_implementation_contract_hash  # noqa: E402


ARTIFACT_ID = "formowl_connected_operator_postgres_live_journey_v2"
DEFAULT_OUTPUT = Path("/tmp/formowl-connected-operator-postgres-live-journey.json")
DEFAULT_EXECUTION_AUTHORITY_OUTPUT = Path(
    "/tmp/formowl-connected-operator-postgres-live-journey-authority.json"
)
DEFAULT_EXECUTION_AUTHORITY_PIN_OUTPUT = Path(
    "/tmp/formowl-connected-operator-postgres-live-journey-authority-pin.json"
)
PINNED_POSTGRES_IMAGE = (
    "pgvector/pgvector@sha256:" "131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6"
)
DEFAULT_POSTGRES_IMAGE = PINNED_POSTGRES_IMAGE
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ED25519_PUBLIC_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_ED25519_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$")
_PUBLIC_PROCESS_ERROR_CODES = frozenset(
    {
        "connected_invitation_failed",
        "operator_last_owner_removal_denied",
        "operator_unauthorized",
    }
)
EXECUTION_AUTHORITY_ARTIFACT_ID = "formowl_operator_v2_execution_authority_v1"
EXECUTION_AUTHORITY_PIN_ARTIFACT_ID = "formowl_operator_v2_execution_authority_pin_v1"
EXECUTION_AUTHORITY_PIN_BINDING_TYPE = "operator_v2_pre_run_execution_authority_pin_v1"
EXECUTION_RECEIPT_ARTIFACT_ID = "formowl_operator_v2_execution_receipt_v1"
EXECUTION_RECEIPT_BINDING_TYPE = "operator_v2_execution_receipt_payload_v1"
FAILURE_DIAGNOSTIC_ARTIFACT_ID = (
    "formowl_connected_operator_postgres_live_journey_failure_diagnostic_v1"
)
FAILURE_DIAGNOSTIC_STAGES = (
    "inside_migration",
    "inside_operator_commands",
    "inside_report",
    "inside_runtime_setup",
    "inside_seed",
    "inside_verification",
    "outer_authority",
    "outer_inner_journey",
    "outer_postgresql",
    "outer_report",
    "outer_runtime_cleanup",
    "outer_runtime_setup",
    "outer_secret_set",
)
_FAILURE_STAGE_HANDOFF_MODE = 0o444
_FAILURE_STAGE_HANDOFF_OWNER_UID = 10001
_FAILURE_STAGE_HANDOFF_OWNER_GID = 10001
_FAILURE_STAGE_HANDOFF_MAX_BYTES = 2048
_REPORT_HANDOFF_INITIAL_MODE = 0o200
_REPORT_HANDOFF_MODE = 0o444
_REPORT_HANDOFF_MAX_BYTES = 65536
_RUNTIME_DATA_CLEANUP_CODE = """\
import os
import shutil
import sys

root = sys.argv[1]
for entry in os.scandir(root):
    path = entry.path
    if entry.is_dir(follow_symlinks=False):
        shutil.rmtree(path)
    else:
        os.unlink(path)
"""
_IMPLEMENTATION_CONTRACT_HASH_ENV = "FORMOWL_OPERATOR_JOURNEY_IMPLEMENTATION_CONTRACT_HASH"
_RUNTIME_IMAGE_ID_ENV = "FORMOWL_OPERATOR_JOURNEY_RUNTIME_IMAGE_ID"
_RUNTIME_IMAGE_ID_HASH_ENV = "FORMOWL_OPERATOR_JOURNEY_RUNTIME_IMAGE_ID_HASH"
_SECRET_CONTRACT_HASH_ENV = "FORMOWL_OPERATOR_JOURNEY_SECRET_CONTRACT_HASH"
_WORKSPACE_ID = "workspace_operator_live_001"
_BOOTSTRAP_WORKSPACE_ID = "workspace_operator_bootstrap_001"
_OWNER_USER_ID = "user_operator_owner_001"
_MEMBER_USER_ID = "user_operator_member_001"
_MEMBER_SESSION_IDS = (
    "oauthsid_operator_member_001",
    "oauthsid_operator_member_002",
)
_LAUNCHER_CAPABILITIES = ("CHOWN", "DAC_READ_SEARCH", "SETPCAP", "SETGID", "SETUID")
_OPERATOR_ACTIONS = (
    "oauth_owner_bootstrap_created",
    "oauth_invitation_create",
    "oauth_token_session_revoked",
    "operator_user_lookup",
    "operator_user_list",
    "operator_token_session_lookup",
    "operator_token_session_list",
    "operator_workspace_member_remove",
    "operator_workspace_member_restore",
)
_FORBIDDEN_REPORT_TEXT = (
    "@example.test",
    "access_token",
    "authorization_code",
    "bearer ",
    "client_secret",
    "database-dsn",
    "database_dsn",
    "google-subject",
    "id_token",
    "postgres-password",
    "postgresql://",
    "private operator journey",
    "private_key",
    "signing-current",
    "state-encryption-key",
    "state_encryption_key",
    "token_jti",
    "/run/secrets/",
    "/tmp/formowl-operator",
    "/workspace/",
    "select ",
    "insert ",
    "update ",
    "delete ",
)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


POSTGRES_IMAGE_DIGEST_HASH = _sha256_json(
    {
        "binding_type": "operator_postgres_image_digest_v1",
        "pinned_image": PINNED_POSTGRES_IMAGE,
    }
)


def create_execution_authority(
    *,
    implementation_contract_hash: str,
    runtime_image_id_hash: str,
    journey_script_hash: str,
    campaign_nonce: bytes | None = None,
    signing_key: Ed25519PrivateKey | None = None,
) -> tuple[dict[str, Any], Ed25519PrivateKey]:
    """Create the pre-run public authority for one v2 operator campaign."""

    for value in (
        implementation_contract_hash,
        runtime_image_id_hash,
        journey_script_hash,
    ):
        if _SHA256_RE.fullmatch(value) is None:
            raise RuntimeError("operator_journey_execution_authority_invalid")
    nonce = secrets.token_bytes(32) if campaign_nonce is None else campaign_nonce
    if not isinstance(nonce, bytes) or len(nonce) < 32:
        raise RuntimeError("operator_journey_execution_authority_invalid")
    private_key = Ed25519PrivateKey.generate() if signing_key is None else signing_key
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    authority = {
        "artifact_id": EXECUTION_AUTHORITY_ARTIFACT_ID,
        "schema_version": 1,
        "campaign_nonce_hash": _sha256_bytes(b"formowl-operator-v2-campaign\x00" + nonce),
        "receipt_public_key_hex": public_key.hex(),
        "receipt_public_key_hash": _sha256_bytes(public_key),
        "implementation_contract_hash": implementation_contract_hash,
        "runtime_image_id_hash": runtime_image_id_hash,
        "journey_script_hash": journey_script_hash,
        "postgres_image_digest_hash": POSTGRES_IMAGE_DIGEST_HASH,
    }
    return authority, private_key


def create_execution_authority_pin(
    execution_authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the independent public pin persisted before the raw v2 journey."""

    authority = dict(execution_authority)
    blockers = _execution_authority_blockers(authority)
    if blockers:
        raise RuntimeError("operator_journey_execution_authority_invalid")
    return {
        "artifact_id": EXECUTION_AUTHORITY_PIN_ARTIFACT_ID,
        "schema_version": 1,
        "binding_type": EXECUTION_AUTHORITY_PIN_BINDING_TYPE,
        "execution_authority_hash": _sha256_json(authority),
        "campaign_nonce_hash": authority["campaign_nonce_hash"],
        "receipt_public_key_hash": authority["receipt_public_key_hash"],
        "implementation_contract_hash": authority["implementation_contract_hash"],
        "runtime_image_id_hash": authority["runtime_image_id_hash"],
        "journey_script_hash": authority["journey_script_hash"],
        "postgres_image_digest_hash": authority["postgres_image_digest_hash"],
    }


def _execution_receipt_payload(
    report_body: Mapping[str, Any],
    execution_authority: Mapping[str, Any],
    execution_authority_pin: Mapping[str, Any],
) -> dict[str, Any]:
    output_hashes = report_body.get("operator_output_hashes")
    if not isinstance(output_hashes, Mapping):
        raise RuntimeError("operator_journey_execution_receipt_invalid")
    return {
        "binding_type": EXECUTION_RECEIPT_BINDING_TYPE,
        "execution_authority_hash": _sha256_json(dict(execution_authority)),
        "execution_authority_pin_hash": _sha256_json(dict(execution_authority_pin)),
        "campaign_nonce_hash": execution_authority.get("campaign_nonce_hash"),
        "unsigned_report_hash": _sha256_json(dict(report_body)),
        "implementation_contract_hash": report_body.get("implementation_contract_hash"),
        "runtime_image_id_hash": report_body.get("runtime_image_id_hash"),
        "journey_script_hash": report_body.get("journey_script_hash"),
        "postgres_image_digest_hash": execution_authority.get("postgres_image_digest_hash"),
        "operator_output_set_hash": _sha256_json(dict(sorted(output_hashes.items()))),
        "operator_audit_contract_hash": output_hashes.get("operator-audit-contract"),
        "operator_rollback_state_hash": output_hashes.get("operator-rollback-state"),
    }


def attach_execution_receipt(
    report_body: Mapping[str, Any],
    execution_authority: Mapping[str, Any],
    execution_authority_pin: Mapping[str, Any],
    signing_key: Ed25519PrivateKey,
) -> dict[str, Any]:
    """Sign exact v2 outputs after the trusted outer journey has executed them."""

    body = dict(report_body)
    if body.get("schema_version") != 2 or "execution_receipt" in body:
        raise RuntimeError("operator_journey_execution_receipt_invalid")
    authority = dict(execution_authority)
    if any(
        authority.get(field) != body.get(field)
        for field in (
            "implementation_contract_hash",
            "runtime_image_id_hash",
            "journey_script_hash",
        )
    ):
        raise RuntimeError("operator_journey_execution_authority_mismatch")
    pin_validation = validate_execution_authority_pin(authority, execution_authority_pin)
    if not pin_validation["passed"]:
        raise RuntimeError("operator_journey_execution_authority_pin_mismatch")
    payload = _execution_receipt_payload(body, authority, execution_authority_pin)
    payload_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    signed = dict(body)
    signed["execution_receipt"] = {
        "artifact_id": EXECUTION_RECEIPT_ARTIFACT_ID,
        "schema_version": 1,
        **payload,
        "signed_payload_hash": _sha256_bytes(payload_bytes),
        "signature_hex": signing_key.sign(payload_bytes).hex(),
    }
    return signed


def _execution_authority_blockers(execution_authority: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    authority = dict(execution_authority)
    expected_authority_keys = {
        "artifact_id",
        "schema_version",
        "campaign_nonce_hash",
        "receipt_public_key_hex",
        "receipt_public_key_hash",
        "implementation_contract_hash",
        "runtime_image_id_hash",
        "journey_script_hash",
        "postgres_image_digest_hash",
    }
    if set(authority) != expected_authority_keys:
        blockers.append("operator execution authority keys are invalid")
    if (
        authority.get("artifact_id") != EXECUTION_AUTHORITY_ARTIFACT_ID
        or authority.get("schema_version") != 1
    ):
        blockers.append("operator execution authority identity is invalid")
    for field in (
        "campaign_nonce_hash",
        "receipt_public_key_hash",
        "implementation_contract_hash",
        "runtime_image_id_hash",
        "journey_script_hash",
        "postgres_image_digest_hash",
    ):
        if (
            not isinstance(authority.get(field), str)
            or _SHA256_RE.fullmatch(str(authority.get(field))) is None
        ):
            blockers.append(f"operator execution authority hash is invalid: {field}")
    public_key_hex = authority.get("receipt_public_key_hex")
    if (
        not isinstance(public_key_hex, str)
        or _ED25519_PUBLIC_KEY_RE.fullmatch(public_key_hex) is None
    ):
        blockers.append("operator execution authority public key is invalid")
    else:
        public_key_bytes = bytes.fromhex(public_key_hex)
        if authority.get("receipt_public_key_hash") != _sha256_bytes(public_key_bytes):
            blockers.append("operator execution authority public key binding is invalid")
    if authority.get("postgres_image_digest_hash") != POSTGRES_IMAGE_DIGEST_HASH:
        blockers.append("operator execution authority PostgreSQL image is stale")
    return blockers


def validate_execution_authority_pin(
    execution_authority: Mapping[str, Any],
    execution_authority_pin: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify that an authority matches the independently supplied pre-run pin."""

    authority = dict(execution_authority)
    pin = dict(execution_authority_pin)
    blockers = _execution_authority_blockers(authority)
    expected_pin_keys = {
        "artifact_id",
        "schema_version",
        "binding_type",
        "execution_authority_hash",
        "campaign_nonce_hash",
        "receipt_public_key_hash",
        "implementation_contract_hash",
        "runtime_image_id_hash",
        "journey_script_hash",
        "postgres_image_digest_hash",
    }
    if set(pin) != expected_pin_keys:
        blockers.append("operator execution authority pin keys are invalid")
    if (
        pin.get("artifact_id") != EXECUTION_AUTHORITY_PIN_ARTIFACT_ID
        or pin.get("schema_version") != 1
        or pin.get("binding_type") != EXECUTION_AUTHORITY_PIN_BINDING_TYPE
    ):
        blockers.append("operator execution authority pin identity is invalid")
    expected_bindings = {
        "execution_authority_hash": _sha256_json(authority),
        "campaign_nonce_hash": authority.get("campaign_nonce_hash"),
        "receipt_public_key_hash": authority.get("receipt_public_key_hash"),
        "implementation_contract_hash": authority.get("implementation_contract_hash"),
        "runtime_image_id_hash": authority.get("runtime_image_id_hash"),
        "journey_script_hash": authority.get("journey_script_hash"),
        "postgres_image_digest_hash": authority.get("postgres_image_digest_hash"),
    }
    for field, expected in expected_bindings.items():
        value = pin.get(field)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            blockers.append(f"operator execution authority pin hash is invalid: {field}")
        elif value != expected:
            blockers.append(f"operator execution authority pin binding mismatch: {field}")
    return {"passed": not blockers, "blockers": blockers}


def validate_execution_receipt(
    report: Mapping[str, Any],
    execution_authority: Mapping[str, Any],
    execution_authority_pin: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify a v2 report against the separately pinned campaign authority."""

    blockers: list[str] = []
    authority = dict(execution_authority)
    pin_validation = validate_execution_authority_pin(authority, execution_authority_pin)
    blockers.extend(pin_validation["blockers"])
    public_key_hex = authority.get("receipt_public_key_hex")
    body = dict(report)
    receipt = body.pop("execution_receipt", None)
    if not isinstance(receipt, Mapping):
        blockers.append("operator execution receipt is missing")
        receipt = {}
    expected_receipt_keys = {
        "artifact_id",
        "schema_version",
        "binding_type",
        "execution_authority_hash",
        "execution_authority_pin_hash",
        "campaign_nonce_hash",
        "unsigned_report_hash",
        "implementation_contract_hash",
        "runtime_image_id_hash",
        "journey_script_hash",
        "postgres_image_digest_hash",
        "operator_output_set_hash",
        "operator_audit_contract_hash",
        "operator_rollback_state_hash",
        "signed_payload_hash",
        "signature_hex",
    }
    if set(receipt) != expected_receipt_keys:
        blockers.append("operator execution receipt keys are invalid")
    if (
        receipt.get("artifact_id") != EXECUTION_RECEIPT_ARTIFACT_ID
        or receipt.get("schema_version") != 1
        or receipt.get("binding_type") != EXECUTION_RECEIPT_BINDING_TYPE
    ):
        blockers.append("operator execution receipt identity is invalid")
    try:
        expected_payload = _execution_receipt_payload(
            body,
            authority,
            execution_authority_pin,
        )
    except RuntimeError:
        expected_payload = {}
        blockers.append("operator execution receipt payload is invalid")
    for field, value in expected_payload.items():
        if receipt.get(field) != value:
            blockers.append(f"operator execution receipt binding mismatch: {field}")
    payload_bytes = json.dumps(
        expected_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if receipt.get("signed_payload_hash") != _sha256_bytes(payload_bytes):
        blockers.append("operator execution receipt payload hash is invalid")
    signature_hex = receipt.get("signature_hex")
    if not isinstance(signature_hex, str) or _ED25519_SIGNATURE_RE.fullmatch(signature_hex) is None:
        blockers.append("operator execution receipt signature is invalid")
    elif isinstance(public_key_hex, str) and _ED25519_PUBLIC_KEY_RE.fullmatch(public_key_hex):
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(
                bytes.fromhex(signature_hex),
                payload_bytes,
            )
        except (InvalidSignature, ValueError):
            blockers.append("operator execution receipt signature verification failed")
    return {"passed": not blockers, "blockers": blockers}


def _require_runtime_image_id(value: str | None) -> str:
    if value is None or _SHA256_RE.fullmatch(value) is None:
        raise RuntimeError("operator_journey_runtime_image_binding_invalid")
    return value


def _require_pinned_postgres_image(value: str) -> str:
    if value != PINNED_POSTGRES_IMAGE:
        raise RuntimeError("operator_journey_postgres_image_invalid")
    return value


def _read_built_runtime_image_id(iidfile: Path) -> str:
    try:
        value = iidfile.read_text(encoding="utf-8").strip()
    except OSError:
        raise RuntimeError("operator_journey_runtime_image_binding_missing") from None
    return _require_runtime_image_id(value)


def _require_nonroot_runtime() -> None:
    capability_fields = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
    try:
        status = {
            key.rstrip(":"): value.strip()
            for key, value in (
                line.split(maxsplit=1)
                for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines()
                if line.startswith(
                    tuple(f"{field}:" for field in capability_fields) + ("NoNewPrivs:",)
                )
            )
        }
    except (OSError, ValueError):
        raise RuntimeError("operator_journey_runtime_security_invalid") from None
    capability_set_is_empty = all(
        isinstance(value, str)
        and re.fullmatch(r"[0-9A-Fa-f]+", value) is not None
        and int(value, 16) == 0
        for value in (status.get(field) for field in capability_fields)
    )
    if (
        os.geteuid() != 10001
        or os.getegid() != 10001
        or os.getgroups()
        or not capability_set_is_empty
        or status.get("NoNewPrivs") != "1"
    ):
        raise RuntimeError("operator_journey_runtime_security_invalid")


def _parse_json_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if result.returncode != 0:
        raise RuntimeError(_safe_process_error(result))
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("operator_journey_output_invalid") from None
    if not isinstance(payload, dict):
        raise RuntimeError("operator_journey_output_invalid")
    return payload


def _safe_process_error(result: subprocess.CompletedProcess[str]) -> str:
    for line in reversed(result.stderr.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidate = payload.get("error") if isinstance(payload, Mapping) else None
        if candidate in _PUBLIC_PROCESS_ERROR_CODES:
            return candidate
    return "operator_journey_command_failed"


def _run_command(
    command: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        env=None if environ is None else dict(environ),
    )
    if check and result.returncode != 0:
        raise RuntimeError(_safe_process_error(result))
    return result


def _runtime_data_cleanup_command(
    data_dir: Path,
    runtime_image_id: str,
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--user",
        "10001:10001",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--mount",
        f"type=bind,src={data_dir},dst=/data",
        runtime_image_id,
        "python",
        "-c",
        _RUNTIME_DATA_CLEANUP_CODE,
        "/data",
    ]


def _runtime_data_directory_is_empty(data_dir: Path) -> bool:
    metadata = data_dir.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        return False
    with os.scandir(data_dir) as entries:
        return next(entries, None) is None


def _cleanup_runtime_data_and_image(
    data_dir: Path,
    runtime_image_id: str,
) -> bool:
    cleanup_failed = False
    try:
        cleanup_result = _run_command(
            _runtime_data_cleanup_command(data_dir, runtime_image_id),
            check=False,
        )
        cleanup_failed = cleanup_result.returncode != 0
    except Exception:
        cleanup_failed = True
    try:
        cleanup_failed = not _runtime_data_directory_is_empty(data_dir) or cleanup_failed
    except Exception:
        cleanup_failed = True
    try:
        image_removal = _run_command(
            ["docker", "image", "rm", "--force", runtime_image_id],
            check=False,
        )
        cleanup_failed = image_removal.returncode != 0 or cleanup_failed
    except Exception:
        cleanup_failed = True
    return not cleanup_failed


def _write_secret(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
    try:
        os.fchmod(descriptor, 0o400)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _write_failure_diagnostic(path: Path | None, stage: str) -> None:
    """Persist one finite redacted failure stage without masking the failure."""

    if path is None or stage not in FAILURE_DIAGNOSTIC_STAGES:
        return
    document = {
        "artifact_id": FAILURE_DIAGNOSTIC_ARTIFACT_ID,
        "failure_code": "stage_failed",
        "schema_version": 1,
        "stage": stage,
        "status": "failed",
    }
    payload = (
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor: int | None = None
    created_by_this_attempt = False
    created_identity: tuple[int, int, int, int] | None = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
        created_by_this_attempt = True
        os.fchmod(descriptor, 0o400)
        created_metadata = os.fstat(descriptor)
        created_identity = (
            created_metadata.st_dev,
            created_metadata.st_ino,
            created_metadata.st_uid,
            created_metadata.st_gid,
        )
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
    except Exception:
        # This is deliberately best-effort: persistence failure must never
        # replace or disclose the original journey failure. Cleanup is limited
        # to an inode created by this exact attempt; an existing path is never
        # removed or altered after O_EXCL rejects it.
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if created_by_this_attempt and created_identity is not None:
            try:
                current_metadata = path.lstat()
                current_identity = (
                    current_metadata.st_dev,
                    current_metadata.st_ino,
                    current_metadata.st_uid,
                    current_metadata.st_gid,
                )
                if (
                    stat.S_ISREG(current_metadata.st_mode)
                    and stat.S_IMODE(current_metadata.st_mode) == 0o400
                    and current_identity == created_identity
                ):
                    path.unlink()
            except OSError:
                pass
        return


def _write_failure_stage_handoff(path: Path | None, stage: str) -> None:
    """Best-effort write one cross-UID-readable inner failure stage."""

    if (
        path is None
        or type(stage) is not str
        or stage not in FAILURE_DIAGNOSTIC_STAGES
        or not stage.startswith("inside_")
    ):
        return
    document = {
        "artifact_id": FAILURE_DIAGNOSTIC_ARTIFACT_ID,
        "failure_code": "stage_failed",
        "schema_version": 1,
        "stage": stage,
        "status": "failed",
    }
    payload = (
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor: int | None = None
    created_identity: tuple[int, int, int, int] | None = None
    try:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o200,
        )
        os.fchmod(descriptor, 0o200)
        created_metadata = os.fstat(descriptor)
        created_identity = (
            created_metadata.st_dev,
            created_metadata.st_ino,
            created_metadata.st_uid,
            created_metadata.st_gid,
        )
        if (
            not stat.S_ISREG(created_metadata.st_mode)
            or stat.S_IMODE(created_metadata.st_mode) != 0o200
            or created_metadata.st_nlink != 1
        ):
            raise OSError
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, _FAILURE_STAGE_HANDOFF_MODE)
        final_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(final_metadata.st_mode)
            or stat.S_IMODE(final_metadata.st_mode) != _FAILURE_STAGE_HANDOFF_MODE
            or final_metadata.st_nlink != 1
            or final_metadata.st_size != len(payload)
            or (
                final_metadata.st_dev,
                final_metadata.st_ino,
                final_metadata.st_uid,
                final_metadata.st_gid,
            )
            != created_identity
        ):
            raise OSError
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
    except Exception:
        # A partial handoff is never promoted to a readable artifact. Cleanup
        # remains bound to the inode created by this attempt, so a replacement
        # at the same path is preserved.
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if created_identity is not None:
            try:
                current_metadata = path.lstat()
                current_identity = (
                    current_metadata.st_dev,
                    current_metadata.st_ino,
                    current_metadata.st_uid,
                    current_metadata.st_gid,
                )
                if (
                    stat.S_ISREG(current_metadata.st_mode)
                    and stat.S_IMODE(current_metadata.st_mode)
                    in (0o200, _FAILURE_STAGE_HANDOFF_MODE)
                    and current_metadata.st_nlink == 1
                    and current_identity == created_identity
                ):
                    path.unlink()
            except OSError:
                pass


def _read_failure_stage_handoff(path: Path) -> str | None:
    """Read one stable inner stage from the private cross-UID handoff."""

    descriptor: int | None = None
    validated_stage: str | None = None
    try:
        path_metadata_before = path.lstat()
        if (
            not stat.S_ISREG(path_metadata_before.st_mode)
            or path_metadata_before.st_uid != _FAILURE_STAGE_HANDOFF_OWNER_UID
            or path_metadata_before.st_gid != _FAILURE_STAGE_HANDOFF_OWNER_GID
            or stat.S_IMODE(path_metadata_before.st_mode) != _FAILURE_STAGE_HANDOFF_MODE
            or path_metadata_before.st_nlink != 1
            or not 2 <= path_metadata_before.st_size <= _FAILURE_STAGE_HANDOFF_MAX_BYTES
        ):
            return None
        identity_before = (
            path_metadata_before.st_dev,
            path_metadata_before.st_ino,
            path_metadata_before.st_uid,
            path_metadata_before.st_gid,
            stat.S_IMODE(path_metadata_before.st_mode),
            path_metadata_before.st_nlink,
            path_metadata_before.st_size,
            path_metadata_before.st_mtime_ns,
            path_metadata_before.st_ctime_ns,
        )
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        descriptor_metadata_before = os.fstat(descriptor)
        descriptor_identity_before = (
            descriptor_metadata_before.st_dev,
            descriptor_metadata_before.st_ino,
            descriptor_metadata_before.st_uid,
            descriptor_metadata_before.st_gid,
            stat.S_IMODE(descriptor_metadata_before.st_mode),
            descriptor_metadata_before.st_nlink,
            descriptor_metadata_before.st_size,
            descriptor_metadata_before.st_mtime_ns,
            descriptor_metadata_before.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(descriptor_metadata_before.st_mode)
            or descriptor_identity_before != identity_before
        ):
            return None
        remaining = descriptor_metadata_before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, remaining)
            if type(chunk) is not bytes or not chunk or len(chunk) > remaining:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1) != b"":
            return None
        payload = b"".join(chunks)
        descriptor_metadata_after = os.fstat(descriptor)
        path_metadata_after = path.lstat()
        descriptor_identity_after = (
            descriptor_metadata_after.st_dev,
            descriptor_metadata_after.st_ino,
            descriptor_metadata_after.st_uid,
            descriptor_metadata_after.st_gid,
            stat.S_IMODE(descriptor_metadata_after.st_mode),
            descriptor_metadata_after.st_nlink,
            descriptor_metadata_after.st_size,
            descriptor_metadata_after.st_mtime_ns,
            descriptor_metadata_after.st_ctime_ns,
        )
        path_identity_after = (
            path_metadata_after.st_dev,
            path_metadata_after.st_ino,
            path_metadata_after.st_uid,
            path_metadata_after.st_gid,
            stat.S_IMODE(path_metadata_after.st_mode),
            path_metadata_after.st_nlink,
            path_metadata_after.st_size,
            path_metadata_after.st_mtime_ns,
            path_metadata_after.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(descriptor_metadata_after.st_mode)
            or not stat.S_ISREG(path_metadata_after.st_mode)
            or descriptor_identity_after != identity_before
            or path_identity_after != identity_before
            or len(payload) != descriptor_metadata_before.st_size
        ):
            return None
        document = json.loads(payload.decode("utf-8"))
        if (
            type(document) is not dict
            or set(document)
            != {
                "artifact_id",
                "failure_code",
                "schema_version",
                "stage",
                "status",
            }
            or type(document.get("artifact_id")) is not str
            or document.get("artifact_id") != FAILURE_DIAGNOSTIC_ARTIFACT_ID
            or type(document.get("failure_code")) is not str
            or document.get("failure_code") != "stage_failed"
            or type(document.get("schema_version")) is not int
            or document.get("schema_version") != 1
            or type(document.get("status")) is not str
            or document.get("status") != "failed"
            or type(document.get("stage")) is not str
            or document.get("stage") not in FAILURE_DIAGNOSTIC_STAGES
            or not document["stage"].startswith("inside_")
        ):
            return None
        canonical_payload = (
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if payload != canonical_payload:
            return None
        validated_stage = document["stage"]
    except (OSError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        validated_stage = None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                validated_stage = None
    return validated_stage


def _runtime_environment() -> dict[str, str]:
    issuer = "https://operator-live.example.test"
    return {
        "FORMOWL_AUTH_MODE": "oauth_google",
        "FORMOWL_OAUTH_ISSUER": issuer,
        "FORMOWL_MCP_RESOURCE": f"{issuer}/mcp",
        "FORMOWL_CHATGPT_CLIENT_ID": "chatgpt_operator_live",
        "FORMOWL_CHATGPT_REDIRECT_URI": ("https://chatgpt.com/connector/oauth/operator-live"),
        "FORMOWL_GOOGLE_CLIENT_ID": "google_operator_live",
        "FORMOWL_GOOGLE_REDIRECT_URI": f"{issuer}/oauth/google/callback",
        "FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID": "operator_live",
        "FORMOWL_DATABASE_DSN_FILE": "/run/secrets/formowl_database_dsn",
        "FORMOWL_GOOGLE_CLIENT_SECRET_FILE": ("/run/secrets/formowl_google_client_secret"),
        "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE": ("/run/secrets/formowl_state_encryption_key"),
        "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE": ("/run/secrets/formowl_signing_key_set"),
        "FORMOWL_DATA_DIR": "/data",
        "FORMOWL_CONNECTED_HOST": "127.0.0.1",
        "FORMOWL_CONNECTED_PORT": "8000",
        "FORMOWL_LOG_LEVEL": "warning",
    }


def _runtime_secret_mounts(secret_dir: Path) -> list[str]:
    mapping = {
        "database-dsn": "formowl_database_dsn",
        "google-client-secret": "formowl_google_client_secret",
        "state-encryption-key": "formowl_state_encryption_key",
        "signing-key-set.json": "formowl_signing_key_set",
        "signing-current.pem": "formowl_signing_key_current",
        "signing-previous.pem": "formowl_signing_key_previous",
    }
    arguments: list[str] = []
    for source_name, target_name in mapping.items():
        arguments.extend(
            [
                "-v",
                f"{secret_dir / source_name}:/run/secrets/{target_name}:ro",
            ]
        )
    return arguments


def _run_operator_cli(
    arguments: Sequence[str],
    *,
    environ: Mapping[str, str],
    expected_error: str | None = None,
) -> tuple[dict[str, Any] | None, subprocess.CompletedProcess[str]]:
    result = _run_command(
        ["formowl-connected-mcp", *arguments],
        environ=environ,
        check=False,
    )
    if expected_error is None:
        return _parse_json_output(result), result
    if result.returncode == 0 or result.stdout.strip():
        raise RuntimeError("operator_journey_denial_invalid")
    try:
        payload = json.loads(result.stderr)
    except json.JSONDecodeError:
        raise RuntimeError("operator_journey_denial_invalid") from None
    if payload != {"error": expected_error, "status": "error"}:
        raise RuntimeError("operator_journey_denial_invalid")
    return None, result


def _seed_operator_records(repository: Any) -> None:
    from formowl_auth import ExternalIdentity, OAuthClientAuthorization, OAuthTokenSession
    from formowl_contract import User, WorkspaceMember

    now = datetime.now(timezone.utc).replace(microsecond=0)
    users = (
        User(
            user_id=_OWNER_USER_ID,
            display_name="Private Operator Journey Owner",
            email="operator-owner@example.test",
            status="active",
            created_at=now.isoformat(),
        ),
        User(
            user_id=_MEMBER_USER_ID,
            display_name="Private Operator Journey Member",
            email="operator-member@example.test",
            status="active",
            created_at=now.isoformat(),
        ),
    )
    memberships = (
        WorkspaceMember(
            workspace_id=_WORKSPACE_ID,
            user_id=_OWNER_USER_ID,
            role="owner",
        ),
        WorkspaceMember(
            workspace_id=_WORKSPACE_ID,
            user_id=_MEMBER_USER_ID,
            role="member",
        ),
    )
    identities = (
        ExternalIdentity(
            external_identity_id="extid_operator_owner_001",
            provider="google",
            issuer="https://accounts.google.com",
            subject="private-google-subject-operator-owner",
            user_id=_OWNER_USER_ID,
            email=users[0].email,
            email_verified=True,
            status="active",
            created_at=now.isoformat(),
            last_authenticated_at=now.isoformat(),
        ),
        ExternalIdentity(
            external_identity_id="extid_operator_member_001",
            provider="google",
            issuer="https://accounts.google.com",
            subject="private-google-subject-operator-member",
            user_id=_MEMBER_USER_ID,
            email=users[1].email,
            email_verified=True,
            status="active",
            created_at=now.isoformat(),
            last_authenticated_at=now.isoformat(),
        ),
    )
    authorizations = tuple(
        OAuthClientAuthorization(
            oauth_client_authorization_id=f"clientauth_operator_{role}_001",
            client_id="chatgpt_operator_live",
            external_identity_id=identity.external_identity_id,
            user_id=user.user_id,
            granted_scopes=("formowl.use",),
            default_workspace_id=_WORKSPACE_ID,
            created_at=now.isoformat(),
        )
        for role, identity, user in zip(
            ("owner", "member"),
            identities,
            users,
            strict=True,
        )
    )
    session_specs = (
        ("oauthsid_operator_owner_001", users[0], identities[0], authorizations[0], "a", 0),
        (_MEMBER_SESSION_IDS[0], users[1], identities[1], authorizations[1], "b", 0),
        (_MEMBER_SESSION_IDS[1], users[1], identities[1], authorizations[1], "c", 1),
    )
    sessions = tuple(
        OAuthTokenSession(
            token_session_id=session_id,
            user_id=user.user_id,
            external_identity_id=identity.external_identity_id,
            oauth_client_authorization_id=authorization.oauth_client_authorization_id,
            client_id=authorization.client_id,
            current_workspace_id=_WORKSPACE_ID,
            resource="https://operator-live.example.test/mcp",
            scopes=("formowl.use",),
            token_jti_hash="sha256:" + token_fill * 64,
            issued_at=(now + timedelta(seconds=issued_offset)).isoformat(),
            expires_at=(now + timedelta(hours=1)).isoformat(),
        )
        for session_id, user, identity, authorization, token_fill, issued_offset in session_specs
    )
    with repository.transaction() as unit:
        for user in users:
            repository.insert_user(user)
        for membership in memberships:
            repository.insert_workspace_member(membership, created_at=now.isoformat())
        for identity in identities:
            repository.insert_external_identity(identity)
        for authorization in authorizations:
            repository.insert_client_authorization(authorization)
        for session in sessions:
            repository.insert_token_session(session)
        unit.commit()


def _operator_audit_summary(
    repository: Any,
    *,
    bootstrap_invitation_id: str,
    member_invitation_id: str,
) -> dict[str, Any]:
    from formowl_graph.storage import SQLStatement

    for value in (bootstrap_invitation_id, member_invitation_id):
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is None
        ):
            raise RuntimeError("operator_journey_audit_invalid")
    rows = repository.connection.query_all(
        SQLStatement(
            sql=(
                "SELECT action, actor_type, actor_service_id, target_type, target_id, "
                "workspace_id, status, reason_code, COUNT(*) AS event_count "
                "FROM formowl_audit_log "
                "WHERE action = ANY(%(actions)s) "
                "GROUP BY action, actor_type, actor_service_id, target_type, target_id, "
                "workspace_id, status, reason_code "
                "ORDER BY action, actor_type, actor_service_id, status, reason_code, "
                "target_type, target_id, workspace_id"
            ),
            parameters={"actions": list(_OPERATOR_ACTIONS)},
        )
    )
    return _summarize_operator_audit_rows(
        rows,
        bootstrap_invitation_id=bootstrap_invitation_id,
        member_invitation_id=member_invitation_id,
    )


def _summarize_operator_audit_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    bootstrap_invitation_id: str,
    member_invitation_id: str,
) -> dict[str, Any]:
    normalized = [
        {
            "action": str(row["action"]),
            "actor_type": str(row["actor_type"]),
            "actor_service_id": row.get("actor_service_id"),
            "target_type": str(row["target_type"]),
            "target_id": str(row["target_id"]),
            "workspace_id": row.get("workspace_id"),
            "status": str(row["status"]),
            "reason_code": str(row["reason_code"]),
            "event_count": int(row["event_count"]),
        }
        for row in rows
    ]
    expected = [
        {
            "action": "oauth_invitation_create",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "workspace",
            "target_id": _WORKSPACE_ID,
            "workspace_id": _WORKSPACE_ID,
            "status": "denied",
            "reason_code": "invitation_owner_required",
            "event_count": 1,
        },
        {
            "action": "oauth_invitation_create",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "oauth_invitation",
            "target_id": member_invitation_id,
            "workspace_id": _WORKSPACE_ID,
            "status": "ok",
            "reason_code": "invitation_created",
            "event_count": 1,
        },
        {
            "action": "oauth_owner_bootstrap_created",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "oauth_owner_bootstrap",
            "target_id": bootstrap_invitation_id,
            "workspace_id": _BOOTSTRAP_WORKSPACE_ID,
            "status": "ok",
            "reason_code": "owner_bootstrap_created",
            "event_count": 1,
        },
        {
            "action": "oauth_token_session_revoked",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "oauth_token_session",
            "target_id": _MEMBER_SESSION_IDS[0],
            "workspace_id": _WORKSPACE_ID,
            "status": "ok",
            "reason_code": "operator_journey_revoked",
            "event_count": 1,
        },
        {
            "action": "operator_token_session_list",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "user",
            "target_id": _MEMBER_USER_ID,
            "workspace_id": None,
            "status": "ok",
            "reason_code": "operator_directory_allowed",
            "event_count": 2,
        },
        {
            "action": "operator_token_session_lookup",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "oauth_token_session",
            "target_id": _MEMBER_SESSION_IDS[1],
            "workspace_id": None,
            "status": "ok",
            "reason_code": "operator_directory_allowed",
            "event_count": 1,
        },
        {
            "action": "operator_user_list",
            "actor_type": "external_unauthenticated",
            "actor_service_id": None,
            "target_type": "operator_directory",
            "target_id": "operator_directory",
            "workspace_id": None,
            "status": "denied",
            "reason_code": "operator_unauthorized",
            "event_count": 1,
        },
        {
            "action": "operator_user_list",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "workspace",
            "target_id": _WORKSPACE_ID,
            "workspace_id": None,
            "status": "ok",
            "reason_code": "operator_directory_allowed",
            "event_count": 1,
        },
        {
            "action": "operator_user_lookup",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "user",
            "target_id": _OWNER_USER_ID,
            "workspace_id": None,
            "status": "ok",
            "reason_code": "operator_directory_allowed",
            "event_count": 1,
        },
        {
            "action": "operator_workspace_member_remove",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "workspace_member",
            "target_id": f"{_WORKSPACE_ID}:{_OWNER_USER_ID}",
            "workspace_id": None,
            "status": "denied",
            "reason_code": "operator_last_owner_removal_denied",
            "event_count": 1,
        },
        {
            "action": "operator_workspace_member_remove",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "workspace_member",
            "target_id": f"{_WORKSPACE_ID}:{_MEMBER_USER_ID}",
            "workspace_id": None,
            "status": "ok",
            "reason_code": "operator_directory_allowed",
            "event_count": 1,
        },
        {
            "action": "operator_workspace_member_restore",
            "actor_type": "service",
            "actor_service_id": "operator_live",
            "target_type": "workspace_member",
            "target_id": f"{_WORKSPACE_ID}:{_MEMBER_USER_ID}",
            "workspace_id": None,
            "status": "ok",
            "reason_code": "operator_directory_allowed",
            "event_count": 1,
        },
    ]
    if normalized != expected:
        raise RuntimeError("operator_journey_audit_invalid")
    total_count = sum(row["event_count"] for row in normalized)
    allowed_count = sum(
        row["event_count"]
        for row in normalized
        if row["actor_type"] == "service" and row["status"] == "ok"
    )
    denied_count = sum(row["event_count"] for row in normalized if row["status"] == "denied")
    return {
        "total_count": total_count,
        "allowed_count": allowed_count,
        "denied_count": denied_count,
        "contract_hash": _sha256_json(normalized),
    }


def _operator_member_state(repository: Any) -> dict[str, Any]:
    active = repository.get_active_workspace_member(_MEMBER_USER_ID, _WORKSPACE_ID)
    removed = repository.get_removed_workspace_member(_MEMBER_USER_ID, _WORKSPACE_ID)
    sessions = repository.list_token_sessions(_MEMBER_USER_ID, _WORKSPACE_ID)
    return {
        "active_role": active.role if active is not None else None,
        "removed_role": removed.role if removed is not None else None,
        "session_count": len(sessions),
        "revoked_session_count": sum(session.revoked_at is not None for session in sessions),
    }


class _AuditFailingRepository:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def append_audit_log(self, _audit_log: Any) -> None:
        raise RuntimeError("injected_operator_audit_failure")


def _run_operator_rollback_probe(repository: Any) -> dict[str, Any]:
    from formowl_gateway.operator import OperatorDirectory, OperatorDirectoryError
    from formowl_graph.storage import SQLStatement

    baseline_state = _operator_member_state(repository)
    baseline_audit_row = repository.connection.query_one(
        SQLStatement(sql="SELECT COUNT(*) AS event_count FROM formowl_audit_log")
    )
    if baseline_audit_row is None:
        raise RuntimeError("operator_journey_rollback_probe_invalid")
    directory = OperatorDirectory(
        repository=_AuditFailingRepository(repository),
        expected_operator_service_id="operator_live",
    )
    try:
        directory.remove_workspace_member(
            user_id=_MEMBER_USER_ID,
            workspace_id=_WORKSPACE_ID,
            operator_service_id="operator_live",
            now=datetime.now(timezone.utc),
        )
    except OperatorDirectoryError as error:
        if error.code != "operator_directory_unavailable":
            raise RuntimeError("operator_journey_rollback_probe_invalid") from None
    else:
        raise RuntimeError("operator_journey_rollback_probe_invalid")
    final_audit_row = repository.connection.query_one(
        SQLStatement(sql="SELECT COUNT(*) AS event_count FROM formowl_audit_log")
    )
    final_state = _operator_member_state(repository)
    if (
        final_audit_row is None
        or int(final_audit_row["event_count"]) != int(baseline_audit_row["event_count"])
        or final_state != baseline_state
    ):
        raise RuntimeError("operator_journey_rollback_probe_invalid")
    return {
        "probe_count": 1,
        "preserved_state_count": 1,
        "state_hash": _sha256_json(final_state),
    }


def _execute_operator_v2_commands(
    environ: Mapping[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    outputs: dict[str, dict[str, Any]] = {}
    denial_hashes: dict[str, str] = {}
    process_outputs: list[str] = []

    def success(label: str, arguments: Sequence[str]) -> dict[str, Any]:
        payload, process = _run_operator_cli(arguments, environ=environ)
        assert payload is not None
        outputs[label] = payload
        process_outputs.extend((process.stdout, process.stderr))
        return payload

    def denial(label: str, arguments: Sequence[str], expected_error: str) -> None:
        _, process = _run_operator_cli(
            arguments,
            environ=environ,
            expected_error=expected_error,
        )
        process_outputs.extend((process.stdout, process.stderr))
        denial_hashes[label] = _sha256_bytes(process.stderr.encode("utf-8"))

    bootstrap = success(
        "bootstrap-owner",
        [
            "bootstrap-owner",
            "--workspace-id",
            _BOOTSTRAP_WORKSPACE_ID,
            "--email",
            "bootstrap-owner@example.test",
            "--expires-at",
            expires_at,
            "--idempotency-key",
            "operator-journey-bootstrap-v2",
            "--operator-service-id",
            "operator_live",
        ],
    )
    invitation = success(
        "invite-member",
        [
            "invite-user",
            "--workspace-id",
            _WORKSPACE_ID,
            "--email",
            "invited-member@example.test",
            "--role",
            "member",
            "--invited-by-user-id",
            _OWNER_USER_ID,
            "--operator-service-id",
            "operator_live",
            "--intended-user-id",
            _MEMBER_USER_ID,
            "--expires-at",
            expires_at,
        ],
    )
    denial(
        "member-approval-denied",
        [
            "invite-user",
            "--workspace-id",
            _WORKSPACE_ID,
            "--email",
            "member-denied-invite@example.test",
            "--role",
            "viewer",
            "--invited-by-user-id",
            _MEMBER_USER_ID,
            "--operator-service-id",
            "operator_live",
            "--expires-at",
            expires_at,
        ],
        "connected_invitation_failed",
    )
    owner_lookup = success(
        "lookup-owner",
        [
            "lookup-user",
            "--email",
            "operator-owner@example.test",
            "--workspace-id",
            _WORKSPACE_ID,
            "--operator-service-id",
            "operator_live",
        ],
    )
    user_list = success(
        "list-users",
        [
            "list-users",
            "--workspace-id",
            _WORKSPACE_ID,
            "--operator-service-id",
            "operator_live",
        ],
    )
    sessions_before = success(
        "list-member-sessions-before",
        [
            "list-token-sessions",
            "--user-id",
            _MEMBER_USER_ID,
            "--workspace-id",
            _WORKSPACE_ID,
            "--operator-service-id",
            "operator_live",
        ],
    )
    revoked = success(
        "revoke-member-session",
        [
            "revoke-token-session",
            "--token-session-id",
            _MEMBER_SESSION_IDS[0],
            "--reason-code",
            "operator_journey_revoked",
            "--operator-service-id",
            "operator_live",
        ],
    )
    session_after_revoke = success(
        "lookup-member-session-after-revoke",
        [
            "lookup-token-session",
            "--user-id",
            _MEMBER_USER_ID,
            "--workspace-id",
            _WORKSPACE_ID,
            "--operator-service-id",
            "operator_live",
        ],
    )
    denial(
        "unauthorized-list-users",
        [
            "list-users",
            "--workspace-id",
            _WORKSPACE_ID,
            "--operator-service-id",
            "operator_removed",
        ],
        "operator_unauthorized",
    )
    denial(
        "last-owner-removal-denied",
        [
            "remove-workspace-member",
            "--user-id",
            _OWNER_USER_ID,
            "--workspace-id",
            _WORKSPACE_ID,
            "--operator-service-id",
            "operator_live",
        ],
        "operator_last_owner_removal_denied",
    )
    removed = success(
        "remove-member",
        [
            "remove-workspace-member",
            "--user-id",
            _MEMBER_USER_ID,
            "--workspace-id",
            _WORKSPACE_ID,
            "--operator-service-id",
            "operator_live",
        ],
    )
    restored = success(
        "restore-member",
        [
            "restore-workspace-member",
            "--user-id",
            _MEMBER_USER_ID,
            "--workspace-id",
            _WORKSPACE_ID,
            "--operator-service-id",
            "operator_live",
        ],
    )
    sessions_after = success(
        "list-member-sessions-after-restore",
        [
            "list-token-sessions",
            "--user-id",
            _MEMBER_USER_ID,
            "--workspace-id",
            _WORKSPACE_ID,
            "--operator-service-id",
            "operator_live",
        ],
    )

    if bootstrap.get("status") != "ok" or bootstrap.get("workspace_id") != _BOOTSTRAP_WORKSPACE_ID:
        raise RuntimeError("operator_journey_bootstrap_invalid")
    if invitation.get("status") != "ok" or invitation.get("role") != "member":
        raise RuntimeError("operator_journey_invitation_invalid")
    if owner_lookup.get("result_count") != 1:
        raise RuntimeError("operator_journey_user_lookup_invalid")
    if user_list.get("result_count") != 2:
        raise RuntimeError("operator_journey_user_list_invalid")
    if (
        sessions_before.get("result_count") != 2
        or sessions_before.get("inactive_session_count") != 0
    ):
        raise RuntimeError("operator_journey_session_list_invalid")
    if revoked != {"status": "ok", "token_session_revoked": True}:
        raise RuntimeError("operator_journey_revocation_invalid")
    if (
        session_after_revoke.get("result_count") != 1
        or session_after_revoke.get("inactive_session_count") != 1
        or session_after_revoke.get("token_session", {}).get("token_session_id")
        != _MEMBER_SESSION_IDS[1]
    ):
        raise RuntimeError("operator_journey_post_revoke_lookup_invalid")
    if removed.get("membership_removed") is not True:
        raise RuntimeError("operator_journey_member_removal_invalid")
    if restored.get("membership_restored") is not True or restored.get("role") != "member":
        raise RuntimeError("operator_journey_member_restore_invalid")
    if sessions_after.get("result_count") != 0 or sessions_after.get("inactive_session_count") != 2:
        raise RuntimeError("operator_journey_post_restore_session_invalid")
    return outputs, denial_hashes, process_outputs


def run_inside(
    output_path: Path,
    *,
    runtime_image_id: str | None,
    failure_stage_handoff_output_path: Path | None = None,
) -> dict[str, Any]:
    if (
        failure_stage_handoff_output_path is not None
        and output_path.resolve() == failure_stage_handoff_output_path.resolve()
    ):
        raise RuntimeError("operator_journey_failure_stage_handoff_output_invalid")
    try:
        environ = dict(os.environ)
        runtime_image_id = _require_runtime_image_id(runtime_image_id)
        authority_runtime_image_id = environ.get(_RUNTIME_IMAGE_ID_ENV)
        if authority_runtime_image_id is None:
            raise RuntimeError("operator_journey_runtime_image_authority_missing")
        if authority_runtime_image_id != runtime_image_id:
            raise RuntimeError("operator_journey_runtime_image_authority_mismatch")
        implementation_contract_hash = environ.get(_IMPLEMENTATION_CONTRACT_HASH_ENV)
        runtime_image_id_hash = environ.get(_RUNTIME_IMAGE_ID_HASH_ENV)
        secret_contract_hash = environ.get(_SECRET_CONTRACT_HASH_ENV)
        for value, error_code in (
            (implementation_contract_hash, "operator_journey_implementation_contract_missing"),
            (runtime_image_id_hash, "operator_journey_runtime_image_binding_missing"),
            (secret_contract_hash, "operator_journey_secret_contract_missing"),
        ):
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise RuntimeError(error_code)
        assert isinstance(implementation_contract_hash, str)
        assert isinstance(runtime_image_id_hash, str)
        assert isinstance(secret_contract_hash, str)
        if runtime_image_id_hash != _sha256_bytes(runtime_image_id.encode("utf-8")):
            raise RuntimeError("operator_journey_runtime_image_hash_mismatch")
        _require_nonroot_runtime()
        from formowl_auth.postgres import PostgreSQLOAuthRepository
        from formowl_gateway.runtime import ConnectedRuntimeConfig
    except Exception:
        _write_failure_stage_handoff(
            failure_stage_handoff_output_path,
            "inside_runtime_setup",
        )
        raise

    try:
        migration, migration_process = _run_operator_cli(
            ["migrate"],
            environ=environ,
        )
        assert migration is not None
    except Exception:
        _write_failure_stage_handoff(
            failure_stage_handoff_output_path,
            "inside_migration",
        )
        raise

    try:
        config = ConnectedRuntimeConfig.from_env_and_secrets(environ)
        repository = PostgreSQLOAuthRepository.connect(config.database_dsn)
        try:
            _seed_operator_records(repository)
        finally:
            repository.close()
    except Exception:
        _write_failure_stage_handoff(
            failure_stage_handoff_output_path,
            "inside_seed",
        )
        raise

    try:
        outputs, denial_hashes, operator_process_outputs = _execute_operator_v2_commands(environ)
        process_outputs = [
            migration_process.stdout,
            migration_process.stderr,
            *operator_process_outputs,
        ]
    except Exception:
        _write_failure_stage_handoff(
            failure_stage_handoff_output_path,
            "inside_operator_commands",
        )
        raise

    try:
        private_values = (
            "operator-owner@example.test",
            "operator-member@example.test",
            "bootstrap-owner@example.test",
            "invited-member@example.test",
            "member-denied-invite@example.test",
            "Private Operator Journey Owner",
            "Private Operator Journey Member",
            "private-google-subject-operator-owner",
            "private-google-subject-operator-member",
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
            "sha256:" + "c" * 64,
            config.database_dsn,
        )
        rendered_outputs = "\n".join(process_outputs)
        if any(value in rendered_outputs for value in private_values):
            raise RuntimeError("operator_journey_output_leak")

        repository = PostgreSQLOAuthRepository.connect(config.database_dsn)
        try:
            rollback_probe = _run_operator_rollback_probe(repository)
            audit_summary = _operator_audit_summary(
                repository,
                bootstrap_invitation_id=outputs["bootstrap-owner"].get("invitation_id"),
                member_invitation_id=outputs["invite-member"].get("invitation_id"),
            )
        finally:
            repository.close()
        output_hashes = {label: _sha256_json(payload) for label, payload in sorted(outputs.items())}
        output_hashes["operator-audit-contract"] = audit_summary["contract_hash"]
        output_hashes["operator-rollback-state"] = rollback_probe["state_hash"]
    except Exception:
        _write_failure_stage_handoff(
            failure_stage_handoff_output_path,
            "inside_verification",
        )
        raise

    try:
        report = {
            "artifact_id": ARTIFACT_ID,
            "schema_version": 2,
            "status": "passed",
            "implementation_contract_hash": implementation_contract_hash,
            "runtime_image_id_hash": runtime_image_id_hash,
            "journey_script_hash": _sha256_bytes(Path(__file__).read_bytes()),
            "secret_initialization_contract_hash": secret_contract_hash,
            "migration_result_hash": _sha256_json(migration),
            "operator_output_hashes": output_hashes,
            "operator_denial_hash": _sha256_json(dict(sorted(denial_hashes.items()))),
            "counts": {
                "fresh_postgresql_database_count": 1,
                "generated_secret_count": 6,
                "idempotent_secret_rerun_count": 1,
                "migration_command_success_count": 1,
                "operator_cli_success_count": len(outputs),
                "operator_cli_denial_count": len(denial_hashes),
                "operator_audit_total_count": audit_summary["total_count"],
                "operator_audit_allowed_count": audit_summary["allowed_count"],
                "operator_audit_denied_count": audit_summary["denied_count"],
                "runtime_image_build_count": 1,
                "owner_bootstrap_success_count": 1,
                "member_invitation_success_count": 1,
                "member_approval_denial_count": 1,
                "explicit_token_revocation_count": 1,
                "last_owner_removal_denial_count": 1,
                "membership_remove_success_count": 1,
                "membership_restore_success_count": 1,
                "post_restore_active_session_count": 0,
                "post_restore_inactive_session_count": 2,
                "transaction_rollback_probe_count": rollback_probe["probe_count"],
                "transaction_rollback_preserved_state_count": rollback_probe[
                    "preserved_state_count"
                ],
            },
            "attestations": {
                "actual_connected_cli_executed": True,
                "clean_temporary_secret_set_used": True,
                "current_runtime_image_built_from_worktree": True,
                "fresh_postgresql_database_used": True,
                "google_credential_injected_outside_initializer": True,
                "inside_probe_used_installed_runtime_package": True,
                "operator_allow_and_deny_audits_persisted": True,
                "operator_outputs_excluded_sensitive_identity_and_backend_detail": True,
                "report_contains_only_safe_status_count_and_hash_evidence": True,
                "exact_operator_lifecycle_exercised": True,
                "member_approval_denial_audited": True,
                "membership_rollback_verified": True,
                "immutable_runtime_and_postgres_images_used": True,
            },
        }
        validation = _validate_report_body(
            report,
            expected_implementation_contract_hash=implementation_contract_hash,
            expected_journey_script_hash=_sha256_bytes(Path(__file__).read_bytes()),
        )
        if not validation["passed"]:
            raise RuntimeError("operator_journey_report_invalid")
        payload = json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        if not 2 <= len(payload) <= _REPORT_HANDOFF_MAX_BYTES:
            raise RuntimeError("operator_journey_report_invalid")
        descriptor: int | None = None
        created_identity: tuple[int, int, int, int] | None = None
        try:
            descriptor = os.open(
                output_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                _REPORT_HANDOFF_INITIAL_MODE,
            )
            # Bind cleanup to the exact descriptor immediately after O_EXCL
            # creates it. If the primary descriptor metadata probe fails, the
            # still-open descriptor may recover identity for safe cleanup, but
            # the original failure remains fatal. No path lookup may establish
            # deletion authority.
            try:
                opened_metadata = os.stat(descriptor)
            except OSError as metadata_error:
                try:
                    opened_metadata = os.fstat(descriptor)
                except OSError:
                    raise metadata_error
                created_identity = (
                    opened_metadata.st_dev,
                    opened_metadata.st_ino,
                    opened_metadata.st_uid,
                    opened_metadata.st_gid,
                )
                raise metadata_error
            created_identity = (
                opened_metadata.st_dev,
                opened_metadata.st_ino,
                opened_metadata.st_uid,
                opened_metadata.st_gid,
            )
            os.fchmod(descriptor, _REPORT_HANDOFF_INITIAL_MODE)
            created_metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(created_metadata.st_mode)
                or created_metadata.st_uid != os.getuid()
                or created_metadata.st_gid != os.getgid()
                or stat.S_IMODE(created_metadata.st_mode) != _REPORT_HANDOFF_INITIAL_MODE
                or created_metadata.st_nlink != 1
                or created_metadata.st_size != 0
                or (
                    created_metadata.st_dev,
                    created_metadata.st_ino,
                    created_metadata.st_uid,
                    created_metadata.st_gid,
                )
                != created_identity
            ):
                raise OSError
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError
                remaining = remaining[written:]
            os.fsync(descriptor)
            os.fchmod(descriptor, _REPORT_HANDOFF_MODE)
            final_metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(final_metadata.st_mode)
                or stat.S_IMODE(final_metadata.st_mode) != _REPORT_HANDOFF_MODE
                or final_metadata.st_nlink != 1
                or final_metadata.st_size != len(payload)
                or (
                    final_metadata.st_dev,
                    final_metadata.st_ino,
                    final_metadata.st_uid,
                    final_metadata.st_gid,
                )
                != created_identity
            ):
                raise OSError
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
        except Exception:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if created_identity is not None:
                try:
                    current_metadata = output_path.lstat()
                    current_identity = (
                        current_metadata.st_dev,
                        current_metadata.st_ino,
                        current_metadata.st_uid,
                        current_metadata.st_gid,
                    )
                    if (
                        stat.S_ISREG(current_metadata.st_mode)
                        and current_metadata.st_nlink == 1
                        and current_identity == created_identity
                    ):
                        output_path.unlink()
                except OSError:
                    pass
            raise
        return report
    except Exception:
        _write_failure_stage_handoff(
            failure_stage_handoff_output_path,
            "inside_report",
        )
        raise


def _contains_forbidden_text(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_forbidden_text(str(key)) or _contains_forbidden_text(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_text(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(token in lowered for token in _FORBIDDEN_REPORT_TEXT)
    return False


def _validate_report_body(
    report: Mapping[str, Any],
    *,
    expected_implementation_contract_hash: str | None = None,
    expected_journey_script_hash: str | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    if expected_implementation_contract_hash is None and (ROOT / "python").is_dir():
        expected_implementation_contract_hash = issue20_implementation_contract_hash(ROOT)
    if expected_journey_script_hash is None and Path(__file__).is_file():
        expected_journey_script_hash = _sha256_bytes(Path(__file__).read_bytes())
    if set(report) != {
        "artifact_id",
        "schema_version",
        "status",
        "implementation_contract_hash",
        "runtime_image_id_hash",
        "journey_script_hash",
        "secret_initialization_contract_hash",
        "migration_result_hash",
        "operator_output_hashes",
        "operator_denial_hash",
        "counts",
        "attestations",
    }:
        blockers.append("operator journey report keys are invalid")
    if report.get("artifact_id") != ARTIFACT_ID:
        blockers.append("operator journey artifact id is invalid")
    schema_version = report.get("schema_version")
    if schema_version not in {1, 2} or report.get("status") != "passed":
        blockers.append("operator journey status is invalid")
    for field in (
        "implementation_contract_hash",
        "runtime_image_id_hash",
        "journey_script_hash",
        "secret_initialization_contract_hash",
        "migration_result_hash",
        "operator_denial_hash",
    ):
        if not isinstance(report.get(field), str) or not _SHA256_RE.fullmatch(
            str(report.get(field))
        ):
            blockers.append(f"operator journey hash is invalid: {field}")
    if (
        expected_implementation_contract_hash is not None
        and report.get("implementation_contract_hash") != expected_implementation_contract_hash
    ):
        blockers.append("operator journey implementation contract hash is stale")
    if (
        expected_journey_script_hash is not None
        and report.get("journey_script_hash") != expected_journey_script_hash
    ):
        blockers.append("operator journey script hash is stale")
    output_hashes = report.get("operator_output_hashes")
    expected_labels = (
        {
            "lookup-user",
            "list-users",
            "lookup-token-session",
            "list-token-sessions",
        }
        if schema_version == 1
        else {
            "bootstrap-owner",
            "invite-member",
            "lookup-owner",
            "list-users",
            "list-member-sessions-before",
            "revoke-member-session",
            "lookup-member-session-after-revoke",
            "remove-member",
            "restore-member",
            "list-member-sessions-after-restore",
            "operator-audit-contract",
            "operator-rollback-state",
        }
    )
    if not isinstance(output_hashes, Mapping) or set(output_hashes) != expected_labels:
        blockers.append("operator journey output hashes are invalid")
    elif any(
        not isinstance(value, str) or not _SHA256_RE.fullmatch(value)
        for value in output_hashes.values()
    ):
        blockers.append("operator journey output hash value is invalid")
    elif len(output_hashes.values()) != len(set(output_hashes.values())):
        blockers.append("operator journey output hashes are not independently bound")
    counts = report.get("counts")
    expected_counts = (
        {
            "fresh_postgresql_database_count": 1,
            "generated_secret_count": 6,
            "idempotent_secret_rerun_count": 1,
            "migration_command_success_count": 1,
            "operator_cli_success_count": 4,
            "operator_cli_denial_count": 1,
            "operator_audit_total_count": 5,
            "operator_audit_allowed_count": 4,
            "operator_audit_denied_count": 1,
            "runtime_image_build_count": 1,
        }
        if schema_version == 1
        else {
            "fresh_postgresql_database_count": 1,
            "generated_secret_count": 6,
            "idempotent_secret_rerun_count": 1,
            "migration_command_success_count": 1,
            "operator_cli_success_count": 10,
            "operator_cli_denial_count": 3,
            "operator_audit_total_count": 13,
            "operator_audit_allowed_count": 10,
            "operator_audit_denied_count": 3,
            "runtime_image_build_count": 1,
            "owner_bootstrap_success_count": 1,
            "member_invitation_success_count": 1,
            "member_approval_denial_count": 1,
            "explicit_token_revocation_count": 1,
            "last_owner_removal_denial_count": 1,
            "membership_remove_success_count": 1,
            "membership_restore_success_count": 1,
            "post_restore_active_session_count": 0,
            "post_restore_inactive_session_count": 2,
            "transaction_rollback_probe_count": 1,
            "transaction_rollback_preserved_state_count": 1,
        }
    )
    if counts != expected_counts:
        blockers.append("operator journey counts are invalid")
    attestations = report.get("attestations")
    expected_attestations = {
        "actual_connected_cli_executed": True,
        "clean_temporary_secret_set_used": True,
        "current_runtime_image_built_from_worktree": True,
        "fresh_postgresql_database_used": True,
        "google_credential_injected_outside_initializer": True,
        "inside_probe_used_installed_runtime_package": True,
        "operator_allow_and_deny_audits_persisted": True,
        "operator_outputs_excluded_sensitive_identity_and_backend_detail": True,
        "report_contains_only_safe_status_count_and_hash_evidence": True,
    }
    if schema_version == 2:
        expected_attestations.update(
            {
                "exact_operator_lifecycle_exercised": True,
                "member_approval_denial_audited": True,
                "membership_rollback_verified": True,
                "immutable_runtime_and_postgres_images_used": True,
            }
        )
    if attestations != expected_attestations:
        blockers.append("operator journey attestations are invalid")
    if _contains_forbidden_text(report):
        blockers.append("operator journey report contains forbidden text")
    return {"passed": not blockers, "blockers": blockers}


def validate_report(
    report: Mapping[str, Any],
    *,
    trusted_execution_authority: Mapping[str, Any] | None = None,
    trusted_execution_authority_pin: Mapping[str, Any] | None = None,
    expected_implementation_contract_hash: str | None = None,
    expected_journey_script_hash: str | None = None,
) -> dict[str, Any]:
    schema_version = report.get("schema_version")
    if schema_version == 1:
        return _validate_report_body(
            report,
            expected_implementation_contract_hash=expected_implementation_contract_hash,
            expected_journey_script_hash=expected_journey_script_hash,
        )
    body = dict(report)
    receipt = body.pop("execution_receipt", None)
    body_validation = _validate_report_body(
        body,
        expected_implementation_contract_hash=expected_implementation_contract_hash,
        expected_journey_script_hash=expected_journey_script_hash,
    )
    blockers = list(body_validation["blockers"])
    if receipt is None:
        blockers.append("operator execution receipt is missing")
    if trusted_execution_authority is None:
        blockers.append("operator trusted execution authority is required")
    if trusted_execution_authority_pin is None:
        blockers.append("operator trusted execution authority pin is required")
    if trusted_execution_authority is not None and trusted_execution_authority_pin is not None:
        receipt_validation = validate_execution_receipt(
            report,
            trusted_execution_authority,
            trusted_execution_authority_pin,
        )
        blockers.extend(receipt_validation["blockers"])
    if _contains_forbidden_text(report):
        blockers.append("operator journey report contains forbidden text")
    return {"passed": not blockers, "blockers": blockers}


def run_outer(
    output_path: Path,
    *,
    postgres_image: str,
    execution_authority_output_path: Path = DEFAULT_EXECUTION_AUTHORITY_OUTPUT,
    execution_authority_pin_output_path: Path = DEFAULT_EXECUTION_AUTHORITY_PIN_OUTPUT,
    failure_diagnostic_output_path: Path | None = None,
) -> dict[str, Any]:
    try:
        postgres_image = _require_pinned_postgres_image(postgres_image)
        output_path = output_path.resolve()
        execution_authority_output_path = execution_authority_output_path.resolve()
        execution_authority_pin_output_path = execution_authority_pin_output_path.resolve()
        if failure_diagnostic_output_path is not None:
            failure_diagnostic_output_path = failure_diagnostic_output_path.resolve()
        distinct_paths = {
            output_path,
            execution_authority_output_path,
            execution_authority_pin_output_path,
        }
        if failure_diagnostic_output_path is not None:
            distinct_paths.add(failure_diagnostic_output_path)
        expected_path_count = 3 + int(failure_diagnostic_output_path is not None)
        if len(distinct_paths) != expected_path_count:
            failure_diagnostic_output_path = None
            raise RuntimeError("operator_journey_execution_authority_output_invalid")
        if os.path.lexists(execution_authority_output_path) or os.path.lexists(
            execution_authority_pin_output_path
        ):
            raise RuntimeError("operator_journey_execution_authority_already_exists")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        execution_authority_output_path.parent.mkdir(parents=True, exist_ok=True)
        execution_authority_pin_output_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = uuid.uuid4().hex[:12]
        network_name = f"formowl-operator-live-{suffix}"
        postgres_name = f"formowl-operator-postgres-{suffix}"
        uid_gid = f"{os.getuid()}:{os.getgid()}"
        implementation_contract_hash = issue20_implementation_contract_hash(ROOT)
    except Exception:
        _write_failure_diagnostic(
            failure_diagnostic_output_path,
            "outer_runtime_setup",
        )
        raise
    try:
        temporary_directory = tempfile.TemporaryDirectory(prefix="formowl-operator-journey-")
    except Exception:
        _write_failure_diagnostic(
            failure_diagnostic_output_path,
            "outer_runtime_setup",
        )
        raise
    try:
        temporary = temporary_directory.name
        temp_root = Path(temporary)
        secret_dir = temp_root / "secrets"
        data_dir = temp_root / "data"
        out_dir = temp_root / "out"
        secret_dir.mkdir(mode=0o700)
        data_dir.mkdir(mode=0o707)
        out_dir.mkdir(mode=0o733)
        # The host-only temporary parent remains 0700. The exact bind-mounted
        # data root grants the runtime UID only what it needs to list and delete
        # its own entries during capability-free cleanup.
        os.chmod(data_dir, 0o707)
        os.chmod(out_dir, 0o733)
        iidfile = temp_root / "runtime-image.iid"
        runtime_image_id: str | None = None
        signed_report: dict[str, Any] | None = None
        failure_stage = "outer_runtime_setup"
        try:
            _run_command(
                [
                    "docker",
                    "build",
                    "--file",
                    str(ROOT / "containers/runtime/Dockerfile"),
                    "--iidfile",
                    str(iidfile),
                    str(ROOT),
                ]
            )
            runtime_image_id = _read_built_runtime_image_id(iidfile)
            runtime_image_id_hash = _sha256_bytes(runtime_image_id.encode("utf-8"))
            failure_stage = "outer_secret_set"
            generated = _parse_json_output(
                _run_command(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--user",
                        uid_gid,
                        "-v",
                        f"{secret_dir}:/secrets",
                        runtime_image_id,
                        "init-secrets",
                        "--output-dir",
                        "/secrets",
                        "--postgres-host",
                        postgres_name,
                    ]
                )
            )
            unchanged = _parse_json_output(
                _run_command(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--user",
                        uid_gid,
                        "-v",
                        f"{secret_dir}:/secrets",
                        runtime_image_id,
                        "init-secrets",
                        "--output-dir",
                        "/secrets",
                        "--postgres-host",
                        postgres_name,
                    ]
                )
            )
            if (
                generated.get("secret_set_state") != "created"
                or generated.get("secret_file_count") != 6
                or generated.get("created_file_count") != 6
            ):
                raise RuntimeError("operator_journey_secret_initialization_invalid")
            if unchanged.get("secret_set_state") != "unchanged":
                raise RuntimeError("operator_journey_secret_rerun_invalid")
            secret_contract_hash = _sha256_json({"generated": generated, "unchanged": unchanged})
            _write_secret(secret_dir / "google-client-secret", b"synthetic-google-secret\n")
            failure_stage = "outer_authority"
            execution_authority, receipt_signing_key = create_execution_authority(
                implementation_contract_hash=implementation_contract_hash,
                runtime_image_id_hash=runtime_image_id_hash,
                journey_script_hash=_sha256_bytes(Path(__file__).read_bytes()),
            )
            execution_authority_pin = create_execution_authority_pin(execution_authority)
            # These two artifacts are the outer campaign trust root. Persist them
            # before starting PostgreSQL or executing the raw inner journey, and
            # never derive or replace them from the resulting report. The pair is
            # fail-closed rather than rollback-cleaned: if the second exclusive
            # write fails, the first file remains and permanently locks this
            # campaign so a later invocation cannot repair or replace it.
            try:
                _write_secret(
                    execution_authority_output_path,
                    (
                        json.dumps(
                            execution_authority,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n"
                    ).encode("utf-8"),
                )
                _write_secret(
                    execution_authority_pin_output_path,
                    (
                        json.dumps(
                            execution_authority_pin,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n"
                    ).encode("utf-8"),
                )
            except OSError as error:
                raise RuntimeError(
                    "operator_journey_execution_authority_pair_incomplete"
                ) from error
            for trust_input_path in (
                execution_authority_output_path,
                execution_authority_pin_output_path,
            ):
                try:
                    metadata = trust_input_path.lstat()
                except OSError as error:
                    raise RuntimeError(
                        "operator_journey_execution_authority_pair_incomplete"
                    ) from error
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o400
                ):
                    raise RuntimeError("operator_journey_execution_authority_pair_incomplete")

            failure_stage = "outer_postgresql"
            _run_command(["docker", "network", "create", network_name])
            postgres_started = False
            try:
                _run_command(
                    [
                        "docker",
                        "run",
                        "--detach",
                        "--rm",
                        "--name",
                        postgres_name,
                        "--network",
                        network_name,
                        "-e",
                        "POSTGRES_DB=formowl",
                        "-e",
                        "POSTGRES_USER=formowl",
                        "-e",
                        "POSTGRES_PASSWORD_FILE=/run/secrets/postgres-password",
                        "-v",
                        (
                            f"{secret_dir / 'postgres-password'}:"
                            "/run/secrets/postgres-password:ro"
                        ),
                        postgres_image,
                    ]
                )
                postgres_started = True
                for _attempt in range(60):
                    ready = _run_command(
                        [
                            "docker",
                            "exec",
                            postgres_name,
                            "pg_isready",
                            "-U",
                            "formowl",
                            "-d",
                            "formowl",
                        ],
                        check=False,
                    )
                    if ready.returncode == 0:
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError("operator_journey_postgres_not_ready")

                environment = _runtime_environment()
                environment[_IMPLEMENTATION_CONTRACT_HASH_ENV] = implementation_contract_hash
                environment[_RUNTIME_IMAGE_ID_ENV] = runtime_image_id
                environment[_RUNTIME_IMAGE_ID_HASH_ENV] = runtime_image_id_hash
                environment[_SECRET_CONTRACT_HASH_ENV] = secret_contract_hash
                command = [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    network_name,
                    "--read-only",
                    "--tmpfs",
                    "/tmp:size=64m,mode=1777",
                    "--tmpfs",
                    "/run/formowl-secrets:size=1m,mode=0700",
                    "--cap-drop",
                    "ALL",
                ]
                for capability in _LAUNCHER_CAPABILITIES:
                    command.extend(["--cap-add", capability])
                command.extend(
                    [
                        "--security-opt",
                        "no-new-privileges:true",
                        "-v",
                        (
                            f"{Path(__file__).resolve()}:"
                            "/opt/formowl-connected-operator-journey.py:ro"
                        ),
                        "-v",
                        f"{data_dir}:/data",
                        "-v",
                        f"{out_dir}:/out",
                        *_runtime_secret_mounts(secret_dir),
                    ]
                )
                environment["FORMOWL_CONTAINER_STAGE_SECRETS"] = "1"
                for name, value in sorted(environment.items()):
                    command.extend(["-e", f"{name}={value}"])
                inner_failure_stage_handoff_path = out_dir / "failure-stage-handoff.json"
                command.extend(
                    [
                        runtime_image_id,
                        "python",
                        "/opt/formowl-connected-operator-journey.py",
                        "--inside",
                        "--runtime-image-id",
                        runtime_image_id,
                        "--output",
                        f"/out/{output_path.name}",
                        "--failure-stage-handoff-output",
                        "/out/failure-stage-handoff.json",
                    ]
                )
                failure_stage = "outer_inner_journey"
                inner_result = _run_command(command, check=False)
                if inner_result.returncode != 0:
                    transferred_stage = _read_failure_stage_handoff(
                        inner_failure_stage_handoff_path
                    )
                    if transferred_stage is not None:
                        failure_stage = transferred_stage
                    raise RuntimeError(_safe_process_error(inner_result))
                if os.path.lexists(inner_failure_stage_handoff_path):
                    raise RuntimeError("operator_journey_failure_stage_handoff_invalid")
                failure_stage = "outer_report"
                container_report_path = out_dir / output_path.name
                report_descriptor: int | None = None
                try:
                    path_metadata_before = container_report_path.lstat()
                    if (
                        not stat.S_ISREG(path_metadata_before.st_mode)
                        or path_metadata_before.st_uid != _FAILURE_STAGE_HANDOFF_OWNER_UID
                        or path_metadata_before.st_gid != _FAILURE_STAGE_HANDOFF_OWNER_GID
                        or stat.S_IMODE(path_metadata_before.st_mode) != _REPORT_HANDOFF_MODE
                        or path_metadata_before.st_nlink != 1
                        or not 2 <= path_metadata_before.st_size <= _REPORT_HANDOFF_MAX_BYTES
                    ):
                        raise OSError
                    identity_before = (
                        path_metadata_before.st_dev,
                        path_metadata_before.st_ino,
                        path_metadata_before.st_uid,
                        path_metadata_before.st_gid,
                        stat.S_IMODE(path_metadata_before.st_mode),
                        path_metadata_before.st_nlink,
                        path_metadata_before.st_size,
                        path_metadata_before.st_mtime_ns,
                        path_metadata_before.st_ctime_ns,
                    )
                    report_descriptor = os.open(
                        container_report_path,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    )
                    descriptor_metadata_before = os.fstat(report_descriptor)
                    descriptor_identity_before = (
                        descriptor_metadata_before.st_dev,
                        descriptor_metadata_before.st_ino,
                        descriptor_metadata_before.st_uid,
                        descriptor_metadata_before.st_gid,
                        stat.S_IMODE(descriptor_metadata_before.st_mode),
                        descriptor_metadata_before.st_nlink,
                        descriptor_metadata_before.st_size,
                        descriptor_metadata_before.st_mtime_ns,
                        descriptor_metadata_before.st_ctime_ns,
                    )
                    if (
                        not stat.S_ISREG(descriptor_metadata_before.st_mode)
                        or descriptor_identity_before != identity_before
                    ):
                        raise OSError
                    remaining_bytes = descriptor_metadata_before.st_size
                    report_chunks: list[bytes] = []
                    while remaining_bytes:
                        chunk = os.read(report_descriptor, remaining_bytes)
                        if type(chunk) is not bytes or not chunk or len(chunk) > remaining_bytes:
                            raise OSError
                        report_chunks.append(chunk)
                        remaining_bytes -= len(chunk)
                    if os.read(report_descriptor, 1) != b"":
                        raise OSError
                    report_payload = b"".join(report_chunks)
                    descriptor_metadata_after = os.fstat(report_descriptor)
                    path_metadata_after = container_report_path.lstat()
                    descriptor_identity_after = (
                        descriptor_metadata_after.st_dev,
                        descriptor_metadata_after.st_ino,
                        descriptor_metadata_after.st_uid,
                        descriptor_metadata_after.st_gid,
                        stat.S_IMODE(descriptor_metadata_after.st_mode),
                        descriptor_metadata_after.st_nlink,
                        descriptor_metadata_after.st_size,
                        descriptor_metadata_after.st_mtime_ns,
                        descriptor_metadata_after.st_ctime_ns,
                    )
                    path_identity_after = (
                        path_metadata_after.st_dev,
                        path_metadata_after.st_ino,
                        path_metadata_after.st_uid,
                        path_metadata_after.st_gid,
                        stat.S_IMODE(path_metadata_after.st_mode),
                        path_metadata_after.st_nlink,
                        path_metadata_after.st_size,
                        path_metadata_after.st_mtime_ns,
                        path_metadata_after.st_ctime_ns,
                    )
                    if (
                        not stat.S_ISREG(descriptor_metadata_after.st_mode)
                        or not stat.S_ISREG(path_metadata_after.st_mode)
                        or descriptor_identity_after != identity_before
                        or path_identity_after != identity_before
                        or len(report_payload) != descriptor_metadata_before.st_size
                    ):
                        raise OSError
                    container_report = json.loads(report_payload.decode("utf-8"))
                    if type(container_report) is not dict:
                        raise ValueError
                    canonical_payload = json.dumps(
                        container_report,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ).encode("utf-8")
                    if report_payload != canonical_payload:
                        raise ValueError
                    os.close(report_descriptor)
                    report_descriptor = None
                except (
                    OSError,
                    TypeError,
                    ValueError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ):
                    if report_descriptor is not None:
                        try:
                            os.close(report_descriptor)
                        except OSError:
                            pass
                    raise RuntimeError("operator_journey_report_invalid") from None
                unsigned_validation = _validate_report_body(
                    container_report,
                    expected_implementation_contract_hash=implementation_contract_hash,
                    expected_journey_script_hash=_sha256_bytes(Path(__file__).read_bytes()),
                )
                if not unsigned_validation["passed"]:
                    raise RuntimeError("operator_journey_report_invalid")
                signed_report = attach_execution_receipt(
                    container_report,
                    execution_authority,
                    execution_authority_pin,
                    receipt_signing_key,
                )
                signed_validation = validate_report(
                    signed_report,
                    trusted_execution_authority=execution_authority,
                    trusted_execution_authority_pin=execution_authority_pin,
                    expected_implementation_contract_hash=implementation_contract_hash,
                    expected_journey_script_hash=_sha256_bytes(Path(__file__).read_bytes()),
                )
                if not signed_validation["passed"]:
                    raise RuntimeError("operator_journey_report_invalid")
            finally:
                primary_failure = sys.exception()
                cleanup_failures: list[str] = []
                if postgres_started:
                    try:
                        stopped = _run_command(
                            ["docker", "stop", postgres_name],
                            check=False,
                        )
                        if stopped.returncode != 0:
                            cleanup_failures.append("operator_journey_postgres_cleanup_failed")
                    except Exception:
                        cleanup_failures.append("operator_journey_postgres_cleanup_failed")
                try:
                    removed_network = _run_command(
                        ["docker", "network", "rm", network_name],
                        check=False,
                    )
                    if removed_network.returncode != 0:
                        cleanup_failures.append("operator_journey_network_cleanup_failed")
                except Exception:
                    cleanup_failures.append("operator_journey_network_cleanup_failed")
                if cleanup_failures:
                    if primary_failure is None:
                        failure_stage = "outer_runtime_cleanup"
                        cleanup_failure = RuntimeError("operator_journey_runtime_cleanup_failed")
                        for cleanup_code in cleanup_failures:
                            cleanup_failure.add_note(cleanup_code)
                        raise cleanup_failure
                    for cleanup_code in cleanup_failures:
                        primary_failure.add_note(cleanup_code)
        except Exception:
            _write_failure_diagnostic(
                failure_diagnostic_output_path,
                failure_stage,
            )
            raise
        finally:
            if runtime_image_id is not None:
                primary_failure = sys.exception()
                cleanup_succeeded = _cleanup_runtime_data_and_image(
                    data_dir,
                    runtime_image_id,
                )
                if primary_failure is None and not cleanup_succeeded:
                    _write_failure_diagnostic(
                        failure_diagnostic_output_path,
                        "outer_runtime_cleanup",
                    )
                    raise RuntimeError("operator_journey_runtime_cleanup_failed")
                if primary_failure is not None and not cleanup_succeeded:
                    primary_failure.add_note("operator_journey_runtime_cleanup_failed")
    finally:
        primary_failure = sys.exception()
        try:
            temporary_directory.cleanup()
        except Exception:
            if primary_failure is None:
                _write_failure_diagnostic(
                    failure_diagnostic_output_path,
                    "outer_runtime_cleanup",
                )
                raise

    try:
        execution_authority = json.loads(
            execution_authority_output_path.read_text(encoding="utf-8")
        )
        execution_authority_pin = json.loads(
            execution_authority_pin_output_path.read_text(encoding="utf-8")
        )
        if not isinstance(execution_authority, dict):
            raise RuntimeError("operator_journey_execution_authority_invalid")
        if not isinstance(execution_authority_pin, dict):
            raise RuntimeError("operator_journey_execution_authority_pin_invalid")
        if signed_report is None:
            raise RuntimeError("operator_journey_report_invalid")
        validation = validate_report(
            signed_report,
            trusted_execution_authority=execution_authority,
            trusted_execution_authority_pin=execution_authority_pin,
            expected_implementation_contract_hash=implementation_contract_hash,
            expected_journey_script_hash=_sha256_bytes(Path(__file__).read_bytes()),
        )
        if not validation["passed"]:
            raise RuntimeError("operator_journey_report_invalid")
        expected_bindings = {
            "implementation_contract_hash": implementation_contract_hash,
            "runtime_image_id_hash": runtime_image_id_hash,
            "journey_script_hash": _sha256_bytes(Path(__file__).read_bytes()),
            "secret_initialization_contract_hash": secret_contract_hash,
        }
        if any(signed_report.get(key) != value for key, value in expected_bindings.items()):
            raise RuntimeError("operator_journey_report_binding_invalid")
        write_json_atomic(output_path, signed_report)
        return signed_report
    except Exception:
        _write_failure_diagnostic(
            failure_diagnostic_output_path,
            "outer_report",
        )
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--execution-authority-output",
        type=Path,
        default=DEFAULT_EXECUTION_AUTHORITY_OUTPUT,
    )
    parser.add_argument(
        "--execution-authority-pin-output",
        type=Path,
        default=DEFAULT_EXECUTION_AUTHORITY_PIN_OUTPUT,
    )
    parser.add_argument("--trusted-execution-authority", type=Path)
    parser.add_argument("--trusted-execution-authority-pin", type=Path)
    parser.add_argument("--failure-diagnostic-output", type=Path)
    parser.add_argument("--failure-stage-handoff-output", type=Path)
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--runtime-image-id")
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--validate-report", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        if arguments.validate_report is not None:
            report = json.loads(arguments.validate_report.read_text(encoding="utf-8"))
            execution_authority = None
            execution_authority_pin = None
            if arguments.trusted_execution_authority is not None:
                execution_authority = json.loads(
                    arguments.trusted_execution_authority.read_text(encoding="utf-8")
                )
            if arguments.trusted_execution_authority_pin is not None:
                execution_authority_pin = json.loads(
                    arguments.trusted_execution_authority_pin.read_text(encoding="utf-8")
                )
            validation = validate_report(
                report,
                trusted_execution_authority=execution_authority,
                trusted_execution_authority_pin=execution_authority_pin,
            )
            write_json_atomic(arguments.output, validation)
            return 0 if validation["passed"] else 1
        if arguments.inside:
            if arguments.failure_diagnostic_output is not None:
                raise RuntimeError("operator_journey_failure_diagnostic_output_invalid")
            run_inside(
                arguments.output,
                runtime_image_id=arguments.runtime_image_id,
                failure_stage_handoff_output_path=(arguments.failure_stage_handoff_output),
            )
        else:
            if arguments.failure_stage_handoff_output is not None:
                raise RuntimeError("operator_journey_failure_stage_handoff_output_invalid")
            run_outer(
                arguments.output,
                postgres_image=arguments.postgres_image,
                execution_authority_output_path=arguments.execution_authority_output,
                execution_authority_pin_output_path=(arguments.execution_authority_pin_output),
                failure_diagnostic_output_path=arguments.failure_diagnostic_output,
            )
        return 0
    except Exception:
        print(
            json.dumps(
                {"error": "operator_journey_failed", "status": "error"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
