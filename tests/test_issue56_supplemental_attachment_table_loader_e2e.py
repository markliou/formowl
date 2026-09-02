from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

import _paths  # noqa: F401
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

import formowl_gateway.runtime as runtime_module
import formowl_mail.hybrid as hybrid_module
from formowl_auth import ActorContext, FileAuditLogStore, OAuthPrincipal
from formowl_contract import (
    ContractValidationError,
    Observation,
    PermissionScope,
    SessionIdentity,
    User,
    WorkspaceMember,
    sha256_json,
)
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_gateway.semantic import SemanticMcpGateway, validate_public_gateway_payload
from formowl_ingestion.storage import UploadSessionStore
from formowl_mail import build_mail_upload_session_handler
from formowl_mail import issue56_sealed_source as sealed_source
from test_connected_attachment_hybrid_e2e import (
    _attachment_child_observations,
    _formal_xlsx_bytes,
)
from test_connected_runtime import (
    _FakeHttpClient,
    _FakeRepository,
    _write_runtime_environment,
)
import test_issue56_sealed_source_loader_e2e as sealed_fixture
from test_issue56_sealed_source_loader_e2e import (
    _json_bytes,
    _loader_environment,
    _prepare_package,
    _sha256_path,
)
from test_issue56_semantic_execution_e2e import _contract_only_runtime


_IDENTIFIER = "SYN-PART-314"
_HEADER = "玄地"
_VALUE = "玄值甲"
_ALTERNATE_HEADER = "AuxField"
_ALTERNATE_VALUE = "AuxValue"
_BLANK_HEADER = "OptionalField"
_BLANK_IDENTIFIER = "SYN-BLANK-271"
_SPARSE_IDENTIFIER = "SYN-SPARSE-592"
_QUERY = f"有{_IDENTIFIER}的{_HEADER}呢？"
_PERMISSION_SCOPE = PermissionScope.project("project_formowl")


def _write_supplemental_partition(root: Path, package: object) -> tuple[Path, Path]:
    output = io.BytesIO()
    replacements = {
        b">Category<": b">PartNumber<",
        b' name="Category"': b' name="PartNumber"',
        b">Code<": f">{_HEADER}<".encode(),
        b' name="Code"': f' name="{_HEADER}"'.encode(),
        b">ROW-FILTER-42<": f">{_IDENTIFIER}<".encode(),
        b">VALUE-7<": f">{_VALUE}<".encode(),
        f"<c r=\"B1\" t=\"inlineStr\"><is><t>{_HEADER}</t></is></c></row>".encode(): (
        f"<c r=\"B1\" t=\"inlineStr\"><is><t>{_HEADER}</t></is></c>"
        f"<c r=\"C1\" t=\"inlineStr\"><is><t>{_ALTERNATE_HEADER}</t></is></c>"
        f"<c r=\"D1\" t=\"inlineStr\"><is><t>{_BLANK_HEADER}</t></is></c></row>"
        ).encode(),
        f"<row r=\"2\"><c r=\"A2\" t=\"inlineStr\"><is><t>{_IDENTIFIER}</t></is></c>"
        f"<c r=\"B2\" t=\"inlineStr\"><is><t>{_VALUE}</t></is></c></row>".encode(): (
            f"<row r=\"2\"><c r=\"A2\" t=\"inlineStr\"><is><t>{_IDENTIFIER}</t></is></c>"
            f"<c r=\"B2\" t=\"inlineStr\"><is><t>{_VALUE}</t></is></c></row>"
            f"\n  <row r=\"3\"><c r=\"A3\" t=\"inlineStr\"><is><t>{_IDENTIFIER}</t></is></c>"
            f"<c r=\"C3\" t=\"inlineStr\"><is><t>{_ALTERNATE_VALUE}</t></is></c></row>"
            f"\n  <row r=\"4\"><c r=\"A4\" t=\"inlineStr\"><is><t>{_BLANK_IDENTIFIER}</t></is></c>"
            f"<c r=\"D4\" t=\"inlineStr\"><is><t></t></is></c></row>"
            f"\n  <row r=\"5\"><c r=\"A5\" t=\"inlineStr\"><is><t>{_SPARSE_IDENTIFIER}</t></is></c></row>"
        ).encode(),
        b'ref="A1:B2"': b'ref="A1:D5"',
        b'<tableColumns count="2">': b'<tableColumns count="4">',
        f'<tableColumn id="2" name="{_HEADER}"/></tableColumns>'.encode(): (
            f'<tableColumn id="2" name="{_HEADER}"/>'
            f'<tableColumn id="3" name="{_ALTERNATE_HEADER}"/>'
            f'<tableColumn id="4" name="{_BLANK_HEADER}"/></tableColumns>'
        ).encode(),
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
    xlsx_bytes = output.getvalue()
    child_asset_id = "asset_supplemental_source_table"
    occurrence = package.fixture.bundle_artifact["bundle"]["message_occurrences"][0]
    parent_id = "observation_supplemental_attachment_parent"
    parent_source_asset_id = "asset_supplemental_v25_parent_source"
    structural_id = "synthetic_reviewed_xlsx_sheet"
    permission = _PERMISSION_SCOPE.to_dict()
    source_inventory_item_id = "inventory_supplemental_xlsx_sheet"
    source_observation_id = "observation_supplemental_xlsx_sheet"
    raw_message_fingerprint = sha256_json(occurrence)
    attachment_content_fingerprint = (
        f"sha256:{hashlib.sha256(xlsx_bytes).hexdigest()}"
    )
    extracted_children = _attachment_child_observations(
        child_asset_id=child_asset_id,
        content=xlsx_bytes,
        suffix=".xlsx",
    )
    cells_by_row: dict[int, list[dict[str, object]]] = {}
    for item in extracted_children:
        if item.observation_type != "table_cell":
            continue
        row_ordinal = int(item.location["row_index"])
        cells_by_row.setdefault(row_ordinal, []).append(
            {
                "row_ordinal": row_ordinal,
                "column_ordinal": int(item.location["cell_index"]),
                "cell_state": "absent" if item.text == "" else "populated",
                "value": item.text,
            }
        )
    record = {
        "checkpoint_path_fingerprint": sha256_json("synthetic checkpoint"),
        "checkpoint_path_ordinal": 1,
        "mime_ancestry": [],
        "mime_ordinal": 1,
        "parent_mime_ordinal": 0,
        "raw_message_fingerprint": raw_message_fingerprint,
        "record_type": "xlsx_sheet",
        "attachment_content_fingerprint": attachment_content_fingerprint,
        "attachment_ordinal": 1,
        "sheet_ordinal": 1,
        "structural_observation": {
            "structural_observation_id": structural_id,
            "structure_kind": "html_table",
            "source_asset_id": parent_source_asset_id,
            "source_inventory_item_id": source_inventory_item_id,
            "source_observation_id": source_observation_id,
            "attachment_ordinal": 1,
            "mime_ordinal": 1,
            "rows": [
                {"row_ordinal": ordinal, "cells": cells}
                for ordinal, cells in sorted(cells_by_row.items())
            ],
            "columns": [
                {"column_ordinal": ordinal}
                for ordinal in sorted(
                    {
                        int(item.location["cell_index"])
                        for item in extracted_children
                        if item.observation_type == "table_cell"
                    }
                )
            ],
        },
    }
    snapshot_record_fingerprint = sha256_json(record)
    children = tuple(
        replace(
            item,
            permission_scope=permission,
            payload={
                **(item.payload or {}),
                **(
                    {
                        "cell_state": (
                            "absent" if item.text == "" else "populated"
                        )
                    }
                    if item.observation_type == "table_cell"
                    else {}
                ),
                "canonical_fact_status": "not_asserted",
                "lineage": {
                    **((item.payload or {}).get("lineage") or {}),
                    "parent_attachment_observation_id": parent_id,
                    "source_structural_observation_id": structural_id,
                    "snapshot_record_fingerprint": snapshot_record_fingerprint,
                    "message_occurrence_id": occurrence["message_occurrence_id"],
                    "raw_message_fingerprint": raw_message_fingerprint,
                    "attachment_content_fingerprint": (
                        attachment_content_fingerprint
                    ),
                    "attachment_ordinal": 1,
                    "mime_ordinal": 1,
                    "sheet_ordinal": 1,
                    "source_inventory_item_id": source_inventory_item_id,
                    "source_observation_id": source_observation_id,
                    "source_row_ordinal": int(item.location["row_index"]),
                    **(
                        {
                            "source_column_ordinal": int(
                                item.location["cell_index"]
                            )
                        }
                        if item.observation_type == "table_cell"
                        else {}
                    ),
                },
            },
        )
        for item in extracted_children
    )
    parent = Observation(
        observation_id=parent_id,
        extractor_run_id="extractor_supplemental_attachment_parent",
        observation_type="email_attachment_occurrence",
        modality="mail",
        location={"message_occurrence_id": occurrence["message_occurrence_id"]},
        confidence=1.0,
        permission_scope=permission,
        created_at="2026-09-02T00:00:00+00:00",
        asset_id=parent_source_asset_id,
        text="Supplemental governed source table",
        payload={
            "message_occurrence_id": occurrence["message_occurrence_id"],
            "child_asset_id": child_asset_id,
            "raw_message_fingerprint": raw_message_fingerprint,
            "attachment_content_fingerprint": attachment_content_fingerprint,
            "attachment_ordinal": 1,
            "mime_ordinal": 1,
            "source_structural_observation_ids": [structural_id],
        },
    )
    snapshot = package.fixture.snapshot
    records = [record]
    source = {
        "workspace_id": sealed_source.WORKSPACE_ID,
        "owner_user_id": sealed_source.APPROVER_ACTOR,
        "source_asset_id": parent_source_asset_id,
        "source_fingerprint": sha256_json("synthetic supplemental source"),
        "permission_scope_fingerprint": snapshot["permission_fingerprint"],
        "selection_checkpoint_fingerprint": sha256_json(
            "synthetic supplemental selection"
        ),
    }
    capture = {
        "candidate_only": True,
        "canonical_kg": False,
        "captured_at": "2026-09-02T00:00:00Z",
        "producer": {
            "implementation_fingerprint": sha256_json("synthetic producer"),
            "parser_fingerprint": sha256_json("synthetic parser"),
        },
    }
    parent_snapshot = {
        "artifact_type": "formowl_diagnostic_current_export_table_snapshot_v2",
        "schema_version": 2,
        "capture": capture,
        "source": source,
        "record_count": len(records),
        "record_stream_fingerprint": sha256_json(records),
        "artifact_commitment": sha256_json(
            {"capture": capture, "source": source, "records": records}
        ),
        "records": records,
        "unavailable_input_ledger": {
            "ledger_version": 1,
            "entry_count": 0,
            "entries": [],
            "category_counts": {},
            "entry_stream_fingerprint": sha256_json([]),
        },
    }
    parent_path = root / "supplemental-parent-snapshot.json"
    parent_path.write_bytes(_json_bytes(parent_snapshot))
    parent_binding = {
        "artifact_type": parent_snapshot["artifact_type"],
        "schema_version": parent_snapshot["schema_version"],
        "artifact_byte_sha256": _sha256_path(parent_path),
        "artifact_commitment": parent_snapshot["artifact_commitment"],
        "record_stream_fingerprint": parent_snapshot["record_stream_fingerprint"],
        "record_count": parent_snapshot["record_count"],
        "source_asset_id": source["source_asset_id"],
        "source_fingerprint": source["source_fingerprint"],
        "permission_scope_fingerprint": source["permission_scope_fingerprint"],
        "selection_checkpoint_fingerprint": source[
            "selection_checkpoint_fingerprint"
        ],
    }
    row_count = sum(item.observation_type == "table_row" for item in children)
    statuses = [
        (item.payload or {})["table_structure"]["structure_status"]
        for item in children
    ]
    observations = (parent, *children)
    counts = {
        "reviewed_xlsx_binding_count": 1,
        "parent_message_occurrence_count": 1,
        "attachment_parent_count": 1,
        "table_row_count": row_count,
        "table_cell_count": len(children) - row_count,
        "source_provided_table_observation_count": statuses.count(
            "source_provided"
        ),
        "candidate_only_table_observation_count": statuses.count("candidate_only"),
        "authorized_supplemental_observation_count": len(observations),
        "retrieval_supplemental_observation_count": 1 + row_count,
    }
    path = root / "supplemental-observations.json"
    path.write_bytes(
        _json_bytes(
            {
                "artifact_id": sealed_source.SUPPLEMENTAL_OBSERVATION_ARTIFACT_ID,
                "schema_version": 1,
                "identity_scope_mode": sealed_source.IDENTITY_SCOPE_MODE,
                "workspace_id": sealed_source.WORKSPACE_ID,
                "approver_actor": sealed_source.APPROVER_ACTOR,
                "base_source_binding": {
                    key: snapshot[key]
                    for key in (
                        "source_snapshot_fingerprint",
                        "source_asset_sha256",
                        "source_inventory_fingerprint",
                        "permission_fingerprint",
                    )
                },
                "v25_parent_snapshot_binding": parent_binding,
                "counts": counts,
                "observations": [item.to_dict() for item in observations],
            }
        )
    )
    return path, parent_path


def _oauth_context(config: ConnectedRuntimeConfig) -> tuple[OAuthPrincipal, ActorContext]:
    principal = OAuthPrincipal(
        user_id=sealed_source.APPROVER_ACTOR,
        external_identity_id="supplemental_source_table_external",
        oauth_client_id="chatgpt_closed_beta",
        token_session_id="oauth_supplemental_source_table",
        scopes=("formowl.use",),
        resource=config.oauth.resource,
    )
    timestamp = "2026-09-02T00:00:00+00:00"
    actor = ActorContext(
        user=User(
            user_id=sealed_source.APPROVER_ACTOR,
            display_name="Supplemental source owner",
            status="active",
            created_at=timestamp,
        ),
        session_identity=SessionIdentity(
            session_id=principal.token_session_id,
            selected_user_id=sealed_source.APPROVER_ACTOR,
            selected_at=timestamp,
            selection_method="google_oidc_oauth",
        ),
        workspace_memberships=[
            WorkspaceMember(
                user_id=sealed_source.APPROVER_ACTOR,
                workspace_id=sealed_source.WORKSPACE_ID,
                role="owner",
            )
        ],
        current_workspace_id=sealed_source.WORKSPACE_ID,
        current_workspace_role="owner",
        external_identity_id=principal.external_identity_id,
        oauth_client_id=principal.oauth_client_id,
        oauth_token_session_id=principal.token_session_id,
        auth_mode="google_oidc_oauth",
        production_authentication=True,
    )
    return principal, actor


class Issue56SupplementalAttachmentTableLoaderE2ETests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_zero_arg_loader_answers_source_provided_table_over_mcp(
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
            parent_snapshot = json.loads(parent_path.read_bytes())
            validation_context = {
                "parent_snapshot": parent_snapshot,
                "parent_snapshot_byte_sha256": _sha256_path(parent_path),
                "base_snapshot": package.fixture.snapshot,
            }
            validation_error = sealed_source.Issue56SealedSourceLoadError
            lineage_reason = "supplemental_attachment_child_lineage_invalid"
            tampered_artifact = json.loads(supplemental_path.read_bytes())
            next(
                item
                for item in tampered_artifact["observations"]
                if item["observation_type"] == "table_cell"
            )["payload"]["value"] = "tampered-child-value"
            with self.assertRaisesRegex(validation_error, lineage_reason):
                sealed_source._validate_supplemental_observation_partition(
                    tampered_artifact,
                    **validation_context,
                )
            tampered_artifact = json.loads(supplemental_path.read_bytes())
            parent_observation = next(
                item for item in tampered_artifact["observations"]
                if item["observation_type"] == "email_attachment_occurrence"
            )
            parent_observation["payload"]["attachment_content_fingerprint"] = (
                sha256_json("tampered attachment provenance")
            )
            with self.assertRaisesRegex(validation_error, lineage_reason):
                sealed_source._validate_supplemental_observation_partition(
                    tampered_artifact, **validation_context
                )
            self.assertNotEqual(
                parent_snapshot["source"]["source_asset_id"],
                package.fixture.snapshot["source_inventory"]["source_asset_id"],
            )
            self.assertEqual(
                {record["record_type"] for record in parent_snapshot["records"]},
                {"xlsx_sheet"},
            )
            self.assertEqual(
                {
                    record["structural_observation"]["structure_kind"]
                    for record in parent_snapshot["records"]
                },
                {"html_table"},
            )
            supplemental_env = {
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
            incomplete_env = dict(supplemental_env)
            incomplete_env.pop(
                "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_SHA256"
            )
            environment = _loader_environment(package)
            with patch.dict(
                os.environ,
                {**environment, **incomplete_env},
                clear=True,
            ):
                with self.assertRaisesRegex(
                    ContractValidationError,
                    "supplemental observation environment is incomplete",
                ):
                    gateway_loader.build_issue56_production_semantic_retrieval_handler()

            environment.update(supplemental_env)
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
            upload = build_mail_upload_session_handler(
                upload_session_store=UploadSessionStore(config.data_dir),
                audit_store=FileAuditLogStore(config.data_dir),
                expires_at_provider=lambda: "2030-01-01T00:00:00+00:00",
            )
            semantic_gateway = SemanticMcpGateway(
                upload_session_handler=upload,
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
                            "id": sha256_json(_QUERY),
                            "method": "tools/call",
                            "params": {
                                "name": "query_effective_graph_view",
                                "arguments": {"query_text": _QUERY},
                            },
                        },
                    )
                    partial_query = (
                        f"有{_IDENTIFIER}的{_HEADER}但是UnmappedField呢？"
                    )
                    partial_response = client.post(
                        "/mcp",
                        headers={
                            "Authorization": "Bearer synthetic.token",
                            "Accept": "application/json, text/event-stream",
                            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                        },
                        json={
                            "jsonrpc": "2.0",
                            "id": sha256_json(partial_query),
                            "method": "tools/call",
                            "params": {
                                "name": "query_effective_graph_view",
                                "arguments": {"query_text": partial_query},
                            },
                        },
                    )
                    union_query = (
                        f"有{_IDENTIFIER}的{_HEADER}但是{_ALTERNATE_HEADER}呢？"
                    )
                    union_response = client.post(
                        "/mcp",
                        headers={
                            "Authorization": "Bearer synthetic.token",
                            "Accept": "application/json, text/event-stream",
                            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                        },
                        json={
                            "jsonrpc": "2.0",
                            "id": sha256_json(union_query),
                            "method": "tools/call",
                            "params": {
                                "name": "query_effective_graph_view",
                                "arguments": {"query_text": union_query},
                            },
                        },
                    )
                    blank_query = f"有{_BLANK_IDENTIFIER}的{_BLANK_HEADER}呢？"
                    blank_response = client.post(
                        "/mcp",
                        headers={
                            "Authorization": "Bearer synthetic.token",
                            "Accept": "application/json, text/event-stream",
                            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                        },
                        json={
                            "jsonrpc": "2.0",
                            "id": sha256_json(blank_query),
                            "method": "tools/call",
                            "params": {
                                "name": "query_effective_graph_view",
                                "arguments": {"query_text": blank_query},
                            },
                        },
                    )
                    sparse_query = f"有{_SPARSE_IDENTIFIER}的{_BLANK_HEADER}呢？"
                    sparse_response = client.post(
                        "/mcp",
                        headers={
                            "Authorization": "Bearer synthetic.token",
                            "Accept": "application/json, text/event-stream",
                            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
                        },
                        json={
                            "jsonrpc": "2.0",
                            "id": sha256_json(sparse_query),
                            "method": "tools/call",
                            "params": {
                                "name": "query_effective_graph_view",
                                "arguments": {"query_text": sparse_query},
                            },
                        },
                    )
                self.assertEqual(response.status_code, 200)
                result = response.json()["result"]
                self.assertFalse(result["isError"], result)
                data = result["structuredContent"]["data"]
                validate_public_gateway_payload(data)
                inventory = data["exact_inventory"]
                self.assertEqual(inventory["coverage_status"], "complete")
                self.assertEqual(inventory["returned_count"], 1)
                self.assertEqual(inventory["candidate_only_occurrence_count"], 0)
                self.assertEqual(
                    inventory["items"][0]["structured_values"][0]["field"],
                    _HEADER,
                )
                self.assertEqual(
                    inventory["items"][0]["structured_values"][0]["value"],
                    _VALUE,
                )
                self.assertEqual(
                    inventory["items"][0]["structure_status"],
                    "source_provided",
                )
                self.assertTrue(data["citations"])
                self.assertNotIn("candidate_interpretation", data)
                self.assertNotIn(str(root), str(data))
                self.assertNotIn("object_uri", str(data))
                self.assertNotIn("tenant_id", str(data))
                self.assertEqual(partial_response.status_code, 200)
                partial_result = partial_response.json()["result"]
                self.assertFalse(partial_result["isError"], partial_result)
                partial_data = partial_result["structuredContent"]["data"]
                partial_inventory = partial_data["exact_inventory"]
                self.assertEqual(
                    partial_inventory["coverage_status"],
                    "incomplete",
                )
                self.assertEqual(partial_inventory["returned_count"], 1)
                partial_value = partial_inventory["items"][0]["structured_values"][0]
                self.assertEqual(
                    (partial_value["field"], partial_value["value"]),
                    (_HEADER, _VALUE),
                )
                self.assertTrue(partial_data["citations"])
                self.assertEqual(union_response.status_code, 200)
                union_result = union_response.json()["result"]
                self.assertFalse(union_result["isError"], union_result)
                union_data = union_result["structuredContent"]["data"]
                union_inventory = union_data["exact_inventory"]
                self.assertEqual(
                    union_inventory["returned_count"], 2, union_inventory
                )
                self.assertEqual(
                    {
                        (value["field"], value["value"])
                        for item in union_inventory["items"]
                        for value in item["structured_values"]
                    },
                    {
                        (_HEADER, _VALUE),
                        (_ALTERNATE_HEADER, _ALTERNATE_VALUE),
                    },
                )
                self.assertEqual(
                    {
                        item["structure_status"]
                        for item in union_inventory["items"]
                    },
                    {"source_provided"},
                )
                self.assertEqual(
                    union_inventory["candidate_only_occurrence_count"],
                    0,
                )
                self.assertTrue(union_data["citations"])
                self.assertEqual(blank_response.status_code, 200)
                blank_result = blank_response.json()["result"]
                self.assertFalse(blank_result["isError"], blank_result)
                blank_data = blank_result["structuredContent"]["data"]
                blank_inventory = blank_data["exact_inventory"]
                self.assertEqual(blank_inventory["returned_count"], 1)
                self.assertEqual(blank_inventory["candidate_only_occurrence_count"], 0)
                blank_item = blank_inventory["items"][0]
                self.assertEqual(blank_item["structure_status"], "source_provided")
                self.assertEqual(
                    [
                        (value["field"], value["value"])
                        for value in blank_item["structured_values"]
                    ],
                    [(_BLANK_HEADER, "")],
                )
                self.assertTrue(blank_item["governed_references"])
                self.assertTrue(blank_data["citations"])
                self.assertEqual(sparse_response.status_code, 200)
                sparse_result = sparse_response.json()["result"]
                self.assertFalse(sparse_result["isError"], sparse_result)
                sparse_data = sparse_result["structuredContent"]["data"]
                sparse_inventory = sparse_data["exact_inventory"]
                self.assertEqual(sparse_inventory["coverage_status"], "incomplete")
                self.assertEqual(sparse_inventory["total_count"], 0)
                self.assertEqual(sparse_inventory["returned_count"], 0)
                self.assertEqual(sparse_inventory["items"], [])
                self.assertEqual(sparse_data["citations"], [])
            finally:
                await runtime.aclose()


if __name__ == "__main__":
    unittest.main()
