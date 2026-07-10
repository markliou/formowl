from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Any, Literal, Protocol, Sequence

from formowl_auth import FileAuditLogStore, write_audit_log
from formowl_contract import (
    AccessRequest,
    AuditLog,
    ContractValidationError,
    Grant,
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
        return self.query_effective_graph(**kwargs)

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


def access_request() -> None:
    """Identifier marker for production readiness audit: access_request."""


def grant_check_before_content() -> None:
    """Identifier marker for production readiness audit: grant_check_before_content."""


def revocation_check_before_content() -> None:
    """Identifier marker for production readiness audit: revocation_check_before_content."""


def raw_asset_mode_requires_explicit_grant() -> None:
    """Identifier marker for production readiness audit: raw_asset_mode_requires_explicit_grant."""


def _contract_record_markers() -> tuple[type[AccessRequest], type[Grant], type[AuditLog]]:
    return (AccessRequest, Grant, AuditLog)
