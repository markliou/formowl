from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from typing import Any

import _paths  # noqa: F401
import formowl_mail.import_workflow as import_workflow
from formowl_auth import FileAuditLogStore
from formowl_contract import ContractValidationError, PermissionScope, SourceRef
from formowl_gateway import validate_public_gateway_payload
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import ExtractionResult
from formowl_ingestion.extractors.mail.pst import (
    PstMailArchiveExtractor,
    _ParserCommandResult,
)
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
    UploadSessionStore,
)
from formowl_ingestion.uploads import create_upload_session
from formowl_mail import (
    PostgreSQLMailEvidenceStore,
    run_upload_session_mail_import,
    validate_mail_upload_import_summary,
)

NOW = "2026-07-05T10:00:00+00:00"
WORKSPACE_ID = "workspace_formowl"
OWNER_USER_ID = "user_yifan"
SESSION_ID = "session_upload_mail"
PROJECT_ID = "project_formowl"
STORAGE_BACKEND_ID = "storage_mail_upload_import"


class MailUploadImportWorkflowTests(unittest.TestCase):
    def test_upload_session_bound_import_writes_store_and_queries_through_jsonrpc(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-import-workflow")
        stores = _workflow_stores(temp_dir)
        upload_session = _create_mail_upload_session(
            stores["upload_session_store"],
            audit_store=stores["audit_store"],
        )
        staged_archive = _write_mail_archive(temp_dir)
        connection = _RecordingMailConnection()

        result = run_upload_session_mail_import(
            staged_archive,
            upload_session_id=upload_session.upload_session_id,
            upload_session_store=stores["upload_session_store"],
            object_store=stores["object_store"],
            asset_store=stores["asset_store"],
            job_store=stores["job_store"],
            extractor_run_store=stores["extractor_run_store"],
            observation_store=stores["observation_store"],
            mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
            storage_backend_id=STORAGE_BACKEND_ID,
            actor_user_id=OWNER_USER_ID,
            session_id=SESSION_ID,
            query_text="audit approval",
            created_at=NOW,
        )

        updated_session = stores["upload_session_store"].get(upload_session.upload_session_id)
        summary = result.to_public_dict()

        self.assertEqual(updated_session.status, "succeeded")
        self.assertEqual(updated_session.processing_status, "mail_evidence_ready")
        self.assertEqual(updated_session.asset_id, result.asset_id)
        self.assertEqual(updated_session.ingestion_job_id, result.ingestion_job_id)
        self.assertEqual(result.owner_query_status, "ok")
        self.assertGreater(result.owner_citation_count, 0)
        self.assertTrue(summary["validation"]["passed"])
        self.assertTrue(
            summary["claim_boundary"]["supports_upload_session_bound_mail_import_workflow_claim"]
        )
        self.assertFalse(summary["claim_boundary"]["supports_real_pst_parser_claim"])
        self.assertFalse(summary["claim_boundary"]["supports_upload_ui_or_iframe_claim"])
        self.assertFalse(summary["claim_boundary"]["supports_live_postgresql_readiness_claim"])
        validate_public_gateway_payload(summary)

        stored_bundle = PostgreSQLMailEvidenceStore(connection).get_bundle(
            mail_import_session_id=result.mail_import_session_id,
        )
        self.assertIsNotNone(stored_bundle)
        self.assertEqual(
            stored_bundle.mail_import_session.upload_session_id,
            upload_session.upload_session_id,
        )
        self.assertEqual(stored_bundle.mail_import_session.source_asset_id, result.asset_id)
        self.assertTrue(
            {
                "mail_import_session",
                "mail_archive_occurrence",
                "mail_folder_occurrence",
                "email_message",
                "email_message_occurrence",
                "email_body_segment",
                "mail_parse_run",
            }.issubset(set(connection.rows))
        )
        self.assertEqual(connection.actions[0], "begin")
        self.assertIn("commit", connection.actions)

        rendered_summary = json.dumps(summary, sort_keys=True)
        self.assertNotIn("Update: Launch reviewed", rendered_summary)
        self.assertNotIn("Waiting on audit approval", rendered_summary)
        self.assertNotIn(str(temp_dir), rendered_summary)
        self.assertNotIn("object-root", rendered_summary)
        self.assertNotIn("payload.bin", rendered_summary)
        self.assertNotIn("fixture_mail_archive_extractor", rendered_summary)
        self.assertNotIn("SELECT", rendered_summary.upper())

    def test_import_uses_asset_already_bound_by_upload_surface(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-import-existing-asset")
        stores = _workflow_stores(temp_dir)
        upload_session = _create_mail_upload_session(
            stores["upload_session_store"],
            audit_store=stores["audit_store"],
        )
        staged_archive = _write_mail_archive(temp_dir)
        asset = register_asset_from_local_file(
            staged_archive,
            object_store=stores["object_store"],
            asset_store=stores["asset_store"],
            storage_backend_id=STORAGE_BACKEND_ID,
            workspace_id=WORKSPACE_ID,
            owner_user_id=OWNER_USER_ID,
            permission_scope=PermissionScope.project(PROJECT_ID),
            source_ref=SourceRef(
                source_system="formowl_upload_session",
                source_type="mail_archive_upload",
                source_id=upload_session.upload_session_id,
                source_key=upload_session.upload_session_id,
            ),
            mime_type="application/vnd.formowl.mail-archive+json",
            created_at=NOW,
            registered_at=NOW,
        )
        stores["upload_session_store"].create(
            replace(
                upload_session,
                status="uploading",
                source_preparation_state="uploaded",
                processing_status="archive_uploaded",
                asset_id=asset.asset_id,
            )
        )
        connection = _RecordingMailConnection()

        result = run_upload_session_mail_import(
            None,
            upload_session_id=upload_session.upload_session_id,
            upload_session_store=stores["upload_session_store"],
            object_store=stores["object_store"],
            asset_store=stores["asset_store"],
            job_store=stores["job_store"],
            extractor_run_store=stores["extractor_run_store"],
            observation_store=stores["observation_store"],
            mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
            storage_backend_id=STORAGE_BACKEND_ID,
            actor_user_id=OWNER_USER_ID,
            session_id=SESSION_ID,
            query_text="audit approval",
            created_at=NOW,
        )

        self.assertEqual(result.asset_id, asset.asset_id)
        self.assertEqual(len(stores["asset_store"].list()), 1)
        self.assertEqual(
            stores["upload_session_store"].get(upload_session.upload_session_id).asset_id,
            asset.asset_id,
        )
        self.assertIn("mail_import_session", connection.rows)

    def test_pst_mime_import_selects_pst_adapter_without_fixture_fallback(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-import-pst-adapter")
        stores = _workflow_stores(temp_dir)
        upload_session = _create_mail_upload_session(
            stores["upload_session_store"],
            audit_store=stores["audit_store"],
        )
        staged_archive = _write_pst_archive(temp_dir)
        connection = _RecordingMailConnection()
        original_pst_adapter = import_workflow.PstMailArchiveExtractor

        class _RunnerBackedPstAdapter(PstMailArchiveExtractor):
            def __init__(self) -> None:
                super().__init__(
                    runner=_pst_runner_with_messages([_pst_rfc822_message()]),
                    scratch_parent=temp_dir / "pst-scratch",
                )

        import_workflow.PstMailArchiveExtractor = _RunnerBackedPstAdapter
        try:
            result = import_workflow.run_upload_session_mail_import(
                staged_archive,
                upload_session_id=upload_session.upload_session_id,
                upload_session_store=stores["upload_session_store"],
                object_store=stores["object_store"],
                asset_store=stores["asset_store"],
                job_store=stores["job_store"],
                extractor_run_store=stores["extractor_run_store"],
                observation_store=stores["observation_store"],
                mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
                storage_backend_id=STORAGE_BACKEND_ID,
                actor_user_id=OWNER_USER_ID,
                session_id=SESSION_ID,
                query_text=None,
                created_at=NOW,
                asset_mime_type="application/vnd.ms-outlook",
                extraction_config={"max_messages": 1},
            )
        finally:
            import_workflow.PstMailArchiveExtractor = original_pst_adapter

        updated_session = stores["upload_session_store"].get(upload_session.upload_session_id)
        extractor_runs = stores["extractor_run_store"].list()
        stored_bundle = PostgreSQLMailEvidenceStore(connection).get_bundle(
            mail_import_session_id=result.mail_import_session_id,
        )

        self.assertEqual(updated_session.status, "succeeded")
        self.assertEqual(updated_session.processing_status, "mail_evidence_ready")
        self.assertEqual(len(extractor_runs), 1)
        self.assertEqual(extractor_runs[0].extractor_name, "pst_mail_archive_extractor")
        self.assertNotEqual(extractor_runs[0].extractor_name, "fixture_mail_archive_extractor")
        self.assertIsNotNone(stored_bundle)
        self.assertEqual(stored_bundle.producer_type, "server_side_parser")
        self.assertEqual(stored_bundle.mail_parse_run.parser_name, "pst_mail_archive_extractor")
        self.assertEqual(
            stored_bundle.mail_parse_run.input_hash,
            stored_bundle.mail_import_session.archive_sha256,
        )
        self.assertGreater(result.observation_count, 0)
        self.assertGreater(result.owner_citation_count, 0)
        rendered_summary = json.dumps(result.to_public_dict(), sort_keys=True)
        self.assertNotIn("fixture_mail_archive_extractor", rendered_summary)
        self.assertNotIn("readpst", rendered_summary)
        self.assertNotIn("pst-scratch", rendered_summary)

    def test_bound_asset_import_requires_upload_receipt_state_and_source_ref(
        self,
    ) -> None:
        cases = (
            {"case_name": "wrong_asset_source_ref", "wrong_source_ref": True},
            {"case_name": "pending_with_bound_asset", "status": "pending"},
            {
                "case_name": "wrong_processing_status",
                "processing_status": "waiting_for_upload",
            },
        )

        for case in cases:
            with self.subTest(case=case["case_name"]):
                temp_dir = _paths.fresh_test_dir(
                    f"mail-upload-import-bound-asset-{case['case_name']}"
                )
                stores = _workflow_stores(temp_dir)
                upload_session = _create_mail_upload_session(
                    stores["upload_session_store"],
                    audit_store=stores["audit_store"],
                )
                staged_archive = _write_mail_archive(temp_dir)
                source_id = (
                    "upload_other_session"
                    if case.get("wrong_source_ref")
                    else upload_session.upload_session_id
                )
                asset = register_asset_from_local_file(
                    staged_archive,
                    object_store=stores["object_store"],
                    asset_store=stores["asset_store"],
                    storage_backend_id=STORAGE_BACKEND_ID,
                    workspace_id=WORKSPACE_ID,
                    owner_user_id=OWNER_USER_ID,
                    permission_scope=PermissionScope.project(PROJECT_ID),
                    source_ref=SourceRef(
                        source_system="formowl_upload_session",
                        source_type="mail_archive_upload",
                        source_id=source_id,
                        source_key=source_id,
                    ),
                    mime_type="application/vnd.formowl.mail-archive+json",
                    created_at=NOW,
                    registered_at=NOW,
                )
                stores["upload_session_store"].create(
                    replace(
                        upload_session,
                        status=case.get("status", "uploading"),
                        source_preparation_state="uploaded",
                        processing_status=case.get(
                            "processing_status",
                            "archive_uploaded",
                        ),
                        asset_id=asset.asset_id,
                    )
                )
                connection = _RecordingMailConnection()

                with self.assertRaises(ContractValidationError):
                    run_upload_session_mail_import(
                        None,
                        upload_session_id=upload_session.upload_session_id,
                        upload_session_store=stores["upload_session_store"],
                        object_store=stores["object_store"],
                        asset_store=stores["asset_store"],
                        job_store=stores["job_store"],
                        extractor_run_store=stores["extractor_run_store"],
                        observation_store=stores["observation_store"],
                        mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
                        storage_backend_id=STORAGE_BACKEND_ID,
                        actor_user_id=OWNER_USER_ID,
                        session_id=SESSION_ID,
                        query_text="audit approval",
                        created_at=NOW,
                    )

                self.assertEqual(stores["job_store"].list(), [])
                self.assertEqual(stores["extractor_run_store"].list(), [])
                self.assertEqual(stores["observation_store"].list(), [])
                self.assertEqual(connection.actions, [])
                self.assertEqual(connection.rows, {})

    def test_import_requires_matching_upload_session_before_side_effects(self) -> None:
        cases = [
            {"case_name": "missing_upload_session", "make_session": False},
            {"case_name": "wrong_actor", "actor_user_id": "user_other"},
            {"case_name": "wrong_session", "session_id": "session_wrong_upload_mail"},
            {
                "case_name": "wrong_profile",
                "intended_asset_type": "document",
                "ingestion_profile": "plain_text",
            },
        ]

        for case in cases:
            with self.subTest(case=case["case_name"]):
                temp_dir = _paths.fresh_test_dir(f"mail-upload-import-reject-{case['case_name']}")
                stores = _workflow_stores(temp_dir)
                staged_archive = _write_mail_archive(temp_dir)
                connection = _RecordingMailConnection()
                if case.get("make_session", True):
                    upload_session = _create_mail_upload_session(
                        stores["upload_session_store"],
                        audit_store=stores["audit_store"],
                        intended_asset_type=case.get("intended_asset_type", "pst"),
                        ingestion_profile=case.get(
                            "ingestion_profile",
                            "mail_archive_phase1",
                        ),
                    )
                    upload_session_id = upload_session.upload_session_id
                else:
                    upload_session_id = "upload_missing_mail_session"

                with self.assertRaises(ContractValidationError):
                    run_upload_session_mail_import(
                        staged_archive,
                        upload_session_id=upload_session_id,
                        upload_session_store=stores["upload_session_store"],
                        object_store=stores["object_store"],
                        asset_store=stores["asset_store"],
                        job_store=stores["job_store"],
                        extractor_run_store=stores["extractor_run_store"],
                        observation_store=stores["observation_store"],
                        mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
                        storage_backend_id=STORAGE_BACKEND_ID,
                        actor_user_id=case.get("actor_user_id", OWNER_USER_ID),
                        session_id=case.get("session_id", SESSION_ID),
                        query_text="audit approval",
                        created_at=NOW,
                    )

                self.assertEqual(stores["asset_store"].list(), [])
                self.assertEqual(stores["job_store"].list(), [])
                self.assertEqual(stores["extractor_run_store"].list(), [])
                self.assertEqual(stores["observation_store"].list(), [])
                self.assertEqual(connection.actions, [])

    def test_repeated_uploads_share_object_payload_and_preserve_occurrences(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-import-duplicate")
        stores = _workflow_stores(temp_dir)
        staged_archive = _write_mail_archive(temp_dir)
        connection = _RecordingMailConnection()
        mail_store = PostgreSQLMailEvidenceStore(connection)

        first_session = _create_mail_upload_session(
            stores["upload_session_store"],
            audit_store=stores["audit_store"],
            created_at="2026-07-05T10:00:00+00:00",
        )
        second_session = _create_mail_upload_session(
            stores["upload_session_store"],
            audit_store=stores["audit_store"],
            session_id="session_upload_mail_second",
            created_at="2026-07-05T10:01:00+00:00",
        )

        first = run_upload_session_mail_import(
            staged_archive,
            upload_session_id=first_session.upload_session_id,
            upload_session_store=stores["upload_session_store"],
            object_store=stores["object_store"],
            asset_store=stores["asset_store"],
            job_store=stores["job_store"],
            extractor_run_store=stores["extractor_run_store"],
            observation_store=stores["observation_store"],
            mail_evidence_store=mail_store,
            storage_backend_id=STORAGE_BACKEND_ID,
            actor_user_id=OWNER_USER_ID,
            session_id=SESSION_ID,
            query_text="audit approval",
            created_at=NOW,
        )
        second = run_upload_session_mail_import(
            staged_archive,
            upload_session_id=second_session.upload_session_id,
            upload_session_store=stores["upload_session_store"],
            object_store=stores["object_store"],
            asset_store=stores["asset_store"],
            job_store=stores["job_store"],
            extractor_run_store=stores["extractor_run_store"],
            observation_store=stores["observation_store"],
            mail_evidence_store=mail_store,
            storage_backend_id=STORAGE_BACKEND_ID,
            actor_user_id=OWNER_USER_ID,
            session_id="session_upload_mail_second",
            query_text="audit approval",
            created_at=NOW,
        )

        object_payloads = list((temp_dir / "object-root").rglob("payload.bin"))

        self.assertNotEqual(first.asset_id, second.asset_id)
        self.assertEqual(len(object_payloads), 1)
        self.assertEqual(len(connection.rows["mail_import_session"]), 2)
        self.assertEqual(len(connection.rows["email_message"]), 1)
        self.assertEqual(len(connection.rows["email_message_occurrence"]), 2)
        self.assertTrue(
            all(
                "DO NOTHING" in statement.sql
                for statement in connection.statements
                if "INSERT INTO email_message " in statement.sql
            )
        )

        with self.assertRaises(ContractValidationError):
            run_upload_session_mail_import(
                staged_archive,
                upload_session_id=first_session.upload_session_id,
                upload_session_store=stores["upload_session_store"],
                object_store=stores["object_store"],
                asset_store=stores["asset_store"],
                job_store=stores["job_store"],
                extractor_run_store=stores["extractor_run_store"],
                observation_store=stores["observation_store"],
                mail_evidence_store=mail_store,
                storage_backend_id=STORAGE_BACKEND_ID,
                actor_user_id=OWNER_USER_ID,
                session_id=SESSION_ID,
                query_text="audit approval",
                created_at=NOW,
            )

    def test_store_failure_rolls_back_and_does_not_mark_session_succeeded(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-import-store-failure")
        stores = _workflow_stores(temp_dir)
        upload_session = _create_mail_upload_session(
            stores["upload_session_store"],
            audit_store=stores["audit_store"],
        )
        staged_archive = _write_mail_archive(temp_dir)
        connection = _RecordingMailConnection(fail_after_execute=2)

        with self.assertRaises(RuntimeError):
            run_upload_session_mail_import(
                staged_archive,
                upload_session_id=upload_session.upload_session_id,
                upload_session_store=stores["upload_session_store"],
                object_store=stores["object_store"],
                asset_store=stores["asset_store"],
                job_store=stores["job_store"],
                extractor_run_store=stores["extractor_run_store"],
                observation_store=stores["observation_store"],
                mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
                storage_backend_id=STORAGE_BACKEND_ID,
                actor_user_id=OWNER_USER_ID,
                session_id=SESSION_ID,
                query_text="audit approval",
                created_at=NOW,
            )

        updated_session = stores["upload_session_store"].get(upload_session.upload_session_id)

        self.assertEqual(connection.actions, ["begin", "execute", "execute", "rollback"])
        self.assertEqual(connection.rows, {})
        self.assertEqual(updated_session.status, "failed")
        self.assertEqual(updated_session.processing_status, "mail_evidence_store_failed")
        self.assertIsNotNone(updated_session.asset_id)
        self.assertIsNotNone(updated_session.ingestion_job_id)

    def test_parser_failure_does_not_write_mail_evidence_or_mark_success(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-import-parser-failure")
        stores = _workflow_stores(temp_dir)
        upload_session = _create_mail_upload_session(
            stores["upload_session_store"],
            audit_store=stores["audit_store"],
        )
        staged_archive = _write_mail_archive(temp_dir)
        connection = _RecordingMailConnection()

        with self.assertRaises(RuntimeError):
            run_upload_session_mail_import(
                staged_archive,
                upload_session_id=upload_session.upload_session_id,
                upload_session_store=stores["upload_session_store"],
                object_store=stores["object_store"],
                asset_store=stores["asset_store"],
                job_store=stores["job_store"],
                extractor_run_store=stores["extractor_run_store"],
                observation_store=stores["observation_store"],
                mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
                storage_backend_id=STORAGE_BACKEND_ID,
                actor_user_id=OWNER_USER_ID,
                session_id=SESSION_ID,
                query_text="audit approval",
                created_at=NOW,
                adapter=_FailingMailArchiveExtractor(),
            )

        updated_session = stores["upload_session_store"].get(upload_session.upload_session_id)
        failed_jobs = stores["job_store"].list()
        failed_runs = stores["extractor_run_store"].list()

        self.assertEqual(updated_session.status, "failed")
        self.assertEqual(updated_session.processing_status, "mail_parser_failed")
        self.assertIsNotNone(updated_session.asset_id)
        self.assertIsNotNone(updated_session.ingestion_job_id)
        self.assertEqual(len(failed_jobs), 1)
        self.assertEqual(failed_jobs[0].status, "failed")
        self.assertEqual(len(failed_runs), 1)
        self.assertEqual(failed_runs[0].status, "failed")
        self.assertEqual(stores["observation_store"].list(), [])
        self.assertEqual(connection.actions, [])
        self.assertEqual(connection.rows, {})

    def test_store_backed_query_must_succeed_before_session_is_succeeded(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-import-query-failure")
        stores = _workflow_stores(temp_dir)
        upload_session = _create_mail_upload_session(
            stores["upload_session_store"],
            audit_store=stores["audit_store"],
        )
        staged_archive = _write_mail_archive(temp_dir)
        connection = _RecordingMailConnection()

        with self.assertRaises(RuntimeError):
            run_upload_session_mail_import(
                staged_archive,
                upload_session_id=upload_session.upload_session_id,
                upload_session_store=stores["upload_session_store"],
                object_store=stores["object_store"],
                asset_store=stores["asset_store"],
                job_store=stores["job_store"],
                extractor_run_store=stores["extractor_run_store"],
                observation_store=stores["observation_store"],
                mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
                storage_backend_id=STORAGE_BACKEND_ID,
                actor_user_id=OWNER_USER_ID,
                session_id=SESSION_ID,
                query_text="nonmatchingterm",
                created_at=NOW,
            )

        updated_session = stores["upload_session_store"].get(upload_session.upload_session_id)

        self.assertEqual(updated_session.status, "failed")
        self.assertEqual(updated_session.processing_status, "mail_evidence_query_failed")
        self.assertEqual(connection.actions[0], "begin")
        self.assertEqual(connection.actions[-1], "rollback")
        self.assertEqual(connection.rows, {})

    def test_public_summary_validation_rejects_leaks_and_overclaims(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-import-summary-validation")
        stores = _workflow_stores(temp_dir)
        upload_session = _create_mail_upload_session(
            stores["upload_session_store"],
            audit_store=stores["audit_store"],
        )
        staged_archive = _write_mail_archive(temp_dir)
        result = run_upload_session_mail_import(
            staged_archive,
            upload_session_id=upload_session.upload_session_id,
            upload_session_store=stores["upload_session_store"],
            object_store=stores["object_store"],
            asset_store=stores["asset_store"],
            job_store=stores["job_store"],
            extractor_run_store=stores["extractor_run_store"],
            observation_store=stores["observation_store"],
            mail_evidence_store=PostgreSQLMailEvidenceStore(_RecordingMailConnection()),
            storage_backend_id=STORAGE_BACKEND_ID,
            actor_user_id=OWNER_USER_ID,
            session_id=SESSION_ID,
            query_text="audit approval",
            created_at=NOW,
        )
        summary = result.to_public_dict()
        tampered = copy.deepcopy(summary)
        tampered["safe_outputs"]["debug_path"] = "C:\\private\\mail.pst"
        tampered["safe_outputs"]["body_text"] = "Update: Launch reviewed"
        tampered["claim_boundary"]["supports_real_pst_parser_claim"] = True

        validation = validate_mail_upload_import_summary(tampered)

        self.assertFalse(validation["passed"])
        self.assertTrue(
            any(
                blocker.startswith("safe_outputs contains unknown keys:")
                for blocker in validation["blockers"]
            )
        )
        self.assertIn(
            "forbidden claim is not explicitly false: supports_real_pst_parser_claim",
            validation["blockers"],
        )
        self.assertIn(
            "public summary leaks raw paths, SQL, secrets, or backend internals",
            validation["blockers"],
        )
        rendered_validation = str(validation)
        self.assertNotIn("C:\\private", rendered_validation)
        self.assertNotIn("Launch reviewed", rendered_validation)


def _workflow_stores(temp_dir) -> dict[str, Any]:
    registry = StorageBackendRegistry(temp_dir)
    registry.register_local_backend(
        temp_dir / "object-root",
        workspace_scope=WORKSPACE_ID,
        storage_backend_id=STORAGE_BACKEND_ID,
    )
    return {
        "upload_session_store": UploadSessionStore(temp_dir),
        "asset_store": AssetStore(temp_dir),
        "job_store": JobStore(temp_dir),
        "extractor_run_store": ExtractorRunStore(temp_dir),
        "observation_store": ObservationStore(temp_dir),
        "object_store": FileObjectStore(registry),
        "audit_store": FileAuditLogStore(temp_dir),
    }


def _create_mail_upload_session(
    upload_session_store,
    *,
    audit_store,
    session_id: str = SESSION_ID,
    intended_asset_type: str = "pst",
    ingestion_profile: str = "mail_archive_phase1",
    created_at: str = NOW,
):
    return create_upload_session(
        upload_session_store=upload_session_store,
        audit_store=audit_store,
        actor_user_id=OWNER_USER_ID,
        session_id=session_id,
        workspace_id=WORKSPACE_ID,
        owner_scope_type="project",
        owner_scope_id=PROJECT_ID,
        project_id=PROJECT_ID,
        intent="Upload PST archive for governed mail evidence reading.",
        intended_asset_type=intended_asset_type,
        ingestion_profile=ingestion_profile,
        visibility_scope="workspace",
        permission_scope=PermissionScope.project(PROJECT_ID),
        expires_at="2026-07-06T10:00:00+00:00",
        created_at=created_at,
    )


def _write_mail_archive(temp_dir) -> Any:
    source_path = temp_dir / "staged-upload" / "mail-archive.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(json.dumps(_mail_archive(), sort_keys=True), encoding="utf-8")
    return source_path


def _write_pst_archive(temp_dir) -> Any:
    source_path = temp_dir / "staged-upload" / "mail-archive.pst"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"!BDN unit pst fixture")
    return source_path


def _mail_archive() -> dict[str, Any]:
    return {
        "archive_id": "archive_launch",
        "mailbox_id": "mailbox_yifan",
        "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
        "messages": [
            {
                "message_id": "<launch-001@example.test>",
                "thread_id": "thread_launch",
                "folder_path_hash": "sha256:folder-inbox",
                "subject": "Launch checklist",
                "sender": "pm@example.test",
                "sent_at": NOW,
                "body": "Update: Launch reviewed\n\nBlocker: Waiting on audit approval",
                "body_hash": "sha256:body-launch",
            }
        ],
    }


class _RecordingMailConnection:
    def __init__(self, *, fail_after_execute: int | None = None) -> None:
        self.fail_after_execute = fail_after_execute
        self.actions: list[str] = []
        self.statements: list[Any] = []
        self.rows: dict[str, dict[str, dict[str, Any]]] = {}
        self.executed_count = 0
        self._transaction_snapshot: dict[str, dict[str, dict[str, Any]]] | None = None

    def execute(self, statement: Any) -> None:
        self.actions.append("execute")
        self.statements.append(statement)
        self.executed_count += 1
        if self.fail_after_execute is not None and self.executed_count >= self.fail_after_execute:
            raise RuntimeError("simulated mail evidence write failure")
        table_name = statement.sql.split("INSERT INTO ", 1)[1].split(" ", 1)[0]
        record_id = _statement_record_id(table_name, statement.parameters)
        if "DO NOTHING" in statement.sql and record_id in self.rows.get(table_name, {}):
            return
        self.rows.setdefault(table_name, {})[record_id] = {
            **statement.parameters,
            "payload": statement.parameters["payload"],
            "payload_hash": statement.parameters["payload_hash"],
        }

    def query_one(self, statement: Any) -> dict[str, Any] | None:
        self.actions.append("query_one")
        self.statements.append(statement)
        table_name = statement.sql.split(" FROM ", 1)[1].split(" ", 1)[0]
        rows = list(self.rows.get(table_name, {}).values())
        for row in rows:
            if _matches_optional(row, statement.parameters, "mail_import_session_id") and (
                _matches_optional(row, statement.parameters, "mail_evidence_bundle_id")
            ):
                return {
                    "payload": row["payload"],
                    "mail_evidence_bundle_id": row["mail_evidence_bundle_id"],
                    "producer_type": row["producer_type"],
                    "bundle_created_at": row["bundle_created_at"],
                }
        return None

    def query_all(self, statement: Any) -> list[dict[str, Any]]:
        self.actions.append("query_all")
        self.statements.append(statement)
        table_name = statement.sql.split(" FROM ", 1)[1].split(" ", 1)[0]
        rows = list(self.rows.get(table_name, {}).values())
        if "mail_import_session_id" in statement.parameters:
            expected = statement.parameters["mail_import_session_id"]
            rows = [row for row in rows if row.get("mail_import_session_id") == expected]
        for key, value in statement.parameters.items():
            if key.endswith("_ids"):
                id_field = key[:-1]
                allowed = set(value)
                rows = [row for row in rows if row.get(id_field) in allowed]
        return [
            {"payload": row["payload"]} for row in sorted(rows, key=lambda row: row["payload_hash"])
        ]

    def begin(self) -> None:
        self.actions.append("begin")
        self._transaction_snapshot = {
            table: {record_id: dict(row) for record_id, row in records.items()}
            for table, records in self.rows.items()
        }

    def commit(self) -> None:
        self.actions.append("commit")
        self._transaction_snapshot = None

    def rollback(self) -> None:
        self.actions.append("rollback")
        if self._transaction_snapshot is not None:
            self.rows = {
                table: {record_id: dict(row) for record_id, row in records.items()}
                for table, records in self._transaction_snapshot.items()
            }
            self._transaction_snapshot = None


def _statement_record_id(table_name: str, parameters: dict[str, Any]) -> str:
    id_fields = {
        "mail_import_session": "mail_import_session_id",
        "mail_archive_occurrence": "mail_archive_occurrence_id",
        "mail_folder_occurrence": "mail_folder_occurrence_id",
        "email_message": "email_message_id",
        "email_message_occurrence": "email_message_occurrence_id",
        "email_body_segment": "email_body_segment_id",
        "email_attachment": "email_attachment_id",
        "email_attachment_occurrence": "email_attachment_occurrence_id",
        "quoted_message_candidate": "quoted_message_candidate_id",
        "embedded_message_relation": "embedded_message_relation_id",
        "mail_parse_run": "mail_parse_run_id",
        "mail_parse_warning": "mail_parse_warning_id",
    }
    return str(parameters[id_fields[table_name]])


def _matches_optional(row: dict[str, Any], parameters: dict[str, Any], key: str) -> bool:
    return parameters.get(key) is None or row.get(key) == parameters[key]


class _FailingMailArchiveExtractor:
    def name(self) -> str:
        return "failing_mail_archive_extractor"

    def version(self) -> str:
        return "0.1.0"

    def supported_mime_types(self) -> list[str]:
        return ["application/vnd.formowl.mail-archive+json"]

    def extractor_type(self) -> str:
        return "mail_archive"

    def extract(self, extraction_input: Any) -> ExtractionResult:
        return ExtractionResult(errors=["simulated parser failure"])


def _pst_runner_with_messages(messages: list[bytes]):
    def runner(command, timeout):
        output_dir = Path(command[command.index("-o") + 1])
        for index, content in enumerate(messages, start=1):
            (output_dir / f"{index}.eml").write_bytes(content)
        return _ParserCommandResult(0)

    return runner


def _pst_rfc822_message() -> bytes:
    return (
        "Message-ID: <pst-unit-001@example.test>\n"
        "Subject: PST import checklist\n"
        "From: pm@example.test\n"
        "To: team@example.test\n"
        f"Date: {NOW}\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "Audit approval is next.\n"
    ).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
