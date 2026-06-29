#!/usr/bin/env python3
"""Run ontology-gate ablations for KG candidate matching.

The benchmark is candidate-only. It compares lexical and embedding similarity
with no ontology signal, a hard ontology type gate, and a soft ontology score
adjustment. It intentionally includes cross-type hard negatives so ontology
effects are measurable instead of being inferred from ordinary same-type pairs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
import importlib
import json
from pathlib import Path
import random
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON_ROOT = ROOT / "python"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import sha256_json  # noqa: E402

import run_public_benchmark as public_benchmark  # noqa: E402

DEFAULT_CACHE_DIR = Path(".formowl/kg-benchmark-cache")
DEFAULT_OUTPUT = Path("experiments/kg_bert_ablation/results/kg_ontology_ablation_latest.json")
DEFAULT_MODEL = "BAAI/bge-large-en-v1.5"

CORE_PARENT = {
    "Clause": "InformationObject",
    "MetadataField": "InformationObject",
    "FinancialAnswer": "InformationObject",
    "Organization": "Entity",
    "Person": "Entity",
    "Product": "Entity",
    "Project": "Entity",
}


@dataclass(frozen=True)
class OntologyPair:
    pair_id: str
    source_family: str
    left_label: str
    right_label: str
    expected_same: bool
    left_core_supertype: str
    right_core_supertype: str
    label_basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "source_family": self.source_family,
            "left_label": self.left_label,
            "right_label": self.right_label,
            "expected_same": self.expected_same,
            "left_core_supertype": self.left_core_supertype,
            "right_core_supertype": self.right_core_supertype,
            "label_basis": self.label_basis,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-pair-limit", type=int, default=10_000)
    parser.add_argument("--hard-negative-limit", type=int, default=10_000)
    parser.add_argument("--lexical-threshold", type=float, default=0.70)
    parser.add_argument("--embedding-threshold", type=float, default=0.62)
    parser.add_argument("--embedding-model", default=DEFAULT_MODEL)
    parser.add_argument("--embedding-batch-size", type=int, default=8)
    parser.add_argument("--soft-sibling-penalty", type=float, default=0.60)
    parser.add_argument("--soft-incompatible-penalty", type=float, default=0.45)
    parser.add_argument("--fail-if-embedding-unavailable", action="store_true")
    args = parser.parse_args(argv)

    started_at = _now()
    cache_dir = args.cache_dir if args.cache_dir.is_absolute() else ROOT / args.cache_dir
    pairs = build_ontology_pairs(
        cache_dir=cache_dir,
        base_pair_limit=args.base_pair_limit,
        hard_negative_limit=args.hard_negative_limit,
    )

    runs: list[dict[str, Any]] = [
        run_scored_ablation(
            pairs,
            run_id="ontology_ablation_lexical_only_v1",
            algorithm="difflib_sequence_matcher",
            threshold=args.lexical_threshold,
            score_kind="lexical",
            ontology_mode="none",
        ),
        run_scored_ablation(
            pairs,
            run_id="ontology_ablation_lexical_hard_gate_v1",
            algorithm="difflib_sequence_matcher_with_hard_core_type_gate",
            threshold=args.lexical_threshold,
            score_kind="lexical",
            ontology_mode="hard_gate",
        ),
    ]

    embedding_run = run_embedding_ablation(
        pairs,
        model_name=args.embedding_model,
        threshold=args.embedding_threshold,
        batch_size=args.embedding_batch_size,
        soft_sibling_penalty=args.soft_sibling_penalty,
        soft_incompatible_penalty=args.soft_incompatible_penalty,
    )
    runs.extend(embedding_run["runs"])
    if args.fail_if_embedding_unavailable and embedding_run["status"] != "completed":
        report = build_report(
            started_at=started_at,
            pairs=pairs,
            runs=runs,
            embedding_status=embedding_run,
        )
        write_report(args.output, report)
        return 2

    report = build_report(
        started_at=started_at,
        pairs=pairs,
        runs=runs,
        embedding_status=embedding_run,
    )
    write_report(args.output, report)
    print(json.dumps(_compact_stdout(report), indent=2, sort_keys=True))
    return 0


def build_ontology_pairs(
    *,
    cache_dir: Path,
    base_pair_limit: int,
    hard_negative_limit: int,
) -> list[OntologyPair]:
    base_pairs = public_benchmark.build_benchmark_pairs(
        cache_dir=cache_dir,
        pair_limit=base_pair_limit,
    )
    pairs = [
        OntologyPair(
            pair_id=f"base_{pair.pair_id}",
            source_family=pair.source_family,
            left_label=pair.left_label,
            right_label=pair.right_label,
            expected_same=pair.expected_same,
            left_core_supertype=pair.core_supertype,
            right_core_supertype=pair.core_supertype,
            label_basis=pair.label_basis,
        )
        for pair in base_pairs
    ]
    pairs.extend(_build_cross_type_hard_negatives(cache_dir, hard_negative_limit))
    rng = random.Random(20260629)
    rng.shuffle(pairs)
    return pairs


def run_scored_ablation(
    pairs: list[OntologyPair],
    *,
    run_id: str,
    algorithm: str,
    threshold: float,
    score_kind: str,
    ontology_mode: str,
    precomputed_scores: dict[str, float] | None = None,
    soft_sibling_penalty: float = 0.60,
    soft_incompatible_penalty: float = 0.45,
) -> dict[str, Any]:
    started = time.perf_counter()
    rows = []
    for pair in pairs:
        score = (
            precomputed_scores[pair.pair_id]
            if precomputed_scores is not None
            else _lexical_score(pair.left_label, pair.right_label)
        )
        adjusted_score, ontology_action = _apply_ontology(
            score,
            pair,
            ontology_mode=ontology_mode,
            soft_sibling_penalty=soft_sibling_penalty,
            soft_incompatible_penalty=soft_incompatible_penalty,
        )
        predicted_same = adjusted_score >= threshold
        rows.append(
            _pair_result(
                pair,
                predicted_same=predicted_same,
                score=score,
                adjusted_score=adjusted_score,
                threshold=threshold,
                ontology_mode=ontology_mode,
                ontology_action=ontology_action,
            )
        )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {
        "run_id": run_id,
        "status": "completed",
        "uses_neural_networks": score_kind == "embedding",
        "algorithm": algorithm,
        "threshold": threshold,
        "score_kind": score_kind,
        "ontology_mode": ontology_mode,
        "latency_ms": round(latency_ms, 3),
        "pairs_per_second": _throughput(len(pairs), latency_ms),
        "metrics": _metrics(rows),
        "stress_metrics": _metrics(
            [row for row in rows if row["label_basis"].startswith("cross_type")]
        ),
        "pair_result_sample": rows[:100],
    }


def run_embedding_ablation(
    pairs: list[OntologyPair],
    *,
    model_name: str,
    threshold: float,
    batch_size: int,
    soft_sibling_penalty: float,
    soft_incompatible_penalty: float,
) -> dict[str, Any]:
    package_status = public_benchmark._sentence_transformer_status()
    torch_status = public_benchmark._torch_status()
    if not package_status["available"]:
        blocked = {
            "run_id": "ontology_ablation_bge_blocked_v1",
            "status": "blocked_missing_dependency",
            "uses_neural_networks": True,
            "algorithm": "sentence_transformer_cosine_similarity",
            "threshold": threshold,
            "model_name": model_name,
            "package_status": package_status,
            "torch_status": torch_status,
            "metrics": None,
            "pair_result_sample": [],
            "blocker": "sentence_transformers is not installed in the execution environment",
        }
        return {"status": "blocked_missing_dependency", "runs": [blocked]}

    started = time.perf_counter()
    try:
        load_started = time.perf_counter()
        sentence_transformers = importlib.import_module("sentence_transformers")
        model = sentence_transformers.SentenceTransformer(model_name)
        model_device = str(getattr(model, "device", "unknown"))
        model_load_latency_ms = (time.perf_counter() - load_started) * 1000.0
        texts = sorted({label for pair in pairs for label in (pair.left_label, pair.right_label)})
        embed_started = time.perf_counter()
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        embedding_latency_ms = (time.perf_counter() - embed_started) * 1000.0
    except Exception as exc:  # pragma: no cover - optional runtime dependent.
        blocked = {
            "run_id": "ontology_ablation_bge_blocked_v1",
            "status": "blocked_model_execution_error",
            "uses_neural_networks": True,
            "algorithm": "sentence_transformer_cosine_similarity",
            "threshold": threshold,
            "model_name": model_name,
            "package_status": package_status,
            "torch_status": torch_status,
            "metrics": None,
            "pair_result_sample": [],
            "blocker": f"{exc.__class__.__name__}: {exc}",
        }
        return {"status": "blocked_model_execution_error", "runs": [blocked]}

    vector_by_text = {
        text: public_benchmark._embedding_to_list(embedding)
        for text, embedding in zip(texts, embeddings, strict=True)
    }
    score_started = time.perf_counter()
    scores = {
        pair.pair_id: public_benchmark._cosine(
            vector_by_text[pair.left_label],
            vector_by_text[pair.right_label],
        )
        for pair in pairs
    }
    scoring_latency_ms = (time.perf_counter() - score_started) * 1000.0
    total_latency_ms = (time.perf_counter() - started) * 1000.0
    common = {
        "model_name": model_name,
        "package_status": package_status,
        "torch_status": torch_status,
        "model_device": model_device,
        "embedding_unique_text_count": len(texts),
        "embedding_latency_breakdown_ms": {
            "model_load": round(model_load_latency_ms, 3),
            "embedding": round(embedding_latency_ms, 3),
            "pair_scoring": round(scoring_latency_ms, 3),
            "total_embedding_phase": round(total_latency_ms, 3),
        },
    }
    runs = []
    for run_id, algorithm, ontology_mode in (
        (
            "ontology_ablation_bge_only_v1",
            "sentence_transformer_cosine_similarity",
            "none",
        ),
        (
            "ontology_ablation_bge_hard_gate_v1",
            "sentence_transformer_cosine_similarity_with_hard_core_type_gate",
            "hard_gate",
        ),
        (
            "ontology_ablation_bge_soft_score_v1",
            "sentence_transformer_cosine_similarity_with_soft_core_type_score",
            "soft_score",
        ),
    ):
        run = run_scored_ablation(
            pairs,
            run_id=run_id,
            algorithm=algorithm,
            threshold=threshold,
            score_kind="embedding",
            ontology_mode=ontology_mode,
            precomputed_scores=scores,
            soft_sibling_penalty=soft_sibling_penalty,
            soft_incompatible_penalty=soft_incompatible_penalty,
        )
        run.update(common)
        runs.append(run)
    return {"status": "completed", "runs": runs}


def build_report(
    *,
    started_at: str,
    pairs: list[OntologyPair],
    runs: list[dict[str, Any]],
    embedding_status: dict[str, Any],
) -> dict[str, Any]:
    pair_payload = [pair.to_dict() for pair in pairs]
    return {
        "artifact_id": "formowl_kg_ontology_ablation_result_v1",
        "created_at": _now(),
        "started_at": started_at,
        "dataset": {
            "dataset_id": "kg_ontology_ablation_stress_v1",
            "pair_count": len(pairs),
            "positive_pair_count": sum(1 for pair in pairs if pair.expected_same),
            "negative_pair_count": sum(1 for pair in pairs if not pair.expected_same),
            "source_family_counts": _source_family_counts(pairs),
            "cross_type_hard_negative_count": sum(
                1 for pair in pairs if pair.label_basis.startswith("cross_type")
            ),
            "dataset_sha256": sha256_json(pair_payload),
            "pair_manifest_sample": pair_payload[:100],
            "pair_manifest_full_stored": False,
        },
        "claim_boundary": {
            "candidate_only": True,
            "ontology_ablation": True,
            "canonical_graph_write_allowed": False,
            "canonical_type_write_allowed": False,
            "raw_access_allowed": False,
            "production_quality_claim": False,
            "stakeholder_grade_claim": False,
            "cross_type_hard_negatives_are_stress_cases": True,
        },
        "ontology_policy": {
            "policy_id": "closed_core_supertype_gate_ablation_v1",
            "core_parent": CORE_PARENT,
            "hard_gate": "same core supertype required",
            "soft_score": "same type unchanged; same parent/incompatible types receive score penalties",
        },
        "label_limitations": [
            "Base pairs reuse the public benchmark's deterministic CUAD, SEC, and optional FiQA labels.",
            "Cross-type hard negatives are ontology stress cases, not naturally sampled human-adjudicated enterprise labels.",
            "This artifact measures candidate-ranking behavior only and does not promote ontology or canonical graph state.",
        ],
        "embedding_status": {
            key: value for key, value in embedding_status.items() if key != "runs"
        },
        "runs": runs,
        "comparison": _compare_ablation_runs(runs),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    output_path = path if path.is_absolute() else ROOT / path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_cross_type_hard_negatives(cache_dir: Path, limit: int) -> list[OntologyPair]:
    rows: list[OntologyPair] = []
    sec_path = cache_dir / "sec_company_tickers.json"
    if sec_path.exists():
        for index, pair in enumerate(public_benchmark._build_sec_pairs(sec_path)):
            if not pair.expected_same:
                continue
            rows.append(
                OntologyPair(
                    pair_id=f"cross_type_sec_org_product_{index:05d}",
                    source_family="ontology_stress",
                    left_label=pair.left_label,
                    right_label=pair.left_label,
                    expected_same=False,
                    left_core_supertype="Organization",
                    right_core_supertype="Product" if index % 2 else "Project",
                    label_basis="cross_type_same_surface_hard_negative",
                )
            )
            if len(rows) >= limit:
                return rows
    cuad_path = cache_dir / "cuad_data.zip"
    if cuad_path.exists():
        for index, pair in enumerate(public_benchmark._build_cuad_pairs(cuad_path)):
            if not pair.expected_same:
                continue
            rows.append(
                OntologyPair(
                    pair_id=f"cross_type_cuad_clause_field_{index:05d}",
                    source_family="ontology_stress",
                    left_label=pair.left_label,
                    right_label=pair.left_label,
                    expected_same=False,
                    left_core_supertype="Clause",
                    right_core_supertype="MetadataField",
                    label_basis="cross_type_same_surface_hard_negative",
                )
            )
            if len(rows) >= limit:
                return rows
    examples = (
        ("Maya Chen", "Person", "Project"),
        ("Mercury", "Organization", "Product"),
        ("Effective Date", "Clause", "MetadataField"),
        ("Apple", "Organization", "Product"),
    )
    while len(rows) < limit:
        text, left_type, right_type = examples[len(rows) % len(examples)]
        index = len(rows)
        rows.append(
            OntologyPair(
                pair_id=f"cross_type_synthetic_{index:05d}",
                source_family="ontology_stress",
                left_label=text,
                right_label=text,
                expected_same=False,
                left_core_supertype=left_type,
                right_core_supertype=right_type,
                label_basis="cross_type_same_surface_hard_negative",
            )
        )
    return rows


def _apply_ontology(
    score: float,
    pair: OntologyPair,
    *,
    ontology_mode: str,
    soft_sibling_penalty: float,
    soft_incompatible_penalty: float,
) -> tuple[float, str]:
    if ontology_mode == "none":
        return score, "not_applied"
    if _same_core_type(pair):
        return score, "same_core_type"
    if ontology_mode == "hard_gate":
        return 0.0, "blocked_type_mismatch"
    if ontology_mode == "soft_score":
        if _same_parent_type(pair):
            return score * soft_sibling_penalty, "penalized_same_parent_type_mismatch"
        return score * soft_incompatible_penalty, "penalized_incompatible_type_mismatch"
    raise ValueError(f"unknown ontology mode: {ontology_mode}")


def _same_core_type(pair: OntologyPair) -> bool:
    return pair.left_core_supertype == pair.right_core_supertype


def _same_parent_type(pair: OntologyPair) -> bool:
    return CORE_PARENT.get(pair.left_core_supertype) == CORE_PARENT.get(pair.right_core_supertype)


def _pair_result(
    pair: OntologyPair,
    *,
    predicted_same: bool,
    score: float,
    adjusted_score: float,
    threshold: float,
    ontology_mode: str,
    ontology_action: str,
) -> dict[str, Any]:
    return {
        "pair_id": pair.pair_id,
        "source_family": pair.source_family,
        "expected_same": pair.expected_same,
        "predicted_same": predicted_same,
        "score": round(score, 6),
        "adjusted_score": round(adjusted_score, 6),
        "status": "same_as_candidate" if predicted_same else "below_threshold",
        "label_basis": pair.label_basis,
        "score_breakdown": {
            "score": round(score, 6),
            "adjusted_score": round(adjusted_score, 6),
            "threshold": threshold,
            "ontology_mode": ontology_mode,
            "ontology_action": ontology_action,
            "left_core_supertype": pair.left_core_supertype,
            "right_core_supertype": pair.right_core_supertype,
        },
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "true_positive": 0,
            "false_positive": 0,
            "true_negative": 0,
            "false_negative": 0,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "accuracy": 0.0,
        }
    tp = sum(1 for row in rows if row["expected_same"] and row["predicted_same"])
    fp = sum(1 for row in rows if not row["expected_same"] and row["predicted_same"])
    tn = sum(1 for row in rows if not row["expected_same"] and not row["predicted_same"])
    fn = sum(1 for row in rows if row["expected_same"] and not row["predicted_same"])
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(rows)
    false_positive_rate = fp / (fp + tn) if fp + tn else 0.0
    return {
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "accuracy": round(accuracy, 6),
        "false_positive_rate": round(false_positive_rate, 6),
    }


def _compare_ablation_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {run["run_id"]: run for run in runs if run.get("status") == "completed"}
    comparisons = {}
    pairs = (
        (
            "lexical_hard_gate_minus_lexical_only",
            "ontology_ablation_lexical_hard_gate_v1",
            "ontology_ablation_lexical_only_v1",
        ),
        (
            "bge_hard_gate_minus_bge_only",
            "ontology_ablation_bge_hard_gate_v1",
            "ontology_ablation_bge_only_v1",
        ),
        (
            "bge_soft_score_minus_bge_only",
            "ontology_ablation_bge_soft_score_v1",
            "ontology_ablation_bge_only_v1",
        ),
    )
    for comparison_id, left_id, right_id in pairs:
        if left_id not in by_id or right_id not in by_id:
            continue
        left = by_id[left_id]["metrics"]
        right = by_id[right_id]["metrics"]
        comparisons[comparison_id] = {
            "accuracy_delta": round(left["accuracy"] - right["accuracy"], 6),
            "precision_delta": round(left["precision"] - right["precision"], 6),
            "recall_delta": round(left["recall"] - right["recall"], 6),
            "f1_delta": round(left["f1"] - right["f1"], 6),
            "false_positive_delta": left["false_positive"] - right["false_positive"],
        }
    return {"status": "completed" if comparisons else "incomplete", "comparisons": comparisons}


def _source_family_counts(pairs: list[OntologyPair]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair.source_family] = counts.get(pair.source_family, 0) + 1
    return dict(sorted(counts.items()))


def _lexical_score(left: str, right: str) -> float:
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _throughput(pair_count: int, latency_ms: float) -> float:
    if latency_ms <= 0:
        return 0.0
    return round(pair_count / (latency_ms / 1000.0), 6)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _compact_stdout(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": report["artifact_id"],
        "pair_count": report["dataset"]["pair_count"],
        "source_family_counts": report["dataset"]["source_family_counts"],
        "comparison": report["comparison"],
        "runs": [
            {
                "run_id": run["run_id"],
                "status": run["status"],
                "metrics": run["metrics"],
                "stress_metrics": run.get("stress_metrics"),
                "model_device": run.get("model_device"),
            }
            for run in report["runs"]
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
