"""Executable production composition for the connected FormOwl MCP service."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import partial
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any, Protocol

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from formowl_auth import (
    FileAuditLogStore,
    FormOwlOAuthBridge,
    FormOwlSigningKey,
    FormOwlSigningKeySet,
    FormOwlTokenCodec,
    GoogleOidcClient,
    OAuthBridgeConfig,
    PostgreSQLOAuthRepository,
)
from formowl_contract import sha256_json
from formowl_graph.storage import SQLStatement
from formowl_ingestion.storage import UploadSessionStore
from formowl_mail import build_mail_upload_session_handler

from .remote import ConnectedMcpApplication, create_connected_mcp_application
from .operator import OperatorDirectory, OperatorDirectoryError
from .secret_init import SecretInitializationError, initialize_connected_secrets
from .semantic import SemanticMcpGateway


_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_SAFE_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_LOG_LEVELS = {"critical", "error", "warning", "info", "debug"}
_ISSUE20_AUDIT_EXPORT_ERROR = "connected_issue20_audit_export_failed"
_ISSUE20_AUDIT_ROW_LIMIT = 257
_ISSUE20_AUDIT_ACTIONS = (
    "google_authentication_failed",
    "google_authentication_succeeded",
    "mcp_authorization_allowed",
    "mcp_authorization_denied",
    "mcp_http_authentication_denied",
    "oauth_authorization_code_issued",
    "oauth_authorization_started",
    "oauth_external_identity_created",
    "oauth_external_identity_resolved",
    "oauth_invitation_accepted",
    "oauth_invitation_create",
    "oauth_owner_bootstrap_created",
    "oauth_token_session_issued",
    "oauth_token_session_revoked",
    "operator_workspace_member_remove",
    "operator_workspace_member_restore",
)
_ISSUE20_AUDIT_LINEAGE_FIELDS = (
    "sequence_index",
    "event_name",
    "action",
    "status",
    "reason_code",
    "actor_type",
    "actor_user_binding_hash",
    "actor_service_binding_hash",
    "approval_user_binding_hash",
    "workspace_binding_hash",
    "external_identity_binding_hash",
    "oauth_client_binding_hash",
    "oauth_token_session_binding_hash",
    "request_binding_hash",
    "tool_call_binding_hash",
    "metadata_shape_hash",
    "previous_audit_record_hash",
    "audit_record_hash",
)
_ISSUE20_AUDIT_LINEAGE = (
    "owner_bootstrap_created_service",
    "owner_oauth_authorization_started",
    "owner_google_authentication_succeeded",
    "owner_external_identity_created",
    "owner_invitation_accepted",
    "owner_authorization_code_issued",
    "owner_token_session_issued",
    "owner_whoami_allowed",
    "owner_upload_session_allowed",
    "second_user_invitation_created_service",
    "second_user_oauth_authorization_started",
    "second_user_google_authentication_succeeded",
    "second_user_external_identity_created",
    "second_user_invitation_accepted",
    "second_user_authorization_code_issued",
    "second_user_token_session_issued",
    "second_user_whoami_allowed",
    "second_user_owner_only_denied",
    "second_user_cross_workspace_denied",
    "forged_identity_denied",
    "second_user_membership_removed_service",
    "removed_old_token_denied",
    "restart_removed_old_token_denied",
    "removed_relink_oauth_authorization_started",
    "removed_relink_google_callback_denied",
    "second_user_membership_restored_service",
    "restore_relink_oauth_authorization_started",
    "restore_relink_google_authentication_succeeded",
    "restore_relink_external_identity_resolved",
    "restore_relink_authorization_code_issued",
    "restore_relink_token_session_issued",
    "restore_relink_whoami_allowed",
    "restored_session_revoked_service",
    "revoked_token_denied",
    "post_revocation_relink_oauth_authorization_started",
    "post_revocation_relink_google_authentication_succeeded",
    "post_revocation_relink_external_identity_resolved",
    "post_revocation_relink_authorization_code_issued",
    "post_revocation_relink_token_session_issued",
    "post_revocation_relink_whoami_allowed",
    "expired_token_denied",
    "post_expiry_relink_oauth_authorization_started",
    "post_expiry_relink_google_authentication_succeeded",
    "post_expiry_relink_external_identity_resolved",
    "post_expiry_relink_authorization_code_issued",
    "post_expiry_relink_token_session_issued",
    "post_expiry_relink_whoami_allowed",
)
_ISSUE20_RAW_AUDIT_FIELDS = {
    "audit_log_id",
    "actor_user_id",
    "actor_service_id",
    "actor_type",
    "action",
    "target_type",
    "target_id",
    "session_id",
    "workspace_id",
    "status",
    "external_identity_id",
    "oauth_client_id",
    "oauth_token_session_id",
    "request_id",
    "tool_call_id",
    "reason_code",
    "metadata",
    "timestamp",
}
_ISSUE20_ABSENT_VALUE_COMMITMENT = sha256_json(
    {"binding_type": "issue20_absent_value_commitment_v1"}
)
_SECRET_FILE_ENV = {
    "database_dsn": "FORMOWL_DATABASE_DSN_FILE",
    "google_client_secret": "FORMOWL_GOOGLE_CLIENT_SECRET_FILE",
    "state_encryption_key": "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE",
}
_SIGNING_KEY_SET_FILE_ENV = "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE"
_REQUIRED_CONFIG_ENV = {
    "issuer": "FORMOWL_OAUTH_ISSUER",
    "resource": "FORMOWL_MCP_RESOURCE",
    "chatgpt_client_id": "FORMOWL_CHATGPT_CLIENT_ID",
    "chatgpt_redirect_uri": "FORMOWL_CHATGPT_REDIRECT_URI",
    "google_client_id": "FORMOWL_GOOGLE_CLIENT_ID",
    "google_redirect_uri": "FORMOWL_GOOGLE_REDIRECT_URI",
}
_FORBIDDEN_IDENTITY_ENV = {
    "FORMOWL_MCP_SESSION_ID",
    "FORMOWL_MCP_ACTOR_USER_ID",
    "FORMOWL_MCP_WORKSPACE_ID",
}
_FORBIDDEN_PLAINTEXT_SECRET_ENV = {
    "FORMOWL_DATABASE_DSN",
    "FORMOWL_GOOGLE_CLIENT_SECRET",
    "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY",
    "FORMOWL_OAUTH_SIGNING_PRIVATE_KEY",
    "FORMOWL_OAUTH_SIGNING_KEY_SET",
}
_REQUIRED_OAUTH_TABLES = (
    "formowl_schema_migrations",
    "formowl_users",
    "formowl_workspace_members",
    "formowl_grants",
    "formowl_audit_log",
    "formowl_external_identities",
    "formowl_oauth_invitations",
    "formowl_oauth_owner_bootstraps",
    "formowl_oauth_client_authorizations",
    "formowl_oauth_transactions",
    "formowl_oauth_authorization_codes",
    "formowl_oauth_token_sessions",
)
_REQUIRED_SCHEMA_COLUMNS = {
    "formowl_schema_migrations": (
        "migration_id",
        "migration_version",
        "filename",
        "sql_sha256",
        "statement_count",
        "runner_version",
        "applied_at",
    ),
    "formowl_users": ("user_id", "status"),
    "formowl_workspace_members": ("workspace_id", "user_id", "role", "removed_at"),
    "formowl_grants": (
        "grant_id",
        "grantee_user_id",
        "scope_type",
        "scope_id",
        "permission",
        "expires_at",
        "revoked_at",
    ),
    "formowl_audit_log": (
        "audit_log_id",
        "actor_user_id",
        "actor_type",
        "actor_service_id",
        "external_identity_id",
        "oauth_client_id",
        "oauth_token_session_id",
        "request_id",
        "tool_call_id",
        "reason_code",
        "timestamp",
    ),
    "formowl_external_identities": (
        "external_identity_id",
        "provider",
        "issuer",
        "subject",
        "user_id",
        "email_verified",
        "status",
    ),
    "formowl_oauth_invitations": (
        "invitation_id",
        "normalized_email",
        "intended_user_id",
        "workspace_id",
        "role",
        "status",
        "expires_at",
        "accepted_external_identity_id",
    ),
    "formowl_oauth_owner_bootstraps": (
        "workspace_id",
        "idempotency_key_hash",
        "normalized_email",
        "invitation_id",
        "operator_service_id",
        "status",
        "created_at",
        "completed_at",
    ),
    "formowl_oauth_client_authorizations": (
        "oauth_client_authorization_id",
        "client_id",
        "external_identity_id",
        "user_id",
        "granted_scopes",
        "default_workspace_id",
        "revoked_at",
    ),
    "formowl_oauth_transactions": (
        "transaction_id",
        "google_state_hash",
        "encrypted_client_state",
        "google_nonce_hash",
        "client_id",
        "redirect_uri",
        "resource",
        "scopes",
        "code_challenge",
        "code_challenge_method",
        "expires_at",
        "status",
        "consumed_at",
    ),
    "formowl_oauth_authorization_codes": (
        "code_hash",
        "transaction_id",
        "user_id",
        "external_identity_id",
        "client_id",
        "redirect_uri",
        "resource",
        "scopes",
        "code_challenge",
        "expires_at",
        "consumed_at",
    ),
    "formowl_oauth_token_sessions": (
        "token_session_id",
        "user_id",
        "external_identity_id",
        "oauth_client_authorization_id",
        "client_id",
        "current_workspace_id",
        "resource",
        "scopes",
        "token_jti_hash",
        "issued_at",
        "expires_at",
        "revoked_at",
        "revocation_reason",
    ),
}
_REQUIRED_SCHEMA_CONSTRAINTS = (
    (
        "formowl_schema_migrations",
        "p",
        None,
        "%PRIMARY KEY (migration_id)%",
    ),
    (
        "formowl_schema_migrations",
        "u",
        None,
        "%UNIQUE (migration_version)%",
    ),
    (
        "formowl_schema_migrations",
        "c",
        None,
        "%sql_sha256%sha256:%",
    ),
    (
        "formowl_audit_log",
        "c",
        "chk_formowl_audit_actor_identity",
        "%actor_type%actor_user_id%actor_service_id%external_unauthenticated%",
    ),
    (
        "formowl_oauth_owner_bootstraps",
        "c",
        None,
        "%status%pending%completed_at IS NULL%completed%completed_at IS NOT NULL%",
    ),
    (
        "formowl_external_identities",
        "u",
        None,
        "%UNIQUE (issuer, subject)%",
    ),
    (
        "formowl_external_identities",
        "u",
        "uq_formowl_external_identity_user",
        "%UNIQUE (external_identity_id, user_id)%",
    ),
    (
        "formowl_oauth_owner_bootstraps",
        "u",
        None,
        "%UNIQUE (invitation_id)%",
    ),
    (
        "formowl_oauth_client_authorizations",
        "u",
        None,
        "%UNIQUE (client_id, external_identity_id)%",
    ),
    (
        "formowl_oauth_client_authorizations",
        "f",
        "fk_formowl_client_authorization_identity_user",
        "%FOREIGN KEY (external_identity_id, user_id) REFERENCES "
        "formowl_external_identities(external_identity_id, user_id) ON DELETE RESTRICT%",
    ),
    (
        "formowl_oauth_transactions",
        "u",
        None,
        "%UNIQUE (google_state_hash)%",
    ),
    (
        "formowl_oauth_authorization_codes",
        "u",
        None,
        "%UNIQUE (transaction_id)%",
    ),
    (
        "formowl_oauth_token_sessions",
        "u",
        None,
        "%UNIQUE (token_jti_hash)%",
    ),
    (
        "formowl_oauth_transactions",
        "c",
        None,
        "%code_challenge_method%S256%",
    ),
)
_REQUIRED_SCHEMA_INDEXES = (
    "idx_formowl_oauth_invitation_active_email",
    "idx_formowl_oauth_owner_bootstraps_status",
    "idx_formowl_oauth_transactions_effective",
    "idx_formowl_oauth_codes_effective",
    "idx_formowl_oauth_token_sessions_effective",
    "idx_formowl_audit_log_oauth_lineage",
    "idx_formowl_audit_log_actor_service",
)
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
}
_MAX_SECRET_FILE_BYTES = 64 * 1024


class ConnectedRuntimeError(RuntimeError):
    """Machine-safe runtime failure containing no secret or path detail."""

    def __init__(self, code: str) -> None:
        safe_code = code if _SAFE_ERROR_CODE.fullmatch(code) else "connected_runtime_error"
        self.code = safe_code
        super().__init__(safe_code)


@dataclass(frozen=True)
class DeploymentSecrets:
    database_dsn: str = field(repr=False)
    google_client_secret: str = field(repr=False)
    state_encryption_key: str = field(repr=False)
    signing_keys: tuple["DeploymentSigningKey", ...] = field(repr=False)


@dataclass(frozen=True)
class DeploymentSigningKey:
    kid: str
    private_key_pem: bytes = field(repr=False)
    active: bool
    verify_until: datetime | None = None


class DeploymentSecretSource(Protocol):
    def load(self, environ: Mapping[str, str]) -> DeploymentSecrets: ...


class FileDeploymentSecretSource:
    """Load deployment secrets only from operator-mounted files."""

    def load(self, environ: Mapping[str, str]) -> DeploymentSecrets:
        raw_values: dict[str, bytes] = {}
        for field_name, env_name in _SECRET_FILE_ENV.items():
            configured_path = environ.get(env_name)
            if not isinstance(configured_path, str) or not configured_path:
                raise ConnectedRuntimeError("deployment_secret_file_config_missing")
            raw_values[field_name] = _read_secret_file(configured_path)
        signing_manifest_path = environ.get(_SIGNING_KEY_SET_FILE_ENV)
        if not isinstance(signing_manifest_path, str) or not signing_manifest_path:
            raise ConnectedRuntimeError("deployment_secret_file_config_missing")
        signing_keys = _load_signing_key_manifest(signing_manifest_path)
        try:
            database_dsn = raw_values["database_dsn"].decode("utf-8")
            google_client_secret = raw_values["google_client_secret"].decode("utf-8")
            state_encryption_key = raw_values["state_encryption_key"].decode("ascii")
        except (UnicodeDecodeError, KeyError):
            raise ConnectedRuntimeError("deployment_secret_file_invalid") from None
        if not database_dsn or not google_client_secret or not state_encryption_key:
            raise ConnectedRuntimeError("deployment_secret_file_invalid")
        return DeploymentSecrets(
            database_dsn=database_dsn,
            google_client_secret=google_client_secret,
            state_encryption_key=state_encryption_key,
            signing_keys=signing_keys,
        )


def _read_secret_file(configured_path: str) -> bytes:
    try:
        value = Path(configured_path).read_bytes()
    except OSError:
        raise ConnectedRuntimeError("deployment_secret_file_unavailable") from None
    if not value or len(value) > _MAX_SECRET_FILE_BYTES or b"\x00" in value:
        raise ConnectedRuntimeError("deployment_secret_file_invalid")
    return value.strip()


def _load_signing_key_manifest(configured_path: str) -> tuple[DeploymentSigningKey, ...]:
    try:
        manifest = json.loads(_read_secret_file(configured_path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid") from None
    if not isinstance(manifest, dict) or set(manifest) != {"version", "keys"}:
        raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid")
    if manifest.get("version") != 1 or not isinstance(manifest.get("keys"), list):
        raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid")
    keys: list[DeploymentSigningKey] = []
    kids: set[str] = set()
    key_paths: set[str] = set()
    for item in manifest["keys"]:
        if not isinstance(item, dict) or not {
            "kid",
            "private_key_file",
            "active",
        } <= set(item) <= {
            "kid",
            "private_key_file",
            "active",
            "verify_until",
        }:
            raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid")
        kid = item.get("kid")
        private_key_file = item.get("private_key_file")
        active = item.get("active")
        verify_until_value = item.get("verify_until")
        if (
            not isinstance(kid, str)
            or not _SAFE_IDENTIFIER.fullmatch(kid)
            or kid in kids
            or not isinstance(private_key_file, str)
            or not private_key_file
            or private_key_file in key_paths
            or not isinstance(active, bool)
        ):
            raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid")
        verify_until: datetime | None = None
        if verify_until_value is not None:
            if not isinstance(verify_until_value, str):
                raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid")
            try:
                verify_until = datetime.fromisoformat(verify_until_value.replace("Z", "+00:00"))
            except ValueError:
                raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid") from None
            if verify_until.tzinfo is None:
                raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid")
            verify_until = verify_until.astimezone(timezone.utc)
        if active and verify_until is not None:
            raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid")
        if not active and verify_until is None:
            raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid")
        keys.append(
            DeploymentSigningKey(
                kid=kid,
                private_key_pem=_read_secret_file(private_key_file),
                active=active,
                verify_until=verify_until,
            )
        )
        kids.add(kid)
        key_paths.add(private_key_file)
    if not keys or sum(key.active for key in keys) != 1:
        raise ConnectedRuntimeError("deployment_signing_key_manifest_invalid")
    return tuple(keys)


@dataclass(frozen=True)
class ConnectedRuntimeConfig:
    oauth: OAuthBridgeConfig
    database_dsn: str = field(repr=False)
    signing_key_set: FormOwlSigningKeySet = field(repr=False)
    host: str
    port: int
    log_level: str
    data_dir: Path = field(default=Path("/data"), repr=False)
    upload_session_lifetime_seconds: int = 3600
    owner_bootstrap_operator_service_id: str | None = None

    @classmethod
    def from_env_and_secrets(
        cls,
        environ: Mapping[str, str],
        *,
        secret_source: DeploymentSecretSource | None = None,
    ) -> "ConnectedRuntimeConfig":
        if environ.get("FORMOWL_AUTH_MODE", "oauth_google") != "oauth_google":
            raise ConnectedRuntimeError("connected_google_oauth_required")
        if any(environ.get(name) for name in _FORBIDDEN_IDENTITY_ENV):
            raise ConnectedRuntimeError("connected_manual_identity_forbidden")
        if any(environ.get(name) for name in _FORBIDDEN_PLAINTEXT_SECRET_ENV):
            raise ConnectedRuntimeError("connected_plaintext_secret_forbidden")
        values: dict[str, str] = {}
        for field_name, env_name in _REQUIRED_CONFIG_ENV.items():
            value = environ.get(env_name)
            if not isinstance(value, str) or not value:
                raise ConnectedRuntimeError("connected_config_missing")
            values[field_name] = value
        host = environ.get("FORMOWL_CONNECTED_HOST", "127.0.0.1")
        port_text = environ.get("FORMOWL_CONNECTED_PORT", "8000")
        log_level = environ.get("FORMOWL_LOG_LEVEL", "info").lower()
        data_dir_value = environ.get("FORMOWL_DATA_DIR", "/data")
        upload_session_lifetime_text = environ.get(
            "FORMOWL_UPLOAD_SESSION_LIFETIME_SECONDS",
            "3600",
        )
        owner_bootstrap_operator_service_id = environ.get(
            "FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID"
        )
        if (
            not isinstance(host, str)
            or (host != "::" and not _SAFE_HOST.fullmatch(host))
            or any(char.isspace() for char in host)
        ):
            raise ConnectedRuntimeError("connected_host_invalid")
        try:
            port = int(port_text)
        except (TypeError, ValueError):
            raise ConnectedRuntimeError("connected_port_invalid") from None
        if isinstance(port_text, bool) or not 1 <= port <= 65535:
            raise ConnectedRuntimeError("connected_port_invalid")
        if log_level not in _SAFE_LOG_LEVELS:
            raise ConnectedRuntimeError("connected_log_level_invalid")
        if (
            not isinstance(data_dir_value, str)
            or not data_dir_value
            or "\x00" in data_dir_value
            or not Path(data_dir_value).is_absolute()
        ):
            raise ConnectedRuntimeError("connected_data_dir_invalid")
        try:
            upload_session_lifetime_seconds = int(upload_session_lifetime_text)
        except (TypeError, ValueError):
            raise ConnectedRuntimeError("connected_upload_lifetime_invalid") from None
        if not 60 <= upload_session_lifetime_seconds <= 86400:
            raise ConnectedRuntimeError("connected_upload_lifetime_invalid")
        if owner_bootstrap_operator_service_id is not None and not _SAFE_IDENTIFIER.fullmatch(
            owner_bootstrap_operator_service_id
        ):
            raise ConnectedRuntimeError("connected_bootstrap_operator_invalid")
        secrets = (secret_source or FileDeploymentSecretSource()).load(environ)
        try:
            oauth = OAuthBridgeConfig(
                issuer=values["issuer"],
                resource=values["resource"],
                chatgpt_client_id=values["chatgpt_client_id"],
                chatgpt_redirect_uri=values["chatgpt_redirect_uri"],
                google_client_id=values["google_client_id"],
                google_client_secret=secrets.google_client_secret,
                google_redirect_uri=values["google_redirect_uri"],
                state_encryption_key=secrets.state_encryption_key,
                allow_loopback_http=environ.get("FORMOWL_OAUTH_ALLOW_LOOPBACK_HTTP") == "1",
            )
        except Exception:
            raise ConnectedRuntimeError("connected_oauth_config_invalid") from None
        try:
            signing_key_set = FormOwlSigningKeySet(
                [
                    FormOwlSigningKey(
                        kid=key.kid,
                        private_key_pem=key.private_key_pem,
                        active=key.active,
                        verify_until=key.verify_until,
                    )
                    for key in secrets.signing_keys
                ]
            )
        except Exception:
            raise ConnectedRuntimeError("connected_signing_key_invalid") from None
        return cls(
            oauth=oauth,
            database_dsn=secrets.database_dsn,
            signing_key_set=signing_key_set,
            host=host,
            port=port,
            log_level=log_level,
            data_dir=Path(data_dir_value),
            upload_session_lifetime_seconds=upload_session_lifetime_seconds,
            owner_bootstrap_operator_service_id=owner_bootstrap_operator_service_id,
        )


@dataclass
class ConnectedRuntime:
    config: ConnectedRuntimeConfig
    repository: PostgreSQLOAuthRepository
    http_client: Any
    google_client: GoogleOidcClient
    bridge: FormOwlOAuthBridge
    application: ConnectedMcpApplication
    _running: bool = field(default=False, init=False, repr=False)
    _lifespan_active: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _close_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def _require_stateful_oauth(self) -> None:
        oauth = getattr(self.config, "oauth", None)
        if getattr(oauth, "chatgpt_callback_mode", "production_exact") == "discovery_only":
            raise ConnectedRuntimeError("connected_discovery_only")

    @classmethod
    async def compose(
        cls,
        config: ConnectedRuntimeConfig,
        *,
        semantic_gateway: SemanticMcpGateway | None = None,
        http_client: Any | None = None,
    ) -> "ConnectedRuntime":
        repository: PostgreSQLOAuthRepository | None = None
        resolved_http_client: Any | None = None
        try:
            repository = PostgreSQLOAuthRepository.connect(config.database_dsn)
            resolved_http_client = http_client or httpx.AsyncClient(
                follow_redirects=False,
                timeout=10.0,
            )
            # GoogleOidcClient validates transport behavior when it performs
            # provider calls. Composition only owns deterministic cleanup, and
            # tests may replace the provider methods before any HTTP request.
            if not callable(getattr(resolved_http_client, "aclose", None)):
                raise ConnectedRuntimeError("connected_http_client_invalid")
            google_client = GoogleOidcClient(
                config=config.oauth,
                http_client=resolved_http_client,
            )
            token_codec = FormOwlTokenCodec(
                issuer=config.oauth.issuer,
                client_id=config.oauth.chatgpt_client_id,
                key_set=config.signing_key_set,
                lifetime_seconds=config.oauth.access_token_lifetime_seconds,
                clock_skew_seconds=config.oauth.clock_skew_seconds,
            )
            operator_authorizer = None
            if config.owner_bootstrap_operator_service_id is not None:
                expected_operator = config.owner_bootstrap_operator_service_id
                operator_authorizer = partial(
                    hmac.compare_digest,
                    expected_operator,
                )
            bridge = FormOwlOAuthBridge(
                config=config.oauth,
                repository=repository,
                google_client=google_client,
                token_codec=token_codec,
                owner_bootstrap_operator_authorizer=operator_authorizer,
            )
            resolved_semantic_gateway = semantic_gateway or _build_runtime_semantic_gateway(config)
            if resolved_semantic_gateway.upload_session_handler is None:
                raise ConnectedRuntimeError("connected_upload_handler_required")
            application = create_connected_mcp_application(
                bridge=bridge,
                config=config.oauth,
                google_client=google_client,
                semantic_gateway=resolved_semantic_gateway,
                additional_routes=[
                    Route("/healthz", _healthz_endpoint, methods=["GET"]),
                    Route("/readyz", _readyz_endpoint, methods=["GET"]),
                ],
                manage_session_manager_lifespan=False,
                environ={"FORMOWL_AUTH_MODE": "oauth_google"},
            )
            if application.manages_session_manager_lifespan:
                raise ConnectedRuntimeError("connected_lifespan_double_management")
            runtime = cls(
                config=config,
                repository=repository,
                http_client=resolved_http_client,
                google_client=google_client,
                bridge=bridge,
                application=application,
            )
            application.app.state.connected_runtime = runtime
            application.app.router.lifespan_context = runtime.lifespan
            return runtime
        except Exception as error:
            if resolved_http_client is not None:
                try:
                    await resolved_http_client.aclose()
                except Exception:
                    pass
            if repository is not None:
                try:
                    repository.close()
                except Exception:
                    pass
            if isinstance(error, ConnectedRuntimeError):
                raise
            raise ConnectedRuntimeError("connected_runtime_composition_failed") from None

    @asynccontextmanager
    async def lifespan(self, _app: Any) -> AsyncIterator[None]:
        if self._closed or self._lifespan_active:
            raise ConnectedRuntimeError("connected_lifecycle_invalid")
        self._lifespan_active = True
        active_error = False
        try:
            async with self.application.session_manager.run():
                self._running = True
                yield
        except BaseException:
            active_error = True
            raise
        finally:
            self._running = False
            self._lifespan_active = False
            try:
                await self.aclose()
            except Exception:
                if not active_error:
                    raise

    async def aclose(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            close_error: Exception | None = None
            try:
                await self.http_client.aclose()
            except Exception as error:
                close_error = error
            try:
                self.repository.close()
            except Exception as error:
                if close_error is None:
                    close_error = error
            if close_error is not None:
                raise ConnectedRuntimeError("connected_runtime_close_failed") from None

    async def readiness(
        self,
        *,
        require_running: bool,
        refresh_google: bool = False,
    ) -> dict[str, Any]:
        checks = {
            "runtime": self._running if require_running else not self._closed,
            "database": False,
            "schema": False,
            "configuration": False,
            "oauth_callback": False,
            "signing_key": False,
            "google_oidc": False,
            "upload_store": False,
        }
        try:
            checks["database"] = self.repository.health_check() is True
        except Exception:
            checks["database"] = False
        if checks["database"]:
            checks["schema"] = _repository_schema_ready(self.repository)
        oauth = self.config.oauth
        checks["configuration"] = (
            oauth.resource == f"{oauth.issuer}/mcp"
            and oauth.google_redirect_uri == f"{oauth.issuer}/oauth/google/callback"
            and oauth.scopes == ("formowl.use",)
            and oauth.chatgpt_callback_mode
            in {"production_exact", "discovery_only", "loopback_test"}
        )
        checks["oauth_callback"] = oauth.chatgpt_callback_mode in {
            "production_exact",
            "loopback_test",
        }
        try:
            jwks = self.config.signing_key_set.public_jwks(now=datetime.now(timezone.utc))
            checks["signing_key"] = (
                len(jwks.get("keys", [])) >= 1
                and self.config.signing_key_set.active_key.active is True
            )
        except Exception:
            checks["signing_key"] = False
        try:
            await self.google_client.load_provider_metadata(refresh=refresh_google)
            await self.google_client.load_jwks(refresh=refresh_google)
            checks["google_oidc"] = True
        except Exception:
            checks["google_oidc"] = False
        checks["upload_store"] = _runtime_data_stores_ready(self.config.data_dir)
        if oauth.chatgpt_callback_mode == "discovery_only":
            discovery_operational = all(
                value for name, value in checks.items() if name != "oauth_callback"
            )
            status = "discovery_only" if discovery_operational else "not_ready"
        else:
            status = "ready" if all(checks.values()) else "not_ready"
        return {
            "status": status,
            "mode": oauth.chatgpt_callback_mode,
            "checks": checks,
        }

    async def preflight(self) -> dict[str, Any]:
        return await self.readiness(require_running=False, refresh_google=True)

    def migrate(self) -> dict[str, Any]:
        try:
            result = self.repository.apply_migrations()
        except Exception:
            raise ConnectedRuntimeError("connected_migration_failed") from None
        return result.to_safe_dict()

    def bootstrap_owner(
        self,
        *,
        workspace_id: str,
        email: str,
        expires_at: datetime,
        idempotency_key: str,
        operator_service_id: str,
    ) -> dict[str, Any]:
        self._require_stateful_oauth()
        try:
            invitation = self.bridge.bootstrap_owner_invitation(
                workspace_id=workspace_id,
                email=email,
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                operator_service_id=operator_service_id,
                now=datetime.now(timezone.utc),
            )
        except Exception:
            raise ConnectedRuntimeError("connected_owner_bootstrap_failed") from None
        return {
            "status": "ok",
            "invitation_id": invitation.invitation_id,
            "workspace_id": invitation.workspace_id,
        }

    def invite_user(
        self,
        *,
        workspace_id: str,
        email: str,
        role: str,
        invited_by_user_id: str,
        operator_service_id: str,
        expires_at: datetime,
        intended_user_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_stateful_oauth()
        try:
            invitation = self.bridge.provision_invitation(
                email=email,
                workspace_id=workspace_id,
                role=role,
                invited_by_user_id=invited_by_user_id,
                operator_service_id=operator_service_id,
                expires_at=expires_at,
                now=datetime.now(timezone.utc),
                intended_user_id=intended_user_id,
            )
        except Exception:
            raise ConnectedRuntimeError("connected_invitation_failed") from None
        return {
            "status": "ok",
            "invitation_id": invitation.invitation_id,
            "workspace_id": invitation.workspace_id,
            "role": invitation.role,
        }

    def lookup_user(
        self,
        *,
        email: str,
        workspace_id: str,
        operator_service_id: str,
    ) -> dict[str, Any]:
        self._require_stateful_oauth()
        try:
            return self._operator_directory().lookup_user(
                email=email,
                workspace_id=workspace_id,
                operator_service_id=operator_service_id,
            )
        except OperatorDirectoryError as error:
            raise ConnectedRuntimeError(error.code) from None

    def list_users(
        self,
        *,
        workspace_id: str,
        operator_service_id: str,
    ) -> dict[str, Any]:
        self._require_stateful_oauth()
        try:
            return self._operator_directory().list_users(
                workspace_id=workspace_id,
                operator_service_id=operator_service_id,
            )
        except OperatorDirectoryError as error:
            raise ConnectedRuntimeError(error.code) from None

    def remove_workspace_member(
        self,
        *,
        user_id: str,
        workspace_id: str,
        operator_service_id: str,
    ) -> dict[str, Any]:
        self._require_stateful_oauth()
        try:
            return self._operator_directory().remove_workspace_member(
                user_id=user_id,
                workspace_id=workspace_id,
                operator_service_id=operator_service_id,
            )
        except OperatorDirectoryError as error:
            raise ConnectedRuntimeError(error.code) from None

    def restore_workspace_member(
        self,
        *,
        user_id: str,
        workspace_id: str,
        operator_service_id: str,
    ) -> dict[str, Any]:
        self._require_stateful_oauth()
        try:
            return self._operator_directory().restore_workspace_member(
                user_id=user_id,
                workspace_id=workspace_id,
                operator_service_id=operator_service_id,
            )
        except OperatorDirectoryError as error:
            raise ConnectedRuntimeError(error.code) from None

    def lookup_token_session(
        self,
        *,
        user_id: str,
        workspace_id: str,
        operator_service_id: str,
    ) -> dict[str, Any]:
        self._require_stateful_oauth()
        try:
            return self._operator_directory().lookup_token_session(
                user_id=user_id,
                workspace_id=workspace_id,
                operator_service_id=operator_service_id,
            )
        except OperatorDirectoryError as error:
            raise ConnectedRuntimeError(error.code) from None

    def list_token_sessions(
        self,
        *,
        user_id: str,
        workspace_id: str,
        operator_service_id: str,
    ) -> dict[str, Any]:
        self._require_stateful_oauth()
        try:
            return self._operator_directory().list_token_sessions(
                user_id=user_id,
                workspace_id=workspace_id,
                operator_service_id=operator_service_id,
            )
        except OperatorDirectoryError as error:
            raise ConnectedRuntimeError(error.code) from None

    def export_issue20_live_audit(
        self,
        *,
        workspace_id: str,
        started_at: datetime,
        ended_at: datetime,
        operator_service_id: str,
        output_path: Path,
    ) -> dict[str, Any]:
        try:
            self._require_stateful_oauth()
            expected_operator = self.config.owner_bootstrap_operator_service_id
            if (
                not isinstance(expected_operator, str)
                or not _SAFE_IDENTIFIER.fullmatch(expected_operator)
                or not isinstance(operator_service_id, str)
                or not _SAFE_IDENTIFIER.fullmatch(operator_service_id)
                or not hmac.compare_digest(expected_operator, operator_service_id)
                or not isinstance(workspace_id, str)
                or not _SAFE_IDENTIFIER.fullmatch(workspace_id)
                or not isinstance(started_at, datetime)
                or started_at.tzinfo is None
                or started_at.utcoffset() is None
                or not isinstance(ended_at, datetime)
                or ended_at.tzinfo is None
                or ended_at.utcoffset() is None
                or ended_at <= started_at
            ):
                raise ValueError("invalid Issue #20 audit export request")
            resolved_output = _validate_issue20_audit_output_path(output_path)
            with self.repository.transaction() as unit:
                rows = self.repository.list_issue20_live_audit_rows(
                    started_at=started_at,
                    ended_at=ended_at,
                    actions=_ISSUE20_AUDIT_ACTIONS,
                    row_limit=_ISSUE20_AUDIT_ROW_LIMIT,
                )
                records = _build_issue20_audit_records(
                    rows,
                    workspace_id=workspace_id,
                    oauth_client_id=self.config.oauth.chatgpt_client_id,
                    operator_service_id=operator_service_id,
                    started_at=started_at,
                    ended_at=ended_at,
                )
                unit.commit()
            manifest_hash = sha256_json(
                {
                    "binding_type": "issue20_live_chatgpt_google_audit_lineage_v1",
                    "audit_records": records,
                }
            )
            _write_issue20_audit_artifact(
                resolved_output,
                {
                    "artifact_type": "issue20_live_audit_manifest",
                    "schema_version": 1,
                    "status": "passed",
                    "audit_record_count": len(records),
                    "audit_manifest_hash": manifest_hash,
                    "audit_records": records,
                },
            )
            return {
                "status": "ok",
                "audit_record_count": len(records),
                "audit_manifest_hash": manifest_hash,
            }
        except Exception:
            raise ConnectedRuntimeError(_ISSUE20_AUDIT_EXPORT_ERROR) from None

    def _operator_directory(self) -> OperatorDirectory:
        return OperatorDirectory(
            repository=self.repository,
            expected_operator_service_id=self.config.owner_bootstrap_operator_service_id,
        )

    def revoke_token_session(
        self,
        *,
        token_session_id: str,
        reason_code: str,
        operator_service_id: str,
    ) -> dict[str, Any]:
        self._require_stateful_oauth()
        try:
            self.bridge.revoke_token_session_as_operator(
                token_session_id,
                operator_service_id=operator_service_id,
                reason_code=reason_code,
                now=datetime.now(timezone.utc),
            )
        except Exception:
            raise ConnectedRuntimeError("connected_token_revocation_failed") from None
        return {"status": "ok", "token_session_revoked": True}

    async def serve(self) -> None:
        try:
            try:
                preflight = await self.preflight()
            except Exception:
                raise ConnectedRuntimeError("connected_preflight_failed") from None
            preflight_status = preflight.get("status")
            discovery_start = (
                self.config.oauth.chatgpt_callback_mode == "discovery_only"
                and preflight_status == "discovery_only"
            )
            if preflight_status != "ready" and not discovery_start:
                raise ConnectedRuntimeError("connected_preflight_failed")
            import uvicorn

            server_config = uvicorn.Config(
                self.application.app,
                host=self.config.host,
                port=self.config.port,
                log_level=self.config.log_level,
                access_log=False,
                proxy_headers=False,
                lifespan="on",
            )
            server = uvicorn.Server(server_config)
            await server.serve()
        finally:
            await self.aclose()


def _build_runtime_semantic_gateway(config: ConnectedRuntimeConfig) -> SemanticMcpGateway:
    upload_session_store = UploadSessionStore(config.data_dir)
    audit_store = FileAuditLogStore(config.data_dir)

    def expires_at_provider() -> str:
        return (
            datetime.now(timezone.utc) + timedelta(seconds=config.upload_session_lifetime_seconds)
        ).isoformat()

    return SemanticMcpGateway(
        upload_session_handler=build_mail_upload_session_handler(
            upload_session_store=upload_session_store,
            audit_store=audit_store,
            expires_at_provider=expires_at_provider,
        )
    )


def _runtime_data_stores_ready(data_dir: Path) -> bool:
    probe_directories = (
        data_dir / "ingestion" / "upload-sessions",
        data_dir / "audit" / "logs",
    )
    for directory in probe_directories:
        probe_path = directory / f".formowl-ready-{secrets.token_hex(16)}"
        descriptor: int | None = None
        probe_failed = False
        try:
            if not directory.is_dir():
                probe_failed = True
            else:
                descriptor = os.open(
                    probe_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.write(descriptor, b"ready")
                os.fsync(descriptor)
        except OSError:
            probe_failed = True
        finally:
            descriptor_close_failed = False
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    descriptor_close_failed = True
            cleanup_failed = False
            for _attempt in range(2):
                try:
                    probe_path.unlink(missing_ok=True)
                except OSError:
                    cleanup_failed = True
                    continue
                break
        # Any probe, descriptor-close, or cleanup fault keeps readiness
        # fail-closed, while one unlink retry removes a transiently retained probe.
        if probe_failed or descriptor_close_failed or cleanup_failed:
            return False
    return True


def _repository_schema_ready(repository: PostgreSQLOAuthRepository) -> bool:
    connection = getattr(repository, "connection", None)
    query_one = getattr(connection, "query_one", None)
    if not callable(query_one):
        return False
    try:
        for table_name in _REQUIRED_OAUTH_TABLES:
            row = query_one(
                SQLStatement(
                    sql="SELECT to_regclass(%(table_name)s) AS relation",
                    parameters={"table_name": table_name},
                )
            )
            if not isinstance(row, Mapping) or row.get("relation") is None:
                return False
        for table_name, column_names in _REQUIRED_SCHEMA_COLUMNS.items():
            for column_name in column_names:
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
                if not isinstance(row, Mapping) or row.get("column_name") != column_name:
                    return False
        for (
            table_name,
            constraint_type,
            constraint_name,
            constraint_pattern,
        ) in _REQUIRED_SCHEMA_CONSTRAINTS:
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
            if not isinstance(row, Mapping) or not row.get("constraint_name"):
                return False
        for relation_name in _REQUIRED_SCHEMA_INDEXES:
            row = query_one(
                SQLStatement(
                    sql="SELECT to_regclass(%(relation_name)s) AS relation",
                    parameters={"relation_name": relation_name},
                )
            )
            if not isinstance(row, Mapping) or row.get("relation") is None:
                return False
    except Exception:
        return False
    return True


async def _healthz_endpoint(request: Request) -> JSONResponse:
    runtime = getattr(request.app.state, "connected_runtime", None)
    healthy = isinstance(runtime, ConnectedRuntime) and runtime._running and not runtime._closed
    return JSONResponse(
        {"status": "ok" if healthy else "unavailable"},
        status_code=200 if healthy else 503,
        headers=_NO_STORE_HEADERS,
    )


async def _readyz_endpoint(request: Request) -> JSONResponse:
    runtime = getattr(request.app.state, "connected_runtime", None)
    if not isinstance(runtime, ConnectedRuntime):
        payload = {"status": "not_ready", "checks": {"runtime": False}}
        return JSONResponse(payload, status_code=503, headers=_NO_STORE_HEADERS)
    payload = await runtime.readiness(require_running=True)
    return JSONResponse(
        payload,
        status_code=200 if payload["status"] == "ready" else 503,
        headers=_NO_STORE_HEADERS,
    )


def _validate_issue20_audit_output_path(output_path: Path) -> Path:
    if not isinstance(output_path, Path) or not output_path.is_absolute() or output_path.name == "":
        raise ValueError("invalid audit output")
    parent = output_path.parent
    if parent.resolve(strict=True) != parent:
        raise ValueError("invalid audit output")
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(parent, flags)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise ValueError("invalid audit output")
        try:
            existing = os.stat(output_path.name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode)
            or existing.st_uid != os.getuid()
            or stat.S_IMODE(existing.st_mode) & 0o077
        ):
            raise ValueError("invalid audit output")
    finally:
        os.close(descriptor)
    return output_path


def _write_issue20_audit_artifact(output_path: Path, artifact: Mapping[str, Any]) -> None:
    payload = (
        json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    parent = output_path.parent
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    parent_descriptor = os.open(parent, flags)
    temporary_name = f".{output_path.name}.tmp-{secrets.token_hex(16)}"
    temporary_descriptor: int | None = None
    try:
        parent_metadata = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != os.getuid()
            or stat.S_IMODE(parent_metadata.st_mode) & 0o077
        ):
            raise ValueError("invalid audit output")
        try:
            existing = os.stat(
                output_path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode)
            or existing.st_uid != os.getuid()
            or stat.S_IMODE(existing.st_mode) & 0o077
        ):
            raise ValueError("invalid audit output")
        create_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            create_flags |= os.O_NOFOLLOW
        temporary_descriptor = os.open(
            temporary_name,
            create_flags,
            0o600,
            dir_fd=parent_descriptor,
        )
        os.fchmod(temporary_descriptor, 0o600)
        offset = 0
        while offset < len(payload):
            written = os.write(temporary_descriptor, payload[offset:])
            if written <= 0:
                raise OSError("audit artifact write failed")
            offset += written
        os.fsync(temporary_descriptor)
        os.close(temporary_descriptor)
        temporary_descriptor = None
        os.replace(
            temporary_name,
            output_path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
    finally:
        if temporary_descriptor is not None:
            try:
                os.close(temporary_descriptor)
            except OSError:
                pass
        try:
            os.unlink(temporary_name, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass
        os.close(parent_descriptor)


def _build_issue20_audit_records(
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    workspace_id: str,
    oauth_client_id: str,
    operator_service_id: str,
    started_at: datetime,
    ended_at: datetime,
) -> list[dict[str, Any]]:
    rows = _normalize_issue20_audit_rows(
        raw_rows,
        started_at=started_at,
        ended_at=ended_at,
    )
    if len(rows) >= _ISSUE20_AUDIT_ROW_LIMIT:
        raise ValueError("audit window is not bounded")

    starts = _issue20_action_rows(rows, "oauth_authorization_started")
    if len(starts) != 6 or any(
        _issue20_row_time(starts[index]) >= _issue20_row_time(starts[index + 1])
        for index in range(5)
    ):
        raise ValueError("authorization lineage is ambiguous")
    for row in starts:
        _require_issue20_row(
            row,
            action="oauth_authorization_started",
            status="ok",
            reason_code="authorization_started",
            actor_type="external_unauthenticated",
            metadata_keys={"event_stage", "provider", "scopes"},
            metadata_values={"event_stage": "authorization", "provider": "google"},
        )
        if (
            row["target_type"] != "oauth_transaction"
            or row["target_id"] != row["session_id"]
            or row["oauth_client_id"] != oauth_client_id
            or any(
                row[field] is not None
                for field in (
                    "actor_user_id",
                    "actor_service_id",
                    "workspace_id",
                    "external_identity_id",
                    "oauth_token_session_id",
                    "request_id",
                    "tool_call_id",
                )
            )
        ):
            raise ValueError("authorization lineage is invalid")
        _require_issue20_scopes(row["metadata"].get("scopes"))

    bootstrap = _issue20_one(
        _issue20_action_rows(rows, "oauth_owner_bootstrap_created"),
    )
    _require_issue20_service_row(
        bootstrap,
        operator_service_id=operator_service_id,
        action="oauth_owner_bootstrap_created",
        status="ok",
        reason_code="owner_bootstrap_created",
        metadata_keys={"event_stage"},
        metadata_values={"event_stage": "owner_bootstrap"},
    )
    if (
        bootstrap["target_type"] != "oauth_owner_bootstrap"
        or bootstrap["workspace_id"] != workspace_id
        or bootstrap["target_id"] != bootstrap["session_id"]
    ):
        raise ValueError("owner bootstrap lineage is invalid")

    invitation_rows = _issue20_action_rows(rows, "oauth_invitation_create")
    invitation_created = _issue20_one(
        [row for row in invitation_rows if row["reason_code"] == "invitation_created"]
    )
    owner_only_denied = _issue20_one(
        [row for row in invitation_rows if row["reason_code"] == "invitation_owner_required"]
    )
    if len(invitation_rows) != 2:
        raise ValueError("invitation audit lineage is ambiguous")
    for row, status in ((invitation_created, "ok"), (owner_only_denied, "denied")):
        _require_issue20_service_row(
            row,
            operator_service_id=operator_service_id,
            action="oauth_invitation_create",
            status=status,
            reason_code=str(row["reason_code"]),
            metadata_keys={"event_stage", "lineage_source", "approval_user_id"},
            metadata_values={
                "event_stage": "invitation",
                "lineage_source": "owner_approval",
            },
        )
        if row["workspace_id"] != workspace_id:
            raise ValueError("invitation workspace lineage is invalid")
    if (
        invitation_created["target_type"] != "oauth_invitation"
        or invitation_created["target_id"] != invitation_created["session_id"]
        or owner_only_denied["target_type"] != "workspace"
        or owner_only_denied["target_id"] != workspace_id
        or owner_only_denied["session_id"] != workspace_id
    ):
        raise ValueError("invitation target lineage is invalid")

    removals = _issue20_action_rows(rows, "operator_workspace_member_remove")
    restores = _issue20_action_rows(rows, "operator_workspace_member_restore")
    revocations = _issue20_action_rows(rows, "oauth_token_session_revoked")
    removal = _issue20_one(removals)
    restore = _issue20_one(restores)
    revocation = _issue20_one(revocations)
    _require_issue20_operator_membership_row(
        removal,
        operator_service_id=operator_service_id,
        action="operator_workspace_member_remove",
        expected_state="removed",
    )
    _require_issue20_operator_membership_row(
        restore,
        operator_service_id=operator_service_id,
        action="operator_workspace_member_restore",
        expected_state="active",
    )
    _require_issue20_service_row(
        revocation,
        operator_service_id=operator_service_id,
        action="oauth_token_session_revoked",
        status="ok",
        reason_code=str(revocation["reason_code"]),
        metadata_keys={"event_stage", "token_session_status"},
        metadata_values={"event_stage": "revocation", "token_session_status": "revoked"},
    )

    owner_created = _issue20_callback_row(
        rows,
        starts[0],
        "oauth_external_identity_created",
    )
    owner_accepted = _issue20_callback_row(rows, starts[0], "oauth_invitation_accepted")
    owner_google = _issue20_callback_row(rows, starts[0], "google_authentication_succeeded")
    owner_code = _issue20_callback_row(rows, starts[0], "oauth_authorization_code_issued")
    member_created = _issue20_callback_row(
        rows,
        starts[1],
        "oauth_external_identity_created",
    )
    member_accepted = _issue20_callback_row(rows, starts[1], "oauth_invitation_accepted")
    member_google = _issue20_callback_row(rows, starts[1], "google_authentication_succeeded")
    member_code = _issue20_callback_row(rows, starts[1], "oauth_authorization_code_issued")

    owner_user_id, owner_identity_id = _validate_issue20_initial_callback(
        created=owner_created,
        accepted=owner_accepted,
        google=owner_google,
        code=owner_code,
        transaction=starts[0],
        workspace_id=workspace_id,
        oauth_client_id=oauth_client_id,
        role="owner",
        invitation_id=bootstrap["target_id"],
    )
    member_user_id, member_identity_id = _validate_issue20_initial_callback(
        created=member_created,
        accepted=member_accepted,
        google=member_google,
        code=member_code,
        transaction=starts[1],
        workspace_id=workspace_id,
        oauth_client_id=oauth_client_id,
        role="member",
        invitation_id=invitation_created["target_id"],
    )
    if owner_user_id == member_user_id or owner_identity_id == member_identity_id:
        raise ValueError("distinct identity lineage is required")
    if (
        invitation_created["metadata"]["approval_user_id"] != owner_user_id
        or owner_only_denied["metadata"]["approval_user_id"] != member_user_id
    ):
        raise ValueError("invitation approval lineage is invalid")

    removed_callback_denied = _issue20_one(
        [
            row
            for row in _issue20_action_rows(rows, "google_authentication_failed")
            if _issue20_between(row, starts[2], restore)
        ]
    )
    _require_issue20_row(
        removed_callback_denied,
        action="google_authentication_failed",
        status="permission_denied",
        reason_code="workspace_membership_inactive",
        actor_type="external_unauthenticated",
        metadata_keys={"event_stage"},
        metadata_values={"event_stage": "google_callback"},
    )
    if removed_callback_denied["oauth_client_id"] != oauth_client_id or any(
        removed_callback_denied[field] is not None
        for field in (
            "actor_user_id",
            "actor_service_id",
            "workspace_id",
            "external_identity_id",
            "oauth_token_session_id",
            "request_id",
            "tool_call_id",
        )
    ):
        raise ValueError("removed callback denial lineage is invalid")

    restore_google, restore_resolved, restore_code = _validate_issue20_relink_callback(
        rows,
        transaction=starts[3],
        user_id=member_user_id,
        external_identity_id=member_identity_id,
        workspace_id=workspace_id,
        oauth_client_id=oauth_client_id,
    )
    post_revocation_google, post_revocation_resolved, post_revocation_code = (
        _validate_issue20_relink_callback(
            rows,
            transaction=starts[4],
            user_id=member_user_id,
            external_identity_id=member_identity_id,
            workspace_id=workspace_id,
            oauth_client_id=oauth_client_id,
        )
    )
    post_expiry_google, post_expiry_resolved, post_expiry_code = _validate_issue20_relink_callback(
        rows,
        transaction=starts[5],
        user_id=member_user_id,
        external_identity_id=member_identity_id,
        workspace_id=workspace_id,
        oauth_client_id=oauth_client_id,
    )

    token_rows = _issue20_action_rows(rows, "oauth_token_session_issued")
    if len(token_rows) != 5:
        raise ValueError("token-session lineage is ambiguous")
    owner_token = _issue20_window_one(token_rows, owner_code, invitation_created)
    member_token = _issue20_window_one(token_rows, member_code, removal)
    restore_token = _issue20_window_one(token_rows, restore_code, revocation)
    post_revocation_token = _issue20_window_one(
        token_rows,
        post_revocation_code,
        starts[5],
    )
    post_expiry_token = _issue20_window_one(token_rows, post_expiry_code, None)
    _validate_issue20_token_row(
        owner_token,
        user_id=owner_user_id,
        external_identity_id=owner_identity_id,
        workspace_id=workspace_id,
        oauth_client_id=oauth_client_id,
        role="owner",
    )
    for token_row in (
        member_token,
        restore_token,
        post_revocation_token,
        post_expiry_token,
    ):
        _validate_issue20_token_row(
            token_row,
            user_id=member_user_id,
            external_identity_id=member_identity_id,
            workspace_id=workspace_id,
            oauth_client_id=oauth_client_id,
            role="member",
        )
    token_session_ids = {
        str(row["oauth_token_session_id"])
        for row in (
            owner_token,
            member_token,
            restore_token,
            post_revocation_token,
            post_expiry_token,
        )
    }
    if len(token_session_ids) != 5:
        raise ValueError("token-session identifiers are not distinct")

    allowed_rows = _issue20_action_rows(rows, "mcp_authorization_allowed")
    if len(allowed_rows) != 6:
        raise ValueError("allowed tool lineage is ambiguous")
    owner_whoami = _issue20_tool_window_one(
        allowed_rows,
        token_row=owner_token,
        tool_name="whoami",
        ended_by=invitation_created,
    )
    owner_upload = _issue20_tool_window_one(
        allowed_rows,
        token_row=owner_token,
        tool_name="open_upload_session",
        ended_by=invitation_created,
    )
    member_whoami = _issue20_tool_window_one(
        allowed_rows,
        token_row=member_token,
        tool_name="whoami",
        ended_by=owner_only_denied,
    )
    restore_whoami = _issue20_tool_window_one(
        allowed_rows,
        token_row=restore_token,
        tool_name="whoami",
        ended_by=revocation,
    )
    post_revocation_whoami = _issue20_tool_window_one(
        allowed_rows,
        token_row=post_revocation_token,
        tool_name="whoami",
        ended_by=None,
    )
    post_expiry_whoami = _issue20_tool_window_one(
        allowed_rows,
        token_row=post_expiry_token,
        tool_name="whoami",
        ended_by=None,
    )
    for row, user_id, identity_id, token_row in (
        (owner_whoami, owner_user_id, owner_identity_id, owner_token),
        (owner_upload, owner_user_id, owner_identity_id, owner_token),
        (member_whoami, member_user_id, member_identity_id, member_token),
        (restore_whoami, member_user_id, member_identity_id, restore_token),
        (
            post_revocation_whoami,
            member_user_id,
            member_identity_id,
            post_revocation_token,
        ),
        (post_expiry_whoami, member_user_id, member_identity_id, post_expiry_token),
    ):
        _validate_issue20_tool_row(
            row,
            user_id=user_id,
            external_identity_id=identity_id,
            workspace_id=workspace_id,
            oauth_client_id=oauth_client_id,
            token_session_id=str(token_row["oauth_token_session_id"]),
            allowed=True,
        )

    invalid_argument_denials = _issue20_action_rows(rows, "mcp_authorization_denied")
    if len(invalid_argument_denials) != 2:
        raise ValueError("argument-denial lineage is ambiguous")
    invalid_argument_denials.sort(key=_issue20_row_sort_key)
    if _issue20_row_time(invalid_argument_denials[0]) == _issue20_row_time(
        invalid_argument_denials[1]
    ):
        raise ValueError("argument-denial order is ambiguous")
    for row in invalid_argument_denials:
        _validate_issue20_tool_row(
            row,
            user_id=member_user_id,
            external_identity_id=member_identity_id,
            workspace_id=workspace_id,
            oauth_client_id=oauth_client_id,
            token_session_id=str(member_token["oauth_token_session_id"]),
            allowed=False,
        )
        if row["reason_code"] != "invalid_tool_arguments" or not _issue20_between(
            row, member_whoami, removal
        ):
            raise ValueError("argument-denial lineage is invalid")

    membership_target = f"{workspace_id}:{member_user_id}"
    if (
        removal["target_id"] != membership_target
        or restore["target_id"] != membership_target
        or removal["target_type"] != "workspace_member"
        or restore["target_type"] != "workspace_member"
    ):
        raise ValueError("membership target lineage is invalid")
    if (
        revocation["workspace_id"] != workspace_id
        or revocation["target_type"] != "oauth_token_session"
        or revocation["target_id"] != restore_token["oauth_token_session_id"]
        or revocation["session_id"] != restore_token["oauth_token_session_id"]
        or revocation["oauth_token_session_id"] != restore_token["oauth_token_session_id"]
        or revocation["external_identity_id"] != member_identity_id
        or revocation["oauth_client_id"] != oauth_client_id
    ):
        raise ValueError("revocation lineage is invalid")

    http_denials = _issue20_action_rows(rows, "mcp_http_authentication_denied")
    removed_denials = sorted(
        [
            row
            for row in http_denials
            if row["reason_code"] == "workspace_membership_inactive"
            and row["oauth_token_session_id"] == member_token["oauth_token_session_id"]
            and _issue20_between(row, removal, starts[2])
        ],
        key=_issue20_row_sort_key,
    )
    if len(removed_denials) != 2 or _issue20_row_time(removed_denials[0]) == _issue20_row_time(
        removed_denials[1]
    ):
        raise ValueError("removed-session denial lineage is ambiguous")
    revoked_denial = _issue20_one(
        [
            row
            for row in http_denials
            if row["reason_code"] == "token_session_revoked"
            and row["oauth_token_session_id"] == restore_token["oauth_token_session_id"]
            and _issue20_between(row, revocation, starts[4])
        ]
    )
    expired_denial = _issue20_one(
        [
            row
            for row in http_denials
            if row["reason_code"] == "token_session_expired"
            and row["oauth_token_session_id"] == post_revocation_token["oauth_token_session_id"]
            and _issue20_between(row, post_revocation_whoami, starts[5])
        ]
    )
    selected_http_denials = {*map(id, removed_denials), id(revoked_denial), id(expired_denial)}
    extras = [row for row in http_denials if id(row) not in selected_http_denials]
    if len(extras) > 1:
        raise ValueError("unexpected HTTP denial lineage")
    if extras and not (
        extras[0]["reason_code"] == "workspace_membership_inactive"
        and extras[0]["oauth_token_session_id"] == member_token["oauth_token_session_id"]
        and _issue20_between(extras[0], restore_whoami, revocation)
    ):
        raise ValueError("unexpected HTTP denial lineage")
    for row, token_row in (
        (removed_denials[0], member_token),
        (removed_denials[1], member_token),
        (revoked_denial, restore_token),
        (expired_denial, post_revocation_token),
    ):
        _validate_issue20_http_denial(
            row,
            user_id=member_user_id,
            external_identity_id=member_identity_id,
            workspace_id=workspace_id,
            oauth_client_id=oauth_client_id,
            token_session_id=str(token_row["oauth_token_session_id"]),
        )

    selected = [
        ("owner_bootstrap_created_service", bootstrap),
        ("owner_oauth_authorization_started", starts[0]),
        ("owner_google_authentication_succeeded", owner_google),
        ("owner_external_identity_created", owner_created),
        ("owner_invitation_accepted", owner_accepted),
        ("owner_authorization_code_issued", owner_code),
        ("owner_token_session_issued", owner_token),
        ("owner_whoami_allowed", owner_whoami),
        ("owner_upload_session_allowed", owner_upload),
        ("second_user_invitation_created_service", invitation_created),
        ("second_user_oauth_authorization_started", starts[1]),
        ("second_user_google_authentication_succeeded", member_google),
        ("second_user_external_identity_created", member_created),
        ("second_user_invitation_accepted", member_accepted),
        ("second_user_authorization_code_issued", member_code),
        ("second_user_token_session_issued", member_token),
        ("second_user_whoami_allowed", member_whoami),
        ("second_user_owner_only_denied", owner_only_denied),
        ("second_user_cross_workspace_denied", invalid_argument_denials[0]),
        ("forged_identity_denied", invalid_argument_denials[1]),
        ("second_user_membership_removed_service", removal),
        ("removed_old_token_denied", removed_denials[0]),
        ("restart_removed_old_token_denied", removed_denials[1]),
        ("removed_relink_oauth_authorization_started", starts[2]),
        ("removed_relink_google_callback_denied", removed_callback_denied),
        ("second_user_membership_restored_service", restore),
        ("restore_relink_oauth_authorization_started", starts[3]),
        ("restore_relink_google_authentication_succeeded", restore_google),
        ("restore_relink_external_identity_resolved", restore_resolved),
        ("restore_relink_authorization_code_issued", restore_code),
        ("restore_relink_token_session_issued", restore_token),
        ("restore_relink_whoami_allowed", restore_whoami),
        ("restored_session_revoked_service", revocation),
        ("revoked_token_denied", revoked_denial),
        ("post_revocation_relink_oauth_authorization_started", starts[4]),
        ("post_revocation_relink_google_authentication_succeeded", post_revocation_google),
        ("post_revocation_relink_external_identity_resolved", post_revocation_resolved),
        ("post_revocation_relink_authorization_code_issued", post_revocation_code),
        ("post_revocation_relink_token_session_issued", post_revocation_token),
        ("post_revocation_relink_whoami_allowed", post_revocation_whoami),
        ("expired_token_denied", expired_denial),
        ("post_expiry_relink_oauth_authorization_started", starts[5]),
        ("post_expiry_relink_google_authentication_succeeded", post_expiry_google),
        ("post_expiry_relink_external_identity_resolved", post_expiry_resolved),
        ("post_expiry_relink_authorization_code_issued", post_expiry_code),
        ("post_expiry_relink_token_session_issued", post_expiry_token),
        ("post_expiry_relink_whoami_allowed", post_expiry_whoami),
    ]
    if tuple(name for name, _row in selected) != _ISSUE20_AUDIT_LINEAGE:
        raise ValueError("audit lineage is invalid")
    if len({str(row["audit_log_id"]) for _name, row in selected}) != 47:
        raise ValueError("audit rows are not distinct")
    selected_audit_ids = {str(row["audit_log_id"]) for _name, row in selected}
    allowed_ignored_audit_ids = {str(row["audit_log_id"]) for row in extras}
    if {
        str(row["audit_log_id"])
        for row in rows
        if str(row["audit_log_id"]) not in selected_audit_ids
    } != allowed_ignored_audit_ids:
        raise ValueError("audit window contains ambiguous rows")
    event_times = [_issue20_row_time(row) for _name, row in selected]
    if any(event_times[index] > event_times[index + 1] for index in range(46)):
        raise ValueError("audit lineage chronology is invalid")

    records: list[dict[str, Any]] = []
    previous_hash = _ISSUE20_ABSENT_VALUE_COMMITMENT
    for sequence_index, (event_name, row) in enumerate(selected, start=1):
        record = _project_issue20_audit_record(
            row,
            sequence_index=sequence_index,
            event_name=event_name,
            previous_hash=previous_hash,
        )
        records.append(record)
        previous_hash = str(record["audit_record_hash"])
    if (
        len(records) != 47
        or len({str(record["audit_record_hash"]) for record in records}) != 47
        or any(set(record) != set(_ISSUE20_AUDIT_LINEAGE_FIELDS) for record in records)
    ):
        raise ValueError("audit manifest is invalid")
    return records


def _normalize_issue20_audit_rows(
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    started_at: datetime,
    ended_at: datetime,
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise ValueError("audit rows are invalid")
    rows: list[dict[str, Any]] = []
    audit_ids: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping) or set(raw) != _ISSUE20_RAW_AUDIT_FIELDS:
            raise ValueError("audit row schema is invalid")
        row = dict(raw)
        for field_name in _ISSUE20_RAW_AUDIT_FIELDS - {"metadata", "timestamp"}:
            value = row[field_name]
            if value is not None and (type(value) is not str or not value):
                raise ValueError("audit row value is invalid")
        if (
            row["action"] not in _ISSUE20_AUDIT_ACTIONS
            or not _SAFE_ERROR_CODE.fullmatch(str(row["action"]))
            or not _SAFE_ERROR_CODE.fullmatch(str(row["reason_code"]))
            or row["actor_type"] not in {"user", "service", "external_unauthenticated"}
            or type(row["metadata"]) is not dict
        ):
            raise ValueError("audit row value is invalid")
        _issue20_metadata_shape(row["metadata"])
        timestamp = _parse_timestamp(str(row["timestamp"]))
        if timestamp < started_at or timestamp > ended_at:
            raise ValueError("audit row is outside the bounded window")
        audit_log_id = str(row["audit_log_id"])
        if audit_log_id in audit_ids:
            raise ValueError("duplicate audit row")
        audit_ids.add(audit_log_id)
        rows.append(row)
    if rows != sorted(rows, key=_issue20_row_sort_key):
        raise ValueError("audit row order is invalid")
    return rows


def _issue20_action_rows(rows: Sequence[dict[str, Any]], action: str) -> list[dict[str, Any]]:
    return [row for row in rows if row["action"] == action]


def _issue20_one(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != 1:
        raise ValueError("audit row is missing or ambiguous")
    return rows[0]


def _issue20_row_time(row: Mapping[str, Any]) -> datetime:
    return _parse_timestamp(str(row["timestamp"]))


def _issue20_row_sort_key(row: Mapping[str, Any]) -> tuple[datetime, str]:
    return (_issue20_row_time(row), str(row["audit_log_id"]))


def _issue20_between(
    row: Mapping[str, Any],
    started_by: Mapping[str, Any],
    ended_by: Mapping[str, Any],
) -> bool:
    return _issue20_row_time(started_by) <= _issue20_row_time(row) <= _issue20_row_time(ended_by)


def _issue20_window_one(
    rows: Sequence[dict[str, Any]],
    started_by: Mapping[str, Any],
    ended_by: Mapping[str, Any] | None,
) -> dict[str, Any]:
    candidates = [
        row
        for row in rows
        if _issue20_row_time(row) >= _issue20_row_time(started_by)
        and (ended_by is None or _issue20_row_time(row) <= _issue20_row_time(ended_by))
    ]
    return _issue20_one(candidates)


def _issue20_callback_row(
    rows: Sequence[dict[str, Any]],
    transaction: Mapping[str, Any],
    action: str,
) -> dict[str, Any]:
    return _issue20_one(
        [
            row
            for row in rows
            if row["action"] == action and row["session_id"] == transaction["session_id"]
        ]
    )


def _require_issue20_row(
    row: Mapping[str, Any],
    *,
    action: str,
    status: str,
    reason_code: str,
    actor_type: str,
    metadata_keys: set[str],
    metadata_values: Mapping[str, Any],
) -> None:
    metadata = row["metadata"]
    if (
        row["action"] != action
        or row["status"] != status
        or row["reason_code"] != reason_code
        or row["actor_type"] != actor_type
        or set(metadata) != metadata_keys
        or any(metadata.get(key) != value for key, value in metadata_values.items())
    ):
        raise ValueError("audit row semantics are invalid")


def _require_issue20_service_row(
    row: Mapping[str, Any],
    *,
    operator_service_id: str,
    action: str,
    status: str,
    reason_code: str,
    metadata_keys: set[str],
    metadata_values: Mapping[str, Any],
) -> None:
    _require_issue20_row(
        row,
        action=action,
        status=status,
        reason_code=reason_code,
        actor_type="service",
        metadata_keys=metadata_keys,
        metadata_values=metadata_values,
    )
    if row["actor_user_id"] is not None or row["actor_service_id"] != operator_service_id:
        raise ValueError("service audit attribution is invalid")


def _require_issue20_operator_membership_row(
    row: Mapping[str, Any],
    *,
    operator_service_id: str,
    action: str,
    expected_state: str,
) -> None:
    expected_keys = {"event_stage", "operation", "membership_role", "membership_state"}
    if action == "operator_workspace_member_remove":
        expected_keys.add("revoked_token_session_count")
    _require_issue20_service_row(
        row,
        operator_service_id=operator_service_id,
        action=action,
        status="ok",
        reason_code="operator_directory_allowed",
        metadata_keys=expected_keys,
        metadata_values={
            "event_stage": "operator_directory",
            "operation": action,
            "membership_role": "member",
            "membership_state": expected_state,
        },
    )
    if (
        row["workspace_id"] is not None
        or row["external_identity_id"] is not None
        or row["oauth_client_id"] is not None
        or row["oauth_token_session_id"] is not None
        or row["request_id"] is not None
        or row["tool_call_id"] is not None
    ):
        raise ValueError("membership audit lineage is invalid")
    if action == "operator_workspace_member_remove":
        count = row["metadata"].get("revoked_token_session_count")
        if isinstance(count, bool) or not isinstance(count, int) or count != 1:
            raise ValueError("membership revocation count is invalid")


def _validate_issue20_initial_callback(
    *,
    created: Mapping[str, Any],
    accepted: Mapping[str, Any],
    google: Mapping[str, Any],
    code: Mapping[str, Any],
    transaction: Mapping[str, Any],
    workspace_id: str,
    oauth_client_id: str,
    role: str,
    invitation_id: str,
) -> tuple[str, str]:
    user_id = str(created["actor_user_id"])
    identity_id = str(created["external_identity_id"])
    if not user_id or not identity_id:
        raise ValueError("identity lineage is missing")
    for row, action, reason, keys, values in (
        (
            created,
            "oauth_external_identity_created",
            "external_identity_created",
            {"event_stage", "identity_status"},
            {"event_stage": "identity_mapping", "identity_status": "created"},
        ),
        (
            accepted,
            "oauth_invitation_accepted",
            "invitation_accepted",
            {"event_stage", "provider", "membership_role"},
            {"event_stage": "first_login", "provider": "google", "membership_role": role},
        ),
        (
            google,
            "google_authentication_succeeded",
            "google_authentication_succeeded",
            {"event_stage", "provider"},
            {"event_stage": "google_callback", "provider": "google"},
        ),
        (
            code,
            "oauth_authorization_code_issued",
            "authorization_code_issued",
            {"event_stage", "provider"},
            {"event_stage": "google_callback", "provider": "google"},
        ),
    ):
        _require_issue20_row(
            row,
            action=action,
            status="ok",
            reason_code=reason,
            actor_type="user",
            metadata_keys=keys,
            metadata_values=values,
        )
        if (
            row["actor_user_id"] != user_id
            or row["actor_service_id"] is not None
            or row["workspace_id"] != workspace_id
            or row["external_identity_id"] != identity_id
            or row["oauth_client_id"] != oauth_client_id
            or row["session_id"] != transaction["session_id"]
            or row["oauth_token_session_id"] is not None
            or row["request_id"] is not None
            or row["tool_call_id"] is not None
        ):
            raise ValueError("identity callback lineage is invalid")
    if (
        created["target_type"] != "external_identity"
        or created["target_id"] != identity_id
        or google["target_type"] != "external_identity"
        or google["target_id"] != identity_id
        or accepted["target_type"] != "oauth_invitation"
        or accepted["target_id"] != invitation_id
        or code["target_type"] != "oauth_authorization_code"
        or code["target_id"] != transaction["session_id"]
    ):
        raise ValueError("identity callback targets are invalid")
    return user_id, identity_id


def _validate_issue20_relink_callback(
    rows: Sequence[dict[str, Any]],
    *,
    transaction: Mapping[str, Any],
    user_id: str,
    external_identity_id: str,
    workspace_id: str,
    oauth_client_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    google = _issue20_callback_row(rows, transaction, "google_authentication_succeeded")
    resolved = _issue20_callback_row(rows, transaction, "oauth_external_identity_resolved")
    code = _issue20_callback_row(rows, transaction, "oauth_authorization_code_issued")
    for row, action, reason, keys, values in (
        (
            google,
            "google_authentication_succeeded",
            "google_authentication_succeeded",
            {"event_stage", "provider"},
            {"event_stage": "google_callback", "provider": "google"},
        ),
        (
            resolved,
            "oauth_external_identity_resolved",
            "external_identity_resolved",
            {"event_stage", "identity_status"},
            {"event_stage": "identity_mapping", "identity_status": "resolved"},
        ),
        (
            code,
            "oauth_authorization_code_issued",
            "authorization_code_issued",
            {"event_stage", "provider"},
            {"event_stage": "google_callback", "provider": "google"},
        ),
    ):
        _require_issue20_row(
            row,
            action=action,
            status="ok",
            reason_code=reason,
            actor_type="user",
            metadata_keys=keys,
            metadata_values=values,
        )
        if (
            row["actor_user_id"] != user_id
            or row["actor_service_id"] is not None
            or row["workspace_id"] != workspace_id
            or row["external_identity_id"] != external_identity_id
            or row["oauth_client_id"] != oauth_client_id
            or row["session_id"] != transaction["session_id"]
            or row["oauth_token_session_id"] is not None
            or row["request_id"] is not None
            or row["tool_call_id"] is not None
        ):
            raise ValueError("relink callback lineage is invalid")
    if (
        google["target_type"] != "external_identity"
        or google["target_id"] != external_identity_id
        or resolved["target_type"] != "external_identity"
        or resolved["target_id"] != external_identity_id
        or code["target_type"] != "oauth_authorization_code"
        or code["target_id"] != transaction["session_id"]
    ):
        raise ValueError("relink callback targets are invalid")
    return google, resolved, code


def _validate_issue20_token_row(
    row: Mapping[str, Any],
    *,
    user_id: str,
    external_identity_id: str,
    workspace_id: str,
    oauth_client_id: str,
    role: str,
) -> None:
    _require_issue20_row(
        row,
        action="oauth_token_session_issued",
        status="ok",
        reason_code="token_session_issued",
        actor_type="user",
        metadata_keys={"event_stage", "scopes", "membership_role"},
        metadata_values={"event_stage": "token_exchange", "membership_role": role},
    )
    _require_issue20_scopes(row["metadata"].get("scopes"))
    token_session_id = row["oauth_token_session_id"]
    if (
        row["actor_user_id"] != user_id
        or row["actor_service_id"] is not None
        or row["workspace_id"] != workspace_id
        or row["external_identity_id"] != external_identity_id
        or row["oauth_client_id"] != oauth_client_id
        or not isinstance(token_session_id, str)
        or row["target_type"] != "oauth_token_session"
        or row["target_id"] != token_session_id
        or row["session_id"] != token_session_id
        or row["request_id"] is not None
        or row["tool_call_id"] is not None
    ):
        raise ValueError("token-session lineage is invalid")


def _issue20_tool_window_one(
    rows: Sequence[dict[str, Any]],
    *,
    token_row: Mapping[str, Any],
    tool_name: str,
    ended_by: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return _issue20_one(
        [
            row
            for row in rows
            if row["oauth_token_session_id"] == token_row["oauth_token_session_id"]
            and row["target_id"] == tool_name
            and _issue20_row_time(row) >= _issue20_row_time(token_row)
            and (ended_by is None or _issue20_row_time(row) <= _issue20_row_time(ended_by))
        ]
    )


def _validate_issue20_tool_row(
    row: Mapping[str, Any],
    *,
    user_id: str,
    external_identity_id: str,
    workspace_id: str,
    oauth_client_id: str,
    token_session_id: str,
    allowed: bool,
) -> None:
    _require_issue20_row(
        row,
        action="mcp_authorization_allowed" if allowed else "mcp_authorization_denied",
        status="ok" if allowed else "permission_denied",
        reason_code="tool_authorized" if allowed else "invalid_tool_arguments",
        actor_type="user",
        metadata_keys={"event_stage", "workspace_decision"},
        metadata_values={
            "event_stage": "mcp_authorization",
            "workspace_decision": "allowed" if allowed else "denied",
        },
    )
    if (
        row["actor_user_id"] != user_id
        or row["actor_service_id"] is not None
        or row["target_type"] != "mcp_tool"
        or row["workspace_id"] != workspace_id
        or row["external_identity_id"] != external_identity_id
        or row["oauth_client_id"] != oauth_client_id
        or row["oauth_token_session_id"] != token_session_id
        or row["session_id"] != token_session_id
        or not isinstance(row["request_id"], str)
        or not isinstance(row["tool_call_id"], str)
        or row["request_id"] == row["tool_call_id"]
    ):
        raise ValueError("tool authorization lineage is invalid")


def _validate_issue20_http_denial(
    row: Mapping[str, Any],
    *,
    user_id: str,
    external_identity_id: str,
    workspace_id: str,
    oauth_client_id: str,
    token_session_id: str,
) -> None:
    _require_issue20_row(
        row,
        action="mcp_http_authentication_denied",
        status="permission_denied",
        reason_code=str(row["reason_code"]),
        actor_type="user",
        metadata_keys={"event_stage", "lineage_source"},
        metadata_values={
            "event_stage": "mcp_http_authentication",
            "lineage_source": "verified_token_session",
        },
    )
    if (
        row["actor_user_id"] != user_id
        or row["actor_service_id"] is not None
        or row["target_type"] != "mcp_resource"
        or row["target_id"] != "mcp"
        or row["workspace_id"] != workspace_id
        or row["external_identity_id"] != external_identity_id
        or row["oauth_client_id"] != oauth_client_id
        or row["oauth_token_session_id"] != token_session_id
        or row["session_id"] != token_session_id
        or not isinstance(row["request_id"], str)
        or row["tool_call_id"] is not None
    ):
        raise ValueError("HTTP denial lineage is invalid")


def _require_issue20_scopes(value: Any) -> None:
    if (
        type(value) is not list
        or not value
        or any(type(item) is not str or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError("scope metadata is invalid")


def _issue20_metadata_shape(value: Any) -> Any:
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is str:
        return "str"
    if type(value) is list:
        return {"list": [_issue20_metadata_shape(item) for item in value]}
    if type(value) is dict:
        if any(
            type(key) is not str or not key or not _SAFE_ERROR_CODE.fullmatch(key) for key in value
        ):
            raise ValueError("metadata shape is invalid")
        return {
            "object": {key: _issue20_metadata_shape(item) for key, item in sorted(value.items())}
        }
    raise ValueError("metadata shape is invalid")


def _issue20_binding_hash(value: Any) -> str:
    if value is None:
        return _ISSUE20_ABSENT_VALUE_COMMITMENT
    if type(value) is not str or not value:
        raise ValueError("audit binding is invalid")
    return sha256_json(
        {
            "binding_type": "issue20_live_audit_value_binding_v1",
            "value": value,
        }
    )


def _project_issue20_audit_record(
    row: Mapping[str, Any],
    *,
    sequence_index: int,
    event_name: str,
    previous_hash: str,
) -> dict[str, Any]:
    approval_user_id = row["metadata"].get("approval_user_id")
    if approval_user_id is not None and (type(approval_user_id) is not str or not approval_user_id):
        raise ValueError("approval-user lineage is invalid")
    record: dict[str, Any] = {
        "sequence_index": sequence_index,
        "event_name": event_name,
        "action": row["action"],
        "status": "denied" if "denied" in event_name else "passed",
        "reason_code": row["reason_code"],
        "actor_type": row["actor_type"],
        "actor_user_binding_hash": _issue20_binding_hash(row["actor_user_id"]),
        "actor_service_binding_hash": _issue20_binding_hash(row["actor_service_id"]),
        "approval_user_binding_hash": _issue20_binding_hash(approval_user_id),
        "workspace_binding_hash": _issue20_binding_hash(row["workspace_id"]),
        "external_identity_binding_hash": _issue20_binding_hash(row["external_identity_id"]),
        "oauth_client_binding_hash": _issue20_binding_hash(row["oauth_client_id"]),
        "oauth_token_session_binding_hash": _issue20_binding_hash(row["oauth_token_session_id"]),
        "request_binding_hash": _issue20_binding_hash(row["request_id"]),
        "tool_call_binding_hash": _issue20_binding_hash(row["tool_call_id"]),
        "metadata_shape_hash": sha256_json(
            {
                "binding_type": "issue20_live_audit_metadata_shape_v1",
                "shape": _issue20_metadata_shape(row["metadata"]),
            }
        ),
        "previous_audit_record_hash": previous_hash,
    }
    record["audit_record_hash"] = sha256_json(
        {
            "binding_type": "issue20_live_chatgpt_google_safe_audit_record_v1",
            "record_without_audit_record_hash": {
                field: record.get(field)
                for field in _ISSUE20_AUDIT_LINEAGE_FIELDS
                if field != "audit_record_hash"
            },
        }
    )
    return record


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="formowl-connected-mcp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init-secrets")
    initialize.add_argument("--output-dir", required=True)
    initialize.add_argument("--postgres-host", default="postgres")
    initialize.add_argument("--postgres-port", type=int, default=5432)
    initialize.add_argument("--postgres-user", default="formowl")
    initialize.add_argument("--postgres-database", default="formowl")
    initialize.add_argument("--recover-partial", action="store_true")
    subparsers.add_parser("migrate")
    subparsers.add_parser("preflight")
    subparsers.add_parser("serve")
    bootstrap = subparsers.add_parser("bootstrap-owner")
    bootstrap.add_argument("--workspace-id", required=True)
    bootstrap.add_argument("--email", required=True)
    bootstrap.add_argument("--expires-at", required=True)
    bootstrap.add_argument("--idempotency-key", required=True)
    bootstrap.add_argument("--operator-service-id", required=True)
    invite = subparsers.add_parser("invite-user")
    invite.add_argument("--workspace-id", required=True)
    invite.add_argument("--email", required=True)
    invite.add_argument("--role", choices=("owner", "member", "viewer"), required=True)
    invite.add_argument("--invited-by-user-id", required=True)
    invite.add_argument("--operator-service-id", required=True)
    invite.add_argument("--intended-user-id")
    invite.add_argument("--expires-at", required=True)
    user_lookup = subparsers.add_parser("lookup-user")
    user_lookup.add_argument("--email", required=True)
    user_lookup.add_argument("--workspace-id", required=True)
    user_lookup.add_argument("--operator-service-id", required=True)
    user_list = subparsers.add_parser("list-users")
    user_list.add_argument("--workspace-id", required=True)
    user_list.add_argument("--operator-service-id", required=True)
    member_remove = subparsers.add_parser("remove-workspace-member")
    member_remove.add_argument("--user-id", required=True)
    member_remove.add_argument("--workspace-id", required=True)
    member_remove.add_argument("--operator-service-id", required=True)
    member_restore = subparsers.add_parser("restore-workspace-member")
    member_restore.add_argument("--user-id", required=True)
    member_restore.add_argument("--workspace-id", required=True)
    member_restore.add_argument("--operator-service-id", required=True)
    session_lookup = subparsers.add_parser("lookup-token-session")
    session_lookup.add_argument("--user-id", required=True)
    session_lookup.add_argument("--workspace-id", required=True)
    session_lookup.add_argument("--operator-service-id", required=True)
    session_list = subparsers.add_parser("list-token-sessions")
    session_list.add_argument("--user-id", required=True)
    session_list.add_argument("--workspace-id", required=True)
    session_list.add_argument("--operator-service-id", required=True)
    audit_export = subparsers.add_parser("export-issue20-live-audit")
    audit_export.add_argument("--workspace-id", required=True)
    audit_export.add_argument("--started-at", required=True)
    audit_export.add_argument("--ended-at", required=True)
    audit_export.add_argument("--operator-service-id", required=True)
    audit_export.add_argument("--output", type=Path, required=True)
    revoke = subparsers.add_parser("revoke-token-session")
    revoke.add_argument("--token-session-id", required=True)
    revoke.add_argument("--reason-code", required=True)
    revoke.add_argument("--operator-service-id", required=True)
    return parser


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ConnectedRuntimeError("connected_timestamp_invalid") from None
    if parsed.tzinfo is None:
        raise ConnectedRuntimeError("connected_timestamp_invalid")
    return parsed.astimezone(timezone.utc)


async def _run_command(
    arguments: argparse.Namespace,
    *,
    environ: Mapping[str, str],
    secret_source: DeploymentSecretSource | None,
) -> int:
    if arguments.command == "init-secrets":
        try:
            payload = initialize_connected_secrets(
                Path(arguments.output_dir),
                postgres_host=arguments.postgres_host,
                postgres_port=arguments.postgres_port,
                postgres_user=arguments.postgres_user,
                postgres_database=arguments.postgres_database,
                recover_partial=arguments.recover_partial,
            )
        except SecretInitializationError as error:
            raise ConnectedRuntimeError(error.code) from None
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 0
    config = ConnectedRuntimeConfig.from_env_and_secrets(
        environ,
        secret_source=secret_source,
    )
    runtime = await ConnectedRuntime.compose(config)
    try:
        if arguments.command == "migrate":
            payload = runtime.migrate()
        elif arguments.command == "preflight":
            payload = await runtime.preflight()
        elif arguments.command == "bootstrap-owner":
            payload = runtime.bootstrap_owner(
                workspace_id=arguments.workspace_id,
                email=arguments.email,
                expires_at=_parse_timestamp(arguments.expires_at),
                idempotency_key=arguments.idempotency_key,
                operator_service_id=arguments.operator_service_id,
            )
        elif arguments.command == "invite-user":
            payload = runtime.invite_user(
                workspace_id=arguments.workspace_id,
                email=arguments.email,
                role=arguments.role,
                invited_by_user_id=arguments.invited_by_user_id,
                operator_service_id=arguments.operator_service_id,
                intended_user_id=arguments.intended_user_id,
                expires_at=_parse_timestamp(arguments.expires_at),
            )
        elif arguments.command == "lookup-user":
            payload = runtime.lookup_user(
                email=arguments.email,
                workspace_id=arguments.workspace_id,
                operator_service_id=arguments.operator_service_id,
            )
        elif arguments.command == "list-users":
            payload = runtime.list_users(
                workspace_id=arguments.workspace_id,
                operator_service_id=arguments.operator_service_id,
            )
        elif arguments.command == "remove-workspace-member":
            payload = runtime.remove_workspace_member(
                user_id=arguments.user_id,
                workspace_id=arguments.workspace_id,
                operator_service_id=arguments.operator_service_id,
            )
        elif arguments.command == "restore-workspace-member":
            payload = runtime.restore_workspace_member(
                user_id=arguments.user_id,
                workspace_id=arguments.workspace_id,
                operator_service_id=arguments.operator_service_id,
            )
        elif arguments.command == "lookup-token-session":
            payload = runtime.lookup_token_session(
                user_id=arguments.user_id,
                workspace_id=arguments.workspace_id,
                operator_service_id=arguments.operator_service_id,
            )
        elif arguments.command == "list-token-sessions":
            payload = runtime.list_token_sessions(
                user_id=arguments.user_id,
                workspace_id=arguments.workspace_id,
                operator_service_id=arguments.operator_service_id,
            )
        elif arguments.command == "export-issue20-live-audit":
            payload = runtime.export_issue20_live_audit(
                workspace_id=arguments.workspace_id,
                started_at=_parse_timestamp(arguments.started_at),
                ended_at=_parse_timestamp(arguments.ended_at),
                operator_service_id=arguments.operator_service_id,
                output_path=arguments.output,
            )
        elif arguments.command == "revoke-token-session":
            payload = runtime.revoke_token_session(
                token_session_id=arguments.token_session_id,
                reason_code=arguments.reason_code,
                operator_service_id=arguments.operator_service_id,
            )
        else:
            await runtime.serve()
            return 0
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 0 if payload.get("status") in {"ok", "ready"} else 1
    finally:
        await runtime.aclose()


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    secret_source: DeploymentSecretSource | None = None,
) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        return asyncio.run(
            _run_command(
                arguments,
                environ=os.environ if environ is None else environ,
                secret_source=secret_source,
            )
        )
    except ConnectedRuntimeError as error:
        print(
            json.dumps(
                {"status": "error", "error": error.code},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            '{"error":"connected_runtime_command_failed","status":"error"}',
            file=sys.stderr,
        )
        return 1


__all__ = [
    "ConnectedRuntime",
    "ConnectedRuntimeConfig",
    "ConnectedRuntimeError",
    "DeploymentSecretSource",
    "DeploymentSecrets",
    "DeploymentSigningKey",
    "FileDeploymentSecretSource",
    "main",
]
