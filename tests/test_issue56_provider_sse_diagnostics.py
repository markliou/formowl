"""Same-call, provider-free SSE failure diagnostics and terminal boundaries."""

from __future__ import annotations

from collections import deque
import hashlib
import json
import unittest
from unittest.mock import Mock, patch

import _paths  # noqa: F401
from formowl_mail import human_uat_orchestrator as uat


def _event(name, payload):
    prefix = f"event: {name}\n" if name else ""
    return (prefix + "data: " + json.dumps(payload) + "\n\n").encode()


class _Stream:
    status = 200
    headers = {"Content-Type": "text/event-stream"}

    def __init__(self, chunks):
        self.chunks = deque(chunks)
        self.read_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read1(self, _size):
        self.read_count += 1
        chunk = self.chunks.popleft() if self.chunks else b""
        if isinstance(chunk, Exception):
            raise chunk
        return chunk


class ProviderSseDiagnosticsTests(unittest.TestCase):
    def _request(self, stream):
        provider = uat.CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="synthetic-key",
        )
        opener = Mock()
        opener.open.return_value = stream
        with patch.object(uat.urllib.request, "build_opener", return_value=opener):
            return provider._request_response({"model": "synthetic", "stream": True})

    def _failure(self, chunks):
        stream = _Stream(chunks)
        with self.assertRaises(uat._UatProviderFailure) as raised:
            self._request(stream)
        return raised.exception, stream

    def test_named_error_preserves_flat_and_nested_data_before_later_completion(self):
        flat = {"type": "error", "code": "server_error", "message": "Capacity unavailable",
                "param": "model", "sequence_number": 7}
        nested = {"type": "error", "error": {"code": "server_error", "type": "server_error",
                                            "message": "Capacity unavailable", "param": "model"}}
        completed = _event("response.completed", {
            "type": "response.completed", "response": {"status": "completed"},
        })
        for payload in (flat, nested, {"error": nested["error"]}):
            with self.subTest(nested="error" in payload):
                failure, stream = self._failure([_event("error", payload), completed])
                diagnostic = failure.safe_diagnostic
                self.assertEqual(diagnostic["reason_code"], "provider_error")
                self.assertEqual(diagnostic["provider_error_code"], "server_error")
                self.assertEqual(diagnostic["provider_error_param"], "model")
                self.assertEqual(diagnostic["provider_error_message_class"], "capacity_unavailable")
                self.assertEqual(diagnostic["provider_error_type"],
                                 "server_error" if "error" in payload else None)
                self.assertEqual(diagnostic["http_status"], 200)
                self.assertEqual(diagnostic["request_shape"]["has_stream"], True)
                self.assertEqual(stream.read_count, 1)
                self.assertFalse(failure.pre_mcp_stream_disconnected)

    def test_flat_data_only_error_hashes_unrecognized_values_without_leaks(self):
        payload = {"type": "error", "code": "synthetic-private-code", "param": "private-field",
                   "message": "synthetic-private-message /private/path Bearer synthetic-secret",
                   "sequence_number": 13}
        failure, _ = self._failure([_event(None, payload)])
        diagnostic = failure.safe_diagnostic
        self.assertEqual(diagnostic["reason_code"], "provider_error")
        for field in ("code", "param"):
            self.assertIsNone(diagnostic["provider_error_" + field])
            self.assertEqual(diagnostic["provider_error_" + field + "_sha256"],
                             "sha256:" + hashlib.sha256(payload[field].encode()).hexdigest())
        from formowl_mail.human_uat_http import _safe_provider_diagnostic as http_safe
        from formowl_gateway.issue56_uat_runtime import _safe_provider_diagnostic as runtime_safe
        for public in (diagnostic, http_safe(diagnostic), runtime_safe(diagnostic)):
            self.assertEqual(public["provider_error_code_sha256"],
                             diagnostic["provider_error_code_sha256"])
            rendered = json.dumps(public)
            for raw in (payload["code"], payload["param"], payload["message"], "synthetic-secret"):
                self.assertNotIn(raw, rendered)
            self.assertNotIn("sequence_number", public)
        self.assertNotIn(payload["message"], str(failure))

    def test_legacy_flat_object_error_diagnostic_still_works(self):
        diagnostic = uat._provider_diagnostic(
            reason_code="provider_error", http_status=400,
            response={"object": "error", "type": "invalid_request_error", "code": "invalid_parameter",
                      "param": "stream", "message": "Unsupported parameter"},
        )
        self.assertEqual(diagnostic["provider_error_type"], "invalid_request_error")
        self.assertEqual(diagnostic["provider_error_code"], "invalid_parameter")
        self.assertEqual(diagnostic["provider_error_message_class"], "invalid_parameter")

    def test_bad_json_is_not_provider_error_or_terminal_eof(self):
        for wire in (b'event: error\ndata: {broken\n\n', b'data: {broken\n\n',
                     b'event: response.completed\ndata: {broken\n\n'):
            with self.subTest(wire=wire):
                failure, _ = self._failure([wire])
                self.assertEqual(failure.safe_diagnostic["reason_code"], "invalid_json_response")

    def test_invalid_error_shapes_are_not_provider_errors(self):
        wires = (
            _event("error", []), _event(None, []), b'event: error\n\n',
            _event("response.created", {"type": "error", "code": "server_error"}),
            _event("error", {"type": "response.created"}),
            _event("error", {"type": ["error"]}),
        )
        for wire in wires:
            with self.subTest(wire=wire):
                failure, _ = self._failure([wire])
                self.assertEqual(failure.safe_diagnostic["reason_code"], "invalid_top_level_shape")

    def test_eof_before_dispatched_terminal_is_distinct_from_invalid_framing(self):
        created = _event("response.created", {"type": "response.created"})
        incomplete_frame = _event("response.completed", {
            "type": "response.completed", "response": {"status": "completed"},
        }).rstrip(b"\n") + b"\n"
        for wire in (b"", b": heartbeat\n\n", created, incomplete_frame):
            with self.subTest(wire=wire):
                failure, _ = self._failure([wire, b""])
                self.assertEqual(failure.safe_diagnostic["reason_code"], "unexpected_sse_response")
        for wire in (b'<html>synthetic failure</html>\n\n', b'{"status":"completed"}\n\n'):
            with self.subTest(framing=wire):
                failure, _ = self._failure([wire, b""])
                self.assertEqual(failure.safe_diagnostic["reason_code"], "invalid_sse_response")

    def test_timeout_retains_same_call_stream_byte_count(self):
        wire = _event("response.created", {"type": "response.created"})
        failure, stream = self._failure([wire, TimeoutError("synthetic-private-timeout")])
        diagnostic = failure.safe_diagnostic
        self.assertEqual(diagnostic["reason_code"], "transport_timeout")
        self.assertEqual(diagnostic["response_body_bytes"], len(wire))
        self.assertEqual(diagnostic["response_body_shape"], "sse")
        self.assertEqual(stream.read_count, 2)
        self.assertNotIn("synthetic-private-timeout", json.dumps(diagnostic))

    def test_failed_and_incomplete_terminal_keep_existing_validation(self):
        failed = {"status": "failed", "error": {"code": "server_error", "type": "server_error"}}
        failure, stream = self._failure([_event("response.failed", {
            "type": "response.failed", "response": failed,
        })])
        self.assertEqual(failure.safe_diagnostic["reason_code"], "provider_error")
        self.assertEqual(failure.safe_diagnostic["provider_status"], "failed")
        self.assertEqual(stream.read_count, 1)
        incomplete = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
        self.assertEqual(self._request(_Stream([_event("response.incomplete", {
            "type": "response.incomplete", "response": incomplete,
        })])), incomplete)

    def test_expiry_after_read_wins_over_eof_or_late_terminal(self):
        terminal = _event("response.completed", {
            "type": "response.completed", "response": {"status": "completed"},
        })
        for wire in (b"", terminal):
            with self.subTest(late_terminal=bool(wire)):
                with patch.object(uat.time, "monotonic", side_effect=(10.0, 10.5, 11.0)):
                    provider = uat.CodexResponsesConversationModel(
                        base_url="https://provider.example.test/v1", api_key="synthetic-key",
                        timeout_seconds=1,
                    )
                    opener = Mock()
                    opener.open.return_value = _Stream([wire])
                    with patch.object(uat.urllib.request, "build_opener", return_value=opener):
                        with self.assertRaises(uat._UatProviderFailure) as raised:
                            provider._request_response({"model": "synthetic", "stream": True})
                self.assertEqual(raised.exception.safe_diagnostic["reason_code"], "transport_timeout")
                self.assertEqual(raised.exception.safe_diagnostic["response_body_bytes"], len(wire))

    def test_split_utf8_crlf_multiline_terminal_remains_valid(self):
        wire = ('\ufeff: heartbeat\r\n\r\nevent: response.completed\r\n'
                'data: {"type":"response.completed",\r\n'
                'data: "response":{"status":"completed","output_text":"合成文字"}}\r\n\r\n').encode()
        parsed = self._request(_Stream([bytes([byte]) for byte in wire]))
        self.assertEqual(parsed["output_text"], "合成文字")

    def test_sse_failures_stop_without_retry_or_mcp(self):
        from test_issue56_provider_stream_recovery import _respond
        wire = _event("error", {"type": "error", "code": "server_error", "message": "unavailable"})
        for chunks, reason, outcome in (([wire], "provider_error", "error"),
                                        ([b": heartbeat\n\n", b""], "unexpected_sse_response", "error"),
                                        ([TimeoutError()], "transport_timeout", "timeout")):
            with self.subTest(reason=reason):
                stream = _Stream(chunks)
                opener = Mock()
                opener.open.return_value = stream
                backend = Mock()
                provider = uat.CodexResponsesConversationModel(
                    base_url="https://provider.example.test/v1", api_key="synthetic-key",
                    stream_initial_requests=True,
                )
                with patch.object(uat.urllib.request, "build_opener", return_value=opener):
                    result = _respond(provider, backend)
                opener.open.assert_called_once()
                backend.assert_not_called()
                self.assertEqual(result.response_kind, "clarification")
                self.assertEqual(result.provider_diagnostic["reason_code"], reason)
                self.assertEqual(result.provider_diagnostic["provider_attempt_count"], 1)
                self.assertEqual(result.provider_diagnostic["provider_attempts"][-1]["outcome"], outcome)


if __name__ == "__main__":
    unittest.main()
