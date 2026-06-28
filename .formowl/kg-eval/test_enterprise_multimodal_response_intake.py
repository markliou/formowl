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


OUTPUT_DIR = "inputs/enterprise_multimodal_real/intake_test/enterprise_intake_run"
TEST_PARENT = validator.REAL_ARTIFACT_ROOT_PATH / "intake_test"
BASE = TEST_PARENT / "enterprise_intake_run"
ASSEMBLY_MANIFEST = intake.WORK_PACKETS / "test_enterprise_multimodal_response_intake_manifest.json"
ASSEMBLY_MANIFEST_PARENT_FILE = intake.WORK_PACKETS / "test_enterprise_multimodal_manifest_parent"
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
        shutil.rmtree(TEST_PARENT, ignore_errors=True)
        shutil.rmtree(validator_fixtures.BASE, ignore_errors=True)
        BROKEN_SYMLINK_TARGET.unlink(missing_ok=True)
        ASSEMBLY_MANIFEST_PARENT_FILE.unlink(missing_ok=True)
        for path in (ASSEMBLY_MANIFEST, WORK_PACKET_PATH, RESPONSE_PACKET_PATH):
            path.unlink(missing_ok=True)
        self.canonical_before = (
            assembler.CANONICAL_PACKET_PATH.read_bytes()
            if assembler.CANONICAL_PACKET_PATH.exists()
            else None
        )

    def tearDown(self) -> None:
        shutil.rmtree(TEST_PARENT, ignore_errors=True)
        shutil.rmtree(validator_fixtures.BASE, ignore_errors=True)
        BROKEN_SYMLINK_TARGET.unlink(missing_ok=True)
        ASSEMBLY_MANIFEST_PARENT_FILE.unlink(missing_ok=True)
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
            output_dir=OUTPUT_DIR,
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
            f"{OUTPUT_DIR}/response_custody_receipt.json",
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
        self.assertEqual(
            custody_receipt["assembly_manifest_output"],
            str(ASSEMBLY_MANIFEST.relative_to(intake.ROOT)),
        )
        self.assertEqual(
            custody_receipt["assembly_manifest_sha256"],
            validator.sha256_file(ASSEMBLY_MANIFEST),
        )
        self.assertEqual(
            result["assembly_manifest_sha256"], validator.sha256_file(ASSEMBLY_MANIFEST)
        )
        self.assertEqual(len(custody_receipt["written_artifacts"]), 9)
        self.assertIn(
            {
                "field": "assembly_manifest",
                "path": str(ASSEMBLY_MANIFEST.relative_to(intake.ROOT)),
                "sha256": validator.sha256_file(ASSEMBLY_MANIFEST) or "",
            },
            custody_receipt["written_artifacts"],
        )
        self.assertEqual(
            sorted(row["path"] for row in custody_receipt["written_artifacts"]),
            sorted(
                f"{OUTPUT_DIR}/{name}"
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
            )
            + [str(ASSEMBLY_MANIFEST.relative_to(intake.ROOT))],
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
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_default_rejects_test_output_dir_before_writes(self) -> None:
        with self.assertRaisesRegex(intake.IntakeError, "test or sandbox"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir=OUTPUT_DIR,
            )

        self.assertFalse((validator.REAL_ARTIFACT_ROOT_PATH / "intake_test").exists())
        self.assert_canonical_unchanged()

    def test_default_rejects_sandbox_and_nested_output_dirs_before_writes(self) -> None:
        for output_dir, pattern in (
            (
                "inputs/enterprise_multimodal_real/sandbox/enterprise_intake_run",
                "test or sandbox",
            ),
            (
                "inputs/enterprise_multimodal_real/operator_group/enterprise_intake_run",
                "exactly inputs/enterprise_multimodal_real/<operator_run_id>",
            ),
        ):
            with self.subTest(output_dir=output_dir):
                with self.assertRaisesRegex(intake.IntakeError, pattern):
                    intake.build_intake_artifacts(
                        work_packet=work_packet_generator.build_work_packet(),
                        response_packet=valid_response_packet(),
                        output_dir=output_dir,
                    )

        self.assertFalse((validator.REAL_ARTIFACT_ROOT_PATH / "sandbox").exists())
        self.assertFalse((validator.REAL_ARTIFACT_ROOT_PATH / "operator_group").exists())
        self.assert_canonical_unchanged()

    def test_rejects_output_overwrite_and_broken_symlink_before_partial_writes(self) -> None:
        BASE.mkdir(parents=True, exist_ok=True)
        (BASE / "pilot_manifest.json").write_text("existing\n", encoding="utf-8")

        with self.assertRaisesRegex(intake.IntakeError, "overwrite existing artifacts"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir=OUTPUT_DIR,
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
                output_dir=OUTPUT_DIR,
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
                output_dir=OUTPUT_DIR,
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
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_raw_internal_response_field_before_writes(self) -> None:
        response = valid_response_packet()
        response["pilot_manifest_artifact"]["source_artifacts"][0]["raw_path"] = "redacted"

        with self.assertRaisesRegex(intake.IntakeError, "raw/internal artifact field"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_validation_raw_internal_response_field_before_writes(self) -> None:
        response = valid_response_packet()
        response["validation_artifacts"][0]["artifact"]["worker_scratch_path"] = "redacted"

        with self.assertRaisesRegex(intake.IntakeError, "raw/internal artifact field"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_backend_connection_field_names_with_benign_values_before_writes(
        self,
    ) -> None:
        response = valid_response_packet()
        response["permission_probe_artifact"]["backend_connection_string"] = "redacted"

        with self.assertRaisesRegex(intake.IntakeError, "raw/internal artifact field"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_top_level_unsupported_response_fields_before_writes(self) -> None:
        response = valid_response_packet()
        response["raw_path"] = "/mnt/nas/multimodal.json"

        with self.assertRaisesRegex(intake.IntakeError, "unsupported fields"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_parent_file_collision_before_partial_writes(self) -> None:
        TEST_PARENT.mkdir(parents=True, exist_ok=True)
        BASE.write_text("not a directory\n", encoding="utf-8")

        with self.assertRaisesRegex(intake.IntakeError, "parent must be a directory"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertEqual(BASE.read_text(encoding="utf-8"), "not a directory\n")
        self.assert_canonical_unchanged()

    def test_rejects_manifest_parent_file_collision_before_partial_writes(self) -> None:
        ASSEMBLY_MANIFEST_PARENT_FILE.write_text("not a directory\n", encoding="utf-8")

        with self.assertRaisesRegex(intake.IntakeError, "parent must be a directory"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir=OUTPUT_DIR,
                assembly_manifest_output="work_packets/test_enterprise_multimodal_manifest_parent/manifest.json",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assertEqual(
            ASSEMBLY_MANIFEST_PARENT_FILE.read_text(encoding="utf-8"), "not a directory\n"
        )
        self.assert_canonical_unchanged()

    def test_rolls_back_intake_created_files_on_assembler_failure(self) -> None:
        original_assemble_packet = intake.assembler.assemble_packet

        def raise_after_writes(**_: object) -> dict:
            raise assembler.AssemblyError("simulated assembler failure")

        try:
            intake.assembler.assemble_packet = raise_after_writes
            with self.assertRaisesRegex(intake.IntakeError, "simulated assembler failure"):
                intake.build_intake_artifacts(
                    work_packet=work_packet_generator.build_work_packet(),
                    response_packet=valid_response_packet(),
                    output_dir=OUTPUT_DIR,
                    assembly_manifest_output=(
                        "work_packets/test_enterprise_multimodal_response_intake_manifest.json"
                    ),
                    allow_test_artifacts=True,
                )
        finally:
            intake.assembler.assemble_packet = original_assemble_packet

        self.assertFalse(BASE.exists())
        self.assertFalse(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()

    def test_rolls_back_intake_created_files_on_write_oserror(self) -> None:
        original_write_json = intake._write_json
        write_count = 0

        def fail_second_write(path: object, payload: object) -> None:
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                raise OSError("simulated write failure")
            original_write_json(path, payload)

        try:
            intake._write_json = fail_second_write
            with self.assertRaisesRegex(intake.IntakeError, "simulated write failure"):
                intake.build_intake_artifacts(
                    work_packet=work_packet_generator.build_work_packet(),
                    response_packet=valid_response_packet(),
                    output_dir=OUTPUT_DIR,
                    assembly_manifest_output=(
                        "work_packets/test_enterprise_multimodal_response_intake_manifest.json"
                    ),
                    allow_test_artifacts=True,
                )
        finally:
            intake._write_json = original_write_json

        self.assertFalse(BASE.exists())
        self.assertFalse(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()

    def test_rolls_back_created_files_on_custody_receipt_hash_oserror(self) -> None:
        original_sha256_file = intake.validator.sha256_file

        def fail_manifest_hash(path: object) -> str | None:
            if path == ASSEMBLY_MANIFEST:
                raise OSError("simulated custody hash failure")
            return original_sha256_file(path)

        try:
            intake.validator.sha256_file = fail_manifest_hash
            with self.assertRaisesRegex(
                intake.IntakeError,
                "simulated custody hash failure",
            ):
                intake.build_intake_artifacts(
                    work_packet=work_packet_generator.build_work_packet(),
                    response_packet=valid_response_packet(),
                    output_dir=OUTPUT_DIR,
                    assembly_manifest_output=(
                        "work_packets/test_enterprise_multimodal_response_intake_manifest.json"
                    ),
                    allow_test_artifacts=True,
                )
        finally:
            intake.validator.sha256_file = original_sha256_file

        self.assertFalse(BASE.exists())
        self.assertFalse(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()

    def test_rolls_back_partial_file_created_by_after_open_write_failure(self) -> None:
        original_artifact_json_text = intake._artifact_json_text
        write_count = 0

        def fail_second_serialization(payload: object) -> str:
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                raise OSError("simulated after-open write failure")
            return original_artifact_json_text(payload)

        try:
            intake._artifact_json_text = fail_second_serialization
            with self.assertRaisesRegex(
                intake.IntakeError,
                "intake output write failed",
            ):
                intake.build_intake_artifacts(
                    work_packet=work_packet_generator.build_work_packet(),
                    response_packet=valid_response_packet(),
                    output_dir=OUTPUT_DIR,
                    assembly_manifest_output=(
                        "work_packets/test_enterprise_multimodal_response_intake_manifest.json"
                    ),
                    allow_test_artifacts=True,
                )
        finally:
            intake._artifact_json_text = original_artifact_json_text

        self.assertFalse(BASE.exists())
        self.assertFalse(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()

    def test_rolls_back_partial_file_created_by_after_open_serialization_failure(self) -> None:
        original_artifact_json_text = intake._artifact_json_text
        write_count = 0

        def fail_second_serialization(payload: object) -> str:
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                raise TypeError("simulated serialization failure")
            return original_artifact_json_text(payload)

        try:
            intake._artifact_json_text = fail_second_serialization
            with self.assertRaisesRegex(
                intake.IntakeError,
                "intake output write failed",
            ):
                intake.build_intake_artifacts(
                    work_packet=work_packet_generator.build_work_packet(),
                    response_packet=valid_response_packet(),
                    output_dir=OUTPUT_DIR,
                    assembly_manifest_output=(
                        "work_packets/test_enterprise_multimodal_response_intake_manifest.json"
                    ),
                    allow_test_artifacts=True,
                )
        finally:
            intake._artifact_json_text = original_artifact_json_text

        self.assertFalse(BASE.exists())
        self.assertFalse(ASSEMBLY_MANIFEST.exists())
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
                OUTPUT_DIR,
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
                OUTPUT_DIR,
                "--assembly-manifest-output",
                "work_packets/test_enterprise_multimodal_response_intake_manifest.json",
                "--allow-test-artifacts",
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
            f"{OUTPUT_DIR}/response_custody_receipt.json",
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
