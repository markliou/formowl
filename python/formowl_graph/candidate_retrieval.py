"""Source-neutral candidate evidence planning and proof-neighborhood retrieval."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
from types import CodeType
from typing import Callable, Iterable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID = "formowl_source_neutral_candidate_evidence_retrieval_v3"
DEFAULT_CANDIDATE_EVIDENCE_ONTOLOGY_POLICY_ID = "formowl_source_neutral_soft_ontology_rerank_v2"
DEFAULT_CANDIDATE_EVIDENCE_HARNESS_SCHEMA_ID = "formowl_candidate_evidence_harness_onboarding_v1"
DEFAULT_CANDIDATE_EVIDENCE_SOURCE_SHAPES = (
    "application_event",
    "audio_video_segment",
    "finance_record",
    "image_ocr_region",
    "mail_message",
    "pdf_page_or_section",
    "ppt_slide",
    "quality_record",
    "table_row",
)
_QUERY_TERM_RE = re.compile(r"[A-Za-z0-9_@.-]+|[\u3400-\u9fff]{2,12}")
_QUERY_CONTROL_TERMS = {
    "about",
    "across",
    "all",
    "and",
    "between",
    "compare",
    "collect",
    "cross",
    "did",
    "different",
    "email",
    "emails",
    "evidence",
    "find",
    "for",
    "from",
    "in",
    "involving",
    "latest",
    "mail",
    "mention",
    "mentions",
    "message",
    "messages",
    "multiple",
    "possible",
    "piece",
    "reconcile",
    "record",
    "records",
    "related",
    "say",
    "said",
    "separate",
    "separate-email",
    "show",
    "summarize",
    "that",
    "the",
    "thread",
    "together",
    "update",
    "updates",
    "what",
    "which",
    "who",
    "with",
}
_CHRONOLOGY_TERMS = {
    "after",
    "before",
    "chronology",
    "earliest",
    "latest",
    "timeline",
    "之後",
    "之前",
    "以後",
    "以前",
    "先後",
    "最早",
    "最晚",
    "最新",
    "時序",
}
_ACTOR_TERMS = {
    "actor",
    "asked",
    "mentioned",
    "noted",
    "report",
    "reported",
    "reports",
    "requested",
    "said",
    "say",
    "stated",
    "wrote",
}
_CONFLICT_TERMS = {
    "conflict",
    "conflicting",
    "contradiction",
    "contradictory",
    "disagree",
    "inconsistent",
    "reconcile",
    "tension",
}
_APPROVAL_TERMS = {"approval", "approved", "decision", "final"}
_MULTI_RECORD_TERMS = {
    "across",
    "multiple",
    "separate",
    "several",
    "多份",
    "多筆",
    "多個",
}
_SOURCE_DESCRIPTOR_TERMS = {
    "attachment",
    "attachments",
    "cell",
    "cells",
    "document",
    "documents",
    "email",
    "emails",
    "evidence",
    "file",
    "files",
    "image",
    "images",
    "mail",
    "message",
    "messages",
    "page",
    "pages",
    "pdf",
    "record",
    "records",
    "row",
    "rows",
    "sheet",
    "sheets",
    "slide",
    "slides",
    "table",
    "tables",
    "thread",
    "threads",
}
_DOCUMENT_MODALITIES = {
    "document",
    "doc",
    "docx",
    "email",
    "mail",
    "pdf",
    "ppt",
    "pptx",
    "presentation",
    "text",
}
_STRUCTURED_RECORD_MODALITIES = {
    "csv",
    "database",
    "erp",
    "spreadsheet",
    "table",
    "xls",
    "xlsx",
}
_AUDIO_VISUAL_MODALITIES = {"audio", "video"}
_IMAGE_MODALITIES = {"image", "ocr", "photo", "scan"}
_DOCUMENT_OBSERVATION_TERMS = {
    "document",
    "email",
    "mail",
    "page",
    "paragraph",
    "section",
    "slide",
    "text_block",
}
_STRUCTURED_RECORD_OBSERVATION_TERMS = {
    "cell",
    "database_row",
    "erp_row",
    "journal_entry",
    "ledger_entry",
    "spreadsheet_row",
    "table_row",
    "transaction",
}
_AUDIO_VISUAL_OBSERVATION_TERMS = {
    "audio_segment",
    "audio_transcript",
    "speech_segment",
    "transcript",
    "video_segment",
}
_IMAGE_OBSERVATION_TERMS = {
    "image",
    "image_region",
    "ocr_region",
    "photo",
    "scan_region",
}
_EVENT_OBSERVATION_TERMS = {
    "application_event",
    "audit_event",
    "event",
    "inspection_event",
    "log_event",
    "sensor_event",
    "workflow_event",
}
_MEASUREMENT_SEMANTIC_ROLES = {
    "amount",
    "currency_amount",
    "duration",
    "measurement",
    "percentage",
    "quantity",
    "rate",
    "score",
    "unit_value",
}
_SHA256_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")
_NORMALIZATION_POLICY_ID_RE = re.compile(r"unicode_nfkc(?:_[a-z0-9]+)*_v[1-9][0-9]*")
_SEGMENTATION_POLICY_ID_RE = re.compile(r"jieba_sentencepiece(?:_[a-z0-9]+)*_v[1-9][0-9]*")
_CANDIDATE_ADMISSION_POLICY_ID_RE = re.compile(r"frozen_profile(?:_[a-z0-9]+)+")
_RUNTIME_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.:+-]*")
_LogicalSourceKey = tuple[str, str]


@dataclass(frozen=True)
class CandidateEvidenceHarnessContract:
    """Exact onboarding contract for every default retrieval harness.

    Historical chunk-count, lexical-component, regex-only, and ontology
    hard-pruning methods remain valid ablations, but they must not be accepted
    by the production/default ``CandidateEvidenceIndex``.
    """

    schema_id: str = DEFAULT_CANDIDATE_EVIDENCE_HARNESS_SCHEMA_ID
    method_id: str = DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID
    evidence_unit: str = "logical_source_item"
    source_identity: str = "source_identity_policy_id+source_item_id"
    access_order: str = "binding_before_query_vocabulary"
    context_policy: str = "explicit_query_context"
    temporal_policy: str = "admissibility_before_planning"
    anchor_policy: str = "conjunctive_within_logical_source"
    ontology_policy: str = "capped_additive_rerank"
    text_policy: str = "unicode+protected_ascii+jieba+corpus_bound_sentencepiece"
    candidate_admission_policy: str = "frozen_profile"
    query_token_source: str = "index_owned_text_policy_runtime"
    ablation_entrypoint: str = "retrieve_ablation"
    text_policy_binding_required: bool = True
    regex_only_default_allowed: bool = False
    parser_chunk_cardinality_allowed: bool = False
    lexical_transitive_closure_allowed: bool = False
    ontology_hard_pruning_allowed: bool = False
    canonical_write_allowed: bool = False
    supported_source_shapes: tuple[str, ...] = DEFAULT_CANDIDATE_EVIDENCE_SOURCE_SHAPES


def build_default_candidate_evidence_harness_contract() -> CandidateEvidenceHarnessContract:
    """Return the one default retrieval contract used by new harnesses."""

    return CandidateEvidenceHarnessContract()


def require_default_candidate_evidence_harness_contract(
    contract: CandidateEvidenceHarnessContract,
) -> None:
    """Reject a harness that silently onboards an obsolete retrieval method."""

    expected = build_default_candidate_evidence_harness_contract()
    if contract != expected:
        raise ValueError(
            "candidate evidence harness must use the default source-neutral contract; "
            "legacy chunk-count, transitive-component, regex-only, and ontology "
            "hard-pruning methods are ablations only"
        )


@dataclass(frozen=True)
class CandidateEvidenceTextPolicyBinding:
    """Hash-bound proof that index and query use the normative text stack."""

    normalization_policy_version: str
    segmentation_policy_version: str
    candidate_admission_policy: str
    candidate_admission_policy_hash: str
    sentencepiece_model_hash: str
    sentencepiece_training_corpus_hash: str
    query_tokenizer_runtime_id: str
    query_tokenizer_implementation_hash: str
    protected_ascii_identifier_extraction: bool = True
    jieba_segmentation: bool = True
    corpus_bound_sentencepiece: bool = True
    frozen_profile_admission: bool = True
    regex_only: bool = False

    def __post_init__(self) -> None:
        required_values = (
            self.normalization_policy_version,
            self.segmentation_policy_version,
            self.candidate_admission_policy,
            self.candidate_admission_policy_hash,
            self.sentencepiece_model_hash,
            self.sentencepiece_training_corpus_hash,
            self.query_tokenizer_runtime_id,
            self.query_tokenizer_implementation_hash,
        )
        if any(_is_blank_text(value) for value in required_values):
            raise ValueError("candidate evidence text policy fields are required")
        boolean_fields = (
            self.protected_ascii_identifier_extraction,
            self.jieba_segmentation,
            self.corpus_bound_sentencepiece,
            self.frozen_profile_admission,
            self.regex_only,
        )
        if any(type(value) is not bool for value in boolean_fields):
            raise ValueError("candidate evidence text policy flags must be booleans")
        if self.regex_only:
            raise ValueError("regex-only tokenization is an ablation-only policy")
        normalized_policy = self.normalization_policy_version.strip().lower()
        if _NORMALIZATION_POLICY_ID_RE.fullmatch(normalized_policy) is None:
            raise ValueError("Unicode NFKC normalization policy is required")
        segmentation_policy = self.segmentation_policy_version.strip().lower()
        if _SEGMENTATION_POLICY_ID_RE.fullmatch(segmentation_policy) is None:
            raise ValueError("Jieba and SentencePiece segmentation policy is required")
        if (
            _CANDIDATE_ADMISSION_POLICY_ID_RE.fullmatch(
                self.candidate_admission_policy.strip().lower()
            )
            is None
        ):
            raise ValueError("candidate admission policy must be a frozen-profile policy")
        if _RUNTIME_ID_RE.fullmatch(self.query_tokenizer_runtime_id.strip().lower()) is None:
            raise ValueError("candidate evidence query tokenizer runtime id is invalid")
        for value in (
            self.candidate_admission_policy_hash,
            self.sentencepiece_model_hash,
            self.sentencepiece_training_corpus_hash,
            self.query_tokenizer_implementation_hash,
        ):
            if _SHA256_HASH_RE.fullmatch(value.strip().lower()) is None:
                raise ValueError("candidate evidence policy hashes must be SHA-256 values")
        if not self.protected_ascii_identifier_extraction:
            raise ValueError("protected ASCII identifier extraction is required")
        if not self.jieba_segmentation:
            raise ValueError("Jieba segmentation is required")
        if not self.corpus_bound_sentencepiece:
            raise ValueError("corpus-bound SentencePiece segmentation is required")
        if not self.frozen_profile_admission:
            raise ValueError("frozen-profile candidate admission is required")

    @property
    def binding_hash(self) -> str:
        payload = json.dumps(
            {
                "normalization_policy_version": self.normalization_policy_version,
                "segmentation_policy_version": self.segmentation_policy_version,
                "candidate_admission_policy": self.candidate_admission_policy,
                "candidate_admission_policy_hash": self.candidate_admission_policy_hash,
                "sentencepiece_model_hash": self.sentencepiece_model_hash,
                "sentencepiece_training_corpus_hash": (self.sentencepiece_training_corpus_hash),
                "query_tokenizer_runtime_id": self.query_tokenizer_runtime_id,
                "query_tokenizer_implementation_hash": (self.query_tokenizer_implementation_hash),
                "protected_ascii_identifier_extraction": (
                    self.protected_ascii_identifier_extraction
                ),
                "jieba_segmentation": self.jieba_segmentation,
                "corpus_bound_sentencepiece": self.corpus_bound_sentencepiece,
                "frozen_profile_admission": self.frozen_profile_admission,
                "regex_only": self.regex_only,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class CandidateEvidenceTextPolicyRuntime:
    """Index-owned query tokenizer for one structured text-policy binding."""

    binding: CandidateEvidenceTextPolicyBinding
    runtime_id: str
    tokenize_query: Callable[[str], Iterable[str]] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.binding, CandidateEvidenceTextPolicyBinding):
            raise ValueError("candidate evidence text policy binding is required")
        if _is_blank_text(self.runtime_id):
            raise ValueError("candidate evidence text policy runtime_id is required")
        if not callable(self.tokenize_query):
            raise ValueError("candidate evidence query tokenizer is required")
        if self.runtime_id != self.binding.query_tokenizer_runtime_id:
            raise ValueError("candidate evidence query tokenizer runtime id mismatch")
        if (
            candidate_evidence_tokenizer_implementation_hash(self.tokenize_query)
            != self.binding.query_tokenizer_implementation_hash
        ):
            raise ValueError("candidate evidence query tokenizer implementation hash mismatch")

    def tokenize(self, query_text: str) -> frozenset[str]:
        if not isinstance(query_text, str):
            raise ValueError("query_text must be a string")
        tokens = frozenset(
            token.strip().lower()
            for token in self.tokenize_query(query_text)
            if isinstance(token, str) and token.strip()
        )
        if any(_is_blank_text(token) for token in tokens):
            raise ValueError("query tokenizer returned an empty token")
        return tokens


def candidate_evidence_tokenizer_implementation_hash(
    tokenize_query: Callable[[str], Iterable[str]],
) -> str:
    """Return a clone-stable fingerprint for the bound Python tokenizer code.

    Model, corpus, and admission data are bound separately. This fingerprint
    prevents a structured policy declaration from being paired with different
    executable query-tokenizer code.
    """

    code = getattr(tokenize_query, "__code__", None)
    if not callable(tokenize_query) or not isinstance(code, CodeType):
        raise ValueError("candidate evidence query tokenizer must expose Python code identity")
    payload = {
        "module": getattr(tokenize_query, "__module__", ""),
        "qualname": getattr(tokenize_query, "__qualname__", ""),
        "code": _code_identity_payload(code),
        "defaults": _stable_code_identity_value(getattr(tokenize_query, "__defaults__", None)),
        "kwdefaults": _stable_code_identity_value(getattr(tokenize_query, "__kwdefaults__", None)),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{sha256(encoded.encode('utf-8')).hexdigest()}"


def _code_identity_payload(code: CodeType) -> dict[str, object]:
    return {
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "flags": code.co_flags,
        "code": code.co_code.hex(),
        "consts": [_stable_code_identity_value(value) for value in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
    }


def _stable_code_identity_value(value: object) -> object:
    if isinstance(value, CodeType):
        return {"code": _code_identity_payload(value)}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, tuple):
        return [_stable_code_identity_value(item) for item in value]
    if isinstance(value, frozenset):
        normalized = [_stable_code_identity_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    if isinstance(value, dict):
        return {
            str(key): _stable_code_identity_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    return {
        "type": f"{type(value).__module__}.{type(value).__qualname__}",
    }


def _is_blank_text(value: object) -> bool:
    return not isinstance(value, str) or not value.strip()


@dataclass(frozen=True)
class CandidateEvidenceRecord:
    """One citeable evidence observation plus source-neutral context facets."""

    observation_id: str
    source_item_id: str
    source_identity_policy_id: str
    source_version_id: str
    permission_scope_id: str
    tokens: frozenset[str]
    actor_tokens: frozenset[str] = field(default_factory=frozenset)
    context_ids: frozenset[str] = field(default_factory=frozenset)
    observed_at: str | None = None
    known_at: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    epistemic_status: str | None = None
    lifecycle_status: str | None = None
    ontology_signals: frozenset[str] = field(default_factory=frozenset)
    observation_type: str | None = None
    modality: str | None = None
    semantic_roles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if _is_blank_text(self.observation_id):
            raise ValueError("observation_id is required")
        if _is_blank_text(self.source_item_id):
            raise ValueError("source_item_id is required")
        if _is_blank_text(self.source_identity_policy_id):
            raise ValueError("source_identity_policy_id is required")
        if _is_blank_text(self.source_version_id):
            raise ValueError("source_version_id is required")
        if _is_blank_text(self.permission_scope_id):
            raise ValueError("permission_scope_id is required")
        if any(_is_blank_text(token) for token in self.tokens):
            raise ValueError("tokens must not contain empty values")
        if any(_is_blank_text(token) for token in self.actor_tokens):
            raise ValueError("actor_tokens must not contain empty values")
        if any(_is_blank_text(context_id) for context_id in self.context_ids):
            raise ValueError("context_ids must not contain empty values")
        if self.observed_at is not None:
            _parse_timestamp(self.observed_at)
        if self.known_at is not None:
            _parse_timestamp(self.known_at)
        if self.valid_from is not None:
            _parse_timestamp(self.valid_from)
        if self.valid_to is not None:
            _parse_timestamp(self.valid_to)
        if self.valid_from is not None and self.valid_to is not None:
            if _parse_timestamp(self.valid_from) > _parse_timestamp(self.valid_to):
                raise ValueError("valid_from must not be after valid_to")
        if self.epistemic_status is not None and not self.epistemic_status.strip():
            raise ValueError("epistemic_status must not be empty")
        if self.lifecycle_status is not None and not self.lifecycle_status.strip():
            raise ValueError("lifecycle_status must not be empty")
        if self.observation_type is not None and not self.observation_type.strip():
            raise ValueError("observation_type must not be empty")
        if self.modality is not None and not self.modality.strip():
            raise ValueError("modality must not be empty")
        if any(_is_blank_text(role) for role in self.semantic_roles):
            raise ValueError("semantic_roles must not contain empty values")


@dataclass(frozen=True)
class CandidateEvidenceAccessBinding:
    """Trusted retrieval eligibility resolved before query planning."""

    binding_id: str
    eligible_observation_ids: frozenset[str]
    eligible_source_identity_policy_ids: frozenset[str]
    eligible_permission_scope_ids: frozenset[str]
    eligible_source_version_ids: frozenset[str]

    def __post_init__(self) -> None:
        if type(self.binding_id) is not str or not self.binding_id.strip():
            raise ValueError("binding_id is required")
        for field_name in (
            "eligible_observation_ids",
            "eligible_source_identity_policy_ids",
            "eligible_permission_scope_ids",
            "eligible_source_version_ids",
        ):
            values = getattr(self, field_name)
            if type(values) is not frozenset:
                raise ValueError(f"{field_name} must be a frozenset")
            if any(type(value) is not str or not value.strip() for value in values):
                raise ValueError(f"{field_name} must contain exact nonblank strings")


def _require_candidate_evidence_access_binding(value: object) -> None:
    if type(value) is not CandidateEvidenceAccessBinding:
        raise ValueError("access binding must use CandidateEvidenceAccessBinding")
    CandidateEvidenceAccessBinding.__post_init__(value)


@dataclass(frozen=True)
class CandidateQueryPlan:
    """Query-independent vocabulary mapped to a universal evidence intent."""

    intent: str
    anchor_tokens: tuple[str, ...]
    actor_tokens: tuple[str, ...] = ()
    minimum_source_items: int = 1
    target_source_items: int = 1
    chronology_mode: str | None = None
    chronology_boundary: str | None = None
    chronology_timezone: str | None = None


@dataclass(frozen=True)
class CandidateRetrievalResult:
    """A bounded candidate-only proof neighborhood."""

    plan: CandidateQueryPlan
    selected_observation_ids: tuple[str, ...]
    rejected: bool
    rejection_reason: str | None = None


def infer_evidence_ontology_signals(
    *,
    observation_type: str | None,
    modality: str | None,
    semantic_roles: Iterable[str] = (),
    actor_tokens: Iterable[str] = (),
    observed_at: str | None = None,
    has_concept_content: bool = True,
) -> frozenset[str]:
    """Infer source-neutral evidence facets from typed extraction metadata.

    Numeric token shape is intentionally ignored. A value becomes measurement
    evidence only when extraction metadata assigns a measurement-bearing
    semantic role.
    """

    normalized_observation_type = _normalized_descriptor(observation_type)
    normalized_modality = _normalized_descriptor(modality)
    normalized_roles = {
        normalized
        for role in semantic_roles
        if (normalized := _normalized_descriptor(str(role))) is not None
    }
    signals: set[str] = set()
    if has_concept_content:
        signals.add("concept_evidence")
    if normalized_modality in _DOCUMENT_MODALITIES or _descriptor_matches(
        normalized_observation_type,
        _DOCUMENT_OBSERVATION_TERMS,
    ):
        signals.add("document_evidence")
    elif normalized_modality in _STRUCTURED_RECORD_MODALITIES or _descriptor_matches(
        normalized_observation_type,
        _STRUCTURED_RECORD_OBSERVATION_TERMS,
    ):
        signals.add("structured_record_evidence")
    elif normalized_modality in _AUDIO_VISUAL_MODALITIES or _descriptor_matches(
        normalized_observation_type,
        _AUDIO_VISUAL_OBSERVATION_TERMS,
    ):
        signals.add("audio_visual_evidence")
    elif normalized_modality in _IMAGE_MODALITIES or _descriptor_matches(
        normalized_observation_type,
        _IMAGE_OBSERVATION_TERMS,
    ):
        signals.add("image_evidence")
    elif _descriptor_matches(
        normalized_observation_type,
        _EVENT_OBSERVATION_TERMS,
    ):
        signals.add("event_evidence")
    else:
        signals.add("artifact_evidence")
    if any(token and str(token).strip() for token in actor_tokens):
        signals.add("actor_attributed_evidence")
    if observed_at is not None:
        _parse_timestamp(observed_at)
        signals.add("temporally_ordered_evidence")
    if normalized_roles & _MEASUREMENT_SEMANTIC_ROLES:
        signals.add("measurement_bearing_evidence")
    return frozenset(signals)


class CandidateEvidenceIndex:
    """Weighted evidence index that never uses lexical transitive closure."""

    def __init__(
        self,
        records: Sequence[CandidateEvidenceRecord],
        *,
        harness_contract: CandidateEvidenceHarnessContract | None = None,
        text_policy_runtime: CandidateEvidenceTextPolicyRuntime | None = None,
        access_binding: CandidateEvidenceAccessBinding | None = None,
        ontology_revision_id: str | None = None,
        ontology_signal_vocabulary_hash: str | None = None,
        ontology_contract_hash: str | None = None,
        ontology_query_signal_resolver: (
            Callable[[str, frozenset[str]], Iterable[str]] | None
        ) = None,
    ) -> None:
        if not records:
            raise ValueError("records are required")
        self._harness_contract = (
            build_default_candidate_evidence_harness_contract()
            if harness_contract is None
            else harness_contract
        )
        require_default_candidate_evidence_harness_contract(self._harness_contract)
        if text_policy_runtime is None:
            raise ValueError("candidate evidence text policy runtime is required")
        if not isinstance(text_policy_runtime, CandidateEvidenceTextPolicyRuntime):
            raise ValueError(
                "candidate evidence text policy runtime must use "
                "CandidateEvidenceTextPolicyRuntime"
            )
        if access_binding is not None:
            _require_candidate_evidence_access_binding(access_binding)
        self._text_policy_runtime = text_policy_runtime
        self._text_policy_binding = text_policy_runtime.binding
        by_id: dict[str, CandidateEvidenceRecord] = {}
        for record in records:
            if record.observation_id in by_id:
                raise ValueError("duplicate observation_id")
            by_id[record.observation_id] = record
        self._records = tuple(records)
        self._by_id = by_id
        self._access_binding = access_binding
        self._ontology_revision_id = ontology_revision_id
        self._ontology_signal_vocabulary_hash = ontology_signal_vocabulary_hash
        self._ontology_contract_hash = ontology_contract_hash
        self._ontology_query_signal_resolver = ontology_query_signal_resolver
        self._by_source_item: dict[_LogicalSourceKey, tuple[CandidateEvidenceRecord, ...]] = {
            source_key: tuple(sorted(items, key=lambda item: item.observation_id))
            for source_key, items in _group_records_by_source_key(records).items()
        }
        self._record_ids_by_token = _record_ids_by_token(records)
        self._record_ids_by_actor_token = _record_ids_by_actor_token(records)

    @property
    def record_count(self) -> int:
        return len(self._records)

    @property
    def source_item_count(self) -> int:
        return len(self._by_source_item)

    @property
    def searchable_token_count(self) -> int:
        return len(self._record_ids_by_token)

    @property
    def records(self) -> tuple[CandidateEvidenceRecord, ...]:
        return self._records

    @property
    def harness_contract(self) -> CandidateEvidenceHarnessContract:
        return self._harness_contract

    @property
    def text_policy_binding(self) -> CandidateEvidenceTextPolicyBinding:
        return self._text_policy_binding

    @property
    def text_policy_runtime(self) -> CandidateEvidenceTextPolicyRuntime:
        return self._text_policy_runtime

    def retrieve(
        self,
        *,
        query_text: str,
        limit: int = 10,
        source_item_budget: int | None = None,
        observation_budget: int | None = None,
        requested_source_item_count: int | None = None,
        enable_ontology_rerank: bool = False,
        access_binding: CandidateEvidenceAccessBinding | None = None,
        eligible_observation_ids: Iterable[str] | None = None,
        ontology_revision_id: str | None = None,
        ontology_signal_vocabulary_hash: str | None = None,
        ontology_contract_hash: str | None = None,
        eligible_context_ids: Iterable[str] | None = None,
        accessible_context_ids: Iterable[str] | None = None,
        query_context_ids: Iterable[str] | None = None,
        allow_cross_context_comparison: bool = False,
        known_as_of: str | None = None,
        as_of_world_time: str | None = None,
        allowed_epistemic_statuses: Iterable[str] | None = None,
        allowed_lifecycle_statuses: Iterable[str] | None = None,
        query_timezone: str | None = None,
    ) -> CandidateRetrievalResult:
        return self._retrieve(
            query_text=query_text,
            limit=limit,
            source_item_budget=source_item_budget,
            observation_budget=observation_budget,
            requested_source_item_count=requested_source_item_count,
            enable_ontology_rerank=enable_ontology_rerank,
            access_binding=access_binding,
            eligible_observation_ids=eligible_observation_ids,
            ontology_revision_id=ontology_revision_id,
            ontology_signal_vocabulary_hash=ontology_signal_vocabulary_hash,
            ontology_contract_hash=ontology_contract_hash,
            eligible_context_ids=eligible_context_ids,
            accessible_context_ids=accessible_context_ids,
            query_context_ids=query_context_ids,
            allow_cross_context_comparison=allow_cross_context_comparison,
            known_as_of=known_as_of,
            as_of_world_time=as_of_world_time,
            allowed_epistemic_statuses=allowed_epistemic_statuses,
            allowed_lifecycle_statuses=allowed_lifecycle_statuses,
            query_timezone=query_timezone,
            ablation_id=None,
            query_token_transform=None,
            eligible_observation_filter=None,
            ontology_query_signal_transform=None,
        )

    def retrieve_ablation(
        self,
        *,
        query_text: str,
        ablation_id: str,
        query_token_transform: Callable[[frozenset[str]], Iterable[str]],
        eligible_observation_filter: (
            Callable[[set[str], frozenset[str]], Iterable[str]] | None
        ) = None,
        ontology_query_signal_transform: (
            Callable[[str, frozenset[str]], Iterable[str]] | None
        ) = None,
        limit: int = 10,
        source_item_budget: int | None = None,
        observation_budget: int | None = None,
        requested_source_item_count: int | None = None,
        enable_ontology_rerank: bool = False,
        access_binding: CandidateEvidenceAccessBinding | None = None,
        eligible_observation_ids: Iterable[str] | None = None,
        ontology_revision_id: str | None = None,
        ontology_signal_vocabulary_hash: str | None = None,
        ontology_contract_hash: str | None = None,
        eligible_context_ids: Iterable[str] | None = None,
        accessible_context_ids: Iterable[str] | None = None,
        query_context_ids: Iterable[str] | None = None,
        allow_cross_context_comparison: bool = False,
        known_as_of: str | None = None,
        as_of_world_time: str | None = None,
        allowed_epistemic_statuses: Iterable[str] | None = None,
        allowed_lifecycle_statuses: Iterable[str] | None = None,
        query_timezone: str | None = None,
    ) -> CandidateRetrievalResult:
        if _is_blank_text(ablation_id):
            raise ValueError("ablation_id is required")
        if not callable(query_token_transform):
            raise ValueError("query_token_transform is required")
        if eligible_observation_filter is not None and not callable(eligible_observation_filter):
            raise ValueError("eligible_observation_filter must be callable")
        if ontology_query_signal_transform is not None and not callable(
            ontology_query_signal_transform
        ):
            raise ValueError("ontology_query_signal_transform must be callable")
        return self._retrieve(
            query_text=query_text,
            limit=limit,
            source_item_budget=source_item_budget,
            observation_budget=observation_budget,
            requested_source_item_count=requested_source_item_count,
            enable_ontology_rerank=enable_ontology_rerank,
            access_binding=access_binding,
            eligible_observation_ids=eligible_observation_ids,
            ontology_revision_id=ontology_revision_id,
            ontology_signal_vocabulary_hash=ontology_signal_vocabulary_hash,
            ontology_contract_hash=ontology_contract_hash,
            eligible_context_ids=eligible_context_ids,
            accessible_context_ids=accessible_context_ids,
            query_context_ids=query_context_ids,
            allow_cross_context_comparison=allow_cross_context_comparison,
            known_as_of=known_as_of,
            as_of_world_time=as_of_world_time,
            allowed_epistemic_statuses=allowed_epistemic_statuses,
            allowed_lifecycle_statuses=allowed_lifecycle_statuses,
            query_timezone=query_timezone,
            ablation_id=ablation_id.strip(),
            query_token_transform=query_token_transform,
            eligible_observation_filter=eligible_observation_filter,
            ontology_query_signal_transform=ontology_query_signal_transform,
        )

    def _retrieve(
        self,
        *,
        query_text: str,
        limit: int,
        source_item_budget: int | None,
        observation_budget: int | None,
        requested_source_item_count: int | None,
        enable_ontology_rerank: bool,
        access_binding: CandidateEvidenceAccessBinding | None,
        eligible_observation_ids: Iterable[str] | None,
        ontology_revision_id: str | None,
        ontology_signal_vocabulary_hash: str | None,
        ontology_contract_hash: str | None,
        eligible_context_ids: Iterable[str] | None,
        accessible_context_ids: Iterable[str] | None,
        query_context_ids: Iterable[str] | None,
        allow_cross_context_comparison: bool,
        known_as_of: str | None,
        as_of_world_time: str | None,
        allowed_epistemic_statuses: Iterable[str] | None,
        allowed_lifecycle_statuses: Iterable[str] | None,
        query_timezone: str | None,
        ablation_id: str | None,
        query_token_transform: (Callable[[frozenset[str]], Iterable[str]] | None),
        eligible_observation_filter: (Callable[[set[str], frozenset[str]], Iterable[str]] | None),
        ontology_query_signal_transform: (Callable[[str, frozenset[str]], Iterable[str]] | None),
    ) -> CandidateRetrievalResult:
        if access_binding is not None:
            try:
                _require_candidate_evidence_access_binding(access_binding)
            except ValueError:
                return CandidateRetrievalResult(
                    plan=CandidateQueryPlan(intent="access_boundary", anchor_tokens=()),
                    selected_observation_ids=(),
                    rejected=True,
                    rejection_reason="invalid_access_binding",
                )
        access_bindings = tuple(
            binding for binding in (self._access_binding, access_binding) if binding is not None
        )
        if not access_bindings:
            return CandidateRetrievalResult(
                plan=CandidateQueryPlan(intent="access_boundary", anchor_tokens=()),
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="access_binding_required",
            )
        if type(allow_cross_context_comparison) is not bool:
            return CandidateRetrievalResult(
                plan=CandidateQueryPlan(intent="context_boundary", anchor_tokens=()),
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="invalid_cross_context_comparison_authorization",
            )
        permission_eligible_ids = set(self._by_id)
        for effective_access_binding in access_bindings:
            permission_eligible_ids &= {
                observation_id
                for observation_id in effective_access_binding.eligible_observation_ids
                if observation_id in self._by_id
                and self._by_id[observation_id].source_identity_policy_id
                in effective_access_binding.eligible_source_identity_policy_ids
                and self._by_id[observation_id].permission_scope_id
                in effective_access_binding.eligible_permission_scope_ids
                and self._by_id[observation_id].source_version_id
                in effective_access_binding.eligible_source_version_ids
            }
        if not permission_eligible_ids:
            return CandidateRetrievalResult(
                plan=CandidateQueryPlan(intent="access_boundary", anchor_tokens=()),
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="no_accessible_evidence",
            )
        effective_source_item_budget = limit if source_item_budget is None else source_item_budget
        effective_observation_budget = limit if observation_budget is None else observation_budget
        if effective_source_item_budget <= 0 or effective_observation_budget <= 0:
            return CandidateRetrievalResult(
                plan=CandidateQueryPlan(intent="general", anchor_tokens=()),
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="evidence_budget_exhausted",
            )
        if requested_source_item_count is not None and (
            type(requested_source_item_count) is not int or requested_source_item_count <= 0
        ):
            return CandidateRetrievalResult(
                plan=CandidateQueryPlan(intent="general", anchor_tokens=()),
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="invalid_evidence_cardinality",
            )
        normalized_accessible_context_ids = _normalized_context_filter(accessible_context_ids)
        normalized_query_context_ids = _normalized_context_filter(
            query_context_ids if query_context_ids is not None else eligible_context_ids
        )
        if (
            normalized_accessible_context_ids is not None
            and len(normalized_accessible_context_ids) > 1
            and normalized_query_context_ids is None
        ):
            return CandidateRetrievalResult(
                plan=CandidateQueryPlan(intent="context_boundary", anchor_tokens=()),
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="query_context_required",
            )
        if (
            normalized_accessible_context_ids is not None
            and normalized_query_context_ids is not None
            and not normalized_query_context_ids <= normalized_accessible_context_ids
        ):
            return CandidateRetrievalResult(
                plan=CandidateQueryPlan(intent="context_boundary", anchor_tokens=()),
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="query_context_not_accessible",
            )
        if (
            normalized_query_context_ids is not None
            and len(normalized_query_context_ids) > 1
            and not allow_cross_context_comparison
        ):
            return CandidateRetrievalResult(
                plan=CandidateQueryPlan(intent="context_boundary", anchor_tokens=()),
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="cross_context_comparison_not_allowed",
            )
        if eligible_observation_ids is not None:
            permission_eligible_ids &= {
                value for value in eligible_observation_ids if value in self._by_id
            }
        eligible_ids = self._admissible_ids(
            permission_eligible_ids,
            accessible_context_ids=normalized_accessible_context_ids,
            query_context_ids=normalized_query_context_ids,
            known_as_of=known_as_of,
            as_of_world_time=as_of_world_time,
            allowed_epistemic_statuses=allowed_epistemic_statuses,
            allowed_lifecycle_statuses=allowed_lifecycle_statuses,
        )
        if not eligible_ids:
            return CandidateRetrievalResult(
                plan=CandidateQueryPlan(intent="admissibility_boundary", anchor_tokens=()),
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="no_admissible_evidence",
            )
        binding_error = self._binding_error(
            enable_ontology_rerank=enable_ontology_rerank,
            ontology_signal_resolver_available=(
                ontology_query_signal_transform is not None
                or self._ontology_query_signal_resolver is not None
            ),
            ontology_revision_id=ontology_revision_id,
            ontology_signal_vocabulary_hash=ontology_signal_vocabulary_hash,
            ontology_contract_hash=ontology_contract_hash,
        )
        if binding_error is not None:
            return CandidateRetrievalResult(
                plan=CandidateQueryPlan(intent="binding_mismatch", anchor_tokens=()),
                selected_observation_ids=(),
                rejected=True,
                rejection_reason=binding_error,
            )
        base_query_tokens = self._text_policy_runtime.tokenize(query_text)
        normalized_query_tokens = set(base_query_tokens)
        if query_token_transform is not None:
            transformed_tokens = frozenset(
                token.strip().lower()
                for token in query_token_transform(base_query_tokens)
                if isinstance(token, str) and token.strip()
            )
            if not base_query_tokens <= transformed_tokens:
                return CandidateRetrievalResult(
                    plan=CandidateQueryPlan(intent="ablation_boundary", anchor_tokens=()),
                    selected_observation_ids=(),
                    rejected=True,
                    rejection_reason="ablation_tokens_must_extend_default",
                )
            normalized_query_tokens = set(transformed_tokens)
        if eligible_observation_filter is not None:
            eligible_ids &= {
                observation_id
                for observation_id in eligible_observation_filter(
                    set(eligible_ids),
                    frozenset(normalized_query_tokens),
                )
                if observation_id in self._by_id
            }
            if not eligible_ids:
                return CandidateRetrievalResult(
                    plan=CandidateQueryPlan(intent="ablation_boundary", anchor_tokens=()),
                    selected_observation_ids=(),
                    rejected=True,
                    rejection_reason="no_admissible_evidence",
                )
        normalized_ontology_signals: set[str] = set()
        if enable_ontology_rerank:
            ontology_signal_resolver = (
                ontology_query_signal_transform or self._ontology_query_signal_resolver
            )
            assert ontology_signal_resolver is not None
            normalized_ontology_signals = {
                signal.strip().lower()
                for signal in ontology_signal_resolver(
                    query_text,
                    frozenset(normalized_query_tokens),
                )
                if isinstance(signal, str) and signal.strip()
            }
        plan = self._plan(
            query_text,
            normalized_query_tokens,
            eligible_ids=eligible_ids,
            limit=effective_source_item_budget,
            query_timezone=query_timezone,
            requested_source_item_count=requested_source_item_count,
        )
        if plan.minimum_source_items > effective_source_item_budget:
            return CandidateRetrievalResult(
                plan=plan,
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="evidence_budget_exhausted",
            )
        planned = self._retrieve_planned(
            plan,
            ontology_query_signals=normalized_ontology_signals,
            eligible_ids=eligible_ids,
            limit=effective_observation_budget,
        )
        if planned:
            return CandidateRetrievalResult(
                plan=plan,
                selected_observation_ids=planned,
                rejected=False,
            )
        if plan.intent != "general":
            return CandidateRetrievalResult(
                plan=plan,
                selected_observation_ids=(),
                rejected=True,
                rejection_reason="insufficient_supported_evidence",
            )
        fallback = self._rank_direct(
            normalized_query_tokens,
            ontology_query_signals=normalized_ontology_signals,
            eligible_ids=eligible_ids,
            source_item_limit=effective_source_item_budget,
            observation_limit=effective_observation_budget,
        )
        return CandidateRetrievalResult(
            plan=plan,
            selected_observation_ids=fallback,
            rejected=not fallback,
            rejection_reason=None if fallback else "no_supported_evidence",
        )

    def _admissible_ids(
        self,
        permission_eligible_ids: set[str],
        *,
        accessible_context_ids: set[str] | None,
        query_context_ids: set[str] | None,
        known_as_of: str | None,
        as_of_world_time: str | None,
        allowed_epistemic_statuses: Iterable[str] | None,
        allowed_lifecycle_statuses: Iterable[str] | None,
    ) -> set[str]:
        known_boundary = _parse_timestamp(known_as_of) if known_as_of is not None else None
        world_boundary = (
            _parse_timestamp(as_of_world_time) if as_of_world_time is not None else None
        )
        epistemic_statuses = _normalized_optional_filter(allowed_epistemic_statuses)
        lifecycle_statuses = _normalized_optional_filter(allowed_lifecycle_statuses)
        admissible: set[str] = set()
        for observation_id in permission_eligible_ids:
            record = self._by_id[observation_id]
            if accessible_context_ids is not None and not (
                record.context_ids & accessible_context_ids
            ):
                continue
            if query_context_ids is not None and not (record.context_ids & query_context_ids):
                continue
            if known_boundary is not None:
                if record.known_at is None or _parse_timestamp(record.known_at) > known_boundary:
                    continue
            if world_boundary is not None:
                if (
                    record.valid_from is not None
                    and _parse_timestamp(record.valid_from) > world_boundary
                ):
                    continue
                if (
                    record.valid_to is not None
                    and _parse_timestamp(record.valid_to) < world_boundary
                ):
                    continue
            if (
                epistemic_statuses is not None
                and _normalized_status(record.epistemic_status) not in epistemic_statuses
            ):
                continue
            if (
                lifecycle_statuses is not None
                and _normalized_status(record.lifecycle_status) not in lifecycle_statuses
            ):
                continue
            admissible.add(observation_id)
        return admissible

    def _binding_error(
        self,
        *,
        enable_ontology_rerank: bool,
        ontology_signal_resolver_available: bool,
        ontology_revision_id: str | None,
        ontology_signal_vocabulary_hash: str | None,
        ontology_contract_hash: str | None,
    ) -> str | None:
        if not enable_ontology_rerank:
            return None
        if not ontology_signal_resolver_available:
            return "ontology_query_signal_resolver_required"
        if (
            self._ontology_revision_id is None
            or self._ontology_signal_vocabulary_hash is None
            or self._ontology_contract_hash is None
        ):
            return "ontology_binding_required"
        if ontology_revision_id != self._ontology_revision_id:
            return "ontology_revision_mismatch"
        if ontology_signal_vocabulary_hash != self._ontology_signal_vocabulary_hash:
            return "ontology_signal_vocabulary_mismatch"
        if ontology_contract_hash != self._ontology_contract_hash:
            return "ontology_contract_mismatch"
        return None

    def _plan(
        self,
        query_text: str,
        query_tokens: set[str],
        *,
        eligible_ids: set[str],
        limit: int,
        query_timezone: str | None,
        requested_source_item_count: int | None,
    ) -> CandidateQueryPlan:
        term_sequence = _normalized_query_term_sequence(query_text)
        raw_terms = set(term_sequence)
        intent = _query_intent(raw_terms, query_text=query_text)
        chronology_mode, chronology_boundary = _chronology_request(
            query_text,
            terms=raw_terms,
        )
        explicit_source_item_count = (
            requested_source_item_count
            if requested_source_item_count is not None
            else _explicit_requested_source_item_count(query_text)
        )
        explicit_multi = (
            (explicit_source_item_count is not None and explicit_source_item_count > 1)
            or bool(raw_terms & _MULTI_RECORD_TERMS)
            or any(
                phrase in query_text
                for phrase in ("多筆", "多份", "多個紀錄", "多個記錄", "不同紀錄", "不同記錄")
            )
        )
        if intent == "general" and explicit_multi:
            intent = "multi_record"
        requested_source_items = _requested_source_item_count(
            term_sequence,
            query_text=query_text,
            default=(
                2
                if explicit_multi
                or intent in {"conflict", "multi_record"}
                or (intent == "chronology" and chronology_mode == "range")
                else 1
            ),
            maximum=limit,
            explicit_count=explicit_source_item_count,
        )
        minimum_source_items = (
            requested_source_items
            if explicit_multi or intent in {"chronology", "conflict", "multi_record"}
            else 1
        )
        target_source_items = requested_source_items
        actor_tokens = (
            self._query_actor_tokens(
                query_tokens,
                preferred_tokens=_explicit_actor_tokens(term_sequence),
                eligible_ids=eligible_ids,
            )
            if intent == "actor_topic"
            else ()
        )
        syntactic_focus_tokens = _syntactic_focus_tokens(term_sequence, intent=intent)
        content_tokens = (
            query_tokens
            - _QUERY_CONTROL_TERMS
            - _SOURCE_DESCRIPTOR_TERMS
            - _ACTOR_TERMS
            - _CHRONOLOGY_TERMS
            - _MULTI_RECORD_TERMS
            - set(actor_tokens)
        )
        content_tokens = {
            token
            for token in content_tokens
            if self._eligible_source_item_count(token, eligible_ids=eligible_ids) > 0
        }
        preferred_tokens = tuple(
            dict.fromkeys(
                (
                    *(
                        token
                        for token in reversed(syntactic_focus_tokens)
                        if token in content_tokens
                    ),
                    *(token for token in reversed(term_sequence) if token in content_tokens),
                )
            )
        )

        if intent == "actor_topic":
            anchors = self._supported_token_set_with_fallback(
                content_tokens,
                preferred_tokens=preferred_tokens,
                actor_tokens=set(actor_tokens),
                eligible_ids=eligible_ids,
                maximum_size=1,
                preferred_source_items=target_source_items,
                minimum_source_items=minimum_source_items,
            )
        elif intent == "conflict":
            anchors = self._supported_token_set_with_fallback(
                content_tokens,
                preferred_tokens=preferred_tokens,
                actor_tokens=set(),
                eligible_ids=eligible_ids,
                maximum_size=2,
                preferred_source_items=target_source_items,
                minimum_source_items=minimum_source_items,
            )
            if len(content_tokens) >= 2 and len(anchors) < 2:
                anchors = ()
        elif intent == "approval_decision":
            semantic_terms = query_tokens & _APPROVAL_TERMS
            topic_tokens = content_tokens - _APPROVAL_TERMS - _CONFLICT_TERMS
            anchors = self._supported_token_set_with_fallback(
                topic_tokens,
                preferred_tokens=preferred_tokens,
                actor_tokens=set(),
                eligible_ids=eligible_ids,
                maximum_size=1,
                preferred_source_items=target_source_items,
                minimum_source_items=minimum_source_items,
                required_tokens=semantic_terms,
            )
        elif intent in {"chronology", "multi_record"}:
            maximum_size = (
                min(2, len(syntactic_focus_tokens))
                if intent == "multi_record" and syntactic_focus_tokens
                else 1
            )
            anchors = self._supported_token_set_with_fallback(
                content_tokens,
                preferred_tokens=preferred_tokens,
                actor_tokens=set(),
                eligible_ids=eligible_ids,
                maximum_size=maximum_size,
                preferred_source_items=target_source_items,
                minimum_source_items=minimum_source_items,
            )
        else:
            anchors = ()
        return CandidateQueryPlan(
            intent=intent,
            anchor_tokens=anchors,
            actor_tokens=actor_tokens,
            minimum_source_items=minimum_source_items,
            target_source_items=target_source_items,
            chronology_mode=chronology_mode if intent == "chronology" else None,
            chronology_boundary=chronology_boundary if intent == "chronology" else None,
            chronology_timezone=query_timezone if intent == "chronology" else None,
        )

    def _query_actor_tokens(
        self,
        query_tokens: set[str],
        *,
        preferred_tokens: Sequence[str],
        eligible_ids: set[str],
    ) -> tuple[str, ...]:
        for token in preferred_tokens:
            if token not in query_tokens:
                continue
            source_item_ids = {
                _logical_source_key(self._by_id[observation_id])
                for observation_id in self._record_ids_by_actor_token.get(token, ())
                if observation_id in eligible_ids
            }
            if source_item_ids:
                return (token,)
        candidates: list[tuple[int, str]] = []
        for token in query_tokens:
            source_item_ids = {
                _logical_source_key(self._by_id[observation_id])
                for observation_id in self._record_ids_by_actor_token.get(token, ())
                if observation_id in eligible_ids
            }
            eligible_count = len(source_item_ids)
            if eligible_count >= 1:
                candidates.append((eligible_count, token))
        if not candidates:
            return ()
        return (min(candidates)[1],)

    def _supported_token_set_with_fallback(
        self,
        tokens: set[str],
        *,
        preferred_tokens: Sequence[str],
        actor_tokens: set[str],
        eligible_ids: set[str],
        maximum_size: int,
        preferred_source_items: int,
        minimum_source_items: int,
        required_tokens: set[str] | None = None,
    ) -> tuple[str, ...]:
        anchors = self._preferred_supported_token_set(
            preferred_tokens,
            actor_tokens=actor_tokens,
            eligible_ids=eligible_ids,
            maximum_size=maximum_size,
            minimum_source_items=preferred_source_items,
            required_tokens=required_tokens,
        )
        if anchors:
            return anchors
        anchors = self._smallest_supported_token_set(
            tokens,
            actor_tokens=actor_tokens,
            eligible_ids=eligible_ids,
            maximum_size=maximum_size,
            minimum_source_items=preferred_source_items,
            required_tokens=required_tokens,
        )
        if anchors or minimum_source_items >= preferred_source_items:
            return anchors
        return self._smallest_supported_token_set(
            tokens,
            actor_tokens=actor_tokens,
            eligible_ids=eligible_ids,
            maximum_size=maximum_size,
            minimum_source_items=minimum_source_items,
            required_tokens=required_tokens,
        )

    def _preferred_supported_token_set(
        self,
        preferred_tokens: Sequence[str],
        *,
        actor_tokens: set[str],
        eligible_ids: set[str],
        maximum_size: int,
        minimum_source_items: int,
        required_tokens: set[str] | None,
    ) -> tuple[str, ...]:
        required = tuple(sorted(required_tokens or set()))
        unique_tokens = tuple(dict.fromkeys(preferred_tokens))
        maximum_size = min(maximum_size, len(unique_tokens))
        for size in range(maximum_size, 0, -1):
            for start in range(0, len(unique_tokens) - size + 1):
                token_set = tuple(sorted(unique_tokens[start : start + size]))
                if (
                    len(
                        self._matching_source_item_ids(
                            required + token_set,
                            actor_tokens=actor_tokens,
                            eligible_ids=eligible_ids,
                        )
                    )
                    >= minimum_source_items
                ):
                    return required + token_set
        return ()

    def _smallest_supported_token_set(
        self,
        tokens: set[str],
        *,
        actor_tokens: set[str],
        eligible_ids: set[str],
        maximum_size: int,
        minimum_source_items: int,
        prefer_larger_sets: bool = False,
        required_tokens: set[str] | None = None,
    ) -> tuple[str, ...]:
        if not tokens or maximum_size <= 0:
            return ()
        required = required_tokens or set()
        candidates = sorted(
            tokens,
            key=lambda token: (
                self._eligible_source_item_count(token, eligible_ids=eligible_ids),
                -self._idf(token, eligible_ids=eligible_ids),
                token,
            ),
        )[:12]
        sizes = range(1, min(maximum_size, len(candidates)) + 1)
        if prefer_larger_sets:
            sizes = reversed(tuple(sizes))
        best: tuple[int, float, tuple[str, ...]] | None = None
        for size in sizes:
            for token_set in _combinations(candidates, size):
                source_item_ids = self._matching_source_item_ids(
                    tuple(sorted(required)) + token_set,
                    actor_tokens=actor_tokens,
                    eligible_ids=eligible_ids,
                )
                support = len(source_item_ids)
                if support < minimum_source_items:
                    continue
                idf_sum = sum(self._idf(token, eligible_ids=eligible_ids) for token in token_set)
                candidate = (support, -idf_sum, tuple(sorted(required)) + token_set)
                if best is None or candidate < best:
                    best = candidate
            if best is not None and prefer_larger_sets:
                break
        return () if best is None else best[2]

    def _retrieve_planned(
        self,
        plan: CandidateQueryPlan,
        *,
        ontology_query_signals: set[str],
        eligible_ids: set[str],
        limit: int,
    ) -> tuple[str, ...]:
        if not plan.anchor_tokens:
            return ()
        source_item_ids = self._matching_source_item_ids(
            plan.anchor_tokens,
            actor_tokens=set(plan.actor_tokens),
            eligible_ids=eligible_ids,
        )
        if len(source_item_ids) < plan.minimum_source_items:
            return ()
        ordered = sorted(
            source_item_ids,
            key=lambda source_item_id: (
                -self._source_item_planned_score(
                    source_item_id,
                    anchor_tokens=set(plan.anchor_tokens),
                    actor_tokens=set(plan.actor_tokens),
                    ontology_query_signals=ontology_query_signals,
                    eligible_ids=eligible_ids,
                ),
                self._source_item_order_key(
                    source_item_id,
                    eligible_ids=eligible_ids,
                ),
            ),
        )
        if plan.intent == "chronology":
            chronological_source_ids = {
                source_item_id
                for source_item_id in source_item_ids
                if self._source_item_timestamp(
                    source_item_id,
                    eligible_ids=eligible_ids,
                )
                is not None
            }
            if len(chronological_source_ids) < plan.minimum_source_items:
                return ()
            chronological = sorted(
                chronological_source_ids,
                key=lambda source_item_id: self._source_item_order_key(
                    source_item_id,
                    eligible_ids=eligible_ids,
                ),
            )
            chronology_mode = plan.chronology_mode or "range"
            if chronology_mode in {"before", "after"}:
                if plan.chronology_boundary is None:
                    return ()
                chronological = [
                    source_item_id
                    for source_item_id in chronological
                    if _timestamp_satisfies_boundary(
                        self._source_item_timestamp(
                            source_item_id,
                            eligible_ids=eligible_ids,
                        ),
                        mode=chronology_mode,
                        boundary=plan.chronology_boundary,
                        query_timezone=plan.chronology_timezone,
                    )
                ]
                if len(chronological) < plan.minimum_source_items:
                    return ()
            if chronology_mode == "earliest":
                selected_source_items = tuple(chronological[: plan.target_source_items])
            elif chronology_mode in {"latest", "before"}:
                selected_source_items = tuple(reversed(chronological[-plan.target_source_items :]))
            elif chronology_mode == "after":
                selected_source_items = tuple(chronological[: plan.target_source_items])
            else:
                selected_source_items = _select_chronology_range(
                    chronological,
                    target_count=plan.target_source_items,
                )
        else:
            selected_source_items = tuple(ordered[: plan.target_source_items])
        selected: list[str] = []
        represented_source_items: set[str] = set()
        for source_item_id in selected_source_items:
            representatives = self._representative_observation_ids(
                source_item_id,
                anchor_tokens=set(plan.anchor_tokens),
                actor_tokens=set(plan.actor_tokens),
                ontology_query_signals=ontology_query_signals,
                eligible_ids=eligible_ids,
                remaining_limit=limit - len(selected),
            )
            if not representatives:
                continue
            selected.extend(representatives)
            represented_source_items.add(source_item_id)
            if len(selected) >= limit:
                break
        if len(represented_source_items) < plan.minimum_source_items:
            return ()
        return tuple(selected[:limit])

    def _representative_observation_ids(
        self,
        source_item_id: _LogicalSourceKey,
        *,
        anchor_tokens: set[str],
        actor_tokens: set[str],
        ontology_query_signals: set[str],
        eligible_ids: set[str],
        remaining_limit: int,
    ) -> tuple[str, ...]:
        if remaining_limit <= 0:
            return ()
        records = [
            record
            for record in self._by_source_item[source_item_id]
            if record.observation_id in eligible_ids
        ]
        if not records:
            return ()
        ranked_records = sorted(
            records,
            key=lambda record: (
                -(len(record.tokens & anchor_tokens) + len(record.actor_tokens & actor_tokens)),
                -len(record.ontology_signals & ontology_query_signals),
                record.observation_id,
            ),
        )
        selected: list[str] = []
        covered: set[str] = set()
        covered_actors: set[str] = set()
        for record in ranked_records:
            newly_covered = (record.tokens & anchor_tokens) - covered
            newly_covered_actors = (record.actor_tokens & actor_tokens) - covered_actors
            if not newly_covered and not newly_covered_actors:
                continue
            selected.append(record.observation_id)
            covered.update(newly_covered)
            covered_actors.update(newly_covered_actors)
            if (covered >= anchor_tokens and covered_actors >= actor_tokens) or len(
                selected
            ) >= remaining_limit:
                break
        if covered < anchor_tokens or covered_actors < actor_tokens:
            return ()
        return tuple(selected)

    def _rank_direct(
        self,
        query_tokens: set[str],
        *,
        ontology_query_signals: set[str],
        eligible_ids: set[str],
        source_item_limit: int,
        observation_limit: int,
    ) -> tuple[str, ...]:
        candidate_source_item_ids = {
            _logical_source_key(self._by_id[observation_id])
            for token in query_tokens
            for observation_id in self._record_ids_by_token.get(token, ())
            if observation_id in eligible_ids
        }
        ranked: list[tuple[float, float, _LogicalSourceKey]] = []
        for source_item_id in candidate_source_item_ids:
            source_tokens = {
                token
                for record in self._by_source_item[source_item_id]
                if record.observation_id in eligible_ids
                for token in record.tokens
            }
            overlap = source_tokens & query_tokens
            if not overlap:
                continue
            lexical_score = sum(self._idf(token, eligible_ids=eligible_ids) for token in overlap)
            ontology_overlap = {
                signal
                for record in self._by_source_item[source_item_id]
                if record.observation_id in eligible_ids
                for signal in record.ontology_signals
            } & ontology_query_signals
            ontology_bonus = min(lexical_score * 0.2, float(len(ontology_overlap)))
            coverage = len(overlap) / max(len(query_tokens), 1)
            ranked.append((-(lexical_score + ontology_bonus), -coverage, source_item_id))
        selected: list[str] = []
        represented_source_items = 0
        for *_score, source_item_id in sorted(ranked):
            anchor_tokens = {
                token
                for record in self._by_source_item[source_item_id]
                if record.observation_id in eligible_ids
                for token in record.tokens
                if token in query_tokens
            }
            representatives = self._representative_observation_ids(
                source_item_id,
                anchor_tokens=anchor_tokens,
                actor_tokens=set(),
                ontology_query_signals=ontology_query_signals,
                eligible_ids=eligible_ids,
                remaining_limit=observation_limit - len(selected),
            )
            if not representatives:
                continue
            selected.extend(representatives)
            represented_source_items += 1
            if represented_source_items >= source_item_limit or len(selected) >= observation_limit:
                break
        return tuple(selected[:observation_limit])

    def _source_item_planned_score(
        self,
        source_item_id: _LogicalSourceKey,
        *,
        anchor_tokens: set[str],
        actor_tokens: set[str],
        ontology_query_signals: set[str],
        eligible_ids: set[str],
    ) -> float:
        lexical_score = sum(
            self._idf(token, eligible_ids=eligible_ids) for token in anchor_tokens | actor_tokens
        )
        ontology_overlap = self._source_item_ontology_overlap(
            source_item_id,
            ontology_query_signals=ontology_query_signals,
            eligible_ids=eligible_ids,
        )
        ontology_bonus = min(lexical_score * 0.2, float(ontology_overlap))
        return lexical_score + ontology_bonus

    def _matching_source_item_ids(
        self,
        tokens: Sequence[str],
        *,
        actor_tokens: set[str],
        eligible_ids: set[str],
    ) -> set[_LogicalSourceKey]:
        token_sets = [
            {
                _logical_source_key(self._by_id[observation_id])
                for observation_id in self._record_ids_by_token.get(token, ())
                if observation_id in eligible_ids
            }
            for token in tokens
        ]
        if not token_sets:
            return set()
        source_item_ids = set.intersection(*token_sets)
        if actor_tokens:
            actor_sets = [
                {
                    _logical_source_key(self._by_id[observation_id])
                    for observation_id in self._record_ids_by_actor_token.get(token, ())
                    if observation_id in eligible_ids
                }
                for token in actor_tokens
            ]
            if not actor_sets:
                return set()
            source_item_ids &= set.intersection(*actor_sets)
        return source_item_ids

    def _eligible_source_item_count(self, token: str, *, eligible_ids: set[str]) -> int:
        return len(
            {
                _logical_source_key(self._by_id[observation_id])
                for observation_id in self._record_ids_by_token.get(token, ())
                if observation_id in eligible_ids
            }
        )

    def _idf(self, token: str, *, eligible_ids: set[str]) -> float:
        eligible_source_items = {
            _logical_source_key(self._by_id[observation_id]) for observation_id in eligible_ids
        }
        document_frequency = len(
            {
                _logical_source_key(self._by_id[observation_id])
                for observation_id in self._record_ids_by_token.get(token, ())
                if observation_id in eligible_ids
            }
        )
        if document_frequency <= 0:
            return 0.0
        return math.log1p(
            (len(eligible_source_items) - document_frequency + 0.5) / (document_frequency + 0.5)
        )

    def _source_item_ontology_overlap(
        self,
        source_item_id: _LogicalSourceKey,
        *,
        ontology_query_signals: set[str],
        eligible_ids: set[str],
    ) -> int:
        return max(
            (
                len(record.ontology_signals & ontology_query_signals)
                for record in self._by_source_item[source_item_id]
                if record.observation_id in eligible_ids
            ),
            default=0,
        )

    def _source_item_order_key(
        self,
        source_item_id: _LogicalSourceKey,
        *,
        eligible_ids: set[str],
    ) -> tuple[datetime, _LogicalSourceKey]:
        timestamp = self._source_item_timestamp(
            source_item_id,
            eligible_ids=eligible_ids,
        )
        return (
            timestamp or datetime.max.replace(tzinfo=timezone.utc),
            source_item_id,
        )

    def _source_item_timestamp(
        self,
        source_item_id: _LogicalSourceKey,
        *,
        eligible_ids: set[str],
    ) -> datetime | None:
        timestamps = [
            _parse_timestamp(record.observed_at)
            for record in self._by_source_item[source_item_id]
            if record.observation_id in eligible_ids and record.observed_at is not None
        ]
        return min(timestamps) if timestamps else None


def _normalized_query_terms(value: str) -> set[str]:
    return set(_normalized_query_term_sequence(value))


def _normalized_query_term_sequence(value: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in _QUERY_TERM_RE.finditer(value):
        normalized = _normalized_term(match.group(0))
        if normalized:
            terms.append(normalized)
        terms.extend(
            part for part in re.split(r"[-_.]+", normalized) if part and part != normalized
        )
    return tuple(terms)


def _normalized_term(value: str) -> str:
    return value.strip().strip("._-").lower()


def _normalized_descriptor(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or None


def _descriptor_matches(value: str | None, terms: set[str]) -> bool:
    if value is None:
        return False
    bounded = f"_{value}_"
    return any(f"_{term}_" in bounded for term in terms)


def _explicit_actor_tokens(terms: Sequence[str]) -> tuple[str, ...]:
    for index, term in enumerate(terms[:-1]):
        if term == "did":
            candidate = terms[index + 1]
            if candidate and candidate not in _ACTOR_TERMS:
                return (candidate,)
    for index, term in enumerate(terms):
        if term in _ACTOR_TERMS and index > 0:
            candidate = terms[index - 1]
            if candidate not in {"what", "which", "who"}:
                return (candidate,)
    return ()


def _syntactic_focus_tokens(
    terms: Sequence[str],
    *,
    intent: str,
) -> tuple[str, ...]:
    cue_terms = {
        "actor_topic": ("about", "regarding", "concerning"),
        "chronology": ("mention", "mentions", "about", "regarding"),
        "conflict": ("between", "involving", "about", "regarding"),
        "multi_record": ("about", "regarding", "concerning"),
        "approval_decision": ("about", "regarding", "concerning"),
    }.get(intent, ())
    cue_index = -1
    for index, term in enumerate(terms):
        if term in cue_terms:
            cue_index = index
    if cue_index >= 0:
        focus_terms = terms[cue_index + 1 :]
    elif intent == "multi_record":
        boundary_index = next(
            (index for index, term in enumerate(terms) if term in {"across", "from", "in", "跨"}),
            -1,
        )
        if boundary_index <= 0:
            return ()
        focus_terms = terms[:boundary_index]
    else:
        return ()
    excluded_terms = {
        "across",
        "all",
        "and",
        "compare",
        "different",
        "email",
        "emails",
        "evidence",
        "find",
        "from",
        "in",
        "multiple",
        "record",
        "records",
        "separate",
        "several",
        "show",
        "source",
        "sources",
        "summarize",
        "the",
        "with",
        "比較",
        "彙整",
        "找出",
        "摘要",
    }
    return tuple(
        term
        for term in focus_terms
        if term not in excluded_terms
        and term not in _SOURCE_DESCRIPTOR_TERMS
        and not term.isdigit()
    )


def _requested_source_item_count(
    terms: Sequence[str],
    *,
    query_text: str,
    default: int,
    maximum: int,
    explicit_count: int | None = None,
) -> int:
    count = (
        explicit_count
        if explicit_count is not None
        else _explicit_requested_source_item_count(query_text)
    )
    if count is not None:
        return max(1, count)
    if "all" in terms:
        return maximum
    return max(1, min(default, maximum))


def _explicit_requested_source_item_count(query_text: str) -> int | None:
    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    count_nouns = _SOURCE_DESCRIPTOR_TERMS | {
        "entry",
        "entries",
        "event",
        "events",
        "inspection",
        "inspections",
        "item",
        "items",
        "lot",
        "lots",
        "report",
        "reports",
        "result",
        "results",
        "source",
        "sources",
    }
    non_source_count_nouns = {
        "day",
        "days",
        "dollar",
        "dollars",
        "hour",
        "hours",
        "minute",
        "minutes",
        "month",
        "months",
        "percent",
        "percentage",
        "quarter",
        "quarters",
        "second",
        "seconds",
        "week",
        "weeks",
        "year",
        "years",
    }
    identifier_markers = {
        "code",
        "id",
        "identifier",
        "no",
        "number",
        "ref",
        "reference",
        "serial",
    }
    identifier_bearing_terms = {
        "account",
        "asset",
        "batch",
        "case",
        "claim",
        "contract",
        "document",
        "event",
        "invoice",
        "item",
        "job",
        "lot",
        "order",
        "po",
        "project",
        "request",
        "row",
        "shipment",
        "task",
        "ticket",
        "transaction",
        "version",
    }
    chinese_identifier_suffixes = (
        "交易",
        "任務",
        "合約",
        "批次",
        "批號",
        "案件",
        "發票",
        "票號",
        "編號",
        "訂單",
        "資產",
        "項目",
    )
    count_bridge_breakers = {
        "about",
        "across",
        "between",
        "for",
        "from",
        "in",
        "of",
        "within",
        "with",
    }
    count_tokens = tuple(re.finditer(r"[A-Za-z]+|\d+", query_text))
    for index, match in enumerate(count_tokens):
        term = match.group(0).lower()
        if term.isdigit() and (
            (
                match.start() > 0
                and (
                    query_text[match.start() - 1].isascii()
                    and query_text[match.start() - 1].isalnum()
                    or query_text[match.start() - 1] in "#-_./"
                )
            )
            or (
                match.end() < len(query_text)
                and (
                    query_text[match.end()].isascii()
                    and query_text[match.end()].isalnum()
                    or query_text[match.end()] in "#-_./"
                )
            )
        ):
            continue
        count = int(term) if term.isdigit() else number_words.get(term)
        if count is None:
            continue
        preceding = [
            count_tokens[position].group(0).lower() for position in range(max(0, index - 2), index)
        ]
        if term.isdigit():
            if any(
                token in identifier_markers or token in identifier_bearing_terms
                for token in preceding
            ):
                continue
            prefix = query_text[: match.start()].rstrip()
            if prefix.endswith(chinese_identifier_suffixes):
                continue
        following = [
            count_tokens[position].group(0).lower()
            for position in range(index + 1, min(index + 4, len(count_tokens)))
        ]
        if any(token in non_source_count_nouns for token in following):
            continue
        source_noun_index = next(
            (
                position
                for position, token in enumerate(following)
                if token in count_nouns
                or (
                    len(token) > 3
                    and token.endswith("s")
                    and token not in non_source_count_nouns
                    and token
                    not in {
                        "across",
                        "always",
                        "does",
                        "has",
                        "is",
                        "this",
                        "was",
                    }
                )
            ),
            None,
        )
        if source_noun_index is not None and not (
            term.isdigit()
            and any(token in count_bridge_breakers for token in following[:source_noun_index])
        ):
            return max(1, count)
    chinese_count = _explicit_chinese_source_count(query_text)
    if chinese_count is not None:
        return max(1, chinese_count)
    return None


def _explicit_chinese_source_count(query_text: str) -> int | None:
    classifier_pattern = r"(?P<classifier>份|筆|個|張|頁|封|則|項|件|批|組|套)"
    match = re.search(
        rf"(?<![A-Za-z0-9_.-])(?P<count>\d{{1,3}}|[一二兩三四五六七八九十]{{1,3}})"
        rf"{classifier_pattern}",
        query_text,
    )
    if match is None:
        return None
    if match.group("classifier") == "個":
        following = query_text[match.end() :].lstrip()
        source_nouns = {
            "事件",
            "來源",
            "信件",
            "問題",
            "圖片",
            "報告",
            "批次",
            "投影片",
            "文件",
            "日報",
            "月報",
            "案件",
            "檔案",
            "檢查",
            "檢驗",
            "照片",
            "異常",
            "紀錄",
            "結論",
            "結果",
            "表格",
            "訊息",
            "記錄",
            "資料列",
            "週報",
            "季報",
            "郵件",
            "頁面",
            "年報",
        }
        source_period_nouns = {"日報", "月報", "週報", "季報", "年報"}
        duration_prefixes = {
            "分鐘",
            "天",
            "季度",
            "季",
            "小時",
            "工作天",
            "年",
            "日",
            "月",
            "秒",
            "週",
            "周",
        }
        if not any(following.startswith(noun) for noun in source_period_nouns):
            if any(following.startswith(prefix) for prefix in duration_prefixes):
                return None
        if not any(noun in following[:12] for noun in source_nouns):
            return None
    raw_count = match.group("count")
    if raw_count.isdigit():
        return int(raw_count)
    return _chinese_integer(raw_count)


def _chinese_integer(value: str) -> int | None:
    digits = {
        "一": 1,
        "二": 2,
        "兩": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value in digits:
        return digits[value]
    if value == "十":
        return 10
    if "十" not in value:
        return None
    left, right = value.split("十", 1)
    tens = digits.get(left, 1) if left else 1
    ones = digits.get(right, 0) if right else 0
    return tens * 10 + ones


def _chronology_request(
    query_text: str,
    *,
    terms: set[str],
) -> tuple[str | None, str | None]:
    normalized_text = query_text.strip().lower()
    boundary = _query_time_boundary(normalized_text)
    if any(term in normalized_text for term in ("before", "之前", "以前")):
        return "before", boundary
    if any(term in normalized_text for term in ("after", "之後", "以後")):
        return "after", boundary
    earliest = "earliest" in terms or any(term in normalized_text for term in ("earliest", "最早"))
    latest = "latest" in terms or any(
        term in normalized_text for term in ("latest", "最晚", "最新")
    )
    if earliest and latest:
        return "range", None
    if earliest:
        return "earliest", None
    if latest:
        return "latest", None
    if any(
        term in normalized_text
        for term in ("chronology", "timeline", "先後", "時間順序", "時序", "歷程")
    ):
        return "range", None
    return None, None


def _query_time_boundary(value: str) -> str | None:
    timestamp_match = re.search(
        r"\b\d{4}-\d{2}-\d{2}t\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:z|[+-]\d{2}:\d{2})\b",
        value,
        flags=re.IGNORECASE,
    )
    if timestamp_match:
        boundary = timestamp_match.group(0)
        _parse_timestamp(boundary)
        return boundary
    date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", value)
    if date_match:
        date.fromisoformat(date_match.group(0))
        return date_match.group(0)
    return None


def _query_intent(terms: set[str], *, query_text: str) -> str:
    normalized_text = query_text.strip().lower()
    if any(
        phrase in normalized_text
        for phrase in ("最早", "最晚", "最新", "先後", "時間順序", "時序", "歷程")
    ):
        return "chronology"
    if any(
        phrase in normalized_text for phrase in ("最終決定", "最後決定", "核准", "批准", "已決定")
    ):
        return "approval_decision"
    if any(phrase in normalized_text for phrase in ("衝突", "矛盾", "不一致", "互相抵觸")):
        return "conflict"
    if any(
        phrase in normalized_text
        for phrase in ("說了", "表示", "提到", "回報", "詢問", "要求", "指出")
    ) and any(phrase in normalized_text for phrase in ("誰", "什麼", "甚麼", "哪些", "如何")):
        return "actor_topic"
    if any(
        phrase in normalized_text
        for phrase in ("多筆", "多份", "多個紀錄", "多個記錄", "不同紀錄", "不同記錄")
    ):
        return "multi_record"
    if {"earliest", "latest"} <= terms or terms & _CHRONOLOGY_TERMS:
        return "chronology"
    if {"approved", "decision"} <= terms or {"final", "decision"} <= terms:
        return "approval_decision"
    if terms & _CONFLICT_TERMS:
        return "conflict"
    if terms & _ACTOR_TERMS and terms & {"what", "who", "which"}:
        return "actor_topic"
    if terms & _MULTI_RECORD_TERMS:
        return "multi_record"
    return "general"


def _logical_source_key(record: CandidateEvidenceRecord) -> _LogicalSourceKey:
    return (record.source_identity_policy_id, record.source_item_id)


def _group_records_by_source_key(
    records: Sequence[CandidateEvidenceRecord],
) -> dict[_LogicalSourceKey, list[CandidateEvidenceRecord]]:
    grouped: dict[_LogicalSourceKey, list[CandidateEvidenceRecord]] = defaultdict(list)
    for record in records:
        grouped[_logical_source_key(record)].append(record)
    return grouped


def _record_ids_by_token(
    records: Sequence[CandidateEvidenceRecord],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for record in records:
        for token in record.tokens:
            grouped[token].append(record.observation_id)
    return {token: tuple(sorted(record_ids)) for token, record_ids in grouped.items()}


def _record_ids_by_actor_token(
    records: Sequence[CandidateEvidenceRecord],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for record in records:
        for token in record.actor_tokens:
            grouped[token].append(record.observation_id)
    return {token: tuple(sorted(record_ids)) for token, record_ids in grouped.items()}


def _combinations(items: Sequence[str], size: int) -> Iterable[tuple[str, ...]]:
    if size == 0:
        yield ()
        return
    if size > len(items):
        return
    for index, item in enumerate(items):
        for suffix in _combinations(items[index + 1 :], size - 1):
            yield (item, *suffix)


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include an explicit UTC offset")
    return parsed


def _timestamp_satisfies_boundary(
    timestamp: datetime | None,
    *,
    mode: str,
    boundary: str,
    query_timezone: str | None,
) -> bool:
    if timestamp is None:
        return False
    if "T" in boundary.upper():
        boundary_timestamp = _parse_timestamp(boundary)
        return (
            timestamp < boundary_timestamp if mode == "before" else timestamp > boundary_timestamp
        )
    if query_timezone is None:
        return False
    boundary_date = date.fromisoformat(boundary)
    try:
        timezone_info = ZoneInfo(query_timezone)
    except ZoneInfoNotFoundError:
        return False
    boundary_start = datetime.combine(
        boundary_date,
        datetime.min.time(),
        tzinfo=timezone_info,
    )
    if mode == "before":
        return timestamp < boundary_start
    return timestamp >= boundary_start + timedelta(days=1)


def _select_chronology_range(
    source_item_ids: Sequence[_LogicalSourceKey],
    *,
    target_count: int,
) -> tuple[_LogicalSourceKey, ...]:
    if not source_item_ids or target_count <= 0:
        return ()
    count = min(target_count, len(source_item_ids))
    if count == 1:
        return (source_item_ids[0],)
    last_index = len(source_item_ids) - 1
    selected_indexes = tuple(
        round(position * last_index / (count - 1)) for position in range(count)
    )
    return tuple(source_item_ids[index] for index in selected_indexes)


def _normalized_optional_filter(values: Iterable[str] | None) -> set[str] | None:
    if values is None:
        return None
    return {normalized for value in values if (normalized := _normalized_status(value)) is not None}


def _normalized_context_filter(values: Iterable[str] | None) -> set[str] | None:
    if values is None:
        return None
    return {normalized for value in values if (normalized := str(value).strip())}


def _normalized_status(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None
