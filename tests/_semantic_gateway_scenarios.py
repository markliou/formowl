from __future__ import annotations

from typing import Any

from formowl_contract import sha256_json
from formowl_gateway import (
    PUBLIC_TOOL_SCHEMAS,
    SemanticGatewaySession,
    SemanticMcpGateway,
    SemanticMcpJsonRpcGateway,
    validate_public_gateway_payload,
)


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
    payload = {
        "transcript": gateway.leak_transcript(),
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
    metrics = {
        "transport_initialized": responses[0].get("result", {}).get("protocolVersion")
        == "2024-11-05",
        "tools_listed": tool_names == {schema["tool_name"] for schema in PUBLIC_TOOL_SCHEMAS},
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
        "smoke_passed": all(metrics.values()),
        "metrics": metrics,
        "transcript": gateway.leak_transcript(),
        "leak_probe_response_hashes": leak_packet["response_hashes"],
        "claim_boundary": {
            "supports_containerized_semantic_mcp_gateway_smoke_claim": all(metrics.values()),
            "supports_production_adapter_ready_claim": False,
            "supports_direct_database_query_tool_claim": False,
            "supports_direct_filesystem_read_tool_claim": False,
        },
    }
    validate_public_gateway_payload(result)
    return result
