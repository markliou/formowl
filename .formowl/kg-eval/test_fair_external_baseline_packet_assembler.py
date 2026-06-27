#!/usr/bin/env python3
"""Tests for assembling real fair external-baseline evidence packets."""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

import fair_external_baseline_packet_assembler as assembler
import fair_external_baseline_run_validator as validator
import test_fair_external_baseline_run_validator as validator_fixtures


BASE = assembler.INPUTS / "fair_baseline_real" / "assembler_test"


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
    manifest: dict[str, object] = {
        "artifact_id": packet["artifact_id"],
        "evidence_kind": packet["evidence_kind"],
        "recovered_after_tmp_loss": packet["recovered_after_tmp_loss"],
        "run_environment": dict(packet["run_environment"]),
        "source_lock_sha256": packet["source_lock_sha256"],
        "human_answer_adjudication": json.loads(json.dumps(packet["human_answer_adjudication"])),
        "graph_quality_validation": json.loads(json.dumps(packet["graph_quality_validation"])),
        "permission_probes": json.loads(json.dumps(packet["permission_probes"])),
        "claim_boundary": dict(packet["claim_boundary"]),
    }
    baseline_runs = []
    for run in packet["baseline_runs"]:
        copied = {
            key: value
            for key, value in run.items()
            if not key.endswith("_artifact_sha256")
            and key not in {f"{field}_sha256" for field in validator.RUN_ARTIFACT_FIELDS}
        }
        for artifact_field in validator.RUN_ARTIFACT_FIELDS:
            source = validator.safe_relative_artifact_path(
                run[artifact_field],
                allow_test_artifacts=True,
            )
            assert source is not None
            payload = json.loads(source.read_text(encoding="utf-8"))
            copied[artifact_field] = write_json(
                f"{run['baseline_id']}/{artifact_field}.json",
                payload,
            )
        baseline_runs.append(copied)
    manifest["baseline_runs"] = baseline_runs
    return manifest


def valid_assembly_manifest() -> dict[str, object]:
    return copy_validator_fixture_artifacts()


class FairExternalBaselinePacketAssemblerTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator_fixtures.BASE, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator_fixtures.BASE, ignore_errors=True)

    def test_assemble_candidate_computes_hashes_without_modifying_artifacts(self) -> None:
        manifest = valid_assembly_manifest()
        first_run = manifest["baseline_runs"][0]
        artifact_path = path_for(first_run["answer_output_artifact"])
        before_bytes = artifact_path.read_bytes()

        packet = assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        self.assertEqual(artifact_path.read_bytes(), before_bytes)
        assembled_run = next(
            run for run in packet["baseline_runs"] if run["baseline_id"] == first_run["baseline_id"]
        )
        self.assertEqual(
            assembled_run["answer_output_artifact"], first_run["answer_output_artifact"]
        )
        self.assertEqual(
            assembled_run["answer_output_artifact_sha256"], validator.sha256_file(artifact_path)
        )
        self.assertNotEqual(
            assembled_run["answer_output_artifact_sha256"],
            validator.sha256_json(json.loads(before_bytes)),
        )
        self.assertEqual(packet["evidence_kind"], "non_synthetic_external_baseline_run")
        self.assertEqual(
            packet["source_lock_sha256"],
            validator.literature.required_baseline_source_lock_sha256(),
        )
        self.assertTrue(
            packet["claim_boundary"]["supports_fair_external_baseline_comparison_claim"]
        )
        self.assertFalse(packet["claim_boundary"]["supports_top_tier_scientific_validation_claim"])
        self.assertEqual(
            sorted(run["baseline_id"] for run in packet["baseline_runs"]),
            sorted(validator.REQUIRED_BASELINES),
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

    def test_plain_text_run_artifact_can_be_hashed_without_json_parsing(self) -> None:
        manifest = valid_assembly_manifest()
        log_artifact = write_raw(
            "microsoft_graphrag/index_build_log.txt", "index build completed\n"
        )
        manifest["baseline_runs"][0]["index_build_log_artifact"] = log_artifact

        packet = assembler.assemble_packet(**manifest, allow_test_artifacts=True)
        run = next(
            run
            for run in packet["baseline_runs"]
            if run["baseline_id"] == manifest["baseline_runs"][0]["baseline_id"]
        )

        self.assertEqual(run["index_build_log_artifact"], log_artifact)
        self.assertEqual(
            run["index_build_log_artifact_sha256"], validator.sha256_file(path_for(log_artifact))
        )

    def test_invalid_candidate_can_be_reported_but_not_promoted_to_canonical_input(self) -> None:
        manifest = valid_assembly_manifest()
        answer_path = path_for(manifest["baseline_runs"][0]["answer_output_artifact"])
        answer = json.loads(answer_path.read_text(encoding="utf-8"))
        answer["changed_after_adjudication"] = True
        answer_path.write_text(
            json.dumps(answer, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
            f"{manifest['baseline_runs'][0]['baseline_id']} human answer-quality row is not bound to package answer output",
            report["blockers"],
        )

    def test_rejects_missing_or_unsupported_claim_boundary_instead_of_generating_it(self) -> None:
        manifest = valid_assembly_manifest()
        manifest.pop("claim_boundary")
        with self.assertRaisesRegex(assembler.AssemblyError, "claim boundary must be supplied"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        manifest = valid_assembly_manifest()
        manifest["claim_boundary"]["supports_fair_external_baseline_comparison_claim"] = False
        with self.assertRaisesRegex(assembler.AssemblyError, "required fair baseline claim"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        manifest = valid_assembly_manifest()
        manifest["claim_boundary"]["supports_unreviewed_canonical_merge_claim"] = True
        with self.assertRaisesRegex(assembler.AssemblyError, "overclaims unsupported claims"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

    def test_rejects_missing_or_mismatched_source_lock_instead_of_generating_it(self) -> None:
        manifest = valid_assembly_manifest()
        manifest.pop("source_lock_sha256")
        with self.assertRaises(TypeError):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        manifest = valid_assembly_manifest()
        manifest["source_lock_sha256"] = "abcdef1234567890" * 4
        with self.assertRaisesRegex(assembler.AssemblyError, "source lock hash"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

    def test_rejects_baseline_run_source_ids_that_do_not_match_literature_lock(self) -> None:
        manifest = valid_assembly_manifest()
        hipporag = next(
            run for run in manifest["baseline_runs"] if run["baseline_id"] == "hipporag"
        )
        hipporag["source_ids"] = ["hipporag_paper", "hipporag_repo"]

        with self.assertRaisesRegex(assembler.AssemblyError, "locked literature source list"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

    def test_baseline_runs_must_cover_required_baselines_once(self) -> None:
        manifest = valid_assembly_manifest()
        manifest["baseline_runs"] = manifest["baseline_runs"][:-1]
        with self.assertRaisesRegex(assembler.AssemblyError, "cover each required baseline"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        manifest = valid_assembly_manifest()
        manifest["baseline_runs"][0] = dict(manifest["baseline_runs"][1])
        with self.assertRaisesRegex(assembler.AssemblyError, "cover each required baseline"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

    def test_rejects_templates_placeholders_and_test_fixture_artifacts(self) -> None:
        with self.assertRaisesRegex(
            assembler.AssemblyError, "template artifact paths are not accepted"
        ):
            assembler.artifact_ref("templates/fair_external_baseline_run_packet.template.json")

        with self.assertRaisesRegex(
            assembler.AssemblyError, "must live under inputs/fair_baseline_real"
        ):
            assembler.artifact_ref(
                "inputs/test_fair_baseline_run_validator/microsoft_graphrag/answer_output_artifact.json"
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
            "test_real_run",
            "release_test",
        ):
            with self.subTest(segment=segment):
                with self.assertRaisesRegex(assembler.AssemblyError, "test or sandbox"):
                    assembler.artifact_ref(
                        f"inputs/fair_baseline_real/{segment}/answer_output.json"
                    )

    def test_rejects_raw_internal_values_inside_real_artifacts(self) -> None:
        raw_path = write_json(
            "raw_payload.json",
            {
                "artifact_field": "answer_output_artifact",
                "storage_uri": "s3://private-bucket/answers.json",
            },
        )

        with self.assertRaisesRegex(assembler.AssemblyError, "raw/internal artifact value"):
            assembler.artifact_ref(raw_path, allow_test_artifacts=True)

    def test_rejects_raw_internal_values_inside_manifest_supplied_summaries(self) -> None:
        manifest = valid_assembly_manifest()
        manifest["run_environment"]["postgres_uri"] = "postgres://internal/formowl"
        with self.assertRaisesRegex(assembler.AssemblyError, "raw/internal artifact value"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        manifest = valid_assembly_manifest()
        manifest["human_answer_adjudication"]["source_uri"] = (
            "s3://private-bucket/adjudication.json"
        )
        with self.assertRaisesRegex(assembler.AssemblyError, "raw/internal artifact value"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

        manifest = valid_assembly_manifest()
        manifest["permission_probes"][0]["raw_probe_path"] = "nas://internal/probe.json"
        with self.assertRaisesRegex(assembler.AssemblyError, "raw/internal artifact value"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

    def test_rejects_raw_internal_values_inside_baseline_run_metadata(self) -> None:
        manifest = valid_assembly_manifest()
        manifest["baseline_runs"][0]["package_version"] = "postgres://internal/formowl"

        with self.assertRaisesRegex(assembler.AssemblyError, "raw/internal artifact value"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

    def test_rejects_placeholder_values_inside_baseline_run_metadata(self) -> None:
        manifest = valid_assembly_manifest()
        manifest["baseline_runs"][0]["package_version"] = "fill-with-real-package-version"

        with self.assertRaisesRegex(assembler.AssemblyError, "placeholder template values"):
            assembler.assemble_packet(**manifest, allow_test_artifacts=True)

    def test_rejects_unsafe_paths_and_symlink_escapes(self) -> None:
        with self.assertRaisesRegex(assembler.AssemblyError, "safe relative path"):
            assembler.artifact_ref("/tmp/answer_output.json")
        with self.assertRaisesRegex(assembler.AssemblyError, "safe relative path"):
            assembler.artifact_ref("s3://bucket/answer_output.json")
        with self.assertRaisesRegex(assembler.AssemblyError, "safe relative path"):
            assembler.artifact_ref("inputs/fair_baseline_real/../answer_output.json")
        with self.assertRaisesRegex(
            assembler.AssemblyError, "must live under inputs/fair_baseline_real"
        ):
            assembler.artifact_ref("inputs/fair_baseline_reality/answer_output.json")

        outside = assembler.ROOT / "templates" / "fair_external_baseline_run_packet.template.json"
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
        target = assembler.ROOT / "inputs" / "test_fair_baseline_run_validator"
        link = BASE / "fixture_alias"
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target, target_is_directory=True)

        with self.assertRaisesRegex(assembler.AssemblyError, "symlinks are not accepted"):
            assembler.artifact_ref(
                str(
                    (link / "microsoft_graphrag" / "answer_output_artifact.json").relative_to(
                        assembler.ROOT
                    )
                ),
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
