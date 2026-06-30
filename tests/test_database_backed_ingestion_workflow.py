from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import unittest

import _paths  # noqa: F401
from formowl_contract import PermissionScope, SourceRef
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extractors import PlainTextObservationExtractor
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job
from formowl_ingestion.storage import (
    AssetRecordStore,
    AssetStore,
    ExtractorRunRecordStore,
    ExtractorRunStore,
    FileObjectStore,
    JobRecordStore,
    JobStore,
    ObservationRecordStore,
    ObservationStore,
    PostgreSQLAssetStore,
    PostgreSQLExtractorRunStore,
    PostgreSQLJobStore,
    PostgreSQLObservationStore,
    StorageBackendRegistry,
    ingestion_record_store_interface_names,
)


class DatabaseBackedIngestionWorkflowTests(unittest.TestCase):
    def test_same_ingestion_workflow_runs_against_file_and_postgres_record_stores(
        self,
    ) -> None:
        summaries = {}
        for store_kind in ("file", "postgres"):
            with self.subTest(store_kind=store_kind):
                context = _WorkflowContext.create(
                    f"database-backed-ingestion-workflow-{store_kind}",
                    store_kind=store_kind,
                    filename="source.md",
                    content="# Source\n\nDatabase stores should keep the workflow contract.\n",
                )

                summary = _run_successful_workflow(context)

                self.assertEqual(summary["completed_status"], "succeeded")
                self.assertEqual(summary["run_statuses"], ["succeeded"])
                self.assertCountEqual(
                    summary["observation_texts"],
                    ["# Source", "Database stores should keep the workflow contract."],
                )
                self.assertTrue(summary["asset_object_uri"].startswith("formowl://object/"))
                self.assertNotIn(str(context.source_path), str(summary))
                summaries[store_kind] = summary

        self.assertCountEqual(
            summaries["file"]["observation_texts"], summaries["postgres"]["observation_texts"]
        )
        self.assertEqual(
            summaries["file"]["completed_status"], summaries["postgres"]["completed_status"]
        )

    def test_postgres_workflow_failure_preserves_no_observation_side_effects_or_raw_paths(
        self,
    ) -> None:
        context = _WorkflowContext.create(
            "database-backed-ingestion-workflow-failure",
            store_kind="postgres",
            filename="archive.bin",
            content="not supported by the text extractor",
        )
        asset = register_asset_from_local_file(
            context.source_path,
            object_store=context.object_store,
            asset_store=context.asset_store,
            storage_backend_id=context.storage_backend_id,
            workspace_id="workspace_formowl",
            owner_user_id="user_yifan",
            permission_scope=context.permission_scope,
            source_ref=context.source_ref,
            mime_type="application/octet-stream",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_adapters=[PlainTextObservationExtractor()],
            created_at="2026-06-17T10:00:00+00:00",
        )

        failed = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id,
            asset_store=context.asset_store,
            job_store=context.job_store,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            extractor_adapters=[PlainTextObservationExtractor()],
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(failed.status, "failed")
        self.assertIn("does not support asset MIME type", failed.error)
        self.assertEqual(failed.extractor_run_ids, [])
        self.assertEqual(failed.observation_ids, [])
        self.assertEqual(context.run_store.list(), [])
        self.assertEqual(context.observation_store.list(), [])
        self.assertNotIn(str(context.source_path), context.connection_public_text())
        self.assertNotIn("postgresql://", context.connection_public_text().lower())

    def test_ingestion_store_protocols_name_the_shared_file_and_postgres_surface(self) -> None:
        self.assertEqual(
            ingestion_record_store_interface_names(),
            (
                "AssetRecordStore",
                "JobRecordStore",
                "ExtractorRunRecordStore",
                "ObservationRecordStore",
                "UploadSessionRecordStore",
            ),
        )


def _run_successful_workflow(context: "_WorkflowContext") -> dict[str, Any]:
    asset = register_asset_from_local_file(
        context.source_path,
        object_store=context.object_store,
        asset_store=context.asset_store,
        storage_backend_id=context.storage_backend_id,
        workspace_id="workspace_formowl",
        owner_user_id="user_yifan",
        permission_scope=context.permission_scope,
        source_ref=context.source_ref,
        mime_type="text/markdown",
        created_at="2026-06-17T10:00:00+00:00",
        registered_at="2026-06-17T10:00:00+00:00",
    )
    job = create_ingestion_job(
        asset=asset,
        job_store=context.job_store,
        requested_by="user_yifan",
        extractor_adapters=[PlainTextObservationExtractor()],
        created_at="2026-06-17T10:00:00+00:00",
    )
    completed = run_ingestion_job(
        ingestion_job_id=job.ingestion_job_id,
        asset_store=context.asset_store,
        job_store=context.job_store,
        object_store=context.object_store,
        extractor_run_store=context.run_store,
        observation_store=context.observation_store,
        extractor_adapters=[PlainTextObservationExtractor()],
        started_at="2026-06-17T10:01:00+00:00",
        completed_at="2026-06-17T10:01:00+00:00",
    )
    persisted_asset = context.asset_store.get(asset.asset_id)
    persisted_job = context.job_store.get(job.ingestion_job_id)
    persisted_runs = context.run_store.list()
    persisted_observations = context.observation_store.list()

    return {
        "asset_object_uri": persisted_asset.object_uri,
        "completed_status": persisted_job.status,
        "job_observation_count": len(completed.observation_ids),
        "run_statuses": [run.status for run in persisted_runs],
        "observation_texts": [observation.text for observation in persisted_observations],
    }


@dataclass
class _WorkflowContext:
    temp_dir: Any
    source_path: Any
    storage_backend_id: str
    object_store: FileObjectStore
    asset_store: AssetRecordStore
    job_store: JobRecordStore
    run_store: ExtractorRunRecordStore
    observation_store: ObservationRecordStore
    permission_scope: PermissionScope
    source_ref: SourceRef
    connection: "_RecordingConnection | None"

    @classmethod
    def create(
        cls,
        test_dir_name: str,
        *,
        store_kind: str,
        filename: str,
        content: str,
    ) -> "_WorkflowContext":
        temp_dir = _paths.fresh_test_dir(test_dir_name)
        source_path = temp_dir / "incoming" / filename
        source_path.parent.mkdir(parents=True)
        source_path.write_text(content, encoding="utf-8")
        registry = StorageBackendRegistry(temp_dir)
        backend = registry.register_local_backend(
            temp_dir / "object-root",
            workspace_scope="workspace_formowl",
        )
        connection = _RecordingConnection() if store_kind == "postgres" else None
        return cls(
            temp_dir=temp_dir,
            source_path=source_path,
            storage_backend_id=backend.storage_backend_id,
            object_store=FileObjectStore(registry),
            asset_store=(
                PostgreSQLAssetStore(connection) if connection is not None else AssetStore(temp_dir)
            ),
            job_store=(
                PostgreSQLJobStore(connection) if connection is not None else JobStore(temp_dir)
            ),
            run_store=(
                PostgreSQLExtractorRunStore(connection)
                if connection is not None
                else ExtractorRunStore(temp_dir)
            ),
            observation_store=(
                PostgreSQLObservationStore(connection)
                if connection is not None
                else ObservationStore(temp_dir)
            ),
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=SourceRef(
                source_system="local",
                source_type="file",
                source_id=filename,
                source_key=filename,
            ),
            connection=connection,
        )

    def connection_public_text(self) -> str:
        if self.connection is None:
            return ""
        return str([statement.to_dict() for statement in self.connection.statements])


class _RecordingConnection:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.statements: list[Any] = []
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}

    def execute(self, statement: Any) -> None:
        self.actions.append("execute")
        self.statements.append(statement)
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


if __name__ == "__main__":
    unittest.main()
