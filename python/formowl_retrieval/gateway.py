from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
import inspect
import math
import re
import time
from typing import Any, Callable, Iterator, Literal, Protocol, Sequence
import unicodedata

from formowl_auth import FileAuditLogStore, write_audit_log
from formowl_contract import (
    AuditLog,
    ContractValidationError,
    Grant,
    Observation,
    now_iso,
    to_plain,
)
from formowl_graph.index import (
    FileGraphProjectionStore,
    FileVectorStore,
    GraphProjectionEdge,
    GraphProjectionNode,
    VectorSearchResult,
    requester_has_graph_access,
)
from formowl_graph.user_graphs import EffectiveGraphView

from .kg_first import (
    EvidenceContext,
    EvidenceResolver,
    GraphHit,
    match_effective_graph_view,
    proposal_seeds_from_fallback,
)

RetrievalMode = Literal["answer_only", "evidence_snippet", "raw_asset"]

_RETRIEVAL_MODES = {"answer_only", "evidence_snippet", "raw_asset"}
_RAW_ASSET_GRANT_PERMISSION = "asset_scoped_access"
_FORBIDDEN_PUBLIC_KEYS = {
    "absolute_path",
    "bucket",
    "database_url",
    "debug_path",
    "dsn",
    "filesystem_path",
    "internal_backend_id",
    "internal_endpoint",
    "internal_sql",
    "internal_url",
    "object_key",
    "object_store_uri",
    "raw_path",
    "secret",
    "signed_url",
    "sql",
    "stack_trace",
    "storage_key",
    "token",
    "traceback",
    "worker_scratch",
}
_FORBIDDEN_PUBLIC_VALUE = re.compile(
    r"(^|[^A-Za-z0-9_.-])(/|[A-Za-z]:[\\/]|\\\\|file://|s3://|smb://|nfs://|"
    r"(?:artifacts|cache|data|nas|object_store|objects|scratch|share|srv|tmp|workspace)"
    r"[\\/]+|"
    r"postgres(?:ql)?://|\bselect\b\s+|\bwith\b\s+|\binsert\b\s+|\bupdate\b\s+|"
    r"\bdelete\b\s+|\bdrop\b\s+)",
    re.IGNORECASE,
)
_FORMOWL_ASSET_LOCATOR = re.compile(r"^formowl://asset/[A-Za-z0-9][A-Za-z0-9_.-]*$")
_FORMOWL_OBSERVATION_LOCATOR = re.compile(r"^formowl://observation/[A-Za-z0-9][A-Za-z0-9_.-]*$")

SOURCE_EVIDENCE_OBSERVATION_LIMIT = 8_192
SOURCE_EVIDENCE_TIME_BUDGET_MS = 500
DEVELOPMENT_POC_SOURCE_EVIDENCE_BOUNDARY_ID = "development_poc_v1"
SECURITY_REVIEW_SOURCE_EVIDENCE_BOUNDARY_ID = "security_review_v1"
SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILIES = ("mail", "document_text")
_SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILY_SET = frozenset(
    SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILIES
)
_SOURCE_EVIDENCE_ELIGIBLE_STATUSES = frozenset(
    {"ok", "not_found", "no_answer", "incomplete", "partial", "pending_review", "unsupported"}
)
_SOURCE_EVIDENCE_PLAN_CLASSES = ("evidence_lookup", "relation_reasoning", "global_summarization")


@dataclass(frozen=True)
class SourceEvidenceExecutionPolicy:
    """Explicit claim boundary for the shared mail/document source recheck.

    The development POC policy is the only default.  A security-review policy
    requires the executable authority gates and the independent three-reviewer
    gate before the shared core may be labelled as review evidence.  This
    policy changes no authorization, provenance, or source-reader behavior.
    """

    boundary_id: str = DEVELOPMENT_POC_SOURCE_EVIDENCE_BOUNDARY_ID
    supported_source_families: tuple[str, ...] = SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILIES
    authority_ready: bool = False
    source_completeness_verified: bool = False
    execution_fingerprint_bound: bool = False
    same_pipeline_ablation_verified: bool = False
    final_answer_acceptance_verified: bool = False
    reviewer_agreement_count: int = 0

    @classmethod
    def development_poc(
        cls,
        *,
        supported_source_families: Sequence[str] = SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILIES,
    ) -> SourceEvidenceExecutionPolicy:
        return cls(
            boundary_id=DEVELOPMENT_POC_SOURCE_EVIDENCE_BOUNDARY_ID,
            supported_source_families=tuple(supported_source_families),
        ).validate()

    @classmethod
    def security_review(
        cls,
        *,
        authority_ready: bool,
        source_completeness_verified: bool,
        execution_fingerprint_bound: bool,
        same_pipeline_ablation_verified: bool,
        final_answer_acceptance_verified: bool,
        reviewer_agreement_count: int,
        supported_source_families: Sequence[str] = SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILIES,
    ) -> SourceEvidenceExecutionPolicy:
        return cls(
            boundary_id=SECURITY_REVIEW_SOURCE_EVIDENCE_BOUNDARY_ID,
            supported_source_families=tuple(supported_source_families),
            authority_ready=authority_ready,
            source_completeness_verified=source_completeness_verified,
            execution_fingerprint_bound=execution_fingerprint_bound,
            same_pipeline_ablation_verified=same_pipeline_ablation_verified,
            final_answer_acceptance_verified=final_answer_acceptance_verified,
            reviewer_agreement_count=reviewer_agreement_count,
        ).validate()

    def validate(self) -> SourceEvidenceExecutionPolicy:
        if self.boundary_id not in {
            DEVELOPMENT_POC_SOURCE_EVIDENCE_BOUNDARY_ID,
            SECURITY_REVIEW_SOURCE_EVIDENCE_BOUNDARY_ID,
        }:
            raise ContractValidationError("source evidence execution boundary is invalid")
        if not self.supported_source_families or any(
            not isinstance(source_family, str)
            or source_family not in _SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILY_SET
            for source_family in self.supported_source_families
        ):
            raise ContractValidationError("source evidence source family boundary is invalid")
        if len(set(self.supported_source_families)) != len(self.supported_source_families):
            raise ContractValidationError("source evidence source family boundary is invalid")
        for field_name in (
            "authority_ready",
            "source_completeness_verified",
            "execution_fingerprint_bound",
            "same_pipeline_ablation_verified",
            "final_answer_acceptance_verified",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ContractValidationError(
                    f"source evidence boundary field is invalid: {field_name}"
                )
        if (
            type(self.reviewer_agreement_count) is not int
            or self.reviewer_agreement_count < 0
        ):
            raise ContractValidationError("source evidence reviewer agreement count is invalid")
        if self.boundary_id == SECURITY_REVIEW_SOURCE_EVIDENCE_BOUNDARY_ID:
            required = (
                self.authority_ready,
                self.source_completeness_verified,
                self.execution_fingerprint_bound,
                self.same_pipeline_ablation_verified,
                self.final_answer_acceptance_verified,
            )
            if not all(required) or self.reviewer_agreement_count != 3:
                raise ContractValidationError(
                    "security review source evidence boundary requires authority, "
                    "four methodology gates, and three reviewer agreements"
                )
        return self

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "boundary_id": self.boundary_id,
            "supported_source_families": list(self.supported_source_families),
            "claim_class": (
                "development_diagnostic_only"
                if self.boundary_id == DEVELOPMENT_POC_SOURCE_EVIDENCE_BOUNDARY_ID
                else "security_review_evidence_candidate"
            ),
            "authority_ready": self.authority_ready,
            "source_completeness_verified": self.source_completeness_verified,
            "execution_fingerprint_bound": self.execution_fingerprint_bound,
            "same_pipeline_ablation_verified": self.same_pipeline_ablation_verified,
            "final_answer_acceptance_verified": self.final_answer_acceptance_verified,
            "reviewer_agreement_count": self.reviewer_agreement_count,
        }


@dataclass(frozen=True)
class SourceEvidenceScan:
    """Internal result of one scope-bound, authorized Observation read."""

    observations: tuple[tuple[Observation, str], ...]
    scanned_observation_count: int
    complete: bool
    stop_reason: str | None = None


@dataclass(frozen=True)
class SourceEvidenceDoubleCheckResult:
    """Internal outcome; None leaves the initial adapter status unchanged."""

    execution_boundary_id: str = DEVELOPMENT_POC_SOURCE_EVIDENCE_BOUNDARY_ID
    supported_source_families: tuple[str, ...] = SOURCE_NEUTRAL_EVIDENCE_SOURCE_FAMILIES
    status: str | None = None
    evidence: tuple[dict[str, Any], ...] = ()
    scan: SourceEvidenceScan | None = None
    warnings: tuple[str, ...] = ()


class _SourceEvidenceDeadlineExceeded(RuntimeError):
    """Only this local budget stop is recoverable; security errors propagate."""


_SOURCE_EVIDENCE_DEADLINE: ContextVar[float | None] = ContextVar(
    "formowl_source_evidence_deadline", default=None,
)
_SOURCE_EVIDENCE_QUERY_TERMS: ContextVar[tuple[str, ...]] = ContextVar(
    "formowl_source_evidence_query_terms", default=(),
)


def _validate_source_evidence_deadline(deadline_monotonic: float | None) -> None:
    if deadline_monotonic is not None and (
        type(deadline_monotonic) not in (int, float)
        or (isinstance(deadline_monotonic, float) and not math.isfinite(deadline_monotonic))
    ):
        raise ContractValidationError("source evidence deadline is invalid")


@contextmanager
def source_evidence_deadline_scope(deadline_monotonic: float | None) -> Iterator[None]:
    """Carry a trusted server deadline on this process's monotonic clock.

    Nested scopes may shorten, never clear or extend, an inherited deadline.
    Callers own context propagation across execution boundaries; this is not
    a public/provider argument or a cancellation mechanism.
    """

    _validate_source_evidence_deadline(deadline_monotonic)
    inherited = _SOURCE_EVIDENCE_DEADLINE.get()
    if inherited is not None:
        deadline_monotonic = (
            inherited if deadline_monotonic is None else min(inherited, deadline_monotonic)
        )
    token = _SOURCE_EVIDENCE_DEADLINE.set(deadline_monotonic)
    try:
        yield
    finally:
        _SOURCE_EVIDENCE_DEADLINE.reset(token)


def check_source_evidence_deadline(deadline_monotonic: float | None) -> None:
    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
        raise _SourceEvidenceDeadlineExceeded()


@contextmanager
def source_evidence_query_terms_scope(query_terms: Sequence[str]) -> Iterator[None]:
    """Carry normalized terms to an owner-bound sealed source reader.

    Terms are metadata-only acceleration hints.  The source reader still
    revalidates every selected helper, Observation hash, permission, and
    lineage, and an index miss is never a no-match claim.
    """

    normalized = tuple(sorted({
        term for term in query_terms
        if isinstance(term, str) and term
    }))
    token = _SOURCE_EVIDENCE_QUERY_TERMS.set(normalized)
    try:
        yield
    finally:
        _SOURCE_EVIDENCE_QUERY_TERMS.reset(token)


def current_source_evidence_query_terms() -> tuple[str, ...]:
    """Return the current validated matcher terms for source acceleration."""

    return _SOURCE_EVIDENCE_QUERY_TERMS.get()


def _source_evidence_query_terms(
    project_observation: Callable[..., Any],
) -> tuple[str, ...]:
    """Read the existing normalized matcher terms without accepting raw text."""

    explicit = getattr(project_observation, "source_lookup_terms", None)
    if isinstance(explicit, (list, tuple, set, frozenset)):
        values = explicit
    else:
        try:
            values = inspect.getclosurevars(project_observation).nonlocals.get(
                "query_terms", ()
            )
        except (TypeError, ValueError):
            values = ()
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    if any(not isinstance(term, str) or not term for term in values):
        return ()
    normalized = tuple(sorted(set(values)))
    return normalized if len(normalized) <= 256 else ()


def _normalize_source_evidence_field_sequence(
    value: Sequence[str],
    *,
    parameter_name: str,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ContractValidationError(
            f"{parameter_name} must be a sequence of field names"
        )
    if len(value) > 128:
        raise ContractValidationError(f"{parameter_name} is too large")
    normalized: list[str] = []
    for field_name in value:
        if not isinstance(field_name, str) or not field_name.strip():
            raise ContractValidationError(f"{parameter_name} contains an invalid field")
        field = unicodedata.normalize("NFKC", field_name.strip())
        if len(field) > 120:
            raise ContractValidationError(f"{parameter_name} contains an invalid field")
        if field in normalized:
            raise ContractValidationError(f"{parameter_name} contains duplicate fields")
        normalized.append(field)
    return tuple(normalized)


def source_evidence_supported_requested_fields(
    requested_fields: Sequence[str],
    *,
    exact_result: Any = None,
    answer_citation_hashes: Sequence[str] = (),
    verified_citation_lineages: Sequence[tuple[str, str]] = (),
) -> tuple[str, ...]:
    """Derive source-backed field coverage from governed exact output only.

    Free-text evidence, citation counts, and field mentions are deliberately
    excluded.  A structured source value counts even when its value is an
    explicit blank; the value must still be source-provided and tied to a
    governed citation in the exact item and the retained, authorized evidence.
    The adapter supplies lineage bindings only after projection validation.
    """

    normalized_requested = _normalize_source_evidence_field_sequence(
        requested_fields,
        parameter_name="requested_fields",
    )
    if not normalized_requested or exact_result is None:
        return ()
    if not isinstance(answer_citation_hashes, Sequence) or isinstance(
        answer_citation_hashes, (str, bytes)
    ):
        raise ContractValidationError("answer_citation_hashes must be a sequence")
    answer_citations = {
        citation_hash
        for citation_hash in answer_citation_hashes
        if isinstance(citation_hash, str)
    }
    verified_bindings = set(verified_citation_lineages)
    supported: set[str] = set()
    items = getattr(exact_result, "items", ())
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return ()
    for item in items:
        if getattr(item, "structure_status", None) != "source_provided":
            continue
        item_citations = getattr(item, "cited_observation_hashes", ())
        if not isinstance(item_citations, Sequence) or isinstance(
            item_citations, (str, bytes)
        ):
            continue
        item_citation_set = {
            citation_hash
            for citation_hash in item_citations
            if isinstance(citation_hash, str)
        }
        structured_values = getattr(item, "structured_values", ())
        if not isinstance(structured_values, Sequence) or isinstance(
            structured_values, (str, bytes)
        ):
            continue
        for binding in structured_values:
            if not isinstance(binding, Sequence) or isinstance(binding, (str, bytes)):
                continue
            if len(binding) != 4:
                continue
            field_name, value, citation_hash, lineage_fingerprint = binding
            if (
                not isinstance(field_name, str)
                or field_name not in normalized_requested
                or not isinstance(value, str)
                or not isinstance(citation_hash, str)
                or citation_hash not in item_citation_set
                or citation_hash not in answer_citations
                or not isinstance(lineage_fingerprint, str)
                or (citation_hash, lineage_fingerprint) not in verified_bindings
            ):
                continue
            supported.add(field_name)
    return tuple(field for field in normalized_requested if field in supported)


def source_evidence_double_check(
    *,
    initial_status: str | None,
    query_class: str,
    result_query_class: str | None,
    initial_warnings: Sequence[str],
    verified_evidence_count: int,
    evidence_limit: int,
    sealed_coverage_complete: bool,
    read_source: Callable[..., SourceEvidenceScan] | None,
    project_observation: Callable[[Observation, str, float], tuple[str, dict[str, Any]] | None],
    prepare: Callable[[], None] | None = None,
    begin: Callable[[float], None] | None = None,
    excluded_hashes: Sequence[str] = (),
    execution_policy: SourceEvidenceExecutionPolicy | None = None,
    deadline_monotonic: float | None = None,
    requested_fields: Sequence[str] = (),
    supported_requested_fields: Sequence[str] = (),
) -> SourceEvidenceDoubleCheckResult:
    """One source-neutral recheck, not a new retrieval or authorization path.

    Callbacks close over the validated query, actor/workspace/grants, selector,
    source revision and seal. The reader must enforce that binding; projection
    must revalidate access, hash and lineage before returning (hash, evidence).
    ``prepare`` reuses pinned runtime configuration before the phase clock;
    ``begin`` and all reads/projections share the single 500ms deadline.
    The earliest trusted explicit/scoped absolute monotonic deadline also
    bounds preparation and can only shorten that phase. Neither deadline
    preempts a blocking callback. With neither supplied, behavior is unchanged.
    Only certified sealed coverage AND a complete bounded scan prove a miss.
    """

    policy = (execution_policy or SourceEvidenceExecutionPolicy.development_poc()).validate()
    normalized_requested_fields = _normalize_source_evidence_field_sequence(
        requested_fields,
        parameter_name="requested_fields",
    )
    normalized_supported_fields = _normalize_source_evidence_field_sequence(
        supported_requested_fields,
        parameter_name="supported_requested_fields",
    )
    if not set(normalized_supported_fields).issubset(set(normalized_requested_fields)):
        raise ContractValidationError(
            "supported_requested_fields must be a subset of requested_fields"
        )
    if type(verified_evidence_count) is not int or verified_evidence_count < 0:
        raise ContractValidationError("verified source evidence count is invalid")
    if normalized_supported_fields and not verified_evidence_count:
        raise ContractValidationError("requested field support requires verified evidence")

    def result(**kwargs: Any) -> SourceEvidenceDoubleCheckResult:
        return SourceEvidenceDoubleCheckResult(
            execution_boundary_id=policy.boundary_id,
            supported_source_families=policy.supported_source_families,
            **kwargs,
        )

    exact = (
        query_class == "exact_set_or_inventory"
        or result_query_class == "exact_set_or_inventory"
        or "exact_query_requires_structured_binding" in initial_warnings
    )
    skip = (
        "skipped_exact"
        if exact
        else "skipped_replan"
        if initial_status == "replan_required"
        else None
    )
    if initial_status in {"permission_denied", "error"}:
        return result(
            status=initial_status, warnings=(skip,) if skip else ()
        )
    if skip:
        if skip == "skipped_exact" and initial_status == "ok" and verified_evidence_count:
            # A successful deterministic result stays deliverable. This is an
            # exclusion from source recovery, not a downgrade of exact output.
            return result(warnings=(skip,))
        return result(status="pending_review", warnings=(skip,))
    if query_class not in _SOURCE_EVIDENCE_PLAN_CLASSES or (
        result_query_class is not None and result_query_class not in _SOURCE_EVIDENCE_PLAN_CLASSES
    ):
        return result(
            status="pending_review", warnings=("skipped_invalid_plan",)
        )
    field_lookup = query_class == "evidence_lookup" and result_query_class in {
        None, "evidence_lookup"
    }
    field_coverage_recheck_required = (
        field_lookup and bool(normalized_requested_fields) and not normalized_supported_fields
    )
    if field_lookup and normalized_supported_fields:
        return result()
    if not field_coverage_recheck_required and verified_evidence_count:
        return result()
    if initial_status not in _SOURCE_EVIDENCE_ELIGIBLE_STATUSES:
        return result()
    if type(evidence_limit) is not int or evidence_limit < 0:
        raise ContractValidationError("source evidence limit is invalid")
    if evidence_limit <= 0:
        return result(
            status="pending_review", warnings=("skipped_zero_limit",)
        )
    evidence_limit = min(evidence_limit, 128)
    evidence_limit -= verified_evidence_count
    if evidence_limit <= 0:
        return result(status="pending_review", warnings=("skipped_zero_limit",))
    if not callable(read_source):
        return result(status="pending_review", warnings=("unavailable",))

    _validate_source_evidence_deadline(deadline_monotonic)
    scoped_deadline = _SOURCE_EVIDENCE_DEADLINE.get()
    if scoped_deadline is not None:
        deadline_monotonic = (
            scoped_deadline
            if deadline_monotonic is None
            else min(scoped_deadline, deadline_monotonic)
        )
    scan = SourceEvidenceScan((), 0, False, "deadline")
    evidence: list[dict[str, Any]] = []
    seen_hashes = set(excluded_hashes)
    callback_count = 0
    stop_reason: str | None = None

    def consume(observation: Observation, source_scope: str) -> bool:
        nonlocal callback_count, stop_reason
        if stop_reason is not None:
            return False
        if callback_count >= SOURCE_EVIDENCE_OBSERVATION_LIMIT:
            stop_reason = "observation_limit"
            return False
        callback_count += 1
        try:
            check_source_evidence_deadline(deadline)
            projected = project_observation(observation, source_scope, deadline)
            if projected is not None:
                observation_hash, item = projected
                if observation_hash not in seen_hashes:
                    evidence.append(item)
                    seen_hashes.add(observation_hash)
            check_source_evidence_deadline(deadline)
            if len(evidence) >= evidence_limit:
                stop_reason = "callback"
                return False
            return True
        except _SourceEvidenceDeadlineExceeded:
            stop_reason = "deadline"
            return False

    try:
        check_source_evidence_deadline(deadline_monotonic)
        if prepare is not None:
            prepare()
        check_source_evidence_deadline(deadline_monotonic)
        deadline = time.monotonic() + SOURCE_EVIDENCE_TIME_BUDGET_MS / 1000
        if deadline_monotonic is not None:
            deadline = min(deadline, deadline_monotonic)
        check_source_evidence_deadline(deadline)
        if begin is not None:
            begin(deadline)
        check_source_evidence_deadline(deadline)
        with source_evidence_query_terms_scope(
            _source_evidence_query_terms(project_observation)
        ):
            scan = read_source(
                max_observations=SOURCE_EVIDENCE_OBSERVATION_LIMIT,
                deadline_monotonic=deadline,
                observation_callback=consume,
            )
        if not isinstance(scan, SourceEvidenceScan):
            raise ContractValidationError("source evidence scan result is invalid")
        if (
            type(scan.complete) is not bool
            or type(scan.scanned_observation_count) is not int
            or scan.scanned_observation_count < 0
        ):
            raise ContractValidationError("source evidence scan coverage is invalid")
        # Empty readers can overrun without ever invoking the callback.
        check_source_evidence_deadline(deadline)
        # Older authorized readers return a batch; never replay streamed items.
        if callback_count == 0:
            for observation, source_scope in scan.observations:
                if not consume(observation, source_scope):
                    break
        if scan.scanned_observation_count > SOURCE_EVIDENCE_OBSERVATION_LIMIT:
            stop_reason = "observation_limit"
        if stop_reason is not None:
            scan = replace(scan, complete=False, stop_reason=stop_reason)
    except _SourceEvidenceDeadlineExceeded:
        scan = replace(scan, complete=False, stop_reason="deadline")

    warnings = ["used"]
    if not scan.complete:
        warnings.append("incomplete")
    elif not evidence:
        warnings.append(
            "complete_requested_fields_unverified"
            if verified_evidence_count
            else "complete_no_match"
            if sealed_coverage_complete is True
            else "complete_coverage_incomplete"
        )
    return result(
        status=(
            "ok"
            if evidence
            else "not_found"
            if scan.complete and sealed_coverage_complete is True and not verified_evidence_count
            else "pending_review"
        ),
        evidence=tuple(evidence),
        scan=scan,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class RetrievalTrace:
    retrieval_trace_id: str
    requester_user_id: str
    query_hash: str
    mode: RetrievalMode
    matched_vector_ids: list[str] = field(default_factory=list)
    matched_graph_object_ids: list[str] = field(default_factory=list)
    visible_node_ids: list[str] = field(default_factory=list)
    fallback_used: bool = False
    redacted_count: int = 0
    audit_log_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class RetrievalGatewayResult:
    status: str
    mode: RetrievalMode
    answer: str | None = None
    evidence_snippets: list[dict[str, Any]] = field(default_factory=list)
    raw_asset_refs: list[dict[str, Any]] = field(default_factory=list)
    visible_graph_snippets: list[dict[str, Any]] = field(default_factory=list)
    graph_hits: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str | None = None
    evidence_coverage: float = 0.0
    candidate_graph_proposal_seeds: list[dict[str, Any]] = field(default_factory=list)
    retrieval_trace: RetrievalTrace | None = None
    audit_log_id: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        _assert_public_payload(payload)
        return payload


class RawAssetLocatorResolver(Protocol):
    def resolve_raw_asset_refs(self, result: VectorSearchResult) -> list[dict[str, Any]]:
        """Return FormOwl raw-asset locator references for a visible vector result."""


@dataclass(frozen=True)
class MetadataRawAssetLocatorResolver:
    """Resolve raw asset refs from already indexed metadata.

    This is the default adapter path for file-backed tests and early production
    wiring. It accepts only governed FormOwl asset locators and never returns
    raw object-store or filesystem locations.
    """

    def resolve_raw_asset_refs(self, result: VectorSearchResult) -> list[dict[str, Any]]:
        metadata = result.record.metadata
        locators = metadata.get("asset_locators")
        if not isinstance(locators, list):
            locators = [metadata.get("asset_locator")]
        return [
            {"asset_locator": locator}
            for locator in locators
            if _safe_formowl_asset_locator(locator) is not None
        ]


class RetrievalGateway:
    """Public retrieval boundary that checks grants before exposing content.

    The gateway composes derived vector and graph projection stores. It does not
    read raw assets, execute SQL, or mutate canonical graph state.
    """

    def __init__(
        self,
        *,
        vector_store: FileVectorStore,
        graph_projection_store: FileGraphProjectionStore | None = None,
        audit_store: FileAuditLogStore | None = None,
        raw_asset_resolver: RawAssetLocatorResolver | None = None,
        evidence_resolver: EvidenceResolver | None = None,
        graph_score_threshold: float = 0.25,
        graph_confidence_threshold: float = 0.5,
        minimum_evidence_count: int = 1,
    ) -> None:
        self.vector_store = vector_store
        self.graph_projection_store = graph_projection_store
        self.audit_store = audit_store
        self.raw_asset_resolver = raw_asset_resolver or MetadataRawAssetLocatorResolver()
        self.evidence_resolver = evidence_resolver
        self.graph_score_threshold = graph_score_threshold
        self.graph_confidence_threshold = graph_confidence_threshold
        self.minimum_evidence_count = minimum_evidence_count

    def query_effective_graph(
        self,
        *,
        query_embedding: Sequence[float],
        query_text: str,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        grants: Sequence[Grant | dict[str, Any]] = (),
        mode: RetrievalMode = "answer_only",
        limit: int = 5,
        now: str | None = None,
        effective_graph_view: EffectiveGraphView | None = None,
    ) -> RetrievalGatewayResult:
        """Deprecated projection-compatible query alias."""

        return self._query_effective_graph(
            query_embedding=query_embedding,
            query_text=query_text,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            grants=grants,
            mode=mode,
            limit=limit,
            now=now,
            effective_graph_view=effective_graph_view,
        )

    def _query_effective_graph(
        self,
        *,
        query_embedding: Sequence[float],
        query_text: str,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        grants: Sequence[Grant | dict[str, Any]] = (),
        mode: RetrievalMode = "answer_only",
        limit: int = 5,
        now: str | None = None,
        effective_graph_view: EffectiveGraphView | None = None,
    ) -> RetrievalGatewayResult:
        _validate_query_inputs(
            query_text=query_text,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            mode=mode,
            limit=limit,
        )
        resolved_now = now or now_iso()
        grant_objects = _normalize_grants(grants)
        if mode == "raw_asset" and self.audit_store is None:
            trace = _retrieval_trace(
                requester_user_id=requester_user_id,
                query_text=query_text,
                mode=mode,
            )
            return RetrievalGatewayResult(
                status="permission_denied",
                mode=mode,
                retrieval_trace=trace,
                warnings=["raw_asset_mode_requires_audit_store"],
            )
        if mode == "raw_asset" and not _has_raw_asset_access_grant(
            grant_objects,
            requester_user_id=requester_user_id,
            now=resolved_now,
        ):
            audit = self._audit(
                actor_user_id=requester_user_id,
                action="retrieval_denied",
                target_id=workspace_id,
                workspace_id=workspace_id,
                session_id=session_id,
                status="permission_denied",
                metadata={"reason": "raw_asset_mode_requires_explicit_grant"},
            )
            trace = _retrieval_trace(
                requester_user_id=requester_user_id,
                query_text=query_text,
                mode=mode,
                audit_log_id=audit.audit_log_id if audit else None,
            )
            return RetrievalGatewayResult(
                status="permission_denied",
                mode=mode,
                retrieval_trace=trace,
                audit_log_id=audit.audit_log_id if audit else None,
                warnings=["raw_asset_mode_requires_explicit_grant"],
            )

        graph_view = effective_graph_view or self._projection_graph_view(
            requester_user_id=requester_user_id,
            grants=grant_objects,
            now=resolved_now,
        )
        if graph_view.requester_user_id != requester_user_id:
            raise ContractValidationError("effective graph view requester does not match query")
        graph_view = _permission_filter_effective_graph_view(
            graph_view,
            requester_user_id=requester_user_id,
            grants=grant_objects,
            now=resolved_now,
        )
        graph_hits = match_effective_graph_view(
            graph_view,
            query_text,
            limit=limit,
            score_threshold=self.graph_score_threshold,
        )
        evidence, unresolved_observation_ids = self._resolve_evidence(
            graph_hits,
            requester_user_id=requester_user_id,
            grants=grant_objects,
            now=resolved_now,
        )
        required_observation_ids = sorted(
            {observation_id for hit in graph_hits for observation_id in hit.source_observation_ids}
        )
        evidence, lineage_mismatch_ids = _filter_evidence_by_graph_lineage(
            graph_hits,
            evidence,
        )
        unresolved_observation_ids = sorted({*unresolved_observation_ids, *lineage_mismatch_ids})
        graph_hits = _attach_evidence_locators(graph_hits, evidence)
        usable_evidence = [context for context in evidence if context.snippet is not None]
        evidence_coverage = (
            round(len(usable_evidence) / len(required_observation_ids), 6)
            if required_observation_ids
            else 0.0
        )
        fallback_reason = _fallback_reason(
            graph_hits,
            evidence=usable_evidence,
            unresolved_observation_ids=unresolved_observation_ids,
            evidence_coverage=evidence_coverage,
            graph_confidence_threshold=self.graph_confidence_threshold,
            minimum_evidence_count=self.minimum_evidence_count,
        )
        fallback_used = fallback_reason is not None
        results = (
            self.vector_store.search(
                list(query_embedding),
                requester_user_id=requester_user_id,
                grants=list(grant_objects),
                allow_stale=False,
                limit=limit,
                now=resolved_now,
            )
            if fallback_used
            else []
        )
        fallback_seed_evidence = self._resolve_fallback_seed_evidence(
            results,
            requester_user_id=requester_user_id,
            grants=grant_objects,
            now=resolved_now,
        )
        proposal_seeds = (
            proposal_seeds_from_fallback(
                query_text=query_text,
                fallback_records=[
                    {
                        "source_type": "observation",
                        "source_id": context.observation_id,
                        "metadata": {"asset_id": context.asset_id},
                    }
                    for context in fallback_seed_evidence
                    if context.asset_id is not None
                ],
            )
            if fallback_used
            else []
        )
        authorized_raw_evidence = _authorized_raw_evidence(
            evidence,
            grants=grant_objects,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            now=resolved_now,
        )
        authorized_raw_results = _authorized_raw_results(
            results,
            grants=grant_objects,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            now=resolved_now,
        )
        raw_sources = results if fallback_used else evidence
        authorized_raw_sources = (
            authorized_raw_results if fallback_used else authorized_raw_evidence
        )
        if mode == "raw_asset" and raw_sources and not authorized_raw_sources:
            audit = self._audit(
                actor_user_id=requester_user_id,
                action="retrieval_denied",
                target_id=workspace_id,
                workspace_id=workspace_id,
                session_id=session_id,
                status="permission_denied",
                metadata={"reason": "raw_asset_scope_not_authorized"},
            )
            trace = _retrieval_trace(
                requester_user_id=requester_user_id,
                query_text=query_text,
                mode=mode,
                matched_vector_ids=[result.record.vector_id for result in results],
                matched_graph_object_ids=[hit.graph_object_id for hit in graph_hits],
                visible_node_ids=[node.node_id for node in graph_view.visible_nodes],
                fallback_used=fallback_used,
                audit_log_id=audit.audit_log_id if audit else None,
            )
            return RetrievalGatewayResult(
                status="permission_denied",
                mode=mode,
                retrieval_trace=trace,
                audit_log_id=audit.audit_log_id if audit else None,
                warnings=["raw_asset_scope_not_authorized"],
            )
        audit = self._audit(
            actor_user_id=requester_user_id,
            action="retrieval_succeeded",
            target_id=workspace_id,
            workspace_id=workspace_id,
            session_id=session_id,
            status="ok",
            metadata={
                "mode": mode,
                "graph_hit_count": len(graph_hits),
                "fallback_used": fallback_used,
                "result_count": len(results),
            },
        )
        trace = _retrieval_trace(
            requester_user_id=requester_user_id,
            query_text=query_text,
            mode=mode,
            matched_vector_ids=[result.record.vector_id for result in results],
            matched_graph_object_ids=[hit.graph_object_id for hit in graph_hits],
            visible_node_ids=[node.node_id for node in graph_view.visible_nodes],
            fallback_used=fallback_used,
            audit_log_id=audit.audit_log_id if audit else None,
        )
        graph_evidence_snippets = _graph_evidence_snippets(evidence)
        return RetrievalGatewayResult(
            status="ok",
            mode=mode,
            answer=(
                _answer_from_graph_hits(graph_hits, evidence)
                if mode == "answer_only" and not fallback_used
                else _answer_only_mode(results)
                if mode == "answer_only"
                else None
            ),
            evidence_snippets=(
                [*graph_evidence_snippets, *_evidence_snippet_mode(results)]
                if mode == "evidence_snippet"
                else []
            ),
            raw_asset_refs=(
                _graph_raw_asset_refs(graph_hits, authorized_raw_evidence)
                if mode == "raw_asset" and not fallback_used
                else _raw_asset_mode(
                    authorized_raw_results,
                    raw_asset_resolver=self.raw_asset_resolver,
                )
                if mode == "raw_asset"
                else []
            ),
            visible_graph_snippets=_graph_hit_snippets(graph_hits),
            graph_hits=[hit.to_dict() for hit in graph_hits],
            evidence=[context.to_dict() for context in evidence],
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            evidence_coverage=evidence_coverage,
            candidate_graph_proposal_seeds=[seed.to_dict() for seed in proposal_seeds],
            retrieval_trace=trace,
            audit_log_id=audit.audit_log_id if audit else None,
            warnings=([fallback_reason] if fallback_reason else []),
        )

    def query_effective_graph_view(self, **kwargs: Any) -> RetrievalGatewayResult:
        if kwargs.get("effective_graph_view") is None:
            raise ContractValidationError("effective_graph_view is required")
        return self._query_effective_graph(**kwargs)

    def _projection_graph_view(
        self,
        *,
        requester_user_id: str,
        grants: Sequence[Grant],
        now: str,
    ) -> EffectiveGraphView:
        return EffectiveGraphView(
            requester_user_id=requester_user_id,
            user_graph_revision_id="projection_compat_user_graph",
            canonical_graph_revision_id="projection_compat_canonical_graph",
            ontology_revision_id="projection_compat_ontology",
            assembly_policy_id="projection_compat_policy",
            visible_nodes=self._visible_nodes(
                requester_user_id=requester_user_id,
                grants=grants,
                now=now,
            ),
        )

    def _resolve_evidence(
        self,
        graph_hits: Sequence[GraphHit],
        *,
        requester_user_id: str,
        grants: Sequence[Grant],
        now: str,
    ) -> tuple[list[EvidenceContext], list[str]]:
        observation_ids = sorted(
            {observation_id for hit in graph_hits for observation_id in hit.source_observation_ids}
        )
        if not observation_ids:
            return [], []
        if self.evidence_resolver is None:
            return [], observation_ids
        return self.evidence_resolver.resolve(
            observation_ids,
            requester_user_id=requester_user_id,
            grants=grants,
            now=now,
        )

    def _resolve_fallback_seed_evidence(
        self,
        results: Sequence[VectorSearchResult],
        *,
        requester_user_id: str,
        grants: Sequence[Grant],
        now: str,
    ) -> list[EvidenceContext]:
        if self.evidence_resolver is None:
            return []
        observation_ids = sorted(
            {
                result.record.source_id
                for result in results
                if result.record.source_type == "observation"
            }
        )
        if not observation_ids:
            return []
        resolved, _ = self.evidence_resolver.resolve(
            observation_ids,
            requester_user_id=requester_user_id,
            grants=grants,
            now=now,
        )
        return resolved

    def _visible_nodes(
        self,
        *,
        requester_user_id: str,
        grants: Sequence[Grant],
        now: str,
    ) -> list[GraphProjectionNode]:
        if self.graph_projection_store is None:
            return []
        return self.graph_projection_store.visible_nodes(
            requester_user_id=requester_user_id,
            grants=list(grants),
            allow_stale=False,
            now=now,
        )

    def _audit(
        self,
        *,
        actor_user_id: str,
        action: str,
        target_id: str,
        workspace_id: str,
        session_id: str,
        status: str,
        metadata: dict[str, Any],
    ) -> AuditLog | None:
        if self.audit_store is None:
            return None
        return write_audit_log(
            self.audit_store,
            actor_user_id=actor_user_id,
            action=action,
            target_type="retrieval_gateway",
            target_id=target_id,
            session_id=session_id,
            workspace_id=workspace_id,
            status=status,
            metadata=metadata,
        )


def _answer_only_mode(results: Sequence[VectorSearchResult]) -> str:
    if not results:
        return "No visible evidence matched the request."
    labels = [
        str(result.record.metadata.get("answer_summary", result.record.source_id))
        for result in results
    ]
    return "Visible evidence: " + "; ".join(labels)


def _evidence_snippet_mode(results: Sequence[VectorSearchResult]) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    for result in results:
        metadata = result.record.metadata
        snippets.append(
            _sanitize_public_dict(
                {
                    "source_type": result.record.source_type,
                    "source_id": result.record.source_id,
                    "score": round(result.score, 6),
                    "snippet": metadata.get("evidence_snippet", metadata.get("answer_summary", "")),
                }
            )
        )
    return snippets


def _raw_asset_mode(
    results: Sequence[VectorSearchResult],
    *,
    raw_asset_resolver: RawAssetLocatorResolver,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for result in results:
        try:
            resolved_refs = raw_asset_resolver.resolve_raw_asset_refs(result)
        except Exception:
            refs.append(_raw_asset_ref(result, warning="raw_asset_resolver_failed"))
            continue
        sanitized_refs = [_raw_asset_ref(result, ref) for ref in resolved_refs]
        refs.extend(sanitized_refs or [_raw_asset_ref(result, warning="asset_locator_unavailable")])
    _assert_public_payload(refs)
    return refs


def _raw_asset_ref(
    result: VectorSearchResult,
    ref: dict[str, Any] | None = None,
    *,
    warning: str | None = None,
) -> dict[str, Any]:
    asset_locator = _safe_formowl_asset_locator((ref or {}).get("asset_locator"))
    payload = {
        "source_type": result.record.source_type,
        "source_id": result.record.source_id,
        "asset_locator": asset_locator,
        "access": "explicit_grant_required",
        "content_returned": False,
    }
    if warning is not None:
        payload["warnings"] = [warning]
    if asset_locator is None and warning is None:
        payload["warnings"] = ["asset_locator_redacted"]
    _assert_public_payload(payload)
    return payload


def _safe_formowl_asset_locator(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    locator = value.strip()
    if not _FORMOWL_ASSET_LOCATOR.fullmatch(locator):
        return None
    return locator


def _graph_hit_snippets(hits: Sequence[GraphHit]) -> list[dict[str, Any]]:
    return [
        _sanitize_public_dict(
            {
                "node_id": hit.graph_object_id,
                "labels": [hit.object_type],
                "properties": {
                    "label": hit.label,
                    "score": hit.score,
                    "confidence": hit.confidence,
                    "review_state": hit.review_state,
                    "source_observation_ids": hit.source_observation_ids,
                    "source_asset_ids": hit.source_asset_ids,
                    "evidence_locators": hit.evidence_locators,
                },
            }
        )
        for hit in hits
    ]


def _attach_evidence_locators(
    hits: Sequence[GraphHit],
    evidence: Sequence[EvidenceContext],
) -> list[GraphHit]:
    context_by_observation_id = {context.observation_id: context for context in evidence}
    return [
        replace(
            hit,
            source_observation_ids=[
                observation_id
                for observation_id in hit.source_observation_ids
                if observation_id in context_by_observation_id
            ],
            source_asset_ids=sorted(
                {
                    str(context_by_observation_id[observation_id].asset_id)
                    for observation_id in hit.source_observation_ids
                    if observation_id in context_by_observation_id
                    and context_by_observation_id[observation_id].asset_id is not None
                }
            ),
            evidence_locators=[
                context_by_observation_id[observation_id].evidence_locator
                for observation_id in hit.source_observation_ids
                if observation_id in context_by_observation_id
            ],
        )
        for hit in hits
    ]


def _filter_evidence_by_graph_lineage(
    hits: Sequence[GraphHit],
    evidence: Sequence[EvidenceContext],
) -> tuple[list[EvidenceContext], list[str]]:
    declared_assets_by_observation: dict[str, list[set[str]]] = {}
    for hit in hits:
        declared_assets = set(hit.source_asset_ids)
        for observation_id in hit.source_observation_ids:
            declared_assets_by_observation.setdefault(observation_id, []).append(declared_assets)
    verified: list[EvidenceContext] = []
    mismatched: list[str] = []
    for context in evidence:
        declared_asset_sets = declared_assets_by_observation.get(context.observation_id, [])
        if (
            context.asset_id is not None
            and declared_asset_sets
            and all(context.asset_id in asset_ids for asset_ids in declared_asset_sets)
        ):
            verified.append(context)
        else:
            mismatched.append(context.observation_id)
    return verified, sorted(set(mismatched))


def _fallback_reason(
    hits: Sequence[GraphHit],
    *,
    evidence: Sequence[EvidenceContext],
    unresolved_observation_ids: Sequence[str],
    evidence_coverage: float,
    graph_confidence_threshold: float,
    minimum_evidence_count: int,
) -> str | None:
    if not hits:
        return "graph_miss_fallback_used"
    if max(hit.confidence for hit in hits) < graph_confidence_threshold:
        return "graph_confidence_insufficient_fallback_used"
    if unresolved_observation_ids or evidence_coverage < 1.0:
        return "graph_evidence_incomplete_fallback_used"
    if len(evidence) < minimum_evidence_count:
        return "graph_evidence_count_insufficient_fallback_used"
    return None


def _graph_evidence_snippets(evidence: Sequence[EvidenceContext]) -> list[dict[str, Any]]:
    return [
        _sanitize_public_dict(
            {
                "source_type": "observation",
                "source_id": context.observation_id,
                "score": round(context.confidence, 6),
                "snippet": context.snippet,
                "evidence_locator": context.evidence_locator,
            }
        )
        for context in evidence
    ]


def _answer_from_graph_hits(
    hits: Sequence[GraphHit],
    evidence: Sequence[EvidenceContext],
) -> str:
    labels = "; ".join(hit.label for hit in hits[:3])
    return f"KG-first evidence matched {len(hits)} graph object(s) and {len(evidence)} observation(s): {labels}"


def _graph_raw_asset_refs(
    hits: Sequence[GraphHit],
    evidence: Sequence[EvidenceContext],
) -> list[dict[str, Any]]:
    context_by_observation_id = {context.observation_id: context for context in evidence}
    refs = [
        {
            "source_type": "graph_object",
            "source_id": hit.graph_object_id,
            "asset_locator": f"formowl://asset/{context.asset_id}",
            "access": "explicit_grant_required",
            "content_returned": False,
        }
        for hit in hits
        for observation_id in hit.source_observation_ids
        if (context := context_by_observation_id.get(observation_id)) is not None
        and context.asset_id is not None
    ]
    unique_refs = {(str(ref["source_id"]), str(ref["asset_locator"])): ref for ref in refs}
    refs = [unique_refs[key] for key in sorted(unique_refs)]
    _assert_public_payload(refs)
    return refs


def _normalize_grants(grants: Sequence[Grant | dict[str, Any]]) -> list[Grant]:
    normalized: list[Grant] = []
    for grant in grants:
        normalized.append(grant if isinstance(grant, Grant) else Grant.from_dict(grant))
    return normalized


def _has_raw_asset_access_grant(
    grants: Sequence[Grant],
    *,
    requester_user_id: str,
    now: str,
) -> bool:
    for grant in grants:
        if grant.grantee_user_id != requester_user_id:
            continue
        if grant.permission != _RAW_ASSET_GRANT_PERMISSION:
            continue
        if grant.revoked_at:
            continue
        if _grant_expired(grant, now):
            continue
        return True
    return False


def _authorized_raw_evidence(
    evidence: Sequence[EvidenceContext],
    *,
    grants: Sequence[Grant],
    requester_user_id: str,
    workspace_id: str,
    now: str,
) -> list[EvidenceContext]:
    return [
        context
        for context in evidence
        if any(
            _raw_grant_allows_target(
                grant,
                requester_user_id=requester_user_id,
                workspace_id=workspace_id,
                permission_scope=context.permission_scope,
                asset_id=context.asset_id,
                now=now,
            )
            for grant in grants
        )
    ]


def _authorized_raw_results(
    results: Sequence[VectorSearchResult],
    *,
    grants: Sequence[Grant],
    requester_user_id: str,
    workspace_id: str,
    now: str,
) -> list[VectorSearchResult]:
    return [
        result
        for result in results
        if any(
            _raw_grant_allows_target(
                grant,
                requester_user_id=requester_user_id,
                workspace_id=workspace_id,
                permission_scope=result.record.permission_scope,
                asset_id=None,
                now=now,
            )
            for grant in grants
        )
    ]


def _raw_grant_allows_target(
    grant: Grant,
    *,
    requester_user_id: str,
    workspace_id: str,
    permission_scope: dict[str, Any],
    asset_id: str | None,
    now: str,
) -> bool:
    if grant.grantee_user_id != requester_user_id:
        return False
    if grant.permission != _RAW_ASSET_GRANT_PERMISSION:
        return False
    if grant.revoked_at or _grant_expired(grant, now):
        return False
    if grant.scope_type == "workspace":
        return grant.scope_id == workspace_id
    if grant.scope_type == "asset":
        return asset_id is not None and grant.scope_id == asset_id
    return grant.scope_type == permission_scope.get(
        "scope_type"
    ) and grant.scope_id == permission_scope.get("scope_id")


def _grant_expired(grant: Grant, now: str) -> bool:
    try:
        from datetime import datetime

        expires = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        return True
    return expires <= current


def _retrieval_trace(
    *,
    requester_user_id: str,
    query_text: str,
    mode: RetrievalMode,
    matched_vector_ids: list[str] | None = None,
    matched_graph_object_ids: list[str] | None = None,
    visible_node_ids: list[str] | None = None,
    fallback_used: bool = False,
    audit_log_id: str | None = None,
) -> RetrievalTrace:
    query_hash = _simple_hash(query_text)
    return RetrievalTrace(
        retrieval_trace_id=f"retrieval_trace_{query_hash[:24]}",
        requester_user_id=requester_user_id,
        query_hash=query_hash,
        mode=mode,
        matched_vector_ids=matched_vector_ids or [],
        matched_graph_object_ids=matched_graph_object_ids or [],
        visible_node_ids=visible_node_ids or [],
        fallback_used=fallback_used,
        audit_log_id=audit_log_id,
    )


def _simple_hash(value: str) -> str:
    from hashlib import sha256

    return sha256(value.encode("utf-8")).hexdigest()


def _validate_query_inputs(
    *,
    query_text: str,
    requester_user_id: str,
    workspace_id: str,
    session_id: str,
    mode: str,
    limit: int,
) -> None:
    for field_name, value in (
        ("query_text", query_text),
        ("requester_user_id", requester_user_id),
        ("workspace_id", workspace_id),
        ("session_id", session_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(f"{field_name} is required")
    if mode not in _RETRIEVAL_MODES:
        raise ContractValidationError("mode must be answer_only, evidence_snippet, or raw_asset")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ContractValidationError("limit must be a non-negative integer")


def _sanitize_public_dict(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if str(key).lower() in _FORBIDDEN_PUBLIC_KEYS:
            continue
        if isinstance(value, dict):
            nested = _sanitize_public_dict(value)
            if nested:
                sanitized[str(key)] = nested
        elif isinstance(value, list):
            sanitized[str(key)] = [
                item
                for item in (_sanitize_public_value(entry) for entry in value)
                if item is not None
            ]
        else:
            cleaned = _sanitize_public_value(value)
            if cleaned is not None or value is None:
                sanitized[str(key)] = cleaned
    _assert_public_payload(sanitized)
    return sanitized


def _sanitize_public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _sanitize_public_dict(value)
    if isinstance(value, str) and _safe_formowl_public_locator(value):
        return value
    if isinstance(value, str) and _FORBIDDEN_PUBLIC_VALUE.search(value):
        return None
    return value


def _safe_formowl_public_locator(value: str) -> bool:
    return bool(
        _FORMOWL_ASSET_LOCATOR.fullmatch(value) or _FORMOWL_OBSERVATION_LOCATOR.fullmatch(value)
    )


def _permission_filter_effective_graph_view(
    view: EffectiveGraphView,
    *,
    requester_user_id: str,
    grants: Sequence[Grant | dict[str, Any]],
    now: str,
) -> EffectiveGraphView:
    visible_nodes = [
        node
        for node in view.visible_nodes
        if node.projection_state == "ready"
        and _graph_object_safe_for_public_retrieval(node)
        and requester_has_graph_access(
            node.permission_scope,
            requester_user_id=requester_user_id,
            grants=list(grants),
            now=now,
        )
    ]
    visible_node_ids = {node.node_id for node in visible_nodes}
    visible_edges: list[GraphProjectionEdge] = [
        edge
        for edge in view.visible_edges
        if edge.projection_state == "ready"
        and _graph_object_safe_for_public_retrieval(edge)
        and edge.source_node_id in visible_node_ids
        and edge.target_node_id in visible_node_ids
        and requester_has_graph_access(
            edge.permission_scope,
            requester_user_id=requester_user_id,
            grants=list(grants),
            now=now,
        )
    ]
    return replace(
        view,
        visible_nodes=sorted(visible_nodes, key=lambda node: node.node_id),
        visible_edges=sorted(visible_edges, key=lambda edge: edge.edge_id),
        access_required=[],
        applied_grant_ids=[],
    )


def _graph_object_safe_for_public_retrieval(value: Any) -> bool:
    try:
        _assert_public_payload(value.to_dict())
    except ContractValidationError:
        return False
    return True


def _assert_public_payload(payload: object) -> None:
    violations: list[str] = []

    def walk(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                if key_text.lower() in _FORBIDDEN_PUBLIC_KEYS:
                    violations.append(f"forbidden public key: {path}.{key_text}")
                walk(item, f"{path}.{key_text}" if path else key_text)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif (
            isinstance(value, str)
            and not _safe_formowl_public_locator(value)
            and _FORBIDDEN_PUBLIC_VALUE.search(value)
        ):
            violations.append(f"forbidden public value: {path}")

    walk(payload, "")
    if violations:
        raise ContractValidationError("; ".join(violations))
