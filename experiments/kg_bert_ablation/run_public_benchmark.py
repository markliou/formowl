#!/usr/bin/env python3
"""Run a larger public enterprise KG matching benchmark.

Raw public corpora are downloaded to an ignored local cache. The saved result is
only a JSON metrics artifact; it never writes canonical graph/type state.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import sys
import time
from typing import Any
from urllib.request import Request, urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import sha256_json  # noqa: E402

DEFAULT_CACHE_DIR = Path(".formowl/kg-benchmark-cache")
DEFAULT_OUTPUT = Path(
    "experiments/kg_bert_ablation/results/kg_public_enterprise_benchmark_latest.json"
)
MANIFEST_PATH = ROOT / "experiments/kg_bert_ablation/public_enterprise_benchmark_manifest.json"
CUAD_URL = "https://github.com/TheAtticusProject/cuad/raw/main/data.zip"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FIQA_SPLITS_URL = "https://datasets-server.huggingface.co/splits?dataset=BeIR/fiqa"
FIQA_BEIR_ZIP_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/fiqa.zip"
ENRON_URL = "https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz"
RVL_CDIP_URL = "https://adamharley.com/rvl-cdip/"
USER_AGENT = "formowl-public-kg-benchmark/0.1 contact@example.com"


@dataclass(frozen=True)
class BenchmarkPair:
    pair_id: str
    source_id: str
    source_family: str
    left_label: str
    right_label: str
    expected_same: bool
    core_supertype: str
    label_basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "source_id": self.source_id,
            "source_family": self.source_family,
            "left_label": self.left_label,
            "right_label": self.right_label,
            "expected_same": self.expected_same,
            "core_supertype": self.core_supertype,
            "label_basis": self.label_basis,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pair-limit", type=int, default=10_000)
    parser.add_argument("--lexical-threshold", type=float, default=0.70)
    parser.add_argument("--embedding-threshold", type=float, default=0.62)
    parser.add_argument("--embedding-model", default="BAAI/bge-large-en-v1.5")
    parser.add_argument("--embedding-batch-size", type=int, default=32)
    parser.add_argument("--mode", choices=("both", "lexical", "embedding"), default="both")
    parser.add_argument("--fail-if-embedding-unavailable", action="store_true")
    args = parser.parse_args(argv)

    if args.pair_limit < 1000:
        raise ValueError("pair-limit must be at least 1000 for this benchmark")

    started_at = _now()
    cache_dir = args.cache_dir if args.cache_dir.is_absolute() else ROOT / args.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest()
    source_locks = collect_source_locks(cache_dir)
    pairs = build_benchmark_pairs(cache_dir=cache_dir, pair_limit=args.pair_limit)
    runs: list[dict[str, Any]] = []
    if args.mode in {"both", "lexical"}:
        runs.append(run_lexical(pairs, threshold=args.lexical_threshold))
    if args.mode in {"both", "embedding"}:
        embedding_run = run_embedding(
            pairs,
            threshold=args.embedding_threshold,
            model_name=args.embedding_model,
            batch_size=args.embedding_batch_size,
        )
        runs.append(embedding_run)
        if args.fail_if_embedding_unavailable and embedding_run["status"] != "completed":
            report = build_report(
                started_at=started_at,
                manifest=manifest,
                source_locks=source_locks,
                pairs=pairs,
                runs=runs,
            )
            write_report(args.output, report)
            return 2

    report = build_report(
        started_at=started_at,
        manifest=manifest,
        source_locks=source_locks,
        pairs=pairs,
        runs=runs,
    )
    write_report(args.output, report)
    print(json.dumps(_compact_stdout(report), indent=2, sort_keys=True))
    return 0


def collect_source_locks(cache_dir: Path) -> dict[str, Any]:
    locks = {
        "cuad_contract_understanding_atticus_dataset": _download_lock(
            CUAD_URL,
            cache_dir / "cuad_data.zip",
        ),
        "sec_edgar_company_tickers": _download_lock(
            SEC_TICKERS_URL,
            cache_dir / "sec_company_tickers.json",
        ),
        "beir_fiqa_2018_splits": _probe_json_lock(FIQA_SPLITS_URL),
        "beir_fiqa_2018": _download_lock(
            FIQA_BEIR_ZIP_URL,
            cache_dir / "fiqa_beir.zip",
        ),
        "enron_email_dataset_cmu": _probe_head_lock(ENRON_URL),
        "rvl_cdip_document_images": _probe_head_lock(RVL_CDIP_URL),
    }
    return {
        "artifact_id": "formowl_kg_public_benchmark_source_locks_v1",
        "created_at": _now(),
        "locks": locks,
        "cache_policy": {
            "raw_cache_directory": str(cache_dir.relative_to(ROOT))
            if cache_dir.is_relative_to(ROOT)
            else "<external-cache>",
            "raw_cache_committed_to_git": False,
        },
    }


def build_benchmark_pairs(*, cache_dir: Path, pair_limit: int) -> list[BenchmarkPair]:
    cuad_pairs = _build_cuad_pairs(cache_dir / "cuad_data.zip")
    sec_pairs = _build_sec_pairs(cache_dir / "sec_company_tickers.json")
    fiqa_pairs = []
    fiqa_path = cache_dir / "fiqa_beir.zip"
    if fiqa_path.exists():
        fiqa_pairs = _build_fiqa_pairs(fiqa_path)
    pairs = _balanced_prefix(
        {
            "contract_document": cuad_pairs,
            "financial_report": sec_pairs,
            "financial_qa": fiqa_pairs,
        },
        pair_limit=pair_limit,
    )
    if len(pairs) < pair_limit:
        raise RuntimeError(f"only built {len(pairs)} pairs; expected {pair_limit}")
    return pairs


def run_lexical(pairs: list[BenchmarkPair], *, threshold: float) -> dict[str, Any]:
    started = time.perf_counter()
    rows = []
    for pair in pairs:
        score = _lexical_score(pair.left_label, pair.right_label)
        predicted_same = score >= threshold
        rows.append(
            _pair_result(pair, predicted_same=predicted_same, score=score, threshold=threshold)
        )
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {
        "run_id": "public_enterprise_lexical_baseline_v1",
        "status": "completed",
        "uses_neural_networks": False,
        "algorithm": "difflib_sequence_matcher_lexical_v1",
        "threshold": threshold,
        "latency_ms": round(latency_ms, 3),
        "pairs_per_second": _throughput(len(pairs), latency_ms),
        "metrics": _metrics(rows),
        "pair_result_sample": rows[:100],
    }


def run_embedding(
    pairs: list[BenchmarkPair],
    *,
    threshold: float,
    model_name: str,
    batch_size: int,
) -> dict[str, Any]:
    package_status = _sentence_transformer_status()
    torch_status = _torch_status()
    if not package_status["available"]:
        return {
            "run_id": "public_enterprise_bge_embedding_v1",
            "status": "blocked_missing_dependency",
            "uses_neural_networks": True,
            "algorithm": "sentence_transformer_cosine_similarity_with_core_type_gate_v1",
            "threshold": threshold,
            "model_name": model_name,
            "package_status": package_status,
            "torch_status": torch_status,
            "metrics": None,
            "pair_result_sample": [],
            "blocker": "sentence_transformers is not installed in the execution environment",
        }

    started = time.perf_counter()
    try:
        import importlib

        load_started = time.perf_counter()
        sentence_transformers = importlib.import_module("sentence_transformers")
        model = sentence_transformers.SentenceTransformer(model_name)
        model_device = str(getattr(model, "device", "unknown"))
        model_load_latency_ms = (time.perf_counter() - load_started) * 1000.0
        texts = [text for pair in pairs for text in (pair.left_label, pair.right_label)]
        embed_started = time.perf_counter()
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        embedding_latency_ms = (time.perf_counter() - embed_started) * 1000.0
    except Exception as exc:  # pragma: no cover - depends on optional runtime.
        return {
            "run_id": "public_enterprise_bge_embedding_v1",
            "status": "blocked_model_execution_error",
            "uses_neural_networks": True,
            "algorithm": "sentence_transformer_cosine_similarity_with_core_type_gate_v1",
            "threshold": threshold,
            "model_name": model_name,
            "package_status": package_status,
            "torch_status": torch_status,
            "metrics": None,
            "pair_result_sample": [],
            "blocker": f"{exc.__class__.__name__}: {exc}",
        }

    score_started = time.perf_counter()
    rows = []
    for index, pair in enumerate(pairs):
        left = _embedding_to_list(embeddings[index * 2])
        right = _embedding_to_list(embeddings[index * 2 + 1])
        score = _cosine(left, right)
        predicted_same = score >= threshold
        rows.append(
            _pair_result(pair, predicted_same=predicted_same, score=score, threshold=threshold)
        )
    scoring_latency_ms = (time.perf_counter() - score_started) * 1000.0
    latency_ms = (time.perf_counter() - started) * 1000.0
    return {
        "run_id": "public_enterprise_bge_embedding_v1",
        "status": "completed",
        "uses_neural_networks": True,
        "algorithm": "sentence_transformer_cosine_similarity_with_core_type_gate_v1",
        "threshold": threshold,
        "model_name": model_name,
        "package_status": package_status,
        "torch_status": torch_status,
        "model_device": model_device,
        "latency_ms": round(latency_ms, 3),
        "latency_breakdown_ms": {
            "model_load": round(model_load_latency_ms, 3),
            "embedding": round(embedding_latency_ms, 3),
            "scoring": round(scoring_latency_ms, 3),
        },
        "pairs_per_second": _throughput(len(pairs), latency_ms),
        "metrics": _metrics(rows),
        "pair_result_sample": rows[:100],
    }


def build_report(
    *,
    started_at: str,
    manifest: dict[str, Any],
    source_locks: dict[str, Any],
    pairs: list[BenchmarkPair],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    pair_payload = [pair.to_dict() for pair in pairs]
    return {
        "artifact_id": "formowl_kg_public_enterprise_benchmark_result_v1",
        "created_at": _now(),
        "started_at": started_at,
        "manifest": {
            "path": str(MANIFEST_PATH.relative_to(ROOT)),
            "artifact_id": manifest["artifact_id"],
            "manifest_sha256": sha256_json(manifest),
            "minimum_pair_count_for_model_selection": manifest[
                "minimum_pair_count_for_model_selection"
            ],
            "recommended_pair_count_for_stakeholder_claim": manifest[
                "recommended_pair_count_for_stakeholder_claim"
            ],
        },
        "dataset": {
            "dataset_id": "kg_public_enterprise_benchmark_run_v1",
            "pair_count": len(pairs),
            "positive_pair_count": sum(1 for pair in pairs if pair.expected_same),
            "negative_pair_count": sum(1 for pair in pairs if not pair.expected_same),
            "source_family_counts": _source_family_counts(pairs),
            "dataset_sha256": sha256_json(pair_payload),
            "pair_manifest_sample": pair_payload[:100],
            "pair_manifest_full_stored": False,
        },
        "source_locks": source_locks,
        "claim_boundary": {
            "candidate_only": True,
            "canonical_graph_write_allowed": False,
            "canonical_type_write_allowed": False,
            "raw_access_allowed": False,
            "production_quality_claim": False,
            "large_benchmark_executed": len(pairs)
            >= manifest["minimum_pair_count_for_model_selection"],
            "stakeholder_grade_claim": len(pairs)
            >= manifest["recommended_pair_count_for_stakeholder_claim"],
            "label_limitations_present": True,
        },
        "label_limitations": [
            "CUAD positives use expert answer spans as relevance evidence; negatives are cross-question hard negatives, not human-adjudicated nonmatches.",
            "SEC positives use issuer alias/title variants; negatives use different issuers and should not be treated as legal entity resolution gold beyond public ticker metadata.",
            "FiQA, Enron, and RVL-CDIP are source-locked or probed in this first run, but not used as labeled pairs unless a later qrel/OCR/mail-label builder is added.",
        ],
        "runs": runs,
        "comparison": _compare_runs(runs),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    output_path = path if path.is_absolute() else ROOT / path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_cuad_pairs(zip_path: Path) -> list[BenchmarkPair]:
    answer_rows: list[dict[str, str]] = []
    with ZipFile(zip_path) as archive:
        for name in ("train_separate_questions.json", "test.json"):
            with archive.open(name) as handle:
                payload = json.loads(handle.read().decode("utf-8"))
            for item in payload.get("data", []):
                title = str(item.get("title", ""))
                for paragraph in item.get("paragraphs", []):
                    for qa in paragraph.get("qas", []):
                        question = _compact_text(qa.get("question", ""))
                        answers = qa.get("answers") or []
                        if not question or not answers:
                            continue
                        answer_text = _compact_text(answers[0].get("text", ""))
                        if answer_text:
                            answer_rows.append(
                                {
                                    "title": title,
                                    "question": question,
                                    "answer": answer_text,
                                    "qa_id": str(qa.get("id", "")),
                                }
                            )
    pairs: list[BenchmarkPair] = []
    for index, row in enumerate(answer_rows):
        pairs.append(
            BenchmarkPair(
                pair_id=f"cuad_positive_{index:05d}",
                source_id="cuad_contract_understanding_atticus_dataset",
                source_family="contract_document",
                left_label=row["question"],
                right_label=row["answer"],
                expected_same=True,
                core_supertype="Clause",
                label_basis="cuad_expert_answer_span",
            )
        )
        negative = answer_rows[(index + 137) % len(answer_rows)]
        if negative["question"] == row["question"]:
            negative = answer_rows[(index + 271) % len(answer_rows)]
        pairs.append(
            BenchmarkPair(
                pair_id=f"cuad_negative_{index:05d}",
                source_id="cuad_contract_understanding_atticus_dataset",
                source_family="contract_document",
                left_label=row["question"],
                right_label=negative["answer"],
                expected_same=False,
                core_supertype="Clause",
                label_basis="cuad_cross_question_negative",
            )
        )
    return pairs


def _build_sec_pairs(path: Path) -> list[BenchmarkPair]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        {
            "cik": str(row["cik_str"]).zfill(10),
            "ticker": _compact_text(row["ticker"]),
            "title": _compact_text(row["title"]),
        }
        for _, row in sorted(payload.items(), key=lambda item: int(item[0]))
        if row.get("ticker") and row.get("title")
    ]
    pairs: list[BenchmarkPair] = []
    for index, row in enumerate(rows):
        alias = f"{row['title']} ticker {row['ticker']} CIK {row['cik']}"
        pairs.append(
            BenchmarkPair(
                pair_id=f"sec_positive_{index:05d}",
                source_id="sec_edgar_company_facts_and_submissions",
                source_family="financial_report",
                left_label=row["title"],
                right_label=alias,
                expected_same=True,
                core_supertype="Organization",
                label_basis="sec_same_cik_ticker_title",
            )
        )
        negative = rows[(index + 97) % len(rows)]
        pairs.append(
            BenchmarkPair(
                pair_id=f"sec_negative_{index:05d}",
                source_id="sec_edgar_company_facts_and_submissions",
                source_family="financial_report",
                left_label=row["title"],
                right_label=negative["title"],
                expected_same=False,
                core_supertype="Organization",
                label_basis="sec_different_cik_negative",
            )
        )
    return pairs


def _build_fiqa_pairs(zip_path: Path) -> list[BenchmarkPair]:
    with ZipFile(zip_path) as archive:
        corpus_name = _find_zip_member(archive, "corpus.jsonl")
        queries_name = _find_zip_member(archive, "queries.jsonl")
        qrel_names = sorted(
            name for name in archive.namelist() if "/qrels/" in name and name.endswith(".tsv")
        )
        corpus = _read_beir_jsonl(archive, corpus_name)
        queries = _read_beir_jsonl(archive, queries_name)
        qrels = _read_beir_qrels(archive, qrel_names)

    corpus_ids = sorted(corpus)
    if not corpus_ids:
        return []
    corpus_index = {corpus_id: index for index, corpus_id in enumerate(corpus_ids)}
    pairs: list[BenchmarkPair] = []
    pair_index = 0
    for query_id in sorted(qrels):
        query_text = queries.get(query_id)
        if not query_text:
            continue
        relevant_ids = sorted(qrels[query_id])
        for corpus_id in relevant_ids:
            document_text = corpus.get(corpus_id)
            if not document_text:
                continue
            pairs.append(
                BenchmarkPair(
                    pair_id=f"fiqa_positive_{pair_index:05d}",
                    source_id="beir_fiqa_2018",
                    source_family="financial_qa",
                    left_label=query_text,
                    right_label=document_text,
                    expected_same=True,
                    core_supertype="FinancialAnswer",
                    label_basis="fiqa_public_qrel_positive",
                )
            )
            negative_id = _choose_fiqa_negative(
                corpus_ids,
                corpus_index.get(corpus_id, pair_index % len(corpus_ids)),
                qrels[query_id],
                offset=997,
            )
            pairs.append(
                BenchmarkPair(
                    pair_id=f"fiqa_negative_{pair_index:05d}",
                    source_id="beir_fiqa_2018",
                    source_family="financial_qa",
                    left_label=query_text,
                    right_label=corpus[negative_id],
                    expected_same=False,
                    core_supertype="FinancialAnswer",
                    label_basis="fiqa_non_qrel_deterministic_negative",
                )
            )
            pair_index += 1
    return pairs


def _find_zip_member(archive: ZipFile, basename: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith("/" + basename)]
    if basename in archive.namelist():
        return basename
    if not matches:
        raise RuntimeError(f"missing {basename} in {archive.filename}")
    return sorted(matches)[0]


def _read_beir_jsonl(archive: ZipFile, member_name: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    with archive.open(member_name) as handle:
        for raw_line in handle:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            payload = json.loads(line)
            row_id = str(payload.get("_id") or payload.get("id") or "")
            if not row_id:
                continue
            title = _compact_text(payload.get("title", ""), max_chars=160)
            text = _compact_text(payload.get("text", ""), max_chars=512)
            combined = _compact_text(f"{title} {text}".strip(), max_chars=512)
            if combined:
                rows[row_id] = combined
    return rows


def _read_beir_qrels(archive: ZipFile, member_names: list[str]) -> dict[str, set[str]]:
    qrels: dict[str, set[str]] = {}
    for member_name in member_names:
        with archive.open(member_name) as handle:
            for raw_line in handle:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                parts = line.split("\t")
                if parts[0].lower() in {"query-id", "query_id", "qid"}:
                    continue
                if len(parts) < 3:
                    continue
                query_id, corpus_id, score_text = parts[0], parts[1], parts[2]
                try:
                    score = float(score_text)
                except ValueError:
                    continue
                if score <= 0:
                    continue
                qrels.setdefault(str(query_id), set()).add(str(corpus_id))
    return qrels


def _choose_fiqa_negative(
    corpus_ids: list[str],
    start_index: int,
    relevant_ids: set[str],
    *,
    offset: int,
) -> str:
    for step in range(len(corpus_ids)):
        candidate = corpus_ids[(start_index + offset + step) % len(corpus_ids)]
        if candidate not in relevant_ids:
            return candidate
    raise RuntimeError("failed to choose a FiQA negative")


def _balanced_prefix(
    pairs_by_family: dict[str, list[BenchmarkPair]],
    *,
    pair_limit: int,
) -> list[BenchmarkPair]:
    rng = random.Random(20260629)
    available = {family: list(pairs) for family, pairs in pairs_by_family.items() if pairs}
    for pairs in available.values():
        rng.shuffle(pairs)
    if "financial_qa" not in available:
        target_contract = int(pair_limit * 0.7)
        target_counts = {
            "contract_document": target_contract,
            "financial_report": pair_limit - target_contract,
        }
    else:
        target_counts = {
            "contract_document": int(pair_limit * 0.45),
            "financial_report": int(pair_limit * 0.30),
        }
        target_counts["financial_qa"] = pair_limit - sum(target_counts.values())
    selected: list[BenchmarkPair] = []
    for family, target_count in target_counts.items():
        selected.extend(available.get(family, [])[:target_count])
    if len(selected) < pair_limit:
        selected_ids = {pair.pair_id for pair in selected}
        remainder = [
            pair
            for pairs in available.values()
            for pair in pairs
            if pair.pair_id not in selected_ids
        ]
        rng.shuffle(remainder)
        selected.extend(remainder[: pair_limit - len(selected)])
    rng.shuffle(selected)
    return selected[:pair_limit]


def _pair_result(
    pair: BenchmarkPair,
    *,
    predicted_same: bool,
    score: float,
    threshold: float,
) -> dict[str, Any]:
    return {
        "pair_id": pair.pair_id,
        "source_family": pair.source_family,
        "expected_same": pair.expected_same,
        "predicted_same": predicted_same,
        "score": round(score, 6),
        "status": "same_as_candidate" if predicted_same else "below_threshold",
        "score_breakdown": {
            "score": round(score, 6),
            "threshold": threshold,
            "core_supertype": pair.core_supertype,
            "label_basis": pair.label_basis,
        },
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(1 for row in rows if row["expected_same"] and row["predicted_same"])
    fp = sum(1 for row in rows if not row["expected_same"] and row["predicted_same"])
    tn = sum(1 for row in rows if not row["expected_same"] and not row["predicted_same"])
    fn = sum(1 for row in rows if row["expected_same"] and not row["predicted_same"])
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(rows) if rows else 0.0
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


def _compare_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {run["run_id"]: run for run in runs}
    lexical = by_id.get("public_enterprise_lexical_baseline_v1")
    embedding = by_id.get("public_enterprise_bge_embedding_v1")
    if not lexical or not embedding or embedding.get("status") != "completed":
        return {
            "status": "incomplete",
            "reason": "embedding run did not complete",
        }
    lexical_metrics = lexical["metrics"]
    embedding_metrics = embedding["metrics"]
    return {
        "status": "completed",
        "accuracy_delta_embedding_minus_lexical": round(
            embedding_metrics["accuracy"] - lexical_metrics["accuracy"],
            6,
        ),
        "f1_delta_embedding_minus_lexical": round(
            embedding_metrics["f1"] - lexical_metrics["f1"],
            6,
        ),
        "recall_delta_embedding_minus_lexical": round(
            embedding_metrics["recall"] - lexical_metrics["recall"],
            6,
        ),
        "precision_delta_embedding_minus_lexical": round(
            embedding_metrics["precision"] - lexical_metrics["precision"],
            6,
        ),
    }


def _download_lock(url: str, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=120) as response:
            path.write_bytes(response.read())
    return {
        "url": url,
        "cached_filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
        "status": "cached",
    }


def _probe_json_lock(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        body = response.read()
    return {
        "url": url,
        "status": "probed_json",
        "bytes": len(body),
        "sha256": "sha256:" + sha256(body).hexdigest(),
        "json": json.loads(body.decode("utf-8")),
    }


def _probe_head_lock(url: str) -> dict[str, Any]:
    request = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            return {
                "url": url,
                "status": "head_ok",
                "content_length": response.headers.get("Content-Length"),
                "content_type": response.headers.get("Content-Type"),
            }
    except Exception as exc:
        return {
            "url": url,
            "status": "head_failed",
            "error": f"{exc.__class__.__name__}: {exc}",
        }


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _source_family_counts(pairs: list[BenchmarkPair]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair.source_family] = counts.get(pair.source_family, 0) + 1
    return dict(sorted(counts.items()))


def _compact_text(value: Any, *, max_chars: int = 512) -> str:
    text = " ".join(str(value).split())
    return text[:max_chars]


def _lexical_score(left: str, right: str) -> float:
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _sentence_transformer_status() -> dict[str, Any]:
    import importlib.util
    from importlib import metadata

    available = importlib.util.find_spec("sentence_transformers") is not None
    try:
        version = metadata.version("sentence-transformers") if available else None
    except metadata.PackageNotFoundError:
        version = None
    return {"available": available, "package_version": version}


def _torch_status() -> dict[str, Any]:
    import importlib
    import importlib.util

    if importlib.util.find_spec("torch") is None:
        return {
            "available": False,
            "package_version": None,
            "cuda_available": False,
            "cuda_version": None,
            "device_count": 0,
            "device_names": [],
        }
    torch = importlib.import_module("torch")
    cuda_available = bool(torch.cuda.is_available())
    device_count = int(torch.cuda.device_count()) if cuda_available else 0
    return {
        "available": True,
        "package_version": str(getattr(torch, "__version__", "unknown")),
        "cuda_available": cuda_available,
        "cuda_version": str(getattr(torch.version, "cuda", None)),
        "device_count": device_count,
        "device_names": [str(torch.cuda.get_device_name(index)) for index in range(device_count)],
    }


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
        "pair_count": report["dataset"]["pair_count"],
        "source_family_counts": report["dataset"]["source_family_counts"],
        "claim_boundary": report["claim_boundary"],
        "comparison": report["comparison"],
        "runs": [
            {
                "run_id": run["run_id"],
                "status": run["status"],
                "metrics": run["metrics"],
                "latency_ms": run.get("latency_ms"),
                "model_device": run.get("model_device"),
            }
            for run in report["runs"]
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
