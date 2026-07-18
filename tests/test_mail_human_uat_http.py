from __future__ import annotations

import http.client
import json
from pathlib import Path
import threading
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
from formowl_mail.bundle import (
    EmailBodySegment,
    EmailMessage,
    MailEvidenceBundle,
    MailImportSession,
    MailParseRun,
)
from formowl_mail.human_uat_http import (
    MailHumanUatHttpConfig,
    MailHumanUatService,
    create_mail_human_uat_http_server,
)

ACCESS_CODE = "may-uat-access-code-2026"
NOW = "2026-07-18T12:00:00+00:00"


class MailHumanUatHttpTests(unittest.TestCase):
    def test_page_is_safe_and_health_does_not_require_access_code(self) -> None:
        service = _service("mail-human-uat-page")
        with _RunningSurface(service) as surface:
            page_response, page_body = surface.request("GET", "/")
            health_response, health_body = surface.request("GET", "/api/health")

        html = page_body.decode("utf-8")
        health = json.loads(health_body)
        self.assertEqual(page_response.status, 200)
        self.assertEqual(health_response.status, 200)
        self.assertIn("郵件證據功能測試", html)
        self.assertIn("上傳新的 EML 郵件", html)
        self.assertIn('id="mail-files"', html)
        self.assertNotIn("user_may", html)
        self.assertNotIn("workspace_formowl", html)
        self.assertNotIn("/tmp/", html)
        self.assertTrue(health["chatgpt_bypassed"])
        self.assertFalse(health["upload_required"])
        self.assertTrue(health["upload_supported"])
        self.assertTrue(health["read_only_business_systems"])
        self.assertEqual(health["uploaded_file_count"], 0)
        self.assertEqual(page_response.getheader("Cache-Control"), "no-store, max-age=0")
        self.assertEqual(page_response.getheader("X-Frame-Options"), "DENY")

    def test_summary_and_query_require_the_server_access_code(self) -> None:
        service = _service("mail-human-uat-auth")
        with _RunningSurface(service) as surface:
            denied, denied_body = surface.request("GET", "/api/session-summary")
            wrong, _ = surface.request(
                "GET",
                "/api/session-summary",
                headers={"X-FormOwl-UAT-Code": "wrong-code"},
            )
            allowed, allowed_body = surface.request(
                "GET",
                "/api/session-summary",
                headers=_auth_headers(),
            )

        self.assertEqual(denied.status, 401)
        self.assertEqual(wrong.status, 401)
        self.assertEqual(json.loads(denied_body)["error_code"], "access_denied")
        self.assertEqual(allowed.status, 200)
        self.assertEqual(json.loads(allowed_body)["query_count"], 0)

    def test_chinese_business_query_expands_and_returns_cited_read_only_evidence(
        self,
    ) -> None:
        service = _service("mail-human-uat-query")
        with _RunningSurface(service) as surface:
            response, body = surface.request_json(
                "/api/query",
                {
                    "query_text": "最近一次文顥的量產時間",
                    "sort": "recent",
                    "limit": 5,
                },
            )

        payload = json.loads(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(payload["result_count"], 1)
        self.assertIn("文顥", payload["results"][0]["subject"])
        self.assertIn("SP.Z6H02G003", payload["results"][0]["snippet"])
        self.assertEqual(payload["results"][0]["sent_at"], "2026-06-15T08:00:00+00:00")
        self.assertTrue(payload["results"][0]["citation"]["citation_id"])
        self.assertTrue(payload["claim_boundary"]["chatgpt_bypassed"])
        self.assertTrue(payload["claim_boundary"]["read_only_mail_evidence"])
        self.assertFalse(payload["claim_boundary"]["project_or_wiki_write_performed"])
        self.assertFalse(payload["claim_boundary"]["canonical_graph_write_performed"])
        self.assertFalse(payload["claim_boundary"]["production_ready"])

    def test_pull_in_query_returns_context_window_and_records_private_feedback(self) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-feedback")
        service = _service_from_state_dir(state_dir)
        with _RunningSurface(service) as surface:
            query_response, query_body = surface.request_json(
                "/api/query",
                {
                    "query_text": "有哪些料件需要 pull-in",
                    "sort": "relevance",
                    "limit": 8,
                },
            )
            query = json.loads(query_body)
            feedback_response, feedback_body = surface.request_json(
                "/api/feedback",
                {
                    "query_id": query["query_id"],
                    "verdict": "partially_correct",
                    "note": "料號正確，但需要再確認交期。",
                },
            )
            summary_response, summary_body = surface.request(
                "GET",
                "/api/session-summary",
                headers=_auth_headers(),
            )

        feedback = json.loads(feedback_body)
        summary = json.loads(summary_body)
        self.assertEqual(query_response.status, 200)
        self.assertEqual(query["result_count"], 1)
        self.assertIn("pull-in", query["results"][0]["snippet"])
        self.assertLessEqual(len(query["results"][0]["snippet"]), 1604)
        self.assertEqual(feedback_response.status, 200)
        self.assertEqual(feedback["status"], "recorded")
        self.assertEqual(summary_response.status, 200)
        self.assertEqual(summary["query_count"], 1)
        self.assertEqual(summary["feedback_count"], 1)
        self.assertEqual(summary["verdict_counts"]["partially_correct"], 1)
        event_path = state_dir / "mail-human-uat-events.private.jsonl"
        events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([event["event_type"] for event in events], ["query", "feedback"])
        self.assertEqual(events[1]["note"], "料號正確，但需要再確認交期。")
        self.assertEqual(event_path.stat().st_mode & 0o777, 0o600)

    def test_browser_cannot_supply_identity_or_unrecognized_controls(self) -> None:
        service = _service("mail-human-uat-identity-guard")
        cases = [
            {
                "query_text": "pull-in",
                "requester_user_id": "user_other",
            },
            {
                "query_text": "pull-in",
                "workspace_id": "workspace_other",
            },
            {
                "query_text": "pull-in",
                "storage_backend": "private",
            },
        ]
        with _RunningSurface(service) as surface:
            responses = [surface.request_json("/api/query", case) for case in cases]

        for response, body in responses:
            self.assertEqual(response.status, 400)
            self.assertEqual(json.loads(body)["error_code"], "request_rejected")
        self.assertEqual(service.session_summary()["query_count"], 0)

    def test_uploaded_eml_is_private_persistent_and_immediately_queryable(self) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-eml-upload")
        service = _service_from_state_dir(state_dir)
        eml = _eml(
            subject="May new pull-in request",
            body=(
                "Please pull-in material NEW.PART.001, PO 470009999, "
                "requested timing 2026-08-01."
            ),
        )
        with _RunningSurface(service) as surface:
            upload_response, upload_body = surface.request_upload([("may-new-message.eml", eml)])
            query_response, query_body = surface.request_json(
                "/api/query",
                {
                    "query_text": "NEW.PART.001 pull-in",
                    "sort": "recent",
                    "limit": 5,
                },
            )
            summary_response, summary_body = surface.request(
                "GET",
                "/api/session-summary",
                headers=_auth_headers(),
            )

        upload = json.loads(upload_body)
        query = json.loads(query_body)
        summary = json.loads(summary_body)
        self.assertEqual(upload_response.status, 201)
        self.assertEqual(upload["accepted_file_count"], 1)
        self.assertEqual(upload["duplicate_file_count"], 0)
        self.assertTrue(upload["claim_boundary"]["mail_upload_performed"])
        self.assertFalse(upload["claim_boundary"]["project_or_wiki_write_performed"])
        self.assertNotIn("may-new-message.eml", upload_body.decode("utf-8"))
        self.assertNotIn("NEW.PART.001", upload_body.decode("utf-8"))
        self.assertEqual(query_response.status, 200)
        uploaded_results = [
            result for result in query["results"] if result["source_kind"] == "uploaded_uat"
        ]
        self.assertEqual(len(uploaded_results), 1)
        self.assertIn("NEW.PART.001", uploaded_results[0]["snippet"])
        self.assertEqual(summary_response.status, 200)
        self.assertEqual(summary["uploaded_file_count"], 1)
        self.assertEqual(summary["uploaded_message_count"], 1)

        upload_dir = state_dir / "mail-human-uat-uploads.private"
        stored = list(upload_dir.iterdir())
        self.assertEqual(len(stored), 1)
        self.assertRegex(stored[0].name, r"^[0-9a-f]{64}\.eml$")
        self.assertEqual(stored[0].stat().st_mode & 0o777, 0o600)

        restarted = _service_from_state_dir(state_dir)
        restarted_query = restarted.query(
            {
                "query_text": "NEW.PART.001 pull-in",
                "sort": "recent",
                "limit": 5,
            }
        )
        self.assertEqual(restarted.session_summary()["uploaded_file_count"], 1)
        self.assertEqual(restarted_query["results"][0]["source_kind"], "uploaded_uat")

    def test_duplicate_upload_does_not_duplicate_searchable_mail(self) -> None:
        service = _service("mail-human-uat-eml-duplicate")
        eml = _eml(
            subject="Unique UAT mail",
            body="UniqueUploadTerm PO 470008888.",
        )
        with _RunningSurface(service) as surface:
            first_response, first_body = surface.request_upload([("one.eml", eml)])
            second_response, second_body = surface.request_upload([("same-copy.eml", eml)])

        self.assertEqual(first_response.status, 201)
        self.assertEqual(second_response.status, 201)
        self.assertEqual(json.loads(first_body)["accepted_file_count"], 1)
        self.assertEqual(json.loads(second_body)["accepted_file_count"], 0)
        self.assertEqual(json.loads(second_body)["duplicate_file_count"], 1)
        self.assertEqual(service.session_summary()["uploaded_message_count"], 1)
        self.assertEqual(
            service.query({"query_text": "UniqueUploadTerm", "limit": 5})["result_count"],
            1,
        )

    def test_inline_text_attachment_is_warned_but_not_indexed(self) -> None:
        service = _service("mail-human-uat-inline-attachment")
        with _RunningSurface(service) as surface:
            upload_response, upload_body = surface.request_upload(
                [
                    (
                        "inline-attachment.eml",
                        _eml_with_inline_text_attachment(
                            body="SearchableMainBodyTerm PO 470007777.",
                            attachment_body="ATTACHMENT_SECRET_94721",
                        ),
                    )
                ]
            )
            main_query_response, main_query_body = surface.request_json(
                "/api/query",
                {"query_text": "SearchableMainBodyTerm", "limit": 5},
            )
            attachment_query_response, attachment_query_body = surface.request_json(
                "/api/query",
                {"query_text": "ATTACHMENT_SECRET_94721", "limit": 5},
            )

        upload = json.loads(upload_body)
        main_query = json.loads(main_query_body)
        attachment_query = json.loads(attachment_query_body)
        self.assertEqual(upload_response.status, 201)
        self.assertIn("uat_eml_attachments_not_indexed", upload["warnings"])
        self.assertEqual(main_query_response.status, 200)
        self.assertEqual(main_query["result_count"], 1)
        self.assertEqual(attachment_query_response.status, 200)
        self.assertEqual(attachment_query["result_count"], 0)
        self.assertNotIn("ATTACHMENT_SECRET_94721", upload_body.decode("utf-8"))

    def test_attached_eml_is_warned_but_not_indexed(self) -> None:
        service = _service("mail-human-uat-attached-eml")
        with _RunningSurface(service) as surface:
            upload_response, upload_body = surface.request_upload(
                [
                    (
                        "attached-message.eml",
                        _eml_with_attached_message(
                            body="VISIBLE_PARENT_BODY PO 470006666.",
                            attached_body="ATTACHED_SECRET_TERM_56391",
                        ),
                    )
                ]
            )
            parent_query_response, parent_query_body = surface.request_json(
                "/api/query",
                {"query_text": "VISIBLE_PARENT_BODY", "limit": 5},
            )
            attachment_query_response, attachment_query_body = surface.request_json(
                "/api/query",
                {"query_text": "ATTACHED_SECRET_TERM_56391", "limit": 5},
            )

        upload = json.loads(upload_body)
        parent_query = json.loads(parent_query_body)
        attachment_query = json.loads(attachment_query_body)
        self.assertEqual(upload_response.status, 201)
        self.assertIn("uat_eml_attachments_not_indexed", upload["warnings"])
        self.assertEqual(parent_query_response.status, 200)
        self.assertEqual(parent_query["result_count"], 1)
        self.assertEqual(attachment_query_response.status, 200)
        self.assertEqual(attachment_query["result_count"], 0)
        self.assertNotIn("ATTACHED_SECRET_TERM_56391", upload_body.decode("utf-8"))

    def test_upload_requires_access_code_and_rejects_msg_or_oversized_eml(self) -> None:
        service = MailHumanUatService(
            MailHumanUatHttpConfig(
                bundle=_bundle(),
                access_code=ACCESS_CODE,
                state_dir=_paths.fresh_test_dir("mail-human-uat-upload-negative"),
                fixed_now=NOW,
                max_upload_request_bytes=2048,
                max_upload_file_bytes=512,
            )
        )
        with _RunningSurface(service) as surface:
            denied, denied_body = surface.request_upload(
                [("denied.eml", _eml(subject="Denied", body="Denied body"))],
                authenticated=False,
            )
            unsupported, unsupported_body = surface.request_upload(
                [("mail.msg", b"not a msg parser input")]
            )
            oversized, oversized_body = surface.request_upload(
                [("large.eml", _eml(subject="Large", body="x" * 700))]
            )

        self.assertEqual(denied.status, 401)
        self.assertEqual(json.loads(denied_body)["error_code"], "access_denied")
        self.assertEqual(unsupported.status, 400)
        self.assertEqual(json.loads(unsupported_body)["error_code"], "request_rejected")
        self.assertEqual(oversized.status, 413)
        self.assertEqual(
            json.loads(oversized_body)["error_code"],
            "upload_request_too_large",
        )
        self.assertEqual(service.session_summary()["uploaded_file_count"], 0)

    def test_upload_event_failure_rolls_back_private_file_and_index(self) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-upload-event-failure")
        service = _service_from_state_dir(state_dir)

        def fail_upload_event(payload):
            if payload.get("event_type") == "mail_upload":
                raise OSError("simulated upload event failure")
            raise AssertionError("unexpected event")

        service._event_store.append = fail_upload_event
        with _RunningSurface(service) as surface:
            response, body = surface.request_upload(
                [
                    (
                        "rollback.eml",
                        _eml(subject="Rollback", body="RollbackUploadTerm"),
                    )
                ]
            )

        self.assertEqual(response.status, 500)
        self.assertEqual(json.loads(body)["error_code"], "request_failed")
        self.assertEqual(service.session_summary()["uploaded_file_count"], 0)
        self.assertEqual(
            list((state_dir / "mail-human-uat-uploads.private").iterdir()),
            [],
        )

    def test_upload_permission_failure_leaves_no_published_or_restart_visible_file(
        self,
    ) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-upload-permission-failure")
        service = _service_from_state_dir(state_dir)
        with mock.patch(
            "formowl_mail.human_uat_upload.os.fchmod",
            side_effect=OSError("simulated permission failure"),
        ):
            with _RunningSurface(service) as surface:
                response, body = surface.request_upload(
                    [
                        (
                            "permission-failure.eml",
                            _eml(
                                subject="Permission failure",
                                body="PermissionFailureUploadTerm",
                            ),
                        )
                    ]
                )

        self.assertEqual(response.status, 500)
        self.assertEqual(json.loads(body)["error_code"], "request_failed")
        self.assertEqual(service.session_summary()["uploaded_file_count"], 0)
        self.assertEqual(
            list((state_dir / "mail-human-uat-uploads.private").iterdir()),
            [],
        )
        restarted = _service_from_state_dir(state_dir)
        self.assertEqual(restarted.session_summary()["uploaded_file_count"], 0)

    def test_rejects_unknown_feedback_query_and_unsafe_query_without_leaks(self) -> None:
        service = _service("mail-human-uat-negative")
        with _RunningSurface(service) as surface:
            feedback_response, feedback_body = surface.request_json(
                "/api/feedback",
                {
                    "query_id": "uatquery_" + "1" * 24,
                    "verdict": "correct",
                    "note": "",
                },
            )
            query_response, query_body = surface.request_json(
                "/api/query",
                {
                    "query_text": "select * from private_mail",
                },
            )

        self.assertEqual(feedback_response.status, 400)
        self.assertEqual(query_response.status, 400)
        rendered = feedback_body.decode("utf-8") + query_body.decode("utf-8")
        self.assertNotIn("private_mail", rendered)
        self.assertNotIn(str(_paths.TEST_TMP_ROOT), rendered)

    def test_private_event_failure_does_not_advance_session_counts(self) -> None:
        service = _service("mail-human-uat-event-failure")

        def fail_event_write(_payload):
            raise OSError("simulated private event write failure")

        service._event_store.append = fail_event_write
        with self.assertRaises(OSError):
            service.query(
                {
                    "query_text": "pull-in",
                    "sort": "relevance",
                    "limit": 5,
                }
            )

        summary = service.session_summary()
        self.assertEqual(summary["query_count"], 0)
        self.assertEqual(summary["feedback_count"], 0)

    def test_feedback_event_failure_does_not_advance_feedback_counts(self) -> None:
        service = _service("mail-human-uat-feedback-event-failure")
        query = service.query(
            {
                "query_text": "pull-in",
                "sort": "relevance",
                "limit": 5,
            }
        )

        def fail_event_write(_payload):
            raise OSError("simulated private feedback write failure")

        service._event_store.append = fail_event_write
        with self.assertRaises(OSError):
            service.record_feedback(
                {
                    "query_id": query["query_id"],
                    "verdict": "incorrect",
                    "note": "",
                }
            )

        summary = service.session_summary()
        self.assertEqual(summary["query_count"], 1)
        self.assertEqual(summary["feedback_count"], 0)
        self.assertEqual(summary["verdict_counts"]["incorrect"], 0)

    def test_state_store_rejects_symlink(self) -> None:
        root = _paths.fresh_test_dir("mail-human-uat-symlink")
        target = root / "target"
        target.mkdir()
        link = root / "state-link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ContractValidationError):
            MailHumanUatService(
                MailHumanUatHttpConfig(
                    bundle=_bundle(),
                    access_code=ACCESS_CODE,
                    state_dir=link,
                    fixed_now=NOW,
                )
            )


def _service(name: str) -> MailHumanUatService:
    return _service_from_state_dir(_paths.fresh_test_dir(name))


def _service_from_state_dir(state_dir: Path) -> MailHumanUatService:
    return MailHumanUatService(
        MailHumanUatHttpConfig(
            bundle=_bundle(),
            access_code=ACCESS_CODE,
            state_dir=state_dir,
            fixed_now=NOW,
        )
    )


def _bundle() -> MailEvidenceBundle:
    import_session = MailImportSession(
        mail_import_session_id="mailimport_may_uat",
        workspace_id="workspace_formowl",
        owner_user_id="user_may",
        source_asset_id="asset_may_mail",
        archive_sha256="sha256:" + "1" * 64,
        retention_policy="retain_7_days",
        raw_archive_retention_decision="retained_by_policy",
        created_at=NOW,
        upload_session_id="upload_may_uat",
    )
    messages = [
        EmailMessage(
            email_message_id="emailmessage_schedule",
            message_fingerprint="sha256:" + "2" * 64,
            message_id="message_schedule",
            archive_id="archive_may",
            mailbox_id="mailbox_may",
            source_observation_ids=["obs_schedule"],
            subject="文顥 RB5 SOM SMT 打件排程",
            sender="planner@example.com",
            sent_at="2026-06-15T08:00:00+00:00",
        ),
        EmailMessage(
            email_message_id="emailmessage_pullin",
            message_fingerprint="sha256:" + "3" * 64,
            message_id="message_pullin",
            archive_id="archive_may",
            mailbox_id="mailbox_may",
            source_observation_ids=["obs_pullin"],
            subject="Supplier pull-in request",
            sender="buyer@example.com",
            sent_at="2026-06-14T08:00:00+00:00",
        ),
        EmailMessage(
            email_message_id="emailmessage_unrelated",
            message_fingerprint="sha256:" + "7" * 64,
            message_id="message_unrelated",
            archive_id="archive_may",
            mailbox_id="mailbox_may",
            source_observation_ids=["obs_unrelated"],
            subject="General production update",
            sender="planner@example.com",
            sent_at="2026-06-20T08:00:00+00:00",
        ),
    ]
    body_segments = [
        EmailBodySegment(
            email_body_segment_id="body_schedule",
            email_message_id="emailmessage_schedule",
            message_occurrence_id="occ_schedule",
            source_observation_id="obs_schedule",
            text=(
                "文顥確認 RB5 SOM SP.Z6H02G003 520 pcs，SMT schedule is "
                "2026-06-16；這是排程通知，不代表已完成量產。"
            ),
            body_segment_hash="sha256:" + "4" * 64,
            body_segment_index=0,
        ),
        EmailBodySegment(
            email_body_segment_id="body_pullin",
            email_message_id="emailmessage_pullin",
            message_occurrence_id="occ_pullin",
            source_observation_id="obs_pullin",
            text=(
                "Please pull-in material 09.B0540GW71, PO 470002154, "
                "current delivery 2027-03-26 and requested timing 9/E."
            ),
            body_segment_hash="sha256:" + "5" * 64,
            body_segment_index=0,
        ),
        EmailBodySegment(
            email_body_segment_id="body_unrelated",
            email_message_id="emailmessage_unrelated",
            message_occurrence_id="occ_unrelated",
            source_observation_id="obs_unrelated",
            text=(
                "This unrelated supplier update quotes an old 文顥 SMT note, "
                "but it is not a 文顥 schedule subject."
            ),
            body_segment_hash="sha256:" + "8" * 64,
            body_segment_index=0,
        ),
    ]
    parse_run = MailParseRun(
        mail_parse_run_id="mailparserun_may_uat",
        mail_import_session_id=import_session.mail_import_session_id,
        extractor_run_id="extractorrun_may_uat",
        parser_name="fixture",
        parser_version="0.1",
        input_hash=import_session.archive_sha256,
        config_hash="sha256:" + "6" * 64,
        status="succeeded",
        started_at=NOW,
        completed_at=NOW,
    )
    return MailEvidenceBundle(
        mail_evidence_bundle_id="mailevidencebundle_may_uat",
        producer_type="fixture_parser",
        mail_import_session=import_session,
        archive_occurrences=[],
        folder_occurrences=[],
        messages=messages,
        message_occurrences=[],
        body_segments=body_segments,
        attachments=[],
        attachment_occurrences=[],
        quoted_message_candidates=[],
        embedded_message_relations=[],
        mail_parse_run=parse_run,
        parse_warnings=[],
        created_at=NOW,
    )


def _auth_headers() -> dict[str, str]:
    return {"X-FormOwl-UAT-Code": ACCESS_CODE}


def _eml(*, subject: str, body: str) -> bytes:
    return (
        "From: may@example.com\r\n"
        "To: buyer@example.com\r\n"
        f"Subject: {subject}\r\n"
        "Date: Sat, 18 Jul 2026 12:30:00 +0800\r\n"
        "Message-ID: <may-uat-message@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        "Content-Transfer-Encoding: 8bit\r\n"
        "\r\n"
        f"{body}\r\n"
    ).encode("utf-8")


def _eml_with_inline_text_attachment(*, body: str, attachment_body: str) -> bytes:
    return (
        "From: may@example.com\r\n"
        "To: buyer@example.com\r\n"
        "Subject: Inline attachment boundary\r\n"
        "Date: Sat, 18 Jul 2026 12:30:00 +0800\r\n"
        "Message-ID: <may-uat-inline-attachment@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="formowl-uat-boundary"\r\n'
        "\r\n"
        "--formowl-uat-boundary\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        "\r\n"
        f"{body}\r\n"
        "--formowl-uat-boundary\r\n"
        'Content-Type: text/plain; charset="utf-8"; name="secret.txt"\r\n'
        'Content-Disposition: inline; filename="secret.txt"\r\n'
        "\r\n"
        f"{attachment_body}\r\n"
        "--formowl-uat-boundary--\r\n"
    ).encode("utf-8")


def _eml_with_attached_message(*, body: str, attached_body: str) -> bytes:
    return (
        "From: may@example.com\r\n"
        "To: buyer@example.com\r\n"
        "Subject: Attached EML boundary\r\n"
        "Date: Sat, 18 Jul 2026 12:30:00 +0800\r\n"
        "Message-ID: <may-uat-attached-eml@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="formowl-uat-outer"\r\n'
        "\r\n"
        "--formowl-uat-outer\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        "\r\n"
        f"{body}\r\n"
        "--formowl-uat-outer\r\n"
        "Content-Type: message/rfc822\r\n"
        'Content-Disposition: attachment; filename="attached.eml"\r\n'
        "\r\n"
        "From: supplier@example.com\r\n"
        "To: may@example.com\r\n"
        "Subject: Nested private message\r\n"
        "Date: Sat, 18 Jul 2026 10:00:00 +0800\r\n"
        "Message-ID: <nested-private@example.com>\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        "\r\n"
        f"{attached_body}\r\n"
        "--formowl-uat-outer--\r\n"
    ).encode("utf-8")


class _RunningSurface:
    def __init__(self, service: MailHumanUatService) -> None:
        self.server = create_mail_human_uat_http_server("127.0.0.1", 0, service)
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

    def request_json(self, path: str, payload: dict[str, object]):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self.request(
            "POST",
            path,
            body=body,
            headers={
                **_auth_headers(),
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )

    def request_upload(
        self,
        files: list[tuple[str, bytes]],
        *,
        authenticated: bool = True,
    ):
        boundary = "----formowl-may-uat-test-boundary"
        body = bytearray()
        for filename, content in files:
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            body.extend(
                (
                    'Content-Disposition: form-data; name="mail_files"; '
                    f'filename="{filename}"\r\n'
                    "Content-Type: application/octet-stream\r\n"
                    "\r\n"
                ).encode("utf-8")
            )
            body.extend(content)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("ascii"))
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        }
        if authenticated:
            headers.update(_auth_headers())
        return self.request(
            "POST",
            "/api/upload",
            body=bytes(body),
            headers=headers,
        )


if __name__ == "__main__":
    unittest.main()
