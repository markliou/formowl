from __future__ import annotations

from dataclasses import replace
from typing import Any
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    Asset,
    ContractValidationError,
    ExtractorRun,
    IngestionJob,
    Observation,
    PermissionScope,
    SourceRef,
    UploadSession,
    sha256_json,
)
from formowl_graph.storage import (
    PostgreSQLUnitOfWork,
    grant_audit_query_indexes,
    migration_files,
)
from formowl_ingestion.storage import (
    PostgreSQLAssetStore,
    PostgreSQLExtractorRunStore,
    PostgreSQLJobStore,
    PostgreSQLObservationStore,
    PostgreSQLUploadSessionStore,
    postgre_sql_ingestion_store_interfaces,
)


class PostgreSQLIngestionStoreTests(unittest.TestCase):
    def test_create_get_list_match_file_backed_store_interfaces(self) -> None:
        connection = _RecordingConnection()
        records = _valid_store_records()

        self.assertEqual(
            PostgreSQLAssetStore(connection).create(records.asset).to_dict(),
            records.asset.to_dict(),
        )
        self.assertEqual(
            PostgreSQLJobStore(connection).create(records.job.to_dict()).to_dict(),
            records.job.to_dict(),
        )
        self.assertEqual(
            PostgreSQLExtractorRunStore(connection).create(records.run).to_dict(),
            records.run.to_dict(),
        )
        self.assertEqual(
            PostgreSQLObservationStore(connection).create(records.observation).to_dict(),
            records.observation.to_dict(),
        )
        self.assertEqual(
            PostgreSQLUploadSessionStore(connection).create(records.upload_session).to_dict(),
            records.upload_session.to_dict(),
        )

        self.assertEqual(
            PostgreSQLAssetStore(connection).get(records.asset.asset_id).to_dict(),
            records.asset.to_dict(),
        )
        self.assertEqual(
            PostgreSQLJobStore(connection).get(records.job.ingestion_job_id).to_dict(),
            records.job.to_dict(),
        )
        self.assertEqual(
            PostgreSQLExtractorRunStore(connection).get(records.run.extractor_run_id).to_dict(),
            records.run.to_dict(),
        )
        self.assertEqual(
            PostgreSQLObservationStore(connection)
            .get(
                records.observation.observation_id,
            )
            .to_dict(),
            records.observation.to_dict(),
        )
        self.assertEqual(
            PostgreSQLUploadSessionStore(connection)
            .get(
                records.upload_session.upload_session_id,
            )
            .to_dict(),
            records.upload_session.to_dict(),
        )

        self.assertEqual(
            [item.to_dict() for item in PostgreSQLAssetStore(connection).list()],
            [records.asset.to_dict()],
        )
        self.assertEqual(
            [item.to_dict() for item in PostgreSQLJobStore(connection).list()],
            [records.job.to_dict()],
        )
        self.assertEqual(
            [item.to_dict() for item in PostgreSQLExtractorRunStore(connection).list()],
            [records.run.to_dict()],
        )
        self.assertEqual(
            [item.to_dict() for item in PostgreSQLObservationStore(connection).list()],
            [records.observation.to_dict()],
        )
        self.assertEqual(
            [item.to_dict() for item in PostgreSQLUploadSessionStore(connection).list()],
            [records.upload_session.to_dict()],
        )

    def test_statements_are_parameterized_and_manifest_names_interfaces(self) -> None:
        connection = _RecordingConnection()
        records = _valid_store_records()
        statement = PostgreSQLAssetStore(connection).create(records.asset)

        insert_statement = connection.statements[0]
        migration_names = [item.filename for item in migration_files()]

        self.assertEqual(statement.to_dict(), records.asset.to_dict())
        self.assertIn("%(record_id)s", insert_statement.sql)
        self.assertNotIn(records.asset.asset_id, insert_statement.sql)
        self.assertEqual(
            insert_statement.parameters["payload_hash"],
            sha256_json(records.asset.to_dict()),
        )
        self.assertIn("003_ingestion_records.sql", migration_names)
        self.assertIn("idx_formowl_ingestion_records_scope", grant_audit_query_indexes())
        self.assertIn("idx_formowl_ingestion_records_asset", grant_audit_query_indexes())
        self.assertEqual(
            postgre_sql_ingestion_store_interfaces(),
            (
                "PostgreSQLAssetStore",
                "PostgreSQLJobStore",
                "PostgreSQLExtractorRunStore",
                "PostgreSQLObservationStore",
                "PostgreSQLUploadSessionStore",
            ),
        )

    def test_invalid_contracts_and_unsafe_ids_fail_before_execute(self) -> None:
        records = _valid_store_records()
        invalid_job = records.job.to_dict()
        invalid_job["status"] = "unknown"
        invalid_asset = replace(records.asset, asset_id="../asset_escape")

        invalid_contract_connection = _RecordingConnection()
        with self.assertRaises(ContractValidationError):
            PostgreSQLJobStore(invalid_contract_connection).create(invalid_job)
        self.assertEqual(invalid_contract_connection.actions, [])

        unsafe_id_connection = _RecordingConnection()
        with self.assertRaises(ValueError):
            PostgreSQLAssetStore(unsafe_id_connection).create(invalid_asset)
        with self.assertRaises(ValueError):
            PostgreSQLAssetStore(unsafe_id_connection).get("../asset_escape")
        self.assertEqual(unsafe_id_connection.actions, [])

    def test_transaction_boundary_rolls_back_failed_ingestion_store_write(self) -> None:
        connection = _RecordingConnection(fail_on_execute=True)
        records = _valid_store_records()

        with self.assertRaises(RuntimeError):
            with PostgreSQLUnitOfWork(connection):
                PostgreSQLAssetStore(connection).create(records.asset)

        self.assertEqual(connection.actions, ["begin", "execute", "rollback"])
        self.assertEqual(connection.rows, {})

    def test_missing_records_return_none(self) -> None:
        connection = _RecordingConnection()

        self.assertIsNone(PostgreSQLAssetStore(connection).get("asset_missing"))
        self.assertIsNone(PostgreSQLJobStore(connection).get("job_missing"))
        self.assertIsNone(PostgreSQLExtractorRunStore(connection).get("run_missing"))
        self.assertIsNone(PostgreSQLObservationStore(connection).get("obs_missing"))
        self.assertIsNone(PostgreSQLUploadSessionStore(connection).get("upload_missing"))


class _StoreRecords:
    def __init__(
        self,
        *,
        asset: Asset,
        job: IngestionJob,
        run: ExtractorRun,
        observation: Observation,
        upload_session: UploadSession,
    ) -> None:
        self.asset = asset
        self.job = job
        self.run = run
        self.observation = observation
        self.upload_session = upload_session


class _RecordingConnection:
    def __init__(self, *, fail_on_execute: bool = False) -> None:
        self.fail_on_execute = fail_on_execute
        self.actions: list[str] = []
        self.statements: list[Any] = []
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}

    def execute(self, statement: Any) -> None:
        self.actions.append("execute")
        self.statements.append(statement)
        if self.fail_on_execute:
            raise RuntimeError("simulated execute failure")
        if "INSERT INTO formowl_ingestion_records" in statement.sql:
            key = (
                str(statement.parameters["record_type"]),
                str(statement.parameters["record_id"]),
            )
            self.rows[key] = {
                "workspace_id": statement.parameters["workspace_id"],
                "permission_scope": statement.parameters["permission_scope"],
                "payload": statement.parameters["payload"],
            }

    def query_one(self, statement: Any) -> dict[str, Any] | None:
        self.actions.append("query_one")
        self.statements.append(statement)
        key = (
            str(statement.parameters["record_type"]),
            str(statement.parameters["record_id"]),
        )
        row = self.rows.get(key)
        return {"payload": row["payload"]} if row else None

    def query_all(self, statement: Any) -> list[dict[str, Any]]:
        self.actions.append("query_all")
        self.statements.append(statement)
        record_type = str(statement.parameters["record_type"])
        rows = []
        for key, row in sorted(self.rows.items()):
            if key[0] == record_type:
                rows.append({"payload": row["payload"]})
        return rows

    def begin(self) -> None:
        self.actions.append("begin")

    def commit(self) -> None:
        self.actions.append("commit")

    def rollback(self) -> None:
        self.actions.append("rollback")


def _valid_store_records() -> _StoreRecords:
    created_at = "2026-06-17T10:00:00+00:00"
    permission_scope = PermissionScope.project("project_formowl")
    source_ref = SourceRef(
        source_system="local",
        source_type="file",
        source_id="source.txt",
    )
    asset = Asset(
        asset_id="asset_pg_001",
        storage_backend_id="storage_local_001",
        object_uri="formowl://object/storage_local_001/workspace_formowl/hash001",
        content_hash="sha256:abc123",
        file_size=12,
        mime_type="text/plain",
        created_at=created_at,
        registered_at=created_at,
        owner_user_id="user_yifan",
        workspace_id="workspace_formowl",
        permission_scope=permission_scope,
        lifecycle_state="active",
        source_ref=source_ref,
        original_filename="source.txt",
    )
    job = IngestionJob(
        ingestion_job_id="job_pg_001",
        asset_id=asset.asset_id,
        status="pending",
        requested_by="user_yifan",
        workspace_id="workspace_formowl",
        permission_scope=permission_scope,
        created_at=created_at,
        extractor_names=["plain_text_extractor"],
    )
    run = ExtractorRun(
        extractor_run_id="run_pg_001",
        asset_id=asset.asset_id,
        extractor_name="plain_text_extractor",
        extractor_version="0.1.0",
        extractor_type="document_structure",
        input_hash=asset.content_hash,
        config_hash="sha256:config",
        status="succeeded",
        started_at=created_at,
        completed_at=created_at,
    )
    observation = Observation(
        observation_id="obs_pg_001",
        asset_id=asset.asset_id,
        extractor_run_id=run.extractor_run_id,
        observation_type="paragraph",
        modality="text",
        text="A persisted observation.",
        location={"line_start": 1, "line_end": 1},
        confidence=1.0,
        permission_scope=permission_scope,
        created_at=created_at,
    )
    upload_session = UploadSession(
        upload_session_id="upload_pg_001",
        actor_user_id="user_yifan",
        workspace_id="workspace_formowl",
        owner_scope_type="project",
        owner_scope_id="project_formowl",
        intent="Upload source material.",
        intended_asset_type="document",
        ingestion_profile="plain_text",
        visibility_scope="workspace",
        permission_scope=permission_scope,
        expires_at="2026-06-18T10:00:00+00:00",
        source_preparation_state="not_started",
        processing_status="waiting_for_upload",
        status="pending",
        created_at=created_at,
        audit_log_id="audit_pg_001",
    )
    return _StoreRecords(
        asset=asset,
        job=job,
        run=run,
        observation=observation,
        upload_session=upload_session,
    )


if __name__ == "__main__":
    unittest.main()
