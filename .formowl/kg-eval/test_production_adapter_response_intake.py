#!/usr/bin/env python3
"""Tests for production adapter response intake."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import production_adapter_collection_packet_generator as work_packet_generator
import production_adapter_packet_assembler as assembler
import production_adapter_path_validator as validator
import production_adapter_response_intake as intake
import test_production_adapter_path_validator as validator_fixtures


OUTPUT_DIR = "inputs/production_adapter_real/intake_test/production_adapter_intake_run"
TEST_PARENT = validator.REAL_ARTIFACT_ROOT_PATH / "intake_test"
BASE = TEST_PARENT / "production_adapter_intake_run"
ASSEMBLY_MANIFEST = intake.WORK_PACKETS / "test_production_adapter_response_intake_manifest.json"
ASSEMBLY_MANIFEST_PARENT_FILE = intake.WORK_PACKETS / "test_production_adapter_manifest_parent"
WORK_PACKET_PATH = intake.WORK_PACKETS / "test_production_adapter_response_intake_work_packet.json"
RESPONSE_PACKET_PATH = intake.WORK_PACKETS / "test_production_adapter_response_intake_response.json"
BROKEN_SYMLINK_TARGET = BASE / "deployment_manifest.json"


def _read_artifact(path_value: str) -> dict:
    path = validator.safe_relative_artifact_path(path_value, allow_test_artifacts=True)
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def valid_response_packet() -> dict:
    packet = validator_fixtures.valid_packet()
    return {
        "response_packet_type": "production_adapter_response_intake_v1",
        "operator_run_id": "production_adapter_intake_run",
        "deployment_manifest_artifact": _read_artifact(packet["deployment_manifest_artifact"]),
        "adapter_artifacts": [
            {
                "component_id": ref["component_id"],
                "artifact": _read_artifact(ref["artifact"]),
            }
            for ref in packet["adapter_artifacts"]
        ],
        "human_false_merge_label_artifact": _read_artifact(
            packet["human_false_merge_label_artifact"]
        ),
        "audit_trail_artifact": _read_artifact(packet["audit_trail_artifact"]),
        "permission_probe_artifact": _read_artifact(packet["permission_probe_artifact"]),
        "rollback_smoke_artifact": _read_artifact(packet["rollback_smoke_artifact"]),
    }


class ProductionAdapterResponseIntakeTest(unittest.TestCase):
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
                "work_packets/test_production_adapter_response_intake_manifest.json"
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
        self.assertEqual(custody_receipt["operator_run_id"], "production_adapter_intake_run")
        self.assertEqual(
            custody_receipt["response_packet_sha256"],
            intake.sha256_artifact_payload(response),
        )
        self.assertEqual(custody_receipt["candidate_packet_sha256"], validator.sha256_json(packet))
        self.assertFalse(custody_receipt["writes_canonical_packet"])
        self.assertFalse(custody_receipt["counts_as_acceptance_gate"])
        self.assertFalse(
            custody_receipt["claim_boundary"]["supports_production_adapter_paths_claim"]
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
        self.assertEqual(len(custody_receipt["written_artifacts"]), 13)
        self.assertIn(
            {
                "field": "assembly_manifest",
                "path": str(ASSEMBLY_MANIFEST.relative_to(intake.ROOT)),
                "sha256": validator.sha256_file(ASSEMBLY_MANIFEST) or "",
            },
            custody_receipt["written_artifacts"],
        )
        self.assertTrue(result["claim_boundary"]["candidate_packet_validator_passed"])
        self.assertFalse(result["claim_boundary"]["supports_production_adapter_paths_claim"])
        self.assertFalse(result["claim_boundary"]["supports_full_product_production_ready_claim"])
        self.assertEqual(
            sorted(path.name for path in BASE.iterdir() if path.is_file()),
            sorted(
                [
                    "audit_trail.json",
                    "deployment_manifest.json",
                    "false_merge_labels.json",
                    "permission_probe.json",
                    "response_custody_receipt.json",
                    "rollback_smoke.json",
                    *(
                        f"adapter_{component_id}.json"
                        for component_id in validator.REQUIRED_COMPONENTS
                    ),
                ]
            ),
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

    def test_default_rejects_sandbox_and_nested_output_dirs_before_writes(self) -> None:
        for output_dir, pattern in (
            (
                "inputs/production_adapter_real/sandbox/production_adapter_intake_run",
                "test or sandbox",
            ),
            (
                "inputs/production_adapter_real/operator_group/production_adapter_intake_run",
                "exactly inputs/production_adapter_real/<operator_run_id>",
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
        path = BASE / "deployment_manifest.json"
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
        response["deployment_manifest_artifact"]["raw_path"] = "/mnt/nas/deploy.json"

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
        response["raw_path"] = "/mnt/nas/deploy.json"

        with self.assertRaisesRegex(intake.IntakeError, "unsupported fields"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_duplicate_adapter_component_before_writes(self) -> None:
        response = valid_response_packet()
        response["adapter_artifacts"][0] = dict(response["adapter_artifacts"][1])

        with self.assertRaisesRegex(intake.IntakeError, "distinct by component_id"):
            intake.build_intake_artifacts(
                work_packet=work_packet_generator.build_work_packet(),
                response_packet=response,
                output_dir=OUTPUT_DIR,
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assert_canonical_unchanged()

    def test_rejects_missing_adapter_component_before_writes(self) -> None:
        response = valid_response_packet()
        response["adapter_artifacts"] = response["adapter_artifacts"][:-1]

        with self.assertRaisesRegex(intake.IntakeError, "missing components"):
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
                assembly_manifest_output="work_packets/test_production_adapter_manifest_parent/manifest.json",
                allow_test_artifacts=True,
            )

        self.assertFalse(BASE.exists())
        self.assertEqual(
            ASSEMBLY_MANIFEST_PARENT_FILE.read_text(encoding="utf-8"), "not a directory\n"
        )
        self.assert_canonical_unchanged()

    def test_cli_rejects_promotion_arguments_without_writes(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "production_adapter_response_intake.py",
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
                "production_adapter_response_intake.py",
                "--work-packet",
                str(WORK_PACKET_PATH),
                "--response-packet",
                str(RESPONSE_PACKET_PATH),
                "--output-dir",
                OUTPUT_DIR,
                "--assembly-manifest-output",
                "work_packets/test_production_adapter_response_intake_manifest.json",
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
            "work_packets/test_production_adapter_response_intake_manifest.json",
        )
        self.assertTrue(ASSEMBLY_MANIFEST.exists())
        self.assert_canonical_unchanged()


if __name__ == "__main__":
    unittest.main()
