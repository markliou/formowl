#!/usr/bin/env python3
"""Run the Issue #56 real multilingual dense-embedding rank smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_core import (  # noqa: E402
    DenseEmbeddingUnavailableError,
    build_issue56_execution_component_binding,
    cosine_similarity,
    issue56_target_dense_embedding_profile,
    load_default_mail_candidate_admission_tokenizer_profile,
    load_issue56_target_dense_encoder,
)
from formowl_core.methodology_authority import check_methodology_authority  # noqa: E402

_QUERY_TEXT = "查詢 ZX-2048-ALPHA 採購單的 delivery deadline"
_RELEVANT_EVIDENCE = (
    "採購單 ZX-2048-ALPHA delivery deadline 是 2026-09-30，"
    "由 owner42@example.test 負責，"
    "證據 www.example.test/cases/ZX-2048-ALPHA。"
)
_NEAR_MISS_EVIDENCE = "員工福利 handbook and office lunch schedule for project ZX-2048-BETA."


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Return zero while preserving an explicit blocked report.",
    )
    args = parser.parse_args(argv)
    report = run_smoke()
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    if report["status"] == "passed" or args.allow_blocked:
        return 0
    return 2


def run_smoke() -> dict[str, Any]:
    """Load, embed query/evidence, and rank without any fallback encoder."""

    authority = check_methodology_authority(repository_root=ROOT).to_safe_dict()
    declared_profile = issue56_target_dense_embedding_profile()
    base = {
        "artifact_id": "formowl_issue56_real_dense_embedding_smoke_v1",
        "schema_version": 1,
        "issue": 56,
        "claim_state": "diagnostic_poc_only",
        "dense_profile": {
            "encoder_id": declared_profile.encoder_id,
            "model_id": declared_profile.model_id,
            "model_revision": declared_profile.model_revision,
            "dimension": declared_profile.dimension,
            "normalization_id": declared_profile.normalization_id,
            "model_file_sha256": declared_profile.model_file_sha256,
            "model_artifact_fingerprint": (declared_profile.model_artifact_fingerprint),
            "profile_fingerprint": declared_profile.profile_fingerprint,
            "dependency_versions": dict(declared_profile.dependency_versions),
            "python_version": declared_profile.python_version,
            "backend": declared_profile.backend,
        },
        "methodology_authority": {
            "authority_valid": authority["authority_valid"],
            "status": authority["status"],
            "methodology_ready": authority["methodology_ready"],
            "blocking_gate_ids": authority["blocking_gate_ids"],
        },
        "limitations": [
            "synthetic_authorized_text_only",
            "no_source_completeness_or_oracle_claim",
            "no_final_answer_or_superiority_claim",
            "no_production_or_issue56_completion_claim",
        ],
    }
    try:
        encoder = load_issue56_target_dense_encoder()
    except DenseEmbeddingUnavailableError as exc:
        return {
            **base,
            "status": "blocked",
            "e2e_executed": False,
            "blocker": exc.reason_code,
            "fallback_used": False,
        }
    try:
        tokenizer_profile = load_default_mail_candidate_admission_tokenizer_profile()
    except RuntimeError:
        return {
            **base,
            "status": "blocked",
            "e2e_executed": False,
            "blocker": "target_tokenizer_runtime_unavailable",
            "fallback_used": False,
        }

    query_analysis = tokenizer_profile.analyze(_QUERY_TEXT)
    evidence_analysis = tokenizer_profile.analyze(_RELEVANT_EVIDENCE)
    expected_identifier_kinds = {
        "business_identifier",
        "date",
        "email",
        "url",
    }
    if not expected_identifier_kinds.issubset(
        {span.identifier_kind for span in evidence_analysis.protected_identifiers}
    ):
        raise RuntimeError("Issue #56 dense smoke protected identifiers are incomplete")
    if not query_analysis.tokens or not evidence_analysis.tokens:
        raise RuntimeError("Issue #56 dense smoke tokenizer admission is empty")

    query_vector = encoder.encode_query(_QUERY_TEXT)
    query_rerun = encoder.encode_query(_QUERY_TEXT)
    relevant_vector = encoder.encode_evidence(_RELEVANT_EVIDENCE)
    near_miss_vector = encoder.encode_evidence(_NEAR_MISS_EVIDENCE)
    query_vector_hash = _vector_hash(query_vector)
    if query_vector_hash != _vector_hash(query_rerun):
        raise RuntimeError("Issue #56 dense query embedding is not deterministic")
    relevant_score = cosine_similarity(query_vector, relevant_vector)
    near_miss_score = cosine_similarity(query_vector, near_miss_vector)
    if relevant_score <= near_miss_score:
        raise RuntimeError("Issue #56 dense relevant evidence did not outrank near miss")
    binding = build_issue56_execution_component_binding(
        tokenizer_profile=tokenizer_profile,
        dense_profile=encoder.profile,
    )

    return {
        **base,
        "status": "passed",
        "e2e_executed": True,
        "fallback_used": False,
        "path_executed": [
            "load_verified_multilingual_model",
            "load_frozen_target_tokenizer",
            "embed_query",
            "embed_relevant_evidence",
            "embed_near_miss_evidence",
            "deterministic_cosine_rank",
        ],
        "tokenizer": {
            "tokenizer_id": tokenizer_profile.tokenizer_id,
            "profile_fingerprint": tokenizer_profile.profile_fingerprint,
            "query_evidence_profile_match": True,
            "protected_identifier_kinds": sorted(expected_identifier_kinds),
        },
        "execution_component": {
            **binding.fingerprint_payload(),
            "execution_component_fingerprint": (binding.execution_component_fingerprint),
        },
        "rank": {
            "candidate_count": 2,
            "relevant_rank": 1,
            "relevant_score": round(relevant_score, 8),
            "near_miss_score": round(near_miss_score, 8),
            "score_margin": round(relevant_score - near_miss_score, 8),
        },
        "determinism": {
            "query_vector_hash": query_vector_hash,
            "rerun_vector_hash": _vector_hash(query_rerun),
            "query_norm": round(_norm(query_vector), 8),
            "relevant_norm": round(_norm(relevant_vector), 8),
            "near_miss_norm": round(_norm(near_miss_vector), 8),
        },
        "input_hashes": {
            "query": _text_hash(_QUERY_TEXT),
            "relevant_evidence": _text_hash(_RELEVANT_EVIDENCE),
            "near_miss_evidence": _text_hash(_NEAR_MISS_EVIDENCE),
        },
    }


def _norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _vector_hash(vector: Sequence[float]) -> str:
    return _text_hash(
        json.dumps(
            [round(float(value), 8) for value in vector],
            separators=(",", ":"),
        )
    )


def _text_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
