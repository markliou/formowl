from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Generic, TypeVar

from formowl_contract import ContractValidationError, Grant, to_plain, validate_permission_scope

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_RAW_PATH_PATTERN = re.compile(r"^(?:/|\\\\|file://|[A-Za-z]:[\\/])")
_RAW_STORAGE_URI_PATTERN = re.compile(
    r"^(?:abfs|dav|file|gs|http\+unix|minio|nfs|object|postgres|postgresql|s3|s3a|"
    r"smb|sqlite|wasb|wasbs|webdav)://",
    re.IGNORECASE,
)
_VECTOR_STATES = {
    "pending",
    "indexing",
    "ready",
    "stale",
    "rebuilding",
    "failed",
    "disabled",
}
_PROJECTION_STATES = {
    "disabled",
    "pending",
    "ready",
    "stale",
    "rebuilding",
    "failed",
}
_GRAPH_ACCESS_PERMISSIONS = {
    "answer_only",
    "asset_scoped_access",
    "evidence_snippet",
    "graph_snippet",
    "project_scoped_access",
    "query_scoped_access",
    "read",
    "search",
    "session_access",
}
T = TypeVar("T")


@dataclass(frozen=True)
class VectorRecord:
    vector_id: str
    source_type: str
    source_id: str
    source_content_hash: str
    embedding_model: str
    embedding: list[float]
    permission_scope: dict[str, Any]
    index_state: str = "ready"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VectorRecord":
        record = validate_vector_record(value)
        return cls(
            vector_id=str(record["vector_id"]),
            source_type=str(record["source_type"]),
            source_id=str(record["source_id"]),
            source_content_hash=str(record["source_content_hash"]),
            embedding_model=str(record["embedding_model"]),
            embedding=[float(component) for component in record["embedding"]],
            permission_scope=dict(record["permission_scope"]),
            index_state=str(record.get("index_state", "ready")),
            metadata=dict(record.get("metadata", {})),
            created_at=record.get("created_at"),
            updated_at=record.get("updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_vector_record(data)
        return data


@dataclass(frozen=True)
class VectorSearchResult:
    record: VectorRecord
    score: float
    stale: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.to_dict(),
            "score": self.score,
            "stale": self.stale,
        }


@dataclass(frozen=True)
class GraphProjectionNode:
    node_id: str
    source_type: str
    source_id: str
    labels: list[str]
    properties: dict[str, Any]
    permission_scope: dict[str, Any]
    projection_state: str = "ready"
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GraphProjectionNode":
        node = validate_graph_projection_node(value)
        return cls(
            node_id=str(node["node_id"]),
            source_type=str(node["source_type"]),
            source_id=str(node["source_id"]),
            labels=list(node["labels"]),
            properties=dict(node["properties"]),
            permission_scope=dict(node["permission_scope"]),
            projection_state=str(node.get("projection_state", "ready")),
            created_at=node.get("created_at"),
            updated_at=node.get("updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_graph_projection_node(data)
        return data


@dataclass(frozen=True)
class GraphProjectionEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    properties: dict[str, Any]
    permission_scope: dict[str, Any]
    projection_state: str = "ready"
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GraphProjectionEdge":
        edge = validate_graph_projection_edge(value)
        return cls(
            edge_id=str(edge["edge_id"]),
            source_node_id=str(edge["source_node_id"]),
            target_node_id=str(edge["target_node_id"]),
            relation_type=str(edge["relation_type"]),
            properties=dict(edge["properties"]),
            permission_scope=dict(edge["permission_scope"]),
            projection_state=str(edge.get("projection_state", "ready")),
            created_at=edge.get("created_at"),
            updated_at=edge.get("updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_graph_projection_edge(data)
        return data


class FileVectorStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonIndexRecordStore[VectorRecord](
            base_dir,
            collection=("index", "vectors"),
            id_field="vector_id",
            factory=VectorRecord.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(self, vector_record: VectorRecord | dict[str, Any]) -> VectorRecord:
        return self._store.create(vector_record)

    def get(self, vector_id: str) -> VectorRecord | None:
        return self._store.get(vector_id)

    def list(self) -> list[VectorRecord]:
        return self._store.list()

    def mark_stale_for_source(
        self,
        *,
        source_type: str,
        source_id: str,
        reason: str | None = None,
    ) -> list[VectorRecord]:
        _validate_public_identifier(source_type, "source_type")
        _validate_public_identifier(source_id, "source_id")
        stale_records: list[VectorRecord] = []
        for record in self.list():
            if record.source_type != source_type or record.source_id != source_id:
                continue
            metadata = dict(record.metadata)
            if reason is not None:
                _validate_string(reason, "reason")
                metadata["stale_reason"] = reason
            stale_record = replace(record, index_state="stale", metadata=metadata)
            self._store.create(stale_record)
            stale_records.append(stale_record)
        return stale_records

    def search(
        self,
        query_embedding: list[float],
        *,
        requester_user_id: str,
        grants: list[Grant | dict[str, Any]] | tuple[Grant | dict[str, Any], ...] = (),
        allow_stale: bool = False,
        limit: int | None = None,
        now: str | None = None,
    ) -> list[VectorSearchResult]:
        query = _validate_embedding(query_embedding, "query_embedding")
        _validate_string(requester_user_id, "requester_user_id")
        if limit is not None and (not isinstance(limit, int) or limit < 0):
            raise ContractValidationError("limit must be a non-negative integer")

        results: list[VectorSearchResult] = []
        for record in self.list():
            if record.index_state == "ready":
                pass
            elif record.index_state == "stale" and allow_stale:
                pass
            else:
                continue
            if len(record.embedding) != len(query):
                continue
            if not requester_has_graph_access(
                record.permission_scope,
                requester_user_id=requester_user_id,
                grants=grants,
                now=now,
            ):
                continue
            results.append(
                VectorSearchResult(
                    record=record,
                    score=_cosine_similarity(query, record.embedding),
                    stale=record.index_state == "stale",
                )
            )

        results.sort(key=lambda result: (-result.score, result.record.vector_id))
        if limit is not None:
            return results[:limit]
        return results


class FileGraphProjectionStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._node_store = _JsonIndexRecordStore[GraphProjectionNode](
            base_dir,
            collection=("index", "graph-projections", "nodes"),
            id_field="node_id",
            factory=GraphProjectionNode.from_dict,
            serializer=lambda value: value.to_dict(),
        )
        self._edge_store = _JsonIndexRecordStore[GraphProjectionEdge](
            base_dir,
            collection=("index", "graph-projections", "edges"),
            id_field="edge_id",
            factory=GraphProjectionEdge.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create_node(
        self,
        node: GraphProjectionNode | dict[str, Any],
    ) -> GraphProjectionNode:
        return self._node_store.create(node)

    def create_edge(
        self,
        edge: GraphProjectionEdge | dict[str, Any],
    ) -> GraphProjectionEdge:
        return self._edge_store.create(edge)

    def get_node(self, node_id: str) -> GraphProjectionNode | None:
        return self._node_store.get(node_id)

    def get_edge(self, edge_id: str) -> GraphProjectionEdge | None:
        return self._edge_store.get(edge_id)

    def list_nodes(self) -> list[GraphProjectionNode]:
        return self._node_store.list()

    def list_edges(self) -> list[GraphProjectionEdge]:
        return self._edge_store.list()

    def visible_nodes(
        self,
        *,
        requester_user_id: str,
        grants: list[Grant | dict[str, Any]] | tuple[Grant | dict[str, Any], ...] = (),
        allow_stale: bool = False,
        now: str | None = None,
    ) -> list[GraphProjectionNode]:
        _validate_string(requester_user_id, "requester_user_id")
        return [
            node
            for node in self.list_nodes()
            if _is_projection_visible(
                node.projection_state,
                allow_stale=allow_stale,
            )
            and requester_has_graph_access(
                node.permission_scope,
                requester_user_id=requester_user_id,
                grants=grants,
                now=now,
            )
        ]

    def neighbors(
        self,
        node_id: str,
        *,
        requester_user_id: str,
        grants: list[Grant | dict[str, Any]] | tuple[Grant | dict[str, Any], ...] = (),
        allow_stale: bool = False,
        now: str | None = None,
    ) -> list[GraphProjectionEdge]:
        start_node = self.get_node(node_id)
        if start_node is None:
            return []
        visible_node_ids = {
            node.node_id
            for node in self.visible_nodes(
                requester_user_id=requester_user_id,
                grants=grants,
                allow_stale=allow_stale,
                now=now,
            )
        }
        if start_node.node_id not in visible_node_ids:
            return []

        visible_edges: list[GraphProjectionEdge] = []
        for edge in self.list_edges():
            if edge.source_node_id != node_id and edge.target_node_id != node_id:
                continue
            other_node_id = (
                edge.target_node_id if edge.source_node_id == node_id else edge.source_node_id
            )
            if other_node_id not in visible_node_ids:
                continue
            if not _is_projection_visible(edge.projection_state, allow_stale=allow_stale):
                continue
            if not requester_has_graph_access(
                edge.permission_scope,
                requester_user_id=requester_user_id,
                grants=grants,
                now=now,
            ):
                continue
            visible_edges.append(edge)
        return visible_edges


def requester_has_graph_access(
    permission_scope: dict[str, Any],
    *,
    requester_user_id: str,
    grants: list[Grant | dict[str, Any]] | tuple[Grant | dict[str, Any], ...] = (),
    now: str | None = None,
) -> bool:
    _validate_string(requester_user_id, "requester_user_id")
    scope = validate_permission_scope(to_plain(permission_scope))
    scope_type = scope["scope_type"]
    scope_id = scope.get("scope_id")
    visibility = scope["visibility"]

    if visibility == "public" or scope_type == "public":
        return True
    if scope_type in {"private_user", "user"} and scope_id == requester_user_id:
        return True

    for grant_value in grants:
        grant = grant_value if isinstance(grant_value, Grant) else Grant.from_dict(grant_value)
        if now is None:
            raise ContractValidationError("now is required for grant-based graph access")
        if _grant_allows_scope(
            grant,
            requester_user_id=requester_user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            now=now,
        ):
            return True
    return False


def validate_vector_record(value: Any) -> dict[str, Any]:
    record = _require_mapping(value, "VectorRecord")
    _require_fields(
        record,
        (
            "vector_id",
            "source_type",
            "source_id",
            "source_content_hash",
            "embedding_model",
            "embedding",
            "permission_scope",
        ),
        "VectorRecord",
    )
    _validate_safe_id(record["vector_id"], "vector_id")
    _validate_public_identifier(record["source_type"], "source_type")
    _validate_public_identifier(record["source_id"], "source_id")
    _validate_string(record["source_content_hash"], "source_content_hash")
    _validate_string(record["embedding_model"], "embedding_model")
    record["embedding"] = _validate_embedding(record["embedding"], "embedding")
    record["permission_scope"] = validate_permission_scope(record["permission_scope"])
    _validate_index_state(record.get("index_state", "ready"), _VECTOR_STATES, "index_state")
    _validate_optional_string_fields(record, ("created_at", "updated_at"), "VectorRecord")
    _validate_json_object(record.get("metadata", {}), "VectorRecord.metadata")
    return record


def validate_graph_projection_node(value: Any) -> dict[str, Any]:
    node = _require_mapping(value, "GraphProjectionNode")
    _require_fields(
        node,
        ("node_id", "source_type", "source_id", "labels", "properties", "permission_scope"),
        "GraphProjectionNode",
    )
    _validate_safe_id(node["node_id"], "node_id")
    _validate_public_identifier(node["source_type"], "source_type")
    _validate_public_identifier(node["source_id"], "source_id")
    _validate_public_string_list(node["labels"], "GraphProjectionNode.labels", allow_empty=False)
    _validate_json_object(node["properties"], "GraphProjectionNode.properties")
    node["permission_scope"] = validate_permission_scope(node["permission_scope"])
    _validate_index_state(
        node.get("projection_state", "ready"),
        _PROJECTION_STATES,
        "projection_state",
    )
    _validate_optional_string_fields(node, ("created_at", "updated_at"), "GraphProjectionNode")
    return node


def validate_graph_projection_edge(value: Any) -> dict[str, Any]:
    edge = _require_mapping(value, "GraphProjectionEdge")
    _require_fields(
        edge,
        (
            "edge_id",
            "source_node_id",
            "target_node_id",
            "relation_type",
            "properties",
            "permission_scope",
        ),
        "GraphProjectionEdge",
    )
    _validate_safe_id(edge["edge_id"], "edge_id")
    _validate_safe_id(edge["source_node_id"], "source_node_id")
    _validate_safe_id(edge["target_node_id"], "target_node_id")
    _validate_public_string(edge["relation_type"], "relation_type")
    _validate_json_object(edge["properties"], "GraphProjectionEdge.properties")
    edge["permission_scope"] = validate_permission_scope(edge["permission_scope"])
    _validate_index_state(
        edge.get("projection_state", "ready"),
        _PROJECTION_STATES,
        "projection_state",
    )
    _validate_optional_string_fields(edge, ("created_at", "updated_at"), "GraphProjectionEdge")
    return edge


class _JsonIndexRecordStore(Generic[T]):
    def __init__(
        self,
        base_dir: str | Path,
        *,
        collection: tuple[str, ...],
        id_field: str,
        factory: Callable[[dict[str, Any]], T],
        serializer: Callable[[T], dict[str, Any]],
    ) -> None:
        # Index stores are derived search/projection state. They deliberately
        # live under graph/index and never create canonical graph collections.
        self.base_dir = Path(base_dir) / "graph"
        for segment in collection:
            self.base_dir = self.base_dir / segment
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.id_field = id_field
        self.factory = factory
        self.serializer = serializer

    def create(self, record: T | dict[str, Any]) -> T:
        validated = self._validate(record)
        payload = self.serializer(validated)
        record_id = str(payload[self.id_field])
        _write_json(self._record_path(record_id), payload)
        return validated

    def get(self, record_id: str) -> T | None:
        path = self._record_path(record_id)
        if not path.exists():
            return None
        return self.factory(_read_json(path))

    def list(self) -> list[T]:
        return [self.factory(_read_json(path)) for path in sorted(self.base_dir.glob("*.json"))]

    def _validate(self, record: T | dict[str, Any]) -> T:
        if isinstance(record, dict):
            return self.factory(record)
        return self.factory(self.serializer(record))

    def _record_path(self, record_id: str) -> Path:
        _validate_safe_id(record_id, self.id_field)
        return self.base_dir / f"{record_id}.json"


def _grant_allows_scope(
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
    if grant.permission not in _GRAPH_ACCESS_PERMISSIONS:
        return False
    if _is_expired(grant.expires_at, now):
        return False
    return grant.scope_type == scope_type and grant.scope_id == scope_id


def _is_expired(expires_at: str, now: str) -> bool:
    try:
        expires = _parse_iso_datetime(expires_at)
        current = _parse_iso_datetime(now)
    except ValueError:
        return True
    return expires <= current


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_projection_visible(state: str, *, allow_stale: bool) -> bool:
    if state == "ready":
        return True
    return state == "stale" and allow_stale


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(component * component for component in left))
    right_norm = math.sqrt(sum(component * component for component in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot_product = sum(left_value * right_value for left_value, right_value in zip(left, right))
    return dot_product / (left_norm * right_norm)


def _validate_embedding(value: Any, field_name: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty list")
    components: list[float] = []
    for index, component in enumerate(value):
        if isinstance(component, bool) or not isinstance(component, int | float):
            raise ContractValidationError(f"{field_name}[{index}] must be numeric")
        numeric = float(component)
        if not math.isfinite(numeric):
            raise ContractValidationError(f"{field_name}[{index}] must be finite")
        components.append(numeric)
    return components


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, dict):
        plain = value
    else:
        plain = to_plain(value)
    if not isinstance(plain, dict):
        raise ContractValidationError(f"{name} must be an object")
    return dict(plain)


def _require_fields(value: dict[str, Any], fields: tuple[str, ...], name: str) -> None:
    missing = [field_name for field_name in fields if field_name not in value]
    if missing:
        raise ContractValidationError(f"{name} missing required field: {missing[0]}")


def _validate_safe_id(value: Any, field_name: str) -> None:
    _validate_string(value, field_name)
    if not _SAFE_RECORD_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a safe file name")


def _validate_public_identifier(value: Any, field_name: str) -> None:
    _validate_string(value, field_name)
    if _RAW_PATH_PATTERN.search(value) or not _SAFE_RECORD_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a safe FormOwl index identifier")


def _validate_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")


def _validate_string_list(value: Any, field_name: str, *, allow_empty: bool) -> None:
    if not isinstance(value, list):
        raise ContractValidationError(f"{field_name} must be a list")
    if not allow_empty and not value:
        raise ContractValidationError(f"{field_name} must not be empty")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ContractValidationError(f"{field_name}[{index}] must be a non-empty string")


def _validate_public_string(value: Any, field_name: str) -> None:
    _validate_string(value, field_name)
    if _looks_like_raw_locator(value):
        raise ContractValidationError(f"{field_name} must not expose a raw storage locator")


def _validate_public_string_list(value: Any, field_name: str, *, allow_empty: bool) -> None:
    _validate_string_list(value, field_name, allow_empty=allow_empty)
    for index, item in enumerate(value):
        _validate_public_string(item, f"{field_name}[{index}]")


def _validate_optional_string_fields(
    value: dict[str, Any],
    fields: tuple[str, ...],
    name: str,
) -> None:
    for field_name in fields:
        if field_name in value and value[field_name] is not None:
            _validate_string(value[field_name], f"{name}.{field_name}")


def _validate_index_state(value: Any, supported_states: set[str], field_name: str) -> None:
    _validate_string(value, field_name)
    if value not in supported_states:
        raise ContractValidationError(f"{field_name} is not supported")


def _validate_json_object(value: Any, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{field_name} must be an object")
    _validate_public_json_payload(value, field_name)
    try:
        json.dumps(to_plain(value), allow_nan=False, sort_keys=True)
    except TypeError as exc:
        raise ContractValidationError(f"{field_name} must be JSON serializable") from exc
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} must be strict JSON") from exc


def _validate_public_json_payload(value: Any, field_name: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ContractValidationError(f"{field_name} keys must be non-empty strings")
            if _looks_like_raw_locator(key):
                raise ContractValidationError(f"{field_name} keys must not expose raw locators")
            _validate_public_json_payload(item, f"{field_name}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_public_json_payload(item, f"{field_name}[{index}]")
        return
    if isinstance(value, str) and _looks_like_raw_locator(value):
        raise ContractValidationError(f"{field_name} must not expose a raw storage locator")
    if value is None or isinstance(value, bool | int | float | str):
        return
    raise ContractValidationError(f"{field_name} must be strict JSON")


def _looks_like_raw_locator(value: str) -> bool:
    if value.startswith(("formowl://", "http://", "https://")):
        return False
    return (
        bool(_RAW_PATH_PATTERN.search(value))
        or bool(_RAW_STORAGE_URI_PATTERN.search(value))
        or "/" in value
        or "\\" in value
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(
            to_plain(payload),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    temp_path.replace(path)
