from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

import _paths  # noqa: F401
from formowl_gateway.remote import build_remote_tool_descriptors
from formowl_mail.human_uat_orchestrator import (
    CodexResponsesConversationModel,
)


def _decision(*, citation: str) -> str:
    return json.dumps(
        {
            "response_kind": "answer",
            "answer_text": "已整理目前可引用的授權郵件；涵蓋仍不完整。",
            "display_format": "narrative",
            "citation_ids": [citation],
            "coverage_status": "incomplete",
            "coverage_note": "目前結果為授權範圍內的部分證據。",
        },
        separators=(",", ":"),
    )


def _mail_tool_descriptor() -> dict:
    return next(
        tool.model_dump(by_alias=True, exclude_none=True)
        for tool in build_remote_tool_descriptors(
            required_scope="formowl.use",
            enabled_tool_names={"whoami", "query_mail_evidence"},
        )
        if tool.name == "query_mail_evidence"
    )


class Issue56ProviderFinalizationTests(unittest.TestCase):
    def test_ordinary_chat_sends_none_when_no_tools_are_selected(self):
        requests: list[dict] = []
        evidence_calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers["Content-Length"])
                requests.append(json.loads(self.rfile.read(length)))
                body = {
                    "status": "completed",
                    "output_text": json.dumps(
                        {
                            "response_kind": "answer",
                            "answer_text": "你好，我可以協助回答一般問題。",
                            "display_format": "narrative",
                            "citation_ids": [],
                            "coverage_status": "not_applicable",
                            "coverage_note": "",
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
                encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = CodexResponsesConversationModel(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="synthetic-local-provider-key",
            )
            outcome = provider.respond(
                history=(),
                user_text="你好，今天好嗎？",
                latest_evidence=None,
                safety_identifier="ordinary-no-tools-local-session",
                evidence_tool=lambda request: evidence_calls.append(request) or {},
                formowl_tool_descriptor=_mail_tool_descriptor(),
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["tools"], [])
        self.assertEqual(requests[0]["tool_choice"], "none")
        self.assertEqual(evidence_calls, [])

    def test_stateless_mail_finalization_replays_encrypted_reasoning_and_tool_pair(self):
        citation = "citation-provider-finalization"
        requests: list[dict] = []
        headers: list[dict[str, str]] = []
        evidence_requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length))
                requests.append(payload)
                headers.append({key: value for key, value in self.headers.items()})
                if len(requests) == 1:
                    body = {
                        "status": "completed",
                        "output": [
                            {
                                "type": "reasoning",
                                "id": "rs-provider-finalization",
                                "encrypted_content": "opaque-reasoning",
                                "content": [],
                                "summary": [],
                            },
                            {
                                "type": "function_call",
                                "call_id": "call-provider-finalization",
                                "name": "query_mail_evidence",
                                "arguments": json.dumps(
                                    {
                                        "query_text": "把授權郵件整理出來",
                                        "required_terms": ["授權郵件"],
                                        "mail_import_session_id": "authorized-session",
                                        "limit": 100,
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                    }
                else:
                    body = {
                        "status": "completed",
                        "output_text": _decision(citation=citation),
                    }
                is_stream = payload.get("stream") is True
                if is_stream:
                    event = {
                        "type": "response.completed",
                        "response": body,
                    }
                    encoded = (
                        b"event: response.completed\n"
                        + b"data: "
                        + json.dumps(event, ensure_ascii=False).encode("utf-8")
                        + b"\n\n"
                    )
                else:
                    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/event-stream" if is_stream else "application/json",
                )
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        original_prompt = "把授權郵件整理出來"
        try:
            provider = CodexResponsesConversationModel(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="synthetic-local-provider-key",
            )
            outcome = provider.respond(
                history=(),
                user_text=original_prompt,
                latest_evidence=None,
                safety_identifier="provider-finalization-local-session",
                evidence_tool=lambda request: (
                    evidence_requests.append(request)
                    or {
                        "status": "ok",
                        "mail_import_session_id": request.mail_import_session_id,
                        "evidence_snippets": [
                            {
                                "citation_id": citation,
                                "snippet": "bounded governed mail evidence",
                            }
                        ],
                        "citations": [citation],
                    }
                ),
                formowl_tool_descriptor=_mail_tool_descriptor(),
                authorized_capability_summary={
                    "source_families": ["mail"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["authorized-session"],
                },
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(len(evidence_requests), 1)
        self.assertEqual(evidence_requests[0].mail_import_session_id, "authorized-session")
        self.assertEqual(evidence_requests[0].required_terms, ("授權郵件",))
        self.assertIsNone(evidence_requests[0].mail_evidence_bundle_id)
        self.assertEqual(evidence_requests[0].limit, 100)
        self.assertIsNone(evidence_requests[0].table_query)
        self.assertIsNone(evidence_requests[0].exact_inventory_kind)
        self.assertIsNone(evidence_requests[0].exact_field)
        self.assertIsNone(evidence_requests[0].page_size)
        self.assertIsNone(evidence_requests[0].cursor)
        request_contract = evidence_requests[0].request_contract
        self.assertEqual(
            request_contract["original_query_hash"],
            "sha256:" + hashlib.sha256(original_prompt.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(request_contract["query_class"], "evidence_lookup")
        self.assertEqual(request_contract["source_family_scope"], ["mail"])
        self.assertEqual(request_contract["maximum_claim_strength"], "cited_evidence")
        self.assertEqual(len(requests), 2)
        self.assertEqual(
            [tool["name"] for tool in requests[0]["tools"]],
            ["query_mail_evidence"],
        )
        self.assertEqual(
            requests[0]["tool_choice"],
            {"type": "function", "name": "query_mail_evidence"},
        )
        self.assertEqual(requests[1]["tools"], [])
        self.assertEqual(requests[1]["tool_choice"], "none")
        self.assertNotIn(
            "clarify_public_terminology",
            json.dumps(requests[0]["tools"]),
        )
        self.assertEqual(requests[0]["max_output_tokens"], 4096)
        self.assertEqual(
            requests[0]["include"],
            ["reasoning.encrypted_content"],
        )
        self.assertEqual(
            requests[1]["include"],
            ["reasoning.encrypted_content"],
        )
        continuation_input = requests[1]["input"]
        reasoning_items = [
            item for item in continuation_input if item.get("type") == "reasoning"
        ]
        self.assertEqual(len(reasoning_items), 1)
        self.assertEqual(
            reasoning_items[0]["encrypted_content"],
            "opaque-reasoning",
        )
        function_calls = [
            item for item in continuation_input if item.get("type") == "function_call"
        ]
        self.assertEqual(
            [item["call_id"] for item in function_calls],
            ["call-provider-finalization"],
        )
        function_outputs = [
            item
            for item in continuation_input
            if item.get("type") == "function_call_output"
        ]
        self.assertEqual(
            [item["call_id"] for item in function_outputs],
            ["call-provider-finalization"],
        )
        self.assertIn(citation, function_outputs[0]["output"])
        self.assertEqual(headers[0]["Authorization"], "Bearer synthetic-local-provider-key")
        self.assertEqual(headers[1]["Authorization"], "Bearer synthetic-local-provider-key")
        self.assertIsNot(requests[0].get("stream"), True)
        self.assertIs(requests[1]["stream"], True)
        self.assertEqual(headers[1]["Accept"], "text/event-stream")


if __name__ == "__main__":
    unittest.main()
