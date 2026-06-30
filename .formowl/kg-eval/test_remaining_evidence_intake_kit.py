#!/usr/bin/env python3
"""Tests for the remaining real-evidence intake kit."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

import enterprise_multimodal_validation_validator as enterprise_multimodal
import fair_external_baseline_run_validator as fair_baseline
import human_annotation_adjudication_validator as human_annotation
import kg_total_acceptance_suite as total_suite
import production_adapter_path_validator as production_adapter


ROOT = Path(__file__).resolve().parent
CHECKLIST = ROOT / "remaining_evidence_checklist.json"
TEMPLATES = ROOT / "templates"


HISTORICAL_GATES = {
    "fair_external_baseline_comparison": {
        "validator": fair_baseline,
        "validator_module": "fair_external_baseline_run_validator.py",
        "input_packet": "inputs/fair_external_baseline_run_packet.json",
        "required_packet_artifact_id": "fair_external_baseline_run_packet_v1",
        "required_evidence_kind": "non_synthetic_external_baseline_run",
        "template": "fair_external_baseline_run_packet.template.json",
    },
    "annotation_adjudication_protocol": {
        "validator": human_annotation,
        "validator_module": "human_annotation_adjudication_validator.py",
        "input_packet": "inputs/human_annotation_results_v1.json",
        "required_packet_artifact_id": "llm_subagent_annotation_results_v1",
        "required_evidence_kind": "four_specialist_llm_subagent_annotation_adjudication",
        "template_packet_artifact_id": "human_annotation_results_v1",
        "template_evidence_kind": "real_human_annotation_adjudication",
        "template": "human_annotation_results_v1.template.json",
    },
    "multimodal_semantic_validation": {
        "validator": enterprise_multimodal,
        "validator_module": "enterprise_multimodal_validation_validator.py",
        "input_packet": "inputs/enterprise_multimodal_validation_packet.json",
        "required_packet_artifact_id": "enterprise_multimodal_validation_packet_v1",
        "required_evidence_kind": "real_enterprise_multimodal_validation",
        "template": "enterprise_multimodal_validation_packet.template.json",
    },
    "production_adapter_paths": {
        "validator": production_adapter,
        "validator_module": "production_adapter_path_validator.py",
        "input_packet": "inputs/production_adapter_evidence_packet.json",
        "required_packet_artifact_id": "production_adapter_evidence_packet_v1",
        "required_evidence_kind": "non_synthetic_production_adapter_validation",
        "template": "production_adapter_evidence_packet.template.json",
    },
}
CURRENT_REMAINING_GATE_IDS = set(total_suite.build_report()["summary"]["failed_gate_ids"])
CURRENT_REMAINING_GATES = {
    gate_id: expected
    for gate_id, expected in HISTORICAL_GATES.items()
    if gate_id in CURRENT_REMAINING_GATE_IDS
}


def load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def exact_artifact_fields(values: list[object]) -> list[str]:
    return [
        value
        for value in values
        if isinstance(value, str)
        and " " not in value
        and value.endswith(("_artifact", "_artifacts"))
    ]


class RemainingEvidenceIntakeKitTest(unittest.TestCase):
    def test_checklist_stays_synchronized_with_validator_packet_contracts(self) -> None:
        checklist = load_json(CHECKLIST)
        rows = {row["gate_id"]: row for row in checklist["remaining_gates"]}

        self.assertEqual(set(rows), set(CURRENT_REMAINING_GATES))
        for gate_id, expected in CURRENT_REMAINING_GATES.items():
            row = rows[gate_id]
            validator = expected["validator"]
            report = validator.build_report({})

            self.assertEqual(row["validator_module"], expected["validator_module"])
            self.assertEqual(row["input_packet"], expected["input_packet"])
            self.assertEqual(
                row["required_packet_artifact_id"], expected["required_packet_artifact_id"]
            )
            self.assertEqual(row["required_evidence_kind"], expected["required_evidence_kind"])
            self.assertEqual(row["current_blockers"], report["blockers"])
            self.assertFalse(report["passed"])

            template = load_json(TEMPLATES / expected["template"])
            packet_allowed_fields = getattr(validator, "PACKET_ALLOWED_FIELDS", set())
            for field in exact_artifact_fields(row.get("required_artifacts", [])):
                self.assertIn(field, packet_allowed_fields)
                if field in template:
                    continue
                self.assertIn(f"{field}_sha256", template)
            claim_boundary_allowed_fields = getattr(
                validator, "CLAIM_BOUNDARY_ALLOWED_FIELDS", set()
            )
            if claim_boundary_allowed_fields:
                self.assertEqual(
                    set(template["claim_boundary"]), set(claim_boundary_allowed_fields)
                )

    def test_checklist_status_matches_total_acceptance_snapshot(self) -> None:
        checklist = load_json(CHECKLIST)
        total = total_suite.build_report()
        summary = total["summary"]
        failed_gate_ids = [row["gate_id"] for row in checklist["remaining_gates"]]

        self.assertEqual(checklist["overall_passed"], summary["overall_passed"])
        self.assertEqual(checklist["passed_gate_count"], summary["passed_gate_count"])
        self.assertEqual(checklist["failed_gate_count"], summary["failed_gate_count"])
        self.assertEqual(checklist["gate_status_sha256"], summary["gate_status_sha256"])
        self.assertEqual(failed_gate_ids, summary["failed_gate_ids"])

    def test_templates_are_outside_real_input_paths_and_cannot_pass_validators(self) -> None:
        for gate_id, expected in HISTORICAL_GATES.items():
            with self.subTest(gate_id=gate_id):
                template_path = TEMPLATES / expected["template"]
                template = load_json(template_path)
                validator = expected["validator"]
                report = validator.build_report(template)

                self.assertTrue(template["template_only"])
                self.assertTrue(template["do_not_submit_as_evidence"])
                self.assertEqual(
                    template["artifact_id"],
                    expected.get(
                        "template_packet_artifact_id", expected["required_packet_artifact_id"]
                    ),
                )
                self.assertEqual(
                    template["evidence_kind"],
                    expected.get("template_evidence_kind", expected["required_evidence_kind"]),
                )
                self.assertNotEqual(str(template_path.relative_to(ROOT)), expected["input_packet"])
                self.assertFalse(report["passed"])
                self.assertTrue(report["blockers"])
                self.assertTrue(
                    any("unsupported fields" in blocker for blocker in report["blockers"])
                )

    def test_templates_do_not_change_total_acceptance_failed_gates(self) -> None:
        total = total_suite.build_report()

        self.assertEqual(total["summary"]["passed_gate_count"], 8)
        self.assertEqual(total["summary"]["failed_gate_count"], 4)
        self.assertEqual(
            total["summary"]["failed_gate_ids"],
            [
                "fair_external_baseline_comparison",
                "annotation_adjudication_protocol",
                "multimodal_semantic_validation",
                "production_adapter_paths",
            ],
        )


if __name__ == "__main__":
    unittest.main()
