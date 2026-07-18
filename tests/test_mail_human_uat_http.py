from __future__ import annotations

import http.client
import json
from pathlib import Path
import threading
import unittest

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
        self.assertIn("不需再次上傳信件", html)
        self.assertNotIn("user_may", html)
        self.assertNotIn("workspace_formowl", html)
        self.assertNotIn("/tmp/", html)
        self.assertTrue(health["chatgpt_bypassed"])
        self.assertFalse(health["upload_required"])
        self.assertTrue(health["read_only"])
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


if __name__ == "__main__":
    unittest.main()
