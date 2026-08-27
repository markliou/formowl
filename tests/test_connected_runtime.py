from __future__ import annotations

from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import _paths  # noqa: F401

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

import formowl_gateway.runtime as runtime_module
from formowl_auth import (
    ActorContext,
    CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
    FormOwlTokenCodec,
    OAuthPrincipal,
    OAuthTokenSession,
)
from formowl_auth import FileAuditLogStore
from formowl_auth.security import hash_oauth_value
from formowl_contract import ContractValidationError, SessionIdentity, User, WorkspaceMember
from formowl_gateway.remote import create_connected_mcp_application
from formowl_gateway.runtime import (
    ConnectedRuntime,
    ConnectedRuntimeConfig,
    ConnectedRuntimeError,
    FileDeploymentSecretSource,
    main,
)
from formowl_gateway.semantic import SemanticMcpGateway
from formowl_ingestion.storage import UploadSessionStore
from formowl_mail import build_mail_upload_session_handler
from oauth_harness import (
    collect_unittest_test_ids,
    current_scoped_functions,
    load_function_harness_manifest,
)


_PRIVATE_KEY_PEM = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
).private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
_PRIVATE_KEY_PEM_2 = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
).private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)


def _write_runtime_environment(root: Path) -> dict[str, str]:
    secret_values = {
        "database_dsn": b"postgresql://runtime-user:runtime-password@db.invalid/formowl\n",
        "google_client_secret": b"google-runtime-secret\n",
        "state_encryption_key": Fernet.generate_key() + b"\n",
        "signing_private_key": _PRIVATE_KEY_PEM,
    }
    secret_paths: dict[str, str] = {}
    for name, value in secret_values.items():
        path = root / f"{name}.secret"
        path.write_bytes(value)
        secret_paths[name] = str(path)
    signing_manifest = root / "signing-key-set.json"
    signing_manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "keys": [
                    {
                        "kid": "formowl-runtime-key-1",
                        "private_key_file": secret_paths["signing_private_key"],
                        "active": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return {
        "FORMOWL_AUTH_MODE": "oauth_google",
        "FORMOWL_OAUTH_ISSUER": "http://127.0.0.1:8765",
        "FORMOWL_MCP_RESOURCE": "http://127.0.0.1:8765/mcp",
        "FORMOWL_CHATGPT_CLIENT_ID": "chatgpt_closed_beta",
        "FORMOWL_CHATGPT_REDIRECT_URI": "https://chatgpt.com/connector/oauth/runtime-test",
        "FORMOWL_GOOGLE_CLIENT_ID": "google-client.apps.googleusercontent.com",
        "FORMOWL_GOOGLE_REDIRECT_URI": ("http://127.0.0.1:8765/oauth/google/callback"),
        "FORMOWL_OAUTH_ALLOW_LOOPBACK_HTTP": "1",
        "FORMOWL_CONNECTED_HOST": "127.0.0.1",
        "FORMOWL_CONNECTED_PORT": "8765",
        "FORMOWL_LOG_LEVEL": "warning",
        "FORMOWL_DATA_DIR": str(root / "runtime-data"),
        "FORMOWL_UPLOAD_SESSION_LIFETIME_SECONDS": "3600",
        "FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID": "operator-trusted",
        "FORMOWL_DATABASE_DSN_FILE": secret_paths["database_dsn"],
        "FORMOWL_GOOGLE_CLIENT_SECRET_FILE": secret_paths["google_client_secret"],
        "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE": secret_paths["state_encryption_key"],
        "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE": str(signing_manifest),
    }


class _FakeConnection:
    def __init__(
        self,
        *,
        schema_ready: bool = True,
        missing_schema_items: set[str] | None = None,
    ) -> None:
        self.schema_ready = schema_ready
        self.missing_schema_items = set(missing_schema_items or ())
        self.queries: list[Any] = []

    def query_one(self, statement: Any) -> dict[str, Any]:
        self.queries.append(statement)
        parameters = statement.parameters
        if "column_name" in parameters:
            key = f"column:{parameters['table_name']}.{parameters['column_name']}"
            return {
                "column_name": parameters["column_name"]
                if self.schema_ready and key not in self.missing_schema_items
                else None
            }
        if "constraint_pattern" in parameters:
            identity = parameters["constraint_name"] or parameters["constraint_pattern"]
            key = f"constraint:{parameters['table_name']}:{identity}"
            return {
                "constraint_name": "constraint_present"
                if self.schema_ready and key not in self.missing_schema_items
                else None
            }
        if "relation_name" in parameters:
            key = f"index:{parameters['relation_name']}"
            return {
                "relation": parameters["relation_name"]
                if self.schema_ready and key not in self.missing_schema_items
                else None
            }
        key = f"table:{parameters['table_name']}"
        return {
            "relation": parameters["table_name"]
            if self.schema_ready and key not in self.missing_schema_items
            else None
        }


class _FakeRepository:
    def __init__(
        self,
        *,
        healthy: bool = True,
        schema_ready: bool = True,
        missing_schema_items: set[str] | None = None,
    ) -> None:
        self.healthy = healthy
        self.connection = _FakeConnection(
            schema_ready=schema_ready,
            missing_schema_items=missing_schema_items,
        )
        self.close_calls = 0
        self.migration_calls = 0
        self.transaction_calls = 0

    def health_check(self) -> bool:
        return self.healthy

    def apply_migrations(self) -> Any:
        self.migration_calls += 1
        return SimpleNamespace(
            to_safe_dict=lambda: {
                "status": "ok",
                "migration_ledger_version": 1,
                "applied_migration_count": 2,
                "skipped_migration_count": 3,
                "applied_statement_count": 17,
                "latest_migration_version": 5,
            }
        )

    def close(self) -> None:
        self.close_calls += 1

    def transaction(self) -> Any:
        self.transaction_calls += 1
        raise AssertionError("unauthorized bootstrap reached repository transaction")


class _FakeHttpClient:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


class _RecordingSecretSource:
    def __init__(self) -> None:
        self.calls = 0

    def load(self, environ: dict[str, str]) -> Any:
        self.calls += 1
        return FileDeploymentSecretSource().load(environ)


class _CountingSessionManager:
    def __init__(self, *, fail_startup: bool = False) -> None:
        self.fail_startup = fail_startup
        self.enter_calls = 0
        self.exit_calls = 0

    @asynccontextmanager
    async def run(self) -> Any:
        self.enter_calls += 1
        if self.fail_startup:
            raise RuntimeError("session_manager_startup_failed")
        try:
            yield
        finally:
            self.exit_calls += 1

    async def handle_request(self, _scope: Any, _receive: Any, _send: Any) -> None:
        return None


def _fake_application(manager: _CountingSessionManager, *, manages: bool = False) -> Any:
    app = Starlette()
    app.state.formowl_session_manager_lifespan_managed = manages
    return SimpleNamespace(
        app=app,
        session_manager=manager,
        manages_session_manager_lifespan=manages,
    )


class ConnectedRuntimeConfigTests(unittest.TestCase):
    def test_direct_runtime_and_mail_upload_helpers_preserve_safe_governed_boundaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            environment = _write_runtime_environment(root)

            self.assertTrue(
                runtime_module._read_secret_file(environment["FORMOWL_DATABASE_DSN_FILE"])
                .decode("utf-8")
                .startswith("postgresql://runtime-user:")
            )
            signing_keys = runtime_module._load_signing_key_manifest(
                environment["FORMOWL_OAUTH_SIGNING_KEY_SET_FILE"]
            )
            self.assertEqual(len(signing_keys), 1)
            self.assertTrue(signing_keys[0].active)
            self.assertEqual(signing_keys[0].kid, "formowl-runtime-key-1")

            unsafe_error = ConnectedRuntimeError("private/path?token=value")
            self.assertEqual(unsafe_error.code, "connected_runtime_error")
            self.assertEqual(str(unsafe_error), "connected_runtime_error")
            self.assertNotIn("private", repr(unsafe_error))
            self.assertNotIn("token", repr(unsafe_error))

            repository = object()
            composed_runtime = ConnectedRuntime(
                config=SimpleNamespace(owner_bootstrap_operator_service_id="operator_trusted"),
                repository=repository,
                http_client=object(),
                google_client=object(),
                bridge=object(),
                application=object(),
            )
            directory = composed_runtime._operator_directory()
            self.assertIs(directory.repository, repository)
            self.assertEqual(
                directory.expected_operator_service_id,
                "operator_trusted",
            )

            gateway = runtime_module._build_runtime_semantic_gateway(
                SimpleNamespace(
                    data_dir=root,
                    upload_session_lifetime_seconds=600,
                )
            )
            with self.assertRaisesRegex(
                ContractValidationError,
                "exactly one upload session expiry source",
            ):
                build_mail_upload_session_handler(
                    upload_session_store=UploadSessionStore(root),
                    audit_store=FileAuditLogStore(root),
                )
            with self.assertRaisesRegex(
                ContractValidationError,
                "exactly one upload session expiry source",
            ):
                build_mail_upload_session_handler(
                    upload_session_store=UploadSessionStore(root),
                    audit_store=FileAuditLogStore(root),
                    expires_at="2030-01-01T00:10:00+00:00",
                    expires_at_provider=lambda: "2030-01-01T00:10:00+00:00",
                )
            self.assertTrue(runtime_module._runtime_data_stores_ready(root))
            self.assertEqual(list(root.rglob(".formowl-ready-*")), [])
            handler = gateway.upload_session_handler
            self.assertIsNotNone(handler)
            assert handler is not None

            class SequencedDateTime:
                values = iter(
                    (
                        datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc),
                        datetime(2030, 1, 1, 0, 1, tzinfo=timezone.utc),
                    )
                )

                @classmethod
                def now(cls, tz: Any = None) -> datetime:
                    value = next(cls.values)
                    return value if tz is None else value.astimezone(tz)

            input_data = {
                "requester_user_id": "user_direct",
                "session_id": "oauthsid_direct_1",
                "workspace_id": "workspace_direct",
                "intent": "Upload governed mail evidence.",
                "intended_asset_type": "pst",
                "owner_scope_type": "workspace",
                "owner_scope_id": "workspace_direct",
                "visibility_scope": "workspace",
            }
            with (
                patch.object(runtime_module, "datetime", SequencedDateTime),
                patch(
                    "formowl_mail.upload_session.now_iso",
                    side_effect=(
                        "2030-01-01T00:00:00+00:00",
                        "2030-01-01T00:01:00+00:00",
                    ),
                ),
            ):
                first = handler(dict(input_data))
                second = handler(
                    {
                        **input_data,
                        "session_id": "oauthsid_direct_2",
                    }
                )

            self.assertEqual(first["status"], "ok")
            self.assertEqual(second["status"], "ok")
            sessions = UploadSessionStore(root).list()
            self.assertEqual(len(sessions), 2)
            self.assertEqual(
                {session.session_id for session in sessions},
                {"oauthsid_direct_1", "oauthsid_direct_2"},
            )
            self.assertEqual(
                {session.expires_at for session in sessions},
                {
                    "2030-01-01T00:10:00+00:00",
                    "2030-01-01T00:11:00+00:00",
                },
            )
            audits = FileAuditLogStore(root).list()
            self.assertEqual(len(audits), 2)
            self.assertEqual(
                {audit.target_id for audit in audits},
                {session.upload_session_id for session in sessions},
            )
            rendered = repr((first, second, sessions, audits))
            self.assertNotIn(temporary_directory, rendered)
            self.assertNotIn("signing_private_key", rendered)
            self.assertNotIn("runtime-password", rendered)

    def test_file_secrets_config_repr_and_persistent_signing_key_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = _write_runtime_environment(Path(temporary_directory))
            first = ConnectedRuntimeConfig.from_env_and_secrets(environment)
            second = ConnectedRuntimeConfig.from_env_and_secrets(environment)

        rendered = repr(first)
        self.assertNotIn("runtime-password", rendered)
        self.assertNotIn("google-runtime-secret", rendered)
        self.assertNotIn("PRIVATE KEY", rendered)
        self.assertNotIn("database_dsn", rendered)
        self.assertNotIn(temporary_directory, rendered)
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        self.assertEqual(
            first.signing_key_set.public_jwks(now=now),
            second.signing_key_set.public_jwks(now=now),
        )
        self.assertEqual(first.host, "127.0.0.1")
        self.assertEqual(first.port, 8765)
        self.assertEqual(first.log_level, "warning")

    def test_reserved_callback_selects_discovery_only_runtime_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = _write_runtime_environment(Path(temporary_directory))
            environment["FORMOWL_CHATGPT_REDIRECT_URI"] = CHATGPT_DISCOVERY_ONLY_REDIRECT_URI
            config = ConnectedRuntimeConfig.from_env_and_secrets(environment)

        self.assertEqual(config.oauth.chatgpt_callback_mode, "discovery_only")
        self.assertEqual(
            config.oauth.chatgpt_redirect_uri,
            CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
        )

    def test_file_mounted_signing_key_rotation_survives_restart_overlap(self) -> None:
        now = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            environment = _write_runtime_environment(root)
            before = ConnectedRuntimeConfig.from_env_and_secrets(environment)
            session = OAuthTokenSession(
                token_session_id="oauthsid_rotation",
                user_id="user_rotation",
                external_identity_id="extid_rotation",
                oauth_client_authorization_id="clientauth_rotation",
                client_id=before.oauth.chatgpt_client_id,
                current_workspace_id="workspace_rotation",
                resource=before.oauth.resource,
                scopes=before.oauth.scopes,
                token_jti_hash=hash_oauth_value("token_jti", "jti_rotation_old"),
                issued_at=now.isoformat(),
                expires_at=(now + timedelta(hours=1)).isoformat(),
            )
            old_codec = FormOwlTokenCodec(
                issuer=before.oauth.issuer,
                client_id=before.oauth.chatgpt_client_id,
                key_set=before.signing_key_set,
            )
            old_token = old_codec.issue_access_token(
                session=session,
                jti="jti_rotation_old",
                now=now,
            )

            second_key_path = root / "signing_private_key_2.secret"
            second_key_path.write_bytes(_PRIVATE_KEY_PEM_2)
            manifest_path = Path(environment["FORMOWL_OAUTH_SIGNING_KEY_SET_FILE"])
            first_key_path = json.loads(manifest_path.read_text(encoding="utf-8"))["keys"][0][
                "private_key_file"
            ]
            manifest_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "keys": [
                            {
                                "kid": "formowl-runtime-key-1",
                                "private_key_file": first_key_path,
                                "active": False,
                                "verify_until": (now + timedelta(hours=1)).isoformat(),
                            },
                            {
                                "kid": "formowl-runtime-key-2",
                                "private_key_file": str(second_key_path),
                                "active": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            after = ConnectedRuntimeConfig.from_env_and_secrets(environment)
            restarted = ConnectedRuntimeConfig.from_env_and_secrets(environment)

        rotated_codec = FormOwlTokenCodec(
            issuer=after.oauth.issuer,
            client_id=after.oauth.chatgpt_client_id,
            key_set=after.signing_key_set,
        )
        claims = rotated_codec.verify_access_token(
            old_token,
            resource=after.oauth.resource,
            required_scope="formowl.use",
            now=now + timedelta(minutes=5),
        )
        self.assertEqual(claims["sub"], "user_rotation")
        self.assertEqual(after.signing_key_set.active_key.kid, "formowl-runtime-key-2")
        self.assertEqual(
            after.signing_key_set.public_jwks(now=now + timedelta(minutes=5)),
            restarted.signing_key_set.public_jwks(now=now + timedelta(minutes=5)),
        )
        public_jwks = after.signing_key_set.public_jwks(now=now + timedelta(minutes=5))
        self.assertEqual(
            {key["kid"] for key in public_jwks["keys"]},
            {
                "formowl-runtime-key-1",
                "formowl-runtime-key-2",
            },
        )
        self.assertFalse(
            any(
                private_name in key
                for key in public_jwks["keys"]
                for private_name in ("d", "p", "q", "dp", "dq", "qi")
            )
        )

    def test_signing_key_manifest_invalid_layouts_fail_closed_without_leak(self) -> None:
        mutations = (
            {"version": 1, "keys": []},
            {
                "version": 1,
                "keys": [
                    {"kid": "key-a", "private_key_file": "KEY_PATH", "active": True},
                    {"kid": "key-b", "private_key_file": "KEY_PATH_2", "active": True},
                ],
            },
            {
                "version": 1,
                "keys": [
                    {"kid": "key-a", "private_key_file": "KEY_PATH", "active": True},
                    {"kid": "key-b", "private_key_file": "KEY_PATH_2", "active": False},
                ],
            },
            {
                "version": 1,
                "keys": [
                    {
                        "kid": "key-a",
                        "private_key_file": "KEY_PATH",
                        "private_key_pem": "PRIVATE KEY MATERIAL",
                        "active": True,
                    }
                ],
            },
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                environment = _write_runtime_environment(root)
                second_key_path = root / "second-key.secret"
                second_key_path.write_bytes(_PRIVATE_KEY_PEM_2)
                first_key_path = str(root / "signing_private_key.secret")
                payload = json.loads(json.dumps(mutation))
                rendered = json.dumps(payload).replace("KEY_PATH_2", str(second_key_path))
                rendered = rendered.replace("KEY_PATH", first_key_path)
                manifest_path = Path(environment["FORMOWL_OAUTH_SIGNING_KEY_SET_FILE"])
                manifest_path.write_text(rendered, encoding="utf-8")

                with self.assertRaisesRegex(
                    ConnectedRuntimeError,
                    "deployment_signing_key_manifest_invalid",
                ) as denied:
                    ConnectedRuntimeConfig.from_env_and_secrets(environment)

                self.assertNotIn(directory, repr(denied.exception))
                self.assertNotIn("PRIVATE KEY MATERIAL", repr(denied.exception))

    def test_secret_and_config_failures_use_only_machine_safe_codes(self) -> None:
        with self.assertRaises(ConnectedRuntimeError) as missing:
            FileDeploymentSecretSource().load({})
        self.assertEqual(str(missing.exception), "deployment_secret_file_config_missing")

        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = _write_runtime_environment(Path(temporary_directory))
            secret_path = environment["FORMOWL_DATABASE_DSN_FILE"]
            environment["FORMOWL_DATABASE_DSN_FILE"] = secret_path + ".missing"
            with self.assertRaises(ConnectedRuntimeError) as unavailable:
                ConnectedRuntimeConfig.from_env_and_secrets(environment)
            rendered = repr(unavailable.exception)
            self.assertEqual(str(unavailable.exception), "deployment_secret_file_unavailable")
            self.assertNotIn(secret_path, rendered)
            self.assertNotIn("runtime-password", rendered)

        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = _write_runtime_environment(Path(temporary_directory))
            environment["FORMOWL_MCP_ACTOR_USER_ID"] = "manual-user"
            with self.assertRaisesRegex(
                ConnectedRuntimeError,
                "connected_manual_identity_forbidden",
            ):
                ConnectedRuntimeConfig.from_env_and_secrets(environment)
            environment.pop("FORMOWL_MCP_ACTOR_USER_ID")
            environment["FORMOWL_GOOGLE_CLIENT_SECRET"] = "plaintext-secret"
            with self.assertRaisesRegex(
                ConnectedRuntimeError,
                "connected_plaintext_secret_forbidden",
            ):
                ConnectedRuntimeConfig.from_env_and_secrets(environment)

    def test_secret_file_content_negative_matrix_is_safe(self) -> None:
        cases = (
            ("empty", "FORMOWL_DATABASE_DSN_FILE", b""),
            ("nul", "FORMOWL_GOOGLE_CLIENT_SECRET_FILE", b"secret\x00value"),
            (
                "oversize",
                "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE",
                b"x" * (runtime_module._MAX_SECRET_FILE_BYTES + 1),
            ),
            ("non_decodable", "FORMOWL_DATABASE_DSN_FILE", b"\xff\xfe\xfd"),
        )
        for case_name, secret_env_name, value in cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as directory:
                environment = _write_runtime_environment(Path(directory))
                path = Path(environment[secret_env_name])
                path.write_bytes(value)
                with self.assertRaisesRegex(
                    ConnectedRuntimeError,
                    "deployment_secret_file_invalid",
                ) as denied:
                    ConnectedRuntimeConfig.from_env_and_secrets(environment)
                rendered = repr(denied.exception)
                self.assertNotIn(str(path), rendered)
                marker = value[:32].decode("utf-8", errors="ignore")
                if marker:
                    self.assertNotIn(marker, rendered)
                self.assertNotIn("postgresql", rendered)

    def test_oauth_signing_and_server_config_negative_matrix_is_stage_specific(self) -> None:
        late_cases = (
            (
                "invalid_fernet",
                "file",
                "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE",
                b"not-a-fernet-key-private",
                "connected_oauth_config_invalid",
            ),
            (
                "invalid_rsa",
                "signing_key_file",
                "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE",
                b"not-an-rsa-private-key",
                "connected_signing_key_invalid",
            ),
            (
                "invalid_kid",
                "signing_kid",
                "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE",
                "invalid kid private",
                "deployment_signing_key_manifest_invalid",
            ),
            (
                "invalid_issuer",
                "env",
                "FORMOWL_OAUTH_ISSUER",
                "http://external.invalid",
                "connected_oauth_config_invalid",
            ),
            (
                "invalid_resource",
                "env",
                "FORMOWL_MCP_RESOURCE",
                "http://127.0.0.1:8765/not-mcp",
                "connected_oauth_config_invalid",
            ),
            (
                "invalid_google_callback",
                "env",
                "FORMOWL_GOOGLE_REDIRECT_URI",
                "http://127.0.0.1:8765/oauth/google/wrong",
                "connected_oauth_config_invalid",
            ),
            (
                "invalid_chatgpt_callback",
                "env",
                "FORMOWL_CHATGPT_REDIRECT_URI",
                "https://chatgpt.com/connector/oauth/*",
                "connected_oauth_config_invalid",
            ),
            (
                "arbitrary_https_chatgpt_callback",
                "env",
                "FORMOWL_CHATGPT_REDIRECT_URI",
                "https://attacker.example/callback",
                "connected_oauth_config_invalid",
            ),
            (
                "other_invalid_discovery_callback",
                "env",
                "FORMOWL_CHATGPT_REDIRECT_URI",
                "https://other.invalid/formowl-discovery-only",
                "connected_oauth_config_invalid",
            ),
        )
        for case_name, mutation_type, name, value, expected_code in late_cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as directory:
                environment = _write_runtime_environment(Path(directory))
                if mutation_type == "file":
                    Path(environment[name]).write_bytes(value)
                elif mutation_type in {"signing_key_file", "signing_kid"}:
                    manifest_path = Path(environment[name])
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if mutation_type == "signing_key_file":
                        Path(manifest["keys"][0]["private_key_file"]).write_bytes(value)
                    else:
                        manifest["keys"][0]["kid"] = value
                        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                else:
                    environment[name] = value
                source = _RecordingSecretSource()
                with self.assertRaisesRegex(
                    ConnectedRuntimeError,
                    expected_code,
                ) as denied:
                    ConnectedRuntimeConfig.from_env_and_secrets(
                        environment,
                        secret_source=source,
                    )
                self.assertEqual(source.calls, 1)
                rendered = repr(denied.exception)
                self.assertNotIn(str(value), rendered)
                self.assertNotIn(directory, rendered)

        early_cases = (
            ("invalid_host", "FORMOWL_CONNECTED_HOST", "bad host", "connected_host_invalid"),
            ("invalid_port_text", "FORMOWL_CONNECTED_PORT", "private", "connected_port_invalid"),
            ("invalid_port_range", "FORMOWL_CONNECTED_PORT", "0", "connected_port_invalid"),
            ("invalid_log", "FORMOWL_LOG_LEVEL", "trace", "connected_log_level_invalid"),
            (
                "invalid_data_dir",
                "FORMOWL_DATA_DIR",
                "relative/private/path",
                "connected_data_dir_invalid",
            ),
            (
                "invalid_upload_lifetime",
                "FORMOWL_UPLOAD_SESSION_LIFETIME_SECONDS",
                "59",
                "connected_upload_lifetime_invalid",
            ),
            (
                "invalid_auth_mode",
                "FORMOWL_AUTH_MODE",
                "manual_trusted_internal",
                "connected_google_oauth_required",
            ),
        )
        for case_name, name, value, expected_code in early_cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as directory:
                environment = _write_runtime_environment(Path(directory))
                environment[name] = value
                source = _RecordingSecretSource()
                with self.assertRaisesRegex(
                    ConnectedRuntimeError,
                    expected_code,
                ) as denied:
                    ConnectedRuntimeConfig.from_env_and_secrets(
                        environment,
                        secret_source=source,
                    )
                self.assertEqual(source.calls, 0)
                self.assertNotIn(str(value), repr(denied.exception))
                self.assertNotIn(directory, repr(denied.exception))

    def test_invalid_database_dsn_fails_before_resources_bind_and_stderr_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = _write_runtime_environment(Path(directory))
            dsn_path = Path(environment["FORMOWL_DATABASE_DSN_FILE"])
            invalid_dsn = "not-a-postgresql-dsn-private-value"
            dsn_path.write_text(invalid_dsn, encoding="utf-8")
            config = ConnectedRuntimeConfig.from_env_and_secrets(environment)
            http_factory = Mock()
            application_factory = Mock()
            with (
                patch.object(
                    runtime_module.PostgreSQLOAuthRepository,
                    "connect",
                    side_effect=RuntimeError("database rejected private dsn"),
                ) as connect,
                patch.object(runtime_module.httpx, "AsyncClient", http_factory),
                patch.object(
                    runtime_module,
                    "create_connected_mcp_application",
                    application_factory,
                ),
            ):
                with self.assertRaisesRegex(
                    ConnectedRuntimeError,
                    "connected_runtime_composition_failed",
                ) as denied:
                    asyncio.run(ConnectedRuntime.compose(config))
            connect.assert_called_once_with(invalid_dsn)
            http_factory.assert_not_called()
            application_factory.assert_not_called()
            self.assertNotIn(invalid_dsn, repr(denied.exception))
            self.assertNotIn(str(dsn_path), repr(denied.exception))

            error_output = StringIO()
            with (
                patch.object(
                    runtime_module.PostgreSQLOAuthRepository,
                    "connect",
                    side_effect=RuntimeError("database rejected private dsn"),
                ),
                patch.object(runtime_module.httpx, "AsyncClient", http_factory),
                patch.object(
                    runtime_module,
                    "create_connected_mcp_application",
                    application_factory,
                ),
                redirect_stderr(error_output),
            ):
                exit_code = main(["preflight"], environ=environment)
            self.assertEqual(exit_code, 1)
            self.assertEqual(
                json.loads(error_output.getvalue())["error"],
                "connected_runtime_composition_failed",
            )
            self.assertNotIn(invalid_dsn, error_output.getvalue())
            self.assertNotIn(str(dsn_path), error_output.getvalue())


class ConnectedRuntimeSchemaFingerprintTests(unittest.TestCase):
    def test_client_authorization_identity_user_pair_constraints_are_required(self) -> None:
        required = {
            (table_name, constraint_type, constraint_name, constraint_pattern)
            for (
                table_name,
                constraint_type,
                constraint_name,
                constraint_pattern,
            ) in runtime_module._REQUIRED_SCHEMA_CONSTRAINTS
        }
        expected = {
            (
                "formowl_external_identities",
                "u",
                "uq_formowl_external_identity_user",
                "%UNIQUE (external_identity_id, user_id)%",
            ),
            (
                "formowl_oauth_client_authorizations",
                "f",
                "fk_formowl_client_authorization_identity_user",
                "%FOREIGN KEY (external_identity_id, user_id) REFERENCES "
                "formowl_external_identities(external_identity_id, user_id) "
                "ON DELETE RESTRICT%",
            ),
        }
        self.assertTrue(expected.issubset(required))

        for table_name, _constraint_type, constraint_name, _pattern in expected:
            with self.subTest(constraint=constraint_name):
                stale = _FakeRepository(
                    missing_schema_items={f"constraint:{table_name}:{constraint_name}"}
                )
                self.assertFalse(runtime_module._repository_schema_ready(stale))

    def test_complete_fingerprint_is_parameterized_and_every_critical_item_is_required(
        self,
    ) -> None:
        complete = _FakeRepository()
        self.assertTrue(runtime_module._repository_schema_ready(complete))
        self.assertGreater(len(complete.connection.queries), 20)
        for statement in complete.connection.queries:
            self.assertTrue(statement.parameters)
            self.assertIn("%(", statement.sql)

        critical_items = [
            *(f"table:{name}" for name in runtime_module._REQUIRED_OAUTH_TABLES),
            *(
                f"column:{table_name}.{column_name}"
                for table_name, column_names in runtime_module._REQUIRED_SCHEMA_COLUMNS.items()
                for column_name in column_names
            ),
            *(
                f"constraint:{table_name}:{constraint_name or constraint_pattern}"
                for (
                    table_name,
                    _constraint_type,
                    constraint_name,
                    constraint_pattern,
                ) in runtime_module._REQUIRED_SCHEMA_CONSTRAINTS
            ),
            *(f"index:{name}" for name in runtime_module._REQUIRED_SCHEMA_INDEXES),
        ]
        for missing_item in critical_items:
            with self.subTest(missing_item=missing_item):
                stale = _FakeRepository(missing_schema_items={missing_item})
                self.assertFalse(runtime_module._repository_schema_ready(stale))


class ConnectedRuntimeManifestTests(unittest.TestCase):
    def test_every_phase_a_function_has_complete_known_manifest_evidence(self) -> None:
        runtime_functions = {
            ("formowl_gateway.runtime", "FileDeploymentSecretSource.load"),
            ("formowl_gateway.runtime", "ConnectedRuntimeConfig.from_env_and_secrets"),
            ("formowl_gateway.runtime", "ConnectedRuntime.compose"),
            ("formowl_gateway.runtime", "ConnectedRuntime.lifespan"),
            ("formowl_gateway.runtime", "ConnectedRuntime.aclose"),
            ("formowl_gateway.runtime", "ConnectedRuntime.readiness"),
            ("formowl_gateway.runtime", "ConnectedRuntime.preflight"),
            ("formowl_gateway.runtime", "ConnectedRuntime.migrate"),
            ("formowl_gateway.runtime", "ConnectedRuntime.bootstrap_owner"),
            ("formowl_gateway.runtime", "ConnectedRuntime.serve"),
            ("formowl_gateway.runtime", "_repository_schema_ready"),
            ("formowl_gateway.runtime", "_healthz_endpoint"),
            ("formowl_gateway.runtime", "_readyz_endpoint"),
            ("formowl_gateway.runtime", "_build_parser"),
            ("formowl_gateway.runtime", "_parse_timestamp"),
            ("formowl_gateway.runtime", "_run_command"),
            ("formowl_gateway.runtime", "main"),
        }
        modified_remote_functions = {
            ("formowl_gateway.remote", "RemoteMcpDispatcher.list_tools"),
            ("formowl_gateway.remote", "RemoteMcpDispatcher.call_tool"),
            ("formowl_gateway.remote", "build_remote_tool_descriptors"),
            ("formowl_gateway.remote", "create_connected_mcp_application"),
            ("formowl_gateway.remote", "run_connected_mcp_application"),
            ("formowl_gateway.remote", "remote_main"),
        }
        expected = runtime_functions | modified_remote_functions
        manifest = load_function_harness_manifest()
        entries = {
            (entry["module"], entry["qualname"]): entry
            for entry in manifest["functions"]
            if (entry["module"], entry["qualname"]) in expected
        }
        current = current_scoped_functions(
            _paths.ROOT,
            ("python/formowl_gateway/runtime.py", "python/formowl_gateway/remote.py"),
        )
        collected = collect_unittest_test_ids(_paths.ROOT / "tests")

        self.assertEqual(set(entries), expected)
        self.assertTrue(expected <= current)
        self.assertEqual(
            {key for key in entries if key[0] == "formowl_gateway.runtime"},
            runtime_functions,
        )
        for key, entry in entries.items():
            with self.subTest(function=key):
                self.assertEqual(set(entry["categories"]), set(manifest["required_categories"]))
                union: set[str] = set()
                for category in manifest["required_categories"]:
                    evidence = entry["categories"][category]
                    test_ids = evidence["test_ids"]
                    reason = evidence["not_applicable_reason"]
                    self.assertTrue(test_ids or (isinstance(reason, str) and reason.strip()))
                    self.assertTrue(set(test_ids) <= collected)
                    union.update(test_ids)
                self.assertEqual(set(entry["test_ids"]), union)


class ConnectedRuntimeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        environment = _write_runtime_environment(Path(self.temporary_directory.name))
        self.config = ConnectedRuntimeConfig.from_env_and_secrets(environment)

    async def test_combined_lifespan_enters_and_closes_each_resource_once(self) -> None:
        repository = _FakeRepository()
        http_client = _FakeHttpClient()
        manager = _CountingSessionManager()
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=repository,
            ),
            patch.object(runtime_module.httpx, "AsyncClient", return_value=http_client),
            patch.object(
                runtime_module,
                "create_connected_mcp_application",
                return_value=_fake_application(manager),
            ),
        ):
            runtime = await ConnectedRuntime.compose(self.config)

        async with runtime.lifespan(runtime.application.app):
            self.assertTrue(runtime._running)
            self.assertEqual(manager.enter_calls, 1)
        await runtime.aclose()

        self.assertEqual(manager.enter_calls, 1)
        self.assertEqual(manager.exit_calls, 1)
        self.assertEqual(http_client.close_calls, 1)
        self.assertEqual(repository.close_calls, 1)

    async def test_health_requires_running_lifespan_and_runtime_state(self) -> None:
        repository = _FakeRepository()
        http_client = _FakeHttpClient()
        manager = _CountingSessionManager()
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=repository,
            ),
            patch.object(runtime_module.httpx, "AsyncClient", return_value=http_client),
            patch.object(
                runtime_module,
                "create_connected_mcp_application",
                return_value=_fake_application(manager),
            ),
        ):
            runtime = await ConnectedRuntime.compose(self.config)

        request = Request({"type": "http", "app": runtime.application.app})
        before = await runtime_module._healthz_endpoint(request)
        async with runtime.lifespan(runtime.application.app):
            during = await runtime_module._healthz_endpoint(request)
        after = await runtime_module._healthz_endpoint(request)
        missing_app = Starlette()
        missing = await runtime_module._healthz_endpoint(
            Request({"type": "http", "app": missing_app})
        )

        self.assertEqual(before.status_code, 503)
        self.assertEqual(during.status_code, 200)
        self.assertEqual(after.status_code, 503)
        self.assertEqual(missing.status_code, 503)
        for response in (before, during, after, missing):
            self.assertEqual(response.headers["cache-control"], "no-store")
            payload = json.loads(response.body)
            self.assertEqual(set(payload), {"status"})
            self.assertNotIn("repository", response.body.decode("utf-8"))
            self.assertNotIn("secret", response.body.decode("utf-8"))

    async def test_startup_and_composition_failures_rethrow_and_roll_back(self) -> None:
        repository = _FakeRepository()
        http_client = _FakeHttpClient()
        manager = _CountingSessionManager(fail_startup=True)
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=repository,
            ),
            patch.object(runtime_module.httpx, "AsyncClient", return_value=http_client),
            patch.object(
                runtime_module,
                "create_connected_mcp_application",
                return_value=_fake_application(manager),
            ),
        ):
            runtime = await ConnectedRuntime.compose(self.config)

        with self.assertRaisesRegex(RuntimeError, "session_manager_startup_failed"):
            async with runtime.lifespan(runtime.application.app):
                pass
        self.assertEqual(http_client.close_calls, 1)
        self.assertEqual(repository.close_calls, 1)

        repository = _FakeRepository()
        http_client = _FakeHttpClient()
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=repository,
            ),
            patch.object(runtime_module.httpx, "AsyncClient", return_value=http_client),
            patch.object(
                runtime_module,
                "create_connected_mcp_application",
                side_effect=RuntimeError("private-path-and-secret"),
            ),
        ):
            with self.assertRaisesRegex(
                ConnectedRuntimeError,
                "connected_runtime_composition_failed",
            ):
                await ConnectedRuntime.compose(self.config)
        self.assertEqual(http_client.close_calls, 1)
        self.assertEqual(repository.close_calls, 1)

    async def test_runtime_rejects_factory_double_lifespan_management(self) -> None:
        repository = _FakeRepository()
        http_client = _FakeHttpClient()
        manager = _CountingSessionManager()
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=repository,
            ),
            patch.object(runtime_module.httpx, "AsyncClient", return_value=http_client),
            patch.object(
                runtime_module,
                "create_connected_mcp_application",
                return_value=_fake_application(manager, manages=True),
            ),
        ):
            with self.assertRaisesRegex(
                ConnectedRuntimeError,
                "connected_lifespan_double_management",
            ):
                await ConnectedRuntime.compose(self.config)
        self.assertEqual(manager.enter_calls, 0)
        self.assertEqual(http_client.close_calls, 1)
        self.assertEqual(repository.close_calls, 1)

    async def test_bootstrap_operator_authority_is_deployment_bound_and_fails_closed(self) -> None:
        for configured_operator, candidate in (
            ("operator-trusted", "operator-arbitrary"),
            ("operator-trusted", "operator-removed"),
            (None, "operator-trusted"),
        ):
            with self.subTest(
                configured_operator=configured_operator,
                candidate=candidate,
            ):
                config = ConnectedRuntimeConfig(
                    oauth=self.config.oauth,
                    database_dsn=self.config.database_dsn,
                    signing_key_set=self.config.signing_key_set,
                    host=self.config.host,
                    port=self.config.port,
                    log_level=self.config.log_level,
                    data_dir=self.config.data_dir,
                    upload_session_lifetime_seconds=(self.config.upload_session_lifetime_seconds),
                    owner_bootstrap_operator_service_id=configured_operator,
                )
                repository = _FakeRepository()
                http_client = _FakeHttpClient()
                manager = _CountingSessionManager()
                with (
                    patch.object(
                        runtime_module.PostgreSQLOAuthRepository,
                        "connect",
                        return_value=repository,
                    ),
                    patch.object(
                        runtime_module.httpx,
                        "AsyncClient",
                        return_value=http_client,
                    ),
                    patch.object(
                        runtime_module,
                        "create_connected_mcp_application",
                        return_value=_fake_application(manager),
                    ),
                ):
                    runtime = await ConnectedRuntime.compose(config)
                with self.assertRaisesRegex(
                    ConnectedRuntimeError,
                    "connected_owner_bootstrap_failed",
                ) as denied:
                    runtime.bootstrap_owner(
                        workspace_id="workspace-safe",
                        email="owner@example.test",
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                        idempotency_key="bootstrap-safe",
                        operator_service_id=candidate,
                    )
                self.assertEqual(repository.transaction_calls, 0)
                self.assertNotIn(candidate, repr(denied.exception))
                await runtime.aclose()

    async def test_discovery_only_blocks_operator_state_and_audited_lookup_entrypoints(
        self,
    ) -> None:
        discovery_config = replace(
            self.config,
            oauth=replace(
                self.config.oauth,
                chatgpt_redirect_uri=CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
            ),
        )
        repository = _FakeRepository()
        http_client = _FakeHttpClient()
        manager = _CountingSessionManager()
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=repository,
            ),
            patch.object(runtime_module.httpx, "AsyncClient", return_value=http_client),
            patch.object(
                runtime_module,
                "create_connected_mcp_application",
                return_value=_fake_application(manager),
            ),
        ):
            runtime = await ConnectedRuntime.compose(discovery_config)

        with (
            patch.object(runtime.bridge, "bootstrap_owner_invitation") as bootstrap,
            patch.object(runtime.bridge, "provision_invitation") as invite,
            patch.object(runtime.bridge, "revoke_token_session_as_operator") as revoke,
            patch.object(runtime, "_operator_directory") as directory,
        ):
            operations = (
                lambda: runtime.bootstrap_owner(
                    workspace_id="workspace-safe",
                    email="owner@example.test",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    idempotency_key="discovery-bootstrap",
                    operator_service_id="operator-trusted",
                ),
                lambda: runtime.invite_user(
                    workspace_id="workspace-safe",
                    email="member@example.test",
                    role="member",
                    invited_by_user_id="owner-safe",
                    operator_service_id="operator-trusted",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                ),
                lambda: runtime.lookup_user(
                    email="member@example.test",
                    workspace_id="workspace-safe",
                    operator_service_id="operator-trusted",
                ),
                lambda: runtime.list_users(
                    workspace_id="workspace-safe",
                    operator_service_id="operator-trusted",
                ),
                lambda: runtime.remove_workspace_member(
                    user_id="user-safe",
                    workspace_id="workspace-safe",
                    operator_service_id="operator-trusted",
                ),
                lambda: runtime.restore_workspace_member(
                    user_id="user-safe",
                    workspace_id="workspace-safe",
                    operator_service_id="operator-trusted",
                ),
                lambda: runtime.lookup_token_session(
                    user_id="user-safe",
                    workspace_id="workspace-safe",
                    operator_service_id="operator-trusted",
                ),
                lambda: runtime.list_token_sessions(
                    user_id="user-safe",
                    workspace_id="workspace-safe",
                    operator_service_id="operator-trusted",
                ),
                lambda: runtime.revoke_token_session(
                    token_session_id="oauthsid-safe",
                    reason_code="discovery_only",
                    operator_service_id="operator-trusted",
                ),
            )
            for operation in operations:
                with self.assertRaisesRegex(
                    ConnectedRuntimeError,
                    "connected_discovery_only",
                ):
                    operation()

        bootstrap.assert_not_called()
        invite.assert_not_called()
        revoke.assert_not_called()
        directory.assert_not_called()
        self.assertEqual(repository.transaction_calls, 0)
        self.assertEqual(repository.migration_calls, 0)
        await runtime.aclose()

    async def test_discovery_preflight_is_not_ready_but_serve_allows_public_discovery(
        self,
    ) -> None:
        class FakeUvicornConfig:
            def __init__(self, app: Any, **kwargs: Any) -> None:
                self.app = app
                self.kwargs = kwargs

        class FakeUvicornServer:
            instances: list["FakeUvicornServer"] = []

            def __init__(self, config: Any) -> None:
                self.config = config
                self.serve_calls = 0
                self.__class__.instances.append(self)

            async def serve(self) -> None:
                self.serve_calls += 1

        discovery_config = replace(
            self.config,
            oauth=replace(
                self.config.oauth,
                chatgpt_redirect_uri=CHATGPT_DISCOVERY_ONLY_REDIRECT_URI,
            ),
        )
        repository = _FakeRepository()
        http_client = _FakeHttpClient()
        manager = _CountingSessionManager()
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=repository,
            ),
            patch.object(runtime_module.httpx, "AsyncClient", return_value=http_client),
            patch.object(
                runtime_module,
                "create_connected_mcp_application",
                return_value=_fake_application(manager),
            ),
        ):
            runtime = await ConnectedRuntime.compose(discovery_config)
        runtime.google_client.load_provider_metadata = AsyncMock(return_value={})
        runtime.google_client.load_jwks = AsyncMock(
            return_value={"keys": [{"kid": "google", "kty": "RSA"}]}
        )

        preflight = await runtime.preflight()
        self.assertEqual(preflight["status"], "discovery_only")
        self.assertEqual(preflight["mode"], "discovery_only")
        self.assertTrue(preflight["checks"]["configuration"])
        self.assertFalse(preflight["checks"]["oauth_callback"])
        self.assertTrue(
            all(value for name, value in preflight["checks"].items() if name != "oauth_callback")
        )

        runtime._running = True
        ready_response = await runtime_module._readyz_endpoint(
            Request({"type": "http", "app": runtime.application.app})
        )
        runtime._running = False
        self.assertEqual(ready_response.status_code, 503)
        self.assertEqual(json.loads(ready_response.body)["status"], "discovery_only")

        fake_uvicorn = SimpleNamespace(
            Config=FakeUvicornConfig,
            Server=FakeUvicornServer,
        )
        with patch.dict("sys.modules", {"uvicorn": fake_uvicorn}):
            await runtime.serve()

        self.assertEqual(FakeUvicornServer.instances[-1].serve_calls, 1)
        self.assertEqual(http_client.close_calls, 1)
        self.assertEqual(repository.close_calls, 1)

    async def test_migrate_and_bootstrap_wrappers_return_safe_results(self) -> None:
        repository = _FakeRepository()
        http_client = _FakeHttpClient()
        manager = _CountingSessionManager()
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=repository,
            ),
            patch.object(runtime_module.httpx, "AsyncClient", return_value=http_client),
            patch.object(
                runtime_module,
                "create_connected_mcp_application",
                return_value=_fake_application(manager),
            ),
        ):
            runtime = await ConnectedRuntime.compose(self.config)

        runtime.google_client.load_provider_metadata = AsyncMock(return_value={})
        runtime.google_client.load_jwks = AsyncMock(
            return_value={"keys": [{"kid": "google", "kty": "RSA"}]}
        )
        self.assertEqual((await runtime.preflight())["status"], "ready")
        self.assertEqual(
            runtime.migrate(),
            {
                "status": "ok",
                "migration_ledger_version": 1,
                "applied_migration_count": 2,
                "skipped_migration_count": 3,
                "applied_statement_count": 17,
                "latest_migration_version": 5,
            },
        )
        with patch.object(
            repository,
            "apply_migrations",
            side_effect=RuntimeError("postgresql://private:secret@db/private"),
        ):
            with self.assertRaisesRegex(
                ConnectedRuntimeError,
                "connected_migration_failed",
            ) as migration_error:
                runtime.migrate()
        self.assertNotIn("private", repr(migration_error.exception))
        invitation = SimpleNamespace(
            invitation_id="invite-safe",
            workspace_id="workspace-safe",
        )
        with patch.object(
            runtime.bridge,
            "bootstrap_owner_invitation",
            return_value=invitation,
        ) as bootstrap:
            payload = runtime.bootstrap_owner(
                workspace_id="workspace-safe",
                email="owner@example.test",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                idempotency_key="bootstrap-safe",
                operator_service_id="operator-trusted",
            )

        self.assertEqual(
            payload,
            {
                "status": "ok",
                "invitation_id": "invite-safe",
                "workspace_id": "workspace-safe",
            },
        )
        self.assertNotIn("owner@example.test", json.dumps(payload))
        self.assertNotIn("bootstrap-safe", json.dumps(payload))
        bootstrap.assert_called_once()
        with patch.object(
            runtime.bridge,
            "provision_invitation",
            return_value=SimpleNamespace(
                invitation_id="invite-member-safe",
                workspace_id="workspace-safe",
                role="member",
            ),
        ) as provision:
            invitation_payload = runtime.invite_user(
                workspace_id="workspace-safe",
                email="member@example.test",
                role="member",
                invited_by_user_id="owner-safe",
                operator_service_id="operator-trusted",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        self.assertEqual(
            invitation_payload,
            {
                "status": "ok",
                "invitation_id": "invite-member-safe",
                "workspace_id": "workspace-safe",
                "role": "member",
            },
        )
        self.assertNotIn("member@example.test", json.dumps(invitation_payload))
        provision.assert_called_once()
        self.assertEqual(
            provision.call_args.kwargs["operator_service_id"],
            "operator-trusted",
        )
        with patch.object(
            runtime.bridge,
            "revoke_token_session_as_operator",
        ) as revoke:
            revocation_payload = runtime.revoke_token_session(
                token_session_id="oauthsid-safe",
                reason_code="operator_revoked",
                operator_service_id="operator-trusted",
            )
        self.assertEqual(
            revocation_payload,
            {"status": "ok", "token_session_revoked": True},
        )
        self.assertNotIn("oauthsid-safe", json.dumps(revocation_payload))
        self.assertNotIn("operator_revoked", json.dumps(revocation_payload))
        revoke.assert_called_once()
        with self.assertRaisesRegex(
            ConnectedRuntimeError,
            "connected_revocation_authority_invalid",
        ):
            runtime.revoke_token_session(
                token_session_id="oauthsid-safe",
                reason_code="operator_revoked",
            )
        await runtime.aclose()

    async def test_upload_store_readiness_probe_is_atomic_clean_and_fail_closed(self) -> None:
        repository = _FakeRepository()
        http_client = _FakeHttpClient()
        manager = _CountingSessionManager()
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=repository,
            ),
            patch.object(runtime_module.httpx, "AsyncClient", return_value=http_client),
            patch.object(
                runtime_module,
                "create_connected_mcp_application",
                return_value=_fake_application(manager),
            ),
        ):
            runtime = await ConnectedRuntime.compose(self.config)
        runtime.google_client.load_provider_metadata = AsyncMock(return_value={})
        runtime.google_client.load_jwks = AsyncMock(return_value={"keys": [{"kid": "google"}]})

        ready = await runtime.preflight()
        probe_files = list(runtime.config.data_dir.rglob(".formowl-ready-*"))

        self.assertEqual(ready["status"], "ready")
        self.assertTrue(ready["checks"]["upload_store"])
        self.assertEqual(probe_files, [])

        for operation in ("open", "write", "fsync"):
            with self.subTest(operation=operation):
                with patch.object(
                    runtime_module.os,
                    operation,
                    side_effect=PermissionError(f"private-{operation}-detail"),
                ):
                    denied = await runtime.preflight()

                serialized = json.dumps(denied)
                self.assertEqual(denied["status"], "not_ready")
                self.assertFalse(denied["checks"]["upload_store"])
                self.assertNotIn(str(runtime.config.data_dir), serialized)
                self.assertNotIn(f"private-{operation}-detail", serialized)
                self.assertEqual(
                    list(runtime.config.data_dir.rglob(".formowl-ready-*")),
                    [],
                )

        original_close = runtime_module.os.close

        def close_then_fail(descriptor: int) -> None:
            original_close(descriptor)
            raise OSError("private-close-detail")

        close_fault_cleanup_attempts = 0

        def unlink_after_close_fault(path: Path, *args: Any, **kwargs: Any) -> None:
            nonlocal close_fault_cleanup_attempts
            close_fault_cleanup_attempts += 1
            original_unlink(path, *args, **kwargs)

        original_unlink = runtime_module.Path.unlink
        with (
            patch.object(
                runtime_module.os,
                "close",
                side_effect=close_then_fail,
            ),
            patch.object(
                runtime_module.Path,
                "unlink",
                autospec=True,
                side_effect=unlink_after_close_fault,
            ),
        ):
            denied = await runtime.preflight()

        serialized = json.dumps(denied)
        self.assertEqual(close_fault_cleanup_attempts, 1)
        self.assertEqual(list(runtime.config.data_dir.rglob(".formowl-ready-*")), [])
        self.assertEqual(denied["status"], "not_ready")
        self.assertFalse(denied["checks"]["upload_store"])
        self.assertNotIn(str(runtime.config.data_dir), serialized)
        self.assertNotIn("private-close-detail", serialized)

        unlink_attempts = 0

        def fail_first_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
            nonlocal unlink_attempts
            unlink_attempts += 1
            if unlink_attempts == 1:
                raise PermissionError("private-unlink-detail")
            original_unlink(path, *args, **kwargs)

        with patch.object(
            runtime_module.Path,
            "unlink",
            autospec=True,
            side_effect=fail_first_unlink,
        ):
            denied = await runtime.preflight()

        serialized = json.dumps(denied)
        self.assertEqual(denied["status"], "not_ready")
        self.assertFalse(denied["checks"]["upload_store"])
        self.assertNotIn(str(runtime.config.data_dir), serialized)
        self.assertNotIn("private-unlink-detail", serialized)
        self.assertGreaterEqual(unlink_attempts, 2)
        self.assertEqual(list(runtime.config.data_dir.rglob(".formowl-ready-*")), [])
        await runtime.aclose()

    async def test_serve_preflight_blocks_bind_and_ready_path_starts_uvicorn(self) -> None:
        class FakeUvicornConfig:
            calls: list[dict[str, Any]] = []

            def __init__(self, app: Any, **kwargs: Any) -> None:
                self.app = app
                self.kwargs = kwargs
                self.__class__.calls.append(dict(kwargs))

        class FakeUvicornServer:
            instances: list["FakeUvicornServer"] = []

            def __init__(self, config: Any) -> None:
                self.config = config
                self.serve_calls = 0
                self.__class__.instances.append(self)

            async def serve(self) -> None:
                self.serve_calls += 1

        fake_uvicorn = SimpleNamespace(
            Config=FakeUvicornConfig,
            Server=FakeUvicornServer,
        )

        for preflight_result in (
            {"status": "not_ready", "checks": {"database": False}},
            RuntimeError("google-secret-and-private-upstream-detail"),
        ):
            with self.subTest(preflight_result=type(preflight_result).__name__):
                repository = _FakeRepository()
                http_client = _FakeHttpClient()
                manager = _CountingSessionManager()
                with (
                    patch.object(
                        runtime_module.PostgreSQLOAuthRepository,
                        "connect",
                        return_value=repository,
                    ),
                    patch.object(
                        runtime_module.httpx,
                        "AsyncClient",
                        return_value=http_client,
                    ),
                    patch.object(
                        runtime_module,
                        "create_connected_mcp_application",
                        return_value=_fake_application(manager),
                    ),
                ):
                    runtime = await ConnectedRuntime.compose(self.config)
                if isinstance(preflight_result, Exception):
                    runtime.preflight = AsyncMock(side_effect=preflight_result)
                else:
                    runtime.preflight = AsyncMock(return_value=preflight_result)
                before_configs = len(FakeUvicornConfig.calls)
                before_servers = len(FakeUvicornServer.instances)
                with (
                    patch.dict("sys.modules", {"uvicorn": fake_uvicorn}),
                    self.assertRaisesRegex(
                        ConnectedRuntimeError,
                        "connected_preflight_failed",
                    ) as denied,
                ):
                    await runtime.serve()
                self.assertEqual(len(FakeUvicornConfig.calls), before_configs)
                self.assertEqual(len(FakeUvicornServer.instances), before_servers)
                self.assertNotIn("google-secret", repr(denied.exception))
                self.assertEqual(http_client.close_calls, 1)
                self.assertEqual(repository.close_calls, 1)

        stale_items = (
            "column:formowl_audit_log.actor_service_id",
            "constraint:formowl_audit_log:chk_formowl_audit_actor_identity",
        )
        for stale_item in stale_items:
            with self.subTest(stale_item=stale_item):
                repository = _FakeRepository(missing_schema_items={stale_item})
                http_client = _FakeHttpClient()
                manager = _CountingSessionManager()
                with (
                    patch.object(
                        runtime_module.PostgreSQLOAuthRepository,
                        "connect",
                        return_value=repository,
                    ),
                    patch.object(
                        runtime_module.httpx,
                        "AsyncClient",
                        return_value=http_client,
                    ),
                    patch.object(
                        runtime_module,
                        "create_connected_mcp_application",
                        return_value=_fake_application(manager),
                    ),
                ):
                    runtime = await ConnectedRuntime.compose(self.config)
                runtime.google_client.load_provider_metadata = AsyncMock(return_value={})
                runtime.google_client.load_jwks = AsyncMock(
                    return_value={"keys": [{"kid": "google", "kty": "RSA"}]}
                )
                before_configs = len(FakeUvicornConfig.calls)
                before_servers = len(FakeUvicornServer.instances)
                with (
                    patch.dict("sys.modules", {"uvicorn": fake_uvicorn}),
                    self.assertRaisesRegex(
                        ConnectedRuntimeError,
                        "connected_preflight_failed",
                    ),
                ):
                    await runtime.serve()
                self.assertEqual(len(FakeUvicornConfig.calls), before_configs)
                self.assertEqual(len(FakeUvicornServer.instances), before_servers)
                self.assertEqual(http_client.close_calls, 1)
                self.assertEqual(repository.close_calls, 1)

        repository = _FakeRepository()
        http_client = _FakeHttpClient()
        manager = _CountingSessionManager()
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=repository,
            ),
            patch.object(runtime_module.httpx, "AsyncClient", return_value=http_client),
            patch.object(
                runtime_module,
                "create_connected_mcp_application",
                return_value=_fake_application(manager),
            ),
        ):
            runtime = await ConnectedRuntime.compose(self.config)
        runtime.preflight = AsyncMock(
            return_value={"status": "ready", "checks": {"database": True}}
        )
        with patch.dict("sys.modules", {"uvicorn": fake_uvicorn}):
            await runtime.serve()

        self.assertEqual(FakeUvicornServer.instances[-1].serve_calls, 1)
        self.assertFalse(FakeUvicornConfig.calls[-1]["access_log"])
        self.assertFalse(FakeUvicornConfig.calls[-1]["proxy_headers"])
        self.assertEqual(http_client.close_calls, 1)
        self.assertEqual(repository.close_calls, 1)


class ConnectedRuntimeHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        environment = _write_runtime_environment(Path(self.temporary_directory.name))
        config = ConnectedRuntimeConfig.from_env_and_secrets(environment)
        self.repository = _FakeRepository()
        self.http_client = _FakeHttpClient()
        with (
            patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=self.repository,
            ),
            patch.object(
                runtime_module.httpx,
                "AsyncClient",
                return_value=self.http_client,
            ),
        ):
            self.runtime = await ConnectedRuntime.compose(config)
        self.runtime.google_client.load_provider_metadata = AsyncMock(
            return_value={"issuer": "https://accounts.google.com"}
        )
        self.runtime.google_client.load_jwks = AsyncMock(
            return_value={"keys": [{"kid": "google-key", "kty": "RSA"}]}
        )

    async def test_health_ready_exact_path_and_identity_only_tools_are_safe(self) -> None:
        headers = {
            "Host": "attacker.invalid",
            "Forwarded": "host=forwarded.invalid;proto=http",
            "X-Forwarded-Host": "forwarded.invalid",
        }
        mcp_headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
            **headers,
        }
        with TestClient(
            self.runtime.application.app,
            raise_server_exceptions=False,
        ) as client:
            health = client.get("/healthz", headers=headers)
            ready = client.get("/readyz", headers=headers)
            listed = client.post(
                "/mcp",
                headers=mcp_headers,
                json={"jsonrpc": "2.0", "id": "list", "method": "tools/list"},
            )
            slash = client.post(
                "/mcp/",
                headers=mcp_headers,
                json={"jsonrpc": "2.0", "id": "slash", "method": "tools/list"},
                follow_redirects=False,
            )

        self.assertEqual(health.status_code, 200, health.text)
        self.assertEqual(health.json(), {"status": "ok"})
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertEqual(ready.json()["status"], "ready")
        self.assertTrue(all(ready.json()["checks"].values()))
        for response in (health, ready):
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn("attacker.invalid", response.text)
            self.assertNotIn("forwarded.invalid", response.text)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(
            [tool["name"] for tool in listed.json()["result"]["tools"]],
            ["whoami", "open_upload_session"],
        )
        self.assertEqual(slash.status_code, 404)
        self.assertNotIn("location", slash.headers)
        self.assertEqual(self.http_client.close_calls, 1)
        self.assertEqual(self.repository.close_calls, 1)

    async def test_ready_failure_is_generic_and_does_not_leak_dependency_detail(self) -> None:
        self.runtime.google_client.load_provider_metadata = AsyncMock(
            side_effect=RuntimeError("postgresql://private-user:private-pass@db/private")
        )
        with TestClient(
            self.runtime.application.app,
            raise_server_exceptions=False,
        ) as client:
            response = client.get(
                "/readyz",
                headers={"Host": "attacker.invalid", "X-Forwarded-Host": "evil.invalid"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertFalse(response.json()["checks"]["google_oidc"])
        self.assertNotIn("private-user", response.text)
        self.assertNotIn("attacker.invalid", response.text)
        self.assertNotIn("evil.invalid", response.text)

    async def test_ready_upload_probe_failure_is_generic_and_cleans_partial_state(
        self,
    ) -> None:
        with TestClient(
            self.runtime.application.app,
            raise_server_exceptions=False,
        ) as client:
            with patch.object(
                runtime_module.os,
                "write",
                side_effect=OSError("private-upload-store-detail"),
            ):
                response = client.get(
                    "/readyz",
                    headers={
                        "Host": "attacker.invalid",
                        "X-Forwarded-Host": "evil.invalid",
                    },
                )

        payload = response.json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertFalse(payload["checks"]["upload_store"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn(str(self.runtime.config.data_dir), response.text)
        self.assertNotIn("private-upload-store-detail", response.text)
        self.assertNotIn("attacker.invalid", response.text)
        self.assertNotIn("evil.invalid", response.text)
        self.assertEqual(
            list(self.runtime.config.data_dir.rglob(".formowl-ready-*")),
            [],
        )

    async def test_ready_stale_schema_exposes_only_boolean_check(self) -> None:
        self.repository.connection.missing_schema_items.add(
            "column:formowl_audit_log.actor_service_id"
        )
        with TestClient(
            self.runtime.application.app,
            raise_server_exceptions=False,
        ) as client:
            response = client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["checks"]["schema"])
        self.assertNotIn("actor_service_id", response.text)
        self.assertNotIn("information_schema", response.text)
        self.assertNotIn("SELECT", response.text)

    async def test_production_runtime_open_upload_session_persists_governed_state(self) -> None:
        principal = OAuthPrincipal(
            user_id="user_runtime",
            external_identity_id="extid_runtime",
            oauth_client_id="chatgpt_closed_beta",
            token_session_id="oauthsid_runtime",
            scopes=("formowl.use",),
            resource=self.runtime.config.oauth.resource,
        )
        membership = WorkspaceMember(
            user_id="user_runtime",
            workspace_id="workspace_runtime",
            role="owner",
        )
        actor_context = ActorContext(
            user=User(
                user_id="user_runtime",
                display_name="Runtime User",
                status="active",
                created_at="2026-07-14T00:00:00+00:00",
            ),
            session_identity=SessionIdentity(
                session_id="oauthsid_runtime",
                selected_user_id="user_runtime",
                selected_at="2026-07-14T00:00:00+00:00",
                selection_method="google_oidc_oauth",
            ),
            workspace_memberships=[membership],
            current_workspace_id="workspace_runtime",
            current_workspace_role="owner",
            external_identity_id="extid_runtime",
            oauth_client_id="chatgpt_closed_beta",
            oauth_token_session_id="oauthsid_runtime",
            auth_mode="google_oidc_oauth",
            production_authentication=True,
        )
        decisions: list[dict[str, Any]] = []

        with (
            patch.object(
                self.runtime.bridge,
                "authenticate_access_token",
                return_value=principal,
            ),
            patch.object(
                self.runtime.bridge,
                "resolve_actor_context",
                return_value=actor_context,
            ),
            patch.object(
                self.runtime.bridge,
                "record_mcp_authorization_decision",
                side_effect=lambda **values: decisions.append(dict(values)),
            ),
            TestClient(
                self.runtime.application.app,
                raise_server_exceptions=False,
            ) as client,
        ):
            allowed = client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer runtime.token.value",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-03-26",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": "upload-runtime",
                    "method": "tools/call",
                    "params": {
                        "name": "open_upload_session",
                        "arguments": {
                            "intent": "Upload governed mail evidence.",
                            "intended_asset_type": "pst",
                        },
                    },
                },
            )
            cross_workspace = client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer runtime.token.value",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-03-26",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": "upload-cross-workspace",
                    "method": "tools/call",
                    "params": {
                        "name": "open_upload_session",
                        "arguments": {
                            "intent": "Upload governed mail evidence.",
                            "intended_asset_type": "pst",
                            "owner_scope_id": "workspace_other",
                        },
                    },
                },
            )

        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertFalse(allowed.json()["result"]["isError"])
        self.assertEqual(cross_workspace.status_code, 200, cross_workspace.text)
        self.assertTrue(cross_workspace.json()["result"]["isError"])
        sessions = UploadSessionStore(self.runtime.config.data_dir).list()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].actor_user_id, "user_runtime")
        self.assertEqual(sessions[0].session_id, "oauthsid_runtime")
        self.assertEqual(sessions[0].workspace_id, "workspace_runtime")
        self.assertEqual(sessions[0].owner_scope_id, "workspace_runtime")
        upload_audits = [
            audit
            for audit in FileAuditLogStore(self.runtime.config.data_dir).list()
            if audit.action == "upload_session_created"
        ]
        self.assertEqual(len(upload_audits), 1)
        self.assertEqual(upload_audits[0].actor_user_id, "user_runtime")
        self.assertEqual(upload_audits[0].session_id, "oauthsid_runtime")
        self.assertEqual(upload_audits[0].workspace_id, "workspace_runtime")
        self.assertEqual(
            [decision["reason_code"] for decision in decisions],
            ["tool_authorized", "invalid_tool_arguments"],
        )
        rendered = allowed.text + cross_workspace.text + str(decisions)
        self.assertNotIn(str(self.runtime.config.data_dir), rendered)
        self.assertNotIn("runtime.token.value", rendered)


class RemoteFactoryOwnershipTests(unittest.TestCase):
    def test_default_remote_factory_owns_manager_lifespan_once(self) -> None:
        config = SimpleNamespace(
            issuer="https://formowl.example",
            resource="https://formowl.example/mcp",
            scopes=("formowl.use",),
            protected_resource_metadata_url=(
                "https://formowl.example/.well-known/oauth-protected-resource"
            ),
        )
        google_client = object()
        bridge = SimpleNamespace(config=config, google_client=google_client)
        manager = _CountingSessionManager()
        with patch(
            "formowl_gateway.remote.StreamableHTTPSessionManager",
            return_value=manager,
        ):
            bundle = create_connected_mcp_application(
                bridge=bridge,
                config=config,
                google_client=google_client,
                semantic_gateway=SemanticMcpGateway(),
                oauth_route_provider=lambda **_kwargs: [],
                environ={"FORMOWL_AUTH_MODE": "oauth_google"},
            )
        with TestClient(bundle.app):
            pass

        self.assertTrue(bundle.manages_session_manager_lifespan)
        self.assertEqual(manager.enter_calls, 1)
        self.assertEqual(manager.exit_calls, 1)


class ConnectedRuntimeOperatorDirectoryWrapperTests(unittest.TestCase):
    def _runtime(self) -> ConnectedRuntime:
        return ConnectedRuntime(
            config=SimpleNamespace(owner_bootstrap_operator_service_id="operator_trusted"),
            repository=object(),
            http_client=object(),
            google_client=object(),
            bridge=object(),
            application=object(),
        )

    def test_directory_factory_and_all_safe_wrappers_delegate(self) -> None:
        runtime = self._runtime()
        directory = runtime._operator_directory()
        self.assertIs(directory.repository, runtime.repository)
        self.assertEqual(directory.expected_operator_service_id, "operator_trusted")

        fake_directory = Mock()
        fake_directory.lookup_user.return_value = {"status": "ok", "result_count": 1}
        fake_directory.list_users.return_value = {"status": "ok", "result_count": 2}
        fake_directory.remove_workspace_member.return_value = {
            "status": "ok",
            "membership_removed": True,
        }
        fake_directory.restore_workspace_member.return_value = {
            "status": "ok",
            "membership_restored": True,
        }
        fake_directory.lookup_token_session.return_value = {
            "status": "ok",
            "result_count": 1,
        }
        fake_directory.list_token_sessions.return_value = {
            "status": "ok",
            "result_count": 2,
        }
        with patch.object(runtime, "_operator_directory", return_value=fake_directory):
            self.assertEqual(
                runtime.lookup_user(
                    email="owner@example.test",
                    workspace_id="workspace_001",
                    operator_service_id="operator_trusted",
                )["result_count"],
                1,
            )
            self.assertEqual(
                runtime.list_users(
                    workspace_id="workspace_001",
                    operator_service_id="operator_trusted",
                )["result_count"],
                2,
            )
            self.assertTrue(
                runtime.remove_workspace_member(
                    user_id="user_001",
                    workspace_id="workspace_001",
                    operator_service_id="operator_trusted",
                )["membership_removed"]
            )
            self.assertTrue(
                runtime.restore_workspace_member(
                    user_id="user_001",
                    workspace_id="workspace_001",
                    operator_service_id="operator_trusted",
                )["membership_restored"]
            )
            self.assertEqual(
                runtime.lookup_token_session(
                    user_id="user_001",
                    workspace_id="workspace_001",
                    operator_service_id="operator_trusted",
                )["result_count"],
                1,
            )
            self.assertEqual(
                runtime.list_token_sessions(
                    user_id="user_001",
                    workspace_id="workspace_001",
                    operator_service_id="operator_trusted",
                )["result_count"],
                2,
            )

        fake_directory.lookup_user.assert_called_once_with(
            email="owner@example.test",
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
        )
        fake_directory.list_users.assert_called_once()
        fake_directory.remove_workspace_member.assert_called_once_with(
            user_id="user_001",
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
        )
        fake_directory.restore_workspace_member.assert_called_once_with(
            user_id="user_001",
            workspace_id="workspace_001",
            operator_service_id="operator_trusted",
        )
        fake_directory.lookup_token_session.assert_called_once()
        fake_directory.list_token_sessions.assert_called_once()

    def test_wrapper_maps_directory_denial_without_private_detail(self) -> None:
        runtime = self._runtime()
        fake_directory = Mock()
        fake_directory.list_users.side_effect = runtime_module.OperatorDirectoryError(
            "operator_directory_unavailable"
        )
        with (
            patch.object(runtime, "_operator_directory", return_value=fake_directory),
            self.assertRaises(ConnectedRuntimeError) as caught,
        ):
            runtime.list_users(
                workspace_id="workspace_001",
                operator_service_id="operator_trusted",
            )

        self.assertEqual(caught.exception.code, "operator_directory_unavailable")
        self.assertNotIn("database", str(caught.exception))


class _FakeCliRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.close_calls = 0

    def migrate(self) -> dict[str, Any]:
        self.calls.append("migrate")
        return {"status": "ok", "migration_statement_count": 3}

    async def preflight(self) -> dict[str, Any]:
        self.calls.append("preflight")
        return {"status": "ready", "checks": {"runtime": True}}

    def bootstrap_owner(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("bootstrap-owner")
        return {
            "status": "ok",
            "invitation_id": "invite_safe",
            "workspace_id": "workspace_safe",
        }

    def invite_user(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("invite-user")
        return {
            "status": "ok",
            "invitation_id": "invite_safe",
            "workspace_id": "workspace_safe",
            "role": "member",
        }

    def remove_workspace_member(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("remove-workspace-member")
        return {"status": "ok", "membership_removed": True}

    def restore_workspace_member(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("restore-workspace-member")
        return {"status": "ok", "membership_restored": True}

    def revoke_token_session(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("revoke-token-session")
        return {"status": "ok", "token_session_revoked": True}

    def lookup_user(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("lookup-user")
        return {"status": "ok", "result_count": 1, "user": {"user_id": "user_safe"}}

    def list_users(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("list-users")
        return {"status": "ok", "result_count": 1, "users": [{"user_id": "user_safe"}]}

    def lookup_token_session(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("lookup-token-session")
        return {
            "status": "ok",
            "result_count": 1,
            "token_session": {"token_session_id": "oauthsid_safe"},
        }

    def list_token_sessions(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append("list-token-sessions")
        return {
            "status": "ok",
            "result_count": 1,
            "token_sessions": [{"token_session_id": "oauthsid_safe"}],
        }

    async def serve(self) -> None:
        self.calls.append("serve")

    async def aclose(self) -> None:
        self.close_calls += 1


class ConnectedRuntimeCliTests(unittest.TestCase):
    def test_cli_invalid_arbitrary_https_callback_fails_before_external_effects(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = _write_runtime_environment(Path(temporary_directory))
            environment["FORMOWL_CHATGPT_REDIRECT_URI"] = (
                "https://attacker.example/private-callback"
            )
            source = _RecordingSecretSource()
            error_output = StringIO()
            with (
                patch.object(
                    runtime_module.PostgreSQLOAuthRepository,
                    "connect",
                ) as repository_connect,
                patch.object(
                    ConnectedRuntime,
                    "compose",
                    new=AsyncMock(),
                ) as compose,
                patch.object(runtime_module.httpx, "AsyncClient") as http_client,
                patch.object(runtime_module.GoogleOidcClient, "__init__") as google_client,
                patch("subprocess.run") as subprocess_run,
                redirect_stderr(error_output),
            ):
                exit_code = main(
                    ["preflight"],
                    environ=environment,
                    secret_source=source,
                )

        self.assertEqual(exit_code, 1)
        self.assertEqual(source.calls, 1)
        repository_connect.assert_not_called()
        compose.assert_not_awaited()
        http_client.assert_not_called()
        google_client.assert_not_called()
        subprocess_run.assert_not_called()
        payload = json.loads(error_output.getvalue())
        self.assertEqual(
            payload,
            {"error": "connected_oauth_config_invalid", "status": "error"},
        )
        self.assertNotIn("attacker.example", error_output.getvalue())
        self.assertNotIn(temporary_directory, error_output.getvalue())

    def test_cli_discovery_preflight_is_nonzero_with_safe_mode_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = _write_runtime_environment(Path(temporary_directory))
            environment["FORMOWL_CHATGPT_REDIRECT_URI"] = CHATGPT_DISCOVERY_ONLY_REDIRECT_URI
            repository = _FakeRepository()
            http_client = _FakeHttpClient()
            manager = _CountingSessionManager()
            output = StringIO()
            with (
                patch.object(
                    runtime_module.PostgreSQLOAuthRepository,
                    "connect",
                    return_value=repository,
                ),
                patch.object(
                    runtime_module.httpx,
                    "AsyncClient",
                    return_value=http_client,
                ),
                patch.object(
                    runtime_module,
                    "create_connected_mcp_application",
                    return_value=_fake_application(manager),
                ),
                patch.object(
                    runtime_module.GoogleOidcClient,
                    "load_provider_metadata",
                    new=AsyncMock(return_value={}),
                ),
                patch.object(
                    runtime_module.GoogleOidcClient,
                    "load_jwks",
                    new=AsyncMock(return_value={"keys": [{"kid": "google", "kty": "RSA"}]}),
                ),
                redirect_stdout(output),
            ):
                exit_code = main(["preflight"], environ=environment)

        self.assertEqual(exit_code, 1)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "discovery_only")
        self.assertEqual(payload["mode"], "discovery_only")
        self.assertFalse(payload["checks"]["oauth_callback"])
        self.assertTrue(
            all(value for name, value in payload["checks"].items() if name != "oauth_callback")
        )
        self.assertEqual(http_client.close_calls, 1)
        self.assertEqual(repository.close_calls, 1)

    def test_cli_discovery_serve_starts_public_surface(self) -> None:
        class FakeUvicornConfig:
            def __init__(self, app: Any, **kwargs: Any) -> None:
                self.app = app
                self.kwargs = kwargs

        class FakeUvicornServer:
            instances: list["FakeUvicornServer"] = []

            def __init__(self, config: Any) -> None:
                self.config = config
                self.serve_calls = 0
                self.__class__.instances.append(self)

            async def serve(self) -> None:
                self.serve_calls += 1

        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = _write_runtime_environment(Path(temporary_directory))
            environment["FORMOWL_CHATGPT_REDIRECT_URI"] = CHATGPT_DISCOVERY_ONLY_REDIRECT_URI
            repository = _FakeRepository()
            http_client = _FakeHttpClient()
            manager = _CountingSessionManager()
            fake_uvicorn = SimpleNamespace(
                Config=FakeUvicornConfig,
                Server=FakeUvicornServer,
            )
            with (
                patch.object(
                    runtime_module.PostgreSQLOAuthRepository,
                    "connect",
                    return_value=repository,
                ),
                patch.object(
                    runtime_module.httpx,
                    "AsyncClient",
                    return_value=http_client,
                ),
                patch.object(
                    runtime_module,
                    "create_connected_mcp_application",
                    return_value=_fake_application(manager),
                ),
                patch.object(
                    runtime_module.GoogleOidcClient,
                    "load_provider_metadata",
                    new=AsyncMock(return_value={}),
                ),
                patch.object(
                    runtime_module.GoogleOidcClient,
                    "load_jwks",
                    new=AsyncMock(return_value={"keys": [{"kid": "google", "kty": "RSA"}]}),
                ),
                patch.dict("sys.modules", {"uvicorn": fake_uvicorn}),
            ):
                exit_code = main(["serve"], environ=environment)

        self.assertEqual(exit_code, 0)
        self.assertEqual(FakeUvicornServer.instances[-1].serve_calls, 1)
        self.assertEqual(http_client.close_calls, 1)
        self.assertEqual(repository.close_calls, 1)

    def test_cli_dispatches_all_commands_and_closes_runtime(self) -> None:
        cases = [
            (["migrate"], "migrate"),
            (["preflight"], "preflight"),
            (["serve"], "serve"),
            (
                [
                    "bootstrap-owner",
                    "--workspace-id",
                    "workspace_safe",
                    "--email",
                    "owner@example.test",
                    "--expires-at",
                    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    "--idempotency-key",
                    "bootstrap-safe",
                    "--operator-service-id",
                    "operator-safe",
                ],
                "bootstrap-owner",
            ),
            (
                [
                    "invite-user",
                    "--workspace-id",
                    "workspace_safe",
                    "--email",
                    "member@example.test",
                    "--role",
                    "member",
                    "--invited-by-user-id",
                    "owner_safe",
                    "--operator-service-id",
                    "operator-safe",
                    "--expires-at",
                    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                ],
                "invite-user",
            ),
            (
                [
                    "remove-workspace-member",
                    "--user-id",
                    "user_safe",
                    "--workspace-id",
                    "workspace_safe",
                    "--operator-service-id",
                    "operator-safe",
                ],
                "remove-workspace-member",
            ),
            (
                [
                    "restore-workspace-member",
                    "--user-id",
                    "user_safe",
                    "--workspace-id",
                    "workspace_safe",
                    "--operator-service-id",
                    "operator-safe",
                ],
                "restore-workspace-member",
            ),
            (
                [
                    "revoke-token-session",
                    "--token-session-id",
                    "oauthsid_safe",
                    "--reason-code",
                    "operator_revoked",
                    "--operator-service-id",
                    "operator-safe",
                ],
                "revoke-token-session",
            ),
            (
                [
                    "lookup-user",
                    "--email",
                    "owner@example.test",
                    "--workspace-id",
                    "workspace_safe",
                    "--operator-service-id",
                    "operator-safe",
                ],
                "lookup-user",
            ),
            (
                [
                    "list-users",
                    "--workspace-id",
                    "workspace_safe",
                    "--operator-service-id",
                    "operator-safe",
                ],
                "list-users",
            ),
            (
                [
                    "lookup-token-session",
                    "--user-id",
                    "user_safe",
                    "--workspace-id",
                    "workspace_safe",
                    "--operator-service-id",
                    "operator-safe",
                ],
                "lookup-token-session",
            ),
            (
                [
                    "list-token-sessions",
                    "--user-id",
                    "user_safe",
                    "--workspace-id",
                    "workspace_safe",
                    "--operator-service-id",
                    "operator-safe",
                ],
                "list-token-sessions",
            ),
        ]
        for argv, expected_call in cases:
            with self.subTest(command=expected_call):
                fake_runtime = _FakeCliRuntime()
                output = StringIO()
                with (
                    patch.object(
                        ConnectedRuntimeConfig,
                        "from_env_and_secrets",
                        return_value=object(),
                    ),
                    patch.object(
                        ConnectedRuntime,
                        "compose",
                        new=AsyncMock(return_value=fake_runtime),
                    ),
                    redirect_stdout(output),
                ):
                    exit_code = main(argv, environ={})
                self.assertEqual(exit_code, 0)
                self.assertEqual(fake_runtime.calls, [expected_call])
                self.assertEqual(fake_runtime.close_calls, 1)
                if expected_call != "serve":
                    self.assertIn('"status"', output.getvalue())

    def test_cli_failure_output_is_machine_safe(self) -> None:
        error_output = StringIO()
        with (
            patch.object(
                ConnectedRuntimeConfig,
                "from_env_and_secrets",
                side_effect=ConnectedRuntimeError("deployment_secret_file_unavailable"),
            ),
            redirect_stderr(error_output),
        ):
            exit_code = main(["preflight"], environ={})

        self.assertEqual(exit_code, 1)
        payload = json.loads(error_output.getvalue())
        self.assertEqual(payload["error"], "deployment_secret_file_unavailable")
        self.assertNotIn("path", error_output.getvalue())
        self.assertNotIn("secret-value", error_output.getvalue())

    def test_cli_rejects_invalid_bootstrap_timestamp_without_leak(self) -> None:
        fake_runtime = _FakeCliRuntime()
        error_output = StringIO()
        with (
            patch.object(
                ConnectedRuntimeConfig,
                "from_env_and_secrets",
                return_value=object(),
            ),
            patch.object(
                ConnectedRuntime,
                "compose",
                new=AsyncMock(return_value=fake_runtime),
            ),
            redirect_stderr(error_output),
        ):
            exit_code = main(
                [
                    "bootstrap-owner",
                    "--workspace-id",
                    "workspace-safe",
                    "--email",
                    "owner@example.test",
                    "--expires-at",
                    "invalid-private-timestamp",
                    "--idempotency-key",
                    "bootstrap-safe",
                    "--operator-service-id",
                    "operator-safe",
                ],
                environ={},
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(fake_runtime.calls, [])
        self.assertEqual(fake_runtime.close_calls, 1)
        self.assertEqual(
            json.loads(error_output.getvalue())["error"], "connected_timestamp_invalid"
        )
        self.assertNotIn("invalid-private-timestamp", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
