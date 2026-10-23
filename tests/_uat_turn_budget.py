"""Pin the legacy 120 s UAT turn cap for tests that model budget arithmetic.

The deployed cap is a configuration value (raised for slow providers); these
tests verify how a fixed turn budget is split across provider attempts, MCP
rounds and return margins, so they pin the value they were written against.
``tests/test_issue56_uat_turn_budget.py`` asserts the deployed values.
"""

from __future__ import annotations

from unittest import mock

LEGACY_TURN_SECONDS = 120.0
_patchers: list = []


def start() -> None:
    from formowl_gateway import issue56_uat_runtime
    from formowl_mail import human_uat_orchestrator

    for module in (human_uat_orchestrator, issue56_uat_runtime):
        patcher = mock.patch.object(module, "_MAX_UAT_TURN_SECONDS", LEGACY_TURN_SECONDS)
        patcher.start()
        _patchers.append(patcher)


def stop() -> None:
    while _patchers:
        _patchers.pop().stop()
