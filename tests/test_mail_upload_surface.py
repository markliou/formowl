from __future__ import annotations

import json
import unittest
from typing import Any

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from formowl_contract import ContractValidationError, PermissionScope
from formowl_gateway import validate_public_gateway_payload
from formowl_ingestion.storage import (
    AssetStore,
    FileObjectStore,
    StorageBackendRegistry,
    UploadSessionStore,
)
from formowl_ingestion.uploads import create_upload_session
from formowl_mail import receive_mail_archive_upload, validate_mail_upload_surface_receipt

NOW = "2026-07-05T11:00:00+00:00"
WORKSPACE_ID = "workspace_formowl"
OWNER_USER_ID = "user_yifan"
SESSION_ID = "session_mail_upload_surface"
PROJECT_ID = "project_formowl"
STORAGE_BACKEND_ID = "storage_mail_upload_surface"


class MailUploadSurfaceTests(unittest.TestCase):
    def test_session_bound_upload_surface_registers_asset_binds_session_and_audits(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-surface")
        stores = _upload_surface_stores(temp_dir)
        upload_session = _create_mail_upload_session(stores["upload_session_store"], stores)
        staged_upload = _write_uploaded_archive(temp_dir)

        receipt = receive_mail_archive_upload(
            staged_upload,
            upload_session_id=upload_session.upload_session_id,
            upload_session_store=stores["upload_session_store"],
            object_store=stores["object_store"],
            asset_store=stores["asset_store"],
            audit_store=stores["audit_store"],
            storage_backend_id=STORAGE_BACKEND_ID,
            actor_user_id=OWNER_USER_ID,
            session_id=SESSION_ID,
            original_filename="mail-export.pst",
            submitted_fields={
                "upload_session_id": upload_session.upload_session_id,
                "actor_user_id": OWNER_USER_ID,
                "session_id": SESSION_ID,
                "workspace_id": WORKSPACE_ID,
                "original_filename": "mail-export.pst",
                "content_type": "application/vnd.ms-outlook",
            },
            received_at=NOW,
        )

        updated_session = stores["upload_session_store"].get(upload_session.upload_session_id)
        asset = stores["asset_store"].get(receipt.asset_id)
        summary = receipt.to_public_dict()

        self.assertEqual(receipt.status, "uploaded")
        self.assertEqual(updated_session.status, "uploading")
        self.assertEqual(updated_session.source_preparation_state, "uploaded")
        self.assertEqual(updated_session.processing_status, "archive_uploaded")
        self.assertEqual(updated_session.asset_id, receipt.asset_id)
        self.assertEqual(asset.workspace_id, WORKSPACE_ID)
        self.assertEqual(asset.owner_user_id, OWNER_USER_ID)
        self.assertEqual(asset.permission_scope, PermissionScope.project(PROJECT_ID).to_dict())
        self.assertEqual(asset.source_ref["source_system"], "formowl_upload_session")
        self.assertEqual(asset.source_ref["source_id"], upload_session.upload_session_id)
        self.assertTrue(stores["object_store"].verify_object(asset.object_uri, asset.content_hash))
        self.assertFalse(receipt.duplicate_object_payload_reused)
        self.assertTrue(summary["validation"]["passed"])
        self.assertTrue(
            summary["claim_boundary"]["supports_upload_session_bound_file_transfer_claim"]
        )
        self.assertFalse(summary["claim_boundary"]["supports_real_upload_iframe_claim"])
        self.assertFalse(
            summary["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"]
        )
        self.assertFalse(summary["claim_boundary"]["supports_real_pst_parser_claim"])
        validate_public_gateway_payload(summary)

        audit_actions = [audit.action for audit in stores["audit_store"].list()]
        self.assertEqual(
            set(audit_actions),
            {
                "upload_session_created",
                "asset_registered",
                "upload_session_file_received",
            },
        )
        self.assertEqual(len(audit_actions), 3)
        rendered_summary = json.dumps(summary, sort_keys=True)
        self.assertNotIn(str(temp_dir), rendered_summary)
        self.assertNotIn("mail-export.pst", rendered_summary)
        self.assertNotIn("payload.bin", rendered_summary)
        self.assertNotIn("formowl://object", rendered_summary)
        self.assertNotIn("SELECT", rendered_summary.upper())

    def test_repeated_uploads_reuse_payload_without_merging_upload_sessions(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-surface-duplicate")
        stores = _upload_surface_stores(temp_dir)
        staged_upload = _write_uploaded_archive(temp_dir)
        first_session = _create_mail_upload_session(
            stores["upload_session_store"],
            stores,
            created_at="2026-07-05T11:00:00+00:00",
        )
        second_session = _create_mail_upload_session(
            stores["upload_session_store"],
            stores,
            session_id="session_mail_upload_surface_second",
            created_at="2026-07-05T11:01:00+00:00",
        )

        first = receive_mail_archive_upload(
            staged_upload,
            upload_session_id=first_session.upload_session_id,
            upload_session_store=stores["upload_session_store"],
            object_store=stores["object_store"],
            asset_store=stores["asset_store"],
            audit_store=stores["audit_store"],
            storage_backend_id=STORAGE_BACKEND_ID,
            actor_user_id=OWNER_USER_ID,
            session_id=SESSION_ID,
            original_filename="mail-export.pst",
            received_at=NOW,
        )
        second = receive_mail_archive_upload(
            staged_upload,
            upload_session_id=second_session.upload_session_id,
            upload_session_store=stores["upload_session_store"],
            object_store=stores["object_store"],
            asset_store=stores["asset_store"],
            audit_store=stores["audit_store"],
            storage_backend_id=STORAGE_BACKEND_ID,
            actor_user_id=OWNER_USER_ID,
            session_id="session_mail_upload_surface_second",
            original_filename="mail-export.pst",
            received_at=NOW,
        )

        self.assertNotEqual(first.asset_id, second.asset_id)
        self.assertFalse(first.duplicate_object_payload_reused)
        self.assertTrue(second.duplicate_object_payload_reused)
        self.assertEqual(len(stores["asset_store"].list()), 2)
        self.assertEqual(len(list((temp_dir / "object-root").rglob("payload.bin"))), 1)
        self.assertEqual(
            stores["upload_session_store"].get(first_session.upload_session_id).asset_id,
            first.asset_id,
        )
        self.assertEqual(
            stores["upload_session_store"].get(second_session.upload_session_id).asset_id,
            second.asset_id,
        )

    def test_upload_surface_rejects_session_actor_profile_and_status_mismatch_before_writes(
        self,
    ) -> None:
        cases = [
            {"case_name": "missing_session", "make_session": False},
            {"case_name": "wrong_actor", "actor_user_id": "user_other"},
            {"case_name": "wrong_session", "session_id": "session_wrong"},
            {
                "case_name": "wrong_profile",
                "intended_asset_type": "document",
                "ingestion_profile": "plain_text",
            },
            {"case_name": "already_uploading", "preset_status": "uploading"},
        ]

        for case in cases:
            with self.subTest(case=case["case_name"]):
                temp_dir = _paths.fresh_test_dir(f"mail-upload-surface-reject-{case['case_name']}")
                stores = _upload_surface_stores(temp_dir)
                staged_upload = _write_uploaded_archive(temp_dir)
                if case.get("make_session", True):
                    upload_session = _create_mail_upload_session(
                        stores["upload_session_store"],
                        stores,
                        intended_asset_type=case.get("intended_asset_type", "pst"),
                        ingestion_profile=case.get(
                            "ingestion_profile",
                            "mail_archive_phase1",
                        ),
                    )
                    if case.get("preset_status") == "uploading":
                        stores["upload_session_store"].create(
                            {
                                **upload_session.to_dict(),
                                "status": "uploading",
                                "processing_status": "archive_uploaded",
                            }
                        )
                    upload_session_id = upload_session.upload_session_id
                else:
                    upload_session_id = "upload_missing_mail_surface_session"

                with self.assertRaises(ContractValidationError):
                    receive_mail_archive_upload(
                        staged_upload,
                        upload_session_id=upload_session_id,
                        upload_session_store=stores["upload_session_store"],
                        object_store=stores["object_store"],
                        asset_store=stores["asset_store"],
                        audit_store=stores["audit_store"],
                        storage_backend_id=STORAGE_BACKEND_ID,
                        actor_user_id=case.get("actor_user_id", OWNER_USER_ID),
                        session_id=case.get("session_id", SESSION_ID),
                        original_filename="mail-export.pst",
                        received_at=NOW,
                    )

                self.assertEqual(stores["asset_store"].list(), [])
                self.assertEqual(list((temp_dir / "object-root").rglob("payload.bin")), [])
                if case.get("make_session", True):
                    self.assertIsNone(
                        stores["upload_session_store"].get(upload_session_id).asset_id
                    )

    def test_upload_surface_rejects_bad_filename_hash_and_infra_form_fields_before_writes(
        self,
    ) -> None:
        cases = [
            {"case_name": "path_filename", "original_filename": "C:\\mail\\export.pst"},
            {"case_name": "unsupported_zip", "original_filename": "mail-export.zip"},
            {"case_name": "hash_mismatch", "expected_content_hash": "sha256:" + "0" * 64},
            {
                "case_name": "infra_form_field",
                "submitted_fields": {"storageBackendName": "default"},
            },
            {
                "case_name": "unbound_expected_hash_field",
                "submitted_fields": {"expected_content_hash": "sha256:" + "1" * 64},
            },
            {
                "case_name": "nested_infra_form_field",
                "submitted_fields": {"metadata": {"parserPath": "pst-parser"}},
            },
        ]

        for case in cases:
            with self.subTest(case=case["case_name"]):
                temp_dir = _paths.fresh_test_dir(f"mail-upload-surface-bad-{case['case_name']}")
                stores = _upload_surface_stores(temp_dir)
                upload_session = _create_mail_upload_session(
                    stores["upload_session_store"],
                    stores,
                )
                staged_upload = _write_uploaded_archive(temp_dir)

                with self.assertRaises(ContractValidationError):
                    receive_mail_archive_upload(
                        staged_upload,
                        upload_session_id=upload_session.upload_session_id,
                        upload_session_store=stores["upload_session_store"],
                        object_store=stores["object_store"],
                        asset_store=stores["asset_store"],
                        audit_store=stores["audit_store"],
                        storage_backend_id=STORAGE_BACKEND_ID,
                        actor_user_id=OWNER_USER_ID,
                        session_id=SESSION_ID,
                        original_filename=case.get("original_filename", "mail-export.pst"),
                        expected_content_hash=case.get("expected_content_hash"),
                        submitted_fields=case.get("submitted_fields"),
                        received_at=NOW,
                    )

                self.assertEqual(stores["asset_store"].list(), [])
                self.assertEqual(list((temp_dir / "object-root").rglob("payload.bin")), [])
                self.assertIsNone(
                    stores["upload_session_store"].get(upload_session.upload_session_id).asset_id
                )
                self.assertEqual(
                    [audit.action for audit in stores["audit_store"].list()],
                    ["upload_session_created"],
                )

    def test_upload_surface_failures_roll_back_asset_audit_and_new_object_payload(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-surface-rollback")
        stores = _upload_surface_stores(temp_dir)
        upload_session = _create_mail_upload_session(stores["upload_session_store"], stores)
        staged_upload = _write_uploaded_archive(temp_dir)
        failing_audit_store = _FailingReceiptAuditLogStore(temp_dir)

        with self.assertRaises(RuntimeError):
            receive_mail_archive_upload(
                staged_upload,
                upload_session_id=upload_session.upload_session_id,
                upload_session_store=stores["upload_session_store"],
                object_store=stores["object_store"],
                asset_store=stores["asset_store"],
                audit_store=failing_audit_store,
                storage_backend_id=STORAGE_BACKEND_ID,
                actor_user_id=OWNER_USER_ID,
                session_id=SESSION_ID,
                original_filename="mail-export.pst",
                received_at=NOW,
            )

        self.assertEqual(stores["asset_store"].list(), [])
        self.assertEqual(list((temp_dir / "object-root").rglob("payload.bin")), [])
        self.assertIsNone(
            stores["upload_session_store"].get(upload_session.upload_session_id).asset_id
        )
        self.assertEqual(
            [audit.action for audit in failing_audit_store.list()],
            ["upload_session_created"],
        )

    def test_upload_surface_rolls_back_when_existing_object_record_is_unverified(
        self,
    ) -> None:
        cases = ("missing_payload", "corrupt_payload")

        for case_name in cases:
            with self.subTest(case_name=case_name):
                temp_dir = _paths.fresh_test_dir(
                    f"mail-upload-surface-unverified-object-{case_name}"
                )
                stores = _upload_surface_stores(temp_dir)
                staged_upload = _write_uploaded_archive(temp_dir)
                stored = stores["object_store"].copy_local_file(
                    staged_upload,
                    storage_backend_id=STORAGE_BACKEND_ID,
                    workspace_id=WORKSPACE_ID,
                    original_filename="mail-export.pst",
                )
                payload_path = stores["object_store"].resolve_object_path(stored.object_uri)
                self.assertIsNotNone(payload_path)
                if case_name == "missing_payload":
                    payload_path.unlink()
                else:
                    payload_path.write_bytes(b"corrupt old payload")
                self.assertFalse(
                    stores["object_store"].verify_object(
                        stored.object_uri,
                        stored.content_hash,
                    )
                )
                upload_session = _create_mail_upload_session(
                    stores["upload_session_store"],
                    stores,
                )
                failing_audit_store = _FailingReceiptAuditLogStore(temp_dir)

                with self.assertRaises(RuntimeError):
                    receive_mail_archive_upload(
                        staged_upload,
                        upload_session_id=upload_session.upload_session_id,
                        upload_session_store=stores["upload_session_store"],
                        object_store=stores["object_store"],
                        asset_store=stores["asset_store"],
                        audit_store=failing_audit_store,
                        storage_backend_id=STORAGE_BACKEND_ID,
                        actor_user_id=OWNER_USER_ID,
                        session_id=SESSION_ID,
                        original_filename="mail-export.pst",
                        received_at=NOW,
                    )

                self.assertEqual(stores["asset_store"].list(), [])
                self.assertIsNone(stores["object_store"].resolve_object_path(stored.object_uri))
                self.assertFalse(
                    stores["object_store"].verify_object(
                        stored.object_uri,
                        stored.content_hash,
                    )
                )
                self.assertIsNone(
                    stores["upload_session_store"].get(upload_session.upload_session_id).asset_id
                )

    def test_upload_surface_session_update_failure_does_not_delete_existing_duplicate_payload(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-surface-duplicate-rollback")
        stores = _upload_surface_stores(temp_dir)
        staged_upload = _write_uploaded_archive(temp_dir)
        first_session = _create_mail_upload_session(stores["upload_session_store"], stores)
        first = receive_mail_archive_upload(
            staged_upload,
            upload_session_id=first_session.upload_session_id,
            upload_session_store=stores["upload_session_store"],
            object_store=stores["object_store"],
            asset_store=stores["asset_store"],
            audit_store=stores["audit_store"],
            storage_backend_id=STORAGE_BACKEND_ID,
            actor_user_id=OWNER_USER_ID,
            session_id=SESSION_ID,
            original_filename="mail-export.pst",
            received_at=NOW,
        )
        second_session = _create_mail_upload_session(
            stores["upload_session_store"],
            stores,
            session_id="session_mail_upload_surface_second",
            created_at="2026-07-05T11:02:00+00:00",
        )
        failing_upload_store = _FailingUploadSessionUpdateStore(temp_dir)

        with self.assertRaises(RuntimeError):
            receive_mail_archive_upload(
                staged_upload,
                upload_session_id=second_session.upload_session_id,
                upload_session_store=failing_upload_store,
                object_store=stores["object_store"],
                asset_store=stores["asset_store"],
                audit_store=stores["audit_store"],
                storage_backend_id=STORAGE_BACKEND_ID,
                actor_user_id=OWNER_USER_ID,
                session_id="session_mail_upload_surface_second",
                original_filename="mail-export.pst",
                received_at=NOW,
            )

        self.assertEqual(len(stores["asset_store"].list()), 1)
        self.assertEqual(stores["asset_store"].list()[0].asset_id, first.asset_id)
        self.assertEqual(len(list((temp_dir / "object-root").rglob("payload.bin"))), 1)
        self.assertTrue(
            stores["object_store"].verify_object(
                stores["asset_store"].get(first.asset_id).object_uri,
                stores["asset_store"].get(first.asset_id).content_hash,
            )
        )
        self.assertIsNone(
            stores["upload_session_store"].get(second_session.upload_session_id).asset_id
        )

    def test_public_receipt_validation_rejects_leaks_and_overclaims(self) -> None:
        payload = {
            "report_type": "mail_upload_surface_receipt",
            "generated_at": NOW,
            "status": "uploaded",
            "upload_session_id": "upload_001",
            "next_required_action": "server_side_mail_import",
            "upload_surface_locator": "formowl_upload_session:upload_001",
            "public_checks": {
                key: True
                for key in (
                    "upload_session_loaded",
                    "upload_session_bound_to_actor",
                    "upload_session_bound_to_session",
                    "mail_profile_bound",
                    "asset_registered",
                    "upload_session_asset_bound",
                    "file_transfer_recorded",
                    "no_user_infrastructure_controls_exposed",
                    "raw_leak_guard_passed",
                )
            },
            "safe_outputs": {
                "upload_session_id_hash": "sha256:" + "1" * 64,
                "asset_id_hash": "sha256:" + "2" * 64,
                "content_hash_hash": "sha256:" + "3" * 64,
                "original_filename_hash": "sha256:" + "4" * 64,
                "accepted_file_type": "pst",
                "file_size_bytes": 12,
                "duplicate_object_payload_reused": False,
                "audit_event_count": 2,
                "debug_path": "C:\\private\\mail.pst",
            },
            "claim_boundary": {
                "supports_upload_session_bound_file_transfer_claim": True,
                "supports_actual_chatgpt_connected_upload_claim": False,
                "supports_real_upload_iframe_claim": True,
                "supports_real_pst_parser_claim": False,
                "supports_live_postgresql_readiness_claim": False,
                "supports_production_worker_leasing_claim": False,
                "supports_kg_write_claim": False,
                "supports_wiki_projection_claim": False,
                "supports_production_ready_claim": False,
                "container_verification_required": True,
            },
        }

        validation = validate_mail_upload_surface_receipt(payload)

        self.assertFalse(validation["passed"])
        self.assertTrue(
            any(
                blocker.startswith("safe_outputs contains unknown keys:")
                for blocker in validation["blockers"]
            )
        )
        self.assertIn(
            "forbidden claim is not explicitly false: supports_real_upload_iframe_claim",
            validation["blockers"],
        )
        self.assertIn(
            "mail upload surface receipt leaks raw paths or backend controls",
            validation["blockers"],
        )
        self.assertNotIn("C:\\private", json.dumps(validation, sort_keys=True))


def _upload_surface_stores(temp_dir) -> dict[str, Any]:
    registry = StorageBackendRegistry(temp_dir)
    registry.register_local_backend(
        temp_dir / "object-root",
        workspace_scope=WORKSPACE_ID,
        storage_backend_id=STORAGE_BACKEND_ID,
    )
    return {
        "upload_session_store": UploadSessionStore(temp_dir),
        "asset_store": AssetStore(temp_dir),
        "object_store": FileObjectStore(registry),
        "audit_store": FileAuditLogStore(temp_dir),
    }


def _create_mail_upload_session(
    upload_session_store: UploadSessionStore,
    stores: dict[str, Any],
    *,
    session_id: str = SESSION_ID,
    intended_asset_type: str = "pst",
    ingestion_profile: str = "mail_archive_phase1",
    created_at: str = NOW,
):
    return create_upload_session(
        upload_session_store=upload_session_store,
        audit_store=stores["audit_store"],
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
        expires_at="2026-07-06T11:00:00+00:00",
        created_at=created_at,
    )


def _write_uploaded_archive(temp_dir):
    source_path = temp_dir / "server-staging" / "upload-body.bin"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"pst upload bytes used for transfer intake tests\n")
    return source_path


class _FailingReceiptAuditLogStore(FileAuditLogStore):
    def create(self, audit_log: Any) -> Any:
        action = audit_log.get("action") if isinstance(audit_log, dict) else audit_log.action
        if action == "upload_session_file_received":
            raise RuntimeError("receipt audit write failed")
        return super().create(audit_log)


class _FailingUploadSessionUpdateStore(UploadSessionStore):
    def create(self, upload_session: Any) -> Any:
        status = (
            upload_session.get("status")
            if isinstance(upload_session, dict)
            else upload_session.status
        )
        if status == "uploading":
            raise RuntimeError("upload session update failed")
        return super().create(upload_session)


if __name__ == "__main__":
    unittest.main()
