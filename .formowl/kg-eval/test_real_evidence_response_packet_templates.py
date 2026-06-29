#!/usr/bin/env python3
"""Tests for non-evidence operator response-packet templates."""

from __future__ import annotations

import json
import shutil
import unittest

import enterprise_multimodal_collection_packet_generator as enterprise_work_packet
import enterprise_multimodal_packet_assembler as enterprise_assembler
import enterprise_multimodal_response_intake as enterprise_intake
import enterprise_multimodal_validation_validator as enterprise_validator
import fair_baseline_response_intake as fair_intake
import fair_baseline_run_work_packet_generator as fair_work_packet
import fair_external_baseline_packet_assembler as fair_assembler
import fair_external_baseline_run_validator as fair_validator
import human_annotation_adjudication_validator as human_validator
import human_annotation_packet_assembler as human_assembler
import human_annotation_response_intake as human_intake
import human_annotation_work_packet_generator as human_work_packet
import production_adapter_collection_packet_generator as production_work_packet
import production_adapter_packet_assembler as production_assembler
import production_adapter_path_validator as production_validator
import production_adapter_response_intake as production_intake
import real_evidence_response_packet_templates as templates


ROOT = templates.ROOT
TEST_ROOTS = [
    fair_validator.REAL_ARTIFACT_ROOT_PATH / "response_template_test",
    human_validator.REAL_ARTIFACT_ROOT_PATH / "response_template_test",
    enterprise_validator.REAL_ARTIFACT_ROOT_PATH / "response_template_test",
    production_validator.REAL_ARTIFACT_ROOT_PATH / "response_template_test",
]
ASSEMBLY_MANIFESTS = [
    templates.WORK_PACKETS / "test_fair_response_template_candidate_manifest.json",
    templates.WORK_PACKETS / "test_human_response_template_candidate_manifest.json",
    templates.WORK_PACKETS / "test_enterprise_response_template_candidate_manifest.json",
    templates.WORK_PACKETS / "test_production_response_template_candidate_manifest.json",
]


def _load_template(gate_id: str) -> dict:
    path = templates.TEMPLATE_PATHS[gate_id]
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


class RealEvidenceResponsePacketTemplatesTest(unittest.TestCase):
    def setUp(self) -> None:
        for root in TEST_ROOTS:
            shutil.rmtree(root, ignore_errors=True)
        for path in ASSEMBLY_MANIFESTS:
            path.unlink(missing_ok=True)
        self.canonical_before = {
            "fair": fair_assembler.CANONICAL_PACKET_PATH.read_bytes()
            if fair_assembler.CANONICAL_PACKET_PATH.exists()
            else None,
            "human": human_assembler.CANONICAL_PACKET_PATH.read_bytes()
            if human_assembler.CANONICAL_PACKET_PATH.exists()
            else None,
            "enterprise": enterprise_assembler.CANONICAL_PACKET_PATH.read_bytes()
            if enterprise_assembler.CANONICAL_PACKET_PATH.exists()
            else None,
            "production": production_assembler.CANONICAL_PACKET_PATH.read_bytes()
            if production_assembler.CANONICAL_PACKET_PATH.exists()
            else None,
        }

    def tearDown(self) -> None:
        for root in TEST_ROOTS:
            shutil.rmtree(root, ignore_errors=True)
        for path in ASSEMBLY_MANIFESTS:
            path.unlink(missing_ok=True)
        canonical_paths = {
            "fair": fair_assembler.CANONICAL_PACKET_PATH,
            "human": human_assembler.CANONICAL_PACKET_PATH,
            "enterprise": enterprise_assembler.CANONICAL_PACKET_PATH,
            "production": production_assembler.CANONICAL_PACKET_PATH,
        }
        for key, path in canonical_paths.items():
            before = self.canonical_before[key]
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(before)

    def assert_no_outputs(self) -> None:
        for root in TEST_ROOTS:
            self.assertFalse(root.exists())
        for path in ASSEMBLY_MANIFESTS:
            self.assertFalse(path.exists())

    def assert_canonical_unchanged(self) -> None:
        canonical_paths = {
            "fair": fair_assembler.CANONICAL_PACKET_PATH,
            "human": human_assembler.CANONICAL_PACKET_PATH,
            "enterprise": enterprise_assembler.CANONICAL_PACKET_PATH,
            "production": production_assembler.CANONICAL_PACKET_PATH,
        }
        for key, path in canonical_paths.items():
            before = self.canonical_before[key]
            if before is None:
                self.assertFalse(path.exists())
            else:
                self.assertEqual(path.read_bytes(), before)

    def test_check_templates_matches_tracked_outputs(self) -> None:
        report = templates.check_templates()

        self.assertTrue(report["up_to_date"])
        self.assertEqual(report["missing_templates"], [])
        self.assertEqual(report["stale_templates"], [])
        self.assertFalse(report["authority"]["accepts_evidence"])
        self.assertFalse(report["authority"]["writes_candidate_artifacts"])
        self.assertFalse(report["authority"]["writes_canonical_packets"])

    def test_templates_have_expected_contract_markers(self) -> None:
        for gate_id, path in templates.TEMPLATE_PATHS.items():
            with self.subTest(gate_id=gate_id):
                payload = _load_template(gate_id)
                self.assertTrue(payload["template_only"])
                self.assertTrue(payload["do_not_submit_as_evidence"])
                self.assertEqual(payload["gate_id"], gate_id)
                self.assertFalse(payload["claim_boundary"]["accepts_evidence"])
                self.assertFalse(payload["claim_boundary"]["promotes_evidence"])
                self.assertFalse(payload["claim_boundary"]["writes_candidate_artifacts"])
                self.assertFalse(payload["claim_boundary"]["writes_canonical_packets"])
                self.assertFalse(payload["claim_boundary"]["counts_as_acceptance_gate"])
                self.assertEqual(path.parent, templates.WORK_PACKETS)
                self.assertTrue(path.name.endswith("_response_packet.template.json"))

    def test_templates_are_rejected_by_intakes_as_is_without_writes(self) -> None:
        checks = [
            (
                "fair_external_baseline_comparison",
                fair_intake.build_intake_artifacts,
                fair_work_packet.build_work_packet(),
                "inputs/fair_baseline_real/response_template_test/fair_template_run",
                "work_packets/test_fair_response_template_candidate_manifest.json",
            ),
            (
                "annotation_adjudication_protocol",
                human_intake.build_intake_artifacts,
                human_work_packet.build_work_packet(),
                "inputs/human_annotation_real/response_template_test",
                "work_packets/test_human_response_template_candidate_manifest.json",
            ),
            (
                "multimodal_semantic_validation",
                enterprise_intake.build_intake_artifacts,
                enterprise_work_packet.build_work_packet(),
                "inputs/enterprise_multimodal_real/response_template_test/enterprise_template_run",
                "work_packets/test_enterprise_response_template_candidate_manifest.json",
            ),
            (
                "production_adapter_paths",
                production_intake.build_intake_artifacts,
                production_work_packet.build_work_packet(),
                "inputs/production_adapter_real/response_template_test/production_template_run",
                "work_packets/test_production_response_template_candidate_manifest.json",
            ),
        ]
        for gate_id, build, work_packet, output_dir, manifest_output in checks:
            with self.subTest(gate_id=gate_id):
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    build(
                        work_packet=work_packet,
                        response_packet=_load_template(gate_id),
                        output_dir=output_dir,
                        assembly_manifest_output=manifest_output,
                        allow_test_artifacts=True,
                    )

        self.assert_no_outputs()
        self.assert_canonical_unchanged()


if __name__ == "__main__":
    unittest.main()
