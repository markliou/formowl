from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Protocol

from formowl_contract import ContractValidationError, sha256_json, to_plain

_MIGRATION_DIR = Path(__file__).resolve().parent / "migrations"
_SAFE_PUBLIC_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
_DSN_PATTERN = re.compile(r"postgres(?:ql)?://", re.IGNORECASE)
_RAW_PATH_PATTERN = re.compile(r"^(?:/|\\\\|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)


@dataclass(frozen=True)
class SQLStatement:
    sql: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"sql": self.sql, "parameters": dict(self.parameters)}


@dataclass(frozen=True)
class PostgreSQLConnectionConfig:
    host: str
    port: int
    database: str
    user: str
    sslmode: str = "require"
    application_name: str = "formowl"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PostgreSQLConnectionConfig":
        _reject_dsn_or_raw_locator(value)
        port = value.get("port", 5432)
        if isinstance(port, bool) or not isinstance(port, int) or port <= 0:
            raise ContractValidationError("PostgreSQLConnectionConfig.port must be positive")
        return cls(
            host=_safe_config_string(value.get("host"), "host"),
            port=port,
            database=_safe_config_string(value.get("database"), "database"),
            user=_safe_config_string(value.get("user"), "user"),
            sslmode=_safe_config_string(value.get("sslmode", "require"), "sslmode"),
            application_name=_safe_config_string(
                value.get("application_name", "formowl"),
                "application_name",
            ),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "host_configured": True,
            "port": self.port,
            "database_configured": True,
            "user_configured": True,
            "sslmode": self.sslmode,
            "application_name": self.application_name,
            "dsn_redacted": True,
        }


@dataclass(frozen=True)
class PostgresMigration:
    migration_id: str
    filename: str
    sql_sha256: str
    statement_count: int

    @classmethod
    def from_file(cls, path: Path) -> "PostgresMigration":
        if not path.name.endswith(".sql") or not path.is_file():
            raise ContractValidationError("PostgresMigration requires a SQL migration file")
        text = path.read_text(encoding="utf-8")
        return cls(
            migration_id=path.stem,
            filename=path.name,
            sql_sha256=sha256_json({"filename": path.name, "sql": text}),
            statement_count=sum(1 for chunk in text.split(";") if chunk.strip()),
        )


@dataclass(frozen=True)
class ReviewDecision:
    review_decision_id: str
    proposal_id: str
    reviewer_user_id: str
    decision: str
    audit_log_id: str
    decided_at: str

    def to_dict(self) -> dict[str, Any]:
        _validate_safe_fields(to_plain(self), "ReviewDecision")
        if self.decision not in {"approve", "reject", "defer"}:
            raise ContractValidationError("ReviewDecision.decision is not supported")
        return to_plain(self)


@dataclass(frozen=True)
class CanonicalCommitProposal:
    canonical_commit_proposal_id: str
    workspace_id: str
    candidate_atom_ids: list[str]
    candidate_relation_ids: list[str]
    required_review_decision_ids: list[str]
    status: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        _validate_safe_fields(to_plain(self), "CanonicalCommitProposal")
        if self.status not in {"pending_review", "approved_for_commit", "rejected"}:
            raise ContractValidationError("CanonicalCommitProposal.status is not supported")
        if not self.required_review_decision_ids:
            raise ContractValidationError(
                "CanonicalCommitProposal requires review decisions before commit"
            )
        return to_plain(self)


@dataclass(frozen=True)
class UserGraphRevision:
    user_graph_revision_id: str
    owner_user_id: str
    workspace_id: str
    graph_revision_id: str
    ontology_revision_id: str
    visible_canonical_ids: list[str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        _validate_safe_fields(to_plain(self), "UserGraphRevision")
        return to_plain(self)


class PostgreSQLConnection(Protocol):
    def execute(self, statement: SQLStatement) -> None: ...

    def query_one(self, statement: SQLStatement) -> dict[str, Any] | None: ...

    def query_all(self, statement: SQLStatement) -> list[dict[str, Any]]: ...

    def begin(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PostgreSQLUnitOfWork:
    """Transaction boundary for metadata repository calls.

    This façade is deliberately connection-protocol based. The production
    implementation can plug in psycopg/asyncpg later while the current tests
    verify statement ordering, rollback behavior, and no public leakage.
    """

    def __init__(self, connection: PostgreSQLConnection) -> None:
        self.connection = connection
        self.committed = False

    def __enter__(self) -> "PostgreSQLUnitOfWork":
        self.connection.begin()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None and self.committed:
            self.connection.commit()
        else:
            self.connection.rollback()
        return False

    def commit(self) -> None:
        self.committed = True


class PostgreSQLMigrationRunner:
    """Replay locked SQL migrations through the internal connection protocol."""

    def __init__(self, connection: PostgreSQLConnection) -> None:
        self.connection = connection

    def migration_replay(
        self, migrations: tuple[PostgresMigration, ...] | None = None
    ) -> list[SQLStatement]:
        statements = []
        for migration in migrations or migration_files():
            path = _MIGRATION_DIR / migration.filename
            if not path.is_file():
                raise ContractValidationError("migration file missing from locked manifest")
            for index, sql in enumerate(
                _split_sql_statements(path.read_text(encoding="utf-8")), start=1
            ):
                statement = SQLStatement(
                    sql=sql,
                    parameters={
                        "migration_id": migration.migration_id,
                        "statement_index": index,
                    },
                )
                self.connection.execute(statement)
                statements.append(statement)
        return statements


class PostgreSQLMetadataRepository:
    """Internal PostgreSQL metadata repository interface.

    It builds parameterized statements only. ChatGPT-facing tools must use the
    gateway/retrieval layers and must not expose these statements.
    """

    def __init__(self, connection: PostgreSQLConnection) -> None:
        self.connection = connection

    def put_graph_record(
        self,
        *,
        record_id: str,
        record_type: str,
        workspace_id: str,
        permission_scope: dict[str, Any],
        payload: dict[str, Any],
    ) -> SQLStatement:
        _validate_public_identifier(record_id, "record_id")
        _validate_public_identifier(record_type, "record_type")
        _validate_public_identifier(workspace_id, "workspace_id")
        statement = SQLStatement(
            sql=(
                "INSERT INTO formowl_graph_records "
                "(record_id, record_type, workspace_id, permission_scope, payload, payload_hash) "
                "VALUES (%(record_id)s, %(record_type)s, %(workspace_id)s, "
                "%(permission_scope)s::jsonb, %(payload)s::jsonb, %(payload_hash)s) "
                "ON CONFLICT (record_id) DO UPDATE SET "
                "permission_scope = EXCLUDED.permission_scope, "
                "payload = EXCLUDED.payload, payload_hash = EXCLUDED.payload_hash"
            ),
            parameters={
                "record_id": record_id,
                "record_type": record_type,
                "workspace_id": workspace_id,
                "permission_scope": to_plain(permission_scope),
                "payload": to_plain(payload),
                "payload_hash": sha256_json(payload),
            },
        )
        self.connection.execute(statement)
        return statement

    def append_audit_log(self, audit_log: dict[str, Any]) -> SQLStatement:
        _validate_safe_fields(audit_log, "AuditLog")
        statement = SQLStatement(
            sql=(
                "INSERT INTO formowl_audit_log "
                "(audit_log_id, actor_user_id, action, target_type, target_id, "
                "session_id, workspace_id, status, metadata, timestamp) "
                "VALUES (%(audit_log_id)s, %(actor_user_id)s, %(action)s, "
                "%(target_type)s, %(target_id)s, %(session_id)s, %(workspace_id)s, "
                "%(status)s, %(metadata)s::jsonb, %(timestamp)s)"
            ),
            parameters=dict(audit_log),
        )
        self.connection.execute(statement)
        return statement

    def direct_unreviewed_canonical_commit(
        self,
        _proposal: CanonicalCommitProposal,
    ) -> None:
        raise ContractValidationError("canonical commits require governed review backend")


def migration_files() -> tuple[PostgresMigration, ...]:
    return tuple(PostgresMigration.from_file(path) for path in sorted(_MIGRATION_DIR.glob("*.sql")))


def postgre_sql_backed_repository_interfaces() -> tuple[str, ...]:
    return (
        "PostgreSQLConnectionConfig",
        "PostgreSQLMigrationRunner",
        "PostgreSQLUnitOfWork",
        "PostgreSQLMetadataRepository",
    )


def postgre_sql_connection_configuration(
    value: dict[str, Any],
) -> PostgreSQLConnectionConfig:
    return PostgreSQLConnectionConfig.from_dict(value)


def grant_audit_query_indexes() -> tuple[str, ...]:
    return (
        "idx_formowl_graph_records_scope",
        "idx_formowl_grants_effective_scope",
        "idx_formowl_audit_log_actor_target",
    )


def transaction_rollback_tests_against_postgre_sql() -> tuple[str, ...]:
    return (
        "scripts/postgres_transaction_rollback_live_smoke.py",
        "scripts/postgres_transaction_rollback_live_smoke_container.sh",
        "results/main_repo_postgres_rollback_live_smoke.json",
    )


def build_permission_query_index_sql() -> SQLStatement:
    return SQLStatement(
        sql=(
            "SELECT record_id FROM formowl_graph_records r "
            "WHERE r.permission_scope->>'visibility' = 'public' "
            "OR EXISTS ("
            "SELECT 1 FROM formowl_grants g "
            "WHERE g.grantee_user_id = %(requester_user_id)s "
            "AND g.scope_type = r.permission_scope->>'scope_type' "
            "AND g.scope_id = r.permission_scope->>'scope_id' "
            "AND g.revoked_at IS NULL "
            "AND g.expires_at > %(now)s)"
        ),
        parameters={"requester_user_id": None, "now": None},
    )


def _safe_config_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"PostgreSQLConnectionConfig.{field_name} is required")
    if _DSN_PATTERN.search(value) or _RAW_PATH_PATTERN.search(value):
        raise ContractValidationError(
            f"PostgreSQLConnectionConfig.{field_name} must not be a raw locator"
        )
    return value


def _reject_dsn_or_raw_locator(value: dict[str, Any]) -> None:
    for key, item in value.items():
        if str(key).lower() in {"dsn", "database_url", "connection_string"}:
            raise ContractValidationError("PostgreSQL DSN must stay outside public config")
        if isinstance(item, str) and (_DSN_PATTERN.search(item) or _RAW_PATH_PATTERN.search(item)):
            raise ContractValidationError("PostgreSQL config must not expose raw locators")


def _split_sql_statements(text: str) -> tuple[str, ...]:
    statements = tuple(chunk.strip() for chunk in text.split(";") if chunk.strip())
    if not statements:
        raise ContractValidationError("migration file must contain at least one statement")
    return statements


def _validate_public_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_PUBLIC_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a safe public identifier")


def _validate_safe_fields(value: dict[str, Any], name: str) -> None:
    for key, item in value.items():
        if isinstance(item, str):
            if _DSN_PATTERN.search(item) or _RAW_PATH_PATTERN.search(item):
                raise ContractValidationError(f"{name}.{key} must not expose raw locators")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                if not isinstance(child, str) or not _SAFE_PUBLIC_ID.fullmatch(child):
                    raise ContractValidationError(f"{name}.{key}[{index}] must be a safe id")
        elif isinstance(item, dict):
            _validate_safe_fields(item, f"{name}.{key}")
