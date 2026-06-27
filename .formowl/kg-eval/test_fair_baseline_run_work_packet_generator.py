#!/usr/bin/env python3
"""Tests for non-evidence fair-baseline run work-packet generation."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import fair_external_baseline_packet_assembler as assembler
import fair_baseline_run_work_packet_generator as generator
import fair_external_baseline_run_validator as validator
import kg_total_acceptance_suite as total_acceptance


OUTPUT = generator.WORK_PACKETS / "test_fair_baseline_run_work_packet_preview.json"
SYMLINK_OUTPUT_PARENT = generator.WORK_PACKETS / "fair_baseline_real_alias"


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


class FairBaselineRunWorkPacketGeneratorTest(unittest.TestCase):
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
            path.relative_to(generator.REAL_ROOT)
            for path in generator.REAL_ROOT.rglob("*")
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
            sorted(path.relative_to(generator.REAL_ROOT) for path in generator.REAL_ROOT.rglob("*")),
            self.real_root_before,
        )

    def test_default_packet_is_non_evidence_and_not_acceptance_shaped(self) -> None:
        packet = generator.build_work_packet()

        self.assertEqual(packet["work_packet_type"], "fair_baseline_run_work_packet_preview_v1")
        self.assertEqual(packet["work_packet_state"], "operator_assignment_only")
        self.assertEqual(packet["evidence_state"], "non_evidence")
        self.assertFalse(packet["artifact_boundary"]["executes_packages"])
        self.assertFalse(packet["artifact_boundary"]["creates_run_artifacts"])
        self.assertFalse(packet["artifact_boundary"]["writes_canonical_packet"])
        self.assertFalse(packet["artifact_boundary"]["touches_real_evidence_root"])
        self.assertFalse(packet["artifact_boundary"]["counts_as_acceptance_gate"])
        keys = nested_keys(packet)
        strings = nested_strings(packet)
        forbidden_keys = {
            "artifact_id",
            "evidence_kind",
            "claim_boundary",
            "package_version",
            "real_package_execution",
            "mock_or_dry_run",
            "synthetic_corpus",
            "container_image_digest_sha256",
            "run_manifest_sha256",
            "human_answer_adjudication",
            "graph_quality_validation",
            "permission_probes",
            "passed",
            "ready",
            "overall_ready",
            "ready_for_acceptance",
        }
        self.assertTrue(forbidden_keys.isdisjoint(keys))
        self.assertTrue({"passed", "ready", "overall_ready", "ready_for_acceptance"}.isdisjoint(strings))
        self.assertFalse(any(key.startswith("supports_") for key in keys))
        self.assertFalse(any("supports_" in value for value in strings))
        self.assertFalse(any("--promote" in value for value in strings))
        self.assert_no_canonical_or_real_root_mutation()

    def test_source_lock_and_baseline_rows_match_validator_contract(self) -> None:
        source_lock = generator.build_source_lock()
        packet = generator.build_work_packet()
        run_manifest = packet["run_manifest_artifact"]
        run_assignments = packet["run_assignments_artifact"]
        rows = run_assignments["assignment_rows"]
        locked_sources_by_id = {
            source["source_id"]: source
            for source in source_lock["locked_sources"]
            if isinstance(source, dict)
        }

        self.assertIn("hipporag2_paper", locked_sources_by_id)
        self.assertEqual(
            locked_sources_by_id["hipporag2_paper"]["url"],
            generator.literature.REQUIRED_SOURCE_URLS["hipporag2_paper"],
        )

        self.assertEqual(run_manifest["artifact_type"], "fair_external_baseline_run_manifest_v1")
        self.assertEqual(run_assignments["artifact_type"], "fair_external_baseline_run_assignments_v1")
        self.assertEqual(
            sorted(row["baseline_id"] for row in rows),
            sorted(validator.REQUIRED_BASELINES),
        )
        self.assertEqual(len(rows), len(validator.REQUIRED_BASELINES))
        self.assertEqual(run_manifest["baseline_ids"], list(validator.REQUIRED_BASELINES))
        self.assertEqual(
            set(run_manifest["equalized_surface_contract_sha256s"]),
            set(validator.EQUALIZED_FIELDS),
        )
        for field, digest in run_manifest["equalized_surface_contract_sha256s"].items():
            with self.subTest(equalized_field=field):
                self.assertTrue(validator.strong_hex64(digest))
        for row in rows:
            baseline_id = row["baseline_id"]
            with self.subTest(baseline_id=baseline_id):
                self.assertEqual(row["package_source_url"], validator.REQUIRED_BASELINE_URLS[baseline_id])
                self.assertEqual(row["run_artifact_field_names"], list(validator.RUN_ARTIFACT_FIELDS))
                self.assertEqual(
                    row["equalized_surface_contract_sha256s"],
                    run_manifest["equalized_surface_contract_sha256s"],
                )
                self.assertEqual(
                    set(row["equalized_surface_contract_sha256s"]),
                    set(validator.EQUALIZED_FIELDS),
                )
                self.assertEqual(row["permission_probe_names"], list(validator.REQUIRED_PERMISSION_PROBES))
                if baseline_id == "hipporag":
                    self.assertIn("hipporag2_paper", row["source_ids"])
                    self.assertIn(
                        generator.literature.REQUIRED_SOURCE_URLS["hipporag2_paper"],
                        row["source_urls"],
                    )
                    manifest_row = next(
                        locked
                        for locked in run_manifest["locked_baselines"]
                        if locked["baseline_id"] == "hipporag"
                    )
                    self.assertIn("hipporag2_paper", manifest_row["source_ids"])
                    self.assertIn(
                        generator.literature.REQUIRED_SOURCE_URLS["hipporag2_paper"],
                        manifest_row["source_urls"],
                    )
                expected_hash = generator.sha256_json(
                    {
                        "baseline_id": baseline_id,
                        "package_source_url": row["package_source_url"],
                        "source_ids": row["source_ids"],
                        "run_artifact_field_names": list(validator.RUN_ARTIFACT_FIELDS),
                        "equalized_surface_contract_sha256s": run_manifest[
                            "equalized_surface_contract_sha256s"
                        ],
                        "permission_probe_names": list(validator.REQUIRED_PERMISSION_PROBES),
                    }
                )
                self.assertEqual(row["row_sha256"], expected_hash)

    def test_packet_does_not_emit_real_run_artifact_keys(self) -> None:
        packet = generator.build_work_packet()
        keys = nested_keys(packet)

        for artifact_field in validator.RUN_ARTIFACT_FIELDS:
            with self.subTest(artifact_field=artifact_field):
                self.assertNotIn(artifact_field, keys)
                self.assertNotIn(f"{artifact_field}_sha256", keys)

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
        self.assertIn("fair baseline run packet artifact id mismatch", report["blockers"])
        self.assertIn("fair baseline run packet evidence kind mismatch", report["blockers"])
        self.assertIn("fair baseline run environment missing", report["blockers"])
        self.assertIn("fair baseline package runs missing", report["blockers"])

    def test_generated_work_packet_is_rejected_by_real_packet_assembler(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "fair_baseline_run_work_packet_generator.py",
                "--output",
                "work_packets/test_fair_baseline_run_work_packet_preview.json",
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
        gate_before = total_acceptance.fair_external_baseline_comparison_gate()
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "fair_baseline_run_work_packet_generator.py",
                "--output",
                "work_packets/test_fair_baseline_run_work_packet_preview.json",
            ]
            with redirect_stdout(StringIO()):
                generator.main()
        finally:
            sys.argv = original_argv

        validator_after = validator.build_report()
        gate_after = total_acceptance.fair_external_baseline_comparison_gate()

        self.assertEqual(validator_after["passed"], validator_before["passed"])
        self.assertEqual(validator_after["blockers"], validator_before["blockers"])
        self.assertEqual(gate_after["passed"], gate_before["passed"])
        self.assertEqual(gate_after["blockers"], gate_before["blockers"])
        self.assertFalse(validator_after["passed"])
        self.assertFalse(gate_after["passed"])
        self.assert_no_canonical_or_real_root_mutation()

    def test_main_writes_only_safe_work_packet_output(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "fair_baseline_run_work_packet_generator.py",
                "--output",
                "work_packets/test_fair_baseline_run_work_packet_preview.json",
            ]
            with redirect_stdout(StringIO()):
                exit_code = generator.main()
        finally:
            sys.argv = original_argv

        self.assertEqual(exit_code, 0)
        self.assertTrue(OUTPUT.exists())
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(payload["work_packet_type"], "fair_baseline_run_work_packet_preview_v1")
        self.assert_no_canonical_or_real_root_mutation()

    def test_cli_does_not_accept_evidence_or_promotion_arguments(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = ["fair_baseline_run_work_packet_generator.py", "--promote", "--evidence", "fake"]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    generator.main()
        finally:
            sys.argv = original_argv

        self.assertFalse(OUTPUT.exists())
        self.assert_no_canonical_or_real_root_mutation()

    def test_results_and_real_root_output_paths_are_rejected_before_partial_writes(self) -> None:
        target = generator.ROOT / "results" / "fair_external_baseline_run_validator.json"
        before = target.read_bytes() if target.exists() else None
        for output in (
            "results/fair_external_baseline_run_validator.json",
            "inputs/fair_baseline_real/work_packet.json",
        ):
            with self.subTest(output=output):
                original_argv = sys.argv[:]
                try:
                    sys.argv = [
                        "fair_baseline_run_work_packet_generator.py",
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
                "fair_baseline_run_work_packet_generator.py",
                "--output",
                "work_packets/fair_baseline_real_alias/work_packet.json",
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaisesRegex(generator.WorkPacketError, "symlinks"):
                    generator.main()
        finally:
            sys.argv = original_argv

        self.assertFalse((generator.REAL_ROOT / "work_packet.json").exists())
        self.assert_no_canonical_or_real_root_mutation()

    def test_safe_output_path_rejects_escapes(self) -> None:
        for path in (
            "results/fair_external_baseline_run_validator.json",
            "inputs/fair_baseline_real/work_packet.json",
            "inputs/test_fair_baseline_run_validator/work_packet.json",
            "../work_packets/escape.json",
            "/tmp/work_packet.json",
            "templates/work_packet.json",
        ):
            with self.subTest(path=path):
                with self.assertRaises(generator.WorkPacketError):
                    generator.safe_output_path(path)

    def test_source_lock_rejects_raw_or_test_url_if_literature_source_is_tampered(self) -> None:
        original_sources = generator.literature.default_sources
        try:
            generator.literature.default_sources = lambda: [
                {
                    "source_id": "microsoft_graphrag_repo",
                    "source_type": "official_repo",
                    "year": 2026,
                    "url": "file:///tmp/repo",
                }
            ]
            with self.assertRaisesRegex(generator.WorkPacketError, "approved public source"):
                generator.build_source_lock()
        finally:
            generator.literature.default_sources = original_sources


if __name__ == "__main__":
    unittest.main()
