"""Packaged summary API for KG benchmark and ontology-ablation artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


BENCHMARK_ARTIFACTS: dict[str, str] = {
    "public_enterprise_10k": (
        "experiments/kg_bert_ablation/results/"
        "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host.json"
    ),
    "public_enterprise_50k": (
        "experiments/kg_bert_ablation/results/"
        "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host.json"
    ),
    "ontology_ablation": (
        "experiments/kg_bert_ablation/results/"
        "kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host.json"
    ),
}

BENCHMARK_CHARTS: dict[str, tuple[str, ...]] = {
    "public_enterprise_10k": (
        "experiments/kg_bert_ablation/results/charts/"
        "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_cu126_host_metrics.svg",
    ),
    "public_enterprise_50k": (
        "experiments/kg_bert_ablation/results/charts/"
        "kg_public_enterprise_benchmark_2026-06-29_bge_gpu_50k_cu126_host_metrics.svg",
    ),
    "ontology_ablation": (
        "experiments/kg_bert_ablation/results/charts/"
        "kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_metrics.svg",
        "experiments/kg_bert_ablation/results/charts/"
        "kg_ontology_ablation_2026-06-29_bge_gpu_cu126_host_ontology_stress.svg",
    ),
}

RUN_DISPLAY_NAMES: dict[str, str] = {
    "public_enterprise_lexical_baseline_v1": "Lexical baseline",
    "public_enterprise_bge_embedding_v1": "BGE large GPU",
    "ontology_ablation_lexical_only_v1": "Lexical only",
    "ontology_ablation_lexical_hard_gate_v1": "Lexical + ontology hard gate",
    "ontology_ablation_bge_only_v1": "BGE only",
    "ontology_ablation_bge_hard_gate_v1": "BGE + ontology hard gate",
    "ontology_ablation_bge_soft_score_v1": "BGE + ontology soft score",
}

METRIC_KEYS: tuple[str, ...] = (
    "accuracy",
    "precision",
    "recall",
    "f1",
    "true_positive",
    "false_positive",
    "true_negative",
    "false_negative",
    "false_positive_rate",
)


def build_benchmark_summary(*, repository_root: Path | str | None = None) -> dict[str, Any]:
    """Build a stable, redacted summary of committed KG benchmark artifacts.

    The returned object is intended for downstream package/API integration. It
    exposes benchmark-level metrics and chart paths, but intentionally omits
    per-pair samples and raw labels from the large JSON artifacts.
    """

    root = _repository_root(repository_root)
    artifact_summaries = [
        summarize_benchmark_artifact(artifact_name, repository_root=root)
        for artifact_name in BENCHMARK_ARTIFACTS
    ]
    return {
        "artifact_id": "formowl_kg_benchmark_summary_v1",
        "claim_boundary": {
            "candidate_only": True,
            "canonical_graph_write_allowed": False,
            "canonical_type_write_allowed": False,
            "raw_access_allowed": False,
            "production_quality_claim": False,
            "production_latency_claim": False,
            "completed_human_adjudication_claim": False,
        },
        "headline_results": _build_headline_results(artifact_summaries),
        "artifacts": artifact_summaries,
        "integration_boundary": {
            "system_agent_should_call": "formowl-kg-eval benchmarks",
            "system_agent_may_call_python_api": "formowl_kg_eval.build_benchmark_summary",
            "raw_pair_samples_exposed": False,
            "chart_paths_are_repo_relative": True,
        },
    }


def summarize_benchmark_artifact(
    artifact_name: str,
    *,
    repository_root: Path | str | None = None,
) -> dict[str, Any]:
    """Summarize one named KG benchmark artifact without exposing pair samples."""

    if artifact_name not in BENCHMARK_ARTIFACTS:
        allowed = ", ".join(sorted(BENCHMARK_ARTIFACTS))
        raise ValueError(
            f"unknown KG benchmark artifact {artifact_name!r}; expected one of: {allowed}"
        )

    root = _repository_root(repository_root)
    relative_path = BENCHMARK_ARTIFACTS[artifact_name]
    artifact = _load_json_object(root / relative_path)
    dataset = _dict_at(artifact, "dataset")
    runs = [_summarize_run(run) for run in artifact.get("runs", []) if isinstance(run, dict)]
    return {
        "artifact_name": artifact_name,
        "artifact_id": artifact.get("artifact_id"),
        "path": relative_path,
        "chart_paths": _existing_chart_paths(root, artifact_name),
        "created_at": artifact.get("created_at"),
        "dataset": _summarize_dataset(dataset),
        "comparison": artifact.get("comparison", {}),
        "claim_boundary": artifact.get("claim_boundary", {}),
        "runs": runs,
    }


def _build_headline_results(artifact_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    artifacts_by_name = {artifact["artifact_name"]: artifact for artifact in artifact_summaries}
    public_50k = artifacts_by_name.get("public_enterprise_50k", {})
    ontology = artifacts_by_name.get("ontology_ablation", {})
    ontology_runs = {run["run_id"]: run for run in ontology.get("runs", [])}
    bge_only = ontology_runs.get("ontology_ablation_bge_only_v1", {})
    bge_hard_gate = ontology_runs.get("ontology_ablation_bge_hard_gate_v1", {})
    return {
        "public_enterprise_50k_bge_vs_lexical": {
            "pair_count": public_50k.get("dataset", {}).get("pair_count"),
            "accuracy_delta": public_50k.get("comparison", {}).get(
                "accuracy_delta_embedding_minus_lexical"
            ),
            "f1_delta": public_50k.get("comparison", {}).get("f1_delta_embedding_minus_lexical"),
            "precision_delta": public_50k.get("comparison", {}).get(
                "precision_delta_embedding_minus_lexical"
            ),
            "recall_delta": public_50k.get("comparison", {}).get(
                "recall_delta_embedding_minus_lexical"
            ),
        },
        "ontology_guided_bge_vs_bge_only": {
            "pair_count": ontology.get("dataset", {}).get("pair_count"),
            "f1_delta": ontology.get("comparison", {})
            .get("comparisons", {})
            .get("bge_hard_gate_minus_bge_only", {})
            .get("f1_delta"),
            "precision_delta": ontology.get("comparison", {})
            .get("comparisons", {})
            .get("bge_hard_gate_minus_bge_only", {})
            .get("precision_delta"),
            "stress_false_positive_before": bge_only.get("stress_metrics", {}).get(
                "false_positive"
            ),
            "stress_false_positive_after": bge_hard_gate.get("stress_metrics", {}).get(
                "false_positive"
            ),
        },
    }


def _summarize_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    pair_count = dataset.get("pair_count")
    negative_pair_count = dataset.get("negative_pair_count")
    positive_pair_count = None
    if isinstance(pair_count, int) and isinstance(negative_pair_count, int):
        positive_pair_count = pair_count - negative_pair_count
    return {
        "dataset_id": dataset.get("dataset_id"),
        "dataset_sha256": dataset.get("dataset_sha256"),
        "pair_count": pair_count,
        "positive_pair_count": positive_pair_count,
        "negative_pair_count": negative_pair_count,
        "cross_type_hard_negative_count": dataset.get("cross_type_hard_negative_count"),
        "pair_manifest_full_stored": dataset.get("pair_manifest_full_stored"),
    }


def _summarize_run(run: dict[str, Any]) -> dict[str, Any]:
    run_id = run.get("run_id")
    return {
        "run_id": run_id,
        "display_name": RUN_DISPLAY_NAMES.get(str(run_id), str(run_id)),
        "status": run.get("status"),
        "algorithm": run.get("algorithm"),
        "uses_neural_networks": run.get("uses_neural_networks"),
        "threshold": run.get("threshold"),
        "ontology_mode": run.get("ontology_mode"),
        "model_name": run.get("model_name"),
        "model_device": run.get("model_device"),
        "latency_ms": run.get("latency_ms"),
        "pairs_per_second": run.get("pairs_per_second"),
        "metrics": _metrics_subset(_dict_at(run, "metrics")),
        "stress_metrics": _metrics_subset(_dict_at(run, "stress_metrics")),
    }


def _metrics_subset(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: metrics[key] for key in METRIC_KEYS if key in metrics}


def _existing_chart_paths(root: Path, artifact_name: str) -> list[str]:
    paths = []
    for relative_path in BENCHMARK_CHARTS.get(artifact_name, ()):
        if (root / relative_path).is_file():
            paths.append(relative_path)
    return paths


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"KG benchmark artifact not found: {path}")
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"KG benchmark artifact is not a JSON object: {path}")
    return payload


def _repository_root(repository_root: Path | str | None) -> Path:
    if repository_root:
        return Path(repository_root).expanduser().resolve()
    configured = os.environ.get("FORMOWL_REPOSITORY_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _dict_at(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        return {}
    return value
