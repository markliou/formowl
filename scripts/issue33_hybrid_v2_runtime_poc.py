#!/usr/bin/env python3
"""Run the bounded Issue #33 Hybrid v2 Observation-only runtime diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    ContractValidationError,
    Observation,
    sha256_json,
)
from formowl_core.methodology_authority import (  # noqa: E402
    check_methodology_authority,
)
from formowl_core.tokenization import (  # noqa: E402
    MailCandidateAdmissionTokenizerProfile,
    build_ascii_identifier_regex_tokenizer_profile,
    build_frozen_jieba_sentencepiece_tokenizer_profile,
)
from formowl_graph.ontology import (  # noqa: E402
    core_supertypes_compatible,
    soft_core_supertypes_compatible,
)
from formowl_mail._guards import assert_public_payload_safe  # noqa: E402
from formowl_mail.bundle import build_mail_evidence_bundle  # noqa: E402
from formowl_mail.query import (  # noqa: E402
    ExistingObservationIndexBuildManifest,
    MailEvidenceQueryGateway,
    build_existing_observation_snippet_index,
)

DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "issue33_hybrid_v2_poc.json"
_REPORT_ARTIFACT_ID = "formowl_issue33_hybrid_v2_runtime_diagnostic_v1"
_CALIBRATION_CORPUS = (
    "交期 產地 供應商 承諾 付款 條件 採購 取消",
    "目前交期與最新交貨日期",
    "料號與原產地資料",
    "request commitment decision blocker deadline dependency",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=5)
    args = parser.parse_args(argv)
    if args.replicates < 3:
        raise SystemExit("--replicates must be at least 3")

    report = run_diagnostic(
        fixture_path=args.fixture,
        replicates=args.replicates,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def run_diagnostic(
    *,
    fixture_path: Path,
    replicates: int,
) -> dict[str, Any]:
    fixture = _load_fixture(fixture_path)
    observations = [Observation.from_dict(item) for item in fixture["observations"]]
    bundle = build_mail_evidence_bundle(
        observations,
        workspace_id=fixture["workspace_id"],
        owner_user_id=fixture["owner_user_id"],
        source_asset_id=fixture["source_asset_id"],
        archive_sha256=fixture["archive_sha256"],
        upload_session_id=fixture["upload_session_id"],
        parser_name="existing_observation_bridge_no_parser",
        parser_version="issue33_poc_v1",
        created_at=fixture["created_at"],
        started_at=fixture["created_at"],
        completed_at=fixture["created_at"],
    )
    baseline_profile = build_ascii_identifier_regex_tokenizer_profile()
    with tempfile.TemporaryDirectory(prefix="formowl-issue33-sp-") as temp_dir:
        model_path, model_sha256 = _train_safe_calibration_model(Path(temp_dir))
        target_profile = build_frozen_jieba_sentencepiece_tokenizer_profile(
            model_path=model_path,
            model_sha256=model_sha256,
        )
        baseline = _run_arm(
            arm_id="regex_baseline",
            profile=baseline_profile,
            observations=observations,
            bundle=bundle,
            fixture=fixture,
            replicates=replicates,
            ontology_mode="off",
        )
        before = _run_arm(
            arm_id="frozen_jieba_sentencepiece_legacy_hard_gate",
            profile=target_profile,
            observations=observations,
            bundle=bundle,
            fixture=fixture,
            replicates=replicates,
            ontology_mode="legacy_hard_gate",
        )
        after = _run_arm(
            arm_id="frozen_jieba_sentencepiece_capped_additive_rerank",
            profile=target_profile,
            observations=observations,
            bundle=bundle,
            fixture=fixture,
            replicates=replicates,
            ontology_mode="capped_additive_rerank",
        )

    authority = check_methodology_authority(repository_root=ROOT).to_safe_dict()
    if not authority["authority_valid"] or authority["methodology_ready"]:
        raise ContractValidationError("diagnostic requires valid blocked methodology authority")
    improvement_observed = (
        after["inspection_summary"]["required_evidence_resolved_count"]
        > before["inspection_summary"]["required_evidence_resolved_count"]
        and after["inspection_summary"]["ontology_hard_gate_false_reject_count"]
        < before["inspection_summary"]["ontology_hard_gate_false_reject_count"]
        and after["inspection_summary"]["no_answer_false_match_count"]
        <= before["inspection_summary"]["no_answer_false_match_count"]
        and after["inspection_summary"]["final_answer_generated_count"]
        > before["inspection_summary"]["final_answer_generated_count"]
    )
    conclusion = (
        "diagnostic_root_cause_improvement_observed"
        if improvement_observed
        else "diagnostic_root_cause_improvement_not_established"
    )
    report = {
        "artifact_id": _REPORT_ARTIFACT_ID,
        "schema_version": 1,
        "issue": 33,
        "partition": "development",
        "source_kind": "source_free_safe_existing_observation_fixture",
        "fixture_fingerprint": sha256_json(fixture),
        "case_manifest_fingerprint": sha256_json(fixture["cases"]),
        "claim_state": "query_evidence_extractive_answer_diagnostic_only",
        "final_answer_generated": bool(
            after["inspection_summary"]["final_answer_generated_count"]
        ),
        "real_query_to_evidence_runtime_path_executed": True,
        "real_source_methodology_evidence": False,
        "methodology_ready": False,
        "authority": {
            "authority_state_fingerprint": authority["authority_state_fingerprint"],
            "execution_fingerprint": authority["execution_fingerprint"],
            "status": authority["status"],
            "current_candidate_admission_profile_id": authority["current_tokenizer_id"],
            "target_candidate_admission_profile_id": authority["target_tokenizer_id"],
            "blocking_gate_ids": authority["blocking_gate_ids"],
        },
        "source_revision": _source_revision(),
        "source_tree_dirty": bool(_source_tree_dirty()),
        "evaluator_source_fingerprint": _sha256_file(Path(__file__)),
        "candidate_admission_baseline": baseline,
        "before": before,
        "after": after,
        "before_after": {
            "required_evidence_resolved_delta": (
                after["inspection_summary"]["required_evidence_resolved_count"]
                - before["inspection_summary"]["required_evidence_resolved_count"]
            ),
            "no_answer_false_match_delta": (
                after["inspection_summary"]["no_answer_false_match_count"]
                - before["inspection_summary"]["no_answer_false_match_count"]
            ),
            "ontology_hard_gate_false_reject_delta": (
                after["inspection_summary"]["ontology_hard_gate_false_reject_count"]
                - before["inspection_summary"]["ontology_hard_gate_false_reject_count"]
            ),
            "final_answer_generated_delta": (
                after["inspection_summary"]["final_answer_generated_count"]
                - before["inspection_summary"]["final_answer_generated_count"]
            ),
            "improvement_observed": improvement_observed,
            "conclusion": conclusion,
        },
        "limitations": [
            "safe_source_free_observation_fixture_not_private_or_real_business_source",
            "sentencepiece_model_is_fixture_calibration_only_not_production_packaging",
            "no_raw_source_or_pst_completeness_measurement",
            "extractive_diagnostic_answers_are_not_real_user_answer_acceptance",
            "no_independent_holdout_or_same_pipeline_real_source_ablation",
            "ontology_false_reject_is_pre_registered_fixture_diagnostic_only",
            "no_kg_vs_ontology_superiority_or_methodology_readiness_claim",
        ],
    }
    _validate_report_safety(report, fixture)
    return report


def _run_arm(
    *,
    arm_id: str,
    profile: MailCandidateAdmissionTokenizerProfile,
    observations: list[Observation],
    bundle: Any,
    fixture: dict[str, Any],
    replicates: int,
    ontology_mode: str,
) -> dict[str, Any]:
    cold_samples_ms: list[float] = []
    cold_manifest_hashes: set[str] = set()
    last_gateway: MailEvidenceQueryGateway | None = None
    last_manifest: ExistingObservationIndexBuildManifest | None = None
    for _ in range(replicates):
        started = time.perf_counter()
        index, manifest = build_existing_observation_snippet_index(
            observations,
            bundle=bundle,
            tokenizer_profile=profile,
        )
        gateway = MailEvidenceQueryGateway(
            [bundle],
            tokenizer_profile=profile,
            snippet_index_by_bundle_id={bundle.mail_evidence_bundle_id: index},
        )
        _execute_cases(
            gateway=gateway,
            bundle=bundle,
            fixture=fixture,
            observations=observations,
            ontology_mode=ontology_mode,
        )
        cold_samples_ms.append((time.perf_counter() - started) * 1000)
        cold_manifest_hashes.add(sha256_json(manifest.to_safe_dict()))
        last_gateway = gateway
        last_manifest = manifest
    if len(cold_manifest_hashes) != 1 or last_gateway is None or last_manifest is None:
        raise ContractValidationError("observation re-index is nondeterministic")

    index, manifest = build_existing_observation_snippet_index(
        observations,
        bundle=bundle,
        tokenizer_profile=profile,
    )
    gateway = MailEvidenceQueryGateway(
        [bundle],
        tokenizer_profile=profile,
        snippet_index_by_bundle_id={bundle.mail_evidence_bundle_id: index},
    )
    warm_samples_ms: list[float] = []
    inspection: list[dict[str, Any]] = []
    for replicate_index in range(replicates):
        started = time.perf_counter()
        current = _execute_cases(
            gateway=gateway,
            bundle=bundle,
            fixture=fixture,
            observations=observations,
            ontology_mode=ontology_mode,
        )
        warm_samples_ms.append((time.perf_counter() - started) * 1000)
        if replicate_index == replicates - 1:
            inspection = current
    manifest_payload = manifest.to_safe_dict()
    if (
        manifest_payload["query_profile_fingerprint"]
        != manifest_payload["evidence_profile_fingerprint"]
        or manifest_payload["query_profile_fingerprint"] != profile.profile_fingerprint
    ):
        raise ContractValidationError("query and evidence profile fingerprints differ")

    positive_cases = [case for case in inspection if case["expected_outcome"] == "evidence"]
    no_answer_cases = [case for case in inspection if case["expected_outcome"] == "no_match"]
    return {
        "arm_id": arm_id,
        "ontology_mode": ontology_mode,
        "candidate_admission_profile_id": profile.tokenizer_id,
        "candidate_admission_profile_fingerprint": profile.profile_fingerprint,
        "candidate_admission_profile": _safe_profile_payload(profile),
        "index_build_manifest": manifest_payload,
        "query_evidence_profile_fingerprint_equal": True,
        "cold_latency_ms": _latency_summary(cold_samples_ms),
        "warm_latency_ms": _latency_summary(warm_samples_ms),
        "max_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "case_inspection": inspection,
        "inspection_summary": {
            "positive_case_count": len(positive_cases),
            "required_evidence_resolved_count": sum(
                bool(case["required_evidence_resolved"]) for case in positive_cases
            ),
            "citation_alignment_count": sum(
                bool(case["citation_alignment"]) for case in positive_cases
            ),
            "no_answer_case_count": len(no_answer_cases),
            "no_answer_false_match_count": sum(
                int(case["returned_evidence_count"] > 0) for case in no_answer_cases
            ),
            "ontology_hard_gate_false_reject_count": sum(
                bool(case["ontology_hard_gate_false_reject"]) for case in positive_cases
            ),
            "final_answer_generated_count": sum(
                bool(case["final_answer_generated"]) for case in positive_cases
            ),
            "unsupported_answer_count": sum(
                int(case["unsupported_answer_count"]) for case in inspection
            ),
            "answer_abstention_count": sum(
                case["answer_outcome"] == "abstained" for case in inspection
            ),
        },
    }


def _safe_profile_payload(
    profile: MailCandidateAdmissionTokenizerProfile,
) -> dict[str, Any]:
    payload = profile.fingerprint_payload()
    payload["candidate_admission_profile_id"] = payload.pop("tokenizer_id")
    return payload


def _execute_cases(
    *,
    gateway: MailEvidenceQueryGateway,
    bundle: Any,
    fixture: dict[str, Any],
    observations: Sequence[Observation],
    ontology_mode: str,
) -> list[dict[str, Any]]:
    type_signals = _candidate_type_signals(observations)
    profile = gateway._tokenizer_profile
    results: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        result = gateway.query_mail_evidence(
            query_text=case["query_text"],
            requester_user_id=fixture["owner_user_id"],
            workspace_id=fixture["workspace_id"],
            session_id="session_issue33_diagnostic",
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            limit=5,
            now=fixture["created_at"],
        )
        selected_snippets, selected_citations, ontology_trace = _apply_ontology_policy(
            case=case,
            snippets=result.evidence_snippets,
            citations=result.citations,
            type_signals=type_signals,
            ontology_mode=ontology_mode,
        )
        returned_observation_ids = {
            snippet["source_observation_id"] for snippet in selected_snippets
        }
        cited_observation_ids = {
            citation["source_observation_id"] for citation in selected_citations
        }
        required_observation_ids = set(case["required_observation_ids"])
        answer = _build_diagnostic_answer(
            query_hash=result.query_hash,
            snippets=selected_snippets,
            citations=selected_citations,
        )
        query_tokenization = profile.analyze(case["query_text"])
        candidate_graph_trace = _candidate_graph_trace(
            query_tokens=set(query_tokenization.tokens),
            snippets=selected_snippets,
            ontology_trace=ontology_trace,
        )
        results.append(
            {
                "case_id": case["case_id"],
                "case_fingerprint": sha256_json(case),
                "expected_outcome": case["expected_outcome"],
                "result_status": result.status,
                "returned_evidence_count": len(selected_snippets),
                "returned_evidence_fingerprint": sha256_json(sorted(returned_observation_ids)),
                "required_evidence_count": len(required_observation_ids),
                "required_evidence_resolved": required_observation_ids.issubset(
                    returned_observation_ids
                ),
                "citation_alignment": returned_observation_ids == cited_observation_ids,
                "matched_term_count": sum(
                    len(snippet.get("matched_terms", [])) for snippet in selected_snippets
                ),
                "candidate_graph_trace": candidate_graph_trace,
                "ontology_hard_gate_false_reject": bool(
                    required_observation_ids
                    & set(ontology_trace["hard_rejected_observation_ids"])
                ),
                **answer,
                "claim_state": "query_evidence_extractive_answer_diagnostic_only",
            }
        )
    return results


def _candidate_type_signals(
    observations: Sequence[Observation],
) -> dict[str, dict[str, Any]]:
    signals: dict[str, dict[str, Any]] = {}
    for observation in observations:
        core_supertype_id = observation.payload.get("candidate_core_supertype_id")
        type_confidence = observation.payload.get("candidate_type_confidence")
        if core_supertype_id is None and type_confidence is None:
            continue
        if not isinstance(core_supertype_id, str) or isinstance(type_confidence, bool):
            raise ContractValidationError("candidate type signal is invalid")
        if not isinstance(type_confidence, (int, float)):
            raise ContractValidationError("candidate type signal is invalid")
        signals[observation.observation_id] = {
            "core_supertype_id": core_supertype_id,
            "confidence": float(type_confidence),
        }
    return signals


def _apply_ontology_policy(
    *,
    case: dict[str, Any],
    snippets: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    type_signals: dict[str, dict[str, Any]],
    ontology_mode: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if ontology_mode not in {"off", "legacy_hard_gate", "capped_additive_rerank"}:
        raise ContractValidationError("diagnostic ontology mode is unsupported")
    query_core_supertype_id = case.get("query_core_supertype_id")
    query_type_confidence = case.get("query_type_confidence")
    citation_by_observation_id = {
        citation["source_observation_id"]: citation for citation in citations
    }
    ranked: list[tuple[float, dict[str, Any]]] = []
    hard_rejected_observation_ids: list[str] = []
    decisions: list[dict[str, Any]] = []
    for snippet in snippets:
        observation_id = str(snippet["source_observation_id"])
        base_score = float(snippet["score"])
        adjustment = 0.0
        hard_reject = False
        reason = "ontology_signal_unavailable_no_adjustment"
        signal = type_signals.get(observation_id)
        if (
            isinstance(query_core_supertype_id, str)
            and isinstance(query_type_confidence, (int, float))
            and not isinstance(query_type_confidence, bool)
            and signal is not None
        ):
            if ontology_mode == "legacy_hard_gate":
                hard = core_supertypes_compatible(
                    query_core_supertype_id,
                    str(signal["core_supertype_id"]),
                )
                hard_reject = not hard.compatible
                reason = hard.reason
            elif ontology_mode == "capped_additive_rerank":
                soft = soft_core_supertypes_compatible(
                    query_core_supertype_id,
                    str(signal["core_supertype_id"]),
                    left_type_confidence=float(query_type_confidence),
                    right_type_confidence=float(signal["confidence"]),
                )
                adjustment = soft.additive_score_adjustment
                hard_reject = soft.hard_reject
                reason = soft.reason
            else:
                reason = "ontology_disabled"
        if hard_reject:
            hard_rejected_observation_ids.append(observation_id)
        else:
            ranked.append((base_score + adjustment, snippet))
        decisions.append(
            {
                "observation_id": observation_id,
                "base_score": base_score,
                "additive_score_adjustment": adjustment,
                "hard_reject": hard_reject,
                "reason": reason,
            }
        )
    ranked.sort(
        key=lambda item: (
            -item[0],
            str(item[1]["source_observation_id"]),
        )
    )
    selected_snippets = [snippet for _score, snippet in ranked]
    selected_citations = [
        citation_by_observation_id[str(snippet["source_observation_id"])]
        for snippet in selected_snippets
    ]
    return (
        selected_snippets,
        selected_citations,
        {
            "ontology_mode": ontology_mode,
            "hard_rejected_observation_ids": hard_rejected_observation_ids,
            "decision_fingerprint": sha256_json(decisions),
            "decision_count": len(decisions),
            "maximum_additive_score_adjustment": 0.2,
        },
    )


def _candidate_graph_trace(
    *,
    query_tokens: set[str],
    snippets: list[dict[str, Any]],
    ontology_trace: dict[str, Any],
) -> dict[str, Any]:
    edges = [
        {
            "anchor_token_hash": sha256_json(term),
            "candidate_observation_hash": sha256_json(
                snippet["source_observation_id"]
            ),
        }
        for snippet in snippets
        for term in sorted(snippet.get("matched_terms", []))
        if term in query_tokens
    ]
    candidate_hashes = sorted(
        sha256_json(snippet["source_observation_id"]) for snippet in snippets
    )
    return {
        "graph_kind": "runtime_token_anchor_candidate_graph_v1",
        "query_anchor_count": len(query_tokens),
        "query_anchor_fingerprint": sha256_json(
            sorted(sha256_json(token) for token in query_tokens)
        ),
        "candidate_node_count": len(candidate_hashes),
        "candidate_node_fingerprint": sha256_json(candidate_hashes),
        "anchor_edge_count": len(edges),
        "anchor_edge_fingerprint": sha256_json(edges),
        "ontology_mode": ontology_trace["ontology_mode"],
        "ontology_decision_fingerprint": ontology_trace["decision_fingerprint"],
        "ontology_hard_reject_count": len(
            ontology_trace["hard_rejected_observation_ids"]
        ),
    }


def _build_diagnostic_answer(
    *,
    query_hash: str,
    snippets: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    if not snippets:
        payload = {
            "outcome": "abstained",
            "query_hash": query_hash,
            "reason": "no_selected_evidence",
        }
        return {
            "answer_outcome": "abstained",
            "final_answer_generated": False,
            "answer_fingerprint": sha256_json(payload),
            "answer_support_fingerprint": sha256_json([]),
            "answer_citation_count": 0,
            "answer_support_alignment": True,
            "unsupported_answer_count": 0,
        }
    top = snippets[0]
    top_observation_id = str(top["source_observation_id"])
    aligned_citations = [
        citation
        for citation in citations
        if citation["source_observation_id"] == top_observation_id
    ]
    answer_payload = {
        "outcome": "supported",
        "query_hash": query_hash,
        "answer_text": top["snippet"],
        "supporting_observation_id": top_observation_id,
        "citation_ids": sorted(
            str(citation["citation_id"]) for citation in aligned_citations
        ),
    }
    support_alignment = len(aligned_citations) == 1
    return {
        "answer_outcome": "supported",
        "final_answer_generated": True,
        "answer_fingerprint": sha256_json(answer_payload),
        "answer_support_fingerprint": sha256_json([top_observation_id]),
        "answer_citation_count": len(aligned_citations),
        "answer_support_alignment": support_alignment,
        "unsupported_answer_count": int(not support_alignment),
    }


def _load_fixture(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError("issue33 diagnostic fixture is unreadable") from exc
    expected_keys = {
        "schema_version",
        "fixture_id",
        "workspace_id",
        "owner_user_id",
        "source_asset_id",
        "archive_sha256",
        "upload_session_id",
        "created_at",
        "observations",
        "cases",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ContractValidationError("issue33 diagnostic fixture has invalid shape")
    if payload["schema_version"] != 1:
        raise ContractValidationError("issue33 diagnostic fixture schema is unsupported")
    if not isinstance(payload["observations"], list) or not payload["observations"]:
        raise ContractValidationError("issue33 diagnostic fixture has no observations")
    if not isinstance(payload["cases"], list) or not payload["cases"]:
        raise ContractValidationError("issue33 diagnostic fixture has no cases")
    return payload


def _train_safe_calibration_model(temp_dir: Path) -> tuple[Path, str]:
    try:
        import sentencepiece
    except ImportError as exc:
        raise ContractValidationError("sentencepiece is unavailable") from exc
    corpus_path = temp_dir / "calibration.txt"
    corpus_path.write_text(
        "\n".join(_CALIBRATION_CORPUS * 32) + "\n",
        encoding="utf-8",
    )
    model_prefix = temp_dir / "issue33-calibration"
    sentencepiece.SentencePieceTrainer.Train(
        input=str(corpus_path),
        model_prefix=str(model_prefix),
        vocab_size=128,
        model_type="bpe",
        character_coverage=1.0,
        hard_vocab_limit=False,
        shuffle_input_sentence=False,
        num_threads=1,
        minloglevel=2,
    )
    model_path = model_prefix.with_suffix(".model")
    return model_path, _sha256_file(model_path)


def _latency_summary(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    return {
        "sample_count": len(ordered),
        "p50": round(_nearest_rank(ordered, 0.50), 6),
        "p95": round(_nearest_rank(ordered, 0.95), 6),
        "samples": [round(value, 6) for value in samples],
    }


def _nearest_rank(ordered: list[float], quantile: float) -> float:
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def _source_revision() -> str:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_tree_dirty() -> str:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "status", "--short"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _validate_report_safety(report: dict[str, Any], fixture: dict[str, Any]) -> None:
    assert_public_payload_safe(report, "issue33_hybrid_v2_runtime_diagnostic")
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    private_values = [case["query_text"] for case in fixture["cases"]] + [
        observation.get("text")
        for observation in fixture["observations"]
        if isinstance(observation.get("text"), str)
    ]
    if any(value and value in serialized for value in private_values):
        raise ContractValidationError("issue33 diagnostic report exposes fixture text")
    if "holdout" in report["partition"].lower():
        raise ContractValidationError("same-corpus diagnostic cannot be a holdout")


if __name__ == "__main__":
    raise SystemExit(main())
