"""Deployed UAT turn and provider request budgets (slow-provider configuration)."""

from __future__ import annotations

import inspect
import unittest

import _paths  # noqa: F401

from formowl_gateway import issue56_uat_runtime
from formowl_mail import human_uat_orchestrator as orchestrator


class UatTurnBudgetTests(unittest.TestCase):
    def test_deployed_turn_and_request_caps(self) -> None:
        self.assertEqual(orchestrator._MAX_UAT_TURN_SECONDS, 300.0)
        self.assertIs(issue56_uat_runtime._MAX_UAT_TURN_SECONDS, orchestrator._MAX_UAT_TURN_SECONDS)
        default = inspect.signature(orchestrator.CodexResponsesConversationModel).parameters["timeout_seconds"].default
        self.assertEqual(default, 240.0)
        self.assertLessEqual(default, orchestrator._MAX_RESPONSES_TIMEOUT_SECONDS)
        self.assertLess(default, orchestrator._MAX_UAT_TURN_SECONDS - orchestrator._UAT_TURN_RETURN_MARGIN_SECONDS)


if __name__ == "__main__":
    unittest.main()
