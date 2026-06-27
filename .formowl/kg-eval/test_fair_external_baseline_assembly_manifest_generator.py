#!/usr/bin/env python3
"""Tests for fair-baseline assembly manifest scaffold generation."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import fair_external_baseline_assembly_manifest_generator as generator
import fair_external_baseline_packet_assembler as assembler
import fair_external_baseline_run_validator as validator
import kg_total_acceptance_suite as total_acceptance


OUTPUT = generator.WORK_ORDERS / "test_fair_external_baseline_assembly_manifest.json"
SYMLINK_OUTPUT_PARENT = generator.WORK_ORDERS / "fair_baseline_real_alias"
PROTECTED_PATHS = [
    generator.ROOT / "results" / "fair_external_baseline_run_validator.json",
    generator.ROOT / "results" / "kg_total_acceptance_snapshot.json",
    generator.ROOT / "results" / "kg_objective_completion_audit.json",
    generator.ROOT / "templates" / "fair_external_baseline_run_packet.template.json",
    generator.CANONICAL_PACKET_PATH,
]


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


def snapshot_files() -> dict[str, bytes | None]:
    return {
        str(path.relative_to(generator.ROOT)): path.read_bytes() if path.exists() else None
        for path in PROTECTED_PATHS
    }


class FairExternalBaselineAssemblyManifestGeneratorTest(unittest.TestCase):
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

    def test_scaffold_has_exact_assembler_shape_and_source_lock(self) -> None:
        manifest = generator.build_manifest_scaffold()

        self.assertEqual(set(manifest), assembler.MANIFEST_ALLOWED_FIELDS)
        self.assertEqual(
            manifest["source_lock_sha256"],
            validator.literature.required_baseline_source_lock_sha256(),
        )
        self.assertEqual(
            sorted(row["baseline_id"] for row in manifest["baseline_runs"]),
            sorted(validator.REQUIRED_BASELINES),
        )
        self.assertEqual(
            set(manifest["claim_boundary"]),
            validator.CLAIM_BOUNDARY_ALLOWED_FIELDS,
        )
        self.assertFalse(any(manifest["claim_boundary"].values()))
        self.assertFalse(
            manifest["claim_boundary"]["supports_fair_external_baseline_comparison_claim"]
        )

        for row in manifest["baseline_runs"]:
            baseline_id = row["baseline_id"]
            with self.subTest(baseline_id=baseline_id):
                self.assertEqual(
                    row["package_source_url"],
                    validator.REQUIRED_BASELINE_URLS[baseline_id],
                )
                self.assertEqual(
                    row["source_ids"],
                    list(validator.REQUIRED_SOURCE_IDS_BY_BASELINE[baseline_id]),
                )
                self.assertEqual(
                    set(row),
                    assembler.RUN_SOURCE_ALLOWED_FIELDS,
                )
                self.assertFalse(
                    any(key.endswith("_artifact_sha256") for key in row),
                )
                self.assertFalse(
                    any(
                        key == f"{field}_sha256"
                        for field in validator.RUN_ARTIFACT_FIELDS
                        for key in row
                    ),
                )
                for field in validator.EQUALIZED_FIELDS:
                    self.assertEqual(row[field], f"fill-with-real-{field.replace('_', '-')}")
                for field in validator.RUN_ARTIFACT_FIELDS:
                    self.assertEqual(
                        row[field],
                        f"inputs/fair_baseline_real/{baseline_id}/{field}.json",
                    )
                    self.assertFalse((generator.ROOT / row[field]).exists())
                if baseline_id == "hipporag":
                    self.assertIn("hipporag2_paper", row["source_ids"])

        self.assert_no_canonical_or_real_root_mutation()

    def test_scaffold_contains_placeholders_and_cannot_pass_assembler_or_validator(self) -> None:
        manifest = generator.build_manifest_scaffold()
        self.assertTrue(
            any(value.startswith("fill-with-real-") for value in nested_strings(manifest))
        )

        with self.assertRaisesRegex(assembler.AssemblyError, "placeholder template values"):
            assembler.assemble_packet(**manifest)

        report = validator.build_report(manifest)
        self.assertFalse(report["passed"])
        self.assertTrue(report["metrics"]["source_lock_bound"])
        self.assertIn(
            "fair baseline packet does not claim fair-baseline completion",
            report["blockers"],
        )
        self.assertIn(
            "fair baseline run environment is not non-synthetic",
            report["blockers"],
        )
        self.assertFalse(
            report["claim_boundary"]["supports_fair_external_baseline_comparison_claim"]
        )
        self.assert_no_canonical_or_real_root_mutation()

    def test_generated_scaffold_file_is_rejected_by_assembler_loader(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "fair_external_baseline_assembly_manifest_generator.py",
                "--output",
                "work_orders/test_fair_external_baseline_assembly_manifest.json",
            ]
            with redirect_stdout(StringIO()):
                generator.main()
        finally:
            sys.argv = original_argv

        with self.assertRaisesRegex(assembler.AssemblyError, "placeholder template values"):
            assembler.load_manifest(OUTPUT)
        self.assert_no_canonical_or_real_root_mutation()

    def test_main_does_not_change_authoritative_gate_state(self) -> None:
        validator_before = validator.build_report()
        gate_before = total_acceptance.fair_external_baseline_comparison_gate()
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "fair_external_baseline_assembly_manifest_generator.py",
                "--output",
                "work_orders/test_fair_external_baseline_assembly_manifest.json",
            ]
            with redirect_stdout(StringIO()):
                exit_code = generator.main()
        finally:
            sys.argv = original_argv

        validator_after = validator.build_report()
        gate_after = total_acceptance.fair_external_baseline_comparison_gate()

        self.assertEqual(exit_code, 0)
        self.assertEqual(validator_after["passed"], validator_before["passed"])
        self.assertEqual(validator_after["blockers"], validator_before["blockers"])
        self.assertEqual(gate_after["passed"], gate_before["passed"])
        self.assertEqual(gate_after["blockers"], gate_before["blockers"])
        self.assertFalse(validator_after["passed"])
        self.assertFalse(gate_after["passed"])
        self.assert_no_canonical_or_real_root_mutation()

    def test_main_writes_only_safe_work_order_output(self) -> None:
        protected_before = snapshot_files()
        work_order_files_before = (
            sorted(generator.WORK_ORDERS.rglob("*")) if generator.WORK_ORDERS.exists() else []
        )
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "fair_external_baseline_assembly_manifest_generator.py",
                "--output",
                "work_orders/test_fair_external_baseline_assembly_manifest.json",
            ]
            with redirect_stdout(StringIO()):
                exit_code = generator.main()
        finally:
            sys.argv = original_argv

        self.assertEqual(exit_code, 0)
        self.assertTrue(OUTPUT.exists())
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(payload["artifact_id"], "fair_external_baseline_run_packet_v1")
        self.assertEqual(snapshot_files(), protected_before)
        work_order_files_after = sorted(generator.WORK_ORDERS.rglob("*"))
        self.assertEqual(
            sorted(set(work_order_files_after) - set(work_order_files_before)),
            [OUTPUT],
        )
        self.assert_no_canonical_or_real_root_mutation()

    def test_cli_does_not_accept_evidence_or_promotion_arguments(self) -> None:
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "fair_external_baseline_assembly_manifest_generator.py",
                "--promote",
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

    def test_safe_output_path_rejects_forbidden_roots_and_escapes(self) -> None:
        for path in (
            "results/fair_external_baseline_run_validator.json",
            "inputs/fair_baseline_real/assembly_manifest.json",
            "inputs/test_fair_baseline_run_validator/assembly_manifest.json",
            "work_packets/assembly_manifest.json",
            "templates/assembly_manifest.json",
            "../work_orders/escape.json",
            "/tmp/assembly_manifest.json",
            "work_orders/s3:/payload.json",
            "work_orders/C:/payload.json",
            "work_orders/nested\\payload.json",
            "work_orders/file://payload.json",
        ):
            with self.subTest(path=path):
                with self.assertRaises(generator.ManifestScaffoldError):
                    generator.safe_output_path(path)

    def test_symlinked_work_order_parent_to_real_root_is_rejected(self) -> None:
        SYMLINK_OUTPUT_PARENT.parent.mkdir(parents=True, exist_ok=True)
        SYMLINK_OUTPUT_PARENT.symlink_to(generator.REAL_ROOT, target_is_directory=True)
        original_argv = sys.argv[:]
        try:
            sys.argv = [
                "fair_external_baseline_assembly_manifest_generator.py",
                "--output",
                "work_orders/fair_baseline_real_alias/assembly_manifest.json",
            ]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaisesRegex(generator.ManifestScaffoldError, "symlinks"):
                    generator.main()
        finally:
            sys.argv = original_argv

        self.assertFalse((generator.REAL_ROOT / "assembly_manifest.json").exists())
        self.assert_no_canonical_or_real_root_mutation()


if __name__ == "__main__":
    unittest.main()
