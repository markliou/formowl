from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
import formowl_kg_eval
from formowl_kg_eval import build_benchmark_summary
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

    def test_run_command_redacts_local_workspace_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            workspace = repo_root / ".formowl" / "kg-eval"
            workspace.mkdir(parents=True)
            (workspace / "real_evidence_preflight.py").write_text(
                "# placeholder script\n",
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(
                args=["python", "real_evidence_preflight.py"],
                returncode=0,
                stdout=f'{{"workspace": "{workspace}", "root": "{repo_root}"}}',
                stderr=f"checked {workspace}",
            )

            with patch("formowl_kg_eval.runner.subprocess.run", return_value=completed):
                result = run_kg_eval_command("preflight", repository_root=repo_root)

            self.assertNotIn(str(workspace), result.stdout)
            self.assertNotIn(str(repo_root), result.stdout)
            self.assertNotIn(str(workspace), result.stderr)
            self.assertIn(".formowl/kg-eval", result.stdout)
            self.assertIn("<FORMOWL_REPOSITORY_ROOT>", result.stdout)

    def test_top_level_package_does_not_export_workspace_resolver(self) -> None:
        self.assertNotIn("kg_eval_workspace", formowl_kg_eval.__all__)
        self.assertFalse(hasattr(formowl_kg_eval, "kg_eval_workspace"))

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
                    "checklist_sync": {"status": "synchronized"},
                    "summary": {
                        "blocked_gate_count": 0,
                        "blocked_gate_ids": [],
                        "checklist_sync_status": "synchronized",
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
                    "gate_status_sha256": "gatehash",
                    "objective_audit_sha256": "audithash",
                    "source_snapshot": "results/kg_total_acceptance_snapshot.json",
                    "source_objective_audit": "results/kg_objective_completion_audit.json",
                },
            )
            _write_minimal_benchmark_artifacts(repo_root)

            summary = build_acceptance_summary(repository_root=repo_root)

            rendered = json.dumps(summary, sort_keys=True)
            self.assertEqual(summary["authority_state"]["state"], "clear")
            self.assertTrue(summary["authority_state"]["consistent"])
            self.assertTrue(
                summary["claim_boundary"]["supports_broad_kg_real_evidence_acceptance_claim"]
            )
            self.assertEqual(summary["total_acceptance"]["passed_gate_count"], 12)
            self.assertEqual(summary["work_orders"]["work_order_count"], 0)
            self.assertEqual(
                summary["integration_boundary"]["system_agent_should_call"],
                "formowl-kg-eval summary",
            )
            self.assertFalse(
                summary["claim_boundary"]["supports_full_product_production_ready_claim"]
            )
            candidate_capabilities = summary["candidate_generation_capabilities"]
            self.assertTrue(
                candidate_capabilities["selection_boundary"][
                    "bert_or_sentence_transformer_available_as_adapter_slot"
                ]
            )
            self.assertTrue(candidate_capabilities["selection_boundary"]["neural_models_optional"])
            self.assertEqual(len(candidate_capabilities["profiles"]), 3)
            benchmark_results = summary["kg_benchmark_results"]
            self.assertEqual(
                benchmark_results["artifact_id"],
                "formowl_kg_benchmark_summary_v1",
            )
            self.assertEqual(
                benchmark_results["headline_results"]["public_enterprise_50k_bge_vs_lexical"][
                    "f1_delta"
                ],
                0.677746,
            )
            self.assertNotIn(str(repo_root), rendered)
            self.assertNotIn("pair_result_sample", rendered)

    def test_acceptance_summary_detects_stale_checklist_and_fails_closed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            workspace = repo_root / ".formowl" / "kg-eval"
            results = workspace / "results"
            results.mkdir(parents=True)
            failed_gate_ids = [
                "fair_external_baseline_comparison",
                "annotation_adjudication_protocol",
                "multimodal_semantic_validation",
                "production_adapter_paths",
            ]
            _write_json(
                results / "kg_total_acceptance_snapshot.json",
                {
                    "summary": {
                        "overall_passed": False,
                        "passed_gate_count": 8,
                        "failed_gate_count": 4,
                        "failed_gate_ids": failed_gate_ids,
                        "gate_status_sha256": "blocked-gatehash",
                    }
                },
            )
            _write_json(
                results / "kg_objective_completion_audit.json",
                {
                    "objective_complete": False,
                    "proved_requirement_count": 5,
                    "incomplete_requirement_count": 4,
                    "audit_sha256": "blocked-audithash",
                },
            )
            _write_json(
                results / "real_evidence_preflight.json",
                {
                    "preflight_state": "blocked",
                    "checklist_sync": {"status": "drifted"},
                    "summary": {
                        "blocked_gate_count": 4,
                        "blocked_gate_ids": failed_gate_ids,
                        "checklist_sync_status": "drifted",
                        "total_acceptance_state": "blocked",
                    },
                },
            )
            _write_json(
                results / "real_evidence_collection_work_orders.json",
                {
                    "work_order_state": "withheld_due_to_checklist_or_preflight_drift",
                    "sync": {"status": "drifted"},
                    "summary": {"work_order_count": 0, "work_order_gate_ids": []},
                },
            )
            _write_json(
                results / "real_evidence_gate_progress.json",
                {
                    "source_report_contract": {"valid": False},
                    "summary": {
                        "gate_count": 0,
                        "blocked_gate_ids": [],
                        "total_acceptance_state": None,
                    },
                },
            )
            _write_json(
                workspace / "remaining_evidence_checklist.json",
                {
                    "overall_passed": True,
                    "passed_gate_count": 12,
                    "failed_gate_count": 0,
                    "remaining_gates": [],
                    "gate_status_sha256": "stale-gatehash",
                    "objective_audit_sha256": "stale-audithash",
                    "source_snapshot": "results/kg_total_acceptance_snapshot.json",
                    "source_objective_audit": "results/kg_objective_completion_audit.json",
                },
            )
            _write_minimal_benchmark_artifacts(repo_root)

            summary = build_acceptance_summary(repository_root=repo_root)

            self.assertEqual(summary["authority_state"]["state"], "drifted")
            self.assertFalse(summary["authority_state"]["consistent"])
            self.assertFalse(
                summary["claim_boundary"]["supports_broad_kg_real_evidence_acceptance_claim"]
            )
            self.assertTrue(summary["remaining_evidence"]["overall_passed"])
            self.assertFalse(summary["total_acceptance"]["overall_passed"])
            self.assertIn(
                "checklist_remaining_gates_match_total_failed_gates",
                summary["authority_state"]["blocking_reasons"],
            )

    def test_benchmark_summary_redacts_pairs_and_exposes_chart_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_minimal_benchmark_artifacts(repo_root)

            summary = build_benchmark_summary(repository_root=repo_root)

            rendered = json.dumps(summary, sort_keys=True)
            self.assertEqual(summary["artifact_id"], "formowl_kg_benchmark_summary_v1")
            self.assertFalse(summary["claim_boundary"]["canonical_graph_write_allowed"])
            self.assertFalse(summary["claim_boundary"]["raw_access_allowed"])
            self.assertEqual(len(summary["artifacts"]), 3)
            self.assertEqual(
                summary["headline_results"]["ontology_guided_bge_vs_bge_only"][
                    "stress_false_positive_before"
                ],
                10000,
            )
            self.assertEqual(
                summary["headline_results"]["ontology_guided_bge_vs_bge_only"][
                    "stress_false_positive_after"
                ],
                0,
            )
            self.assertIn(
                "experiments/kg_bert_ablation/results/charts/"
                "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host_metrics.svg",
                rendered,
            )
            self.assertNotIn("pair_result_sample", rendered)
            self.assertNotIn("private label text", rendered)

    def test_cli_summary_prints_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            workspace = repo_root / ".formowl" / "kg-eval"
            results = workspace / "results"
            results.mkdir(parents=True)
            _write_minimal_reports(workspace)
            _write_minimal_benchmark_artifacts(repo_root)

            with patch("builtins.print") as print_mock:
                exit_code = kg_eval_cli_main(["--repo-root", str(repo_root), "summary"])

            self.assertEqual(exit_code, 0)
            printed = print_mock.call_args.args[0]
            self.assertEqual(
                json.loads(printed)["artifact_id"],
                "formowl_kg_eval_acceptance_summary_v1",
            )

    def test_cli_benchmarks_prints_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            _write_minimal_benchmark_artifacts(repo_root)

            with patch("builtins.print") as print_mock:
                exit_code = kg_eval_cli_main(["--repo-root", str(repo_root), "benchmarks"])

            self.assertEqual(exit_code, 0)
            printed = print_mock.call_args.args[0]
            self.assertEqual(
                json.loads(printed)["artifact_id"],
                "formowl_kg_benchmark_summary_v1",
            )


def _write_minimal_reports(workspace: Path) -> None:
    results = workspace / "results"
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
            "checklist_sync": {"status": "synchronized"},
            "summary": {
                "blocked_gate_count": 0,
                "blocked_gate_ids": [],
                "checklist_sync_status": "synchronized",
            },
        },
    )
    _write_json(
        results / "real_evidence_collection_work_orders.json",
        {
            "work_order_state": "no_remaining_work_orders_all_broad_gates_clear",
            "sync": {"status": "synchronized"},
            "summary": {"work_order_count": 0, "work_order_gate_ids": []},
        },
    )
    _write_json(
        results / "real_evidence_gate_progress.json",
        {
            "source_report_contract": {"valid": True},
            "summary": {"gate_count": 0, "blocked_gate_ids": []},
        },
    )
    _write_json(
        workspace / "remaining_evidence_checklist.json",
        {
            "overall_passed": True,
            "passed_gate_count": 12,
            "failed_gate_count": 0,
            "remaining_gates": [],
            "gate_status_sha256": "gatehash",
            "objective_audit_sha256": "audithash",
            "source_snapshot": "results/kg_total_acceptance_snapshot.json",
            "source_objective_audit": "results/kg_objective_completion_audit.json",
        },
    )


def _write_minimal_benchmark_artifacts(repo_root: Path) -> None:
    results = repo_root / "experiments" / "kg_bert_ablation" / "results"
    charts = results / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    _write_public_benchmark_artifact(
        results / "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json",
        pair_count=10000,
        negative_pair_count=5024,
        lexical_f1=0.078937,
        bge_f1=0.623245,
        f1_delta=0.544308,
    )
    _write_public_benchmark_artifact(
        results / "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json",
        pair_count=50000,
        negative_pair_count=25163,
        lexical_f1=0.080918,
        bge_f1=0.758664,
        f1_delta=0.677746,
    )
    _write_json(
        results / "kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json",
        {
            "artifact_id": "formowl_kg_ontology_ablation_result_v1",
            "created_at": "2026-06-29T00:00:00+00:00",
            "dataset": {
                "dataset_id": "kg_ontology_ablation_stress_v1",
                "dataset_sha256": "sha256:ontology",
                "pair_count": 20000,
                "negative_pair_count": 15044,
                "cross_type_hard_negative_count": 10000,
                "pair_manifest_full_stored": False,
                "pair_result_sample": [{"left_label": "private label text"}],
            },
            "comparison": {
                "status": "completed",
                "comparisons": {
                    "bge_hard_gate_minus_bge_only": {
                        "f1_delta": 0.414884,
                        "precision_delta": 0.711221,
                    }
                },
            },
            "claim_boundary": {
                "candidate_only": True,
                "canonical_graph_write_allowed": False,
                "canonical_type_write_allowed": False,
                "raw_access_allowed": False,
            },
            "runs": [
                {
                    "run_id": "ontology_ablation_bge_only_v1",
                    "status": "completed",
                    "uses_neural_networks": True,
                    "metrics": {"f1": 0.34286, "false_positive": 10177},
                    "stress_metrics": {"false_positive": 10000},
                    "pair_result_sample": [{"left_label": "private label text"}],
                },
                {
                    "run_id": "ontology_ablation_bge_hard_gate_v1",
                    "status": "completed",
                    "uses_neural_networks": True,
                    "metrics": {"f1": 0.757744, "false_positive": 177},
                    "stress_metrics": {"false_positive": 0},
                },
            ],
        },
    )
    for chart_name in [
        "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host_metrics.svg",
        "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host_metrics.svg",
        "kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_metrics.svg",
        "kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_ontology_stress.svg",
    ]:
        (charts / chart_name).write_text("<svg></svg>", encoding="utf-8")


def _write_public_benchmark_artifact(
    path: Path,
    *,
    pair_count: int,
    negative_pair_count: int,
    lexical_f1: float,
    bge_f1: float,
    f1_delta: float,
) -> None:
    _write_json(
        path,
        {
            "artifact_id": "formowl_kg_public_enterprise_benchmark_result_v1",
            "created_at": "2026-06-29T00:00:00+00:00",
            "dataset": {
                "dataset_id": "kg_public_enterprise_benchmark_run_v1",
                "dataset_sha256": "sha256:public",
                "pair_count": pair_count,
                "negative_pair_count": negative_pair_count,
                "pair_manifest_full_stored": False,
                "pair_result_sample": [{"left_label": "private label text"}],
            },
            "comparison": {
                "status": "completed",
                "accuracy_delta_embedding_minus_lexical": 0.27736,
                "f1_delta_embedding_minus_lexical": f1_delta,
                "precision_delta_embedding_minus_lexical": 0.024005,
                "recall_delta_embedding_minus_lexical": 0.590973,
            },
            "claim_boundary": {
                "candidate_only": True,
                "canonical_graph_write_allowed": False,
                "canonical_type_write_allowed": False,
                "raw_access_allowed": False,
            },
            "runs": [
                {
                    "run_id": "public_enterprise_lexical_baseline_v1",
                    "status": "completed",
                    "uses_neural_networks": False,
                    "metrics": {"f1": lexical_f1},
                    "pair_result_sample": [{"left_label": "private label text"}],
                },
                {
                    "run_id": "public_enterprise_bge_embedding_v1",
                    "status": "completed",
                    "uses_neural_networks": True,
                    "metrics": {"f1": bge_f1},
                },
            ],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
