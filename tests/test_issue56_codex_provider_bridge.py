from __future__ import annotations

import copy
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import tomllib
from types import SimpleNamespace
import unittest
from unittest import mock

import _paths  # noqa: F401
import scripts.mail_human_uat_codex_engine as codex_engine
from formowl_contract import ContractValidationError, assert_no_public_raw_references, sha256_json
import formowl_gateway.issue56_uat_runtime as uat_runtime
import formowl_mail.human_uat_orchestrator as orchestrator
from formowl_gateway.issue56_uat_runtime import (
    Issue56TemporaryLanQueryService,
    _query_agent_runtime_context,
    _browser_projection,
    _safe_provider_diagnostic as runtime_project,
    _with_mcp_diagnostic,
)
from formowl_gateway.remote import build_remote_tool_descriptors
from formowl_mail.human_uat_orchestrator import (
    CodexAppServerConversationModel,
    CodexAppServerStdioTransport,
    CodexAppServerThread,
    CodexAppServerTurn,
    CodexDynamicToolInvocation,
    _CodexAppServerProviderFailure,
    CodexResponsesConversationModel,
    UatConversationOutcome,
    UatEvidenceToolRequest,
    _UatTurnRequestContractBinder,
    _parse_tool_request,
    _required_term_source_family,
    _CODEX_DISABLED_FEATURES,
    _assert_hardened_codex_runtime,
    build_hardened_codex_app_server_command,
    build_codex_runtime_environment,
    compact_evidence_for_model,
    evidence_citation_ids,
    safe_provider_loop_diagnostics,
    prepare_codex_runtime_state_for_custom_provider,
    prepare_codex_runtime_state_with_device_auth,
    validate_codex_runtime_state,
    _provider_diagnostic,
)
from formowl_mail.semantic_plan import requires_workspace_evidence


def _decision(
    *,
    response_kind: str = "answer",
    answer_text: str = "bounded answer",
    citations: tuple[str, ...] = (),
    coverage_status: str = "not_applicable",
    coverage_note: str = "",
) -> str:
    return json.dumps(
        {
            "response_kind": response_kind,
            "answer_text": answer_text,
            "display_format": "narrative",
            "citation_ids": list(citations),
            "coverage_status": coverage_status,
            "coverage_note": coverage_note,
        },
        separators=(",", ":"),
    )


def _actual_query_tool_descriptor():
    return next(
        tool.model_dump(by_alias=True, exclude_none=True)
        for tool in build_remote_tool_descriptors(
            required_scope="formowl.use",
            enabled_tool_names={"whoami", "query_effective_graph_view"},
        )
        if tool.name == "query_effective_graph_view"
    )


def _actual_mail_tool_descriptor():
    return next(
        tool.model_dump(by_alias=True, exclude_none=True)
        for tool in build_remote_tool_descriptors(
            required_scope="formowl.use",
            enabled_tool_names={"whoami", "query_mail_evidence"},
        )
        if tool.name == "query_mail_evidence"
    )


def _binding_attempt(index=1, *, http_status=201, tool_choice="auto"):
    tools = [{"type": "function", "name": "query_mail_evidence",
              "description": "descriptor-private-sentinel",
              "parameters": {"type": "object", "properties": {}}, "strict": True}]
    shape = orchestrator._provider_request_shape_snapshot({
        "model": "gpt-5.5", "tools": tools, "tool_choice": tool_choice,
    })
    return orchestrator._provider_attempt_diagnostic(
        attempt=index, elapsed_ms=index, outcome="completed",
        response={"status": "completed", "output": []},
        tool_choice=tool_choice, tools=tools, request_shape=shape, http_status=http_status,
    )


def _unbound_diagnostic():
    return {"diagnostic_comparability": {
        "status": "incomparable", "claim_scope": "diagnostic_only",
        "missing_bindings": ["deployment", "code", "build", "source"],
        "missing_fields": ["request_shape", "tool_descriptor", "upstream_http_status",
                           "terminal_outcome", "valid_attempt"],
    }}


def _exhausted_graph_recovery(request, *, family="mail", complete=False):
    status = "not_found" if complete else "pending_review"
    return {
        "status": status, "citations": [], "evidence": [],
        "query_agent": {
            "status": "replan_required", "stop_reason": "time_budget_exhausted",
            "original_query_hash": request.request_contract["original_query_hash"],
            "request_contract": {
                "query_class": "evidence_lookup", "source_family_scope": [family],
            },
            "context_bundle": {
                "source_recovery": {
                    "artifact_id": "formowl_bounded_source_recovery_v1",
                    "query_hash": sha256_json(request.query_text),
                    "source_family_scope": [family], "source_families": [family],
                    "initial_status": "no_answer", "status": status, "attempted": True,
                    "scan": {
                        "scanned_observation_count": 4, "complete": complete,
                        "stop_reason": None if complete else "deadline",
                    },
                    "warnings": ["used", "complete_no_match" if complete else "incomplete"],
                },
            },
        },
    }


class MailToolDescriptionContractTests(unittest.TestCase):
    def test_graph_descriptor_teaches_document_and_table_intents_without_widening(self) -> None:
        descriptor = _actual_query_tool_descriptor()
        description = descriptor["description"]
        for phrase in (
            "standalone document_text lookup",
            "independently registered Markdown or plain-text documents",
            "not mail attachments",
            "No mail-session, sender, or message dependency",
            "line_start and line_end",
            "document revision bindings",
            "occurrence lineage",
            "structured/source-table lookup",
            "table_query with exact source-provided field labels",
            "at most one bounded same-scope source recheck inside this tool call",
            "same actor, workspace, grants, source scope and revision",
            "outer replan_required marker is not itself an eligible retrieval miss",
            "provider/tool errors",
            "permission denials",
            "unsupported or underspecified plans",
            "deterministic structured execution, never top-k inference",
            "pending_review, not absence",
            "not_found requires a complete bounded scan and sealed coverage",
            "Do not use this tool for ordinary chat",
            "zero new MCP calls",
            "query_mail_evidence",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, description)
        self.assertEqual(descriptor["inputSchema"]["required"], ["query_text"])
        self.assertNotIn("mail_import_session_id", descriptor["inputSchema"]["properties"])
        self.assertTrue(descriptor["annotations"]["readOnlyHint"])
        assert_no_public_raw_references(description, "graph_descriptor_intents")

    def test_mail_descriptor_teaches_standalone_authorized_bounded_lookup(self) -> None:
        descriptor = _actual_mail_tool_descriptor()
        description = descriptor["description"].lower()
        required_terms_schema = descriptor["inputSchema"]["properties"]["required_terms"]
        required_terms_description = required_terms_schema["description"].lower()

        for required_phrase in (
            "authorized workspace-mail evidence lookup",
            "query_text must be a standalone query",
            "preserve the user's person names, source scope, and quantifiers",
            "do not add 'all' or invent exact inventory/count intent",
            "exactly one selector",
            "current authorized capabilities",
            "do not send graph, table",
            "empty citations list is not proof that data is absent",
            "pending_review means",
            "not_found means",
            "permission_denied means",
            "retry at most once",
            "when budget remains",
            "server execution control permits requery",
        ):
            with self.subTest(required_phrase=required_phrase):
                self.assertIn(required_phrase, description)

        for required_phrase in (
            "all terms are conjunctive",
            "all terms are conjunctive and must match within the same candidate evidence item",
            "identity and genuine topic anchors",
            "authorized selector and validated request contract determine source-family/scope",
            "source-family and operation/action words are not content terms",
            "unless the user explicitly requests those literal words",
        ):
            with self.subTest(tool_description_phrase=required_phrase):
                self.assertIn(required_phrase, description)

        self.assertEqual(required_terms_schema["type"], "array")
        self.assertEqual(required_terms_schema["minItems"], 1)
        self.assertEqual(required_terms_schema["maxItems"], 8)
        self.assertEqual(required_terms_schema["items"]["minLength"], 1)
        self.assertEqual(required_terms_schema["items"]["maxLength"], 80)
        for required_phrase in (
            "combined with and",
            "every term must match within the same candidate evidence item",
            "identity and genuine topic terms",
            "authorized selector and validated request contract determine source-family/scope",
            "source-family and operation/action words are not content terms",
            "unless the user explicitly requests those literal words",
            "do not grant or widen authorization",
        ):
            with self.subTest(required_terms_description_phrase=required_phrase):
                self.assertIn(required_phrase, required_terms_description)

        for forbidden_fragment in (
            "raw path",
            "filesystem path",
            "secret",
            "private payload",
        ):
            with self.subTest(forbidden_fragment=forbidden_fragment):
                self.assertNotIn(forbidden_fragment, description)


class _RecordingTransport:
    def __init__(
        self,
        *,
        calls,
        final_message,
        run_error=None,
        handler_tool_name=None,
        invocation_tool_name=None,
    ) -> None:
        self.calls = tuple(calls)
        self.final_message = final_message
        self.run_error = run_error
        self.handler_tool_name = handler_tool_name
        self.invocation_tool_name = invocation_tool_name
        self.thread_start = None
        self.thread_starts = []
        self.turn_call = None
        self.tool_outputs = []
        self.deleted_threads = []

    def start_thread(
        self,
        *,
        model,
        cwd,
        base_instructions,
        developer_instructions,
        dynamic_tools,
    ):
        self.thread_start = {
            "model": model,
            "cwd": cwd,
            "base_instructions": base_instructions,
            "developer_instructions": developer_instructions,
            "dynamic_tools": tuple(dynamic_tools),
        }
        self.thread_starts.append(self.thread_start)
        return CodexAppServerThread(
            thread_id=f"thread-{len(self.thread_starts)}",
            model_name=model,
        )

    def run_turn(
        self,
        *,
        thread_id,
        user_text,
        additional_context,
        output_schema,
        reasoning_effort,
        client_metadata,
        tool_handler,
    ):
        selected_tool_name = self.thread_start["dynamic_tools"][0]["name"]
        self.turn_call = {
            "thread_id": thread_id,
            "user_text": user_text,
            "additional_context": additional_context,
            "output_schema": output_schema,
            "reasoning_effort": reasoning_effort,
            "client_metadata": client_metadata,
        }
        invocations = []
        for index, arguments in enumerate(self.calls):
            requested_tool_name = self.handler_tool_name or selected_tool_name
            result = tool_handler(requested_tool_name, arguments)
            self.tool_outputs.append(result)
            invocations.append(
                CodexDynamicToolInvocation(
                    thread_id=thread_id,
                    turn_id="turn-1",
                    call_id=f"call-{index}",
                    tool_name=self.invocation_tool_name or selected_tool_name,
                    arguments=arguments,
                    result=result,
                )
            )
        if self.run_error is not None:
            raise self.run_error
        return CodexAppServerTurn(
            thread_id=thread_id,
            turn_id="turn-1",
            final_message=self.final_message,
            tool_invocations=tuple(invocations),
        )

    def delete_thread(self, thread_id):
        self.deleted_threads.append(thread_id)

    def close(self):
        return None


class Issue56CodexProviderBridgeTests(unittest.TestCase):
    def test_binding_latest_attempt_controls_top_metadata_in_both_projections(self) -> None:
        from formowl_mail.human_uat_http import _safe_provider_diagnostic as http_project

        attempts = [_binding_attempt(i) for i in range(1, 7)]
        attempts[-1] = _binding_attempt(6, http_status=None, tool_choice="none")
        attempts[-1]["outcome"] = "error"
        attempts[-1]["valid_attempt"] = False  # Input claims never determine validation.
        raw = {"provider_attempt_count": 6, "provider_attempts": attempts,
               "provider_attempts_valid": False, "http_status": 201,
               "request_shape": attempts[0]["request_shape"],
               "tool_choice": attempts[0]["tool_choice"], "outcome": "completed"}
        for records in (attempts, attempts[-3:]):
            for project in (safe_provider_loop_diagnostics, runtime_project, http_project):
                with self.subTest(projection=project.__module__, records=len(records)):
                    safe = project({**raw, "provider_attempts": records})
                    self.assertIs(safe["provider_attempts_valid"], True)
                    self.assertEqual([a["attempt"] for a in safe["provider_attempts"]], [4, 5, 6])
                    self.assertTrue(all(a["valid_attempt"] is True for a in safe["provider_attempts"]))
                    latest = safe["provider_attempts"][-1]
                    self.assertEqual(safe["tool_choice"], latest["tool_choice"])
                    self.assertEqual(safe["outcome"], "error")
                    self.assertEqual(safe["request_shape"], latest["request_shape"])
                    self.assertNotIn("http_status", safe)
                    self.assertNotIn("http_status", latest)
                    self.assertEqual(safe["tool_choice"]["offered_tool_fingerprint_kind"],
                                     "full_descriptor_v1")
                    self.assertNotIn("private-sentinel", json.dumps(safe))
                    self.assertEqual(project(safe), safe)
        # A later record with absent shape/status must clear earlier top-level values.
        raw["provider_attempts"][-1].pop("request_shape")
        for project in (safe_provider_loop_diagnostics, runtime_project, http_project):
            safe = project(raw)
            self.assertNotIn("request_shape", safe)
            self.assertNotIn("http_status", safe)

    def test_binding_malformed_sequence_cannot_be_made_valid_by_claimed_flags(self) -> None:
        from formowl_mail.human_uat_http import _safe_provider_diagnostic as http_project

        raw = {"provider_attempt_count": 2,
               "provider_attempts": [_binding_attempt(1), _binding_attempt(2)],
               "provider_attempts_valid": True,
               "tool_choice": _binding_attempt()["tool_choice"], "outcome": "completed"}
        for bad in (True, 1, 3, "2"):
            forged = copy.deepcopy(raw)
            forged["provider_attempts"][-1].update(attempt=bad, valid_attempt=True)
            for project in (safe_provider_loop_diagnostics, runtime_project, http_project):
                with self.subTest(attempt=bad, projection=project.__module__):
                    safe = project(forged)
                    self.assertIs(safe["provider_attempts_valid"], False)
                    self.assertEqual(safe["provider_attempts"], [])
                    self.assertNotIn("tool_choice", safe)
                    self.assertNotIn("outcome", safe)

    def test_offered_tool_fingerprint_binds_full_descriptor_and_list_identity(self) -> None:
        descriptor = {
            "type": "function", "name": "query_mail_evidence",
            "description": "descriptor-private-sentinel",
            "parameters": {"type": "object", "properties": {
                "query_text": {"type": "string", "description": "schema-private-sentinel"},
            }, "required": ["query_text"], "additionalProperties": False},
            "strict": True,
        }

        def snapshot(tools):
            return orchestrator._provider_tool_choice_snapshot("auto", tools)

        original = snapshot([descriptor])
        with self.subTest(field="fingerprint_kind"):
            self.assertEqual(original.get("offered_tool_fingerprint_kind"), "full_descriptor_v1")
        for field in ("description", "parameters", "strict"):
            changed = copy.deepcopy(descriptor)
            if field == "description":
                changed[field] = "changed descriptor"
            elif field == "parameters":
                changed[field]["properties"]["query_text"]["type"] = "integer"
            else:
                changed[field] = False
            with self.subTest(field=field):
                self.assertNotEqual(snapshot([changed])["offered_tool_fingerprint"],
                                    original["offered_tool_fingerprint"])
        reordered = json.loads(json.dumps(descriptor, sort_keys=True))
        self.assertEqual(snapshot([reordered]), original)
        second = {**descriptor, "name": "query_effective_graph_view"}
        self.assertNotEqual(snapshot([descriptor, second])["offered_tool_fingerprint"],
                            snapshot([second, descriptor])["offered_tool_fingerprint"])
        self.assertNotEqual(snapshot([descriptor, descriptor])["offered_tool_fingerprint"],
                            original["offered_tool_fingerprint"])
        self.assertNotIn("private-sentinel", json.dumps(original))
        self.assertNotIn("offered_tool_fingerprint_kind", snapshot([{"name": descriptor["name"]}]))

    def test_concurrent_provider_requests_keep_their_own_upstream_status(self) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="concurrent-private-sentinel",
        )
        barrier = threading.Barrier(2, timeout=5)
        original_request = provider._request_response

        def request(payload):
            response = original_request(payload)
            # Both transport responses finish before either conversation can
            # record diagnostics, exposing any shared last-status slot.
            barrier.wait()
            return response

        def respond(status):
            response = mock.MagicMock()
            response.status = status
            response.headers = {"Content-Type": "application/json"}
            response.read.return_value = json.dumps({
                "status": "completed", "output_text": _decision(answer_text="hello"),
            }).encode()
            response.__enter__.return_value = response
            # The thread-local opener fixture below supplies this response.
            local.response = response
            return provider.respond(
                history=(), user_text="hello", latest_evidence=None,
                safety_identifier="concurrent-offline-session", evidence_tool=mock.Mock(),
            )

        local = threading.local()
        opener = mock.Mock()
        opener.open.side_effect = lambda *args, **kwargs: local.response
        with mock.patch.object(provider, "_request_response", side_effect=request), mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib.request.build_opener", return_value=opener,
        ), ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(respond, (201, 202)))
        for status, outcome in zip((201, 202), outcomes):
            self.assertEqual(outcome.provider_diagnostic["http_status"], status)
            self.assertEqual(outcome.provider_diagnostic["provider_attempts"][0]["http_status"], status)
            self.assertNotIn("private-sentinel", json.dumps(outcome.provider_diagnostic))

    def test_required_term_source_roles_are_full_span_and_preserve_literal_content(self) -> None:
        for term, family in (
            ("郵件", "mail"),
            ("mail", "mail"),
            ("MAIL", "mail"),
            ("ＭＡＩＬ", "mail"),
            ("e-mail", "mail"),
            ("文件", "document_text"),
            ("plain text", "document_text"),
            ("附件", "attachment_table"),
        ):
            self.assertEqual(_required_term_source_family(term), family)
        self.assertIsNone(_required_term_source_family("郵件風險"))
        self.assertIsNone(_required_term_source_family("mail security"))

        cases = (
            ("整理岑月的 郵件", "郵件", False),
            ("整理岑月的 mail", "mail", False),
            ("整理岑月的 MAIL", "MAIL", False),
            ("整理岑月的 ＭＡＩＬ", "ＭＡＩＬ", False),
            ("整理岑月關於郵件風險的郵件", "郵件風險", True),
            ("整理岑月關於mail security的郵件", "mail security", True),
            ('找出岑月郵件中包含「郵件」一詞的內容', "郵件", True),
            ('找出岑月郵件中包含「文件」一詞的內容', "文件", True),
            ("在獨立文件和郵件中整理岑月的研究記錄", "文件", False),
        )
        for prompt, term, accepted in cases:
            with self.subTest(prompt=prompt, term=term):
                binder = _UatTurnRequestContractBinder(
                    user_text=prompt,
                    authorized_capability_summary={
                        "source_families": ["mail", "document_text"],
                    },
                )
                if accepted:
                    bound = binder.bind_required_terms([term])
                    self.assertEqual(bound, (term.casefold(),))
                else:
                    with self.assertRaisesRegex(ContractValidationError, "source-family label"):
                        binder.bind_required_terms([term])

    def test_invalid_required_term_is_repaired_before_one_normal_mcp_call(self) -> None:
        descriptor = _actual_mail_tool_descriptor()
        citation = "citation-source-term-repair"
        prompt = "整理岑月關於青銅日誌的郵件內容"
        requests = []
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-required-term-repair-key",
        )
        invalid_arguments = {
            "query_text": "岑月 青銅日誌 郵件",
            "required_terms": ["岑月", "青銅日誌", "郵件"],
            "mail_import_session_id": "synthetic-mail-session",
        }
        corrected_arguments = {
            "query_text": "岑月 青銅日誌",
            "required_terms": ["岑月", "青銅日誌"],
            "mail_import_session_id": "synthetic-mail-session",
        }
        provider_responses = [
            {
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-source-term-invalid",
                        "name": descriptor["name"],
                        "arguments": json.dumps(invalid_arguments, ensure_ascii=False),
                    }
                ],
            },
            {
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-source-term-corrected",
                        "name": descriptor["name"],
                        "arguments": json.dumps(corrected_arguments, ensure_ascii=False),
                    }
                ],
            },
            {
                "status": "completed",
                "output_text": _decision(
                    answer_text="Synthetic cited mail evidence.",
                    citations=(citation,),
                    coverage_status="incomplete",
                    coverage_note="Bounded synthetic evidence.",
                ),
            },
        ]

        evidence_tool = mock.Mock(
            return_value={
                "status": "ok",
                "mail_import_session_id": "synthetic-mail-session",
                "evidence_snippets": [
                    {"citation_id": citation, "snippet": "Synthetic bounded evidence."}
                ],
                "citations": [citation],
            }
        )
        with mock.patch.object(
            provider,
            "_request_response",
            side_effect=provider_responses,
        ) as response_requests:
            outcome = provider.respond(
                history=(),
                user_text=prompt,
                latest_evidence=None,
                safety_identifier="required-term-source-repair",
                evidence_tool=evidence_tool,
                formowl_tool_descriptor=descriptor,
                authorized_capability_summary={
                    "source_families": ["mail"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["synthetic-mail-session"],
                },
            )
        requests.extend(call.args[0] for call in response_requests.call_args_list)

        self.assertEqual(len(requests), 3)
        repaired_output = next(
            item
            for item in requests[1]["input"]
            if item.get("type") == "function_call_output"
        )
        repair_payload = json.loads(repaired_output["output"])
        repair_hint = repair_payload["data"]["query_agent"]["external_replan"]["repair_hint"]
        self.assertIn("submit all grounded identity/topic content terms", repair_hint)
        self.assertNotIn("青銅日誌", json.dumps(repair_payload, ensure_ascii=False))
        evidence_tool.assert_called_once()
        self.assertEqual(set(evidence_tool.call_args.args[0].required_terms), {"岑月", "青銅日誌"})
        self.assertEqual(outcome.citation_ids, (citation,))

    def test_required_terms_freeze_only_after_valid_request_and_cannot_be_dropped(self) -> None:
        descriptor = _actual_mail_tool_descriptor()
        prompt = "整理岑月關於青銅日誌與星曆計畫的郵件"
        capability_summary = {
            "source_families": ["mail"],
            "mail_selector_kind": "mail_import_session_id",
            "authorized_mail_import_session_ids": ["synthetic-mail-session"],
        }
        binder = _UatTurnRequestContractBinder(
            user_text=prompt,
            authorized_capability_summary=capability_summary,
        )
        with self.assertRaisesRegex(ContractValidationError, "limit is invalid"):
            _parse_tool_request(
                {
                    "query_text": prompt,
                    "required_terms": ["岑月", "青銅日誌"],
                    "mail_import_session_id": "synthetic-mail-session",
                    "limit": 101,
                },
                tool_descriptor=descriptor,
                request_contract_binder=binder,
            )
        self.assertIsNone(binder._required_terms)

        accepted = _parse_tool_request(
            {
                "query_text": prompt,
                "required_terms": ["岑月", "青銅日誌", "星曆計畫"],
                "mail_import_session_id": "synthetic-mail-session",
                "limit": 1,
            },
            tool_descriptor=descriptor,
            request_contract_binder=binder,
        )
        self.assertEqual(set(accepted.required_terms), {"岑月", "青銅日誌", "星曆計畫"})
        with self.assertRaisesRegex(ContractValidationError, "changed within the turn"):
            _parse_tool_request(
                {
                    "query_text": prompt,
                    "required_terms": ["岑月", "青銅日誌"],
                    "mail_import_session_id": "synthetic-mail-session",
                    "limit": 1,
                },
                tool_descriptor=descriptor,
                request_contract_binder=binder,
            )

    def test_graph_retry_omission_preserves_frozen_required_terms(self) -> None:
        descriptor = _actual_query_tool_descriptor()
        prompt = "Find evidence for the synthetic project deadline"
        binder = _UatTurnRequestContractBinder(
            user_text=prompt,
            authorized_capability_summary={"source_families": ["mail", "document_text"]},
        )
        # Legacy standalone requests need no new conjunction, but once provided
        # it cannot be removed or narrowed by a provider retry.
        legacy = _parse_tool_request(
            {"query_text": prompt}, tool_descriptor=descriptor, request_contract_binder=binder,
        )
        self.assertIsNone(legacy.required_terms)
        accepted = _parse_tool_request(
            {"query_text": prompt, "required_terms": ["synthetic", "deadline"]},
            tool_descriptor=descriptor, request_contract_binder=binder,
        )
        retry = _parse_tool_request(
            {"query_text": prompt}, tool_descriptor=descriptor, request_contract_binder=binder,
        )
        self.assertEqual(retry.required_terms, accepted.required_terms)
        with self.assertRaisesRegex(ContractValidationError, "changed within the turn"):
            _parse_tool_request(
                {"query_text": prompt, "required_terms": ["synthetic"]},
                tool_descriptor=descriptor, request_contract_binder=binder,
            )

    def test_exhausted_source_recovery_stops_without_provider_continuation(self) -> None:
        for tool, family, complete in (
            ("query_effective_graph_view", "mail", False),
            ("query_effective_graph_view", "document_text", False),
            ("query_effective_graph_view", "document_text", True),
            ("query_mail_evidence", "mail", False),
        ):
            with self.subTest(tool=tool, family=family, complete=complete):
                descriptor = (
                    _actual_mail_tool_descriptor() if tool == "query_mail_evidence"
                    else _actual_query_tool_descriptor()
                )
                capabilities = {
                    "source_families": [family],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["synthetic-session"],
                }
                arguments = {
                    "query_text": "Find synthetic approval evidence",
                    "required_terms": ["synthetic", "approval"],
                }
                provider = CodexResponsesConversationModel(
                    base_url="https://provider.example.test/v1", api_key="synthetic-stop-key",
                )
                planned = {
                    "status": "completed", "output": [{
                        "type": "function_call", "call_id": "synthetic-stop-call",
                        "name": tool, "arguments": json.dumps(arguments),
                    }],
                }

                def recover(request):
                    if tool == "query_mail_evidence":
                        return {
                            "status": "pending_review", "citations": [],
                            "warnings": ["mail_evidence_source_fallback_used"],
                        }
                    return _exhausted_graph_recovery(request, family=family, complete=complete)

                evidence_tool = mock.Mock(side_effect=recover)
                with mock.patch.object(
                    provider, "_request_response",
                    side_effect=[planned, AssertionError("redundant provider continuation")],
                ) as provider_call:
                    outcome = provider.respond(
                        history=(), user_text="Find synthetic approval evidence",
                        latest_evidence=None, safety_identifier="source-stop-test",
                        evidence_tool=evidence_tool, formowl_tool_descriptor=descriptor,
                        authorized_capability_summary=capabilities,
                    )
                self.assertEqual(provider_call.call_count, 1)
                evidence_tool.assert_called_once()
                self.assertEqual(outcome.response_kind, "clarification")
                self.assertEqual(outcome.coverage_status, "incomplete")
                self.assertEqual(outcome.citation_ids, ())
                self.assertIn("這不代表資料不存在", outcome.answer_text)

    def test_graph_source_stop_requires_bound_attempted_lookup(self) -> None:
        request = UatEvidenceToolRequest(
            query_text="Find synthetic evidence",
            request_contract={
                "original_query_hash": sha256_json("synthetic original request"),
                "query_class": "evidence_lookup", "source_family_scope": ["document_text"],
                "requested_fields": [], "maximum_claim_strength": "cited_evidence",
            },
        )
        original = _exhausted_graph_recovery(request, family="document_text")
        self.assertTrue(orchestrator._source_fallback_exhausted(request, original))
        for change in (
            "unattempted", "no_scan", "no_marker", "wrong_query", "wrong_scope",
            "wrong_original", "provider_error", "permission_denied", "cited", "exact",
            "unsupported", "planner_stop_without_subquery", "planner_stop_rejected",
            "planner_stop_error", "planner_stop_failed", "planner_stop_permission_denied",
            "planner_stop_unsupported", "planner_stop_wrong_miss", "planner_stop_wrong_reason",
        ):
            with self.subTest(change=change):
                result = copy.deepcopy(original)
                agent = result["query_agent"]
                recovery = agent["context_bundle"]["source_recovery"]
                candidate_request = request
                if change == "unattempted":
                    recovery["attempted"] = False
                elif change == "no_scan":
                    recovery["scan"] = None
                elif change == "no_marker":
                    agent["context_bundle"].pop("source_recovery")
                elif change == "wrong_query":
                    recovery["query_hash"] = sha256_json("different query")
                elif change == "wrong_scope":
                    recovery["source_family_scope"] = ["mail"]
                elif change == "wrong_original":
                    agent["original_query_hash"] = sha256_json("different original")
                elif change == "provider_error":
                    agent["stop_reason"] = "provider_error"
                elif change == "permission_denied":
                    result["status"] = "permission_denied"
                elif change == "cited":
                    result["citations"] = ["synthetic-citation"]
                elif change == "exact":
                    candidate_request = replace(request, exact_field="synthetic_field")
                elif change == "unsupported":
                    agent["status"] = "unsupported"
                elif change.startswith("planner_stop_"):
                    agent.update(status="unsupported", stop_reason="planner_stopped_partial")
                    step = {
                        "validation_status": "validated_existing_scope_schema_permission",
                        "status": "no_answer",
                    }
                    agent["subqueries"] = [step]
                    if change == "planner_stop_without_subquery":
                        agent.pop("subqueries")
                    elif change == "planner_stop_rejected":
                        step["validation_status"] = "rejected_existing_validator"
                    elif change == "planner_stop_wrong_miss":
                        recovery["initial_status"] = "permission_denied"
                    elif change == "planner_stop_wrong_reason":
                        agent["stop_reason"] = "provider_error"
                    else:
                        step["status"] = change.removeprefix("planner_stop_")
                self.assertFalse(
                    orchestrator._source_fallback_exhausted(candidate_request, result),
                )

    def test_graph_recovery_private_trace_from_validated_call_is_safe(self) -> None:
        request = UatEvidenceToolRequest(
            query_text="Find synthetic trace evidence", required_terms=("synthetic",),
            request_contract={
                "original_query_hash": sha256_json("synthetic trace original"),
                "query_class": "evidence_lookup", "source_family_scope": ["document_text"],
                "requested_fields": [], "maximum_claim_strength": "cited_evidence",
            },
        )
        result = _exhausted_graph_recovery(request, family="document_text")
        service = object.__new__(Issue56TemporaryLanQueryService)
        service._client = SimpleNamespace(post=mock.Mock(return_value=SimpleNamespace(
            status_code=200,
            json=lambda: {"result": {"isError": False, "structuredContent": {"data": result}}},
        )))
        service._active_turn_deadline = time.monotonic() + 60
        service.last_failure_phase = "provider_model"
        service.request_count = 0
        service._record_raw_uat_interactions = False
        traces, private_log = [], io.StringIO()
        with redirect_stderr(private_log):
            returned = service._call(
                request, trace_sink=traces, browser_request_sha256=sha256_json("trace request"),
            )
        self.assertEqual(returned, result)
        event = json.loads(private_log.getvalue())
        self.assertEqual(event["event"], "issue56_private_graph_recheck_trace")
        self.assertTrue(event["recovery_present"])
        self.assertTrue(event["attempted"])
        self.assertEqual(event["source_families"], ["document_text"])
        self.assertEqual(event["scanned_observation_count"], 4)
        self.assertEqual(event["scan_stop_reason"], "deadline")
        self.assertFalse(event["scan_complete"])
        self.assertEqual(event["recheck_warnings"], ["incomplete", "used"])
        self.assertNotIn(request.query_text, private_log.getvalue())
        self.assertNotIn("source_recovery", traces[0])
        self.assertIsNone(uat_runtime._private_graph_recheck_trace(
            {**traces[0], "response_stage": "payload_validation"}, result,
        ))
        no_recovery = {**result, "query_agent": {"status": "replan_required"}}
        self.assertFalse(
            uat_runtime._private_graph_recheck_trace(traces[0], no_recovery)["recovery_present"],
        )
        recovery = result["query_agent"]["context_bundle"]["source_recovery"]
        recovery.update({
            "initial_status": "private-source-marker",
            "source_families": ["document_text", "private-source-marker"],
            "warnings": ["used", "private-source-marker"],
            "source_authority_fingerprint": "private-source-marker",
            "evidence": [{"snippet": "private-source-marker"}],
        })
        recovery["scan"].update({
            "stop_reason": "private-source-marker", "scanned_observation_count": True,
        })
        safe = uat_runtime._private_graph_recheck_trace(traces[0], result)
        self.assertNotIn("private-source-marker", json.dumps(safe))
        self.assertNotIn("scan_stop_reason", safe)
        self.assertNotIn("scanned_observation_count", safe)

    def test_graph_document_guidance_reaches_responses_and_app_server(self) -> None:
        """Provider-free transport contract, not document retrieval acceptance."""

        descriptor = _actual_query_tool_descriptor()
        arguments = {"query_text": "Find evidence in the authorized project document."}
        citation = "document-citation-bridge"
        final_message = _decision(
            answer_text="Synthetic document evidence.",
            citations=(citation,),
            coverage_status="incomplete",
            coverage_note="Only bounded evidence is available.",
        )
        evidence = {"status": "ok", "citations": [citation]}
        for bridge in ("responses", "app_server"):
            with self.subTest(bridge=bridge), tempfile.TemporaryDirectory() as workspace:
                evidence_tool = mock.Mock(return_value=evidence)
                if bridge == "responses":
                    provider = CodexResponsesConversationModel(
                        base_url="https://provider.example.test/v1",
                        api_key="synthetic-descriptor-key",
                    )
                    response_patch = mock.patch.object(
                        provider,
                        "_request_response",
                        side_effect=[
                            {
                                "status": "completed",
                                "output": [{
                                    "type": "function_call",
                                    "call_id": "document-bridge-call",
                                    "name": descriptor["name"],
                                    "arguments": json.dumps(arguments),
                                }],
                            },
                            {"status": "completed", "output_text": final_message},
                        ],
                    )
                else:
                    transport = _RecordingTransport(
                        calls=(arguments,), final_message=final_message
                    )
                    provider = CodexAppServerConversationModel(transport, workspace_dir=workspace)
                    response_patch = mock.patch.object(
                        transport, "start_thread", wraps=transport.start_thread
                    )
                with response_patch as recorded:
                    outcome = provider.respond(
                        history=(),
                        user_text=arguments["query_text"],
                        latest_evidence=None,
                        safety_identifier=f"document-descriptor-{bridge}",
                        evidence_tool=evidence_tool,
                        formowl_tool_descriptor=descriptor,
                        authorized_capability_summary={"source_families": ["document_text"]},
                    )
                if bridge == "responses":
                    payload = recorded.call_args_list[0].args[0]
                    tool = next(
                        item for item in payload["tools"] if item["name"] == descriptor["name"]
                    )
                    schema = tool["parameters"]
                    instructions = payload["instructions"]
                else:
                    tool = transport.thread_start["dynamic_tools"][0]
                    schema = tool["inputSchema"]
                    instructions = transport.thread_start["base_instructions"]
                self.assertEqual(tool["description"], descriptor["description"])
                self.assertEqual(schema, descriptor["inputSchema"])
                instructions = " ".join(instructions.split())
                for phrase in (
                    "standalone document_text lookup",
                    "independent Markdown or plain-text document",
                    "No mail-session, sender, or message dependency",
                    "line_start and line_end",
                    "revision bindings",
                    "occurrence lineage",
                    "source-table lookup",
                    "typed table_query",
                    "at most one bounded same-scope source recheck inside this tool call",
                    "outer replan_required marker is not itself an eligible retrieval miss",
                    "provider/tool errors, permission denials",
                    "unsupported or underspecified plans, or exact requests",
                    "deterministic structured execution, never top-k inference",
                    "pending_review, not absence",
                    "Do not call FormOwl when the user:",
                    "greets you",
                    "evidence already returned in this conversation",
                    "do not widen authorization",
                ):
                    with self.subTest(phrase=phrase):
                        self.assertIn(phrase.casefold(), instructions.casefold())
                assert_no_public_raw_references(instructions, "graph_provider_instructions")
                evidence_tool.assert_called_once()
                request = evidence_tool.call_args.args[0]
                self.assertEqual(request.request_contract["source_family_scope"], ["document_text"])
                self.assertIsNone(request.mail_import_session_id)
                self.assertIsNone(request.table_query)
                self.assertEqual(outcome.citation_ids, (citation,))

    def test_mail_provider_omitted_selector_is_bound_from_one_authorized_selector(self) -> None:
        prompt = "把劉一帆的信件整理出來"
        citation = "sha256:mail-selector-bound"
        transport = _RecordingTransport(
            calls=(
                {
                    "query_text": prompt,
                    "required_terms": ["劉一帆"],
                    "limit": 1,
                },
            ),
            final_message=_decision(
                answer_text="已整理授權郵件證據。",
                citations=(citation,),
                coverage_status="complete",
            ),
        )
        evidence_requests = []
        with tempfile.TemporaryDirectory() as workspace:
            provider = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            outcome = provider.respond(
                history=(),
                user_text=prompt,
                latest_evidence=None,
                safety_identifier="mail-selector-omitted",
                evidence_tool=lambda request: (
                    evidence_requests.append(request)
                    or {"status": "ok", "citations": [citation]}
                ),
                formowl_tool_descriptor=_actual_mail_tool_descriptor(),
                authorized_capability_summary={
                    "source_families": ["mail"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["authorized-session"],
                },
            )

        self.assertEqual(len(evidence_requests), 1)
        self.assertEqual(
            evidence_requests[0].mail_import_session_id,
            "authorized-session",
        )
        self.assertIsNone(evidence_requests[0].mail_evidence_bundle_id)
        self.assertEqual(outcome.citation_ids, (citation,))

    def test_mail_selector_binding_preserves_explicit_authorized_and_rejects_other_or_ambiguous(
        self,
    ) -> None:
        descriptor = _actual_mail_tool_descriptor()
        binder = _UatTurnRequestContractBinder(
            user_text="把劉一帆的信件整理出來",
            authorized_capability_summary={
                "source_families": ["mail"],
                "mail_selector_kind": "mail_import_session_id",
                "authorized_mail_import_session_ids": ["authorized-session"],
            },
        )
        explicit = _parse_tool_request(
            {
                "query_text": "把劉一帆的信件整理出來",
                "required_terms": ["劉一帆"],
                "mail_import_session_id": "authorized-session",
            },
            tool_descriptor=descriptor,
            request_contract_binder=binder,
        )
        self.assertEqual(explicit.mail_import_session_id, "authorized-session")

        with self.assertRaisesRegex(ContractValidationError, "selector is unauthorized"):
            _parse_tool_request(
                {
                    "query_text": "把劉一帆的信件整理出來",
                    "required_terms": ["劉一帆"],
                    "mail_import_session_id": "other-session",
                },
                tool_descriptor=descriptor,
                request_contract_binder=binder,
            )

        ambiguous_binder = _UatTurnRequestContractBinder(
            user_text="把劉一帆的信件整理出來",
            authorized_capability_summary={
                "source_families": ["mail"],
                "mail_selector_kind": "mail_import_session_id",
                "authorized_mail_import_session_ids": [
                    "authorized-session-a",
                    "authorized-session-b",
                ],
            },
        )
        with self.assertRaisesRegex(ContractValidationError, "selector is ambiguous"):
            _parse_tool_request(
                {
                    "query_text": "把劉一帆的信件整理出來",
                    "required_terms": ["劉一帆"],
                },
                tool_descriptor=descriptor,
                request_contract_binder=ambiguous_binder,
            )

        unavailable_binder = _UatTurnRequestContractBinder(
            user_text="把劉一帆的信件整理出來",
            authorized_capability_summary={"source_families": ["mail"]},
        )
        with self.assertRaisesRegex(ContractValidationError, "selector is unavailable"):
            _parse_tool_request(
                {
                    "query_text": "把劉一帆的信件整理出來",
                    "required_terms": ["劉一帆"],
                },
                tool_descriptor=descriptor,
                request_contract_binder=unavailable_binder,
            )
        with self.assertRaisesRegex(ContractValidationError, "selector is unavailable"):
            _parse_tool_request(
                {
                    "query_text": "把劉一帆的信件整理出來",
                    "required_terms": ["劉一帆"],
                    "mail_import_session_id": "unbound-session",
                },
                tool_descriptor=descriptor,
                request_contract_binder=unavailable_binder,
            )

        non_mail_binder = _UatTurnRequestContractBinder(
            user_text="把劉一帆的信件整理出來",
            authorized_capability_summary={"source_families": ["attachment_table"]},
        )
        with self.assertRaisesRegex(ContractValidationError, "selector is unavailable"):
            _parse_tool_request(
                {
                    "query_text": "把劉一帆的信件整理出來",
                    "required_terms": ["劉一帆"],
                    "mail_import_session_id": "unbound-session",
                },
                tool_descriptor=descriptor,
                request_contract_binder=non_mail_binder,
            )

        for malformed_value in (None, "", "   ", 42, ["not-a-selector"]):
            with self.subTest(malformed_value=malformed_value):
                with self.assertRaisesRegex(
                    ContractValidationError,
                    "selector is invalid",
                ):
                    _parse_tool_request(
                        {
                            "query_text": "把劉一帆的信件整理出來",
                            "required_terms": ["劉一帆"],
                            "mail_import_session_id": malformed_value,
                        },
                        tool_descriptor=descriptor,
                        request_contract_binder=binder,
                    )

    def test_mail_selector_metadata_rejects_malformed_duplicate_and_over_limit_values(self) -> None:
        for key in ("authorized_mail_import_session_ids", "authorized_mail_evidence_bundle_ids"):
            for values in (
                [], "session", {"session": "value"}, [None], [""], ["   "],
                ["session", "session"], [f"session-{index}" for index in range(129)],
            ):
                with self.subTest(key=key, values=values):
                    with self.assertRaisesRegex(
                        ContractValidationError, "mail selector metadata is invalid",
                    ):
                        _UatTurnRequestContractBinder(
                            user_text="Hello",
                            authorized_capability_summary={"source_families": ["mail"], key: values},
                        )

    def test_mail_explicit_selector_without_valid_capabilities_never_calls_mcp(
        self,
    ) -> None:
        descriptor = _actual_mail_tool_descriptor()
        capability_cases = (
            ("missing", None),
            (
                "non_mail_source",
                {
                    "source_families": ["attachment_table"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["authorized-session"],
                },
            ),
        )
        for case_name, capability_summary in capability_cases:
            with self.subTest(case_name=case_name):
                transport = _RecordingTransport(
                    calls=(
                        {
                            "query_text": "authorized mail evidence",
                            "mail_import_session_id": "authorized-session",
                        },
                    ),
                    final_message=_decision(answer_text="should not finalize"),
                )
                evidence_tool = mock.Mock(
                    return_value={
                        "status": "ok",
                        "citations": ["must-not-be-called"],
                    }
                )
                with tempfile.TemporaryDirectory() as workspace:
                    provider = CodexAppServerConversationModel(
                        transport,
                        workspace_dir=workspace,
                    )
                    with self.assertRaisesRegex(
                        ContractValidationError,
                        "(?:selector is unavailable|mail capability source family is unavailable)",
                    ):
                        provider.respond(
                            history=(),
                            user_text="整理授權郵件",
                            latest_evidence=None,
                            safety_identifier=f"missing-mail-capability-{case_name}",
                            evidence_tool=evidence_tool,
                            formowl_tool_descriptor=descriptor,
                            authorized_capability_summary=capability_summary,
                        )
                evidence_tool.assert_not_called()
                self.assertEqual(transport.tool_outputs, [])

    def test_app_server_rebinds_selected_descriptor_when_conversation_tool_changes(
        self,
    ) -> None:
        transport = _RecordingTransport(
            calls=(),
            final_message=_decision(answer_text="bounded non-evidence answer"),
        )
        with tempfile.TemporaryDirectory() as workspace:
            provider = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            provider.respond(
                history=(),
                user_text="hello",
                latest_evidence=None,
                safety_identifier="descriptor-switch-session",
                evidence_tool=mock.Mock(),
                formowl_tool_descriptor=_actual_query_tool_descriptor(),
            )
            provider.respond(
                history=(),
                user_text="hello",
                latest_evidence=None,
                safety_identifier="descriptor-switch-session",
                evidence_tool=mock.Mock(),
                formowl_tool_descriptor=_actual_mail_tool_descriptor(),
            )

        self.assertEqual(len(transport.thread_starts), 2)
        self.assertEqual(
            [start["dynamic_tools"][0]["name"] for start in transport.thread_starts],
            ["query_effective_graph_view", "query_mail_evidence"],
        )
        self.assertEqual(transport.deleted_threads, ["thread-1"])

    def test_typed_evidence_request_rejects_cross_tool_arguments(self) -> None:
        with self.assertRaisesRegex(
            ContractValidationError,
            "graph arguments",
        ):
            UatEvidenceToolRequest(
                query_text="mail lookup",
                tool_name="query_mail_evidence",
                mail_import_session_id="mail-session",
                exact_field="subject",
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "mail arguments",
        ):
            UatEvidenceToolRequest(
                query_text="graph lookup",
                tool_name="query_effective_graph_view",
                limit=1,
            )

    def test_final_citation_budget_matches_structured_response_schema(self) -> None:
        with self.assertRaisesRegex(
            ContractValidationError,
            "citation identifier limit",
        ):
            UatConversationOutcome(
                response_kind="answer",
                answer_text="bounded answer",
                display_format="narrative",
                model_name="synthetic-provider",
                citation_ids=tuple(f"citation-{index}" for index in range(25)),
            )

    def test_query_agent_context_keeps_descriptor_when_optional_capabilities_fail_contract(
        self,
    ) -> None:
        descriptor = SimpleNamespace(
            name="query_effective_graph_view",
            model_dump=lambda **_kwargs: _actual_query_tool_descriptor(),
        )
        retrieval_handler = SimpleNamespace(
            authorized_capability_summary={"token": "must-not-be-public"},
        )
        application = SimpleNamespace(
            dispatcher=SimpleNamespace(
                required_scope="formowl.use",
                enabled_tool_names=frozenset(
                    {"whoami", "query_effective_graph_view"},
                ),
                semantic_gateway=SimpleNamespace(
                    retrieval_handler=retrieval_handler,
                ),
            ),
        )
        with mock.patch(
            "formowl_gateway.issue56_uat_runtime.build_remote_tool_descriptors",
            return_value=[descriptor],
        ):
            tool_descriptor, capabilities = _query_agent_runtime_context(application)

        self.assertEqual(tool_descriptor["name"], "query_effective_graph_view")
        self.assertIsNone(capabilities)

    def test_query_agent_context_routes_chinese_mail_and_keeps_chat_on_graph(self) -> None:
        graph_descriptor = SimpleNamespace(
            name="query_effective_graph_view",
            model_dump=lambda **_kwargs: _actual_query_tool_descriptor(),
        )
        mail_descriptor = SimpleNamespace(
            name="query_mail_evidence",
            model_dump=lambda **_kwargs: _actual_mail_tool_descriptor(),
        )
        capability_summary = {"source_families": ["mail"]}
        application = SimpleNamespace(
            dispatcher=SimpleNamespace(
                required_scope="formowl.use",
                enabled_tool_names=frozenset(
                    {"whoami", "query_effective_graph_view", "query_mail_evidence"},
                ),
                semantic_gateway=SimpleNamespace(
                    retrieval_handler=SimpleNamespace(
                        authorized_capability_summary=capability_summary,
                    ),
                    mail_evidence_handler=SimpleNamespace(
                        authorized_capability_summary=capability_summary,
                    ),
                ),
            ),
        )

        with mock.patch(
            "formowl_gateway.issue56_uat_runtime.build_remote_tool_descriptors",
            return_value=[graph_descriptor, mail_descriptor],
        ):
            mail_tool, _ = _query_agent_runtime_context(
                application,
                user_text="劉一帆的信件",
            )
            greeting_tool, _ = _query_agent_runtime_context(
                application,
                user_text="你好，今天好嗎？",
            )
            writing_tool, _ = _query_agent_runtime_context(
                application,
                user_text="幫我寫一封信",
            )

        self.assertEqual(mail_tool["name"], "query_mail_evidence")
        self.assertEqual(greeting_tool["name"], "query_effective_graph_view")
        self.assertEqual(writing_tool["name"], "query_effective_graph_view")

    def test_uat_accepts_success_envelope_with_canonical_content_only(self) -> None:
        from formowl_gateway.issue56_uat_runtime import Issue56UatQueryService

        payload = {
            "result_type": "effective_graph_query",
            "status": "ok",
            "data": {"status": "ok", "citations": []},
            "warnings": [],
        }
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "jsonrpc": "2.0",
                "id": "call-1",
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload, separators=(",", ":")),
                        }
                    ],
                },
            },
        )
        service = object.__new__(Issue56UatQueryService)
        service._client = SimpleNamespace(post=mock.Mock(return_value=response))
        service.request_count = 0

        result = service._call(
            UatEvidenceToolRequest(query_text="bounded query"),
            bearer="synthetic-bearer",
        )

        self.assertEqual(result, payload["data"])
        self.assertEqual(service.request_count, 1)
        service._client.post.assert_called_once()

    def test_uat_mcp_worker_uses_isolated_testclient_from_http_worker(self) -> None:
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from formowl_gateway.issue56_uat_runtime import Issue56TemporaryLanQueryService

        async def mcp(request):
            del request
            payload = {
                "result_type": "effective_graph_query",
                "status": "ok",
                "data": {
                    "status": "ok",
                    "citations": ["thread-safe-citation"],
                },
                "warnings": [],
            }
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": "call-1",
                    "result": {
                        "content": [
                            {
                                "type": "json",
                                "json": payload,
                            }
                        ],
                    },
                }
            )

        lifespan_started = False

        @asynccontextmanager
        async def lifespan(_app):
            nonlocal lifespan_started
            if lifespan_started:
                raise RuntimeError("one-shot lifespan was re-entered")
            lifespan_started = True
            yield

        app = Starlette(
            routes=[Route("/mcp", mcp, methods=["POST"])],
            lifespan=lifespan,
        )
        service = object.__new__(Issue56TemporaryLanQueryService)
        service._application = SimpleNamespace(app=app)
        service._active_turn_deadline = time.monotonic() + 10
        service.last_failure_phase = "provider_model"
        service.request_count = 0
        service._record_raw_uat_interactions = False
        traces: list[dict[str, object]] = []
        result_holder: list[Mapping[str, object]] = []

        with TestClient(app, raise_server_exceptions=False) as shared_client:
            service._client = shared_client
            # The outer HTTP service owns the app lifespan.  Re-entering it
            # from this worker would be an invalid second session-manager
            # lifetime; the isolated transport must therefore stay unentered.
            with self.assertRaises(RuntimeError):
                with TestClient(app, raise_server_exceptions=False):
                    pass
            worker = threading.Thread(
                target=lambda: result_holder.append(
                    service._call(
                        UatEvidenceToolRequest(query_text="bounded query"),
                        trace_sink=traces,
                    )
                ),
                name="threading-http-worker",
            )
            worker.start()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertTrue(lifespan_started)
        self.assertEqual(result_holder, [{"status": "ok", "citations": ["thread-safe-citation"]}])
        self.assertEqual(traces[0]["response_stage"], "payload_validated")

    def test_uat_accepts_success_envelope_with_canonical_json_content_only(self) -> None:
        from formowl_gateway.issue56_uat_runtime import Issue56UatQueryService

        payload = {
            "result_type": "effective_graph_query",
            "status": "ok",
            "data": {"status": "ok", "citations": []},
            "warnings": [],
        }
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "jsonrpc": "2.0",
                "id": "call-1",
                "result": {
                    "content": [{"type": "json", "json": payload}],
                    "isError": False,
                },
            },
        )
        service = object.__new__(Issue56UatQueryService)
        service._client = SimpleNamespace(post=mock.Mock(return_value=response))
        service.request_count = 0

        result = service._call(
            UatEvidenceToolRequest(query_text="bounded query"),
            bearer="synthetic-bearer",
        )

        self.assertEqual(result, payload["data"])
        self.assertEqual(service.request_count, 1)
        service._client.post.assert_called_once()

    def test_uat_classifies_safe_mcp_envelope_failures(self) -> None:
        from formowl_gateway.issue56_uat_runtime import Issue56TemporaryLanQueryService

        request = UatEvidenceToolRequest(query_text="bounded query")
        cases = (
            (
                {
                    "jsonrpc": "2.0",
                    "id": "call-1",
                    "result": {"isError": True, "content": []},
                },
                "jsonrpc_result_error",
            ),
            (
                {
                    "jsonrpc": "2.0",
                    "id": "call-1",
                    "result": {
                        "isError": False,
                        "content": [{"type": "json", "json": {"status": "ok"}}],
                    },
                },
                "missing_data_mapping",
            ),
        )
        for envelope, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                response = SimpleNamespace(status_code=200, json=lambda: envelope)
                service = object.__new__(Issue56TemporaryLanQueryService)
                service._client = SimpleNamespace(post=mock.Mock(return_value=response))
                service._active_turn_deadline = time.monotonic() + 60
                service.last_failure_phase = "provider_model"
                service.request_count = 0
                service._record_raw_uat_interactions = False
                traces = []

                result = service._call(request, trace_sink=traces)

                self.assertEqual(result, {"status": "mcp_failed", "citations": []})
                self.assertEqual(traces[0]["failure_reason"], expected_reason)
                self.assertIsNone(traces[0]["exception_class"])

    def test_uat_extracts_allowlisted_reason_from_error_structured_content(self) -> None:
        from formowl_gateway.issue56_uat_runtime import Issue56TemporaryLanQueryService

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
                            "private_detail": "raw-provider-body-never-public",
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
        traces: list[dict[str, object]] = []

        result = service._call(
            UatEvidenceToolRequest(query_text="bounded query"),
            trace_sink=traces,
        )

        self.assertEqual(result, {"status": "mcp_failed", "citations": []})
        self.assertEqual(traces[0]["failure_reason"], "tool_execution_failed")
        self.assertNotIn("raw-provider-body-never-public", json.dumps(traces))

    def test_uat_maps_fixed_remote_error_text_without_exposing_error_text(self) -> None:
        from formowl_gateway.issue56_uat_runtime import Issue56TemporaryLanQueryService

        response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "jsonrpc": "2.0",
                "id": "call-1",
                "result": {
                    "isError": True,
                    "content": [
                        {
                            "type": "text",
                            "text": "The FormOwl tool could not complete the request.",
                        }
                    ],
                },
            },
        )
        service = object.__new__(Issue56TemporaryLanQueryService)
        service._client = SimpleNamespace(post=mock.Mock(return_value=response))
        service._active_turn_deadline = time.monotonic() + 60
        service.last_failure_phase = "provider_model"
        service.request_count = 0
        service._record_raw_uat_interactions = False
        traces: list[dict[str, object]] = []

        service._call(
            UatEvidenceToolRequest(query_text="bounded query"),
            trace_sink=traces,
        )

        self.assertEqual(traces[0]["failure_reason"], "tool_execution_failed")
        self.assertNotIn("The FormOwl tool could not complete", json.dumps(traces))

    def test_uat_failure_reason_reaches_http_normalization_safely(self) -> None:
        from formowl_mail.human_uat_http import _normalize_query_response

        request = UatEvidenceToolRequest(query_text="bounded query")
        reasons = (
            "http_status",
            "jsonrpc_result_error",
            "missing_structured_payload",
            "missing_data_mapping",
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                response = SimpleNamespace(
                    status_code=200,
                    json=lambda: {
                        "jsonrpc": "2.0",
                        "id": "call-1",
                        "result": {"isError": True, "content": []},
                    },
                )
                service = object.__new__(Issue56TemporaryLanQueryService)
                service._client = SimpleNamespace(post=mock.Mock(return_value=response))
                service._active_turn_deadline = time.monotonic() + 60
                service.last_failure_phase = "provider_model"
                service.request_count = 0
                service._record_raw_uat_interactions = False
                traces = []
                service._call(request, trace_sink=traces)
                traced = dict(traces[0])
                traced["failure_reason"] = reason

                projected = _with_mcp_diagnostic(
                    {
                        "status": "clarification_required",
                        "answer": "",
                        "citations": [],
                        "clarification": "safe failure",
                    },
                    [traced],
                )
                normalized = _normalize_query_response(projected)

                self.assertEqual(
                    normalized["diagnostic"]["mcp"]["failure_reason"],
                    reason,
                )
                rendered = json.dumps(normalized, ensure_ascii=False)
                self.assertNotIn("private-mail-body", rendered)
                self.assertNotIn("https://private.example", rendered)
                self.assertNotIn("secret-token", rendered)

        unsafe = _normalize_query_response(
            {
                "status": "clarification_required",
                "answer": "",
                "citations": [],
                "clarification": "safe failure",
                "diagnostic": {"mcp": {"failure_reason": "raw_payload"}},
            }
        )
        self.assertNotIn("mcp", unsafe["diagnostic"])

    def test_remote_failure_metadata_reaches_safe_trace_and_http_projection(self) -> None:
        from formowl_mail.human_uat_http import _normalize_query_response

        query = "private-query-marker"
        selector = "private-selector-marker"
        for stage, exception, expected_stage, expected_class in (
            ("exception", "RuntimeError", "exception", "RuntimeError"),
            (
                "payload_validation",
                "ContractValidationError",
                "payload_validation",
                "ContractValidationError",
            ),
            ("payload_validated", "PrivateSecretException", "jsonrpc_error", None),
            ([], {}, "jsonrpc_error", None),
        ):
            with self.subTest(expected_stage=expected_stage, expected_class=expected_class):
                result = {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": "The FormOwl tool could not complete the request.",
                    }],
                    "_meta": {"formowl_diagnostic": {
                        "response_stage": stage,
                        "exception_class": exception,
                        "exception_owner": {
                            "module": "formowl_mail.query",
                            "symbol": "build_revision_owned_mail_evidence_query_handler.locals.handler",
                            "line": 1070,
                        },
                        "query_hash": "private-secret-marker",
                        "query_length": -1,
                        "query": query,
                        "selector": selector,
                        "exception_message": "/tmp/private-path-marker",
                    }},
                }
                service = object.__new__(Issue56TemporaryLanQueryService)
                service._client = SimpleNamespace(post=mock.Mock(return_value=SimpleNamespace(
                    status_code=200, json=lambda: {"result": result},
                )))
                service._active_turn_deadline = time.monotonic() + 60
                service.last_failure_phase = "provider_model"
                service.request_count = 0
                service._record_raw_uat_interactions = False
                traces = []
                private_log = io.StringIO()
                with redirect_stderr(private_log):
                    returned = service._call(
                        UatEvidenceToolRequest(
                            query_text=query,
                            tool_name="query_mail_evidence",
                            mail_import_session_id=selector,
                        ),
                        trace_sink=traces,
                    )
                self.assertEqual(returned, {"status": "mcp_failed", "citations": []})
                self.assertIn("issue56_private_mcp_owner_trace", private_log.getvalue())
                self.assertNotIn(query, private_log.getvalue())
                self.assertNotIn(selector, private_log.getvalue())
                self.assertNotIn("/tmp/private-path-marker", private_log.getvalue())
                self.assertEqual(traces[0]["exception_class"], expected_class)
                self.assertEqual(traces[0]["response_stage"], expected_stage)
                self.assertEqual(
                    traces[0]["exception_owner"],
                    {
                        "module": "formowl_mail.query",
                        "symbol": "build_revision_owned_mail_evidence_query_handler.locals.handler",
                        "line": 1070,
                    },
                )
                self.assertEqual(
                    service._last_private_mcp_owner_trace,
                    {
                        "exception_owner": {
                            "module": "formowl_mail.query",
                            "symbol": "build_revision_owned_mail_evidence_query_handler.locals.handler",
                            "line": 1070,
                        },
                        **(
                            {"exception_class": expected_class}
                            if expected_class is not None
                            else {}
                        ),
                        "response_stage": expected_stage,
                        "failure_reason": "tool_execution_failed",
                        "request_discriminator": {
                            "tool_name": "query_mail_evidence",
                            "query_text_char_count": 20,
                            "selector_kind": "mail_import_session_id",
                            "selector_present": True,
                            "selector_count": 1,
                            "selector_hash": (
                                "sha256:"
                                + hashlib.sha256(selector.encode()).hexdigest()
                            ),
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
                self.assertEqual(traces[0]["query_hash"],
                                 "sha256:" + hashlib.sha256(query.encode()).hexdigest())
                self.assertEqual(traces[0]["query_length"], len(query))
                projected = _with_mcp_diagnostic({
                    "status": "clarification_required", "answer": "",
                    "citations": [], "clarification": "safe failure",
                }, traces)
                projected["diagnostic"] = runtime_project(projected["diagnostic"])
                normalized = _normalize_query_response(projected)
                diagnostic = normalized["diagnostic"]["mcp"]
                self.assertEqual(diagnostic["response_stage"], expected_stage)
                self.assertEqual(diagnostic.get("exception_class"), expected_class)
                self.assertEqual(diagnostic["failure_reason"], "tool_execution_failed")
                self.assertEqual(diagnostic["request_discriminator"]["selector_count"], 1)
                self.assertFalse(diagnostic["timeout"])
                self.assertNotIn("exception_owner", diagnostic)
                rendered = json.dumps([traces, normalized])
                for private in (
                    query, selector, "private-secret-marker", "PrivateSecretException",
                    "/tmp/private-path-marker",
                ):
                    self.assertNotIn(private, rendered)
                service._client.post.assert_called_once()

    def test_evidence_need_binding_preserves_generic_interaction_semantics(self) -> None:
        self.assertFalse(requires_workspace_evidence("你好"))
        self.assertFalse(requires_workspace_evidence("What can you do?"))
        self.assertFalse(
            requires_workspace_evidence(
                "summarize the above in a table",
                prior_evidence_citeable=True,
                prior_evidence_present=True,
            )
        )
        self.assertTrue(
            requires_workspace_evidence(
                "What is the current supplier status?",
                prior_evidence_citeable=True,
                prior_evidence_present=True,
            )
        )

    def test_compact_mail_evidence_keeps_bounded_safe_snippets_and_citations(self) -> None:
        citation = {
            "citation_id": "mail-citation-1",
            "source_type": "mail_body_segment",
            "source_observation_id": "observation-1",
            "mail_import_session_id": "mail-session-1",
            "email_message_id": "message-1",
            "message_occurrence_id": "occurrence-1",
            "raw_path": "/private/mail/archive.pst",
        }
        compact = compact_evidence_for_model(
            {
                "status": "ok",
                "query_hash": "sha256:mail-query",
                "evidence_snippets": [
                    {
                        "source_type": "mail_body_segment",
                        "source_observation_id": "observation-1",
                        "mail_import_session_id": "mail-session-1",
                        "email_message_id": "message-1",
                        "message_occurrence_id": "occurrence-1",
                        "subject": "Launch checklist",
                        "snippet": "The governed mail snippet.",
                        "score": 2,
                        "matched_terms": ["launch", "checklist"],
                        "raw_path": "/private/mail/archive.pst",
                    },
                    {
                        "source_type": "mail_body_segment",
                        "source_observation_id": "observation-2",
                        "snippet": "This second snippet is outside the bound.",
                    },
                ],
                "citations": [
                    citation,
                    {
                        "citation_id": "mail-citation-2",
                        "source_observation_id": "observation-2",
                    },
                ],
            },
            item_limit=1,
        )

        self.assertEqual(len(compact["evidence_snippets"]), 1)
        self.assertEqual(
            compact["evidence_snippets"][0]["snippet"],
            "The governed mail snippet.",
        )
        self.assertNotIn("raw_path", json.dumps(compact, ensure_ascii=False))
        self.assertEqual(len(compact["citations"]), 1)
        self.assertEqual(compact["citations"][0]["citation_id"], "mail-citation-1")
        self.assertEqual(
            compact["citations"][0]["source_observation_id"],
            "observation-1",
        )

    def test_selected_mail_descriptor_drives_responses_and_app_server_tools(self) -> None:
        descriptor = _actual_mail_tool_descriptor()
        citation_id = "mail-citation-provider"
        capability_summary = {
            "source_families": ["mail"],
            "mail_selector_kind": "mail_import_session_id",
            "authorized_mail_import_session_ids": ["mail-session-1"],
        }
        evidence_result = {
            "status": "ok",
            "query_hash": "sha256:mail-query",
            "mail_import_session_id": "mail-session-1",
            "evidence_snippets": [
                {
                    "source_type": "mail_body_segment",
                    "source_observation_id": "observation-1",
                    "mail_import_session_id": "mail-session-1",
                    "email_message_id": "message-1",
                    "message_occurrence_id": "occurrence-1",
                    "subject": "Launch checklist",
                    "snippet": "The governed mail snippet.",
                }
            ],
            "citations": [
                {
                    "citation_id": citation_id,
                    "source_type": "mail_body_segment",
                    "source_observation_id": "observation-1",
                    "mail_import_session_id": "mail-session-1",
                    "email_message_id": "message-1",
                    "message_occurrence_id": "occurrence-1",
                }
            ],
        }

        requests = []
        responses_provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-mail-provider",
                            "name": descriptor["name"],
                            "arguments": json.dumps(
                                {
                                    "query_text": (
                                        "Find the authorized launch checklist " "mail evidence."
                                    ),
                                    "required_terms": ["launch checklist"],
                                    "mail_import_session_id": "mail-session-1",
                                    "limit": 1,
                                }
                            ),
                        }
                    ],
                }
            tool_outputs = [
                item for item in payload["input"] if item.get("type") == "function_call_output"
            ]
            self.assertTrue(tool_outputs)
            tool_output = json.loads(tool_outputs[-1]["output"])
            self.assertEqual(
                tool_output["data"]["evidence_snippets"][0]["subject"],
                "Launch checklist",
            )
            self.assertEqual(
                tool_output["data"]["citations"][0]["citation_id"],
                citation_id,
            )
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text="The governed mail evidence is cited.",
                    citations=(citation_id,),
                    coverage_status="incomplete",
                    coverage_note="Mail evidence is bounded and incomplete.",
                ),
            }

        with mock.patch.object(
            responses_provider,
            "_request_response",
            side_effect=response,
        ):
            responses_outcome = responses_provider.respond(
                history=(),
                user_text="Summarize the launch checklist mail.",
                latest_evidence=None,
                safety_identifier="selected-mail-responses",
                evidence_tool=mock.Mock(return_value=evidence_result),
                formowl_tool_descriptor=descriptor,
                authorized_capability_summary=capability_summary,
            )

        selected_response_tool = next(
            tool for tool in requests[0]["tools"] if tool["name"] == descriptor["name"]
        )
        self.assertEqual(selected_response_tool["parameters"], descriptor["inputSchema"])
        self.assertEqual(
            requests[0]["tool_choice"],
            {"type": "function", "name": descriptor["name"]},
        )
        response_instructions = " ".join(requests[0]["instructions"].split()).casefold()
        self.assertEqual(responses_outcome.citation_ids, (citation_id,))
        response_contract_context = " ".join(
            str(item.get("content", ""))
            for item in requests[0]["input"]
            if item.get("role") == "developer"
        )
        response_contract_context = " ".join(response_contract_context.split()).casefold()

        transport = _RecordingTransport(
            calls=(
                {
                    "query_text": "Find the authorized launch checklist mail evidence.",
                    "required_terms": ["launch checklist"],
                    "mail_import_session_id": "mail-session-1",
                    "limit": 1,
                },
            ),
            final_message=_decision(
                answer_text="The governed mail evidence is cited.",
                citations=(citation_id,),
                coverage_status="incomplete",
                coverage_note="Mail evidence is bounded and incomplete.",
            ),
        )
        with tempfile.TemporaryDirectory() as workspace:
            app_provider = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            app_outcome = app_provider.respond(
                history=(),
                user_text="Summarize the launch checklist mail.",
                latest_evidence=None,
                safety_identifier="selected-mail-app-server",
                evidence_tool=mock.Mock(return_value=evidence_result),
                formowl_tool_descriptor=descriptor,
                authorized_capability_summary=capability_summary,
            )

        selected_app_tool = transport.thread_start["dynamic_tools"][0]
        self.assertEqual(selected_app_tool["name"], descriptor["name"])
        self.assertEqual(selected_app_tool["inputSchema"], descriptor["inputSchema"])
        app_server_instructions = (
            transport.thread_start["base_instructions"]
            + " "
            + transport.thread_start["developer_instructions"]
        )
        app_server_instructions = " ".join(app_server_instructions.split()).casefold()
        app_server_contract_context = " ".join(
            json.dumps(
                transport.turn_call["additional_context"],
                ensure_ascii=False,
            ).split()
        ).casefold()
        for instructions in (response_instructions, app_server_instructions):
            for phrase in (
                "required_terms",
                "1-8 literal identity and genuine topic terms",
                "all terms are conjunctive",
                "same candidate evidence item",
                "authorized selector and request_contract determine source-family/scope",
                "operation/action words are routing semantics",
                "unless the user explicitly requests those literal words",
                "copy its original_query_hash, query_class, and maximum_claim_strength",
                "do not send graph-only table_query, exact-inventory, or cursor arguments",
            ):
                with self.subTest(instruction_phrase=phrase):
                    self.assertIn(phrase, instructions)
            self.assertNotIn(
                "do not send graph-only table_query, request_contract",
                instructions,
            )
        for context in (response_contract_context, app_server_contract_context):
            self.assertIn("formowl_uat_turn_request_contract_boundary_v1", context)
            self.assertIn("original_query_hash", context)
            self.assertIn("query_class", context)
            self.assertIn("maximum_claim_strength", context)
            self.assertIn("copy its original_query_hash", context)
        self.assertNotIn("query_effective_graph_view", response_instructions)
        self.assertNotIn("query_effective_graph_view", app_server_instructions)
        self.assertEqual(
            transport.tool_outputs[0]["data"]["evidence_snippets"][0]["subject"], "Launch checklist"
        )
        self.assertEqual(app_outcome.citation_ids, (citation_id,))

    def test_localhost_responses_stub_runs_selected_mail_tool_loop(self) -> None:
        descriptor = _actual_mail_tool_descriptor()
        citation_id = "mail-citation-local-http"
        received: list[dict[str, object]] = []
        accepted_headers: list[str | None] = []
        evidence_requests: list[UatEvidenceToolRequest] = []
        evidence_result = {
            "status": "ok",
            "query_hash": "sha256:mail-local-http-query",
            "mail_import_session_id": "mail-session-local-http",
            "evidence_snippets": [
                {
                    "source_type": "mail_body_segment",
                    "source_observation_id": "observation-local-http",
                    "mail_import_session_id": "mail-session-local-http",
                    "email_message_id": "message-local-http",
                    "message_occurrence_id": "occurrence-local-http",
                    "snippet": "The governed local HTTP mail snippet.",
                }
            ],
            "citations": [
                {
                    "citation_id": citation_id,
                    "source_type": "mail_body_segment",
                    "source_observation_id": "observation-local-http",
                    "mail_import_session_id": "mail-session-local-http",
                    "email_message_id": "message-local-http",
                    "message_occurrence_id": "occurrence-local-http",
                }
            ],
        }

        class ResponsesStubHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length))
                received.append(payload)
                accepted_headers.append(self.headers.get("Accept"))
                if len(received) == 1:
                    response = {
                        "status": "completed",
                        "output": [
                            {
                                "type": "function_call",
                                "call_id": "call-local-http-mail",
                                "name": descriptor["name"],
                                "arguments": json.dumps(
                                    {
                                        "query_text": (
                                            "Find the authorized local HTTP mail evidence."
                                        ),
                                        "required_terms": ["local HTTP mail evidence"],
                                        "limit": 1,
                                    }
                                ),
                            }
                        ],
                    }
                else:
                    response = {
                        "status": "completed",
                        "output_text": _decision(
                            answer_text=("The governed local HTTP mail evidence is cited."),
                            citations=(citation_id,),
                            coverage_status="incomplete",
                            coverage_note="Mail evidence is bounded and incomplete.",
                        ),
                    }
                is_stream = payload.get("stream") is True
                if is_stream:
                    terminal = {
                        "type": "response.completed",
                        "response": response,
                    }
                    body = (
                        b"event: response.completed\r\n"
                        + b"data: "
                        + json.dumps(terminal).encode("utf-8")
                        + b"\r\n\r\n"
                    )
                    content_type = "text/event-stream"
                else:
                    body = json.dumps(response).encode("utf-8")
                    content_type = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), ResponsesStubHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        provider = CodexResponsesConversationModel(
            base_url=f"http://127.0.0.1:{server.server_address[1]}/v1",
            api_key="synthetic-local-http-provider-key",
            model="gpt-5.6-luna",
            reasoning_effort="max",
        )

        def evidence_tool(request: UatEvidenceToolRequest) -> dict[str, object]:
            evidence_requests.append(request)
            return evidence_result

        try:
            outcome = provider.respond(
                history=(),
                user_text="Summarize the local HTTP mail evidence.",
                latest_evidence=None,
                safety_identifier="local-http-provider-session",
                evidence_tool=evidence_tool,
                formowl_tool_descriptor=descriptor,
                authorized_capability_summary={
                    "source_families": ["mail"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["mail-session-local-http"],
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

        self.assertEqual(len(received), 2)
        self.assertEqual(len(evidence_requests), 1)
        request = evidence_requests[0]
        self.assertEqual(request.tool_name, "query_mail_evidence")
        self.assertEqual(request.query_text, "Find the authorized local HTTP mail evidence.")
        self.assertEqual(request.mail_import_session_id, "mail-session-local-http")
        self.assertEqual(request.required_terms, ("local http mail evidence",))
        self.assertEqual(request.limit, 1)
        self.assertFalse(received[0].get("stream", False))
        self.assertTrue(received[1]["stream"])
        self.assertEqual(accepted_headers, ["application/json", "text/event-stream"])
        self.assertEqual(
            received[0]["tool_choice"], {"type": "function", "name": descriptor["name"]}
        )
        selected_tool = next(
            tool for tool in received[0]["tools"] if tool["name"] == descriptor["name"]
        )
        self.assertEqual(selected_tool["parameters"], descriptor["inputSchema"])
        self.assertIn(descriptor["name"], received[0]["instructions"])
        self.assertNotIn("query_effective_graph_view", received[0]["instructions"])
        tool_output = json.loads(received[1]["input"][-1]["output"])
        self.assertEqual(tool_output["trust"], "untrusted_evidence")
        self.assertEqual(
            tool_output["data"]["evidence_snippets"][0]["snippet"],
            "The governed local HTTP mail snippet.",
        )
        self.assertEqual(
            tool_output["data"]["citations"][0]["citation_id"],
            citation_id,
        )
        self.assertEqual(
            tool_output["data"]["evidence_snippets"][0]["mail_import_session_id"],
            "mail-session-local-http",
        )
        self.assertNotIn("raw_path", json.dumps(tool_output))
        self.assertNotIn("synthetic-local-http-provider-key", json.dumps(tool_output))
        self.assertEqual(outcome.citation_ids, (citation_id,))
        self.assertEqual(outcome.coverage_status, "incomplete")

    def test_browser_projection_uses_recursive_governed_citation_authority(self) -> None:
        citation = "citation-nested-retained-result"
        prior_evidence = {
            "status": "partial",
            "results": [
                {
                    "status": "partial",
                    "exact_inventory": {
                        "items": [
                            {
                                "structured_values": [
                                    {
                                        "field": "source-field",
                                        "value": "source-value",
                                        "citation_hash": citation,
                                    }
                                ]
                            }
                        ]
                    },
                }
            ],
        }
        outcome = UatConversationOutcome(
            response_kind="render_prior_evidence",
            answer_text="Retained governed evidence.",
            display_format="narrative",
            model_name="synthetic-provider",
            citation_ids=(citation,),
            coverage_status="incomplete",
            coverage_note="The retained evidence remains incomplete.",
        )

        self.assertEqual(evidence_citation_ids(prior_evidence), (citation,))
        projected = _browser_projection(outcome, (), latest_evidence=prior_evidence)
        diagnostic = projected.pop("diagnostic", None)
        if diagnostic is not None:
            self.assertEqual(diagnostic, _unbound_diagnostic())
        self.assertEqual(
            projected,
            {
                "status": "partial",
                "answer": "Retained governed evidence.",
                "citations": [citation],
                "clarification": "The retained evidence remains incomplete.",
            },
        )
        unavailable = UatConversationOutcome(
            response_kind="render_prior_evidence",
            answer_text="Unavailable evidence must not render.",
            display_format="narrative",
            model_name="synthetic-provider",
            citation_ids=("citation-not-returned",),
            coverage_status="incomplete",
            coverage_note="The requested evidence is unavailable.",
        )
        with self.assertRaisesRegex(
            ValueError,
            "cited evidence that was not returned",
        ):
            _browser_projection(
                unavailable,
                (),
                latest_evidence=prior_evidence,
            )

    def test_citations_do_not_complete_missing_requested_field_union(self) -> None:
        citations = (
            "citation-requested-field-a",
            "citation-requested-field-b",
        )
        single_outcome = UatConversationOutcome(
            response_kind="answer",
            answer_text="source-backed but incomplete",
            display_format="narrative",
            model_name="synthetic-provider",
            citation_ids=citations[:1],
            coverage_status="complete",
        )
        first = {
            "status": "replan_required",
            "coverage": {"status": "complete", "coverage_status": "complete"},
            "citations": [citations[0]],
            "query_agent": {
                "status": "replan_required",
                "stop_reason": "external_replan_required",
                "request_contract": {
                    "request_contract_fingerprint": "sha256:frozen-task",
                    "requested_field_count": 2,
                    "requested_field_hashes": ["sha256:field-a", "sha256:field-b"],
                },
                "context_bundle": {
                    "successful_subquery_count": 1,
                    "citation_hashes": [citations[0]],
                    "missing_field_hashes": ["sha256:field-b"],
                },
            },
        }
        second = copy.deepcopy(first)
        second["citations"] = [citations[1]]
        second["query_agent"]["context_bundle"] = {
            "successful_subquery_count": 1,
            "citation_hashes": [citations[1]],
            "missing_field_hashes": ["sha256:field-a"],
        }

        with self.assertRaisesRegex(ValueError, "hid incomplete coverage"):
            _browser_projection(single_outcome, (first,), latest_evidence=None)

        combined_outcome = UatConversationOutcome(
            **{
                **single_outcome.__dict__,
                "citation_ids": citations,
            }
        )
        self.assertEqual(
            _browser_projection(
                combined_outcome,
                (first, second),
                latest_evidence=None,
            )["status"],
            "complete",
        )

        mismatched = copy.deepcopy(second)
        mismatched["query_agent"]["request_contract"]["request_contract_fingerprint"] = (
            "sha256:different-task"
        )
        with self.assertRaisesRegex(ValueError, "hid incomplete coverage"):
            _browser_projection(
                combined_outcome,
                (first, mismatched),
                latest_evidence=None,
            )

    def test_temporary_backend_keeps_bounded_transcript_and_rotates_on_reset(self) -> None:
        class ConversationModel:
            model_name = "synthetic-session-model"

            def __init__(self) -> None:
                self.calls = []
                self.discarded = []

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
                    latest_evidence,
                    evidence_tool,
                    formowl_tool_descriptor,
                    authorized_capability_summary,
                )
                self.calls.append((tuple(history), user_text, safety_identifier))
                if user_text == "fail":
                    raise RuntimeError("synthetic failed turn")
                return UatConversationOutcome(
                    response_kind="answer",
                    answer_text=f"answer:{user_text}",
                    display_format="narrative",
                    model_name=self.model_name,
                )

            def discard_conversation(self, safety_identifier):
                self.discarded.append(safety_identifier)

            def close(self):
                return None

        from starlette.applications import Starlette

        model = ConversationModel()
        with Issue56TemporaryLanQueryService(
            SimpleNamespace(app=Starlette()),
            conversation_model=model,
        ) as service:
            session_id, _max_age = service.ensure_browser_session(None)
            service.ask("first", session_id=session_id)
            service.ask("follow-up", session_id=session_id)
            before_failure = service.read_browser_conversation(session_id)

            with self.assertRaisesRegex(RuntimeError, "synthetic failed turn"):
                service.ask("fail", session_id=session_id)

            after_failure = service.read_browser_conversation(session_id)
            self.assertEqual(after_failure["turns"][:2], before_failure["turns"])
            self.assertEqual(
                after_failure["turns"][2],
                {
                    "prompt": "fail",
                    "response": {
                        "status": "error",
                        "answer": "查詢失敗，請稍後再試。",
                        "citations": [],
                        "clarification": None,
                        "diagnostic": _unbound_diagnostic(),
                    },
                },
            )
            self.assertEqual(
                [turn["prompt"] for turn in before_failure["turns"]],
                ["first", "follow-up"],
            )
            self.assertEqual(len(model.calls[1][0]), 2)
            service.ask("after-failure", session_id=session_id)
            self.assertEqual(len(model.calls[-1][0]), 4)

            new_session_id, max_age = service.reset_browser_conversation(session_id)
            self.assertNotEqual(new_session_id, session_id)
            self.assertEqual(max_age, 60 * 60)
            with self.assertRaises(PermissionError):
                service.read_browser_conversation(session_id)
            self.assertEqual(
                service.read_browser_conversation(new_session_id),
                {"turns": []},
            )
            service.ask("new", session_id=new_session_id)
            self.assertEqual(model.calls[-1][0], ())
            for index in range(65):
                service.ask(f"visible-{index}", session_id=new_session_id)
            visible_turns = service.read_browser_conversation(new_session_id)["turns"]
            self.assertEqual(len(visible_turns), 64)
            self.assertEqual(visible_turns[0]["prompt"], "visible-1")
            self.assertEqual(visible_turns[-1]["prompt"], "visible-64")

    def test_temporary_backend_does_not_hold_session_lock_during_provider_wait(self) -> None:
        class BlockingConversationModel:
            model_name = "synthetic-session-model"

            def __init__(self) -> None:
                self.started = threading.Event()
                self.release = threading.Event()

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
                    evidence_tool,
                    formowl_tool_descriptor,
                    authorized_capability_summary,
                )
                self.started.set()
                if not self.release.wait(timeout=5):
                    raise AssertionError("synthetic provider did not release")
                return UatConversationOutcome(
                    response_kind="answer",
                    answer_text="answer",
                    display_format="narrative",
                    model_name=self.model_name,
                )

            def discard_conversation(self, safety_identifier):
                del safety_identifier

            def close(self):
                return None

        from starlette.applications import Starlette

        model = BlockingConversationModel()
        with Issue56TemporaryLanQueryService(
            SimpleNamespace(app=Starlette()),
            conversation_model=model,
        ) as service:
            session_id, _max_age = service.ensure_browser_session(None)
            worker = threading.Thread(
                target=service.ask,
                kwargs={"prompt": "blocked provider", "session_id": session_id},
            )
            worker.start()
            self.assertTrue(model.started.wait(timeout=5))
            self.assertTrue(service.is_browser_session_authenticated(session_id))
            self.assertEqual(
                service.read_browser_conversation(session_id),
                {"turns": []},
            )
            model.release.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())

    def test_direct_responses_provider_runs_one_citation_bound_tool_loop(self) -> None:
        api_key = "synthetic-direct-provider-key"
        raw_prompt = "紅色零件庫存"
        expanded_query = "查詢授權來源中紅色零件目前的庫存數量與相關證據"
        citation = "citation-direct-provider"
        capabilities = {
            "source_families": ["attachment_table", "mail"],
        }
        requests = []
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key=api_key,
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-direct-1",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {
                                    "query_text": expanded_query,
                                    "table_query": None,
                                    "request_contract": {
                                        "original_query_hash": "sha256:" + ("0" * 64),
                                        "query_class": "exact_set_or_inventory",
                                        "source_family_scope": ["mail"],
                                        "requested_fields": ["庫存"],
                                        "maximum_claim_strength": ("complete_authorized_scope"),
                                    },
                                }
                            ),
                        }
                    ],
                }
            tool_output = json.loads(payload["input"][-1]["output"])
            self.assertEqual(tool_output["trust"], "untrusted_evidence")
            self.assertIn(citation, json.dumps(tool_output, sort_keys=True))
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text=f"bounded answer [{citation}]",
                    citations=(citation,),
                    coverage_status="complete",
                ),
            }

        evidence_tool = mock.Mock(
            return_value={
                "status": "complete",
                "coverage": {"status": "complete", "coverage_status": "complete"},
                "exact_inventory": {
                    "status": "complete",
                    "coverage_status": "complete",
                    "returned_count": 1,
                    "total_count": 1,
                    "items": [
                        {
                            "item_hash": "item-direct-provider",
                            "structure_status": "source_provided",
                            "structured_values": [
                                {
                                    "field": "Requested Field",
                                    "value": "source-backed value",
                                    "citation_hash": citation,
                                }
                            ],
                            "governed_references": [{"citation_hash": citation}],
                        }
                    ],
                },
                "citations": [citation],
            }
        )
        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text=raw_prompt,
                latest_evidence=None,
                safety_identifier="direct-provider-session",
                evidence_tool=evidence_tool,
                authorized_capability_summary=capabilities,
            )

        self.assertEqual(len(requests), 2)
        tool = requests[0]["tools"][0]
        expected_tool = _actual_query_tool_descriptor()
        self.assertEqual(tool["name"], "query_effective_graph_view")
        self.assertEqual(tool["parameters"], expected_tool["inputSchema"])
        self.assertFalse(tool["strict"])
        self.assertEqual(tool["parameters"]["required"], ["query_text"])
        typed_table = tool["parameters"]["properties"]["table_query"]
        self.assertEqual(typed_table["properties"]["filters"]["maxItems"], 4)
        self.assertEqual(
            typed_table["properties"]["projection_fields"]["maxItems"],
            8,
        )
        self.assertEqual(
            requests[0]["text"]["format"]["schema"]["properties"]["citation_ids"]["maxItems"],
            24,
        )
        self.assertEqual(
            requests[0]["tool_choice"],
            {"type": "function", "name": "query_effective_graph_view"},
        )
        self.assertFalse(requests[0]["parallel_tool_calls"])
        self.assertIn(
            "A terse or telegraphic factual/business lookup is not ambiguous",
            requests[0]["instructions"],
        )
        self.assertIn(
            "use typed table_query",
            requests[0]["instructions"],
        )
        self.assertIn(
            "authorized source-validated candidate",
            requests[0]["instructions"],
        )
        self.assertIn(
            "every replan must preserve the user's original source family",
            requests[0]["instructions"],
        )
        self.assertIn(
            'Never add "all", "every", "所有"',
            requests[0]["instructions"],
        )
        self.assertIn("gratuitous description", requests[0]["instructions"])
        self.assertEqual(tool["description"], expected_tool["description"])
        self.assertNotIn(
            "render_prior_evidence",
            requests[0]["text"]["format"]["schema"]["properties"]["response_kind"]["enum"],
        )
        requested = evidence_tool.call_args.args[0]
        self.assertEqual(requested.query_text, expanded_query)
        self.assertIsNone(requested.table_query)
        self.assertNotEqual(requested.query_text, raw_prompt)
        self.assertEqual(
            requested.request_contract,
            {
                "original_query_hash": (
                    "sha256:" + hashlib.sha256(raw_prompt.encode()).hexdigest()
                ),
                "query_class": "evidence_lookup",
                "source_family_scope": ["attachment_table", "mail"],
                "requested_fields": ["庫存"],
                "maximum_claim_strength": "cited_evidence",
            },
        )
        self.assertTrue(
            any(
                item.get("role") == "developer"
                and "formowl_uat_turn_request_contract_boundary_v1" in item.get("content", "")
                for item in requests[0]["input"]
            )
        )
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(outcome.coverage_status, "complete")
        self.assertEqual(len(outcome.tool_requests), 1)
        self.assertNotIn(api_key, json.dumps(requests, sort_keys=True))

    def test_direct_provider_records_bounded_citation_stage_diagnostics(self) -> None:
        citation_ids = ("citation-diagnostic-a", "citation-diagnostic-b")
        requests = []
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-diagnostic-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-diagnostic-1",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {
                                    "query_text": "bounded authorized evidence lookup",
                                    "table_query": None,
                                }
                            ),
                        }
                    ],
                }
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text="bounded cited answer",
                    citations=(citation_ids[0],),
                    coverage_status="incomplete",
                    coverage_note="The evidence is bounded.",
                ),
            }

        evidence_tool = mock.Mock(
            return_value={
                "status": "partial",
                "query_hash": "sha256:diagnostic-query",
                "citations": list(citation_ids),
                "evidence_snippets": [
                    {
                        "source_type": "mail_body_segment",
                        "source_observation_id": "observation-diagnostic",
                        "email_message_id": "private-mail-id",
                        "snippet": "private mail body",
                    }
                ],
            }
        )
        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text="Summarize the authorized evidence.",
                latest_evidence=None,
                safety_identifier="citation-stage-diagnostic-session",
                evidence_tool=evidence_tool,
            )

        diagnostic = dict(outcome.provider_diagnostic or {})
        attempts = diagnostic["provider_attempts"]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["attempt"], 1)
        self.assertEqual(attempts[0]["outcome"], "completed")
        self.assertEqual(attempts[0]["response_status"], "completed")
        self.assertEqual(attempts[0]["function_call_count"], 1)
        self.assertEqual(attempts[0]["tool_choice"]["tool_choice"], "required_function")
        self.assertEqual(attempts[1]["tool_choice"]["tool_choice"], "auto")
        self.assertTrue(all(item["elapsed_ms"] >= 0 for item in attempts))

        stages = diagnostic["mcp_citation_stages"]
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["raw_governed"]["citation_count"], 2)
        self.assertEqual(stages[0]["compacted_presented"]["citation_count"], 2)
        self.assertEqual(stages[0]["projection_result"], "preserved")

        finalization = diagnostic["finalization_validation"]
        self.assertEqual(len(finalization), 1)
        self.assertEqual(finalization[0]["final_model"]["citation_count"], 1)
        self.assertEqual(finalization[0]["available_governed"]["citation_count"], 2)
        self.assertEqual(finalization[0]["validation_result"], "passed")
        self.assertFalse(finalization[0]["repair_attempted"])

        rendered = json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("private mail body", rendered)
        self.assertNotIn("private-mail-id", rendered)
        self.assertNotIn("synthetic-diagnostic-provider-key", rendered)
        self.assertNotIn("/private/", rendered)
        for fingerprint in (
            attempts[0]["tool_choice"]["offered_tool_fingerprint"],
            stages[0]["raw_governed"]["citation_fingerprint"],
            stages[0]["compacted_presented"]["citation_fingerprint"],
            finalization[0]["final_model"]["citation_fingerprint"],
            finalization[0]["available_governed"]["citation_fingerprint"],
        ):
            self.assertRegex(fingerprint, r"^sha256:[0-9a-f]{64}$")

    def test_direct_provider_retains_fourth_finalization_repair_diagnostic(self) -> None:
        citation_id = "citation-fourth-repair"
        requests = []
        clock = [1_000.0]
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-fourth-repair-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) <= 2:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": f"call-fourth-repair-{len(requests)}",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {
                                    "query_text": f"bounded evidence query {len(requests)}",
                                    "table_query": None,
                                }
                            ),
                        }
                    ],
                }
            if len(requests) == 3:
                return {
                    "status": "completed",
                    "output_text": _decision(
                        answer_text="A cited summary.",
                        citations=("citation-not-present",),
                        coverage_status="incomplete",
                        coverage_note="The source coverage is bounded.",
                    ),
                }
            clock[0] += 68.703
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text="A repaired cited summary.",
                    citations=(citation_id,),
                    coverage_status="incomplete",
                    coverage_note="The source coverage is bounded.",
                ),
            }

        evidence_tool = mock.Mock(
            side_effect=[
                {
                    "status": "pending_review",
                    "query_hash": "sha256:first-bounded-query",
                    "citations": [],
                },
                {
                    "status": "partial",
                    "query_hash": "sha256:second-bounded-query",
                    "coverage": {
                        "status": "incomplete",
                        "coverage_status": "incomplete",
                    },
                    "citations": [citation_id],
                    "results": [
                        {
                            "source_observation_id": "observation-fourth-repair",
                            "citation_id": citation_id,
                            "lineage_id": "lineage-fourth-repair",
                            "text": "bounded synthetic evidence",
                        }
                    ],
                },
            ]
        )

        with (
            mock.patch(
                "formowl_mail.human_uat_orchestrator.time.monotonic",
                side_effect=lambda: clock[0],
            ),
            mock.patch.object(provider, "_request_response", side_effect=response),
        ):
            outcome = provider.respond(
                history=(),
                user_text="Summarize the authorized evidence.",
                latest_evidence=None,
                safety_identifier="fourth-repair-diagnostic-session",
                evidence_tool=evidence_tool,
            )

        self.assertEqual(len(requests), 4)
        self.assertEqual(evidence_tool.call_count, 2)
        self.assertEqual(outcome.citation_ids, (citation_id,))
        diagnostic = outcome.provider_diagnostic
        self.assertEqual(diagnostic["provider_attempt_count"], 4)
        self.assertEqual(
            [item["attempt"] for item in diagnostic["provider_attempts"]],
            [2, 3, 4],
        )
        self.assertEqual(diagnostic["provider_attempts"][-1]["elapsed_ms"], 68_703)
        self.assertEqual(
            [item["attempt"] for item in diagnostic["provider_phase_timings"]],
            [2, 3, 4],
        )
        self.assertEqual(diagnostic["provider_phase_timings"][-1]["elapsed_ms"], 68_703)
        self.assertEqual(
            [item["validation_result"] for item in diagnostic["finalization_validation"]],
            ["citation_rejected", "passed"],
        )
        self.assertTrue(diagnostic["finalization_validation"][-1]["repair_attempted"])

        from formowl_mail.human_uat_http import _safe_provider_diagnostic

        projected = _safe_provider_diagnostic(diagnostic)
        self.assertEqual(projected["provider_attempt_count"], 4)
        self.assertEqual(
            [item["attempt"] for item in projected["provider_attempts"]],
            [2, 3, 4],
        )
        self.assertEqual(projected["provider_attempts"][-1]["elapsed_ms"], 68_703)
        self.assertEqual(
            projected["provider_phase_timings"][-1]["elapsed_ms"],
            68_703,
        )
        self.assertNotIn("synthetic-fourth-repair-key", json.dumps(projected))

    def test_provider_loop_diagnostics_project_safely_at_public_boundaries(self) -> None:
        from formowl_mail.human_uat_http import _safe_provider_diagnostic as http_project

        raw = {
            "provider_attempt_count": 4,
            "provider_phase_timings": [
                {
                    "phase": "provider_request",
                    "attempt": index,
                    "elapsed_ms": 68_703 if index == 4 else 10,
                }
                for index in range(1, 5)
            ],
            "provider_attempts": [
                {
                    "attempt": index,
                    "phase": "provider_request",
                    "elapsed_ms": 68_703 if index == 4 else 3.5,
                    "outcome": "completed",
                    "response_status": "completed",
                    "function_call_count": 1,
                    "tool_choice": {
                        "tool_choice": "required_function",
                        "selected_tool": "query_mail_evidence",
                        "offered_tool_count": 1,
                        "offered_tool_fingerprint": "sha256:" + ("a" * 64),
                    },
                }
                for index in range(2, 5)
            ],
            "mcp_citation_stages": [
                {
                    "call_index": 1,
                    "elapsed_ms": 4,
                    "raw_governed": {
                        "citation_count": 2,
                        "citation_fingerprint": "sha256:" + ("b" * 64),
                    },
                    "compacted_presented": {
                        "citation_count": 1,
                        "citation_fingerprint": "sha256:" + ("c" * 64),
                    },
                    "projection_result": "reduced",
                }
            ],
            "finalization_validation": [
                {
                    "final_model": {
                        "citation_count": 0,
                        "citation_fingerprint": "sha256:" + ("d" * 64),
                    },
                    "available_governed": {
                        "citation_count": 2,
                        "citation_fingerprint": "sha256:" + ("e" * 64),
                    },
                    "validation_result": "citation_rejected",
                    "repair_attempted": True,
                }
            ],
            "provider_body": "must not project",
            "prompt": "must not project",
            "mail_message_id": "must not project",
            "raw_path": "/must/not/project",
        }

        projected = safe_provider_loop_diagnostics(raw)
        self.assertEqual(
            [item["attempt"] for item in projected["provider_attempts"]],
            [2, 3, 4],
        )
        self.assertEqual(projected["provider_attempts"][-1]["elapsed_ms"], 68_703)
        self.assertEqual(projected["provider_attempt_count"], 4)
        self.assertEqual(
            projected["mcp_citation_stages"][0]["raw_governed"]["citation_count"],
            2,
        )
        self.assertEqual(
            projected["finalization_validation"][0]["validation_result"],
            "citation_rejected",
        )
        rendered = json.dumps(projected, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("must not project", rendered)
        self.assertNotIn("/must/not/project", rendered)

        runtime_bounded = runtime_project(raw)
        self.assertEqual(
            [item["attempt"] for item in runtime_bounded["provider_attempts"]],
            [2, 3, 4],
        )
        self.assertEqual(runtime_bounded["provider_attempt_count"], 4)
        self.assertEqual(
            [item["elapsed_ms"] for item in runtime_bounded["provider_phase_timings"]],
            [10, 10, 68_703],
        )
        for bounded in (
            http_project(raw),
            http_project(runtime_bounded),
        ):
            self.assertEqual(
                bounded["provider_attempts"][0]["tool_choice"]["tool_choice"],
                "required_function",
            )
            self.assertEqual(
                [item["attempt"] for item in bounded["provider_attempts"]],
                [2, 3, 4],
            )
            self.assertEqual(bounded["provider_attempt_count"], 4)
            self.assertEqual(len(bounded["provider_phase_timings"]), 3)
            self.assertEqual(bounded["provider_phase_timings"][-1]["elapsed_ms"], 68_703)
            self.assertEqual(
                bounded["finalization_validation"][0]["final_model"]["citation_count"],
                0,
            )
            self.assertNotIn("provider_body", json.dumps(bounded))

        malformed_provider_tail = {
            **raw,
            "provider_attempts": [
                *raw["provider_attempts"][:2],
                {
                    **raw["provider_attempts"][-1],
                    "outcome": "not-allowlisted",
                },
            ],
        }
        malformed_validation_tail = {
            **raw,
            "finalization_validation": [
                {
                    **raw["finalization_validation"][0],
                    "validation_result": "passed",
                    "repair_attempted": False,
                },
                {
                    **raw["finalization_validation"][0],
                    "validation_result": "passed",
                    "repair_attempted": "malformed",
                },
            ],
        }
        for project in (runtime_project, http_project):
            with self.subTest(project=project.__module__ if hasattr(project, "__module__") else "runtime"):
                self.assertEqual(
                    project(malformed_provider_tail)["provider_attempts"],
                    [],
                )
            self.assertEqual(
                project(malformed_validation_tail)["finalization_validation"],
                    [],
                )

        missing_count = {"provider_attempts": raw["provider_attempts"]}
        self.assertEqual(
            safe_provider_loop_diagnostics(missing_count),
            {"provider_attempts": [], "provider_attempts_valid": False},
        )
        runtime_missing_count = runtime_project(missing_count)
        self.assertEqual(runtime_missing_count["provider_attempts"], [])
        self.assertNotIn("provider_attempt_count", runtime_missing_count)
        http_missing_count = http_project(missing_count)
        self.assertNotIn("provider_attempt_count", http_missing_count)

    def test_runtime_drops_untrusted_provider_attempt_shape_before_public_projection(self) -> None:
        unsafe_loop = {
            "provider_attempts": [
                {
                    "attempt": 1,
                    "phase": "provider_request",
                    "elapsed_ms": 3,
                    "outcome": "completed",
                    "response_status": "completed",
                    "function_call_count": 0,
                    "tool_choice": {
                        "tool_choice": "none",
                        "selected_tool": "none",
                        "offered_tool_count": 0,
                        "offered_tool_fingerprint": "sha256:" + ("a" * 64),
                    },
                    "request_shape": {
                        "item[8]": {
                            "api_key": "private-provider-key",
                            "input": [{"role": "user", "content": "private prompt"}],
                        }
                    },
                }
            ]
        }
        with mock.patch(
            "formowl_gateway.issue56_uat_runtime.safe_provider_loop_diagnostics",
            return_value=unsafe_loop,
        ):
            projected = _with_mcp_diagnostic(
                {
                    "status": "complete",
                    "answer": "safe answer",
                    "citations": [],
                    "clarification": None,
                    "diagnostic": {},
                },
                (),
            )

        diagnostic = projected["diagnostic"]
        self.assertNotIn("provider_attempts", diagnostic)
        rendered = json.dumps(projected, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("private-provider-key", rendered)
        self.assertNotIn("private prompt", rendered)
        self.assertNotIn("item[8]", rendered)

    def test_provider_loop_diagnostics_rejects_malformed_enum_values_safely(self) -> None:
        valid = {
            "attempt": 1,
            "elapsed_ms": 1,
            "outcome": "completed",
            "response_status": "completed",
            "function_call_count": 0,
            "tool_choice": {
                "tool_choice": "none",
                "selected_tool": "none",
                "offered_tool_count": 0,
                "offered_tool_fingerprint": "sha256:" + ("a" * 64),
            },
        }
        for field, malformed in (
            ("outcome", []),
            ("response_status", {"malformed": True}),
        ):
            with self.subTest(field=field):
                raw = dict(valid)
                raw[field] = malformed
                self.assertEqual(
                    safe_provider_loop_diagnostics({"provider_attempts": [raw]}),
                    {"provider_attempts": [], "provider_attempts_valid": False},
                )

        stage = {
            "call_index": 1,
            "elapsed_ms": 1,
            "raw_governed": {
                "citation_count": 0,
                "citation_fingerprint": "sha256:" + ("b" * 64),
            },
            "compacted_presented": {
                "citation_count": 0,
                "citation_fingerprint": "sha256:" + ("c" * 64),
            },
            "projection_result": [],
        }
        validation = {
            "final_model": {
                "citation_count": 0,
                "citation_fingerprint": "sha256:" + ("d" * 64),
            },
            "available_governed": {
                "citation_count": 0,
                "citation_fingerprint": "sha256:" + ("e" * 64),
            },
            "validation_result": {"malformed": True},
            "repair_attempted": False,
        }
        self.assertEqual(
            safe_provider_loop_diagnostics(
                {
                    "mcp_citation_stages": [stage],
                    "finalization_validation": [validation],
                }
            ),
            {"finalization_validation": [], "provider_attempts_valid": False},
        )

    def test_malformed_provider_status_keeps_existing_finalization_flow(self) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-malformed-status-key",
        )
        for malformed_status in ([], {"malformed": True}):
            with self.subTest(status_type=type(malformed_status).__name__):
                with mock.patch.object(
                    provider,
                    "_request_response",
                    return_value={
                        "status": malformed_status,
                        "output_text": _decision(answer_text="normal final answer"),
                    },
                ) as request_response:
                    outcome = provider.respond(
                        history=(),
                        user_text="hello",
                        latest_evidence=None,
                        safety_identifier=f"malformed-status-{type(malformed_status).__name__}",
                        evidence_tool=mock.Mock(),
                    )
                self.assertEqual(request_response.call_count, 1)
                self.assertEqual(outcome.answer_text, "normal final answer")
                self.assertEqual(
                    outcome.provider_diagnostic["provider_attempts"][0]["response_status"],
                    "unknown",
                )

    def test_direct_provider_processes_multiple_function_calls_sequentially(
        self,
    ) -> None:
        citation_ids = ("citation-batch-first", "citation-batch-second")
        requests = []
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-batch-first",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {
                                    "query_text": "first authorized source subquery",
                                    "table_query": None,
                                }
                            ),
                        },
                        {
                            "type": "function_call",
                            "call_id": "call-batch-second",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {
                                    "query_text": "second authorized source subquery",
                                    "table_query": None,
                                }
                            ),
                        },
                    ],
                }
            function_outputs = [
                item for item in payload["input"] if item.get("type") == "function_call_output"
            ]
            self.assertEqual(
                [item["call_id"] for item in function_outputs],
                ["call-batch-first", "call-batch-second"],
            )
            output_payloads = [json.loads(item["output"]) for item in function_outputs]
            self.assertIn(citation_ids[0], json.dumps(output_payloads[0], sort_keys=True))
            self.assertIn(citation_ids[1], json.dumps(output_payloads[1], sort_keys=True))
            self.assertEqual(
                [output["execution_control"]["remaining_mcp_calls"] for output in output_payloads],
                [2, 1],
            )
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text="Both authorized source results are cited.",
                    citations=citation_ids,
                    coverage_status="complete",
                ),
            }

        evidence_tool = mock.Mock(
            side_effect=[
                {
                    "status": "complete",
                    "coverage": {"status": "complete", "coverage_status": "complete"},
                    "citations": [citation_ids[0]],
                },
                {
                    "status": "complete",
                    "coverage": {"status": "complete", "coverage_status": "complete"},
                    "citations": [citation_ids[1]],
                },
            ]
        )
        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text="Retrieve both authorized source results.",
                latest_evidence=None,
                safety_identifier="multiple-function-call-session",
                evidence_tool=evidence_tool,
                authorized_capability_summary={"source_families": ["mail"]},
            )

        self.assertEqual(len(requests), 2)
        self.assertFalse(requests[0]["parallel_tool_calls"])
        self.assertEqual(evidence_tool.call_count, 2)
        self.assertEqual(
            [call.args[0].query_text for call in evidence_tool.call_args_list],
            [
                "first authorized source subquery",
                "second authorized source subquery",
            ],
        )
        self.assertEqual(
            len(
                {
                    json.dumps(call.args[0].request_contract, sort_keys=True)
                    for call in evidence_tool.call_args_list
                }
            ),
            1,
        )
        self.assertEqual(outcome.citation_ids, citation_ids)
        self.assertEqual(len(outcome.tool_requests), 2)

    def test_direct_responses_provider_general_chat_sends_none_without_mcp(self) -> None:
        for index, prompt in enumerate(
            (
                "講個笑話吧",
                "2 加 2 等於多少？",
                "我今天過得很開心",
            )
        ):
            with self.subTest(prompt=prompt):
                provider = CodexResponsesConversationModel(
                    base_url="https://provider.example.test/v1",
                    api_key="synthetic-direct-provider-key",
                    clock=lambda: datetime(
                        2026,
                        9,
                        6,
                        14,
                        30,
                        tzinfo=timezone.utc,
                    ),
                )
                evidence_tool = mock.Mock()
                with mock.patch.object(
                    provider,
                    "_request_response",
                    return_value={
                        "status": "completed",
                        "output_text": _decision(answer_text="hello"),
                    },
                ) as request_response:
                    outcome = provider.respond(
                        history=(),
                        user_text=prompt,
                        latest_evidence=None,
                        safety_identifier=f"general-chat-{index}",
                        evidence_tool=evidence_tool,
                    )

                evidence_tool.assert_not_called()
                self.assertEqual(outcome.answer_text, "hello")
                self.assertEqual(outcome.tool_requests, ())
                request = request_response.call_args.args[0]
                self.assertEqual(request["tools"], [])
                self.assertEqual(request["tool_choice"], "none")
                clock_context = next(
                    item["content"]
                    for item in request["input"]
                    if item.get("role") == "developer"
                    and "Trusted runtime clock context" in item.get("content", "")
                )
                self.assertIn("2026-09-06T22:30:00+08:00", clock_context)
                self.assertIn("timezone is Asia/Taipei", clock_context)
                self.assertIn("weekday is Sunday", clock_context)

    def test_no_tool_payload_preserves_strict_answer_contract_with_explicit_none_tool_choice(
        self,
    ) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        with mock.patch.object(
            provider,
            "_request_response",
            return_value={
                "status": "completed",
                "output_text": _decision(answer_text="hello"),
            },
        ) as request_response:
            provider.respond(
                history=(),
                user_text="hello",
                latest_evidence=None,
                safety_identifier="no-tool-payload-session",
                evidence_tool=mock.Mock(),
            )

        request = request_response.call_args.args[0]
        self.assertEqual(request["tools"], [])
        self.assertEqual(request["tool_choice"], "none")
        self.assertEqual(request["parallel_tool_calls"], False)
        self.assertEqual(request["reasoning"], {"effort": "high"})
        self.assertFalse(request["store"])
        self.assertEqual(request["text"]["format"]["type"], "json_schema")
        self.assertTrue(request["text"]["format"]["strict"])

    def test_tool_choice_none_rejects_forged_function_call_without_mcp(self) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        evidence_tool = mock.Mock()
        with mock.patch.object(
            provider,
            "_request_response",
            return_value={
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "forged-no-tool-call",
                        "name": "query_effective_graph_view",
                        "arguments": json.dumps({"query_text": "must not execute"}),
                    }
                ],
            },
        ) as request_response:
            outcome = provider.respond(
                history=(),
                user_text="hello",
                latest_evidence=None,
                safety_identifier="forged-no-tool-call-session",
                evidence_tool=evidence_tool,
            )

        request = request_response.call_args.args[0]
        self.assertEqual(request["tools"], [])
        self.assertEqual(request["tool_choice"], "none")
        evidence_tool.assert_not_called()
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(outcome.tool_requests, ())
        self.assertEqual(
            outcome.provider_diagnostic["reason_code"],
            "invalid_function_call_shape",
        )

    def test_direct_provider_records_secret_free_phase_timing(self) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        with mock.patch.object(
            provider,
            "_request_response",
            return_value={
                "status": "completed",
                "output_text": _decision(answer_text="bounded answer"),
            },
        ):
            outcome = provider.respond(
                history=(),
                user_text="hello",
                latest_evidence=None,
                safety_identifier="phase-timing-session",
                evidence_tool=mock.Mock(),
            )

        self.assertEqual(outcome.provider_diagnostic["provider_attempt_count"], 1)
        self.assertEqual(
            outcome.provider_diagnostic["provider_phase_timings"][0]["phase"],
            "provider_request",
        )
        self.assertEqual(
            outcome.provider_diagnostic["provider_phase_timings"][0]["attempt"],
            1,
        )
        self.assertEqual(
            outcome.provider_diagnostic["provider_phase_timings"][0]["outcome"],
            "completed",
        )
        self.assertNotIn(
            "synthetic-direct-provider-key",
            json.dumps(outcome.provider_diagnostic, sort_keys=True),
        )

    def test_direct_provider_reserves_return_margin_and_keeps_timeout_evidence(self) -> None:
        for with_evidence in (False, True):
            with self.subTest(with_evidence=with_evidence):
                clock_value = 1_000.0
                observed_timeouts = []
                citation = "citation-generic-bounded-timeout"
                result = {"status": "ok", "citations": [citation]}
                provider = CodexResponsesConversationModel(
                    base_url="https://provider.example.test/v1", api_key="synthetic-key",
                )
                original_context = orchestrator._runtime_clock_context
                original_shape = orchestrator._provider_request_shape_snapshot

                def context(**kwargs):
                    nonlocal clock_value
                    clock_value += 2  # Input preparation is part of the turn.
                    return original_context(**kwargs)

                def shape(payload):
                    nonlocal clock_value
                    clock_value += 3  # Payload preparation must not reset the deadline.
                    return original_shape(payload)

                def response(payload):
                    nonlocal clock_value
                    observed_timeouts.append(provider._active_request_timeout_seconds)
                    if with_evidence and len(observed_timeouts) == 1:
                        return {"status": "completed", "output": [{
                            "type": "function_call", "call_id": "call-bounded-timeout",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps({"query_text": "generic evidence lookup"}),
                        }]}
                    clock_value += provider._active_request_timeout_seconds
                    raise TimeoutError("simulated bounded provider timeout")

                def evidence_tool(request):
                    nonlocal clock_value
                    clock_value += 58
                    return result

                with (
                    mock.patch.object(orchestrator.time, "monotonic", side_effect=lambda: clock_value),
                    mock.patch.object(orchestrator, "_runtime_clock_context", side_effect=context),
                    mock.patch.object(orchestrator, "_provider_request_shape_snapshot", side_effect=shape),
                    mock.patch.object(provider, "_request_response", side_effect=response),
                ):
                    outcome = provider.respond(
                        history=(), user_text="Retrieve authorized evidence." if with_evidence else "Hello.",
                        latest_evidence=None, safety_identifier="generic-timeout-session",
                        evidence_tool=evidence_tool,
                    )
                self.assertEqual(orchestrator._MAX_UAT_TURN_SECONDS, 120.0)
                self.assertEqual(observed_timeouts, [110.0, 49.0] if with_evidence else [110.0])
                self.assertEqual(clock_value, 1_115.0)
                self.assertEqual(outcome.response_kind, "clarification")
                self.assertEqual(outcome.provider_diagnostic["reason_code"], "transport_timeout")
                self.assertTrue(safe_provider_loop_diagnostics(outcome.provider_diagnostic)[
                    "provider_attempts_valid"
                ])
                self.assertEqual(outcome.citation_ids, (citation,) if with_evidence else ())
                self.assertEqual(outcome.tool_results, (result,) if with_evidence else ())
                self.assertEqual(outcome.coverage_status, "incomplete")

    def test_direct_provider_return_margin_stops_new_requests_after_mcp_budget_exhaustion(self) -> None:
        clock_value = 1_000.0
        citation = "citation-generic-budget-exhausted"
        result = {"status": "ok", "citations": [citation]}
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="synthetic-key",
        )

        def evidence_tool(request):
            nonlocal clock_value
            clock_value += 115
            return result

        with (
            mock.patch.object(orchestrator.time, "monotonic", side_effect=lambda: clock_value),
            mock.patch.object(provider, "_request_response", return_value={
                "status": "completed", "output": [{
                    "type": "function_call", "call_id": "call-budget-exhausted",
                    "name": "query_effective_graph_view",
                    "arguments": json.dumps({"query_text": "generic evidence lookup"}),
                }],
            }) as request_response,
        ):
            outcome = provider.respond(
                history=(), user_text="Retrieve authorized evidence.", latest_evidence=None,
                safety_identifier="generic-budget-session", evidence_tool=evidence_tool,
            )
        self.assertEqual(request_response.call_count, 1)
        self.assertEqual(outcome.provider_diagnostic["reason_code"], "turn_budget_exhausted")
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(outcome.tool_results, (result,))
        self.assertEqual(outcome.coverage_status, "incomplete")

    def test_direct_provider_timeout_fails_fast_with_phase(self) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
            timeout_seconds=120,
        )
        with mock.patch.object(
            provider,
            "_request_response",
            side_effect=TimeoutError("provider wait"),
        ):
            outcome = provider.respond(
                history=(),
                user_text="我要 PO470002002 的交期",
                latest_evidence=None,
                safety_identifier="provider-timeout-session",
                evidence_tool=mock.Mock(),
            )

        self.assertEqual(outcome.response_kind, "clarification")
        self.assertIn("受控時間", outcome.answer_text)
        self.assertEqual(
            outcome.provider_diagnostic["reason_code"],
            "transport_timeout",
        )
        self.assertEqual(
            outcome.provider_diagnostic["provider_attempt_count"],
            1,
        )
        self.assertEqual(
            outcome.provider_diagnostic["provider_phase_timings"][0]["outcome"],
            "timeout",
        )
        rendered = json.dumps(outcome.provider_diagnostic, ensure_ascii=False)
        self.assertNotIn("PO470002002", rendered)

    def test_direct_provider_finalizes_after_bounded_slow_mcp_round(self) -> None:
        citation = "citation-slow-mcp-finalization"
        requests = []
        observed_timeouts = []
        clock_value = 1_000.0

        def monotonic():
            return clock_value

        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-slow-mcp-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            observed_timeouts.append(provider._active_request_timeout_seconds)
            if len(requests) == 1:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-slow-mcp",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {"query_text": "bounded slow MCP evidence lookup"}
                            ),
                        }
                    ],
                }
            if provider._active_request_timeout_seconds < 10:
                raise TimeoutError("simulated finalization timeout")
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text="The bounded MCP evidence was finalized.",
                    citations=(citation,),
                    coverage_status="complete",
                ),
            }

        def evidence_tool(_request):
            nonlocal clock_value
            clock_value += 58.0
            return {
                "status": "ok",
                "citations": [citation],
            }

        with (
            mock.patch(
                "formowl_mail.human_uat_orchestrator.time.monotonic",
                side_effect=monotonic,
            ),
            mock.patch.object(provider, "_request_response", side_effect=response),
        ):
            outcome = provider.respond(
                history=(),
                user_text="Retrieve the authorized evidence.",
                latest_evidence=None,
                safety_identifier="slow-mcp-finalization-session",
                evidence_tool=evidence_tool,
            )

        self.assertEqual(len(requests), 2)
        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(outcome.answer_text, "The bounded MCP evidence was finalized.")
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(outcome.coverage_status, "complete")
        self.assertEqual(observed_timeouts, [115.0, 57.0])
        self.assertEqual(
            outcome.provider_diagnostic["finalization_validation"][0]["validation_result"],
            "passed",
        )

    def test_public_term_lookup_is_stateless_then_uses_typed_formowl_query(
        self,
    ) -> None:
        private_identifier = "PRIVATE-123"
        citation = "citation-public-plan-source-evidence"
        requests = []
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                public_tool = next(
                    tool
                    for tool in payload["tools"]
                    if tool.get("name") == "clarify_public_terminology"
                )
                self.assertIn("COO", public_tool["parameters"]["properties"]["term"]["enum"])
                self.assertNotIn("PRIVATE", public_tool["parameters"]["properties"]["term"]["enum"])
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-public-term",
                            "name": "clarify_public_terminology",
                            "arguments": json.dumps({"term": "COO", "domain": "supply_chain"}),
                        }
                    ],
                }
            if payload["tools"] == [{"type": "web_search", "search_context_size": "low"}]:
                rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                self.assertNotIn(private_identifier, rendered)
                self.assertNotIn("safety_identifier", payload)
                self.assertFalse(payload["store"])
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "web_search_call",
                            "id": "web-public-term",
                            "status": "completed",
                        },
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "COO commonly means country of origin in supply-chain use.",
                                    "annotations": [
                                        {
                                            "type": "url_citation",
                                            "url": "https://public.example.test/coo",
                                            "title": "Public terminology",
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                }
            if len(requests) == 3:
                public_output = json.loads(payload["input"][-1]["output"])
                self.assertEqual(
                    public_output["trust"],
                    "untrusted_public_terminology",
                )
                self.assertFalse(public_output["business_evidence"])
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-formowl-after-public-term",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {
                                    "query_text": (
                                        "Find the authorized country-of-origin value "
                                        f"for {private_identifier}."
                                    ),
                                    "table_query": {
                                        "filters": [
                                            {
                                                "field": "MPN",
                                                "value": private_identifier,
                                            }
                                        ],
                                        "projection_fields": ["COO"],
                                    },
                                }
                            ),
                        }
                    ],
                }
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text="source-backed answer",
                    citations=(citation,),
                    coverage_status="complete",
                ),
            }

        evidence_tool = mock.Mock(
            return_value={
                "status": "complete",
                "coverage": {"status": "complete", "coverage_status": "complete"},
                "citations": [citation],
            }
        )
        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text=f"{private_identifier} 的 COO 是什麼？",
                latest_evidence=None,
                safety_identifier="public-term-session",
                evidence_tool=evidence_tool,
            )

        requested = evidence_tool.call_args.args[0]
        self.assertEqual(requested.table_query["filters"][0]["value"], private_identifier)
        self.assertEqual(requested.table_query["projection_fields"], ["COO"])
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(len(outcome.tool_requests), 1)
        self.assertEqual(len(requests), 4)

    def test_repeated_whitespace_query_stops_without_second_mcp_call(self) -> None:
        requests = []
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                query_text = "CN 的 料號"
            elif len(requests) == 2:
                query_text = "CN的料號"
            else:
                return {
                    "status": "completed",
                    "output_text": _decision(
                        answer_text="unsupported uncited draft",
                        coverage_status="complete",
                    ),
                }
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": f"call-repeat-{len(requests)}",
                        "name": "query_effective_graph_view",
                        "arguments": json.dumps({"query_text": query_text, "table_query": None}),
                    }
                ],
            }

        evidence_tool = mock.Mock(
            return_value={
                "status": "replan_required",
                "citations": [],
                "query_agent": {
                    "status": "replan_required",
                    "external_replan": {
                        "status": "required",
                        "reason_code": "free_text_directional_binding_invalid",
                    },
                },
            }
        )
        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text="列出產地是 CN 的料號",
                latest_evidence=None,
                safety_identifier="no-repeat-session",
                evidence_tool=evidence_tool,
            )

        evidence_tool.assert_called_once()
        duplicate_control = json.loads(requests[2]["input"][-1]["output"])
        self.assertEqual(
            duplicate_control["execution_control"]["stop_reason"],
            "no_progress",
        )
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertIn("停止無效重試", outcome.answer_text)
        self.assertEqual(len(outcome.tool_requests), 1)

    def test_distinct_rejection_feedback_allows_third_candidate_call(self) -> None:
        citation = "citation-third-candidate"
        requests = []
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) <= 3:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": f"call-distinct-{len(requests)}",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {
                                    "query_text": f"preserved mail goal {len(requests)}",
                                    "table_query": None,
                                }
                            ),
                        }
                    ],
                }
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text="source-backed candidate result",
                    citations=(citation,),
                    coverage_status="complete",
                ),
            }

        evidence_tool = mock.Mock(
            side_effect=[
                {
                    "status": "replan_required",
                    "citations": [],
                    "query_agent": {
                        "status": "replan_required",
                        "subqueries": [
                            {
                                "status": "rejected",
                                "rejection_reason_code": ("free_text_directional_binding_invalid"),
                                "missing_field_hashes": ["sha256:field-a"],
                            }
                        ],
                        "external_replan": {
                            "status": "required",
                            "rejection_reason_codes": ["free_text_directional_binding_invalid"],
                        },
                    },
                },
                {
                    "status": "replan_required",
                    "citations": [],
                    "query_agent": {
                        "status": "replan_required",
                        "subqueries": [
                            {
                                "status": "rejected",
                                "rejection_reason_code": (
                                    "filter_value_not_found_in_authorized_field"
                                ),
                                "missing_field_hashes": ["sha256:field-b"],
                            }
                        ],
                        "external_replan": {
                            "status": "required",
                            "rejection_reason_codes": [
                                "filter_value_not_found_in_authorized_field"
                            ],
                        },
                    },
                },
                {
                    "status": "complete",
                    "coverage": {
                        "status": "complete",
                        "coverage_status": "complete",
                    },
                    "citations": [citation],
                },
            ]
        )

        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text="preserve this mail lookup goal",
                latest_evidence=None,
                safety_identifier="distinct-progress-session",
                evidence_tool=evidence_tool,
            )

        self.assertEqual(evidence_tool.call_count, 3)
        self.assertEqual(len(requests), 4)
        self.assertEqual(outcome.answer_text, "source-backed candidate result")
        self.assertEqual(outcome.citation_ids, (citation,))

    def test_unknown_uppercase_value_is_not_sent_to_public_web(self) -> None:
        requests = []
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-unsafe-public-term",
                            "name": "clarify_public_terminology",
                            "arguments": json.dumps({"term": "PRIVATE", "domain": "general"}),
                        }
                    ],
                }
            rejected = json.loads(payload["input"][-1]["output"])
            self.assertEqual(rejected["data"]["status"], "rejected")
            self.assertEqual(
                rejected["data"]["reason_code"],
                "unsafe_or_invalid_public_term",
            )
            return {
                "status": "completed",
                "output_text": _decision(
                    response_kind="clarification",
                    answer_text="Public lookup was rejected.",
                ),
            }

        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text="Explain the term.",
                latest_evidence=None,
                safety_identifier="unsafe-public-term-session",
                evidence_tool=mock.Mock(),
            )

        self.assertEqual(len(requests), 1)
        self.assertFalse(
            any(
                request.get("tools") == [{"type": "web_search", "search_context_size": "low"}]
                for request in requests
            )
        )
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(
            outcome.provider_diagnostic["reason_code"],
            "invalid_function_call_shape",
        )

    def test_bad_final_citation_gets_one_tool_disabled_repair(self) -> None:
        citation = "citation-final-repair"
        requests = []
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                return orchestrator._UatProviderResponse({
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-before-final-repair",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {
                                    "query_text": "standalone authorized lookup",
                                    "table_query": None,
                                }
                            ),
                        }
                    ],
                }, http_status=201, request_shape=orchestrator._provider_request_shape_snapshot(payload))
            if len(requests) == 2:
                return {
                    "status": "completed",
                    "output_text": _decision(
                        answer_text="bad citation",
                        citations=("citation-not-returned",),
                        coverage_status="complete",
                    ),
                }
            self.assertEqual(payload["tools"], [])
            self.assertEqual(payload["tool_choice"], "none")
            repair_context = payload["input"][-1]["content"]
            self.assertIn("citation_validation_failed", repair_context)
            self.assertIn(citation, repair_context)
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text="repaired source-backed answer",
                    citations=(citation,),
                    coverage_status="complete",
                ),
            }

        evidence_tool = mock.Mock(
            return_value={
                "status": "complete",
                "coverage": {"status": "complete", "coverage_status": "complete"},
                "citations": [citation],
            }
        )
        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text="authorized lookup",
                latest_evidence=None,
                safety_identifier="final-repair-session",
                evidence_tool=evidence_tool,
            )

        self.assertEqual(len(requests), 3)
        self.assertEqual(outcome.answer_text, "repaired source-backed answer")
        self.assertEqual(outcome.citation_ids, (citation,))
        diagnostic = outcome.provider_diagnostic
        self.assertEqual(diagnostic["provider_attempt_count"], 3)
        self.assertEqual(diagnostic["provider_attempts"][0]["http_status"], 201)
        self.assertNotIn("http_status", diagnostic)
        for attempt in diagnostic["provider_attempts"][1:]:
            self.assertNotIn("http_status", attempt)
        self.assertTrue(all(a["valid_attempt"] is True for a in diagnostic["provider_attempts"]))
        self.assertEqual(diagnostic["tool_choice"], diagnostic["provider_attempts"][-1]["tool_choice"])
        self.assertEqual(diagnostic["tool_choice"]["tool_choice"], "none")
        self.assertEqual(diagnostic["outcome"], diagnostic["provider_attempts"][-1]["outcome"])
        self.assertEqual(diagnostic["request_shape"], diagnostic["provider_attempts"][-1]["request_shape"])

    def test_incomplete_provider_final_stops_without_blind_retry_and_keeps_evidence(
        self,
    ) -> None:
        citation = "citation-provider-incomplete"
        requests = []
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-before-provider-incomplete",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {
                                    "query_text": "bounded source-backed rows",
                                    "table_query": None,
                                }
                            ),
                        }
                    ],
                }
            if len(requests) == 2:
                return {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "usage": {
                        "input_tokens": 1_000,
                        "output_tokens": 4_096,
                        "total_tokens": 5_096,
                    },
                    "output": [{"type": "reasoning"}],
                }
            self.fail("an observed incomplete provider result must not be retried blindly")

        evidence_tool = mock.Mock(
            return_value={
                "status": "complete",
                "coverage": {"status": "complete", "coverage_status": "complete"},
                "citations": [citation],
            }
        )
        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text="return the supported rows",
                latest_evidence=None,
                safety_identifier="provider-incomplete-session",
                evidence_tool=evidence_tool,
            )

        self.assertEqual(len(requests), 2)
        self.assertEqual(evidence_tool.call_count, 1)
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(len(outcome.tool_results), 1)
        self.assertEqual(outcome.tool_results[0]["citations"], [citation])
        diagnostic = dict(outcome.provider_diagnostic or {})
        self.assertNotIn("http_status", diagnostic)
        self.assertEqual(
            {
                key: diagnostic.pop(key)
                for key in (
                    "reason_code",
                    "provider_status",
                    "provider_status_sha256",
                    "incomplete_reason",
                    "incomplete_reason_sha256",
                    "provider_error_code",
                    "provider_error_code_sha256",
                    "provider_error_type",
                    "provider_error_type_sha256",
                    "reasoning_item_present",
                    "reasoning_encrypted_content_present",
                )
            },
            {
                "reason_code": "incomplete_status",
                "provider_status": "incomplete",
                "provider_status_sha256": None,
                "incomplete_reason": "max_output_tokens",
                "incomplete_reason_sha256": None,
                "provider_error_code": None,
                "provider_error_code_sha256": None,
                "provider_error_type": None,
                "provider_error_type_sha256": None,
                "reasoning_item_present": True,
                "reasoning_encrypted_content_present": False,
            },
        )
        self.assertEqual(diagnostic["provider_attempt_count"], 2)
        self.assertEqual(diagnostic["tool_choice"], diagnostic["provider_attempts"][-1]["tool_choice"])
        self.assertEqual(diagnostic["outcome"], diagnostic["provider_attempts"][-1]["outcome"])
        for attempt in diagnostic["provider_attempts"]:
            self.assertNotIn("http_status", attempt)
            self.assertIs(attempt["valid_attempt"], True)
        self.assertEqual(len(diagnostic["provider_phase_timings"]), 2)
        self.assertEqual(
            [item["phase"] for item in diagnostic["provider_phase_timings"]],
            ["provider_request", "provider_request"],
        )

    def test_provider_error_diagnostic_hashes_code_without_exposing_body(self) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        private_error_code = "provider-private-error-code"
        response = mock.MagicMock()
        response.status = 200
        response.read.return_value = json.dumps(
            {
                "status": "failed",
                "error": {
                    "code": private_error_code,
                    "type": "invalid_request_error",
                    "message": "private provider response detail",
                },
            }
        ).encode()
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        opener = mock.MagicMock()
        opener.open.return_value = response

        with mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(RuntimeError) as raised:
                provider._request_response({"model": "synthetic"})

        diagnostic = raised.exception.safe_diagnostic
        rendered = json.dumps(diagnostic, sort_keys=True)
        self.assertEqual(diagnostic["reason_code"], "provider_error")
        self.assertEqual(diagnostic["http_status"], 200)
        self.assertEqual(diagnostic["provider_status"], "failed")
        self.assertEqual(diagnostic["provider_error_code"], None)
        self.assertEqual(
            diagnostic["provider_error_code_sha256"],
            "sha256:" + hashlib.sha256(private_error_code.encode()).hexdigest(),
        )
        self.assertEqual(diagnostic["provider_error_type"], "invalid_request_error")
        self.assertIsNone(diagnostic["provider_error_type_sha256"])
        self.assertNotIn(private_error_code, rendered)
        self.assertNotIn("private provider response detail", rendered)

    def test_function_call_continuation_accepts_complete_split_sse_response(self) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        response_payload = {
            "status": "completed",
            "output_text": "continuation completed",
        }
        wire = (
            b": keepalive\r\n\r\n"
            b"event: response.completed\r\n"
            b'data: {"type":"response.completed","response":'
            b'{"status":"completed","output_text":"continuation completed"}}\r\n\r\n'
        )
        chunks = (wire[:17], wire[17:53], wire[53:91], wire[91:])
        response = mock.MagicMock()
        response.status = 200
        response.headers = {"Content-Type": "text/event-stream"}
        response.read1.side_effect = (*chunks, b"")
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        opener = mock.MagicMock()
        opener.open.return_value = response

        with mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
            return_value=opener,
        ):
            parsed = provider._request_response(
                {
                    "model": "synthetic",
                    "input": [
                        {
                            "type": "function_call_output",
                            "call_id": "call-synthetic",
                            "output": "{}",
                        }
                    ],
                }
            )

        self.assertEqual(parsed, response_payload)
        request = opener.open.call_args.args[0]
        self.assertTrue(json.loads(request.data)["stream"])
        self.assertEqual(request.get_header("Accept"), "text/event-stream")

    def test_function_call_continuation_accepts_data_type_terminal_event(self) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        expected = {"status": "completed", "output_text": "data-only completion"}
        wire = (
            b'data: {"type":"response.completed","response":'
            b'{"status":"completed","output_text":"data-only completion"}}\r\n\r\n'
        )
        response = mock.MagicMock()
        response.status = 200
        response.headers = {"Content-Type": "text/event-stream"}
        response.read1.side_effect = (wire, b"")
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        opener = mock.MagicMock()
        opener.open.return_value = response

        with mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
            return_value=opener,
        ):
            parsed = provider._request_response(
                {
                    "model": "synthetic",
                    "input": [
                        {
                            "type": "function_call_output",
                            "call_id": "call-synthetic",
                            "output": "{}",
                        }
                    ],
                }
            )

        self.assertEqual(parsed, expected)

    def test_function_call_sse_error_before_completed_fails_immediately(self) -> None:
        continuation = {
            "model": "synthetic",
            "input": [{"type": "function_call_output", "call_id": "call", "output": "{}"}],
        }
        completed = (
            b'event: response.completed\n'
            b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        )
        error_wires = (
            b'event: error\n'
            b'data: {"type":"error","error":{"type":"server_error","code":"server_error"}}\n\n'
            + completed,
            b'data: {"type":"error","error":{"type":"server_error","code":"server_error"}}\n\n'
            + completed,
        )

        for wire in error_wires:
            with self.subTest(data_only=wire.startswith(b"data:")):
                provider = CodexResponsesConversationModel(
                    base_url="https://provider.example.test/v1",
                    api_key="synthetic-direct-provider-key",
                )
                response = mock.MagicMock()
                response.status = 200
                response.headers = {"Content-Type": "text/event-stream"}
                response.read1.return_value = wire
                response.__enter__.return_value = response
                response.__exit__.return_value = None
                opener = mock.MagicMock()
                opener.open.return_value = response

                with mock.patch(
                    "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
                    return_value=opener,
                ):
                    with self.assertRaises(RuntimeError) as raised:
                        provider._request_response(continuation)

                self.assertEqual(
                    raised.exception.safe_diagnostic["reason_code"],
                    "provider_error",
                )
                response.read1.assert_called_once()

    def test_function_call_sse_requires_terminal_and_preserves_provider_status(self) -> None:
        def provider_response(wire: bytes):
            provider = CodexResponsesConversationModel(
                base_url="https://provider.example.test/v1",
                api_key="synthetic-direct-provider-key",
            )
            response = mock.MagicMock()
            response.status = 200
            response.headers = {"Content-Type": "text/event-stream"}
            response.read1.side_effect = (wire, b"")
            response.__enter__.return_value = response
            response.__exit__.return_value = None
            opener = mock.MagicMock()
            opener.open.return_value = response
            return provider, opener

        continuation = {
            "model": "synthetic",
            "input": [{"type": "function_call_output", "call_id": "call", "output": "{}"}],
        }
        failed_response = {
            "status": "failed",
            "error": {"code": "server_error", "type": "server_error"},
        }
        failed_wire = (
            b"event: response.failed\n"
            + b"data: "
            + json.dumps(
                {"type": "response.failed", "response": failed_response}
            ).encode()
            + b"\n\n"
        )
        provider, opener = provider_response(failed_wire)
        with mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(RuntimeError) as raised:
                provider._request_response(continuation)
        self.assertEqual(raised.exception.safe_diagnostic["reason_code"], "provider_error")

        incomplete_response = {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
        }
        incomplete_wire = (
            b"event: response.incomplete\r\n"
            + b"data: "
            + json.dumps(
                {"type": "response.incomplete", "response": incomplete_response}
            ).encode()
            + b"\r\n\r\n"
        )
        provider, opener = provider_response(incomplete_wire)
        with mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
            return_value=opener,
        ):
            parsed = provider._request_response(continuation)
        self.assertEqual(parsed, incomplete_response)

        provider, opener = provider_response(
            b"event: response.completed\r\ndata: {\"response\":{\"status\":\"completed\"}}\r\n"
        )
        with mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(RuntimeError) as raised:
                provider._request_response(continuation)
        self.assertEqual(
            raised.exception.safe_diagnostic["reason_code"],
            "unexpected_sse_response",
        )

    def test_function_call_sse_enforces_total_byte_and_active_deadline_caps(self) -> None:
        continuation = {
            "model": "synthetic",
            "input": [{"type": "function_call_output", "call_id": "call", "output": "{}"}],
        }

        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        response = mock.MagicMock()
        response.status = 200
        response.headers = {"Content-Type": "text/event-stream"}
        response.read1.return_value = b":" * (4 * 1024 * 1024 + 1)
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        opener = mock.MagicMock()
        opener.open.return_value = response
        with mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
            return_value=opener,
        ):
            with self.assertRaises(RuntimeError) as raised:
                provider._request_response(continuation)
        self.assertEqual(
            raised.exception.safe_diagnostic["reason_code"],
            "response_too_large",
        )

        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        provider._active_request_timeout_seconds = 1.0
        response = mock.MagicMock()
        response.status = 200
        response.headers = {"Content-Type": "text/event-stream"}
        response.read1.return_value = b": keepalive\n"
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        opener = mock.MagicMock()
        opener.open.return_value = response
        with (
            mock.patch(
                "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
                return_value=opener,
            ),
            mock.patch(
                "formowl_mail.human_uat_orchestrator.time.monotonic",
                side_effect=(10.0, 10.5, 11.0),
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                provider._request_response(continuation)
        self.assertEqual(
            raised.exception.safe_diagnostic["reason_code"],
            "transport_timeout",
        )

    def test_noncontinuation_provider_request_keeps_json_transport(self) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        expected = {"status": "completed", "output_text": "ordinary response"}
        response = mock.MagicMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = json.dumps(expected).encode()
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        opener = mock.MagicMock()
        opener.open.return_value = response

        with mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
            return_value=opener,
        ):
            parsed = provider._request_response(
                {"model": "synthetic", "input": [{"role": "user", "content": "hello"}]}
            )

        self.assertEqual(parsed, expected)
        request = opener.open.call_args.args[0]
        self.assertFalse(json.loads(request.data)["stream"])
        self.assertEqual(request.get_header("Accept"), "application/json")

    def test_provider_error_discriminator_is_allowlisted_and_non_leaking(self) -> None:
        public_params = (
            "model",
            "tools",
            "tool_choice",
            "text.format",
            "reasoning",
            "max_output_tokens",
            "stream",
            "store",
            "safety_identifier",
        )
        for public_param in public_params:
            with self.subTest(public_param=public_param):
                diagnostic = _provider_diagnostic(
                    reason_code="provider_error",
                    http_status=408,
                    response={
                        "error": {
                            "param": public_param,
                            "message": f"invalid parameter: {public_param}",
                        }
                    },
                )
                self.assertEqual(diagnostic["provider_error_param"], public_param)
                self.assertEqual(
                    diagnostic["provider_error_message_class"],
                    "invalid_parameter",
                )

        private_param = "input[0].content[0].text"
        private_message = "secret body and https://provider.example.test/private"
        diagnostic = _provider_diagnostic(
            reason_code="provider_error",
            http_status=408,
            response={
                "error": {
                    "param": private_param,
                    "message": private_message,
                }
            },
        )
        rendered = json.dumps(diagnostic, ensure_ascii=False, sort_keys=True)
        self.assertIsNone(diagnostic["provider_error_param"])
        self.assertEqual(diagnostic["provider_error_message_class"], "unknown")
        self.assertNotIn(private_param, rendered)
        self.assertNotIn(private_message, rendered)
        self.assertNotIn("provider.example.test", rendered)

        for message, expected_class in (
            ("request timed out", "timeout"),
            ("rate limit exceeded", "rate_limit"),
            ("service temporarily unavailable due to capacity", "capacity_unavailable"),
            ("unsupported parameter", "invalid_parameter"),
            ("unrelated provider detail", "unknown"),
        ):
            with self.subTest(message=message):
                diagnostic = _provider_diagnostic(
                    reason_code="provider_error",
                    http_status=408,
                    response={"error": {"message": message}},
                )
                self.assertEqual(
                    diagnostic["provider_error_message_class"],
                    expected_class,
                )
                self.assertNotIn(message, json.dumps(diagnostic, ensure_ascii=False))

    def test_provider_failure_is_error_with_safe_wire_diagnostic_in_browser_payload(self) -> None:
        from formowl_mail.human_uat_http import _normalize_query_response

        outcome = UatConversationOutcome(
            response_kind="clarification",
            answer_text="GPT provider 目前無法完成回應，這次沒有產生可驗證答案；請稍後再試。",
            display_format="narrative",
            model_name="codex-responses:gpt-5.6-luna",
            coverage_status="incomplete",
            coverage_note="provider failure",
            provider_diagnostic={
                "reason_code": "http_error",
                "http_status": 502,
                "provider_error_type": "rate_limit_error",
                "provider_error_code_sha256": (
                    "sha256:" + hashlib.sha256(b"provider-limit").hexdigest()
                ),
                "response_body_bytes": 123,
                "response_body_shape": "json_object",
                "response_content_type": "application/json",
                "response_content_encoding": "identity",
                "response_declared_body_bytes": 123,
                "response_declared_length_matches": True,
                "response_transfer_chunked": False,
            },
        )

        projected = _browser_projection(
            outcome,
            (),
            latest_evidence=None,
        )
        normalized = _normalize_query_response(
            _with_mcp_diagnostic(projected, ()),
        )

        self.assertEqual(projected["status"], "error")
        self.assertEqual(projected["answer"], outcome.answer_text)
        self.assertIsNone(projected["clarification"])
        self.assertEqual(normalized["diagnostic"]["http_status"], 502)
        self.assertEqual(
            normalized["diagnostic"]["provider_error_type"],
            "rate_limit_error",
        )
        self.assertEqual(
            normalized["diagnostic"]["response_body_shape"],
            "json_object",
        )
        self.assertNotIn("provider-limit", json.dumps(normalized, ensure_ascii=False))

    def test_http_408_invalid_request_before_mcp_is_provider_failure(self) -> None:
        received: list[dict[str, object]] = []
        private_detail = "private provider detail"
        private_code = "private-provider-code"

        class PreMcpFailureHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                received.append(json.loads(self.rfile.read(length)))
                body = json.dumps(
                    {
                        "error": {
                            "type": "invalid_request_error",
                            "code": private_code,
                            "message": private_detail,
                        }
                    }
                ).encode("utf-8")
                self.send_response(408)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), PreMcpFailureHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        provider = CodexResponsesConversationModel(
            base_url=f"http://127.0.0.1:{server.server_address[1]}/v1",
            api_key="synthetic-local-http-provider-key",
        )
        evidence_tool = mock.Mock()
        try:
            outcome = provider.respond(
                history=(),
                user_text="整理劉一帆的信件",
                latest_evidence=None,
                safety_identifier="pre-mcp-408-session",
                evidence_tool=evidence_tool,
            )
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["model"], "gpt-5.5")
        self.assertEqual(received[0]["reasoning"], {"effort": "high"})
        evidence_tool.assert_not_called()
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(
            outcome.provider_diagnostic["reason_code"],
            "provider_pre_mcp_failure",
        )
        self.assertEqual(outcome.provider_diagnostic["http_status"], 408)
        self.assertEqual(outcome.provider_diagnostic["provider_attempts"][0]["http_status"], 408)
        self.assertEqual(
            outcome.provider_diagnostic["provider_error_type"],
            "invalid_request_error",
        )
        diagnostic_text = json.dumps(outcome.provider_diagnostic, ensure_ascii=False)
        self.assertNotIn(private_code, diagnostic_text)
        self.assertNotIn(private_detail, diagnostic_text)
        projected = _with_mcp_diagnostic(
            _browser_projection(outcome, (), latest_evidence=None),
            (),
        )
        self.assertEqual(projected["status"], "error")
        self.assertEqual(projected["citations"], [])
        self.assertEqual(projected["diagnostic"]["reason_code"], "provider_pre_mcp_failure")
        self.assertEqual(projected["diagnostic"]["mcp"]["call_count"], 0)
        self.assertNotIn("查無資料", projected["answer"])
        self.assertNotIn("not_found", projected["answer"])
        request_shape = outcome.provider_diagnostic["request_shape"]
        self.assertEqual(
            set(request_shape),
            {
                "fingerprint",
                "has_model",
                "has_instructions",
                "has_input",
                "has_tools",
                "tool_count",
                "tool_choice_kind",
                "tool_choice_wire_type",
                "has_text_format",
                "has_reasoning",
                "has_store",
                "has_stream",
                "has_output_limit",
            },
        )
        self.assertRegex(request_shape["fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertIsInstance(request_shape["tool_count"], int)
        self.assertEqual(request_shape["tool_choice_kind"], "required_function")
        self.assertEqual(request_shape["tool_choice_wire_type"], "function")
        attempt_shape = outcome.provider_diagnostic["provider_attempts"][0]["request_shape"]
        self.assertEqual(attempt_shape, request_shape)
        rendered_shape = json.dumps(request_shape, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("整理劉一帆的信件", rendered_shape)
        self.assertNotIn(private_code, rendered_shape)
        self.assertNotIn("synthetic-local-http-provider-key", rendered_shape)

    def test_http_408_after_mcp_is_not_pre_mcp_failure_and_keeps_evidence(self) -> None:
        descriptor = _actual_mail_tool_descriptor()
        citation_id = "mail-citation-before-provider-408"
        received: list[dict[str, object]] = []
        evidence_requests: list[UatEvidenceToolRequest] = []
        private_detail = "private post-mcp provider detail"
        private_code = "private-post-mcp-code"
        evidence_result = {
            "status": "partial",
            "query_hash": "sha256:post-mcp-408-query",
            "mail_import_session_id": "mail-session-post-mcp-408",
            "evidence_snippets": [
                {
                    "source_type": "mail_body_segment",
                    "source_observation_id": "observation-post-mcp-408",
                    "mail_import_session_id": "mail-session-post-mcp-408",
                    "email_message_id": "message-post-mcp-408",
                    "message_occurrence_id": "occurrence-post-mcp-408",
                    "snippet": "Bounded post-MCP evidence snippet.",
                }
            ],
            "citations": [
                {
                    "citation_id": citation_id,
                    "source_type": "mail_body_segment",
                    "source_observation_id": "observation-post-mcp-408",
                    "mail_import_session_id": "mail-session-post-mcp-408",
                    "email_message_id": "message-post-mcp-408",
                    "message_occurrence_id": "occurrence-post-mcp-408",
                }
            ],
        }

        class PostMcpFailureHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                received.append(json.loads(self.rfile.read(length)))
                if len(received) == 1:
                    body = json.dumps(
                        {
                            "status": "completed",
                            "output": [
                                {
                                    "type": "function_call",
                                    "call_id": "call-post-mcp-408",
                                    "name": descriptor["name"],
                                    "arguments": json.dumps(
                                        {
                                            "query_text": (
                                                "Find bounded mail evidence before "
                                                "provider failure."
                                            ),
                                            "required_terms": ["bounded mail evidence"],
                                            "mail_import_session_id": ("mail-session-post-mcp-408"),
                                            "limit": 1,
                                        }
                                    ),
                                }
                            ],
                        }
                    ).encode("utf-8")
                    self.send_response(201)
                else:
                    body = json.dumps(
                        {
                            "error": {
                                "type": "invalid_request_error",
                                "code": private_code,
                                "message": private_detail,
                            }
                        }
                    ).encode("utf-8")
                    self.send_response(408)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        server = ThreadingHTTPServer(("127.0.0.1", 0), PostMcpFailureHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        provider = CodexResponsesConversationModel(
            base_url=f"http://127.0.0.1:{server.server_address[1]}/v1",
            api_key="synthetic-local-http-provider-key",
        )

        def evidence_tool(request: UatEvidenceToolRequest) -> dict[str, object]:
            evidence_requests.append(request)
            return evidence_result

        try:
            outcome = provider.respond(
                history=(),
                user_text="Summarize the bounded mail evidence.",
                latest_evidence=None,
                safety_identifier="post-mcp-408-session",
                evidence_tool=evidence_tool,
                formowl_tool_descriptor=descriptor,
                authorized_capability_summary={
                    "source_families": ["mail"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": [
                        "mail-session-post-mcp-408"
                    ],
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

        self.assertEqual(len(received), 2)
        self.assertEqual(len(evidence_requests), 1)
        self.assertEqual(outcome.provider_diagnostic["reason_code"], "http_error")
        self.assertEqual(
            [attempt["http_status"] for attempt in outcome.provider_diagnostic["provider_attempts"]],
            [201, 408],
        )
        self.assertNotEqual(
            outcome.provider_diagnostic["reason_code"],
            "provider_pre_mcp_failure",
        )
        self.assertEqual(outcome.provider_diagnostic["http_status"], 408)
        self.assertEqual(
            outcome.provider_diagnostic["provider_error_type"],
            "invalid_request_error",
        )
        self.assertEqual(outcome.citation_ids, (citation_id,))
        self.assertEqual(outcome.tool_results, (evidence_result,))
        tool_output = json.loads(received[1]["input"][-1]["output"])
        self.assertEqual(tool_output["data"]["citations"][0]["citation_id"], citation_id)
        self.assertEqual(
            tool_output["data"]["evidence_snippets"][0]["snippet"],
            "Bounded post-MCP evidence snippet.",
        )
        projected = _browser_projection(
            outcome,
            outcome.tool_results,
            latest_evidence=None,
        )
        self.assertEqual(projected["status"], "partial")
        self.assertEqual(projected["citations"], [citation_id])
        rendered = json.dumps(
            {
                "diagnostic": outcome.provider_diagnostic,
                "projected": projected,
                "tool_output": tool_output,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn("provider_pre_mcp_failure", rendered)
        self.assertNotIn(private_code, rendered)
        self.assertNotIn(private_detail, rendered)
        self.assertNotIn("synthetic-local-http-provider-key", rendered)
        self.assertNotIn("raw_path", rendered)

    def test_direct_provider_preserves_citations_without_duplicate_final_envelope_retry(
        self,
    ) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        citation = "citation-envelope-retry"

        def http_response(payload, *, content_type="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            response = mock.MagicMock()
            response.status = 200
            response.headers = {"Content-Type": content_type}
            response.read.return_value = body
            response.read1.side_effect = (body, b"")
            response.__enter__.return_value = response
            response.__exit__.return_value = None
            return response

        tool_responses = [
            {
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": f"call-envelope-{index}",
                        "name": "query_effective_graph_view",
                        "arguments": json.dumps(
                            {
                                "query_text": f"bounded source rows {index}",
                                "table_query": None,
                            }
                        ),
                    }
                ],
            }
            for index in range(3)
        ]
        responses = [http_response(tool_responses[0])]
        for tool_response in tool_responses[1:]:
            event = json.dumps(
                {
                    "type": "response.completed",
                    "response": tool_response,
                }
            ).encode()
            responses.append(
                http_response(
                    b"event: response.completed\n"
                    + b"data: "
                    + event
                    + b"\n\n",
                    content_type="text/event-stream",
                )
            )
        malformed_body = b"data: provider envelope was not JSON\n\n"
        responses.extend(
            [
                http_response(
                    malformed_body,
                    content_type="text/event-stream; charset=utf-8",
                ),
                http_response(
                    {
                        "status": "completed",
                        "output_text": _decision(
                            answer_text=f"bounded recovered answer [{citation}]",
                            citations=(citation,),
                            coverage_status="complete",
                        ),
                    }
                ),
            ]
        )
        opener = mock.MagicMock()
        observed_timeouts: list[float] = []
        clock_value = 1_000.0

        def open_response(request, *, timeout):
            nonlocal clock_value
            call_index = len(observed_timeouts)
            if call_index == 3:
                clock_value += 110.0
            observed_timeouts.append(timeout)
            return responses[call_index]

        opener.open.side_effect = open_response
        evidence_tool = mock.Mock(
            return_value={
                "status": "complete",
                "coverage": {"status": "complete", "coverage_status": "complete"},
                "citations": [citation],
            }
        )

        with (
            mock.patch(
                "formowl_mail.human_uat_orchestrator.urllib.request.build_opener",
                return_value=opener,
            ),
            mock.patch(
                "formowl_mail.human_uat_orchestrator.time.monotonic",
                side_effect=lambda: clock_value,
            ),
        ):
            outcome = provider.respond(
                history=(),
                user_text="return the bounded source rows",
                latest_evidence=None,
                safety_identifier="envelope-retry-session",
                evidence_tool=evidence_tool,
            )

        self.assertEqual(evidence_tool.call_count, 3)
        self.assertEqual(opener.open.call_count, 4)
        self.assertEqual(observed_timeouts[:4], [115.0] * 4)
        first_final_request = opener.open.call_args_list[3].args[0]
        wire_payload = json.loads(first_final_request.data)
        self.assertIs(wire_payload["stream"], True)
        self.assertEqual(first_final_request.get_header("Accept"), "text/event-stream")
        self.assertEqual(first_final_request.get_header("Accept-encoding"), "identity")
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(
            outcome.provider_diagnostic["reason_code"],
            "unexpected_sse_response",
        )
        self.assertEqual(outcome.provider_diagnostic["response_body_shape"], "sse")
        self.assertEqual(
            outcome.provider_diagnostic["response_body_bytes"],
            len(malformed_body),
        )
        self.assertEqual(
            outcome.provider_diagnostic["response_content_type"],
            "text/event-stream",
        )
        self.assertEqual(
            outcome.provider_diagnostic["response_content_encoding"],
            "identity",
        )
        self.assertFalse(outcome.provider_diagnostic["retry_attempted"])
        self.assertEqual(
            outcome.provider_diagnostic["retry_outcome"],
            "preserved_partial",
        )

    def test_direct_responses_provider_preserves_missing_reference_clarification(
        self,
    ) -> None:
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        evidence_tool = mock.Mock()
        with mock.patch.object(
            provider,
            "_request_response",
            return_value={
                "status": "completed",
                "output_text": _decision(
                    response_kind="clarification",
                    answer_text="請問你指的是哪一個項目？",
                ),
            },
        ) as request_response:
            outcome = provider.respond(
                history=(),
                user_text="那個呢？",
                latest_evidence={
                    "status": "clarification_required",
                    "citations": [],
                },
                safety_identifier="missing-reference-session",
                evidence_tool=evidence_tool,
            )

        request = request_response.call_args.args[0]
        self.assertEqual(
            request["tool_choice"],
            {"type": "function", "name": "query_effective_graph_view"},
        )
        self.assertEqual(
            request["text"]["format"]["schema"]["properties"]["response_kind"]["enum"],
            ["answer", "clarification"],
        )
        self.assertIn(
            "a required referent is genuinely absent",
            request["instructions"],
        )
        prior_message = next(
            item
            for item in request["input"]
            if item.get("role") == "developer"
            and "latest governed FormOwl evidence" in item.get("content", "")
        )
        self.assertIn("no citeable prior evidence", prior_message["content"])
        evidence_tool.assert_not_called()
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(outcome.tool_requests, ())

    def test_direct_provider_binds_prior_evidence_to_presented_compaction(self) -> None:
        citation_ids = tuple(f"citation-prior-{index}" for index in range(9))
        latest_evidence = {
            "status": "partial",
            "query_agent": {
                "capabilities": {
                    "source_fields": ["Field A", "Field B"],
                    "maximum_tool_calls": 3,
                }
            },
            "coverage": {"status": "incomplete", "coverage_status": "incomplete"},
            "citations": list(citation_ids[:8]),
            "exact_inventory": {
                "status": "partial",
                "coverage_status": "incomplete",
                "items": [
                    {
                        "item_hash": f"item-{index}",
                        "governed_references": [{"citation_hash": citation_id}],
                    }
                    for index, citation_id in enumerate(citation_ids[:8])
                ],
            },
        }
        compact = compact_evidence_for_model(latest_evidence, item_limit=8)
        self.assertEqual(
            compact["query_agent"]["capabilities"],
            latest_evidence["query_agent"]["capabilities"],
        )
        self.assertEqual(len(compact["exact_inventory"]["items"]), 8)
        self.assertNotIn("presentation_truncated", compact)

        overflow_exact = {
            **latest_evidence["exact_inventory"],
            "items": [
                *latest_evidence["exact_inventory"]["items"],
                {
                    "item_hash": "item-overflow",
                    "governed_references": [{"citation_hash": citation_ids[8]}],
                },
            ],
        }
        overflow_compact = compact_evidence_for_model(
            {**latest_evidence, "exact_inventory": overflow_exact},
            item_limit=8,
        )
        self.assertNotIn("exact_inventory", overflow_compact)
        self.assertTrue(overflow_compact["presentation_truncated"])
        # Citation-only exact references remain hidden when the exact
        # inventory is rejected; they are not independently citeable text.
        self.assertEqual(overflow_compact["citations"], [])

        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )
        evidence_tool = mock.Mock()
        valid_decision = _decision(
            response_kind="render_prior_evidence",
            answer_text="Prior evidence rendered without adding facts.",
            citations=(citation_ids[0],),
            coverage_status="incomplete",
            coverage_note="The presented prior evidence remains incomplete.",
        )
        with mock.patch.object(
            provider,
            "_request_response",
            return_value={"status": "completed", "output_text": valid_decision},
        ) as request_response:
            outcome = provider.respond(
                history=(),
                user_text="Render the prior evidence as a list.",
                latest_evidence=latest_evidence,
                safety_identifier="prior-evidence-session",
                evidence_tool=evidence_tool,
            )

        evidence_tool.assert_not_called()
        request = request_response.call_args.args[0]
        self.assertIn(
            "render_prior_evidence",
            request["text"]["format"]["schema"]["properties"]["response_kind"]["enum"],
        )
        prior_message = next(
            item
            for item in request["input"]
            if item.get("role") == "developer"
            and "latest governed FormOwl evidence" in item.get("content", "")
        )
        envelope = json.loads(prior_message["content"].split("\n", 1)[1])
        self.assertEqual(envelope["evidence_disposition"], "cited_partial")
        self.assertEqual(
            envelope["data"]["query_agent"]["capabilities"],
            latest_evidence["query_agent"]["capabilities"],
        )
        self.assertNotIn(citation_ids[8], json.dumps(envelope, sort_keys=True))
        self.assertEqual(outcome.citation_ids, (citation_ids[0],))
        self.assertEqual(outcome.coverage_status, "incomplete")

        invalid_decisions = (
            (
                _decision(
                    response_kind="render_prior_evidence",
                    citations=(citation_ids[8],),
                    coverage_status="incomplete",
                    coverage_note="The presented prior evidence remains incomplete.",
                ),
                "cited unavailable evidence",
            ),
            (
                _decision(
                    response_kind="render_prior_evidence",
                    citations=(citation_ids[0],),
                    coverage_status="complete",
                ),
                "hid incomplete coverage",
            ),
        )
        for final_decision, error in invalid_decisions:
            with (
                self.subTest(error=error),
                mock.patch.object(
                    provider,
                    "_request_response",
                    return_value={"status": "completed", "output_text": final_decision},
                ) as request_response,
            ):
                stopped = provider.respond(
                    history=(),
                    user_text="Render the prior evidence.",
                    latest_evidence=latest_evidence,
                    safety_identifier=f"prior-evidence-{error}",
                    evidence_tool=evidence_tool,
                )
            self.assertEqual(request_response.call_count, 2)
            self.assertEqual(stopped.response_kind, "clarification")
            self.assertEqual(stopped.citation_ids, tuple(citation_ids[:8]))
            self.assertIn(
                ("引用無法" if error == "cited unavailable evidence" else "覆蓋限制"),
                stopped.answer_text,
            )

    def test_direct_provider_distinguishes_empty_result_from_mcp_failure(self) -> None:
        cases = (
            (
                "empty-result",
                {"status": "ok", "citations": []},
                "no_evidence",
                "目前授權來源沒有回傳可引用證據",
                "FormOwl 證據工具目前無法完成查詢",
                False,
            ),
            (
                "mcp-failure",
                {"status": "mcp_failed", "citations": []},
                "mcp_unavailable",
                "FormOwl 證據工具目前無法完成查詢",
                "目前授權來源沒有回傳可引用證據",
                True,
            ),
        )
        for (
            session_suffix,
            tool_result,
            _stop_reason,
            expected_text,
            forbidden_text,
            expect_tools_empty,
        ) in cases:
            with self.subTest(session_suffix=session_suffix):
                requests = []
                provider = CodexResponsesConversationModel(
                    base_url="https://provider.example.test/v1",
                    api_key="synthetic-direct-provider-key",
                )

                def response(payload):
                    requests.append(copy.deepcopy(payload))
                    if len(requests) == 1:
                        return {
                            "status": "completed",
                            "output": [
                                {
                                    "type": "function_call",
                                    "call_id": f"call-{session_suffix}",
                                    "name": "query_effective_graph_view",
                                    "arguments": json.dumps(
                                        {
                                            "query_text": "bounded source lookup",
                                            "table_query": None,
                                        }
                                    ),
                                }
                            ],
                        }
                    self.assertEqual(bool(payload["tools"]), not expect_tools_empty)
                    if expect_tools_empty:
                        self.assertEqual(payload["tool_choice"], "none")
                    return {
                        "status": "completed",
                        "output_text": _decision(
                            response_kind="clarification",
                            answer_text="provider final draft is not used",
                            coverage_status="incomplete",
                            coverage_note="bounded diagnostic",
                        ),
                    }

                evidence_tool = mock.Mock(return_value=tool_result)
                with mock.patch.object(provider, "_request_response", side_effect=response):
                    outcome = provider.respond(
                        history=(),
                        user_text="return the bounded source lookup",
                        latest_evidence=None,
                        safety_identifier=f"status-distinction-{session_suffix}",
                        evidence_tool=evidence_tool,
                    )

                self.assertEqual(evidence_tool.call_count, 1)
                self.assertEqual(len(requests), 2)
                self.assertEqual(outcome.tool_results[0]["status"], tool_result["status"])
                self.assertIn(expected_text, outcome.answer_text)
                self.assertNotIn(forbidden_text, outcome.answer_text)

    def test_mail_cited_partial_finalizes_with_none_without_second_mcp_call(self) -> None:
        requests = []
        citation = "citation-mail-partial"
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-mail-1",
                            "name": "query_mail_evidence",
                            "arguments": json.dumps(
                                {
                                    "query_text": "把劉一帆的信件整理出來",
                                    "required_terms": ["劉一帆"],
                                    "mail_import_session_id": "authorized-session",
                                }
                            ),
                        }
                    ],
                }
            self.assertEqual(payload["tools"], [])
            self.assertEqual(payload["tool_choice"], "none")
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text="已整理目前可引用的授權郵件；涵蓋仍不完整。",
                    citations=(citation,),
                    coverage_status="incomplete",
                    coverage_note="目前結果為授權範圍內的部分證據。",
                ),
            }

        evidence_tool = mock.Mock(
            return_value={
                "status": "ok",
                "mail_import_session_id": "authorized-session",
                "evidence_snippets": [
                    {"citation_id": citation, "snippet": "bounded mail evidence"}
                ],
                "citations": [citation],
            }
        )
        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text="把劉一帆的信件整理出來",
                latest_evidence=None,
                safety_identifier="mail-cited-partial-finalization",
                evidence_tool=evidence_tool,
                formowl_tool_descriptor=_actual_mail_tool_descriptor(),
                authorized_capability_summary={
                    "source_families": ["mail"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["authorized-session"],
                },
            )

        self.assertEqual(evidence_tool.call_count, 1)
        self.assertEqual(len(requests), 2)
        self.assertEqual(
            requests[0]["tool_choice"],
            {"type": "function", "name": "query_mail_evidence"},
        )
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(outcome.coverage_status, "incomplete")
        self.assertEqual(len(outcome.tool_requests), 1)

    def test_direct_provider_preserves_tool_outputs_and_stops_at_three_calls(self) -> None:
        requests = []
        citation_ids = ("citation-row-1", "citation-row-2")
        tool_results = (
            {
                "status": "replan_required",
                "query_agent": {"external_replan": {"status": "required"}},
            },
            {
                "status": "replan_required",
                "coverage": {"status": "incomplete", "coverage_status": "incomplete"},
                "results": [
                    {"row_hash": "row-1", "citation_id": citation_ids[0]},
                    {"row_hash": "row-2", "citation_id": citation_ids[1]},
                ],
                "citations": list(citation_ids),
            },
            {
                "status": "replan_required",
                "query_agent": {"external_replan": {"status": "required"}},
            },
        )
        evidence_tool = mock.Mock(side_effect=tool_results)
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-direct-provider-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            request_number = len(requests)
            if request_number <= 3:
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "reasoning",
                            "id": f"reasoning-{request_number}",
                            "encrypted_content": f"opaque-{request_number}",
                        },
                        {
                            "type": "function_call",
                            "call_id": f"call-{request_number}",
                            "name": "query_effective_graph_view",
                            "arguments": json.dumps(
                                {"query_text": f"standalone query {request_number}"}
                            ),
                        },
                    ],
                }

            self.assertEqual(payload["tool_choice"], "none")
            reasoning_ids = [
                item["id"] for item in payload["input"] if item.get("type") == "reasoning"
            ]
            function_call_ids = [
                item["call_id"] for item in payload["input"] if item.get("type") == "function_call"
            ]
            function_outputs = [
                item for item in payload["input"] if item.get("type") == "function_call_output"
            ]
            self.assertEqual(
                reasoning_ids,
                ["reasoning-1", "reasoning-2", "reasoning-3"],
            )
            self.assertEqual(function_call_ids, ["call-1", "call-2", "call-3"])
            self.assertEqual(
                [item["call_id"] for item in function_outputs],
                function_call_ids,
            )
            dispositions = [
                json.loads(item["output"])["evidence_disposition"] for item in function_outputs
            ]
            self.assertEqual(
                dispositions,
                [
                    "replan_without_cited_evidence",
                    "cited_partial",
                    "replan_without_cited_evidence",
                ],
            )
            cited_partial = json.loads(function_outputs[1]["output"])
            self.assertEqual(
                [row["row_hash"] for row in cited_partial["data"]["results"]],
                ["row-1", "row-2"],
            )
            return {
                "status": "completed",
                "output_text": _decision(
                    answer_text="Bounded partial evidence with both rows preserved.",
                    citations=citation_ids,
                    coverage_status="incomplete",
                    coverage_note="The authorized evidence remains incomplete.",
                ),
            }

        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(),
                user_text="Retrieve the authorized evidence.",
                latest_evidence=None,
                safety_identifier="three-call-session",
                evidence_tool=evidence_tool,
            )

        self.assertEqual(len(requests), 4)
        self.assertTrue(
            all(
                request["tool_choice"] == {"type": "function", "name": "query_effective_graph_view"}
                for request in requests[:3]
            )
        )
        self.assertIn("never collapse a multi-row", requests[0]["instructions"])
        self.assertEqual(evidence_tool.call_count, 3)
        self.assertEqual(outcome.citation_ids, citation_ids)
        self.assertEqual(outcome.coverage_status, "incomplete")
        self.assertEqual(len(outcome.tool_requests), 3)

    def test_pinned_provider_allows_three_untrusted_queries_and_discloses_incomplete(
        self,
    ) -> None:
        transport = _RecordingTransport(
            calls=(
                {"query_text": "standalone query one"},
                {"query_text": "standalone query two"},
                {"query_text": "standalone query three"},
            ),
            final_message=_decision(
                citations=("citation-final",),
                coverage_status="incomplete",
                coverage_note="Authorized evidence coverage remains incomplete.",
            ),
        )
        returned = (
            {
                "status": "replan_required",
                "query_agent": {"external_replan": {"status": "required"}},
                "citations": [],
            },
            {"status": "partial", "citations": ["citation-middle"]},
            {
                "status": "partial",
                "exact_inventory": {
                    "coverage_status": "incomplete",
                    "items": [
                        {
                            "item_hash": "item-final",
                            "governed_references": [{"citation_hash": "citation-final"}],
                        }
                    ],
                },
            },
        )
        requests = []

        def query_tool(request):
            requests.append(request)
            return returned[len(requests) - 1]

        with tempfile.TemporaryDirectory() as workspace:
            provider = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            outcome = provider.respond(
                history=(),
                user_text="fragmentary request",
                latest_evidence=None,
                safety_identifier="diagnostic-session",
                evidence_tool=query_tool,
                authorized_capability_summary={
                    "source_families": ["attachment_table", "mail"],
                },
            )

        self.assertEqual(transport.thread_start["model"], "gpt-5.5")
        tool = transport.thread_start["dynamic_tools"][0]
        expected_tool = _actual_query_tool_descriptor()
        self.assertEqual(tool["name"], "query_effective_graph_view")
        self.assertEqual(tool["inputSchema"], expected_tool["inputSchema"])
        self.assertEqual(tool["description"], expected_tool["description"])
        self.assertEqual(transport.turn_call["reasoning_effort"], "high")
        self.assertIn(
            "formowl_turn_request_contract",
            transport.turn_call["additional_context"],
        )
        self.assertEqual(
            [request.query_text for request in requests],
            [
                "standalone query one",
                "standalone query two",
                "standalone query three",
            ],
        )
        self.assertTrue(
            all(output["trust"] == "untrusted_evidence" for output in transport.tool_outputs)
        )
        self.assertEqual(
            {json.dumps(request.request_contract, sort_keys=True) for request in requests},
            {
                json.dumps(
                    {
                        "original_query_hash": (
                            "sha256:" + hashlib.sha256(b"fragmentary request").hexdigest()
                        ),
                        "query_class": "evidence_lookup",
                        "source_family_scope": ["attachment_table", "mail"],
                        "requested_fields": [],
                        "maximum_claim_strength": "cited_evidence",
                    },
                    sort_keys=True,
                )
            },
        )
        self.assertEqual(outcome.model_name, "codex:gpt-5.5")
        self.assertEqual(outcome.citation_ids, ("citation-final",))
        self.assertEqual(outcome.coverage_status, "incomplete")
        self.assertEqual(len(outcome.tool_requests), 3)

    def test_provider_rejects_fourth_call_or_uncited_incomplete_answer(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            transport = _RecordingTransport(
                calls=tuple({"query_text": f"query {index}"} for index in range(4)),
                final_message=_decision(),
            )
            provider = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            with self.assertRaisesRegex(RuntimeError, "too many UAT tools"):
                provider.respond(
                    history=(),
                    user_text="request",
                    latest_evidence=None,
                    safety_identifier="session-too-many-tools",
                    evidence_tool=lambda request: {
                        "status": "partial",
                        "citations": ["citation"],
                    },
                )
            self.assertEqual(transport.deleted_threads, ["thread-1"])

        for final_message in (
            _decision(coverage_status="complete"),
            _decision(citations=("citation",), coverage_status="complete"),
        ):
            with (
                self.subTest(final_message=final_message),
                tempfile.TemporaryDirectory() as workspace,
            ):
                transport = _RecordingTransport(
                    calls=({"query_text": "query"},),
                    final_message=final_message,
                )
                provider = CodexAppServerConversationModel(
                    transport,
                    workspace_dir=workspace,
                )
                outcome = provider.respond(
                    history=(),
                    user_text="request",
                    latest_evidence=None,
                    safety_identifier="session-finalization-failure",
                    evidence_tool=lambda request: {
                        "status": "partial",
                        "citations": ["citation"],
                    },
                )
                self.assertEqual(outcome.response_kind, "clarification")
                self.assertEqual(len(outcome.tool_results), 1)
                self.assertEqual(outcome.tool_results[0]["citations"], ["citation"])
                self.assertEqual(transport.deleted_threads, ["thread-1"])

    def test_app_server_failure_without_diagnostic_stays_error(self) -> None:
        with tempfile.TemporaryDirectory() as workspace:
            transport = _RecordingTransport(
                calls=(),
                final_message="unused",
                run_error=_CodexAppServerProviderFailure(
                    "provider_unavailable",
                    "synthetic private transport detail",
                ),
            )
            provider = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            outcome = provider.respond(
                history=(),
                user_text="synthetic request",
                latest_evidence=None,
                safety_identifier="session-app-server-no-diagnostic",
                evidence_tool=lambda _request: self.fail("no source call expected"),
            )

        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(
            outcome.provider_diagnostic,
            {"reason_code": "provider_unavailable"},
        )
        projection = _browser_projection(outcome, (), latest_evidence=None)
        self.assertEqual(projection["status"], "error")
        self.assertEqual(projection["citations"], [])
        self.assertNotIn("synthetic private transport detail", json.dumps(projection))
        self.assertEqual(transport.deleted_threads, ["thread-1"])

    def test_app_server_provider_timeout_preserves_citation_bearing_evidence(self) -> None:
        citation = "citation-app-server-timeout"
        with tempfile.TemporaryDirectory() as workspace:
            transport = _RecordingTransport(
                calls=({"query_text": "standalone source lookup"},),
                final_message=_decision(citations=(citation,), coverage_status="complete"),
                run_error=TimeoutError("provider wait"),
            )
            provider = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            outcome = provider.respond(
                history=(),
                user_text="request",
                latest_evidence=None,
                safety_identifier="session-provider-timeout",
                evidence_tool=lambda request: {
                    "status": "complete",
                    "citations": [citation],
                },
            )

        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(outcome.coverage_status, "incomplete")
        self.assertEqual(len(outcome.tool_results), 1)
        self.assertEqual(outcome.tool_results[0]["citations"], [citation])
        self.assertEqual(transport.deleted_threads, ["thread-1"])

    def test_stdio_error_events_surface_only_safe_provider_metadata(self) -> None:
        private_message = "synthetic private provider detail"
        private_details = "synthetic-private-additional-details"
        error = {
            "message": private_message,
            "additionalDetails": private_details,
            "codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 408}},
        }
        error_event = {
            "threadId": "thread-stdio-error",
            "turnId": "turn-stdio-error",
            "willRetry": False,
            "error": error,
        }

        retry_transport = object.__new__(CodexAppServerStdioTransport)
        retry_transport._state_lock = threading.RLock()
        retry_context = SimpleNamespace(
            event=threading.Event(),
            lock=threading.Lock(),
            error_event=None,
        )
        retry_transport._active_turns = {
            error_event["threadId"]: retry_context,
        }
        retry_transport._deliver_turn_error({**error_event, "willRetry": True})
        self.assertIsNone(retry_context.error_event)
        self.assertFalse(retry_context.event.is_set())

        reader_transport = object.__new__(CodexAppServerStdioTransport)
        reader_transport._state_lock = threading.RLock()
        reader_context = SimpleNamespace(
            event=threading.Event(),
            lock=threading.Lock(),
            error_event=None,
        )
        reader_transport._active_turns = {
            error_event["threadId"]: reader_context,
        }
        reader_transport._pending = {}
        reader_transport._fatal_error = False
        reader_transport._process = SimpleNamespace(
            stdout=io.StringIO(
                json.dumps({"method": "error", "params": error_event}) + "\n"
            )
        )
        reader_transport._reader_loop()
        self.assertIsNotNone(reader_context.error_event)
        self.assertTrue(reader_context.event.is_set())

        for event_kind in ("error_notification", "failed_completion"):
            with self.subTest(event_kind=event_kind):
                transport = object.__new__(CodexAppServerStdioTransport)
                transport._state_lock = threading.RLock()
                transport._thread_locks = {}
                transport._active_turns = {}
                transport._timeout_seconds = 1.0
                transport._fatal_error = False
                transport._closed = False

                def request(method, params, *, timeout_seconds=None):
                    del params, timeout_seconds
                    self.assertEqual(method, "turn/start")
                    if event_kind == "error_notification":
                        transport._deliver_turn_error(error_event)
                    else:
                        transport._deliver_turn_completion(
                            {
                                "threadId": error_event["threadId"],
                                "turn": {
                                    "id": error_event["turnId"],
                                    "status": "failed",
                                    "items": [],
                                    "error": error,
                                },
                            }
                        )
                    return {"turn": {"id": error_event["turnId"]}}

                transport._request = request
                with self.assertRaises(RuntimeError) as raised:
                    transport.run_turn(
                        thread_id=error_event["threadId"],
                        user_text="synthetic bounded request",
                        additional_context={},
                        output_schema={},
                        reasoning_effort="high",
                        client_metadata={},
                        tool_handler=lambda _name, _arguments: {},
                    )

                diagnostic = raised.exception.provider_diagnostic
                self.assertEqual(diagnostic["reason_code"], "provider_incomplete")
                self.assertEqual(diagnostic["codex_error_kind"], "httpConnectionFailed")
                self.assertEqual(diagnostic["http_status"], 408)
                self.assertIsNone(diagnostic["provider_error_type"])
                self.assertIsNone(diagnostic["provider_error_code"])
                self.assertIsNone(diagnostic["provider_error_param"])
                self.assertEqual(diagnostic["provider_error_message_class"], "unknown")
                rendered = json.dumps(diagnostic, ensure_ascii=False)
                self.assertNotIn(private_message, rendered)
                self.assertNotIn(private_details, rendered)

        from formowl_mail.human_uat_orchestrator import _codex_app_server_error_diagnostic

        for kind in (
            "responseStreamConnectionFailed",
            "responseStreamDisconnected",
            "responseTooManyFailedAttempts",
        ):
            with self.subTest(codex_error_kind=kind):
                diagnostic = _codex_app_server_error_diagnostic(
                    {
                        "message": private_message,
                        "codexErrorInfo": {kind: {"httpStatusCode": 503}},
                    }
                )
                self.assertEqual(diagnostic["codex_error_kind"], kind)
                self.assertEqual(diagnostic["http_status"], 503)
        enum_diagnostic = _codex_app_server_error_diagnostic(
            {"message": private_message, "codexErrorInfo": "rateLimitExceeded"}
        )
        self.assertEqual(enum_diagnostic["codex_error_kind"], "rateLimitExceeded")
        self.assertIsNone(enum_diagnostic["http_status"])
        invalid_status_diagnostic = _codex_app_server_error_diagnostic(
            {
                "message": private_message,
                "codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 599}},
            }
        )
        self.assertEqual(invalid_status_diagnostic["codex_error_kind"], "httpConnectionFailed")
        self.assertIsNone(invalid_status_diagnostic["http_status"])
        unknown_diagnostic = _codex_app_server_error_diagnostic(
            {
                "message": private_message,
                "additionalDetails": private_details,
                "codexErrorInfo": {"unknownFutureVariant": {"httpStatusCode": 599}},
            }
        )
        self.assertNotIn("codex_error_kind", unknown_diagnostic)
        self.assertIsNone(unknown_diagnostic["http_status"])

    def test_app_server_rejects_unknown_tool_and_record_mismatch(self) -> None:
        for transport in (
            _RecordingTransport(
                calls=({"query_text": "query"},),
                final_message=_decision(),
                handler_tool_name="unknown_uat_tool",
            ),
            _RecordingTransport(
                calls=({"query_text": "query"},),
                final_message=_decision(),
                invocation_tool_name="unknown_uat_tool",
            ),
        ):
            with (
                self.subTest(type=type(transport).__name__),
                tempfile.TemporaryDirectory() as workspace,
            ):
                provider = CodexAppServerConversationModel(
                    transport,
                    workspace_dir=workspace,
                )
                with self.assertRaises(RuntimeError):
                    provider.respond(
                        history=(),
                        user_text="request",
                        latest_evidence=None,
                        safety_identifier=f"session-strict-{id(transport)}",
                        evidence_tool=lambda request: {
                            "status": "complete",
                            "citations": ["citation"],
                        },
                    )
                self.assertEqual(transport.deleted_threads, ["thread-1"])

    def test_mail_top_k_status_ok_remains_incomplete_without_exact_contract(self) -> None:
        citation = "citation-mail-top-k"
        transport = _RecordingTransport(
            calls=(
                {
                    "query_text": "standalone amber orchid plan mail lookup",
                    "required_terms": ["amber orchid plan"],
                    "mail_import_session_id": "mail-session",
                },
            ),
            final_message=_decision(
                citations=(citation,),
                coverage_status="complete",
            ),
        )
        with tempfile.TemporaryDirectory() as workspace:
            provider = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            outcome = provider.respond(
                history=(),
                user_text="summarize the amber orchid plan mail",
                latest_evidence=None,
                safety_identifier="session-mail-top-k",
                evidence_tool=lambda request: {
                    "status": "ok",
                    "mail_import_session_id": "mail-session",
                    "evidence_snippets": [{"snippet": "bounded", "citation_id": citation}],
                    "citations": [{"citation_id": citation}],
                },
                formowl_tool_descriptor=_actual_mail_tool_descriptor(),
                authorized_capability_summary={
                    "source_families": ["mail"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["mail-session"],
                },
            )

        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(outcome.coverage_status, "incomplete")
        self.assertEqual(len(outcome.tool_results), 1)

    def test_device_auth_is_provisioned_in_isolated_chatgpt_runtime(self) -> None:
        auth_cache = json.dumps(
            {
                "OPENAI_API_KEY": None,
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": "synthetic-access",
                    "account_id": "synthetic-account",
                    "id_token": "synthetic-id",
                    "refresh_token": "synthetic-refresh",
                },
            }
        )

        def fake_login(*args, **kwargs):
            auth_path = Path(kwargs["env"]["CODEX_HOME"]) / "auth.json"
            auth_path.write_text(auth_cache, encoding="utf-8")
            auth_path.chmod(0o600)
            return subprocess.CompletedProcess(args[0], 0)

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "PATH": os.environ.get("PATH", ""),
                        "OPENAI_API_KEY": "must-not-propagate",
                    },
                    clear=True,
                ),
                mock.patch(
                    "formowl_mail.human_uat_orchestrator.subprocess.run",
                    side_effect=fake_login,
                ) as run,
            ):
                paths = prepare_codex_runtime_state_with_device_auth(
                    codex_command="codex",
                    state_dir=Path(temporary_directory) / "runtime",
                )
                validated = validate_codex_runtime_state(paths.state_dir)
                config = (paths.codex_home / "config.toml").read_text(encoding="utf-8")

                self.assertEqual(
                    run.call_args.args[0],
                    ["codex", "login", "--device-auth"],
                )
                environment = run.call_args.kwargs["env"]
                self.assertEqual(environment["HOME"], environment["CODEX_HOME"])
                self.assertNotIn("OPENAI_API_KEY", environment)
                self.assertEqual(paths.login_method, "chatgpt")
                self.assertEqual(validated, paths)
        self.assertIn('forced_login_method = "chatgpt"', config)
        self.assertEqual(config.count('SKILL.md"\nenabled = false'), 6)
        for skill_name in (
            "imagegen",
            "openai-docs",
            "plugin-creator",
            "review-agent",
            "skill-creator",
            "skill-installer",
        ):
            self.assertIn(f'/{skill_name}/SKILL.md"\nenabled = false', config)

    def test_app_server_command_disables_non_provider_capabilities(self) -> None:
        command = build_hardened_codex_app_server_command("codex")
        disabled = {
            command[index + 1] for index, value in enumerate(command[:-1]) if value == "--disable"
        }
        self.assertTrue(set(_CODEX_DISABLED_FEATURES).issubset(disabled))
        self.assertIn('sandbox_mode="read-only"', command)
        self.assertIn('web_search="disabled"', command)
        self.assertIn("mcp_servers={}", command)

    def test_custom_provider_runtime_is_secretless_and_hash_bound(self) -> None:
        base_url = "https://provider.example.test/v1"
        env_key = "FORMOWL_TEST_PROVIDER_API_KEY"
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = prepare_codex_runtime_state_for_custom_provider(
                state_dir=Path(temporary_directory) / "runtime",
                base_url=base_url,
                env_key=env_key,
            )
            config_path = paths.codex_home / "config.toml"
            config_text = config_path.read_text(encoding="utf-8")
            config = tomllib.loads(config_text)
            marker = json.loads(
                (paths.state_dir / "formowl-uat-codex-runtime-v3.json").read_text(encoding="utf-8")
            )

            self.assertEqual(paths.login_method, "custom_provider")
            self.assertEqual(paths.provider_env_key, env_key)
            self.assertEqual(validate_codex_runtime_state(paths.state_dir), paths)
            self.assertFalse((paths.codex_home / "auth.json").exists())
            self.assertEqual(config["model"], "gpt-5.5")
            self.assertEqual(config["model_provider"], "formowl_uat_custom")
            provider = config["model_providers"]["formowl_uat_custom"]
            self.assertEqual(provider["base_url"], base_url)
            self.assertEqual(provider["wire_api"], "responses")
            self.assertEqual(provider["env_key"], env_key)
            self.assertIs(provider["requires_openai_auth"], False)
            self.assertEqual(
                marker["config_sha256"],
                hashlib.sha256(config_text.encode("utf-8")).hexdigest(),
            )
            self.assertNotIn("auth.json", config_text)

            auth_path = paths.codex_home / "auth.json"
            auth_path.write_text('{"auth_mode":"chatgpt"}', encoding="utf-8")
            auth_path.chmod(0o600)
            with self.assertRaisesRegex(
                ContractValidationError,
                "runtime state integrity check failed",
            ):
                validate_codex_runtime_state(paths.state_dir)
            auth_path.unlink()

            config_path.chmod(0o600)
            config_path.write_text(config_text + "# tampered\n", encoding="utf-8")
            config_path.chmod(0o400)
            with self.assertRaisesRegex(
                ContractValidationError,
                "runtime state integrity check failed",
            ):
                validate_codex_runtime_state(paths.state_dir)

    def test_custom_provider_environment_and_attestation_are_exact(self) -> None:
        base_url = "https://provider.example.test/v1"
        env_key = "FORMOWL_TEST_PROVIDER_API_KEY"
        provider_secret = "synthetic-provider-secret"
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = prepare_codex_runtime_state_for_custom_provider(
                state_dir=Path(temporary_directory) / "runtime",
                base_url=base_url,
                env_key=env_key,
            )
            source = {
                "PATH": os.environ.get("PATH", ""),
                env_key: provider_secret,
                "OTHER_API_KEY": "must-not-propagate",
                "OTHER_TOKEN": "must-not-propagate",
                "OTHER_SECRET": "must-not-propagate",
            }
            environment = build_codex_runtime_environment(
                paths.codex_home,
                source=source,
                provider_env_key=env_key,
            )
            self.assertEqual(environment[env_key], provider_secret)
            self.assertNotIn("OTHER_API_KEY", environment)
            self.assertNotIn("OTHER_TOKEN", environment)
            self.assertNotIn("OTHER_SECRET", environment)

            process = mock.MagicMock()
            process.stdin = mock.MagicMock()
            process.stdout = mock.MagicMock()
            process.stderr = None
            process.poll.return_value = 0
            with (
                mock.patch(
                    "formowl_mail.human_uat_orchestrator.subprocess.Popen",
                    return_value=process,
                ) as popen,
                mock.patch("formowl_mail.human_uat_orchestrator.threading.Thread"),
                mock.patch.object(
                    CodexAppServerStdioTransport,
                    "_request",
                    return_value={},
                ),
                mock.patch.object(CodexAppServerStdioTransport, "_send"),
            ):
                transport = CodexAppServerStdioTransport(
                    command=("codex", "app-server"),
                    cwd=paths.workspace,
                    codex_home=paths.codex_home,
                    environment=source,
                    provider_env_key=env_key,
                    attest_runtime=False,
                )
                transport.close()
            spawned_environment = popen.call_args.kwargs["env"]
            self.assertEqual(spawned_environment[env_key], provider_secret)
            self.assertNotIn("OTHER_API_KEY", spawned_environment)
            self.assertNotIn("OTHER_TOKEN", spawned_environment)
            self.assertNotIn("OTHER_SECRET", spawned_environment)

        config_response = {
            "config": {
                "model": "gpt-5.5",
                "model_provider": "formowl_uat_custom",
                "forced_login_method": None,
                "cli_auth_credentials_store": "file",
                "approval_policy": "never",
                "sandbox_mode": "read-only",
                "web_search": "disabled",
                "mcp_servers": {},
                "analytics": {"enabled": False},
                "apps": {
                    "_default": {
                        "enabled": False,
                        "destructive_enabled": False,
                        "open_world_enabled": False,
                    }
                },
                "features": {name: False for name in _CODEX_DISABLED_FEATURES},
                "model_providers": {
                    "formowl_uat_custom": {
                        "name": "FormOwl UAT custom provider",
                        "base_url": base_url,
                        "wire_api": "responses",
                        "env_key": env_key,
                        "requires_openai_auth": False,
                    }
                },
            }
        }
        attestation = {
            "config_response": config_response,
            "mcp_response": {"data": [], "nextCursor": None},
            "skills_response": {
                "data": [
                    {
                        "cwd": "/tmp/formowl-codex-workspace",
                        "errors": [],
                        "skills": [],
                    }
                ]
            },
            "apps_response": {"data": [], "nextCursor": None},
            "runtime_workspace": Path("/tmp/formowl-codex-workspace"),
            "provider_base_url": base_url,
            "provider_env_key": env_key,
        }
        _assert_hardened_codex_runtime(**attestation)
        unsafe_values = (
            ("model", "other-model"),
            ("model_provider", "other-provider"),
        )
        for key, value in unsafe_values:
            with self.subTest(key=key):
                altered = copy.deepcopy(config_response)
                altered["config"][key] = value
                with self.assertRaisesRegex(RuntimeError, "unsafe configuration"):
                    _assert_hardened_codex_runtime(**(attestation | {"config_response": altered}))
        provider_values = (
            ("base_url", "https://other.example.test/v1"),
            ("wire_api", "chat"),
            ("env_key", "OTHER_API_KEY"),
            ("requires_openai_auth", True),
        )
        for key, value in provider_values:
            with self.subTest(key=key):
                altered = copy.deepcopy(config_response)
                altered["config"]["model_providers"]["formowl_uat_custom"][key] = value
                with self.assertRaisesRegex(RuntimeError, "unsafe configuration"):
                    _assert_hardened_codex_runtime(**(attestation | {"config_response": altered}))

    def test_cli_custom_provider_init_persists_metadata_not_secret(self) -> None:
        base_url = "https://provider.example.test/v1"
        env_key = "FORMOWL_TEST_PROVIDER_API_KEY"
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_dir = Path(temporary_directory) / "runtime"
            paths = SimpleNamespace(
                state_dir=state_dir,
                login_method="custom_provider",
            )
            standard_output = io.StringIO()
            arguments = [
                "mail_human_uat_codex_engine.py",
                "init",
                "--state-dir",
                str(state_dir),
                "--custom-provider",
                "--custom-provider-base-url",
                base_url,
                "--custom-provider-env-key",
                env_key,
            ]
            with (
                mock.patch.object(codex_engine.os, "geteuid", return_value=1000),
                mock.patch.object(codex_engine.sys, "argv", arguments),
                mock.patch.object(
                    codex_engine,
                    "prepare_codex_runtime_state_for_custom_provider",
                    return_value=paths,
                ) as prepare,
                redirect_stdout(standard_output),
            ):
                self.assertEqual(codex_engine.main(), 0)
            prepare.assert_called_once_with(
                state_dir=state_dir,
                base_url=base_url,
                env_key=env_key,
            )
            self.assertNotIn("secret", standard_output.getvalue())


if __name__ == "__main__":
    unittest.main()
