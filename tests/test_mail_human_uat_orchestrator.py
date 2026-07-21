from __future__ import annotations

import json
import unittest
from unittest import mock
from urllib import error as urllib_error

import _paths  # noqa: F401
from formowl_mail.human_uat_orchestrator import (
    OpenAIResponsesConversationModel,
    OpenAIResponsesHttpTransport,
    UatConversationMessage,
)


def _message_response(
    *,
    response_kind: str,
    answer_text: str,
    display_format: str = "narrative",
) -> dict[str, object]:
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "response_kind": response_kind,
                                "answer_text": answer_text,
                                "display_format": display_format,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            }
        ],
    }


class _RecordingTransport:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.payloads: list[dict[str, object]] = []

    def create_response(self, payload):
        self.payloads.append(dict(payload))
        return self.responses.pop(0)


class _BytesResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.payload


class MailHumanUatOrchestratorTests(unittest.TestCase):
    def test_direct_answer_does_not_call_formowl(self) -> None:
        transport = _RecordingTransport(
            [
                _message_response(
                    response_kind="answer",
                    answer_text="這個問題不需要調閱來源。",
                )
            ]
        )
        model = OpenAIResponsesConversationModel(
            transport,
            model="gpt-5.6-terra",
            reasoning_effort="low",
        )
        tool_calls = []

        outcome = model.respond(
            history=(),
            user_text="你好",
            latest_evidence=None,
            safety_identifier="formowl_uat_" + "1" * 48,
            evidence_tool=lambda request: tool_calls.append(request),
        )

        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(outcome.answer_text, "這個問題不需要調閱來源。")
        self.assertIsNone(outcome.tool_request)
        self.assertEqual(tool_calls, [])
        self.assertEqual(len(transport.payloads), 1)
        request = transport.payloads[0]
        self.assertEqual(request["tool_choice"], "auto")
        self.assertFalse(request["parallel_tool_calls"])
        self.assertFalse(request["store"])
        self.assertEqual(request["model"], "gpt-5.6-terra")
        self.assertTrue(request["tools"][0]["strict"])
        self.assertFalse(request["tools"][0]["parameters"]["additionalProperties"])

    def test_function_call_is_executed_then_returned_for_final_answer(self) -> None:
        first = {
            "status": "completed",
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_test",
                    "encrypted_content": "opaque",
                },
                {
                    "type": "function_call",
                    "id": "fc_test",
                    "call_id": "call_test",
                    "name": "search_formowl_evidence",
                    "arguments": json.dumps(
                        {
                            "query_text": "PO470002002 delivery",
                            "required_terms": ["PO470002002"],
                            "sort": "relevance",
                            "limit": 50,
                        }
                    ),
                },
            ],
        }
        transport = _RecordingTransport(
            [
                first,
                _message_response(
                    response_kind="answer",
                    answer_text="來源證據已整理完成。",
                    display_format="table",
                ),
            ]
        )
        model = OpenAIResponsesConversationModel(transport)
        requests = []

        def evidence_tool(request):
            requests.append(request)
            return {
                "status": "ok",
                "total_result_count": 1,
                "displayed_result_count": 1,
                "results": [
                    {
                        "subject": "Delivery",
                        "snippet": "PO470002002 delivery is 2026-08-01.",
                        "sent_at": "2026-07-20T08:00:00+00:00",
                        "citation": {"citation_id": "mailcitation_test"},
                    }
                ],
            }

        outcome = model.respond(
            history=(
                UatConversationMessage(role="user", content="前一題"),
                UatConversationMessage(role="assistant", content="前一答"),
            ),
            user_text="查 PO470002002 的交期",
            latest_evidence=None,
            safety_identifier="formowl_uat_" + "2" * 48,
            evidence_tool=evidence_tool,
        )

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].query_text, "PO470002002 delivery")
        self.assertEqual(requests[0].required_terms, ("PO470002002",))
        self.assertEqual(outcome.answer_text, "來源證據已整理完成。")
        self.assertEqual(outcome.display_format, "table")
        self.assertIsNotNone(outcome.tool_result)
        self.assertEqual(len(transport.payloads), 2)
        continuation = transport.payloads[1]
        self.assertEqual(continuation["tool_choice"], "none")
        continuation_input = continuation["input"]
        self.assertIn(first["output"][0], continuation_input)
        self.assertIn(first["output"][1], continuation_input)
        tool_output = continuation_input[-1]
        self.assertEqual(tool_output["type"], "function_call_output")
        self.assertEqual(tool_output["call_id"], "call_test")
        rendered_output = json.loads(tool_output["output"])
        self.assertEqual(rendered_output["total_result_count"], 1)
        self.assertEqual(
            rendered_output["results"][0]["content"],
            "PO470002002 delivery is 2026-08-01.",
        )

    def test_unknown_multiple_and_malformed_tool_calls_fail_closed(self) -> None:
        cases = [
            [
                {
                    "type": "function_call",
                    "call_id": "call_unknown",
                    "name": "unknown_tool",
                    "arguments": "{}",
                }
            ],
            [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "search_formowl_evidence",
                    "arguments": "{}",
                },
                {
                    "type": "function_call",
                    "call_id": "call_2",
                    "name": "search_formowl_evidence",
                    "arguments": "{}",
                },
            ],
            [
                {
                    "type": "function_call",
                    "call_id": "call_bad",
                    "name": "search_formowl_evidence",
                    "arguments": "{not-json",
                }
            ],
        ]
        for output in cases:
            with self.subTest(output=output):
                model = OpenAIResponsesConversationModel(
                    _RecordingTransport([{"status": "completed", "output": output}])
                )
                calls = []
                with self.assertRaises(RuntimeError):
                    model.respond(
                        history=(),
                        user_text="test",
                        latest_evidence=None,
                        safety_identifier="formowl_uat_" + "3" * 48,
                        evidence_tool=lambda request: calls.append(request),
                    )
                self.assertEqual(calls, [])

    def test_http_transport_returns_generic_errors_without_leaking_key(self) -> None:
        transport = OpenAIResponsesHttpTransport(api_key="super-secret-key")
        with mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib_request.urlopen",
            side_effect=urllib_error.URLError("super-secret-key upstream private detail"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "^UAT conversation model request failed$",
            ) as captured:
                transport.create_response({"model": "gpt-5.6-terra"})
        self.assertNotIn("super-secret-key", str(captured.exception))

        with mock.patch(
            "formowl_mail.human_uat_orchestrator.urllib_request.urlopen",
            return_value=_BytesResponse(b"not-json"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "^UAT conversation model returned an invalid response$",
            ):
                transport.create_response({"model": "gpt-5.6-terra"})


if __name__ == "__main__":
    unittest.main()
