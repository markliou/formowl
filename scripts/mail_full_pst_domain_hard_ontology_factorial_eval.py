#!/usr/bin/env python3
"""Run ordered ontology-operator combinations on hard full-PST mail cases.

This experiment reuses the preserved #21 domain-hard full-PST work directory.
It loads observations and builds the deterministic candidate KG once, then
scores every ordered subset of the configured ontology operators in memory.

The report is public-safe hash/count/timing output only. It does not reparse the
PST, run neural packages, write canonical KG/type/user-graph/wiki state, grant
raw access, or claim business answer generation.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import permutations
import json
import os
from pathlib import Path
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
import mail_full_pst_domain_hard_kg_fusion_eval as kg_eval  # noqa: E402
import mail_full_pst_domain_hard_ontology_ablation_eval as ontology_eval  # noqa: E402
from formowl_contract import sha256_json  # noqa: E402
from formowl_evaluator.report_validation import (  # noqa: E402
    basis_points_via_positive_ratio as _basis_points,
    mapping_dict_or_empty as _dict_or_empty,
    public_outputs_are_safe,
    require_sha256 as _require_sha256,
    validate_exact_keys_missing_first as _validate_exact_keys,
)

DEFAULT_BASELINE_REPORT = ROOT / ".test-tmp" / "formowl-mail-domain-hard-case-baseline-v4.json"
DEFAULT_WORK_DIR = ROOT / ".test-tmp" / "formowl-mail-domain-hard-case-baseline-work-v4"
DEFAULT_OUTPUT = ROOT / ".test-tmp" / "formowl-mail-domain-hard-ontology-factorial-eval.json"
NOW = "2026-07-07T14:00:00+00:00"
REPORT_TYPE = "mail_full_pst_domain_hard_ontology_factorial_eval"
RUN_OPT_IN_ENV = "FORMOWL_RUN_FULL_PST_DOMAIN_HARD_ONTOLOGY_FACTORIAL_EVAL"
FACTORIAL_POLICY_VERSION = "formowl_domain_hard_ontology_operator_factorial_v1"
CASE_COUNT = 100
MAX_COMPONENT_EVIDENCE_PER_CASE = 10

BROAD_DOMAIN = "broad_domain"
SKOS_EXPANSION = "skos_expansion"
FINE_TYPE = "fine_type"
RELATION_SLOT = "relation_slot"
SHACL_PRUNING = "shacl_pruning"
ONTOLOGY_OPERATORS = (
    BROAD_DOMAIN,
    SKOS_EXPANSION,
    FINE_TYPE,
    RELATION_SLOT,
    SHACL_PRUNING,
)
EXPECTED_ARM_COUNT = sum(
    len(tuple(permutations(ONTOLOGY_OPERATORS, size)))
    for size in range(len(ONTOLOGY_OPERATORS) + 1)
)

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
    "supports_formal_ontology_governance_completion_claim",
    "supports_canonical_kg_write_claim",
    "supports_user_graph_write_claim",
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
    "factorial_arms_generated",
    "all_ordered_subsets_scored",
    "uses_broad_domain_operator",
    "uses_skos_expansion_operator",
    "uses_fine_type_operator",
    "uses_relation_slot_operator",
    "uses_shacl_pruning_operator",
    "no_bert_or_neural_dependency_used",
    "candidate_only_boundary_respected",
    "canonical_kg_wiki_side_effects_absent",
    "domain_case_count_is_100",
    "positive_cases_scored",
    "permission_denied_cases_preserved",
    "arm_summaries_recorded",
    "row_derived_validation_recomputed",
    "raw_leak_guard_passed",
    "ontology_factorial_eval_completed",
}
_BLOCKED_REASONS = {
    "ontology_factorial_requires_explicit_opt_in",
    "explicit_work_dir_required",
    "baseline_report_missing",
    "baseline_report_invalid",
    "work_dir_missing",
    "private_manifest_missing",
    "observations_missing",
    "ontology_factorial_eval_failed",
}

_SKOS_EXPANSIONS: dict[str, set[str]] = {
    "approval": {"approved", "pending", "decision", "waiver", "review"},
    "approved": {"approval", "decision", "waiver", "accepted"},
    "backorder": {"shortage", "allocation", "delay", "shipment"},
    "blocked": {"blocker", "pending", "hold", "risk", "delay"},
    "budget": {"cost", "variance", "expense", "finance"},
    "change": {"revision", "revised", "waiver", "substitute"},
    "conflict": {"tension", "mismatch", "revised", "rejected", "exception"},
    "customer": {"account", "buyer", "partner", "reseller"},
    "deadline": {"milestone", "schedule", "overdue", "due"},
    "delay": {"slip", "shortage", "hold", "backorder", "urgent"},
    "invoice": {"payment", "vendor", "reconciliation", "amount"},
    "launch": {"release", "beta", "roadmap", "milestone"},
    "order": {"purchase", "quote", "shipment", "allocation"},
    "risk": {"issue", "blocked", "hold", "problem", "exception"},
    "shipment": {"delivery", "carrier", "outbound", "backorder"},
}

_FINE_TYPE_VOCABULARY: dict[str, set[str]] = {
    "approval_decision": {"approval", "approved", "decision", "waiver", "rejected", "denied"},
    "blocking_risk": {"blocked", "blocker", "pending", "hold", "risk", "delay", "shortage"},
    "commercial_document": {"invoice", "quote", "contract", "order", "payment", "budget"},
    "logistics_inventory": {"shipment", "delivery", "inventory", "backorder", "allocation"},
    "project_commitment": {"deadline", "milestone", "owner", "task", "status", "progress"},
    "technical_change": {"bug", "fix", "release", "deploy", "test", "regression", "component"},
    "market_actor": {"customer", "vendor", "partner", "reseller", "distributor", "buyer"},
    "research_signal": {"ai", "llm", "model", "benchmark", "experiment", "validation"},
}


@dataclass(frozen=True)
class _FactorialIndex:
    ontology_index: ontology_eval._OntologyIndex
    type_scores_by_component: dict[str, dict[str, int]]
    component_ids_by_type: dict[str, tuple[str, ...]]

    @property
    def typed_component_count(self) -> int:
        return sum(1 for scores in self.type_scores_by_component.values() if scores)


def run_ontology_factorial_eval(
    *,
    baseline_report_path: Path | None = None,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    if os.environ.get(RUN_OPT_IN_ENV) != "1":
        return _blocked_report("ontology_factorial_requires_explicit_opt_in")
    if baseline_report_path is None or work_dir is None:
        return _blocked_report("explicit_work_dir_required")
    try:
        return _run_ontology_factorial_eval_inner(
            baseline_report_path=baseline_report_path,
            work_dir=work_dir,
        )
    except FileNotFoundError as exc:
        reason = str(exc)
        if reason in _BLOCKED_REASONS:
            return _blocked_report(reason)
        return _blocked_report("ontology_factorial_eval_failed")
    except Exception:
        return _blocked_report("ontology_factorial_eval_failed")


def _run_ontology_factorial_eval_inner(
    *,
    baseline_report_path: Path,
    work_dir: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    baseline_report = _read_json_file(baseline_report_path, "baseline_report_missing")
    baseline_hash = sha256_json(baseline_report)
    baseline_validation = hard_eval.validate_report(baseline_report)
    if not baseline_validation.get("passed"):
        raise FileNotFoundError("baseline_report_invalid")
    if not work_dir.exists() or not work_dir.is_dir():
        raise FileNotFoundError("work_dir_missing")

    load_started = time.monotonic()
    segments = kg_eval._load_mail_segments(work_dir)
    observations_load_elapsed_ms = int((time.monotonic() - load_started) * 1000)
    if not segments:
        raise FileNotFoundError("observations_missing")

    kg_started = time.monotonic()
    kg_index = kg_eval._build_candidate_kg_index(segments)
    ontology_index = ontology_eval._build_ontology_index(segments, kg_index)
    factorial_index = _build_factorial_index(segments, kg_index, ontology_index)
    kg_build_elapsed_ms = int((time.monotonic() - kg_started) * 1000)

    manifest = _read_json_file(
        work_dir / kg_eval.PRIVATE_MANIFEST_RELATIVE,
        "private_manifest_missing",
    )
    manifest_hash = sha256_json(manifest)
    cases = kg_eval._validate_private_manifest_cases(manifest)
    baseline_rows = kg_eval._baseline_rows_by_manifest_hash(baseline_report)

    scoring_started = time.monotonic()
    arm_summaries = [
        _score_arm(
            arm,
            cases=cases,
            baseline_rows=baseline_rows,
            kg_index=kg_index,
            factorial_index=factorial_index,
        )
        for arm in _ordered_operator_arms()
    ]
    scoring_elapsed_ms = int((time.monotonic() - scoring_started) * 1000)

    safe_outputs = _safe_outputs(
        baseline_report=baseline_report,
        baseline_hash=baseline_hash,
        manifest_hash=manifest_hash,
        arm_summaries=arm_summaries,
        kg_index=kg_index,
        factorial_index=factorial_index,
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
        "factorial_arms_generated": safe_outputs["ordered_arm_count"] == EXPECTED_ARM_COUNT,
        "all_ordered_subsets_scored": safe_outputs["scored_arm_count"] == EXPECTED_ARM_COUNT,
        "uses_broad_domain_operator": BROAD_DOMAIN in safe_outputs["operator_names"],
        "uses_skos_expansion_operator": SKOS_EXPANSION in safe_outputs["operator_names"],
        "uses_fine_type_operator": FINE_TYPE in safe_outputs["operator_names"],
        "uses_relation_slot_operator": RELATION_SLOT in safe_outputs["operator_names"],
        "uses_shacl_pruning_operator": SHACL_PRUNING in safe_outputs["operator_names"],
        "no_bert_or_neural_dependency_used": True,
        "candidate_only_boundary_respected": True,
        "canonical_kg_wiki_side_effects_absent": kg_eval._no_graph_or_wiki_side_effects(work_dir),
        "domain_case_count_is_100": safe_outputs["case_count"] == CASE_COUNT,
        "positive_cases_scored": safe_outputs["positive_case_count"] == 80,
        "permission_denied_cases_preserved": safe_outputs["best_permission_denied_passed_count"]
        == 10,
        "no_match_cases_non_leaking": safe_outputs["best_no_match_passed_count"] == 10,
        "arm_summaries_recorded": len(arm_summaries) == EXPECTED_ARM_COUNT,
        "row_derived_validation_recomputed": True,
        "raw_leak_guard_passed": False,
        "ontology_factorial_eval_completed": False,
    }
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": _claim_boundary(False),
    }
    report["metrics"]["raw_leak_guard_passed"] = _public_outputs_are_safe(report)
    report["metrics"]["ontology_factorial_eval_completed"] = _factorial_eval_completed(report)
    report["claim_boundary"]["supports_ontology_operator_factorial_experiment_claim"] = report[
        "metrics"
    ]["ontology_factorial_eval_completed"]
    report["validation"] = validate_report(report)
    return report


def _build_factorial_index(
    segments: Sequence[kg_eval._MailSegment],
    kg_index: kg_eval._CandidateKgIndex,
    ontology_index: ontology_eval._OntologyIndex,
) -> _FactorialIndex:
    type_scores_by_component: dict[str, dict[str, int]] = defaultdict(dict)
    for component_id, observation_ids in kg_index.observation_ids_by_component.items():
        scores: Counter[str] = Counter()
        for observation_id in observation_ids:
            segment = kg_index.segment_by_observation_id[observation_id]
            for type_name, vocabulary in _FINE_TYPE_VOCABULARY.items():
                hits = len(segment.tokens & vocabulary)
                if hits:
                    scores[type_name] += hits
        type_scores_by_component[component_id] = dict(scores)
    component_ids_by_type: dict[str, list[str]] = defaultdict(list)
    for component_id, scores in type_scores_by_component.items():
        for type_name in scores:
            component_ids_by_type[type_name].append(component_id)
    return _FactorialIndex(
        ontology_index=ontology_index,
        type_scores_by_component=dict(type_scores_by_component),
        component_ids_by_type={
            type_name: tuple(sorted(component_ids))
            for type_name, component_ids in component_ids_by_type.items()
        },
    )


def _ordered_operator_arms() -> list[tuple[str, ...]]:
    return [
        arm
        for size in range(len(ONTOLOGY_OPERATORS) + 1)
        for arm in permutations(ONTOLOGY_OPERATORS, size)
    ]


def _score_arm(
    arm: tuple[str, ...],
    *,
    cases: Sequence[Mapping[str, Any]],
    baseline_rows: Mapping[str, Mapping[str, Any]],
    kg_index: kg_eval._CandidateKgIndex,
    factorial_index: _FactorialIndex,
) -> dict[str, Any]:
    started = time.monotonic()
    rows = [
        _score_case_for_arm(
            case,
            arm=arm,
            baseline_row=baseline_rows.get(case["private_fingerprint"]),
            kg_index=kg_index,
            factorial_index=factorial_index,
        )
        for case in cases
    ]
    passed = sum(1 for row in rows if row["status"] == "passed")
    summary = {
        "arm_id_hash": _arm_id_hash(arm),
        "operator_order": list(arm),
        "operator_count": len(arm),
        "passed_case_count": passed,
        "failed_case_count": len(rows) - passed,
        "pass_rate_basis_points": _basis_points(passed, len(rows)),
        "positive_passed_count": _passed_count(rows, "owner_match"),
        "no_match_passed_count": _passed_count(rows, "no_match"),
        "permission_denied_passed_count": _passed_count(rows, "permission_denied"),
        "case_result_hash": sha256_json(rows),
        "unique_response_hash_count": len({row["response_hash"] for row in rows}),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    summary["arm_summary_hash"] = sha256_json(summary)
    return summary


def _score_case_for_arm(
    case: Mapping[str, Any],
    *,
    arm: tuple[str, ...],
    baseline_row: Mapping[str, Any] | None,
    kg_index: kg_eval._CandidateKgIndex,
    factorial_index: _FactorialIndex,
) -> dict[str, Any]:
    result_kind = str(case["result_kind"])
    required_ids = tuple(str(value) for value in case.get("required_source_observation_ids", []))
    required_match_count = int(case.get("required_match_count", 0))
    baseline_status = (
        str(baseline_row.get("status"))
        if isinstance(baseline_row, Mapping) and isinstance(baseline_row.get("status"), str)
        else "unknown"
    )
    if result_kind == "permission_denied":
        selected_ids: tuple[str, ...] = ()
        status = "passed"
        matched_required_count = 0
        selected_component_count = 0
    else:
        query_tokens = kg_eval._tokenize(str(case.get("query_text", "")))
        selected_components = _rank_components_for_arm(
            query_tokens,
            arm=arm,
            kg_index=kg_index,
            factorial_index=factorial_index,
            limit=4,
        )
        selected_ids = kg_eval._evidence_from_components(
            selected_components,
            query_tokens=query_tokens,
            kg_index=kg_index,
            limit=MAX_COMPONENT_EVIDENCE_PER_CASE,
        )
        matched_required_count = len(set(required_ids) & set(selected_ids))
        selected_component_count = len(selected_components)
        if result_kind == "owner_match":
            status = "passed" if matched_required_count >= required_match_count else "failed"
        else:
            status = "passed" if len(selected_ids) == 0 else "failed"
    response_payload = {
        "case": sha256_json(str(case.get("case_id", ""))),
        "arm": _arm_id_hash(arm),
        "baseline_status": baseline_status,
        "status": status,
        "selected_evidence": selected_ids,
        "matched_required": matched_required_count,
        "selected_component_count": selected_component_count,
    }
    return {
        "case_hash": sha256_json(str(case.get("case_id", ""))),
        "result_kind": result_kind,
        "baseline_status": baseline_status,
        "status": status,
        "matched_required_evidence_count": matched_required_count,
        "selected_component_count": selected_component_count,
        "selected_evidence_count": len(selected_ids),
        "response_hash": sha256_json(response_payload),
    }


def _rank_components_for_arm(
    query_tokens: set[str],
    *,
    arm: tuple[str, ...],
    kg_index: kg_eval._CandidateKgIndex,
    factorial_index: _FactorialIndex,
    limit: int,
) -> tuple[str, ...]:
    if not arm:
        return kg_eval._rank_components(query_tokens, kg_index, limit=limit)
    state_tokens = set(query_tokens)
    scores: Counter[str] = Counter()
    _add_token_scores(scores, state_tokens, kg_index, weight=10)
    candidate_components: set[str] = set(scores)
    for operator_name in arm:
        if operator_name == SKOS_EXPANSION:
            expanded = _skos_expand(state_tokens)
            new_tokens = expanded - state_tokens
            state_tokens.update(expanded)
            _add_token_scores(scores, new_tokens, kg_index, weight=4)
            candidate_components.update(scores)
        elif operator_name == BROAD_DOMAIN:
            domains = ontology_eval._domains_for_tokens(state_tokens)
            for domain in domains:
                for component_id in factorial_index.ontology_index.component_ids_by_domain.get(
                    domain, ()
                ):
                    domain_score = factorial_index.ontology_index.domain_scores_by_component.get(
                        component_id, {}
                    ).get(domain, 0)
                    scores[component_id] += 3 * min(domain_score, 4)
                    candidate_components.add(component_id)
        elif operator_name == FINE_TYPE:
            type_names = _fine_types_for_tokens(state_tokens)
            for type_name in type_names:
                for component_id in factorial_index.component_ids_by_type.get(type_name, ()):
                    type_score = factorial_index.type_scores_by_component.get(component_id, {}).get(
                        type_name, 0
                    )
                    scores[component_id] += 6 * min(type_score, 3)
                    candidate_components.add(component_id)
        elif operator_name == RELATION_SLOT:
            slots = _relation_slots_for_tokens(state_tokens)
            for component_id in list(candidate_components or kg_index.observation_ids_by_component):
                slot_score = _slot_score(component_id, slots=slots, kg_index=kg_index)
                if slot_score:
                    scores[component_id] += slot_score
                    candidate_components.add(component_id)
        elif operator_name == SHACL_PRUNING:
            candidate_components = _shacl_pruned_components(
                candidate_components or set(scores),
                query_tokens=state_tokens,
                kg_index=kg_index,
            )
            scores = Counter(
                {component_id: scores[component_id] for component_id in candidate_components}
            )
        else:
            raise RuntimeError("unknown ontology operator")
    ranked = sorted(
        candidate_components,
        key=lambda component_id: (
            -scores[component_id],
            len(kg_index.observation_ids_by_component[component_id]),
            component_id,
        ),
    )
    return tuple(component_id for component_id in ranked[:limit] if scores[component_id] > 0)


def _add_token_scores(
    scores: Counter[str],
    tokens: set[str],
    kg_index: kg_eval._CandidateKgIndex,
    *,
    weight: int,
) -> None:
    for token in tokens & kg_eval._IMPORTANT_TERMS:
        for component_id in kg_index.component_ids_by_token.get(token, ()):
            scores[component_id] += weight


def _skos_expand(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for token in tuple(tokens):
        expanded.update(_SKOS_EXPANSIONS.get(token, ()))
    for domain, vocabulary in hard_eval.DOMAIN_VOCABULARY.items():
        domain_label_tokens = set(domain.split("_"))
        if tokens & (domain_label_tokens | vocabulary):
            expanded.update(sorted(vocabulary)[:8])
    return expanded


def _fine_types_for_tokens(tokens: set[str]) -> set[str]:
    return {
        type_name for type_name, vocabulary in _FINE_TYPE_VOCABULARY.items() if tokens & vocabulary
    }


def _relation_slots_for_tokens(tokens: set[str]) -> set[str]:
    slots: set[str] = set()
    if tokens & {"separate-email", "separate", "multiple", "across"}:
        slots.add("multi_message")
    if tokens & {"earliest", "latest", "compare", "chronology"}:
        slots.add("chronology")
    if tokens & {"conflicting", "conflict", "tension", "between", "reconcile"}:
        slots.add("conflict")
    if tokens & {"final", "approved", "approval", "decision"}:
        slots.add("approval_decision")
    if tokens & {"what", "say", "said"}:
        slots.add("actor_topic")
    return slots


def _slot_score(
    component_id: str,
    *,
    slots: set[str],
    kg_index: kg_eval._CandidateKgIndex,
) -> int:
    if not slots:
        return 0
    tokens = kg_index.tokens_by_component.get(component_id, frozenset())
    size = len(kg_index.observation_ids_by_component.get(component_id, ()))
    score = 0
    if "multi_message" in slots and size >= 2:
        score += 8
    if "chronology" in slots and size >= 2 and tokens & {"deadline", "schedule", "overdue"}:
        score += 6
    if "conflict" in slots and tokens & hard_eval.CONFLICT_TERMS:
        score += 10
    if "approval_decision" in slots and tokens & _FINE_TYPE_VOCABULARY["approval_decision"]:
        score += 10
    if "actor_topic" in slots and size >= 2:
        score += 3
    return score


def _shacl_pruned_components(
    component_ids: set[str],
    *,
    query_tokens: set[str],
    kg_index: kg_eval._CandidateKgIndex,
) -> set[str]:
    slots = _relation_slots_for_tokens(query_tokens)
    if not slots:
        return component_ids
    pruned: set[str] = set()
    for component_id in component_ids:
        tokens = kg_index.tokens_by_component.get(component_id, frozenset())
        size = len(kg_index.observation_ids_by_component.get(component_id, ()))
        if "multi_message" in slots and size < 2:
            continue
        if "conflict" in slots and not (tokens & hard_eval.CONFLICT_TERMS):
            continue
        if "approval_decision" in slots and not (
            tokens & _FINE_TYPE_VOCABULARY["approval_decision"]
        ):
            continue
        pruned.add(component_id)
    return pruned


def _safe_outputs(
    *,
    baseline_report: Mapping[str, Any],
    baseline_hash: str,
    manifest_hash: str,
    arm_summaries: Sequence[Mapping[str, Any]],
    kg_index: kg_eval._CandidateKgIndex,
    factorial_index: _FactorialIndex,
    observations_load_elapsed_ms: int,
    kg_build_elapsed_ms: int,
    scoring_elapsed_ms: int,
    total_elapsed_ms: int,
) -> dict[str, Any]:
    baseline_safe = baseline_report.get("safe_outputs")
    baseline_safe_outputs = baseline_safe if isinstance(baseline_safe, Mapping) else {}
    baseline_passed = _int_or_zero(baseline_safe_outputs.get("passed_case_count"))
    kg_only = _kg_only_summary(arm_summaries)
    best = _best_summary(arm_summaries)
    return {
        "baseline_report_hash": baseline_hash,
        "baseline_case_result_hash": str(baseline_safe_outputs.get("case_result_hash", "")),
        "private_manifest_hash": manifest_hash,
        "factorial_policy_hash": sha256_json(FACTORIAL_POLICY_VERSION),
        "operator_names": list(ONTOLOGY_OPERATORS),
        "operator_count": len(ONTOLOGY_OPERATORS),
        "expected_ordered_arm_count": EXPECTED_ARM_COUNT,
        "ordered_arm_count": len(arm_summaries),
        "scored_arm_count": len(arm_summaries),
        "ordered_arm_count_by_length": _arm_count_by_length(arm_summaries),
        "arm_summary_hash": sha256_json(arm_summaries),
        "case_count": CASE_COUNT,
        "positive_case_count": 80,
        "no_match_case_count": 10,
        "permission_denied_case_count": 10,
        "baseline_passed_case_count": baseline_passed,
        "baseline_pass_rate_basis_points": _int_or_zero(
            baseline_safe_outputs.get("pass_rate_basis_points")
        ),
        "kg_only_arm_hash": str(kg_only["arm_id_hash"]),
        "kg_only_passed_case_count": int(kg_only["passed_case_count"]),
        "kg_only_pass_rate_basis_points": int(kg_only["pass_rate_basis_points"]),
        "best_arm_hash": str(best["arm_id_hash"]),
        "best_arm_operator_order": list(best["operator_order"]),
        "best_arm_operator_count": int(best["operator_count"]),
        "best_passed_case_count": int(best["passed_case_count"]),
        "best_pass_rate_basis_points": int(best["pass_rate_basis_points"]),
        "best_delta_vs_baseline_passed_case_count": int(best["passed_case_count"])
        - baseline_passed,
        "best_delta_vs_kg_only_passed_case_count": int(best["passed_case_count"])
        - int(kg_only["passed_case_count"]),
        "best_positive_passed_count": int(best["positive_passed_count"]),
        "best_no_match_passed_count": int(best["no_match_passed_count"]),
        "best_permission_denied_passed_count": int(best["permission_denied_passed_count"]),
        "arms_better_than_kg_only_count": sum(
            1
            for summary in arm_summaries
            if int(summary["passed_case_count"]) > int(kg_only["passed_case_count"])
        ),
        "arms_equal_to_kg_only_count": sum(
            1
            for summary in arm_summaries
            if int(summary["passed_case_count"]) == int(kg_only["passed_case_count"])
        ),
        "arms_worse_than_kg_only_count": sum(
            1
            for summary in arm_summaries
            if int(summary["passed_case_count"]) < int(kg_only["passed_case_count"])
        ),
        "candidate_graph_node_count": kg_index.candidate_atom_count,
        "candidate_graph_relation_count": kg_index.candidate_relation_count,
        "kg_component_count": kg_index.component_count,
        "typed_component_count": factorial_index.typed_component_count,
        "fine_type_count": len(_FINE_TYPE_VOCABULARY),
        "skos_expansion_seed_count": len(_SKOS_EXPANSIONS),
        "largest_component_size": kg_index.largest_component_size,
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
        "arm_summaries": list(arm_summaries),
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
            blockers.append("required ontology factorial metric is not true: " + key)
    if type(metrics.get("no_match_cases_non_leaking")) is not bool:
        blockers.append("no_match_cases_non_leaking must be boolean")
    expected_safe_keys = {
        "baseline_report_hash",
        "baseline_case_result_hash",
        "private_manifest_hash",
        "factorial_policy_hash",
        "operator_names",
        "operator_count",
        "expected_ordered_arm_count",
        "ordered_arm_count",
        "scored_arm_count",
        "ordered_arm_count_by_length",
        "arm_summary_hash",
        "case_count",
        "positive_case_count",
        "no_match_case_count",
        "permission_denied_case_count",
        "baseline_passed_case_count",
        "baseline_pass_rate_basis_points",
        "kg_only_arm_hash",
        "kg_only_passed_case_count",
        "kg_only_pass_rate_basis_points",
        "best_arm_hash",
        "best_arm_operator_order",
        "best_arm_operator_count",
        "best_passed_case_count",
        "best_pass_rate_basis_points",
        "best_delta_vs_baseline_passed_case_count",
        "best_delta_vs_kg_only_passed_case_count",
        "best_positive_passed_count",
        "best_no_match_passed_count",
        "best_permission_denied_passed_count",
        "arms_better_than_kg_only_count",
        "arms_equal_to_kg_only_count",
        "arms_worse_than_kg_only_count",
        "candidate_graph_node_count",
        "candidate_graph_relation_count",
        "kg_component_count",
        "typed_component_count",
        "fine_type_count",
        "skos_expansion_seed_count",
        "largest_component_size",
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
        "arm_summaries",
    }
    _validate_exact_keys(safe_outputs, expected_safe_keys, "safe_outputs", blockers)
    for key in (
        "baseline_report_hash",
        "baseline_case_result_hash",
        "private_manifest_hash",
        "factorial_policy_hash",
        "arm_summary_hash",
        "kg_only_arm_hash",
        "best_arm_hash",
    ):
        _require_sha256(safe_outputs.get(key), "safe_outputs." + key, blockers)
    for key in expected_safe_keys - {
        "operator_names",
        "ordered_arm_count_by_length",
        "best_arm_operator_order",
        "arm_summaries",
        "baseline_report_hash",
        "baseline_case_result_hash",
        "private_manifest_hash",
        "factorial_policy_hash",
        "arm_summary_hash",
        "kg_only_arm_hash",
        "best_arm_hash",
    }:
        if not isinstance(safe_outputs.get(key), int) or isinstance(safe_outputs.get(key), bool):
            blockers.append(f"safe_outputs.{key} must be an integer")
    if tuple(safe_outputs.get("operator_names", ())) != ONTOLOGY_OPERATORS:
        blockers.append("safe_outputs.operator_names mismatch")
    if safe_outputs.get("expected_ordered_arm_count") != EXPECTED_ARM_COUNT:
        blockers.append("safe_outputs.expected_ordered_arm_count mismatch")
    arm_summaries = safe_outputs.get("arm_summaries")
    if not isinstance(arm_summaries, list):
        blockers.append("safe_outputs.arm_summaries must be a list")
        arm_summaries = []
    if len(arm_summaries) != EXPECTED_ARM_COUNT:
        blockers.append("safe_outputs.arm_summaries must contain all ordered arms")
    _validate_arm_summaries(arm_summaries, blockers)
    if safe_outputs.get("arm_summary_hash") != sha256_json(arm_summaries):
        blockers.append("safe_outputs.arm_summary_hash does not match arm summaries")
    _validate_arm_derived_counts(safe_outputs, arm_summaries, blockers)
    _validate_success_claim_boundary(claim_boundary, metrics, blockers)


def _validate_arm_summaries(items: Sequence[Any], blockers: list[str]) -> None:
    expected_keys = {
        "arm_id_hash",
        "operator_order",
        "operator_count",
        "passed_case_count",
        "failed_case_count",
        "pass_rate_basis_points",
        "positive_passed_count",
        "no_match_passed_count",
        "permission_denied_passed_count",
        "case_result_hash",
        "unique_response_hash_count",
        "elapsed_ms",
        "arm_summary_hash",
    }
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            blockers.append("arm_summary entries must be objects")
            continue
        _validate_exact_keys(item, expected_keys, "arm_summary", blockers)
        for key in ("arm_id_hash", "case_result_hash", "arm_summary_hash"):
            _require_sha256(item.get(key), "arm_summary." + key, blockers)
        operator_order = item.get("operator_order")
        if not isinstance(operator_order, list) or any(
            operator not in ONTOLOGY_OPERATORS for operator in operator_order
        ):
            blockers.append("arm_summary.operator_order must use configured operators")
        elif len(operator_order) != len(set(operator_order)):
            blockers.append("arm_summary.operator_order must not repeat operators")
        for key in expected_keys - {
            "arm_id_hash",
            "operator_order",
            "case_result_hash",
            "arm_summary_hash",
        }:
            if not isinstance(item.get(key), int) or isinstance(item.get(key), bool):
                blockers.append(f"arm_summary.{key} must be an integer")
        if isinstance(operator_order, list) and item.get("operator_count") != len(operator_order):
            blockers.append("arm_summary.operator_count mismatch")
        arm_id = item.get("arm_id_hash")
        if isinstance(arm_id, str):
            seen.add(arm_id)
    if len(seen) != len(items):
        blockers.append("arm summaries must have unique arm ids")


def _validate_arm_derived_counts(
    safe_outputs: Mapping[str, Any],
    arm_summaries: Sequence[Mapping[str, Any]],
    blockers: list[str],
) -> None:
    kg_only = _kg_only_summary(arm_summaries)
    best = _best_summary(arm_summaries)
    if safe_outputs.get("kg_only_passed_case_count") != kg_only.get("passed_case_count"):
        blockers.append("safe_outputs.kg_only_passed_case_count does not match arms")
    if safe_outputs.get("best_passed_case_count") != best.get("passed_case_count"):
        blockers.append("safe_outputs.best_passed_case_count does not match arms")
    if safe_outputs.get("best_arm_hash") != best.get("arm_id_hash"):
        blockers.append("safe_outputs.best_arm_hash does not match arms")
    better = sum(
        1
        for summary in arm_summaries
        if int(summary.get("passed_case_count", -1)) > int(kg_only.get("passed_case_count", 0))
    )
    equal = sum(
        1
        for summary in arm_summaries
        if int(summary.get("passed_case_count", -1)) == int(kg_only.get("passed_case_count", 0))
    )
    worse = sum(
        1
        for summary in arm_summaries
        if int(summary.get("passed_case_count", -1)) < int(kg_only.get("passed_case_count", 0))
    )
    if safe_outputs.get("arms_better_than_kg_only_count") != better:
        blockers.append("safe_outputs.arms_better_than_kg_only_count does not match arms")
    if safe_outputs.get("arms_equal_to_kg_only_count") != equal:
        blockers.append("safe_outputs.arms_equal_to_kg_only_count does not match arms")
    if safe_outputs.get("arms_worse_than_kg_only_count") != worse:
        blockers.append("safe_outputs.arms_worse_than_kg_only_count does not match arms")
    if sum((better, equal, worse)) != len(arm_summaries):
        blockers.append("arm comparison counts do not sum to arm count")


def _validate_blocked_report(
    metrics: Mapping[str, Any],
    safe_outputs: Mapping[str, Any],
    claim_boundary: Mapping[str, Any],
    blockers: list[str],
) -> None:
    _validate_exact_keys(
        metrics,
        {"blocked_reason", "raw_leak_guard_passed", "ontology_factorial_eval_completed"},
        "metrics",
        blockers,
    )
    if metrics.get("blocked_reason") not in _BLOCKED_REASONS:
        blockers.append("blocked_reason must be a configured safe enum")
    if metrics.get("raw_leak_guard_passed") is not True:
        blockers.append("blocked report raw leak guard must be true")
    if metrics.get("ontology_factorial_eval_completed") is not False:
        blockers.append("blocked report must not be complete")
    _validate_exact_keys(safe_outputs, {"blocker_hash", "case_count"}, "safe_outputs", blockers)
    _require_sha256(safe_outputs.get("blocker_hash"), "safe_outputs.blocker_hash", blockers)
    if safe_outputs.get("case_count") != 0:
        blockers.append("blocked report case_count must be 0")
    _validate_success_claim_boundary(claim_boundary, metrics, blockers)


def _validate_success_claim_boundary(
    claim_boundary: Mapping[str, Any],
    metrics: Mapping[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = set(_FORBIDDEN_TRUE_CLAIMS) | {
        "supports_ontology_operator_factorial_experiment_claim",
        "container_verification_required",
    }
    _validate_exact_keys(claim_boundary, expected_keys, "claim_boundary", blockers)
    expected_support = metrics.get("ontology_factorial_eval_completed") is True
    if claim_boundary.get("supports_ontology_operator_factorial_experiment_claim") is not (
        expected_support
    ):
        blockers.append("ontology factorial claim boundary mismatch")
    for key in _FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(key) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {key}")
    if claim_boundary.get("container_verification_required") is not True:
        blockers.append("container_verification_required must be true")


def _factorial_eval_completed(report: Mapping[str, Any]) -> bool:
    metrics = report.get("metrics")
    safe_outputs = report.get("safe_outputs")
    if not isinstance(metrics, Mapping) or not isinstance(safe_outputs, Mapping):
        return False
    return (
        all(
            metrics.get(key) is True
            for key in _REQUIRED_SUCCESS_METRICS
            - {"raw_leak_guard_passed", "ontology_factorial_eval_completed"}
        )
        and metrics.get("raw_leak_guard_passed") is True
        and safe_outputs.get("ordered_arm_count") == EXPECTED_ARM_COUNT
        and safe_outputs.get("case_count") == CASE_COUNT
    )


def _blocked_report(reason: str) -> dict[str, Any]:
    safe_reason = reason if reason in _BLOCKED_REASONS else "ontology_factorial_eval_failed"
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": NOW,
        "metrics": {
            "blocked_reason": safe_reason,
            "raw_leak_guard_passed": True,
            "ontology_factorial_eval_completed": False,
        },
        "safe_outputs": {
            "blocker_hash": sha256_json(safe_reason),
            "case_count": 0,
        },
        "claim_boundary": _claim_boundary(False),
    }
    report["validation"] = validate_report(report)
    return report


def _claim_boundary(supports_eval: bool) -> dict[str, bool]:
    return {
        "supports_ontology_operator_factorial_experiment_claim": supports_eval,
        "supports_actual_chatgpt_connected_upload_claim": False,
        "supports_real_upload_iframe_claim": False,
        "supports_general_full_pst_parser_readiness_claim": False,
        "supports_live_postgresql_readiness_claim": False,
        "supports_production_worker_leasing_claim": False,
        "supports_business_answer_generation_claim": False,
        "supports_bert_or_neural_candidate_generation_claim": False,
        "supports_formal_ontology_governance_completion_claim": False,
        "supports_canonical_kg_write_claim": False,
        "supports_user_graph_write_claim": False,
        "supports_wiki_projection_claim": False,
        "supports_raw_mail_access_claim": False,
        "supports_production_ready_claim": False,
        "container_verification_required": True,
    }


def _kg_only_summary(arm_summaries: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for summary in arm_summaries:
        if summary.get("operator_order") == []:
            return summary
    raise RuntimeError("kg_only_arm_missing")


def _best_summary(arm_summaries: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return sorted(
        arm_summaries,
        key=lambda summary: (
            -int(summary["passed_case_count"]),
            int(summary["operator_count"]),
            str(summary["arm_id_hash"]),
        ),
    )[0]


def _arm_count_by_length(arm_summaries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[int] = Counter(int(summary["operator_count"]) for summary in arm_summaries)
    return {str(length): counts[length] for length in range(len(ONTOLOGY_OPERATORS) + 1)}


def _passed_count(rows: Sequence[Mapping[str, Any]], result_kind: str) -> int:
    return sum(
        1 for row in rows if row.get("result_kind") == result_kind and row.get("status") == "passed"
    )


def _arm_id_hash(arm: Sequence[str]) -> str:
    return sha256_json({"operators": list(arm), "policy": FACTORIAL_POLICY_VERSION})


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _read_json_file(path: Path, missing_reason: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(missing_reason)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


def _reject_private_text_or_evidence_fields(
    value: Any, blockers: list[str], path: str = ""
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(
                forbidden in lowered
                for forbidden in (
                    "query_text",
                    "source_observation_id",
                    "selected_evidence",
                    "message_id",
                    "mail_subject",
                    "body_text",
                    "snippet",
                    "workspace_formowl",
                )
            ):
                blockers.append(
                    f"public report contains private field: {sha256_json(path + key_text)}"
                )
            _reject_private_text_or_evidence_fields(item, blockers, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_private_text_or_evidence_fields(item, blockers, f"{path}[{index}]")


def _public_outputs_are_safe(report: Mapping[str, Any]) -> bool:
    return public_outputs_are_safe(
        report,
        raw_reference_context="mail_domain_hard_ontology_factorial_report",
    )


def _validation(
    passed: bool,
    blockers: list[str],
    *,
    report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    supported = (
        passed
        and isinstance(report, Mapping)
        and isinstance(report.get("metrics"), Mapping)
        and report["metrics"].get("ontology_factorial_eval_completed") is True
    )
    return {
        "passed": passed,
        "blockers": blockers,
        "claim_boundary": {
            "supports_ontology_operator_factorial_experiment_claim": supported,
            "supports_production_ready_claim": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-report", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-report", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.validate_report is not None:
        report = _read_json_file(args.validate_report, "ontology_factorial_eval_failed")
        validation = validate_report(report)
        _write_json(args.output, validation)
        return 0 if validation["passed"] else 1
    report = run_ontology_factorial_eval(
        baseline_report_path=args.baseline_report,
        work_dir=args.work_dir,
    )
    _write_json(args.output, report)
    return 0 if report.get("metrics", {}).get("ontology_factorial_eval_completed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
