from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_gateway import (
    SemanticGatewaySession,
    SemanticMcpJsonRpcGateway,
    build_raw_path_raw_sql_worker_internal_leak_transcript,
    containerized_semantic_mcp_gateway_smoke,
    end_to_end_raw_path_raw_sql_worker_internal_leak_transcript,
    session_auth_and_audit_store_integration,
    standards_compliant_mcp_gateway_transport,
)


class SemanticMcpJsonRpcGatewayTests(unittest.TestCase):
    def test_standards_compliant_mcp_gateway_transport_initialize_and_tool_list(
        self,
    ) -> None:
        gateway = SemanticMcpJsonRpcGateway(
            session=SemanticGatewaySession(
                session_id="session_001",
                actor_user_id="user_yifan",
                workspace_id="workspace_main",
            )
        )

        initialized = gateway.handle_json_rpc(
            {"jsonrpc": "2.0", "id": "init_001", "method": "initialize"}
        )
        tools = gateway.handle_json_rpc(
            {"jsonrpc": "2.0", "id": "tools_001", "method": "tools/list"}
        )

        standards_compliant_mcp_gateway_transport_marker = (
            standards_compliant_mcp_gateway_transport()
            == ("jsonrpc_2_0", "initialize", "tools/list", "tools/call")
        )
        self.assertTrue(standards_compliant_mcp_gateway_transport_marker)
        self.assertEqual(initialized["jsonrpc"], "2.0")
        self.assertEqual(initialized["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(
            {tool["name"] for tool in tools["result"]["tools"]},
            {
                "open_upload_session",
                "create_ingestion_job",
                "list_observations",
                "preview_graph_candidates",
                "query_effective_graph",
                "request_graph_access",
                "submit_graph_review_decision",
                "generate_wiki_draft_from_graph_view",
            },
        )
        self.assertEqual(len(gateway.leak_transcript()), 2)

    def test_tools_call_binds_session_and_records_hash_only_transcript(self) -> None:
        gateway = SemanticMcpJsonRpcGateway(
            session=SemanticGatewaySession(
                session_id="session_001",
                actor_user_id="user_yifan",
                workspace_id="workspace_main",
            )
        )

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "call_001",
                "method": "tools/call",
                "params": {
                    "name": "query_effective_graph",
                    "arguments": {"query_text": "delivery risk"},
                },
            }
        )
        transcript = gateway.leak_transcript()

        session_auth_and_audit_store_integration_marker = (
            session_auth_and_audit_store_integration()
            == "session_context_bound_to_json_rpc_transcript_hashes"
        )
        self.assertTrue(session_auth_and_audit_store_integration_marker)
        self.assertFalse(result["result"]["isError"])
        self.assertEqual(
            result["result"]["session"]["actor_user_id"],
            "user_yifan",
        )
        self.assertEqual(set(transcript[0]), {"method", "request_hash", "response_hash", "status"})
        self.assertNotIn("delivery risk", str(transcript))

    def test_forbidden_tool_calls_return_safe_json_rpc_errors(self) -> None:
        gateway = SemanticMcpJsonRpcGateway()

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "attack_001",
                "method": "tools/call",
                "params": {
                    "name": "direct_database_query_tool",
                    "arguments": {"sql": "select * from private_table"},
                },
            }
        )

        rendered = str(result).lower()
        self.assertTrue(result["result"]["isError"])
        self.assertNotIn("select *", rendered)
        self.assertNotIn("private_table", rendered)

    def test_end_to_end_raw_path_raw_sql_worker_internal_leak_transcript(self) -> None:
        transcript_packet = build_raw_path_raw_sql_worker_internal_leak_transcript()
        alias_packet = end_to_end_raw_path_raw_sql_worker_internal_leak_transcript()

        end_to_end_raw_path_raw_sql_worker_internal_leak_transcript_marker = (
            transcript_packet["raw_request_retained"] is False
            and transcript_packet["safe_response_count"] == 3
        )
        self.assertTrue(end_to_end_raw_path_raw_sql_worker_internal_leak_transcript_marker)
        self.assertEqual(alias_packet, transcript_packet)
        rendered = str(transcript_packet).lower()
        self.assertNotIn("/srv/", rendered)
        self.assertNotIn("/tmp/", rendered)
        self.assertNotIn("select *", rendered)
        self.assertNotIn("worker_scratch", rendered)

    def test_containerized_semantic_mcp_gateway_smoke(self) -> None:
        smoke = containerized_semantic_mcp_gateway_smoke()

        containerized_semantic_mcp_gateway_smoke_marker = smoke["smoke_passed"]
        self.assertTrue(containerized_semantic_mcp_gateway_smoke_marker)
        self.assertTrue(smoke["metrics"]["transport_initialized"])
        self.assertTrue(smoke["metrics"]["tools_listed"])
        self.assertTrue(smoke["metrics"]["tool_call_succeeded"])
        self.assertTrue(smoke["metrics"]["session_bound"])
        self.assertTrue(smoke["metrics"]["hash_only_transcript"])
        self.assertTrue(smoke["metrics"]["raw_leak_probe_passed"])
        self.assertFalse(smoke["claim_boundary"]["supports_production_adapter_ready_claim"])
        rendered = str(smoke).lower()
        self.assertNotIn("/srv/", rendered)
        self.assertNotIn("/tmp/", rendered)
        self.assertNotIn("select *", rendered)
        self.assertNotIn("worker_scratch", rendered)


if __name__ == "__main__":
    unittest.main()
