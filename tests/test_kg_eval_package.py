from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_kg_eval.cli import main as kg_eval_cli_main
from formowl_kg_eval.runner import (
    build_acceptance_summary,
    kg_eval_workspace,
    run_kg_eval_command,
)


class KGEvalPackageTests(unittest.TestCase):
    def test_workspace_resolution_uses_repo_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            workspace = repo_root / ".formowl" / "kg-eval"
            workspace.mkdir(parents=True)

            self.assertEqual(kg_eval_workspace(repo_root), workspace)

    def test_run_command_invokes_authoritative_script_in_eval_workspace(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            workspace = repo_root / ".formowl" / "kg-eval"
            workspace.mkdir(parents=True)
            (workspace / "kg_total_acceptance_suite.py").write_text(
                "# placeholder script\n",
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(
                args=["python", "kg_total_acceptance_suite.py"],
                returncode=0,
                stdout="{}",
                stderr="",
            )

            with patch("formowl_kg_eval.runner.subprocess.run", return_value=completed) as run:
                result = run_kg_eval_command("total", repository_root=repo_root)

            self.assertTrue(result.passed)
            self.assertEqual(result.script, "kg_total_acceptance_suite.py")
            run.assert_called_once()
            self.assertEqual(run.call_args.kwargs["cwd"], workspace)

    def test_acceptance_summary_redacts_workspace_and_exposes_integration_boundary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            workspace = repo_root / ".formowl" / "kg-eval"
            results = workspace / "results"
            results.mkdir(parents=True)
            _write_json(
                results / "kg_total_acceptance_snapshot.json",
                {
                    "summary": {
                        "overall_passed": True,
                        "passed_gate_count": 12,
                        "failed_gate_count": 0,
                        "failed_gate_ids": [],
                        "gate_status_sha256": "gatehash",
                    }
                },
            )
            _write_json(
                results / "kg_objective_completion_audit.json",
                {
                    "objective_complete": True,
                    "proved_requirement_count": 9,
                    "incomplete_requirement_count": 0,
                    "audit_sha256": "audithash",
                },
            )
            _write_json(
                results / "real_evidence_preflight.json",
                {
                    "preflight_state": "validator_clear_for_all_broad_gates",
                    "summary": {
                        "blocked_gate_count": 0,
                        "blocked_gate_ids": [],
                        "validator_clear_gate_ids": ["production_adapter_paths"],
                    },
                },
            )
            _write_json(
                results / "real_evidence_collection_work_orders.json",
                {"summary": {"work_order_count": 0, "work_order_gate_ids": []}},
            )
            _write_json(
                results / "real_evidence_gate_progress.json",
                {
                    "summary": {
                        "gate_count": 0,
                        "blocked_gate_ids": [],
                        "total_acceptance_state": "clear",
                    }
                },
            )
            _write_json(
                workspace / "remaining_evidence_checklist.json",
                {
                    "overall_passed": True,
                    "passed_gate_count": 12,
                    "failed_gate_count": 0,
                    "remaining_gates": [],
                },
            )

            summary = build_acceptance_summary(repository_root=repo_root)

            rendered = json.dumps(summary, sort_keys=True)
            self.assertEqual(summary["total_acceptance"]["passed_gate_count"], 12)
            self.assertEqual(summary["work_orders"]["work_order_count"], 0)
            self.assertEqual(
                summary["integration_boundary"]["system_agent_should_call"],
                "formowl-kg-eval summary",
            )
            self.assertFalse(
                summary["claim_boundary"]["supports_full_product_production_ready_claim"]
            )
            self.assertNotIn(str(repo_root), rendered)

    def test_cli_summary_prints_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            workspace = repo_root / ".formowl" / "kg-eval"
            results = workspace / "results"
            results.mkdir(parents=True)
            _write_minimal_reports(workspace)

            with patch("builtins.print") as print_mock:
                exit_code = kg_eval_cli_main(["--repo-root", str(repo_root), "summary"])

            self.assertEqual(exit_code, 0)
            printed = print_mock.call_args.args[0]
            self.assertEqual(
                json.loads(printed)["artifact_id"],
                "formowl_kg_eval_acceptance_summary_v1",
            )


def _write_minimal_reports(workspace: Path) -> None:
    results = workspace / "results"
    _write_json(
        results / "kg_total_acceptance_snapshot.json",
        {"summary": {"overall_passed": True, "passed_gate_count": 12, "failed_gate_count": 0}},
    )
    _write_json(
        results / "kg_objective_completion_audit.json",
        {
            "objective_complete": True,
            "proved_requirement_count": 9,
            "incomplete_requirement_count": 0,
        },
    )
    _write_json(results / "real_evidence_preflight.json", {"summary": {}})
    _write_json(results / "real_evidence_collection_work_orders.json", {"summary": {}})
    _write_json(results / "real_evidence_gate_progress.json", {"summary": {}})
    _write_json(workspace / "remaining_evidence_checklist.json", {"remaining_gates": []})


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
