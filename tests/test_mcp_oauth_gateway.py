from __future__ import annotations

import asyncio
import copy
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
import gc
import inspect
import json
import logging
from types import SimpleNamespace
from typing import Any, Mapping
import unittest
from unittest.mock import patch
import warnings

import _paths  # noqa: F401

try:
    import jsonschema
    from formowl_contract import ContractValidationError
    from mcp.shared.version import LATEST_PROTOCOL_VERSION
    from starlette.testclient import TestClient

    from formowl_gateway.remote import (
        ConnectedMcpApplication,
        ExactMcpPathApp,
        SafeExceptionMiddleware,
        _SessionManagerLifespan,
        _canonical_metadata_url,
        _current_principal,
        _current_request_id,
        _new_safe_id,
        _no_store_headers,
        _required_scope,
        _safe_denial,
        _successful_tool_result,
        _tool_descriptor,
        _validate_connected_dependencies,
        build_remote_tool_descriptors,
        build_www_authenticate_challenge,
        create_connected_mcp_application,
        create_connected_mcp_asgi_app,
        remote_main,
        run_connected_mcp_application,
    )
    from formowl_gateway.semantic import SemanticMcpGateway
except ModuleNotFoundError as exc:  # stale local dev images may predate issue #20 deps
    if exc.name not in {"mcp", "starlette", "httpx", "jsonschema"}:
        raise
    TestClient = None  # type: ignore[assignment,misc]
    ConnectedMcpApplication = Any  # type: ignore[assignment,misc]
    LATEST_PROTOCOL_VERSION = "2025-11-25"
    _IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _IMPORT_ERROR = None


def _now() -> datetime:
    return datetime(2026, 7, 12, 8, 0, 0, tzinfo=timezone.utc)


_UNSET = object()


class _DetachedTimezone(tzinfo):
    def utcoffset(self, value: datetime | None):
        del value
        return None


@dataclass(frozen=True)
class _Config:
    issuer: str = "https://formowl.example"
    resource: str = "https://formowl.example/mcp"
    scopes: tuple[str, ...] = ("formowl.use",)
    chatgpt_callback_mode: str = "production_exact"

    @property
    def protected_resource_metadata_url(self) -> str:
        return f"{self.issuer}/.well-known/oauth-protected-resource"


@dataclass(frozen=True)
class _Principal:
    user_id: str = "user_beta"
    external_identity_id: str = "ext_google_beta"
    oauth_client_id: str = "chatgpt_client"
    token_session_id: str = "oauthsid_beta"
    scopes: tuple[str, ...] = ("formowl.use",)
    resource: str = "https://formowl.example/mcp"


class _Denied(Exception):
    def __init__(self, error: str, reason_code: str, http_status: int) -> None:
        self.error = error
        self.reason_code = reason_code
        self.http_status = http_status
        super().__init__(reason_code)


class _MalformedDenial(Exception):
    def __init__(self, *, error: Any, reason_code: Any, http_status: Any) -> None:
        self.error = error
        self.reason_code = reason_code
        self.http_status = http_status
        super().__init__("raw-malformed-denial-secret")


class _NonJsonPayload:
    def __init__(self) -> None:
        self.raw_value = "raw-custom-object-secret"


class _FakeBridge:
    def __init__(self, config: _Config, google_client: object) -> None:
        self.config = config
        self.google_client = google_client
        self.principal = _Principal(resource=config.resource)
        self.authenticate_calls = 0
        self.resolve_calls = 0
        self.decisions: list[dict[str, Any]] = []
        self.http_denials: list[dict[str, Any]] = []
        self.resolve_denial: _Denied | None = None
        self.current_workspace_role = "member"
        self.active_grants: list[Any] = []
        self.fail_allowed_audit = False
        self.fail_denied_audit = False
        self.fail_http_denial_audit = False
        self.actor_context_session_identity: Any = _UNSET
        self.actor_context_token_session_id: Any = _UNSET
        self.omit_actor_context_session_identity = False

    def authenticate_access_token(
        self,
        raw_token: str,
        *,
        required_scope: str,
        resource: str,
        now: datetime,
    ) -> _Principal:
        self.authenticate_calls += 1
        if raw_token == "expired.jwt.value":
            raise _Denied("invalid_token", "token_expired", 401)
        if raw_token == "revoked.jwt.value":
            raise _Denied("invalid_token", "token_session_revoked", 401)
        if raw_token == "identity-disabled.jwt.value":
            raise _Denied("invalid_token", "external_identity_disabled", 401)
        if raw_token == "user-disabled.jwt.value":
            raise _Denied("invalid_token", "formowl_user_disabled", 401)
        if raw_token == "client-revoked.jwt.value":
            raise _Denied("invalid_token", "client_authorization_revoked", 401)
        if raw_token == "scope-insufficient.jwt.value":
            raise _Denied("insufficient_scope", "required_scope_missing", 403)
        if raw_token != "valid.jwt.value":
            raise _Denied("invalid_token", "token_signature_invalid", 401)
        if required_scope != "formowl.use" or resource != self.config.resource:
            raise AssertionError("gateway passed a non-canonical OAuth target")
        if now != _now():
            raise AssertionError("gateway clock mismatch")
        return self.principal

    def resolve_actor_context(
        self,
        principal: _Principal,
        *,
        now: datetime,
    ) -> SimpleNamespace:
        self.resolve_calls += 1
        if self.resolve_denial is not None:
            raise self.resolve_denial
        if principal != self.principal or now != _now():
            raise AssertionError("gateway did not pass the request-scoped principal")
        user = SimpleNamespace(user_id=principal.user_id, display_name="Beta User")
        membership = SimpleNamespace(
            user_id=principal.user_id,
            workspace_id="workspace_beta",
            role=self.current_workspace_role,
        )
        session_identity = (
            SimpleNamespace(
                session_id=principal.token_session_id,
                selected_user_id=principal.user_id,
                selection_method="google_oidc_oauth",
            )
            if self.actor_context_session_identity is _UNSET
            else self.actor_context_session_identity
        )
        token_session_id = (
            principal.token_session_id
            if self.actor_context_token_session_id is _UNSET
            else self.actor_context_token_session_id
        )
        context_values = {
            "user": user,
            "workspace_memberships": [membership],
            "active_grants": list(self.active_grants),
            "pending_access_requests": [],
            "current_workspace_id": "workspace_beta",
            "current_workspace_role": self.current_workspace_role,
            "external_identity_id": principal.external_identity_id,
            "oauth_client_id": principal.oauth_client_id,
            "oauth_token_session_id": token_session_id,
            "auth_mode": "google_oidc_oauth",
            "production_authentication": True,
        }
        if not self.omit_actor_context_session_identity:
            context_values["session_identity"] = session_identity
        return SimpleNamespace(
            **context_values,
        )

    def record_mcp_authorization_decision(self, **values: Any) -> dict[str, Any]:
        if (values["allowed"] and self.fail_allowed_audit) or (
            not values["allowed"] and self.fail_denied_audit
        ):
            raise RuntimeError("synthetic audit failure with secret-bearer-value")
        self.decisions.append(dict(values))
        return {"status": "ok"}

    def record_mcp_http_authentication_denial(self, **values: Any) -> dict[str, Any]:
        raw_token = values.pop("raw_token")
        if self.fail_http_denial_audit:
            raise RuntimeError("synthetic audit failure with secret-bearer-value")
        if values["required_scope"] != "formowl.use" or values["resource"] != self.config.resource:
            raise AssertionError("gateway passed a non-canonical denial audit target")
        values["raw_token_present"] = raw_token is not None
        self.http_denials.append(dict(values))
        return {"status": "ok"}

    def whoami_payload(self, actor_context: SimpleNamespace) -> dict[str, Any]:
        return {
            "user_id": actor_context.user.user_id,
            "display_name": actor_context.user.display_name,
            "current_workspace": {
                "workspace_id": actor_context.current_workspace_id,
                "role": actor_context.current_workspace_role,
            },
            "auth_mode": "google_oidc_oauth",
        }


def _request(
    method: str, request_id: str, params: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = dict(params)
    return payload


def _initialize_request() -> dict[str, Any]:
    return _request(
        "initialize",
        "initialize_1",
        {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "formowl-gateway-test", "version": "1.0"},
        },
    )


def _mcp_headers(*, bearer: str | None = None, host: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
    }
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    if host is not None:
        headers["Host"] = host
    return headers


@unittest.skipIf(_IMPORT_ERROR is not None, f"issue #20 dependencies unavailable: {_IMPORT_ERROR}")
class RemoteMcpDescriptorTests(unittest.TestCase):
    def test_descriptors_have_oauth_output_schema_and_complete_annotations(self) -> None:
        tools = build_remote_tool_descriptors(required_scope="formowl.use")

        self.assertEqual({tool.name for tool in tools}, {"whoami", "open_upload_session"})
        for tool in tools:
            with self.subTest(tool=tool.name):
                payload = tool.model_dump(by_alias=True, exclude_none=True)
                self.assertTrue(payload["title"])
                self.assertEqual(
                    payload["securitySchemes"],
                    [{"type": "oauth2", "scopes": ["formowl.use"]}],
                )
                self.assertEqual(payload["_meta"]["securitySchemes"], payload["securitySchemes"])
                self.assertIn("inputSchema", payload)
                self.assertIn("outputSchema", payload)
                self.assertEqual(
                    set(payload["annotations"]),
                    {
                        "title",
                        "readOnlyHint",
                        "destructiveHint",
                        "idempotentHint",
                        "openWorldHint",
                    },
                )
                self.assertFalse(payload["annotations"]["destructiveHint"])
                self.assertFalse(payload["annotations"]["openWorldHint"])
                self.assertEqual(
                    payload["annotations"]["readOnlyHint"],
                    payload["annotations"]["idempotentHint"],
                )
        for kwargs in (
            {"required_scope": "other.scope"},
            {
                "required_scope": "formowl.use",
                "enabled_tool_names": {"open_upload_session"},
            },
            {
                "required_scope": "formowl.use",
                "enabled_tool_names": {"whoami", "unknown_tool"},
            },
            {
                "required_scope": "formowl.use",
                "enabled_tool_names": {"whoami", "query_mail_evidence"},
            },
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(Exception):
                build_remote_tool_descriptors(**kwargs)

    def test_challenge_is_canonical_and_rejects_header_injection(self) -> None:
        challenge = build_www_authenticate_challenge(
            "https://formowl.example/.well-known/oauth-protected-resource",
            error="invalid_token",
            error_description="Authentication required.",
        )

        self.assertEqual(
            challenge,
            'Bearer resource_metadata="https://formowl.example/.well-known/'
            'oauth-protected-resource", error="invalid_token", '
            'error_description="Authentication required."',
        )
        for value in (
            "https://formowl.example/meta\r\nX-Evil: yes",
            "https://user:pass@formowl.example/meta",
            "https://formowl.example/meta?redirect=https://evil.example",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_www_authenticate_challenge(
                    value,
                    error="invalid_token",
                    error_description="Authentication required.",
                )


@unittest.skipIf(_IMPORT_ERROR is not None, f"issue #20 dependencies unavailable: {_IMPORT_ERROR}")
class RemoteMcpHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _Config()
        self.google_client = object()
        self.bridge = _FakeBridge(self.config, self.google_client)
        self.handler_calls: list[dict[str, Any]] = []
        self.fail_handler = False

        def upload_handler(arguments: dict[str, Any]) -> dict[str, Any]:
            if not self.bridge.decisions or not self.bridge.decisions[-1]["allowed"]:
                raise AssertionError("authorization audit did not precede the handler")
            if self.fail_handler:
                raise RuntimeError("secret-bearer-value backend failure")
            self.handler_calls.append(dict(arguments))
            return {
                "status": "ok",
                "upload_session_id": "upload_beta",
                "next_required_action": "upload_file",
            }

        self.semantic_gateway = SemanticMcpGateway(upload_session_handler=upload_handler)
        self.bundle = create_connected_mcp_application(
            bridge=self.bridge,
            config=self.config,
            google_client=self.google_client,
            semantic_gateway=self.semantic_gateway,
            oauth_route_provider=lambda **_kwargs: [],
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )

    def test_initialize_and_tool_list_are_public_on_exact_mcp_path(self) -> None:
        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            initialized = client.post("/mcp", json=_initialize_request(), headers=_mcp_headers())
            listed = client.post(
                "/mcp",
                json=_request("tools/list", "list_1"),
                headers=_mcp_headers(),
            )
            slash = client.post(
                "/mcp/",
                json=_request("tools/list", "list_slash"),
                headers=_mcp_headers(),
                follow_redirects=False,
            )

        self.assertEqual(initialized.status_code, 200, initialized.text)
        self.assertEqual(listed.status_code, 200, listed.text)
        names = {tool["name"] for tool in listed.json()["result"]["tools"]}
        self.assertEqual(names, {"whoami", "open_upload_session"})
        self.assertEqual(slash.status_code, 404)
        self.assertNotIn("location", slash.headers)

    def test_discovery_only_lists_tools_and_challenges_without_auth_or_audit(self) -> None:
        config = _Config(chatgpt_callback_mode="discovery_only")
        google_client = object()
        bridge = _FakeBridge(config, google_client)
        handler_calls: list[dict[str, Any]] = []
        bundle = create_connected_mcp_application(
            bridge=bridge,
            config=config,
            google_client=google_client,
            semantic_gateway=SemanticMcpGateway(
                upload_session_handler=lambda arguments: handler_calls.append(dict(arguments))
                or {"status": "ok"}
            ),
            oauth_route_provider=lambda **_kwargs: [],
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )

        with TestClient(bundle.app, raise_server_exceptions=False) as client:
            initialized = client.post(
                "/mcp",
                json=_initialize_request(),
                headers=_mcp_headers(bearer="ignored.discovery.token"),
            )
            listed = client.post(
                "/mcp",
                json=_request("tools/list", "discovery_list"),
                headers=_mcp_headers(bearer="ignored.discovery.token"),
            )
            protected = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "discovery_whoami",
                    {"name": "whoami", "arguments": {}},
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        self.assertEqual(initialized.status_code, 200, initialized.text)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(
            {tool["name"] for tool in listed.json()["result"]["tools"]},
            {"whoami", "open_upload_session"},
        )
        self.assertEqual(protected.status_code, 200, protected.text)
        result = protected.json()["result"]
        _assert_error_result_has_no_structured_content(
            self,
            result,
            expected_message="Authentication required.",
        )
        challenge = result["_meta"]["mcp/www_authenticate"][0]
        self.assertIn(config.protected_resource_metadata_url, challenge)
        self.assertEqual(bridge.authenticate_calls, 0)
        self.assertEqual(bridge.resolve_calls, 0)
        self.assertEqual(bridge.decisions, [])
        self.assertEqual(bridge.http_denials, [])
        self.assertEqual(handler_calls, [])

    def test_missing_bearer_returns_mcp_tool_error_with_canonical_challenge(self) -> None:
        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "whoami_missing",
                    {"name": "whoami", "arguments": {}},
                ),
                headers=_mcp_headers(host="attacker.invalid"),
            )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        _assert_error_result_has_no_structured_content(
            self,
            result,
            expected_message="Authentication required.",
        )
        challenge = result["_meta"]["mcp/www_authenticate"][0]
        self.assertIn(self.config.protected_resource_metadata_url, challenge)
        self.assertNotIn("attacker.invalid", challenge)
        self.assertNotIn("location", response.headers)
        self.assertEqual(self.handler_calls, [])
        self.assertEqual(self.bridge.decisions[-1]["reason_code"], "authentication_required")
        self.assertEqual(self.bridge.http_denials, [])

    def test_invalid_or_multiple_bearer_is_http_denial_without_token_echo(self) -> None:
        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            invalid = client.post(
                "/mcp",
                json=_request("tools/list", "invalid_bearer"),
                headers=_mcp_headers(bearer="secret-bearer-value"),
            )
            duplicate = client.post(
                "/mcp",
                json=_request("tools/list", "duplicate_bearer"),
                headers=[
                    ("Accept", "application/json, text/event-stream"),
                    ("MCP-Protocol-Version", LATEST_PROTOCOL_VERSION),
                    ("Authorization", "Bearer valid.jwt.value"),
                    ("Authorization", "Bearer secret-bearer-value"),
                ],
            )
            expired = client.post(
                "/mcp",
                json=_request("tools/list", "expired_bearer"),
                headers=_mcp_headers(bearer="expired.jwt.value"),
            )
            revoked = client.post(
                "/mcp",
                json=_request("tools/list", "revoked_bearer"),
                headers=_mcp_headers(bearer="revoked.jwt.value"),
            )
            identity_disabled = client.post(
                "/mcp",
                json=_request("tools/list", "identity_disabled_bearer"),
                headers=_mcp_headers(bearer="identity-disabled.jwt.value"),
            )
            user_disabled = client.post(
                "/mcp",
                json=_request("tools/list", "user_disabled_bearer"),
                headers=_mcp_headers(bearer="user-disabled.jwt.value"),
            )
            client_revoked = client.post(
                "/mcp",
                json=_request("tools/list", "client_revoked_bearer"),
                headers=_mcp_headers(bearer="client-revoked.jwt.value"),
            )
            insufficient_scope = client.post(
                "/mcp",
                json=_request("tools/list", "insufficient_scope_bearer"),
                headers=_mcp_headers(bearer="scope-insufficient.jwt.value"),
            )

        unauthorized_responses = (
            invalid,
            duplicate,
            expired,
            revoked,
            identity_disabled,
            user_disabled,
            client_revoked,
        )
        for response in unauthorized_responses:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"error": "invalid_token"})
            self.assertIn(
                self.config.protected_resource_metadata_url, response.headers["www-authenticate"]
            )
            self.assertIn("invalid_token", response.headers["www-authenticate"])
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["pragma"], "no-cache")
            self.assertNotIn("secret-bearer-value", response.text)
            self.assertNotIn("secret-bearer-value", response.headers["www-authenticate"])
            self.assertNotIn("expired.jwt.value", response.text)
        self.assertEqual(insufficient_scope.status_code, 403)
        self.assertEqual(insufficient_scope.json(), {"error": "insufficient_scope"})
        self.assertIn(
            self.config.protected_resource_metadata_url,
            insufficient_scope.headers["www-authenticate"],
        )
        self.assertIn("insufficient_scope", insufficient_scope.headers["www-authenticate"])
        self.assertEqual(insufficient_scope.headers["cache-control"], "no-store")
        self.assertEqual(insufficient_scope.headers["pragma"], "no-cache")
        public_rendered = "".join(
            response.text + response.headers["www-authenticate"]
            for response in (*unauthorized_responses, insufficient_scope)
        )
        for internal_reason in (
            "token_signature_invalid",
            "authorization_header_invalid",
            "token_expired",
            "token_session_revoked",
            "external_identity_disabled",
            "formowl_user_disabled",
            "client_authorization_revoked",
            "required_scope_missing",
        ):
            self.assertNotIn(internal_reason, public_rendered)
        self.assertEqual(
            [item["reason_code"] for item in self.bridge.http_denials],
            [
                "token_signature_invalid",
                "authorization_header_invalid",
                "token_expired",
                "token_session_revoked",
                "external_identity_disabled",
                "formowl_user_disabled",
                "client_authorization_revoked",
                "required_scope_missing",
            ],
        )
        self.assertTrue(
            all(
                set(item)
                == {
                    "request_id",
                    "reason_code",
                    "required_scope",
                    "resource",
                    "now",
                    "raw_token_present",
                }
                for item in self.bridge.http_denials
            )
        )
        self.assertEqual(
            [item["raw_token_present"] for item in self.bridge.http_denials],
            [True, False, True, True, True, True, True, True],
        )
        self.assertNotIn(
            "secret-bearer-value",
            str(self.bridge.http_denials),
        )

    def test_http_denial_audit_failure_fails_closed_without_token_echo(self) -> None:
        self.bridge.fail_http_denial_audit = True
        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json=_request("tools/list", "audit_failure"),
                headers=_mcp_headers(bearer="secret-bearer-value"),
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "invalid_token"})
        self.assertIn(
            self.config.protected_resource_metadata_url,
            response.headers["www-authenticate"],
        )
        self.assertIn("invalid_token", response.headers["www-authenticate"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertNotIn("authentication_audit_failed", response.text)
        self.assertNotIn("authentication_audit_failed", response.headers["www-authenticate"])
        self.assertNotIn("server_error", response.text)
        self.assertNotIn("secret-bearer-value", response.text)
        self.assertNotIn("secret-bearer-value", response.headers["www-authenticate"])
        self.assertEqual(self.handler_calls, [])
        self.assertEqual(self.bridge.http_denials, [])

    def test_valid_bearer_resolves_fresh_actor_context_for_every_tool_call(self) -> None:
        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            first = client.post(
                "/mcp",
                json=_request("tools/call", "whoami_1", {"name": "whoami", "arguments": {}}),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )
            second = client.post(
                "/mcp",
                json=_request("tools/call", "whoami_2", {"name": "whoami", "arguments": {}}),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        payload = first.json()["result"]["structuredContent"]
        whoami_schema = next(
            tool.outputSchema
            for tool in build_remote_tool_descriptors(required_scope="formowl.use")
            if tool.name == "whoami"
        )
        jsonschema.validate(instance=payload, schema=whoami_schema)
        self.assertEqual(payload["user_id"], "user_beta")
        self.assertEqual(payload["current_workspace"]["workspace_id"], "workspace_beta")
        self.assertNotIn("external_identity_id", payload)
        self.assertNotIn("oauth_client_id", payload)
        self.assertNotIn("token_session_id", payload)
        self.assertEqual(self.bridge.authenticate_calls, 2)
        self.assertEqual(self.bridge.resolve_calls, 2)

    def test_nested_session_identity_tampering_fails_closed_before_handler(self) -> None:
        valid_nested = SimpleNamespace(
            session_id=self.bridge.principal.token_session_id,
            selected_user_id=self.bridge.principal.user_id,
            selection_method="google_oidc_oauth",
        )
        cases = {
            "nested_session_id": {
                "session_identity": SimpleNamespace(
                    session_id="oauthsid_forged",
                    selected_user_id=self.bridge.principal.user_id,
                    selection_method="google_oidc_oauth",
                ),
                "top_level_token_session_id": _UNSET,
                "omit_session_identity": False,
                "forged_values": ("oauthsid_forged",),
            },
            "nested_selected_user_id": {
                "session_identity": SimpleNamespace(
                    session_id=self.bridge.principal.token_session_id,
                    selected_user_id="user_forged",
                    selection_method="google_oidc_oauth",
                ),
                "top_level_token_session_id": _UNSET,
                "omit_session_identity": False,
                "forged_values": ("user_forged",),
            },
            "nested_selection_method": {
                "session_identity": SimpleNamespace(
                    session_id=self.bridge.principal.token_session_id,
                    selected_user_id=self.bridge.principal.user_id,
                    selection_method="manual_trusted_internal",
                ),
                "top_level_token_session_id": _UNSET,
                "omit_session_identity": False,
                "forged_values": ("manual_trusted_internal",),
            },
            "missing_session_identity": {
                "session_identity": _UNSET,
                "top_level_token_session_id": _UNSET,
                "omit_session_identity": True,
                "forged_values": (),
            },
            "none_session_identity": {
                "session_identity": None,
                "top_level_token_session_id": _UNSET,
                "omit_session_identity": False,
                "forged_values": (),
            },
            "top_level_vs_nested_session_id": {
                "session_identity": valid_nested,
                "top_level_token_session_id": "oauthsid_top_level_forged",
                "omit_session_identity": False,
                "forged_values": ("oauthsid_top_level_forged",),
            },
        }
        upload_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }

        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            for case_index, (name, case) in enumerate(cases.items()):
                with self.subTest(name=name):
                    self.bridge.actor_context_session_identity = case["session_identity"]
                    self.bridge.actor_context_token_session_id = case["top_level_token_session_id"]
                    self.bridge.omit_actor_context_session_identity = case["omit_session_identity"]
                    self.bridge.decisions.clear()
                    self.bridge.http_denials.clear()
                    self.handler_calls.clear()
                    before = json.dumps(
                        {
                            "active_grants": self.bridge.active_grants,
                            "http_denials": self.bridge.http_denials,
                            "handler_calls": self.handler_calls,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")

                    response = client.post(
                        "/mcp",
                        json=_request(
                            "tools/call",
                            f"session_identity_{case_index}",
                            {
                                "name": "open_upload_session",
                                "arguments": upload_arguments,
                            },
                        ),
                        headers=_mcp_headers(bearer="valid.jwt.value"),
                    )

                    self.assertEqual(response.status_code, 200, response.text)
                    result = response.json()["result"]
                    _assert_error_result_has_no_structured_content(
                        self,
                        result,
                        expected_message="Authentication required.",
                    )
                    self.assertIn(
                        "invalid_token",
                        result["_meta"]["mcp/www_authenticate"][0],
                    )
                    for forged_value in case["forged_values"]:
                        self.assertNotIn(forged_value, response.text)
                    self.assertEqual(self.handler_calls, [])
                    self.assertEqual(self.bridge.http_denials, [])
                    self.assertEqual(len(self.bridge.decisions), 1)
                    decision = self.bridge.decisions[0]
                    self.assertFalse(decision["allowed"])
                    self.assertEqual(
                        decision["reason_code"],
                        "authorization_header_invalid",
                    )
                    self.assertNotEqual(decision["reason_code"], "tool_authorized")
                    after = json.dumps(
                        {
                            "active_grants": self.bridge.active_grants,
                            "http_denials": self.bridge.http_denials,
                            "handler_calls": self.handler_calls,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    self.assertEqual(after, before)

    def test_closed_tool_policy_allows_only_declared_roles_without_grants(self) -> None:
        policies = self.bundle.dispatcher.tool_policies
        self.assertEqual(set(policies), {"whoami", "open_upload_session"})
        self.assertEqual(
            policies["whoami"].allowed_roles,
            frozenset({"owner", "member", "viewer"}),
        )
        self.assertEqual(
            policies["open_upload_session"].allowed_roles,
            frozenset({"owner", "member"}),
        )
        self.assertFalse(policies["whoami"].requires_grant)
        self.assertFalse(policies["open_upload_session"].requires_grant)

        upload_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }
        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            for role in ("owner", "member", "viewer"):
                self.bridge.current_workspace_role = role
                response = client.post(
                    "/mcp",
                    json=_request(
                        "tools/call",
                        f"whoami_{role}",
                        {"name": "whoami", "arguments": {}},
                    ),
                    headers=_mcp_headers(bearer="valid.jwt.value"),
                )
                result = response.json()["result"]
                self.assertFalse(result["isError"], response.text)
                self.assertEqual(
                    result["structuredContent"]["current_workspace"]["role"],
                    role,
                )

            for role in ("owner", "member"):
                self.bridge.current_workspace_role = role
                response = client.post(
                    "/mcp",
                    json=_request(
                        "tools/call",
                        f"upload_{role}",
                        {"name": "open_upload_session", "arguments": upload_arguments},
                    ),
                    headers=_mcp_headers(bearer="valid.jwt.value"),
                )
                self.assertFalse(response.json()["result"]["isError"], response.text)

        self.assertEqual(len(self.handler_calls), 2)
        self.assertEqual(len(self.bridge.decisions), 5)
        self.assertTrue(all(decision["allowed"] for decision in self.bridge.decisions))
        self.assertTrue(
            all(decision["reason_code"] == "tool_authorized" for decision in self.bridge.decisions)
        )

    def test_viewer_upload_grants_cannot_elevate_and_denial_is_audited(self) -> None:
        self.bridge.current_workspace_role = "viewer"
        grant_cases = {
            "matching_active": SimpleNamespace(
                grant_id="grant_matching_active",
                grantee_user_id="user_beta",
                scope_type="workspace",
                scope_id="workspace_beta",
                permission="upload",
                expires_at="2026-07-13T08:00:00+00:00",
                revoked_at=None,
            ),
            "expired": SimpleNamespace(
                grant_id="grant_expired",
                grantee_user_id="user_beta",
                scope_type="workspace",
                scope_id="workspace_beta",
                permission="upload",
                expires_at="2026-07-11T08:00:00+00:00",
                revoked_at=None,
            ),
            "revoked": SimpleNamespace(
                grant_id="grant_revoked",
                grantee_user_id="user_beta",
                scope_type="workspace",
                scope_id="workspace_beta",
                permission="upload",
                expires_at="2026-07-13T08:00:00+00:00",
                revoked_at="2026-07-12T07:00:00+00:00",
            ),
            "unrelated": SimpleNamespace(
                grant_id="grant_unrelated",
                grantee_user_id="user_beta",
                scope_type="workspace",
                scope_id="workspace_other",
                permission="upload",
                expires_at="2026-07-13T08:00:00+00:00",
                revoked_at=None,
            ),
        }
        responses = []
        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            for name, grant in grant_cases.items():
                self.bridge.active_grants = [grant]
                responses.append(
                    client.post(
                        "/mcp",
                        json=_request(
                            "tools/call",
                            f"viewer_upload_{name}",
                            {
                                "name": "open_upload_session",
                                "arguments": {
                                    "intent": "Upload governed mail evidence.",
                                    "intended_asset_type": "pst",
                                },
                            },
                        ),
                        headers=_mcp_headers(bearer="valid.jwt.value"),
                    )
                )

        self.assertEqual(self.handler_calls, [])
        self.assertEqual(len(self.bridge.decisions), len(grant_cases))
        for response, decision in zip(responses, self.bridge.decisions, strict=True):
            result = response.json()["result"]
            result_text = repr(result)
            _assert_error_result_has_no_structured_content(
                self,
                result,
                expected_message="Authorization is insufficient.",
            )
            self.assertIn(
                "insufficient_scope",
                result["_meta"]["mcp/www_authenticate"][0],
            )
            self.assertNotIn("viewer", result_text)
            self.assertNotIn("grant_", result_text)
            self.assertNotIn("workspace_role_forbidden", result_text)
            self.assertFalse(decision["allowed"])
            self.assertEqual(decision["reason_code"], "workspace_role_forbidden")
            self.assertEqual(decision["tool_name"], "open_upload_session")
            self.assertEqual(decision["workspace_id"], "workspace_beta")
            self.assertEqual(decision["principal"], self.bridge.principal)
            self.assertRegex(decision["request_id"], r"^mcp_req_[0-9a-f]{32}$")
            self.assertRegex(decision["tool_call_id"], r"^mcp_call_[0-9a-f]{32}$")

    def test_viewer_denial_audit_failure_blocks_upload_handler_and_success(self) -> None:
        self.bridge.current_workspace_role = "viewer"
        self.bridge.active_grants = [
            SimpleNamespace(
                grant_id="grant_matching_active",
                grantee_user_id="user_beta",
                scope_type="workspace",
                scope_id="workspace_beta",
                permission="upload",
            )
        ]
        self.bridge.fail_denied_audit = True

        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "viewer_audit_failure",
                    {
                        "name": "open_upload_session",
                        "arguments": {
                            "intent": "Upload governed mail evidence.",
                            "intended_asset_type": "pst",
                        },
                    },
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        _assert_error_result_has_no_structured_content(
            self,
            response.json()["result"],
            expected_message="The FormOwl authorization decision could not be recorded.",
        )
        self.assertEqual(self.handler_calls, [])
        self.assertEqual(self.bridge.decisions, [])
        result_text = repr(response.json()["result"])
        self.assertNotIn("viewer", result_text)
        self.assertNotIn("grant_matching_active", result_text)
        self.assertNotIn("secret-bearer-value", result_text)

    def test_unknown_tool_denial_audit_failure_returns_safe_server_error(self) -> None:
        self.bridge.fail_denied_audit = True

        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "audit_failure_unsupported",
                    {"name": "unknown_backend_tool", "arguments": {}},
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        result = response.json()["result"]
        _assert_error_result_has_no_structured_content(
            self,
            result,
            expected_message="The FormOwl authorization decision could not be recorded.",
        )
        self.assertNotIn("_meta", result)
        self.assertEqual(self.handler_calls, [])
        self.assertEqual(self.bridge.decisions, [])
        self.assertNotIn("unknown_backend_tool", response.text)
        self.assertNotIn("The requested FormOwl tool is unavailable.", response.text)
        self.assertNotIn("secret-bearer-value", response.text)

    def test_unknown_tool_name_is_redacted_from_sdk_logs_before_dispatch(self) -> None:
        secret_tool_name = "access_token=private-marker"
        records: list[logging.LogRecord] = []

        class Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        root_logger = logging.getLogger()
        handler = Handler()
        root_logger.addHandler(handler)
        try:
            with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/mcp",
                    json=_request(
                        "tools/call",
                        "unknown_tool_log_redaction",
                        {"name": secret_tool_name, "arguments": {}},
                    ),
                    headers=_mcp_headers(bearer="valid.jwt.value"),
                )
        finally:
            root_logger.removeHandler(handler)

        result = response.json()["result"]
        _assert_error_result_has_no_structured_content(
            self,
            result,
            expected_message="The requested FormOwl tool is unavailable.",
        )
        rendered_headers = repr(dict(response.headers))
        rendered_logs = "\n".join(record.getMessage() for record in records)
        self.assertNotIn(secret_tool_name, response.text)
        self.assertNotIn(secret_tool_name, rendered_headers)
        self.assertNotIn(secret_tool_name, repr(self.bridge.decisions))
        self.assertNotIn(secret_tool_name, rendered_logs)
        self.assertEqual(self.handler_calls, [])
        self.assertEqual(len(self.bridge.decisions), 1)
        self.assertEqual(self.bridge.decisions[0]["tool_name"], "unknown_tool")
        self.assertEqual(self.bridge.decisions[0]["reason_code"], "unknown_tool")
        self.assertTrue(
            any(
                record.name == "formowl_gateway.remote"
                and record.getMessage() == "unknown_tool request rejected"
                for record in records
            )
        )

    def test_missing_principal_denial_audit_failure_returns_safe_server_error(self) -> None:
        self.bridge.fail_denied_audit = True

        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "missing_principal_audit_failure",
                    {"name": "whoami", "arguments": {}},
                ),
                headers=_mcp_headers(),
            )

        result = response.json()["result"]
        _assert_error_result_has_no_structured_content(
            self,
            result,
            expected_message="The FormOwl authorization decision could not be recorded.",
        )
        self.assertNotIn("_meta", result)
        self.assertEqual(self.handler_calls, [])
        self.assertEqual(self.bridge.decisions, [])
        self.assertNotIn("authentication_required", response.text)
        self.assertNotIn(self.config.protected_resource_metadata_url, response.text)
        self.assertNotIn("secret-bearer-value", response.text)

    def test_actor_context_denial_audit_failure_returns_safe_server_error(self) -> None:
        self.bridge.resolve_denial = _Denied(
            "insufficient_scope",
            "workspace_membership_inactive",
            403,
        )
        self.bridge.fail_denied_audit = True

        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "actor_context_audit_failure",
                    {
                        "name": "open_upload_session",
                        "arguments": {
                            "intent": "Upload governed mail evidence.",
                            "intended_asset_type": "pst",
                        },
                    },
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        result = response.json()["result"]
        _assert_error_result_has_no_structured_content(
            self,
            result,
            expected_message="The FormOwl authorization decision could not be recorded.",
        )
        self.assertNotIn("_meta", result)
        self.assertEqual(self.handler_calls, [])
        self.assertEqual(self.bridge.decisions, [])
        self.assertNotIn("workspace_membership_inactive", response.text)
        self.assertNotIn(self.config.protected_resource_metadata_url, response.text)
        self.assertNotIn("secret-bearer-value", response.text)

    def test_invalid_tool_arguments_denial_audit_failure_returns_safe_server_error_and_skips_handler(
        self,
    ) -> None:
        self.bridge.fail_denied_audit = True

        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "invalid_arguments_audit_failure",
                    {
                        "name": "open_upload_session",
                        "arguments": {
                            "intent": "Upload governed mail evidence.",
                            "intended_asset_type": "pst",
                            "workspace_id": "workspace_other",
                            "requester_user_id": "user_other",
                            "grants": [{"grant_id": "grant_forged"}],
                        },
                    },
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        result = response.json()["result"]
        _assert_error_result_has_no_structured_content(
            self,
            result,
            expected_message="The FormOwl authorization decision could not be recorded.",
        )
        self.assertNotIn("_meta", result)
        self.assertEqual(self.handler_calls, [])
        self.assertEqual(self.bridge.decisions, [])
        for forbidden in (
            "workspace_other",
            "user_other",
            "grant_forged",
            "invalid_tool_arguments",
            "secret-bearer-value",
        ):
            self.assertNotIn(forbidden, response.text)

    def test_connected_factory_rejects_enabled_handler_without_tool_policy(self) -> None:
        handler_calls: list[dict[str, Any]] = []
        with self.assertRaisesRegex(Exception, "lacks an authorization policy"):
            create_connected_mcp_application(
                bridge=self.bridge,
                config=self.config,
                google_client=self.google_client,
                semantic_gateway=SemanticMcpGateway(
                    ingestion_handler=lambda arguments: handler_calls.append(dict(arguments))
                    or {"status": "ok"}
                ),
                oauth_route_provider=lambda **_kwargs: [],
                clock=_now,
                environ={"FORMOWL_AUTH_MODE": "oauth_google"},
            )
        self.assertEqual(handler_calls, [])

    def test_connected_factory_rejects_detached_timezone_before_any_effect(self) -> None:
        detached_now = datetime(2026, 7, 14, 4, 0, tzinfo=_DetachedTimezone())

        def mutable_snapshot() -> bytes:
            return json.dumps(
                {
                    "authenticate_calls": self.bridge.authenticate_calls,
                    "resolve_calls": self.bridge.resolve_calls,
                    "decisions": self.bridge.decisions,
                    "http_denials": self.bridge.http_denials,
                    "handler_calls": self.handler_calls,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

        before = mutable_snapshot()

        with self.assertRaises(RuntimeError) as caught:
            create_connected_mcp_application(
                bridge=self.bridge,
                config=self.config,
                google_client=self.google_client,
                semantic_gateway=self.semantic_gateway,
                oauth_route_provider=lambda **_kwargs: [],
                clock=lambda: detached_now,
                environ={"FORMOWL_AUTH_MODE": "oauth_google"},
            )

        self.assertEqual(
            str(caught.exception),
            "connected MCP clock must return a timezone-aware datetime",
        )
        self.assertEqual(mutable_snapshot(), before)
        self.assertEqual(self.bridge.authenticate_calls, 0)
        self.assertEqual(self.bridge.resolve_calls, 0)
        self.assertEqual(self.bridge.decisions, [])
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_challenge_quoted_strings_escape_once_without_side_effects(self) -> None:
        def mutable_snapshot() -> bytes:
            return json.dumps(
                {
                    "authenticate_calls": self.bridge.authenticate_calls,
                    "resolve_calls": self.bridge.resolve_calls,
                    "decisions": self.bridge.decisions,
                    "http_denials": self.bridge.http_denials,
                    "handler_calls": self.handler_calls,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

        before = mutable_snapshot()
        raw_description = 'Boundary "quoted" at path\\segment.'
        challenge = build_www_authenticate_challenge(
            self.config.protected_resource_metadata_url,
            error="invalid_token",
            error_description=raw_description,
        )

        self.assertEqual(
            challenge,
            'Bearer resource_metadata="https://formowl.example/'
            '.well-known/oauth-protected-resource", error="invalid_token", '
            'error_description="Boundary \\"quoted\\" at path\\\\segment."',
        )
        self.assertEqual(challenge.count('", error="'), 1)
        self.assertEqual(challenge.count('", error_description="'), 1)
        self.assertEqual(challenge.count('\\"'), 2)
        self.assertEqual(challenge.count("\\\\"), 1)
        self.assertNotIn(raw_description, challenge)
        self.assertNotIn("secret-bearer-value", challenge)
        self.assertEqual(mutable_snapshot(), before)

        for invalid_description in (
            "Boundary\r\nX-Evil: yes",
            "Boundary\x7fvalue",
        ):
            with self.subTest(invalid_description=invalid_description):
                with self.assertRaises(ValueError):
                    build_www_authenticate_challenge(
                        self.config.protected_resource_metadata_url,
                        error="invalid_token",
                        error_description=invalid_description,
                    )
                self.assertEqual(mutable_snapshot(), before)

        self.assertEqual(self.bridge.authenticate_calls, 0)
        self.assertEqual(self.bridge.resolve_calls, 0)
        self.assertEqual(self.bridge.decisions, [])
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_safe_denial_normalizes_malformed_attributes_without_leaks_or_effects(
        self,
    ) -> None:
        malformed_cases = (
            _MalformedDenial(error=[], reason_code={}, http_status=[]),
            _MalformedDenial(
                error="x" * 65,
                reason_code="y" * 65,
                http_status={},
            ),
            _MalformedDenial(
                error="invalid_token\r\nX-Leak: raw-error-secret",
                reason_code="raw/reason/secret",
                http_status="403",
            ),
            _MalformedDenial(
                error="invalid token",
                reason_code=["raw-reason-secret"],
                http_status=403.0,
            ),
            _MalformedDenial(
                error="invalid_token\x7fraw-error-secret",
                reason_code="invalid\nreason",
                http_status=True,
            ),
            _MalformedDenial(
                error=None,
                reason_code=None,
                http_status=418,
            ),
        )

        for malformed in malformed_cases:
            with self.subTest(
                error=malformed.error,
                reason_code=malformed.reason_code,
                http_status=malformed.http_status,
            ):
                denial = _safe_denial(malformed)
                self.assertEqual(denial.error, "invalid_token")
                self.assertEqual(denial.reason_code, "authentication_failed")
                self.assertEqual(denial.http_status, 401)
                self.assertIs(type(denial.http_status), int)

        for malformed in (
            ValueError("raw-value-error-secret"),
            ContractValidationError("raw-contract-error-secret"),
        ):
            with self.subTest(exception_type=type(malformed).__name__):
                denial = _safe_denial(malformed)
                self.assertEqual(denial.error, "invalid_token")
                self.assertEqual(denial.reason_code, "authorization_header_invalid")
                self.assertEqual(denial.http_status, 401)

        self.assertEqual(self.bridge.authenticate_calls, 0)
        self.assertEqual(self.bridge.resolve_calls, 0)
        self.assertEqual(self.bridge.decisions, [])
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_successful_tool_result_rejects_unsafe_payloads_before_serialization(
        self,
    ) -> None:
        unsafe_payloads = (
            {"status": "ok", "token": "raw-token-secret"},
            {"status": "ok", "secret": "raw-secret-value"},
            {"status": "ok", "raw_path": "/tmp/raw-path-secret"},
            {"status": "ok", "bucket": "raw-storage-secret"},
            {
                "status": "ok",
                "details": {"internal_endpoint": "https://192.168.1.2/private"},
            },
            {"status": "ok", "details": "postgresql://db.internal/private"},
        )

        with (
            patch("formowl_gateway.remote.json.dumps") as serialize,
            patch("formowl_gateway.remote.mcp_types.CallToolResult") as result_type,
        ):
            for payload in unsafe_payloads:
                with self.subTest(payload=payload):
                    result = None
                    with self.assertRaises(ContractValidationError) as caught:
                        result = _successful_tool_result(payload)
                    self.assertIsNone(result)
                    self.assertTrue(
                        str(caught.exception).startswith("forbidden public "),
                        str(caught.exception),
                    )
                    for raw_value in (
                        "raw-token-secret",
                        "raw-secret-value",
                        "/tmp/raw-path-secret",
                        "raw-storage-secret",
                        "https://192.168.1.2/private",
                        "postgresql://db.internal/private",
                    ):
                        self.assertNotIn(raw_value, str(caught.exception))

            serialize.assert_not_called()
            result_type.assert_not_called()

        self.assertEqual(self.bridge.authenticate_calls, 0)
        self.assertEqual(self.bridge.resolve_calls, 0)
        self.assertEqual(self.bridge.decisions, [])
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_successful_tool_result_rejects_non_json_non_finite_and_serializer_failures(
        self,
    ) -> None:
        fixed_error = "connected MCP tool result must contain strict JSON values"

        async def coroutine_payload() -> dict[str, Any]:
            return {"status": "ok"}

        returned_coroutine = coroutine_payload()
        invalid_payloads = (
            (
                "set",
                {"status": "ok", "data": {"value": {"raw-set-secret"}}},
                "raw-set-secret",
            ),
            (
                "bytes",
                {"status": "ok", "data": {"value": b"raw-bytes-secret"}},
                "raw-bytes-secret",
            ),
            (
                "custom",
                {"status": "ok", "data": {"value": _NonJsonPayload()}},
                "raw-custom-object-secret",
            ),
            (
                "coroutine",
                {"status": "ok", "data": {"value": returned_coroutine}},
                "coroutine_payload",
            ),
            ("nan", {"status": "ok", "data": {"value": float("nan")}}, None),
            ("positive_infinity", {"status": "ok", "data": {"value": float("inf")}}, None),
            (
                "negative_infinity",
                {"status": "ok", "data": {"value": float("-inf")}},
                None,
            ),
        )
        round_trip_payloads = (
            (
                "nested_tuple",
                {"status": "ok", "data": {"value": ("raw-tuple-secret",)}},
                ["raw-tuple-secret"],
                "raw-tuple-secret",
            ),
            (
                "non_string_mapping_key",
                {"status": "ok", "data": {"value": {7: "raw-key-secret"}}},
                {"7": "raw-key-secret"},
                "raw-key-secret",
            ),
        )
        real_json_loads = json.loads

        try:
            with (
                patch("formowl_gateway.remote.mcp_types.TextContent") as text_type,
                patch("formowl_gateway.remote.mcp_types.CallToolResult") as result_type,
            ):
                for label, payload, raw_marker in invalid_payloads:
                    with self.subTest(label=label):
                        with self.assertRaises(ContractValidationError) as caught:
                            _successful_tool_result(payload)
                        self.assertEqual(str(caught.exception), fixed_error)
                        if raw_marker is not None:
                            self.assertNotIn(raw_marker, str(caught.exception))

                for label, payload, expected_round_trip_value, raw_marker in round_trip_payloads:
                    with self.subTest(label=label):
                        original_payload = copy.deepcopy(payload)
                        canonical_text = json.dumps(
                            payload,
                            allow_nan=False,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        round_trip_payload = real_json_loads(canonical_text)
                        self.assertIsInstance(round_trip_payload, dict)
                        self.assertEqual(
                            round_trip_payload["data"]["value"],
                            expected_round_trip_value,
                        )
                        self.assertNotEqual(round_trip_payload, payload)

                        with patch(
                            "formowl_gateway.remote.json.loads",
                            wraps=real_json_loads,
                        ) as deserialize:
                            with self.assertRaises(ContractValidationError) as caught:
                                _successful_tool_result(payload)

                        self.assertEqual(str(caught.exception), fixed_error)
                        self.assertNotIn(raw_marker, str(caught.exception))
                        self.assertEqual(payload, original_payload)
                        deserialize.assert_called_once_with(canonical_text)

                with patch(
                    "formowl_gateway.remote.json.dumps",
                    side_effect=RuntimeError("raw-serializer-secret"),
                ):
                    with self.assertRaises(ContractValidationError) as caught:
                        _successful_tool_result({"status": "ok", "data": {"count": 1}})
                    self.assertEqual(str(caught.exception), fixed_error)
                    self.assertNotIn("raw-serializer-secret", str(caught.exception))

                text_type.assert_not_called()
                result_type.assert_not_called()
        finally:
            returned_coroutine.close()

        self.assertEqual(self.bridge.authenticate_calls, 0)
        self.assertEqual(self.bridge.resolve_calls, 0)
        self.assertEqual(self.bridge.decisions, [])
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_successful_tool_result_preserves_canonical_safe_payload_and_error_flag(
        self,
    ) -> None:
        payloads = (
            (
                {
                    "status": "error",
                    "error": "server_error",
                    "reason_code": "safe_failure",
                },
                True,
            ),
            (
                {
                    "status": "ok",
                    "result_type": "safe_result",
                    "data": {"count": 1},
                },
                False,
            ),
        )

        for payload, expected_is_error in payloads:
            with self.subTest(status=payload["status"]):
                result = _successful_tool_result(payload)
                canonical_text = json.dumps(
                    payload,
                    allow_nan=False,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self.assertEqual(result.structuredContent, payload)
                self.assertEqual(len(result.content), 1)
                self.assertEqual(result.content[0].type, "text")
                self.assertEqual(result.content[0].text, canonical_text)
                self.assertIs(result.isError, expected_is_error)

        self.assertEqual(self.bridge.authenticate_calls, 0)
        self.assertEqual(self.bridge.resolve_calls, 0)
        self.assertEqual(self.bridge.decisions, [])
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_dispatcher_invalid_semantic_payloads_return_fixed_error_after_authorization(
        self,
    ) -> None:
        invalid_payloads = (
            (
                "set",
                {"status": "ok", "data": {"value": {"raw-set-secret"}}},
                "raw-set-secret",
            ),
            (
                "bytes",
                {"status": "ok", "data": {"value": b"raw-bytes-secret"}},
                "raw-bytes-secret",
            ),
            (
                "custom",
                {"status": "ok", "data": {"value": _NonJsonPayload()}},
                "raw-custom-object-secret",
            ),
            ("nan", {"status": "ok", "data": {"value": float("nan")}}, None),
            ("positive_infinity", {"status": "ok", "data": {"value": float("inf")}}, None),
            (
                "negative_infinity",
                {"status": "ok", "data": {"value": float("-inf")}},
                None,
            ),
        )
        original_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }
        expected_prepared_arguments = {
            **original_arguments,
            "session_id": "oauthsid_beta",
            "workspace_id": "workspace_beta",
            "requester_user_id": "user_beta",
        }

        for case_index, (label, payload, raw_marker) in enumerate(
            invalid_payloads,
            start=1,
        ):
            with self.subTest(label=label):
                immutable_before = json.dumps(
                    {
                        "active_grants": self.bridge.active_grants,
                        "http_denials": self.bridge.http_denials,
                        "handler_calls": self.handler_calls,
                        "tool_call_logs": [
                            item.to_dict() for item in self.semantic_gateway.tool_call_logs
                        ],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                decision_count = len(self.bridge.decisions)
                resolve_count = self.bridge.resolve_calls
                request_id = f"mcp_req_invalid_payload_{case_index:02d}"
                principal_token = _current_principal.set(self.bridge.principal)
                request_token = _current_request_id.set(request_id)
                try:
                    with patch.object(
                        self.semantic_gateway,
                        "dispatch_tool",
                        return_value=payload,
                    ) as dispatch:
                        result = asyncio.run(
                            self.bundle.dispatcher.call_tool(
                                "open_upload_session",
                                original_arguments,
                            )
                        )
                finally:
                    _current_request_id.reset(request_token)
                    _current_principal.reset(principal_token)

                dispatch.assert_called_once_with(
                    "open_upload_session",
                    expected_prepared_arguments,
                )
                public_result = result.model_dump(by_alias=True, exclude_none=True)
                _assert_error_result_has_no_structured_content(
                    self,
                    public_result,
                    expected_message="The FormOwl tool could not complete the request.",
                )
                self.assertNotIn("_meta", public_result)
                if raw_marker is not None:
                    self.assertNotIn(raw_marker, repr(public_result))
                    self.assertNotIn(raw_marker, repr(self.bridge.decisions))
                self.assertEqual(self.bridge.resolve_calls, resolve_count + 1)
                self.assertEqual(len(self.bridge.decisions), decision_count + 1)
                decision = self.bridge.decisions[-1]
                self.assertEqual(decision["principal"], self.bridge.principal)
                self.assertEqual(decision["request_id"], request_id)
                self.assertRegex(decision["tool_call_id"], r"^mcp_call_[0-9a-f]{32}$")
                self.assertEqual(decision["tool_name"], "open_upload_session")
                self.assertEqual(decision["workspace_id"], "workspace_beta")
                self.assertTrue(decision["allowed"])
                self.assertEqual(decision["reason_code"], "tool_authorized")
                self.assertEqual(
                    json.dumps(
                        {
                            "active_grants": self.bridge.active_grants,
                            "http_denials": self.bridge.http_denials,
                            "handler_calls": self.handler_calls,
                            "tool_call_logs": [
                                item.to_dict() for item in self.semantic_gateway.tool_call_logs
                            ],
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                    immutable_before,
                )

        self.assertEqual(self.bridge.authenticate_calls, 0)
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_real_semantic_handler_non_finite_result_cannot_leave_false_success_log(
        self,
    ) -> None:
        original_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }
        expected_prepared_arguments = {
            **original_arguments,
            "session_id": "oauthsid_beta",
            "workspace_id": "workspace_beta",
            "requester_user_id": "user_beta",
        }

        for case_index, (label, non_finite_value) in enumerate(
            (
                ("nan", float("nan")),
                ("positive_infinity", float("inf")),
                ("negative_infinity", float("-inf")),
            ),
            start=1,
        ):
            with self.subTest(label=label):
                raw_marker = f"raw-non-finite-handler-marker-{label}"
                handler_calls: list[dict[str, Any]] = []

                def configured_handler(arguments: dict[str, Any]) -> dict[str, Any]:
                    handler_calls.append(dict(arguments))
                    return {
                        "status": "ok",
                        "value": non_finite_value,
                        "marker": raw_marker,
                    }

                bridge = _FakeBridge(self.config, self.google_client)
                semantic_gateway = SemanticMcpGateway(upload_session_handler=configured_handler)
                bundle = create_connected_mcp_application(
                    bridge=bridge,
                    config=self.config,
                    google_client=self.google_client,
                    semantic_gateway=semantic_gateway,
                    oauth_route_provider=lambda **_kwargs: [],
                    clock=_now,
                    environ={"FORMOWL_AUTH_MODE": "oauth_google"},
                )
                request_id = f"non_finite_handler_{case_index:02d}"
                with TestClient(bundle.app, raise_server_exceptions=False) as client:
                    response = client.post(
                        "/mcp",
                        json=_request(
                            "tools/call",
                            request_id,
                            {
                                "name": "open_upload_session",
                                "arguments": original_arguments,
                            },
                        ),
                        headers=_mcp_headers(bearer="valid.jwt.value"),
                    )

                self.assertEqual(response.status_code, 200, response.text)
                response_payload = response.json()
                self.assertEqual(
                    set(response_payload),
                    {"jsonrpc", "id", "result"},
                )
                self.assertEqual(response_payload["jsonrpc"], "2.0")
                self.assertEqual(response_payload["id"], request_id)
                self.assertEqual(handler_calls, [expected_prepared_arguments])
                public_result = response_payload["result"]
                self.assertEqual(set(public_result), {"content", "isError"})
                _assert_error_result_has_no_structured_content(
                    self,
                    public_result,
                    expected_message="The FormOwl tool could not complete the request.",
                )
                self.assertNotIn("_meta", public_result)
                self.assertEqual(bridge.authenticate_calls, 1)
                self.assertEqual(bridge.resolve_calls, 1)
                self.assertEqual(len(bridge.decisions), 1)
                decision = bridge.decisions[0]
                self.assertEqual(decision["principal"], bridge.principal)
                self.assertRegex(decision["request_id"], r"^mcp_req_[0-9a-f]{32}$")
                self.assertRegex(decision["tool_call_id"], r"^mcp_call_[0-9a-f]{32}$")
                self.assertEqual(decision["tool_name"], "open_upload_session")
                self.assertEqual(decision["workspace_id"], "workspace_beta")
                self.assertTrue(decision["allowed"])
                self.assertEqual(
                    decision["reason_code"],
                    "tool_authorized",
                )
                self.assertEqual(bridge.http_denials, [])
                self.assertFalse(
                    any(item.status == "ok" for item in semantic_gateway.tool_call_logs),
                    semantic_gateway.tool_call_logs,
                )
                rendered_state = repr(
                    {
                        "response": public_result,
                        "authorization": bridge.decisions,
                        "tool_logs": [item.to_dict() for item in semantic_gateway.tool_call_logs],
                    }
                )
                self.assertNotIn(raw_marker, response.text)
                self.assertNotIn(raw_marker, rendered_state)

    def test_real_semantic_handler_finite_float_result_is_canonical_success(
        self,
    ) -> None:
        handler_calls: list[dict[str, Any]] = []

        def configured_handler(arguments: dict[str, Any]) -> dict[str, Any]:
            handler_calls.append(dict(arguments))
            return {
                "status": "ok",
                "value": 1.25,
            }

        bridge = _FakeBridge(self.config, self.google_client)
        semantic_gateway = SemanticMcpGateway(upload_session_handler=configured_handler)
        bundle = create_connected_mcp_application(
            bridge=bridge,
            config=self.config,
            google_client=self.google_client,
            semantic_gateway=semantic_gateway,
            oauth_route_provider=lambda **_kwargs: [],
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        request_id = "finite_handler"
        with TestClient(bundle.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    request_id,
                    {
                        "name": "open_upload_session",
                        "arguments": {
                            "intent": "Upload governed mail evidence.",
                            "intended_asset_type": "pst",
                        },
                    },
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        self.assertEqual(response.status_code, 200, response.text)
        response_payload = response.json()
        self.assertEqual(set(response_payload), {"jsonrpc", "id", "result"})
        self.assertEqual(response_payload["jsonrpc"], "2.0")
        self.assertEqual(response_payload["id"], request_id)
        result = response_payload["result"]
        self.assertEqual(
            set(result),
            {"content", "isError", "structuredContent"},
        )
        self.assertEqual(
            handler_calls,
            [
                {
                    "intent": "Upload governed mail evidence.",
                    "intended_asset_type": "pst",
                    "session_id": "oauthsid_beta",
                    "workspace_id": "workspace_beta",
                    "requester_user_id": "user_beta",
                }
            ],
        )
        self.assertFalse(result["isError"])
        structured_content = result["structuredContent"]
        self.assertEqual(structured_content["status"], "ok")
        self.assertEqual(structured_content["data"]["value"], 1.25)
        canonical_text = json.dumps(
            structured_content,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(
            result["content"],
            [{"type": "text", "text": canonical_text}],
        )
        self.assertEqual(json.loads(canonical_text), structured_content)
        self.assertEqual(bridge.authenticate_calls, 1)
        self.assertEqual(bridge.resolve_calls, 1)
        self.assertEqual(len(bridge.decisions), 1)
        decision = bridge.decisions[0]
        self.assertEqual(decision["principal"], bridge.principal)
        self.assertRegex(decision["request_id"], r"^mcp_req_[0-9a-f]{32}$")
        self.assertRegex(decision["tool_call_id"], r"^mcp_call_[0-9a-f]{32}$")
        self.assertEqual(decision["tool_name"], "open_upload_session")
        self.assertEqual(decision["workspace_id"], "workspace_beta")
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["reason_code"], "tool_authorized")
        self.assertEqual(bridge.http_denials, [])
        self.assertEqual(len(semantic_gateway.tool_call_logs), 1)
        self.assertEqual(semantic_gateway.tool_call_logs[0].status, "ok")

    def test_dispatcher_closes_coroutine_result_without_awaiting_or_leaking(self) -> None:
        execution_started: list[bool] = []

        async def coroutine_payload() -> dict[str, Any]:
            execution_started.append(True)
            return {"status": "ok", "data": {"raw_value": "raw-coroutine-secret"}}

        returned_coroutine = coroutine_payload()
        principal_token = _current_principal.set(self.bridge.principal)
        request_token = _current_request_id.set("mcp_req_coroutine_result")
        try:
            with patch.object(
                self.semantic_gateway,
                "dispatch_tool",
                return_value=returned_coroutine,
            ) as dispatch:
                result = asyncio.run(
                    self.bundle.dispatcher.call_tool(
                        "open_upload_session",
                        {
                            "intent": "Upload governed mail evidence.",
                            "intended_asset_type": "pst",
                        },
                    )
                )
        finally:
            _current_request_id.reset(request_token)
            _current_principal.reset(principal_token)

        dispatch.assert_called_once()
        self.assertEqual(execution_started, [])
        self.assertIsNone(returned_coroutine.cr_frame)
        public_result = result.model_dump(by_alias=True, exclude_none=True)
        _assert_error_result_has_no_structured_content(
            self,
            public_result,
            expected_message="The FormOwl tool could not complete the request.",
        )
        self.assertNotIn("_meta", public_result)
        self.assertNotIn("raw-coroutine-secret", repr(public_result))
        self.assertEqual(self.bridge.resolve_calls, 1)
        self.assertEqual(len(self.bridge.decisions), 1)
        self.assertTrue(self.bridge.decisions[0]["allowed"])
        self.assertEqual(self.bridge.decisions[0]["reason_code"], "tool_authorized")
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_dispatcher_closes_coroutine_returned_by_sync_configured_handler_without_warning(
        self,
    ) -> None:
        synchronous_effects: list[dict[str, Any]] = []
        coroutine_execution_started: list[bool] = []
        returned_coroutines: list[Any] = []
        raw_marker = "/tmp/raw-sync-handler-coroutine-secret"

        async def configured_handler_coroutine() -> dict[str, Any]:
            coroutine_execution_started.append(True)
            return {"status": "ok", "raw_path": raw_marker}

        def sync_handler(arguments: dict[str, Any]) -> Any:
            synchronous_effects.append(dict(arguments))
            returned_coroutine = configured_handler_coroutine()
            returned_coroutines.append(returned_coroutine)
            return returned_coroutine

        bridge = _FakeBridge(self.config, self.google_client)
        semantic_gateway = SemanticMcpGateway(upload_session_handler=sync_handler)
        bundle = create_connected_mcp_application(
            bridge=bridge,
            config=self.config,
            google_client=self.google_client,
            semantic_gateway=semantic_gateway,
            oauth_route_provider=lambda **_kwargs: [],
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        original_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }
        expected_prepared_arguments = {
            **original_arguments,
            "session_id": "oauthsid_beta",
            "workspace_id": "workspace_beta",
            "requester_user_id": "user_beta",
        }
        principal_token = _current_principal.set(bridge.principal)
        request_token = _current_request_id.set("mcp_req_sync_handler_coroutine_result")
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = asyncio.run(
                    bundle.dispatcher.call_tool(
                        "open_upload_session",
                        original_arguments,
                    )
                )
                self.assertEqual(len(returned_coroutines), 1)
                returned_coroutine = returned_coroutines[0]
                self.assertIsNone(returned_coroutine.cr_frame)
                returned_coroutines.clear()
                del returned_coroutine
                gc.collect()
        finally:
            _current_request_id.reset(request_token)
            _current_principal.reset(principal_token)

        self.assertEqual(synchronous_effects, [expected_prepared_arguments])
        self.assertEqual(coroutine_execution_started, [])
        self.assertEqual(caught, [])
        public_result = result.model_dump(by_alias=True, exclude_none=True)
        _assert_error_result_has_no_structured_content(
            self,
            public_result,
            expected_message="The FormOwl tool could not complete the request.",
        )
        self.assertNotIn("_meta", public_result)
        rendered_state = repr(
            {
                "response": public_result,
                "warnings": [str(item.message) for item in caught],
                "authorization": bridge.decisions,
                "tool_logs": [item.to_dict() for item in semantic_gateway.tool_call_logs],
            }
        )
        self.assertNotIn("configured_handler_coroutine", rendered_state)
        self.assertNotIn(raw_marker, rendered_state)
        self.assertEqual(bridge.resolve_calls, 1)
        self.assertEqual(len(bridge.decisions), 1)
        self.assertTrue(bridge.decisions[0]["allowed"])
        self.assertEqual(bridge.decisions[0]["reason_code"], "tool_authorized")
        self.assertEqual(bridge.http_denials, [])
        self.assertEqual(semantic_gateway.tool_call_logs, [])

    def test_dispatcher_closes_nested_coroutine_from_sync_configured_handler_without_warning(
        self,
    ) -> None:
        synchronous_effects: list[dict[str, Any]] = []
        coroutine_execution_started: list[bool] = []
        returned_coroutines: list[Any] = []
        raw_marker = "/tmp/raw-sync-handler-nested-coroutine-secret"

        async def nested_configured_handler_coroutine() -> dict[str, Any]:
            coroutine_execution_started.append(True)
            return {"status": "ok", "raw_path": raw_marker}

        def sync_handler(arguments: dict[str, Any]) -> dict[str, Any]:
            synchronous_effects.append(dict(arguments))
            returned_coroutine = nested_configured_handler_coroutine()
            returned_coroutines.append(returned_coroutine)
            return {
                "status": "ok",
                "nested": {
                    "items": (
                        "safe",
                        [returned_coroutine],
                    )
                },
            }

        bridge = _FakeBridge(self.config, self.google_client)
        semantic_gateway = SemanticMcpGateway(upload_session_handler=sync_handler)
        bundle = create_connected_mcp_application(
            bridge=bridge,
            config=self.config,
            google_client=self.google_client,
            semantic_gateway=semantic_gateway,
            oauth_route_provider=lambda **_kwargs: [],
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        original_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }
        expected_prepared_arguments = {
            **original_arguments,
            "session_id": "oauthsid_beta",
            "workspace_id": "workspace_beta",
            "requester_user_id": "user_beta",
        }
        principal_token = _current_principal.set(bridge.principal)
        request_token = _current_request_id.set("mcp_req_sync_handler_nested_coroutine_result")
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = asyncio.run(
                    bundle.dispatcher.call_tool(
                        "open_upload_session",
                        original_arguments,
                    )
                )
                self.assertEqual(len(returned_coroutines), 1)
                returned_coroutine = returned_coroutines[0]
                self.assertIsNone(returned_coroutine.cr_frame)
                returned_coroutines.clear()
                del returned_coroutine
                gc.collect()
        finally:
            _current_request_id.reset(request_token)
            _current_principal.reset(principal_token)

        self.assertEqual(synchronous_effects, [expected_prepared_arguments])
        self.assertEqual(coroutine_execution_started, [])
        self.assertEqual(caught, [])
        public_result = result.model_dump(by_alias=True, exclude_none=True)
        _assert_error_result_has_no_structured_content(
            self,
            public_result,
            expected_message="The FormOwl tool could not complete the request.",
        )
        self.assertNotIn("_meta", public_result)
        rendered_state = repr(
            {
                "response": public_result,
                "warnings": [str(item.message) for item in caught],
                "authorization": bridge.decisions,
                "tool_logs": [item.to_dict() for item in semantic_gateway.tool_call_logs],
            }
        )
        self.assertNotIn("nested_configured_handler_coroutine", rendered_state)
        self.assertNotIn(raw_marker, rendered_state)
        self.assertEqual(original_arguments.keys(), {"intent", "intended_asset_type"})
        self.assertEqual(bridge.resolve_calls, 1)
        self.assertEqual(len(bridge.decisions), 1)
        self.assertTrue(bridge.decisions[0]["allowed"])
        self.assertEqual(bridge.decisions[0]["reason_code"], "tool_authorized")
        self.assertEqual(bridge.http_denials, [])
        self.assertEqual(bridge.active_grants, [])
        self.assertEqual(semantic_gateway.tool_call_logs, [])

    def test_dispatcher_uses_one_stateful_container_snapshot_without_coroutine_injection(
        self,
    ) -> None:
        synchronous_effects: list[dict[str, Any]] = []
        injected_coroutines: list[Any] = []
        coroutine_execution_started: list[bool] = []
        raw_marker = "/tmp/raw-connected-stateful-second-read-secret"

        async def second_read_coroutine() -> dict[str, str]:
            coroutine_execution_started.append(True)
            return {"raw_path": raw_marker}

        class StatefulMapping(Mapping[str, Any]):
            def __init__(self, safe_items: list[tuple[str, Any]]) -> None:
                self.safe_items = tuple(safe_items)
                self.read_operations: list[str] = []
                self.active_items = dict(self.safe_items)

            def _begin_read(self, operation: str) -> tuple[tuple[str, Any], ...]:
                self.read_operations.append(operation)
                if len(self.read_operations) == 1:
                    return self.safe_items
                injected = second_read_coroutine()
                injected_coroutines.append(injected)
                return (*self.safe_items, ("second_read_injection", injected))

            def items(self):
                return self._begin_read("items")

            def __iter__(self):
                self.active_items = dict(self._begin_read("__iter__"))
                return iter(self.active_items)

            def __getitem__(self, key: str) -> Any:
                return self.active_items[key]

            def __len__(self) -> int:
                return len(self.safe_items)

        class StatefulList(list[Any]):
            def __init__(self, values: list[Any]) -> None:
                super().__init__(values)
                self.read_count = 0

            def __iter__(self):
                self.read_count += 1
                if self.read_count > 1:
                    injected = second_read_coroutine()
                    injected_coroutines.append(injected)
                    return iter([injected])
                return super().__iter__()

        class StatefulTuple(tuple[Any, ...]):
            def __new__(cls, values: tuple[Any, ...]):
                return super().__new__(cls, values)

            def __init__(self, values: tuple[Any, ...]) -> None:
                del values
                self.read_count = 0

            def __iter__(self):
                self.read_count += 1
                if self.read_count > 1:
                    injected = second_read_coroutine()
                    injected_coroutines.append(injected)
                    return iter([injected])
                return super().__iter__()

        nested_mapping = StatefulMapping([("safe_value", "detached")])
        nested_tuple = StatefulTuple(("safe-tuple-value",))
        nested_list = StatefulList([nested_mapping, nested_tuple])
        handler_payload = StatefulMapping(
            [
                ("status", "ok"),
                ("nested", nested_list),
            ]
        )

        def sync_handler(arguments: dict[str, Any]) -> Mapping[str, Any]:
            synchronous_effects.append(dict(arguments))
            return handler_payload

        bridge = _FakeBridge(self.config, self.google_client)
        semantic_gateway = SemanticMcpGateway(upload_session_handler=sync_handler)
        bundle = create_connected_mcp_application(
            bridge=bridge,
            config=self.config,
            google_client=self.google_client,
            semantic_gateway=semantic_gateway,
            oauth_route_provider=lambda **_kwargs: [],
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        original_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }
        expected_prepared_arguments = {
            **original_arguments,
            "session_id": "oauthsid_beta",
            "workspace_id": "workspace_beta",
            "requester_user_id": "user_beta",
        }
        principal_token = _current_principal.set(bridge.principal)
        request_token = _current_request_id.set("mcp_req_stateful_handler_snapshot")
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = asyncio.run(
                    bundle.dispatcher.call_tool(
                        "open_upload_session",
                        original_arguments,
                    )
                )
                gc.collect()
        finally:
            _current_request_id.reset(request_token)
            _current_principal.reset(principal_token)

        self.assertEqual(synchronous_effects, [expected_prepared_arguments])
        self.assertEqual(handler_payload.read_operations, ["items"])
        self.assertEqual(nested_mapping.read_operations, ["items"])
        self.assertEqual(nested_list.read_count, 1)
        self.assertEqual(nested_tuple.read_count, 1)
        self.assertEqual(injected_coroutines, [])
        self.assertEqual(coroutine_execution_started, [])
        self.assertEqual(caught, [])
        self.assertEqual(
            result.structuredContent["data"]["nested"],
            [{"safe_value": "detached"}, ["safe-tuple-value"]],
        )
        self.assertFalse(result.isError)
        self.assertEqual(bridge.resolve_calls, 1)
        self.assertEqual(len(bridge.decisions), 1)
        self.assertTrue(bridge.decisions[0]["allowed"])
        self.assertEqual(bridge.decisions[0]["reason_code"], "tool_authorized")
        self.assertEqual(bridge.http_denials, [])
        self.assertEqual(bridge.active_grants, [])
        self.assertEqual(len(semantic_gateway.tool_call_logs), 1)
        self.assertEqual(semantic_gateway.tool_call_logs[0].status, "ok")
        rendered_state = repr(
            {
                "response": result.model_dump(by_alias=True, exclude_none=True),
                "warnings": [str(item.message) for item in caught],
                "authorization": bridge.decisions,
                "tool_logs": [item.to_dict() for item in semantic_gateway.tool_call_logs],
            }
        )
        self.assertNotIn("StatefulMapping", rendered_state)
        self.assertNotIn("second_read_coroutine", rendered_state)
        self.assertNotIn(raw_marker, rendered_state)

    def test_dispatcher_rejects_nested_custom_awaitable_without_custom_close_or_partial_state(
        self,
    ) -> None:
        class TrackedCustomAwaitable:
            def __init__(self, raw_marker: str) -> None:
                self.raw_marker = raw_marker
                self.await_calls = 0
                self.close_calls = 0

            def __await__(self):
                self.await_calls += 1
                if False:
                    yield None
                return self.raw_marker

            def close(self) -> None:
                self.close_calls += 1

        synchronous_effects: list[dict[str, Any]] = []
        raw_marker = "/tmp/raw-sync-handler-custom-awaitable-secret"
        custom_awaitable = TrackedCustomAwaitable(raw_marker)

        def sync_handler(arguments: dict[str, Any]) -> dict[str, Any]:
            synchronous_effects.append(dict(arguments))
            return {
                "status": "ok",
                "nested": {
                    "items": (
                        "safe",
                        [custom_awaitable],
                    )
                },
            }

        bridge = _FakeBridge(self.config, self.google_client)
        semantic_gateway = SemanticMcpGateway(upload_session_handler=sync_handler)
        bundle = create_connected_mcp_application(
            bridge=bridge,
            config=self.config,
            google_client=self.google_client,
            semantic_gateway=semantic_gateway,
            oauth_route_provider=lambda **_kwargs: [],
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        original_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }
        expected_prepared_arguments = {
            **original_arguments,
            "session_id": "oauthsid_beta",
            "workspace_id": "workspace_beta",
            "requester_user_id": "user_beta",
        }
        principal_token = _current_principal.set(bridge.principal)
        request_token = _current_request_id.set("mcp_req_sync_handler_nested_custom_awaitable")
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = asyncio.run(
                    bundle.dispatcher.call_tool(
                        "open_upload_session",
                        original_arguments,
                    )
                )
                gc.collect()
        finally:
            _current_request_id.reset(request_token)
            _current_principal.reset(principal_token)

        self.assertEqual(synchronous_effects, [expected_prepared_arguments])
        self.assertEqual(custom_awaitable.await_calls, 0)
        self.assertEqual(custom_awaitable.close_calls, 0)
        self.assertEqual(caught, [])
        public_result = result.model_dump(by_alias=True, exclude_none=True)
        _assert_error_result_has_no_structured_content(
            self,
            public_result,
            expected_message="The FormOwl tool could not complete the request.",
        )
        self.assertNotIn("_meta", public_result)
        rendered_state = repr(
            {
                "response": public_result,
                "warnings": [str(item.message) for item in caught],
                "authorization": bridge.decisions,
                "tool_logs": [item.to_dict() for item in semantic_gateway.tool_call_logs],
            }
        )
        self.assertNotIn("TrackedCustomAwaitable", rendered_state)
        self.assertNotIn(raw_marker, rendered_state)
        self.assertEqual(original_arguments.keys(), {"intent", "intended_asset_type"})
        self.assertEqual(bridge.resolve_calls, 1)
        self.assertEqual(len(bridge.decisions), 1)
        self.assertTrue(bridge.decisions[0]["allowed"])
        self.assertEqual(bridge.decisions[0]["reason_code"], "tool_authorized")
        self.assertEqual(bridge.http_denials, [])
        self.assertEqual(bridge.active_grants, [])
        self.assertEqual(semantic_gateway.tool_call_logs, [])

    def test_dispatcher_rejects_cyclic_nested_coroutine_graph_without_partial_state(
        self,
    ) -> None:
        synchronous_effects: list[dict[str, Any]] = []
        coroutine_execution_started: list[str] = []
        raw_markers = {
            "key": "/tmp/raw-connected-coroutine-mapping-key-secret",
            "set": "/tmp/raw-connected-coroutine-set-member-secret",
            "frozenset": "/tmp/raw-connected-coroutine-frozenset-member-secret",
        }
        returned_coroutines: list[Any] = []

        async def connected_coroutine_mapping_key() -> dict[str, str]:
            coroutine_execution_started.append("key")
            return {"raw_path": raw_markers["key"]}

        async def connected_coroutine_set_member() -> dict[str, str]:
            coroutine_execution_started.append("set")
            return {"raw_path": raw_markers["set"]}

        async def connected_coroutine_frozenset_member() -> dict[str, str]:
            coroutine_execution_started.append("frozenset")
            return {"raw_path": raw_markers["frozenset"]}

        mapping_key = connected_coroutine_mapping_key()
        set_member = connected_coroutine_set_member()
        frozenset_member = connected_coroutine_frozenset_member()
        returned_coroutines.extend((mapping_key, set_member, frozenset_member))
        self.assertEqual(len({id(item) for item in returned_coroutines}), 3)
        for returned_coroutine in returned_coroutines:
            self.assertEqual(
                inspect.getcoroutinestate(returned_coroutine),
                inspect.CORO_CREATED,
            )
        handler_payload: dict[object, object] = {"status": "ok"}
        handler_payload["cycle"] = handler_payload
        handler_payload[mapping_key] = {
            "set_nesting": {set_member},
            "frozenset_nesting": frozenset({frozenset_member}),
        }

        def sync_handler(arguments: dict[str, Any]) -> dict[object, object]:
            synchronous_effects.append(dict(arguments))
            return handler_payload

        bridge = _FakeBridge(self.config, self.google_client)
        semantic_gateway = SemanticMcpGateway(upload_session_handler=sync_handler)
        bundle = create_connected_mcp_application(
            bridge=bridge,
            config=self.config,
            google_client=self.google_client,
            semantic_gateway=semantic_gateway,
            oauth_route_provider=lambda **_kwargs: [],
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        original_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }
        expected_prepared_arguments = {
            **original_arguments,
            "session_id": "oauthsid_beta",
            "workspace_id": "workspace_beta",
            "requester_user_id": "user_beta",
        }
        principal_token = _current_principal.set(bridge.principal)
        request_token = _current_request_id.set("mcp_req_sync_handler_cyclic_nested_coroutines")
        try:
            with (
                warnings.catch_warnings(record=True) as caught,
                patch("formowl_gateway.semantic.sha256_json") as payload_hasher,
            ):
                warnings.simplefilter("always")
                result = asyncio.run(
                    bundle.dispatcher.call_tool(
                        "open_upload_session",
                        original_arguments,
                    )
                )
                payload_hasher.assert_not_called()
                self.assertEqual(len(returned_coroutines), 3)
                for returned_coroutine in returned_coroutines:
                    self.assertIsNone(returned_coroutine.cr_frame)
                    self.assertEqual(
                        inspect.getcoroutinestate(returned_coroutine),
                        inspect.CORO_CLOSED,
                    )
                gc.collect()
        finally:
            _current_request_id.reset(request_token)
            _current_principal.reset(principal_token)

        self.assertEqual(synchronous_effects, [expected_prepared_arguments])
        self.assertEqual(coroutine_execution_started, [])
        self.assertEqual(caught, [])
        public_result = result.model_dump(by_alias=True, exclude_none=True)
        _assert_error_result_has_no_structured_content(
            self,
            public_result,
            expected_message="The FormOwl tool could not complete the request.",
        )
        self.assertNotIn("_meta", public_result)
        rendered_state = repr(
            {
                "response": public_result,
                "warnings": [str(item.message) for item in caught],
                "authorization": bridge.decisions,
                "tool_logs": [item.to_dict() for item in semantic_gateway.tool_call_logs],
            }
        )
        for function_name in (
            "connected_coroutine_mapping_key",
            "connected_coroutine_set_member",
            "connected_coroutine_frozenset_member",
        ):
            self.assertNotIn(function_name, rendered_state)
        for raw_marker in raw_markers.values():
            self.assertNotIn(raw_marker, rendered_state)
        self.assertEqual(bridge.resolve_calls, 1)
        self.assertEqual(len(bridge.decisions), 1)
        self.assertTrue(bridge.decisions[0]["allowed"])
        self.assertEqual(bridge.decisions[0]["reason_code"], "tool_authorized")
        self.assertEqual(bridge.http_denials, [])
        self.assertEqual(bridge.active_grants, [])
        self.assertEqual(semantic_gateway.tool_call_logs, [])

    def test_dispatcher_rejects_non_mapping_payloads_from_sync_configured_handler_without_partial_state(
        self,
    ) -> None:
        original_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }
        expected_prepared_arguments = {
            **original_arguments,
            "session_id": "oauthsid_beta",
            "workspace_id": "workspace_beta",
            "requester_user_id": "user_beta",
        }
        invalid_payloads = (
            ("none", None, None),
            ("list", ["raw-list-payload-secret"], "raw-list-payload-secret"),
            ("string", "/tmp/raw-string-payload-secret", "/tmp/raw-string-payload-secret"),
            ("integer", 7, None),
        )

        for case_index, (label, invalid_payload, raw_marker) in enumerate(
            invalid_payloads,
            start=1,
        ):
            with self.subTest(label=label):
                handler_calls: list[dict[str, Any]] = []

                def sync_handler(arguments: dict[str, Any]) -> Any:
                    handler_calls.append(dict(arguments))
                    return invalid_payload

                bridge = _FakeBridge(self.config, self.google_client)
                semantic_gateway = SemanticMcpGateway(upload_session_handler=sync_handler)
                bundle = create_connected_mcp_application(
                    bridge=bridge,
                    config=self.config,
                    google_client=self.google_client,
                    semantic_gateway=semantic_gateway,
                    oauth_route_provider=lambda **_kwargs: [],
                    clock=_now,
                    environ={"FORMOWL_AUTH_MODE": "oauth_google"},
                )
                principal_token = _current_principal.set(bridge.principal)
                request_token = _current_request_id.set(
                    f"mcp_req_sync_handler_non_mapping_{case_index:02d}"
                )
                try:
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        result = asyncio.run(
                            bundle.dispatcher.call_tool(
                                "open_upload_session",
                                original_arguments,
                            )
                        )
                        gc.collect()
                finally:
                    _current_request_id.reset(request_token)
                    _current_principal.reset(principal_token)

                public_result = result.model_dump(by_alias=True, exclude_none=True)
                _assert_error_result_has_no_structured_content(
                    self,
                    public_result,
                    expected_message="The FormOwl tool could not complete the request.",
                )
                self.assertNotIn("_meta", public_result)
                self.assertEqual(caught, [])
                self.assertEqual(handler_calls, [expected_prepared_arguments])
                self.assertEqual(bridge.resolve_calls, 1)
                self.assertEqual(len(bridge.decisions), 1)
                self.assertTrue(bridge.decisions[0]["allowed"])
                self.assertEqual(
                    bridge.decisions[0]["reason_code"],
                    "tool_authorized",
                )
                self.assertEqual(bridge.http_denials, [])
                self.assertEqual(semantic_gateway.tool_call_logs, [])
                rendered_state = repr(
                    {
                        "response": public_result,
                        "warnings": [str(item.message) for item in caught],
                        "authorization": bridge.decisions,
                        "tool_logs": [item.to_dict() for item in semantic_gateway.tool_call_logs],
                    }
                )
                if raw_marker is not None:
                    self.assertNotIn(raw_marker, rendered_state)

    def test_dispatcher_rejects_configured_async_handler_before_dispatch_without_warning(
        self,
    ) -> None:
        execution_started: list[bool] = []

        async def async_handler(_arguments: dict[str, Any]) -> dict[str, Any]:
            execution_started.append(True)
            return {"status": "ok", "raw_value": "raw-async-handler-secret"}

        bridge = _FakeBridge(self.config, self.google_client)
        semantic_gateway = SemanticMcpGateway(upload_session_handler=async_handler)
        bundle = create_connected_mcp_application(
            bridge=bridge,
            config=self.config,
            google_client=self.google_client,
            semantic_gateway=semantic_gateway,
            oauth_route_provider=lambda **_kwargs: [],
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        principal_token = _current_principal.set(bridge.principal)
        request_token = _current_request_id.set("mcp_req_async_handler")
        try:
            with (
                patch.object(
                    semantic_gateway,
                    "dispatch_tool",
                    wraps=semantic_gateway.dispatch_tool,
                ) as dispatch,
                warnings.catch_warnings(record=True) as caught,
            ):
                warnings.simplefilter("always")
                result = asyncio.run(
                    bundle.dispatcher.call_tool(
                        "open_upload_session",
                        {
                            "intent": "Upload governed mail evidence.",
                            "intended_asset_type": "pst",
                        },
                    )
                )
                gc.collect()
        finally:
            _current_request_id.reset(request_token)
            _current_principal.reset(principal_token)

        dispatch.assert_not_called()
        self.assertEqual(execution_started, [])
        self.assertEqual(caught, [])
        public_result = result.model_dump(by_alias=True, exclude_none=True)
        _assert_error_result_has_no_structured_content(
            self,
            public_result,
            expected_message="The FormOwl tool could not complete the request.",
        )
        self.assertNotIn("_meta", public_result)
        self.assertNotIn("raw-async-handler-secret", repr(public_result))
        self.assertEqual(bridge.resolve_calls, 1)
        self.assertEqual(len(bridge.decisions), 1)
        self.assertTrue(bridge.decisions[0]["allowed"])
        self.assertEqual(bridge.decisions[0]["reason_code"], "tool_authorized")
        self.assertEqual(bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_dispatcher_does_not_swallow_cancellation(self) -> None:
        principal_token = _current_principal.set(self.bridge.principal)
        request_token = _current_request_id.set("mcp_req_cancelled_handler")
        try:
            with patch.object(
                self.semantic_gateway,
                "dispatch_tool",
                side_effect=asyncio.CancelledError("raw-cancellation-secret"),
            ) as dispatch:
                with self.assertRaises(asyncio.CancelledError) as caught:
                    asyncio.run(
                        self.bundle.dispatcher.call_tool(
                            "open_upload_session",
                            {
                                "intent": "Upload governed mail evidence.",
                                "intended_asset_type": "pst",
                            },
                        )
                    )
        finally:
            _current_request_id.reset(request_token)
            _current_principal.reset(principal_token)

        dispatch.assert_called_once()
        self.assertEqual(str(caught.exception), "raw-cancellation-secret")
        self.assertEqual(self.bridge.resolve_calls, 1)
        self.assertEqual(len(self.bridge.decisions), 1)
        self.assertTrue(self.bridge.decisions[0]["allowed"])
        self.assertEqual(self.bridge.decisions[0]["reason_code"], "tool_authorized")
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_unsafe_handler_payload_returns_generic_error_after_truthful_authorization(
        self,
    ) -> None:
        unsafe_handler_calls: list[dict[str, Any]] = []
        raw_values = (
            "raw-handler-token-secret",
            "/tmp/raw-handler-path-secret",
            "raw-storage-secret",
        )

        def unsafe_handler(arguments: dict[str, Any]) -> dict[str, Any]:
            unsafe_handler_calls.append(dict(arguments))
            return {
                "status": "ok",
                "token": raw_values[0],
                "raw_path": raw_values[1],
                "bucket": raw_values[2],
            }

        unsafe_bundle = create_connected_mcp_application(
            bridge=self.bridge,
            config=self.config,
            google_client=self.google_client,
            semantic_gateway=SemanticMcpGateway(upload_session_handler=unsafe_handler),
            oauth_route_provider=lambda **_kwargs: [],
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
        }
        before = json.dumps(
            {
                "active_grants": self.bridge.active_grants,
                "http_denials": self.bridge.http_denials,
                "handler_calls": self.handler_calls,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        with TestClient(unsafe_bundle.app, raise_server_exceptions=False) as client:
            response = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "unsafe_handler_payload",
                    {"name": "open_upload_session", "arguments": arguments},
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        _assert_error_result_has_no_structured_content(
            self,
            result,
            expected_message="The FormOwl tool could not complete the request.",
        )
        self.assertNotIn("_meta", result)
        self.assertEqual(len(unsafe_handler_calls), 1)
        self.assertEqual(
            unsafe_handler_calls[0]["requester_user_id"],
            "user_beta",
        )
        self.assertEqual(
            unsafe_handler_calls[0]["workspace_id"],
            "workspace_beta",
        )
        self.assertEqual(self.bridge.authenticate_calls, 1)
        self.assertEqual(self.bridge.resolve_calls, 1)
        self.assertEqual(len(self.bridge.decisions), 1)
        self.assertTrue(self.bridge.decisions[0]["allowed"])
        self.assertEqual(
            self.bridge.decisions[0]["reason_code"],
            "tool_authorized",
        )
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])
        after = json.dumps(
            {
                "active_grants": self.bridge.active_grants,
                "http_denials": self.bridge.http_denials,
                "handler_calls": self.handler_calls,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(after, before)
        for raw_value in raw_values:
            self.assertNotIn(raw_value, response.text)
            self.assertNotIn(raw_value, str(self.bridge.decisions))

    def test_malformed_denial_http_response_and_audit_use_only_normalized_values(
        self,
    ) -> None:
        malformed = _MalformedDenial(
            error="invalid_token\r\nX-Leak: raw-error-secret",
            reason_code="raw/reason/secret",
            http_status=[],
        )

        with patch.object(
            self.bridge,
            "authenticate_access_token",
            side_effect=malformed,
        ) as authenticate:
            with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/mcp",
                    json=_request("tools/list", "malformed_denial"),
                    headers=_mcp_headers(bearer="raw-bearer-secret"),
                )

        authenticate.assert_called_once()
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json(), {"error": "invalid_token"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertEqual(
            response.headers["www-authenticate"],
            'Bearer resource_metadata="https://formowl.example/.well-known/'
            'oauth-protected-resource", error="invalid_token", '
            'error_description="Authentication required."',
        )
        self.assertEqual(self.bridge.authenticate_calls, 0)
        self.assertEqual(self.bridge.resolve_calls, 0)
        self.assertEqual(self.bridge.decisions, [])
        self.assertEqual(len(self.bridge.http_denials), 1)
        self.assertEqual(
            self.bridge.http_denials[0]["reason_code"],
            "authentication_failed",
        )
        self.assertTrue(self.bridge.http_denials[0]["raw_token_present"])
        self.assertEqual(self.handler_calls, [])
        for raw_value in (
            "raw-malformed-denial-secret",
            "raw-error-secret",
            "raw/reason/secret",
            "raw-bearer-secret",
        ):
            self.assertNotIn(raw_value, response.text)
            self.assertNotIn(raw_value, str(dict(response.headers)))
            self.assertNotIn(raw_value, str(self.bridge.http_denials))

    def test_generated_identifier_guard_is_safe_and_fails_before_any_effect(self) -> None:
        def mutable_snapshot() -> bytes:
            return json.dumps(
                {
                    "authenticate_calls": self.bridge.authenticate_calls,
                    "resolve_calls": self.bridge.resolve_calls,
                    "decisions": self.bridge.decisions,
                    "http_denials": self.bridge.http_denials,
                    "handler_calls": self.handler_calls,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

        with patch("formowl_gateway.remote.secrets.token_hex", return_value="a" * 32):
            generated = _new_safe_id("mcp_req")

        self.assertEqual(generated, f"mcp_req_{'a' * 32}")
        self.assertRegex(generated, r"^mcp_req_[0-9a-f]{32}$")

        before = mutable_snapshot()
        invalid_value = "unsafe/value"
        with patch(
            "formowl_gateway.remote.secrets.token_hex",
            return_value=invalid_value,
        ):
            with self.assertRaises(RuntimeError) as caught:
                _new_safe_id("mcp_req")

            self.assertEqual(str(caught.exception), "generated identifier is invalid")
            self.assertEqual(mutable_snapshot(), before)

            with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/mcp",
                    json=_request("tools/list", "unsafe_generated_identifier"),
                    headers=_mcp_headers(),
                )

        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(response.json(), {"error": "internal_error"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertNotIn(invalid_value, response.text)
        self.assertNotIn(invalid_value, str(dict(response.headers)))
        self.assertEqual(mutable_snapshot(), before)
        self.assertEqual(self.bridge.authenticate_calls, 0)
        self.assertEqual(self.bridge.resolve_calls, 0)
        self.assertEqual(self.bridge.decisions, [])
        self.assertEqual(self.bridge.http_denials, [])
        self.assertEqual(self.handler_calls, [])

    def test_current_workspace_upload_is_bound_and_forgery_fails_before_handler(self) -> None:
        valid_arguments = {
            "intent": "Upload governed mail evidence.",
            "intended_asset_type": "pst",
            "owner_scope_type": "workspace",
            "owner_scope_id": "workspace_beta",
            "visibility_scope": "workspace",
            "permission_scope": {
                "scope_type": "workspace",
                "scope_id": "workspace_beta",
                "visibility": "restricted",
            },
        }
        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            valid = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "upload_valid",
                    {"name": "open_upload_session", "arguments": valid_arguments},
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )
            forged = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "upload_forged",
                    {
                        "name": "open_upload_session",
                        "arguments": {
                            **valid_arguments,
                            "workspace_id": "workspace_other",
                            "requester_user_id": "user_other",
                            "role": "owner",
                            "grants": [{"grant_id": "grant_forged"}],
                        },
                    },
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )
            cross_workspace = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "upload_cross_workspace",
                    {
                        "name": "open_upload_session",
                        "arguments": {
                            **valid_arguments,
                            "owner_scope_id": "workspace_other",
                        },
                    },
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        valid_result = valid.json()["result"]
        self.assertFalse(valid_result["isError"])
        upload_schema = next(
            tool.outputSchema
            for tool in build_remote_tool_descriptors(required_scope="formowl.use")
            if tool.name == "open_upload_session"
        )
        jsonschema.validate(instance=valid_result["structuredContent"], schema=upload_schema)
        _assert_error_result_has_no_structured_content(
            self,
            forged.json()["result"],
            expected_message="The FormOwl tool arguments were rejected.",
        )
        _assert_error_result_has_no_structured_content(
            self,
            cross_workspace.json()["result"],
            expected_message="The FormOwl tool arguments were rejected.",
        )
        self.assertEqual(len(self.handler_calls), 1)
        injected = self.handler_calls[0]
        self.assertEqual(injected["requester_user_id"], "user_beta")
        self.assertEqual(injected["workspace_id"], "workspace_beta")
        self.assertEqual(injected["session_id"], "oauthsid_beta")
        self.assertNotIn("valid.jwt.value", str(injected))
        for forbidden in ("workspace_other", "user_other", "grant_forged"):
            self.assertNotIn(forbidden, forged.text)

    def test_removed_membership_and_audit_failure_fail_closed_before_handler(self) -> None:
        self.bridge.resolve_denial = _Denied(
            "insufficient_scope",
            "workspace_membership_inactive",
            403,
        )
        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            removed = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "removed_membership",
                    {
                        "name": "open_upload_session",
                        "arguments": {
                            "intent": "Upload mail.",
                            "intended_asset_type": "pst",
                        },
                    },
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )
            self.bridge.resolve_denial = None
            self.bridge.fail_allowed_audit = True
            audit_failed = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "audit_failure",
                    {
                        "name": "open_upload_session",
                        "arguments": {
                            "intent": "Upload mail.",
                            "intended_asset_type": "pst",
                        },
                    },
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        _assert_error_result_has_no_structured_content(
            self,
            removed.json()["result"],
            expected_message="Authorization is insufficient.",
        )
        self.assertIn(
            "insufficient_scope",
            removed.json()["result"]["_meta"]["mcp/www_authenticate"][0],
        )
        self.assertNotIn("workspace_membership_inactive", removed.text)
        self.assertEqual(len(self.bridge.decisions), 1)
        self.assertFalse(self.bridge.decisions[0]["allowed"])
        self.assertEqual(
            self.bridge.decisions[0]["reason_code"],
            "workspace_membership_inactive",
        )
        self.assertEqual(self.handler_calls, [])
        result = audit_failed.json()["result"]
        _assert_error_result_has_no_structured_content(
            self,
            result,
            expected_message="The FormOwl authorization decision could not be recorded.",
        )
        self.assertNotIn("secret-bearer-value", audit_failed.text)
        self.assertEqual(self.handler_calls, [])

    def test_invalid_token_unknown_tool_and_handler_failure_have_no_structured_content(
        self,
    ) -> None:
        self.bridge.resolve_denial = _Denied(
            "invalid_token",
            "token_session_revoked",
            401,
        )
        with TestClient(self.bundle.app, raise_server_exceptions=False) as client:
            invalid_token = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "invalid_token",
                    {"name": "whoami", "arguments": {}},
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )
            self.bridge.resolve_denial = None
            unknown_tool = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "unknown_tool",
                    {"name": "unknown_backend_tool", "arguments": {}},
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )
            self.fail_handler = True
            handler_failed = client.post(
                "/mcp",
                json=_request(
                    "tools/call",
                    "handler_failure",
                    {
                        "name": "open_upload_session",
                        "arguments": {
                            "intent": "Upload mail.",
                            "intended_asset_type": "pst",
                        },
                    },
                ),
                headers=_mcp_headers(bearer="valid.jwt.value"),
            )

        _assert_error_result_has_no_structured_content(
            self,
            invalid_token.json()["result"],
            expected_message="Authentication required.",
        )
        self.assertIn(
            "invalid_token",
            invalid_token.json()["result"]["_meta"]["mcp/www_authenticate"][0],
        )
        _assert_error_result_has_no_structured_content(
            self,
            unknown_tool.json()["result"],
            expected_message="The requested FormOwl tool is unavailable.",
        )
        _assert_error_result_has_no_structured_content(
            self,
            handler_failed.json()["result"],
            expected_message="The FormOwl tool could not complete the request.",
        )
        rendered = invalid_token.text + unknown_tool.text + handler_failed.text
        self.assertNotIn("token_session_revoked", rendered)
        self.assertNotIn("unknown_backend_tool", rendered)
        self.assertNotIn("secret-bearer-value", rendered)

    def test_connected_factory_rejects_manual_identity_environment(self) -> None:
        with self.assertRaisesRegex(Exception, "manual session identity"):
            create_connected_mcp_application(
                bridge=self.bridge,
                config=self.config,
                google_client=self.google_client,
                semantic_gateway=self.semantic_gateway,
                oauth_route_provider=lambda **_kwargs: [],
                clock=_now,
                environ={
                    "FORMOWL_AUTH_MODE": "oauth_google",
                    "FORMOWL_MCP_ACTOR_USER_ID": "manual_user",
                },
            )
        with self.assertRaisesRegex(Exception, "Google-backed OAuth"):
            create_connected_mcp_application(
                bridge=self.bridge,
                config=self.config,
                google_client=self.google_client,
                semantic_gateway=self.semantic_gateway,
                oauth_route_provider=lambda **_kwargs: [],
                clock=_now,
                environ={"FORMOWL_AUTH_MODE": "manual_trusted_internal"},
            )


@unittest.skipIf(_IMPORT_ERROR is not None, f"issue #20 dependencies unavailable: {_IMPORT_ERROR}")
class RemoteMcpRunnerTests(unittest.TestCase):
    def test_runner_disables_proxy_and_access_logs_and_remote_main_delegates(self) -> None:
        fake_uvicorn = SimpleNamespace(calls=[])

        def run(app: Any, **kwargs: Any) -> None:
            fake_uvicorn.calls.append((app, kwargs))

        fake_uvicorn.run = run
        application = object.__new__(ConnectedMcpApplication)
        object.__setattr__(application, "app", object())
        object.__setattr__(application, "server", object())
        object.__setattr__(application, "session_manager", object())
        object.__setattr__(application, "dispatcher", object())
        object.__setattr__(application, "bridge", object())
        object.__setattr__(application, "config", object())

        with patch.dict("sys.modules", {"uvicorn": fake_uvicorn}):
            run_connected_mcp_application(application, host="127.0.0.1", port=8443)

        self.assertEqual(fake_uvicorn.calls[0][1]["access_log"], False)
        self.assertEqual(fake_uvicorn.calls[0][1]["proxy_headers"], False)
        with patch("formowl_gateway.runtime.main", return_value=17) as connected_main:
            self.assertEqual(remote_main(), 17)
        connected_main.assert_called_once_with()

    def test_gateway_does_not_emit_sensitive_values_to_logs(self) -> None:
        logger = logging.getLogger()
        records: list[logging.LogRecord] = []

        class Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = Handler()
        logger.addHandler(handler)
        try:
            with patch("formowl_gateway.runtime.main", return_value=1):
                remote_main()
        finally:
            logger.removeHandler(handler)
        rendered = "\n".join(record.getMessage() for record in records)
        self.assertNotIn("Authorization", rendered)
        self.assertNotIn("code=", rendered)
        self.assertNotIn("state=", rendered)
        self.assertNotIn("secret", rendered.lower())


@unittest.skipIf(_IMPORT_ERROR is not None, f"issue #20 dependencies unavailable: {_IMPORT_ERROR}")
class RemoteSafeExceptionMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_composition_helpers_enforce_exact_safe_boundaries(self) -> None:
        delegated_paths: list[str] = []

        async def downstream(
            scope: dict[str, Any],
            _receive: Any,
            _send: Any,
        ) -> None:
            delegated_paths.append(scope["path"])

        exact_app = ExactMcpPathApp(downstream)
        await exact_app(
            {"type": "http", "method": "POST", "path": "/mcp"},
            _empty_receive,
            _discard_send,
        )
        self.assertEqual(delegated_paths, ["/mcp"])

        not_found_messages: list[dict[str, Any]] = []

        async def collect_not_found(message: dict[str, Any]) -> None:
            not_found_messages.append(message)

        await exact_app(
            {"type": "http", "method": "POST", "path": "/mcp/"},
            _empty_receive,
            collect_not_found,
        )
        start = next(
            message for message in not_found_messages if message["type"] == "http.response.start"
        )
        headers = {
            bytes(name).decode("ascii"): bytes(value).decode("ascii")
            for name, value in start["headers"]
        }
        self.assertEqual(start["status"], 404)
        self.assertEqual(
            {name.lower(): value for name, value in headers.items()},
            {
                "content-length": "21",
                "content-type": "application/json",
                "cache-control": "no-store",
                "pragma": "no-cache",
                "referrer-policy": "no-referrer",
            },
        )
        self.assertEqual(
            b"".join(
                message.get("body", b"")
                for message in not_found_messages
                if message["type"] == "http.response.body"
            ),
            b'{"error":"not_found"}',
        )
        with self.assertRaisesRegex(ValueError, "connected MCP path must be /mcp"):
            ExactMcpPathApp(downstream, path="/mcp/")

        lifecycle: list[str] = []

        @asynccontextmanager
        async def run_manager() -> Any:
            lifecycle.append("entered")
            try:
                yield
            finally:
                lifecycle.append("exited")

        manager = SimpleNamespace(run=run_manager)
        lifespan = _SessionManagerLifespan(manager)
        async with lifespan(SimpleNamespace()):
            self.assertEqual(lifecycle, ["entered"])
        self.assertEqual(lifecycle, ["entered", "exited"])

        config = _Config()
        google_client = object()
        bridge = _FakeBridge(config, google_client)
        semantic_gateway = SemanticMcpGateway()
        _validate_connected_dependencies(
            bridge=bridge,
            config=config,
            google_client=google_client,
            semantic_gateway=semantic_gateway,
            clock=_now,
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "rejects manual session identity",
        ):
            _validate_connected_dependencies(
                bridge=bridge,
                config=config,
                google_client=google_client,
                semantic_gateway=semantic_gateway,
                clock=_now,
                environ={
                    "FORMOWL_AUTH_MODE": "oauth_google",
                    "FORMOWL_MCP_SESSION_ID": "private-session",
                },
            )
        self.assertEqual(_required_scope(config), "formowl.use")
        self.assertEqual(
            _canonical_metadata_url(config),
            "https://formowl.example/.well-known/oauth-protected-resource",
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "requires exactly formowl.use",
        ):
            _required_scope(SimpleNamespace(scopes=("other.scope",)))
        with self.assertRaisesRegex(
            ValueError,
            "metadata URL",
        ):
            _canonical_metadata_url(
                SimpleNamespace(
                    protected_resource_metadata_url=(
                        "https://formowl.example/meta?redirect=https://evil.example"
                    )
                )
            )
        self.assertEqual(
            _no_store_headers(),
            {
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
            },
        )
        descriptor = _tool_descriptor(
            name="whoami",
            description="Return the authenticated actor.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema={"type": "object"},
            schemes=[{"type": "oauth2", "scopes": ["formowl.use"]}],
        ).model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(descriptor["name"], "whoami")
        self.assertTrue(descriptor["annotations"]["readOnlyHint"])
        self.assertFalse(descriptor["annotations"]["destructiveHint"])

        sentinel_app = object()
        with patch(
            "formowl_gateway.remote.create_connected_mcp_application",
            return_value=SimpleNamespace(app=sentinel_app),
        ) as create_application:
            self.assertIs(
                create_connected_mcp_asgi_app(marker="direct-wrapper"),
                sentinel_app,
            )
        create_application.assert_called_once_with(marker="direct-wrapper")

    async def test_started_http_exception_closes_incomplete_body_without_leak(self) -> None:
        async def failing_started_app(
            _scope: dict[str, Any],
            _receive: Any,
            send: Any,
        ) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/octet-stream")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"partial-safe-body",
                    "more_body": True,
                }
            )
            raise RuntimeError("private-token callback?code=private&state=private")

        messages: list[dict[str, Any]] = []

        async def collect_send(message: dict[str, Any]) -> None:
            messages.append(message)

        await SafeExceptionMiddleware(failing_started_app)(
            {
                "type": "http",
                "method": "GET",
                "path": "/mcp",
                "query_string": b"code=private&state=private",
                "headers": [(b"authorization", b"Bearer private-token")],
            },
            _empty_receive,
            collect_send,
        )

        self.assertEqual(
            messages,
            [
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/octet-stream")],
                },
                {
                    "type": "http.response.body",
                    "body": b"partial-safe-body",
                    "more_body": True,
                },
                {
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False,
                },
            ],
        )
        self.assertNotIn("private-token", repr(messages))
        self.assertNotIn("code=private", repr(messages))
        self.assertNotIn("state=private", repr(messages))

    async def test_lifespan_startup_exception_is_not_swallowed(self) -> None:
        async def failing_lifespan_app(
            _scope: dict[str, Any],
            _receive: Any,
            _send: Any,
        ) -> None:
            raise RuntimeError("session_manager_startup_failed")

        middleware = SafeExceptionMiddleware(failing_lifespan_app)

        with self.assertRaisesRegex(RuntimeError, "session_manager_startup_failed"):
            await middleware(
                {"type": "lifespan"},
                _empty_receive,
                _discard_send,
            )

    async def test_http_exception_returns_generic_500_without_logging_secret(self) -> None:
        async def failing_http_app(
            _scope: dict[str, Any],
            _receive: Any,
            _send: Any,
        ) -> None:
            raise RuntimeError("secret-bearer-value callback?code=private&state=private")

        messages: list[dict[str, Any]] = []
        records: list[logging.LogRecord] = []

        async def collect_send(message: dict[str, Any]) -> None:
            messages.append(message)

        class Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        logger = logging.getLogger()
        handler = Handler()
        logger.addHandler(handler)
        try:
            await SafeExceptionMiddleware(failing_http_app)(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/oauth/google/callback",
                    "query_string": b"code=private&state=private",
                    "headers": [(b"authorization", b"Bearer secret-bearer-value")],
                },
                _empty_receive,
                collect_send,
            )
        finally:
            logger.removeHandler(handler)

        start = next(message for message in messages if message["type"] == "http.response.start")
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        self.assertEqual(start["status"], 500)
        self.assertEqual(body, b'{"error":"internal_error"}')
        rendered = "\n".join(record.getMessage() for record in records)
        self.assertNotIn("secret-bearer-value", rendered)
        self.assertNotIn("code=private", rendered)
        self.assertNotIn("state=private", rendered)


def _assert_error_result_has_no_structured_content(
    test_case: unittest.TestCase,
    result: Mapping[str, Any],
    *,
    expected_message: str,
) -> None:
    test_case.assertTrue(result["isError"])
    test_case.assertNotIn("structuredContent", result)
    test_case.assertEqual(result["content"], [{"type": "text", "text": expected_message}])


async def _empty_receive() -> dict[str, Any]:
    return {"type": "http.disconnect"}


async def _discard_send(_message: dict[str, Any]) -> None:
    return None


PUBLIC_TOOLS = [
    {"tool_name": "open_upload_session"},
    {"tool_name": "create_ingestion_job"},
    {"tool_name": "list_observations"},
    {"tool_name": "preview_graph_candidates"},
    {"tool_name": "query_effective_graph"},
    {"tool_name": "query_effective_graph_view"},
    {"tool_name": "query_mail_evidence"},
    {"tool_name": "answer_mail_case_progress"},
    {"tool_name": "request_graph_access"},
    {"tool_name": "submit_graph_review_decision"},
    {"tool_name": "generate_wiki_draft_from_graph_view"},
]


if __name__ == "__main__":
    unittest.main()
