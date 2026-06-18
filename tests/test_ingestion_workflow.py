from __future__ import annotations

from dataclasses import replace
import json
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    Observation,
    PermissionScope,
    SourceRef,
    stable_observation_id,
)
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import ExtractionInput, ExtractionResult
from formowl_ingestion.extractors import PlainTextObservationExtractor
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
)


class IngestionWorkflowTests(unittest.TestCase):
    def test_asset_to_job_to_run_to_observation_persists_after_restart(self) -> None:
        context = _WorkflowContext.create(
            "ingestion-workflow",
            filename="meeting-notes.md",
            content="# Meeting Notes\n\nUse observations before graph governance.\n",
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
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_names=["plain_text_extractor"],
            config={"mode": "block"},
            created_at="2026-06-17T10:00:00+00:00",
        )
        recording_extractor = _RecordingTextExtractor(context.job_store, job.ingestion_job_id)

        completed = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id,
            asset_store=context.asset_store,
            job_store=context.job_store,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            extractor_adapters=[recording_extractor],
            config={"mode": "block"},
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertTrue(asset.asset_id.startswith("asset_"))
        self.assertTrue(asset.object_uri.startswith("formowl://object/"))
        self.assertTrue(asset.content_hash.startswith("sha256:"))
        self.assertEqual(asset.file_size, context.source_path.stat().st_size)
        self.assertEqual(asset.permission_scope, context.permission_scope.to_dict())
        self.assertEqual(asset.source_ref, context.source_ref.to_dict())
        self.assertEqual(context.asset_store.get(asset.asset_id).to_dict(), asset.to_dict())
        self.assertNotIn(str(context.source_path), json.dumps(asset.to_dict(), sort_keys=True))

        self.assertEqual(job.status, "pending")
        self.assertEqual(recording_extractor.seen_job_statuses, ["running"])
        self.assertEqual(completed.status, "succeeded")
        self.assertEqual(completed.started_at, "2026-06-17T10:01:00+00:00")
        self.assertEqual(completed.completed_at, "2026-06-17T10:01:00+00:00")
        self.assertEqual(completed.error, None)
        self.assertEqual(len(completed.extractor_run_ids), 1)
        self.assertEqual(len(completed.observation_ids), 2)

        restarted_assets = AssetStore(context.temp_dir)
        restarted_jobs = JobStore(context.temp_dir)
        restarted_runs = ExtractorRunStore(context.temp_dir)
        restarted_observations = ObservationStore(context.temp_dir)
        run = restarted_runs.get(completed.extractor_run_ids[0])
        observations = [restarted_observations.get(item) for item in completed.observation_ids]

        self.assertEqual(restarted_assets.get(asset.asset_id).to_dict(), asset.to_dict())
        self.assertEqual(
            restarted_jobs.get(job.ingestion_job_id).to_dict(),
            completed.to_dict(),
        )
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.input_hash, asset.content_hash)
        self.assertEqual(run.extractor_name, "plain_text_extractor")
        self.assertEqual(
            [item.text for item in observations],
            [
                "# Meeting Notes",
                "Use observations before graph governance.",
            ],
        )
        for observation in observations:
            self.assertEqual(observation.asset_id, asset.asset_id)
            self.assertEqual(observation.permission_scope, context.permission_scope.to_dict())
            self.assertEqual(observation.payload["source_ref"], context.source_ref.to_dict())

    def test_failed_ingestion_job_records_error_without_observations(self) -> None:
        context = _WorkflowContext.create(
            "ingestion-workflow-failed",
            filename="archive.bin",
            content="not a text asset",
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
        self.assertEqual(context.observation_store.list(), [])
        self.assertEqual(context.job_store.get(job.ingestion_job_id).to_dict(), failed.to_dict())

    def test_failed_extractor_result_does_not_link_unpersisted_observations(self) -> None:
        context = _WorkflowContext.create(
            "ingestion-workflow-failed-result-observation-lineage",
            filename="notes.txt",
            content="The adapter will report an error with an observation.\n",
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
            mime_type="text/plain",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        adapter = _ErrorResultTextExtractor()
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_adapters=[adapter],
            created_at="2026-06-17T10:00:00+00:00",
        )

        failed = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id,
            asset_store=context.asset_store,
            job_store=context.job_store,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            extractor_adapters=[adapter],
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "adapter_reported_error")
        self.assertEqual(len(failed.extractor_run_ids), 1)
        self.assertEqual(failed.observation_ids, [])
        self.assertEqual(context.observation_store.list(), [])
        self.assertEqual(context.run_store.get(failed.extractor_run_ids[0]).status, "failed")

    def test_adapter_exception_failed_job_links_persisted_failed_run(self) -> None:
        context = _WorkflowContext.create(
            "ingestion-workflow-exception-run-lineage",
            filename="notes.txt",
            content="The adapter exception should still leave auditable run lineage.\n",
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
            mime_type="text/plain",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        adapter = _ExplodingTextExtractor()
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_adapters=[adapter],
            created_at="2026-06-17T10:00:00+00:00",
        )

        failed = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id,
            asset_store=context.asset_store,
            job_store=context.job_store,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            extractor_adapters=[adapter],
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "fixture exception after run setup")
        self.assertEqual(len(failed.extractor_run_ids), 1)
        self.assertEqual(failed.observation_ids, [])
        failed_run = context.run_store.get(failed.extractor_run_ids[0])
        self.assertIsNotNone(failed_run)
        self.assertEqual(failed_run.status, "failed")
        self.assertEqual(failed_run.errors, ["fixture exception after run setup"])
        self.assertEqual(context.observation_store.list(), [])

        restarted_jobs = JobStore(context.temp_dir)
        restarted_runs = ExtractorRunStore(context.temp_dir)
        self.assertEqual(
            restarted_jobs.get(job.ingestion_job_id).to_dict(),
            failed.to_dict(),
        )
        self.assertEqual(
            restarted_runs.get(failed.extractor_run_ids[0]).to_dict(),
            failed_run.to_dict(),
        )

    def test_run_ingestion_job_rejects_non_pending_job_without_new_records(self) -> None:
        # Each non-pending state must fail before run/observation stores can change.
        for status in ("running", "succeeded", "failed"):
            with self.subTest(status=status):
                context = _WorkflowContext.create(
                    f"ingestion-workflow-non-pending-job-{status}",
                    filename="notes.txt",
                    content="Already completed jobs must not rerun.\n",
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
                    mime_type="text/plain",
                    created_at="2026-06-17T10:00:00+00:00",
                    registered_at="2026-06-17T10:00:00+00:00",
                )
                pending = create_ingestion_job(
                    asset=asset,
                    job_store=context.job_store,
                    requested_by="user_yifan",
                    extractor_adapters=[PlainTextObservationExtractor()],
                    created_at="2026-06-17T10:00:00+00:00",
                )
                non_pending = context.job_store.create(
                    replace(
                        pending,
                        status=status,  # type: ignore[arg-type]
                        started_at="2026-06-17T10:01:00+00:00",
                        completed_at=(
                            "2026-06-17T10:01:00+00:00" if status != "running" else None
                        ),
                        error="previous failure" if status == "failed" else None,
                    )
                )

                with self.assertRaisesRegex(ValueError, "must be pending"):
                    run_ingestion_job(
                        ingestion_job_id=non_pending.ingestion_job_id,
                        asset_store=context.asset_store,
                        job_store=context.job_store,
                        object_store=context.object_store,
                        extractor_run_store=context.run_store,
                        observation_store=context.observation_store,
                        extractor_adapters=[PlainTextObservationExtractor()],
                        started_at="2026-06-17T10:02:00+00:00",
                        completed_at="2026-06-17T10:02:00+00:00",
                    )

                self.assertEqual(
                    context.job_store.get(non_pending.ingestion_job_id).to_dict(),
                    non_pending.to_dict(),
                )
                self.assertEqual(context.run_store.list(), [])
                self.assertEqual(context.observation_store.list(), [])

    def test_run_ingestion_job_rejects_empty_timestamps_without_new_records(self) -> None:
        invalid_cases = [
            ("started_at", {"started_at": "", "completed_at": "2026-06-17T10:02:00+00:00"}),
            ("completed_at", {"started_at": "2026-06-17T10:02:00+00:00", "completed_at": ""}),
            (
                "started_at",
                {
                    "started_at": "not-a-timestamp",
                    "completed_at": "2026-06-17T10:02:00+00:00",
                },
            ),
            (
                "completed_at",
                {
                    "started_at": "2026-06-17T10:02:00+00:00",
                    "completed_at": "not-a-timestamp",
                },
            ),
        ]

        for field_name, timestamp_kwargs in invalid_cases:
            with self.subTest(field_name=field_name):
                context = _WorkflowContext.create(
                    f"ingestion-workflow-empty-{field_name}",
                    filename="notes.txt",
                    content="Empty execution timestamps must fail before job mutation.\n",
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
                    mime_type="text/plain",
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

                with self.assertRaisesRegex(ContractValidationError, field_name):
                    run_ingestion_job(
                        ingestion_job_id=job.ingestion_job_id,
                        asset_store=context.asset_store,
                        job_store=context.job_store,
                        object_store=context.object_store,
                        extractor_run_store=context.run_store,
                        observation_store=context.observation_store,
                        extractor_adapters=[PlainTextObservationExtractor()],
                        **timestamp_kwargs,
                    )

                self.assertEqual(
                    context.job_store.get(job.ingestion_job_id).to_dict(),
                    job.to_dict(),
                )
                self.assertEqual(context.run_store.list(), [])
                self.assertEqual(context.observation_store.list(), [])

    def test_run_ingestion_job_rejects_duplicate_adapters_without_job_mutation(self) -> None:
        context = _WorkflowContext.create(
            "ingestion-workflow-duplicate-adapters",
            filename="notes.txt",
            content="Duplicate adapters must fail before the job starts running.\n",
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
            mime_type="text/plain",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_names=["plain_text_extractor"],
            created_at="2026-06-17T10:00:00+00:00",
        )

        with self.assertRaisesRegex(ValueError, "duplicate extractor adapter name"):
            run_ingestion_job(
                ingestion_job_id=job.ingestion_job_id,
                asset_store=context.asset_store,
                job_store=context.job_store,
                object_store=context.object_store,
                extractor_run_store=context.run_store,
                observation_store=context.observation_store,
                extractor_adapters=[
                    PlainTextObservationExtractor(),
                    PlainTextObservationExtractor(),
                ],
                started_at="2026-06-17T10:02:00+00:00",
                completed_at="2026-06-17T10:02:00+00:00",
            )

        self.assertEqual(
            context.job_store.get(job.ingestion_job_id).to_dict(),
            job.to_dict(),
        )
        self.assertEqual(context.run_store.list(), [])
        self.assertEqual(context.observation_store.list(), [])

    def test_create_ingestion_job_rejects_malformed_extractor_names_without_job(self) -> None:
        context = _WorkflowContext.create(
            "ingestion-workflow-malformed-extractor-names",
            filename="notes.txt",
            content="Malformed extractor names must not create jobs.\n",
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
            mime_type="text/plain",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        invalid_cases = [
            "plain_text_extractor",
            [""],
            ["plain_text_extractor", ""],
            ["plain_text_extractor", 123],
            ["plain_text_extractor", "plain_text_extractor"],
        ]

        for extractor_names in invalid_cases:
            with self.subTest(extractor_names=extractor_names):
                with self.assertRaisesRegex(ValueError, "extractor names"):
                    create_ingestion_job(
                        asset=asset,
                        job_store=context.job_store,
                        requested_by="user_yifan",
                        extractor_names=extractor_names,  # type: ignore[list-item]
                        created_at="2026-06-17T10:00:00+00:00",
                    )

        self.assertEqual(context.job_store.list(), [])

    def test_multi_extractor_failure_preserves_only_successful_persisted_observations(
        self,
    ) -> None:
        context = _WorkflowContext.create(
            "ingestion-workflow-multi-extractor-partial-failure",
            filename="notes.txt",
            content="The first extractor succeeds before the second fails.\n",
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
            mime_type="text/plain",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        failing_adapter = _ErrorResultTextExtractor()
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_names=["plain_text_extractor", failing_adapter.name()],
            created_at="2026-06-17T10:00:00+00:00",
        )

        failed = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id,
            asset_store=context.asset_store,
            job_store=context.job_store,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            extractor_adapters=[PlainTextObservationExtractor(), failing_adapter],
            started_at="2026-06-17T10:01:00+00:00",
            completed_at="2026-06-17T10:01:00+00:00",
        )

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "adapter_reported_error")
        self.assertEqual(len(failed.extractor_run_ids), 2)
        self.assertEqual(len(failed.observation_ids), 1)
        self.assertEqual(
            [observation.observation_id for observation in context.observation_store.list()],
            failed.observation_ids,
        )
        self.assertCountEqual(
            [run.status for run in context.run_store.list()],
            ["succeeded", "failed"],
        )

    def test_multi_extractor_missing_adapter_preserves_only_prior_success(self) -> None:
        context = _WorkflowContext.create(
            "ingestion-workflow-missing-second-extractor",
            filename="notes.txt",
            content="The first extractor succeeds before adapter resolution fails.\n",
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
            mime_type="text/plain",
            created_at="2026-06-17T10:00:00+00:00",
            registered_at="2026-06-17T10:00:00+00:00",
        )
        job = create_ingestion_job(
            asset=asset,
            job_store=context.job_store,
            requested_by="user_yifan",
            extractor_names=["plain_text_extractor", "missing_extractor"],
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
        self.assertIn("adapter was not provided", failed.error)
        self.assertEqual(len(failed.extractor_run_ids), 1)
        self.assertEqual(len(failed.observation_ids), 1)
        self.assertEqual(
            [observation.observation_id for observation in context.observation_store.list()],
            failed.observation_ids,
        )
        # Missing adapters do not create synthetic runs; only the prior success remains.
        self.assertEqual(
            [run.status for run in context.run_store.list()],
            ["succeeded"],
        )


class _RecordingTextExtractor(PlainTextObservationExtractor):
    def __init__(self, job_store: JobStore, ingestion_job_id: str) -> None:
        super().__init__()
        self.job_store = job_store
        self.ingestion_job_id = ingestion_job_id
        self.seen_job_statuses: list[str] = []

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        job = self.job_store.get(self.ingestion_job_id)
        self.seen_job_statuses.append(job.status if job is not None else "missing")
        return super().extract(extraction_input)


class _ErrorResultTextExtractor(PlainTextObservationExtractor):
    def name(self) -> str:
        return "error_result_text_extractor"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        text = "This failed observation must not be linked from the job."
        location = {"line_start": 1, "line_end": 1}
        observation = Observation(
            observation_id=stable_observation_id(
                asset_id=extraction_input.asset.asset_id,
                extractor_run_id=extraction_input.extractor_run_id,
                observation_type="paragraph",
                modality="text",
                location=location,
                text=text,
            ),
            asset_id=extraction_input.asset.asset_id,
            extractor_run_id=extraction_input.extractor_run_id,
            observation_type="paragraph",
            modality="text",
            text=text,
            location=location,
            confidence=1.0,
            permission_scope=extraction_input.asset.permission_scope,
            created_at=extraction_input.created_at,
        )
        return ExtractionResult(observations=[observation], errors=["adapter_reported_error"])


class _ExplodingTextExtractor(PlainTextObservationExtractor):
    def name(self) -> str:
        return "exploding_text_extractor"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        raise RuntimeError("fixture exception after run setup")


class _WorkflowContext:
    def __init__(
        self,
        *,
        temp_dir,
        source_path,
        storage_backend_id: str,
        object_store: FileObjectStore,
        asset_store: AssetStore,
        job_store: JobStore,
        run_store: ExtractorRunStore,
        observation_store: ObservationStore,
        permission_scope: PermissionScope,
        source_ref: SourceRef,
    ) -> None:
        self.temp_dir = temp_dir
        self.source_path = source_path
        self.storage_backend_id = storage_backend_id
        self.object_store = object_store
        self.asset_store = asset_store
        self.job_store = job_store
        self.run_store = run_store
        self.observation_store = observation_store
        self.permission_scope = permission_scope
        self.source_ref = source_ref

    @classmethod
    def create(
        cls,
        test_dir_name: str,
        *,
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
        return cls(
            temp_dir=temp_dir,
            source_path=source_path,
            storage_backend_id=backend.storage_backend_id,
            object_store=FileObjectStore(registry),
            asset_store=AssetStore(temp_dir),
            job_store=JobStore(temp_dir),
            run_store=ExtractorRunStore(temp_dir),
            observation_store=ObservationStore(temp_dir),
            permission_scope=PermissionScope.project("project_formowl"),
            source_ref=SourceRef(
                source_system="local",
                source_type="file",
                source_id=filename,
                source_key=filename,
            ),
        )


if __name__ == "__main__":
    unittest.main()
