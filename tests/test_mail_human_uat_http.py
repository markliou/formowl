from __future__ import annotations

from dataclasses import replace
import http.client
import json
from pathlib import Path
import threading
import unittest
import unicodedata
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_ingestion.extractors.mail.pst import (
    PstMailArchiveExtractor,
    _ParserCommandResult,
)
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
from formowl_mail.human_uat_orchestrator import (
    UatConversationMessage,
    UatConversationOutcome,
    UatEvidenceToolRequest,
)
from formowl_mail.human_uat_upload import UatUploadedResourcePart
from formowl_mail.query import MailEvidenceQueryGateway

NOW = "2026-07-18T12:00:00+00:00"
VISITOR_ID = "uatvisitor_" + "1" * 32
SESSION_ID = "uatsession_" + "2" * 32


def _conversation_id(visitor_id: str, session_id: str) -> str:
    digest = sha256_json(
        {
            "visitor_id": visitor_id,
            "session_id": session_id,
        }
    ).removeprefix("sha256:")
    return f"formowl_uat_{digest[:48]}"


class _ScriptedConversationModel:
    model_name = "test-orchestrator"

    def __init__(self, steps: list[dict[str, object]]) -> None:
        self.steps = list(steps)
        self.calls: list[dict[str, object]] = []
        self.tool_call_count = 0
        self.discarded_identifiers: list[str] = []

    def respond(
        self,
        *,
        history,
        user_text,
        latest_evidence,
        safety_identifier,
        evidence_tool,
    ) -> UatConversationOutcome:
        self.calls.append(
            {
                "history": tuple(history),
                "user_text": user_text,
                "latest_evidence": latest_evidence,
                "safety_identifier": safety_identifier,
            }
        )
        step = self.steps.pop(0)
        tool_request = step.get("tool_request")
        tool_result = None
        if isinstance(tool_request, UatEvidenceToolRequest):
            self.tool_call_count += 1
            tool_result = evidence_tool(tool_request)
        return UatConversationOutcome(
            response_kind=str(step["response_kind"]),
            answer_text=str(step["answer_text"]),
            display_format=str(step.get("display_format", "narrative")),
            model_name=self.model_name,
            tool_request=tool_request,
            tool_result=tool_result,
            fallback_reason=step.get("fallback_reason"),
        )

    def discard_conversation(self, safety_identifier: str) -> None:
        self.discarded_identifiers.append(safety_identifier)


class MailHumanUatHttpTests(unittest.TestCase):
    def test_page_is_shared_chat_ui_without_login_gate(self) -> None:
        service = _service("mail-human-uat-page")
        with _RunningSurface(service) as surface:
            page_response, page_body = surface.request("GET", "/")
            health_response, health_body = surface.request("GET", "/api/health")

        html = page_body.decode("utf-8")
        health = json.loads(health_body)
        self.assertEqual(page_response.status, 200)
        self.assertEqual(health_response.status, 200)
        self.assertIn("有什麼可以幫忙的？", html)
        self.assertIn('id="sidebar-toggle"', html)
        self.assertIn('id="current-chat-title"', html)
        self.assertIn('id="search-conversations"', html)
        self.assertIn('id="model-selector"', html)
        self.assertIn('id="tools-control"', html)
        self.assertIn('id="shell-toast"', html)
        self.assertIn('class="conversation"', html)
        self.assertIn('id="chat-input"', html)
        self.assertIn('id="upload-frame"', html)
        self.assertIn('src="/upload"', html)
        self.assertIn("測試期間會記錄已送出的問題與按鈕操作", html)
        self.assertIn('"/api/interaction"', html)
        self.assertIn('"/api/chat"', html)
        self.assertIn('"formowl_uat_visitor_id"', html)
        self.assertIn("!event.isComposing", html)
        self.assertIn("正在思考", html)
        self.assertNotIn("sort: querySort(query)", html)
        self.assertNotIn("limit: 50", html)
        self.assertNotIn('api("/api/query"', html)
        self.assertIn('className = "evidence-table"', html)
        self.assertIn('["順序", "內容", "主旨", "時間"]', html)
        self.assertIn('cell.setAttribute("scope", "col")', html)
        self.assertIn('order.setAttribute("data-label", "順序")', html)
        self.assertIn('content.setAttribute("data-label", "內容")', html)
        self.assertIn('subject.setAttribute("data-label", "主旨")', html)
        self.assertIn('time.setAttribute("data-label", "時間")', html)
        self.assertIn("formatEvidenceTime", html)
        self.assertIn('timeZone: "Asia/Taipei"', html)
        self.assertIn("時間未提供", html)
        self.assertIn("時間格式無法判讀", html)
        self.assertIn("supporting-list", html)
        self.assertIn("overflow-wrap: anywhere; word-break: break-word;", html)
        self.assertNotIn("min-width: 720px", html)
        self.assertNotIn('id="starter-grid"', html)
        self.assertNotIn('class="starter-card', html)
        self.assertNotIn("最近一次文顥的量產時間", html)
        self.assertNotIn("有哪些料件需要 pull-in", html)
        self.assertNotIn("PO 470002154", html)
        self.assertNotIn('id="gate"', html)
        self.assertNotIn("輸入測試存取碼", html)
        self.assertNotIn("X-FormOwl-UAT-Code", html)
        self.assertNotIn("May、Maggie 與相關同事", html)
        self.assertNotIn("user_may", html)
        self.assertNotIn("workspace_formowl", html)
        self.assertNotIn("/tmp/", html)
        self.assertNotIn("citation_id", html)
        self.assertNotIn("source_observation_id", html)
        self.assertNotIn("backend_path", html)
        self.assertNotIn("private_metadata", html)
        self.assertTrue(health["chatgpt_bypassed"])
        self.assertFalse(health["authentication_required"])
        self.assertTrue(health["shared_uat"])
        self.assertTrue(health["behavior_capture_enabled"])
        self.assertFalse(health["conversation_orchestrator_enabled"])
        self.assertIsNone(health["conversation_model"])
        self.assertEqual(
            health["behavior_capture_scope"],
            "submitted_questions_and_bounded_interactions",
        )
        self.assertEqual(health["behavior_capture_retention_days"], 30)
        self.assertFalse(health["upload_required"])
        self.assertTrue(health["upload_supported"])
        self.assertTrue(health["read_only_business_systems"])
        self.assertEqual(health["uploaded_file_count"], 0)
        self.assertEqual(health["index_build_mode"], "single_process")
        self.assertEqual(health["index_worker_count"], 1)
        self.assertGreaterEqual(health["index_build_elapsed_ms"], 0.0)
        self.assertEqual(page_response.getheader("Cache-Control"), "no-store, max-age=0")
        self.assertEqual(page_response.getheader("X-Frame-Options"), "DENY")

    def test_page_result_projection_has_responsive_readability_contract(self) -> None:
        service = _service("mail-human-uat-responsive-contract")
        with _RunningSurface(service) as surface:
            response, body = surface.request("GET", "/")

        html = body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("width: min(1120px, calc(100% - 48px));", html)
        self.assertIn("table-layout: fixed;", html)
        self.assertIn(".evidence-table td::before", html)
        self.assertIn("content: attr(data-label)", html)
        self.assertIn("@media (max-width: 720px)", html)
        self.assertIn(".evidence-table tbody { display: grid; gap: 12px; }", html)
        self.assertIn("display: block; border: 1px solid var(--line)", html)
        self.assertIn("clip: rect(0, 0, 0, 0)", html)
        self.assertIn("overflow: visible", html)
        self.assertNotIn("overflow-x: auto", html)
        mobile_css = html.split("@media (max-width: 800px)", 1)[1].split(
            "@media (max-width: 720px)",
            1,
        )[0]
        self.assertIn(
            "padding-bottom: calc(240px + env(safe-area-inset-bottom));",
            mobile_css,
        )
        self.assertIn(
            "padding: 10px 10px calc(8px + env(safe-area-inset-bottom));",
            mobile_css,
        )
        self.assertIn(
            "body.has-conversation .composer-note { display: none; }",
            mobile_css,
        )
        self.assertIn(
            '<div class="composer-note">測試期間會記錄已送出的問題與按鈕操作',
            html,
        )

    def test_service_uses_injected_gateway_metrics_and_rejects_bundle_mismatch(
        self,
    ) -> None:
        bundle = _bundle()
        gateway = MailEvidenceQueryGateway([bundle])
        service = MailHumanUatService(
            MailHumanUatHttpConfig(
                bundle=bundle,
                state_dir=_paths.fresh_test_dir("mail-human-uat-injected-gateway"),
                fixed_now=NOW,
            ),
            base_gateway=gateway,
        )

        health = service.health()

        self.assertIs(service._base_gateway, gateway)
        self.assertEqual(health["index_build_mode"], gateway.index_build_mode)
        self.assertEqual(health["index_worker_count"], gateway.index_worker_count)
        self.assertEqual(
            health["index_build_elapsed_ms"],
            gateway.index_build_elapsed_ms,
        )

        mismatched_bundle = replace(
            bundle,
            mail_evidence_bundle_id="mailbundle_other_uat",
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "UAT base gateway does not match its bundle",
        ):
            MailHumanUatService(
                MailHumanUatHttpConfig(
                    bundle=mismatched_bundle,
                    state_dir=_paths.fresh_test_dir("mail-human-uat-injected-gateway-mismatch"),
                    fixed_now=NOW,
                ),
                base_gateway=gateway,
            )

    def test_upload_page_is_same_origin_iframe_surface(self) -> None:
        service = _service("mail-human-uat-upload-iframe")
        with _RunningSurface(service) as surface:
            response, body = surface.request("GET", "/upload")

        html = body.decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn('id="mail-files"', html)
        self.assertIn("formowl-upload-complete", html)
        self.assertIn("window.parent.postMessage", html)
        self.assertIn("目前可處理 EML、PST、PDF、TXT", html)
        self.assertIn("PST 單檔最多 500 MB", html)
        self.assertIn("其他格式單檔最多 25 MB", html)
        self.assertIn("合計最多 500 MB", html)
        self.assertIn('accept=".eml,.pst,.pdf,.txt', html)
        self.assertIn("file.size > limit", html)
        self.assertIn("> maxTotalBytes", html)
        self.assertNotIn("目前只支援 EML", html)
        self.assertNotIn("選擇 EML", html)
        self.assertEqual(response.getheader("X-Frame-Options"), "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", response.getheader("Content-Security-Policy"))

    def test_summary_query_and_upload_do_not_require_authentication(self) -> None:
        service = _service("mail-human-uat-no-auth")
        with _RunningSurface(service) as surface:
            summary_response, summary_body = surface.request("GET", "/api/session-summary")
            query_response, query_body = surface.request_json(
                "/api/query",
                {"query_text": "pull-in", "limit": 5},
            )
            upload_response, upload_body = surface.request_upload(
                [("shared.eml", _eml(subject="Shared UAT", body="SharedUploadTerm"))]
            )

        self.assertEqual(summary_response.status, 200)
        self.assertEqual(json.loads(summary_body)["query_count"], 0)
        self.assertEqual(query_response.status, 200)
        self.assertEqual(json.loads(query_body)["status"], "ok")
        self.assertEqual(upload_response.status, 201)
        self.assertEqual(json.loads(upload_body)["accepted_file_count"], 1)

    def test_chat_orchestrator_calls_formowl_only_for_new_evidence(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "你好，我可以先了解你想處理的資料問題。",
                },
                {
                    "response_kind": "answer",
                    "answer_text": "PO470002002 的來源內容顯示目前交期資訊如下。",
                    "tool_request": UatEvidenceToolRequest(
                        query_text="SMT delivery PO470002002",
                        required_terms=("PO470002002",),
                        sort="relevance",
                        limit=50,
                    ),
                },
                {
                    "response_kind": "answer",
                    "answer_text": "簡單說，前一筆證據是在描述該採購單的交期。",
                },
                {
                    "response_kind": "render_prior_evidence",
                    "answer_text": "我把同一批證據整理成表格。",
                    "display_format": "table",
                },
                {
                    "response_kind": "answer",
                    "answer_text": "這是另一個一般問題，不沿用前一個搜尋任務。",
                },
            ]
        )
        state_dir = _paths.fresh_test_dir("mail-human-uat-chat-orchestrator")
        service = _service_with_model(state_dir, model)
        tracking = {
            "visitor_id": VISITOR_ID,
            "session_id": SESSION_ID,
            "source": "composer",
        }

        greeting = service.chat(
            {
                "query_text": "你好，你可以做什麼？",
                "sequence": 1,
                **tracking,
            }
        )
        evidence = service.chat(
            {
                "query_text": "查 PO470002002 的交期",
                "sequence": 2,
                **tracking,
            }
        )
        explanation = service.chat(
            {
                "query_text": "上面的東西我看不懂",
                "sequence": 3,
                **tracking,
            }
        )
        table = service.chat(
            {
                "query_text": "整理成表格",
                "sequence": 4,
                **tracking,
            }
        )
        unrelated = service.chat(
            {
                "query_text": "你可以幫我寫一段會議開場白嗎？",
                "sequence": 5,
                **tracking,
            }
        )

        self.assertEqual(
            greeting["orchestration"]["action"],
            "answer_without_tool",
        )
        self.assertEqual(greeting["results"], [])
        self.assertEqual(
            evidence["orchestration"]["action"],
            "call_formowl_tool",
        )
        self.assertEqual(evidence["total_result_count"], 1)
        self.assertEqual(evidence["results"][0]["subject"], "Supplier pull-in request")
        self.assertEqual(
            explanation["orchestration"]["action"],
            "answer_without_tool",
        )
        self.assertEqual(explanation["results"], [])
        self.assertEqual(
            table["orchestration"]["action"],
            "render_prior_evidence",
        )
        self.assertEqual(table["results"], evidence["results"])
        self.assertEqual(table["projection"]["output_format"], "table")
        self.assertEqual(
            unrelated["orchestration"]["action"],
            "answer_without_tool",
        )
        self.assertEqual(unrelated["results"], [])
        self.assertEqual(model.tool_call_count, 1)
        self.assertIsNone(model.calls[0]["latest_evidence"])
        self.assertIsNotNone(model.calls[2]["latest_evidence"])
        self.assertEqual(
            model.calls[2]["history"][-1],
            UatConversationMessage(
                role="assistant",
                content="PO470002002 的來源內容顯示目前交期資訊如下。",
            ),
        )
        self.assertRegex(
            str(model.calls[0]["safety_identifier"]),
            r"^formowl_uat_[0-9a-f]{48}$",
        )
        summary = service.session_summary()
        self.assertEqual(summary["chat_count"], 5)
        self.assertEqual(summary["query_count"], 1)
        self.assertEqual(summary["formowl_tool_call_count"], 1)

        events = [
            json.loads(line)
            for line in (state_dir / "mail-human-uat-events.private.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        chat_results = [event for event in events if event["event_type"] == "chat_result"]
        self.assertEqual(
            [event["orchestration_action"] for event in chat_results],
            [
                "answer_without_tool",
                "call_formowl_tool",
                "answer_without_tool",
                "render_prior_evidence",
                "answer_without_tool",
            ],
        )
        self.assertEqual(chat_results[1]["tool_name"], "search_formowl_evidence")
        self.assertEqual(len(chat_results[1]["required_term_hashes"]), 1)
        self.assertNotIn(
            "PO470002002",
            json.dumps(chat_results[1]["required_term_hashes"]),
        )

    def test_chat_matches_typed_identifier_to_numeric_source_and_etd(self) -> None:
        bundle = _bundle()
        bundle = replace(
            bundle,
            body_segments=[
                replace(
                    segment,
                    text=(
                        "Purchase order 470002002 | Item 1 | " "Part 20.QCS64G901 | ETD 2026-07-13"
                    ),
                )
                if segment.email_message_id == "emailmessage_pullin"
                else segment
                for segment in bundle.body_segments
            ],
        )
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "找到該採購單的交期來源。",
                    "tool_request": UatEvidenceToolRequest(
                        query_text="PO470002002 交期",
                        required_terms=("PO470002002",),
                        sort="relevance",
                        limit=20,
                    ),
                },
            ]
        )
        service = MailHumanUatService(
            MailHumanUatHttpConfig(
                bundle=bundle,
                state_dir=_paths.fresh_test_dir("mail-human-uat-typed-numeric-identifier"),
                conversation_model=model,
                fixed_now=NOW,
            )
        )

        result = service.chat(
            {
                "query_text": "我要 PO470002002 的交期",
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "source": "composer",
            }
        )

        self.assertEqual(result["orchestration"]["action"], "call_formowl_tool")
        self.assertEqual(result["total_result_count"], 1)
        self.assertEqual(result["results"][0]["subject"], "Supplier pull-in request")
        self.assertIn("470002002", result["results"][0]["snippet"])
        self.assertIn("ETD 2026-07-13", result["results"][0]["snippet"])
        self.assertNotIn("business_filter_no_exact_match", result["warnings"])
        self.assertNotIn("required_terms_no_exact_match", result["warnings"])
        self.assertGreaterEqual(result["timings_ms"]["posting_retrieval"], 0.0)
        self.assertGreaterEqual(result["timings_ms"]["exact_verification"], 0.0)
        self.assertGreaterEqual(result["timings_ms"]["ranking"], 0.0)
        self.assertGreaterEqual(result["timings_ms"]["formowl_orchestration"], 0.0)
        self.assertGreaterEqual(result["timings_ms"]["chat_orchestration"], 0.0)

    def test_chat_preserves_evidence_when_codex_uses_answer_fallback(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": ("已找到 1 筆符合條件的來源，以下依相關性列出內容。"),
                    "display_format": "table",
                    "fallback_reason": ("codex_answer_generation_failed_after_evidence"),
                    "tool_request": UatEvidenceToolRequest(
                        query_text="PO470002002 delivery",
                        required_terms=("PO470002002",),
                        sort="relevance",
                        limit=10,
                    ),
                }
            ]
        )
        state_dir = _paths.fresh_test_dir("mail-human-uat-answer-fallback")
        service = _service_with_model(state_dir, model)

        result = service.chat(
            {
                "query_text": "查 PO470002002 的交期",
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "source": "composer",
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["result_count"], 0)
        self.assertEqual(result["projection"]["output_format"], "narrative")
        self.assertTrue(result["orchestration"]["answer_fallback_used"])
        self.assertIn("codex_answer_fallback_used", result["warnings"])
        events = [
            json.loads(line)
            for line in (state_dir / "mail-human-uat-events.private.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        chat_result = next(event for event in events if event["event_type"] == "chat_result")
        self.assertTrue(chat_result["answer_fallback_used"])
        self.assertEqual(
            chat_result["fallback_reason"],
            "codex_answer_generation_failed_after_evidence",
        )

    def test_chat_required_terms_preserve_all_matching_oracle_and_citations(
        self,
    ) -> None:
        bundle = _bulk_bundle(12)
        matching_count = 7
        bundle = replace(
            bundle,
            body_segments=[
                replace(
                    segment,
                    text=(
                        f"{segment.text} Alex Rivera approved DOC-2026-ABC9."
                        if index < matching_count
                        else f"{segment.text} Avery Stone approved DOC-2026-XYZ8."
                    ),
                )
                for index, segment in enumerate(bundle.body_segments)
            ],
        )
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "找到所有同時符合人名與文件識別碼的來源。",
                    "tool_request": UatEvidenceToolRequest(
                        query_text="BULK_MATCH_TERM Alex Rivera DOC-2026-ABC9",
                        required_terms=("Alex Rivera", "DOC-2026-ABC9"),
                        sort="relevance",
                        limit=3,
                    ),
                },
            ]
        )
        service = MailHumanUatService(
            MailHumanUatHttpConfig(
                bundle=bundle,
                state_dir=_paths.fresh_test_dir("mail-human-uat-required-all-matching"),
                conversation_model=model,
                fixed_now=NOW,
            )
        )

        result = service.chat(
            {
                "query_text": "列出 Alex Rivera 核准 DOC-2026-ABC9 的所有來源",
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "source": "composer",
            }
        )

        expected_observation_ids = _exhaustive_uat_source_ids(
            bundle,
            ("Alex Rivera", "DOC-2026-ABC9"),
        )
        displayed_observation_ids = {
            item["citation"]["source_observation_id"] for item in result["results"]
        }
        self.assertEqual(result["orchestration"]["action"], "call_formowl_tool")
        self.assertEqual(result["total_result_count"], matching_count)
        self.assertEqual(result["result_count"], 3)
        self.assertEqual(len(result["results"]), 3)
        self.assertEqual(
            result["coverage"]["cardinality_mode"],
            "all_matching",
        )
        self.assertEqual(
            result["coverage"]["total_source_item_count"],
            matching_count,
        )
        self.assertEqual(
            result["coverage"]["returned_source_item_count"],
            matching_count,
        )
        self.assertEqual(
            result["coverage"]["displayed_source_item_count"],
            3,
        )
        self.assertTrue(result["coverage"]["is_exhaustive"])
        self.assertFalse(result["coverage"]["has_more"])
        self.assertEqual(len(expected_observation_ids), matching_count)
        self.assertTrue(displayed_observation_ids.issubset(expected_observation_ids))
        self.assertEqual(len(displayed_observation_ids), 3)
        self.assertTrue(result["projection"]["has_more"])
        self.assertEqual(
            len({item["citation"]["citation_id"] for item in result["results"]}),
            3,
        )
        self.assertEqual(
            set(result["timings_ms"]),
            {
                "posting_retrieval",
                "exact_verification",
                "ranking",
                "formowl_orchestration",
                "chat_orchestration",
            },
        )
        self.assertTrue(all(value >= 0.0 for value in result["timings_ms"].values()))
        self.assertTrue(all("DOC-2026-ABC9" in item["snippet"] for item in result["results"]))

    def test_chat_required_terms_include_minimal_supporting_evidence(self) -> None:
        base = _bundle()
        source_observation_ids = [
            "obs_required_query",
            "obs_required_person",
            "obs_required_document",
            "obs_required_unrelated",
        ]
        message = replace(
            base.messages[0],
            email_message_id="emailmessage_required_support",
            message_fingerprint="sha256:" + "a" * 64,
            message_id="message_required_support",
            source_observation_ids=source_observation_ids,
            subject="Program evidence review",
            sent_at="2026-07-22T08:00:00+00:00",
        )
        segments = [
            EmailBodySegment(
                email_body_segment_id=f"body_required_{index}",
                email_message_id=message.email_message_id,
                message_occurrence_id="occ_required_support",
                source_observation_id=source_observation_id,
                text=text,
                body_segment_hash="sha256:" + f"{index + 20:064x}",
                body_segment_index=index,
            )
            for index, (source_observation_id, text) in enumerate(
                zip(
                    source_observation_ids,
                    (
                        "Program ORBIT is ready for the evidence review.",
                        "Alex Rivera is the accountable reviewer.",
                        "The approved record is DOC-2026-ABC9.",
                        "UNRELATED-SEGMENT must not be materialized.",
                    ),
                    strict=True,
                )
            )
        ]
        bundle = replace(
            base,
            mail_evidence_bundle_id="mailevidencebundle_required_support",
            messages=[message],
            body_segments=segments,
        )
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "找到完整的必要詞支持證據。",
                    "tool_request": UatEvidenceToolRequest(
                        query_text="ORBIT",
                        required_terms=("Alex Rivera", "DOC-2026-ABC9"),
                        sort="relevance",
                        limit=10,
                    ),
                },
            ]
        )
        service = MailHumanUatService(
            MailHumanUatHttpConfig(
                bundle=bundle,
                state_dir=_paths.fresh_test_dir("mail-human-uat-required-support"),
                conversation_model=model,
                fixed_now=NOW,
            )
        )

        result = service.chat(
            {
                "query_text": "列出所有 ORBIT 且由 Alex Rivera 核准 DOC-2026-ABC9 的來源",
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "source": "composer",
            }
        )

        self.assertEqual(result["total_result_count"], 1)
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["coverage"]["cardinality_mode"], "all_matching")
        primary = result["results"][0]
        self.assertIn("Program ORBIT", primary["snippet"])
        self.assertEqual(
            {item["citation"]["source_observation_id"] for item in primary["supporting_evidence"]},
            {"obs_required_person", "obs_required_document"},
        )
        self.assertEqual(
            {
                term.casefold()
                for item in primary["supporting_evidence"]
                for term in item["matched_required_terms"]
            },
            {"alex rivera", "doc-2026-abc9"},
        )
        self.assertEqual(
            {item["source_observation_id"] for item in primary["supporting_citations"]},
            {"obs_required_person", "obs_required_document"},
        )
        self.assertNotIn("UNRELATED-SEGMENT", str(result))

    def test_chat_required_term_no_match_is_explicit_and_exhaustive(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "沒有找到同時符合必要詞的來源。",
                    "tool_request": UatEvidenceToolRequest(
                        query_text="pull-in Alex Rivera",
                        required_terms=("Alex Rivera", "DOC-2099-MISSING"),
                        sort="relevance",
                        limit=50,
                    ),
                },
            ]
        )
        service = _service_with_model(
            _paths.fresh_test_dir("mail-human-uat-required-no-match"),
            model,
        )

        result = service.chat(
            {
                "query_text": "查找不存在的必要詞組合",
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "source": "composer",
            }
        )

        self.assertEqual(result["total_result_count"], 0)
        self.assertEqual(result["result_count"], 0)
        self.assertEqual(result["results"], [])
        self.assertEqual(result["answerability"]["status"], "target_not_found")
        self.assertEqual(result["coverage"]["total_source_item_count"], 0)
        self.assertEqual(result["coverage"]["returned_source_item_count"], 0)
        self.assertEqual(result["coverage"]["displayed_source_item_count"], 0)
        self.assertTrue(result["coverage"]["is_exhaustive"])
        self.assertFalse(result["coverage"]["has_more"])
        self.assertFalse(result["projection"]["has_more"])
        self.assertIn("required_terms_no_exact_match", result["warnings"])
        self.assertEqual(
            set(result["timings_ms"]),
            {
                "posting_retrieval",
                "exact_verification",
                "ranking",
                "formowl_orchestration",
                "chat_orchestration",
            },
        )
        self.assertTrue(all(value >= 0.0 for value in result["timings_ms"].values()))

    def test_chat_clarification_and_new_chat_do_not_reuse_prior_evidence(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "先提供來源證據。",
                    "tool_request": UatEvidenceToolRequest(
                        query_text="delivery PO470002002",
                        required_terms=("PO470002002",),
                        sort="relevance",
                        limit=20,
                    ),
                },
                {
                    "response_kind": "clarification",
                    "answer_text": "你想查哪一份資料或哪一個主題？",
                },
            ]
        )
        service = _service_with_model(
            _paths.fresh_test_dir("mail-human-uat-chat-reset"),
            model,
        )
        tracking = {
            "visitor_id": VISITOR_ID,
            "session_id": SESSION_ID,
            "source": "composer",
        }
        service.chat(
            {
                "query_text": "查 PO470002002 的交期",
                "sequence": 1,
                **tracking,
            }
        )
        service.record_interaction(
            {
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 2,
                "action": "new_chat",
                "details": {},
            }
        )
        clarification = service.chat(
            {
                "query_text": "幫我看一下",
                "sequence": 3,
                **tracking,
            }
        )

        self.assertEqual(clarification["orchestration"]["action"], "clarify")
        self.assertFalse(clarification["orchestration"]["formowl_tool_called"])
        self.assertEqual(model.calls[1]["history"], ())
        self.assertIsNone(model.calls[1]["latest_evidence"])
        self.assertEqual(model.tool_call_count, 1)
        self.assertEqual(service.session_summary()["query_count"], 1)

    def test_chat_http_route_is_same_origin_and_feedback_compatible(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "這一題不需要調閱來源。",
                }
            ]
        )
        service = _service_with_model(
            _paths.fresh_test_dir("mail-human-uat-chat-http"),
            model,
        )
        with _RunningSurface(service) as surface:
            response, body = surface.request_json(
                "/api/chat",
                {
                    "query_text": "請解釋 FormOwl 的用途",
                    "visitor_id": VISITOR_ID,
                    "session_id": SESSION_ID,
                    "sequence": 1,
                    "source": "composer",
                },
            )
            payload = json.loads(body)
            feedback_response, _ = surface.request_json(
                "/api/feedback",
                {
                    "query_id": payload["query_id"],
                    "verdict": "correct",
                    "note": "",
                },
            )

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["assistant_text"], "這一題不需要調閱來源。")
        self.assertEqual(payload["orchestration"]["action"], "answer_without_tool")
        self.assertEqual(feedback_response.status, 200)

    def test_uat_query_serializes_authorized_body_without_generic_redaction(
        self,
    ) -> None:
        bundle = _bundle()
        ordinary_text = (
            "PO470002002 delivery remains 2026/07/24. "
            "See https://supplier.example.com/docs/PO470002002 and "
            "/Users/may/Documents/PO plan.pdf. "
            "Status path is pull-in/ETA/COO."
        )
        ordinary_subject = "PO470002002 / COO at https://supplier.example.com/portal"
        bundle = replace(
            bundle,
            messages=[
                bundle.messages[0],
                replace(bundle.messages[1], subject=ordinary_subject),
                bundle.messages[2],
            ],
            body_segments=[
                bundle.body_segments[0],
                replace(bundle.body_segments[1], text=ordinary_text),
                bundle.body_segments[2],
            ],
        )
        service = MailHumanUatService(
            MailHumanUatHttpConfig(
                bundle=bundle,
                state_dir=_paths.fresh_test_dir("mail-human-uat-authorized-body"),
                fixed_now=NOW,
            )
        )

        payload = service.query(
            {
                "query_text": "PO470002002 delivery",
                "limit": 5,
            }
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["results"][0]["subject"], ordinary_subject)
        self.assertEqual(payload["results"][0]["snippet"], ordinary_text)
        self.assertFalse(payload["results"][0]["content_redacted"])
        self.assertNotIn("unsafe_mail_evidence_content_redacted", payload["warnings"])

    def test_uploaded_authorized_mail_preserves_body_after_restart(self) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-upload-authorized-body")
        body = (
            "UPLOADMARK delivery 2026/07/24 "
            "https://supplier.example.com/docs "
            "/Users/may/Documents/plan.pdf."
        )
        subject = "UPLOADMARK https://supplier.example.com/portal"
        service = _service_from_state_dir(state_dir)

        receipt = service.upload_mail_files(
            [
                UatUploadedResourcePart(
                    filename="ordinary.eml",
                    content=_eml(subject=subject, body=body),
                )
            ]
        )
        restarted = _service_from_state_dir(state_dir)
        payload = restarted.query(
            {
                "query_text": "UPLOADMARK delivery",
                "limit": 5,
            }
        )

        self.assertEqual(receipt["accepted_file_count"], 1)
        self.assertEqual(payload["results"][0]["subject"], subject)
        self.assertEqual(payload["results"][0]["snippet"], body)
        self.assertFalse(payload["results"][0]["content_redacted"])

    def test_uat_chat_locally_redacts_sensitive_answer_spans_only(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": (
                        "Readable answer at https://supplier.example.com/status "
                        "for /Users/may/Documents/PO plan.pdf. "
                        "api_key=super-secret; formowl://storage/private/item; "
                        "SELECT * FROM private_table. "
                        "Delivery remains 2026/07/24."
                    ),
                }
            ]
        )
        service = _service_with_model(
            _paths.fresh_test_dir("mail-human-uat-chat-local-redaction"),
            model,
        )

        payload = service.chat(
            {
                "query_text": "請整理目前狀況",
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "source": "composer",
            }
        )

        self.assertIn(
            "Readable answer at https://supplier.example.com/status",
            payload["assistant_text"],
        )
        self.assertIn("/Users/may/Documents/PO plan.pdf", payload["assistant_text"])
        self.assertIn("Delivery remains 2026/07/24.", payload["assistant_text"])
        self.assertIn("[redacted_credential]", payload["assistant_text"])
        self.assertIn("[redacted_internal_locator]", payload["assistant_text"])
        self.assertIn("[redacted_sql]", payload["assistant_text"])
        self.assertNotIn("super-secret", payload["assistant_text"])
        self.assertNotIn("formowl://storage", payload["assistant_text"])
        self.assertNotIn("SELECT * FROM", payload["assistant_text"])
        self.assertIn("unsafe_mail_evidence_content_redacted", payload["warnings"])

    def test_chat_requires_tracking_to_isolate_persistent_codex_threads(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "不應執行。",
                }
            ]
        )
        service = _service_with_model(
            _paths.fresh_test_dir("mail-human-uat-chat-tracking-required"),
            model,
        )

        with self.assertRaisesRegex(
            ContractValidationError,
            "anonymous UAT tracking ids are invalid",
        ):
            service.chat(
                {
                    "query_text": "沒有 session 的請求",
                    "source": "api",
                }
            )

        self.assertEqual(model.calls, [])

    def test_chat_discards_model_thread_when_response_validation_fails(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "render_prior_evidence",
                    "answer_text": "不應保留這個遠端 turn。",
                }
            ]
        )
        service = _service_with_model(
            _paths.fresh_test_dir("mail-human-uat-chat-discard-invalid-response"),
            model,
        )

        with self.assertRaisesRegex(RuntimeError, "missing prior evidence"):
            service.chat(
                {
                    "query_text": "重新顯示上一筆",
                    "visitor_id": VISITOR_ID,
                    "session_id": SESSION_ID,
                    "sequence": 1,
                    "source": "composer",
                }
            )

        conversation_id = _conversation_id(VISITOR_ID, SESSION_ID)
        self.assertEqual(model.discarded_identifiers, [conversation_id])
        self.assertNotIn(
            conversation_id,
            service._conversation_states_by_conversation_id,
        )

    def test_chat_discards_model_thread_when_result_persistence_fails(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "這個 turn 不得成為隱藏歷史。",
                }
            ]
        )
        service = _service_with_model(
            _paths.fresh_test_dir("mail-human-uat-chat-discard-persistence-failure"),
            model,
        )
        original_append = service._event_store.append

        def append_with_failure(event):
            if event.get("event_type") == "chat_result":
                raise OSError("simulated durable event failure")
            return original_append(event)

        with mock.patch.object(
            service._event_store,
            "append",
            side_effect=append_with_failure,
        ):
            with self.assertRaisesRegex(OSError, "durable event failure"):
                service.chat(
                    {
                        "query_text": "一般問題",
                        "visitor_id": VISITOR_ID,
                        "session_id": SESSION_ID,
                        "sequence": 1,
                        "source": "composer",
                    }
                )

        conversation_id = _conversation_id(VISITOR_ID, SESSION_ID)
        self.assertEqual(model.discarded_identifiers, [conversation_id])
        self.assertNotIn(
            conversation_id,
            service._conversation_states_by_conversation_id,
        )

    def test_chat_keeps_history_and_evidence_isolated_between_sessions(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "第一個 session 的證據。",
                    "tool_request": UatEvidenceToolRequest(
                        query_text="PO470002002 delivery",
                        required_terms=("PO470002002",),
                        sort="relevance",
                        limit=20,
                    ),
                },
                {
                    "response_kind": "answer",
                    "answer_text": "第二個 session 的一般回答。",
                },
                {
                    "response_kind": "answer",
                    "answer_text": "延續第一個 session。",
                },
                {
                    "response_kind": "answer",
                    "answer_text": "延續第二個 session。",
                },
            ]
        )
        service = _service_with_model(
            _paths.fresh_test_dir("mail-human-uat-chat-session-isolation"),
            model,
        )
        second_session_id = "uatsession_" + "3" * 32

        service.chat(
            {
                "query_text": "查 PO470002002 的交期",
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "source": "composer",
            }
        )
        service.chat(
            {
                "query_text": "你好",
                "visitor_id": VISITOR_ID,
                "session_id": second_session_id,
                "sequence": 1,
                "source": "composer",
            }
        )
        service.chat(
            {
                "query_text": "解釋上一筆",
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 2,
                "source": "composer",
            }
        )
        service.chat(
            {
                "query_text": "接著說",
                "visitor_id": VISITOR_ID,
                "session_id": second_session_id,
                "sequence": 2,
                "source": "composer",
            }
        )

        first, second, first_follow_up, second_follow_up = model.calls
        self.assertEqual(
            first["safety_identifier"],
            first_follow_up["safety_identifier"],
        )
        self.assertEqual(
            second["safety_identifier"],
            second_follow_up["safety_identifier"],
        )
        self.assertNotEqual(
            first["safety_identifier"],
            second["safety_identifier"],
        )
        self.assertEqual(first["history"], ())
        self.assertEqual(second["history"], ())
        self.assertIsNone(first["latest_evidence"])
        self.assertIsNone(second["latest_evidence"])
        self.assertEqual(
            first_follow_up["history"],
            (
                UatConversationMessage(
                    role="user",
                    content="查 PO470002002 的交期",
                ),
                UatConversationMessage(
                    role="assistant",
                    content="第一個 session 的證據。",
                ),
            ),
        )
        self.assertIsNotNone(first_follow_up["latest_evidence"])
        self.assertEqual(
            second_follow_up["history"],
            (
                UatConversationMessage(role="user", content="你好"),
                UatConversationMessage(
                    role="assistant",
                    content="第二個 session 的一般回答。",
                ),
            ),
        )
        self.assertIsNone(second_follow_up["latest_evidence"])

    def test_chat_keeps_history_isolated_between_visitors_with_same_session_id(self) -> None:
        model = _ScriptedConversationModel(
            [
                {
                    "response_kind": "answer",
                    "answer_text": "第一位訪客的回答。",
                },
                {
                    "response_kind": "answer",
                    "answer_text": "第二位訪客的回答。",
                },
                {
                    "response_kind": "answer",
                    "answer_text": "第一位訪客的後續回答。",
                },
                {
                    "response_kind": "answer",
                    "answer_text": "第二位訪客的後續回答。",
                },
            ]
        )
        service = _service_with_model(
            _paths.fresh_test_dir("mail-human-uat-chat-visitor-isolation"),
            model,
        )
        second_visitor_id = "uatvisitor_" + "4" * 32

        for visitor_id, query_text, sequence in (
            (VISITOR_ID, "第一位訪客", 1),
            (second_visitor_id, "第二位訪客", 1),
            (VISITOR_ID, "延續第一位", 2),
            (second_visitor_id, "延續第二位", 2),
        ):
            service.chat(
                {
                    "query_text": query_text,
                    "visitor_id": visitor_id,
                    "session_id": SESSION_ID,
                    "sequence": sequence,
                    "source": "composer",
                }
            )

        first, second, first_follow_up, second_follow_up = model.calls
        self.assertNotEqual(first["safety_identifier"], second["safety_identifier"])
        self.assertEqual(
            first["safety_identifier"],
            first_follow_up["safety_identifier"],
        )
        self.assertEqual(
            second["safety_identifier"],
            second_follow_up["safety_identifier"],
        )
        self.assertEqual(first["history"], ())
        self.assertEqual(second["history"], ())
        self.assertEqual(
            first_follow_up["history"],
            (
                UatConversationMessage(role="user", content="第一位訪客"),
                UatConversationMessage(role="assistant", content="第一位訪客的回答。"),
            ),
        )
        self.assertEqual(
            second_follow_up["history"],
            (
                UatConversationMessage(role="user", content="第二位訪客"),
                UatConversationMessage(role="assistant", content="第二位訪客的回答。"),
            ),
        )

    def test_post_endpoints_require_same_origin_browser_requests(self) -> None:
        service = _service("mail-human-uat-same-origin")
        body = json.dumps({"query_text": "pull-in"}).encode("utf-8")
        with _RunningSurface(service) as surface:
            missing_origin, missing_body = surface.request(
                "POST",
                "/api/query",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
            cross_origin, cross_body = surface.request(
                "POST",
                "/api/query",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    "Origin": "https://attacker.example",
                    "Sec-Fetch-Site": "cross-site",
                },
            )

        for response, response_body in (
            (missing_origin, missing_body),
            (cross_origin, cross_body),
        ):
            self.assertEqual(response.status, 403)
            self.assertEqual(
                json.loads(response_body)["error_code"],
                "same_origin_required",
            )
        self.assertEqual(service.session_summary()["query_count"], 0)
        self.assertEqual(service.session_summary()["uploaded_file_count"], 0)

    def test_anonymous_interactions_and_question_sources_are_recorded_privately(
        self,
    ) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-interactions")
        service = _service_from_state_dir(state_dir)
        with _RunningSurface(service) as surface:
            page_view_response, page_view_body = surface.request_json(
                "/api/interaction",
                {
                    "visitor_id": VISITOR_ID,
                    "session_id": SESSION_ID,
                    "sequence": 1,
                    "action": "page_view",
                    "details": {"viewport": "desktop"},
                },
            )
            upload_open_response, upload_open_body = surface.request_json(
                "/api/interaction",
                {
                    "visitor_id": VISITOR_ID,
                    "session_id": SESSION_ID,
                    "sequence": 2,
                    "action": "upload_open",
                    "details": {"source": "composer"},
                },
            )
            query_response, query_body = surface.request_json(
                "/api/query",
                {
                    "query_text": "有哪些料件需要 pull-in",
                    "sort": "relevance",
                    "limit": 8,
                    "visitor_id": VISITOR_ID,
                    "session_id": SESSION_ID,
                    "sequence": 3,
                    "source": "composer",
                },
            )
            summary_response, summary_body = surface.request(
                "GET",
                "/api/session-summary",
            )

        self.assertEqual(page_view_response.status, 200)
        self.assertEqual(json.loads(page_view_body)["action"], "page_view")
        self.assertEqual(upload_open_response.status, 200)
        self.assertEqual(json.loads(upload_open_body)["action"], "upload_open")
        self.assertEqual(query_response.status, 200)
        self.assertEqual(json.loads(query_body)["status"], "ok")
        summary = json.loads(summary_body)
        self.assertEqual(summary_response.status, 200)
        self.assertEqual(summary["interaction_count"], 2)
        self.assertEqual(
            summary["interaction_counts"],
            {"page_view": 1, "upload_open": 1},
        )
        self.assertEqual(summary["anonymous_visitor_count"], 1)
        self.assertEqual(summary["anonymous_session_count"], 1)

        event_path = state_dir / "mail-human-uat-events.private.jsonl"
        events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            [event["event_type"] for event in events],
            ["interaction", "interaction", "query", "query_result"],
        )
        self.assertEqual(events[0]["details"], {"viewport": "desktop"})
        self.assertEqual(events[1]["details"], {"source": "composer"})
        self.assertEqual(events[2]["query_text"], "有哪些料件需要 pull-in")
        self.assertEqual(events[2]["source"], "composer")
        self.assertEqual(events[2]["visitor_id"], VISITOR_ID)
        self.assertEqual(events[2]["session_id"], SESSION_ID)
        self.assertEqual([event["sequence"] for event in events[:3]], [1, 2, 3])
        self.assertEqual(events[3]["query_id"], events[2]["query_id"])
        rendered = event_path.read_text(encoding="utf-8")
        self.assertNotIn("filename", rendered)
        self.assertNotIn("keystroke", rendered)
        self.assertEqual(event_path.stat().st_mode & 0o777, 0o600)

    def test_interaction_api_rejects_open_ended_or_invalid_tracking_payloads(self) -> None:
        service = _service("mail-human-uat-interaction-negative")
        cases = [
            {
                "visitor_id": "visitor_other",
                "session_id": SESSION_ID,
                "sequence": 1,
                "action": "page_view",
                "details": {"viewport": "desktop"},
            },
            {
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "action": "raw_click",
                "details": {},
            },
            {
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "action": "quick_prompt",
                "details": {"prompt_id": "arbitrary_text"},
            },
            {
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "action": "shell_control",
                "details": {"control": "arbitrary_control"},
            },
            {
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "action": "upload_complete",
                "details": {
                    "accepted_file_count": 20,
                    "duplicate_file_count": 1,
                },
            },
        ]
        with _RunningSurface(service) as surface:
            responses = [surface.request_json("/api/interaction", payload) for payload in cases]

        for response, body in responses:
            self.assertEqual(response.status, 400)
            self.assertEqual(json.loads(body)["error_code"], "request_rejected")
        summary = service.session_summary()
        self.assertEqual(summary["interaction_count"], 0)
        self.assertEqual(summary["anonymous_visitor_count"], 0)
        self.assertEqual(summary["anonymous_session_count"], 0)

    def test_shell_control_exploration_is_recorded_with_closed_control_names(
        self,
    ) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-shell-controls")
        service = _service_from_state_dir(state_dir)
        for sequence, control in enumerate(
            (
                "brand_home",
                "search_conversations",
                "current_history",
                "model_selector",
                "tools_menu",
                "profile_card",
                "profile_avatar",
            ),
            start=1,
        ):
            response = service.record_interaction(
                {
                    "visitor_id": VISITOR_ID,
                    "session_id": SESSION_ID,
                    "sequence": sequence,
                    "action": "shell_control",
                    "details": {"control": control},
                }
            )
            self.assertEqual(response["action"], "shell_control")

        summary = service.session_summary()
        self.assertEqual(summary["interaction_count"], 7)
        self.assertEqual(summary["interaction_counts"], {"shell_control": 7})
        event_path = state_dir / "mail-human-uat-events.private.jsonl"
        events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            [event["details"]["control"] for event in events],
            [
                "brand_home",
                "search_conversations",
                "current_history",
                "model_selector",
                "tools_menu",
                "profile_card",
                "profile_avatar",
            ],
        )
        self.assertEqual([event["sequence"] for event in events], list(range(1, 8)))

    def test_private_event_store_enforces_retention_and_size_bounds(self) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-event-retention")
        event_path = state_dir / "mail-human-uat-events.private.jsonl"
        old_event = {
            "event_type": "interaction",
            "created_at": "2026-06-17T12:00:00+00:00",
            "visitor_id": VISITOR_ID,
            "session_id": SESSION_ID,
            "sequence": 1,
            "action": "page_view",
            "details": {"viewport": "desktop"},
        }
        recent_event = {
            **old_event,
            "created_at": "2026-07-17T12:00:00+00:00",
            "sequence": 2,
        }
        event_path.write_text(
            "\n".join(json.dumps(event, ensure_ascii=False) for event in (old_event, recent_event))
            + "\n",
            encoding="utf-8",
        )
        service = MailHumanUatService(
            MailHumanUatHttpConfig(
                bundle=_bundle(),
                state_dir=state_dir,
                fixed_now=NOW,
                max_event_store_bytes=900,
            )
        )
        after_start = [
            json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([event["sequence"] for event in after_start], [2])

        for sequence in range(3, 21):
            service.record_interaction(
                {
                    "visitor_id": VISITOR_ID,
                    "session_id": SESSION_ID,
                    "sequence": sequence,
                    "action": "shell_control",
                    "details": {"control": "tools_menu"},
                }
            )

        retained = [
            json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertLessEqual(event_path.stat().st_size, 900)
        self.assertEqual(retained[-1]["sequence"], 20)
        self.assertGreater(retained[0]["sequence"], 2)
        self.assertEqual(event_path.stat().st_mode & 0o777, 0o600)

    def test_generic_identifier_query_returns_cited_read_only_evidence(
        self,
    ) -> None:
        service = _service("mail-human-uat-query")
        with _RunningSurface(service) as surface:
            response, body = surface.request_json(
                "/api/query",
                {
                    "query_text": "最近一次 PO470002002 的交期",
                    "sort": "recent",
                    "limit": 5,
                },
            )

        payload = json.loads(body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(payload["result_count"], 1)
        self.assertEqual(payload["results"][0]["subject"], "Supplier pull-in request")
        self.assertIn("PO470002002", payload["results"][0]["snippet"])
        self.assertEqual(payload["results"][0]["sent_at"], "2026-06-14T08:00:00+00:00")
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
        self.assertEqual(
            [event["event_type"] for event in events],
            ["query", "query_result", "feedback"],
        )
        self.assertEqual(events[2]["note"], "料號正確，但需要再確認交期。")
        self.assertEqual(event_path.stat().st_mode & 0o777, 0o600)

    def test_follow_ups_revise_task_projection_and_new_chat_resets_context(self) -> None:
        service = _service("mail-human-uat-task-frame")
        first = service.query(
            {
                "query_text": "pull-in",
                "limit": 50,
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 1,
                "source": "composer",
            }
        )
        self.assertEqual(first["task_frame"]["revision"], 1)
        self.assertEqual(first["coverage"]["cardinality_mode"], "all_matching")
        self.assertEqual(first["projection"]["output_format"], "narrative")
        self.assertGreater(first["result_count"], 0)

        table = service.query(
            {
                "query_text": "我只想看到表格，不要給我寄件人跟收件人的資訊",
                "limit": 50,
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 2,
                "source": "composer",
            }
        )
        self.assertEqual(table["task_frame"]["revision"], 2)
        self.assertEqual(table["task_frame"]["changed_dimensions"], ["projection"])
        self.assertEqual(table["projection"]["output_format"], "table")
        self.assertGreater(table["result_count"], 0)
        self.assertEqual(
            service._task_frames_by_conversation_id[
                _conversation_id(VISITOR_ID, SESSION_ID)
            ].retrieval_query_text,
            "pull-in",
        )
        self.assertNotIn("sender", table["results"][0])
        self.assertNotIn("recipient", table["results"][0])

        refined = service.query(
            {
                "query_text": "寄件者應該是DENNIS",
                "limit": 50,
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 3,
                "source": "composer",
            }
        )
        self.assertEqual(refined["task_frame"]["revision"], 3)
        self.assertIn("anchors", refined["task_frame"]["changed_dimensions"])
        self.assertIn("retrieval_query", refined["task_frame"]["changed_dimensions"])
        self.assertIn(
            "DENNIS",
            service._task_frames_by_conversation_id[
                _conversation_id(VISITOR_ID, SESSION_ID)
            ].retrieval_query_text,
        )

        new_identifier = service.query(
            {
                "query_text": "請查 NEW.12345 的內容",
                "limit": 50,
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 4,
                "source": "composer",
            }
        )
        self.assertEqual(new_identifier["task_frame"]["revision"], 1)
        identifier_frame_id = new_identifier["task_frame"]["task_frame_id"]

        service.record_interaction(
            {
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 5,
                "action": "new_chat",
                "details": {},
            }
        )
        reset = service.query(
            {
                "query_text": "只想看到表格",
                "limit": 50,
                "visitor_id": VISITOR_ID,
                "session_id": SESSION_ID,
                "sequence": 6,
                "source": "composer",
            }
        )
        self.assertEqual(reset["task_frame"]["revision"], 1)
        self.assertNotEqual(reset["task_frame"]["task_frame_id"], identifier_frame_id)

    def test_default_query_returns_more_than_eight_and_reports_display_coverage(
        self,
    ) -> None:
        bundle = _bulk_bundle(12)
        service = MailHumanUatService(
            MailHumanUatHttpConfig(
                bundle=bundle,
                state_dir=_paths.fresh_test_dir("mail-human-uat-all-matches"),
                fixed_now=NOW,
            )
        )

        complete = service.query({"query_text": "BULK_MATCH_TERM"})
        self.assertEqual(complete["total_result_count"], 12)
        self.assertEqual(complete["displayed_result_count"], 12)
        self.assertEqual(complete["result_count"], 12)
        self.assertEqual(complete["coverage"]["returned_source_item_count"], 12)
        self.assertTrue(complete["coverage"]["is_exhaustive"])
        self.assertFalse(complete["coverage"]["has_more"])
        self.assertFalse(complete["projection"]["has_more"])

        paged = service.query({"query_text": "BULK_MATCH_TERM", "limit": 8})
        self.assertEqual(paged["total_result_count"], 12)
        self.assertEqual(paged["displayed_result_count"], 8)
        self.assertEqual(paged["coverage"]["returned_source_item_count"], 12)
        self.assertTrue(paged["coverage"]["is_exhaustive"])
        self.assertFalse(paged["coverage"]["has_more"])
        self.assertTrue(paged["projection"]["has_more"])

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

    def test_txt_reference_is_persistent_and_immediately_queryable(self) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-txt-upload")
        service = _service_from_state_dir(state_dir)
        content = (
            "量產會議附件\n\n"
            "TXT_REFERENCE_TERM_8172 對應料件 SP.TXT.001，請確認 2026-08-03 排程。"
        ).encode("utf-8")
        with _RunningSurface(service) as surface:
            upload_response, upload_body = surface.request_upload(
                [("meeting-reference.txt", content)]
            )
            query_response, query_body = surface.request_json(
                "/api/query",
                {"query_text": "TXT_REFERENCE_TERM_8172", "limit": 5},
            )

        upload = json.loads(upload_body)
        query = json.loads(query_body)
        self.assertEqual(upload_response.status, 201)
        self.assertEqual(upload["accepted_file_count"], 1)
        self.assertEqual(upload["indexed_item_count"], 1)
        self.assertEqual(query_response.status, 200)
        self.assertEqual(query["result_count"], 1)
        self.assertIn("SP.TXT.001", query["results"][0]["snippet"])
        stored = list((state_dir / "mail-human-uat-uploads.private").iterdir())
        self.assertEqual(len(stored), 1)
        self.assertRegex(stored[0].name, r"^[0-9a-f]{64}\.txt$")

        restarted = _service_from_state_dir(state_dir)
        self.assertEqual(
            restarted.query({"query_text": "TXT_REFERENCE_TERM_8172", "limit": 5})["result_count"],
            1,
        )

    def test_text_pdf_is_accepted_as_searchable_reference(self) -> None:
        service = _service("mail-human-uat-pdf-upload")
        with mock.patch(
            "formowl_mail.human_uat_upload._extract_pdf_text",
            return_value=(
                "PDF_REFERENCE_TERM_4921\n"
                "附件內容指出料件 SP.PDF.002 需要 pull-in 到 2026-08-05。"
            ),
        ):
            with _RunningSurface(service) as surface:
                upload_response, upload_body = surface.request_upload(
                    [("supplier-reference.pdf", b"%PDF-1.4\nmock-uplift-fixture")]
                )
                query_response, query_body = surface.request_json(
                    "/api/query",
                    {"query_text": "PDF_REFERENCE_TERM_4921", "limit": 5},
                )

        upload = json.loads(upload_body)
        query = json.loads(query_body)
        self.assertEqual(upload_response.status, 201)
        self.assertEqual(upload["accepted_file_count"], 1)
        self.assertEqual(upload["indexed_item_count"], 1)
        self.assertEqual(query_response.status, 200)
        self.assertEqual(query["result_count"], 1)
        self.assertIn("SP.PDF.002", query["results"][0]["snippet"])

    def test_pst_batch_is_expanded_into_searchable_mail(self) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-pst-upload")

        def runner(command, _timeout):
            output_dir = Path(command[command.index("-o") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "message-1.eml").write_bytes(
                _eml(
                    subject="PST batch mail",
                    body="PST_BATCH_TERM_6631 includes material SP.PST.003.",
                )
            )
            return _ParserCommandResult(returncode=0)

        adapter = PstMailArchiveExtractor(
            runner=runner,
            scratch_parent=state_dir / "pst-adapter-scratch",
        )
        with mock.patch(
            "formowl_mail.human_uat_upload.PstMailArchiveExtractor",
            return_value=adapter,
        ):
            service = _service_from_state_dir(state_dir)
            with _RunningSurface(service) as surface:
                upload_response, upload_body = surface.request_upload(
                    [("mail-archive.pst", b"!BDN synthetic-UAT-PST")]
                )
                query_response, query_body = surface.request_json(
                    "/api/query",
                    {"query_text": "PST_BATCH_TERM_6631", "limit": 5},
                )

        upload = json.loads(upload_body)
        query = json.loads(query_body)
        self.assertEqual(upload_response.status, 201)
        self.assertEqual(upload["accepted_file_count"], 1)
        self.assertEqual(upload["indexed_item_count"], 1)
        self.assertEqual(query_response.status, 200)
        self.assertEqual(query["result_count"], 1)
        self.assertIn("SP.PST.003", query["results"][0]["snippet"])
        stored = list((state_dir / "mail-human-uat-uploads.private").glob("*.pst"))
        self.assertEqual(len(stored), 1)

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

    def test_upload_rejects_msg_or_oversized_eml(self) -> None:
        service = MailHumanUatService(
            MailHumanUatHttpConfig(
                bundle=_bundle(),
                state_dir=_paths.fresh_test_dir("mail-human-uat-upload-negative"),
                fixed_now=NOW,
                max_upload_request_bytes=2048,
                max_upload_file_bytes=512,
            )
        )
        with _RunningSurface(service) as surface:
            unsupported, unsupported_body = surface.request_upload(
                [("mail.msg", b"not a msg parser input")]
            )
            oversized, oversized_body = surface.request_upload(
                [("large.eml", _eml(subject="Large", body="x" * 700))]
            )

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

    def test_retrieval_failure_preserves_submitted_question_for_uat_diagnosis(
        self,
    ) -> None:
        state_dir = _paths.fresh_test_dir("mail-human-uat-query-runtime-failure")
        service = _service_from_state_dir(state_dir)
        with mock.patch.object(
            service._base_gateway,
            "execute_mail_evidence_query",
            side_effect=RuntimeError("simulated retrieval failure"),
        ):
            with self.assertRaises(RuntimeError):
                service.query(
                    {
                        "query_text": "失敗時也要保留這個已送出的問題",
                        "sort": "relevance",
                        "limit": 5,
                        "visitor_id": VISITOR_ID,
                        "session_id": SESSION_ID,
                        "sequence": 9,
                        "source": "composer",
                    }
                )

        summary = service.session_summary()
        self.assertEqual(summary["query_count"], 1)
        self.assertEqual(summary["anonymous_visitor_count"], 1)
        event_path = state_dir / "mail-human-uat-events.private.jsonl"
        events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "query")
        self.assertEqual(events[0]["query_text"], "失敗時也要保留這個已送出的問題")
        self.assertEqual(events[0]["sequence"], 9)
        self.assertNotIn("result_count", events[0])

    def test_interaction_event_failure_does_not_advance_interaction_counts(self) -> None:
        service = _service("mail-human-uat-interaction-event-failure")

        def fail_event_write(_payload):
            raise OSError("simulated private interaction write failure")

        service._event_store.append = fail_event_write
        with self.assertRaises(OSError):
            service.record_interaction(
                {
                    "visitor_id": VISITOR_ID,
                    "session_id": SESSION_ID,
                    "sequence": 1,
                    "action": "shell_control",
                    "details": {"control": "tools_menu"},
                }
            )

        summary = service.session_summary()
        self.assertEqual(summary["interaction_count"], 0)
        self.assertEqual(summary["interaction_counts"], {})
        self.assertEqual(summary["anonymous_visitor_count"], 0)
        self.assertEqual(summary["anonymous_session_count"], 0)

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
            state_dir=state_dir,
            fixed_now=NOW,
        )
    )


def _service_with_model(
    state_dir: Path,
    model: _ScriptedConversationModel,
) -> MailHumanUatService:
    return MailHumanUatService(
        MailHumanUatHttpConfig(
            bundle=_bundle(),
            state_dir=state_dir,
            conversation_model=model,
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
                "Please pull-in material 09.B0540GW71, PO470002002, "
                "legacy reference PO 470002154, "
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


def _bulk_bundle(count: int) -> MailEvidenceBundle:
    base = _bundle()
    messages = []
    body_segments = []
    for index in range(count):
        message_id = f"emailmessage_bulk_{index:03d}"
        observation_id = f"obs_bulk_{index:03d}"
        messages.append(
            EmailMessage(
                email_message_id=message_id,
                message_fingerprint="sha256:" + f"{index + 100:064x}",
                message_id=f"message_bulk_{index:03d}",
                archive_id="archive_bulk",
                mailbox_id="mailbox_bulk",
                source_observation_ids=[observation_id],
                subject=f"Bulk evidence {index + 1}",
                sender="source@example.com",
                sent_at=f"2026-07-{(index % 20) + 1:02d}T08:00:00+00:00",
            )
        )
        body_segments.append(
            EmailBodySegment(
                email_body_segment_id=f"body_bulk_{index:03d}",
                email_message_id=message_id,
                message_occurrence_id=f"occ_bulk_{index:03d}",
                source_observation_id=observation_id,
                text=f"BULK_MATCH_TERM source content number {index + 1}.",
                body_segment_hash="sha256:" + f"{index + 1000:064x}",
                body_segment_index=0,
            )
        )
    return replace(
        base,
        mail_evidence_bundle_id="mailevidencebundle_bulk_uat",
        messages=messages,
        body_segments=body_segments,
    )


def _exhaustive_uat_source_ids(
    bundle: MailEvidenceBundle,
    required_terms: tuple[str, ...],
) -> frozenset[str]:
    """Independent bounded oracle over complete logical source text."""
    segments_by_message_id: dict[str, list[str]] = {}
    for segment in bundle.body_segments:
        segments_by_message_id.setdefault(segment.email_message_id, []).append(segment.text)
    matches: set[str] = set()
    for message in bundle.messages:
        source_text = unicodedata.normalize(
            "NFKC",
            "\n".join(
                [
                    message.subject or "",
                    *segments_by_message_id.get(message.email_message_id, ()),
                ]
            ),
        ).casefold()
        if all(
            unicodedata.normalize("NFKC", term).casefold().strip() in source_text
            for term in required_terms
        ):
            matches.add(message.email_message_id)
    return frozenset(
        segment.source_observation_id
        for segment in bundle.body_segments
        if segment.email_message_id in matches
    )


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
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "Origin": self.origin,
                "Sec-Fetch-Site": "same-origin",
            },
        )

    def request_upload(
        self,
        files: list[tuple[str, bytes]],
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
            "Origin": self.origin,
            "Sec-Fetch-Site": "same-origin",
        }
        return self.request(
            "POST",
            "/api/upload",
            body=bytes(body),
            headers=headers,
        )

    @property
    def origin(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"


if __name__ == "__main__":
    unittest.main()
