#!/usr/bin/env python3
"""Run a bounded connected-runtime E2E against a fresh live PostgreSQL database."""

from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import urlparse
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "tests"))

from formowl_core import write_json_atomic  # noqa: E402
from formowl_evidence import issue20_implementation_contract_hash  # noqa: E402

if TYPE_CHECKING:
    from cryptography.fernet import Fernet
    from formowl_auth import (
        FileAuditLogStore,
        FormOwlSigningKey,
        FormOwlSigningKeySet,
        OAuthBridgeConfig,
    )
    from formowl_auth.config import (
        GOOGLE_AUTHORIZATION_ENDPOINT,
        GOOGLE_DISCOVERY_URL,
        GOOGLE_JWKS_URI,
        GOOGLE_TOKEN_ENDPOINT,
    )
    from formowl_contract import User
    import formowl_gateway.runtime as runtime_module
    from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
    from formowl_graph.storage import SQLStatement
    from formowl_ingestion.storage import UploadSessionStore
    from oauth_harness import (
        AsgiHttpServer,
        DeterministicRng,
        DeterministicRsaKey,
        FakeClock,
        FakeGoogleAccount,
        FakeGoogleOidcProvider,
        HttpClient,
        RewritingAsyncHttpClient,
        SimulatedChatGptOAuthClient,
        generate_ephemeral_formowl_signing_key,
        run_official_mcp_client_sequence,
    )


ARTIFACT_ID = "formowl_connected_runtime_postgres_live_e2e_v2"
DEFAULT_OUTPUT = Path("/tmp/formowl-connected-runtime-postgres-live-e2e.json")
PINNED_POSTGRES_IMAGE = (
    "pgvector/pgvector@sha256:" "131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6"
)
POSTGRES_IMAGE = PINNED_POSTGRES_IMAGE
LATEST_PROTOCOL_VERSION = "2025-11-25"
_INSIDE_DSN_ENV = "FORMOWL_LIVE_POSTGRES_DSN"
_INSIDE_DATA_DIR_ENV = "FORMOWL_LIVE_DATA_DIR"
_RUNNER_CAMPAIGN_PIN_ENV = "FORMOWL_RUNNER_CAMPAIGN_PIN"
_RUNNER_CAMPAIGN_PIN_SHA256_ENV = "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RUNNER_SCRATCH_NAME_RE = re.compile(
    r"^formowl-issue20-containerized-evidence-runner-[A-Za-z0-9._-]+$"
)
_SAFE_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"\b(?:https?|postgres(?:ql)?)://", re.IGNORECASE)
_RAW_PATH_RE = re.compile(
    r"(^|[\s'\"([{=,:;])(/(?:home|tmp|srv|mnt|var|root|workspace)/|[A-Za-z]:[\\/])"
)
_SQL_RE = re.compile(
    r"\b(select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+table)\b",
    re.IGNORECASE,
)
_FORBIDDEN_REPORT_TEXT = (
    "access_token",
    "authorization_code",
    "bearer ",
    "client_secret",
    "code_verifier",
    "database_dsn",
    "google_code",
    "id_token",
    "postgresql://",
    "private_key",
    "state_encryption_key",
    "/home/",
    "/live-data",
    "/run/secrets/",
    "/tmp/formowl-live",
    "/workspace/",
    "SELECT ",
    "INSERT ",
    "UPDATE ",
    "DELETE ",
)

_METRIC_FIELDS = {
    "fresh_database_migrated",
    "migration_ledger_replayed_without_duplication",
    "transaction_rollback_verified",
    "operator_owner_bootstrap_completed",
    "oauth_pkce_formowl_token_completed",
    "official_streamable_http_mcp_completed",
    "whoami_actor_context_verified",
    "server_bound_upload_persisted",
    "postgres_auth_and_audit_persisted",
    "restart_existing_token_verified",
    "restart_upload_and_file_audit_persisted",
    "signing_key_rotation_overlap_verified",
    "signing_key_rotation_jwks_public_only_verified",
    "signing_key_rotation_new_token_verified",
    "signing_key_rotation_retirement_verified",
    "upload_file_audit_token_binding_verified",
    "cross_workspace_and_forgery_denied",
    "postgres_mcp_audit_lineage_verified",
    "second_user_invitation_and_mapping_verified",
    "revoked_token_denied",
    "revoked_token_stays_denied_after_relink",
    "same_subject_relink_verified",
    "relink_token_session_lineage_separated",
    "relinked_token_expiry_denied",
    "exact_connected_tool_surface_verified",
    "raw_secret_or_path_exposed",
}
_SAFE_COUNT_FIELDS = {
    "migration_ledger_rows",
    "migration_applied_count",
    "migration_restart_skipped_count",
    "postgres_audit_rows_before_restart",
    "postgres_audit_rows_after_all_journeys",
    "persisted_upload_session_rows",
    "persisted_file_audit_rows",
    "listed_tool_count",
    "user_rows_after_second_login",
    "workspace_member_rows_after_second_login",
    "external_identity_rows_after_second_login",
    "accepted_invitation_rows_after_second_login",
    "token_session_rows_after_all_journeys",
    "revoked_token_denial_count",
    "post_relink_old_token_denial_count",
    "revoked_token_sessions_after_relink_count",
    "relink_distinct_token_session_count",
    "expiry_denial_count",
    "relink_count",
    "transaction_rollback_probe_count",
    "postgres_mcp_allowed_audit_count",
    "postgres_mcp_denied_audit_count",
    "postgres_mcp_lineage_complete_count",
    "cross_workspace_denial_count",
    "identity_forgery_denial_count",
    "signing_key_rotation_count",
    "overlap_old_token_verification_count",
    "overlap_jwks_public_key_count",
    "new_key_token_verification_count",
    "post_overlap_old_token_denial_count",
    "post_overlap_jwks_public_key_count",
    "post_overlap_new_token_verification_count",
    "private_signing_key_exposure_count",
}
_SAFE_HASH_FIELDS = {
    "implementation_contract_hash",
    "command_contract_hash",
    "schema_state_hash",
    "rollback_state_hash",
    "first_owner_bootstrap_state_hash",
    "persisted_auth_upload_audit_state_hash",
    "restart_state_hash",
    "second_user_invitation_state_hash",
    "revocation_expiry_relink_state_hash",
    "signing_key_rotation_state_hash",
    "first_mcp_result_shape_hash",
    "persisted_upload_shape_hash",
}
_CLAIM_FIELDS = {
    "live_postgresql",
    "production_oauth_and_mcp_runtime",
    "production_upload_and_file_audit_stores",
    "fake_google_oidc",
    "live_google_account",
    "live_chatgpt_connector",
    "live_postgresql_external_layer_contract",
    "revoke_and_expiry_relink_verified",
    "second_user_invitation_verified",
    "cross_workspace_verified",
    "signing_key_rotation_verified",
    "whole_issue_20_complete",
    "production_readiness",
}
_LIVE_POSTGRESQL_LAYER_FIELDS = {
    "status",
    "operator_attested",
    "endpoint_scheme",
    "evidence_artifact_hash",
    "source_report_commitment_hash",
    "implementation_contract_hash",
    "command_contract_hash",
    "schema_state_hash",
    "rollback_state_hash",
    "first_owner_bootstrap_state_hash",
    "persisted_auth_upload_audit_state_hash",
    "restart_state_hash",
    "second_user_invitation_state_hash",
    "revocation_expiry_relink_state_hash",
    "signing_key_rotation_state_hash",
    "run_count",
    "pass_count",
    "failure_count",
    "skip_count",
    "fresh_database_count",
    "migration_count",
    "first_owner_bootstrap_count",
    "persisted_auth_count",
    "persisted_upload_count",
    "persisted_audit_count",
    "restart_recovery_count",
    "second_user_invitation_count",
    "revocation_count",
    "post_relink_old_token_denial_count",
    "revoked_token_sessions_after_relink_count",
    "relink_distinct_token_session_count",
    "expiry_denial_count",
    "relink_count",
    "transaction_rollback_probe_count",
    "production_smoke_probe_count",
    "signing_key_rotation_count",
    "overlap_old_token_verification_count",
    "overlap_jwks_public_key_count",
    "new_key_token_verification_count",
    "post_overlap_old_token_denial_count",
    "post_overlap_jwks_public_key_count",
    "post_overlap_new_token_verification_count",
    "private_signing_key_exposure_count",
    "attestations",
}
_LIVE_POSTGRESQL_ATTESTATIONS = {
    "live_server_observed",
    "production_repository_used",
    "no_fake_database",
    "no_sensitive_material_in_packet",
}
_CAMPAIGN_PIN_FIELDS = {
    "artifact_type",
    "boundary_sha256",
    "dev_image_id",
    "docker_authority",
    "git_base_commit",
    "git_head_commit",
    "git_metadata_sha256",
    "implementation_contract_hash",
    "runner_sha256",
    "sandboxed_untrusted_source",
    "source_snapshot_sha256",
    "status",
}
_CAMPAIGN_PIN_ARTIFACT_TYPE = "issue20_containerized_evidence_campaign_pin_v1"
_CAMPAIGN_DOCKER_AUTHORITY = "trusted_operator_docker_daemon"
_CAMPAIGN_SOURCE_VERIFY_PROGRAM = """
import hashlib
import json
from pathlib import Path
import stat
import sys

try:
    root = Path("/campaign-root")
    campaign = root / "campaign"
    source = campaign / "source-snapshot"
    trust_inputs = root / "trust-inputs"
    pin = trust_inputs / "campaign-source-pin.json"
    for path in (campaign, source, trust_inputs):
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise OSError
    for path in (
        source / "scripts" / "connected_runtime_postgres_live_e2e.py",
        source / "scripts" / "issue20_containerized_evidence_runner.sh",
        source / "scripts" / "issue20_runner_boundary.py",
    ):
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise OSError
    pin_metadata = pin.lstat()
    if not stat.S_ISREG(pin_metadata.st_mode) or stat.S_ISLNK(pin_metadata.st_mode):
        raise OSError
    pin_bytes = pin.read_bytes()
    if "sha256:" + hashlib.sha256(pin_bytes).hexdigest() != sys.argv[1]:
        raise OSError
    value = json.loads(pin_bytes.decode("utf-8"))
    if type(value) is not dict or value.get("dev_image_id") != sys.argv[2]:
        raise OSError
except Exception:
    raise SystemExit(1)
""".strip()
_NESTED_CAMPAIGN_EXEC_PROGRAM = """
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

PIN_FIELDS = {
    "artifact_type",
    "boundary_sha256",
    "dev_image_id",
    "docker_authority",
    "git_base_commit",
    "git_head_commit",
    "git_metadata_sha256",
    "implementation_contract_hash",
    "runner_sha256",
    "sandboxed_untrusted_source",
    "source_snapshot_sha256",
    "status",
}
SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\\Z")
MAXIMUM_FILE_SIZE = 16 * 1024 * 1024


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def read_regular_file(path, expected_uid, maximum_size):
    path_metadata = path.lstat()
    if path.is_symlink() or path.resolve(strict=True) != path:
        raise OSError
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        opened_metadata = os.fstat(descriptor)
        current_metadata = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or opened_metadata.st_uid != expected_uid
            or opened_metadata.st_nlink != 1
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (current_metadata.st_dev, current_metadata.st_ino)
            or opened_metadata.st_size < 1
            or opened_metadata.st_size > maximum_size
        ):
            raise OSError
        payload = bytearray()
        while len(payload) <= maximum_size:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, maximum_size + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != opened_metadata.st_size:
            raise OSError
        return bytes(payload), opened_metadata
    finally:
        os.close(descriptor)


def read_pin(path, expected_uid, expected_hash, expected_image_id):
    payload, metadata = read_regular_file(path, expected_uid, 8192)
    if stat.S_IMODE(metadata.st_mode) != 0o400:
        raise OSError
    if "sha256:" + hashlib.sha256(payload).hexdigest() != expected_hash:
        raise OSError
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_object)
    if (
        type(value) is not dict
        or set(value) != PIN_FIELDS
        or value.get("artifact_type")
        != "issue20_containerized_evidence_campaign_pin_v1"
        or value.get("docker_authority") != "trusted_operator_docker_daemon"
        or value.get("sandboxed_untrusted_source") is not False
        or value.get("status") != "frozen"
        or value.get("dev_image_id") != expected_image_id
    ):
        raise OSError
    for key in (
        "boundary_sha256",
        "dev_image_id",
        "git_metadata_sha256",
        "implementation_contract_hash",
        "runner_sha256",
        "source_snapshot_sha256",
    ):
        if type(value.get(key)) is not str or SHA256_RE.fullmatch(value[key]) is None:
            raise OSError
    for key in ("git_base_commit", "git_head_commit"):
        if type(value.get(key)) is not str or COMMIT_RE.fullmatch(value[key]) is None:
            raise OSError
    return value


def write_regular_file(path, payload, mode, expected_uid):
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != expected_uid
            or metadata.st_nlink != 1
            or metadata.st_size != 0
        ):
            raise OSError
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written < 1:
                raise OSError
            remaining = remaining[written:]
        os.fchmod(descriptor, mode)
        finalized = os.fstat(descriptor)
        if (
            finalized.st_uid != expected_uid
            or finalized.st_nlink != 1
            or finalized.st_size != len(payload)
            or stat.S_IMODE(finalized.st_mode) != mode
        ):
            raise OSError
    finally:
        os.close(descriptor)


def copy_verified_tree(source_root, destination_root, expected_uid, expected_hash):
    canonical_source = source_root.resolve(strict=True)
    source_metadata = source_root.lstat()
    destination_metadata = destination_root.lstat()
    if (
        source_root.is_symlink()
        or canonical_source != source_root
        or not stat.S_ISDIR(source_metadata.st_mode)
        or source_metadata.st_uid != expected_uid
        or destination_root.is_symlink()
        or destination_root.resolve(strict=True) != destination_root
        or not stat.S_ISDIR(destination_metadata.st_mode)
        or destination_metadata.st_uid != expected_uid
        or stat.S_IMODE(destination_metadata.st_mode) != 0o700
        or any(destination_root.iterdir())
    ):
        raise OSError
    digest = hashlib.sha256()
    pending = [(source_root, destination_root)]
    directory_modes = []
    while pending:
        source_directory, destination_directory = pending.pop()
        entries = sorted(source_directory.iterdir(), key=lambda item: item.name)
        for entry in entries:
            metadata = entry.lstat()
            relative = entry.relative_to(source_root)
            encoded_relative = relative.as_posix().encode("utf-8")
            destination = destination_root / relative
            if stat.S_ISLNK(metadata.st_mode):
                raise OSError
            if stat.S_ISDIR(metadata.st_mode):
                if metadata.st_uid != expected_uid:
                    raise OSError
                destination.mkdir(mode=0o700)
                directory_modes.append(
                    (destination, stat.S_IMODE(metadata.st_mode))
                )
                digest.update(b"D\\0")
                digest.update(encoded_relative)
                digest.update(b"\\0")
                digest.update(
                    f"{stat.S_IMODE(metadata.st_mode):04o}".encode("ascii")
                )
                digest.update(b"\\0")
                pending.append((entry, destination))
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != expected_uid:
                raise OSError
            payload, opened_metadata = read_regular_file(
                entry,
                expected_uid,
                MAXIMUM_FILE_SIZE,
            )
            mode = stat.S_IMODE(opened_metadata.st_mode)
            write_regular_file(destination, payload, mode, expected_uid)
            digest.update(b"F\\0")
            digest.update(encoded_relative)
            digest.update(b"\\0")
            digest.update(f"{mode:04o}".encode("ascii"))
            digest.update(b"\\0")
            digest.update(str(len(payload)).encode("ascii"))
            digest.update(b"\\0")
            digest.update(hashlib.sha256(payload).digest())
    if "sha256:" + digest.hexdigest() != expected_hash:
        raise OSError
    for directory, mode in sorted(
        directory_modes,
        key=lambda item: len(item[0].parts),
        reverse=True,
    ):
        directory.chmod(mode)


try:
    (
        source_value,
        pin_value,
        pin_hash,
        image_id,
        destination_parent_value,
        target_value,
        *target_arguments,
    ) = sys.argv[1:]
    expected_uid = os.getuid()
    source_root = Path(source_value)
    pin_path = Path(pin_value)
    destination_parent = Path(destination_parent_value)
    target = Path(target_value)
    if (
        not source_root.is_absolute()
        or not pin_path.is_absolute()
        or not destination_parent.is_absolute()
        or not target.is_absolute()
        or not target.is_relative_to(source_root)
        or SHA256_RE.fullmatch(pin_hash) is None
        or SHA256_RE.fullmatch(image_id) is None
    ):
        raise OSError
    pin = read_pin(pin_path, expected_uid, pin_hash, image_id)
    destination_root = Path(
        tempfile.mkdtemp(
            prefix="formowl-verified-campaign-",
            dir=destination_parent,
        )
    )
    destination_root.chmod(0o700)
    copy_verified_tree(
        source_root,
        destination_root,
        expected_uid,
        pin["source_snapshot_sha256"],
    )
    verified_target = destination_root / target.relative_to(source_root)
    target_metadata = verified_target.lstat()
    if (
        verified_target.is_symlink()
        or not stat.S_ISREG(target_metadata.st_mode)
        or target_metadata.st_uid != expected_uid
    ):
        raise OSError
    os.environ["PYTHONPATH"] = os.pathsep.join(
        (
            str(destination_root / "python"),
            str(destination_root / "tests"),
        )
    )
    os.chdir(destination_root)
    os.execv(
        sys.executable,
        [
            sys.executable,
            str(verified_target),
            *target_arguments,
        ],
    )
except Exception:
    raise SystemExit(70)
""".strip()


def _load_inside_dependencies() -> None:
    """Load production and test-harness dependencies only inside the dev image."""

    if "ConnectedRuntime" in globals():
        return
    from cryptography.fernet import Fernet as _Fernet
    from formowl_auth import (
        FileAuditLogStore as _FileAuditLogStore,
        FormOwlSigningKey as _FormOwlSigningKey,
        FormOwlSigningKeySet as _FormOwlSigningKeySet,
        OAuthBridgeConfig as _OAuthBridgeConfig,
    )
    from formowl_auth.config import (
        GOOGLE_AUTHORIZATION_ENDPOINT as _GOOGLE_AUTH_ENDPOINT,
        GOOGLE_DISCOVERY_URL as _GOOGLE_DISCOVERY_URL,
        GOOGLE_JWKS_URI as _GOOGLE_JWKS_URI,
        GOOGLE_TOKEN_ENDPOINT as _GOOGLE_TOKEN_ENDPOINT,
    )
    from formowl_contract import User as _User
    from formowl_gateway.runtime import (
        ConnectedRuntime as _ConnectedRuntime,
        ConnectedRuntimeConfig as _ConnectedRuntimeConfig,
    )
    import formowl_gateway.runtime as _runtime_module
    from formowl_graph.storage import SQLStatement as _SQLStatement
    from formowl_ingestion.storage import UploadSessionStore as _UploadSessionStore
    from mcp.shared.version import LATEST_PROTOCOL_VERSION as _runtime_protocol_version
    from oauth_harness import (
        AsgiHttpServer as _AsgiHttpServer,
        DeterministicRng as _DeterministicRng,
        DeterministicRsaKey as _DeterministicRsaKey,
        FakeClock as _FakeClock,
        FakeGoogleAccount as _FakeGoogleAccount,
        FakeGoogleOidcProvider as _FakeGoogleOidcProvider,
        HttpClient as _HttpClient,
        RewritingAsyncHttpClient as _RewritingAsyncHttpClient,
        SimulatedChatGptOAuthClient as _SimulatedChatGptOAuthClient,
        generate_ephemeral_formowl_signing_key as _generate_signing_key,
        run_official_mcp_client_sequence as _run_official_mcp_client_sequence,
    )

    if _runtime_protocol_version != LATEST_PROTOCOL_VERSION:
        raise RuntimeError("live_e2e_protocol_version_mismatch")
    globals().update(
        {
            "Fernet": _Fernet,
            "FileAuditLogStore": _FileAuditLogStore,
            "FormOwlSigningKey": _FormOwlSigningKey,
            "FormOwlSigningKeySet": _FormOwlSigningKeySet,
            "OAuthBridgeConfig": _OAuthBridgeConfig,
            "GOOGLE_AUTHORIZATION_ENDPOINT": _GOOGLE_AUTH_ENDPOINT,
            "GOOGLE_DISCOVERY_URL": _GOOGLE_DISCOVERY_URL,
            "GOOGLE_JWKS_URI": _GOOGLE_JWKS_URI,
            "GOOGLE_TOKEN_ENDPOINT": _GOOGLE_TOKEN_ENDPOINT,
            "User": _User,
            "ConnectedRuntime": _ConnectedRuntime,
            "ConnectedRuntimeConfig": _ConnectedRuntimeConfig,
            "runtime_module": _runtime_module,
            "SQLStatement": _SQLStatement,
            "UploadSessionStore": _UploadSessionStore,
            "AsgiHttpServer": _AsgiHttpServer,
            "DeterministicRng": _DeterministicRng,
            "DeterministicRsaKey": _DeterministicRsaKey,
            "FakeClock": _FakeClock,
            "FakeGoogleAccount": _FakeGoogleAccount,
            "FakeGoogleOidcProvider": _FakeGoogleOidcProvider,
            "HttpClient": _HttpClient,
            "RewritingAsyncHttpClient": _RewritingAsyncHttpClient,
            "SimulatedChatGptOAuthClient": _SimulatedChatGptOAuthClient,
            "generate_ephemeral_formowl_signing_key": _generate_signing_key,
            "run_official_mcp_client_sequence": _run_official_mcp_client_sequence,
        }
    )


class _ClosableRewritingAsyncHttpClient:
    def __init__(self, url_rewrites: Mapping[str, str]) -> None:
        self._client = RewritingAsyncHttpClient(url_rewrites)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def get(self, url: str, **kwargs: Any) -> Any:
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Any:
        return await self._request("POST", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        import httpx

        rewritten = self._client._rewrite_url(url)
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.request(method, rewritten, **kwargs)
        parsed = urlparse(url)
        self._client.request_history.append(
            {
                "method": method,
                "path": parsed.path or "/",
                "status": response.status_code,
            }
        )
        return response

    async def aclose(self) -> None:
        return None


class _MigrationDiagnosticConnection:
    """Bound failures to operation/index, SQLSTATE, position, and statement hash."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.operation_index = 0

    def _call(self, operation: str, function: Any, *args: Any) -> Any:
        self.operation_index += 1
        try:
            return function(*args)
        except Exception as error:
            from inspect import getattr_static

            missing = object()
            failed = object()

            def snapshot_attribute(value: Any, name: str) -> Any:
                try:
                    static_value = getattr_static(value, name, missing)
                except Exception:
                    return failed
                if static_value is missing:
                    try:
                        return getattr(value, name)
                    except AttributeError:
                        return missing
                    except Exception:
                        return failed
                try:
                    return getattr(value, name)
                except Exception:
                    return failed

            raw_sqlstate = snapshot_attribute(error, "sqlstate")
            if (
                raw_sqlstate is missing
                or raw_sqlstate is None
                or (type(raw_sqlstate) is str and not raw_sqlstate)
            ):
                raw_sqlstate = snapshot_attribute(error, "pgcode")
            sqlstate = (
                raw_sqlstate.lower()
                if type(raw_sqlstate) is str
                and len(raw_sqlstate) == 5
                and raw_sqlstate.isascii()
                and raw_sqlstate.isalnum()
                else "unknown"
            )
            diagnostic = snapshot_attribute(error, "diag")
            raw_position = (
                snapshot_attribute(diagnostic, "statement_position")
                if diagnostic is not missing and diagnostic is not failed and diagnostic is not None
                else None
            )
            position = "unknown"
            # PostgreSQL cursor positions are positive 32-bit decimal values.
            # Exact builtins avoid invoking attacker-controlled conversion hooks.
            if type(raw_position) is int:
                if 1 <= raw_position <= 2_147_483_647:
                    position = str(raw_position)
            elif (
                type(raw_position) is str
                and 1 <= len(raw_position) <= 10
                and raw_position.isascii()
                and raw_position.isdigit()
                and 1 <= int(raw_position) <= 2_147_483_647
            ):
                position = raw_position
            statement_hash = "unknown"
            raw_statement_sql = snapshot_attribute(args[0], "sql") if args else missing
            if type(raw_statement_sql) is str:
                try:
                    encoded_statement = raw_statement_sql.encode("utf-8")
                    statement_hash = hashlib.sha256(encoded_statement).hexdigest()[:12]
                except UnicodeError:
                    statement_hash = "unknown"
            raise RuntimeError(
                f"live_e2e_migration_{operation}_{self.operation_index}_{sqlstate}_"
                f"pos_{position}_h_{statement_hash}"
            ) from None

    def execute(self, statement: Any) -> None:
        self._call("execute", self.delegate.execute, statement)

    def query_one(self, statement: Any) -> Any:
        return self._call("query_one", self.delegate.query_one, statement)

    def query_all(self, statement: Any) -> Any:
        return self._call("query_all", self.delegate.query_all, statement)

    def begin(self) -> None:
        self._call("begin", self.delegate.begin)

    def commit(self) -> None:
        self._call("commit", self.delegate.commit)

    def rollback(self) -> None:
        self._call("rollback", self.delegate.rollback)

    def close(self) -> None:
        self._call("close", self.delegate.close)


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _evidence_hash(kind: str, value: Any) -> str:
    return _sha256_json({"evidence_kind": kind, "value": value})


def _command_contract_hash(implementation_contract_hash: str) -> str:
    return _evidence_hash(
        "command_contract",
        {
            "artifact_id": ARTIFACT_ID,
            "fresh_database": True,
            "official_mcp_client": True,
            "production_runtime": True,
            "postgres_image": PINNED_POSTGRES_IMAGE,
            "implementation_contract_hash": implementation_contract_hash,
        },
    )


def _require_pinned_postgres_image() -> str:
    if POSTGRES_IMAGE != PINNED_POSTGRES_IMAGE:
        raise RuntimeError("postgres_image_contract_mismatch")
    return POSTGRES_IMAGE


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _campaign_source_root(runner_image_id: str) -> Path:
    pin_value = os.environ.get(_RUNNER_CAMPAIGN_PIN_ENV)
    pin_hash = os.environ.get(_RUNNER_CAMPAIGN_PIN_SHA256_ENV)
    if pin_value is None and pin_hash is None:
        return ROOT
    try:
        if (
            type(pin_value) is not str
            or not pin_value
            or type(pin_hash) is not str
            or _SHA256_RE.fullmatch(pin_hash) is None
        ):
            raise OSError
        pin_path = Path(pin_value)
        if not pin_path.is_absolute() or pin_path.name != "campaign-source-pin.json":
            raise OSError
        trust_input_dir = pin_path.parent
        scratch_root = trust_input_dir.parent
        if (
            trust_input_dir.name != "trust-inputs"
            or scratch_root.parent != Path("/tmp")
            or _RUNNER_SCRATCH_NAME_RE.fullmatch(scratch_root.name) is None
            or pin_path.resolve(strict=True) != pin_path
        ):
            raise OSError
        pin_metadata = pin_path.lstat()
        if (
            not stat.S_ISREG(pin_metadata.st_mode)
            or stat.S_ISLNK(pin_metadata.st_mode)
            or pin_metadata.st_uid != os.getuid()
            or stat.S_IMODE(pin_metadata.st_mode) != 0o400
            or pin_metadata.st_size > 8192
        ):
            raise OSError
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(pin_path, flags)
        try:
            opened_metadata = os.fstat(descriptor)
            if not stat.S_ISREG(opened_metadata.st_mode) or (
                opened_metadata.st_dev,
                opened_metadata.st_ino,
            ) != (pin_metadata.st_dev, pin_metadata.st_ino):
                raise OSError
            pin_bytes = b""
            while len(pin_bytes) <= 8192:
                chunk = os.read(descriptor, 8193 - len(pin_bytes))
                if not chunk:
                    break
                pin_bytes += chunk
            if len(pin_bytes) > 8192:
                raise OSError
        finally:
            os.close(descriptor)
        if "sha256:" + hashlib.sha256(pin_bytes).hexdigest() != pin_hash:
            raise OSError
        pin = json.loads(
            pin_bytes.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
        if (
            type(pin) is not dict
            or set(pin) != _CAMPAIGN_PIN_FIELDS
            or pin.get("artifact_type") != _CAMPAIGN_PIN_ARTIFACT_TYPE
            or pin.get("docker_authority") != _CAMPAIGN_DOCKER_AUTHORITY
            or pin.get("sandboxed_untrusted_source") is not False
            or pin.get("status") != "frozen"
            or pin.get("dev_image_id") != runner_image_id
        ):
            raise OSError
        for key in (
            "boundary_sha256",
            "dev_image_id",
            "git_metadata_sha256",
            "implementation_contract_hash",
            "runner_sha256",
            "source_snapshot_sha256",
        ):
            if type(pin.get(key)) is not str or _SHA256_RE.fullmatch(pin[key]) is None:
                raise OSError
        for key in ("git_base_commit", "git_head_commit"):
            value = pin.get(key)
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{40}", value) is None:
                raise OSError
        return scratch_root / "campaign" / "source-snapshot"
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        raise RuntimeError("live_e2e_campaign_source_invalid") from None


def _visible_campaign_source_is_valid(source_root: Path) -> bool:
    try:
        campaign_dir = source_root.parent
        scratch_root = campaign_dir.parent
        if (
            source_root.name != "source-snapshot"
            or campaign_dir.name != "campaign"
            or source_root.resolve(strict=True) != source_root
        ):
            return False
        for path in (scratch_root, campaign_dir, source_root):
            metadata = path.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                return False
        for path in (
            source_root / "scripts" / "connected_runtime_postgres_live_e2e.py",
            source_root / "scripts" / "issue20_containerized_evidence_runner.sh",
            source_root / "scripts" / "issue20_runner_boundary.py",
        ):
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                return False
        return True
    except OSError:
        return False


def _verify_campaign_source_mount(source_root: Path, runner_image_id: str) -> None:
    if source_root == ROOT:
        return
    if source_root.exists() or source_root.is_symlink():
        if _visible_campaign_source_is_valid(source_root):
            return
        raise RuntimeError("live_e2e_campaign_source_invalid")
    pin_hash = os.environ.get(_RUNNER_CAMPAIGN_PIN_SHA256_ENV)
    if type(pin_hash) is not str or _SHA256_RE.fullmatch(pin_hash) is None:
        raise RuntimeError("live_e2e_campaign_source_invalid")
    scratch_root = source_root.parent.parent
    try:
        result = _run_command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--mount",
                f"type=bind,src={scratch_root},dst=/campaign-root,readonly",
                runner_image_id,
                "python",
                "-c",
                _CAMPAIGN_SOURCE_VERIFY_PROGRAM,
                pin_hash,
                runner_image_id,
            ],
            check=False,
        )
    except Exception:
        raise RuntimeError("live_e2e_campaign_source_invalid") from None
    if result.returncode != 0:
        raise RuntimeError("live_e2e_campaign_source_invalid")


def _metrics_pass(metrics: Mapping[str, Any]) -> bool:
    return all(
        value is (False if key == "raw_secret_or_path_exposed" else True)
        for key, value in metrics.items()
    )


def _exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> list[str]:
    blockers: list[str] = []
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        blockers.append(f"{context} is missing required fields")
    if extra:
        blockers.append(f"{context} contains unsupported fields")
    return blockers


def _initialize_request(request_id: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "formowl-connected-runtime-live-e2e",
                "version": "1.0.0",
            },
        },
    }


def _chatgpt_client(
    *,
    oauth: OAuthBridgeConfig,
    server_base_url: str,
    fake_google: FakeGoogleOidcProvider,
    seed: str,
) -> SimulatedChatGptOAuthClient:
    browser = HttpClient(
        {
            oauth.issuer: server_base_url,
            GOOGLE_AUTHORIZATION_ENDPOINT: fake_google.authorization_endpoint,
        }
    )
    return SimulatedChatGptOAuthClient(
        rng=DeterministicRng(seed),
        client_id=oauth.chatgpt_client_id,
        redirect_uri=oauth.chatgpt_redirect_uri,
        resource=oauth.resource,
        http_client=browser,
    )


def _complete_oauth_login(
    chatgpt: SimulatedChatGptOAuthClient,
    oauth: OAuthBridgeConfig,
) -> str:
    authorization = chatgpt.new_authorization()
    callback = chatgpt.complete_browser_redirects(
        chatgpt.authorization_url(oauth.authorization_endpoint, authorization)
    )
    if callback.get("state") != authorization["state"] or not callback.get("code"):
        raise RuntimeError("live_e2e_oauth_callback_invalid")
    token_response = chatgpt.exchange_code(
        oauth.token_endpoint,
        code=callback["code"],
        verifier=authorization["code_verifier"],
    )
    if token_response.status != 200:
        raise RuntimeError("live_e2e_token_exchange_failed")
    try:
        token_payload = token_response.json()
    except (ValueError, UnicodeError):
        raise RuntimeError("live_e2e_token_exchange_failed") from None
    if not isinstance(token_payload, Mapping):
        raise RuntimeError("live_e2e_token_exchange_failed")
    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("live_e2e_access_token_invalid")
    if token_payload.get("resource") != oauth.resource:
        raise RuntimeError("live_e2e_access_token_invalid")
    return access_token


def _jwt_kid(raw_token: str) -> str:
    try:
        if type(raw_token) is not str:
            raise ValueError
        segments = raw_token.split(".")
        if len(segments) != 3 or any(not segment for segment in segments):
            raise ValueError
        encoded_header = segments[0]
        if (
            not encoded_header.isascii()
            or "=" in encoded_header
            or re.fullmatch(r"[A-Za-z0-9_-]+", encoded_header) is None
        ):
            raise ValueError
        padding = "=" * (-len(encoded_header) % 4)
        header_bytes = base64.b64decode(
            (encoded_header + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        canonical_header = base64.urlsafe_b64encode(header_bytes).rstrip(b"=").decode("ascii")
        if canonical_header != encoded_header:
            raise ValueError
        header = json.loads(header_bytes.decode("utf-8"))
        if type(header) is not dict:
            raise ValueError
        kid = header.get("kid")
        if type(kid) is not str or not kid:
            raise ValueError
        return kid
    except (ValueError, UnicodeError, json.JSONDecodeError):
        raise RuntimeError("live_e2e_token_header_invalid") from None


def _jwt_expiry(raw_token: str) -> datetime:
    try:
        if type(raw_token) is not str:
            raise ValueError
        segments = raw_token.split(".")
        if len(segments) != 3 or any(not segment for segment in segments):
            raise ValueError
        encoded_payload = segments[1]
        if (
            not encoded_payload.isascii()
            or "=" in encoded_payload
            or re.fullmatch(r"[A-Za-z0-9_-]+", encoded_payload) is None
        ):
            raise ValueError
        padding = "=" * (-len(encoded_payload) % 4)
        payload_bytes = base64.b64decode(
            (encoded_payload + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        canonical_payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
        if canonical_payload != encoded_payload:
            raise ValueError
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError
        expiry = payload.get("exp")
        if type(expiry) is not int:
            raise ValueError
        return datetime.fromtimestamp(expiry, tz=timezone.utc)
    except (ValueError, UnicodeError, OverflowError, OSError):
        raise RuntimeError("live_e2e_token_payload_invalid") from None


def _jwks_summary(response: Any) -> dict[str, Any]:
    if response.status != 200:
        raise RuntimeError("live_e2e_jwks_request_failed")
    payload = response.json()
    keys = payload.get("keys") if isinstance(payload, Mapping) else None
    if not isinstance(keys, list) or not keys:
        raise RuntimeError("live_e2e_jwks_shape_invalid")
    private_fields = {"d", "p", "q", "dp", "dq", "qi", "oth"}
    if any(not isinstance(item, Mapping) for item in keys):
        raise RuntimeError("live_e2e_jwks_shape_invalid")
    kids = [item.get("kid") for item in keys]
    if any(not isinstance(kid, str) or not kid for kid in kids):
        raise RuntimeError("live_e2e_jwks_shape_invalid")
    private_count = sum(1 for item in keys if any(field in item for field in private_fields))
    return {
        "key_count": len(keys),
        "kids": sorted(str(kid) for kid in kids),
        "private_key_exposure_count": private_count,
        "shape": _shape(payload),
    }


def _invalid_token_challenge(metadata_url: str) -> str:
    return (
        f'Bearer resource_metadata="{metadata_url}", '
        'error="invalid_token", '
        'error_description="Authentication required."'
    )


def _denial_shape(
    response: Any,
    *,
    expected_metadata_url: str | None = None,
) -> dict[str, Any]:
    challenge = response.headers.get("www-authenticate")
    body = response.json()
    shape = {
        "status": response.status,
        "challenge_present": isinstance(challenge, str) and bool(challenge),
        "body_shape": _shape(body),
    }
    if expected_metadata_url is not None:
        shape["challenge_exact"] = challenge == _invalid_token_challenge(expected_metadata_url)
        shape["body_exact"] = body == {"error": "invalid_token"}
    return shape


def _assert_bearer_denied(
    response: Any,
    *,
    expected_metadata_url: str | None = None,
) -> dict[str, Any]:
    shape = _denial_shape(
        response,
        expected_metadata_url=expected_metadata_url,
    )
    if shape["status"] != 401 or shape["challenge_present"] is not True:
        raise RuntimeError("live_e2e_bearer_denial_failed")
    if expected_metadata_url is not None and (
        shape["challenge_exact"] is not True or shape["body_exact"] is not True
    ):
        raise RuntimeError("live_e2e_bearer_denial_failed")
    return shape


def _run_transaction_rollback_probe(runtime: ConnectedRuntime, *, now: datetime) -> dict[str, int]:
    before = _count_rows(runtime, "formowl_users")
    injected_error = RuntimeError("live_e2e_injected_rollback")
    try:
        with runtime.repository.transaction():
            runtime.repository.insert_user(
                User(
                    user_id="user_live_rollback_probe",
                    display_name="Rollback Probe",
                    email="rollback-probe@example.test",
                    status="active",
                    created_at=now.isoformat(),
                )
            )
            raise injected_error
    except RuntimeError as error:
        if error is not injected_error:
            raise
    after = _count_rows(runtime, "formowl_users")
    if before != after:
        raise RuntimeError("live_e2e_transaction_rollback_failed")
    return {"before_user_count": before, "after_user_count": after, "probe_count": 1}


def _shape(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return {"type": "list", "length": len(value), "items": [_shape(item) for item in value]}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _tool_call_result(
    sequence: Mapping[str, Any],
    name: str,
    *,
    occurrence: int = 0,
) -> dict[str, Any]:
    calls = sequence.get("calls")
    if not isinstance(calls, list):
        raise RuntimeError("live_e2e_mcp_calls_invalid")
    matches = [item for item in calls if isinstance(item, dict) and item.get("name") == name]
    if occurrence < 0 or len(matches) <= occurrence:
        raise RuntimeError("live_e2e_mcp_call_missing")
    result = matches[occurrence].get("result")
    if not isinstance(result, dict):
        raise RuntimeError("live_e2e_mcp_call_failed")
    return result


def _structured_call(
    sequence: Mapping[str, Any],
    name: str,
    *,
    occurrence: int = 0,
) -> dict[str, Any]:
    result = _tool_call_result(sequence, name, occurrence=occurrence)
    if result.get("isError") is True:
        raise RuntimeError("live_e2e_mcp_call_failed")
    payload = result.get("structuredContent")
    if not isinstance(payload, dict):
        raise RuntimeError("live_e2e_mcp_payload_invalid")
    return payload


def _tool_call_is_error(
    sequence: Mapping[str, Any],
    name: str,
    *,
    occurrence: int,
) -> bool:
    return _tool_call_result(sequence, name, occurrence=occurrence).get("isError") is True


def _listed_tool_names(sequence: Mapping[str, Any]) -> list[str]:
    tools_payload = sequence.get("tools")
    if not isinstance(tools_payload, dict) or not isinstance(tools_payload.get("tools"), list):
        raise RuntimeError("live_e2e_tool_list_invalid")
    names = [
        item.get("name")
        for item in tools_payload["tools"]
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    return sorted(names)


def _count_rows(runtime: ConnectedRuntime, table_name: str) -> int:
    if table_name not in {
        "formowl_audit_log",
        "formowl_external_identities",
        "formowl_oauth_invitations",
        "formowl_oauth_token_sessions",
        "formowl_schema_migrations",
        "formowl_users",
        "formowl_workspace_members",
    }:
        raise ValueError("unsupported live E2E table")
    row = runtime.repository.connection.query_one(
        SQLStatement(sql=f"SELECT COUNT(*) AS row_count FROM {table_name}", parameters={})
    )
    if not isinstance(row, Mapping):
        raise RuntimeError("live_e2e_database_count_invalid")
    row_count = row.get("row_count")
    if type(row_count) is not int or row_count < 0:
        raise RuntimeError("live_e2e_database_count_invalid")
    return row_count


def _count_oauth_state(runtime: ConnectedRuntime, state_name: str) -> int:
    if type(state_name) is not str:
        raise ValueError("unsupported live E2E OAuth state count")
    statements = {
        "accepted_invitations": (
            "SELECT COUNT(*) AS row_count FROM formowl_oauth_invitations "
            "WHERE status = 'accepted'"
        ),
        "revoked_token_sessions": (
            "SELECT COUNT(*) AS row_count FROM formowl_oauth_token_sessions "
            "WHERE revoked_at IS NOT NULL"
        ),
    }
    sql = statements.get(state_name)
    if sql is None:
        raise ValueError("unsupported live E2E OAuth state count")
    row = runtime.repository.connection.query_one(SQLStatement(sql=sql, parameters={}))
    if not isinstance(row, Mapping):
        raise RuntimeError("live_e2e_database_count_invalid")
    row_count = row.get("row_count")
    if type(row_count) is not int or row_count < 0:
        raise RuntimeError("live_e2e_database_count_invalid")
    return row_count


def _token_session_binding(runtime: ConnectedRuntime) -> dict[str, str]:
    row = runtime.repository.connection.query_one(
        SQLStatement(
            sql=(
                "SELECT token_session_id, user_id, current_workspace_id "
                "FROM formowl_oauth_token_sessions ORDER BY issued_at LIMIT 1"
            ),
            parameters={},
        )
    )
    if type(row) is not dict:
        raise RuntimeError("live_e2e_token_session_missing")
    for row_key in dict.__iter__(row):
        if type(row_key) is not str:
            raise RuntimeError("live_e2e_token_session_invalid")
    payload = {
        key: dict.get(row, key) for key in ("token_session_id", "user_id", "current_workspace_id")
    }
    if not all(type(value) is str and value for value in payload.values()):
        raise RuntimeError("live_e2e_token_session_invalid")
    return payload  # type: ignore[return-value]


def _latest_token_session_binding_for_user(
    runtime: ConnectedRuntime,
    *,
    user_id: str,
) -> dict[str, str]:
    if type(user_id) is not str or not user_id:
        raise RuntimeError("live_e2e_token_session_invalid")
    row = runtime.repository.connection.query_one(
        SQLStatement(
            sql=(
                "SELECT token_session_id, user_id, current_workspace_id "
                "FROM formowl_oauth_token_sessions WHERE user_id = %(user_id)s "
                "ORDER BY issued_at DESC, token_session_id DESC LIMIT 1"
            ),
            parameters={"user_id": user_id},
        )
    )
    if type(row) is not dict:
        raise RuntimeError("live_e2e_token_session_missing")
    payload = {
        key: dict.get(row, key) for key in ("token_session_id", "user_id", "current_workspace_id")
    }
    if not all(type(value) is str and value for value in payload.values()):
        raise RuntimeError("live_e2e_token_session_invalid")
    if payload["user_id"] != user_id:
        raise RuntimeError("live_e2e_token_session_invalid")
    return payload  # type: ignore[return-value]


def _validate_mcp_authorization_audit_lineage(
    runtime: ConnectedRuntime,
    *,
    token_binding: Mapping[str, str],
) -> dict[str, int]:
    if type(token_binding) is not dict:
        raise RuntimeError("live_e2e_mcp_audit_lineage_failed")
    token_binding_fields = (
        "token_session_id",
        "user_id",
        "current_workspace_id",
    )
    token_binding_keys = tuple(dict.keys(token_binding))
    if (
        any(type(key) is not str for key in token_binding_keys)
        or len(token_binding_keys) != len(token_binding_fields)
        or set(token_binding_keys) != set(token_binding_fields)
    ):
        raise RuntimeError("live_e2e_mcp_audit_lineage_failed")
    token_binding_values = tuple(
        dict.__getitem__(token_binding, key) for key in token_binding_fields
    )
    if any(type(value) is not str or not value for value in token_binding_values):
        raise RuntimeError("live_e2e_mcp_audit_lineage_failed")
    token_session_id, token_user_id, token_workspace_id = token_binding_values
    try:
        token_session = runtime.repository.get_token_session(token_session_id)
    except Exception:
        raise RuntimeError("live_e2e_mcp_audit_lineage_failed") from None
    if token_session is None:
        raise RuntimeError("live_e2e_token_session_missing")
    try:
        authority_values = (
            token_session.user_id,
            token_session.current_workspace_id,
            token_session.external_identity_id,
            token_session.client_id,
            token_session.token_session_id,
        )
    except Exception:
        raise RuntimeError("live_e2e_mcp_audit_lineage_failed") from None
    if any(type(value) is not str or not value for value in authority_values):
        raise RuntimeError("live_e2e_mcp_audit_lineage_failed")
    (
        authority_user_id,
        authority_workspace_id,
        authority_external_identity_id,
        authority_client_id,
        authority_token_session_id,
    ) = authority_values
    if (
        authority_token_session_id != token_session_id
        or authority_user_id != token_user_id
        or authority_workspace_id != token_workspace_id
    ):
        raise RuntimeError("live_e2e_mcp_audit_lineage_failed")
    try:
        rows = runtime.repository.connection.query_all(
            SQLStatement(
                sql=(
                    "SELECT action, target_id, actor_user_id, workspace_id, "
                    "external_identity_id, oauth_client_id, oauth_token_session_id, "
                    "request_id, tool_call_id, reason_code, status "
                    "FROM formowl_audit_log "
                    "WHERE oauth_token_session_id = %(token_session_id)s "
                    "AND action IN ('mcp_authorization_allowed', 'mcp_authorization_denied')"
                ),
                parameters={"token_session_id": token_session_id},
            )
        )
    except Exception:
        raise RuntimeError("live_e2e_mcp_audit_lineage_failed") from None
    if type(rows) is not list:
        raise RuntimeError("live_e2e_mcp_audit_lineage_failed")
    if len(rows) != 4:
        raise RuntimeError("live_e2e_mcp_audit_count_failed")
    row_fields = (
        "action",
        "target_id",
        "actor_user_id",
        "workspace_id",
        "external_identity_id",
        "oauth_client_id",
        "oauth_token_session_id",
        "request_id",
        "tool_call_id",
        "reason_code",
        "status",
    )
    row_field_set = set(row_fields)
    row_snapshots: list[dict[str, str]] = []
    for row in rows:
        if type(row) is not dict:
            raise RuntimeError("live_e2e_mcp_audit_lineage_failed")
        row_keys = tuple(dict.keys(row))
        if (
            any(type(key) is not str for key in row_keys)
            or len(row_keys) != len(row_fields)
            or set(row_keys) != row_field_set
        ):
            raise RuntimeError("live_e2e_mcp_audit_lineage_failed")
        values = tuple(dict.get(row, key) for key in row_fields)
        if any(type(value) is not str or not value for value in values):
            raise RuntimeError("live_e2e_mcp_audit_lineage_failed")
        row_snapshots.append(dict(zip(row_fields, values, strict=True)))
    expected_lineage = {
        "actor_user_id": authority_user_id,
        "workspace_id": authority_workspace_id,
        "external_identity_id": authority_external_identity_id,
        "oauth_client_id": authority_client_id,
        "oauth_token_session_id": authority_token_session_id,
    }
    for row in row_snapshots:
        if any(row[key] != value for key, value in expected_lineage.items()):
            raise RuntimeError("live_e2e_mcp_audit_lineage_failed")
    allowed = [row for row in row_snapshots if row["action"] == "mcp_authorization_allowed"]
    denied = [row for row in row_snapshots if row["action"] == "mcp_authorization_denied"]
    allowed_targets = sorted(row["target_id"] for row in allowed)
    denied_targets = [row["target_id"] for row in denied]
    if (
        allowed_targets != ["open_upload_session", "whoami"]
        or any(row["reason_code"] != "tool_authorized" for row in allowed)
        or any(row["status"] != "ok" for row in allowed)
        or len(denied) != 2
        or denied_targets != ["open_upload_session", "open_upload_session"]
        or any(row["reason_code"] != "invalid_tool_arguments" for row in denied)
        or any(row["status"] != "permission_denied" for row in denied)
        or len({row["tool_call_id"] for row in row_snapshots}) != 4
    ):
        raise RuntimeError("live_e2e_mcp_audit_decision_failed")
    return {
        "allowed_count": len(allowed),
        "denied_count": len(denied),
        "lineage_complete_count": len(row_snapshots),
        "distinct_tool_call_count": len({row["tool_call_id"] for row in row_snapshots}),
    }


async def _compose_runtime(
    config: ConnectedRuntimeConfig,
    *,
    fake_google: FakeGoogleOidcProvider,
) -> ConnectedRuntime:
    client = _ClosableRewritingAsyncHttpClient(
        {
            GOOGLE_DISCOVERY_URL: fake_google.discovery_url,
            GOOGLE_AUTHORIZATION_ENDPOINT: fake_google.authorization_endpoint,
            GOOGLE_TOKEN_ENDPOINT: fake_google.token_endpoint,
            GOOGLE_JWKS_URI: fake_google.jwks_uri,
        }
    )
    return await ConnectedRuntime.compose(config, http_client=client)


def _initial_migrate_with_safe_diagnostics(runtime: ConnectedRuntime) -> dict[str, Any]:
    try:
        return runtime.migrate()
    except Exception:
        original_connection = runtime.repository.connection
        runtime.repository.connection = _MigrationDiagnosticConnection(original_connection)
        try:
            runtime.repository.apply_migrations()
        finally:
            runtime.repository.connection = original_connection
        raise RuntimeError("live_e2e_migration_wrapper_inconsistent") from None


def _schema_readiness_failure(repository: Any) -> str:
    query_one = repository.connection.query_one
    try:
        for index, table_name in enumerate(runtime_module._REQUIRED_OAUTH_TABLES, start=1):
            row = query_one(
                SQLStatement(
                    sql="SELECT to_regclass(%(table_name)s) AS relation",
                    parameters={"table_name": table_name},
                )
            )
            if type(row) is not dict:
                return f"table_{index}"
            relation = dict.get(row, "relation")
            if type(relation) is not str or not relation:
                return f"table_{index}"
        column_index = 0
        for table_name, column_names in runtime_module._REQUIRED_SCHEMA_COLUMNS.items():
            for column_name in column_names:
                column_index += 1
                row = query_one(
                    SQLStatement(
                        sql=(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name = %(table_name)s "
                            "AND column_name = %(column_name)s"
                        ),
                        parameters={
                            "table_name": table_name,
                            "column_name": column_name,
                        },
                    )
                )
                if type(row) is not dict:
                    return f"column_{column_index}"
                actual_column = dict.get(row, "column_name")
                if (
                    type(actual_column) is not str
                    or not actual_column
                    or actual_column != column_name
                ):
                    return f"column_{column_index}"
        for index, item in enumerate(runtime_module._REQUIRED_SCHEMA_CONSTRAINTS, start=1):
            table_name, constraint_type, constraint_name, constraint_pattern = item
            constraint_name_clause = (
                "AND conname = %(constraint_name)s " if constraint_name is not None else ""
            )
            row = query_one(
                SQLStatement(
                    sql=(
                        "SELECT conname AS constraint_name FROM pg_constraint "
                        "WHERE conrelid = to_regclass(%(table_name)s) "
                        "AND contype = %(constraint_type)s "
                        f"{constraint_name_clause}"
                        "AND pg_get_constraintdef(oid) LIKE %(constraint_pattern)s"
                    ),
                    parameters={
                        "table_name": table_name,
                        "constraint_type": constraint_type,
                        "constraint_name": constraint_name,
                        "constraint_pattern": constraint_pattern,
                    },
                )
            )
            if type(row) is not dict:
                return f"constraint_{index}"
            actual_name = dict.get(row, "constraint_name")
            if type(actual_name) is not str or not actual_name:
                return f"constraint_{index}"
        for index, relation_name in enumerate(runtime_module._REQUIRED_SCHEMA_INDEXES, start=1):
            row = query_one(
                SQLStatement(
                    sql="SELECT to_regclass(%(relation_name)s) AS relation",
                    parameters={"relation_name": relation_name},
                )
            )
            if type(row) is not dict:
                return f"index_{index}"
            relation = dict.get(row, "relation")
            if type(relation) is not str or not relation:
                return f"index_{index}"
    except Exception as error:
        return "exception_" + re.sub(r"[^a-z0-9]+", "_", type(error).__name__.lower())[:32]
    return "unknown"


async def _preflight_with_safe_diagnostics(runtime: ConnectedRuntime, *, stage: str) -> None:
    payload = await runtime.preflight()
    if type(payload) is not dict:
        raise RuntimeError(f"live_e2e_{stage}_preflight_unknown")
    payload_keys = tuple(dict.keys(payload))
    if (
        any(type(key) is not str for key in payload_keys)
        or len(payload_keys) != 3
        or set(payload_keys) != {"status", "mode", "checks"}
    ):
        raise RuntimeError(f"live_e2e_{stage}_preflight_unknown")
    status = dict.__getitem__(payload, "status")
    mode = dict.__getitem__(payload, "mode")
    checks = dict.__getitem__(payload, "checks")
    if (
        type(status) is not str
        or status == ""
        or type(mode) is not str
        or mode == ""
        or type(checks) is not dict
    ):
        raise RuntimeError(f"live_e2e_{stage}_preflight_unknown")
    check_keys = tuple(dict.keys(checks))
    if (
        any(type(key) is not str for key in check_keys)
        or len(check_keys) != 8
        or set(check_keys)
        != {
            "runtime",
            "database",
            "schema",
            "configuration",
            "oauth_callback",
            "signing_key",
            "google_oidc",
            "upload_store",
        }
    ):
        raise RuntimeError(f"live_e2e_{stage}_preflight_unknown")
    check_items = tuple(dict.items(checks))
    if any(type(value) is not bool for _, value in check_items):
        raise RuntimeError(f"live_e2e_{stage}_preflight_unknown")
    if status == "ready" and all(value is True for _, value in check_items):
        return
    failures: list[str] = []
    if dict.__getitem__(checks, "schema") is not True:
        failures.append("schema_" + _schema_readiness_failure(runtime.repository))
    if dict.__getitem__(checks, "google_oidc") is not True:
        google_reason = "unknown"
        google_cause = "none"
        try:
            await runtime.google_client.load_provider_metadata(refresh=True)
            await runtime.google_client.load_jwks(refresh=True)
        except Exception as error:
            candidate = getattr(error, "reason_code", None)
            if isinstance(candidate, str) and _SAFE_ERROR_RE.fullmatch(candidate):
                google_reason = candidate
            else:
                google_reason = re.sub(r"[^a-z0-9]+", "_", type(error).__name__.lower())[:32]
            cause = error.__cause__
            if cause is not None:
                google_cause = re.sub(r"[^a-z0-9]+", "_", type(cause).__name__.lower())[:24]
        history = getattr(runtime.http_client, "request_history", [])
        last_status = (
            history[-1].get("status")
            if isinstance(history, list) and history and isinstance(history[-1], Mapping)
            else None
        )
        status_label = str(last_status) if isinstance(last_status, int) else "none"
        failures.append(f"google_{google_reason}_{google_cause}_{status_label}")
    failures.extend(
        str(key)
        for key, value in sorted(check_items)
        if key not in {"schema", "google_oidc"} and value is not True
    )
    suffix = "_".join(failures) if failures else "unknown"
    raise RuntimeError(f"live_e2e_{stage}_preflight_{suffix}"[:96])


async def _run_inside(output_path: Path) -> dict[str, Any]:
    output_path = output_path.resolve()
    output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    output_artifacts = (output_path, output_helper_path)
    # A new execution must never inherit a previously passing report or helper.
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        for artifact_path in output_artifacts:
            artifact_path.unlink(missing_ok=True)
    except Exception:
        for artifact_path in output_artifacts:
            try:
                artifact_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise RuntimeError("live_e2e_output_isolation_failed") from None

    _load_inside_dependencies()
    dsn = os.environ.get(_INSIDE_DSN_ENV)
    data_dir_value = os.environ.get(_INSIDE_DATA_DIR_ENV)
    if not dsn or not data_dir_value:
        raise RuntimeError("live_e2e_environment_missing")
    data_dir = Path(data_dir_value)
    if not data_dir.is_absolute():
        raise RuntimeError("live_e2e_data_dir_invalid")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    clock = FakeClock(current=now)
    google_rng = DeterministicRng("connected-runtime-live-google")
    google_key = DeterministicRsaKey.generate(
        "connected-runtime-live-google-key",
        kid="google-live-key",
    )
    signing_key = generate_ephemeral_formowl_signing_key(kid="formowl-live-key")
    issuer = "https://formowl-live.example"
    oauth = OAuthBridgeConfig(
        issuer=issuer,
        resource=f"{issuer}/mcp",
        chatgpt_client_id="chatgpt-live-client",
        chatgpt_redirect_uri="https://chatgpt.com/connector/oauth/formowl-live-e2e",
        google_client_id="google-live-client",
        google_client_secret="synthetic-live-google-secret",
        google_redirect_uri=f"{issuer}/oauth/google/callback",
        state_encryption_key=Fernet.generate_key().decode("ascii"),
        access_token_lifetime_seconds=12,
        clock_skew_seconds=0,
    )
    config = ConnectedRuntimeConfig(
        oauth=oauth,
        database_dsn=dsn,
        signing_key_set=FormOwlSigningKeySet([signing_key]),
        host="127.0.0.1",
        port=8000,
        log_level="warning",
        data_dir=data_dir,
        upload_session_lifetime_seconds=3600,
        owner_bootstrap_operator_service_id="operator_live_e2e",
    )

    with FakeGoogleOidcProvider(
        clock=clock,
        rng=google_rng,
        signing_key=google_key,
        client_id=oauth.google_client_id,
        client_secret=oauth.google_client_secret,
    ) as fake_google:
        fake_google.set_account(
            FakeGoogleAccount(
                subject="google-live-owner-subject",
                email="live-owner@example.test",
            )
        )
        runtime = await _compose_runtime(config, fake_google=fake_google)
        migration = _initial_migrate_with_safe_diagnostics(runtime)
        rollback_probe = _run_transaction_rollback_probe(runtime, now=now)
        bootstrap = runtime.bootstrap_owner(
            workspace_id="workspace_live_e2e",
            email="live-owner@example.test",
            expires_at=now + timedelta(minutes=30),
            idempotency_key="live-e2e-owner-bootstrap-v1",
            operator_service_id="operator_live_e2e",
        )
        await _preflight_with_safe_diagnostics(runtime, stage="initial")

        access_token = ""
        first_sequence: dict[str, Any]
        with AsgiHttpServer(lambda _base_url: runtime.application.app) as server:
            chatgpt = _chatgpt_client(
                oauth=oauth,
                server_base_url=server.base_url,
                fake_google=fake_google,
                seed="connected-runtime-live-chatgpt-owner",
            )
            access_token = _complete_oauth_login(chatgpt, oauth)
            old_token_expires_at = _jwt_expiry(access_token)
            first_sequence = await run_official_mcp_client_sequence(
                f"{server.base_url}/mcp",
                bearer=access_token,
                tool_calls=(
                    ("whoami", {}),
                    (
                        "open_upload_session",
                        {
                            "intent": "Upload governed mail evidence.",
                            "intended_asset_type": "pst",
                        },
                    ),
                    (
                        "open_upload_session",
                        {
                            "intent": "Attempt another workspace.",
                            "intended_asset_type": "pst",
                            "owner_scope_type": "workspace",
                            "owner_scope_id": "workspace_other",
                            "visibility_scope": "workspace",
                        },
                    ),
                    (
                        "open_upload_session",
                        {
                            "intent": "Attempt caller identity forgery.",
                            "intended_asset_type": "pst",
                            "requester_user_id": "user_forged",
                        },
                    ),
                ),
            )
            first_whoami = _structured_call(first_sequence, "whoami")
            first_upload = _structured_call(first_sequence, "open_upload_session", occurrence=0)
            cross_workspace_denied = _tool_call_is_error(
                first_sequence, "open_upload_session", occurrence=1
            )
            identity_forgery_denied = _tool_call_is_error(
                first_sequence, "open_upload_session", occurrence=2
            )
            token_binding = _token_session_binding(runtime)
            sessions = UploadSessionStore(data_dir).list()
            file_audits = FileAuditLogStore(data_dir).list()
            if len(sessions) != 1 or len(file_audits) != 1:
                raise RuntimeError("live_e2e_upload_persistence_failed")
            stored_session = sessions[0]
            upload_audit = file_audits[0]
            try:
                first_whoami_user_id = first_whoami.get("user_id")
                token_session_id = token_binding["token_session_id"]
                token_user_id = token_binding["user_id"]
                token_workspace_id = token_binding["current_workspace_id"]
                stored_upload_session_id = getattr(
                    stored_session,
                    "upload_session_id",
                    None,
                )
                stored_actor_user_id = getattr(stored_session, "actor_user_id", None)
                stored_session_id = getattr(stored_session, "session_id", None)
                stored_workspace_id = getattr(stored_session, "workspace_id", None)
                stored_owner_scope_id = getattr(stored_session, "owner_scope_id", None)
                upload_audit_action = getattr(upload_audit, "action", None)
                upload_audit_target_type = getattr(upload_audit, "target_type", None)
                upload_audit_target_id = getattr(upload_audit, "target_id", None)
                upload_audit_status = getattr(upload_audit, "status", None)
                upload_audit_actor_user_id = getattr(upload_audit, "actor_user_id", None)
                upload_audit_session_id = getattr(upload_audit, "session_id", None)
                upload_audit_workspace_id = getattr(upload_audit, "workspace_id", None)
                upload_binding_values = (
                    first_whoami_user_id,
                    token_session_id,
                    token_user_id,
                    token_workspace_id,
                    stored_upload_session_id,
                    stored_actor_user_id,
                    stored_session_id,
                    stored_workspace_id,
                    stored_owner_scope_id,
                    upload_audit_action,
                    upload_audit_target_type,
                    upload_audit_target_id,
                    upload_audit_status,
                    upload_audit_actor_user_id,
                    upload_audit_session_id,
                    upload_audit_workspace_id,
                )
                upload_binding_values_are_plain_strings = all(
                    type(value) is str for value in upload_binding_values
                )
                upload_binding_ids_are_nonempty = upload_binding_values_are_plain_strings and all(
                    value
                    for value in (
                        first_whoami_user_id,
                        token_session_id,
                        token_user_id,
                        token_workspace_id,
                        stored_upload_session_id,
                        stored_actor_user_id,
                        stored_session_id,
                        stored_workspace_id,
                        stored_owner_scope_id,
                        upload_audit_target_id,
                        upload_audit_actor_user_id,
                        upload_audit_session_id,
                        upload_audit_workspace_id,
                    )
                )
                upload_file_audit_token_binding_verified = (
                    upload_binding_values_are_plain_strings
                    and upload_binding_ids_are_nonempty
                    and stored_actor_user_id == token_user_id
                    and stored_session_id == token_session_id
                    and stored_workspace_id == token_workspace_id
                    and upload_audit_action == "upload_session_created"
                    and upload_audit_target_type == "upload_session"
                    and upload_audit_target_id == stored_upload_session_id
                    and upload_audit_status == "ok"
                    and upload_audit_actor_user_id == token_user_id
                    and upload_audit_session_id == token_session_id
                    and upload_audit_workspace_id == token_workspace_id
                )
                upload_actor_binding_verified = (
                    upload_file_audit_token_binding_verified
                    and stored_actor_user_id == first_whoami_user_id
                    and stored_owner_scope_id == token_workspace_id
                    and upload_audit_actor_user_id == stored_actor_user_id
                    and upload_audit_session_id == stored_session_id
                    and upload_audit_workspace_id == stored_workspace_id
                )
            except Exception:
                raise RuntimeError("live_e2e_upload_actor_binding_failed") from None
            if not upload_actor_binding_verified:
                raise RuntimeError("live_e2e_upload_actor_binding_failed") from None
            owner_user_id = token_user_id
            mcp_audit_lineage = _validate_mcp_authorization_audit_lineage(
                runtime,
                token_binding={
                    "token_session_id": token_session_id,
                    "user_id": token_user_id,
                    "current_workspace_id": token_workspace_id,
                },
            )
            upload_audits = [upload_audit]
            owner_bootstrap = runtime.repository.get_owner_bootstrap("workspace_live_e2e")
            owner_invitation = runtime.repository.get_invitation(str(bootstrap["invitation_id"]))
            first_counts = {
                "migration_ledger": _count_rows(runtime, "formowl_schema_migrations"),
                "users": _count_rows(runtime, "formowl_users"),
                "workspace_members": _count_rows(runtime, "formowl_workspace_members"),
                "external_identities": _count_rows(runtime, "formowl_external_identities"),
                "invitations": _count_rows(runtime, "formowl_oauth_invitations"),
                "token_sessions": _count_rows(runtime, "formowl_oauth_token_sessions"),
                "postgres_audits": _count_rows(runtime, "formowl_audit_log"),
            }

        new_signing_key = generate_ephemeral_formowl_signing_key(kid="formowl-live-key-rotated")
        overlap_old_signing_key = FormOwlSigningKey(
            kid=signing_key.kid,
            private_key_pem=signing_key.private_key_pem,
            active=False,
            verify_until=old_token_expires_at + timedelta(seconds=1),
        )
        rotated_key_set = FormOwlSigningKeySet([overlap_old_signing_key, new_signing_key])
        rotated_oauth = replace(
            oauth,
            access_token_lifetime_seconds=60,
            clock_skew_seconds=0,
        )
        rotated_config = replace(
            config,
            oauth=rotated_oauth,
            signing_key_set=rotated_key_set,
        )
        restarted = await _compose_runtime(rotated_config, fake_google=fake_google)
        restart_migration = restarted.migrate()
        await _preflight_with_safe_diagnostics(restarted, stage="restart")
        with AsgiHttpServer(lambda _base_url: restarted.application.app) as restarted_server:
            rotation_probe = _chatgpt_client(
                oauth=rotated_oauth,
                server_base_url=restarted_server.base_url,
                fake_google=fake_google,
                seed="connected-runtime-live-rotation-probe",
            )
            overlap_jwks = _jwks_summary(rotation_probe.http.get(rotated_oauth.jwks_uri))
            restart_sequence = await run_official_mcp_client_sequence(
                f"{restarted_server.base_url}/mcp",
                bearer=access_token,
                tool_calls=(("whoami", {}),),
            )
            restart_whoami = _structured_call(restart_sequence, "whoami")
            restart_sessions = UploadSessionStore(data_dir).list()
            restart_upload_audits = [
                audit
                for audit in FileAuditLogStore(data_dir).list()
                if audit.action == "upload_session_created"
            ]
            restart_counts = {
                "migration_ledger": _count_rows(restarted, "formowl_schema_migrations"),
                "users": _count_rows(restarted, "formowl_users"),
                "workspace_members": _count_rows(restarted, "formowl_workspace_members"),
                "external_identities": _count_rows(restarted, "formowl_external_identities"),
                "invitations": _count_rows(restarted, "formowl_oauth_invitations"),
                "token_sessions": _count_rows(restarted, "formowl_oauth_token_sessions"),
                "postgres_audits": _count_rows(restarted, "formowl_audit_log"),
            }

            second_invitation = restarted.invite_user(
                workspace_id="workspace_live_e2e",
                email="live-member@example.test",
                role="member",
                invited_by_user_id=owner_user_id,
                operator_service_id="operator_live_e2e",
                expires_at=now + timedelta(minutes=30),
            )
            fake_google.set_account(
                FakeGoogleAccount(
                    subject="google-live-member-subject",
                    email="live-member@example.test",
                )
            )
            second_chatgpt = _chatgpt_client(
                oauth=rotated_oauth,
                server_base_url=restarted_server.base_url,
                fake_google=fake_google,
                seed="connected-runtime-live-chatgpt-member",
            )
            second_access_token = _complete_oauth_login(second_chatgpt, rotated_oauth)
            second_sequence = await run_official_mcp_client_sequence(
                f"{restarted_server.base_url}/mcp",
                bearer=second_access_token,
                tool_calls=(("whoami", {}),),
            )
            second_whoami = _structured_call(second_sequence, "whoami")
            second_user_id = str(second_whoami.get("user_id", ""))
            second_token_kid = _jwt_kid(second_access_token)
            second_token_binding = _latest_token_session_binding_for_user(
                restarted,
                user_id=second_user_id,
            )
            accepted_second_invitation = restarted.repository.get_invitation(
                str(second_invitation["invitation_id"])
            )
            second_counts = {
                "users": _count_rows(restarted, "formowl_users"),
                "workspace_members": _count_rows(restarted, "formowl_workspace_members"),
                "external_identities": _count_rows(restarted, "formowl_external_identities"),
                "accepted_invitations": _count_oauth_state(restarted, "accepted_invitations"),
            }
            if (
                accepted_second_invitation is None
                or accepted_second_invitation.status != "accepted"
                or not second_user_id
                or second_whoami.get("user_id") == owner_user_id
                or second_whoami.get("current_workspace")
                != {"workspace_id": "workspace_live_e2e", "role": "member"}
                or second_counts
                != {
                    "users": 2,
                    "workspace_members": 2,
                    "external_identities": 2,
                    "accepted_invitations": 2,
                }
            ):
                raise RuntimeError("live_e2e_second_user_mapping_failed")

        overlap_end = overlap_old_signing_key.verify_until
        assert overlap_end is not None
        wait_seconds = max(
            0.0,
            (overlap_end - datetime.now(timezone.utc)).total_seconds() + 0.25,
        )
        if wait_seconds > 20:
            raise RuntimeError("live_e2e_rotation_wait_unbounded")
        await asyncio.sleep(wait_seconds)
        retirement_observed_at = datetime.now(timezone.utc)
        if retirement_observed_at <= old_token_expires_at or retirement_observed_at <= overlap_end:
            raise RuntimeError("live_e2e_rotation_overlap_not_elapsed")

        retired_key_set = FormOwlSigningKeySet([new_signing_key])
        retired_config = replace(
            config,
            oauth=rotated_oauth,
            signing_key_set=retired_key_set,
        )
        post_overlap_runtime = await _compose_runtime(
            retired_config,
            fake_google=fake_google,
        )
        post_overlap_migration = post_overlap_runtime.migrate()
        await _preflight_with_safe_diagnostics(post_overlap_runtime, stage="post_overlap")
        with AsgiHttpServer(
            lambda _base_url: post_overlap_runtime.application.app
        ) as post_overlap_server:
            post_overlap_probe = _chatgpt_client(
                oauth=rotated_oauth,
                server_base_url=post_overlap_server.base_url,
                fake_google=fake_google,
                seed="connected-runtime-live-post-overlap-probe",
            )
            post_overlap_jwks = _jwks_summary(post_overlap_probe.http.get(rotated_oauth.jwks_uri))
            retired_old_token_response = post_overlap_probe.mcp_call(
                f"{post_overlap_server.base_url}/mcp",
                _initialize_request("live_e2e_retired_old_key_token"),
                bearer=access_token,
            )
            retired_old_token_denial_shape = _assert_bearer_denied(retired_old_token_response)
            post_overlap_new_sequence = await run_official_mcp_client_sequence(
                f"{post_overlap_server.base_url}/mcp",
                bearer=second_access_token,
                tool_calls=(("whoami", {}),),
            )
            post_overlap_new_whoami = _structured_call(
                post_overlap_new_sequence,
                "whoami",
            )
            if post_overlap_new_whoami.get("user_id") != second_user_id:
                raise RuntimeError("live_e2e_post_overlap_new_token_failed")
            post_overlap_runtime.revoke_token_session(
                token_session_id=second_token_binding["token_session_id"],
                reason_code="live_e2e_revoked",
                operator_service_id="operator_live_e2e",
            )
            revoked_response = post_overlap_probe.mcp_call(
                f"{post_overlap_server.base_url}/mcp",
                _initialize_request("live_e2e_revoked_token"),
                bearer=second_access_token,
            )
            revoked_denial_shape = _assert_bearer_denied(revoked_response)
            if _count_oauth_state(post_overlap_runtime, "revoked_token_sessions") != 1:
                raise RuntimeError("live_e2e_token_revocation_state_failed")

        short_oauth = replace(
            rotated_oauth,
            access_token_lifetime_seconds=1,
            clock_skew_seconds=0,
        )
        expiry_config = replace(retired_config, oauth=short_oauth)
        expiry_runtime = await _compose_runtime(expiry_config, fake_google=fake_google)
        expiry_migration = expiry_runtime.migrate()
        await _preflight_with_safe_diagnostics(expiry_runtime, stage="expiry")
        fake_google.set_account(
            FakeGoogleAccount(
                subject="google-live-member-subject",
                email="live-member@example.test",
            )
        )
        with AsgiHttpServer(lambda _base_url: expiry_runtime.application.app) as expiry_server:
            relink_chatgpt = _chatgpt_client(
                oauth=short_oauth,
                server_base_url=expiry_server.base_url,
                fake_google=fake_google,
                seed="connected-runtime-live-chatgpt-owner-relink",
            )
            relink_access_token = _complete_oauth_login(relink_chatgpt, short_oauth)
            relink_sequence = await run_official_mcp_client_sequence(
                f"{expiry_server.base_url}/mcp",
                bearer=relink_access_token,
                tool_calls=(("whoami", {}),),
            )
            relink_whoami = _structured_call(relink_sequence, "whoami")
            if relink_whoami.get("user_id") != second_user_id:
                raise RuntimeError("live_e2e_relink_identity_failed")
            relink_token_binding = _latest_token_session_binding_for_user(
                expiry_runtime,
                user_id=second_user_id,
            )
            old_revoked_token_session = expiry_runtime.repository.get_token_session(
                second_token_binding["token_session_id"]
            )
            relinked_token_session = expiry_runtime.repository.get_token_session(
                relink_token_binding["token_session_id"]
            )
            revoked_token_sessions_after_relink = _count_oauth_state(
                expiry_runtime,
                "revoked_token_sessions",
            )
            if (
                old_revoked_token_session is None
                or relinked_token_session is None
                or relink_token_binding["token_session_id"]
                == second_token_binding["token_session_id"]
                or old_revoked_token_session.token_session_id
                != second_token_binding["token_session_id"]
                or relinked_token_session.token_session_id
                != relink_token_binding["token_session_id"]
                or old_revoked_token_session.user_id != second_user_id
                or relinked_token_session.user_id != second_user_id
                or old_revoked_token_session.current_workspace_id != "workspace_live_e2e"
                or relinked_token_session.current_workspace_id != "workspace_live_e2e"
                or old_revoked_token_session.revoked_at is None
                or relinked_token_session.revoked_at is not None
                or revoked_token_sessions_after_relink != 1
            ):
                raise RuntimeError("live_e2e_relink_token_session_lineage_failed")
            relink_token_session_lineage = {
                "old_token_session_id": old_revoked_token_session.token_session_id,
                "old_user_id": old_revoked_token_session.user_id,
                "old_workspace_id": old_revoked_token_session.current_workspace_id,
                "old_session_revoked": old_revoked_token_session.revoked_at is not None,
                "relinked_token_session_id": relinked_token_session.token_session_id,
                "relinked_user_id": relinked_token_session.user_id,
                "relinked_workspace_id": relinked_token_session.current_workspace_id,
                "relinked_session_revoked": relinked_token_session.revoked_at is not None,
                "distinct_token_session_ids": (
                    old_revoked_token_session.token_session_id
                    != relinked_token_session.token_session_id
                ),
            }
            post_relink_revoked_response = relink_chatgpt.mcp_call(
                f"{expiry_server.base_url}/mcp",
                _initialize_request("live_e2e_post_relink_revoked_token"),
                bearer=second_access_token,
            )
            post_relink_revoked_denial_shape = _assert_bearer_denied(
                post_relink_revoked_response,
                expected_metadata_url=short_oauth.protected_resource_metadata_url,
            )
            await asyncio.sleep(2)
            expired_response = relink_chatgpt.mcp_call(
                f"{expiry_server.base_url}/mcp",
                _initialize_request("live_e2e_expired_token"),
                bearer=relink_access_token,
            )
            expiry_denial_shape = _assert_bearer_denied(
                expired_response,
                expected_metadata_url=short_oauth.protected_resource_metadata_url,
            )
            final_sessions = UploadSessionStore(data_dir).list()
            final_upload_audits = [
                audit
                for audit in FileAuditLogStore(data_dir).list()
                if audit.action == "upload_session_created"
            ]
            final_counts = {
                "users": _count_rows(expiry_runtime, "formowl_users"),
                "workspace_members": _count_rows(expiry_runtime, "formowl_workspace_members"),
                "external_identities": _count_rows(expiry_runtime, "formowl_external_identities"),
                "accepted_invitations": _count_oauth_state(expiry_runtime, "accepted_invitations"),
                "token_sessions": _count_rows(expiry_runtime, "formowl_oauth_token_sessions"),
                "postgres_audits": _count_rows(expiry_runtime, "formowl_audit_log"),
                "revoked_token_sessions": _count_oauth_state(
                    expiry_runtime, "revoked_token_sessions"
                ),
            }

    protocol_version = str(first_sequence.get("initialize", {}).get("protocolVersion", ""))
    tool_names = _listed_tool_names(first_sequence)
    metrics = {
        "fresh_database_migrated": (
            first_counts["migration_ledger"] == 5
            and migration.get("applied_migration_count") == 5
            and migration.get("skipped_migration_count") == 0
        ),
        "migration_ledger_replayed_without_duplication": (
            restart_counts["migration_ledger"] == first_counts["migration_ledger"]
            and restart_migration.get("applied_migration_count") == 0
            and restart_migration.get("skipped_migration_count") == 5
            and post_overlap_migration.get("applied_migration_count") == 0
            and post_overlap_migration.get("skipped_migration_count") == 5
            and expiry_migration.get("applied_migration_count") == 0
            and expiry_migration.get("skipped_migration_count") == 5
        ),
        "transaction_rollback_verified": rollback_probe
        == {"before_user_count": 0, "after_user_count": 0, "probe_count": 1},
        "operator_owner_bootstrap_completed": (
            first_counts["users"] == 1
            and first_counts["workspace_members"] == 1
            and first_counts["external_identities"] == 1
            and first_counts["invitations"] == 1
            and owner_bootstrap is not None
            and owner_bootstrap.status == "completed"
            and owner_invitation is not None
            and owner_invitation.status == "accepted"
        ),
        "oauth_pkce_formowl_token_completed": bool(access_token),
        "official_streamable_http_mcp_completed": protocol_version == LATEST_PROTOCOL_VERSION,
        "whoami_actor_context_verified": (
            first_whoami.get("auth_mode") == "google_oidc_oauth"
            and first_whoami.get("current_workspace")
            == {"workspace_id": "workspace_live_e2e", "role": "owner"}
            and first_whoami_user_id == restart_whoami.get("user_id")
        ),
        "server_bound_upload_persisted": (
            len(sessions) == 1 and len(upload_audits) == 1 and first_upload.get("status") == "ok"
        ),
        "postgres_auth_and_audit_persisted": (
            first_counts["token_sessions"] == 1 and first_counts["postgres_audits"] > 0
        ),
        "restart_existing_token_verified": (restart_whoami.get("user_id") == first_whoami_user_id),
        "restart_upload_and_file_audit_persisted": (
            len(restart_sessions) == 1 and len(restart_upload_audits) == 1
        ),
        "signing_key_rotation_overlap_verified": (
            restart_whoami.get("user_id") == owner_user_id
            and overlap_jwks["key_count"] == 2
            and overlap_jwks["kids"] == sorted([signing_key.kid, new_signing_key.kid])
        ),
        "signing_key_rotation_jwks_public_only_verified": (
            overlap_jwks["private_key_exposure_count"] == 0
            and post_overlap_jwks["private_key_exposure_count"] == 0
        ),
        "signing_key_rotation_new_token_verified": (
            second_token_kid == new_signing_key.kid
            and post_overlap_new_whoami.get("user_id") == second_user_id
        ),
        "signing_key_rotation_retirement_verified": (
            retirement_observed_at > old_token_expires_at
            and retirement_observed_at > overlap_end
            and retired_old_token_denial_shape["status"] == 401
            and post_overlap_jwks["key_count"] == 1
            and post_overlap_jwks["kids"] == [new_signing_key.kid]
        ),
        "upload_file_audit_token_binding_verified": (upload_file_audit_token_binding_verified),
        "cross_workspace_and_forgery_denied": (
            cross_workspace_denied
            and identity_forgery_denied
            and len(sessions) == 1
            and len(upload_audits) == 1
        ),
        "postgres_mcp_audit_lineage_verified": mcp_audit_lineage
        == {
            "allowed_count": 2,
            "denied_count": 2,
            "lineage_complete_count": 4,
            "distinct_tool_call_count": 4,
        },
        "second_user_invitation_and_mapping_verified": (
            second_counts["users"] == 2
            and second_counts["workspace_members"] == 2
            and second_counts["external_identities"] == 2
            and second_counts["accepted_invitations"] == 2
        ),
        "revoked_token_denied": (
            revoked_denial_shape["status"] == 401 and final_counts["revoked_token_sessions"] == 1
        ),
        "revoked_token_stays_denied_after_relink": (
            post_relink_revoked_denial_shape["status"] == 401
            and post_relink_revoked_denial_shape["challenge_exact"] is True
            and post_relink_revoked_denial_shape["body_exact"] is True
            and revoked_token_sessions_after_relink == 1
        ),
        "same_subject_relink_verified": (
            relink_whoami.get("user_id") == second_user_id
            and final_counts["users"] == 2
            and final_counts["external_identities"] == 2
            and final_counts["token_sessions"] == 3
        ),
        "relink_token_session_lineage_separated": (
            relink_token_session_lineage["distinct_token_session_ids"] is True
            and relink_token_session_lineage["old_user_id"]
            == relink_token_session_lineage["relinked_user_id"]
            == second_user_id
            and relink_token_session_lineage["old_workspace_id"]
            == relink_token_session_lineage["relinked_workspace_id"]
            == "workspace_live_e2e"
            and relink_token_session_lineage["old_session_revoked"] is True
            and relink_token_session_lineage["relinked_session_revoked"] is False
            and revoked_token_sessions_after_relink == 1
        ),
        "relinked_token_expiry_denied": (
            expiry_denial_shape["status"] == 401
            and expiry_denial_shape["challenge_exact"] is True
            and expiry_denial_shape["body_exact"] is True
        ),
        "exact_connected_tool_surface_verified": tool_names == ["open_upload_session", "whoami"],
        "raw_secret_or_path_exposed": False,
    }
    safe_counts = {
        "migration_ledger_rows": first_counts["migration_ledger"],
        "migration_applied_count": int(migration["applied_migration_count"]),
        "migration_restart_skipped_count": int(restart_migration["skipped_migration_count"]),
        "postgres_audit_rows_before_restart": first_counts["postgres_audits"],
        "postgres_audit_rows_after_all_journeys": final_counts["postgres_audits"],
        "persisted_upload_session_rows": len(final_sessions),
        "persisted_file_audit_rows": len(final_upload_audits),
        "listed_tool_count": len(tool_names),
        "user_rows_after_second_login": final_counts["users"],
        "workspace_member_rows_after_second_login": final_counts["workspace_members"],
        "external_identity_rows_after_second_login": final_counts["external_identities"],
        "accepted_invitation_rows_after_second_login": final_counts["accepted_invitations"],
        "token_session_rows_after_all_journeys": final_counts["token_sessions"],
        "revoked_token_denial_count": 1,
        "post_relink_old_token_denial_count": (
            1
            if (
                post_relink_revoked_denial_shape["status"] == 401
                and post_relink_revoked_denial_shape["challenge_exact"] is True
                and post_relink_revoked_denial_shape["body_exact"] is True
            )
            else 0
        ),
        "revoked_token_sessions_after_relink_count": revoked_token_sessions_after_relink,
        "relink_distinct_token_session_count": (
            1 if relink_token_session_lineage["distinct_token_session_ids"] is True else 0
        ),
        "expiry_denial_count": (
            1
            if (
                expiry_denial_shape["status"] == 401
                and expiry_denial_shape["challenge_exact"] is True
                and expiry_denial_shape["body_exact"] is True
            )
            else 0
        ),
        "relink_count": 1,
        "transaction_rollback_probe_count": rollback_probe["probe_count"],
        "postgres_mcp_allowed_audit_count": mcp_audit_lineage["allowed_count"],
        "postgres_mcp_denied_audit_count": mcp_audit_lineage["denied_count"],
        "postgres_mcp_lineage_complete_count": mcp_audit_lineage["lineage_complete_count"],
        "cross_workspace_denial_count": 1 if cross_workspace_denied else 0,
        "identity_forgery_denial_count": 1 if identity_forgery_denied else 0,
        "signing_key_rotation_count": 1,
        "overlap_old_token_verification_count": 1,
        "overlap_jwks_public_key_count": overlap_jwks["key_count"],
        "new_key_token_verification_count": 1,
        "post_overlap_old_token_denial_count": 1,
        "post_overlap_jwks_public_key_count": post_overlap_jwks["key_count"],
        "post_overlap_new_token_verification_count": 1,
        "private_signing_key_exposure_count": (
            overlap_jwks["private_key_exposure_count"]
            + post_overlap_jwks["private_key_exposure_count"]
        ),
    }
    implementation_contract_hash = issue20_implementation_contract_hash(ROOT)
    safe_hashes = {
        "implementation_contract_hash": implementation_contract_hash,
        "command_contract_hash": _command_contract_hash(implementation_contract_hash),
        "schema_state_hash": _evidence_hash(
            "schema_state",
            {
                "first_migration": migration,
                "restart_migration": restart_migration,
                "post_overlap_migration": post_overlap_migration,
                "expiry_migration": expiry_migration,
                "ledger_rows": final_counts.get(
                    "migration_ledger", first_counts["migration_ledger"]
                ),
            },
        ),
        "rollback_state_hash": _evidence_hash("rollback_state", rollback_probe),
        "first_owner_bootstrap_state_hash": _evidence_hash(
            "first_owner_bootstrap_state",
            {
                "counts": first_counts,
                "bootstrap_status": owner_bootstrap.status if owner_bootstrap else "missing",
                "invitation_status": owner_invitation.status if owner_invitation else "missing",
            },
        ),
        "persisted_auth_upload_audit_state_hash": _evidence_hash(
            "persisted_auth_upload_audit_state",
            {
                "counts": safe_counts,
                "upload_shape": _shape(final_sessions[0].to_dict()),
                "mcp_audit_lineage": mcp_audit_lineage,
            },
        ),
        "restart_state_hash": _evidence_hash(
            "restart_state",
            {
                "counts": restart_counts,
                "mcp_shape": _shape(restart_sequence),
            },
        ),
        "second_user_invitation_state_hash": _evidence_hash(
            "second_user_invitation_state",
            {
                "counts": second_counts,
                "mcp_shape": _shape(second_sequence),
            },
        ),
        "revocation_expiry_relink_state_hash": _evidence_hash(
            "revocation_expiry_relink_state",
            {
                "revoked_denial_shape": revoked_denial_shape,
                "relink_mcp_shape": _shape(relink_sequence),
                "post_relink_revoked_denial_shape": post_relink_revoked_denial_shape,
                "revoked_token_sessions_after_relink_count": (revoked_token_sessions_after_relink),
                "relink_token_session_lineage": relink_token_session_lineage,
                "expiry_denial_shape": expiry_denial_shape,
                "final_counts": final_counts,
            },
        ),
        "signing_key_rotation_state_hash": _evidence_hash(
            "signing_key_rotation_state",
            {
                "overlap_covers_old_token": overlap_end > old_token_expires_at,
                "overlap_jwks": overlap_jwks,
                "overlap_old_token_mcp_shape": _shape(restart_sequence),
                "new_token_kid_matches": second_token_kid == new_signing_key.kid,
                "retirement_after_token_and_overlap": (
                    retirement_observed_at > old_token_expires_at
                    and retirement_observed_at > overlap_end
                ),
                "post_overlap_jwks": post_overlap_jwks,
                "post_overlap_old_token_denial_shape": retired_old_token_denial_shape,
                "post_overlap_new_token_mcp_shape": _shape(post_overlap_new_sequence),
            },
        ),
        "first_mcp_result_shape_hash": _evidence_hash(
            "first_mcp_result_shape", _shape(first_sequence)
        ),
        "persisted_upload_shape_hash": _evidence_hash(
            "persisted_upload_shape", _shape(final_sessions[0].to_dict())
        ),
    }
    claims = {
        "live_postgresql": True,
        "production_oauth_and_mcp_runtime": True,
        "production_upload_and_file_audit_stores": True,
        "fake_google_oidc": True,
        "live_google_account": False,
        "live_chatgpt_connector": False,
        "live_postgresql_external_layer_contract": True,
        "revoke_and_expiry_relink_verified": True,
        "second_user_invitation_verified": True,
        "cross_workspace_verified": True,
        "signing_key_rotation_verified": True,
        "whole_issue_20_complete": False,
        "production_readiness": False,
    }
    report: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "status": "passed" if _metrics_pass(metrics) else "failed",
        "protocol_version": protocol_version,
        "metrics": metrics,
        "safe_counts": safe_counts,
        "safe_hashes": safe_hashes,
        "claim_boundary": claims,
    }
    report["live_postgresql_layer"] = build_live_postgresql_layer(report)
    try:
        validation = validate_report(report)
    except Exception:
        raise RuntimeError("live_e2e_report_validation_failed") from None
    if not isinstance(validation, Mapping) or validation.get("passed") is not True:
        raise RuntimeError("live_e2e_report_validation_failed")
    try:
        write_json_atomic(output_path, report)
    except Exception:
        for artifact_path in output_artifacts:
            try:
                artifact_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise RuntimeError("live_e2e_report_persist_failed") from None
    return report


def build_live_postgresql_layer(report: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministically convert the safe report into the harness layer shape."""

    metrics = report.get("metrics")
    counts = report.get("safe_counts")
    hashes = report.get("safe_hashes")
    claims = report.get("claim_boundary")
    if not all(isinstance(item, Mapping) for item in (metrics, counts, hashes, claims)):
        return {}
    metrics = dict(metrics)
    counts = dict(counts)
    hashes = dict(hashes)
    claims = dict(claims)
    passed = (
        report.get("artifact_id") == ARTIFACT_ID
        and report.get("status") == "passed"
        and _metrics_pass(metrics)
        and claims.get("live_postgresql_external_layer_contract") is True
        and hashes.get("implementation_contract_hash") == issue20_implementation_contract_hash(ROOT)
    )
    source_report_commitment_hash = _evidence_hash(
        "live_postgresql_source_report_commitment_v1",
        {
            "artifact_id": report.get("artifact_id"),
            "status": report.get("status"),
            "protocol_version": report.get("protocol_version"),
            "metrics": metrics,
            "safe_counts": counts,
            "safe_hashes": hashes,
            "claim_boundary": claims,
        },
    )

    def journey(metric: str) -> int:
        return 1 if metrics.get(metric) is True else 0

    layer = {
        "status": "passed" if passed else "failed",
        "operator_attested": passed,
        "endpoint_scheme": "postgresql",
        "source_report_commitment_hash": source_report_commitment_hash,
        "implementation_contract_hash": hashes.get("implementation_contract_hash"),
        "command_contract_hash": hashes.get("command_contract_hash"),
        "schema_state_hash": hashes.get("schema_state_hash"),
        "rollback_state_hash": hashes.get("rollback_state_hash"),
        "first_owner_bootstrap_state_hash": hashes.get("first_owner_bootstrap_state_hash"),
        "persisted_auth_upload_audit_state_hash": hashes.get(
            "persisted_auth_upload_audit_state_hash"
        ),
        "restart_state_hash": hashes.get("restart_state_hash"),
        "second_user_invitation_state_hash": hashes.get("second_user_invitation_state_hash"),
        "revocation_expiry_relink_state_hash": hashes.get("revocation_expiry_relink_state_hash"),
        "signing_key_rotation_state_hash": hashes.get("signing_key_rotation_state_hash"),
        "run_count": 1,
        "pass_count": 1 if passed else 0,
        "failure_count": 0 if passed else 1,
        "skip_count": 0,
        "fresh_database_count": journey("fresh_database_migrated"),
        "migration_count": journey("migration_ledger_replayed_without_duplication"),
        "first_owner_bootstrap_count": journey("operator_owner_bootstrap_completed"),
        "persisted_auth_count": journey("postgres_auth_and_audit_persisted"),
        "persisted_upload_count": journey("server_bound_upload_persisted"),
        "persisted_audit_count": counts.get("postgres_audit_rows_after_all_journeys", 0),
        "restart_recovery_count": journey("restart_existing_token_verified"),
        "second_user_invitation_count": journey("second_user_invitation_and_mapping_verified"),
        "revocation_count": journey("revoked_token_denied"),
        "post_relink_old_token_denial_count": counts.get("post_relink_old_token_denial_count", 0),
        "revoked_token_sessions_after_relink_count": counts.get(
            "revoked_token_sessions_after_relink_count", 0
        ),
        "relink_distinct_token_session_count": counts.get("relink_distinct_token_session_count", 0),
        "expiry_denial_count": counts.get("expiry_denial_count", 0),
        "relink_count": counts.get("relink_count", 0),
        "transaction_rollback_probe_count": counts.get("transaction_rollback_probe_count", 0),
        "production_smoke_probe_count": journey("official_streamable_http_mcp_completed"),
        "signing_key_rotation_count": counts.get("signing_key_rotation_count", 0),
        "overlap_old_token_verification_count": counts.get(
            "overlap_old_token_verification_count", 0
        ),
        "overlap_jwks_public_key_count": counts.get("overlap_jwks_public_key_count", 0),
        "new_key_token_verification_count": counts.get("new_key_token_verification_count", 0),
        "post_overlap_old_token_denial_count": counts.get("post_overlap_old_token_denial_count", 0),
        "post_overlap_jwks_public_key_count": counts.get("post_overlap_jwks_public_key_count", 0),
        "post_overlap_new_token_verification_count": counts.get(
            "post_overlap_new_token_verification_count", 0
        ),
        "private_signing_key_exposure_count": counts.get("private_signing_key_exposure_count", 0),
        "attestations": {
            "live_server_observed": passed,
            "production_repository_used": passed,
            "no_fake_database": passed,
            "no_sensitive_material_in_packet": passed,
        },
    }
    layer["evidence_artifact_hash"] = _evidence_hash(
        "live_postgresql_external_layer_v3",
        layer,
    )
    return layer


def _run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    if (
        type(command) is not list
        or type(check) is not bool
        or not command
        or any(type(value) is not str or value == "" for value in command)
    ):
        raise RuntimeError("live_e2e_command_invalid") from None
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, UnicodeError):
        raise RuntimeError("live_e2e_command_failed") from None
    if check and result.returncode != 0:
        safe_code = "live_e2e_command_failed"
        for line in reversed(result.stderr.splitlines()):
            try:
                payload = json.loads(line)
            except (ValueError, RecursionError):
                continue
            candidate = payload.get("error") if isinstance(payload, Mapping) else None
            if isinstance(candidate, str) and _SAFE_ERROR_RE.fullmatch(candidate):
                safe_code = candidate
                break
        raise RuntimeError(safe_code)
    return result


def run_live_e2e(
    output_path: Path,
    *,
    runner_image_id: str | None,
) -> dict[str, Any]:
    output_path = output_path.resolve()
    output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    output_artifacts = (output_path, output_helper_path)
    # The final path stays absent until the isolated nested report passes validation.
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        for artifact_path in output_artifacts:
            artifact_path.unlink(missing_ok=True)
    except Exception:
        for artifact_path in output_artifacts:
            try:
                artifact_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise RuntimeError("live_e2e_output_isolation_failed") from None

    if runner_image_id is None or _SHA256_RE.fullmatch(runner_image_id) is None:
        raise RuntimeError("runner_image_id_required")
    authority_image_id = os.environ.get("FORMOWL_RUNNER_IMAGE_ID")
    if authority_image_id is None:
        raise RuntimeError("runner_image_id_authority_missing")
    if authority_image_id != runner_image_id:
        raise RuntimeError("runner_image_id_authority_mismatch")
    postgres_image = _require_pinned_postgres_image()
    source_root = _campaign_source_root(runner_image_id)
    _verify_campaign_source_mount(source_root, runner_image_id)
    campaign_pin_path: Path | None = None
    campaign_pin_hash: str | None = None
    if source_root != ROOT:
        campaign_pin_value = os.environ.get(_RUNNER_CAMPAIGN_PIN_ENV)
        campaign_pin_hash = os.environ.get(_RUNNER_CAMPAIGN_PIN_SHA256_ENV)
        if (
            type(campaign_pin_value) is not str
            or type(campaign_pin_hash) is not str
            or _SHA256_RE.fullmatch(campaign_pin_hash) is None
        ):
            raise RuntimeError("live_e2e_campaign_source_invalid")
        campaign_pin_path = Path(campaign_pin_value)

    suffix = uuid.uuid4().hex[:12]
    network_name = f"formowl-live-e2e-{suffix}"
    postgres_name = f"formowl-live-postgres-{suffix}"
    published = False
    try:
        with tempfile.TemporaryDirectory(
            prefix="formowl-live-e2e-",
            ignore_cleanup_errors=True,
        ) as temporary:
            temp_root = Path(temporary)
            data_dir = temp_root / "data"
            exchange_dir = temp_root / "exchange"
            data_dir.mkdir()
            exchange_dir.mkdir()
            run_output_path = exchange_dir / f"run-{suffix}.json"
            run_output_helper_path = run_output_path.with_suffix(f"{run_output_path.suffix}.tmp")
            private_artifacts = (
                run_output_path,
                run_output_helper_path,
            )
            postgres_started = False
            network_created = False
            try:
                try:
                    _run_command(["docker", "network", "create", network_name])
                    network_created = True
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
                            "POSTGRES_HOST_AUTH_METHOD=trust",
                            postgres_image,
                        ]
                    )
                    postgres_started = True
                    ready = False
                    for _attempt in range(60):
                        probe = _run_command(
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
                        if probe.returncode == 0:
                            ready = True
                            break
                        time.sleep(1)
                    if not ready:
                        raise RuntimeError("live_e2e_postgres_not_ready")
                    nested_command = [
                        "docker",
                        "run",
                        "--rm",
                        "--user",
                        f"{os.getuid()}:{os.getgid()}",
                        "--network",
                        network_name,
                        "-v",
                        f"{source_root}:/workspace:ro",
                        "-v",
                        f"{data_dir}:/live-data",
                        "-v",
                        f"{exchange_dir}:/out",
                        "-w",
                        "/workspace",
                        "-e",
                        (
                            f"{_INSIDE_DSN_ENV}=postgresql://formowl@"
                            f"{postgres_name}:5432/formowl"
                        ),
                        "-e",
                        f"{_INSIDE_DATA_DIR_ENV}=/live-data",
                        "-e",
                        f"FORMOWL_RUNNER_IMAGE_ID={runner_image_id}",
                    ]
                    if campaign_pin_path is not None and campaign_pin_hash is not None:
                        nested_command.extend(
                            [
                                "--read-only",
                                "--tmpfs",
                                "/tmp:rw,exec,nosuid,nodev,size=512m,mode=1777",
                                "--mount",
                                (
                                    f"type=bind,src={campaign_pin_path},"
                                    "dst=/campaign-pin.json,readonly"
                                ),
                                runner_image_id,
                                "python",
                                "-c",
                                _NESTED_CAMPAIGN_EXEC_PROGRAM,
                                "/workspace",
                                "/campaign-pin.json",
                                campaign_pin_hash,
                                runner_image_id,
                                "/tmp",
                                ("/workspace/scripts/" "connected_runtime_postgres_live_e2e.py"),
                            ]
                        )
                    else:
                        nested_command.extend(
                            [
                                runner_image_id,
                                "python",
                                ("/workspace/scripts/" "connected_runtime_postgres_live_e2e.py"),
                            ]
                        )
                    nested_command.extend(
                        [
                            "--inside",
                            "--runner-image-id",
                            runner_image_id,
                            "--output",
                            f"/out/{run_output_path.name}",
                        ]
                    )
                    _run_command(nested_command)
                finally:
                    if postgres_started:
                        try:
                            _run_command(["docker", "stop", postgres_name], check=False)
                        except Exception:
                            pass
                    if network_created:
                        try:
                            _run_command(["docker", "network", "rm", network_name], check=False)
                        except Exception:
                            pass

                if not run_output_path.is_file():
                    raise RuntimeError("live_e2e_report_missing")
                try:
                    report = json.loads(run_output_path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    raise RuntimeError("live_e2e_report_missing") from None
                except (OSError, UnicodeError, json.JSONDecodeError):
                    raise RuntimeError("live_e2e_report_parse_failed") from None
                try:
                    validation = validate_report(report)
                except Exception:
                    raise RuntimeError("live_e2e_report_validation_failed") from None
                if not isinstance(validation, Mapping) or validation.get("passed") is not True:
                    raise RuntimeError("live_e2e_report_validation_failed")
                try:
                    write_json_atomic(output_path, report)
                except Exception:
                    for artifact_path in output_artifacts:
                        try:
                            artifact_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                    raise RuntimeError("live_e2e_report_persist_failed") from None
                published = True
                return report
            finally:
                # Explicit cleanup is best effort; the private directory is the boundary.
                for artifact_path in private_artifacts:
                    try:
                        artifact_path.unlink(missing_ok=True)
                    except Exception:
                        pass
    finally:
        # Public cleanup is best effort so it cannot replace the primary failure.
        if not published:
            for artifact_path in output_artifacts:
                try:
                    artifact_path.unlink(missing_ok=True)
                except Exception:
                    pass


def _contains_forbidden_text(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_forbidden_text(str(key)) or _contains_forbidden_text(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_text(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return (
            any(token.lower() in lowered for token in _FORBIDDEN_REPORT_TEXT)
            or _EMAIL_RE.search(value) is not None
            or _URL_RE.search(value) is not None
            or _RAW_PATH_RE.search(value) is not None
            or _SQL_RE.search(value) is not None
        )
    return False


def _is_nonnegative_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def validate_live_postgresql_external_layer(layer: Any) -> dict[str, Any]:
    """Validate the current public live-PostgreSQL external layer."""

    if not isinstance(layer, Mapping):
        return {
            "passed": False,
            "status": "failed",
            "blockers": ["live PostgreSQL external layer must be an object"],
            "blocker_count": 1,
        }
    value = dict(layer)
    blockers = _exact_keys(
        value,
        _LIVE_POSTGRESQL_LAYER_FIELDS,
        "live PostgreSQL external layer",
    )
    if value.get("status") != "passed":
        blockers.append("live PostgreSQL external layer status is not passed")
    if value.get("operator_attested") is not True:
        blockers.append("live PostgreSQL external layer is not attested")
    if value.get("endpoint_scheme") != "postgresql":
        blockers.append("live PostgreSQL external layer scheme is invalid")
    hash_fields = sorted(
        field for field in _LIVE_POSTGRESQL_LAYER_FIELDS if field.endswith("_hash")
    )
    hash_values = [value.get(field) for field in hash_fields]
    if any(
        not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None for value in hash_values
    ):
        blockers.append("live PostgreSQL external layer hashes are invalid")
    elif len(hash_values) != len(set(hash_values)):
        blockers.append("live PostgreSQL external layer hashes are not independently bound")
    count_fields = sorted(
        field for field in _LIVE_POSTGRESQL_LAYER_FIELDS if field.endswith("_count")
    )
    if any(not _is_nonnegative_int(value.get(field)) for field in count_fields):
        blockers.append("live PostgreSQL external layer counts are invalid")
    exact_counts = {
        "run_count": 1,
        "pass_count": 1,
        "failure_count": 0,
        "skip_count": 0,
        "fresh_database_count": 1,
        "migration_count": 1,
        "first_owner_bootstrap_count": 1,
        "persisted_auth_count": 1,
        "persisted_upload_count": 1,
        "restart_recovery_count": 1,
        "second_user_invitation_count": 1,
        "revocation_count": 1,
        "post_relink_old_token_denial_count": 1,
        "revoked_token_sessions_after_relink_count": 1,
        "relink_distinct_token_session_count": 1,
        "expiry_denial_count": 1,
        "relink_count": 1,
        "transaction_rollback_probe_count": 1,
        "production_smoke_probe_count": 1,
        "signing_key_rotation_count": 1,
        "overlap_old_token_verification_count": 1,
        "overlap_jwks_public_key_count": 2,
        "new_key_token_verification_count": 1,
        "post_overlap_old_token_denial_count": 1,
        "post_overlap_jwks_public_key_count": 1,
        "post_overlap_new_token_verification_count": 1,
        "private_signing_key_exposure_count": 0,
    }
    for field, expected in exact_counts.items():
        if value.get(field) != expected:
            blockers.append(f"live PostgreSQL external layer count is invalid: {field}")
    if (
        not _is_nonnegative_int(value.get("persisted_audit_count"))
        or value.get("persisted_audit_count", 0) < 1
    ):
        blockers.append("live PostgreSQL external layer audit count is invalid")
    attestations = value.get("attestations")
    if not isinstance(attestations, Mapping):
        blockers.append("live PostgreSQL external layer attestations are missing")
    else:
        blockers.extend(
            _exact_keys(
                attestations,
                _LIVE_POSTGRESQL_ATTESTATIONS,
                "live PostgreSQL external layer attestations",
            )
        )
        if any(attestations.get(key) is not True for key in _LIVE_POSTGRESQL_ATTESTATIONS):
            blockers.append("live PostgreSQL external layer attestations are incomplete")
    if value.get("implementation_contract_hash") != issue20_implementation_contract_hash(ROOT):
        blockers.append("live PostgreSQL external layer implementation contract is stale")
    layer_implementation_contract_hash = value.get("implementation_contract_hash")
    if isinstance(layer_implementation_contract_hash, str) and value.get(
        "command_contract_hash"
    ) != _command_contract_hash(layer_implementation_contract_hash):
        blockers.append("live PostgreSQL external layer command contract is stale")
    artifact_source = {key: item for key, item in value.items() if key != "evidence_artifact_hash"}
    expected_artifact_hash = _evidence_hash(
        "live_postgresql_external_layer_v3",
        artifact_source,
    )
    if value.get("evidence_artifact_hash") != expected_artifact_hash:
        blockers.append("live PostgreSQL external layer artifact binding mismatch")
    if _contains_forbidden_text(value):
        blockers.append("live PostgreSQL external layer contains forbidden material")
    return {
        "passed": not blockers,
        "status": "passed" if not blockers else "failed",
        "blockers": blockers,
        "blocker_count": len(blockers),
    }


def _validate_live_postgresql_layer(
    report: Mapping[str, Any],
    layer: Mapping[str, Any],
) -> list[str]:
    public_validation = validate_live_postgresql_external_layer(layer)
    blockers = list(public_validation["blockers"])
    expected_layer = build_live_postgresql_layer(report)
    if layer.get("source_report_commitment_hash") != expected_layer.get(
        "source_report_commitment_hash"
    ):
        blockers.append("live PostgreSQL source report commitment is stale")
    counts = report.get("safe_counts")
    expected_audit_count = (
        counts.get("postgres_audit_rows_after_all_journeys")
        if isinstance(counts, Mapping)
        else None
    )
    if layer.get("persisted_audit_count") != expected_audit_count:
        blockers.append("live PostgreSQL external layer audit count is not source-bound")
    if dict(layer) != expected_layer:
        blockers.append("live PostgreSQL external layer is not the deterministic conversion")
    return blockers


def validate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, Mapping):
        return {"passed": False, "blockers": ["report must be an object"]}
    blockers.extend(
        _exact_keys(
            report,
            {
                "artifact_id",
                "status",
                "protocol_version",
                "metrics",
                "safe_counts",
                "safe_hashes",
                "live_postgresql_layer",
                "claim_boundary",
            },
            "report",
        )
    )
    metrics = report.get("metrics")
    counts = report.get("safe_counts")
    hashes = report.get("safe_hashes")
    layer = report.get("live_postgresql_layer")
    claims = report.get("claim_boundary")
    if report.get("artifact_id") != ARTIFACT_ID:
        blockers.append("unexpected artifact id")
    if report.get("status") != "passed":
        blockers.append("live E2E status is not passed")
    if report.get("protocol_version") != LATEST_PROTOCOL_VERSION:
        blockers.append("official MCP 2025-11-25 was not negotiated")
    if not isinstance(metrics, Mapping) or not metrics:
        blockers.append("metrics are missing")
    else:
        blockers.extend(_exact_keys(metrics, _METRIC_FIELDS, "metrics"))
        for key in _METRIC_FIELDS:
            value = metrics.get(key)
            expected = False if key == "raw_secret_or_path_exposed" else True
            if value is not expected:
                blockers.append(f"metric failed: {key}")
    if not isinstance(counts, Mapping):
        blockers.append("safe counts are missing")
    else:
        blockers.extend(_exact_keys(counts, _SAFE_COUNT_FIELDS, "safe counts"))
        if any(not _is_nonnegative_int(counts.get(field)) for field in _SAFE_COUNT_FIELDS):
            blockers.append("safe counts are invalid")
        exact_counts = {
            "migration_ledger_rows": 5,
            "migration_applied_count": 5,
            "migration_restart_skipped_count": 5,
            "persisted_upload_session_rows": 1,
            "persisted_file_audit_rows": 1,
            "listed_tool_count": 2,
            "user_rows_after_second_login": 2,
            "workspace_member_rows_after_second_login": 2,
            "external_identity_rows_after_second_login": 2,
            "accepted_invitation_rows_after_second_login": 2,
            "token_session_rows_after_all_journeys": 3,
            "revoked_token_denial_count": 1,
            "post_relink_old_token_denial_count": 1,
            "revoked_token_sessions_after_relink_count": 1,
            "relink_distinct_token_session_count": 1,
            "expiry_denial_count": 1,
            "relink_count": 1,
            "transaction_rollback_probe_count": 1,
            "postgres_mcp_allowed_audit_count": 2,
            "postgres_mcp_denied_audit_count": 2,
            "postgres_mcp_lineage_complete_count": 4,
            "cross_workspace_denial_count": 1,
            "identity_forgery_denial_count": 1,
            "signing_key_rotation_count": 1,
            "overlap_old_token_verification_count": 1,
            "overlap_jwks_public_key_count": 2,
            "new_key_token_verification_count": 1,
            "post_overlap_old_token_denial_count": 1,
            "post_overlap_jwks_public_key_count": 1,
            "post_overlap_new_token_verification_count": 1,
            "private_signing_key_exposure_count": 0,
        }
        for field, expected in exact_counts.items():
            if counts.get(field) != expected:
                blockers.append(f"safe count is invalid: {field}")
        before_audits = counts.get("postgres_audit_rows_before_restart")
        final_audits = counts.get("postgres_audit_rows_after_all_journeys")
        if (
            not _is_nonnegative_int(before_audits)
            or not _is_nonnegative_int(final_audits)
            or before_audits < 1
            or final_audits < before_audits
        ):
            blockers.append("persisted PostgreSQL audit counts are invalid")
    if not isinstance(hashes, Mapping) or not hashes:
        blockers.append("safe hashes are missing")
    else:
        blockers.extend(_exact_keys(hashes, _SAFE_HASH_FIELDS, "safe hashes"))
        hash_values = list(hashes.values())
        if any(
            not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None
            for value in hash_values
        ):
            blockers.append("safe hashes are invalid")
        elif len(hash_values) != len(set(hash_values)):
            blockers.append("safe hashes are not independently bound")
        implementation_contract_hash = hashes.get("implementation_contract_hash")
        if implementation_contract_hash != issue20_implementation_contract_hash(ROOT):
            blockers.append("implementation contract hash is stale")
        if isinstance(implementation_contract_hash, str) and hashes.get(
            "command_contract_hash"
        ) != _command_contract_hash(implementation_contract_hash):
            blockers.append("command contract hash is stale")
    required_true_claims = {
        "live_postgresql",
        "production_oauth_and_mcp_runtime",
        "production_upload_and_file_audit_stores",
        "fake_google_oidc",
        "live_postgresql_external_layer_contract",
        "revoke_and_expiry_relink_verified",
        "second_user_invitation_verified",
        "cross_workspace_verified",
        "signing_key_rotation_verified",
    }
    required_false_claims = {
        "live_google_account",
        "live_chatgpt_connector",
        "whole_issue_20_complete",
        "production_readiness",
    }
    if not isinstance(claims, Mapping):
        blockers.append("claim boundary is missing")
    else:
        blockers.extend(_exact_keys(claims, _CLAIM_FIELDS, "claim boundary"))
        for key in required_true_claims:
            if claims.get(key) is not True:
                blockers.append(f"required true claim missing: {key}")
        for key in required_false_claims:
            if claims.get(key) is not False:
                blockers.append(f"required false claim missing: {key}")
    if not isinstance(layer, Mapping):
        blockers.append("live PostgreSQL external layer is missing")
    else:
        blockers.extend(_validate_live_postgresql_layer(report, layer))
    if _contains_forbidden_text(report):
        blockers.append("public report contains a DSN, URL, email, token, path, or SQL")
    return {"passed": not blockers, "blockers": blockers}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--validate-report", action="store_true")
    parser.add_argument("--runner-image-id")
    args = parser.parse_args()
    try:
        if args.validate_report:
            report = json.loads(args.output.read_text(encoding="utf-8"))
            validation = validate_report(report)
        elif args.inside:
            output_path = args.output.resolve()
            output_helper_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
            output_artifacts = (output_path, output_helper_path)
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                for artifact_path in output_artifacts:
                    artifact_path.unlink(missing_ok=True)
            except Exception:
                for artifact_path in output_artifacts:
                    try:
                        artifact_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                raise RuntimeError("live_e2e_output_isolation_failed") from None
            if args.runner_image_id is None or _SHA256_RE.fullmatch(args.runner_image_id) is None:
                raise RuntimeError("runner_image_id_required")
            authority_image_id = os.environ.get("FORMOWL_RUNNER_IMAGE_ID")
            if authority_image_id is None:
                raise RuntimeError("runner_image_id_authority_missing")
            if authority_image_id != args.runner_image_id:
                raise RuntimeError("runner_image_id_authority_mismatch")
            report = asyncio.run(_run_inside(output_path))
            validation = validate_report(report)
        else:
            report = run_live_e2e(
                args.output,
                runner_image_id=args.runner_image_id,
            )
            validation = validate_report(report)
    except Exception as error:
        candidate = str(error)
        safe_code = (
            candidate
            if _SAFE_ERROR_RE.fullmatch(candidate)
            else "connected_runtime_live_e2e_failed"
        )
        print(
            json.dumps(
                {"error": safe_code, "status": "error"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "artifact_id": report.get("artifact_id"),
                "blocker_count": len(validation["blockers"]),
                "status": "passed" if validation["passed"] else "failed",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if validation["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
