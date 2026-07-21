from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_mail.human_uat_orchestrator import (
    CodexAppServerConversationModel,
    CodexAppServerStdioTransport,
    CodexAppServerThread,
    CodexAppServerTurn,
    CodexDynamicToolInvocation,
    UatConversationMessage,
    _CODEX_DISABLED_FEATURES,
    _assert_hardened_codex_runtime,
    build_codex_app_server_proxy_command,
    build_hardened_codex_app_server_command,
    prepare_codex_runtime_state,
    prepare_codex_runtime_state_from_auth_cache,
    validate_codex_runtime_state,
)


def _decision(
    *,
    response_kind: str = "answer",
    answer_text: str = "完成。",
    display_format: str = "narrative",
) -> str:
    return json.dumps(
        {
            "response_kind": response_kind,
            "answer_text": answer_text,
            "display_format": display_format,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


class _RecordingCodexTransport:
    def __init__(self, turns: list[dict[str, object]]) -> None:
        self.turns = list(turns)
        self.thread_starts: list[dict[str, object]] = []
        self.turn_calls: list[dict[str, object]] = []
        self.deleted_threads: list[str] = []
        self.closed = False

    def start_thread(
        self,
        *,
        model,
        cwd,
        base_instructions,
        developer_instructions,
        dynamic_tools,
    ):
        thread_id = f"thread_{len(self.thread_starts) + 1}"
        self.thread_starts.append(
            {
                "model": model,
                "cwd": cwd,
                "base_instructions": base_instructions,
                "developer_instructions": developer_instructions,
                "dynamic_tools": tuple(dynamic_tools),
                "thread_id": thread_id,
            }
        )
        return CodexAppServerThread(
            thread_id=thread_id,
            model_name=model or "gpt-test-default",
        )

    def run_turn(
        self,
        *,
        thread_id,
        user_text,
        additional_context,
        output_schema,
        reasoning_effort,
        client_metadata,
        tool_handler,
    ):
        step = self.turns.pop(0)
        turn_id = f"turn_{len(self.turn_calls) + 1}"
        self.turn_calls.append(
            {
                "thread_id": thread_id,
                "user_text": user_text,
                "additional_context": dict(additional_context),
                "output_schema": dict(output_schema),
                "reasoning_effort": reasoning_effort,
                "client_metadata": dict(client_metadata),
            }
        )
        invocations = []
        for index, tool_call in enumerate(step.get("tool_calls", []), start=1):
            tool_name = tool_call["tool_name"]
            arguments = tool_call["arguments"]
            result = tool_handler(tool_name, arguments)
            invocations.append(
                CodexDynamicToolInvocation(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    call_id=f"call_{index}",
                    tool_name=tool_name,
                    arguments=dict(arguments),
                    result=dict(result),
                )
            )
        if step.get("drop_invocations"):
            invocations = []
        return CodexAppServerTurn(
            thread_id=thread_id,
            turn_id=turn_id,
            final_message=str(step["final_message"]),
            tool_invocations=tuple(invocations),
        )

    def delete_thread(self, thread_id):
        self.deleted_threads.append(thread_id)

    def close(self):
        self.closed = True


_FAKE_APP_SERVER = textwrap.dedent(
    r"""
    import json
    from pathlib import Path
    import sys

    trace_path = Path(sys.argv[1])

    def trace(message):
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")

    def send(message):
        print(json.dumps(message, ensure_ascii=False), flush=True)

    for line in sys.stdin:
        message = json.loads(line)
        trace(message)
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            send({"id": request_id, "result": {"serverInfo": {"name": "fake"}}})
        elif method == "initialized":
            continue
        elif method == "thread/start":
            send(
                {
                    "id": request_id,
                    "result": {
                        "thread": {"id": "thread_stdio"},
                        "model": "gpt-test-stdio",
                    },
                }
            )
        elif method == "turn/start":
            send(
                {
                    "id": request_id,
                    "result": {"turn": {"id": "turn_stdio"}},
                }
            )
            send(
                {
                    "id": "server_tool_1",
                    "method": "item/tool/call",
                    "params": {
                        "threadId": "thread_stdio",
                        "turnId": "turn_stdio",
                        "callId": "call_stdio",
                        "tool": "search_formowl_evidence",
                        "arguments": {
                            "query_text": "source-neutral question",
                            "required_terms": ["ID-42"],
                            "sort": "relevance",
                            "limit": 20,
                        },
                    },
                }
            )
        elif method == "thread/delete":
            send({"id": request_id, "result": {}})
        elif request_id == "server_tool_1":
            result = message.get("result", {})
            valid = (
                result.get("success") is True
                and result.get("contentItems", [{}])[0].get("type") == "inputText"
            )
            final_message = json.dumps(
                {
                    "response_kind": "answer",
                    "answer_text": "stdio tool complete" if valid else "invalid tool response",
                    "display_format": "table",
                },
                separators=(",", ":"),
            )
            send(
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": "thread_stdio",
                        "turnId": "turn_stdio",
                        "completedAtMs": 1,
                        "item": {
                            "id": "message_stdio",
                            "type": "agentMessage",
                            "text": final_message,
                            "phase": "final_answer",
                        },
                    },
                }
            )
            send(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread_stdio",
                        "turn": {
                            "id": "turn_stdio",
                            "status": "completed",
                            "error": None,
                            "items": [],
                            "itemsView": "notLoaded",
                        },
                    },
                }
            )
    """
)

_FAKE_APP_SERVER_TOOL_PROTOCOL_VIOLATION = textwrap.dedent(
    r"""
    import json
    import sys

    scenario = sys.argv[1]

    def send(message):
        print(json.dumps(message, ensure_ascii=False), flush=True)

    def tool_request(request_id, *, turn_id, call_id):
        send(
            {
                "id": request_id,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread_stdio",
                    "turnId": turn_id,
                    "callId": call_id,
                    "tool": "search_formowl_evidence",
                    "arguments": {
                        "query_text": "source-neutral question",
                        "required_terms": [],
                        "sort": "relevance",
                        "limit": 20,
                    },
                },
            }
        )

    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            send({"id": request_id, "result": {"serverInfo": {"name": "fake"}}})
        elif method == "initialized":
            continue
        elif method == "thread/start":
            send(
                {
                    "id": request_id,
                    "result": {
                        "thread": {"id": "thread_stdio"},
                        "model": "gpt-test-stdio",
                    },
                }
            )
        elif method == "turn/start":
            send({"id": request_id, "result": {"turn": {"id": "turn_stdio"}}})
            if scenario == "mismatched_turn":
                tool_request(
                    "server_tool_mismatch",
                    turn_id="turn_stale",
                    call_id="call_1",
                )
            else:
                tool_request(
                    "server_tool_first",
                    turn_id="turn_stdio",
                    call_id="call_1",
                )
        elif request_id in {"server_tool_mismatch", "server_tool_duplicate"}:
            send(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread_stdio",
                        "turn": {
                            "id": "turn_stdio",
                            "status": "completed",
                            "error": None,
                            "items": [
                                {
                                    "id": "message_stdio",
                                    "type": "agentMessage",
                                    "text": "{}",
                                }
                            ],
                        },
                    },
                }
            )
        elif request_id == "server_tool_first":
            tool_request(
                "server_tool_duplicate",
                turn_id="turn_stdio",
                call_id="call_1",
            )
    """
)


class MailHumanUatOrchestratorTests(unittest.TestCase):
    def test_direct_answer_does_not_call_formowl(self) -> None:
        transport = _RecordingCodexTransport(
            [
                {
                    "final_message": _decision(
                        answer_text="這個問題不需要調閱來源。",
                    )
                }
            ]
        )
        with tempfile.TemporaryDirectory() as workspace:
            model = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
                model="gpt-test",
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
        self.assertEqual(len(transport.thread_starts), 1)
        thread_start = transport.thread_starts[0]
        self.assertEqual(thread_start["model"], "gpt-test")
        dynamic_tool = thread_start["dynamic_tools"][0]
        self.assertEqual(dynamic_tool["name"], "search_formowl_evidence")
        self.assertFalse(dynamic_tool["inputSchema"]["additionalProperties"])
        turn = transport.turn_calls[0]
        self.assertEqual(turn["reasoning_effort"], "low")
        self.assertFalse(turn["output_schema"]["additionalProperties"])
        self.assertEqual(turn["additional_context"], {})

    def test_dynamic_tool_is_executed_and_returned_with_original_evidence(self) -> None:
        transport = _RecordingCodexTransport(
            [
                {
                    "tool_calls": [
                        {
                            "tool_name": "search_formowl_evidence",
                            "arguments": {
                                "query_text": "ID-42 delivery",
                                "required_terms": ["ID-42"],
                                "sort": "recent",
                                "limit": 50,
                            },
                        }
                    ],
                    "final_message": _decision(
                        answer_text="來源證據已整理完成。",
                        display_format="table",
                    ),
                }
            ]
        )
        evidence_result = {
            "status": "ok",
            "total_result_count": 1,
            "displayed_result_count": 1,
            "results": [
                {
                    "subject": "Delivery",
                    "snippet": "ID-42 delivery is 2026-08-01.",
                    "sent_at": "2026-07-20T08:00:00+00:00",
                    "citation": {"citation_id": "mailcitation_test"},
                }
            ],
        }
        requests = []

        def evidence_tool(request):
            requests.append(request)
            return evidence_result

        with tempfile.TemporaryDirectory() as workspace:
            model = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            outcome = model.respond(
                history=(),
                user_text="查 ID-42 的交期",
                latest_evidence=None,
                safety_identifier="formowl_uat_" + "2" * 48,
                evidence_tool=evidence_tool,
            )

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].query_text, "ID-42 delivery")
        self.assertEqual(requests[0].required_terms, ("ID-42",))
        self.assertEqual(requests[0].sort, "recent")
        self.assertEqual(outcome.answer_text, "來源證據已整理完成。")
        self.assertEqual(outcome.display_format, "table")
        self.assertEqual(outcome.tool_result, evidence_result)

    def test_same_safety_identifier_reuses_thread_and_new_identifier_does_not(self) -> None:
        transport = _RecordingCodexTransport(
            [
                {"final_message": _decision(answer_text="first")},
                {"final_message": _decision(answer_text="second")},
                {"final_message": _decision(answer_text="third")},
            ]
        )
        with tempfile.TemporaryDirectory() as workspace:
            model = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            for safety_identifier in ("session-a", "session-a", "session-b"):
                model.respond(
                    history=(),
                    user_text="test",
                    latest_evidence=None,
                    safety_identifier=safety_identifier,
                    evidence_tool=lambda request: {},
                )

        self.assertEqual(len(transport.thread_starts), 2)
        self.assertEqual(
            [call["thread_id"] for call in transport.turn_calls],
            ["thread_1", "thread_1", "thread_2"],
        )

    def test_new_thread_receives_bounded_recovery_history_and_prior_evidence(self) -> None:
        transport = _RecordingCodexTransport(
            [{"final_message": _decision(answer_text="recovered")}]
        )
        prior_evidence = {
            "status": "ok",
            "results": [{"subject": "S", "snippet": "body"}],
        }
        history = (
            UatConversationMessage(role="user", content="之前的問題"),
            UatConversationMessage(role="assistant", content="之前的答案"),
        )
        with tempfile.TemporaryDirectory() as workspace:
            model = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            model.respond(
                history=history,
                user_text="換個說法",
                latest_evidence=prior_evidence,
                safety_identifier="session-recovery",
                evidence_tool=lambda request: {},
            )

        context = transport.turn_calls[0]["additional_context"]
        self.assertEqual(context["formowl_latest_evidence"]["kind"], "untrusted")
        self.assertIn("body", context["formowl_latest_evidence"]["value"])
        self.assertEqual(context["formowl_recovery_history"]["kind"], "untrusted")
        self.assertIn("之前的答案", context["formowl_recovery_history"]["value"])

    def test_unknown_malformed_multiple_and_inconsistent_tools_fail_closed(self) -> None:
        cases = [
            {
                "tool_calls": [{"tool_name": "unknown", "arguments": {}}],
                "final_message": _decision(),
                "expected_evidence_calls": 0,
            },
            {
                "tool_calls": [
                    {
                        "tool_name": "search_formowl_evidence",
                        "arguments": {"query_text": "missing fields"},
                    }
                ],
                "final_message": _decision(),
                "expected_evidence_calls": 0,
            },
            {
                "tool_calls": [
                    {
                        "tool_name": "search_formowl_evidence",
                        "arguments": {
                            "query_text": "first",
                            "required_terms": [],
                            "sort": "relevance",
                            "limit": 10,
                        },
                    },
                    {
                        "tool_name": "search_formowl_evidence",
                        "arguments": {
                            "query_text": "second",
                            "required_terms": [],
                            "sort": "relevance",
                            "limit": 10,
                        },
                    },
                ],
                "final_message": _decision(),
                "expected_evidence_calls": 1,
            },
            {
                "tool_calls": [
                    {
                        "tool_name": "search_formowl_evidence",
                        "arguments": {
                            "query_text": "valid",
                            "required_terms": [],
                            "sort": "relevance",
                            "limit": 10,
                        },
                    }
                ],
                "drop_invocations": True,
                "final_message": _decision(),
                "expected_evidence_calls": 1,
            },
        ]
        for index, step in enumerate(cases):
            with self.subTest(index=index):
                transport = _RecordingCodexTransport([step])
                evidence_calls = []
                with tempfile.TemporaryDirectory() as workspace:
                    model = CodexAppServerConversationModel(
                        transport,
                        workspace_dir=workspace,
                    )
                    with self.assertRaises((RuntimeError, ValueError)):
                        model.respond(
                            history=(),
                            user_text="test",
                            latest_evidence=None,
                            safety_identifier=f"session-{index}",
                            evidence_tool=lambda request: (evidence_calls.append(request) or {}),
                        )
                self.assertEqual(
                    len(evidence_calls),
                    step["expected_evidence_calls"],
                )
                self.assertEqual(transport.deleted_threads, ["thread_1"])

    def test_invalid_final_message_discards_thread(self) -> None:
        transport = _RecordingCodexTransport([{"final_message": "not-json"}])
        with tempfile.TemporaryDirectory() as workspace:
            model = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            with self.assertRaisesRegex(RuntimeError, "invalid UAT answer"):
                model.respond(
                    history=(),
                    user_text="test",
                    latest_evidence=None,
                    safety_identifier="session-invalid",
                    evidence_tool=lambda request: {},
                )
        self.assertEqual(transport.deleted_threads, ["thread_1"])

    def test_service_can_discard_advanced_conversation_thread(self) -> None:
        transport = _RecordingCodexTransport(
            [
                {"final_message": _decision(answer_text="first")},
                {"final_message": _decision(answer_text="retry")},
            ]
        )
        with tempfile.TemporaryDirectory() as workspace:
            model = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
            )
            identifier = "formowl_uat_" + "9" * 48
            model.respond(
                history=(),
                user_text="first",
                latest_evidence=None,
                safety_identifier=identifier,
                evidence_tool=lambda request: {},
            )
            model.discard_conversation(identifier)
            retry = model.respond(
                history=(
                    UatConversationMessage(role="user", content="first"),
                    UatConversationMessage(role="assistant", content="local answer"),
                ),
                user_text="retry",
                latest_evidence=None,
                safety_identifier=identifier,
                evidence_tool=lambda request: {},
            )

        self.assertEqual(retry.answer_text, "retry")
        self.assertEqual(transport.deleted_threads, ["thread_1"])
        self.assertEqual(len(transport.thread_starts), 2)
        self.assertIn(
            "formowl_recovery_history",
            transport.turn_calls[1]["additional_context"],
        )

    def test_thread_lru_deletes_oldest_inactive_thread(self) -> None:
        transport = _RecordingCodexTransport(
            [
                {"final_message": _decision(answer_text="one")},
                {"final_message": _decision(answer_text="two")},
                {"final_message": _decision(answer_text="three")},
            ]
        )
        with tempfile.TemporaryDirectory() as workspace:
            model = CodexAppServerConversationModel(
                transport,
                workspace_dir=workspace,
                max_threads=2,
            )
            for identifier in ("one", "two", "three"):
                model.respond(
                    history=(),
                    user_text=identifier,
                    latest_evidence=None,
                    safety_identifier=identifier,
                    evidence_tool=lambda request: {},
                )
            model.close()
        self.assertEqual(transport.deleted_threads, ["thread_1"])
        self.assertTrue(transport.closed)

    def test_stdio_transport_performs_v2_dynamic_tool_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trace_path = root / "trace.jsonl"
            transport = CodexAppServerStdioTransport(
                command=(
                    sys.executable,
                    "-u",
                    "-c",
                    _FAKE_APP_SERVER,
                    str(trace_path),
                ),
                cwd=root / "workspace",
                codex_home=root / "codex-home",
                timeout_seconds=5,
                environment={"PATH": os.environ.get("PATH", "")},
                attest_runtime=False,
            )
            try:
                thread = transport.start_thread(
                    model=None,
                    cwd=root / "workspace",
                    base_instructions="base",
                    developer_instructions="developer",
                    dynamic_tools=(
                        {
                            "type": "function",
                            "name": "search_formowl_evidence",
                            "description": "Search evidence.",
                            "inputSchema": {
                                "type": "object",
                                "additionalProperties": False,
                            },
                        },
                    ),
                )
                tool_calls = []

                def tool_handler(tool_name, arguments):
                    tool_calls.append((tool_name, dict(arguments)))
                    return {"status": "ok", "results": [{"content": "bounded"}]}

                turn = transport.run_turn(
                    thread_id=thread.thread_id,
                    user_text="find evidence",
                    additional_context={"prior": {"kind": "untrusted", "value": "prior evidence"}},
                    output_schema={
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                    },
                    reasoning_effort="low",
                    client_metadata={"surface": "test"},
                    tool_handler=tool_handler,
                )
                transport.delete_thread(thread.thread_id)
            finally:
                transport.close()

            trace = [
                json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(thread.model_name, "gpt-test-stdio")
        self.assertEqual(
            turn.final_message,
            _decision(
                answer_text="stdio tool complete",
                display_format="table",
            ),
        )
        self.assertEqual(tool_calls[0][0], "search_formowl_evidence")
        self.assertEqual(tool_calls[0][1]["required_terms"], ["ID-42"])
        self.assertEqual(turn.tool_invocations[0].thread_id, "thread_stdio")
        self.assertEqual(turn.tool_invocations[0].turn_id, "turn_stdio")
        self.assertEqual(turn.tool_invocations[0].call_id, "call_stdio")
        initialize = next(item for item in trace if item.get("method") == "initialize")
        self.assertTrue(initialize["params"]["capabilities"]["experimentalApi"])
        thread_start = next(item for item in trace if item.get("method") == "thread/start")
        self.assertEqual(thread_start["params"]["sandbox"], "read-only")
        self.assertFalse(thread_start["params"]["ephemeral"])
        self.assertNotIn("runtimeWorkspaceRoots", thread_start["params"])
        self.assertNotIn("historyMode", thread_start["params"])
        self.assertNotIn("environments", thread_start["params"])
        self.assertEqual(
            thread_start["params"]["dynamicTools"][0]["name"],
            "search_formowl_evidence",
        )
        turn_start = next(item for item in trace if item.get("method") == "turn/start")
        self.assertNotIn("runtimeWorkspaceRoots", turn_start["params"])
        self.assertNotIn("environments", turn_start["params"])
        self.assertNotIn("responsesapiClientMetadata", turn_start["params"])
        self.assertEqual(
            turn_start["params"]["sandboxPolicy"]["type"],
            "readOnly",
        )
        self.assertFalse(turn_start["params"]["sandboxPolicy"]["networkAccess"])
        tool_response = next(item for item in trace if item.get("id") == "server_tool_1")
        self.assertTrue(tool_response["result"]["success"])
        self.assertEqual(
            tool_response["result"]["contentItems"][0]["type"],
            "inputText",
        )

    def test_stdio_transport_rejects_mismatched_turn_and_duplicate_call_id(self) -> None:
        for scenario, expected_error, expected_tool_calls in (
            ("mismatched_turn", "does not match active turn", 0),
            ("duplicate_call", "was duplicated", 1),
        ):
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    transport = CodexAppServerStdioTransport(
                        command=(
                            sys.executable,
                            "-u",
                            "-c",
                            _FAKE_APP_SERVER_TOOL_PROTOCOL_VIOLATION,
                            scenario,
                        ),
                        cwd=root / "workspace",
                        codex_home=root / "codex-home",
                        timeout_seconds=5,
                        environment={"PATH": os.environ.get("PATH", "")},
                        attest_runtime=False,
                    )
                    tool_calls = []
                    try:
                        thread = transport.start_thread(
                            model=None,
                            cwd=root / "workspace",
                            base_instructions="base",
                            developer_instructions="developer",
                            dynamic_tools=(),
                        )
                        with self.assertRaisesRegex(RuntimeError, expected_error):
                            transport.run_turn(
                                thread_id=thread.thread_id,
                                user_text="find evidence",
                                additional_context={},
                                output_schema={
                                    "type": "object",
                                    "additionalProperties": False,
                                },
                                reasoning_effort="low",
                                client_metadata={"surface": "test"},
                                tool_handler=lambda tool_name, arguments: (
                                    tool_calls.append((tool_name, dict(arguments)))
                                    or {"status": "ok", "results": []}
                                ),
                            )
                    finally:
                        transport.close()
                self.assertEqual(len(tool_calls), expected_tool_calls)

    def test_codex_command_disables_non_formowl_capabilities(self) -> None:
        command = build_hardened_codex_app_server_command("codex")

        self.assertEqual(command[:4], ("codex", "app-server", "--listen", "stdio://"))
        disabled = {
            command[index + 1] for index, value in enumerate(command[:-1]) if value == "--disable"
        }
        self.assertTrue(
            {
                "apps",
                "browser_use",
                "computer_use",
                "hooks",
                "image_generation",
                "multi_agent",
                "plugins",
                "remote_plugin",
                "shell_tool",
                "unified_exec",
            }.issubset(disabled)
        )
        self.assertIn('sandbox_mode="read-only"', command)
        self.assertNotIn('sandbox_mode="danger-full-access"', command)
        self.assertIn("mcp_servers={}", command)
        self.assertNotIn("OPENAI_API_KEY", " ".join(command))

    def test_codex_proxy_command_uses_only_private_unix_socket(self) -> None:
        command = build_codex_app_server_proxy_command(
            socket_path="/run/formowl-codex/app-server.sock",
            python_command="/usr/bin/python3",
            proxy_script="/opt/formowl/python/formowl_mail/codex_unix_socket_proxy.py",
        )

        self.assertEqual(
            command,
            (
                "/usr/bin/python3",
                "/opt/formowl/python/formowl_mail/codex_unix_socket_proxy.py",
                "--socket",
                "/run/formowl-codex/app-server.sock",
            ),
        )

    def test_prepare_codex_runtime_uses_stdin_and_sanitized_environment(self) -> None:
        secret = "super-secret-key"
        with tempfile.TemporaryDirectory() as temp_dir:

            def fake_login(*_args, **kwargs):
                auth_path = Path(kwargs["env"]["CODEX_HOME"]) / "auth.json"
                auth_path.write_text('{"auth_mode":"apikey"}\n', encoding="utf-8")
                auth_path.chmod(0o600)
                return subprocess.CompletedProcess([], 0)

            with mock.patch.dict(
                os.environ,
                {
                    "PATH": os.environ.get("PATH", ""),
                    "OPENAI_API_KEY": "ambient-secret",
                    "UNRELATED_PRIVATE_VALUE": "do-not-inherit",
                },
                clear=True,
            ):
                with mock.patch(
                    "formowl_mail.human_uat_orchestrator.subprocess.run",
                    side_effect=fake_login,
                ) as run:
                    paths = prepare_codex_runtime_state(
                        codex_command="codex",
                        state_dir=Path(temp_dir) / "runtime",
                        api_key=secret,
                    )
                    config = (paths.codex_home / "config.toml").read_text(encoding="utf-8")
                    validated_paths = validate_codex_runtime_state(paths.state_dir)

        positional = run.call_args.args
        keyword = run.call_args.kwargs
        self.assertNotIn(secret, " ".join(positional[0]))
        self.assertEqual(keyword["input"], secret + "\n")
        self.assertNotIn("OPENAI_API_KEY", keyword["env"])
        self.assertNotIn("UNRELATED_PRIVATE_VALUE", keyword["env"])
        self.assertEqual(keyword["env"]["HOME"], keyword["env"]["CODEX_HOME"])
        self.assertEqual(paths.codex_home, paths.state_dir / "codex-home")
        self.assertEqual(paths.workspace, paths.state_dir / "codex-workspace")
        self.assertEqual(paths.login_method, "api")
        self.assertIn('sandbox_mode = "read-only"', config)
        self.assertIn("[mcp_servers]", config)
        self.assertEqual(config.count("[[skills.config]]"), 5)
        self.assertEqual(validated_paths, paths)

    def test_prepare_codex_runtime_copies_only_valid_chatgpt_auth_cache(self) -> None:
        secret = "never-print-this-token"
        auth_cache = json.dumps(
            {
                "OPENAI_API_KEY": None,
                "auth_mode": "chatgpt",
                "last_refresh": "2026-07-21T00:00:00Z",
                "tokens": {
                    "access_token": secret,
                    "account_id": "00000000-0000-0000-0000-000000000000",
                    "id_token": "id-token",
                    "refresh_token": "refresh-token",
                },
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = prepare_codex_runtime_state_from_auth_cache(
                state_dir=Path(temp_dir) / "runtime",
                auth_cache=auth_cache,
            )
            config = (paths.codex_home / "config.toml").read_text(encoding="utf-8")
            copied = json.loads((paths.codex_home / "auth.json").read_text(encoding="utf-8"))
            validated_paths = validate_codex_runtime_state(paths.state_dir)

        self.assertEqual(paths.login_method, "chatgpt")
        self.assertEqual(copied["tokens"]["access_token"], secret)
        self.assertIn('forced_login_method = "chatgpt"', config)
        self.assertEqual(validated_paths, paths)

    def test_prepare_codex_runtime_rejects_invalid_chatgpt_auth_without_leak(self) -> None:
        secret = "never-print-this-token"
        auth_cache = json.dumps(
            {
                "OPENAI_API_KEY": None,
                "auth_mode": "api",
                "tokens": {"access_token": secret},
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                ValueError,
                "^Codex ChatGPT auth cache is invalid$",
            ) as captured:
                prepare_codex_runtime_state_from_auth_cache(
                    state_dir=Path(temp_dir) / "runtime",
                    auth_cache=auth_cache,
                )
        self.assertNotIn(secret, str(captured.exception))

    def test_prepare_codex_runtime_errors_do_not_leak_key(self) -> None:
        secret = "super-secret-key"
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch(
                "formowl_mail.human_uat_orchestrator.subprocess.run",
                side_effect=OSError(f"{secret} private detail"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "^Codex authentication setup failed$",
                ) as captured:
                    prepare_codex_runtime_state(
                        codex_command="codex",
                        state_dir=Path(temp_dir) / "runtime",
                        api_key=secret,
                    )
        self.assertNotIn(secret, str(captured.exception))

    def test_prepare_codex_runtime_rejects_reused_or_symlinked_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reused = root / "reused"
            reused.mkdir()
            (reused / "foreign-auth.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be empty"):
                prepare_codex_runtime_state(
                    codex_command="codex",
                    state_dir=reused,
                    api_key="secret",
                )

            target = root / "target"
            target.mkdir()
            symlink = root / "symlink"
            symlink.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                prepare_codex_runtime_state(
                    codex_command="codex",
                    state_dir=symlink,
                    api_key="secret",
                )

    def test_runtime_attestation_rejects_enabled_skills_or_mcp(self) -> None:
        safe_config = {
            "forced_login_method": "chatgpt",
            "cli_auth_credentials_store": "file",
            "approval_policy": "never",
            "sandbox_mode": "read-only",
            "web_search": "disabled",
            "mcp_servers": {},
            "analytics": {"enabled": False},
            "apps": {
                "_default": {
                    "enabled": False,
                    "destructive_enabled": False,
                    "open_world_enabled": False,
                }
            },
            "features": {name: False for name in _CODEX_DISABLED_FEATURES},
            "agents": None,
            "hooks": None,
            "memories": None,
            "plugins": {},
            "marketplaces": {},
        }
        workspace = Path("/codex-state/codex-workspace")
        safe_skills = {
            "data": [
                {
                    "cwd": str(workspace),
                    "errors": [],
                    "skills": [{"name": "imagegen", "enabled": False}],
                }
            ]
        }
        _assert_hardened_codex_runtime(
            config_response={"config": safe_config, "layers": []},
            mcp_response={"data": [], "nextCursor": None},
            skills_response=safe_skills,
            apps_response={"data": [], "nextCursor": None},
            runtime_workspace=workspace,
        )

        enabled_skills = json.loads(json.dumps(safe_skills))
        enabled_skills["data"][0]["skills"][0]["enabled"] = True
        with self.assertRaisesRegex(RuntimeError, "enabled skills"):
            _assert_hardened_codex_runtime(
                config_response={"config": safe_config, "layers": []},
                mcp_response={"data": [], "nextCursor": None},
                skills_response=enabled_skills,
                apps_response={"data": [], "nextCursor": None},
                runtime_workspace=workspace,
            )
        with self.assertRaisesRegex(RuntimeError, "MCP servers"):
            _assert_hardened_codex_runtime(
                config_response={"config": safe_config, "layers": []},
                mcp_response={"data": [{"name": "unexpected"}], "nextCursor": None},
                skills_response=safe_skills,
                apps_response={"data": [], "nextCursor": None},
                runtime_workspace=workspace,
            )
        for feature in _CODEX_DISABLED_FEATURES:
            with self.subTest(feature=feature):
                unsafe_config = json.loads(json.dumps(safe_config))
                unsafe_config["features"][feature] = True
                with self.assertRaisesRegex(RuntimeError, "enabled capabilities"):
                    _assert_hardened_codex_runtime(
                        config_response={"config": unsafe_config, "layers": []},
                        mcp_response={"data": [], "nextCursor": None},
                        skills_response=safe_skills,
                        apps_response={"data": [], "nextCursor": None},
                        runtime_workspace=workspace,
                    )


if __name__ == "__main__":
    unittest.main()
