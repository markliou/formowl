from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import _paths  # noqa: F401
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

import formowl_gateway.runtime as runtime_module
from formowl_auth import ActorContext, OAuthPrincipal
from formowl_contract import (
    ContractValidationError,
    Observation,
    SessionIdentity,
    User,
    WorkspaceMember,
    sha256_json,
)
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_gateway.semantic import SemanticMcpGateway, validate_public_gateway_payload
from formowl_graph import EffectiveGraphView
from formowl_graph.index import GraphProjectionEdge
from formowl_mail.hybrid import build_authorized_semantic_observation_session
from formowl_mail.query import (
    build_authorized_observation_snippet_index,
    source_occurrence_lineage_from_observation,
    validate_source_neutral_attachment_observation_coverage,
)
from formowl_mail.semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    validated_authorized_semantic_source,
)
from test_connected_runtime import (
    _FakeHttpClient,
    _FakeRepository,
    _write_runtime_environment,
)
from test_issue56_semantic_execution_e2e import _contract_only_runtime


WORKSPACE_ID = "workspace_attachment_hybrid"
REQUESTER_ID = "user_attachment_hybrid"
SOURCE_SCOPE_ID = "mail_import_attachment_hybrid"
MESSAGE_OCCURRENCE_ID = "message_occurrence_attachment_hybrid"
PERMISSION_SCOPE = {
    "scope_type": "mail_import_session",
    "visibility": "shared",
    "scope_id": SOURCE_SCOPE_ID,
}


def _observation(
    *,
    observation_id: str,
    observation_type: str,
    text: str,
    message_occurrence_id: str = MESSAGE_OCCURRENCE_ID,
    asset_id: str = "asset_parent_mail",
    payload: dict[str, object] | None = None,
    permission_scope: dict[str, object] = PERMISSION_SCOPE,
) -> Observation:
    return Observation.from_dict(
        Observation(
            observation_id=observation_id,
            extractor_run_id="extractor_attachment_hybrid",
            observation_type=observation_type,
            modality="mail",
            location={"message_occurrence_id": message_occurrence_id},
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-08-29T00:00:00+00:00",
            asset_id=asset_id,
            text=text,
            payload={
                "message_occurrence_id": message_occurrence_id,
                **(payload or {}),
            },
        ).to_dict()
    )


class ConnectedAttachmentHybridE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_attachment_child_is_authorized_before_index_and_projected_over_asgi(
        self,
    ) -> None:
        from formowl_auth import FileAuditLogStore
        from formowl_gateway import issue56_sealed_source_loader as gateway_loader
        from formowl_ingestion.storage import UploadSessionStore
        from formowl_mail import build_mail_upload_session_handler

        query_text = "ATTACHMENT-CONTROL-42"
        parent_mail = _observation(
            observation_id="observation_attachment_parent_mail",
            observation_type="email_body_segment",
            text=f"Parent containment context {query_text}",
        )
        parent_attachment = _observation(
            observation_id="observation_attachment_occurrence",
            observation_type="email_attachment_occurrence",
            text=f"Authorized attachment occurrence {query_text}",
            payload={"attachment_id": "attachment_opaque_1"},
        )
        unresolved_attachment = _observation(
            observation_id="observation_attachment_unresolved",
            observation_type="email_attachment_occurrence",
            text="Authorized attachment occurrence without an extracted child",
            message_occurrence_id="message_occurrence_attachment_unresolved",
            payload={"attachment_id": "attachment_opaque_2"},
        )
        child_asset_id = "asset_attachment_child"
        child_row = _observation(
            observation_id="observation_attachment_table_row",
            observation_type="table_row",
            text=f"Structured child row {query_text}",
            asset_id=child_asset_id,
            payload={
                "parent_attachment_observation_id": parent_attachment.observation_id,
                "child_asset_id": child_asset_id,
                "object_uri": "storage://private/attachment.bin",
            },
        )
        observations = (
            parent_mail,
            parent_attachment,
            unresolved_attachment,
            child_row,
        )
        authorized_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
        )
        lineages = tuple(
            source_occurrence_lineage_from_observation(
                observation,
                authorized_source=authorized_source,
            )
            for observation in observations
        )
        authorized_hashes = {
            observation.observation_id: sha256_json(observation.to_dict())
            for observation in observations
        }
        runtime_components = _contract_only_runtime()
        snippet_index, _ = build_authorized_observation_snippet_index(
            observations,
            authorized_source=authorized_source,
            occurrence_lineages=lineages,
            authorized_observation_hash_by_id=authorized_hashes,
            tokenizer_profile=runtime_components.tokenizer_profile,
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=runtime_components,
        ):
            session = build_authorized_semantic_observation_session(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                requester_user_id=REQUESTER_ID,
            )
        candidate_by_hash = {
            candidate.source_observation_hash: candidate
            for candidate in session.index.candidates
        }
        expected_hashes = set(authorized_hashes.values())
        self.assertEqual(set(candidate_by_hash), expected_hashes)
        self.assertEqual(
            candidate_by_hash[authorized_hashes[parent_mail.observation_id]].coherence_group_hash,
            candidate_by_hash[authorized_hashes[child_row.observation_id]].coherence_group_hash,
        )
        self.assertIn(
            authorized_hashes[unresolved_attachment.observation_id],
            candidate_by_hash,
        )

        graph_view = EffectiveGraphView(
            requester_user_id=REQUESTER_ID,
            user_graph_revision_id="user_graph_attachment_hybrid",
            canonical_graph_revision_id="canonical_graph_attachment_hybrid",
            ontology_revision_id="ontology_attachment_hybrid",
            assembly_policy_id="assembly_attachment_hybrid",
            visible_edges=[
                GraphProjectionEdge(
                    edge_id="edge_attachment_hybrid_source_backed",
                    source_node_id="node_attachment_hybrid_parent",
                    target_node_id="node_attachment_hybrid_child",
                    relation_type="source_backed",
                    properties={
                        "source_observation_ids": [parent_mail.observation_id],
                        "source_kind_hash": sha256_json(
                            AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
                        ),
                    },
                    permission_scope=dict(PERMISSION_SCOPE),
                )
            ],
        )
        loaded = SimpleNamespace(
            session=session,
            effective_graph_view=graph_view,
            safe_binding={},
        )
        with (
            patch.object(gateway_loader, "APPROVER_ACTOR", REQUESTER_ID),
            patch.object(gateway_loader, "WORKSPACE_ID", WORKSPACE_ID),
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
                return_value=(),
            ),
        ):
            retrieval_handler = (
                gateway_loader.build_issue56_production_semantic_retrieval_handler()
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = _write_runtime_environment(Path(temporary_directory))
            config = ConnectedRuntimeConfig.from_env_and_secrets(environment)
            upload_handler = build_mail_upload_session_handler(
                upload_session_store=UploadSessionStore(config.data_dir),
                audit_store=FileAuditLogStore(config.data_dir),
                expires_at_provider=lambda: "2030-01-01T00:00:00+00:00",
            )
            with patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=_FakeRepository(),
            ):
                connected = await ConnectedRuntime.compose(
                    config,
                    semantic_gateway=SemanticMcpGateway(
                        upload_session_handler=upload_handler,
                        retrieval_handler=retrieval_handler,
                    ),
                    http_client=_FakeHttpClient(),
                )
            connected.preflight = AsyncMock(return_value={"status": "ready"})
            principal = OAuthPrincipal(
                user_id=REQUESTER_ID,
                external_identity_id="external_attachment_hybrid",
                oauth_client_id="chatgpt_closed_beta",
                token_session_id="oauth_attachment_hybrid",
                scopes=("formowl.use",),
                resource=config.oauth.resource,
            )
            timestamp = "2026-08-29T00:00:00+00:00"
            actor = ActorContext(
                user=User(
                    user_id=REQUESTER_ID,
                    display_name="Attachment hybrid owner",
                    status="active",
                    created_at=timestamp,
                ),
                session_identity=SessionIdentity(
                    session_id=principal.token_session_id,
                    selected_user_id=REQUESTER_ID,
                    selected_at=timestamp,
                    selection_method="google_oidc_oauth",
                ),
                workspace_memberships=[
                    WorkspaceMember(
                        user_id=REQUESTER_ID,
                        workspace_id=WORKSPACE_ID,
                        role="owner",
                    )
                ],
                current_workspace_id=WORKSPACE_ID,
                current_workspace_role="owner",
                external_identity_id=principal.external_identity_id,
                oauth_client_id=principal.oauth_client_id,
                oauth_token_session_id=principal.token_session_id,
                auth_mode="google_oidc_oauth",
                production_authentication=True,
            )
            try:
                with (
                    patch.object(
                        connected.bridge,
                        "authenticate_access_token",
                        return_value=principal,
                    ),
                    patch.object(
                        connected.bridge,
                        "resolve_actor_context",
                        return_value=actor,
                    ),
                    patch.object(
                        connected.bridge,
                        "record_mcp_authorization_decision",
                        return_value=None,
                    ),
                    TestClient(
                        connected.application.app,
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
                            "id": "attachment-hybrid",
                            "method": "tools/call",
                            "params": {
                                "name": "query_effective_graph_view",
                                "arguments": {"query_text": query_text},
                            },
                        },
                    ).json()["result"]
                self.assertFalse(response["isError"])
                data = response["structuredContent"]["data"]
                validate_public_gateway_payload(data)
                evidence = data["evidence"]
                evidence_hashes = {item["citation_hash"] for item in evidence}
                child_hash = authorized_hashes[child_row.observation_id]
                self.assertIn(child_hash, evidence_hashes)
                self.assertIn(
                    authorized_hashes[parent_attachment.observation_id],
                    evidence_hashes,
                )
                self.assertTrue(
                    all(item["citation_hash"] in data["citations"] for item in evidence)
                )
                self.assertNotIn("storage://", str(data))
                self.assertNotIn("object_uri", str(data))
                self.assertNotIn("tenant", str(data))
                coverage = validate_source_neutral_attachment_observation_coverage(
                    observations,
                    matched_child_observation_hashes=(child_hash,),
                )
                self.assertEqual(
                    coverage["authorized_attachment_occurrence_count"],
                    2,
                )
                self.assertEqual(
                    coverage["returned_attachment_occurrence_count"],
                    1,
                )
                self.assertEqual(
                    coverage["unresolved_attachment_occurrence_count"],
                    1,
                )
                self.assertEqual(
                    coverage["query_matched_attachment_occurrence_count"],
                    1,
                )
                self.assertFalse(coverage["authorized_scope_complete"])
            finally:
                await connected.aclose()

        missing_child_asset = replace(
            child_row,
            asset_id="asset_missing_child_binding",
            payload={
                key: value
                for key, value in (child_row.payload or {}).items()
                if key != "child_asset_id"
            },
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "child asset binding is unavailable",
        ):
            validate_source_neutral_attachment_observation_coverage(
                (*observations[:-1], missing_child_asset)
            )

        unauthorized_sibling = replace(
            child_row,
            observation_id="observation_attachment_unauthorized_sibling",
            permission_scope={
                "scope_type": "mail_import_session",
                "visibility": "shared",
                "scope_id": "mail_import_not_authorized",
            },
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "parent-child lineage binding mismatch",
        ):
            validate_source_neutral_attachment_observation_coverage(
                (*observations, unauthorized_sibling)
            )


if __name__ == "__main__":
    unittest.main()
