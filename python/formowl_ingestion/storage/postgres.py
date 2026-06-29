from __future__ import annotations

import re
from typing import Any, Callable, Generic, Protocol, TypeVar

from formowl_contract import (
    Asset,
    ExtractorRun,
    IngestionJob,
    Observation,
    UploadSession,
    sha256_json,
    to_plain,
)
from formowl_graph.storage import SQLStatement

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SAFE_RECORD_TYPE = re.compile(r"^[a-z][a-z0-9_-]*$")

T = TypeVar("T")


class PostgreSQLRecordConnection(Protocol):
    def execute(self, statement: SQLStatement) -> None: ...

    def query_one(self, statement: SQLStatement) -> dict[str, Any] | None: ...

    def query_all(self, statement: SQLStatement) -> list[dict[str, Any]]: ...


class _PostgreSQLIngestionRecordStore(Generic[T]):
    def __init__(
        self,
        connection: PostgreSQLRecordConnection,
        *,
        record_type: str,
        id_field: str,
        factory: Callable[[dict[str, Any]], T],
        serializer: Callable[[T], dict[str, Any]],
        workspace_id: Callable[[dict[str, Any]], str],
        permission_scope: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        _validate_record_type(record_type)
        self.connection = connection
        self.record_type = record_type
        self.id_field = id_field
        self.factory = factory
        self.serializer = serializer
        self.workspace_id = workspace_id
        self.permission_scope = permission_scope

    def create(self, record: T | dict[str, Any]) -> T:
        validated = self._validate(record)
        payload = self.serializer(validated)
        record_id = str(payload[self.id_field])
        _validate_record_id(record_id, self.id_field)
        statement = SQLStatement(
            sql=(
                "INSERT INTO formowl_ingestion_records "
                "(record_type, record_id, workspace_id, permission_scope, "
                "payload, payload_hash) "
                "VALUES (%(record_type)s, %(record_id)s, %(workspace_id)s, "
                "%(permission_scope)s::jsonb, %(payload)s::jsonb, %(payload_hash)s) "
                "ON CONFLICT (record_type, record_id) DO UPDATE SET "
                "workspace_id = EXCLUDED.workspace_id, "
                "permission_scope = EXCLUDED.permission_scope, "
                "payload = EXCLUDED.payload, "
                "payload_hash = EXCLUDED.payload_hash, "
                "updated_at = now()"
            ),
            parameters={
                "record_type": self.record_type,
                "record_id": record_id,
                "workspace_id": self.workspace_id(payload),
                "permission_scope": self.permission_scope(payload),
                "payload": to_plain(payload),
                "payload_hash": sha256_json(payload),
            },
        )
        self.connection.execute(statement)
        return validated

    def get(self, record_id: str) -> T | None:
        _validate_record_id(record_id, self.id_field)
        statement = SQLStatement(
            sql=(
                "SELECT payload FROM formowl_ingestion_records "
                "WHERE record_type = %(record_type)s AND record_id = %(record_id)s"
            ),
            parameters={"record_type": self.record_type, "record_id": record_id},
        )
        row = self.connection.query_one(statement)
        if row is None:
            return None
        return self.factory(_row_payload(row))

    def list(self) -> list[T]:
        statement = SQLStatement(
            sql=(
                "SELECT payload FROM formowl_ingestion_records "
                "WHERE record_type = %(record_type)s ORDER BY record_id"
            ),
            parameters={"record_type": self.record_type},
        )
        return [self.factory(_row_payload(row)) for row in self.connection.query_all(statement)]

    def validate_record_id(self, record_id: str) -> None:
        _validate_record_id(record_id, self.id_field)

    def _validate(self, record: T | dict[str, Any]) -> T:
        if isinstance(record, dict):
            return self.factory(record)
        return self.factory(self.serializer(record))


class PostgreSQLAssetStore:
    def __init__(self, connection: PostgreSQLRecordConnection) -> None:
        self._store = _PostgreSQLIngestionRecordStore[Asset](
            connection,
            record_type="asset",
            id_field="asset_id",
            factory=Asset.from_dict,
            serializer=lambda value: value.to_dict(),
            workspace_id=lambda payload: str(payload["workspace_id"]),
            permission_scope=lambda payload: dict(payload["permission_scope"]),
        )

    def create(self, asset: Asset | dict[str, Any]) -> Asset:
        return self._store.create(asset)

    def get(self, asset_id: str) -> Asset | None:
        return self._store.get(asset_id)

    def list(self) -> list[Asset]:
        return self._store.list()


class PostgreSQLJobStore:
    def __init__(self, connection: PostgreSQLRecordConnection) -> None:
        self._store = _PostgreSQLIngestionRecordStore[IngestionJob](
            connection,
            record_type="ingestion_job",
            id_field="ingestion_job_id",
            factory=IngestionJob.from_dict,
            serializer=lambda value: value.to_dict(),
            workspace_id=lambda payload: str(payload["workspace_id"]),
            permission_scope=lambda payload: dict(payload["permission_scope"]),
        )

    def create(self, job: IngestionJob | dict[str, Any]) -> IngestionJob:
        return self._store.create(job)

    def get(self, ingestion_job_id: str) -> IngestionJob | None:
        return self._store.get(ingestion_job_id)

    def list(self) -> list[IngestionJob]:
        return self._store.list()


class PostgreSQLExtractorRunStore:
    def __init__(self, connection: PostgreSQLRecordConnection) -> None:
        self._store = _PostgreSQLIngestionRecordStore[ExtractorRun](
            connection,
            record_type="extractor_run",
            id_field="extractor_run_id",
            factory=ExtractorRun.from_dict,
            serializer=lambda value: value.to_dict(),
            workspace_id=lambda payload: str(payload["asset_id"]),
            permission_scope=lambda payload: _asset_scoped_permission(str(payload["asset_id"])),
        )

    def create(self, run: ExtractorRun | dict[str, Any]) -> ExtractorRun:
        return self._store.create(run)

    def get(self, extractor_run_id: str) -> ExtractorRun | None:
        return self._store.get(extractor_run_id)

    def list(self) -> list[ExtractorRun]:
        return self._store.list()


class PostgreSQLObservationStore:
    def __init__(self, connection: PostgreSQLRecordConnection) -> None:
        self._store = _PostgreSQLIngestionRecordStore[Observation](
            connection,
            record_type="observation",
            id_field="observation_id",
            factory=Observation.from_dict,
            serializer=lambda value: value.to_dict(),
            workspace_id=lambda payload: str(
                payload.get("asset_id") or payload["extractor_run_id"]
            ),
            permission_scope=lambda payload: dict(payload["permission_scope"]),
        )

    def create(self, observation: Observation | dict[str, Any]) -> Observation:
        return self._store.create(observation)

    def get(self, observation_id: str) -> Observation | None:
        return self._store.get(observation_id)

    def list(self) -> list[Observation]:
        return self._store.list()

    def validate_observation_id(self, observation_id: str) -> None:
        self._store.validate_record_id(observation_id)


class PostgreSQLUploadSessionStore:
    def __init__(self, connection: PostgreSQLRecordConnection) -> None:
        self._store = _PostgreSQLIngestionRecordStore[UploadSession](
            connection,
            record_type="upload_session",
            id_field="upload_session_id",
            factory=UploadSession.from_dict,
            serializer=lambda value: value.to_dict(),
            workspace_id=lambda payload: str(payload["workspace_id"]),
            permission_scope=lambda payload: dict(payload["permission_scope"]),
        )

    def create(self, upload_session: UploadSession | dict[str, Any]) -> UploadSession:
        return self._store.create(upload_session)

    def get(self, upload_session_id: str) -> UploadSession | None:
        return self._store.get(upload_session_id)

    def list(self) -> list[UploadSession]:
        return self._store.list()


def postgre_sql_ingestion_store_interfaces() -> tuple[str, ...]:
    return (
        "PostgreSQLAssetStore",
        "PostgreSQLJobStore",
        "PostgreSQLExtractorRunStore",
        "PostgreSQLObservationStore",
        "PostgreSQLUploadSessionStore",
    )


def _asset_scoped_permission(asset_id: str) -> dict[str, str]:
    _validate_record_id(asset_id, "asset_id")
    return {"scope_type": "asset", "scope_id": asset_id, "visibility": "restricted"}


def _row_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("PostgreSQL ingestion store row payload must be a JSON object")
    return payload


def _validate_record_id(record_id: str, field_name: str) -> None:
    if not isinstance(record_id, str) or not _SAFE_RECORD_ID.fullmatch(record_id):
        raise ValueError(f"{field_name} must be a safe PostgreSQL record id")


def _validate_record_type(record_type: str) -> None:
    if not _SAFE_RECORD_TYPE.fullmatch(record_type):
        raise ValueError("record_type must be a safe PostgreSQL record type")
