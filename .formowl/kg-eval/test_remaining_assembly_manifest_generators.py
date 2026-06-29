#!/usr/bin/env python3
"""Tests for remaining broad-gate assembly manifest scaffold generation."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import enterprise_multimodal_assembly_manifest_generator as enterprise_generator
import enterprise_multimodal_packet_assembler as enterprise_assembler
import enterprise_multimodal_validation_validator as enterprise_validator
import human_annotation_assembly_manifest_generator as human_generator
import human_annotation_packet_assembler as human_assembler
import kg_total_acceptance_suite as total_acceptance
import production_adapter_assembly_manifest_generator as production_generator
import production_adapter_packet_assembler as production_assembler
import production_adapter_path_validator as production_validator


GATES = {
    "multimodal_semantic_validation": {
        "generator": enterprise_generator,
        "assembler": enterprise_assembler,
        "validator": enterprise_validator,
        "gate": total_acceptance.multimodal_semantic_validation_gate,
        "output": enterprise_generator.WORK_ORDERS
        / "test_multimodal_semantic_validation_assembly_manifest.json",
        "script": "enterprise_multimodal_assembly_manifest_generator.py",
    },
    "production_adapter_paths": {
        "generator": production_generator,
        "assembler": production_assembler,
        "validator": production_validator,
        "gate": total_acceptance.production_adapter_paths_gate,
        "output": production_generator.WORK_ORDERS
        / "test_production_adapter_paths_assembly_manifest.json",
        "script": "production_adapter_assembly_manifest_generator.py",
    },
}


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


def real_root_snapshot(generator: object) -> list[str]:
    return sorted(
        str(path.relative_to(generator.REAL_ROOT)) for path in generator.REAL_ROOT.rglob("*")
    )


class RemainingAssemblyManifestGeneratorsTest(unittest.TestCase):
    def setUp(self) -> None:
        for entry in GATES.values():
            output = entry["output"]
            if output.exists():
                output.unlink()
            alias = entry["generator"].WORK_ORDERS / f"{output.stem}_real_alias"
            if alias.exists() or alias.is_symlink():
                if alias.is_dir() and not alias.is_symlink():
                    shutil.rmtree(alias)
                else:
                    alias.unlink()
        self.canonical_before = {
            gate_id: entry["generator"].CANONICAL_PACKET_PATH.read_bytes()
            if entry["generator"].CANONICAL_PACKET_PATH.exists()
            else None
            for gate_id, entry in GATES.items()
        }
        self.real_root_before = {
            gate_id: real_root_snapshot(entry["generator"]) for gate_id, entry in GATES.items()
        }

    def tearDown(self) -> None:
        for gate_id, entry in GATES.items():
            output = entry["output"]
            if output.exists():
                output.unlink()
            alias = entry["generator"].WORK_ORDERS / f"{output.stem}_real_alias"
            if alias.exists() or alias.is_symlink():
                if alias.is_dir() and not alias.is_symlink():
                    shutil.rmtree(alias)
                else:
                    alias.unlink()
            canonical_path = entry["generator"].CANONICAL_PACKET_PATH
            canonical_before = self.canonical_before[gate_id]
            if canonical_before is None:
                if canonical_path.exists():
                    canonical_path.unlink()
            else:
                canonical_path.write_bytes(canonical_before)

    def assert_no_canonical_or_real_root_mutation(self) -> None:
        for gate_id, entry in GATES.items():
            with self.subTest(gate_id=gate_id):
                canonical_path = entry["generator"].CANONICAL_PACKET_PATH
                canonical_before = self.canonical_before[gate_id]
                if canonical_before is None:
                    self.assertFalse(canonical_path.exists())
                else:
                    self.assertEqual(canonical_path.read_bytes(), canonical_before)
                self.assertEqual(
                    real_root_snapshot(entry["generator"]), self.real_root_before[gate_id]
                )

    def test_human_annotation_scaffold_matches_assembler_shape(self) -> None:
        manifest = human_generator.build_manifest_scaffold()

        self.assertEqual(
            set(manifest),
            human_assembler.MANIFEST_COMMON_REQUIRED_FIELDS
            | human_assembler.MANIFEST_HUMAN_ROUTE_FIELDS,
        )
        self.assertEqual(len(manifest["first_pass_artifacts"]), 2)
        self.assertEqual(
            len({row["reviewer_id"] for row in manifest["first_pass_artifacts"]}),
            2,
        )
        for value in nested_strings(manifest):
            if value.startswith("inputs/"):
                self.assertTrue(value.startswith("inputs/human_annotation_real/"))
                self.assertIn("fill-with-real", value)
                self.assertFalse((human_generator.ROOT / value).exists())
        self.assert_no_canonical_or_real_root_mutation()

    def test_enterprise_scaffold_matches_assembler_shape_and_withholds_claims(self) -> None:
        manifest = enterprise_generator.build_manifest_scaffold()

        self.assertEqual(
            set(manifest),
            enterprise_assembler.MANIFEST_COMMON_REQUIRED_FIELDS | {"human_adjudication_artifact"},
        )
        self.assertEqual(
            sorted(row["modality"] for row in manifest["validation_artifacts"]),
            sorted(enterprise_validator.REQUIRED_MODALITIES),
        )
        self.assertEqual(
            set(manifest["claim_boundary"]),
            enterprise_validator.CLAIM_BOUNDARY_ALLOWED_FIELDS,
        )
        self.assertFalse(any(manifest["claim_boundary"].values()))
        self.assertFalse(manifest["claim_boundary"]["supports_real_enterprise_multimodal_claim"])
        self.assert_no_canonical_or_real_root_mutation()

    def test_production_scaffold_matches_assembler_shape_and_withholds_claims(self) -> None:
        manifest = production_generator.build_manifest_scaffold()

        self.assertEqual(set(manifest), production_assembler.MANIFEST_COMMON_REQUIRED_FIELDS)
        self.assertEqual(
            sorted(row["component_id"] for row in manifest["adapter_artifacts"]),
            sorted(production_validator.REQUIRED_COMPONENTS),
        )
        self.assertEqual(
            set(manifest["claim_boundary"]),
            production_validator.CLAIM_BOUNDARY_ALLOWED_FIELDS,
        )
        self.assertFalse(any(manifest["claim_boundary"].values()))
        self.assertFalse(manifest["claim_boundary"]["supports_production_adapter_paths_claim"])
        self.assert_no_canonical_or_real_root_mutation()

    def test_scaffolds_contain_placeholders_cannot_assemble_and_preserve_gate_state(
        self,
    ) -> None:
        for gate_id, entry in GATES.items():
            with self.subTest(gate_id=gate_id):
                validator_before = entry["validator"].build_report()
                gate_before = entry["gate"]()
                manifest = entry["generator"].build_manifest_scaffold()
                self.assertTrue(
                    any("fill-with-real" in value for value in nested_strings(manifest))
                )
                with self.assertRaises(entry["assembler"].AssemblyError):
                    entry["assembler"].assemble_packet(**manifest)
                validator_after = entry["validator"].build_report()
                gate_after = entry["gate"]()
                self.assertEqual(validator_after["passed"], validator_before["passed"])
                self.assertEqual(validator_after["blockers"], validator_before["blockers"])
                self.assertEqual(gate_after["passed"], gate_before["passed"])
                self.assertEqual(gate_after["blockers"], gate_before["blockers"])
        self.assert_no_canonical_or_real_root_mutation()

    def test_generated_scaffold_files_cannot_be_promoted_and_preserve_gate_state(
        self,
    ) -> None:
        for gate_id, entry in GATES.items():
            with self.subTest(gate_id=gate_id):
                validator_before = entry["validator"].build_report()
                gate_before = entry["gate"]()
                original_argv = sys.argv[:]
                try:
                    sys.argv = [
                        entry["script"],
                        "--output",
                        str(entry["output"].relative_to(entry["generator"].ROOT)),
                    ]
                    with redirect_stdout(StringIO()):
                        entry["generator"].main()
                finally:
                    sys.argv = original_argv

                with self.assertRaisesRegex(
                    entry["assembler"].AssemblyError,
                    "placeholder template values",
                ):
                    entry["assembler"].load_manifest(entry["output"])
                validator_after = entry["validator"].build_report()
                gate_after = entry["gate"]()
                self.assertEqual(validator_after["passed"], validator_before["passed"])
                self.assertEqual(validator_after["blockers"], validator_before["blockers"])
                self.assertEqual(gate_after["passed"], gate_before["passed"])
                self.assertEqual(gate_after["blockers"], gate_before["blockers"])
        self.assert_no_canonical_or_real_root_mutation()

    def test_main_writes_only_safe_work_order_outputs_and_preserves_gate_state(self) -> None:
        for gate_id, entry in GATES.items():
            with self.subTest(gate_id=gate_id):
                validator_before = entry["validator"].build_report()
                gate_before = entry["gate"]()
                work_order_files_before = (
                    sorted(entry["generator"].WORK_ORDERS.rglob("*"))
                    if entry["generator"].WORK_ORDERS.exists()
                    else []
                )
                original_argv = sys.argv[:]
                try:
                    sys.argv = [
                        entry["script"],
                        "--output",
                        str(entry["output"].relative_to(entry["generator"].ROOT)),
                    ]
                    with redirect_stdout(StringIO()):
                        exit_code = entry["generator"].main()
                finally:
                    sys.argv = original_argv

                self.assertEqual(exit_code, 0)
                self.assertTrue(entry["output"].exists())
                payload = json.loads(entry["output"].read_text(encoding="utf-8"))
                self.assertEqual(payload, entry["generator"].build_manifest_scaffold())
                work_order_files_after = sorted(entry["generator"].WORK_ORDERS.rglob("*"))
                self.assertEqual(
                    sorted(set(work_order_files_after) - set(work_order_files_before)),
                    [entry["output"]],
                )
                validator_after = entry["validator"].build_report()
                gate_after = entry["gate"]()
                self.assertEqual(validator_after["passed"], validator_before["passed"])
                self.assertEqual(validator_after["blockers"], validator_before["blockers"])
                self.assertEqual(gate_after["passed"], gate_before["passed"])
                self.assertEqual(gate_after["blockers"], gate_before["blockers"])
        self.assert_no_canonical_or_real_root_mutation()

    def test_cli_does_not_accept_evidence_or_promotion_arguments(self) -> None:
        for gate_id, entry in GATES.items():
            with self.subTest(gate_id=gate_id):
                original_argv = sys.argv[:]
                try:
                    sys.argv = [entry["script"], "--promote", "--evidence", "fake"]
                    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                        with self.assertRaises(SystemExit):
                            entry["generator"].main()
                finally:
                    sys.argv = original_argv
                self.assertFalse(entry["output"].exists())
        self.assert_no_canonical_or_real_root_mutation()

    def test_safe_output_path_rejects_forbidden_roots_and_escapes(self) -> None:
        bad_paths = (
            "results/kg_total_acceptance_snapshot.json",
            "inputs/human_annotation_real/assembly_manifest.json",
            "inputs/enterprise_multimodal_real/assembly_manifest.json",
            "inputs/production_adapter_real/assembly_manifest.json",
            "work_packets/assembly_manifest.json",
            "templates/assembly_manifest.json",
            "../work_orders/escape.json",
            "/tmp/assembly_manifest.json",
            "work_orders/s3:/payload.json",
            "work_orders/C:/payload.json",
            "work_orders/nested\\payload.json",
            "work_orders/file://payload.json",
        )
        for gate_id, entry in GATES.items():
            for path in bad_paths:
                with self.subTest(gate_id=gate_id, path=path):
                    with self.assertRaises(entry["generator"].ManifestScaffoldError):
                        entry["generator"].safe_output_path(path)

    def test_symlinked_work_order_parent_to_real_root_is_rejected(self) -> None:
        for gate_id, entry in GATES.items():
            with self.subTest(gate_id=gate_id):
                alias = entry["generator"].WORK_ORDERS / f"{entry['output'].stem}_real_alias"
                alias.parent.mkdir(parents=True, exist_ok=True)
                alias.symlink_to(entry["generator"].REAL_ROOT, target_is_directory=True)
                original_argv = sys.argv[:]
                try:
                    sys.argv = [
                        entry["script"],
                        "--output",
                        str(
                            (alias / "assembly_manifest.json").relative_to(entry["generator"].ROOT)
                        ),
                    ]
                    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                        with self.assertRaisesRegex(
                            entry["generator"].ManifestScaffoldError,
                            "symlinks",
                        ):
                            entry["generator"].main()
                finally:
                    sys.argv = original_argv
                    if alias.exists() or alias.is_symlink():
                        alias.unlink()
        self.assert_no_canonical_or_real_root_mutation()


if __name__ == "__main__":
    unittest.main()
