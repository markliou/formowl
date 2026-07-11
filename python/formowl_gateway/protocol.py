from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from formowl_contract import ContractValidationError, sha256_json, to_plain

from .semantic import validate_public_gateway_payload


@dataclass(frozen=True)
class McpSession:
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


class McpProtocolStrategy(Protocol):
    server_name: str
    server_version: str

    def list_tools(self) -> list[dict[str, Any]]: ...

    def validate_tool_call(self, tool_name: str, arguments: Mapping[str, Any]) -> None: ...

    def dispatch_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        session: McpSession,
    ) -> dict[str, Any]: ...

    def safe_tool_error(self, tool_name: str, error_code: str) -> dict[str, Any]: ...


@dataclass
class McpJsonRpcEngine:
    strategy: McpProtocolStrategy
    session: McpSession
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
            return json_rpc_error(request_id, -32600, "invalid_request")
        if not self.session.authenticated:
            return json_rpc_error(request_id, -32001, "session_not_authenticated")
        method = request.get("method")
        if method == "initialize":
            return json_rpc_result(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": safe_public_name(self.strategy.server_name),
                        "version": safe_public_name(self.strategy.server_version),
                    },
                    "capabilities": {"tools": {"listChanged": False}},
                    "session": self.session.to_dict(),
                },
            )
        if method == "tools/list":
            return json_rpc_result(
                request_id,
                {"tools": self.strategy.list_tools(), "session": self.session.to_dict()},
            )
        if method == "tools/call":
            return self._handle_tool_call(request_id, request.get("params"))
        return json_rpc_error(request_id, -32601, "method_not_found")

    def _handle_tool_call(self, request_id: Any, params: Any) -> dict[str, Any]:
        if not isinstance(params, Mapping):
            return json_rpc_error(request_id, -32602, "invalid_params")
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(tool_name, str) or not isinstance(arguments, Mapping):
            return json_rpc_error(request_id, -32602, "invalid_params")
        try:
            self.strategy.validate_tool_call(tool_name, arguments)
            tool_result = self.strategy.dispatch_tool(tool_name, arguments, self.session)
            validate_public_gateway_payload(tool_result)
        except ContractValidationError:
            tool_result = self.strategy.safe_tool_error(tool_name, "unsafe_tool_payload")
        except Exception:
            tool_result = self.strategy.safe_tool_error(tool_name, "tool_execution_failed")
        return json_rpc_result(
            request_id,
            {
                "content": [{"type": "json", "json": tool_result}],
                "isError": tool_result.get("status") == "error",
                "session": self.session.to_dict(),
            },
        )

    def _record_transcript(
        self,
        request: Mapping[str, Any],
        response: dict[str, Any],
    ) -> None:
        status = "error" if "error" in response else "ok"
        result = response.get("result")
        if isinstance(result, Mapping):
            if result.get("isError") is True:
                status = "error"
            content = result.get("content")
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, Mapping):
                    payload = first.get("json")
                    if isinstance(payload, Mapping):
                        tool_status = payload.get("status")
                        if isinstance(tool_status, str) and tool_status not in {
                            "ok",
                            "pending_review",
                        }:
                            status = safe_public_name(tool_status)
        self.transcript.append(
            JsonRpcTranscriptEntry(
                method=safe_public_name(str(request.get("method", "unknown"))),
                request_hash=sha256_json(to_plain(dict(request))),
                response_hash=sha256_json(response),
                status=status,
            )
        )


def json_rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    validate_public_gateway_payload(response)
    return response


def json_rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    response = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": safe_public_name(message)},
    }
    validate_public_gateway_payload(response)
    return response


def safe_public_name(value: str) -> str:
    try:
        validate_public_gateway_payload(value)
    except ContractValidationError:
        return "unsafe_input_redacted"
    return value if value else "unknown"
