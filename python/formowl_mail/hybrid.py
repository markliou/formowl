"""Issue #56 fail-closed Hybrid-v2 path over authorized mail Observations.

The normal path loads the frozen tokenizer and exact-revision multilingual E5
encoder together from :mod:`formowl_core.dense_embedding`.  Missing or drifting
runtime artifacts block execution; this module has no hash, random, ASCII, or
diagnostic dense fallback.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from functools import lru_cache
import math
import re
import struct
import unicodedata
from threading import RLock
from time import monotonic as _system_monotonic
from time import perf_counter_ns as _system_perf_counter_ns
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from formowl_contract import (
    CandidateMention,
    ContractValidationError,
    Grant,
    Observation,
    sha256_json,
    stable_candidate_mention_id,
    to_plain,
)
from formowl_core import (
    DenseEmbeddingUnavailableError,
    DenseEncoder,
    ISSUE56_TARGET_DENSE_DIMENSION,
    ISSUE56_TARGET_DENSE_ENCODER_ID,
    ISSUE56_TARGET_DENSE_MODEL_ID,
    ISSUE56_TARGET_DENSE_MODEL_REVISION,
    ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT,
    Issue56TargetRuntimeComponents,
    build_issue56_execution_component_binding,
    issue56_target_dense_embedding_profile,
    load_issue56_target_runtime_components,
    sha256_prefixed,
)
from formowl_core.tokenization import MailCandidateAdmissionTokenizerProfile
from formowl_graph import EffectiveGraphView, soft_core_supertypes_compatible
from formowl_graph.index import GraphProjectionEdge, GraphProjectionNode
from formowl_graph.resolution import (
    ExactProtectedIdentifierCandidate,
    ExactProtectedIdentifierResolutionResult,
    resolve_exact_protected_identifier_candidates,
)

from ._access import matching_bundles
from ._guards import assert_public_payload_safe, safe_public_string
from .bundle import MailEvidenceBundle
from .candidates import (
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT,
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID,
    TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    SourceBoundIdentifierMentionBatch,
    SourceIdentifierIdentityScope,
)
from .exact import (
    SourceOccurrenceQueryPartition,
    SourceOccurrenceProvider,
    DeterministicExactExecutionResult,
    authorized_source_occurrence_scope_fingerprint,
    execute_deterministic_exact_inventory,
    execute_deterministic_source_occurrence_inventory,
)
from .query import (
    GitHubProjectOccurrenceLineage,
    IndexedObservationSnippet,
    IndexedMailSnippet,
    MailSnippetIndex,
    ObservationSnippetIndex,
    SourceOccurrenceLineage,
    authorize_mail_evidence_bundles,
    build_authorized_observation_snippet_index,
    build_existing_observation_snippet_index,
    normalized_authorized_observation_lineages,
    require_issue56_target_tokenizer_profile,
    source_occurrence_lineage_from_observation,
)
from .semantic_plan import (
    _CJK_EXACT_OUTPUT_GRAMMAR_V1,
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    DEFAULT_SEMANTIC_PLAN_LIMITS,
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
    AuthorizedSemanticSource,
    SemanticPlanLimits,
    SemanticQueryPlan,
    authorized_permission_scope_matches,
    deterministic_query_class,
    repair_relation_plan_once,
    route_semantic_query,
    validated_authorized_semantic_source,
    validate_semantic_query_plan,
)

_SUPPORTED_QUERY_CLASS = "evidence_lookup"
_BLOCKED_QUERY_CLASSES = {
    "exact_set_or_inventory",
    "global_summarization",
    "relation_reasoning",
}
ISSUE56_TARGET_RUNTIME_METHOD_ID = "evidence_to_knowledge_kg_ontology_v2_hybrid_v1"
_RRF_K = 60
_PINNED_DENSE_STATUS = "pinned_real_e5"
_SOURCE_GRAPH_POLICY_ID = "source_backed_mail_candidate_graph_v1"
_SOURCE_GRAPH_POLICY_ID_V2 = "source_backed_mail_candidate_graph_v2"
_SOURCE_GRAPH_GITHUB_REFERENCE_POLICY_ID = "source_backed_github_candidate_graph_v1"
_SOURCE_GRAPH_RELATION_TYPE = "co_occurs_with"
_SOURCE_GRAPH_IDENTIFIER_MENTION_RELATION_TYPE = "mentions_identifier"
_SOURCE_GRAPH_GITHUB_REFERENCE_RELATION_TYPE = "source_native_issue_reference"
_SOURCE_GRAPH_MAX_IDENTIFIERS_PER_OBSERVATION = 24
_SOURCE_GRAPH_MAX_TERMS_PER_OBSERVATION = 32
_SOURCE_GRAPH_MAX_TERM_HASHES_PER_ENTITY = 128
_RELATION_FALLBACK_POLICY_ID = "strict_no_answer_connected_authorized_relation_repair_v1"
_SEMANTIC_TIME_BUDGET_EXHAUSTED_WARNING = "semantic_query_time_budget_exhausted"
_SOURCE_OCCURRENCE_IDENTIFIER_NOT_FOUND_WARNING = (
    "source_occurrence_identifier_not_found"
)
_AUTHORIZED_EVIDENCE_IDENTIFIER_NOT_FOUND_WARNING = "authorized_evidence_identifier_not_found"
_MONOTONIC_CLOCK: Callable[[], float] = _system_monotonic
_SEMANTIC_PHASE_TRACE_CLOCK_NS: Callable[[], int] = _system_perf_counter_ns
_RELATION_PROJECTION_COLD_DIAGNOSTIC_CLOCK_NS: Callable[[], int] = _system_perf_counter_ns
_SEMANTIC_PHASE_TRACE_PHASES = (
    "source_session_validation",
    "graph_snapshot",
    "routing_plan",
    "lineage_crosswalk",
    "deterministic_exact_execution",
    "strong_rag",
    "relation_projection",
    "graph_traversal",
    "scoring",
    "proof_citation_selection",
    "fallback",
    "lineage_audit",
    "result_projection",
)
_SEMANTIC_PHASE_TRACE_OUTCOMES = {
    "completed",
    "skipped",
    "deadline_exhausted",
    "failed",
}
_RELATION_FALLBACK_POLICY_FINGERPRINT = sha256_json(
    {
        "policy_id": _RELATION_FALLBACK_POLICY_ID,
        "strict_path_precedence": True,
        "protected_identifiers_required": True,
        "concept_policy": "one_maximal_non_fragment_high_idf_authorized_concept",
        "proof_policy": "one_complete_connected_authorized_graph_path",
        "targeted_retraversal_limit": 1,
        "scope_change": "seed_narrowing_only",
    }
)
_EXACT_QUERY_OPERATOR_PHRASES = (
    "purchase orders",
    "purchase order",
    "exact set",
    "how many",
    "identifiers",
    "identifier",
    "messages",
    "message",
    "inventory",
    "emails",
    "email",
    "count",
    "total",
    "list",
    "every",
    "all",
    "about",
    "from",
    "with",
    "for",
    "the",
    "全部",
    "列出",
    "清單",
    "盤點",
    "多少",
    "計數",
    "總數",
    "每一",
    "所有",
    "郵件",
    "訊息",
    "電郵",
    "識別碼",
    "編號",
    "採購單",
    "請",
    "幫我",
    "查詢",
)
_RELATION_QUERY_OPERATOR_PHRASES = (
    "relationship",
    "cross-message",
    "relation",
    "related",
    "through",
    "關係",
    "關聯",
    "跨訊息",
    "透過",
)
_GENERAL_QUERY_OPERATOR_PHRASES = (
    "show me",
    "find",
    "lookup",
    "search",
    "what",
    "which",
    "where",
    "when",
    "who",
    "between",
    "and",
    "of",
    "the",
    "for",
    "with",
    "about",
    "please",
    "evidence",
    "請",
    "幫我",
    "查詢",
    "搜尋",
    "找出",
    "顯示",
    "什麼",
    "哪些",
    "何時",
    "哪裡",
    "誰",
    "之間",
    "以及",
    "與",
    "和",
    "的",
)
_MAX_DETERMINISTIC_PROOF_TOPIC_SLOTS = 4
_GRAPH_ADJACENCY_CACHE: dict[
    str,
    dict[str, tuple[tuple[GraphProjectionEdge, str, str], ...]],
] = {}
_EVIDENCE_LINEAGE_CROSSWALK_CACHE: dict[
    tuple[str, str, str],
    "EvidenceIdentityLineageCrosswalk",
] = {}
_EVIDENCE_LINEAGE_CROSSWALK_CACHE_LOCK = RLock()
_ISSUE56_TARGET_RUNTIME_METHOD_BINDING = {
    "method_id": "evidence_to_knowledge_kg_ontology_v2_hybrid_v1",
    "normal_entrypoint": "run_authorized_semantic_mail_query",
    "authorization_order": "permission_before_candidate_materialization",
    "lexical_dense_path": "bm25_pinned_multilingual_e5_same_profile_v1",
    "typed_router": "semantic_query_plan_fail_closed_v1",
    "entity_path": "source_backed_entity_matching_v1",
    "candidate_graph_path": "source_backed_mail_candidate_graph_v1",
    "ontology_path": "capped_soft_additive_ontology_v1",
    "exact_path": "deterministic_authorized_inventory_coverage_v1",
    "cited_result_path": "governed_authorized_observation_citations_v1",
    "legacy_hard_gate_default": False,
    "fallback_policy": "fail_closed_no_ascii_hash_random_or_diagnostic_fallback_v1",
}
ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT = sha256_json(_ISSUE56_TARGET_RUNTIME_METHOD_BINDING)
_EFFECTIVE_GRAPH_CONTENT_SNAPSHOT_ATTRIBUTE = "_formowl_issue56_effective_graph_content_snapshot_v1"


@dataclass(frozen=True)
class SemanticPhaseTiming:
    """One safe, query-local phase timing without source or query material."""

    phase: str
    attempt: int
    outcome: str
    elapsed_ms: float

    def to_safe_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "issue56_semantic_phase_timing")
        return payload


class SemanticPhaseTrace:
    """Opt-in behavior-neutral phase trace for one semantic query.

    The trace is an out-of-band diagnostic sidecar.  It deliberately carries
    only frozen phase enums, attempts, outcomes, and durations; it is not part
    of the query plan, result, graph, ranking, citation, or fingerprint payload.
    A trace instance is single-use so callers cannot accidentally combine
    timings from different authorization or graph contexts.
    """

    artifact_id = "formowl_issue56_semantic_phase_trace_v1"
    schema_version = 1
    trace_contract_fingerprint = sha256_json(
        {
            "artifact_id": artifact_id,
            "schema_version": schema_version,
            "phases": list(_SEMANTIC_PHASE_TRACE_PHASES),
            "outcomes": sorted(_SEMANTIC_PHASE_TRACE_OUTCOMES),
            "private_payload_policy": "phase_enum_attempt_outcome_duration_only",
            "result_binding_policy": "out_of_band_not_fingerprinted",
        }
    )

    def __init__(self) -> None:
        self._entries: list[SemanticPhaseTiming] = []
        self._started = False
        self._terminal_status: str | None = None
        self._last_completed_phase: str | None = None
        self._deadline_exhausted_phase: str | None = None

    def _begin_query(self) -> None:
        if self._started or self._terminal_status is not None or self._entries:
            raise ContractValidationError("semantic phase trace is single-use")
        self._started = True

    def _start_phase(self, phase: str) -> int:
        self._require_active_phase(phase)
        return _SEMANTIC_PHASE_TRACE_CLOCK_NS()

    def _finish_phase(
        self,
        *,
        phase: str,
        started_at_ns: int,
        outcome: str,
    ) -> None:
        self._require_active_phase(phase)
        if outcome not in _SEMANTIC_PHASE_TRACE_OUTCOMES - {"skipped"}:
            raise ContractValidationError("semantic phase trace outcome is invalid")
        finished_at_ns = _SEMANTIC_PHASE_TRACE_CLOCK_NS()
        elapsed_ms = max(0.0, (finished_at_ns - started_at_ns) / 1_000_000.0)
        attempt = sum(entry.phase == phase for entry in self._entries) + 1
        self._entries.append(
            SemanticPhaseTiming(
                phase=phase,
                attempt=attempt,
                outcome=outcome,
                elapsed_ms=round(elapsed_ms, 6),
            )
        )
        if outcome == "completed":
            self._last_completed_phase = phase
        elif outcome == "deadline_exhausted":
            self._deadline_exhausted_phase = phase

    def _skip_phase(self, phase: str) -> None:
        self._require_active_phase(phase)
        if any(entry.phase == phase for entry in self._entries):
            return
        self._entries.append(
            SemanticPhaseTiming(
                phase=phase,
                attempt=0,
                outcome="skipped",
                elapsed_ms=0.0,
            )
        )

    def _finish_query(self, terminal_status: str) -> None:
        if terminal_status not in {"completed", "deadline_exhausted", "failed"}:
            raise ContractValidationError("semantic phase trace terminal status is invalid")
        if not self._started or self._terminal_status is not None:
            raise ContractValidationError("semantic phase trace lifecycle is invalid")
        for phase in _SEMANTIC_PHASE_TRACE_PHASES:
            self._skip_phase(phase)
        self._terminal_status = terminal_status
        self.to_safe_dict()

    def _require_active_phase(self, phase: str) -> None:
        if phase not in _SEMANTIC_PHASE_TRACE_PHASES:
            raise ContractValidationError("semantic phase trace phase is invalid")
        if not self._started or self._terminal_status is not None:
            raise ContractValidationError("semantic phase trace is not active")

    def to_safe_dict(self) -> dict[str, Any]:
        if not self._started:
            raise ContractValidationError("semantic phase trace has not started")
        payload = {
            "artifact_id": self.artifact_id,
            "schema_version": self.schema_version,
            "trace_contract_fingerprint": self.trace_contract_fingerprint,
            "terminal_status": self._terminal_status or "in_progress",
            "last_completed_phase": self._last_completed_phase,
            "deadline_exhausted_phase": self._deadline_exhausted_phase,
            "phase_event_count": len(self._entries),
            "phases": [entry.to_safe_dict() for entry in self._entries],
        }
        assert_public_payload_safe(payload, "issue56_semantic_phase_trace")
        return payload


class _QueryExecutionDeadlineExceeded(RuntimeError):
    """Internal fail-closed signal; it never carries private phase data."""


@dataclass(frozen=True)
class _QueryExecutionDeadline:
    """One monotonic deadline shared by every phase of one semantic query."""

    budget_ms: int
    started_at: float
    expires_at: float
    clock: Callable[[], float] = field(repr=False, compare=False)

    @classmethod
    def start(
        cls,
        *,
        budget_ms: int,
        clock: Callable[[], float] | None = None,
    ) -> "_QueryExecutionDeadline":
        if not isinstance(budget_ms, int) or isinstance(budget_ms, bool) or budget_ms < 1:
            raise ContractValidationError("semantic query time budget is invalid")
        selected_clock = clock or _MONOTONIC_CLOCK
        started_at = selected_clock()
        return cls(
            budget_ms=budget_ms,
            started_at=started_at,
            expires_at=started_at + (budget_ms / 1_000.0),
            clock=selected_clock,
        )

    def checkpoint(self) -> None:
        if self.clock() >= self.expires_at:
            raise _QueryExecutionDeadlineExceeded(_SEMANTIC_TIME_BUDGET_EXHAUSTED_WARNING)

    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_at - self.clock())


_ACTIVE_QUERY_EXECUTION_DEADLINE: ContextVar[_QueryExecutionDeadline | None] = ContextVar(
    "formowl_issue56_active_query_execution_deadline",
    default=None,
)
_TIME_BUDGET_EXHAUSTED = object()


def _run_before_query_deadline(
    deadline: _QueryExecutionDeadline,
    operation: Callable[[], Any],
) -> Any:
    token = _ACTIVE_QUERY_EXECUTION_DEADLINE.set(deadline)
    try:
        deadline.checkpoint()
        result = operation()
        deadline.checkpoint()
        return result
    except _QueryExecutionDeadlineExceeded:
        return _TIME_BUDGET_EXHAUSTED
    finally:
        _ACTIVE_QUERY_EXECUTION_DEADLINE.reset(token)


def _run_traced_query_phase(
    *,
    deadline: _QueryExecutionDeadline,
    phase_trace: SemanticPhaseTrace | None,
    phase: str,
    operation: Callable[[], Any],
) -> Any:
    if phase_trace is None:
        return _run_before_query_deadline(deadline, operation)
    started_at_ns = phase_trace._start_phase(phase)
    try:
        result = _run_before_query_deadline(deadline, operation)
    except Exception:
        phase_trace._finish_phase(
            phase=phase,
            started_at_ns=started_at_ns,
            outcome="failed",
        )
        phase_trace._finish_query("failed")
        raise
    phase_trace._finish_phase(
        phase=phase,
        started_at_ns=started_at_ns,
        outcome=("deadline_exhausted" if result is _TIME_BUDGET_EXHAUSTED else "completed"),
    )
    return result


def _run_unbudgeted_traced_phase(
    *,
    phase_trace: SemanticPhaseTrace,
    phase: str,
    operation: Callable[[], Any],
) -> Any:
    started_at_ns = phase_trace._start_phase(phase)
    try:
        result = operation()
    except Exception:
        phase_trace._finish_phase(
            phase=phase,
            started_at_ns=started_at_ns,
            outcome="failed",
        )
        phase_trace._finish_query("failed")
        raise
    phase_trace._finish_phase(
        phase=phase,
        started_at_ns=started_at_ns,
        outcome="completed",
    )
    return result


def _query_deadline_checkpoint(
    execution_deadline: _QueryExecutionDeadline | None,
) -> None:
    selected_deadline = execution_deadline or _ACTIVE_QUERY_EXECUTION_DEADLINE.get()
    if selected_deadline is not None:
        selected_deadline.checkpoint()


@contextmanager
def _acquire_relation_projection_base_lock(
    lock: RLock,
    *,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> Iterator[None]:
    selected_deadline = execution_deadline or _ACTIVE_QUERY_EXECUTION_DEADLINE.get()
    acquired = False
    try:
        if selected_deadline is None:
            lock.acquire()
            acquired = True
        else:
            remaining_seconds = selected_deadline.remaining_seconds()
            if remaining_seconds <= 0.0 or not lock.acquire(timeout=remaining_seconds):
                raise _QueryExecutionDeadlineExceeded(_SEMANTIC_TIME_BUDGET_EXHAUSTED_WARNING)
            acquired = True
            selected_deadline.checkpoint()
        yield
    finally:
        if acquired:
            lock.release()


class _FrozenGraphList(list[Any]):
    """List-compatible immutable JSON value used to seal an effective view."""

    @staticmethod
    def _reject_mutation(*_args: Any, **_kwargs: Any) -> None:
        raise ContractValidationError("effective graph snapshot is immutable")

    __delitem__ = _reject_mutation
    __iadd__ = _reject_mutation
    __imul__ = _reject_mutation
    __setitem__ = _reject_mutation
    append = _reject_mutation
    clear = _reject_mutation
    extend = _reject_mutation
    insert = _reject_mutation
    pop = _reject_mutation
    remove = _reject_mutation
    reverse = _reject_mutation
    sort = _reject_mutation


class _FrozenGraphDict(dict[str, Any]):
    """Dict-compatible immutable JSON value used to seal an effective view."""

    @staticmethod
    def _reject_mutation(*_args: Any, **_kwargs: Any) -> None:
        raise ContractValidationError("effective graph snapshot is immutable")

    __delitem__ = _reject_mutation
    __ior__ = _reject_mutation
    __setitem__ = _reject_mutation
    clear = _reject_mutation
    pop = _reject_mutation
    popitem = _reject_mutation
    setdefault = _reject_mutation
    update = _reject_mutation


@dataclass(frozen=True)
class HybridRagCandidateScore:
    source_observation_hash: str
    message_hash: str
    bm25_score: float
    dense_score: float
    bm25_rank: int | None
    dense_rank: int | None
    fusion_score: float

    def to_safe_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "issue56_hybrid_candidate_score")
        return payload


@dataclass(frozen=True)
class HybridRagBundleScore:
    evidence_bundle_hash: str
    evidence_count: int
    unique_message_count: int
    source_observation_hashes: tuple[str, ...]
    matched_protected_identifier_hashes: tuple[str, ...]
    bm25_score: float
    dense_score: float
    fusion_score: float
    query_coverage_score: float
    multi_message_score: float
    rerank_score: float
    candidate_scores: tuple[HybridRagCandidateScore, ...]

    def to_safe_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "issue56_hybrid_bundle_score")
        return payload


@dataclass(frozen=True)
class GovernedHybridRagResult:
    artifact_id: str
    status: str
    runtime_method_id: str
    runtime_method_fingerprint: str
    query_hash: str
    query_class: str
    candidate_profile_id: str
    profile_fingerprint: str
    index_fingerprint: str | None
    dense_encoder_id: str
    dense_encoder_status: str
    dense_profile_fingerprint: str
    dense_model_id: str
    dense_model_revision: str
    execution_component_fingerprint: str
    selected_bundle_count: int
    authorized_bundle_count: int
    denied_bundle_count: int
    materialized_candidate_count: int
    retrieved_candidate_count: int
    result_bundle_count: int
    exact_executor_status: str
    results: tuple[HybridRagBundleScore, ...] = ()
    admitted_candidate_scores: tuple[HybridRagCandidateScore, ...] = ()
    answer_citation_hashes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_safe_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "issue56_governed_hybrid_rag_result")
        return payload


@dataclass(frozen=True)
class GraphTraversalHop:
    edge_hash: str
    relation_type_hash: str
    direction: str
    source_node_hash: str
    target_node_hash: str
    cited_observation_hashes: tuple[str, ...]

    def to_safe_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "issue56_graph_traversal_hop")
        return payload


@dataclass(frozen=True)
class BoundedGraphPath:
    path_hash: str
    hop_count: int
    graph_path_score: float
    cited_observation_hashes: tuple[str, ...]
    hops: tuple[GraphTraversalHop, ...]

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "path_hash": self.path_hash,
            "hop_count": self.hop_count,
            "graph_path_score": self.graph_path_score,
            "cited_observation_hashes": list(self.cited_observation_hashes),
            "citation_count": len(self.cited_observation_hashes),
            "hops": [hop.to_safe_dict() for hop in self.hops],
        }
        assert_public_payload_safe(payload, "issue56_bounded_graph_path")
        return payload


@dataclass(frozen=True)
class SemanticEvidenceScore:
    evidence_bundle_hash: str
    source_observation_hash: str
    message_hash: str
    lexical_score: float
    dense_score: float
    entity_score: float
    graph_path_score: float
    temporal_current_score: float
    provenance_coverage_score: float
    ontology_bonus: float
    ontology_bonus_cap: float
    base_score: float
    total_score: float

    def to_safe_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "issue56_semantic_evidence_score")
        return payload


@dataclass(frozen=True)
class GovernedSemanticExecutionResult:
    artifact_id: str
    status: str
    runtime_method_id: str
    runtime_method_fingerprint: str
    query_hash: str
    query_class: str
    claim_strength: str
    plan_fingerprint: str | None
    result_fingerprint: str
    profile_fingerprint: str
    index_fingerprint: str | None
    graph_revision_fingerprint: str
    dense_encoder_id: str
    dense_encoder_status: str
    dense_profile_fingerprint: str
    dense_model_id: str
    dense_model_revision: str
    execution_component_fingerprint: str
    selected_bundle_count: int
    authorized_bundle_count: int
    denied_bundle_count: int
    materialized_candidate_count: int
    semantic_result_count: int
    graph_path_count: int
    rejected_hop_count: int
    exact_executor_status: str
    repair_attempt_count: int
    relation_repair_policy_fingerprint: str | None
    relation_repair_vocabulary_fingerprint: str | None
    scores: tuple[SemanticEvidenceScore, ...] = ()
    graph_paths: tuple[BoundedGraphPath, ...] = ()
    answer_citation_hashes: tuple[str, ...] = ()
    exact_result: DeterministicExactExecutionResult | None = None
    lineage_audit: EvidenceIdentityLineageAudit | None = None
    warnings: tuple[str, ...] = ()

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": self.artifact_id,
            "status": self.status,
            "runtime_method_id": self.runtime_method_id,
            "runtime_method_fingerprint": self.runtime_method_fingerprint,
            "query_hash": self.query_hash,
            "query_class": self.query_class,
            "claim_strength": self.claim_strength,
            "plan_fingerprint": self.plan_fingerprint,
            "result_fingerprint": self.result_fingerprint,
            "profile_fingerprint": self.profile_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "dense_encoder_id": self.dense_encoder_id,
            "dense_encoder_status": self.dense_encoder_status,
            "dense_profile_fingerprint": self.dense_profile_fingerprint,
            "dense_model_id": self.dense_model_id,
            "dense_model_revision": self.dense_model_revision,
            "execution_component_fingerprint": (self.execution_component_fingerprint),
            "selected_bundle_count": self.selected_bundle_count,
            "authorized_bundle_count": self.authorized_bundle_count,
            "denied_bundle_count": self.denied_bundle_count,
            "materialized_candidate_count": self.materialized_candidate_count,
            "semantic_result_count": self.semantic_result_count,
            "graph_path_count": self.graph_path_count,
            "rejected_hop_count": self.rejected_hop_count,
            "exact_executor_status": self.exact_executor_status,
            "repair_attempt_count": self.repair_attempt_count,
            "relation_repair_policy_fingerprint": (self.relation_repair_policy_fingerprint),
            "relation_repair_vocabulary_fingerprint": (self.relation_repair_vocabulary_fingerprint),
            "scores": [score.to_safe_dict() for score in self.scores],
            "graph_paths": [path.to_safe_dict() for path in self.graph_paths],
            "answer_citation_hashes": list(self.answer_citation_hashes),
            "exact_result": (
                self.exact_result.to_safe_dict() if self.exact_result is not None else None
            ),
            "lineage_audit": (
                self.lineage_audit.to_safe_dict() if self.lineage_audit is not None else None
            ),
            "warnings": list(self.warnings),
        }
        assert_public_payload_safe(payload, "issue56_governed_semantic_execution_result")
        return payload


@dataclass(frozen=True)
class SourceBackedGraphBuild:
    """Permission-scoped candidate graph projected from source Observations."""

    effective_graph_view: EffectiveGraphView = field(repr=False, compare=False)
    graph_revision_fingerprint: str
    source_observation_count: int
    observation_node_count: int
    entity_node_count: int
    edge_count: int
    ontology_typed_node_count: int
    relation_type_hashes: tuple[str, ...]
    build_fingerprint: str
    graph_policy_id: str = _SOURCE_GRAPH_POLICY_ID
    complete_identifier_mention_fingerprint: str | None = None
    authorized_identifier_mention_fingerprint: str | None = None
    identifier_resolution_fingerprint: str | None = None
    identifier_mention_count: int = 0
    authorized_identifier_mention_count: int = 0
    identity_scope_mode: str | None = None
    identity_scope_fingerprint: str | None = None
    identity_scope_attestation_fingerprint: str | None = None
    identity_scope_policy_fingerprint: str | None = None
    operator_approval_fingerprint: str | None = None
    spec_approval_fingerprint: str | None = None
    identity_scope_graph_binding_fingerprint: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": _source_backed_graph_artifact_id(self.graph_policy_id),
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "source_observation_count": self.source_observation_count,
            "observation_node_count": self.observation_node_count,
            "entity_node_count": self.entity_node_count,
            "edge_count": self.edge_count,
            "ontology_typed_node_count": self.ontology_typed_node_count,
            "relation_type_hashes": list(self.relation_type_hashes),
            "build_fingerprint": self.build_fingerprint,
            "graph_policy_id": self.graph_policy_id,
            "candidate_graph_only": True,
            "human_review_complete": False,
        }
        if self.graph_policy_id == _SOURCE_GRAPH_POLICY_ID_V2:
            payload.update(
                {
                    "complete_identifier_mention_fingerprint": (
                        self.complete_identifier_mention_fingerprint
                    ),
                    "authorized_identifier_mention_fingerprint": (
                        self.authorized_identifier_mention_fingerprint
                    ),
                    "identifier_resolution_fingerprint": (self.identifier_resolution_fingerprint),
                    "identifier_mention_count": self.identifier_mention_count,
                    "authorized_identifier_mention_count": (
                        self.authorized_identifier_mention_count
                    ),
                    "identity_scope_mode": self.identity_scope_mode,
                    "identity_scope_fingerprint": self.identity_scope_fingerprint,
                    "identity_scope_attestation_fingerprint": (
                        self.identity_scope_attestation_fingerprint
                    ),
                    "identity_scope_policy_fingerprint": (self.identity_scope_policy_fingerprint),
                    "operator_approval_fingerprint": (self.operator_approval_fingerprint),
                    "identity_scope_graph_binding_fingerprint": (
                        self.identity_scope_graph_binding_fingerprint
                    ),
                }
            )
            if self.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
                payload["spec_approval_fingerprint"] = self.spec_approval_fingerprint
        assert_public_payload_safe(payload, "issue56_source_backed_graph_build")
        return payload


@dataclass(frozen=True)
class _SourceIdentifierMentionGraphInput:
    """Validated source-authored identifier occurrences for one authorized build."""

    batch: SourceBoundIdentifierMentionBatch = field(repr=False, compare=False)
    authorized_mentions: tuple[CandidateMention, ...] = field(
        repr=False,
        compare=False,
    )
    exact_resolution: ExactProtectedIdentifierResolutionResult = field(
        repr=False,
        compare=False,
    )
    exact_candidate_by_mention_id: Mapping[
        str,
        ExactProtectedIdentifierCandidate,
    ] = field(repr=False, compare=False)
    mentions_by_observation_id: Mapping[str, tuple[CandidateMention, ...]] = field(
        repr=False,
        compare=False,
    )
    identity_scope: SourceIdentifierIdentityScope
    graph_identity_binding: Mapping[str, str]
    graph_identity_binding_fingerprint: str
    governed_scope_fingerprint: str
    complete_mention_fingerprint: str
    authorized_mention_fingerprint: str


@dataclass(frozen=True)
class EvidenceIdentityLineageEntry:
    """Hash-only binding from one authorized Observation into runtime surfaces."""

    source_observation_hash: str
    index_binding_hashes: tuple[str, ...]
    message_hashes: tuple[str, ...]
    occurrence_hashes: tuple[str, ...]
    graph_node_hashes: tuple[str, ...]
    graph_edge_hashes: tuple[str, ...]

    def to_safe_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "issue56_evidence_identity_lineage_entry")
        return payload


@dataclass(frozen=True)
class EvidenceIdentityLineageCrosswalk:
    """Query-independent authorized evidence identity map with no source locators."""

    index_fingerprint: str
    graph_revision_fingerprint: str
    source_session_binding_fingerprint: str
    authorized_evidence_count: int
    indexed_evidence_count: int
    occurrence_bound_evidence_count: int
    graph_node_bound_evidence_count: int
    graph_edge_bound_evidence_count: int
    entries: tuple[EvidenceIdentityLineageEntry, ...]
    crosswalk_fingerprint: str

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": "formowl_issue56_evidence_identity_lineage_crosswalk_v1",
            "index_fingerprint": self.index_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "source_session_binding_fingerprint": (
                self.source_session_binding_fingerprint
            ),
            "authorized_evidence_count": self.authorized_evidence_count,
            "indexed_evidence_count": self.indexed_evidence_count,
            "occurrence_bound_evidence_count": self.occurrence_bound_evidence_count,
            "graph_node_bound_evidence_count": self.graph_node_bound_evidence_count,
            "graph_edge_bound_evidence_count": self.graph_edge_bound_evidence_count,
            "entries": [entry.to_safe_dict() for entry in self.entries],
            "crosswalk_fingerprint": self.crosswalk_fingerprint,
        }
        assert_public_payload_safe(payload, "issue56_evidence_identity_lineage_crosswalk")
        return payload


@dataclass(frozen=True)
class EffectiveGraphContentSnapshotPrecompute:
    """Safe evidence that one immutable graph snapshot is materialized cold."""

    graph_revision_fingerprint: str
    graph_content_fingerprint: str
    effective_graph_view_fingerprint: str
    source_session_binding_fingerprint: str
    source_access_fingerprint: str
    permission_lineage_fingerprint: str
    index_fingerprint: str
    candidate_admission_profile_fingerprint: str
    authorized_observation_set_fingerprint: str
    authorized_observation_count: int
    source_scope_count: int
    node_count: int
    edge_count: int
    access_required_count: int
    applied_grant_count: int
    relation_projection_cache_binding_entry_count: int
    relation_projection_base_entry_count: int
    precompute_fingerprint: str

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": "formowl_issue56_effective_graph_content_snapshot_precompute_v1",
            "schema_version": 1,
            "status": "passed",
            "snapshot_status": "materialized_relation_projection_caches_cold",
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "graph_content_fingerprint": self.graph_content_fingerprint,
            "effective_graph_view_fingerprint": self.effective_graph_view_fingerprint,
            "source_session_binding_fingerprint": self.source_session_binding_fingerprint,
            "source_access_fingerprint": self.source_access_fingerprint,
            "permission_lineage_fingerprint": self.permission_lineage_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "candidate_admission_profile_fingerprint": (
                self.candidate_admission_profile_fingerprint
            ),
            "authorized_observation_set_fingerprint": (self.authorized_observation_set_fingerprint),
            "counts": {
                "authorized_observation_count": self.authorized_observation_count,
                "source_scope_count": self.source_scope_count,
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "access_required_count": self.access_required_count,
                "applied_grant_count": self.applied_grant_count,
                "relation_projection_cache_binding_entry_count": (
                    self.relation_projection_cache_binding_entry_count
                ),
                "relation_projection_base_entry_count": (self.relation_projection_base_entry_count),
            },
            "precompute_fingerprint": self.precompute_fingerprint,
        }
        assert_public_payload_safe(
            payload,
            "issue56_effective_graph_content_snapshot_precompute",
        )
        return payload


@dataclass(frozen=True)
class RelationProjectionBasePrecompute:
    """Safe evidence that one immutable relation projection base is primed."""

    cache_binding_fingerprint: str
    graph_revision_fingerprint: str
    index_fingerprint: str
    tokenizer_profile_fingerprint: str
    authorized_observation_set_fingerprint: str
    candidate_set_fingerprint: str
    authorized_observation_count: int
    candidate_count: int
    projected_node_count: int
    observation_bound_node_group_count: int
    adjacency_node_count: int
    adjacency_transition_count: int
    authorized_index_vocabulary_hash_count: int
    authorized_graph_vocabulary_hash_count: int
    precompute_fingerprint: str

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": "formowl_issue56_relation_projection_base_precompute_v1",
            "schema_version": 1,
            "status": "passed",
            "cache_status": "primed",
            "cache_binding_fingerprint": self.cache_binding_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "candidate_admission_profile_fingerprint": (self.tokenizer_profile_fingerprint),
            "authorized_observation_set_fingerprint": (self.authorized_observation_set_fingerprint),
            "candidate_set_fingerprint": self.candidate_set_fingerprint,
            "counts": {
                "authorized_observation_count": self.authorized_observation_count,
                "candidate_count": self.candidate_count,
                "projected_node_count": self.projected_node_count,
                "observation_bound_node_group_count": (self.observation_bound_node_group_count),
                "adjacency_node_count": self.adjacency_node_count,
                "adjacency_transition_count": self.adjacency_transition_count,
                "authorized_index_vocabulary_hash_count": (
                    self.authorized_index_vocabulary_hash_count
                ),
                "authorized_graph_vocabulary_hash_count": (
                    self.authorized_graph_vocabulary_hash_count
                ),
            },
            "precompute_fingerprint": self.precompute_fingerprint,
        }
        assert_public_payload_safe(
            payload,
            "issue56_relation_projection_base_precompute",
        )
        return payload


@dataclass(frozen=True)
class RelationProjectionBaseColdDiagnostic:
    """Safe evidence for one offline cold binding/base build."""

    graph_revision_fingerprint: str
    graph_content_fingerprint: str
    effective_graph_view_fingerprint: str
    source_session_binding_fingerprint: str
    source_access_fingerprint: str
    permission_lineage_fingerprint: str
    index_fingerprint: str
    tokenizer_profile_fingerprint: str
    authorized_observation_set_fingerprint: str
    candidate_set_fingerprint: str
    cache_binding_fingerprint: str
    relation_projection_base_precompute_fingerprint: str
    before_binding_cache_entry_count: int
    before_base_cache_entry_count: int
    after_binding_cache_entry_count: int
    after_base_cache_entry_count: int
    binding_started: bool
    binding_completed: bool
    binding_elapsed_ms: float
    binding_invocation_count: int
    binding_publication_status: str
    base_builder_started: bool
    base_builder_completed: bool
    base_builder_elapsed_ms: float
    base_builder_invocation_count: int
    base_publication_status: str
    authorized_observation_count: int
    candidate_count: int
    projected_node_count: int
    observation_bound_node_group_count: int
    adjacency_node_count: int
    adjacency_transition_count: int
    authorized_index_vocabulary_hash_count: int
    authorized_graph_vocabulary_hash_count: int
    diagnostic_fingerprint: str

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": ("formowl_issue56_relation_projection_base_cold_diagnostic_v1"),
            "schema_version": 1,
            "status": "passed",
            "claim_boundary": "diagnostic_only_not_query_or_methodology_evidence",
            "deadline_mode": "offline_no_query_deadline",
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "graph_content_fingerprint": self.graph_content_fingerprint,
            "effective_graph_view_fingerprint": (self.effective_graph_view_fingerprint),
            "source_session_binding_fingerprint": (self.source_session_binding_fingerprint),
            "source_access_fingerprint": self.source_access_fingerprint,
            "permission_lineage_fingerprint": self.permission_lineage_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "candidate_admission_profile_fingerprint": (self.tokenizer_profile_fingerprint),
            "authorized_observation_set_fingerprint": (self.authorized_observation_set_fingerprint),
            "candidate_set_fingerprint": self.candidate_set_fingerprint,
            "cache_binding_fingerprint": self.cache_binding_fingerprint,
            "relation_projection_base_precompute_fingerprint": (
                self.relation_projection_base_precompute_fingerprint
            ),
            "cache": {
                "before": {
                    "binding_entry_count": (self.before_binding_cache_entry_count),
                    "base_entry_count": self.before_base_cache_entry_count,
                },
                "after": {
                    "binding_entry_count": self.after_binding_cache_entry_count,
                    "base_entry_count": self.after_base_cache_entry_count,
                },
            },
            "phases": {
                "binding": {
                    "started": self.binding_started,
                    "completed": self.binding_completed,
                    "elapsed_ms": self.binding_elapsed_ms,
                    "invocation_count": self.binding_invocation_count,
                    "publication_status": self.binding_publication_status,
                },
                "base_builder": {
                    "started": self.base_builder_started,
                    "completed": self.base_builder_completed,
                    "elapsed_ms": self.base_builder_elapsed_ms,
                    "invocation_count": self.base_builder_invocation_count,
                    "publication_status": self.base_publication_status,
                },
            },
            "counts": {
                "authorized_observation_count": self.authorized_observation_count,
                "candidate_count": self.candidate_count,
                "projected_node_count": self.projected_node_count,
                "observation_bound_node_group_count": (self.observation_bound_node_group_count),
                "adjacency_node_count": self.adjacency_node_count,
                "adjacency_transition_count": self.adjacency_transition_count,
                "authorized_index_vocabulary_hash_count": (
                    self.authorized_index_vocabulary_hash_count
                ),
                "authorized_graph_vocabulary_hash_count": (
                    self.authorized_graph_vocabulary_hash_count
                ),
            },
            "diagnostic_fingerprint": self.diagnostic_fingerprint,
        }
        assert_public_payload_safe(
            payload,
            "issue56_relation_projection_base_cold_diagnostic",
        )
        return payload


@dataclass
class _RelationProjectionBaseColdDiagnosticRecorder:
    """Private default-off recorder for one exact cold cache publication."""

    clock_ns: Callable[[], int] = field(repr=False)
    binding_started_at_ns: int | None = None
    binding_elapsed_ms: float | None = None
    binding_invocation_count: int = 0
    binding_publication_count: int = 0
    base_builder_started_at_ns: int | None = None
    base_builder_elapsed_ms: float | None = None
    base_builder_invocation_count: int = 0
    base_publication_count: int = 0

    def start_binding(self) -> None:
        if (
            self.binding_started_at_ns is not None
            or self.binding_elapsed_ms is not None
            or self.binding_invocation_count != 0
            or self.binding_publication_count != 0
        ):
            raise ContractValidationError(
                "relation projection cold diagnostic binding invocation mismatch"
            )
        self.binding_started_at_ns = self.clock_ns()
        self.binding_invocation_count = 1

    def complete_binding(self) -> None:
        if (
            self.binding_started_at_ns is None
            or self.binding_elapsed_ms is not None
            or self.binding_invocation_count != 1
        ):
            raise ContractValidationError(
                "relation projection cold diagnostic binding completion mismatch"
            )
        completed_at_ns = self.clock_ns()
        if completed_at_ns < self.binding_started_at_ns:
            raise ContractValidationError(
                "relation projection cold diagnostic clock moved backwards"
            )
        self.binding_elapsed_ms = round(
            (completed_at_ns - self.binding_started_at_ns) / 1_000_000.0,
            6,
        )

    def publish_binding(self) -> None:
        if (
            self.binding_elapsed_ms is None
            or self.binding_invocation_count != 1
            or self.binding_publication_count != 0
        ):
            raise ContractValidationError(
                "relation projection cold diagnostic binding publication mismatch"
            )
        self.binding_publication_count = 1

    def start_base_builder(self) -> None:
        if (
            self.base_builder_started_at_ns is not None
            or self.base_builder_elapsed_ms is not None
            or self.base_builder_invocation_count != 0
            or self.base_publication_count != 0
        ):
            raise ContractValidationError(
                "relation projection cold diagnostic base invocation mismatch"
            )
        self.base_builder_started_at_ns = self.clock_ns()
        self.base_builder_invocation_count = 1

    def complete_base_builder(self) -> None:
        if (
            self.base_builder_started_at_ns is None
            or self.base_builder_elapsed_ms is not None
            or self.base_builder_invocation_count != 1
        ):
            raise ContractValidationError(
                "relation projection cold diagnostic base completion mismatch"
            )
        completed_at_ns = self.clock_ns()
        if completed_at_ns < self.base_builder_started_at_ns:
            raise ContractValidationError(
                "relation projection cold diagnostic clock moved backwards"
            )
        self.base_builder_elapsed_ms = round(
            (completed_at_ns - self.base_builder_started_at_ns) / 1_000_000.0,
            6,
        )

    def publish_base(self) -> None:
        if (
            self.base_builder_elapsed_ms is None
            or self.base_builder_invocation_count != 1
            or self.base_publication_count != 0
        ):
            raise ContractValidationError(
                "relation projection cold diagnostic base publication mismatch"
            )
        self.base_publication_count = 1


@dataclass(frozen=True)
class EvidenceIdentityLineageAudit:
    """Per-result hash-only trace; adjudication is never an input."""

    crosswalk_fingerprint: str
    traced_evidence_hashes: tuple[str, ...]
    graph_path_evidence_hashes: tuple[str, ...]
    final_citation_hashes: tuple[str, ...]
    exact_item_evidence_hashes: tuple[str, ...]
    unresolved_evidence_hashes: tuple[str, ...]
    audit_fingerprint: str

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": "formowl_issue56_evidence_identity_lineage_audit_v1",
            "crosswalk_fingerprint": self.crosswalk_fingerprint,
            "traced_evidence_hashes": list(self.traced_evidence_hashes),
            "graph_path_evidence_hashes": list(self.graph_path_evidence_hashes),
            "final_citation_hashes": list(self.final_citation_hashes),
            "exact_item_evidence_hashes": list(self.exact_item_evidence_hashes),
            "unresolved_evidence_hashes": list(self.unresolved_evidence_hashes),
            "audit_fingerprint": self.audit_fingerprint,
        }
        assert_public_payload_safe(payload, "issue56_evidence_identity_lineage_audit")
        return payload


@dataclass(frozen=True)
class _HybridCandidate:
    bundle_id: str
    coherence_group_hash: str
    source_observation_hash: str
    message_hash: str
    message_occurrence_hash: str
    index_binding_hash: str
    searchable_tokens: frozenset[str]
    protected_identifier_tokens: frozenset[str]
    observation_tokens: frozenset[str]
    observation_protected_identifier_tokens: frozenset[str]
    dense_evidence_text_hash: str
    dense_vector: tuple[float, ...]


@dataclass(frozen=True)
class _EvidenceQuerySlots:
    identifier_tokens: frozenset[str]
    topic_tokens: frozenset[str]


@dataclass(frozen=True)
class _RelationFallbackSlotSelection:
    identifier_tokens: frozenset[str]
    concept_tokens: frozenset[str]
    identifier_term_hashes: tuple[str, ...]
    concept_term_hashes: tuple[str, ...]
    vocabulary_fingerprint: str

    @property
    def proof_slots(self) -> _EvidenceQuerySlots:
        return _EvidenceQuerySlots(
            identifier_tokens=self.identifier_tokens,
            topic_tokens=self.concept_tokens,
        )


@dataclass(frozen=True)
class _RelationFallbackOutcome:
    plan: SemanticQueryPlan
    graph_paths: tuple[BoundedGraphPath, ...]
    answer_citation_hashes: tuple[str, ...]
    rejected_hop_count: int
    targeted_retraversal_used: bool


@dataclass(frozen=True)
class _EffectiveGraphContentSnapshot:
    """Permission-bound immutable graph content shared by queries over one view."""

    graph_revision_fingerprint: str
    view_binding: tuple[Any, ...]
    source_neutral_session_binding: tuple[Any, ...] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    relation_projection_cache_binding_snapshots: dict[tuple[Any, ...], Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    relation_projection_bases: dict[str, Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    relation_projection_base_lock: RLock = field(
        default_factory=RLock,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True)
class _QueryGraphSnapshot:
    """One query-local handle to an immutable full-content graph snapshot."""

    effective_graph_view: EffectiveGraphView = field(repr=False, compare=False)
    graph_revision_fingerprint: str
    content_snapshot: _EffectiveGraphContentSnapshot = field(
        repr=False,
        compare=False,
    )


@dataclass(frozen=True)
class _RelationProjectionNode:
    node: GraphProjectionNode = field(repr=False, compare=False)
    node_id: str
    node_hash: str
    node_kind: str | None
    authorized_evidence_hashes: tuple[str, ...] | None
    searchable_tokens: frozenset[str]
    searchable_protected_tokens: frozenset[str]
    source_term_hashes: frozenset[str]
    protected_term_hashes: frozenset[str]
    bound_candidate_concept_term_hashes: frozenset[str]
    bound_candidate_identifier_term_hashes: frozenset[str]
    lineage_support_by_observation_hash: tuple[
        tuple[str, frozenset[str], frozenset[str]],
        ...,
    ]


@dataclass(frozen=True)
class _RelationProjectionTransition:
    edge: GraphProjectionEdge = field(repr=False, compare=False)
    direction: str
    next_node_id: str
    authorized_evidence_hashes: tuple[str, ...] | None


@dataclass(frozen=True)
class _RelationProjectionBase:
    """Query-independent authorized projection over one immutable graph snapshot."""

    cache_binding_fingerprint: str
    authorized_observation_set_fingerprint: str
    candidate_set_fingerprint: str
    candidate_concept_term_hashes_by_observation: Mapping[str, frozenset[str]] = field(
        repr=False,
        compare=False,
    )
    candidate_identifier_term_hashes_by_observation: Mapping[str, frozenset[str]] = field(
        repr=False,
        compare=False,
    )
    node_by_id: Mapping[str, _RelationProjectionNode] = field(repr=False, compare=False)
    node_by_hash: Mapping[str, _RelationProjectionNode] = field(repr=False, compare=False)
    graph_nodes_by_observation_hash: Mapping[str, tuple[GraphProjectionNode, ...]] = field(
        repr=False,
        compare=False,
    )
    adjacency: Mapping[str, tuple[_RelationProjectionTransition, ...]] = field(
        repr=False,
        compare=False,
    )
    authorized_index_vocabulary_hashes: frozenset[str]
    authorized_graph_vocabulary_hashes: frozenset[str]


@dataclass(frozen=True)
class _RelationProjectionCacheBindingSnapshot:
    """Immutable full-content binding reused before relation-base cache lookup."""

    cache_binding_fingerprint: str
    graph_revision_fingerprint: str
    index_fingerprint: str
    tokenizer_profile_fingerprint: str
    authorized_observation_set_fingerprint: str
    candidate_set_fingerprint: str
    projection_helper_object_ids: tuple[int, ...]
    index_candidates: tuple[_HybridCandidate, ...] = field(
        repr=False,
        compare=False,
    )


@dataclass(frozen=True)
class _RelationQueryProjection:
    """Immutable authorization-bound relation projection for one query only."""

    binding_fingerprint: str
    query_hash: str
    requester_user_id: str
    workspace_id: str
    source_scope_ids: tuple[str, ...]
    graph_revision_fingerprint: str
    index_fingerprint: str
    tokenizer_profile_fingerprint: str
    authorized_observation_set_fingerprint: str
    candidate_set_fingerprint: str
    relation_policy_fingerprint: str
    candidates_by_hash: Mapping[str, _HybridCandidate] = field(repr=False, compare=False)
    candidate_concept_term_hashes_by_observation: Mapping[str, frozenset[str]] = field(
        repr=False,
        compare=False,
    )
    candidate_identifier_term_hashes_by_observation: Mapping[str, frozenset[str]] = field(
        repr=False,
        compare=False,
    )
    candidate_query_slot_coverage_by_observation: Mapping[
        str,
        frozenset[tuple[str, str]],
    ] = field(
        repr=False,
        compare=False,
    )
    node_by_id: Mapping[str, _RelationProjectionNode] = field(repr=False, compare=False)
    node_by_hash: Mapping[str, _RelationProjectionNode] = field(repr=False, compare=False)
    graph_nodes_by_observation_hash: Mapping[str, tuple[GraphProjectionNode, ...]] = field(
        repr=False,
        compare=False,
    )
    adjacency: Mapping[str, tuple[_RelationProjectionTransition, ...]] = field(
        repr=False,
        compare=False,
    )
    authorized_index_vocabulary_hashes: frozenset[str]
    authorized_graph_vocabulary_hashes: frozenset[str]
    initial_query_anchor_node_ids: tuple[str, ...]
    completion_query_anchor_node_ids: tuple[str, ...]
    build_count: int = 1


@dataclass(frozen=True)
class _ExactFilterSlots:
    identifier_hashes: tuple[str, ...] = ()
    topic_hashes: tuple[str, ...] = ()

    @property
    def combined_hashes(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.identifier_hashes) | set(self.topic_hashes)))


_PARTICIPANT_LOCAL_PART_FIELDS = frozenset(
    {
        "participant.any.local_part",
        "participant.from.local_part",
        "participant.sender.local_part",
        "participant.to.local_part",
        "participant.cc.local_part",
    }
)
_RFC_DOT_ATOM_ATEXT = r"A-Za-z0-9!#$%&'*+/=?^_`{|}~\-"
_RFC_DOT_ATOM_LOCAL_PART = (
    rf"[{_RFC_DOT_ATOM_ATEXT}]+(?:\.[{_RFC_DOT_ATOM_ATEXT}]+)*"
)
_RFC_DNS_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_PARTICIPANT_ADDR_SPEC_SLOT_RE = re.compile(
    rf"(?<![{_RFC_DOT_ATOM_ATEXT}.@])"
    rf"{_RFC_DOT_ATOM_LOCAL_PART}@"
    rf"{_RFC_DNS_LABEL}(?:\.{_RFC_DNS_LABEL})+"
    rf"(?![{_RFC_DOT_ATOM_ATEXT}.@])"
)
_PARTICIPANT_LOCAL_PART_SLOT_RE = re.compile(
    rf"(?<![{_RFC_DOT_ATOM_ATEXT}.@])"
    rf"{_RFC_DOT_ATOM_LOCAL_PART}"
    rf"(?![{_RFC_DOT_ATOM_ATEXT}.@])"
)
_DISTINCTIVE_RFC_ATEXT = frozenset("!#$%&'*+/=?^`{|}~")
_SOURCE_OCCURRENCE_PROJECTION_CONNECTOR_POLICY_ID = "source_occurrence_projection_connector_v1"
_SOURCE_OCCURRENCE_PROJECTION_CONNECTORS = ("以及", "與", "和", "跟", "還有")
_SOURCE_OCCURRENCE_PROJECTION_CONNECTOR_BOUNDARY_RULE = (
    "post_unique_directional_particle_strictly_between_nonempty_projection_segments_v2")
_SOURCE_OCCURRENCE_SENTENCE_FINAL_PARTICLE_POLICY_ID = (
    "source_occurrence_sentence_final_particle_v1")
_SOURCE_OCCURRENCE_SENTENCE_FINAL_PARTICLES = ("嗎", "呢", "吧", "麼")
_SOURCE_OCCURRENCE_CONTIGUOUS_PHRASE_POLICY_ID = (
    "source_occurrence_contiguous_lexical_particle_phrase_v1")
_SOURCE_OCCURRENCE_CONTIGUOUS_PHRASE_BOUNDARY_RULE = (
    "one_term_after_prior_particle_boundary_without_control_or_sentence_final_v1")
_PRECOMPUTED_HYBRID_OBSERVATION_INDEX_ARTIFACT_ID = (
    "formowl_issue56_precomputed_hybrid_observation_index_v1"
)
_PRECOMPUTED_DENSE_VECTOR_FORMAT = "little_endian_float32_v1"
_PRECOMPUTED_DENSE_VECTOR_BYTES = 4


@dataclass(frozen=True)
class AuthorizedHybridObservationIndexArtifact:
    """Sealed manifest plus compact private dense-vector payload."""

    source_access_fingerprint: str
    source_session_binding_fingerprint: str
    snippet_index_fingerprint: str
    graph_revision_fingerprint: str
    tokenizer_id: str
    profile_fingerprint: str
    dense_encoder_id: str
    dense_profile_fingerprint: str
    dense_model_id: str
    dense_model_revision: str
    execution_component_fingerprint: str
    index_fingerprint: str
    dense_vector_payload_fingerprint: str
    dense_vector_bindings: tuple[tuple[str, str], ...] = field(repr=False)
    _dense_vector_payload: bytes = field(repr=False, compare=False)

    @property
    def artifact_fingerprint(self) -> str:
        return sha256_json(self._fingerprint_payload())

    @property
    def dense_vector_payload(self) -> bytes:
        return self._dense_vector_payload

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": _PRECOMPUTED_HYBRID_OBSERVATION_INDEX_ARTIFACT_ID,
            "source_access_fingerprint": self.source_access_fingerprint,
            "source_session_binding_fingerprint": self.source_session_binding_fingerprint,
            "snippet_index_fingerprint": self.snippet_index_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "tokenizer_id": self.tokenizer_id,
            "profile_fingerprint": self.profile_fingerprint,
            "dense_encoder_id": self.dense_encoder_id,
            "dense_profile_fingerprint": self.dense_profile_fingerprint,
            "dense_model_id": self.dense_model_id,
            "dense_model_revision": self.dense_model_revision,
            "execution_component_fingerprint": self.execution_component_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "dense_vector_format": _PRECOMPUTED_DENSE_VECTOR_FORMAT,
            "dense_vector_dimension": ISSUE56_TARGET_DENSE_DIMENSION,
            "dense_vector_count": len(self.dense_vector_bindings),
            "dense_vector_payload_size_bytes": len(self._dense_vector_payload),
            "dense_vector_payload_fingerprint": self.dense_vector_payload_fingerprint,
            "dense_vector_bindings": [
                {
                    "source_observation_hash": observation_hash,
                    "dense_evidence_text_hash": text_hash,
                }
                for observation_hash, text_hash in self.dense_vector_bindings
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._fingerprint_payload()
        payload["artifact_fingerprint"] = self.artifact_fingerprint
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        dense_vector_payload: bytes,
        expected_artifact_fingerprint: str,
    ) -> AuthorizedHybridObservationIndexArtifact:
        plain = to_plain(payload)
        expected_keys = {
            "artifact_id",
            "source_access_fingerprint",
            "source_session_binding_fingerprint",
            "snippet_index_fingerprint",
            "graph_revision_fingerprint",
            "tokenizer_id",
            "profile_fingerprint",
            "dense_encoder_id",
            "dense_profile_fingerprint",
            "dense_model_id",
            "dense_model_revision",
            "execution_component_fingerprint",
            "index_fingerprint",
            "dense_vector_format",
            "dense_vector_dimension",
            "dense_vector_count",
            "dense_vector_payload_size_bytes",
            "dense_vector_payload_fingerprint",
            "dense_vector_bindings",
            "artifact_fingerprint",
        }
        if (
            not isinstance(plain, dict)
            or set(plain) != expected_keys
            or plain.get("artifact_id")
            != _PRECOMPUTED_HYBRID_OBSERVATION_INDEX_ARTIFACT_ID
        ):
            raise ContractValidationError("precomputed hybrid index artifact schema mismatch")
        bindings = plain.get("dense_vector_bindings")
        if not isinstance(bindings, list):
            raise ContractValidationError("precomputed hybrid index vector bindings are invalid")
        parsed_bindings: list[tuple[str, str]] = []
        for binding in bindings:
            if not isinstance(binding, dict) or set(binding) != {
                "source_observation_hash",
                "dense_evidence_text_hash",
            }:
                raise ContractValidationError(
                    "precomputed hybrid index vector binding is invalid"
                )
            parsed_bindings.append(
                (
                    binding.get("source_observation_hash"),
                    binding.get("dense_evidence_text_hash"),
                )
            )
        if not isinstance(dense_vector_payload, bytes):
            raise ContractValidationError("precomputed hybrid index vector payload is invalid")
        artifact = cls(
            source_access_fingerprint=plain.get("source_access_fingerprint"),
            source_session_binding_fingerprint=plain.get(
                "source_session_binding_fingerprint"
            ),
            snippet_index_fingerprint=plain.get("snippet_index_fingerprint"),
            graph_revision_fingerprint=plain.get("graph_revision_fingerprint"),
            tokenizer_id=plain.get("tokenizer_id"),
            profile_fingerprint=plain.get("profile_fingerprint"),
            dense_encoder_id=plain.get("dense_encoder_id"),
            dense_profile_fingerprint=plain.get("dense_profile_fingerprint"),
            dense_model_id=plain.get("dense_model_id"),
            dense_model_revision=plain.get("dense_model_revision"),
            execution_component_fingerprint=plain.get(
                "execution_component_fingerprint"
            ),
            index_fingerprint=plain.get("index_fingerprint"),
            dense_vector_payload_fingerprint=plain.get(
                "dense_vector_payload_fingerprint"
            ),
            dense_vector_bindings=tuple(parsed_bindings),
            _dense_vector_payload=dense_vector_payload,
        )
        _validate_precomputed_hybrid_observation_index_artifact(
            artifact,
            expected_artifact_fingerprint=expected_artifact_fingerprint,
        )
        if (
            plain.get("artifact_fingerprint") != artifact.artifact_fingerprint
            or plain.get("dense_vector_format") != _PRECOMPUTED_DENSE_VECTOR_FORMAT
            or plain.get("dense_vector_dimension") != ISSUE56_TARGET_DENSE_DIMENSION
            or plain.get("dense_vector_count") != len(parsed_bindings)
            or plain.get("dense_vector_payload_size_bytes")
            != len(dense_vector_payload)
            or plain.get("dense_vector_payload_fingerprint")
            != sha256_prefixed(dense_vector_payload)
        ):
            raise ContractValidationError("precomputed hybrid index artifact seal mismatch")
        return artifact


@dataclass(frozen=True)
class AuthorizedHybridMailIndex:
    tokenizer_id: str
    profile_fingerprint: str
    index_fingerprint: str
    dense_encoder_id: str
    dense_encoder_status: str
    dense_profile_fingerprint: str
    dense_model_id: str
    dense_model_revision: str
    execution_component_fingerprint: str
    selected_bundle_count: int
    authorized_bundle_count: int
    denied_bundle_count: int
    candidates: tuple[_HybridCandidate, ...] = field(repr=False)
    document_frequency: tuple[tuple[str, int], ...] = field(repr=False)
    average_document_length: float = field(repr=False)
    _relation_projection_candidates_snapshot: tuple[_HybridCandidate, ...] = field(
        repr=False,
        compare=False,
    )
    _integrity_fingerprint: str = field(repr=False, compare=False)
    _runtime_components: Issue56TargetRuntimeComponents = field(
        repr=False,
        compare=False,
    )
    _precomputed_graph_revision_fingerprint: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def query(
        self,
        *,
        query_text: str,
        query_class: str,
        candidate_limit: int = 12,
        result_limit: int = 5,
        execution_deadline: _QueryExecutionDeadline | None = None,
    ) -> GovernedHybridRagResult:
        _query_deadline_checkpoint(execution_deadline)
        _validate_hybrid_index_runtime(self)
        tokenizer_profile = self._runtime_components.tokenizer_profile
        dense_encoder = self._runtime_components.dense_encoder
        _validate_hybrid_query_inputs(
            query_text=query_text,
            query_class=query_class,
            candidate_limit=candidate_limit,
            result_limit=result_limit,
        )
        query_hash = sha256_json(query_text)
        if query_class in _BLOCKED_QUERY_CLASSES:
            return _route_blocked_result(
                query_hash=query_hash,
                query_class=query_class,
                runtime_components=self._runtime_components,
                selected_bundle_count=self.selected_bundle_count,
                authorized_bundle_count=self.authorized_bundle_count,
                denied_bundle_count=self.denied_bundle_count,
            )
        if query_class != _SUPPORTED_QUERY_CLASS:
            raise ContractValidationError("unsupported issue56 query class")
        if self.authorized_bundle_count == 0:
            status = "permission_denied" if self.denied_bundle_count else "not_found"
            warning = (
                "mail_evidence_permission_denied"
                if status == "permission_denied"
                else "mail_evidence_not_found"
            )
            return GovernedHybridRagResult(
                artifact_id="formowl_issue56_governed_hybrid_rag_result_v1",
                status=status,
                runtime_method_id=ISSUE56_TARGET_RUNTIME_METHOD_ID,
                runtime_method_fingerprint=ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
                query_hash=query_hash,
                query_class=query_class,
                candidate_profile_id=self.tokenizer_id,
                profile_fingerprint=self.profile_fingerprint,
                index_fingerprint=self.index_fingerprint,
                dense_encoder_id=self.dense_encoder_id,
                dense_encoder_status=self.dense_encoder_status,
                dense_profile_fingerprint=self.dense_profile_fingerprint,
                dense_model_id=self.dense_model_id,
                dense_model_revision=self.dense_model_revision,
                execution_component_fingerprint=(self.execution_component_fingerprint),
                selected_bundle_count=self.selected_bundle_count,
                authorized_bundle_count=self.authorized_bundle_count,
                denied_bundle_count=self.denied_bundle_count,
                materialized_candidate_count=0,
                retrieved_candidate_count=0,
                result_bundle_count=0,
                exact_executor_status="not_requested",
                warnings=(warning,),
            )

        query_analysis = tokenizer_profile.analyze(query_text)
        _query_deadline_checkpoint(execution_deadline)
        query_tokens = frozenset(query_analysis.tokens)
        if not query_tokens:
            return _no_answer_result(
                index=self,
                query_hash=query_hash,
                query_class=query_class,
                warning="query_has_no_admitted_tokens",
            )
        proof_slots = _deterministic_high_idf_proof_slots(
            query_text,
            query_class=query_class,
            tokenizer_profile=tokenizer_profile,
            document_frequency=dict(self.document_frequency),
            document_count=len(self.candidates),
        )
        _query_deadline_checkpoint(execution_deadline)
        if proof_slots is None:
            return _no_answer_result(
                index=self,
                query_hash=query_hash,
                query_class=query_class,
                warning="query_concept_not_in_authorized_index",
            )
        query_vector = dense_encoder.encode_query(query_text)
        _query_deadline_checkpoint(execution_deadline)
        bm25_scores = self._bm25_scores(
            query_tokens,
            execution_deadline=execution_deadline,
        )
        dense_scores: list[float] = []
        for candidate in self.candidates:
            _query_deadline_checkpoint(execution_deadline)
            dense_scores.append(_cosine_similarity(query_vector, candidate.dense_vector))
        _query_deadline_checkpoint(execution_deadline)
        bm25_ranks = _positive_ranks(bm25_scores)
        _query_deadline_checkpoint(execution_deadline)
        dense_ranks = _positive_ranks(dense_scores)
        _query_deadline_checkpoint(execution_deadline)
        selected_candidate_indexes = set(
            _top_ranked_indexes(
                bm25_scores,
                candidate_limit,
            )
        )
        selected_candidate_indexes.update(
            _top_ranked_indexes(
                dense_scores,
                candidate_limit,
            )
        )
        if not selected_candidate_indexes:
            return _no_answer_result(
                index=self,
                query_hash=query_hash,
                query_class=query_class,
                warning="no_authorized_hybrid_candidates",
            )

        grouped: dict[str, list[tuple[int, HybridRagCandidateScore]]] = {}
        admitted_candidate_scores: list[HybridRagCandidateScore] = []
        for candidate_index in sorted(selected_candidate_indexes):
            _query_deadline_checkpoint(execution_deadline)
            candidate = self.candidates[candidate_index]
            bm25_rank = bm25_ranks.get(candidate_index)
            dense_rank = dense_ranks.get(candidate_index)
            fusion_score = (1.0 / (_RRF_K + bm25_rank) if bm25_rank is not None else 0.0) + (
                1.0 / (_RRF_K + dense_rank) if dense_rank is not None else 0.0
            )
            if fusion_score <= 0.0:
                continue
            candidate_score = HybridRagCandidateScore(
                source_observation_hash=candidate.source_observation_hash,
                message_hash=candidate.message_hash,
                bm25_score=_metric(bm25_scores[candidate_index]),
                dense_score=_metric(max(0.0, dense_scores[candidate_index])),
                bm25_rank=bm25_rank,
                dense_rank=dense_rank,
                fusion_score=_metric(fusion_score),
            )
            admitted_candidate_scores.append(candidate_score)
            grouped.setdefault(candidate.coherence_group_hash, []).append(
                (
                    candidate_index,
                    candidate_score,
                )
            )
        ordered_admitted_candidate_scores = tuple(
            sorted(
                admitted_candidate_scores,
                key=lambda item: (
                    -item.fusion_score,
                    item.source_observation_hash,
                    item.message_hash,
                ),
            )
        )

        bundle_results: list[HybridRagBundleScore] = []
        coverage_tokens_by_group_hash: dict[str, frozenset[str]] = {}
        protected_tokens_by_group_hash: dict[str, frozenset[str]] = {}
        for coherence_group_hash, grouped_candidates in grouped.items():
            _query_deadline_checkpoint(execution_deadline)
            candidate_indexes = [item[0] for item in grouped_candidates]
            candidates = [self.candidates[index] for index in candidate_indexes]
            union_tokens = frozenset().union(
                *(candidate.searchable_tokens for candidate in candidates)
            )
            coverage_score = len(query_tokens & union_tokens) / len(query_tokens)
            if coverage_score <= 0.0:
                continue
            observation_union_tokens = frozenset().union(
                *(candidate.observation_tokens for candidate in candidates)
            )
            observation_union_protected_tokens = frozenset().union(
                *(candidate.observation_protected_identifier_tokens for candidate in candidates)
            )
            coverage_tokens_by_group_hash[coherence_group_hash] = (
                proof_slots.topic_tokens & observation_union_tokens
            )
            protected_tokens_by_group_hash[coherence_group_hash] = (
                proof_slots.identifier_tokens & observation_union_protected_tokens
            )
            message_hashes = {candidate.message_hash for candidate in candidates}
            multi_message_score = min(len(message_hashes), 3) / 3.0
            candidate_metrics = tuple(
                sorted(
                    (item[1] for item in grouped_candidates),
                    key=lambda item: (
                        -item.fusion_score,
                        item.source_observation_hash,
                    ),
                )
            )
            bm25_score = sum(item.bm25_score for item in candidate_metrics)
            dense_score = sum(item.dense_score for item in candidate_metrics)
            fusion_score = sum(item.fusion_score for item in candidate_metrics)
            rerank_score = fusion_score + (0.10 * coverage_score) + (0.02 * multi_message_score)
            bundle_results.append(
                HybridRagBundleScore(
                    evidence_bundle_hash=coherence_group_hash,
                    evidence_count=len(candidates),
                    unique_message_count=len(message_hashes),
                    source_observation_hashes=tuple(
                        sorted(candidate.source_observation_hash for candidate in candidates)
                    ),
                    matched_protected_identifier_hashes=tuple(
                        sorted(
                            sha256_json(token)
                            for token in (
                                proof_slots.identifier_tokens & observation_union_protected_tokens
                            )
                        )
                    ),
                    bm25_score=_metric(bm25_score),
                    dense_score=_metric(dense_score),
                    fusion_score=_metric(fusion_score),
                    query_coverage_score=_metric(coverage_score),
                    multi_message_score=_metric(multi_message_score),
                    rerank_score=_metric(rerank_score),
                    candidate_scores=candidate_metrics,
                )
            )
        ranked_bundle_results = tuple(
            sorted(
                bundle_results,
                key=lambda item: (-item.rerank_score, item.evidence_bundle_hash),
            )
        )
        _query_deadline_checkpoint(execution_deadline)
        ordered_results = _select_coherent_bundle_results(
            ranked_bundle_results,
            proof_slots=proof_slots,
            coverage_tokens_by_group_hash=coverage_tokens_by_group_hash,
            protected_tokens_by_group_hash=protected_tokens_by_group_hash,
            result_limit=result_limit,
        )
        if not ordered_results:
            return _no_answer_result(
                index=self,
                query_hash=query_hash,
                query_class=query_class,
                warning="no_authorized_hybrid_evidence_matched",
                retrieved_candidate_count=len(selected_candidate_indexes),
                admitted_candidate_scores=ordered_admitted_candidate_scores,
            )
        answer_citation_hashes = _minimal_hybrid_answer_citation_hashes(
            ordered_results=ordered_results,
            candidates=self.candidates,
            proof_slots=proof_slots,
            evidence_budget=result_limit,
            execution_deadline=execution_deadline,
        )
        if not answer_citation_hashes:
            return _no_answer_result(
                index=self,
                query_hash=query_hash,
                query_class=query_class,
                warning="no_authorized_observation_level_proof",
                retrieved_candidate_count=len(selected_candidate_indexes),
                admitted_candidate_scores=ordered_admitted_candidate_scores,
            )
        result = GovernedHybridRagResult(
            artifact_id="formowl_issue56_governed_hybrid_rag_result_v1",
            status="ok",
            runtime_method_id=ISSUE56_TARGET_RUNTIME_METHOD_ID,
            runtime_method_fingerprint=ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
            query_hash=query_hash,
            query_class=query_class,
            candidate_profile_id=self.tokenizer_id,
            profile_fingerprint=self.profile_fingerprint,
            index_fingerprint=self.index_fingerprint,
            dense_encoder_id=self.dense_encoder_id,
            dense_encoder_status=self.dense_encoder_status,
            dense_profile_fingerprint=self.dense_profile_fingerprint,
            dense_model_id=self.dense_model_id,
            dense_model_revision=self.dense_model_revision,
            execution_component_fingerprint=self.execution_component_fingerprint,
            selected_bundle_count=self.selected_bundle_count,
            authorized_bundle_count=self.authorized_bundle_count,
            denied_bundle_count=self.denied_bundle_count,
            materialized_candidate_count=len(self.candidates),
            retrieved_candidate_count=len(selected_candidate_indexes),
            result_bundle_count=len(ordered_results),
            exact_executor_status="not_requested",
            results=ordered_results,
            admitted_candidate_scores=ordered_admitted_candidate_scores,
            answer_citation_hashes=answer_citation_hashes,
            warnings=(),
        )
        result.to_safe_dict()
        _query_deadline_checkpoint(execution_deadline)
        return result

    def _bm25_scores(
        self,
        query_tokens: frozenset[str],
        *,
        execution_deadline: _QueryExecutionDeadline | None = None,
    ) -> list[float]:
        document_frequency = dict(self.document_frequency)
        document_count = len(self.candidates)
        average_document_length = max(self.average_document_length, 1.0)
        scores: list[float] = []
        for candidate in self.candidates:
            _query_deadline_checkpoint(execution_deadline)
            document_length = max(len(candidate.searchable_tokens), 1)
            score = 0.0
            for token in query_tokens:
                _query_deadline_checkpoint(execution_deadline)
                if token not in candidate.searchable_tokens:
                    continue
                frequency = document_frequency.get(token, 0)
                inverse_document_frequency = math.log(
                    1.0 + ((document_count - frequency + 0.5) / (frequency + 0.5))
                )
                term_frequency = 1.0
                denominator = term_frequency + 1.2 * (
                    1.0 - 0.75 + 0.75 * document_length / average_document_length
                )
                score += inverse_document_frequency * (term_frequency * (1.2 + 1.0) / denominator)
            scores.append(score)
        return scores


@dataclass(frozen=True)
class AuthorizedSemanticMailSession:
    """Statically auditable compatibility session over authorized semantic evidence."""

    index: AuthorizedHybridMailIndex
    requester_user_id: str
    workspace_id: str
    selected_source_scope_ids: tuple[str, ...]
    authorized_source_scope_ids: tuple[str, ...]
    retrieval_observation_hashes: tuple[tuple[str, str], ...] = field(
        repr=False,
    )
    authorized_observation_hashes: tuple[tuple[str, str], ...] = field(
        repr=False,
    )
    authorized_source: AuthorizedSemanticSource | None = field(
        default=None,
        repr=False,
    )
    authorized_observations: tuple[Observation, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    occurrence_lineages: tuple[SourceOccurrenceLineage, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    source_session_binding_fingerprint: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    source_occurrence_providers: tuple[SourceOccurrenceProvider, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    _source_occurrence_provider_provenance_seal: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def query(
        self,
        *,
        query_text: str,
        effective_graph_view: EffectiveGraphView,
        allowed_relation_types: Sequence[str] = (),
        allowed_directions: Sequence[str] = ("out",),
        seed_node_ids: Sequence[str] = (),
        target_core_supertype_id: str | None = None,
        exact_inventory_kind: str | None = None,
        exact_field: str | None = None,
        page_size: int = 20,
        cursor: str | None = None,
        limits: SemanticPlanLimits = DEFAULT_SEMANTIC_PLAN_LIMITS,
        enable_entity_signal: bool = True,
        enable_graph_traversal: bool = True,
        legacy_hard_gate: bool = False,
        phase_trace: SemanticPhaseTrace | None = None,
    ) -> GovernedSemanticExecutionResult:
        """Run one typed plan without rebuilding or widening the authorized index."""

        source_validation_started_at_ns: int | None = None
        if phase_trace is not None:
            if not isinstance(phase_trace, SemanticPhaseTrace):
                raise ContractValidationError("semantic phase trace type is invalid")
            phase_trace._begin_query()
            source_validation_started_at_ns = phase_trace._start_phase("source_session_validation")
        typed_exact_intent = any(
            isinstance(value, str) and value.strip()
            for value in (exact_inventory_kind, exact_field)
        )
        typed_exact_inventory_kind = (
            isinstance(exact_inventory_kind, str)
            and bool(exact_inventory_kind.strip())
        )
        typed_source_occurrence_kind = typed_exact_inventory_kind and any(
            exact_inventory_kind
            in {provider.inventory_kind_alias, provider.resource_kind}
            for provider in self.source_occurrence_providers
        )
        query_class = (
            "exact_set_or_inventory"
            if typed_exact_intent
            else deterministic_query_class(query_text)
        )
        try:
            _validate_hybrid_query_inputs(
                query_text=query_text,
                query_class=query_class,
                candidate_limit=max(1, min(12, limits.max_candidates)),
                result_limit=max(1, min(5, limits.max_results)),
            )
            (
                _validate_hybrid_index_runtime_binding(self.index)
                if typed_source_occurrence_kind
                else _validate_hybrid_index_runtime(self.index)
            )
            if effective_graph_view.requester_user_id != self.requester_user_id:
                raise ContractValidationError("effective graph requester mismatch")
        except Exception:
            if phase_trace is not None and source_validation_started_at_ns is not None:
                phase_trace._finish_phase(
                    phase="source_session_validation",
                    started_at_ns=source_validation_started_at_ns,
                    outcome="failed",
                )
                phase_trace._finish_query("failed")
            raise
        if not self.selected_source_scope_ids:
            if phase_trace is not None and source_validation_started_at_ns is not None:
                phase_trace._finish_phase(
                    phase="source_session_validation",
                    started_at_ns=source_validation_started_at_ns,
                    outcome="completed",
                )
            graph_revision_fingerprint = (
                _graph_revision_fingerprint(effective_graph_view)
                if phase_trace is None
                else _run_unbudgeted_traced_phase(
                    phase_trace=phase_trace,
                    phase="graph_snapshot",
                    operation=lambda: _graph_revision_fingerprint(effective_graph_view),
                )
            )
            result = _empty_semantic_execution_result(
                status="not_found",
                query_text=query_text,
                query_class=query_class,
                runtime_components=self.index._runtime_components,
                graph_revision_fingerprint=graph_revision_fingerprint,
                selected_bundle_count=0,
                authorized_bundle_count=0,
                denied_bundle_count=0,
                warning="mail_evidence_not_found",
            )
            if phase_trace is not None:
                phase_trace._finish_query("completed")
            return result
        if not self.authorized_source_scope_ids:
            if phase_trace is not None and source_validation_started_at_ns is not None:
                phase_trace._finish_phase(
                    phase="source_session_validation",
                    started_at_ns=source_validation_started_at_ns,
                    outcome="completed",
                )
            graph_revision_fingerprint = (
                _graph_revision_fingerprint(effective_graph_view)
                if phase_trace is None
                else _run_unbudgeted_traced_phase(
                    phase_trace=phase_trace,
                    phase="graph_snapshot",
                    operation=lambda: _graph_revision_fingerprint(effective_graph_view),
                )
            )
            result = _empty_semantic_execution_result(
                status="permission_denied",
                query_text=query_text,
                query_class=query_class,
                runtime_components=self.index._runtime_components,
                graph_revision_fingerprint=graph_revision_fingerprint,
                selected_bundle_count=len(self.selected_source_scope_ids),
                authorized_bundle_count=0,
                denied_bundle_count=len(self.selected_source_scope_ids),
                warning="mail_evidence_permission_denied",
            )
            if phase_trace is not None:
                phase_trace._finish_query("completed")
            return result
        deadline = _QueryExecutionDeadline.start(
            budget_ms=min(1_500, limits.max_time_budget_ms),
        )
        try:
            source_binding_validation = _run_before_query_deadline(
                deadline,
                lambda: _validate_source_neutral_query_session(
                    session=self,
                    effective_graph_view=effective_graph_view,
                    execution_deadline=deadline,
                ),
            )
        except Exception:
            if phase_trace is not None and source_validation_started_at_ns is not None:
                phase_trace._finish_phase(
                    phase="source_session_validation",
                    started_at_ns=source_validation_started_at_ns,
                    outcome="failed",
                )
                phase_trace._finish_query("failed")
            raise
        if phase_trace is not None and source_validation_started_at_ns is not None:
            phase_trace._finish_phase(
                phase="source_session_validation",
                started_at_ns=source_validation_started_at_ns,
                outcome=(
                    "deadline_exhausted"
                    if source_binding_validation is _TIME_BUDGET_EXHAUSTED
                    else "completed"
                ),
            )
        if source_binding_validation is _TIME_BUDGET_EXHAUSTED:
            result = _time_budget_exhausted_semantic_result(
                query_text=query_text,
                query_class=query_class,
                plan=None,
                index=self.index,
                graph_revision_fingerprint=_graph_revision_pin_fingerprint(effective_graph_view),
            )
            if phase_trace is not None:
                phase_trace._finish_query("deadline_exhausted")
            return result
        graph_snapshot = _run_traced_query_phase(
            deadline=deadline,
            phase_trace=phase_trace,
            phase="graph_snapshot",
            operation=lambda: _build_query_graph_snapshot(effective_graph_view),
        )
        if graph_snapshot is _TIME_BUDGET_EXHAUSTED:
            result = _time_budget_exhausted_semantic_result(
                query_text=query_text,
                query_class=query_class,
                plan=None,
                index=self.index,
                graph_revision_fingerprint=_graph_revision_pin_fingerprint(effective_graph_view),
            )
            if phase_trace is not None:
                phase_trace._finish_query("deadline_exhausted")
            return result
        assert isinstance(graph_snapshot, _QueryGraphSnapshot)
        graph_revision_fingerprint = graph_snapshot.graph_revision_fingerprint
        routing_started_at_ns = (
            phase_trace._start_phase("routing_plan") if phase_trace is not None else None
        )
        exact_routing_inputs = _run_before_query_deadline(
            deadline,
            lambda: (
                (
                    _deterministic_exact_filter_slots(
                        query_text,
                        tokenizer_profile=self.index._runtime_components.tokenizer_profile,
                        exact_inventory_kind=exact_inventory_kind,
                        exact_field=exact_field,
                    )
                    if query_class in {"exact_set_or_inventory", "evidence_lookup"}
                    else _ExactFilterSlots()
                ),
                (
                    any(
                        query_identifier_tokens & candidate.protected_identifier_tokens
                        or query_identifier_tokens & candidate.observation_protected_identifier_tokens
                        for candidate in self.index.candidates
                    )
                    if query_class == "evidence_lookup"
                    and (
                        query_identifier_tokens := _query_evidence_slots(query_text, query_class=query_class, tokenizer_profile=self.index._runtime_components.tokenizer_profile).identifier_tokens
                    )
                    else None
                ),
            ),
        )
        if exact_routing_inputs is _TIME_BUDGET_EXHAUSTED:
            if phase_trace is not None and routing_started_at_ns is not None:
                phase_trace._finish_phase(
                    phase="routing_plan",
                    started_at_ns=routing_started_at_ns,
                    outcome="deadline_exhausted",
                )
            result = _time_budget_exhausted_semantic_result(
                query_text=query_text,
                query_class=query_class,
                plan=None,
                index=self.index,
                graph_revision_fingerprint=graph_revision_fingerprint,
            )
            if phase_trace is not None:
                phase_trace._finish_query("deadline_exhausted")
            return result
        exact_slots, authorized_identifier_present = exact_routing_inputs
        assert isinstance(exact_slots, _ExactFilterSlots)
        exact_provider: SourceOccurrenceProvider | None = None
        exact_value_hashes: tuple[str, ...] = ()
        exact_projection_hashes: tuple[str, ...] = ()
        exact_unsupported_projection_hashes: tuple[str, ...] = ()
        exact_partition: SourceOccurrenceQueryPartition | None = None
        exact_grammar_term_ledger: tuple[tuple[str, str], ...] = ()
        exact_grammar_policy_fingerprint: str | None = None
        identifier_provider_candidate_present = any(
            provider.filter_slot_policy == "identifier_union_v1"
            and set(exact_slots.identifier_hashes).intersection(
                provider._value_hash_postings
            )
            for provider in self.source_occurrence_providers
        )
        combined_providers = tuple(
            provider
            for provider in self.source_occurrence_providers
            if provider.filter_slot_policy
            == "combined_present_intersection_v1"
        )
        structured_provider_bindings: dict[
            str,
            tuple[
                SourceOccurrenceQueryPartition,
                tuple[tuple[str, str], ...],
                tuple[str, ...],
            ],
        ] = {}
        if combined_providers:
            (
                ordered_query_terms,
                exact_grammar_policy_fingerprint,
            ) = _ordered_source_occurrence_query_grounding(
                query_text,
                tokenizer_profile=(
                    self.index._runtime_components.tokenizer_profile
                ),
            )
            for provider in combined_providers:
                if not any(
                    control_kind == "none"
                    and grammar_role in {"lexical", "operator"}
                    and any(
                        candidate_hash in provider._value_candidate_columns
                        or candidate_hash
                        in provider._projection_candidate_columns
                        for candidate_hash in candidate_hashes
                    )
                    for (
                        _term_hash,
                        grammar_role,
                        candidate_hashes,
                        control_kind,
                    ) in ordered_query_terms
                ):
                    continue
                binding = _partition_source_occurrence_query_grounding(
                    provider=provider,
                    ordered_terms=ordered_query_terms,
                )
                if binding[2] and len(combined_providers) != 1:
                    raise ContractValidationError(
                        "source occurrence provider selection is ambiguous"
                    )
                structured_provider_bindings[provider.provider_fingerprint] = binding
            identifier_not_found_warning: str | None = None
            if (
                not structured_provider_bindings
                and not identifier_provider_candidate_present
                and exact_slots.identifier_hashes
                and not typed_exact_intent
                and cursor is None
            ):
                if query_class == "exact_set_or_inventory":
                    identifier_not_found_warning = (
                        _SOURCE_OCCURRENCE_IDENTIFIER_NOT_FOUND_WARNING
                    )
                elif (
                    query_class == "evidence_lookup"
                    and authorized_identifier_present is False
                ):
                    identifier_not_found_warning = (
                        _AUTHORIZED_EVIDENCE_IDENTIFIER_NOT_FOUND_WARNING
                    )
            if identifier_not_found_warning is not None:
                if phase_trace is not None and routing_started_at_ns is not None:
                    phase_trace._finish_phase(
                        phase="routing_plan",
                        started_at_ns=routing_started_at_ns,
                        outcome="completed",
                    )
                result = _empty_semantic_execution_result(
                    status="incomplete",
                    query_text=query_text,
                    query_class=query_class,
                    runtime_components=self.index._runtime_components,
                    graph_revision_fingerprint=graph_revision_fingerprint,
                    selected_bundle_count=self.index.selected_bundle_count,
                    authorized_bundle_count=self.index.authorized_bundle_count,
                    denied_bundle_count=self.index.denied_bundle_count,
                    warning=identifier_not_found_warning,
                )
                if identifier_not_found_warning == _AUTHORIZED_EVIDENCE_IDENTIFIER_NOT_FOUND_WARNING:
                    result = replace(
                        result,
                        index_fingerprint=self.index.index_fingerprint,
                        materialized_candidate_count=len(self.index.candidates),
                        result_fingerprint=sha256_json([result.result_fingerprint, self.index.index_fingerprint, len(self.index.candidates)]),
                    )
                    result.to_safe_dict()
                if phase_trace is not None:
                    phase_trace._finish_query("completed")
                return result
            if (
                not structured_provider_bindings
                and not identifier_provider_candidate_present
                and not (query_class == "evidence_lookup" and exact_slots.identifier_hashes and not typed_exact_intent and cursor is None)
                and any(
                    control_kind == "none" and grammar_role == "particle"
                    for (
                        _term_hash,
                        grammar_role,
                        _candidate_hashes,
                        control_kind,
                    ) in ordered_query_terms
                )
            ):
                raise ContractValidationError(
                    "source occurrence query candidate binding is incomplete"
                )
            if (
                query_class != "exact_set_or_inventory"
                and not typed_exact_intent
                and len(structured_provider_bindings) == 1
            ):
                query_class = "exact_set_or_inventory"
        if query_class == "exact_set_or_inventory" and self.source_occurrence_providers:
            if typed_exact_inventory_kind:
                typed_providers = tuple(
                    provider
                    for provider in self.source_occurrence_providers
                    if exact_inventory_kind
                    in {provider.inventory_kind_alias, provider.resource_kind}
                    and (
                        exact_field is None
                        or provider.normalized_field == exact_field
                    )
                )
                providers_list = []
                for provider in typed_providers:
                    if provider.filter_slot_policy == "identifier_union_v1":
                        providers_list.append(provider)
                        continue
                    if (
                        provider.provider_fingerprint
                        in structured_provider_bindings
                    ):
                        providers_list.append(provider)
                providers = tuple(providers_list)
            else:
                providers_list: list[SourceOccurrenceProvider] = []
                for provider in self.source_occurrence_providers:
                    if (
                        exact_field is not None
                        and provider.normalized_field != exact_field
                    ):
                        continue
                    if provider.filter_slot_policy == "identifier_union_v1":
                        if set(exact_slots.identifier_hashes).intersection(
                            provider._value_hash_postings
                        ):
                            providers_list.append(provider)
                        continue
                    if (
                        provider.provider_fingerprint
                        in structured_provider_bindings
                    ):
                        providers_list.append(provider)
                providers = tuple(providers_list)
                providers = _prefer_untyped_participant_any_provider(
                    providers,
                    identifier_hashes=exact_slots.identifier_hashes,
                )
            if not providers:
                raise ContractValidationError("source occurrence provider selection is invalid")
            if len(providers) > 1:
                raise ContractValidationError(
                    "source occurrence provider selection is ambiguous"
                )
            exact_provider = providers[0]
            if exact_provider.filter_slot_policy == "identifier_union_v1":
                exact_value_hashes = exact_slots.identifier_hashes
            else:
                (
                    exact_partition,
                    exact_grammar_term_ledger,
                    exact_unsupported_projection_hashes,
                ) = structured_provider_bindings[
                    exact_provider.provider_fingerprint
                ]
                exact_value_hashes = (
                    exact_partition.filter_term_hashes
                )
                exact_projection_hashes = (
                    exact_partition.projection_column_hashes
                )
            _require_source_occurrence_provider_provenance(
                session=self,
                selected_provider=exact_provider,
            )
        if (
            isinstance(exact_field, str)
            and exact_field.strip()
            and exact_provider is None
        ):
            raise ContractValidationError("source occurrence provider selection is invalid")
        if cursor is not None and exact_provider is None:
            raise ContractValidationError("source occurrence cursor has no registered provider")
        plan = _run_before_query_deadline(
            deadline,
            lambda: route_semantic_query(
                query_text=query_text,
                requester_user_id=self.requester_user_id,
                workspace_id=self.workspace_id,
                source_scope_ids=self.authorized_source_scope_ids,
                effective_graph_view=effective_graph_view,
                allowed_relation_types=allowed_relation_types,
                allowed_directions=allowed_directions,
                seed_node_ids=seed_node_ids,
                target_core_supertype_id=target_core_supertype_id,
                exact_inventory_kind=(
                    exact_provider.resource_kind if exact_provider is not None else exact_inventory_kind
                ),
                exact_filter_term_hashes=(
                    (
                        exact_value_hashes
                        if exact_provider.filter_slot_policy == "identifier_union_v1"
                        else exact_value_hashes
                    )
                    if exact_provider is not None
                    else exact_slots.combined_hashes
                ),
                exact_projection_term_hashes=(
                    exact_projection_hashes if exact_provider is not None else ()
                ),
                exact_column_value_hash_pairs=(
                    exact_partition.column_value_hash_pairs
                    if exact_partition is not None
                    else ()
                ),
                exact_lexical_term_ledger=(
                    exact_partition.lexical_term_ledger
                    if exact_partition is not None
                    else ()
                ),
                exact_grammar_term_ledger=(
                    exact_grammar_term_ledger
                    if exact_partition is not None
                    else ()
                ),
                exact_grammar_policy_fingerprint=(
                    exact_grammar_policy_fingerprint
                    if exact_partition is not None
                    else None
                ),
                exact_source_occurrence_provider_fingerprint=(
                    exact_provider.provider_fingerprint
                    if exact_partition is not None
                    else None
                ),
                exact_identifier_term_hashes=(
                    (
                        exact_slots.identifier_hashes
                        if exact_provider is None
                        or exact_provider.filter_slot_policy == "identifier_union_v1"
                        else tuple(
                            sorted(
                                set(exact_slots.identifier_hashes)
                                .intersection(exact_value_hashes)
                            )
                        )
                    )
                    if query_class == "exact_set_or_inventory"
                    else ()
                ),
                exact_topic_term_hashes=(
                    (
                        ()
                        if exact_provider.filter_slot_policy == "identifier_union_v1"
                        else exact_value_hashes
                    )
                    if exact_provider is not None
                    else (
                        exact_slots.topic_hashes
                        if query_class == "exact_set_or_inventory"
                        else ()
                    )
                ),
                exact_normalized_field=(
                    exact_provider.normalized_field if exact_provider is not None else None
                ),
                exact_predicate=exact_provider.predicate if exact_provider is not None else None,
                exact_operator=exact_provider.operator if exact_provider is not None else None,
                limits=limits,
                authorized_source=self.authorized_source,
                **({"query_class_override": query_class} if exact_provider is not None else {}),
            ),
        )
        if phase_trace is not None and routing_started_at_ns is not None:
            phase_trace._finish_phase(
                phase="routing_plan",
                started_at_ns=routing_started_at_ns,
                outcome=("deadline_exhausted" if plan is _TIME_BUDGET_EXHAUSTED else "completed"),
            )
        if plan is _TIME_BUDGET_EXHAUSTED:
            result = _time_budget_exhausted_semantic_result(
                query_text=query_text,
                query_class=query_class,
                plan=None,
                index=self.index,
                graph_revision_fingerprint=graph_revision_fingerprint,
            )
            if phase_trace is not None:
                phase_trace._finish_query("deadline_exhausted")
            return result
        assert isinstance(plan, SemanticQueryPlan)
        if plan.time_budget_ms != deadline.budget_ms:
            if phase_trace is not None:
                phase_trace._finish_query("failed")
            raise ContractValidationError("semantic query deadline binding mismatch")

        def timeout_result() -> GovernedSemanticExecutionResult:
            result = _time_budget_exhausted_semantic_result(
                query_text=query_text,
                query_class=query_class,
                plan=plan,
                index=self.index,
                graph_revision_fingerprint=graph_revision_fingerprint,
            )
            if phase_trace is not None:
                phase_trace._finish_query("deadline_exhausted")
            return result

        authorized_observation_hash_by_id = dict(self.authorized_observation_hashes)
        lineage_crosswalk = _run_traced_query_phase(
            deadline=deadline,
            phase_trace=phase_trace,
            phase="lineage_crosswalk",
            operation=lambda: build_evidence_identity_lineage_crosswalk(
                session=self,
                effective_graph_view=effective_graph_view,
                graph_snapshot=graph_snapshot,
                execution_deadline=deadline,
            ),
        )
        if lineage_crosswalk is _TIME_BUDGET_EXHAUSTED:
            return timeout_result()
        assert isinstance(lineage_crosswalk, EvidenceIdentityLineageCrosswalk)
        if plan.query_class == "exact_set_or_inventory":
            exact_result = _run_traced_query_phase(
                deadline=deadline,
                phase_trace=phase_trace,
                phase="deterministic_exact_execution",
                operation=lambda: (
                    execute_deterministic_source_occurrence_inventory(
                        plan=plan,
                        provider=exact_provider,
                        expected_authorized_scope_fingerprint=(
                            authorized_source_occurrence_scope_fingerprint(
                                requester_user_id=self.requester_user_id,
                                workspace_id=self.workspace_id,
                                source_scope_ids=self.authorized_source_scope_ids,
                                authorized_observation_hashes=self.authorized_observation_hashes,
                                source_session_binding_fingerprint=(
                                    self.source_session_binding_fingerprint or ""
                                ),
                            )
                        ),
                        page_size=page_size,
                        cursor=cursor,
                    )
                    if exact_provider is not None
                    else execute_deterministic_exact_inventory(
                        plan=plan,
                        effective_graph_view=effective_graph_view,
                        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
                    )
                ),
            )
            if exact_result is _TIME_BUDGET_EXHAUSTED:
                return timeout_result()
            assert isinstance(exact_result, DeterministicExactExecutionResult)
            if exact_unsupported_projection_hashes:
                exact_result = _mark_partial_projection_exact_result(
                    exact_result,
                    unsupported_projection_hashes=exact_unsupported_projection_hashes,
                    has_bound_projections=bool(exact_projection_hashes),
                )
            exact_answer_citation_hashes = tuple(
                dict.fromkeys(
                    observation_hash
                    for item in exact_result.items
                    for observation_hash in item.cited_observation_hashes
                )
            )
            exact_lineage_audit = _run_traced_query_phase(
                deadline=deadline,
                phase_trace=phase_trace,
                phase="lineage_audit",
                operation=lambda: _result_lineage_audit(
                    crosswalk=lineage_crosswalk,
                    semantic_scores=(),
                    graph_paths=(),
                    final_citation_hashes=exact_answer_citation_hashes,
                    exact_result=exact_result,
                    execution_deadline=deadline,
                ),
            )
            if exact_lineage_audit is _TIME_BUDGET_EXHAUSTED:
                return timeout_result()
            assert isinstance(exact_lineage_audit, EvidenceIdentityLineageAudit)
            if (
                exact_provider is not None
                and exact_lineage_audit.unresolved_evidence_hashes
            ):
                raise ContractValidationError(
                    "exact source occurrence citation lineage is unresolved"
                )
            exact_execution_result = _run_traced_query_phase(
                deadline=deadline,
                phase_trace=phase_trace,
                phase="result_projection",
                operation=lambda: _semantic_execution_result(
                    status=exact_result.status,
                    plan=plan,
                    index=self.index,
                    graph_revision_fingerprint=graph_revision_fingerprint,
                    scores=(),
                    graph_paths=(),
                    answer_citation_hashes=exact_answer_citation_hashes,
                    rejected_hop_count=0,
                    exact_result=exact_result,
                    lineage_audit=exact_lineage_audit,
                    warnings=(),
                ),
            )
            if exact_execution_result is _TIME_BUDGET_EXHAUSTED:
                return timeout_result()
            assert isinstance(exact_execution_result, GovernedSemanticExecutionResult)
            if phase_trace is not None:
                phase_trace._finish_query("completed")
            return exact_execution_result

        hybrid_result = _run_traced_query_phase(
            deadline=deadline,
            phase_trace=phase_trace,
            phase="strong_rag",
            operation=lambda: self.index.query(
                query_text=query_text,
                query_class="evidence_lookup",
                candidate_limit=plan.candidate_limit,
                result_limit=plan.result_limit,
                execution_deadline=deadline,
            ),
        )
        if hybrid_result is _TIME_BUDGET_EXHAUSTED:
            return timeout_result()
        assert isinstance(hybrid_result, GovernedHybridRagResult)
        evidence_candidates_by_hash = _run_before_query_deadline(
            deadline,
            lambda: {
                candidate.source_observation_hash: candidate for candidate in self.index.candidates
            },
        )
        if evidence_candidates_by_hash is _TIME_BUDGET_EXHAUSTED:
            return timeout_result()
        assert isinstance(evidence_candidates_by_hash, dict)
        relation_projection: _RelationQueryProjection | None = None
        if plan.query_class == "relation_reasoning" and enable_graph_traversal:
            relation_projection_result = _run_traced_query_phase(
                deadline=deadline,
                phase_trace=phase_trace,
                phase="relation_projection",
                operation=lambda: _build_relation_query_projection(
                    plan=plan,
                    query_text=query_text,
                    index=self.index,
                    effective_graph_view=effective_graph_view,
                    tokenizer_profile=self.index._runtime_components.tokenizer_profile,
                    authorized_observation_hash_by_id=(authorized_observation_hash_by_id),
                    candidates_by_hash=evidence_candidates_by_hash,
                    graph_snapshot=graph_snapshot,
                    authorized_source=self.authorized_source,
                    execution_deadline=deadline,
                ),
            )
            if relation_projection_result is _TIME_BUDGET_EXHAUSTED:
                return timeout_result()
            assert isinstance(relation_projection_result, _RelationQueryProjection)
            relation_projection = relation_projection_result
        elif phase_trace is not None:
            phase_trace._skip_phase("relation_projection")
        graph_paths: tuple[BoundedGraphPath, ...] = ()
        rejected_hop_count = 0
        if plan.query_class == "relation_reasoning" and enable_graph_traversal:
            traversal_result = _run_traced_query_phase(
                deadline=deadline,
                phase_trace=phase_trace,
                phase="graph_traversal",
                operation=lambda: _bounded_graph_traversal(
                    plan=plan,
                    query_text=query_text,
                    effective_graph_view=effective_graph_view,
                    tokenizer_profile=self.index._runtime_components.tokenizer_profile,
                    authorized_observation_hash_by_id=(authorized_observation_hash_by_id),
                    evidence_candidates_by_hash=evidence_candidates_by_hash,
                    relation_projection=relation_projection,
                    graph_snapshot=graph_snapshot,
                    execution_deadline=deadline,
                ),
            )
            if traversal_result is _TIME_BUDGET_EXHAUSTED:
                return timeout_result()
            assert isinstance(traversal_result, tuple)
            graph_paths, rejected_hop_count = traversal_result
        elif phase_trace is not None:
            phase_trace._skip_phase("graph_traversal")
        scores = _run_traced_query_phase(
            deadline=deadline,
            phase_trace=phase_trace,
            phase="scoring",
            operation=lambda: _semantic_evidence_scores(
                plan=plan,
                query_text=query_text,
                hybrid_result=hybrid_result,
                index=self.index,
                graph_paths=graph_paths,
                effective_graph_view=effective_graph_view,
                tokenizer_profile=self.index._runtime_components.tokenizer_profile,
                authorized_observation_hash_by_id=(authorized_observation_hash_by_id),
                enable_entity_signal=enable_entity_signal,
                legacy_hard_gate=legacy_hard_gate,
                relation_projection=relation_projection,
                execution_deadline=deadline,
            ),
        )
        if scores is _TIME_BUDGET_EXHAUSTED:
            return timeout_result()
        assert isinstance(scores, tuple)
        warnings = list(hybrid_result.warnings)
        if plan.query_class == "global_summarization":
            warnings.append("bounded_summary_evidence_only_no_answer_model")
        if plan.query_class == "relation_reasoning" and not enable_graph_traversal:
            warnings.append("graph_traversal_ablation_disabled")
        if legacy_hard_gate:
            warnings.append("legacy_ontology_hard_gate_negative_ablation")
        answer_citation_hashes = _run_traced_query_phase(
            deadline=deadline,
            phase_trace=phase_trace,
            phase="proof_citation_selection",
            operation=lambda: _bounded_semantic_answer_citation_hashes(
                plan=plan,
                query_text=query_text,
                hybrid_result=hybrid_result,
                semantic_scores=scores,
                graph_paths=graph_paths,
                index=self.index,
                tokenizer_profile=self.index._runtime_components.tokenizer_profile,
                execution_deadline=deadline,
            ),
        )
        if answer_citation_hashes is _TIME_BUDGET_EXHAUSTED:
            return timeout_result()
        assert isinstance(answer_citation_hashes, tuple)
        status = hybrid_result.status
        if plan.query_class == "relation_reasoning" and enable_graph_traversal:
            status = "ok" if answer_citation_hashes else "no_answer"
            if not answer_citation_hashes:
                warnings.append("required_relation_slots_unresolved")
                fallback = _run_traced_query_phase(
                    deadline=deadline,
                    phase_trace=phase_trace,
                    phase="fallback",
                    operation=lambda: _execute_bounded_relation_fallback(
                        plan=plan,
                        query_text=query_text,
                        graph_paths=graph_paths,
                        effective_graph_view=effective_graph_view,
                        tokenizer_profile=(self.index._runtime_components.tokenizer_profile),
                        document_frequency=dict(self.index.document_frequency),
                        document_count=len(self.index.candidates),
                        index_fingerprint=self.index.index_fingerprint,
                        authorized_observation_hash_by_id=(authorized_observation_hash_by_id),
                        evidence_candidates_by_hash=evidence_candidates_by_hash,
                        authorized_workspace_id=self.workspace_id,
                        authorized_source_scope_ids=self.authorized_source_scope_ids,
                        authorized_source=self.authorized_source,
                        supported_relation_types=allowed_relation_types,
                        limits=limits,
                        relation_projection=relation_projection,
                        graph_snapshot=graph_snapshot,
                        execution_deadline=deadline,
                    ),
                )
                if fallback is _TIME_BUDGET_EXHAUSTED:
                    return timeout_result()
                if fallback is not None:
                    assert isinstance(fallback, _RelationFallbackOutcome)
                    plan = fallback.plan
                    graph_paths = fallback.graph_paths
                    rejected_hop_count += fallback.rejected_hop_count
                    answer_citation_hashes = fallback.answer_citation_hashes
                    warnings.append("bounded_relation_fallback_repair_attempted")
                    if fallback.targeted_retraversal_used:
                        warnings.append("bounded_relation_targeted_retraversal_attempted")
                    if answer_citation_hashes:
                        status = "ok"
                        warnings.append("bounded_relation_fallback_repair_succeeded")
                        warnings = [
                            warning
                            for warning in warnings
                            if warning != "required_relation_slots_unresolved"
                        ]
                        if fallback.targeted_retraversal_used:
                            rescored = _run_traced_query_phase(
                                deadline=deadline,
                                phase_trace=phase_trace,
                                phase="scoring",
                                operation=lambda: _semantic_evidence_scores(
                                    plan=plan,
                                    query_text=query_text,
                                    hybrid_result=hybrid_result,
                                    index=self.index,
                                    graph_paths=graph_paths,
                                    effective_graph_view=effective_graph_view,
                                    tokenizer_profile=(
                                        self.index._runtime_components.tokenizer_profile
                                    ),
                                    authorized_observation_hash_by_id=(
                                        authorized_observation_hash_by_id
                                    ),
                                    enable_entity_signal=enable_entity_signal,
                                    legacy_hard_gate=legacy_hard_gate,
                                    relation_projection=relation_projection,
                                    execution_deadline=deadline,
                                ),
                            )
                            if rescored is _TIME_BUDGET_EXHAUSTED:
                                return timeout_result()
                            assert isinstance(rescored, tuple)
                            scores = rescored
                    else:
                        warnings.append("bounded_relation_fallback_repair_exhausted")
            elif phase_trace is not None:
                phase_trace._skip_phase("fallback")
        elif phase_trace is not None:
            phase_trace._skip_phase("fallback")
        if plan.query_class == "relation_reasoning" and enable_graph_traversal and not graph_paths:
            warnings.append("no_supported_authorized_graph_path")
        elif status == "ok" and (not scores or not answer_citation_hashes):
            status = "no_answer"
        lineage_audit = _run_traced_query_phase(
            deadline=deadline,
            phase_trace=phase_trace,
            phase="lineage_audit",
            operation=lambda: _result_lineage_audit(
                crosswalk=lineage_crosswalk,
                semantic_scores=scores,
                graph_paths=graph_paths,
                final_citation_hashes=answer_citation_hashes,
                exact_result=None,
                execution_deadline=deadline,
            ),
        )
        if lineage_audit is _TIME_BUDGET_EXHAUSTED:
            return timeout_result()
        assert isinstance(lineage_audit, EvidenceIdentityLineageAudit)
        semantic_result = _run_traced_query_phase(
            deadline=deadline,
            phase_trace=phase_trace,
            phase="result_projection",
            operation=lambda: _semantic_execution_result(
                status=status,
                plan=plan,
                index=self.index,
                graph_revision_fingerprint=graph_revision_fingerprint,
                scores=scores,
                graph_paths=graph_paths,
                answer_citation_hashes=answer_citation_hashes,
                rejected_hop_count=rejected_hop_count,
                exact_result=None,
                lineage_audit=lineage_audit,
                warnings=tuple(sorted(set(warnings))),
            ),
        )
        if semantic_result is _TIME_BUDGET_EXHAUSTED:
            return timeout_result()
        assert isinstance(semantic_result, GovernedSemanticExecutionResult)
        if phase_trace is not None:
            phase_trace._finish_query("completed")
        return semantic_result


@dataclass(frozen=True)
class AuthorizedSemanticObservationSession(AuthorizedSemanticMailSession):
    """Source-neutral session using typed source occurrence and authorization bindings."""


def _validated_source_occurrence_providers(
    *,
    session: AuthorizedSemanticMailSession,
    providers: Sequence[SourceOccurrenceProvider],
) -> tuple[SourceOccurrenceProvider, ...]:
    resolved = tuple(providers)
    if any(not isinstance(provider, SourceOccurrenceProvider) for provider in resolved):
        raise ContractValidationError("source occurrence exact binding is invalid")
    provider_fingerprints = tuple(provider.provider_fingerprint for provider in resolved)
    expected_scope = authorized_source_occurrence_scope_fingerprint(
        requester_user_id=session.requester_user_id,
        workspace_id=session.workspace_id,
        source_scope_ids=session.authorized_source_scope_ids,
        authorized_observation_hashes=session.authorized_observation_hashes,
        source_session_binding_fingerprint=session.source_session_binding_fingerprint or "",
    )
    if (
        len(set(provider_fingerprints)) != len(provider_fingerprints)
        or any(
            provider.requester_user_id != session.requester_user_id
            or provider.workspace_id != session.workspace_id
            or provider.source_scope_ids != session.authorized_source_scope_ids
            or provider.authorized_scope_fingerprint != expected_scope
            for provider in resolved
        )
    ):
        raise ContractValidationError("source occurrence exact binding is invalid")
    if not resolved:
        return resolved
    authorized_hashes = dict(session.authorized_observation_hashes)
    lineages = {
        lineage.source_observation_id: lineage
        for lineage in session.occurrence_lineages
    }
    if (
        len(lineages) != len(session.occurrence_lineages)
        or not lineages.keys() <= authorized_hashes.keys()
    ):
        raise ContractValidationError(
            "source occurrence provider provenance binding is invalid"
        )
    authorized_pairs = {
        (authorized_hashes[observation_id], lineage.lineage_fingerprint)
        for observation_id, lineage in lineages.items()
    }
    if any(
        any(
            (binding[2], binding[3]) not in authorized_pairs
            for binding in occurrence.value_bindings
        )
        or any(
            (binding[5], binding[6]) not in authorized_pairs
            for binding in occurrence.structured_column_bindings
        )
        for provider in resolved
        for occurrence in provider.occurrences
    ):
        raise ContractValidationError(
            "source occurrence provider provenance binding mismatch"
        )
    return resolved


def _source_occurrence_provider_seal(
    *,
    session: AuthorizedSemanticMailSession,
    providers: tuple[SourceOccurrenceProvider, ...],
) -> str:
    return sha256_json(
        (
            "source_occurrence_provider_provenance_seal_v1",
            session.source_session_binding_fingerprint,
            session.requester_user_id,
            session.workspace_id,
            session.selected_source_scope_ids,
            session.authorized_source_scope_ids,
            tuple(provider.provider_fingerprint for provider in providers),
        )
    )


def attach_authorized_source_occurrence_providers(
    session: AuthorizedSemanticMailSession,
    providers: Sequence[SourceOccurrenceProvider],
) -> AuthorizedSemanticMailSession:
    """Validate and seal immutable source providers once at their owner boundary."""
    if not isinstance(session, AuthorizedSemanticMailSession) or (
        session.source_occurrence_providers
        or session._source_occurrence_provider_provenance_seal is not None
    ):
        raise ContractValidationError(
            "source occurrence provider attach binding is invalid"
        )
    resolved = _validated_source_occurrence_providers(
        session=session,
        providers=providers,
    )
    if resolved:
        session.index._runtime_components.tokenizer_profile.analyze_query_grounding(
            resolved[0].normalized_field
        )
    return replace(
        session,
        source_occurrence_providers=resolved,
        _source_occurrence_provider_provenance_seal=(
            _source_occurrence_provider_seal(
                session=session,
                providers=resolved,
            )
        ),
    )


def _require_source_occurrence_provider_provenance(
    *,
    session: AuthorizedSemanticMailSession,
    selected_provider: SourceOccurrenceProvider,
) -> None:
    seal = session._source_occurrence_provider_provenance_seal
    if seal is None:
        _validated_source_occurrence_providers(
            session=session,
            providers=(selected_provider,),
        )
        return
    providers = session.source_occurrence_providers
    if (
        any(
            not isinstance(provider, SourceOccurrenceProvider)
            for provider in providers
        )
        or not any(provider is selected_provider for provider in providers)
        or seal
        != _source_occurrence_provider_seal(
            session=session,
            providers=providers,
        )
    ):
        raise ContractValidationError(
            "source occurrence provider provenance seal mismatch"
        )


def _is_mail_compatibility_session(
    session: AuthorizedSemanticMailSession,
) -> bool:
    return type(session) is AuthorizedSemanticMailSession


def build_authorized_hybrid_mail_index(
    *,
    observations_by_bundle_id: Mapping[str, Sequence[Observation]],
    bundles: Sequence[MailEvidenceBundle],
    requester_user_id: str,
    workspace_id: str,
    expected_profile_fingerprint: str | None = None,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
    mail_import_session_id: str | None = None,
    mail_evidence_bundle_id: str | None = None,
) -> AuthorizedHybridMailIndex:
    """Authorize first, then materialize candidates with the pinned E5 runtime."""

    selected_bundles = matching_bundles(
        bundles,
        mail_import_session_id=mail_import_session_id,
        mail_evidence_bundle_id=mail_evidence_bundle_id,
    )
    authorized_bundles = authorize_mail_evidence_bundles(
        selected_bundles,
        requester_user_id=requester_user_id,
        workspace_id=workspace_id,
        grants=grants,
        now=now,
    )
    authorized_ids = {bundle.mail_evidence_bundle_id for bundle in authorized_bundles}
    denied_bundle_count = len(selected_bundles) - len(authorized_bundles)
    runtime_components = _require_issue56_runtime_components(
        expected_profile_fingerprint=expected_profile_fingerprint,
    )
    tokenizer_profile = runtime_components.tokenizer_profile
    dense_encoder = runtime_components.dense_encoder
    execution_binding = runtime_components.execution_binding
    candidates: list[_HybridCandidate] = []
    authorized_index_fingerprints: list[str] = []
    for bundle in sorted(
        authorized_bundles,
        key=lambda item: item.mail_evidence_bundle_id,
    ):
        observations = observations_by_bundle_id.get(bundle.mail_evidence_bundle_id)
        if observations is None:
            raise ContractValidationError("authorized mail evidence observations are unavailable")
        snippet_index, manifest = build_existing_observation_snippet_index(
            observations,
            bundle=bundle,
            tokenizer_profile=tokenizer_profile,
        )
        _require_hybrid_index_profile(
            snippet_index,
            tokenizer_profile=tokenizer_profile,
            expected_profile_fingerprint=tokenizer_profile.profile_fingerprint,
        )
        authorized_index_fingerprints.append(manifest.index_fingerprint)
        coherence_group_hash_by_message_id = {
            message.email_message_id: _mail_coherence_group_hash(
                bundle_id=bundle.mail_evidence_bundle_id,
                message_id=message.email_message_id,
                thread_id=message.thread_id,
            )
            for message in bundle.messages
        }
        candidates.extend(
            _hybrid_candidates_from_snippet_index(
                snippet_index,
                dense_encoder=dense_encoder,
                tokenizer_profile=tokenizer_profile,
                coherence_group_hash_by_message_id=(coherence_group_hash_by_message_id),
            )
        )
    candidates.sort(
        key=lambda item: (
            item.bundle_id,
            item.source_observation_hash,
            item.message_hash,
        )
    )
    if set(authorized_ids) - set(observations_by_bundle_id):
        raise ContractValidationError("authorized mail evidence observations are unavailable")
    document_frequency: Counter[str] = Counter()
    for candidate in candidates:
        document_frequency.update(candidate.searchable_tokens)
    average_document_length = (
        sum(len(candidate.searchable_tokens) for candidate in candidates) / len(candidates)
        if candidates
        else 0.0
    )
    index_fingerprint = sha256_json(
        {
            "schema_version": 2,
            "profile_fingerprint": tokenizer_profile.profile_fingerprint,
            "dense_encoder_id": dense_encoder.encoder_id,
            "dense_profile_fingerprint": dense_encoder.profile_fingerprint,
            "dense_model_id": execution_binding.dense_model_id,
            "dense_model_revision": execution_binding.dense_model_revision,
            "execution_component_fingerprint": (execution_binding.execution_component_fingerprint),
            "authorized_index_fingerprints": sorted(authorized_index_fingerprints),
            "candidate_hashes": [
                sha256_json(
                    {
                        "bundle_id": candidate.bundle_id,
                        "coherence_group_hash": (candidate.coherence_group_hash),
                        "source_observation_hash": candidate.source_observation_hash,
                        "message_hash": candidate.message_hash,
                        "message_occurrence_hash": candidate.message_occurrence_hash,
                        "index_binding_hash": candidate.index_binding_hash,
                        "token_hashes": sorted(
                            sha256_json(token) for token in candidate.searchable_tokens
                        ),
                        "protected_identifier_hashes": sorted(
                            sha256_json(token) for token in candidate.protected_identifier_tokens
                        ),
                        "observation_token_hashes": sorted(
                            sha256_json(token) for token in candidate.observation_tokens
                        ),
                        "observation_protected_identifier_hashes": sorted(
                            sha256_json(token)
                            for token in candidate.observation_protected_identifier_tokens
                        ),
                        "dense_evidence_text_hash": (candidate.dense_evidence_text_hash),
                        "dense_vector": [_metric(value) for value in candidate.dense_vector],
                    }
                )
                for candidate in candidates
            ],
        }
    )
    frozen_candidates = tuple(candidates)
    integrity_fingerprint = _hybrid_index_integrity_fingerprint(
        index_fingerprint=index_fingerprint,
        tokenizer_id=tokenizer_profile.tokenizer_id,
        profile_fingerprint=tokenizer_profile.profile_fingerprint,
        execution_component_fingerprint=(execution_binding.execution_component_fingerprint),
        candidates=frozen_candidates,
        precomputed_graph_revision_fingerprint=None,
    )
    return AuthorizedHybridMailIndex(
        tokenizer_id=tokenizer_profile.tokenizer_id,
        profile_fingerprint=tokenizer_profile.profile_fingerprint,
        index_fingerprint=index_fingerprint,
        dense_encoder_id=dense_encoder.encoder_id,
        dense_encoder_status=_PINNED_DENSE_STATUS,
        dense_profile_fingerprint=dense_encoder.profile_fingerprint,
        dense_model_id=execution_binding.dense_model_id,
        dense_model_revision=execution_binding.dense_model_revision,
        execution_component_fingerprint=(execution_binding.execution_component_fingerprint),
        selected_bundle_count=len(selected_bundles),
        authorized_bundle_count=len(authorized_bundles),
        denied_bundle_count=denied_bundle_count,
        candidates=frozen_candidates,
        document_frequency=tuple(sorted(document_frequency.items())),
        average_document_length=average_document_length,
        _relation_projection_candidates_snapshot=frozen_candidates,
        _integrity_fingerprint=integrity_fingerprint,
        _runtime_components=runtime_components,
    )


def build_authorized_semantic_observation_session(
    *,
    authorized_source: AuthorizedSemanticSource,
    snippet_index: ObservationSnippetIndex,
    authorized_observations: Sequence[Observation],
    retrieval_observations: Sequence[Observation] | None = None,
    occurrence_lineages: Sequence[SourceOccurrenceLineage],
    requester_user_id: str,
    expected_profile_fingerprint: str | None = None,
    precomputed_index_artifact: AuthorizedHybridObservationIndexArtifact | None = None,
    expected_precomputed_index_artifact_fingerprint: str | None = None,
) -> AuthorizedSemanticObservationSession:
    """Bind an already-authorized source-neutral Observation index to Hybrid execution."""

    if not isinstance(authorized_source, AuthorizedSemanticSource):
        raise ContractValidationError("authorized semantic source is invalid")
    safe_public_string(requester_user_id, "requester_user_id")
    if not isinstance(snippet_index, ObservationSnippetIndex):
        raise ContractValidationError("authorized Observation snippet index is invalid")
    observations, lineages, authorized_hash_by_id = _validated_source_neutral_inputs(
        authorized_source=authorized_source,
        authorized_observations=authorized_observations,
        occurrence_lineages=occurrence_lineages,
    )
    retrieval_by_id: dict[str, Observation] = {}
    retrieval_hash_by_id: dict[str, str] = {}
    for observation in observations if retrieval_observations is None else retrieval_observations:
        if not isinstance(observation, Observation):
            raise ContractValidationError(
                "semantic retrieval requires Observation records"
            )
        validated = Observation.from_dict(observation.to_dict())
        if validated.observation_id in retrieval_by_id:
            raise ContractValidationError(
                "semantic retrieval has duplicate Observation ids"
            )
        observation_hash = sha256_json(validated.to_dict())
        if authorized_hash_by_id.get(validated.observation_id) != observation_hash:
            raise ContractValidationError(
                "semantic retrieval authorization binding mismatch"
            )
        retrieval_by_id[validated.observation_id] = validated
        retrieval_hash_by_id[validated.observation_id] = observation_hash
    if not retrieval_by_id:
        raise ContractValidationError("semantic retrieval requires Observations")
    lineage_by_observation_id = {
        lineage.source_observation_id: lineage for lineage in lineages
    }
    if any(
        observation_id not in lineage_by_observation_id
        for observation_id in retrieval_by_id
    ):
        raise ContractValidationError(
            "semantic retrieval occurrence lineage is incomplete"
        )
    retrieval_lineages = tuple(
        lineage_by_observation_id[observation_id]
        for observation_id in sorted(retrieval_by_id)
    )
    retrieval_observations = tuple(
        retrieval_by_id[observation_id] for observation_id in sorted(retrieval_by_id)
    )
    if snippet_index.source_access_fingerprint != authorized_source.authorization_fingerprint:
        raise ContractValidationError("authorized Observation index source binding mismatch")

    runtime_components = _require_issue56_runtime_components(
        expected_profile_fingerprint=(
            expected_profile_fingerprint or snippet_index.profile_fingerprint
        ),
    )
    tokenizer_profile = runtime_components.tokenizer_profile
    rebuilt_index, _ = build_authorized_observation_snippet_index(
        retrieval_observations,
        authorized_source=authorized_source,
        occurrence_lineages=retrieval_lineages,
        authorized_observation_hash_by_id=retrieval_hash_by_id,
        tokenizer_profile=tokenizer_profile,
    )
    if rebuilt_index != snippet_index:
        raise ContractValidationError("authorized Observation snippet index binding mismatch")

    artifact = _resolve_precomputed_hybrid_observation_index_artifact(
        precomputed_index_artifact,
        expected_artifact_fingerprint=(
            expected_precomputed_index_artifact_fingerprint
        ),
    )
    precomputed_dense_vectors = (
        _precomputed_dense_vectors_for_snippets(
            artifact=artifact,
            authorized_source=authorized_source,
            snippet_index=snippet_index,
            retrieval_hash_by_id=retrieval_hash_by_id,
            runtime_components=runtime_components,
        )
        if artifact is not None
        else None
    )
    index = _build_authorized_hybrid_observation_index(
        authorized_source=authorized_source,
        snippet_index=snippet_index,
        authorized_observations=retrieval_observations,
        occurrence_lineages=retrieval_lineages,
        runtime_components=runtime_components,
        dense_vectors=precomputed_dense_vectors,
        precomputed_graph_revision_fingerprint=(
            artifact.graph_revision_fingerprint if artifact is not None else None
        ),
    )
    source_session_binding_fingerprint = _source_neutral_session_binding_fingerprint(
        authorized_source=authorized_source,
        index=index,
        authorized_observations=observations,
        occurrence_lineages=lineages,
    )
    if artifact is not None and (
        index.index_fingerprint != artifact.index_fingerprint
        or source_session_binding_fingerprint
        != artifact.source_session_binding_fingerprint
    ):
        raise ContractValidationError("precomputed hybrid index session binding mismatch")
    retrieval_observation_hashes = tuple(sorted(retrieval_hash_by_id.items()))
    authorized_observation_hashes = tuple(sorted(authorized_hash_by_id.items()))
    return AuthorizedSemanticObservationSession(
        index=index,
        requester_user_id=requester_user_id,
        workspace_id=authorized_source.workspace_id,
        selected_source_scope_ids=authorized_source.source_scope_ids,
        authorized_source_scope_ids=authorized_source.source_scope_ids,
        retrieval_observation_hashes=retrieval_observation_hashes,
        authorized_observation_hashes=authorized_observation_hashes,
        authorized_source=authorized_source,
        authorized_observations=observations,
        occurrence_lineages=lineages,
        source_session_binding_fingerprint=source_session_binding_fingerprint,
    )


def _build_authorized_hybrid_observation_index(
    *,
    authorized_source: AuthorizedSemanticSource,
    snippet_index: ObservationSnippetIndex,
    authorized_observations: Sequence[Observation],
    occurrence_lineages: Sequence[SourceOccurrenceLineage],
    runtime_components: Issue56TargetRuntimeComponents,
    dense_vectors: Sequence[Sequence[float]] | None = None,
    precomputed_graph_revision_fingerprint: str | None = None,
) -> AuthorizedHybridMailIndex:
    tokenizer_profile = runtime_components.tokenizer_profile
    dense_encoder = runtime_components.dense_encoder
    execution_binding = runtime_components.execution_binding
    observation_by_id = {
        observation.observation_id: observation for observation in authorized_observations
    }
    lineage_by_observation_id = {
        lineage.source_observation_id: lineage for lineage in occurrence_lineages
    }
    ordered_snippets = tuple(snippet_index.snippets)
    if dense_vectors is None:
        resolved_dense_vectors = _encode_authorized_evidence_vectors(
            dense_encoder,
            tuple(snippet.dense_evidence_text for snippet in ordered_snippets),
        )
    else:
        if not isinstance(dense_vectors, tuple) or any(
            not isinstance(vector, tuple) for vector in dense_vectors
        ):
            raise ContractValidationError(
                "precomputed hybrid index dense vectors must be immutable"
            )
        for vector in dense_vectors:
            _validate_precomputed_dense_vector(vector)
        resolved_dense_vectors = dense_vectors
    if len(resolved_dense_vectors) != len(ordered_snippets):
        raise ContractValidationError("precomputed hybrid index vector count mismatch")
    candidates = [
        _hybrid_candidate_from_observation_snippet(
            snippet,
            authorized_source=authorized_source,
            observation=observation_by_id[_required_snippet_source_observation_id(snippet.payload)],
            occurrence_lineage=lineage_by_observation_id[
                _required_snippet_source_observation_id(snippet.payload)
            ],
            dense_encoder=dense_encoder,
            tokenizer_profile=tokenizer_profile,
            dense_vector=resolved_dense_vectors[index],
        )
        for index, snippet in enumerate(ordered_snippets)
    ]
    candidates.sort(
        key=lambda item: (
            item.bundle_id,
            item.source_observation_hash,
            item.message_occurrence_hash,
        )
    )
    document_frequency: Counter[str] = Counter()
    for candidate in candidates:
        document_frequency.update(candidate.searchable_tokens)
    average_document_length = (
        sum(len(candidate.searchable_tokens) for candidate in candidates) / len(candidates)
        if candidates
        else 0.0
    )
    index_fingerprint = sha256_json(
        {
            "schema_version": 1,
            "index_kind": "authorized_source_neutral_hybrid_observation_index",
            "source_access_fingerprint": authorized_source.authorization_fingerprint,
            "observation_index_fingerprint": snippet_index.index_fingerprint,
            "profile_fingerprint": tokenizer_profile.profile_fingerprint,
            "dense_encoder_id": dense_encoder.encoder_id,
            "dense_profile_fingerprint": dense_encoder.profile_fingerprint,
            "dense_model_id": execution_binding.dense_model_id,
            "dense_model_revision": execution_binding.dense_model_revision,
            "execution_component_fingerprint": (execution_binding.execution_component_fingerprint),
            "candidate_hashes": [
                _hybrid_candidate_content_fingerprint(candidate) for candidate in candidates
            ],
        }
    )
    frozen_candidates = tuple(candidates)
    integrity_fingerprint = _hybrid_index_integrity_fingerprint(
        index_fingerprint=index_fingerprint,
        tokenizer_id=tokenizer_profile.tokenizer_id,
        profile_fingerprint=tokenizer_profile.profile_fingerprint,
        execution_component_fingerprint=execution_binding.execution_component_fingerprint,
        candidates=frozen_candidates,
        precomputed_graph_revision_fingerprint=(
            precomputed_graph_revision_fingerprint
        ),
    )
    return AuthorizedHybridMailIndex(
        tokenizer_id=tokenizer_profile.tokenizer_id,
        profile_fingerprint=tokenizer_profile.profile_fingerprint,
        index_fingerprint=index_fingerprint,
        dense_encoder_id=dense_encoder.encoder_id,
        dense_encoder_status=_PINNED_DENSE_STATUS,
        dense_profile_fingerprint=dense_encoder.profile_fingerprint,
        dense_model_id=execution_binding.dense_model_id,
        dense_model_revision=execution_binding.dense_model_revision,
        execution_component_fingerprint=execution_binding.execution_component_fingerprint,
        selected_bundle_count=len(authorized_source.source_scope_ids),
        authorized_bundle_count=len(authorized_source.source_scope_ids),
        denied_bundle_count=0,
        candidates=frozen_candidates,
        document_frequency=tuple(sorted(document_frequency.items())),
        average_document_length=average_document_length,
        _relation_projection_candidates_snapshot=frozen_candidates,
        _integrity_fingerprint=integrity_fingerprint,
        _runtime_components=runtime_components,
        _precomputed_graph_revision_fingerprint=(
            precomputed_graph_revision_fingerprint
        ),
    )


def build_authorized_hybrid_observation_index_artifact(
    *,
    session: AuthorizedSemanticObservationSession,
    snippet_index: ObservationSnippetIndex,
    graph_build: SourceBackedGraphBuild,
) -> AuthorizedHybridObservationIndexArtifact:
    """Seal one reusable dense projection after source and graph validation."""

    if (
        not isinstance(session, AuthorizedSemanticObservationSession)
        or _is_mail_compatibility_session(session)
        or not isinstance(snippet_index, ObservationSnippetIndex)
        or not isinstance(graph_build, SourceBackedGraphBuild)
    ):
        raise ContractValidationError("precomputed hybrid index source session is invalid")
    _validate_hybrid_index_runtime(session.index)
    if (
        session.authorized_source is None
        or snippet_index.source_access_fingerprint
        != session.authorized_source.authorization_fingerprint
        or graph_build.graph_revision_fingerprint
        != _graph_revision_fingerprint(graph_build.effective_graph_view)
    ):
        raise ContractValidationError("precomputed hybrid index source/graph binding mismatch")
    _validate_source_neutral_semantic_session(
        session=session,
        effective_graph_view=graph_build.effective_graph_view,
    )
    retrieval_hashes = frozenset(dict(session.retrieval_observation_hashes).values())
    candidates = tuple(
        sorted(session.index.candidates, key=lambda item: item.source_observation_hash)
    )
    if (
        len(candidates) != len(retrieval_hashes)
        or {candidate.source_observation_hash for candidate in candidates}
        != retrieval_hashes
    ):
        raise ContractValidationError("precomputed hybrid index candidate binding mismatch")
    dense_vector_payload = _pack_precomputed_dense_vectors(
        tuple(candidate.dense_vector for candidate in candidates)
    )
    artifact = AuthorizedHybridObservationIndexArtifact(
        source_access_fingerprint=session.authorized_source.authorization_fingerprint,
        source_session_binding_fingerprint=_source_graph_require_sha256(
            session.source_session_binding_fingerprint,
            "precomputed hybrid index source session binding fingerprint",
        ),
        snippet_index_fingerprint=snippet_index.index_fingerprint,
        graph_revision_fingerprint=graph_build.graph_revision_fingerprint,
        tokenizer_id=session.index.tokenizer_id,
        profile_fingerprint=session.index.profile_fingerprint,
        dense_encoder_id=session.index.dense_encoder_id,
        dense_profile_fingerprint=session.index.dense_profile_fingerprint,
        dense_model_id=session.index.dense_model_id,
        dense_model_revision=session.index.dense_model_revision,
        execution_component_fingerprint=(
            session.index.execution_component_fingerprint
        ),
        index_fingerprint=session.index.index_fingerprint,
        dense_vector_payload_fingerprint=sha256_prefixed(dense_vector_payload),
        dense_vector_bindings=tuple(
            (
                candidate.source_observation_hash,
                candidate.dense_evidence_text_hash,
            )
            for candidate in candidates
        ),
        _dense_vector_payload=dense_vector_payload,
    )
    _validate_precomputed_hybrid_observation_index_artifact(
        artifact,
        expected_artifact_fingerprint=artifact.artifact_fingerprint,
    )
    return artifact


def _resolve_precomputed_hybrid_observation_index_artifact(
    artifact: AuthorizedHybridObservationIndexArtifact | None,
    *,
    expected_artifact_fingerprint: str | None,
) -> AuthorizedHybridObservationIndexArtifact | None:
    if artifact is None:
        if expected_artifact_fingerprint is not None:
            raise ContractValidationError("precomputed hybrid index artifact is unavailable")
        return None
    if expected_artifact_fingerprint is None:
        raise ContractValidationError("precomputed hybrid index artifact fingerprint is required")
    if not isinstance(artifact, AuthorizedHybridObservationIndexArtifact):
        raise ContractValidationError("precomputed hybrid index artifact is invalid")
    _validate_precomputed_hybrid_observation_index_artifact(
        artifact,
        expected_artifact_fingerprint=expected_artifact_fingerprint,
    )
    return artifact


def _validate_precomputed_hybrid_observation_index_artifact(
    artifact: AuthorizedHybridObservationIndexArtifact,
    *,
    expected_artifact_fingerprint: str,
) -> None:
    _source_graph_require_sha256(
        expected_artifact_fingerprint,
        "precomputed hybrid index expected artifact fingerprint",
    )
    for value, field_name in (
        (artifact.source_access_fingerprint, "source access fingerprint"),
        (artifact.source_session_binding_fingerprint, "source session binding fingerprint"),
        (artifact.snippet_index_fingerprint, "snippet index fingerprint"),
        (artifact.graph_revision_fingerprint, "graph revision fingerprint"),
        (artifact.profile_fingerprint, "profile fingerprint"),
        (artifact.dense_profile_fingerprint, "dense profile fingerprint"),
        (artifact.execution_component_fingerprint, "execution component fingerprint"),
        (artifact.index_fingerprint, "index fingerprint"),
        (
            artifact.dense_vector_payload_fingerprint,
            "dense vector payload fingerprint",
        ),
    ):
        _source_graph_require_sha256(value, f"precomputed hybrid index {field_name}")
    for value, field_name in (
        (artifact.tokenizer_id, "tokenizer id"),
        (artifact.dense_encoder_id, "dense encoder id"),
        (artifact.dense_model_id, "dense model id"),
        (artifact.dense_model_revision, "dense model revision"),
    ):
        safe_public_string(value, f"precomputed hybrid index {field_name}")
    observation_hashes: list[str] = []
    for observation_hash, text_hash in artifact.dense_vector_bindings:
        _source_graph_require_sha256(
            observation_hash,
            "precomputed hybrid index source Observation hash",
        )
        _source_graph_require_sha256(
            text_hash,
            "precomputed hybrid index dense evidence text hash",
        )
        observation_hashes.append(observation_hash)
    expected_payload_size = (
        len(observation_hashes)
        * ISSUE56_TARGET_DENSE_DIMENSION
        * _PRECOMPUTED_DENSE_VECTOR_BYTES
    )
    if (
        not observation_hashes
        or tuple(sorted(observation_hashes)) != tuple(observation_hashes)
        or len(set(observation_hashes)) != len(observation_hashes)
        or not isinstance(artifact._dense_vector_payload, bytes)
        or len(artifact._dense_vector_payload) != expected_payload_size
        or sha256_prefixed(artifact._dense_vector_payload)
        != artifact.dense_vector_payload_fingerprint
        or artifact.artifact_fingerprint != expected_artifact_fingerprint
    ):
        raise ContractValidationError("precomputed hybrid index artifact binding mismatch")


def _precomputed_dense_vectors_for_snippets(
    *,
    artifact: AuthorizedHybridObservationIndexArtifact,
    authorized_source: AuthorizedSemanticSource,
    snippet_index: ObservationSnippetIndex,
    retrieval_hash_by_id: Mapping[str, str],
    runtime_components: Issue56TargetRuntimeComponents,
) -> tuple[tuple[float, ...], ...]:
    binding = runtime_components.execution_binding
    if (
        artifact.source_access_fingerprint
        != authorized_source.authorization_fingerprint
        or artifact.snippet_index_fingerprint != snippet_index.index_fingerprint
        or artifact.tokenizer_id != binding.tokenizer_id
        or artifact.profile_fingerprint != binding.tokenizer_profile_fingerprint
        or artifact.dense_encoder_id != binding.dense_encoder_id
        or artifact.dense_profile_fingerprint != binding.dense_profile_fingerprint
        or artifact.dense_model_id != binding.dense_model_id
        or artifact.dense_model_revision != binding.dense_model_revision
        or artifact.execution_component_fingerprint
        != binding.execution_component_fingerprint
    ):
        raise ContractValidationError("precomputed hybrid index runtime/source mismatch")
    binding_by_observation_hash = {
        observation_hash: (text_hash, index)
        for index, (observation_hash, text_hash) in enumerate(
            artifact.dense_vector_bindings
        )
    }
    if set(binding_by_observation_hash) != set(retrieval_hash_by_id.values()):
        raise ContractValidationError("precomputed hybrid index Observation binding mismatch")
    vectors: list[tuple[float, ...]] = []
    for snippet in snippet_index.snippets:
        observation_id = _required_snippet_source_observation_id(snippet.payload)
        binding_value = binding_by_observation_hash.get(
            retrieval_hash_by_id.get(observation_id, "")
        )
        if (
            binding_value is None
            or binding_value[0] != sha256_json(snippet.dense_evidence_text)
        ):
            raise ContractValidationError("precomputed hybrid index snippet binding mismatch")
        vector = _unpack_precomputed_dense_vector(
            artifact._dense_vector_payload,
            row_index=binding_value[1],
        )
        _validate_precomputed_dense_vector(vector)
        vectors.append(vector)
    return tuple(vectors)


def _pack_precomputed_dense_vectors(
    vectors: Sequence[Sequence[float]],
) -> bytes:
    payload = bytearray(
        len(vectors)
        * ISSUE56_TARGET_DENSE_DIMENSION
        * _PRECOMPUTED_DENSE_VECTOR_BYTES
    )
    row_format = f"<{ISSUE56_TARGET_DENSE_DIMENSION}f"
    row_size = ISSUE56_TARGET_DENSE_DIMENSION * _PRECOMPUTED_DENSE_VECTOR_BYTES
    for row_index, vector in enumerate(vectors):
        frozen = tuple(float(value) for value in vector)
        _validate_precomputed_dense_vector(frozen)
        struct.pack_into(row_format, payload, row_index * row_size, *frozen)
    return bytes(payload)


def _unpack_precomputed_dense_vector(
    payload: bytes,
    *,
    row_index: int,
) -> tuple[float, ...]:
    row_size = ISSUE56_TARGET_DENSE_DIMENSION * _PRECOMPUTED_DENSE_VECTOR_BYTES
    return tuple(
        struct.unpack_from(
            f"<{ISSUE56_TARGET_DENSE_DIMENSION}f",
            payload,
            row_index * row_size,
        )
    )


def _validate_precomputed_dense_vector(vector: Sequence[float]) -> None:
    if (
        len(vector) != ISSUE56_TARGET_DENSE_DIMENSION
        or any(not math.isfinite(value) for value in vector)
        or not math.isclose(
            math.sqrt(sum(value * value for value in vector)),
            1.0,
            rel_tol=1e-5,
            abs_tol=1e-5,
        )
    ):
        raise ContractValidationError("precomputed hybrid index dense vector is invalid")


def build_authorized_semantic_mail_session(
    *,
    observations_by_bundle_id: Mapping[str, Sequence[Observation]],
    authorization_observations_by_bundle_id: Mapping[str, Sequence[Observation]] | None = None,
    bundles: Sequence[MailEvidenceBundle],
    requester_user_id: str,
    workspace_id: str,
    expected_profile_fingerprint: str | None = None,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
    mail_import_session_id: str | None = None,
    mail_evidence_bundle_id: str | None = None,
) -> AuthorizedSemanticMailSession:
    """Authorize once and bind a reusable semantic session to that exact scope."""

    selected_bundles = matching_bundles(
        bundles,
        mail_import_session_id=mail_import_session_id,
        mail_evidence_bundle_id=mail_evidence_bundle_id,
    )
    authorized_bundles = authorize_mail_evidence_bundles(
        selected_bundles,
        requester_user_id=requester_user_id,
        workspace_id=workspace_id,
        grants=grants,
        now=now,
    )
    index = build_authorized_hybrid_mail_index(
        observations_by_bundle_id=observations_by_bundle_id,
        bundles=selected_bundles,
        requester_user_id=requester_user_id,
        workspace_id=workspace_id,
        expected_profile_fingerprint=expected_profile_fingerprint,
        grants=grants,
        now=now,
    )
    authorization_observations_by_bundle_id = (
        observations_by_bundle_id
        if authorization_observations_by_bundle_id is None
        else authorization_observations_by_bundle_id
    )
    if set(authorization_observations_by_bundle_id) != set(observations_by_bundle_id):
        raise ContractValidationError("mail session authorization bundle binding mismatch")
    indexed_authorized_hash_by_id = _authorized_observation_hashes(
        observations_by_bundle_id=observations_by_bundle_id,
        authorized_bundles=authorized_bundles,
    )
    authorized_observation_hash_by_id = _authorized_observation_hashes(
        observations_by_bundle_id=authorization_observations_by_bundle_id,
        authorized_bundles=authorized_bundles,
    )
    if any(
        authorized_observation_hash_by_id.get(observation_id) != observation_hash
        for observation_id, observation_hash in indexed_authorized_hash_by_id.items()
    ):
        raise ContractValidationError("mail session retrieval authorization binding mismatch")
    selected_source_scope_ids = tuple(
        sorted(bundle.mail_evidence_bundle_id for bundle in selected_bundles)
    )
    authorized_source_scope_ids = tuple(
        sorted(bundle.mail_evidence_bundle_id for bundle in authorized_bundles)
    )
    authorized_source = (
        validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=workspace_id,
            source_scope_ids=authorized_source_scope_ids,
        )
        if authorized_source_scope_ids
        else None
    )
    authorized_observations = tuple(
        sorted(
            (
                Observation.from_dict(observation.to_dict())
                for bundle in authorized_bundles
                for observation in authorization_observations_by_bundle_id[
                    bundle.mail_evidence_bundle_id
                ]
            ),
            key=lambda observation: observation.observation_id,
        )
    )
    occurrence_lineages = (
        tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            for observation in authorized_observations
            if _observation_message_occurrence_id(observation) is not None
        )
        if authorized_source is not None
        else ()
    )
    source_session_binding_fingerprint = (
        _mail_compatibility_session_binding_fingerprint(
            authorized_source=authorized_source,
            index=index,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            selected_source_scope_ids=selected_source_scope_ids,
            authorized_source_scope_ids=authorized_source_scope_ids,
            retrieval_observation_hashes=tuple(
                sorted(indexed_authorized_hash_by_id.items())
            ),
            authorized_observations=authorized_observations,
            occurrence_lineages=occurrence_lineages,
        )
        if authorized_source is not None
        else None
    )
    return AuthorizedSemanticMailSession(
        index=index,
        requester_user_id=requester_user_id,
        workspace_id=workspace_id,
        selected_source_scope_ids=selected_source_scope_ids,
        authorized_source_scope_ids=authorized_source_scope_ids,
        retrieval_observation_hashes=tuple(sorted(indexed_authorized_hash_by_id.items())),
        authorized_observation_hashes=tuple(sorted(authorized_observation_hash_by_id.items())),
        authorized_source=authorized_source,
        authorized_observations=authorized_observations,
        occurrence_lineages=occurrence_lineages,
        source_session_binding_fingerprint=source_session_binding_fingerprint,
    )


def build_authorized_source_backed_effective_graph_view(
    *,
    session: AuthorizedSemanticObservationSession,
    observations_by_bundle_id: Mapping[str, Sequence[Observation]] | None = None,
    source_binding_fingerprint: str,
    identifier_mention_batch: SourceBoundIdentifierMentionBatch | None = None,
    source_graph_policy_id: str | None = None,
) -> SourceBackedGraphBuild:
    """Build one deterministic candidate graph from retrieval-bound Observations.

    The function reads only source scopes already authorized by ``session``.
    Query text, adjudication, expected ids, and case order are not inputs.

    The legacy v1 policy remains available only for existing explicit callers.
    Supplying a source-authored identifier mention batch selects v2.  An
    explicit v2 request without that artifact fails closed.  GitHub native
    parent and issue-reference assertions require the explicit source-backed
    GitHub candidate policy; the compatibility mail policy never infers them.
    """

    safe_public_string(source_binding_fingerprint, "source_binding_fingerprint")
    resolved_policy_id = source_graph_policy_id or (
        _SOURCE_GRAPH_POLICY_ID_V2
        if identifier_mention_batch is not None
        else _SOURCE_GRAPH_POLICY_ID
    )
    if resolved_policy_id not in {
        _SOURCE_GRAPH_POLICY_ID,
        _SOURCE_GRAPH_POLICY_ID_V2,
        _SOURCE_GRAPH_GITHUB_REFERENCE_POLICY_ID,
    }:
        raise ContractValidationError("source-backed graph policy is unsupported")
    if resolved_policy_id == _SOURCE_GRAPH_POLICY_ID_V2 and identifier_mention_batch is None:
        raise ContractValidationError(
            "source-backed graph v2 identifier mention artifact is unavailable"
        )
    if resolved_policy_id == _SOURCE_GRAPH_POLICY_ID and identifier_mention_batch is not None:
        raise ContractValidationError(
            "source-backed graph v1 cannot consume identifier mention artifacts"
        )
    if resolved_policy_id == _SOURCE_GRAPH_GITHUB_REFERENCE_POLICY_ID:
        if identifier_mention_batch is not None:
            raise ContractValidationError(
                "GitHub source-reference graph cannot consume identifier mention artifacts"
            )
        if (
            _is_mail_compatibility_session(session)
            or session.authorized_source is None
            or session.authorized_source.source_kind != GITHUB_PROJECT_OBSERVATION_SOURCE_KIND
        ):
            raise ContractValidationError(
                "GitHub source-reference graph requires the GitHub source kind"
            )
    observations_by_scope_id, occurrence_lineage_by_observation_id = _source_backed_graph_inputs(
        session=session,
        observations_by_source_scope_id=observations_by_bundle_id,
    )
    if identifier_mention_batch is not None and not _is_mail_compatibility_session(
        session,
    ):
        raise ContractValidationError(
            "source-backed identifier mention graph requires the mail compatibility source"
        )
    if identifier_mention_batch is not None and observations_by_bundle_id is None:
        raise ContractValidationError(
            "source-backed identifier mention graph requires selected mail Observations"
        )
    identifier_input = (
        _validate_source_identifier_mention_batch(
            session=session,
            observations_by_bundle_id=observations_by_bundle_id,
            source_binding_fingerprint=source_binding_fingerprint,
            batch=identifier_mention_batch,
        )
        if identifier_mention_batch is not None
        else None
    )
    graph_identity_binding = (
        dict(identifier_input.graph_identity_binding) if identifier_input is not None else {}
    )
    graph_identity_binding_fingerprint = (
        identifier_input.graph_identity_binding_fingerprint
        if identifier_input is not None
        else None
    )
    authorized_hash_by_id = dict(session.authorized_observation_hashes)
    observation_nodes: list[GraphProjectionNode] = []
    observation_node_id_by_observation_id: dict[str, str] = {}
    entity_observations: dict[str, set[str]] = {}
    entity_labels: dict[str, str] = {}
    entity_supertypes: dict[str, str] = {}
    entity_permission_scopes: dict[str, dict[str, Any]] = {}
    entity_term_hashes: dict[str, set[str]] = {}
    term_observations: dict[str, set[str]] = {}
    term_hashes: dict[str, str] = {}
    term_permission_scopes: dict[str, dict[str, Any]] = {}
    term_is_protected: dict[str, bool] = {}
    source_terms_by_observation_id: dict[str, tuple[str, ...]] = {}
    authorized_observation_by_id: dict[str, Observation] = {}
    edges_by_id: dict[str, GraphProjectionEdge] = {}
    observed_ids: set[str] = set()
    candidates_by_observation_hash = {
        candidate.source_observation_hash: candidate for candidate in session.index.candidates
    }
    document_frequency = dict(session.index.document_frequency)
    source_kind_properties = _source_graph_source_kind_properties(session)

    for source_scope_id in session.authorized_source_scope_ids:
        observations = observations_by_scope_id.get(source_scope_id)
        if observations is None:
            raise ContractValidationError(
                "authorized source-backed graph observations are unavailable"
            )
        for observation in sorted(observations, key=lambda item: item.observation_id):
            validated = Observation.from_dict(observation.to_dict())
            expected_hash = authorized_hash_by_id.get(validated.observation_id)
            if expected_hash is None or expected_hash != sha256_json(validated.to_dict()):
                raise ContractValidationError("source-backed graph Observation lineage mismatch")
            observed_ids.add(validated.observation_id)
            authorized_observation_by_id[validated.observation_id] = validated
            candidate = candidates_by_observation_hash.get(expected_hash)
            if candidate is not None:
                occurrence_lineage = occurrence_lineage_by_observation_id.get(
                    validated.observation_id
                )
                if occurrence_lineage is None or candidate.message_occurrence_hash != sha256_json(
                    occurrence_lineage.occurrence_id
                ):
                    raise ContractValidationError("source-backed graph occurrence lineage mismatch")
                source_terms = _source_graph_source_terms(
                    tuple(candidate.observation_tokens),
                    document_frequency=document_frequency,
                )
                identifiers = (
                    tuple(sorted(candidate.observation_protected_identifier_tokens))[
                        :_SOURCE_GRAPH_MAX_IDENTIFIERS_PER_OBSERVATION
                    ]
                    if identifier_input is None
                    else ()
                )
            else:
                source_terms = ()
                identifiers = ()
            source_terms_by_observation_id[validated.observation_id] = source_terms
            identifier_mentions = (
                identifier_input.mentions_by_observation_id.get(
                    validated.observation_id,
                    (),
                )
                if identifier_input is not None
                else ()
            )
            observation_node_id = _source_graph_observation_node_id(
                observation_id=validated.observation_id,
                identity_scope_binding_fingerprint=(graph_identity_binding_fingerprint),
                permission_boundary_fingerprint=sha256_json(validated.permission_scope),
            )
            observation_node_id_by_observation_id[validated.observation_id] = observation_node_id
            observation_labels = _source_graph_observation_labels(source_terms)
            observation_term_hashes = _source_graph_term_hashes(source_terms)
            occurrence_lineage = occurrence_lineage_by_observation_id.get(validated.observation_id)
            if occurrence_lineage is None and not _is_mail_compatibility_session(session):
                raise ContractValidationError(
                    "source-backed graph occurrence lineage is unavailable"
                )
            observation_protected_term_hashes = (
                tuple(sorted({mention.text_hash for mention in identifier_mentions}))
                if identifier_input is not None
                else _source_graph_term_hashes(identifiers)
            )
            observation_nodes.append(
                GraphProjectionNode(
                    node_id=observation_node_id,
                    source_type=_source_graph_source_type(
                        session,
                        mail_value="mail_observation_candidate",
                        source_neutral_value="source_observation_candidate",
                    ),
                    source_id=observation_node_id,
                    labels=list(observation_labels),
                    properties={
                        "source_observation_ids": [validated.observation_id],
                        "node_kind": "source_observation",
                        "review_state": "source_record",
                        "temporal_state": "current",
                        "core_supertype_id": "Document",
                        "type_confidence": 1.0,
                        "inventory_kind": _source_graph_inventory_kind_for_occurrence(
                            session,
                            occurrence_lineage=occurrence_lineage,
                        ),
                        "inventory_value": validated.observation_id,
                        "ontology_subject": False,
                        "source_term_hashes": list(observation_term_hashes),
                        "protected_term_hashes": list(observation_protected_term_hashes),
                        **source_kind_properties,
                        **graph_identity_binding,
                    },
                    permission_scope=dict(validated.permission_scope),
                )
            )
            if identifier_input is None:
                for identifier in identifiers:
                    entity_key = sha256_json(identifier)
                    entity_observations.setdefault(entity_key, set()).add(validated.observation_id)
                    entity_labels.setdefault(entity_key, identifier)
                    entity_supertypes.setdefault(
                        entity_key,
                        _source_graph_core_supertype(identifier),
                    )
                    entity_permission_scopes.setdefault(
                        entity_key,
                        dict(validated.permission_scope),
                    )
                    entity_term_hashes.setdefault(entity_key, set()).update(observation_term_hashes)
                for left_key, right_key in _source_graph_entity_pairs(identifiers):
                    edge_id = _source_graph_edge_id(
                        observation_id=validated.observation_id,
                        left_identifier=left_key,
                        right_identifier=right_key,
                    )
                    if edge_id in edges_by_id:
                        continue
                    edges_by_id[edge_id] = GraphProjectionEdge(
                        edge_id=edge_id,
                        source_node_id=_source_graph_node_id("entity", left_key),
                        target_node_id=_source_graph_node_id("entity", right_key),
                        relation_type=_SOURCE_GRAPH_RELATION_TYPE,
                        properties={
                            "source_observation_ids": [validated.observation_id],
                            "review_state": "diagnostic_policy_admitted",
                            **source_kind_properties,
                        },
                        permission_scope=dict(validated.permission_scope),
                    )
            protected_terms = (
                set(
                    candidate.observation_protected_identifier_tokens
                    if candidate is not None
                    else ()
                )
                if identifier_input is None
                else set()
            )
            protected_term_hashes = {mention.text_hash for mention in identifier_mentions}
            permission_fingerprint = sha256_json(validated.permission_scope)
            for term in source_terms:
                term_hash = sha256_json(term)
                term_key_payload = {
                    "term_hash": term_hash,
                    "permission_fingerprint": permission_fingerprint,
                }
                if graph_identity_binding_fingerprint is not None:
                    term_key_payload["identity_scope_graph_binding_fingerprint"] = (
                        graph_identity_binding_fingerprint
                    )
                term_key = sha256_json(term_key_payload)
                term_observations.setdefault(term_key, set()).add(validated.observation_id)
                term_hashes.setdefault(term_key, term_hash)
                term_permission_scopes.setdefault(
                    term_key,
                    dict(validated.permission_scope),
                )
                term_is_protected[term_key] = (
                    term_is_protected.get(term_key, False)
                    or term in protected_terms
                    or term_hash in protected_term_hashes
                )
                edge_id = _source_graph_observation_term_edge_id(
                    observation_id=validated.observation_id,
                    term_key=term_key,
                )
                edges_by_id[edge_id] = GraphProjectionEdge(
                    edge_id=edge_id,
                    source_node_id=observation_node_id,
                    target_node_id=_source_graph_node_id("term", term_key),
                    relation_type=_SOURCE_GRAPH_RELATION_TYPE,
                    properties={
                        "source_observation_ids": [validated.observation_id],
                        "review_state": "diagnostic_policy_admitted",
                        **source_kind_properties,
                        **graph_identity_binding,
                    },
                    permission_scope=dict(validated.permission_scope),
                )

    occurrence_observation_id = {
        lineage.occurrence_id: lineage.source_observation_id
        for lineage in occurrence_lineage_by_observation_id.values()
    }
    for lineage in sorted(
        occurrence_lineage_by_observation_id.values(),
        key=lambda item: item.source_observation_id,
    ):
        if lineage.parent_occurrence_id is None:
            continue
        parent_observation_id = occurrence_observation_id.get(lineage.parent_occurrence_id)
        child_observation_id = lineage.source_observation_id
        if parent_observation_id is None:
            continue
        parent_observation = authorized_observation_by_id[parent_observation_id]
        child_observation = authorized_observation_by_id[child_observation_id]
        if dict(parent_observation.permission_scope) != dict(child_observation.permission_scope):
            continue
        source_node_id = observation_node_id_by_observation_id[parent_observation_id]
        target_node_id = observation_node_id_by_observation_id[child_observation_id]
        edge_id = _source_graph_occurrence_lineage_edge_id(
            source_kind=(
                session.authorized_source.source_kind
                if session.authorized_source is not None
                else AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
            ),
            parent_observation_id=parent_observation_id,
            child_observation_id=child_observation_id,
        )
        edges_by_id[edge_id] = GraphProjectionEdge(
            edge_id=edge_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relation_type=_SOURCE_GRAPH_RELATION_TYPE,
            properties={
                "source_observation_ids": [
                    parent_observation_id,
                    child_observation_id,
                ],
                "review_state": "diagnostic_policy_admitted",
                "occurrence_lineage_hash": sha256_json(lineage.lineage_fingerprint),
                **source_kind_properties,
            },
            permission_scope=dict(child_observation.permission_scope),
        )

    if resolved_policy_id == _SOURCE_GRAPH_GITHUB_REFERENCE_POLICY_ID:
        for edge in _source_graph_github_reference_edges(
            session=session,
            authorized_observation_by_id=authorized_observation_by_id,
            occurrence_lineage_by_observation_id=(occurrence_lineage_by_observation_id),
            observation_node_id_by_observation_id=(observation_node_id_by_observation_id),
        ):
            if edge.edge_id in edges_by_id:
                raise ContractValidationError(
                    "GitHub source-reference graph edge identity conflict"
                )
            edges_by_id[edge.edge_id] = edge

    expected_observed_ids = {
        observation_id
        for observation_id, _observation_hash in session.retrieval_observation_hashes
    }
    if observed_ids != expected_observed_ids:
        raise ContractValidationError(
            "source-backed graph retrieval Observation binding mismatch"
        )
    if identifier_input is not None:
        entity_nodes, identifier_edges = _source_graph_identifier_projection(
            identifier_input=identifier_input,
            authorized_observation_by_id=authorized_observation_by_id,
            source_terms_by_observation_id=source_terms_by_observation_id,
            observation_node_id_by_observation_id=(observation_node_id_by_observation_id),
        )
        for edge in identifier_edges:
            if edge.edge_id in edges_by_id:
                raise ContractValidationError(
                    "source-backed identifier graph edge identity conflict"
                )
            edges_by_id[edge.edge_id] = edge
    else:
        entity_nodes = [
            GraphProjectionNode(
                node_id=_source_graph_node_id("entity", entity_key),
                source_type=_source_graph_source_type(
                    session,
                    mail_value="mail_candidate_entity",
                    source_neutral_value="source_candidate_entity",
                ),
                source_id=_source_graph_node_id("entity", entity_key),
                labels=[
                    "candidate_entity",
                    _source_graph_typed_hash_label(
                        "candidate_entity",
                        entity_labels[entity_key],
                    ),
                ],
                properties={
                    "source_observation_ids": sorted(observation_ids),
                    "node_kind": "candidate_entity",
                    "review_state": "diagnostic_policy_admitted",
                    "temporal_state": "current",
                    "core_supertype_id": entity_supertypes[entity_key],
                    "type_confidence": 0.7,
                    "inventory_kind": _source_graph_inventory_kind(entity_labels[entity_key]),
                    "inventory_value": entity_key,
                    "ontology_subject": True,
                    "source_term_hashes": sorted(
                        entity_term_hashes[entity_key]
                        | set(_source_graph_term_hashes((entity_labels[entity_key],)))
                    )[:_SOURCE_GRAPH_MAX_TERM_HASHES_PER_ENTITY],
                    "protected_term_hashes": list(
                        _source_graph_term_hashes((entity_labels[entity_key],))
                    ),
                    **source_kind_properties,
                },
                permission_scope=entity_permission_scopes[entity_key],
            )
            for entity_key, observation_ids in sorted(entity_observations.items())
        ]
    term_nodes = [
        GraphProjectionNode(
            node_id=_source_graph_node_id("term", term_key),
            source_type=_source_graph_source_type(
                session,
                mail_value="mail_candidate_source_term",
                source_neutral_value="source_candidate_source_term",
            ),
            source_id=_source_graph_node_id("term", term_key),
            labels=[
                "candidate_source_term",
                _source_graph_typed_hash_label(
                    "source_term",
                    term_hashes[term_key],
                ),
            ],
            properties={
                "source_observation_ids": sorted(observation_ids),
                "node_kind": "candidate_source_term",
                "review_state": "diagnostic_policy_admitted",
                "temporal_state": "current",
                "core_supertype_id": "Concept",
                "type_confidence": 0.5,
                "ontology_subject": False,
                "source_term_hashes": [term_hashes[term_key]],
                "protected_term_hashes": (
                    [term_hashes[term_key]] if term_is_protected.get(term_key, False) else []
                ),
                **source_kind_properties,
                **graph_identity_binding,
            },
            permission_scope=term_permission_scopes[term_key],
        )
        for term_key, observation_ids in sorted(term_observations.items())
    ]
    nodes = sorted(
        (*observation_nodes, *entity_nodes, *term_nodes),
        key=lambda item: item.node_id,
    )
    edges = sorted(edges_by_id.values(), key=lambda item: item.edge_id)
    for node in nodes:
        node.to_dict()
    for edge in edges:
        edge.to_dict()
    build_payload = {
        "policy_id": resolved_policy_id,
        "source_binding_fingerprint": source_binding_fingerprint,
        **source_kind_properties,
        "requester_user_id": session.requester_user_id,
        "authorized_source_scope_ids": list(session.authorized_source_scope_ids),
        "authorized_observation_hashes": sorted(authorized_hash_by_id.values()),
        "node_hashes": [sha256_json(node.to_dict()) for node in nodes],
        "edge_hashes": [sha256_json(edge.to_dict()) for edge in edges],
    }
    if identifier_input is not None:
        build_payload.update(
            {
                "identity_scope_binding": (identifier_input.identity_scope.to_dict()),
                "identity_scope_graph_binding": graph_identity_binding,
                "identity_scope_graph_binding_fingerprint": (
                    identifier_input.graph_identity_binding_fingerprint
                ),
                "complete_identifier_mention_fingerprint": (
                    identifier_input.complete_mention_fingerprint
                ),
                "authorized_identifier_mention_fingerprint": (
                    identifier_input.authorized_mention_fingerprint
                ),
                "identifier_resolution_fingerprint": (
                    identifier_input.exact_resolution.resolution_fingerprint
                ),
            }
        )
    build_fingerprint = sha256_json(build_payload)
    suffix = build_fingerprint.removeprefix("sha256:")[:24]
    view = EffectiveGraphView(
        requester_user_id=session.requester_user_id,
        user_graph_revision_id=f"ugraph_source_{suffix}",
        canonical_graph_revision_id=f"cgraph_candidate_{suffix}",
        ontology_revision_id=f"ontology_scoped_{suffix}",
        assembly_policy_id=f"assembly_source_{suffix}",
        visible_nodes=nodes,
        visible_edges=edges,
    )
    graph_revision_fingerprint = _graph_revision_fingerprint(view)
    _validate_precomputed_hybrid_graph_binding(
        index=session.index,
        graph_revision_fingerprint=graph_revision_fingerprint,
    )
    _validate_source_neutral_semantic_session(
        session=session,
        effective_graph_view=view,
    )
    result = SourceBackedGraphBuild(
        effective_graph_view=view,
        graph_revision_fingerprint=graph_revision_fingerprint,
        source_observation_count=len(observed_ids),
        observation_node_count=len(observation_nodes),
        entity_node_count=len(entity_nodes) + len(term_nodes),
        edge_count=len(edges),
        ontology_typed_node_count=sum(
            bool(node.properties.get("ontology_subject")) for node in entity_nodes
        ),
        relation_type_hashes=_source_graph_relation_type_hashes(
            graph_policy_id=resolved_policy_id,
            identifier_input=identifier_input,
        ),
        build_fingerprint=build_fingerprint,
        graph_policy_id=resolved_policy_id,
        complete_identifier_mention_fingerprint=(
            identifier_input.complete_mention_fingerprint if identifier_input is not None else None
        ),
        authorized_identifier_mention_fingerprint=(
            identifier_input.authorized_mention_fingerprint
            if identifier_input is not None
            else None
        ),
        identifier_resolution_fingerprint=(
            identifier_input.exact_resolution.resolution_fingerprint
            if identifier_input is not None
            else None
        ),
        identifier_mention_count=(
            identifier_input.batch.occurrence_count if identifier_input is not None else 0
        ),
        authorized_identifier_mention_count=(
            len(identifier_input.authorized_mentions) if identifier_input is not None else 0
        ),
        identity_scope_mode=(
            identifier_input.identity_scope.identity_scope_mode
            if identifier_input is not None
            else None
        ),
        identity_scope_fingerprint=(
            identifier_input.identity_scope.identity_scope_fingerprint
            if identifier_input is not None
            else None
        ),
        identity_scope_attestation_fingerprint=(
            identifier_input.identity_scope.identity_scope_attestation_fingerprint
            if identifier_input is not None
            else None
        ),
        identity_scope_policy_fingerprint=(
            identifier_input.identity_scope.identity_scope_policy_fingerprint
            if identifier_input is not None
            else None
        ),
        operator_approval_fingerprint=(
            identifier_input.identity_scope.operator_approval_fingerprint
            if identifier_input is not None
            else None
        ),
        spec_approval_fingerprint=(
            identifier_input.identity_scope.spec_approval_fingerprint
            if identifier_input is not None
            else None
        ),
        identity_scope_graph_binding_fingerprint=(
            identifier_input.graph_identity_binding_fingerprint
            if identifier_input is not None
            else None
        ),
    )
    result.to_safe_dict()
    return result


def build_evidence_identity_lineage_crosswalk(
    *,
    session: AuthorizedSemanticObservationSession,
    effective_graph_view: EffectiveGraphView,
    graph_snapshot: _QueryGraphSnapshot | None = None,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> EvidenceIdentityLineageCrosswalk:
    """Trace authorized Observation hashes through index and graph identities.

    The crosswalk is query-independent and contains hashes only.  It never
    receives adjudication ids, expected answers, or private source locators.
    """

    _query_deadline_checkpoint(execution_deadline)
    if graph_snapshot is None:
        graph_snapshot = _build_query_graph_snapshot(
            effective_graph_view,
            execution_deadline=execution_deadline,
        )
    graph_revision_fingerprint = _require_query_graph_snapshot(
        effective_graph_view=effective_graph_view,
        graph_snapshot=graph_snapshot,
    )
    source_session_binding_fingerprint = _source_graph_require_sha256(
        session.source_session_binding_fingerprint,
        "evidence lineage crosswalk source session binding fingerprint",
    )
    cache_binding = (
        session.index.index_fingerprint,
        graph_revision_fingerprint,
        source_session_binding_fingerprint,
    )
    cache_key = cache_binding
    with _EVIDENCE_LINEAGE_CROSSWALK_CACHE_LOCK:
        cached = _EVIDENCE_LINEAGE_CROSSWALK_CACHE.get(cache_key)
    if cached is not None:
        cached_binding = (
            cached.index_fingerprint,
            cached.graph_revision_fingerprint,
            cached.source_session_binding_fingerprint,
        )
        if cached_binding != cache_key:
            raise ContractValidationError("evidence lineage crosswalk cache binding mismatch")
        _query_deadline_checkpoint(execution_deadline)
        return cached

    candidates_by_hash: dict[str, list[_HybridCandidate]] = {}
    for candidate in session.index.candidates:
        _query_deadline_checkpoint(execution_deadline)
        candidates_by_hash.setdefault(candidate.source_observation_hash, []).append(candidate)
    authorized_hash_by_id = dict(session.authorized_observation_hashes)
    graph_node_hashes_by_evidence: dict[str, set[str]] = {}
    graph_edge_hashes_by_evidence: dict[str, set[str]] = {}
    for node in effective_graph_view.visible_nodes:
        _query_deadline_checkpoint(execution_deadline)
        evidence_hashes = _authorized_property_evidence_hashes(
            node.properties,
            authorized_observation_hash_by_id=authorized_hash_by_id,
        )
        if evidence_hashes is None:
            continue
        node_hash = sha256_json(node.node_id)
        for evidence_hash in evidence_hashes:
            _query_deadline_checkpoint(execution_deadline)
            graph_node_hashes_by_evidence.setdefault(evidence_hash, set()).add(node_hash)
    for edge in effective_graph_view.visible_edges:
        _query_deadline_checkpoint(execution_deadline)
        evidence_hashes = _authorized_property_evidence_hashes(
            edge.properties,
            authorized_observation_hash_by_id=authorized_hash_by_id,
        )
        if evidence_hashes is None:
            continue
        edge_hash = sha256_json(edge.edge_id)
        for evidence_hash in evidence_hashes:
            _query_deadline_checkpoint(execution_deadline)
            graph_edge_hashes_by_evidence.setdefault(evidence_hash, set()).add(edge_hash)

    entries: list[EvidenceIdentityLineageEntry] = []
    for evidence_hash in sorted(set(authorized_hash_by_id.values())):
        _query_deadline_checkpoint(execution_deadline)
        candidates = candidates_by_hash.get(evidence_hash, ())
        entries.append(
            EvidenceIdentityLineageEntry(
                source_observation_hash=evidence_hash,
                index_binding_hashes=tuple(
                    sorted({candidate.index_binding_hash for candidate in candidates})
                ),
                message_hashes=tuple(sorted({candidate.message_hash for candidate in candidates})),
                occurrence_hashes=tuple(
                    sorted({candidate.message_occurrence_hash for candidate in candidates})
                ),
                graph_node_hashes=tuple(
                    sorted(graph_node_hashes_by_evidence.get(evidence_hash, ()))
                ),
                graph_edge_hashes=tuple(
                    sorted(graph_edge_hashes_by_evidence.get(evidence_hash, ()))
                ),
            )
        )
    entry_payloads = [entry.to_safe_dict() for entry in entries]
    crosswalk_fingerprint = sha256_json(
        {
            "index_fingerprint": session.index.index_fingerprint,
            "graph_revision_fingerprint": graph_revision_fingerprint,
            "source_session_binding_fingerprint": source_session_binding_fingerprint,
            "entries": entry_payloads,
        }
    )
    result = EvidenceIdentityLineageCrosswalk(
        index_fingerprint=session.index.index_fingerprint,
        graph_revision_fingerprint=graph_revision_fingerprint,
        source_session_binding_fingerprint=source_session_binding_fingerprint,
        authorized_evidence_count=len(entries),
        indexed_evidence_count=sum(bool(entry.index_binding_hashes) for entry in entries),
        occurrence_bound_evidence_count=sum(
            bool(entry.index_binding_hashes)
            and bool(entry.message_hashes)
            and bool(entry.occurrence_hashes)
            for entry in entries
        ),
        graph_node_bound_evidence_count=sum(bool(entry.graph_node_hashes) for entry in entries),
        graph_edge_bound_evidence_count=sum(bool(entry.graph_edge_hashes) for entry in entries),
        entries=tuple(entries),
        crosswalk_fingerprint=crosswalk_fingerprint,
    )
    result.to_safe_dict()
    _query_deadline_checkpoint(execution_deadline)
    with _EVIDENCE_LINEAGE_CROSSWALK_CACHE_LOCK:
        cached = _EVIDENCE_LINEAGE_CROSSWALK_CACHE.get(cache_key)
        if cached is not None:
            cached_binding = (
                cached.index_fingerprint,
                cached.graph_revision_fingerprint,
                cached.source_session_binding_fingerprint,
            )
            if cached_binding != cache_key:
                raise ContractValidationError("evidence lineage crosswalk cache binding mismatch")
            return cached
        if len(_EVIDENCE_LINEAGE_CROSSWALK_CACHE) >= 16:
            _EVIDENCE_LINEAGE_CROSSWALK_CACHE.clear()
        _EVIDENCE_LINEAGE_CROSSWALK_CACHE[cache_key] = result
        return result


def precompute_evidence_identity_lineage_crosswalk(
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
) -> EvidenceIdentityLineageCrosswalk:
    """Prime the query-independent authorized lineage map before prompt execution.

    The primed value is the same immutable hash-only crosswalk used by the cold
    query path.  Its cache binding is the complete authorized index fingerprint
    plus the immutable full-content graph revision fingerprint.
    """

    _validate_hybrid_index_runtime(session.index)
    if effective_graph_view.requester_user_id != session.requester_user_id:
        raise ContractValidationError("effective graph requester mismatch")
    _validate_source_neutral_semantic_session(
        session=session,
        effective_graph_view=effective_graph_view,
    )
    graph_snapshot = _build_query_graph_snapshot(effective_graph_view)
    crosswalk = build_evidence_identity_lineage_crosswalk(
        session=session,
        effective_graph_view=effective_graph_view,
        graph_snapshot=graph_snapshot,
    )
    if (
        crosswalk.index_fingerprint != session.index.index_fingerprint
        or crosswalk.graph_revision_fingerprint != graph_snapshot.graph_revision_fingerprint
    ):
        raise ContractValidationError("evidence lineage crosswalk precompute binding mismatch")
    return crosswalk


def precompute_effective_graph_content_snapshot(
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
    expected_graph_revision_fingerprint: str,
    expected_effective_graph_view_fingerprint: str,
) -> EffectiveGraphContentSnapshotPrecompute:
    """Materialize only the immutable graph-content snapshot before a query.

    This owner helper accepts the existing source-neutral and mail-compatibility
    authorized semantic sessions.  It validates their complete source/session,
    index, tokenizer, Observation, permission, and expected graph/view
    bindings.  It deliberately does not build a relation-projection cache
    binding or base.  Repeated calls over the same sealed view reuse its content
    snapshot and require both relation-projection cache containers to remain
    empty.
    """

    if not isinstance(session, AuthorizedSemanticMailSession) or not (
        _is_mail_compatibility_session(session)
        or isinstance(session, AuthorizedSemanticObservationSession)
    ):
        raise ContractValidationError(
            "graph snapshot precompute requires an authorized semantic session"
        )
    if not isinstance(effective_graph_view, EffectiveGraphView):
        raise ContractValidationError("graph snapshot precompute effective graph view is invalid")
    _source_graph_require_sha256(
        expected_graph_revision_fingerprint,
        "expected graph revision fingerprint",
    )
    _source_graph_require_sha256(
        expected_effective_graph_view_fingerprint,
        "expected effective graph view fingerprint",
    )
    _validate_hybrid_index_runtime(session.index)
    if effective_graph_view.requester_user_id != session.requester_user_id:
        raise ContractValidationError("effective graph requester mismatch")
    _validate_source_neutral_semantic_session(
        session=session,
        effective_graph_view=effective_graph_view,
    )

    (
        authorized_source,
        actual_authorized_observation_hashes,
        source_access_fingerprint,
        source_session_binding_fingerprint,
    ) = _validated_effective_graph_snapshot_session_bindings(session)
    authorized_observation_set_fingerprint = sha256_json(list(actual_authorized_observation_hashes))

    tokenizer_profile = session.index._runtime_components.tokenizer_profile
    if (
        tokenizer_profile.tokenizer_id != session.index.tokenizer_id
        or tokenizer_profile.profile_fingerprint != session.index.profile_fingerprint
    ):
        raise ContractValidationError("graph snapshot precompute tokenizer/index mismatch")
    _source_graph_require_sha256(
        session.index.index_fingerprint,
        "graph snapshot precompute index fingerprint",
    )
    _source_graph_require_sha256(
        tokenizer_profile.profile_fingerprint,
        "graph snapshot precompute tokenizer profile fingerprint",
    )

    effective_graph_view_fingerprint = sha256_json(effective_graph_view.to_dict())
    if effective_graph_view_fingerprint != expected_effective_graph_view_fingerprint:
        raise ContractValidationError("graph snapshot precompute effective graph binding mismatch")
    permission_lineage_fingerprint = _effective_graph_permission_lineage_fingerprint(
        session=session,
        effective_graph_view=effective_graph_view,
    )
    graph_content_fingerprint = _effective_graph_content_fingerprint(effective_graph_view)

    graph_snapshot = _build_query_graph_snapshot(effective_graph_view)
    graph_revision_fingerprint = _require_query_graph_snapshot(
        effective_graph_view=effective_graph_view,
        graph_snapshot=graph_snapshot,
    )
    if graph_revision_fingerprint != expected_graph_revision_fingerprint:
        raise ContractValidationError("graph snapshot precompute graph revision binding mismatch")
    if (
        sha256_json(effective_graph_view.to_dict()) != effective_graph_view_fingerprint
        or _effective_graph_content_fingerprint(effective_graph_view) != graph_content_fingerprint
    ):
        raise ContractValidationError("graph snapshot precompute content changed during sealing")

    content_snapshot = graph_snapshot.content_snapshot
    with content_snapshot.relation_projection_base_lock:
        binding_entry_count = len(content_snapshot.relation_projection_cache_binding_snapshots)
        base_entry_count = len(content_snapshot.relation_projection_bases)
        if binding_entry_count != 0 or base_entry_count != 0:
            raise ContractValidationError(
                "graph snapshot precompute relation projection caches are not cold"
            )
        safe_payload = {
            "artifact_id": "formowl_issue56_effective_graph_content_snapshot_precompute_v1",
            "graph_revision_fingerprint": graph_revision_fingerprint,
            "graph_content_fingerprint": graph_content_fingerprint,
            "effective_graph_view_fingerprint": effective_graph_view_fingerprint,
            "source_session_binding_fingerprint": source_session_binding_fingerprint,
            "source_access_fingerprint": source_access_fingerprint,
            "permission_lineage_fingerprint": permission_lineage_fingerprint,
            "index_fingerprint": session.index.index_fingerprint,
            "candidate_admission_profile_fingerprint": (tokenizer_profile.profile_fingerprint),
            "authorized_observation_set_fingerprint": (authorized_observation_set_fingerprint),
            "authorized_observation_count": len(actual_authorized_observation_hashes),
            "source_scope_count": len(authorized_source.source_scope_ids),
            "node_count": len(effective_graph_view.visible_nodes),
            "edge_count": len(effective_graph_view.visible_edges),
            "access_required_count": len(effective_graph_view.access_required),
            "applied_grant_count": len(effective_graph_view.applied_grant_ids),
            "relation_projection_cache_binding_entry_count": binding_entry_count,
            "relation_projection_base_entry_count": base_entry_count,
        }
        precompute = EffectiveGraphContentSnapshotPrecompute(
            graph_revision_fingerprint=graph_revision_fingerprint,
            graph_content_fingerprint=graph_content_fingerprint,
            effective_graph_view_fingerprint=effective_graph_view_fingerprint,
            source_session_binding_fingerprint=source_session_binding_fingerprint,
            source_access_fingerprint=source_access_fingerprint,
            permission_lineage_fingerprint=permission_lineage_fingerprint,
            index_fingerprint=session.index.index_fingerprint,
            candidate_admission_profile_fingerprint=(tokenizer_profile.profile_fingerprint),
            authorized_observation_set_fingerprint=(authorized_observation_set_fingerprint),
            authorized_observation_count=len(actual_authorized_observation_hashes),
            source_scope_count=len(authorized_source.source_scope_ids),
            node_count=len(effective_graph_view.visible_nodes),
            edge_count=len(effective_graph_view.visible_edges),
            access_required_count=len(effective_graph_view.access_required),
            applied_grant_count=len(effective_graph_view.applied_grant_ids),
            relation_projection_cache_binding_entry_count=binding_entry_count,
            relation_projection_base_entry_count=base_entry_count,
            precompute_fingerprint=sha256_json(safe_payload),
        )
    precompute.to_safe_dict()
    return precompute


def precompute_relation_projection_base(
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
) -> RelationProjectionBasePrecompute:
    """Prime the query-independent authorized relation projection base.

    Query tokenization, slot coverage, and anchor ranking remain in
    :func:`_build_relation_query_projection`; this helper invokes the exact
    immutable base cache path used by a relation query.
    """

    return _precompute_relation_projection_base_impl(
        session=session,
        effective_graph_view=effective_graph_view,
    )


def precompute_relation_projection_base_cold_diagnostic(
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
    expected_graph_revision_fingerprint: str,
    expected_effective_graph_view_fingerprint: str,
) -> RelationProjectionBaseColdDiagnostic:
    """Build one cold relation binding/base outside every query deadline.

    This diagnostic-only helper requires an already sealed graph-content
    snapshot whose relation caches are both empty.  It invokes the exact owner
    validation, binding, base-builder, and publication path used by a cold
    query, but it is forbidden while a query deadline is active.  Query
    tokenization, slot coverage, anchor ranking, and result production are not
    performed here.
    """

    if type(session) is not AuthorizedSemanticMailSession:
        raise ContractValidationError(
            "relation projection cold diagnostic requires an authorized mail session"
        )
    if not isinstance(effective_graph_view, EffectiveGraphView):
        raise ContractValidationError(
            "relation projection cold diagnostic effective graph view is invalid"
        )
    if _ACTIVE_QUERY_EXECUTION_DEADLINE.get() is not None:
        raise ContractValidationError(
            "relation projection cold diagnostic cannot run under a query deadline"
        )
    _source_graph_require_sha256(
        expected_graph_revision_fingerprint,
        "expected graph revision fingerprint",
    )
    _source_graph_require_sha256(
        expected_effective_graph_view_fingerprint,
        "expected effective graph view fingerprint",
    )

    content_snapshot = _require_effective_graph_content_snapshot(effective_graph_view)
    graph_snapshot = _build_query_graph_snapshot(effective_graph_view)
    graph_revision_fingerprint = _require_query_graph_snapshot(
        effective_graph_view=effective_graph_view,
        graph_snapshot=graph_snapshot,
    )
    if graph_revision_fingerprint != expected_graph_revision_fingerprint:
        raise ContractValidationError("relation projection cold diagnostic graph revision mismatch")
    effective_graph_view_fingerprint = sha256_json(effective_graph_view.to_dict())
    if effective_graph_view_fingerprint != expected_effective_graph_view_fingerprint:
        raise ContractValidationError(
            "relation projection cold diagnostic effective graph binding mismatch"
        )
    (
        authorized_source,
        actual_authorized_observation_hashes,
        source_access_fingerprint,
        source_session_binding_fingerprint,
    ) = _validated_effective_graph_snapshot_session_bindings(session)
    permission_lineage_fingerprint = _effective_graph_permission_lineage_fingerprint(
        session=session,
        effective_graph_view=effective_graph_view,
    )
    graph_content_fingerprint = _effective_graph_content_fingerprint(effective_graph_view)

    with content_snapshot.relation_projection_base_lock:
        before_binding_cache_entry_count = len(
            content_snapshot.relation_projection_cache_binding_snapshots
        )
        before_base_cache_entry_count = len(content_snapshot.relation_projection_bases)
    if before_binding_cache_entry_count != 0 or before_base_cache_entry_count != 0:
        raise ContractValidationError("relation projection cold diagnostic requires empty caches")

    recorder = _RelationProjectionBaseColdDiagnosticRecorder(
        clock_ns=_RELATION_PROJECTION_COLD_DIAGNOSTIC_CLOCK_NS
    )
    precompute = _precompute_relation_projection_base_impl(
        session=session,
        effective_graph_view=effective_graph_view,
        diagnostic_recorder=recorder,
    )

    with content_snapshot.relation_projection_base_lock:
        after_binding_cache_entry_count = len(
            content_snapshot.relation_projection_cache_binding_snapshots
        )
        after_base_cache_entry_count = len(content_snapshot.relation_projection_bases)
        binding_fingerprint_present = any(
            isinstance(snapshot, _RelationProjectionCacheBindingSnapshot)
            and snapshot.cache_binding_fingerprint == precompute.cache_binding_fingerprint
            for snapshot in (content_snapshot.relation_projection_cache_binding_snapshots.values())
        )
        base_fingerprint_present = (
            precompute.cache_binding_fingerprint in content_snapshot.relation_projection_bases
        )
    if (
        after_binding_cache_entry_count != 1
        or after_base_cache_entry_count != 1
        or not binding_fingerprint_present
        or not base_fingerprint_present
        or recorder.binding_started_at_ns is None
        or recorder.binding_elapsed_ms is None
        or recorder.binding_invocation_count != 1
        or recorder.binding_publication_count != 1
        or recorder.base_builder_started_at_ns is None
        or recorder.base_builder_elapsed_ms is None
        or recorder.base_builder_invocation_count != 1
        or recorder.base_publication_count != 1
    ):
        raise ContractValidationError("relation projection cold diagnostic publication mismatch")

    if (
        precompute.authorized_observation_count != len(actual_authorized_observation_hashes)
        or authorized_source.workspace_id != session.workspace_id
    ):
        raise ContractValidationError("relation projection cold diagnostic source binding mismatch")
    safe_payload = {
        "graph_revision_fingerprint": graph_revision_fingerprint,
        "graph_content_fingerprint": graph_content_fingerprint,
        "effective_graph_view_fingerprint": effective_graph_view_fingerprint,
        "source_session_binding_fingerprint": (source_session_binding_fingerprint),
        "source_access_fingerprint": source_access_fingerprint,
        "permission_lineage_fingerprint": permission_lineage_fingerprint,
        "index_fingerprint": precompute.index_fingerprint,
        "tokenizer_profile_fingerprint": (precompute.tokenizer_profile_fingerprint),
        "authorized_observation_set_fingerprint": (
            precompute.authorized_observation_set_fingerprint
        ),
        "candidate_set_fingerprint": precompute.candidate_set_fingerprint,
        "cache_binding_fingerprint": precompute.cache_binding_fingerprint,
        "relation_projection_base_precompute_fingerprint": (precompute.precompute_fingerprint),
        "before_binding_cache_entry_count": (before_binding_cache_entry_count),
        "before_base_cache_entry_count": before_base_cache_entry_count,
        "after_binding_cache_entry_count": after_binding_cache_entry_count,
        "after_base_cache_entry_count": after_base_cache_entry_count,
        "binding_started": True,
        "binding_completed": True,
        "binding_elapsed_ms": recorder.binding_elapsed_ms,
        "binding_invocation_count": recorder.binding_invocation_count,
        "binding_publication_status": "published",
        "base_builder_started": True,
        "base_builder_completed": True,
        "base_builder_elapsed_ms": recorder.base_builder_elapsed_ms,
        "base_builder_invocation_count": (recorder.base_builder_invocation_count),
        "base_publication_status": "published",
        "authorized_observation_count": (precompute.authorized_observation_count),
        "candidate_count": precompute.candidate_count,
        "projected_node_count": precompute.projected_node_count,
        "observation_bound_node_group_count": (precompute.observation_bound_node_group_count),
        "adjacency_node_count": precompute.adjacency_node_count,
        "adjacency_transition_count": precompute.adjacency_transition_count,
        "authorized_index_vocabulary_hash_count": (
            precompute.authorized_index_vocabulary_hash_count
        ),
        "authorized_graph_vocabulary_hash_count": (
            precompute.authorized_graph_vocabulary_hash_count
        ),
    }
    diagnostic = RelationProjectionBaseColdDiagnostic(
        **safe_payload,
        diagnostic_fingerprint=sha256_json(
            {
                "artifact_id": ("formowl_issue56_relation_projection_base_cold_diagnostic_v1"),
                "schema_version": 1,
                "status": "passed",
                "claim_boundary": ("diagnostic_only_not_query_or_methodology_evidence"),
                "deadline_mode": "offline_no_query_deadline",
                **safe_payload,
            }
        ),
    )
    diagnostic.to_safe_dict()
    return diagnostic


def _precompute_relation_projection_base_impl(
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
    diagnostic_recorder: (_RelationProjectionBaseColdDiagnosticRecorder | None) = None,
) -> RelationProjectionBasePrecompute:
    _validate_hybrid_index_runtime(session.index)
    if effective_graph_view.requester_user_id != session.requester_user_id:
        raise ContractValidationError("effective graph requester mismatch")
    _validate_source_neutral_semantic_session(
        session=session,
        effective_graph_view=effective_graph_view,
    )
    if (
        session.authorized_source is None
        or session.authorized_source.workspace_id != session.workspace_id
        or session.authorized_source.source_scope_ids != session.authorized_source_scope_ids
        or session.index.selected_bundle_count != len(session.selected_source_scope_ids)
        or session.index.authorized_bundle_count != len(session.authorized_source_scope_ids)
        or session.index.denied_bundle_count
        != len(session.selected_source_scope_ids) - len(session.authorized_source_scope_ids)
    ):
        raise ContractValidationError("relation projection session source binding mismatch")
    authorized_observation_hash_by_id = dict(session.authorized_observation_hashes)
    if (
        not authorized_observation_hash_by_id
        or tuple(sorted(authorized_observation_hash_by_id.items()))
        != session.authorized_observation_hashes
        or tuple(
            sorted(
                (
                    observation.observation_id,
                    sha256_json(observation.to_dict()),
                )
                for observation in session.authorized_observations
            )
        )
        != session.authorized_observation_hashes
    ):
        raise ContractValidationError("relation projection session Observation binding mismatch")
    tokenizer_profile = session.index._runtime_components.tokenizer_profile
    if tokenizer_profile.profile_fingerprint != session.index.profile_fingerprint:
        raise ContractValidationError("relation projection tokenizer/index mismatch")
    candidates_by_hash = {
        candidate.source_observation_hash: candidate for candidate in session.index.candidates
    }
    _validated_relation_projection_candidates(
        index=session.index,
        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        candidates_by_hash=candidates_by_hash,
        authorized_source=session.authorized_source,
    )
    graph_snapshot = _build_query_graph_snapshot(effective_graph_view)
    projection_base = _relation_projection_base(
        index=session.index,
        effective_graph_view=effective_graph_view,
        tokenizer_profile=tokenizer_profile,
        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        candidates_by_hash=candidates_by_hash,
        graph_snapshot=graph_snapshot,
        diagnostic_recorder=diagnostic_recorder,
    )
    cache_binding_snapshot = _relation_projection_base_cache_binding_snapshot(
        index=session.index,
        effective_graph_view=effective_graph_view,
        tokenizer_profile=tokenizer_profile,
        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        candidates_by_hash=candidates_by_hash,
        graph_snapshot=graph_snapshot,
    )
    if (
        projection_base.cache_binding_fingerprint
        != cache_binding_snapshot.cache_binding_fingerprint
        or projection_base.authorized_observation_set_fingerprint
        != cache_binding_snapshot.authorized_observation_set_fingerprint
        or projection_base.candidate_set_fingerprint
        != cache_binding_snapshot.candidate_set_fingerprint
    ):
        raise ContractValidationError("relation projection base precompute binding mismatch")
    safe_payload = {
        "cache_binding_fingerprint": projection_base.cache_binding_fingerprint,
        "graph_revision_fingerprint": graph_snapshot.graph_revision_fingerprint,
        "index_fingerprint": session.index.index_fingerprint,
        "tokenizer_profile_fingerprint": tokenizer_profile.profile_fingerprint,
        "authorized_observation_set_fingerprint": (
            projection_base.authorized_observation_set_fingerprint
        ),
        "candidate_set_fingerprint": projection_base.candidate_set_fingerprint,
        "authorized_observation_count": len(authorized_observation_hash_by_id),
        "candidate_count": len(candidates_by_hash),
        "projected_node_count": len(projection_base.node_by_id),
        "observation_bound_node_group_count": len(projection_base.graph_nodes_by_observation_hash),
        "adjacency_node_count": len(projection_base.adjacency),
        "adjacency_transition_count": sum(
            len(transitions) for transitions in projection_base.adjacency.values()
        ),
        "authorized_index_vocabulary_hash_count": len(
            projection_base.authorized_index_vocabulary_hashes
        ),
        "authorized_graph_vocabulary_hash_count": len(
            projection_base.authorized_graph_vocabulary_hashes
        ),
    }
    precompute = RelationProjectionBasePrecompute(
        **safe_payload,
        precompute_fingerprint=sha256_json(
            {
                "artifact_id": "formowl_issue56_relation_projection_base_precompute_v1",
                **safe_payload,
            }
        ),
    )
    precompute.to_safe_dict()
    return precompute


def run_authorized_hybrid_mail_query(
    *,
    observations_by_bundle_id: Mapping[str, Sequence[Observation]],
    bundles: Sequence[MailEvidenceBundle],
    query_text: str,
    query_class: str,
    requester_user_id: str,
    workspace_id: str,
    expected_profile_fingerprint: str | None = None,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
    mail_import_session_id: str | None = None,
    mail_evidence_bundle_id: str | None = None,
    candidate_limit: int = 12,
    result_limit: int = 5,
) -> GovernedHybridRagResult:
    """Run the bounded authorized Observation-to-result Issue #56 POC path."""

    _validate_hybrid_query_inputs(
        query_text=query_text,
        query_class=query_class,
        candidate_limit=candidate_limit,
        result_limit=result_limit,
    )
    selected_bundles = matching_bundles(
        bundles,
        mail_import_session_id=mail_import_session_id,
        mail_evidence_bundle_id=mail_evidence_bundle_id,
    )
    authorized_bundles = authorize_mail_evidence_bundles(
        selected_bundles,
        requester_user_id=requester_user_id,
        workspace_id=workspace_id,
        grants=grants,
        now=now,
    )
    runtime_components = _require_issue56_runtime_components(
        expected_profile_fingerprint=expected_profile_fingerprint,
    )
    if query_class in _BLOCKED_QUERY_CLASSES:
        return _route_blocked_result(
            query_hash=sha256_json(query_text),
            query_class=query_class,
            runtime_components=runtime_components,
            selected_bundle_count=len(selected_bundles),
            authorized_bundle_count=len(authorized_bundles),
            denied_bundle_count=len(selected_bundles) - len(authorized_bundles),
        )
    index = build_authorized_hybrid_mail_index(
        observations_by_bundle_id=observations_by_bundle_id,
        bundles=selected_bundles,
        requester_user_id=requester_user_id,
        workspace_id=workspace_id,
        expected_profile_fingerprint=expected_profile_fingerprint,
        grants=grants,
        now=now,
    )
    return index.query(
        query_text=query_text,
        query_class=query_class,
        candidate_limit=candidate_limit,
        result_limit=result_limit,
    )


def run_authorized_semantic_mail_query(
    *,
    observations_by_bundle_id: Mapping[str, Sequence[Observation]],
    bundles: Sequence[MailEvidenceBundle],
    query_text: str,
    requester_user_id: str,
    workspace_id: str,
    effective_graph_view: EffectiveGraphView,
    expected_profile_fingerprint: str | None = None,
    allowed_relation_types: Sequence[str] = (),
    allowed_directions: Sequence[str] = ("out",),
    seed_node_ids: Sequence[str] = (),
    target_core_supertype_id: str | None = None,
    exact_inventory_kind: str | None = None,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
    mail_import_session_id: str | None = None,
    mail_evidence_bundle_id: str | None = None,
    limits: SemanticPlanLimits = DEFAULT_SEMANTIC_PLAN_LIMITS,
    enable_entity_signal: bool = True,
    enable_graph_traversal: bool = True,
    legacy_hard_gate: bool = False,
    phase_trace: SemanticPhaseTrace | None = None,
) -> GovernedSemanticExecutionResult:
    """Execute one revision-pinned semantic plan over authorized evidence and graph."""

    session = build_authorized_semantic_mail_session(
        observations_by_bundle_id=observations_by_bundle_id,
        bundles=bundles,
        requester_user_id=requester_user_id,
        workspace_id=workspace_id,
        expected_profile_fingerprint=expected_profile_fingerprint,
        grants=grants,
        now=now,
        mail_import_session_id=mail_import_session_id,
        mail_evidence_bundle_id=mail_evidence_bundle_id,
    )
    return session.query(
        query_text=query_text,
        effective_graph_view=effective_graph_view,
        allowed_relation_types=allowed_relation_types,
        allowed_directions=allowed_directions,
        seed_node_ids=seed_node_ids,
        target_core_supertype_id=target_core_supertype_id,
        exact_inventory_kind=exact_inventory_kind,
        limits=limits,
        enable_entity_signal=enable_entity_signal,
        enable_graph_traversal=enable_graph_traversal,
        legacy_hard_gate=legacy_hard_gate,
        phase_trace=phase_trace,
    )


def _hybrid_candidates_from_snippet_index(
    snippet_index: MailSnippetIndex,
    *,
    dense_encoder: DenseEncoder,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    coherence_group_hash_by_message_id: Mapping[str, str],
) -> list[_HybridCandidate]:
    candidates: list[_HybridCandidate] = []
    for snippet in snippet_index.snippets:
        message_id = snippet.payload.get("email_message_id")
        if not isinstance(message_id, str) or not message_id:
            raise ContractValidationError("mail evidence message lineage is unavailable")
        coherence_group_hash = coherence_group_hash_by_message_id.get(message_id)
        if coherence_group_hash is None:
            raise ContractValidationError("mail evidence coherence lineage is unavailable")
        candidates.append(
            _hybrid_candidate_from_snippet(
                snippet,
                dense_encoder=dense_encoder,
                tokenizer_profile=tokenizer_profile,
                coherence_group_hash=coherence_group_hash,
            )
        )
    return candidates


def _mail_coherence_group_hash(
    *,
    bundle_id: str,
    message_id: str,
    thread_id: str | None,
) -> str:
    """Bind evidence to one source-defined thread, falling back to one message."""

    if isinstance(thread_id, str) and thread_id.strip():
        payload = {
            "coherence_kind": "mail_thread",
            "bundle_id": bundle_id,
            "thread_id": thread_id,
        }
    else:
        payload = {
            "coherence_kind": "mail_message",
            "bundle_id": bundle_id,
            "message_id": message_id,
        }
    return sha256_json(payload)


def _required_snippet_source_observation_id(payload: Mapping[str, Any]) -> str:
    observation_id = payload.get("source_observation_id")
    if not isinstance(observation_id, str) or not observation_id:
        raise ContractValidationError("Observation candidate lineage is unavailable")
    return observation_id


def _hybrid_candidate_from_observation_snippet(
    snippet: IndexedObservationSnippet,
    *,
    authorized_source: AuthorizedSemanticSource,
    observation: Observation,
    occurrence_lineage: SourceOccurrenceLineage,
    dense_encoder: DenseEncoder,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    dense_vector: Sequence[float] | None = None,
) -> _HybridCandidate:
    observation_id = _required_snippet_source_observation_id(snippet.payload)
    if observation_id != observation.observation_id:
        raise ContractValidationError("Observation candidate lineage mismatch")
    if (
        snippet.source_access_fingerprint != authorized_source.authorization_fingerprint
        or snippet.payload.get("source_kind") != authorized_source.source_kind
        or occurrence_lineage.source_kind != authorized_source.source_kind
        or occurrence_lineage.source_observation_id != observation_id
    ):
        raise ContractValidationError("Observation candidate source binding mismatch")
    source_observation_hash = sha256_json(observation.to_dict())
    source_occurrence_hash = sha256_json(occurrence_lineage.occurrence_id)
    expected_parent_hash = (
        sha256_json(occurrence_lineage.parent_occurrence_id)
        if occurrence_lineage.parent_occurrence_id is not None
        else None
    )
    if (
        snippet.source_observation_hash != source_observation_hash
        or snippet.payload.get("source_occurrence_hash") != source_occurrence_hash
        or snippet.payload.get("source_occurrence_kind") != occurrence_lineage.occurrence_kind
        or snippet.payload.get("parent_source_occurrence_hash") != expected_parent_hash
    ):
        raise ContractValidationError("Observation candidate occurrence lineage mismatch")
    observation_text = snippet.payload.get("snippet")
    expected_observation_text = observation.text or observation.caption or ""
    if not isinstance(observation_text, str) or observation_text != expected_observation_text:
        raise ContractValidationError("Observation candidate text lineage mismatch")
    source_scope_id = _observation_source_scope_id(
        observation,
        authorized_source=authorized_source,
    )
    observation_analysis = tokenizer_profile.analyze(observation_text)
    observation_tokens = frozenset(observation_analysis.tokens)
    observation_protected_tokens = frozenset(
        span.exact_token for span in observation_analysis.protected_identifiers
    )
    coherence_group_hash = _source_occurrence_coherence_group_hash(
        authorized_source=authorized_source,
        source_scope_id=source_scope_id,
        occurrence_lineage=occurrence_lineage,
    )
    dense_evidence_text_hash = sha256_json(snippet.dense_evidence_text)
    index_binding_hash = sha256_json(
        {
            "source_access_fingerprint": authorized_source.authorization_fingerprint,
            "source_observation_hash": source_observation_hash,
            "source_occurrence_hash": source_occurrence_hash,
            "dense_evidence_text_hash": dense_evidence_text_hash,
        }
    )
    return _HybridCandidate(
        bundle_id=source_scope_id,
        coherence_group_hash=coherence_group_hash,
        source_observation_hash=source_observation_hash,
        message_hash=source_occurrence_hash,
        message_occurrence_hash=source_occurrence_hash,
        index_binding_hash=index_binding_hash,
        searchable_tokens=frozenset(snippet.searchable_tokens),
        protected_identifier_tokens=frozenset(snippet.protected_identifier_tokens),
        observation_tokens=observation_tokens,
        observation_protected_identifier_tokens=observation_protected_tokens,
        dense_evidence_text_hash=dense_evidence_text_hash,
        dense_vector=(
            tuple(float(value) for value in dense_vector)
            if dense_vector is not None
            else dense_encoder.encode_evidence(snippet.dense_evidence_text)
        ),
    )


def _encode_authorized_evidence_vectors(
    dense_encoder: DenseEncoder,
    texts: Sequence[str],
) -> tuple[tuple[float, ...], ...]:
    """Encode source-authorized snippets in index order without weakening runtime checks."""

    ordered_texts = tuple(texts)
    batch_encoder = getattr(dense_encoder, "encode_evidence_batch", None)
    if callable(batch_encoder):
        encoded = tuple(
            tuple(float(value) for value in vector)
            for vector in batch_encoder(ordered_texts)
        )
        if len(encoded) != len(ordered_texts):
            raise DenseEmbeddingUnavailableError("dense_batch_output_count_mismatch")
        return encoded
    if (
        getattr(dense_encoder, "encoder_id", None) == ISSUE56_TARGET_DENSE_ENCODER_ID
        and getattr(dense_encoder, "profile_fingerprint", None)
        == ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT
    ):
        raise DenseEmbeddingUnavailableError("dense_evidence_batch_unavailable")
    return tuple(
        tuple(float(value) for value in dense_encoder.encode_evidence(text))
        for text in ordered_texts
    )


def _source_occurrence_coherence_group_hash(
    *,
    authorized_source: AuthorizedSemanticSource,
    source_scope_id: str,
    occurrence_lineage: SourceOccurrenceLineage,
) -> str:
    root_occurrence_id = occurrence_lineage.parent_occurrence_id or occurrence_lineage.occurrence_id
    return sha256_json(
        {
            "coherence_kind": "typed_source_occurrence",
            "source_kind": authorized_source.source_kind,
            "source_scope_id": source_scope_id,
            "root_occurrence_hash": sha256_json(root_occurrence_id),
        }
    )


def _hybrid_candidate_content_fingerprint(candidate: _HybridCandidate) -> str:
    return sha256_json(
        {
            "source_scope_id": candidate.bundle_id,
            "coherence_group_hash": candidate.coherence_group_hash,
            "source_observation_hash": candidate.source_observation_hash,
            "source_occurrence_hash": candidate.message_occurrence_hash,
            "index_binding_hash": candidate.index_binding_hash,
            "token_hashes": sorted(sha256_json(token) for token in candidate.searchable_tokens),
            "protected_identifier_hashes": sorted(
                sha256_json(token) for token in candidate.protected_identifier_tokens
            ),
            "observation_token_hashes": sorted(
                sha256_json(token) for token in candidate.observation_tokens
            ),
            "observation_protected_identifier_hashes": sorted(
                sha256_json(token) for token in candidate.observation_protected_identifier_tokens
            ),
            "dense_evidence_text_hash": candidate.dense_evidence_text_hash,
            "dense_vector": [_metric(value) for value in candidate.dense_vector],
        }
    )


def _authorized_observation_hashes(
    *,
    observations_by_bundle_id: Mapping[str, Sequence[Observation]],
    authorized_bundles: Sequence[MailEvidenceBundle],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for bundle in sorted(
        authorized_bundles,
        key=lambda item: item.mail_evidence_bundle_id,
    ):
        observations = observations_by_bundle_id.get(bundle.mail_evidence_bundle_id)
        if observations is None:
            raise ContractValidationError("authorized mail evidence observations are unavailable")
        for observation in observations:
            if not isinstance(observation, Observation):
                raise ContractValidationError(
                    "authorized mail evidence requires Observation records"
                )
            validated = Observation.from_dict(observation.to_dict())
            observation_hash = sha256_json(validated.to_dict())
            existing = hashes.get(validated.observation_id)
            if existing is not None and existing != observation_hash:
                raise ContractValidationError("authorized Observation lineage is inconsistent")
            hashes[validated.observation_id] = observation_hash
    return hashes


def _validated_source_neutral_inputs(
    *,
    authorized_source: AuthorizedSemanticSource,
    authorized_observations: Sequence[Observation],
    occurrence_lineages: Sequence[SourceOccurrenceLineage],
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[
    tuple[Observation, ...],
    tuple[SourceOccurrenceLineage, ...],
    dict[str, str],
]:
    observation_by_id: dict[str, Observation] = {}
    authorized_hash_by_id: dict[str, str] = {}
    for observation in authorized_observations:
        _query_deadline_checkpoint(execution_deadline)
        if not isinstance(observation, Observation):
            raise ContractValidationError(
                "authorized semantic session requires Observation records"
            )
        validated = _sealed_source_neutral_observation(observation)
        if validated.observation_id in observation_by_id:
            raise ContractValidationError(
                "authorized semantic session has duplicate Observation ids"
            )
        _observation_source_scope_id(
            validated,
            authorized_source=authorized_source,
        )
        observation_by_id[validated.observation_id] = validated
        authorized_hash_by_id[validated.observation_id] = sha256_json(validated.to_dict())
    if not observation_by_id:
        raise ContractValidationError(
            "authorized semantic session requires authorized Observations"
        )

    normalized_lineages = normalized_authorized_observation_lineages(
        tuple(observation_by_id.values()),
        authorized_source=authorized_source,
        occurrence_lineages=occurrence_lineages,
    )
    lineage_by_observation_id = {
        lineage.source_observation_id: lineage for lineage in normalized_lineages
    }
    return (
        tuple(observation_by_id[key] for key in sorted(observation_by_id)),
        tuple(lineage_by_observation_id[key] for key in sorted(lineage_by_observation_id)),
        authorized_hash_by_id,
    )


def _sealed_source_neutral_observation(observation: Observation) -> Observation:
    """Copy and recursively seal one build-boundary Observation."""

    validated = Observation.from_dict(observation.to_dict())
    return replace(
        validated,
        location=_freeze_graph_json_value(validated.location),
        permission_scope=_freeze_graph_json_value(
            to_plain(validated.permission_scope)
        ),
        payload=(
            _freeze_graph_json_value(validated.payload)
            if validated.payload is not None
            else None
        ),
        extracted_value=(
            _freeze_graph_json_value(validated.extracted_value)
            if validated.extracted_value is not None
            else None
        ),
    )


def _observation_source_scope_id(
    observation: Observation,
    *,
    authorized_source: AuthorizedSemanticSource,
    require_exact_permission_binding: bool = True,
) -> str:
    permission_scope = to_plain(observation.permission_scope)
    if not isinstance(permission_scope, dict):
        raise ContractValidationError("authorized semantic Observation permission scope is invalid")
    source_scope_id = permission_scope.get("scope_id")
    if (
        not isinstance(source_scope_id, str)
        or not source_scope_id
        or source_scope_id not in authorized_source.source_scope_ids
        or (
            require_exact_permission_binding
            and not authorized_permission_scope_matches(
                permission_scope,
                authorized_source=authorized_source,
            )
        )
    ):
        raise ContractValidationError("authorized semantic Observation permission scope mismatch")
    return source_scope_id


def _source_neutral_session_binding_fingerprint(
    *,
    authorized_source: AuthorizedSemanticSource,
    index: AuthorizedHybridMailIndex,
    authorized_observations: Sequence[Observation],
    occurrence_lineages: Sequence[SourceOccurrenceLineage],
) -> str:
    return sha256_json(
        {
            "schema_version": 1,
            "source_access_fingerprint": authorized_source.authorization_fingerprint,
            "index_fingerprint": index.index_fingerprint,
            "authorized_observation_hashes": sorted(
                sha256_json(observation.to_dict()) for observation in authorized_observations
            ),
            "occurrence_lineage_fingerprints": sorted(
                lineage.lineage_fingerprint for lineage in occurrence_lineages
            ),
        }
    )


def _mail_compatibility_session_binding_fingerprint(
    *,
    authorized_source: AuthorizedSemanticSource,
    index: AuthorizedHybridMailIndex,
    requester_user_id: str,
    workspace_id: str,
    selected_source_scope_ids: Sequence[str],
    authorized_source_scope_ids: Sequence[str],
    retrieval_observation_hashes: Sequence[tuple[str, str]],
    authorized_observations: Sequence[Observation],
    occurrence_lineages: Sequence[SourceOccurrenceLineage],
) -> str:
    return sha256_json(
        {
            "schema_version": 1,
            "session_kind": "authorized_semantic_mail_session",
            "requester_fingerprint": sha256_json(requester_user_id),
            "workspace_fingerprint": sha256_json(workspace_id),
            "selected_source_scope_hashes": [
                sha256_json(source_scope_id) for source_scope_id in selected_source_scope_ids
            ],
            "authorized_source_scope_hashes": [
                sha256_json(source_scope_id) for source_scope_id in authorized_source_scope_ids
            ],
            "source_access_fingerprint": authorized_source.authorization_fingerprint,
            "index_fingerprint": index.index_fingerprint,
            "runtime_method_fingerprint": index.execution_component_fingerprint,
            "retrieval_observation_binding_hashes": [
                sha256_json([observation_id, observation_hash])
                for observation_id, observation_hash in retrieval_observation_hashes
            ],
            "authorized_observation_binding_hashes": [
                sha256_json(
                    [
                        observation.observation_id,
                        sha256_json(observation.to_dict()),
                    ]
                )
                for observation in sorted(
                    authorized_observations,
                    key=lambda item: item.observation_id,
                )
            ],
            "occurrence_lineage_fingerprints": sorted(
                lineage.lineage_fingerprint for lineage in occurrence_lineages
            ),
            "candidate_content_fingerprints": sorted(
                _hybrid_candidate_content_fingerprint(candidate) for candidate in index.candidates
            ),
        }
    )


def _validated_effective_graph_snapshot_session_bindings(
    session: AuthorizedSemanticMailSession,
) -> tuple[
    AuthorizedSemanticSource,
    tuple[tuple[str, str], ...],
    str,
    str,
]:
    authorized_source = session.authorized_source
    selected_source_scope_ids = session.selected_source_scope_ids
    authorized_source_scope_ids = session.authorized_source_scope_ids
    if (
        authorized_source is None
        or authorized_source.workspace_id != session.workspace_id
        or authorized_source.source_scope_ids != authorized_source_scope_ids
        or not selected_source_scope_ids
        or selected_source_scope_ids != tuple(sorted(set(selected_source_scope_ids)))
        or not authorized_source_scope_ids
        or authorized_source_scope_ids != tuple(sorted(set(authorized_source_scope_ids)))
        or not set(authorized_source_scope_ids).issubset(selected_source_scope_ids)
        or session.index.selected_bundle_count != len(selected_source_scope_ids)
        or session.index.authorized_bundle_count != len(authorized_source_scope_ids)
        or session.index.denied_bundle_count
        != len(selected_source_scope_ids) - len(authorized_source_scope_ids)
    ):
        raise ContractValidationError("graph snapshot precompute source scope binding mismatch")
    if not _is_mail_compatibility_session(session) and (
        selected_source_scope_ids != authorized_source_scope_ids
        or session.index.denied_bundle_count != 0
    ):
        raise ContractValidationError("graph snapshot precompute source scope binding mismatch")

    observation_by_id: dict[str, Observation] = {}
    actual_authorized_observation_hashes: list[tuple[str, str]] = []
    for observation in session.authorized_observations:
        if not isinstance(observation, Observation):
            raise ContractValidationError(
                "graph snapshot precompute requires authorized Observation records"
            )
        validated = Observation.from_dict(observation.to_dict())
        if validated.observation_id in observation_by_id:
            raise ContractValidationError("graph snapshot precompute has duplicate Observation ids")
        observation_by_id[validated.observation_id] = validated
        actual_authorized_observation_hashes.append(
            (validated.observation_id, sha256_json(validated.to_dict()))
        )
    frozen_authorized_observation_hashes = tuple(sorted(actual_authorized_observation_hashes))
    if (
        not frozen_authorized_observation_hashes
        or frozen_authorized_observation_hashes != session.authorized_observation_hashes
    ):
        raise ContractValidationError("graph snapshot precompute Observation binding mismatch")
    authorized_observation_hash_by_id = dict(frozen_authorized_observation_hashes)
    if (
        not session.retrieval_observation_hashes
        or tuple(sorted(session.retrieval_observation_hashes))
        != session.retrieval_observation_hashes
        or any(
            authorized_observation_hash_by_id.get(observation_id) != observation_hash
            for observation_id, observation_hash in session.retrieval_observation_hashes
        )
    ):
        raise ContractValidationError(
            "graph snapshot precompute retrieval Observation binding mismatch"
        )

    source_access_fingerprint = _source_graph_require_sha256(
        authorized_source.authorization_fingerprint,
        "source authorization fingerprint",
    )
    if not _is_mail_compatibility_session(session):
        source_session_binding_fingerprint = _source_graph_require_sha256(
            session.source_session_binding_fingerprint,
            "source session binding fingerprint",
        )
        return (
            authorized_source,
            frozen_authorized_observation_hashes,
            source_access_fingerprint,
            source_session_binding_fingerprint,
        )

    if authorized_source.source_kind != AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND:
        raise ContractValidationError("graph snapshot precompute mail source kind mismatch")
    authorized_observation_hashes = frozenset(
        observation_hash
        for _observation_id, observation_hash in frozen_authorized_observation_hashes
    )
    if (
        session.index.candidates is not session.index._relation_projection_candidates_snapshot
        or any(
            candidate.bundle_id not in authorized_source_scope_ids
            or candidate.source_observation_hash not in authorized_observation_hashes
            for candidate in session.index.candidates
        )
    ):
        raise ContractValidationError("graph snapshot precompute mail index binding mismatch")

    lineage_by_observation_id: dict[str, SourceOccurrenceLineage] = {}
    for lineage in session.occurrence_lineages:
        observation_id = getattr(lineage, "source_observation_id", None)
        if (
            not isinstance(observation_id, str)
            or observation_id not in observation_by_id
            or observation_id in lineage_by_observation_id
        ):
            raise ContractValidationError(
                "graph snapshot precompute mail occurrence lineage is invalid"
            )
        lineage_by_observation_id[observation_id] = lineage
    expected_lineage_observation_ids = {
        observation_id
        for observation_id, observation in observation_by_id.items()
        if _observation_message_occurrence_id(observation) is not None
    }
    if set(lineage_by_observation_id) != expected_lineage_observation_ids:
        raise ContractValidationError(
            "graph snapshot precompute mail occurrence lineage is incomplete"
        )
    for observation_id, lineage in lineage_by_observation_id.items():
        if lineage != source_occurrence_lineage_from_observation(
            observation_by_id[observation_id],
            authorized_source=authorized_source,
        ):
            raise ContractValidationError(
                "graph snapshot precompute mail occurrence lineage mismatch"
            )

    source_session_binding_fingerprint = _mail_compatibility_session_binding_fingerprint(
        authorized_source=authorized_source,
        index=session.index,
        requester_user_id=session.requester_user_id,
        workspace_id=session.workspace_id,
        selected_source_scope_ids=selected_source_scope_ids,
        authorized_source_scope_ids=authorized_source_scope_ids,
        retrieval_observation_hashes=session.retrieval_observation_hashes,
        authorized_observations=tuple(
            observation_by_id[observation_id] for observation_id in sorted(observation_by_id)
        ),
        occurrence_lineages=tuple(
            lineage_by_observation_id[observation_id]
            for observation_id in sorted(lineage_by_observation_id)
        ),
    )
    if session.source_session_binding_fingerprint != source_session_binding_fingerprint:
        raise ContractValidationError("graph snapshot precompute mail session binding mismatch")
    return (
        authorized_source,
        frozen_authorized_observation_hashes,
        source_access_fingerprint,
        source_session_binding_fingerprint,
    )


def _effective_graph_permission_lineage_fingerprint(
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
) -> str:
    permission_fingerprint_by_observation_id: dict[str, str] = {}
    for observation in session.authorized_observations:
        permission_scope = to_plain(observation.permission_scope)
        if not isinstance(permission_scope, dict):
            raise ContractValidationError(
                "graph snapshot precompute Observation permission scope is invalid"
            )
        permission_fingerprint_by_observation_id[observation.observation_id] = sha256_json(
            permission_scope
        )

    for label, items in (
        ("node", effective_graph_view.visible_nodes),
        ("edge", effective_graph_view.visible_edges),
    ):
        for item in items:
            source_observation_ids = item.properties.get("source_observation_ids")
            item_permission_scope = to_plain(item.permission_scope)
            if (
                not isinstance(source_observation_ids, (list, tuple))
                or not source_observation_ids
                or len(set(source_observation_ids)) != len(source_observation_ids)
                or any(
                    not isinstance(observation_id, str)
                    or observation_id not in permission_fingerprint_by_observation_id
                    for observation_id in source_observation_ids
                )
                or not isinstance(item_permission_scope, dict)
            ):
                raise ContractValidationError(
                    f"graph snapshot precompute {label} permission lineage is invalid"
                )
            item_permission_fingerprint = sha256_json(item_permission_scope)
            if any(
                permission_fingerprint_by_observation_id[observation_id]
                != item_permission_fingerprint
                for observation_id in source_observation_ids
            ):
                raise ContractValidationError(
                    f"graph snapshot precompute {label} permission lineage mismatch"
                )

    return sha256_json(
        {
            "schema_version": 1,
            "observation_permission_bindings": [
                {
                    "observation_hash": sha256_json(observation.to_dict()),
                    "permission_scope_fingerprint": sha256_json(
                        to_plain(observation.permission_scope)
                    ),
                }
                for observation in sorted(
                    session.authorized_observations,
                    key=lambda item: item.observation_id,
                )
            ],
            "graph_node_permission_bindings": [
                {
                    "node_hash": sha256_json(node.to_dict()),
                    "permission_scope_fingerprint": sha256_json(to_plain(node.permission_scope)),
                    "source_observation_hashes": sorted(
                        sha256_json(source_id)
                        for source_id in node.properties.get(
                            "source_observation_ids",
                            (),
                        )
                        if isinstance(source_id, str)
                    ),
                }
                for node in sorted(
                    effective_graph_view.visible_nodes,
                    key=lambda item: item.node_id,
                )
            ],
            "graph_edge_permission_bindings": [
                {
                    "edge_hash": sha256_json(edge.to_dict()),
                    "permission_scope_fingerprint": sha256_json(to_plain(edge.permission_scope)),
                    "source_observation_hashes": sorted(
                        sha256_json(source_id)
                        for source_id in edge.properties.get(
                            "source_observation_ids",
                            (),
                        )
                        if isinstance(source_id, str)
                    ),
                }
                for edge in sorted(
                    effective_graph_view.visible_edges,
                    key=lambda item: item.edge_id,
                )
            ],
        }
    )


def _validate_source_neutral_query_session(
    *,
    session: AuthorizedSemanticObservationSession,
    effective_graph_view: EffectiveGraphView,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> None:
    """Validate one query against the fully validated build-time identity."""

    _query_deadline_checkpoint(execution_deadline)
    if _is_mail_compatibility_session(session):
        return
    authorized_source = session.authorized_source
    if (
        authorized_source is None
        or authorized_source.workspace_id != session.workspace_id
        or authorized_source.source_scope_ids != session.authorized_source_scope_ids
        or session.selected_source_scope_ids != session.authorized_source_scope_ids
        or session.index.selected_bundle_count != len(session.selected_source_scope_ids)
        or session.index.authorized_bundle_count
        != len(session.authorized_source_scope_ids)
        or session.index.denied_bundle_count != 0
    ):
        raise ContractValidationError(
            "authorized semantic session source binding mismatch"
        )
    content_snapshot = _require_effective_graph_content_snapshot(
        effective_graph_view
    )
    if not _source_neutral_session_snapshot_binding_matches(
        content_snapshot.source_neutral_session_binding,
        session,
    ):
        raise ContractValidationError("authorized semantic session binding mismatch")
    _validate_precomputed_hybrid_graph_binding(
        index=session.index,
        graph_revision_fingerprint=content_snapshot.graph_revision_fingerprint,
    )
    _query_deadline_checkpoint(execution_deadline)


def _validate_source_neutral_semantic_session(
    *,
    session: AuthorizedSemanticObservationSession,
    effective_graph_view: EffectiveGraphView,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> None:
    _query_deadline_checkpoint(execution_deadline)
    if _is_mail_compatibility_session(session):
        return
    authorized_source = session.authorized_source
    if (
        authorized_source is None
        or authorized_source.workspace_id != session.workspace_id
        or authorized_source.source_scope_ids != session.authorized_source_scope_ids
        or session.selected_source_scope_ids != session.authorized_source_scope_ids
        or session.index.selected_bundle_count != len(session.selected_source_scope_ids)
        or session.index.authorized_bundle_count != len(session.authorized_source_scope_ids)
        or session.index.denied_bundle_count != 0
    ):
        raise ContractValidationError("authorized semantic session source binding mismatch")
    observations, lineages, authorized_hash_by_id = _validated_source_neutral_inputs(
        authorized_source=authorized_source,
        authorized_observations=session.authorized_observations,
        occurrence_lineages=session.occurrence_lineages,
        execution_deadline=execution_deadline,
    )
    _query_deadline_checkpoint(execution_deadline)
    if tuple(sorted(authorized_hash_by_id.items())) != session.authorized_observation_hashes:
        raise ContractValidationError("authorized semantic session Observation binding mismatch")
    retrieval_hashes = session.retrieval_observation_hashes
    retrieval_hash_by_id = dict(retrieval_hashes)
    if (
        not retrieval_hashes
        or tuple(sorted(retrieval_hashes)) != retrieval_hashes
        or len(retrieval_hash_by_id) != len(retrieval_hashes)
        or any(
            authorized_hash_by_id.get(observation_id) != observation_hash
            for observation_id, observation_hash in retrieval_hashes
        )
    ):
        raise ContractValidationError(
            "authorized semantic session retrieval binding mismatch"
        )
    if tuple(
        sorted(candidate.source_observation_hash for candidate in session.index.candidates)
    ) != tuple(sorted(retrieval_hash_by_id.values())):
        raise ContractValidationError(
            "authorized semantic session candidate retrieval binding mismatch"
        )
    expected_binding = _source_neutral_session_binding_fingerprint(
        authorized_source=authorized_source,
        index=session.index,
        authorized_observations=observations,
        occurrence_lineages=lineages,
    )
    if session.source_session_binding_fingerprint != expected_binding:
        raise ContractValidationError("authorized semantic session binding mismatch")
    _validate_source_neutral_graph_binding(
        authorized_source=authorized_source,
        index=session.index,
        effective_graph_view=effective_graph_view,
        retrieval_ids=frozenset(retrieval_hash_by_id),
        execution_deadline=execution_deadline,
    )
    _bind_source_neutral_session_to_graph_snapshot(
        session=session,
        effective_graph_view=effective_graph_view,
    )


def _source_neutral_session_snapshot_binding(
    session: AuthorizedSemanticObservationSession,
) -> tuple[Any, ...]:
    return (
        session,
        session.authorized_source,
        session.index,
        session.authorized_observations,
        session.occurrence_lineages,
        session.retrieval_observation_hashes,
        session.authorized_observation_hashes,
        session.requester_user_id,
        session.workspace_id,
        session.selected_source_scope_ids,
        session.authorized_source_scope_ids,
        session.source_session_binding_fingerprint,
    )


def _source_neutral_session_snapshot_binding_matches(
    expected: tuple[Any, ...] | None,
    session: AuthorizedSemanticObservationSession,
) -> bool:
    actual = _source_neutral_session_snapshot_binding(session)
    return (
        expected is not None
        and len(expected) == len(actual)
        and all(expected[index] is actual[index] for index in range(1, 7))
        and expected[7:] == actual[7:]
    )


def _bind_source_neutral_session_to_graph_snapshot(
    *,
    session: AuthorizedSemanticObservationSession,
    effective_graph_view: EffectiveGraphView,
) -> None:
    content_snapshot = _require_effective_graph_content_snapshot(
        effective_graph_view
    )
    existing = content_snapshot.source_neutral_session_binding
    if existing is None:
        object.__setattr__(
            content_snapshot,
            "source_neutral_session_binding",
            _source_neutral_session_snapshot_binding(session),
        )
    elif not _source_neutral_session_snapshot_binding_matches(existing, session):
        raise ContractValidationError(
            "effective graph source session binding mismatch"
        )


def _validate_source_neutral_graph_binding(
    *,
    authorized_source: AuthorizedSemanticSource,
    index: AuthorizedHybridMailIndex,
    effective_graph_view: EffectiveGraphView,
    retrieval_ids: frozenset[str],
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> None:
    _validate_precomputed_hybrid_graph_binding(
        index=index,
        graph_revision_fingerprint=_graph_revision_fingerprint(effective_graph_view),
    )

    source_kind_hash = sha256_json(authorized_source.source_kind)
    for item in (
        *effective_graph_view.visible_nodes,
        *effective_graph_view.visible_edges,
    ):
        _query_deadline_checkpoint(execution_deadline)
        source_observation_ids = item.properties.get("source_observation_ids", ())
        if not isinstance(source_observation_ids, (list, tuple)):
            raise ContractValidationError("source-neutral graph Observation lineage is invalid")
        if (
            not source_observation_ids
            or any(
                not isinstance(observation_id, str) or observation_id not in retrieval_ids
                for observation_id in source_observation_ids
            )
            or item.properties.get("source_kind_hash") != source_kind_hash
        ):
            raise ContractValidationError("source-neutral graph source kind mismatch")
        permission_scope = to_plain(item.permission_scope)
        if (
            not isinstance(permission_scope, dict)
            or not authorized_permission_scope_matches(
                permission_scope,
                authorized_source=authorized_source,
            )
        ):
            raise ContractValidationError("source-neutral graph permission scope mismatch")
    _query_deadline_checkpoint(execution_deadline)


def _validate_precomputed_hybrid_graph_binding(
    *,
    index: AuthorizedHybridMailIndex,
    graph_revision_fingerprint: str,
) -> None:
    expected = index._precomputed_graph_revision_fingerprint
    if expected is not None and expected != graph_revision_fingerprint:
        raise ContractValidationError("precomputed hybrid index graph binding mismatch")


def _source_backed_graph_inputs(
    *,
    session: AuthorizedSemanticObservationSession,
    observations_by_source_scope_id: Mapping[str, Sequence[Observation]] | None,
) -> tuple[
    dict[str, tuple[Observation, ...]],
    dict[str, SourceOccurrenceLineage],
]:
    authorized_source = session.authorized_source
    if authorized_source is None:
        if session.authorized_source_scope_ids:
            raise ContractValidationError(
                "source-backed graph authorized source binding is unavailable"
            )
        return {}, {}
    if (
        authorized_source.workspace_id != session.workspace_id
        or authorized_source.source_scope_ids != session.authorized_source_scope_ids
    ):
        raise ContractValidationError("source-backed graph authorized source mismatch")
    stored_observation_by_id = {
        observation.observation_id: Observation.from_dict(observation.to_dict())
        for observation in session.authorized_observations
    }
    stored_hash_by_id = {
        observation_id: sha256_json(observation.to_dict())
        for observation_id, observation in stored_observation_by_id.items()
    }
    if tuple(sorted(stored_hash_by_id.items())) != session.authorized_observation_hashes:
        raise ContractValidationError("source-backed graph Observation lineage mismatch")
    graph_hash_by_id = dict(session.retrieval_observation_hashes)
    if _is_mail_compatibility_session(session):
        _validated_effective_graph_snapshot_session_bindings(session)
    elif (
        not graph_hash_by_id
        or tuple(sorted(session.retrieval_observation_hashes))
        != session.retrieval_observation_hashes
        or len(graph_hash_by_id) != len(session.retrieval_observation_hashes)
        or any(
            stored_hash_by_id.get(observation_id) != observation_hash
            for observation_id, observation_hash in graph_hash_by_id.items()
        )
    ):
        raise ContractValidationError(
            "source-backed graph retrieval Observation binding mismatch"
        )
    lineage_by_observation_id = {
        lineage.source_observation_id: lineage for lineage in session.occurrence_lineages
    }
    if (
        _is_mail_compatibility_session(session)
        or set(graph_hash_by_id) != set(stored_observation_by_id)
    ):
        lineage_by_observation_id = {
            observation_id: lineage
            for observation_id, lineage in lineage_by_observation_id.items()
            if observation_id in graph_hash_by_id
        }
    if not _is_mail_compatibility_session(session) and set(lineage_by_observation_id) != set(
        graph_hash_by_id
    ):
        raise ContractValidationError("source-backed graph occurrence lineage is incomplete")

    grouped: dict[str, list[Observation]] = {
        source_scope_id: [] for source_scope_id in session.authorized_source_scope_ids
    }
    if observations_by_source_scope_id is None:
        for observation_id in graph_hash_by_id:
            observation = stored_observation_by_id[observation_id]
            grouped[
                _observation_source_scope_id(
                    observation,
                    authorized_source=authorized_source,
                    require_exact_permission_binding=not _is_mail_compatibility_session(
                        session
                    ),
                )
            ].append(observation)
    else:
        supplied_ids: set[str] = set()
        for source_scope_id in session.authorized_source_scope_ids:
            observations = observations_by_source_scope_id.get(source_scope_id)
            if observations is None:
                raise ContractValidationError(
                    "authorized source-backed graph observations are unavailable"
                )
            for observation in observations:
                if not isinstance(observation, Observation):
                    raise ContractValidationError(
                        "source-backed graph requires Observation records"
                    )
                validated = Observation.from_dict(observation.to_dict())
                expected = graph_hash_by_id.get(validated.observation_id)
                if expected is None or expected != sha256_json(validated.to_dict()):
                    raise ContractValidationError(
                        "source-backed graph Observation lineage mismatch"
                    )
                if validated.observation_id in supplied_ids:
                    raise ContractValidationError(
                        "source-backed graph has duplicate Observation ids"
                    )
                supplied_ids.add(validated.observation_id)
                grouped[source_scope_id].append(validated)
        if supplied_ids != set(graph_hash_by_id):
            raise ContractValidationError(
                "source-backed graph retrieval Observation binding mismatch"
            )
    return (
        {
            source_scope_id: tuple(sorted(observations, key=lambda item: item.observation_id))
            for source_scope_id, observations in grouped.items()
        },
        lineage_by_observation_id,
    )


def _source_graph_source_kind_properties(
    session: AuthorizedSemanticObservationSession,
) -> dict[str, str]:
    if _is_mail_compatibility_session(session):
        return {}
    if session.authorized_source is None:
        raise ContractValidationError("source-backed graph source kind binding is unavailable")
    return {"source_kind_hash": sha256_json(session.authorized_source.source_kind)}


def _source_graph_source_type(
    session: AuthorizedSemanticObservationSession,
    *,
    mail_value: str,
    source_neutral_value: str,
) -> str:
    return mail_value if _is_mail_compatibility_session(session) else source_neutral_value


def _source_graph_inventory_kind_for_occurrence(
    session: AuthorizedSemanticObservationSession,
    *,
    occurrence_lineage: SourceOccurrenceLineage | None,
) -> str:
    if _is_mail_compatibility_session(session):
        return "mail_observation"
    if occurrence_lineage is None:
        raise ContractValidationError("source-backed graph occurrence lineage is unavailable")
    return occurrence_lineage.occurrence_kind


def _source_graph_require_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ContractValidationError(f"{field_name} must be a sha256 fingerprint")
    return value


def _source_graph_identity_scope_from_batch(
    batch: SourceBoundIdentifierMentionBatch,
) -> SourceIdentifierIdentityScope:
    """Replay the owner contract instead of trusting batch self-assertions."""

    try:
        identity_scope = SourceIdentifierIdentityScope(
            identity_scope_mode=batch.identity_scope_mode,
            identity_scope_fingerprint=batch.identity_scope_fingerprint,
            workspace_id=batch.workspace_id,
            identity_scope_attestation_fingerprint=(batch.identity_scope_attestation_fingerprint),
            identity_scope_policy_fingerprint=(batch.identity_scope_policy_fingerprint),
            operator_approval_fingerprint=batch.operator_approval_fingerprint,
            tenant_id=batch.tenant_id,
            spec_approval_fingerprint=batch.spec_approval_fingerprint,
        )
    except (AttributeError, TypeError, ContractValidationError) as exc:
        raise ContractValidationError(
            "source-backed identifier identity scope binding is invalid"
        ) from exc
    serialized = identity_scope.to_dict()
    if (
        identity_scope.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
        and "tenant_id" in serialized
    ):
        raise ContractValidationError(
            "workspace_only_v1 source-backed identifier scope fabricates tenant"
        )
    return identity_scope


def _source_graph_identity_scope_graph_binding(
    identity_scope: SourceIdentifierIdentityScope,
) -> dict[str, str]:
    """Return the safe identity binding carried by every v2 graph record."""

    payload = {
        "identity_scope_mode": identity_scope.identity_scope_mode,
        "identity_scope_fingerprint": identity_scope.identity_scope_fingerprint,
        "workspace_scope_fingerprint": sha256_json(identity_scope.workspace_id),
        "identity_scope_attestation_fingerprint": (
            identity_scope.identity_scope_attestation_fingerprint
        ),
        "identity_scope_policy_fingerprint": (identity_scope.identity_scope_policy_fingerprint),
        "operator_approval_fingerprint": (identity_scope.operator_approval_fingerprint),
    }
    if identity_scope.identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE:
        assert identity_scope.spec_approval_fingerprint is not None
        payload["spec_approval_fingerprint"] = identity_scope.spec_approval_fingerprint
    assert_public_payload_safe(
        payload,
        "source_backed_identifier_identity_scope_graph_binding",
    )
    return payload


def _source_graph_selected_observations(
    *,
    session: AuthorizedSemanticMailSession,
    observations_by_bundle_id: Mapping[str, Sequence[Observation]],
) -> dict[str, Observation]:
    selected: dict[str, Observation] = {}
    selected_hashes: dict[str, str] = {}
    for source_scope_id in session.selected_source_scope_ids:
        observations = observations_by_bundle_id.get(source_scope_id)
        if observations is None:
            raise ContractValidationError(
                "selected source-backed graph observations are unavailable"
            )
        for observation in observations:
            if not isinstance(observation, Observation):
                raise ContractValidationError(
                    "source-backed identifier mentions require Observation records"
                )
            validated = Observation.from_dict(observation.to_dict())
            observation_hash = sha256_json(validated.to_dict())
            existing_hash = selected_hashes.get(validated.observation_id)
            if existing_hash is not None and existing_hash != observation_hash:
                raise ContractValidationError(
                    "selected source-backed graph Observation lineage is inconsistent"
                )
            selected[validated.observation_id] = validated
            selected_hashes[validated.observation_id] = observation_hash
    return selected


def _source_graph_observation_provenance_fingerprint(
    observation: Observation,
) -> str:
    return sha256_json(
        {
            "asset_id": observation.asset_id,
            "evidence_snapshot_id": observation.evidence_snapshot_id,
            "extractor_run_id": observation.extractor_run_id,
            "modality": observation.modality,
            "observation_type": observation.observation_type,
        }
    )


def _source_graph_validate_identifier_mention(
    mention: CandidateMention,
    *,
    batch: SourceBoundIdentifierMentionBatch,
    identity_scope: SourceIdentifierIdentityScope,
    observation: Observation,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
) -> tuple[str, int, int, str, str]:
    validated = CandidateMention.from_dict(mention.to_dict())
    if (
        validated.status != "pending_review"
        or validated.requires_review is not True
        or validated.metadata.get("candidate_kind") != "protected_identifier_occurrence"
        or validated.metadata.get("candidate_only") is not True
        or validated.metadata.get("canonical_write_allowed") is not False
    ):
        raise ContractValidationError("source-backed identifier mention must remain candidate-only")
    if len(validated.source_observation_ids) != 1:
        raise ContractValidationError("source-backed identifier mention requires one Observation")
    source_observation_id = validated.source_observation_ids[0]
    if source_observation_id != observation.observation_id:
        raise ContractValidationError(
            "source-backed identifier mention Observation binding mismatch"
        )
    prefix = "protected_identifier:"
    if not validated.mention_type.startswith(prefix):
        raise ContractValidationError("source-backed identifier mention type is unsupported")
    identifier_kind = validated.mention_type.removeprefix(prefix)
    if not identifier_kind:
        raise ContractValidationError("source-backed identifier mention kind is unavailable")

    metadata = validated.metadata
    exact_hash = _source_graph_require_sha256(
        metadata.get("exact_protected_token_hash"),
        "source-backed identifier exact hash",
    )
    if validated.normalized_label != exact_hash or validated.text_hash != exact_hash:
        raise ContractValidationError("source-backed identifier mention exact hash mismatch")
    if (
        metadata.get("tokenizer_id") != batch.tokenizer_id
        or metadata.get("tokenizer_profile_fingerprint") != batch.tokenizer_profile_fingerprint
        or metadata.get("extraction_policy_id") != batch.extraction_policy_id
        or metadata.get("extraction_policy_fingerprint") != batch.extraction_policy_fingerprint
    ):
        raise ContractValidationError("source-backed identifier mention batch binding mismatch")
    if (
        "tenant_workspace_fingerprint" in metadata
        or "tenant_workspace_fingerprint" in validated.location
    ):
        raise ContractValidationError(
            "source-backed identifier legacy raw tenant schema is unsupported"
        )
    expected_identity_scope = identity_scope.to_dict()
    if any(
        metadata.get(field_name) != value for field_name, value in expected_identity_scope.items()
    ):
        raise ContractValidationError("source-backed identifier identity scope binding mismatch")
    if identity_scope.identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE:
        if (
            "tenant_id" not in metadata
            or "spec_approval_fingerprint" in metadata
            or "tenant_id" not in validated.location
            or "spec_approval_fingerprint" in validated.location
        ):
            raise ContractValidationError(
                "source-backed identifier tenant identity scope fields are invalid"
            )
    elif (
        "tenant_id" in metadata
        or "spec_approval_fingerprint" not in metadata
        or "tenant_id" in validated.location
        or "spec_approval_fingerprint" not in validated.location
    ):
        raise ContractValidationError(
            "source-backed identifier workspace-only identity scope fields are invalid"
        )
    if (
        metadata.get("normalization_id") != tokenizer_profile.normalization_id
        or metadata.get("normalization_fingerprint") != tokenizer_profile.normalization_sha256
        or metadata.get("protected_identifier_policy_id")
        != tokenizer_profile.protected_identifier_policy_id
        or metadata.get("protected_identifier_policy_fingerprint")
        != tokenizer_profile.protected_identifier_policy_sha256
        or metadata.get("candidate_admission_policy_id")
        != tokenizer_profile.candidate_admission_policy_id
        or metadata.get("candidate_admission_policy_fingerprint")
        != tokenizer_profile.candidate_admission_policy_sha256
    ):
        raise ContractValidationError("source-backed identifier tokenizer policy binding mismatch")

    permission_scope = dict(observation.permission_scope)
    permission_fingerprint = sha256_json(permission_scope)
    if (
        metadata.get("permission_scope") != permission_scope
        or metadata.get("permission_boundary_fingerprint") != permission_fingerprint
    ):
        raise ContractValidationError("source-backed identifier permission binding mismatch")
    observation_fingerprint = sha256_json(observation.to_dict())
    if metadata.get("source_observation_fingerprint") != observation_fingerprint:
        raise ContractValidationError("source-backed identifier Observation fingerprint mismatch")
    if metadata.get("source_extractor_provenance_fingerprint") != (
        _source_graph_observation_provenance_fingerprint(observation)
    ):
        raise ContractValidationError("source-backed identifier provenance binding mismatch")
    occurrence_id = _observation_message_occurrence_id(observation)
    if occurrence_id is None:
        raise ContractValidationError("source-backed identifier message occurrence is unavailable")
    message_occurrence_fingerprint = sha256_json(occurrence_id)
    source_locator_fingerprint = sha256_json(observation.location)
    if (
        metadata.get("message_occurrence_fingerprint") != message_occurrence_fingerprint
        or metadata.get("source_locator_fingerprint") != source_locator_fingerprint
    ):
        raise ContractValidationError("source-backed identifier source occurrence binding mismatch")

    location = validated.location
    span_start = location.get("span_start")
    span_end = location.get("span_end")
    if (
        not isinstance(span_start, int)
        or isinstance(span_start, bool)
        or not isinstance(span_end, int)
        or isinstance(span_end, bool)
        or span_start < 0
        or span_end <= span_start
    ):
        raise ContractValidationError("source-backed identifier occurrence span is invalid")
    expected_location = {
        "source_observation_id": source_observation_id,
        "message_occurrence_fingerprint": message_occurrence_fingerprint,
        "source_locator_fingerprint": source_locator_fingerprint,
        "permission_boundary_fingerprint": permission_fingerprint,
        "tokenizer_profile_fingerprint": batch.tokenizer_profile_fingerprint,
        "extraction_policy_fingerprint": batch.extraction_policy_fingerprint,
        "identifier_kind": identifier_kind,
        **expected_identity_scope,
    }
    if any(location.get(key) != value for key, value in expected_location.items()):
        raise ContractValidationError("source-backed identifier occurrence location mismatch")
    occurrence_scope_fingerprint = sha256_json(
        {
            "source_observation_fingerprint": observation_fingerprint,
            "message_occurrence_fingerprint": message_occurrence_fingerprint,
            "source_locator_fingerprint": source_locator_fingerprint,
            "span_start": span_start,
            "span_end": span_end,
            "identifier_kind": identifier_kind,
        }
    )
    if (
        location.get("occurrence_scope_fingerprint") != occurrence_scope_fingerprint
        or metadata.get("occurrence_scope_fingerprint") != occurrence_scope_fingerprint
    ):
        raise ContractValidationError("source-backed identifier occurrence fingerprint mismatch")
    if (
        stable_candidate_mention_id(
            source_observation_ids=[source_observation_id],
            mention_type=validated.mention_type,
            normalized_label=validated.normalized_label,
            location=validated.location,
            extractor_run_id=validated.extractor_run_id,
        )
        != validated.candidate_mention_id
    ):
        raise ContractValidationError("source-backed identifier mention identity mismatch")

    text = observation.text
    if not isinstance(text, str):
        raise ContractValidationError("source-backed identifier Observation text is unavailable")
    matching_spans = [
        span
        for span in tokenizer_profile.analyze(text).protected_identifiers
        if span.start == span_start
        and span.end == span_end
        and span.identifier_kind == identifier_kind
        and sha256_json(span.exact_token) == exact_hash
    ]
    if len(matching_spans) != 1:
        raise ContractValidationError("source-backed identifier token occurrence mismatch")
    return (
        source_observation_id,
        span_start,
        span_end,
        identifier_kind,
        exact_hash,
    )


def _source_graph_expected_identifier_occurrences(
    observations: Mapping[str, Observation],
    *,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
) -> set[tuple[str, int, int, str, str]]:
    expected: set[tuple[str, int, int, str, str]] = set()
    for observation_id, observation in sorted(observations.items()):
        text = observation.text
        if not isinstance(text, str) or not text:
            continue
        spans = tokenizer_profile.analyze(text).protected_identifiers
        if spans and _observation_message_occurrence_id(observation) is None:
            raise ContractValidationError(
                "source-backed identifier message occurrence is unavailable"
            )
        expected.update(
            (
                observation_id,
                span.start,
                span.end,
                span.identifier_kind,
                sha256_json(span.exact_token),
            )
            for span in spans
        )
    return expected


def _validate_source_identifier_mention_batch(
    *,
    session: AuthorizedSemanticMailSession,
    observations_by_bundle_id: Mapping[str, Sequence[Observation]],
    source_binding_fingerprint: str,
    batch: SourceBoundIdentifierMentionBatch,
) -> _SourceIdentifierMentionGraphInput:
    if not isinstance(batch, SourceBoundIdentifierMentionBatch):
        raise ContractValidationError(
            "source-backed graph v2 requires SourceBoundIdentifierMentionBatch"
        )
    identity_scope = _source_graph_identity_scope_from_batch(batch)
    graph_identity_binding = _source_graph_identity_scope_graph_binding(identity_scope)
    graph_identity_binding_fingerprint = sha256_json(graph_identity_binding)
    tokenizer_profile = session.index._runtime_components.tokenizer_profile
    if (
        batch.tokenizer_id != session.index.tokenizer_id
        or batch.tokenizer_id != tokenizer_profile.tokenizer_id
        or batch.tokenizer_profile_fingerprint != session.index.profile_fingerprint
        or batch.tokenizer_profile_fingerprint != tokenizer_profile.profile_fingerprint
    ):
        raise ContractValidationError("source-backed identifier tokenizer profile mismatch")
    if (
        batch.extraction_policy_id != SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID
        or batch.extraction_policy_fingerprint
        != SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
        or batch.workspace_id != session.workspace_id
    ):
        raise ContractValidationError("source-backed identifier batch policy or workspace mismatch")
    safe_public_string(batch.workspace_id, "source-backed identifier workspace_id")

    mentions = tuple(
        CandidateMention.from_dict(mention.to_dict()) for mention in batch.candidate_mentions
    )
    mention_ids = tuple(mention.candidate_mention_id for mention in mentions)
    if batch.occurrence_count != len(mentions):
        raise ContractValidationError("source-backed identifier batch occurrence count mismatch")
    if len(set(mention_ids)) != len(mention_ids):
        raise ContractValidationError("source-backed identifier batch mention ids are not unique")
    if mention_ids != tuple(sorted(mention_ids)):
        raise ContractValidationError("source-backed identifier batch order mismatch")
    expected_batch_fingerprint = sha256_json(
        {
            "candidate_mention_ids": list(mention_ids),
            "extraction_policy_fingerprint": (
                SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
            ),
            "identity_scope": identity_scope.to_dict(),
            "tokenizer_profile_fingerprint": tokenizer_profile.profile_fingerprint,
        }
    )
    if batch.batch_fingerprint != expected_batch_fingerprint:
        raise ContractValidationError("source-backed identifier batch seal mismatch")

    selected_observations = _source_graph_selected_observations(
        session=session,
        observations_by_bundle_id=observations_by_bundle_id,
    )
    actual_occurrences: set[tuple[str, int, int, str, str]] = set()
    for mention in mentions:
        if len(mention.source_observation_ids) != 1:
            raise ContractValidationError(
                "source-backed identifier mention requires one Observation"
            )
        observation = selected_observations.get(mention.source_observation_ids[0])
        if observation is None:
            raise ContractValidationError(
                "source-backed identifier mention is outside selected source scope"
            )
        occurrence = _source_graph_validate_identifier_mention(
            mention,
            batch=batch,
            identity_scope=identity_scope,
            observation=observation,
            tokenizer_profile=tokenizer_profile,
        )
        if occurrence in actual_occurrences:
            raise ContractValidationError("source-backed identifier occurrence is duplicated")
        actual_occurrences.add(occurrence)
    expected_occurrences = _source_graph_expected_identifier_occurrences(
        selected_observations,
        tokenizer_profile=tokenizer_profile,
    )
    if actual_occurrences != expected_occurrences:
        raise ContractValidationError("source-backed identifier occurrence coverage mismatch")

    complete_mention_fingerprint = sha256_json(
        {
            "batch_fingerprint": batch.batch_fingerprint,
            "identity_scope_binding": identity_scope.to_dict(),
            "mention_hashes": [sha256_json(mention.to_dict()) for mention in mentions],
            "selected_source_scope_ids": list(session.selected_source_scope_ids),
        }
    )
    authorized_hash_by_id = dict(session.authorized_observation_hashes)
    authorized_mentions = tuple(
        mention
        for mention in mentions
        if mention.source_observation_ids[0] in authorized_hash_by_id
    )
    authorized_mention_fingerprint = sha256_json(
        {
            "authorized_mention_hashes": [
                sha256_json(mention.to_dict()) for mention in authorized_mentions
            ],
            "identity_scope_binding": identity_scope.to_dict(),
            "authorized_observation_hashes": sorted(authorized_hash_by_id.values()),
            "authorized_source_scope_ids": list(session.authorized_source_scope_ids),
        }
    )
    exact_resolution = resolve_exact_protected_identifier_candidates(authorized_mentions)
    exact_candidate_by_mention_id: dict[
        str,
        ExactProtectedIdentifierCandidate,
    ] = {}
    for candidate in exact_resolution.candidates:
        for occurrence in candidate.occurrence_scopes:
            if occurrence.candidate_mention_id in exact_candidate_by_mention_id:
                raise ContractValidationError(
                    "source-backed identifier resolution occurrence is ambiguous"
                )
            exact_candidate_by_mention_id[occurrence.candidate_mention_id] = candidate
    if set(exact_candidate_by_mention_id) != {
        mention.candidate_mention_id for mention in authorized_mentions
    }:
        raise ContractValidationError("source-backed identifier exact resolution is incomplete")
    mentions_by_observation_id: dict[str, list[CandidateMention]] = {}
    for mention in authorized_mentions:
        mentions_by_observation_id.setdefault(
            mention.source_observation_ids[0],
            [],
        ).append(mention)
    governed_scope_fingerprint = sha256_json(
        {
            "policy_id": _SOURCE_GRAPH_POLICY_ID_V2,
            "source_binding_fingerprint": source_binding_fingerprint,
            "requester_user_id": session.requester_user_id,
            "identity_scope_binding": identity_scope.to_dict(),
            "identity_scope_graph_binding_fingerprint": (graph_identity_binding_fingerprint),
            "authorized_source_scope_ids": list(session.authorized_source_scope_ids),
            "authorized_observation_hashes": sorted(authorized_hash_by_id.values()),
        }
    )
    return _SourceIdentifierMentionGraphInput(
        batch=batch,
        authorized_mentions=authorized_mentions,
        exact_resolution=exact_resolution,
        exact_candidate_by_mention_id=MappingProxyType(exact_candidate_by_mention_id),
        mentions_by_observation_id=MappingProxyType(
            {
                observation_id: tuple(sorted(items, key=lambda item: item.candidate_mention_id))
                for observation_id, items in sorted(mentions_by_observation_id.items())
            }
        ),
        identity_scope=identity_scope,
        graph_identity_binding=MappingProxyType(graph_identity_binding),
        graph_identity_binding_fingerprint=(graph_identity_binding_fingerprint),
        governed_scope_fingerprint=governed_scope_fingerprint,
        complete_mention_fingerprint=complete_mention_fingerprint,
        authorized_mention_fingerprint=authorized_mention_fingerprint,
    )


def _source_graph_node_id(kind: str, value: str) -> str:
    digest = sha256_json({"kind": kind, "value": value}).removeprefix("sha256:")
    return f"sg_{kind}_{digest[:32]}"


def _source_backed_graph_artifact_id(graph_policy_id: str) -> str:
    if graph_policy_id == _SOURCE_GRAPH_POLICY_ID_V2:
        return "formowl_issue56_source_backed_graph_build_v2"
    if graph_policy_id == _SOURCE_GRAPH_GITHUB_REFERENCE_POLICY_ID:
        return "formowl_issue56_source_backed_github_reference_graph_build_v1"
    if graph_policy_id == _SOURCE_GRAPH_POLICY_ID:
        return "formowl_issue56_source_backed_graph_build_v1"
    raise ContractValidationError("source-backed graph policy is unsupported")


def _source_graph_relation_type_hashes(
    *,
    graph_policy_id: str,
    identifier_input: _SourceIdentifierMentionGraphInput | None,
) -> tuple[str, ...]:
    relation_types = {_SOURCE_GRAPH_RELATION_TYPE}
    if identifier_input is not None:
        relation_types.add(_SOURCE_GRAPH_IDENTIFIER_MENTION_RELATION_TYPE)
    if graph_policy_id == _SOURCE_GRAPH_GITHUB_REFERENCE_POLICY_ID:
        relation_types.add(_SOURCE_GRAPH_GITHUB_REFERENCE_RELATION_TYPE)
    return tuple(sorted(sha256_json(relation_type) for relation_type in relation_types))


def _source_graph_github_reference_edges(
    *,
    session: AuthorizedSemanticObservationSession,
    authorized_observation_by_id: Mapping[str, Observation],
    occurrence_lineage_by_observation_id: Mapping[str, SourceOccurrenceLineage],
    observation_node_id_by_observation_id: Mapping[str, str],
) -> tuple[GraphProjectionEdge, ...]:
    authorized_source = session.authorized_source
    if (
        _is_mail_compatibility_session(session)
        or authorized_source is None
        or authorized_source.source_kind != GITHUB_PROJECT_OBSERVATION_SOURCE_KIND
    ):
        raise ContractValidationError(
            "GitHub source-reference graph requires the GitHub source kind"
        )
    if set(authorized_observation_by_id) != set(occurrence_lineage_by_observation_id):
        raise ContractValidationError("GitHub source-reference occurrence lineage is incomplete")
    if set(authorized_observation_by_id) != set(observation_node_id_by_observation_id):
        raise ContractValidationError(
            "GitHub source-reference Observation projection is incomplete"
        )

    lineage_by_observation_id: dict[str, GitHubProjectOccurrenceLineage] = {}
    observation_id_by_occurrence_id: dict[str, str] = {}
    project_scope_by_observation_id: dict[str, str] = {}
    reference_numbers_by_observation_id: dict[str, tuple[int, ...]] = {}
    issue_observation_id_by_scope_and_number: dict[tuple[str, int], str] = {}
    issue_scopes_by_number: dict[int, set[str]] = {}

    for observation_id, observation in sorted(authorized_observation_by_id.items()):
        validated = Observation.from_dict(observation.to_dict())
        lineage = occurrence_lineage_by_observation_id.get(observation_id)
        if not isinstance(lineage, GitHubProjectOccurrenceLineage):
            raise ContractValidationError("GitHub source-reference occurrence lineage is invalid")
        expected_lineage = source_occurrence_lineage_from_observation(
            validated,
            authorized_source=authorized_source,
        )
        if lineage != expected_lineage:
            raise ContractValidationError("GitHub source-reference occurrence lineage mismatch")
        if lineage.source_local_key in observation_id_by_occurrence_id:
            raise ContractValidationError(
                "GitHub source-reference occurrence identity is duplicated"
            )
        observation_id_by_occurrence_id[lineage.source_local_key] = observation_id
        lineage_by_observation_id[observation_id] = lineage

        project_scope_id = _source_graph_github_project_scope_id(
            validated,
            authorized_source=authorized_source,
        )
        project_scope_by_observation_id[observation_id] = project_scope_id
        issue_number, reference_numbers = _source_graph_github_reference_fields(validated)
        reference_numbers_by_observation_id[observation_id] = reference_numbers
        if lineage.record_kind != "issue_record":
            continue
        issue_key = (project_scope_id, issue_number)
        if issue_key in issue_observation_id_by_scope_and_number:
            raise ContractValidationError("GitHub source-reference issue identity is duplicated")
        issue_observation_id_by_scope_and_number[issue_key] = observation_id
        issue_scopes_by_number.setdefault(issue_number, set()).add(project_scope_id)

    edges: list[GraphProjectionEdge] = []
    for source_observation_id, source_observation in sorted(authorized_observation_by_id.items()):
        source_lineage = lineage_by_observation_id[source_observation_id]
        source_scope_id = project_scope_by_observation_id[source_observation_id]
        if source_lineage.record_kind == "top_level_issue_comment":
            parent_occurrence_id = source_lineage.parent_source_local_key
            if parent_occurrence_id is None:
                raise ContractValidationError(
                    "GitHub source-reference comment parent is unavailable"
                )
            parent_observation_id = observation_id_by_occurrence_id.get(parent_occurrence_id)
            if parent_observation_id is None:
                raise ContractValidationError("GitHub source-reference target is unavailable")
            parent_lineage = lineage_by_observation_id[parent_observation_id]
            if parent_lineage.record_kind != "issue_record":
                raise ContractValidationError("GitHub source-reference comment parent is malformed")
            edges.append(
                _source_graph_github_reference_edge(
                    source_observation=source_observation,
                    source_lineage=source_lineage,
                    target_observation=authorized_observation_by_id[parent_observation_id],
                    target_lineage=parent_lineage,
                    source_node_id=observation_node_id_by_observation_id[source_observation_id],
                    target_node_id=observation_node_id_by_observation_id[parent_observation_id],
                    source_scope_id=source_scope_id,
                    target_scope_id=project_scope_by_observation_id[parent_observation_id],
                    assertion_kind="comment_parent",
                )
            )

        for referenced_issue_number in reference_numbers_by_observation_id[source_observation_id]:
            target_observation_id = issue_observation_id_by_scope_and_number.get(
                (source_scope_id, referenced_issue_number)
            )
            if target_observation_id is None:
                if issue_scopes_by_number.get(referenced_issue_number):
                    raise ContractValidationError(
                        "GitHub source-reference target crosses project scope"
                    )
                raise ContractValidationError("GitHub source-reference target is unavailable")
            if target_observation_id == source_observation_id:
                raise ContractValidationError("GitHub source-reference self target is unsupported")
            edges.append(
                _source_graph_github_reference_edge(
                    source_observation=source_observation,
                    source_lineage=source_lineage,
                    target_observation=authorized_observation_by_id[target_observation_id],
                    target_lineage=lineage_by_observation_id[target_observation_id],
                    source_node_id=observation_node_id_by_observation_id[source_observation_id],
                    target_node_id=observation_node_id_by_observation_id[target_observation_id],
                    source_scope_id=source_scope_id,
                    target_scope_id=project_scope_by_observation_id[target_observation_id],
                    assertion_kind="explicit_issue_reference",
                )
            )
    return tuple(sorted(edges, key=lambda edge: edge.edge_id))


def _source_graph_github_project_scope_id(
    observation: Observation,
    *,
    authorized_source: AuthorizedSemanticSource,
) -> str:
    permission_scope = to_plain(observation.permission_scope)
    if (
        not isinstance(permission_scope, dict)
        or permission_scope.get("scope_type") != "project"
        or not isinstance(permission_scope.get("scope_id"), str)
        or permission_scope["scope_id"] not in authorized_source.source_scope_ids
    ):
        raise ContractValidationError("GitHub source-reference permission scope mismatch")
    return str(permission_scope["scope_id"])


def _source_graph_github_reference_fields(
    observation: Observation,
) -> tuple[int, tuple[int, ...]]:
    payload = observation.payload
    if not isinstance(payload, dict):
        raise ContractValidationError("GitHub source-reference fields are unavailable")
    issue_number = payload.get("issue_number")
    raw_references = payload.get("source_native_issue_references")
    if (
        not isinstance(issue_number, int)
        or isinstance(issue_number, bool)
        or issue_number <= 0
        or not isinstance(raw_references, list)
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in raw_references
        )
    ):
        raise ContractValidationError("GitHub source-reference fields are malformed")
    references = tuple(raw_references)
    if references != tuple(sorted(set(references))):
        raise ContractValidationError("GitHub source-reference fields are malformed")
    return issue_number, references


def _source_graph_github_reference_edge(
    *,
    source_observation: Observation,
    source_lineage: GitHubProjectOccurrenceLineage,
    target_observation: Observation,
    target_lineage: GitHubProjectOccurrenceLineage,
    source_node_id: str,
    target_node_id: str,
    source_scope_id: str,
    target_scope_id: str,
    assertion_kind: str,
) -> GraphProjectionEdge:
    if source_scope_id != target_scope_id:
        raise ContractValidationError("GitHub source-reference target crosses project scope")
    source_permission_scope = to_plain(source_observation.permission_scope)
    target_permission_scope = to_plain(target_observation.permission_scope)
    if (
        not isinstance(source_permission_scope, dict)
        or not isinstance(target_permission_scope, dict)
        or source_permission_scope != target_permission_scope
    ):
        raise ContractValidationError("GitHub source-reference permission binding mismatch")
    assertion_fingerprint = sha256_json(
        {
            "policy_id": _SOURCE_GRAPH_GITHUB_REFERENCE_POLICY_ID,
            "relation_type": _SOURCE_GRAPH_GITHUB_REFERENCE_RELATION_TYPE,
            "assertion_kind": assertion_kind,
            "source_observation_hash": sha256_json(source_observation.to_dict()),
            "source_occurrence_lineage_fingerprint": (source_lineage.lineage_fingerprint),
            "target_occurrence_lineage_fingerprint": (target_lineage.lineage_fingerprint),
            "source_scope_hash": sha256_json(source_scope_id),
            "permission_fingerprint": sha256_json(source_permission_scope),
        }
    )
    edge_id = _source_graph_github_reference_edge_id(
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        assertion_fingerprint=assertion_fingerprint,
    )
    return GraphProjectionEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        relation_type=_SOURCE_GRAPH_GITHUB_REFERENCE_RELATION_TYPE,
        properties={
            "source_observation_ids": [source_observation.observation_id],
            "review_state": "source_record_candidate",
            "candidate_graph_only": True,
            "source_kind_hash": sha256_json(GITHUB_PROJECT_OBSERVATION_SOURCE_KIND),
            "source_scope_hash": sha256_json(source_scope_id),
            "permission_binding_hash": sha256_json(source_permission_scope),
            "source_occurrence_lineage_hash": sha256_json(source_lineage.lineage_fingerprint),
            "target_occurrence_lineage_hash": sha256_json(target_lineage.lineage_fingerprint),
            "source_record_binding_hash": sha256_json(source_lineage.source_record_fingerprint),
            "reference_assertion_hash": assertion_fingerprint,
            "reference_assertion_kind_hash": sha256_json(assertion_kind),
        },
        permission_scope=source_permission_scope,
    )


def _source_graph_github_reference_edge_id(
    *,
    source_node_id: str,
    target_node_id: str,
    assertion_fingerprint: str,
) -> str:
    digest = sha256_json(
        {
            "policy_id": _SOURCE_GRAPH_GITHUB_REFERENCE_POLICY_ID,
            "relation_type": _SOURCE_GRAPH_GITHUB_REFERENCE_RELATION_TYPE,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "assertion_fingerprint": assertion_fingerprint,
        }
    ).removeprefix("sha256:")
    return f"sg_edge_{digest[:32]}"


def _source_graph_observation_node_id(
    *,
    observation_id: str,
    identity_scope_binding_fingerprint: str | None,
    permission_boundary_fingerprint: str,
) -> str:
    if identity_scope_binding_fingerprint is None:
        return _source_graph_node_id("observation", observation_id)
    return _source_graph_node_id(
        "observation",
        sha256_json(
            {
                "observation_id": observation_id,
                "identity_scope_graph_binding_fingerprint": (identity_scope_binding_fingerprint),
                "permission_boundary_fingerprint": permission_boundary_fingerprint,
            }
        ),
    )


def _observation_message_occurrence_id(observation: Observation) -> str | None:
    for source in (observation.location, observation.payload or {}):
        value = source.get("message_occurrence_id")
        if isinstance(value, str) and value:
            return value
    return None


def _source_graph_edge_id(
    *,
    observation_id: str,
    left_identifier: str,
    right_identifier: str,
) -> str:
    digest = sha256_json(
        {
            "policy_id": _SOURCE_GRAPH_POLICY_ID,
            "observation_id": observation_id,
            "left_identifier": left_identifier,
            "right_identifier": right_identifier,
        }
    ).removeprefix("sha256:")
    return f"sg_edge_{digest[:32]}"


def _source_graph_observation_term_edge_id(
    *,
    observation_id: str,
    term_key: str,
) -> str:
    digest = sha256_json(
        {
            "policy_id": _SOURCE_GRAPH_POLICY_ID,
            "observation_id": observation_id,
            "term_key": term_key,
        }
    ).removeprefix("sha256:")
    return f"sg_edge_{digest[:32]}"


def _source_graph_occurrence_lineage_edge_id(
    *,
    source_kind: str,
    parent_observation_id: str,
    child_observation_id: str,
) -> str:
    digest = sha256_json(
        {
            "policy_id": _SOURCE_GRAPH_POLICY_ID,
            "relation_type": _SOURCE_GRAPH_RELATION_TYPE,
            "source_kind": source_kind,
            "parent_observation_id": parent_observation_id,
            "child_observation_id": child_observation_id,
        }
    ).removeprefix("sha256:")
    return f"sg_edge_{digest[:32]}"


def _source_graph_identifier_node_id(
    *,
    candidate: ExactProtectedIdentifierCandidate,
    governed_scope_fingerprint: str,
    graph_identity_binding: Mapping[str, str],
) -> str:
    scoped_identity = sha256_json(
        {
            "policy_id": _SOURCE_GRAPH_POLICY_ID_V2,
            "exact_identifier_hash": candidate.exact_protected_token_hash,
            "identity_scope_graph_binding": dict(graph_identity_binding),
            "permission_boundary_fingerprint": (candidate.permission_boundary_fingerprint),
            "governed_scope_fingerprint": governed_scope_fingerprint,
            "tokenizer_profile_fingerprint": (candidate.tokenizer_profile_fingerprint),
            "extraction_policy_fingerprint": (candidate.extraction_policy_fingerprint),
        }
    )
    return _source_graph_node_id("identifier", scoped_identity)


def _source_graph_identifier_mention_edge_id(
    *,
    mention: CandidateMention,
    source_node_id: str,
    target_node_id: str,
    graph_identity_binding_fingerprint: str,
) -> str:
    digest = sha256_json(
        {
            "policy_id": _SOURCE_GRAPH_POLICY_ID_V2,
            "relation_type": _SOURCE_GRAPH_IDENTIFIER_MENTION_RELATION_TYPE,
            "candidate_mention_id": mention.candidate_mention_id,
            "occurrence_scope_fingerprint": mention.metadata["occurrence_scope_fingerprint"],
            "identity_scope_graph_binding_fingerprint": (graph_identity_binding_fingerprint),
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
        }
    ).removeprefix("sha256:")
    return f"sg_edge_{digest[:32]}"


def _source_graph_identifier_cooccurrence_edge_id(
    *,
    observation_id: str,
    source_node_id: str,
    target_node_id: str,
    graph_identity_binding_fingerprint: str,
) -> str:
    digest = sha256_json(
        {
            "policy_id": _SOURCE_GRAPH_POLICY_ID_V2,
            "relation_type": _SOURCE_GRAPH_RELATION_TYPE,
            "observation_id": observation_id,
            "identity_scope_graph_binding_fingerprint": (graph_identity_binding_fingerprint),
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
        }
    ).removeprefix("sha256:")
    return f"sg_edge_{digest[:32]}"


def _source_graph_identifier_projection(
    *,
    identifier_input: _SourceIdentifierMentionGraphInput,
    authorized_observation_by_id: Mapping[str, Observation],
    source_terms_by_observation_id: Mapping[str, tuple[str, ...]],
    observation_node_id_by_observation_id: Mapping[str, str],
) -> tuple[list[GraphProjectionNode], list[GraphProjectionEdge]]:
    mention_by_id = {
        mention.candidate_mention_id: mention for mention in identifier_input.authorized_mentions
    }
    nodes: list[GraphProjectionNode] = []
    edges: list[GraphProjectionEdge] = []
    node_id_by_mention_id: dict[str, str] = {}

    for candidate in identifier_input.exact_resolution.candidates:
        identity_scope = identifier_input.identity_scope
        if (
            candidate.identity_scope_mode != identity_scope.identity_scope_mode
            or candidate.identity_scope_fingerprint != identity_scope.identity_scope_fingerprint
            or candidate.workspace_id != identity_scope.workspace_id
            or candidate.identity_scope_attestation_fingerprint
            != identity_scope.identity_scope_attestation_fingerprint
            or candidate.identity_scope_policy_fingerprint
            != identity_scope.identity_scope_policy_fingerprint
            or candidate.operator_approval_fingerprint
            != identity_scope.operator_approval_fingerprint
            or candidate.tenant_id != identity_scope.tenant_id
            or candidate.spec_approval_fingerprint != identity_scope.spec_approval_fingerprint
        ):
            raise ContractValidationError(
                "source-backed identifier resolution identity scope mismatch"
            )
        occurrence_mentions = [
            mention_by_id[occurrence.candidate_mention_id]
            for occurrence in candidate.occurrence_scopes
        ]
        source_observation_ids = sorted(
            {mention.source_observation_ids[0] for mention in occurrence_mentions}
        )
        if not source_observation_ids:
            raise ContractValidationError(
                "source-backed identifier node requires authorized occurrences"
            )
        observations = [
            authorized_observation_by_id[observation_id]
            for observation_id in source_observation_ids
        ]
        permission_scope = dict(observations[0].permission_scope)
        permission_fingerprint = sha256_json(permission_scope)
        if permission_fingerprint != candidate.permission_boundary_fingerprint or any(
            dict(observation.permission_scope) != permission_scope for observation in observations
        ):
            raise ContractValidationError("source-backed identifier node permission scope mismatch")
        node_id = _source_graph_identifier_node_id(
            candidate=candidate,
            governed_scope_fingerprint=(identifier_input.governed_scope_fingerprint),
            graph_identity_binding=identifier_input.graph_identity_binding,
        )
        for mention in occurrence_mentions:
            node_id_by_mention_id[mention.candidate_mention_id] = node_id
        source_term_hashes = {
            candidate.exact_protected_token_hash,
            *(
                term_hash
                for observation_id in source_observation_ids
                for term_hash in _source_graph_term_hashes(
                    source_terms_by_observation_id.get(observation_id, ())
                )
            ),
        }
        nodes.append(
            GraphProjectionNode(
                node_id=node_id,
                source_type="mail_candidate_identifier",
                source_id=node_id,
                labels=[
                    "candidate_identifier",
                    _source_graph_typed_hash_label(
                        "candidate_identifier",
                        candidate.candidate_identity_fingerprint,
                    ),
                ],
                properties={
                    "source_observation_ids": source_observation_ids,
                    "node_kind": "candidate_identifier",
                    "review_state": "diagnostic_policy_admitted",
                    "temporal_state": "current",
                    "core_supertype_id": "Artifact",
                    "type_confidence": 1.0,
                    "inventory_kind": "protected_identifier",
                    "inventory_value": (candidate.candidate_identity_fingerprint),
                    "ontology_subject": True,
                    "source_term_hashes": sorted(source_term_hashes)[
                        :_SOURCE_GRAPH_MAX_TERM_HASHES_PER_ENTITY
                    ],
                    "protected_term_hashes": [candidate.exact_protected_token_hash],
                    "candidate_resolution_fingerprint": (candidate.candidate_fingerprint),
                    "identifier_kind_fingerprint": sha256_json(candidate.identifier_kind),
                    "permission_boundary_fingerprint": (candidate.permission_boundary_fingerprint),
                    "governed_scope_fingerprint": (identifier_input.governed_scope_fingerprint),
                    "source_candidate_mention_hashes": sorted(
                        sha256_json(mention.candidate_mention_id) for mention in occurrence_mentions
                    ),
                    **identifier_input.graph_identity_binding,
                },
                permission_scope=permission_scope,
            )
        )

    if set(node_id_by_mention_id) != set(mention_by_id):
        raise ContractValidationError("source-backed identifier node resolution is incomplete")
    identifier_node_ids_by_observation: dict[str, set[str]] = {}
    for mention in identifier_input.authorized_mentions:
        observation_id = mention.source_observation_ids[0]
        observation = authorized_observation_by_id[observation_id]
        source_node_id = observation_node_id_by_observation_id.get(observation_id)
        if source_node_id is None:
            raise ContractValidationError(
                "source-backed identifier Observation node binding is unavailable"
            )
        target_node_id = node_id_by_mention_id[mention.candidate_mention_id]
        identifier_node_ids_by_observation.setdefault(
            observation_id,
            set(),
        ).add(target_node_id)
        edges.append(
            GraphProjectionEdge(
                edge_id=_source_graph_identifier_mention_edge_id(
                    mention=mention,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    graph_identity_binding_fingerprint=(
                        identifier_input.graph_identity_binding_fingerprint
                    ),
                ),
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                relation_type=(_SOURCE_GRAPH_IDENTIFIER_MENTION_RELATION_TYPE),
                properties={
                    "source_observation_ids": [observation_id],
                    "review_state": "diagnostic_policy_admitted",
                    "candidate_mention_hash": sha256_json(mention.candidate_mention_id),
                    "occurrence_scope_fingerprint": mention.metadata[
                        "occurrence_scope_fingerprint"
                    ],
                    "protected_term_hashes": [mention.text_hash],
                    **identifier_input.graph_identity_binding,
                },
                permission_scope=dict(observation.permission_scope),
            )
        )

    for observation_id, node_ids in sorted(identifier_node_ids_by_observation.items()):
        bounded_node_ids = tuple(sorted(node_ids))[:_SOURCE_GRAPH_MAX_IDENTIFIERS_PER_OBSERVATION]
        if len(bounded_node_ids) < 2:
            continue
        pairs: set[tuple[str, str]] = set()
        anchor = bounded_node_ids[0]
        for node_id in bounded_node_ids[1:]:
            pairs.add(tuple(sorted((anchor, node_id))))
        for left_node_id, right_node_id in zip(
            bounded_node_ids,
            bounded_node_ids[1:],
        ):
            pairs.add(tuple(sorted((left_node_id, right_node_id))))
        observation = authorized_observation_by_id[observation_id]
        for source_node_id, target_node_id in sorted(pairs):
            edges.append(
                GraphProjectionEdge(
                    edge_id=_source_graph_identifier_cooccurrence_edge_id(
                        observation_id=observation_id,
                        source_node_id=source_node_id,
                        target_node_id=target_node_id,
                        graph_identity_binding_fingerprint=(
                            identifier_input.graph_identity_binding_fingerprint
                        ),
                    ),
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    relation_type=_SOURCE_GRAPH_RELATION_TYPE,
                    properties={
                        "source_observation_ids": [observation_id],
                        "review_state": "diagnostic_policy_admitted",
                        **identifier_input.graph_identity_binding,
                    },
                    permission_scope=dict(observation.permission_scope),
                )
            )
    if len({node.node_id for node in nodes}) != len(nodes):
        raise ContractValidationError("source-backed identifier node identity is not unique")
    if len({edge.edge_id for edge in edges}) != len(edges):
        raise ContractValidationError("source-backed identifier edge identity is not unique")
    return (
        sorted(nodes, key=lambda item: item.node_id),
        sorted(edges, key=lambda item: item.edge_id),
    )


def _source_graph_source_terms(
    tokens: Sequence[str],
    *,
    document_frequency: Mapping[str, int],
) -> tuple[str, ...]:
    admitted = {
        token.strip()
        for token in tokens
        if (isinstance(token, str) and token.strip() and 2 <= len(token.strip()) <= 256)
    }
    return tuple(
        sorted(
            admitted,
            key=lambda token: (
                document_frequency.get(token, 0),
                sha256_json(token),
            ),
        )[:_SOURCE_GRAPH_MAX_TERMS_PER_OBSERVATION]
    )


def _source_graph_observation_labels(tokens: Sequence[str]) -> tuple[str, ...]:
    labels: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        normalized = token.strip()
        if not normalized or normalized in seen or len(normalized) < 2 or len(normalized) > 80:
            continue
        seen.add(normalized)
        labels.append(_source_graph_typed_hash_label("source_term", normalized))
        if len(labels) >= 16:
            break
    return tuple(labels or ("mail_observation",))


def _source_graph_typed_hash_label(kind: str, value: str) -> str:
    digest = sha256_json({"kind": kind, "value": value}).removeprefix("sha256:")
    return f"{kind}_{digest[:32]}"


def _source_graph_term_hashes(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                sha256_json(value.strip())
                for value in values
                if isinstance(value, str) and value.strip()
            }
        )
    )


def _source_graph_identifiers(
    protected_identifiers: Sequence[Any],
) -> tuple[str, ...]:
    identifiers: list[str] = []
    seen: set[str] = set()
    for span in protected_identifiers:
        value = getattr(span, "exact_token", None)
        if not isinstance(value, str) or not value or value in seen or len(value) > 256:
            continue
        seen.add(value)
        identifiers.append(value)
        if len(identifiers) >= _SOURCE_GRAPH_MAX_IDENTIFIERS_PER_OBSERVATION:
            break
    return tuple(identifiers)


def _source_graph_entity_pairs(
    identifiers: Sequence[str],
) -> tuple[tuple[str, str], ...]:
    entity_keys = tuple(sha256_json(identifier) for identifier in identifiers)
    if len(entity_keys) < 2:
        return ()
    pairs: set[tuple[str, str]] = set()
    anchor = entity_keys[0]
    for entity_key in entity_keys[1:]:
        pairs.add(tuple(sorted((anchor, entity_key))))
    for left, right in zip(entity_keys, entity_keys[1:]):
        pairs.add(tuple(sorted((left, right))))
    return tuple(sorted(pairs))


def _source_graph_core_supertype(identifier: str) -> str:
    normalized = identifier.casefold()
    if "@" in normalized:
        return "Person"
    if normalized.startswith(("http://", "https://")):
        return "Artifact"
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", normalized):
        return "Event"
    if re.fullmatch(r"po[-_]?\d{4,}", normalized):
        return "Artifact"
    return "Concept"


def _source_graph_inventory_kind(identifier: str) -> str:
    if re.fullmatch(r"(?i)po[-_]?\d{4,}", identifier):
        return "purchase_order"
    return "generic_identifier"


def _relation_projection_policy_fingerprint(plan: SemanticQueryPlan) -> str:
    return sha256_json(
        {
            "source_kind": plan.source_kind,
            "required_permissions": list(plan.required_permissions),
            "allowed_paths": [list(path) for path in plan.allowed_paths],
            "max_hops": plan.max_hops,
            "max_fanout": plan.max_fanout,
            "candidate_limit": plan.candidate_limit,
            "result_limit": plan.result_limit,
            "evidence_budget": plan.evidence_budget,
            "time_budget_ms": plan.time_budget_ms,
            "repair_budget": plan.repair_budget,
            "claim_strength": plan.claim_strength,
        }
    )


def _rank_relation_projection_query_anchors(
    projected_nodes: Sequence[_RelationProjectionNode],
    *,
    query_tokens: frozenset[str],
    protected_query_tokens: frozenset[str],
    query_term_hashes: frozenset[str],
    query_concept_term_hashes: frozenset[str],
    protected_query_hashes: frozenset[str],
    include_bound_candidate_terms: bool,
    allow_bound_concept_anchor_with_protected_query: bool,
    limit: int,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[str, ...]:
    matches: list[tuple[float, str]] = []
    seedable_node_kinds = {
        "candidate_entity",
        "candidate_source_term",
        "source_observation",
    }
    for projected_node in projected_nodes:
        _query_deadline_checkpoint(execution_deadline)
        if (
            projected_node.node_kind is not None
            and projected_node.node_kind not in seedable_node_kinds
        ):
            continue
        if projected_node.authorized_evidence_hashes is None:
            continue
        node_term_hashes = set(projected_node.source_term_hashes)
        node_protected_hashes = set(projected_node.protected_term_hashes)
        if include_bound_candidate_terms:
            node_term_hashes.update(projected_node.bound_candidate_concept_term_hashes)
            node_protected_hashes.update(projected_node.bound_candidate_identifier_term_hashes)
        bound_concept_overlap = len(
            query_concept_term_hashes & projected_node.bound_candidate_concept_term_hashes
        )
        lexical_overlap = max(
            len(query_tokens & projected_node.searchable_tokens),
            len(query_term_hashes & node_term_hashes),
        )
        protected_overlap = max(
            len(protected_query_tokens & projected_node.searchable_protected_tokens),
            len(protected_query_hashes & (node_protected_hashes | node_term_hashes)),
        )
        score = float(lexical_overlap + (2 * protected_overlap))
        if protected_query_tokens and protected_overlap:
            matches.append((score, projected_node.node_id))
        elif (
            protected_query_tokens
            and allow_bound_concept_anchor_with_protected_query
            and bound_concept_overlap
        ):
            matches.append((score + float(bound_concept_overlap), projected_node.node_id))
        elif not protected_query_tokens and (
            lexical_overlap >= 2
            or (
                projected_node.node_kind in {"candidate_source_term", "source_observation"}
                and bool(query_term_hashes & node_term_hashes)
            )
        ):
            matches.append((score, projected_node.node_id))
    _query_deadline_checkpoint(execution_deadline)
    return tuple(
        node_id
        for _, node_id in sorted(
            matches,
            key=lambda item: (-item[0], item[1]),
        )[:limit]
    )


def _relation_projection_base_cache_binding(
    *,
    graph_revision_fingerprint: str,
    index_fingerprint: str,
    tokenizer_profile_fingerprint: str,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, _HybridCandidate],
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> str:
    candidate_projection_inputs, _candidate_set_fingerprint = (
        _relation_projection_candidate_binding_inputs(
            candidates_by_hash=candidates_by_hash,
            execution_deadline=execution_deadline,
        )
    )
    return _relation_projection_base_cache_binding_from_inputs(
        graph_revision_fingerprint=graph_revision_fingerprint,
        index_fingerprint=index_fingerprint,
        tokenizer_profile_fingerprint=tokenizer_profile_fingerprint,
        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        candidate_projection_inputs=candidate_projection_inputs,
    )


def _relation_projection_helper_object_ids() -> tuple[int, ...]:
    return (
        id(_authorized_property_evidence_hashes),
        id(_node_searchable_values),
        id(_node_source_term_hashes),
        id(_node_protected_term_hashes),
        id(_source_graph_term_hashes),
    )


def _relation_projection_candidate_binding_inputs(
    *,
    candidates_by_hash: Mapping[str, _HybridCandidate],
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[list[list[Any]], str]:
    candidate_projection_inputs: list[list[Any]] = []
    candidate_set_inputs: list[list[str]] = []
    for observation_hash, candidate in sorted(candidates_by_hash.items()):
        _query_deadline_checkpoint(execution_deadline)
        candidate_projection_inputs.append(
            [
                observation_hash,
                candidate.index_binding_hash,
                candidate.message_occurrence_hash,
                sorted(sha256_json(token) for token in candidate.observation_tokens),
                sorted(
                    sha256_json(token)
                    for token in candidate.observation_protected_identifier_tokens
                ),
            ]
        )
        candidate_set_inputs.append(
            [
                observation_hash,
                candidate.index_binding_hash,
                candidate.message_occurrence_hash,
            ]
        )
    _query_deadline_checkpoint(execution_deadline)
    return candidate_projection_inputs, sha256_json(candidate_set_inputs)


def _relation_projection_base_cache_binding_from_inputs(
    *,
    graph_revision_fingerprint: str,
    index_fingerprint: str,
    tokenizer_profile_fingerprint: str,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidate_projection_inputs: Sequence[Sequence[Any]],
) -> str:
    return sha256_json(
        {
            "graph_revision_fingerprint": graph_revision_fingerprint,
            "index_fingerprint": index_fingerprint,
            "tokenizer_profile_fingerprint": tokenizer_profile_fingerprint,
            "projection_helper_object_ids": list(_relation_projection_helper_object_ids()),
            "authorized_observations": sorted(authorized_observation_hash_by_id.items()),
            "candidate_projection_inputs": candidate_projection_inputs,
        }
    )


def _require_relation_projection_cache_binding_snapshot(
    snapshot: _RelationProjectionCacheBindingSnapshot,
    *,
    index: AuthorizedHybridMailIndex,
    graph_revision_fingerprint: str,
    tokenizer_profile_fingerprint: str,
    authorized_observation_set_fingerprint: str,
) -> None:
    if (
        snapshot.graph_revision_fingerprint != graph_revision_fingerprint
        or snapshot.index_fingerprint != index.index_fingerprint
        or snapshot.tokenizer_profile_fingerprint != tokenizer_profile_fingerprint
        or snapshot.authorized_observation_set_fingerprint != authorized_observation_set_fingerprint
        or snapshot.projection_helper_object_ids != _relation_projection_helper_object_ids()
        or snapshot.index_candidates is not index.candidates
        or index.candidates is not index._relation_projection_candidates_snapshot
    ):
        raise ContractValidationError("relation projection cache binding snapshot mismatch")


def _relation_projection_base_cache_binding_snapshot(
    *,
    index: AuthorizedHybridMailIndex,
    effective_graph_view: EffectiveGraphView,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, _HybridCandidate],
    graph_snapshot: _QueryGraphSnapshot,
    execution_deadline: _QueryExecutionDeadline | None = None,
    diagnostic_recorder: (_RelationProjectionBaseColdDiagnosticRecorder | None) = None,
) -> _RelationProjectionCacheBindingSnapshot:
    graph_revision_fingerprint = _require_query_graph_snapshot(
        effective_graph_view=effective_graph_view,
        graph_snapshot=graph_snapshot,
    )
    authorized_observation_set_fingerprint = sha256_json(
        sorted(authorized_observation_hash_by_id.items())
    )
    helper_object_ids = _relation_projection_helper_object_ids()
    snapshot_key = (
        graph_revision_fingerprint,
        index.index_fingerprint,
        tokenizer_profile.profile_fingerprint,
        authorized_observation_set_fingerprint,
        helper_object_ids,
        id(index.candidates),
    )
    content_snapshot = graph_snapshot.content_snapshot
    with _acquire_relation_projection_base_lock(
        content_snapshot.relation_projection_base_lock,
        execution_deadline=execution_deadline,
    ):
        cached = content_snapshot.relation_projection_cache_binding_snapshots.get(snapshot_key)
        if cached is not None:
            if diagnostic_recorder is not None:
                raise ContractValidationError(
                    "relation projection cold diagnostic binding cache is not cold"
                )
            if not isinstance(cached, _RelationProjectionCacheBindingSnapshot):
                raise ContractValidationError(
                    "relation projection cache binding snapshot is invalid"
                )
            _require_relation_projection_cache_binding_snapshot(
                cached,
                index=index,
                graph_revision_fingerprint=graph_revision_fingerprint,
                tokenizer_profile_fingerprint=tokenizer_profile.profile_fingerprint,
                authorized_observation_set_fingerprint=(authorized_observation_set_fingerprint),
            )
            _query_deadline_checkpoint(execution_deadline)
            return cached

        if index.candidates is not index._relation_projection_candidates_snapshot:
            raise ContractValidationError("relation projection candidate content snapshot mismatch")
        if diagnostic_recorder is not None:
            diagnostic_recorder.start_binding()
        candidate_projection_inputs, candidate_set_fingerprint = (
            _relation_projection_candidate_binding_inputs(
                candidates_by_hash=candidates_by_hash,
                execution_deadline=execution_deadline,
            )
        )
        cache_binding_fingerprint = _relation_projection_base_cache_binding_from_inputs(
            graph_revision_fingerprint=graph_revision_fingerprint,
            index_fingerprint=index.index_fingerprint,
            tokenizer_profile_fingerprint=tokenizer_profile.profile_fingerprint,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            candidate_projection_inputs=candidate_projection_inputs,
        )
        snapshot = _RelationProjectionCacheBindingSnapshot(
            cache_binding_fingerprint=cache_binding_fingerprint,
            graph_revision_fingerprint=graph_revision_fingerprint,
            index_fingerprint=index.index_fingerprint,
            tokenizer_profile_fingerprint=tokenizer_profile.profile_fingerprint,
            authorized_observation_set_fingerprint=(authorized_observation_set_fingerprint),
            candidate_set_fingerprint=candidate_set_fingerprint,
            projection_helper_object_ids=helper_object_ids,
            index_candidates=index.candidates,
        )
        _require_relation_projection_cache_binding_snapshot(
            snapshot,
            index=index,
            graph_revision_fingerprint=graph_revision_fingerprint,
            tokenizer_profile_fingerprint=tokenizer_profile.profile_fingerprint,
            authorized_observation_set_fingerprint=(authorized_observation_set_fingerprint),
        )
        if diagnostic_recorder is not None:
            diagnostic_recorder.complete_binding()
        if len(content_snapshot.relation_projection_cache_binding_snapshots) >= 8:
            content_snapshot.relation_projection_cache_binding_snapshots.clear()
            content_snapshot.relation_projection_bases.clear()
        content_snapshot.relation_projection_cache_binding_snapshots[snapshot_key] = snapshot
        if diagnostic_recorder is not None:
            diagnostic_recorder.publish_binding()
        _query_deadline_checkpoint(execution_deadline)
        return snapshot


def _require_relation_projection_base_binding(
    base: _RelationProjectionBase,
    *,
    binding_snapshot: _RelationProjectionCacheBindingSnapshot,
) -> None:
    if (
        base.cache_binding_fingerprint != binding_snapshot.cache_binding_fingerprint
        or base.authorized_observation_set_fingerprint
        != binding_snapshot.authorized_observation_set_fingerprint
        or base.candidate_set_fingerprint != binding_snapshot.candidate_set_fingerprint
    ):
        raise ContractValidationError("relation projection base precompute binding mismatch")


def _build_relation_projection_base(
    *,
    index: AuthorizedHybridMailIndex,
    effective_graph_view: EffectiveGraphView,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, _HybridCandidate],
    graph_snapshot: _QueryGraphSnapshot,
    cache_binding_snapshot: _RelationProjectionCacheBindingSnapshot,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> _RelationProjectionBase:
    _query_deadline_checkpoint(execution_deadline)
    graph_revision_fingerprint = _require_query_graph_snapshot(
        effective_graph_view=effective_graph_view,
        graph_snapshot=graph_snapshot,
    )
    _require_relation_projection_cache_binding_snapshot(
        cache_binding_snapshot,
        index=index,
        graph_revision_fingerprint=graph_revision_fingerprint,
        tokenizer_profile_fingerprint=tokenizer_profile.profile_fingerprint,
        authorized_observation_set_fingerprint=sha256_json(
            sorted(authorized_observation_hash_by_id.items())
        ),
    )

    candidate_concept_hashes: dict[str, frozenset[str]] = {}
    candidate_identifier_hashes: dict[str, frozenset[str]] = {}
    for observation_hash, candidate in candidates_by_hash.items():
        _query_deadline_checkpoint(execution_deadline)
        candidate_concept_hashes[observation_hash] = frozenset(
            _source_graph_term_hashes(tuple(candidate.observation_tokens))
        )
        candidate_identifier_hashes[observation_hash] = frozenset(
            _source_graph_term_hashes(tuple(candidate.observation_protected_identifier_tokens))
        )
    projected_nodes_by_id: dict[str, _RelationProjectionNode] = {}
    projected_nodes_by_hash: dict[str, _RelationProjectionNode] = {}
    graph_nodes_by_observation_hash: dict[str, list[GraphProjectionNode]] = {}
    authorized_graph_vocabulary_hashes: set[str] = set()
    for node in effective_graph_view.visible_nodes:
        _query_deadline_checkpoint(execution_deadline)
        if node.node_id in projected_nodes_by_id:
            raise ContractValidationError("relation projection duplicate graph node")
        node_hash = sha256_json(node.node_id)
        if node_hash in projected_nodes_by_hash:
            raise ContractValidationError("relation projection duplicate graph node hash")
        evidence_hashes = _authorized_property_evidence_hashes(
            node.properties,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        )
        searchable_analysis = tokenizer_profile.analyze(" ".join(_node_searchable_values(node)))
        source_term_hashes = frozenset(_node_source_term_hashes(node))
        protected_term_hashes = frozenset(_node_protected_term_hashes(node))
        bound_candidate_concept_hashes: set[str] = set()
        bound_candidate_identifier_hashes: set[str] = set()
        lineage_support: list[tuple[str, frozenset[str], frozenset[str]]] = []
        if evidence_hashes is not None:
            authorized_graph_vocabulary_hashes.update(source_term_hashes)
            authorized_graph_vocabulary_hashes.update(protected_term_hashes)
            for observation_hash in evidence_hashes:
                _query_deadline_checkpoint(execution_deadline)
                graph_nodes_by_observation_hash.setdefault(
                    observation_hash,
                    [],
                ).append(node)
                observation_concept_hashes = candidate_concept_hashes.get(
                    observation_hash,
                    frozenset(),
                )
                observation_identifier_hashes = candidate_identifier_hashes.get(
                    observation_hash,
                    frozenset(),
                )
                supported_identifiers = observation_identifier_hashes & protected_term_hashes
                supported_concepts = observation_concept_hashes & source_term_hashes
                bound_candidate_concept_hashes.update(supported_concepts)
                bound_candidate_identifier_hashes.update(supported_identifiers)
                if supported_identifiers or supported_concepts:
                    lineage_support.append(
                        (
                            observation_hash,
                            frozenset(supported_identifiers),
                            frozenset(supported_concepts),
                        )
                    )
        node_kind_value = node.properties.get("node_kind")
        projected_node = _RelationProjectionNode(
            node=node,
            node_id=node.node_id,
            node_hash=node_hash,
            node_kind=(node_kind_value if isinstance(node_kind_value, str) else None),
            authorized_evidence_hashes=evidence_hashes,
            searchable_tokens=frozenset(searchable_analysis.tokens),
            searchable_protected_tokens=frozenset(
                span.exact_token for span in searchable_analysis.protected_identifiers
            ),
            source_term_hashes=source_term_hashes,
            protected_term_hashes=protected_term_hashes,
            bound_candidate_concept_term_hashes=frozenset(bound_candidate_concept_hashes),
            bound_candidate_identifier_term_hashes=frozenset(bound_candidate_identifier_hashes),
            lineage_support_by_observation_hash=tuple(sorted(lineage_support)),
        )
        projected_nodes_by_id[node.node_id] = projected_node
        projected_nodes_by_hash[node_hash] = projected_node

    transitions: dict[str, list[_RelationProjectionTransition]] = {}
    edge_ids: set[str] = set()
    for edge in effective_graph_view.visible_edges:
        _query_deadline_checkpoint(execution_deadline)
        if edge.edge_id in edge_ids:
            raise ContractValidationError("relation projection duplicate graph edge")
        edge_ids.add(edge.edge_id)
        edge_evidence_hashes = _authorized_property_evidence_hashes(
            edge.properties,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        )
        transitions.setdefault(edge.source_node_id, []).append(
            _RelationProjectionTransition(
                edge=edge,
                direction="out",
                next_node_id=edge.target_node_id,
                authorized_evidence_hashes=edge_evidence_hashes,
            )
        )
        transitions.setdefault(edge.target_node_id, []).append(
            _RelationProjectionTransition(
                edge=edge,
                direction="in",
                next_node_id=edge.source_node_id,
                authorized_evidence_hashes=edge_evidence_hashes,
            )
        )
    adjacency: dict[str, tuple[_RelationProjectionTransition, ...]] = {}
    for node_id, values in transitions.items():
        _query_deadline_checkpoint(execution_deadline)
        adjacency[node_id] = tuple(
            sorted(
                values,
                key=lambda item: (
                    item.edge.edge_id,
                    item.direction,
                    item.next_node_id,
                ),
            )
        )
    frozen_graph_nodes_by_observation_hash: dict[
        str,
        tuple[GraphProjectionNode, ...],
    ] = {}
    for observation_hash, nodes in graph_nodes_by_observation_hash.items():
        _query_deadline_checkpoint(execution_deadline)
        frozen_graph_nodes_by_observation_hash[observation_hash] = tuple(
            sorted(nodes, key=lambda item: item.node_id)
        )
    _query_deadline_checkpoint(execution_deadline)
    return _RelationProjectionBase(
        cache_binding_fingerprint=cache_binding_snapshot.cache_binding_fingerprint,
        authorized_observation_set_fingerprint=(
            cache_binding_snapshot.authorized_observation_set_fingerprint
        ),
        candidate_set_fingerprint=cache_binding_snapshot.candidate_set_fingerprint,
        candidate_concept_term_hashes_by_observation=MappingProxyType(candidate_concept_hashes),
        candidate_identifier_term_hashes_by_observation=MappingProxyType(
            candidate_identifier_hashes
        ),
        node_by_id=MappingProxyType(projected_nodes_by_id),
        node_by_hash=MappingProxyType(projected_nodes_by_hash),
        graph_nodes_by_observation_hash=MappingProxyType(frozen_graph_nodes_by_observation_hash),
        adjacency=MappingProxyType(adjacency),
        authorized_index_vocabulary_hashes=frozenset(
            term_hash for hashes in candidate_concept_hashes.values() for term_hash in hashes
        ),
        authorized_graph_vocabulary_hashes=frozenset(authorized_graph_vocabulary_hashes),
    )


def _relation_projection_base(
    *,
    index: AuthorizedHybridMailIndex,
    effective_graph_view: EffectiveGraphView,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, _HybridCandidate],
    graph_snapshot: _QueryGraphSnapshot,
    execution_deadline: _QueryExecutionDeadline | None = None,
    diagnostic_recorder: (_RelationProjectionBaseColdDiagnosticRecorder | None) = None,
) -> _RelationProjectionBase:
    _query_deadline_checkpoint(execution_deadline)
    cache_binding_snapshot = _relation_projection_base_cache_binding_snapshot(
        index=index,
        effective_graph_view=effective_graph_view,
        tokenizer_profile=tokenizer_profile,
        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        candidates_by_hash=candidates_by_hash,
        graph_snapshot=graph_snapshot,
        execution_deadline=execution_deadline,
        diagnostic_recorder=diagnostic_recorder,
    )
    content_snapshot = graph_snapshot.content_snapshot
    with _acquire_relation_projection_base_lock(
        content_snapshot.relation_projection_base_lock,
        execution_deadline=execution_deadline,
    ):
        cached = content_snapshot.relation_projection_bases.get(
            cache_binding_snapshot.cache_binding_fingerprint
        )
        if cached is not None:
            if diagnostic_recorder is not None:
                raise ContractValidationError(
                    "relation projection cold diagnostic base cache is not cold"
                )
            if not isinstance(cached, _RelationProjectionBase):
                raise ContractValidationError("relation projection base cache is invalid")
            _require_relation_projection_base_binding(
                cached,
                binding_snapshot=cache_binding_snapshot,
            )
            _query_deadline_checkpoint(execution_deadline)
            return cached
        if diagnostic_recorder is not None:
            diagnostic_recorder.start_base_builder()
        base = _build_relation_projection_base(
            index=index,
            effective_graph_view=effective_graph_view,
            tokenizer_profile=tokenizer_profile,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            candidates_by_hash=candidates_by_hash,
            graph_snapshot=graph_snapshot,
            cache_binding_snapshot=cache_binding_snapshot,
            execution_deadline=execution_deadline,
        )
        if diagnostic_recorder is not None:
            diagnostic_recorder.complete_base_builder()
        _require_relation_projection_base_binding(
            base,
            binding_snapshot=cache_binding_snapshot,
        )
        if len(content_snapshot.relation_projection_bases) >= 8:
            content_snapshot.relation_projection_bases.clear()
        content_snapshot.relation_projection_bases[
            cache_binding_snapshot.cache_binding_fingerprint
        ] = base
        if diagnostic_recorder is not None:
            diagnostic_recorder.publish_base()
        _query_deadline_checkpoint(execution_deadline)
        return base


def _validated_relation_projection_candidates(
    *,
    index: AuthorizedHybridMailIndex,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, _HybridCandidate],
    authorized_source: AuthorizedSemanticSource | None = None,
) -> frozenset[str]:
    authorized_observation_hashes = frozenset(authorized_observation_hash_by_id.values())
    indexed_candidate_hashes = tuple(
        candidate.source_observation_hash for candidate in index.candidates
    )
    if (
        len(authorized_observation_hashes) != len(authorized_observation_hash_by_id)
        or len(set(indexed_candidate_hashes)) != len(indexed_candidate_hashes)
        or len(candidates_by_hash) != len(index.candidates)
        or any(
            candidate.source_observation_hash != observation_hash
            or observation_hash not in authorized_observation_hashes
            or candidate.index_binding_hash
            != _relation_candidate_index_binding_hash(
                candidate,
                authorized_source=authorized_source,
            )
            for observation_hash, candidate in candidates_by_hash.items()
        )
        or set(candidates_by_hash) != set(indexed_candidate_hashes)
    ):
        raise ContractValidationError("relation projection authorized candidate mismatch")
    if index.candidates is not index._relation_projection_candidates_snapshot:
        raise ContractValidationError("relation projection candidate content snapshot mismatch")
    return authorized_observation_hashes


def _relation_candidate_index_binding_hash(
    candidate: _HybridCandidate,
    *,
    authorized_source: AuthorizedSemanticSource | None,
) -> str:
    if (
        authorized_source is not None
        and authorized_source.source_kind != AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
    ):
        return sha256_json(
            {
                "source_access_fingerprint": authorized_source.authorization_fingerprint,
                "source_observation_hash": candidate.source_observation_hash,
                "source_occurrence_hash": candidate.message_occurrence_hash,
                "dense_evidence_text_hash": candidate.dense_evidence_text_hash,
            }
        )
    return sha256_json(
        {
            "source_observation_hash": candidate.source_observation_hash,
            "message_hash": candidate.message_hash,
            "message_occurrence_hash": candidate.message_occurrence_hash,
            "dense_evidence_text_hash": candidate.dense_evidence_text_hash,
        }
    )


def _build_relation_query_projection(
    *,
    plan: SemanticQueryPlan,
    query_text: str,
    index: AuthorizedHybridMailIndex,
    effective_graph_view: EffectiveGraphView,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, _HybridCandidate],
    graph_snapshot: _QueryGraphSnapshot,
    authorized_source: AuthorizedSemanticSource | None = None,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> _RelationQueryProjection:
    """Build the authorization-bound relation projection exactly once per query."""

    _query_deadline_checkpoint(execution_deadline)
    if plan.query_class != "relation_reasoning":
        raise ContractValidationError("relation projection requires relation plan")
    if plan.query_hash != sha256_json(query_text):
        raise ContractValidationError("relation projection query mismatch")
    if effective_graph_view.requester_user_id != plan.requester_user_id:
        raise ContractValidationError("relation projection requester mismatch")
    if (
        plan.user_graph_revision_id != effective_graph_view.user_graph_revision_id
        or plan.canonical_graph_revision_id != effective_graph_view.canonical_graph_revision_id
        or plan.ontology_revision_id != effective_graph_view.ontology_revision_id
        or plan.assembly_policy_id != effective_graph_view.assembly_policy_id
    ):
        raise ContractValidationError("relation projection graph revision mismatch")
    if (
        tokenizer_profile.profile_fingerprint != index.profile_fingerprint
        or index.index_fingerprint == ""
    ):
        raise ContractValidationError("relation projection tokenizer/index mismatch")

    _validated_relation_projection_candidates(
        index=index,
        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        candidates_by_hash=candidates_by_hash,
        authorized_source=authorized_source,
    )

    projection_base = _relation_projection_base(
        index=index,
        effective_graph_view=effective_graph_view,
        tokenizer_profile=tokenizer_profile,
        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        candidates_by_hash=candidates_by_hash,
        graph_snapshot=graph_snapshot,
        execution_deadline=execution_deadline,
    )
    candidate_concept_hashes = projection_base.candidate_concept_term_hashes_by_observation
    candidate_identifier_hashes = projection_base.candidate_identifier_term_hashes_by_observation
    query_analysis = tokenizer_profile.analyze(query_text)
    _query_deadline_checkpoint(execution_deadline)
    query_tokens = frozenset(query_analysis.tokens)
    protected_query_tokens = frozenset(
        span.exact_token for span in query_analysis.protected_identifiers
    )
    relation_query_slots = _query_evidence_slots(
        query_text,
        query_class="relation_reasoning",
        tokenizer_profile=tokenizer_profile,
    )
    query_identifier_term_hashes = frozenset(
        _source_graph_term_hashes(tuple(relation_query_slots.identifier_tokens))
    )
    query_concept_term_hashes = frozenset(
        _source_graph_term_hashes(tuple(relation_query_slots.topic_tokens))
    )
    query_term_hashes = frozenset(_source_graph_term_hashes(tuple(query_tokens)))
    protected_query_hashes = frozenset(_source_graph_term_hashes(tuple(protected_query_tokens)))
    candidate_query_slot_coverage = {
        observation_hash: frozenset(
            ("identifier", term_hash)
            for term_hash in (
                query_identifier_term_hashes & candidate_identifier_hashes[observation_hash]
            )
        )
        | frozenset(
            ("concept", term_hash)
            for term_hash in (
                query_concept_term_hashes & candidate_concept_hashes[observation_hash]
            )
        )
        for observation_hash in candidates_by_hash
    }
    projected_nodes = tuple(projection_base.node_by_id.values())
    initial_query_anchor_node_ids = _rank_relation_projection_query_anchors(
        projected_nodes,
        query_tokens=query_tokens,
        protected_query_tokens=protected_query_tokens,
        query_term_hashes=query_term_hashes,
        query_concept_term_hashes=query_concept_term_hashes,
        protected_query_hashes=protected_query_hashes,
        include_bound_candidate_terms=False,
        allow_bound_concept_anchor_with_protected_query=False,
        limit=plan.candidate_limit,
        execution_deadline=execution_deadline,
    )
    completion_query_anchor_node_ids = _rank_relation_projection_query_anchors(
        projected_nodes,
        query_tokens=query_tokens,
        protected_query_tokens=protected_query_tokens,
        query_term_hashes=query_term_hashes,
        query_concept_term_hashes=query_concept_term_hashes,
        protected_query_hashes=protected_query_hashes,
        include_bound_candidate_terms=True,
        allow_bound_concept_anchor_with_protected_query=True,
        limit=plan.candidate_limit,
        execution_deadline=execution_deadline,
    )
    graph_revision_fingerprint = _require_query_graph_snapshot(
        effective_graph_view=effective_graph_view,
        graph_snapshot=graph_snapshot,
    )
    authorized_observation_set_fingerprint = projection_base.authorized_observation_set_fingerprint
    candidate_set_fingerprint = projection_base.candidate_set_fingerprint
    relation_policy_fingerprint = _relation_projection_policy_fingerprint(plan)
    candidate_query_slot_coverage_fingerprint = sha256_json(
        [
            [
                observation_hash,
                [list(slot) for slot in sorted(coverage)],
            ]
            for observation_hash, coverage in sorted(candidate_query_slot_coverage.items())
        ]
    )
    binding_payload = {
        "query_hash": plan.query_hash,
        "requester_user_id": plan.requester_user_id,
        "workspace_id": plan.workspace_id,
        "source_scope_ids": list(plan.source_scope_ids),
        "graph_revision_fingerprint": graph_revision_fingerprint,
        "index_fingerprint": index.index_fingerprint,
        "tokenizer_profile_fingerprint": tokenizer_profile.profile_fingerprint,
        "authorized_observation_set_fingerprint": (authorized_observation_set_fingerprint),
        "candidate_set_fingerprint": candidate_set_fingerprint,
        "relation_policy_fingerprint": relation_policy_fingerprint,
        "candidate_query_slot_coverage_fingerprint": (candidate_query_slot_coverage_fingerprint),
        "initial_query_anchor_node_hashes": [
            sha256_json(node_id) for node_id in initial_query_anchor_node_ids
        ],
        "completion_query_anchor_node_hashes": [
            sha256_json(node_id) for node_id in completion_query_anchor_node_ids
        ],
    }
    _query_deadline_checkpoint(execution_deadline)
    return _RelationQueryProjection(
        binding_fingerprint=sha256_json(binding_payload),
        query_hash=plan.query_hash,
        requester_user_id=plan.requester_user_id,
        workspace_id=plan.workspace_id,
        source_scope_ids=plan.source_scope_ids,
        graph_revision_fingerprint=graph_revision_fingerprint,
        index_fingerprint=index.index_fingerprint,
        tokenizer_profile_fingerprint=tokenizer_profile.profile_fingerprint,
        authorized_observation_set_fingerprint=authorized_observation_set_fingerprint,
        candidate_set_fingerprint=candidate_set_fingerprint,
        relation_policy_fingerprint=relation_policy_fingerprint,
        candidates_by_hash=MappingProxyType(dict(candidates_by_hash)),
        candidate_concept_term_hashes_by_observation=MappingProxyType(
            dict(candidate_concept_hashes)
        ),
        candidate_identifier_term_hashes_by_observation=MappingProxyType(
            dict(candidate_identifier_hashes)
        ),
        candidate_query_slot_coverage_by_observation=MappingProxyType(
            candidate_query_slot_coverage
        ),
        node_by_id=MappingProxyType(dict(projection_base.node_by_id)),
        node_by_hash=MappingProxyType(dict(projection_base.node_by_hash)),
        graph_nodes_by_observation_hash=MappingProxyType(
            dict(projection_base.graph_nodes_by_observation_hash)
        ),
        adjacency=MappingProxyType(dict(projection_base.adjacency)),
        authorized_index_vocabulary_hashes=(projection_base.authorized_index_vocabulary_hashes),
        authorized_graph_vocabulary_hashes=(projection_base.authorized_graph_vocabulary_hashes),
        initial_query_anchor_node_ids=initial_query_anchor_node_ids,
        completion_query_anchor_node_ids=completion_query_anchor_node_ids,
    )


def _require_relation_projection_compatible(
    projection: _RelationQueryProjection,
    *,
    plan: SemanticQueryPlan,
    query_text: str,
    effective_graph_view: EffectiveGraphView,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    graph_snapshot: _QueryGraphSnapshot,
) -> None:
    graph_revision_fingerprint = _require_query_graph_snapshot(
        effective_graph_view=effective_graph_view,
        graph_snapshot=graph_snapshot,
    )
    if (
        projection.build_count != 1
        or projection.query_hash != plan.query_hash
        or projection.query_hash != sha256_json(query_text)
        or projection.requester_user_id != plan.requester_user_id
        or projection.workspace_id != plan.workspace_id
        or projection.source_scope_ids != plan.source_scope_ids
        or projection.graph_revision_fingerprint != graph_revision_fingerprint
        or projection.tokenizer_profile_fingerprint != tokenizer_profile.profile_fingerprint
        or projection.relation_policy_fingerprint != _relation_projection_policy_fingerprint(plan)
    ):
        raise ContractValidationError("relation projection binding mismatch")


def _graph_adjacency(
    effective_graph_view: EffectiveGraphView,
    *,
    graph_snapshot: _QueryGraphSnapshot,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> dict[str, tuple[tuple[GraphProjectionEdge, str, str], ...]]:
    _query_deadline_checkpoint(execution_deadline)
    fingerprint = _require_query_graph_snapshot(
        effective_graph_view=effective_graph_view,
        graph_snapshot=graph_snapshot,
    )
    cached = _GRAPH_ADJACENCY_CACHE.get(fingerprint)
    if cached is not None:
        _query_deadline_checkpoint(execution_deadline)
        return cached
    transitions: dict[str, list[tuple[GraphProjectionEdge, str, str]]] = {}
    for edge in effective_graph_view.visible_edges:
        _query_deadline_checkpoint(execution_deadline)
        transitions.setdefault(edge.source_node_id, []).append((edge, "out", edge.target_node_id))
        transitions.setdefault(edge.target_node_id, []).append((edge, "in", edge.source_node_id))
    adjacency: dict[str, tuple[tuple[GraphProjectionEdge, str, str], ...]] = {}
    for node_id, values in transitions.items():
        _query_deadline_checkpoint(execution_deadline)
        adjacency[node_id] = tuple(
            sorted(
                values,
                key=lambda item: (item[0].edge_id, item[1], item[2]),
            )
        )
    if len(_GRAPH_ADJACENCY_CACHE) >= 16:
        _GRAPH_ADJACENCY_CACHE.clear()
    _GRAPH_ADJACENCY_CACHE[fingerprint] = adjacency
    _query_deadline_checkpoint(execution_deadline)
    return adjacency


def _bounded_graph_traversal(
    *,
    plan: SemanticQueryPlan,
    query_text: str,
    effective_graph_view: EffectiveGraphView,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    authorized_observation_hash_by_id: Mapping[str, str],
    evidence_candidates_by_hash: Mapping[str, _HybridCandidate],
    relation_proof_slots: _EvidenceQuerySlots | None = None,
    relation_projection: _RelationQueryProjection | None = None,
    graph_snapshot: _QueryGraphSnapshot,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[tuple[BoundedGraphPath, ...], int]:
    _query_deadline_checkpoint(execution_deadline)
    if relation_projection is not None:
        _require_relation_projection_compatible(
            relation_projection,
            plan=plan,
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            tokenizer_profile=tokenizer_profile,
            graph_snapshot=graph_snapshot,
        )
        visible_nodes = {
            node_id: projected.node for node_id, projected in relation_projection.node_by_id.items()
        }
    else:
        visible_nodes = {node.node_id: node for node in effective_graph_view.visible_nodes}
    allowed_paths = set(plan.allowed_paths)
    seeds = (
        tuple(node_id for node_id in plan.seed_node_ids if node_id in visible_nodes)
        if plan.seed_node_ids
        else _matched_visible_seed_nodes(
            query_text=query_text,
            visible_nodes=tuple(visible_nodes.values()),
            tokenizer_profile=tokenizer_profile,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            limit=plan.candidate_limit,
            relation_projection=relation_projection,
            execution_deadline=execution_deadline,
        )
    )
    completion_required_slots: frozenset[tuple[str, str]] = frozenset()
    completion_slot_coverage_by_node_id: Mapping[
        str,
        frozenset[tuple[str, str]],
    ] = {}
    if relation_projection is not None and relation_proof_slots is not None:
        required_identifier_hashes = frozenset(
            _source_graph_term_hashes(tuple(relation_proof_slots.identifier_tokens))
        )
        required_concept_hashes = frozenset(
            _source_graph_term_hashes(tuple(relation_proof_slots.topic_tokens))
        )
        completion_required_slots = frozenset(
            ("identifier", term_hash) for term_hash in required_identifier_hashes
        ) | frozenset(("concept", term_hash) for term_hash in required_concept_hashes)
        completion_slot_coverage_by_node_id = {
            node_id: frozenset().union(
                *(
                    frozenset(
                        ("identifier", term_hash)
                        for term_hash in (required_identifier_hashes & supported_identifier_hashes)
                    )
                    | frozenset(
                        ("concept", term_hash)
                        for term_hash in (required_concept_hashes & supported_concept_hashes)
                    )
                    for (
                        _observation_hash,
                        supported_identifier_hashes,
                        supported_concept_hashes,
                    ) in projected_node.lineage_support_by_observation_hash
                )
            )
            for node_id, projected_node in relation_projection.node_by_id.items()
        }
    queue: deque[
        tuple[
            str,
            tuple[str, ...],
            tuple[GraphTraversalHop, ...],
            frozenset[str],
            frozenset[tuple[str, str]],
        ]
    ] = deque(
        (
            seed,
            (seed,),
            (),
            frozenset(),
            completion_slot_coverage_by_node_id.get(seed, frozenset()),
        )
        for seed in seeds
    )
    paths_by_hash: dict[str, BoundedGraphPath] = {}
    rejected_hop_count = 0
    adjacency = (
        relation_projection.adjacency
        if relation_projection is not None
        else _graph_adjacency(
            effective_graph_view,
            graph_snapshot=graph_snapshot,
            execution_deadline=execution_deadline,
        )
    )
    path_candidate_limit = max(
        plan.result_limit,
        plan.candidate_limit * plan.max_fanout * max(1, plan.max_hops),
    )
    while queue and len(paths_by_hash) < path_candidate_limit:
        _query_deadline_checkpoint(execution_deadline)
        (
            current_node_id,
            visited_node_ids,
            hops,
            path_evidence,
            path_slot_coverage,
        ) = queue.popleft()
        if len(hops) >= plan.max_hops:
            continue
        transitions = adjacency.get(current_node_id, ())
        accepted_transitions = 0
        if relation_projection is not None and completion_required_slots:
            missing_slots = completion_required_slots - path_slot_coverage
            ordered_transitions = tuple(
                sorted(
                    transitions,
                    key=lambda item: (
                        not completion_required_slots.issubset(
                            path_slot_coverage
                            | completion_slot_coverage_by_node_id.get(
                                item.next_node_id,
                                frozenset(),
                            )
                        ),
                        -len(
                            missing_slots
                            & completion_slot_coverage_by_node_id.get(
                                item.next_node_id,
                                frozenset(),
                            )
                        ),
                        item.edge.edge_id,
                        item.direction,
                        item.next_node_id,
                    ),
                )
            )
        elif relation_projection is not None:
            ordered_transitions = transitions
        else:
            ordered_transitions = tuple(
                sorted(
                    transitions,
                    key=lambda item: (item[0].edge_id, item[1], item[2]),
                )
            )
        for transition in ordered_transitions:
            _query_deadline_checkpoint(execution_deadline)
            if relation_projection is not None:
                edge = transition.edge
                direction = transition.direction
                next_node_id = transition.next_node_id
                edge_evidence = transition.authorized_evidence_hashes
                source_has_evidence = relation_projection.node_by_id[
                    current_node_id
                ].authorized_evidence_hashes
                target_has_evidence = relation_projection.node_by_id.get(next_node_id)
                target_evidence = (
                    target_has_evidence.authorized_evidence_hashes
                    if target_has_evidence is not None
                    else None
                )
            else:
                edge, direction, next_node_id = transition
                edge_evidence = _authorized_property_evidence_hashes(
                    edge.properties,
                    authorized_observation_hash_by_id=authorized_observation_hash_by_id,
                )
                source_has_evidence = _authorized_property_evidence_hashes(
                    visible_nodes[current_node_id].properties,
                    authorized_observation_hash_by_id=authorized_observation_hash_by_id,
                )
                target_evidence = _authorized_property_evidence_hashes(
                    visible_nodes[next_node_id].properties,
                    authorized_observation_hash_by_id=authorized_observation_hash_by_id,
                )
            if (edge.relation_type, direction) not in allowed_paths:
                rejected_hop_count += 1
                continue
            if next_node_id in visited_node_ids or next_node_id not in visible_nodes:
                continue
            if edge_evidence is None or source_has_evidence is None or target_evidence is None:
                rejected_hop_count += 1
                continue
            hop_evidence = edge_evidence
            proposed_evidence = set(path_evidence).union(hop_evidence)
            if len(proposed_evidence) > plan.evidence_budget:
                rejected_hop_count += 1
                continue
            hop = GraphTraversalHop(
                edge_hash=sha256_json(edge.edge_id),
                relation_type_hash=sha256_json(edge.relation_type),
                direction=direction,
                source_node_hash=sha256_json(current_node_id),
                target_node_hash=sha256_json(next_node_id),
                cited_observation_hashes=hop_evidence,
            )
            next_hops = (*hops, hop)
            next_visited = (*visited_node_ids, next_node_id)
            next_slot_coverage = path_slot_coverage | completion_slot_coverage_by_node_id.get(
                next_node_id,
                frozenset(),
            )
            cited_hashes = tuple(sorted(proposed_evidence))
            path_hash = sha256_json(
                {
                    "plan_fingerprint": plan.plan_fingerprint,
                    "node_hashes": [sha256_json(node_id) for node_id in next_visited],
                    "edge_hashes": [item.edge_hash for item in next_hops],
                    "cited_observation_hashes": list(cited_hashes),
                }
            )
            path = BoundedGraphPath(
                path_hash=path_hash,
                hop_count=len(next_hops),
                graph_path_score=_metric(max(0.0, 1.0 - 0.15 * (len(next_hops) - 1))),
                cited_observation_hashes=cited_hashes,
                hops=next_hops,
            )
            paths_by_hash[path_hash] = path
            accepted_transitions += 1
            if len(next_hops) < plan.max_hops:
                queue.append(
                    (
                        next_node_id,
                        next_visited,
                        next_hops,
                        frozenset(cited_hashes),
                        next_slot_coverage,
                    )
                )
            if accepted_transitions >= plan.max_fanout:
                break
    ordered_paths = _rank_relation_graph_paths(
        tuple(paths_by_hash.values()),
        query_text=query_text,
        tokenizer_profile=tokenizer_profile,
        evidence_candidates_by_hash=evidence_candidates_by_hash,
        result_limit=plan.result_limit,
        slots_override=relation_proof_slots,
        relation_projection=relation_projection,
        execution_deadline=execution_deadline,
    )
    _query_deadline_checkpoint(execution_deadline)
    return ordered_paths, rejected_hop_count


def _matched_visible_seed_nodes(
    *,
    query_text: str,
    visible_nodes: Sequence[GraphProjectionNode],
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    authorized_observation_hash_by_id: Mapping[str, str],
    limit: int,
    relation_projection: _RelationQueryProjection | None = None,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[str, ...]:
    _query_deadline_checkpoint(execution_deadline)
    if relation_projection is not None:
        return relation_projection.initial_query_anchor_node_ids[:limit]
    query_analysis = tokenizer_profile.analyze(query_text)
    query_tokens = set(query_analysis.tokens)
    protected_query_tokens = {span.exact_token for span in query_analysis.protected_identifiers}
    query_term_hashes = set(_source_graph_term_hashes(tuple(query_tokens)))
    protected_query_hashes = set(_source_graph_term_hashes(tuple(protected_query_tokens)))
    matches: list[tuple[float, str]] = []
    seedable_node_kinds = {
        "candidate_entity",
        "candidate_source_term",
        "source_observation",
    }
    for node in visible_nodes:
        _query_deadline_checkpoint(execution_deadline)
        projected_node = (
            relation_projection.node_by_id.get(node.node_id)
            if relation_projection is not None
            else None
        )
        node_kind = (
            projected_node.node_kind
            if projected_node is not None
            else node.properties.get("node_kind")
        )
        if node_kind is not None and node_kind not in seedable_node_kinds:
            continue
        node_evidence = (
            projected_node.authorized_evidence_hashes
            if projected_node is not None
            else _authorized_property_evidence_hashes(
                node.properties,
                authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            )
        )
        if node_evidence is None:
            continue
        if projected_node is not None:
            node_term_hashes = set(projected_node.source_term_hashes)
            node_protected_hashes = set(projected_node.protected_term_hashes)
            node_tokens = set(projected_node.searchable_tokens)
            node_protected = set(projected_node.searchable_protected_tokens)
        else:
            node_term_hashes = _node_source_term_hashes(node)
            node_protected_hashes = _node_protected_term_hashes(node)
            searchable = " ".join(_node_searchable_values(node))
            analysis = tokenizer_profile.analyze(searchable)
            node_tokens = set(analysis.tokens)
            node_protected = {span.exact_token for span in analysis.protected_identifiers}
        lexical_overlap = max(
            len(query_tokens & node_tokens),
            len(query_term_hashes & node_term_hashes),
        )
        protected_overlap = max(
            len(protected_query_tokens & node_protected),
            len(protected_query_hashes & (node_protected_hashes | node_term_hashes)),
        )
        score = float(lexical_overlap + (2 * protected_overlap))
        if protected_query_tokens and protected_overlap:
            matches.append((score, node.node_id))
        elif not protected_query_tokens and (
            lexical_overlap >= 2
            or (
                node_kind in {"candidate_source_term", "source_observation"}
                and bool(query_term_hashes & node_term_hashes)
            )
        ):
            matches.append((score, node.node_id))
    _query_deadline_checkpoint(execution_deadline)
    return tuple(
        node_id for _, node_id in sorted(matches, key=lambda item: (-item[0], item[1]))[:limit]
    )


def _node_searchable_values(node: GraphProjectionNode) -> tuple[str, ...]:
    values: list[str] = [value for value in node.labels if isinstance(value, str)]
    for field_name in (
        "label",
        "canonical_label",
        "inventory_value",
        "summary",
    ):
        value = node.properties.get(field_name)
        if isinstance(value, str):
            values.append(value)
    aliases = node.properties.get("aliases")
    if isinstance(aliases, (list, tuple)):
        values.extend(value for value in aliases if isinstance(value, str))
    return tuple(values)


def _node_source_term_hashes(node: GraphProjectionNode) -> set[str]:
    hashes = _safe_hash_property_values(node.properties.get("source_term_hashes"))
    hashes.update(
        _source_graph_term_hashes(tuple(value for value in _node_searchable_values(node) if value))
    )
    return hashes


def _node_protected_term_hashes(node: GraphProjectionNode) -> set[str]:
    return _safe_hash_property_values(node.properties.get("protected_term_hashes"))


def _safe_hash_property_values(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple)):
        return set()
    return {
        item
        for item in value
        if isinstance(item, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", item) is not None
    }


def _authorized_property_evidence_hashes(
    properties: Mapping[str, Any],
    *,
    authorized_observation_hash_by_id: Mapping[str, str],
) -> tuple[str, ...] | None:
    values = properties.get("source_observation_ids")
    if not isinstance(values, (list, tuple)) or not values:
        return None
    observation_ids = tuple(
        sorted({value for value in values if isinstance(value, str) and value.strip()})
    )
    if not observation_ids or any(
        observation_id not in authorized_observation_hash_by_id
        for observation_id in observation_ids
    ):
        return None
    return tuple(
        authorized_observation_hash_by_id[observation_id] for observation_id in observation_ids
    )


def _semantic_evidence_scores(
    *,
    plan: SemanticQueryPlan,
    query_text: str,
    hybrid_result: GovernedHybridRagResult,
    index: AuthorizedHybridMailIndex,
    graph_paths: Sequence[BoundedGraphPath],
    effective_graph_view: EffectiveGraphView,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    authorized_observation_hash_by_id: Mapping[str, str],
    enable_entity_signal: bool,
    legacy_hard_gate: bool,
    relation_projection: _RelationQueryProjection | None = None,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[SemanticEvidenceScore, ...]:
    _query_deadline_checkpoint(execution_deadline)
    query_analysis = tokenizer_profile.analyze(query_text)
    _query_deadline_checkpoint(execution_deadline)
    query_tokens = set(query_analysis.tokens)
    protected_query_tokens = {span.exact_token for span in query_analysis.protected_identifiers}
    candidates_by_hash = {
        candidate.source_observation_hash: candidate for candidate in index.candidates
    }
    graph_nodes_by_observation_hash = (
        relation_projection.graph_nodes_by_observation_hash
        if relation_projection is not None
        else _graph_nodes_by_observation_hash(
            effective_graph_view=effective_graph_view,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            execution_deadline=execution_deadline,
        )
    )
    path_scores_by_observation_hash: dict[str, float] = {}
    for path in graph_paths:
        _query_deadline_checkpoint(execution_deadline)
        for observation_hash in path.cited_observation_hashes:
            _query_deadline_checkpoint(execution_deadline)
            path_scores_by_observation_hash[observation_hash] = max(
                path_scores_by_observation_hash.get(observation_hash, 0.0),
                path.graph_path_score,
            )
    candidate_scores_by_observation_hash = {
        candidate_score.source_observation_hash: candidate_score
        for candidate_score in hybrid_result.admitted_candidate_scores
    }
    admitted_observation_hashes = set(candidate_scores_by_observation_hash)
    admitted_observation_hashes.update(path_scores_by_observation_hash)
    scores: list[SemanticEvidenceScore] = []
    authorized_observation_hashes = set(authorized_observation_hash_by_id.values())
    for observation_hash in sorted(admitted_observation_hashes):
        _query_deadline_checkpoint(execution_deadline)
        candidate = candidates_by_hash.get(observation_hash)
        if candidate is None:
            continue
        candidate_score = candidate_scores_by_observation_hash.get(observation_hash)
        lexical_score = (
            candidate_score.bm25_score / (1.0 + candidate_score.bm25_score)
            if candidate_score is not None
            else 0.0
        )
        dense_score = (
            max(0.0, min(1.0, candidate_score.dense_score)) if candidate_score is not None else 0.0
        )
        nodes = graph_nodes_by_observation_hash.get(
            candidate.source_observation_hash,
            (),
        )
        if (
            legacy_hard_gate
            and plan.target_core_supertype_id is not None
            and not _legacy_ontology_hard_gate_accepts(
                nodes,
                target_core_supertype_id=plan.target_core_supertype_id,
            )
        ):
            continue
        if enable_entity_signal:
            entity_score = _graph_entity_score(
                nodes,
                query_tokens=query_tokens,
                protected_query_tokens=protected_query_tokens,
                tokenizer_profile=tokenizer_profile,
                relation_projection=relation_projection,
            )
        else:
            entity_score = 0.0
        temporal_score = _temporal_current_score(nodes)
        ontology_bonus = _capped_ontology_bonus(
            nodes,
            target_core_supertype_id=plan.target_core_supertype_id,
        )
        graph_path_score = path_scores_by_observation_hash.get(
            candidate.source_observation_hash,
            0.0,
        )
        provenance_coverage_score = (
            1.0 if candidate.source_observation_hash in authorized_observation_hashes else 0.0
        )
        base_score = (
            (0.25 * lexical_score)
            + (0.20 * dense_score)
            + (0.15 * entity_score)
            + (0.15 * graph_path_score)
            + (0.10 * temporal_score)
            + (0.15 * provenance_coverage_score)
        )
        scores.append(
            SemanticEvidenceScore(
                evidence_bundle_hash=candidate.coherence_group_hash,
                source_observation_hash=candidate.source_observation_hash,
                message_hash=candidate.message_hash,
                lexical_score=_metric(lexical_score),
                dense_score=_metric(dense_score),
                entity_score=_metric(entity_score),
                graph_path_score=_metric(graph_path_score),
                temporal_current_score=_metric(temporal_score),
                provenance_coverage_score=_metric(provenance_coverage_score),
                ontology_bonus=_metric(ontology_bonus),
                ontology_bonus_cap=0.2,
                base_score=_metric(base_score),
                total_score=_metric(base_score + ontology_bonus),
            )
        )
    _query_deadline_checkpoint(execution_deadline)
    return tuple(
        sorted(
            scores,
            key=lambda item: (
                -item.total_score,
                item.source_observation_hash,
            ),
        )
    )


def _bounded_semantic_answer_citation_hashes(
    *,
    plan: SemanticQueryPlan,
    query_text: str,
    hybrid_result: GovernedHybridRagResult,
    semantic_scores: Sequence[SemanticEvidenceScore],
    graph_paths: Sequence[BoundedGraphPath],
    index: AuthorizedHybridMailIndex,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[str, ...]:
    """Return the smallest deterministic Observation-level proof available."""

    _query_deadline_checkpoint(execution_deadline)
    evidence_budget = plan.evidence_budget
    proof_slots = _deterministic_high_idf_proof_slots(
        query_text,
        query_class=plan.query_class,
        tokenizer_profile=tokenizer_profile,
        document_frequency=dict(index.document_frequency),
        document_count=len(index.candidates),
    )
    _query_deadline_checkpoint(execution_deadline)
    if proof_slots is None:
        return ()
    candidates_by_hash = {
        candidate.source_observation_hash: candidate for candidate in index.candidates
    }
    scores_by_observation_hash = {score.source_observation_hash: score for score in semantic_scores}

    if plan.query_class == "relation_reasoning":
        return _minimal_relation_proof_citations(
            query_text=query_text,
            graph_paths=graph_paths,
            candidates_by_hash=candidates_by_hash,
            scores_by_observation_hash=scores_by_observation_hash,
            tokenizer_profile=tokenizer_profile,
            evidence_budget=evidence_budget,
            execution_deadline=execution_deadline,
        )

    admitted_hashes = {
        score.source_observation_hash for score in hybrid_result.admitted_candidate_scores
    }
    ranked_by_group: dict[str, list[tuple[_HybridCandidate, float]]] = {}
    for score in semantic_scores:
        _query_deadline_checkpoint(execution_deadline)
        if (
            score.source_observation_hash not in admitted_hashes
            or score.source_observation_hash not in candidates_by_hash
        ):
            continue
        candidate = candidates_by_hash[score.source_observation_hash]
        ranked_by_group.setdefault(candidate.coherence_group_hash, []).append(
            (candidate, score.total_score)
        )
    proofs: list[tuple[tuple[str, ...], float, str]] = []
    for coherence_group_hash, ranked_candidates in ranked_by_group.items():
        _query_deadline_checkpoint(execution_deadline)
        citations = _minimal_candidate_proof_citations(
            ranked_candidates,
            slots=proof_slots,
            evidence_budget=evidence_budget,
            execution_deadline=execution_deadline,
        )
        if not citations:
            continue
        proofs.append(
            (
                citations,
                sum(
                    score
                    for candidate, score in ranked_candidates
                    if candidate.source_observation_hash in citations
                ),
                coherence_group_hash,
            )
        )
    if not proofs:
        return ()
    citations, _, _ = min(
        proofs,
        key=lambda item: (
            len(item[0]),
            -item[1],
            item[2],
            item[0],
        ),
    )
    return citations


def _minimal_hybrid_answer_citation_hashes(
    *,
    ordered_results: Sequence[HybridRagBundleScore],
    candidates: Sequence[_HybridCandidate],
    proof_slots: _EvidenceQuerySlots,
    evidence_budget: int,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[str, ...]:
    _query_deadline_checkpoint(execution_deadline)
    if not ordered_results:
        return ()
    candidates_by_hash = {candidate.source_observation_hash: candidate for candidate in candidates}
    ranked: list[tuple[_HybridCandidate, float]] = []
    for score in ordered_results[0].candidate_scores:
        _query_deadline_checkpoint(execution_deadline)
        candidate = candidates_by_hash.get(score.source_observation_hash)
        if candidate is not None:
            ranked.append((candidate, score.fusion_score))
    return _minimal_candidate_proof_citations(
        ranked,
        slots=proof_slots,
        evidence_budget=evidence_budget,
        execution_deadline=execution_deadline,
    )


def _minimal_candidate_proof_citations(
    ranked_candidates: Sequence[tuple[_HybridCandidate, float]],
    *,
    slots: _EvidenceQuerySlots,
    evidence_budget: int,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[str, ...]:
    _query_deadline_checkpoint(execution_deadline)
    best_by_hash: dict[str, tuple[_HybridCandidate, float]] = {}
    for candidate, score in ranked_candidates:
        _query_deadline_checkpoint(execution_deadline)
        existing = best_by_hash.get(candidate.source_observation_hash)
        if existing is None or score > existing[1]:
            best_by_hash[candidate.source_observation_hash] = (candidate, score)
    candidates = tuple(best_by_hash.values())
    coverable_identifiers = frozenset().union(
        *(candidate.observation_protected_identifier_tokens for candidate, _ in candidates)
    )
    if not slots.identifier_tokens.issubset(coverable_identifiers):
        return ()
    coverable_topics = frozenset().union(
        *(candidate.observation_tokens for candidate, _ in candidates)
    )
    if not slots.topic_tokens.issubset(coverable_topics):
        return ()
    if not slots.identifier_tokens and not slots.topic_tokens:
        return ()
    required = frozenset(("identifier", token) for token in slots.identifier_tokens) | frozenset(
        ("topic", token) for token in slots.topic_tokens
    )
    ordered_candidates = tuple(
        sorted(
            candidates,
            key=lambda item: (
                -item[1],
                item[0].source_observation_hash,
            ),
        )
    )
    states: dict[
        frozenset[tuple[str, str]],
        tuple[tuple[str, ...], float],
    ] = {frozenset(): ((), 0.0)}
    for candidate, score in ordered_candidates:
        _query_deadline_checkpoint(execution_deadline)
        candidate_coverage = frozenset(
            ("identifier", token)
            for token in (
                candidate.observation_protected_identifier_tokens & slots.identifier_tokens
            )
        ) | frozenset(
            ("topic", token) for token in candidate.observation_tokens & slots.topic_tokens
        )
        if not candidate_coverage:
            continue
        updated = dict(states)
        for covered, (selected_hashes, selected_score) in states.items():
            _query_deadline_checkpoint(execution_deadline)
            if len(selected_hashes) >= evidence_budget:
                continue
            proposed_covered = covered | candidate_coverage
            proposed = (
                (*selected_hashes, candidate.source_observation_hash),
                selected_score + score,
            )
            existing = updated.get(proposed_covered)
            if existing is None or _proof_selection_key(proposed) < _proof_selection_key(existing):
                updated[proposed_covered] = proposed
        states = updated
    _query_deadline_checkpoint(execution_deadline)
    selected = states.get(required)
    return selected[0] if selected is not None else ()


def _proof_selection_key(
    selection: tuple[tuple[str, ...], float],
) -> tuple[int, float, tuple[str, ...]]:
    selected_hashes, selected_score = selection
    return (
        len(selected_hashes),
        -selected_score,
        selected_hashes,
    )


def _relation_path_satisfies_query_slots(
    path: BoundedGraphPath,
    *,
    slots: _EvidenceQuerySlots,
    candidates_by_hash: Mapping[str, _HybridCandidate],
) -> bool:
    path_candidates = [
        candidates_by_hash[evidence_hash]
        for evidence_hash in path.cited_observation_hashes
        if evidence_hash in candidates_by_hash
    ]
    if len(path_candidates) != len(set(path.cited_observation_hashes)):
        return False
    covered_identifiers = frozenset().union(
        *(candidate.observation_protected_identifier_tokens for candidate in path_candidates)
    )
    if not slots.identifier_tokens.issubset(covered_identifiers):
        return False
    covered_topics = slots.topic_tokens & frozenset().union(
        *(candidate.observation_tokens for candidate in path_candidates)
    )
    if not slots.topic_tokens.issubset(covered_topics):
        return False
    if slots.identifier_tokens:
        return True
    return (
        bool(slots.topic_tokens)
        and len({candidate.message_hash for candidate in path_candidates}) >= 2
    )


def _deterministic_required_relation_slots(
    query_text: str,
    *,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    candidates_by_hash: Mapping[str, _HybridCandidate],
) -> _EvidenceQuerySlots | None:
    """Return all source-verifiable relation slots without score thresholds.

    Relation answers require every protected identifier and every non-operator
    query concept to be present in the authorized Observation projection.  A
    missing slot blocks the relation claim instead of silently falling back to
    whichever retrieved candidate happened to rank highest.
    """

    slots = _query_evidence_slots(
        query_text,
        query_class="relation_reasoning",
        tokenizer_profile=tokenizer_profile,
    )
    if not slots.identifier_tokens and not slots.topic_tokens:
        return None
    authorized_identifiers = frozenset().union(
        *(
            candidate.observation_protected_identifier_tokens
            for candidate in candidates_by_hash.values()
        )
    )
    authorized_topics = frozenset().union(
        *(candidate.observation_tokens for candidate in candidates_by_hash.values())
    )
    if not slots.identifier_tokens.issubset(authorized_identifiers):
        return None
    if not slots.topic_tokens.issubset(authorized_topics):
        return None
    return slots


def _deterministic_relation_fallback_slots(
    query_text: str,
    *,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    document_frequency: Mapping[str, int],
    document_count: int,
    index_fingerprint: str,
    graph_revision_fingerprint: str,
    effective_graph_view: EffectiveGraphView,
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, _HybridCandidate],
    relation_projection: _RelationQueryProjection | None = None,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> _RelationFallbackSlotSelection | None:
    """Pin one maximal authorized concept while retaining every identifier."""

    _query_deadline_checkpoint(execution_deadline)
    query_slots = _query_evidence_slots(
        query_text,
        query_class="relation_reasoning",
        tokenizer_profile=tokenizer_profile,
    )
    authorized_identifier_tokens = frozenset().union(
        *(
            candidate.observation_protected_identifier_tokens
            for candidate in candidates_by_hash.values()
        )
    )
    if not query_slots.identifier_tokens.issubset(authorized_identifier_tokens):
        return None
    if relation_projection is not None:
        indexed_vocabulary_hashes = set(relation_projection.authorized_index_vocabulary_hashes)
        graph_vocabulary_hashes = set(relation_projection.authorized_graph_vocabulary_hashes)
    else:
        indexed_vocabulary_hashes = {
            sha256_json(token)
            for candidate in candidates_by_hash.values()
            for token in candidate.observation_tokens
        }
        graph_vocabulary_hashes = set()
        for node in effective_graph_view.visible_nodes:
            _query_deadline_checkpoint(execution_deadline)
            if (
                _authorized_property_evidence_hashes(
                    node.properties,
                    authorized_observation_hash_by_id=authorized_observation_hash_by_id,
                )
                is None
            ):
                continue
            graph_vocabulary_hashes.update(_node_source_term_hashes(node))
            graph_vocabulary_hashes.update(_node_protected_term_hashes(node))
    authorized_vocabulary_hashes = indexed_vocabulary_hashes | graph_vocabulary_hashes
    eligible_topics = {
        token
        for token in query_slots.topic_tokens
        if 0 < document_frequency.get(token, 0) <= document_count
        and sha256_json(token) in authorized_vocabulary_hashes
    }
    maximal_topics = {
        token
        for token in eligible_topics
        if not any(token != other and token in other for other in eligible_topics)
    }
    if not maximal_topics:
        return None

    def concept_order(token: str) -> tuple[float, str]:
        frequency = document_frequency[token]
        inverse_document_frequency = math.log(
            1.0 + ((document_count - frequency + 0.5) / (frequency + 0.5))
        )
        return (-inverse_document_frequency, sha256_json(token))

    selected_concept = min(maximal_topics, key=concept_order)
    identifier_hashes = _source_graph_term_hashes(tuple(query_slots.identifier_tokens))
    concept_hashes = _source_graph_term_hashes((selected_concept,))
    vocabulary_fingerprint = sha256_json(
        {
            "policy_fingerprint": _RELATION_FALLBACK_POLICY_FINGERPRINT,
            "index_fingerprint": index_fingerprint,
            "graph_revision_fingerprint": graph_revision_fingerprint,
            "authorized_index_vocabulary_hashes": sorted(indexed_vocabulary_hashes),
            "authorized_graph_vocabulary_hashes": sorted(graph_vocabulary_hashes),
            "eligible_query_concept_hashes": sorted(sha256_json(token) for token in maximal_topics),
            "eligible_document_frequency": [
                [sha256_json(token), document_frequency[token]]
                for token in sorted(maximal_topics, key=sha256_json)
            ],
            "document_count": document_count,
        }
    )
    _query_deadline_checkpoint(execution_deadline)
    return _RelationFallbackSlotSelection(
        identifier_tokens=query_slots.identifier_tokens,
        concept_tokens=frozenset((selected_concept,)),
        identifier_term_hashes=identifier_hashes,
        concept_term_hashes=concept_hashes,
        vocabulary_fingerprint=vocabulary_fingerprint,
    )


def _matched_relation_fallback_seed_nodes(
    *,
    selection: _RelationFallbackSlotSelection,
    visible_nodes: Sequence[GraphProjectionNode],
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, _HybridCandidate],
    limit: int,
    relation_projection: _RelationQueryProjection | None = None,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[str, ...]:
    """Resolve query-linked seeds from safe node hashes or cited evidence."""

    required_identifier_hashes = set(selection.identifier_term_hashes)
    required_concept_hashes = set(selection.concept_term_hashes)
    matches: list[tuple[int, str]] = []
    for node in visible_nodes:
        _query_deadline_checkpoint(execution_deadline)
        projected_node = (
            relation_projection.node_by_id.get(node.node_id)
            if relation_projection is not None
            else None
        )
        evidence_hashes = (
            projected_node.authorized_evidence_hashes
            if projected_node is not None
            else _authorized_property_evidence_hashes(
                node.properties,
                authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            )
        )
        if evidence_hashes is None:
            continue
        if projected_node is not None:
            node_identifier_hashes = set(projected_node.protected_term_hashes)
            node_identifier_hashes.update(projected_node.bound_candidate_identifier_term_hashes)
            node_concept_hashes = set(projected_node.source_term_hashes)
            node_concept_hashes.update(projected_node.bound_candidate_concept_term_hashes)
        else:
            node_identifier_hashes = _node_protected_term_hashes(node)
            node_concept_hashes = _node_source_term_hashes(node)
            for evidence_hash in evidence_hashes:
                _query_deadline_checkpoint(execution_deadline)
                candidate = candidates_by_hash.get(evidence_hash)
                if candidate is None:
                    continue
                node_identifier_hashes.update(
                    _source_graph_term_hashes(
                        tuple(candidate.observation_protected_identifier_tokens)
                    )
                )
                node_concept_hashes.update(
                    _source_graph_term_hashes(tuple(candidate.observation_tokens))
                )
        identifier_overlap = len(required_identifier_hashes & node_identifier_hashes)
        concept_overlap = len(required_concept_hashes & node_concept_hashes)
        if identifier_overlap or concept_overlap:
            matches.append(
                (
                    (2 * identifier_overlap) + concept_overlap,
                    node.node_id,
                )
            )
    _query_deadline_checkpoint(execution_deadline)
    return tuple(
        node_id
        for _, node_id in sorted(
            matches,
            key=lambda item: (-item[0], item[1]),
        )[:limit]
    )


def _relation_fallback_node_slot_coverage(
    *,
    path: BoundedGraphPath,
    selection: _RelationFallbackSlotSelection,
    visible_nodes_by_hash: Mapping[str, GraphProjectionNode],
    authorized_observation_hash_by_id: Mapping[str, str],
    candidates_by_hash: Mapping[str, _HybridCandidate],
    relation_projection: _RelationQueryProjection | None = None,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[tuple[str, frozenset[tuple[str, str]]], ...]:
    """Return term-level support from authorized Observations bound to path nodes."""

    path_node_hashes = _path_node_hashes(path)
    support_by_observation_hash: dict[str, set[tuple[str, str]]] = {}
    required_identifier_hashes = set(selection.identifier_term_hashes)
    required_concept_hashes = set(selection.concept_term_hashes)
    for node_hash in sorted(path_node_hashes):
        _query_deadline_checkpoint(execution_deadline)
        if relation_projection is not None:
            projected_node = relation_projection.node_by_hash.get(node_hash)
            if projected_node is None:
                continue
            for (
                observation_hash,
                supported_identifier_hashes,
                supported_concept_hashes,
            ) in projected_node.lineage_support_by_observation_hash:
                _query_deadline_checkpoint(execution_deadline)
                coverage = {
                    ("identifier", term_hash)
                    for term_hash in (required_identifier_hashes & supported_identifier_hashes)
                } | {
                    ("concept", term_hash)
                    for term_hash in (required_concept_hashes & supported_concept_hashes)
                }
                if coverage:
                    support_by_observation_hash.setdefault(
                        observation_hash,
                        set(),
                    ).update(coverage)
            continue
        # Graph paths expose only hashed node identities. Resolve that identity
        # before considering any node-backed terms.
        node = visible_nodes_by_hash.get(node_hash)
        if node is None:
            continue
        node_evidence = _authorized_property_evidence_hashes(
            node.properties,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        )
        if node_evidence is None:
            continue
        node_identifier_hashes = _node_protected_term_hashes(node)
        node_concept_hashes = _node_source_term_hashes(node)
        for observation_hash in node_evidence:
            _query_deadline_checkpoint(execution_deadline)
            candidate = candidates_by_hash.get(observation_hash)
            if candidate is None:
                continue
            candidate_identifier_hashes = set(
                _source_graph_term_hashes(tuple(candidate.observation_protected_identifier_tokens))
            )
            candidate_concept_hashes = set(
                _source_graph_term_hashes(tuple(candidate.observation_tokens))
            )
            coverage = {
                ("identifier", term_hash)
                for term_hash in (
                    required_identifier_hashes
                    & node_identifier_hashes
                    & candidate_identifier_hashes
                )
            } | {
                ("concept", term_hash)
                for term_hash in (
                    required_concept_hashes & node_concept_hashes & candidate_concept_hashes
                )
            }
            if coverage:
                support_by_observation_hash.setdefault(observation_hash, set()).update(coverage)
    return tuple(
        (observation_hash, frozenset(coverage))
        for observation_hash, coverage in sorted(support_by_observation_hash.items())
    )


def _minimal_relation_fallback_path_citations(
    *,
    path: BoundedGraphPath,
    required: frozenset[tuple[str, str]],
    selection: _RelationFallbackSlotSelection,
    candidates_by_hash: Mapping[str, _HybridCandidate],
    visible_nodes_by_hash: Mapping[str, GraphProjectionNode],
    authorized_observation_hash_by_id: Mapping[str, str],
    evidence_budget: int,
    relation_projection: _RelationQueryProjection | None = None,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[str, ...]:
    _query_deadline_checkpoint(execution_deadline)
    base_citations = tuple(sorted(set(path.cited_observation_hashes)))
    if len(base_citations) > evidence_budget:
        return ()
    path_node_support = dict(
        _relation_fallback_node_slot_coverage(
            path=path,
            selection=selection,
            visible_nodes_by_hash=visible_nodes_by_hash,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            candidates_by_hash=candidates_by_hash,
            relation_projection=relation_projection,
            execution_deadline=execution_deadline,
        )
    )
    node_supported_slots = frozenset().union(*path_node_support.values())
    if not required.issubset(node_supported_slots):
        return ()

    coverage_by_observation_hash: dict[str, frozenset[tuple[str, str]]] = {}
    if relation_projection is not None:
        for observation_hash, node_coverage in path_node_support.items():
            _query_deadline_checkpoint(execution_deadline)
            coverage_by_observation_hash[observation_hash] = (
                relation_projection.candidate_query_slot_coverage_by_observation.get(
                    observation_hash,
                    frozenset(),
                )
                & required
                & node_coverage
            )
    else:
        for observation_hash in base_citations:
            _query_deadline_checkpoint(execution_deadline)
            candidate = candidates_by_hash.get(observation_hash)
            if candidate is None:
                continue
            coverage_by_observation_hash[observation_hash] = frozenset(
                ("identifier", term_hash)
                for term_hash in _source_graph_term_hashes(
                    tuple(candidate.observation_protected_identifier_tokens)
                )
                if term_hash in selection.identifier_term_hashes
            ) | frozenset(
                ("concept", term_hash)
                for term_hash in _source_graph_term_hashes(tuple(candidate.observation_tokens))
                if term_hash in selection.concept_term_hashes
            )
        for observation_hash, node_coverage in path_node_support.items():
            _query_deadline_checkpoint(execution_deadline)
            coverage_by_observation_hash[observation_hash] = (
                coverage_by_observation_hash.get(
                    observation_hash,
                    frozenset(),
                )
                | node_coverage
            )

    for observation_hash in base_citations:
        _query_deadline_checkpoint(execution_deadline)
        coverage_by_observation_hash.setdefault(
            observation_hash,
            frozenset(),
        )

    covered_by_base = frozenset().union(
        *(
            coverage_by_observation_hash.get(observation_hash, frozenset())
            for observation_hash in base_citations
        )
    )
    if required.issubset(covered_by_base):
        return base_citations
    states: dict[
        frozenset[tuple[str, str]],
        tuple[str, ...],
    ] = {covered_by_base: ()}
    for observation_hash in sorted(set(coverage_by_observation_hash) - set(base_citations)):
        _query_deadline_checkpoint(execution_deadline)
        observation_coverage = coverage_by_observation_hash[observation_hash]
        if not observation_coverage:
            continue
        updated = dict(states)
        for covered, selected_hashes in states.items():
            _query_deadline_checkpoint(execution_deadline)
            if len(base_citations) + len(selected_hashes) >= evidence_budget:
                continue
            proposed_covered = covered | observation_coverage
            proposed_hashes = (*selected_hashes, observation_hash)
            existing_hashes = updated.get(proposed_covered)
            if existing_hashes is None or (
                len(proposed_hashes),
                proposed_hashes,
            ) < (
                len(existing_hashes),
                existing_hashes,
            ):
                updated[proposed_covered] = proposed_hashes
        states = updated
    eligible = [
        (selected_hashes, covered)
        for covered, selected_hashes in states.items()
        if required.issubset(covered)
    ]
    if not eligible:
        return ()
    selected_hashes, _ = min(
        eligible,
        key=lambda item: (
            len(item[0]),
            item[0],
        ),
    )
    citations = tuple(sorted((*base_citations, *selected_hashes)))
    authorized_hashes = frozenset(authorized_observation_hash_by_id.values())
    if len(citations) > evidence_budget or not set(citations).issubset(authorized_hashes):
        return ()
    _query_deadline_checkpoint(execution_deadline)
    return citations


def _connected_relation_fallback_citations(
    *,
    graph_paths: Sequence[BoundedGraphPath],
    selection: _RelationFallbackSlotSelection,
    candidates_by_hash: Mapping[str, _HybridCandidate],
    visible_nodes: Sequence[GraphProjectionNode],
    authorized_observation_hash_by_id: Mapping[str, str],
    evidence_budget: int,
    relation_projection: _RelationQueryProjection | None = None,
    required_anchor_node_hashes: frozenset[str] = frozenset(),
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[str, ...]:
    """Select one complete connected path; never assemble isolated chunks."""

    _query_deadline_checkpoint(execution_deadline)
    authorized_observation_hashes = frozenset(authorized_observation_hash_by_id.values())
    visible_nodes_by_hash = (
        {
            node_hash: projected.node
            for node_hash, projected in relation_projection.node_by_hash.items()
        }
        if relation_projection is not None
        else {sha256_json(node.node_id): node for node in visible_nodes}
    )
    required = frozenset(
        ("identifier", term_hash) for term_hash in selection.identifier_term_hashes
    ) | frozenset(("concept", term_hash) for term_hash in selection.concept_term_hashes)
    proofs: list[tuple[BoundedGraphPath, tuple[str, ...]]] = []
    for path in graph_paths:
        _query_deadline_checkpoint(execution_deadline)
        path_node_hashes = _path_node_hashes(path)
        hop_citations = {
            evidence_hash for hop in path.hops for evidence_hash in hop.cited_observation_hashes
        }
        if (
            not path.hops
            or (
                required_anchor_node_hashes
                and required_anchor_node_hashes.isdisjoint(path_node_hashes)
            )
            or len(path.cited_observation_hashes) > evidence_budget
            or not set(path.cited_observation_hashes).issubset(authorized_observation_hashes)
            or hop_citations != set(path.cited_observation_hashes)
            or any(
                not hop.cited_observation_hashes
                or not set(hop.cited_observation_hashes).issubset(authorized_observation_hashes)
                for hop in path.hops
            )
        ):
            continue
        citations = _minimal_relation_fallback_path_citations(
            path=path,
            required=required,
            selection=selection,
            candidates_by_hash=candidates_by_hash,
            visible_nodes_by_hash=visible_nodes_by_hash,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            evidence_budget=evidence_budget,
            relation_projection=relation_projection,
            execution_deadline=execution_deadline,
        )
        if citations:
            proofs.append((path, citations))
    if not proofs:
        return ()
    _, selected_citations = min(
        proofs,
        key=lambda item: (
            len(item[1]),
            item[0].hop_count,
            -item[0].graph_path_score,
            item[0].path_hash,
            item[1],
        ),
    )
    _query_deadline_checkpoint(execution_deadline)
    return selected_citations


def _execute_bounded_relation_fallback(
    *,
    plan: SemanticQueryPlan,
    query_text: str,
    graph_paths: Sequence[BoundedGraphPath],
    effective_graph_view: EffectiveGraphView,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    document_frequency: Mapping[str, int],
    document_count: int,
    index_fingerprint: str,
    authorized_observation_hash_by_id: Mapping[str, str],
    evidence_candidates_by_hash: Mapping[str, _HybridCandidate],
    authorized_workspace_id: str,
    authorized_source_scope_ids: Sequence[str],
    authorized_source: AuthorizedSemanticSource | None,
    supported_relation_types: Sequence[str],
    limits: SemanticPlanLimits,
    relation_projection: _RelationQueryProjection | None = None,
    graph_snapshot: _QueryGraphSnapshot,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> _RelationFallbackOutcome | None:
    _query_deadline_checkpoint(execution_deadline)
    if plan.repair_budget < 1 or plan.repair_attempt_count >= plan.repair_budget:
        return None
    graph_revision_fingerprint = _require_query_graph_snapshot(
        effective_graph_view=effective_graph_view,
        graph_snapshot=graph_snapshot,
    )
    selection = _deterministic_relation_fallback_slots(
        query_text,
        tokenizer_profile=tokenizer_profile,
        document_frequency=document_frequency,
        document_count=document_count,
        index_fingerprint=index_fingerprint,
        graph_revision_fingerprint=graph_revision_fingerprint,
        effective_graph_view=effective_graph_view,
        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        candidates_by_hash=evidence_candidates_by_hash,
        relation_projection=relation_projection,
        execution_deadline=execution_deadline,
    )
    if selection is None:
        return None
    if plan.seed_node_ids:
        candidate_anchor_node_ids = plan.seed_node_ids
    elif relation_projection is not None:
        candidate_anchor_node_ids = (
            relation_projection.initial_query_anchor_node_ids
            or relation_projection.completion_query_anchor_node_ids
        )
    else:
        candidate_anchor_node_ids = ()
    if relation_projection is not None:
        anchors_are_authorized = all(
            (projected_node := relation_projection.node_by_id.get(node_id)) is not None
            and projected_node.authorized_evidence_hashes is not None
            for node_id in candidate_anchor_node_ids
        )
    else:
        visible_nodes_by_id = {node.node_id: node for node in effective_graph_view.visible_nodes}
        anchors_are_authorized = all(
            node_id in visible_nodes_by_id
            and _authorized_property_evidence_hashes(
                visible_nodes_by_id[node_id].properties,
                authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            )
            is not None
            for node_id in candidate_anchor_node_ids
        )
    completion_anchor_node_ids = (
        tuple(candidate_anchor_node_ids)
        if candidate_anchor_node_ids and anchors_are_authorized
        else ()
    )
    required_anchor_node_hashes = frozenset(
        sha256_json(node_id) for node_id in completion_anchor_node_ids
    )
    citations = _connected_relation_fallback_citations(
        graph_paths=graph_paths,
        selection=selection,
        candidates_by_hash=evidence_candidates_by_hash,
        visible_nodes=effective_graph_view.visible_nodes,
        authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        evidence_budget=plan.evidence_budget,
        relation_projection=relation_projection,
        required_anchor_node_hashes=required_anchor_node_hashes,
        execution_deadline=execution_deadline,
    )
    _query_deadline_checkpoint(execution_deadline)
    repaired_plan = repair_relation_plan_once(
        plan,
        seed_node_ids=plan.seed_node_ids,
        required_identifier_term_hashes=selection.identifier_term_hashes,
        required_concept_term_hashes=selection.concept_term_hashes,
        policy_fingerprint=_RELATION_FALLBACK_POLICY_FINGERPRINT,
        vocabulary_fingerprint=selection.vocabulary_fingerprint,
    )
    repaired_plan = validate_semantic_query_plan(
        repaired_plan,
        effective_graph_view=effective_graph_view,
        authorized_workspace_id=authorized_workspace_id,
        authorized_source_scope_ids=authorized_source_scope_ids,
        supported_relation_types=supported_relation_types,
        limits=limits,
        allow_bounded_repair=False,
        authorized_source=authorized_source,
    )
    repaired_paths = tuple(graph_paths)
    rejected_hop_count = 0
    targeted_retraversal_used = False
    if not citations and completion_anchor_node_ids:
        targeted_retraversal_used = True
        traversal_plan = replace(
            repaired_plan,
            seed_node_ids=completion_anchor_node_ids,
        )
        traversal_plan = validate_semantic_query_plan(
            traversal_plan,
            effective_graph_view=effective_graph_view,
            authorized_workspace_id=authorized_workspace_id,
            authorized_source_scope_ids=authorized_source_scope_ids,
            supported_relation_types=supported_relation_types,
            limits=limits,
            allow_bounded_repair=False,
            authorized_source=authorized_source,
        )
        repaired_paths, rejected_hop_count = _bounded_graph_traversal(
            plan=traversal_plan,
            query_text=query_text,
            effective_graph_view=effective_graph_view,
            tokenizer_profile=tokenizer_profile,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            evidence_candidates_by_hash=evidence_candidates_by_hash,
            relation_proof_slots=selection.proof_slots,
            relation_projection=relation_projection,
            graph_snapshot=graph_snapshot,
            execution_deadline=execution_deadline,
        )
        citations = _connected_relation_fallback_citations(
            graph_paths=repaired_paths,
            selection=selection,
            candidates_by_hash=evidence_candidates_by_hash,
            visible_nodes=effective_graph_view.visible_nodes,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
            evidence_budget=repaired_plan.evidence_budget,
            relation_projection=relation_projection,
            required_anchor_node_hashes=required_anchor_node_hashes,
            execution_deadline=execution_deadline,
        )
        _query_deadline_checkpoint(execution_deadline)
    _query_deadline_checkpoint(execution_deadline)
    return _RelationFallbackOutcome(
        plan=repaired_plan,
        graph_paths=repaired_paths,
        answer_citation_hashes=citations,
        rejected_hop_count=rejected_hop_count,
        targeted_retraversal_used=targeted_retraversal_used,
    )


def _path_node_hashes(path: BoundedGraphPath) -> frozenset[str]:
    return frozenset(
        node_hash for hop in path.hops for node_hash in (hop.source_node_hash, hop.target_node_hash)
    )


def _candidate_slot_coverage(
    candidate: _HybridCandidate,
    *,
    slots: _EvidenceQuerySlots,
) -> frozenset[tuple[str, str]]:
    return frozenset(
        ("identifier", token)
        for token in (candidate.observation_protected_identifier_tokens & slots.identifier_tokens)
    ) | frozenset(("topic", token) for token in candidate.observation_tokens & slots.topic_tokens)


def _relation_path_slot_coverage(
    path: BoundedGraphPath,
    *,
    slots: _EvidenceQuerySlots,
    candidates_by_hash: Mapping[str, _HybridCandidate],
) -> frozenset[tuple[str, str]]:
    return frozenset().union(
        *(
            _candidate_slot_coverage(
                candidates_by_hash[observation_hash],
                slots=slots,
            )
            for observation_hash in path.cited_observation_hashes
            if observation_hash in candidates_by_hash
        )
    )


def _relation_projection_path_slot_coverage(
    path: BoundedGraphPath,
    *,
    required_identifier_hashes: frozenset[str],
    required_concept_hashes: frozenset[str],
    relation_projection: _RelationQueryProjection,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[frozenset[tuple[str, str]], frozenset[str]]:
    coverage: set[tuple[str, str]] = set()
    supporting_observation_hashes: set[str] = set()
    for node_hash in _path_node_hashes(path):
        _query_deadline_checkpoint(execution_deadline)
        projected_node = relation_projection.node_by_hash.get(node_hash)
        if projected_node is None:
            continue
        for (
            observation_hash,
            supported_identifier_hashes,
            supported_concept_hashes,
        ) in projected_node.lineage_support_by_observation_hash:
            _query_deadline_checkpoint(execution_deadline)
            selected_coverage = {
                ("identifier", term_hash)
                for term_hash in (required_identifier_hashes & supported_identifier_hashes)
            } | {
                ("concept", term_hash)
                for term_hash in (required_concept_hashes & supported_concept_hashes)
            }
            if selected_coverage:
                coverage.update(selected_coverage)
                supporting_observation_hashes.add(observation_hash)
    return frozenset(coverage), frozenset(supporting_observation_hashes)


def _rank_relation_graph_paths(
    graph_paths: Sequence[BoundedGraphPath],
    *,
    query_text: str,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    evidence_candidates_by_hash: Mapping[str, _HybridCandidate],
    result_limit: int,
    slots_override: _EvidenceQuerySlots | None = None,
    relation_projection: _RelationQueryProjection | None = None,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[BoundedGraphPath, ...]:
    """Keep bounded graph output focused on query-verifiable relation slots."""

    _query_deadline_checkpoint(execution_deadline)
    slots = slots_override or _deterministic_required_relation_slots(
        query_text,
        tokenizer_profile=tokenizer_profile,
        candidates_by_hash=evidence_candidates_by_hash,
    )
    if slots is None:
        return tuple(
            sorted(
                graph_paths,
                key=lambda path: (
                    len(path.cited_observation_hashes),
                    path.hop_count,
                    -path.graph_path_score,
                    path.path_hash,
                ),
            )[:result_limit]
        )
    use_projected_node_support = slots_override is not None and relation_projection is not None
    if use_projected_node_support:
        required_identifier_hashes = frozenset(
            _source_graph_term_hashes(tuple(slots.identifier_tokens))
        )
        required_concept_hashes = frozenset(_source_graph_term_hashes(tuple(slots.topic_tokens)))
        required = frozenset(
            ("identifier", term_hash) for term_hash in required_identifier_hashes
        ) | frozenset(("concept", term_hash) for term_hash in required_concept_hashes)
    else:
        required_identifier_hashes = frozenset()
        required_concept_hashes = frozenset()
        required = frozenset(
            ("identifier", token) for token in slots.identifier_tokens
        ) | frozenset(("topic", token) for token in slots.topic_tokens)

    def ranking_key(path: BoundedGraphPath) -> tuple[Any, ...]:
        if use_projected_node_support:
            assert relation_projection is not None
            coverage, supporting_observation_hashes = _relation_projection_path_slot_coverage(
                path,
                required_identifier_hashes=required_identifier_hashes,
                required_concept_hashes=required_concept_hashes,
                relation_projection=relation_projection,
                execution_deadline=execution_deadline,
            )
            supporting_evidence_count = len(supporting_observation_hashes)
        else:
            coverage = _relation_path_slot_coverage(
                path,
                slots=slots,
                candidates_by_hash=evidence_candidates_by_hash,
            )
            supporting_evidence_count = sum(
                bool(
                    _candidate_slot_coverage(
                        evidence_candidates_by_hash[observation_hash],
                        slots=slots,
                    )
                )
                for observation_hash in path.cited_observation_hashes
                if observation_hash in evidence_candidates_by_hash
            )
        unrelated_evidence_count = len(path.cited_observation_hashes) - supporting_evidence_count
        return (
            coverage != required,
            -len(coverage),
            unrelated_evidence_count,
            len(path.cited_observation_hashes),
            path.hop_count,
            -path.graph_path_score,
            path.path_hash,
        )

    ranked_paths: list[tuple[tuple[Any, ...], BoundedGraphPath]] = []
    for path in graph_paths:
        _query_deadline_checkpoint(execution_deadline)
        ranked_paths.append((ranking_key(path), path))
    _query_deadline_checkpoint(execution_deadline)
    return tuple(
        path
        for _, path in sorted(
            ranked_paths,
            key=lambda item: item[0],
        )[:result_limit]
    )


def _minimal_relation_proof_citations(
    *,
    query_text: str,
    graph_paths: Sequence[BoundedGraphPath],
    candidates_by_hash: Mapping[str, _HybridCandidate],
    scores_by_observation_hash: Mapping[str, SemanticEvidenceScore],
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    evidence_budget: int,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> tuple[str, ...]:
    """Select the smallest connected Observation proof for all relation slots."""

    _query_deadline_checkpoint(execution_deadline)
    if not graph_paths:
        return ()
    slots = _deterministic_required_relation_slots(
        query_text,
        tokenizer_profile=tokenizer_profile,
        candidates_by_hash=candidates_by_hash,
    )
    if slots is None:
        return ()
    paths_by_anchor: dict[str, list[BoundedGraphPath]] = {}
    for path in graph_paths:
        _query_deadline_checkpoint(execution_deadline)
        for node_hash in _path_node_hashes(path):
            _query_deadline_checkpoint(execution_deadline)
            paths_by_anchor.setdefault(node_hash, []).append(path)

    proofs: list[tuple[tuple[str, ...], int, float, str]] = []
    for anchor_hash, anchored_paths in sorted(paths_by_anchor.items()):
        _query_deadline_checkpoint(execution_deadline)
        evidence_hashes = tuple(
            dict.fromkeys(
                observation_hash
                for path in sorted(anchored_paths, key=lambda item: item.path_hash)
                for observation_hash in path.cited_observation_hashes
                if observation_hash in candidates_by_hash
            )
        )
        ranked_candidates = [
            (
                candidates_by_hash[observation_hash],
                (
                    scores_by_observation_hash[observation_hash].total_score
                    if observation_hash in scores_by_observation_hash
                    else 0.0
                ),
            )
            for observation_hash in evidence_hashes
        ]
        citations = _minimal_candidate_proof_citations(
            ranked_candidates,
            slots=slots,
            evidence_budget=evidence_budget,
            execution_deadline=execution_deadline,
        )
        if not citations:
            continue
        supporting_path_count = sum(
            bool(set(path.cited_observation_hashes) & set(citations)) for path in anchored_paths
        )
        proofs.append(
            (
                citations,
                supporting_path_count,
                sum(
                    scores_by_observation_hash[observation_hash].total_score
                    if observation_hash in scores_by_observation_hash
                    else 0.0
                    for observation_hash in citations
                ),
                anchor_hash,
            )
        )
    if not proofs:
        return ()
    citations, _, _, _ = min(
        proofs,
        key=lambda item: (
            len(item[0]),
            item[1],
            -item[2],
            item[3],
            item[0],
        ),
    )
    _query_deadline_checkpoint(execution_deadline)
    return citations


def _result_lineage_audit(
    *,
    crosswalk: EvidenceIdentityLineageCrosswalk,
    semantic_scores: Sequence[SemanticEvidenceScore],
    graph_paths: Sequence[BoundedGraphPath],
    final_citation_hashes: Sequence[str],
    exact_result: DeterministicExactExecutionResult | None,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> EvidenceIdentityLineageAudit:
    _query_deadline_checkpoint(execution_deadline)
    score_hashes = {score.source_observation_hash for score in semantic_scores}
    graph_path_hashes = {
        evidence_hash for path in graph_paths for evidence_hash in path.cited_observation_hashes
    }
    exact_item_hashes = (
        {
            evidence_hash
            for item in exact_result.items
            for evidence_hash in item.cited_observation_hashes
        }
        if exact_result is not None
        else set()
    )
    final_hashes = set(final_citation_hashes)
    traced_hashes = score_hashes | graph_path_hashes | exact_item_hashes | final_hashes
    known_hashes = {entry.source_observation_hash for entry in crosswalk.entries}
    unresolved_hashes = traced_hashes - known_hashes
    payload = {
        "crosswalk_fingerprint": crosswalk.crosswalk_fingerprint,
        "traced_evidence_hashes": sorted(traced_hashes),
        "graph_path_evidence_hashes": sorted(graph_path_hashes),
        "final_citation_hashes": sorted(final_hashes),
        "exact_item_evidence_hashes": sorted(exact_item_hashes),
        "unresolved_evidence_hashes": sorted(unresolved_hashes),
    }
    result = EvidenceIdentityLineageAudit(
        crosswalk_fingerprint=crosswalk.crosswalk_fingerprint,
        traced_evidence_hashes=tuple(payload["traced_evidence_hashes"]),
        graph_path_evidence_hashes=tuple(payload["graph_path_evidence_hashes"]),
        final_citation_hashes=tuple(payload["final_citation_hashes"]),
        exact_item_evidence_hashes=tuple(payload["exact_item_evidence_hashes"]),
        unresolved_evidence_hashes=tuple(payload["unresolved_evidence_hashes"]),
        audit_fingerprint=sha256_json(payload),
    )
    result.to_safe_dict()
    _query_deadline_checkpoint(execution_deadline)
    return result


def _graph_nodes_by_observation_hash(
    *,
    effective_graph_view: EffectiveGraphView,
    authorized_observation_hash_by_id: Mapping[str, str],
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> dict[str, tuple[GraphProjectionNode, ...]]:
    nodes_by_hash: dict[str, list[GraphProjectionNode]] = {}
    for node in effective_graph_view.visible_nodes:
        _query_deadline_checkpoint(execution_deadline)
        evidence_hashes = _authorized_property_evidence_hashes(
            node.properties,
            authorized_observation_hash_by_id=authorized_observation_hash_by_id,
        )
        if evidence_hashes is None:
            continue
        for evidence_hash in evidence_hashes:
            _query_deadline_checkpoint(execution_deadline)
            nodes_by_hash.setdefault(evidence_hash, []).append(node)
    _query_deadline_checkpoint(execution_deadline)
    return {
        evidence_hash: tuple(sorted(nodes, key=lambda item: item.node_id))
        for evidence_hash, nodes in nodes_by_hash.items()
    }


def _temporal_current_score(nodes: Sequence[GraphProjectionNode]) -> float:
    if not nodes:
        return 0.5
    scores: list[float] = []
    for node in nodes:
        temporal_state = str(node.properties.get("temporal_state", "")).casefold()
        if temporal_state in {"active", "current", "effective", "valid"}:
            scores.append(1.0)
        elif temporal_state in {"expired", "stale", "superseded", "withdrawn"}:
            scores.append(0.0)
        else:
            scores.append(0.5)
    return max(scores)


def _capped_ontology_bonus(
    nodes: Sequence[GraphProjectionNode],
    *,
    target_core_supertype_id: str | None,
) -> float:
    if target_core_supertype_id is None:
        return 0.0
    bonuses: list[float] = []
    for node in _ontology_subject_nodes(nodes):
        core_supertype_id = node.properties.get("core_supertype_id")
        confidence = node.properties.get("type_confidence", 0.0)
        if (
            not isinstance(core_supertype_id, str)
            or not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
        ):
            continue
        decision = soft_core_supertypes_compatible(
            target_core_supertype_id,
            core_supertype_id,
            left_type_confidence=1.0,
            right_type_confidence=float(confidence),
            maximum_additive_score_adjustment=0.2,
        )
        if decision.hard_reject:
            raise ContractValidationError("soft ontology scoring cannot hard reject")
        bonuses.append(
            min(
                decision.additive_score_adjustment,
                decision.maximum_additive_score_adjustment,
                0.2,
            )
        )
    return max(bonuses, default=0.0)


def _graph_entity_score(
    nodes: Sequence[GraphProjectionNode],
    *,
    query_tokens: set[str],
    protected_query_tokens: set[str],
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    relation_projection: _RelationQueryProjection | None = None,
) -> float:
    if not nodes or not query_tokens:
        return 0.0
    entity_nodes = [
        node
        for node in nodes
        if node.properties.get("node_kind")
        in {
            "candidate_entity",
            "candidate_source_term",
        }
    ]
    selected_nodes = entity_nodes or list(nodes)
    node_tokens: set[str] = set()
    node_protected: set[str] = set()
    node_term_hashes: set[str] = set()
    node_protected_hashes: set[str] = set()
    for node in selected_nodes:
        projected_node = (
            relation_projection.node_by_id.get(node.node_id)
            if relation_projection is not None
            else None
        )
        if projected_node is not None:
            node_tokens.update(projected_node.searchable_tokens)
            node_protected.update(projected_node.searchable_protected_tokens)
            node_term_hashes.update(projected_node.source_term_hashes)
            node_protected_hashes.update(projected_node.protected_term_hashes)
        else:
            analysis = tokenizer_profile.analyze(" ".join(_node_searchable_values(node)))
            node_tokens.update(analysis.tokens)
            node_protected.update(span.exact_token for span in analysis.protected_identifiers)
            node_term_hashes.update(_node_source_term_hashes(node))
            node_protected_hashes.update(_node_protected_term_hashes(node))
    if protected_query_tokens:
        protected_overlap = max(
            len(protected_query_tokens & node_protected),
            len(
                set(_source_graph_term_hashes(tuple(protected_query_tokens)))
                & node_protected_hashes
            ),
        )
        return protected_overlap / len(protected_query_tokens)
    query_overlap = max(
        len(query_tokens & node_tokens),
        len(set(_source_graph_term_hashes(tuple(query_tokens))) & node_term_hashes),
    )
    return query_overlap / len(query_tokens)


def _query_evidence_slots(
    query_text: str,
    *,
    query_class: str,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
) -> _EvidenceQuerySlots:
    query_analysis = tokenizer_profile.analyze(query_text)
    protected_tokens = frozenset(span.exact_token for span in query_analysis.protected_identifiers)
    operator_phrases = list(_GENERAL_QUERY_OPERATOR_PHRASES)
    if query_class == "exact_set_or_inventory":
        operator_phrases.extend(_EXACT_QUERY_OPERATOR_PHRASES)
    elif query_class == "relation_reasoning":
        operator_phrases.extend(_RELATION_QUERY_OPERATOR_PHRASES)
    elif query_class == "global_summarization":
        operator_phrases.extend(
            (
                "summarize",
                "summary",
                "overview",
                "總結",
                "摘要",
                "概況",
            )
        )
    content_text = query_text
    for phrase in sorted(set(operator_phrases), key=lambda value: (-len(value), value)):
        if phrase.isascii():
            content_text = re.sub(
                rf"\b{re.escape(phrase)}\b",
                " ",
                content_text,
                flags=re.IGNORECASE,
            )
        else:
            content_text = content_text.replace(phrase, " ")
    topic_tokens = frozenset(tokenizer_profile.analyze(content_text).tokens) - protected_tokens
    return _EvidenceQuerySlots(
        identifier_tokens=protected_tokens,
        topic_tokens=topic_tokens,
    )


def _deterministic_high_idf_proof_slots(
    query_text: str,
    *,
    query_class: str,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    document_frequency: Mapping[str, int],
    document_count: int,
) -> _EvidenceQuerySlots | None:
    """Require exact identifiers plus bounded indexed query concepts."""

    slots = _query_evidence_slots(
        query_text,
        query_class=query_class,
        tokenizer_profile=tokenizer_profile,
    )
    if not slots.topic_tokens:
        return slots
    indexed_topics = [
        token
        for token in slots.topic_tokens
        if 0 < document_frequency.get(token, 0) <= document_count
    ]
    if not indexed_topics:
        return None

    def topic_order(token: str) -> tuple[float, str]:
        frequency = document_frequency[token]
        inverse_document_frequency = math.log(
            1.0 + ((document_count - frequency + 0.5) / (frequency + 0.5))
        )
        return (-inverse_document_frequency, sha256_json(token))

    ordered_topics = tuple(sorted(indexed_topics, key=topic_order))
    return _EvidenceQuerySlots(
        identifier_tokens=slots.identifier_tokens,
        topic_tokens=frozenset(ordered_topics[:_MAX_DETERMINISTIC_PROOF_TOPIC_SLOTS]),
    )


def _deterministic_exact_filter_slots(
    query_text: str,
    *,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    exact_inventory_kind: str | None = None,
    exact_field: str | None = None,
) -> _ExactFilterSlots:
    typed_participant_query = (
        exact_inventory_kind == "mail_observation"
        and exact_field in _PARTICIPANT_LOCAL_PART_FIELDS
    )
    participant_slots, remaining_query_text = _typed_participant_identifier_slots(
        query_text,
        tokenizer_profile=tokenizer_profile,
        exact_inventory_kind=exact_inventory_kind,
        exact_field=exact_field,
    )
    if typed_participant_query:
        slots = _query_evidence_slots(
            remaining_query_text,
            query_class="exact_set_or_inventory",
            tokenizer_profile=tokenizer_profile,
        )
        if not participant_slots:
            raise ContractValidationError(
                "typed participant identifier slot is unavailable"
            )
        return _ExactFilterSlots(
            identifier_hashes=_source_graph_term_hashes(participant_slots),
            topic_hashes=_source_graph_term_hashes(
                (*slots.identifier_tokens, *slots.topic_tokens)
            ),
        )
    slots = _query_evidence_slots(
        remaining_query_text,
        query_class="exact_set_or_inventory",
        tokenizer_profile=tokenizer_profile,
    )
    return _ExactFilterSlots(
        identifier_hashes=_source_graph_term_hashes(
            (*participant_slots, *slots.identifier_tokens)
        ),
        topic_hashes=_source_graph_term_hashes(tuple(slots.topic_tokens)),
    )


def _ordered_source_occurrence_query_grounding(
    query_text: str,
    *,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
) -> tuple[tuple[tuple[str, str, tuple[str, ...], str], ...], str]:
    analysis = tokenizer_profile.analyze_query_grounding(query_text)
    terms = analysis.terms
    output_verbs, completion_markers, inventory_markers = _CJK_EXACT_OUTPUT_GRAMMAR_V1
    exact_output_enabled = (
        any(surface in query_text for surface in output_verbs)
        and any(surface in query_text for surface in (*completion_markers, *inventory_markers))
    )
    control_spans = []
    for role, control_kind, surfaces, enabled in (
        ("verb", "exact_output", (*output_verbs, *completion_markers), exact_output_enabled),
        ("operator", "exact_output", inventory_markers, exact_output_enabled),
        ("conjunction", "projection_connector", _SOURCE_OCCURRENCE_PROJECTION_CONNECTORS, True),
    ):
        if not enabled:
            continue
        for surface in surfaces:
            start = query_text.find(surface)
            while start >= 0:
                end = start + len(surface)
                term_indexes = tuple(index for index, term in enumerate(terms)
                                     if start <= term.start and term.end <= end)
                if (
                    term_indexes
                    and terms[term_indexes[0]].start == start
                    and terms[term_indexes[-1]].end == end
                    and all(
                        terms[left].end == terms[right].start
                        for left, right in zip(term_indexes, term_indexes[1:])
                    )
                ):
                    control_spans.append(
                        (start, end, term_indexes[0], term_indexes[-1], role, control_kind))
                start = query_text.find(surface, end)
    control_spans.sort()
    if any(current[0] < previous[1]
           for previous, current in zip(control_spans, control_spans[1:])):
        raise ContractValidationError("source occurrence query control span is invalid")
    exact_controls = {
        term_index: (role, control_kind)
        for _start, _end, first, last, role, control_kind in control_spans
        if control_kind == "exact_output"
        for term_index in range(first, last + 1)
    }
    connectors = {
        first: (start, end, last)
        for start, end, first, last, _role, control_kind in control_spans
        if control_kind == "projection_connector"
    }
    controlled_term_indexes = {
        term_index
        for _start, _end, first, last, _role, _kind in control_spans
        for term_index in range(first, last + 1)
    }
    ordered_terms: list[tuple[str, str, tuple[str, ...], str]] = []
    term_index = 0
    while term_index < len(terms):
        connector = connectors.get(term_index)
        if connector is not None:
            start, end, last = connector
            constituent_hashes = tuple(sha256_json([
                "ordered_query_grounding_term_v1", term.start, term.end,
                term.normalized_term, term.grammar_role, "projection_connector",
            ]) for term in terms[term_index : last + 1])
            ordered_terms.append(
                (
                    sha256_json(["ordered_query_grounding_control_v1", start, end,
                                 "projection_connector", constituent_hashes]),
                    "conjunction", (), "projection_connector",
                )
            )
            term_index = last + 1
            continue
        term = terms[term_index]
        grammar_role, control_kind = exact_controls.get(term_index, (term.grammar_role, "none"))
        if (
            control_kind == "none"
            and term.normalized_term in _SOURCE_OCCURRENCE_SENTENCE_FINAL_PARTICLES
            and all(
                character.isspace()
                or unicodedata.category(character).startswith("P")
                for character in query_text[term.end :]
            )
        ):
            grammar_role = "particle"
        run_last = term_index
        normalized_surface = term.normalized_term
        occurrence_kind = "ordered_query_grounding_term_v1"
        candidate_tokens = (
            set(tokenizer_profile.analyze(term.normalized_term).tokens)
            if control_kind == "none"
            else set()
        )
        if (
            control_kind == "none"
            and grammar_role == "lexical"
            and term_index + 1 < len(terms)
            and term_index + 1 not in controlled_term_indexes
            and terms[term_index + 1].grammar_role == "particle"
            and term.end == terms[term_index + 1].start
            and any(
                earlier.grammar_role == "particle"
                for earlier in terms[:term_index]
            )
            and not (
                terms[term_index + 1].normalized_term
                in _SOURCE_OCCURRENCE_SENTENCE_FINAL_PARTICLES
                and all(
                    character.isspace()
                    or unicodedata.category(character).startswith("P")
                    for character in query_text[terms[term_index + 1].end :]
                )
            )
        ):
            phrase_end = terms[term_index + 1].end
            span = query_text[term.start : phrase_end]
            phrase_surface = tokenizer_profile.normalize_exact_identifier_surface(span)
            if (
                phrase_surface
                and phrase_surface in tokenizer_profile.analyze(span).tokens
            ):
                run_last = term_index + 1
                normalized_surface = phrase_surface
                occurrence_kind = "ordered_query_grounding_contiguous_phrase_v1"
                candidate_tokens = {phrase_surface}
        if (
            run_last == term_index
            and control_kind == "none"
            and grammar_role == "lexical"
            and not candidate_tokens
        ):
            occurrence_kind = "ordered_query_grounding_phrase_v1"
            while (
                run_last + 1 < len(terms)
                and run_last + 1 not in controlled_term_indexes
                and terms[run_last + 1].grammar_role == "lexical"
                and terms[run_last].end == terms[run_last + 1].start
                and not tokenizer_profile.analyze(
                    terms[run_last + 1].normalized_term
                ).tokens
            ):
                run_last += 1
            span = query_text[term.start : terms[run_last].end]
            normalized_surface = tokenizer_profile.normalize_exact_identifier_surface(span)
            candidate_tokens = {normalized_surface} if normalized_surface else set()
        occurrence_hash = sha256_json([
            occurrence_kind, term.start, terms[run_last].end,
            normalized_surface, grammar_role, control_kind,
        ])
        ordered_candidates = tuple(sha256_json(token) for token in sorted(
            candidate_tokens,
            key=lambda token: (token != term.normalized_term, -len(token), token),
        ))
        ordered_terms.append((occurrence_hash, grammar_role, ordered_candidates, control_kind))
        term_index = run_last + 1
    grammar_policy_fingerprint = sha256_json(
        [
            "source_occurrence_query_grammar_policy_v7",
            analysis.grammar_policy_fingerprint,
            _CJK_EXACT_OUTPUT_GRAMMAR_V1,
            _SOURCE_OCCURRENCE_PROJECTION_CONNECTOR_POLICY_ID,
            _SOURCE_OCCURRENCE_PROJECTION_CONNECTORS,
            _SOURCE_OCCURRENCE_PROJECTION_CONNECTOR_BOUNDARY_RULE,
            _SOURCE_OCCURRENCE_SENTENCE_FINAL_PARTICLE_POLICY_ID,
            _SOURCE_OCCURRENCE_SENTENCE_FINAL_PARTICLES,
            _SOURCE_OCCURRENCE_CONTIGUOUS_PHRASE_POLICY_ID,
            _SOURCE_OCCURRENCE_CONTIGUOUS_PHRASE_BOUNDARY_RULE,
        ]
    )
    return tuple(ordered_terms), grammar_policy_fingerprint


def _partition_source_occurrence_query_grounding(
    *,
    provider: SourceOccurrenceProvider,
    ordered_terms: Sequence[tuple[str, str, Sequence[str], str]],
) -> tuple[SourceOccurrenceQueryPartition, tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Ground all ordered terms through one source-backed table provider."""

    if provider.filter_slot_policy != "combined_present_intersection_v1" or not ordered_terms:
        raise ContractValidationError("source occurrence query value binding is incomplete")
    lexical_ledger: list[tuple[str, str, str, str]] = []
    grammar_ledger: list[tuple[str, str]] = []
    rejected_term_hashes: list[str] = []
    rejected_term_indexes: list[int] = []
    column_value_pairs: set[tuple[str, str]] = set()
    projection_columns: set[str] = set()
    unsupported_projection_hashes: set[str] = set()
    seen_term_hashes: set[str] = set()
    resolved_term_hashes: set[str] = set()
    grounded_terms = []
    for term_hash, grammar_role, raw_candidates, control_kind in ordered_terms:
        if control_kind not in {"none", "exact_output", "projection_connector"}:
            raise ContractValidationError("source occurrence query grounding ledger is invalid")
        candidates = tuple(raw_candidates)
        if term_hash in seen_term_hashes:
            raise ContractValidationError("source occurrence query grounding ledger is invalid")
        seen_term_hashes.add(term_hash)
        value_binding = projection_binding = None
        if control_kind == "none" and grammar_role in {"lexical", "operator"}:
            value_binding = next((
                (candidate_hash, columns) for candidate_hash in candidates
                if (columns := provider._value_candidate_columns.get(
                    candidate_hash, frozenset()))
            ), None)
            projection_binding = next((
                (candidate_hash, columns) for candidate_hash in candidates
                if (columns := provider._projection_candidate_columns.get(
                    candidate_hash, frozenset()))
            ), None)
        grounded_terms.append(
            (term_hash, grammar_role, control_kind, value_binding, projection_binding))

    particle_indices = tuple(
        index for index, (_, role, control, _, _) in enumerate(grounded_terms)
        if control == "none" and role == "particle")
    directional_particle: int | None = None
    viable_particles = []
    for particle_index in particle_indices:
        left = grounded_terms[:particle_index]
        right = grounded_terms[particle_index + 1 :]
        if (
            any(value and not projection for _, _, _, value, projection in left)
            and any(
                (projection and not value)
                or (
                    control == "none" and role in {"lexical", "operator"}
                    and ordered_terms[index][2]
                )
                for index, (_, role, control, value, projection) in enumerate(
                    grounded_terms[particle_index + 1 :], particle_index + 1,
                )
            )
            and not any(
                projection and not value for _, _, _, value, projection in left
            )
            and not any(
                value and not projection for _, _, _, value, projection in right
            )
        ):
            viable_particles.append(particle_index)
    if particle_indices:
        if len(viable_particles) != 1:
            raise ContractValidationError("source occurrence query candidate binding is invalid")
        directional_particle = viable_particles[0]
        last_grounded_index = max(
            index
            for index, (_, _, _, value, projection) in enumerate(grounded_terms)
            if value or projection
        )
        terminal_particles = {
            index
            for index in particle_indices
            if index != directional_particle
            and index > last_grounded_index
            and not grounded_terms[index][3]
            and not grounded_terms[index][4]
        }
        if any(
            index != directional_particle and index not in terminal_particles
            for index in particle_indices
        ):
            raise ContractValidationError("source occurrence query candidate binding is invalid")
    else:
        terminal_particles = set()

    resolved_bindings = []
    for index, (_, _, _, value_binding, projection_binding) in enumerate(grounded_terms):
        if value_binding and projection_binding:
            if directional_particle is None:
                raise ContractValidationError("source occurrence query lexical binding is ambiguous")
            resolved_bindings.append(
                ("filter_value", value_binding)
                if index < directional_particle
                else ("projection_field", projection_binding)
            )
        elif value_binding or projection_binding:
            is_filter = value_binding is not None
            if directional_particle is not None and (
                (is_filter and index > directional_particle)
                or (not is_filter and index < directional_particle)
            ):
                raise ContractValidationError("source occurrence query candidate binding is invalid")
            resolved_bindings.append(
                (
                    "filter_value" if is_filter else "projection_field",
                    value_binding if is_filter else projection_binding,
                )
            )
        else:
            resolved_bindings.append(None)

    connector_indexes = tuple(
        index
        for index, (_, _, control_kind, _, _) in enumerate(grounded_terms)
        if control_kind == "projection_connector"
    )
    if connector_indexes and (
        directional_particle is None
        or any(index <= directional_particle for index in connector_indexes)
    ):
        raise ContractValidationError(
            "source occurrence query connector binding is invalid"
        )
    if directional_particle is not None:
        projection_segments: list[list[int]] = [[]]
        connector_seen = False
        for index in range(directional_particle + 1, len(grounded_terms)):
            _, role, control_kind, _, _ = grounded_terms[index]
            if (
                control_kind == "projection_connector"
                or (
                    control_kind == "none"
                    and role == "conjunction"
                    and resolved_bindings[index] is None
                )
            ):
                if not projection_segments[-1]:
                    raise ContractValidationError(
                        "source occurrence query connector binding is invalid"
                    )
                connector_seen = True
                projection_segments.append([])
            elif (
                control_kind == "none"
                and role in {"lexical", "operator"}
                and ordered_terms[index][2]
            ):
                projection_segments[-1].append(index)
        if connector_seen and not projection_segments[-1]:
            raise ContractValidationError(
                "source occurrence query connector binding is invalid"
            )
        for segment in projection_segments:
            column_sets = {
                binding[1][1]
                for index in segment
                if (binding := resolved_bindings[index]) is not None
                and binding[0] == "projection_field"
            }
            unsupported = [
                index for index in segment if resolved_bindings[index] is None
            ]
            if unsupported and len(column_sets) > 1:
                raise ContractValidationError(
                    "source occurrence query projection binding is ambiguous"
                )
            if unsupported:
                for index in segment:
                    resolved_bindings[index] = (
                        "unsupported_projection",
                        (grounded_terms[index][0], frozenset()),
                    )

    for index, (term_hash, grammar_role, control_kind, _, _) in enumerate(grounded_terms):
        if index in terminal_particles:
            grammar_ledger.append((term_hash, grammar_role))
            resolved_term_hashes.add(term_hash)
            continue
        resolved_binding = resolved_bindings[index]
        if resolved_binding is not None:
            grounded_role, (grounded_hash, grounded_columns) = resolved_binding
        else:
            grounded_role = None
            grounded_hash = None
            grounded_columns = frozenset()
        if grounded_role is None:
            if control_kind == "projection_connector":
                grammar_ledger.append((term_hash, "conjunction"))
                resolved_term_hashes.add(term_hash)
            elif grammar_role == "lexical":
                rejected_term_hashes.append(term_hash)
                rejected_term_indexes.append(index)
            else:
                grammar_ledger.append((term_hash, grammar_role))
                resolved_term_hashes.add(term_hash)
            continue
        assert grounded_hash is not None
        resolved_term_hashes.add(term_hash)
        if grounded_role == "unsupported_projection":
            unsupported_projection_hashes.add(grounded_hash)
            continue
        if grounded_role == "filter_value":
            for grounded_column in sorted(grounded_columns):
                pair = (grounded_column, grounded_hash)
                if pair not in provider._column_value_postings:
                    raise ContractValidationError("source occurrence query value binding is incomplete")
                column_value_pairs.add(pair)
                lexical_ledger.append(
                    (term_hash, grounded_role, grounded_column, grounded_hash)
                )
        else:
            if len(grounded_columns) > DEFAULT_SEMANTIC_PLAN_LIMITS.max_candidates:
                raise ContractValidationError("source occurrence query projection binding exceeds limit")
            for grounded_column in sorted(grounded_columns):
                if grounded_column not in provider._column_postings:
                    raise ContractValidationError("source occurrence query projection binding is incomplete")
                projection_columns.add(grounded_column)
                lexical_ledger.append(
                    (
                        sha256_json(
                            [
                                "source_occurrence_projection_candidate_term_v1",
                                term_hash,
                                grounded_hash,
                                grounded_column,
                            ]
                        ),
                        grounded_role,
                        grounded_column,
                        grounded_hash,
                    )
                )
    if rejected_term_hashes:
        matching_filter_positions = (
            set.intersection(
                *(
                    set(provider._column_value_postings[pair])
                    for pair in column_value_pairs
                )
            )
            if column_value_pairs
            else set()
        )
        if (
            directional_particle is None
            or any(index >= directional_particle for index in rejected_term_indexes)
            or not any(
                provider._ordered_occurrences[position].structure_status
                == "source_provided"
                for position in matching_filter_positions
            )
        ):
            raise ContractValidationError(
                "source occurrence query candidate binding is incomplete"
            )
        unsupported_projection_hashes.update(rejected_term_hashes)
        resolved_term_hashes.update(rejected_term_hashes)
        unsupported_projection_hashes.update(
            grounded_terms[index][0]
            for index in range(directional_particle + 1, len(grounded_terms))
            if resolved_bindings[index] is not None
            and resolved_bindings[index][0] == "projection_field"
        )
        projection_columns.clear()
        lexical_ledger = [
            binding for binding in lexical_ledger
            if binding[1] != "projection_field"
        ]
    if not column_value_pairs:
        raise ContractValidationError("source occurrence query value binding is incomplete")
    if len(resolved_term_hashes) != len(ordered_terms):
        raise ContractValidationError("source occurrence query grounding ledger is invalid")
    return (
        SourceOccurrenceQueryPartition(
            filter_term_hashes=tuple(sorted(
                {value_hash for _column_hash, value_hash in column_value_pairs})),
            projection_column_hashes=tuple(sorted(projection_columns)),
            column_value_hash_pairs=tuple(sorted(column_value_pairs)),
            lexical_term_ledger=tuple(lexical_ledger),
        ),
        tuple(grammar_ledger),
        tuple(sorted(unsupported_projection_hashes)),
    )


def _mark_partial_projection_exact_result(
    result: DeterministicExactExecutionResult,
    *,
    unsupported_projection_hashes: tuple[str, ...],
    has_bound_projections: bool,
) -> DeterministicExactExecutionResult:
    reason_hash = sha256_json("source_occurrence_projection_capability_incomplete")
    items = result.items if has_bound_projections else ()
    reasons = tuple(sorted(set((*result.coverage.incompleteness_reason_hashes, reason_hash))))
    coverage = replace(
        result.coverage,
        authorized_scope_complete=False,
        global_scope_complete=False,
        eligible_record_count=(
            result.coverage.eligible_record_count if has_bound_projections else 0
        ),
        enumerated_record_count=(
            result.coverage.enumerated_record_count if has_bound_projections else 0
        ),
        cited_observation_count=(
            result.coverage.cited_observation_count if has_bound_projections else 0
        ),
        incompleteness_reason_hashes=reasons,
        coverage_fingerprint=sha256_json(
            [result.coverage.coverage_fingerprint, unsupported_projection_hashes]
        ),
    )
    page = dict(result.source_occurrence_page or {})
    page["coverage_status"] = "incomplete"
    page["unsupported_count"] = (
        int(page.get("unsupported_count", 0)) + len(unsupported_projection_hashes)
    )
    page["unsupported_projection_hashes"] = list(unsupported_projection_hashes)
    updated = replace(
        result,
        status="incomplete",
        exact_count=result.exact_count if has_bound_projections else 0,
        returned_item_count=len(items),
        cited_observation_count=(
            result.cited_observation_count if has_bound_projections else 0
        ),
        items=items,
        coverage=coverage,
        source_occurrence_page=page,
        result_fingerprint=sha256_json(
            [
                result.result_fingerprint,
                unsupported_projection_hashes,
                has_bound_projections,
            ]
        ),
    )
    updated.to_safe_dict()
    return updated


def _prefer_untyped_participant_any_provider(
    providers: Sequence[SourceOccurrenceProvider],
    *,
    identifier_hashes: Sequence[str],
) -> tuple[SourceOccurrenceProvider, ...]:
    resolved = tuple(providers)
    if len(resolved) < 2:
        return resolved
    if any(
        provider.filter_slot_policy != "identifier_union_v1"
        or provider.normalized_field not in _PARTICIPANT_LOCAL_PART_FIELDS
        for provider in resolved
    ):
        return resolved
    participant_any = tuple(
        provider
        for provider in resolved
        if provider.normalized_field == "participant.any.local_part"
    )
    if len(participant_any) != 1:
        return resolved
    query_hashes = set(identifier_hashes)
    any_provider = participant_any[0]
    any_matches = query_hashes.intersection(any_provider._value_hash_postings)
    role_matches = [
        query_hashes.intersection(provider._value_hash_postings)
        for provider in resolved
        if provider is not any_provider
    ]
    if (
        any_matches
        and role_matches
        and all(matches and matches.issubset(any_matches) for matches in role_matches)
    ):
        return (any_provider,)
    return resolved


def _typed_participant_identifier_slots(
    query_text: str,
    *,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    exact_inventory_kind: str | None,
    exact_field: str | None,
) -> tuple[tuple[str, ...], str]:
    if (
        exact_inventory_kind != "mail_observation"
        or exact_field not in _PARTICIPANT_LOCAL_PART_FIELDS
    ):
        return (), query_text

    occupied: list[tuple[int, int]] = []
    slots: list[str] = []
    for match in _PARTICIPANT_ADDR_SPEC_SLOT_RE.finditer(query_text):
        occupied.append(match.span())
        slots.append(
            tokenizer_profile.normalize_exact_identifier_surface(match.group(0))
        )
    for match in _PARTICIPANT_LOCAL_PART_SLOT_RE.finditer(query_text):
        start, end = match.span()
        if any(
            start < occupied_end and end > occupied_start
            for occupied_start, occupied_end in occupied
        ):
            continue
        surface = match.group(0)
        if "." not in surface and not _DISTINCTIVE_RFC_ATEXT.intersection(surface):
            continue
        occupied.append((start, end))
        slots.append(tokenizer_profile.normalize_exact_identifier_surface(surface))

    if not occupied:
        return (), query_text
    characters = list(query_text)
    for start, end in occupied:
        characters[start:end] = " " * (end - start)
    return tuple(slots), "".join(characters)


def _ontology_subject_nodes(
    nodes: Sequence[GraphProjectionNode],
) -> tuple[GraphProjectionNode, ...]:
    explicit = tuple(node for node in nodes if node.properties.get("ontology_subject") is True)
    return explicit or tuple(nodes)


def _legacy_ontology_hard_gate_accepts(
    nodes: Sequence[GraphProjectionNode],
    *,
    target_core_supertype_id: str,
) -> bool:
    typed_nodes = [
        node
        for node in _ontology_subject_nodes(nodes)
        if isinstance(node.properties.get("core_supertype_id"), str)
    ]
    if not typed_nodes:
        return True
    for node in typed_nodes:
        core_supertype_id = str(node.properties["core_supertype_id"])
        confidence = node.properties.get("type_confidence", 0.0)
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            continue
        decision = soft_core_supertypes_compatible(
            target_core_supertype_id,
            core_supertype_id,
            left_type_confidence=1.0,
            right_type_confidence=float(confidence),
            maximum_additive_score_adjustment=0.2,
        )
        if decision.compatible:
            return True
    return False


def _semantic_execution_result(
    *,
    status: str,
    plan: SemanticQueryPlan,
    index: AuthorizedHybridMailIndex,
    graph_revision_fingerprint: str,
    scores: tuple[SemanticEvidenceScore, ...],
    graph_paths: tuple[BoundedGraphPath, ...],
    answer_citation_hashes: tuple[str, ...],
    rejected_hop_count: int,
    exact_result: DeterministicExactExecutionResult | None,
    lineage_audit: EvidenceIdentityLineageAudit,
    warnings: tuple[str, ...],
) -> GovernedSemanticExecutionResult:
    exact_executor_status = exact_result.status if exact_result is not None else "not_requested"
    result_payload = {
        "status": status,
        "runtime_method_id": ISSUE56_TARGET_RUNTIME_METHOD_ID,
        "runtime_method_fingerprint": ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        "query_hash": plan.query_hash,
        "query_class": plan.query_class,
        "claim_strength": plan.claim_strength,
        "plan_fingerprint": plan.plan_fingerprint,
        "profile_fingerprint": index.profile_fingerprint,
        "index_fingerprint": index.index_fingerprint,
        "dense_profile_fingerprint": index.dense_profile_fingerprint,
        "dense_model_id": index.dense_model_id,
        "dense_model_revision": index.dense_model_revision,
        "execution_component_fingerprint": (index.execution_component_fingerprint),
        "graph_revision_fingerprint": graph_revision_fingerprint,
        "score_fingerprints": [sha256_json(score.to_safe_dict()) for score in scores],
        "path_fingerprints": [path.path_hash for path in graph_paths],
        "answer_citation_hashes": list(answer_citation_hashes),
        "exact_result_fingerprint": (
            exact_result.result_fingerprint if exact_result is not None else None
        ),
        "lineage_audit_fingerprint": lineage_audit.audit_fingerprint,
        "warnings": list(warnings),
    }
    if plan.relation_repair_policy_fingerprint is not None:
        result_payload["relation_repair"] = {
            "attempt_count": plan.repair_attempt_count,
            "policy_fingerprint": plan.relation_repair_policy_fingerprint,
            "vocabulary_fingerprint": (plan.relation_repair_vocabulary_fingerprint),
        }
    result = GovernedSemanticExecutionResult(
        artifact_id="formowl_issue56_governed_semantic_execution_result_v1",
        status=status,
        runtime_method_id=ISSUE56_TARGET_RUNTIME_METHOD_ID,
        runtime_method_fingerprint=ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        query_hash=plan.query_hash,
        query_class=plan.query_class,
        claim_strength=plan.claim_strength,
        plan_fingerprint=plan.plan_fingerprint,
        result_fingerprint=sha256_json(result_payload),
        profile_fingerprint=index.profile_fingerprint,
        index_fingerprint=index.index_fingerprint,
        graph_revision_fingerprint=graph_revision_fingerprint,
        dense_encoder_id=index.dense_encoder_id,
        dense_encoder_status=index.dense_encoder_status,
        dense_profile_fingerprint=index.dense_profile_fingerprint,
        dense_model_id=index.dense_model_id,
        dense_model_revision=index.dense_model_revision,
        execution_component_fingerprint=(index.execution_component_fingerprint),
        selected_bundle_count=index.selected_bundle_count,
        authorized_bundle_count=index.authorized_bundle_count,
        denied_bundle_count=index.denied_bundle_count,
        materialized_candidate_count=len(index.candidates),
        semantic_result_count=len(scores),
        graph_path_count=len(graph_paths),
        rejected_hop_count=rejected_hop_count,
        exact_executor_status=exact_executor_status,
        repair_attempt_count=plan.repair_attempt_count,
        relation_repair_policy_fingerprint=(plan.relation_repair_policy_fingerprint),
        relation_repair_vocabulary_fingerprint=(plan.relation_repair_vocabulary_fingerprint),
        scores=scores,
        graph_paths=graph_paths,
        answer_citation_hashes=answer_citation_hashes,
        exact_result=exact_result,
        lineage_audit=lineage_audit,
        warnings=warnings,
    )
    result.to_safe_dict()
    return result


def _time_budget_exhausted_semantic_result(
    *,
    query_text: str,
    query_class: str,
    plan: SemanticQueryPlan | None,
    index: AuthorizedHybridMailIndex,
    graph_revision_fingerprint: str,
) -> GovernedSemanticExecutionResult:
    """Return no partial proof when the one query-local deadline is exhausted."""

    query_hash = sha256_json(query_text)
    if plan is not None:
        if plan.query_hash != query_hash or plan.query_class != query_class:
            raise ContractValidationError("semantic timeout plan binding mismatch")
        plan_fingerprint = plan.plan_fingerprint
        repair_attempt_count = plan.repair_attempt_count
        repair_policy_fingerprint = plan.relation_repair_policy_fingerprint
        repair_vocabulary_fingerprint = plan.relation_repair_vocabulary_fingerprint
    else:
        plan_fingerprint = None
        repair_attempt_count = 0
        repair_policy_fingerprint = None
        repair_vocabulary_fingerprint = None
    result_payload = {
        "status": "no_answer",
        "runtime_method_id": ISSUE56_TARGET_RUNTIME_METHOD_ID,
        "runtime_method_fingerprint": ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        "query_hash": query_hash,
        "query_class": query_class,
        "plan_fingerprint": plan_fingerprint,
        "profile_fingerprint": index.profile_fingerprint,
        "index_fingerprint": index.index_fingerprint,
        "graph_revision_fingerprint": graph_revision_fingerprint,
        "execution_component_fingerprint": index.execution_component_fingerprint,
        "warning": _SEMANTIC_TIME_BUDGET_EXHAUSTED_WARNING,
    }
    result = GovernedSemanticExecutionResult(
        artifact_id="formowl_issue56_governed_semantic_execution_result_v1",
        status="no_answer",
        runtime_method_id=ISSUE56_TARGET_RUNTIME_METHOD_ID,
        runtime_method_fingerprint=ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        query_hash=query_hash,
        query_class=query_class,
        claim_strength="no_claim",
        plan_fingerprint=plan_fingerprint,
        result_fingerprint=sha256_json(result_payload),
        profile_fingerprint=index.profile_fingerprint,
        index_fingerprint=index.index_fingerprint,
        graph_revision_fingerprint=graph_revision_fingerprint,
        dense_encoder_id=index.dense_encoder_id,
        dense_encoder_status=index.dense_encoder_status,
        dense_profile_fingerprint=index.dense_profile_fingerprint,
        dense_model_id=index.dense_model_id,
        dense_model_revision=index.dense_model_revision,
        execution_component_fingerprint=index.execution_component_fingerprint,
        selected_bundle_count=index.selected_bundle_count,
        authorized_bundle_count=index.authorized_bundle_count,
        denied_bundle_count=index.denied_bundle_count,
        materialized_candidate_count=len(index.candidates),
        semantic_result_count=0,
        graph_path_count=0,
        rejected_hop_count=0,
        exact_executor_status="not_started",
        repair_attempt_count=repair_attempt_count,
        relation_repair_policy_fingerprint=repair_policy_fingerprint,
        relation_repair_vocabulary_fingerprint=repair_vocabulary_fingerprint,
        scores=(),
        graph_paths=(),
        answer_citation_hashes=(),
        exact_result=None,
        lineage_audit=None,
        warnings=(_SEMANTIC_TIME_BUDGET_EXHAUSTED_WARNING,),
    )
    result.to_safe_dict()
    return result


def _empty_semantic_execution_result(
    *,
    status: str,
    query_text: str,
    query_class: str,
    runtime_components: Issue56TargetRuntimeComponents,
    graph_revision_fingerprint: str,
    selected_bundle_count: int,
    authorized_bundle_count: int,
    denied_bundle_count: int,
    warning: str,
) -> GovernedSemanticExecutionResult:
    tokenizer_profile = runtime_components.tokenizer_profile
    dense_encoder = runtime_components.dense_encoder
    execution_binding = runtime_components.execution_binding
    result_payload = {
        "status": status,
        "runtime_method_id": ISSUE56_TARGET_RUNTIME_METHOD_ID,
        "runtime_method_fingerprint": ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        "query_hash": sha256_json(query_text),
        "query_class": query_class,
        "profile_fingerprint": tokenizer_profile.profile_fingerprint,
        "dense_profile_fingerprint": dense_encoder.profile_fingerprint,
        "execution_component_fingerprint": (execution_binding.execution_component_fingerprint),
        "graph_revision_fingerprint": graph_revision_fingerprint,
        "selected_bundle_count": selected_bundle_count,
        "authorized_bundle_count": authorized_bundle_count,
        "denied_bundle_count": denied_bundle_count,
        "warning": warning,
    }
    result = GovernedSemanticExecutionResult(
        artifact_id="formowl_issue56_governed_semantic_execution_result_v1",
        status=status,
        runtime_method_id=ISSUE56_TARGET_RUNTIME_METHOD_ID,
        runtime_method_fingerprint=ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        query_hash=sha256_json(query_text),
        query_class=query_class,
        claim_strength="no_claim",
        plan_fingerprint=None,
        result_fingerprint=sha256_json(result_payload),
        profile_fingerprint=tokenizer_profile.profile_fingerprint,
        index_fingerprint=None,
        graph_revision_fingerprint=graph_revision_fingerprint,
        dense_encoder_id=dense_encoder.encoder_id,
        dense_encoder_status=_PINNED_DENSE_STATUS,
        dense_profile_fingerprint=dense_encoder.profile_fingerprint,
        dense_model_id=execution_binding.dense_model_id,
        dense_model_revision=execution_binding.dense_model_revision,
        execution_component_fingerprint=(execution_binding.execution_component_fingerprint),
        selected_bundle_count=selected_bundle_count,
        authorized_bundle_count=authorized_bundle_count,
        denied_bundle_count=denied_bundle_count,
        materialized_candidate_count=0,
        semantic_result_count=0,
        graph_path_count=0,
        rejected_hop_count=0,
        exact_executor_status="not_started",
        repair_attempt_count=0,
        relation_repair_policy_fingerprint=None,
        relation_repair_vocabulary_fingerprint=None,
        warnings=(warning,),
    )
    result.to_safe_dict()
    return result


def _freeze_graph_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenGraphDict(
            {str(key): _freeze_graph_json_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return _FrozenGraphList(_freeze_graph_json_value(item) for item in value)
    return value


def _sealed_graph_node(payload: Mapping[str, Any]) -> GraphProjectionNode:
    return GraphProjectionNode(
        node_id=str(payload["node_id"]),
        source_type=str(payload["source_type"]),
        source_id=str(payload["source_id"]),
        labels=_freeze_graph_json_value(payload["labels"]),
        properties=_freeze_graph_json_value(payload["properties"]),
        permission_scope=_freeze_graph_json_value(payload["permission_scope"]),
        projection_state=str(payload.get("projection_state", "ready")),
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
    )


def _sealed_graph_edge(payload: Mapping[str, Any]) -> GraphProjectionEdge:
    return GraphProjectionEdge(
        edge_id=str(payload["edge_id"]),
        source_node_id=str(payload["source_node_id"]),
        target_node_id=str(payload["target_node_id"]),
        relation_type=str(payload["relation_type"]),
        properties=_freeze_graph_json_value(payload["properties"]),
        permission_scope=_freeze_graph_json_value(payload["permission_scope"]),
        projection_state=str(payload.get("projection_state", "ready")),
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
    )


def _effective_graph_content_view_binding(
    effective_graph_view: EffectiveGraphView,
) -> tuple[Any, ...]:
    return (
        effective_graph_view.requester_user_id,
        effective_graph_view.user_graph_revision_id,
        effective_graph_view.canonical_graph_revision_id,
        effective_graph_view.ontology_revision_id,
        effective_graph_view.assembly_policy_id,
        id(effective_graph_view.visible_nodes),
        len(effective_graph_view.visible_nodes),
        id(effective_graph_view.visible_edges),
        len(effective_graph_view.visible_edges),
        id(effective_graph_view.access_required),
        tuple(sha256_json(scope.to_dict()) for scope in effective_graph_view.access_required),
        id(effective_graph_view.applied_grant_ids),
        tuple(effective_graph_view.applied_grant_ids),
    )


def _effective_graph_content_fingerprint(
    effective_graph_view: EffectiveGraphView,
) -> str:
    return sha256_json(
        {
            "schema_version": 1,
            "visible_node_hashes": sorted(
                sha256_json(node.to_dict()) for node in effective_graph_view.visible_nodes
            ),
            "visible_edge_hashes": sorted(
                sha256_json(edge.to_dict()) for edge in effective_graph_view.visible_edges
            ),
            "access_required_hashes": sorted(
                sha256_json(scope.to_dict()) for scope in effective_graph_view.access_required
            ),
            "applied_grant_hashes": sorted(
                sha256_json(grant_id) for grant_id in effective_graph_view.applied_grant_ids
            ),
        }
    )


def _require_effective_graph_content_snapshot(
    effective_graph_view: EffectiveGraphView,
) -> _EffectiveGraphContentSnapshot:
    cached = getattr(
        effective_graph_view,
        _EFFECTIVE_GRAPH_CONTENT_SNAPSHOT_ATTRIBUTE,
        None,
    )
    if not isinstance(cached, _EffectiveGraphContentSnapshot):
        raise ContractValidationError("effective graph content snapshot is unavailable")
    if (
        not isinstance(effective_graph_view.visible_nodes, _FrozenGraphList)
        or not isinstance(effective_graph_view.visible_edges, _FrozenGraphList)
        or not isinstance(effective_graph_view.access_required, _FrozenGraphList)
        or not isinstance(effective_graph_view.applied_grant_ids, _FrozenGraphList)
        or cached.view_binding != _effective_graph_content_view_binding(effective_graph_view)
    ):
        raise ContractValidationError("effective graph content snapshot binding mismatch")
    return cached


def _build_effective_graph_content_snapshot(
    effective_graph_view: EffectiveGraphView,
    *,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> _EffectiveGraphContentSnapshot:
    _query_deadline_checkpoint(execution_deadline)
    node_payloads: list[dict[str, Any]] = []
    for node in effective_graph_view.visible_nodes:
        _query_deadline_checkpoint(execution_deadline)
        node_payloads.append(node.to_dict())
    edge_payloads: list[dict[str, Any]] = []
    for edge in effective_graph_view.visible_edges:
        _query_deadline_checkpoint(execution_deadline)
        edge_payloads.append(edge.to_dict())
    access_required_payloads: list[dict[str, Any]] = []
    for scope in effective_graph_view.access_required:
        _query_deadline_checkpoint(execution_deadline)
        access_required_payloads.append(scope.to_dict())
    _query_deadline_checkpoint(execution_deadline)
    graph_revision_fingerprint = sha256_json(
        {
            "requester_user_id": effective_graph_view.requester_user_id,
            "user_graph_revision_id": effective_graph_view.user_graph_revision_id,
            "canonical_graph_revision_id": (effective_graph_view.canonical_graph_revision_id),
            "ontology_revision_id": effective_graph_view.ontology_revision_id,
            "assembly_policy_id": effective_graph_view.assembly_policy_id,
            "applied_grant_ids": sorted(effective_graph_view.applied_grant_ids),
            "access_required_hashes": sorted(
                sha256_json(payload) for payload in access_required_payloads
            ),
            "visible_node_hashes": sorted(sha256_json(payload) for payload in node_payloads),
            "visible_edge_hashes": sorted(sha256_json(payload) for payload in edge_payloads),
        }
    )
    sealed_nodes = _FrozenGraphList()
    for payload in node_payloads:
        _query_deadline_checkpoint(execution_deadline)
        list.append(sealed_nodes, _sealed_graph_node(payload))
    sealed_edges = _FrozenGraphList()
    for payload in edge_payloads:
        _query_deadline_checkpoint(execution_deadline)
        list.append(sealed_edges, _sealed_graph_edge(payload))
    sealed_access_required = _FrozenGraphList(effective_graph_view.access_required)
    sealed_applied_grant_ids = _FrozenGraphList(effective_graph_view.applied_grant_ids)
    object.__setattr__(effective_graph_view, "visible_nodes", sealed_nodes)
    object.__setattr__(effective_graph_view, "visible_edges", sealed_edges)
    object.__setattr__(
        effective_graph_view,
        "access_required",
        sealed_access_required,
    )
    object.__setattr__(
        effective_graph_view,
        "applied_grant_ids",
        sealed_applied_grant_ids,
    )
    snapshot = _EffectiveGraphContentSnapshot(
        graph_revision_fingerprint=graph_revision_fingerprint,
        view_binding=_effective_graph_content_view_binding(effective_graph_view),
    )
    object.__setattr__(
        effective_graph_view,
        _EFFECTIVE_GRAPH_CONTENT_SNAPSHOT_ATTRIBUTE,
        snapshot,
    )
    _query_deadline_checkpoint(execution_deadline)
    return snapshot


def _graph_revision_fingerprint(
    effective_graph_view: EffectiveGraphView,
    *,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> str:
    _query_deadline_checkpoint(execution_deadline)
    cached = getattr(
        effective_graph_view,
        _EFFECTIVE_GRAPH_CONTENT_SNAPSHOT_ATTRIBUTE,
        None,
    )
    if cached is not None:
        fingerprint = _require_effective_graph_content_snapshot(
            effective_graph_view
        ).graph_revision_fingerprint
        _query_deadline_checkpoint(execution_deadline)
        return fingerprint
    return _build_effective_graph_content_snapshot(
        effective_graph_view,
        execution_deadline=execution_deadline,
    ).graph_revision_fingerprint


def _graph_revision_pin_fingerprint(
    effective_graph_view: EffectiveGraphView,
) -> str:
    """Return an O(1) revision pin for a timeout before full graph sealing."""

    return sha256_json(
        {
            "requester_user_id": effective_graph_view.requester_user_id,
            "user_graph_revision_id": effective_graph_view.user_graph_revision_id,
            "canonical_graph_revision_id": (effective_graph_view.canonical_graph_revision_id),
            "ontology_revision_id": effective_graph_view.ontology_revision_id,
            "assembly_policy_id": effective_graph_view.assembly_policy_id,
        }
    )


def _build_query_graph_snapshot(
    effective_graph_view: EffectiveGraphView,
    *,
    execution_deadline: _QueryExecutionDeadline | None = None,
) -> _QueryGraphSnapshot:
    graph_revision_fingerprint = _graph_revision_fingerprint(
        effective_graph_view,
        execution_deadline=execution_deadline,
    )
    _query_deadline_checkpoint(execution_deadline)
    return _QueryGraphSnapshot(
        effective_graph_view=effective_graph_view,
        graph_revision_fingerprint=graph_revision_fingerprint,
        content_snapshot=_require_effective_graph_content_snapshot(effective_graph_view),
    )


def _require_query_graph_snapshot(
    *,
    effective_graph_view: EffectiveGraphView,
    graph_snapshot: _QueryGraphSnapshot,
) -> str:
    if (
        graph_snapshot.effective_graph_view is not effective_graph_view
        or graph_snapshot.content_snapshot
        is not _require_effective_graph_content_snapshot(effective_graph_view)
        or graph_snapshot.graph_revision_fingerprint
        != graph_snapshot.content_snapshot.graph_revision_fingerprint
    ):
        raise ContractValidationError("query graph snapshot binding mismatch")
    return graph_snapshot.graph_revision_fingerprint


def _hybrid_candidate_from_snippet(
    snippet: IndexedMailSnippet,
    *,
    dense_encoder: DenseEncoder,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    coherence_group_hash: str,
) -> _HybridCandidate:
    source_observation_id = snippet.payload.get("source_observation_id")
    message_id = snippet.payload.get("email_message_id")
    message_occurrence_id = snippet.payload.get("message_occurrence_id")
    if not isinstance(source_observation_id, str) or not source_observation_id:
        raise ContractValidationError("mail evidence candidate lineage is unavailable")
    if not isinstance(message_id, str) or not message_id:
        raise ContractValidationError("mail evidence message lineage is unavailable")
    if not isinstance(message_occurrence_id, str) or not message_occurrence_id:
        raise ContractValidationError("mail evidence message occurrence lineage is unavailable")
    source_observation_hash = snippet.source_observation_hash or sha256_json(source_observation_id)
    observation_text = snippet.payload.get("snippet")
    if not isinstance(observation_text, str):
        raise ContractValidationError("mail evidence Observation text lineage is unavailable")
    observation_analysis = tokenizer_profile.analyze(observation_text)
    observation_tokens = frozenset(observation_analysis.tokens)
    observation_protected_tokens = frozenset(
        span.exact_token for span in observation_analysis.protected_identifiers
    )
    message_hash = sha256_json(message_id)
    message_occurrence_hash = sha256_json(message_occurrence_id)
    index_binding_hash = sha256_json(
        {
            "source_observation_hash": source_observation_hash,
            "message_hash": message_hash,
            "message_occurrence_hash": message_occurrence_hash,
            "dense_evidence_text_hash": sha256_json(snippet.dense_evidence_text),
        }
    )
    return _HybridCandidate(
        bundle_id=snippet.mail_evidence_bundle_id,
        coherence_group_hash=coherence_group_hash,
        source_observation_hash=source_observation_hash,
        message_hash=message_hash,
        message_occurrence_hash=message_occurrence_hash,
        index_binding_hash=index_binding_hash,
        searchable_tokens=frozenset(snippet.searchable_tokens),
        protected_identifier_tokens=frozenset(snippet.protected_identifier_tokens),
        observation_tokens=observation_tokens,
        observation_protected_identifier_tokens=observation_protected_tokens,
        dense_evidence_text_hash=sha256_json(snippet.dense_evidence_text),
        dense_vector=dense_encoder.encode_evidence(snippet.dense_evidence_text),
    )


def _require_hybrid_index_profile(
    snippet_index: MailSnippetIndex,
    *,
    tokenizer_profile: MailCandidateAdmissionTokenizerProfile,
    expected_profile_fingerprint: str,
) -> None:
    if snippet_index.profile_fingerprint != expected_profile_fingerprint:
        raise ContractValidationError("mail evidence tokenizer profile mismatch")
    if snippet_index.profile_fingerprint != tokenizer_profile.profile_fingerprint:
        raise ContractValidationError("mail evidence tokenizer profile mismatch")


def _validate_hybrid_query_inputs(
    *,
    query_text: str,
    query_class: str,
    candidate_limit: int,
    result_limit: int,
) -> None:
    if not isinstance(query_text, str) or not query_text.strip():
        raise ContractValidationError("query_text is required")
    safe_public_string(query_text, "query_text")
    if not isinstance(query_class, str) or not query_class.strip():
        raise ContractValidationError("query_class is required")
    safe_public_string(query_class, "query_class")
    for field_name, value in (
        ("candidate_limit", candidate_limit),
        ("result_limit", result_limit),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContractValidationError(f"{field_name} must be a positive integer")


def _route_blocked_result(
    *,
    query_hash: str,
    query_class: str,
    runtime_components: Issue56TargetRuntimeComponents,
    selected_bundle_count: int,
    authorized_bundle_count: int,
    denied_bundle_count: int,
) -> GovernedHybridRagResult:
    tokenizer_profile = runtime_components.tokenizer_profile
    dense_encoder = runtime_components.dense_encoder
    execution_binding = runtime_components.execution_binding
    warning = (
        "deterministic_exact_executor_required"
        if query_class == "exact_set_or_inventory"
        else "issue56_query_route_not_implemented"
    )
    result = GovernedHybridRagResult(
        artifact_id="formowl_issue56_governed_hybrid_rag_result_v1",
        status="route_blocked",
        runtime_method_id=ISSUE56_TARGET_RUNTIME_METHOD_ID,
        runtime_method_fingerprint=ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        query_hash=query_hash,
        query_class=query_class,
        candidate_profile_id=tokenizer_profile.tokenizer_id,
        profile_fingerprint=tokenizer_profile.profile_fingerprint,
        index_fingerprint=None,
        dense_encoder_id=dense_encoder.encoder_id,
        dense_encoder_status=_PINNED_DENSE_STATUS,
        dense_profile_fingerprint=dense_encoder.profile_fingerprint,
        dense_model_id=execution_binding.dense_model_id,
        dense_model_revision=execution_binding.dense_model_revision,
        execution_component_fingerprint=(execution_binding.execution_component_fingerprint),
        selected_bundle_count=selected_bundle_count,
        authorized_bundle_count=authorized_bundle_count,
        denied_bundle_count=denied_bundle_count,
        materialized_candidate_count=0,
        retrieved_candidate_count=0,
        result_bundle_count=0,
        exact_executor_status=(
            "required_but_unavailable"
            if query_class == "exact_set_or_inventory"
            else "not_requested"
        ),
        warnings=(warning,),
    )
    result.to_safe_dict()
    return result


def _no_answer_result(
    *,
    index: AuthorizedHybridMailIndex,
    query_hash: str,
    query_class: str,
    warning: str,
    retrieved_candidate_count: int = 0,
    admitted_candidate_scores: tuple[HybridRagCandidateScore, ...] = (),
) -> GovernedHybridRagResult:
    result = GovernedHybridRagResult(
        artifact_id="formowl_issue56_governed_hybrid_rag_result_v1",
        status="no_answer",
        runtime_method_id=ISSUE56_TARGET_RUNTIME_METHOD_ID,
        runtime_method_fingerprint=ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        query_hash=query_hash,
        query_class=query_class,
        candidate_profile_id=index.tokenizer_id,
        profile_fingerprint=index.profile_fingerprint,
        index_fingerprint=index.index_fingerprint,
        dense_encoder_id=index.dense_encoder_id,
        dense_encoder_status=index.dense_encoder_status,
        dense_profile_fingerprint=index.dense_profile_fingerprint,
        dense_model_id=index.dense_model_id,
        dense_model_revision=index.dense_model_revision,
        execution_component_fingerprint=index.execution_component_fingerprint,
        selected_bundle_count=index.selected_bundle_count,
        authorized_bundle_count=index.authorized_bundle_count,
        denied_bundle_count=index.denied_bundle_count,
        materialized_candidate_count=len(index.candidates),
        retrieved_candidate_count=retrieved_candidate_count,
        result_bundle_count=0,
        exact_executor_status="not_requested",
        admitted_candidate_scores=admitted_candidate_scores,
        warnings=(warning,),
    )
    result.to_safe_dict()
    return result


@lru_cache(maxsize=1)
def _load_pinned_issue56_runtime_components() -> Issue56TargetRuntimeComponents:
    """Load one process-local pinned runtime; never substitute another encoder."""

    try:
        return load_issue56_target_runtime_components()
    except DenseEmbeddingUnavailableError:
        raise
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise DenseEmbeddingUnavailableError("target_tokenizer_runtime_unavailable") from exc


def _require_issue56_runtime_components(
    *,
    expected_profile_fingerprint: str | None,
) -> Issue56TargetRuntimeComponents:
    components = _load_pinned_issue56_runtime_components()
    return _validate_loaded_issue56_runtime_components(
        components,
        expected_profile_fingerprint=expected_profile_fingerprint,
    )


def _validate_loaded_issue56_runtime_components(
    components: Issue56TargetRuntimeComponents,
    *,
    expected_profile_fingerprint: str | None,
) -> Issue56TargetRuntimeComponents:
    if not isinstance(components, Issue56TargetRuntimeComponents):
        raise DenseEmbeddingUnavailableError("execution_component_binding_mismatch")
    tokenizer_profile = components.tokenizer_profile
    expected_tokenizer_fingerprint = (
        expected_profile_fingerprint or tokenizer_profile.profile_fingerprint
    )
    require_issue56_target_tokenizer_profile(
        tokenizer_profile,
        expected_profile_fingerprint=expected_tokenizer_fingerprint,
    )
    dense_encoder = components.dense_encoder
    declared_dense_profile = issue56_target_dense_embedding_profile()
    if (
        dense_encoder.diagnostic
        or dense_encoder.encoder_id != ISSUE56_TARGET_DENSE_ENCODER_ID
        or dense_encoder.dimension != ISSUE56_TARGET_DENSE_DIMENSION
        or dense_encoder.profile_fingerprint != ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT
        or dense_encoder.profile != declared_dense_profile
    ):
        raise DenseEmbeddingUnavailableError("dense_profile_fingerprint_mismatch")
    expected_binding = build_issue56_execution_component_binding(
        tokenizer_profile=tokenizer_profile,
        dense_profile=declared_dense_profile,
    )
    binding = components.execution_binding
    if (
        binding != expected_binding
        or binding.dense_encoder_id != ISSUE56_TARGET_DENSE_ENCODER_ID
        or binding.dense_model_id != ISSUE56_TARGET_DENSE_MODEL_ID
        or binding.dense_model_revision != ISSUE56_TARGET_DENSE_MODEL_REVISION
        or binding.dense_profile_fingerprint != ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT
    ):
        raise DenseEmbeddingUnavailableError("execution_component_binding_mismatch")
    return components


def _hybrid_index_integrity_fingerprint(
    *,
    index_fingerprint: str,
    tokenizer_id: str,
    profile_fingerprint: str,
    execution_component_fingerprint: str,
    candidates: Sequence[_HybridCandidate],
    precomputed_graph_revision_fingerprint: str | None,
) -> str:
    return sha256_json(
        {
            "index_fingerprint": index_fingerprint,
            "tokenizer_id": tokenizer_id,
            "profile_fingerprint": profile_fingerprint,
            "execution_component_fingerprint": execution_component_fingerprint,
            "precomputed_graph_revision_fingerprint": (
                precomputed_graph_revision_fingerprint
            ),
            "candidate_bindings": [
                [
                    candidate.source_observation_hash,
                    candidate.index_binding_hash,
                    candidate.message_occurrence_hash,
                ]
                for candidate in candidates
            ],
        }
    )


def _validate_hybrid_index_runtime_binding(
    index: AuthorizedHybridMailIndex,
) -> None:
    components = _validate_loaded_issue56_runtime_components(
        index._runtime_components,
        expected_profile_fingerprint=index.profile_fingerprint,
    )
    binding = components.execution_binding
    if (
        index.tokenizer_id != binding.tokenizer_id
        or index.profile_fingerprint != binding.tokenizer_profile_fingerprint
        or index.dense_encoder_id != binding.dense_encoder_id
        or index.dense_encoder_status != _PINNED_DENSE_STATUS
        or index.dense_profile_fingerprint != binding.dense_profile_fingerprint
        or index.dense_model_id != binding.dense_model_id
        or index.dense_model_revision != binding.dense_model_revision
        or index.execution_component_fingerprint != binding.execution_component_fingerprint
    ):
        raise ContractValidationError("mail evidence execution component mismatch")


def _validate_hybrid_index_runtime(index: AuthorizedHybridMailIndex) -> None:
    _validate_hybrid_index_runtime_binding(index)
    expected_integrity_fingerprint = _hybrid_index_integrity_fingerprint(
        index_fingerprint=index.index_fingerprint,
        tokenizer_id=index.tokenizer_id,
        profile_fingerprint=index.profile_fingerprint,
        execution_component_fingerprint=index.execution_component_fingerprint,
        candidates=index.candidates,
        precomputed_graph_revision_fingerprint=(
            index._precomputed_graph_revision_fingerprint
        ),
    )
    if index._integrity_fingerprint != expected_integrity_fingerprint:
        raise ContractValidationError("mail evidence index binding mismatch")


def _positive_ranks(scores: Sequence[float]) -> dict[int, int]:
    ordered = [
        index
        for index, score in sorted(
            enumerate(scores),
            key=lambda item: (-item[1], item[0]),
        )
        if score > 0.0
    ]
    return {index: rank for rank, index in enumerate(ordered, start=1)}


def _select_coherent_bundle_results(
    ranked_results: Sequence[HybridRagBundleScore],
    *,
    proof_slots: _EvidenceQuerySlots,
    coverage_tokens_by_group_hash: Mapping[str, frozenset[str]],
    protected_tokens_by_group_hash: Mapping[str, frozenset[str]],
    result_limit: int,
) -> tuple[HybridRagBundleScore, ...]:
    selected: list[HybridRagBundleScore] = []
    for result in ranked_results:
        covered_query_tokens = set(
            coverage_tokens_by_group_hash.get(
                result.evidence_bundle_hash,
                frozenset(),
            )
        )
        covered_protected_tokens = set(
            protected_tokens_by_group_hash.get(
                result.evidence_bundle_hash,
                frozenset(),
            )
        )
        if not proof_slots.identifier_tokens.issubset(covered_protected_tokens):
            continue
        if not proof_slots.topic_tokens.issubset(covered_query_tokens):
            continue
        selected.append(result)
        if len(selected) >= result_limit:
            break
    return tuple(selected)


def _top_ranked_indexes(
    scores: Sequence[float],
    limit: int,
    *,
    allowed_indexes: set[int] | None = None,
) -> tuple[int, ...]:
    return tuple(
        index
        for index, score in sorted(
            enumerate(scores),
            key=lambda item: (-item[1], item[0]),
        )
        if score > 0.0 and (allowed_indexes is None or index in allowed_indexes)
    )[:limit]


def _cosine_similarity(
    left: Sequence[float],
    right: Sequence[float],
) -> float:
    if len(left) != len(right):
        raise ContractValidationError("dense vector dimensions do not match")
    return sum(left_value * right_value for left_value, right_value in zip(left, right))


def _metric(value: float) -> float:
    return round(float(value), 8)


__all__ = [
    "AuthorizedHybridObservationIndexArtifact",
    "AuthorizedHybridMailIndex",
    "AuthorizedSemanticMailSession",
    "AuthorizedSemanticObservationSession",
    "BoundedGraphPath",
    "DenseEncoder",
    "EvidenceIdentityLineageAudit",
    "EvidenceIdentityLineageCrosswalk",
    "EvidenceIdentityLineageEntry",
    "EffectiveGraphContentSnapshotPrecompute",
    "GovernedHybridRagResult",
    "GovernedSemanticExecutionResult",
    "GraphTraversalHop",
    "HybridRagBundleScore",
    "HybridRagCandidateScore",
    "ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT",
    "ISSUE56_TARGET_RUNTIME_METHOD_ID",
    "RelationProjectionBasePrecompute",
    "RelationProjectionBaseColdDiagnostic",
    "SemanticEvidenceScore",
    "SourceBackedGraphBuild",
    "attach_authorized_source_occurrence_providers",
    "build_authorized_hybrid_mail_index",
    "build_authorized_hybrid_observation_index_artifact",
    "build_authorized_semantic_mail_session",
    "build_authorized_semantic_observation_session",
    "build_authorized_source_backed_effective_graph_view",
    "build_evidence_identity_lineage_crosswalk",
    "precompute_effective_graph_content_snapshot",
    "precompute_evidence_identity_lineage_crosswalk",
    "precompute_relation_projection_base",
    "precompute_relation_projection_base_cold_diagnostic",
    "run_authorized_hybrid_mail_query",
    "run_authorized_semantic_mail_query",
]
