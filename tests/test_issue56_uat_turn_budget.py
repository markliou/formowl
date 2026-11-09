"""Deployed UAT turn and provider request budgets (slow-provider configuration)."""

from __future__ import annotations

import inspect
import threading
import unittest
from unittest import mock

import _paths  # noqa: F401

from formowl_gateway import issue56_uat_runtime
from formowl_mail import human_uat_orchestrator as orchestrator


class UatTurnBudgetTests(unittest.TestCase):
    def test_deployed_turn_and_request_caps(self) -> None:
        self.assertEqual(orchestrator._MAX_UAT_TURN_SECONDS, 240.0)
        self.assertIs(issue56_uat_runtime._MAX_UAT_TURN_SECONDS, orchestrator._MAX_UAT_TURN_SECONDS)
        default = inspect.signature(orchestrator.CodexResponsesConversationModel).parameters["timeout_seconds"].default
        self.assertEqual(default, 240.0)
        self.assertLessEqual(default, orchestrator._MAX_RESPONSES_TIMEOUT_SECONDS)
        stdio_timeout = inspect.signature(orchestrator.CodexAppServerStdioTransport).parameters["timeout_seconds"].default
        self.assertEqual(stdio_timeout, orchestrator._MAX_UAT_TURN_SECONDS)

    def test_official_app_server_long_turn_uses_remaining_browser_time(self):
        from test_issue56_codex_provider_bridge import _decision

        for model_seconds, completes in [(226, True), (228, False)]:
            with self.subTest(model_seconds=model_seconds):
                # At provider entry, 13 seconds of the original browser turn have elapsed.
                now = 1013.0
                deadline = 1240.0
                wire = object.__new__(orchestrator.CodexAppServerStdioTransport)
                wire._timeout_seconds = inspect.signature(type(wire)).parameters["timeout_seconds"].default
                wire._state_lock = threading.RLock()
                wire._thread_locks = {}
                wire._active_turns = {}
                wire._fatal_error = False
                wire.start_thread = mock.Mock(return_value=orchestrator.CodexAppServerThread("fixture", "model"))
                wire.delete_thread = mock.Mock()
                wire._interrupt_turn = mock.Mock()
                def request(method, params, *, timeout_seconds):
                    self.assertEqual(method, "turn/start")
                    self.assertEqual(timeout_seconds, deadline - now)
                    context = wire._active_turns[params["threadId"]]
                    def wait(remaining):
                        nonlocal now
                        self.assertEqual(remaining, deadline - now)
                        now += min(remaining, model_seconds)
                        if remaining < model_seconds:
                            return False
                        wire._deliver_turn_completion({
                            "threadId": "fixture", "turn": {"id": "turn", "status": "completed",
                            "items": [{"type": "agentMessage", "text": _decision()}]}})
                        return True
                    context.event.wait = wait
                    return {"turn": {"id": "turn"}}
                wire._request = request
                provider = orchestrator.CodexAppServerConversationModel(wire, workspace_dir="/tmp", model="model")
                token = orchestrator._BROWSER_TURN_DEADLINE.set(deadline)
                try:
                    with mock.patch.object(orchestrator.time, "monotonic", side_effect=lambda: now):
                        result = provider.respond(history=(), user_text="Hello", latest_evidence=None,
                            safety_identifier="fixture", evidence_tool=mock.Mock())
                finally:
                    orchestrator._BROWSER_TURN_DEADLINE.reset(token)
                if completes:
                    self.assertEqual(result.answer_text, "bounded answer")
                    wire._interrupt_turn.assert_not_called()
                else:
                    self.assertEqual(result.provider_diagnostic["reason_code"], "provider_timeout")
                    wire._interrupt_turn.assert_called_once_with("fixture", "turn")


if __name__ == "__main__":
    unittest.main()
