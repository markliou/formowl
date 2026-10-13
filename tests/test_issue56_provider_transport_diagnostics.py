"""Provider-free transport causes through the existing public/trace owners."""

from collections import deque
from contextlib import redirect_stderr
import errno
import hashlib
import http.client
import io
import json
import socket
import ssl
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import _paths  # noqa: F401
from formowl_mail import human_uat_orchestrator as uat
from formowl_mail.human_uat_http import _safe_provider_diagnostic as http_safe
from formowl_gateway.issue56_uat_runtime import (
    _emit_private_uat_terminal_trace,
    _safe_provider_diagnostic as gateway_safe,
)
from test_issue56_provider_stream_recovery import _respond


_PRIVATE = "Bearer synthetic-secret https://private.invalid /private/source prompt-private"
_WIRE = b': heartbeat\n\n'
_REQUEST_ID = "private-request-id"
_COMPLETED = b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'


class _Response:
    status = 200
    headers = {"Content-Type": "text/event-stream", "x-request-id": _REQUEST_ID,
               "Authorization": _PRIVATE}

    def __init__(self, chunks, close_error=None):
        self.chunks = deque(chunks)
        self.close_error = close_error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        if self.close_error is not None:
            raise self.close_error
        return False

    def read1(self, _size):
        chunk = self.chunks.popleft() if self.chunks else b""
        if isinstance(chunk, Exception):
            raise chunk
        return chunk

    read = read1


class ProviderTransportDiagnosticsTests(unittest.TestCase):
    def _failure(self, *, response=None, error=None, stream=True, payload=None):
        provider = uat.CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="synthetic-key",
            timeout_seconds=3,
        )
        opener = Mock()
        opener.open.side_effect = error
        opener.open.return_value = response
        with patch.object(uat.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(uat._UatProviderFailure) as raised:
                provider._request_response(payload or {"model": "synthetic", "stream": stream})
        return raised.exception.safe_diagnostic

    def _assert_safe(self, diagnostic):
        for public in (diagnostic, http_safe(diagnostic), gateway_safe(diagnostic)):
            rendered = json.dumps(public)
            for private in (_PRIVATE, "synthetic-secret", "private.invalid", "/private/source",
                            "prompt-private", _REQUEST_ID):
                self.assertNotIn(private, rendered)

    def test_sse_reset_retains_received_wire_and_safe_root_cause(self):
        diagnostic = self._failure(response=_Response([
            _WIRE, ConnectionResetError(errno.ECONNRESET, _PRIVATE),
        ]))
        self.assertEqual(diagnostic["reason_code"], "transport_error")
        self.assertEqual(diagnostic["failure_phase"], "sse_read")
        self.assertEqual(diagnostic["transport_exception_type"], "ConnectionResetError")
        self.assertEqual(diagnostic["transport_errno"], errno.ECONNRESET)
        self.assertEqual(diagnostic["http_status"], 200)
        self.assertEqual(diagnostic["response_body_bytes"], len(_WIRE))
        self.assertEqual(diagnostic["request_timeout_seconds"], 3)
        self.assertTrue(0 <= diagnostic["remaining_deadline_seconds"] <= 3)
        expected_hash = "sha256:" + hashlib.sha256(_REQUEST_ID.encode()).hexdigest()
        self.assertEqual(diagnostic["response_request_id_sha256"], expected_hash)
        for project in (http_safe, gateway_safe):
            public = project(diagnostic)
            for key in ("failure_phase", "transport_exception_type", "transport_errno",
                        "request_timeout_seconds", "remaining_deadline_seconds",
                        "response_request_id_sha256", "response_body_bytes", "http_status"):
                self.assertEqual(public[key], diagnostic[key])
        self._assert_safe(diagnostic)

    def test_connect_url_reason_and_sse_nested_causes_preserve_existing_reason(self):
        for nested, kind in ((TimeoutError(_PRIVATE), "TimeoutError"),
                             (ssl.SSLError(1, _PRIVATE), "SSLError"),
                             (socket.gaierror(socket.EAI_AGAIN, _PRIVATE), "gaierror"),
                             (OSError(errno.EIO, _PRIVATE), "OSError"),
                             (http.client.RemoteDisconnected(_PRIVATE), "RemoteDisconnected"),
                             (_PRIVATE, "non_exception")):
            for streaming_read in (False, True):
                with self.subTest(kind=kind, streaming_read=streaming_read):
                    error = uat.urllib.error.URLError(nested)
                    diagnostic = self._failure(
                        response=_Response([_WIRE, error]) if streaming_read else None,
                        error=None if streaming_read else error,
                    )
                    expected = "transport_timeout" if kind == "TimeoutError" else "transport_error"
                    self.assertEqual(diagnostic["reason_code"], expected)
                    self.assertEqual(diagnostic["failure_phase"], "sse_read" if streaming_read else "connect_headers")
                    self.assertEqual(diagnostic["transport_exception_type"], "URLError")
                    self.assertEqual(diagnostic["transport_causes"][0]["relation"], "reason")
                    self.assertEqual(diagnostic["transport_causes"][0]["exception_type"], kind)
                    self._assert_safe(diagnostic)

    def test_timeout_and_partial_json_read_keep_status_and_received_bytes(self):
        for stream, error, kind, size in (
            (True, TimeoutError(_PRIVATE), "TimeoutError", len(_WIRE)),
            (False, http.client.IncompleteRead(b"private-body", 100), "IncompleteRead", 12),
        ):
            with self.subTest(stream=stream):
                response = _Response([_WIRE, error] if stream else [error])
                diagnostic = self._failure(response=response, stream=stream)
                self.assertEqual(diagnostic["failure_phase"], "sse_read" if stream else "json_read")
                self.assertEqual(diagnostic["transport_exception_type"], kind)
                self.assertEqual(diagnostic["http_status"], 200)
                self.assertEqual(diagnostic["response_body_bytes"], size)
                self.assertNotIn("private-body", json.dumps(diagnostic))
                self._assert_safe(diagnostic)

    def test_expired_before_sse_read_retains_zero_remaining_deadline(self):
        response = Mock()
        with patch.object(uat.time, "monotonic", return_value=11.0):
            with self.assertRaises(uat._UatProviderFailure) as raised:
                uat._read_responses_sse_terminal(
                    response, deadline=10.0, http_status=200,
                    headers=_Response.headers, request_shape=None, timeout_seconds=3,
                )
        diagnostic = raised.exception.safe_diagnostic
        self.assertEqual(diagnostic["reason_code"], "transport_timeout")
        self.assertEqual(diagnostic["failure_phase"], "sse_read")
        self.assertEqual(diagnostic["remaining_deadline_seconds"], 0.0)
        self.assertEqual(diagnostic["response_body_bytes"], 0)
        response.read1.assert_not_called()
        for project in (http_safe, gateway_safe):
            self.assertEqual(project(diagnostic)["remaining_deadline_seconds"], 0.0)

    def test_prepare_close_and_http_error_body_read_are_distinct(self):
        cases = (
            (dict(payload={"model": object()}), "prepare", "TypeError", None),
            (dict(response=_Response([_COMPLETED], RuntimeError(_PRIVATE))), "close", "RuntimeError", 200),
        )
        for arguments, phase, kind, status in cases:
            with self.subTest(phase=phase):
                diagnostic = self._failure(**arguments)
                self.assertEqual(diagnostic["failure_phase"], phase)
                self.assertEqual(diagnostic["transport_exception_type"], kind)
                self.assertEqual(diagnostic["http_status"], status)
                self._assert_safe(diagnostic)
        http_error = uat.urllib.error.HTTPError("https://private.invalid", 503, _PRIVATE,
                                              _Response.headers, None)
        http_error.read = Mock(side_effect=ConnectionResetError(errno.ECONNRESET, _PRIVATE))
        diagnostic = self._failure(error=http_error)
        self.assertEqual(diagnostic["reason_code"], "http_error")
        self.assertEqual(diagnostic["http_status"], 503)
        self.assertEqual(diagnostic["failure_phase"], "http_error_read")
        self.assertEqual(diagnostic["transport_exception_type"], "ConnectionResetError")
        self._assert_safe(diagnostic)

    def test_close_during_failure_preserves_primary_read_diagnostic(self):
        for stream in (True, False):
            with self.subTest(stream=stream):
                response = _Response(
                    [_WIRE, ConnectionResetError(errno.ECONNRESET, _PRIVATE)] if stream
                    else [ConnectionResetError(errno.ECONNRESET, _PRIVATE)],
                    RuntimeError("private-close"),
                )
                diagnostic = self._failure(response=response, stream=stream)
                self.assertEqual(diagnostic["failure_phase"], "sse_read" if stream else "json_read")
                self.assertEqual(diagnostic["transport_exception_type"], "ConnectionResetError")
                self.assertEqual(diagnostic["transport_errno"], errno.ECONNRESET)
                self.assertEqual(diagnostic["response_body_bytes"], len(_WIRE) if stream else 0)
                self.assertNotIn("private-close", json.dumps(diagnostic))

    def test_nested_causes_are_bounded_cycle_safe_and_unknown_names_hidden(self):
        class PrivateSecretError(RuntimeError):
            pass
        root = PrivateSecretError(_PRIVATE)
        previous = root
        for _ in range(20):
            child = OSError(errno.EIO, _PRIVATE)
            previous.__cause__ = child
            previous = child
        previous.__cause__ = root
        diagnostic = self._failure(error=root)
        self.assertEqual(diagnostic["transport_exception_type"], "RuntimeError")
        self.assertTrue(0 < len(diagnostic["transport_causes"]) <= 4)
        self.assertNotIn("PrivateSecretError", json.dumps(diagnostic))
        root.__cause__ = root
        diagnostic = self._failure(error=root)
        self.assertEqual(diagnostic["transport_causes"], [])
        self._assert_safe(diagnostic)

    def test_public_projections_reject_forged_diagnostic_fields(self):
        for project in (http_safe, gateway_safe):
            value = project({"failure_phase": _PRIVATE, "transport_exception_type": _PRIVATE,
                             "transport_errno": True, "request_timeout_seconds": float("inf"),
                             "remaining_deadline_seconds": -1, "response_request_id_sha256": _PRIVATE,
                             "transport_causes": [{"relation": _PRIVATE, "exception_type": "OSError", "errno": 5}]})
            for field in ("failure_phase", "transport_exception_type", "transport_errno",
                          "request_timeout_seconds", "remaining_deadline_seconds", "response_request_id_sha256"):
                self.assertNotIn(field, value)
            self.assertNotIn(_PRIVATE, json.dumps(value))
            huge = project({"request_timeout_seconds": 10 ** 1000,
                            "remaining_deadline_seconds": 10 ** 1000})
            self.assertNotIn("request_timeout_seconds", huge)
            self.assertNotIn("remaining_deadline_seconds", huge)

    def test_respond_attempt_and_terminal_trace_retain_failure_without_retry(self):
        provider = uat.CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="synthetic-key",
            stream_initial_requests=True,
        )
        opener = Mock()
        opener.open.return_value = _Response([_WIRE, OSError(errno.EIO, _PRIVATE)])
        backend = Mock()
        with patch.object(uat.urllib.request, "build_opener", return_value=opener):
            outcome = _respond(provider, backend)
        opener.open.assert_called_once()
        backend.assert_not_called()
        self.assertEqual(outcome.provider_diagnostic["reason_code"], "transport_error")
        for project in (http_safe, gateway_safe):
            public = project(outcome.provider_diagnostic)
            self.assertEqual(public["failure_phase"], "sse_read")
            attempt = public["provider_attempts"][-1]
            self.assertEqual(attempt["transport_exception_type"], "OSError")
            self.assertEqual(attempt["failure_phase"], "sse_read")
            self.assertEqual(attempt["http_status"], 200)
        output = io.StringIO()
        with redirect_stderr(output):
            _emit_private_uat_terminal_trace("provider", started_at=0, outcome=SimpleNamespace(
                response_kind=outcome.response_kind, provider_diagnostic=outcome.provider_diagnostic))
        trace = json.loads(output.getvalue())["provider_diagnostic"]
        self.assertEqual(trace["failure_phase"], "sse_read")
        self.assertEqual(trace["transport_errno"], errno.EIO)
        self.assertEqual(trace["provider_attempts"][-1]["transport_exception_type"], "OSError")
        self._assert_safe(trace)


if __name__ == "__main__":
    unittest.main()
