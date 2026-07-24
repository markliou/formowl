from __future__ import annotations

from dataclasses import dataclass, field
import multiprocessing
import re
import sys
import threading
from time import perf_counter
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping, Sequence
import unicodedata

from formowl_contract import (
    ContractValidationError,
    Grant,
    sha256_json,
    to_plain,
)
from formowl_core import (
    configured_mail_candidate_admission_tokens,
    configured_mail_tokenizer_id,
)

from ._access import grant_expired, matching_bundles, normalize_grants
from ._guards import (
    assert_authorized_evidence_payload_safe,
    assert_public_payload_safe,
    redact_authorized_evidence_text,
    safe_public_string,
)
from .bundle import MailEvidenceBundle

MAIL_TOKENIZER_ID = configured_mail_tokenizer_id()
_MAIL_EVIDENCE_PERMISSIONS = {"read", "evidence_snippet", "mail_evidence_read"}
_PROTECTED_IDENTIFIER_TOKEN = re.compile(r"(?=.{5,}\Z)(?=.*\d)[a-z0-9_@.-]+\Z")
_TYPED_NUMERIC_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]{2,5}[\s#:_-]*([0-9]{8,})(?![0-9])"
)
_SourceItemKey = tuple[str, str, str]
_SourceItemIdentity = _SourceItemKey | str
_MAX_INDEX_WORKERS = 4
_PARALLEL_INDEX_TASKS_PER_WORKER = 32
_PARALLEL_INDEX_BUILD_LOCK = threading.Lock()
_PARALLEL_INDEX_BUNDLE: MailEvidenceBundle | None = None
_PARALLEL_INDEX_MESSAGES_BY_ID: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class MailEvidenceQueryResult:
    status: str
    mail_import_session_id: str | None
    query_hash: str
    evidence_snippets: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    redaction_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    evidence_completeness: str = "unknown"
    answerability_state: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_authorized_evidence_payload_safe(
            payload,
            "mail_evidence_query_result",
        )
        return payload


@dataclass(frozen=True)
class MailEvidenceReadResult:
    status: str
    mail_import_session_id: str | None
    evidence_segments: list[dict[str, Any]] = field(default_factory=list)
    redaction_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    evidence_completeness: str = "unknown"
    answerability_state: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_authorized_evidence_payload_safe(
            payload,
            "mail_evidence_read_result",
        )
        return payload


@dataclass(frozen=True)
class _IndexedMailSnippet:
    mail_evidence_bundle_id: str
    source_item_id: str
    searchable_tokens: frozenset[str]
    payload: dict[str, Any]
    source_item_key: _SourceItemKey | None = None


@dataclass(frozen=True)
class _MailSnippetIndex:
    snippets: tuple[_IndexedMailSnippet, ...]
    snippet_indexes_by_token: Mapping[str, tuple[int, ...]]
    source_item_ids_by_token: Mapping[str, frozenset[_SourceItemIdentity]] = field(
        default_factory=dict
    )
    snippet_indexes_by_source_item_id: Mapping[
        _SourceItemIdentity,
        tuple[int, ...],
    ] = field(default_factory=dict)
    subject_by_source_item_id: Mapping[_SourceItemIdentity, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _RequiredTermAlternative:
    normalized_text: str
    anchor_tokens: frozenset[str]


@dataclass(frozen=True)
class _RequiredTermSpec:
    display_text: str
    alternatives: tuple[_RequiredTermAlternative, ...]


@dataclass(frozen=True)
class _RequiredTermMatch:
    display_text: str
    normalized_alternatives: tuple[str, ...]
    snippet_index: int


@dataclass(frozen=True)
class _MailEvidenceQueryExecution:
    result: MailEvidenceQueryResult
    verified_source_item_keys: frozenset[_SourceItemIdentity] | None
    timings_ms: dict[str, float]

    @property
    def verified_source_item_ids(self) -> frozenset[str] | None:
        """Compatibility projection of the namespaced internal identities."""

        if self.verified_source_item_keys is None:
            return None
        return frozenset(
            source_item_key[2] if isinstance(source_item_key, tuple) else source_item_key
            for source_item_key in self.verified_source_item_keys
        )


@dataclass(frozen=True)
class _MailSnippetSearch:
    snippets: list[dict[str, Any]]
    bundle_ids: tuple[str, ...]
    posting_retrieval_ms: float
    ranking_ms: float


_SUBJECT_REQUIRED_TERM_MATCH = -1


class MailEvidenceQueryGateway:
    """Permission-checked query facade over normalized mail evidence bundles."""

    def __init__(
        self,
        bundles: Sequence[MailEvidenceBundle],
        *,
        index_worker_count: int = 1,
    ) -> None:
        requested_worker_count = _validated_index_worker_count(index_worker_count)
        self._bundles = list(bundles)
        build_started = perf_counter()
        worker_counts: list[int] = []
        snippet_indexes: dict[str, _MailSnippetIndex] = {}
        for bundle in self._bundles:
            worker_count = _effective_index_worker_count(
                requested_worker_count,
                segment_count=len(bundle.body_segments),
            )
            worker_counts.append(worker_count)
            if worker_count == 1:
                snippet_index = _build_snippet_index(bundle)
            else:
                snippet_index = _build_snippet_index(
                    bundle,
                    worker_count=worker_count,
                )
            snippet_indexes[bundle.mail_evidence_bundle_id] = snippet_index
        self._snippet_index_by_bundle_id = snippet_indexes
        self.index_build_elapsed_ms = round(
            (perf_counter() - build_started) * 1000.0,
            3,
        )
        self.index_worker_count = max(worker_counts, default=1)
        self.index_build_mode = "multiprocess" if self.index_worker_count > 1 else "single_process"

    @property
    def mail_evidence_bundle_ids(self) -> tuple[str, ...]:
        return tuple(bundle.mail_evidence_bundle_id for bundle in self._bundles)

    def query_mail_evidence(
        self,
        *,
        query_text: str,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
        grants: Sequence[Grant | dict[str, Any]] = (),
        limit: int = 5,
        now: str | None = None,
    ) -> MailEvidenceQueryResult:
        return self.execute_mail_evidence_query(
            query_text=query_text,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
            grants=grants,
            limit=limit,
            now=now,
        ).result

    def execute_mail_evidence_query(
        self,
        *,
        query_text: str,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
        grants: Sequence[Grant | dict[str, Any]] = (),
        limit: int = 5,
        now: str | None = None,
        required_terms: Sequence[str] = (),
        snippet_filter_groups: Sequence[Sequence[str]] = (),
        collapse_source_items: bool = False,
    ) -> _MailEvidenceQueryExecution:
        _validate_query_inputs(
            query_text=query_text,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
            limit=limit,
        )
        query_hash = sha256_json(query_text)
        selected_bundles = matching_bundles(
            self._bundles,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
        )
        if not selected_bundles:
            result = MailEvidenceQueryResult(
                status="not_found",
                mail_import_session_id=mail_import_session_id,
                query_hash=query_hash,
                redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
                warnings=["mail_evidence_not_found"],
                evidence_completeness="unknown",
                answerability_state="source_not_found",
            )
            return _MailEvidenceQueryExecution(
                result=result,
                verified_source_item_keys=(frozenset() if required_terms else None),
                timings_ms=_zero_query_timings(),
            )

        resolved_now = now or "9999-12-31T23:59:59+00:00"
        grant_objects = normalize_grants(grants)
        visible_bundles = [
            bundle
            for bundle in selected_bundles
            if bundle.mail_import_session.workspace_id == workspace_id
            and _can_read_bundle(
                bundle,
                requester_user_id=requester_user_id,
                grants=grant_objects,
                now=resolved_now,
            )
        ]
        if not visible_bundles:
            result = MailEvidenceQueryResult(
                status="permission_denied",
                mail_import_session_id=mail_import_session_id,
                query_hash=query_hash,
                redaction_counts={
                    "hidden_bundles": len(selected_bundles),
                    "hidden_messages": sum(len(bundle.messages) for bundle in selected_bundles),
                },
                warnings=["mail_evidence_permission_denied"],
                evidence_completeness="unknown",
                answerability_state="permission_denied",
            )
            return _MailEvidenceQueryExecution(
                result=result,
                verified_source_item_keys=(frozenset() if required_terms else None),
                timings_ms=_zero_query_timings(),
            )

        # Do not derive query vocabulary, required-term postings, or business
        # filters until the effective permission boundary has been established.
        required_term_specs = _required_term_specs(required_terms)
        normalized_filter_groups = _normalized_filter_groups(snippet_filter_groups)
        source_completeness = _source_completeness(visible_bundles)
        verified_source_item_keys: frozenset[_SourceItemIdentity] | None = None
        required_matches_by_source_item: Mapping[
            _SourceItemIdentity,
            tuple[_RequiredTermMatch, ...],
        ] = MappingProxyType({})
        required_posting_ms = 0.0
        exact_verification_ms = 0.0
        if required_term_specs:
            (
                verified_source_item_keys,
                required_matches_by_source_item,
                required_posting_ms,
                exact_verification_ms,
            ) = _resolve_verified_required_source_item_ids(
                visible_bundles,
                required_term_specs=required_term_specs,
                snippet_index_by_bundle_id=self._snippet_index_by_bundle_id,
            )
        search = _search_visible_bundles_with_diagnostics(
            visible_bundles,
            query_text=query_text,
            limit=limit,
            snippet_index_by_bundle_id=self._snippet_index_by_bundle_id,
            allowed_source_item_ids=verified_source_item_keys,
            snippet_filter_groups=normalized_filter_groups,
            collapse_source_items=collapse_source_items,
        )
        snippets = search.snippets
        support_assembly_started = perf_counter()
        if required_term_specs and snippets:
            snippets = _assemble_required_term_supporting_evidence(
                snippets,
                bundle_ids=search.bundle_ids,
                matches_by_source_item=required_matches_by_source_item,
                snippet_index_by_bundle_id=self._snippet_index_by_bundle_id,
            )
        support_assembly_ms = (perf_counter() - support_assembly_started) * 1000.0
        timings_ms = {
            "posting_retrieval": round(
                required_posting_ms + search.posting_retrieval_ms,
                3,
            ),
            "exact_verification": round(exact_verification_ms, 3),
            "ranking": round(search.ranking_ms + support_assembly_ms, 3),
        }
        if not snippets:
            result = MailEvidenceQueryResult(
                status="ok",
                mail_import_session_id=(
                    visible_bundles[0].mail_import_session.mail_import_session_id
                ),
                query_hash=query_hash,
                redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
                warnings=["no_visible_mail_evidence_matched"],
                evidence_completeness=source_completeness,
                answerability_state=(
                    "target_not_found_in_complete_source"
                    if source_completeness == "complete"
                    else "source_incomplete"
                ),
            )
            return _MailEvidenceQueryExecution(
                result=result,
                verified_source_item_keys=verified_source_item_keys,
                timings_ms=timings_ms,
            )
        citations = [
            _citation_for_snippet(snippet, mail_evidence_bundle_id=bundle_id)
            for snippet, bundle_id in zip(snippets, search.bundle_ids, strict=True)
        ]
        unsafe_snippet_count = sum(bool(snippet.get("content_redacted")) for snippet in snippets)
        result = MailEvidenceQueryResult(
            status="ok",
            mail_import_session_id=visible_bundles[0].mail_import_session.mail_import_session_id,
            query_hash=query_hash,
            evidence_snippets=snippets,
            citations=citations,
            redaction_counts={
                "hidden_bundles": 0,
                "hidden_messages": 0,
                "unsafe_snippets": unsafe_snippet_count,
            },
            warnings=(["unsafe_mail_evidence_content_redacted"] if unsafe_snippet_count else []),
            evidence_completeness=_matched_evidence_completeness(snippets),
            answerability_state=(
                "evidence_found_complete"
                if _matched_evidence_completeness(snippets) == "complete"
                else "evidence_found_source_incomplete"
            ),
        )
        return _MailEvidenceQueryExecution(
            result=result,
            verified_source_item_keys=verified_source_item_keys,
            timings_ms=timings_ms,
        )

    def read_mail_evidence(
        self,
        *,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
        source_observation_ids: Sequence[str] = (),
        email_message_ids: Sequence[str] = (),
        grants: Sequence[Grant | dict[str, Any]] = (),
        limit: int | None = None,
        now: str | None = None,
    ) -> MailEvidenceReadResult:
        _validate_read_inputs(
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
            source_observation_ids=source_observation_ids,
            email_message_ids=email_message_ids,
            limit=limit,
        )
        selected_bundles = matching_bundles(
            self._bundles,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
        )
        if not selected_bundles:
            return MailEvidenceReadResult(
                status="not_found",
                mail_import_session_id=mail_import_session_id,
                warnings=["mail_evidence_not_found"],
                answerability_state="source_not_found",
            )
        resolved_now = now or "9999-12-31T23:59:59+00:00"
        grant_objects = normalize_grants(grants)
        visible_bundles = [
            bundle
            for bundle in selected_bundles
            if bundle.mail_import_session.workspace_id == workspace_id
            and _can_read_bundle(
                bundle,
                requester_user_id=requester_user_id,
                grants=grant_objects,
                now=resolved_now,
            )
        ]
        if not visible_bundles:
            return MailEvidenceReadResult(
                status="permission_denied",
                mail_import_session_id=mail_import_session_id,
                redaction_counts={
                    "hidden_bundles": len(selected_bundles),
                    "hidden_messages": sum(len(bundle.messages) for bundle in selected_bundles),
                },
                warnings=["mail_evidence_permission_denied"],
                answerability_state="permission_denied",
            )
        requested_observations = set(source_observation_ids)
        requested_messages = set(email_message_ids)
        segments: list[dict[str, Any]] = []
        for bundle in visible_bundles:
            message_by_id = {message.email_message_id: message for message in bundle.messages}
            for segment in bundle.body_segments:
                if (
                    segment.source_observation_id not in requested_observations
                    and segment.email_message_id not in requested_messages
                ):
                    continue
                message = message_by_id.get(segment.email_message_id)
                segments.append(_safe_snippet(_segment_payload(bundle, segment, message)))
        segments = sorted(
            segments,
            key=lambda item: (
                str(item["email_message_id"]),
                str(item.get("segment_source_type", "")),
                str(item.get("attachment_id", "")),
                int(item.get("body_segment_index") or 0),
                str(item["source_observation_id"]),
            ),
        )
        if not segments:
            return MailEvidenceReadResult(
                status="not_found",
                mail_import_session_id=visible_bundles[
                    0
                ].mail_import_session.mail_import_session_id,
                warnings=["requested_mail_evidence_not_found"],
                evidence_completeness=_source_completeness(visible_bundles),
                answerability_state="requested_evidence_not_found",
            )
        limit_reached = limit is not None and len(segments) > limit
        if limit is not None:
            segments = segments[:limit]
        unsafe_segment_count = sum(bool(item.get("content_redacted")) for item in segments)
        completeness = _matched_evidence_completeness(segments)
        return MailEvidenceReadResult(
            status="partial" if limit_reached else "ok",
            mail_import_session_id=visible_bundles[0].mail_import_session.mail_import_session_id,
            evidence_segments=segments,
            redaction_counts={"unsafe_segments": unsafe_segment_count},
            warnings=[
                *(["unsafe_mail_evidence_content_redacted"] if unsafe_segment_count else []),
                *(["mail_evidence_read_limit_reached"] if limit_reached else []),
            ],
            evidence_completeness="incomplete" if limit_reached else completeness,
            answerability_state=(
                "read_limit_reached"
                if limit_reached
                else (
                    "evidence_read_complete"
                    if completeness == "complete"
                    else "evidence_read_source_incomplete"
                )
            ),
        )


def build_mail_evidence_query_handler(
    bundles: Sequence[MailEvidenceBundle],
    *,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
) -> Any:
    gateway = MailEvidenceQueryGateway(bundles)
    trusted_grants = tuple(grants)

    def handler(input_data: dict[str, Any]) -> dict[str, Any]:
        result = gateway.query_mail_evidence(
            query_text=input_data.get("query_text", ""),
            requester_user_id=input_data.get("requester_user_id", ""),
            workspace_id=input_data.get("workspace_id", ""),
            session_id=input_data.get("session_id", "semantic_gateway_session"),
            mail_import_session_id=input_data.get("mail_import_session_id"),
            mail_evidence_bundle_id=input_data.get("mail_evidence_bundle_id"),
            grants=trusted_grants,
            limit=input_data.get("limit", 5),
            now=now,
        )
        return result.to_dict()

    return handler


def build_mail_evidence_read_handler(
    bundles: Sequence[MailEvidenceBundle],
    *,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
) -> Any:
    gateway = MailEvidenceQueryGateway(bundles)
    trusted_grants = tuple(grants)

    def handler(input_data: dict[str, Any]) -> dict[str, Any]:
        result = gateway.read_mail_evidence(
            requester_user_id=input_data.get("requester_user_id", ""),
            workspace_id=input_data.get("workspace_id", ""),
            session_id=input_data.get("session_id", "semantic_gateway_session"),
            mail_import_session_id=input_data.get("mail_import_session_id"),
            mail_evidence_bundle_id=input_data.get("mail_evidence_bundle_id"),
            source_observation_ids=input_data.get("source_observation_ids", ()),
            email_message_ids=input_data.get("email_message_ids", ()),
            grants=trusted_grants,
            limit=input_data.get("limit"),
            now=now,
        )
        return result.to_dict()

    return handler


def _search_visible_bundles(
    bundles: Sequence[MailEvidenceBundle],
    *,
    query_text: str,
    limit: int | None,
    snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex] | None = None,
) -> list[dict[str, Any]]:
    return _search_visible_bundles_with_diagnostics(
        bundles,
        query_text=query_text,
        limit=limit,
        snippet_index_by_bundle_id=snippet_index_by_bundle_id,
    ).snippets


def _search_visible_bundles_with_diagnostics(
    bundles: Sequence[MailEvidenceBundle],
    *,
    query_text: str,
    limit: int | None,
    snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex] | None = None,
    allowed_source_item_ids: frozenset[_SourceItemIdentity] | None = None,
    snippet_filter_groups: tuple[tuple[str, ...], ...] = (),
    collapse_source_items: bool = False,
) -> _MailSnippetSearch:
    terms = _indexable_tokens(query_text)
    posting_started = perf_counter()
    matched: list[tuple[_IndexedMailSnippet, tuple[str, ...]]] = []
    matched_by_source_item_id: dict[
        _SourceItemIdentity,
        tuple[_IndexedMailSnippet, tuple[str, ...]],
    ] = {}
    for bundle in bundles:
        if snippet_index_by_bundle_id is None:
            snippet_index = _build_snippet_index(bundle)
        else:
            snippet_index = snippet_index_by_bundle_id.get(bundle.mail_evidence_bundle_id)
            if snippet_index is None:
                snippet_index = _build_snippet_index(bundle)
        candidate_indexes = _candidate_snippet_indexes(
            snippet_index,
            terms,
            allowed_source_item_ids=allowed_source_item_ids,
        )
        for snippet_index_value in candidate_indexes:
            indexed = snippet_index.snippets[snippet_index_value]
            if (
                allowed_source_item_ids is not None
                and _indexed_source_item_identity(indexed) not in allowed_source_item_ids
            ):
                continue
            matched_terms = tuple(
                sorted(term for term in terms if term in indexed.searchable_tokens)
            )
            if not matched_terms:
                continue
            if snippet_filter_groups and not _payload_matches_filter_groups(
                indexed.payload,
                snippet_filter_groups,
            ):
                continue
            candidate = (indexed, matched_terms)
            if not collapse_source_items:
                matched.append(candidate)
                continue
            source_item_identity = _indexed_source_item_identity(indexed)
            current = matched_by_source_item_id.get(source_item_identity)
            if current is None or _matched_snippet_preference(candidate) > (
                _matched_snippet_preference(current)
            ):
                matched_by_source_item_id[source_item_identity] = candidate
    if collapse_source_items:
        matched = list(matched_by_source_item_id.values())
    posting_retrieval_ms = (perf_counter() - posting_started) * 1000.0

    ranking_started = perf_counter()
    ranked = sorted(
        matched,
        key=lambda item: (
            -len(item[1]),
            str(item[0].payload["source_observation_id"]),
        ),
    )
    if limit is not None:
        ranked = ranked[:limit]
    ranking_ms = (perf_counter() - ranking_started) * 1000.0
    snippets = [
        _safe_snippet(
            {
                **indexed.payload,
                "score": len(matched_terms),
                "matched_terms": list(matched_terms),
            }
        )
        for indexed, matched_terms in ranked
    ]
    return _MailSnippetSearch(
        snippets=snippets,
        bundle_ids=tuple(indexed.mail_evidence_bundle_id for indexed, _ in ranked),
        posting_retrieval_ms=posting_retrieval_ms,
        ranking_ms=ranking_ms,
    )


def _matched_snippet_preference(
    item: tuple[_IndexedMailSnippet, tuple[str, ...]],
) -> tuple[int, int]:
    indexed, matched_terms = item
    return (
        len(matched_terms),
        len(str(indexed.payload.get("snippet", ""))),
    )


def _assemble_required_term_supporting_evidence(
    snippets: list[dict[str, Any]],
    *,
    bundle_ids: tuple[str, ...],
    matches_by_source_item: Mapping[
        _SourceItemIdentity,
        tuple[_RequiredTermMatch, ...],
    ],
    snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex],
) -> list[dict[str, Any]]:
    assembled: list[dict[str, Any]] = []
    for primary, bundle_id in zip(snippets, bundle_ids, strict=True):
        source_item_key: _SourceItemIdentity = (
            bundle_id,
            str(primary["mail_import_session_id"]),
            str(primary["email_message_id"]),
        )
        required_term_matches = matches_by_source_item.get(source_item_key)
        if required_term_matches is None:
            # Compatibility for tests or callers that inject an older
            # bare-ID index.  Built indexes always use the namespaced key.
            required_term_matches = matches_by_source_item.get(
                str(primary["email_message_id"]),
                (),
            )
        snippet_index = snippet_index_by_bundle_id.get(bundle_id)
        if snippet_index is None or not required_term_matches:
            assembled.append(primary)
            continue

        primary_required_terms: list[str] = []
        required_terms_by_support_index: dict[int, list[str]] = {}
        for required_term_match in required_term_matches:
            support_index = required_term_match.snippet_index
            if (
                _snippet_matches_required_term(primary, required_term_match)
                or support_index == _SUBJECT_REQUIRED_TERM_MATCH
                or _indexed_snippet_is_primary(
                    snippet_index.snippets[support_index],
                    primary,
                )
            ):
                if required_term_match.display_text not in primary_required_terms:
                    primary_required_terms.append(required_term_match.display_text)
                continue
            support_terms = required_terms_by_support_index.setdefault(support_index, [])
            if required_term_match.display_text not in support_terms:
                support_terms.append(required_term_match.display_text)

        enriched_primary = dict(primary)
        if primary_required_terms:
            enriched_primary["matched_required_terms"] = primary_required_terms
        supporting_evidence: list[dict[str, Any]] = []
        for support_index, matched_required_terms in required_terms_by_support_index.items():
            indexed_support = snippet_index.snippets[support_index]
            support = _safe_snippet(
                {
                    **indexed_support.payload,
                    "matched_required_terms": matched_required_terms,
                }
            )
            support["citation"] = _citation_for_snippet(
                support,
                mail_evidence_bundle_id=bundle_id,
            )
            assert_authorized_evidence_payload_safe(
                support,
                "mail_evidence_required_term_support",
            )
            supporting_evidence.append(support)
        if supporting_evidence:
            enriched_primary["supporting_evidence"] = supporting_evidence
        assembled.append(enriched_primary)
    return assembled


def _indexed_snippet_is_primary(
    indexed: _IndexedMailSnippet,
    primary: Mapping[str, Any],
) -> bool:
    return all(
        indexed.payload.get(field_name) == primary.get(field_name)
        for field_name in (
            "source_observation_id",
            "message_occurrence_id",
            "segment_source_type",
            "attachment_id",
            "body_segment_index",
        )
    )


def _snippet_matches_required_term(
    snippet: Mapping[str, Any],
    required_term_match: _RequiredTermMatch,
) -> bool:
    normalized = _normalize_exact_text(
        " ".join(
            value
            for value in (snippet.get("subject"), snippet.get("snippet"))
            if isinstance(value, str)
        )
    )
    return any(
        alternative in normalized for alternative in required_term_match.normalized_alternatives
    )


def _payload_matches_filter_groups(
    payload: Mapping[str, Any],
    groups: tuple[tuple[str, ...], ...],
) -> bool:
    rendered = " ".join(
        value
        for value in (payload.get("subject"), payload.get("snippet"))
        if isinstance(value, str)
    ).casefold()
    rendered = _normalize_exact_text(rendered)
    return all(any(term in rendered for term in group) for group in groups)


def _candidate_snippet_indexes(
    snippet_index: _MailSnippetIndex,
    terms: set[str],
    *,
    allowed_source_item_ids: frozenset[_SourceItemIdentity] | None = None,
) -> tuple[int, ...]:
    if allowed_source_item_ids is not None and not allowed_source_item_ids:
        return ()
    identifier_anchors = {term for term in terms if _PROTECTED_IDENTIFIER_TOKEN.fullmatch(term)}
    candidate_terms = identifier_anchors or terms
    indexes: set[int] = set()
    for term in candidate_terms:
        indexes.update(snippet_index.snippet_indexes_by_token.get(term, ()))
    if allowed_source_item_ids is not None:
        allowed_indexes: set[int] = set()
        for source_item_id in allowed_source_item_ids:
            allowed_indexes.update(_source_item_indexes(snippet_index, source_item_id))
        indexes.intersection_update(allowed_indexes)
    return tuple(sorted(indexes))


def _build_snippet_index(
    bundle: MailEvidenceBundle,
    *,
    worker_count: int = 1,
) -> _MailSnippetIndex:
    resolved_worker_count = _validated_index_worker_count(worker_count)
    messages_by_id = {message.email_message_id: message for message in bundle.messages}
    if resolved_worker_count == 1:
        tokenized_segments = (
            tokenized
            for segment_index in range(len(bundle.body_segments))
            if (
                tokenized := _tokenize_segment(
                    bundle,
                    messages_by_id,
                    segment_index,
                )
            )
            is not None
        )
    else:
        tokenized_segments = _parallel_tokenized_segments(
            bundle,
            messages_by_id,
            worker_count=resolved_worker_count,
        )
    return _assemble_snippet_index(
        bundle,
        messages_by_id,
        tokenized_segments,
    )


def _assemble_snippet_index(
    bundle: MailEvidenceBundle,
    messages_by_id: Mapping[str, Any],
    tokenized_segments: Iterable[tuple[int, tuple[str, ...]]],
) -> _MailSnippetIndex:
    indexed: list[_IndexedMailSnippet] = []
    indexes_by_token: dict[str, list[int]] = {}
    source_item_ids_by_token: dict[str, set[_SourceItemKey]] = {}
    snippet_indexes_by_source_item_id: dict[_SourceItemKey, list[int]] = {}
    for segment_index, ordered_tokens in tokenized_segments:
        segment = bundle.body_segments[segment_index]
        message = messages_by_id.get(segment.email_message_id)
        tokens = frozenset(ordered_tokens)
        source_item_key = _source_item_key(bundle, segment.email_message_id)
        snippet_index = len(indexed)
        indexed.append(
            _IndexedMailSnippet(
                mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
                source_item_id=segment.email_message_id,
                searchable_tokens=frozenset(tokens),
                payload={
                    **_segment_payload(bundle, segment, message),
                },
                source_item_key=source_item_key,
            )
        )
        snippet_indexes_by_source_item_id.setdefault(
            source_item_key,
            [],
        ).append(snippet_index)
        for token in tokens:
            indexes_by_token.setdefault(token, []).append(snippet_index)
            source_item_ids_by_token.setdefault(token, set()).add(source_item_key)
    return _MailSnippetIndex(
        snippets=tuple(indexed),
        snippet_indexes_by_token=_immutable_posting_map(
            {token: tuple(indexes) for token, indexes in indexes_by_token.items()}
        ),
        source_item_ids_by_token=_immutable_posting_map(
            {
                token: frozenset(source_item_ids)
                for token, source_item_ids in source_item_ids_by_token.items()
            }
        ),
        snippet_indexes_by_source_item_id=_immutable_posting_map(
            {
                source_item_id: tuple(indexes)
                for source_item_id, indexes in snippet_indexes_by_source_item_id.items()
            }
        ),
        subject_by_source_item_id=_immutable_posting_map(
            {
                _source_item_key(bundle, message.email_message_id): message.subject or ""
                for message in bundle.messages
            }
        ),
    )


def _parallel_tokenized_segments(
    bundle: MailEvidenceBundle,
    messages_by_id: Mapping[str, Any],
    *,
    worker_count: int,
) -> Iterator[tuple[int, tuple[str, ...]]]:
    global _PARALLEL_INDEX_BUNDLE, _PARALLEL_INDEX_MESSAGES_BY_ID

    context = multiprocessing.get_context("fork")
    ranges = _parallel_index_ranges(
        len(bundle.body_segments),
        worker_count=worker_count,
    )
    with _PARALLEL_INDEX_BUILD_LOCK:
        _PARALLEL_INDEX_BUNDLE = bundle
        _PARALLEL_INDEX_MESSAGES_BY_ID = messages_by_id
        try:
            with context.Pool(processes=worker_count) as pool:
                for chunk in pool.imap(
                    _tokenize_segment_range,
                    ranges,
                    chunksize=1,
                ):
                    yield from chunk
        finally:
            _PARALLEL_INDEX_BUNDLE = None
            _PARALLEL_INDEX_MESSAGES_BY_ID = None


def _parallel_index_ranges(
    segment_count: int,
    *,
    worker_count: int,
) -> tuple[tuple[int, int], ...]:
    target_task_count = max(worker_count, worker_count * _PARALLEL_INDEX_TASKS_PER_WORKER)
    chunk_size = max(1, (segment_count + target_task_count - 1) // target_task_count)
    return tuple(
        (start, min(start + chunk_size, segment_count))
        for start in range(0, segment_count, chunk_size)
    )


def _tokenize_segment_range(
    bounds: tuple[int, int],
) -> tuple[tuple[int, tuple[str, ...]], ...]:
    bundle = _PARALLEL_INDEX_BUNDLE
    messages_by_id = _PARALLEL_INDEX_MESSAGES_BY_ID
    if bundle is None or messages_by_id is None:
        raise RuntimeError("parallel mail index worker is unavailable")
    start, stop = bounds
    rows: list[tuple[int, tuple[str, ...]]] = []
    for segment_index in range(start, stop):
        tokenized = _tokenize_segment(
            bundle,
            messages_by_id,
            segment_index,
        )
        if tokenized is not None:
            rows.append(tokenized)
    return tuple(rows)


def _tokenize_segment(
    bundle: MailEvidenceBundle,
    messages_by_id: Mapping[str, Any],
    segment_index: int,
) -> tuple[int, tuple[str, ...]] | None:
    segment = bundle.body_segments[segment_index]
    message = messages_by_id.get(segment.email_message_id)
    searchable = " ".join(
        item
        for item in (
            segment.text,
            message.subject if message else None,
            message.sender if message else None,
            message.message_id if message else None,
        )
        if isinstance(item, str)
    )
    tokens = _indexable_tokens(searchable)
    if not tokens:
        return None
    return segment_index, tuple(sorted(tokens))


def _validated_index_worker_count(value: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > _MAX_INDEX_WORKERS
    ):
        raise ContractValidationError("mail index worker count is invalid")
    return value


def _effective_index_worker_count(
    requested_worker_count: int,
    *,
    segment_count: int,
) -> int:
    if requested_worker_count == 1 or segment_count < 2:
        return 1
    if (
        sys.platform != "linux"
        or threading.current_thread() is not threading.main_thread()
        or threading.active_count() != 1
    ):
        return 1
    try:
        multiprocessing.get_context("fork")
    except ValueError:
        return 1
    return min(requested_worker_count, segment_count)


def _immutable_posting_map(
    values: dict[str, Any],
) -> Mapping[str, Any]:
    """Freeze the maps that make up the reusable query postings."""

    return MappingProxyType(values)


def _source_item_key(
    bundle: MailEvidenceBundle,
    email_message_id: str,
) -> _SourceItemKey:
    return (
        bundle.mail_evidence_bundle_id,
        bundle.mail_import_session.mail_import_session_id,
        email_message_id,
    )


def _indexed_source_item_identity(indexed: _IndexedMailSnippet) -> _SourceItemIdentity:
    return indexed.source_item_key or indexed.source_item_id


def _source_item_indexes(
    snippet_index: _MailSnippetIndex,
    source_item_identity: _SourceItemIdentity,
) -> tuple[int, ...]:
    indexes = snippet_index.snippet_indexes_by_source_item_id.get(source_item_identity)
    if indexes is not None:
        return indexes
    if isinstance(source_item_identity, tuple) and any(
        getattr(snippet, "mail_evidence_bundle_id", None) == source_item_identity[0]
        for snippet in snippet_index.snippets
    ):
        return snippet_index.snippet_indexes_by_source_item_id.get(
            source_item_identity[2],
            (),
        )
    return ()


def _canonical_source_item_identity(
    snippet_index: _MailSnippetIndex,
    source_item_identity: _SourceItemIdentity,
) -> _SourceItemIdentity:
    if isinstance(source_item_identity, tuple):
        return source_item_identity
    indexes = _source_item_indexes(snippet_index, source_item_identity)
    if indexes:
        return _indexed_source_item_identity(snippet_index.snippets[indexes[0]])
    return source_item_identity


def _source_item_subject(
    snippet_index: _MailSnippetIndex,
    source_item_identity: _SourceItemIdentity,
) -> str:
    subject = snippet_index.subject_by_source_item_id.get(source_item_identity)
    if subject is not None:
        return subject
    if isinstance(source_item_identity, tuple) and any(
        getattr(snippet, "mail_evidence_bundle_id", None) == source_item_identity[0]
        for snippet in snippet_index.snippets
    ):
        return snippet_index.subject_by_source_item_id.get(source_item_identity[2], "")
    return ""


def _required_term_specs(
    values: Sequence[str],
) -> tuple[_RequiredTermSpec, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ContractValidationError("required terms are invalid")
    if len(values) > 12:
        raise ContractValidationError("required terms are invalid")
    normalized_terms: list[str] = []
    specs: list[_RequiredTermSpec] = []
    for value in values:
        if not isinstance(value, str) or not value.strip() or len(value) > 120:
            raise ContractValidationError("required term is invalid")
        safe_public_string(value, "required_term")
        normalized = _normalize_exact_text(value).strip()
        if not normalized or normalized in normalized_terms:
            raise ContractValidationError("required terms must be unique")
        normalized_terms.append(normalized)
        alternative_values = [normalized]
        for numeric_alias in typed_numeric_identifier_aliases(normalized):
            if numeric_alias not in alternative_values:
                alternative_values.append(numeric_alias)
        alternatives = tuple(
            _RequiredTermAlternative(
                normalized_text=alternative,
                # Equivalent forms are alternatives, not additional required
                # tokens.  A typed identifier therefore may match a numeric
                # source, while a normal phrase still uses conjunctive token
                # postings.
                anchor_tokens=frozenset(_tokenize(alternative)),
            )
            for alternative in alternative_values
        )
        specs.append(
            _RequiredTermSpec(
                display_text=value.strip(),
                alternatives=alternatives,
            )
        )
    return tuple(specs)


def _normalized_filter_groups(
    groups: Sequence[Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    if isinstance(groups, (str, bytes)) or not isinstance(groups, Sequence):
        raise ContractValidationError("snippet filter groups are invalid")
    normalized_groups: list[tuple[str, ...]] = []
    for group in groups:
        if isinstance(group, (str, bytes)) or not isinstance(group, Sequence):
            raise ContractValidationError("snippet filter group is invalid")
        normalized_group: list[str] = []
        for value in group:
            if not isinstance(value, str) or not value.strip():
                raise ContractValidationError("snippet filter term is invalid")
            safe_public_string(value, "snippet_filter_term")
            normalized = _normalize_exact_text(value).strip()
            if normalized not in normalized_group:
                normalized_group.append(normalized)
        if not normalized_group:
            raise ContractValidationError("snippet filter group is invalid")
        normalized_groups.append(tuple(normalized_group))
    return tuple(normalized_groups)


def _resolve_verified_required_source_item_ids(
    bundles: Sequence[MailEvidenceBundle],
    *,
    required_term_specs: tuple[_RequiredTermSpec, ...],
    snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex],
) -> tuple[
    frozenset[_SourceItemIdentity],
    Mapping[_SourceItemIdentity, tuple[_RequiredTermMatch, ...]],
    float,
    float,
]:
    indexes_by_bundle_id: dict[str, _MailSnippetIndex] = {}
    for bundle in bundles:
        snippet_index = snippet_index_by_bundle_id.get(bundle.mail_evidence_bundle_id)
        if snippet_index is None:
            snippet_index = _build_snippet_index(bundle)
        indexes_by_bundle_id[bundle.mail_evidence_bundle_id] = snippet_index

    posting_started = perf_counter()
    candidate_ids_by_bundle: dict[str, frozenset[_SourceItemIdentity]] = {}
    for bundle in bundles:
        snippet_index = indexes_by_bundle_id[bundle.mail_evidence_bundle_id]
        candidate_ids = _required_term_candidate_source_item_ids(
            snippet_index,
            required_term_specs,
        )
        if candidate_ids:
            candidate_ids_by_bundle[bundle.mail_evidence_bundle_id] = candidate_ids
    posting_retrieval_ms = (perf_counter() - posting_started) * 1000.0

    verification_started = perf_counter()
    verified: set[_SourceItemIdentity] = set()
    matches_by_source_item: dict[
        _SourceItemIdentity,
        tuple[_RequiredTermMatch, ...],
    ] = {}
    for bundle in bundles:
        candidate_ids = candidate_ids_by_bundle.get(bundle.mail_evidence_bundle_id)
        if not candidate_ids:
            continue
        snippet_index = indexes_by_bundle_id[bundle.mail_evidence_bundle_id]
        bundle_verified, bundle_matches = _verify_required_source_item_ids(
            snippet_index,
            candidate_ids=candidate_ids,
            required_term_specs=required_term_specs,
        )
        verified.update(bundle_verified)
        matches_by_source_item.update(bundle_matches)
    exact_verification_ms = (perf_counter() - verification_started) * 1000.0
    return (
        frozenset(verified),
        MappingProxyType(matches_by_source_item),
        posting_retrieval_ms,
        exact_verification_ms,
    )


def _required_term_candidate_source_item_ids(
    snippet_index: _MailSnippetIndex,
    required_term_specs: tuple[_RequiredTermSpec, ...],
) -> frozenset[_SourceItemIdentity]:
    candidates_for_all_terms: set[_SourceItemIdentity] | None = None
    for required_term_spec in required_term_specs:
        candidates_for_term: set[_SourceItemIdentity] = set()
        for alternative in required_term_spec.alternatives:
            if not alternative.anchor_tokens:
                continue
            token_postings = [
                snippet_index.source_item_ids_by_token.get(token, frozenset())
                for token in alternative.anchor_tokens
            ]
            if any(not postings for postings in token_postings):
                continue
            # Intersect the smallest postings first.  This is both the
            # conjunctive required-term rule and the useful cost bound before
            # exact source-field verification.
            token_postings.sort(key=len)
            alternative_candidates = set(token_postings[0])
            for postings in token_postings[1:]:
                alternative_candidates.intersection_update(postings)
                if not alternative_candidates:
                    break
            candidates_for_term.update(
                _canonical_source_item_identity(snippet_index, candidate_id)
                for candidate_id in alternative_candidates
            )
        if not candidates_for_term:
            return frozenset()
        if candidates_for_all_terms is None:
            candidates_for_all_terms = candidates_for_term
        else:
            candidates_for_all_terms.intersection_update(candidates_for_term)
        if not candidates_for_all_terms:
            return frozenset()
    return frozenset(candidates_for_all_terms or ())


def _verify_required_source_item_ids(
    snippet_index: _MailSnippetIndex,
    *,
    candidate_ids: frozenset[_SourceItemIdentity],
    required_term_specs: tuple[_RequiredTermSpec, ...],
) -> tuple[
    frozenset[_SourceItemIdentity],
    Mapping[_SourceItemIdentity, tuple[_RequiredTermMatch, ...]],
]:
    verified: set[_SourceItemIdentity] = set()
    matches_by_source_item: dict[
        _SourceItemIdentity,
        tuple[_RequiredTermMatch, ...],
    ] = {}
    for source_item_id in candidate_ids:
        subject = _normalize_exact_text(_source_item_subject(snippet_index, source_item_id))
        normalized_snippets: dict[int, str] = {}
        snippet_indexes = _source_item_indexes(snippet_index, source_item_id)
        required_term_matches: list[_RequiredTermMatch] = []
        for required_term_spec in required_term_specs:
            supporting_snippet_index = _required_term_supporting_snippet_index(
                snippet_index,
                subject=subject,
                snippet_indexes=snippet_indexes,
                normalized_snippets=normalized_snippets,
                required_term_spec=required_term_spec,
            )
            if supporting_snippet_index is None:
                break
            required_term_matches.append(
                _RequiredTermMatch(
                    display_text=required_term_spec.display_text,
                    normalized_alternatives=tuple(
                        alternative.normalized_text
                        for alternative in required_term_spec.alternatives
                    ),
                    snippet_index=supporting_snippet_index,
                )
            )
        else:
            verified.add(source_item_id)
            matches_by_source_item[source_item_id] = tuple(required_term_matches)
    return frozenset(verified), MappingProxyType(matches_by_source_item)


def _source_item_matches_required_term(
    snippet_index: _MailSnippetIndex,
    *,
    subject: str,
    snippet_indexes: tuple[int, ...],
    normalized_snippets: dict[int, str],
    required_term_spec: _RequiredTermSpec,
) -> bool:
    return (
        _required_term_supporting_snippet_index(
            snippet_index,
            subject=subject,
            snippet_indexes=snippet_indexes,
            normalized_snippets=normalized_snippets,
            required_term_spec=required_term_spec,
        )
        is not None
    )


def _required_term_supporting_snippet_index(
    snippet_index: _MailSnippetIndex,
    *,
    subject: str,
    snippet_indexes: tuple[int, ...],
    normalized_snippets: dict[int, str],
    required_term_spec: _RequiredTermSpec,
) -> int | None:
    for alternative in required_term_spec.alternatives:
        if alternative.normalized_text in subject:
            return _SUBJECT_REQUIRED_TERM_MATCH
        for snippet_index_value in snippet_indexes:
            indexed = snippet_index.snippets[snippet_index_value]
            normalized_snippet = normalized_snippets.get(snippet_index_value)
            if normalized_snippet is None:
                normalized_snippet = _normalize_exact_text(str(indexed.payload.get("snippet", "")))
                normalized_snippets[snippet_index_value] = normalized_snippet
            if alternative.normalized_text in normalized_snippet:
                return snippet_index_value
    return None


def _typed_numeric_identifier_alias(value: str) -> str | None:
    normalized = _normalize_exact_text(value).strip()
    match = _TYPED_NUMERIC_IDENTIFIER_RE.fullmatch(normalized)
    return match.group(1) if match is not None else None


def typed_numeric_identifier_aliases(value: str) -> tuple[str, ...]:
    normalized = _normalize_exact_text(value)
    aliases: list[str] = []
    for match in _TYPED_NUMERIC_IDENTIFIER_RE.finditer(normalized):
        alias = match.group(1)
        if alias not in aliases:
            aliases.append(alias)
    return tuple(aliases)


def _zero_query_timings() -> dict[str, float]:
    return {
        "posting_retrieval": 0.0,
        "exact_verification": 0.0,
        "ranking": 0.0,
    }


def _segment_payload(bundle: MailEvidenceBundle, segment: Any, message: Any) -> dict[str, Any]:
    return {
        "source_type": (
            "mail_attachment_text_segment"
            if segment.segment_source_type == "attachment_text"
            else "mail_body_segment"
        ),
        "source_observation_id": segment.source_observation_id,
        "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        "email_message_id": segment.email_message_id,
        "message_occurrence_id": segment.message_occurrence_id,
        "subject": message.subject if message else None,
        "snippet": segment.text,
        "segment_source_type": segment.segment_source_type,
        "attachment_id": segment.attachment_id,
        "body_segment_index": segment.body_segment_index,
        "body_segment_count": segment.body_segment_count,
        "source_body_char_count": segment.source_body_char_count,
        "stored_body_char_count": segment.stored_body_char_count,
        "body_evidence_state": (
            segment.body_evidence_state
            if segment.body_evidence_state != "unknown"
            else (message.body_evidence_state if message else "unknown")
        ),
        "unresolved_attachment_count": (message.unresolved_attachment_count if message else 0),
    }


def _source_completeness(bundles: Sequence[MailEvidenceBundle]) -> str:
    messages = [message for bundle in bundles for message in bundle.messages]
    if not messages:
        return "unknown"
    if any(
        message.body_evidence_state != "complete"
        or message.unresolved_attachment_count > 0
        or (
            message.source_body_char_count is not None
            and message.stored_body_char_count != message.source_body_char_count
        )
        for message in messages
    ):
        return "incomplete"
    return "complete"


def _matched_evidence_completeness(snippets: Sequence[Mapping[str, Any]]) -> str:
    if not snippets:
        return "unknown"
    if any(
        snippet.get("body_evidence_state") != "complete"
        or int(snippet.get("unresolved_attachment_count") or 0) > 0
        or (
            snippet.get("source_body_char_count") is not None
            and snippet.get("stored_body_char_count") != snippet.get("source_body_char_count")
        )
        for snippet in snippets
    ):
        return "incomplete"
    return "complete"


def _safe_snippet(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: value for key, value in payload.items() if value is not None}
    redaction_count = 0
    for field_name in ("subject", "snippet"):
        value = cleaned.get(field_name)
        if not isinstance(value, str):
            continue
        redacted, field_redaction_count = _redact_mail_public_text(value)
        cleaned[field_name] = redacted
        redaction_count += field_redaction_count
    if redaction_count:
        cleaned["content_redacted"] = True
    assert_authorized_evidence_payload_safe(cleaned, "mail_evidence_snippet")
    return cleaned


def _redact_mail_public_text(value: str) -> tuple[str, int]:
    return redact_authorized_evidence_text(value)


def _citation_for_snippet(
    snippet: dict[str, Any],
    *,
    mail_evidence_bundle_id: str | None = None,
) -> dict[str, Any]:
    citation = {
        "citation_id": "mailcitation_"
        + sha256_json(
            {
                "mail_evidence_bundle_id": mail_evidence_bundle_id,
                "mail_import_session_id": snippet["mail_import_session_id"],
                "email_message_id": snippet["email_message_id"],
                "message_occurrence_id": snippet["message_occurrence_id"],
                "source_observation_id": snippet["source_observation_id"],
            }
        )[-24:],
        "source_type": snippet["source_type"],
        "source_observation_id": snippet["source_observation_id"],
        "mail_import_session_id": snippet["mail_import_session_id"],
        "email_message_id": snippet["email_message_id"],
        "message_occurrence_id": snippet["message_occurrence_id"],
    }
    assert_public_payload_safe(citation, "mail_evidence_citation")
    return citation


def _can_read_bundle(
    bundle: MailEvidenceBundle,
    *,
    requester_user_id: str,
    grants: Sequence[Grant],
    now: str,
) -> bool:
    if requester_user_id == bundle.mail_import_session.owner_user_id:
        return True
    for grant in grants:
        if grant.owner_user_id != bundle.mail_import_session.owner_user_id:
            continue
        if grant.grantee_user_id != requester_user_id:
            continue
        if grant.permission not in _MAIL_EVIDENCE_PERMISSIONS:
            continue
        if grant.revoked_at or grant_expired(grant, now):
            continue
        if (
            grant.scope_type == "workspace"
            and grant.scope_id == bundle.mail_import_session.workspace_id
        ):
            return True
        if (
            grant.scope_type == "mail_import_session"
            and grant.scope_id == bundle.mail_import_session.mail_import_session_id
        ):
            return True
    return False


def _validate_query_inputs(
    *,
    query_text: str,
    requester_user_id: str,
    workspace_id: str,
    session_id: str,
    mail_import_session_id: str | None,
    mail_evidence_bundle_id: str | None,
    limit: int,
) -> None:
    safe_public_string(query_text, "query_text")
    for field_name, value in (
        ("query_text", query_text),
        ("requester_user_id", requester_user_id),
        ("workspace_id", workspace_id),
        ("session_id", session_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(f"{field_name} is required")
        safe_public_string(value, field_name)
    if not mail_import_session_id and not mail_evidence_bundle_id:
        raise ContractValidationError(
            "mail_import_session_id or mail_evidence_bundle_id is required"
        )
    if mail_import_session_id is not None:
        safe_public_string(mail_import_session_id, "mail_import_session_id")
    if mail_evidence_bundle_id is not None:
        safe_public_string(mail_evidence_bundle_id, "mail_evidence_bundle_id")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ContractValidationError("limit must be a non-negative integer")


def _validate_read_inputs(
    *,
    requester_user_id: str,
    workspace_id: str,
    session_id: str,
    mail_import_session_id: str | None,
    mail_evidence_bundle_id: str | None,
    source_observation_ids: Sequence[str],
    email_message_ids: Sequence[str],
    limit: int,
) -> None:
    for field_name, value in (
        ("requester_user_id", requester_user_id),
        ("workspace_id", workspace_id),
        ("session_id", session_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(f"{field_name} is required")
        safe_public_string(value, field_name)
    if not mail_import_session_id and not mail_evidence_bundle_id:
        raise ContractValidationError(
            "mail_import_session_id or mail_evidence_bundle_id is required"
        )
    if not source_observation_ids and not email_message_ids:
        raise ContractValidationError("source_observation_ids or email_message_ids is required")
    for field_name, values in (
        ("source_observation_ids", source_observation_ids),
        ("email_message_ids", email_message_ids),
    ):
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ContractValidationError(f"{field_name} must be a list")
        for value in values:
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"{field_name} must contain non-empty strings")
            safe_public_string(value, field_name)
    if mail_import_session_id is not None:
        safe_public_string(mail_import_session_id, "mail_import_session_id")
    if mail_evidence_bundle_id is not None:
        safe_public_string(mail_evidence_bundle_id, "mail_evidence_bundle_id")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
        raise ContractValidationError("limit must be a positive integer")


def _tokenize(value: str) -> set[str]:
    return configured_mail_candidate_admission_tokens(value)


def _indexable_tokens(value: str) -> set[str]:
    tokens = _tokenize(_normalize_exact_text(value))
    aliases: set[str] = set()
    for token in tokens:
        if not _PROTECTED_IDENTIFIER_TOKEN.fullmatch(token):
            continue
        stripped = token.strip(".")
        if stripped and stripped != token:
            aliases.add(stripped)
        aliases.update(typed_numeric_identifier_aliases(token))
    return {*tokens, *aliases}


def _normalize_exact_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


__all__ = [
    "MailEvidenceQueryGateway",
    "MailEvidenceQueryResult",
    "MailEvidenceReadResult",
    "build_mail_evidence_query_handler",
    "build_mail_evidence_read_handler",
]
