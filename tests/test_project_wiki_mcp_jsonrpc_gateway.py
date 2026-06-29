from __future__ import annotations

from pathlib import Path
import unittest

import _paths
from formowl_gateway import McpServerJsonRpcGateway, SemanticGatewaySession
from formowl_project_mcp import create_default_server as create_project_server
from formowl_wiki_mcp import create_default_server as create_wiki_server

from test_wiki_mcp import sample_context_package


WORK_ITEM_REF = {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123",
}


class ProjectWikiMcpJsonRpcGatewayTests(unittest.TestCase):
    def test_project_mcp_json_rpc_preserves_context_snapshot_behavior(self) -> None:
        temp_dir = _paths.fresh_test_dir("project-jsonrpc-context")
        gateway = McpServerJsonRpcGateway(
            create_project_server(temp_dir),
            session=SemanticGatewaySession(
                session_id="project_jsonrpc_session",
                actor_user_id="project_actor",
                workspace_id="workspace_formowl",
            ),
        )

        initialized = gateway.handle_json_rpc(
            {"jsonrpc": "2.0", "id": "init", "method": "initialize"}
        )
        tools = gateway.handle_json_rpc({"jsonrpc": "2.0", "id": "tools", "method": "tools/list"})
        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "context",
                "method": "tools/call",
                "params": {
                    "name": "get_work_item_context",
                    "arguments": {
                        "source_ref": WORK_ITEM_REF,
                        "include_comments": True,
                        "include_activities": True,
                        "include_relations": True,
                        "include_attachments": True,
                        "create_evidence_snapshot": True,
                    },
                },
            }
        )

        self.assertEqual(initialized["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(
            initialized["result"]["serverInfo"]["name"],
            "formowl-project-mcp-jsonrpc",
        )
        self.assertIn(
            "get_work_item_context",
            {tool["name"] for tool in tools["result"]["tools"]},
        )
        self.assertFalse(result["result"]["isError"])
        self.assertEqual(result["result"]["session"]["actor_user_id"], "project_actor")
        envelope = result["result"]["content"][0]["json"]
        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["result_type"], "work_item_context")
        self.assertEqual(envelope["context_package"]["context_type"], "work_item_context")
        self.assertEqual(len(envelope["evidence_snapshot_ids"]), 1)
        self.assertIn("reviewable ADR", envelope["context_package"]["context_markdown"])
        metadata_files = list(Path(temp_dir).glob("raw/evidence/openproject/*/*/*/*/metadata.json"))
        self.assertEqual(len(metadata_files), 1)
        self.assertEqual(
            [set(entry) for entry in gateway.leak_transcript()],
            [
                {"method", "request_hash", "response_hash", "status"},
                {"method", "request_hash", "response_hash", "status"},
                {"method", "request_hash", "response_hash", "status"},
            ],
        )
        self.assertNotIn("reviewable ADR", str(gateway.leak_transcript()))

    def test_wiki_mcp_json_rpc_preserves_draft_and_proposal_only_publish(self) -> None:
        temp_dir = _paths.fresh_test_dir("wiki-jsonrpc-draft")
        gateway = McpServerJsonRpcGateway(create_wiki_server(temp_dir))

        draft_response = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "draft",
                "method": "tools/call",
                "params": {
                    "name": "generate_wiki_draft",
                    "arguments": {
                        "page_type": "adr",
                        "title": "JSON RPC Wiki Draft",
                        "context_package": sample_context_package(),
                    },
                },
            }
        )
        draft = draft_response["result"]["content"][0]["json"]
        draft_id = draft["data"]["draft_id"]
        publish_response = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "publish",
                "method": "tools/call",
                "params": {
                    "name": "publish_wiki_page",
                    "arguments": {
                        "draft_id": draft_id,
                        "target": {
                            "target_system": "openproject_wiki",
                            "project_id": "formowl",
                            "page_slug": "json-rpc-wiki-draft",
                        },
                        "require_review": True,
                    },
                },
            }
        )

        publish = publish_response["result"]["content"][0]["json"]
        self.assertFalse(draft_response["result"]["isError"])
        self.assertEqual(draft["status"], "ok")
        self.assertIn("source_refs:", draft["data"]["markdown"])
        self.assertFalse(publish_response["result"]["isError"])
        self.assertEqual(publish["status"], "pending_review")
        self.assertIn("No wiki page was published", publish["warnings"][0])
        self.assertEqual(len(list((Path(temp_dir) / "wiki" / "drafts").glob("*.json"))), 1)

    def test_json_rpc_gateway_rejects_unsafe_payload_before_tool_side_effects(self) -> None:
        temp_dir = _paths.fresh_test_dir("wiki-jsonrpc-unsafe-payload")
        gateway = McpServerJsonRpcGateway(create_wiki_server(temp_dir))

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "unsafe",
                "method": "tools/call",
                "params": {
                    "name": "generate_wiki_draft",
                    "arguments": {
                        "page_type": "adr",
                        "title": "Unsafe Draft",
                        "context_package": {
                            **sample_context_package(),
                            "context_markdown": "Read /tmp/private-source.txt",
                        },
                    },
                },
            }
        )

        rendered = str(result)
        envelope = result["result"]["content"][0]["json"]
        self.assertTrue(result["result"]["isError"])
        self.assertEqual(envelope["status"], "error")
        self.assertEqual(envelope["data"]["error_code"], "unsafe_tool_payload")
        self.assertNotIn("/tmp/private-source.txt", rendered)
        self.assertEqual(list((Path(temp_dir) / "wiki" / "drafts").glob("*.json")), [])
        self.assertNotIn("/tmp/private-source.txt", str(gateway.leak_transcript()))

    def test_json_rpc_gateway_returns_protocol_errors_without_raw_request_leak(self) -> None:
        gateway = McpServerJsonRpcGateway(
            create_project_server(_paths.fresh_test_dir("bad-jsonrpc"))
        )

        invalid = gateway.handle_json_rpc(
            {"jsonrpc": "1.0", "id": "bad", "method": "tools/call", "path": "/tmp/private"}
        )
        unknown = gateway.handle_json_rpc(
            {"jsonrpc": "2.0", "id": "unknown", "method": "backend/raw_sql"}
        )

        self.assertEqual(invalid["error"]["message"], "invalid_request")
        self.assertEqual(unknown["error"]["message"], "method_not_found")
        self.assertNotIn("/tmp/private", str(invalid))
        self.assertNotIn("/tmp/private", str(gateway.leak_transcript()))


if __name__ == "__main__":
    unittest.main()
