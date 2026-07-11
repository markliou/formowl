from __future__ import annotations

from io import StringIO
import json
import unittest
from unittest.mock import patch

import _paths
from formowl_gateway import (
    McpJsonRpcEngine,
    McpServerJsonRpcGateway,
    SemanticGatewaySession,
    SemanticMcpJsonRpcGateway,
    run_jsonline_compat,
)
from formowl_project_mcp import create_default_server as create_project_server
from formowl_wiki_mcp import create_default_server as create_wiki_server


class McpProtocolInfrastructureTests(unittest.TestCase):
    def _session(self) -> SemanticGatewaySession:
        return SemanticGatewaySession(
            session_id="session_protocol_test",
            actor_user_id="user_protocol_test",
            workspace_id="workspace_protocol_test",
        )

    def test_project_wiki_and_semantic_gateways_share_one_jsonrpc_engine(self) -> None:
        temp_dir = _paths.fresh_test_dir("shared-jsonrpc-engine")
        gateways = [
            McpServerJsonRpcGateway(
                create_project_server(temp_dir / "project"), session=self._session()
            ),
            McpServerJsonRpcGateway(create_wiki_server(temp_dir / "wiki"), session=self._session()),
            SemanticMcpJsonRpcGateway(session=self._session()),
        ]

        for gateway in gateways:
            with self.subTest(gateway=type(gateway).__name__):
                self.assertIsInstance(gateway._engine, McpJsonRpcEngine)
                initialized = gateway.handle_json_rpc(
                    {"jsonrpc": "2.0", "id": "init", "method": "initialize"}
                )
                self.assertEqual(initialized["result"]["protocolVersion"], "2024-11-05")

    def test_project_wiki_error_envelopes_use_the_initialized_server_name_once(self) -> None:
        temp_dir = _paths.fresh_test_dir("shared-jsonrpc-server-name")
        gateways = (
            McpServerJsonRpcGateway(
                create_project_server(temp_dir / "project"), session=self._session()
            ),
            McpServerJsonRpcGateway(create_wiki_server(temp_dir / "wiki"), session=self._session()),
            McpServerJsonRpcGateway(
                create_project_server(temp_dir / "custom"),
                server_name="custom-compat",
                session=self._session(),
            ),
        )

        for gateway in gateways:
            initialized = gateway.handle_json_rpc(
                {"jsonrpc": "2.0", "id": "init", "method": "initialize"}
            )
            public_name = initialized["result"]["serverInfo"]["name"]
            tool_name = gateway.server.list_tools()[0]["name"]
            with patch.object(
                gateway.server,
                "call_tool",
                side_effect=RuntimeError("backend failed"),
            ):
                rejected = gateway.handle_json_rpc(
                    {
                        "jsonrpc": "2.0",
                        "id": "failed",
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": {}},
                    }
                )

            error = rejected["result"]["content"][0]["json"]
            self.assertTrue(rejected["result"]["isError"])
            self.assertEqual(error["data"]["server_name"], public_name)
            self.assertNotIn("formowl-formowl", public_name)
            self.assertNotIn("jsonrpc-jsonrpc", public_name)

    def test_default_jsonrpc_gateways_fail_closed_without_authenticated_session(self) -> None:
        temp_dir = _paths.fresh_test_dir("shared-jsonrpc-default-auth")
        gateways = (
            McpServerJsonRpcGateway(create_project_server(temp_dir / "project")),
            McpServerJsonRpcGateway(create_wiki_server(temp_dir / "wiki")),
            SemanticMcpJsonRpcGateway(),
        )

        for gateway in gateways:
            response = gateway.handle_json_rpc(
                {"jsonrpc": "2.0", "id": "init", "method": "initialize"}
            )
            self.assertEqual(response["error"]["code"], -32001)
            self.assertEqual(response["error"]["message"], "session_not_authenticated")

    def test_project_and_wiki_bind_gateway_identity_and_reject_forgery(self) -> None:
        temp_dir = _paths.fresh_test_dir("shared-jsonrpc-identity")
        cases = (
            (
                "project",
                create_project_server(temp_dir / "project"),
                "search_work_items",
                {"query": "risk"},
                temp_dir / "project" / "logs" / "project-mcp-tool-calls.jsonl",
            ),
            (
                "wiki",
                create_wiki_server(temp_dir / "wiki"),
                "search_wiki_pages",
                {"query": "risk"},
                temp_dir / "wiki" / "logs" / "wiki-mcp-tool-calls.jsonl",
            ),
        )

        for name, server, tool_name, arguments, log_path in cases:
            with self.subTest(server=name):
                gateway = McpServerJsonRpcGateway(server, session=self._session())
                accepted = gateway.handle_json_rpc(
                    {
                        "jsonrpc": "2.0",
                        "id": "accepted",
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments},
                    }
                )
                self.assertFalse(accepted["result"]["isError"])
                event = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
                self.assertEqual(event["session_id"], "session_protocol_test")
                self.assertEqual(event["actor_user_id"], "user_protocol_test")
                self.assertEqual(event["workspace_id"], "workspace_protocol_test")

                before = log_path.read_bytes()
                rejected = gateway.handle_json_rpc(
                    {
                        "jsonrpc": "2.0",
                        "id": "forged",
                        "method": "tools/call",
                        "params": {
                            "name": tool_name,
                            "arguments": {
                                **arguments,
                                "nested": {"actorUserId": "forged-user"},
                            },
                        },
                    }
                )
                self.assertTrue(rejected["result"]["isError"])
                error = rejected["result"]["content"][0]["json"]
                self.assertEqual(error["data"]["error_code"], "unsafe_tool_payload")
                self.assertEqual(log_path.read_bytes(), before)

    def test_shared_jsonline_runner_preserves_project_and_wiki_compatibility(self) -> None:
        temp_dir = _paths.fresh_test_dir("shared-jsonline-runner")
        for name, factory in (
            ("project", lambda: create_project_server(temp_dir / "project")),
            ("wiki", lambda: create_wiki_server(temp_dir / "wiki")),
        ):
            with self.subTest(server=name):
                output = StringIO()
                run_jsonline_compat(
                    factory,
                    input_stream=StringIO('{"method":"list_tools"}\n[]\n'),
                    output_stream=output,
                )
                responses = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertTrue(responses[0]["tools"])
                self.assertEqual(responses[1]["status"], "error")
                self.assertEqual(responses[1]["data"]["error_code"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
