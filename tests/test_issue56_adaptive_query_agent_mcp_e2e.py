from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import _paths  # noqa: F401
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

import formowl_gateway.runtime as runtime_module
import formowl_mail.hybrid as hybrid_module
from formowl_auth import FileAuditLogStore
from formowl_contract import sha256_json
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_gateway.semantic import SemanticMcpGateway, validate_public_gateway_payload
from formowl_ingestion.storage import UploadSessionStore
from formowl_mail import build_mail_upload_session_handler
from test_connected_runtime import (
    _FakeHttpClient,
    _FakeRepository,
    _write_runtime_environment,
)
from test_issue56_sealed_source_loader_e2e import (
    _loader_environment,
    _prepare_package,
    _sha256_path,
)
from test_issue56_semantic_execution_e2e import _contract_only_runtime
from test_issue56_supplemental_attachment_table_loader_e2e import (
    _ALTERNATE_HEADER,
    _ALTERNATE_VALUE,
    _HEADER,
    _IDENTIFIER,
    _PERMISSION_SCOPE,
    _VALUE,
    _oauth_context,
    _write_supplemental_partition,
)
import test_issue56_sealed_source_loader_e2e as sealed_fixture


class Issue56AdaptiveQueryAgentMcpE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_external_agent_replans_from_capabilities_over_normal_mcp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch.object(
                sealed_fixture,
                "WORKSPACE_PERMISSION_SCOPE",
                _PERMISSION_SCOPE,
            ):
                package = _prepare_package(root / "sealed")
            supplemental_path, parent_path = _write_supplemental_partition(
                root,
                package,
            )
            environment = _loader_environment(package)
            environment.update(
                {
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_PATH": str(
                        supplemental_path
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_SHA256": (
                        _sha256_path(supplemental_path)
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_PATH": str(
                        parent_path
                    ),
                    "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_SHA256": (
                        _sha256_path(parent_path)
                    ),
                }
            )
            cases = (
                (_HEADER, _VALUE, "OpaqueGapAlpha"),
                (_ALTERNATE_HEADER, _ALTERNATE_VALUE, "OpaqueGapBeta"),
            )

            with (
                patch.dict(os.environ, environment, clear=True),
                patch.object(
                    hybrid_module,
                    "_load_pinned_issue56_runtime_components",
                    return_value=_contract_only_runtime(),
                ),
            ):
                retrieval_handler = (
                    gateway_loader.build_issue56_production_semantic_retrieval_handler()
                )
            runtime_root = root / "runtime"
            runtime_root.mkdir()
            config = ConnectedRuntimeConfig.from_env_and_secrets(
                _write_runtime_environment(runtime_root)
            )
            semantic_gateway = SemanticMcpGateway(
                upload_session_handler=build_mail_upload_session_handler(
                    upload_session_store=UploadSessionStore(config.data_dir),
                    audit_store=FileAuditLogStore(config.data_dir),
                    expires_at_provider=lambda: "2030-01-01T00:00:00+00:00",
                ),
                retrieval_handler=retrieval_handler,
            )
            with patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=_FakeRepository(),
            ):
                runtime = await ConnectedRuntime.compose(
                    config,
                    semantic_gateway=semantic_gateway,
                    http_client=_FakeHttpClient(),
                )
            runtime.preflight = AsyncMock(return_value={"status": "ready"})
            principal, actor = _oauth_context(config)
            try:
                with (
                    patch.object(
                        runtime.bridge,
                        "authenticate_access_token",
                        return_value=principal,
                    ),
                    patch.object(
                        runtime.bridge,
                        "resolve_actor_context",
                        return_value=actor,
                    ),
                    patch.object(
                        runtime.bridge,
                        "record_mcp_authorization_decision",
                        return_value=None,
                    ),
                    TestClient(
                        runtime.application.app,
                        raise_server_exceptions=False,
                    ) as client,
                ):
                    request_count = 0

                    def post_query(query_text):
                        nonlocal request_count
                        request_count += 1
                        return client.post(
                            "/mcp",
                            headers={
                                "Authorization": "Bearer synthetic.token",
                                "Accept": "application/json, text/event-stream",
                                "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                            },
                            json={
                                "jsonrpc": "2.0",
                                "id": sha256_json(query_text),
                                "method": "tools/call",
                                "params": {
                                    "name": "query_effective_graph_view",
                                    "arguments": {"query_text": query_text},
                                },
                            },
                        )

                    for header, expected_value, unsupported_field in cases:
                        prompt = (
                            f"把{_IDENTIFIER}的{header}"
                            f"跟{unsupported_field}給出來"
                        )
                        response = post_query(prompt)
                        self.assertEqual(response.status_code, 200)
                        result = response.json()["result"]
                        self.assertFalse(result["isError"], result)
                        data = result["structuredContent"]["data"]
                        validate_public_gateway_payload(data)
                        self.assertEqual(data["status"], "replan_required")
                        agent = data["query_agent"]
                        self.assertEqual(agent["status"], "replan_required")
                        self.assertEqual(agent["planner_model_status"], "not_connected")
                        self.assertEqual(agent["mcp_call_count"], 1)
                        self.assertEqual(
                            agent["conversation_state"],
                            {
                                "status": "must_be_resolved_upstream",
                                "hidden_history_used": False,
                            },
                        )
                        summary = agent["authorized_capability_summary"]
                        projection_fields = summary["projection_fields"]
                        self.assertTrue(projection_fields)
                        self.assertTrue(
                            all(
                                item["field_hash"].startswith("sha256:")
                                for item in projection_fields
                            )
                        )
                        matching_fields = [
                            item["field"]
                            for item in projection_fields
                            if item["structure_status"] == "source_provided"
                            and item["field"] in prompt
                        ]
                        self.assertEqual(matching_fields, [header])
                        self.assertNotIn(unsupported_field, matching_fields)
                        self.assertFalse(
                            any(
                                key in item
                                for item in projection_fields
                                for key in ("value", "text", "snippet")
                            )
                        )
                        summary_text = str(summary)
                        self.assertNotIn(_VALUE, summary_text)
                        self.assertNotIn(_ALTERNATE_VALUE, summary_text)

                        follow_up = f"有{_IDENTIFIER}的{matching_fields[0]}呢？"
                        follow_up_response = post_query(follow_up)
                        self.assertEqual(follow_up_response.status_code, 200)
                        follow_up_result = follow_up_response.json()["result"]
                        self.assertFalse(
                            follow_up_result["isError"],
                            follow_up_result,
                        )
                        follow_up_data = follow_up_result["structuredContent"]["data"]
                        validate_public_gateway_payload(follow_up_data)
                        inventory = follow_up_data["exact_inventory"]
                        self.assertEqual(
                            inventory["status"],
                            "complete_authorized_scope",
                        )
                        self.assertEqual(inventory["coverage_status"], "complete")
                        self.assertEqual(inventory["returned_count"], 1)
                        self.assertEqual(inventory["unsupported_count"], 0)
                        self.assertEqual(
                            inventory["candidate_only_occurrence_count"],
                            0,
                        )
                        item = inventory["items"][0]
                        self.assertEqual(item["structure_status"], "source_provided")
                        self.assertEqual(
                            [
                                (value["field"], value["value"])
                                for value in item["structured_values"]
                            ],
                            [(matching_fields[0], expected_value)],
                        )
                        self.assertTrue(follow_up_data["citations"])
                        follow_up_agent = follow_up_data["query_agent"]
                        self.assertEqual(follow_up_agent["status"], "complete")
                        self.assertEqual(follow_up_agent["mcp_call_count"], 1)
                        self.assertEqual(
                            follow_up_agent["executed_subquery_count"],
                            1,
                        )
                        self.assertEqual(
                            follow_up_agent["planner_model_status"],
                            "not_connected",
                        )
                        context = follow_up_agent["context_bundle"]
                        self.assertTrue(context["citation_hashes"])
                        self.assertTrue(context["lineage_fingerprints"])
                        snippets = [
                            evidence["snippet"]
                            for successful in context["successful_subqueries"]
                            for evidence in successful["evidence"]
                        ]
                        self.assertTrue(
                            any(expected_value in snippet for snippet in snippets)
                        )
                        rendered = str((data, follow_up_data))
                        self.assertNotIn(str(root), rendered)
                        self.assertNotIn("object_uri", rendered)
                        self.assertNotIn("tenant_id", rendered)
                    self.assertEqual(request_count, 2 * len(cases))
            finally:
                await runtime.aclose()


if __name__ == "__main__":
    unittest.main()
