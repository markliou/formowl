from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Sequence

from formowl_contract import (
    ContractValidationError,
    Grant,
    UserKnowledgeGraphRevision,
    to_plain,
    validate_permission_scope,
)

from .index import FileGraphProjectionStore, GraphProjectionEdge, GraphProjectionNode

_SAFE_PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RAW_REFERENCE_BOUNDARY = r"(^|[\s'\"(\[{=:,])"
_RELATIVE_PATH_PREFIXES = (
    "assets",
    "customer",
    "data",
    "docs",
    "files",
    "home",
    "mnt",
    "nas",
    "private",
    "raw",
    "root",
    "scratch",
    "secret",
    "secrets",
    "share",
    "srv",
    "tmp",
    "workspace",
)
_EFFECTIVE_VIEW_RAW_REFERENCE_PATTERNS = (
    re.compile(_RAW_REFERENCE_BOUNDARY + r"\\\\[A-Za-z0-9_.-]+\\"),
    re.compile(r"(^|[^A-Za-z])[A-Za-z]:[\\/]"),
    re.compile(_RAW_REFERENCE_BOUNDARY + r"/(?!/)(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+"),
    re.compile(
        _RAW_REFERENCE_BOUNDARY + r"(?!https?:[\\/]{2})"
        r"\.{1,2}[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*",
    ),
    re.compile(
        _RAW_REFERENCE_BOUNDARY
        + r"(?!https?:[\\/]{2})(?:"
        + "|".join(_RELATIVE_PATH_PREFIXES)
        + r")[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*",
        re.IGNORECASE,
    ),
    re.compile(
        _RAW_REFERENCE_BOUNDARY + r"(?!https?:[\\/]{2})"
        r"[A-Za-z0-9_.-]+[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*"
        r"\.[A-Za-z0-9]{2,8}\b",
    ),
    re.compile(r"\b(?!https?://)[A-Za-z][A-Za-z0-9+.-]*://", re.IGNORECASE),
    re.compile(r"\bformowl://(asset|object|storage|worker|evidence)\b", re.IGNORECASE),
    re.compile(r"\b(select|with|copy|insert|update|delete|drop|alter)\b\s+", re.IGNORECASE),
)
_EFFECTIVE_GRAPH_VIEW_GRANT_PERMISSIONS = {"graph_snippet"}
_NODE_SOURCE_FIELDS = {
    "canonical_atom": "included_atom_ids",
    "canonical_entity": "included_entity_ids",
    "user_authored_atom": "user_authored_atom_ids",
}


@dataclass(frozen=True)
class AccessRequiredScope:
    requestable_scope_type: str
    requestable_scope_id: str | None
    owner_user_id: str | None
    recommended_access_level: str = "graph_snippet"
    hidden_node_count: int = 0
    hidden_edge_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_required": True,
            "requestable_scope_type": self.requestable_scope_type,
            "requestable_scope_id": self.requestable_scope_id,
            "owner_user_id": self.owner_user_id,
            "recommended_access_level": self.recommended_access_level,
            "hidden_node_count": self.hidden_node_count,
            "hidden_edge_count": self.hidden_edge_count,
        }


@dataclass(frozen=True)
class EffectiveGraphView:
    requester_user_id: str
    user_graph_revision_id: str
    canonical_graph_revision_id: str
    ontology_revision_id: str
    assembly_policy_id: str
    visible_nodes: list[GraphProjectionNode] = field(default_factory=list)
    visible_edges: list[GraphProjectionEdge] = field(default_factory=list)
    access_required: list[AccessRequiredScope] = field(default_factory=list)
    applied_grant_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "requester_user_id": self.requester_user_id,
            "user_graph_revision_id": self.user_graph_revision_id,
            "canonical_graph_revision_id": self.canonical_graph_revision_id,
            "ontology_revision_id": self.ontology_revision_id,
            "assembly_policy_id": self.assembly_policy_id,
            "visible_nodes": [node.to_dict() for node in self.visible_nodes],
            "visible_edges": [edge.to_dict() for edge in self.visible_edges],
            "access_required": [scope.to_dict() for scope in self.access_required],
            "applied_grant_ids": list(self.applied_grant_ids),
        }
        _validate_no_raw_effective_view_reference(data)
        return data


def assemble_effective_graph_view(
    *,
    user_graph_revision: UserKnowledgeGraphRevision | dict[str, Any],
    graph_projection_store: FileGraphProjectionStore,
    requester_user_id: str,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
    allow_stale: bool = False,
) -> EffectiveGraphView:
    _validate_public_id(requester_user_id, "requester_user_id")
    revision = (
        user_graph_revision
        if isinstance(user_graph_revision, UserKnowledgeGraphRevision)
        else UserKnowledgeGraphRevision.from_dict(user_graph_revision)
    )
    grant_objects = _normalize_grants(grants)
    revision_access_grant_id = _effective_graph_view_access_grant_id(
        revision.permission_scope,
        requester_user_id=requester_user_id,
        grants=grant_objects,
        now=now,
    )
    if revision_access_grant_id is None:
        hidden_scopes: dict[tuple[str, str | None], AccessRequiredScope] = {}
        _record_access_required(hidden_scopes, revision.permission_scope)
        return EffectiveGraphView(
            requester_user_id=requester_user_id,
            user_graph_revision_id=revision.user_graph_revision_id,
            canonical_graph_revision_id=revision.canonical_graph_revision_id,
            ontology_revision_id=revision.ontology_revision_id,
            assembly_policy_id=revision.assembly_policy_id,
            access_required=sorted(
                hidden_scopes.values(),
                key=lambda scope: (
                    scope.requestable_scope_type,
                    scope.requestable_scope_id or "",
                ),
            ),
        )

    selected_node_ids = _selected_node_source_ids(revision)
    selected_relation_ids = set(revision.included_relation_ids)
    visible_nodes: list[GraphProjectionNode] = []
    hidden_scopes: dict[tuple[str, str | None], AccessRequiredScope] = {}
    applied_grant_ids: set[str] = set()
    if revision_access_grant_id:
        applied_grant_ids.add(revision_access_grant_id)

    for node in graph_projection_store.list_nodes():
        if not _projection_state_visible(node.projection_state, allow_stale=allow_stale):
            continue
        if not _node_selected_by_revision(node, selected_node_ids):
            continue
        access_grant_id = _effective_graph_view_access_grant_id(
            node.permission_scope,
            requester_user_id=requester_user_id,
            grants=grant_objects,
            now=now,
        )
        if access_grant_id is not None:
            if access_grant_id:
                applied_grant_ids.add(access_grant_id)
            _validate_no_raw_effective_view_reference(node.to_dict())
            visible_nodes.append(node)
        else:
            _record_access_required(hidden_scopes, node.permission_scope, hidden_node_count=1)

    visible_node_ids = {node.node_id for node in visible_nodes}
    visible_edges: list[GraphProjectionEdge] = []
    for edge in graph_projection_store.list_edges():
        if not _projection_state_visible(edge.projection_state, allow_stale=allow_stale):
            continue
        if not _edge_selected_by_revision(edge, selected_relation_ids):
            continue
        if (
            edge.source_node_id not in visible_node_ids
            or edge.target_node_id not in visible_node_ids
        ):
            continue
        access_grant_id = _effective_graph_view_access_grant_id(
            edge.permission_scope,
            requester_user_id=requester_user_id,
            grants=grant_objects,
            now=now,
        )
        if access_grant_id is not None:
            if access_grant_id:
                applied_grant_ids.add(access_grant_id)
            _validate_no_raw_effective_view_reference(edge.to_dict())
            visible_edges.append(edge)
        else:
            _record_access_required(hidden_scopes, edge.permission_scope, hidden_edge_count=1)

    return EffectiveGraphView(
        requester_user_id=requester_user_id,
        user_graph_revision_id=revision.user_graph_revision_id,
        canonical_graph_revision_id=revision.canonical_graph_revision_id,
        ontology_revision_id=revision.ontology_revision_id,
        assembly_policy_id=revision.assembly_policy_id,
        visible_nodes=sorted(visible_nodes, key=lambda node: node.node_id),
        visible_edges=sorted(visible_edges, key=lambda edge: edge.edge_id),
        access_required=sorted(
            hidden_scopes.values(),
            key=lambda scope: (scope.requestable_scope_type, scope.requestable_scope_id or ""),
        ),
        applied_grant_ids=sorted(applied_grant_ids),
    )


def requester_has_effective_graph_view_access(
    permission_scope: dict[str, Any],
    *,
    requester_user_id: str,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
) -> bool:
    return (
        _effective_graph_view_access_grant_id(
            permission_scope,
            requester_user_id=requester_user_id,
            grants=grants,
            now=now,
        )
        is not None
    )


def _effective_graph_view_access_grant_id(
    permission_scope: dict[str, Any],
    *,
    requester_user_id: str,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
) -> str | None:
    _validate_public_id(requester_user_id, "requester_user_id")
    scope = _safe_permission_scope(permission_scope)
    scope_type = scope["scope_type"]
    scope_id = scope.get("scope_id")
    visibility = scope["visibility"]

    if visibility == "public" or scope_type == "public":
        return ""
    if scope_type in {"private_user", "user"} and scope_id == requester_user_id:
        return ""

    for grant in _normalize_grants(grants):
        if now is None:
            raise ContractValidationError("now is required for grant-based graph view access")
        if _grant_allows_effective_graph_view(
            grant,
            requester_user_id=requester_user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            now=now,
        ):
            return grant.grant_id
    return None


def _selected_node_source_ids(revision: UserKnowledgeGraphRevision) -> dict[str, set[str]]:
    return {
        source_type: set(getattr(revision, field_name))
        for source_type, field_name in _NODE_SOURCE_FIELDS.items()
    }


def _node_selected_by_revision(
    node: GraphProjectionNode,
    selected_node_ids: dict[str, set[str]],
) -> bool:
    return node.source_id in selected_node_ids.get(node.source_type, set())


def _edge_selected_by_revision(edge: GraphProjectionEdge, selected_relation_ids: set[str]) -> bool:
    relation_id = edge.properties.get("canonical_relation_id")
    if relation_id is not None and not isinstance(relation_id, str):
        raise ContractValidationError("GraphProjectionEdge.canonical_relation_id must be a string")
    return edge.edge_id in selected_relation_ids or relation_id in selected_relation_ids


def _record_access_required(
    hidden_scopes: dict[tuple[str, str | None], AccessRequiredScope],
    permission_scope: dict[str, Any],
    *,
    hidden_node_count: int = 0,
    hidden_edge_count: int = 0,
) -> None:
    scope = _safe_permission_scope(permission_scope)
    key = (scope["scope_type"], scope.get("scope_id"))
    current = hidden_scopes.get(key)
    owner_user_id = (
        scope.get("scope_id") if scope["scope_type"] in {"private_user", "user"} else None
    )
    if current is None:
        hidden_scopes[key] = AccessRequiredScope(
            requestable_scope_type=scope["scope_type"],
            requestable_scope_id=scope.get("scope_id"),
            owner_user_id=owner_user_id,
            hidden_node_count=hidden_node_count,
            hidden_edge_count=hidden_edge_count,
        )
        return
    hidden_scopes[key] = AccessRequiredScope(
        requestable_scope_type=current.requestable_scope_type,
        requestable_scope_id=current.requestable_scope_id,
        owner_user_id=current.owner_user_id,
        recommended_access_level=current.recommended_access_level,
        hidden_node_count=current.hidden_node_count + hidden_node_count,
        hidden_edge_count=current.hidden_edge_count + hidden_edge_count,
    )


def _grant_allows_effective_graph_view(
    grant: Grant,
    *,
    requester_user_id: str,
    scope_type: str,
    scope_id: str | None,
    now: str,
) -> bool:
    if grant.grantee_user_id != requester_user_id:
        return False
    if grant.revoked_at:
        return False
    if grant.permission not in _EFFECTIVE_GRAPH_VIEW_GRANT_PERMISSIONS:
        return False
    if grant.max_access_count == 0:
        return False
    if _is_expired(grant.expires_at, now):
        return False
    if scope_type in {"private_user", "user"} and grant.owner_user_id != scope_id:
        return False
    return grant.scope_type == scope_type and grant.scope_id == scope_id


def _normalize_grants(grants: Sequence[Grant | dict[str, Any]]) -> list[Grant]:
    normalized = [Grant.from_dict(to_plain(grant)) for grant in grants]
    for grant in normalized:
        _validate_public_id(grant.grant_id, "Grant.grant_id")
    return normalized


def _safe_permission_scope(permission_scope: dict[str, Any]) -> dict[str, Any]:
    scope = validate_permission_scope(to_plain(permission_scope))
    _validate_public_id(scope["scope_type"], "permission_scope.scope_type")
    _validate_public_id(scope["visibility"], "permission_scope.visibility")
    if scope.get("scope_id") is not None:
        _validate_public_id(scope["scope_id"], "permission_scope.scope_id")
    return scope


def _validate_public_id(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_PUBLIC_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a safe FormOwl identifier")


def _validate_no_raw_effective_view_reference(value: Any) -> None:
    if isinstance(value, str):
        for pattern in _EFFECTIVE_VIEW_RAW_REFERENCE_PATTERNS:
            if pattern.search(value):
                raise ContractValidationError(
                    "effective graph view must not contain raw references"
                )
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_no_raw_effective_view_reference(str(key))
            _validate_no_raw_effective_view_reference(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_no_raw_effective_view_reference(item)


def _is_expired(expires_at: str, now: str) -> bool:
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        return True
    return expires <= current


def _projection_state_visible(state: str, *, allow_stale: bool) -> bool:
    return state == "ready" or (state == "stale" and allow_stale)
