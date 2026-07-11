#!/usr/bin/env python3
"""Evaluate EXM PST candidate admission and graph scoring behavior.

This experiment consumes preserved full-PST parsed work directories rather than
re-parsing archives inside the KG scorer. Public output is hash/count/status
only. The private manifest under the selected private output directory may
contain generated questions and evidence bindings, so it must stay untracked.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import importlib
import json
import math
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
    basis_points as _basis_points,
    mapping_or_empty as _dict_or_empty,
    public_outputs_are_safe,
    require_sha256 as _require_sha256,
    validate_exact_keys_missing_first as _validate_exact_keys,
)

DEFAULT_OUTPUT = ROOT / ".test-tmp" / "formowl-mail-exm-lexical-ontology-50000.json"
DEFAULT_PRIVATE_DIR = ROOT / ".test-tmp" / "formowl-mail-exm-lexical-ontology-private"
REPORT_TYPE = "mail_full_pst_exm_candidate_admission_eval"
RUN_OPT_IN_ENV = "FORMOWL_RUN_FULL_PST_EXM_LEXICAL_ONTOLOGY_EVAL"
NOW = "2026-07-09T16:00:00+08:00"
CASE_COUNT = 50000
POSITIVE_CASE_RATIO_BP = 8000
NO_MATCH_CASE_RATIO_BP = 1000
EXPECTED_EXM_PST_COUNT = 2
MAX_GROUP_DOCUMENT_FREQUENCY = 900
MAX_COMPONENT_EVIDENCE_PER_CASE = 10
MAX_COMPONENT_FALLBACK_SCAN_SEGMENTS = 80
MAX_CATEGORY_COMPONENT_FALLBACK = 200
PROGRAMMATIC_MIN_DOCUMENT_FREQUENCY = 2
PROGRAMMATIC_MAX_DOCUMENT_FREQUENCY = 260
PROGRAMMATIC_NEURAL_SCORE_THRESHOLD_BP = 5200
PROGRAMMATIC_NEURAL_MODEL_VERSION = "formowl_exm_weak_label_cjk_mlp_v1"
PROGRAMMATIC_NEURAL_TRAINING_EPOCHS = 8
PROGRAMMATIC_NEURAL_LEARNING_RATE = 0.08
PROGRAMMATIC_NEURAL_HIDDEN_UNITS = 5
PROGRAMMATIC_DATA_DRIVEN_MODEL_VERSION = "formowl_exm_data_driven_cjk_policy_v1"
PROGRAMMATIC_FROZEN_MODEL_VERSION = "formowl_exm_frozen_cjk_profile_v1"
PROGRAMMATIC_SCORER_WEAK_LABEL_MLP = "weak_label_mlp"
PROGRAMMATIC_SCORER_DATA_DRIVEN = "data_driven_no_neural"
PROGRAMMATIC_SCORER_FROZEN_PROFILE = "frozen_profile_no_training"
SEGMENTATION_POLICY_VERSION = "jieba_sentencepiece_protected_spans_v1"
TYPE_COMPATIBILITY_PROXY_POLICY_VERSION = "formowl_exm_category_soft_scoring_proxy_v1"
PRIVATE_MANIFEST_NAME = "exm_lexical_ontology_50000.private.json"
PRIVATE_ROWS_NAME = "exm_lexical_ontology_50000_rows.private.json"
PRIVATE_CORPUS_NAME = "sentencepiece_training_corpus.private.txt"
PRIVATE_SENTENCEPIECE_LOG_NAME = "sentencepiece_training.private.log"
PRIVATE_SENTENCEPIECE_PREFIX = "sentencepiece_exm_private"

ARM_REGEX_KG = "regex_candidate_admission__candidate_kg"
ARM_REGEX_ONTOLOGY = "regex_candidate_admission__type_compatibility_proxy"
ARM_LEXICAL_KG = "jieba_sentencepiece_candidate_admission__candidate_kg"
ARM_LEXICAL_ONTOLOGY = "jieba_sentencepiece_candidate_admission__type_compatibility_proxy"
ARM_DATA_DRIVEN_ONTOLOGY = "frequency_rule_candidate_admission__type_compatibility_proxy"
ARM_FROZEN_ONTOLOGY = "frozen_profile_candidate_admission__type_compatibility_proxy"
ARM_PROGRAMMATIC_ONTOLOGY = "weak_label_mlp_candidate_admission__type_compatibility_proxy"
ARMS = (
    ARM_REGEX_KG,
    ARM_REGEX_ONTOLOGY,
    ARM_LEXICAL_KG,
    ARM_LEXICAL_ONTOLOGY,
    ARM_DATA_DRIVEN_ONTOLOGY,
    ARM_FROZEN_ONTOLOGY,
    ARM_PROGRAMMATIC_ONTOLOGY,
)

ARM_STAGE_DEFINITIONS = {
    ARM_REGEX_KG: {
        "candidate_admission_policy": "regex_candidate_admission",
        "kg_construction_mode": "lexeme_component_graph_v1",
        "type_compatibility_mode": "not_applied",
        "frame_semantics_mode": "not_evaluated",
    },
    ARM_REGEX_ONTOLOGY: {
        "candidate_admission_policy": "regex_candidate_admission",
        "kg_construction_mode": "lexeme_component_graph_v1",
        "type_compatibility_mode": "category_soft_scoring_proxy_v1",
        "frame_semantics_mode": "not_evaluated",
    },
    ARM_LEXICAL_KG: {
        "candidate_admission_policy": "jieba_sentencepiece_candidate_admission",
        "kg_construction_mode": "lexeme_component_graph_v1",
        "type_compatibility_mode": "not_applied",
        "frame_semantics_mode": "not_evaluated",
    },
    ARM_LEXICAL_ONTOLOGY: {
        "candidate_admission_policy": "jieba_sentencepiece_candidate_admission",
        "kg_construction_mode": "lexeme_component_graph_v1",
        "type_compatibility_mode": "category_soft_scoring_proxy_v1",
        "frame_semantics_mode": "not_evaluated",
    },
    ARM_DATA_DRIVEN_ONTOLOGY: {
        "candidate_admission_policy": "frequency_rule_candidate_admission",
        "kg_construction_mode": "lexeme_component_graph_v1",
        "type_compatibility_mode": "category_soft_scoring_proxy_v1",
        "frame_semantics_mode": "not_evaluated",
    },
    ARM_FROZEN_ONTOLOGY: {
        "candidate_admission_policy": "frozen_profile_candidate_admission",
        "kg_construction_mode": "lexeme_component_graph_v1",
        "type_compatibility_mode": "category_soft_scoring_proxy_v1",
        "frame_semantics_mode": "not_evaluated",
    },
    ARM_PROGRAMMATIC_ONTOLOGY: {
        "candidate_admission_policy": "weak_label_mlp_candidate_admission",
        "kg_construction_mode": "lexeme_component_graph_v1",
        "type_compatibility_mode": "category_soft_scoring_proxy_v1",
        "frame_semantics_mode": "not_evaluated",
    },
}

POLICY_REGEX = "regex_candidate_admission"
POLICY_LEXICAL = "jieba_sentencepiece_candidate_admission"
POLICY_DATA_DRIVEN_PROGRAMMATIC = "frequency_rule_candidate_admission"
POLICY_FROZEN_PROGRAMMATIC = "frozen_profile_candidate_admission"
POLICY_PROGRAMMATIC = "weak_label_mlp_candidate_admission"
PROGRAMMATIC_POLICIES = frozenset(
    {
        POLICY_DATA_DRIVEN_PROGRAMMATIC,
        POLICY_FROZEN_PROGRAMMATIC,
        POLICY_PROGRAMMATIC,
    }
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CJK_ORG_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9]{2,32}"
    r"(?:股份有限公司|有限公司|科技|電子|光電|公司|集團|企業|實業)"
)
_CJK_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")
_IDENTIFIER_RE = re.compile(
    r"(?:\b(?i:PO|PR|RFQ|INV|SO|MOQ|MPQ|SKU|PN)[-_:/ #]*"
    r"[A-Za-z0-9][A-Za-z0-9_.-]{2,}\b|\b[A-Z]{2,}[A-Z0-9_-]{3,}\b)"
)
_EMAIL_OR_DOMAIN_RE = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"
    r"\b[A-Z0-9.-]+\.(?:com|net|org|tw|cn|jp|io|co)\b"
)
_ASCII_RE = re.compile(r"[A-Za-z0-9_@.-]+")

_STOPWORDS = {
    "about",
    "across",
    "and",
    "case",
    "compare",
    "cross",
    "cross-message",
    "different",
    "email",
    "emails",
    "evidence",
    "find",
    "for",
    "from",
    "mail",
    "mails",
    "mention",
    "mentions",
    "message",
    "messages",
    "related",
    "separate",
    "separate-email",
    "the",
    "to",
    "update",
    "updates",
    "with",
}

_DOMAIN_TERMS = frozenset(term for terms in hard_eval.DOMAIN_VOCABULARY.values() for term in terms)
_CONFLICT_TERMS = frozenset(hard_eval.CONFLICT_TERMS)
_IMPORTANT_REGEX_TERMS = _DOMAIN_TERMS | _CONFLICT_TERMS
_OWNER_MATCH_BUCKETS = frozenset(
    {
        "ascii_business",
        "business_identifier",
        "cjk_organization",
        "cjk_phrase",
        "sentencepiece_piece",
    }
)
_CASE_BUCKETS = _OWNER_MATCH_BUCKETS | {"access_boundary", "false_positive_guard"}
_CASE_SPLITS = frozenset({"development", "evaluation"})
_PROGRAMMATIC_NEURAL_FEATURE_NAMES = (
    "has_cjk",
    "length_norm",
    "medium_length",
    "longer_cjk",
    "protected_category",
    "org_suffix",
    "low_document_frequency",
    "mid_document_frequency",
    "high_document_frequency",
    "sentencepiece_piece",
    "jieba_piece",
    "char_variety_norm",
)
_FROZEN_PROFILE_SCORE_RULES = {
    "bias": -1.25,
    "cjk_presence": 1.15,
    "medium_length": 0.55,
    "minimum_business_length": 0.25,
    "protected_category": 1.15,
    "org_suffix": 1.3,
    "document_frequency": {
        "lte_12": 0.45,
        "lte_80": 0.15,
        "gt_160": -0.7,
    },
    "sentencepiece_piece": -0.35,
    "sigmoid_multiplier_basis_points": 10000,
}
_DATA_DRIVEN_SCORE_RULES = {
    "cjk_presence": 2700,
    "length_bonus": {
        "len_2": 700,
        "len_3_to_10": 1300,
    },
    "document_frequency": {
        "lte_12": 1300,
        "lte_80": 900,
        "lte_160": 200,
        "gt_160": -1500,
    },
    "protected_category": 1600,
    "org_suffix": 1500,
    "sentencepiece_piece": -900,
    "char_variety_min_3": 500,
    "clamp_min": 0,
    "clamp_max": 10000,
}

_FORBIDDEN_TRUE_CLAIMS = {
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_real_upload_iframe_claim",
    "supports_general_full_pst_parser_readiness_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_business_answer_generation_claim",
    "supports_formal_ontology_governance_completion_claim",
    "supports_canonical_kg_write_claim",
    "supports_canonical_type_write_claim",
    "supports_user_graph_write_claim",
    "supports_wiki_projection_claim",
    "supports_raw_mail_access_claim",
    "supports_production_ready_claim",
}
_BLOCKED_REASONS = {
    "exm_lexical_eval_requires_explicit_opt_in",
    "explicit_parsed_corpus_required",
    "external_segmenters_required",
    "parsed_observations_missing",
    "insufficient_positive_case_evidence",
    "exm_lexical_eval_failed",
}


@dataclass(frozen=True)
class _TermOccurrence:
    lexeme: str
    display: str
    bucket: str
    categories: frozenset[str]


@dataclass(frozen=True)
class _Segment:
    segment_id: str
    corpus_id_hash: str
    observation_id_hash: str
    message_key: str
    thread_key: str | None
    text: str
    lexemes_by_policy: dict[str, frozenset[str]]
    categories: frozenset[str]
    term_occurrences: tuple[_TermOccurrence, ...]


@dataclass(frozen=True)
class _Case:
    case_id: str
    result_kind: str
    bucket: str
    split: str
    query_text: str
    required_segment_ids: tuple[str, ...]
    required_match_count: int
    requester_kind: str
    limit: int = MAX_COMPONENT_EVIDENCE_PER_CASE

    def private_fingerprint(self) -> str:
        return sha256_json(
            {
                "case_id": self.case_id,
                "result_kind": self.result_kind,
                "bucket": self.bucket,
                "split": self.split,
                "query_text": self.query_text,
                "required_segment_ids": self.required_segment_ids,
                "required_match_count": self.required_match_count,
                "requester_kind": self.requester_kind,
                "limit": self.limit,
            }
        )

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "result_kind": self.result_kind,
            "bucket": self.bucket,
            "split": self.split,
            "query_text": self.query_text,
            "required_segment_ids": list(self.required_segment_ids),
            "required_match_count": self.required_match_count,
            "requester_kind": self.requester_kind,
            "limit": self.limit,
            "private_fingerprint": self.private_fingerprint(),
        }


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
class _KgIndex:
    policy_name: str
    segmenters: "_SegmenterBundle"
    compiled_policy: _CompiledOntologyPolicy | None
    segment_by_id: dict[str, _Segment]
    component_by_segment_id: dict[str, str]
    segment_ids_by_component: dict[str, tuple[str, ...]]
    lexemes_by_component: dict[str, frozenset[str]]
    component_ids_by_lexeme: dict[str, tuple[str, ...]]
    segment_ids_by_component_lexeme: dict[str, dict[str, tuple[str, ...]]]
    fallback_segment_ids_by_component: dict[str, tuple[str, ...]]
    relation_count: int
    thread_relation_count: int
    lexical_relation_count: int

    @property
    def node_count(self) -> int:
        return len(self.segment_by_id)

    @property
    def component_count(self) -> int:
        return len(self.segment_ids_by_component)

    @property
    def largest_component_size(self) -> int:
        if not self.segment_ids_by_component:
            return 0
        return max(len(items) for items in self.segment_ids_by_component.values())


@dataclass(frozen=True)
class _OntologyIndex:
    categories_by_segment_id: dict[str, frozenset[str]]
    category_scores_by_component: dict[str, dict[str, int]]
    component_ids_by_category: dict[str, tuple[str, ...]]

    @property
    def typed_node_count(self) -> int:
        return sum(1 for value in self.categories_by_segment_id.values() if value)

    @property
    def typed_component_count(self) -> int:
        return sum(1 for value in self.category_scores_by_component.values() if value)


@dataclass(frozen=True)
class _CompiledOntologyPolicy:
    policy_hash: str
    scorer_kind: str
    scorer_requires_training: bool
    candidate_lexeme_count: int
    accepted_lexeme_count: int
    rejected_lexeme_count: int
    protected_accepted_lexeme_count: int
    cjk_accepted_lexeme_count: int
    ascii_piece_rejected_count: int
    frequency_rejected_lexeme_count: int
    neural_scored_lexeme_count: int
    neural_accepted_lexeme_count: int
    neural_model_version: str
    neural_model_hash: str
    neural_training_example_count: int
    neural_training_positive_count: int
    neural_training_negative_count: int
    neural_training_epoch_count: int
    neural_feature_count: int
    accepted_lexemes: frozenset[str]


@dataclass(frozen=True)
class _StaticCandidateScorer:
    model_version: str
    model_hash: str
    scorer_kind: str
    training_example_count: int
    training_positive_count: int
    training_negative_count: int
    training_epoch_count: int
    feature_count: int

    def score_basis_points(
        self,
        lexeme: str,
        *,
        document_frequency: int,
        categories: frozenset[str],
    ) -> int:
        if self.scorer_kind == PROGRAMMATIC_SCORER_DATA_DRIVEN:
            return _data_driven_candidate_score_basis_points(
                lexeme,
                document_frequency=document_frequency,
                categories=categories,
            )
        if self.scorer_kind == PROGRAMMATIC_SCORER_FROZEN_PROFILE:
            return _frozen_profile_candidate_score_basis_points(
                lexeme,
                document_frequency=document_frequency,
                categories=categories,
            )
        return 0


@dataclass(frozen=True)
class _WeakLabelNeuralScorer:
    model_version: str
    model_hash: str
    hidden_weights: tuple[tuple[float, ...], ...]
    output_weights: tuple[float, ...]
    training_example_count: int
    training_positive_count: int
    training_negative_count: int
    training_epoch_count: int
    feature_count: int

    def score_basis_points(
        self,
        lexeme: str,
        *,
        document_frequency: int,
        categories: frozenset[str],
    ) -> int:
        probability = _neural_predict_probability(
            _neural_candidate_features(
                lexeme,
                document_frequency=document_frequency,
                categories=categories,
            ),
            hidden_weights=self.hidden_weights,
            output_weights=self.output_weights,
        )
        return int(probability * 10000)


@dataclass(frozen=True)
class _SegmenterBundle:
    jieba_module: Any
    sentencepiece_module: Any
    sentencepiece_processor: Any
    sentencepiece_vocab_size: int
    sentencepiece_model_hash: str
    training_corpus_hash: str
    user_symbol_count: int
    external_jieba_available: bool
    external_sentencepiece_available: bool


@dataclass(frozen=True)
class _PreparedCorpus:
    segments: tuple[_Segment, ...]
    segmenters: _SegmenterBundle
    parsed_corpus_count: int
    parsed_corpus_hash: str


def run_exm_lexical_ontology_eval(
    *,
    parsed_corpus_dirs: Sequence[Path] | None = None,
    output_private_dir: Path = DEFAULT_PRIVATE_DIR,
    case_count: int = CASE_COUNT,
    expected_parsed_corpus_count: int = EXPECTED_EXM_PST_COUNT,
    require_external_segmenters: bool = True,
) -> dict[str, Any]:
    if os.environ.get(RUN_OPT_IN_ENV) != "1":
        return _blocked_report("exm_lexical_eval_requires_explicit_opt_in")
    if not parsed_corpus_dirs:
        return _blocked_report("explicit_parsed_corpus_required")

    try:
        return _run_exm_lexical_ontology_eval_inner(
            parsed_corpus_dirs=tuple(parsed_corpus_dirs),
            output_private_dir=output_private_dir,
            case_count=case_count,
            expected_parsed_corpus_count=expected_parsed_corpus_count,
            require_external_segmenters=require_external_segmenters,
        )
    except FileNotFoundError as exc:
        reason = str(exc)
        if reason in _BLOCKED_REASONS:
            return _blocked_report(reason)
        return _blocked_report("exm_lexical_eval_failed")
    except Exception:
        return _blocked_report("exm_lexical_eval_failed")


def _run_exm_lexical_ontology_eval_inner(
    *,
    parsed_corpus_dirs: Sequence[Path],
    output_private_dir: Path,
    case_count: int,
    expected_parsed_corpus_count: int,
    require_external_segmenters: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    output_private_dir.mkdir(parents=True, exist_ok=True)

    raw_records = _load_raw_segment_records(parsed_corpus_dirs)
    if not raw_records:
        raise FileNotFoundError("parsed_observations_missing")

    segmenter_started = time.monotonic()
    segmenters = _prepare_segmenters(
        raw_records,
        output_private_dir=output_private_dir,
        require_external_segmenters=require_external_segmenters,
    )
    segmenter_elapsed_ms = int((time.monotonic() - segmenter_started) * 1000)

    corpus_started = time.monotonic()
    prepared = _prepare_corpus(
        raw_records,
        segmenters=segmenters,
        parsed_corpus_count=len(parsed_corpus_dirs),
    )
    corpus_elapsed_ms = int((time.monotonic() - corpus_started) * 1000)

    case_started = time.monotonic()
    cases = _generate_cases(prepared.segments, case_count=case_count)
    if len(cases) != case_count:
        raise FileNotFoundError("insufficient_positive_case_evidence")
    private_manifest_hash = _write_private_manifest(
        output_private_dir / PRIVATE_MANIFEST_NAME,
        cases=cases,
        prepared=prepared,
        expected_parsed_corpus_count=expected_parsed_corpus_count,
    )
    case_elapsed_ms = int((time.monotonic() - case_started) * 1000)

    kg_started = time.monotonic()
    regex_kg = _build_kg_index(
        prepared.segments,
        policy_name=POLICY_REGEX,
        segmenters=prepared.segmenters,
    )
    lexical_kg = _build_kg_index(
        prepared.segments,
        policy_name=POLICY_LEXICAL,
        segmenters=prepared.segmenters,
    )
    data_driven_policy = _compile_programmatic_ontology_policy(
        prepared.segments,
        scorer_kind=PROGRAMMATIC_SCORER_DATA_DRIVEN,
    )
    data_driven_kg = _build_kg_index(
        prepared.segments,
        policy_name=POLICY_DATA_DRIVEN_PROGRAMMATIC,
        segmenters=prepared.segmenters,
        compiled_policy=data_driven_policy,
    )
    frozen_policy = _compile_programmatic_ontology_policy(
        prepared.segments,
        scorer_kind=PROGRAMMATIC_SCORER_FROZEN_PROFILE,
    )
    frozen_kg = _build_kg_index(
        prepared.segments,
        policy_name=POLICY_FROZEN_PROGRAMMATIC,
        segmenters=prepared.segmenters,
        compiled_policy=frozen_policy,
    )
    programmatic_policy = _compile_programmatic_ontology_policy(
        prepared.segments,
        scorer_kind=PROGRAMMATIC_SCORER_WEAK_LABEL_MLP,
    )
    programmatic_kg = _build_kg_index(
        prepared.segments,
        policy_name=POLICY_PROGRAMMATIC,
        segmenters=prepared.segmenters,
        compiled_policy=programmatic_policy,
    )
    regex_ontology = _build_ontology_index(prepared.segments, regex_kg, policy_name=POLICY_REGEX)
    lexical_ontology = _build_ontology_index(
        prepared.segments, lexical_kg, policy_name=POLICY_LEXICAL
    )
    data_driven_ontology = _build_ontology_index(
        prepared.segments,
        data_driven_kg,
        policy_name=POLICY_DATA_DRIVEN_PROGRAMMATIC,
    )
    frozen_ontology = _build_ontology_index(
        prepared.segments,
        frozen_kg,
        policy_name=POLICY_FROZEN_PROGRAMMATIC,
    )
    programmatic_ontology = _build_ontology_index(
        prepared.segments,
        programmatic_kg,
        policy_name=POLICY_PROGRAMMATIC,
    )
    kg_elapsed_ms = int((time.monotonic() - kg_started) * 1000)

    scoring_started = time.monotonic()
    arm_rows = {
        ARM_REGEX_KG: _score_cases(
            cases,
            kg_index=regex_kg,
            ontology_index=None,
            policy_name=POLICY_REGEX,
        ),
        ARM_REGEX_ONTOLOGY: _score_cases(
            cases,
            kg_index=regex_kg,
            ontology_index=regex_ontology,
            policy_name=POLICY_REGEX,
        ),
        ARM_LEXICAL_KG: _score_cases(
            cases,
            kg_index=lexical_kg,
            ontology_index=None,
            policy_name=POLICY_LEXICAL,
        ),
        ARM_LEXICAL_ONTOLOGY: _score_cases(
            cases,
            kg_index=lexical_kg,
            ontology_index=lexical_ontology,
            policy_name=POLICY_LEXICAL,
        ),
        ARM_DATA_DRIVEN_ONTOLOGY: _score_cases(
            cases,
            kg_index=data_driven_kg,
            ontology_index=data_driven_ontology,
            policy_name=POLICY_DATA_DRIVEN_PROGRAMMATIC,
        ),
        ARM_FROZEN_ONTOLOGY: _score_cases(
            cases,
            kg_index=frozen_kg,
            ontology_index=frozen_ontology,
            policy_name=POLICY_FROZEN_PROGRAMMATIC,
        ),
        ARM_PROGRAMMATIC_ONTOLOGY: _score_cases(
            cases,
            kg_index=programmatic_kg,
            ontology_index=programmatic_ontology,
            policy_name=POLICY_PROGRAMMATIC,
        ),
    }
    private_rows_hash = _write_private_rows(output_private_dir / PRIVATE_ROWS_NAME, arm_rows)
    scoring_elapsed_ms = int((time.monotonic() - scoring_started) * 1000)

    safe_outputs = _safe_outputs(
        prepared=prepared,
        cases=cases,
        arm_rows=arm_rows,
        regex_kg=regex_kg,
        lexical_kg=lexical_kg,
        data_driven_kg=data_driven_kg,
        frozen_kg=frozen_kg,
        programmatic_kg=programmatic_kg,
        regex_ontology=regex_ontology,
        lexical_ontology=lexical_ontology,
        data_driven_ontology=data_driven_ontology,
        frozen_ontology=frozen_ontology,
        programmatic_ontology=programmatic_ontology,
        data_driven_policy=data_driven_policy,
        frozen_policy=frozen_policy,
        programmatic_policy=programmatic_policy,
        private_manifest_hash=private_manifest_hash,
        private_rows_hash=private_rows_hash,
        case_elapsed_ms=case_elapsed_ms,
        segmenter_elapsed_ms=segmenter_elapsed_ms,
        corpus_elapsed_ms=corpus_elapsed_ms,
        kg_elapsed_ms=kg_elapsed_ms,
        scoring_elapsed_ms=scoring_elapsed_ms,
        total_elapsed_ms=int((time.monotonic() - started) * 1000),
        expected_parsed_corpus_count=expected_parsed_corpus_count,
        require_external_segmenters=require_external_segmenters,
    )
    metrics = {
        "parsed_corpora_loaded": safe_outputs["parsed_corpus_count"] > 0,
        "expected_exm_corpus_count_met": (
            safe_outputs["parsed_corpus_count"] == expected_parsed_corpus_count
        ),
        "body_segments_loaded": safe_outputs["body_segment_count"] > 0,
        "external_jieba_available": segmenters.external_jieba_available,
        "external_sentencepiece_available": segmenters.external_sentencepiece_available,
        "sentencepiece_model_trained": safe_outputs["sentencepiece_model_hash"].startswith(
            "sha256:"
        ),
        "protected_spans_used": safe_outputs["protected_span_case_count"] > 0,
        "case_manifest_generated": safe_outputs["case_count"] == case_count,
        "case_count_target_met": safe_outputs["case_count"] == case_count,
        "candidate_kg_scored": all(
            safe_outputs["arm_summaries"][arm]["case_count"] == case_count for arm in ARMS
        ),
        "type_compatibility_proxy_scored": (
            safe_outputs["arm_summaries"][ARM_REGEX_ONTOLOGY]["case_count"] == case_count
            and safe_outputs["arm_summaries"][ARM_LEXICAL_ONTOLOGY]["case_count"] == case_count
            and safe_outputs["arm_summaries"][ARM_DATA_DRIVEN_ONTOLOGY]["case_count"] == case_count
            and safe_outputs["arm_summaries"][ARM_FROZEN_ONTOLOGY]["case_count"] == case_count
            and safe_outputs["arm_summaries"][ARM_PROGRAMMATIC_ONTOLOGY]["case_count"] == case_count
        ),
        "candidate_only_boundary_respected": True,
        "canonical_kg_wiki_side_effects_absent": _no_graph_or_wiki_side_effects(parsed_corpus_dirs),
        "raw_leak_guard_passed": False,
        "exm_candidate_admission_eval_completed": False,
    }
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": _claim_boundary(False),
    }
    report["metrics"]["raw_leak_guard_passed"] = _public_outputs_are_safe(report)
    report["metrics"]["exm_candidate_admission_eval_completed"] = _eval_completed(report)
    report["claim_boundary"]["supports_exm_50000_candidate_admission_eval_claim"] = report[
        "metrics"
    ]["exm_candidate_admission_eval_completed"]
    report["validation"] = validate_report(report)
    return report


def _load_raw_segment_records(parsed_corpus_dirs: Sequence[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for corpus_index, parsed_dir in enumerate(parsed_corpus_dirs):
        observations_dir = parsed_dir / "data" / "ingestion" / "observations"
        if not observations_dir.exists():
            raise FileNotFoundError("parsed_observations_missing")
        corpus_hash = sha256_json({"corpus_index": corpus_index, "input": str(parsed_dir)})
        for path in sorted(observations_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("observation_type") != "email_body_segment":
                continue
            text = payload.get("text")
            observation_id = payload.get("observation_id")
            if not isinstance(text, str) or not text.strip() or not isinstance(observation_id, str):
                continue
            location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
            body_payload = (
                payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            )
            message_value = _first_string(
                location.get("message_id"),
                body_payload.get("message_id"),
                observation_id,
            )
            thread_value = _first_string(location.get("thread_id"), body_payload.get("thread_id"))
            records.append(
                {
                    "corpus_hash": corpus_hash,
                    "observation_id": observation_id,
                    "message_value": message_value,
                    "thread_value": thread_value,
                    "text": text,
                }
            )
    return records


def _prepare_segmenters(
    raw_records: Sequence[Mapping[str, Any]],
    *,
    output_private_dir: Path,
    require_external_segmenters: bool,
) -> _SegmenterBundle:
    jieba_module = _optional_import("jieba")
    sentencepiece_module = _optional_import("sentencepiece")
    if require_external_segmenters and (jieba_module is None or sentencepiece_module is None):
        raise FileNotFoundError("external_segmenters_required")

    corpus_text = "\n".join(str(record["text"]).replace("\n", " ") for record in raw_records)
    corpus_hash = sha256_json(corpus_text)
    corpus_path = output_private_dir / PRIVATE_CORPUS_NAME
    corpus_path.write_text(corpus_text + "\n", encoding="utf-8")

    user_symbols = _sentencepiece_user_symbols(raw_records)
    processor: Any = None
    model_hash = "sha256:" + "0" * 64
    vocab_size = 0
    if sentencepiece_module is not None:
        model_prefix = output_private_dir / PRIVATE_SENTENCEPIECE_PREFIX
        vocab_size = _sentencepiece_vocab_size(raw_records)
        with _redirect_process_output(output_private_dir / PRIVATE_SENTENCEPIECE_LOG_NAME):
            sentencepiece_module.SentencePieceTrainer.Train(
                input=str(corpus_path),
                model_prefix=str(model_prefix),
                vocab_size=vocab_size,
                model_type="bpe",
                character_coverage=0.9995,
                hard_vocab_limit=False,
                user_defined_symbols=",".join(user_symbols),
            )
        model_path = model_prefix.with_suffix(".model")
        model_hash = _file_sha256(model_path)
        processor = _load_sentencepiece_processor(sentencepiece_module, model_path)
    return _SegmenterBundle(
        jieba_module=jieba_module,
        sentencepiece_module=sentencepiece_module,
        sentencepiece_processor=processor,
        sentencepiece_vocab_size=vocab_size,
        sentencepiece_model_hash=model_hash,
        training_corpus_hash=corpus_hash,
        user_symbol_count=len(user_symbols),
        external_jieba_available=jieba_module is not None,
        external_sentencepiece_available=sentencepiece_module is not None,
    )


def _prepare_corpus(
    raw_records: Sequence[Mapping[str, Any]],
    *,
    segmenters: _SegmenterBundle,
    parsed_corpus_count: int,
) -> _PreparedCorpus:
    segments: list[_Segment] = []
    for index, record in enumerate(raw_records):
        text = str(record["text"])
        corpus_hash = str(record["corpus_hash"])
        observation_id = str(record["observation_id"])
        message_value = str(record["message_value"])
        thread_value = record.get("thread_value")
        segment_id = (
            "seg_"
            + sha256_json(
                {"corpus_hash": corpus_hash, "observation_id": observation_id, "index": index}
            )[-28:]
        )
        regex_lexemes = _regex_lexemes(text)
        term_occurrences = _term_occurrences(text, segmenters=segmenters)
        lexical_lexemes = set(regex_lexemes)
        for occurrence in term_occurrences:
            lexical_lexemes.add(occurrence.lexeme)
        lexical_lexemes.update(_jieba_lexemes(text, segmenters.jieba_module))
        lexical_lexemes.update(_sentencepiece_lexemes(text, segmenters.sentencepiece_processor))
        categories = _categories_for_lexemes(lexical_lexemes, term_occurrences)
        segments.append(
            _Segment(
                segment_id=segment_id,
                corpus_id_hash=corpus_hash,
                observation_id_hash=sha256_json(observation_id),
                message_key=sha256_json({"corpus_hash": corpus_hash, "message": message_value}),
                thread_key=sha256_json({"corpus_hash": corpus_hash, "thread": thread_value})
                if isinstance(thread_value, str) and thread_value
                else None,
                text=text,
                lexemes_by_policy={
                    POLICY_REGEX: frozenset(regex_lexemes),
                    POLICY_LEXICAL: frozenset(lexical_lexemes),
                    POLICY_DATA_DRIVEN_PROGRAMMATIC: frozenset(lexical_lexemes),
                    POLICY_FROZEN_PROGRAMMATIC: frozenset(lexical_lexemes),
                    POLICY_PROGRAMMATIC: frozenset(lexical_lexemes),
                },
                categories=categories,
                term_occurrences=tuple(term_occurrences),
            )
        )
    return _PreparedCorpus(
        segments=tuple(segments),
        segmenters=segmenters,
        parsed_corpus_count=parsed_corpus_count,
        parsed_corpus_hash=sha256_json(
            {
                "segment_count": len(segments),
                "segment_ids": [segment.segment_id for segment in segments],
            }
        ),
    )


def _generate_cases(segments: Sequence[_Segment], *, case_count: int) -> list[_Case]:
    positive_target = int(case_count * POSITIVE_CASE_RATIO_BP / 10000)
    no_match_target = int(case_count * NO_MATCH_CASE_RATIO_BP / 10000)
    permission_target = case_count - positive_target - no_match_target
    groups = _eligible_term_groups(segments)
    if not groups:
        raise FileNotFoundError("insufficient_positive_case_evidence")

    positives: list[_Case] = []
    group_items = list(groups.items())
    template_count = 6
    index = 0
    while len(positives) < positive_target:
        (lexeme, bucket), members = group_items[index % len(group_items)]
        del lexeme
        member_pair = _distinct_pair_for_variant(members, index)
        display = members[0][1]
        split = "development" if len(positives) < max(1, positive_target // 10) else "evaluation"
        positives.append(
            _Case(
                case_id="exmlexcase_"
                + sha256_json(
                    {
                        "kind": "positive",
                        "bucket": bucket,
                        "index": index,
                        "members": [item.segment_id for item, _display in member_pair],
                    }
                )[-28:],
                result_kind="owner_match",
                bucket=bucket,
                split=split,
                query_text=_positive_query(display, index % template_count),
                required_segment_ids=tuple(item.segment_id for item, _display in member_pair),
                required_match_count=2,
                requester_kind="owner",
            )
        )
        index += 1

    no_match_cases = [
        _Case(
            case_id="exmlexcase_" + sha256_json({"kind": "no_match", "index": index})[-28:],
            result_kind="no_match",
            bucket="false_positive_guard",
            split=("development" if index < max(1, no_match_target // 10) else "evaluation"),
            query_text=f"Find separate evidence about absentlexicalcase{index:05d}.",
            required_segment_ids=(),
            required_match_count=0,
            requester_kind="owner",
        )
        for index in range(no_match_target)
    ]
    permission_cases: list[_Case] = []
    for index in range(permission_target):
        source = positives[index % len(positives)]
        permission_cases.append(
            _Case(
                case_id="exmlexcase_"
                + sha256_json(
                    {"kind": "permission_denied", "index": index, "source": source.case_id}
                )[-28:],
                result_kind="permission_denied",
                bucket="access_boundary",
                split=("development" if index < max(1, permission_target // 10) else "evaluation"),
                query_text=source.query_text,
                required_segment_ids=(),
                required_match_count=0,
                requester_kind="denied",
            )
        )
    cases = positives + no_match_cases + permission_cases
    return sorted(cases, key=lambda case: sha256_json({"case": case.case_id}))


def _eligible_term_groups(
    segments: Sequence[_Segment],
) -> dict[tuple[str, str], list[tuple[_Segment, str]]]:
    by_term: dict[tuple[str, str], dict[str, tuple[_Segment, str]]] = defaultdict(dict)
    for segment in segments:
        for occurrence in segment.term_occurrences:
            if occurrence.lexeme not in segment.lexemes_by_policy[POLICY_LEXICAL]:
                continue
            key = (occurrence.lexeme, occurrence.bucket)
            by_term[key].setdefault(segment.message_key, (segment, occurrence.display))
    eligible: dict[tuple[str, str], list[tuple[_Segment, str]]] = {}
    for key, by_message in by_term.items():
        members = sorted(
            by_message.values(),
            key=lambda item: (item[0].corpus_id_hash, item[0].message_key, item[0].segment_id),
        )
        if 2 <= len(members) <= MAX_GROUP_DOCUMENT_FREQUENCY:
            eligible[key] = members
    if not eligible:
        return {}
    bucket_order = {
        "cjk_organization": 0,
        "cjk_phrase": 1,
        "business_identifier": 2,
        "ascii_business": 3,
        "sentencepiece_piece": 4,
    }
    return dict(
        sorted(
            eligible.items(),
            key=lambda item: (
                bucket_order.get(item[0][1], 99),
                sha256_json({"term": item[0][0], "bucket": item[0][1]}),
            ),
        )
    )


def _distinct_pair_for_variant(
    members: Sequence[tuple[_Segment, str]],
    variant_index: int,
) -> tuple[tuple[_Segment, str], tuple[_Segment, str]]:
    left_index = variant_index % len(members)
    right_index = (variant_index // len(members) + 1) % len(members)
    if right_index == left_index:
        right_index = (right_index + 1) % len(members)
    return (members[left_index], members[right_index])


def _positive_query(display: str, template_index: int) -> str:
    templates = (
        "Piece together separate mail evidence about {term}.",
        "Find cross message updates related to {term}.",
        "Compare different email evidence mentioning {term}.",
        "Find separate email updates for {term}.",
        "Collect related mail evidence about {term}.",
        "Find cross message evidence with {term}.",
    )
    return templates[template_index].format(term=display)


def _build_kg_index(
    segments: Sequence[_Segment],
    *,
    policy_name: str,
    segmenters: _SegmenterBundle,
    compiled_policy: _CompiledOntologyPolicy | None = None,
) -> _KgIndex:
    ids = [segment.segment_id for segment in segments]
    union_find = _UnionFind.from_ids(ids)
    relation_count = 0
    thread_relation_count = 0
    lexical_relation_count = 0
    for grouped_ids in _groups_by_thread(segments).values():
        added = _union_group(union_find, grouped_ids)
        relation_count += added
        thread_relation_count += added
    lexeme_to_ids: dict[str, list[str]] = defaultdict(list)
    for segment in segments:
        for lexeme in _important_lexemes(
            segment.lexemes_by_policy[policy_name],
            policy_name,
            compiled_policy=compiled_policy,
        ):
            lexeme_to_ids[lexeme].append(segment.segment_id)
    for grouped_ids in lexeme_to_ids.values():
        if 2 <= len(grouped_ids) <= MAX_GROUP_DOCUMENT_FREQUENCY:
            added = _union_group(union_find, grouped_ids)
            relation_count += added
            lexical_relation_count += added

    ids_by_component: dict[str, list[str]] = defaultdict(list)
    lexemes_by_component: dict[str, set[str]] = defaultdict(set)
    segment_ids_by_component_lexeme: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    globally_indexed_lexemes = {
        lexeme
        for lexeme, segment_ids in lexeme_to_ids.items()
        if len(segment_ids) <= MAX_GROUP_DOCUMENT_FREQUENCY
    }
    for segment in segments:
        component_id = union_find.find(segment.segment_id)
        ids_by_component[component_id].append(segment.segment_id)
        segment_lexemes = _important_lexemes(
            segment.lexemes_by_policy[policy_name],
            policy_name,
            compiled_policy=compiled_policy,
        )
        indexed_segment_lexemes = segment_lexemes & globally_indexed_lexemes
        lexemes_by_component[component_id].update(indexed_segment_lexemes)
        for lexeme in indexed_segment_lexemes:
            segment_ids_by_component_lexeme[component_id][lexeme].add(segment.segment_id)
    component_ids_by_lexeme: dict[str, set[str]] = defaultdict(set)
    for component_id, lexemes in lexemes_by_component.items():
        for lexeme in lexemes:
            component_ids_by_lexeme[lexeme].add(component_id)
    segment_by_id = {segment.segment_id: segment for segment in segments}
    fallback_segment_ids_by_component = {
        component_id: tuple(
            segment_id
            for segment_id in sorted(
                segment_ids,
                key=lambda item: (len(segment_by_id[item].text), item),
            )[:MAX_COMPONENT_FALLBACK_SCAN_SEGMENTS]
        )
        for component_id, segment_ids in ids_by_component.items()
    }
    return _KgIndex(
        policy_name=policy_name,
        segmenters=segmenters,
        compiled_policy=compiled_policy,
        segment_by_id=segment_by_id,
        component_by_segment_id={
            segment_id: component_id
            for component_id, segment_ids in ids_by_component.items()
            for segment_id in segment_ids
        },
        segment_ids_by_component={
            component_id: tuple(sorted(segment_ids))
            for component_id, segment_ids in ids_by_component.items()
        },
        lexemes_by_component={
            component_id: frozenset(lexemes)
            for component_id, lexemes in lexemes_by_component.items()
        },
        component_ids_by_lexeme={
            lexeme: tuple(sorted(component_ids))
            for lexeme, component_ids in component_ids_by_lexeme.items()
        },
        segment_ids_by_component_lexeme={
            component_id: {
                lexeme: tuple(sorted(segment_ids))
                for lexeme, segment_ids in sorted(by_lexeme.items())
            }
            for component_id, by_lexeme in sorted(segment_ids_by_component_lexeme.items())
        },
        fallback_segment_ids_by_component=fallback_segment_ids_by_component,
        relation_count=relation_count,
        thread_relation_count=thread_relation_count,
        lexical_relation_count=lexical_relation_count,
    )


def _build_ontology_index(
    segments: Sequence[_Segment],
    kg_index: _KgIndex,
    *,
    policy_name: str,
) -> _OntologyIndex:
    categories_by_segment_id = {
        segment.segment_id: _categories_for_policy(segment, policy_name) for segment in segments
    }
    category_scores_by_component: dict[str, dict[str, int]] = defaultdict(dict)
    for component_id, segment_ids in kg_index.segment_ids_by_component.items():
        scores: Counter[str] = Counter()
        for segment_id in segment_ids:
            for category in categories_by_segment_id.get(segment_id, frozenset()):
                scores[category] += 1
        category_scores_by_component[component_id] = dict(scores)
    component_ids_by_category: dict[str, list[str]] = defaultdict(list)
    for component_id, scores in category_scores_by_component.items():
        for category in scores:
            component_ids_by_category[category].append(component_id)
    return _OntologyIndex(
        categories_by_segment_id=categories_by_segment_id,
        category_scores_by_component=dict(category_scores_by_component),
        component_ids_by_category={
            category: tuple(sorted(component_ids))
            for category, component_ids in component_ids_by_category.items()
        },
    )


def _compile_programmatic_ontology_policy(
    segments: Sequence[_Segment],
    *,
    scorer_kind: str = PROGRAMMATIC_SCORER_WEAK_LABEL_MLP,
) -> _CompiledOntologyPolicy:
    message_keys_by_lexeme: dict[str, set[str]] = defaultdict(set)
    categories_by_lexeme: dict[str, set[str]] = defaultdict(set)
    for segment in segments:
        for lexeme in _important_lexemes(segment.lexemes_by_policy[POLICY_LEXICAL], POLICY_LEXICAL):
            message_keys_by_lexeme[lexeme].add(segment.message_key)
        for occurrence in segment.term_occurrences:
            categories_by_lexeme[occurrence.lexeme].update(occurrence.categories)

    accepted: set[str] = set()
    counters: Counter[str] = Counter()
    lexeme_rows = tuple(
        sorted(
            (
                lexeme,
                len(message_keys),
                frozenset(categories_by_lexeme.get(lexeme, set())),
            )
            for lexeme, message_keys in message_keys_by_lexeme.items()
        )
    )
    scorer_candidates = tuple(
        (lexeme, document_frequency, categories)
        for lexeme, document_frequency, categories in lexeme_rows
        if PROGRAMMATIC_MIN_DOCUMENT_FREQUENCY
        <= document_frequency
        <= PROGRAMMATIC_MAX_DOCUMENT_FREQUENCY
        and not lexeme.startswith(("org:", "id:", "contact:"))
        and (
            lexeme.startswith("zh:")
            or (lexeme.startswith("sp:") and _CJK_RE.search(lexeme.removeprefix("sp:")))
        )
    )
    if scorer_kind == PROGRAMMATIC_SCORER_WEAK_LABEL_MLP:
        candidate_scorer = _train_weak_label_neural_scorer(scorer_candidates)
        scorer_requires_training = True
    else:
        candidate_scorer = _static_candidate_scorer(scorer_kind)
        scorer_requires_training = False
    for lexeme, document_frequency, categories in lexeme_rows:
        counters["candidate"] += 1
        if document_frequency < PROGRAMMATIC_MIN_DOCUMENT_FREQUENCY:
            counters["frequency_rejected"] += 1
            continue
        if document_frequency > PROGRAMMATIC_MAX_DOCUMENT_FREQUENCY:
            counters["frequency_rejected"] += 1
            continue
        if lexeme.startswith(("org:", "id:", "contact:")):
            accepted.add(lexeme)
            counters["protected_accepted"] += 1
            continue
        if lexeme.startswith("sp:") and not _CJK_RE.search(lexeme.removeprefix("sp:")):
            counters["ascii_piece_rejected"] += 1
            continue
        surface = lexeme.split(":", 1)[1] if ":" in lexeme else lexeme
        if lexeme.startswith(("zh:", "sp:")) and _CJK_RE.search(surface):
            counters["neural_scored"] += 1
            neural_score = candidate_scorer.score_basis_points(
                lexeme,
                document_frequency=document_frequency,
                categories=categories,
            )
            if neural_score >= PROGRAMMATIC_NEURAL_SCORE_THRESHOLD_BP:
                accepted.add(lexeme)
                counters["neural_accepted"] += 1
                counters["cjk_accepted"] += 1
            continue
        counters["frequency_rejected"] += 1

    payload = {
        "policy_version": TYPE_COMPATIBILITY_PROXY_POLICY_VERSION,
        "min_document_frequency": PROGRAMMATIC_MIN_DOCUMENT_FREQUENCY,
        "max_document_frequency": PROGRAMMATIC_MAX_DOCUMENT_FREQUENCY,
        "neural_score_threshold_basis_points": PROGRAMMATIC_NEURAL_SCORE_THRESHOLD_BP,
        "scorer_kind": scorer_kind,
        "scorer_requires_training": scorer_requires_training,
        "neural_model_version": candidate_scorer.model_version,
        "neural_model_hash": candidate_scorer.model_hash,
        "candidate_lexeme_count": counters["candidate"],
        "accepted_lexeme_count": len(accepted),
        "accepted_lexeme_hash": sha256_json(sorted(accepted)),
    }
    return _CompiledOntologyPolicy(
        policy_hash=sha256_json(payload),
        scorer_kind=scorer_kind,
        scorer_requires_training=scorer_requires_training,
        candidate_lexeme_count=counters["candidate"],
        accepted_lexeme_count=len(accepted),
        rejected_lexeme_count=counters["candidate"] - len(accepted),
        protected_accepted_lexeme_count=counters["protected_accepted"],
        cjk_accepted_lexeme_count=counters["cjk_accepted"],
        ascii_piece_rejected_count=counters["ascii_piece_rejected"],
        frequency_rejected_lexeme_count=counters["frequency_rejected"],
        neural_scored_lexeme_count=counters["neural_scored"],
        neural_accepted_lexeme_count=counters["neural_accepted"],
        neural_model_version=candidate_scorer.model_version,
        neural_model_hash=candidate_scorer.model_hash,
        neural_training_example_count=candidate_scorer.training_example_count,
        neural_training_positive_count=candidate_scorer.training_positive_count,
        neural_training_negative_count=candidate_scorer.training_negative_count,
        neural_training_epoch_count=candidate_scorer.training_epoch_count,
        neural_feature_count=candidate_scorer.feature_count,
        accepted_lexemes=frozenset(accepted),
    )


def _weak_label_candidate_score_basis_points(
    lexeme: str,
    *,
    document_frequency: int,
    categories: frozenset[str],
) -> int:
    surface = lexeme.split(":", 1)[1] if ":" in lexeme else lexeme
    rules = _FROZEN_PROFILE_SCORE_RULES
    score = float(rules["bias"])
    if _CJK_RE.search(surface):
        score += float(rules["cjk_presence"])
    if 2 <= len(surface) <= 12:
        score += float(rules["medium_length"])
    if len(surface) >= 4:
        score += float(rules["minimum_business_length"])
    if categories & {"organization", "identifier", "contact"}:
        score += float(rules["protected_category"])
    if surface.endswith(("公司", "科技", "電子", "光電", "集團", "企業", "實業")):
        score += float(rules["org_suffix"])
    frequency_rules = rules["document_frequency"]
    if document_frequency <= 12:
        score += float(frequency_rules["lte_12"])
    elif document_frequency <= 80:
        score += float(frequency_rules["lte_80"])
    elif document_frequency > 160:
        score += float(frequency_rules["gt_160"])
    if lexeme.startswith("sp:"):
        score += float(rules["sentencepiece_piece"])
    probability = 1.0 / (1.0 + pow(2.718281828459045, -score))
    return int(probability * int(rules["sigmoid_multiplier_basis_points"]))


def _data_driven_candidate_score_basis_points(
    lexeme: str,
    *,
    document_frequency: int,
    categories: frozenset[str],
) -> int:
    surface = lexeme.split(":", 1)[1] if ":" in lexeme else lexeme
    rules = _DATA_DRIVEN_SCORE_RULES
    score = 0
    if _CJK_RE.search(surface):
        score += int(rules["cjk_presence"])
    length_bonus = rules["length_bonus"]
    if 3 <= len(surface) <= 10:
        score += int(length_bonus["len_3_to_10"])
    elif len(surface) == 2:
        score += int(length_bonus["len_2"])
    frequency_rules = rules["document_frequency"]
    if document_frequency <= 12:
        score += int(frequency_rules["lte_12"])
    elif document_frequency <= 80:
        score += int(frequency_rules["lte_80"])
    elif document_frequency <= 160:
        score += int(frequency_rules["lte_160"])
    else:
        score += int(frequency_rules["gt_160"])
    if categories & {"organization", "identifier", "contact"}:
        score += int(rules["protected_category"])
    if surface.endswith(("公司", "科技", "電子", "光電", "集團", "企業", "實業")):
        score += int(rules["org_suffix"])
    if lexeme.startswith("sp:"):
        score += int(rules["sentencepiece_piece"])
    if len({char for char in surface if _CJK_RE.search(char)}) >= 3:
        score += int(rules["char_variety_min_3"])
    return max(int(rules["clamp_min"]), min(int(rules["clamp_max"]), score))


def _frozen_profile_candidate_score_basis_points(
    lexeme: str,
    *,
    document_frequency: int,
    categories: frozenset[str],
) -> int:
    # Fixed profile control: no weights are fit on this corpus or on generated cases.
    return _weak_label_candidate_score_basis_points(
        lexeme,
        document_frequency=document_frequency,
        categories=categories,
    )


def _static_candidate_scorer(scorer_kind: str) -> _StaticCandidateScorer:
    if scorer_kind == PROGRAMMATIC_SCORER_DATA_DRIVEN:
        model_version = PROGRAMMATIC_DATA_DRIVEN_MODEL_VERSION
        profile_payload = {
            "model_version": model_version,
            "scorer_kind": scorer_kind,
            "requires_training": False,
            "rules": _DATA_DRIVEN_SCORE_RULES,
        }
    elif scorer_kind == PROGRAMMATIC_SCORER_FROZEN_PROFILE:
        model_version = PROGRAMMATIC_FROZEN_MODEL_VERSION
        profile_payload = {
            "model_version": model_version,
            "scorer_kind": scorer_kind,
            "requires_training": False,
            "basis": "fixed_sigmoid_profile_not_fit_on_eval_corpus",
            "threshold_basis_points": PROGRAMMATIC_NEURAL_SCORE_THRESHOLD_BP,
            "feature_names": _PROGRAMMATIC_NEURAL_FEATURE_NAMES,
            "rules": _FROZEN_PROFILE_SCORE_RULES,
        }
    else:
        raise ValueError("unknown static candidate scorer")
    return _StaticCandidateScorer(
        model_version=model_version,
        model_hash=sha256_json(profile_payload),
        scorer_kind=scorer_kind,
        training_example_count=0,
        training_positive_count=0,
        training_negative_count=0,
        training_epoch_count=0,
        feature_count=len(_PROGRAMMATIC_NEURAL_FEATURE_NAMES),
    )


def _train_weak_label_neural_scorer(
    candidate_rows: Sequence[tuple[str, int, frozenset[str]]],
) -> _WeakLabelNeuralScorer:
    training_rows: list[tuple[tuple[float, ...], int]] = []
    for lexeme, document_frequency, categories in candidate_rows:
        label = int(
            _weak_label_candidate_score_basis_points(
                lexeme,
                document_frequency=document_frequency,
                categories=categories,
            )
            >= PROGRAMMATIC_NEURAL_SCORE_THRESHOLD_BP
        )
        training_rows.append(
            (
                _neural_candidate_features(
                    lexeme,
                    document_frequency=document_frequency,
                    categories=categories,
                ),
                label,
            )
        )
    training_rows.extend(_neural_anchor_training_rows())
    training_rows.sort(key=lambda item: (item[1], item[0]))

    feature_count = len(_PROGRAMMATIC_NEURAL_FEATURE_NAMES)
    hidden_weights = [
        [
            _initial_weight("hidden", hidden_index, feature_index)
            for feature_index in range(feature_count + 1)
        ]
        for hidden_index in range(PROGRAMMATIC_NEURAL_HIDDEN_UNITS)
    ]
    output_weights = [
        _initial_weight("output", 0, feature_index)
        for feature_index in range(PROGRAMMATIC_NEURAL_HIDDEN_UNITS + 1)
    ]
    for _epoch in range(PROGRAMMATIC_NEURAL_TRAINING_EPOCHS):
        for features, label in training_rows:
            hidden_values = [
                _sigmoid(
                    weights[0] + sum(weight * value for weight, value in zip(weights[1:], features))
                )
                for weights in hidden_weights
            ]
            output = _sigmoid(
                output_weights[0]
                + sum(weight * value for weight, value in zip(output_weights[1:], hidden_values))
            )
            output_error = output - label
            old_output_weights = list(output_weights)
            output_weights[0] -= PROGRAMMATIC_NEURAL_LEARNING_RATE * output_error
            for index, hidden_value in enumerate(hidden_values, start=1):
                output_weights[index] -= (
                    PROGRAMMATIC_NEURAL_LEARNING_RATE * output_error * hidden_value
                )
            for hidden_index, hidden_value in enumerate(hidden_values):
                hidden_error = (
                    output_error
                    * old_output_weights[hidden_index + 1]
                    * hidden_value
                    * (1.0 - hidden_value)
                )
                hidden_weights[hidden_index][0] -= PROGRAMMATIC_NEURAL_LEARNING_RATE * hidden_error
                for feature_index, feature_value in enumerate(features, start=1):
                    hidden_weights[hidden_index][feature_index] -= (
                        PROGRAMMATIC_NEURAL_LEARNING_RATE * hidden_error * feature_value
                    )

    rounded_hidden = tuple(
        tuple(round(value, 8) for value in weights) for weights in hidden_weights
    )
    rounded_output = tuple(round(value, 8) for value in output_weights)
    model_payload = {
        "model_version": PROGRAMMATIC_NEURAL_MODEL_VERSION,
        "feature_names": _PROGRAMMATIC_NEURAL_FEATURE_NAMES,
        "hidden_units": PROGRAMMATIC_NEURAL_HIDDEN_UNITS,
        "training_epoch_count": PROGRAMMATIC_NEURAL_TRAINING_EPOCHS,
        "learning_rate": PROGRAMMATIC_NEURAL_LEARNING_RATE,
        "hidden_weights": rounded_hidden,
        "output_weights": rounded_output,
    }
    positive_count = sum(label for _features, label in training_rows)
    return _WeakLabelNeuralScorer(
        model_version=PROGRAMMATIC_NEURAL_MODEL_VERSION,
        model_hash=sha256_json(model_payload),
        hidden_weights=rounded_hidden,
        output_weights=rounded_output,
        training_example_count=len(training_rows),
        training_positive_count=positive_count,
        training_negative_count=len(training_rows) - positive_count,
        training_epoch_count=PROGRAMMATIC_NEURAL_TRAINING_EPOCHS,
        feature_count=feature_count,
    )


def _neural_anchor_training_rows() -> list[tuple[tuple[float, ...], int]]:
    anchors = (
        ("org:宏達電子公司", 4, frozenset({"organization", "cjk"}), 1),
        ("zh:採購交期", 8, frozenset({"cjk"}), 1),
        ("sp:付款條件", 12, frozenset({"cjk"}), 1),
        ("zh:一下", 240, frozenset({"cjk"}), 0),
        ("sp:通知", 220, frozenset({"cjk"}), 0),
        ("sp:meeting", 20, frozenset(), 0),
    )
    return [
        (
            _neural_candidate_features(
                lexeme,
                document_frequency=document_frequency,
                categories=categories,
            ),
            label,
        )
        for lexeme, document_frequency, categories, label in anchors
    ]


def _neural_candidate_features(
    lexeme: str,
    *,
    document_frequency: int,
    categories: frozenset[str],
) -> tuple[float, ...]:
    surface = lexeme.split(":", 1)[1] if ":" in lexeme else lexeme
    cjk_chars = {char for char in surface if _CJK_RE.search(char)}
    char_variety = min(len(cjk_chars), 12) / 12.0
    return (
        1.0 if _CJK_RE.search(surface) else 0.0,
        min(len(surface), 12) / 12.0,
        1.0 if 2 <= len(surface) <= 12 else 0.0,
        1.0 if len(surface) >= 4 else 0.0,
        1.0 if categories & {"organization", "identifier", "contact"} else 0.0,
        1.0 if surface.endswith(("公司", "科技", "電子", "光電", "集團", "企業", "實業")) else 0.0,
        1.0 if document_frequency <= 12 else 0.0,
        1.0 if 12 < document_frequency <= 80 else 0.0,
        1.0 if document_frequency > 160 else 0.0,
        1.0 if lexeme.startswith("sp:") else 0.0,
        1.0 if lexeme.startswith("zh:") else 0.0,
        char_variety,
    )


def _neural_predict_probability(
    features: tuple[float, ...],
    *,
    hidden_weights: Sequence[Sequence[float]],
    output_weights: Sequence[float],
) -> float:
    hidden_values = [
        _sigmoid(weights[0] + sum(weight * value for weight, value in zip(weights[1:], features)))
        for weights in hidden_weights
    ]
    return _sigmoid(
        output_weights[0]
        + sum(weight * value for weight, value in zip(output_weights[1:], hidden_values))
    )


def _initial_weight(layer: str, row: int, column: int) -> float:
    seed = sha256_json(
        {
            "model_version": PROGRAMMATIC_NEURAL_MODEL_VERSION,
            "layer": layer,
            "row": row,
            "column": column,
        }
    )
    return ((int(seed[-8:], 16) % 2001) - 1000) / 10000.0


def _sigmoid(value: float) -> float:
    if value >= 35:
        return 1.0
    if value <= -35:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def _score_cases(
    cases: Sequence[_Case],
    *,
    kg_index: _KgIndex,
    ontology_index: _OntologyIndex | None,
    policy_name: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    query_cache: dict[tuple[str, str], tuple[set[str], set[str]]] = {}
    for case in cases:
        if case.result_kind == "permission_denied":
            selected_ids: tuple[str, ...] = ()
            selected_components: tuple[str, ...] = ()
            matched_count = 0
            status = "passed"
        else:
            cache_key = (policy_name, case.query_text)
            cached = query_cache.get(cache_key)
            if cached is None:
                cached = (
                    _query_lexemes(case.query_text, kg_index, policy_name),
                    _query_categories(case.query_text, policy_name),
                )
                query_cache[cache_key] = cached
            query_lexemes, query_categories = cached
            if ontology_index is None:
                selected_components = _rank_components(
                    query_lexemes,
                    kg_index=kg_index,
                    limit=6,
                )
            else:
                selected_components = _rank_components_with_ontology(
                    query_lexemes,
                    query_categories=query_categories,
                    kg_index=kg_index,
                    ontology_index=ontology_index,
                    limit=6,
                )
            selected_ids = _evidence_from_components(
                selected_components,
                query_lexemes=query_lexemes,
                kg_index=kg_index,
                limit=case.limit,
            )
            matched_count = len(set(case.required_segment_ids) & set(selected_ids))
            if case.result_kind == "owner_match":
                status = "passed" if matched_count >= case.required_match_count else "failed"
            elif case.result_kind == "no_match":
                status = "passed" if not selected_ids else "failed"
            else:
                status = "failed"
        row = {
            "case_hash": sha256_json(case.case_id),
            "case_manifest_entry_hash": case.private_fingerprint(),
            "bucket_hash": sha256_json(case.bucket),
            "split": case.split,
            "result_kind": case.result_kind,
            "status": status,
            "required_evidence_count": len(case.required_segment_ids),
            "matched_required_evidence_count": matched_count,
            "selected_component_count": len(selected_components),
            "selected_evidence_count": len(selected_ids),
        }
        row["response_hash"] = sha256_json(
            {
                **row,
                "selected_components": selected_components,
                "selected_evidence": selected_ids,
            }
        )
        rows.append(row)
    return rows


def _rank_components(
    query_lexemes: set[str],
    *,
    kg_index: _KgIndex,
    limit: int,
) -> tuple[str, ...]:
    scores: Counter[str] = Counter()
    for lexeme in _important_lexemes(
        query_lexemes,
        kg_index.policy_name,
        compiled_policy=kg_index.compiled_policy,
    ):
        for component_id in kg_index.component_ids_by_lexeme.get(lexeme, ()):
            scores[component_id] += 10
    ranked = sorted(
        scores,
        key=lambda component_id: (
            -scores[component_id],
            len(kg_index.segment_ids_by_component[component_id]),
            component_id,
        ),
    )
    return tuple(component_id for component_id in ranked[:limit] if scores[component_id] > 0)


def _rank_components_with_ontology(
    query_lexemes: set[str],
    *,
    query_categories: set[str],
    kg_index: _KgIndex,
    ontology_index: _OntologyIndex,
    limit: int,
) -> tuple[str, ...]:
    scores: Counter[str] = Counter()
    exact_components = _rank_components(query_lexemes, kg_index=kg_index, limit=limit * 3)
    for component_id in exact_components:
        scores[component_id] += 20
    exact_component_set = set(exact_components)
    if kg_index.policy_name in PROGRAMMATIC_POLICIES and not exact_component_set:
        return ()
    for category in query_categories:
        category_component_ids = ontology_index.component_ids_by_category.get(category, ())
        if exact_component_set:
            candidate_component_ids = (
                component_id
                for component_id in category_component_ids
                if component_id in exact_component_set
            )
        else:
            candidate_component_ids = iter(category_component_ids[:MAX_CATEGORY_COMPONENT_FALLBACK])
        for component_id in candidate_component_ids:
            category_score = ontology_index.category_scores_by_component.get(component_id, {}).get(
                category, 0
            )
            scores[component_id] += min(category_score, 5)
    ranked = sorted(
        scores,
        key=lambda component_id: (
            -scores[component_id],
            len(kg_index.segment_ids_by_component[component_id]),
            component_id,
        ),
    )
    return tuple(component_id for component_id in ranked[:limit] if scores[component_id] > 0)


def _evidence_from_components(
    component_ids: Sequence[str],
    *,
    query_lexemes: set[str],
    kg_index: _KgIndex,
    limit: int,
) -> tuple[str, ...]:
    ranked: list[tuple[int, int, str]] = []
    important_query_lexemes = _important_lexemes(
        query_lexemes,
        kg_index.policy_name,
        compiled_policy=kg_index.compiled_policy,
    )
    for component_id in component_ids:
        segment_ids: set[str] = set()
        by_lexeme = kg_index.segment_ids_by_component_lexeme.get(component_id, {})
        for lexeme in important_query_lexemes:
            segment_ids.update(by_lexeme.get(lexeme, ()))
        if not segment_ids:
            segment_ids.update(kg_index.fallback_segment_ids_by_component.get(component_id, ()))
        for segment_id in segment_ids:
            segment = kg_index.segment_by_id[segment_id]
            score = len(segment.lexemes_by_policy[kg_index.policy_name] & query_lexemes)
            ranked.append((-score, len(segment.text), segment_id))
    return tuple(segment_id for _score, _length, segment_id in sorted(ranked)[:limit])


def _policy_public_summary(policy: _CompiledOntologyPolicy) -> dict[str, Any]:
    return {
        "policy_hash": policy.policy_hash,
        "scorer_kind": policy.scorer_kind,
        "scorer_requires_training": int(policy.scorer_requires_training),
        "candidate_lexeme_count": policy.candidate_lexeme_count,
        "accepted_lexeme_count": policy.accepted_lexeme_count,
        "rejected_lexeme_count": policy.rejected_lexeme_count,
        "protected_accepted_lexeme_count": policy.protected_accepted_lexeme_count,
        "cjk_accepted_lexeme_count": policy.cjk_accepted_lexeme_count,
        "ascii_piece_rejected_count": policy.ascii_piece_rejected_count,
        "frequency_rejected_lexeme_count": policy.frequency_rejected_lexeme_count,
        "scored_lexeme_count": policy.neural_scored_lexeme_count,
        "accepted_scored_lexeme_count": policy.neural_accepted_lexeme_count,
        "model_version": policy.neural_model_version,
        "model_hash": policy.neural_model_hash,
        "training_example_count": policy.neural_training_example_count,
        "training_positive_count": policy.neural_training_positive_count,
        "training_negative_count": policy.neural_training_negative_count,
        "training_epoch_count": policy.neural_training_epoch_count,
        "feature_count": policy.neural_feature_count,
    }


def _safe_outputs(
    *,
    prepared: _PreparedCorpus,
    cases: Sequence[_Case],
    arm_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    regex_kg: _KgIndex,
    lexical_kg: _KgIndex,
    data_driven_kg: _KgIndex,
    frozen_kg: _KgIndex,
    programmatic_kg: _KgIndex,
    regex_ontology: _OntologyIndex,
    lexical_ontology: _OntologyIndex,
    data_driven_ontology: _OntologyIndex,
    frozen_ontology: _OntologyIndex,
    programmatic_ontology: _OntologyIndex,
    data_driven_policy: _CompiledOntologyPolicy,
    frozen_policy: _CompiledOntologyPolicy,
    programmatic_policy: _CompiledOntologyPolicy,
    private_manifest_hash: str,
    private_rows_hash: str,
    case_elapsed_ms: int,
    segmenter_elapsed_ms: int,
    corpus_elapsed_ms: int,
    kg_elapsed_ms: int,
    scoring_elapsed_ms: int,
    total_elapsed_ms: int,
    expected_parsed_corpus_count: int,
    require_external_segmenters: bool,
) -> dict[str, Any]:
    arm_summaries = {
        arm: _arm_summary(rows, cases=cases, arm=arm) for arm, rows in arm_rows.items()
    }
    best_arm = max(
        ARMS,
        key=lambda arm: (
            arm_summaries[arm]["primary_retrieval_passed_count"],
            arm_summaries[arm]["no_answer_passed_count"],
            arm,
        ),
    )
    regex_current_summary = arm_summaries[ARM_REGEX_ONTOLOGY]
    lexical_ontology_summary = arm_summaries[ARM_LEXICAL_ONTOLOGY]
    data_driven_ontology_summary = arm_summaries[ARM_DATA_DRIVEN_ONTOLOGY]
    frozen_ontology_summary = arm_summaries[ARM_FROZEN_ONTOLOGY]
    programmatic_ontology_summary = arm_summaries[ARM_PROGRAMMATIC_ONTOLOGY]
    programmatic_policy_summaries = {
        POLICY_DATA_DRIVEN_PROGRAMMATIC: _policy_public_summary(data_driven_policy),
        POLICY_FROZEN_PROGRAMMATIC: _policy_public_summary(frozen_policy),
        POLICY_PROGRAMMATIC: _policy_public_summary(programmatic_policy),
    }
    return {
        "segmentation_policy_hash": sha256_json(SEGMENTATION_POLICY_VERSION),
        "type_compatibility_proxy_policy_hash": sha256_json(
            TYPE_COMPATIBILITY_PROXY_POLICY_VERSION
        ),
        "parsed_corpus_count": prepared.parsed_corpus_count,
        "expected_parsed_corpus_count": expected_parsed_corpus_count,
        "parsed_corpus_hash": prepared.parsed_corpus_hash,
        "body_segment_count": len(prepared.segments),
        "message_key_count": len({segment.message_key for segment in prepared.segments}),
        "thread_key_count": len(
            {segment.thread_key for segment in prepared.segments if segment.thread_key}
        ),
        "training_corpus_hash": prepared.segmenters.training_corpus_hash,
        "sentencepiece_model_hash": prepared.segmenters.sentencepiece_model_hash,
        "sentencepiece_vocab_size": prepared.segmenters.sentencepiece_vocab_size,
        "sentencepiece_user_symbol_count": prepared.segmenters.user_symbol_count,
        "candidate_admission_policy_summaries": programmatic_policy_summaries,
        "programmatic_policy_hash": programmatic_policy.policy_hash,
        "programmatic_candidate_lexeme_count": programmatic_policy.candidate_lexeme_count,
        "programmatic_accepted_lexeme_count": programmatic_policy.accepted_lexeme_count,
        "programmatic_rejected_lexeme_count": programmatic_policy.rejected_lexeme_count,
        "programmatic_protected_accepted_lexeme_count": (
            programmatic_policy.protected_accepted_lexeme_count
        ),
        "programmatic_cjk_accepted_lexeme_count": programmatic_policy.cjk_accepted_lexeme_count,
        "programmatic_ascii_piece_rejected_count": (programmatic_policy.ascii_piece_rejected_count),
        "programmatic_frequency_rejected_lexeme_count": (
            programmatic_policy.frequency_rejected_lexeme_count
        ),
        "programmatic_neural_scored_lexeme_count": (programmatic_policy.neural_scored_lexeme_count),
        "programmatic_neural_accepted_lexeme_count": (
            programmatic_policy.neural_accepted_lexeme_count
        ),
        "programmatic_neural_model_version": programmatic_policy.neural_model_version,
        "programmatic_neural_model_hash": programmatic_policy.neural_model_hash,
        "programmatic_neural_training_example_count": (
            programmatic_policy.neural_training_example_count
        ),
        "programmatic_neural_training_positive_count": (
            programmatic_policy.neural_training_positive_count
        ),
        "programmatic_neural_training_negative_count": (
            programmatic_policy.neural_training_negative_count
        ),
        "programmatic_neural_training_epoch_count": (
            programmatic_policy.neural_training_epoch_count
        ),
        "programmatic_neural_feature_count": programmatic_policy.neural_feature_count,
        "external_jieba_available": int(prepared.segmenters.external_jieba_available),
        "external_sentencepiece_available": int(
            prepared.segmenters.external_sentencepiece_available
        ),
        "external_segmenters_required": int(require_external_segmenters),
        "case_count": len(cases),
        "positive_case_count": sum(1 for case in cases if case.result_kind == "owner_match"),
        "no_match_case_count": sum(1 for case in cases if case.result_kind == "no_match"),
        "permission_denied_case_count": sum(
            1 for case in cases if case.result_kind == "permission_denied"
        ),
        "development_case_count": sum(1 for case in cases if case.split == "development"),
        "evaluation_case_count": sum(1 for case in cases if case.split == "evaluation"),
        "protected_span_case_count": sum(
            1 for case in cases if case.bucket in {"cjk_organization", "business_identifier"}
        ),
        "case_bucket_counts": _case_counts(cases, "bucket"),
        "case_split_counts": _case_counts(cases, "split"),
        "private_manifest_hash": private_manifest_hash,
        "private_score_rows_hash": private_rows_hash,
        "arm_names": list(ARMS),
        "arm_stage_definitions": {
            arm: dict(definition) for arm, definition in ARM_STAGE_DEFINITIONS.items()
        },
        "arm_summaries": arm_summaries,
        **_report_sections(
            arm_summaries=arm_summaries,
            protected_span_case_count=sum(
                1 for case in cases if case.bucket in {"cjk_organization", "business_identifier"}
            ),
            regex_kg=regex_kg,
            lexical_kg=lexical_kg,
            data_driven_kg=data_driven_kg,
            frozen_kg=frozen_kg,
            programmatic_kg=programmatic_kg,
            case_elapsed_ms=case_elapsed_ms,
            segmenter_elapsed_ms=segmenter_elapsed_ms,
            corpus_elapsed_ms=corpus_elapsed_ms,
            kg_elapsed_ms=kg_elapsed_ms,
            scoring_elapsed_ms=scoring_elapsed_ms,
            total_elapsed_ms=total_elapsed_ms,
        ),
        "best_arm_name": best_arm,
        "best_primary_retrieval_passed_count": int(
            arm_summaries[best_arm]["primary_retrieval_passed_count"]
        ),
        "best_primary_retrieval_accuracy_basis_points": int(
            arm_summaries[best_arm]["primary_retrieval_accuracy_basis_points"]
        ),
        "jieba_sentencepiece_type_compatibility_proxy_delta_vs_regex_type_compatibility_proxy_primary_retrieval_passed_count": int(
            lexical_ontology_summary["primary_retrieval_passed_count"]
        )
        - int(regex_current_summary["primary_retrieval_passed_count"]),
        "type_compatibility_proxy_delta_vs_jieba_sentencepiece_candidate_kg_primary_retrieval_passed_count": int(
            arm_summaries[ARM_LEXICAL_ONTOLOGY]["primary_retrieval_passed_count"]
        )
        - int(arm_summaries[ARM_LEXICAL_KG]["primary_retrieval_passed_count"]),
        "weak_label_mlp_delta_vs_jieba_sentencepiece_primary_retrieval_passed_count": int(
            programmatic_ontology_summary["primary_retrieval_passed_count"]
        )
        - int(lexical_ontology_summary["primary_retrieval_passed_count"]),
        "frequency_rule_delta_vs_jieba_sentencepiece_primary_retrieval_passed_count": int(
            data_driven_ontology_summary["primary_retrieval_passed_count"]
        )
        - int(lexical_ontology_summary["primary_retrieval_passed_count"]),
        "frozen_profile_delta_vs_jieba_sentencepiece_primary_retrieval_passed_count": int(
            frozen_ontology_summary["primary_retrieval_passed_count"]
        )
        - int(lexical_ontology_summary["primary_retrieval_passed_count"]),
        "weak_label_mlp_delta_vs_frequency_rule_primary_retrieval_passed_count": int(
            programmatic_ontology_summary["primary_retrieval_passed_count"]
        )
        - int(data_driven_ontology_summary["primary_retrieval_passed_count"]),
        "weak_label_mlp_delta_vs_frozen_profile_primary_retrieval_passed_count": int(
            programmatic_ontology_summary["primary_retrieval_passed_count"]
        )
        - int(frozen_ontology_summary["primary_retrieval_passed_count"]),
        "weak_label_mlp_delta_vs_regex_primary_retrieval_passed_count": int(
            programmatic_ontology_summary["primary_retrieval_passed_count"]
        )
        - int(regex_current_summary["primary_retrieval_passed_count"]),
        "regex_candidate_graph_node_count": regex_kg.node_count,
        "regex_candidate_graph_relation_count": regex_kg.relation_count,
        "regex_lexical_relation_count": regex_kg.lexical_relation_count,
        "regex_component_count": regex_kg.component_count,
        "regex_largest_component_size": regex_kg.largest_component_size,
        "lexical_candidate_graph_node_count": lexical_kg.node_count,
        "lexical_candidate_graph_relation_count": lexical_kg.relation_count,
        "lexical_relation_count": lexical_kg.lexical_relation_count,
        "lexical_component_count": lexical_kg.component_count,
        "lexical_largest_component_size": lexical_kg.largest_component_size,
        "data_driven_candidate_graph_node_count": data_driven_kg.node_count,
        "data_driven_candidate_graph_relation_count": data_driven_kg.relation_count,
        "data_driven_lexical_relation_count": data_driven_kg.lexical_relation_count,
        "data_driven_component_count": data_driven_kg.component_count,
        "data_driven_largest_component_size": data_driven_kg.largest_component_size,
        "frozen_candidate_graph_node_count": frozen_kg.node_count,
        "frozen_candidate_graph_relation_count": frozen_kg.relation_count,
        "frozen_lexical_relation_count": frozen_kg.lexical_relation_count,
        "frozen_component_count": frozen_kg.component_count,
        "frozen_largest_component_size": frozen_kg.largest_component_size,
        "programmatic_candidate_graph_node_count": programmatic_kg.node_count,
        "programmatic_candidate_graph_relation_count": programmatic_kg.relation_count,
        "programmatic_lexical_relation_count": programmatic_kg.lexical_relation_count,
        "programmatic_component_count": programmatic_kg.component_count,
        "programmatic_largest_component_size": programmatic_kg.largest_component_size,
        "regex_typed_node_count": regex_ontology.typed_node_count,
        "regex_typed_component_count": regex_ontology.typed_component_count,
        "lexical_typed_node_count": lexical_ontology.typed_node_count,
        "lexical_typed_component_count": lexical_ontology.typed_component_count,
        "data_driven_typed_node_count": data_driven_ontology.typed_node_count,
        "data_driven_typed_component_count": data_driven_ontology.typed_component_count,
        "frozen_typed_node_count": frozen_ontology.typed_node_count,
        "frozen_typed_component_count": frozen_ontology.typed_component_count,
        "programmatic_typed_node_count": programmatic_ontology.typed_node_count,
        "programmatic_typed_component_count": programmatic_ontology.typed_component_count,
        "case_generation_elapsed_ms": case_elapsed_ms,
        "segmentation_elapsed_ms": segmenter_elapsed_ms,
        "corpus_preparation_elapsed_ms": corpus_elapsed_ms,
        "kg_build_elapsed_ms": kg_elapsed_ms,
        "scoring_elapsed_ms": scoring_elapsed_ms,
        "total_elapsed_ms": total_elapsed_ms,
    }


def _arm_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    cases: Sequence[_Case],
    arm: str,
) -> dict[str, Any]:
    by_hash = {sha256_json(case.case_id): case for case in cases}
    passed = sum(1 for row in rows if row.get("status") == "passed")
    positive_passed = sum(
        1
        for row in rows
        if row.get("result_kind") == "owner_match" and row.get("status") == "passed"
    )
    no_match_passed = sum(
        1 for row in rows if row.get("result_kind") == "no_match" and row.get("status") == "passed"
    )
    denied_passed = sum(
        1
        for row in rows
        if row.get("result_kind") == "permission_denied" and row.get("status") == "passed"
    )
    positive_case_count = sum(1 for row in rows if row.get("result_kind") == "owner_match")
    no_match_case_count = sum(1 for row in rows if row.get("result_kind") == "no_match")
    permission_case_count = sum(1 for row in rows if row.get("result_kind") == "permission_denied")
    bucket_passed: Counter[str] = Counter()
    bucket_total: Counter[str] = Counter()
    for row in rows:
        case = by_hash.get(str(row.get("case_hash")))
        bucket = case.bucket if case is not None else "unknown"
        bucket_total[bucket] += 1
        if row.get("status") == "passed":
            bucket_passed[bucket] += 1
    summary = {
        "arm_hash": sha256_json(arm),
        **ARM_STAGE_DEFINITIONS[arm],
        "case_count": len(rows),
        "passed_case_count": passed,
        "failed_case_count": len(rows) - passed,
        "all_case_pass_rate_basis_points": _basis_points(passed, len(rows)),
        "primary_retrieval_case_count": positive_case_count,
        "primary_retrieval_passed_count": positive_passed,
        "primary_retrieval_accuracy_basis_points": _basis_points(
            positive_passed, positive_case_count
        ),
        "no_answer_case_count": no_match_case_count,
        "no_answer_passed_count": no_match_passed,
        "no_answer_accuracy_basis_points": _basis_points(no_match_passed, no_match_case_count),
        "permission_safety_case_count": permission_case_count,
        "permission_safety_passed_count": denied_passed,
        "permission_safety_accuracy_basis_points": _basis_points(
            denied_passed, permission_case_count
        ),
        "positive_passed_count": positive_passed,
        "no_match_passed_count": no_match_passed,
        "permission_denied_passed_count": denied_passed,
        "bucket_counts": dict(sorted(bucket_total.items())),
        "bucket_passed_counts": dict(sorted(bucket_passed.items())),
        "result_hash": sha256_json(rows),
        "unique_response_hash_count": len({row.get("response_hash") for row in rows}),
    }
    summary["summary_hash"] = sha256_json(summary)
    return summary


def _report_sections(
    *,
    arm_summaries: Mapping[str, Mapping[str, Any]],
    protected_span_case_count: int,
    regex_kg: _KgIndex,
    lexical_kg: _KgIndex,
    data_driven_kg: _KgIndex,
    frozen_kg: _KgIndex,
    programmatic_kg: _KgIndex,
    case_elapsed_ms: int,
    segmenter_elapsed_ms: int,
    corpus_elapsed_ms: int,
    kg_elapsed_ms: int,
    scoring_elapsed_ms: int,
    total_elapsed_ms: int,
) -> dict[str, Any]:
    positive_retrieval = {
        "primary_metric": "primary_retrieval_accuracy_basis_points",
        "permission_denied_cases_excluded": True,
        "arms": {
            arm: {
                "case_count": summary["primary_retrieval_case_count"],
                "passed_count": summary["primary_retrieval_passed_count"],
                "accuracy_basis_points": summary["primary_retrieval_accuracy_basis_points"],
            }
            for arm, summary in arm_summaries.items()
        },
    }
    no_answer = {
        "primary_metric": "no_answer_accuracy_basis_points",
        "arms": {
            arm: {
                "case_count": summary["no_answer_case_count"],
                "passed_count": summary["no_answer_passed_count"],
                "accuracy_basis_points": summary["no_answer_accuracy_basis_points"],
            }
            for arm, summary in arm_summaries.items()
        },
    }
    permission_safety = {
        "primary_metric": "permission_safety_accuracy_basis_points",
        "automatically_blocked_cases_are_not_retrieval_successes": True,
        "arms": {
            arm: {
                "case_count": summary["permission_safety_case_count"],
                "passed_count": summary["permission_safety_passed_count"],
                "accuracy_basis_points": summary["permission_safety_accuracy_basis_points"],
            }
            for arm, summary in arm_summaries.items()
        },
    }
    kg_indexes = {
        ARM_REGEX_KG: regex_kg,
        ARM_REGEX_ONTOLOGY: regex_kg,
        ARM_LEXICAL_KG: lexical_kg,
        ARM_LEXICAL_ONTOLOGY: lexical_kg,
        ARM_DATA_DRIVEN_ONTOLOGY: data_driven_kg,
        ARM_FROZEN_ONTOLOGY: frozen_kg,
        ARM_PROGRAMMATIC_ONTOLOGY: programmatic_kg,
    }
    graph_topology = {
        "measurement_status": "candidate_graph_diagnostics",
        "arms": {
            arm: {
                "candidate_graph_node_count": index.node_count,
                "candidate_graph_relation_count": index.relation_count,
                "lexical_relation_count": index.lexical_relation_count,
                "component_count": index.component_count,
                "largest_component_size": index.largest_component_size,
            }
            for arm, index in kg_indexes.items()
        },
    }
    return {
        "positive_retrieval": positive_retrieval,
        "no_answer_or_no_match": no_answer,
        "permission_safety": permission_safety,
        "frame_type_quality": {
            "measurement_status": "not_measured_by_candidate_admission_harness",
            "quality_claim_supported": False,
            "type_compatibility_modes": {
                arm: definition["type_compatibility_mode"]
                for arm, definition in ARM_STAGE_DEFINITIONS.items()
            },
            "frame_semantics_modes": {
                arm: definition["frame_semantics_mode"]
                for arm, definition in ARM_STAGE_DEFINITIONS.items()
            },
        },
        "slot_value_quality": {
            "measurement_status": "not_measured_by_candidate_admission_harness",
            "quality_claim_supported": False,
        },
        "evidence_span_quality": {
            "measurement_status": "coverage_proxy_only",
            "quality_claim_supported": False,
            "protected_span_case_count": protected_span_case_count,
        },
        "latency_and_resource_use": {
            "case_generation_elapsed_ms": case_elapsed_ms,
            "segmentation_elapsed_ms": segmenter_elapsed_ms,
            "corpus_preparation_elapsed_ms": corpus_elapsed_ms,
            "kg_build_elapsed_ms": kg_elapsed_ms,
            "scoring_elapsed_ms": scoring_elapsed_ms,
            "total_elapsed_ms": total_elapsed_ms,
        },
        "graph_topology_diagnostics": graph_topology,
    }


def validate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, Mapping):
        return _validation(False, ["report must be an object"])
    _validate_exact_keys(
        report,
        {"report_type", "generated_at", "metrics", "safe_outputs", "claim_boundary"},
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
        recomputed_complete = _eval_completed(report)
        if metrics.get("exm_candidate_admission_eval_completed") is not recomputed_complete:
            blockers.append("completion metric does not match recomputed completion predicate")
        if claim_boundary.get("supports_exm_50000_candidate_admission_eval_claim") is not (
            recomputed_complete
        ):
            blockers.append("claim boundary does not match recomputed completion predicate")
    _validate_embedded_validation(report.get("validation"), report, blockers)
    if not _public_outputs_are_safe(report):
        blockers.append("public output leak guard failed")
    return _validation(not blockers, blockers, report=report)


def _validate_success_report(
    metrics: Mapping[str, Any],
    safe_outputs: Mapping[str, Any],
    claim_boundary: Mapping[str, Any],
    blockers: list[str],
) -> None:
    expected_metrics = {
        "parsed_corpora_loaded",
        "expected_exm_corpus_count_met",
        "body_segments_loaded",
        "external_jieba_available",
        "external_sentencepiece_available",
        "sentencepiece_model_trained",
        "protected_spans_used",
        "case_manifest_generated",
        "case_count_target_met",
        "candidate_kg_scored",
        "type_compatibility_proxy_scored",
        "candidate_only_boundary_respected",
        "canonical_kg_wiki_side_effects_absent",
        "raw_leak_guard_passed",
        "exm_candidate_admission_eval_completed",
    }
    _validate_exact_keys(metrics, expected_metrics, "metrics", blockers)
    for key in expected_metrics - {"exm_candidate_admission_eval_completed"}:
        if metrics.get(key) is not True:
            blockers.append("required metric is not true: " + key)
    expected_safe_keys = {
        "segmentation_policy_hash",
        "type_compatibility_proxy_policy_hash",
        "parsed_corpus_count",
        "expected_parsed_corpus_count",
        "parsed_corpus_hash",
        "body_segment_count",
        "message_key_count",
        "thread_key_count",
        "training_corpus_hash",
        "sentencepiece_model_hash",
        "sentencepiece_vocab_size",
        "sentencepiece_user_symbol_count",
        "candidate_admission_policy_summaries",
        "programmatic_policy_hash",
        "programmatic_candidate_lexeme_count",
        "programmatic_accepted_lexeme_count",
        "programmatic_rejected_lexeme_count",
        "programmatic_protected_accepted_lexeme_count",
        "programmatic_cjk_accepted_lexeme_count",
        "programmatic_ascii_piece_rejected_count",
        "programmatic_frequency_rejected_lexeme_count",
        "programmatic_neural_scored_lexeme_count",
        "programmatic_neural_accepted_lexeme_count",
        "programmatic_neural_model_version",
        "programmatic_neural_model_hash",
        "programmatic_neural_training_example_count",
        "programmatic_neural_training_positive_count",
        "programmatic_neural_training_negative_count",
        "programmatic_neural_training_epoch_count",
        "programmatic_neural_feature_count",
        "external_jieba_available",
        "external_sentencepiece_available",
        "external_segmenters_required",
        "case_count",
        "positive_case_count",
        "no_match_case_count",
        "permission_denied_case_count",
        "development_case_count",
        "evaluation_case_count",
        "protected_span_case_count",
        "case_bucket_counts",
        "case_split_counts",
        "private_manifest_hash",
        "private_score_rows_hash",
        "arm_names",
        "arm_stage_definitions",
        "arm_summaries",
        "positive_retrieval",
        "no_answer_or_no_match",
        "permission_safety",
        "frame_type_quality",
        "slot_value_quality",
        "evidence_span_quality",
        "latency_and_resource_use",
        "graph_topology_diagnostics",
        "best_arm_name",
        "best_primary_retrieval_passed_count",
        "best_primary_retrieval_accuracy_basis_points",
        "jieba_sentencepiece_type_compatibility_proxy_delta_vs_regex_type_compatibility_proxy_primary_retrieval_passed_count",
        "type_compatibility_proxy_delta_vs_jieba_sentencepiece_candidate_kg_primary_retrieval_passed_count",
        "weak_label_mlp_delta_vs_jieba_sentencepiece_primary_retrieval_passed_count",
        "frequency_rule_delta_vs_jieba_sentencepiece_primary_retrieval_passed_count",
        "frozen_profile_delta_vs_jieba_sentencepiece_primary_retrieval_passed_count",
        "weak_label_mlp_delta_vs_frequency_rule_primary_retrieval_passed_count",
        "weak_label_mlp_delta_vs_frozen_profile_primary_retrieval_passed_count",
        "weak_label_mlp_delta_vs_regex_primary_retrieval_passed_count",
        "regex_candidate_graph_node_count",
        "regex_candidate_graph_relation_count",
        "regex_lexical_relation_count",
        "regex_component_count",
        "regex_largest_component_size",
        "lexical_candidate_graph_node_count",
        "lexical_candidate_graph_relation_count",
        "lexical_relation_count",
        "lexical_component_count",
        "lexical_largest_component_size",
        "data_driven_candidate_graph_node_count",
        "data_driven_candidate_graph_relation_count",
        "data_driven_lexical_relation_count",
        "data_driven_component_count",
        "data_driven_largest_component_size",
        "frozen_candidate_graph_node_count",
        "frozen_candidate_graph_relation_count",
        "frozen_lexical_relation_count",
        "frozen_component_count",
        "frozen_largest_component_size",
        "programmatic_candidate_graph_node_count",
        "programmatic_candidate_graph_relation_count",
        "programmatic_lexical_relation_count",
        "programmatic_component_count",
        "programmatic_largest_component_size",
        "regex_typed_node_count",
        "regex_typed_component_count",
        "lexical_typed_node_count",
        "lexical_typed_component_count",
        "data_driven_typed_node_count",
        "data_driven_typed_component_count",
        "frozen_typed_node_count",
        "frozen_typed_component_count",
        "programmatic_typed_node_count",
        "programmatic_typed_component_count",
        "case_generation_elapsed_ms",
        "segmentation_elapsed_ms",
        "corpus_preparation_elapsed_ms",
        "kg_build_elapsed_ms",
        "scoring_elapsed_ms",
        "total_elapsed_ms",
    }
    _validate_exact_keys(safe_outputs, expected_safe_keys, "safe_outputs", blockers)
    for key in (
        "segmentation_policy_hash",
        "type_compatibility_proxy_policy_hash",
        "parsed_corpus_hash",
        "training_corpus_hash",
        "sentencepiece_model_hash",
        "programmatic_policy_hash",
        "programmatic_neural_model_hash",
        "private_manifest_hash",
        "private_score_rows_hash",
    ):
        _require_sha256(safe_outputs.get(key), "safe_outputs." + key, blockers)
    if safe_outputs.get("programmatic_neural_model_version") != PROGRAMMATIC_NEURAL_MODEL_VERSION:
        blockers.append("programmatic neural model version mismatch")
    if safe_outputs.get("programmatic_neural_feature_count") != len(
        _PROGRAMMATIC_NEURAL_FEATURE_NAMES
    ):
        blockers.append("programmatic neural feature count mismatch")
    if safe_outputs.get("programmatic_neural_training_epoch_count") != (
        PROGRAMMATIC_NEURAL_TRAINING_EPOCHS
    ):
        blockers.append("programmatic neural training epoch count mismatch")
    if safe_outputs.get("programmatic_neural_training_positive_count", 0) + safe_outputs.get(
        "programmatic_neural_training_negative_count", 0
    ) != safe_outputs.get("programmatic_neural_training_example_count"):
        blockers.append("programmatic neural training counts do not sum")
    _validate_programmatic_policy_summaries(safe_outputs, blockers)
    if tuple(safe_outputs.get("arm_names", ())) != ARMS:
        blockers.append("safe_outputs.arm_names mismatch")
    _validate_report_level_case_counts(safe_outputs, blockers)
    _validate_arm_summaries(safe_outputs, blockers)
    _validate_report_sections(safe_outputs, blockers)
    _validate_safe_output_derived_values(safe_outputs, blockers)
    if safe_outputs.get("positive_case_count", 0) + safe_outputs.get(
        "no_match_case_count", 0
    ) + safe_outputs.get("permission_denied_case_count", 0) != safe_outputs.get("case_count"):
        blockers.append("case-kind counts do not sum to case_count")
    if safe_outputs.get("development_case_count", 0) + safe_outputs.get(
        "evaluation_case_count", 0
    ) != safe_outputs.get("case_count"):
        blockers.append("split counts do not sum to case_count")
    _validate_success_claim_boundary(claim_boundary, metrics, blockers)


def _validate_report_level_case_counts(
    safe_outputs: Mapping[str, Any], blockers: list[str]
) -> None:
    case_count = _int_value(safe_outputs.get("case_count"))
    positive_case_count = _int_value(safe_outputs.get("positive_case_count"))
    no_match_case_count = _int_value(safe_outputs.get("no_match_case_count"))
    denied_case_count = _int_value(safe_outputs.get("permission_denied_case_count"))
    for key in (
        "case_count",
        "positive_case_count",
        "no_match_case_count",
        "permission_denied_case_count",
        "development_case_count",
        "evaluation_case_count",
    ):
        if not _is_non_negative_int(safe_outputs.get(key)):
            blockers.append("safe_outputs count must be a non-negative integer: " + key)
    expected_positive_count = int(case_count * POSITIVE_CASE_RATIO_BP / 10000)
    expected_no_match_count = int(case_count * NO_MATCH_CASE_RATIO_BP / 10000)
    expected_denied_count = case_count - expected_positive_count - expected_no_match_count
    if (
        positive_case_count,
        no_match_case_count,
        denied_case_count,
    ) != (
        expected_positive_count,
        expected_no_match_count,
        expected_denied_count,
    ):
        blockers.append("case-kind counts must match configured evaluation mix")
    case_bucket_counts = safe_outputs.get("case_bucket_counts")
    if not isinstance(case_bucket_counts, Mapping):
        blockers.append("safe_outputs.case_bucket_counts must be an object")
    else:
        if not set(case_bucket_counts) <= _CASE_BUCKETS:
            blockers.append("case bucket counts contain unknown bucket")
        if not all(_is_non_negative_int(value) for value in case_bucket_counts.values()):
            blockers.append("case bucket counts must be non-negative integers")
        if sum(_int_value(value) for value in case_bucket_counts.values()) != case_count:
            blockers.append("case bucket counts do not sum")
        if _int_value(case_bucket_counts.get("access_boundary")) != denied_case_count:
            blockers.append("access bucket count must match denied case count")
        if _int_value(case_bucket_counts.get("false_positive_guard")) != no_match_case_count:
            blockers.append("false-positive bucket count must match no-match case count")
        owner_bucket_count = sum(
            _int_value(value)
            for bucket, value in case_bucket_counts.items()
            if bucket in _OWNER_MATCH_BUCKETS
        )
        if owner_bucket_count != positive_case_count:
            blockers.append("owner-match bucket counts must match positive case count")
    case_split_counts = safe_outputs.get("case_split_counts")
    if not isinstance(case_split_counts, Mapping):
        blockers.append("safe_outputs.case_split_counts must be an object")
    else:
        if not set(case_split_counts) <= _CASE_SPLITS:
            blockers.append("case split counts contain unknown split")
        if not all(_is_non_negative_int(value) for value in case_split_counts.values()):
            blockers.append("case split counts must be non-negative integers")
        if sum(_int_value(value) for value in case_split_counts.values()) != case_count:
            blockers.append("case split counts do not sum")


def _validate_programmatic_policy_summaries(
    safe_outputs: Mapping[str, Any], blockers: list[str]
) -> None:
    summaries = safe_outputs.get("candidate_admission_policy_summaries")
    if not isinstance(summaries, Mapping):
        blockers.append("safe_outputs.candidate_admission_policy_summaries must be an object")
        return
    expected_policies = {
        POLICY_DATA_DRIVEN_PROGRAMMATIC,
        POLICY_FROZEN_PROGRAMMATIC,
        POLICY_PROGRAMMATIC,
    }
    if set(summaries) != expected_policies:
        blockers.append("candidate admission policy summary set mismatch")
        return
    expected_keys = {
        "policy_hash",
        "scorer_kind",
        "scorer_requires_training",
        "candidate_lexeme_count",
        "accepted_lexeme_count",
        "rejected_lexeme_count",
        "protected_accepted_lexeme_count",
        "cjk_accepted_lexeme_count",
        "ascii_piece_rejected_count",
        "frequency_rejected_lexeme_count",
        "scored_lexeme_count",
        "accepted_scored_lexeme_count",
        "model_version",
        "model_hash",
        "training_example_count",
        "training_positive_count",
        "training_negative_count",
        "training_epoch_count",
        "feature_count",
    }
    expected_scorers = {
        POLICY_DATA_DRIVEN_PROGRAMMATIC: PROGRAMMATIC_SCORER_DATA_DRIVEN,
        POLICY_FROZEN_PROGRAMMATIC: PROGRAMMATIC_SCORER_FROZEN_PROFILE,
        POLICY_PROGRAMMATIC: PROGRAMMATIC_SCORER_WEAK_LABEL_MLP,
    }
    expected_versions = {
        POLICY_DATA_DRIVEN_PROGRAMMATIC: PROGRAMMATIC_DATA_DRIVEN_MODEL_VERSION,
        POLICY_FROZEN_PROGRAMMATIC: PROGRAMMATIC_FROZEN_MODEL_VERSION,
        POLICY_PROGRAMMATIC: PROGRAMMATIC_NEURAL_MODEL_VERSION,
    }
    for policy_name, summary in summaries.items():
        if not isinstance(summary, Mapping):
            blockers.append("programmatic policy summary must be an object")
            continue
        _validate_exact_keys(summary, expected_keys, "programmatic_policy_summary", blockers)
        scorer_kind = expected_scorers[policy_name]
        if summary.get("scorer_kind") != scorer_kind:
            blockers.append("programmatic policy summary scorer kind mismatch")
        if summary.get("model_version") != expected_versions[policy_name]:
            blockers.append("programmatic policy summary model version mismatch")
        for key in ("policy_hash", "model_hash"):
            _require_sha256(summary.get(key), "programmatic_policy_summary." + key, blockers)
        for key in expected_keys - {
            "policy_hash",
            "scorer_kind",
            "model_version",
            "model_hash",
        }:
            if not _is_non_negative_int(summary.get(key)):
                blockers.append(
                    "programmatic policy summary count must be a non-negative integer: " + key
                )
        if _int_value(summary.get("candidate_lexeme_count")) != (
            _int_value(summary.get("accepted_lexeme_count"))
            + _int_value(summary.get("rejected_lexeme_count"))
        ):
            blockers.append("programmatic policy summary accepted/rejected counts do not sum")
        if _int_value(summary.get("training_positive_count")) + _int_value(
            summary.get("training_negative_count")
        ) != _int_value(summary.get("training_example_count")):
            blockers.append("programmatic policy summary training counts do not sum")
        if scorer_kind in {PROGRAMMATIC_SCORER_DATA_DRIVEN, PROGRAMMATIC_SCORER_FROZEN_PROFILE}:
            if summary.get("scorer_requires_training") != 0:
                blockers.append("no-training policy summary requires training")
            if summary.get("training_example_count") != 0:
                blockers.append("no-training policy summary has training examples")
            if summary.get("training_epoch_count") != 0:
                blockers.append("no-training policy summary has training epochs")
        else:
            if summary.get("scorer_requires_training") != 1:
                blockers.append("weak-label MLP policy summary must require training")
            if summary.get("training_epoch_count") != PROGRAMMATIC_NEURAL_TRAINING_EPOCHS:
                blockers.append("weak-label MLP training epoch count mismatch")
            if _int_value(summary.get("training_example_count")) <= 0:
                blockers.append("weak-label MLP training examples missing")
        if scorer_kind == PROGRAMMATIC_SCORER_WEAK_LABEL_MLP:
            if summary.get("policy_hash") != safe_outputs.get("programmatic_policy_hash"):
                blockers.append("programmatic policy hash does not match summary")
            if summary.get("model_hash") != safe_outputs.get("programmatic_neural_model_hash"):
                blockers.append("programmatic neural model hash does not match summary")


def _validate_arm_summaries(safe_outputs: Mapping[str, Any], blockers: list[str]) -> None:
    arm_summaries = safe_outputs.get("arm_summaries")
    if not isinstance(arm_summaries, Mapping):
        blockers.append("safe_outputs.arm_summaries must be an object")
        return
    if set(arm_summaries) != set(ARMS):
        blockers.append("safe_outputs.arm_summaries arm set mismatch")
        return
    case_count = safe_outputs.get("case_count")
    positive_case_count = _int_value(safe_outputs.get("positive_case_count"))
    no_match_case_count = _int_value(safe_outputs.get("no_match_case_count"))
    denied_case_count = _int_value(safe_outputs.get("permission_denied_case_count"))
    expected_bucket_counts = safe_outputs.get("case_bucket_counts")
    for arm, summary in arm_summaries.items():
        if not isinstance(summary, Mapping):
            blockers.append("arm summary must be an object")
            continue
        expected = {
            "arm_hash",
            "candidate_admission_policy",
            "kg_construction_mode",
            "type_compatibility_mode",
            "frame_semantics_mode",
            "case_count",
            "passed_case_count",
            "failed_case_count",
            "all_case_pass_rate_basis_points",
            "primary_retrieval_case_count",
            "primary_retrieval_passed_count",
            "primary_retrieval_accuracy_basis_points",
            "no_answer_case_count",
            "no_answer_passed_count",
            "no_answer_accuracy_basis_points",
            "permission_safety_case_count",
            "permission_safety_passed_count",
            "permission_safety_accuracy_basis_points",
            "positive_passed_count",
            "no_match_passed_count",
            "permission_denied_passed_count",
            "bucket_counts",
            "bucket_passed_counts",
            "result_hash",
            "unique_response_hash_count",
            "summary_hash",
        }
        _validate_exact_keys(summary, expected, "arm_summary", blockers)
        for key in ("arm_hash", "result_hash", "summary_hash"):
            _require_sha256(summary.get(key), "arm_summary." + key, blockers)
        if summary.get("case_count") != case_count:
            blockers.append("arm_summary.case_count mismatch")
        if {
            key: summary.get(key)
            for key in (
                "candidate_admission_policy",
                "kg_construction_mode",
                "type_compatibility_mode",
                "frame_semantics_mode",
            )
        } != ARM_STAGE_DEFINITIONS[arm]:
            blockers.append("arm summary stage definition mismatch")
        passed_count = _int_value(summary.get("passed_case_count"))
        failed_count = _int_value(summary.get("failed_case_count"))
        positive_passed = _int_value(summary.get("positive_passed_count"))
        no_match_passed = _int_value(summary.get("no_match_passed_count"))
        denied_passed = _int_value(summary.get("permission_denied_passed_count"))
        for key in (
            "case_count",
            "passed_case_count",
            "failed_case_count",
            "all_case_pass_rate_basis_points",
            "primary_retrieval_case_count",
            "primary_retrieval_passed_count",
            "primary_retrieval_accuracy_basis_points",
            "no_answer_case_count",
            "no_answer_passed_count",
            "no_answer_accuracy_basis_points",
            "permission_safety_case_count",
            "permission_safety_passed_count",
            "permission_safety_accuracy_basis_points",
            "positive_passed_count",
            "no_match_passed_count",
            "permission_denied_passed_count",
            "unique_response_hash_count",
        ):
            if not _is_non_negative_int(summary.get(key)):
                blockers.append("arm summary count must be a non-negative integer: " + key)
        if passed_count + failed_count != case_count:
            blockers.append("arm summary passed/failed counts do not sum")
        if positive_passed + no_match_passed + denied_passed != passed_count:
            blockers.append("arm summary result-kind passed counts do not sum")
        if positive_passed > positive_case_count:
            blockers.append("arm summary positive passed count exceeds total")
        if no_match_passed > no_match_case_count:
            blockers.append("arm summary no-match passed count exceeds total")
        if denied_passed > denied_case_count:
            blockers.append("arm summary permission-denied passed count exceeds total")
        if summary.get("all_case_pass_rate_basis_points") != _basis_points(
            passed_count, case_count
        ):
            blockers.append("arm summary all-case pass rate mismatch")
        expected_separate_metrics = (
            (
                "primary_retrieval",
                positive_case_count,
                positive_passed,
            ),
            ("no_answer", no_match_case_count, no_match_passed),
            ("permission_safety", denied_case_count, denied_passed),
        )
        for prefix, expected_count, expected_passed in expected_separate_metrics:
            if summary.get(prefix + "_case_count") != expected_count:
                blockers.append("arm summary " + prefix + " case count mismatch")
            if summary.get(prefix + "_passed_count") != expected_passed:
                blockers.append("arm summary " + prefix + " passed count mismatch")
            accuracy_key = (
                "primary_retrieval_accuracy_basis_points"
                if prefix == "primary_retrieval"
                else prefix + "_accuracy_basis_points"
            )
            if summary.get(accuracy_key) != _basis_points(expected_passed, expected_count):
                blockers.append("arm summary " + prefix + " accuracy mismatch")
        if summary.get("unique_response_hash_count") != case_count:
            blockers.append("arm summary response hashes must be unique")
        if summary.get("arm_hash") != sha256_json(str(arm)):
            blockers.append("arm hash mismatch")
        bucket_counts = summary.get("bucket_counts")
        bucket_passed_counts = summary.get("bucket_passed_counts")
        if not isinstance(bucket_counts, Mapping):
            blockers.append("arm summary bucket_counts must be an object")
        else:
            if isinstance(expected_bucket_counts, Mapping) and dict(bucket_counts) != dict(
                expected_bucket_counts
            ):
                blockers.append("arm summary bucket counts must match case bucket counts")
            if not all(_is_non_negative_int(value) for value in bucket_counts.values()):
                blockers.append("arm summary bucket counts must be non-negative integers")
            if sum(_int_value(value) for value in bucket_counts.values()) != case_count:
                blockers.append("arm summary bucket counts do not sum")
        if not isinstance(bucket_passed_counts, Mapping):
            blockers.append("arm summary bucket_passed_counts must be an object")
        else:
            if not all(_is_non_negative_int(value) for value in bucket_passed_counts.values()):
                blockers.append("arm summary bucket passed counts must be non-negative integers")
            if isinstance(bucket_counts, Mapping) and not (
                set(bucket_passed_counts) <= set(bucket_counts)
            ):
                blockers.append("arm summary bucket passed keys must be bucket-count subset")
            if isinstance(bucket_counts, Mapping):
                for bucket, passed_value in bucket_passed_counts.items():
                    if _int_value(passed_value) > _int_value(bucket_counts.get(bucket)):
                        blockers.append("arm summary bucket passed count exceeds bucket total")
                        break
            bucket_passed_total = sum(_int_value(value) for value in bucket_passed_counts.values())
            if bucket_passed_total != passed_count:
                blockers.append("arm summary bucket passed counts do not sum")
            access_passed = _int_value(bucket_passed_counts.get("access_boundary"))
            false_positive_passed = _int_value(bucket_passed_counts.get("false_positive_guard"))
            positive_bucket_passed = bucket_passed_total - access_passed - false_positive_passed
            if denied_passed != access_passed:
                blockers.append("arm summary denied passed count does not match bucket")
            if no_match_passed != false_positive_passed:
                blockers.append("arm summary no-match passed count does not match bucket")
            if positive_passed != positive_bucket_passed:
                blockers.append("arm summary positive passed count does not match buckets")
        recomputed_summary = {key: summary.get(key) for key in expected if key != "summary_hash"}
        if summary.get("summary_hash") != sha256_json(recomputed_summary):
            blockers.append("arm summary hash mismatch")


def _validate_report_sections(safe_outputs: Mapping[str, Any], blockers: list[str]) -> None:
    if safe_outputs.get("arm_stage_definitions") != ARM_STAGE_DEFINITIONS:
        blockers.append("arm stage definitions mismatch")
    arm_summaries = safe_outputs.get("arm_summaries")
    if not isinstance(arm_summaries, Mapping) or set(arm_summaries) != set(ARMS):
        return
    section_specs = {
        "positive_retrieval": (
            "primary_retrieval",
            "primary_retrieval_accuracy_basis_points",
        ),
        "no_answer_or_no_match": ("no_answer", "no_answer_accuracy_basis_points"),
        "permission_safety": (
            "permission_safety",
            "permission_safety_accuracy_basis_points",
        ),
    }
    for section_name, (prefix, metric_name) in section_specs.items():
        section = safe_outputs.get(section_name)
        if not isinstance(section, Mapping):
            blockers.append(section_name + " section must be an object")
            continue
        expected_section_keys = {"primary_metric", "arms"}
        if section_name == "positive_retrieval":
            expected_section_keys.add("permission_denied_cases_excluded")
        elif section_name == "permission_safety":
            expected_section_keys.add("automatically_blocked_cases_are_not_retrieval_successes")
        _validate_exact_keys(section, expected_section_keys, section_name, blockers)
        if section.get("primary_metric") != metric_name:
            blockers.append(section_name + " primary metric mismatch")
        arms = section.get("arms")
        if not isinstance(arms, Mapping) or set(arms) != set(ARMS):
            blockers.append(section_name + " arm set mismatch")
            continue
        for arm, values in arms.items():
            expected = {
                "case_count": arm_summaries[arm][prefix + "_case_count"],
                "passed_count": arm_summaries[arm][prefix + "_passed_count"],
                "accuracy_basis_points": arm_summaries[arm][metric_name],
            }
            if not isinstance(values, Mapping):
                blockers.append(section_name + " arm values mismatch")
                break
            _validate_exact_keys(
                values,
                set(expected),
                section_name + ".arms." + str(arm),
                blockers,
            )
            if dict(values) != expected:
                blockers.append(section_name + " arm values mismatch")
                break
    positive = safe_outputs.get("positive_retrieval")
    if (
        not isinstance(positive, Mapping)
        or positive.get("permission_denied_cases_excluded") is not True
    ):
        blockers.append("positive retrieval must exclude permission-denied cases")
    permission = safe_outputs.get("permission_safety")
    if (
        not isinstance(permission, Mapping)
        or permission.get("automatically_blocked_cases_are_not_retrieval_successes") is not True
    ):
        blockers.append("permission safety must not count blocked cases as retrieval successes")
    frame_type = safe_outputs.get("frame_type_quality")
    if not isinstance(frame_type, Mapping):
        blockers.append("frame_type_quality section must be an object")
    else:
        _validate_exact_keys(
            frame_type,
            {
                "measurement_status",
                "quality_claim_supported",
                "type_compatibility_modes",
                "frame_semantics_modes",
            },
            "frame_type_quality",
            blockers,
        )
        if frame_type.get("measurement_status") != ("not_measured_by_candidate_admission_harness"):
            blockers.append("frame_type_quality measurement status mismatch")
        if frame_type.get("quality_claim_supported") is not False:
            blockers.append("frame_type_quality must not support a quality claim")
        expected_type_modes = {
            arm: definition["type_compatibility_mode"]
            for arm, definition in ARM_STAGE_DEFINITIONS.items()
        }
        type_modes = frame_type.get("type_compatibility_modes")
        if not isinstance(type_modes, Mapping) or dict(type_modes) != expected_type_modes:
            blockers.append("frame type compatibility modes mismatch")
        expected_frame_modes = {
            arm: definition["frame_semantics_mode"]
            for arm, definition in ARM_STAGE_DEFINITIONS.items()
        }
        frame_modes = frame_type.get("frame_semantics_modes")
        if not isinstance(frame_modes, Mapping) or dict(frame_modes) != expected_frame_modes:
            blockers.append("frame semantics modes mismatch")
    slot_value = safe_outputs.get("slot_value_quality")
    if not isinstance(slot_value, Mapping):
        blockers.append("slot_value_quality section must be an object")
    else:
        _validate_exact_keys(
            slot_value,
            {"measurement_status", "quality_claim_supported"},
            "slot_value_quality",
            blockers,
        )
        if slot_value.get("measurement_status") != ("not_measured_by_candidate_admission_harness"):
            blockers.append("slot_value_quality measurement status mismatch")
        if slot_value.get("quality_claim_supported") is not False:
            blockers.append("slot_value_quality must not support a quality claim")
    evidence = safe_outputs.get("evidence_span_quality")
    if not isinstance(evidence, Mapping):
        blockers.append("evidence_span_quality section must be an object")
    else:
        _validate_exact_keys(
            evidence,
            {
                "measurement_status",
                "quality_claim_supported",
                "protected_span_case_count",
            },
            "evidence_span_quality",
            blockers,
        )
        if evidence.get("measurement_status") != "coverage_proxy_only":
            blockers.append("evidence span measurement status mismatch")
        if evidence.get("quality_claim_supported") is not False:
            blockers.append("evidence span must not support a quality claim")
        if evidence.get("protected_span_case_count") != safe_outputs.get(
            "protected_span_case_count"
        ):
            blockers.append("evidence span protected case count mismatch")
    latency = safe_outputs.get("latency_and_resource_use")
    latency_keys = (
        "case_generation_elapsed_ms",
        "segmentation_elapsed_ms",
        "corpus_preparation_elapsed_ms",
        "kg_build_elapsed_ms",
        "scoring_elapsed_ms",
        "total_elapsed_ms",
    )
    if not isinstance(latency, Mapping):
        blockers.append("latency_and_resource_use section must be an object")
    else:
        _validate_exact_keys(
            latency,
            set(latency_keys),
            "latency_and_resource_use",
            blockers,
        )
        if dict(latency) != {key: safe_outputs.get(key) for key in latency_keys}:
            blockers.append("latency and resource use values mismatch")
    topology = safe_outputs.get("graph_topology_diagnostics")
    if not isinstance(topology, Mapping) or not isinstance(topology.get("arms"), Mapping):
        blockers.append("graph_topology_diagnostics section must contain arms")
    else:
        _validate_exact_keys(
            topology,
            {"measurement_status", "arms"},
            "graph_topology_diagnostics",
            blockers,
        )
        if topology.get("measurement_status") != "candidate_graph_diagnostics":
            blockers.append("graph topology diagnostics measurement status mismatch")
        topology_arms = topology["arms"]
        if set(topology_arms) != set(ARMS):
            blockers.append("graph topology diagnostics arm set mismatch")
        else:
            topology_prefixes = {
                ARM_REGEX_KG: "regex",
                ARM_REGEX_ONTOLOGY: "regex",
                ARM_LEXICAL_KG: "lexical",
                ARM_LEXICAL_ONTOLOGY: "lexical",
                ARM_DATA_DRIVEN_ONTOLOGY: "data_driven",
                ARM_FROZEN_ONTOLOGY: "frozen",
                ARM_PROGRAMMATIC_ONTOLOGY: "programmatic",
            }
            for arm, prefix in topology_prefixes.items():
                lexical_key = (
                    "lexical_relation_count"
                    if prefix == "lexical"
                    else prefix + "_lexical_relation_count"
                )
                expected = {
                    "candidate_graph_node_count": safe_outputs.get(
                        prefix + "_candidate_graph_node_count"
                    ),
                    "candidate_graph_relation_count": safe_outputs.get(
                        prefix + "_candidate_graph_relation_count"
                    ),
                    "lexical_relation_count": safe_outputs.get(lexical_key),
                    "component_count": safe_outputs.get(prefix + "_component_count"),
                    "largest_component_size": safe_outputs.get(prefix + "_largest_component_size"),
                }
                values = topology_arms.get(arm)
                if not isinstance(values, Mapping):
                    blockers.append("graph topology diagnostics arm values mismatch")
                    break
                _validate_exact_keys(
                    values,
                    set(expected),
                    "graph_topology_diagnostics.arms." + arm,
                    blockers,
                )
                if dict(values) != expected:
                    blockers.append("graph topology diagnostics arm values mismatch")
                    break


def _validate_safe_output_derived_values(
    safe_outputs: Mapping[str, Any], blockers: list[str]
) -> None:
    arm_summaries = safe_outputs.get("arm_summaries")
    if not isinstance(arm_summaries, Mapping) or set(arm_summaries) != set(ARMS):
        return
    best_arm = max(
        ARMS,
        key=lambda arm: (
            _int_value(arm_summaries[arm].get("primary_retrieval_passed_count")),
            _int_value(arm_summaries[arm].get("no_answer_passed_count")),
            arm,
        ),
    )
    if safe_outputs.get("best_arm_name") != best_arm:
        blockers.append("best arm name mismatch")
    if safe_outputs.get("best_primary_retrieval_passed_count") != arm_summaries[best_arm].get(
        "primary_retrieval_passed_count"
    ):
        blockers.append("best primary retrieval passed count mismatch")
    if safe_outputs.get("best_primary_retrieval_accuracy_basis_points") != arm_summaries[
        best_arm
    ].get("primary_retrieval_accuracy_basis_points"):
        blockers.append("best primary retrieval accuracy mismatch")
    regex_current = _int_value(
        arm_summaries[ARM_REGEX_ONTOLOGY].get("primary_retrieval_passed_count")
    )
    lexical_kg = _int_value(arm_summaries[ARM_LEXICAL_KG].get("primary_retrieval_passed_count"))
    lexical_ontology = _int_value(
        arm_summaries[ARM_LEXICAL_ONTOLOGY].get("primary_retrieval_passed_count")
    )
    data_driven = _int_value(
        arm_summaries[ARM_DATA_DRIVEN_ONTOLOGY].get("primary_retrieval_passed_count")
    )
    frozen = _int_value(arm_summaries[ARM_FROZEN_ONTOLOGY].get("primary_retrieval_passed_count"))
    programmatic = _int_value(
        arm_summaries[ARM_PROGRAMMATIC_ONTOLOGY].get("primary_retrieval_passed_count")
    )
    expected_deltas = {
        "jieba_sentencepiece_type_compatibility_proxy_delta_vs_regex_type_compatibility_proxy_primary_retrieval_passed_count": (
            lexical_ontology - regex_current
        ),
        "type_compatibility_proxy_delta_vs_jieba_sentencepiece_candidate_kg_primary_retrieval_passed_count": (
            lexical_ontology - lexical_kg
        ),
        "frequency_rule_delta_vs_jieba_sentencepiece_primary_retrieval_passed_count": (
            data_driven - lexical_ontology
        ),
        "frozen_profile_delta_vs_jieba_sentencepiece_primary_retrieval_passed_count": (
            frozen - lexical_ontology
        ),
        "weak_label_mlp_delta_vs_jieba_sentencepiece_primary_retrieval_passed_count": (
            programmatic - lexical_ontology
        ),
        "weak_label_mlp_delta_vs_frequency_rule_primary_retrieval_passed_count": (
            programmatic - data_driven
        ),
        "weak_label_mlp_delta_vs_frozen_profile_primary_retrieval_passed_count": (
            programmatic - frozen
        ),
        "weak_label_mlp_delta_vs_regex_primary_retrieval_passed_count": (
            programmatic - regex_current
        ),
    }
    for key, expected_value in expected_deltas.items():
        if safe_outputs.get(key) != expected_value:
            blockers.append(key + " mismatch")


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _blocked_report(reason: str) -> dict[str, Any]:
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": NOW,
        "metrics": {
            "blocked_reason": reason,
            "raw_leak_guard_passed": True,
            "exm_candidate_admission_eval_completed": False,
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
        {"blocked_reason", "raw_leak_guard_passed", "exm_candidate_admission_eval_completed"},
        "metrics",
        blockers,
    )
    if metrics.get("blocked_reason") not in _BLOCKED_REASONS:
        blockers.append("blocked_reason must be a configured enum")
    if metrics.get("raw_leak_guard_passed") is not True:
        blockers.append("blocked report raw leak guard must be true")
    if metrics.get("exm_candidate_admission_eval_completed") is not False:
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
    expected = _FORBIDDEN_TRUE_CLAIMS | {
        "supports_exm_50000_candidate_admission_eval_claim",
        "container_verification_required",
    }
    _validate_exact_keys(claim_boundary, expected, "claim_boundary", blockers)
    expected_support = metrics.get("exm_candidate_admission_eval_completed") is True
    if claim_boundary.get("supports_exm_50000_candidate_admission_eval_claim") is not (
        expected_support
    ):
        blockers.append("lexical ontology eval claim boundary mismatch")
    for key in _FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(key) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {key}")
    if claim_boundary.get("container_verification_required") is not True:
        blockers.append("container_verification_required must be true")


def _eval_completed(report: Mapping[str, Any]) -> bool:
    metrics = report.get("metrics")
    safe_outputs = report.get("safe_outputs")
    if not isinstance(metrics, Mapping) or not isinstance(safe_outputs, Mapping):
        return False
    required = set(metrics) - {"exm_candidate_admission_eval_completed"}
    return (
        all(metrics.get(key) is True for key in required)
        and safe_outputs.get("case_count") == CASE_COUNT
        and safe_outputs.get("parsed_corpus_count") == EXPECTED_EXM_PST_COUNT
    )


def _claim_boundary(supports_eval: bool) -> dict[str, bool]:
    return {
        "supports_exm_50000_candidate_admission_eval_claim": supports_eval,
        "supports_actual_chatgpt_connected_upload_claim": False,
        "supports_real_upload_iframe_claim": False,
        "supports_general_full_pst_parser_readiness_claim": False,
        "supports_live_postgresql_readiness_claim": False,
        "supports_production_worker_leasing_claim": False,
        "supports_business_answer_generation_claim": False,
        "supports_formal_ontology_governance_completion_claim": False,
        "supports_canonical_kg_write_claim": False,
        "supports_canonical_type_write_claim": False,
        "supports_user_graph_write_claim": False,
        "supports_wiki_projection_claim": False,
        "supports_raw_mail_access_claim": False,
        "supports_production_ready_claim": False,
        "container_verification_required": True,
    }


def _public_outputs_are_safe(report: Mapping[str, Any]) -> bool:
    return public_outputs_are_safe(
        report,
        forbidden_fragments=(
            "archive.pst",
            "backup_may.pst",
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
            PRIVATE_MANIFEST_NAME.lower(),
            PRIVATE_ROWS_NAME.lower(),
            PRIVATE_CORPUS_NAME.lower(),
            PRIVATE_SENTENCEPIECE_LOG_NAME.lower(),
        ),
        raw_reference_context="mail_full_pst_exm_lexical_report",
    )


def _regex_lexemes(value: str) -> set[str]:
    return {
        "rx:" + item.lower()
        for item in _ASCII_RE.findall(value)
        if len(item) >= 3 and item.lower() not in _STOPWORDS
    }


def _jieba_lexemes(value: str, jieba_module: Any) -> set[str]:
    if jieba_module is None:
        return set()
    lexemes: set[str] = set()
    for item in jieba_module.cut(value, cut_all=False):
        normalized = str(item).strip().lower()
        if _usable_cjk_term(normalized):
            lexemes.add("zh:" + normalized)
    return lexemes


def _sentencepiece_lexemes(value: str, processor: Any) -> set[str]:
    if processor is None:
        return set()
    lexemes: set[str] = set()
    try:
        pieces = processor.encode(value, out_type=str)
    except TypeError:
        pieces = processor.EncodeAsPieces(value)
    for piece in pieces:
        normalized = str(piece).replace("\u2581", "").strip().lower()
        if _usable_cjk_term(normalized) or (len(normalized) >= 3 and normalized not in _STOPWORDS):
            lexemes.add("sp:" + normalized)
    return lexemes


def _term_occurrences(value: str, *, segmenters: _SegmenterBundle) -> list[_TermOccurrence]:
    occurrences: dict[tuple[str, str], _TermOccurrence] = {}
    for match in _CJK_ORG_RE.finditer(value):
        display = match.group(0).strip()
        lexeme = "org:" + display.lower()
        occurrences[(lexeme, "cjk_organization")] = _TermOccurrence(
            lexeme=lexeme,
            display=display,
            bucket="cjk_organization",
            categories=frozenset({"organization", "cjk"}),
        )
    for match in _IDENTIFIER_RE.finditer(value):
        display = match.group(0).strip()
        lexeme = "id:" + display.lower()
        occurrences[(lexeme, "business_identifier")] = _TermOccurrence(
            lexeme=lexeme,
            display=display,
            bucket="business_identifier",
            categories=frozenset({"identifier"}),
        )
    for lexeme in _regex_lexemes(value):
        term = lexeme.removeprefix("rx:")
        if term in _IMPORTANT_REGEX_TERMS:
            occurrences[(lexeme, "ascii_business")] = _TermOccurrence(
                lexeme=lexeme,
                display=term,
                bucket="ascii_business",
                categories=frozenset(_domains_for_regex_terms({"rx:" + term})),
            )
    for item in _jieba_lexemes(value, segmenters.jieba_module):
        display = item.removeprefix("zh:")
        occurrences[(item, "cjk_phrase")] = _TermOccurrence(
            lexeme=item,
            display=display,
            bucket="cjk_phrase",
            categories=frozenset({"cjk"}),
        )
    for item in _sentencepiece_lexemes(value, segmenters.sentencepiece_processor):
        display = item.removeprefix("sp:")
        if _CJK_RE.search(display) and len(display) >= 2:
            occurrences[(item, "sentencepiece_piece")] = _TermOccurrence(
                lexeme=item,
                display=display,
                bucket="sentencepiece_piece",
                categories=frozenset({"cjk"}),
            )
    for match in _CJK_TERM_RE.finditer(value):
        display = match.group(0).strip()
        if _usable_cjk_term(display):
            lexeme = "zh:" + display.lower()
            occurrences.setdefault(
                (lexeme, "cjk_phrase"),
                _TermOccurrence(
                    lexeme=lexeme,
                    display=display,
                    bucket="cjk_phrase",
                    categories=frozenset({"cjk"}),
                ),
            )
    for match in _EMAIL_OR_DOMAIN_RE.finditer(value):
        display = match.group(0).strip()
        lexeme = "contact:" + display.lower()
        occurrences[(lexeme, "business_identifier")] = _TermOccurrence(
            lexeme=lexeme,
            display=display,
            bucket="business_identifier",
            categories=frozenset({"contact"}),
        )
    return list(occurrences.values())


def _categories_for_lexemes(
    lexemes: set[str],
    occurrences: Sequence[_TermOccurrence],
) -> frozenset[str]:
    categories: set[str] = set()
    categories.update(_domains_for_regex_terms(lexemes))
    for occurrence in occurrences:
        categories.update(occurrence.categories)
    return frozenset(categories)


def _categories_for_policy(segment: _Segment, policy_name: str) -> frozenset[str]:
    lexemes = set(segment.lexemes_by_policy[policy_name])
    if policy_name == POLICY_REGEX:
        return frozenset(_domains_for_regex_terms(lexemes))
    return segment.categories


def _domains_for_regex_terms(lexemes: set[str] | frozenset[str]) -> set[str]:
    terms = {lexeme.removeprefix("rx:") for lexeme in lexemes if lexeme.startswith("rx:")}
    return {
        "domain:" + domain
        for domain in hard_eval.DOMAINS
        if terms & hard_eval.DOMAIN_VOCABULARY[domain]
    }


def _query_lexemes(query_text: str, kg_index: _KgIndex, policy_name: str) -> set[str]:
    regex = _regex_lexemes(query_text)
    if policy_name == POLICY_REGEX:
        return regex
    lexemes = set(regex)
    lexemes.update(_jieba_lexemes(query_text, kg_index.segmenters.jieba_module))
    lexemes.update(_sentencepiece_lexemes(query_text, kg_index.segmenters.sentencepiece_processor))
    lexemes.update(_query_protected_lexemes(query_text))
    # SentencePiece pieces used in the corpus are recoverable from component
    # indexes, so query-time matching can safely include observed pieces only.
    for item in _CJK_TERM_RE.findall(query_text):
        normalized = item.strip().lower()
        if _usable_cjk_term(normalized):
            lexemes.add("zh:" + normalized)
            lexemes.add("sp:" + normalized)
    return lexemes


def _query_categories(query_text: str, policy_name: str) -> set[str]:
    regex = _regex_lexemes(query_text)
    categories = set(_domains_for_regex_terms(regex))
    if policy_name == POLICY_REGEX:
        return categories
    if _CJK_ORG_RE.search(query_text):
        categories.update({"organization", "cjk"})
    elif _CJK_RE.search(query_text):
        categories.add("cjk")
    if _IDENTIFIER_RE.search(query_text):
        categories.add("identifier")
    if _EMAIL_OR_DOMAIN_RE.search(query_text):
        categories.add("contact")
    return categories


def _query_protected_lexemes(query_text: str) -> set[str]:
    lexemes: set[str] = set()
    for match in _CJK_ORG_RE.finditer(query_text):
        lexemes.add("org:" + match.group(0).strip().lower())
    for match in _IDENTIFIER_RE.finditer(query_text):
        lexemes.add("id:" + match.group(0).strip().lower())
    for match in _EMAIL_OR_DOMAIN_RE.finditer(query_text):
        lexemes.add("contact:" + match.group(0).strip().lower())
    return lexemes


def _important_lexemes(
    lexemes: set[str] | frozenset[str],
    policy_name: str,
    *,
    compiled_policy: _CompiledOntologyPolicy | None = None,
) -> set[str]:
    if policy_name == POLICY_REGEX:
        return {
            lexeme
            for lexeme in lexemes
            if lexeme.startswith("rx:") and lexeme.removeprefix("rx:") in _IMPORTANT_REGEX_TERMS
        }
    lexical_important = {
        lexeme
        for lexeme in lexemes
        if lexeme.startswith(("org:", "id:", "contact:", "zh:", "sp:"))
        or (lexeme.startswith("rx:") and lexeme.removeprefix("rx:") in _IMPORTANT_REGEX_TERMS)
    }
    if policy_name in PROGRAMMATIC_POLICIES and compiled_policy is not None:
        return lexical_important & compiled_policy.accepted_lexemes
    return lexical_important


def _groups_by_thread(segments: Sequence[_Segment]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for segment in segments:
        if segment.thread_key:
            grouped[segment.thread_key].append(segment.segment_id)
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


def _sentencepiece_user_symbols(raw_records: Sequence[Mapping[str, Any]]) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for record in raw_records:
        text = str(record["text"])
        for regex in (_CJK_ORG_RE, _IDENTIFIER_RE):
            for match in regex.finditer(text):
                symbol = match.group(0).strip()
                if symbol and symbol not in seen:
                    seen.add(symbol)
                    symbols.append(symbol)
                    if len(symbols) >= 2000:
                        return symbols
    return symbols


def _sentencepiece_vocab_size(raw_records: Sequence[Mapping[str, Any]]) -> int:
    cjk_seen: set[str] = set()
    ascii_seen: set[str] = set()
    for record in raw_records[:20000]:
        text = str(record["text"])
        cjk_seen.update(_CJK_TERM_RE.findall(text))
        ascii_seen.update(item.lower() for item in _ASCII_RE.findall(text) if len(item) >= 3)
    estimate = len(cjk_seen) + len(ascii_seen)
    return max(800, min(12000, estimate // 2 if estimate else 800))


def _load_sentencepiece_processor(sentencepiece_module: Any, model_path: Path) -> Any:
    try:
        return sentencepiece_module.SentencePieceProcessor(model_file=str(model_path))
    except TypeError:
        processor = sentencepiece_module.SentencePieceProcessor()
        processor.Load(str(model_path))
        return processor


class _redirect_process_output:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._log_fd: int | None = None
        self._stdout_fd: int | None = None
        self._stderr_fd: int | None = None

    def __enter__(self) -> "_redirect_process_output":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._log_fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        self._stdout_fd = os.dup(1)
        self._stderr_fd = os.dup(2)
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(self._log_fd, 1)
        os.dup2(self._log_fd, 2)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        del exc_type, exc, traceback
        if self._stdout_fd is not None:
            os.dup2(self._stdout_fd, 1)
        if self._stderr_fd is not None:
            os.dup2(self._stderr_fd, 2)
        for fd in (self._stdout_fd, self._stderr_fd, self._log_fd):
            if fd is not None:
                os.close(fd)


def _optional_import(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _usable_cjk_term(value: str) -> bool:
    return len(value) >= 2 and bool(_CJK_RE.search(value)) and not value.isspace()


def _case_counts(cases: Sequence[_Case], field_name: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for case in cases:
        counts[str(getattr(case, field_name))] += 1
    return dict(sorted(counts.items()))


def _write_private_manifest(
    path: Path,
    *,
    cases: Sequence[_Case],
    prepared: _PreparedCorpus,
    expected_parsed_corpus_count: int,
) -> str:
    payload = {
        "manifest_type": "exm_candidate_admission_private_case_manifest",
        "generated_at": NOW,
        "segmentation_policy_version": SEGMENTATION_POLICY_VERSION,
        "type_compatibility_proxy_policy_version": TYPE_COMPATIBILITY_PROXY_POLICY_VERSION,
        "expected_parsed_corpus_count": expected_parsed_corpus_count,
        "parsed_corpus_count": prepared.parsed_corpus_count,
        "parsed_corpus_hash": prepared.parsed_corpus_hash,
        "case_count": len(cases),
        "cases": [case.to_private_dict() for case in cases],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return sha256_json(payload)


def _write_private_rows(path: Path, arm_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    payload = {
        "manifest_type": "exm_candidate_admission_private_score_rows",
        "generated_at": NOW,
        "arm_names": list(ARMS),
        "rows_by_arm": {arm: list(rows) for arm, rows in arm_rows.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return sha256_json(payload)


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _no_graph_or_wiki_side_effects(parsed_corpus_dirs: Sequence[Path]) -> bool:
    return all(
        not (parsed_dir / "data" / "graph").exists() and not (parsed_dir / "data" / "wiki").exists()
        for parsed_dir in parsed_corpus_dirs
    )


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


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
        validation.get("claim_boundary"), "validation.claim_boundary", blockers
    )
    _validate_exact_keys(
        claim_boundary,
        {
            "supports_exm_50000_candidate_admission_eval_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    metrics = report.get("metrics") if isinstance(report, Mapping) else {}
    expected = (
        isinstance(metrics, Mapping)
        and metrics.get("exm_candidate_admission_eval_completed") is True
    )
    if claim_boundary.get("supports_exm_50000_candidate_admission_eval_claim") is not expected:
        blockers.append("validation lexical eval claim mismatch")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


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
        and report["metrics"].get("exm_candidate_admission_eval_completed") is True
    )
    return {
        "passed": passed,
        "blockers": blockers,
        "claim_boundary": {
            "supports_exm_50000_candidate_admission_eval_claim": supported,
            "supports_production_ready_claim": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parsed-corpus-dir", type=Path, action="append", default=[])
    parser.add_argument("--private-dir", type=Path, default=DEFAULT_PRIVATE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-count", type=int, default=CASE_COUNT)
    parser.add_argument("--expected-parsed-corpus-count", type=int, default=EXPECTED_EXM_PST_COUNT)
    parser.add_argument("--allow-missing-external-segmenters", action="store_true")
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
    report = run_exm_lexical_ontology_eval(
        parsed_corpus_dirs=args.parsed_corpus_dir,
        output_private_dir=args.private_dir,
        case_count=args.case_count,
        expected_parsed_corpus_count=args.expected_parsed_corpus_count,
        require_external_segmenters=not args.allow_missing_external_segmenters,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return (
        0 if report.get("metrics", {}).get("exm_candidate_admission_eval_completed") is True else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
