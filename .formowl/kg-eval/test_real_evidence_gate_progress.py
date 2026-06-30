#!/usr/bin/env python3
"""Tests for the non-authoritative real-evidence gate progress report."""

from __future__ import annotations

import json
import os
import shutil
import unittest
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import real_evidence_gate_progress as progress


ROOT = Path(__file__).resolve().parent
BLOCKED_GATE_IDS = ["multimodal_semantic_validation"]
CURRENT_BLOCKED_GATE_IDS = [
    "fair_external_baseline_comparison",
    "annotation_adjudication_protocol",
    "multimodal_semantic_validation",
    "production_adapter_paths",
]


def blocked_preflight_report() -> dict:
    report = deepcopy(progress.preflight.build_report())
    report["preflight_state"] = "blocked"
    report["summary"]["blocked_gate_ids"] = list(BLOCKED_GATE_IDS)
    report["summary"]["blocked_gate_count"] = len(BLOCKED_GATE_IDS)
    report["summary"]["total_acceptance_state"] = "blocked"
    report["summary"]["total_acceptance_failed_gate_ids"] = list(BLOCKED_GATE_IDS)
    for row in report["gates"]:
        if row["gate_id"] not in BLOCKED_GATE_IDS:
            continue
        row["current_total_gate_state"] = "blocked"
        row["current_total_gate_blockers"] = ["missing_operator_response"]
        row["validator_status"] = "blocked"
        row["validator_blockers"] = ["missing_operator_response"]
        row["collection_state"] = "missing_real_artifacts_and_packet"
        row["packet_surface"].update(
            {
                "present": False,
                "sha256": None,
                "packet_state": "missing",
            }
        )
        row["real_root_scan"] = {
            "root_exists": True,
            "root_ready": False,
            "file_count": 0,
            "candidate_artifact_count": 0,
            "symlink_count": 0,
            "disappeared_file_count": 0,
            "test_or_sandbox_file_count": 0,
            "template_marker_file_count": 0,
            "placeholder_marker_file_count": 0,
            "raw_internal_marker_file_count": 0,
            "candidate_artifact_paths": [],
            "disappeared_file_paths": [],
        }
    return report


def blocked_work_order_report(preflight_report: dict) -> dict:
    gate_status_sha256 = preflight_report["summary"]["gate_status_sha256"]
    return {
        "artifact_id": "kg_real_evidence_collection_work_orders_v1",
        "workspace": ".formowl/kg-eval",
        "source_preflight": "results/real_evidence_preflight.json",
        "summary": {
            "preflight_blocked_gate_ids": list(BLOCKED_GATE_IDS),
            "gate_status_sha256": gate_status_sha256,
        },
        "sync": {"status": "synchronized"},
        "work_orders": [
            {
                "gate_id": "multimodal_semantic_validation",
                "current_blockers": ["missing_operator_response"],
            }
        ],
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


class RealEvidenceGateProgressTest(unittest.TestCase):
    def setUp(self) -> None:
        self.output = progress.OUTPUT_PATH
        self.gate_id = "multimodal_semantic_validation"
        self.candidate_manifest = (
            "work_packets/multimodal_semantic_validation_candidate_manifest.json"
        )
        self.manifest = (
            ROOT / "work_packets" / "multimodal_semantic_validation_candidate_manifest.json"
        )
        self.validation_report = (
            ROOT / "work_packets" / "progress_unitcase_candidate_validation_report.json"
        )
        self.hazard_source = ROOT / "work_packets" / "progress_unitcase_manifest_source.json"
        self.approval_manifest = ROOT / "work_packets" / "progress_unitcase_approval_manifest.json"
        self.actual_validation_report = (
            ROOT
            / "work_packets"
            / "multimodal_semantic_validation_candidate_validation_report.json"
        )
        self.actual_approval_manifest = (
            ROOT / "work_packets" / "multimodal_semantic_validation_approval_manifest.json"
        )
        self._managed_paths = list(
            dict.fromkeys(
                [
                    self.output,
                    self.manifest,
                    self.actual_validation_report,
                    self.actual_approval_manifest,
                    self.validation_report,
                    self.hazard_source,
                    self.approval_manifest,
                    *sorted((ROOT / "work_packets").glob("*_candidate_validation_report.json")),
                    *sorted((ROOT / "work_packets").glob("*_approval_manifest.json")),
                ]
            )
        )
        self._snapshots = {path: self._snapshot_path(path) for path in self._managed_paths}
        for path in self._managed_paths:
            self._clear_path(path)

    def tearDown(self) -> None:
        for path in self._managed_paths:
            self._restore_path(path, self._snapshots[path])

    def _snapshot_path(self, path: Path) -> dict:
        if path.is_symlink():
            return {"kind": "symlink", "target": path.readlink()}
        if path.is_file():
            return {"kind": "file", "bytes": path.read_bytes()}
        if path.is_dir():
            return {"kind": "dir"}
        return {"kind": "missing"}

    def _clear_path(self, path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)

    def _restore_path(self, path: Path, snapshot: dict) -> None:
        self._clear_path(path)
        kind = snapshot["kind"]
        if kind == "missing":
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "file":
            path.write_bytes(snapshot["bytes"])
        elif kind == "symlink":
            path.symlink_to(snapshot["target"])
        elif kind == "dir":
            path.mkdir()

    def _gate(self, report: dict, gate_id: str) -> dict:
        return {row["gate_id"]: row for row in report["gate_progress"]}[gate_id]

    def _blocked_report(self) -> dict:
        preflight_report = blocked_preflight_report()
        return progress.build_report(
            preflight_report_override=preflight_report,
            work_order_report_override=blocked_work_order_report(preflight_report),
        )

    def _write_validation_report(
        self,
        *,
        candidate_manifest_sha256: str,
        candidate_manifest: str | None = None,
        status: str = "passed",
    ) -> None:
        if candidate_manifest is None:
            candidate_manifest = self.candidate_manifest
        payload = {
            "artifact_id": "kg_real_evidence_candidate_manifest_validation_v1",
            "overall_success": status == "passed",
            "validation_results": [
                {
                    "sequence": 1,
                    "gate_id": self.gate_id,
                    "candidate_manifest": candidate_manifest,
                    "candidate_manifest_sha256": candidate_manifest_sha256,
                    "assembler_script": "enterprise_multimodal_packet_assembler.py",
                    "canonical_packet_not_written": (
                        "inputs/enterprise_multimodal_validation_packet.json"
                    ),
                    "argv": [
                        "python3",
                        "enterprise_multimodal_packet_assembler.py",
                        "--assembly-manifest",
                        self.candidate_manifest,
                        "--validate",
                    ],
                    "exit_code": 0 if status == "passed" else 1,
                    "status": status,
                    "stdout_summary": {"passed": status == "passed"},
                    "canonical_packet_integrity": {"passed": True},
                }
            ],
        }
        self.validation_report.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def test_current_baseline_reports_all_remaining_gate_progress(self) -> None:
        report = progress.build_report()

        self.assertEqual(report["artifact_id"], "kg_real_evidence_gate_progress_v1")
        self.assertFalse(report["progress_authority"]["accepts_evidence"])
        self.assertFalse(report["progress_authority"]["reads_operator_response_packets"])
        self.assertFalse(report["progress_authority"]["reads_candidate_artifact_contents"])
        self.assertFalse(report["progress_authority"]["writes_candidate_artifacts"])
        self.assertFalse(report["progress_authority"]["writes_canonical_packets"])
        self.assertFalse(report["progress_authority"]["promotes_evidence"])
        self.assertFalse(report["progress_authority"]["counts_as_acceptance_gate"])
        self.assertEqual(report["summary"]["gate_count"], 4)
        self.assertEqual(report["summary"]["gate_ids"], CURRENT_BLOCKED_GATE_IDS)
        self.assertEqual(report["summary"]["blocked_gate_ids"], CURRENT_BLOCKED_GATE_IDS)
        self.assertEqual(report["summary"]["stage_counts"], {"missing_operator_response": 4})
        self.assertEqual(report["summary"]["candidate_manifest_regular_gate_count"], 0)
        self.assertEqual(report["summary"]["candidate_validation_clear_gate_count"], 0)
        self.assertEqual(report["summary"]["valid_approval_manifest_gate_count"], 0)
        self.assertEqual(report["summary"]["canonical_validator_clear_gate_count"], 0)
        self.assertEqual(report["summary"]["rejected_approval_manifest_surface_count"], 0)
        self.assertEqual(report["progress_state"], "report_current_from_persisted_sources")
        self.assertTrue(report["source_report_contract"]["valid"])
        self.assertEqual(
            report["source_report_contract"]["historical_monitored_gate_ids"],
            CURRENT_BLOCKED_GATE_IDS,
        )
        self.assertEqual(
            report["source_report_contract"]["current_blocked_gate_ids"],
            CURRENT_BLOCKED_GATE_IDS,
        )
        root_text = str(ROOT)
        self.assertFalse(
            any(
                value == root_text or value.startswith(f"{root_text}/")
                for value in nested_strings(report)
            )
        )
        self.assertEqual(
            [row["gate_id"] for row in report["gate_progress"]], CURRENT_BLOCKED_GATE_IDS
        )
        for row in report["gate_progress"]:
            self.assertEqual(row["stage"], "missing_operator_response")

    def test_build_report_uses_persisted_reports_without_refreshing_preflight(self) -> None:
        original_preflight_build = progress.preflight.build_report
        original_work_order_build = progress.work_orders.build_report

        def fail_refresh(*_args: object, **_kwargs: object) -> dict:
            raise AssertionError("progress report must not refresh source reports")

        progress.preflight.build_report = fail_refresh
        progress.work_orders.build_report = fail_refresh
        try:
            report = progress.build_report()
        finally:
            progress.preflight.build_report = original_preflight_build
            progress.work_orders.build_report = original_work_order_build

        self.assertEqual(report["artifact_id"], "kg_real_evidence_gate_progress_v1")
        self.assertEqual(report["summary"]["gate_count"], 4)
        self.assertFalse(report["progress_authority"]["reads_candidate_artifact_contents"])

    def test_missing_source_reports_withhold_gate_progress(self) -> None:
        report = progress.build_report(
            preflight_report_override={},
            work_order_report_override={},
        )

        self.assertEqual(
            report["progress_state"],
            "withheld_due_to_source_report_contract",
        )
        self.assertFalse(report["source_report_contract"]["valid"])
        self.assertEqual(report["summary"]["gate_count"], 0)
        self.assertEqual(report["summary"]["stage_counts"], {})
        self.assertEqual(report["gate_progress"], [])
        self.assertIn("preflight_artifact_id", report["source_report_contract"]["blockers"])
        self.assertFalse(report["progress_authority"]["reads_candidate_artifact_contents"])

    def test_source_report_sync_mismatch_withholds_gate_progress(self) -> None:
        preflight_report = progress._load_json(progress.preflight.OUTPUT_PATH)
        work_order_report = progress._load_json(progress.work_orders.OUTPUT_PATH)
        work_order_report["summary"]["gate_status_sha256"] = "stale"

        report = progress.build_report(
            preflight_report_override=preflight_report,
            work_order_report_override=work_order_report,
        )

        self.assertEqual(
            report["progress_state"],
            "withheld_due_to_source_report_contract",
        )
        self.assertFalse(report["source_report_contract"]["valid"])
        self.assertIn(
            "work_order_gate_status_hash_matches_preflight",
            report["source_report_contract"]["blockers"],
        )
        self.assertEqual(report["gate_progress"], [])

    def test_candidate_manifest_moves_only_that_gate_to_validation_stage(self) -> None:
        self.manifest.write_text("candidate manifest bytes\n", encoding="utf-8")

        report = self._blocked_report()
        row = self._gate(report, self.gate_id)

        self.assertEqual(row["stage"], "candidate_manifest_present_pending_validation")
        self.assertEqual(row["candidate_manifest"]["state"], "regular")
        self.assertEqual(row["candidate_validation"]["clear_report_count"], 0)
        self.assertIn("validate-candidate-manifests", row["next_action"])
        self.assertFalse(report["progress_authority"]["writes_canonical_packets"])
        self.assertFalse(report["progress_authority"]["counts_as_acceptance_gate"])

    def test_current_candidate_validation_report_moves_gate_to_approval_stage(self) -> None:
        self.manifest.write_text("candidate manifest bytes\n", encoding="utf-8")
        manifest_sha = progress._sha256_file(self.manifest)
        assert manifest_sha is not None
        self._write_validation_report(candidate_manifest_sha256=manifest_sha)

        report = self._blocked_report()
        row = self._gate(report, self.gate_id)

        self.assertEqual(row["stage"], "candidate_validation_clear_pending_approval")
        self.assertEqual(row["candidate_validation"]["report_count"], 1)
        self.assertEqual(row["candidate_validation"]["clear_report_count"], 1)
        self.assertEqual(
            row["candidate_validation"]["reports"][0]["candidate_manifest"],
            self.candidate_manifest,
        )
        self.assertTrue(
            row["candidate_validation"]["reports"][0]["candidate_manifest_sha256_current"]
        )
        self.assertIn("manual governance review", row["next_action"])
        self.assertFalse(report["progress_authority"]["promotes_evidence"])

    def test_stale_candidate_validation_report_does_not_claim_approval_stage(self) -> None:
        self.manifest.write_text("old candidate manifest bytes\n", encoding="utf-8")
        old_sha = progress._sha256_file(self.manifest)
        assert old_sha is not None
        self._write_validation_report(candidate_manifest_sha256=old_sha)
        self.manifest.write_text("new candidate manifest bytes\n", encoding="utf-8")

        report = self._blocked_report()
        row = self._gate(report, self.gate_id)

        self.assertEqual(row["stage"], "candidate_validation_failed_or_stale")
        self.assertEqual(row["candidate_validation"]["report_count"], 1)
        self.assertEqual(row["candidate_validation"]["clear_report_count"], 0)
        self.assertFalse(
            row["candidate_validation"]["reports"][0]["candidate_manifest_sha256_current"]
        )
        self.assertIn("rerun validate-candidate-manifests", row["next_action"])

    def test_symlink_candidate_manifest_is_not_read_or_marked_current(self) -> None:
        self.hazard_source.write_text("candidate manifest bytes\n", encoding="utf-8")
        manifest_sha = progress._sha256_file(self.hazard_source)
        assert manifest_sha is not None
        self.manifest.symlink_to(self.hazard_source.name)
        self._write_validation_report(candidate_manifest_sha256=manifest_sha)

        report = self._blocked_report()
        row = self._gate(report, self.gate_id)

        self.assertEqual(row["candidate_manifest"]["state"], "symlink_rejected")
        self.assertEqual(row["stage"], "candidate_validation_failed_or_stale")
        self.assertEqual(row["candidate_validation"]["clear_report_count"], 0)
        self.assertEqual(
            row["candidate_validation"]["reports"][0]["candidate_manifest_surface_state"],
            "symlink_rejected",
        )
        self.assertFalse(
            row["candidate_validation"]["reports"][0]["candidate_manifest_sha256_current"]
        )

    def test_hardlink_candidate_manifest_is_not_read_or_marked_current(self) -> None:
        self.hazard_source.write_text("candidate manifest bytes\n", encoding="utf-8")
        manifest_sha = progress._sha256_file(self.hazard_source)
        assert manifest_sha is not None
        os.link(self.hazard_source, self.manifest)
        self._write_validation_report(candidate_manifest_sha256=manifest_sha)

        report = self._blocked_report()
        row = self._gate(report, self.gate_id)

        self.assertEqual(row["candidate_manifest"]["state"], "hardlink_rejected")
        self.assertEqual(row["stage"], "candidate_validation_failed_or_stale")
        self.assertEqual(row["candidate_validation"]["clear_report_count"], 0)
        self.assertEqual(
            row["candidate_validation"]["reports"][0]["candidate_manifest_surface_state"],
            "hardlink_rejected",
        )
        self.assertFalse(
            row["candidate_validation"]["reports"][0]["candidate_manifest_sha256_current"]
        )

    def test_rejected_approval_manifest_surface_is_reported(self) -> None:
        self.hazard_source.write_text(
            json.dumps(
                {
                    "manifest_type": "kg_real_evidence_governance_approval_v1",
                    "gate_id": self.gate_id,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.approval_manifest.symlink_to(self.hazard_source.name)

        report = self._blocked_report()

        self.assertEqual(report["summary"]["rejected_approval_manifest_surface_count"], 1)
        self.assertEqual(
            report["work_packet_hazards"]["rejected_approval_manifest_surfaces"][0][
                "approval_manifest"
            ],
            "work_packets/progress_unitcase_approval_manifest.json",
        )
        self.assertEqual(
            report["work_packet_hazards"]["rejected_approval_manifest_surfaces"][0][
                "approval_surface_state"
            ],
            "symlink_rejected",
        )
        self.assertEqual(
            self._gate(report, self.gate_id)["governance_approval"]["approval_manifest_count"],
            0,
        )

    def test_unexpected_validation_report_manifest_path_is_redacted(self) -> None:
        self.manifest.write_text("candidate manifest bytes\n", encoding="utf-8")
        manifest_sha = progress._sha256_file(self.manifest)
        assert manifest_sha is not None
        self._write_validation_report(
            candidate_manifest="/tmp/raw-secret.json",
            candidate_manifest_sha256=manifest_sha,
        )

        report = self._blocked_report()
        row = self._gate(report, self.gate_id)

        self.assertEqual(row["stage"], "candidate_validation_failed_or_stale")
        self.assertFalse(
            row["candidate_validation"]["reports"][0]["candidate_manifest_matches_gate"]
        )
        self.assertEqual(
            row["candidate_validation"]["reports"][0]["candidate_manifest"],
            "<unexpected-candidate-manifest>",
        )
        self.assertNotIn("/tmp/raw-secret.json", "\n".join(nested_strings(report)))

    def test_main_writes_only_non_authoritative_progress_report(self) -> None:
        before_real_roots = {
            path: sorted(child.relative_to(ROOT) for child in path.rglob("*"))
            for path in [
                ROOT / "inputs" / "fair_baseline_real",
                ROOT / "inputs" / "human_annotation_real",
                ROOT / "inputs" / "enterprise_multimodal_real",
                ROOT / "inputs" / "production_adapter_real",
            ]
        }
        canonical_packets = [
            ROOT / "inputs" / "fair_external_baseline_run_packet.json",
            ROOT / "inputs" / "human_annotation_results_v1.json",
            ROOT / "inputs" / "enterprise_multimodal_validation_packet.json",
            ROOT / "inputs" / "production_adapter_evidence_packet.json",
        ]
        canonical_before = {
            path: path.read_bytes() if path.exists() and path.is_file() else None
            for path in canonical_packets
        }
        stdout = StringIO()

        with redirect_stdout(stdout):
            result = progress.main([])

        self.assertEqual(result, 0)
        self.assertTrue(self.output.exists())
        written = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(written["artifact_id"], "kg_real_evidence_gate_progress_v1")
        self.assertFalse(written["progress_authority"]["counts_as_acceptance_gate"])
        self.assertFalse(written["progress_authority"]["writes_canonical_packets"])
        self.assertFalse(written["progress_authority"]["promotes_evidence"])
        for path in canonical_packets:
            if canonical_before[path] is None:
                self.assertFalse(path.exists() or path.is_symlink())
            else:
                self.assertEqual(path.read_bytes(), canonical_before[path])
        after_real_roots = {
            path: sorted(child.relative_to(ROOT) for child in path.rglob("*"))
            for path in before_real_roots
        }
        self.assertEqual(after_real_roots, before_real_roots)


if __name__ == "__main__":
    unittest.main()
