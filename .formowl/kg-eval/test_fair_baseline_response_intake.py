#!/usr/bin/env python3
"""Tests for fair external-baseline response intake."""

from __future__ import annotations

from copy import deepcopy
import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import fair_baseline_response_intake as intake
import fair_baseline_run_work_packet_generator as work_packet_generator
import fair_external_baseline_packet_assembler as assembler
import fair_external_baseline_run_validator as validator
import test_fair_external_baseline_run_validator as validator_fixtures


OUTPUT_DIR = "inputs/fair_baseline_real/intake_test/fair_intake_run"
TEST_PARENT = validator.REAL_ARTIFACT_ROOT_PATH / "intake_test"
BASE = TEST_PARENT / "fair_intake_run"
ASSEMBLY_MANIFEST = intake.WORK_PACKETS / "test_fair_baseline_response_intake_manifest.json"
ASSEMBLY_MANIFEST_PARENT_FILE = intake.WORK_PACKETS / "test_fair_baseline_manifest_parent"
WORK_PACKET_PATH = intake.WORK_PACKETS / "test_fair_baseline_response_intake_work_packet.json"
RESPONSE_PACKET_PATH = intake.WORK_PACKETS / "test_fair_baseline_response_intake_response.json"
BROKEN_SYMLINK_TARGET = BASE / "microsoft_graphrag" / "package_lock.json"


def _read_artifact(path_value: str) -> dict:
    path = validator.safe_relative_artifact_path(path_value, allow_test_artifacts=True)
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def valid_response_packet() -> dict:
    packet = validator_fixtures.valid_packet()
    baseline_runs = []
    for run in packet["baseline_runs"]:
        row = {
            key: value
            for key, value in run.items()
            if key in assembler.RUN_SOURCE_ALLOWED_FIELDS
            and key not in validator.RUN_ARTIFACT_FIELDS
        }
        for artifact_field in validator.RUN_ARTIFACT_FIELDS:
            row[artifact_field] = _read_artifact(run[artifact_field])
        baseline_runs.append(row)
    return {
        "response_packet_type": "fair_baseline_response_intake_v1",
        "operator_run_id": "fair_intake_run",
        "run_environment": deepcopy(packet["run_environment"]),
        "source_lock_sha256": packet["source_lock_sha256"],
        "baseline_runs": baseline_runs,
        "human_answer_adjudication": deepcopy(packet["human_answer_adjudication"]),
        "graph_quality_validation": deepcopy(packet["graph_quality_validation"]),
        "permission_probes": deepcopy(packet["permission_probes"]),
    }


class FairBaselineResponseIntakeTest(unittest.TestCase):
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
            assembly_manifest_output="work_packets/test_fair_baseline_response_intake_manifest.json",
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
        self.assertEqual(custody_receipt["operator_run_id"], "fair_intake_run")
        self.assertEqual(
            custody_receipt["response_packet_sha256"],
            intake.sha256_artifact_payload(response),
        )
        self.assertEqual(custody_receipt["candidate_packet_sha256"], validator.sha256_json(packet))
        self.assertFalse(custody_receipt["writes_canonical_packet"])
        self.assertFalse(custody_receipt["counts_as_acceptance_gate"])
        self.assertFalse(
            custody_receipt["claim_boundary"]["supports_fair_external_baseline_comparison_claim"]
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
        self.assertEqual(len(custody_receipt["written_artifacts"]), 25)
        self.assertIn(
            {
                "field": "assembly_manifest",
                "path": str(ASSEMBLY_MANIFEST.relative_to(intake.ROOT)),
                "sha256": validator.sha256_file(ASSEMBLY_MANIFEST) or "",
            },
            custody_receipt["written_artifacts"],
        )
        self.assertTrue(result["claim_boundary"]["candidate_packet_validator_passed"])
        self.assertFalse(
            result["claim_boundary"]["supports_fair_external_baseline_comparison_claim"]
        )
        self.assertFalse(result["claim_boundary"]["supports_production_ready_claim"])
        self.assertEqual(
            sorted(path.name for path in BASE.iterdir() if path.is_file()),
            [
                "graph_quality_validation.json",
                "human_answer_adjudication.json",
                "permission_probes.json",
                "response_custody_receipt.json",
            ],
        )
        for baseline_id in validator.REQUIRED_BASELINES:
            self.assertEqual(
                sorted(path.name for path in (BASE / baseline_id).iterdir()),
                sorted(intake.RUN_ARTIFACT_FILENAMES.values()),
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

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_operator_run_id_output_dir_mismatch_before_writes(self) -> None:
        with self.assertRaisesRegex(intake.IntakeError, "final segment"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir="inputs/fair_baseline_real/fair_intake_mismatch",
            )

        self.assertFalse((validator.REAL_ARTIFACT_ROOT_PATH / "fair_intake_mismatch").exists())
        self.assert_canonical_unchanged()

    def test_default_rejects_sandbox_and_nested_output_dirs_before_writes(self) -> None:
        for output_dir, pattern in (
            (
                "inputs/fair_baseline_real/sandbox/fair_intake_run",
                "test or sandbox",
            ),
            (
                "inputs/fair_baseline_real/operator_group/fair_intake_run",
                "exactly inputs/fair_baseline_real/<operator_run_id>",
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
        path = BASE / "microsoft_graphrag" / "package_lock.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("existing\n", encoding="utf-8")

        with self.assertRaisesRegex(intake.IntakeError, "overwrite existing artifacts"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertEqual(path.read_text(encoding="utf-8"), "existing\n")
        shutil.rmtree(BASE, ignore_errors=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(BASE / "missing-target.json")

        with self.assertRaisesRegex(intake.IntakeError, "overwrite existing artifacts"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertTrue(path.is_symlink())
        self.assert_canonical_unchanged()

    def test_rejects_raw_internal_response_payload_before_writes(self) -> None:
        response = valid_response_packet()
        response["baseline_runs"][0]["package_lock_artifact"]["package_source_url"] = (
            "file:///mnt/nas/run.json"
        )

        with self.assertRaisesRegex(intake.IntakeError, "raw/internal artifact value"):
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
        response["claim_boundary"] = {"supports_fair_external_baseline_comparison_claim": True}

        with self.assertRaisesRegex(intake.IntakeError, "unsupported fields"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_unsupported_nested_response_wrapper_fields_before_writes(self) -> None:
        response = valid_response_packet()
        response["baseline_runs"][0]["notes"] = "operator-side note"
        with self.assertRaisesRegex(intake.IntakeError, "baseline run has unsupported fields"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )
        self.assertFalse(BASE.exists())

        response = valid_response_packet()
        response["human_answer_adjudication"]["reviewers"][0]["notes"] = "manual review"
        with self.assertRaisesRegex(
            intake.IntakeError,
            "human_answer_adjudication reviewer has unsupported fields",
        ):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )
        self.assertFalse(BASE.exists())

        response = valid_response_packet()
        response["permission_probes"][0]["notes"] = "manual probe"
        with self.assertRaisesRegex(intake.IntakeError, "permission_probe row has unsupported"):
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
        response["baseline_runs"][0]["package_lock_artifact"]["raw_path"] = "redacted"

        with self.assertRaisesRegex(intake.IntakeError, "raw/internal field"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_source_lock_mismatch_before_writes(self) -> None:
        response = valid_response_packet()
        response["source_lock_sha256"] = "0" * 64

        with self.assertRaisesRegex(intake.IntakeError, "source lock hash"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                assembly_manifest_output="work_packets/test_fair_baseline_response_intake_manifest.json",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assertFalse(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()

    def test_rejects_source_id_mismatch_before_writes(self) -> None:
        response = valid_response_packet()
        response["baseline_runs"][0]["source_ids"] = ["wrong_source"]

        with self.assertRaisesRegex(intake.IntakeError, "source ids"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_parent_file_collision_before_partial_writes(self) -> None:
        BASE.mkdir(parents=True, exist_ok=True)
        collision = BASE / "microsoft_graphrag"
        collision.write_text("not a directory\n", encoding="utf-8")

        with self.assertRaisesRegex(intake.IntakeError, "parent must be a directory"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertEqual(sorted(path.name for path in BASE.iterdir()), ["microsoft_graphrag"])
        self.assertEqual(collision.read_text(encoding="utf-8"), "not a directory\n")
        self.assert_canonical_unchanged()

    def test_rejects_manifest_parent_file_collision_before_partial_writes(self) -> None:
        ASSEMBLY_MANIFEST_PARENT_FILE.write_text("not a directory\n", encoding="utf-8")

        with self.assertRaisesRegex(intake.IntakeError, "parent must be a directory"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=valid_response_packet(),
                output_dir=OUTPUT_DIR,
                assembly_manifest_output="work_packets/test_fair_baseline_manifest_parent/manifest.json",
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
                        "work_packets/test_fair_baseline_response_intake_manifest.json"
                    ),
                    allow_test_artifacts=True,
                )
        finally:
            intake.assembler.assemble_packet = original_assemble_packet

        self.assertFalse(BASE.exists())
        self.assertFalse(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()

    def test_rolls_back_intake_created_files_on_validator_failure(self) -> None:
        original_validate_candidate = intake.assembler.validate_candidate

        def raise_after_writes(packet: object, *, allow_test_artifacts: bool = False) -> dict:
            del packet, allow_test_artifacts
            raise assembler.AssemblyError("simulated validator failure")

        try:
            intake.assembler.validate_candidate = raise_after_writes
            with self.assertRaisesRegex(intake.IntakeError, "simulated validator failure"):
                intake.build_intake_artifacts(
                    work_packet=work_packet_generator.build_work_packet(),
                    response_packet=valid_response_packet(),
                    output_dir=OUTPUT_DIR,
                    assembly_manifest_output=(
                        "work_packets/test_fair_baseline_response_intake_manifest.json"
                    ),
                    allow_test_artifacts=True,
                )
        finally:
            intake.assembler.validate_candidate = original_validate_candidate

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
            with self.assertRaisesRegex(intake.IntakeError, "intake output write failed"):
                intake.build_intake_artifacts(
                    work_packet=work_packet_generator.build_work_packet(),
                    response_packet=valid_response_packet(),
                    output_dir=OUTPUT_DIR,
                    assembly_manifest_output=(
                        "work_packets/test_fair_baseline_response_intake_manifest.json"
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
                "fair_baseline_response_intake.py",
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
                "fair_baseline_response_intake.py",
                "--work-packet",
                str(WORK_PACKET_PATH),
                "--response-packet",
                str(RESPONSE_PACKET_PATH),
                "--output-dir",
                OUTPUT_DIR,
                "--assembly-manifest-output",
                "work_packets/test_fair_baseline_response_intake_manifest.json",
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
            result["assembly_manifest_output"],
            "work_packets/test_fair_baseline_response_intake_manifest.json",
        )
        self.assertTrue(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()


if __name__ == "__main__":
    unittest.main()
