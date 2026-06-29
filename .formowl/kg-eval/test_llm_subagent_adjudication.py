#!/usr/bin/env python3
"""Tests for the shared four-specialist LLM subagent panel contract."""

from __future__ import annotations

from copy import deepcopy
import unittest

import llm_subagent_adjudication as panel_contract


INPUT_HASHES = [f"{index + 1:064x}" for index in range(3)]
RUBRIC_HASH = "a1234567890bcdef" * 4


def valid_panel() -> dict:
    panel = {
        "artifact_type": panel_contract.PANEL_ARTIFACT_TYPE,
        "panel_id": "panel_fair_baseline_001",
        "adjudication_target": "fair_external_baseline_comparison",
        "completed": True,
        "final_decision": "PASS",
        "human_adjudication_claimed": False,
        "input_artifact_sha256s": sorted(INPUT_HASHES),
        "rubric_sha256": RUBRIC_HASH,
        "specialist_subagents": [
            {
                "subagent_id": f"subagent_{specialty}",
                "specialty": specialty,
                "professional_role": panel_contract.REQUIRED_PROFESSIONAL_ROLES[specialty],
                "model_name": "codex-subagent",
                "model_version": "2026-06-28",
                "prompt_sha256": f"{index + 10:064x}",
                "rubric_sha256": RUBRIC_HASH,
                "run_id": f"run_{specialty}_001",
                "temperature": 0,
                "independent": True,
                "decision": "PASS",
                "blocking_findings": [],
                "reviewed_artifact_sha256s": sorted(INPUT_HASHES),
                "output_sha256": f"{index + 20:064x}",
            }
            for index, specialty in enumerate(panel_contract.REQUIRED_SPECIALTIES)
        ],
    }
    panel["panel_decision_sha256"] = panel_contract.panel_decision_sha256(panel)
    return panel


class LlmSubagentAdjudicationContractTest(unittest.TestCase):
    def test_valid_panel_passes_contract(self) -> None:
        blockers: list[str] = []

        panel_contract.validate_four_specialist_panel(
            valid_panel(),
            blockers,
            label="fair baseline",
            expected_target="fair_external_baseline_comparison",
            expected_input_sha256s=INPUT_HASHES,
        )

        self.assertEqual(blockers, [])

    def test_missing_specialist_fails_contract(self) -> None:
        panel = valid_panel()
        panel["specialist_subagents"].pop()
        panel["panel_decision_sha256"] = panel_contract.panel_decision_sha256(panel)
        blockers: list[str] = []

        panel_contract.validate_four_specialist_panel(
            panel,
            blockers,
            label="fair baseline",
            expected_target="fair_external_baseline_comparison",
            expected_input_sha256s=INPUT_HASHES,
        )

        self.assertIn(
            "fair baseline four-specialist LLM panel must include exactly four subagents",
            blockers,
        )
        self.assertIn(
            "fair baseline four-specialist LLM panel specialty coverage mismatch",
            blockers,
        )

    def test_any_blocking_subagent_fails_contract(self) -> None:
        panel = valid_panel()
        panel["specialist_subagents"][0]["decision"] = "BLOCK"
        panel["specialist_subagents"][0]["blocking_findings"] = ["missing baseline run"]
        panel["panel_decision_sha256"] = panel_contract.panel_decision_sha256(panel)
        blockers: list[str] = []

        panel_contract.validate_four_specialist_panel(
            panel,
            blockers,
            label="fair baseline",
            expected_target="fair_external_baseline_comparison",
            expected_input_sha256s=INPUT_HASHES,
        )

        self.assertIn(
            "fair baseline four-specialist LLM subagent decision is not PASS",
            blockers,
        )
        self.assertIn(
            "fair baseline four-specialist LLM subagent has blocking findings",
            blockers,
        )

    def test_generic_professional_role_fails_contract(self) -> None:
        panel = valid_panel()
        panel["specialist_subagents"][0]["professional_role"] = "generic_llm_judge"
        panel["panel_decision_sha256"] = panel_contract.panel_decision_sha256(panel)
        blockers: list[str] = []

        panel_contract.validate_four_specialist_panel(
            panel,
            blockers,
            label="fair baseline",
            expected_target="fair_external_baseline_comparison",
            expected_input_sha256s=INPUT_HASHES,
        )

        self.assertIn(
            "fair baseline four-specialist LLM subagent professional role mismatch",
            blockers,
        )

    def test_duplicated_run_prompt_and_output_fail_contract(self) -> None:
        panel = valid_panel()
        panel["specialist_subagents"][1]["run_id"] = panel["specialist_subagents"][0]["run_id"]
        panel["specialist_subagents"][1]["prompt_sha256"] = panel["specialist_subagents"][0][
            "prompt_sha256"
        ]
        panel["specialist_subagents"][1]["output_sha256"] = panel["specialist_subagents"][0][
            "output_sha256"
        ]
        panel["panel_decision_sha256"] = panel_contract.panel_decision_sha256(panel)
        blockers: list[str] = []

        panel_contract.validate_four_specialist_panel(
            panel,
            blockers,
            label="fair baseline",
            expected_target="fair_external_baseline_comparison",
            expected_input_sha256s=INPUT_HASHES,
        )

        self.assertIn(
            "fair baseline four-specialist LLM subagent run_ids are not distinct",
            blockers,
        )
        self.assertIn(
            "fair baseline four-specialist LLM subagent prompt hashes are not distinct",
            blockers,
        )
        self.assertIn(
            "fair baseline four-specialist LLM subagent output hashes are not distinct",
            blockers,
        )

    def test_panel_cannot_claim_human_adjudication(self) -> None:
        panel = valid_panel()
        panel["human_adjudication_claimed"] = True
        panel["panel_decision_sha256"] = panel_contract.panel_decision_sha256(panel)
        blockers: list[str] = []

        panel_contract.validate_four_specialist_panel(
            panel,
            blockers,
            label="fair baseline",
            expected_target="fair_external_baseline_comparison",
            expected_input_sha256s=INPUT_HASHES,
        )

        self.assertIn(
            "fair baseline four-specialist LLM panel must not claim human adjudication",
            blockers,
        )

    def test_stale_decision_hash_fails_contract(self) -> None:
        panel = valid_panel()
        stale_panel = deepcopy(panel)
        stale_panel["final_decision"] = "BLOCK"
        blockers: list[str] = []

        panel_contract.validate_four_specialist_panel(
            stale_panel,
            blockers,
            label="fair baseline",
            expected_target="fair_external_baseline_comparison",
            expected_input_sha256s=INPUT_HASHES,
        )

        self.assertIn(
            "fair baseline four-specialist LLM panel final decision is not PASS",
            blockers,
        )
        self.assertIn(
            "fair baseline four-specialist LLM panel decision hash mismatch",
            blockers,
        )


if __name__ == "__main__":
    unittest.main()
