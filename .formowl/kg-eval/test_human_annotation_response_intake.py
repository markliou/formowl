#!/usr/bin/env python3
"""Tests for sealing real human annotation responses into candidate artifacts."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import human_annotation_adjudication_validator as validator
import human_annotation_packet_assembler as assembler
import human_annotation_response_intake as intake
import human_annotation_work_packet_generator as work_packet_generator


BASE = validator.REAL_ARTIFACT_ROOT_PATH / "intake_test"
LIVE_CLI_BASE = validator.REAL_ARTIFACT_ROOT_PATH / "operator_intake_cli_check"
ASSEMBLY_MANIFEST = intake.WORK_PACKETS / "test_human_annotation_response_intake_manifest.json"
WORK_PACKET_PATH = intake.WORK_PACKETS / "test_human_annotation_response_intake_work_packet.json"
RESPONSE_PACKET_PATH = intake.WORK_PACKETS / "test_human_annotation_response_intake_response.json"
BROKEN_SYMLINK_TARGET = Path("/tmp/formowl_human_annotation_response_intake_broken_target.json")


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def valid_response_packet(operator_run_id: str = "intake_test") -> dict[str, object]:
    return {
        "response_packet_type": "human_annotation_response_intake_v1",
        "operator_run_id": operator_run_id,
        "annotation_task_id": work_packet_generator.DEFAULT_ANNOTATION_TASK_ID,
        "first_pass_submissions": [
            {
                "reviewer_id": "human_reviewer_alpha",
                "reviewer_type": "human",
                "independent_first_pass": True,
                "generated_by_llm": False,
                "template_source": None,
                "human_attestation": "reviewed manually by alpha",
                "rows": [
                    {
                        "item_id": "ann_finance_table_revenue_001",
                        "label": "supported",
                        "generated_by_llm": False,
                        "template_source": None,
                    },
                    {
                        "item_id": "ann_meeting_decision_001",
                        "label": "supported",
                        "generated_by_llm": False,
                        "template_source": None,
                    },
                ],
            },
            {
                "reviewer_id": "human_reviewer_beta",
                "reviewer_type": "human",
                "independent_first_pass": True,
                "generated_by_llm": False,
                "template_source": None,
                "human_attestation": "reviewed manually by beta",
                "rows": [
                    {
                        "item_id": "ann_finance_table_revenue_001",
                        "label": "supported",
                        "generated_by_llm": False,
                        "template_source": None,
                    },
                    {
                        "item_id": "ann_meeting_decision_001",
                        "label": "needs_review",
                        "generated_by_llm": False,
                        "template_source": None,
                    },
                ],
            },
        ],
        "adjudication": {
            "adjudicator_id": "human_adjudicator_gamma",
            "reviewer_type": "human",
            "opened_after_first_pass_seal": True,
            "generated_by_llm": False,
            "template_source": None,
            "human_attestation": "reviewed manually by gamma",
            "rows": [
                {
                    "item_id": "ann_meeting_decision_001",
                    "final_label": "needs_review",
                    "generated_by_llm": False,
                    "template_source": None,
                }
            ],
        },
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class HumanAnnotationResponseIntakeTest(unittest.TestCase):
    def setUp(self) -> None:
        remove_path(BASE)
        remove_path(LIVE_CLI_BASE)
        BROKEN_SYMLINK_TARGET.unlink(missing_ok=True)
        for path in (ASSEMBLY_MANIFEST, WORK_PACKET_PATH, RESPONSE_PACKET_PATH):
            path.unlink(missing_ok=True)
        self.canonical_before = (
            assembler.CANONICAL_PACKET_PATH.read_bytes()
            if assembler.CANONICAL_PACKET_PATH.exists()
            else None
        )

    def tearDown(self) -> None:
        remove_path(BASE)
        remove_path(LIVE_CLI_BASE)
        BROKEN_SYMLINK_TARGET.unlink(missing_ok=True)
        for path in (ASSEMBLY_MANIFEST, WORK_PACKET_PATH, RESPONSE_PACKET_PATH):
            path.unlink(missing_ok=True)
        if self.canonical_before is None:
            assembler.CANONICAL_PACKET_PATH.unlink(missing_ok=True)
        else:
            assembler.CANONICAL_PACKET_PATH.write_bytes(self.canonical_before)

    def assert_canonical_unchanged(self) -> None:
        if self.canonical_before is None:
            self.assertFalse(assembler.CANONICAL_PACKET_PATH.exists())
        else:
            self.assertEqual(assembler.CANONICAL_PACKET_PATH.read_bytes(), self.canonical_before)

    def test_valid_response_intake_builds_validator_accepted_candidate_without_promoting(
        self,
    ) -> None:
        response = valid_response_packet()
        result = intake.build_intake_artifacts(
            work_packet=work_packet_generator.build_work_packet(),
            response_packet=response,
            output_dir="inputs/human_annotation_real/intake_test",
            assembly_manifest_output="work_packets/test_human_annotation_response_intake_manifest.json",
            allow_test_artifacts=True,
        )

        self.assertFalse(result["writes_canonical_packet"])
        self.assertTrue(result["validation_report"]["candidate_packet_validator_passed"])
        self.assertEqual(result["validation_report"]["blocker_count"], 0)
        self.assertFalse(result["validation_report"]["authoritative_validator_report_embedded"])
        self.assertFalse(result["validation_report"]["counts_as_acceptance_gate"])
        self.assertNotIn("input_packet", result["validation_report"])
        self.assertNotIn("claim_boundary", result["validation_report"])
        self.assertFalse(any(key.startswith("supports_") for key in result["validation_report"]))
        self.assertTrue(ASSEMBLY_MANIFEST.exists())
        assembly_manifest = json.loads(ASSEMBLY_MANIFEST.read_text(encoding="utf-8"))
        packet = assembler.assemble_packet(**assembly_manifest, allow_test_artifacts=True)
        report = validator.build_report(packet, allow_test_artifacts=True)

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(result["candidate_packet_sha256"], validator.sha256_json(packet))
        self.assertEqual(result["response_packet_sha256"], intake.sha256_artifact_payload(response))
        self.assertEqual(result["operator_run_id"], "intake_test")
        self.assertEqual(
            result["custody_receipt_artifact"],
            "inputs/human_annotation_real/intake_test/response_custody_receipt.json",
        )
        self.assertEqual(
            result["custody_receipt_sha256"],
            validator.sha256_file(BASE / "response_custody_receipt.json"),
        )
        self.assertEqual(
            result["assembly_manifest_sha256"],
            validator.sha256_file(ASSEMBLY_MANIFEST),
        )
        self.assertTrue(result["claim_boundary"]["candidate_packet_validator_passed"])
        self.assertFalse(result["claim_boundary"]["supports_human_annotation_completed_claim"])
        self.assertFalse(result["claim_boundary"]["supports_human_adjudication_completed_claim"])
        custody = json.loads((BASE / "custody_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(custody["response_packet_sha256"], result["response_packet_sha256"])
        response_custody = json.loads(
            (BASE / "response_custody_receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(response_custody["operator_run_id"], "intake_test")
        self.assertEqual(
            response_custody["candidate_packet_sha256"], result["candidate_packet_sha256"]
        )
        self.assertEqual(
            response_custody["assembly_manifest_sha256"],
            validator.sha256_file(ASSEMBLY_MANIFEST),
        )
        self.assertFalse(response_custody["writes_canonical_packet"])
        self.assertFalse(response_custody["counts_as_acceptance_gate"])
        self.assertEqual(
            sorted(path.name for path in BASE.iterdir()),
            [
                "adjudication.json",
                "confusion_matrix.json",
                "custody_receipt.json",
                "first_pass_human_reviewer_alpha.json",
                "first_pass_human_reviewer_beta.json",
                "manifest.json",
                "response_custody_receipt.json",
                "work_orders.json",
            ],
        )
        self.assert_canonical_unchanged()

    def test_cli_preflight_response_validates_without_writing_artifacts(self) -> None:
        write_json(WORK_PACKET_PATH, work_packet_generator.build_work_packet())
        response = valid_response_packet(operator_run_id="operator_intake_cli_check")
        write_json(RESPONSE_PACKET_PATH, response)
        original_argv = sys.argv[:]
        stdout = StringIO()
        try:
            sys.argv = [
                "human_annotation_response_intake.py",
                "--work-packet",
                str(WORK_PACKET_PATH),
                "--response-packet",
                str(RESPONSE_PACKET_PATH),
                "--output-dir",
                "inputs/human_annotation_real/operator_intake_cli_check",
                "--assembly-manifest-output",
                "work_packets/test_human_annotation_response_intake_manifest.json",
                "--preflight-response",
            ]
            with redirect_stdout(stdout):
                exit_code = intake.main()
        finally:
            sys.argv = original_argv

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["preflight_packet_type"], "human_annotation_response_preflight_v1")
        self.assertTrue(result["response_packet_valid_for_candidate_intake"])
        self.assertFalse(result["writes_candidate_artifacts"])
        self.assertFalse(result["writes_canonical_packet"])
        self.assertFalse(result["counts_as_acceptance_gate"])
        self.assertFalse(result["candidate_packet_validator_run"])
        self.assertEqual(result["operator_run_id"], "operator_intake_cli_check")
        self.assertEqual(result["response_packet_sha256"], intake.sha256_artifact_payload(response))
        self.assertIn(
            "inputs/human_annotation_real/operator_intake_cli_check/response_custody_receipt.json",
            result["planned_artifacts"],
        )
        self.assertNotIn("candidate_packet_sha256", result)
        self.assertNotIn("validation_report", result)
        self.assertFalse(LIVE_CLI_BASE.exists())
        self.assertFalse(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()

    def test_rejects_annotation_task_id_mismatch_before_writes(self) -> None:
        response = valid_response_packet()
        response["annotation_task_id"] = "kg_eval_human_annotation_wrong"

        with self.assertRaisesRegex(intake.IntakeError, "annotation_task_id mismatch"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_operator_run_id_output_dir_mismatch_before_writes(self) -> None:
        response = valid_response_packet(operator_run_id="human_run_001")

        with self.assertRaisesRegex(intake.IntakeError, "final segment"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/human_run_002",
            )

        self.assertFalse((validator.REAL_ARTIFACT_ROOT_PATH / "human_run_002").exists())
        self.assert_canonical_unchanged()

    def test_default_rejects_nested_output_dir_before_writes(self) -> None:
        response = valid_response_packet(operator_run_id="human_run_001")

        with self.assertRaisesRegex(intake.IntakeError, "exactly inputs/human_annotation_real"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/human_run_001/nested",
            )

        self.assertFalse((validator.REAL_ARTIFACT_ROOT_PATH / "human_run_001").exists())
        self.assert_canonical_unchanged()

    def test_default_rejects_test_output_dir_before_writes(self) -> None:
        with self.assertRaisesRegex(intake.IntakeError, "test or sandbox"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir="inputs/human_annotation_real/intake_test",
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_llm_or_template_responses_before_writes(self) -> None:
        response = valid_response_packet()
        response["first_pass_submissions"][0]["generated_by_llm"] = True
        with self.assertRaisesRegex(intake.IntakeError, "generated_by_llm"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )
        self.assertFalse(BASE.exists())

        response = valid_response_packet()
        response["first_pass_submissions"][0]["rows"][0]["template_source"] = "copied.template.json"
        with self.assertRaisesRegex(intake.IntakeError, "template_source"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )
        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_unsupported_response_fields_before_writes(self) -> None:
        response = valid_response_packet()
        response["claim_boundary"] = {"supports_human_annotation_completed_claim": True}

        with self.assertRaisesRegex(intake.IntakeError, "unsupported fields"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_raw_internal_nested_response_fields_before_writes(self) -> None:
        response = valid_response_packet()
        response["first_pass_submissions"][0]["rows"][0]["raw_sql"] = "select * from labels"

        with self.assertRaisesRegex(intake.IntakeError, "raw/internal field"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_unsupported_nested_response_fields_before_writes(self) -> None:
        response = valid_response_packet()
        response["first_pass_submissions"][0]["rows"][0]["notes"] = "manually reviewed"

        with self.assertRaisesRegex(intake.IntakeError, "first-pass row has unsupported fields"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_missing_or_extra_adjudication_rows_before_writes(self) -> None:
        response = valid_response_packet()
        response["adjudication"]["rows"] = []

        with self.assertRaisesRegex(intake.IntakeError, "cover exactly the disagreement set"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_all_consensus_packet_because_adjudication_would_not_be_exercised(self) -> None:
        response = valid_response_packet()
        response["first_pass_submissions"][1]["rows"][1]["label"] = "supported"
        response["adjudication"]["rows"] = []

        with self.assertRaisesRegex(intake.IntakeError, "at least one first-pass disagreement"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_unknown_reviewer_or_item_before_writes(self) -> None:
        response = valid_response_packet()
        response["first_pass_submissions"][0]["reviewer_id"] = "human_reviewer_delta"
        with self.assertRaisesRegex(intake.IntakeError, "work order missing"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        response = valid_response_packet()
        response["first_pass_submissions"][0]["rows"][0]["item_id"] = "ann_unknown_001"
        with self.assertRaisesRegex(intake.IntakeError, "unknown item_id"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_refuses_to_overwrite_existing_intake_artifacts(self) -> None:
        BASE.mkdir(parents=True, exist_ok=True)
        (BASE / "manifest.json").write_text("existing\n", encoding="utf-8")

        with self.assertRaisesRegex(intake.IntakeError, "overwrite existing artifacts"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        self.assertEqual((BASE / "manifest.json").read_text(encoding="utf-8"), "existing\n")
        self.assert_canonical_unchanged()

    def test_refuses_broken_symlink_output_artifacts_before_writes(self) -> None:
        BASE.mkdir(parents=True, exist_ok=True)
        (BASE / "manifest.json").symlink_to(BROKEN_SYMLINK_TARGET)

        with self.assertRaisesRegex(intake.IntakeError, "overwrite existing artifacts"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        self.assertFalse(BROKEN_SYMLINK_TARGET.exists())
        self.assertTrue((BASE / "manifest.json").is_symlink())
        self.assert_canonical_unchanged()

    def test_refuses_parent_file_collision_before_writes(self) -> None:
        BASE.parent.mkdir(parents=True, exist_ok=True)
        BASE.write_text("not a directory\n", encoding="utf-8")

        with self.assertRaisesRegex(intake.IntakeError, "parent must be a directory"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir="inputs/human_annotation_real/intake_test",
                allow_test_artifacts=True,
            )

        self.assertEqual(BASE.read_text(encoding="utf-8"), "not a directory\n")
        self.assert_canonical_unchanged()

    def test_rolls_back_candidate_artifacts_when_assembler_fails_after_writes(self) -> None:
        with patch.object(
            assembler, "assemble_packet", side_effect=assembler.AssemblyError("boom")
        ):
            with self.assertRaisesRegex(intake.IntakeError, "boom"):
                intake.build_intake_artifacts(
                    work_packet=work_packet_generator.build_work_packet(),
                    response_packet=valid_response_packet(),
                    output_dir="inputs/human_annotation_real/intake_test",
                    assembly_manifest_output=(
                        "work_packets/test_human_annotation_response_intake_manifest.json"
                    ),
                    allow_test_artifacts=True,
                )

        self.assertFalse(BASE.exists())
        self.assertFalse(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()

    def test_write_json_removes_after_open_partial_output(self) -> None:
        partial = BASE / "partial.json"

        with patch.object(intake, "_artifact_json_text", side_effect=RuntimeError("interrupted")):
            with self.assertRaisesRegex(intake.IntakeError, "write failed"):
                intake._write_json(partial, {"artifact": "partial"})

        self.assertFalse(partial.exists())
        self.assertFalse(any(BASE.glob("*.json")) if BASE.exists() else False)
        self.assert_canonical_unchanged()

    def test_main_writes_candidate_artifacts_and_manifest_without_canonical_promotion(self) -> None:
        write_json(WORK_PACKET_PATH, work_packet_generator.build_work_packet())
        write_json(
            RESPONSE_PACKET_PATH,
            valid_response_packet(operator_run_id="operator_intake_cli_check"),
        )
        original_argv = sys.argv[:]
        stdout = StringIO()
        try:
            sys.argv = [
                "human_annotation_response_intake.py",
                "--work-packet",
                str(WORK_PACKET_PATH),
                "--response-packet",
                str(RESPONSE_PACKET_PATH),
                "--output-dir",
                "inputs/human_annotation_real/operator_intake_cli_check",
                "--assembly-manifest-output",
                "work_packets/test_human_annotation_response_intake_manifest.json",
            ]
            with redirect_stdout(stdout):
                exit_code = intake.main()
        finally:
            sys.argv = original_argv

        self.assertEqual(exit_code, 0)
        cli_result = json.loads(stdout.getvalue())
        self.assertFalse(cli_result["writes_canonical_packet"])
        self.assertEqual(
            cli_result["canonical_packet_not_written"],
            "inputs/human_annotation_results_v1.json",
        )
        self.assertFalse(cli_result["claim_boundary"]["supports_human_annotation_completed_claim"])
        self.assertFalse(
            cli_result["claim_boundary"]["supports_human_adjudication_completed_claim"]
        )
        self.assertTrue(cli_result["claim_boundary"]["candidate_packet_validator_passed"])
        self.assertNotIn("input_packet", cli_result["validation_report"])
        self.assertNotIn("claim_boundary", cli_result["validation_report"])
        self.assertFalse(
            any(key.startswith("supports_") for key in cli_result["validation_report"])
        )
        self.assertEqual(cli_result["operator_run_id"], "operator_intake_cli_check")
        self.assertEqual(
            cli_result["custody_receipt_artifact"],
            "inputs/human_annotation_real/operator_intake_cli_check/"
            "response_custody_receipt.json",
        )
        self.assertEqual(
            cli_result["custody_receipt_sha256"],
            validator.sha256_file(LIVE_CLI_BASE / "response_custody_receipt.json"),
        )
        self.assertTrue((LIVE_CLI_BASE / "manifest.json").exists())
        self.assertTrue((LIVE_CLI_BASE / "response_custody_receipt.json").exists())
        self.assertTrue(ASSEMBLY_MANIFEST.exists())
        packet = assembler.assemble_packet(
            **json.loads(ASSEMBLY_MANIFEST.read_text(encoding="utf-8"))
        )
        report = validator.build_report(packet)

        self.assertTrue(report["passed"])
        self.assert_canonical_unchanged()

    def test_main_rejects_promote_argument_before_writes(self) -> None:
        write_json(WORK_PACKET_PATH, work_packet_generator.build_work_packet())
        write_json(RESPONSE_PACKET_PATH, valid_response_packet())
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "human_annotation_response_intake.py",
                "--work-packet",
                str(WORK_PACKET_PATH),
                "--response-packet",
                str(RESPONSE_PACKET_PATH),
                "--output-dir",
                "inputs/human_annotation_real/operator_intake_cli_check",
                "--promote",
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    intake.main()
        finally:
            sys.argv = original_argv

        self.assertNotEqual(raised.exception.code, 0)
        self.assertFalse(LIVE_CLI_BASE.exists())
        self.assertFalse(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()

    def test_main_rejects_unsafe_output_paths_before_writes(self) -> None:
        write_json(WORK_PACKET_PATH, work_packet_generator.build_work_packet())
        write_json(RESPONSE_PACKET_PATH, valid_response_packet())
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "human_annotation_response_intake.py",
                "--work-packet",
                str(WORK_PACKET_PATH),
                "--response-packet",
                str(RESPONSE_PACKET_PATH),
                "--output-dir",
                "results/human_annotation_response_intake.json",
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaises(intake.IntakeError):
                    intake.main()
        finally:
            sys.argv = original_argv

        self.assertFalse(LIVE_CLI_BASE.exists())
        self.assert_canonical_unchanged()

    def test_main_rejects_real_root_assembly_manifest_output_before_writes(self) -> None:
        write_json(WORK_PACKET_PATH, work_packet_generator.build_work_packet())
        write_json(RESPONSE_PACKET_PATH, valid_response_packet())
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "human_annotation_response_intake.py",
                "--work-packet",
                str(WORK_PACKET_PATH),
                "--response-packet",
                str(RESPONSE_PACKET_PATH),
                "--output-dir",
                "inputs/human_annotation_real/operator_intake_cli_check",
                "--assembly-manifest-output",
                "inputs/human_annotation_real/operator_intake_cli_check/manifest.json",
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaises(intake.IntakeError):
                    intake.main()
        finally:
            sys.argv = original_argv

        self.assertFalse(LIVE_CLI_BASE.exists())
        self.assert_canonical_unchanged()


if __name__ == "__main__":
    unittest.main()
