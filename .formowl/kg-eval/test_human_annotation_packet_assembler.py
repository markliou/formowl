#!/usr/bin/env python3
"""Tests for assembling real human annotation evidence packets."""

from __future__ import annotations

import hashlib
import json
import shutil
import unittest
from pathlib import Path

import human_annotation_packet_assembler as assembler
import human_annotation_adjudication_validator as validator
import test_human_annotation_adjudication_validator as validator_fixtures


BASE = assembler.INPUTS / "human_annotation_real" / "assembler_test"


def write_json(relative_name: str, payload: object) -> str:
    path = BASE / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path.relative_to(assembler.ROOT))


def write_raw(relative_name: str, content: str) -> str:
    path = BASE / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path.relative_to(assembler.ROOT))


def path_for(relative_path: str) -> Path:
    return assembler.ROOT / relative_path


def copy_validator_fixture_artifacts() -> dict[str, str | list[dict[str, str]]]:
    packet = validator_fixtures.valid_packet()
    mapping: dict[str, str | list[dict[str, str]]] = {}
    for field in (
        "manifest_artifact",
        "work_orders_artifact",
        "adjudication_artifact",
        "confusion_matrix_artifact",
        "custody_receipt_artifact",
    ):
        source = validator.safe_relative_artifact_path(
            packet[field],
            allow_test_artifacts=True,
        )
        assert source is not None
        payload = json.loads(source.read_text(encoding="utf-8"))
        mapping[field] = write_json(f"{field}.json", payload)
    first_pass = []
    for index, ref in enumerate(packet["first_pass_submission_artifacts"]):
        source = validator.safe_relative_artifact_path(
            ref["artifact"],
            allow_test_artifacts=True,
        )
        assert source is not None
        payload = json.loads(source.read_text(encoding="utf-8"))
        first_pass.append(
            {
                "reviewer_id": ref["reviewer_id"],
                "artifact": write_json(f"first_pass_{index}.json", payload),
            }
        )
    mapping["first_pass_artifacts"] = first_pass
    return mapping


def valid_assembly_manifest() -> dict:
    return copy_validator_fixture_artifacts()


class HumanAnnotationPacketAssemblerTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator_fixtures.BASE, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator_fixtures.BASE, ignore_errors=True)

    def test_assemble_candidate_computes_raw_file_hashes_without_modifying_artifacts(self) -> None:
        manifest = valid_assembly_manifest()
        artifact_path = path_for(manifest["manifest_artifact"])
        before_bytes = artifact_path.read_bytes()

        packet = assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        self.assertEqual(artifact_path.read_bytes(), before_bytes)
        self.assertEqual(packet["manifest_artifact"], manifest["manifest_artifact"])
        self.assertEqual(packet["manifest_artifact_sha256"], validator.sha256_file(artifact_path))
        self.assertNotEqual(
            packet["manifest_artifact_sha256"], validator.sha256_json(json.loads(before_bytes))
        )
        self.assertEqual(packet["evidence_kind"], "real_human_annotation_adjudication")
        self.assertFalse(packet["claim_boundary"]["supports_production_ready_claim"])
        self.assertFalse(packet["claim_boundary"]["supports_top_tier_scientific_validation_claim"])
        self.assertFalse(packet["claim_boundary"]["supports_template_as_human_evidence_claim"])

    def test_valid_supplied_artifacts_can_validate_and_promote_to_explicit_output(self) -> None:
        manifest = valid_assembly_manifest()
        packet = assembler.assemble_packet(**manifest, allow_test_artifacts=True)
        report = assembler.validate_candidate(packet, allow_test_artifacts=True)
        output = BASE / "promoted_packet.json"
        if output.exists():
            output.unlink()

        assembler.promote_packet(packet, output_path=output, allow_test_artifacts=True)

        self.assertTrue(report["passed"])
        self.assertTrue(output.exists())
        promoted = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(promoted, packet)

    def test_load_manifest_rejects_bytes_that_do_not_match_approved_sha(self) -> None:
        manifest_path = BASE / "assembly_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(valid_assembly_manifest(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        approved_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        manifest_path.write_text('{"manifest_artifact": "swapped"}\n', encoding="utf-8")

        with self.assertRaisesRegex(assembler.AssemblyError, "assembly manifest sha256 mismatch"):
            assembler.load_manifest(manifest_path, expected_sha256=approved_sha)

    def test_valid_fixture_packet_cannot_promote_to_canonical_input(self) -> None:
        manifest = valid_assembly_manifest()
        packet = assembler.assemble_packet(**manifest, allow_test_artifacts=True)
        canonical_before = (
            assembler.CANONICAL_PACKET_PATH.read_bytes()
            if assembler.CANONICAL_PACKET_PATH.exists()
            else None
        )

        with self.assertRaisesRegex(assembler.AssemblyError, "cannot be promoted to canonical"):
            assembler.promote_packet(packet, allow_test_artifacts=True)

        if canonical_before is None:
            self.assertFalse(assembler.CANONICAL_PACKET_PATH.exists())
        else:
            self.assertEqual(assembler.CANONICAL_PACKET_PATH.read_bytes(), canonical_before)

    def test_valid_fixture_packet_cannot_promote_to_canonical_hardlink_alias(self) -> None:
        manifest = valid_assembly_manifest()
        packet = assembler.assemble_packet(**manifest, allow_test_artifacts=True)
        canonical_path = assembler.CANONICAL_PACKET_PATH
        hardlink_alias = BASE / "canonical_hardlink_alias.json"
        canonical_before = canonical_path.read_bytes() if canonical_path.exists() else None
        seeded_canonical = canonical_before or b'{"artifact_id":"canonical_seed"}\n'
        if hardlink_alias.exists() or hardlink_alias.is_symlink():
            hardlink_alias.unlink()
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_bytes(seeded_canonical)
        hardlink_alias.hardlink_to(canonical_path)

        try:
            with self.assertRaisesRegex(assembler.AssemblyError, "cannot be promoted to canonical"):
                assembler.promote_packet(
                    packet,
                    output_path=hardlink_alias,
                    allow_test_artifacts=True,
                )
            self.assertEqual(canonical_path.read_bytes(), seeded_canonical)
        finally:
            if hardlink_alias.exists() or hardlink_alias.is_symlink():
                hardlink_alias.unlink()
            if canonical_before is None:
                if canonical_path.exists():
                    canonical_path.unlink()
            else:
                canonical_path.write_bytes(canonical_before)

    def test_invalid_candidate_can_be_reported_but_not_promoted_to_canonical_input(self) -> None:
        manifest = valid_assembly_manifest()
        custody_path = path_for(manifest["custody_receipt_artifact"])
        custody = json.loads(custody_path.read_text(encoding="utf-8"))
        custody["human_packet_complete"] = False
        custody_path.write_text(
            json.dumps(custody, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        packet = assembler.assemble_packet(**manifest, allow_test_artifacts=True)
        canonical_before = (
            assembler.CANONICAL_PACKET_PATH.read_bytes()
            if assembler.CANONICAL_PACKET_PATH.exists()
            else None
        )

        report = assembler.validate_candidate(packet, allow_test_artifacts=True)
        with self.assertRaisesRegex(assembler.AssemblyError, "cannot be promoted to canonical"):
            assembler.promote_packet(packet, allow_test_artifacts=True)

        self.assertFalse(report["passed"])
        if canonical_before is None:
            self.assertFalse(assembler.CANONICAL_PACKET_PATH.exists())
        else:
            self.assertEqual(assembler.CANONICAL_PACKET_PATH.read_bytes(), canonical_before)
        self.assertIn(
            "custody receipt does not certify human packet completion", report["blockers"]
        )

    def test_rejects_templates_and_test_fixture_artifacts(self) -> None:
        with self.assertRaisesRegex(
            assembler.AssemblyError, "template artifact paths are not accepted"
        ):
            assembler.artifact_ref("templates/human_annotation_results_v1.template.json")

        with self.assertRaisesRegex(
            assembler.AssemblyError, "artifact path must live under inputs/human_annotation_real"
        ):
            assembler.artifact_ref("inputs/test_human_annotation_validator/manifest.json")

        template_payload = {"template_only": True}
        template_marker_path = write_json("template_marker.json", template_payload)
        with self.assertRaisesRegex(assembler.AssemblyError, "template markers are not accepted"):
            assembler.artifact_ref(template_marker_path, allow_test_artifacts=True)

    def test_default_rejects_real_root_sandbox_artifact_paths(self) -> None:
        for segment in (
            "validator_fixture",
            "assembler_test",
            "preflight_test",
            "test_real_labels",
            "release_test",
        ):
            with self.subTest(segment=segment):
                with self.assertRaisesRegex(assembler.AssemblyError, "test or sandbox"):
                    assembler.artifact_ref(f"inputs/human_annotation_real/{segment}/manifest.json")

    def test_rejects_unsafe_paths_and_symlink_escapes(self) -> None:
        with self.assertRaisesRegex(assembler.AssemblyError, "safe relative path"):
            assembler.artifact_ref("/tmp/manifest.json")
        with self.assertRaisesRegex(assembler.AssemblyError, "safe relative path"):
            assembler.artifact_ref("inputs/human_annotation_real/../manifest.json")
        with self.assertRaisesRegex(
            assembler.AssemblyError, "must live under inputs/human_annotation_real"
        ):
            assembler.artifact_ref("input/human_annotation_real/manifest.json")

        outside = assembler.ROOT / "templates" / "human_annotation_results_v1.template.json"
        link = BASE / "escape_link.json"
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(outside)
        with self.assertRaisesRegex(assembler.AssemblyError, "symlinks are not accepted"):
            assembler.artifact_ref(
                str(link.relative_to(assembler.ROOT)),
                allow_test_artifacts=True,
            )

    def test_rejects_symlinked_parent_directory_to_test_fixtures(self) -> None:
        target = assembler.ROOT / "inputs" / "test_human_annotation_validator"
        link = BASE / "fixture_alias"
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target, target_is_directory=True)

        with self.assertRaisesRegex(assembler.AssemblyError, "symlinks are not accepted"):
            assembler.artifact_ref(
                str((link / "manifest.json").relative_to(assembler.ROOT)),
                allow_test_artifacts=True,
            )

    def test_load_manifest_rejects_unsupported_fields(self) -> None:
        manifest_path = Path(write_raw("assembly_manifest.json", json.dumps({"unexpected": True})))

        with self.assertRaisesRegex(assembler.AssemblyError, "unsupported fields"):
            assembler.load_manifest(assembler.ROOT / manifest_path)


if __name__ == "__main__":
    unittest.main()
