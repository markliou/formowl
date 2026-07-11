from __future__ import annotations

import json
import sys
from typing import Any, Callable, Mapping, TextIO


def run_jsonline_compat(
    server_factory: Callable[[], Any],
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> None:
    server = server_factory()
    source = input_stream or sys.stdin
    target = output_stream or sys.stdout
    for line in source:
        if not line.strip():
            continue
        response = _handle_jsonline_request(server, line)
        print(json.dumps(response, ensure_ascii=False), file=target, flush=True)


def _handle_jsonline_request(server: Any, line: str) -> dict[str, Any]:
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        return _compat_error("parse_error")
    if not isinstance(request, Mapping):
        return _compat_error("invalid_request")
    if request.get("method") == "list_tools":
        return {"tools": server.list_tools()}
    tool_name = request.get("tool")
    arguments = request.get("arguments", {})
    if not isinstance(tool_name, str) or not isinstance(arguments, Mapping):
        return _compat_error("invalid_request")
    try:
        return server.call_tool(tool_name, dict(arguments))
    except Exception:
        return _compat_error("tool_execution_failed")


def _compat_error(error_code: str) -> dict[str, Any]:
    return {
        "result_type": "jsonline_compat_error",
        "status": "error",
        "data": {
            "error_code": error_code,
            "message": "The MCP JSON-line compatibility runner rejected this request.",
        },
        "warnings": ["jsonline_compatibility_transport"],
    }
