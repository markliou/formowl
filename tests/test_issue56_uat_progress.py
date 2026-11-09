import json
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import _paths  # noqa: F401
from formowl_gateway import issue56_uat_runtime as runtime
from formowl_mail.human_uat_orchestrator import UatConversationOutcome, UatEvidenceToolRequest


class UatProgressTests(unittest.TestCase):
    def service(self, authenticated=False):
        cls = runtime.Issue56UatQueryService if authenticated else runtime.Issue56TemporaryLanQueryService
        service = object.__new__(cls)
        service._lock, service._query_lock = threading.RLock(), threading.Lock()
        states = {key: runtime._ConversationState(expires_at=time.monotonic()+60) for key in ("one", "two")}
        service._sessions = ({key: ("private-bearer", state, state.expires_at) for key, state in states.items()}
                             if authenticated else states)
        service._pending = {}
        service._conversation_model = SimpleNamespace(discard_conversation=Mock())
        service._application = object()
        service._provider_tool_catalog = ()
        service._behavior_log_path = None
        service._source_binding_fingerprint = None
        service._active_turn_deadline = None
        return service

    def test_session_isolation_expiry_and_elapsed_terminal_snapshot(self):
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                service = self.service(authenticated)
                self.assertEqual(service.read_browser_progress("two")["phase"], "idle")
                with self.assertRaises(PermissionError):
                    service.read_browser_progress("unknown")
                state = service._sessions["one"][1] if authenticated else service._sessions["one"]
                with patch.object(runtime.time, "monotonic", return_value=100.2):
                    progress = runtime._start_turn_progress(state)
                runtime._update_turn_progress(progress, "querying", query_count=2)
                runtime._update_turn_progress(progress, "records", counts=(42, 7))
                runtime._update_turn_progress(progress, "model")
                with patch.object(runtime.time, "monotonic", return_value=105.9):
                    snapshot = runtime._progress_projection(state)
                self.assertEqual(set(snapshot), {"phase", "detail", "elapsed_seconds", "deadline_seconds"})
                self.assertEqual(snapshot["elapsed_seconds"], 5)
                self.assertEqual(snapshot["deadline_seconds"], int(runtime._MAX_UAT_TURN_SECONDS))
                self.assertIn("42 筆／7 組", snapshot["detail"])
                with patch.object(runtime.time, "monotonic", return_value=108.9):
                    runtime._update_turn_progress(progress, "complete")
                with patch.object(runtime.time, "monotonic", return_value=200):
                    self.assertEqual(runtime._progress_projection(state)["elapsed_seconds"], 8)
                replacement = runtime._start_turn_progress(state)
                runtime._update_turn_progress(progress, "records", counts=(999, 999))
                self.assertIs(state.progress, replacement)
                self.assertNotIn("999", service.read_browser_progress("one")["detail"])
                if authenticated:
                    bearer, state, _ = service._sessions["two"]
                    service._sessions["two"] = bearer, state, time.monotonic()-1
                else:
                    service._sessions["two"].expires_at = time.monotonic()-1
                with self.assertRaises(PermissionError):
                    service.read_browser_progress("two")

    def test_only_public_vetted_integer_counts_reach_progress(self):
        def data(total, groups):
            return {"status": "partial", "evidence": [{"source_type": "candidate_fact_table",
                "snippet": "private-label\n" + json.dumps({"total": total,
                    "result_set": {"total_groups": groups}, "rows": ["private-value /private/path"]})}]}
        self.assertEqual(runtime._progress_record_counts(data(42, 7)), (42, 7))
        for total, groups in ((True, 7), (-1, 7), ("42", 7), (42, False), (42, 2**54)):
            self.assertIsNone(runtime._progress_record_counts(data(total, groups)))
        self.assertIsNone(runtime._progress_record_counts({**data(42, 7), "status": "permission_denied"}))
        self.assertEqual(runtime._progress_record_counts({"coverage": {"record_identifier_lookup": "no_matches"}}), (0, 0))
        self.assertIsNone(runtime._progress_record_counts({"evidence": None}))
        self.assertIsNone(runtime._progress_record_counts({"evidence": [{"source_type": "candidate_fact_table", "snippet": "bad"}]}))

    def test_real_agent_hooks_accept_sidecar_thread_callbacks_and_bound_deadline(self):
        state = runtime._ConversationState(expires_at=time.monotonic()+60)
        progress = runtime._start_turn_progress(state)
        seen, errors = [], []
        prompt = "Find evidence about the synthetic milestone"
        request = UatEvidenceToolRequest(query_text=prompt, required_terms=("synthetic",))
        outcome = UatConversationOutcome(response_kind="answer", answer_text="Synthetic answer",
            display_format="narrative", model_name="synthetic")

        def update(phase, **values):
            runtime._update_turn_progress(progress, phase, **values)
            seen.append(runtime._progress_projection(state))

        def respond(*, evidence_tool, **kwargs):
            self.assertEqual(runtime._BROWSER_TURN_DEADLINE.get(), 12345.0)
            def sidecar():
                try:
                    evidence_tool(request)
                    evidence_tool(request)
                except BaseException as exc:
                    errors.append(exc)
            thread = threading.Thread(target=sidecar)
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            return outcome

        data = {"status": "partial", "citations": [], "evidence": [{"source_type": "candidate_fact_table",
            "snippet": "label\n" + json.dumps({"total": 42, "result_set": {"total_groups": 7}})}]}
        with patch.object(runtime, "_browser_projection", return_value={}), \
                patch.object(runtime, "_emit_private_uat_terminal_trace"):
            runtime._run_gpt_query_agent(SimpleNamespace(respond=respond), prompt=prompt, history=(),
                latest_evidence=None, safety_identifier="synthetic", formowl_tool_descriptor=None,
                authorized_capability_summary={"source_families": ["mail", "document_text"]},
                mcp_call=lambda request: data, progress=update, deadline_monotonic=12345.0)
        self.assertEqual(errors, [])
        self.assertEqual([s["phase"] for s in seen],
                         ["model", "querying", "records", "model", "querying", "records", "model", "validating"])
        self.assertIn("第 2 次查詢", seen[4]["detail"])
        self.assertEqual(seen[0]["detail"], "模型處理中")
        self.assertIn("模型整理答案中", seen[3]["detail"])
        self.assertIn("42 筆／7 組", seen[-1]["detail"])
        self.assertIsNone(runtime._BROWSER_TURN_DEADLINE.get())

    def test_active_turn_reads_busy_reset_and_logout_do_not_wait_for_model(self):
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                service = self.service(authenticated)
                entered, release = threading.Event(), threading.Event()
                result = {"status": "ok", "answer": "Synthetic answer", "citations": [], "clarification": None}
                outcome = UatConversationOutcome(response_kind="answer", answer_text="Synthetic answer",
                    display_format="narrative", model_name="synthetic")
                errors = []

                def agent(*args, progress, deadline_monotonic, **kwargs):
                    self.assertLessEqual(deadline_monotonic, time.monotonic()+runtime._MAX_UAT_TURN_SECONDS)
                    progress("model")
                    progress("querying", query_count=1)
                    progress("records", counts=(42, 7))
                    progress("model")
                    entered.set()
                    release.wait(2)
                    progress("validating")
                    return result, (), outcome

                def ask():
                    try:
                        service.ask("Synthetic question", session_id="one")
                    except BaseException as exc:
                        errors.append(exc)

                with patch.object(runtime, "_query_agent_runtime_context", return_value=(None, {})), \
                        patch.object(runtime, "_run_gpt_query_agent", side_effect=agent), \
                        patch.object(runtime, "_emit_private_uat_terminal_trace"), \
                        patch.object(runtime, "_advance_conversation_state"):
                    thread = threading.Thread(target=ask)
                    thread.start()
                    try:
                        self.assertTrue(entered.wait(1))
                        before = time.monotonic()
                        snapshot = service.read_browser_progress("one")
                        self.assertLess(time.monotonic()-before, .2)
                        self.assertEqual(snapshot["phase"], "model")
                        self.assertIn("42 筆／7 組", snapshot["detail"])
                        self.assertEqual(service.read_browser_progress("two")["phase"], "idle")
                        if not authenticated:
                            self.assertEqual(service.ask("Busy turn", session_id="one")["status"], "error")
                            self.assertEqual(service.read_browser_progress("one")["phase"], "model")
                            service.ask("Busy turn", session_id="two")
                            self.assertEqual(service.read_browser_progress("two")["phase"], "failed")
                        new_session, _ = service.reset_browser_conversation("one")
                        self.assertEqual(service.read_browser_progress(new_session)["phase"], "idle")
                        with self.assertRaises(PermissionError):
                            service.read_browser_progress("one")
                        service.logout_browser_session("two")
                        with self.assertRaises(PermissionError):
                            service.read_browser_progress("two")
                    finally:
                        release.set()
                        thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(service.read_browser_progress(new_session)["phase"], "idle")

    def test_failed_turn_uses_fixed_terminal_detail_and_restores_deadline_context(self):
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                service = self.service(authenticated)
                with patch.object(runtime, "_query_agent_runtime_context", return_value=(None, {})), \
                        patch.object(runtime, "_run_gpt_query_agent", side_effect=TimeoutError("private failure")), \
                        patch.object(runtime, "_emit_private_uat_failure_trace"), \
                        patch.object(runtime, "_emit_private_uat_terminal_trace"):
                    with self.assertRaises(TimeoutError):
                        service.ask("private prompt", session_id="one")
                snapshot = service.read_browser_progress("one")
                self.assertEqual(snapshot["phase"], "failed")
                self.assertNotIn("private", json.dumps(snapshot))

    def test_successful_services_publish_complete_after_validation(self):
        result = {"status": "ok", "answer": "Synthetic answer", "citations": [], "clarification": None}
        outcome = UatConversationOutcome(response_kind="answer", answer_text="Synthetic answer",
            display_format="narrative", model_name="synthetic")
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                service = self.service(authenticated)
                def validate(value):
                    self.assertEqual(service.read_browser_progress("one")["phase"], "validating")
                with patch.object(runtime, "_query_agent_runtime_context", return_value=(None, {})), \
                        patch.object(runtime, "_run_gpt_query_agent", return_value=(result, (), outcome)), \
                        patch.object(runtime, "validate_public_gateway_payload", side_effect=validate), \
                        patch.object(runtime, "_emit_private_uat_terminal_trace"), \
                        patch.object(runtime, "_advance_conversation_state"):
                    actual = service.ask("Synthetic question", session_id="one")
                    self.assertEqual({key: actual[key] for key in result}, result)
                self.assertEqual(service.read_browser_progress("one")["phase"], "complete")

    def test_respond_failure_restores_outer_absolute_deadline(self):
        token = runtime._BROWSER_TURN_DEADLINE.set(54321.0)
        try:
            model = SimpleNamespace(respond=Mock(side_effect=TimeoutError("synthetic")))
            with self.assertRaises(TimeoutError):
                runtime._run_gpt_query_agent(model, prompt="Synthetic question", history=(),
                    latest_evidence=None, safety_identifier="synthetic", formowl_tool_descriptor=None,
                    authorized_capability_summary=None, mcp_call=Mock(), deadline_monotonic=12345.0)
            self.assertEqual(runtime._BROWSER_TURN_DEADLINE.get(), 54321.0)
        finally:
            runtime._BROWSER_TURN_DEADLINE.reset(token)


if __name__ == "__main__":
    unittest.main()
