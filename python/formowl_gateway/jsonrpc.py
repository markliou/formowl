from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from formowl_contract import ContractValidationError, safe_public_string, sha256_json

from .protocol import JsonRpcTranscriptEntry, McpJsonRpcEngine, McpSession

from .semantic import (
    PUBLIC_TOOL_SCHEMAS,
    SemanticMcpGateway,
    validate_public_gateway_payload,
)

_SEMANTIC_TOOL_INPUT_KEYS = {
    schema["tool_name"]: set(schema["input_keys"]) for schema in PUBLIC_TOOL_SCHEMAS
}
_SEMANTIC_TOOL_EXTRA_ARGUMENT_KEYS = {
    "open_upload_session": {
        "owner_scope_type",
        "owner_scope_id",
        "project_id",
        "customer_id",
        "visibility_scope",
        "ingestion_profile",
    },
    "query_mail_evidence": {"limit"},
}
_SEMANTIC_TOOL_CALLER_IDENTITY_KEYS = {
    "actor_user_id",
    "requester_user_id",
    "reviewer_user_id",
    "session_id",
    "workspace_id",
}
_SEMANTIC_TOOL_OBJECT_ARGUMENT_KEYS = {
    "candidate_filter",
    "observation_filter",
    "permission_scope",
    "requested_scope",
}
_SEMANTIC_TOOL_INTEGER_ARGUMENT_KEYS = {"limit"}
_SEMANTIC_TOOL_REQUIRED_ARGUMENT_KEYS = {
    "open_upload_session": {"intent", "intended_asset_type"},
    "create_ingestion_job": {"asset_locator", "extractor_profile"},
    "list_observations": {"asset_locator"},
    "preview_graph_candidates": {"candidate_filter"},
    "query_effective_graph": {"query_text"},
    "query_effective_graph_view": {"query_text"},
    "query_mail_evidence": {"query_text"},
    "answer_mail_case_progress": {"case_id"},
    "request_graph_access": {
        "owner_user_id",
        "requested_scope",
        "requested_access_level",
        "reason",
    },
    "submit_graph_review_decision": {"proposal_id", "decision"},
    "generate_wiki_draft_from_graph_view": {"projection_spec_id"},
}
_SEMANTIC_TOOL_SELECTOR_ARGUMENT_KEYS = {
    "query_mail_evidence": ("mail_import_session_id", "mail_evidence_bundle_id"),
    "answer_mail_case_progress": ("mail_import_session_id", "mail_evidence_bundle_id"),
}
_SEMANTIC_TOOL_FORBIDDEN_ARGUMENT_KEYS = {
    "backend",
    "backend_id",
    "backend_name",
    "grants",
    "parser",
    "parser_id",
    "parser_name",
    "raw",
    "storage",
    "storage_backend",
    "storage_backend_id",
    "storage_backend_name",
    "worker",
    "worker_name",
    "worker_queue",
}


SemanticGatewaySession = McpSession


def _default_session() -> SemanticGatewaySession:
    return SemanticGatewaySession(
        session_id="unauthenticated_session",
        actor_user_id="anonymous",
        workspace_id="unbound_workspace",
        authenticated=False,
    )


@dataclass
class _McpServerProtocolStrategy:
    server: Any
    configured_server_name: str | None = None
    server_version: str = "0.1.0"

    @property
    def server_name(self) -> str:
        value = self.configured_server_name or getattr(self.server, "server_name", "formowl-mcp")
        safe_value = _safe_method_name(str(value))
        return f"formowl-{safe_value}-jsonrpc"

    def list_tools(self) -> list[dict[str, Any]]:
        return [_mcp_server_tool_to_json_rpc_schema(tool) for tool in self.server.list_tools()]

    def validate_tool_call(self, tool_name: str, arguments: Mapping[str, Any]) -> None:
        _reject_mcp_server_caller_identity_keys(arguments)
        validate_public_gateway_payload({"tool_name": tool_name, "arguments": arguments})

    def dispatch_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        session: McpSession,
    ) -> dict[str, Any]:
        return self.server.call_tool(
            tool_name,
            {
                **dict(arguments),
                "session_id": session.session_id,
                "requester_user_id": session.actor_user_id,
                "workspace_id": session.workspace_id,
            },
        )

    def safe_tool_error(self, tool_name: str, error_code: str) -> dict[str, Any]:
        return _safe_mcp_tool_error_envelope(
            server_name=self.server_name,
            tool_name=tool_name,
            error_code=error_code,
        )


@dataclass
class McpServerJsonRpcGateway:
    server: Any
    server_name: str | None = None
    session: SemanticGatewaySession = field(default_factory=_default_session)
    transcript: list[JsonRpcTranscriptEntry] = field(default_factory=list)
    _engine: McpJsonRpcEngine = field(init=False, repr=False)

    def __post_init__(self) -> None:
        strategy = _McpServerProtocolStrategy(self.server, self.server_name)
        self._engine = McpJsonRpcEngine(strategy, self.session, self.transcript)

    def handle_json_rpc(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._engine.handle_json_rpc(request)

    def leak_transcript(self) -> list[dict[str, Any]]:
        return self._engine.leak_transcript()


@dataclass
class _SemanticProtocolStrategy:
    semantic_gateway: SemanticMcpGateway = field(default_factory=SemanticMcpGateway)
    server_name: str = "formowl-semantic-gateway"
    server_version: str = "0.1.0"

    def list_tools(self) -> list[dict[str, Any]]:
        return [_tool_to_json_rpc_schema(schema) for schema in PUBLIC_TOOL_SCHEMAS]

    def validate_tool_call(self, tool_name: str, arguments: Mapping[str, Any]) -> None:
        _validate_semantic_tool_arguments(tool_name, arguments)

    def dispatch_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        session: McpSession,
    ) -> dict[str, Any]:
        merged_arguments = {
            **dict(arguments),
            "session_id": session.session_id,
            "workspace_id": session.workspace_id,
            "requester_user_id": session.actor_user_id,
        }
        if tool_name == "submit_graph_review_decision":
            merged_arguments["reviewer_user_id"] = session.actor_user_id
        return self.semantic_gateway.dispatch_tool(tool_name, merged_arguments)

    def safe_tool_error(self, tool_name: str, error_code: str) -> dict[str, Any]:
        return self.semantic_gateway.safe_error_envelope(
            tool_name=tool_name,
            error_code=error_code,
        )


@dataclass
class SemanticMcpJsonRpcGateway:
    semantic_gateway: SemanticMcpGateway = field(default_factory=SemanticMcpGateway)
    session: SemanticGatewaySession = field(default_factory=_default_session)
    transcript: list[JsonRpcTranscriptEntry] = field(default_factory=list)
    _engine: McpJsonRpcEngine = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._engine = McpJsonRpcEngine(
            _SemanticProtocolStrategy(self.semantic_gateway),
            self.session,
            self.transcript,
        )

    def handle_json_rpc(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._engine.handle_json_rpc(request)

    def leak_transcript(self) -> list[dict[str, Any]]:
        return self._engine.leak_transcript()


def build_raw_path_raw_sql_worker_internal_leak_transcript() -> dict[str, Any]:
    gateway = SemanticMcpJsonRpcGateway()
    attack_requests = [
        {
            "jsonrpc": "2.0",
            "id": "attack_raw_path",
            "method": "tools/call",
            "params": {
                "name": "direct_filesystem_read_tool",
                "arguments": {"path": "/srv/formowl/private/customer.xlsx"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": "attack_raw_sql",
            "method": "tools/call",
            "params": {
                "name": "direct_database_query_tool",
                "arguments": {"sql": "select * from private_table"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": "attack_worker",
            "method": "tools/call",
            "params": {
                "name": "query_effective_graph",
                "arguments": {"query_text": "worker_scratch /tmp/raw"},
            },
        },
    ]
    responses = [gateway.handle_json_rpc(request) for request in attack_requests]
    transcript = gateway.leak_transcript()
    payload = {
        "transcript": transcript,
        "response_hashes": [sha256_json(response) for response in responses],
        "raw_request_retained": False,
        "safe_response_count": len(responses),
    }
    validate_public_gateway_payload(payload)
    return payload


def containerized_semantic_mcp_gateway_smoke() -> dict[str, Any]:
    gateway = SemanticMcpJsonRpcGateway(
        semantic_gateway=SemanticMcpGateway(
            retrieval_handler=lambda input_data: {
                "answer": "bounded semantic smoke answer",
                "citations": [],
                "visible_graph_snippets": [],
                "redaction_counts": {"hidden_records": 0},
            }
        ),
        session=SemanticGatewaySession(
            session_id="semantic_smoke_session",
            actor_user_id="semantic_smoke_actor",
            workspace_id="semantic_smoke_workspace",
        ),
    )
    requests = [
        {"jsonrpc": "2.0", "id": "init", "method": "initialize"},
        {"jsonrpc": "2.0", "id": "tools", "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": "query",
            "method": "tools/call",
            "params": {
                "name": "query_effective_graph_view",
                "arguments": {"query_text": "delivery risk"},
            },
        },
    ]
    responses = [gateway.handle_json_rpc(request) for request in requests]
    leak_packet = build_raw_path_raw_sql_worker_internal_leak_transcript()
    tool_names = {
        tool["name"]
        for response in responses
        for tool in response.get("result", {}).get("tools", [])
    }
    expected_tool_names = {schema["tool_name"] for schema in PUBLIC_TOOL_SCHEMAS}
    smoke = {
        "transport_initialized": responses[0].get("result", {}).get("protocolVersion")
        == "2024-11-05",
        "tools_listed": tool_names == expected_tool_names,
        "tool_call_succeeded": responses[2].get("result", {}).get("isError") is False,
        "session_bound": all(
            response.get("result", {}).get("session", {}).get("actor_user_id")
            == "semantic_smoke_actor"
            for response in responses
        ),
        "hash_only_transcript": all(
            set(entry) == {"method", "request_hash", "response_hash", "status"}
            for entry in gateway.leak_transcript()
        ),
        "raw_leak_probe_passed": leak_packet["raw_request_retained"] is False
        and leak_packet["safe_response_count"] == 3,
        "container_verification_required": True,
    }
    result = {
        "smoke_passed": all(smoke.values()),
        "metrics": smoke,
        "transcript": gateway.leak_transcript(),
        "leak_probe_response_hashes": leak_packet["response_hashes"],
        "claim_boundary": {
            "supports_containerized_semantic_mcp_gateway_smoke_claim": all(smoke.values()),
            "supports_production_adapter_ready_claim": False,
            "supports_direct_database_query_tool_claim": False,
            "supports_direct_filesystem_read_tool_claim": False,
        },
    }
    validate_public_gateway_payload(result)
    return result


def standards_compliant_mcp_gateway_transport() -> tuple[str, ...]:
    return ("jsonrpc_2_0", "initialize", "tools/list", "tools/call")


def session_auth_and_audit_store_integration() -> str:
    return "session_context_bound_to_json_rpc_transcript_hashes"


def end_to_end_raw_path_raw_sql_worker_internal_leak_transcript() -> dict[str, Any]:
    return build_raw_path_raw_sql_worker_internal_leak_transcript()


def create_mail_upload_semantic_jsonrpc_gateway(
    *,
    data_dir: str | Path | None = None,
    expires_at: str | None = None,
    session: SemanticGatewaySession | None = None,
) -> SemanticMcpJsonRpcGateway:
    """Build the Phase 1 semantic gateway runtime with mail upload sessions enabled."""

    # Local imports avoid a module cycle: formowl_mail.upload_session imports the
    # public payload validator from formowl_gateway.
    from formowl_auth import FileAuditLogStore
    from formowl_ingestion.storage import UploadSessionStore
    from formowl_mail import build_mail_upload_session_handler

    root = Path(data_dir or os.environ.get("FORMOWL_DATA_DIR", ".formowl/data"))
    resolved_session = session or _session_from_env()
    resolved_expires_at = (
        expires_at
        or os.environ.get("FORMOWL_MAIL_UPLOAD_EXPIRES_AT")
        or _default_mail_upload_expires_at()
    )
    gateway = SemanticMcpGateway(
        upload_session_handler=build_mail_upload_session_handler(
            upload_session_store=UploadSessionStore(root),
            audit_store=FileAuditLogStore(root),
            expires_at=resolved_expires_at,
        )
    )
    return SemanticMcpJsonRpcGateway(semantic_gateway=gateway, session=resolved_session)


def _tool_to_json_rpc_schema(schema: dict[str, Any]) -> dict[str, Any]:
    tool_name = schema["tool_name"]
    exposed_keys = (
        set(schema["input_keys"]) | _SEMANTIC_TOOL_EXTRA_ARGUMENT_KEYS.get(tool_name, set())
    ) - _SEMANTIC_TOOL_CALLER_IDENTITY_KEYS
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {key: _semantic_argument_json_schema(key) for key in sorted(exposed_keys)},
        "required": sorted(
            _SEMANTIC_TOOL_REQUIRED_ARGUMENT_KEYS.get(tool_name, set()) & exposed_keys
        ),
        "additionalProperties": False,
    }
    selector_keys = _SEMANTIC_TOOL_SELECTOR_ARGUMENT_KEYS.get(tool_name)
    if selector_keys is not None:
        input_schema["anyOf"] = [{"required": [key]} for key in selector_keys]
    compatibility = schema.get("compatibility", {})
    description = f"FormOwl semantic gateway tool: {tool_name}"
    if compatibility.get("status") == "deprecated_alias":
        description += (
            "; deprecated compatibility alias, use " f"{compatibility['canonical_tool_name']}"
        )
    elif compatibility.get("status") == "canonical":
        description += "; canonical API"
    return {
        "name": tool_name,
        "description": description,
        "inputSchema": input_schema,
    }


def _semantic_argument_json_schema(key: str) -> dict[str, Any]:
    if key in _SEMANTIC_TOOL_OBJECT_ARGUMENT_KEYS:
        return {"type": "object"}
    if key in _SEMANTIC_TOOL_INTEGER_ARGUMENT_KEYS:
        return {"type": "integer", "minimum": 1, "maximum": 100}
    return {"type": "string"}


def _mcp_server_tool_to_json_rpc_schema(tool: dict[str, Any]) -> dict[str, Any]:
    name = _safe_method_name(str(tool.get("name") or "unknown_tool"))
    description = str(tool.get("description") or f"FormOwl MCP tool: {name}")
    try:
        validate_public_gateway_payload(description)
    except ContractValidationError:
        description = "FormOwl MCP tool."
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    }


def _validate_semantic_tool_arguments(tool_name: str, arguments: Mapping[str, Any]) -> None:
    _reject_semantic_caller_identity_keys(arguments)
    _reject_semantic_control_argument_keys(arguments)
    allowed_keys = _SEMANTIC_TOOL_INPUT_KEYS.get(tool_name)
    if allowed_keys is None:
        return
    allowed = allowed_keys | _SEMANTIC_TOOL_EXTRA_ARGUMENT_KEYS.get(tool_name, set())
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise ContractValidationError(
            "semantic JSON-RPC arguments contain unsupported keys: " + sha256_json(extra)
        )
    required = _SEMANTIC_TOOL_REQUIRED_ARGUMENT_KEYS.get(tool_name, set())
    missing = sorted(key for key in required if key not in arguments)
    if missing:
        raise ContractValidationError(
            "semantic JSON-RPC arguments omit required keys: " + sha256_json(missing)
        )
    selector_keys = _SEMANTIC_TOOL_SELECTOR_ARGUMENT_KEYS.get(tool_name)
    if selector_keys is not None and not any(arguments.get(key) for key in selector_keys):
        raise ContractValidationError("semantic JSON-RPC arguments omit a required selector")
    for key, value in arguments.items():
        if key in _SEMANTIC_TOOL_OBJECT_ARGUMENT_KEYS:
            if not isinstance(value, Mapping):
                raise ContractValidationError("semantic JSON-RPC object argument is invalid")
        elif key in _SEMANTIC_TOOL_INTEGER_ARGUMENT_KEYS:
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
                raise ContractValidationError("semantic JSON-RPC integer argument is invalid")
        elif not isinstance(value, str) or not value.strip():
            raise ContractValidationError("semantic JSON-RPC string argument is invalid")


def _reject_semantic_caller_identity_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalized_semantic_argument_key(str(key))
            if normalized in _SEMANTIC_TOOL_CALLER_IDENTITY_KEYS:
                raise ContractValidationError(
                    "semantic JSON-RPC arguments contain caller-controlled identity key: "
                    + sha256_json(normalized)
                )
            _reject_semantic_caller_identity_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_semantic_caller_identity_keys(item)


def _reject_mcp_server_caller_identity_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalized_semantic_argument_key(str(key))
            if normalized in _SEMANTIC_TOOL_CALLER_IDENTITY_KEYS:
                raise ContractValidationError(
                    "MCP server arguments contain caller-controlled identity key: "
                    + sha256_json(normalized)
                )
            _reject_mcp_server_caller_identity_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_mcp_server_caller_identity_keys(item)


def _reject_semantic_control_argument_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalized_semantic_argument_key(str(key))
            if normalized in _SEMANTIC_TOOL_FORBIDDEN_ARGUMENT_KEYS:
                raise ContractValidationError(
                    "semantic JSON-RPC arguments contain unsupported control key: "
                    + sha256_json(normalized)
                )
            _reject_semantic_control_argument_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_semantic_control_argument_keys(item)


def _normalized_semantic_argument_key(value: str) -> str:
    normalized = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0:
            normalized.append("_")
        normalized.append(char.lower() if char.isalnum() else "_")
    return "_".join(part for part in "".join(normalized).split("_") if part)


def _safe_mcp_tool_error_envelope(
    *,
    server_name: str,
    tool_name: str,
    error_code: str,
) -> dict[str, Any]:
    envelope = {
        "result_type": "mcp_gateway_error",
        "status": "error",
        "data": {
            "server_name": _safe_method_name(server_name),
            "tool_name": _safe_method_name(tool_name),
            "error_code": _safe_method_name(error_code),
            "message": "The MCP JSON-RPC gateway rejected this request.",
        },
        "warnings": ["safe_json_rpc_error_envelope"],
    }
    validate_public_gateway_payload(envelope)
    return envelope


def _json_rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    validate_public_gateway_payload(response)
    return response


def _json_rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    response = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": _safe_method_name(message)},
    }
    validate_public_gateway_payload(response)
    return response


def _safe_method_name(value: str) -> str:
    try:
        validate_public_gateway_payload(value)
    except ContractValidationError:
        return "unsafe_input_redacted"
    return value if value else "unknown"


def _session_from_env() -> SemanticGatewaySession:
    session_id = _public_env_value("FORMOWL_MCP_SESSION_ID")
    actor_user_id = _public_env_value("FORMOWL_MCP_ACTOR_USER_ID")
    workspace_id = _public_env_value("FORMOWL_MCP_WORKSPACE_ID")
    if not all((session_id, actor_user_id, workspace_id)):
        return _default_session()
    return SemanticGatewaySession(
        session_id=session_id,
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        authenticated=True,
    )


def _public_env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        safe_public_string(value, name)
        validate_public_gateway_payload(value)
    except ContractValidationError:
        return None
    return value


def _default_mail_upload_expires_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()


def main() -> None:
    gateway: SemanticMcpJsonRpcGateway | None = None
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = _safe_json_rpc_error(None, -32700, "parse_error")
        else:
            if not isinstance(request, Mapping):
                response = _safe_json_rpc_error(None, -32600, "invalid_request")
            else:
                if gateway is None:
                    try:
                        gateway = create_mail_upload_semantic_jsonrpc_gateway()
                    except Exception:
                        response = _safe_json_rpc_error(
                            request.get("id"),
                            -32000,
                            "internal_error",
                        )
                        print(json.dumps(response, ensure_ascii=False), flush=True)
                        continue
                try:
                    response = gateway.handle_json_rpc(request)
                except Exception:
                    response = _safe_json_rpc_error(
                        request.get("id"),
                        -32000,
                        "internal_error",
                    )
        print(json.dumps(response, ensure_ascii=False), flush=True)


def _safe_json_rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    try:
        return _json_rpc_error(request_id, code, message)
    except ContractValidationError:
        return _json_rpc_error(None, code, message)


if __name__ == "__main__":
    main()
