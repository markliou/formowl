from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
from formowl_gateway import (
    PUBLIC_TOOL_SCHEMAS,
    SemanticMcpGateway,
    safe_workflow_error_envelope,
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
                "open_upload_session",
                "create_ingestion_job",
                "list_observations",
                "preview_graph_candidates",
                "query_effective_graph",
                "query_effective_graph_view",
                "query_mail_evidence",
                "answer_mail_case_progress",
                "request_graph_access",
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

    def test_missing_semantic_handlers_fail_without_synthesizing_domain_results(
        self,
    ) -> None:
        gateway = SemanticMcpGateway()

        upload = gateway.dispatch_tool(
            "open_upload_session",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "intent": "Upload sourced notes.",
            },
        )
        ingestion = gateway.dispatch_tool(
            "create_ingestion_job",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "asset_locator": "formowl://asset/asset_001",
            },
        )
        observations = gateway.dispatch_tool(
            "list_observations",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "asset_locator": "formowl://asset/asset_001",
            },
        )
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
        mail_query = gateway.dispatch_tool(
            "query_mail_evidence",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "query_text": "mail evidence",
                "mail_import_session_id": "mailimport_001",
            },
        )
        case_progress = gateway.dispatch_tool(
            "answer_mail_case_progress",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "case_id": "case_launch",
                "mail_import_session_id": "mailimport_001",
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
        access = gateway.dispatch_tool(
            "request_graph_access",
            {
                "workspace_id": "workspace_main",
                "requester_user_id": "user_yifan",
                "owner_user_id": "user_owner",
                "requested_scope": {"scope_type": "project", "scope_id": "formowl"},
                "requested_access_level": "evidence_snippet",
                "reason": "Review sourced project context.",
            },
        )
        draft = gateway.dispatch_tool(
            "generate_wiki_draft_from_graph_view",
            {"projection_spec_id": "projection_001", "requester_user_id": "user_yifan"},
        )

        results = [
            upload,
            ingestion,
            observations,
            preview,
            query,
            mail_query,
            case_progress,
            review,
            access,
            draft,
        ]
        for result in results:
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["data"]["error_code"], "handler_not_configured")
        self.assertNotIn("candidate_summaries", preview["data"])
        self.assertNotIn("access_request_id", access["data"])
        self.assertNotIn("audit_ref", review["data"])
        self.assertIn("deprecated_alias_use_query_effective_graph_view", query["warnings"])
        self.assertNotIn(
            "canonical_commit",
            str(
                [
                    upload,
                    ingestion,
                    observations,
                    preview,
                    query,
                    mail_query,
                    case_progress,
                    review,
                    access,
                    draft,
                ]
            ),
        )
        self.assertNotIn("raw_path", str(results))
        self.assertEqual(len(gateway.tool_call_logs), 10)

    def test_effective_graph_view_is_canonical_and_old_name_is_deprecated_alias(self) -> None:
        schemas = {schema["tool_name"]: schema for schema in PUBLIC_TOOL_SCHEMAS}

        self.assertEqual(
            schemas["query_effective_graph_view"]["compatibility"],
            {"status": "canonical"},
        )
        self.assertEqual(
            schemas["query_effective_graph"]["compatibility"],
            {
                "status": "deprecated_alias",
                "canonical_tool_name": "query_effective_graph_view",
            },
        )

        gateway = SemanticMcpGateway(
            retrieval_handler=lambda _payload: {
                "answer": "same governed answer",
                "citations": [],
                "visible_graph_snippets": [],
                "redaction_counts": {"hidden_records": 0},
            }
        )
        arguments = {
            "query_text": "delivery risk",
            "session_id": "session_alias",
            "workspace_id": "workspace_main",
            "requester_user_id": "user_alias",
        }
        canonical = gateway.dispatch_tool("query_effective_graph_view", arguments)
        alias = gateway.dispatch_tool("query_effective_graph", arguments)

        self.assertEqual(alias["data"], canonical["data"])
        self.assertNotIn("deprecated_alias_use_query_effective_graph_view", canonical["warnings"])
        self.assertIn("deprecated_alias_use_query_effective_graph_view", alias["warnings"])

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

        self.assertEqual(len(PUBLIC_TOOL_SCHEMAS), 11)
        self.assertEqual(
            {schema["workflow"] for schema in PUBLIC_TOOL_SCHEMAS},
            {
                "upload",
                "ingestion",
                "observation",
                "mail_evidence",
                "candidate_graph",
                "access",
                "wiki_projection",
            },
        )
        for schema in PUBLIC_TOOL_SCHEMAS:
            with self.subTest(tool_name=schema["tool_name"]):
                validate_public_gateway_payload(schema)
                self.assertIn("result_type", schema)
                self.assertIn("status_values", schema)
        self.assertTrue(no_raw_path_output)
        self.assertTrue(no_raw_sql_output)
        self.assertTrue(no_worker_internal_output)
        self.assertTrue(safe_error_envelope)

    def test_safe_workflow_error_envelopes_cover_public_workflows_without_echoing_raw_input(
        self,
    ) -> None:
        for workflow in {
            "upload",
            "ingestion",
            "observation",
            "candidate_graph",
            "mail_evidence",
            "access",
            "wiki_projection",
        }:
            with self.subTest(workflow=workflow):
                envelope = safe_workflow_error_envelope(
                    workflow=workflow,
                    tool_name="/srv/formowl/private/raw.txt",
                    error_code="select * from private_table worker_scratch",
                )
                rendered = str(envelope).lower()
                self.assertEqual(envelope["status"], "error")
                self.assertEqual(envelope["data"]["workflow"], workflow)
                self.assertNotIn("/srv/formowl", rendered)
                self.assertNotIn("select *", rendered)
                self.assertNotIn("worker_scratch", rendered)

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
