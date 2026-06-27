#!/usr/bin/env python3
"""Tests for enterprise multimodal response intake."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import enterprise_multimodal_collection_packet_generator as work_packet_generator
import enterprise_multimodal_packet_assembler as assembler
import enterprise_multimodal_response_intake as intake
import enterprise_multimodal_validation_validator as validator
import test_enterprise_multimodal_validation_validator as validator_fixtures


BASE = validator.REAL_ARTIFACT_ROOT_PATH / "enterprise_intake_run"
ASSEMBLY_MANIFEST = intake.WORK_PACKETS / "test_enterprise_multimodal_response_intake_manifest.json"
WORK_PACKET_PATH = intake.WORK_PACKETS / "test_enterprise_multimodal_collection_packet.json"
RESPONSE_PACKET_PATH = intake.WORK_PACKETS / "test_enterprise_multimodal_response_packet.json"
BROKEN_SYMLINK_TARGET = BASE / "pilot_manifest.json"


def _read_artifact(path_value: str) -> dict:
    path = validator.safe_relative_artifact_path(path_value, allow_test_artifacts=True)
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def valid_response_packet() -> dict:
    packet = validator_fixtures.valid_packet()
    return {
        "response_packet_type": "enterprise_multimodal_response_intake_v1",
        "operator_run_id": "enterprise_intake_run",
        "pilot_manifest_artifact": _read_artifact(packet["pilot_manifest_artifact"]),
        "validation_artifacts": [
            {
                "modality": ref["modality"],
                "artifact": _read_artifact(ref["artifact"]),
            }
            for ref in packet["validation_artifacts"]
        ],
        "human_adjudication_artifact": _read_artifact(packet["human_adjudication_artifact"]),
        "business_decision_review_artifact": _read_artifact(
            packet["business_decision_review_artifact"]
        ),
        "permission_probe_artifact": _read_artifact(packet["permission_probe_artifact"]),
    }


class EnterpriseMultimodalResponseIntakeTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator_fixtures.BASE, ignore_errors=True)
        BROKEN_SYMLINK_TARGET.unlink(missing_ok=True)
        for path in (ASSEMBLY_MANIFEST, WORK_PACKET_PATH, RESPONSE_PACKET_PATH):
            path.unlink(missing_ok=True)
        self.canonical_before = (
            assembler.CANONICAL_PACKET_PATH.read_bytes()
            if assembler.CANONICAL_PACKET_PATH.exists()
            else None
        )

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator_fixtures.BASE, ignore_errors=True)
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
            output_dir="inputs/enterprise_multimodal_real/enterprise_intake_run",
            assembly_manifest_output=(
                "work_packets/test_enterprise_multimodal_response_intake_manifest.json"
            ),
            allow_test_artifacts=True,
        )

        self.assertFalse(result["writes_canonical_packet"])
        self.assertTrue(result["validation_report"]["candidate_packet_validator_passed"])
        self.assertEqual(result["validation_report"]["blocker_count"], 0)
        self.assertFalse(result["validation_report"]["authoritative_validator_report_embedded"])
        self.assertFalse(result["validation_report"]["counts_as_acceptance_gate"])
        self.assertNotIn("input_packet", result["validation_report"])
        self.assertNotIn("claim_boundary", result["validation_report"])
        self.assertTrue(ASSEMBLY_MANIFEST.exists())
        assembly_manifest = json.loads(ASSEMBLY_MANIFEST.read_text(encoding="utf-8"))
        packet = assembler.assemble_packet(**assembly_manifest, allow_test_artifacts=True)
        report = validator.build_report(packet, allow_test_artifacts=True)

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(result["candidate_packet_sha256"], validator.sha256_json(packet))
        self.assertEqual(result["response_packet_sha256"], intake.sha256_artifact_payload(response))
        self.assertEqual(
            result["custody_receipt_artifact"],
            "inputs/enterprise_multimodal_real/enterprise_intake_run/response_custody_receipt.json",
        )
        custody_receipt = json.loads(
            (BASE / "response_custody_receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(custody_receipt["operator_run_id"], "enterprise_intake_run")
        self.assertEqual(
            custody_receipt["response_packet_sha256"],
            intake.sha256_artifact_payload(response),
        )
        self.assertEqual(custody_receipt["candidate_packet_sha256"], validator.sha256_json(packet))
        self.assertFalse(custody_receipt["writes_canonical_packet"])
        self.assertFalse(custody_receipt["counts_as_acceptance_gate"])
        self.assertFalse(
            custody_receipt["claim_boundary"]["supports_real_enterprise_multimodal_claim"]
        )
        self.assertEqual(
            result["custody_receipt_sha256"],
            validator.sha256_file(BASE / "response_custody_receipt.json"),
        )
        self.assertEqual(len(custody_receipt["written_artifacts"]), 8)
        self.assertEqual(
            sorted(row["path"] for row in custody_receipt["written_artifacts"]),
            sorted(
                f"inputs/enterprise_multimodal_real/enterprise_intake_run/{name}"
                for name in (
                    "business_decision_review.json",
                    "human_adjudication.json",
                    "permission_probe.json",
                    "pilot_manifest.json",
                    "validation_mail.json",
                    "validation_meeting_audio.json",
                    "validation_spreadsheet.json",
                    "validation_video_ocr.json",
                )
            ),
        )
        self.assertTrue(result["claim_boundary"]["candidate_packet_validator_passed"])
        self.assertFalse(result["claim_boundary"]["supports_real_enterprise_multimodal_claim"])
        self.assertFalse(result["claim_boundary"]["supports_production_ready_claim"])
        self.assertEqual(
            sorted(path.name for path in BASE.iterdir()),
            [
                "business_decision_review.json",
                "human_adjudication.json",
                "permission_probe.json",
                "pilot_manifest.json",
                "response_custody_receipt.json",
                "validation_mail.json",
                "validation_meeting_audio.json",
                "validation_spreadsheet.json",
                "validation_video_ocr.json",
            ],
        )
        self.assert_canonical_unchanged()

    def test_rejects_work_packet_boundary_mismatch_before_writes(self) -> None:
        work_packet = work_packet_generator.build_work_packet()
        work_packet["artifact_boundary"]["counts_as_acceptance_gate"] = True

        with self.assertRaisesRegex(intake.IntakeError, "counts_as_acceptance_gate"):
            intake.build_intake_artifacts(
                work_packet=work_packet,
                response_packet=valid_response_packet(),
                output_dir="inputs/enterprise_multimodal_real/enterprise_intake_run",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_default_rejects_test_output_dir_before_writes(self) -> None:
        with self.assertRaisesRegex(intake.IntakeError, "test or sandbox"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir="inputs/enterprise_multimodal_real/intake_test",
            )

        self.assertFalse((validator.REAL_ARTIFACT_ROOT_PATH / "intake_test").exists())
        self.assert_canonical_unchanged()

    def test_rejects_output_overwrite_and_broken_symlink_before_partial_writes(self) -> None:
        BASE.mkdir(parents=True, exist_ok=True)
        (BASE / "pilot_manifest.json").write_text("existing\n", encoding="utf-8")

        with self.assertRaisesRegex(intake.IntakeError, "overwrite existing artifacts"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir="inputs/enterprise_multimodal_real/enterprise_intake_run",
                allow_test_artifacts=True,
            )

        self.assertEqual((BASE / "pilot_manifest.json").read_text(encoding="utf-8"), "existing\n")
        shutil.rmtree(BASE, ignore_errors=True)
        BASE.mkdir(parents=True, exist_ok=True)
        (BASE / "pilot_manifest.json").symlink_to(BASE / "missing-target.json")

        with self.assertRaisesRegex(intake.IntakeError, "overwrite existing artifacts"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir="inputs/enterprise_multimodal_real/enterprise_intake_run",
                allow_test_artifacts=True,
            )

        self.assertTrue((BASE / "pilot_manifest.json").is_symlink())
        self.assert_canonical_unchanged()

    def test_rejects_custody_receipt_overwrite_before_partial_writes(self) -> None:
        BASE.mkdir(parents=True, exist_ok=True)
        (BASE / "response_custody_receipt.json").write_text("existing\n", encoding="utf-8")

        with self.assertRaisesRegex(intake.IntakeError, "overwrite existing artifacts"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir="inputs/enterprise_multimodal_real/enterprise_intake_run",
                allow_test_artifacts=True,
            )

        self.assertEqual(
            sorted(path.name for path in BASE.iterdir()),
            ["response_custody_receipt.json"],
        )
        self.assertEqual((BASE / "response_custody_receipt.json").read_text(), "existing\n")
        self.assert_canonical_unchanged()

    def test_rejects_raw_internal_response_payload_before_writes(self) -> None:
        response = valid_response_packet()
        response["pilot_manifest_artifact"]["source_artifacts"][0]["raw_path"] = "/mnt/nas/x.xlsx"

        with self.assertRaisesRegex(intake.IntakeError, "raw/internal artifact value"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir="inputs/enterprise_multimodal_real/enterprise_intake_run",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_cli_rejects_promotion_arguments_without_writes(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "enterprise_multimodal_response_intake.py",
                "--promote",
                "--work-packet",
                str(WORK_PACKET_PATH),
                "--response-packet",
                str(RESPONSE_PACKET_PATH),
                "--output-dir",
                "inputs/enterprise_multimodal_real/enterprise_intake_run",
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    intake.main()
        finally:
            sys.argv = original_argv

        self.assertNotEqual(raised.exception.code, 0)
        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_cli_writes_candidate_artifacts_and_manifest_only(self) -> None:
        WORK_PACKET_PATH.write_text(
            json.dumps(work_packet_generator.build_work_packet(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        response = valid_response_packet()
        RESPONSE_PACKET_PATH.write_text(
            json.dumps(response, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "enterprise_multimodal_response_intake.py",
                "--work-packet",
                str(WORK_PACKET_PATH),
                "--response-packet",
                str(RESPONSE_PACKET_PATH),
                "--output-dir",
                "inputs/enterprise_multimodal_real/enterprise_intake_run",
                "--assembly-manifest-output",
                "work_packets/test_enterprise_multimodal_response_intake_manifest.json",
            ]
            with redirect_stdout(StringIO()) as output:
                exit_code = intake.main()
        finally:
            sys.argv = original_argv

        self.assertEqual(exit_code, 0)
        result = json.loads(output.getvalue())
        self.assertFalse(result["writes_canonical_packet"])
        self.assertEqual(
            result["custody_receipt_artifact"],
            "inputs/enterprise_multimodal_real/enterprise_intake_run/response_custody_receipt.json",
        )
        self.assertEqual(
            result["custody_receipt_sha256"],
            validator.sha256_file(BASE / "response_custody_receipt.json"),
        )
        self.assertTrue(BASE.exists())
        self.assertTrue(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()


if __name__ == "__main__":
    unittest.main()
