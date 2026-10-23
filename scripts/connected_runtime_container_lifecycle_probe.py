#!/usr/bin/env python3
"""Exercise the packaged connected runtime through its real container lifecycle."""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse
import uuid


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DOCKERFILE = ROOT / "containers" / "runtime" / "Dockerfile"
COMPOSE_FILE = ROOT / "compose.yaml"
PROBE_SCRIPT = Path(__file__).resolve()
PINNED_POSTGRES_IMAGE = (
    "pgvector/pgvector@sha256:" "131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6"
)
POSTGRES_IMAGE = PINNED_POSTGRES_IMAGE
ARTIFACT_ID = "formowl_connected_runtime_container_lifecycle_v2"
DEFAULT_OUTPUT = Path("/tmp/formowl-connected-runtime-container-lifecycle.json")
STOP_GRACE_SECONDS = 30
OVERLAP_WINDOW_SECONDS = 15
MAX_OVERLAP_WAIT_SECONDS = 20
EXPECTED_MIGRATION_COUNT = 5
RUNTIME_UID = 10001
INITIAL_KID = "formowl-lifecycle-key-a"
ROTATED_KID = "formowl-lifecycle-key-b"
IMPLEMENTATION_CONTRACT_IMAGE_LABEL = "org.formowl.issue20.implementation-contract"
LAUNCHER_CAPABILITIES = ("CHOWN", "DAC_READ_SEARCH", "SETPCAP", "SETGID", "SETUID")

_SAFE_ERROR_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_RAW_PATH_RE = re.compile(
    r"(^|[\s'\"([{=,:;])(/(?:home|tmp|srv|mnt|var|root|workspace)/|[A-Za-z]:[\\/])"
)
_SQL_RE = re.compile(
    r"\b(select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+table)\b",
    re.IGNORECASE,
)

_METRIC_FIELDS = {
    "actual_compose_healthcheck_security_verified",
    "actual_compose_key_rotation_verified",
    "actual_compose_migrate_verified",
    "actual_compose_postgresql_0400_secret_verified",
    "actual_compose_preflight_verified",
    "actual_compose_restart_fresh_secret_snapshot_verified",
    "actual_compose_service_readiness_verified",
    "runtime_image_built",
    "runtime_image_entrypoint_verified",
    "compose_config_resolved",
    "fresh_postgresql_ready",
    "file_deployment_secret_source_exercised",
    "initial_migration_applied",
    "real_google_preflight_ready",
    "production_bridge_oauth_state_seeded",
    "runtime_security_options_verified",
    "first_process_bearer_whoami_verified",
    "first_process_upload_and_audit_persisted",
    "first_process_ready",
    "first_process_sigterm_clean",
    "first_process_database_released",
    "restart_migration_noop",
    "restart_bearer_whoami_verified",
    "restart_state_lineage_persisted",
    "second_process_ready",
    "second_process_sigterm_clean",
    "second_process_database_released",
    "third_process_ready",
    "third_process_sigterm_clean",
    "third_process_database_released",
    "fourth_process_ready",
    "fourth_process_sigterm_clean",
    "fourth_process_database_released",
    "same_database_and_data_restart_verified",
    "jwks_manifest_reload_one_two_one_verified",
    "runtime_logs_safe",
    "docker_resources_cleaned",
}
_COUNT_FIELDS = {
    "compose_healthcheck_success_count",
    "compose_migration_success_count",
    "compose_old_snapshot_retirement_count",
    "compose_postgres_0400_secret_read_count",
    "compose_preflight_success_count",
    "compose_runtime_process_uid",
    "compose_runtime_ready_count",
    "compose_secret_snapshot_count",
    "operator_owned_0400_secret_count",
    "runtime_process_start_count",
    "runtime_ready_count",
    "sigterm_clean_exit_count",
    "database_release_count",
    "migration_applied_count",
    "migration_restart_skipped_count",
    "real_google_preflight_count",
    "production_bridge_seed_count",
    "bearer_whoami_success_count",
    "bearer_expected_denial_count",
    "persisted_user_count",
    "persisted_external_identity_count",
    "persisted_token_session_count",
    "persisted_upload_session_count",
    "persisted_file_audit_count",
    "postgres_mcp_allowed_audit_count",
    "postgres_mcp_denied_audit_count",
    "persisted_state_snapshot_count",
    "jwks_initial_public_key_count",
    "jwks_overlap_public_key_count",
    "jwks_retired_public_key_count",
    "runtime_process_uid",
    "runtime_log_line_count",
    "compose_service_count",
    "removed_runtime_container_count",
    "database_active_connection_check_count",
    "database_zero_connection_check_count",
    "stop_grace_seconds",
}
_HASH_FIELDS = {
    "implementation_contract_hash",
    "runtime_image_contract_hash",
    "compose_runtime_wiring_hash",
    "migration_initial_result_hash",
    "migration_restart_result_hash",
    "compose_live_journey_hash",
    "compose_live_security_contract_hash",
    "compose_secret_snapshot_set_hash",
    "oauth_seed_state_hash",
    "first_client_result_hash",
    "restart_client_result_hash",
    "first_persisted_state_hash",
    "restart_persisted_state_hash",
    "persistent_core_state_hash",
    "readiness_shape_hash",
    "jwks_phase_set_hash",
    "runtime_security_contract_hash",
    "runtime_log_hash",
    "data_restart_state_hash",
    "command_contract_hash",
}
_CLAIM_FIELDS = {
    "actual_compose_connected_stack",
    "actual_runtime_dockerfile_image",
    "actual_formowl_container_entrypoint",
    "live_postgresql",
    "real_google_metadata_and_jwks_preflight",
    "file_mounted_deployment_secrets",
    "production_subprocess_lifecycle",
    "signing_key_manifest_reload",
    "real_process_bearer_restart_persistence",
    "token_overlap_semantics_reverified",
    "live_google_account",
    "live_chatgpt_connector",
    "whole_issue_20_complete",
    "production_readiness",
}
_TRUE_CLAIMS = {
    "actual_compose_connected_stack",
    "actual_runtime_dockerfile_image",
    "actual_formowl_container_entrypoint",
    "live_postgresql",
    "real_google_metadata_and_jwks_preflight",
    "file_mounted_deployment_secrets",
    "production_subprocess_lifecycle",
    "signing_key_manifest_reload",
    "real_process_bearer_restart_persistence",
}
_FALSE_CLAIMS = _CLAIM_FIELDS - _TRUE_CLAIMS
_RUNTIME_SECRET_NAMES = (
    "formowl_database_dsn",
    "formowl_google_client_secret",
    "formowl_state_encryption_key",
    "formowl_signing_key_set",
    "formowl_signing_key_current",
    "formowl_signing_key_previous",
)
_FORBIDDEN_PLAINTEXT_SECRET_ENV = {
    "FORMOWL_DATABASE_DSN",
    "FORMOWL_GOOGLE_CLIENT_SECRET",
    "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY",
    "FORMOWL_OAUTH_SIGNING_PRIVATE_KEY",
    "FORMOWL_OAUTH_SIGNING_KEY_SET",
}


class LifecycleProbeFailure(RuntimeError):
    """Bounded failure that can be reported without command or secret detail."""

    def __init__(self, stage: str, code: str) -> None:
        self.stage = stage if _SAFE_ERROR_RE.fullmatch(stage) else "orchestration"
        self.code = code if _SAFE_ERROR_RE.fullmatch(code) else "lifecycle_probe_failed"
        super().__init__(self.code)


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_runtime_image_id(image: str, *, stage: str) -> str:
    if not isinstance(image, str) or _SHA256_RE.fullmatch(image) is None:
        raise LifecycleProbeFailure(stage, "runtime_image_id_invalid")
    return image


def _require_pinned_postgres_image(*, stage: str) -> str:
    if POSTGRES_IMAGE != PINNED_POSTGRES_IMAGE:
        raise LifecycleProbeFailure(stage, "postgres_image_contract_mismatch")
    return POSTGRES_IMAGE


def _runtime_command_contract_hash(
    *,
    implementation_contract_hash: str,
    runtime_image_contract_hash: str,
    compose_runtime_wiring_hash: str,
) -> str:
    return _sha256_json(
        {
            "dockerfile": "containers/runtime/Dockerfile",
            "entrypoint": "formowl-container-entrypoint",
            "resolved_application_command": "formowl-connected-mcp",
            "commands": ["migrate", "preflight", "serve"],
            "ready_path": "readyz",
            "jwks_path": "well_known_jwks",
            "stop_signal": "SIGTERM",
            "stop_grace_seconds": STOP_GRACE_SECONDS,
            "overlap_window_seconds": OVERLAP_WINDOW_SECONDS,
            "runtime_process_count": 4,
            "actual_compose_sequence": [
                "postgres",
                "connected-migrate",
                "connected-mcp preflight",
                "connected-mcp initial",
                "connected-mcp overlap",
                "connected-mcp retired",
            ],
            "postgres_image": PINNED_POSTGRES_IMAGE,
            "runtime_image_contract_hash": runtime_image_contract_hash,
            "compose_runtime_wiring_hash": compose_runtime_wiring_hash,
            "implementation_contract_hash": implementation_contract_hash,
        }
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        try:
            items = tuple(value.items())
        except Exception:
            raise LifecycleProbeFailure(
                "inside_serialization",
                "jsonable_mapping_invalid",
            ) from None
        if any(type(key) is not str for key, _item in items):
            raise LifecycleProbeFailure(
                "inside_serialization",
                "jsonable_mapping_key_invalid",
            ) from None
        return {key: _jsonable(item) for key, item in items}
    if isinstance(value, set):
        raise LifecycleProbeFailure(
            "inside_serialization",
            "jsonable_set_invalid",
        ) from None
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        try:
            if value.tzinfo is None:
                raise ValueError
            offset = value.utcoffset()
            if offset is None or value.utcoffset() != offset:
                raise ValueError
            # Pin one stable source offset before conversion so a stateful
            # tzinfo cannot change the serialized instant mid-operation.
            normalized = (value.replace(tzinfo=None) - offset).replace(tzinfo=timezone.utc)
            return normalized.isoformat()
        except Exception:
            raise LifecycleProbeFailure(
                "inside_serialization",
                "jsonable_datetime_invalid",
            ) from None
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LifecycleProbeFailure(
                "inside_serialization",
                "jsonable_number_invalid",
            ) from None
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise LifecycleProbeFailure(
        "inside_serialization",
        "jsonable_value_invalid",
    ) from None


def _current_issue20_implementation_contract_hash() -> str:
    helper_path = ROOT / "python" / "formowl_evidence" / "issue20.py"
    spec = importlib.util.spec_from_file_location(
        "formowl_issue20_evidence_contract",
        helper_path,
    )
    if spec is None or spec.loader is None:
        raise LifecycleProbeFailure("implementation_binding", "implementation_contract_missing")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        value = module.issue20_implementation_contract_hash(ROOT)
    except Exception:
        raise LifecycleProbeFailure(
            "implementation_binding",
            "implementation_contract_unavailable",
        ) from None
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise LifecycleProbeFailure("implementation_binding", "implementation_contract_invalid")
    return value


def _inside_seed_step(code: str, operation: Callable[[], Any]) -> Any:
    """Convert an installed-wheel seed failure into a bounded public code."""

    try:
        return operation()
    except LifecycleProbeFailure:
        raise
    except Exception:
        raise LifecycleProbeFailure("inside_seed", code) from None


def _write_inside_seed_bearer_file(token_path: Path, access_token: str) -> None:
    descriptor = _inside_seed_step(
        "bearer_file_create_failed",
        lambda: os.open(
            token_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o400,
        ),
    )
    write_error: LifecycleProbeFailure | None = None
    try:
        remaining = memoryview(access_token.encode("ascii"))
        while remaining:
            written = os.write(descriptor, remaining)
            if type(written) is not int or written <= 0 or written > len(remaining):
                raise OSError
            remaining = remaining[written:]
        os.fsync(descriptor)
    except Exception:
        write_error = LifecycleProbeFailure("inside_seed", "bearer_file_write_failed")
    try:
        os.close(descriptor)
    except Exception:
        if write_error is None:
            write_error = LifecycleProbeFailure("inside_seed", "bearer_file_close_failed")
    if write_error is not None:
        try:
            token_path.unlink(missing_ok=True)
        except OSError:
            raise LifecycleProbeFailure(
                "inside_seed",
                "bearer_file_cleanup_failed",
            ) from None
        raise write_error
    try:
        mode = token_path.stat().st_mode & 0o777
    except OSError:
        try:
            token_path.unlink(missing_ok=True)
        except OSError:
            raise LifecycleProbeFailure(
                "inside_seed",
                "bearer_file_cleanup_failed",
            ) from None
        raise LifecycleProbeFailure("inside_seed", "bearer_file_stat_failed") from None
    if mode != 0o400:
        try:
            token_path.unlink(missing_ok=True)
        except OSError:
            raise LifecycleProbeFailure(
                "inside_seed",
                "bearer_file_cleanup_failed",
            ) from None
        raise LifecycleProbeFailure("inside_seed", "bearer_file_mode_invalid")


def _inside_seed_oauth_state() -> dict[str, Any]:
    from formowl_auth import (
        FormOwlOAuthBridge,
        FormOwlTokenCodec,
        GoogleIdentity,
        PostgreSQLOAuthRepository,
    )
    from formowl_auth.security import hash_oauth_value, pkce_s256_challenge
    from formowl_gateway.runtime import ConnectedRuntimeConfig

    class _SeedGoogleClient:
        def __init__(self) -> None:
            self.last_state: str | None = None
            self.last_nonce: str | None = None

        def build_authorization_url(self, *, google_state: str, google_nonce: str) -> str:
            self.last_state = google_state
            self.last_nonce = google_nonce
            return "https://accounts.google.com/o/oauth2/v2/auth"

        async def authenticate_code(
            self,
            google_code: str,
            *,
            expected_nonce_hash: str,
            now: datetime,
        ) -> GoogleIdentity:
            del now
            if google_code != "lifecycle-google-code" or self.last_nonce is None:
                raise LifecycleProbeFailure("inside_seed", "fake_google_callback_invalid")
            if expected_nonce_hash != hash_oauth_value("google_nonce", self.last_nonce):
                raise LifecycleProbeFailure("inside_seed", "fake_google_nonce_invalid")
            return GoogleIdentity(
                issuer="https://accounts.google.com",
                subject="formowl-lifecycle-subject",
                email="formowl-lifecycle@example.test",
                email_verified=True,
                display_name="FormOwl Lifecycle User",
            )

    token_path = Path(os.environ.get("FORMOWL_LIFECYCLE_BEARER_FILE", ""))
    if not token_path.is_absolute():
        raise LifecycleProbeFailure("inside_seed", "bearer_file_config_invalid")
    config = _inside_seed_step(
        "config_and_secret_load_failed",
        lambda: ConnectedRuntimeConfig.from_env_and_secrets(os.environ),
    )
    operator_service_id = config.owner_bootstrap_operator_service_id
    if operator_service_id is None:
        raise LifecycleProbeFailure("inside_seed", "bootstrap_operator_missing")
    repository = _inside_seed_step(
        "oauth_repository_connect_failed",
        lambda: PostgreSQLOAuthRepository.connect(config.database_dsn),
    )
    google_client = _SeedGoogleClient()
    now = datetime.now(timezone.utc)
    verifier = "v" * 64
    bridge = _inside_seed_step(
        "oauth_bridge_construction_failed",
        lambda: FormOwlOAuthBridge(
            config=config.oauth,
            repository=repository,
            google_client=google_client,  # type: ignore[arg-type]
            token_codec=FormOwlTokenCodec(
                issuer=config.oauth.issuer,
                client_id=config.oauth.chatgpt_client_id,
                key_set=config.signing_key_set,
                lifetime_seconds=config.oauth.access_token_lifetime_seconds,
                clock_skew_seconds=config.oauth.clock_skew_seconds,
            ),
            random_bytes=os.urandom,
            owner_bootstrap_operator_authorizer=(
                lambda candidate: candidate == operator_service_id
            ),
        ),
    )
    seed_error: BaseException | None = None
    try:
        _inside_seed_step(
            "owner_bootstrap_failed",
            lambda: bridge.bootstrap_owner_invitation(
                workspace_id="workspace_lifecycle_probe",
                email="formowl-lifecycle@example.test",
                expires_at=now + timedelta(minutes=20),
                idempotency_key="formowl-lifecycle-owner-bootstrap",
                operator_service_id=operator_service_id,
                now=now,
            ),
        )
        _inside_seed_step(
            "authorization_start_failed",
            lambda: bridge.start_authorization(
                {
                    "client_id": config.oauth.chatgpt_client_id,
                    "redirect_uri": config.oauth.chatgpt_redirect_uri,
                    "response_type": "code",
                    "resource": config.oauth.resource,
                    "scope": "formowl.use",
                    "state": "formowl-lifecycle-client-state",
                    "code_challenge": pkce_s256_challenge(verifier),
                    "code_challenge_method": "S256",
                },
                now=now,
            ),
        )
        if google_client.last_state is None:
            raise LifecycleProbeFailure("inside_seed", "fake_google_state_missing")
        callback = _inside_seed_step(
            "google_callback_failed",
            lambda: asyncio.run(
                bridge.complete_google_callback(
                    google_state=google_client.last_state,
                    google_code="lifecycle-google-code",
                    now=now,
                )
            ),
        )
        try:
            callback_uri = callback["redirect_uri"]
            if not isinstance(callback_uri, str):
                raise ValueError
            parsed_callback = urlparse(callback_uri)
            callback_base = parsed_callback._replace(query="", fragment="").geturl()
            values = parse_qs(
                parsed_callback.query,
                keep_blank_values=True,
                strict_parsing=True,
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            raise LifecycleProbeFailure(
                "inside_seed",
                "authorization_callback_invalid",
            ) from None
        authorization_codes = values.get("code")
        client_states = values.get("state")
        if (
            not isinstance(authorization_codes, list)
            or len(authorization_codes) != 1
            or not isinstance(authorization_codes[0], str)
            or not authorization_codes[0]
        ):
            raise LifecycleProbeFailure("inside_seed", "authorization_code_missing")
        if (
            callback_base != config.oauth.chatgpt_redirect_uri
            or parsed_callback.fragment
            or set(values) != {"code", "state"}
            or client_states != ["formowl-lifecycle-client-state"]
        ):
            raise LifecycleProbeFailure(
                "inside_seed",
                "authorization_callback_invalid",
            )
        authorization_code = authorization_codes[0]
        token = _inside_seed_step(
            "token_exchange_failed",
            lambda: bridge.exchange_authorization_code(
                {
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "client_id": config.oauth.chatgpt_client_id,
                    "redirect_uri": config.oauth.chatgpt_redirect_uri,
                    "code_verifier": verifier,
                    "resource": config.oauth.resource,
                },
                now=now,
            ),
        )
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or _JWT_RE.fullmatch(access_token) is None:
            raise LifecycleProbeFailure("inside_seed", "bearer_token_invalid")
        _write_inside_seed_bearer_file(token_path, access_token)
        return {
            "status": "ok",
            "seed_count": 1,
            "seed_state_hash": _sha256_json(
                {
                    "bootstrap": True,
                    "oauth_pkce": True,
                    "token_session": True,
                    "file_secret_source": True,
                }
            ),
        }
    except BaseException as error:
        seed_error = error
        raise
    finally:
        try:
            repository.close()
        except Exception:
            if seed_error is None:
                raise LifecycleProbeFailure(
                    "inside_seed",
                    "oauth_repository_close_failed",
                ) from None


def _model_dump(value: Any) -> Any:
    try:
        model_dump = getattr(value, "model_dump")
    except AttributeError:
        try:
            inspect.getattr_static(value, "model_dump")
        except AttributeError:
            return value
        except Exception:
            raise LifecycleProbeFailure(
                "inside_serialization",
                "model_dump_invalid",
            ) from None
        raise LifecycleProbeFailure(
            "inside_serialization",
            "model_dump_invalid",
        ) from None
    except Exception:
        raise LifecycleProbeFailure(
            "inside_serialization",
            "model_dump_invalid",
        ) from None
    try:
        return model_dump(mode="json", by_alias=True, exclude_none=True)
    except Exception:
        raise LifecycleProbeFailure(
            "inside_serialization",
            "model_dump_invalid",
        ) from None


async def _inside_client_sequence() -> dict[str, Any]:
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.version import LATEST_PROTOCOL_VERSION

    phase = os.environ.get("FORMOWL_LIFECYCLE_CLIENT_PHASE")
    runtime_host = os.environ.get("FORMOWL_LIFECYCLE_RUNTIME_HOST")
    if phase not in {"first", "restart"}:
        raise LifecycleProbeFailure("inside_client", "client_phase_invalid")
    if not isinstance(runtime_host, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", runtime_host
    ):
        raise LifecycleProbeFailure("inside_client", "runtime_host_invalid")
    token_path = Path("/run/probe/bearer")
    try:
        if token_path.stat().st_mode & 0o777 != 0o400:
            raise LifecycleProbeFailure("inside_client", "bearer_file_mode_invalid")
        bearer = token_path.read_text(encoding="ascii").strip()
    except OSError:
        raise LifecycleProbeFailure("inside_client", "bearer_file_unavailable") from None
    if _JWT_RE.fullmatch(bearer) is None:
        raise LifecycleProbeFailure("inside_client", "bearer_token_invalid")
    headers = {
        "Authorization": f"Bearer {bearer}",
        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
    }
    endpoint = f"http://{runtime_host}:8000/mcp"
    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=False,
        timeout=15.0,
        trust_env=False,
    ) as http_client:
        async with streamable_http_client(endpoint, http_client=http_client) as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                listed = await session.list_tools()
                tool_names = sorted(tool.name for tool in listed.tools)
                if tool_names != ["open_upload_session", "whoami"]:
                    raise LifecycleProbeFailure("inside_client", "client_tool_surface_invalid")
                calls: list[Any] = [await session.call_tool("whoami", arguments={})]
                if phase == "first":
                    calls.append(
                        await session.call_tool(
                            "open_upload_session",
                            arguments={
                                "intent": "Upload governed mail evidence.",
                                "intended_asset_type": "pst",
                            },
                        )
                    )
                    calls.append(
                        await session.call_tool(
                            "open_upload_session",
                            arguments={
                                "intent": "Attempt caller identity forgery.",
                                "intended_asset_type": "pst",
                                "requester_user_id": "user_forged",
                            },
                        )
                    )
    error_flags: list[bool] = []
    for call in calls:
        try:
            error_flag = getattr(call, "isError")
        except Exception:
            raise LifecycleProbeFailure(
                "inside_client",
                "client_tool_result_invalid",
            ) from None
        if type(error_flag) is not bool:
            raise LifecycleProbeFailure(
                "inside_client",
                "client_tool_result_invalid",
            )
        error_flags.append(error_flag)
    expected_error_flags = [False, False, True] if phase == "first" else [False]
    if error_flags != expected_error_flags:
        raise LifecycleProbeFailure("inside_client", "client_tool_results_invalid")
    allowed_count = error_flags.count(False)
    denied_count = error_flags.count(True)
    return {
        "status": "ok",
        "phase": phase,
        "allowed_count": allowed_count,
        "denied_count": denied_count,
        "result_shape_hash": _sha256_json(
            {
                "initialize": _jsonable(_model_dump(initialized)),
                "tools": tool_names,
                "calls": [_jsonable(_model_dump(call)) for call in calls],
            }
        ),
    }


def _inside_persisted_state() -> dict[str, Any]:
    from formowl_auth import FileAuditLogStore, PostgreSQLOAuthRepository
    from formowl_gateway.runtime import ConnectedRuntimeConfig
    from formowl_graph.storage import SQLStatement
    from formowl_ingestion.storage import UploadSessionStore

    phase = os.environ.get("FORMOWL_LIFECYCLE_STATE_PHASE")
    if phase not in {"first", "restart"}:
        raise LifecycleProbeFailure("inside_state", "state_phase_invalid")
    try:
        expected_allowed = int(os.environ["FORMOWL_LIFECYCLE_EXPECTED_ALLOWED_COUNT"])
        expected_denied = int(os.environ["FORMOWL_LIFECYCLE_EXPECTED_DENIED_COUNT"])
    except (KeyError, ValueError):
        raise LifecycleProbeFailure("inside_state", "state_expected_count_invalid") from None
    config = ConnectedRuntimeConfig.from_env_and_secrets(os.environ)
    repository = PostgreSQLOAuthRepository.connect(config.database_dsn)
    try:

        def query(sql: str) -> list[Mapping[str, Any]]:
            return repository.connection.query_all(SQLStatement(sql=sql, parameters={}))

        users = query("SELECT user_id, status FROM formowl_users ORDER BY user_id")
        identities = query(
            "SELECT external_identity_id, issuer, subject, user_id, status "
            "FROM formowl_external_identities ORDER BY external_identity_id"
        )
        memberships = query(
            "SELECT workspace_id, user_id, role, removed_at "
            "FROM formowl_workspace_members ORDER BY workspace_id, user_id"
        )
        token_sessions = query(
            "SELECT token_session_id, user_id, external_identity_id, client_id, "
            "current_workspace_id, resource, scopes, issued_at, expires_at, revoked_at "
            "FROM formowl_oauth_token_sessions ORDER BY token_session_id"
        )
        mcp_audits = query(
            "SELECT action, target_id, actor_user_id, workspace_id, external_identity_id, "
            "oauth_client_id, oauth_token_session_id, request_id, tool_call_id, "
            "reason_code, status FROM formowl_audit_log "
            "WHERE action IN ('mcp_authorization_allowed', 'mcp_authorization_denied') "
            "ORDER BY timestamp, audit_log_id"
        )
        upload_sessions = [
            session.to_dict() for session in UploadSessionStore(config.data_dir).list()
        ]
        file_audits = [
            audit.to_dict()
            for audit in FileAuditLogStore(config.data_dir).list()
            if audit.action == "upload_session_created"
        ]
        allowed = [row for row in mcp_audits if row.get("action") == "mcp_authorization_allowed"]
        denied = [row for row in mcp_audits if row.get("action") == "mcp_authorization_denied"]
        if (
            len(users) != 1
            or len(identities) != 1
            or len(memberships) != 1
            or len(token_sessions) != 1
            or len(upload_sessions) != 1
            or len(file_audits) != 1
            or len(allowed) != expected_allowed
            or len(denied) != expected_denied
        ):
            raise LifecycleProbeFailure("inside_state", "persisted_state_count_invalid")
        membership = memberships[0]
        token_session = token_sessions[0]
        if (
            membership.get("removed_at") is not None
            or membership.get("user_id") != token_session.get("user_id")
            or membership.get("workspace_id") != token_session.get("current_workspace_id")
        ):
            raise LifecycleProbeFailure(
                "inside_state",
                "persisted_membership_invalid",
            )
        lineage_fields = {
            "actor_user_id": token_session.get("user_id"),
            "workspace_id": token_session.get("current_workspace_id"),
            "external_identity_id": token_session.get("external_identity_id"),
            "oauth_client_id": token_session.get("client_id"),
            "oauth_token_session_id": token_session.get("token_session_id"),
        }
        for row in mcp_audits:
            if any(row.get(key) != value for key, value in lineage_fields.items()):
                raise LifecycleProbeFailure("inside_state", "postgres_lineage_invalid")
            if not all(
                isinstance(row.get(key), str) and row.get(key)
                for key in ("request_id", "tool_call_id", "reason_code")
            ):
                raise LifecycleProbeFailure("inside_state", "postgres_lineage_invalid")
        core_state = {
            "users": users,
            "identities": identities,
            "memberships": memberships,
            "token_sessions": token_sessions,
            "upload_sessions": upload_sessions,
            "file_audits": file_audits,
        }
        snapshot = {**core_state, "mcp_audits": mcp_audits}
        return {
            "status": "ok",
            "phase": phase,
            "counts": {
                "user_count": len(users),
                "external_identity_count": len(identities),
                "token_session_count": len(token_sessions),
                "upload_session_count": len(upload_sessions),
                "file_audit_count": len(file_audits),
                "mcp_allowed_count": len(allowed),
                "mcp_denied_count": len(denied),
            },
            "core_state_hash": _sha256_json(_jsonable(core_state)),
            "snapshot_hash": _sha256_json(_jsonable(snapshot)),
        }
    finally:
        repository.close()


def _run_command(
    command: Sequence[str],
    *,
    stage: str,
    error_code: str,
    check: bool = True,
    timeout: float | None = None,
    environ: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=ROOT,
            env=None if environ is None else dict(environ),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise LifecycleProbeFailure(stage, "docker_cli_unavailable") from None
    except subprocess.TimeoutExpired:
        raise LifecycleProbeFailure(stage, f"{error_code}_timeout") from None
    except OSError:
        raise LifecycleProbeFailure(stage, error_code) from None
    if check and result.returncode != 0:
        runtime_code = _safe_runtime_error_code(result.stdout, result.stderr)
        raise LifecycleProbeFailure(stage, runtime_code or error_code)
    return result


def _safe_runtime_error_code(*streams: str) -> str | None:
    for stream in streams:
        for line in reversed(stream.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, Mapping):
                continue
            candidate = value.get("error")
            if isinstance(candidate, str) and _SAFE_ERROR_RE.fullmatch(candidate):
                return candidate
    return None


def _json_line(stdout: str, *, stage: str, error_code: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise LifecycleProbeFailure(stage, error_code)


def _atomic_write(
    path: Path,
    value: bytes,
    *,
    mode: int = 0o400,
    stage: str = "file_write",
    error_code: str = "atomic_write_failed",
    cleanup_error_code: str = "atomic_write_cleanup_failed",
) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(value)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except Exception:
                raise LifecycleProbeFailure(stage, cleanup_error_code) from None
            raise LifecycleProbeFailure(stage, cleanup_error_code) from None
        raise LifecycleProbeFailure(stage, error_code) from None


def _write_signing_manifest(
    secret_dir: Path,
    *,
    phase: str,
    verify_until: datetime | None = None,
) -> None:
    if phase == "initial":
        keys = [
            {
                "kid": INITIAL_KID,
                "private_key_file": "/run/secrets/formowl_signing_key_current",
                "active": True,
            }
        ]
    elif phase == "overlap":
        if verify_until is None:
            raise LifecycleProbeFailure("secret_reload", "overlap_expiry_missing")
        keys = [
            {
                "kid": INITIAL_KID,
                "private_key_file": "/run/secrets/formowl_signing_key_previous",
                "active": False,
                "verify_until": verify_until.astimezone(timezone.utc).isoformat(),
            },
            {
                "kid": ROTATED_KID,
                "private_key_file": "/run/secrets/formowl_signing_key_current",
                "active": True,
            },
        ]
    elif phase == "retired":
        keys = [
            {
                "kid": ROTATED_KID,
                "private_key_file": "/run/secrets/formowl_signing_key_current",
                "active": True,
            }
        ]
    else:
        raise LifecycleProbeFailure("secret_reload", "signing_manifest_phase_invalid")
    payload = json.dumps(
        {"version": 1, "keys": keys},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    _atomic_write(secret_dir / "formowl_signing_key_set", payload)


def _generate_signing_keys(image: str, secret_dir: Path) -> tuple[bytes, bytes]:
    image = _require_runtime_image_id(image, stage="secret_setup")
    generator = (
        "from pathlib import Path;"
        "from cryptography.hazmat.primitives import serialization;"
        "from cryptography.hazmat.primitives.asymmetric import rsa;"
        "p=Path('/secrets');"
        "[(p/name).write_bytes(rsa.generate_private_key(public_exponent=65537,key_size=2048)"
        ".private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,"
        "serialization.NoEncryption())) for name in ('key-a.pem','key-b.pem')]"
    )
    _run_command(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0:0",
            "--entrypoint",
            "python",
            "-v",
            f"{secret_dir}:/secrets",
            image,
            "-c",
            generator,
        ],
        stage="secret_setup",
        error_code="signing_key_generation_failed",
        timeout=60,
    )
    try:
        key_a_path = secret_dir / "key-a.pem"
        key_b_path = secret_dir / "key-b.pem"
        key_a = key_a_path.read_bytes()
        key_b = key_b_path.read_bytes()
        key_a_path.unlink()
        key_b_path.unlink()
    except OSError:
        raise LifecycleProbeFailure("secret_setup", "signing_key_generation_failed") from None
    return key_a, key_b


def _prepare_data_directory(image: str, data_dir: Path) -> None:
    image = _require_runtime_image_id(image, stage="data_setup")
    _run_command(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0:0",
            "--entrypoint",
            "python",
            "-v",
            f"{data_dir}:/data",
            image,
            "-c",
            (
                "import os;"
                f"os.chown('/data',{RUNTIME_UID},{RUNTIME_UID});"
                "os.chmod('/data',0o750)"
            ),
        ],
        stage="data_setup",
        error_code="runtime_data_setup_failed",
        timeout=30,
    )


def _prepare_probe_directory(probe_dir: Path) -> None:
    probe_dir.mkdir()
    # mkdir's requested mode is filtered by the operator umask. Set the exact
    # bind-mount contract so runtime UID 10001 can create only the known file.
    os.chmod(probe_dir, 0o733)


def _restore_data_directory_ownership(image: str, data_dir: Path) -> bool:
    image = _require_runtime_image_id(image, stage="cleanup")
    host_uid = os.getuid()
    host_gid = os.getgid()
    restore_code = f"""
import os

for root, directories, files in os.walk('/data', topdown=False):
    for name in files:
        path = os.path.join(root, name)
        os.chown(path, {host_uid}, {host_gid}, follow_symlinks=False)
        os.chmod(path, 0o600, follow_symlinks=False)
    for name in directories:
        path = os.path.join(root, name)
        os.chown(path, {host_uid}, {host_gid}, follow_symlinks=False)
        os.chmod(path, 0o700, follow_symlinks=False)
os.chown('/data', {host_uid}, {host_gid}, follow_symlinks=False)
os.chmod('/data', 0o700, follow_symlinks=False)
"""
    result = _run_command(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0:0",
            "--entrypoint",
            "python",
            "-v",
            f"{data_dir}:/data",
            image,
            "-c",
            restore_code,
        ],
        stage="cleanup",
        error_code="runtime_data_ownership_restore_failed",
        check=False,
        timeout=30,
    )
    return result.returncode == 0


def _remove_runtime_image(image: str) -> bool:
    image = _require_runtime_image_id(image, stage="cleanup")
    result = _run_command(
        ["docker", "image", "rm", "--force", image],
        stage="cleanup",
        error_code="image_cleanup_failed",
        check=False,
        timeout=60,
    )
    return result.returncode == 0


def _runtime_environment() -> dict[str, str]:
    issuer = "http://127.0.0.1:8000"
    return {
        "FORMOWL_AUTH_MODE": "oauth_google",
        "FORMOWL_OAUTH_ISSUER": issuer,
        "FORMOWL_MCP_RESOURCE": f"{issuer}/mcp",
        "FORMOWL_CHATGPT_CLIENT_ID": "chatgpt_lifecycle_probe",
        "FORMOWL_CHATGPT_REDIRECT_URI": (
            "https://chatgpt.com/connector/oauth/formowl-lifecycle-probe"
        ),
        "FORMOWL_GOOGLE_CLIENT_ID": "formowl-lifecycle.apps.googleusercontent.com",
        "FORMOWL_GOOGLE_REDIRECT_URI": f"{issuer}/oauth/google/callback",
        "FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID": "lifecycle-operator",
        "FORMOWL_DATABASE_DSN_FILE": "/run/secrets/formowl_database_dsn",
        "FORMOWL_GOOGLE_CLIENT_SECRET_FILE": "/run/secrets/formowl_google_client_secret",
        "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE": ("/run/secrets/formowl_state_encryption_key"),
        "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE": "/run/secrets/formowl_signing_key_set",
        "FORMOWL_DATA_DIR": "/data",
        "FORMOWL_UPLOAD_SESSION_LIFETIME_SECONDS": "3600",
        "FORMOWL_CONNECTED_HOST": "0.0.0.0",
        "FORMOWL_CONNECTED_PORT": "8000",
        "FORMOWL_LOG_LEVEL": "warning",
        "FORMOWL_OAUTH_ALLOW_LOOPBACK_HTTP": "1",
    }


def _runtime_secret_mount_args(secret_dir: Path) -> list[str]:
    arguments: list[str] = []
    for name in _RUNTIME_SECRET_NAMES:
        arguments.extend(
            [
                "--mount",
                f"type=bind,src={secret_dir / name},dst=/run/secrets/{name},readonly",
            ]
        )
    return arguments


def _launcher_security_args() -> list[str]:
    arguments = [
        "--read-only",
        "--tmpfs",
        "/tmp:size=64m,mode=1777",
        "--tmpfs",
        "/run/formowl-secrets:size=1m,mode=0700",
        "--cap-drop",
        "ALL",
    ]
    for capability in LAUNCHER_CAPABILITIES:
        arguments.extend(["--cap-add", capability])
    arguments.extend(["--security-opt", "no-new-privileges:true"])
    return arguments


def _runtime_run_command(
    *,
    image: str,
    network: str,
    data_dir: Path,
    secret_dir: Path,
    command: str,
    name: str | None = None,
    detach: bool = False,
) -> list[str]:
    image = _require_runtime_image_id(image, stage="runtime_command")
    result = ["docker", "run"]
    if detach:
        result.append("--detach")
    else:
        result.append("--rm")
    if name is not None:
        result.extend(["--name", name])
    result.extend(
        [
            "--network",
            network,
            *_launcher_security_args(),
            "--stop-signal",
            "SIGTERM",
            "--stop-timeout",
            str(STOP_GRACE_SECONDS),
            "--mount",
            f"type=bind,src={data_dir},dst=/data",
            *_runtime_secret_mount_args(secret_dir),
        ]
    )
    for key, value in sorted(_runtime_environment().items()):
        result.extend(["-e", f"{key}={value}"])
    result.extend([image, command])
    return result


def _inside_helper_result(
    command: Sequence[str],
    *,
    stage: str,
    error_code: str,
    secret_values: Sequence[str],
    timeout: float = 120,
) -> dict[str, Any]:
    result = _run_command(
        command,
        stage=stage,
        error_code=error_code,
        timeout=timeout,
    )
    _assert_runtime_output_safe(
        result.stdout + result.stderr,
        secret_values=secret_values,
    )
    if sum(bool(line.strip()) for line in result.stdout.splitlines()) != 1:
        raise LifecycleProbeFailure(stage, f"{error_code}_output_invalid")
    try:
        payload = _json_line(
            result.stdout,
            stage=stage,
            error_code=f"{error_code}_output_invalid",
        )
    except LifecycleProbeFailure:
        raise
    except (ValueError, RecursionError):
        raise LifecycleProbeFailure(
            stage,
            f"{error_code}_output_invalid",
        ) from None
    try:
        canonical_payload = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise LifecycleProbeFailure(stage, f"{error_code}_output_invalid") from None
    _assert_runtime_output_safe(
        canonical_payload,
        secret_values=secret_values,
    )
    if payload.get("status") != "ok":
        raise LifecycleProbeFailure(stage, error_code)
    return payload


def _seed_oauth_state(
    *,
    image: str,
    network: str,
    data_dir: Path,
    secret_dir: Path,
    probe_dir: Path,
    secret_values: Sequence[str],
) -> dict[str, Any]:
    image = _require_runtime_image_id(image, stage="oauth_seed")
    token_file = probe_dir / "formowl_bearer_token"
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        *_launcher_security_args(),
        "--mount",
        f"type=bind,src={PROBE_SCRIPT},dst=/opt/formowl-lifecycle-probe.py,readonly",
        "--mount",
        f"type=bind,src={data_dir},dst=/data,readonly",
        "--mount",
        f"type=bind,src={probe_dir},dst=/probe",
        *_runtime_secret_mount_args(secret_dir),
        "-e",
        "PYTHONWARNINGS=ignore",
        "-e",
        "FORMOWL_LIFECYCLE_BEARER_FILE=/probe/formowl_bearer_token",
        "-e",
        "FORMOWL_CONTAINER_STAGE_SECRETS=1",
    ]
    for key, value in sorted(_runtime_environment().items()):
        command.extend(["-e", f"{key}={value}"])
    command.extend(
        [
            image,
            "python",
            "/opt/formowl-lifecycle-probe.py",
            "--inside-seed",
        ]
    )
    payload = _inside_helper_result(
        command,
        stage="oauth_seed",
        error_code="production_bridge_oauth_seed_failed",
        secret_values=secret_values,
        timeout=120,
    )
    try:
        if token_file.stat().st_mode & 0o777 != 0o400 or token_file.stat().st_size < 64:
            raise LifecycleProbeFailure("oauth_seed", "bearer_file_contract_invalid")
    except OSError:
        raise LifecycleProbeFailure("oauth_seed", "bearer_file_contract_invalid") from None
    return payload


def _run_official_container_client(
    *,
    image: str,
    network: str,
    runtime_name: str,
    probe_dir: Path,
    phase: str,
    secret_values: Sequence[str],
) -> dict[str, Any]:
    image = _require_runtime_image_id(image, stage=f"{phase}_mcp_client")
    token_file = probe_dir / "formowl_bearer_token"
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        *_launcher_security_args(),
        "--mount",
        f"type=bind,src={PROBE_SCRIPT},dst=/opt/formowl-lifecycle-probe.py,readonly",
        "--mount",
        f"type=bind,src={token_file},dst=/run/probe/bearer,readonly",
        "-e",
        f"FORMOWL_LIFECYCLE_RUNTIME_HOST={runtime_name}",
        "-e",
        f"FORMOWL_LIFECYCLE_CLIENT_PHASE={phase}",
        "-e",
        "PYTHONWARNINGS=ignore",
        image,
        "python",
        "/opt/formowl-lifecycle-probe.py",
        "--inside-client",
    ]
    return _inside_helper_result(
        command,
        stage=f"{phase}_mcp_client",
        error_code="official_mcp_client_failed",
        secret_values=secret_values,
        timeout=120,
    )


def _read_persisted_state(
    *,
    image: str,
    network: str,
    data_dir: Path,
    secret_dir: Path,
    phase: str,
    expected_allowed: int,
    expected_denied: int,
    secret_values: Sequence[str],
) -> dict[str, Any]:
    image = _require_runtime_image_id(image, stage=f"{phase}_state")
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        *_launcher_security_args(),
        "--mount",
        f"type=bind,src={PROBE_SCRIPT},dst=/opt/formowl-lifecycle-probe.py,readonly",
        "--mount",
        f"type=bind,src={data_dir},dst=/data,readonly",
        *_runtime_secret_mount_args(secret_dir),
        "-e",
        "PYTHONWARNINGS=ignore",
        "-e",
        f"FORMOWL_LIFECYCLE_STATE_PHASE={phase}",
        "-e",
        f"FORMOWL_LIFECYCLE_EXPECTED_ALLOWED_COUNT={expected_allowed}",
        "-e",
        f"FORMOWL_LIFECYCLE_EXPECTED_DENIED_COUNT={expected_denied}",
        "-e",
        "FORMOWL_CONTAINER_STAGE_SECRETS=1",
    ]
    for key, value in sorted(_runtime_environment().items()):
        command.extend(["-e", f"{key}={value}"])
    command.extend(
        [
            image,
            "python",
            "/opt/formowl-lifecycle-probe.py",
            "--inside-state",
        ]
    )
    return _inside_helper_result(
        command,
        stage=f"{phase}_state",
        error_code="persisted_state_probe_failed",
        secret_values=secret_values,
        timeout=120,
    )


def _build_runtime_image(iidfile: Path) -> tuple[str, dict[str, Any]]:
    implementation_contract_hash = _current_issue20_implementation_contract_hash()
    if iidfile.exists():
        raise LifecycleProbeFailure("image_build", "runtime_image_iidfile_exists")
    _run_command(
        [
            "docker",
            "build",
            "--file",
            str(RUNTIME_DOCKERFILE),
            "--label",
            f"{IMPLEMENTATION_CONTRACT_IMAGE_LABEL}={implementation_contract_hash}",
            "--iidfile",
            str(iidfile),
            str(ROOT),
        ],
        stage="image_build",
        error_code="runtime_image_build_failed",
        timeout=900,
    )
    try:
        runtime_image_id = iidfile.read_text(encoding="utf-8").strip()
    except OSError:
        raise LifecycleProbeFailure("image_build", "runtime_image_id_missing") from None
    runtime_image_id = _require_runtime_image_id(runtime_image_id, stage="image_build")
    result = _run_command(
        ["docker", "image", "inspect", runtime_image_id],
        stage="image_build",
        error_code="runtime_image_inspect_failed",
    )
    try:
        payload = json.loads(result.stdout)[0]
        config = payload["Config"]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError):
        raise LifecycleProbeFailure("image_build", "runtime_image_inspect_failed") from None
    contract = {
        "runtime_image_id": payload.get("Id"),
        "entrypoint": config.get("Entrypoint"),
        "cmd": config.get("Cmd"),
        "user": config.get("User"),
        "working_dir": config.get("WorkingDir"),
        "implementation_contract_hash": (config.get("Labels") or {}).get(
            IMPLEMENTATION_CONTRACT_IMAGE_LABEL
        ),
    }
    if contract != {
        "runtime_image_id": runtime_image_id,
        "entrypoint": ["formowl-container-entrypoint"],
        "cmd": ["serve"],
        "user": "root",
        "working_dir": "/home/formowl",
        "implementation_contract_hash": implementation_contract_hash,
    }:
        raise LifecycleProbeFailure("image_build", "runtime_image_contract_invalid")
    return runtime_image_id, contract


def _compose_environment(secret_dir: Path, runtime_image_id: str) -> dict[str, str]:
    runtime_image_id = _require_runtime_image_id(
        runtime_image_id,
        stage="compose_config",
    )
    postgres_image = _require_pinned_postgres_image(stage="compose_config")
    environ = dict(os.environ)
    environ.update(
        {
            "FORMOWL_RUNTIME_IMAGE": runtime_image_id,
            "FORMOWL_POSTGRES_IMAGE": postgres_image,
            "FORMOWL_OAUTH_ISSUER": "https://formowl-lifecycle.invalid",
            "FORMOWL_MCP_RESOURCE": "https://formowl-lifecycle.invalid/mcp",
            "FORMOWL_CHATGPT_CLIENT_ID": "chatgpt_lifecycle_probe",
            "FORMOWL_CHATGPT_REDIRECT_URI": (
                "https://chatgpt.com/connector/oauth/formowl-lifecycle-probe"
            ),
            "FORMOWL_GOOGLE_CLIENT_ID": "formowl-lifecycle.apps.googleusercontent.com",
            "FORMOWL_GOOGLE_REDIRECT_URI": (
                "https://formowl-lifecycle.invalid/oauth/google/callback"
            ),
            "FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID": "lifecycle-operator",
            "FORMOWL_POSTGRES_PASSWORD_FILE": str(secret_dir / "formowl_postgres_password"),
            "FORMOWL_DATABASE_DSN_FILE": str(secret_dir / "formowl_database_dsn"),
            "FORMOWL_GOOGLE_CLIENT_SECRET_FILE": str(secret_dir / "formowl_google_client_secret"),
            "FORMOWL_STATE_ENCRYPTION_KEY_FILE": str(secret_dir / "formowl_state_encryption_key"),
            "FORMOWL_SIGNING_KEY_SET_FILE": str(secret_dir / "formowl_signing_key_set"),
            "FORMOWL_SIGNING_KEY_CURRENT_FILE": str(secret_dir / "formowl_signing_key_current"),
            "FORMOWL_SIGNING_KEY_PREVIOUS_FILE": str(secret_dir / "formowl_signing_key_previous"),
        }
    )
    return environ


def _host_secret_source_contract(secret_dir: Path) -> dict[str, Any]:
    operator_uid = os.getuid()
    if operator_uid == RUNTIME_UID:
        raise LifecycleProbeFailure("secret_setup", "secret_owner_not_distinct")
    names = ("formowl_postgres_password", *_RUNTIME_SECRET_NAMES)
    try:
        metadata = [os.lstat(secret_dir / name) for name in names]
    except OSError:
        raise LifecycleProbeFailure("secret_setup", "secret_source_contract_invalid") from None
    if any(
        not stat.S_ISREG(item.st_mode)
        or item.st_uid != operator_uid
        or stat.S_IMODE(item.st_mode) != 0o400
        for item in metadata
    ):
        raise LifecycleProbeFailure("secret_setup", "secret_source_contract_invalid")
    return {
        "operator_owned_0400_secret_count": len(metadata),
        "secret_owner_distinct_from_runtime": True,
    }


def _validate_compose_config(
    secret_dir: Path,
    runtime_image_id: str,
) -> tuple[dict[str, Any], int]:
    runtime_image_id = _require_runtime_image_id(
        runtime_image_id,
        stage="compose_config",
    )
    postgres_image = _require_pinned_postgres_image(stage="compose_config")
    secret_source_contract = _host_secret_source_contract(secret_dir)
    result = _run_command(
        [
            "docker",
            "compose",
            "--file",
            str(COMPOSE_FILE),
            "config",
            "--format",
            "json",
        ],
        stage="compose_config",
        error_code="compose_config_failed",
        timeout=60,
        environ=_compose_environment(secret_dir, runtime_image_id),
    )
    try:
        payload = json.loads(result.stdout)
        services = payload["services"]
        connected = services["connected-mcp"]
        migrate = services["connected-migrate"]
        postgres = services["postgres"]
        project = services["project-mcp"]
        wiki = services["wiki-mcp"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise LifecycleProbeFailure("compose_config", "compose_config_invalid") from None
    health_test = connected.get("healthcheck", {}).get("test", [])
    stop_grace = connected.get("stop_grace_period")
    connected_tmpfs = {str(item).split(":", 1)[0] for item in connected.get("tmpfs", [])}
    connected_secret_sources = {
        item.get("source") for item in connected.get("secrets", []) if isinstance(item, Mapping)
    }
    migrate_secret_sources = {
        item.get("source") for item in migrate.get("secrets", []) if isinstance(item, Mapping)
    }
    postgres_secret_sources = {
        item.get("source") for item in postgres.get("secrets", []) if isinstance(item, Mapping)
    }
    if stop_grace not in {"30s", 30_000_000_000}:
        raise LifecycleProbeFailure("compose_config", "compose_stop_grace_invalid")
    if (
        connected.get("command") != ["serve"]
        or migrate.get("command") != ["migrate"]
        or connected.get("read_only") is not True
        or "ALL" not in connected.get("cap_drop", [])
        or set(connected.get("cap_add", [])) != set(LAUNCHER_CAPABILITIES)
        or "no-new-privileges:true" not in connected.get("security_opt", [])
        or not any("/readyz" in str(item) for item in health_test)
        or "formowl-container-entrypoint" not in health_test
        or connected_tmpfs != {"/tmp", "/run/formowl-secrets"}
        or connected.get("build", {}).get("dockerfile") != "containers/runtime/Dockerfile"
        or connected.get("image") != runtime_image_id
        or migrate.get("image") != runtime_image_id
        or project.get("image") != runtime_image_id
        or wiki.get("image") != runtime_image_id
        or postgres.get("image") != postgres_image
        or connected_secret_sources != set(_RUNTIME_SECRET_NAMES)
        or migrate_secret_sources != set(_RUNTIME_SECRET_NAMES)
        or postgres_secret_sources != {"formowl_postgres_password"}
        or project.get("entrypoint") is not None
        or wiki.get("entrypoint") is not None
        or project.get("command") != ["python", "-m", "formowl_project_mcp"]
        or wiki.get("command") != ["python", "-m", "formowl_wiki_mcp"]
        or "connected-init-secrets" in services
    ):
        raise LifecycleProbeFailure("compose_config", "compose_runtime_wiring_invalid")
    projection = {
        "connected_command": connected.get("command"),
        "migrate_command": migrate.get("command"),
        "read_only": connected.get("read_only"),
        "cap_drop": connected.get("cap_drop"),
        "cap_add": connected.get("cap_add"),
        "security_opt": connected.get("security_opt"),
        "tmpfs": sorted(connected_tmpfs),
        "stop_grace_period": stop_grace,
        "health_uses_readyz": any("/readyz" in str(item) for item in health_test),
        "health_uses_privilege_drop_launcher": ("formowl-container-entrypoint" in health_test),
        "dockerfile": connected.get("build", {}).get("dockerfile"),
        "connected_image_id": connected.get("image"),
        "migrate_image_id": migrate.get("image"),
        "project_image_id": project.get("image"),
        "wiki_image_id": wiki.get("image"),
        "postgres_image": postgres.get("image"),
        "connected_secret_sources": sorted(connected_secret_sources),
        "migrate_secret_sources": sorted(migrate_secret_sources),
        "postgres_secret_sources": sorted(postgres_secret_sources),
        "project_command": project.get("command"),
        "wiki_command": wiki.get("command"),
        "pre_secret_bootstrap_mode": "built_runtime_image_docker_run",
        **secret_source_contract,
    }
    return projection, len(services)


def _reserve_loopback_port() -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])
    except OSError:
        raise LifecycleProbeFailure("compose_live", "compose_publish_port_unavailable") from None


def _compose_command(project_name: str, *arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--file",
        str(COMPOSE_FILE),
        "--project-name",
        project_name,
        *arguments,
    ]


def _run_compose_command(
    project_name: str,
    *arguments: str,
    stage: str,
    error_code: str,
    environ: Mapping[str, str],
    secret_values: Sequence[str],
    check: bool = True,
    timeout: float = 180,
) -> subprocess.CompletedProcess[str]:
    result = _run_command(
        _compose_command(project_name, *arguments),
        stage=stage,
        error_code=error_code,
        check=check,
        timeout=timeout,
        environ=environ,
    )
    _assert_runtime_output_safe(
        result.stdout + result.stderr,
        secret_values=secret_values,
    )
    return result


def _compose_container_id(
    project_name: str,
    service: str,
    *,
    environ: Mapping[str, str],
    secret_values: Sequence[str],
) -> str:
    result = _run_compose_command(
        project_name,
        "ps",
        "--quiet",
        service,
        stage="compose_live",
        error_code="compose_container_lookup_failed",
        environ=environ,
        secret_values=secret_values,
        timeout=30,
    )
    values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(values) != 1 or re.fullmatch(r"[0-9a-f]{12,64}", values[0]) is None:
        raise LifecycleProbeFailure("compose_live", "compose_container_lookup_invalid")
    return values[0]


def _wait_for_healthy_container(name: str, *, stage: str) -> dict[str, Any]:
    for _attempt in range(120):
        state = _container_json(name).get("State", {})
        if not isinstance(state, Mapping):
            raise LifecycleProbeFailure(
                stage,
                "compose_container_health_invalid",
            ) from None
        if state.get("Running") is not True:
            raise LifecycleProbeFailure(stage, "compose_container_exited_before_healthy")
        health = state.get("Health", {})
        if not isinstance(health, Mapping):
            raise LifecycleProbeFailure(
                stage,
                "compose_container_health_invalid",
            ) from None
        if health.get("Status") == "healthy":
            return health
        if health.get("Status") == "unhealthy":
            raise LifecycleProbeFailure(stage, "compose_container_unhealthy")
        time.sleep(1)
    raise LifecycleProbeFailure(stage, "compose_container_health_timeout")


def _compose_postgres_secret_contract(
    container_name: str,
    *,
    secret_dir: Path,
) -> dict[str, Any]:
    payload = _container_json(container_name)
    matching = [
        mount
        for mount in payload.get("Mounts", [])
        if isinstance(mount, Mapping)
        and mount.get("Destination") == "/run/secrets/formowl_postgres_password"
    ]
    try:
        expected_source = (secret_dir / "formowl_postgres_password").resolve(strict=True)
        source_matches = (
            len(matching) == 1
            and Path(str(matching[0].get("Source", ""))).resolve(strict=True) == expected_source
        )
    except OSError:
        source_matches = False
    contract = {
        "same_operator_owned_source": source_matches,
        "secret_mount_read_only": len(matching) == 1 and matching[0].get("RW") is False,
        "postgres_healthy": payload.get("State", {}).get("Health", {}).get("Status") == "healthy",
    }
    if any(value is not True for value in contract.values()):
        raise LifecycleProbeFailure(
            "compose_postgres",
            "compose_postgres_secret_contract_invalid",
        )
    return contract


def _staged_secret_snapshot(
    container_name: str,
    *,
    secret_values: Sequence[str],
) -> dict[str, Any]:
    snapshot_code = f"""
import hashlib
import json
import os
from pathlib import Path
import stat

root = Path('/run/formowl-secrets')
root_stat = root.stat()
records = []
inodes = []
for path in sorted(root.iterdir()):
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or metadata.st_uid != {RUNTIME_UID}
        or metadata.st_gid != {RUNTIME_UID}
    ):
        raise SystemExit(2)
    records.append((path.name, hashlib.sha256(path.read_bytes()).hexdigest()))
    inodes.append((path.name, metadata.st_dev, metadata.st_ino))
if (
    stat.S_IMODE(root_stat.st_mode) != 0o700
    or root_stat.st_uid != {RUNTIME_UID}
    or root_stat.st_gid != {RUNTIME_UID}
):
    raise SystemExit(3)

def digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(payload).hexdigest()

print(json.dumps({{
    'content_hash': digest(records),
    'file_count': len(records),
    'inode_hash': digest((root_stat.st_dev, root_stat.st_ino, inodes)),
}}, sort_keys=True, separators=(',', ':')))
"""
    result = _run_command(
        [
            "docker",
            "exec",
            "--user",
            "0:0",
            container_name,
            "python",
            "-c",
            snapshot_code,
        ],
        stage="compose_secret_snapshot",
        error_code="compose_secret_snapshot_failed",
        timeout=20,
    )
    _assert_runtime_output_safe(
        result.stdout + result.stderr,
        secret_values=secret_values,
    )
    payload = _json_line(
        result.stdout,
        stage="compose_secret_snapshot",
        error_code="compose_secret_snapshot_invalid",
    )
    if (
        isinstance(payload.get("file_count"), bool)
        or not isinstance(payload.get("file_count"), int)
        or payload["file_count"] < 0
        or not isinstance(payload.get("content_hash"), str)
        or _SHA256_RE.fullmatch(payload["content_hash"]) is None
        or not isinstance(payload.get("inode_hash"), str)
        or _SHA256_RE.fullmatch(payload["inode_hash"]) is None
    ):
        raise LifecycleProbeFailure(
            "compose_secret_snapshot",
            "compose_secret_snapshot_invalid",
        )
    return {
        "content_hash": payload["content_hash"],
        "file_count": payload["file_count"],
        "instance_hash": _sha256_json(
            {
                "container_id": container_name,
                "inode_hash": payload["inode_hash"],
            }
        ),
    }


def _assert_container_removed(name: str) -> None:
    result = _run_command(
        ["docker", "inspect", name],
        stage="compose_secret_snapshot",
        error_code="retired_compose_container_probe_failed",
        check=False,
        timeout=15,
    )
    if result.returncode == 1:
        return
    if result.returncode == 0:
        raise LifecycleProbeFailure(
            "compose_secret_snapshot",
            "retired_compose_container_still_present",
        )
    raise LifecycleProbeFailure(
        "compose_secret_snapshot",
        "retired_compose_container_probe_failed",
    ) from None


def _run_actual_compose_journey(
    *,
    runtime_image_id: str,
    secret_dir: Path,
    password: str,
    key_a: bytes,
    key_b: bytes,
    secret_values: Sequence[str],
) -> dict[str, Any]:
    runtime_image_id = _require_runtime_image_id(
        runtime_image_id,
        stage="compose_live",
    )
    project_name = "formowl-compose-" + uuid.uuid4().hex[:12]
    compose_dsn = f"postgresql://formowl:{password}@postgres:5432/formowl"
    _atomic_write(secret_dir / "formowl_database_dsn", compose_dsn.encode("utf-8"))
    _atomic_write(secret_dir / "formowl_signing_key_current", key_a)
    _atomic_write(secret_dir / "formowl_signing_key_previous", key_b)
    _write_signing_manifest(secret_dir, phase="initial")
    compose_environment = _compose_environment(secret_dir, runtime_image_id)
    compose_environment["FORMOWL_CONNECTED_PUBLISH_PORT"] = str(_reserve_loopback_port())
    compose_secret_values = [*secret_values, compose_dsn]
    snapshots: list[dict[str, Any]] = []
    security_contracts: list[dict[str, Any]] = []
    jwks_phases: list[dict[str, Any]] = []
    runtime_log_hashes: list[str] = []
    retired_container_count = 0
    cleanup_ok = False
    try:
        _run_compose_command(
            project_name,
            "up",
            "--detach",
            "postgres",
            stage="compose_postgres",
            error_code="compose_postgres_start_failed",
            environ=compose_environment,
            secret_values=compose_secret_values,
            timeout=180,
        )
        postgres_id = _compose_container_id(
            project_name,
            "postgres",
            environ=compose_environment,
            secret_values=compose_secret_values,
        )
        _wait_for_healthy_container(postgres_id, stage="compose_postgres")
        postgres_contract = _compose_postgres_secret_contract(
            postgres_id,
            secret_dir=secret_dir,
        )

        migration_result = _run_compose_command(
            project_name,
            "run",
            "--rm",
            "--no-deps",
            "connected-migrate",
            stage="compose_migrate",
            error_code="compose_migrate_failed",
            environ=compose_environment,
            secret_values=compose_secret_values,
            timeout=180,
        )
        migration = _json_line(
            migration_result.stdout,
            stage="compose_migrate",
            error_code="compose_migrate_output_invalid",
        )
        if (
            migration.get("status") != "ok"
            or migration.get("applied_migration_count") != EXPECTED_MIGRATION_COUNT
            or migration.get("skipped_migration_count") != 0
        ):
            raise LifecycleProbeFailure(
                "compose_migrate",
                "compose_migrate_result_invalid",
            )

        preflight_result = _run_compose_command(
            project_name,
            "run",
            "--rm",
            "--no-deps",
            "connected-mcp",
            "preflight",
            stage="compose_preflight",
            error_code="compose_preflight_failed",
            environ=compose_environment,
            secret_values=compose_secret_values,
            timeout=180,
        )
        preflight = _json_line(
            preflight_result.stdout,
            stage="compose_preflight",
            error_code="compose_preflight_output_invalid",
        )
        if (
            preflight.get("status") != "ready"
            or not isinstance(preflight.get("checks"), Mapping)
            or not preflight["checks"]
            or any(value is not True for value in preflight["checks"].values())
        ):
            raise LifecycleProbeFailure(
                "compose_preflight",
                "compose_preflight_result_invalid",
            )

        phase_contracts = (
            ("initial", {INITIAL_KID}, 5),
            ("overlap", {INITIAL_KID, ROTATED_KID}, 6),
            ("retired", {ROTATED_KID}, 5),
        )
        prior_container: str | None = None
        for phase, expected_kids, expected_file_count in phase_contracts:
            if phase == "overlap":
                _atomic_write(secret_dir / "formowl_signing_key_previous", key_a)
                _atomic_write(secret_dir / "formowl_signing_key_current", key_b)
                _write_signing_manifest(
                    secret_dir,
                    phase="overlap",
                    verify_until=datetime.now(timezone.utc) + timedelta(minutes=10),
                )
            elif phase == "retired":
                _write_signing_manifest(secret_dir, phase="retired")
            _run_compose_command(
                project_name,
                "up",
                "--detach",
                "--no-deps",
                "--force-recreate",
                "connected-mcp",
                stage="compose_runtime",
                error_code="compose_runtime_start_failed",
                environ=compose_environment,
                secret_values=compose_secret_values,
                timeout=180,
            )
            current_container = _compose_container_id(
                project_name,
                "connected-mcp",
                environ=compose_environment,
                secret_values=compose_secret_values,
            )
            if prior_container is not None:
                if current_container == prior_container:
                    raise LifecycleProbeFailure(
                        "compose_secret_snapshot",
                        "compose_runtime_not_recreated",
                    )
                _assert_container_removed(prior_container)
                retired_container_count += 1
            _wait_for_healthy_container(current_container, stage="compose_runtime")
            ready = _wait_for_ready(current_container)
            if ready.get("status") != "ready":
                raise LifecycleProbeFailure(
                    "compose_runtime",
                    "compose_runtime_not_ready",
                )
            security_contracts.append(
                _runtime_security_contract(
                    current_container,
                    require_compose_healthcheck=True,
                )
            )
            snapshot = _staged_secret_snapshot(
                current_container,
                secret_values=compose_secret_values,
            )
            if snapshot["file_count"] != expected_file_count:
                raise LifecycleProbeFailure(
                    "compose_secret_snapshot",
                    "compose_secret_snapshot_count_invalid",
                )
            snapshots.append(snapshot)
            jwks_phases.append(
                _validate_public_jwks(
                    _fetch_public_jwks(current_container),
                    expected_kids,
                )
            )
            logs = _run_command(
                ["docker", "logs", current_container],
                stage="compose_runtime_logs",
                error_code="compose_runtime_logs_unavailable",
                timeout=30,
            )
            combined_logs = logs.stdout + logs.stderr
            _assert_runtime_output_safe(
                combined_logs,
                secret_values=compose_secret_values,
            )
            runtime_log_hashes.append(_sha256_json(combined_logs))
            prior_container = current_container

        if len({item["content_hash"] for item in snapshots}) != len(snapshots):
            raise LifecycleProbeFailure(
                "compose_secret_snapshot",
                "compose_secret_snapshot_content_not_rotated",
            )
        if len({item["instance_hash"] for item in snapshots}) != len(snapshots):
            raise LifecycleProbeFailure(
                "compose_secret_snapshot",
                "compose_secret_snapshot_not_fresh",
            )
        return {
            "postgres_secret_contract": postgres_contract,
            "migration": migration,
            "preflight_check_count": len(preflight["checks"]),
            "runtime_ready_count": len(phase_contracts),
            "healthcheck_success_count": len(security_contracts),
            "retired_container_count": retired_container_count,
            "runtime_process_uid": RUNTIME_UID,
            "security_contracts": security_contracts,
            "secret_snapshots": snapshots,
            "jwks_phases": jwks_phases,
            "runtime_log_hashes": runtime_log_hashes,
        }
    finally:
        cleanup = _run_compose_command(
            project_name,
            "down",
            "--volumes",
            "--remove-orphans",
            "--timeout",
            str(STOP_GRACE_SECONDS),
            stage="compose_cleanup",
            error_code="compose_cleanup_failed",
            environ=compose_environment,
            secret_values=compose_secret_values,
            check=False,
            timeout=180,
        )
        cleanup_ok = cleanup.returncode == 0
        if not cleanup_ok:
            raise LifecycleProbeFailure("compose_cleanup", "compose_cleanup_failed")


def _start_postgres(
    *,
    name: str,
    network: str,
    secret_dir: Path,
) -> None:
    postgres_image = _require_pinned_postgres_image(stage="postgres_start")
    _run_command(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "--network",
            network,
            "--tmpfs",
            "/var/lib/postgresql/data:rw,nosuid,nodev,size=512m",
            "--mount",
            (
                "type=bind,src="
                + str(secret_dir / "formowl_postgres_password")
                + ",dst=/run/secrets/formowl_postgres_password,readonly"
            ),
            "-e",
            "POSTGRES_DB=formowl",
            "-e",
            "POSTGRES_USER=formowl",
            "-e",
            "POSTGRES_PASSWORD_FILE=/run/secrets/formowl_postgres_password",
            postgres_image,
        ],
        stage="postgres_start",
        error_code="postgres_start_failed",
        timeout=60,
    )
    for _attempt in range(90):
        probe = _run_command(
            ["docker", "exec", name, "pg_isready", "-U", "formowl", "-d", "formowl"],
            stage="postgres_start",
            error_code="postgres_ready_probe_failed",
            check=False,
            timeout=10,
        )
        if probe.returncode == 0:
            return
        time.sleep(1)
    raise LifecycleProbeFailure("postgres_start", "postgres_not_ready")


def _database_connection_count(postgres_name: str) -> int:
    result = _run_command(
        [
            "docker",
            "exec",
            postgres_name,
            "psql",
            "-U",
            "formowl",
            "-d",
            "formowl",
            "-Atqc",
            (
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND backend_type = 'client backend' AND pid <> pg_backend_pid()"
            ),
        ],
        stage="database_activity",
        error_code="database_activity_probe_failed",
        timeout=15,
    )
    try:
        count = int(result.stdout.strip())
    except ValueError:
        raise LifecycleProbeFailure(
            "database_activity", "database_activity_probe_invalid"
        ) from None
    if count < 0:
        raise LifecycleProbeFailure("database_activity", "database_activity_probe_invalid")
    return count


def _wait_for_zero_database_connections(postgres_name: str) -> None:
    for _attempt in range(30):
        if _database_connection_count(postgres_name) == 0:
            return
        time.sleep(0.25)
    raise LifecycleProbeFailure("database_activity", "database_connection_not_released")


def _run_runtime_command(
    *,
    image: str,
    network: str,
    data_dir: Path,
    secret_dir: Path,
    command: str,
    stage: str,
    secret_values: Sequence[str],
) -> dict[str, Any]:
    result = _run_command(
        _runtime_run_command(
            image=image,
            network=network,
            data_dir=data_dir,
            secret_dir=secret_dir,
            command=command,
        ),
        stage=stage,
        error_code=f"connected_{command}_failed",
        timeout=120,
    )
    _assert_runtime_output_safe(result.stdout + result.stderr, secret_values=secret_values)
    return _json_line(result.stdout, stage=stage, error_code=f"connected_{command}_output_invalid")


def _start_runtime(
    *,
    image: str,
    network: str,
    data_dir: Path,
    secret_dir: Path,
    name: str,
) -> None:
    _run_command(
        _runtime_run_command(
            image=image,
            network=network,
            data_dir=data_dir,
            secret_dir=secret_dir,
            command="serve",
            name=name,
            detach=True,
        ),
        stage="runtime_start",
        error_code="runtime_container_start_failed",
        timeout=60,
    )


def _container_json(name: str) -> dict[str, Any]:
    result = _run_command(
        ["docker", "inspect", name],
        stage="runtime_inspect",
        error_code="runtime_container_inspect_failed",
    )
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        raise LifecycleProbeFailure("runtime_inspect", "runtime_container_inspect_failed") from None
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise LifecycleProbeFailure(
            "runtime_inspect",
            "runtime_container_inspect_failed",
        ) from None
    return payload[0]


def _runtime_security_contract(
    name: str,
    *,
    require_compose_healthcheck: bool = False,
) -> dict[str, Any]:
    payload = _container_json(name)
    config = payload.get("Config", {})
    host = payload.get("HostConfig", {})
    mounts = payload.get("Mounts", [])
    process_probe = """
import json
import os

def status(pid):
    values = {}
    with open(f'/proc/{pid}/status', encoding='utf-8') as stream:
        for line in stream:
            if ':' in line:
                key, value = line.split(':', 1)
                values[key] = value.strip()
    return {
        'uid': int(values['Uid'].split()[1]),
        'gid': int(values['Gid'].split()[1]),
        'groups': [int(value) for value in values.get('Groups', '').split()],
        'cap_inh': int(values['CapInh'], 16),
        'cap_prm': int(values['CapPrm'], 16),
        'cap_eff': int(values['CapEff'], 16),
        'cap_bnd': int(values['CapBnd'], 16),
        'cap_amb': int(values['CapAmb'], 16),
        'no_new_privs': int(values['NoNewPrivs']),
    }

try:
    os.seteuid(0)
except OSError:
    root_regain_denied = True
else:
    root_regain_denied = False

print(json.dumps({
    'probe_uid': os.geteuid(),
    'probe_gid': os.getegid(),
    'probe_groups': os.getgroups(),
    'root_regain_denied': root_regain_denied,
    'main': status(1),
}, sort_keys=True))
"""
    uid_result = _run_command(
        [
            "docker",
            "exec",
            name,
            "formowl-container-entrypoint",
            "python",
            "-c",
            process_probe,
        ],
        stage="runtime_security",
        error_code="runtime_uid_probe_failed",
        timeout=15,
    )
    try:
        process_identity = json.loads(uid_result.stdout)
        main_identity = process_identity["main"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise LifecycleProbeFailure("runtime_security", "runtime_uid_probe_invalid") from None
    secret_mounts = [
        mount for mount in mounts if str(mount.get("Destination", "")).startswith("/run/secrets/")
    ]
    environment_names = {
        item.split("=", 1)[0]
        for item in config.get("Env", [])
        if isinstance(item, str) and "=" in item
    }
    cap_add = sorted(str(value).removeprefix("CAP_") for value in host.get("CapAdd", []))
    capability_values = [
        main_identity.get(field)
        for field in ("cap_inh", "cap_prm", "cap_eff", "cap_bnd", "cap_amb")
    ]
    contract = {
        "path": payload.get("Path"),
        "args": payload.get("Args"),
        "image_user": config.get("User"),
        "process_uid": main_identity.get("uid"),
        "process_gid": main_identity.get("gid"),
        "process_supplementary_group_count": len(main_identity.get("groups", [])),
        # Linux exposes five independent capability sets. Missing or malformed
        # values must count as unsafe rather than collapsing to zero.
        "process_capability_count": sum(
            int(type(value) is not int or value != 0) for value in capability_values
        ),
        "process_no_new_privileges": main_identity.get("no_new_privs"),
        "probe_uid": process_identity.get("probe_uid"),
        "probe_gid": process_identity.get("probe_gid"),
        "probe_supplementary_group_count": len(process_identity.get("probe_groups", [])),
        "probe_root_regain_denied": process_identity.get("root_regain_denied"),
        "read_only": host.get("ReadonlyRootfs"),
        "cap_drop_all": "ALL" in host.get("CapDrop", []),
        "cap_add": cap_add,
        "no_new_privileges": "no-new-privileges:true" in host.get("SecurityOpt", []),
        "stop_signal": config.get("StopSignal"),
        "stop_timeout": config.get("StopTimeout"),
        "tmpfs_configured": set(host.get("Tmpfs", {})) == {"/tmp", "/run/formowl-secrets"},
        "secret_mount_count": len(secret_mounts),
        "secret_mounts_read_only": bool(secret_mounts)
        and all(mount.get("RW") is False for mount in secret_mounts),
        "data_mount_writable": any(
            mount.get("Destination") == "/data" and mount.get("RW") is True for mount in mounts
        ),
        "plaintext_secret_env_absent": not (environment_names & _FORBIDDEN_PLAINTEXT_SECRET_ENV),
    }
    expected = {
        "path": "formowl-container-entrypoint",
        "args": ["serve"],
        "image_user": "root",
        "process_uid": RUNTIME_UID,
        "process_gid": RUNTIME_UID,
        "process_supplementary_group_count": 0,
        "process_capability_count": 0,
        "process_no_new_privileges": 1,
        "probe_uid": RUNTIME_UID,
        "probe_gid": RUNTIME_UID,
        "probe_supplementary_group_count": 0,
        "probe_root_regain_denied": True,
        "read_only": True,
        "cap_drop_all": True,
        "cap_add": sorted(LAUNCHER_CAPABILITIES),
        "no_new_privileges": True,
        "stop_signal": "SIGTERM",
        "stop_timeout": STOP_GRACE_SECONDS,
        "tmpfs_configured": True,
        "secret_mount_count": len(_RUNTIME_SECRET_NAMES),
        "secret_mounts_read_only": True,
        "data_mount_writable": True,
        "plaintext_secret_env_absent": True,
    }
    if require_compose_healthcheck:
        health_test = config.get("Healthcheck", {}).get("Test", [])
        health_state = payload.get("State", {}).get("Health", {})
        successful_healthchecks = sum(
            item.get("ExitCode") == 0
            for item in health_state.get("Log", [])
            if isinstance(item, Mapping)
        )
        contract.update(
            {
                "health_uses_privilege_drop_launcher": (
                    "formowl-container-entrypoint" in health_test
                ),
                "health_status_healthy": health_state.get("Status") == "healthy",
                "successful_healthcheck_count": successful_healthchecks,
            }
        )
        expected.update(
            {
                "health_uses_privilege_drop_launcher": True,
                "health_status_healthy": True,
            }
        )
        if successful_healthchecks < 1:
            raise LifecycleProbeFailure(
                "runtime_security",
                "runtime_healthcheck_security_unverified",
            )
        expected["successful_healthcheck_count"] = successful_healthchecks
        expected["stop_signal"] = contract["stop_signal"]
        expected["stop_timeout"] = contract["stop_timeout"]
    if contract != expected:
        raise LifecycleProbeFailure("runtime_security", "runtime_security_contract_invalid")
    return contract


def _wait_for_ready(name: str) -> dict[str, Any]:
    code = (
        "import json,urllib.request;"
        "r=urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=5);"
        "print(r.read().decode('utf-8'))"
    )
    for _attempt in range(90):
        state = _container_json(name).get("State")
        if not isinstance(state, Mapping):
            raise LifecycleProbeFailure(
                "runtime_ready",
                "runtime_ready_state_invalid",
            ) from None
        if state.get("Running") is not True:
            raise LifecycleProbeFailure("runtime_ready", "runtime_exited_before_ready")
        result = _run_command(
            [
                "docker",
                "exec",
                name,
                "formowl-container-entrypoint",
                "python",
                "-c",
                code,
            ],
            stage="runtime_ready",
            error_code="runtime_ready_probe_failed",
            check=False,
            timeout=10,
        )
        if result.returncode not in {0, 1}:
            raise LifecycleProbeFailure(
                "runtime_ready",
                "runtime_ready_probe_failed",
            ) from None
        if result.returncode == 0:
            payload = _json_line(
                result.stdout,
                stage="runtime_ready",
                error_code="runtime_ready_payload_invalid",
            )
            checks = payload.get("checks")
            if (
                payload.get("status") == "ready"
                and isinstance(checks, Mapping)
                and checks
                and all(value is True for value in checks.values())
            ):
                return payload
        time.sleep(1)
    raise LifecycleProbeFailure("runtime_ready", "runtime_not_ready")


def _fetch_public_jwks(name: str) -> dict[str, Any]:
    code = (
        "import urllib.request;"
        "r=urllib.request.urlopen('http://127.0.0.1:8000/.well-known/jwks.json',timeout=5);"
        "print(r.read().decode('utf-8'))"
    )
    result = _run_command(
        [
            "docker",
            "exec",
            name,
            "formowl-container-entrypoint",
            "python",
            "-c",
            code,
        ],
        stage="jwks_probe",
        error_code="jwks_probe_failed",
        timeout=15,
    )
    return _json_line(
        result.stdout,
        stage="jwks_probe",
        error_code="jwks_payload_invalid",
    )


def _validate_public_jwks(jwks: Mapping[str, Any], expected_kids: set[str]) -> dict[str, Any]:
    keys = jwks.get("keys")
    if not isinstance(keys, list) or len(keys) != len(expected_kids):
        raise LifecycleProbeFailure("jwks_probe", "jwks_public_key_count_invalid")
    observed_kids: set[str] = set()
    private_fields = {"d", "p", "q", "dp", "dq", "qi", "oth", "k"}
    for key in keys:
        if not isinstance(key, Mapping):
            raise LifecycleProbeFailure("jwks_probe", "jwks_public_key_invalid")
        kid = key.get("kid")
        if not isinstance(kid, str):
            raise LifecycleProbeFailure("jwks_probe", "jwks_public_key_invalid")
        if private_fields & set(key):
            raise LifecycleProbeFailure("jwks_probe", "jwks_private_material_exposed")
        if key.get("kty") != "RSA" or key.get("alg") != "RS256":
            raise LifecycleProbeFailure("jwks_probe", "jwks_public_key_invalid")
        observed_kids.add(kid)
    if observed_kids != expected_kids:
        raise LifecycleProbeFailure("jwks_probe", "jwks_public_kid_set_invalid")
    return {"key_count": len(keys), "kid_set_hash": _sha256_json(sorted(observed_kids))}


def _assert_runtime_output_safe(text: str, *, secret_values: Sequence[str]) -> None:
    lowered = text.lower()
    forbidden_literals = (
        "traceback",
        "postgresql://",
        "database_dsn",
        "client_secret",
        "state_encryption_key",
        "begin private key",
        "authorization: bearer",
        "bearer ",
        "/run/secrets/",
        "/run/formowl-secrets",
    )
    if (
        any(value and value in text for value in secret_values)
        or any(value in lowered for value in forbidden_literals)
        or _JWT_RE.search(text) is not None
        or _EMAIL_RE.search(text) is not None
        or _RAW_PATH_RE.search(text) is not None
        or _SQL_RE.search(text) is not None
    ):
        raise LifecycleProbeFailure("runtime_logs", "runtime_output_leak_detected")


def _stop_runtime(
    name: str,
    *,
    postgres_name: str,
    secret_values: Sequence[str],
) -> tuple[str, int]:
    started = time.monotonic()
    _run_command(
        [
            "docker",
            "stop",
            "--signal",
            "SIGTERM",
            "--timeout",
            str(STOP_GRACE_SECONDS),
            name,
        ],
        stage="runtime_stop",
        error_code="runtime_sigterm_failed",
        timeout=STOP_GRACE_SECONDS + 10,
    )
    elapsed = time.monotonic() - started
    payload = _container_json(name)
    state = payload.get("State")
    if not isinstance(state, Mapping):
        raise LifecycleProbeFailure(
            "runtime_stop",
            "runtime_sigterm_exit_invalid",
        ) from None
    if (
        elapsed > STOP_GRACE_SECONDS + 5
        or state.get("Running") is not False
        or type(exit_code := state.get("ExitCode")) is not int
        or exit_code != 0
        or state.get("OOMKilled") is not False
        or state.get("Error") not in {None, ""}
    ):
        raise LifecycleProbeFailure("runtime_stop", "runtime_sigterm_exit_invalid")
    logs = _run_command(
        ["docker", "logs", name],
        stage="runtime_logs",
        error_code="runtime_logs_unavailable",
        timeout=30,
    )
    combined = logs.stdout + logs.stderr
    _assert_runtime_output_safe(combined, secret_values=secret_values)
    _wait_for_zero_database_connections(postgres_name)
    _run_command(
        ["docker", "rm", name],
        stage="runtime_cleanup",
        error_code="runtime_container_remove_failed",
        timeout=30,
    )
    return combined, len([line for line in combined.splitlines() if line.strip()])


def _data_state_hash(data_dir: Path) -> str:
    relative_entries: list[tuple[str, str, str | None]] = []
    try:
        for path in sorted(data_dir.rglob("*")):
            metadata = path.lstat()
            relative_path = path.relative_to(data_dir).as_posix()
            if stat.S_ISDIR(metadata.st_mode):
                relative_entries.append((relative_path, "directory", None))
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            relative_entries.append(
                (
                    relative_path,
                    "file",
                    "sha256:" + digest.hexdigest(),
                )
            )
    except OSError:
        raise LifecycleProbeFailure("data_restart", "runtime_data_state_unavailable") from None
    return _sha256_json(relative_entries)


def _contains_forbidden_report_text(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_forbidden_report_text(str(key)) or _contains_forbidden_report_text(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_report_text(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return (
            "postgresql://" in lowered
            or "http://" in lowered
            or "https://" in lowered
            or "bearer " in lowered
            or "begin private key" in lowered
            or "/run/secrets/" in lowered
            or "/run/formowl-secrets" in lowered
            or _JWT_RE.search(value) is not None
            or _EMAIL_RE.search(value) is not None
            or _RAW_PATH_RE.search(value) is not None
            or _SQL_RE.search(value) is not None
        )
    return False


def validate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if report.get("status") == "failed":
        if set(report) != {"artifact_id", "status", "failure_stage", "error_code"}:
            blockers.append("failed report keys mismatch")
        if report.get("artifact_id") != ARTIFACT_ID:
            blockers.append("artifact id mismatch")
        if not isinstance(report.get("failure_stage"), str) or not _SAFE_ERROR_RE.fullmatch(
            str(report.get("failure_stage", ""))
        ):
            blockers.append("failure stage is not safe")
        if not isinstance(report.get("error_code"), str) or not _SAFE_ERROR_RE.fullmatch(
            str(report.get("error_code", ""))
        ):
            blockers.append("failure code is not safe")
        if _contains_forbidden_report_text(report):
            blockers.append("failed report contains forbidden detail")
        return {"passed": not blockers, "blockers": blockers}

    expected_top_level = {
        "artifact_id",
        "status",
        "metrics",
        "safe_counts",
        "safe_hashes",
        "claim_boundary",
    }
    if set(report) != expected_top_level:
        blockers.append("success report keys mismatch")
    if report.get("artifact_id") != ARTIFACT_ID:
        blockers.append("artifact id mismatch")
    if report.get("status") != "passed":
        blockers.append("status must be passed")
    metrics = report.get("metrics")
    counts = report.get("safe_counts")
    hashes = report.get("safe_hashes")
    claims = report.get("claim_boundary")
    if not isinstance(metrics, Mapping) or set(metrics) != _METRIC_FIELDS:
        blockers.append("metrics keys mismatch")
        metrics = {}
    if any(value is not True for value in metrics.values()):
        blockers.append("all lifecycle metrics must pass")
    if not isinstance(counts, Mapping) or set(counts) != _COUNT_FIELDS:
        blockers.append("safe count keys mismatch")
        counts = {}
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counts.values()
    ):
        blockers.append("safe counts must be non-negative integers")
    expected_counts = {
        "compose_healthcheck_success_count": 3,
        "compose_migration_success_count": 1,
        "compose_old_snapshot_retirement_count": 2,
        "compose_postgres_0400_secret_read_count": 1,
        "compose_preflight_success_count": 1,
        "compose_runtime_process_uid": RUNTIME_UID,
        "compose_runtime_ready_count": 3,
        "compose_secret_snapshot_count": 3,
        "operator_owned_0400_secret_count": 7,
        "runtime_process_start_count": 4,
        "runtime_ready_count": 4,
        "sigterm_clean_exit_count": 4,
        "database_release_count": 4,
        "migration_applied_count": EXPECTED_MIGRATION_COUNT,
        "migration_restart_skipped_count": EXPECTED_MIGRATION_COUNT,
        "real_google_preflight_count": 1,
        "production_bridge_seed_count": 1,
        "bearer_whoami_success_count": 2,
        "bearer_expected_denial_count": 1,
        "persisted_user_count": 1,
        "persisted_external_identity_count": 1,
        "persisted_token_session_count": 1,
        "persisted_upload_session_count": 1,
        "persisted_file_audit_count": 1,
        "postgres_mcp_allowed_audit_count": 3,
        "postgres_mcp_denied_audit_count": 1,
        "persisted_state_snapshot_count": 2,
        "jwks_initial_public_key_count": 1,
        "jwks_overlap_public_key_count": 2,
        "jwks_retired_public_key_count": 1,
        "runtime_process_uid": RUNTIME_UID,
        "removed_runtime_container_count": 4,
        "database_active_connection_check_count": 4,
        "database_zero_connection_check_count": 4,
        "stop_grace_seconds": STOP_GRACE_SECONDS,
    }
    for key, expected in expected_counts.items():
        if counts.get(key) != expected:
            blockers.append(f"safe count is invalid: {key}")
    if counts.get("compose_service_count", 0) < 5:
        blockers.append("compose service count is invalid")
    if not isinstance(hashes, Mapping) or set(hashes) != _HASH_FIELDS:
        blockers.append("safe hash keys mismatch")
        hashes = {}
    if any(
        not isinstance(value, str) or not _SHA256_RE.fullmatch(value) for value in hashes.values()
    ):
        blockers.append("safe hashes must be sha256 values")
    elif len(hashes.values()) != len(set(hashes.values())):
        blockers.append("safe hashes must be independently bound")
    if hashes.get("implementation_contract_hash") != (
        _current_issue20_implementation_contract_hash()
    ):
        blockers.append("implementation contract hash is stale")
    implementation_contract_hash = hashes.get("implementation_contract_hash")
    runtime_image_contract_hash = hashes.get("runtime_image_contract_hash")
    compose_runtime_wiring_hash = hashes.get("compose_runtime_wiring_hash")
    if all(
        isinstance(value, str)
        for value in (
            implementation_contract_hash,
            runtime_image_contract_hash,
            compose_runtime_wiring_hash,
        )
    ) and hashes.get("command_contract_hash") != _runtime_command_contract_hash(
        implementation_contract_hash=implementation_contract_hash,
        runtime_image_contract_hash=runtime_image_contract_hash,
        compose_runtime_wiring_hash=compose_runtime_wiring_hash,
    ):
        blockers.append("command contract hash is stale")
    if not isinstance(claims, Mapping) or set(claims) != _CLAIM_FIELDS:
        blockers.append("claim boundary keys mismatch")
        claims = {}
    for key in _TRUE_CLAIMS:
        if claims.get(key) is not True:
            blockers.append(f"required bounded claim is false: {key}")
    for key in _FALSE_CLAIMS:
        if claims.get(key) is not False:
            blockers.append(f"excluded claim is not false: {key}")
    if _contains_forbidden_report_text(report):
        blockers.append("public report contains a URL, credential, path, token, or SQL")
    return {"passed": not blockers, "blockers": blockers}


def _build_success_report(evidence: Mapping[str, Any]) -> dict[str, Any]:
    implementation_contract_hash = _current_issue20_implementation_contract_hash()
    runtime_image_id = _require_runtime_image_id(
        evidence.get("runtime_image_id"),
        stage="report",
    )
    image_contract = evidence.get("image_contract")
    compose_projection = evidence.get("compose_projection")
    compose_journey = evidence.get("compose_journey")
    if (
        not isinstance(image_contract, Mapping)
        or image_contract.get("runtime_image_id") != runtime_image_id
    ):
        raise LifecycleProbeFailure("report", "runtime_image_report_binding_invalid")
    if (
        not isinstance(compose_projection, Mapping)
        or compose_projection.get("connected_image_id") != runtime_image_id
        or compose_projection.get("migrate_image_id") != runtime_image_id
        or compose_projection.get("project_image_id") != runtime_image_id
        or compose_projection.get("wiki_image_id") != runtime_image_id
        or compose_projection.get("postgres_image") != PINNED_POSTGRES_IMAGE
    ):
        raise LifecycleProbeFailure("report", "compose_image_report_binding_invalid")
    compose_security = (
        compose_journey.get("security_contracts") if isinstance(compose_journey, Mapping) else None
    )
    compose_snapshots = (
        compose_journey.get("secret_snapshots") if isinstance(compose_journey, Mapping) else None
    )
    compose_jwks = (
        compose_journey.get("jwks_phases") if isinstance(compose_journey, Mapping) else None
    )
    compose_migration = (
        compose_journey.get("migration") if isinstance(compose_journey, Mapping) else None
    )
    compose_postgres = (
        compose_journey.get("postgres_secret_contract")
        if isinstance(compose_journey, Mapping)
        else None
    )
    if (
        not isinstance(compose_journey, Mapping)
        or compose_journey.get("runtime_ready_count") != 3
        or compose_journey.get("healthcheck_success_count") != 3
        or compose_journey.get("retired_container_count") != 2
        or compose_journey.get("runtime_process_uid") != RUNTIME_UID
        or not isinstance(compose_journey.get("preflight_check_count"), int)
        or compose_journey["preflight_check_count"] < 1
        or not isinstance(compose_postgres, Mapping)
        or any(value is not True for value in compose_postgres.values())
        or not isinstance(compose_migration, Mapping)
        or compose_migration.get("status") != "ok"
        or compose_migration.get("applied_migration_count") != EXPECTED_MIGRATION_COUNT
        or compose_migration.get("skipped_migration_count") != 0
        or not isinstance(compose_security, list)
        or len(compose_security) != 3
        or not isinstance(compose_snapshots, list)
        or len(compose_snapshots) != 3
        or [item.get("file_count") for item in compose_snapshots] != [5, 6, 5]
        or len({item.get("content_hash") for item in compose_snapshots}) != 3
        or len({item.get("instance_hash") for item in compose_snapshots}) != 3
        or not isinstance(compose_jwks, list)
        or [item.get("key_count") for item in compose_jwks] != [1, 2, 1]
    ):
        raise LifecycleProbeFailure("report", "compose_live_report_binding_invalid")
    for contract in compose_security:
        if (
            not isinstance(contract, Mapping)
            or contract.get("process_uid") != RUNTIME_UID
            or contract.get("process_gid") != RUNTIME_UID
            or contract.get("process_supplementary_group_count") != 0
            or contract.get("process_capability_count") != 0
            or contract.get("process_no_new_privileges") != 1
            or contract.get("probe_uid") != RUNTIME_UID
            or contract.get("probe_gid") != RUNTIME_UID
            or contract.get("probe_supplementary_group_count") != 0
            or contract.get("probe_root_regain_denied") is not True
            or contract.get("health_uses_privilege_drop_launcher") is not True
            or contract.get("health_status_healthy") is not True
            or not isinstance(contract.get("successful_healthcheck_count"), int)
            or contract["successful_healthcheck_count"] < 1
        ):
            raise LifecycleProbeFailure(
                "report",
                "compose_live_security_binding_invalid",
            )
    if compose_projection.get("operator_owned_0400_secret_count") != 7:
        raise LifecycleProbeFailure("report", "compose_secret_owner_binding_invalid")
    runtime_image_contract_hash = _sha256_json(image_contract)
    compose_runtime_wiring_hash = _sha256_json(compose_projection)
    report = {
        "artifact_id": ARTIFACT_ID,
        "status": "passed",
        "metrics": {field: True for field in sorted(_METRIC_FIELDS)},
        "safe_counts": {
            "compose_healthcheck_success_count": compose_journey["healthcheck_success_count"],
            "compose_migration_success_count": 1,
            "compose_old_snapshot_retirement_count": compose_journey["retired_container_count"],
            "compose_postgres_0400_secret_read_count": 1,
            "compose_preflight_success_count": 1,
            "compose_runtime_process_uid": compose_journey["runtime_process_uid"],
            "compose_runtime_ready_count": compose_journey["runtime_ready_count"],
            "compose_secret_snapshot_count": len(compose_journey["secret_snapshots"]),
            "operator_owned_0400_secret_count": compose_projection[
                "operator_owned_0400_secret_count"
            ],
            "runtime_process_start_count": 4,
            "runtime_ready_count": 4,
            "sigterm_clean_exit_count": 4,
            "database_release_count": 4,
            "migration_applied_count": evidence["migration_applied_count"],
            "migration_restart_skipped_count": evidence["migration_restart_skipped_count"],
            "real_google_preflight_count": 1,
            "production_bridge_seed_count": evidence["oauth_seed"]["seed_count"],
            "bearer_whoami_success_count": 2,
            "bearer_expected_denial_count": evidence["first_client"]["denied_count"],
            "persisted_user_count": evidence["restart_state"]["counts"]["user_count"],
            "persisted_external_identity_count": evidence["restart_state"]["counts"][
                "external_identity_count"
            ],
            "persisted_token_session_count": evidence["restart_state"]["counts"][
                "token_session_count"
            ],
            "persisted_upload_session_count": evidence["restart_state"]["counts"][
                "upload_session_count"
            ],
            "persisted_file_audit_count": evidence["restart_state"]["counts"]["file_audit_count"],
            "postgres_mcp_allowed_audit_count": evidence["restart_state"]["counts"][
                "mcp_allowed_count"
            ],
            "postgres_mcp_denied_audit_count": evidence["restart_state"]["counts"][
                "mcp_denied_count"
            ],
            "persisted_state_snapshot_count": 2,
            "jwks_initial_public_key_count": 1,
            "jwks_overlap_public_key_count": 2,
            "jwks_retired_public_key_count": 1,
            "runtime_process_uid": RUNTIME_UID,
            "runtime_log_line_count": evidence["runtime_log_line_count"],
            "compose_service_count": evidence["compose_service_count"],
            "removed_runtime_container_count": 4,
            "database_active_connection_check_count": 4,
            "database_zero_connection_check_count": 4,
            "stop_grace_seconds": STOP_GRACE_SECONDS,
        },
        "safe_hashes": {
            "implementation_contract_hash": implementation_contract_hash,
            "runtime_image_contract_hash": runtime_image_contract_hash,
            "compose_runtime_wiring_hash": compose_runtime_wiring_hash,
            "migration_initial_result_hash": _sha256_json(evidence["initial_migration"]),
            "migration_restart_result_hash": _sha256_json(evidence["restart_migration"]),
            "compose_live_journey_hash": _sha256_json(compose_journey),
            "compose_live_security_contract_hash": _sha256_json(
                compose_journey["security_contracts"]
            ),
            "compose_secret_snapshot_set_hash": _sha256_json(compose_journey["secret_snapshots"]),
            "oauth_seed_state_hash": evidence["oauth_seed"]["seed_state_hash"],
            "first_client_result_hash": evidence["first_client"]["result_shape_hash"],
            "restart_client_result_hash": evidence["restart_client"]["result_shape_hash"],
            "first_persisted_state_hash": evidence["first_state"]["snapshot_hash"],
            "restart_persisted_state_hash": evidence["restart_state"]["snapshot_hash"],
            "persistent_core_state_hash": evidence["restart_state"]["core_state_hash"],
            "readiness_shape_hash": _sha256_json(evidence["readiness_shapes"]),
            "jwks_phase_set_hash": _sha256_json(evidence["jwks_phases"]),
            "runtime_security_contract_hash": _sha256_json(evidence["security_contract"]),
            "runtime_log_hash": _sha256_json(evidence["runtime_log_hashes"]),
            "data_restart_state_hash": evidence["data_state_hash"],
            "command_contract_hash": _runtime_command_contract_hash(
                implementation_contract_hash=implementation_contract_hash,
                runtime_image_contract_hash=runtime_image_contract_hash,
                compose_runtime_wiring_hash=compose_runtime_wiring_hash,
            ),
        },
        "claim_boundary": {
            "actual_compose_connected_stack": True,
            "actual_runtime_dockerfile_image": True,
            "actual_formowl_container_entrypoint": True,
            "live_postgresql": True,
            "real_google_metadata_and_jwks_preflight": True,
            "file_mounted_deployment_secrets": True,
            "production_subprocess_lifecycle": True,
            "signing_key_manifest_reload": True,
            "real_process_bearer_restart_persistence": True,
            "token_overlap_semantics_reverified": False,
            "live_google_account": False,
            "live_chatgpt_connector": False,
            "whole_issue_20_complete": False,
            "production_readiness": False,
        },
    }
    validation = validate_report(report)
    if not validation["passed"]:
        raise LifecycleProbeFailure("report", "lifecycle_report_validation_failed")
    return report


def run_probe(output_path: Path) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:12]
    network = f"formowl-runtime-lifecycle-{suffix}"
    postgres_name = f"formowl-runtime-postgres-{suffix}"
    runtime_names = [f"formowl-runtime-{phase}-{suffix}" for phase in ("a", "b", "c", "d")]
    cleanup_ok = True
    run_error: LifecycleProbeFailure | None = None
    evidence: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(
        prefix="formowl-runtime-lifecycle-",
        ignore_cleanup_errors=True,
    ) as temporary:
        temp_root = Path(temporary)
        secret_dir = temp_root / "secrets"
        data_dir = temp_root / "data"
        probe_dir = temp_root / "probe"
        secret_dir.mkdir(mode=0o755)
        data_dir.mkdir(mode=0o755)
        _prepare_probe_directory(probe_dir)
        postgres_started = False
        network_created = False
        image_built = False
        runtime_image_id: str | None = None
        secret_values: list[str] = []
        try:
            runtime_image_id, image_contract = _build_runtime_image(temp_root / "runtime-image.iid")
            image_built = True
            key_a, key_b = _generate_signing_keys(runtime_image_id, secret_dir)
            _prepare_data_directory(runtime_image_id, data_dir)
            password = os.urandom(24).hex()
            dsn = f"postgresql://formowl:{password}@{postgres_name}:5432/formowl"
            google_secret = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
            state_key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
            _atomic_write(secret_dir / "formowl_postgres_password", password.encode("ascii"))
            _atomic_write(secret_dir / "formowl_database_dsn", dsn.encode("utf-8"))
            _atomic_write(
                secret_dir / "formowl_google_client_secret",
                google_secret.encode("ascii"),
            )
            _atomic_write(
                secret_dir / "formowl_state_encryption_key",
                state_key.encode("ascii"),
            )
            _atomic_write(secret_dir / "formowl_signing_key_current", key_a)
            _atomic_write(secret_dir / "formowl_signing_key_previous", key_b)
            _write_signing_manifest(secret_dir, phase="initial")
            secret_values = [password, dsn, google_secret, state_key, str(temp_root)]

            compose_projection, compose_service_count = _validate_compose_config(
                secret_dir,
                runtime_image_id,
            )
            _run_command(
                ["docker", "network", "create", network],
                stage="network_setup",
                error_code="runtime_network_create_failed",
                timeout=30,
            )
            network_created = True
            _start_postgres(name=postgres_name, network=network, secret_dir=secret_dir)
            postgres_started = True

            initial_migration = _run_runtime_command(
                image=runtime_image_id,
                network=network,
                data_dir=data_dir,
                secret_dir=secret_dir,
                command="migrate",
                stage="initial_migration",
                secret_values=secret_values,
            )
            if (
                initial_migration.get("status") != "ok"
                or initial_migration.get("applied_migration_count") != EXPECTED_MIGRATION_COUNT
                or initial_migration.get("skipped_migration_count") != 0
            ):
                raise LifecycleProbeFailure("initial_migration", "initial_migration_result_invalid")
            preflight = _run_runtime_command(
                image=runtime_image_id,
                network=network,
                data_dir=data_dir,
                secret_dir=secret_dir,
                command="preflight",
                stage="real_google_preflight",
                secret_values=secret_values,
            )
            if (
                preflight.get("status") != "ready"
                or not isinstance(preflight.get("checks"), Mapping)
                or not preflight["checks"]
                or any(value is not True for value in preflight["checks"].values())
            ):
                raise LifecycleProbeFailure(
                    "real_google_preflight", "connected_preflight_not_ready"
                )
            oauth_seed = _seed_oauth_state(
                image=runtime_image_id,
                network=network,
                data_dir=data_dir,
                secret_dir=secret_dir,
                probe_dir=probe_dir,
                secret_values=secret_values,
            )

            readiness_shapes: list[dict[str, Any]] = []
            jwks_phases: list[dict[str, Any]] = []
            runtime_log_hashes: list[str] = []
            runtime_log_line_count = 0
            security_contract: dict[str, Any] | None = None
            data_state_after_first: str | None = None

            _start_runtime(
                image=runtime_image_id,
                network=network,
                data_dir=data_dir,
                secret_dir=secret_dir,
                name=runtime_names[0],
            )
            first_ready = _wait_for_ready(runtime_names[0])
            readiness_shapes.append(
                {"status": first_ready["status"], "checks": sorted(first_ready["checks"])}
            )
            security_contract = _runtime_security_contract(runtime_names[0])
            if _database_connection_count(postgres_name) < 1:
                raise LifecycleProbeFailure(
                    "database_activity", "runtime_database_connection_missing"
                )
            first_jwks = _validate_public_jwks(_fetch_public_jwks(runtime_names[0]), {INITIAL_KID})
            jwks_phases.append(first_jwks)
            first_client = _run_official_container_client(
                image=runtime_image_id,
                network=network,
                runtime_name=runtime_names[0],
                probe_dir=probe_dir,
                phase="first",
                secret_values=secret_values,
            )
            first_logs, first_line_count = _stop_runtime(
                runtime_names[0],
                postgres_name=postgres_name,
                secret_values=secret_values,
            )
            runtime_log_hashes.append(_sha256_json(first_logs))
            runtime_log_line_count += first_line_count
            first_state = _read_persisted_state(
                image=runtime_image_id,
                network=network,
                data_dir=data_dir,
                secret_dir=secret_dir,
                phase="first",
                expected_allowed=2,
                expected_denied=1,
                secret_values=secret_values,
            )
            data_state_after_first = _data_state_hash(data_dir)

            restart_migration = _run_runtime_command(
                image=runtime_image_id,
                network=network,
                data_dir=data_dir,
                secret_dir=secret_dir,
                command="migrate",
                stage="restart_migration",
                secret_values=secret_values,
            )
            if (
                restart_migration.get("status") != "ok"
                or restart_migration.get("applied_migration_count") != 0
                or restart_migration.get("skipped_migration_count") != EXPECTED_MIGRATION_COUNT
            ):
                raise LifecycleProbeFailure("restart_migration", "restart_migration_result_invalid")

            _start_runtime(
                image=runtime_image_id,
                network=network,
                data_dir=data_dir,
                secret_dir=secret_dir,
                name=runtime_names[1],
            )
            restart_ready = _wait_for_ready(runtime_names[1])
            readiness_shapes.append(
                {
                    "status": restart_ready["status"],
                    "checks": sorted(restart_ready["checks"]),
                }
            )
            if _database_connection_count(postgres_name) < 1:
                raise LifecycleProbeFailure(
                    "database_activity", "runtime_database_connection_missing"
                )
            restart_jwks = _validate_public_jwks(
                _fetch_public_jwks(runtime_names[1]), {INITIAL_KID}
            )
            jwks_phases.append(restart_jwks)
            restart_client = _run_official_container_client(
                image=runtime_image_id,
                network=network,
                runtime_name=runtime_names[1],
                probe_dir=probe_dir,
                phase="restart",
                secret_values=secret_values,
            )
            restart_logs, restart_line_count = _stop_runtime(
                runtime_names[1],
                postgres_name=postgres_name,
                secret_values=secret_values,
            )
            runtime_log_hashes.append(_sha256_json(restart_logs))
            runtime_log_line_count += restart_line_count
            restart_state = _read_persisted_state(
                image=runtime_image_id,
                network=network,
                data_dir=data_dir,
                secret_dir=secret_dir,
                phase="restart",
                expected_allowed=3,
                expected_denied=1,
                secret_values=secret_values,
            )
            if first_state["core_state_hash"] != restart_state["core_state_hash"]:
                raise LifecycleProbeFailure("restart_state", "persistent_core_state_changed")
            if data_state_after_first != _data_state_hash(data_dir):
                raise LifecycleProbeFailure("data_restart", "runtime_data_state_changed")

            overlap_until = datetime.now(timezone.utc) + timedelta(seconds=OVERLAP_WINDOW_SECONDS)
            _atomic_write(secret_dir / "formowl_signing_key_previous", key_a)
            _atomic_write(secret_dir / "formowl_signing_key_current", key_b)
            _write_signing_manifest(
                secret_dir,
                phase="overlap",
                verify_until=overlap_until,
            )
            _start_runtime(
                image=runtime_image_id,
                network=network,
                data_dir=data_dir,
                secret_dir=secret_dir,
                name=runtime_names[2],
            )
            second_ready = _wait_for_ready(runtime_names[2])
            readiness_shapes.append(
                {"status": second_ready["status"], "checks": sorted(second_ready["checks"])}
            )
            if _database_connection_count(postgres_name) < 1:
                raise LifecycleProbeFailure(
                    "database_activity", "runtime_database_connection_missing"
                )
            second_jwks = _validate_public_jwks(
                _fetch_public_jwks(runtime_names[2]),
                {INITIAL_KID, ROTATED_KID},
            )
            if datetime.now(timezone.utc) >= overlap_until:
                raise LifecycleProbeFailure("secret_reload", "overlap_window_exhausted")
            jwks_phases.append(second_jwks)
            second_logs, second_line_count = _stop_runtime(
                runtime_names[2],
                postgres_name=postgres_name,
                secret_values=secret_values,
            )
            runtime_log_hashes.append(_sha256_json(second_logs))
            runtime_log_line_count += second_line_count

            remaining_overlap = (overlap_until - datetime.now(timezone.utc)).total_seconds()
            if remaining_overlap > MAX_OVERLAP_WAIT_SECONDS:
                raise LifecycleProbeFailure("secret_reload", "overlap_wait_unbounded")
            wait_deadline = time.monotonic() + MAX_OVERLAP_WAIT_SECONDS
            while datetime.now(timezone.utc) <= overlap_until:
                if time.monotonic() >= wait_deadline:
                    raise LifecycleProbeFailure("secret_reload", "overlap_wait_timeout")
                time.sleep(0.25)
            _write_signing_manifest(secret_dir, phase="retired")
            _start_runtime(
                image=runtime_image_id,
                network=network,
                data_dir=data_dir,
                secret_dir=secret_dir,
                name=runtime_names[3],
            )
            third_ready = _wait_for_ready(runtime_names[3])
            readiness_shapes.append(
                {"status": third_ready["status"], "checks": sorted(third_ready["checks"])}
            )
            if _database_connection_count(postgres_name) < 1:
                raise LifecycleProbeFailure(
                    "database_activity", "runtime_database_connection_missing"
                )
            third_jwks = _validate_public_jwks(_fetch_public_jwks(runtime_names[3]), {ROTATED_KID})
            jwks_phases.append(third_jwks)
            third_logs, third_line_count = _stop_runtime(
                runtime_names[3],
                postgres_name=postgres_name,
                secret_values=secret_values,
            )
            runtime_log_hashes.append(_sha256_json(third_logs))
            runtime_log_line_count += third_line_count
            final_data_state = _data_state_hash(data_dir)
            if data_state_after_first != final_data_state:
                raise LifecycleProbeFailure("data_restart", "runtime_data_state_changed")
            compose_journey = _run_actual_compose_journey(
                runtime_image_id=runtime_image_id,
                secret_dir=secret_dir,
                password=password,
                key_a=key_a,
                key_b=key_b,
                secret_values=secret_values,
            )

            evidence = {
                "runtime_image_id": runtime_image_id,
                "image_contract": image_contract,
                "compose_projection": compose_projection,
                "compose_service_count": compose_service_count,
                "initial_migration": initial_migration,
                "restart_migration": restart_migration,
                "oauth_seed": oauth_seed,
                "first_client": first_client,
                "restart_client": restart_client,
                "first_state": first_state,
                "restart_state": restart_state,
                "migration_applied_count": initial_migration["applied_migration_count"],
                "migration_restart_skipped_count": restart_migration["skipped_migration_count"],
                "readiness_shapes": readiness_shapes,
                "jwks_phases": jwks_phases,
                "security_contract": security_contract,
                "runtime_log_hashes": runtime_log_hashes,
                "runtime_log_line_count": runtime_log_line_count,
                "data_state_hash": final_data_state,
                "compose_journey": compose_journey,
            }
        except LifecycleProbeFailure as error:
            run_error = error
        except Exception:
            run_error = LifecycleProbeFailure("orchestration", "lifecycle_probe_failed")
        finally:
            for runtime_name in runtime_names:
                removal = _run_command(
                    ["docker", "rm", "--force", runtime_name],
                    stage="cleanup",
                    error_code="runtime_cleanup_failed",
                    check=False,
                    timeout=30,
                )
                if removal.returncode not in {0, 1}:
                    cleanup_ok = False
            if postgres_started:
                stopped = _run_command(
                    ["docker", "stop", postgres_name],
                    stage="cleanup",
                    error_code="postgres_cleanup_failed",
                    check=False,
                    timeout=40,
                )
                cleanup_ok = cleanup_ok and stopped.returncode == 0
            if network_created:
                removed_network = _run_command(
                    ["docker", "network", "rm", network],
                    stage="cleanup",
                    error_code="network_cleanup_failed",
                    check=False,
                    timeout=30,
                )
                cleanup_ok = cleanup_ok and removed_network.returncode == 0
            if image_built and runtime_image_id is not None:
                cleanup_ok = (
                    _restore_data_directory_ownership(runtime_image_id, data_dir) and cleanup_ok
                )
                cleanup_ok = _remove_runtime_image(runtime_image_id) and cleanup_ok
        if run_error is not None:
            raise run_error
        if not cleanup_ok:
            raise LifecycleProbeFailure("cleanup", "docker_resource_cleanup_failed")
        report = _build_success_report(evidence)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            output_path,
            (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
            stage="report",
            error_code="report_output_write_failed",
            cleanup_error_code="report_output_cleanup_failed",
        )
        return report


def _failure_report(error: LifecycleProbeFailure) -> dict[str, str]:
    return {
        "artifact_id": ARTIFACT_ID,
        "status": "failed",
        "failure_stage": error.stage,
        "error_code": error.code,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-report", type=Path)
    inside = parser.add_mutually_exclusive_group()
    inside.add_argument("--inside-seed", action="store_true")
    inside.add_argument("--inside-client", action="store_true")
    inside.add_argument("--inside-state", action="store_true")
    arguments = parser.parse_args(argv)
    inside_mode = arguments.inside_seed or arguments.inside_client or arguments.inside_state
    if inside_mode:
        try:
            if arguments.inside_seed:
                value = _inside_seed_oauth_state()
            elif arguments.inside_client:
                value = asyncio.run(_inside_client_sequence())
            else:
                value = _inside_persisted_state()
        except LifecycleProbeFailure as error:
            print(
                json.dumps(
                    {"status": "error", "error": error.code},
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 1
        except Exception:
            print('{"error":"inside_lifecycle_probe_failed","status":"error"}')
            return 1
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
        return 0
    if arguments.validate_report is not None:
        try:
            value = json.loads(arguments.validate_report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        validation = validate_report(value if isinstance(value, Mapping) else {})
        print(json.dumps(validation, sort_keys=True, separators=(",", ":")))
        return 0 if validation["passed"] else 1
    output_path = arguments.output.resolve()
    try:
        report = run_probe(output_path)
    except LifecycleProbeFailure as error:
        report = _failure_report(error)
        if not (
            error.stage == "report"
            and error.code
            in {
                "report_output_write_failed",
                "report_output_cleanup_failed",
            }
        ):
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write(
                    output_path,
                    (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode(
                        "utf-8"
                    ),
                    stage="report",
                    error_code="report_output_write_failed",
                    cleanup_error_code="report_output_cleanup_failed",
                )
            except (LifecycleProbeFailure, OSError):
                pass
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 1
    except Exception:
        report = _failure_report(LifecycleProbeFailure("orchestration", "lifecycle_probe_failed"))
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(
                output_path,
                (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
                stage="report",
                error_code="report_output_write_failed",
                cleanup_error_code="report_output_cleanup_failed",
            )
        except (LifecycleProbeFailure, OSError):
            pass
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
