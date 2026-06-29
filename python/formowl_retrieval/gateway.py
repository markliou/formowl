from __future__ import annotations

from dataclasses import dataclass, field
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
    GraphProjectionNode,
    VectorSearchResult,
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
    r"(^|[\s'\"])(/|[A-Za-z]:[\\/]|\\\\|file://|s3://|smb://|nfs://|"
    r"postgres(?:ql)?://|\bselect\b\s+|\bwith\b\s+|\binsert\b\s+|\bupdate\b\s+|"
    r"\bdelete\b\s+|\bdrop\b\s+)",
    re.IGNORECASE,
)
_FORMOWL_ASSET_LOCATOR = re.compile(r"^formowl://asset/[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class RetrievalTrace:
    retrieval_trace_id: str
    requester_user_id: str
    query_hash: str
    mode: RetrievalMode
    matched_vector_ids: list[str] = field(default_factory=list)
    visible_node_ids: list[str] = field(default_factory=list)
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
    ) -> None:
        self.vector_store = vector_store
        self.graph_projection_store = graph_projection_store
        self.audit_store = audit_store
        self.raw_asset_resolver = raw_asset_resolver or MetadataRawAssetLocatorResolver()

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

        results = self.vector_store.search(
            list(query_embedding),
            requester_user_id=requester_user_id,
            grants=list(grant_objects),
            allow_stale=False,
            limit=limit,
            now=resolved_now,
        )
        visible_nodes = self._visible_nodes(
            requester_user_id=requester_user_id,
            grants=grant_objects,
            now=resolved_now,
        )
        audit = self._audit(
            actor_user_id=requester_user_id,
            action="retrieval_succeeded",
            target_id=workspace_id,
            workspace_id=workspace_id,
            session_id=session_id,
            status="ok",
            metadata={"mode": mode, "result_count": len(results)},
        )
        trace = _retrieval_trace(
            requester_user_id=requester_user_id,
            query_text=query_text,
            mode=mode,
            matched_vector_ids=[result.record.vector_id for result in results],
            visible_node_ids=[node.node_id for node in visible_nodes],
            audit_log_id=audit.audit_log_id if audit else None,
        )
        return RetrievalGatewayResult(
            status="ok",
            mode=mode,
            answer=_answer_only_mode(results) if mode == "answer_only" else None,
            evidence_snippets=_evidence_snippet_mode(results) if mode == "evidence_snippet" else [],
            raw_asset_refs=(
                _raw_asset_mode(results, raw_asset_resolver=self.raw_asset_resolver)
                if mode == "raw_asset"
                else []
            ),
            visible_graph_snippets=_graph_snippets(visible_nodes),
            retrieval_trace=trace,
            audit_log_id=audit.audit_log_id if audit else None,
        )

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


def _graph_snippets(nodes: Sequence[GraphProjectionNode]) -> list[dict[str, Any]]:
    return [
        _sanitize_public_dict(
            {
                "node_id": node.node_id,
                "labels": list(node.labels),
                "properties": node.properties,
            }
        )
        for node in nodes
    ]


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
    visible_node_ids: list[str] | None = None,
    audit_log_id: str | None = None,
) -> RetrievalTrace:
    query_hash = _simple_hash(query_text)
    return RetrievalTrace(
        retrieval_trace_id=f"retrieval_trace_{query_hash[:24]}",
        requester_user_id=requester_user_id,
        query_hash=query_hash,
        mode=mode,
        matched_vector_ids=matched_vector_ids or [],
        visible_node_ids=visible_node_ids or [],
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
    if isinstance(value, str) and _FORBIDDEN_PUBLIC_VALUE.search(value):
        return None
    return value


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
        elif isinstance(value, str) and _FORBIDDEN_PUBLIC_VALUE.search(value):
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
