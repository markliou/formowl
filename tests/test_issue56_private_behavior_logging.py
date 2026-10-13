from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import stat
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import _paths  # noqa: F401
from formowl_contract import sha256_json
import formowl_gateway.issue56_uat_runtime as runtime
import formowl_mail.human_uat_orchestrator as orchestrator


class PrivateBehaviorLoggingTests(unittest.TestCase):
    def service(self, path=None):
        service = object.__new__(runtime.Issue56TemporaryLanQueryService)
        service._application = object()
        service._conversation_model = SimpleNamespace(discard_conversation=MagicMock())
        service._lock = threading.RLock()
        service._query_lock = threading.Lock()
        service._sessions = {"synthetic-session": runtime._ConversationState(
            expires_at=runtime.time.monotonic() + 60,
        )}
        service._behavior_log_path = path
        service._record_raw_uat_interactions = path is not None
        service._source_binding_fingerprint = None
        service.last_failure_class = None
        return service

    def ask(self, service, *, run=None, prompt="PRIVATE-PROMPT"):
        outcome = orchestrator.UatConversationOutcome(
            response_kind="answer", answer_text="PRIVATE-ANSWER",
            display_format="narrative", model_name="synthetic",
        )
        with (
            patch.object(runtime, "_query_agent_runtime_context", return_value=(None, None)),
            patch.object(runtime, "_run_gpt_query_agent", side_effect=run) if run else
            patch.object(runtime, "_run_gpt_query_agent", return_value=(
                {"status": "ok", "answer": "PRIVATE-ANSWER", "citations": [],
                 "clarification": None}, (), outcome,
            )),
        ):
            return service.ask(prompt, session_id="synthetic-session")

    def test_enabled_duplicate_chat_preserves_visible_result_and_correlates_safe_terminal(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as stderr:
            path = Path(directory) / "private.jsonl"
            service = self.service(path)
            answers = [self.ask(service), self.ask(service)]
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(records), 2)
            self.assertNotEqual(records[0]["request_id"], records[1]["request_id"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            terminals = [json.loads(line) for line in stderr.getvalue().splitlines()]
            for record, answer, terminal in zip(records, answers, terminals, strict=True):
                self.assertEqual(record["result"], {key: answer.get(key) for key in (
                    "status", "answer", "clarification", "citations",
                )})
                self.assertEqual(record["request_count"], 0)
                self.assertEqual(record["calls"], [])
                self.assertEqual(record["request_id"], terminal["request_id"])
                self.assertEqual(record["prompt"], "PRIVATE-PROMPT")
            for private in ("PRIVATE-PROMPT", "PRIVATE-ANSWER", "synthetic-session"):
                self.assertNotIn(private, stderr.getvalue())
            self.assertIsNone(orchestrator._PRIVATE_UAT_CITATION_TRACE.get())

    def test_disabled_logging_collects_no_private_stages_and_preserves_chat(self):
        with redirect_stderr(io.StringIO()):
            with patch.object(runtime, "_append_behavior_log") as append:
                self.assertEqual(self.ask(self.service())["answer"], "PRIVATE-ANSWER")
                append.assert_not_called()
        self.assertIsNone(orchestrator._PRIVATE_UAT_CITATION_TRACE.get())

    def test_actual_chat_route_correlates_provider_turn_and_file(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as stderr:
            path = Path(directory) / "private.jsonl"
            service = self.service(path)
            service._conversation_model.respond = MagicMock(return_value=orchestrator.UatConversationOutcome(
                response_kind="answer", answer_text="ordinary answer",
                display_format="narrative", model_name="synthetic",
            ))
            with patch.object(runtime, "_query_agent_runtime_context", return_value=(None, None)):
                answer = service.ask("hello", session_id="synthetic-session")
            self.assertEqual(answer["answer"], "ordinary answer")
            record = json.loads(path.read_text())
            events = [json.loads(line) for line in stderr.getvalue().splitlines()]
            self.assertEqual(len(events), 2)
            self.assertEqual([event["request_id"] for event in events], [record["request_id"]] * 2)
            self.assertEqual(record["request_count"], 0)

    def test_pool_membership_capture_is_private_and_final_answer_is_explicit(self):
        first, second = "sha256:" + "a" * 64, "sha256:" + "b" * 64
        raw = {"status": "partial", "citations": [first, second]}
        presented = {"status": "partial", "citations": [second]}
        public = []

        def run(*args, **kwargs):
            public.append(orchestrator._mcp_citation_stage_diagnostic(
                call_index=1, elapsed_ms=1, raw_result=raw, presented_result=presented,
                projection_result="reduced",
            ))
            public.append(orchestrator._finalization_validation_diagnostic(
                final_citation_ids=[second], available_citation_ids=[first, second],
                validation_result="passed", repair_attempted=False,
            ))
            outcome = orchestrator.UatConversationOutcome(
                response_kind="answer", answer_text="PRIVATE-ANSWER",
                display_format="narrative", model_name="synthetic", citation_ids=(second,),
                coverage_status="incomplete", coverage_note="Partial fixture scope.",
            )
            return {"status": "partial", "answer": "PRIVATE-ANSWER", "citations": [second]}, (), outcome

        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as stderr:
            path = Path(directory) / "private.jsonl"
            self.ask(self.service(path), run=run)
            record = json.loads(path.read_text())
        mcp, final = record["citation_stages"]
        self.assertEqual(mcp["raw_governed"]["citation_ids"], [first, second])
        self.assertEqual(mcp["compacted_presented"]["citation_ids"], [second])
        self.assertEqual(final["final_model"]["citation_ids"], [second])
        self.assertEqual(record["final_answer"]["citation_ids"], [second])
        self.assertNotIn("citation_ids", json.dumps(public))
        self.assertNotIn(first, stderr.getvalue())
        self.assertNotIn(second, stderr.getvalue())

    def test_call_captures_only_validated_plan_support_and_deadline_metadata(self):
        citation = "sha256:" + "c" * 64
        contract = {
            "original_query_hash": sha256_json("synthetic query"),
            "query_class": "evidence_lookup", "source_family_scope": ["mail"],
            "requested_fields": ["dispatch_window"], "maximum_claim_strength": "cited_evidence",
        }
        request = orchestrator.UatEvidenceToolRequest(
            query_text="SYNTHETIC-ID dispatch window", required_terms=("SYNTHETIC-ID",),
            request_contract=contract,
        )
        coverage = {
            "requested_fields": ["dispatch_window"], "supported_fields": ["dispatch_window"],
            "missing_fields": [], "evidence_citation_hashes": [citation],
            "request_contract_fingerprint": sha256_json(contract),
        }
        coverage["coverage_fingerprint"] = sha256_json(coverage)
        data = {"status": "partial", "citations": [citation], "requested_field_coverage": coverage,
                "query_agent": {"context_bundle": {"source_recovery": {
                    "scan": {"scanned_observation_count": 11, "complete": False,
                             "stop_reason": "deadline"},
                }}}}
        response = SimpleNamespace(status_code=200, json=lambda: {
            "result": {"structuredContent": {"data": data}},
        })
        service = self.service(Path("unused.jsonl"))
        service._client = SimpleNamespace(post=MagicMock(return_value=response))
        service.request_count = 0
        service.last_failure_phase = "provider_model"
        service._active_turn_deadline = runtime.time.monotonic() + 2
        traces = []
        with redirect_stderr(io.StringIO()) as stderr:
            actual = service._call(request, trace_sink=traces,
                                   browser_request_sha256="sha256:" + "d" * 64)
        self.assertEqual(actual, data)
        private = traces[0]["private_diagnostic"]
        self.assertEqual(private["request_contract"], contract)
        self.assertEqual(private["raw_governed"]["citation_ids"], [citation])
        self.assertEqual(private["source_recovery"]["scan_stop_reason"], "deadline")
        self.assertEqual(private["field_support"]["verified_supported_field_hashes"],
                         [sha256_json("dispatch_window")])
        self.assertNotIn("private_diagnostic", json.dumps(runtime._safe_mcp_call_diagnostic(traces)))
        self.assertNotIn(request.query_text, stderr.getvalue())
        self.assertNotIn("dispatch_window", stderr.getvalue())
        # A citation alone never creates verified field support.
        del data["requested_field_coverage"]
        self.assertEqual(runtime._private_behavior_call_diagnostic(
            request, traces[0], data,
        )["field_support"]["verified_supported_field_hashes"], [])

    def test_original_provider_error_is_preserved_and_logged(self):
        error = TimeoutError("PRIVATE provider error /hidden/storage")
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as stderr:
            path = Path(directory) / "private.jsonl"
            with self.assertRaises(TimeoutError) as caught:
                self.ask(self.service(path), run=MagicMock(side_effect=error))
            self.assertIs(caught.exception, error)
            record = json.loads(path.read_text())
            self.assertIsNone(record["result"])
            self.assertIsNotNone(record["failure_sha256"])
            self.assertNotIn("PRIVATE provider error", path.read_text() + stderr.getvalue())
            self.assertNotIn("/hidden/storage", path.read_text() + stderr.getvalue())

    def test_recording_failure_does_not_replace_success_or_original_error(self):
        for business_error in (None, TimeoutError("original")):
            with self.subTest(error=business_error), redirect_stderr(io.StringIO()) as stderr:
                service = self.service(Path("unused.jsonl"))
                with patch.object(runtime, "_append_behavior_log",
                                  side_effect=OSError("secret=private /hidden/storage")):
                    if business_error is None:
                        self.assertEqual(self.ask(service)["answer"], "PRIVATE-ANSWER")
                    else:
                        with self.assertRaises(TimeoutError) as caught:
                            self.ask(service, run=MagicMock(side_effect=business_error))
                        self.assertIs(caught.exception, business_error)
                events = [json.loads(line) for line in stderr.getvalue().splitlines()]
                failure = events[-1]
                self.assertEqual(failure["event"], "issue56_private_uat_behavior_log_failure")
                self.assertEqual(failure["failure_kind"], "io")
                self.assertEqual(failure["request_id"], events[-2]["request_id"])
                self.assertNotIn("/hidden/storage", stderr.getvalue())
                self.assertNotIn("secret=private", stderr.getvalue())
                self.assertIsNone(orchestrator._PRIVATE_UAT_CITATION_TRACE.get())

    def test_unsafe_prompt_is_not_persisted_and_log_rejection_is_safe(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as stderr:
            path = Path(directory) / "private.jsonl"
            answer = self.ask(self.service(path), prompt="Authorization: Bearer abcdefghijklmnop")
            self.assertEqual(answer["answer"], "PRIVATE-ANSWER")
            self.assertFalse(path.exists())
            self.assertEqual(json.loads(stderr.getvalue().splitlines()[-1])["failure_kind"], "validation")
            self.assertNotIn("abcdefghijklmnop", stderr.getvalue())

    def test_citation_bound_and_hashing_prevent_locator_or_secret_leaks(self):
        unsafe = "/hidden/storage/secret"
        snapshot = orchestrator._private_citation_ids_snapshot([unsafe])
        self.assertEqual(snapshot["citation_ids"], [sha256_json(unsafe)])
        self.assertNotIn(unsafe, json.dumps(snapshot))
        large = orchestrator._private_citation_ids_snapshot([str(i) for i in range(101)])
        self.assertEqual(large["citation_count"], 101)
        self.assertEqual(len(large["citation_ids"]), 100)
        self.assertTrue(large["truncated"])


if __name__ == "__main__":
    unittest.main()
