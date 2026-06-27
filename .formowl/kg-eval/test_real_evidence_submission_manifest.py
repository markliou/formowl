#!/usr/bin/env python3
"""Tests for the KG real-evidence operator submission manifest preflight."""

from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import real_evidence_submission_manifest as submission_manifest


ROOT = submission_manifest.ROOT
REPO_ROOT = ROOT.parents[1]
TEMPLATE_PATH = submission_manifest.DEFAULT_TEMPLATE_OUTPUT


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

    def tearDown(self) -> None:
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

    def test_valid_manifest_returns_candidate_only_intake_commands(self) -> None:
        report = submission_manifest.validate_manifest(self.valid_manifest())

        self.assertTrue(report["valid"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(len(report["intake_commands"]), 4)
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
        self.assertEqual(len(plan["execution_plan"]), 4)
        for expected, row in zip(
            submission_manifest.EXPECTED_SUBMISSIONS,
            plan["execution_plan"],
            strict=True,
        ):
            self.assertEqual(row["gate_id"], expected.gate_id)
            self.assertEqual(row["work_packet"], expected.work_packet_path)
            self.assertEqual(row["canonical_packet_not_written"], expected.canonical_packet)
            self.assertTrue(row["execution_effects"]["reads_response_packet_contents"])
            self.assertTrue(row["execution_effects"]["writes_candidate_artifacts"])
            self.assertFalse(row["execution_effects"]["writes_canonical_packets"])
            self.assertFalse(row["execution_effects"]["promotes_evidence"])
            self.assertFalse(row["execution_effects"]["counts_as_acceptance_gate"])
            self.assertEqual(row["argv"][0], "python3")
            self.assertEqual(row["argv"][1], expected.intake_script)
            self.assertIn("--response-packet", row["argv"])
            self.assertIn("--assembly-manifest-output", row["argv"])
            self.assertNotIn("--promote", row["argv"])
            self.assertNotIn("--allow-test-artifacts", row["argv"])

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
            "work_packets/fair_external_baseline_comparison_candidate_manifest.json",
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
            "work_packets/fair_baseline_run_work_packet_preview.json",
            "work_packets/fair_external_baseline_comparison_candidate_manifest.json",
            "work_packets/intake_plan.template.json",
            "work_packets/intake_plan_preview.json",
            "work_packets/intake_plan.txt",
        ]
        for rejected in rejected_paths:
            with self.subTest(rejected=rejected):
                with self.assertRaises(submission_manifest.ManifestError):
                    submission_manifest.safe_intake_plan_output(rejected)

        accepted.write_text("already present\n", encoding="utf-8")
        with self.assertRaisesRegex(submission_manifest.ManifestError, "already exists"):
            submission_manifest.safe_intake_plan_output(str(accepted.relative_to(ROOT)))

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
        self.assertEqual(len(plan["execution_plan"]), 4)
        self.assertFalse(plan["authority"]["writes_candidate_artifacts"])
        self.assertFalse(plan["authority"]["writes_canonical_packets"])

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
        submissions[2]["response_packet_type"] = "wrong_packet_type"

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
        submissions[0]["output_dir"] = "inputs/fair_baseline_real/nested/operator_run"

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
        submissions[0]["response_packet"] = "inputs/fair_external_baseline_run_packet.json"
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
