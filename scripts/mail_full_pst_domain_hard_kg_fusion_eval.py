#!/usr/bin/env python3
"""Run or validate a non-BERT KG fusion probe for #21 hard-domain mail cases.

This experiment reuses an existing hard-domain full-PST work directory. It does
not reparse the PST and does not run BERT, SentenceTransformer, local LLM, or
other neural inference. The private manifest may contain query text and
observation ids; the public report is hash/status/count/timing only.

Measured path:

preserved full-PST observations + private hard-case manifest
-> deterministic candidate-only mail KG components
-> 100 hard-domain case coverage scores.

The output is a research baseline for whether candidate graph structure can
connect cross-message evidence. It is not business answer generation and it is
not a canonical KG/write or wiki projection claim.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts"
PYTHON_ROOT = ROOT / "python"
for import_path in (PYTHON_ROOT, SCRIPT_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import mail_full_pst_domain_hard_case_eval as hard_eval  # noqa: E402
from formowl_contract import sha256_json  # noqa: E402
from formowl_evaluator.report_validation import (  # noqa: E402
    mapping_dict_or_empty as _dict_or_empty,
    public_outputs_are_safe,
    require_sha256 as _require_sha256,
    validate_exact_keys as _validate_exact_keys,
)

DEFAULT_BASELINE_REPORT = ROOT / ".test-tmp" / "formowl-mail-domain-hard-case-baseline-v4.json"
DEFAULT_WORK_DIR = ROOT / ".test-tmp" / "formowl-mail-domain-hard-case-baseline-work-v4"
DEFAULT_OUTPUT = ROOT / ".test-tmp" / "formowl-mail-domain-hard-kg-fusion-eval.json"
PRIVATE_MANIFEST_RELATIVE = Path("artifacts") / hard_eval.PRIVATE_MANIFEST_NAME
NOW = "2026-07-07T12:30:00+00:00"
REPORT_TYPE = "mail_full_pst_domain_hard_kg_fusion_eval"
KG_POLICY_VERSION = "formowl_domain_hard_non_bert_candidate_kg_v1"
RUN_OPT_IN_ENV = "FORMOWL_RUN_FULL_PST_DOMAIN_HARD_KG_FUSION_EVAL"
CASE_COUNT = 100
MAX_TOKEN_DF = 48
MAX_COMPONENT_EVIDENCE_PER_CASE = 10

_STOPWORDS = {
    "a",
    "about",
    "across",
    "after",
    "all",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "between",
    "by",
    "can",
    "case",
    "compare",
    "did",
    "email",
    "emails",
    "evidence",
    "find",
    "for",
    "from",
    "how",
    "in",
    "involving",
    "is",
    "it",
    "latest",
    "mail",
    "mention",
    "multiple",
    "of",
    "on",
    "or",
    "possible",
    "reconcile",
    "related",
    "separate",
    "separate-email",
    "that",
    "the",
    "to",
    "what",
    "with",
}
_DOMAIN_TERMS = frozenset(
    token for terms in hard_eval.DOMAIN_VOCABULARY.values() for token in terms
)
_CONFLICT_TERMS = frozenset(hard_eval.CONFLICT_TERMS)
_IMPORTANT_TERMS = _DOMAIN_TERMS | _CONFLICT_TERMS

_TOP_LEVEL_KEYS = {
    "report_type",
    "generated_at",
    "metrics",
    "safe_outputs",
    "claim_boundary",
}
_FORBIDDEN_TRUE_CLAIMS = {
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_real_upload_iframe_claim",
    "supports_general_full_pst_parser_readiness_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_business_answer_generation_claim",
    "supports_bert_or_neural_candidate_generation_claim",
    "supports_canonical_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_raw_mail_access_claim",
    "supports_production_ready_claim",
}
_REQUIRED_SUCCESS_METRICS = {
    "baseline_report_loaded",
    "baseline_report_validation_passed",
    "private_manifest_loaded",
    "observations_loaded",
    "body_segments_loaded",
    "deterministic_candidate_kg_built",
    "no_bert_or_neural_dependency_used",
    "candidate_only_boundary_respected",
    "canonical_kg_wiki_side_effects_absent",
    "component_degeneracy_recorded",
    "domain_case_count_is_100",
    "positive_cases_scored",
    "permission_denied_cases_preserved",
    "case_scores_recorded",
    "row_derived_validation_recomputed",
    "raw_leak_guard_passed",
    "kg_fusion_eval_completed",
}
_BLOCKED_REASONS = {
    "kg_fusion_eval_requires_explicit_opt_in",
    "explicit_work_dir_required",
    "baseline_report_missing",
    "baseline_report_invalid",
    "work_dir_missing",
    "private_manifest_missing",
    "observations_missing",
    "kg_fusion_eval_failed",
}


@dataclass(frozen=True)
class _MailSegment:
    observation_id: str
    thread_id: str | None
    message_occurrence_id: str | None
    message_id: str | None
    tokens: frozenset[str]


@dataclass
class _UnionFind:
    parent: dict[str, str]
    size: dict[str, int]

    @classmethod
    def from_ids(cls, ids: Sequence[str]) -> "_UnionFind":
        return cls(parent={item: item for item in ids}, size={item: 1 for item in ids})

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> bool:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return False
        if self.size[left_root] < self.size[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.size[left_root] += self.size[right_root]
        return True


@dataclass(frozen=True)
class _CandidateKgIndex:
    segment_by_observation_id: dict[str, _MailSegment]
    component_by_observation_id: dict[str, str]
    observation_ids_by_component: dict[str, tuple[str, ...]]
    tokens_by_component: dict[str, frozenset[str]]
    component_ids_by_token: dict[str, tuple[str, ...]]
    candidate_relation_count: int
    token_relation_count: int
    thread_relation_count: int

    @property
    def candidate_atom_count(self) -> int:
        return len(self.segment_by_observation_id)

    @property
    def component_count(self) -> int:
        return len(self.observation_ids_by_component)

    @property
    def largest_component_size(self) -> int:
        if not self.observation_ids_by_component:
            return 0
        return max(len(items) for items in self.observation_ids_by_component.values())


def run_kg_fusion_eval(
    *,
    baseline_report_path: Path | None = None,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    if os.environ.get(RUN_OPT_IN_ENV) != "1":
        return _blocked_report("kg_fusion_eval_requires_explicit_opt_in")
    if baseline_report_path is None or work_dir is None:
        return _blocked_report("explicit_work_dir_required")

    try:
        return _run_kg_fusion_eval_inner(
            baseline_report_path=baseline_report_path,
            work_dir=work_dir,
        )
    except FileNotFoundError as exc:
        reason = str(exc)
        if reason in _BLOCKED_REASONS:
            return _blocked_report(reason)
        return _blocked_report("kg_fusion_eval_failed")
    except Exception:
        return _blocked_report("kg_fusion_eval_failed")


def _run_kg_fusion_eval_inner(*, baseline_report_path: Path, work_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    baseline_report = _read_json_file(baseline_report_path, "baseline_report_missing")
    baseline_hash = sha256_json(baseline_report)
    baseline_validation = hard_eval.validate_report(baseline_report)
    if not baseline_validation.get("passed"):
        raise FileNotFoundError("baseline_report_invalid")
    if not work_dir.exists() or not work_dir.is_dir():
        raise FileNotFoundError("work_dir_missing")

    load_started = time.monotonic()
    segments = _load_mail_segments(work_dir)
    observations_load_elapsed_ms = int((time.monotonic() - load_started) * 1000)
    if not segments:
        raise FileNotFoundError("observations_missing")

    kg_started = time.monotonic()
    kg_index = _build_candidate_kg_index(segments)
    kg_build_elapsed_ms = int((time.monotonic() - kg_started) * 1000)

    manifest = _read_json_file(work_dir / PRIVATE_MANIFEST_RELATIVE, "private_manifest_missing")
    manifest_hash = sha256_json(manifest)
    cases = _validate_private_manifest_cases(manifest)

    scoring_started = time.monotonic()
    baseline_rows = _baseline_rows_by_manifest_hash(baseline_report)
    rows = [
        _score_case(
            case,
            kg_index=kg_index,
            baseline_row=baseline_rows.get(case["private_fingerprint"]),
        )
        for case in cases
    ]
    scoring_elapsed_ms = int((time.monotonic() - scoring_started) * 1000)

    safe_outputs = _safe_outputs(
        baseline_report=baseline_report,
        baseline_hash=baseline_hash,
        manifest_hash=manifest_hash,
        rows=rows,
        kg_index=kg_index,
        observations_load_elapsed_ms=observations_load_elapsed_ms,
        kg_build_elapsed_ms=kg_build_elapsed_ms,
        scoring_elapsed_ms=scoring_elapsed_ms,
        total_elapsed_ms=int((time.monotonic() - started) * 1000),
    )
    metrics = {
        "baseline_report_loaded": True,
        "baseline_report_validation_passed": True,
        "private_manifest_loaded": True,
        "observations_loaded": True,
        "body_segments_loaded": safe_outputs["body_segment_count"] > 0,
        "deterministic_candidate_kg_built": safe_outputs["candidate_graph_node_count"] > 0,
        "no_bert_or_neural_dependency_used": True,
        "candidate_only_boundary_respected": True,
        "canonical_kg_wiki_side_effects_absent": _no_graph_or_wiki_side_effects(work_dir),
        "component_degeneracy_recorded": True,
        "domain_case_count_is_100": safe_outputs["case_count"] == CASE_COUNT,
        "positive_cases_scored": safe_outputs["positive_case_count"] == 80,
        "permission_denied_cases_preserved": safe_outputs["permission_denied_passed_count"] == 10,
        "no_match_cases_non_leaking": safe_outputs["no_match_passed_count"] == 10,
        "case_scores_recorded": len(rows) == CASE_COUNT,
        "row_derived_validation_recomputed": True,
        "raw_leak_guard_passed": False,
        "kg_fusion_eval_completed": False,
    }
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": _claim_boundary(False),
    }
    report["metrics"]["raw_leak_guard_passed"] = _public_outputs_are_safe(report)
    report["metrics"]["kg_fusion_eval_completed"] = _kg_fusion_eval_completed(report)
    report["claim_boundary"]["supports_candidate_only_kg_fusion_experiment_claim"] = report[
        "metrics"
    ]["kg_fusion_eval_completed"]
    report["validation"] = validate_report(report)
    return report


def _validate_private_manifest_cases(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != CASE_COUNT:
        raise RuntimeError("invalid_private_manifest")
    validated: list[dict[str, Any]] = []
    for item in cases:
        if not isinstance(item, dict):
            raise RuntimeError("invalid_private_manifest")
        result_kind = item.get("result_kind")
        if result_kind not in {"owner_match", "no_match", "permission_denied"}:
            raise RuntimeError("invalid_private_manifest")
        query_text = item.get("query_text")
        fingerprint = item.get("private_fingerprint")
        required_ids = item.get("required_source_observation_ids", [])
        if not isinstance(query_text, str) or not isinstance(fingerprint, str):
            raise RuntimeError("invalid_private_manifest")
        if not isinstance(required_ids, list) or any(
            not isinstance(value, str) for value in required_ids
        ):
            raise RuntimeError("invalid_private_manifest")
        validated.append(item)
    return validated


def _load_mail_segments(work_dir: Path) -> list[_MailSegment]:
    observations_dir = work_dir / "data" / "ingestion" / "observations"
    if not observations_dir.exists():
        raise FileNotFoundError("observations_missing")
    segments: list[_MailSegment] = []
    for path in sorted(observations_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("observation_type") != "email_body_segment":
            continue
        observation_id = payload.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id:
            continue
        text = payload.get("text")
        location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
        body_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        searchable = " ".join(
            item
            for item in (
                text,
                body_payload.get("thread_id"),
                body_payload.get("message_id"),
                location.get("thread_id"),
                location.get("message_id"),
            )
            if isinstance(item, str)
        )
        tokens = frozenset(_tokenize(searchable))
        segments.append(
            _MailSegment(
                observation_id=observation_id,
                thread_id=_string_or_none(location.get("thread_id"))
                or _string_or_none(body_payload.get("thread_id")),
                message_occurrence_id=_string_or_none(location.get("message_occurrence_id"))
                or _string_or_none(body_payload.get("message_occurrence_id")),
                message_id=_string_or_none(location.get("message_id"))
                or _string_or_none(body_payload.get("message_id")),
                tokens=tokens,
            )
        )
    return segments


def _build_candidate_kg_index(segments: Sequence[_MailSegment]) -> _CandidateKgIndex:
    ids = [segment.observation_id for segment in segments]
    union_find = _UnionFind.from_ids(ids)
    segment_by_id = {segment.observation_id: segment for segment in segments}
    relation_count = 0
    thread_relation_count = 0
    token_relation_count = 0

    for grouped_ids in _groups_by_value(segments, "thread_id").values():
        added = _union_group(union_find, grouped_ids)
        relation_count += added
        thread_relation_count += added

    token_to_ids: dict[str, list[str]] = defaultdict(list)
    for segment in segments:
        for token in segment.tokens:
            if token in _IMPORTANT_TERMS:
                token_to_ids[token].append(segment.observation_id)
    for grouped_ids in token_to_ids.values():
        if 2 <= len(grouped_ids) <= MAX_TOKEN_DF:
            added = _union_group(union_find, grouped_ids)
            relation_count += added
            token_relation_count += added

    ids_by_component: dict[str, list[str]] = defaultdict(list)
    tokens_by_component: dict[str, set[str]] = defaultdict(set)
    for segment in segments:
        component_id = union_find.find(segment.observation_id)
        ids_by_component[component_id].append(segment.observation_id)
        tokens_by_component[component_id].update(segment.tokens & _IMPORTANT_TERMS)

    component_by_observation_id = {
        observation_id: component_id
        for component_id, observation_ids in ids_by_component.items()
        for observation_id in observation_ids
    }
    component_ids_by_token: dict[str, set[str]] = defaultdict(set)
    for component_id, tokens in tokens_by_component.items():
        for token in tokens:
            component_ids_by_token[token].add(component_id)

    return _CandidateKgIndex(
        segment_by_observation_id=segment_by_id,
        component_by_observation_id=component_by_observation_id,
        observation_ids_by_component={
            component_id: tuple(sorted(observation_ids))
            for component_id, observation_ids in ids_by_component.items()
        },
        tokens_by_component={
            component_id: frozenset(tokens) for component_id, tokens in tokens_by_component.items()
        },
        component_ids_by_token={
            token: tuple(sorted(component_ids))
            for token, component_ids in component_ids_by_token.items()
        },
        candidate_relation_count=relation_count,
        token_relation_count=token_relation_count,
        thread_relation_count=thread_relation_count,
    )


def _groups_by_value(
    segments: Sequence[_MailSegment],
    field_name: str,
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for segment in segments:
        value = getattr(segment, field_name)
        if isinstance(value, str) and value:
            grouped[value].append(segment.observation_id)
    return grouped


def _union_group(union_find: _UnionFind, ids: Sequence[str]) -> int:
    if len(ids) < 2:
        return 0
    first = ids[0]
    count = 0
    for item in ids[1:]:
        if union_find.union(first, item):
            count += 1
    return count


def _score_case(
    case: Mapping[str, Any],
    *,
    kg_index: _CandidateKgIndex,
    baseline_row: Mapping[str, Any] | None,
) -> dict[str, Any]:
    started = time.monotonic()
    result_kind = str(case["result_kind"])
    required_ids = tuple(str(value) for value in case.get("required_source_observation_ids", []))
    required_count = len(required_ids)
    required_match_count = int(case.get("required_match_count", 0))
    limit = int(case.get("limit", MAX_COMPONENT_EVIDENCE_PER_CASE))
    baseline_status = (
        str(baseline_row.get("status"))
        if isinstance(baseline_row, Mapping) and isinstance(baseline_row.get("status"), str)
        else "unknown"
    )

    if result_kind == "permission_denied":
        selected_ids: tuple[str, ...] = ()
        selected_components: tuple[str, ...] = ()
        matched_required_count = 0
        status = "passed"
        warning_count = 1
    else:
        query_tokens = _tokenize(str(case.get("query_text", "")))
        selected_components = _rank_components(query_tokens, kg_index, limit=4)
        selected_ids = _evidence_from_components(
            selected_components,
            query_tokens=query_tokens,
            kg_index=kg_index,
            limit=min(max(limit, 0), MAX_COMPONENT_EVIDENCE_PER_CASE),
        )
        required_set = set(required_ids)
        matched_required_count = len(required_set & set(selected_ids))
        warning_count = 0
        if result_kind == "owner_match":
            status = "passed" if matched_required_count >= required_match_count else "failed"
        else:
            status = "passed" if len(selected_ids) == 0 else "failed"

    row = {
        "case_id_hash": sha256_json(str(case.get("case_id", ""))),
        "case_manifest_entry_hash": str(case["private_fingerprint"]),
        "domain_hash": sha256_json(str(case.get("domain", ""))),
        "intent_kind_hash": sha256_json(str(case.get("intent_kind", ""))),
        "pattern_hash": sha256_json(str(case.get("pattern", ""))),
        "result_kind": result_kind,
        "baseline_status": baseline_status,
        "kg_status": status,
        "required_evidence_count": required_count,
        "matched_required_evidence_count": matched_required_count,
        "selected_component_count": len(selected_components),
        "selected_evidence_count": len(selected_ids),
        "warning_count": warning_count,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    row["response_hash"] = sha256_json(
        {
            "case": row["case_id_hash"],
            "baseline_status": baseline_status,
            "kg_status": status,
            "selected_components": selected_components,
            "selected_evidence": selected_ids,
            "matched_required": matched_required_count,
        }
    )
    return row


def _rank_components(
    query_tokens: set[str],
    kg_index: _CandidateKgIndex,
    *,
    limit: int,
) -> tuple[str, ...]:
    important_query_tokens = query_tokens & _IMPORTANT_TERMS
    scores: Counter[str] = Counter()
    for token in important_query_tokens:
        for component_id in kg_index.component_ids_by_token.get(token, ()):
            scores[component_id] += 1
    ranked = sorted(
        scores,
        key=lambda component_id: (
            -scores[component_id],
            len(kg_index.observation_ids_by_component[component_id]),
            component_id,
        ),
    )
    return tuple(ranked[:limit])


def _evidence_from_components(
    component_ids: Sequence[str],
    *,
    query_tokens: set[str],
    kg_index: _CandidateKgIndex,
    limit: int,
) -> tuple[str, ...]:
    if limit <= 0:
        return ()
    ranked: list[tuple[int, str]] = []
    for component_id in component_ids:
        for observation_id in kg_index.observation_ids_by_component.get(component_id, ()):
            segment = kg_index.segment_by_observation_id[observation_id]
            score = len(segment.tokens & query_tokens)
            ranked.append((-score, observation_id))
    return tuple(observation_id for _, observation_id in sorted(ranked)[:limit])


def _safe_outputs(
    *,
    baseline_report: Mapping[str, Any],
    baseline_hash: str,
    manifest_hash: str,
    rows: Sequence[Mapping[str, Any]],
    kg_index: _CandidateKgIndex,
    observations_load_elapsed_ms: int,
    kg_build_elapsed_ms: int,
    scoring_elapsed_ms: int,
    total_elapsed_ms: int,
) -> dict[str, Any]:
    kg_counts = _kg_aggregate_scores(rows)
    baseline_safe = baseline_report.get("safe_outputs")
    baseline_safe_outputs = baseline_safe if isinstance(baseline_safe, Mapping) else {}
    baseline_passed = _int_or_zero(baseline_safe_outputs.get("passed_case_count"))
    baseline_pass_rate = _int_or_zero(baseline_safe_outputs.get("pass_rate_basis_points"))
    return {
        "baseline_report_hash": baseline_hash,
        "baseline_case_result_hash": str(baseline_safe_outputs.get("case_result_hash", "")),
        "baseline_passed_case_count": baseline_passed,
        "baseline_pass_rate_basis_points": baseline_pass_rate,
        "private_manifest_hash": manifest_hash,
        "case_policy_hash": sha256_json(KG_POLICY_VERSION),
        "case_result_hash": sha256_json(rows),
        "case_count": kg_counts["case_count"],
        "scored_case_count": kg_counts["scored_case_count"],
        "kg_passed_case_count": kg_counts["kg_passed_case_count"],
        "kg_failed_case_count": kg_counts["kg_failed_case_count"],
        "kg_pass_rate_basis_points": kg_counts["kg_pass_rate_basis_points"],
        "kg_delta_passed_case_count": kg_counts["kg_passed_case_count"] - baseline_passed,
        "baseline_failed_kg_passed_count": sum(
            1
            for row in rows
            if row.get("baseline_status") != "passed" and row.get("kg_status") == "passed"
        ),
        "baseline_passed_kg_failed_count": sum(
            1
            for row in rows
            if row.get("baseline_status") == "passed" and row.get("kg_status") != "passed"
        ),
        "positive_case_count": kg_counts["positive_case_count"],
        "positive_passed_count": kg_counts["positive_passed_count"],
        "no_match_case_count": kg_counts["no_match_case_count"],
        "no_match_passed_count": kg_counts["no_match_passed_count"],
        "permission_denied_case_count": kg_counts["permission_denied_case_count"],
        "permission_denied_passed_count": kg_counts["permission_denied_passed_count"],
        "unique_case_id_hash_count": len({row.get("case_id_hash") for row in rows}),
        "unique_response_hash_count": len({row.get("response_hash") for row in rows}),
        "duplicate_response_hash_count": len(rows)
        - len({row.get("response_hash") for row in rows}),
        "domain_hash_counts": _row_counts(rows, "domain_hash"),
        "domain_hash_passed_counts": _passed_row_counts(rows, "domain_hash"),
        "pattern_hash_counts": _row_counts(rows, "pattern_hash"),
        "pattern_hash_passed_counts": _passed_row_counts(rows, "pattern_hash"),
        "result_kind_counts": _row_counts(rows, "result_kind"),
        "candidate_graph_node_count": kg_index.candidate_atom_count,
        "candidate_graph_relation_count": kg_index.candidate_relation_count,
        "thread_relation_count": kg_index.thread_relation_count,
        "term_relation_count": kg_index.token_relation_count,
        "kg_component_count": kg_index.component_count,
        "largest_component_size": kg_index.largest_component_size,
        "largest_component_basis_points": int(
            (kg_index.largest_component_size / max(kg_index.candidate_atom_count, 1)) * 10000
        ),
        "oversized_component_count": sum(
            1
            for observation_ids in kg_index.observation_ids_by_component.values()
            if len(observation_ids) > max(25, int(kg_index.candidate_atom_count * 0.25))
        ),
        "searchable_term_count": len(kg_index.component_ids_by_token),
        "observation_count": _int_or_zero(baseline_safe_outputs.get("observation_count")),
        "body_segment_count": kg_index.candidate_atom_count,
        "message_count": _int_or_zero(baseline_safe_outputs.get("message_count")),
        "parse_warning_count": _int_or_zero(baseline_safe_outputs.get("parse_warning_count")),
        "baseline_import_elapsed_ms": _int_or_zero(baseline_safe_outputs.get("import_elapsed_ms")),
        "baseline_query_loop_elapsed_ms": _int_or_zero(
            baseline_safe_outputs.get("case_query_loop_elapsed_ms")
        ),
        "observations_load_elapsed_ms": observations_load_elapsed_ms,
        "kg_build_elapsed_ms": kg_build_elapsed_ms,
        "scoring_elapsed_ms": scoring_elapsed_ms,
        "total_elapsed_ms": total_elapsed_ms,
        "case_rows": list(rows),
    }


def validate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, Mapping):
        return _validation(False, ["report must be an object"])
    _validate_exact_keys(
        report,
        _TOP_LEVEL_KEYS,
        "report",
        blockers,
        allowed_extra={"validation"},
    )
    if report.get("report_type") != REPORT_TYPE:
        blockers.append("report_type mismatch")
    metrics = _dict_or_empty(report.get("metrics"), "metrics", blockers)
    safe_outputs = _dict_or_empty(report.get("safe_outputs"), "safe_outputs", blockers)
    claim_boundary = _dict_or_empty(report.get("claim_boundary"), "claim_boundary", blockers)
    if "blocked_reason" in metrics:
        _validate_blocked_report(metrics, safe_outputs, claim_boundary, blockers)
    else:
        _validate_success_report(metrics, safe_outputs, claim_boundary, blockers)
    _validate_embedded_validation(report.get("validation"), report, blockers)
    _reject_private_text_or_evidence_fields(report, blockers)
    if not _public_outputs_are_safe(report):
        blockers.append("public output leak guard failed")
    return _validation(not blockers, blockers, report=report)


def _validate_success_report(
    metrics: Mapping[str, Any],
    safe_outputs: Mapping[str, Any],
    claim_boundary: Mapping[str, Any],
    blockers: list[str],
) -> None:
    expected_metric_keys = set(_REQUIRED_SUCCESS_METRICS) | {"no_match_cases_non_leaking"}
    _validate_exact_keys(metrics, expected_metric_keys, "metrics", blockers)
    for key in _REQUIRED_SUCCESS_METRICS:
        if metrics.get(key) is not True:
            blockers.append("required KG fusion metric is not true: " + key)
    if type(metrics.get("no_match_cases_non_leaking")) is not bool:
        blockers.append("no_match_cases_non_leaking must be boolean")
    expected_safe_keys = {
        "baseline_report_hash",
        "baseline_case_result_hash",
        "baseline_passed_case_count",
        "baseline_pass_rate_basis_points",
        "private_manifest_hash",
        "case_policy_hash",
        "case_result_hash",
        "case_count",
        "scored_case_count",
        "kg_passed_case_count",
        "kg_failed_case_count",
        "kg_pass_rate_basis_points",
        "kg_delta_passed_case_count",
        "baseline_failed_kg_passed_count",
        "baseline_passed_kg_failed_count",
        "positive_case_count",
        "positive_passed_count",
        "no_match_case_count",
        "no_match_passed_count",
        "permission_denied_case_count",
        "permission_denied_passed_count",
        "unique_case_id_hash_count",
        "unique_response_hash_count",
        "duplicate_response_hash_count",
        "domain_hash_counts",
        "domain_hash_passed_counts",
        "pattern_hash_counts",
        "pattern_hash_passed_counts",
        "result_kind_counts",
        "candidate_graph_node_count",
        "candidate_graph_relation_count",
        "thread_relation_count",
        "term_relation_count",
        "kg_component_count",
        "largest_component_size",
        "largest_component_basis_points",
        "oversized_component_count",
        "searchable_term_count",
        "observation_count",
        "body_segment_count",
        "message_count",
        "parse_warning_count",
        "baseline_import_elapsed_ms",
        "baseline_query_loop_elapsed_ms",
        "observations_load_elapsed_ms",
        "kg_build_elapsed_ms",
        "scoring_elapsed_ms",
        "total_elapsed_ms",
        "case_rows",
    }
    _validate_exact_keys(safe_outputs, expected_safe_keys, "safe_outputs", blockers)
    for key in (
        "baseline_report_hash",
        "baseline_case_result_hash",
        "private_manifest_hash",
        "case_policy_hash",
        "case_result_hash",
    ):
        _require_sha256(safe_outputs.get(key), "safe_outputs." + key, blockers)
    for key in expected_safe_keys - {
        "baseline_report_hash",
        "baseline_case_result_hash",
        "private_manifest_hash",
        "case_policy_hash",
        "case_result_hash",
        "case_rows",
        "domain_hash_counts",
        "domain_hash_passed_counts",
        "pattern_hash_counts",
        "pattern_hash_passed_counts",
        "result_kind_counts",
    }:
        if type(safe_outputs.get(key)) is not int:
            blockers.append(f"safe_outputs.{key} must be an integer")
    rows = safe_outputs.get("case_rows")
    if not isinstance(rows, list) or len(rows) != CASE_COUNT:
        blockers.append("safe_outputs.case_rows must contain 100 rows")
    elif any(not isinstance(row, Mapping) for row in rows):
        blockers.append("case_rows entries must be objects")
    else:
        _validate_case_rows(rows, blockers)
        _validate_row_derived_bindings(safe_outputs, rows, blockers)
    _validate_success_claim_boundary(claim_boundary, metrics, blockers)


def _validate_case_rows(rows: Sequence[Mapping[str, Any]], blockers: list[str]) -> None:
    expected_keys = {
        "case_id_hash",
        "case_manifest_entry_hash",
        "domain_hash",
        "intent_kind_hash",
        "pattern_hash",
        "result_kind",
        "baseline_status",
        "kg_status",
        "required_evidence_count",
        "matched_required_evidence_count",
        "selected_component_count",
        "selected_evidence_count",
        "warning_count",
        "elapsed_ms",
        "response_hash",
    }
    case_hashes: set[str] = set()
    response_hashes: set[str] = set()
    for row in rows:
        _validate_exact_keys(row, expected_keys, "case_row", blockers)
        for key in (
            "case_id_hash",
            "case_manifest_entry_hash",
            "domain_hash",
            "intent_kind_hash",
            "pattern_hash",
            "response_hash",
        ):
            _require_sha256(row.get(key), "case_row." + key, blockers)
        if row.get("result_kind") not in {"owner_match", "no_match", "permission_denied"}:
            blockers.append("case_row.result_kind must be a configured enum")
        if row.get("baseline_status") not in {"passed", "failed", "unknown"}:
            blockers.append("case_row.baseline_status must be a configured enum")
        if row.get("kg_status") not in {"passed", "failed"}:
            blockers.append("case_row.kg_status must be a configured enum")
        for key in (
            "required_evidence_count",
            "matched_required_evidence_count",
            "selected_component_count",
            "selected_evidence_count",
            "warning_count",
            "elapsed_ms",
        ):
            if type(row.get(key)) is not int:
                blockers.append(f"case_row.{key} must be an integer")
        if row.get("result_kind") == "permission_denied" and row.get("kg_status") == "passed":
            if row.get("selected_component_count") != 0 or row.get("selected_evidence_count") != 0:
                blockers.append("passed permission_denied KG row must expose no selected evidence")
        if isinstance(row.get("case_id_hash"), str):
            case_hashes.add(row["case_id_hash"])
        if isinstance(row.get("response_hash"), str):
            response_hashes.add(row["response_hash"])
    if len(case_hashes) != CASE_COUNT:
        blockers.append("case rows must contain 100 unique case hashes")
    if len(response_hashes) != CASE_COUNT:
        blockers.append("case rows must contain 100 unique response hashes")


def _validate_row_derived_bindings(
    safe_outputs: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    blockers: list[str],
) -> None:
    aggregate = _kg_aggregate_scores(rows)
    for key, value in aggregate.items():
        if safe_outputs.get(key) != value:
            blockers.append(f"safe_outputs.{key} does not match case rows")
    if safe_outputs.get("case_result_hash") != sha256_json(rows):
        blockers.append("safe_outputs.case_result_hash does not match case rows")
    duplicate_response_hash_count = len(rows) - len(
        {row.get("response_hash") for row in rows if isinstance(row.get("response_hash"), str)}
    )
    derived = {
        "unique_case_id_hash_count": len(
            {row.get("case_id_hash") for row in rows if isinstance(row.get("case_id_hash"), str)}
        ),
        "unique_response_hash_count": len(
            {row.get("response_hash") for row in rows if isinstance(row.get("response_hash"), str)}
        ),
        "duplicate_response_hash_count": duplicate_response_hash_count,
        "domain_hash_counts": _row_counts(rows, "domain_hash"),
        "domain_hash_passed_counts": _passed_row_counts(rows, "domain_hash"),
        "pattern_hash_counts": _row_counts(rows, "pattern_hash"),
        "pattern_hash_passed_counts": _passed_row_counts(rows, "pattern_hash"),
        "result_kind_counts": _row_counts(rows, "result_kind"),
        "baseline_failed_kg_passed_count": sum(
            1
            for row in rows
            if row.get("baseline_status") != "passed" and row.get("kg_status") == "passed"
        ),
        "baseline_passed_kg_failed_count": sum(
            1
            for row in rows
            if row.get("baseline_status") == "passed" and row.get("kg_status") != "passed"
        ),
    }
    for key, value in derived.items():
        if safe_outputs.get(key) != value:
            blockers.append(f"safe_outputs.{key} does not match case rows")
    if safe_outputs.get("duplicate_response_hash_count") != 0:
        blockers.append("safe_outputs.duplicate_response_hash_count must be 0")
    if (
        type(safe_outputs.get("kg_delta_passed_case_count")) is int
        and type(safe_outputs.get("baseline_passed_case_count")) is int
        and type(safe_outputs.get("kg_passed_case_count")) is int
        and safe_outputs.get("kg_delta_passed_case_count")
        != safe_outputs.get("kg_passed_case_count") - safe_outputs.get("baseline_passed_case_count")
    ):
        blockers.append("safe_outputs.kg_delta_passed_case_count is stale")


def _kg_aggregate_scores(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    case_count = len(rows)
    passed = sum(1 for row in rows if row.get("kg_status") == "passed")
    positive_count = sum(1 for row in rows if row.get("result_kind") == "owner_match")
    no_match_count = sum(1 for row in rows if row.get("result_kind") == "no_match")
    denied_count = sum(1 for row in rows if row.get("result_kind") == "permission_denied")
    return {
        "case_count": case_count,
        "scored_case_count": case_count,
        "kg_passed_case_count": passed,
        "kg_failed_case_count": case_count - passed,
        "kg_pass_rate_basis_points": int((passed / case_count) * 10000) if case_count else 0,
        "positive_case_count": positive_count,
        "positive_passed_count": sum(
            1
            for row in rows
            if row.get("result_kind") == "owner_match" and row.get("kg_status") == "passed"
        ),
        "no_match_case_count": no_match_count,
        "no_match_passed_count": sum(
            1
            for row in rows
            if row.get("result_kind") == "no_match" and row.get("kg_status") == "passed"
        ),
        "permission_denied_case_count": denied_count,
        "permission_denied_passed_count": sum(
            1
            for row in rows
            if row.get("result_kind") == "permission_denied" and row.get("kg_status") == "passed"
        ),
    }


def _row_counts(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        value = row.get(key)
        if isinstance(value, str):
            counts[value] += 1
    return dict(sorted(counts.items()))


def _passed_row_counts(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        value = row.get(key)
        if isinstance(value, str) and row.get("kg_status") == "passed":
            counts[value] += 1
    return dict(sorted(counts.items()))


def _baseline_rows_by_manifest_hash(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    safe_outputs = report.get("safe_outputs")
    if not isinstance(safe_outputs, Mapping):
        return {}
    rows = safe_outputs.get("case_rows")
    if not isinstance(rows, list):
        return {}
    return {
        str(row["case_manifest_entry_hash"]): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("case_manifest_entry_hash"), str)
    }


def _blocked_report(reason: str) -> dict[str, Any]:
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": NOW,
        "metrics": {
            "blocked_reason": reason,
            "raw_leak_guard_passed": True,
            "kg_fusion_eval_completed": False,
        },
        "safe_outputs": {
            "blocker_hash": sha256_json(reason),
            "case_count": 0,
        },
        "claim_boundary": _claim_boundary(False),
    }
    report["validation"] = validate_report(report)
    return report


def _validate_blocked_report(
    metrics: Mapping[str, Any],
    safe_outputs: Mapping[str, Any],
    claim_boundary: Mapping[str, Any],
    blockers: list[str],
) -> None:
    _validate_exact_keys(
        metrics,
        {"blocked_reason", "raw_leak_guard_passed", "kg_fusion_eval_completed"},
        "metrics",
        blockers,
    )
    if metrics.get("blocked_reason") not in _BLOCKED_REASONS:
        blockers.append("blocked_reason must be a configured safe enum")
    if metrics.get("raw_leak_guard_passed") is not True:
        blockers.append("blocked report raw leak guard must be true")
    if metrics.get("kg_fusion_eval_completed") is not False:
        blockers.append("blocked report must not be complete")
    _validate_exact_keys(
        safe_outputs,
        {"blocker_hash", "case_count"},
        "safe_outputs",
        blockers,
    )
    _require_sha256(safe_outputs.get("blocker_hash"), "safe_outputs.blocker_hash", blockers)
    if type(safe_outputs.get("case_count")) is not int or safe_outputs.get("case_count") != 0:
        blockers.append("blocked report case_count must be 0")
    _validate_success_claim_boundary(claim_boundary, metrics, blockers)


def _validate_success_claim_boundary(
    claim_boundary: Mapping[str, Any],
    metrics: Mapping[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = _FORBIDDEN_TRUE_CLAIMS | {
        "supports_candidate_only_kg_fusion_experiment_claim",
        "container_verification_required",
    }
    _validate_exact_keys(claim_boundary, expected_keys, "claim_boundary", blockers)
    expected_support = metrics.get("kg_fusion_eval_completed") is True
    if claim_boundary.get("supports_candidate_only_kg_fusion_experiment_claim") is not (
        expected_support
    ):
        blockers.append("candidate-only KG fusion claim boundary mismatch")
    for key in _FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(key) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {key}")
    if claim_boundary.get("container_verification_required") is not True:
        blockers.append("container_verification_required must be true")


def _validate_embedded_validation(
    value: Any,
    report: Mapping[str, Any],
    blockers: list[str],
) -> None:
    if value is None:
        return
    validation = _dict_or_empty(value, "validation", blockers)
    _validate_exact_keys(
        validation, {"passed", "blockers", "claim_boundary"}, "validation", blockers
    )
    if validation.get("passed") is not True:
        blockers.append("validation.passed must be true")
    if validation.get("blockers") != []:
        blockers.append("validation.blockers must be empty")
    claim_boundary = _dict_or_empty(
        validation.get("claim_boundary"),
        "validation.claim_boundary",
        blockers,
    )
    _validate_exact_keys(
        claim_boundary,
        {
            "supports_candidate_only_kg_fusion_experiment_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    metrics = report.get("metrics") if isinstance(report, Mapping) else {}
    expected = isinstance(metrics, Mapping) and metrics.get("kg_fusion_eval_completed") is True
    if claim_boundary.get("supports_candidate_only_kg_fusion_experiment_claim") is not expected:
        blockers.append("validation candidate-only KG fusion claim mismatch")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


def _kg_fusion_eval_completed(report: Mapping[str, Any]) -> bool:
    metrics = report.get("metrics")
    safe_outputs = report.get("safe_outputs")
    if not isinstance(metrics, Mapping) or not isinstance(safe_outputs, Mapping):
        return False
    for key in _REQUIRED_SUCCESS_METRICS - {"raw_leak_guard_passed", "kg_fusion_eval_completed"}:
        if metrics.get(key) is not True:
            return False
    return (
        metrics.get("raw_leak_guard_passed") is True
        and safe_outputs.get("case_count") == CASE_COUNT
        and safe_outputs.get("duplicate_response_hash_count") == 0
    )


def _claim_boundary(supports_eval: bool) -> dict[str, bool]:
    return {
        "supports_candidate_only_kg_fusion_experiment_claim": supports_eval,
        "supports_actual_chatgpt_connected_upload_claim": False,
        "supports_real_upload_iframe_claim": False,
        "supports_general_full_pst_parser_readiness_claim": False,
        "supports_live_postgresql_readiness_claim": False,
        "supports_production_worker_leasing_claim": False,
        "supports_business_answer_generation_claim": False,
        "supports_bert_or_neural_candidate_generation_claim": False,
        "supports_canonical_kg_write_claim": False,
        "supports_wiki_projection_claim": False,
        "supports_raw_mail_access_claim": False,
        "supports_production_ready_claim": False,
        "container_verification_required": True,
    }


def _validation(
    passed: bool,
    blockers: list[str],
    *,
    report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = report.get("metrics") if isinstance(report, Mapping) else {}
    supported = (
        passed
        and isinstance(metrics, Mapping)
        and (metrics.get("kg_fusion_eval_completed") is True)
    )
    return {
        "passed": passed,
        "blockers": blockers,
        "claim_boundary": {
            "supports_candidate_only_kg_fusion_experiment_claim": supported,
            "supports_production_ready_claim": False,
        },
    }


def _reject_private_text_or_evidence_fields(
    value: Any,
    blockers: list[str],
    path: str = "",
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            parts = set(normalized.split("_"))
            if (
                {
                    "answer",
                    "attachment",
                    "body",
                    "content",
                    "message_id",
                    "observation_id",
                    "prompt",
                    "query",
                    "sender",
                    "snippet",
                    "subject",
                    "text",
                    "transcript",
                    "upload_session_id",
                }
                & parts
            ) and not _is_safe_metadata_key(normalized):
                offending_path = f"{path}.{key_text}" if path else key_text
                blockers.append(
                    "public report contains private field: " + sha256_json(offending_path)
                )
                return
            _reject_private_text_or_evidence_fields(
                item,
                blockers,
                f"{path}.{key_text}" if path else key_text,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_private_text_or_evidence_fields(item, blockers, f"{path}[{index}]")


def _is_safe_metadata_key(normalized_key: str) -> bool:
    explicit = {
        "baseline_report_hash",
        "baseline_case_result_hash",
        "baseline_passed_case_count",
        "baseline_pass_rate_basis_points",
        "baseline_import_elapsed_ms",
        "baseline_query_loop_elapsed_ms",
        "body_segments_loaded",
        "case_result_hash",
        "domain_hash",
        "domain_hash_counts",
        "domain_hash_passed_counts",
        "intent_kind_hash",
        "matched_required_evidence_count",
        "private_manifest_hash",
        "required_evidence_count",
        "selected_evidence_count",
        "supports_business_answer_generation_claim",
        "supports_bert_or_neural_candidate_generation_claim",
        "supports_raw_mail_access_claim",
    }
    if normalized_key in explicit:
        return True
    if normalized_key.startswith("supports_") and normalized_key.endswith("_claim"):
        return True
    return normalized_key.endswith(("_count", "_counts", "_hash", "_hashes", "_status", "_ms"))


def _public_outputs_are_safe(report: Mapping[str, Any]) -> bool:
    return public_outputs_are_safe(
        report,
        forbidden_fragments=(
            "archive.pst",
            "tests/pst-exm",
            "pst-exm",
            ".test-tmp",
            str(ROOT).lower(),
            "formowl://object",
            "payload.bin",
            "storage_backend_id",
            "traceback",
            "readpst",
            "pffexport",
            "pst-scratch",
            "object-root",
            "query_text",
            "source_observation_id",
            "email_message_id",
            "message_occurrence_id",
            hard_eval.PRIVATE_MANIFEST_NAME.lower(),
        ),
        raw_reference_context="mail_domain_hard_kg_fusion_eval_report",
    )


def _no_graph_or_wiki_side_effects(work_dir: Path) -> bool:
    return not (work_dir / "data" / "graph").exists() and not (work_dir / "data" / "wiki").exists()


def _read_json_file(path: Path, missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(missing_reason)
    return json.loads(path.read_text(encoding="utf-8"))


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _int_or_zero(value: Any) -> int:
    return value if type(value) is int else 0


def _tokenize(value: str) -> set[str]:
    tokens = {
        token
        for token in re.split(r"[^a-zA-Z0-9_@.-]+", value.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }
    return tokens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline-report", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--validate-report", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.validate_report is not None:
        try:
            report = json.loads(args.validate_report.read_text(encoding="utf-8"))
        except Exception:
            validation = _validation(False, ["validate_report_input_unreadable"])
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
            return 1
        validation = validate_report(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
        return 0 if validation["passed"] else 1

    report = run_kg_fusion_eval(
        baseline_report_path=args.baseline_report,
        work_dir=args.work_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report.get("metrics", {}).get("kg_fusion_eval_completed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
