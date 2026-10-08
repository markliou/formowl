from __future__ import annotations

import json
import hashlib
from types import SimpleNamespace
import time
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_gateway.issue56_diagnostic import (
    _SYNTHETIC_BEARER,
    Issue56DiagnosticConfig,
    Issue56DiagnosticOAuthBridge,
    Issue56DiagnosticState,
    mcp_headers,
)
from formowl_gateway.issue56_uat_runtime import (
    Issue56TemporaryLanQueryService,
    _mcp_query_request,
    _safe_mcp_call_diagnostic,
)
from formowl_gateway.remote import create_connected_mcp_application
from formowl_gateway.semantic import SemanticMcpGateway
from formowl_gateway.issue56_uat_runtime import _run_gpt_query_agent
from formowl_mail.human_uat_http import _safe_query_failure_diagnostic
from formowl_mail.human_uat_orchestrator import (
    UatConversationOutcome,
    UatEvidenceToolRequest,
)


class _ForgedToolCallModel:
    model_name = "synthetic-forged-provider"

    def __init__(self, request: UatEvidenceToolRequest) -> None:
        self.request = request

    def respond(
        self,
        *,
        history,
        user_text,
        latest_evidence,
        safety_identifier,
        evidence_tool,
        formowl_tool_descriptor=None,
        authorized_capability_summary=None,
    ):
        del (
            history,
            user_text,
            latest_evidence,
            safety_identifier,
            formowl_tool_descriptor,
            authorized_capability_summary,
        )
        evidence_tool(self.request)
        raise AssertionError("the forged tool call should have been rejected")


class _PriorEvidenceModel:
    model_name = "synthetic-prior-evidence-provider"

    def respond(
        self,
        *,
        history,
        user_text,
        latest_evidence,
        safety_identifier,
        evidence_tool,
        formowl_tool_descriptor=None,
        authorized_capability_summary=None,
    ):
        del (
            history,
            user_text,
            safety_identifier,
            evidence_tool,
            formowl_tool_descriptor,
            authorized_capability_summary,
        )
        citation_id = latest_evidence["citations"][0]
        return UatConversationOutcome(
            response_kind="render_prior_evidence",
            answer_text="已將既有引用整理為摘要。",
            display_format="list",
            model_name=self.model_name,
            citation_ids=(citation_id,),
            coverage_status="incomplete",
            coverage_note="既有來源涵蓋範圍仍不完整。",
        )


class _MailEvidenceModel:
    model_name = "synthetic-mail-provider"

    def __init__(self, request: UatEvidenceToolRequest) -> None:
        self.request = request

    def respond(
        self,
        *,
        history,
        user_text,
        latest_evidence,
        safety_identifier,
        evidence_tool,
        formowl_tool_descriptor=None,
        authorized_capability_summary=None,
    ):
        del (
            history,
            user_text,
            latest_evidence,
            safety_identifier,
            formowl_tool_descriptor,
            authorized_capability_summary,
        )
        evidence = evidence_tool(self.request)
        citation_id = evidence["citations"][0]
        return UatConversationOutcome(
            response_kind="answer",
            answer_text="找到一封相關信件。",
            display_format="narrative",
            model_name=self.model_name,
            citation_ids=(citation_id,),
            coverage_status="complete",
            tool_requests=(self.request,),
            tool_results=(evidence,),
        )


class Issue56UatMcpGateTests(unittest.TestCase):
    def test_actual_composed_app_keeps_safe_mail_discriminator_in_nested_call(self) -> None:
        def mail_handler(_arguments: dict[str, object]) -> dict[str, object]:
            return {"status": "ok", "citations": []}

        mail_handler.authorized_capability_summary = {"source_families": ["mail"]}
        config = Issue56DiagnosticConfig()
        google_client = object()
        application = create_connected_mcp_application(
            bridge=Issue56DiagnosticOAuthBridge(
                config=config,
                google_client=google_client,
                state=Issue56DiagnosticState(),
            ),
            config=config,
            google_client=google_client,
            semantic_gateway=SemanticMcpGateway(mail_evidence_handler=mail_handler),
            oauth_route_provider=lambda **_kwargs: (),
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        service = Issue56TemporaryLanQueryService(
            application,
            conversation_model=mock.Mock(),
        )
        selector = "mailimport:" + ("a" * 64)
        request = UatEvidenceToolRequest(
            query_text="authorized mail lookup",
            tool_name="query_mail_evidence",
            mail_import_session_id=selector,
            limit=5,
        )
        try:
            main_response = service._client.post(
                "/mcp",
                headers=mcp_headers(bearer=_SYNTHETIC_BEARER),
                json=_mcp_query_request(request),
            )
            self.assertEqual(main_response.status_code, 200)

            traces: list[dict[str, object]] = []
            service._active_turn_deadline = time.monotonic() + 5.0
            nested_result = service._call(request, trace_sink=traces)
        finally:
            service.close()

        self.assertEqual(nested_result["status"], "ok")
        self.assertEqual(len(traces), 1)
        diagnostic = _safe_mcp_call_diagnostic(traces)
        discriminator = diagnostic["request_discriminator"]
        self.assertEqual(discriminator["tool_name"], "query_mail_evidence")
        self.assertEqual(discriminator["selector_kind"], "mail_import_session_id")
        self.assertTrue(discriminator["selector_present"])
        self.assertEqual(discriminator["selector_count"], 1)
        self.assertEqual(
            discriminator["selector_hash"],
            "sha256:" + hashlib.sha256(selector.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(discriminator["limit"], 5)
        self.assertEqual(diagnostic["response_stage"], "payload_validated")
        self.assertNotIn(selector, json.dumps(diagnostic, ensure_ascii=False))

    def test_nested_mcp_error_preserves_owner_class_privately_and_projects_safe_diagnostic(
        self,
    ) -> None:
        selector = "mailimport:" + ("b" * 64)
        query_text = "private-query-marker"
        owner = {
            "module": "formowl_mail.query",
            "symbol": "build_revision_owned_mail_evidence_query_handler.locals.handler",
            "line": 1070,
        }
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "jsonrpc": "2.0",
                "id": "call-1",
                "result": {
                    "isError": True,
                    "structuredContent": {
                        "result_type": "semantic_gateway_error",
                        "status": "error",
                        "data": {
                            "error_code": "tool_execution_failed",
                        },
                    },
                    "_meta": {
                        "formowl_diagnostic": {
                            "response_stage": "exception",
                            "exception_class": "ContractValidationError",
                            "exception_owner": owner,
                            "query": query_text,
                            "selector": selector,
                            "exception_message": "/private/raw/path",
                        },
                    },
                },
            },
        )
        service = object.__new__(Issue56TemporaryLanQueryService)
        service._client = SimpleNamespace(post=mock.Mock(return_value=response))
        service._active_turn_deadline = time.monotonic() + 60
        service.last_failure_phase = "provider_model"
        service.request_count = 0
        service._record_raw_uat_interactions = False
        request = UatEvidenceToolRequest(
            query_text=query_text,
            tool_name="query_mail_evidence",
            mail_import_session_id=selector,
            limit=100,
        )
        traces: list[dict[str, object]] = []

        result = service._call(request, trace_sink=traces)

        self.assertEqual(result, {"status": "mcp_failed", "citations": []})
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["response_stage"], "exception")
        self.assertEqual(traces[0]["exception_class"], "ContractValidationError")
        self.assertEqual(traces[0]["failure_reason"], "tool_execution_failed")
        self.assertEqual(traces[0]["exception_owner"], owner)
        self.assertEqual(
            service._last_private_mcp_owner_trace,
            {
                "exception_owner": owner,
                "exception_class": "ContractValidationError",
                "response_stage": "exception",
                "failure_reason": "tool_execution_failed",
                "request_discriminator": {
                    "tool_name": "query_mail_evidence",
                    "selector_kind": "mail_import_session_id",
                    "selector_present": True,
                    "selector_count": 1,
                    "selector_hash": (
                        "sha256:" + hashlib.sha256(selector.encode("utf-8")).hexdigest()
                    ),
                    "limit": 100,
                    "query_text_char_count": len(query_text),
                },
                "request_shape": {
                    "request_contract_present": False,
                    "table_query_present": False,
                    "exact_field_present": False,
                    "exact_inventory_kind_present": False,
                    "page_size_present": False,
                    "cursor_present": False,
                },
            },
        )

        public_diagnostic = _safe_mcp_call_diagnostic(traces)
        self.assertEqual(public_diagnostic["response_stage"], "exception")
        self.assertEqual(public_diagnostic["exception_class"], "ContractValidationError")
        self.assertEqual(public_diagnostic["failure_reason"], "tool_execution_failed")
        self.assertNotIn("exception_owner", public_diagnostic)
        rendered = json.dumps(public_diagnostic, ensure_ascii=False)
        for private in (query_text, selector, "/private/raw/path", "formowl_mail.query"):
            self.assertNotIn(private, rendered)

    def test_ordinary_prompt_rejects_forged_tool_call_without_mcp(self) -> None:
        request = UatEvidenceToolRequest(query_text="forged internal query")
        model = _ForgedToolCallModel(request)
        mcp_call = mock.Mock(return_value={"status": "complete", "citations": []})

        with self.assertRaisesRegex(
            RuntimeError,
            r"^uat_mcp_not_authorized_for_conversation$",
        ):
            _run_gpt_query_agent(
                model,
                prompt="你好，今天過得如何？",
                history=(),
                latest_evidence=None,
                safety_identifier="ordinary-chat",
                formowl_tool_descriptor=None,
                authorized_capability_summary=None,
                mcp_call=mcp_call,
            )

        mcp_call.assert_not_called()

    def test_varied_natural_greetings_skip_mcp(self) -> None:
        request = UatEvidenceToolRequest(query_text="forged internal query")
        model = _ForgedToolCallModel(request)
        mcp_call = mock.Mock(return_value={"status": "complete", "citations": []})

        for prompt in (
            "你好，今天天氣真不錯。",
            "Hey, hope your morning is going well.",
            "您好，最近還好嗎？",
            "Hi, explain project management.",
            "你好，幫我找回信心。",
        ):
            with self.subTest(prompt=prompt):
                with self.assertRaisesRegex(
                    RuntimeError,
                    r"^uat_mcp_not_authorized_for_conversation$",
                ):
                    _run_gpt_query_agent(
                        model,
                        prompt=prompt,
                        history=(),
                        latest_evidence=None,
                        safety_identifier="ordinary-natural-greeting",
                        formowl_tool_descriptor=None,
                        authorized_capability_summary=None,
                        mcp_call=mcp_call,
                    )

        mcp_call.assert_not_called()

    def test_greeting_prefix_does_not_override_mail_request(self) -> None:
        base_request = UatEvidenceToolRequest(
            query_text="找我的信件",
            tool_name="query_mail_evidence",
            mail_evidence_bundle_id="bundle-1",
            limit=1,
        )
        citation_id = "sha256:greeting-mail-citation"
        mcp_call = mock.Mock(
            return_value={
                "status": "complete",
                "citations": [citation_id],
                "evidence_snippets": [
                    {"snippet": "bounded mail evidence", "citation_id": citation_id}
                ],
            }
        )

        for prompt, required_terms in (
            ("Hi, search my inbox for the latest invoice.", ("invoice",)),
            ("你好，請幫我找劉一帆寄來的信。", ("劉一帆",)),
            ("您好，整理上週的來信。", ("上週",)),
            ("嗨，查一下昨天的寄出信。", ("昨天",)),
            ("Hello, 幫我看看客戶寄給我的那封信。", ("客戶",)),
        ):
            with self.subTest(prompt=prompt):
                mcp_call.reset_mock()
                request = UatEvidenceToolRequest(
                    query_text=base_request.query_text,
                    tool_name=base_request.tool_name,
                    mail_evidence_bundle_id=base_request.mail_evidence_bundle_id,
                    required_terms=required_terms,
                    limit=base_request.limit,
                )
                result, responses, _outcome = _run_gpt_query_agent(
                    _MailEvidenceModel(request),
                    prompt=prompt,
                    history=(),
                    latest_evidence=None,
                    safety_identifier="greeting-mail-chat",
                    formowl_tool_descriptor=None,
                    authorized_capability_summary=None,
                    mcp_call=mcp_call,
                )

                mcp_call.assert_called_once_with(request)
                self.assertEqual(len(responses), 1)
                self.assertEqual(result["citations"], [citation_id])

    def test_greeting_prefix_does_not_override_nonmail_lookup(self) -> None:
        for prompt in (
            "Hi, find the project document",
            "你好，查詢專案資料",
        ):
            with self.subTest(prompt=prompt):
                request = UatEvidenceToolRequest(query_text=prompt)
                citation_id = "sha256:document-citation"
                mcp_call = mock.Mock(
                    return_value={"status": "complete", "citations": [citation_id]}
                )

                result, responses, _outcome = _run_gpt_query_agent(
                    _MailEvidenceModel(request),
                    prompt=prompt,
                    history=(),
                    latest_evidence=None,
                    safety_identifier="greeting-document-chat",
                    formowl_tool_descriptor=None,
                    authorized_capability_summary={
                        "source_families": ["document_text"],
                    },
                    mcp_call=mcp_call,
                )

                mcp_call.assert_called_once()
                bound_request = mcp_call.call_args.args[0]
                self.assertEqual(bound_request.tool_name, "query_effective_graph_view")
                self.assertEqual(bound_request.query_text, prompt)
                self.assertIsNotNone(bound_request.request_contract)
                self.assertEqual(len(responses), 1)
                self.assertEqual(result["citations"], [citation_id])

    def test_mail_prompt_still_calls_mcp_and_preserves_citation(self) -> None:
        request = UatEvidenceToolRequest(
            query_text="整理劉一帆信件",
            tool_name="query_mail_evidence",
            mail_evidence_bundle_id="bundle-1",
            required_terms=("劉一帆",),
            limit=1,
        )
        model = _MailEvidenceModel(request)
        citation_id = "sha256:mail-citation"
        mcp_call = mock.Mock(
            return_value={
                "status": "complete",
                "citations": [citation_id],
                "evidence_snippets": [
                    {"snippet": "bounded mail evidence", "citation_id": citation_id}
                ],
            }
        )

        result, responses, _outcome = _run_gpt_query_agent(
            model,
            prompt="整理劉一帆信件",
            history=(),
            latest_evidence=None,
            safety_identifier="mail-chat",
            formowl_tool_descriptor=None,
            authorized_capability_summary=None,
            mcp_call=mcp_call,
        )

        mcp_call.assert_called_once_with(request)
        self.assertEqual(len(responses), 1)
        self.assertEqual(result["citations"], [citation_id])

    def test_prior_cited_reformat_skips_mcp_and_keeps_citation(self) -> None:
        citation_id = "sha256:prior-citation"
        latest_evidence = {
            "status": "partial",
            "citations": [citation_id],
            "results": [{"answer": "prior governed answer"}],
        }
        mcp_call = mock.Mock()

        result, responses, _outcome = _run_gpt_query_agent(
            _PriorEvidenceModel(),
            prompt="整理上面的引用證據",
            history=(),
            latest_evidence=latest_evidence,
            safety_identifier="prior-reformat",
            formowl_tool_descriptor=None,
            authorized_capability_summary=None,
            mcp_call=mcp_call,
        )

        mcp_call.assert_not_called()
        self.assertEqual(responses, ())
        self.assertEqual(result["citations"], [citation_id])

    def test_gate_passes_prior_evidence_flags_and_public_error_is_safe(self) -> None:
        request = UatEvidenceToolRequest(query_text="forged internal query")
        model = _ForgedToolCallModel(request)
        mcp_call = mock.Mock()

        with mock.patch(
            "formowl_gateway.issue56_uat_runtime.requires_workspace_evidence",
            return_value=False,
        ) as requires_workspace_evidence:
            with self.assertRaisesRegex(
                RuntimeError,
                r"^uat_mcp_not_authorized_for_conversation$",
            ) as raised:
                _run_gpt_query_agent(
                    model,
                    prompt="你好",
                    history=(),
                    latest_evidence={
                        "citations": ["sha256:prior-citation"],
                        "internal_backend_detail": "private backend detail",
                    },
                    safety_identifier="ordinary-chat-with-prior",
                    formowl_tool_descriptor=None,
                    authorized_capability_summary=None,
                    mcp_call=mcp_call,
                )

        requires_workspace_evidence.assert_called_once_with(
            "你好",
            query_class="evidence_lookup",
            prior_evidence_citeable=True,
            prior_evidence_present=True,
        )
        public_diagnostic = _safe_query_failure_diagnostic(
            SimpleNamespace(
                last_failure_phase="provider_model",
                last_failure_class="provider_model",
                request_count=0,
            ),
            raised.exception,
        )
        public_payload = json.dumps(public_diagnostic, ensure_ascii=False)
        self.assertNotIn("private backend detail", public_payload)
        self.assertNotIn("internal_backend_detail", public_payload)
        self.assertNotIn("mcp_call", public_payload)
        mcp_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
