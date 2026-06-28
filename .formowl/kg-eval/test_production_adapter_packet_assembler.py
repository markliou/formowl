#!/usr/bin/env python3
"""Tests for assembling real production adapter evidence packets."""

from __future__ import annotations

import hashlib
import json
import shutil
import unittest
from pathlib import Path

import production_adapter_packet_assembler as assembler
import production_adapter_path_validator as validator
import test_production_adapter_path_validator as validator_fixtures


BASE = assembler.INPUTS / "production_adapter_real" / "assembler_test"


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


def copy_validator_fixture_artifacts() -> dict[str, object]:
    packet = validator_fixtures.valid_packet()
    mapping: dict[str, object] = {
        "artifact_id": packet["artifact_id"],
        "evidence_kind": packet["evidence_kind"],
        "recovered_after_tmp_loss": packet["recovered_after_tmp_loss"],
        "claim_boundary": dict(packet["claim_boundary"]),
    }
    for field in (
        "deployment_manifest_artifact",
        "human_false_merge_label_artifact",
        "audit_trail_artifact",
        "permission_probe_artifact",
        "rollback_smoke_artifact",
    ):
        source = validator.safe_relative_artifact_path(
            packet[field],
            allow_test_artifacts=True,
        )
        assert source is not None
        payload = json.loads(source.read_text(encoding="utf-8"))
        mapping[field] = write_json(f"{field}.json", payload)
    adapter_artifacts = []
    for ref in packet["adapter_artifacts"]:
        source = validator.safe_relative_artifact_path(
            ref["artifact"],
            allow_test_artifacts=True,
        )
        assert source is not None
        payload = json.loads(source.read_text(encoding="utf-8"))
        adapter_artifacts.append(
            {
                "component_id": ref["component_id"],
                "artifact": write_json(f"adapter_{ref['component_id']}.json", payload),
            }
        )
    mapping["adapter_artifacts"] = adapter_artifacts
    return mapping


def valid_assembly_manifest() -> dict[str, object]:
    return copy_validator_fixture_artifacts()


class ProductionAdapterPacketAssemblerTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator_fixtures.BASE, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator_fixtures.BASE, ignore_errors=True)

    def test_assemble_candidate_computes_hashes_without_modifying_artifacts(self) -> None:
        manifest = valid_assembly_manifest()
        artifact_path = path_for(manifest["deployment_manifest_artifact"])
        before_bytes = artifact_path.read_bytes()

        packet = assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        self.assertEqual(artifact_path.read_bytes(), before_bytes)
        self.assertEqual(
            packet["deployment_manifest_artifact"], manifest["deployment_manifest_artifact"]
        )
        self.assertEqual(
            packet["deployment_manifest_artifact_sha256"], validator.sha256_file(artifact_path)
        )
        self.assertNotEqual(
            packet["deployment_manifest_artifact_sha256"],
            validator.sha256_json(json.loads(before_bytes)),
        )
        self.assertEqual(packet["evidence_kind"], "non_synthetic_production_adapter_validation")
        self.assertTrue(packet["claim_boundary"]["supports_production_adapter_paths_claim"])
        self.assertFalse(packet["claim_boundary"]["supports_full_product_production_ready_claim"])
        self.assertEqual(
            sorted(ref["component_id"] for ref in packet["adapter_artifacts"]),
            sorted(validator.REQUIRED_COMPONENTS),
        )

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
        manifest_path.write_text('{"artifact_id": "swapped"}\n', encoding="utf-8")

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
        permission_path = path_for(manifest["permission_probe_artifact"])
        permission = json.loads(permission_path.read_text(encoding="utf-8"))
        permission["raw_asset_access_denied"] = False
        permission_path.write_text(
            json.dumps(permission, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
            "production adapter permission probe failed or missing: raw_asset_access_denied",
            report["blockers"],
        )

    def test_rejects_missing_or_unsupported_claim_boundary_instead_of_generating_it(self) -> None:
        manifest = valid_assembly_manifest()
        manifest.pop("claim_boundary")
        with self.assertRaisesRegex(assembler.AssemblyError, "claim boundary must be supplied"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        manifest = valid_assembly_manifest()
        manifest["claim_boundary"]["supports_production_adapter_paths_claim"] = False
        with self.assertRaisesRegex(assembler.AssemblyError, "required production adapter claims"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        manifest = valid_assembly_manifest()
        manifest["claim_boundary"]["supports_raw_access_claim"] = True
        with self.assertRaisesRegex(assembler.AssemblyError, "overclaims unsupported claims"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

    def test_adapter_artifacts_must_cover_required_components_once(self) -> None:
        manifest = valid_assembly_manifest()
        manifest["adapter_artifacts"] = manifest["adapter_artifacts"][:-1]
        with self.assertRaisesRegex(assembler.AssemblyError, "cover each required component"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        manifest = valid_assembly_manifest()
        manifest["adapter_artifacts"][0] = dict(manifest["adapter_artifacts"][1])
        with self.assertRaisesRegex(assembler.AssemblyError, "cover each required component"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

    def test_rejects_templates_placeholders_and_test_fixture_artifacts(self) -> None:
        with self.assertRaisesRegex(
            assembler.AssemblyError, "template artifact paths are not accepted"
        ):
            assembler.artifact_ref("templates/production_adapter_evidence_packet.template.json")

        with self.assertRaisesRegex(
            assembler.AssemblyError, "must live under inputs/production_adapter_real"
        ):
            assembler.artifact_ref(
                "inputs/test_production_adapter_path_validator/deployment_manifest.json"
            )

        marker_path = write_json("template_marker.json", {"template_only": True})
        with self.assertRaisesRegex(assembler.AssemblyError, "template markers"):
            assembler.artifact_ref(marker_path, allow_test_artifacts=True)

        placeholder_path = write_json("placeholder.json", {"sha256": "fill-with-real-sha256"})
        with self.assertRaisesRegex(assembler.AssemblyError, "placeholder template values"):
            assembler.artifact_ref(placeholder_path, allow_test_artifacts=True)

    def test_default_rejects_real_root_sandbox_artifact_paths(self) -> None:
        for segment in (
            "validator_fixture",
            "assembler_test",
            "preflight_test",
            "test_adapter",
            "release_test",
        ):
            with self.subTest(segment=segment):
                with self.assertRaisesRegex(assembler.AssemblyError, "test or sandbox"):
                    assembler.artifact_ref(
                        f"inputs/production_adapter_real/{segment}/deployment_manifest.json"
                    )

    def test_rejects_raw_internal_values_inside_real_artifacts(self) -> None:
        for value in ("/mnt/nas/config.json", "postgresql+psycopg2://db.internal/formowl"):
            raw_path = write_json(
                f"raw_payload_{len(value)}.json",
                {
                    "artifact_type": "production_adapter_audit_trail_v1",
                    "resource_ref": value,
                },
            )
            with self.assertRaisesRegex(assembler.AssemblyError, "raw/internal artifact value"):
                assembler.artifact_ref(raw_path, allow_test_artifacts=True)

    def test_rejects_unsafe_paths_and_symlink_escapes(self) -> None:
        with self.assertRaisesRegex(assembler.AssemblyError, "safe relative path"):
            assembler.artifact_ref("/tmp/deployment_manifest.json")
        with self.assertRaisesRegex(assembler.AssemblyError, "safe relative path"):
            assembler.artifact_ref("postgresql+psycopg2://db.internal/formowl")
        with self.assertRaisesRegex(assembler.AssemblyError, "safe relative path"):
            assembler.artifact_ref("inputs/production_adapter_real/../deployment_manifest.json")
        with self.assertRaisesRegex(
            assembler.AssemblyError, "must live under inputs/production_adapter_real"
        ):
            assembler.artifact_ref("inputs/production_adapter_reality/deployment_manifest.json")

        outside = assembler.ROOT / "templates" / "production_adapter_evidence_packet.template.json"
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

    def test_rejects_uri_like_segments_inside_allowed_root(self) -> None:
        for relative_path in (
            "s3:/payload.json",
            "C:/payload.json",
            "nested\\payload.json",
        ):
            path = BASE / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"artifact_type": "placeholder"}) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(assembler.AssemblyError, "safe relative path"):
                assembler.artifact_ref(str(path.relative_to(assembler.ROOT)))

    def test_rejects_symlinked_parent_directory_to_test_fixtures(self) -> None:
        target = assembler.ROOT / "inputs" / "test_production_adapter_path_validator"
        link = BASE / "fixture_alias"
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target, target_is_directory=True)

        with self.assertRaisesRegex(assembler.AssemblyError, "symlinks are not accepted"):
            assembler.artifact_ref(
                str((link / "deployment_manifest.json").relative_to(assembler.ROOT)),
                allow_test_artifacts=True,
            )

    def test_load_manifest_rejects_unsupported_fields_and_template_markers(self) -> None:
        manifest_path = Path(write_raw("assembly_manifest.json", json.dumps({"unexpected": True})))
        with self.assertRaisesRegex(assembler.AssemblyError, "unsupported fields"):
            assembler.load_manifest(assembler.ROOT / manifest_path)

        template_path = Path(
            write_raw("template_manifest.json", json.dumps({"template_only": True}))
        )
        with self.assertRaisesRegex(assembler.AssemblyError, "template markers"):
            assembler.load_manifest(assembler.ROOT / template_path)

        missing_path = Path(write_raw("missing_manifest.json", json.dumps({"artifact_id": "x"})))
        with self.assertRaisesRegex(assembler.AssemblyError, "missing required fields"):
            assembler.load_manifest(assembler.ROOT / missing_path)


if __name__ == "__main__":
    unittest.main()
