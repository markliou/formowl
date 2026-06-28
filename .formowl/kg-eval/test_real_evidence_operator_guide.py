#!/usr/bin/env python3
"""Tests for the remaining real-evidence operator guide generator."""

from __future__ import annotations

import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO

import real_evidence_collection_work_orders as work_orders
import real_evidence_operator_guide as guide


def nested_strings(payload: object) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str):
                values.append(key)
            values.extend(nested_strings(value))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(nested_strings(value))
    elif isinstance(payload, str):
        values.append(payload)
    return values


class RealEvidenceOperatorGuideTest(unittest.TestCase):
    def setUp(self) -> None:
        self.output = guide.WORK_PACKETS / "test_remaining_real_evidence_operator_guide.md"
        self.nested_output = (
            guide.WORK_PACKETS / "test_remaining_real_evidence_operator_guide_parent" / "guide.md"
        )

    def tearDown(self) -> None:
        for path in [self.output, self.nested_output]:
            if path.exists() or path.is_symlink():
                path.unlink()
        if self.nested_output.parent.exists():
            self.nested_output.parent.rmdir()

    def test_guide_covers_all_current_work_orders_without_acceptance_authority(self) -> None:
        report = work_orders.build_report()
        text = guide.build_guide(report)

        self.assertIn("# Remaining KG Real-Evidence Operator Guide", text)
        self.assertIn("This guide is not an acceptance artifact", text)
        self.assertIn("accepts evidence: False", text)
        self.assertIn("promotes evidence: False", text)
        self.assertIn("writes canonical packets: False", text)
        self.assertIn("counts as acceptance gate: False", text)
        self.assertIn("## Gate Progress Report", text)
        self.assertIn("real_evidence_gate_progress.py", text)
        self.assertIn("persisted preflight/work-order reports", text)
        self.assertIn("work-packet surfaces", text)
        self.assertIn("does not refresh preflight", text)
        self.assertIn("operator response packets", text)
        self.assertIn("read candidate artifact contents", text)
        self.assertIn("write canonical packets", text)
        self.assertIn("A gate still requires a", text)
        self.assertIn("candidate_artifacts_present_without_manifest", text)
        self.assertIn("candidate_validation_failed_or_stale", text)
        self.assertIn("## Submission Manifest Preflight", text)
        self.assertIn("real_evidence_submission_manifest.py --check-template", text)
        self.assertIn("real_evidence_submission_manifest.py --manifest", text)
        self.assertIn("--emit-intake-plan", text)
        self.assertIn("work_packets/OPERATOR_INTAKE_PLAN.json", text)
        self.assertIn("response preflight or candidate-only intake command", text)
        self.assertIn("paired response-preflight commands", text)
        self.assertIn("`--preflight-response` command", text)
        self.assertIn("Response preflight reads", text)
        self.assertIn("writes no candidate artifacts, writes no candidate", text)
        self.assertIn("--preflight-responses", text)
        self.assertIn("one controlled non-evidence runner", text)
        self.assertIn("reads operator response-packet", text)
        self.assertIn("leaves a final-state", text)
        self.assertIn("candidate output surface or canonical packet surface changed", text)
        self.assertIn("--execute-candidate-intakes", text)
        self.assertIn("candidate artifacts plus generated candidate manifests only", text)
        self.assertIn("still does not count as an acceptance gate", text)
        self.assertIn("remain for operator", text)
        self.assertIn("not automatically promoted or rolled back", text)
        self.assertIn("fails closed if", text)
        self.assertIn("candidate-only helper exits with a canonical packet path created", text)
        self.assertIn("or changed", text)
        self.assertIn("refuses to launch subprocesses", text)
        self.assertIn("already a symlink, hardlink alias, non-regular", text)
        self.assertIn("--validate-candidate-manifests", text)
        self.assertIn("validate-only runner", text)
        self.assertIn("reads emitted candidate manifests", text)
        self.assertIn("writes no candidate artifacts", text)
        self.assertIn("runs no response intake commands", text)
        self.assertIn("assembler exits with", text)
        self.assertIn("a canonical packet path created or changed", text)
        self.assertIn("refuses to launch", text)
        self.assertIn("--emit-candidate-validation-report", text)
        self.assertIn("ignored non-evidence", text)
        self.assertIn("does not authorize", text)
        self.assertIn("_candidate_validation_report.json", text)
        self.assertIn("real_evidence_governance_approval.py --check-template", text)
        self.assertIn(
            "work_packets/remaining_real_evidence_governance_approval.template.json",
            text,
        )
        self.assertIn("real_evidence_governance_approval.py --approval-manifest", text)
        self.assertIn("--execute-approved-promotion", text)
        self.assertIn("approval manifest remains non-evidence", text)
        self.assertIn("refuses stale hashes", text)
        self.assertIn("manifest bytes consumed for", text)
        self.assertIn("pre-existing canonical packet targets", text)
        self.assertIn("removes that", text)
        self.assertIn("newly created target packet", text)
        self.assertIn("passing target gate", text)
        self.assertIn("Do not pass generated `*_candidate_manifest.json` files", text)
        self.assertIn("not operator-filled submission manifests", text)
        self.assertIn("preflight rejects hardlink aliases", text)
        self.assertIn(
            "work_packets/remaining_real_evidence_submission_manifest.template.json",
            text,
        )
        self.assertNotIn("--promote", text)
        self.assertNotIn("supports_", text)
        self.assertNotIn("overall_passed=true", text)
        self.assertNotIn("accepts_evidence: true", text.lower())

        for order in report["work_orders"]:
            with self.subTest(gate_id=order["gate_id"]):
                self.assertIn(f"## {order['gate_id']}", text)
                self.assertIn(order["canonical_input_packet"], text)
                self.assertIn(order["real_artifact_root"], text)
                self.assertIn(order["validator_module"], text)
                self.assertIn(order["assembler_module"], text)
                for blocker in order["current_blockers"]:
                    self.assertIn(blocker, text)
                response_contract = order["operator_tasks"]["response_packet_contract"]
                self.assertIn(response_contract["work_packet_path"], text)
                self.assertIn(response_contract["candidate_output_dir"], text)
                self.assertIn(response_contract["assembly_manifest_output"], text)
                self.assertIn(
                    f"--assembly-manifest {response_contract['assembly_manifest_output']} --validate",
                    text,
                )
                self.assertIn(
                    response_contract["canonical_packet_not_written"],
                    text,
                )
                self.assertIn("Response packet preflight command:", text)
                preflight_commands = [
                    value
                    for key, value in order["commands"].items()
                    if isinstance(value, str) and key.startswith("preflight_")
                ]
                self.assertEqual(len(preflight_commands), 1)
                self.assertIn(preflight_commands[0], text)
                self.assertIn("--preflight-response", preflight_commands[0])
                self.assertIn("Candidate-only intake command:", text)
                self.assertIn("Optional non-evidence scaffold command:", text)
                self.assertIn("Candidate manifest emitted by intake:", text)
                self.assertIn("Validation sequence after candidate artifacts exist:", text)

    def test_guide_is_sourced_from_work_order_report(self) -> None:
        report = work_orders.build_report()
        mutated = deepcopy(report)
        mutated["report_sha256"] = "mutated-test-sha"
        mutated["work_orders"][0]["current_blockers"].append("operator test blocker")
        mutated["work_orders"][0]["operator_tasks"]["response_packet_contract"][
            "required_controls"
        ].append("operator test required control")

        text = guide.build_guide(mutated)

        self.assertIn("mutated-test-sha", text)
        self.assertIn("operator test blocker", text)
        self.assertIn("operator test required control", text)

    def test_drifted_work_orders_withhold_gate_specific_instructions(self) -> None:
        report = work_orders.build_report()
        drifted = deepcopy(report)
        drifted["sync"]["status"] = "drifted"

        text = guide.build_guide(drifted)

        self.assertIn("## Guide Withheld", text)
        self.assertIn("not synchronized", text)
        self.assertIn("## Submission Manifest Preflight", text)
        self.assertNotIn("Response packet preflight command:", text)
        self.assertNotIn("Candidate-only intake command:", text)

    def test_output_path_is_limited_to_work_packets_markdown(self) -> None:
        valid = guide.safe_output_path(
            "work_packets/test_remaining_real_evidence_operator_guide.md"
        )

        self.assertEqual(valid, self.output.resolve())
        with self.assertRaisesRegex(ValueError, "under work_packets"):
            guide.safe_output_path("inputs/human_annotation_real/operator/guide.md")
        with self.assertRaisesRegex(ValueError, "markdown"):
            guide.safe_output_path("work_packets/operator-guide.json")

    def test_main_writes_markdown_guide_and_reports_non_authoritative_summary(self) -> None:
        stdout = StringIO()

        with redirect_stdout(stdout):
            result = guide.main(
                ["--output", "work_packets/test_remaining_real_evidence_operator_guide.md"]
            )

        self.assertEqual(result, 0)
        self.assertTrue(self.output.exists())
        text = self.output.read_text(encoding="utf-8")
        self.assertIn("Remaining KG Real-Evidence Operator Guide", text)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["artifact_id"], "kg_real_evidence_operator_guide_v1")
        self.assertEqual(
            payload["output"],
            "work_packets/test_remaining_real_evidence_operator_guide.md",
        )
        self.assertFalse(payload["authority"]["accepts_evidence"])
        self.assertFalse(payload["authority"]["promotes_evidence"])
        self.assertFalse(payload["authority"]["writes_canonical_packets"])
        self.assertFalse(payload["authority"]["counts_as_acceptance_gate"])

    def test_check_mode_passes_when_tracked_guide_is_current(self) -> None:
        with redirect_stdout(StringIO()):
            guide.main(["--output", "work_packets/test_remaining_real_evidence_operator_guide.md"])
        stdout = StringIO()

        with redirect_stdout(stdout):
            result = guide.main(
                [
                    "--output",
                    "work_packets/test_remaining_real_evidence_operator_guide.md",
                    "--check",
                ]
            )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["check"]["exists"])
        self.assertTrue(payload["check"]["up_to_date"])
        self.assertFalse(payload["authority"]["accepts_evidence"])
        self.assertFalse(payload["authority"]["writes_canonical_packets"])

    def test_check_mode_fails_without_rewriting_stale_guide(self) -> None:
        self.output.write_text("stale operator guide\n", encoding="utf-8")
        before = self.output.read_text(encoding="utf-8")
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = guide.main(
                [
                    "--output",
                    "work_packets/test_remaining_real_evidence_operator_guide.md",
                    "--check",
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(self.output.read_text(encoding="utf-8"), before)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["check"]["exists"])
        self.assertFalse(payload["check"]["up_to_date"])
        self.assertIn("operator guide is stale", stderr.getvalue())

    def test_guide_does_not_introduce_forbidden_authority_claims_from_report(self) -> None:
        report = work_orders.build_report()
        text = guide.build_guide(report)
        report_strings = nested_strings(report)

        self.assertFalse(any("--promote" in value for value in report_strings))
        self.assertFalse(any("--promote" in value for value in nested_strings(text)))
        self.assertNotIn("counts_as_acceptance_gate: True", text)
        self.assertNotIn("writes_canonical_packet: True", text)


if __name__ == "__main__":
    unittest.main()
