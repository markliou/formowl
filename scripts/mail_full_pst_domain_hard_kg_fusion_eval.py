#!/usr/bin/env python3
"""Run or validate the default Candidate evidence retrieval hardness harness.

The legacy filename is retained for compatibility, but the active method is not
the old lexical/thread component KG. This harness reuses an existing
hard-domain full-PST work directory, onboards the exact source-neutral
Candidate evidence contract, and does not reparse the PST or run neural
inference. The private manifest may contain query text and observation ids; the
public report is hash/status/count/timing only.

Measured path:

preserved full-PST observations + private hard-case manifest
-> source-neutral candidate evidence records
-> bounded proof-neighborhood query planning
-> 100 hard-domain case coverage scores.

The output measures logical-source retrieval and citation behavior. It is not
business answer generation, a canonical KG/write, or a wiki projection claim.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts"
PYTHON_ROOT = ROOT / "python"
for import_path in (PYTHON_ROOT, SCRIPT_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import mail_full_pst_domain_hard_case_eval as hard_eval  # noqa: E402
import mail_full_pst_exm_lexical_ontology_eval as lexical_eval  # noqa: E402
from formowl_contract import sha256_json, stable_resource_contract_id  # noqa: E402
from formowl_evaluator.report_validation import (  # noqa: E402
    mapping_dict_or_empty as _dict_or_empty,
    public_outputs_are_safe,
    require_sha256 as _require_sha256,
    validate_exact_keys as _validate_exact_keys,
)
from formowl_graph.candidate_retrieval import (  # noqa: E402
    DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID,
    CandidateEvidenceAccessBinding,
    CandidateEvidenceIndex,
    CandidateEvidenceRecord,
    CandidateEvidenceTextPolicyBinding,
    CandidateEvidenceTextPolicyRuntime,
    candidate_evidence_tokenizer_implementation_hash,
    build_default_candidate_evidence_harness_contract,
    infer_evidence_ontology_signals,
    require_default_candidate_evidence_harness_contract,
)

DEFAULT_BASELINE_REPORT = ROOT / ".test-tmp" / "formowl-mail-domain-hard-case-baseline-v4.json"
DEFAULT_WORK_DIR = ROOT / ".test-tmp" / "formowl-mail-domain-hard-case-baseline-work-v4"
DEFAULT_OUTPUT = ROOT / ".test-tmp" / "formowl-mail-domain-hard-kg-fusion-eval.json"
PRIVATE_MANIFEST_RELATIVE = Path("artifacts") / hard_eval.PRIVATE_MANIFEST_NAME
NOW = "2026-07-07T12:30:00+00:00"
REPORT_TYPE = "mail_full_pst_domain_hard_kg_fusion_eval"
KG_POLICY_VERSION = DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID
HARNESS_CONTRACT = build_default_candidate_evidence_harness_contract()
require_default_candidate_evidence_harness_contract(HARNESS_CONTRACT)
NORMALIZATION_POLICY_VERSION = "unicode_nfkc_v1"
RUN_OPT_IN_ENV = "FORMOWL_RUN_FULL_PST_DOMAIN_HARD_KG_FUSION_EVAL"
CASE_COUNT = 100
MAX_COMPONENT_EVIDENCE_PER_CASE = 10
EVIDENCE_BUDGET = 5
EMAIL_SOURCE_IDENTITY_POLICY_ID = "email_message_fingerprint_then_message_or_occurrence_v1"
EVIDENCE_ONTOLOGY_REVISION_ID = "ontology_revision_source_neutral_evidence_facets_v2"
_EVIDENCE_ONTOLOGY_SIGNALS = frozenset(
    {
        "actor_attributed_evidence",
        "artifact_evidence",
        "audio_visual_evidence",
        "concept_evidence",
        "document_evidence",
        "event_evidence",
        "image_evidence",
        "measurement_bearing_evidence",
        "structured_record_evidence",
        "temporally_ordered_evidence",
    }
)
EVIDENCE_ONTOLOGY_SIGNAL_VOCABULARY_HASH = sha256_json(sorted(_EVIDENCE_ONTOLOGY_SIGNALS))
_CORE_COORDINATION_TERMS = frozenset(
    {
        "approval",
        "approved",
        "blocked",
        "cancel",
        "cancelled",
        "change",
        "conflict",
        "decision",
        "delay",
        "denied",
        "exception",
        "fail",
        "failed",
        "final",
        "fixed",
        "hold",
        "issue",
        "pending",
        "problem",
        "reject",
        "rejected",
        "revised",
        "risk",
        "shortage",
        "slip",
        "urgent",
        "waiver",
    }
)

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
    "baseline_manifest_binding_validated",
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
    "baseline_manifest_binding_mismatch",
    "work_dir_missing",
    "private_manifest_missing",
    "private_manifest_logical_source_gold_missing",
    "observations_missing",
    "permission_scope_missing",
    "knowledge_time_missing",
    "stable_source_identity_missing",
    "external_segmenters_required",
    "kg_fusion_eval_failed",
}


@dataclass(frozen=True)
class _MailSegment:
    observation_id: str
    source_item_id: str
    source_identity_policy_id: str
    source_version_id: str
    permission_scope_id: str
    thread_id: str | None
    message_occurrence_id: str | None
    message_id: str | None
    searchable_text: str
    actor_text: str
    observed_at: str | None
    known_at: str
    observation_type: str
    modality: str | None
    semantic_roles: frozenset[str]
    tokens: frozenset[str]
    actor_tokens: frozenset[str]
    ontology_signals: frozenset[str]


@dataclass(frozen=True)
class _CandidateKgIndex:
    segmenters: Any
    compiled_policy: Any
    text_policy_runtime: CandidateEvidenceTextPolicyRuntime
    evidence_index: CandidateEvidenceIndex
    evaluation_context_id: str
    known_as_of: str
    as_of_world_time: str
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
    def tokenizer_binding_hash(self) -> str:
        return self.text_policy_runtime.binding.binding_hash

    @property
    def text_policy_binding(self) -> CandidateEvidenceTextPolicyBinding:
        return self.text_policy_runtime.binding

    @property
    def component_count(self) -> int:
        return len(self.observation_ids_by_component)

    @property
    def largest_component_size(self) -> int:
        if not self.observation_ids_by_component:
            return 0
        return max(len(items) for items in self.observation_ids_by_component.values())


@dataclass(frozen=True)
class _SelectionScore:
    status: str
    required_observation_count: int
    matched_required_observation_count: int
    unmapped_required_observation_count: int
    required_source_item_count: int
    required_source_item_match_threshold: int
    matched_required_source_item_count: int
    selected_source_item_ids: tuple[str, ...]


def run_kg_fusion_eval(
    *,
    baseline_report_path: Path | None = None,
    work_dir: Path | None = None,
    private_manifest_path: Path | None = None,
) -> dict[str, Any]:
    if os.environ.get(RUN_OPT_IN_ENV) != "1":
        return _blocked_report("kg_fusion_eval_requires_explicit_opt_in")
    if baseline_report_path is None or work_dir is None:
        return _blocked_report("explicit_work_dir_required")

    try:
        return _run_kg_fusion_eval_inner(
            baseline_report_path=baseline_report_path,
            work_dir=work_dir,
            private_manifest_path=(private_manifest_path or work_dir / PRIVATE_MANIFEST_RELATIVE),
        )
    except FileNotFoundError as exc:
        reason = str(exc)
        if reason in _BLOCKED_REASONS:
            return _blocked_report(reason)
        return _blocked_report("kg_fusion_eval_failed")
    except Exception:
        return _blocked_report("kg_fusion_eval_failed")


def _run_kg_fusion_eval_inner(
    *,
    baseline_report_path: Path,
    work_dir: Path,
    private_manifest_path: Path,
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
    segments = _load_mail_segments(work_dir)
    observations_load_elapsed_ms = int((time.monotonic() - load_started) * 1000)
    if not segments:
        raise FileNotFoundError("observations_missing")

    kg_started = time.monotonic()
    kg_index = _build_candidate_kg_index(segments)
    kg_build_elapsed_ms = int((time.monotonic() - kg_started) * 1000)

    manifest = _read_json_file(private_manifest_path, "private_manifest_missing")
    manifest_hash = sha256_json(manifest)
    cases = _validate_private_manifest_cases(manifest)

    scoring_started = time.monotonic()
    baseline_rows = _validate_baseline_manifest_binding(
        baseline_report,
        cases=cases,
    )
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
        "baseline_manifest_binding_validated": True,
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
        required_logical_source_item_ids = item.get("required_logical_source_item_ids")
        if not isinstance(query_text, str) or not isinstance(fingerprint, str):
            raise RuntimeError("invalid_private_manifest")
        if not isinstance(required_ids, list) or any(
            not isinstance(value, str) for value in required_ids
        ):
            raise RuntimeError("invalid_private_manifest")
        if not isinstance(required_logical_source_item_ids, list) or any(
            not isinstance(value, str) or not value for value in required_logical_source_item_ids
        ):
            raise FileNotFoundError("private_manifest_logical_source_gold_missing")
        if result_kind == "owner_match" and not required_logical_source_item_ids:
            raise FileNotFoundError("private_manifest_logical_source_gold_missing")
        if result_kind != "owner_match" and required_logical_source_item_ids:
            raise RuntimeError("invalid_private_manifest")
        validated.append(item)
    return validated


def migrate_legacy_private_manifest_logical_source_gold(
    manifest: Mapping[str, Any],
    *,
    segments: Sequence[_MailSegment],
) -> dict[str, Any]:
    """Explicit one-time migration; retrieval scoring never calls this path."""

    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != CASE_COUNT:
        raise RuntimeError("invalid_private_manifest")
    source_item_by_observation_id = {
        segment.observation_id: segment.source_item_id for segment in segments
    }
    migrated_cases: list[dict[str, Any]] = []
    for item in cases:
        if not isinstance(item, Mapping):
            raise RuntimeError("invalid_private_manifest")
        case = dict(item)
        configured = case.get("required_logical_source_item_ids")
        if isinstance(configured, list) and configured:
            case["required_logical_source_item_ids"] = list(dict.fromkeys(configured))
            migrated_cases.append(case)
            continue
        required_observation_ids = case.get("required_source_observation_ids", [])
        if not isinstance(required_observation_ids, list) or any(
            not isinstance(value, str) for value in required_observation_ids
        ):
            raise RuntimeError("invalid_private_manifest")
        missing = [
            observation_id
            for observation_id in required_observation_ids
            if observation_id not in source_item_by_observation_id
        ]
        if missing:
            raise RuntimeError("legacy_manifest_observation_unmapped")
        case["required_logical_source_item_ids"] = list(
            dict.fromkeys(
                source_item_by_observation_id[observation_id]
                for observation_id in required_observation_ids
            )
        )
        if (
            case.get("result_kind") == "owner_match"
            and not case["required_logical_source_item_ids"]
        ):
            raise RuntimeError("legacy_manifest_logical_source_gold_missing")
        migrated_cases.append(case)
    migrated = dict(manifest)
    migrated["cases"] = migrated_cases
    migrated["logical_source_gold_policy_version"] = "stable_logical_source_item_gold_v1"
    migrated["legacy_manifest_hash"] = sha256_json(manifest)
    return migrated


def _load_mail_segments(work_dir: Path) -> list[_MailSegment]:
    observations_dir = work_dir / "data" / "ingestion" / "observations"
    if not observations_dir.exists():
        raise FileNotFoundError("observations_missing")
    payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(observations_dir.glob("*.json"))
    ]
    message_metadata: dict[str, dict[str, str]] = {}
    for payload in payloads:
        if payload.get("observation_type") != "email_message":
            continue
        location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
        message_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        metadata = {
            key: value
            for key in (
                "subject",
                "normalized_subject",
                "sender",
                "sent_at",
                "message_fingerprint",
            )
            if isinstance((value := message_payload.get(key)), str) and value
        }
        if isinstance(payload.get("text"), str) and payload["text"]:
            metadata.setdefault("subject", payload["text"])
        for identity in _message_identity_candidates(location, message_payload):
            message_metadata[identity] = metadata

    segments: list[_MailSegment] = []
    for payload in payloads:
        if payload.get("observation_type") != "email_body_segment":
            continue
        observation_id = payload.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id:
            continue
        text = payload.get("text")
        location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
        body_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        identities = _message_identity_candidates(location, body_payload)
        metadata = next(
            (message_metadata[identity] for identity in identities if identity in message_metadata),
            {},
        )
        message_occurrence_id = _string_or_none(location.get("message_occurrence_id")) or (
            _string_or_none(body_payload.get("message_occurrence_id"))
        )
        message_id = _string_or_none(location.get("message_id")) or _string_or_none(
            body_payload.get("message_id")
        )
        message_fingerprint = _string_or_none(body_payload.get("message_fingerprint")) or (
            _string_or_none(metadata.get("message_fingerprint"))
        )
        if message_fingerprint:
            source_item_id = stable_resource_contract_id(
                "emailmsg",
                "EmailMessage",
                {"message_fingerprint": message_fingerprint},
            )
        else:
            source_item_id = message_id or message_occurrence_id
        if source_item_id is None:
            raise FileNotFoundError("stable_source_identity_missing")
        source_version_id = stable_resource_contract_id(
            "sourceversion",
            "SourceVersion",
            {
                "source_identity_policy_id": EMAIL_SOURCE_IDENTITY_POLICY_ID,
                "source_item_id": source_item_id,
                "immutable_source_fingerprint": message_fingerprint or source_item_id,
            },
        )
        permission_scope_id = _permission_scope_id(payload)
        known_at = _valid_ordered_timestamp_or_none(payload.get("created_at"))
        if known_at is None:
            raise FileNotFoundError("knowledge_time_missing")
        thread_id = _string_or_none(location.get("thread_id")) or _string_or_none(
            body_payload.get("thread_id")
        )
        searchable = " ".join(
            item
            for item in (
                text,
                metadata.get("subject"),
                metadata.get("normalized_subject"),
                metadata.get("sender"),
            )
            if isinstance(item, str)
        )
        searchable = unicodedata.normalize("NFKC", searchable)
        segments.append(
            _MailSegment(
                observation_id=observation_id,
                source_item_id=source_item_id,
                source_identity_policy_id=EMAIL_SOURCE_IDENTITY_POLICY_ID,
                source_version_id=source_version_id,
                permission_scope_id=permission_scope_id,
                thread_id=thread_id,
                message_occurrence_id=message_occurrence_id,
                message_id=message_id,
                searchable_text=searchable,
                actor_text=metadata.get("sender", ""),
                observed_at=_valid_ordered_timestamp_or_none(metadata.get("sent_at")),
                known_at=known_at,
                observation_type="email_body_segment",
                modality=_string_or_none(payload.get("modality")) or "mail",
                semantic_roles=_semantic_roles(payload, body_payload),
                tokens=frozenset(),
                actor_tokens=frozenset(),
                ontology_signals=frozenset(),
            )
        )
    return segments


def _build_candidate_kg_index(segments: Sequence[_MailSegment]) -> _CandidateKgIndex:
    segments, segmenters, compiled_policy, text_policy_runtime = (
        _apply_default_lexical_candidate_policy(segments)
    )
    segment_by_id = {segment.observation_id: segment for segment in segments}
    ids_by_component: dict[str, list[str]] = defaultdict(list)
    tokens_by_component: dict[str, set[str]] = defaultdict(set)
    for segment in segments:
        component_id = segment.source_item_id
        ids_by_component[component_id].append(segment.observation_id)
        tokens_by_component[component_id].update(segment.tokens)

    evaluation_context_id = stable_resource_contract_id(
        "candidatecontext",
        "CandidateEvidenceEvaluationContext",
        {
            "source_identity_policy_ids": sorted(
                {segment.source_identity_policy_id for segment in segments}
            ),
            "source_version_ids": sorted({segment.source_version_id for segment in segments}),
            "permission_scope_ids": sorted({segment.permission_scope_id for segment in segments}),
        },
    )
    known_as_of = _latest_ordered_timestamp(segment.known_at for segment in segments)
    as_of_world_time = known_as_of
    component_by_observation_id = {
        observation_id: component_id
        for component_id, observation_ids in ids_by_component.items()
        for observation_id in observation_ids
    }
    component_ids_by_token: dict[str, set[str]] = defaultdict(set)
    for component_id, tokens in tokens_by_component.items():
        for token in tokens:
            component_ids_by_token[token].add(component_id)
    evidence_records = tuple(
        [
            CandidateEvidenceRecord(
                observation_id=segment.observation_id,
                source_item_id=segment.source_item_id,
                source_identity_policy_id=segment.source_identity_policy_id,
                source_version_id=segment.source_version_id,
                permission_scope_id=segment.permission_scope_id,
                tokens=segment.tokens,
                actor_tokens=segment.actor_tokens,
                context_ids=frozenset(
                    {
                        evaluation_context_id,
                        *({segment.thread_id} if segment.thread_id else set()),
                    }
                ),
                observed_at=segment.observed_at,
                known_at=segment.known_at,
                valid_from=segment.observed_at,
                ontology_signals=segment.ontology_signals,
                observation_type=segment.observation_type,
                modality=segment.modality,
                semantic_roles=segment.semantic_roles,
            )
            for segment in segments
        ]
    )
    evidence_index = CandidateEvidenceIndex(
        evidence_records,
        access_binding=_access_binding_for_records(
            evidence_records,
            binding_context="candidate_index",
        ),
        text_policy_runtime=text_policy_runtime,
        ontology_revision_id=EVIDENCE_ONTOLOGY_REVISION_ID,
        ontology_signal_vocabulary_hash=EVIDENCE_ONTOLOGY_SIGNAL_VOCABULARY_HASH,
    )
    relation_count = sum(
        max(0, len(observation_ids) - 1) for observation_ids in ids_by_component.values()
    )

    return _CandidateKgIndex(
        segmenters=segmenters,
        compiled_policy=compiled_policy,
        text_policy_runtime=text_policy_runtime,
        evidence_index=evidence_index,
        evaluation_context_id=evaluation_context_id,
        known_as_of=known_as_of,
        as_of_world_time=as_of_world_time,
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
        token_relation_count=0,
        thread_relation_count=0,
    )


def _apply_default_lexical_candidate_policy(
    segments: Sequence[_MailSegment],
) -> tuple[
    tuple[_MailSegment, ...],
    lexical_eval._SegmenterBundle,
    lexical_eval._CompiledOntologyPolicy,
    CandidateEvidenceTextPolicyRuntime,
]:
    corpus_hash = sha256_json(
        {
            "policy_version": KG_POLICY_VERSION,
            "observation_ids": [segment.observation_id for segment in segments],
        }
    )
    raw_records = [
        {
            "corpus_hash": corpus_hash,
            "observation_id": segment.observation_id,
            "message_value": segment.message_id
            or segment.message_occurrence_id
            or segment.observation_id,
            "thread_value": segment.thread_id,
            "text": segment.searchable_text,
        }
        for segment in segments
    ]
    with tempfile.TemporaryDirectory(prefix="formowl-domain-hard-lexical-") as private_dir:
        segmenters = lexical_eval._prepare_segmenters(
            raw_records,
            output_private_dir=Path(private_dir),
            require_external_segmenters=True,
        )
        prepared = lexical_eval._prepare_corpus(
            raw_records,
            segmenters=segmenters,
            parsed_corpus_count=1,
        )
    compiled_policy = lexical_eval._compile_programmatic_ontology_policy(
        prepared.segments,
        scorer_kind=lexical_eval.PROGRAMMATIC_SCORER_FROZEN_PROFILE,
    )

    tokenized_segments: list[_MailSegment] = []
    for source_segment, prepared_segment in zip(segments, prepared.segments, strict=True):
        lexical_candidates = set(
            lexical_eval._important_lexemes(
                prepared_segment.lexemes_by_policy[lexical_eval.POLICY_FROZEN_PROGRAMMATIC],
                lexical_eval.POLICY_FROZEN_PROGRAMMATIC,
                compiled_policy=compiled_policy,
            )
        )
        tokens = frozenset(
            _lexeme_surfaces(lexical_candidates)
            | _core_coordination_terms(source_segment.searchable_text)
        )
        actor_tokens = frozenset(
            _lexeme_surfaces(
                lexical_eval._regex_lexemes(source_segment.actor_text)
                | lexical_eval._query_protected_lexemes(source_segment.actor_text)
            )
        )
        tokenized_segments.append(
            _MailSegment(
                observation_id=source_segment.observation_id,
                source_item_id=source_segment.source_item_id,
                source_identity_policy_id=source_segment.source_identity_policy_id,
                source_version_id=source_segment.source_version_id,
                permission_scope_id=source_segment.permission_scope_id,
                thread_id=source_segment.thread_id,
                message_occurrence_id=source_segment.message_occurrence_id,
                message_id=source_segment.message_id,
                searchable_text=source_segment.searchable_text,
                actor_text=source_segment.actor_text,
                observed_at=source_segment.observed_at,
                known_at=source_segment.known_at,
                observation_type=source_segment.observation_type,
                modality=source_segment.modality,
                semantic_roles=source_segment.semantic_roles,
                tokens=tokens,
                actor_tokens=actor_tokens,
                ontology_signals=_source_neutral_ontology_signals(
                    observation_type=source_segment.observation_type,
                    modality=source_segment.modality,
                    semantic_roles=source_segment.semantic_roles,
                    tokens=tokens,
                    actor_tokens=actor_tokens,
                    observed_at=source_segment.observed_at,
                ),
            )
        )

    query_tokenizer_runtime_id = "mail_domain_hard_normative_query_text_policy_v1"

    def tokenize_query(value: str) -> set[str]:
        return _query_tokens_from_policy(
            value,
            segmenters=segmenters,
            compiled_policy=compiled_policy,
        )

    text_policy_binding = CandidateEvidenceTextPolicyBinding(
        normalization_policy_version=NORMALIZATION_POLICY_VERSION,
        segmentation_policy_version=lexical_eval.SEGMENTATION_POLICY_VERSION,
        candidate_admission_policy=lexical_eval.POLICY_FROZEN_PROGRAMMATIC,
        candidate_admission_policy_hash=compiled_policy.policy_hash,
        sentencepiece_model_hash=segmenters.sentencepiece_model_hash,
        sentencepiece_training_corpus_hash=segmenters.training_corpus_hash,
        query_tokenizer_runtime_id=query_tokenizer_runtime_id,
        query_tokenizer_implementation_hash=(
            candidate_evidence_tokenizer_implementation_hash(tokenize_query)
        ),
    )
    text_policy_runtime = CandidateEvidenceTextPolicyRuntime(
        binding=text_policy_binding,
        runtime_id=query_tokenizer_runtime_id,
        tokenize_query=tokenize_query,
    )
    return (
        tuple(tokenized_segments),
        segmenters,
        compiled_policy,
        text_policy_runtime,
    )


def _query_tokens(value: str, kg_index: _CandidateKgIndex) -> set[str]:
    return set(kg_index.text_policy_runtime.tokenize(value))


def _query_tokens_from_policy(
    value: str,
    *,
    segmenters: lexical_eval._SegmenterBundle,
    compiled_policy: lexical_eval._CompiledOntologyPolicy,
) -> set[str]:
    value = unicodedata.normalize("NFKC", value)
    return _lexeme_surfaces(
        _admitted_lexemes_for_text(
            value,
            segmenters=segmenters,
            compiled_policy=compiled_policy,
        )
    ) | _core_coordination_terms(value)


def _admitted_lexemes_for_text(
    value: str,
    *,
    segmenters: lexical_eval._SegmenterBundle,
    compiled_policy: lexical_eval._CompiledOntologyPolicy,
) -> set[str]:
    lexemes = lexical_eval._regex_lexemes(value)
    lexemes.update(lexical_eval._jieba_lexemes(value, segmenters.jieba_module))
    lexemes.update(lexical_eval._sentencepiece_lexemes(value, segmenters.sentencepiece_processor))
    lexemes.update(lexical_eval._query_protected_lexemes(value))
    return set(
        lexical_eval._important_lexemes(
            lexemes,
            lexical_eval.POLICY_FROZEN_PROGRAMMATIC,
            compiled_policy=compiled_policy,
        )
    )


def _lexeme_surfaces(lexemes: set[str]) -> set[str]:
    return {lexeme.split(":", 1)[1] if ":" in lexeme else lexeme for lexeme in lexemes if lexeme}


def _core_coordination_terms(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return {
        match.group(0)
        for match in re.finditer(r"[a-z][a-z0-9_-]{2,}", normalized)
        if match.group(0) in _CORE_COORDINATION_TERMS
    }


def _source_neutral_ontology_signals(
    *,
    observation_type: str,
    modality: str | None,
    semantic_roles: frozenset[str],
    tokens: frozenset[str],
    actor_tokens: frozenset[str],
    observed_at: str | None,
) -> frozenset[str]:
    return infer_evidence_ontology_signals(
        observation_type=observation_type,
        modality=modality,
        semantic_roles=semantic_roles,
        actor_tokens=actor_tokens,
        observed_at=observed_at,
        has_concept_content=bool(tokens),
    )


def _query_ontology_signals(query_text: str, query_tokens: set[str]) -> set[str]:
    normalized = query_text.lower()
    signals = {"concept_evidence"} if query_tokens else set()
    if any(
        term in normalized
        for term in ("document", "file", "page", "slide", "message", "email", "pdf", "ppt")
    ):
        signals.add("document_evidence")
    if any(
        term in normalized
        for term in (
            "cell",
            "erp",
            "ledger",
            "row",
            "sheet",
            "spreadsheet",
            "table",
            "transaction",
        )
    ):
        signals.add("structured_record_evidence")
    if any(term in normalized for term in ("audio", "recording", "transcript", "video")):
        signals.add("audio_visual_evidence")
    if any(term in normalized for term in ("image", "photo", "scan", "screenshot")):
        signals.add("image_evidence")
    if any(term in normalized for term in ("audit", "event", "log", "workflow")):
        signals.add("event_evidence")
    if any(
        term in normalized
        for term in (
            "asked",
            "mentioned",
            "reported",
            "said",
            "stated",
            "who",
            "wrote",
        )
    ):
        signals.add("actor_attributed_evidence")
    if any(
        term in normalized
        for term in ("after", "before", "chronology", "earliest", "latest", "timeline")
    ):
        signals.add("temporally_ordered_evidence")
    if any(
        term in query_tokens
        for term in (
            "amount",
            "cost",
            "duration",
            "measurement",
            "percent",
            "percentage",
            "price",
            "quantity",
            "rate",
            "score",
            "total",
            "variance",
        )
    ):
        signals.add("measurement_bearing_evidence")
    return signals


def _score_case(
    case: Mapping[str, Any],
    *,
    kg_index: _CandidateKgIndex,
    baseline_row: Mapping[str, Any] | None,
) -> dict[str, Any]:
    started = time.monotonic()
    query_text = str(case.get("query_text", ""))
    requester_user_id = str(case.get("requester_user_id", ""))
    retrieval = _retrieve_case_evidence(
        query_text=query_text,
        requester_user_id=requester_user_id,
        kg_index=kg_index,
    )
    selected_ids = retrieval.selected_observation_ids
    selection_score = _score_selection(
        case,
        selected_observation_ids=selected_ids,
        kg_index=kg_index,
    )

    result_kind = str(case["result_kind"])
    baseline_status = (
        str(baseline_row.get("status"))
        if isinstance(baseline_row, Mapping) and isinstance(baseline_row.get("status"), str)
        else "unknown"
    )

    warning_count = int(result_kind == "permission_denied" and retrieval.rejected)

    row = {
        "case_id_hash": sha256_json(str(case.get("case_id", ""))),
        "case_manifest_entry_hash": str(case["private_fingerprint"]),
        "domain_hash": sha256_json(str(case.get("domain", ""))),
        "intent_kind_hash": sha256_json(str(case.get("intent_kind", ""))),
        "pattern_hash": sha256_json(str(case.get("pattern", ""))),
        "result_kind": result_kind,
        "baseline_status": baseline_status,
        "kg_status": selection_score.status,
        "required_evidence_count": selection_score.required_observation_count,
        "matched_required_evidence_count": (selection_score.matched_required_observation_count),
        "unmapped_required_evidence_count": (selection_score.unmapped_required_observation_count),
        "required_source_item_count": selection_score.required_source_item_count,
        "required_source_item_match_threshold": (
            selection_score.required_source_item_match_threshold
        ),
        "matched_required_source_item_count": (selection_score.matched_required_source_item_count),
        "selected_component_count": len(selection_score.selected_source_item_ids),
        "selected_evidence_count": len(selected_ids),
        "warning_count": warning_count,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    row["response_hash"] = sha256_json(
        {
            "case": row["case_id_hash"],
            "baseline_status": baseline_status,
            "kg_status": selection_score.status,
            "selected_components": selection_score.selected_source_item_ids,
            "selected_evidence": selected_ids,
            "matched_required_source_items": (selection_score.matched_required_source_item_count),
            "matched_required_observations": (selection_score.matched_required_observation_count),
        }
    )
    return row


def _score_selection(
    case: Mapping[str, Any],
    *,
    selected_observation_ids: Sequence[str],
    kg_index: _CandidateKgIndex,
) -> _SelectionScore:
    required_observation_ids = tuple(
        str(value) for value in case.get("required_source_observation_ids", [])
    )
    required_source_item_ids = set(
        str(value) for value in case.get("required_logical_source_item_ids", [])
    )
    unmapped_required_observation_count = sum(
        observation_id not in kg_index.component_by_observation_id
        for observation_id in required_observation_ids
    )
    selected_source_item_ids = tuple(
        dict.fromkeys(
            kg_index.component_by_observation_id[observation_id]
            for observation_id in selected_observation_ids
            if observation_id in kg_index.component_by_observation_id
        )
    )
    required_match_count = int(case.get("required_match_count", 0))
    source_item_match_threshold = min(
        required_match_count,
        len(required_source_item_ids),
    )
    matched_required_source_item_count = len(
        required_source_item_ids & set(selected_source_item_ids)
    )
    matched_required_observation_count = len(
        set(required_observation_ids) & set(selected_observation_ids)
    )
    result_kind = str(case["result_kind"])
    if result_kind == "owner_match":
        status = (
            "passed"
            if source_item_match_threshold > 0
            and matched_required_source_item_count >= source_item_match_threshold
            else "failed"
        )
    else:
        status = "passed" if not selected_observation_ids else "failed"
    return _SelectionScore(
        status=status,
        required_observation_count=len(required_observation_ids),
        matched_required_observation_count=matched_required_observation_count,
        unmapped_required_observation_count=unmapped_required_observation_count,
        required_source_item_count=len(required_source_item_ids),
        required_source_item_match_threshold=source_item_match_threshold,
        matched_required_source_item_count=matched_required_source_item_count,
        selected_source_item_ids=selected_source_item_ids,
    )


def _retrieve_case_evidence(
    *,
    query_text: str,
    requester_user_id: str,
    kg_index: _CandidateKgIndex,
):
    access_binding = _access_binding_for_requester(
        requester_user_id,
        kg_index=kg_index,
    )
    return kg_index.evidence_index.retrieve(
        query_text=query_text,
        limit=EVIDENCE_BUDGET,
        access_binding=access_binding,
        **_retrieval_scope(kg_index),
    )


def _retrieval_scope(kg_index: _CandidateKgIndex) -> dict[str, object]:
    """Return the explicit source-neutral context/time boundary for one run."""

    return {
        "accessible_context_ids": {kg_index.evaluation_context_id},
        "query_context_ids": {kg_index.evaluation_context_id},
        "known_as_of": kg_index.known_as_of,
        "as_of_world_time": kg_index.as_of_world_time,
    }


def _eligible_observation_ids_for_requester(
    requester_user_id: str,
    *,
    kg_index: _CandidateKgIndex,
) -> set[str]:
    return set(
        _access_binding_for_requester(
            requester_user_id,
            kg_index=kg_index,
        ).eligible_observation_ids
    )


def _access_binding_for_requester(
    requester_user_id: str,
    *,
    kg_index: _CandidateKgIndex,
) -> CandidateEvidenceAccessBinding:
    segments = (
        tuple(kg_index.segment_by_observation_id.values())
        if requester_user_id == hard_eval.ACTOR_USER_ID
        else ()
    )
    return CandidateEvidenceAccessBinding(
        binding_id=stable_resource_contract_id(
            "candidateaccess",
            "CandidateEvidenceAccessBinding",
            {
                "requester_user_id": requester_user_id,
                "observation_ids": sorted(segment.observation_id for segment in segments),
                "source_identity_policy_ids": sorted(
                    {segment.source_identity_policy_id for segment in segments}
                ),
                "permission_scope_ids": sorted(
                    {segment.permission_scope_id for segment in segments}
                ),
                "source_version_ids": sorted({segment.source_version_id for segment in segments}),
            },
        ),
        eligible_observation_ids=frozenset(segment.observation_id for segment in segments),
        eligible_source_identity_policy_ids=frozenset(
            segment.source_identity_policy_id for segment in segments
        ),
        eligible_permission_scope_ids=frozenset(
            segment.permission_scope_id for segment in segments
        ),
        eligible_source_version_ids=frozenset(segment.source_version_id for segment in segments),
    )


def _access_binding_for_records(
    records: Sequence[CandidateEvidenceRecord],
    *,
    binding_context: str,
) -> CandidateEvidenceAccessBinding:
    return CandidateEvidenceAccessBinding(
        binding_id=stable_resource_contract_id(
            "candidateaccess",
            "CandidateEvidenceAccessBinding",
            {
                "binding_context": binding_context,
                "observation_ids": sorted(record.observation_id for record in records),
                "source_identity_policy_ids": sorted(
                    {record.source_identity_policy_id for record in records}
                ),
                "permission_scope_ids": sorted({record.permission_scope_id for record in records}),
                "source_version_ids": sorted({record.source_version_id for record in records}),
            },
        ),
        eligible_observation_ids=frozenset(record.observation_id for record in records),
        eligible_source_identity_policy_ids=frozenset(
            record.source_identity_policy_id for record in records
        ),
        eligible_permission_scope_ids=frozenset(record.permission_scope_id for record in records),
        eligible_source_version_ids=frozenset(record.source_version_id for record in records),
    )


def _rank_components(
    query_tokens: set[str],
    kg_index: _CandidateKgIndex,
    *,
    limit: int,
) -> tuple[str, ...]:
    scores: Counter[str] = Counter()
    for token in query_tokens:
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
        "case_policy_hash": kg_index.tokenizer_binding_hash,
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
        "required_source_item_count": kg_counts["required_source_item_count"],
        "matched_required_source_item_count": kg_counts["matched_required_source_item_count"],
        "source_item_recall_basis_points": kg_counts["source_item_recall_basis_points"],
        "required_observation_citation_count": kg_counts["required_observation_citation_count"],
        "matched_required_observation_citation_count": kg_counts[
            "matched_required_observation_citation_count"
        ],
        "selected_observation_citation_count": kg_counts["selected_observation_citation_count"],
        "observation_citation_recall_basis_points": kg_counts[
            "observation_citation_recall_basis_points"
        ],
        "observation_citation_precision_basis_points": kg_counts[
            "observation_citation_precision_basis_points"
        ],
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
        "required_source_item_count",
        "matched_required_source_item_count",
        "source_item_recall_basis_points",
        "required_observation_citation_count",
        "matched_required_observation_citation_count",
        "selected_observation_citation_count",
        "observation_citation_recall_basis_points",
        "observation_citation_precision_basis_points",
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
        "unmapped_required_evidence_count",
        "required_source_item_count",
        "required_source_item_match_threshold",
        "matched_required_source_item_count",
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
            "unmapped_required_evidence_count",
            "required_source_item_count",
            "required_source_item_match_threshold",
            "matched_required_source_item_count",
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
    positive_rows = [row for row in rows if row.get("result_kind") == "owner_match"]
    required_source_item_count = sum(
        _int_or_zero(row.get("required_source_item_count")) for row in positive_rows
    )
    matched_required_source_item_count = sum(
        _int_or_zero(row.get("matched_required_source_item_count")) for row in positive_rows
    )
    required_observation_citation_count = sum(
        _int_or_zero(row.get("required_evidence_count")) for row in positive_rows
    )
    matched_required_observation_citation_count = sum(
        _int_or_zero(row.get("matched_required_evidence_count")) for row in positive_rows
    )
    selected_observation_citation_count = sum(
        _int_or_zero(row.get("selected_evidence_count")) for row in positive_rows
    )
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
        "required_source_item_count": required_source_item_count,
        "matched_required_source_item_count": matched_required_source_item_count,
        "source_item_recall_basis_points": _basis_points(
            matched_required_source_item_count,
            required_source_item_count,
        ),
        "required_observation_citation_count": (required_observation_citation_count),
        "matched_required_observation_citation_count": (
            matched_required_observation_citation_count
        ),
        "selected_observation_citation_count": selected_observation_citation_count,
        "observation_citation_recall_basis_points": _basis_points(
            matched_required_observation_citation_count,
            required_observation_citation_count,
        ),
        "observation_citation_precision_basis_points": _basis_points(
            matched_required_observation_citation_count,
            selected_observation_citation_count,
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


def _validate_baseline_manifest_binding(
    report: Mapping[str, Any],
    *,
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    fingerprints = [
        case.get("private_fingerprint")
        for case in cases
        if isinstance(case.get("private_fingerprint"), str)
    ]
    if (
        len(fingerprints) != CASE_COUNT
        or len(set(fingerprints)) != CASE_COUNT
        or sha256_json(fingerprints)
        != (
            report.get("safe_outputs", {}).get("case_manifest_hash")
            if isinstance(report.get("safe_outputs"), Mapping)
            else None
        )
    ):
        raise FileNotFoundError("baseline_manifest_binding_mismatch")

    rows_by_hash = _baseline_rows_by_manifest_hash(report)
    if len(rows_by_hash) != CASE_COUNT or set(rows_by_hash) != set(fingerprints):
        raise FileNotFoundError("baseline_manifest_binding_mismatch")

    safe_outputs = report.get("safe_outputs")
    rows = safe_outputs.get("case_rows") if isinstance(safe_outputs, Mapping) else None
    if not isinstance(rows, list) or len(rows) != CASE_COUNT:
        raise FileNotFoundError("baseline_manifest_binding_mismatch")
    row_fingerprints = [
        row.get("case_manifest_entry_hash")
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("case_manifest_entry_hash"), str)
    ]
    if (
        len(row_fingerprints) != CASE_COUNT
        or len(set(row_fingerprints)) != CASE_COUNT
        or row_fingerprints != fingerprints
    ):
        raise FileNotFoundError("baseline_manifest_binding_mismatch")
    return rows_by_hash


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


def _permission_scope_id(observation: Mapping[str, Any]) -> str:
    permission_scope = observation.get("permission_scope")
    if not isinstance(permission_scope, Mapping):
        raise FileNotFoundError("permission_scope_missing")
    scope_type = permission_scope.get("scope_type")
    if not isinstance(scope_type, str) or not scope_type.strip():
        raise FileNotFoundError("permission_scope_missing")
    normalized_scope = {
        str(key): value for key, value in permission_scope.items() if isinstance(key, str)
    }
    return stable_resource_contract_id(
        "permissionscope",
        "PermissionScope",
        normalized_scope,
    )


def _message_identity_candidates(
    location: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value
            for value in (
                _string_or_none(location.get("message_occurrence_id")),
                _string_or_none(payload.get("message_occurrence_id")),
                _string_or_none(location.get("message_id")),
                _string_or_none(payload.get("message_id")),
            )
            if value
        )
    )


def _semantic_roles(*payloads: Mapping[str, Any]) -> frozenset[str]:
    roles: set[str] = set()
    for payload in payloads:
        for field_name in ("semantic_roles", "field_roles", "value_roles"):
            value = payload.get(field_name)
            if isinstance(value, str) and value.strip():
                roles.add(value.strip().lower())
            elif isinstance(value, list):
                roles.update(
                    item.strip().lower() for item in value if isinstance(item, str) and item.strip()
                )
    return frozenset(roles)


def _valid_ordered_timestamp_or_none(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return value


def _latest_ordered_timestamp(values: Iterable[str]) -> str:
    normalized_values = tuple(value for value in values if isinstance(value, str))
    if not normalized_values:
        raise FileNotFoundError("knowledge_time_missing")
    return max(
        normalized_values,
        key=lambda value: datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        ).astimezone(timezone.utc),
    )


def _int_or_zero(value: Any) -> int:
    return value if type(value) is int else 0


def _basis_points(numerator: int, denominator: int) -> int:
    return int((numerator / denominator) * 10000) if denominator else 0


def _regex_baseline_tokenize(value: str) -> set[str]:
    """Regex-only degraded fallback retained for explicit baselines and ablations."""

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
    parser.add_argument("--private-manifest", type=Path, default=None)
    parser.add_argument("--migrate-private-manifest", type=Path, default=None)
    parser.add_argument("--validate-report", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.migrate_private_manifest is not None:
        if args.work_dir is None:
            return 1
        try:
            source = json.loads(args.migrate_private_manifest.read_text(encoding="utf-8"))
            migrated = migrate_legacy_private_manifest_logical_source_gold(
                source,
                segments=_load_mail_segments(args.work_dir),
            )
        except Exception:
            return 1
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(migrated, indent=2, sort_keys=True) + "\n")
        return 0

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
        private_manifest_path=args.private_manifest,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report.get("metrics", {}).get("kg_fusion_eval_completed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
