#!/usr/bin/env python3
"""Tests for remaining real-evidence preflight reporting."""

from __future__ import annotations

import json
import shutil
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import real_evidence_preflight as preflight
import test_human_annotation_adjudication_validator as human_fixtures


CANONICAL_PACKETS = [gate["input_packet"] for gate in preflight.EXPECTED_GATES.values()]


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


class RealEvidencePreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_packets: dict[Path, bytes | None] = {
            path: path.read_bytes() if path.exists() else None for path in CANONICAL_PACKETS
        }
        self._saved_checklist = preflight.CHECKLIST_PATH.read_bytes()
        for gate in preflight.EXPECTED_GATES.values():
            shutil.rmtree(gate["real_root"] / "preflight_test", ignore_errors=True)
            shutil.rmtree(gate["real_root"] / "assembler_test", ignore_errors=True)
            shutil.rmtree(gate["real_root"] / "validator_fixture", ignore_errors=True)
            shutil.rmtree(gate["real_root"] / "release_artifacts", ignore_errors=True)
        shutil.rmtree(preflight.INPUTS / "test_preflight_fixture_inputs", ignore_errors=True)

    def tearDown(self) -> None:
        for path, content in self._saved_packets.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        preflight.CHECKLIST_PATH.write_bytes(self._saved_checklist)
        for gate in preflight.EXPECTED_GATES.values():
            shutil.rmtree(gate["real_root"] / "preflight_test", ignore_errors=True)
            shutil.rmtree(gate["real_root"] / "assembler_test", ignore_errors=True)
            shutil.rmtree(gate["real_root"] / "validator_fixture", ignore_errors=True)
            shutil.rmtree(gate["real_root"] / "release_artifacts", ignore_errors=True)
        shutil.rmtree(preflight.INPUTS / "test_preflight_fixture_inputs", ignore_errors=True)

    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _gate(self, report: dict, gate_id: str) -> dict:
        return {row["gate_id"]: row for row in report["gates"]}[gate_id]

    def test_missing_real_packets_keep_preflight_blocked_and_match_total_snapshot(self) -> None:
        report = preflight.build_report()

        self.assertEqual(report["preflight_state"], "blocked")
        self.assertFalse(report["preflight_authority"]["accepts_evidence"])
        self.assertFalse(report["preflight_authority"]["promotes_evidence"])
        self.assertEqual(report["summary"]["validator_clear_gate_count"], 0)
        self.assertEqual(
            report["summary"]["blocked_gate_ids"],
            [
                "fair_external_baseline_comparison",
                "annotation_adjudication_protocol",
                "multimodal_semantic_validation",
                "production_adapter_paths",
            ],
        )
        self.assertEqual(report["checklist_sync"]["status"], "synchronized")
        self.assertEqual(
            report["summary"]["total_acceptance_failed_gate_ids"],
            report["summary"]["blocked_gate_ids"],
        )
        self.assertNotIn("overall_ready", report)
        self.assertNotIn("claim_boundary", report)
        self.assertFalse(any(key.startswith("supports_") for key in nested_keys(report)))
        for row in report["gates"]:
            self.assertEqual(row["validator_status"], "blocked")
            self.assertFalse(row["packet_surface"]["present"])
            self.assertEqual(row["packet_surface"]["packet_state"], "missing")
            self.assertEqual(row["collection_state"], "missing_real_artifacts_and_packet")
            self.assertTrue(row["validator_blockers"])
            self.assertFalse(row["real_root_scan"]["root_ready"])

    def test_preflight_remains_non_authoritative_when_validators_are_mocked_clear(self) -> None:
        fake_report = {"passed": True, "blockers": [], "metrics": {}, "packet_sha256": "a" * 64}
        patches = [
            mock.patch.object(gate["validator"], "build_report", return_value=fake_report)
            for gate in preflight.EXPECTED_GATES.values()
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        report = preflight.build_report()

        self.assertFalse(report["preflight_authority"]["accepts_evidence"])
        self.assertFalse(report["preflight_authority"]["promotes_evidence"])
        self.assertFalse(report["preflight_authority"]["writes_canonical_packets"])
        self.assertFalse(report["preflight_authority"]["counts_as_acceptance_gate"])
        self.assertEqual(report["preflight_state"], "blocked")
        self.assertEqual(report["summary"]["broad_validator_status"], "clear")
        self.assertEqual(report["summary"]["canonical_collection_status"], "blocked")
        self.assertFalse(any(key.startswith("supports_") for key in nested_keys(report)))

    def test_templates_are_reported_as_non_evidence_and_rejected_by_validators(self) -> None:
        report = preflight.build_report()

        for row in report["gates"]:
            template_guard = row["template_guard"]
            self.assertTrue(template_guard["template_exists"])
            self.assertTrue(template_guard["template_contains_non_evidence_markers"])
            self.assertTrue(template_guard["template_outside_canonical_input_path"])
            self.assertEqual(template_guard["template_validator_status"], "blocked")
            self.assertTrue(template_guard["template_rejected_by_validator"])
            self.assertTrue(template_guard["template_validator_blockers"])

    def test_canonical_template_payload_is_detected_and_cannot_clear_collection(self) -> None:
        gate = preflight.EXPECTED_GATES["annotation_adjudication_protocol"]
        template = preflight.load_json(gate["template"])
        self._write_json(gate["input_packet"], template)

        report = preflight.build_report()
        row = self._gate(report, "annotation_adjudication_protocol")

        self.assertEqual(report["preflight_state"], "blocked")
        self.assertEqual(row["validator_status"], "blocked")
        self.assertEqual(row["collection_state"], "partial_canonical_packet")
        self.assertTrue(row["packet_surface"]["present"])
        self.assertTrue(row["packet_surface"]["partial_packet"])
        self.assertTrue(row["packet_surface"]["contains_template_marker"])

    def test_partial_real_artifact_without_valid_packet_is_counted_but_not_accepted(self) -> None:
        gate = preflight.EXPECTED_GATES["annotation_adjudication_protocol"]
        artifact = gate["real_root"] / "preflight_test" / "manifest.json"
        self._write_json(
            artifact,
            {
                "artifact_type": "human_annotation_manifest_v1",
                "items": [],
            },
        )

        report = preflight.build_report()
        row = self._gate(report, "annotation_adjudication_protocol")

        self.assertEqual(row["collection_state"], "real_artifacts_present_without_valid_packet")
        self.assertEqual(row["real_root_scan"]["file_count"], 1)
        self.assertEqual(row["real_root_scan"]["test_or_sandbox_file_count"], 1)
        self.assertEqual(row["real_root_scan"]["candidate_artifact_count"], 0)
        self.assertEqual(row["real_root_scan"]["candidate_artifact_paths"], [])
        self.assertFalse(row["real_root_scan"]["root_ready"])

    def test_mixed_real_root_with_sandbox_leftover_is_not_ready(self) -> None:
        gate = preflight.EXPECTED_GATES["annotation_adjudication_protocol"]
        candidate = gate["real_root"] / "release_artifacts" / "manifest.json"
        sandbox = gate["real_root"] / "assembler_test" / "leftover.json"
        self._write_json(
            candidate,
            {
                "artifact_type": "human_annotation_manifest_v1",
                "items": [],
            },
        )
        self._write_json(
            sandbox,
            {
                "artifact_type": "human_annotation_manifest_v1",
                "items": [],
            },
        )

        report = preflight.build_report()
        row = self._gate(report, "annotation_adjudication_protocol")

        self.assertEqual(row["real_root_scan"]["file_count"], 2)
        self.assertEqual(row["real_root_scan"]["candidate_artifact_count"], 1)
        self.assertEqual(row["real_root_scan"]["test_or_sandbox_file_count"], 1)
        self.assertEqual(
            row["real_root_scan"]["candidate_artifact_paths"],
            ["inputs/human_annotation_real/release_artifacts/manifest.json"],
        )
        self.assertFalse(row["real_root_scan"]["root_ready"])
        self.assertFalse(report["summary"]["no_packet_or_artifact_hazards"])

    def test_valid_packet_nearby_does_not_replace_missing_canonical_packet(self) -> None:
        gate = preflight.EXPECTED_GATES["annotation_adjudication_protocol"]
        nearby_packet = gate["real_root"] / "assembler_test" / "promoted_packet.json"
        self._write_json(nearby_packet, human_fixtures.valid_packet())
        shutil.rmtree(gate["real_root"] / "validator_fixture", ignore_errors=True)

        report = preflight.build_report()
        row = self._gate(report, "annotation_adjudication_protocol")

        self.assertFalse(row["packet_surface"]["present"])
        self.assertEqual(row["packet_surface"]["packet_state"], "missing")
        self.assertEqual(row["collection_state"], "real_artifacts_present_without_valid_packet")
        self.assertEqual(row["real_root_scan"]["test_or_sandbox_file_count"], 1)
        self.assertEqual(row["real_root_scan"]["candidate_artifact_paths"], [])

    def test_canonical_packet_referencing_test_fixtures_is_rejected_by_preflight_refs(self) -> None:
        gate = preflight.EXPECTED_GATES["annotation_adjudication_protocol"]
        self._write_json(gate["input_packet"], human_fixtures.valid_packet())
        shutil.rmtree(gate["real_root"] / "validator_fixture", ignore_errors=True)

        report = preflight.build_report()
        row = self._gate(report, "annotation_adjudication_protocol")
        refs = row["packet_surface"]["artifact_references"]

        self.assertEqual(row["validator_status"], "blocked")
        self.assertEqual(row["collection_state"], "partial_canonical_packet")
        self.assertTrue(row["validator_blockers"])
        self.assertGreater(refs["reference_count"], 0)
        self.assertEqual(refs["real_root_artifact_count"], 0)
        self.assertEqual(refs["rejected_reference_count"], refs["reference_count"])
        self.assertEqual(refs["rejected_statuses"], ["fixture_rejected"])

    def test_partial_canonical_packet_is_classified_separately_from_missing(self) -> None:
        gate = preflight.EXPECTED_GATES["annotation_adjudication_protocol"]
        self._write_json(
            gate["input_packet"],
            {
                "artifact_id": "human_annotation_results_v1",
                "evidence_kind": "real_human_annotation_adjudication",
                "recovered_after_tmp_loss": False,
            },
        )

        report = preflight.build_report()
        row = self._gate(report, "annotation_adjudication_protocol")

        self.assertTrue(row["packet_surface"]["present"])
        self.assertTrue(row["packet_surface"]["partial_packet"])
        self.assertEqual(row["packet_surface"]["packet_state"], "partial")
        self.assertEqual(row["validator_status"], "blocked")
        self.assertEqual(row["collection_state"], "partial_canonical_packet")
        self.assertTrue(row["validator_blockers"])

    def test_malformed_canonical_packet_json_is_reported_without_crashing(self) -> None:
        gate = preflight.EXPECTED_GATES["annotation_adjudication_protocol"]
        gate["input_packet"].parent.mkdir(parents=True, exist_ok=True)
        gate["input_packet"].write_text("{not-json", encoding="utf-8")

        report = preflight.build_report()
        row = self._gate(report, "annotation_adjudication_protocol")

        self.assertEqual(report["preflight_state"], "blocked")
        self.assertEqual(row["validator_status"], "blocked")
        self.assertEqual(row["packet_surface"]["packet_state"], "invalid_json_or_non_object")
        self.assertIn("JSON malformed", row["packet_surface"]["packet_error"])
        self.assertTrue(row["validator_blockers"])
        self.assertIn("canonical input packet JSON malformed", row["validator_blockers"][0])
        self.assertIsNotNone(report["summary"]["total_acceptance_report_error"])
        self.assertFalse(any(key.startswith("supports_") for key in nested_keys(report)))

    def test_symlinked_canonical_packet_is_rejected_before_validator_can_accept_it(self) -> None:
        gate = preflight.EXPECTED_GATES["annotation_adjudication_protocol"]
        nearby_packet = gate["real_root"] / "assembler_test" / "promoted_packet.json"
        self._write_json(nearby_packet, human_fixtures.valid_packet())
        shutil.rmtree(gate["real_root"] / "validator_fixture", ignore_errors=True)
        gate["input_packet"].unlink(missing_ok=True)
        gate["input_packet"].symlink_to(nearby_packet)

        report = preflight.build_report()
        row = self._gate(report, "annotation_adjudication_protocol")

        self.assertEqual(report["preflight_state"], "blocked")
        self.assertEqual(row["validator_status"], "blocked")
        self.assertEqual(row["packet_surface"]["packet_state"], "symlink_rejected")
        self.assertTrue(row["packet_surface"]["symlink_rejected"])
        self.assertEqual(row["collection_state"], "validator_failed_canonical_packet")
        self.assertIn("canonical input packet is a symlink", row["validator_blockers"])
        self.assertNotEqual(row["collection_state"], "canonical_packet_validator_clear")

    def test_recursive_template_placeholder_and_raw_markers_are_detected_in_real_root(self) -> None:
        gate = preflight.EXPECTED_GATES["annotation_adjudication_protocol"]
        artifact = gate["real_root"] / "preflight_test" / "nested_bad.json"
        self._write_json(
            artifact,
            {
                "artifact_type": "human_annotation_manifest_v1",
                "nested": {
                    "template_only": True,
                    "notes": "fill-with-real-reviewer",
                    "storage_uri": "postgresql+psycopg2://internal/db",
                    "windows_path": "C:\\secret\\labels.json",
                },
            },
        )

        report = preflight.build_report()
        row = self._gate(report, "annotation_adjudication_protocol")

        self.assertEqual(row["real_root_scan"]["template_marker_file_count"], 1)
        self.assertEqual(row["real_root_scan"]["placeholder_marker_file_count"], 1)
        self.assertEqual(row["real_root_scan"]["raw_internal_marker_file_count"], 1)
        self.assertFalse(row["real_root_scan"]["root_ready"])
        self.assertFalse(report["summary"]["no_packet_or_artifact_hazards"])

    def test_fixture_inputs_are_separate_from_real_artifact_roots(self) -> None:
        fixture = preflight.INPUTS / "test_preflight_fixture_inputs" / "fixture.json"
        self._write_json(fixture, {"artifact_type": "test_fixture_only"})

        report = preflight.build_report()

        self.assertGreater(report["test_fixture_inputs"]["fixture_root_count"], 0)
        self.assertGreater(report["test_fixture_inputs"]["fixture_file_count"], 0)
        for row in report["gates"]:
            self.assertEqual(row["real_root_scan"]["file_count"], 0)
            self.assertEqual(row["real_root_scan"]["candidate_artifact_paths"], [])
            self.assertFalse(row["real_root_scan"]["root_ready"])

    def test_checklist_sync_detects_objective_audit_and_blocker_drift(self) -> None:
        checklist = preflight.load_json(preflight.CHECKLIST_PATH)
        checklist["objective_audit_sha256"] = "0" * 64
        checklist["source_snapshot"] = "wrong/snapshot.json"
        checklist["remaining_gates"][0]["current_blockers"] = ["corrupted blocker"]
        preflight.CHECKLIST_PATH.write_text(
            json.dumps(checklist, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        report = preflight.build_report()

        self.assertEqual(report["checklist_sync"]["status"], "drifted")
        self.assertFalse(
            report["checklist_sync"]["checklist_objective_audit_sha256_matches_current"]
        )
        self.assertFalse(report["checklist_sync"]["checklist_source_snapshot_path_matches"])
        first_gate = self._gate(report, "fair_external_baseline_comparison")
        self.assertEqual(first_gate["checklist_current_blockers"], ["corrupted blocker"])
        self.assertNotEqual(
            first_gate["checklist_current_blockers"], first_gate["validator_blockers"]
        )

    def test_main_writes_preflight_result_without_mutating_acceptance_snapshot(self) -> None:
        snapshot_path = preflight.RESULTS / "kg_total_acceptance_snapshot.json"
        before_snapshot = snapshot_path.read_bytes()
        with redirect_stdout(StringIO()):
            preflight.main()
        output = preflight.load_json(preflight.OUTPUT_PATH)

        self.assertEqual(snapshot_path.read_bytes(), before_snapshot)
        self.assertEqual(output["artifact_id"], "kg_real_evidence_preflight_v1")
        self.assertEqual(output["preflight_state"], "blocked")
        self.assertEqual(output["summary"]["blocked_gate_count"], 4)


if __name__ == "__main__":
    unittest.main()
