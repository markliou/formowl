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
from formowl_contract import ContractValidationError, sha256_json
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
    _IDENTIFIER,
    _PERMISSION_SCOPE,
    _oauth_context,
    _write_supplemental_partition,
)
import test_issue56_sealed_source_loader_e2e as sealed_fixture


class Issue56AdaptiveQueryAgentMcpE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_multi_subquery_coverage_stop_over_normal_mcp(self) -> None:
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
            unknown_field = _ALTERNATE_VALUE
            query = (
                f"把{_IDENTIFIER}的{_ALTERNATE_HEADER}"
                f"跟{unknown_field}給出來"
            )
            supported_query = f"有{_IDENTIFIER}的{_ALTERNATE_HEADER}呢？"
            unsupported_query = f"有{_IDENTIFIER}的{unknown_field}呢？"
            planner_inputs = []

            def planner(
                original_prompt,
                prior_steps,
                _tokenizer_profile,
                _max_query_count,
            ):
                self.assertEqual(original_prompt, query)
                planner_inputs.append(tuple(dict(step) for step in prior_steps))
                if not prior_steps:
                    return original_prompt
                if len(prior_steps) == 1:
                    self.assertEqual(
                        prior_steps[-1]["validation_status"],
                        "rejected_existing_validator",
                    )
                    return supported_query
                if len(prior_steps) == 2:
                    self.assertEqual(prior_steps[-1]["coverage_status"], "complete")
                    return unsupported_query
                return None

            with (
                patch.dict(os.environ, environment, clear=True),
                patch.object(
                    hybrid_module,
                    "_load_pinned_issue56_runtime_components",
                    return_value=_contract_only_runtime(),
                ),
            ):
                retrieval_handler = (
                    gateway_loader.build_issue56_production_semantic_retrieval_handler(
                        query_agent_planner=planner
                    )
                )
            closure = dict(
                zip(
                    retrieval_handler.__code__.co_freevars,
                    (
                        cell.cell_contents
                        for cell in retrieval_handler.__closure__ or ()
                    ),
                    strict=True,
                )
            )
            with self.assertRaises(ContractValidationError):
                closure["session"].query(
                    query_text=query,
                    effective_graph_view=closure["graph_view"],
                    allowed_relation_types=closure["relation_types"],
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
                    response = client.post(
                        "/mcp",
                        headers={
                            "Authorization": "Bearer synthetic.token",
                            "Accept": "application/json, text/event-stream",
                            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                        },
                        json={
                            "jsonrpc": "2.0",
                            "id": sha256_json(query),
                            "method": "tools/call",
                            "params": {
                                "name": "query_effective_graph_view",
                                "arguments": {"query_text": query},
                            },
                        },
                    )
                self.assertEqual(response.status_code, 200)
                result = response.json()["result"]
                self.assertFalse(result["isError"], result)
                data = result["structuredContent"]["data"]
                validate_public_gateway_payload(data)
                inventory = data["exact_inventory"]
                self.assertEqual(inventory["status"], "complete_authorized_scope")
                self.assertEqual(inventory["coverage_status"], "complete")
                self.assertEqual(inventory["returned_count"], 1)
                self.assertEqual(inventory["unsupported_count"], 0)
                values = inventory["items"][0]["structured_values"]
                self.assertEqual(
                    [(item["field"], item["value"]) for item in values],
                    [(_ALTERNATE_HEADER, _ALTERNATE_VALUE)],
                )
                self.assertEqual(
                    inventory["items"][0]["structure_status"],
                    "source_provided",
                )
                self.assertTrue(data["citations"])
                agent = data["query_agent"]
                self.assertEqual(agent["status"], "partial")
                self.assertEqual(agent["mcp_call_count"], 1)
                self.assertEqual(agent["executed_subquery_count"], 3)
                self.assertEqual(agent["stop_reason"], "planner_stopped_partial")
                self.assertTrue(agent["stop_reason_fingerprint"].startswith("sha256:"))
                self.assertEqual(
                    len({item["query_hash"] for item in agent["subqueries"]}),
                    3,
                )
                self.assertEqual(
                    {item["validation_status"] for item in agent["subqueries"]},
                    {
                        "rejected_existing_validator",
                        "validated_existing_scope_schema_permission",
                    },
                )
                self.assertEqual(
                    [item["coverage_status"] for item in agent["subqueries"]],
                    ["not_executed", "complete", "not_executed"],
                )
                context = agent["context_bundle"]
                self.assertEqual(context["successful_subquery_count"], 1)
                self.assertTrue(context["citation_hashes"])
                self.assertTrue(context["lineage_fingerprints"])
                unsupported_step = agent["subqueries"][2]
                self.assertEqual(
                    unsupported_step["query_hash"],
                    sha256_json(unsupported_query),
                )
                self.assertTrue(unsupported_step["missing_field_hashes"])
                self.assertTrue(
                    set(unsupported_step["missing_field_hashes"])
                    <= set(context["missing_field_hashes"])
                )
                snippets = [
                    item["snippet"]
                    for subquery in context["successful_subqueries"]
                    for item in subquery["evidence"]
                ]
                self.assertTrue(snippets)
                self.assertTrue(
                    any(_ALTERNATE_VALUE in snippet for snippet in snippets)
                )
                exact_items = [
                    item
                    for subquery in context["successful_subqueries"]
                    for item in subquery["exact_items"]
                ]
                self.assertTrue(
                    any(
                        value["field"] == _ALTERNATE_HEADER
                        and value["value"] == _ALTERNATE_VALUE
                        for item in exact_items
                        for value in item.get("structured_values", [])
                    )
                )
                self.assertTrue(
                    all(
                        item.get("structure_status") == "source_provided"
                        for item in exact_items
                        if item.get("structured_values")
                    )
                )
                self.assertEqual(
                    agent["conversation_state"],
                    {
                        "status": "must_be_resolved_upstream",
                        "hidden_history_used": False,
                    },
                )
                self.assertEqual(
                    agent["planner_model_status"],
                    "injected_callback_non_model",
                )
                self.assertEqual(len(planner_inputs), 4)
                rendered = str(data)
                self.assertNotIn(str(root), rendered)
                self.assertNotIn("object_uri", rendered)
                self.assertNotIn("tenant_id", rendered)
            finally:
                await runtime.aclose()


if __name__ == "__main__":
    unittest.main()
