from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from formowl_contract import ContractValidationError, sha256_json, to_plain
from formowl_graph.storage.postgres import SQLStatement


@dataclass(frozen=True)
class EmbeddingManifest:
    embedding_model: str
    embedding_dimension: int
    distance_metric: str = "cosine"
    normalization: str = "l2"
    manifest_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.embedding_dimension <= 0:
            raise ContractValidationError("EmbeddingManifest.embedding_dimension must be positive")
        if self.distance_metric not in {"cosine", "l2", "inner_product"}:
            raise ContractValidationError("EmbeddingManifest.distance_metric is not supported")
        payload = to_plain(self)
        if payload.get("manifest_hash") is None:
            payload["manifest_hash"] = sha256_json(
                {
                    "embedding_model": self.embedding_model,
                    "embedding_dimension": self.embedding_dimension,
                    "distance_metric": self.distance_metric,
                    "normalization": self.normalization,
                }
            )
        return payload


@dataclass(frozen=True)
class VectorIndexRow:
    vector_id: str
    source_type: str
    source_id: str
    embedding: list[float]
    permission_scope: dict[str, Any]
    index_state: str = "ready"
    embedding_manifest_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.index_state not in {"ready", "stale", "rebuilding", "failed"}:
            raise ContractValidationError("VectorIndexRow.index_state is not supported")
        if not self.embedding or any(isinstance(item, bool) for item in self.embedding):
            raise ContractValidationError("VectorIndexRow.embedding must be numeric")
        return to_plain(self)


@dataclass(frozen=True)
class PgVectorSearchTrace:
    retrieval_trace_id: str
    matched_vector_ids: list[str]
    latency_ms: float
    permission_filtered: bool
    stale_vectors_excluded: bool

    def to_dict(self) -> dict[str, Any]:
        if self.latency_ms < 0:
            raise ContractValidationError("PgVectorSearchTrace.latency_ms must be non-negative")
        return to_plain(self)


@dataclass(frozen=True)
class PgVectorSearchExecution:
    result_source_ids: list[str]
    trace: PgVectorSearchTrace
    raw_sql_exposed: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        if self.raw_sql_exposed:
            raise ContractValidationError("PgVectorSearchExecution must not expose raw SQL")
        return {
            "result_source_ids": list(self.result_source_ids),
            "trace": self.trace.to_dict(),
            "raw_sql_exposed": False,
        }


@dataclass(frozen=True)
class PgVectorQueryBuilder:
    embedding_manifest: EmbeddingManifest
    table_name: str = "formowl_vector_index"
    supported_permissions: set[str] = field(
        default_factory=lambda: {"read", "search", "evidence_snippet", "graph_snippet"}
    )

    def search_statement(
        self,
        *,
        query_embedding: list[float],
        requester_user_id: str,
        now: str,
        limit: int,
        allow_stale: bool = False,
    ) -> SQLStatement:
        manifest = self.embedding_manifest.to_dict()
        if len(query_embedding) != manifest["embedding_dimension"]:
            raise ContractValidationError("query embedding dimension mismatch")
        if limit <= 0:
            raise ContractValidationError("limit must be positive")
        state_clause = (
            "v.index_state IN ('ready', 'stale')" if allow_stale else "v.index_state = 'ready'"
        )
        sql = (
            "SELECT v.vector_id, v.source_type, v.source_id, "
            "v.embedding <=> %(query_embedding)s::vector AS distance "
            f"FROM {self.table_name} v "
            "WHERE "
            f"{state_clause} "
            "AND (v.permission_scope->>'visibility' = 'public' "
            "OR EXISTS ("
            "SELECT 1 FROM formowl_grants g "
            "WHERE g.grantee_user_id = %(requester_user_id)s "
            "AND g.scope_type = v.permission_scope->>'scope_type' "
            "AND g.scope_id = v.permission_scope->>'scope_id' "
            "AND g.permission = ANY(%(supported_permissions)s) "
            "AND g.revoked_at IS NULL "
            "AND g.expires_at > %(now)s)) "
            "ORDER BY distance ASC LIMIT %(limit)s"
        )
        return SQLStatement(
            sql=sql,
            parameters={
                "query_embedding": [float(component) for component in query_embedding],
                "requester_user_id": requester_user_id,
                "supported_permissions": sorted(self.supported_permissions),
                "now": now,
                "limit": limit,
            },
        )

    def upsert_statement(self, row: VectorIndexRow) -> SQLStatement:
        payload = row.to_dict()
        manifest_hash = (
            payload.get("embedding_manifest_hash")
            or self.embedding_manifest.to_dict()["manifest_hash"]
        )
        return SQLStatement(
            sql=(
                f"INSERT INTO {self.table_name} "
                "(vector_id, source_type, source_id, embedding, permission_scope, "
                "index_state, embedding_manifest_hash) "
                "VALUES (%(vector_id)s, %(source_type)s, %(source_id)s, "
                "%(embedding)s::vector, %(permission_scope)s::jsonb, "
                "%(index_state)s, %(embedding_manifest_hash)s) "
                "ON CONFLICT (vector_id) DO UPDATE SET "
                "source_type = EXCLUDED.source_type, "
                "source_id = EXCLUDED.source_id, "
                "embedding = EXCLUDED.embedding, "
                "permission_scope = EXCLUDED.permission_scope, "
                "index_state = EXCLUDED.index_state, "
                "embedding_manifest_hash = EXCLUDED.embedding_manifest_hash"
            ),
            parameters={
                **payload,
                "embedding": [float(component) for component in payload["embedding"]],
                "permission_scope": to_plain(payload["permission_scope"]),
                "embedding_manifest_hash": manifest_hash,
            },
        )


class PgVectorRepository:
    """Internal pgvector adapter over the PostgreSQL connection protocol."""

    def __init__(
        self,
        connection: Any,
        *,
        query_builder: PgVectorQueryBuilder,
    ) -> None:
        self.connection = connection
        self.query_builder = query_builder

    def upsert_vector_index_row(self, row: VectorIndexRow) -> SQLStatement:
        statement = self.query_builder.upsert_statement(row)
        self.connection.execute(statement)
        return statement

    def search_ready_vectors(
        self,
        *,
        query_embedding: list[float],
        requester_user_id: str,
        now: str,
        limit: int,
        retrieval_trace_id: str,
    ) -> PgVectorSearchExecution:
        statement = self.query_builder.search_statement(
            query_embedding=query_embedding,
            requester_user_id=requester_user_id,
            now=now,
            limit=limit,
            allow_stale=False,
        )
        rows = self.connection.query_all(statement)
        matched_vector_ids = [str(row["vector_id"]) for row in rows]
        result_source_ids = [str(row["source_id"]) for row in rows]
        trace = PgVectorSearchTrace(
            retrieval_trace_id=retrieval_trace_id,
            matched_vector_ids=matched_vector_ids,
            latency_ms=float(len(rows)),
            permission_filtered=True,
            stale_vectors_excluded=True,
        )
        return PgVectorSearchExecution(
            result_source_ids=result_source_ids,
            trace=trace,
            raw_sql_exposed=False,
        )


def pgvector_sql_adapter_contract() -> tuple[str, ...]:
    return (
        "EmbeddingManifest",
        "VectorIndexRow",
        "PgVectorQueryBuilder",
        "PgVectorRepository",
    )


def main_repo_pgvector_adapter() -> tuple[str, ...]:
    return pgvector_sql_adapter_contract()
