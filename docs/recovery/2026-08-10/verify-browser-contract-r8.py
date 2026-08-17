#!/usr/bin/env python3
"""Verify the R8 UAT contract through a real Chromium DevTools session."""

from __future__ import annotations

import argparse
import base64
from contextlib import AbstractContextManager
import hashlib
import json
from pathlib import Path
import os
import re
import secrets
import select
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import time
from typing import Any, Mapping, Sequence
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_QUERY = "把COO是日本的料號取出"
DEFAULT_TIMEOUT_SECONDS = 360.0
_EXPECTED_TOOL_NAME = "search_formowl_evidence"
_COMMITMENT_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_THINKING_TEXTS = {"正在思考", "正在思考…", "正在思考..."}
_ERROR_TEXTS = {
    "回覆暫時失敗，請稍後再試。",
    "回覆暫時失敗，請稍後再試",
}
_ATTEMPTED_COUNT_ALIASES = ("mcp_attempted_call_count",)
_SUCCESSFUL_COUNT_ALIASES = ("mcp_successful_call_count",)
_RESPONSE_COMMITMENT_ALIASES = ("mcp_response_commitment",)
_TOOL_RESULT_COMMITMENT_ALIASES = ("tool_result_reinject_commitment",)
_FINAL_COMMITMENT_ALIASES = ("final_response_commitment",)
_FORBIDDEN_DOCUMENT_RESPONSE_KEYS = frozenset(
    {
        "complete_projection",
        "expected_answer",
        "expected_count",
        "final_answer",
        "fingerprint",
        "oracle",
    }
)
_REQUIRED_DOCUMENT_CLAIM_BOUNDARY = {
    "document_first": True,
    "existing_export_only": True,
    "read_only": True,
    "pst_or_extractor_invoked": False,
    "kg_or_ontology_invoked": False,
    "oracle_or_expected_answer_used": False,
    "canonical_graph_write_performed": False,
    "production_ready": False,
}


class VerificationFailure(RuntimeError):
    """A safe, non-payload-bearing verification failure."""


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--page-path", default="/")
    parser.add_argument("--summary-path", default="/api/session-summary")
    parser.add_argument("--query-path", default="/api/chat")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    browser = parser.add_mutually_exclusive_group()
    browser.add_argument("--browser-executable", type=Path)
    browser.add_argument(
        "--cdp-url",
        help="Chromium remote-debugging HTTP endpoint or WebSocket URL",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    return parser


def _safe_url(base_url: str, path: str) -> str:
    parsed_base = urlparse(base_url)
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
        raise VerificationFailure("base URL is invalid")
    if not isinstance(path, str) or not path.startswith("/"):
        raise VerificationFailure("endpoint path is invalid")
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _request_json(url: str, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            if response.status != 200:
                raise VerificationFailure("CDP endpoint did not return success")
            raw = response.read()
    except (HTTPError, URLError, TimeoutError) as error:
        raise VerificationFailure("CDP endpoint is unavailable") from error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationFailure("CDP endpoint returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise VerificationFailure("CDP endpoint returned an invalid response")
    return payload


def _walk_values(payload: Any, aliases: Sequence[str]) -> list[Any]:
    values: list[Any] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if key in aliases:
                values.append(value)
            values.extend(_walk_values(value, aliases))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(_walk_values(value, aliases))
    return values


def _counter(payload: Mapping[str, Any], aliases: Sequence[str], label: str) -> int:
    if len(aliases) != 1:
        raise VerificationFailure(f"{label} field configuration is invalid")
    field_name = aliases[0]
    if field_name not in payload:
        raise VerificationFailure(f"{label} count is missing")
    value = payload[field_name]
    if type(value) is not int or value < 0:
        raise VerificationFailure(f"{label} count is invalid")
    return value


def _response_orchestration(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    orchestration = payload.get("orchestration")
    if not isinstance(orchestration, Mapping):
        raise VerificationFailure("chat response orchestration is missing")
    return orchestration


def _summary_commitment(
    payload: Mapping[str, Any],
    aliases: Sequence[str],
    label: str,
) -> str:
    if len(aliases) != 1:
        raise VerificationFailure(f"{label} field configuration is invalid")
    field_name = aliases[0]
    if field_name not in payload:
        raise VerificationFailure(f"{label} commitment is missing")
    value = payload[field_name]
    if not isinstance(value, str) or _COMMITMENT_RE.fullmatch(value) is None:
        raise VerificationFailure(f"{label} commitment is invalid")
    return value


def _validate_count_deltas(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, int]:
    attempted_before = _counter(before, _ATTEMPTED_COUNT_ALIASES, "attempted MCP")
    attempted_after = _counter(after, _ATTEMPTED_COUNT_ALIASES, "attempted MCP")
    successful_before = _counter(before, _SUCCESSFUL_COUNT_ALIASES, "successful MCP")
    successful_after = _counter(after, _SUCCESSFUL_COUNT_ALIASES, "successful MCP")
    if attempted_after - attempted_before != 1:
        raise VerificationFailure("browser session did not record exactly one attempted MCP call")
    if successful_after - successful_before != 1:
        raise VerificationFailure("browser session did not record exactly one successful MCP call")
    return {
        "attempted_before": attempted_before,
        "attempted_after": attempted_after,
        "attempted_delta": 1,
        "successful_before": successful_before,
        "successful_after": successful_after,
        "successful_delta": 1,
    }


def _validate_commitments(
    response: Mapping[str, Any],
    after_summary: Mapping[str, Any],
) -> dict[str, str]:
    orchestration = _response_orchestration(response)
    response_commitment = _summary_commitment(
        orchestration,
        _RESPONSE_COMMITMENT_ALIASES,
        "MCP response",
    )
    tool_result_commitment = _summary_commitment(
        orchestration,
        _TOOL_RESULT_COMMITMENT_ALIASES,
        "reinjected tool result",
    )
    final_commitment = _summary_commitment(
        orchestration,
        _FINAL_COMMITMENT_ALIASES,
        "final response",
    )
    if response_commitment != tool_result_commitment:
        raise VerificationFailure("MCP response and reinjected tool result commitments differ")

    summary_checks = (
        (
            _RESPONSE_COMMITMENT_ALIASES,
            "MCP response",
            response_commitment,
        ),
        (
            _TOOL_RESULT_COMMITMENT_ALIASES,
            "reinjected tool result",
            tool_result_commitment,
        ),
        (
            _FINAL_COMMITMENT_ALIASES,
            "final response",
            final_commitment,
        ),
    )
    for aliases, label, expected in summary_checks:
        observed = _summary_commitment(
            after_summary,
            aliases,
            label,
        )
        if observed != expected:
            raise VerificationFailure(f"{label} commitment does not match chat response")
    return {
        "mcp_response": response_commitment,
        "reinject_tool_result": tool_result_commitment,
        "final_response": final_commitment,
    }


def _validate_turn_orchestration(response: Mapping[str, Any]) -> dict[str, Any]:
    orchestration = _response_orchestration(response)
    attempted = _counter(
        orchestration,
        _ATTEMPTED_COUNT_ALIASES,
        "turn attempted MCP",
    )
    successful = _counter(
        orchestration,
        _SUCCESSFUL_COUNT_ALIASES,
        "turn successful MCP",
    )
    if attempted != 1 or successful != 1:
        raise VerificationFailure(
            "browser chat turn did not record exactly one successful MCP invocation"
        )
    if orchestration.get("action") != "call_formowl_tool":
        raise VerificationFailure("browser chat turn did not use the FormOwl tool")
    if orchestration.get("response_kind") != "answer":
        raise VerificationFailure("browser chat turn did not finish with an answer")
    if orchestration.get("formowl_tool_called") is not True:
        raise VerificationFailure("browser chat turn tool-call flag is invalid")
    if orchestration.get("answer_fallback_used") is not False:
        raise VerificationFailure("browser chat turn used an answer fallback")
    if orchestration.get("tool_name") != _EXPECTED_TOOL_NAME:
        raise VerificationFailure("browser chat turn used an unexpected tool")
    return {
        "action": "call_formowl_tool",
        "response_kind": "answer",
        "tool_name": _EXPECTED_TOOL_NAME,
        "dynamic_tool_invocation_count": 1,
        "mcp_attempted_call_count": attempted,
        "mcp_successful_call_count": successful,
        "answer_fallback_used": False,
    }


def _validate_document_first_response(
    response: Mapping[str, Any],
) -> dict[str, Any]:
    if response.get("status") != "ok":
        raise VerificationFailure("document-first chat response was not successful")
    if response.get("answer_items") != []:
        raise VerificationFailure("document-first chat response contained precomputed answer items")
    if _FORBIDDEN_DOCUMENT_RESPONSE_KEYS.intersection(response):
        raise VerificationFailure("document-first chat response contained a forbidden oracle field")
    if _contains_document_value_field(response):
        raise VerificationFailure("document-first chat response exposed raw document fields")
    if response.get("document_payload_projection") != ("formowl_document_uat_public_metadata_v1"):
        raise VerificationFailure("document-first public projection is invalid")
    assistant_text = response.get("assistant_text")
    if not isinstance(assistant_text, str) or not assistant_text.strip():
        raise VerificationFailure("document-first assistant synthesis is missing")
    results = response.get("results")
    result_count = response.get("result_count")
    if (
        not isinstance(results, list)
        or not results
        or type(result_count) is not int
        or result_count != len(results)
    ):
        raise VerificationFailure(
            "document-first chat response contained no readable document result"
        )
    for item in results:
        if not isinstance(item, Mapping):
            raise VerificationFailure("document-first result item is invalid")
        if (
            _COMMITMENT_RE.fullmatch(str(item.get("content_sha256", ""))) is None
            or type(item.get("content_char_count")) is not int
            or item["content_char_count"] < 1
            or type(item.get("content_utf8_bytes")) is not int
            or item["content_utf8_bytes"] < 1
        ):
            raise VerificationFailure("document-first result metadata is invalid")
        if item.get("source_kind") != "authorized_document_export":
            raise VerificationFailure("document-first result source is invalid")
        if _FORBIDDEN_DOCUMENT_RESPONSE_KEYS.intersection(item):
            raise VerificationFailure("document-first result contained a forbidden oracle field")
    claim_boundary = response.get("claim_boundary")
    if not isinstance(claim_boundary, Mapping):
        raise VerificationFailure("document-first claim boundary is missing")
    for field_name, expected in _REQUIRED_DOCUMENT_CLAIM_BOUNDARY.items():
        if claim_boundary.get(field_name) is not expected:
            raise VerificationFailure("document-first claim boundary is invalid")
    return {
        "status": "ok",
        "result_count": result_count,
        "answer_items_count": 0,
        "authorized_existing_export_only": True,
        "read_only": True,
        "pst_or_extractor_invoked": False,
        "kg_or_ontology_invoked": False,
        "oracle_or_expected_answer_used": False,
        "canonical_graph_write_performed": False,
        "production_ready": False,
        "raw_document_fields_absent": True,
    }


def _validate_document_first_browser_observation(
    response: Mapping[str, Any],
    rendered_answer: str,
    *,
    forbidden_raw_sentinel: str | None = None,
) -> dict[str, Any]:
    report = _validate_document_first_response(response)
    if not isinstance(rendered_answer, str) or not rendered_answer.strip():
        raise VerificationFailure("document-first rendered assistant answer is missing")
    assistant_text = str(response["assistant_text"])
    if _normalize_rendered_text(assistant_text) not in _normalize_rendered_text(rendered_answer):
        raise VerificationFailure("document-first rendered DOM omitted the assistant synthesis")
    if forbidden_raw_sentinel is not None:
        if (
            not isinstance(forbidden_raw_sentinel, str)
            or not forbidden_raw_sentinel
            or forbidden_raw_sentinel in rendered_answer
            or forbidden_raw_sentinel
            in json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        ):
            raise VerificationFailure(
                "document-first browser observation exposed raw document content"
            )
    return {
        **report,
        "captured_network_json_redacted": True,
        "rendered_dom_redacted": True,
    }


def _contains_document_value_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in {"content", "snippet"} or _contains_document_value_field(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_document_value_field(item) for item in value)
    return False


class _WebSocket:
    def __init__(self, url: str, timeout_seconds: float) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise VerificationFailure("CDP WebSocket URL is invalid")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        try:
            connection = socket.create_connection(
                (parsed.hostname, port),
                timeout=timeout_seconds,
            )
            if parsed.scheme == "wss":
                connection = ssl.create_default_context().wrap_socket(
                    connection,
                    server_hostname=parsed.hostname,
                )
        except OSError as error:
            raise VerificationFailure("CDP WebSocket connection failed") from error
        self._socket = connection
        self._socket.settimeout(timeout_seconds)
        self._buffer = bytearray()
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        host = parsed.hostname
        if parsed.port is not None:
            host += f":{parsed.port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        try:
            self._socket.sendall(request)
            headers = self._read_headers()
        except OSError as error:
            self.close()
            raise VerificationFailure("CDP WebSocket handshake failed") from error
        status_line, _, raw_headers = headers.partition(b"\r\n")
        if b" 101 " not in status_line:
            self.close()
            raise VerificationFailure("CDP WebSocket upgrade was rejected")
        response_headers: dict[bytes, bytes] = {}
        for line in raw_headers.split(b"\r\n"):
            name, separator, value = line.partition(b":")
            if separator:
                response_headers[name.strip().lower()] = value.strip()
        expected_accept = base64.b64encode(
            hashlib.sha1(  # noqa: S324 - required by the WebSocket protocol
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        )
        if response_headers.get(b"sec-websocket-accept") != expected_accept:
            self.close()
            raise VerificationFailure("CDP WebSocket handshake is invalid")

    def _read_headers(self) -> bytes:
        marker = b"\r\n\r\n"
        while marker not in self._buffer:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise OSError("WebSocket closed during handshake")
            self._buffer.extend(chunk)
            if len(self._buffer) > 65536:
                raise OSError("WebSocket handshake is too large")
        index = self._buffer.index(marker)
        headers = bytes(self._buffer[:index])
        del self._buffer[: index + len(marker)]
        return headers

    def _read_exact(self, size: int) -> bytes:
        while len(self._buffer) < size:
            chunk = self._socket.recv(max(4096, size - len(self._buffer)))
            if not chunk:
                raise VerificationFailure("CDP WebSocket closed unexpectedly")
            self._buffer.extend(chunk)
        result = bytes(self._buffer[:size])
        del self._buffer[:size]
        return result

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = secrets.token_bytes(4)
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, length)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        try:
            self._socket.sendall(header + mask + masked)
        except OSError as error:
            raise VerificationFailure("CDP WebSocket write failed") from error

    def send_json(self, payload: Mapping[str, Any]) -> None:
        self._send_frame(
            0x1,
            json.dumps(
                dict(payload),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )

    def receive_json(self) -> dict[str, Any]:
        fragments = bytearray()
        started = False
        while True:
            first, second = struct.unpack("!BB", self._read_exact(2))
            final = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length)
            if masked:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            if opcode == 0x8:
                raise VerificationFailure("CDP WebSocket was closed")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                fragments = bytearray(payload)
                started = True
            elif opcode == 0x0 and started:
                fragments.extend(payload)
            else:
                continue
            if not final:
                continue
            try:
                decoded = json.loads(fragments.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise VerificationFailure("CDP WebSocket returned invalid JSON") from error
            if not isinstance(decoded, dict):
                raise VerificationFailure("CDP WebSocket returned an invalid message")
            return decoded

    def close(self) -> None:
        sock = getattr(self, "_socket", None)
        if sock is None:
            return
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            sock.close()
        finally:
            self._socket = None  # type: ignore[assignment]


class _CdpConnection:
    def __init__(self, websocket_url: str, timeout_seconds: float) -> None:
        self._websocket = _WebSocket(websocket_url, timeout_seconds)
        self._next_id = 1
        self._events: list[dict[str, Any]] = []

    def call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        request: dict[str, Any] = {
            "id": request_id,
            "method": method,
            "params": dict(params or {}),
        }
        if session_id is not None:
            request["sessionId"] = session_id
        self._websocket.send_json(request)
        while True:
            response = self._websocket.receive_json()
            if response.get("id") != request_id:
                if "id" not in response and isinstance(response.get("method"), str):
                    self._events.append(response)
                continue
            error = response.get("error")
            if isinstance(error, Mapping):
                raise VerificationFailure(f"CDP command failed: {method}")
            result = response.get("result", {})
            if not isinstance(result, dict):
                raise VerificationFailure(f"CDP command returned invalid data: {method}")
            return result

    def take_events(self) -> list[dict[str, Any]]:
        events = self._events
        self._events = []
        return events

    def close(self) -> None:
        self._websocket.close()


class _BrowserEndpoint(AbstractContextManager[str]):
    def __init__(
        self,
        *,
        browser_executable: Path | None,
        cdp_url: str | None,
    ) -> None:
        self._browser_executable = browser_executable
        self._cdp_url = cdp_url
        self._process: subprocess.Popen[str] | None = None
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> str:
        if self._cdp_url:
            return _resolve_websocket_url(self._cdp_url)
        executable = self._browser_executable
        if executable is None:
            discovered = next(
                (
                    path
                    for name in (
                        "chromium",
                        "chromium-browser",
                        "google-chrome",
                        "google-chrome-stable",
                    )
                    if (path := shutil.which(name)) is not None
                ),
                None,
            )
            if discovered is None:
                raise VerificationFailure("no Chromium executable found; provide --cdp-url")
            executable = Path(discovered)
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise VerificationFailure("browser executable is unavailable")
        self._temporary = tempfile.TemporaryDirectory(prefix="formowl-r8-browser-")
        command = [
            str(executable),
            "--headless=new",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-default-browser-check",
            "--no-first-run",
            "--remote-allow-origins=*",
            "--remote-debugging-port=0",
            f"--user-data-dir={self._temporary.name}",
            "about:blank",
        ]
        try:
            self._process = subprocess.Popen(  # noqa: S603
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as error:
            self.__exit__(None, None, None)
            raise VerificationFailure("browser could not be started") from error
        assert self._process.stderr is not None
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self.__exit__(None, None, None)
                raise VerificationFailure("browser exited before CDP became ready")
            readable, _, _ = select.select(
                [self._process.stderr],
                [],
                [],
                min(0.25, max(0.0, deadline - time.monotonic())),
            )
            if not readable:
                continue
            line = self._process.stderr.readline()
            match = re.search(r"DevTools listening on (ws://\S+)", line)
            if match is not None:
                return match.group(1)
        self.__exit__(None, None, None)
        raise VerificationFailure("browser CDP endpoint did not become ready")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            self._process = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None


def _resolve_websocket_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"ws", "wss"}:
        return value
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise VerificationFailure("CDP URL is invalid")
    endpoint = value.rstrip("/")
    if not endpoint.endswith("/json/version"):
        endpoint += "/json/version"
    payload = _request_json(endpoint)
    websocket_url = payload.get("webSocketDebuggerUrl")
    if not isinstance(websocket_url, str):
        raise VerificationFailure("CDP endpoint lacks a browser WebSocket URL")
    return websocket_url


def _runtime_value(
    cdp: _CdpConnection,
    session_id: str,
    expression: str,
    *,
    await_promise: bool = False,
) -> Any:
    result = cdp.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
            "userGesture": True,
        },
        session_id=session_id,
    )
    if "exceptionDetails" in result:
        raise VerificationFailure("browser JavaScript evaluation failed")
    remote = result.get("result")
    if not isinstance(remote, Mapping) or "value" not in remote:
        raise VerificationFailure("browser JavaScript returned no value")
    return remote["value"]


def _wait_for(
    cdp: _CdpConnection,
    session_id: str,
    expression: str,
    *,
    deadline: float,
    failure: str,
) -> Any:
    while time.monotonic() < deadline:
        value = _runtime_value(cdp, session_id, expression)
        if value:
            return value
        time.sleep(0.1)
    raise VerificationFailure(failure)


def _browser_fetch_json(
    cdp: _CdpConnection,
    session_id: str,
    path: str,
) -> dict[str, Any]:
    expression = f"""
        (async () => {{
          const response = await fetch({json.dumps(path)}, {{
            method: "GET",
            credentials: "same-origin",
            cache: "no-store"
          }});
          if (!response.ok) throw new Error("summary request failed");
          return await response.json();
        }})()
    """
    payload = _runtime_value(
        cdp,
        session_id,
        expression,
        await_promise=True,
    )
    if not isinstance(payload, dict):
        raise VerificationFailure("browser session summary is invalid")
    return payload


def _normalize_rendered_text(value: str) -> str:
    if not isinstance(value, str):
        raise VerificationFailure("browser answer text is invalid")
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _observer_script() -> str:
    return """
      (() => {
        const isObserverState = (value) => (
          value !== null
          && typeof value === "object"
          && Object.prototype.hasOwnProperty.call(
            value, "baselineAssistantCount"
          )
          && Array.isArray(value.baselineAssistantNodes)
        );
        const existing = Object.getOwnPropertyDescriptor(
          window, "__formowlR8Observer"
        );
        if (existing) return isObserverState(existing.value);
        const state = {
          baselineAssistantCount: null,
          baselineAssistantNodes: []
        };
        Object.defineProperty(window, "__formowlR8Observer", {
          value: state,
          writable: false,
          configurable: false
        });
        return isObserverState(window.__formowlR8Observer);
      })();
    """


def _prepare_answer_observer_expression() -> str:
    return """
      (() => {
        const observer = window.__formowlR8Observer;
        if (!observer) return false;
        const candidates = Array.from(document.querySelectorAll(
          ".message.assistant, [data-role='assistant'], [data-message-role='assistant']"
        ));
        observer.baselineAssistantNodes = candidates;
        observer.baselineAssistantCount = candidates.length;
        return true;
      })()
    """


def _answer_probe_expression() -> str:
    return """
      (() => {
        const observer = window.__formowlR8Observer || {};
        const candidates = Array.from(document.querySelectorAll(
          ".message.assistant, [data-role='assistant'], [data-message-role='assistant']"
        ));
        const baselineNodes = Array.isArray(observer.baselineAssistantNodes)
          ? observer.baselineAssistantNodes
          : [];
        const added = candidates.filter((node) => !baselineNodes.includes(node));
        const latest = added.length ? added[added.length - 1] : null;
        const errorNode = latest ? latest.querySelector(".error-text, [role='alert']") : null;
        const answerNode = latest ? (
          latest.querySelector(".bubble > .assistant-text") ||
          latest.querySelector(".assistant-text")
        ) : null;
        return {
          baselineAssistantCount: observer.baselineAssistantCount,
          currentAssistantCount: candidates.length,
          addedAssistantCount: added.length,
          answer: answerNode ? String(answerNode.innerText || answerNode.textContent || "").trim() : "",
          error: errorNode ? String(errorNode.innerText || errorNode.textContent || "").trim() : "",
          sendDisabled: Boolean(document.querySelector("#send")?.disabled)
        };
      })()
    """


def _origin_key(value: str) -> tuple[str, str, int]:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise VerificationFailure("browser request origin is invalid")
    return (
        parsed.scheme,
        parsed.hostname.casefold(),
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


def _matches_same_origin_path(
    request_url: str,
    *,
    page_url: str,
    query_path: str,
) -> bool:
    try:
        parsed_request = urlparse(request_url)
        return (
            _origin_key(request_url) == _origin_key(page_url) and parsed_request.path == query_path
        )
    except (ValueError, VerificationFailure):
        return False


def _collect_chat_network_events(
    cdp: _CdpConnection,
    *,
    session_id: str,
    page_url: str,
    query_path: str,
    request_ids: set[str],
    successful_response_ids: set[str],
    completed_ids: set[str],
) -> None:
    for event in cdp.take_events():
        event_session_id = event.get("sessionId")
        if event_session_id not in {None, session_id}:
            continue
        method = event.get("method")
        params = event.get("params")
        if not isinstance(params, Mapping):
            continue
        request_id = params.get("requestId")
        if not isinstance(request_id, str):
            continue
        if method == "Network.requestWillBeSent":
            request = params.get("request")
            if (
                isinstance(request, Mapping)
                and request.get("method") == "POST"
                and isinstance(request.get("url"), str)
                and _matches_same_origin_path(
                    request["url"],
                    page_url=page_url,
                    query_path=query_path,
                )
            ):
                request_ids.add(request_id)
        elif method == "Network.responseReceived" and request_id in request_ids:
            response = params.get("response")
            if not isinstance(response, Mapping) or response.get("status") != 200:
                raise VerificationFailure("same-origin chat response was not successful")
            successful_response_ids.add(request_id)
        elif method == "Network.loadingFinished" and request_id in request_ids:
            completed_ids.add(request_id)


def _cdp_response_json(
    cdp: _CdpConnection,
    *,
    session_id: str,
    request_id: str,
) -> dict[str, Any]:
    result = cdp.call(
        "Network.getResponseBody",
        {"requestId": request_id},
        session_id=session_id,
    )
    body = result.get("body")
    if not isinstance(body, str):
        raise VerificationFailure("CDP chat response body is invalid")
    try:
        raw = (
            base64.b64decode(body, validate=True)
            if result.get("base64Encoded")
            else body.encode("utf-8")
        )
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationFailure("CDP chat response JSON is invalid") from error
    if not isinstance(payload, dict):
        raise VerificationFailure("CDP chat response JSON is invalid")
    return payload


def _run_browser_flow(
    *,
    websocket_url: str,
    page_url: str,
    summary_path: str,
    query_path: str,
    query: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, float]:
    cdp = _CdpConnection(websocket_url, min(timeout_seconds, 30.0))
    context_id: str | None = None
    target_id: str | None = None
    try:
        context_result = cdp.call("Target.createBrowserContext")
        context_id = context_result.get("browserContextId")
        if not isinstance(context_id, str):
            raise VerificationFailure("CDP did not create a browser context")
        target_result = cdp.call(
            "Target.createTarget",
            {"url": "about:blank", "browserContextId": context_id},
        )
        target_id = target_result.get("targetId")
        if not isinstance(target_id, str):
            raise VerificationFailure("CDP did not create a page target")
        attach_result = cdp.call(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True},
        )
        session_id = attach_result.get("sessionId")
        if not isinstance(session_id, str):
            raise VerificationFailure("CDP did not attach to the page target")
        cdp.call("Page.enable", session_id=session_id)
        cdp.call("Runtime.enable", session_id=session_id)
        cdp.call("Network.enable", session_id=session_id)
        observer_source = _observer_script()
        try:
            observer_registration = cdp.call(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": observer_source},
                session_id=session_id,
            )
        except VerificationFailure as error:
            raise VerificationFailure("browser observer bootstrap failed") from error
        observer_identifier = observer_registration.get("identifier")
        if not isinstance(observer_identifier, str) or not observer_identifier:
            raise VerificationFailure("browser observer bootstrap failed")
        cdp.call("Page.navigate", {"url": page_url}, session_id=session_id)
        setup_deadline = time.monotonic() + min(30.0, timeout_seconds)
        _wait_for(
            cdp,
            session_id,
            """
              document.readyState === "complete"
              && Boolean(document.querySelector("#chat-input"))
              && Boolean(document.querySelector("#send"))
            """,
            deadline=setup_deadline,
            failure="UAT page did not expose the chat controls",
        )
        try:
            observer_ready = _runtime_value(
                cdp,
                session_id,
                observer_source,
            )
        except VerificationFailure as error:
            raise VerificationFailure("browser observer bootstrap failed") from error
        if observer_ready is not True:
            raise VerificationFailure("browser observer bootstrap failed")
        before_summary = _browser_fetch_json(cdp, session_id, summary_path)
        baseline_ready = _runtime_value(
            cdp,
            session_id,
            _prepare_answer_observer_expression(),
        )
        if baseline_ready is not True:
            raise VerificationFailure("browser could not snapshot existing answers")
        cdp.take_events()
        submit_result = _runtime_value(
            cdp,
            session_id,
            f"""
              (() => {{
                const input = document.querySelector("#chat-input");
                const send = document.querySelector("#send");
                if (!input || !send || send.disabled) return false;
                const setter = Object.getOwnPropertyDescriptor(
                  HTMLTextAreaElement.prototype, "value"
                ).set;
                setter.call(input, {json.dumps(query)});
                input.dispatchEvent(new Event("input", {{ bubbles: true }}));
                input.dispatchEvent(new Event("change", {{ bubbles: true }}));
                send.click();
                return true;
              }})()
            """,
        )
        if submit_result is not True:
            raise VerificationFailure("UAT page could not submit the browser query")
        query_started = time.monotonic()
        deadline = query_started + timeout_seconds
        probe: Mapping[str, Any] | None = None
        chat_response: dict[str, Any] | None = None
        chat_request_ids: set[str] = set()
        successful_response_ids: set[str] = set()
        completed_ids: set[str] = set()
        while time.monotonic() < deadline:
            candidate = _runtime_value(
                cdp,
                session_id,
                _answer_probe_expression(),
            )
            _collect_chat_network_events(
                cdp,
                session_id=session_id,
                page_url=page_url,
                query_path=query_path,
                request_ids=chat_request_ids,
                successful_response_ids=successful_response_ids,
                completed_ids=completed_ids,
            )
            if len(chat_request_ids) > 1:
                raise VerificationFailure("browser issued more than one chat request")
            ready_ids = successful_response_ids.intersection(completed_ids)
            if chat_response is None and len(ready_ids) == 1:
                chat_response = _cdp_response_json(
                    cdp,
                    session_id=session_id,
                    request_id=next(iter(ready_ids)),
                )
            if not isinstance(candidate, Mapping):
                raise VerificationFailure("browser answer probe is invalid")
            if candidate.get("error"):
                raise VerificationFailure("UAT page rendered an error response")
            answer = candidate.get("answer")
            if (
                chat_response is not None
                and candidate.get("sendDisabled") is False
                and isinstance(answer, str)
                and answer.strip()
                and answer.strip() not in _THINKING_TEXTS
                and answer.strip() not in _ERROR_TEXTS
            ):
                probe = candidate
                break
            time.sleep(0.2)
        if probe is None:
            raise VerificationFailure("UAT page did not render a non-placeholder answer")
        if (
            len(chat_request_ids) != 1
            or len(successful_response_ids) != 1
            or len(completed_ids.intersection(chat_request_ids)) != 1
        ):
            raise VerificationFailure("browser did not record exactly one successful chat response")
        response = chat_response
        answer = probe.get("answer")
        if not isinstance(response, dict) or not isinstance(answer, str):
            raise VerificationFailure("browser did not capture the chat response")
        if probe.get("addedAssistantCount") != 1:
            raise VerificationFailure(
                "browser did not bind the answer to one newly rendered assistant message"
            )
        assistant_text = response.get("assistant_text")
        if not isinstance(assistant_text, str) or not assistant_text.strip():
            raise VerificationFailure("chat response assistant_text is missing")
        if _normalize_rendered_text(answer) != _normalize_rendered_text(assistant_text):
            raise VerificationFailure(
                "newly rendered DOM answer does not match chat response assistant_text"
            )
        after_summary = _browser_fetch_json(cdp, session_id, summary_path)
        return (
            before_summary,
            after_summary,
            response,
            answer,
            time.monotonic() - query_started,
        )
    finally:
        if target_id is not None:
            try:
                cdp.call("Target.closeTarget", {"targetId": target_id})
            except VerificationFailure:
                pass
        if context_id is not None:
            try:
                cdp.call(
                    "Target.disposeBrowserContext",
                    {"browserContextId": context_id},
                )
            except VerificationFailure:
                pass
        cdp.close()


def _write_report(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(encoded)
        temporary.flush()
        temporary_path = Path(temporary.name)
    temporary_path.chmod(0o600)
    temporary_path.replace(path)
    path.chmod(0o600)


def verify_browser_contract(
    *,
    base_url: str,
    page_path: str,
    summary_path: str,
    query_path: str,
    query: str,
    browser_executable: Path | None,
    cdp_url: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise VerificationFailure("query is invalid")
    if not 0 < timeout_seconds <= DEFAULT_TIMEOUT_SECONDS:
        raise VerificationFailure("timeout must be between zero and 360 seconds")
    page_url = _safe_url(base_url, page_path)
    _safe_url(base_url, summary_path)
    _safe_url(base_url, query_path)
    with _BrowserEndpoint(
        browser_executable=browser_executable,
        cdp_url=cdp_url,
    ) as websocket_url:
        before, after, response, answer, elapsed = _run_browser_flow(
            websocket_url=websocket_url,
            page_url=page_url,
            summary_path=summary_path,
            query_path=query_path,
            query=query,
            timeout_seconds=timeout_seconds,
        )
    counts = _validate_count_deltas(before, after)
    commitments = _validate_commitments(response, after)
    turn_orchestration = _validate_turn_orchestration(response)
    document_first_response = _validate_document_first_browser_observation(
        response,
        answer,
    )
    answer_bytes = answer.encode("utf-8")
    query_bytes = query.encode("utf-8")
    return {
        "artifact_type": "formowl_browser_contract_r8",
        "status": "passed",
        "browser_transport": "cdp",
        "query_route": "browser_to_one_sidecar_to_one_read_only_mcp",
        "query_sha256": "sha256:" + hashlib.sha256(query_bytes).hexdigest(),
        "query_utf8_bytes": len(query_bytes),
        "answer_sha256": "sha256:" + hashlib.sha256(answer_bytes).hexdigest(),
        "answer_utf8_bytes": len(answer_bytes),
        "query_elapsed_ms": round(elapsed * 1000, 3),
        "mcp_counts": counts,
        "commitments": commitments,
        "turn_orchestration": turn_orchestration,
        "document_first_response": document_first_response,
        "dom_answer_non_placeholder": True,
        "chat_fetch_observed_in_browser": True,
    }


def main() -> int:
    args = _argument_parser().parse_args()
    try:
        report = verify_browser_contract(
            base_url=args.base_url,
            page_path=args.page_path,
            summary_path=args.summary_path,
            query_path=args.query_path,
            query=args.query,
            browser_executable=args.browser_executable,
            cdp_url=args.cdp_url,
            timeout_seconds=args.timeout_seconds,
        )
    except VerificationFailure as error:
        _write_report(
            args.report,
            {
                "artifact_type": "formowl_browser_contract_r8",
                "status": "failed",
                "reason": str(error),
            },
        )
        raise SystemExit(1) from error
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
