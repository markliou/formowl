#!/usr/bin/env python3
"""Run the KG BERT vs non-BERT candidate matching ablation.

The BERT/SentenceTransformer side is optional because the default FormOwl dev
container does not require neural-network packages. Missing neural packages are
recorded as data, not hidden.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import importlib
from importlib import metadata
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import sha256_json  # noqa: E402
from formowl_graph import (  # noqa: E402
    LexicalFusionCandidateGenerator,
    ResolutionPolicy,
    ResolutionRecord,
)

DEFAULT_OUTPUT = Path("experiments/kg_bert_ablation/results/kg_bert_ablation_latest.json")
DEFAULT_BERT_MODEL = "sentence-transformers/bert-base-nli-mean-tokens"
CREATED_AT = "2026-06-29T00:00:00+00:00"


@dataclass(frozen=True)
class LabeledPair:
    pair_id: str
    left_label: str
    right_label: str
    expected_same: bool
    core_supertype: str = "Concept"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "left_label": self.left_label,
            "right_label": self.right_label,
            "expected_same": self.expected_same,
            "core_supertype": self.core_supertype,
        }


DATASET = (
    LabeledPair(
        "positive_customer_escalation",
        "customer escalation policy",
        "client complaint handling procedure",
        True,
    ),
    LabeledPair(
        "positive_refund_approval",
        "refund approval workflow",
        "reimbursement authorization process",
        True,
    ),
    LabeledPair(
        "positive_launch_date",
        "project launch date",
        "go-live schedule",
        True,
    ),
    LabeledPair(
        "positive_data_retention",
        "data retention rule",
        "information preservation policy",
        True,
    ),
    LabeledPair(
        "positive_vendor_onboarding",
        "vendor onboarding checklist",
        "supplier intake requirements",
        True,
    ),
    LabeledPair(
        "positive_security_review",
        "security review gate",
        "risk assessment checkpoint",
        True,
    ),
    LabeledPair(
        "positive_meeting_action",
        "meeting action item",
        "follow-up task from discussion",
        True,
    ),
    LabeledPair(
        "positive_invoice_delay",
        "invoice payment delay",
        "late accounts payable settlement",
        True,
    ),
    LabeledPair(
        "positive_contract_renewal",
        "contract renewal reminder",
        "agreement extension notice",
        True,
    ),
    LabeledPair(
        "positive_customer_org",
        "Acme Corp",
        "ACME Corporation",
        True,
        core_supertype="Organization",
    ),
    LabeledPair(
        "negative_customer_vs_security",
        "customer escalation policy",
        "security review gate",
        False,
    ),
    LabeledPair(
        "negative_refund_vs_launch",
        "refund approval workflow",
        "project launch date",
        False,
    ),
    LabeledPair(
        "negative_vendor_vs_invoice",
        "vendor onboarding checklist",
        "invoice payment delay",
        False,
    ),
    LabeledPair(
        "negative_contract_vs_action",
        "contract renewal reminder",
        "meeting action item",
        False,
    ),
    LabeledPair(
        "negative_data_vs_vendor",
        "data retention rule",
        "supplier intake requirements",
        False,
    ),
    LabeledPair(
        "negative_person_project_same_label",
        "Maya Chen",
        "Maya Chen",
        False,
        core_supertype="Person",
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run FormOwl KG BERT vs non-BERT candidate matching ablation."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--lexical-threshold", type=float, default=0.70)
    parser.add_argument("--bert-threshold", type=float, default=0.70)
    parser.add_argument("--bert-model", default=None)
    parser.add_argument(
        "--mode",
        choices=("both", "lexical", "bert"),
        default="both",
    )
    parser.add_argument("--fail-if-bert-unavailable", action="store_true")
    args = parser.parse_args(argv)

    started_at = _now()
    runs: list[dict[str, Any]] = []
    if args.mode in {"both", "lexical"}:
        runs.append(run_lexical_baseline(args.lexical_threshold))
    if args.mode in {"both", "bert"}:
        bert_run = run_sentence_transformer(
            threshold=args.bert_threshold,
            model_name=args.bert_model or _default_bert_model(),
        )
        runs.append(bert_run)
        if args.fail_if_bert_unavailable and bert_run["status"] != "completed":
            report = build_report(started_at=started_at, runs=runs)
            write_report(args.output, report)
            return 2

    report = build_report(started_at=started_at, runs=runs)
    write_report(args.output, report)
    print(json.dumps(_compact_stdout(report), indent=2, sort_keys=True))
    return 0


def run_lexical_baseline(threshold: float) -> dict[str, Any]:
    started = time.perf_counter()
    policy = ResolutionPolicy(
        policy_id="kg_bert_ablation_lexical_policy_v1",
        same_as_threshold=threshold,
        clerical_review_min=min(0.50, threshold),
    )
    generator = LexicalFusionCandidateGenerator(policy=policy)
    pair_results = []
    for pair in DATASET:
        candidates = generator.candidate_only_output(
            [_record(pair, side="left")],
            [_record(pair, side="right")],
            created_at=CREATED_AT,
        )
        candidate = candidates[0]
        predicted_same = candidate.status == "same_as_candidate"
        pair_results.append(
            {
                "pair_id": pair.pair_id,
                "expected_same": pair.expected_same,
                "predicted_same": predicted_same,
                "score": candidate.confidence,
                "status": candidate.status,
                "score_breakdown": dict(candidate.score_breakdown),
            }
        )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {
        "run_id": "non_bert_lexical_baseline_v1",
        "status": "completed",
        "uses_neural_networks": False,
        "algorithm": "rapidfuzz_compatible_lexical_v1",
        "threshold": threshold,
        "latency_ms": round(latency_ms, 3),
        "pairs_per_second": _throughput(len(DATASET), latency_ms),
        "metrics": _metrics(pair_results),
        "pair_results": pair_results,
    }


def run_sentence_transformer(*, threshold: float, model_name: str) -> dict[str, Any]:
    package_status = _sentence_transformer_status()
    if not package_status["available"]:
        return {
            "run_id": "bert_sentence_transformer_embedding_v1",
            "status": "blocked_missing_dependency",
            "uses_neural_networks": True,
            "algorithm": "sentence_transformer_cosine_similarity_v1",
            "threshold": threshold,
            "model_name": model_name,
            "package_status": package_status,
            "metrics": None,
            "pair_results": [],
            "blocker": "sentence_transformers is not installed in the execution environment",
        }

    started = time.perf_counter()
    try:
        sentence_transformers = importlib.import_module("sentence_transformers")
        model = sentence_transformers.SentenceTransformer(model_name)
        texts = [text for pair in DATASET for text in (pair.left_label, pair.right_label)]
        embeddings = model.encode(texts, normalize_embeddings=True)
    except Exception as exc:  # pragma: no cover - only exercised with optional package.
        return {
            "run_id": "bert_sentence_transformer_embedding_v1",
            "status": "blocked_model_execution_error",
            "uses_neural_networks": True,
            "algorithm": "sentence_transformer_cosine_similarity_v1",
            "threshold": threshold,
            "model_name": model_name,
            "package_status": package_status,
            "metrics": None,
            "pair_results": [],
            "blocker": f"{exc.__class__.__name__}: {exc}",
        }

    pair_results = []
    for index, pair in enumerate(DATASET):
        left_embedding = _embedding_to_list(embeddings[index * 2])
        right_embedding = _embedding_to_list(embeddings[index * 2 + 1])
        score = _cosine(left_embedding, right_embedding)
        predicted_same = score >= threshold
        pair_results.append(
            {
                "pair_id": pair.pair_id,
                "expected_same": pair.expected_same,
                "predicted_same": predicted_same,
                "score": round(score, 6),
                "status": "same_as_candidate" if predicted_same else "below_threshold",
                "score_breakdown": {
                    "embedding_cosine_similarity": round(score, 6),
                    "threshold": threshold,
                    "type_gate_passed": True,
                },
            }
        )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {
        "run_id": "bert_sentence_transformer_embedding_v1",
        "status": "completed",
        "uses_neural_networks": True,
        "algorithm": "sentence_transformer_cosine_similarity_v1",
        "threshold": threshold,
        "model_name": model_name,
        "package_status": package_status,
        "latency_ms": round(latency_ms, 3),
        "pairs_per_second": _throughput(len(DATASET), latency_ms),
        "metrics": _metrics(pair_results),
        "pair_results": pair_results,
    }


def build_report(*, started_at: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    dataset = [pair.to_dict() for pair in DATASET]
    return {
        "artifact_id": "formowl_kg_bert_ablation_result_v1",
        "created_at": _now(),
        "started_at": started_at,
        "dataset": {
            "dataset_id": "kg_matching_synonym_ablation_fixture_v1",
            "pair_count": len(DATASET),
            "positive_pair_count": sum(1 for pair in DATASET if pair.expected_same),
            "negative_pair_count": sum(1 for pair in DATASET if not pair.expected_same),
            "dataset_sha256": sha256_json(dataset),
            "pairs": dataset,
        },
        "claim_boundary": {
            "candidate_only": True,
            "canonical_graph_write_allowed": False,
            "canonical_type_write_allowed": False,
            "raw_access_allowed": False,
            "production_quality_claim": False,
            "stakeholder_evidence_artifact": True,
        },
        "environment": {
            "python_version": sys.version.split()[0],
            "sentence_transformers_available": _sentence_transformer_status()["available"],
            "default_model": _default_bert_model(),
        },
        "runs": runs,
        "comparison": compare_runs(runs),
    }


def compare_runs(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    by_id = {run["run_id"]: run for run in runs}
    lexical = by_id.get("non_bert_lexical_baseline_v1")
    bert = by_id.get("bert_sentence_transformer_embedding_v1")
    if not lexical or not bert or bert.get("status") != "completed":
        return {
            "status": "incomplete",
            "reason": "BERT/SentenceTransformer run did not complete in this environment",
        }
    lexical_metrics = lexical["metrics"]
    bert_metrics = bert["metrics"]
    return {
        "status": "completed",
        "f1_delta_bert_minus_non_bert": round(bert_metrics["f1"] - lexical_metrics["f1"], 6),
        "recall_delta_bert_minus_non_bert": round(
            bert_metrics["recall"] - lexical_metrics["recall"], 6
        ),
        "precision_delta_bert_minus_non_bert": round(
            bert_metrics["precision"] - lexical_metrics["precision"], 6
        ),
        "latency_ms_delta_bert_minus_non_bert": round(
            bert["latency_ms"] - lexical["latency_ms"], 3
        ),
        "throughput_ratio_bert_over_non_bert": round(
            bert["pairs_per_second"] / lexical["pairs_per_second"],
            6 if lexical["pairs_per_second"] else 0.0,
        ),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    output_path = path if path.is_absolute() else ROOT / path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record(pair: LabeledPair, *, side: str) -> ResolutionRecord:
    label = pair.left_label if side == "left" else pair.right_label
    core_supertype = pair.core_supertype
    if pair.pair_id == "negative_person_project_same_label" and side == "right":
        core_supertype = "Project"
    return ResolutionRecord.from_candidate_atom(
        record_id=f"{side}_{pair.pair_id}",
        label=label,
        atom_type=core_supertype,
        owner_user_id="user_ablation",
        scope_type="workspace",
        scope_id="kg_bert_ablation",
        source_candidate_atom_id=f"catom_{side}_{pair.pair_id}",
        source_observation_ids=(f"obs_{side}_{pair.pair_id}",),
    )


def _metrics(pair_results: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(1 for row in pair_results if row["expected_same"] and row["predicted_same"])
    fp = sum(1 for row in pair_results if not row["expected_same"] and row["predicted_same"])
    tn = sum(1 for row in pair_results if not row["expected_same"] and not row["predicted_same"])
    fn = sum(1 for row in pair_results if row["expected_same"] and not row["predicted_same"])
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(pair_results) if pair_results else 0.0
    return {
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "accuracy": round(accuracy, 6),
    }


def _sentence_transformer_status() -> dict[str, Any]:
    available = importlib.util.find_spec("sentence_transformers") is not None
    return {
        "available": available,
        "package_version": _package_version("sentence-transformers") if available else None,
    }


def _package_version(package_name: str) -> str | None:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def _default_bert_model() -> str:
    import os

    return os.environ.get("FORMOWL_BERT_ABLATION_MODEL", DEFAULT_BERT_MODEL)


def _embedding_to_list(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(component) for component in value]


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _throughput(pair_count: int, latency_ms: float) -> float:
    if latency_ms <= 0:
        return 0.0
    return round(pair_count / (latency_ms / 1000.0), 6)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _compact_stdout(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": report["artifact_id"],
        "output_dataset": report["dataset"]["dataset_id"],
        "comparison": report["comparison"],
        "runs": [
            {
                "run_id": run["run_id"],
                "status": run["status"],
                "uses_neural_networks": run["uses_neural_networks"],
                "metrics": run["metrics"],
                "latency_ms": run.get("latency_ms"),
            }
            for run in report["runs"]
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
