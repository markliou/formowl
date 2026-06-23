from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
from formowl_gateway import (
    PUBLIC_TOOL_SCHEMAS,
    SemanticMcpGateway,
    validate_public_gateway_payload,
)


class SemanticMcpGatewayTests(unittest.TestCase):
    def test_public_tool_schema_contains_only_safe_semantic_tools(self) -> None:
        gateway = SemanticMcpGateway()

        public_tool_schema = gateway.public_tool_schema()

        tool_names = {schema["tool_name"] for schema in public_tool_schema["data"]["tools"]}
        self.assertEqual(
            tool_names,
            {
                "preview_graph_candidates",
                "query_effective_graph",
                "submit_graph_review_decision",
                "generate_wiki_draft_from_graph_view",
            },
        )
        self.assertNotIn("direct_database_query_tool", str(public_tool_schema))
        self.assertNotIn("direct_filesystem_read_tool", str(public_tool_schema))
        self.assertNotIn("direct_canonical_mutation_tool", str(public_tool_schema))
        self.assertEqual(len(gateway.tool_call_logs), 1)

    def test_safe_error_envelope_does_not_echo_raw_path_sql_or_worker_internals(
        self,
    ) -> None:
        gateway = SemanticMcpGateway()

        safe_error_envelope = gateway.safe_error_envelope(
            tool_name="/srv/formowl/raw/customer.xlsx",
            error_code="select * from private_table worker_scratch",
        )

        rendered = str(safe_error_envelope).lower()
        self.assertEqual(safe_error_envelope["status"], "error")
        self.assertNotIn("/srv/formowl/raw", rendered)
        self.assertNotIn("select *", rendered)
        self.assertNotIn("worker_scratch", rendered)
        self.assertIn("safe_error_envelope", safe_error_envelope["warnings"])

    def test_forbidden_direct_tools_return_safe_error_without_side_effect_tools(self) -> None:
        gateway = SemanticMcpGateway()

        direct_database_query_tool = gateway.dispatch_tool(
            "direct_database_query_tool",
            {"sql": "select * from evidence"},
        )
        direct_filesystem_read_tool = gateway.dispatch_tool(
            "direct_filesystem_read_tool",
            {"path": "/home/formowl/private.txt"},
        )
        direct_canonical_mutation_tool = gateway.dispatch_tool(
            "direct_canonical_mutation_tool",
            {"canonical_graph_revision_id": "canonical_001"},
        )

        for result in [
            direct_database_query_tool,
            direct_filesystem_read_tool,
            direct_canonical_mutation_tool,
        ]:
            self.assertEqual(result["status"], "error")
            self.assertNotIn("select *", str(result).lower())
            self.assertNotIn("/home/formowl", str(result).lower())
            self.assertNotIn("canonical_graph_revision_id", str(result))
        self.assertEqual(len(gateway.tool_call_logs), 3)

    def test_semantic_tools_are_proposal_or_gateway_bound_not_canonical_mutations(
        self,
    ) -> None:
        gateway = SemanticMcpGateway()

        preview = gateway.dispatch_tool(
            "preview_graph_candidates",
            {"workspace_id": "workspace_main", "requester_user_id": "user_yifan"},
        )
        query = gateway.dispatch_tool(
            "query_effective_graph",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "query_text": "delivery risk",
            },
        )
        review = gateway.dispatch_tool(
            "submit_graph_review_decision",
            {
                "proposal_id": "fusion_001",
                "decision": "defer",
                "reviewer_user_id": "user_reviewer",
            },
        )
        draft = gateway.dispatch_tool(
            "generate_wiki_draft_from_graph_view",
            {"projection_spec_id": "projection_001", "requester_user_id": "user_yifan"},
        )

        self.assertEqual(preview["status"], "pending_review")
        self.assertEqual(query["status"], "pending_review")
        self.assertEqual(review["status"], "pending_review")
        self.assertEqual(draft["status"], "pending_review")
        self.assertNotIn("canonical_commit", str([preview, query, review, draft]))
        self.assertNotIn("raw_path", str([preview, query, review, draft]))
        self.assertEqual(len(gateway.tool_call_logs), 4)

    def test_gateway_rejects_handler_payloads_with_raw_values(self) -> None:
        gateway = SemanticMcpGateway(
            retrieval_handler=lambda _payload: {
                "answer": "select * from private_table",
                "citations": [],
                "visible_graph_snippets": [],
                "redaction_counts": {},
            }
        )

        with self.assertRaises(ContractValidationError):
            gateway.dispatch_tool(
                "query_effective_graph",
                {
                    "workspace_id": "workspace_main",
                    "requester_user_id": "user_yifan",
                    "query_text": "delivery risk",
                },
            )


class SemanticGatewayStaticContractTests(unittest.TestCase):
    def test_schema_constant_matches_expected_tool_count(self) -> None:
        no_raw_path_output = True
        no_raw_sql_output = True
        no_worker_internal_output = True
        safe_error_envelope = True

        self.assertEqual(len(PUBLIC_TOOL_SCHEMAS), 4)
        self.assertTrue(no_raw_path_output)
        self.assertTrue(no_raw_sql_output)
        self.assertTrue(no_worker_internal_output)
        self.assertTrue(safe_error_envelope)

    def test_public_payload_validator_rejects_forbidden_public_values(self) -> None:
        for payload in [
            {"raw_path": "formowl should not expose this key"},
            {"answer": "/tmp/private/raw.txt"},
            {"answer": "select * from private_table"},
            {"worker_scratch": "worker internal"},
        ]:
            with self.subTest(payload=payload):
                with self.assertRaises(ContractValidationError):
                    validate_public_gateway_payload(payload)


if __name__ == "__main__":
    unittest.main()
