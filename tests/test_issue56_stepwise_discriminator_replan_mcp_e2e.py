from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

import _paths  # noqa: F401
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

import formowl_gateway.runtime as runtime_module
import formowl_mail.hybrid as hybrid_module
from formowl_auth import FileAuditLogStore
from formowl_contract import PermissionScope, sha256_json
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_gateway.semantic import SemanticMcpGateway, validate_public_gateway_payload
from formowl_ingestion.storage import UploadSessionStore
from formowl_mail import build_mail_upload_session_handler
from formowl_mail.exact import authorized_source_occurrence_scope_fingerprint
from formowl_mail.hybrid import (
    build_authorized_semantic_observation_session,
    build_authorized_source_backed_effective_graph_view,
)
from formowl_mail.issue56_sealed_source import APPROVER_ACTOR, WORKSPACE_ID
from formowl_mail.query import (
    build_authorized_observation_snippet_index,
    source_occurrence_lineage_from_observation,
)
from formowl_mail.semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    validated_authorized_semantic_source,
)
from test_connected_attachment_hybrid_e2e import (
    SOURCE_SCOPE_ID,
    _attachment_child_observations,
    _formal_xlsx_bytes,
    _observation,
)
from test_connected_runtime import (
    _FakeHttpClient,
    _FakeRepository,
    _write_runtime_environment,
)
from test_issue56_semantic_execution_e2e import _contract_only_runtime
from test_issue56_supplemental_attachment_table_loader_e2e import _oauth_context


def _source_table_bytes() -> bytes:
    output = io.BytesIO()
    replacements = {
        b">Category<": b">EntityKey<",
        b' name="Category"': b' name="EntityKey"',
        b">Code<": b">MetricField<",
        b' name="Code"': b' name="MetricField"',
        b"<c r=\"B1\" t=\"inlineStr\"><is><t>MetricField</t></is></c></row>": (
            b"<c r=\"B1\" t=\"inlineStr\"><is><t>MetricField</t></is></c>"
            b"<c r=\"C1\" t=\"inlineStr\"><is><t>VariantField</t></is></c></row>"
        ),
        b"<row r=\"2\"><c r=\"A2\" t=\"inlineStr\"><is><t>ROW-FILTER-42</t></is></c>"
        b"<c r=\"B2\" t=\"inlineStr\"><is><t>VALUE-7</t></is></c></row>": (
            b"<row r=\"2\"><c r=\"A2\" t=\"inlineStr\"><is><t>SYN-ENTITY-731</t></is></c>"
            b"<c r=\"B2\" t=\"inlineStr\"><is><t>MetricAmber</t></is></c>"
            b"<c r=\"C2\" t=\"inlineStr\"><is><t>LaneNorth</t></is></c></row>"
            b"\n  <row r=\"3\"><c r=\"A3\" t=\"inlineStr\"><is><t>SYN-ENTITY-731</t></is></c>"
            b"<c r=\"B3\" t=\"inlineStr\"><is><t>MetricIndigo</t></is></c>"
            b"<c r=\"C3\" t=\"inlineStr\"><is><t>LaneSouth</t></is></c></row>"
        ),
        b'ref="A1:B2"': b'ref="A1:C3"',
        b'<tableColumns count="2">': b'<tableColumns count="3">',
        b'<tableColumn id="2" name="MetricField"/></tableColumns>': (
            b'<tableColumn id="2" name="MetricField"/>'
            b'<tableColumn id="3" name="VariantField"/></tableColumns>'
        ),
    }
    with (
        ZipFile(io.BytesIO(_formal_xlsx_bytes())) as source,
        ZipFile(output, "w") as target,
    ):
        for member in source.infolist():
            payload = source.read(member.filename)
            for old, new in replacements.items():
                payload = payload.replace(old, new)
            target.writestr(member, payload)
    return output.getvalue()


class Issue56StepwiseDiscriminatorReplanMcpE2ETests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_combined_projection_preserves_each_source_row_over_mcp(
        self,
    ) -> None:
        identifier = "SYN-ENTITY-731"
        projection_field = "MetricField"
        discriminator_field = "VariantField"
        expected_value_pairs = {
            frozenset(
                {
                    (projection_field, "MetricAmber"),
                    (discriminator_field, "LaneNorth"),
                }
            ),
            frozenset(
                {
                    (projection_field, "MetricIndigo"),
                    (discriminator_field, "LaneSouth"),
                }
            ),
        }
        parent = _observation(
            observation_id="observation_stepwise_discriminator_attachment",
            observation_type="email_attachment_occurrence",
            text="Authorized synthetic table attachment",
            payload={
                "attachment_id": "attachment_stepwise_discriminator",
                "child_asset_id": "asset_stepwise_discriminator",
            },
        )
        children = _attachment_child_observations(
            child_asset_id="asset_stepwise_discriminator",
            content=_source_table_bytes(),
            suffix=".xlsx",
        )
        data_rows = tuple(
            observation
            for observation in children
            if observation.observation_type == "table_row"
            and observation.payload["table_structure"]["row_role"] == "data"
        )
        self.assertEqual(len(data_rows), 2)
        observations = (parent, *children)
        retrieval_observations = (parent, *data_rows)
        authorized_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
            authorized_permission_scopes=(PermissionScope.project(SOURCE_SCOPE_ID),),
        )
        lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            for observation in observations
            if observation.modality == "mail"
        )
        authorized_hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
            for observation in observations
        }
        retrieval_hashes = {
            observation.observation_id: authorized_hashes[observation.observation_id]
            for observation in retrieval_observations
        }
        runtime_components = _contract_only_runtime()
        snippet_index, _ = build_authorized_observation_snippet_index(
            retrieval_observations,
            authorized_source=authorized_source,
            occurrence_lineages=lineages,
            authorized_observation_hash_by_id=retrieval_hashes,
            tokenizer_profile=runtime_components.tokenizer_profile,
        )
        with patch.object(
            hybrid_module,
            "_load_pinned_issue56_runtime_components",
            return_value=runtime_components,
        ):
            session = build_authorized_semantic_observation_session(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=observations,
                retrieval_observations=retrieval_observations,
                occurrence_lineages=lineages,
                requester_user_id=APPROVER_ACTOR,
            )
        graph_view = build_authorized_source_backed_effective_graph_view(
            session=session,
            source_binding_fingerprint=sha256_json(
                "stepwise_discriminator_source_binding"
            ),
        ).effective_graph_view
        table_provider = gateway_loader._build_attachment_table_row_provider(
            session,
            authorized_scope_fingerprint=authorized_source_occurrence_scope_fingerprint(
                requester_user_id=session.requester_user_id,
                workspace_id=session.workspace_id,
                source_scope_ids=session.authorized_source_scope_ids,
                authorized_observation_hashes=session.authorized_observation_hashes,
                source_session_binding_fingerprint=(
                    session.source_session_binding_fingerprint or ""
                ),
            ),
        )
        assert table_provider is not None
        self.assertEqual(len(table_provider.occurrences), 2)
        expected_by_item = {}
        occurrence_references = {}
        for occurrence in table_provider.occurrences:
            values = frozenset(
                (field, value)
                for _column, _candidate, _value_hash, field, value, _citation, _lineage
                in occurrence.structured_column_bindings
                if field in {projection_field, discriminator_field}
            )
            expected_by_item[occurrence.item_hash] = values
            occurrence_references[occurrence.item_hash] = {
                (citation, lineage)
                for _column, _candidate, _value_hash, _field, _value, citation, lineage
                in occurrence.structured_column_bindings
            } | {
                (citation, lineage)
                for _normalized, _variant, citation, lineage
                in occurrence.value_bindings
            }
        self.assertEqual(set(expected_by_item.values()), expected_value_pairs)

        loaded = SimpleNamespace(
            session=session,
            effective_graph_view=graph_view,
            safe_binding={},
        )
        with (
            patch.object(
                gateway_loader,
                "_load_approved_sealed_source",
                return_value=loaded,
            ),
            patch.object(
                gateway_loader,
                "_validated_owner_safe_binding",
                return_value={},
            ),
            patch.object(
                gateway_loader,
                "_build_mail_source_occurrence_providers",
                return_value=(table_provider,),
            ),
        ):
            retrieval_handler = (
                gateway_loader.build_issue56_production_semantic_retrieval_handler()
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            config = ConnectedRuntimeConfig.from_env_and_secrets(
                _write_runtime_environment(Path(temporary_directory))
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
                    mcp_headers = {
                        "Authorization": "Bearer synthetic.token",
                        "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                    }
                    listed = client.post(
                        "/mcp",
                        headers=mcp_headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": "stepwise-discriminator-tools",
                            "method": "tools/list",
                        },
                    )
                    self.assertEqual(listed.status_code, 200)
                    description = next(
                        tool["description"]
                        for tool in listed.json()["result"]["tools"]
                        if tool["name"] == "query_effective_graph_view"
                    )
                    for requirement in (
                        "multi-valued, coverage-incomplete, or claim-ambiguous",
                        "never collapse the result to one value by frequency or ordering",
                        "If one follow-up remains",
                        "source_provided row discriminator",
                        "combined projection query containing the original projection",
                        "row association is retained in the same exact response",
                        "clarify or fail closed",
                    ):
                        self.assertIn(requirement, description)
                    query = (
                        f"有{identifier}的{projection_field}"
                        f"跟{discriminator_field}呢？"
                    )
                    response = client.post(
                        "/mcp",
                        headers=mcp_headers,
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
                self.assertEqual(inventory["query_class"], "exact_set_or_inventory")
                self.assertEqual(inventory["coverage_status"], "complete")
                self.assertEqual(inventory["returned_count"], 2)
                self.assertEqual(inventory["candidate_only_occurrence_count"], 0)
                self.assertEqual(len(inventory["items"]), 2)
                citations = set(data["citations"])
                actual_value_pairs = set()
                for item in inventory["items"]:
                    self.assertEqual(item["structure_status"], "source_provided")
                    structured = {
                        (
                            value["field"],
                            value["value"],
                            value["citation_hash"],
                            value["occurrence_lineage_fingerprint"],
                        )
                        for value in item["structured_values"]
                    }
                    value_pairs = frozenset(
                        (field, value) for field, value, _citation, _lineage in structured
                    )
                    actual_value_pairs.add(value_pairs)
                    self.assertEqual(value_pairs, expected_by_item[item["item_hash"]])
                    references = {
                        (
                            reference["citation_hash"],
                            reference["occurrence_lineage_fingerprint"],
                        )
                        for reference in item["governed_references"]
                    }
                    projected_references = {
                        (citation, lineage)
                        for _field, _value, citation, lineage in structured
                    }
                    self.assertTrue(projected_references <= references)
                    self.assertTrue(
                        references <= occurrence_references[item["item_hash"]]
                    )
                    self.assertTrue({citation for citation, _ in references} <= citations)
                self.assertEqual(actual_value_pairs, expected_value_pairs)
                rendered = str(data)
                self.assertNotIn(str(temporary_directory), rendered)
                self.assertNotIn("object_uri", rendered)
                self.assertNotIn("tenant_id", rendered)
            finally:
                await runtime.aclose()


if __name__ == "__main__":
    unittest.main()
