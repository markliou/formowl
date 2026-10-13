"""Bounded, pre-tool recovery for a proven upstream stream-termination error."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import Mock, patch

import _paths  # noqa: F401
from formowl_mail import human_uat_orchestrator as uat
import test_issue56_provider_source_scope as scope


_DISCONNECTED = "stream error: stream disconnected before completion: stream closed before response.completed"


def _failure(message=_DISCONNECTED):
    return {"error": {"type": "invalid_request_error", "message": message}}


def _answer(citation=None):
    return {"status": "completed", "output_text": json.dumps({
        "response_kind": "answer", "answer_text": "orchid source text" if citation else "你好，很高興和你聊天。",
        "display_format": "narrative", "citation_ids": [citation] if citation else [],
        "coverage_status": "incomplete" if citation else "not_applicable",
        "coverage_note": "Only bounded evidence is available." if citation else "",
    })}


@contextmanager
def _server(responses, **model_options):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            index = len(received) - 1
            status, response, stream = responses[index] if index < len(responses) else (503, {}, False)
            body = response if isinstance(response, bytes) else json.dumps(response).encode()
            if stream and not isinstance(response, bytes):
                body = b'event: response.completed\ndata: ' + json.dumps({
                    "type": "response.completed", "response": response,
                }).encode() + b'\n\n'
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield uat.CodexResponsesConversationModel(
            base_url=f"http://127.0.0.1:{server.server_address[1]}/v1", api_key="synthetic-key",
            timeout_seconds=3,
            **model_options,
        ), received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _respond(provider, backend, prompt="你好，今天過得如何？"):
    return provider.respond(
        history=(), user_text=prompt, latest_evidence=None, safety_identifier="bounded-stream-recovery",
        evidence_tool=backend, formowl_tool_descriptor=scope._descriptor(),
        authorized_capability_summary={"source_families": ["mail"]},
    )


class ProviderStreamRecoveryTests(unittest.TestCase):
    def test_initial_streaming_is_explicit_and_does_not_retry_the_same_transport(self):
        for status, response in ((200, _answer()), (408, _failure())):
            with self.subTest(status=status):
                backend = Mock()
                with _server([(status, response, status == 200)], stream_initial_requests=True) as (provider, received):
                    outcome = _respond(provider, backend)
                self.assertEqual(len(received), 1)
                self.assertTrue(received[0]["stream"])
                self.assertEqual(outcome.response_kind, "answer" if status == 200 else "clarification")
                backend.assert_not_called()

    def test_recovery_trigger_survives_four_requests_and_public_serialization(self):
        from formowl_mail.human_uat_http import _safe_provider_diagnostic as http_safe
        from formowl_gateway.issue56_uat_runtime import _safe_provider_diagnostic as runtime_safe
        prompt = "Find orchid in mail attachments."
        citation = "sha256:" + "d" * 64
        def function(call_id, family):
            return {"status": "completed", "output": [{
                "type": "function_call", "name": "query_effective_graph_view", "call_id": call_id,
                "arguments": json.dumps(scope._arguments(prompt, [family])),
            }]}
        backend = Mock(return_value={"status": "ok", "citations": [citation],
                                     "coverage": {"status": "incomplete"}})
        with _server([(408, _failure(), False), (200, function("rejected", "attachment_table"), True),
                      (200, function("valid", "mail"), True), (200, _answer(citation), True)]) as (provider, received):
            outcome = _respond(provider, backend, prompt)
        self.assertEqual(len(received), 4)
        self.assertEqual(outcome.citation_ids, (citation,))
        backend.assert_called_once()
        self.assertEqual([x["attempt"] for x in outcome.provider_diagnostic["provider_attempts"]], [2, 3, 4])
        expected = {"attempt": 1, "http_status": 408, "reason_code": "stream_disconnected", "retry_transport": "sse"}
        for projection in (uat.safe_provider_loop_diagnostics, runtime_safe, http_safe):
            public = projection(outcome.provider_diagnostic)
            self.assertEqual(public["pre_mcp_recovery"], expected)
            self.assertNotIn(_DISCONNECTED, json.dumps(public))
            for bad in ({**expected, "attempt": True}, {**expected, "http_status": 401},
                        {**expected, "secret": "must not survive"}):
                invalid = projection({**outcome.provider_diagnostic, "pre_mcp_recovery": bad})
                self.assertNotIn("pre_mcp_recovery", invalid)

    def test_ordinary_408_recovers_once_over_sse_without_mcp_and_retains_failure(self):
        backend = Mock()
        with _server([(408, _failure(), False), (200, _answer(), True)]) as (provider, received):
            outcome = _respond(provider, backend)
        self.assertEqual(outcome.response_kind, "answer")
        backend.assert_not_called()
        self.assertEqual(len(received), 2)
        self.assertEqual(received[1], {**received[0], "stream": True})
        self.assertFalse(received[0]["stream"])
        self.assertEqual([r["tool_choice"] for r in received], ["none", "none"])
        attempts = outcome.provider_diagnostic["provider_attempts"]
        self.assertEqual([r["http_status"] for r in attempts], [408, 200])
        self.assertEqual([r["outcome"] for r in attempts], ["error", "completed"])
        self.assertNotIn(_DISCONNECTED, json.dumps(outcome.provider_diagnostic))

    def test_business_recovery_dispatches_only_the_valid_provider_tool_call(self):
        prompt = "Find orchid in mail attachments."
        citation = "sha256:" + "b" * 64
        function = {"status": "completed", "output": [{
            "type": "function_call", "name": "query_effective_graph_view", "call_id": "synthetic-call",
            "arguments": json.dumps(scope._arguments(prompt, ["mail"])),
        }]}
        backend = Mock(return_value={"status": "ok", "citations": [citation],
                                     "coverage": {"status": "incomplete"}})
        with _server([(408, _failure(), False), (200, function, True),
                      (200, _answer(citation), True)]) as (provider, received):
            outcome = _respond(provider, backend, prompt)
        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(outcome.citation_ids, (citation,))
        backend.assert_called_once()
        self.assertEqual(backend.call_args.args[0].request_contract["source_family_scope"], ["mail"])
        self.assertEqual(received[1], {**received[0], "stream": True})
        self.assertEqual(len(received), 3)
        self.assertEqual(outcome.provider_diagnostic["provider_attempt_count"], 3)

    def test_repeated_disconnect_stops_after_one_recovery_without_mcp(self):
        backend = Mock()
        with _server([(408, _failure(), False)] * 2) as (provider, received):
            outcome = _respond(provider, backend)
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertTrue(outcome.provider_diagnostic)
        self.assertEqual(len(received), 2)
        self.assertEqual(outcome.provider_diagnostic["reason_code"], "provider_pre_mcp_failure")
        backend.assert_not_called()

    def test_unrelated_invalid_requests_and_auth_errors_do_not_retry(self):
        for status, message in ((408, "private unrelated detail"), (400, _DISCONNECTED), (401, _DISCONNECTED)):
            with self.subTest(status=status, message=message):
                backend = Mock()
                with _server([(status, _failure(message), False)]) as (provider, received):
                    outcome = _respond(provider, backend)
                self.assertEqual(outcome.response_kind, "clarification")
                self.assertTrue(outcome.provider_diagnostic)
                self.assertEqual(len(received), 1)
                backend.assert_not_called()

    def test_missing_sse_terminal_is_failure_not_a_tool_call_or_answer(self):
        backend = Mock()
        with _server([(408, _failure(), False), (200, b': heartbeat\n\n', True)]) as (provider, received):
            outcome = _respond(provider, backend)
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertTrue(outcome.provider_diagnostic)
        self.assertEqual(len(received), 2)
        backend.assert_not_called()

    def test_recovery_consumes_existing_provider_attempt_budget(self):
        backend = Mock()
        with patch.object(uat, "_MAX_PROVIDER_REQUESTS_PER_TURN", 1):
            with _server([(408, _failure(), False)]) as (provider, received):
                outcome = _respond(provider, backend)
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertTrue(outcome.provider_diagnostic)
        self.assertEqual(len(received), 1)
        backend.assert_not_called()

    def test_expired_turn_does_not_get_a_new_deadline(self):
        provider = uat.CodexResponsesConversationModel(base_url="https://provider.example.test/v1", api_key="synthetic")
        backend = Mock()
        with patch.object(uat.time, "monotonic", return_value=1000.0) as clock:
            def disconnected(_payload):
                clock.return_value = 1000.0 + uat._MAX_UAT_TURN_SECONDS
                raise uat._UatProviderFailure(reason_code="http_error", http_status=408, response=_failure())
            with patch.object(provider, "_request_response", side_effect=disconnected) as request:
                outcome = _respond(provider, backend)
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertTrue(outcome.provider_diagnostic)
        request.assert_called_once()
        backend.assert_not_called()

    def test_post_mcp_disconnect_keeps_citations_without_transport_retry(self):
        prompt = "Find orchid in mail attachments."
        citation = "sha256:" + "c" * 64
        function = {"status": "completed", "output": [{
            "type": "function_call", "name": "query_effective_graph_view", "call_id": "synthetic-call",
            "arguments": json.dumps(scope._arguments(prompt, ["mail"])),
        }]}
        backend = Mock(return_value={"status": "ok", "citations": [citation],
                                     "coverage": {"status": "incomplete"}})
        with _server([(200, function, False), (408, _failure(), False)]) as (provider, received):
            outcome = _respond(provider, backend, prompt)
        self.assertEqual(len(received), 2)
        self.assertEqual(outcome.citation_ids, (citation,))
        backend.assert_called_once()
        self.assertNotEqual(outcome.provider_diagnostic["reason_code"], "provider_pre_mcp_failure")


if __name__ == "__main__":
    unittest.main()
