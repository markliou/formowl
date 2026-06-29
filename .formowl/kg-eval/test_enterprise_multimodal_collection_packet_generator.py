#!/usr/bin/env python3
"""Tests for non-evidence enterprise multimodal collection packets."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import enterprise_multimodal_collection_packet_generator as generator
import enterprise_multimodal_packet_assembler as assembler
import enterprise_multimodal_validation_validator as validator
import kg_total_acceptance_suite as total_acceptance


OUTPUT = generator.WORK_PACKETS / "test_enterprise_multimodal_collection_packet_preview.json"
SYMLINK_OUTPUT_PARENT = generator.WORK_PACKETS / "enterprise_multimodal_real_alias"


def nested_keys(payload: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str):
                keys.add(key)
            keys.update(nested_keys(value))
    elif isinstance(payload, list):
        for value in payload:
            keys.update(nested_keys(value))
    return keys


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


class EnterpriseMultimodalCollectionPacketGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        if OUTPUT.exists():
            OUTPUT.unlink()
        if SYMLINK_OUTPUT_PARENT.exists() or SYMLINK_OUTPUT_PARENT.is_symlink():
            if SYMLINK_OUTPUT_PARENT.is_dir() and not SYMLINK_OUTPUT_PARENT.is_symlink():
                shutil.rmtree(SYMLINK_OUTPUT_PARENT)
            else:
                SYMLINK_OUTPUT_PARENT.unlink()
        self.canonical_before = (
            generator.CANONICAL_PACKET_PATH.read_bytes()
            if generator.CANONICAL_PACKET_PATH.exists()
            else None
        )
        self.real_root_before = sorted(
            path.relative_to(generator.REAL_ROOT) for path in generator.REAL_ROOT.rglob("*")
        )

    def tearDown(self) -> None:
        if OUTPUT.exists():
            OUTPUT.unlink()
        if SYMLINK_OUTPUT_PARENT.exists() or SYMLINK_OUTPUT_PARENT.is_symlink():
            if SYMLINK_OUTPUT_PARENT.is_dir() and not SYMLINK_OUTPUT_PARENT.is_symlink():
                shutil.rmtree(SYMLINK_OUTPUT_PARENT)
            else:
                SYMLINK_OUTPUT_PARENT.unlink()
        if self.canonical_before is None:
            if generator.CANONICAL_PACKET_PATH.exists():
                generator.CANONICAL_PACKET_PATH.unlink()
        else:
            generator.CANONICAL_PACKET_PATH.write_bytes(self.canonical_before)

    def assert_no_canonical_or_real_root_mutation(self) -> None:
        if self.canonical_before is None:
            self.assertFalse(generator.CANONICAL_PACKET_PATH.exists())
        else:
            self.assertEqual(generator.CANONICAL_PACKET_PATH.read_bytes(), self.canonical_before)
        self.assertEqual(
            sorted(
                path.relative_to(generator.REAL_ROOT) for path in generator.REAL_ROOT.rglob("*")
            ),
            self.real_root_before,
        )

    def test_default_packet_is_non_evidence_and_not_acceptance_shaped(self) -> None:
        packet = generator.build_work_packet()

        self.assertEqual(
            packet["work_packet_type"], "enterprise_multimodal_collection_packet_preview_v1"
        )
        self.assertEqual(packet["work_packet_state"], "operator_assignment_only")
        self.assertEqual(packet["evidence_state"], "non_evidence")
        self.assertFalse(packet["artifact_boundary"]["creates_real_source_rows"])
        self.assertFalse(packet["artifact_boundary"]["creates_real_validation_rows"])
        self.assertFalse(packet["artifact_boundary"]["creates_human_review_results"])
        self.assertFalse(packet["artifact_boundary"]["creates_business_review_results"])
        self.assertFalse(packet["artifact_boundary"]["creates_permission_probe_results"])
        self.assertFalse(packet["artifact_boundary"]["writes_assembly_manifest"])
        self.assertFalse(packet["artifact_boundary"]["writes_canonical_packet"])
        self.assertFalse(packet["artifact_boundary"]["touches_real_evidence_root"])
        self.assertFalse(packet["artifact_boundary"]["counts_as_acceptance_gate"])

        keys = nested_keys(packet)
        strings = nested_strings(packet)
        forbidden_keys = {
            "artifact_id",
            "evidence_kind",
            "claim_boundary",
            "recovered_after_tmp_loss",
            "pilot_manifest_artifact",
            "pilot_manifest_artifact_sha256",
            "validation_artifacts",
            "artifact_sha256",
            "human_adjudication_artifact",
            "human_adjudication_artifact_sha256",
            "business_decision_review_artifact",
            "business_decision_review_artifact_sha256",
            "permission_probe_artifact",
            "permission_probe_artifact_sha256",
            "validation_artifact_sha256s",
            "real_enterprise_pilot",
            "synthetic_or_demo",
            "real_enterprise_data",
            "text_proxy_only",
            "raw_path_exposed",
            "completed",
            "reviewer_type",
            "final_label",
            "passed",
            "ready",
            "overall_ready",
            "ready_for_acceptance",
        }
        self.assertTrue(forbidden_keys.isdisjoint(keys))
        self.assertTrue(
            {
                "enterprise_multimodal_validation_packet_v1",
                "real_enterprise_multimodal_validation",
                "passed",
                "ready",
                "overall_ready",
                "ready_for_acceptance",
            }.isdisjoint(strings)
        )
        self.assertFalse(any(key.startswith("supports_") for key in keys))
        self.assertFalse(any("supports_" in value for value in strings))
        self.assertFalse(any("--promote" in value for value in strings))
        self.assertFalse(any("--validate" in value for value in strings))
        self.assertFalse(any("--assembly-manifest" in value for value in strings))
        self.assertFalse(any("--evidence" in value for value in strings))
        self.assert_no_canonical_or_real_root_mutation()

    def test_collection_plan_covers_required_modalities_and_locators(self) -> None:
        packet = generator.build_work_packet()
        rows = packet["source_collection_plan"]["modality_rows"]
        rows_by_modality = {row["modality"]: row for row in rows}

        self.assertEqual(sorted(rows_by_modality), sorted(validator.REQUIRED_MODALITIES))
        self.assertEqual(
            rows_by_modality["spreadsheet"]["locator_fields"],
            ["sheet", "table_index", "row_index", "column_index", "cell_address"],
        )
        self.assertIn("message_id", rows_by_modality["mail"]["locator_fields"])
        self.assertIn("speaker", rows_by_modality["meeting_audio"]["locator_fields"])
        self.assertIn("bbox", rows_by_modality["video_ocr"]["locator_fields"])
        for row in rows:
            with self.subTest(modality=row["modality"]):
                row_without_hash = dict(row)
                row_hash = row_without_hash.pop("row_sha256")
                self.assertEqual(row_hash, generator.sha256_json(row_without_hash))
                self.assertTrue(row["collection_task_id"].startswith("collect_"))
                self.assertGreaterEqual(len(row["operator_checks"]), 3)

    def test_review_plan_binds_to_source_collection_rows_without_results(self) -> None:
        packet = generator.build_work_packet()
        source_hashes = {
            row["row_sha256"] for row in packet["source_collection_plan"]["modality_rows"]
        }
        review_rows = packet["review_collection_plan"]["review_rows"]

        self.assertEqual(len(review_rows), len(validator.REQUIRED_MODALITIES))
        for row in review_rows:
            with self.subTest(modality=row["modality"]):
                self.assertIn(row["source_collection_row_sha256"], source_hashes)
                self.assertIn("minimum_review_checks", row)
                self.assertNotIn("final_label", row)
                self.assertNotIn("completed", row)

    def test_packet_generation_is_deterministic(self) -> None:
        packet_a = generator.build_work_packet()
        packet_b = generator.build_work_packet()

        self.assertEqual(packet_a, packet_b)
        packet_hash = packet_a["work_packet_sha256"]
        packet_without_hash = dict(packet_a)
        packet_without_hash.pop("work_packet_sha256")
        self.assertEqual(packet_hash, generator.sha256_json(packet_without_hash))

    def test_generated_work_packet_alone_does_not_pass_validator(self) -> None:
        report = validator.build_report(generator.build_work_packet())

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal validation packet artifact id mismatch", report["blockers"]
        )
        self.assertIn("enterprise multimodal evidence kind mismatch", report["blockers"])
        self.assertIn("enterprise multimodal packet claim boundary missing", report["blockers"])
        self.assertIn("pilot_manifest_artifact missing or hash mismatch", report["blockers"])
        self.assertFalse(report["claim_boundary"]["supports_real_enterprise_multimodal_claim"])

    def test_generated_work_packet_is_rejected_by_real_packet_assembler(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "enterprise_multimodal_collection_packet_generator.py",
                "--output",
                "work_packets/test_enterprise_multimodal_collection_packet_preview.json",
            ]
            with redirect_stdout(StringIO()):
                generator.main()
        finally:
            sys.argv = original_argv

        with self.assertRaisesRegex(assembler.AssemblyError, "unsupported fields"):
            assembler.load_manifest(OUTPUT)
        self.assert_no_canonical_or_real_root_mutation()

    def test_main_does_not_change_authoritative_gate_state(self) -> None:
        validator_before = validator.build_report()
        gate_before = total_acceptance.multimodal_semantic_validation_gate()
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "enterprise_multimodal_collection_packet_generator.py",
                "--output",
                "work_packets/test_enterprise_multimodal_collection_packet_preview.json",
            ]
            with redirect_stdout(StringIO()):
                generator.main()
        finally:
            sys.argv = original_argv

        validator_after = validator.build_report()
        gate_after = total_acceptance.multimodal_semantic_validation_gate()

        self.assertEqual(validator_after["passed"], validator_before["passed"])
        self.assertEqual(validator_after["blockers"], validator_before["blockers"])
        self.assertEqual(gate_after["passed"], gate_before["passed"])
        self.assertEqual(gate_after["blockers"], gate_before["blockers"])
        self.assert_no_canonical_or_real_root_mutation()

    def test_main_writes_only_safe_work_packet_output(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "enterprise_multimodal_collection_packet_generator.py",
                "--output",
                "work_packets/test_enterprise_multimodal_collection_packet_preview.json",
            ]
            with redirect_stdout(StringIO()):
                exit_code = generator.main()
        finally:
            sys.argv = original_argv

        self.assertEqual(exit_code, 0)
        self.assertTrue(OUTPUT.exists())
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["work_packet_type"], "enterprise_multimodal_collection_packet_preview_v1"
        )
        self.assert_no_canonical_or_real_root_mutation()

    def test_cli_does_not_accept_evidence_validation_or_promotion_arguments(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "enterprise_multimodal_collection_packet_generator.py",
                "--promote",
                "--validate",
                "--assembly-manifest",
                "fake",
                "--evidence",
                "fake",
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    generator.main()
        finally:
            sys.argv = original_argv

        self.assertFalse(OUTPUT.exists())
        self.assert_no_canonical_or_real_root_mutation()

    def test_results_and_real_root_output_paths_are_rejected_before_partial_writes(self) -> None:
        target = generator.ROOT / "results" / "enterprise_multimodal_validation_validator.json"
        before = target.read_bytes() if target.exists() else None
        for output in (
            "results/enterprise_multimodal_validation_validator.json",
            "inputs/enterprise_multimodal_real/work_packet.json",
            "inputs/test_enterprise_multimodal_validator/work_packet.json",
            "templates/work_packet.json",
        ):
            with self.subTest(output=output):
                original_argv = sys.argv[:]
                try:
                    sys.argv = [
                        "enterprise_multimodal_collection_packet_generator.py",
                        "--output",
                        output,
                    ]
                    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                        with self.assertRaises(generator.WorkPacketError):
                            generator.main()
                finally:
                    sys.argv = original_argv

        if before is None:
            self.assertFalse(target.exists())
        else:
            self.assertEqual(target.read_bytes(), before)
        self.assertFalse(OUTPUT.exists())
        self.assert_no_canonical_or_real_root_mutation()

    def test_symlinked_work_packet_parent_to_real_root_is_rejected(self) -> None:
        SYMLINK_OUTPUT_PARENT.parent.mkdir(parents=True, exist_ok=True)
        SYMLINK_OUTPUT_PARENT.symlink_to(generator.REAL_ROOT, target_is_directory=True)
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "enterprise_multimodal_collection_packet_generator.py",
                "--output",
                "work_packets/enterprise_multimodal_real_alias/work_packet.json",
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaisesRegex(generator.WorkPacketError, "symlinks"):
                    generator.main()
        finally:
            sys.argv = original_argv

        self.assertFalse((generator.REAL_ROOT / "work_packet.json").exists())
        self.assert_no_canonical_or_real_root_mutation()

    def test_safe_output_path_rejects_real_roots_and_escapes(self) -> None:
        for path in (
            "inputs/enterprise_multimodal_real/work_packet.json",
            "inputs/test_enterprise_multimodal_validator/work_packet.json",
            "results/enterprise_multimodal_validation_validator.json",
            "../work_packets/escape.json",
            "/tmp/work_packet.json",
            "templates/work_packet.json",
        ):
            with self.subTest(path=path):
                with self.assertRaises(generator.WorkPacketError):
                    generator.safe_output_path(path)

    def test_rejects_missing_extra_or_raw_modality_requirements(self) -> None:
        missing = dict(generator.DEFAULT_MODALITY_REQUIREMENTS)
        missing.pop("video_ocr")
        with self.assertRaisesRegex(generator.WorkPacketError, "missing modalities"):
            generator.build_work_packet(modality_requirements=missing)

        extra = dict(generator.DEFAULT_MODALITY_REQUIREMENTS)
        extra["document"] = dict(generator.DEFAULT_MODALITY_REQUIREMENTS["spreadsheet"])
        with self.assertRaisesRegex(generator.WorkPacketError, "unsupported modalities"):
            generator.build_work_packet(modality_requirements=extra)

        raw = {key: dict(value) for key, value in generator.DEFAULT_MODALITY_REQUIREMENTS.items()}
        raw["spreadsheet"]["operator_checks"] = ["/mnt/nas/finance.xlsx"]
        with self.assertRaisesRegex(generator.WorkPacketError, "raw path"):
            generator.build_work_packet(modality_requirements=raw)


if __name__ == "__main__":
    unittest.main()
