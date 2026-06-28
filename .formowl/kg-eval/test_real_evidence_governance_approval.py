#!/usr/bin/env python3
"""Tests for governed real-evidence canonical packet promotion approval."""

from __future__ import annotations

import json
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import real_evidence_governance_approval as approval


ROOT = approval.ROOT
EXPECTED = approval.submission_manifest.EXPECTED_BY_GATE["annotation_adjudication_protocol"]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class RealEvidenceGovernanceApprovalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate_manifest = ROOT / EXPECTED.assembly_manifest_output
        self.validation_report = (
            ROOT / "work_packets" / "operatorapproval_unitcase_candidate_validation_report.json"
        )
        self.approval_manifest = (
            ROOT / "work_packets" / "operatorapproval_unitcase_approval_manifest.json"
        )
        self.created_paths = [
            self.validation_report,
            self.approval_manifest,
        ]
        self.before_candidate_manifest = (
            self.candidate_manifest.read_bytes() if self.candidate_manifest.exists() else None
        )
        self.before_canonical_packets = {
            rel_path: (ROOT / rel_path).read_bytes() if (ROOT / rel_path).exists() else None
            for rel_path in approval.submission_manifest.CANONICAL_INPUT_PACKETS
        }
        for path in self.created_paths:
            if path.exists() or path.is_symlink():
                path.unlink()
        if self.candidate_manifest.exists() or self.candidate_manifest.is_symlink():
            self.candidate_manifest.unlink()

    def tearDown(self) -> None:
        for path in self.created_paths:
            if path.exists() or path.is_symlink():
                path.unlink()
        if self.before_candidate_manifest is None:
            if self.candidate_manifest.exists() or self.candidate_manifest.is_symlink():
                self.candidate_manifest.unlink()
        else:
            self.candidate_manifest.parent.mkdir(parents=True, exist_ok=True)
            self.candidate_manifest.write_bytes(self.before_candidate_manifest)
        for rel_path, before in self.before_canonical_packets.items():
            path = ROOT / rel_path
            if before is None:
                if path.exists() or path.is_symlink():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(before)

    def write_candidate_manifest(self, payload: dict[str, object] | None = None) -> str:
        write_json(
            self.candidate_manifest,
            payload
            if payload is not None
            else {
                "artifact_id": "operatorapproval_unitcase_candidate_manifest",
                "evidence_kind": "operatorapproval_unitcase",
            },
        )
        return approval._sha256_file(self.candidate_manifest)

    def validation_report_payload(self, candidate_sha: str) -> dict[str, object]:
        return {
            "artifact_id": "kg_real_evidence_candidate_manifest_validation_v1",
            "valid_manifest": True,
            "overall_success": True,
            "candidate_manifest_preflight_passed": True,
            "authority": {
                "accepts_evidence": False,
                "promotes_evidence": False,
                "writes_candidate_artifacts": False,
                "writes_canonical_packets": False,
                "counts_as_acceptance_gate": False,
            },
            "validation_results": [
                {
                    "sequence": 1,
                    "gate_id": EXPECTED.gate_id,
                    "candidate_manifest": EXPECTED.assembly_manifest_output,
                    "candidate_manifest_sha256": candidate_sha,
                    "assembler_script": EXPECTED.assembler_script,
                    "canonical_packet_not_written": EXPECTED.canonical_packet,
                    "argv": [
                        "python3",
                        EXPECTED.assembler_script,
                        "--assembly-manifest",
                        EXPECTED.assembly_manifest_output,
                        "--validate",
                    ],
                    "status": "passed",
                    "stdout_summary": {
                        "json_stdout": True,
                        "validation_report_present": True,
                        "packet_present": True,
                        "passed": True,
                        "blocker_count": 0,
                    },
                    "canonical_packet_integrity": {
                        "passed": True,
                        "changed_packet_count": 0,
                        "changed_packets": [],
                    },
                }
            ],
        }

    def write_validation_report(self, candidate_sha: str) -> str:
        write_json(self.validation_report, self.validation_report_payload(candidate_sha))
        return approval._sha256_file(self.validation_report)

    def approval_payload(
        self,
        *,
        candidate_sha: str,
        report_sha: str,
    ) -> dict[str, object]:
        return {
            "manifest_type": approval.MANIFEST_TYPE,
            "gate_id": EXPECTED.gate_id,
            "candidate_validation_report": str(self.validation_report.relative_to(ROOT)),
            "candidate_validation_report_sha256": report_sha,
            "candidate_manifest": EXPECTED.assembly_manifest_output,
            "candidate_manifest_sha256": candidate_sha,
            "canonical_packet": EXPECTED.canonical_packet,
            "approved_by": "human:reviewer_unitcase",
            "approval_timestamp_utc": "2026-06-28T12:00:00Z",
            "manual_governance_review_completed": True,
            "target_candidate_validation_passed": True,
            "canonical_packet_update_approved": True,
            "approval_scope": dict(approval.APPROVAL_SCOPE),
            "claim_boundary": dict(approval.CLAIM_BOUNDARY),
        }

    def write_approval_manifest(
        self,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        candidate_sha = self.write_candidate_manifest()
        report_sha = self.write_validation_report(candidate_sha)
        approval_payload = payload or self.approval_payload(
            candidate_sha=candidate_sha,
            report_sha=report_sha,
        )
        write_json(self.approval_manifest, approval_payload)
        return approval_payload

    def test_template_check_passes_for_tracked_template(self) -> None:
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = approval.main(["--check-template"])

        self.assertEqual(status, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["up_to_date"])

    def test_valid_approval_binds_validation_report_candidate_manifest_and_target(
        self,
    ) -> None:
        payload = self.write_approval_manifest()

        validation = approval.validate_approval_manifest(
            payload,
            manifest_path=self.approval_manifest,
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["blockers"], [])
        self.assertFalse(validation["authority"]["writes_canonical_packets"])
        self.assertFalse(validation["authority"]["promotes_evidence"])
        self.assertFalse(validation["authority"]["counts_as_acceptance_gate"])
        target = validation["promotion_target"]
        self.assertEqual(target["gate_id"], EXPECTED.gate_id)
        self.assertEqual(target["candidate_manifest"], EXPECTED.assembly_manifest_output)
        self.assertEqual(target["canonical_packet"], EXPECTED.canonical_packet)
        self.assertEqual(target["assembler_script"], EXPECTED.assembler_script)

    def test_stale_candidate_manifest_hash_blocks_approval(self) -> None:
        payload = self.write_approval_manifest()
        write_json(
            self.candidate_manifest,
            {
                "artifact_id": "operatorapproval_unitcase_candidate_manifest_changed",
            },
        )

        validation = approval.validate_approval_manifest(
            payload,
            manifest_path=self.approval_manifest,
        )

        self.assertFalse(validation["valid"])
        self.assertIn(
            "candidate_manifest_sha256 does not match current file",
            validation["blockers"],
        )

    def test_candidate_validation_report_must_bind_target_pass_and_hash(self) -> None:
        candidate_sha = self.write_candidate_manifest()
        report = self.validation_report_payload(candidate_sha)
        report["validation_results"][0]["status"] = "failed"
        report["validation_results"][0]["candidate_manifest_sha256"] = "0" * 64
        write_json(self.validation_report, report)
        report_sha = approval._sha256_file(self.validation_report)
        payload = self.approval_payload(candidate_sha=candidate_sha, report_sha=report_sha)

        validation = approval.validate_approval_manifest(
            payload,
            manifest_path=self.approval_manifest,
        )

        self.assertFalse(validation["valid"])
        self.assertIn("target candidate validation row did not pass", validation["blockers"])
        self.assertIn(
            "candidate validation report candidate manifest hash mismatch",
            validation["blockers"],
        )

    def test_candidate_validation_report_requires_exact_validate_only_argv(self) -> None:
        candidate_sha = self.write_candidate_manifest()
        for bad_argv in (
            None,
            "python3 human_annotation_packet_assembler.py --promote",
            [
                "python3",
                EXPECTED.assembler_script,
                "--assembly-manifest",
                EXPECTED.assembly_manifest_output,
                "--promote",
            ],
        ):
            with self.subTest(bad_argv=bad_argv):
                report = self.validation_report_payload(candidate_sha)
                if bad_argv is None:
                    report["validation_results"][0].pop("argv")
                else:
                    report["validation_results"][0]["argv"] = bad_argv
                write_json(self.validation_report, report)
                payload = self.approval_payload(
                    candidate_sha=candidate_sha,
                    report_sha=approval._sha256_file(self.validation_report),
                )

                validation = approval.validate_approval_manifest(
                    payload,
                    manifest_path=self.approval_manifest,
                )

                self.assertFalse(validation["valid"])
                self.assertIn(
                    "candidate validation report target row argv is not validate-only",
                    validation["blockers"],
                )

    def test_candidate_validation_report_must_use_generated_report_naming(self) -> None:
        candidate_sha = self.write_candidate_manifest()
        bad_report = ROOT / "work_packets" / "operatorapproval_unitcase_validation_report.json"
        if bad_report.exists() or bad_report.is_symlink():
            bad_report.unlink()
        self.created_paths.append(bad_report)
        write_json(bad_report, self.validation_report_payload(candidate_sha))
        payload = self.approval_payload(
            candidate_sha=candidate_sha,
            report_sha=approval._sha256_file(bad_report),
        )
        payload["candidate_validation_report"] = str(bad_report.relative_to(ROOT))

        validation = approval.validate_approval_manifest(
            payload,
            manifest_path=self.approval_manifest,
        )

        self.assertFalse(validation["valid"])
        self.assertIn(
            "candidate_validation_report must use *_candidate_validation_report.json naming",
            validation["blockers"],
        )

    def test_existing_canonical_packet_blocks_execution_before_subprocess(self) -> None:
        payload = self.write_approval_manifest()
        canonical_path = ROOT / EXPECTED.canonical_packet
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_text('{"artifact_id":"existing"}\n', encoding="utf-8")

        with mock.patch.object(approval.subprocess, "run") as run_mock:
            execution = approval.execute_approved_promotion(
                payload,
                manifest_path=self.approval_manifest,
            )

        self.assertFalse(execution["overall_success"])
        self.assertFalse(execution["executed"])
        run_mock.assert_not_called()
        self.assertIn(
            "canonical packet target must be missing before approved promotion",
            execution["approval_validation"]["blockers"],
        )

    def test_execute_approved_promotion_allows_only_target_packet_creation(self) -> None:
        payload = self.write_approval_manifest()
        canonical_path = ROOT / EXPECTED.canonical_packet
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"validation_report": {"passed": true, "blockers": []}}\n',
            stderr="",
        )

        def write_target_packet(
            *_args: object,
            **_kwargs: object,
        ) -> subprocess.CompletedProcess:
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(
                '{"artifact_id":"operatorapproval_unitcase_promoted"}\n',
                encoding="utf-8",
            )
            return completed

        with mock.patch.object(
            approval.subprocess,
            "run",
            side_effect=write_target_packet,
        ) as run_mock:
            execution = approval.execute_approved_promotion(
                payload,
                manifest_path=self.approval_manifest,
            )

        self.assertTrue(execution["overall_success"])
        self.assertTrue(execution["executed"])
        self.assertTrue(execution["authority"]["writes_canonical_packets"])
        self.assertTrue(execution["authority"]["promotes_evidence"])
        self.assertFalse(execution["authority"]["counts_as_acceptance_gate"])
        self.assertEqual(run_mock.call_count, 1)
        argv = run_mock.call_args.args[0]
        self.assertEqual(argv[1], EXPECTED.assembler_script)
        self.assertEqual(argv[3], EXPECTED.assembly_manifest_output)
        self.assertEqual(argv[4], "--assembly-manifest-sha256")
        self.assertEqual(argv[5], payload["candidate_manifest_sha256"])
        self.assertIn("--promote", argv)
        result = execution["execution_result"]
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(
            result["candidate_manifest_sha256"],
            payload["candidate_manifest_sha256"],
        )
        integrity = result["canonical_packet_promotion_integrity"]
        self.assertTrue(integrity["passed"])
        self.assertEqual(integrity["changed_packet_count"], 1)
        self.assertEqual(integrity["changed_packets"][0]["packet"], EXPECTED.canonical_packet)

    def test_execute_approved_promotion_rejects_and_rolls_back_candidate_manifest_swap(
        self,
    ) -> None:
        payload = self.write_approval_manifest()
        canonical_path = ROOT / EXPECTED.canonical_packet
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"validation_report": {"passed": true, "blockers": []}}\n',
            stderr="",
        )

        def swap_manifest_and_write_target(
            *_args: object,
            **_kwargs: object,
        ) -> subprocess.CompletedProcess:
            write_json(
                self.candidate_manifest,
                {"artifact_id": "operatorapproval_unitcase_swapped_manifest"},
            )
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(
                '{"artifact_id":"operatorapproval_unitcase_unapproved_promoted"}\n',
                encoding="utf-8",
            )
            return completed

        with mock.patch.object(
            approval.subprocess,
            "run",
            side_effect=swap_manifest_and_write_target,
        ):
            execution = approval.execute_approved_promotion(
                payload,
                manifest_path=self.approval_manifest,
            )

        self.assertFalse(execution["overall_success"])
        result = execution["execution_result"]
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["candidate_manifest_integrity"]["passed"])
        self.assertIn(
            "candidate manifest hash changed during promotion",
            result["candidate_manifest_integrity"]["blockers"],
        )
        self.assertTrue(result["rollback_after_candidate_manifest_drift"]["attempted"])
        self.assertTrue(result["rollback_after_candidate_manifest_drift"]["removed"])
        self.assertFalse(canonical_path.exists())
        self.assertFalse(result["canonical_packet_promotion_integrity"]["passed"])

    def test_execute_approved_promotion_rolls_back_target_packet_on_subprocess_failure(
        self,
    ) -> None:
        payload = self.write_approval_manifest()
        canonical_path = ROOT / EXPECTED.canonical_packet
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout='{"validation_report": {"passed": true, "blockers": []}}\n',
            stderr="assembler failed after writing target\n",
        )

        def write_target_packet_then_fail(
            *_args: object,
            **_kwargs: object,
        ) -> subprocess.CompletedProcess:
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(
                '{"artifact_id":"operatorapproval_unitcase_failed_promoted"}\n',
                encoding="utf-8",
            )
            return completed

        with mock.patch.object(
            approval.subprocess,
            "run",
            side_effect=write_target_packet_then_fail,
        ):
            execution = approval.execute_approved_promotion(
                payload,
                manifest_path=self.approval_manifest,
            )

        self.assertFalse(execution["overall_success"])
        result = execution["execution_result"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 1)
        self.assertTrue(result["candidate_manifest_integrity"]["passed"])
        self.assertTrue(result["rollback_after_failed_promotion"]["attempted"])
        self.assertTrue(result["rollback_after_failed_promotion"]["removed"])
        self.assertFalse(canonical_path.exists())
        self.assertFalse(result["canonical_packet_promotion_integrity"]["passed"])

    def test_execute_approved_promotion_rolls_back_hardlink_alias_target_on_failure(
        self,
    ) -> None:
        payload = self.write_approval_manifest()
        canonical_path = ROOT / EXPECTED.canonical_packet
        temp_path = canonical_path.with_name(f".{canonical_path.name}.tmp")
        self.created_paths.append(temp_path)
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout='{"validation_report": {"passed": true, "blockers": []}}\n',
            stderr="assembler failed after linking target\n",
        )

        def link_target_packet_then_fail(
            *_args: object,
            **_kwargs: object,
        ) -> subprocess.CompletedProcess:
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                '{"artifact_id":"operatorapproval_unitcase_failed_promoted"}\n',
                encoding="utf-8",
            )
            canonical_path.hardlink_to(temp_path)
            return completed

        with mock.patch.object(
            approval.subprocess,
            "run",
            side_effect=link_target_packet_then_fail,
        ):
            execution = approval.execute_approved_promotion(
                payload,
                manifest_path=self.approval_manifest,
            )

        self.assertFalse(execution["overall_success"])
        result = execution["execution_result"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 1)
        self.assertTrue(result["candidate_manifest_integrity"]["passed"])
        self.assertTrue(result["rollback_after_failed_promotion"]["attempted"])
        self.assertTrue(result["rollback_after_failed_promotion"]["removed"])
        self.assertFalse(canonical_path.exists())
        self.assertFalse(result["canonical_packet_promotion_integrity"]["passed"])

    def test_execute_approved_promotion_rolls_back_target_packet_on_subprocess_oserror(
        self,
    ) -> None:
        payload = self.write_approval_manifest()
        canonical_path = ROOT / EXPECTED.canonical_packet

        def write_target_packet_then_raise(
            *_args: object,
            **_kwargs: object,
        ) -> subprocess.CompletedProcess:
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(
                '{"artifact_id":"operatorapproval_unitcase_oserror_promoted"}\n',
                encoding="utf-8",
            )
            raise OSError("launcher failed after target write")

        with mock.patch.object(
            approval.subprocess,
            "run",
            side_effect=write_target_packet_then_raise,
        ):
            execution = approval.execute_approved_promotion(
                payload,
                manifest_path=self.approval_manifest,
            )

        self.assertFalse(execution["overall_success"])
        result = execution["execution_result"]
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["exit_code"])
        self.assertEqual(result["subprocess_error"]["type"], "OSError")
        self.assertTrue(result["candidate_manifest_integrity"]["passed"])
        self.assertTrue(result["rollback_after_failed_promotion"]["attempted"])
        self.assertTrue(result["rollback_after_failed_promotion"]["removed"])
        self.assertFalse(canonical_path.exists())
        self.assertFalse(result["canonical_packet_promotion_integrity"]["passed"])


if __name__ == "__main__":
    unittest.main()
