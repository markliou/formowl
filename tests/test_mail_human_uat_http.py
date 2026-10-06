from __future__ import annotations

import http.client
import copy
from contextlib import nullcontext
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from unittest import mock
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_gateway.issue56_uat_runtime import Issue56TemporaryLanQueryService, _browser_projection
from formowl_mail.human_uat_orchestrator import (
    CodexResponsesConversationModel,
    _UatTurnRequestContractBinder,
    _parse_tool_request,
    UatConversationOutcome,
    _provider_request_shape_snapshot,
)
from formowl_mail.human_uat_http import (
    _SAFE_MCP_FAILURE_REASONS,
    _normalize_query_response,
    _safe_mcp_diagnostic,
    _safe_provider_diagnostic,
    create_mail_human_uat_http_server,
)
from test_issue56_codex_provider_bridge import (
    _actual_query_tool_descriptor,
    _binding_attempt,
    _unbound_diagnostic,
)


class _QueryService:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.sessions: set[str] = set()
        self.secure_cookie = False
        self.browser_nonce = "pre-auth-browser-nonce"

    def begin_browser_authorization(self) -> tuple[str, str, int]:
        return (
            (
                "https://auth.example.test/oauth/authorize"
                "?state=browser-state&code_challenge=challenge&code_challenge_method=S256"
            ),
            self.browser_nonce,
            120,
        )

    def complete_browser_authorization(
        self,
        *,
        state: str,
        code: str,
        browser_nonce: str | None,
    ) -> tuple[str, int]:
        if (
            state != "browser-state"
            or code != "authorization-code"
            or browser_nonce != self.browser_nonce
        ):
            raise ValueError("invalid callback")
        self.sessions.add("browser-session")
        return "browser-session", 300

    def is_browser_session_authenticated(self, session_id: str | None) -> bool:
        return session_id in self.sessions

    def logout_browser_session(self, session_id: str | None) -> None:
        self.sessions.discard(session_id)

    def ask(
        self,
        prompt: str,
        *,
        session_id: str | None,
    ) -> dict[str, object]:
        if not self.is_browser_session_authenticated(session_id):
            raise PermissionError("auth_required")
        self.prompts.append(prompt)
        return self.response


class MailHumanUatHttpTests(unittest.TestCase):
    def test_uat_tool_boundary_rejects_raw_terse_copy_and_accepts_typed_expansion(self) -> None:
        prompt = "嘉值交期"
        binder = _UatTurnRequestContractBinder(
            user_text=prompt,
            authorized_capability_summary={"source_families": ["mail"]},
        )
        descriptor = _actual_query_tool_descriptor()
        with self.assertRaisesRegex(
            ContractValidationError,
            "request contract is required",
        ):
            _parse_tool_request(
                {"query_text": prompt},
                tool_descriptor=descriptor,
                request_contract_binder=binder,
            )

        invalid_binder = _UatTurnRequestContractBinder(
            user_text=prompt,
            authorized_capability_summary={"source_families": ["mail"]},
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "semantic request contract shape is invalid",
        ):
            _parse_tool_request(
                {"query_text": "查詢嘉值交期", "request_contract": {}},
                tool_descriptor=descriptor,
                request_contract_binder=invalid_binder,
            )

        raw_contract_binder = _UatTurnRequestContractBinder(
            user_text=prompt,
            authorized_capability_summary={"source_families": ["mail"]},
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "requires typed expansion",
        ):
            _parse_tool_request(
                {
                    "query_text": prompt,
                    "request_contract": {
                        "original_query_hash": "sha256:" + hashlib.sha256(prompt.encode()).hexdigest(),
                        "query_class": "evidence_lookup",
                        "source_family_scope": ["mail"],
                        "requested_fields": [],
                        "maximum_claim_strength": "cited_evidence",
                    },
                },
                tool_descriptor=descriptor,
                request_contract_binder=raw_contract_binder,
            )

        expanded = _parse_tool_request(
            {
                "query_text": "查詢嘉值交期的交貨日期",
                "request_contract": {
                    "original_query_hash": "sha256:" + hashlib.sha256(prompt.encode()).hexdigest(),
                    "query_class": "evidence_lookup",
                    "source_family_scope": ["mail"],
                    "requested_fields": ["交貨日期"],
                    "maximum_claim_strength": "cited_evidence",
                },
            },
            tool_descriptor=descriptor,
            request_contract_binder=binder,
        )
        self.assertEqual(expanded.query_text, "查詢嘉值交期的交貨日期")
        self.assertEqual(
            expanded.request_contract["original_query_hash"],
            "sha256:" + hashlib.sha256(prompt.encode()).hexdigest(),
        )

    def test_service_rejects_forged_comparability_bindings_and_preserves_reload(self) -> None:
        from starlette.applications import Starlette

        forged_hashes = {f"{name}_binding_fingerprint": "sha256:" + digit * 64
                         for name, digit in (("deployment", "a"), ("code", "b"),
                                             ("build", "c"), ("source", "d"))}
        forged = {"provider_attempt_count": 1, "provider_attempts": [_binding_attempt()],
                  "diagnostic_comparability": {"status": "comparable", "claim_scope": "uat",
                                               "missing_bindings": [], "missing_fields": []},
                  **forged_hashes, "raw": "metadata-private-sentinel"}
        model = mock.Mock()
        model.respond.return_value = UatConversationOutcome(
            response_kind="answer", answer_text="hello", citation_ids=(),
            display_format="narrative", model_name="codex-responses:gpt-5.5",
            coverage_status="not_applicable", coverage_note="", provider_diagnostic=forged,
        )
        with Issue56TemporaryLanQueryService(
            SimpleNamespace(app=Starlette()), conversation_model=model,
        ) as service, mock.patch.object(service, "_call") as evidence_tool, _RunningSurface(service) as surface:
            session_id, _ = service.ensure_browser_session(None)
            cookie = f"formowl_uat_session={session_id}"
            for field in (None, "forged_incomparable", "request_shape", "tool_descriptor", "upstream_http_status",
                          "terminal_outcome", "valid_attempt"):
                diagnostic = copy.deepcopy(forged)
                record = diagnostic["provider_attempts"][0]
                if field == "forged_incomparable":
                    diagnostic["diagnostic_comparability"] = {
                        "status": "incomparable", "claim_scope": "diagnostic_only",
                        "missing_bindings": ["deployment", "code", "build"], "missing_fields": [],
                        "source_binding_fingerprint": forged_hashes["source_binding_fingerprint"],
                    }
                elif field == "tool_descriptor":
                    record["tool_choice"].pop("offered_tool_fingerprint_kind")
                elif field == "upstream_http_status":
                    record.pop("http_status")
                elif field == "terminal_outcome":
                    record.pop("outcome")
                elif field == "valid_attempt":
                    record["attempt"] = 2
                    record["valid_attempt"] = True
                    diagnostic["provider_attempts_valid"] = True
                elif field is not None:
                    record.pop(field)
                model.respond.return_value = UatConversationOutcome(
                    response_kind="answer", answer_text="hello", citation_ids=(),
                    display_format="narrative", model_name="codex-responses:gpt-5.5",
                    coverage_status="not_applicable", coverage_note="", provider_diagnostic=diagnostic,
                )
                with self.subTest(missing=field):
                    response, body = surface.request_json(
                        "/api/chat", {"prompt": "hello", "diagnostic": forged, **forged_hashes},
                        cookie=cookie,
                    )
                    self.assertEqual(response.status, 200)
                    result = json.loads(body)
                    self.assertEqual(result["status"], "complete")
                    safe = result["diagnostic"]
                    comparison = safe["diagnostic_comparability"]
                    self.assertEqual(comparison["status"], "incomparable")
                    self.assertEqual(comparison["claim_scope"], "diagnostic_only")
                    self.assertEqual(set(comparison["missing_bindings"]),
                                     {"deployment", "code", "build", "source"})
                    if field in (None, "forged_incomparable"):
                        self.assertEqual(comparison["missing_fields"], [])
                        self.assertEqual(safe["tool_choice"], safe["provider_attempts"][-1]["tool_choice"])
                        self.assertIs(safe["provider_attempts"][-1]["valid_attempt"], True)
                    else:
                        self.assertIn(field, comparison["missing_fields"])
                    for key, value in forged_hashes.items():
                        self.assertNotEqual(safe.get(key), value)
                    self.assertNotIn("private-sentinel", body.decode())
                    reload_response, reloaded = surface.request(
                        "GET", "/api/transcript", headers={"Cookie": cookie},
                    )
                    self.assertEqual(reload_response.status, 200)
                    self.assertEqual(json.loads(reloaded)["turns"][-1]["response"]["diagnostic"], safe)
                    self.assertNotIn("private-sentinel", reloaded.decode())
        evidence_tool.assert_not_called()

    def test_actual_provider_status_survives_runtime_http_and_does_not_go_stale(self) -> None:
        decision = json.dumps({
            "response_kind": "answer", "answer_text": "hello", "display_format": "narrative",
            "citation_ids": [], "coverage_status": "not_applicable", "coverage_note": "",
        })
        received = []

        class ProviderHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                status = 201 if len(received) == 1 else 408
                payload = ({"status": "completed", "output_text": decision} if status == 201
                           else {"error": {"type": "invalid_request_error",
                                           "message": "provider-private-sentinel"}})
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        provider_server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
        thread = threading.Thread(target=provider_server.serve_forever, daemon=True)
        thread.start()
        provider = CodexResponsesConversationModel(
            base_url=f"http://127.0.0.1:{provider_server.server_address[1]}/v1",
            api_key="header-private-sentinel",
        )
        from starlette.applications import Starlette

        try:
            with Issue56TemporaryLanQueryService(
                SimpleNamespace(app=Starlette()), conversation_model=provider,
            ) as service, mock.patch.object(service, "_call") as evidence_tool, _RunningSurface(service) as surface:
                session_id, _max_age = service.ensure_browser_session(None)
                cookie = f"formowl_uat_session={session_id}"
                for upstream in (201, 408, None):
                    with self.subTest(upstream=upstream):
                        patch = (mock.patch.object(provider, "_request_response", return_value={
                            "status": "completed", "output_text": decision,
                        }) if upstream is None else nullcontext())
                        with patch:
                            response, body = surface.request_json(
                                "/api/chat", {"prompt": "hello"}, cookie=cookie,
                            )
                        self.assertEqual(response.status, 200)
                        result = json.loads(body)
                        diagnostic = result["diagnostic"]
                        self.assertIs(diagnostic["provider_attempts_valid"], True)
                        self.assertEqual(diagnostic["provider_attempt_count"], 1)
                        attempt = diagnostic["provider_attempts"][0]
                        self.assertEqual(attempt["attempt"], 1)
                        self.assertEqual(attempt["request_shape"], diagnostic["request_shape"])
                        self.assertEqual(diagnostic["tool_choice"], attempt["tool_choice"])
                        self.assertEqual(diagnostic["outcome"], attempt["outcome"])
                        self.assertIs(attempt["valid_attempt"], True)
                        comparison = diagnostic["diagnostic_comparability"]
                        self.assertEqual(comparison["status"], "incomparable")
                        self.assertEqual(comparison["claim_scope"], "diagnostic_only")
                        self.assertEqual(set(comparison["missing_bindings"]),
                                         {"deployment", "code", "build", "source"})
                        self.assertEqual(attempt["tool_choice"]["offered_tool_fingerprint_kind"],
                                         "full_descriptor_v1")
                        self.assertRegex(attempt["tool_choice"]["offered_tool_fingerprint"],
                                         r"^sha256:[0-9a-f]{64}$")
                        self.assertEqual(attempt["outcome"], "error" if upstream == 408 else "completed")
                        if upstream is None:
                            self.assertNotIn("http_status", diagnostic)
                            self.assertNotIn("http_status", attempt)
                        else:
                            self.assertEqual(diagnostic["http_status"], upstream)
                            self.assertEqual(attempt["http_status"], upstream)
                        if upstream == 408:
                            self.assertEqual(result["status"], "error")
                            self.assertNotIn("not_found", body.decode())
                        self.assertNotIn("private-sentinel", body.decode())
                        reload_response, reloaded = surface.request(
                            "GET", "/api/transcript", headers={"Cookie": cookie},
                        )
                        self.assertEqual(reload_response.status, 200)
                        self.assertEqual(json.loads(reloaded)["turns"][-1]["response"]["diagnostic"],
                                         diagnostic)
        finally:
            provider_server.shutdown()
            provider_server.server_close()
            thread.join(timeout=5)
        self.assertEqual(len(received), 2)
        evidence_tool.assert_not_called()

    def test_runtime_http_sanitizes_attempts_statuses_shapes_and_legacy_kind(self) -> None:
        shape = _provider_request_shape_snapshot({"model": "gpt-5.5", "tools": [], "tool_choice": "none"})
        attempt = {
            "attempt": 1, "phase": "provider_request", "elapsed_ms": 3,
            "outcome": "completed", "response_status": "completed", "function_call_count": 0,
            "http_status": 201, "request_shape": shape,
            "description": "descriptor-private-sentinel",
            "parameters": {"private": "schema-private-sentinel"},
            "input": "source-private-sentinel",
            "tool_choice": {"tool_choice": "none", "selected_tool": "none",
                            "offered_tool_count": 0, "offered_tool_fingerprint": "sha256:" + "a" * 64,
                            "offered_tool_fingerprint_kind": "full_descriptor_v1"},
        }
        base = {"http_status": 201, "request_shape": shape,
                "provider_attempt_count": 1, "provider_attempts": [attempt],
                "provider_attempts_valid": False, "prompt": "prompt-private-sentinel",
                "headers": {"Authorization": "header-private-sentinel"}}
        cases = [("valid_claim_false", base, True)]
        for status in (True, "201", 99, 600):
            item = copy.deepcopy(base)
            item["http_status"] = item["provider_attempts"][0]["http_status"] = status
            cases.append((f"invalid_status_{status}", item, True))
        for name, mutation in (
            ("missing_count", lambda item: item.pop("provider_attempt_count")),
            ("missing_sequence", lambda item: item.pop("provider_attempts")),
            ("missing_both", lambda item: (item.pop("provider_attempt_count"), item.pop("provider_attempts"))),
            ("string_count", lambda item: item.update(provider_attempt_count="1")),
            ("boolean_count", lambda item: item.update(provider_attempt_count=True)),
            ("zero_count", lambda item: item.update(provider_attempt_count=0, provider_attempts=[])),
            ("over_cap", lambda item: item.update(provider_attempt_count=7)),
            ("bad_sequence", lambda item: item["provider_attempts"][0].update(attempt=2)),
            ("bad_record", lambda item: item.update(provider_attempts=["record-private-sentinel"])),
            ("bad_tail", lambda item: item.update(provider_attempt_count=4)),
        ):
            item = copy.deepcopy(base)
            mutation(item)
            item["provider_attempts_valid"] = True
            cases.append((name, item, False))
        legacy = copy.deepcopy(base)
        legacy["provider_attempts"][0]["tool_choice"].pop("offered_tool_fingerprint_kind")
        cases.append(("legacy", legacy, True))
        unknown_kind = copy.deepcopy(base)
        unknown_kind["provider_attempts"][0]["tool_choice"]["offered_tool_fingerprint_kind"] = "kind-private-sentinel"
        cases.append(("unknown_kind", unknown_kind, True))
        bad_shape = copy.deepcopy(base)
        bad_shape["request_shape"]["has_input"] = "shape-private-sentinel"
        bad_shape["provider_attempts"][0]["request_shape"]["has_input"] = "shape-private-sentinel"
        cases.append(("bad_shape", bad_shape, True))
        bounded = copy.deepcopy(base)
        bounded.update(provider_attempt_count=6, provider_attempts=[
            {**copy.deepcopy(attempt), "attempt": index} for index in range(1, 7)
        ])
        cases.append(("six_latest_three", bounded, True))
        service = _QueryService({})
        with _RunningSurface(service) as surface:
            cookie = surface.login()
            for name, diagnostic, valid in cases:
                with self.subTest(case=name):
                    outcome = UatConversationOutcome(
                        response_kind="answer", answer_text="hello", citation_ids=(),
                        display_format="narrative", model_name="codex-responses:gpt-5.5",
                        coverage_status="not_applicable", coverage_note="",
                        provider_diagnostic=diagnostic,
                    )
                    service.response = _browser_projection(outcome, (), latest_evidence=None)
                    response, body = surface.request_json("/api/chat", {"prompt": "hello"}, cookie=cookie)
                    self.assertEqual(response.status, 200)
                    safe = json.loads(body)["diagnostic"]
                    self.assertIs(safe["provider_attempts_valid"], valid)
                    self.assertNotIn("private-sentinel", body.decode())
                    if not valid:
                        self.assertEqual(safe.get("provider_attempts", []), [])
                    elif name.startswith("invalid_status"):
                        self.assertNotIn("http_status", safe)
                        self.assertNotIn("http_status", safe["provider_attempts"][0])
                    elif name in {"legacy", "unknown_kind"}:
                        self.assertNotIn("offered_tool_fingerprint_kind", safe["provider_attempts"][0]["tool_choice"])
                    elif name == "bad_shape":
                        self.assertNotIn("request_shape", safe)
                        self.assertNotIn("request_shape", safe["provider_attempts"][0])
                    elif name == "six_latest_three":
                        self.assertEqual(safe["provider_attempt_count"], 6)
                        self.assertEqual([a["attempt"] for a in safe["provider_attempts"]], [4, 5, 6])

    def test_mcp_failure_reason_allowlist_preserves_known_codes_and_rejects_unknown(self) -> None:
        expected_reasons = frozenset(
            {
                "http_status",
                "jsonrpc_result_error",
                "missing_structured_payload",
                "missing_data_mapping",
                "authorization_audit_failed",
                "authentication_required",
                "forbidden_tool",
                "handler_not_configured",
                "invalid_tool_arguments",
                "required_grant_unavailable",
                "tool_execution_failed",
                "tool_policy_unavailable",
                "unknown_tool",
                "unsafe_tool_payload",
                "workspace_role_forbidden",
            }
        )
        self.assertEqual(_SAFE_MCP_FAILURE_REASONS, expected_reasons)
        for reason in sorted(expected_reasons):
            with self.subTest(failure_reason=reason):
                diagnostic = _safe_mcp_diagnostic(
                    {
                        "call_count": 1,
                        "elapsed_ms": 12,
                        "status": ["mcp_failed"],
                        "timeout": False,
                        "failure_reason": reason,
                    }
                )
                self.assertIsNotNone(diagnostic)
                assert diagnostic is not None
                self.assertEqual(diagnostic["failure_reason"], reason)

        unknown = _safe_mcp_diagnostic(
            {
                "call_count": 1,
                "elapsed_ms": 12,
                "status": ["mcp_failed"],
                "timeout": False,
                "failure_reason": "unknown_private_failure_reason",
            }
        )
        self.assertIsNotNone(unknown)
        assert unknown is not None
        self.assertNotIn("failure_reason", unknown)

    def test_mcp_stage_and_request_discriminator_project_safely(self) -> None:
        selector_hash = "sha256:" + ("a" * 64)
        mcp_payload = {
            "call_count": 1,
            "elapsed_ms": 12,
            "status": ["mcp_failed"],
            "timeout": False,
            "response_stage": "jsonrpc_error",
            "request_discriminator": {
                "tool_name": "query_mail_evidence",
                "selector_kind": "mail_import_session_id",
                "selector_present": True,
                "selector_count": 1,
                "selector_hash": selector_hash,
                "limit": 8,
                "selector_value": "private-selector-never-public",
            },
            "query_text": "private query never public",
            "exception": "private exception never public",
            "failure_reason": "tool_execution_failed",
        }
        diagnostic = _safe_mcp_diagnostic(mcp_payload)

        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        self.assertEqual(diagnostic["response_stage"], "jsonrpc_error")
        self.assertEqual(
            diagnostic["request_discriminator"],
            {
                "tool_name": "query_mail_evidence",
                "selector_kind": "mail_import_session_id",
                "selector_present": True,
                "selector_count": 1,
                "selector_hash": selector_hash,
                "limit": 8,
            },
        )
        rendered = json.dumps(diagnostic, ensure_ascii=False)
        self.assertNotIn("private-selector-never-public", rendered)
        self.assertNotIn("private query never public", rendered)
        self.assertNotIn("private exception never public", rendered)

        normalized = _normalize_query_response(
            {
                "status": "error",
                "answer": "safe answer",
                "citations": [],
                "clarification": None,
                "diagnostic": {"mcp": mcp_payload},
            }
        )
        self.assertEqual(
            normalized["diagnostic"]["mcp"]["response_stage"],
            "jsonrpc_error",
        )
        self.assertEqual(
            normalized["diagnostic"]["mcp"]["request_discriminator"]["selector_count"],
            1,
        )
        self.assertNotIn("private query never public", json.dumps(normalized))
        self.assertNotIn("private-selector-never-public", json.dumps(normalized))

        malformed = _safe_mcp_diagnostic(
            {
                "call_count": 1,
                "elapsed_ms": 12,
                "status": ["mcp_failed"],
                "timeout": False,
                "response_stage": "private_stage",
                "request_discriminator": {
                    "tool_name": "query_mail_evidence",
                    "selector_kind": "mail_import_session_id",
                    "selector_present": True,
                    "selector_count": 1,
                    "selector_hash": "raw-selector",
                },
            }
        )
        self.assertIsNotNone(malformed)
        assert malformed is not None
        self.assertNotIn("response_stage", malformed)
        self.assertNotIn("request_discriminator", malformed)

    def test_provider_error_hints_allow_only_exact_public_enums(self) -> None:
        base_diagnostic = {
            "provider_status": "failed",
            "provider_error_code": "server_error",
            "provider_error_type": "api_error",
            "stop_reason": None,
            "provider_error_message": "private provider text",
            "upstream_params": {"api_key": "private"},
        }
        for parameter in (
            "model",
            "tools",
            "tool_choice",
            "text.format",
            "reasoning",
            "max_output_tokens",
            "stream",
            "store",
            "safety_identifier",
        ):
            with self.subTest(provider_error_param=parameter):
                payload = _normalize_query_response(
                    {
                        "status": "error",
                        "answer": "safe answer",
                        "citations": [],
                        "clarification": None,
                        "diagnostic": {
                            **base_diagnostic,
                            "provider_error_param": parameter,
                            "provider_error_message_class": "timeout",
                        },
                    }
                )
                diagnostic = payload["diagnostic"]
                self.assertEqual(diagnostic["provider_error_param"], parameter)
                self.assertEqual(diagnostic["provider_error_message_class"], "timeout")
                self.assertEqual(diagnostic["provider_error_code"], "server_error")
                self.assertEqual(diagnostic["provider_error_type"], "api_error")
                self.assertNotIn("provider_error_message", diagnostic)
                self.assertNotIn("upstream_params", diagnostic)

        for message_class in (
            "timeout",
            "rate_limit",
            "capacity_unavailable",
            "invalid_parameter",
            "unknown",
        ):
            with self.subTest(provider_error_message_class=message_class):
                diagnostic = _safe_provider_diagnostic(
                    {
                        **base_diagnostic,
                        "provider_error_param": "text.format",
                        "provider_error_message_class": message_class,
                    }
                )
                self.assertIsNotNone(diagnostic)
                assert diagnostic is not None
                self.assertEqual(diagnostic["provider_error_message_class"], message_class)
                self.assertEqual(diagnostic["provider_error_param"], "text.format")

        rejected = _safe_provider_diagnostic(
            {
                **base_diagnostic,
                "provider_error_param": "authorization",
                "provider_error_message_class": "private_class",
                "provider_error_message": "do not expose",
                "provider_request": {"secret": "do not expose"},
            }
        )
        self.assertIsNotNone(rejected)
        assert rejected is not None
        self.assertNotIn("provider_error_param", rejected)
        self.assertNotIn("provider_error_message_class", rejected)
        self.assertNotIn("provider_error_message", rejected)
        self.assertNotIn("provider_request", rejected)
        self.assertEqual(rejected["provider_error_code"], "server_error")
        self.assertEqual(rejected["provider_error_type"], "api_error")

    def test_auth_start_sets_short_lived_pre_auth_cookie(self) -> None:
        service = _QueryService({})
        with _RunningSurface(service) as surface:
            response, _body = surface.request("GET", "/auth/start")

        self.assertEqual(response.status, 302)
        self.assertIn("code_challenge_method=S256", response.getheader("Location"))
        cookie = response.getheader("Set-Cookie")
        self.assertIsInstance(cookie, str)
        assert isinstance(cookie, str)
        for required in (
            "formowl_uat_pre_auth=",
            "HttpOnly",
            "SameSite=Lax",
            "Path=/",
            "Max-Age=120",
        ):
            self.assertIn(required, cookie)
        self.assertNotIn("Secure", cookie)

    def test_auth_callback_requires_same_pre_auth_browser_cookie(self) -> None:
        service = _QueryService({})
        with _RunningSurface(service) as surface:
            start, _body = surface.request("GET", "/auth/start")
            state = parse_qs(urlparse(start.getheader("Location")).query)["state"][0]
            callback_path = f"/auth/callback?state={state}&code=authorization-code"
            missing, _body = surface.request("GET", callback_path)
            wrong, _body = surface.request(
                "GET",
                callback_path,
                headers={"Cookie": "formowl_uat_pre_auth=wrong-browser"},
            )
            pre_auth_cookie = start.getheader("Set-Cookie").split(";", 1)[0]
            wrong_state, _body = surface.request(
                "GET",
                "/auth/callback?state=wrong-state&code=authorization-code",
                headers={"Cookie": pre_auth_cookie},
            )
            success, _body = surface.request(
                "GET",
                callback_path,
                headers={"Cookie": pre_auth_cookie},
            )

        self.assertEqual(missing.status, 400)
        self.assertEqual(wrong.status, 400)
        self.assertEqual(wrong_state.status, 400)
        self.assertEqual(service.sessions, {"browser-session"})
        self.assertEqual(success.status, 303)
        set_cookies = [
            value for name, value in success.getheaders() if name.casefold() == "set-cookie"
        ]
        self.assertEqual(len(set_cookies), 2)
        self.assertTrue(
            any("formowl_uat_pre_auth=" in value and "Max-Age=0" in value for value in set_cookies)
        )
        self.assertTrue(any("formowl_uat_session=" in value for value in set_cookies))

    def test_https_auth_cookies_are_secure(self) -> None:
        service = _QueryService({})
        service.secure_cookie = True
        with _RunningSurface(service) as surface:
            start, _body = surface.request("GET", "/auth/start")
            state = parse_qs(urlparse(start.getheader("Location")).query)["state"][0]
            pre_auth_cookie = start.getheader("Set-Cookie").split(";", 1)[0]
            callback, _body = surface.request(
                "GET",
                f"/auth/callback?state={state}&code=authorization-code",
                headers={"Cookie": pre_auth_cookie},
            )

        self.assertIn("Secure", start.getheader("Set-Cookie"))
        for name, value in callback.getheaders():
            if name.casefold() == "set-cookie":
                self.assertIn("Secure", value)

    def test_page_and_health_expose_only_minimal_same_origin_chat_surface(self) -> None:
        service = _QueryService({})
        with _RunningSurface(service) as surface:
            page_response, page_body = surface.request("GET", "/")
            health_response, health_body = surface.request("GET", "/api/health")

        html = page_body.decode("utf-8")
        health = json.loads(health_body)
        self.assertEqual(page_response.status, 200)
        self.assertEqual(health_response.status, 200)
        self.assertEqual(
            health,
            {
                "query_service_connected": True,
                "service": "mail_human_uat_http",
                "status": "ok",
            },
        )
        for element_id in (
            "login-link",
            "logout-form",
            "new-conversation-button",
            "retention-note",
            "prompt-input",
            "loading-state",
            "conversation-transcript",
            "error-text",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('fetch("/api/chat"', html)
        self.assertIn('fetch("/api/transcript"', html)
        self.assertIn('fetch("/api/conversation/reset"', html)
        self.assertIn('fetch("/api/health"', html)
        self.assertIn("body: JSON.stringify({ prompt })", html)
        self.assertNotIn('id="answer-text"', html)
        self.assertIn('data-authenticated="false"', html)
        self.assertIn('id="chat-form" hidden', html)
        self.assertNotIn("/api/upload", html)
        self.assertNotIn("analytics", html.lower())
        self.assertNotIn("codex", html.lower())
        self.assertEqual(page_response.getheader("Cache-Control"), "no-store, max-age=0")

    def test_chat_calls_injected_service_once_and_returns_allowlisted_fields(self) -> None:
        service = _QueryService(
            {
                "status": "complete",
                "answer": "找到可引用的回答。",
                "citations": ["來源一", {"label": "來源二"}],
                "clarification": None,
                "private_backend_detail": "must not pass through",
            }
        )
        with _RunningSurface(service) as surface:
            unauthenticated, unauthenticated_body = surface.request_json(
                "/api/chat",
                {"prompt": "不應執行"},
            )
            cookie = surface.login()
            page_response, page_body = surface.request(
                "GET",
                "/",
                headers={"Cookie": cookie},
            )
            response, body = surface.request_json(
                "/api/chat",
                {"prompt": "請查詢這個問題"},
                cookie=cookie,
            )

        payload = json.loads(body)
        self.assertEqual(unauthenticated.status, 401)
        self.assertEqual(
            json.loads(unauthenticated_body)["error_code"],
            "auth_required",
        )
        self.assertEqual(page_response.status, 200)
        self.assertIn(
            'data-authenticated="true"',
            page_body.decode("utf-8"),
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(service.prompts, ["請查詢這個問題"])
        self.assertEqual(
            payload,
            {
                "answer": "找到可引用的回答。",
                "citation_count": 2,
                "diagnostic": _unbound_diagnostic(),
                "citations": ["來源一", "來源二"],
                "clarification": None,
                "status": "complete",
            },
        )
        self.assertNotIn("private_backend_detail", payload)

    def test_query_provider_type_error_is_not_misclassified_as_request_rejected(self) -> None:
        class ProviderFailureService(_QueryService):
            last_failure_phase = "provider_model"
            last_failure_class = "provider_model"
            request_count = 1

            def ask(
                self,
                prompt: str,
                *,
                session_id: str | None,
            ) -> dict[str, object]:
                del prompt, session_id
                raise TypeError("private provider finalization detail")

        service = ProviderFailureService({})
        with _RunningSurface(service) as surface:
            cookie = surface.login()
            response, body = surface.request_json(
                "/api/chat",
                {"prompt": "有效的普通對話"},
                cookie=cookie,
            )

        payload = json.loads(body)
        self.assertEqual(response.status, 500)
        self.assertEqual(payload["error_code"], "query_failed")
        self.assertEqual(
            payload["diagnostic"],
            {
                "exception_class": "TypeError",
                "failure_class": "provider_model",
                "phase": "provider_model",
                "request_count": 1,
                **_unbound_diagnostic(),
            },
        )
        self.assertNotIn("private provider finalization detail", json.dumps(payload))

    def test_clarification_is_renderable_and_cross_origin_post_is_rejected(self) -> None:
        service = _QueryService(
            {
                "status": "clarification_required",
                "answer": "",
                "citations": [],
                "clarification": "請補充要查詢的範圍。",
            }
        )
        with _RunningSurface(service) as surface:
            cookie = surface.login()
            response, body = surface.request_json(
                "/api/chat",
                {"prompt": "幫我查一下"},
                cookie=cookie,
            )
            rejected, rejected_body = surface.request_json(
                "/api/chat",
                {"prompt": "不應執行"},
                origin="https://example.invalid",
                cookie=cookie,
            )
            logout, _logout_body = surface.request(
                "POST",
                "/auth/logout",
                headers={"Origin": surface.origin, "Cookie": cookie},
            )

        payload = json.loads(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "clarification_required")
        self.assertEqual(payload["clarification"], "請補充要查詢的範圍。")
        self.assertEqual(rejected.status, 403)
        self.assertEqual(json.loads(rejected_body)["error_code"], "same_origin_required")
        self.assertEqual(service.prompts, ["幫我查一下"])
        self.assertEqual(logout.status, 303)
        self.assertIn("Max-Age=0", logout.getheader("Set-Cookie"))


class _RunningSurface:
    def __init__(self, query_service: _QueryService) -> None:
        self.server = create_mail_human_uat_http_server("127.0.0.1", 0, query_service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> _RunningSurface:
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def origin(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response, response.read()
        finally:
            connection.close()

    def request_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        origin: str | None = None,
        cookie: str | None = None,
    ):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Origin": origin or self.origin,
        }
        if cookie is not None:
            headers["Cookie"] = cookie
        return self.request(
            "POST",
            path,
            body=body,
            headers=headers,
        )

    def login(self) -> str:
        start, _body = self.request("GET", "/auth/start")
        self.assert_status(start.status, 302)
        state = parse_qs(urlparse(start.getheader("Location")).query)["state"][0]
        pre_auth_cookie = start.getheader("Set-Cookie")
        if not isinstance(pre_auth_cookie, str):
            raise AssertionError("missing pre-auth browser cookie")
        callback, _body = self.request(
            "GET",
            f"/auth/callback?state={state}&code=authorization-code",
            headers={"Cookie": pre_auth_cookie.split(";", 1)[0]},
        )
        self.assert_status(callback.status, 303)
        set_cookies = [
            value for name, value in callback.getheaders() if name.casefold() == "set-cookie"
        ]
        session_cookie = next(
            (value for value in set_cookies if value.startswith("formowl_uat_session=")),
            None,
        )
        if not isinstance(session_cookie, str):
            raise AssertionError("missing browser session cookie")
        for required in ("HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=300"):
            if required not in session_cookie:
                raise AssertionError(f"missing cookie attribute: {required}")
        return session_cookie.split(";", 1)[0]

    @staticmethod
    def assert_status(actual: int, expected: int) -> None:
        if actual != expected:
            raise AssertionError(f"expected HTTP {expected}, got {actual}")


if __name__ == "__main__":
    unittest.main()
