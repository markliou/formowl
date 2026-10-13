from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Generic, Iterable, TypeVar

from formowl_contract import (
    ContractValidationError, Grant, sha256_json, to_plain, validate_permission_scope,
)
from formowl_graph.storage.postgres import (
    PostgreSQLConnection, PostgreSQLMetadataRepository, SQLStatement,
)

# File-backed index ids must not become dot entries, hidden files, or
# traversal fragments when converted into JSON record paths.
_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RAW_PATH_PATTERN = re.compile(r"^(?:/|\\\\|file://|[A-Za-z]:[\\/])")
_RAW_STORAGE_URI_PATTERN = re.compile(
    r"^(?:abfs|dav|file|gs|http\+unix|minio|nfs|object|postgres|postgresql|s3|s3a|"
    r"smb|sqlite|wasb|wasbs|webdav)://",
    re.IGNORECASE,
)
# Session-scoped because CREATE/DROP INDEX CONCURRENTLY cannot be enclosed in
# the transaction-scoped lock used by the normal migration runner.
_PROJECTION_INDEX_REPAIR_LOCK_KEY = 0x466F726D4F776C49
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
class ProjectionIndexRepairPlan:
    """Auditable, operator-applied repair plan for stale projection indexes.

    The plan is intentionally not a migration-runner input and never executes
    SQL by itself.  ``build`` and ``cleanup`` contain ``CONCURRENTLY`` DDL and
    must run outside a transaction.  ``swap`` (or ``rollback``) is the only
    transactional phase: it renames the validated replacement and quarantines
    the old same-named index before the old index is dropped.  A failed build,
    validation, swap, or cleanup therefore leaves either the original index or
    a named quarantine artifact available for operator diagnosis.
    """

    target_names: tuple[str, ...]
    replacement_names: tuple[str, ...]
    quarantine_names: tuple[str, ...]
    stale_predicate: str
    expected_predicates: tuple[tuple[str, str], ...]
    preflight: SQLStatement
    advisory_lock: SQLStatement
    advisory_unlock: SQLStatement
    build: tuple[SQLStatement, ...]
    validate: SQLStatement
    swap: tuple[SQLStatement, ...]
    rollback: tuple[SQLStatement, ...]
    cleanup: tuple[SQLStatement, ...]
    rollback_cleanup: tuple[SQLStatement, ...]

    def validate_preflight(self, rows: Iterable[Mapping[str, Any]]) -> None:
        """Reject missing targets and any replacement/quarantine collision.

        The operator must run :attr:`advisory_lock` on one session, verify that
        it returns ``acquired = true``, run :attr:`preflight`, and pass the
        result here before any build or swap statement.  The same session must
        retain the lock through cleanup/rollback and then run
        :attr:`advisory_unlock`.
        """
        expected = {
            **{(name, "target"): "target_present" for name in self.target_names},
            **{(name, "replacement"): "absent" for name in self.replacement_names},
            **{(name, "quarantine"): "absent" for name in self.quarantine_names},
        }
        seen: set[tuple[Any, Any]] = set()
        failures: list[str] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ContractValidationError(
                    "projection index repair preflight row is invalid"
                )
            key = (row.get("index_name"), row.get("index_role"))
            if key not in expected:
                failures.append(f"unexpected:{key[0]}:{key[1]}")
                continue
            if key in seen:
                failures.append(f"duplicate:{key[0]}:{key[1]}")
                continue
            seen.add(key)
            if row.get("preflight_status") != expected[key]:
                failures.append(
                    f"{key[0]}:{key[1]}:{row.get('preflight_status')}"
                )
        missing = sorted(
            f"{name}:{role}"
            for (name, role) in expected
            if (name, role) not in seen
        )
        if failures or missing:
            details = ", ".join([*failures, *(f"missing:{item}" for item in missing)])
            raise ContractValidationError(
                "projection index repair preflight rejected: " + details
            )


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


class PostgreSQLGraphProjectionStore:
    """Private revision-scoped projection over the existing metadata table.

    This is not a canonical graph writer. Callers bind the authorized source and
    execution profile before writing. Pages are bounded even during sealing;
    request paths must use lookups, not iterate the revision. Index installation
    is an explicit operator action, never a side effect of opening a revision.
    """

    _TYPE = "bounded_graph_projection_v1"
    _MAX_BATCH = 256

    def __init__(
        self, connection: PostgreSQLConnection, *, revision_id: str,
        workspace_id: str, binding: dict[str, Any],
    ) -> None:
        _validate_safe_id(revision_id, "revision_id")
        _validate_public_identifier(workspace_id, "workspace_id")
        if not binding:
            raise ContractValidationError("graph projection requires an authority binding")
        self.connection = connection
        self.revision_id = revision_id
        self.workspace_id = workspace_id
        self.binding = to_plain(binding)
        self._binding_hash = sha256_json(self.binding)
        self._repository = PostgreSQLMetadataRepository(connection)
        self.seal_hash: str | None = None

    @classmethod
    def index_statements(cls) -> tuple[SQLStatement, ...]:
        """Indexes on the existing owner table; apply via reviewed deployment."""
        prefix = (
            "CREATE INDEX IF NOT EXISTS formowl_projection_"
        )
        columns = {
            "page": "(payload->>'kind'), (payload->>'id')",
            "source": "(payload->>'kind'), (payload->>'source_node_id'), (payload->>'id')",
            "target": "(payload->>'kind'), (payload->>'target_node_id'), (payload->>'id')",
            "member_node": "(payload->>'node_id'), (payload->>'observation_id')",
            "member_observation": "(payload->>'observation_id'), (payload->>'node_id')",
            "edge_hash": "(payload->>'edge_hash')",
            "helper_hash": "(payload->>'kind'), (payload->>'observation_hash')",
            "helper_family": (
                "(payload->>'kind'), (payload->'data'->>'retrieval_source_family'), "
                "(payload->>'observation_hash')"
            ),
            "attachment_asset": "(payload->>'kind'), (payload->>'attachment_child_asset_id')",
            "helper_occurrence": "(payload->>'kind'), (payload->>'occurrence_id'), (payload->>'id')",
            "dense_text": "(payload->>'kind'), (payload->>'dense_text_hash'), (payload->>'id')",
            # Digest is an index accelerator only; ranked queries recheck raw
            # equality so collisions cannot merge terms or alter scoring.
            "token": "(payload->>'kind'), (md5(payload->>'token')), (payload->>'id')",
            "ordinal": "(payload->>'kind'), ((payload->>'ordinal')::bigint)",
            "candidate_order": (
                "(payload->>'kind'), ((payload->'data'->>'bundle_id') COLLATE \"C\"), "
                "((payload->'data'->>'source_observation_hash') COLLATE \"C\"), "
                "((payload->'data'->>'message_occurrence_hash') COLLATE \"C\")"
            ),
        }
        # Keep the existing keys/names, but do not index unrelated projection
        # records as NULL-valued entries (especially the much larger postings).
        kinds = {
            "source": ("edge",), "target": ("edge",),
            "member_node": ("membership",), "member_observation": ("membership",),
            "edge_hash": ("edge",),
            "helper_hash": ("helper",), "helper_family": ("helper",),
            "attachment_asset": ("helper",), "helper_occurrence": ("helper",),
            "dense_text": ("candidate",), "ordinal": ("candidate",),
            "candidate_order": ("candidate",), "token": ("posting", "token_stat"),
        }
        def kind_predicate(name: str) -> str:
            if name not in kinds:
                return ""
            return " AND payload->>'kind' IN (" + ", ".join(
                "'" + kind + "'" for kind in kinds[name]
            ) + ")"

        def collated(expression: str) -> str:
            for name in ("id", "node_id", "observation_id", "source_node_id", "target_node_id"):
                expression = expression.replace(
                    f"(payload->>'{name}')", f"((payload->>'{name}') COLLATE \"C\")",
                )
            return expression
        return tuple(SQLStatement(
            prefix + name + " ON formowl_graph_records "
            "(workspace_id, (payload->>'revision_id'), "
            + collated(expression) + ") "
            "WHERE record_type = 'bounded_graph_projection_v1'" + kind_predicate(name)
        ) for name, expression in columns.items()) + (SQLStatement(
            "CREATE INDEX IF NOT EXISTS formowl_projection_vector_source "
            "ON formowl_vector_index (source_type, source_id)",
        ),) + tuple(SQLStatement(
            "CREATE INDEX IF NOT EXISTS formowl_projection_" + name
            + " ON formowl_graph_records USING gin ((payload->'data'->'" + name + "')) "
            "WHERE record_type = 'bounded_graph_projection_v1' AND payload->>'kind' = 'candidate'"
        ) for name in (
            "protected_identifier_tokens", "observation_protected_identifier_tokens",
            "observation_tokens",
        )) + tuple(SQLStatement(
            "CREATE INDEX IF NOT EXISTS formowl_projection_" + name
            + " ON formowl_graph_records USING gin "
            "((payload->'data'->'properties'->'" + name + "')) "
            "WHERE record_type = 'bounded_graph_projection_v1' AND payload->>'kind' = 'node'"
        ) for name in (
            "relation_searchable_tokens", "relation_source_term_hashes",
            "relation_protected_term_hashes",
        ))

    @classmethod
    def projection_index_repair_plan(cls) -> ProjectionIndexRepairPlan:
        """Build a pure, explicit repair plan for the 13 stale B-tree indexes.

        This is deliberately separate from :meth:`index_statements` and from
        :class:`PostgreSQLMigrationRunner`: it is not automatic startup work
        and must be reviewed/applied by an operator.  The source definitions
        are reused so the repair cannot silently drift from the owner path.
        """
        target_names = (
            "formowl_projection_source",
            "formowl_projection_target",
            "formowl_projection_member_node",
            "formowl_projection_member_observation",
            "formowl_projection_edge_hash",
            "formowl_projection_helper_hash",
            "formowl_projection_helper_family",
            "formowl_projection_attachment_asset",
            "formowl_projection_helper_occurrence",
            "formowl_projection_dense_text",
            "formowl_projection_token",
            "formowl_projection_ordinal",
            "formowl_projection_candidate_order",
        )
        definitions = {
            name: next(
                (
                    statement.sql
                    for statement in cls.index_statements()
                    if statement.sql.startswith(name + " ON ")
                    or statement.sql.startswith("CREATE INDEX IF NOT EXISTS " + name + " ON ")
                ),
                None,
            )
            for name in target_names
        }
        # ``index_statements`` currently emits the CREATE prefix, while this
        # lookup also accepts the unprefixed form to keep the contract local
        # if the owner changes its SQL builder shape.
        if any(value is None for value in definitions.values()):
            raise ContractValidationError(
                "projection index repair definitions are incomplete"
            )

        stale_predicate = "record_type = 'bounded_graph_projection_v1'"
        replacement_names = tuple(name + "__repair_v1" for name in target_names)
        quarantine_names = tuple(name + "__old_v1" for name in target_names)
        expected_predicates = tuple(
            (
                name,
                definitions[name].split(" WHERE ", 1)[1],
            )
            for name in target_names
        )
        preflight = SQLStatement(
            sql=(
                "WITH expected(index_name, index_role) AS ("
                "SELECT unnest(%(target_names)s::text[]), 'target'::text "
                "UNION ALL "
                "SELECT unnest(%(replacement_names)s::text[]), 'replacement'::text "
                "UNION ALL "
                "SELECT unnest(%(quarantine_names)s::text[]), 'quarantine'::text"
                "), catalog AS ("
                "SELECT c.relname AS index_name, c.relkind, t.relname AS table_name, "
                "pg_get_expr(i.indpred, i.indrelid) AS predicate, "
                "i.indisvalid, i.indisready, i.indislive "
                "FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "LEFT JOIN pg_catalog.pg_index AS i ON i.indexrelid = c.oid "
                "LEFT JOIN pg_catalog.pg_class AS t ON t.oid = i.indrelid "
                "WHERE n.nspname = %(schema_name)s"
                ") "
                "SELECT e.index_name, e.index_role, "
                "CASE "
                "WHEN c.index_name IS NULL THEN 'absent' "
                "WHEN e.index_role = 'target' AND c.relkind = 'i' "
                "AND c.table_name = %(table_name)s THEN 'target_present' "
                "ELSE 'collision' END AS preflight_status, "
                "c.table_name, c.predicate, c.indisvalid, c.indisready, c.indislive "
                "FROM expected AS e "
                "LEFT JOIN catalog AS c ON c.index_name = e.index_name "
                "ORDER BY e.index_role, e.index_name"
            ),
            parameters={
                "schema_name": "public",
                "table_name": "formowl_graph_records",
                # Keep the old key as a compatibility alias for plan
                # consumers while the three role-specific arrays make the
                # collision contract explicit.
                "index_names": target_names,
                "target_names": list(target_names),
                "replacement_names": list(replacement_names),
                "quarantine_names": list(quarantine_names),
            },
        )
        advisory_lock = SQLStatement(
            sql="SELECT pg_try_advisory_lock(%(lock_key)s) AS acquired",
            parameters={"lock_key": _PROJECTION_INDEX_REPAIR_LOCK_KEY},
        )
        advisory_unlock = SQLStatement(
            sql="SELECT pg_advisory_unlock(%(lock_key)s) AS released",
            parameters={"lock_key": _PROJECTION_INDEX_REPAIR_LOCK_KEY},
        )
        build = tuple(
            SQLStatement(
                sql=definitions[name].replace(
                    "CREATE INDEX IF NOT EXISTS " + name,
                    "CREATE INDEX CONCURRENTLY " + replacement_name,
                    1,
                )
            )
            for name, replacement_name in zip(
                target_names, replacement_names, strict=True
            )
        )
        validate = SQLStatement(
            sql=(
                "SELECT c.relname AS index_name, "
                "pg_get_indexdef(c.oid) AS index_definition, "
                "pg_get_expr(i.indpred, i.indrelid) AS predicate, "
                "i.indisvalid, i.indisready, i.indislive "
                "FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "JOIN pg_catalog.pg_index AS i ON i.indexrelid = c.oid "
                "JOIN pg_catalog.pg_class AS t ON t.oid = i.indrelid "
                "WHERE n.nspname = %(schema_name)s "
                "AND t.relname = %(table_name)s "
                "AND c.relname = ANY(%(index_names)s) "
                "ORDER BY c.relname"
            ),
            parameters={
                "schema_name": "public",
                "table_name": "formowl_graph_records",
                "index_names": replacement_names,
            },
        )
        swap = tuple(
            statement
            for name, replacement_name, quarantine_name in zip(
                target_names, replacement_names, quarantine_names, strict=True
            )
            for statement in (
                SQLStatement(
                    sql=f"ALTER INDEX {name} RENAME TO {quarantine_name}"
                ),
                SQLStatement(
                    sql=f"ALTER INDEX {replacement_name} RENAME TO {name}"
                ),
            )
        )
        rollback = tuple(
            statement
            for name, replacement_name, quarantine_name in zip(
                target_names, replacement_names, quarantine_names, strict=True
            )
            for statement in (
                SQLStatement(
                    sql=f"ALTER INDEX {name} RENAME TO {replacement_name}"
                ),
                SQLStatement(
                    sql=f"ALTER INDEX {quarantine_name} RENAME TO {name}"
                ),
            )
        )
        cleanup = tuple(
            SQLStatement(sql=f"DROP INDEX CONCURRENTLY {quarantine_name}")
            for quarantine_name in quarantine_names
        )
        rollback_cleanup = tuple(
            SQLStatement(sql=f"DROP INDEX CONCURRENTLY {replacement_name}")
            for replacement_name in replacement_names
        )
        return ProjectionIndexRepairPlan(
            target_names=target_names,
            replacement_names=replacement_names,
            quarantine_names=quarantine_names,
            stale_predicate=stale_predicate,
            expected_predicates=expected_predicates,
            preflight=preflight,
            advisory_lock=advisory_lock,
            advisory_unlock=advisory_unlock,
            build=build,
            validate=validate,
            swap=swap,
            rollback=rollback,
            cleanup=cleanup,
            rollback_cleanup=rollback_cleanup,
        )

    def _key(self, kind: str, record_id: str) -> str:
        return "projection_" + sha256_json([
            self.workspace_id, self.revision_id, kind, record_id,
        ]).removeprefix("sha256:")

    def _get(self, kind: str, record_id: str) -> dict[str, Any] | None:
        row = self.connection.query_one(SQLStatement(
            "SELECT payload, payload_hash FROM formowl_graph_records "
            "WHERE record_id = %(record_id)s AND workspace_id = %(workspace_id)s "
            "AND record_type = 'bounded_graph_projection_v1'",
            {"record_id": self._key(kind, record_id), "workspace_id": self.workspace_id},
        ))
        if row is None:
            return None
        payload = self._checked(row)
        if payload["kind"] != kind or payload["id"] != record_id:
            raise ContractValidationError("graph projection record identity mismatch")
        return payload

    def _checked(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = row["payload"]
        if (
            not isinstance(payload, dict)
            or sha256_json(payload) != row["payload_hash"]
            or payload.get("revision_id") != self.revision_id
            or payload.get("binding_hash") != self._binding_hash
        ):
            raise ContractValidationError("graph projection record seal mismatch")
        return payload

    def _put(self, kind: str, record_id: str, data: dict[str, Any], **keys: str) -> None:
        self._repository.put_graph_record(
            record_id=self._key(kind, record_id), record_type=self._TYPE,
            workspace_id=self.workspace_id,
            permission_scope=data.get("permission_scope", {
                "scope_type": "workspace", "scope_id": self.workspace_id,
                "visibility": "private",
            }),
            payload={
                "revision_id": self.revision_id, "binding_hash": self._binding_hash,
                "kind": kind, "id": record_id, "data": data, **keys,
            },
        )

    def _put_many(
        self, kind: str, records: Iterable[tuple[str, dict[str, Any], dict[str, str]]],
    ) -> None:
        """Same owner rows/hashes/upsert semantics, one bounded SQL statement."""
        batch = self._batch(records)
        # Sequential single-row upserts previously made the last duplicate win.
        unique = {record_id: (data, keys) for record_id, data, keys in batch}
        parameters: dict[str, Any] = {}
        values = []
        for index, (record_id, (data, keys)) in enumerate(unique.items()):
            payload = {
                "revision_id": self.revision_id, "binding_hash": self._binding_hash,
                "kind": kind, "id": record_id, "data": data, **keys,
            }
            fields = {
                "record_id": self._key(kind, record_id), "record_type": self._TYPE,
                "workspace_id": self.workspace_id,
                "permission_scope": to_plain(data.get("permission_scope", {
                    "scope_type": "workspace", "scope_id": self.workspace_id,
                    "visibility": "private",
                })),
                "payload": to_plain(payload), "payload_hash": sha256_json(payload),
            }
            row = []
            for name, value in fields.items():
                parameter = f"{name}_{index}"
                parameters[parameter] = value
                row.append(f"%({parameter})s" + (
                    "::jsonb" if name in {"permission_scope", "payload"} else ""
                ))
            values.append("(" + ", ".join(row) + ")")
        if values:
            self.connection.execute(SQLStatement(
                "INSERT INTO formowl_graph_records "
                "(record_id, record_type, workspace_id, permission_scope, payload, payload_hash) "
                "VALUES " + ", ".join(values) + " ON CONFLICT (record_id) DO UPDATE SET "
                "permission_scope = EXCLUDED.permission_scope, "
                "payload = EXCLUDED.payload, payload_hash = EXCLUDED.payload_hash",
                parameters,
            ))

    def _get_many(self, kind: str, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        keys = {self._key(kind, value): value for value in self._batch(ids)}
        if not keys:
            return {}
        rows = self.connection.query_all(SQLStatement(
            "SELECT record_id, payload, payload_hash FROM formowl_graph_records "
            "WHERE record_id = ANY(%(record_ids)s) AND workspace_id = %(workspace_id)s "
            "AND record_type = 'bounded_graph_projection_v1' LIMIT 256",
            {"record_ids": list(keys), "workspace_id": self.workspace_id},
        ))
        result = {}
        for row in rows:
            payload = self._checked(row)
            if payload["kind"] != kind or keys.get(row["record_id"]) != payload["id"]:
                raise ContractValidationError("graph projection record identity mismatch")
            result[payload["id"]] = payload
        return result

    def _write(self, action: Callable[[], None]) -> None:
        self.connection.begin()
        try:
            # Serialize a revision's writes/seal without locking unrelated revisions.
            lock_key = int(self._key("lock", "state")[-15:], 16)
            self.connection.execute(SQLStatement(
                "SELECT pg_advisory_xact_lock(%(key)s)", {"key": lock_key},
            ))
            state = self._get("state", "manifest")
            if state is not None and state["data"].get("sealed"):
                raise ContractValidationError("sealed graph projection is immutable")
            if state is None:
                self._put("state", "manifest", {"sealed": False, "binding": self.binding})
            action()
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def _batch(self, records: Iterable[T]) -> list[T]:
        batch: list[T] = []
        for record in records:
            if len(batch) == self._MAX_BATCH:
                raise ContractValidationError("graph projection batch exceeds bound")
            batch.append(record)
        return batch

    def put_nodes(self, records: Iterable[GraphProjectionNode]) -> None:
        batch = [GraphProjectionNode.from_dict(item.to_dict()) for item in self._batch(records)]
        self._write(lambda: self._put_many(
            "node", ((node.node_id, node.to_dict(), {}) for node in batch),
        ))

    def put_edges(self, records: Iterable[GraphProjectionEdge]) -> None:
        batch = [GraphProjectionEdge.from_dict(item.to_dict()) for item in self._batch(records)]
        def write() -> None:
            endpoints = sorted({
                node_id for edge in batch for node_id in (edge.source_node_id, edge.target_node_id)
            })
            for offset in range(0, len(endpoints), self._MAX_BATCH):
                ids = endpoints[offset:offset + self._MAX_BATCH]
                if set(self.get_nodes(ids)) != set(ids):
                    raise ContractValidationError("graph projection edge endpoint unavailable")
            self._put_many("edge", (
                (edge.edge_id, edge.to_dict(), {
                    "source_node_id": edge.source_node_id, "target_node_id": edge.target_node_id,
                    "edge_hash": sha256_json(edge.edge_id),
                }) for edge in batch
            ))
        self._write(write)

    def put_memberships(self, records: Iterable[tuple[str, str]]) -> None:
        batch = self._batch(records)
        def write() -> None:
            for _, observation_id in batch:
                _validate_safe_id(observation_id, "observation_id")
            ids = sorted({node_id for node_id, _ in batch})
            if set(self.get_nodes(ids)) != set(ids):
                raise ContractValidationError("graph projection membership node unavailable")
            self._put_many("membership", (
                (sha256_json([node_id, observation_id]), {}, {
                    "node_id": node_id, "observation_id": observation_id,
                }) for node_id, observation_id in batch
            ))
        self._write(write)

    def get_node(self, node_id: str) -> GraphProjectionNode | None:
        row = self._get("node", node_id)
        return None if row is None else GraphProjectionNode.from_dict(row["data"])

    def get_nodes(self, node_ids: Iterable[str]) -> dict[str, GraphProjectionNode]:
        return {key: GraphProjectionNode.from_dict(row["data"])
                for key, row in self._get_many("node", node_ids).items()}

    def get_edge(self, edge_id: str) -> GraphProjectionEdge | None:
        row = self._get("edge", edge_id)
        return None if row is None else GraphProjectionEdge.from_dict(row["data"])

    def _page(
        self, kind: str, *, after_id: str | None = None, limit: int = 256,
        field: str = "id", match: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 256:
            raise ContractValidationError("graph projection page limit must be 1..256")
        # Column expressions are internal constants, never caller-supplied SQL.
        allowed = {
            "id", "node_id", "observation_id", "source_node_id", "target_node_id",
            "edge_hash", "observation_hash", "dense_text_hash",
            "attachment_child_asset_id", "occurrence_id",
        }
        if field not in allowed or (match is not None and match[0] not in allowed):
            raise ContractValidationError("graph projection lookup field is invalid")
        predicate = ""
        if match is not None:
            collation = ' COLLATE "C"' if match[0] in {
                "node_id", "observation_id", "source_node_id", "target_node_id",
            } else ""
            predicate = f" AND (payload->>'{match[0]}'){collation} = %(match)s"
        rows = self.connection.query_all(SQLStatement(
            "SELECT payload, payload_hash FROM formowl_graph_records "
            "WHERE record_type = 'bounded_graph_projection_v1' "
            "AND workspace_id = %(workspace_id)s "
            "AND payload->>'revision_id' = %(revision_id)s "
            "AND payload->>'kind' = %(kind)s "
            f"AND (payload->>'{field}') COLLATE \"C\" > %(after_id)s" + predicate
            + f" ORDER BY (payload->>'{field}') COLLATE \"C\" LIMIT %(limit)s",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id,
             "kind": kind, "after_id": after_id or "", "limit": limit,
             **({"match": match[1]} if match is not None else {})},
        ))
        return [self._checked(row) for row in rows]

    def iter_nodes(self, *, after_id: str | None = None, limit: int = 256) -> list[GraphProjectionNode]:
        return [GraphProjectionNode.from_dict(row["data"]) for row in self._page(
            "node", after_id=after_id, limit=limit,
        )]

    def iter_edges(self, *, after_id: str | None = None, limit: int = 256) -> list[GraphProjectionEdge]:
        return [GraphProjectionEdge.from_dict(row["data"]) for row in self._page(
            "edge", after_id=after_id, limit=limit,
        )]

    def incident_edges(
        self, node_id: str, *, after_id: str | None = None, limit: int = 64,
    ) -> list[GraphProjectionEdge]:
        # Two indexed keyset pages avoid OR + a whole-revision edge scan.
        rows = {}
        for match_field in ("source_node_id", "target_node_id"):
            for row in self._page(
                "edge", after_id=after_id, limit=limit, match=(match_field, node_id),
            ):
                rows[row["id"]] = row
        return [GraphProjectionEdge.from_dict(rows[key]["data"]) for key in sorted(rows)[:limit]]

    def observation_ids_for_node(
        self, node_id: str, *, after_id: str | None = None, limit: int = 256,
    ) -> list[str]:
        return [row["observation_id"] for row in self._page(
            "membership", after_id=after_id, limit=limit, field="observation_id",
            match=("node_id", node_id),
        )]

    def nodes_for_observation(
        self, observation_id: str, *, after_id: str | None = None, limit: int = 64,
    ) -> list[GraphProjectionNode]:
        result = []
        for row in self._page(
            "membership", after_id=after_id, limit=limit, field="node_id",
            match=("observation_id", observation_id),
        ):
            node = self.get_node(row["node_id"])
            if node is None:
                raise ContractValidationError("graph projection membership endpoint unavailable")
            result.append(node)
        return result

    def edge_for_hash(self, edge_hash: str) -> GraphProjectionEdge | None:
        rows = self._page("edge", match=("edge_hash", edge_hash), limit=2)
        if len(rows) > 1:
            raise ContractValidationError("graph projection edge hash is ambiguous")
        return GraphProjectionEdge.from_dict(rows[0]["data"]) if rows else None

    def put_helpers(self, records: Iterable[dict[str, Any]]) -> None:
        """Persist only bound references/hash/lineage, never copy source bodies."""
        batch = self._batch(records)
        def write() -> None:
            rows = []
            for item in batch:
                _require_fields(item, (
                    "observation_id", "observation_hash", "source_scope_id", "reference", "lineage",
                    "permission_scope",
                ), "helper")
                _validate_safe_id(item["observation_id"], "observation_id")
                validate_permission_scope(item["permission_scope"])
                rows.append((item["observation_id"], to_plain(item), {
                    "observation_hash": item["observation_hash"],
                    "attachment_child_asset_id": item.get("attachment_child_asset_id", ""),
                    "occurrence_id": item.get("occurrence_id", ""),
                }))
            self._put_many("helper", rows)
        self._write(write)

    def get_helper(self, observation_id: str) -> dict[str, Any] | None:
        row = self._get("helper", observation_id)
        return None if row is None else row["data"]

    def helper_for_hash(self, observation_hash: str) -> dict[str, Any] | None:
        rows = self._page("helper", match=("observation_hash", observation_hash), limit=2)
        if len(rows) > 1:
            raise ContractValidationError("graph helper hash binding is ambiguous")
        return rows[0]["data"] if rows else None

    def helpers_for_hashes(
        self, observation_hashes: Iterable[str],
    ) -> dict[str, dict[str, Any]]:
        hashes = list(dict.fromkeys(self._batch(observation_hashes)))
        if not hashes:
            return {}
        rows = self.connection.query_all(SQLStatement(
            "SELECT payload, payload_hash FROM formowl_graph_records "
            "WHERE record_type = 'bounded_graph_projection_v1' "
            "AND workspace_id = %(workspace_id)s "
            "AND payload->>'revision_id' = %(revision_id)s "
            "AND payload->>'kind' = 'helper' "
            "AND payload->>'observation_hash' = ANY(%(observation_hashes)s) "
            "LIMIT 257",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id,
             "observation_hashes": hashes},
        ))
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload = self._checked(row)
            if payload["kind"] != "helper":
                raise ContractValidationError("graph projection record identity mismatch")
            data = payload.get("data")
            if (
                not isinstance(data, dict)
                or payload.get("id") != data.get("observation_id")
                or payload.get("observation_hash") != data.get("observation_hash")
            ):
                raise ContractValidationError("graph projection record identity mismatch")
            observation_hash = payload.get("observation_hash")
            if observation_hash not in hashes:
                raise ContractValidationError("graph helper hash binding mismatch")
            if observation_hash in result:
                raise ContractValidationError("graph helper hash binding is ambiguous")
            result[observation_hash] = data
        return result

    def helper_for_attachment_asset(self, child_asset_id: str) -> dict[str, Any] | None:
        if not child_asset_id:
            return None
        rows = self._page("helper", match=("attachment_child_asset_id", child_asset_id), limit=2)
        if len(rows) > 1:
            raise ContractValidationError("indexed attachment parent is ambiguous")
        return rows[0]["data"] if rows else None

    def iter_helpers(self, *, after_id: str | None = None, limit: int = 256) -> list[dict[str, Any]]:
        return [row["data"] for row in self._page("helper", after_id=after_id, limit=limit)]

    def iter_helpers_for_source_family(
        self,
        source_family: str,
        *,
        after_id: str | None = None,
        limit: int = 256,
    ) -> list[dict[str, Any]]:
        """Page retrieval-eligible helpers for one already-authorized family."""

        if source_family not in {"mail", "document_text"}:
            raise ContractValidationError("graph helper source family is invalid")
        if after_id is not None:
            _validate_safe_id(after_id, "after_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 256:
            raise ContractValidationError("graph projection page limit must be 1..256")
        rows = self.connection.query_all(SQLStatement(
            "SELECT payload, payload_hash FROM formowl_graph_records "
            "WHERE record_type = 'bounded_graph_projection_v1' "
            "AND workspace_id = %(workspace_id)s "
            "AND payload->>'revision_id' = %(revision_id)s "
            "AND payload->>'kind' = 'helper' "
            "AND payload->'data'->>'retrieval' = 'true' "
            "AND payload->'data'->>'retrieval_source_family' = %(source_family)s "
            "AND (payload->>'id') COLLATE \"C\" > %(after_id)s "
            "ORDER BY (payload->>'id') COLLATE \"C\" LIMIT %(limit)s",
            {
                "workspace_id": self.workspace_id,
                "revision_id": self.revision_id,
                "source_family": source_family,
                "after_id": after_id or "",
                "limit": limit,
            },
        ))
        return [self._checked(row)["data"] for row in rows]

    def helpers_for_occurrence(
        self, occurrence_id: str, *, after_id: str | None = None, limit: int = 64,
    ) -> list[dict[str, Any]]:
        return [row["data"] for row in self._page(
            "helper", after_id=after_id, limit=limit, match=("occurrence_id", occurrence_id),
        )]

    def put_candidates(self, records: Iterable[dict[str, Any]]) -> None:
        batch = self._batch(records)
        self._write(lambda: self._put_candidates(batch))

    def _put_candidates(
        self,
        batch: list[dict[str, Any]],
        *,
        helpers: Mapping[str, dict[str, Any]] | None = None,
    ) -> None:
        for item in batch:
            _require_fields(item, (
                "source_observation_hash", "dense_evidence_text_hash", "searchable_tokens",
                "ordinal", "bundle_id", "message_occurrence_hash",
            ), "candidate")
            if "dense_vector" in item:
                raise ContractValidationError("candidate must reference a persisted unique vector")
        validated = []
        if helpers is None:
            helpers = self.helpers_for_hashes(
                item["source_observation_hash"] for item in batch
            )
        for item in batch:
            helper = helpers.get(item["source_observation_hash"])
            if helper is None:
                raise ContractValidationError("candidate source binding is unavailable")
            validated.append((
                item["source_observation_hash"], to_plain(item),
                {"dense_text_hash": item["dense_evidence_text_hash"],
                 "ordinal": str(item["ordinal"])},
            ))
        self._put_many("candidate", validated)

    def candidate_for_observation(self, observation_hash: str) -> dict[str, Any] | None:
        row = self._get("candidate", observation_hash)
        return None if row is None else row["data"]

    def candidates_for_dense_text(
        self, text_hash: str, *, after_id: str | None = None, limit: int = 256,
    ) -> list[dict[str, Any]]:
        return [row["data"] for row in self._page(
            "candidate", after_id=after_id, limit=limit, match=("dense_text_hash", text_hash),
        )]

    def put_postings(self, records: Iterable[dict[str, Any]]) -> None:
        batch = self._batch(records)
        self._write(lambda: self._put_postings(batch))

    def _put_postings(self, batch: list[dict[str, Any]]) -> None:
        validated = []
        for item in batch:
            _require_fields(item, ("token", "source_observation_hash", "document_length"), "posting")
            if not isinstance(item["document_length"], int) or item["document_length"] < 1:
                raise ContractValidationError("posting document length must be positive")
            validated.append((
                sha256_json([item["token"], item["source_observation_hash"]]),
                to_plain(item), {"token": item["token"]},
            ))
        self._put_many("posting", validated)

    def persist_hybrid_batch(
        self,
        posting_batches: Iterable[Iterable[dict[str, Any]]],
        vectors: Iterable[dict[str, Any]],
        candidates: Iterable[dict[str, Any]],
        *,
        batch_id: str,
        source_cursor: str,
        binding: dict[str, Any],
        candidate_count: int | None = None,
        resume_fingerprint: str | None = None,
    ) -> None:
        """Persist one bounded hybrid callback as one transaction.

        Posting fanout remains split into bounded statements; the transaction
        covers every statement and advances the checkpoint only after all
        projection writes succeed.
        """
        posting_batches = (self._batch(batch) for batch in posting_batches)
        vector_batch = self._batch(vectors)
        candidate_batch = self._batch(candidates)
        if sha256_json(to_plain(binding)) != self._binding_hash:
            raise ContractValidationError("graph projection checkpoint authority mismatch")
        if candidate_count is not None or resume_fingerprint is not None:
            _validate_safe_id(source_cursor, "candidate source cursor")
            if (
                isinstance(candidate_count, bool) or not isinstance(candidate_count, int)
                or not candidate_batch or candidate_count < len(candidate_batch)
                or [item.get("ordinal") for item in candidate_batch]
                != list(range(candidate_count - len(candidate_batch), candidate_count))
            ):
                raise ContractValidationError("candidate checkpoint count is invalid")

        def write() -> None:
            candidate_helpers: Mapping[str, dict[str, Any]] | None = None
            if candidate_count is not None:
                previous = self.hybrid_build_checkpoint(resume_fingerprint=resume_fingerprint)
                if (
                    candidate_count != (previous["candidate_count"] if previous else 0)
                    + len(candidate_batch)
                    or (previous is not None and source_cursor <= previous["source_cursor"])
                ):
                    raise ContractValidationError("candidate checkpoint does not advance")
                candidate_helpers = self.helpers_for_hashes(
                    item["source_observation_hash"] for item in candidate_batch
                )
                helper = candidate_helpers.get(
                    candidate_batch[-1]["source_observation_hash"]
                )
                if (
                    helper is None or helper["observation_hash"]
                    != candidate_batch[-1]["source_observation_hash"]
                    or helper.get("observation_id") != source_cursor
                ):
                    raise ContractValidationError("candidate checkpoint source binding mismatch")
            for batch in posting_batches:
                self._put_postings(batch)
            self._put_dense_vectors(vector_batch)
            self._put_candidates(candidate_batch, helpers=candidate_helpers)
            self._put("checkpoint", batch_id, {"source_cursor": source_cursor})
            if candidate_count is not None:
                self._put("checkpoint", "candidate_build_progress_v1", {
                    "source_cursor": source_cursor, "candidate_count": candidate_count,
                    "resume_fingerprint": resume_fingerprint,
                })

        self._write(write)

    def hybrid_build_checkpoint(self, *, resume_fingerprint: str) -> dict[str, Any] | None:
        """Read one sealed-payload checkpoint, never scan legacy batch markers."""
        if (
            not isinstance(resume_fingerprint, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", resume_fingerprint) is None
        ):
            raise ContractValidationError("candidate checkpoint fingerprint is invalid")
        row = self._get("checkpoint", "candidate_build_progress_v1")
        if row is None:
            return None  # Legacy builds replay idempotently from the start.
        data = row["data"]
        if (
            not isinstance(data, dict)
            or set(data) != {"source_cursor", "candidate_count", "resume_fingerprint"}
            or data["resume_fingerprint"] != resume_fingerprint
            or isinstance(data["candidate_count"], bool)
            or not isinstance(data["candidate_count"], int) or data["candidate_count"] < 1
        ):
            raise ContractValidationError("candidate checkpoint binding is invalid")
        _validate_safe_id(data["source_cursor"], "candidate source cursor")
        return dict(data)

    def put_token_statistics(self, records: Iterable[dict[str, Any]]) -> None:
        batch = self._batch(records)
        self._write(lambda: [
            self._put("token_stat", sha256_json(item["token"]), to_plain(item), token=item["token"])
            for item in batch
        ])

    def put_corpus_statistics(self, statistics: dict[str, Any]) -> None:
        _require_fields(statistics, ("document_count", "average_document_length"), "corpus statistics")
        self._write(lambda: self._put("corpus_stat", "corpus", to_plain(statistics)))

    def corpus_statistics(self) -> dict[str, Any]:
        row = self._get("corpus_stat", "corpus")
        if row is None:
            raise ContractValidationError("graph index corpus statistics are unavailable")
        return row["data"]

    def token_statistics(self, tokens: Iterable[str]) -> dict[str, int]:
        batch = self._batch(tokens)
        rows = self._get_many("token_stat", (sha256_json(token) for token in batch))
        return {
            token: rows[sha256_json(token)]["data"]["document_frequency"]
            if sha256_json(token) in rows else 0
            for token in batch
        }

    def document_frequency(self, tokens: Iterable[str]) -> dict[str, int]:
        return self.token_statistics(tokens)

    def source_family_lexical_lookup(
        self,
        query_tokens: Iterable[str],
        *,
        source_family: str,
        limit: int = 256,
        timeout_ms: int,
    ) -> list[str]:
        """Return a bounded posting shortlist for one sealed source family.

        The result is only an accelerator.  Callers must hydrate each hash
        through the ordinary helper/authority path before projecting evidence.
        """
        if source_family not in {"mail", "document_text"}:
            raise ContractValidationError("graph source family is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 256:
            raise ContractValidationError("graph lexical lookup limit is invalid")
        tokens = sorted(set(self._batch(query_tokens)))
        if not tokens:
            return []
        rows = self._ranked_query(SQLStatement(
            "SELECT p.payload->'data'->>'source_observation_hash' AS observation_hash "
            "FROM formowl_graph_records p "
            "JOIN formowl_graph_records h ON "
            "h.record_type = 'bounded_graph_projection_v1' "
            "AND h.workspace_id = p.workspace_id "
            "AND h.payload->>'revision_id' = p.payload->>'revision_id' "
            "AND h.payload->>'kind' = 'helper' "
            "AND h.payload->>'observation_hash' = "
            "p.payload->'data'->>'source_observation_hash' "
            "WHERE p.record_type = 'bounded_graph_projection_v1' "
            "AND p.workspace_id = %(workspace_id)s "
            "AND p.payload->>'revision_id' = %(revision_id)s "
            "AND p.payload->>'kind' = 'posting' "
            # Reuse the digest expression index; raw equality below is still
            # authoritative, including when different tokens share a digest.
            "AND md5(p.payload->>'token') = ANY(ARRAY("
            "SELECT md5(t.token) FROM unnest(%(tokens)s::text[]) AS t(token))) "
            "AND p.payload->>'token' = ANY(%(tokens)s) "
            "AND h.payload->'data'->>'retrieval_source_family' = %(source_family)s "
            "GROUP BY observation_hash "
            "ORDER BY COUNT(DISTINCT p.payload->>'token') DESC, "
            # PostgreSQL output aliases must stand alone in ORDER BY.
            "(p.payload->'data'->>'source_observation_hash') COLLATE \"C\" LIMIT %(limit)s",
            {
                "workspace_id": self.workspace_id,
                "revision_id": self.revision_id,
                "tokens": tokens,
                "source_family": source_family,
                "limit": limit,
            },
        ), timeout_ms)
        result = []
        for row in rows:
            observation_hash = row.get("observation_hash")
            if not isinstance(observation_hash, str) or not observation_hash:
                raise ContractValidationError("graph lexical lookup result is invalid")
            result.append(observation_hash)
        return result

    def identifier_present(self, tokens: Iterable[str]) -> bool:
        rows = self._ranked_query(SQLStatement(
            "SELECT record_id FROM formowl_graph_records "
            "WHERE record_type = 'bounded_graph_projection_v1' "
            "AND workspace_id = %(workspace_id)s AND payload->>'revision_id' = %(revision_id)s "
            "AND payload->>'kind' = 'candidate' AND ("
            "payload->'data'->'protected_identifier_tokens' ?| %(tokens)s OR "
            "payload->'data'->'observation_protected_identifier_tokens' ?| %(tokens)s) LIMIT 1",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id,
             "tokens": self._batch(tokens)},
        ), 1500)
        return bool(rows)

    def _requested_families(self, values: Iterable[str] | None) -> list[str] | None:
        if values is None:
            return None
        families = self._batch(values)
        if any(family not in ("mail", "attachment_table", "document_text") for family in families):
            raise ContractValidationError("requested source family is invalid")
        return sorted(set(families))

    @staticmethod
    def _candidate_family_sql() -> str:
        # The caller supplies candidate alias c. Tags come from the ordinary
        # inline-aware classifier on genuine authorized records, not top-k.
        return (
            "EXISTS (SELECT 1 FROM formowl_graph_records h "
            "WHERE h.record_type = 'bounded_graph_projection_v1' "
            "AND h.workspace_id = c.workspace_id "
            "AND h.payload->>'revision_id' = c.payload->>'revision_id' "
            "AND h.payload->>'kind' = 'helper' "
            "AND h.payload->>'observation_hash' = c.payload->>'id' "
            "AND h.payload->'data'->>'retrieval_source_family' = ANY(%(families)s))"
        )

    def candidate_tokens_present(
        self, tokens: Iterable[str], field: str, *,
        requested_source_families: Iterable[str] | None = None,
    ) -> set[str]:
        if field not in ("observation_tokens", "observation_protected_identifier_tokens"):
            raise ContractValidationError("candidate token field is invalid")
        requested = sorted(set(self._batch(tokens)))
        families = self._requested_families(requested_source_families)
        rows = self._ranked_query(SQLStatement(
            "SELECT t.token FROM unnest(%(tokens)s::text[]) AS t(token) "
            "WHERE EXISTS (SELECT 1 FROM formowl_graph_records c "
            "WHERE c.record_type = 'bounded_graph_projection_v1' "
            "AND c.workspace_id = %(workspace_id)s "
            "AND c.payload->>'revision_id' = %(revision_id)s "
            "AND c.payload->>'kind' = 'candidate' "
            "AND c.payload->'data'->'" + field + "' ? t.token "
            "AND (%(families_unrestricted)s OR " + self._candidate_family_sql() + ")) "
            "ORDER BY t.token COLLATE \"C\" LIMIT 256",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id,
             "tokens": requested, "families": families or [],
             "families_unrestricted": families is None},
        ), 1500)
        return {row["token"] for row in rows}

    def candidate_count_for_families(self, source_families: Iterable[str]) -> int:
        families = self._requested_families(source_families)
        if families is None:
            raise ContractValidationError("source family count requires an explicit scope")
        rows = self._ranked_query(SQLStatement(
            "SELECT COUNT(*) AS candidate_count FROM formowl_graph_records c "
            "WHERE c.record_type = 'bounded_graph_projection_v1' "
            "AND c.workspace_id = %(workspace_id)s "
            "AND c.payload->>'revision_id' = %(revision_id)s "
            "AND c.payload->>'kind' = 'candidate' AND " + self._candidate_family_sql(),
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id,
             "families": families},
        ), 1500)
        return int(rows[0]["candidate_count"])

    def node_candidates_by_terms(
        self, *, tokens: Iterable[str], term_hashes: Iterable[str],
        after_id: str | None = None, limit: int = 256,
        requested_source_families: Iterable[str] | None = None,
    ) -> list[GraphProjectionNode]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 256:
            raise ContractValidationError("node candidate page limit must be 1..256")
        if after_id is not None:
            _validate_safe_id(after_id, "after_id")
        families = self._requested_families(requested_source_families)
        rows = self._ranked_query(SQLStatement(
            "SELECT n.payload, n.payload_hash FROM formowl_graph_records n "
            "WHERE n.record_type = 'bounded_graph_projection_v1' "
            "AND n.workspace_id = %(workspace_id)s "
            "AND n.payload->>'revision_id' = %(revision_id)s AND n.payload->>'kind' = 'node' "
            "AND (n.payload->>'id') COLLATE \"C\" > %(after_id)s AND ("
            "n.payload->'data'->'properties'->'relation_searchable_tokens' ?| %(tokens)s OR "
            "n.payload->'data'->'properties'->'relation_source_term_hashes' ?| %(hashes)s OR "
            "n.payload->'data'->'properties'->'relation_protected_term_hashes' ?| %(hashes)s) "
            "AND (%(families_unrestricted)s OR EXISTS ("
            "SELECT 1 FROM formowl_graph_records m JOIN formowl_graph_records h ON "
            "h.record_type = 'bounded_graph_projection_v1' "
            "AND h.workspace_id = %(workspace_id)s "
            "AND h.payload->>'revision_id' = %(revision_id)s "
            "AND h.payload->>'kind' = 'helper' "
            "AND (h.payload->>'id') COLLATE \"C\" = m.payload->>'observation_id' "
            "JOIN formowl_graph_records c ON c.record_type = 'bounded_graph_projection_v1' "
            "AND c.workspace_id = %(workspace_id)s "
            "AND c.payload->>'revision_id' = %(revision_id)s "
            "AND c.payload->>'kind' = 'candidate' "
            "AND (c.payload->>'id') COLLATE \"C\" = h.payload->>'observation_hash' "
            "WHERE m.record_type = 'bounded_graph_projection_v1' "
            "AND m.workspace_id = %(workspace_id)s "
            "AND m.payload->>'revision_id' = %(revision_id)s "
            "AND m.payload->>'kind' = 'membership' "
            "AND (m.payload->>'node_id') COLLATE \"C\" = n.payload->>'id' "
            "AND h.payload->'data'->>'retrieval_source_family' = ANY(%(families)s))) "
            "ORDER BY (n.payload->>'id') COLLATE \"C\" LIMIT %(limit)s",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id,
             "tokens": sorted(set(self._batch(tokens))),
             "hashes": sorted(set(self._batch(term_hashes))), "after_id": after_id or "",
             "limit": limit, "families": families or [],
             "families_unrestricted": families is None},
        ), 1500)
        return [GraphProjectionNode.from_dict(self._checked(row)["data"]) for row in rows]

    def candidate_by_ordinal(self, ordinal: int) -> dict[str, Any] | None:
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            raise ContractValidationError("candidate ordinal must be nonnegative")
        rows = self.connection.query_all(SQLStatement(
            "SELECT payload, payload_hash FROM formowl_graph_records "
            "WHERE record_type = 'bounded_graph_projection_v1' "
            "AND workspace_id = %(workspace_id)s AND payload->>'revision_id' = %(revision_id)s "
            "AND payload->>'kind' = 'candidate' AND (payload->>'ordinal')::bigint = %(ordinal)s "
            "LIMIT 2",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id, "ordinal": ordinal},
        ))
        if len(rows) > 1:
            raise ContractValidationError("candidate ordinal binding is ambiguous")
        return self._checked(rows[0])["data"] if rows else None

    def iter_candidates(
        self, *, after_ordinal: int | None = None, limit: int = 256,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 256:
            raise ContractValidationError("candidate page limit must be 1..256")
        if after_ordinal is not None and (
            isinstance(after_ordinal, bool) or not isinstance(after_ordinal, int) or after_ordinal < 0
        ):
            raise ContractValidationError("candidate page cursor must be nonnegative")
        rows = self.connection.query_all(SQLStatement(
            "SELECT payload, payload_hash FROM formowl_graph_records "
            "WHERE record_type = 'bounded_graph_projection_v1' "
            "AND workspace_id = %(workspace_id)s AND payload->>'revision_id' = %(revision_id)s "
            "AND payload->>'kind' = 'candidate' AND (payload->>'ordinal')::bigint > %(after)s "
            "ORDER BY (payload->>'ordinal')::bigint LIMIT %(limit)s",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id,
             "after": -1 if after_ordinal is None else after_ordinal, "limit": limit},
        ))
        return [self._checked(row)["data"] for row in rows]

    def finalize_candidate_order_and_statistics(self) -> dict[str, Any]:
        """Build-only global order/DF, without loading a candidate corpus in RAM."""
        order = (
            "(payload->'data'->>'bundle_id') COLLATE \"C\", "
            "(payload->'data'->>'source_observation_hash') COLLATE \"C\", "
            "(payload->'data'->>'message_occurrence_hash') COLLATE \"C\""
        )
        cursor, count, length_sum = ("", "", ""), 0, 0
        digest = hashlib.sha256(b"[")
        while rows := self.connection.query_all(SQLStatement(
            "SELECT payload, payload_hash FROM formowl_graph_records "
            "WHERE record_type = 'bounded_graph_projection_v1' "
            "AND workspace_id = %(workspace_id)s AND payload->>'revision_id' = %(revision_id)s "
            "AND payload->>'kind' = 'candidate' AND (" + order + ") > "
            "(%(bundle)s, %(observation)s, %(occurrence)s) ORDER BY " + order + " LIMIT 256",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id,
             "bundle": cursor[0], "observation": cursor[1], "occurrence": cursor[2]},
        )):
            batch = []
            for row in rows:
                item = dict(self._checked(row)["data"])
                item["ordinal"] = count
                if count:
                    digest.update(b",")
                digest.update(json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8"))
                count += 1
                length_sum += len(item["searchable_tokens"])
                batch.append(item)
            self.put_candidates(batch)
            item = batch[-1]
            cursor = (item["bundle_id"], item["source_observation_hash"], item["message_occurrence_hash"])
            self.checkpoint("candidate_order", json.dumps(cursor), self.binding)
        digest.update(b"]")
        token_cursor = ""
        while rows := self.connection.query_all(SQLStatement(
            "SELECT payload->>'token' AS token, COUNT(*) AS document_frequency "
            "FROM formowl_graph_records WHERE record_type = 'bounded_graph_projection_v1' "
            "AND workspace_id = %(workspace_id)s AND payload->>'revision_id' = %(revision_id)s "
            "AND payload->>'kind' = 'posting' AND (payload->>'token') COLLATE \"C\" > %(after)s "
            "GROUP BY payload->>'token' ORDER BY (payload->>'token') COLLATE \"C\" LIMIT 256",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id, "after": token_cursor},
        )):
            self.put_token_statistics(rows)
            token_cursor = rows[-1]["token"]
        statistics = {
            "document_count": count, "average_document_length": length_sum / count if count else 0.0,
            # Owner-record content seal; NOT a fabricated hybrid method fingerprint.
            "candidate_content_fingerprint": "sha256:" + digest.hexdigest(),
        }
        self.put_corpus_statistics(statistics)
        return statistics

    def put_dense_vectors(self, records: Iterable[dict[str, Any]]) -> None:
        batch = self._batch(records)
        self._write(lambda: self._put_dense_vectors(batch))

    def _put_dense_vectors(self, batch: list[dict[str, Any]]) -> None:
        from formowl_graph.index.pgvector import (
            EmbeddingManifest, PgVectorQueryBuilder, VectorIndexRow,
        )
        query_builder = PgVectorQueryBuilder(
            embedding_manifest=EmbeddingManifest(
                embedding_model=self._binding_hash, embedding_dimension=384,
            ),
        )
        def write() -> None:
            statements = {}
            references = []
            for item in batch:
                vector = tuple(float(value) for value in item["vector"])
                if len(vector) != 384 or not all(math.isfinite(value) for value in vector):
                    raise ContractValidationError("pinned dense vector must have 384 finite components")
                statement = query_builder.upsert_statement(VectorIndexRow(
                    vector_id=self._key("vector", item["text_hash"]),
                    source_type=self._key("vectors", "scope"), source_id=item["text_hash"],
                    embedding=list(vector), embedding_manifest_hash=self._binding_hash,
                    permission_scope={
                        "scope_type": "workspace", "scope_id": self.workspace_id, "visibility": "private",
                    },
                ))
                # Validate every occurrence before last-write-wins deduplication.
                statements[item["text_hash"]] = statement
                # Include the numerical binding in the revision seal, without a second vector copy.
                references.append((
                    item["text_hash"], {"vector_hash": sha256_json(list(vector))}, {},
                ))
            if statements:
                values = []
                parameters = {}
                for index, statement in enumerate(statements.values()):
                    prefix, remainder = statement.sql.split("VALUES ", 1)
                    value, conflict = remainder.split(" ON CONFLICT ", 1)
                    values.append(re.sub(
                        r"%\(([^)]+)\)s", lambda match: f"%({match[1]}_{index})s", value,
                    ))
                    parameters.update({
                        f"{name}_{index}": value for name, value in statement.parameters.items()
                    })
                self.connection.execute(SQLStatement(
                    prefix + "VALUES " + ", ".join(values) + " ON CONFLICT " + conflict,
                    parameters,
                ))
            self._put_many("vector_ref", references)
        write()

    def get_dense_vector(self, text_hash: str) -> tuple[float, ...]:
        row = self.connection.query_one(SQLStatement(
            "SELECT embedding::text AS embedding FROM formowl_vector_index "
            "WHERE vector_id = %(vector_id)s AND embedding_manifest_hash = %(binding)s "
            "AND source_type = %(source_type)s AND index_state = 'ready'",
            {"vector_id": self._key("vector", text_hash), "binding": self._binding_hash,
             "source_type": self._key("vectors", "scope")},
        ))
        if row is None:
            raise ContractValidationError("selected dense vector is unavailable")
        vector = tuple(json.loads(row["embedding"]))
        # pgvector stores float32; parse/repack to recover the exact float values,
        # not the decimal display representation used by PostgreSQL.
        import struct
        vector = struct.unpack("<384f", struct.pack("<384f", *vector))
        reference = self._get("vector_ref", text_hash)
        if reference is None or sha256_json(list(vector)) != reference["data"]["vector_hash"]:
            raise ContractValidationError("selected dense vector content seal mismatch")
        return vector

    def _ranked_query(self, statement: SQLStatement, timeout_ms: int) -> list[dict[str, Any]]:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 1 <= timeout_ms <= 1500:
            raise ContractValidationError("query timeout must fit the frozen 1500ms ceiling")
        state = self._get("state", "manifest")
        if state is None or not state["data"].get("sealed"):
            raise ContractValidationError("ranked query requires a sealed revision")
        self.connection.begin()
        try:
            self.connection.execute(SQLStatement(
                "SELECT set_config('statement_timeout', %(timeout)s, true)",
                {"timeout": str(timeout_ms)},
            ))
            result = self.connection.query_all(statement)
            self.connection.commit()
            return result
        except BaseException:
            self.connection.rollback()
            raise

    def lexical_ranked(
        self, query_tokens: Iterable[str], *, limit: int = 64, timeout_ms: int,
    ) -> list[tuple[str, float]]:
        tokens = sorted(set(self._batch(query_tokens)))
        if not 1 <= limit <= 256:
            raise ContractValidationError("ranked page limit must be 1..256")
        stats = self.corpus_statistics()
        # Same unique-token TF=1, k1=1.2, b=.75 as the existing Python scorer.
        # SQL does not manufacture evidence or change source authorization.
        statement = SQLStatement(
            "SELECT p.payload->'data'->>'source_observation_hash' AS observation_hash, "
            "SUM(LN(1.0 + ((%(count)s - (s.payload->'data'->>'document_frequency')::float8 + 0.5) "
            "/ ((s.payload->'data'->>'document_frequency')::float8 + 0.5))) "
            "* (2.2 / (1.0 + 1.2 * (0.25 + 0.75 * "
            "(p.payload->'data'->>'document_length')::float8 / %(average)s)))) AS score "
            "FROM formowl_graph_records p JOIN formowl_graph_records s ON "
            "s.record_type = 'bounded_graph_projection_v1' AND s.workspace_id = p.workspace_id "
            "AND s.payload->>'revision_id' = p.payload->>'revision_id' "
            "AND s.payload->>'kind' = 'token_stat' "
            "AND md5(s.payload->>'token') = md5(p.payload->>'token') "
            "AND s.payload->>'token' = p.payload->>'token' "
            "WHERE p.record_type = 'bounded_graph_projection_v1' "
            "AND p.workspace_id = %(workspace_id)s AND p.payload->>'revision_id' = %(revision_id)s "
            "AND p.payload->>'kind' = 'posting' "
            "AND md5(p.payload->>'token') = ANY(ARRAY("
            "SELECT md5(t.token) FROM unnest(%(tokens)s::text[]) AS t(token))) "
            "AND p.payload->>'token' = ANY(%(tokens)s) "
            "GROUP BY observation_hash ORDER BY score DESC, "
            "(p.payload->'data'->>'source_observation_hash') COLLATE \"C\" "
            "LIMIT %(limit)s",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id, "tokens": tokens,
             "count": stats["document_count"], "average": max(stats["average_document_length"], 1.0),
             "limit": limit},
        )
        return [(row["observation_hash"], float(row["score"])) for row in self._ranked_query(
            statement, timeout_ms,
        )]

    def hybrid_ranked(
        self, *, query_tokens: Iterable[str], query_vector: Iterable[float],
        limit: int, timeout_ms: int,
        allowed_source_observation_hashes: Iterable[str] | None = None,
        requested_source_families: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Exact global positive ranks, then allowed-source top-k union.

        Database computation may exceed the deadline at scale; that is an
        explicit failure, never permission to silently switch to ANN or a
        different corpus. Only <=2*limit scored occurrences cross this port.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 256:
            raise ContractValidationError("hybrid result limit must be 1..256")
        tokens = sorted(set(self._batch(query_tokens)))
        families = self._requested_families(requested_source_families)
        vector = tuple(query_vector)
        if len(vector) != 384 or not all(math.isfinite(value) for value in vector):
            raise ContractValidationError("query vector must have 384 finite components")
        stats = self.corpus_statistics()
        lexical = (
            "SELECT p.payload->'data'->>'source_observation_hash' AS observation_hash, "
            "SUM(LN(1.0 + ((%(count)s - (s.payload->'data'->>'document_frequency')::float8 + 0.5) "
            "/ ((s.payload->'data'->>'document_frequency')::float8 + 0.5))) "
            "* (2.2 / (1.0 + 1.2 * (0.25 + 0.75 * "
            "(p.payload->'data'->>'document_length')::float8 / %(average)s)))) AS bm25_score "
            "FROM formowl_graph_records p JOIN formowl_graph_records s ON "
            "s.record_type = 'bounded_graph_projection_v1' AND s.workspace_id = p.workspace_id "
            "AND s.payload->>'revision_id' = p.payload->>'revision_id' "
            "AND s.payload->>'kind' = 'token_stat' "
            "AND s.payload->>'token' = p.payload->>'token' "
            "WHERE p.record_type = 'bounded_graph_projection_v1' AND p.workspace_id = %(workspace_id)s "
            "AND p.payload->>'revision_id' = %(revision_id)s AND p.payload->>'kind' = 'posting' "
            "AND md5(p.payload->>'token') = ANY(ARRAY("
            "SELECT md5(t.token) FROM unnest(%(tokens)s::text[]) AS t(token))) "
            "AND p.payload->>'token' = ANY(%(tokens)s) GROUP BY observation_hash"
        )
        statement = SQLStatement(
            "WITH lexical AS (" + lexical + "), scored AS ("
            "SELECT c.payload->>'id' AS source_observation_hash, "
            "(c.payload->>'ordinal')::bigint AS ordinal, "
            "COALESCE(l.bm25_score, 0.0) AS bm25_score, "
            "CASE WHEN %(query_nonzero)s AND (v.embedding <#> v.embedding) < 0 "
            "THEN 1.0 - (v.embedding <=> %(query_vector)s::vector) ELSE 0.0 END AS dense_score "
            "FROM formowl_graph_records c JOIN formowl_vector_index v ON "
            "v.source_type = %(vector_scope)s AND v.embedding_manifest_hash = %(binding)s "
            "AND v.index_state = 'ready' AND v.source_id = c.payload->>'dense_text_hash' "
            "LEFT JOIN lexical l ON l.observation_hash = c.payload->>'id' "
            "WHERE c.record_type = 'bounded_graph_projection_v1' AND c.workspace_id = %(workspace_id)s "
            "AND c.payload->>'revision_id' = %(revision_id)s AND c.payload->>'kind' = 'candidate'), "
            "ranked AS (SELECT *, CASE WHEN bm25_score > 0 THEN "
            "ROW_NUMBER() OVER (ORDER BY bm25_score DESC, ordinal) END AS bm25_rank, "
            "CASE WHEN dense_score > 0 THEN ROW_NUMBER() OVER (ORDER BY dense_score DESC, ordinal) "
            "END AS dense_rank FROM scored), eligible AS (SELECT * FROM ranked "
            "WHERE (%(unrestricted)s OR source_observation_hash = ANY(%(allowed)s)) "
            "AND (%(families_unrestricted)s OR EXISTS (SELECT 1 FROM formowl_graph_records c "
            "WHERE c.record_type = 'bounded_graph_projection_v1' "
            "AND c.workspace_id = %(workspace_id)s "
            "AND c.payload->>'revision_id' = %(revision_id)s "
            "AND c.payload->>'kind' = 'candidate' "
            "AND c.payload->>'id' = ranked.source_observation_hash AND "
            + self._candidate_family_sql() + "))), "
            "chosen AS ((SELECT source_observation_hash FROM eligible WHERE bm25_score > 0 "
            "ORDER BY bm25_score DESC, ordinal LIMIT %(limit)s) UNION "
            "(SELECT source_observation_hash FROM eligible WHERE dense_score > 0 "
            "ORDER BY dense_score DESC, ordinal LIMIT %(limit)s)) "
            "SELECT eligible.* FROM eligible JOIN chosen USING (source_observation_hash) ORDER BY ordinal",
            {"workspace_id": self.workspace_id, "revision_id": self.revision_id,
             "tokens": tokens, "count": stats["document_count"],
             "average": max(stats["average_document_length"], 1.0), "limit": limit,
             "query_vector": list(vector), "query_nonzero": any(vector),
             "binding": self._binding_hash, "vector_scope": self._key("vectors", "scope"),
             "unrestricted": allowed_source_observation_hashes is None,
             "families": families or [], "families_unrestricted": families is None,
             "allowed": list(allowed_source_observation_hashes or ())},
        )
        return self._ranked_query(statement, timeout_ms)

    def checkpoint(self, batch_id: str, source_cursor: str, binding: dict[str, Any]) -> None:
        if sha256_json(to_plain(binding)) != self._binding_hash:
            raise ContractValidationError("graph projection checkpoint authority mismatch")
        self._write(lambda: self._put("checkpoint", batch_id, {"source_cursor": source_cursor}))

    def checkpoint_cursor(self, batch_id: str) -> str | None:
        row = self._get("checkpoint", batch_id)
        return None if row is None else row["data"]["source_cursor"]

    def seal(self, view_metadata: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
        if sha256_json(to_plain(binding)) != self._binding_hash:
            raise ContractValidationError("graph projection seal authority mismatch")
        result: dict[str, Any] = {}
        def finish() -> None:
            counts, hashes, relation_types = {}, {}, set()
            for kind in (
                "node", "edge", "membership", "helper", "candidate",
                "posting", "token_stat", "corpus_stat", "vector_ref",
            ):
                digest, count, cursor = hashlib.sha256(), 0, None
                digest.update(b"[")
                while page := self._page(kind, after_id=cursor):
                    for row in page:
                        if count:
                            digest.update(b",")
                        digest.update(json.dumps(sha256_json(row), separators=(",", ":")).encode())
                        count += 1
                        if kind == "edge":
                            relation_types.add(row["data"]["relation_type"])
                    cursor = page[-1]["id"]
                digest.update(b"]")
                counts[kind] = count
                hashes[kind] = "sha256:" + digest.hexdigest()
            result.update({
                "sealed": True, "binding": self.binding, "counts": counts,
                "record_hashes": hashes, "view_metadata": to_plain(view_metadata),
                "relation_types": sorted(relation_types),
            })
            result["seal_hash"] = sha256_json(result)
            self._put("state", "manifest", result)
        self._write(finish)
        self.seal_hash = result["seal_hash"]
        return result

    def reopen(self, expected_seal: str) -> dict[str, Any]:
        state = self._get("state", "manifest")
        if state is None or not state["data"].get("sealed"):
            raise ContractValidationError("graph projection is not sealed")
        data = state["data"]
        payload = {key: value for key, value in data.items() if key != "seal_hash"}
        if data.get("seal_hash") != expected_seal or sha256_json(payload) != expected_seal:
            raise ContractValidationError("graph projection manifest seal mismatch")
        self.seal_hash = expected_seal
        return data


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
