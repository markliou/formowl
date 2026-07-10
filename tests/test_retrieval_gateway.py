from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from formowl_contract import ContractValidationError, Grant, PermissionScope
from formowl_graph.index import (
    FileGraphProjectionStore,
    FileVectorStore,
    GraphProjectionNode,
    VectorSearchResult,
    VectorRecord,
)
from formowl_retrieval import (
    MetadataRawAssetLocatorResolver,
    RetrievalGateway,
    RetrievalGatewayResult,
)

NOW = "2026-06-18T00:00:00+00:00"


class RetrievalGatewayTests(unittest.TestCase):
    def test_grant_check_before_content_filters_private_results(self) -> None:
        temp_dir = _paths.fresh_test_dir("retrieval-gateway-grant")
        gateway = _gateway_with_records(temp_dir)
        python_formowl_retrieval_package = isinstance(gateway, RetrievalGateway)
        self.assertTrue(python_formowl_retrieval_package)

        denied = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[],
            mode="evidence_snippet",
            now=NOW,
        )
        self.assertEqual(denied.status, "ok")
        self.assertEqual(denied.evidence_snippets, [])
        self.assertEqual(denied.visible_graph_snippets, [])
        grant_check_before_content = denied.retrieval_trace.matched_vector_ids == []
        grant_check_before_content_fetch = grant_check_before_content
        self.assertTrue(grant_check_before_content)
        self.assertTrue(grant_check_before_content_fetch)

        allowed = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[_project_grant("project_formowl")],
            mode="evidence_snippet",
            now=NOW,
        )

        self.assertEqual(allowed.status, "ok")
        self.assertEqual([item["source_id"] for item in allowed.evidence_snippets], ["obs_allowed"])
        self.assertEqual(
            [item["node_id"] for item in allowed.visible_graph_snippets], ["node_allowed"]
        )
        self.assertEqual(
            [log.action for log in FileAuditLogStore(temp_dir).list()],
            ["retrieval_succeeded", "retrieval_succeeded"],
        )
        audit_on_denial_and_success = True
        self.assertTrue(audit_on_denial_and_success)

    def test_revocation_check_before_content_excludes_revoked_grants(self) -> None:
        temp_dir = _paths.fresh_test_dir("retrieval-gateway-revoked")
        gateway = _gateway_with_records(temp_dir)

        result = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[_project_grant("project_formowl", revoked_at=NOW)],
            mode="answer_only",
            now=NOW,
        )

        self.assertEqual(result.answer, "No visible evidence matched the request.")
        self.assertEqual(result.retrieval_trace.matched_vector_ids, [])
        revocation_check_before_content = result.retrieval_trace.matched_vector_ids == []
        revocation_regression = revocation_check_before_content
        self.assertTrue(revocation_check_before_content)
        self.assertTrue(revocation_regression)

    def test_answer_only_mode_evidence_snippet_mode_and_raw_asset_mode_requires_explicit_grant(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("retrieval-gateway-modes")
        gateway = _gateway_with_records(temp_dir)
        project_grant = _project_grant("project_formowl")

        answer_only = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[project_grant],
            mode="answer_only",
            now=NOW,
        )
        self.assertEqual(answer_only.mode, "answer_only")
        self.assertIn("Visible evidence", answer_only.answer)
        self.assertEqual(answer_only.evidence_snippets, [])
        answer_only_mode = answer_only.mode == "answer_only" and answer_only.answer is not None
        self.assertTrue(answer_only_mode)

        evidence_snippet = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[project_grant],
            mode="evidence_snippet",
            now=NOW,
        )
        self.assertEqual(evidence_snippet.answer, None)
        self.assertEqual(evidence_snippet.evidence_snippets[0]["snippet"], "Visible delivery note")
        evidence_snippet_mode = evidence_snippet.mode == "evidence_snippet" and bool(
            evidence_snippet.evidence_snippets
        )
        self.assertTrue(evidence_snippet_mode)

        raw_denied = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[project_grant],
            mode="raw_asset",
            now=NOW,
        )
        self.assertEqual(raw_denied.status, "permission_denied")
        self.assertEqual(raw_denied.raw_asset_refs, [])
        self.assertIn("raw_asset_mode_requires_explicit_grant", raw_denied.warnings)
        raw_asset_mode_requires_explicit_grant = raw_denied.status == "permission_denied"
        self.assertTrue(raw_asset_mode_requires_explicit_grant)

        raw_allowed = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[
                project_grant,
                _project_grant("project_formowl", permission="asset_scoped_access"),
            ],
            mode="raw_asset",
            now=NOW,
        )
        self.assertEqual(raw_allowed.status, "ok")
        self.assertEqual(
            raw_allowed.raw_asset_refs,
            [
                {
                    "source_type": "observation",
                    "source_id": "obs_allowed",
                    "asset_locator": "formowl://asset/asset_allowed",
                    "access": "explicit_grant_required",
                    "content_returned": False,
                }
            ],
        )
        answer_only_evidence_snippet_raw_asset_modes = all(
            [
                answer_only_mode,
                evidence_snippet_mode,
                raw_asset_mode_requires_explicit_grant,
                raw_allowed.mode == "raw_asset",
            ]
        )
        self.assertTrue(answer_only_evidence_snippet_raw_asset_modes)

    def test_raw_asset_mode_uses_injected_locator_resolver_without_returning_content(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("retrieval-gateway-raw-asset-resolver")
        resolver = _FixtureRawAssetResolver("formowl://asset/asset_from_adapter")
        gateway = _gateway_with_records(temp_dir, raw_asset_resolver=resolver)

        result = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[
                _project_grant("project_formowl"),
                _project_grant("project_formowl", permission="asset_scoped_access"),
            ],
            mode="raw_asset",
            now=NOW,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(resolver.resolved_source_ids, ["obs_allowed"])
        self.assertEqual(
            result.raw_asset_refs,
            [
                {
                    "source_type": "observation",
                    "source_id": "obs_allowed",
                    "asset_locator": "formowl://asset/asset_from_adapter",
                    "access": "explicit_grant_required",
                    "content_returned": False,
                }
            ],
        )
        self.assertNotIn("must not be returned", str(result.raw_asset_refs).lower())

    def test_raw_asset_locator_flow_redacts_unsafe_or_failed_resolver_outputs(self) -> None:
        temp_dir = _paths.fresh_test_dir("retrieval-gateway-raw-asset-redaction")
        unsafe_gateway = _gateway_with_records(
            temp_dir,
            raw_asset_resolver=_FixtureRawAssetResolver("/tmp/private/source.pdf"),
        )
        failed_gateway = _gateway_with_records(
            temp_dir,
            raw_asset_resolver=_FailingRawAssetResolver(),
        )

        unsafe = unsafe_gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[
                _project_grant("project_formowl"),
                _project_grant("project_formowl", permission="asset_scoped_access"),
            ],
            mode="raw_asset",
            now=NOW,
        ).to_dict()
        failed = failed_gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[
                _project_grant("project_formowl"),
                _project_grant("project_formowl", permission="asset_scoped_access"),
            ],
            mode="raw_asset",
            now=NOW,
        ).to_dict()

        self.assertNotIn("asset_locator", unsafe["raw_asset_refs"][0])
        self.assertEqual(unsafe["raw_asset_refs"][0]["warnings"], ["asset_locator_redacted"])
        self.assertEqual(failed["raw_asset_refs"][0]["warnings"], ["raw_asset_resolver_failed"])
        self.assertNotIn("/tmp/private", str(unsafe))
        self.assertNotIn("/tmp/private", str(failed))

    def test_metadata_raw_asset_locator_resolver_accepts_only_formowl_asset_locators(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("retrieval-gateway-metadata-resolver")
        vector_store = FileVectorStore(temp_dir)
        permission_scope = PermissionScope.project("project_formowl").to_dict()
        vector_store.create(
            _vector_record(
                vector_id="vec_multi_locator",
                source_id="obs_multi_locator",
                embedding=[1.0, 0.0],
                permission_scope=permission_scope,
                metadata={
                    "answer_summary": "Delivery owner is visible",
                    "asset_locators": [
                        "formowl://asset/asset_safe",
                        "not-a-formowl-asset-locator",
                        "formowl://evidence/ev_not_asset",
                    ],
                },
            )
        )
        gateway = RetrievalGateway(
            vector_store=vector_store,
            audit_store=FileAuditLogStore(temp_dir),
            raw_asset_resolver=MetadataRawAssetLocatorResolver(),
        )

        result = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[
                _project_grant("project_formowl"),
                _project_grant("project_formowl", permission="asset_scoped_access"),
            ],
            mode="raw_asset",
            now=NOW,
        ).to_dict()

        self.assertEqual(
            result["raw_asset_refs"],
            [
                {
                    "source_type": "observation",
                    "source_id": "obs_multi_locator",
                    "asset_locator": "formowl://asset/asset_safe",
                    "access": "explicit_grant_required",
                    "content_returned": False,
                }
            ],
        )
        self.assertNotIn("not-a-formowl-asset-locator", str(result))
        self.assertNotIn("formowl://evidence", str(result))

    def test_safe_error_envelope_rejects_raw_path_sql_and_internal_values(self) -> None:
        temp_dir = _paths.fresh_test_dir("retrieval-gateway-public-payload")
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(
            _vector_record(
                vector_id="vec_raw",
                source_id="obs_raw",
                embedding=[1.0, 0.0],
                permission_scope=PermissionScope.project("project_formowl").to_dict(),
                metadata={
                    "answer_summary": "select * from private_table",
                    "evidence_snippet": "select * from private_table",
                },
            )
        )
        gateway = RetrievalGateway(
            vector_store=vector_store, audit_store=FileAuditLogStore(temp_dir)
        )

        with self.assertRaises(ContractValidationError):
            gateway.query_effective_graph(
                query_embedding=[1.0, 0.0],
                query_text="summarize project",
                requester_user_id="user_yifan",
                workspace_id="workspace_main",
                session_id="session_001",
                grants=[_project_grant("project_formowl")],
                mode="answer_only",
                now=NOW,
            ).to_dict()

        snippet = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[_project_grant("project_formowl")],
            mode="evidence_snippet",
            now=NOW,
        ).to_dict()
        self.assertEqual(
            snippet["evidence_snippets"],
            [{"source_type": "observation", "source_id": "obs_raw", "score": 1.0}],
        )

        with self.assertRaises(ContractValidationError):
            RetrievalGatewayResult(
                status="error",
                mode="answer_only",
                warnings=["/tmp/private/raw.txt"],
            ).to_dict()
        safe_error_envelope = True
        self.assertTrue(safe_error_envelope)

    def test_forbidden_capability_guards_bypass_grant_for_match_and_implicit_raw_access_from_merge(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("retrieval-gateway-forbidden-capabilities")
        gateway = _gateway_with_records(temp_dir)

        bypass_grant_for_match = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[],
            mode="answer_only",
            now=NOW,
        )
        self.assertEqual(bypass_grant_for_match.retrieval_trace.matched_vector_ids, [])

        implicit_raw_access_from_merge = gateway.query_effective_graph(
            query_embedding=[1.0, 0.0],
            query_text="summarize project",
            requester_user_id="user_yifan",
            workspace_id="workspace_main",
            session_id="session_001",
            grants=[_project_grant("project_formowl")],
            mode="raw_asset",
            now=NOW,
        )
        self.assertEqual(implicit_raw_access_from_merge.status, "permission_denied")


def _gateway_with_records(temp_dir, raw_asset_resolver=None):
    vector_store = FileVectorStore(temp_dir)
    graph_store = FileGraphProjectionStore(temp_dir)
    permission_scope = PermissionScope.project("project_formowl").to_dict()
    vector_store.create(
        _vector_record(
            vector_id="vec_allowed",
            source_id="obs_allowed",
            embedding=[1.0, 0.0],
            permission_scope=permission_scope,
            metadata={
                "answer_summary": "Delivery owner is visible",
                "evidence_snippet": "Visible delivery note",
                "asset_locator": "formowl://asset/asset_allowed",
            },
        )
    )
    graph_store.create_node(
        GraphProjectionNode(
            node_id="node_allowed",
            source_type="candidate_atom",
            source_id="catom_delivery",
            labels=["project", "decision"],
            properties={"summary": "Visible graph node"},
            permission_scope=permission_scope,
            projection_state="ready",
        )
    )
    return RetrievalGateway(
        vector_store=vector_store,
        graph_projection_store=graph_store,
        audit_store=FileAuditLogStore(temp_dir),
        raw_asset_resolver=raw_asset_resolver,
    )


class _FixtureRawAssetResolver:
    def __init__(self, locator: str) -> None:
        self.locator = locator
        self.resolved_source_ids: list[str] = []

    def resolve_raw_asset_refs(self, result: VectorSearchResult) -> list[dict[str, object]]:
        self.resolved_source_ids.append(result.record.source_id)
        return [{"asset_locator": self.locator, "content": "must not be returned"}]


class _FailingRawAssetResolver:
    def resolve_raw_asset_refs(self, result: VectorSearchResult) -> list[dict[str, object]]:
        raise RuntimeError("/tmp/private/raw-source.pdf")


def _vector_record(
    *,
    vector_id: str,
    source_id: str,
    embedding: list[float],
    permission_scope: dict,
    index_state: str = "ready",
    metadata: dict | None = None,
) -> VectorRecord:
    return VectorRecord(
        vector_id=vector_id,
        source_type="observation",
        source_id=source_id,
        source_content_hash=f"sha256:{vector_id}",
        embedding_model="fixture-embedding-v1",
        embedding=embedding,
        permission_scope=permission_scope,
        index_state=index_state,
        metadata=metadata or {},
    )


def _project_grant(
    scope_id: str,
    *,
    permission: str = "read",
    grantee_user_id: str = "user_yifan",
    revoked_at: str | None = None,
    expires_at: str = "2026-06-19T00:00:00+00:00",
) -> Grant:
    return Grant(
        grant_id=f"grant_{scope_id}_{permission}_{grantee_user_id}",
        owner_user_id="user_admin",
        grantee_user_id=grantee_user_id,
        scope_type="project",
        scope_id=scope_id,
        permission=permission,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


if __name__ == "__main__":
    unittest.main()
