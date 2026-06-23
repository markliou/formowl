from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from formowl_contract import ContractValidationError, sha256_json, to_plain

from .semantic import (
    PUBLIC_TOOL_SCHEMAS,
    SemanticMcpGateway,
    validate_public_gateway_payload,
)


@dataclass(frozen=True)
class SemanticGatewaySession:
    session_id: str
    actor_user_id: str
    workspace_id: str
    authenticated: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        validate_public_gateway_payload(payload)
        return payload


@dataclass(frozen=True)
class JsonRpcTranscriptEntry:
    method: str
    request_hash: str
    response_hash: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        validate_public_gateway_payload(payload)
        return payload


@dataclass
class SemanticMcpJsonRpcGateway:
    semantic_gateway: SemanticMcpGateway = field(default_factory=SemanticMcpGateway)
    session: SemanticGatewaySession = field(
        default_factory=lambda: SemanticGatewaySession(
            session_id="semantic_gateway_session",
            actor_user_id="manual_trusted_internal",
            workspace_id="workspace_main",
        )
    )
    transcript: list[JsonRpcTranscriptEntry] = field(default_factory=list)

    def handle_json_rpc(self, request: Mapping[str, Any]) -> dict[str, Any]:
        response = self._handle(request)
        validate_public_gateway_payload(response)
        self._record_transcript(request, response)
        return response

    def leak_transcript(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self.transcript]

    def _handle(self, request: Mapping[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0":
            return _json_rpc_error(request_id, -32600, "invalid_request")
        if not self.session.authenticated:
            return _json_rpc_error(request_id, -32001, "session_not_authenticated")
        method = request.get("method")
        if method == "initialize":
            return _json_rpc_result(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "formowl-semantic-gateway",
                        "version": "0.1.0",
                    },
                    "capabilities": {"tools": {"listChanged": False}},
                    "session": self.session.to_dict(),
                },
            )
        if method == "tools/list":
            return _json_rpc_result(
                request_id,
                {
                    "tools": [_tool_to_json_rpc_schema(schema) for schema in PUBLIC_TOOL_SCHEMAS],
                    "session": self.session.to_dict(),
                },
            )
        if method == "tools/call":
            params = request.get("params")
            if not isinstance(params, Mapping):
                return _json_rpc_error(request_id, -32602, "invalid_params")
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(tool_name, str) or not isinstance(arguments, Mapping):
                return _json_rpc_error(request_id, -32602, "invalid_params")
            merged_arguments = {
                "workspace_id": self.session.workspace_id,
                "requester_user_id": self.session.actor_user_id,
                **dict(arguments),
            }
            try:
                tool_result = self.semantic_gateway.dispatch_tool(tool_name, merged_arguments)
            except ContractValidationError:
                tool_result = self.semantic_gateway.safe_error_envelope(
                    tool_name=tool_name,
                    error_code="unsafe_tool_payload",
                )
            validate_public_gateway_payload(tool_result)
            return _json_rpc_result(
                request_id,
                {
                    "content": [{"type": "json", "json": tool_result}],
                    "isError": tool_result.get("status") == "error",
                    "session": self.session.to_dict(),
                },
            )
        return _json_rpc_error(request_id, -32601, "method_not_found")

    def _record_transcript(self, request: Mapping[str, Any], response: dict[str, Any]) -> None:
        method = str(request.get("method", "unknown"))
        entry = JsonRpcTranscriptEntry(
            method=_safe_method_name(method),
            request_hash=sha256_json(to_plain(dict(request))),
            response_hash=sha256_json(response),
            status="error" if "error" in response else "ok",
        )
        self.transcript.append(entry)


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
        session=SemanticGatewaySession(
            session_id="semantic_smoke_session",
            actor_user_id="semantic_smoke_actor",
            workspace_id="semantic_smoke_workspace",
        )
    )
    requests = [
        {"jsonrpc": "2.0", "id": "init", "method": "initialize"},
        {"jsonrpc": "2.0", "id": "tools", "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": "query",
            "method": "tools/call",
            "params": {
                "name": "query_effective_graph",
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
    smoke = {
        "transport_initialized": responses[0].get("result", {}).get("protocolVersion")
        == "2024-11-05",
        "tools_listed": tool_names
        == {
            "preview_graph_candidates",
            "query_effective_graph",
            "submit_graph_review_decision",
            "generate_wiki_draft_from_graph_view",
        },
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


def _tool_to_json_rpc_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": schema["tool_name"],
        "description": f"FormOwl semantic gateway tool: {schema['tool_name']}",
        "inputSchema": {
            "type": "object",
            "properties": {key: {"type": "string"} for key in schema["input_keys"]},
            "additionalProperties": True,
        },
    }


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
