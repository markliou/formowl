from __future__ import annotations

import http.client
from io import BytesIO
import json
import threading
import unittest
from typing import Any

import _paths  # noqa: F401
import formowl_mail.upload_http as upload_http
from formowl_auth import FileAuditLogStore
from formowl_contract import ContractValidationError, PermissionScope
from formowl_ingestion.storage import (
    AssetStore,
    FileObjectStore,
    StorageBackendRegistry,
    UploadSessionStore,
)
from formowl_ingestion.uploads import create_upload_session
from formowl_mail import (
    MailUploadHttpSurfaceConfig,
    create_mail_upload_http_surface_server,
    validate_mail_upload_http_post_result,
)

NOW = "2026-07-05T12:00:00+00:00"
WORKSPACE_ID = "workspace_formowl"
OWNER_USER_ID = "user_yifan"
SESSION_ID = "session_mail_upload_http_surface"
PROJECT_ID = "project_formowl"
STORAGE_BACKEND_ID = "storage_mail_upload_http_surface"


class MailUploadHttpSurfaceTests(unittest.TestCase):
    def test_get_returns_session_bound_upload_form_without_backend_controls(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-http-get")
        stores = _upload_surface_stores(temp_dir)
        upload_session = _create_mail_upload_session(stores["upload_session_store"], stores)
        config = _http_config(temp_dir, stores)

        with _RunningHttpSurface(config) as surface:
            response, body = surface.request(
                "GET",
                f"/mail/upload/{upload_session.upload_session_id}",
            )

        html = body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn(f'action="/mail/upload/{upload_session.upload_session_id}"', html)
        self.assertIn(f'value="{upload_session.upload_session_id}"', html)
        self.assertIn(f'value="{WORKSPACE_ID}"', html)
        self.assertIn('name="mail_archive"', html)
        self.assertIn('accept=".pst,.ost,.msg,.eml,.mbox"', html)
        self.assertNotIn(OWNER_USER_ID, html)
        self.assertNotIn(SESSION_ID, html)
        rendered = html.lower()
        for forbidden in (
            "storage_backend_id",
            "object_store",
            "parser_path",
            "worker_queue",
            "nas_path",
            "payload.bin",
            "formowl://object",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_post_multipart_upload_registers_asset_binds_session_and_cleans_staging(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-http-post")
        stores = _upload_surface_stores(temp_dir)
        upload_session = _create_mail_upload_session(stores["upload_session_store"], stores)
        config = _http_config(temp_dir, stores)
        body, content_type = _multipart_body(
            {
                "upload_session_id": upload_session.upload_session_id,
                "workspace_id": WORKSPACE_ID,
            },
            filename="mail-export.pst",
            content=b"pst bytes from a browser multipart upload\n",
        )

        with _RunningHttpSurface(config) as surface:
            response, response_body = surface.request(
                "POST",
                f"/mail/upload/{upload_session.upload_session_id}",
                body=body,
                headers={"Content-Type": content_type, "Content-Length": str(len(body))},
            )

        payload = json.loads(response_body.decode("utf-8"))
        validation = validate_mail_upload_http_post_result(payload)
        updated_session = stores["upload_session_store"].get(upload_session.upload_session_id)

        self.assertEqual(response.status, 201)
        self.assertTrue(payload["validation"]["passed"])
        self.assertTrue(validation["passed"])
        self.assertTrue(
            payload["claim_boundary"]["supports_local_http_upload_surface_contract_claim"]
        )
        self.assertFalse(
            payload["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"]
        )
        self.assertFalse(payload["claim_boundary"]["supports_real_upload_iframe_claim"])
        self.assertFalse(payload["claim_boundary"]["supports_real_pst_parser_claim"])
        self.assertEqual(updated_session.status, "uploading")
        self.assertIsNotNone(updated_session.asset_id)
        self.assertEqual(len(stores["asset_store"].list()), 1)
        stored_asset = stores["asset_store"].get(updated_session.asset_id)
        self.assertIsNotNone(stored_asset)
        assert stored_asset is not None
        self.assertTrue(
            stores["object_store"].verify_object(
                stored_asset.object_uri,
                stored_asset.content_hash,
            )
        )
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
        self.assertEqual(list((temp_dir / "staging").rglob("*")), [])
        rendered = response_body.decode("utf-8").lower()
        self.assertNotIn(str(temp_dir).lower(), rendered)
        self.assertNotIn("mail-export.pst", rendered)
        self.assertNotIn("payload.bin", rendered)
        self.assertNotIn("formowl://object", rendered)
        self.assertNotIn("select ", rendered)

    def test_post_rejects_route_form_mismatch_before_durable_writes(self) -> None:
        cases = [
            {
                "case_name": "wrong_upload_session_id",
                "fields": {
                    "upload_session_id": "upload_wrong_http_surface_session",
                    "workspace_id": WORKSPACE_ID,
                },
            },
            {
                "case_name": "wrong_workspace_id",
                "fields": {
                    "upload_session_id": None,
                    "workspace_id": "workspace_other",
                },
            },
            {
                "case_name": "missing_workspace_id",
                "fields": {
                    "upload_session_id": None,
                },
            },
        ]

        for case in cases:
            with self.subTest(case=case["case_name"]):
                temp_dir = _paths.fresh_test_dir(
                    f"mail-upload-http-route-mismatch-{case['case_name']}"
                )
                stores = _upload_surface_stores(temp_dir)
                upload_session = _create_mail_upload_session(
                    stores["upload_session_store"],
                    stores,
                )
                config = _http_config(temp_dir, stores)
                fields = {
                    key: upload_session.upload_session_id if value is None else value
                    for key, value in case["fields"].items()
                }
                body, content_type = _multipart_body(
                    fields,
                    filename="mail-export.pst",
                    content=b"pst bytes should not persist\n",
                )

                with _RunningHttpSurface(config) as surface:
                    response, response_body = surface.request(
                        "POST",
                        f"/mail/upload/{upload_session.upload_session_id}",
                        body=body,
                        headers={"Content-Type": content_type, "Content-Length": str(len(body))},
                    )

                self.assertEqual(response.status, 400)
                self.assertEqual(
                    json.loads(response_body)["error_code"],
                    "upload_request_rejected",
                )
                self.assertEqual(stores["asset_store"].list(), [])
                self.assertEqual(list((temp_dir / "object-root").rglob("payload.bin")), [])
                self.assertEqual(list((temp_dir / "staging").rglob("*")), [])
                self.assertIsNone(
                    stores["upload_session_store"].get(upload_session.upload_session_id).asset_id
                )
                self.assertEqual(
                    [audit.action for audit in stores["audit_store"].list()],
                    ["upload_session_created"],
                )

    def test_post_rejects_missing_upload_session_id_before_durable_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-http-missing-upload-session-field")
        stores = _upload_surface_stores(temp_dir)
        upload_session = _create_mail_upload_session(stores["upload_session_store"], stores)
        config = _http_config(temp_dir, stores)
        body, content_type = _multipart_body(
            {"workspace_id": WORKSPACE_ID},
            filename="mail-export.pst",
            content=b"pst bytes should not persist\n",
        )

        with _RunningHttpSurface(config) as surface:
            response, response_body = surface.request(
                "POST",
                f"/mail/upload/{upload_session.upload_session_id}",
                body=body,
                headers={"Content-Type": content_type, "Content-Length": str(len(body))},
            )

        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response_body)["error_code"], "upload_request_rejected")
        self.assertEqual(stores["asset_store"].list(), [])
        self.assertEqual(list((temp_dir / "object-root").rglob("payload.bin")), [])
        self.assertEqual(list((temp_dir / "staging").rglob("*")), [])
        self.assertIsNone(
            stores["upload_session_store"].get(upload_session.upload_session_id).asset_id
        )
        self.assertEqual(
            [audit.action for audit in stores["audit_store"].list()],
            ["upload_session_created"],
        )

    def test_post_rejects_bad_multipart_and_infra_fields_before_durable_writes(self) -> None:
        cases = [
            {
                "case_name": "missing_file",
                "fields": {"upload_session_id": None, "workspace_id": WORKSPACE_ID},
                "filename": None,
                "content": b"",
            },
            {
                "case_name": "unsupported_filename",
                "fields": {"upload_session_id": None, "workspace_id": WORKSPACE_ID},
                "filename": "mail-export.zip",
                "content": b"zip bytes",
            },
            {
                "case_name": "infra_field",
                "fields": {
                    "upload_session_id": None,
                    "workspace_id": WORKSPACE_ID,
                    "storageBackendName": "default",
                },
                "filename": "mail-export.pst",
                "content": b"pst bytes",
            },
            {
                "case_name": "missing_boundary",
                "fields": {"upload_session_id": None, "workspace_id": WORKSPACE_ID},
                "filename": "mail-export.pst",
                "content": b"pst bytes",
                "content_type": "multipart/form-data",
            },
            {
                "case_name": "missing_close_boundary",
                "fields": {"upload_session_id": None, "workspace_id": WORKSPACE_ID},
                "filename": "mail-export.pst",
                "content": b"pst bytes",
                "truncate_closing_boundary": True,
            },
        ]

        for case in cases:
            with self.subTest(case=case["case_name"]):
                temp_dir = _paths.fresh_test_dir(f"mail-upload-http-bad-{case['case_name']}")
                stores = _upload_surface_stores(temp_dir)
                upload_session = _create_mail_upload_session(
                    stores["upload_session_store"],
                    stores,
                )
                fields = {
                    key: upload_session.upload_session_id if value is None else value
                    for key, value in case["fields"].items()
                }
                body, content_type = _multipart_body(
                    fields,
                    filename=case["filename"],
                    content=case["content"],
                )
                if case.get("truncate_closing_boundary"):
                    body = body.rsplit(b"----FormOwlMailUploadHttpBoundary--", 1)[0]
                config = _http_config(temp_dir, stores)

                with _RunningHttpSurface(config) as surface:
                    response, _ = surface.request(
                        "POST",
                        f"/mail/upload/{upload_session.upload_session_id}",
                        body=body,
                        headers={
                            "Content-Type": case.get("content_type", content_type),
                            "Content-Length": str(len(body)),
                        },
                    )

                self.assertEqual(response.status, 400)
                self.assertEqual(stores["asset_store"].list(), [])
                self.assertEqual(list((temp_dir / "object-root").rglob("payload.bin")), [])
                self.assertEqual(list((temp_dir / "staging").rglob("*")), [])
                self.assertIsNone(
                    stores["upload_session_store"].get(upload_session.upload_session_id).asset_id
                )
                self.assertEqual(
                    [audit.action for audit in stores["audit_store"].list()],
                    ["upload_session_created"],
                )

    def test_short_http_body_read_is_rejected_before_multipart_parsing(self) -> None:
        with self.assertRaises(ContractValidationError):
            upload_http._read_request_body(BytesIO(b"abc"), 8)

    def test_post_rejects_duplicate_multipart_fields_before_durable_writes(self) -> None:
        cases = [
            {
                "case_name": "duplicate_file",
                "field_pairs": None,
                "files": [
                    ("mail-export.pst", b"first pst bytes"),
                    ("mail-export-second.pst", b"second pst bytes"),
                ],
            },
            {
                "case_name": "duplicate_upload_session_id",
                "field_pairs": [
                    ("upload_session_id", None),
                    ("upload_session_id", None),
                    ("workspace_id", WORKSPACE_ID),
                ],
                "files": [("mail-export.pst", b"pst bytes")],
            },
            {
                "case_name": "duplicate_workspace_id",
                "field_pairs": [
                    ("upload_session_id", None),
                    ("workspace_id", WORKSPACE_ID),
                    ("workspace_id", WORKSPACE_ID),
                ],
                "files": [("mail-export.pst", b"pst bytes")],
            },
        ]

        for case in cases:
            with self.subTest(case=case["case_name"]):
                temp_dir = _paths.fresh_test_dir(f"mail-upload-http-duplicate-{case['case_name']}")
                stores = _upload_surface_stores(temp_dir)
                upload_session = _create_mail_upload_session(
                    stores["upload_session_store"],
                    stores,
                )
                field_pairs = case["field_pairs"] or [
                    ("upload_session_id", upload_session.upload_session_id),
                    ("workspace_id", WORKSPACE_ID),
                ]
                resolved_field_pairs = [
                    (
                        key,
                        upload_session.upload_session_id if value is None else value,
                    )
                    for key, value in field_pairs
                ]
                body, content_type = _multipart_body_parts(
                    resolved_field_pairs,
                    files=case["files"],
                )
                config = _http_config(temp_dir, stores)

                with _RunningHttpSurface(config) as surface:
                    response, _ = surface.request(
                        "POST",
                        f"/mail/upload/{upload_session.upload_session_id}",
                        body=body,
                        headers={"Content-Type": content_type, "Content-Length": str(len(body))},
                    )

                self.assertEqual(response.status, 400)
                self.assertEqual(stores["asset_store"].list(), [])
                self.assertEqual(list((temp_dir / "object-root").rglob("payload.bin")), [])
                self.assertEqual(list((temp_dir / "staging").rglob("*")), [])
                self.assertIsNone(
                    stores["upload_session_store"].get(upload_session.upload_session_id).asset_id
                )
                self.assertEqual(
                    [audit.action for audit in stores["audit_store"].list()],
                    ["upload_session_created"],
                )

    def test_post_rejects_oversize_request_before_staging_or_durable_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("mail-upload-http-too-large")
        stores = _upload_surface_stores(temp_dir)
        upload_session = _create_mail_upload_session(stores["upload_session_store"], stores)
        body, content_type = _multipart_body(
            {
                "upload_session_id": upload_session.upload_session_id,
                "workspace_id": WORKSPACE_ID,
            },
            filename="mail-export.pst",
            content=b"x" * 128,
        )
        config = _http_config(temp_dir, stores, max_request_bytes=64)

        with _RunningHttpSurface(config) as surface:
            response, response_body = surface.request(
                "POST",
                f"/mail/upload/{upload_session.upload_session_id}",
                body=body,
                headers={"Content-Type": content_type, "Content-Length": str(len(body))},
            )

        payload = json.loads(response_body.decode("utf-8"))
        self.assertEqual(response.status, 413)
        self.assertEqual(payload["error_code"], "upload_request_too_large")
        self.assertEqual(stores["asset_store"].list(), [])
        self.assertEqual(list((temp_dir / "object-root").rglob("payload.bin")), [])
        self.assertEqual(list((temp_dir / "staging").rglob("*")), [])
        self.assertIsNone(
            stores["upload_session_store"].get(upload_session.upload_session_id).asset_id
        )

    def test_get_and_post_reject_wrong_actor_status_or_route_without_durable_writes(self) -> None:
        cases = [
            {"case_name": "wrong_actor", "actor_user_id": "user_other", "get_status": 404},
            {"case_name": "already_uploading", "status": "uploading", "get_status": 404},
            {
                "case_name": "missing_route",
                "route": "/mail/upload/missing_session",
                "get_status": 404,
            },
        ]

        for case in cases:
            with self.subTest(case=case["case_name"]):
                temp_dir = _paths.fresh_test_dir(f"mail-upload-http-session-{case['case_name']}")
                stores = _upload_surface_stores(temp_dir)
                upload_session = _create_mail_upload_session(
                    stores["upload_session_store"],
                    stores,
                )
                if case.get("status") == "uploading":
                    stores["upload_session_store"].create(
                        {
                            **upload_session.to_dict(),
                            "status": "uploading",
                            "processing_status": "archive_uploaded",
                        }
                    )
                route = case.get("route", f"/mail/upload/{upload_session.upload_session_id}")
                body, content_type = _multipart_body(
                    {
                        "upload_session_id": upload_session.upload_session_id,
                        "workspace_id": WORKSPACE_ID,
                    },
                    filename="mail-export.pst",
                    content=b"pst bytes",
                )
                config = _http_config(
                    temp_dir,
                    stores,
                    actor_user_id=case.get("actor_user_id", OWNER_USER_ID),
                )

                with _RunningHttpSurface(config) as surface:
                    get_response, _ = surface.request("GET", route)
                    post_response, _ = surface.request(
                        "POST",
                        route,
                        body=body,
                        headers={"Content-Type": content_type, "Content-Length": str(len(body))},
                    )

                self.assertEqual(get_response.status, case["get_status"])
                self.assertEqual(post_response.status, 400)
                self.assertEqual(stores["asset_store"].list(), [])
                self.assertEqual(list((temp_dir / "object-root").rglob("payload.bin")), [])
                self.assertEqual(list((temp_dir / "staging").rglob("*")), [])

    def test_public_http_result_validation_rejects_overclaims_and_leaks(self) -> None:
        report = _valid_http_post_result()
        report["safe_outputs"]["receipt_hash"] = "sha256:short"
        report["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"] = True
        report["receipt"]["safe_outputs"]["debug_path"] = "C:\\private\\mail.pst"

        validation = validate_mail_upload_http_post_result(report)

        self.assertFalse(validation["passed"])
        self.assertIn("safe_outputs.receipt_hash must be a sha256 hash", validation["blockers"])
        self.assertIn(
            "claim boundary mismatch: supports_actual_chatgpt_connected_upload_claim",
            validation["blockers"],
        )
        self.assertIn("embedded upload receipt must validate", validation["blockers"])
        self.assertIn(
            "mail upload HTTP response leaks raw paths or backend controls",
            validation["blockers"],
        )
        self.assertNotIn("C:\\private", json.dumps(validation, sort_keys=True))

    def test_public_http_result_validation_rejects_tampered_embedded_validation(self) -> None:
        report = _valid_http_post_result()
        report["validation"] = {
            "passed": True,
            "blockers": [],
            "claim_boundary": {
                "supports_local_http_upload_surface_contract_claim": True,
                "supports_production_ready_claim": True,
            },
        }

        validation = validate_mail_upload_http_post_result(report)

        self.assertFalse(validation["passed"])
        self.assertIn("validation production claim must be false", validation["blockers"])


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


def _http_config(
    temp_dir,
    stores: dict[str, Any],
    *,
    actor_user_id: str = OWNER_USER_ID,
    max_request_bytes: int = 1024 * 1024,
) -> MailUploadHttpSurfaceConfig:
    return MailUploadHttpSurfaceConfig(
        upload_session_store=stores["upload_session_store"],
        object_store=stores["object_store"],
        asset_store=stores["asset_store"],
        audit_store=stores["audit_store"],
        storage_backend_id=STORAGE_BACKEND_ID,
        actor_user_id=actor_user_id,
        session_id=SESSION_ID,
        workspace_id=WORKSPACE_ID,
        staging_dir=temp_dir / "staging",
        received_at=NOW,
        max_request_bytes=max_request_bytes,
    )


def _create_mail_upload_session(
    upload_session_store: UploadSessionStore,
    stores: dict[str, Any],
):
    return create_upload_session(
        upload_session_store=upload_session_store,
        audit_store=stores["audit_store"],
        actor_user_id=OWNER_USER_ID,
        session_id=SESSION_ID,
        workspace_id=WORKSPACE_ID,
        owner_scope_type="project",
        owner_scope_id=PROJECT_ID,
        project_id=PROJECT_ID,
        intent="Upload PST archive for governed mail evidence reading.",
        intended_asset_type="pst",
        ingestion_profile="mail_archive_phase1",
        visibility_scope="workspace",
        permission_scope=PermissionScope.project(PROJECT_ID),
        expires_at="2026-07-06T12:00:00+00:00",
        created_at=NOW,
    )


def _multipart_body(
    fields: dict[str, str],
    *,
    filename: str | None,
    content: bytes,
    file_content_type: str = "application/vnd.ms-outlook",
) -> tuple[bytes, str]:
    return _multipart_body_parts(
        list(fields.items()),
        files=[] if filename is None else [(filename, content)],
        file_content_type=file_content_type,
    )


def _multipart_body_parts(
    field_pairs: list[tuple[str, str]],
    *,
    files: list[tuple[str, bytes]],
    file_content_type: str = "application/vnd.ms-outlook",
) -> tuple[bytes, str]:
    boundary = "----FormOwlMailUploadHttpBoundary"
    parts: list[bytes] = []
    for key, value in field_pairs:
        parts.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for filename, content in files:
        parts.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="mail_archive"; '
                    f'filename="{filename}"\r\n'
                ).encode("ascii"),
                f"Content-Type: {file_content_type}\r\n\r\n".encode("ascii"),
                content,
                b"\r\n",
            ]
        )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _valid_http_post_result() -> dict[str, Any]:
    receipt = {
        "report_type": "mail_upload_surface_receipt",
        "generated_at": NOW,
        "status": "uploaded",
        "upload_session_id": "upload_001",
        "next_required_action": "server_side_mail_import",
        "upload_surface_locator": "formowl_upload_session:upload_001",
        "public_checks": {
            "upload_session_loaded": True,
            "upload_session_bound_to_actor": True,
            "upload_session_bound_to_session": True,
            "mail_profile_bound": True,
            "asset_registered": True,
            "upload_session_asset_bound": True,
            "file_transfer_recorded": True,
            "no_user_infrastructure_controls_exposed": True,
            "raw_leak_guard_passed": True,
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
        },
        "claim_boundary": {
            "supports_upload_session_bound_file_transfer_claim": True,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_real_pst_parser_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }
    return {
        "report_type": "mail_upload_http_surface_post",
        "generated_at": NOW,
        "status": "uploaded",
        "http_status_code": 201,
        "upload_session_id": "upload_001",
        "receipt": receipt,
        "public_checks": {
            "http_upload_surface_received_multipart": True,
            "upload_session_bound_to_route": True,
            "backend_intake_receipt_validated": True,
            "no_user_infrastructure_controls_exposed": True,
            "staging_file_removed_after_intake": True,
        },
        "safe_outputs": {
            "upload_session_id_hash": "sha256:" + "5" * 64,
            "receipt_hash": "sha256:" + "6" * 64,
            "http_status_code": 201,
        },
        "claim_boundary": {
            "supports_local_http_upload_surface_contract_claim": True,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_real_pst_parser_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }


class _RunningHttpSurface:
    def __init__(self, config: MailUploadHttpSurfaceConfig) -> None:
        self.server = create_mail_upload_http_surface_server("127.0.0.1", 0, config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ):
        connection = http.client.HTTPConnection(
            self.server.server_address[0],
            self.server.server_address[1],
            timeout=5,
        )
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            response_body = response.read()
            return response, response_body
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
