from __future__ import annotations
from dataclasses import replace
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import _paths  # noqa: F401
from mcp.shared.version import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient
import formowl_mail
import formowl_gateway.runtime as runtime_module
import formowl_mail.hybrid as hybrid_module
from formowl_auth import ActorContext, FileAuditLogStore, OAuthPrincipal
from formowl_contract import (
    Asset, ContractValidationError, PermissionScope, SessionIdentity, User,
    WorkspaceMember, sha256_json,
)
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
from formowl_gateway.runtime import ConnectedRuntime, ConnectedRuntimeConfig
from formowl_gateway.semantic import SemanticMcpGateway, validate_public_gateway_payload
from formowl_ingestion.extraction import ExtractionInput
from formowl_ingestion.extractors.document.attachment import AttachmentDocumentExtractor
from formowl_ingestion.storage import UploadSessionStore
from formowl_mail import build_mail_upload_session_handler
from formowl_mail.exact import (
    SourceOccurrenceProvider,
    authorized_source_occurrence_scope_fingerprint,
)
from formowl_mail.hybrid import (
    attach_authorized_source_occurrence_providers,
    build_authorized_semantic_observation_session,
    build_authorized_source_backed_effective_graph_view,
)
from formowl_mail.query import (
    build_authorized_observation_snippet_index,
    normalized_authorized_observation_lineages,
    source_occurrence_lineage_from_observation,
)
from formowl_mail.semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    validated_authorized_semantic_source,
)
from test_connected_attachment_hybrid_e2e import (
    REQUESTER_ID,
    SOURCE_SCOPE_ID,
    WORKSPACE_ID,
    _observation,
)
from test_connected_runtime import _FakeHttpClient, _FakeRepository, _write_runtime_environment
from test_issue56_semantic_execution_e2e import _contract_only_runtime


def _candidate_attachment_observations(
    *, child_asset_id: str, content: bytes,
) -> tuple[object, ...]:
    with tempfile.NamedTemporaryFile(suffix=".csv") as child_file:
        child_file.write(content)
        child_file.flush()
        asset = Asset.from_dict({
            "asset_id": child_asset_id,
            "storage_backend_id": "candidate_answer_test_store",
            "object_uri": "formowl://asset/candidate-table-answer",
            "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
            "file_size": len(content),
            "mime_type": "text/csv",
            "created_at": "2026-09-01T00:00:00+00:00",
            "registered_at": "2026-09-01T00:00:00+00:00",
            "owner_user_id": REQUESTER_ID,
            "workspace_id": WORKSPACE_ID,
            "permission_scope": PermissionScope.project(SOURCE_SCOPE_ID).to_dict(),
            "lifecycle_state": "active",
            "source_ref": {
                "source_system": "formowl_mail_attachment",
                "source_type": "email_attachment_occurrence",
                "source_id": "candidate_table_answer_fixture",
            },
        })
        result = AttachmentDocumentExtractor().extract(ExtractionInput(
            asset=asset,
            object_path=Path(child_file.name),
            extractor_run_id="extractor_candidate_table_answer",
            config={"parent_asset_id": "asset_parent_mail"},
            created_at="2026-09-01T00:00:00+00:00",
        ))
    if result.errors or result.warnings:
        raise AssertionError("candidate attachment extraction failed")
    return tuple(result.observations)


class Issue56CandidateTableAnswerMcpE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_table_answer_and_ambiguities_over_normal_mcp(self) -> None:
        parent = _observation(
            observation_id="observation_candidate_answer_parent",
            observation_type="email_attachment_occurrence",
            text="Authorized candidate table",
            payload={"child_asset_id": "asset_candidate_answer"},
            permission_scope=PermissionScope.project(SOURCE_SCOPE_ID).to_dict(),
        )
        children = _candidate_attachment_observations(
            child_asset_id="asset_candidate_answer",
            content=(
                b"IdentifierField,OriginField,SecondaryField\n"
                b"SYN-ITEM-42,REGION-ALPHA,NOTE-A\n"
                b"SYN-DUP-77,REGION-X,NOTE-X\n"
                b"SYN-DUP-77,REGION-Y,NOTE-Y\n"
            ),
        )
        observations = (parent, *children)
        authorized_source = validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=(SOURCE_SCOPE_ID,),
            authorized_permission_scopes=(PermissionScope.project(SOURCE_SCOPE_ID),),
        )
        parent_lineage = source_occurrence_lineage_from_observation(parent, authorized_source=authorized_source)
        lineages = normalized_authorized_observation_lineages(
            observations,
            authorized_source=authorized_source,
            occurrence_lineages=(parent_lineage,),
        )
        authorized_hashes = {item.observation_id: sha256_json(item.to_dict())
                             for item in observations}
        runtime_components = _contract_only_runtime()
        snippet_index, _ = build_authorized_observation_snippet_index(
            (parent,),
            authorized_source=authorized_source,
            occurrence_lineages=(parent_lineage,),
            authorized_observation_hash_by_id={
                parent.observation_id: authorized_hashes[parent.observation_id]
            },
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
                retrieval_observations=(parent,),
                occurrence_lineages=lineages,
                requester_user_id=REQUESTER_ID,
            )
            session_b = build_authorized_semantic_observation_session(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=(parent,),
                retrieval_observations=(parent,),
                occurrence_lineages=(parent_lineage,),
                requester_user_id=REQUESTER_ID,
            )
        ledger = gateway_loader._build_candidate_table_ledger(session)
        self.assertIsNotNone(ledger)
        lookup = gateway_loader.build_authorized_candidate_table_lookup(
            session=session, ledger=ledger)
        direct = gateway_loader.interpret_authorized_candidate_table_query(
            session=session, query_text="SYN-ITEM-42 asks for OriginField", lookup=lookup)
        self.assertIsNotNone(direct)
        self.assertEqual(session.index.profile_fingerprint, session_b.index.profile_fingerprint)
        self.assertNotEqual(session.source_session_binding_fingerprint,
                            session_b.source_session_binding_fingerprint)
        with self.assertRaisesRegex(ContractValidationError, "session binding mismatch"):
            gateway_loader.interpret_authorized_candidate_table_query(
                session=session_b, query_text="SYN-ITEM-42 asks for OriginField",
                lookup=lookup)
        self.assertFalse(hasattr(formowl_mail, "CandidateTableLookup"))
        self.assertFalse(hasattr(formowl_mail, "CandidateTableInterpretation"))
        result_parameters = inspect.signature(type(direct)).parameters
        for fixed_claim in ("status", "canonical_kg", "deterministic_exact", "exact_result"):
            self.assertNotIn(fixed_claim, result_parameters)
        self.assertEqual(direct.status, "candidate_interpretation")
        self.assertFalse(direct.canonical_kg)
        self.assertFalse(direct.deterministic_exact)
        self.assertIsNone(direct.exact_result)
        exact_identifier = "SYN-DUP-77"
        identifier_hash = sha256_json(
            runtime_components.tokenizer_profile.analyze(
                exact_identifier
            ).protected_identifiers[0].exact_token
        )
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
        self.assertIsInstance(table_provider, SourceOccurrenceProvider)
        assert table_provider is not None
        candidate_occurrence = next(
            item
            for item in table_provider.occurrences
            if item.structure_status == "candidate_only"
            and any(identifier_hash in binding[:2] for binding in item.value_bindings)
        )
        provider = replace(
            table_provider,
            provider_id="candidate_table_exact_guard_provider_v1",
            occurrences=(candidate_occurrence,),
            unresolved_count=0,
            authorized_occurrence_scope_count=1,
            extractable_occurrence_scope_count=1,
            source_asset_reason_counts=(),
        )
        exact_projection_field = next(
            field for field, value, *_ in candidate_occurrence.projection_bindings
            if value in {"REGION-X", "REGION-Y"}
        )
        graph = build_authorized_source_backed_effective_graph_view(session=session,
            source_binding_fingerprint=sha256_json(
                "candidate-table-answer-source")).effective_graph_view
        routed_session = attach_authorized_source_occurrence_providers(
            session, (provider,),
        )
        original_query = type(routed_session).query
        for invalid_binding, error_pattern in (
            ("hash", "provenance binding mismatch"),
            ("lineage", "provenance binding mismatch"),
            ("permission", "exact binding is invalid"),
        ):
            with self.subTest(fallback_authority=invalid_binding):
                value_bindings = list(candidate_occurrence.value_bindings)
                first_binding = list(value_bindings[0])
                if invalid_binding in {"hash", "lineage"}:
                    first_binding[2 if invalid_binding == "hash" else 3] = (
                        sha256_json("unbound_candidate_reference")
                    )
                    value_bindings[0] = tuple(first_binding)
                invalid_provider = replace(
                    provider,
                    requester_user_id=(
                        "user_without_source_permission"
                        if invalid_binding == "permission" else REQUESTER_ID
                    ),
                    occurrences=(replace(
                        candidate_occurrence,
                        value_bindings=tuple(value_bindings),
                        projection_bindings=(),
                        structured_column_bindings=(),
                        structure_status=None,
                    ),),
                )
                query_calls = []

                def reject_invalid_fallback(bound_session, **kwargs):
                    query_calls.append(kwargs)
                    if kwargs.get("exact_inventory_kind") is not None:
                        hybrid_module._validated_source_occurrence_providers(
                            session=bound_session, providers=(invalid_provider,),
                        )
                    return original_query(bound_session, **kwargs)

                with patch.object(
                    type(routed_session), "query", new=reject_invalid_fallback,
                ):
                    with self.assertRaisesRegex(ContractValidationError, error_pattern):
                        hybrid_module.execute_bounded_adaptive_query(
                            session=routed_session,
                            query_text="SYN-DUP-77 asks for OriginField",
                            effective_graph_view=graph,
                        )
                self.assertEqual(len(query_calls), 2)
                self.assertIs(
                    query_calls[0]["execution_deadline"],
                    query_calls[1]["execution_deadline"],
                )
        loaded = SimpleNamespace(
            session=session,
            effective_graph_view=graph,
            safe_binding={},
            observations=session.authorized_observations,
            query_bundle=SimpleNamespace(
                mail_import_session=SimpleNamespace(
                    mail_import_session_id=SOURCE_SCOPE_ID,
                ),
            ),
        )
        with (
            patch.object(gateway_loader, "APPROVER_ACTOR", REQUESTER_ID),
            patch.object(gateway_loader, "WORKSPACE_ID", WORKSPACE_ID),
            patch.object(gateway_loader, "_load_approved_sealed_source",
                         return_value=loaded),
            patch.object(gateway_loader, "_validated_owner_safe_binding",
                         return_value={}),
            patch.object(gateway_loader, "_build_mail_source_occurrence_providers",
                         return_value=(provider,)),
            patch.object(
                gateway_loader,
                "build_authorized_candidate_table_lookup",
                wraps=gateway_loader.build_authorized_candidate_table_lookup,
            ) as lookup_builder,
        ):
            retrieval_handler = (
                gateway_loader.build_issue56_production_semantic_retrieval_handler()
            )
        self.assertEqual(lookup_builder.call_count, 1)
        with tempfile.TemporaryDirectory() as temporary_directory:
            config = ConnectedRuntimeConfig.from_env_and_secrets(
                _write_runtime_environment(Path(temporary_directory))
            )
            upload = build_mail_upload_session_handler(
                upload_session_store=UploadSessionStore(config.data_dir),
                audit_store=FileAuditLogStore(config.data_dir),
                expires_at_provider=lambda: "2030-01-01T00:00:00+00:00")
            with patch.object(
                runtime_module.PostgreSQLOAuthRepository,
                "connect",
                return_value=_FakeRepository(),
            ):
                runtime = await ConnectedRuntime.compose(
                    config,
                    semantic_gateway=SemanticMcpGateway(
                        upload_session_handler=upload,
                        retrieval_handler=retrieval_handler,
                    ),
                    http_client=_FakeHttpClient(),
                )
            runtime.preflight = AsyncMock(return_value={"status": "ready"})
            principal = OAuthPrincipal(user_id=REQUESTER_ID,
                external_identity_id="candidate_answer_external",
                oauth_client_id="chatgpt_closed_beta",
                token_session_id="oauth_candidate_answer",
                scopes=("formowl.use",), resource=config.oauth.resource)
            timestamp = "2026-09-01T00:00:00+00:00"
            actor = ActorContext(user=User(user_id=REQUESTER_ID,
                display_name="Candidate answer owner", status="active",
                created_at=timestamp),
                session_identity=SessionIdentity(session_id=principal.token_session_id,
                    selected_user_id=REQUESTER_ID, selected_at=timestamp,
                    selection_method="google_oidc_oauth"),
                workspace_memberships=[
                    WorkspaceMember(user_id=REQUESTER_ID,
                        workspace_id=WORKSPACE_ID, role="owner")],
                current_workspace_id=WORKSPACE_ID,
                current_workspace_role="owner",
                external_identity_id=principal.external_identity_id,
                oauth_client_id=principal.oauth_client_id,
                oauth_token_session_id=principal.token_session_id,
                auth_mode="google_oidc_oauth", production_authentication=True)
            def call(
                client: TestClient, query_text: str, **extra_arguments: object
            ) -> dict[str, object]:
                response = client.post(
                    "/mcp",
                    headers={"Authorization": "Bearer synthetic.token",
                        "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION},
                    json={
                        "jsonrpc": "2.0",
                        "id": sha256_json(query_text),
                        "method": "tools/call",
                        "params": {
                            "name": "query_effective_graph_view",
                            "arguments": {
                                "query_text": query_text,
                                **extra_arguments,
                            },
                        },
                    },
                )
                self.assertEqual(response.status_code, 200)
                result = response.json()["result"]
                self.assertFalse(result["isError"])
                data = result["structuredContent"]["data"]
                validate_public_gateway_payload(data)
                return data
            try:
                with (
                    patch.object(runtime.bridge, "authenticate_access_token",
                                 return_value=principal),
                    patch.object(runtime.bridge, "resolve_actor_context",
                                 return_value=actor),
                    patch.object(runtime.bridge, "record_mcp_authorization_decision",
                                 return_value=None),
                    TestClient(runtime.application.app,
                               raise_server_exceptions=False) as client,
                ):
                    success = call(client, "SYN-ITEM-42 asks for OriginField")
                    duplicate = call(client, "SYN-DUP-77 asks for OriginField")
                    multi_header = call(client,
                        "SYN-ITEM-42 asks for OriginField and SecondaryField")
                    exact = call(
                        client,
                        f"{exact_identifier} 的 {exact_projection_field}",
                        exact_inventory_kind=provider.inventory_kind_alias,
                        exact_field=provider.normalized_field,
                    )
                candidate = success["candidate_interpretation"]
                governed = candidate["governed_citations"]
                citation_hashes = [item["observation_hash"] for item in governed]
                self.assertEqual(success["status"], "replan_required")
                self.assertEqual(success["answer"]["status"], "candidate_interpretation")
                self.assertEqual(success["answer"]["header"], "OriginField")
                self.assertEqual(success["answer"]["value"], "REGION-ALPHA")
                self.assertEqual(len(governed), 4)
                self.assertEqual(len(set(citation_hashes)), 4)
                self.assertEqual(success["citations"], citation_hashes)
                self.assertEqual(candidate["structure_status"], "candidate_only")
                self.assertFalse(candidate["canonical_kg"])
                self.assertFalse(candidate["deterministic_exact"])
                self.assertIsNone(candidate["exact_result"])
                self.assertIsNone(success["exact_result"])
                inventory = exact["exact_inventory"]
                self.assertEqual(exact["status"], "incomplete")
                self.assertEqual(inventory["status"], "incomplete")
                self.assertEqual(inventory["coverage_status"], "incomplete")
                self.assertEqual(inventory["total_count"], 0)
                self.assertEqual(inventory["returned_count"], 0)
                self.assertEqual(inventory["items"], [])
                self.assertEqual(exact["citations"], [])
                self.assertEqual(inventory["candidate_only_occurrence_count"], 1)
                self.assertNotIn("candidate_interpretation", exact)
                self.assertTrue(
                    all(
                        value not in str(exact)
                        for _field, value, _citation, _lineage in (
                            candidate_occurrence.projection_bindings
                        )
                    )
                )
                for rejected in (duplicate, multi_header):
                    self.assertNotIn("candidate_interpretation", rejected)
                    self.assertNotIn("REGION-X", str(rejected))
                    self.assertNotIn("REGION-Y", str(rejected))
                    self.assertNotIn("REGION-ALPHA", str(rejected))
                    self.assertIsNone(rejected.get("exact_result"))
                    self.assertEqual(rejected["citations"], [])
                    self.assertEqual(
                        rejected["query_agent"]["external_replan"]["status"],
                        "required",
                    )
                self.assertEqual(duplicate["status"], "pending_review")
                self.assertEqual(duplicate["query_agent"]["status"], "pending_review")
                self.assertEqual(
                    duplicate["query_agent"]["stop_reason"],
                    "source_binding_clarification_required",
                )
                self.assertEqual(
                    duplicate["query_agent"]["external_replan"]["recommended_query_mode"],
                    "clarify_source_binding",
                )
                self.assertEqual(lookup_builder.call_count, 1)
                public = str((success, duplicate, multi_header))
                self.assertNotIn("object_uri", public)
                self.assertNotIn("tenant_id", public)
                self.assertTrue(all(item.observation_id not in public for item in observations))
            finally:
                await runtime.aclose()
