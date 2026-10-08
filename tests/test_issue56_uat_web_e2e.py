from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import _paths  # noqa: F401
from formowl_auth import GoogleIdentity, OAuthInvitation
from formowl_auth.security import normalize_verified_email
from formowl_gateway.issue56_diagnostic import (
    Issue56DiagnosticConfig,
    Issue56DiagnosticOAuthBridge,
    Issue56DiagnosticState,
)
import formowl_gateway.issue56_uat_runtime as uat_runtime_module
import formowl_gateway.issue56_sealed_source_loader as sealed_loader
import formowl_gateway.runtime as runtime_module
from formowl_gateway.remote import create_connected_mcp_application
from formowl_contract import (
    ContractValidationError,
    User,
    WorkspaceMember,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_gateway.issue56_uat_runtime import (
    _ConversationState,
    _advance_conversation_state,
    Issue56TemporaryLanQueryService,
    Issue56UatQueryService,
    _browser_projection,
    _classify_mcp_failure_result,
    _governed_mail_evidence_records,
    _mcp_query_request,
    _retained_authorized_evidence,
    _safe_provider_diagnostic,
    create_issue56_temporary_lan_query_service,
)
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_gateway.semantic import SemanticMcpGateway
from formowl_mail import build_mail_evidence_query_handler
from formowl_mail.human_uat_http import (
    _normalize_query_response,
    _render_page,
    create_mail_human_uat_http_server,
)
from formowl_mail.human_uat_orchestrator import (
    CodexAppServerConversationModel,
    CodexAppServerStdioTransport,
    CodexResponsesConversationModel,
    _UatTurnRequestContractBinder,
    _source_fallback_exhausted,
    UatConversationMessage,
    UatConversationOutcome,
    UatEvidenceToolRequest,
)
from formowl_mail import hybrid
import formowl_mail.query as mail_query_module
from formowl_mail.query import RevisionOwnedMailSourceScan
from formowl_retrieval.gateway import source_evidence_double_check
import formowl_retrieval.gateway as retrieval_gateway_module
from formowl_mail.issue56_sealed_source import (
    IngestionRevisionSourceRecords,
    build_issue56_ingestion_revision,
)
from formowl_mail.semantic_plan import validate_semantic_request_contract
import formowl_mail.issue56_sealed_source as sealed_source
from oauth_harness import TransactionAwareMemoryRepository
import scripts.issue56_uat_web as uat_web_script
from test_connected_runtime import (
    _FakeConnection,
    _FakeHttpClient,
    _FakeRepository,
    _write_runtime_environment,
)
from test_mail_evidence_mcp_gateway import NOW, _mail_bundle, _mail_session_grant
from test_oauth_bridge_service import StubGoogleClient
from test_issue56_sealed_source_loader_e2e import (
    _loader_environment,
    _prepare_package,
    _sha256_path,
)
from test_issue56_semantic_execution_e2e import _contract_only_runtime
from test_issue56_uat_handler_composition import (
    Issue56UatHandlerCompositionTests,
    _completed_registered_text_revision_fixture,
    _source_start_preparation_fixture,
)
import test_issue56_sealed_source_loader_e2e as sealed_fixture
from test_issue56_supplemental_attachment_table_loader_e2e import (
    _HEADER,
    _IDENTIFIER,
    _PERMISSION_SCOPE,
    _VALUE,
    _write_supplemental_partition,
)

_EXTERNAL_PROVIDER_ACCEPTANCE_FLAG = "FORMOWL_ISSUE56_EXTERNAL_PROVIDER_ACCEPTANCE"
_EXTERNAL_PROVIDER_BASE_URL_ENV = "FORMOWL_ISSUE56_EXTERNAL_PROVIDER_BASE_URL"
_EXTERNAL_PROVIDER_API_KEY_ENV_ENV = "FORMOWL_ISSUE56_EXTERNAL_PROVIDER_API_KEY_ENV"
_PROVIDER_MODEL = "gpt-5.5"
_PROVIDER_REASONING_EFFORT = "high"
_EXTERNAL_PROVIDER_MODEL = _PROVIDER_MODEL
_CHROMIUM_ACCEPTANCE_RUNNER = (
    Path(__file__).resolve().parents[1] / "scripts" / "issue56_uat_chromium_acceptance.js"
)


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _with_authorized_source_families(handler, *source_families):
    handler.authorized_capability_summary = {
        "source_families": list(source_families),
    }
    return handler


def _external_provider_acceptance_config(test_case: unittest.TestCase) -> tuple[str, str]:
    """Read an opt-in provider endpoint and credential from process memory only."""

    if os.environ.get(_EXTERNAL_PROVIDER_ACCEPTANCE_FLAG) != "1":
        test_case.skipTest(
            "external provider browser acceptance is opt-in; "
            f"set {_EXTERNAL_PROVIDER_ACCEPTANCE_FLAG}=1 to run it"
        )
    base_url = os.environ.get(_EXTERNAL_PROVIDER_BASE_URL_ENV, "").strip()
    credential_env_name = os.environ.get(_EXTERNAL_PROVIDER_API_KEY_ENV_ENV, "").strip()
    if not base_url or not credential_env_name:
        test_case.fail(
            "external provider acceptance is enabled but its endpoint or "
            "credential environment selector is missing"
        )
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", credential_env_name) is None:
        test_case.fail("external provider credential environment selector is invalid")
    api_key = os.environ.get(credential_env_name, "")
    if not api_key.strip():
        test_case.fail("external provider credential environment value is unavailable")
    return base_url, api_key


class Issue56UatTerminalTraceTests(unittest.TestCase):
    def _diagnostic(self):
        def snapshot(count):
            return {"citation_count": count, "citation_fingerprint": _sha256_text(str(count))}

        return {
            "provider_status": "completed",
            "provider_phase_timings": [{"phase": "finalization", "elapsed_ms": 25.0}],
            "mcp_citation_stages": [{
                "call_index": 1, "elapsed_ms": 10.0, "projection_result": "reduced",
                "raw_governed": snapshot(100), "compacted_presented": snapshot(2),
            }],
            "finalization_validation": [{
                "final_model": snapshot(2), "available_governed": snapshot(2),
                "validation_result": "passed", "repair_attempted": False,
            }],
        }

    def _service(self, outcome):
        service = object.__new__(Issue56TemporaryLanQueryService)
        service._application = object()
        service._conversation_model = SimpleNamespace(
            respond=MagicMock(return_value=outcome), discard_conversation=MagicMock(),
        )
        service._lock = threading.RLock()
        service._query_lock = threading.Lock()
        service._sessions = {"private-session": _ConversationState(
            expires_at=uat_runtime_module.time.monotonic() + 60,
        )}
        service._behavior_log_path = None
        service._source_binding_fingerprint = None
        service.last_failure_class = None
        return service

    def _make_outcome(self):
        return UatConversationOutcome(
            response_kind="answer", answer_text="GENERIC-ANSWER",
            display_format="narrative", model_name="synthetic",
            provider_diagnostic=self._diagnostic(),
        )

    def test_terminal_traces_precede_projection_and_return_without_raw_interactions(self):
        service = self._service(self._make_outcome())
        stderr = io.StringIO()
        result = {"status": "ok", "answer": "GENERIC-ANSWER", "citations": [],
                  "clarification": None}

        def project(*args, **kwargs):
            events = [json.loads(line) for line in stderr.getvalue().splitlines()]
            self.assertEqual([event["event"] for event in events],
                             ["issue56_private_uat_provider_terminal_trace"])
            return result

        with (
            redirect_stderr(stderr),
            patch.object(uat_runtime_module, "_query_agent_runtime_context",
                         return_value=(None, None)),
            patch.object(uat_runtime_module, "_browser_projection", side_effect=project),
        ):
            actual = service.ask("PRIVATE-PROMPT", session_id="private-session")
        self.assertEqual(actual["answer"], result["answer"])
        events = [json.loads(line) for line in stderr.getvalue().splitlines()]
        self.assertEqual([event["event"] for event in events], [
            "issue56_private_uat_provider_terminal_trace",
            "issue56_private_uat_turn_terminal_trace",
        ])
        self.assertEqual([event["status"] for event in events], ["answer", "ok"])
        for event in events:
            self.assertGreaterEqual(event["elapsed_ms"], 0)
            diagnostic = event["provider_diagnostic"]
            stage = diagnostic["mcp_citation_stages"][0]
            self.assertEqual(stage["raw_governed"]["citation_count"], 100)
            self.assertEqual(stage["compacted_presented"]["citation_count"], 2)
            self.assertEqual(diagnostic["finalization_validation"][0]["validation_result"],
                             "passed")
            self.assertEqual(diagnostic["provider_phase_timings"][0]["elapsed_ms"], 25)
            assert_no_public_raw_references(event)
        for private in ("PRIVATE-PROMPT", "GENERIC-ANSWER", "private-session"):
            self.assertNotIn(private, stderr.getvalue())

    def test_terminal_trace_rejects_injected_text_and_invalid_metadata(self):
        private = "PRIVATE-CONTENT /tmp/private.txt api_key=SECRET"
        diagnostic = self._diagnostic()
        diagnostic.update({"reason_code": "PRIVATE_REASON", "provider_status": private,
                           "prompt": private, "session_id": private, "citations": [private]})
        diagnostic["provider_phase_timings"].append({"phase": private, "elapsed_ms": 1})
        diagnostic["mcp_citation_stages"][0]["raw_governed"]["citations"] = [private]
        diagnostic["finalization_validation"][0]["answer"] = private
        outcome = SimpleNamespace(response_kind=private, provider_diagnostic=diagnostic)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            uat_runtime_module._emit_private_uat_terminal_trace(
                "provider", started_at=uat_runtime_module.time.perf_counter(),
                outcome=outcome, mcp_call_count=True, failure_class=private,
            )
            diagnostic["mcp_citation_stages"][0]["raw_governed"]["citation_count"] = 101
            diagnostic["finalization_validation"][0]["validation_result"] = private
            uat_runtime_module._emit_private_uat_terminal_trace(
                "turn", started_at=float("nan"), outcome=outcome,
                result={"status": private}, mcp_call_count=4,
            )
        events = [json.loads(line) for line in stderr.getvalue().splitlines()]
        self.assertEqual(len(events), 2)
        self.assertEqual([event["status"] for event in events], ["unknown", "unknown"])
        self.assertNotIn("elapsed_ms", events[1])
        self.assertNotIn("mcp_citation_stages", events[1]["provider_diagnostic"])
        self.assertEqual(events[1]["provider_diagnostic"]["finalization_validation"], [])
        for event in events:
            self.assertNotIn("mcp_call_count", event)
            self.assertNotIn("failure_class", event)
            assert_no_public_raw_references(event)
        self.assertNotIn("PRIVATE", stderr.getvalue())
        self.assertNotIn("SECRET", stderr.getvalue())

    def test_terminal_trace_preserves_allowlisted_reason_when_attempt_timing_is_invalid(self):
        diagnostic = self._diagnostic()
        diagnostic.update({
            "reason_code": "transport_timeout", "stop_reason": "provider_timeout",
            "provider_attempt_count": 1,
            "provider_attempts": [{
                "attempt": 1, "elapsed_ms": 120_114.008, "outcome": "timeout",
                "response_status": "unknown", "function_call_count": 0,
                "tool_choice": {"tool_choice": "none", "selected_tool": "none",
                                "offered_tool_count": 0,
                                "offered_tool_fingerprint": _sha256_text("no-tools")},
            }],
        })
        outcome = replace(self._make_outcome(), provider_diagnostic=diagnostic)
        for reason in ("transport_timeout", "turn_budget_exhausted"):
            diagnostic["reason_code"] = reason
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                uat_runtime_module._emit_private_uat_terminal_trace(
                    "provider", started_at=uat_runtime_module.time.perf_counter() - 121,
                    outcome=outcome,
                )
            event = json.loads(stderr.getvalue())
            self.assertGreater(event["elapsed_ms"], 120_000)
            safe = event["provider_diagnostic"]
            self.assertEqual(safe["reason_code"], reason)
            self.assertEqual(safe["stop_reason"], "provider_timeout")
            self.assertEqual(safe["provider_attempt_count"], 1)
            self.assertEqual(safe["provider_attempts"], [])
            self.assertFalse(safe["provider_attempts_valid"])

    def test_terminal_logging_failure_cannot_replace_success(self):
        service = self._service(self._make_outcome())
        with (
            patch.object(uat_runtime_module, "_query_agent_runtime_context",
                         return_value=(None, None)),
            patch.object(uat_runtime_module, "print", side_effect=BrokenPipeError(), create=True),
        ):
            result = service.ask("GENERIC-QUERY", session_id="private-session")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["answer"], "GENERIC-ANSWER")
        with patch.object(uat_runtime_module, "_safe_provider_diagnostic",
                          side_effect=RuntimeError("bad diagnostic")):
            uat_runtime_module._emit_private_uat_terminal_trace(
                "provider", started_at=uat_runtime_module.time.perf_counter(),
                outcome=self._make_outcome(),
            )

    def test_turn_trace_preserves_original_exception_and_provider_trace_before_projection_failure(self):
        for failing_phase in ("provider", "projection"):
            with self.subTest(failing_phase=failing_phase):
                service = self._service(self._make_outcome())
                error = TimeoutError("PRIVATE-ERROR /tmp/private.txt")
                if failing_phase == "provider":
                    service._conversation_model.respond.side_effect = error
                stderr = io.StringIO()
                with (
                    redirect_stderr(stderr),
                    patch.object(uat_runtime_module, "_query_agent_runtime_context",
                                 return_value=(None, None)),
                    patch.object(uat_runtime_module, "_browser_projection", side_effect=error),
                    self.assertRaises(TimeoutError) as caught,
                ):
                    service.ask("PRIVATE-PROMPT", session_id="private-session")
                self.assertIs(caught.exception, error)
                events = [json.loads(line) for line in stderr.getvalue().splitlines()]
                terminals = [event for event in events if "terminal_trace" in event["event"]]
                self.assertEqual(len(terminals), 1 if failing_phase == "provider" else 2)
                self.assertEqual(terminals[-1]["event"], "issue56_private_uat_turn_terminal_trace")
                self.assertEqual(terminals[-1]["status"], "error")
                self.assertNotIn("PRIVATE", stderr.getvalue())


class Issue56UatMailSourceRefAdmissionTests(unittest.TestCase):
    def test_governed_mail_root_refs_are_normalized_and_preserved(self) -> None:
        helper = uat_web_script._accepted_governed_mail_root_source_ref
        cases = [
            {
                "source_system": "formowl_upload_session",
                "source_type": "mail_archive_upload",
                "source_id": "upload_mail_1",
                "source_key": "upload_mail_1",
            },
            {
                "source_system": "local",
                "source_type": "file",
                "source_id": "archive.pst",
                "source_key": "archive.pst",
            },
            {
                "source_system": "local_folder_inbox",
                "source_type": "file_content",
                "source_id": "sha256:" + "a" * 64,
            },
        ]
        for source_ref in cases:
            with self.subTest(source_system=source_ref["source_system"]):
                self.assertEqual(helper(source_ref), source_ref)

    def test_invalid_mail_root_refs_fail_closed(self) -> None:
        helper = uat_web_script._accepted_governed_mail_root_source_ref
        invalid = [
            {"source_system": "unknown", "source_type": "file",
             "source_id": "archive.pst", "source_key": "archive.pst"},
            {"source_system": "local", "source_type": "file",
             "source_id": "/tmp/archive.pst", "source_key": "archive.pst"},
            {"source_system": "local", "source_type": "file",
             "source_id": "archive.pst", "source_key": "https://example.test/x"},
            {"source_system": "local_folder_inbox", "source_type": "file_content",
             "source_id": "archive.pst"},
            {"source_system": "local", "source_type": "file",
             "source_id": "archive.pst"},
            {"source_system": "formowl_upload_session", "source_type": "mail_archive",
             "source_id": ""},
        ]
        for source_ref in invalid:
            with self.subTest(source_ref=source_ref):
                with self.assertRaises(ValueError):
                    helper(source_ref)


class _RecordingGptQueryAgent:
    model_name = f"codex:{_PROVIDER_MODEL}"

    def __init__(
        self,
        *,
        standalone_query: str,
        table_query=None,
    ) -> None:
        self.standalone_query = standalone_query
        self.table_query = table_query
        self.user_texts: list[str] = []
        self.tool_queries: list[str] = []
        self.tool_table_queries: list[object] = []
        self.closed = False

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
            latest_evidence,
            safety_identifier,
            formowl_tool_descriptor,
            authorized_capability_summary,
        )
        self.user_texts.append(user_text)
        if user_text == "你好":
            return UatConversationOutcome(
                response_kind="answer",
                answer_text="你好，請告訴我想查詢的資料。",
                display_format="narrative",
                model_name=self.model_name,
            )
        request = UatEvidenceToolRequest(
            query_text=self.standalone_query,
            table_query=self.table_query,
        )
        evidence = evidence_tool(request)
        self.tool_queries.append(request.query_text)
        self.tool_table_queries.append(request.table_query)
        inventory = evidence.get("exact_inventory")
        items = inventory.get("items", ()) if isinstance(inventory, dict) else ()
        citations = tuple(evidence.get("citations", ()))
        if not items or not citations:
            return UatConversationOutcome(
                response_kind="clarification",
                answer_text="目前沒有可引用的來源結果，請補充查詢範圍。",
                display_format="narrative",
                model_name=self.model_name,
                coverage_status="incomplete",
                coverage_note="目前沒有足夠的可引用來源。",
                tool_requests=(request,),
                tool_results=(evidence,),
            )
        values = items[0]["structured_values"]
        answer = "\n".join(f"{value['field']}: {value['value']}" for value in values)
        coverage_complete = (
            evidence.get("status") == "complete" and inventory.get("coverage_status") == "complete"
        )
        return UatConversationOutcome(
            response_kind="answer",
            answer_text=answer,
            display_format="narrative",
            model_name=self.model_name,
            citation_ids=(citations[0],),
            coverage_status="complete" if coverage_complete else "incomplete",
            coverage_note="" if coverage_complete else "來源涵蓋範圍仍不完整。",
            tool_requests=(request,),
            tool_results=(evidence,),
        )

    def discard_conversation(self, safety_identifier) -> None:
        del safety_identifier

    def close(self) -> None:
        self.closed = True


class _SessionConversationModel:
    model_name = "synthetic-session-model"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.discarded: list[str] = []

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
            evidence_tool,
            formowl_tool_descriptor,
            authorized_capability_summary,
        )
        self.calls.append(
            {
                "history": tuple(history),
                "user_text": user_text,
                "latest_evidence": latest_evidence,
                "safety_identifier": safety_identifier,
            }
        )
        if user_text == "第六輪觸發安全失敗":
            raise RuntimeError("private backend failure detail")
        return UatConversationOutcome(
            response_kind="answer",
            answer_text=f"回答：{user_text}",
            display_format="narrative",
            model_name=self.model_name,
            coverage_status="not_applicable",
        )

    def discard_conversation(self, safety_identifier: str) -> None:
        self.discarded.append(safety_identifier)

    def close(self) -> None:
        return


class Issue56UatWebE2ETests(unittest.TestCase):
    def test_public_uat_mcp_call_is_bounded_before_http_projection(self) -> None:
        release = threading.Event()

        class BlockingClient:
            def post(self, path, **kwargs):
                del path, kwargs
                release.wait(timeout=2)
                raise RuntimeError("synthetic MCP stop")

        service = object.__new__(Issue56UatQueryService)
        service._client = BlockingClient()
        service.request_count = 0
        started = uat_runtime_module.time.monotonic()
        with self.assertRaises(uat_runtime_module._UatMcpTimeout):
            service._call(
                UatEvidenceToolRequest(query_text="synthetic bounded query"),
                bearer="synthetic-bearer",
                deadline_monotonic=started + 0.05,
            )
        elapsed = uat_runtime_module.time.monotonic() - started
        release.set()

        self.assertLess(elapsed, 1.0)
        self.assertEqual(service.request_count, 1)

    def test_chromium_runner_self_check_enforces_safe_browser_contract(self) -> None:
        """Exercise only the runner contract; live acceptance still uses --live."""

        runner = _CHROMIUM_ACCEPTANCE_RUNNER
        self.assertTrue(runner.is_file(), "repository-owned Chromium runner is missing")
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for the runner self-check")

        completed = subprocess.run(
            [node, str(runner), "--self-check"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={
                "PATH": os.environ.get("PATH", os.defpath),
                "HOME": tempfile.gettempdir(),
                "TMPDIR": tempfile.gettempdir(),
            },
        )
        self.assertEqual(completed.returncode, 0, "runner self-check failed")
        self.assertFalse(completed.stderr, "runner self-check wrote stderr")
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        self.assertEqual(lines, ['{"status":"tooling_self_check_passed"}'])
        self.assertNotIn("prompt", completed.stdout.casefold())
        self.assertNotIn("private", completed.stdout.casefold())
        self.assertNotIn("secret", completed.stdout.casefold())

    def test_repo_chromium_runner_local_basic_browser_lifecycle(self) -> None:
        """Rendered synthetic browser diagnostic; never contacts a provider."""

        runner = _CHROMIUM_ACCEPTANCE_RUNNER
        self.assertTrue(runner.is_file(), "repository-owned Chromium runner is missing")
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for the Chromium browser test")

        conversation_model = _SessionConversationModel()
        with (
            patch.object(
                uat_runtime_module,
                "build_issue56_production_semantic_handlers",
                return_value=(
                    _with_authorized_source_families(
                        lambda _arguments: {},
                        "mail",
                    ),
                    None,
                ),
            ),
            create_issue56_temporary_lan_query_service(
                conversation_model,
            ) as service,
        ):
            server = create_mail_human_uat_http_server("127.0.0.1", 0, service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertNotEqual(server.server_address[1], 0)

            reset_probe: dict[str, object] = {}
            actual_reset = service.reset_browser_conversation

            def seed_synthetic_evidence_then_reset(session_id):
                with service._lock:
                    state = service._sessions.get(session_id)
                    reset_probe["session_id"] = session_id
                    reset_probe["had_history"] = bool(state and state.history)
                    if state is not None:
                        state.latest_evidence = {
                            "synthetic_reset_probe": True,
                            "results": (),
                        }
                    reset_probe["had_evidence"] = bool(state and state.latest_evidence is not None)
                return actual_reset(session_id)

            process = None
            try:
                with patch.object(
                    service,
                    "reset_browser_conversation",
                    side_effect=seed_synthetic_evidence_then_reset,
                ):
                    process = subprocess.Popen(
                        [node, str(runner), "--live", "--basic-only"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env={
                            "PATH": os.environ.get("PATH", os.defpath),
                            "HOME": tempfile.gettempdir(),
                            "TMPDIR": tempfile.gettempdir(),
                            "FORMOWL_UAT_URL": origin + "/",
                            "FORMOWL_UAT_TIMEOUT_MS": "10000",
                        },
                        start_new_session=True,
                    )
                    try:
                        stdout, stderr = process.communicate(timeout=40)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.communicate()
                        self.fail("synthetic Chromium runner exceeded 40 seconds")
            finally:
                if process is not None and process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(process.returncode, 0, stdout)
            self.assertFalse(stderr, "Chromium runner wrote unexpected stderr")
            lines = [line for line in stdout.splitlines() if line.strip()]
            self.assertEqual(len(lines), 1, "runner must emit one safe result")
            result = json.loads(lines[0])
            self.assertEqual(result["status"], "basic_only_passed")
            self.assertEqual(result["acceptance_surface"], "basic_only")
            self.assertEqual(result["mail_acceptance"], "not_run")
            self.assertEqual(result["http_status"], 200)
            self.assertTrue(result["visible_text_pass"])
            self.assertTrue(result["ordinary_mcp_zero"])
            self.assertEqual(result["tool_count"], 0)
            self.assertEqual(result["citation_count"], 0)
            self.assertEqual(result["reload_transcript_count"], 1)
            self.assertEqual(result["reload_visible_turn_count"], 1)
            self.assertEqual(result["reset_transcript_count"], 0)
            self.assertEqual(result["reset_visible_article_count"], 0)
            self.assertEqual(result["post_reset_transcript_count"], 1)
            self.assertEqual(result["post_reset_visible_turn_count"], 1)
            self.assertTrue(result["reload_content_preserved"])

            self.assertTrue(reset_probe["had_history"])
            self.assertTrue(reset_probe["had_evidence"])
            old_session_id = reset_probe["session_id"]
            self.assertNotIn(old_session_id, service._sessions)
            self.assertEqual(len(service._sessions), 1)
            current_state = next(iter(service._sessions.values()))
            self.assertIsNone(current_state.latest_evidence)
            self.assertEqual(len(current_state.turns), 1)
            self.assertEqual(len(current_state.history), 2)

            self.assertEqual(len(conversation_model.calls), 2)
            first_call, post_reset_call = conversation_model.calls
            self.assertEqual(first_call["history"], ())
            self.assertEqual(first_call["latest_evidence"], None)
            self.assertEqual(post_reset_call["history"], ())
            self.assertEqual(post_reset_call["latest_evidence"], None)
            self.assertNotEqual(
                first_call["safety_identifier"],
                post_reset_call["safety_identifier"],
            )
            self.assertEqual(
                conversation_model.discarded,
                [first_call["safety_identifier"]],
            )
            self.assertEqual(service.request_count, 0)
            self.assertEqual(service.last_mcp_statuses, ())

    def test_source_only_preparation_mail_and_text_survive_browser_lifecycle(self) -> None:
        """Real synthetic jobs and normal MCP; no external provider/live UAT."""
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for the Chromium browser test")
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(
                Path(directory),
                mail_text="Synthetic audit approval links CASE-421 and CASE-422.",
            )
            revision = sealed_source.load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
            )
            self.assertIsNone(revision.session)
            self.assertIsNone(revision.graph_build)
            selector = revision.source_records.authorized_mail_import_session_ids[0]
            body = next(item for item in fixture.observations
                        if item.observation_type == "email_body_segment")
            paragraph = next(item for item in fixture.observations
                             if item.observation_type == "paragraph")
            expected = {
                "mail": {
                    "source_family": "mail", "answer_fingerprint": _sha256_text(body.text),
                    "citation_fingerprints": [_sha256_text(
                        "mailcitation_" + sha256_json({
                            "mail_import_session_id": selector,
                            "source_observation_id": body.observation_id,
                        })[-24:],
                    )],
                },
                "document": {
                    "source_family": "document_text",
                    "answer_fingerprint": _sha256_text(paragraph.text),
                    "citation_fingerprints": [_sha256_text(sha256_json(paragraph.to_dict()))],
                },
            }
            tool_results = []

            class SourceStartConversationModel:
                model_name = "provider-free-source-start-browser-model"

                def respond(self, *, user_text, evidence_tool, **_kwargs):
                    if user_text == "你好，今天過得如何？":
                        return UatConversationOutcome(
                            response_kind="answer", answer_text="你好，今天很好，隨時可以幫忙。",
                            display_format="narrative", model_name=self.model_name,
                            coverage_status="not_applicable",
                        )
                    mail = user_text == "Organize the authorized synthetic mail evidence."
                    request = UatEvidenceToolRequest(
                        tool_name="query_mail_evidence" if mail else "query_effective_graph_view",
                        query_text="synthetic audit approval" if mail else "written owner approval",
                        mail_import_session_id=selector if mail else None,
                        required_terms=("synthetic",) if mail else None,
                        request_contract={
                            "original_query_hash": sha256_json(user_text),
                            "query_class": "evidence_lookup",
                            "source_family_scope": ["mail" if mail else "document_text"],
                            "requested_fields": ["acceptance_condition"],
                            "maximum_claim_strength": "cited_evidence",
                        },
                    )
                    result = evidence_tool(request)
                    tool_results.append(result)
                    evidence = result.get("evidence_snippets") or result.get("evidence") or ()
                    citations = tuple(
                        item["citation_id"] if isinstance(item, Mapping) else item
                        for item in result.get("citations", ())
                    )
                    if not evidence or not citations:
                        raise AssertionError("source-start MCP returned no governed evidence")
                    return UatConversationOutcome(
                        response_kind="answer", answer_text=evidence[0]["snippet"],
                        display_format="narrative", model_name=self.model_name,
                        citation_ids=(citations[0],), coverage_status="incomplete",
                        coverage_note="合成來源範圍不代表完整資料。",
                        tool_requests=(request,), tool_results=(result,),
                    )

                def close(self):
                    pass

                def discard_conversation(self, _safety_identifier):
                    pass

            with (
                patch.object(sealed_loader, "source_evidence_double_check",
                             wraps=source_evidence_double_check) as core,
                create_issue56_temporary_lan_query_service(
                    SourceStartConversationModel(), ingestion_revision=revision,
                ) as service,
            ):
                server = create_mail_human_uat_http_server("127.0.0.1", 0, service)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                process = None
                try:
                    process = subprocess.Popen(
                        [node, str(_CHROMIUM_ACCEPTANCE_RUNNER), "--live",
                         "--synthetic-source-neutral"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        env={
                            "PATH": os.environ.get("PATH", os.defpath),
                            "HOME": tempfile.gettempdir(), "TMPDIR": tempfile.gettempdir(),
                            "FORMOWL_UAT_URL": (
                                f"http://{server.server_address[0]}:{server.server_address[1]}/"
                            ),
                            "FORMOWL_UAT_TIMEOUT_MS": "15000",
                            "FORMOWL_UAT_EXPECTED_EVIDENCE_BINDINGS": json.dumps(expected),
                        },
                        start_new_session=True,
                    )
                    try:
                        stdout, stderr = process.communicate(timeout=70)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.communicate()
                        self.fail("synthetic source-start Chromium runner exceeded 70 seconds")
                finally:
                    if process is not None and process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.communicate()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
                self.assertEqual(process.returncode, 0, stdout)
                self.assertFalse(stderr)
                result = json.loads(stdout)
                self.assertEqual(result["status"], "source_neutral_passed")
                self.assertTrue(result["mail_source_binding_verified"])
                self.assertTrue(result["document_source_binding_verified"])
                self.assertTrue(result["ordinary_mcp_zero"])
                self.assertEqual((result["mail_tool_count"], result["document_tool_count"]), (1, 1))
                self.assertEqual(result["reload_transcript_count"], 3)
                self.assertTrue(result["reload_content_preserved"])
                self.assertEqual((result["reset_transcript_count"],
                                  result["post_reset_transcript_count"]), (0, 1))
                self.assertEqual(core.call_count, 2)
                self.assertEqual(len(tool_results), 2)
                self.assertEqual(service.request_count, 0)

    def test_repo_chromium_runner_source_neutral_mail_and_document_rechecks(self) -> None:
        """Render both governed source families through one real MCP session."""

        runner = _CHROMIUM_ACCEPTANCE_RUNNER
        self.assertTrue(runner.is_file(), "repository-owned Chromium runner is missing")
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for the Chromium browser test")

        mail_prompt = "Organize the authorized synthetic mail evidence."
        document_prompt = "Find the acceptance condition in the authorized project document."
        ordinary_prompt = "你好，今天過得如何？"
        document_query = "written owner approval"
        mail_query = "synthetic audit approval"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "registered-text").mkdir(parents=True, exist_ok=True)
            asset, text_observations, job_authority = _completed_registered_text_revision_fixture(
                root / "registered-text",
                owner_user_id=sealed_loader.APPROVER_ACTOR,
            )
            paragraph = next(
                item for item in text_observations if item.observation_type == "paragraph"
            )
            mail_case = Issue56UatHandlerCompositionTests()
            _, _, mail_fixture_records, mail_selector, _, mail_hash = (
                mail_case._revision_owned_mail_fixture(
                    source_text=("Synthetic audit approval links CASE-421 and CASE-422."),
                    subject="Synthetic audit approval",
                )
            )
            mail_observation = mail_fixture_records.observation
            text_authority_fingerprint = sha256_json(
                {
                    "asset_id": asset.asset_id,
                    "asset_content_hash": asset.content_hash,
                    "completed_job_fingerprint": job_authority.job_fingerprint,
                    "observation_hashes": sorted(
                        sha256_json(item.to_dict()) for item in text_observations
                    ),
                }
            )
            source_authority_fingerprint = sha256_json(
                {
                    "registered_asset_revision_fingerprint": (text_authority_fingerprint),
                    "mail_observation_hash": mail_hash,
                }
            )
            expected_evidence_bindings = {
                "mail": {
                    "source_family": "mail",
                    "answer_fingerprint": _sha256_text(mail_observation.text),
                    "citation_fingerprints": [
                        _sha256_text(
                            "mailcitation_"
                            + sha256_json(
                                {
                                    "mail_import_session_id": mail_selector,
                                    "source_observation_id": mail_observation.observation_id,
                                }
                            )[-24:]
                        )
                    ],
                },
                "document": {
                    "source_family": "document_text",
                    "answer_fingerprint": _sha256_text(paragraph.text),
                    "citation_fingerprints": [_sha256_text(sha256_json(paragraph.to_dict()))],
                },
            }
            runtime = _contract_only_runtime()
            with (
                patch.object(
                    sealed_source,
                    "load_issue56_target_runtime_components",
                    return_value=runtime,
                ),
                patch.object(
                    hybrid,
                    "_load_pinned_issue56_runtime_components",
                    return_value=runtime,
                ),
            ):
                revision = build_issue56_ingestion_revision(
                    observations=(mail_observation, *text_observations),
                    bundles=(),
                    source_binding={
                        "source_authority_fingerprint": source_authority_fingerprint,
                        "registered_asset_revision_fingerprint": (text_authority_fingerprint),
                        "mail_observation_hash": mail_hash,
                        "extraction_coverage": {
                            "source_completeness_certified": False,
                        },
                    },
                    requester_user_id=sealed_loader.APPROVER_ACTOR,
                    workspace_id=sealed_loader.WORKSPACE_ID,
                    source_authority_fingerprint=source_authority_fingerprint,
                    retrieval_observation_ids=(
                        next(
                            item for item in text_observations if item.observation_type == "heading"
                        ).observation_id,
                    ),
                )

            lineages = {
                item.source_observation_id: item for item in revision.session.occurrence_lineages
            }

            source_reader_calls = []

            class MixedSourceRecords:
                authorized_mail_import_session_ids = (mail_selector,)

                def observation_for_hash(self, value):
                    return mail_observation if value == mail_hash else None

                def observation_hash(self, value):
                    return mail_hash if value == mail_observation.observation_id else None

                def lineage(self, value):
                    return lineages[value]

                def mail_import_session_id_for_observation(self, value):
                    return mail_selector if value == mail_observation.observation_id else None

                def scan_authorized_mail_observations(
                    self,
                    *,
                    max_observations,
                    deadline_monotonic=None,
                    mail_import_session_id=None,
                    observation_callback=None,
                ):
                    del max_observations, deadline_monotonic
                    if mail_import_session_id != mail_selector:
                        return RevisionOwnedMailSourceScan((), 0, True)
                    if observation_callback is None:
                        return RevisionOwnedMailSourceScan(
                            ((mail_observation, mail_selector),), 1, True
                        )
                    if not observation_callback(mail_observation, mail_selector):
                        return RevisionOwnedMailSourceScan((), 1, False, "callback")
                    return RevisionOwnedMailSourceScan((), 1, True)

                def scan_authorized_observations(
                    self,
                    *,
                    source_family,
                    max_observations,
                    deadline_monotonic=None,
                    source_scope_ids=(),
                    mail_import_session_id=None,
                    observation_callback=None,
                ):
                    source_reader_calls.append(source_family)
                    if source_family == "mail":
                        return self.scan_authorized_mail_observations(
                            max_observations=max_observations,
                            deadline_monotonic=deadline_monotonic,
                            mail_import_session_id=mail_import_session_id,
                            observation_callback=observation_callback,
                        )
                    if source_family != "document_text":
                        raise AssertionError("document recovery used the wrong source family")
                    if mail_import_session_id is not None:
                        raise AssertionError("document recovery received a mail selector")
                    if "project_document" not in source_scope_ids:
                        raise AssertionError("document scope was not preserved")
                    selected = []
                    scanned = 0
                    for observation in job_authority.open_reader().iter_observations():
                        scanned += 1
                        if observation_callback is None:
                            selected.append((observation, "project_document"))
                        elif not observation_callback(observation, "project_document"):
                            return RevisionOwnedMailSourceScan((), scanned, False, "callback")
                    return RevisionOwnedMailSourceScan(tuple(selected), scanned, True)

            revision = replace(
                revision,
                job_authorities=(job_authority,),
                source_records=MixedSourceRecords(),
            )

            class SourceNeutralConversationModel:
                model_name = "provider-free-source-neutral-browser-model"

                def __init__(self):
                    self.calls = []
                    self.requests = []
                    self.tool_results = []
                    self.discarded = []

                @staticmethod
                def citation_ids(result):
                    values = []
                    for citation in result.get("citations", ()):
                        if isinstance(citation, str):
                            values.append(citation)
                        elif isinstance(citation, Mapping):
                            value = citation.get("citation_id") or citation.get("citation_hash")
                            if isinstance(value, str):
                                values.append(value)
                    return tuple(values)

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
                        formowl_tool_descriptor,
                        authorized_capability_summary,
                    )
                    self.calls.append(
                        {
                            "history": tuple(history),
                            "user_text": user_text,
                            "latest_evidence": latest_evidence,
                            "safety_identifier": safety_identifier,
                        }
                    )
                    if user_text == ordinary_prompt:
                        return UatConversationOutcome(
                            response_kind="answer",
                            answer_text="你好，今天很好，隨時可以幫忙。",
                            display_format="narrative",
                            model_name=self.model_name,
                            coverage_status="not_applicable",
                        )
                    if user_text == mail_prompt:
                        request = UatEvidenceToolRequest(
                            tool_name="query_mail_evidence",
                            query_text=mail_query,
                            mail_import_session_id=mail_selector,
                            required_terms=("synthetic",),
                            limit=2,
                        )
                    elif user_text == document_prompt:
                        request = UatEvidenceToolRequest(
                            tool_name="query_effective_graph_view",
                            query_text=document_query,
                            page_size=2,
                            request_contract={
                                "original_query_hash": sha256_json(document_query),
                                "query_class": "evidence_lookup",
                                "source_family_scope": ["document_text"],
                                "requested_fields": [],
                                "maximum_claim_strength": "cited_evidence",
                            },
                        )
                    else:
                        raise AssertionError(f"unexpected browser prompt: {user_text}")
                    result = evidence_tool(request)
                    self.requests.append(request)
                    self.tool_results.append(result)
                    evidence = result.get("evidence_snippets") or result.get("evidence") or ()
                    citations = self.citation_ids(result)
                    if not evidence or not citations:
                        raise AssertionError(
                            "source-neutral recovery returned no governed evidence"
                        )
                    return UatConversationOutcome(
                        response_kind="answer",
                        answer_text=str(evidence[0]["snippet"]),
                        display_format="narrative",
                        model_name=self.model_name,
                        citation_ids=(citations[0],),
                        coverage_status="incomplete",
                        coverage_note="來源完整性仍受目前合成範圍限制。",
                        tool_requests=(request,),
                        tool_results=(result,),
                    )

                def discard_conversation(self, safety_identifier):
                    self.discarded.append(safety_identifier)

                def close(self):
                    return

            core_calls = []
            core_results = []
            mail_handler_calls = []
            retrieval_handlers = []
            expire_source_phase = None

            real_handler_builder = uat_runtime_module.build_issue56_production_semantic_handlers

            def build_observed_handlers(**kwargs):
                retrieval_handler, mail_handler = real_handler_builder(**kwargs)
                retrieval_handlers.append(retrieval_handler)
                if mail_handler is not None:
                    real_mail_handler = mail_handler

                    def observe_mail_handler(arguments):
                        mail_handler_calls.append(dict(arguments))
                        return real_mail_handler(arguments)

                    observe_mail_handler.authorized_capability_summary = (
                        real_mail_handler.authorized_capability_summary
                    )
                    mail_handler = observe_mail_handler
                return retrieval_handler, mail_handler

            def record_core(**kwargs):
                core_calls.append(kwargs)
                if expire_source_phase is not None:
                    # Advance only the helper's clock, after the real daemon/
                    # TestClient/MCP request has reached the source phase.
                    with patch.object(
                        retrieval_gateway_module, "time",
                        SimpleNamespace(monotonic=lambda: expire_source_phase),
                    ):
                        result = source_evidence_double_check(**kwargs)
                else:
                    result = source_evidence_double_check(**kwargs)
                core_results.append(result)
                return result

            conversation_model = SourceNeutralConversationModel()
            with (
                patch.object(
                    sealed_loader,
                    "source_evidence_double_check",
                    side_effect=record_core,
                ),
                patch.object(
                    mail_query_module,
                    "source_evidence_double_check",
                    side_effect=record_core,
                ),
                patch.object(
                    uat_runtime_module,
                    "build_issue56_production_semantic_handlers",
                    side_effect=build_observed_handlers,
                ),
                create_issue56_temporary_lan_query_service(
                    conversation_model,
                    ingestion_revision=revision,
                    query_agent_planner=lambda original, steps, _profile, _limit: (
                        original if not steps else None
                    ),
                ) as query_service,
            ):
                graph_mail_result = retrieval_handlers[0](
                    {
                        "query_text": mail_query,
                        "requester_user_id": sealed_loader.APPROVER_ACTOR,
                        "workspace_id": sealed_loader.WORKSPACE_ID,
                        "session_id": "synthetic-graph-mail-session",
                        "page_size": 2,
                        "request_contract": {
                            "original_query_hash": sha256_json(mail_query),
                            "query_class": "evidence_lookup",
                            "source_family_scope": ["mail"],
                            "requested_fields": [],
                            "maximum_claim_strength": "cited_evidence",
                        },
                    }
                )
                self.assertEqual(source_reader_calls, ["mail"])
                self.assertEqual(
                    graph_mail_result["evidence"][0]["citation_hash"],
                    mail_hash,
                )
                source_reader_calls.clear()
                expire_source_phase = uat_runtime_module.time.monotonic() + 30
                query_service._active_turn_deadline = expire_source_phase
                deadline_calls = []

                def deadline_tool(request):
                    result = query_service._call(request, trace_sink=[])
                    deadline_calls.append((request, result))
                    return result

                provider = CodexResponsesConversationModel(
                    base_url="https://provider.example.test/v1",
                    api_key="synthetic-stop-key",
                )
                with patch.object(
                    provider, "_request_response", side_effect=[
                        {
                            "status": "completed", "output": [{
                                "type": "function_call", "call_id": "synthetic-stop-call",
                                "name": "query_effective_graph_view",
                                "arguments": json.dumps({
                                    "query_text": mail_query,
                                    "required_terms": ["synthetic", "approval"],
                                }),
                            }],
                        },
                        AssertionError("redundant provider continuation"),
                    ],
                ) as provider_call:
                    stopped = provider.respond(
                        history=(), user_text=f"Find evidence for {mail_query}", latest_evidence=None,
                        safety_identifier="synthetic-actual-mcp-stop",
                        evidence_tool=deadline_tool,
                        formowl_tool_descriptor=query_service._formowl_tool_descriptor,
                        authorized_capability_summary={"source_families": ["mail"]},
                    )
                self.assertEqual(len(deadline_calls), 1, stopped)
                deadline_request, deadline_result = deadline_calls[0]
                self.assertEqual(deadline_result["status"], "pending_review")
                self.assertEqual(deadline_result["query_agent"]["status"], "unsupported")
                self.assertEqual(
                    deadline_result["query_agent"]["stop_reason"], "planner_stopped_partial",
                )
                self.assertTrue(_source_fallback_exhausted(deadline_request, deadline_result))
                self.assertEqual(provider_call.call_count, 1)
                self.assertEqual(stopped.response_kind, "clarification")
                self.assertEqual(stopped.coverage_status, "incomplete")
                self.assertEqual(stopped.citation_ids, ())
                self.assertIn("這不代表資料不存在", stopped.answer_text)
                self.assertEqual(source_reader_calls, [])
                self.assertEqual(core_results[-1].scan.stop_reason, "deadline")
                self.assertEqual(core_results[-1].scan.scanned_observation_count, 0)
                expire_source_phase = None
                query_service._active_turn_deadline = None
                query_service.request_count = 0
                core_calls.clear()
                core_results.clear()
                per_turn_request_counts = []
                reset_session_count = None
                reset_turn_count = None
                reset_history_count = None
                reset_latest_evidence = None
                original_ask = query_service.ask

                def record_turn_request_count(prompt, *, session_id):
                    result = original_ask(prompt, session_id=session_id)
                    per_turn_request_counts.append(query_service.request_count)
                    return result

                with patch.object(
                    query_service,
                    "ask",
                    side_effect=record_turn_request_count,
                ):
                    server = create_mail_human_uat_http_server("127.0.0.1", 0, query_service)
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
                    process = None
                    try:
                        process = subprocess.Popen(
                            [node, str(runner), "--live", "--synthetic-source-neutral"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            env={
                                "PATH": os.environ.get("PATH", os.defpath),
                                "HOME": tempfile.gettempdir(),
                                "TMPDIR": tempfile.gettempdir(),
                                "FORMOWL_UAT_URL": origin + "/",
                                "FORMOWL_UAT_TIMEOUT_MS": "15000",
                                "FORMOWL_UAT_EXPECTED_EVIDENCE_BINDINGS": json.dumps(
                                    expected_evidence_bindings,
                                    sort_keys=True,
                                ),
                            },
                            start_new_session=True,
                        )
                        try:
                            stdout, stderr = process.communicate(timeout=70)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            stdout, stderr = process.communicate()
                            self.fail(
                                "synthetic source-neutral Chromium runner exceeded 70 seconds"
                            )
                    finally:
                        if process is not None and process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.communicate()
                        server.shutdown()
                        server.server_close()
                        thread.join(timeout=5)
                    reset_session_count = len(query_service._sessions)
                    reset_state = next(iter(query_service._sessions.values()), None)
                    if reset_state is not None:
                        reset_turn_count = len(reset_state.turns)
                        reset_history_count = len(reset_state.history)
                        reset_latest_evidence = reset_state.latest_evidence

            self.assertEqual(process.returncode, 0, stdout)
            self.assertFalse(stderr, "Chromium runner wrote unexpected stderr")
            lines = [line for line in stdout.splitlines() if line.strip()]
            self.assertEqual(len(lines), 1, "runner must emit one safe result")
            browser_result = json.loads(lines[0])
            self.assertEqual(browser_result["status"], "source_neutral_passed")
            self.assertEqual(browser_result["acceptance_surface"], "source_neutral_synthetic")
            self.assertEqual(browser_result["mail_acceptance"], "synthetic_only")
            self.assertEqual(browser_result["document_acceptance"], "synthetic_only")
            self.assertEqual(
                browser_result["provider_finalization"],
                "not_exercised_provider_free",
            )
            self.assertTrue(browser_result["ordinary_mcp_zero"])
            self.assertEqual(browser_result["mail_tool_count"], 1)
            self.assertEqual(browser_result["mail_citation_count"], 1)
            self.assertTrue(browser_result["mail_source_binding_verified"])
            self.assertEqual(browser_result["document_tool_count"], 1)
            self.assertEqual(browser_result["document_citation_count"], 1)
            self.assertTrue(browser_result["document_source_binding_verified"])
            self.assertEqual(browser_result["reload_transcript_count"], 3)
            self.assertEqual(browser_result["reset_transcript_count"], 0)
            self.assertEqual(browser_result["post_reset_transcript_count"], 1)
            self.assertTrue(browser_result["reload_content_preserved"])
            self.assertEqual(per_turn_request_counts, [0, 1, 1, 0])
            self.assertEqual(query_service.request_count, 0)
            self.assertEqual(query_service.last_mcp_statuses, ())
            self.assertEqual(source_reader_calls, ["document_text"])
            self.assertEqual(len(core_calls), 2)
            self.assertEqual(
                [item["initial_status"] for item in core_calls], ["no_answer", "no_answer"]
            )
            for result in core_results:
                self.assertEqual(result.status, "ok")
                self.assertIsNotNone(result.scan)
                self.assertTrue(result.scan.complete)
                self.assertIsNone(result.scan.stop_reason)
                self.assertEqual(len(result.evidence), 1)

            mail_request, document_request = conversation_model.requests
            self.assertEqual(mail_request.tool_name, "query_mail_evidence")
            self.assertEqual(mail_request.mail_import_session_id, mail_selector)
            self.assertIsNone(mail_request.request_contract)
            self.assertEqual(document_request.tool_name, "query_effective_graph_view")
            self.assertEqual(
                document_request.request_contract["source_family_scope"],
                ["document_text"],
            )
            self.assertIsNone(document_request.mail_import_session_id)
            self.assertEqual(len(mail_handler_calls), 1)
            server_bound_mail_contract = mail_handler_calls[0]["request_contract"]
            self.assertEqual(
                server_bound_mail_contract["original_query_hash"],
                _sha256_text(mail_prompt),
            )
            self.assertEqual(
                server_bound_mail_contract["source_family_scope"],
                ["mail"],
            )
            self.assertEqual(
                server_bound_mail_contract["query_class"],
                "evidence_lookup",
            )
            mail_result, document_result = conversation_model.tool_results
            self.assertEqual(mail_result["status"], "ok")
            self.assertEqual(
                mail_result["evidence_snippets"][0]["source_observation_id"],
                mail_observation.observation_id,
            )
            self.assertEqual(
                mail_result["evidence_snippets"][0]["source_observation_hash"],
                mail_hash,
            )
            self.assertIn(
                "mail_evidence_source_fallback_used",
                mail_result["warnings"],
            )
            document_hash = sha256_json(paragraph.to_dict())
            document_evidence = next(
                item
                for item in document_result["evidence"]
                if item["citation_hash"] == document_hash
            )
            self.assertIn(
                "Acceptance requires written owner approval.", document_evidence["snippet"]
            )
            self.assertEqual(
                document_evidence["document_locator"],
                {
                    "block_type": "paragraph",
                    "asset_id": asset.asset_id,
                    "extractor_run_id": paragraph.extractor_run_id,
                    "line_start": paragraph.location["line_start"],
                    "line_end": paragraph.location["line_end"],
                },
            )
            self.assertEqual(
                document_evidence["revision_binding"],
                {
                    "source_authority_fingerprint": source_authority_fingerprint,
                    "source_session_binding_fingerprint": (
                        revision.session.source_session_binding_fingerprint
                    ),
                },
            )
            context_bundle = document_result["query_agent"]["context_bundle"]
            source_recovery = context_bundle["source_recovery"]
            self.assertEqual(source_recovery["source_family"], "document_text")
            self.assertEqual(source_recovery["source_family_scope"], ["document_text"])
            self.assertEqual(source_recovery["initial_status"], "no_answer")
            self.assertEqual(source_recovery["status"], "ok")
            self.assertTrue(source_recovery["attempted"])
            self.assertTrue(source_recovery["scan"]["complete"])
            self.assertIn(document_hash, source_recovery["citation_hashes"])
            self.assertIn(
                document_evidence["occurrence_lineage_fingerprint"],
                source_recovery["lineage_fingerprints"],
            )
            self.assertEqual(
                context_bundle["bundle_fingerprint"],
                sha256_json(
                    {
                        key: value
                        for key, value in context_bundle.items()
                        if key != "bundle_fingerprint"
                    }
                ),
            )
            self.assertEqual(
                len(conversation_model.calls),
                4,
            )
            self.assertEqual(conversation_model.calls[0]["history"], ())
            self.assertEqual(conversation_model.calls[3]["history"], ())
            self.assertIsNone(conversation_model.calls[3]["latest_evidence"])
            self.assertEqual(len(conversation_model.discarded), 1)
            self.assertEqual(reset_session_count, 1)
            self.assertEqual(reset_turn_count, 1)
            self.assertEqual(reset_history_count, 2)
            self.assertIsNone(reset_latest_evidence)

    def test_runtime_provider_error_hints_allow_only_exact_public_enums(self) -> None:
        base_diagnostic = {
            "provider_status": "failed",
            "provider_error_code": "server_error",
            "provider_error_type": "api_error",
            "stop_reason": None,
            "provider_error_message": "private provider text",
            "upstream_params": {"api_key": "private"},
        }
        accepted = _safe_provider_diagnostic(
            {
                **base_diagnostic,
                "provider_error_param": "text.format",
                "provider_error_message_class": "capacity_unavailable",
            }
        )
        self.assertIsNotNone(accepted)
        assert accepted is not None
        self.assertEqual(accepted["provider_error_param"], "text.format")
        self.assertEqual(accepted["provider_error_message_class"], "capacity_unavailable")
        self.assertEqual(accepted["provider_error_code"], "server_error")
        self.assertEqual(accepted["provider_error_type"], "api_error")
        self.assertNotIn("provider_error_message", accepted)
        self.assertNotIn("upstream_params", accepted)

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
                diagnostic = _safe_provider_diagnostic(
                    {
                        **base_diagnostic,
                        "provider_error_param": parameter,
                    }
                )
                self.assertIsNotNone(diagnostic)
                assert diagnostic is not None
                self.assertEqual(diagnostic["provider_error_param"], parameter)

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
                        "provider_error_message_class": message_class,
                    }
                )
                self.assertIsNotNone(diagnostic)
                assert diagnostic is not None
                self.assertEqual(diagnostic["provider_error_message_class"], message_class)

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

    def test_browser_non_2xx_projection_is_allowlisted_and_transcript_safe(self) -> None:
        page = _render_page(True)

        self.assertIn("async function readJsonResponse", page)
        self.assertIn("response.json()", page)
        self.assertIn("error_code", page)
        self.assertIn("diagnostic", page)
        self.assertIn('query_failed: "查詢未完成；請稍後再試。"', page)
        self.assertIn('mcp_timeout: "查詢逾時；請稍後再試。"', page)
        self.assertIn("showPageError(message)", page)
        self.assertNotIn("response.text()", page)
        self.assertNotIn("errorText.textContent = payload", page)

        self.assertEqual(
            _normalize_query_response(
                {
                    "status": "partial",
                    "answer": "目前只有部分可引用結果。",
                    "citations": ["citation-1"],
                    "clarification": "請補充查詢範圍。",
                    "diagnostic": {
                        "failure_class": "provider_timeout",
                        "provider_error_code": "server_error",
                        "raw_body": "/workspace/secret/provider-response.json",
                    },
                }
            ),
            {
                "status": "partial",
                "answer": "目前只有部分可引用結果。",
                "citations": ["citation-1"],
                "citation_count": 1,
                "clarification": "請補充查詢範圍。",
                "diagnostic": {
                    "provider_error_code": "server_error",
                    "stop_reason": None,
                    "provider_attempts_valid": False,
                    "diagnostic_comparability": {
                        "status": "incomparable",
                        "claim_scope": "diagnostic_only",
                        "missing_bindings": ["deployment", "code", "build", "source"],
                        "missing_fields": [
                            "request_shape",
                            "tool_descriptor",
                            "upstream_http_status",
                            "terminal_outcome",
                            "valid_attempt",
                        ],
                    },
                },
            },
        )

        with self.assertRaises(ValueError):
            _normalize_query_response(
                {
                    "status": "provider_internal_secret",
                    "answer": "不應公開",
                    "citations": [],
                    "clarification": None,
                }
            )

    def test_private_projection_failure_trace_excludes_rejected_content(self) -> None:
        result = {"answer": "PRIVATE-BODY /tmp/private-source.txt api_key=SECRET-VALUE",
                  "clarification": None, "diagnostic": {}}
        stderr = io.StringIO()
        try:
            assert_no_public_raw_references(result)
        except Exception as exc:
            with redirect_stderr(stderr):
                uat_runtime_module._emit_private_uat_failure_trace(exc, "projection", result)
        trace = json.loads(stderr.getvalue())
        self.assertEqual(trace["phase"], "projection")
        self.assertEqual(trace["rejected_fields"], ["answer"])
        self.assertEqual(trace["exception_class"], "ContractValidationError")
        self.assertEqual(trace["exception_owner"]["module"], "formowl_contract.public_safety")
        for forbidden in ("PRIVATE-BODY", "/tmp/private-source.txt", "SECRET-VALUE", "api_key"):
            self.assertNotIn(forbidden, stderr.getvalue())
        self.assertEqual(result["answer"], "PRIVATE-BODY /tmp/private-source.txt api_key=SECRET-VALUE")

    def test_api_chat_non_2xx_projects_safe_browser_error_and_same_transcript_state(
        self,
    ) -> None:
        class FailingQueryService:
            secure_cookie = False
            last_failure_phase = "provider_model"
            last_failure_class = "provider_model"
            request_count = 1

            def __init__(self) -> None:
                self.session_id = "browser-session"
                self.turns: list[dict[str, object]] = []

            def ensure_browser_session(self, session_id):
                if session_id is not None:
                    return None
                return self.session_id, 3600

            def is_browser_session_authenticated(self, session_id):
                return session_id == self.session_id

            def begin_browser_authorization(self):
                raise AssertionError("not used")

            def complete_browser_authorization(self, **kwargs):
                raise AssertionError("not used")

            def logout_browser_session(self, session_id):
                del session_id

            def read_browser_conversation(self, session_id):
                if session_id != self.session_id:
                    raise PermissionError("auth_required")
                return {"turns": self.turns}

            def reset_browser_conversation(self, session_id):
                if session_id != self.session_id:
                    raise PermissionError("auth_required")
                self.session_id = "new-browser-session"
                return self.session_id, 3600

            def ask(self, prompt, *, session_id):
                if session_id != self.session_id:
                    raise PermissionError("auth_required")
                self.turns.append(
                    {
                        "prompt": prompt,
                        "response": {
                            "status": "error",
                            "answer": "查詢失敗，請稍後再試。",
                            "citations": [],
                            "clarification": None,
                        },
                    }
                )
                failure = RuntimeError(
                    "raw provider body secret=never-public " "/private/provider-response.json"
                )
                failure.provider_diagnostic = {
                    "reason_code": "provider_incomplete",
                    "codex_error_kind": "httpConnectionFailed",
                    "http_status": 408,
                    "additionalDetails": "never-public synthetic detail",
                }
                raise failure

        query_service = FailingQueryService()
        server = create_mail_human_uat_http_server("127.0.0.1", 0, query_service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://{server.server_address[0]}:{server.server_address[1]}"

        def request(
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            cookie: str | None = None,
        ):
            body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
            headers = {}
            if body is not None:
                headers.update(
                    {
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),
                        "Origin": origin,
                    }
                )
            if cookie is not None:
                headers["Cookie"] = cookie
            connection = http.client.HTTPConnection(*server.server_address, timeout=10)
            try:
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                return response, response.read()
            finally:
                connection.close()

        try:
            page_response, page_body = request("GET", "/")
            set_cookie = page_response.getheader("Set-Cookie")
            self.assertIsInstance(set_cookie, str)
            cookie = set_cookie.split(";", 1)[0]
            failed_response, failed_body = request(
                "POST",
                "/api/chat",
                payload={"prompt": "觸發 provider 失敗"},
                cookie=cookie,
            )
            transcript_response, transcript_body = request(
                "GET",
                "/api/transcript",
                cookie=cookie,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        page = page_body.decode("utf-8")
        failed_payload = json.loads(failed_body)
        transcript_payload = json.loads(transcript_body)
        self.assertEqual(page_response.status, 200)
        self.assertIn("error.publicResponse", page)
        self.assertEqual(failed_response.status, 500)
        self.assertEqual(
            failed_payload["response"],
            {
                "answer": "查詢失敗，請稍後再試。",
                "citation_count": 0,
                "citations": [],
                "clarification": None,
                "diagnostic": {
                    "diagnostic_comparability": {
                        "status": "incomparable",
                        "claim_scope": "diagnostic_only",
                        "missing_bindings": ["deployment", "code", "build", "source"],
                        "missing_fields": [
                            "request_shape",
                            "tool_descriptor",
                            "upstream_http_status",
                            "terminal_outcome",
                            "valid_attempt",
                        ],
                    },
                },
                "status": "error",
            },
        )
        self.assertEqual(
            failed_payload["diagnostic"],
            {
                "failure_class": "provider_model",
                "phase": "provider_model",
                "request_count": 1,
                "reason_code": "provider_incomplete",
                "codex_error_kind": "httpConnectionFailed",
                "http_status": 408,
                "stop_reason": None,
                "provider_attempts_valid": False,
                "diagnostic_comparability": {
                    "status": "incomparable",
                    "claim_scope": "diagnostic_only",
                    "missing_bindings": ["deployment", "code", "build", "source"],
                    "missing_fields": [
                        "request_shape",
                        "tool_descriptor",
                        "upstream_http_status",
                        "terminal_outcome",
                        "valid_attempt",
                    ],
                },
            },
        )
        self.assertNotIn("raw provider body", json.dumps(failed_payload, ensure_ascii=False))
        self.assertNotIn("never-public", json.dumps(failed_payload, ensure_ascii=False))
        self.assertNotIn("/private/provider-response.json", json.dumps(failed_payload))
        assert_no_public_raw_references(
            failed_payload,
            "issue56_uat_non_2xx_error_projection",
        )
        self.assertEqual(transcript_response.status, 200)
        self.assertEqual(transcript_payload["turn_count"], 1)
        self.assertEqual(
            transcript_payload["turns"][0]["response"],
            failed_payload["response"],
        )

    def test_app_server_pre_mcp_error_is_safe_http_error_and_survives_reload(self) -> None:
        error_message = "synthetic secret-bearing app-server message"
        error_details = "synthetic secret-bearing additional details"
        transport = object.__new__(CodexAppServerStdioTransport)
        transport._state_lock = threading.RLock()
        transport._thread_locks = {}
        transport._active_turns = {}
        transport._timeout_seconds = 1.0
        transport._fatal_error = False
        transport._closed = False

        def app_server_request(method, params, *, timeout_seconds=None):
            del timeout_seconds
            if method == "thread/start":
                return {"thread": {"id": "synthetic-app-server-thread"}, "model": "gpt-5.5"}
            if method == "turn/start":
                transport._deliver_turn_error(
                    {
                        "threadId": params["threadId"],
                        "turnId": "synthetic-app-server-turn",
                        "willRetry": False,
                        "error": {
                            "message": error_message,
                            "additionalDetails": error_details,
                            "codexErrorInfo": {
                                "httpConnectionFailed": {"httpStatusCode": 408},
                            },
                        },
                    }
                )
                return {"turn": {"id": "synthetic-app-server-turn"}}
            if method == "thread/delete":
                return {}
            raise AssertionError(f"unexpected local app-server method: {method}")

        transport._request = app_server_request
        transport.close = lambda: None
        with tempfile.TemporaryDirectory() as workspace:
            conversation_model = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
                model="gpt-5.5",
                reasoning_effort="high",
            )
            config = Issue56DiagnosticConfig()
            google_client = object()
            retrieval_handler = _with_authorized_source_families(
                MagicMock(),
                "document_text",
            )
            application = create_connected_mcp_application(
                bridge=Issue56DiagnosticOAuthBridge(
                    config=config,
                    google_client=google_client,
                    state=Issue56DiagnosticState(),
                ),
                config=config,
                google_client=google_client,
                semantic_gateway=SemanticMcpGateway(
                    retrieval_handler=retrieval_handler,
                ),
                oauth_route_provider=lambda **_kwargs: (),
                environ={"FORMOWL_AUTH_MODE": "oauth_google"},
            )
            service = Issue56TemporaryLanQueryService(
                application,
                conversation_model=conversation_model,
            )
            server = create_mail_human_uat_http_server("127.0.0.1", 0, service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f"http://{server.server_address[0]}:{server.server_address[1]}"

            def request(method, path, *, payload=None, cookie=None):
                body = (
                    json.dumps(payload, ensure_ascii=False).encode()
                    if payload is not None
                    else None
                )
                headers = {}
                if body is not None:
                    headers.update(
                        {
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                            "Origin": origin,
                        }
                    )
                if cookie is not None:
                    headers["Cookie"] = cookie
                connection = http.client.HTTPConnection(*server.server_address, timeout=10)
                try:
                    connection.request(method, path, body=body, headers=headers)
                    response = connection.getresponse()
                    return response, response.read()
                finally:
                    connection.close()

            try:
                page_response, _ = request("GET", "/")
                set_cookie = page_response.getheader("Set-Cookie")
                self.assertIsInstance(set_cookie, str)
                cookie = set_cookie.split(";", 1)[0]
                session_id = cookie.split("=", 1)[1]
                state = service._sessions[session_id]
                previous_history = (
                    UatConversationMessage(
                        role="user",
                        content="synthetic prior authorized lookup",
                    ),
                    UatConversationMessage(
                        role="assistant",
                        content="synthetic prior cited answer",
                    ),
                )
                previous_evidence = {
                    "status": "partial",
                    "coverage": {
                        "status": "incomplete",
                        "coverage_status": "incomplete",
                    },
                    "citations": ["synthetic-prior-citation"],
                    "results": [
                        {
                            "status": "complete",
                            "answer": "synthetic prior governed summary",
                            "citations": ["synthetic-prior-citation"],
                        },
                    ],
                }
                state.history = previous_history
                state.latest_evidence = previous_evidence
                turn_response, turn_body = request(
                    "POST",
                    "/api/chat",
                    payload={"prompt": "列出已授權文件中的驗收條件"},
                    cookie=cookie,
                )
                transcript_response, transcript_body = request(
                    "GET",
                    "/api/transcript",
                    cookie=cookie,
                )
                self.assertEqual(service.request_count, 0)
                self.assertEqual(service.last_mcp_statuses, ())
                self.assertEqual(state.history, previous_history)
                self.assertIs(state.latest_evidence, previous_evidence)
                retrieval_handler.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                service.close()

        turn_payload = json.loads(turn_body)
        transcript_payload = json.loads(transcript_body)
        diagnostic = turn_payload["diagnostic"]
        self.assertEqual(page_response.status, 200)
        self.assertEqual(turn_response.status, 200)
        self.assertEqual(turn_payload["status"], "error")
        self.assertEqual(turn_payload["citations"], [])
        self.assertEqual(diagnostic["reason_code"], "provider_incomplete")
        self.assertEqual(diagnostic["codex_error_kind"], "httpConnectionFailed")
        self.assertEqual(diagnostic["http_status"], 408)
        self.assertEqual(diagnostic["mcp"]["call_count"], 0)
        self.assertEqual(diagnostic["mcp"]["status"], [])
        self.assertEqual(transcript_response.status, 200)
        transcript_turn = transcript_payload["turns"][0]["response"]
        self.assertEqual(transcript_turn["status"], "error")
        self.assertEqual(transcript_turn["diagnostic"], diagnostic)
        rendered = json.dumps(
            {"turn": turn_payload, "transcript": transcript_payload},
            ensure_ascii=False,
        )
        self.assertNotIn(error_message, rendered)
        self.assertNotIn(error_details, rendered)

    def test_mcp_failure_is_error_but_empty_mail_evidence_is_not_absence(self) -> None:
        base_result = {
            "status": "clarification_required",
            "answer": "",
            "citations": [],
            "clarification": "沒有可引用證據。",
        }
        failure_trace = {
            "status": "mcp_failed",
            "timeout": False,
            "timings_ms": {"mcp_call": 1.0},
            "request_shape": {
                "request_contract_present": False,
                "table_query_present": False,
                "exact_field_present": False,
                "exact_inventory_kind_present": False,
                "page_size_present": False,
                "cursor_present": False,
            },
        }

        failed = _classify_mcp_failure_result(
            base_result,
            ({"status": "mcp_failed", "citations": []},),
            (failure_trace,),
        )
        empty = _classify_mcp_failure_result(
            base_result,
            (
                {
                    "status": "not_found",
                    "mail_import_session_id": "mail-import-session-1",
                    "evidence_snippets": [],
                    "citations": [],
                },
            ),
            (),
        )

        self.assertEqual(failed["status"], "error")
        self.assertEqual(failed["citations"], [])
        self.assertEqual(failed["diagnostic"]["mcp"]["status"], ["mcp_failed"])
        self.assertEqual(
            set(failed["diagnostic"]["mcp"]),
            {
                "call_count",
                "elapsed_ms",
                "status",
                "timeout",
                "request_shape",
            },
        )
        self.assertEqual(empty["status"], "clarification_required")
        self.assertEqual(empty["citations"], [])
        self.assertIn("沒有可引用證據", empty["clarification"])

    def test_mcp_query_request_uses_mail_tool_and_selector(self) -> None:
        request = UatEvidenceToolRequest(
            query_text="查詢授權郵件",
            tool_name="query_mail_evidence",
            mail_import_session_id="mail-import-session-1",
            limit=7,
        )

        payload = _mcp_query_request(request)

        self.assertEqual(payload["params"]["name"], "query_mail_evidence")
        self.assertEqual(
            payload["params"]["arguments"],
            {
                "query_text": "查詢授權郵件",
                "mail_import_session_id": "mail-import-session-1",
                "limit": 7,
            },
        )

    def test_private_mail_recheck_trace_is_discriminating_and_allowlisted(self) -> None:
        selector = "synthetic-mail-selector"
        query = "synthetic mail lookup"
        required_terms = ("synthetic", "LOOKUP")
        required_terms_fingerprint = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    ["lookup", "synthetic"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        unknown_warning = "unrecognized_warning_SYNTHETIC_MARKER"
        scenarios = (
            (
                ["mail_evidence_source_fallback_skipped_exact"],
                ["mail_evidence_source_fallback_skipped_exact"],
                1,
            ),
            (
                ["mail_evidence_source_fallback_skipped_replan"],
                ["mail_evidence_source_fallback_skipped_replan"],
                2,
            ),
            (
                [
                    "mail_evidence_source_fallback_used",
                    "mail_evidence_source_fallback_incomplete",
                    "mail_evidence_coverage_incomplete",
                ],
                [
                    "mail_evidence_coverage_incomplete",
                    "mail_evidence_source_fallback_incomplete",
                    "mail_evidence_source_fallback_used",
                ],
                3,
            ),
            (
                ["mail_evidence_source_fallback_unavailable"],
                ["mail_evidence_source_fallback_unavailable"],
                1,
            ),
            (
                [
                    "mail_evidence_source_fallback_used",
                    unknown_warning,
                    {"warning": "nested_synthetic_marker"},
                ],
                ["mail_evidence_source_fallback_used"],
                2,
            ),
            ([unknown_warning], None, 3),
            ("mail_evidence_source_fallback_used", None, 1),
        )

        def response_for(warnings):
            return SimpleNamespace(
                status_code=200,
                json=MagicMock(
                    return_value={
                        "result": {
                            "isError": False,
                            "structuredContent": {
                                "data": {
                                    "status": "pending_review",
                                    "citations": [],
                                    "evidence_snippets": [],
                                    "warnings": warnings,
                                }
                            },
                        }
                    }
                ),
            )
        query_hash = "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()
        selector_hash = "sha256:" + hashlib.sha256(selector.encode("utf-8")).hexdigest()
        for scenario_index, (warnings, expected_warnings, call_index) in enumerate(
            scenarios,
            start=1,
        ):
            service = object.__new__(Issue56TemporaryLanQueryService)
            service._client = SimpleNamespace(
                post=MagicMock(return_value=response_for(warnings))
            )
            service.request_count = call_index - 1
            service.last_failure_phase = "provider_model"
            service._active_turn_deadline = uat_runtime_module.time.monotonic() + 2.0
            service._record_raw_uat_interactions = False
            traces = []
            stderr = io.StringIO()
            browser_hash = "sha256:" + (chr(ord("a") + scenario_index) * 64)
            with redirect_stderr(stderr):
                result = service._call(
                    UatEvidenceToolRequest(
                        query_text=query,
                        tool_name="query_mail_evidence",
                        mail_import_session_id=selector,
                        required_terms=required_terms,
                        limit=1,
                    ),
                    trace_sink=traces,
                    browser_request_sha256=browser_hash,
                )
            service._client.post.assert_called_once()
            posted_payload = service._client.post.call_args.kwargs["json"]
            self.assertEqual(
                posted_payload["params"]["arguments"]["required_terms"],
                list(required_terms),
            )
            self.assertEqual(result["status"], "pending_review")
            self.assertTrue(all("warnings" not in trace for trace in traces))
            emitted = [json.loads(line) for line in stderr.getvalue().splitlines()]
            if expected_warnings is None:
                self.assertEqual(emitted, [])
            else:
                self.assertEqual(
                    emitted,
                    [
                        {
                            "event": "issue56_private_mail_recheck_trace",
                            "status": "pending_review",
                            "citation_count": 0,
                            "browser_request_sha256": browser_hash,
                            "mcp_call_index": call_index,
                            "query_hash": query_hash,
                            "selector_hash": selector_hash,
                            "query_text_char_count": len(query),
                            "required_term_count": len(required_terms),
                            "required_terms_fingerprint": required_terms_fingerprint,
                            "recheck_warnings": expected_warnings,
                        }
                    ],
                )
            rendered = stderr.getvalue()
            self.assertNotIn(query, rendered)
            self.assertNotIn(selector, rendered)
            for term in required_terms:
                self.assertNotIn(term, rendered)
            self.assertNotIn(unknown_warning, rendered)
            self.assertNotIn("nested_synthetic_marker", rendered)
            self.assertNotIn("exception_owner", rendered)

    def test_mail_projection_accepts_partial_governed_identity_without_public_ids(self) -> None:
        citation_id = "mailcitation_partial"
        response = {
            "evidence_snippets": [
                {
                    "snippet": "Waiting on audit approval",
                    "mail_import_session_id": "mail-session-1",
                }
            ],
            "citations": [
                {
                    "citation_id": citation_id,
                    "mail_import_session_id": "mail-session-1",
                }
            ],
        }
        records = _governed_mail_evidence_records(response, limit=8)

        self.assertEqual(
            records,
            ({"snippet": "Waiting on audit approval", "citation_id": citation_id},),
        )
        assert_no_public_raw_references(records[0], "issue56_partial_mail_projection")
        self.assertNotIn("mail_import_session_id", records[0])
        failed_finalization = UatConversationOutcome(
            response_kind="clarification",
            answer_text="Provider finalization failed.",
            display_format="narrative",
            model_name="synthetic",
            coverage_status="incomplete",
            coverage_note="Evidence is partial.",
            provider_diagnostic={"reason_code": "invalid_json_response"},
        )
        preserved = _browser_projection(
            failed_finalization,
            (response,),
            latest_evidence=None,
        )
        self.assertEqual(preserved["status"], "partial")
        self.assertEqual(preserved["citations"], [citation_id])
        self.assertIn("Waiting on audit approval", preserved["answer"])
        self.assertNotIn("mail-session-1", json.dumps(preserved))
        self.assertEqual(
            _browser_projection(
                failed_finalization,
                ({"evidence_snippets": response["evidence_snippets"], "citations": []},),
                latest_evidence=None,
            )["status"],
            "error",
        )

    def test_graph_projection_preserves_cited_top_level_evidence_after_provider_failure(self) -> None:
        citation_hash = "sha256:graph-citation"
        response = {
            "status": "ok",
            "evidence": [
                {
                    "snippet": "嘉值交期：2026-10-15。",
                    "citation_hash": citation_hash,
                    "source_observation_id": "observation-private",
                    "document_locator": {"line_start": 4, "line_end": 4},
                }
            ],
            "citations": [citation_hash],
            "lineages": [{"source_observation_id": "observation-private"}],
        }
        failed_finalization = UatConversationOutcome(
            response_kind="clarification",
            answer_text="Provider citation finalization failed.",
            display_format="narrative",
            model_name="synthetic",
            coverage_status="incomplete",
            coverage_note="Graph evidence is available but coverage is partial.",
            provider_diagnostic={"reason_code": "invalid_json_response"},
        )

        preserved = _browser_projection(
            failed_finalization,
            (response,),
            latest_evidence=None,
        )

        self.assertEqual(preserved["status"], "partial")
        self.assertEqual(preserved["citations"], [citation_hash])
        self.assertIn("嘉值交期：2026-10-15。", preserved["answer"])
        self.assertIn("涵蓋限制", preserved["clarification"])
        self.assertNotIn("observation-private", json.dumps(preserved))
        assert_no_public_raw_references(preserved, "issue56_graph_partial_projection")

        ungoverned = {
            "status": "ok",
            "evidence": [
                {
                    "snippet": "不得投影的未授權摘錄",
                    "citation_hash": "sha256:not-governed",
                }
            ],
            "citations": [citation_hash],
        }
        rejected = _browser_projection(
            failed_finalization,
            (ungoverned,),
            latest_evidence=None,
        )
        self.assertEqual(rejected["status"], "error")
        self.assertEqual(rejected["citations"], [])
        self.assertNotIn("不得投影的未授權摘錄", json.dumps(rejected))

    def test_runtime_projection_replaces_unsafe_provider_text_only_with_bound_evidence(self) -> None:
        citation = "sha256:" + "b" * 64
        response = {
            "status": "ok",
            "evidence": [{"snippet": "本回合授權來源摘要", "citation_hash": citation}],
            "citations": [citation],
        }

        def ask_synthetic(
            result,
            outcome,
            current_response=response,
            *,
            source_binding_fingerprint=None,
            diagnostic=None,
        ):
            service = object.__new__(uat_runtime_module.Issue56TemporaryLanQueryService)
            service._application = object()
            service._conversation_model = SimpleNamespace(discard_conversation=lambda _: None)
            service._lock = threading.RLock()
            service._query_lock = threading.Lock()
            service._sessions = {
                "synthetic-session": _ConversationState(
                    expires_at=(uat_runtime_module.time.monotonic() + 60),
                )
            }
            service._behavior_log_path = None
            service._source_binding_fingerprint = source_binding_fingerprint
            service._active_turn_deadline = None
            service.request_count = 0
            service.last_mcp_statuses = ()
            service.last_failure_class = None
            service.last_failure_phase = "unknown"
            service._last_private_mcp_owner_trace = None
            if diagnostic is not None:
                result = {**result, "diagnostic": diagnostic}
            with (
                patch.object(
                    uat_runtime_module,
                    "_query_agent_runtime_context",
                    return_value=(None, None),
                ),
                patch.object(
                    uat_runtime_module,
                    "_run_gpt_query_agent",
                    return_value=(result, (current_response,), outcome),
                ),
            ):
                return service.ask("查詢授權來源", session_id="synthetic-session")

        for unsafe_answer, unsafe_coverage in (
            ("/workspace/private/provider-answer.txt", "涵蓋仍不完整。"),
            ("正常答案", "/workspace/private/provider-coverage.txt"),
        ):
            with self.subTest(unsafe_answer=unsafe_answer, unsafe_coverage=unsafe_coverage):
                unsafe_result = {
                    "status": "partial",
                    "answer": unsafe_answer,
                    "citations": [citation],
                    "clarification": unsafe_coverage,
                }
                unsafe_outcome = UatConversationOutcome(
                    response_kind="answer",
                    answer_text=unsafe_answer,
                    display_format="narrative",
                    model_name="synthetic",
                    citation_ids=(citation,),
                    coverage_status="incomplete",
                    coverage_note=unsafe_coverage,
                )
                projected = ask_synthetic(unsafe_result, unsafe_outcome)
                self.assertEqual(projected["status"], "partial")
                self.assertEqual(projected["citations"], [citation])
                self.assertIn("本回合授權來源摘要", projected["answer"])
                self.assertIn("答案仍不完整", projected["clarification"])
                self.assertNotIn("/workspace/private", json.dumps(projected))
                assert_no_public_raw_references(projected, "issue56_unsafe_provider_fallback")

        safe_outcome = UatConversationOutcome(
            response_kind="answer",
            answer_text="正常答案",
            display_format="narrative",
            model_name="synthetic",
            citation_ids=(citation,),
            coverage_status="complete",
        )
        unchanged = ask_synthetic(
            {
                "status": "complete",
                "answer": "正常答案",
                "citations": [citation],
                "clarification": None,
            },
            safe_outcome,
        )
        self.assertEqual(unchanged["status"], "complete")
        self.assertEqual(unchanged["answer"], "正常答案")
        self.assertEqual(unchanged["citations"], [citation])

        source_binding = "sha256:" + "d" * 64
        passed_diagnostic = {
            "finalization_validation": [
                {
                    "final_model": {
                        "citation_count": 1,
                        "citation_fingerprint": "sha256:" + "e" * 64,
                    },
                    "available_governed": {
                        "citation_count": 1,
                        "citation_fingerprint": "sha256:" + "f" * 64,
                    },
                    "validation_result": "passed",
                    "repair_attempted": False,
                }
            ],
        }
        private_trace = io.StringIO()
        with redirect_stderr(private_trace):
            diagnostic_fallback = ask_synthetic(
                {
                    "status": "partial",
                    "answer": "/workspace/private/provider-answer.txt",
                    "citations": [citation],
                    "clarification": "/workspace/private/provider-coverage.txt",
                },
                UatConversationOutcome(
                    response_kind="answer",
                    answer_text="/workspace/private/provider-answer.txt",
                    display_format="narrative",
                    model_name="synthetic",
                    citation_ids=(citation,),
                    coverage_status="incomplete",
                    coverage_note="/workspace/private/provider-coverage.txt",
                ),
                source_binding_fingerprint=source_binding,
                diagnostic=passed_diagnostic,
            )
        diagnostic = diagnostic_fallback["diagnostic"]
        self.assertEqual(diagnostic["source_binding_fingerprint"], source_binding)
        self.assertIn("mcp", diagnostic)
        self.assertEqual(
            [item["validation_result"] for item in diagnostic["finalization_validation"]],
            ["parse_rejected"],
        )
        self.assertFalse(diagnostic["finalization_validation"][0]["repair_attempted"])
        self.assertNotIn('"validation_result": "passed"', json.dumps(diagnostic))
        self.assertIn("issue56_private_uat_failure_trace", private_trace.getvalue())
        self.assertNotIn("/workspace/private", private_trace.getvalue())

    def test_runtime_projection_rejects_unbound_or_unsafe_current_evidence(self) -> None:
        citation = "sha256:" + "c" * 64
        outcome = UatConversationOutcome(
            response_kind="answer",
            answer_text="/workspace/private/provider-answer.txt",
            display_format="narrative",
            model_name="synthetic",
            citation_ids=(citation,),
            coverage_status="incomplete",
            coverage_note="/workspace/private/provider-coverage.txt",
        )
        invalid_result = {
            "status": "partial",
            "answer": outcome.answer_text,
            "citations": [citation],
            "clarification": outcome.coverage_note,
        }

        def ask_with(response):
            service = object.__new__(uat_runtime_module.Issue56TemporaryLanQueryService)
            service._application = object()
            service._conversation_model = SimpleNamespace(discard_conversation=lambda _: None)
            service._lock = threading.RLock()
            service._query_lock = threading.Lock()
            service._sessions = {
                "synthetic-session": _ConversationState(
                    expires_at=(uat_runtime_module.time.monotonic() + 60),
                )
            }
            service._behavior_log_path = None
            service._source_binding_fingerprint = None
            service._active_turn_deadline = None
            service.request_count = 0
            service.last_mcp_statuses = ()
            service.last_failure_class = None
            service.last_failure_phase = "unknown"
            service._last_private_mcp_owner_trace = None
            with (
                patch.object(uat_runtime_module, "_query_agent_runtime_context", return_value=(None, None)),
                patch.object(
                    uat_runtime_module,
                    "_run_gpt_query_agent",
                    return_value=(invalid_result, (response,), outcome),
                ),
            ):
                return service.ask("查詢授權來源", session_id="synthetic-session")

        invalid_responses = (
            {
                "status": "ok",
                "evidence": [{"snippet": "摘要", "citation_hash": "sha256:unbound"}],
                "citations": [citation],
            },
            {
                "status": "ok",
                "evidence": [{"snippet": "/workspace/private/source.txt", "citation_hash": citation}],
                "citations": [citation],
            },
        )
        for response in invalid_responses:
            with self.subTest(response=response):
                with self.assertRaises(ContractValidationError):
                    ask_with(response)

    def test_requery_retains_bounded_prior_mail_snippets_for_next_browser_turn(self) -> None:
        def mail_response(
            *, snippet: str, citation_id: str, occurrence_id: str
        ) -> dict[str, object]:
            return {
                "status": "ok",
                "mail_import_session_id": "mail-session-uat",
                "evidence_snippets": [
                    {
                        "snippet": snippet,
                        "mail_import_session_id": "mail-session-uat",
                        "message_occurrence_id": occurrence_id,
                    }
                ],
                "citations": [
                    {
                        "citation_id": citation_id,
                        "mail_import_session_id": "mail-session-uat",
                        "message_occurrence_id": occurrence_id,
                    }
                ],
            }

        old_response = mail_response(
            snippet="舊郵件摘要：等待稽核核准。",
            citation_id="mail-citation-old",
            occurrence_id="mail-occurrence-old",
        )
        new_response = mail_response(
            snippet="新郵件摘要：稽核已回覆。",
            citation_id="mail-citation-new",
            occurrence_id="mail-occurrence-new",
        )
        state = _ConversationState(expires_at=1.0)
        first_outcome = UatConversationOutcome(
            response_kind="answer",
            answer_text="舊郵件摘要。",
            display_format="narrative",
            model_name="synthetic-test-provider",
            citation_ids=("mail-citation-old",),
            coverage_status="incomplete",
            coverage_note="郵件來源涵蓋範圍仍不完整。",
        )
        _advance_conversation_state(
            state,
            prompt="查詢舊稽核郵件",
            result={
                "status": "partial",
                "answer": first_outcome.answer_text,
                "citations": ["mail-citation-old"],
                "clarification": first_outcome.coverage_note,
            },
            outcome=first_outcome,
            responses=(old_response,),
        )

        second_outcome = UatConversationOutcome(
            response_kind="answer",
            answer_text="新郵件摘要。",
            display_format="narrative",
            model_name="synthetic-test-provider",
            citation_ids=("mail-citation-new",),
            coverage_status="incomplete",
            coverage_note="重新查詢後郵件來源涵蓋範圍仍不完整。",
        )
        _advance_conversation_state(
            state,
            prompt="重新查詢稽核回覆",
            result={
                "status": "partial",
                "answer": second_outcome.answer_text,
                "citations": ["mail-citation-new"],
                "clarification": second_outcome.coverage_note,
            },
            outcome=second_outcome,
            responses=(new_response,),
        )

        self.assertIsNotNone(state.latest_evidence)
        assert state.latest_evidence is not None
        retained = state.latest_evidence
        snippets = [
            snippet["snippet"]
            for result in retained["results"]
            if isinstance(result, dict)
            for snippet in result.get("evidence_snippets", ())
            if isinstance(snippet, dict) and isinstance(snippet.get("snippet"), str)
        ]
        self.assertIn("舊郵件摘要：等待稽核核准。", snippets)
        self.assertIn("新郵件摘要：稽核已回覆。", snippets)
        self.assertEqual(
            retained["citations"],
            ["mail-citation-old", "mail-citation-new"],
        )
        self.assertLessEqual(len(retained["results"]), 8)
        self.assertLessEqual(
            sum(len(result.get("evidence_snippets", ())) for result in retained["results"]),
            8,
        )
        assert_no_public_raw_references(
            retained,
            "issue56_requery_retained_mail_evidence",
        )

    def test_mail_only_normal_mcp_preserves_cited_snippet_on_provider_finalization_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle = _mail_bundle(Path(temporary_directory))
            mail_session_id = bundle.mail_import_session.mail_import_session_id
            real_mail_handler = build_mail_evidence_query_handler(
                [bundle],
                grants=(
                    _mail_session_grant(
                        bundle,
                        grantee_user_id="user_full_pst_domain_hard_case_eval_owner",
                    ),
                ),
                now=NOW,
            )
            mcp_arguments: list[dict[str, object]] = []
            mcp_results: list[dict[str, object]] = []

            def recording_mail_handler(arguments):
                mcp_arguments.append(dict(arguments))
                result = real_mail_handler(arguments)
                mcp_results.append(dict(result))
                return result

            recording_mail_handler.authorized_capability_summary = {
                "source_families": ["mail"],
                "mail_selector_kind": "mail_import_session_id",
                "authorized_mail_import_session_ids": [mail_session_id],
            }

            provider_requests: list[dict[str, object]] = []
            provider_paths: list[str] = []
            provider_authorization_headers: list[str] = []

            # This is a localhost wire stub for the Responses boundary.  It
            # deliberately exercises urllib's real HTTP path and is not an
            # assertion of behavior from an external provider.
            class ResponsesStubHandler(BaseHTTPRequestHandler):
                def do_POST(self) -> None:  # noqa: N802
                    provider_paths.append(self.path)
                    authorization = self.headers.get("Authorization")
                    if authorization is not None:
                        provider_authorization_headers.append(authorization)
                    if self.path != "/v1/responses":
                        self.send_error(404)
                        return
                    content_length = self.headers.get("Content-Length")
                    if content_length is None:
                        self.send_error(400)
                        return
                    request = json.loads(self.rfile.read(int(content_length)).decode("utf-8"))
                    provider_requests.append(request)
                    if len(provider_requests) == 1:
                        response = {
                            "status": "completed",
                            "output": [
                                {
                                    "type": "function_call",
                                    "call_id": "mail-call-1",
                                    "name": "query_mail_evidence",
                                    "arguments": json.dumps(
                                        {
                                            "query_text": "audit approval",
                                            "required_terms": ["audit approval"],
                                            "mail_import_session_id": mail_session_id,
                                            "limit": 1,
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ],
                        }
                    else:
                        # Match the live blocker: finalization returns a
                        # successful HTTP envelope with an empty body.  The
                        # owner path must preserve the governed mail evidence
                        # immediately rather than issue another identical
                        # provider request.
                        self.send_response(200)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    body = json.dumps(response, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, format: str, *args: object) -> None:
                    del format, args

            provider_server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                ResponsesStubHandler,
            )
            provider_thread = threading.Thread(
                target=provider_server.serve_forever,
                daemon=True,
            )
            provider_thread.start()
            config = Issue56DiagnosticConfig()
            diagnostic_state = Issue56DiagnosticState()
            google_client = object()
            bridge = Issue56DiagnosticOAuthBridge(
                config=config,
                google_client=google_client,
                state=diagnostic_state,
            )
            application = create_connected_mcp_application(
                bridge=bridge,
                config=config,
                google_client=google_client,
                semantic_gateway=SemanticMcpGateway(
                    mail_evidence_handler=recording_mail_handler,
                ),
                oauth_route_provider=lambda **_kwargs: (),
                environ={"FORMOWL_AUTH_MODE": "oauth_google"},
            )
            provider_model = CodexResponsesConversationModel(
                base_url=f"http://127.0.0.1:{provider_server.server_address[1]}/v1",
                api_key="provider-key-never-public",
                model=_PROVIDER_MODEL,
                reasoning_effort=_PROVIDER_REASONING_EFFORT,
            )
            service = Issue56TemporaryLanQueryService(
                application,
                conversation_model=provider_model,
            )
            server = create_mail_human_uat_http_server("127.0.0.1", 0, service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def request(method: str, path: str, *, body=None, cookie=None):
                headers = {}
                if body is not None:
                    headers.update(
                        {
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                            "Origin": f"http://{server.server_address[0]}:"
                            f"{server.server_address[1]}",
                        }
                    )
                if cookie is not None:
                    headers["Cookie"] = cookie
                connection = http.client.HTTPConnection(*server.server_address, timeout=10)
                try:
                    connection.request(method, path, body=body, headers=headers)
                    response = connection.getresponse()
                    return response, response.read()
                finally:
                    connection.close()

            try:
                page_response, page_body = request("GET", "/")
                set_cookie = page_response.getheader("Set-Cookie")
                assert isinstance(set_cookie, str)
                cookie = set_cookie.split(";", 1)[0]
                response, body = request(
                    "POST",
                    "/api/chat",
                    body=json.dumps(
                        {"prompt": "請查詢授權郵件中的 audit approval"},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    cookie=cookie,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                service.close()
                provider_server.shutdown()
                provider_server.server_close()
                provider_thread.join(timeout=5)

        payload = json.loads(body)
        self.assertEqual(page_response.status, 200)
        self.assertIn('data-authenticated="true"', page_body.decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["citation_count"], 1)
        self.assertIn("Waiting on audit approval", payload["answer"])
        self.assertNotIn("provider-key-never-public", json.dumps(provider_requests))
        self.assertEqual(provider_paths, ["/v1/responses"] * 2)
        self.assertEqual(
            provider_authorization_headers,
            ["Bearer provider-key-never-public"] * 2,
        )
        self.assertEqual(len(provider_requests), 2)
        self.assertEqual(
            {
                (
                    request["model"],
                    request["reasoning"]["effort"],
                )
                for request in provider_requests
            },
            {(_PROVIDER_MODEL, _PROVIDER_REASONING_EFFORT)},
        )
        self.assertIn(
            "query_mail_evidence",
            [tool["name"] for tool in provider_requests[0]["tools"]],
        )
        self.assertEqual(
            provider_requests[0]["tool_choice"],
            {"type": "function", "name": "query_mail_evidence"},
        )
        self.assertEqual(len(mcp_arguments), 1)
        self.assertEqual(
            mcp_arguments[0]["mail_import_session_id"],
            mail_session_id,
        )
        self.assertEqual(mcp_arguments[0]["required_terms"], ["audit approval"])
        self.assertEqual(mcp_arguments[0]["limit"], 1)
        self.assertEqual(
            mcp_arguments[0]["request_contract"]["original_query_hash"],
            _sha256_text("請查詢授權郵件中的 audit approval"),
        )
        self.assertEqual(
            mcp_arguments[0]["request_contract"]["source_family_scope"],
            ["mail"],
        )
        self.assertEqual(
            mcp_arguments[0]["request_contract"]["query_class"],
            "evidence_lookup",
        )
        self.assertNotIn("table_query", mcp_arguments[0])
        self.assertEqual(len(mcp_results), 1)
        citation_id = mcp_results[0]["citations"][0]["citation_id"]
        function_call_outputs = [
            item
            for item in provider_requests[1]["input"]
            if item.get("type") == "function_call_output"
        ]
        self.assertEqual(len(function_call_outputs), 1)
        tool_output = json.loads(function_call_outputs[0]["output"])
        self.assertIn(
            "Waiting on audit approval",
            tool_output["data"]["evidence_snippets"][0]["snippet"],
        )
        self.assertEqual(
            tool_output["data"]["citations"][0]["citation_id"],
            citation_id,
        )
        self.assertEqual(payload["citations"], [citation_id])
        assert_no_public_raw_references(
            payload,
            "issue56_mail_provider_finalization_failure",
        )

    def test_browser_greeting_then_business_pre_mcp_provider_failure_is_not_no_data(
        self,
    ) -> None:
        """Regression: provider rejection before its first tool call is explicit."""

        provider_requests: list[dict[str, object]] = []
        mcp_calls: list[dict[str, object]] = []

        def should_not_run(arguments):
            mcp_calls.append(dict(arguments))
            return {"status": "mcp_failed", "citations": []}

        class ResponsesStubHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                content_length = self.headers.get("Content-Length")
                assert content_length is not None
                request = json.loads(self.rfile.read(int(content_length)).decode("utf-8"))
                provider_requests.append(request)
                if len(provider_requests) == 1:
                    response = {
                        "status": "completed",
                        "output_text": json.dumps(
                            {
                                "response_kind": "answer",
                                "answer_text": "你好，請告訴我想查詢的資料。",
                                "display_format": "narrative",
                                "citation_ids": [],
                                "coverage_status": "not_applicable",
                                "coverage_note": "",
                            },
                            ensure_ascii=False,
                        ),
                    }
                    status = 200
                else:
                    response = {
                        "error": {
                            "type": "invalid_request_error",
                            "code": "invalid_parameter",
                        }
                    }
                    status = 408
                body = json.dumps(response, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        provider_server = ThreadingHTTPServer(("127.0.0.1", 0), ResponsesStubHandler)
        provider_thread = threading.Thread(
            target=provider_server.serve_forever,
            daemon=True,
        )
        provider_thread.start()
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
            semantic_gateway=SemanticMcpGateway(
                mail_evidence_handler=should_not_run,
            ),
            oauth_route_provider=lambda **_kwargs: (),
            environ={"FORMOWL_AUTH_MODE": "oauth_google"},
        )
        conversation_model = CodexResponsesConversationModel(
            base_url=f"http://127.0.0.1:{provider_server.server_address[1]}/v1",
            api_key="pre-mcp-provider-key-never-public",
            model=_PROVIDER_MODEL,
            reasoning_effort=_PROVIDER_REASONING_EFFORT,
        )
        service = Issue56TemporaryLanQueryService(
            application,
            conversation_model=conversation_model,
        )
        server = create_mail_human_uat_http_server("127.0.0.1", 0, service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(prompt: str | None, cookie: str | None = None):
            body = (
                json.dumps({"prompt": prompt}, ensure_ascii=False).encode("utf-8")
                if prompt is not None
                else None
            )
            headers = {}
            if body is not None:
                headers.update(
                    {
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),
                        "Origin": (
                            f"http://{server.server_address[0]}:" f"{server.server_address[1]}"
                        ),
                    }
                )
            if cookie is not None:
                headers["Cookie"] = cookie
            connection = http.client.HTTPConnection(*server.server_address, timeout=5)
            try:
                connection.request(
                    "GET" if body is None else "POST",
                    "/" if body is None else "/api/chat",
                    body=body,
                    headers=headers,
                )
                response = connection.getresponse()
                return response, response.read()
            finally:
                connection.close()

        try:
            page_response, page_body = request(None)
            set_cookie = page_response.getheader("Set-Cookie")
            assert isinstance(set_cookie, str)
            cookie = set_cookie.split(";", 1)[0]
            greeting_response, greeting_body = request("你好", cookie)
            business_response, business_body = request(
                "把劉一帆的信件整理出來",
                cookie,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            service.close()
            provider_server.shutdown()
            provider_server.server_close()
            provider_thread.join(timeout=5)

        greeting = json.loads(greeting_body)
        business = json.loads(business_body)
        self.assertEqual(page_response.status, 200)
        self.assertIn('data-authenticated="true"', page_body.decode("utf-8"))
        self.assertEqual(greeting_response.status, 200)
        self.assertEqual(greeting["status"], "complete")
        self.assertEqual(greeting["citation_count"], 0)
        self.assertEqual(business_response.status, 200)
        self.assertEqual(business["status"], "error")
        self.assertEqual(business["citation_count"], 0)
        diagnostic = business["diagnostic"]
        self.assertEqual(diagnostic["reason_code"], "provider_pre_mcp_failure")
        self.assertEqual(diagnostic["http_status"], 408)
        self.assertEqual(diagnostic["provider_error_type"], "invalid_request_error")
        self.assertEqual(diagnostic["provider_attempt_count"], 1)
        self.assertEqual(diagnostic["mcp"]["call_count"], 0)
        self.assertEqual(diagnostic["mcp"]["status"], [])
        self.assertEqual(diagnostic["provider_phase_timings"][0]["phase"], "provider_request")
        self.assertIn("provider", business["answer"].casefold())
        rendered = json.dumps(business, ensure_ascii=False).casefold()
        for forbidden in ("kg", "no_data", "no evidence", "資料不存在", "查無資料"):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(len(provider_requests), 2)
        self.assertEqual(
            [
                (
                    request["model"],
                    request["reasoning"]["effort"],
                )
                for request in provider_requests
            ],
            [
                (_PROVIDER_MODEL, _PROVIDER_REASONING_EFFORT),
                (_PROVIDER_MODEL, _PROVIDER_REASONING_EFFORT),
            ],
        )
        self.assertEqual(provider_requests[0]["tools"], [])
        self.assertEqual(provider_requests[0]["tool_choice"], "none")
        self.assertTrue(provider_requests[1]["tools"])
        self.assertNotEqual(provider_requests[1]["tool_choice"], "none")
        self.assertEqual(mcp_calls, [])
        self.assertNotIn(
            "pre-mcp-provider-key-never-public",
            json.dumps(provider_requests, ensure_ascii=False),
        )
        assert_no_public_raw_references(
            business,
            "issue56_pre_mcp_provider_failure_browser_response",
        )

    def test_uat_binder_preserves_revision_bound_family_and_rejects_unavailable(
        self,
    ) -> None:
        query = "把劉一帆的信統整出來"
        capability_summary = {"source_families": ["attachment_table", "mail"]}
        revision_source_families = ("mail",)
        base_contract = {
            "original_query_hash": ("sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()),
            "query_class": "global_summarization",
            "source_family_scope": ["mail"],
            "requested_fields": [],
            "maximum_claim_strength": "bounded_summary",
        }

        bound = _UatTurnRequestContractBinder(
            user_text=query,
            authorized_capability_summary=capability_summary,
        ).bind(base_contract, table_query=None)

        self.assertEqual(bound["source_family_scope"], ["mail"])
        self.assertEqual(
            validate_semantic_request_contract(
                bound,
                available_source_families=revision_source_families,
            )["source_family_scope"],
            ["mail"],
        )
        with self.assertRaisesRegex(
            uat_runtime_module.ContractValidationError,
            "source scope is unavailable",
        ):
            _UatTurnRequestContractBinder(
                user_text=query,
                authorized_capability_summary=capability_summary,
            ).bind(
                {
                    **base_contract,
                    "source_family_scope": ["unauthorized_fixture_family"],
                },
                table_query=None,
            )

    @unittest.skipUnless(
        os.environ.get("FORMOWL_TEST_PROJECTION_POSTGRES_PASSWORD_FILE"),
        "isolated PostgreSQL fixture not configured",
    )
    def test_persisted_session_graph_reopen_and_normal_query_without_source_scan(self) -> None:
        import psycopg
        from psycopg.rows import dict_row
        from formowl_auth.postgres import PsycopgOAuthConnection
        from dataclasses import replace
        from formowl_graph.index.records import PostgreSQLGraphProjectionStore
        import formowl_mail.hybrid as hybrid
        from formowl_mail.query import build_authorized_observation_snippet_index
        from formowl_gateway.issue56_sealed_source_loader import (
            build_issue56_production_semantic_retrieval_handler,
        )
        from test_issue56_hybrid_batch_encoding import Issue56HybridBatchEncodingTests

        runtime, source, observations, lineages, hashes, snippets, snippet_manifest = (
            Issue56HybridBatchEncodingTests()._artifact_fixture()
        )
        source = replace(source, workspace_id=sealed_source.WORKSPACE_ID)
        snippets, snippet_manifest = build_authorized_observation_snippet_index(
            observations,
            authorized_source=source,
            occurrence_lineages=lineages,
            authorized_observation_hash_by_id=hashes,
            tokenizer_profile=runtime.tokenizer_profile,
        )
        # Tiny existing source-neutral fixture only. This in-memory fixture setup
        # is explicitly NOT the full-source bounded build route.
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components", return_value=runtime
        ):
            session = hybrid.build_authorized_semantic_observation_session(
                authorized_source=source,
                snippet_index=snippets,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                requester_user_id=sealed_source.APPROVER_ACTOR,
            )
        graph = hybrid.build_authorized_source_backed_effective_graph_view(
            session=session,
            source_binding_fingerprint=snippet_manifest.index_fingerprint,
        )
        index = session.index
        raw = psycopg.connect(
            host="postgres",
            dbname="formowl",
            user="formowl",
            password=Path(os.environ["FORMOWL_TEST_PROJECTION_POSTGRES_PASSWORD_FILE"]).read_text(),
            row_factory=dict_row,
            autocommit=True,
        )
        self.addCleanup(raw.close)
        connection = PsycopgOAuthConnection(raw)
        store = PostgreSQLGraphProjectionStore(
            connection,
            revision_id="fixture_normal_" + uuid.uuid4().hex,
            workspace_id=source.workspace_id,
            binding={
                "source_access_fingerprint": source.authorization_fingerprint,
                "index": index.index_fingerprint,
            },
        )
        metadata = hybrid.persist_authorized_semantic_observation_session(
            session=session,
            graph_build=graph,
            runtime_store=store,
            source_references={item.observation_id: {"fixture": True} for item in observations},
        )
        metadata["source_families"] = ["mail"]
        seal = store.seal(metadata, store.binding)
        relation_types = tuple(
            sorted({edge.relation_type for edge in graph.effective_graph_view.visible_edges})
        )
        evidence_encodes = runtime.dense_encoder._model.call_count
        with (
            patch.object(
                store, "iter_helpers", side_effect=AssertionError("source scan forbidden")
            ),
            patch.object(store, "iter_nodes", side_effect=AssertionError("graph scan forbidden")),
            patch.object(store, "iter_edges", side_effect=AssertionError("edge scan forbidden")),
            patch.object(
                hybrid,
                "build_authorized_source_backed_effective_graph_view",
                side_effect=AssertionError("graph rebuild forbidden"),
            ),
        ):
            reopened = hybrid.reopen_authorized_semantic_observation_session(
                runtime_store=store,
                expected_seal=seal["seal_hash"],
                runtime_components=runtime,
                requester_user_id=session.requester_user_id,
            )
            reopened_graph = hybrid.reopen_authorized_effective_graph_view(session=reopened)
            self.assertEqual(runtime.dense_encoder._model.call_count, evidence_encodes)
            result = reopened.query(
                query_text="authorized evidence snippet",
                effective_graph_view=reopened_graph,
                allowed_relation_types=relation_types,
            )
            by_hash = {hashes[item.observation_id]: item for item in observations}
            by_id = {item.source_observation_id: item for item in lineages}
            fixture_source_reader = SimpleNamespace(
                runtime_store=store,
                observation_for_hash=by_hash.get,
                lineage=by_id.__getitem__,
            )
            revision = sealed_source.Issue56IngestionRevision(
                observations=(),
                bundles=(),
                session=reopened,
                snippet_index=None,
                graph_build=replace(graph, effective_graph_view=reopened_graph),
                safe_binding={"extraction_coverage": {"source_completeness_certified": False}},
                source_records=fixture_source_reader,
            )
            handler = build_issue56_production_semantic_retrieval_handler(
                ingestion_revision=revision,
            )
            payload = handler(
                {
                    "query_text": "authorized evidence snippet",
                    "requester_user_id": session.requester_user_id,
                    "workspace_id": session.workspace_id,
                    "session_id": "session_fixture_stored",
                }
            )
        self.assertTrue(result.answer_citation_hashes)
        self.assertEqual(result.index_fingerprint, index.index_fingerprint)
        self.assertTrue(payload["citations"])
        self.assertEqual(payload["coverage"]["status"], "incomplete")

    def test_sidecar_supplement_keeps_two_roots_and_remaps_exact_rows(
        self,
    ) -> None:
        root = _paths.fresh_test_dir("issue56-sidecar-supplement")
        base = root / "base.preembedding"
        delta = root / "delta.preembedding"
        contract = root / "delta-store"
        repair = {"artifact_id": "repair", "repair_count": 2}
        parent_bytes = b'{"parent":"sealed"}'
        parent_sha = "sha256:" + hashlib.sha256(parent_bytes).hexdigest()
        failure_manifest = {
            "artifact_id": ("formowl_bound_child_content_failure_exclusions_v1"),
            "schema_version": 1,
            "ingestion_job_id": "job_delta",
            "records": [{"child_extractor_run_id": "run_failed"}],
            "unknown_parse_failures_must_reject": True,
            "full_source_coverage_claim": False,
        }
        failure_path = root / "failure.json"
        failure_bytes = json.dumps(failure_manifest).encode()
        failure_path.write_bytes(failure_bytes)
        failure_binding = {
            "artifact_id": failure_manifest["artifact_id"],
            "manifest_byte_sha256": ("sha256:" + hashlib.sha256(failure_bytes).hexdigest()),
            "ingestion_job_id": "job_delta",
            "record_count": 1,
            "unknown_parse_failures_must_reject": True,
            "full_source_coverage_claim": False,
        }

        def write_preparation(
            path: Path,
            *,
            bindings: list[dict],
            jobs: list[dict],
            references: list[list],
            row_records: list[list],
            value_records: list[list],
            columns: list[dict],
            counts: dict,
            source_count: int,
            job_count: int,
            failure: dict | None = None,
        ) -> None:
            exact = path / "exact-cells"
            (exact / "rows").mkdir(parents=True)
            (exact / "values").mkdir()
            shards = []
            for kind, shard, records in (
                ("row", "aa", row_records),
                ("value", "bb", value_records),
            ):
                if not records:
                    continue
                payload = b"".join(
                    json.dumps(
                        record,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                    + b"\n"
                    for record in records
                )
                subdirectory = "rows" if kind == "row" else "values"
                (exact / subdirectory / f"{shard}.jsonl").write_bytes(payload)
                shards.append(
                    {
                        "kind": kind,
                        "shard": shard,
                        "record_count": len(records),
                        "size_bytes": len(payload),
                        "sha256": ("sha256:" + hashlib.sha256(payload).hexdigest()),
                    }
                )
            source_authority = sha256_json(jobs)
            exact_core = {
                "artifact_id": ("formowl_issue56_ingestion_exact_cell_lookup_v1"),
                "schema_version": 1,
                "source_authority_fingerprint": source_authority,
                "tokenizer_profile_fingerprint": "sha256:profile",
                "job_count": len(bindings),
                "counts": counts,
                "columns": columns,
                "shards": shards,
            }
            exact_bytes = json.dumps(
                {
                    **exact_core,
                    "manifest_fingerprint": sha256_json(exact_core),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            (exact / "manifest.json").write_bytes(exact_bytes)
            source_binding = {
                "jobs": jobs,
                "source_authority_fingerprint": source_authority,
                "exact_lookup_manifest_sha256": (
                    "sha256:" + hashlib.sha256(exact_bytes).hexdigest()
                ),
                "extraction_coverage": {
                    "scope": "declared_completed_jobs_only",
                    "root_count": job_count,
                    "warning_count": 0,
                    "warning_code_counts": {},
                    "source_completeness_certified": False,
                },
            }
            if failure is not None:
                source_binding["bound_child_failure_binding"] = failure
            snapshot = {
                "bundles": [],
                "observation_references": references,
                "source_binding": source_binding,
                "job_store_bindings": bindings,
            }
            snapshot_bytes = json.dumps(
                snapshot,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            (path / "observations.json").write_bytes(snapshot_bytes)
            preparation_core = {
                "artifact_id": ("formowl_issue56_ingestion_revision_preparation_v1"),
                "schema_version": 1,
                "requested_jobs": [
                    [item["store_directory"], item["ingestion_job_id"]] for item in bindings
                ],
                "sidecar_parent_job_id": ("job_prior" if job_count == 2 else None),
                "reference_repair_binding": repair if job_count == 2 else None,
                "bound_child_failure_binding": failure,
                "sidecar_parent_binding_sha256": (parent_sha if job_count == 2 else None),
                "snapshot_sha256": ("sha256:" + hashlib.sha256(snapshot_bytes).hexdigest()),
                "snapshot_size_bytes": len(snapshot_bytes),
                "exact_lookup_manifest_sha256": (
                    "sha256:" + hashlib.sha256(exact_bytes).hexdigest()
                ),
                "source_observation_count": source_count,
                "observation_type_counts": {
                    "table_row": len(row_records),
                    "table_cell": max(0, source_count - len(references)),
                },
                "job_count": job_count,
            }
            (path / "preparation.json").write_text(
                json.dumps(
                    {
                        **preparation_core,
                        "preparation_fingerprint": sha256_json(preparation_core),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )

        base_bindings = [
            {
                "job_index": 0,
                "store_directory": str(root / "store0"),
                "ingestion_job_id": "job_other",
                "job_fingerprint": "sha256:other",
                "observation_count": 1,
            },
            {
                "job_index": 1,
                "store_directory": str(root / "store1"),
                "ingestion_job_id": "job_prior",
                "job_fingerprint": "sha256:prior",
                "observation_count": 1,
            },
        ]
        delta_bindings = [
            {
                "job_index": 0,
                "store_directory": str(contract),
                "ingestion_job_id": "job_delta",
                "job_fingerprint": "sha256:delta",
                "observation_count": 2,
            }
        ]
        base_row = ["row", "sha256:row", 1, "obs_base", "sha256:base", False]
        delta_row = [
            "row",
            "sha256:row",
            0,
            "obs_delta",
            "sha256:delta-observation",
            False,
        ]
        write_preparation(
            base,
            bindings=base_bindings,
            jobs=[
                {"root_asset_hash": "sha256:other", "job_fingerprint": "sha256:other"},
                {"root_asset_hash": "sha256:asset", "job_fingerprint": "sha256:prior"},
            ],
            references=[
                [0, "obs_other", "sha256:other-observation"],
                [1, "obs_base", "sha256:base"],
            ],
            row_records=[base_row],
            value_records=[],
            columns=[],
            counts={"table_row": 1, "table_cell": 0},
            source_count=2,
            job_count=2,
        )
        (base / "sidecar-parent-binding.json").write_bytes(parent_bytes)
        write_preparation(
            delta,
            bindings=delta_bindings,
            jobs=[{"root_asset_hash": "sha256:asset", "job_fingerprint": "sha256:delta"}],
            references=[[0, "obs_delta", "sha256:delta-observation"]],
            row_records=[delta_row],
            value_records=[["sha256:value", "sha256:row", False]],
            columns=[
                {
                    "field": "COO",
                    "column_hash": "sha256:column",
                    "inline_table": False,
                    "structure_status": "source_provided",
                    "candidate_hashes": ["sha256:candidate"],
                }
            ],
            counts={"table_row": 1, "table_cell": 1},
            source_count=2,
            job_count=1,
            failure=failure_binding,
        )
        contract.mkdir()
        config = {
            "prior_ingestion_job_id": "job_prior",
            "prior_job_fingerprint": "sha256:prior",
            "parent_binding_byte_sha256": parent_sha,
            "reference_repair_binding": repair,
        }
        source_scope = {
            "source_asset_id": "asset_shared",
            "prior_ingestion_job_id": "job_prior",
            "reference_repair_binding": repair,
            "regenerate_parent_messages": False,
            "full_source_coverage_claim": False,
        }
        result = {
            "status": "succeeded",
            "ingestion_job_id": "job_delta",
            "prior_ingestion_job_id": "job_prior",
            "observation_count": 2,
            "full_source_coverage_claim": False,
        }
        parent_delta = {
            "artifact_id": "readpst_missing_parent_observation_delta_v1",
            "ingestion_job_id": "job_delta",
            "prior_ingestion_job_id": "job_prior",
            "original_parent_map_byte_sha256": parent_sha,
            "reference_repair_binding": repair,
            "repaired_parent_count": 1,
            "records": [{"observation_id": "obs_delta"}],
            "full_source_coverage_claim": False,
        }
        for name, value in (
            ("config.json", config),
            ("source-scope.json", source_scope),
            ("result.json", result),
            ("repaired-parent-delta.json", parent_delta),
        ):
            (contract / name).write_text(json.dumps(value))

        asset = SimpleNamespace(
            asset_id="asset_shared",
            content_hash="sha256:asset",
        )
        authorities = {
            "job_prior": SimpleNamespace(
                authority=SimpleNamespace(
                    asset=asset,
                    ingestion_job_id="job_prior",
                    job_fingerprint="sha256:prior",
                    observation_count=1,
                    permission_scope={"scope": "same"},
                )
            ),
            "job_delta": SimpleNamespace(
                authority=SimpleNamespace(
                    asset=asset,
                    ingestion_job_id="job_delta",
                    job_fingerprint="sha256:delta",
                    observation_count=2,
                    permission_scope={"scope": "same"},
                )
            ),
        }
        base_bytes = (base / "preparation.json").read_bytes()
        with patch(
            "formowl_mail.import_workflow.open_completed_ingestion_job_reader",
            side_effect=lambda job_id, **_: authorities[job_id],
        ):
            report = uat_web_script._compose_sidecar_supplement_preparation(
                root / "revision",
                base_preparation_directory=base,
                supplement_preparation_directory=delta,
                supplement_contract_directory=contract,
                prior_job_id="job_prior",
                bound_child_failure_manifest_path=failure_path,
            )
        output = Path(report["preparation_directory"])
        self.assertEqual((base / "preparation.json").read_bytes(), base_bytes)
        snapshot = json.loads((output / "observations.json").read_bytes())
        self.assertEqual(snapshot["observation_references"][-1][0], 2)
        self.assertEqual(
            len(snapshot["source_binding"]["jobs"][1]["supplements"]),
            1,
        )
        exact = json.loads((output / "exact-cells" / "manifest.json").read_bytes())
        self.assertFalse(exact["exact_query_capability_complete"])
        self.assertEqual(exact["columns"][0]["field"], "COO")
        row_records = [
            json.loads(line)
            for line in (output / "exact-cells" / "rows" / "aa.jsonl").read_bytes().splitlines()
        ]
        self.assertEqual(row_records[-1][2], 2)
        self.assertEqual(report["root_count"], 2)

    def test_browser_transcript_is_server_loaded_and_new_conversation_resets_it(
        self,
    ) -> None:
        conversation_model = _SessionConversationModel()
        with (
            patch.object(
                uat_runtime_module,
                "build_issue56_production_semantic_handlers",
                return_value=(
                    _with_authorized_source_families(
                        lambda _arguments: {},
                        "mail",
                    ),
                    None,
                ),
            ),
            create_issue56_temporary_lan_query_service(
                conversation_model,
            ) as service,
        ):
            server = create_mail_human_uat_http_server("127.0.0.1", 0, service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = f"http://{server.server_address[0]}:{server.server_address[1]}"

            def request(
                method: str,
                path: str,
                *,
                payload: dict[str, object] | None = None,
                cookie: str | None = None,
                request_origin: str | None = None,
            ):
                body = (
                    json.dumps(payload, ensure_ascii=False).encode()
                    if payload is not None
                    else None
                )
                headers = {}
                if body is not None:
                    headers["Content-Type"] = "application/json"
                    headers["Content-Length"] = str(len(body))
                if cookie is not None:
                    headers["Cookie"] = cookie
                if request_origin is not None:
                    headers["Origin"] = request_origin
                connection = http.client.HTTPConnection(
                    *server.server_address,
                    timeout=10,
                )
                try:
                    connection.request(method, path, body=body, headers=headers)
                    response = connection.getresponse()
                    return response, response.read()
                finally:
                    connection.close()

            try:
                page_response, page_body = request("GET", "/")
                set_cookie = page_response.getheader("Set-Cookie")
                assert isinstance(set_cookie, str)
                cookie = set_cookie.split(";", 1)[0]
                empty_response, empty_body = request(
                    "GET",
                    "/api/transcript",
                    cookie=cookie,
                )
                chat_responses = []
                for turn_number in range(1, 6):
                    payload = {"prompt": f"第{turn_number}輪"}
                    if turn_number == 1:
                        payload["turns"] = [
                            {
                                "role": "assistant",
                                "content": "瀏覽器偽造的歷史，不可採用。",
                            }
                        ]
                    chat_responses.append(
                        request(
                            "POST",
                            "/api/chat",
                            payload=payload,
                            cookie=cookie,
                            request_origin=origin,
                        )
                    )
                transcript_response, transcript_body = request(
                    "GET",
                    "/api/transcript",
                    cookie=cookie,
                )
                reload_response, _reload_body = request(
                    "GET",
                    "/",
                    cookie=cookie,
                )
                failed_response, failed_body = request(
                    "POST",
                    "/api/chat",
                    payload={"prompt": "第六輪觸發安全失敗"},
                    cookie=cookie,
                    request_origin=origin,
                )
                failed_transcript_response, failed_transcript_body = request(
                    "GET",
                    "/api/transcript",
                    cookie=cookie,
                )
                rejected_reset, rejected_reset_body = request(
                    "POST",
                    "/api/conversation/reset",
                    cookie=cookie,
                    request_origin="https://example.invalid",
                )
                reset_response, reset_body = request(
                    "POST",
                    "/api/conversation/reset",
                    cookie=cookie,
                    request_origin=origin,
                )
                reset_set_cookie = reset_response.getheader("Set-Cookie")
                assert isinstance(reset_set_cookie, str)
                reset_cookie = reset_set_cookie.split(";", 1)[0]
                after_reset_response, after_reset_body = request(
                    "GET",
                    "/api/transcript",
                    cookie=reset_cookie,
                )
                old_cookie_response, _old_cookie_body = request(
                    "GET",
                    "/api/transcript",
                    cookie=cookie,
                )
                new_turn_response, _new_turn_body = request(
                    "POST",
                    "/api/chat",
                    payload={"prompt": "新對話第一輪"},
                    cookie=reset_cookie,
                    request_origin=origin,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        page = page_body.decode()
        empty_payload = json.loads(empty_body)
        transcript_payload = json.loads(transcript_body)
        failed_payload = json.loads(failed_body)
        failed_transcript_payload = json.loads(failed_transcript_body)
        reset_payload = json.loads(reset_body)
        after_reset_payload = json.loads(after_reset_body)

        self.assertEqual(page_response.status, 200)
        self.assertIn('id="conversation-transcript"', page)
        self.assertIn('id="new-conversation-button"', page)
        self.assertIn('fetch("/api/transcript"', page)
        self.assertIn('fetch("/api/conversation/reset"', page)
        self.assertNotIn("function resetResult()", page)
        self.assertNotIn('id="answer-text"', page)
        self.assertNotIn('id="citation-summary"', page)
        self.assertIn("不是永久或無限記憶", page)
        self.assertEqual(empty_response.status, 200)
        self.assertEqual(
            empty_payload,
            {
                "retention": "temporary_bounded",
                "turn_count": 0,
                "turns": [],
            },
        )
        self.assertTrue(all(response.status == 200 for response, _body in chat_responses))
        self.assertEqual(transcript_response.status, 200)
        self.assertEqual(transcript_payload["turn_count"], 5)
        self.assertEqual(
            transcript_payload["turns"][0]["prompt"],
            "第1輪",
        )
        self.assertEqual(
            transcript_payload["turns"][4]["prompt"],
            "第5輪",
        )
        self.assertNotIn(
            "瀏覽器偽造的歷史",
            json.dumps(transcript_payload, ensure_ascii=False),
        )
        self.assertEqual(
            [len(call["history"]) for call in conversation_model.calls[:5]],
            [0, 2, 4, 6, 8],
        )
        self.assertEqual(reload_response.status, 200)
        self.assertIsNone(reload_response.getheader("Set-Cookie"))
        self.assertEqual(failed_response.status, 500)
        self.assertEqual(failed_payload["error_code"], "query_failed")
        self.assertEqual(failed_transcript_response.status, 200)
        self.assertEqual(failed_transcript_payload["turn_count"], 6)
        failed_turn = failed_transcript_payload["turns"][-1]
        self.assertEqual(failed_turn["prompt"], "第六輪觸發安全失敗")
        self.assertEqual(failed_turn["response"]["status"], "error")
        self.assertTrue(failed_turn["response"]["answer"])
        self.assertNotIn(
            "private backend failure detail",
            json.dumps(failed_turn, ensure_ascii=False),
        )
        self.assertEqual(rejected_reset.status, 403)
        self.assertEqual(
            json.loads(rejected_reset_body)["error_code"],
            "same_origin_required",
        )
        self.assertEqual(reset_response.status, 200)
        self.assertEqual(
            reset_payload,
            {
                "retention": "temporary_bounded",
                "status": "reset",
                "turn_count": 0,
                "turns": [],
            },
        )
        for required in (
            "formowl_uat_session=",
            "HttpOnly",
            "SameSite=Lax",
            "Path=/",
            "Max-Age=3600",
        ):
            self.assertIn(required, reset_set_cookie)
        self.assertEqual(after_reset_response.status, 200)
        self.assertEqual(after_reset_payload["turns"], [])
        self.assertEqual(old_cookie_response.status, 401)
        self.assertNotEqual(cookie, reset_cookie)
        self.assertEqual(new_turn_response.status, 200)
        self.assertEqual(conversation_model.calls[-1]["history"], ())

    @contextmanager
    def _source_start_cli(self, fixture, *, model=None, serve=None, expected_sha256=None):
        """Actual main/loader/service; replace only the external model and lifetime."""
        root = fixture.directory.parent
        key = root / "synthetic-provider.key"
        key.write_text("synthetic-cli-provider-key", encoding="utf-8")
        key.chmod(0o600)
        unused_config = root / "UNUSED-unavailable-postgres.json"
        self.assertFalse(unused_config.exists())
        arguments = [
            "issue56_uat_web.py", "--temporary-lan-diagnostic",
            "--host", "127.0.0.1", "--port", "0",
            "--codex-runtime-state-dir", str(root / "runtime"),
            "--codex-provider-api-key-file", str(key),
            "--ingestion-revision", str(fixture.directory),
            "--ingestion-revision-sha256", expected_sha256 or fixture.preparation_sha256,
            "--ingestion-projection-postgres-config", str(unused_config),
        ]
        runtime_paths = SimpleNamespace(
            codex_home=root / "codex-home", workspace=root,
            provider_base_url="https://provider.example.test/v1",
            provider_env_key="FORMOWL_TEST_CLI_PROVIDER_KEY",
        )
        real_open = Path.open
        config_reads = []

        def checked_open(path, *args, **kwargs):
            if path == unused_config:
                config_reads.append(path)
                raise AssertionError("source-only CLI must not open the PG config")
            return real_open(path, *args, **kwargs)

        with (
            patch.object(uat_web_script.sys, "argv", arguments),
            patch.object(uat_web_script, "validate_codex_runtime_state",
                         return_value=runtime_paths),
            patch.object(uat_web_script, "CodexResponsesConversationModel",
                         return_value=model or _SessionConversationModel()),
            patch.object(Path, "open", checked_open),
            patch.object(uat_web_script, "_open_ingestion_projection_connection",
                         side_effect=RuntimeError("synthetic PostgreSQL unavailable")) as pg_open,
            patch("psycopg.connect",
                  side_effect=AssertionError("no PostgreSQL connection allowed")) as pg_connect,
            patch.object(sealed_source, "load_issue56_ingestion_revision",
                         wraps=sealed_source.load_issue56_ingestion_revision) as load,
            patch.object(uat_web_script, "create_issue56_temporary_lan_query_service",
                         wraps=create_issue56_temporary_lan_query_service) as service,
            patch.object(sealed_loader, "source_evidence_double_check",
                         wraps=source_evidence_double_check) as core,
            patch.object(sealed_source, "build_issue56_ingestion_revision",
                         side_effect=AssertionError("no inline revision rebuild")) as rebuild,
            patch.object(hybrid, "build_authorized_semantic_observation_session",
                         side_effect=AssertionError("no inline index build")) as index,
            patch.object(hybrid, "build_authorized_source_backed_effective_graph_view",
                         side_effect=AssertionError("no inline graph build")) as graph,
            patch.object(hybrid, "reopen_authorized_semantic_observation_session",
                         side_effect=AssertionError("no projection reopen")) as reopen,
            patch("formowl_core.dense_embedding.SentenceTransformerDenseEncoder.encode_evidence_batch",
                  side_effect=AssertionError("no embedding")) as embed,
            patch.object(ThreadingHTTPServer, "serve_forever", autospec=True,
                         side_effect=serve or (lambda _server: None)) as lifetime,
            redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()),
        ):
            yield SimpleNamespace(
                load=load, service=service, core=core, lifetime=lifetime,
                pg_open=pg_open, pg_connect=pg_connect, config_reads=config_reads,
                forbidden=(rebuild, index, graph, reopen, embed),
            )

    def test_cli_source_only_preparation_starts_mail_text_and_chat_without_postgres(self):
        """Enter through main(), real HTTP and normal MCP, not loader-only wiring."""
        real_serve = ThreadingHTTPServer.serve_forever
        responses, tool_results = [], []

        class SourceStartModel(_SessionConversationModel):
            selector = None

            def respond(self, *, user_text, evidence_tool, **kwargs):
                if user_text == "你好":
                    return super().respond(
                        user_text=user_text, evidence_tool=evidence_tool, **kwargs,
                    )
                mail = user_text == "Find written owner approval in the authorized mail."
                request = UatEvidenceToolRequest(
                    tool_name="query_mail_evidence" if mail else "query_effective_graph_view",
                    query_text="written owner approval",
                    mail_import_session_id=self.selector if mail else None,
                    required_terms=("approval",) if mail else None,
                    request_contract={
                        "original_query_hash": sha256_json(user_text),
                        "query_class": "evidence_lookup",
                        "source_family_scope": ["mail" if mail else "document_text"],
                        "requested_fields": ["acceptance_condition"],
                        "maximum_claim_strength": "cited_evidence",
                    },
                )
                result = evidence_tool(request)
                tool_results.append(result)
                snippets = result.get("evidence_snippets") or result.get("evidence") or ()
                citations = tuple(
                    item["citation_id"] if isinstance(item, Mapping) else item
                    for item in result.get("citations", ())
                )
                if not snippets or not citations:
                    raise AssertionError("actual CLI MCP did not return governed source evidence")
                return UatConversationOutcome(
                    response_kind="answer", answer_text=snippets[0]["snippet"],
                    display_format="narrative", model_name=self.model_name,
                    citation_ids=(citations[0],), coverage_status="incomplete",
                    coverage_note="Only the declared synthetic source scope was searched.",
                    tool_requests=(request,), tool_results=(result,),
                )

        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(Path(directory))
            model = SourceStartModel()

            def serve(server):
                revision = probes.service.call_args.kwargs["ingestion_revision"]
                self.assertIsNone(revision.session)
                self.assertIsNone(revision.graph_build)
                model.selector = revision.source_records.authorized_mail_import_session_ids[0]
                thread = threading.Thread(target=real_serve, args=(server,), daemon=True)
                thread.start()
                connection = http.client.HTTPConnection(*server.server_address, timeout=10)
                try:
                    connection.request("GET", "/")
                    page = connection.getresponse()
                    page.read()
                    self.assertEqual(page.status, 200)
                    cookie = page.getheader("Set-Cookie").split(";", 1)[0]
                    origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
                    for prompt in (
                        "你好", "Find written owner approval in the authorized mail.",
                        "Find the independent document acceptance condition.",
                    ):
                        connection.request(
                            "POST", "/api/chat", body=json.dumps({"prompt": prompt}),
                            headers={"Content-Type": "application/json",
                                     "Cookie": cookie, "Origin": origin},
                        )
                        response = connection.getresponse()
                        payload = json.loads(response.read())
                        self.assertEqual(response.status, 200)
                        responses.append(payload)
                finally:
                    connection.close()
                    server.shutdown()
                    thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

            with self._source_start_cli(fixture, model=model, serve=serve) as probes:
                self.assertEqual(uat_web_script.main(), 0)
                probes.load.assert_called_once()
                probes.service.assert_called_once()
                probes.lifetime.assert_called_once()
                self.assertEqual(probes.core.call_count, 2)
                probes.pg_open.assert_not_called()
                probes.pg_connect.assert_not_called()
                self.assertEqual(probes.config_reads, [])
                for forbidden in probes.forbidden:
                    forbidden.assert_not_called()
            self.assertEqual(responses[0]["diagnostic"]["mcp"]["call_count"], 0)
            self.assertEqual(responses[0]["citation_count"], 0)
            expected_observations = [
                next(item for item in fixture.observations
                     if item.observation_type == observation_type)
                for observation_type in ("email_body_segment", "paragraph")
            ]
            self.assertEqual(len(tool_results), 2)
            for payload, result, family, observation in zip(
                responses[1:], tool_results, ("mail", "document_text"), expected_observations,
            ):
                self.assertEqual(payload["status"], "partial")
                self.assertEqual(payload["diagnostic"]["mcp"]["call_count"], 1)
                self.assertEqual(payload["citation_count"], 1)
                self.assertEqual(payload["answer"], observation.text)
                expected_citation = (
                    "mailcitation_" + sha256_json({
                        "mail_import_session_id": model.selector,
                        "source_observation_id": observation.observation_id,
                    })[-24:] if family == "mail" else sha256_json(observation.to_dict())
                )
                self.assertEqual(payload["citations"], [expected_citation])
                coverage_key = "requested_field_coverage" if family == "mail" else "coverage"
                self.assertEqual(result[coverage_key]["status"], "incomplete")
                snippets = result.get("evidence_snippets") or result["evidence"]
                self.assertEqual(snippets[0]["citation_hash"], sha256_json(observation.to_dict()))
                if family == "document_text":
                    self.assertEqual(
                        (snippets[0]["document_locator"]["line_start"],
                         snippets[0]["document_locator"]["line_end"]),
                        (observation.location["line_start"], observation.location["line_end"]),
                    )
                assert_no_public_raw_references(payload, "source_only_cli_response")

    def test_cli_source_only_preparation_rejects_source_corruption_before_postgres(self):
        from formowl_contract import ContractValidationError
        from formowl_ingestion.storage import JobStore

        # Three source bindings, not a broad negative matrix.
        for corruption in ("sha", "job", "snapshot"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as directory:
                fixture = _source_start_preparation_fixture(Path(directory))
                expected = fixture.preparation_sha256
                if corruption == "sha":
                    expected = sha256_json("wrong CLI source SHA")
                elif corruption == "snapshot":
                    path = fixture.directory / "observations.json"
                    path.write_bytes(path.read_bytes() + b" ")
                else:
                    binding = fixture.snapshot["job_store_bindings"][0]
                    store = JobStore(Path(binding["store_directory"]))
                    job = store.get(binding["ingestion_job_id"])
                    store.create(replace(job, requested_by="user_unauthorized"))
                with self._source_start_cli(fixture, expected_sha256=expected) as probes:
                    with self.assertRaises((sealed_source.Issue56SealedSourceLoadError,
                                            ContractValidationError)):
                        uat_web_script.main()
                    probes.load.assert_called_once()
                    probes.service.assert_not_called()
                    probes.lifetime.assert_not_called()
                    probes.pg_open.assert_not_called()
                    probes.pg_connect.assert_not_called()
                    self.assertEqual(probes.config_reads, [])
                    for forbidden in probes.forbidden:
                        forbidden.assert_not_called()

    def test_cli_indexed_revision_cannot_downgrade_to_preparation_when_postgres_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(Path(directory))
            # A finalized marker with real sealed source bindings; no usable
            # projection/seal is fabricated. PG unavailability must stop startup.
            finalized = {
                "artifact_id": "formowl_issue56_ingestion_revision_v1",
                "requester_user_id": sealed_source.APPROVER_ACTOR,
                "workspace_id": sealed_source.WORKSPACE_ID,
                "snapshot_sha256": fixture.preparation_core["snapshot_sha256"],
                "storage_mode": "postgresql_projection_v1",
                "source_binding": fixture.snapshot["source_binding"],
                "job_store_bindings": fixture.snapshot["job_store_bindings"],
            }
            path = fixture.directory / "revision.json"
            path.write_text(json.dumps(finalized, sort_keys=True), encoding="utf-8")
            with self._source_start_cli(fixture, expected_sha256=_sha256_path(path)) as probes:
                with self.assertRaisesRegex(RuntimeError, "synthetic PostgreSQL unavailable"):
                    uat_web_script.main()
                probes.load.assert_called_once()
                probes.pg_open.assert_called_once()
                probes.service.assert_not_called()
                probes.lifetime.assert_not_called()
                probes.pg_connect.assert_not_called()
                for forbidden in probes.forbidden:
                    forbidden.assert_not_called()

    def test_cli_binds_private_custom_provider_key_and_fails_closed(self) -> None:
        provider_env_key = "FORMOWL_TEST_CUSTOM_PROVIDER_KEY"
        provider_api_key = "synthetic-provider-key-never-public"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            key_path = root / "provider.key"
            key_path.write_text(provider_api_key, encoding="utf-8")
            key_path.chmod(0o600)
            runtime_paths = SimpleNamespace(
                codex_home=root / "codex-home",
                workspace=root / "workspace",
                provider_base_url="https://provider.example.test/v1",
                provider_env_key=provider_env_key,
            )
            transport = MagicMock()
            conversation_model = MagicMock()
            query_service = MagicMock()
            query_service.__enter__.return_value = query_service
            server = MagicMock()
            arguments = [
                "issue56_uat_web.py",
                "--temporary-lan-diagnostic",
                "--codex-runtime-state-dir",
                str(root / "runtime"),
                "--codex-provider-api-key-file",
                str(key_path),
            ]
            standard_output = io.StringIO()
            standard_error = io.StringIO()
            with (
                patch.object(
                    uat_web_script, "validate_codex_runtime_state", return_value=runtime_paths
                ),
                patch.object(
                    uat_web_script,
                    "CodexAppServerStdioTransport",
                    return_value=transport,
                ) as transport_factory,
                patch.object(
                    uat_web_script,
                    "CodexAppServerConversationModel",
                ) as app_server_model_factory,
                patch.object(
                    uat_web_script,
                    "CodexResponsesConversationModel",
                    return_value=conversation_model,
                ) as responses_model_factory,
                patch.object(
                    uat_web_script,
                    "create_issue56_temporary_lan_query_service",
                    return_value=query_service,
                ) as query_service_factory,
                patch.object(
                    uat_web_script,
                    "create_mail_human_uat_http_server",
                    return_value=server,
                ) as server_factory,
                patch.object(uat_web_script.sys, "argv", arguments),
                redirect_stdout(standard_output),
                redirect_stderr(standard_error),
            ):
                self.assertEqual(uat_web_script.main(), 0)

            responses_model_factory.assert_called_once_with(
                base_url=runtime_paths.provider_base_url,
                api_key=provider_api_key,
                model="gpt-5.5",
            )
            transport_factory.assert_not_called()
            app_server_model_factory.assert_not_called()
            self.assertNotIn(
                provider_api_key,
                standard_output.getvalue() + standard_error.getvalue(),
            )
            server.serve_forever.assert_called_once_with()
            server_factory.assert_called_once_with(
                "0.0.0.0",
                8088,
                query_service,
                temporary_access_code=None,
            )

            explicit_server = MagicMock()
            explicit_query_service = MagicMock()
            explicit_query_service.__enter__.return_value = explicit_query_service
            server_factory.reset_mock()
            server_factory.return_value = explicit_server
            query_service_factory.reset_mock()
            query_service_factory.return_value = explicit_query_service
            explicit_arguments = [
                "issue56_uat_web.py",
                "--temporary-lan-diagnostic",
                "--host",
                "127.0.0.1",
                "--port",
                "9876",
                "--temporary-access-code",
                "explicit-lan-code",
                "--codex-runtime-state-dir",
                str(root / "runtime"),
                "--codex-provider-api-key-file",
                str(key_path),
            ]
            with (
                patch.object(
                    uat_web_script,
                    "validate_codex_runtime_state",
                    return_value=runtime_paths,
                ),
                patch.object(
                    uat_web_script,
                    "CodexResponsesConversationModel",
                    return_value=conversation_model,
                ),
                patch.object(
                    uat_web_script,
                    "create_issue56_temporary_lan_query_service",
                    return_value=explicit_query_service,
                ),
                patch.object(
                    uat_web_script,
                    "create_mail_human_uat_http_server",
                    return_value=explicit_server,
                ) as explicit_server_factory,
                patch.object(uat_web_script.sys, "argv", explicit_arguments),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(uat_web_script.main(), 0)
            explicit_server_factory.assert_called_once_with(
                "127.0.0.1",
                9876,
                explicit_query_service,
                temporary_access_code="explicit-lan-code",
            )
            explicit_server.serve_forever.assert_called_once_with()

            with patch.object(
                uat_web_script,
                "validate_codex_runtime_state",
                return_value=SimpleNamespace(
                    codex_home=root / "chatgpt-home",
                    workspace=root / "chatgpt-workspace",
                    provider_base_url=None,
                    provider_env_key=None,
                ),
            ):
                with (
                    patch.object(uat_web_script.sys, "argv", arguments),
                    redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    uat_web_script.main()

            missing_key_arguments = [
                argument
                for argument in arguments
                if argument not in {"--codex-provider-api-key-file", str(key_path)}
            ]
            with (
                patch.object(
                    uat_web_script,
                    "validate_codex_runtime_state",
                    return_value=runtime_paths,
                ),
                patch.object(uat_web_script.sys, "argv", missing_key_arguments),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                uat_web_script.main()

            key_path.chmod(0o644)
            with self.assertRaises(ValueError):
                uat_web_script._read_codex_provider_api_key(key_path)
            key_path.chmod(0o600)
            symlink_path = root / "provider-link"
            symlink_path.symlink_to(key_path)
            with self.assertRaises(ValueError):
                uat_web_script._read_codex_provider_api_key(symlink_path)
            with self.assertRaises(ValueError):
                uat_web_script._read_codex_provider_api_key(Path("provider.key"))
            key_path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                uat_web_script._read_codex_provider_api_key(key_path)
            key_path.write_bytes(b"x" * (uat_web_script._MAX_PROVIDER_API_KEY_BYTES + 1))
            with self.assertRaises(ValueError):
                uat_web_script._read_codex_provider_api_key(key_path)

    def test_temporary_lan_real_document_text_recheck_survives_browser_session(self) -> None:
        """Exercise the real text reader through HTTP without a provider."""

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            revision_root = root / "registered-text"
            revision_root.mkdir()
            asset, observations, job_authority = _completed_registered_text_revision_fixture(
                revision_root,
                owner_user_id=sealed_loader.APPROVER_ACTOR,
            )
            paragraph = next(item for item in observations if item.observation_type == "paragraph")
            source_references = [
                [0, item.observation_id, sha256_json(item.to_dict())]
                for item in observations
            ]
            source_authority_fingerprint = sha256_json(
                {
                    "asset_id": asset.asset_id,
                    "asset_content_hash": asset.content_hash,
                    "completed_job_fingerprint": job_authority.job_fingerprint,
                    "observation_hashes": sorted(
                        sha256_json(item.to_dict()) for item in observations
                    ),
                }
            )
            runtime = _contract_only_runtime()
            with (
                patch.object(
                    sealed_source,
                    "load_issue56_target_runtime_components",
                    return_value=runtime,
                ),
                patch.object(
                    hybrid,
                    "_load_pinned_issue56_runtime_components",
                    return_value=runtime,
                ),
            ):
                revision = build_issue56_ingestion_revision(
                    observations=observations,
                    bundles=(),
                    source_binding={
                        "source_authority_fingerprint": source_authority_fingerprint,
                        "registered_asset_revision_fingerprint": (source_authority_fingerprint),
                        "extraction_coverage": {
                            "source_completeness_certified": False,
                        },
                    },
                    requester_user_id=sealed_loader.APPROVER_ACTOR,
                    workspace_id=sealed_loader.WORKSPACE_ID,
                    source_authority_fingerprint=source_authority_fingerprint,
                    retrieval_observation_ids=(
                        next(
                            item for item in observations if item.observation_type == "heading"
                        ).observation_id,
                    ),
                )
            revision = replace(
                revision,
                job_authorities=(job_authority,),
                source_records=IngestionRevisionSourceRecords(
                    runtime_store=SimpleNamespace(
                        workspace_id=sealed_loader.WORKSPACE_ID,
                    ),
                    job_authorities=(job_authority,),
                    requester_user_id=sealed_loader.APPROVER_ACTOR,
                    workspace_id=sealed_loader.WORKSPACE_ID,
                    observation_references=source_references,
                ),
            )

            query_text = "written owner approval"
            document_prompt = "Find the acceptance condition in the project document."
            request_contract = {
                "original_query_hash": sha256_json(document_prompt),
                "query_class": "evidence_lookup",
                "source_family_scope": ["document_text"],
                "requested_fields": [],
                "maximum_claim_strength": "cited_evidence",
            }

            class DocumentConversationModel:
                model_name = "provider-free-document-model"

                def __init__(self) -> None:
                    self.calls: list[str] = []
                    self.requests: list[UatEvidenceToolRequest] = []
                    self.tool_results: list[Mapping[str, object]] = []

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
                        latest_evidence,
                        safety_identifier,
                        formowl_tool_descriptor,
                        authorized_capability_summary,
                    )
                    self.calls.append(user_text)
                    if user_text == "你好":
                        return UatConversationOutcome(
                            response_kind="answer",
                            answer_text="你好，請告訴我想查詢的資料。",
                            display_format="narrative",
                            model_name=self.model_name,
                            coverage_status="not_applicable",
                        )
                    request = UatEvidenceToolRequest(
                        query_text=query_text,
                        request_contract=request_contract,
                    )
                    result = evidence_tool(request)
                    self.requests.append(request)
                    self.tool_results.append(result)
                    citations = tuple(result.get("citations", ()))
                    evidence = tuple(result.get("evidence", ()))
                    if not citations or not evidence:
                        raise AssertionError("document source recheck returned no evidence")
                    return UatConversationOutcome(
                        response_kind="answer",
                        answer_text=f"驗收條件：{evidence[0]['snippet']}",
                        display_format="narrative",
                        model_name=self.model_name,
                        citation_ids=citations,
                        coverage_status="incomplete",
                        coverage_note="已取得授權文件引用，但來源完整性尚未認證。",
                        tool_requests=(request,),
                        tool_results=(result,),
                    )

                def discard_conversation(self, safety_identifier) -> None:
                    del safety_identifier

                def close(self) -> None:
                    return

            conversation_model = DocumentConversationModel()
            origin: str

            def request(server, method, path, *, payload=None, cookie=None):
                body = (
                    json.dumps(payload, ensure_ascii=False).encode()
                    if payload is not None
                    else None
                )
                headers = {}
                if body is not None:
                    headers.update(
                        {
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                        }
                    )
                headers["Origin"] = origin
                if cookie is not None:
                    headers["Cookie"] = cookie
                connection = http.client.HTTPConnection(
                    *server.server_address,
                    timeout=30,
                )
                try:
                    connection.request(method, path, body=body, headers=headers)
                    response = connection.getresponse()
                    return response, response.read()
                finally:
                    connection.close()

            with create_issue56_temporary_lan_query_service(
                conversation_model,
                ingestion_revision=revision,
                query_agent_planner=lambda original, steps, _profile, _limit: (
                    original if not steps else None
                ),
            ) as query_service:
                server = create_mail_human_uat_http_server(
                    "127.0.0.1",
                    0,
                    query_service,
                )
                origin = f"http://{server.server_address[0]}:{server.server_address[1]}"
                thread = threading.Thread(
                    target=server.serve_forever,
                    daemon=True,
                )
                thread.start()
                try:
                    page_response, page_body = request(server, "GET", "/")
                    set_cookie = page_response.getheader("Set-Cookie")
                    assert isinstance(set_cookie, str)
                    cookie = set_cookie.split(";", 1)[0]
                    greeting_response, greeting_body = request(
                        server,
                        "POST",
                        "/api/chat",
                        payload={"prompt": "你好"},
                        cookie=cookie,
                    )
                    greeting_mcp_count = query_service.request_count
                    document_response, document_body = request(
                        server,
                        "POST",
                        "/api/chat",
                        payload={"prompt": document_prompt},
                        cookie=cookie,
                    )
                    document_mcp_count = query_service.request_count
                    reload_response, reload_body = request(
                        server,
                        "GET",
                        "/",
                        cookie=cookie,
                    )
                    transcript_response, transcript_body = request(
                        server,
                        "GET",
                        "/api/transcript",
                        cookie=cookie,
                    )
                    reset_response, reset_body = request(
                        server,
                        "POST",
                        "/api/conversation/reset",
                        cookie=cookie,
                    )
                    reset_set_cookie = reset_response.getheader("Set-Cookie")
                    assert isinstance(reset_set_cookie, str)
                    reset_cookie = reset_set_cookie.split(";", 1)[0]
                    after_reset_response, after_reset_body = request(
                        server,
                        "GET",
                        "/api/transcript",
                        cookie=reset_cookie,
                    )
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

            page = page_body.decode()
            greeting_payload = json.loads(greeting_body)
            document_payload = json.loads(document_body)
            reload_page = reload_body.decode()
            transcript_payload = json.loads(transcript_body)
            reset_payload = json.loads(reset_body)
            after_reset_payload = json.loads(after_reset_body)
            self.assertEqual(page_response.status, 200)
            self.assertIn('id="conversation-transcript"', page)
            self.assertEqual(greeting_response.status, 200)
            self.assertEqual(greeting_payload["citation_count"], 0)
            self.assertEqual(greeting_mcp_count, 0)
            self.assertEqual(document_response.status, 200)
            self.assertIn(document_payload["status"], {"complete", "partial"})
            self.assertIn("Acceptance requires written owner approval.", document_payload["answer"])
            self.assertEqual(document_payload["citation_count"], 1)
            self.assertEqual(document_mcp_count, 1)
            self.assertEqual(query_service.last_mcp_statuses, ("ok",))
            self.assertEqual(len(conversation_model.requests), 1)
            self.assertEqual(
                conversation_model.requests[0].request_contract["source_family_scope"],
                ["document_text"],
            )
            recovery = conversation_model.tool_results[0]["query_agent"]["context_bundle"][
                "source_recovery"
            ]
            self.assertTrue(recovery["attempted"])
            self.assertEqual(recovery["initial_status"], "no_answer")
            self.assertEqual(recovery["status"], "ok")
            self.assertTrue(recovery["scan"]["complete"])
            citation = next(
                item
                for item in recovery["evidence"]
                if item["citation_hash"] == sha256_json(paragraph.to_dict())
            )
            self.assertEqual(
                citation["document_locator"],
                {
                    "block_type": "paragraph",
                    "asset_id": asset.asset_id,
                    "extractor_run_id": paragraph.extractor_run_id,
                    "line_start": paragraph.location["line_start"],
                    "line_end": paragraph.location["line_end"],
                },
            )
            self.assertEqual(
                citation["revision_binding"],
                {
                    "source_authority_fingerprint": source_authority_fingerprint,
                    "source_session_binding_fingerprint": (
                        revision.session.source_session_binding_fingerprint
                    ),
                },
            )
            self.assertTrue(
                any(
                    citation["citation_hash"] in turn["response"]["citations"]
                    for turn in transcript_payload["turns"]
                )
            )
            self.assertEqual(reload_response.status, 200)
            self.assertIsNone(reload_response.getheader("Set-Cookie"))
            self.assertIn('id="conversation-transcript"', reload_page)
            self.assertEqual(transcript_response.status, 200)
            self.assertEqual(transcript_payload["turn_count"], 2)
            self.assertEqual(reset_response.status, 200)
            self.assertEqual(reset_payload["turns"], [])
            self.assertEqual(after_reset_response.status, 200)
            self.assertEqual(after_reset_payload["turns"], [])
            self.assertNotEqual(cookie, reset_cookie)

    def test_temporary_lan_uses_real_sealed_source_normal_mcp_and_opt_in_log(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch.object(
                sealed_fixture,
                "WORKSPACE_PERMISSION_SCOPE",
                _PERMISSION_SCOPE,
            ):
                package = _prepare_package(root / "sealed")
            supplemental_path, parent_path = _write_supplemental_partition(
                root,
                package,
            )
            environment = dict(__import__("os").environ)
            environment.update(_loader_environment(package))
            environment.update(
                {
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_PATH": str(
                        supplemental_path
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_SHA256": (
                        _sha256_path(supplemental_path)
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_PATH": str(parent_path),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_SHA256": (
                        _sha256_path(parent_path)
                    ),
                }
            )
            greeting = "你好，今天過得如何？"
            prompt = f"麻煩幫我確認一下 {_IDENTIFIER} 這筆的 {_HEADER}，謝謝。"
            standalone_query = f"有{_IDENTIFIER}的{_HEADER}呢？"
            provider_api_key = "synthetic-direct-provider-key-never-public"
            conversation_model = CodexResponsesConversationModel(
                base_url="https://provider.example.test/v1",
                api_key=provider_api_key,
            )
            provider_requests: list[dict[str, object]] = []

            def provider_response(request):
                provider_requests.append(json.loads(json.dumps(request)))
                response_input = request["input"]
                if response_input[-1].get("role") == "user":
                    if response_input[-1]["content"] == greeting:
                        return {
                            "status": "completed",
                            "output_text": json.dumps(
                                {
                                    "response_kind": "answer",
                                    "answer_text": "你好，請告訴我想查詢的資料。",
                                    "display_format": "narrative",
                                    "citation_ids": [],
                                    "coverage_status": "not_applicable",
                                    "coverage_note": "",
                                }
                            ),
                        }
                    return {
                        "status": "completed",
                        "output": [
                            {
                                "type": "function_call",
                                "call_id": "browser-source-call",
                                "name": "query_effective_graph_view",
                                "arguments": json.dumps(
                                    {
                                        "query_text": standalone_query,
                                        "required_terms": [_IDENTIFIER, _HEADER],
                                        "table_query": {
                                            "filters": [
                                                {
                                                    "field": "PartNumber",
                                                    "value": _IDENTIFIER,
                                                }
                                            ],
                                            "projection_fields": [_HEADER],
                                        },
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ],
                    }
                tool_output = json.loads(response_input[-1]["output"])
                evidence = tool_output["data"]
                inventory = evidence["exact_inventory"]
                values = inventory["items"][0]["structured_values"]
                citations = evidence["citations"]
                answer = "\n".join(f"{value['field']}: {value['value']}" for value in values)
                return {
                    "status": "completed",
                    "output_text": json.dumps(
                        {
                            "response_kind": "answer",
                            "answer_text": f"{answer} [{citations[0]}]",
                            "display_format": "narrative",
                            "citation_ids": [citations[0]],
                            "coverage_status": (
                                "complete"
                                if evidence["status"] == "complete"
                                and inventory["coverage_status"] == "complete"
                                else "incomplete"
                            ),
                            "coverage_note": (
                                ""
                                if evidence["status"] == "complete"
                                and inventory["coverage_status"] == "complete"
                                else "來源涵蓋範圍仍不完整。"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                }

            access_code = "synthetic-lan-access-731"
            basic_authorization = (
                "Basic " + base64.b64encode(f"formowl-uat:{access_code}".encode()).decode()
            )
            wrong_authorization = (
                "Basic " + base64.b64encode(f"formowl-uat:{access_code}-wrong".encode()).decode()
            )
            behavior_log = root / "consented-behavior.jsonl"
            handler_arguments: list[dict[str, object]] = []
            handler_results: list[object] = []
            loader_build_count = 0
            cached_handlers = None
            original_builder = uat_runtime_module.build_issue56_production_semantic_handlers

            def build_once():
                nonlocal cached_handlers, loader_build_count
                if cached_handlers is None:
                    loader_build_count += 1
                    real_handler, real_mail_handler = original_builder()

                    def observed_handler(arguments):
                        handler_arguments.append(dict(arguments))
                        result = real_handler(arguments)
                        handler_results.append(result)
                        return result

                    observed_handler.authorized_capability_summary = (
                        real_handler.authorized_capability_summary
                    )
                    cached_handlers = (observed_handler, real_mail_handler)
                return cached_handlers

            def browser_request(
                server,
                method,
                path,
                *,
                prompt=None,
                authorization=None,
                cookie=None,
            ):
                body = (
                    json.dumps({"prompt": prompt}, ensure_ascii=False).encode()
                    if prompt is not None
                    else None
                )
                headers = {}
                if body is not None:
                    host, port = server.server_address
                    headers.update(
                        {
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                            "Origin": f"http://{host}:{port}",
                        }
                    )
                if authorization is not None:
                    headers["Authorization"] = authorization
                if cookie is not None:
                    headers["Cookie"] = cookie
                connection = http.client.HTTPConnection(
                    *server.server_address,
                    timeout=30,
                )
                try:
                    connection.request(method, path, body=body, headers=headers)
                    response = connection.getresponse()
                    return response, response.read()
                finally:
                    connection.close()

            with (
                patch.dict(__import__("os").environ, environment, clear=True),
                patch.object(
                    conversation_model,
                    "_request_response",
                    side_effect=provider_response,
                ),
                patch.object(
                    conversation_model,
                    "close",
                    wraps=conversation_model.close,
                ) as model_close,
                patch.object(
                    uat_runtime_module,
                    "build_issue56_production_semantic_handlers",
                    side_effect=build_once,
                ),
            ):
                with create_issue56_temporary_lan_query_service(
                    conversation_model,
                    behavior_log_path=behavior_log,
                    record_raw_uat_interactions=True,
                ) as query_service:
                    protected_server = create_mail_human_uat_http_server(
                        "127.0.0.1",
                        0,
                        query_service,
                        temporary_access_code=access_code,
                    )
                    thread = threading.Thread(
                        target=protected_server.serve_forever,
                        daemon=True,
                    )
                    thread.start()
                    try:
                        denied_responses = (
                            browser_request(protected_server, "GET", "/")[0],
                            browser_request(
                                protected_server,
                                "GET",
                                "/",
                                authorization=wrong_authorization,
                            )[0],
                            browser_request(
                                protected_server,
                                "POST",
                                "/api/chat",
                                prompt=prompt,
                            )[0],
                            browser_request(
                                protected_server,
                                "POST",
                                "/api/chat",
                                prompt=prompt,
                                authorization=wrong_authorization,
                            )[0],
                        )
                        self.assertEqual(query_service.request_count, 0)
                        self.assertFalse(behavior_log.exists())
                        page_response, page_body = browser_request(
                            protected_server,
                            "GET",
                            "/",
                            authorization=basic_authorization,
                        )
                        protected_set_cookie = page_response.getheader("Set-Cookie")
                        assert isinstance(protected_set_cookie, str)
                        protected_cookie = protected_set_cookie.split(";", 1)[0]
                        greeting_response, greeting_body = browser_request(
                            protected_server,
                            "POST",
                            "/api/chat",
                            prompt=greeting,
                            authorization=basic_authorization,
                            cookie=protected_cookie,
                        )
                        greeting_request_count = query_service.request_count
                    finally:
                        protected_server.shutdown()
                        protected_server.server_close()
                        thread.join(timeout=5)

                    server = create_mail_human_uat_http_server(
                        "127.0.0.1",
                        0,
                        query_service,
                    )
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        open_page_response, open_page_body = browser_request(
                            server,
                            "GET",
                            "/",
                        )
                        open_set_cookie = open_page_response.getheader("Set-Cookie")
                        assert isinstance(open_set_cookie, str)
                        open_cookie = open_set_cookie.split(";", 1)[0]
                        response, body = browser_request(
                            server,
                            "POST",
                            "/api/chat",
                            prompt=prompt,
                            cookie=open_cookie,
                        )
                        source_request_count = query_service.request_count
                    finally:
                        server.shutdown()
                        server.server_close()
                        thread.join(timeout=5)

                page = page_body.decode()
                open_page = open_page_body.decode()
                greeting_payload = json.loads(greeting_body)
                payload = json.loads(body)
                for denied in denied_responses:
                    self.assertEqual(denied.status, 401)
                    self.assertEqual(
                        denied.getheader("WWW-Authenticate"),
                        'Basic realm="FormOwl temporary UAT", charset="UTF-8"',
                    )
                self.assertEqual(page_response.status, 200)
                self.assertIn('data-authenticated="true"', page)
                self.assertIn('id="login-link" href="/auth/start" hidden', page)
                self.assertNotIn('id="chat-form" hidden', page)
                self.assertIn("formowl_uat_session=", protected_set_cookie)
                self.assertEqual(greeting_response.status, 200)
                self.assertIsNone(greeting_response.getheader("Set-Cookie"))
                self.assertEqual(greeting_payload["status"], "complete")
                self.assertTrue(greeting_payload["answer"])
                self.assertEqual(greeting_payload["citation_count"], 0)
                self.assertEqual(greeting_request_count, 0)
                self.assertEqual(open_page_response.status, 200)
                self.assertIn('data-authenticated="true"', open_page)
                self.assertIn("formowl_uat_session=", open_set_cookie)
                self.assertEqual(response.status, 200)
                self.assertIsNone(response.getheader("Set-Cookie"))
                self.assertIn(
                    payload["status"],
                    {"complete", "partial", "clarification_required"},
                )
                if payload["status"] == "clarification_required":
                    self.assertTrue(payload["clarification"])
                else:
                    self.assertTrue(payload["answer"])
                    self.assertIn(_VALUE, payload["answer"])
                self.assertGreater(payload["citation_count"], 0)
                self.assertGreaterEqual(source_request_count, 1)
                self.assertLessEqual(source_request_count, 3)
                mcp_trace = payload["diagnostic"]["mcp"]
                self.assertEqual(mcp_trace["call_count"], 1)
                self.assertFalse(mcp_trace["timeout"])
                self.assertNotIn("mcp_failed", mcp_trace["status"])
                self.assertEqual(len(handler_results), 1)
                self.assertIsInstance(handler_results[0], dict)
                self.assertNotEqual(prompt, standalone_query)
                assert_no_public_raw_references(
                    payload,
                    "issue56_temporary_lan_web_response",
                )
                self.assertEqual(loader_build_count, 1)

            self.assertEqual(loader_build_count, 1)
            model_close.assert_called_once_with()
            self.assertEqual(len(provider_requests), 3)
            self.assertEqual(
                provider_requests[0]["input"][-1]["content"],
                greeting,
            )
            self.assertEqual(provider_requests[0]["tools"], [])
            self.assertEqual(provider_requests[0]["tool_choice"], "none")
            self.assertEqual(
                provider_requests[1]["input"][-1]["content"],
                prompt,
            )
            self.assertEqual(
                provider_requests[1]["tool_choice"],
                {"type": "function", "name": "query_effective_graph_view"},
            )
            self.assertTrue(provider_requests[1]["tools"])
            # This sealed fixture deliberately returns replan_required after
            # the first MCP call, so the next evidence request must retain the
            # bounded FormOwl function choice rather than finalize with auto.
            second_request_tool_output = json.loads(provider_requests[2]["input"][-1]["output"])
            self.assertEqual(
                second_request_tool_output["data"]["status"],
                "replan_required",
            )
            self.assertEqual(
                provider_requests[2]["tool_choice"],
                {"type": "function", "name": "query_effective_graph_view"},
            )
            self.assertEqual(
                json.loads(provider_requests[2]["input"][-1]["output"])["trust"],
                "untrusted_evidence",
            )
            self.assertNotIn(
                provider_api_key,
                json.dumps(provider_requests, ensure_ascii=False),
            )
            self.assertEqual(len(handler_arguments), 1)
            for arguments in handler_arguments:
                self.assertEqual(arguments["query_text"], standalone_query)
                self.assertNotEqual(arguments["query_text"], prompt)
                self.assertEqual(
                    arguments["requester_user_id"],
                    sealed_source.APPROVER_ACTOR,
                )
                self.assertEqual(
                    arguments["workspace_id"],
                    sealed_source.WORKSPACE_ID,
                )
                self.assertNotIn("tenant_id", arguments)

            self.assertEqual(stat.S_IMODE(behavior_log.stat().st_mode), 0o600)
            log_lines = behavior_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(log_lines), 2)
            records = tuple(json.loads(line) for line in log_lines)
            for record, recorded_prompt, recorded_payload in zip(
                records,
                (greeting, prompt),
                (greeting_payload, payload),
                strict=True,
            ):
                self.assertEqual(
                    set(record),
                    {
                        "calls",
                        "elapsed_ms",
                        "failure_sha256",
                        "mcp_statuses",
                        "prompt",
                        "provider_diagnostic",
                        "request_count",
                        "result",
                        "timestamp",
                    },
                )
                self.assertEqual(record["prompt"], recorded_prompt)
                self.assertEqual(
                    record["result"],
                    {
                        key: recorded_payload.get(key)
                        for key in ("status", "answer", "clarification", "citations")
                    },
                )
                self.assertEqual(
                    set(record["result"]),
                    {"answer", "citations", "clarification", "status"},
                )
                self.assertEqual(record["request_count"], len(record["mcp_statuses"]))
                self.assertIsNone(record["failure_sha256"])
                provider_diagnostic = record["provider_diagnostic"]
                self.assertIsInstance(provider_diagnostic, dict)
                mcp_diagnostic = provider_diagnostic["mcp"]
                self.assertEqual(
                    mcp_diagnostic["call_count"],
                    record["request_count"],
                )
                self.assertFalse(mcp_diagnostic["timeout"])
                self.assertNotIn("mcp_failed", mcp_diagnostic["status"])
                assert_no_public_raw_references(
                    record,
                    "issue56_temporary_lan_behavior_log",
                )
            self.assertEqual(records[0]["calls"], [])
            self.assertEqual(len(records[1]["calls"]), 1)
            self.assertEqual(
                records[1]["calls"][0]["query_text"],
                standalone_query,
            )
            rendered_log = json.dumps(records, ensure_ascii=False).casefold()
            for forbidden in (
                "synthetic-provider-key-never-public",
                provider_api_key,
                access_code.casefold(),
                basic_authorization.casefold(),
                "authorization",
                "bearer",
                "cookie",
                "formowl-uat",
                "object_uri",
                "session_id",
                "tenant_id",
                str(root).casefold(),
                "/tmp/",
                "/workspace/",
            ):
                self.assertNotIn(forbidden, rendered_log)

    def test_no_auth_browser_cookie_isolates_and_reuses_cited_partial_evidence(
        self,
    ) -> None:
        prompt = "嘉值交期"
        reformat_prompt = "把剛才查到的結果整理成表格"
        failure_prompt = "查詢授權來源中的不存在追蹤項目"
        expanded_queries = (
            "查詢授權來源中 Record Key ENTITY-ALPHA-17 的 Measurement Band",
            "查詢授權來源中 Record Key ENTITY-BETA-18 的 Measurement Band",
        )
        failing_query = "查詢授權來源中的不存在追蹤項目"
        field = "Measurement Band"
        citations = ("citation-row-alpha", "citation-row-beta")
        lineages = ("lineage-row-alpha", "lineage-row-beta")
        values = ("12-14", "15-17")
        items = tuple(
            {
                "item_hash": f"item-row-{suffix}",
                "structure_status": "source_provided",
                "structured_values": [
                    {
                        "field": field,
                        "value": value,
                        "citation_hash": citation,
                        "occurrence_lineage_fingerprint": lineage,
                    }
                ],
                "governed_references": [
                    {
                        "citation_hash": citation,
                        "occurrence_lineage_fingerprint": lineage,
                    }
                ],
            }
            for suffix, value, citation, lineage in zip(
                ("alpha", "beta"),
                values,
                citations,
                lineages,
                strict=True,
            )
        )
        retained_items = (
            items[0],
            *(
                {
                    **items[0],
                    "item_hash": f"item-row-retained-{index}",
                }
                for index in range(7)
            ),
        )
        validation_statuses = (
            "validated_existing_scope_schema_permission",
            "rejected_existing_validator",
        )
        payloads = tuple(
            {
                "status": "complete" if index == 0 else "replan_required",
                "citations": [citations[index]],
                "coverage": {
                    "status": "complete" if index == 0 else "incomplete",
                    "coverage_status": "complete" if index == 0 else "incomplete",
                    "candidate_status": "candidate_interpretation",
                },
                "answer": {
                    "status": "candidate_interpretation",
                    "text": f"{field}: {values[index]}",
                },
                "source_structure_statuses": ["source_provided"],
                "exact_inventory": {
                    "status": "complete" if index == 0 else "partial",
                    "coverage_status": "complete" if index == 0 else "incomplete",
                    "returned_count": len(retained_items) if index == 0 else 1,
                    "items": list(retained_items if index == 0 else (items[index],)),
                },
                "query_agent": {
                    "status": "complete" if index == 0 else "replan_required",
                    "external_replan": {"status": "required"},
                    "context_bundle": {
                        "coverage_status": "complete" if index == 0 else "incomplete",
                        "candidate_status": "candidate_interpretation",
                        "selected_evidence": [items[index]],
                    },
                    "subqueries": [
                        {
                            "validation_status": validation_statuses[index],
                            "coverage_status": ("incomplete" if index == 0 else "not_executed"),
                            "rejection_fingerprint": (
                                None if index == 0 else "sha256:rejected-plan"
                            ),
                        }
                    ],
                },
            }
            for index in range(2)
        )
        payloads[1].pop("answer")
        payloads[1].pop("exact_inventory")
        handler_arguments: list[dict[str, object]] = []

        def retrieval_handler(arguments):
            handler_arguments.append(dict(arguments))
            if arguments.get("query_text") == failing_query:
                raise RuntimeError("synthetic retrieval failure")
            return payloads[expanded_queries.index(arguments["query_text"])]

        _with_authorized_source_families(retrieval_handler, "mail")

        class RecordingConversationModel:
            model_name = "recording-conversation-model"

            def __init__(self) -> None:
                self.calls = []

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
                del formowl_tool_descriptor, authorized_capability_summary
                self.calls.append(
                    {
                        "history": tuple(history),
                        "user_text": user_text,
                        "latest_evidence": latest_evidence,
                        "safety_identifier": safety_identifier,
                    }
                )
                if user_text == prompt:
                    requests = tuple(
                        UatEvidenceToolRequest(query_text=query_text)
                        for query_text in expanded_queries
                    )
                    evidence_results = tuple(evidence_tool(request) for request in requests)
                    return UatConversationOutcome(
                        response_kind="answer",
                        answer_text=(
                            f"{field}: {values[0]} [{citations[0]}]; "
                            f"{field}: {values[1]} [{citations[1]}]\n" + ("補充" * 4_000)
                        ),
                        display_format="narrative",
                        model_name=self.model_name,
                        citation_ids=citations,
                        coverage_status="incomplete",
                        coverage_note="授權來源仍有一筆未解析記錄。",
                        tool_requests=requests,
                        tool_results=evidence_results,
                    )
                if user_text == reformat_prompt and latest_evidence is not None:
                    return UatConversationOutcome(
                        response_kind="answer",
                        answer_text=(
                            f"| {field} | 引用 |\n|---|---|\n"
                            f"| {values[0]} | {citations[0]} |\n"
                            f"| {values[1]} | {citations[1]} |"
                        ),
                        display_format="table",
                        model_name=self.model_name,
                        citation_ids=citations,
                        coverage_status="incomplete",
                        coverage_note="授權來源仍有一筆未解析記錄。",
                    )
                if user_text == failure_prompt:
                    evidence_tool(UatEvidenceToolRequest(query_text=failing_query))
                    raise RuntimeError("synthetic conversation failure")
                return UatConversationOutcome(
                    response_kind="clarification",
                    answer_text="目前沒有可綁定的先前查詢結果。",
                    display_format="narrative",
                    model_name=self.model_name,
                    coverage_status="not_applicable",
                )

            def discard_conversation(self, safety_identifier) -> None:
                del safety_identifier

            def close(self) -> None:
                return

        conversation_model = RecordingConversationModel()

        with tempfile.TemporaryDirectory() as temporary_directory:
            behavior_log = Path(temporary_directory) / "conversation-trace.jsonl"
            with (
                patch.object(
                    uat_runtime_module,
                    "build_issue56_production_semantic_handlers",
                    return_value=(retrieval_handler, None),
                ),
                create_issue56_temporary_lan_query_service(
                    conversation_model,
                    behavior_log_path=behavior_log,
                    record_raw_uat_interactions=True,
                ) as query_service,
            ):
                server = create_mail_human_uat_http_server(
                    "127.0.0.1",
                    0,
                    query_service,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def request(*, prompt_text=None, cookie=None):
                    body = (
                        json.dumps({"prompt": prompt_text}, ensure_ascii=False).encode()
                        if prompt_text is not None
                        else None
                    )
                    headers = {}
                    if body is not None:
                        headers.update(
                            {
                                "Content-Type": "application/json",
                                "Content-Length": str(len(body)),
                                "Origin": (
                                    f"http://{server.server_address[0]}:"
                                    f"{server.server_address[1]}"
                                ),
                            }
                        )
                    if cookie is not None:
                        headers["Cookie"] = cookie
                    connection = http.client.HTTPConnection(*server.server_address, timeout=10)
                    try:
                        connection.request(
                            "POST" if body is not None else "GET",
                            "/api/chat" if body is not None else "/",
                            body=body,
                            headers=headers,
                        )
                        response = connection.getresponse()
                        return response, response.read()
                    finally:
                        connection.close()

                try:
                    first_page, first_page_body = request()
                    first_set_cookie = first_page.getheader("Set-Cookie")
                    assert isinstance(first_set_cookie, str)
                    first_cookie = first_set_cookie.split(";", 1)[0]
                    first_response, first_body = request(
                        prompt_text=prompt,
                        cookie=first_cookie,
                    )
                    reformat_response, reformat_body = request(
                        prompt_text=reformat_prompt,
                        cookie=first_cookie,
                    )

                    second_page, _second_page_body = request()
                    second_set_cookie = second_page.getheader("Set-Cookie")
                    assert isinstance(second_set_cookie, str)
                    second_cookie = second_set_cookie.split(";", 1)[0]
                    unbound_response, unbound_body = request(
                        prompt_text=reformat_prompt,
                        cookie=second_cookie,
                    )
                    failure_response, failure_body = request(
                        prompt_text=failure_prompt,
                        cookie=first_cookie,
                    )
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

            first_payload = json.loads(first_body)
            reformat_payload = json.loads(reformat_body)
            unbound_payload = json.loads(unbound_body)
            failure_payload = json.loads(failure_body)
            records = tuple(
                json.loads(line) for line in behavior_log.read_text(encoding="utf-8").splitlines()
            )
            behavior_log_mode = stat.S_IMODE(behavior_log.stat().st_mode)

        self.assertEqual(first_page.status, 200)
        self.assertIn('data-authenticated="true"', first_page_body.decode())
        for required in (
            "formowl_uat_session=",
            "HttpOnly",
            "SameSite=Lax",
            "Path=/",
            "Max-Age=3600",
        ):
            self.assertIn(required, first_set_cookie)
        self.assertNotEqual(first_cookie, second_cookie)
        self.assertEqual(first_response.status, 200)
        self.assertEqual(first_payload["status"], "partial")
        self.assertEqual(first_payload["citations"], list(citations))
        self.assertEqual(reformat_response.status, 200)
        self.assertEqual(reformat_payload["status"], "partial")
        self.assertEqual(reformat_payload["citations"], list(citations))
        self.assertEqual(
            reformat_payload["clarification"],
            "授權來源仍有一筆未解析記錄。",
        )
        self.assertIn(f"| {field} |", reformat_payload["answer"])
        for payload, boundary in (
            (first_payload, "issue56_multi_row_replan_browser"),
            (reformat_payload, "issue56_prior_evidence_reformat_browser"),
        ):
            assert_no_public_raw_references(payload, boundary)
        self.assertEqual(unbound_response.status, 200)
        self.assertEqual(unbound_payload["status"], "clarification_required")
        self.assertEqual(unbound_payload["citation_count"], 0)
        self.assertEqual(failure_response.status, 500)
        self.assertEqual(failure_payload["error_code"], "query_failed")

        self.assertEqual(len(conversation_model.calls), 4)
        first_call, reformat_call, unbound_call, failure_call = conversation_model.calls
        self.assertEqual(first_call["history"], ())
        self.assertIsNone(first_call["latest_evidence"])
        self.assertEqual(len(reformat_call["history"]), 2)
        self.assertEqual(
            [message.role for message in reformat_call["history"]],
            ["user", "assistant"],
        )
        self.assertEqual(len(reformat_call["history"][1].content), 8_000)
        self.assertEqual(
            reformat_call["latest_evidence"]["citations"],
            list(citations),
        )
        self.assertEqual(
            reformat_call["latest_evidence"]["status"],
            "partial",
        )
        self.assertEqual(
            reformat_call["latest_evidence"]["coverage"],
            {"status": "incomplete", "coverage_status": "incomplete"},
        )
        retained_results = reformat_call["latest_evidence"]["results"]
        self.assertLessEqual(len(retained_results), 8)
        self.assertEqual(len(retained_results), 2)
        self.assertEqual(retained_results[0]["status"], payloads[0]["status"])
        self.assertEqual(retained_results[0]["citations"], payloads[0]["citations"])
        self.assertEqual(
            [item["item_hash"] for item in retained_results[0]["exact_inventory"]["items"]],
            [item["item_hash"] for item in retained_items],
        )
        self.assertEqual(retained_results[1]["status"], payloads[1]["status"])
        self.assertEqual(
            retained_results[1]["query_agent"]["context_bundle"],
            payloads[1]["query_agent"]["context_bundle"],
        )
        self.assertEqual(unbound_call["history"], ())
        self.assertIsNone(unbound_call["latest_evidence"])
        self.assertEqual(
            first_call["safety_identifier"],
            reformat_call["safety_identifier"],
        )
        self.assertEqual(
            first_call["safety_identifier"],
            failure_call["safety_identifier"],
        )
        self.assertNotEqual(
            first_call["safety_identifier"],
            unbound_call["safety_identifier"],
        )
        self.assertNotEqual(
            first_call["safety_identifier"],
            "issue56-temporary-lan",
        )

        self.assertEqual(
            [arguments["query_text"] for arguments in handler_arguments],
            [*expanded_queries, failing_query],
        )
        self.assertEqual(len(records), 4)
        first_trace = records[0]["calls"][0]
        self.assertEqual(first_trace["query_text"], expanded_queries[0])
        self.assertTrue(first_trace["query_hash"].startswith("sha256:"))
        self.assertEqual(first_trace["status"], "complete")
        self.assertEqual(first_trace["result_count"], len(retained_items))
        self.assertEqual(first_trace["citation_count"], 1)
        self.assertEqual(first_trace["item_count"], len(retained_items))
        self.assertEqual(
            first_trace["subqueries"],
            [
                {
                    "validation_status": ("validated_existing_scope_schema_permission"),
                    "coverage_status": "incomplete",
                    "rejection_sha256": None,
                },
            ],
        )
        self.assertGreaterEqual(first_trace["timings_ms"]["mcp_call"], 0)
        second_trace = records[0]["calls"][1]
        self.assertEqual(second_trace["query_text"], expanded_queries[1])
        self.assertEqual(
            second_trace["subqueries"],
            [
                {
                    "validation_status": "rejected_existing_validator",
                    "coverage_status": "not_executed",
                    "rejection_sha256": "sha256:rejected-plan",
                }
            ],
        )
        self.assertEqual(records[1]["calls"], [])
        self.assertEqual(records[2]["calls"], [])
        self.assertIsNotNone(records[3]["failure_sha256"])
        self.assertIsNotNone(records[3]["calls"][0]["failure_sha256"])
        self.assertEqual(behavior_log_mode, 0o600)
        rendered_log = json.dumps(records, ensure_ascii=False).casefold()
        for forbidden in (
            "synthetic retrieval failure",
            "synthetic conversation failure",
            "authorization",
            "bearer",
            "cookie",
            "session_id",
            "object_uri",
            "tenant_id",
            "/tmp/",
            "/workspace/",
        ):
            self.assertNotIn(forbidden, rendered_log)

    def test_safe_stop_retains_all_source_rows_without_claiming_answer_coverage(
        self,
    ) -> None:
        items = []
        citations = []
        for row_index in range(20):
            row_values = []
            for field_index in range(3):
                citation = f"citation-row-{row_index}-field-{field_index}"
                citations.append(citation)
                row_values.append(
                    {
                        "field": f"field-{field_index}",
                        "value": f"value-{row_index}-{field_index}",
                        "citation_hash": citation,
                    }
                )
            items.append(
                {
                    "item_hash": f"item-row-{row_index}",
                    "structure_status": "source_provided",
                    "structured_values": row_values,
                }
            )
        snippet_citation = "citation-readable-mail-snippet"
        citations.append(snippet_citation)
        evidence = {
            "status": "complete_authorized_scope",
            "coverage": {
                "status": "complete",
                "coverage_status": "complete",
            },
            "citations": citations,
            "exact_inventory": {
                "status": "complete",
                "coverage_status": "complete",
                "returned_count": len(items),
                "total_count": len(items),
                "items": items,
            },
            "query_agent": {
                "context_bundle": {
                    "successful_subqueries": [
                        {
                            "evidence": [
                                {
                                    "snippet": "可讀的授權郵件摘要",
                                    "citation_hash": snippet_citation,
                                }
                            ]
                        }
                    ]
                }
            },
        }
        safe_stop = UatConversationOutcome(
            response_kind="clarification",
            answer_text="Provider finalization stopped safely.",
            display_format="narrative",
            model_name="synthetic",
            coverage_status="incomplete",
            coverage_note="No answer claim was emitted.",
            tool_requests=(
                UatEvidenceToolRequest(
                    query_text="bounded authorized table lookup",
                ),
            ),
            tool_results=(evidence,),
        )

        small_items = [
            {
                **item,
                "structured_values": item["structured_values"][:1],
            }
            for item in items[:7]
        ]
        small_row_citations = [
            f"citation-row-{row_index}-field-0"
            for row_index in range(len(small_items))
        ]
        small_citations = [*small_row_citations, snippet_citation]
        small_evidence = {
            **evidence,
            "citations": small_citations,
            "exact_inventory": {
                **evidence["exact_inventory"],
                "returned_count": len(small_items),
                "total_count": len(small_items),
                "items": small_items,
            },
        }
        compact_small = uat_runtime_module.compact_evidence_for_model(
            small_evidence,
            item_limit=8,
        )
        self.assertNotIn("presentation_truncated", compact_small)
        self.assertEqual(
            compact_small["exact_inventory"]["items"],
            small_items,
        )
        self.assertEqual(compact_small["citations"], small_citations)

        compact_overflow = uat_runtime_module.compact_evidence_for_model(
            evidence,
            item_limit=8,
        )
        self.assertNotIn("exact_inventory", compact_overflow)
        self.assertTrue(compact_overflow["presentation_truncated"])
        self.assertEqual(compact_overflow["citations"], [])
        self.assertEqual(compact_overflow["coverage"], evidence["coverage"])
        self.assertTrue(
            uat_runtime_module._evidence_results_are_incomplete((compact_overflow,))
        )
        compact_context_evidence = (
            compact_overflow["query_agent"]["context_bundle"]["successful_subqueries"][0][
                "evidence"
            ][0]
        )
        self.assertEqual(compact_context_evidence["citation_hash"], snippet_citation)

        retained = _retained_authorized_evidence(safe_stop, (evidence,))

        self.assertIsNotNone(retained)
        self.assertEqual(len(retained["results"]), 1)
        retained_result = retained["results"][0]
        self.assertNotIn("exact_inventory", retained_result)
        self.assertTrue(retained_result["presentation_truncated"])
        retained_context_evidence = (
            retained_result["query_agent"]["context_bundle"]["successful_subqueries"][0][
                "evidence"
            ][0]
        )
        self.assertEqual(
            retained_context_evidence["snippet"],
            "可讀的授權郵件摘要",
        )
        self.assertEqual(
            retained_context_evidence["citation_hash"],
            snippet_citation,
        )
        self.assertEqual(retained["citations"], [snippet_citation])
        self.assertTrue(set(citations[:-1]).isdisjoint(retained["citations"]))
        self.assertLessEqual(len(retained["results"]), 8)
        self.assertEqual(retained["coverage"]["status"], "incomplete")
        self.assertTrue(
            uat_runtime_module._evidence_results_are_incomplete((retained_result,))
        )
        projected = _browser_projection(
            safe_stop,
            (evidence,),
            latest_evidence=None,
        )
        self.assertEqual(projected["status"], "partial")
        self.assertIn("field-0：value-0-0", projected["answer"])
        self.assertIn("[citation-row-0-field-0]", projected["answer"])
        self.assertIn("來源摘錄：可讀的授權郵件摘要", projected["answer"])
        self.assertNotIn("授權項目：", projected["answer"])
        self.assertEqual(set(projected["citations"]), set(citations))
        self.assertIn("未證明已完整涵蓋", projected["clarification"])
        self.assertIn("Provider finalization stopped safely.", projected["clarification"])
        assert_no_public_raw_references(
            retained,
            "issue56_safe_stop_retained_evidence",
        )
        assert_no_public_raw_references(
            projected,
            "issue56_safe_stop_projected_evidence",
        )

    def test_real_sealed_source_over_browser_and_normal_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch.object(
                sealed_fixture,
                "WORKSPACE_PERMISSION_SCOPE",
                _PERMISSION_SCOPE,
            ):
                package = _prepare_package(root / "sealed")
            supplemental_path, parent_path = _write_supplemental_partition(
                root,
                package,
            )
            prompt = f"可以幫忙查一下 {_IDENTIFIER} 對應的 {_HEADER} 嗎？"
            standalone_query = f"有{_IDENTIFIER}的{_HEADER}呢？"
            table_query = {
                "filters": [
                    {
                        "field": "PartNumber",
                        "value": _IDENTIFIER,
                    }
                ],
                "projection_fields": [_HEADER],
            }
            conversation_model = _RecordingGptQueryAgent(
                standalone_query=standalone_query,
                table_query=table_query,
            )
            environment = dict(__import__("os").environ)
            environment.update(_loader_environment(package))
            environment.update(
                {
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_PATH": str(
                        supplemental_path
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_SHA256": (
                        _sha256_path(supplemental_path)
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_PATH": str(parent_path),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_SHA256": (
                        _sha256_path(parent_path)
                    ),
                }
            )
            runtime_root = root / "runtime"
            runtime_root.mkdir()
            environment.update(_write_runtime_environment(runtime_root))
            environment["FORMOWL_ISSUE56_PRODUCTION_SEMANTIC_ENABLED"] = "1"
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                browser_port = reservation.getsockname()[1]
            public_base_url = f"http://127.0.0.1:{browser_port}"
            environment["FORMOWL_CHATGPT_REDIRECT_URI"] = f"{public_base_url}/auth/callback"
            environment["FORMOWL_ISSUE56_UAT_PUBLIC_BASE_URL"] = public_base_url
            repository = TransactionAwareMemoryRepository()
            repository.connection = _FakeConnection()
            runtime_repository = _FakeRepository()
            repository.health_check = runtime_repository.health_check
            repository.apply_migrations = runtime_repository.apply_migrations
            repository.close = runtime_repository.close
            oauth_email = "browser-uat@example.test"
            created_at = datetime.now(timezone.utc)
            with repository.transaction() as transaction:
                repository.insert_user(
                    User(
                        user_id=sealed_source.APPROVER_ACTOR,
                        display_name="Browser UAT owner",
                        email=oauth_email,
                        status="active",
                        created_at=created_at.isoformat(),
                    )
                )
                repository.insert_workspace_member(
                    WorkspaceMember(
                        workspace_id=sealed_source.WORKSPACE_ID,
                        user_id=sealed_source.APPROVER_ACTOR,
                        role="owner",
                    ),
                    created_at=created_at.isoformat(),
                )
                repository.insert_invitation(
                    OAuthInvitation(
                        invitation_id="invite_issue56_browser_uat",
                        normalized_email=normalize_verified_email(oauth_email),
                        workspace_id=sealed_source.WORKSPACE_ID,
                        role="owner",
                        status="pending",
                        expires_at=(created_at + timedelta(hours=1)).isoformat(),
                        created_at=created_at.isoformat(),
                        intended_user_id=sealed_source.APPROVER_ACTOR,
                    )
                )
                transaction.commit()
            with (
                patch.dict(__import__("os").environ, environment, clear=True),
                patch.object(
                    runtime_module.PostgreSQLOAuthRepository,
                    "connect",
                    return_value=repository,
                ),
            ):
                config = ConnectedRuntimeConfig.from_env_and_secrets(environment)
                runtime = asyncio.run(
                    ConnectedRuntime.compose(
                        config,
                        http_client=_FakeHttpClient(),
                    )
                )
            google = StubGoogleClient(
                GoogleIdentity(
                    issuer="https://accounts.google.com",
                    subject="browser-uat-google-subject",
                    email=oauth_email,
                    email_verified=True,
                    display_name="Browser UAT owner",
                )
            )
            with (
                patch.object(
                    runtime.google_client,
                    "build_authorization_url",
                    side_effect=google.build_authorization_url,
                ),
                patch.object(
                    runtime.google_client,
                    "authenticate_code",
                    side_effect=google.authenticate_code,
                ),
                Issue56UatQueryService(
                    runtime,
                    public_base_url=public_base_url,
                    conversation_model=conversation_model,
                ) as query_service,
            ):
                server = create_mail_human_uat_http_server(
                    "127.0.0.1",
                    browser_port,
                    query_service,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    body = json.dumps({"prompt": prompt}, ensure_ascii=False).encode()
                    origin = f"http://{server.server_address[0]}:" f"{server.server_address[1]}"
                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "POST",
                        "/api/chat",
                        body=body,
                        headers={
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                            "Origin": origin,
                        },
                    )
                    unauthenticated = connection.getresponse()
                    unauthenticated_payload = json.loads(unauthenticated.read())
                    connection.close()

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request("GET", "/")
                    page_response = connection.getresponse()
                    page = page_response.read().decode("utf-8")
                    connection.close()
                    self.assertEqual(page_response.status, 200)
                    self.assertIn('id="login-link"', page)
                    self.assertIn('data-authenticated="false"', page)

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request("GET", "/auth/start")
                    start_response = connection.getresponse()
                    start_response.read()
                    authorization_url = urlparse(start_response.getheader("Location"))
                    pre_auth_set_cookie = start_response.getheader("Set-Cookie")
                    connection.close()
                    authorization_parameters = parse_qs(authorization_url.query)
                    self.assertEqual(start_response.status, 302)
                    self.assertEqual(
                        f"{authorization_url.scheme}://"
                        f"{authorization_url.netloc}{authorization_url.path}",
                        config.oauth.authorization_endpoint,
                    )
                    self.assertEqual(
                        authorization_parameters["code_challenge_method"],
                        ["S256"],
                    )
                    self.assertNotIn("code_verifier", authorization_parameters)
                    self.assertIsInstance(pre_auth_set_cookie, str)
                    assert isinstance(pre_auth_set_cookie, str)
                    for required in (
                        "formowl_uat_pre_auth=",
                        "HttpOnly",
                        "SameSite=Lax",
                        "Path=/",
                    ):
                        self.assertIn(required, pre_auth_set_cookie)
                    pre_auth_cookie = pre_auth_set_cookie.split(";", 1)[0]

                    authorize_response = query_service._client.get(
                        authorization_url.path + "?" + authorization_url.query,
                        follow_redirects=False,
                    )
                    self.assertEqual(authorize_response.status_code, 302)
                    google_state = parse_qs(urlparse(authorize_response.headers["location"]).query)[
                        "state"
                    ][0]
                    callback_response = query_service._client.get(
                        "/oauth/google/callback",
                        params={
                            "state": google_state,
                            "code": "google-browser-uat-code",
                        },
                        follow_redirects=False,
                    )
                    self.assertEqual(callback_response.status_code, 302)
                    browser_callback = urlparse(callback_response.headers["location"])
                    self.assertEqual(
                        f"{browser_callback.scheme}://{browser_callback.netloc}"
                        f"{browser_callback.path}",
                        f"{public_base_url}/auth/callback",
                    )

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "GET",
                        browser_callback.path + "?" + browser_callback.query,
                    )
                    missing_cookie_response = connection.getresponse()
                    missing_cookie_response.read()
                    connection.close()

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "GET",
                        browser_callback.path + "?" + browser_callback.query,
                        headers={"Cookie": "formowl_uat_pre_auth=wrong-browser"},
                    )
                    wrong_browser_response = connection.getresponse()
                    wrong_browser_response.read()
                    connection.close()

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "GET",
                        browser_callback.path + "?" + browser_callback.query,
                        headers={"Cookie": pre_auth_cookie},
                    )
                    login_response = connection.getresponse()
                    login_response.read()
                    set_cookies = [
                        value
                        for name, value in login_response.getheaders()
                        if name.casefold() == "set-cookie"
                    ]
                    connection.close()
                    self.assertEqual(missing_cookie_response.status, 400)
                    self.assertEqual(wrong_browser_response.status, 400)
                    self.assertIsNone(missing_cookie_response.getheader("Set-Cookie"))
                    self.assertIsNone(wrong_browser_response.getheader("Set-Cookie"))
                    self.assertEqual(login_response.status, 303)
                    self.assertEqual(len(set_cookies), 2)
                    self.assertTrue(
                        any(
                            "formowl_uat_pre_auth=" in value and "Max-Age=0" in value
                            for value in set_cookies
                        )
                    )
                    session_set_cookie = next(
                        value for value in set_cookies if value.startswith("formowl_uat_session=")
                    )
                    for required in (
                        "HttpOnly",
                        "SameSite=Lax",
                        "Path=/",
                        f"Max-Age={config.oauth.access_token_lifetime_seconds}",
                    ):
                        self.assertIn(required, session_set_cookie)
                    for forbidden in ("access_token", "code_verifier", "tenant_id"):
                        self.assertNotIn(forbidden, repr(set_cookies))
                    session_cookie = session_set_cookie.split(";", 1)[0]

                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "POST",
                        "/api/chat",
                        body=body,
                        headers={
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                            "Origin": origin,
                            "Cookie": session_cookie,
                        },
                    )
                    response = connection.getresponse()
                    payload = json.loads(response.read())
                    connection.close()
                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "GET",
                        "/api/transcript",
                        headers={"Cookie": session_cookie},
                    )
                    transcript_response = connection.getresponse()
                    transcript_payload = json.loads(transcript_response.read())
                    connection.close()
                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "GET",
                        "/",
                        headers={"Cookie": session_cookie},
                    )
                    reload_response = connection.getresponse()
                    reload_page = reload_response.read().decode("utf-8")
                    connection.close()
                    connection = http.client.HTTPConnection(
                        *server.server_address,
                        timeout=30,
                    )
                    connection.request(
                        "GET",
                        "/api/transcript",
                        headers={"Cookie": session_cookie},
                    )
                    reload_transcript_response = connection.getresponse()
                    reload_transcript_payload = json.loads(reload_transcript_response.read())
                    connection.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

                self.assertEqual(unauthenticated.status, 401)
                self.assertEqual(
                    unauthenticated_payload["error_code"],
                    "auth_required",
                )
                self.assertEqual(response.status, 200)
                self.assertIn(payload["status"], {"complete", "partial"})
                self.assertGreaterEqual(query_service.request_count, 1)
                self.assertLessEqual(query_service.request_count, 3)
                self.assertNotIn("mcp_failed", query_service.last_mcp_statuses)
                self.assertEqual(
                    conversation_model.tool_queries,
                    [standalone_query],
                )
                self.assertEqual(
                    conversation_model.tool_table_queries,
                    [table_query],
                )
                self.assertNotEqual(prompt, standalone_query)
                self.assertTrue(payload["answer"])
                self.assertIn(_VALUE, payload["answer"])
                self.assertGreater(payload["citation_count"], 0)
                self.assertEqual(transcript_response.status, 200)
                self.assertEqual(transcript_payload["turn_count"], 1)
                self.assertEqual(
                    transcript_payload["turns"][0]["response"]["citations"],
                    payload["citations"],
                )
                self.assertEqual(reload_response.status, 200)
                self.assertIn('data-authenticated="true"', reload_page)
                self.assertEqual(reload_transcript_response.status, 200)
                self.assertEqual(
                    reload_transcript_payload,
                    transcript_payload,
                )
                assert_no_public_raw_references(payload, "issue56_uat_web_response")
                rendered = json.dumps(payload, ensure_ascii=False).lower()
                for forbidden in (
                    "object_uri",
                    "tenant_id",
                    "/tmp/",
                    "/workspace/",
                ):
                    self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
