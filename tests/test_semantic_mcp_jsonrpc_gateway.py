from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any
import unittest

import _paths  # noqa: F401
from _semantic_gateway_scenarios import (
    build_raw_path_raw_sql_worker_internal_leak_transcript,
    containerized_semantic_mcp_gateway_smoke,
)
from formowl_contract import sha256_json
from formowl_gateway import (
    SemanticMcpGateway,
    SemanticGatewaySession,
    SemanticMcpJsonRpcGateway,
    create_mail_upload_semantic_jsonrpc_gateway,
)
from formowl_gateway.remote import build_remote_tool_descriptors
from formowl_ingestion.storage import UploadSessionStore
from formowl_mail.exact import (
    AuthorizedSourceOccurrence,
    ExactInventoryItem,
    SourceOccurrenceProvider,
    execute_deterministic_source_occurrence_inventory,
)
from formowl_mail.semantic_plan import SemanticQueryPlan


class SemanticMcpJsonRpcGatewayTests(unittest.TestCase):
    def test_tools_list_exposes_canonical_and_deprecated_alias_policy(self) -> None:
        gateway = SemanticMcpJsonRpcGateway(
            session=SemanticGatewaySession(
                session_id="session_alias_discovery",
                actor_user_id="user_alias_discovery",
                workspace_id="workspace_main",
            )
        )

        listed = gateway.handle_json_rpc({"jsonrpc": "2.0", "id": "list", "method": "tools/list"})
        tools = {tool["name"]: tool for tool in listed["result"]["tools"]}

        self.assertIn("canonical API", tools["query_effective_graph_view"]["description"])
        self.assertIn(
            "deprecated compatibility alias", tools["query_effective_graph"]["description"]
        )
        self.assertIn("query_effective_graph_view", tools["query_effective_graph"]["description"])

    def test_transcript_records_tool_errors_and_permission_denials(self) -> None:
        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                mail_evidence_handler=lambda _input_data: {
                    "status": "permission_denied",
                    "evidence_snippets": [],
                    "citations": [],
                    "redaction_counts": {"hidden_records": 1},
                    "warnings": [],
                }
            ),
            session=SemanticGatewaySession(
                session_id="session_transcript_status",
                actor_user_id="user_transcript_status",
                workspace_id="workspace_main",
            ),
        )

        missing_handler = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "missing",
                "method": "tools/call",
                "params": {
                    "name": "create_ingestion_job",
                    "arguments": {
                        "asset_locator": "formowl://asset/asset_001",
                        "extractor_profile": "mail_archive_phase1",
                    },
                },
            }
        )
        denied = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "denied",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": "restricted evidence",
                        "mail_import_session_id": "mailimport_001",
                    },
                },
            }
        )

        self.assertTrue(missing_handler["result"]["isError"])
        self.assertFalse(denied["result"]["isError"])
        self.assertEqual(
            [entry["status"] for entry in gateway.leak_transcript()],
            ["error", "permission_denied"],
        )

    def test_query_effective_graph_view_is_discoverable_and_dispatches_kg_first_payload(
        self,
    ) -> None:
        handler_calls: list[dict[str, Any]] = []

        def retrieval_handler(input_data: dict[str, Any]) -> dict[str, Any]:
            handler_calls.append(input_data)
            return {
                "answer": "KG-first answer",
                "graph_hits": [
                    {
                        "graph_object_id": "node_optoma_decision",
                        "object_type": "candidate_decision_frame",
                        "source_observation_ids": ["obs_optoma_mail"],
                        "evidence_locators": ["formowl://observation/obs_optoma_mail"],
                    }
                ],
                "evidence": [
                    {
                        "observation_id": "obs_optoma_mail",
                        "evidence_locator": "formowl://observation/obs_optoma_mail",
                    }
                ],
                "fallback_used": False,
                "fallback_reason": None,
                "evidence_coverage": 1.0,
                "candidate_graph_proposal_seeds": [],
                "citations": [],
                "visible_graph_snippets": [],
                "redaction_counts": {"hidden_records": 0},
                "warnings": [],
            }

        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(retrieval_handler=retrieval_handler),
            session=SemanticGatewaySession(
                session_id="session_kg_first",
                actor_user_id="user_pm",
                workspace_id="workspace_main",
            ),
        )

        listed = gateway.handle_json_rpc({"jsonrpc": "2.0", "id": "list", "method": "tools/list"})
        tool_names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertIn("query_effective_graph_view", tool_names)

        called = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "call",
                "method": "tools/call",
                "params": {
                    "name": "query_effective_graph_view",
                    "arguments": {"query_text": "Optoma quotation decision"},
                },
            }
        )

        self.assertFalse(called["result"]["isError"])
        payload = called["result"]["content"][0]["json"]["data"]
        self.assertFalse(payload["fallback_used"])
        self.assertEqual(payload["evidence_coverage"], 1.0)
        self.assertEqual(payload["graph_hits"][0]["graph_object_id"], "node_optoma_decision")
        self.assertEqual(handler_calls[0]["requester_user_id"], "user_pm")
        self.assertEqual(handler_calls[0]["workspace_id"], "workspace_main")
        self.assertEqual(handler_calls[0]["session_id"], "session_kg_first")

    def test_query_effective_graph_view_rejects_malformed_arguments_before_dispatch(
        self,
    ) -> None:
        handler_calls: list[dict[str, Any]] = []

        def retrieval_handler(input_data: dict[str, Any]) -> dict[str, Any]:
            handler_calls.append(input_data)
            return {"answer": "unexpected"}

        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(retrieval_handler=retrieval_handler),
            session=SemanticGatewaySession(
                session_id="session_kg_first_validation",
                actor_user_id="user_pm",
                workspace_id="workspace_main",
            ),
        )
        tools = gateway.handle_json_rpc({"jsonrpc": "2.0", "id": "list", "method": "tools/list"})
        tool_schema = next(
            tool
            for tool in tools["result"]["tools"]
            if tool["name"] == "query_effective_graph_view"
        )["inputSchema"]

        self.assertEqual(tool_schema["required"], ["query_text"])
        self.assertEqual(
            tool_schema["properties"],
            {
                "cursor": {"type": "string"},
                "exact_field": {"type": "string"},
                "exact_inventory_kind": {"type": "string"},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
                "query_text": {"type": "string"},
            },
        )
        self.assertFalse(tool_schema["additionalProperties"])

        valid = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "valid_optional_paging",
                "method": "tools/call",
                "params": {
                    "name": "query_effective_graph_view",
                    "arguments": {
                        "query_text": "Optoma",
                        "exact_inventory_kind": "mail_message_occurrence",
                        "page_size": 25,
                        "cursor": "opaque_cursor_v1",
                    },
                },
            }
        )
        self.assertFalse(valid["result"]["isError"])
        self.assertEqual(
            handler_calls[0]["exact_inventory_kind"],
            "mail_message_occurrence",
        )
        self.assertEqual(handler_calls[0]["page_size"], 25)
        self.assertEqual(handler_calls[0]["cursor"], "opaque_cursor_v1")
        handler_calls.clear()

        malformed_arguments = (
            {},
            {"query_text": ""},
            {"query_text": 42},
            {"query_text": "Optoma", "page_size": 0},
            {"query_text": "Optoma", "page_size": 101},
            {"query_text": "Optoma", "page_size": True},
            {"query_text": "Optoma", "page_size": "25"},
            {"query_text": "Optoma", "cursor": 42},
            {"query_text": "Optoma", "cursor": ""},
            {"query_text": "Optoma", "exact_field": 42},
            {"query_text": "Optoma", "exact_inventory_kind": 42},
            {"query_text": "Optoma", "workspace_id": "workspace_other"},
        )
        for index, arguments in enumerate(malformed_arguments):
            response = gateway.handle_json_rpc(
                {
                    "jsonrpc": "2.0",
                    "id": f"invalid_{index}",
                    "method": "tools/call",
                    "params": {
                        "name": "query_effective_graph_view",
                        "arguments": arguments,
                    },
                }
            )
            self.assertTrue(response["result"]["isError"])
            self.assertEqual(
                response["result"]["content"][0]["json"]["data"]["error_code"],
                "unsafe_tool_payload",
            )
        self.assertEqual(handler_calls, [])

    def test_terminal_partial_exact_inventory_reports_incomplete_coverage(self) -> None:
        identifier_hash = sha256_json("participant")
        safe_item = ExactInventoryItem(
            item_hash=sha256_json("occurrence"),
            cited_observation_hashes=(sha256_json("citation"),),
            governed_references=((sha256_json("citation"), sha256_json("lineage")),),
            matched_normalized_value_hashes=(identifier_hash,),
        ).to_safe_dict()
        self.assertEqual(safe_item["matched_normalized_value_hashes"], [identifier_hash])
        plan = SemanticQueryPlan(
            query_hash=sha256_json("list all participant mail"),
            query_class="exact_set_or_inventory",
            source_kind="authorized_mail_observation",
            source_scope_ids=("scope_authorized",),
            workspace_id="workspace_main",
            requester_user_id="user_pm",
            required_permissions=("evidence_snippet", "graph_snippet"),
            user_graph_revision_id="user_graph_v1",
            canonical_graph_revision_id="canonical_graph_v1",
            ontology_revision_id="ontology_v1",
            assembly_policy_id="assembly_v1",
            allowed_paths=(),
            seed_node_ids=(),
            max_hops=0,
            max_fanout=1,
            candidate_limit=1,
            result_limit=20,
            evidence_budget=1,
            time_budget_ms=1_500,
            repair_budget=1,
            repair_attempt_count=0,
            claim_strength="complete_authorized_scope",
            exact_operation="inventory_with_count",
            exact_inventory_kind="mail_message_occurrence",
            exact_filter_term_hashes=(identifier_hash,),
            exact_identifier_term_hashes=(identifier_hash,),
            exact_normalized_field="participant.any.local_part",
            exact_predicate="source_occurrence_involves",
            exact_operator="case_insensitive_exact",
        )
        provider = SourceOccurrenceProvider(
            provider_id="mail_source_occurrence_provider_v1",
            inventory_kind_alias="mail_observation",
            resource_kind="mail_message_occurrence",
            normalized_field="participant.any.local_part",
            predicate="source_occurrence_involves",
            operator="case_insensitive_exact",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            source_scope_ids=("scope_authorized",),
            authorized_scope_fingerprint=sha256_json("authorized_scope"),
            occurrences=(
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json("occurrence"),
                    value_bindings=(
                        (
                            identifier_hash,
                            identifier_hash,
                            sha256_json("citation"),
                            sha256_json("lineage"),
                        ),
                    ),
                ),
            ),
            unresolved_count=1,
        )

        result = execute_deterministic_source_occurrence_inventory(
            plan=plan,
            provider=provider,
            expected_authorized_scope_fingerprint=provider.authorized_scope_fingerprint,
            page_size=20,
            cursor=None,
        )

        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.source_occurrence_page["coverage_status"], "incomplete")
        self.assertIsNone(result.source_occurrence_page["next_cursor"])

        terminal_payload = {
            "status": result.status,
            "exact_inventory": {
                "status": result.status,
                "query_class": plan.query_class,
                "plan": {"plan_fingerprint": result.plan_fingerprint},
                "total_count": result.exact_count,
                "returned_count": result.returned_item_count,
                "coverage_status": result.source_occurrence_page["coverage_status"],
                "next_cursor": result.source_occurrence_page["next_cursor"],
                "redacted_count": result.source_occurrence_page["redacted_count"],
                "unsupported_count": result.source_occurrence_page["unsupported_count"],
                "unresolved_count": result.source_occurrence_page["unresolved_count"],
                "duplicate_policy": result.source_occurrence_page["duplicate_policy"],
                "ambiguous_identifier_count": result.source_occurrence_page[
                    "ambiguous_identifier_count"
                ],
                "items": [safe_item],
            },
            "citations": list(result.items[0].cited_observation_hashes),
            "redaction_counts": {"redacted_value_count": 0},
        }
        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                retrieval_handler=lambda _input_data: terminal_payload
            ),
            session=SemanticGatewaySession(
                session_id="session_terminal_inventory",
                actor_user_id="user_pm",
                workspace_id="workspace_main",
            ),
        )
        response = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "terminal_inventory",
                "method": "tools/call",
                "params": {
                    "name": "query_effective_graph_view",
                    "arguments": {"query_text": "list all participant mail"},
                },
            }
        )

        self.assertFalse(response["result"]["isError"])
        structured_content = response["result"]["content"][0]["json"]
        terminal_inventory = structured_content["data"]["exact_inventory"]
        self.assertIn("next_cursor", terminal_inventory)
        self.assertIsNone(terminal_inventory["next_cursor"])

        output_schema = next(
            tool.outputSchema
            for tool in build_remote_tool_descriptors(
                required_scope="formowl.use",
                enabled_tool_names={"whoami", "query_effective_graph_view"},
            )
            if tool.name == "query_effective_graph_view"
        )
        exact_inventory_schema = output_schema["properties"]["data"]["properties"][
            "exact_inventory"
        ]
        self.assertIn("next_cursor", exact_inventory_schema["required"])
        self.assertEqual(
            exact_inventory_schema["properties"]["next_cursor"],
            {"type": ["string", "null"]},
        )

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
                "query_effective_graph_view",
                "query_mail_evidence",
                "answer_mail_case_progress",
                "request_graph_access",
                "submit_graph_review_decision",
                "generate_wiki_draft_from_graph_view",
            },
        )
        tools_by_name = {tool["name"]: tool for tool in tools["result"]["tools"]}
        upload_schema = tools_by_name["open_upload_session"]["inputSchema"]
        mail_schema = tools_by_name["query_mail_evidence"]["inputSchema"]
        access_schema = tools_by_name["request_graph_access"]["inputSchema"]
        review_schema = tools_by_name["submit_graph_review_decision"]["inputSchema"]
        self.assertFalse(upload_schema["additionalProperties"])
        self.assertFalse(mail_schema["additionalProperties"])
        self.assertEqual(upload_schema["properties"]["permission_scope"], {"type": "object"})
        self.assertEqual(
            mail_schema["properties"]["limit"],
            {"type": "integer", "minimum": 1, "maximum": 100},
        )
        self.assertEqual(access_schema["properties"]["requested_scope"], {"type": "object"})
        self.assertEqual(upload_schema["required"], ["intended_asset_type", "intent"])
        self.assertEqual(mail_schema["required"], ["query_text"])
        self.assertEqual(
            mail_schema["anyOf"],
            [
                {"required": ["mail_import_session_id"]},
                {"required": ["mail_evidence_bundle_id"]},
            ],
        )
        self.assertEqual(
            access_schema["required"],
            ["owner_user_id", "reason", "requested_access_level", "requested_scope"],
        )
        self.assertEqual(review_schema["required"], ["decision", "proposal_id"])
        for tool in tools_by_name.values():
            input_schema = tool["inputSchema"]
            self.assertFalse(input_schema["additionalProperties"])
            self.assertIn("required", input_schema)
        for identity_key in (
            "actor_user_id",
            "requester_user_id",
            "reviewer_user_id",
            "session_id",
            "workspace_id",
        ):
            self.assertNotIn(identity_key, upload_schema["properties"])
            self.assertNotIn(identity_key, mail_schema["properties"])
            self.assertNotIn(identity_key, review_schema["properties"])
        self.assertEqual(len(gateway.leak_transcript()), 2)

    def test_tools_call_binds_session_and_records_hash_only_transcript(self) -> None:
        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(
                retrieval_handler=lambda input_data: {
                    "answer": "bounded answer",
                    "citations": [],
                    "visible_graph_snippets": [],
                    "redaction_counts": {"hidden_records": 0},
                }
            ),
            session=SemanticGatewaySession(
                session_id="session_001",
                actor_user_id="user_yifan",
                workspace_id="workspace_main",
            ),
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

        self.assertFalse(result["result"]["isError"])
        self.assertEqual(
            result["result"]["session"]["actor_user_id"],
            "user_yifan",
        )
        self.assertEqual(set(transcript[0]), {"method", "request_hash", "response_hash", "status"})
        self.assertNotIn("delivery risk", str(transcript))

    def test_semantic_jsonrpc_allowlist_rejects_public_control_fields_before_handler_dispatch(
        self,
    ) -> None:
        handler_calls: list[dict[str, Any]] = []

        def recording_handler(input_data: dict[str, Any]) -> dict[str, Any]:
            handler_calls.append(input_data)
            return {
                "answer": "bounded answer",
                "citations": [],
                "visible_graph_snippets": [],
                "redaction_counts": {"hidden_records": 0},
            }

        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(retrieval_handler=recording_handler),
            session=SemanticGatewaySession(
                session_id="session_001",
                actor_user_id="user_yifan",
                workspace_id="workspace_main",
            ),
        )
        cases = [
            {"grants": [{"scope": "workspace_formowl", "level": "admin"}]},
            {"storage": {"profile": "mail_archive_pool"}},
            {"parser": {"profile": "pst_local"}},
            {"backend": {"name": "private_backend"}},
            {"raw": {"include_unprocessed": True}},
            {"requested_scope": {"grants": [{"scope": "workspace_formowl"}]}},
        ]

        for index, extra_arguments in enumerate(cases, start=1):
            with self.subTest(index=index):
                result = gateway.handle_json_rpc(
                    {
                        "jsonrpc": "2.0",
                        "id": f"control_{index}",
                        "method": "tools/call",
                        "params": {
                            "name": "query_effective_graph",
                            "arguments": {
                                "query_text": "delivery risk",
                                **extra_arguments,
                            },
                        },
                    }
                )

                tool_result = result["result"]["content"][0]["json"]
                self.assertTrue(result["result"]["isError"])
                self.assertEqual(tool_result["status"], "error")
                self.assertEqual(tool_result["data"]["error_code"], "unsafe_tool_payload")
                self.assertEqual(handler_calls, [])
                self.assertEqual(result["result"]["session"]["session_id"], "session_001")
                rendered = str(result).lower()
                self.assertNotIn("workspace_formowl", rendered)
                self.assertNotIn("mail_archive_pool", rendered)
                self.assertNotIn("pst_local", rendered)
                self.assertNotIn("private_backend", rendered)
                self.assertNotIn("include_unprocessed", rendered)

    def test_semantic_jsonrpc_rejects_caller_identity_before_handler_dispatch(self) -> None:
        handler_calls: list[dict[str, Any]] = []

        def recording_handler(input_data: dict[str, Any]) -> dict[str, Any]:
            handler_calls.append(input_data)
            return {
                "answer": "bounded answer",
                "citations": [],
                "visible_graph_snippets": [],
                "redaction_counts": {"hidden_records": 0},
            }

        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(retrieval_handler=recording_handler),
            session=SemanticGatewaySession(
                session_id="session_001",
                actor_user_id="user_yifan",
                workspace_id="workspace_main",
            ),
        )
        cases = [
            {"session_id": "session_forged"},
            {"workspace_id": "workspace_forged"},
            {"requester_user_id": "user_forged"},
            {"actorUserId": "user_forged"},
            {"candidate_filter": {"reviewer_user_id": "user_forged"}},
        ]

        for index, identity_arguments in enumerate(cases, start=1):
            with self.subTest(index=index):
                result = gateway.handle_json_rpc(
                    {
                        "jsonrpc": "2.0",
                        "id": f"identity_{index}",
                        "method": "tools/call",
                        "params": {
                            "name": "query_effective_graph",
                            "arguments": {
                                "query_text": "delivery risk",
                                **identity_arguments,
                            },
                        },
                    }
                )

                tool_result = result["result"]["content"][0]["json"]
                self.assertTrue(result["result"]["isError"])
                self.assertEqual(tool_result["status"], "error")
                self.assertEqual(tool_result["data"]["error_code"], "unsafe_tool_payload")
                self.assertEqual(handler_calls, [])
                rendered = str(result)
                self.assertNotIn("forged", rendered)

    def test_review_decision_binds_reviewer_identity_from_session(self) -> None:
        calls: list[dict[str, Any]] = []

        def review_handler(input_data: dict[str, Any]) -> dict[str, Any]:
            calls.append(input_data)
            return {"status": "pending_review", "decision": input_data["decision"]}

        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(review_decision_handler=review_handler),
            session=SemanticGatewaySession(
                session_id="session_001",
                actor_user_id="user_reviewer",
                workspace_id="workspace_main",
            ),
        )

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "review_001",
                "method": "tools/call",
                "params": {
                    "name": "submit_graph_review_decision",
                    "arguments": {"proposal_id": "fusion_001", "decision": "defer"},
                },
            }
        )

        self.assertFalse(result["result"]["isError"])
        tool_result = result["result"]["content"][0]["json"]
        self.assertEqual(tool_result["status"], "pending_review")
        self.assertEqual(calls[0]["reviewer_user_id"], "user_reviewer")

    def test_private_query_content_is_dispatched_without_output_leak_scanning_or_echo(self) -> None:
        calls: list[dict[str, Any]] = []

        def recording_handler(input_data: dict[str, Any]) -> dict[str, Any]:
            calls.append(input_data)
            return {
                "status": "ok",
                "mail_import_session_id": "mailimport_001",
                "query_hash": "sha256:" + "1" * 64,
                "evidence_snippets": [],
                "citations": [],
                "redaction_counts": {"hidden_bundles": 0, "hidden_messages": 0},
                "warnings": ["no_visible_mail_evidence_matched"],
            }

        gateway = SemanticMcpJsonRpcGateway(
            semantic_gateway=SemanticMcpGateway(mail_evidence_handler=recording_handler),
            session=SemanticGatewaySession(
                session_id="session_private_query",
                actor_user_id="user_yifan",
                workspace_id="workspace_main",
            ),
        )
        private_query = "Review /srv/private/a.csv and select * from supplier_private"

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "private_query",
                "method": "tools/call",
                "params": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": private_query,
                        "mail_import_session_id": "mailimport_001",
                    },
                },
            }
        )

        self.assertFalse(result["result"]["isError"])
        self.assertEqual(calls[0]["query_text"], private_query)
        self.assertNotIn(private_query, str(result))
        self.assertNotIn(private_query, str(gateway.leak_transcript()))

    def test_forbidden_tool_calls_return_safe_json_rpc_errors(self) -> None:
        gateway = SemanticMcpJsonRpcGateway(
            session=SemanticGatewaySession(
                session_id="session_forbidden_tool",
                actor_user_id="user_forbidden_tool",
                workspace_id="workspace_main",
            )
        )

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
        self.assertFalse(transcript_packet["raw_request_retained"])
        self.assertEqual(transcript_packet["safe_response_count"], 3)
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

    def test_mail_upload_runtime_gateway_configures_open_upload_session_handler(self) -> None:
        temp_dir = _paths.fresh_test_dir("semantic-mail-upload-runtime")
        gateway = create_mail_upload_semantic_jsonrpc_gateway(
            data_dir=temp_dir,
            expires_at="2026-07-06T00:00:00+00:00",
            session=SemanticGatewaySession(
                session_id="session_runtime_001",
                actor_user_id="user_yifan",
                workspace_id="workspace_formowl",
            ),
        )

        result = gateway.handle_json_rpc(
            {
                "jsonrpc": "2.0",
                "id": "mail_upload_runtime",
                "method": "tools/call",
                "params": {
                    "name": "open_upload_session",
                    "arguments": {
                        "intent": "Upload my PST for FormOwl mail evidence reading.",
                        "intended_asset_type": "pst",
                        "owner_scope_type": "project",
                        "owner_scope_id": "project_formowl",
                        "project_id": "project_formowl",
                    },
                },
            }
        )

        self.assertFalse(result["result"]["isError"])
        payload = result["result"]["content"][0]["json"]["data"]
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["validation"]["passed"], True)
        task_card = payload["upload_task_card"]
        self.assertEqual(task_card["card_type"], "mail_archive_upload_task")
        self.assertTrue(
            task_card["upload_surface_locator"].startswith("formowl_upload_session:upload_")
        )
        upload_store = UploadSessionStore(temp_dir)
        persisted = upload_store.get(payload["upload_session_id"])
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted.actor_user_id, "user_yifan")
        self.assertEqual(persisted.session_id, "session_runtime_001")
        self.assertEqual(persisted.workspace_id, "workspace_formowl")
        self.assertEqual(persisted.ingestion_profile, "mail_archive_phase1")
        rendered = str(result).lower()
        self.assertNotIn("upload_handler_not_configured", rendered)
        self.assertNotIn("storage_backend_id", rendered)
        self.assertNotIn("private_backend", rendered)
        self.assertNotIn("parser_path", rendered)
        self.assertNotIn("worker_queue", rendered)

    def test_pyproject_exposes_semantic_jsonrpc_console_script(self) -> None:
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["project"]["scripts"]["formowl-semantic-mcp-jsonrpc"],
            "formowl_gateway.cli:main",
        )

    def test_jsonrpc_module_main_uses_configured_mail_upload_runtime(self) -> None:
        temp_dir = _paths.fresh_test_dir("semantic-mail-upload-runtime-main")
        repo_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo_root / "python")
        env["FORMOWL_DATA_DIR"] = str(temp_dir)
        env["FORMOWL_MCP_SESSION_ID"] = "session_cli_001"
        env["FORMOWL_MCP_ACTOR_USER_ID"] = "user_cli"
        env["FORMOWL_MCP_WORKSPACE_ID"] = "workspace_cli"
        env["FORMOWL_MAIL_UPLOAD_EXPIRES_AT"] = "2026-07-06T00:00:00+00:00"
        request = {
            "jsonrpc": "2.0",
            "id": "mail_upload_cli",
            "method": "tools/call",
            "params": {
                "name": "open_upload_session",
                "arguments": {
                    "intent": "Upload mail archive from ChatGPT MCP runtime.",
                    "intended_asset_type": "pst",
                },
            },
        }

        completed = subprocess.run(
            [sys.executable, "-m", "formowl_gateway.cli"],
            input=json.dumps(request) + "\n",
            text=True,
            capture_output=True,
            cwd=repo_root,
            env=env,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        response = json.loads(completed.stdout)
        self.assertFalse(response["result"]["isError"])
        payload = response["result"]["content"][0]["json"]["data"]
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["validation"]["passed"], True)
        persisted = UploadSessionStore(temp_dir).get(payload["upload_session_id"])
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted.actor_user_id, "user_cli")
        self.assertEqual(persisted.session_id, "session_cli_001")
        self.assertEqual(persisted.workspace_id, "workspace_cli")
        rendered = (completed.stdout + completed.stderr).lower()
        self.assertNotIn("upload_handler_not_configured", rendered)
        self.assertNotIn("storage_backend_id", rendered)
        self.assertNotIn("parser_path", rendered)
        self.assertNotIn("worker_queue", rendered)

    def test_jsonrpc_module_main_rejects_non_object_json_without_traceback(self) -> None:
        temp_dir = _paths.fresh_test_dir("semantic-mail-upload-runtime-non-object")
        repo_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo_root / "python")
        env["FORMOWL_DATA_DIR"] = str(temp_dir)

        completed = subprocess.run(
            [sys.executable, "-m", "formowl_gateway.cli"],
            input='[]\n"x"\n',
            text=True,
            capture_output=True,
            cwd=repo_root,
            env=env,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(len(responses), 2)
        for response in responses:
            self.assertEqual(response["error"]["code"], -32600)
            self.assertEqual(response["error"]["message"], "invalid_request")
        rendered = (completed.stdout + completed.stderr).lower()
        self.assertNotIn("traceback", rendered)
        self.assertNotIn(str(repo_root).lower(), rendered)

    def test_jsonrpc_module_main_redacts_secret_like_env_session_values(self) -> None:
        temp_dir = _paths.fresh_test_dir("semantic-mail-upload-runtime-secret-env")
        repo_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo_root / "python")
        env["FORMOWL_DATA_DIR"] = str(temp_dir)
        env["FORMOWL_MCP_SESSION_ID"] = "token: session-secret"
        env["FORMOWL_MCP_ACTOR_USER_ID"] = "password: swordfish"
        env["FORMOWL_MCP_WORKSPACE_ID"] = "workspace_cli"

        completed = subprocess.run(
            [sys.executable, "-m", "formowl_gateway.cli"],
            input=json.dumps({"jsonrpc": "2.0", "id": "init", "method": "initialize"}) + "\n",
            text=True,
            capture_output=True,
            cwd=repo_root,
            env=env,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        response = json.loads(completed.stdout)
        self.assertEqual(response["error"]["code"], -32001)
        self.assertEqual(response["error"]["message"], "session_not_authenticated")
        rendered = completed.stdout.lower()
        self.assertNotIn("swordfish", rendered)
        self.assertNotIn("session-secret", rendered)
        self.assertNotIn("password:", rendered)
        self.assertNotIn("token:", rendered)

    def test_jsonrpc_module_main_redacts_gateway_startup_failures(self) -> None:
        temp_dir = _paths.fresh_test_dir("semantic-mail-upload-runtime-startup-failure")
        bad_data_dir = temp_dir / "not-a-directory"
        bad_data_dir.write_text("occupied", encoding="utf-8")
        repo_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo_root / "python")
        env["FORMOWL_DATA_DIR"] = str(bad_data_dir)
        request = {
            "jsonrpc": "2.0",
            "id": "startup_failure",
            "method": "initialize",
        }

        completed = subprocess.run(
            [sys.executable, "-m", "formowl_gateway.cli"],
            input=json.dumps(request) + "\n",
            text=True,
            capture_output=True,
            cwd=repo_root,
            env=env,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        response = json.loads(completed.stdout)
        self.assertEqual(response["id"], "startup_failure")
        self.assertEqual(response["error"]["code"], -32000)
        self.assertEqual(response["error"]["message"], "internal_error")
        rendered = (completed.stdout + completed.stderr).lower()
        self.assertNotIn("traceback", rendered)
        self.assertNotIn(str(bad_data_dir).lower(), rendered)
        self.assertNotIn(str(repo_root).lower(), rendered)


if __name__ == "__main__":
    unittest.main()
