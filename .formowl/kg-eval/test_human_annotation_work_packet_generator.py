#!/usr/bin/env python3
"""Tests for non-evidence human annotation work-packet generation."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import human_annotation_adjudication_validator as validator
import human_annotation_work_packet_generator as generator
import kg_total_acceptance_suite as total_acceptance


BASE = generator.ROOT / "inputs" / "test_human_annotation_work_packet_generator"
OUTPUT = generator.ROOT / "work_packets" / "test_human_annotation_work_packet_preview.json"
SYMLINK_OUTPUT_PARENT = generator.WORK_PACKETS / "human_annotation_real_alias"


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


def write_artifact(relative_name: str, payload: object) -> tuple[str, str]:
    path = BASE / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f"inputs/test_human_annotation_work_packet_generator/{relative_name}", validator.sha256_file(path) or ""


class HumanAnnotationWorkPacketGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
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
            path.relative_to(generator.REAL_ROOT)
            for path in generator.REAL_ROOT.rglob("*")
        )

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
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
            sorted(path.relative_to(generator.REAL_ROOT) for path in generator.REAL_ROOT.rglob("*")),
            self.real_root_before,
        )

    def test_default_work_packet_is_non_evidence_and_not_acceptance_shaped(self) -> None:
        packet = generator.build_work_packet()

        self.assertEqual(packet["work_packet_type"], "human_annotation_work_packet_preview_v1")
        self.assertEqual(packet["work_packet_state"], "operator_assignment_only")
        self.assertEqual(packet["evidence_state"], "non_evidence")
        self.assertFalse(packet["artifact_boundary"]["accepts_human_responses"])
        self.assertFalse(packet["artifact_boundary"]["creates_downstream_evidence_artifacts"])
        self.assertFalse(packet["artifact_boundary"]["writes_canonical_packet"])
        self.assertFalse(packet["artifact_boundary"]["touches_real_evidence_root"])
        self.assertFalse(packet["artifact_boundary"]["counts_as_acceptance_gate"])
        self.assertNotIn("claim_boundary", packet)
        keys = nested_keys(packet)
        strings = nested_strings(packet)
        forbidden_tokens = {
            "label",
            "final_label",
            "gold_label",
            "consensus_label",
            "sealed",
            "submission_set_sha256",
            "sealed_disagreement_set",
            "custody_receipt_sha256",
            "passed",
            "ready",
            "overall_ready",
            "ready_for_acceptance",
            "evidence_kind",
        }
        self.assertTrue(forbidden_tokens.isdisjoint(keys))
        self.assertTrue(forbidden_tokens.isdisjoint(strings))
        self.assertFalse(any(key.startswith("supports_") for key in keys))
        self.assertFalse(any("supports_" in value for value in strings))
        self.assertFalse(any("--promote" in value for value in strings))
        self.assertNotEqual(packet.get("artifact_id"), "human_annotation_results_v1")
        self.assert_no_canonical_or_real_root_mutation()

    def test_manifest_and_work_order_rows_match_validator_contracts(self) -> None:
        packet = generator.build_work_packet()
        manifest = packet["manifest_artifact"]
        work_orders = packet["work_orders_artifact"]
        blockers: list[str] = []

        manifest_by_item, manifest_rows = validator._validate_manifest(manifest, blockers)
        work_order_by_id = validator._validate_work_orders(work_orders, manifest_by_item, blockers)

        self.assertEqual(blockers, [])
        self.assertEqual(manifest["artifact_type"], "human_annotation_manifest_v1")
        self.assertEqual(manifest["item_count"], len(generator.DEFAULT_ITEMS))
        self.assertEqual(len(manifest_rows), len(generator.DEFAULT_ITEMS))
        self.assertEqual(work_orders["artifact_type"], "human_annotation_work_orders_v1")
        self.assertEqual(set(work_orders), {"artifact_type", "work_orders"})
        self.assertEqual(len(work_orders["work_orders"]), len(generator.DEFAULT_ITEMS) * 3)
        self.assertEqual(len(work_order_by_id), len(generator.DEFAULT_ITEMS) * 3)
        for row in manifest_rows:
            self.assertEqual(
                set(row),
                {"item_id", "task_id", "source_ref", "source_observation_id", "row_sha256"},
            )
            self.assertEqual(row["source_ref"], f"formowl://observation/{row['source_observation_id']}")
            self.assertEqual(row["row_sha256"], validator.row_hash(row))
        for row in work_orders["work_orders"]:
            self.assertEqual(row["row_sha256"], validator.row_hash(row))
            self.assertIn(row["role"], {"first_pass", "adjudicator"})

    def test_packet_generation_is_deterministic(self) -> None:
        packet_a = generator.build_work_packet()
        packet_b = generator.build_work_packet()

        self.assertEqual(packet_a, packet_b)
        packet_hash = packet_a["work_packet_sha256"]
        packet_without_hash = dict(packet_a)
        packet_without_hash.pop("work_packet_sha256")
        self.assertEqual(packet_hash, generator.sha256_json(packet_without_hash))

    def test_generated_manifest_and_work_orders_alone_do_not_pass_validator(self) -> None:
        packet = generator.build_work_packet()
        manifest_path, manifest_sha = write_artifact("manifest.json", packet["manifest_artifact"])
        work_orders_path, work_orders_sha = write_artifact("work_orders.json", packet["work_orders_artifact"])
        partial_evidence_packet = {
            "artifact_id": "human_annotation_results_v1",
            "evidence_kind": "real_human_annotation_adjudication",
            "recovered_after_tmp_loss": False,
            "manifest_artifact": manifest_path,
            "manifest_artifact_sha256": manifest_sha,
            "work_orders_artifact": work_orders_path,
            "work_orders_artifact_sha256": work_orders_sha,
            "first_pass_submission_artifacts": [],
            "adjudication_artifact": "",
            "adjudication_artifact_sha256": "",
            "confusion_matrix_artifact": "",
            "confusion_matrix_artifact_sha256": "",
            "custody_receipt_artifact": "",
            "custody_receipt_artifact_sha256": "",
            "claim_boundary": {
                "supports_human_annotation_completed_claim": True,
                "supports_human_adjudication_completed_claim": True,
                "supports_confusion_matrix_claim": True,
                "supports_custody_receipt_claim": True,
                "supports_synthetic_label_generation_claim": False,
                "supports_template_as_human_evidence_claim": False,
                "supports_production_ready_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
        }

        report = validator.build_report(partial_evidence_packet)

        self.assertFalse(report["passed"])
        self.assertIn("two independent first-pass human submission artifacts are not present", report["blockers"])
        self.assertIn("adjudication_artifact missing or hash mismatch", report["blockers"])
        self.assertIn("confusion_matrix_artifact missing or hash mismatch", report["blockers"])
        self.assertIn("custody_receipt_artifact missing or hash mismatch", report["blockers"])

    def test_main_does_not_change_authoritative_gate_state(self) -> None:
        validator_before = validator.build_report()
        gate_before = total_acceptance.annotation_adjudication_protocol_gate()
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "human_annotation_work_packet_generator.py",
                "--output",
                "work_packets/test_human_annotation_work_packet_preview.json",
            ]
            with redirect_stdout(StringIO()):
                generator.main()
        finally:
            sys.argv = original_argv

        validator_after = validator.build_report()
        gate_after = total_acceptance.annotation_adjudication_protocol_gate()

        self.assertEqual(validator_after["passed"], validator_before["passed"])
        self.assertEqual(validator_after["blockers"], validator_before["blockers"])
        self.assertEqual(gate_after["passed"], gate_before["passed"])
        self.assertEqual(gate_after["blockers"], gate_before["blockers"])
        self.assertFalse(validator_after["passed"])
        self.assertFalse(gate_after["passed"])
        self.assert_no_canonical_or_real_root_mutation()

    def test_rejects_duplicate_reviewers_and_non_distinct_adjudicator(self) -> None:
        with self.assertRaisesRegex(generator.WorkPacketError, "first-pass reviewer ids must be distinct"):
            generator.build_work_packet(first_pass_reviewer_ids=["human_reviewer_alpha", "human_reviewer_alpha"])

        with self.assertRaisesRegex(generator.WorkPacketError, "adjudicator id must be distinct"):
            generator.build_work_packet(
                first_pass_reviewer_ids=["human_reviewer_alpha", "human_reviewer_beta"],
                adjudicator_id="human_reviewer_alpha",
            )

        with self.assertRaisesRegex(generator.WorkPacketError, "exactly two first-pass reviewer ids"):
            generator.build_work_packet(
                first_pass_reviewer_ids=[
                    "human_reviewer_alpha",
                    "human_reviewer_beta",
                    "human_reviewer_delta",
                ],
            )

    def test_rejects_raw_test_result_and_template_sources(self) -> None:
        good_item = dict(generator.DEFAULT_ITEMS[0])
        bad_cases = [
            ("source_ref", "/mnt/share/raw.pdf", "raw path"),
            ("source_ref", "/home/markliou/raw.pdf", "raw path"),
            ("source_ref", "file:///tmp/raw.pdf", "raw, test, result, or template"),
            ("source_ref", "object://bucket/raw", "raw, test, result, or template"),
            ("source_ref", "s3://bucket/raw", "raw, test, result, or template"),
            ("source_ref", "postgres://db/table", "raw, test, result, or template"),
            ("source_ref", "C:\\raw\\file.pdf", "raw, test, result, or template"),
            ("source_ref", "../raw/file.pdf", "raw, test, result, or template"),
            ("source_ref", "inputs/test_human_annotation_validator/manifest.json", "raw, test, result, or template"),
            ("source_ref", "results/generated.json", "raw, test, result, or template"),
            ("source_ref", "templates/human_annotation_results_v1.template.json", "raw, test, result, or template"),
            ("source_ref", "formowl://observation/do_not_submit_as_evidence", "raw, test, result, or template"),
            ("item_id", "test_item_001", "test fixture or template markers"),
            ("task_id", "fixture_task_001", "test fixture or template markers"),
        ]
        for field, value, message in bad_cases:
            item = dict(good_item)
            item[field] = value
            if field == "source_ref" and str(value).startswith("formowl://observation/"):
                item["source_observation_id"] = str(value).removeprefix("formowl://observation/")
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(generator.WorkPacketError, message):
                    generator.build_work_packet(items=[item])

    def test_rejects_source_ref_that_does_not_match_observation_id(self) -> None:
        item = dict(generator.DEFAULT_ITEMS[0])
        item["source_ref"] = "formowl://observation/obs_other"

        with self.assertRaisesRegex(generator.WorkPacketError, "bind exactly"):
            generator.build_work_packet(items=[item])

    def test_main_writes_only_safe_work_packet_output(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "human_annotation_work_packet_generator.py",
                "--output",
                "work_packets/test_human_annotation_work_packet_preview.json",
            ]
            with redirect_stdout(StringIO()):
                exit_code = generator.main()
        finally:
            sys.argv = original_argv

        self.assertEqual(exit_code, 0)
        self.assertTrue(OUTPUT.exists())
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(payload["work_packet_type"], "human_annotation_work_packet_preview_v1")
        self.assert_no_canonical_or_real_root_mutation()

    def test_cli_does_not_accept_evidence_or_promotion_arguments(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = ["human_annotation_work_packet_generator.py", "--promote", "--evidence", "fake"]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    generator.main()
        finally:
            sys.argv = original_argv

        self.assertFalse(OUTPUT.exists())
        self.assert_no_canonical_or_real_root_mutation()

    def test_invalid_output_path_fails_before_partial_writes(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "human_annotation_work_packet_generator.py",
                "--output",
                "inputs/human_annotation_real/work_packet.json",
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaises(generator.WorkPacketError):
                    generator.main()
        finally:
            sys.argv = original_argv

        self.assertFalse(OUTPUT.exists())
        self.assert_no_canonical_or_real_root_mutation()

    def test_results_output_path_is_rejected_before_partial_writes(self) -> None:
        target = generator.ROOT / "results" / "human_annotation_adjudication_validator.json"
        before = target.read_bytes() if target.exists() else None
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "human_annotation_work_packet_generator.py",
                "--output",
                "results/human_annotation_adjudication_validator.json",
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
                "human_annotation_work_packet_generator.py",
                "--output",
                "work_packets/human_annotation_real_alias/work_packet.json",
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaisesRegex(generator.WorkPacketError, "symlinks"):
                    generator.main()
        finally:
            sys.argv = original_argv

        self.assertFalse((generator.REAL_ROOT / "work_packet.json").exists())
        self.assert_no_canonical_or_real_root_mutation()

    def test_safe_output_path_rejects_real_roots_and_escapes(self) -> None:
        bad_paths = [
            "inputs/human_annotation_real/work_packet.json",
            "inputs/test_human_annotation_work_packet_generator/work_packet.json",
            "results/human_annotation_adjudication_validator.json",
            "../work_packets/escape.json",
            "/tmp/work_packet.json",
            "templates/work_packet.json",
        ]
        for path in bad_paths:
            with self.subTest(path=path):
                with self.assertRaises(generator.WorkPacketError):
                    generator.safe_output_path(path)


if __name__ == "__main__":
    unittest.main()
