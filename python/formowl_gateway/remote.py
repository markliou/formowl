"""Connected OAuth and Streamable HTTP MCP application for FormOwl.

This module is the connected deployment boundary.  It composes the OAuth
authorization routes owned by :mod:`formowl_auth` with the official MCP Python
SDK's stateless Streamable HTTP transport on the exact ``/mcp`` resource.

The legacy JSON-line and hand-built JSON-RPC gateways remain compatibility
surfaces.  They are not used by this connected application.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import json
import logging
import os
import re
import secrets
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urlparse

from formowl_contract import ContractValidationError
from mcp import types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Mount

from .jsonrpc import _tool_to_json_rpc_schema, _validate_semantic_tool_arguments
from .semantic import (
    PUBLIC_TOOL_SCHEMAS,
    SemanticMcpGateway,
    validate_public_gateway_payload,
)


Clock = Callable[[], datetime]
AsgiApp = Callable[
    [
        dict[str, Any],
        Callable[[], Awaitable[dict[str, Any]]],
        Callable[[dict[str, Any]], Awaitable[None]],
    ],
    Awaitable[None],
]
OAuthRouteProvider = Callable[..., Sequence[BaseRoute]]

_SAFE_MACHINE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_OAUTH_ERROR = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FORBIDDEN_CONNECTED_ENV = (
    "FORMOWL_MCP_SESSION_ID",
    "FORMOWL_MCP_ACTOR_USER_ID",
    "FORMOWL_MCP_WORKSPACE_ID",
)
_AUTH_MODE_ENV = "FORMOWL_AUTH_MODE"
_DEFAULT_REQUIRED_SCOPE = "formowl.use"
_MCP_PATH = "/mcp"
_STRICT_TOOL_RESULT_ERROR = "connected MCP tool result must contain strict JSON values"
_LOGGER = logging.getLogger(__name__)

_current_principal: ContextVar[Any | None] = ContextVar(
    "formowl_remote_oauth_principal",
    default=None,
)
_current_request_id: ContextVar[str | None] = ContextVar(
    "formowl_remote_request_id",
    default=None,
)

_TOOL_TITLES = {
    "whoami": "Show current FormOwl identity",
    "open_upload_session": "Open an upload session",
    "create_ingestion_job": "Create an ingestion job",
    "list_observations": "List extracted observations",
    "preview_graph_candidates": "Preview graph candidates",
    "query_effective_graph": "Query the effective graph (legacy alias)",
    "query_effective_graph_view": "Query the effective graph view",
    "query_mail_evidence": "Query governed mail evidence",
    "answer_mail_case_progress": "Answer mail case progress",
    "request_graph_access": "Request graph access",
    "submit_graph_review_decision": "Submit a graph review decision",
    "generate_wiki_draft_from_graph_view": "Generate a wiki draft from a graph view",
}
_READ_ONLY_TOOL_NAMES = {
    "whoami",
    "list_observations",
    "preview_graph_candidates",
    "query_effective_graph",
    "query_effective_graph_view",
    "query_mail_evidence",
    "answer_mail_case_progress",
}
_SEMANTIC_HANDLER_ATTRIBUTES = {
    "open_upload_session": "upload_session_handler",
    "create_ingestion_job": "ingestion_handler",
    "list_observations": "observation_handler",
    "preview_graph_candidates": "preview_handler",
    "query_effective_graph": "retrieval_handler",
    "query_effective_graph_view": "retrieval_handler",
    "query_mail_evidence": "mail_evidence_handler",
    "answer_mail_case_progress": "mail_case_progress_handler",
    "request_graph_access": "access_request_handler",
    "submit_graph_review_decision": "review_decision_handler",
    "generate_wiki_draft_from_graph_view": "wiki_projection_handler",
}


@dataclass(frozen=True)
class _ConnectedToolPolicy:
    allowed_roles: frozenset[str]
    requires_grant: bool


_CONNECTED_TOOL_POLICIES: Mapping[str, _ConnectedToolPolicy] = MappingProxyType(
    {
        "whoami": _ConnectedToolPolicy(
            allowed_roles=frozenset({"owner", "member", "viewer"}),
            requires_grant=False,
        ),
        "open_upload_session": _ConnectedToolPolicy(
            allowed_roles=frozenset({"owner", "member"}),
            requires_grant=False,
        ),
    }
)

_WHOAMI_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}
_WHOAMI_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["user_id", "display_name", "current_workspace", "auth_mode"],
    "properties": {
        "user_id": {"type": "string"},
        "display_name": {"type": "string"},
        "current_workspace": {
            "type": "object",
            "required": ["workspace_id", "role"],
            "properties": {
                "workspace_id": {"type": "string"},
                "role": {"type": "string", "enum": ["owner", "member", "viewer"]},
            },
            "additionalProperties": False,
        },
        "auth_mode": {"const": "google_oidc_oauth"},
    },
    "additionalProperties": False,
}
_SEMANTIC_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["result_type", "status", "data", "warnings"],
    "properties": {
        "result_type": {"type": "string"},
        "status": {
            "type": "string",
            "enum": [
                "ok",
                "partial",
                "not_found",
                "permission_denied",
                "pending_review",
                "error",
            ],
        },
        "data": {},
        "context_package": {"type": ["object", "null"]},
        "source_refs": {"type": ["array", "null"]},
        "evidence_snapshot_ids": {"type": ["array", "null"]},
        "citations": {"type": ["array", "null"]},
        "permission_scope": {"type": ["object", "null"]},
        "warnings": {"type": ["array", "null"], "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


class OAuthBridgeProtocol(Protocol):
    config: Any
    google_client: Any

    def authenticate_access_token(
        self,
        raw_token: str,
        *,
        required_scope: str,
        resource: str,
        now: datetime,
    ) -> Any: ...

    def resolve_actor_context(self, principal: Any, *, now: datetime) -> Any: ...

    def record_mcp_authorization_decision(
        self,
        *,
        principal: Any | None,
        request_id: str,
        tool_call_id: str,
        tool_name: str,
        workspace_id: str | None,
        allowed: bool,
        reason_code: str,
        now: datetime,
    ) -> Any: ...

    def record_mcp_http_authentication_denial(
        self,
        *,
        raw_token: str | None,
        request_id: str,
        reason_code: str,
        required_scope: str,
        resource: str,
        now: datetime,
    ) -> Any: ...

    def whoami_payload(self, actor_context: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ConnectedMcpApplication:
    """Dependency bundle for a connected FormOwl OAuth/MCP application."""

    app: Starlette
    server: Server[Any, Any]
    session_manager: StreamableHTTPSessionManager
    dispatcher: "RemoteMcpDispatcher"
    bridge: OAuthBridgeProtocol
    config: Any
    manages_session_manager_lifespan: bool


class SafeExceptionMiddleware:
    """Return a generic response without logging query strings or credentials."""

    def __init__(self, app: AsgiApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        response_started = False
        response_complete = False

        async def safe_send(message: dict[str, Any]) -> None:
            nonlocal response_started, response_complete
            if message.get("type") == "http.response.start":
                response_started = True
            elif message.get("type") == "http.response.body" and not message.get(
                "more_body", False
            ):
                response_complete = True
            await send(message)

        try:
            await self.app(scope, receive, safe_send)
        except Exception:
            if scope.get("type") != "http":
                raise
            if not response_started:
                response = JSONResponse(
                    {"error": "internal_error"},
                    status_code=500,
                    headers=_no_store_headers(),
                )
                await response(scope, receive, send)
            elif not response_complete:
                await send({"type": "http.response.body", "body": b"", "more_body": False})


class ExactMcpPathApp:
    """Delegate only the exact canonical MCP resource path to the SDK."""

    def __init__(self, app: AsgiApp, *, path: str = _MCP_PATH) -> None:
        if path != _MCP_PATH:
            raise ValueError("connected MCP path must be /mcp")
        self.app = app
        self.path = path

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http" or scope.get("path") != self.path:
            response = JSONResponse(
                {"error": "not_found"},
                status_code=404,
                headers=_no_store_headers(),
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class BearerAuthenticationMiddleware:
    """Authenticate one request-scoped bearer without retaining the raw token."""

    def __init__(
        self,
        app: AsgiApp,
        *,
        bridge: OAuthBridgeProtocol,
        resource: str,
        required_scope: str,
        metadata_url: str,
        clock: Clock,
        discovery_only: bool = False,
    ) -> None:
        self.app = app
        self.bridge = bridge
        self.resource = resource
        self.required_scope = required_scope
        self.metadata_url = metadata_url
        self.clock = clock
        self.discovery_only = discovery_only

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        request_id = _new_safe_id("mcp_req")
        principal: Any | None = None
        raw_token: str | None = None
        try:
            if not self.discovery_only:
                raw_token = _extract_bearer_token(scope)
                if raw_token is not None:
                    principal = self.bridge.authenticate_access_token(
                        raw_token,
                        required_scope=self.required_scope,
                        resource=self.resource,
                        now=_aware_now(self.clock),
                    )
                    raw_token = ""
        except Exception as exc:
            denial = _safe_denial(exc)
            try:
                self.bridge.record_mcp_http_authentication_denial(
                    raw_token=raw_token,
                    request_id=request_id,
                    reason_code=denial.reason_code,
                    required_scope=self.required_scope,
                    resource=self.resource,
                    now=_aware_now(self.clock),
                )
            except Exception:
                denial = _SafeDenial(
                    error="server_error",
                    reason_code="authentication_audit_failed",
                    http_status=500,
                )
            raw_token = None
            await _send_http_oauth_denial(
                scope,
                receive,
                send,
                denial=denial,
                metadata_url=self.metadata_url,
            )
            return

        principal_token = _current_principal.set(principal)
        request_token = _current_request_id.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_request_id.reset(request_token)
            _current_principal.reset(principal_token)


class _SessionManagerLifespan:
    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager

    def __call__(self, _app: Starlette) -> AbstractAsyncContextManager[None]:
        return self.session_manager.run()


class _RedactingMcpServer(Server[Any, Any]):
    async def _get_cached_tool_definition(self, tool_name: str) -> mcp_types.Tool | None:
        # The SDK warning includes an unknown caller-controlled tool name. Keep
        # its cache behavior but emit only a fixed operator signal.
        if tool_name not in self._tool_cache:
            if mcp_types.ListToolsRequest in self.request_handlers:
                await self.request_handlers[mcp_types.ListToolsRequest](None)

        tool = self._tool_cache.get(tool_name)
        if tool is None:
            _LOGGER.warning("unknown_tool request rejected")
        return tool


class RemoteMcpDispatcher:
    """Bind protected MCP tools to fresh FormOwl authorization state."""

    def __init__(
        self,
        *,
        bridge: OAuthBridgeProtocol,
        config: Any,
        semantic_gateway: SemanticMcpGateway,
        clock: Clock,
        enabled_tool_names: Collection[str],
    ) -> None:
        self.bridge = bridge
        self.config = config
        self.semantic_gateway = semantic_gateway
        self.clock = clock
        self.metadata_url = _canonical_metadata_url(config)
        self.required_scope = _required_scope(config)
        self.discovery_only = getattr(config, "chatgpt_callback_mode", None) == "discovery_only"
        self.enabled_tool_names = frozenset(enabled_tool_names)
        self.tool_policies = _CONNECTED_TOOL_POLICIES
        if "whoami" not in self.enabled_tool_names:
            raise ContractValidationError("connected MCP must expose whoami")
        if not self.enabled_tool_names <= frozenset(self.tool_policies):
            raise ContractValidationError(
                "connected MCP enabled tool lacks an authorization policy"
            )

    async def list_tools(self) -> list[mcp_types.Tool]:
        return build_remote_tool_descriptors(
            required_scope=self.required_scope,
            enabled_tool_names=self.enabled_tool_names,
        )

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> mcp_types.CallToolResult:
        principal = _current_principal.get()
        request_id = _current_request_id.get() or _new_safe_id("mcp_req")
        tool_call_id = _new_safe_id("mcp_call")
        safe_tool_name = tool_name if tool_name in self.tool_policies else "unknown_tool"

        if tool_name not in self.enabled_tool_names:
            if not self._record_decision(
                principal=principal,
                request_id=request_id,
                tool_call_id=tool_call_id,
                tool_name=safe_tool_name,
                workspace_id=None,
                allowed=False,
                reason_code="unknown_tool",
            ):
                return _safe_tool_error(
                    error="server_error",
                    reason_code="authorization_audit_failed",
                    message="The FormOwl authorization decision could not be recorded.",
                )
            return _safe_tool_error(
                error="invalid_request",
                reason_code="unknown_tool",
                message="The requested FormOwl tool is unavailable.",
            )

        if self.discovery_only or principal is None:
            if not self._record_decision(
                principal=None,
                request_id=request_id,
                tool_call_id=tool_call_id,
                tool_name=safe_tool_name,
                workspace_id=None,
                allowed=False,
                reason_code="authentication_required",
            ):
                return _safe_tool_error(
                    error="server_error",
                    reason_code="authorization_audit_failed",
                    message="The FormOwl authorization decision could not be recorded.",
                )
            return self._authorization_error(
                error="invalid_token",
                reason_code="authentication_required",
                message="Authentication required.",
            )

        try:
            actor_context = self.bridge.resolve_actor_context(
                principal,
                now=_aware_now(self.clock),
            )
            workspace_id = _validate_actor_context(
                principal,
                actor_context,
                resource=self.config.resource,
                required_scope=self.required_scope,
            )
        except Exception as exc:
            denial = _safe_denial(exc)
            if not self._record_decision(
                principal=principal,
                request_id=request_id,
                tool_call_id=tool_call_id,
                tool_name=safe_tool_name,
                workspace_id=None,
                allowed=False,
                reason_code=denial.reason_code,
            ):
                return _safe_tool_error(
                    error="server_error",
                    reason_code="authorization_audit_failed",
                    message="The FormOwl authorization decision could not be recorded.",
                )
            return self._authorization_error(
                error=denial.error,
                reason_code=denial.reason_code,
                message=(
                    "Authorization is insufficient."
                    if denial.http_status == 403
                    else "Authentication required."
                ),
            )

        tool_policy = self.tool_policies.get(tool_name)
        policy_denial_reason: str | None = None
        if tool_policy is None:
            policy_denial_reason = "tool_policy_unavailable"
        elif actor_context.current_workspace_role not in tool_policy.allowed_roles:
            # Role is authoritative and is evaluated before grants, so a Grant
            # can never elevate a viewer into an owner/member-only operation.
            policy_denial_reason = "workspace_role_forbidden"
        elif tool_policy.requires_grant:
            # No current connected policy requires a Grant. Future policies
            # must add an explicit matcher instead of inheriting ambient grants.
            policy_denial_reason = "required_grant_unavailable"

        if policy_denial_reason is not None:
            if not self._record_decision(
                principal=principal,
                request_id=request_id,
                tool_call_id=tool_call_id,
                tool_name=safe_tool_name,
                workspace_id=workspace_id,
                allowed=False,
                reason_code=policy_denial_reason,
            ):
                return _safe_tool_error(
                    error="server_error",
                    reason_code="authorization_audit_failed",
                    message="The FormOwl authorization decision could not be recorded.",
                )
            if policy_denial_reason == "tool_policy_unavailable":
                return _safe_tool_error(
                    error="server_error",
                    reason_code=policy_denial_reason,
                    message="The requested FormOwl tool is unavailable.",
                )
            return self._authorization_error(
                error="insufficient_scope",
                reason_code=policy_denial_reason,
                message="Authorization is insufficient.",
            )

        try:
            prepared_arguments = _prepare_tool_arguments(
                tool_name,
                arguments,
                actor_context=actor_context,
                workspace_id=workspace_id,
            )
        except ContractValidationError:
            if not self._record_decision(
                principal=principal,
                request_id=request_id,
                tool_call_id=tool_call_id,
                tool_name=safe_tool_name,
                workspace_id=workspace_id,
                allowed=False,
                reason_code="invalid_tool_arguments",
            ):
                return _safe_tool_error(
                    error="server_error",
                    reason_code="authorization_audit_failed",
                    message="The FormOwl authorization decision could not be recorded.",
                )
            return _safe_tool_error(
                error="invalid_request",
                reason_code="invalid_tool_arguments",
                message="The FormOwl tool arguments were rejected.",
            )

        if not self._record_decision(
            principal=principal,
            request_id=request_id,
            tool_call_id=tool_call_id,
            tool_name=safe_tool_name,
            workspace_id=workspace_id,
            allowed=True,
            reason_code="tool_authorized",
        ):
            return _safe_tool_error(
                error="server_error",
                reason_code="authorization_audit_failed",
                message="The FormOwl authorization decision could not be recorded.",
            )

        try:
            if tool_name == "whoami":
                payload = self.bridge.whoami_payload(actor_context)
            else:
                handler_attribute = _SEMANTIC_HANDLER_ATTRIBUTES.get(tool_name)
                handler = (
                    None
                    if handler_attribute is None
                    else getattr(self.semantic_gateway, handler_attribute, None)
                )
                handler_call = None if handler is None else getattr(handler, "__call__", None)
                if inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(
                    handler_call
                ):
                    raise ContractValidationError(_STRICT_TOOL_RESULT_ERROR)
                payload = self.semantic_gateway.dispatch_tool(tool_name, prepared_arguments)
            if inspect.isawaitable(payload):
                if inspect.iscoroutine(payload):
                    try:
                        payload.close()
                    except Exception:
                        pass
                raise ContractValidationError(_STRICT_TOOL_RESULT_ERROR)
            validate_public_gateway_payload(payload)
            return _successful_tool_result(payload)
        except Exception:
            return _safe_tool_error(
                error="server_error",
                reason_code="tool_execution_failed",
                message="The FormOwl tool could not complete the request.",
            )

    def _record_decision(
        self,
        *,
        principal: Any | None,
        request_id: str,
        tool_call_id: str,
        tool_name: str,
        workspace_id: str | None,
        allowed: bool,
        reason_code: str,
    ) -> bool:
        if self.discovery_only:
            return True
        try:
            self.bridge.record_mcp_authorization_decision(
                principal=principal,
                request_id=request_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                workspace_id=workspace_id,
                allowed=allowed,
                reason_code=reason_code,
                now=_aware_now(self.clock),
            )
        except Exception:
            return False
        return True

    def _authorization_error(
        self,
        *,
        error: str,
        reason_code: str,
        message: str,
    ) -> mcp_types.CallToolResult:
        challenge_error = "insufficient_scope" if error == "insufficient_scope" else "invalid_token"
        challenge = build_www_authenticate_challenge(
            self.metadata_url,
            error=challenge_error,
            error_description=message,
        )
        return _safe_tool_error(
            error=error,
            reason_code=reason_code,
            message=message,
            meta={"mcp/www_authenticate": [challenge]},
        )


@dataclass(frozen=True)
class _SafeDenial:
    error: str
    reason_code: str
    http_status: int


def build_www_authenticate_challenge(
    metadata_url: str,
    *,
    error: str,
    error_description: str,
) -> str:
    """Build a canonical OAuth challenge and reject header injection."""

    parsed = urlparse(_header_value(metadata_url, "metadata_url"))
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OAuth resource metadata URL is invalid")
    safe_error = _header_value(error, "error")
    if not _SAFE_OAUTH_ERROR.fullmatch(safe_error):
        raise ValueError("OAuth challenge error is invalid")
    description = _header_value(error_description, "error_description")
    return (
        f'Bearer resource_metadata="{_quote_header_value(metadata_url)}", '
        f'error="{safe_error}", '
        f'error_description="{_quote_header_value(description)}"'
    )


def build_remote_tool_descriptors(
    *,
    required_scope: str,
    enabled_tool_names: Collection[str] | None = None,
) -> list[mcp_types.Tool]:
    """Return Apps-compatible tool descriptors with complete safety annotations."""

    if required_scope != _DEFAULT_REQUIRED_SCOPE:
        raise ContractValidationError("connected MCP scope must be formowl.use")
    enabled = (
        frozenset(_CONNECTED_TOOL_POLICIES)
        if enabled_tool_names is None
        else frozenset(enabled_tool_names)
    )
    if "whoami" not in enabled or not enabled <= frozenset(_CONNECTED_TOOL_POLICIES):
        raise ContractValidationError("connected MCP tool configuration is invalid")
    schemes = [{"type": "oauth2", "scopes": [required_scope]}]
    descriptors = [
        _tool_descriptor(
            name="whoami",
            description="Return the authenticated FormOwl user and current workspace context.",
            input_schema=_WHOAMI_INPUT_SCHEMA,
            output_schema=_WHOAMI_OUTPUT_SCHEMA,
            schemes=schemes,
        )
    ]
    for schema in PUBLIC_TOOL_SCHEMAS:
        if schema["tool_name"] not in enabled:
            continue
        json_rpc_schema = _tool_to_json_rpc_schema(schema)
        descriptors.append(
            _tool_descriptor(
                name=schema["tool_name"],
                description=json_rpc_schema["description"],
                input_schema=json_rpc_schema["inputSchema"],
                output_schema=_SEMANTIC_OUTPUT_SCHEMA,
                schemes=schemes,
            )
        )
    return descriptors


def create_connected_mcp_application(
    *,
    bridge: OAuthBridgeProtocol,
    config: Any,
    google_client: Any,
    semantic_gateway: SemanticMcpGateway,
    oauth_route_provider: OAuthRouteProvider | None = None,
    additional_routes: Sequence[BaseRoute] = (),
    manage_session_manager_lifespan: bool = True,
    clock: Clock | None = None,
    environ: Mapping[str, str] | None = None,
) -> ConnectedMcpApplication:
    """Compose OAuth routes and official Streamable HTTP MCP on one origin."""

    resolved_clock = clock or (lambda: datetime.now(timezone.utc))
    _validate_connected_dependencies(
        bridge=bridge,
        config=config,
        google_client=google_client,
        semantic_gateway=semantic_gateway,
        clock=resolved_clock,
        environ=os.environ if environ is None else environ,
    )
    if oauth_route_provider is None:
        from formowl_auth.http import oauth_routes

        oauth_route_provider = oauth_routes

    server: Server[Any, Any] = _RedactingMcpServer(
        "formowl-connected-mcp",
        version="0.1.0",
        instructions=(
            "Use governed FormOwl tools. Identity, workspace, grants, storage, "
            "parser, and worker controls are server-managed."
        ),
    )
    dispatcher = RemoteMcpDispatcher(
        bridge=bridge,
        config=config,
        semantic_gateway=semantic_gateway,
        clock=resolved_clock,
        enabled_tool_names={
            "whoami",
            *(
                tool_name
                for tool_name, attribute_name in _SEMANTIC_HANDLER_ATTRIBUTES.items()
                if getattr(semantic_gateway, attribute_name) is not None
            ),
        },
    )
    server.list_tools()(dispatcher.list_tools)
    server.call_tool(validate_input=False)(dispatcher.call_tool)
    session_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=True,
        json_response=True,
    )
    exact_mcp_app = ExactMcpPathApp(session_manager.handle_request)
    authenticated_mcp_app = BearerAuthenticationMiddleware(
        exact_mcp_app,
        bridge=bridge,
        resource=config.resource,
        required_scope=dispatcher.required_scope,
        metadata_url=dispatcher.metadata_url,
        clock=resolved_clock,
        discovery_only=dispatcher.discovery_only,
    )
    oauth_routes = list(
        oauth_route_provider(
            bridge=bridge,
            config=config,
            google_client=google_client,
            clock=resolved_clock,
        )
    )
    app = Starlette(
        routes=[
            *oauth_routes,
            *additional_routes,
            Mount("/", app=authenticated_mcp_app, name="mcp"),
        ],
        middleware=[Middleware(SafeExceptionMiddleware)],
        lifespan=(
            _SessionManagerLifespan(session_manager) if manage_session_manager_lifespan else None
        ),
    )
    app.state.formowl_session_manager_lifespan_managed = manage_session_manager_lifespan
    return ConnectedMcpApplication(
        app=app,
        server=server,
        session_manager=session_manager,
        dispatcher=dispatcher,
        bridge=bridge,
        config=config,
        manages_session_manager_lifespan=manage_session_manager_lifespan,
    )


def create_connected_mcp_asgi_app(**kwargs: Any) -> Starlette:
    """Return only the ASGI app for deployment adapters."""

    return create_connected_mcp_application(**kwargs).app


def run_connected_mcp_application(
    application: ConnectedMcpApplication,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    log_level: str = "info",
) -> None:
    """Run a pre-composed connected app with sensitive access logging disabled."""

    if not isinstance(application, ConnectedMcpApplication):
        raise TypeError("a connected MCP application bundle is required")
    if not isinstance(host, str) or not host:
        raise ValueError("connected MCP host is required")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("connected MCP port is invalid")
    import uvicorn

    uvicorn.run(
        application.app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=False,
        proxy_headers=False,
    )


def remote_main() -> int:
    """Run the installed connected production composition CLI."""

    from .runtime import main

    return main()


def _tool_descriptor(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    schemes: list[dict[str, Any]],
) -> mcp_types.Tool:
    title = _TOOL_TITLES[name]
    read_only = name in _READ_ONLY_TOOL_NAMES
    return mcp_types.Tool(
        name=name,
        title=title,
        description=description,
        inputSchema=input_schema,
        outputSchema=output_schema,
        annotations=mcp_types.ToolAnnotations(
            title=title,
            readOnlyHint=read_only,
            destructiveHint=False,
            idempotentHint=read_only,
            openWorldHint=False,
        ),
        securitySchemes=schemes,
        _meta={"securitySchemes": schemes},
    )


def _prepare_tool_arguments(
    tool_name: str,
    arguments: Mapping[str, Any],
    *,
    actor_context: Any,
    workspace_id: str,
) -> dict[str, Any]:
    if not isinstance(arguments, Mapping):
        raise ContractValidationError("tool arguments must be an object")
    if tool_name == "whoami":
        if arguments:
            raise ContractValidationError("whoami does not accept arguments")
        return {}
    _validate_semantic_tool_arguments(tool_name, arguments)
    if tool_name == "open_upload_session":
        _validate_current_workspace_upload(arguments, workspace_id=workspace_id)
    prepared = dict(arguments)
    prepared["session_id"] = actor_context.oauth_token_session_id
    prepared["workspace_id"] = workspace_id
    prepared["requester_user_id"] = actor_context.user.user_id
    if tool_name == "submit_graph_review_decision":
        prepared["reviewer_user_id"] = actor_context.user.user_id
    return prepared


def _validate_current_workspace_upload(
    arguments: Mapping[str, Any],
    *,
    workspace_id: str,
) -> None:
    if "project_id" in arguments or "customer_id" in arguments:
        raise ContractValidationError("connected upload scope is restricted to current workspace")
    owner_scope_type = arguments.get("owner_scope_type", "workspace")
    owner_scope_id = arguments.get("owner_scope_id", workspace_id)
    visibility_scope = arguments.get("visibility_scope", "workspace")
    if owner_scope_type != "workspace" or owner_scope_id != workspace_id:
        raise ContractValidationError("upload owner scope must match current workspace")
    if visibility_scope != "workspace":
        raise ContractValidationError("upload visibility must remain workspace-scoped")
    permission_scope = arguments.get("permission_scope")
    if permission_scope is None:
        return
    if not isinstance(permission_scope, Mapping):
        raise ContractValidationError("upload permission scope must be an object")
    if set(permission_scope) != {"scope_type", "scope_id", "visibility"}:
        raise ContractValidationError("upload permission scope shape is invalid")
    if dict(permission_scope) != {
        "scope_type": "workspace",
        "scope_id": workspace_id,
        "visibility": "restricted",
    }:
        raise ContractValidationError("upload permission scope must match current workspace")


def _validate_actor_context(
    principal: Any,
    actor_context: Any,
    *,
    resource: str,
    required_scope: str,
) -> str:
    workspace_id = getattr(actor_context, "current_workspace_id", None)
    role = getattr(actor_context, "current_workspace_role", None)
    user = getattr(actor_context, "user", None)
    user_id = getattr(user, "user_id", None)
    principal_user_id = getattr(principal, "user_id", None)
    principal_token_session_id = getattr(principal, "token_session_id", None)
    actor_token_session_id = getattr(actor_context, "oauth_token_session_id", None)
    session_identity = getattr(actor_context, "session_identity", None)
    if (
        user_id != principal_user_id
        or session_identity is None
        or getattr(session_identity, "session_id", None) != principal_token_session_id
        or getattr(session_identity, "session_id", None) != actor_token_session_id
        or getattr(session_identity, "selected_user_id", None) != principal_user_id
        or getattr(session_identity, "selected_user_id", None) != user_id
        or getattr(session_identity, "selection_method", None) != "google_oidc_oauth"
        or getattr(actor_context, "external_identity_id", None)
        != getattr(principal, "external_identity_id", None)
        or getattr(actor_context, "oauth_client_id", None)
        != getattr(principal, "oauth_client_id", None)
        or actor_token_session_id != principal_token_session_id
        or getattr(principal, "resource", None) != resource
        or required_scope not in tuple(getattr(principal, "scopes", ()))
        or getattr(actor_context, "auth_mode", None) != "google_oidc_oauth"
        or getattr(actor_context, "production_authentication", None) is not True
        or not isinstance(workspace_id, str)
        or not workspace_id
        or role not in {"owner", "member", "viewer"}
    ):
        raise ContractValidationError("gateway actor context is inconsistent")
    memberships = getattr(actor_context, "workspace_memberships", ())
    if not any(
        getattr(member, "user_id", None) == user_id
        and getattr(member, "workspace_id", None) == workspace_id
        and getattr(member, "role", None) == role
        for member in memberships
    ):
        raise ContractValidationError("current workspace membership is unavailable")
    return workspace_id


def _validate_connected_dependencies(
    *,
    bridge: OAuthBridgeProtocol,
    config: Any,
    google_client: Any,
    semantic_gateway: SemanticMcpGateway,
    clock: Clock,
    environ: Mapping[str, str],
) -> None:
    if bridge is None or config is None or google_client is None:
        raise ContractValidationError("connected OAuth dependencies are required")
    if not isinstance(semantic_gateway, SemanticMcpGateway):
        raise ContractValidationError("connected semantic gateway is required")
    if getattr(bridge, "config", None) != config:
        raise ContractValidationError("connected bridge configuration mismatch")
    if getattr(bridge, "google_client", None) is not google_client:
        raise ContractValidationError("connected Google client mismatch")
    _aware_now(clock)
    resource = urlparse(str(getattr(config, "resource", "")))
    if resource.path != _MCP_PATH or resource.params or resource.query or resource.fragment:
        raise ContractValidationError("connected MCP resource must be the exact /mcp URL")
    _canonical_metadata_url(config)
    _required_scope(config)
    forbidden = sorted(name for name in _FORBIDDEN_CONNECTED_ENV if environ.get(name))
    if forbidden:
        raise ContractValidationError(
            "connected MCP rejects manual session identity environment variables"
        )
    auth_mode = environ.get(_AUTH_MODE_ENV, "oauth_google")
    if auth_mode != "oauth_google":
        raise ContractValidationError("connected MCP requires Google-backed OAuth mode")


def _required_scope(config: Any) -> str:
    scopes = tuple(getattr(config, "scopes", ()))
    if scopes != (_DEFAULT_REQUIRED_SCOPE,):
        raise ContractValidationError("connected MCP requires exactly formowl.use")
    return scopes[0]


def _canonical_metadata_url(config: Any) -> str:
    value = getattr(config, "protected_resource_metadata_url", None)
    if not isinstance(value, str):
        raise ContractValidationError("OAuth protected-resource metadata URL is required")
    build_www_authenticate_challenge(
        value,
        error="invalid_token",
        error_description="Authentication required.",
    )
    return value


def _extract_bearer_token(scope: Mapping[str, Any]) -> str | None:
    values: list[str] = []
    for raw_name, raw_value in scope.get("headers", []):
        if bytes(raw_name).lower() != b"authorization":
            continue
        try:
            values.append(bytes(raw_value).decode("ascii"))
        except UnicodeDecodeError as exc:
            raise ValueError("authorization_header_invalid") from exc
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("authorization_header_duplicated")
    value = values[0]
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("authorization_header_invalid")
    parts = value.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise ValueError("authorization_header_invalid")
    return parts[1]


def _safe_denial(error: Exception) -> _SafeDenial:
    denial_error = getattr(error, "error", "invalid_token")
    reason_code = getattr(error, "reason_code", "authentication_failed")
    http_status = getattr(error, "http_status", 401)
    if not isinstance(denial_error, str) or not _SAFE_OAUTH_ERROR.fullmatch(denial_error):
        denial_error = "invalid_token"
    if not isinstance(reason_code, str) or not _SAFE_MACHINE_CODE.fullmatch(reason_code):
        reason_code = "authentication_failed"
    if type(http_status) is not int or http_status not in {400, 401, 403, 500}:
        http_status = 401
    if isinstance(error, (ValueError, ContractValidationError)) and not hasattr(
        error, "reason_code"
    ):
        reason_code = "authorization_header_invalid"
        http_status = 401
    return _SafeDenial(denial_error, reason_code, http_status)


async def _send_http_oauth_denial(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    denial: _SafeDenial,
    metadata_url: str,
) -> None:
    status_code = 403 if denial.http_status == 403 else 401
    challenge_error = "insufficient_scope" if status_code == 403 else "invalid_token"
    description = (
        "Authorization is insufficient." if status_code == 403 else "Authentication required."
    )
    challenge = build_www_authenticate_challenge(
        metadata_url,
        error=challenge_error,
        error_description=description,
    )
    response = JSONResponse(
        {"error": challenge_error},
        status_code=status_code,
        headers={**_no_store_headers(), "WWW-Authenticate": challenge},
    )
    await response(scope, receive, send)


def _successful_tool_result(payload: dict[str, Any]) -> mcp_types.CallToolResult:
    validate_public_gateway_payload(payload)
    try:
        canonical_text = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        canonical_payload = json.loads(canonical_text)
        if not isinstance(canonical_payload, dict) or canonical_payload != payload:
            raise TypeError(_STRICT_TOOL_RESULT_ERROR)
    except Exception:
        raise ContractValidationError(_STRICT_TOOL_RESULT_ERROR) from None
    return mcp_types.CallToolResult(
        content=[
            mcp_types.TextContent(
                type="text",
                text=canonical_text,
            )
        ],
        structuredContent=canonical_payload,
        isError=canonical_payload.get("status") == "error",
    )


def _safe_tool_error(
    *,
    error: str,
    reason_code: str,
    message: str,
    meta: dict[str, Any] | None = None,
) -> mcp_types.CallToolResult:
    safe_error = error if _SAFE_OAUTH_ERROR.fullmatch(error) else "server_error"
    safe_reason = reason_code if _SAFE_MACHINE_CODE.fullmatch(reason_code) else "request_rejected"
    payload = {
        "status": "error",
        "error": safe_error,
        "reason_code": safe_reason,
    }
    validate_public_gateway_payload(payload)
    _header_value(message, "message")
    return mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text=message)],
        _meta=meta,
        isError=True,
    )


def _new_safe_id(prefix: str) -> str:
    value = f"{prefix}_{secrets.token_hex(16)}"
    if not _SAFE_TOOL_NAME.fullmatch(value):
        raise RuntimeError("generated identifier is invalid")
    return value


def _aware_now(clock: Clock) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("connected MCP clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _header_value(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError(f"{field_name} is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field_name} contains control characters")
    return value


def _quote_header_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _no_store_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "Referrer-Policy": "no-referrer",
    }


__all__ = [
    "BearerAuthenticationMiddleware",
    "ConnectedMcpApplication",
    "ExactMcpPathApp",
    "RemoteMcpDispatcher",
    "SafeExceptionMiddleware",
    "build_remote_tool_descriptors",
    "build_www_authenticate_challenge",
    "create_connected_mcp_application",
    "create_connected_mcp_asgi_app",
    "remote_main",
    "run_connected_mcp_application",
]
