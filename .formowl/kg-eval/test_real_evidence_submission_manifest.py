#!/usr/bin/env python3
"""Tests for the KG real-evidence operator submission manifest preflight."""

from __future__ import annotations

import json
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import real_evidence_submission_manifest as submission_manifest


ROOT = submission_manifest.ROOT
REPO_ROOT = ROOT.parents[1]
TEMPLATE_PATH = submission_manifest.DEFAULT_TEMPLATE_OUTPUT
EXPECTED_COUNT = len(submission_manifest.EXPECTED_SUBMISSIONS)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class RealEvidenceSubmissionManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.before_real_roots = {
            expected.gate_id: sorted(
                str(path.relative_to(ROOT / expected.real_root))
                for path in (ROOT / expected.real_root).rglob("*")
            )
            if (ROOT / expected.real_root).exists()
            else []
            for expected in submission_manifest.EXPECTED_SUBMISSIONS
        }
        self.before_canonical_packets = {
            rel_path: (ROOT / rel_path).read_bytes() if (ROOT / rel_path).exists() else None
            for rel_path in submission_manifest.CANONICAL_INPUT_PACKETS
        }
        self.before_candidate_manifests = {
            expected.assembly_manifest_output: (
                (ROOT / expected.assembly_manifest_output).read_bytes()
                if (ROOT / expected.assembly_manifest_output).exists()
                else None
            )
            for expected in submission_manifest.EXPECTED_SUBMISSIONS
        }
        self.response_paths = []
        self.created_manifest_paths: list[Path] = []
        self.created_plan_paths: list[Path] = []
        self.created_validation_report_paths: list[Path] = []
        for expected in submission_manifest.EXPECTED_SUBMISSIONS:
            run_id = self.operator_run_id(expected)
            path = ROOT / expected.response_packet_for(run_id)
            self.response_paths.append(path)
            if path.exists() or path.is_symlink():
                path.unlink()
            write_json(
                path,
                {
                    "response_packet_type": "placeholder_for_path_preflight_only",
                    "operator_supplied": True,
                },
            )
        for rel_path in self.before_candidate_manifests:
            path = ROOT / rel_path
            if path.exists() or path.is_symlink():
                path.unlink()

    def tearDown(self) -> None:
        for path in self.created_validation_report_paths:
            if path.exists() or path.is_symlink():
                path.unlink()
        for path in self.created_plan_paths:
            if path.exists() or path.is_symlink():
                path.unlink()
        for path in self.created_manifest_paths:
            if path.exists() or path.is_symlink():
                path.unlink()
        for path in self.response_paths:
            if path.exists() or path.is_symlink():
                path.unlink()
            try:
                path.parent.rmdir()
            except OSError:
                pass
        for gate_id, before in self.before_real_roots.items():
            expected = submission_manifest.EXPECTED_BY_GATE[gate_id]
            current = sorted(
                str(path.relative_to(ROOT / expected.real_root))
                for path in (ROOT / expected.real_root).rglob("*")
            )
            self.assertEqual(current, before)
        for rel_path, before in self.before_canonical_packets.items():
            path = ROOT / rel_path
            if before is None:
                self.assertFalse(path.exists())
            else:
                self.assertEqual(path.read_bytes(), before)
        for rel_path, before in self.before_candidate_manifests.items():
            path = ROOT / rel_path
            if before is None:
                self.assertFalse(path.exists())
            else:
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(before)
                self.assertEqual(path.read_bytes(), before)

    def operator_run_id(self, expected: submission_manifest.ExpectedSubmission) -> str:
        return f"operatorpreflight_unitcase_{expected.gate_id}_run"

    def valid_manifest(self) -> dict[str, object]:
        return {
            "manifest_type": submission_manifest.MANIFEST_TYPE,
            "claim_boundary": {
                "accepts_evidence": False,
                "promotes_evidence": False,
                "writes_candidate_artifacts": False,
                "writes_canonical_packets": False,
                "counts_as_acceptance_gate": False,
            },
            "submissions": [
                {
                    "gate_id": expected.gate_id,
                    "response_packet_type": expected.response_packet_type,
                    "response_packet": expected.response_packet_for(self.operator_run_id(expected)),
                    "operator_run_id": self.operator_run_id(expected),
                    "output_dir": expected.output_dir_for(self.operator_run_id(expected)),
                    "assembly_manifest_output": expected.assembly_manifest_output,
                }
                for expected in submission_manifest.EXPECTED_SUBMISSIONS
            ],
        }

    def write_operator_manifest(
        self, name: str = "operatorpreflight_unitcase_manifest.json"
    ) -> Path:
        path = ROOT / "work_packets" / name
        if path.exists() or path.is_symlink():
            path.unlink()
        write_json(path, self.valid_manifest())
        self.created_manifest_paths.append(path)
        return path

    def write_candidate_manifests(self) -> list[Path]:
        paths: list[Path] = []
        for expected in submission_manifest.EXPECTED_SUBMISSIONS:
            path = ROOT / expected.assembly_manifest_output
            if path.exists() or path.is_symlink():
                path.unlink()
            write_json(path, {"candidate_manifest_for": expected.gate_id})
            self.created_manifest_paths.append(path)
            paths.append(path)
        return paths

    def remove_path_surface(self, path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            path.rmdir()

    def move_path_surface_aside(self, path: Path) -> Path | None:
        restore_path = path.with_name(f".{path.name}.unitcase_restore")
        if restore_path.exists() or restore_path.is_symlink():
            raise AssertionError(f"test restore path already exists: {restore_path}")
        if path.exists() or path.is_symlink():
            path.rename(restore_path)
            return restore_path
        return None

    def restore_path_surface(self, path: Path, restore_path: Path | None) -> None:
        if path.is_symlink() or path.exists():
            self.remove_path_surface(path)
        if restore_path is not None:
            restore_path.rename(path)

    def make_canonical_packet_path_hazard(
        self,
        kind: str,
    ) -> tuple[str, Path, Path | None]:
        canonical_rel_path = sorted(submission_manifest.CANONICAL_INPUT_PACKETS)[0]
        canonical_path = ROOT / canonical_rel_path
        restore_path = self.move_path_surface_aside(canonical_path)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "symlink":
            canonical_path.symlink_to(TEMPLATE_PATH)
        elif kind == "hardlink":
            canonical_path.hardlink_to(TEMPLATE_PATH)
        elif kind == "directory":
            canonical_path.mkdir()
        else:
            raise AssertionError(f"unsupported hazard kind {kind}")
        return canonical_rel_path, canonical_path, restore_path

    def canonical_packet_snapshot_with_state(
        self, state: str
    ) -> tuple[str, dict[str, dict[str, object]]]:
        canonical_rel_path = sorted(submission_manifest.CANONICAL_INPUT_PACKETS)[0]
        snapshot = {
            rel_path: {
                "state": "missing",
                "sha256": None,
                "hardlink_alias": False,
            }
            for rel_path in submission_manifest.CANONICAL_INPUT_PACKETS
        }
        snapshot[canonical_rel_path] = {
            "state": state,
            "sha256": None,
            "hardlink_alias": False,
        }
        return canonical_rel_path, snapshot

    def test_valid_manifest_returns_candidate_only_intake_commands(self) -> None:
        report = submission_manifest.validate_manifest(self.valid_manifest())

        self.assertTrue(report["valid"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(len(report["intake_commands"]), EXPECTED_COUNT)
        self.assertFalse(report["authority"]["writes_candidate_artifacts"])
        self.assertFalse(report["authority"]["writes_canonical_packets"])
        for expected, row, command in zip(
            submission_manifest.EXPECTED_SUBMISSIONS,
            report["validated_submissions"],
            report["intake_commands"],
            strict=True,
        ):
            self.assertEqual(row["gate_id"], expected.gate_id)
            self.assertFalse(row["writes_canonical_packet"])
            self.assertEqual(row["canonical_packet_not_written"], expected.canonical_packet)
            self.assertIn(expected.intake_script, command)
            self.assertIn(f"--work-packet {expected.work_packet_path}", command)
            self.assertIn("--assembly-manifest-output", command)
            self.assertNotIn("--promote", command)
            self.assertNotIn("--allow-test-artifacts", command)

    def test_cli_description_distinguishes_validation_plan_and_execution_modes(self) -> None:
        doc = submission_manifest.__doc__ or ""
        help_text = submission_manifest.build_arg_parser().format_help()
        normalized_help = " ".join(help_text.split())

        self.assertIn("Validation and plan modes", doc)
        self.assertIn("do not", doc)
        self.assertIn("read response packet contents", doc)
        self.assertIn("--execute-candidate-intakes", doc)
        self.assertIn("reads response packet contents", doc)
        self.assertIn("writes candidate artifacts", doc)
        self.assertIn("--preflight-responses", doc)
        self.assertIn("writes no candidate artifacts", doc)
        self.assertIn("writes no candidate manifest", doc)
        self.assertIn("--validate-candidate-manifests", doc)
        self.assertIn("reads the candidate", doc)
        self.assertIn("writes no candidate artifacts", doc)
        self.assertIn("non-evidence validation report", doc)
        self.assertIn("No mode promotes evidence or writes canonical input packets", doc)
        self.assertIn("--preflight-responses", help_text)
        self.assertIn("--execute-candidate-intakes", help_text)
        self.assertIn("--validate-candidate-manifests", help_text)
        self.assertIn("--emit-candidate-validation-report", help_text)
        self.assertIn(
            "reads response packet contents but writes no candidate or canonical artifacts",
            normalized_help,
        )
        self.assertIn(
            "writes candidate artifacts but never canonical packets",
            normalized_help,
        )
        self.assertIn(
            "reads candidate artifacts but never promotes or writes canonical packets",
            normalized_help,
        )

    def test_valid_manifest_builds_non_evidence_intake_execution_plan(self) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        plan_output = ROOT / "work_packets" / "operatorpreflight_unitcase_intake_plan.json"

        plan = submission_manifest.build_intake_plan(
            report,
            manifest_path=manifest_path,
            plan_output=plan_output,
        )

        self.assertEqual(plan["artifact_id"], "kg_real_evidence_candidate_intake_plan_v1")
        self.assertEqual(plan["manifest"], str(manifest_path.relative_to(ROOT)))
        self.assertEqual(plan["plan_output"], str(plan_output.relative_to(ROOT)))
        self.assertFalse(plan["authority"]["writes_candidate_artifacts"])
        self.assertFalse(plan["authority"]["writes_canonical_packets"])
        self.assertEqual(len(plan["execution_plan"]), EXPECTED_COUNT)
        self.assertEqual(len(plan["preflight_commands"]), EXPECTED_COUNT)
        for expected, row in zip(
            submission_manifest.EXPECTED_SUBMISSIONS,
            plan["execution_plan"],
            strict=True,
        ):
            self.assertEqual(row["gate_id"], expected.gate_id)
            self.assertEqual(row["work_packet"], expected.work_packet_path)
            self.assertEqual(row["canonical_packet_not_written"], expected.canonical_packet)
            self.assertTrue(row["preflight_effects"]["reads_response_packet_contents"])
            self.assertFalse(row["preflight_effects"]["writes_candidate_artifacts"])
            self.assertFalse(row["preflight_effects"]["writes_candidate_manifest"])
            self.assertFalse(row["preflight_effects"]["writes_canonical_packets"])
            self.assertFalse(row["preflight_effects"]["promotes_evidence"])
            self.assertFalse(row["preflight_effects"]["counts_as_acceptance_gate"])
            self.assertTrue(row["execution_effects"]["reads_response_packet_contents"])
            self.assertTrue(row["execution_effects"]["writes_candidate_artifacts"])
            self.assertFalse(row["execution_effects"]["writes_canonical_packets"])
            self.assertFalse(row["execution_effects"]["promotes_evidence"])
            self.assertFalse(row["execution_effects"]["counts_as_acceptance_gate"])
            self.assertEqual(row["preflight_argv"], [*row["argv"], "--preflight-response"])
            self.assertEqual(row["preflight_command"], f"{row['command']} --preflight-response")
            self.assertIn(row["preflight_command"], plan["preflight_commands"])
            self.assertEqual(row["argv"][0], "python3")
            self.assertEqual(row["argv"][1], expected.intake_script)
            self.assertIn("--response-packet", row["argv"])
            self.assertIn("--assembly-manifest-output", row["argv"])
            self.assertIn("--preflight-response", row["preflight_argv"])
            self.assertNotIn("--promote", row["argv"])
            self.assertNotIn("--promote", row["preflight_argv"])
            self.assertNotIn("--allow-test-artifacts", row["argv"])

    def test_preflight_operator_responses_runs_preflight_argv_without_shell(self) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"artifact_id": "response_preflight", "valid": true}\n',
            stderr="",
        )

        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            return_value=completed,
        ) as run_mock:
            preflight = submission_manifest.preflight_operator_responses(
                report,
                manifest_path=manifest_path,
            )

        self.assertTrue(preflight["overall_success"])
        self.assertEqual(preflight["executed_gate_count"], EXPECTED_COUNT)
        self.assertFalse(preflight["authority"]["accepts_evidence"])
        self.assertFalse(preflight["authority"]["writes_candidate_artifacts"])
        self.assertFalse(preflight["authority"]["writes_canonical_packets"])
        self.assertTrue(preflight["preflight_effects"]["reads_response_packet_contents"])
        self.assertFalse(preflight["preflight_effects"]["writes_candidate_artifacts"])
        self.assertFalse(preflight["preflight_effects"]["writes_candidate_manifest"])
        self.assertFalse(preflight["preflight_effects"]["counts_as_acceptance_gate"])
        self.assertTrue(preflight["response_output_integrity"]["passed"])
        self.assertEqual(run_mock.call_count, EXPECTED_COUNT)
        for expected, call, row in zip(
            submission_manifest.EXPECTED_SUBMISSIONS,
            run_mock.call_args_list,
            preflight["preflight_results"],
            strict=True,
        ):
            args, kwargs = call
            argv = args[0]
            self.assertEqual(argv[0], "python3")
            self.assertEqual(argv[1], expected.intake_script)
            self.assertIn("--preflight-response", argv)
            self.assertNotIn("--promote", argv)
            self.assertNotIn("--allow-test-artifacts", argv)
            self.assertEqual(kwargs["cwd"], ROOT)
            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["text"])
            self.assertFalse(kwargs["check"])
            self.assertNotIn("shell", kwargs)
            self.assertEqual(row["status"], "succeeded")
            self.assertEqual(row["stdout_summary"]["artifact_id"], "response_preflight")
            self.assertTrue(row["response_output_integrity"]["passed"])
            self.assertEqual(row["canonical_packet_not_written"], expected.canonical_packet)

    def test_preflight_operator_responses_stops_after_first_failure(self) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        success = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}\n", stderr="")
        failure = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="not-json\n",
            stderr="operator response preflight failed\n",
        )

        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            side_effect=[success, failure, success, success],
        ) as run_mock:
            preflight = submission_manifest.preflight_operator_responses(
                report,
                manifest_path=manifest_path,
            )

        self.assertFalse(preflight["overall_success"])
        self.assertTrue(preflight["stopped_after_failure"])
        self.assertEqual(preflight["executed_gate_count"], 2)
        self.assertEqual(run_mock.call_count, 2)
        self.assertEqual(preflight["preflight_results"][0]["status"], "succeeded")
        self.assertEqual(preflight["preflight_results"][1]["status"], "failed")
        self.assertFalse(preflight["preflight_results"][1]["stdout_summary"]["json_stdout"])
        self.assertEqual(preflight["preflight_results"][1]["stderr_line_count"], 1)

    def test_preflight_operator_responses_refuses_preexisting_canonical_packet_hazard(
        self,
    ) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        rel_path, canonical_path, restore_path = self.make_canonical_packet_path_hazard("symlink")

        try:
            with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
                preflight = submission_manifest.preflight_operator_responses(
                    report,
                    manifest_path=manifest_path,
                )
        finally:
            self.restore_path_surface(canonical_path, restore_path)

        self.assertFalse(preflight["overall_success"])
        self.assertEqual(preflight["executed_gate_count"], 0)
        self.assertFalse(preflight["preflight_effects"]["reads_response_packet_contents"])
        self.assertFalse(preflight["authority"]["writes_candidate_artifacts"])
        self.assertEqual(preflight["canonical_packet_baseline"]["hazards"][0]["packet"], rel_path)
        self.assertTrue(
            any(
                "pre-existing canonical packet path hazard" in blocker
                for blocker in preflight["blockers"]
            )
        )
        self.assertEqual(preflight["preflight_results"], [])
        run_mock.assert_not_called()

    def test_preflight_operator_responses_detects_candidate_output_surface_change(
        self,
    ) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        expected = submission_manifest.EXPECTED_SUBMISSIONS[0]
        run_id = self.operator_run_id(expected)
        leaked_candidate = ROOT / expected.output_dir_for(run_id) / "unexpected_candidate.json"
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}\n", stderr="")

        def write_unexpected_candidate(
            *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess:
            leaked_candidate.write_text('{"unexpected":"candidate artifact"}\n', encoding="utf-8")
            return completed

        try:
            with mock.patch.object(
                submission_manifest.subprocess,
                "run",
                side_effect=write_unexpected_candidate,
            ) as run_mock:
                preflight = submission_manifest.preflight_operator_responses(
                    report,
                    manifest_path=manifest_path,
                )
        finally:
            if leaked_candidate.exists() or leaked_candidate.is_symlink():
                leaked_candidate.unlink()

        self.assertFalse(preflight["overall_success"])
        self.assertTrue(preflight["stopped_after_failure"])
        self.assertEqual(preflight["executed_gate_count"], 1)
        self.assertEqual(run_mock.call_count, 1)
        self.assertFalse(preflight["response_output_integrity"]["passed"])
        changed_paths = {
            row["path"] for row in preflight["response_output_integrity"]["changed_surfaces"]
        }
        self.assertIn(str(leaked_candidate.relative_to(ROOT)), changed_paths)
        self.assertEqual(preflight["preflight_results"][0]["status"], "failed")

    def test_preflight_operator_responses_fails_if_subprocess_changes_canonical_packet(
        self,
    ) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        canonical_rel_path = sorted(submission_manifest.CANONICAL_INPUT_PACKETS)[0]
        canonical_path = ROOT / canonical_rel_path
        before = canonical_path.read_bytes() if canonical_path.exists() else None
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"artifact_id": "response_preflight"}\n',
            stderr="",
        )

        def write_canonical_packet(
            *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess:
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text('{"unexpected":"canonical write"}\n', encoding="utf-8")
            return completed

        try:
            with mock.patch.object(
                submission_manifest.subprocess,
                "run",
                side_effect=write_canonical_packet,
            ) as run_mock:
                preflight = submission_manifest.preflight_operator_responses(
                    report,
                    manifest_path=manifest_path,
                )
        finally:
            if before is None:
                if canonical_path.exists() or canonical_path.is_symlink():
                    canonical_path.unlink()
            else:
                canonical_path.write_bytes(before)

        self.assertFalse(preflight["overall_success"])
        self.assertTrue(preflight["stopped_after_failure"])
        self.assertEqual(preflight["executed_gate_count"], 1)
        self.assertEqual(run_mock.call_count, 1)
        self.assertFalse(preflight["canonical_packet_integrity"]["passed"])
        self.assertEqual(
            preflight["canonical_packet_integrity"]["changed_packets"][0]["packet"],
            canonical_rel_path,
        )
        self.assertEqual(preflight["preflight_results"][0]["status"], "failed")
        self.assertFalse(preflight["preflight_results"][0]["canonical_packet_integrity"]["passed"])

    def test_execute_candidate_intakes_uses_validated_argv_without_shell(self) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())

        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"artifact_id": "candidate_intake_result", "valid": true}\n',
            stderr="",
        )
        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            return_value=completed,
        ) as run_mock:
            execution = submission_manifest.execute_candidate_intakes(
                report,
                manifest_path=manifest_path,
            )

        self.assertTrue(execution["overall_success"])
        self.assertEqual(execution["executed_gate_count"], EXPECTED_COUNT)
        self.assertFalse(execution["authority"]["accepts_evidence"])
        self.assertTrue(execution["authority"]["writes_candidate_artifacts"])
        self.assertFalse(execution["authority"]["writes_canonical_packets"])
        self.assertFalse(execution["authority"]["counts_as_acceptance_gate"])
        self.assertIn("stops on the first failed intake", execution["partial_execution_policy"])
        self.assertIn("remain for operator review", execution["partial_execution_policy"])
        self.assertEqual(run_mock.call_count, EXPECTED_COUNT)
        for expected, call in zip(
            submission_manifest.EXPECTED_SUBMISSIONS,
            run_mock.call_args_list,
            strict=True,
        ):
            args, kwargs = call
            argv = args[0]
            self.assertEqual(argv[0], "python3")
            self.assertEqual(argv[1], expected.intake_script)
            self.assertNotIn("--promote", argv)
            self.assertNotIn("--allow-test-artifacts", argv)
            self.assertEqual(kwargs["cwd"], ROOT)
            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["text"])
            self.assertFalse(kwargs["check"])
            self.assertNotIn("shell", kwargs)
        for expected, row in zip(
            submission_manifest.EXPECTED_SUBMISSIONS,
            execution["execution_results"],
            strict=True,
        ):
            self.assertEqual(row["gate_id"], expected.gate_id)
            self.assertEqual(row["status"], "succeeded")
            self.assertEqual(row["stdout_summary"]["artifact_id"], "candidate_intake_result")
            self.assertEqual(row["canonical_packet_not_written"], expected.canonical_packet)

    def test_execute_candidate_intakes_stops_after_first_failure(self) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        success = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}\n", stderr="")
        failure = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="not-json\n",
            stderr="operator supplied packet failed validation\n",
        )

        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            side_effect=[success, failure, success, success],
        ) as run_mock:
            execution = submission_manifest.execute_candidate_intakes(
                report,
                manifest_path=manifest_path,
            )

        self.assertFalse(execution["overall_success"])
        self.assertTrue(execution["stopped_after_failure"])
        self.assertEqual(execution["executed_gate_count"], 2)
        self.assertIn("not promoted", execution["partial_execution_policy"])
        self.assertEqual(run_mock.call_count, 2)
        self.assertEqual(execution["execution_results"][0]["status"], "succeeded")
        self.assertEqual(execution["execution_results"][1]["status"], "failed")
        self.assertFalse(execution["execution_results"][1]["stdout_summary"]["json_stdout"])
        self.assertEqual(execution["execution_results"][1]["stderr_line_count"], 1)

    def test_execute_candidate_intakes_fails_if_subprocess_changes_canonical_packet(
        self,
    ) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        canonical_rel_path = sorted(submission_manifest.CANONICAL_INPUT_PACKETS)[0]
        canonical_path = ROOT / canonical_rel_path
        before = canonical_path.read_bytes() if canonical_path.exists() else None
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"artifact_id": "candidate_intake_result"}\n',
            stderr="",
        )

        def write_canonical_packet(
            *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess:
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text('{"unexpected":"canonical write"}\n', encoding="utf-8")
            return completed

        try:
            with mock.patch.object(
                submission_manifest.subprocess,
                "run",
                side_effect=write_canonical_packet,
            ) as run_mock:
                execution = submission_manifest.execute_candidate_intakes(
                    report,
                    manifest_path=manifest_path,
                )
        finally:
            if before is None:
                if canonical_path.exists() or canonical_path.is_symlink():
                    canonical_path.unlink()
            else:
                canonical_path.write_bytes(before)

        self.assertFalse(execution["overall_success"])
        self.assertTrue(execution["stopped_after_failure"])
        self.assertEqual(execution["executed_gate_count"], 1)
        self.assertEqual(run_mock.call_count, 1)
        self.assertIn("canonical packet integrity", execution["partial_execution_policy"])
        self.assertFalse(execution["canonical_packet_integrity"]["passed"])
        self.assertEqual(
            execution["canonical_packet_integrity"]["changed_packets"][0]["packet"],
            canonical_rel_path,
        )
        self.assertEqual(execution["execution_results"][0]["status"], "failed")
        self.assertFalse(execution["execution_results"][0]["canonical_packet_integrity"]["passed"])

    def test_execute_candidate_intakes_refuses_preexisting_canonical_packet_path_hazards(
        self,
    ) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())

        for hazard_kind in ("symlink", "hardlink", "directory"):
            with self.subTest(hazard_kind=hazard_kind):
                rel_path, canonical_path, restore_path = self.make_canonical_packet_path_hazard(
                    hazard_kind
                )
                try:
                    with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
                        execution = submission_manifest.execute_candidate_intakes(
                            report,
                            manifest_path=manifest_path,
                        )
                finally:
                    self.restore_path_surface(canonical_path, restore_path)

                self.assertFalse(execution["overall_success"])
                self.assertTrue(execution["stopped_after_failure"])
                self.assertEqual(execution["executed_gate_count"], 0)
                self.assertFalse(execution["authority"]["writes_candidate_artifacts"])
                self.assertFalse(execution["execution_effects"]["reads_response_packet_contents"])
                self.assertFalse(execution["canonical_packet_baseline"]["passed"])
                self.assertEqual(
                    execution["canonical_packet_baseline"]["hazards"][0]["packet"],
                    rel_path,
                )
                self.assertTrue(
                    any(
                        "pre-existing canonical packet path hazard" in blocker
                        for blocker in execution["blockers"]
                    )
                )
                self.assertIn(
                    "pre-existing canonical packet path hazard",
                    execution["partial_execution_policy"],
                )
                self.assertEqual(execution["execution_results"], [])
                run_mock.assert_not_called()

    def test_canonical_packet_surface_rejects_symlinked_parent_components(self) -> None:
        parent = ROOT / "work_packets" / "operatorpreflight_unitcase_parent_symlink"
        target_dir = ROOT / "work_packets" / "operatorpreflight_unitcase_parent_target"
        packet_rel_path = "work_packets/operatorpreflight_unitcase_parent_symlink/packet.json"
        for path in (parent, target_dir):
            if path.exists() or path.is_symlink():
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                else:
                    path.unlink()
        target_dir.mkdir()
        parent.symlink_to(target_dir, target_is_directory=True)
        self.created_manifest_paths.extend([parent, target_dir])

        try:
            surface = submission_manifest._canonical_packet_surface(packet_rel_path)
            snapshot = {packet_rel_path: surface}
            baseline = submission_manifest._canonical_packet_baseline_hazards(snapshot)
        finally:
            if parent.exists() or parent.is_symlink():
                parent.unlink()
            if target_dir.exists():
                target_dir.rmdir()
            self.created_manifest_paths = [
                path for path in self.created_manifest_paths if path not in {parent, target_dir}
            ]

        self.assertEqual(surface["state"], "parent_symlink")
        self.assertFalse(baseline["passed"])
        self.assertEqual(baseline["hazards"][0]["packet"], packet_rel_path)

    def test_execute_candidate_intakes_refuses_unavailable_canonical_packet_surfaces(
        self,
    ) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())

        for state in ("metadata_unavailable", "read_unavailable"):
            with self.subTest(state=state):
                rel_path, snapshot = self.canonical_packet_snapshot_with_state(state)
                with (
                    mock.patch.object(
                        submission_manifest,
                        "_canonical_packet_snapshot",
                        return_value=snapshot,
                    ),
                    mock.patch.object(submission_manifest.subprocess, "run") as run_mock,
                ):
                    execution = submission_manifest.execute_candidate_intakes(
                        report,
                        manifest_path=manifest_path,
                    )

                self.assertFalse(execution["overall_success"])
                self.assertEqual(execution["executed_gate_count"], 0)
                self.assertFalse(execution["execution_effects"]["reads_response_packet_contents"])
                self.assertFalse(execution["authority"]["writes_candidate_artifacts"])
                self.assertEqual(
                    execution["canonical_packet_baseline"]["hazards"][0]["packet"],
                    rel_path,
                )
                self.assertIn(state, execution["blockers"][0])
                self.assertEqual(execution["execution_results"], [])
                run_mock.assert_not_called()

    def test_valid_manifest_builds_candidate_manifest_validation_plan(self) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())

        plan = submission_manifest.build_candidate_validation_plan(
            report,
            manifest_path=manifest_path,
        )

        self.assertEqual(
            plan["artifact_id"],
            "kg_real_evidence_candidate_manifest_validation_plan_v1",
        )
        self.assertFalse(plan["authority"]["writes_candidate_artifacts"])
        self.assertFalse(plan["authority"]["writes_canonical_packets"])
        self.assertEqual(len(plan["validation_plan"]), EXPECTED_COUNT)
        for expected, row in zip(
            submission_manifest.EXPECTED_SUBMISSIONS,
            plan["validation_plan"],
            strict=True,
        ):
            self.assertEqual(row["gate_id"], expected.gate_id)
            self.assertEqual(row["candidate_manifest"], expected.assembly_manifest_output)
            self.assertEqual(row["assembler_script"], expected.assembler_script)
            self.assertEqual(row["argv"][0], "python3")
            self.assertEqual(row["argv"][1], expected.assembler_script)
            self.assertEqual(row["argv"][2], "--assembly-manifest")
            self.assertEqual(row["argv"][3], expected.assembly_manifest_output)
            self.assertEqual(row["argv"][4], "--validate")
            self.assertNotIn("--promote", row["argv"])
            self.assertFalse(row["validation_effects"]["writes_candidate_artifacts"])
            self.assertFalse(row["validation_effects"]["writes_canonical_packets"])
            self.assertFalse(row["validation_effects"]["promotes_evidence"])
            self.assertFalse(row["validation_effects"]["counts_as_acceptance_gate"])

    def test_validate_candidate_manifests_requires_existing_manifests_before_commands(
        self,
    ) -> None:
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())

        with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
            validation = submission_manifest.validate_candidate_manifests(
                report,
                manifest_path=manifest_path,
            )

        self.assertFalse(validation["overall_success"])
        self.assertFalse(validation["candidate_manifest_preflight_passed"])
        self.assertEqual(validation["executed_gate_count"], 0)
        self.assertFalse(validation["validation_effects"]["reads_candidate_manifest_contents"])
        self.assertFalse(validation["validation_effects"]["reads_candidate_artifacts"])
        self.assertTrue(
            any(
                "candidate_manifest file is missing" in blocker
                for blocker in validation["blockers"]
            )
        )
        run_mock.assert_not_called()

    def test_validate_candidate_manifests_runs_validate_only_assemblers_without_raw_packet_echo(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                '{"packet": {"sensitive": "assembled packet should not be echoed"}, '
                '"validation_report": {"artifact_id": "validator_report", '
                '"passed": true, "blockers": []}}\n'
            ),
            stderr="",
        )

        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            return_value=completed,
        ) as run_mock:
            validation = submission_manifest.validate_candidate_manifests(
                report,
                manifest_path=manifest_path,
            )

        self.assertTrue(validation["overall_success"])
        self.assertTrue(validation["candidate_manifest_preflight_passed"])
        self.assertEqual(validation["executed_gate_count"], EXPECTED_COUNT)
        self.assertFalse(validation["authority"]["writes_candidate_artifacts"])
        self.assertFalse(validation["authority"]["writes_canonical_packets"])
        self.assertTrue(validation["validation_effects"]["reads_candidate_manifest_contents"])
        self.assertTrue(validation["validation_effects"]["reads_candidate_artifacts"])
        self.assertFalse(validation["validation_effects"]["promotes_evidence"])
        self.assertFalse(validation["validation_effects"]["counts_as_acceptance_gate"])
        self.assertEqual(run_mock.call_count, EXPECTED_COUNT)
        self.assertNotIn("assembled packet should not be echoed", json.dumps(validation))
        for expected, call, row in zip(
            submission_manifest.EXPECTED_SUBMISSIONS,
            run_mock.call_args_list,
            validation["validation_results"],
            strict=True,
        ):
            args, kwargs = call
            argv = args[0]
            self.assertEqual(
                argv,
                [
                    "python3",
                    expected.assembler_script,
                    "--assembly-manifest",
                    expected.assembly_manifest_output,
                    "--validate",
                ],
            )
            self.assertNotIn("--promote", argv)
            self.assertEqual(kwargs["cwd"], ROOT)
            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["text"])
            self.assertFalse(kwargs["check"])
            self.assertNotIn("shell", kwargs)
            self.assertEqual(row["status"], "passed")
            self.assertEqual(
                row["candidate_manifest_sha256"],
                submission_manifest._sha256_file(ROOT / expected.assembly_manifest_output),
            )
            self.assertTrue(row["stdout_summary"]["packet_present"])
            self.assertTrue(row["stdout_summary"]["passed"])
            self.assertEqual(row["stdout_summary"]["blocker_count"], 0)

    def test_validate_candidate_manifests_treats_failed_validation_report_as_failure(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"validation_report": {"passed": false, "blockers": ["blocked"]}}\n',
            stderr="",
        )

        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            return_value=completed,
        ):
            validation = submission_manifest.validate_candidate_manifests(
                report,
                manifest_path=manifest_path,
            )

        self.assertFalse(validation["overall_success"])
        self.assertEqual(validation["executed_gate_count"], EXPECTED_COUNT)
        self.assertTrue(all(row["status"] == "failed" for row in validation["validation_results"]))
        self.assertTrue(
            all(
                row["stdout_summary"]["blocker_count"] == 1
                for row in validation["validation_results"]
            )
        )

    def test_validate_candidate_manifests_fails_if_assembler_changes_canonical_packet(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        canonical_rel_path = sorted(submission_manifest.CANONICAL_INPUT_PACKETS)[0]
        canonical_path = ROOT / canonical_rel_path
        before = canonical_path.read_bytes() if canonical_path.exists() else None
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"validation_report": {"passed": true, "blockers": []}}\n',
            stderr="",
        )

        def write_canonical_packet(
            *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess:
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text('{"unexpected":"canonical write"}\n', encoding="utf-8")
            return completed

        try:
            with mock.patch.object(
                submission_manifest.subprocess,
                "run",
                side_effect=write_canonical_packet,
            ) as run_mock:
                validation = submission_manifest.validate_candidate_manifests(
                    report,
                    manifest_path=manifest_path,
                )
        finally:
            if before is None:
                if canonical_path.exists() or canonical_path.is_symlink():
                    canonical_path.unlink()
            else:
                canonical_path.write_bytes(before)

        self.assertFalse(validation["overall_success"])
        self.assertEqual(validation["executed_gate_count"], 1)
        self.assertEqual(run_mock.call_count, 1)
        self.assertFalse(validation["canonical_packet_integrity"]["passed"])
        self.assertEqual(
            validation["canonical_packet_integrity"]["changed_packets"][0]["packet"],
            canonical_rel_path,
        )
        self.assertEqual(validation["validation_results"][0]["status"], "failed")
        self.assertFalse(
            validation["validation_results"][0]["canonical_packet_integrity"]["passed"]
        )

    def test_validate_candidate_manifests_refuses_preexisting_canonical_packet_path_hazard(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        rel_path, canonical_path, restore_path = self.make_canonical_packet_path_hazard("hardlink")

        try:
            with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
                validation = submission_manifest.validate_candidate_manifests(
                    report,
                    manifest_path=manifest_path,
                )
        finally:
            self.restore_path_surface(canonical_path, restore_path)

        self.assertFalse(validation["overall_success"])
        self.assertFalse(validation["candidate_manifest_preflight_passed"])
        self.assertEqual(validation["executed_gate_count"], 0)
        self.assertFalse(validation["validation_effects"]["reads_candidate_manifest_contents"])
        self.assertFalse(validation["validation_effects"]["reads_candidate_artifacts"])
        self.assertFalse(validation["canonical_packet_baseline"]["passed"])
        self.assertEqual(
            validation["canonical_packet_baseline"]["hazards"][0]["packet"],
            rel_path,
        )
        self.assertTrue(
            any(
                "pre-existing canonical packet path hazard" in blocker
                for blocker in validation["blockers"]
            )
        )
        self.assertEqual(validation["validation_results"], [])
        run_mock.assert_not_called()

    def test_validate_candidate_manifests_refuses_unavailable_canonical_packet_surfaces(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())

        for state in ("metadata_unavailable", "read_unavailable"):
            with self.subTest(state=state):
                rel_path, snapshot = self.canonical_packet_snapshot_with_state(state)
                with (
                    mock.patch.object(
                        submission_manifest,
                        "_canonical_packet_snapshot",
                        return_value=snapshot,
                    ),
                    mock.patch.object(submission_manifest.subprocess, "run") as run_mock,
                ):
                    validation = submission_manifest.validate_candidate_manifests(
                        report,
                        manifest_path=manifest_path,
                    )

                self.assertFalse(validation["overall_success"])
                self.assertFalse(validation["candidate_manifest_preflight_passed"])
                self.assertEqual(validation["executed_gate_count"], 0)
                self.assertFalse(
                    validation["validation_effects"]["reads_candidate_manifest_contents"]
                )
                self.assertFalse(validation["validation_effects"]["reads_candidate_artifacts"])
                self.assertEqual(
                    validation["canonical_packet_baseline"]["hazards"][0]["packet"],
                    rel_path,
                )
                self.assertIn(state, validation["blockers"][0])
                self.assertEqual(validation["validation_results"], [])
                run_mock.assert_not_called()

    def test_validate_candidate_manifests_rejects_symlinked_candidate_manifest_before_commands(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        symlink_path = ROOT / submission_manifest.EXPECTED_SUBMISSIONS[0].assembly_manifest_output
        symlink_path.unlink()
        symlink_path.symlink_to(TEMPLATE_PATH)

        with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
            validation = submission_manifest.validate_candidate_manifests(
                report,
                manifest_path=manifest_path,
            )

        self.assertFalse(validation["overall_success"])
        self.assertEqual(validation["executed_gate_count"], 0)
        self.assertTrue(any("symlink components" in blocker for blocker in validation["blockers"]))
        run_mock.assert_not_called()

    def test_validate_candidate_manifests_rejects_hardlink_candidate_manifest_before_commands(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        report = submission_manifest.validate_manifest(self.valid_manifest())
        hardlink_path = ROOT / submission_manifest.EXPECTED_SUBMISSIONS[0].assembly_manifest_output
        hardlink_path.unlink()
        hardlink_path.hardlink_to(TEMPLATE_PATH)

        with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
            validation = submission_manifest.validate_candidate_manifests(
                report,
                manifest_path=manifest_path,
            )

        self.assertFalse(validation["overall_success"])
        self.assertEqual(validation["executed_gate_count"], 0)
        self.assertTrue(any("hardlink aliases" in blocker for blocker in validation["blockers"]))
        run_mock.assert_not_called()

    def test_template_is_tracked_but_rejected_as_real_submission_manifest(self) -> None:
        template = submission_manifest.build_template()
        report = submission_manifest.validate_manifest(
            template,
            require_existing_response_packets=False,
        )

        self.assertFalse(report["valid"])
        self.assertTrue(
            any("unsupported top-level fields" in blocker for blocker in report["blockers"])
        )
        self.assertTrue(
            any("response_packet placeholder" in blocker for blocker in report["blockers"])
        )
        self.assertEqual(
            TEMPLATE_PATH.read_text(encoding="utf-8"),
            json.dumps(template, indent=2, sort_keys=True) + "\n",
        )

    def test_template_output_is_restricted_to_tracked_template(self) -> None:
        self.assertEqual(
            submission_manifest.safe_template_output(str(TEMPLATE_PATH.relative_to(ROOT))),
            TEMPLATE_PATH,
        )

        with self.assertRaisesRegex(
            submission_manifest.ManifestError,
            "tracked submission manifest template path",
        ):
            submission_manifest.safe_template_output("work_packets/operator_manifest.json")

    def test_cli_manifest_input_is_restricted_to_safe_operator_work_packet(self) -> None:
        manifest_path = self.write_operator_manifest()

        self.assertEqual(
            submission_manifest.safe_manifest_input(str(manifest_path.relative_to(ROOT))),
            manifest_path,
        )

        rejected_paths = [
            "/tmp/operator_manifest.json",
            "./work_packets/operator_manifest.json",
            "results/operator_manifest.json",
            "inputs/operator_manifest.json",
            "work_packets/../work_packets/operator_manifest.json",
            "work_packets/./operator_manifest.json",
            "work_packets/operator_submission_preview.json",
            "work_packets/multimodal_semantic_validation_candidate_manifest.json",
            "work_packets/OPERATOR_INTAKE_PLAN.json",
            "work_packets/remaining_real_evidence_submission_manifest.template.json",
            "work_packets/templates/operator_manifest.json",
            "work_packets/operator_manifest.txt",
        ]
        for rejected in rejected_paths:
            with self.subTest(rejected=rejected):
                with self.assertRaises(submission_manifest.ManifestError):
                    submission_manifest.safe_manifest_input(rejected)

    def test_intake_plan_output_is_restricted_to_ignored_operator_work_packet(self) -> None:
        accepted = ROOT / "work_packets" / "operatorpreflight_unitcase_intake_plan.json"
        if accepted.exists() or accepted.is_symlink():
            accepted.unlink()
        self.created_plan_paths.append(accepted)

        self.assertEqual(
            submission_manifest.safe_intake_plan_output(str(accepted.relative_to(ROOT))),
            accepted,
        )

        rejected_paths = [
            "/tmp/intake_plan.json",
            "./work_packets/intake_plan.json",
            "results/intake_plan.json",
            "inputs/intake_plan.json",
            "work_packets/enterprise_multimodal_collection_packet_preview.json",
            "work_packets/multimodal_semantic_validation_candidate_manifest.json",
            "work_packets/intake_plan.template.json",
            "work_packets/intake_plan_preview.json",
            "work_packets/nested/operatorpreflight_unitcase_intake_plan.json",
            "work_packets/intake_plan.txt",
        ]
        for rejected in rejected_paths:
            with self.subTest(rejected=rejected):
                with self.assertRaises(submission_manifest.ManifestError):
                    submission_manifest.safe_intake_plan_output(rejected)

        accepted.write_text("already present\n", encoding="utf-8")
        with self.assertRaisesRegex(submission_manifest.ManifestError, "already exists"):
            submission_manifest.safe_intake_plan_output(str(accepted.relative_to(ROOT)))

    def test_candidate_validation_report_output_is_restricted_to_ignored_work_packet(
        self,
    ) -> None:
        accepted = (
            ROOT / "work_packets" / "operatorpreflight_unitcase_candidate_validation_report.json"
        )
        if accepted.exists() or accepted.is_symlink():
            accepted.unlink()
        self.created_validation_report_paths.append(accepted)

        self.assertEqual(
            submission_manifest.safe_candidate_validation_report_output(
                str(accepted.relative_to(ROOT))
            ),
            accepted,
        )

        rejected_paths = [
            "/tmp/candidate_validation_report.json",
            "./work_packets/candidate_validation_report.json",
            "results/candidate_validation_report.json",
            "inputs/candidate_validation_report.json",
            "work_packets/enterprise_multimodal_collection_packet_preview.json",
            "work_packets/multimodal_semantic_validation_candidate_manifest.json",
            "work_packets/candidate_validation_report.template.json",
            "work_packets/candidate_validation_report_preview.json",
            "work_packets/operatorpreflight_unitcase_intake_plan.json",
            "work_packets/nested/operatorpreflight_unitcase_candidate_validation_report.json",
            "work_packets/candidate_validation_report.txt",
            "work_packets/operatorpreflight_unitcase_report.json",
        ]
        for rejected in rejected_paths:
            with self.subTest(rejected=rejected):
                with self.assertRaises(submission_manifest.ManifestError):
                    submission_manifest.safe_candidate_validation_report_output(rejected)

        accepted.write_text("already present\n", encoding="utf-8")
        with self.assertRaisesRegex(submission_manifest.ManifestError, "already exists"):
            submission_manifest.safe_candidate_validation_report_output(
                str(accepted.relative_to(ROOT))
            )

    def test_cli_emit_intake_plan_writes_no_real_or_canonical_artifacts(self) -> None:
        manifest_path = self.write_operator_manifest()
        plan_path = ROOT / "work_packets" / "operatorpreflight_unitcase_cli_intake_plan.json"
        if plan_path.exists() or plan_path.is_symlink():
            plan_path.unlink()
        self.created_plan_paths.append(plan_path)
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = submission_manifest.main(
                [
                    "--manifest",
                    str(manifest_path.relative_to(ROOT)),
                    "--emit-intake-plan",
                    str(plan_path.relative_to(ROOT)),
                ]
            )

        self.assertEqual(status, 0)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        printed = json.loads(stdout.getvalue())
        self.assertEqual(printed, plan)
        self.assertEqual(plan["artifact_id"], "kg_real_evidence_candidate_intake_plan_v1")
        self.assertEqual(len(plan["execution_plan"]), EXPECTED_COUNT)
        self.assertEqual(len(plan["preflight_commands"]), EXPECTED_COUNT)
        self.assertTrue(all("--preflight-response" in row for row in plan["preflight_commands"]))
        self.assertFalse(plan["authority"]["writes_candidate_artifacts"])
        self.assertFalse(plan["authority"]["writes_canonical_packets"])

    def test_cli_emit_intake_plan_does_not_leave_partial_plan_on_write_failure(
        self,
    ) -> None:
        manifest_path = self.write_operator_manifest()
        plan_path = ROOT / "work_packets" / "operatorpreflight_unitcase_partial_intake_plan.json"
        temp_path = plan_path.with_name(f".{plan_path.name}.tmp")
        for path in (plan_path, temp_path):
            if path.exists() or path.is_symlink():
                path.unlink()
            self.created_plan_paths.append(path)
        stdout = StringIO()
        original_open = Path.open

        class FailingHandle:
            def __enter__(self) -> "FailingHandle":
                return self

            def __exit__(self, *exc_info: object) -> bool:
                return False

            def write(self, _text: str) -> int:
                with original_open(temp_path, "w", encoding="utf-8") as handle:
                    handle.write("partial plan\n")
                raise OSError("simulated interrupted intake-plan write")

        def fake_open(path_self: Path, *args: object, **kwargs: object) -> object:
            mode = args[0] if args else kwargs.get("mode", "r")
            if path_self == temp_path and mode == "x":
                return FailingHandle()
            return original_open(path_self, *args, **kwargs)

        with (
            mock.patch.object(Path, "open", autospec=True, side_effect=fake_open),
            redirect_stdout(stdout),
            self.assertRaisesRegex(OSError, "simulated interrupted intake-plan write"),
        ):
            submission_manifest.main(
                [
                    "--manifest",
                    str(manifest_path.relative_to(ROOT)),
                    "--emit-intake-plan",
                    str(plan_path.relative_to(ROOT)),
                ]
            )

        self.assertFalse(plan_path.exists())
        self.assertFalse(temp_path.exists())
        self.assertEqual(stdout.getvalue(), "")

    def test_cli_execute_candidate_intakes_writes_no_canonical_packets_itself(self) -> None:
        manifest_path = self.write_operator_manifest()
        stdout = StringIO()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"artifact_id": "candidate_intake_result"}\n',
            stderr="",
        )

        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            return_value=completed,
        ) as run_mock:
            with redirect_stdout(stdout):
                status = submission_manifest.main(
                    [
                        "--manifest",
                        str(manifest_path.relative_to(ROOT)),
                        "--execute-candidate-intakes",
                    ]
                )

        self.assertEqual(status, 0)
        printed = json.loads(stdout.getvalue())
        self.assertEqual(
            printed["artifact_id"],
            "kg_real_evidence_candidate_intake_execution_v1",
        )
        self.assertTrue(printed["authority"]["writes_candidate_artifacts"])
        self.assertFalse(printed["authority"]["writes_canonical_packets"])
        self.assertFalse(printed["authority"]["counts_as_acceptance_gate"])
        self.assertEqual(run_mock.call_count, EXPECTED_COUNT)

    def test_cli_preflight_responses_writes_no_candidate_or_canonical_packets(self) -> None:
        manifest_path = self.write_operator_manifest()
        stdout = StringIO()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"artifact_id": "response_preflight"}\n',
            stderr="",
        )

        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            return_value=completed,
        ) as run_mock:
            with redirect_stdout(stdout):
                status = submission_manifest.main(
                    [
                        "--manifest",
                        str(manifest_path.relative_to(ROOT)),
                        "--preflight-responses",
                    ]
                )

        self.assertEqual(status, 0)
        printed = json.loads(stdout.getvalue())
        self.assertEqual(
            printed["artifact_id"],
            "kg_real_evidence_response_preflight_execution_v1",
        )
        self.assertFalse(printed["authority"]["writes_candidate_artifacts"])
        self.assertFalse(printed["authority"]["writes_canonical_packets"])
        self.assertFalse(printed["authority"]["counts_as_acceptance_gate"])
        self.assertTrue(printed["preflight_effects"]["reads_response_packet_contents"])
        self.assertEqual(run_mock.call_count, EXPECTED_COUNT)

    def test_cli_validate_candidate_manifests_writes_no_artifacts_or_canonical_packets(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        stdout = StringIO()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"validation_report": {"passed": true, "blockers": []}}\n',
            stderr="",
        )

        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            return_value=completed,
        ) as run_mock:
            with redirect_stdout(stdout):
                status = submission_manifest.main(
                    [
                        "--manifest",
                        str(manifest_path.relative_to(ROOT)),
                        "--validate-candidate-manifests",
                    ]
                )

        self.assertEqual(status, 0)
        printed = json.loads(stdout.getvalue())
        self.assertEqual(
            printed["artifact_id"],
            "kg_real_evidence_candidate_manifest_validation_v1",
        )
        self.assertFalse(printed["authority"]["writes_candidate_artifacts"])
        self.assertFalse(printed["authority"]["writes_canonical_packets"])
        self.assertFalse(printed["authority"]["counts_as_acceptance_gate"])
        self.assertTrue(printed["validation_effects"]["reads_candidate_artifacts"])
        self.assertEqual(run_mock.call_count, EXPECTED_COUNT)

    def test_cli_validate_candidate_manifests_can_write_non_evidence_report(self) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        report_path = (
            ROOT
            / "work_packets"
            / "operatorpreflight_unitcase_cli_candidate_validation_report.json"
        )
        if report_path.exists() or report_path.is_symlink():
            report_path.unlink()
        self.created_validation_report_paths.append(report_path)
        stdout = StringIO()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"validation_report": {"passed": true, "blockers": []}}\n',
            stderr="",
        )

        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            return_value=completed,
        ) as run_mock:
            with redirect_stdout(stdout):
                status = submission_manifest.main(
                    [
                        "--manifest",
                        str(manifest_path.relative_to(ROOT)),
                        "--validate-candidate-manifests",
                        "--emit-candidate-validation-report",
                        str(report_path.relative_to(ROOT)),
                    ]
                )

        self.assertEqual(status, 0)
        printed = json.loads(stdout.getvalue())
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(saved, printed)
        self.assertEqual(
            saved["artifact_id"],
            "kg_real_evidence_candidate_manifest_validation_v1",
        )
        self.assertFalse(saved["authority"]["accepts_evidence"])
        self.assertFalse(saved["authority"]["promotes_evidence"])
        self.assertFalse(saved["authority"]["writes_candidate_artifacts"])
        self.assertFalse(saved["authority"]["writes_canonical_packets"])
        self.assertFalse(saved["authority"]["counts_as_acceptance_gate"])
        self.assertEqual(run_mock.call_count, EXPECTED_COUNT)

    def test_cli_validate_candidate_manifests_writes_failure_report_after_execution(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        report_path = (
            ROOT
            / "work_packets"
            / "operatorpreflight_unitcase_failed_candidate_validation_report.json"
        )
        if report_path.exists() or report_path.is_symlink():
            report_path.unlink()
        self.created_validation_report_paths.append(report_path)
        stdout = StringIO()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"validation_report": {"passed": false, "blockers": ["blocked"]}}\n',
            stderr="",
        )

        with mock.patch.object(
            submission_manifest.subprocess,
            "run",
            return_value=completed,
        ):
            with redirect_stdout(stdout):
                status = submission_manifest.main(
                    [
                        "--manifest",
                        str(manifest_path.relative_to(ROOT)),
                        "--validate-candidate-manifests",
                        "--emit-candidate-validation-report",
                        str(report_path.relative_to(ROOT)),
                    ]
                )

        self.assertEqual(status, 1)
        printed = json.loads(stdout.getvalue())
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(saved, printed)
        self.assertFalse(saved["overall_success"])
        self.assertTrue(saved["candidate_manifest_preflight_passed"])
        self.assertTrue(
            all(row["stdout_summary"]["blocker_count"] == 1 for row in saved["validation_results"])
        )

    def test_cli_validate_candidate_manifests_does_not_leave_partial_report_on_write_failure(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest()
        report_path = (
            ROOT
            / "work_packets"
            / "operatorpreflight_unitcase_partial_candidate_validation_report.json"
        )
        temp_path = report_path.with_name(f".{report_path.name}.tmp")
        for path in (report_path, temp_path):
            if path.exists() or path.is_symlink():
                path.unlink()
            self.created_validation_report_paths.append(path)
        stdout = StringIO()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"validation_report": {"passed": true, "blockers": []}}\n',
            stderr="",
        )
        original_open = Path.open

        class FailingHandle:
            def __enter__(self) -> "FailingHandle":
                return self

            def __exit__(self, *exc_info: object) -> bool:
                return False

            def write(self, _text: str) -> int:
                with original_open(temp_path, "w", encoding="utf-8") as handle:
                    handle.write("partial report\n")
                raise OSError("simulated interrupted report write")

        def fake_open(path_self: Path, *args: object, **kwargs: object) -> object:
            mode = args[0] if args else kwargs.get("mode", "r")
            if path_self == temp_path and mode == "x":
                return FailingHandle()
            return original_open(path_self, *args, **kwargs)

        with (
            mock.patch.object(
                submission_manifest.subprocess,
                "run",
                return_value=completed,
            ),
            mock.patch.object(Path, "open", autospec=True, side_effect=fake_open),
            redirect_stdout(stdout),
            self.assertRaisesRegex(OSError, "simulated interrupted report write"),
        ):
            submission_manifest.main(
                [
                    "--manifest",
                    str(manifest_path.relative_to(ROOT)),
                    "--validate-candidate-manifests",
                    "--emit-candidate-validation-report",
                    str(report_path.relative_to(ROOT)),
                ]
            )

        self.assertFalse(report_path.exists())
        self.assertFalse(temp_path.exists())
        self.assertEqual(stdout.getvalue(), "")

    def test_cli_validate_candidate_manifests_does_not_write_report_without_candidates(
        self,
    ) -> None:
        manifest_path = self.write_operator_manifest()
        report_path = (
            ROOT
            / "work_packets"
            / "operatorpreflight_unitcase_missing_candidate_validation_report.json"
        )
        if report_path.exists() or report_path.is_symlink():
            report_path.unlink()
        self.created_validation_report_paths.append(report_path)
        stdout = StringIO()

        with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
            with redirect_stdout(stdout):
                status = submission_manifest.main(
                    [
                        "--manifest",
                        str(manifest_path.relative_to(ROOT)),
                        "--validate-candidate-manifests",
                        "--emit-candidate-validation-report",
                        str(report_path.relative_to(ROOT)),
                    ]
                )

        self.assertEqual(status, 1)
        self.assertFalse(report_path.exists())
        run_mock.assert_not_called()
        printed = json.loads(stdout.getvalue())
        self.assertFalse(printed["candidate_manifest_preflight_passed"])
        self.assertEqual(printed["executed_gate_count"], 0)

    def test_cli_validate_candidate_manifests_does_not_write_report_for_invalid_manifest(
        self,
    ) -> None:
        self.write_candidate_manifests()
        manifest_path = self.write_operator_manifest(
            "operatorpreflight_unitcase_invalid_validation_manifest.json"
        )
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        loaded["submissions"][0]["response_packet"] = (
            "inputs/enterprise_multimodal_real/missing.json"
        )
        manifest_path.write_text(json.dumps(loaded), encoding="utf-8")
        report_path = (
            ROOT
            / "work_packets"
            / "operatorpreflight_unitcase_invalid_candidate_validation_report.json"
        )
        if report_path.exists() or report_path.is_symlink():
            report_path.unlink()
        self.created_validation_report_paths.append(report_path)
        stdout = StringIO()

        with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
            with redirect_stdout(stdout):
                status = submission_manifest.main(
                    [
                        "--manifest",
                        str(manifest_path.relative_to(ROOT)),
                        "--validate-candidate-manifests",
                        "--emit-candidate-validation-report",
                        str(report_path.relative_to(ROOT)),
                    ]
                )

        self.assertEqual(status, 1)
        self.assertFalse(report_path.exists())
        run_mock.assert_not_called()
        printed = json.loads(stdout.getvalue())
        self.assertFalse(printed["valid"])
        self.assertEqual(printed["validated_submissions"], [])

    def test_invalid_manifest_execute_candidate_intakes_runs_no_commands(self) -> None:
        manifest_path = self.write_operator_manifest(
            "operatorpreflight_unitcase_invalid_execute_manifest.json"
        )
        payload = self.valid_manifest()
        submissions = payload["submissions"]
        assert isinstance(submissions, list)
        submissions[0]["response_packet_type"] = "wrong_packet_type"
        write_json(manifest_path, payload)
        stdout = StringIO()

        with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
            with redirect_stdout(stdout):
                status = submission_manifest.main(
                    [
                        "--manifest",
                        str(manifest_path.relative_to(ROOT)),
                        "--execute-candidate-intakes",
                    ]
                )

        self.assertEqual(status, 1)
        run_mock.assert_not_called()
        printed = json.loads(stdout.getvalue())
        self.assertFalse(printed["valid"])
        self.assertTrue(
            any("response_packet_type mismatch" in blocker for blocker in printed["blockers"])
        )

    def test_invalid_manifest_preflight_responses_runs_no_commands(self) -> None:
        manifest_path = self.write_operator_manifest(
            "operatorpreflight_unitcase_invalid_preflight_manifest.json"
        )
        payload = self.valid_manifest()
        submissions = payload["submissions"]
        assert isinstance(submissions, list)
        submissions[0]["response_packet_type"] = "wrong_packet_type"
        write_json(manifest_path, payload)
        stdout = StringIO()

        with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
            with redirect_stdout(stdout):
                status = submission_manifest.main(
                    [
                        "--manifest",
                        str(manifest_path.relative_to(ROOT)),
                        "--preflight-responses",
                    ]
                )

        self.assertEqual(status, 1)
        run_mock.assert_not_called()
        printed = json.loads(stdout.getvalue())
        self.assertFalse(printed["valid"])
        self.assertTrue(
            any("response_packet_type mismatch" in blocker for blocker in printed["blockers"])
        )

    def test_invalid_manifest_validate_candidate_manifests_runs_no_commands(self) -> None:
        manifest_path = self.write_operator_manifest(
            "operatorpreflight_unitcase_invalid_validate_manifest.json"
        )
        payload = self.valid_manifest()
        submissions = payload["submissions"]
        assert isinstance(submissions, list)
        submissions[0]["response_packet_type"] = "wrong_packet_type"
        write_json(manifest_path, payload)
        stdout = StringIO()

        with mock.patch.object(submission_manifest.subprocess, "run") as run_mock:
            with redirect_stdout(stdout):
                status = submission_manifest.main(
                    [
                        "--manifest",
                        str(manifest_path.relative_to(ROOT)),
                        "--validate-candidate-manifests",
                    ]
                )

        self.assertEqual(status, 1)
        run_mock.assert_not_called()
        printed = json.loads(stdout.getvalue())
        self.assertFalse(printed["valid"])
        self.assertTrue(
            any("response_packet_type mismatch" in blocker for blocker in printed["blockers"])
        )

    def test_execute_candidate_intakes_rejects_path_only_validation_mode(self) -> None:
        manifest_path = self.write_operator_manifest()

        with self.assertRaisesRegex(
            submission_manifest.ManifestError,
            "require existing response packets",
        ):
            submission_manifest.main(
                [
                    "--manifest",
                    str(manifest_path.relative_to(ROOT)),
                    "--no-require-existing-response-packets",
                    "--execute-candidate-intakes",
                ]
            )
        with self.assertRaisesRegex(
            submission_manifest.ManifestError,
            "require existing response packets",
        ):
            submission_manifest.main(
                [
                    "--manifest",
                    str(manifest_path.relative_to(ROOT)),
                    "--no-require-existing-response-packets",
                    "--preflight-responses",
                ]
            )

    def test_emit_candidate_validation_report_requires_candidate_validation_mode(self) -> None:
        manifest_path = self.write_operator_manifest()
        report_path = (
            ROOT
            / "work_packets"
            / "operatorpreflight_unitcase_requires_validate_candidate_validation_report.json"
        )
        if report_path.exists() or report_path.is_symlink():
            report_path.unlink()
        self.created_validation_report_paths.append(report_path)

        with self.assertRaisesRegex(
            submission_manifest.ManifestError,
            "requires --validate-candidate-manifests",
        ):
            submission_manifest.main(
                [
                    "--manifest",
                    str(manifest_path.relative_to(ROOT)),
                    "--emit-candidate-validation-report",
                    str(report_path.relative_to(ROOT)),
                ]
            )

    def test_emit_plan_preflight_execute_and_candidate_validation_are_mutually_exclusive(
        self,
    ) -> None:
        manifest_path = self.write_operator_manifest()
        plan_path = ROOT / "work_packets" / "operatorpreflight_unitcase_exclusive_plan.json"
        if plan_path.exists() or plan_path.is_symlink():
            plan_path.unlink()
        self.created_plan_paths.append(plan_path)

        with self.assertRaisesRegex(
            submission_manifest.ManifestError,
            "mutually exclusive",
        ):
            submission_manifest.main(
                [
                    "--manifest",
                    str(manifest_path.relative_to(ROOT)),
                    "--emit-intake-plan",
                    str(plan_path.relative_to(ROOT)),
                    "--execute-candidate-intakes",
                    "--validate-candidate-manifests",
                ]
            )

        with self.assertRaisesRegex(
            submission_manifest.ManifestError,
            "mutually exclusive",
        ):
            submission_manifest.main(
                [
                    "--manifest",
                    str(manifest_path.relative_to(ROOT)),
                    "--preflight-responses",
                    "--execute-candidate-intakes",
                ]
            )

        with self.assertRaisesRegex(
            submission_manifest.ManifestError,
            "mutually exclusive",
        ):
            submission_manifest.main(
                [
                    "--manifest",
                    str(manifest_path.relative_to(ROOT)),
                    "--execute-candidate-intakes",
                    "--validate-candidate-manifests",
                ]
            )

    def test_invalid_manifest_emit_intake_plan_writes_no_plan_file(self) -> None:
        manifest_path = self.write_operator_manifest(
            "operatorpreflight_unitcase_invalid_manifest.json"
        )
        payload = self.valid_manifest()
        submissions = payload["submissions"]
        assert isinstance(submissions, list)
        submissions[0]["response_packet_type"] = "wrong_packet_type"
        write_json(manifest_path, payload)
        plan_path = ROOT / "work_packets" / "operatorpreflight_unitcase_invalid_plan.json"
        if plan_path.exists() or plan_path.is_symlink():
            plan_path.unlink()
        self.created_plan_paths.append(plan_path)
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = submission_manifest.main(
                [
                    "--manifest",
                    str(manifest_path.relative_to(ROOT)),
                    "--emit-intake-plan",
                    str(plan_path.relative_to(ROOT)),
                ]
            )

        self.assertEqual(status, 1)
        self.assertFalse(plan_path.exists())
        printed = json.loads(stdout.getvalue())
        self.assertFalse(printed["valid"])
        self.assertTrue(
            any("response_packet_type mismatch" in blocker for blocker in printed["blockers"])
        )

    def test_cli_manifest_input_rejects_symlinked_operator_manifest(self) -> None:
        target = self.write_operator_manifest("operatorpreflight_unitcase_target.json")
        symlink_path = ROOT / "work_packets" / "operatorpreflight_unitcase_symlink.json"
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(target.name)
        self.created_manifest_paths.append(symlink_path)

        with self.assertRaisesRegex(submission_manifest.ManifestError, "symlink components"):
            submission_manifest.safe_manifest_input(str(symlink_path.relative_to(ROOT)))

    def test_cli_manifest_input_rejects_hardlink_alias(self) -> None:
        target = self.write_operator_manifest("operatorpreflight_unitcase_target.json")
        hardlink_path = ROOT / "work_packets" / "operatorpreflight_unitcase_hardlink.json"
        if hardlink_path.exists() or hardlink_path.is_symlink():
            hardlink_path.unlink()
        hardlink_path.hardlink_to(target)
        self.created_manifest_paths.append(hardlink_path)

        with self.assertRaisesRegex(submission_manifest.ManifestError, "hardlink aliases"):
            submission_manifest.safe_manifest_input(str(hardlink_path.relative_to(ROOT)))

    def test_work_packet_gitignore_keeps_operator_outputs_untracked(self) -> None:
        ignore_lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

        self.assertIn(".formowl/kg-eval/work_packets/*", ignore_lines)
        self.assertNotIn("!.formowl/kg-eval/work_packets/*.json", ignore_lines)
        self.assertNotIn("!.formowl/kg-eval/work_packets/*.md", ignore_lines)
        self.assertNotIn("!.formowl/kg-eval/work_packets/*_preview.json", ignore_lines)
        self.assertIn(
            "!.formowl/kg-eval/work_packets/fair_baseline_run_work_packet_preview.json",
            ignore_lines,
        )
        self.assertIn(
            "!.formowl/kg-eval/work_packets/human_annotation_work_packet_preview.json",
            ignore_lines,
        )
        self.assertIn(
            "!.formowl/kg-eval/work_packets/enterprise_multimodal_collection_packet_preview.json",
            ignore_lines,
        )
        self.assertIn(
            "!.formowl/kg-eval/work_packets/production_adapter_collection_packet_preview.json",
            ignore_lines,
        )
        self.assertIn(
            "!.formowl/kg-eval/work_packets/remaining_real_evidence_submission_manifest.template.json",
            ignore_lines,
        )
        self.assertIn(
            "!.formowl/kg-eval/work_packets/remaining_real_evidence_operator_guide.md",
            ignore_lines,
        )

    def test_manifest_requires_exact_remaining_gate_order_and_types(self) -> None:
        payload = self.valid_manifest()
        submissions = payload["submissions"]
        assert isinstance(submissions, list)
        submissions[0], submissions[1] = submissions[1], submissions[0]
        submissions[-1]["response_packet_type"] = "wrong_packet_type"

        report = submission_manifest.validate_manifest(payload)

        self.assertFalse(report["valid"])
        self.assertIn(
            "submission gate order must match the remaining KG gate order",
            report["blockers"],
        )
        self.assertTrue(
            any("response_packet_type mismatch" in blocker for blocker in report["blockers"])
        )

    def test_manifest_rejects_unsafe_run_id_and_output_dir(self) -> None:
        payload = self.valid_manifest()
        submissions = payload["submissions"]
        assert isinstance(submissions, list)
        submissions[0]["operator_run_id"] = "test_fixture_run"
        submissions[0]["output_dir"] = "inputs/enterprise_multimodal_real/nested/operator_run"

        report = submission_manifest.validate_manifest(payload)

        self.assertFalse(report["valid"])
        self.assertTrue(
            any("operator_run_id must not use test" in blocker for blocker in report["blockers"])
        )
        self.assertTrue(
            any("output_dir must be exactly" in blocker for blocker in report["blockers"])
        )

    def test_manifest_rejects_canonical_and_raw_response_packet_paths(self) -> None:
        payload = self.valid_manifest()
        submissions = payload["submissions"]
        assert isinstance(submissions, list)
        submissions[0]["response_packet"] = submission_manifest.EXPECTED_SUBMISSIONS[
            0
        ].canonical_packet
        submissions[1]["response_packet"] = "/tmp/operator_response.json"

        report = submission_manifest.validate_manifest(
            payload,
            require_existing_response_packets=False,
        )

        self.assertFalse(report["valid"])
        self.assertTrue(any("canonical input packets" in blocker for blocker in report["blockers"]))
        self.assertTrue(any("safe repo-relative path" in blocker for blocker in report["blockers"]))

    def test_manifest_rejects_missing_response_packets_by_default(self) -> None:
        self.response_paths[0].unlink()

        report = submission_manifest.validate_manifest(self.valid_manifest())

        self.assertFalse(report["valid"])
        self.assertTrue(
            any("response_packet file is missing" in blocker for blocker in report["blockers"])
        )

    def test_manifest_rejects_symlinked_response_packet_components(self) -> None:
        symlink_response = self.response_paths[0]
        symlink_response.unlink()
        symlink_response.symlink_to(TEMPLATE_PATH)
        payload = self.valid_manifest()

        report = submission_manifest.validate_manifest(
            payload,
            require_existing_response_packets=False,
        )

        self.assertFalse(report["valid"])
        self.assertTrue(any("symlink components" in blocker for blocker in report["blockers"]))

    def test_manifest_rejects_hardlink_alias_response_packet(self) -> None:
        hardlink_response = self.response_paths[0]
        hardlink_response.unlink()
        hardlink_response.hardlink_to(TEMPLATE_PATH)

        report = submission_manifest.validate_manifest(self.valid_manifest())

        self.assertFalse(report["valid"])
        self.assertTrue(any("hardlink aliases" in blocker for blocker in report["blockers"]))

    def test_manifest_rejects_promotion_or_extra_control_fields(self) -> None:
        payload = self.valid_manifest()
        payload["promote"] = True
        submissions = payload["submissions"]
        assert isinstance(submissions, list)
        submissions[0]["allow_test_artifacts"] = True

        report = submission_manifest.validate_manifest(payload)

        self.assertFalse(report["valid"])
        self.assertTrue(
            any("unsupported top-level fields" in blocker for blocker in report["blockers"])
        )
        self.assertTrue(
            any("unsupported submission fields" in blocker for blocker in report["blockers"])
        )


if __name__ == "__main__":
    unittest.main()
