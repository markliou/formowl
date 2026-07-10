from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_auth import FileAuditLogStore
from formowl_contract import ContractValidationError, Grant, Observation, PermissionScope
from formowl_graph import EffectiveGraphView
from formowl_graph.index import (
    FileVectorStore,
    GraphProjectionEdge,
    GraphProjectionNode,
    VectorRecord,
    VectorSearchResult,
)
from formowl_graph.storage import CandidateAtomStore, CanonicalGraphStore
from formowl_ingestion.storage import ObservationStore
from formowl_retrieval import ObservationStoreEvidenceResolver, RetrievalGateway

NOW = "2026-07-10T08:00:00+00:00"
PUBLIC_SCOPE = {"scope_type": "public", "visibility": "public"}


class KgFirstCrossResourceRetrievalTests(unittest.TestCase):
    def test_kg_first_hit_resolves_mail_slide_and_project_evidence_without_fallback(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-cross-resource")
        observation_store = ObservationStore(temp_dir)
        observations = [
            _observation(
                "obs_optoma_mail",
                "asset_optoma_mail",
                "mail_message",
                "mail",
                {"thread_id": "thread_optoma", "message_id": "msg_optoma"},
                "Optoma requested a revised quotation.",
            ),
            _observation(
                "obs_optoma_slide",
                "asset_optoma_slide",
                "slide_region",
                "slide",
                {"slide_number": 7, "shape_id": "shape_decision"},
                "Decision: accept the revised Optoma quotation.",
            ),
            _observation(
                "obs_optoma_project",
                "asset_optoma_project",
                "work_package_comment",
                "project",
                {"section_id": "work_package_42"},
                "The project owner confirmed the quotation decision.",
            ),
        ]
        for observation in observations:
            observation_store.create(observation)
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(_vector("vec_unused", "obs_optoma_mail"))
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
            minimum_evidence_count=3,
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="What was the final Optoma quotation decision?",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_kg_first",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=[item.observation_id for item in observations],
                    source_asset_ids=[str(item.asset_id) for item in observations],
                )
            ),
        )

        self.assertFalse(result.fallback_used, result.to_dict())
        self.assertIsNone(result.fallback_reason)
        self.assertEqual(result.evidence_coverage, 1.0)
        self.assertEqual(len(result.graph_hits), 1)
        self.assertEqual(
            result.graph_hits[0]["source_observation_ids"],
            ["obs_optoma_mail", "obs_optoma_project", "obs_optoma_slide"],
        )
        self.assertEqual(
            sorted(item["modality"] for item in result.evidence),
            ["mail", "project", "slide"],
        )
        self.assertEqual(
            sorted(result.graph_hits[0]["evidence_locators"]),
            [
                "formowl://observation/obs_optoma_mail",
                "formowl://observation/obs_optoma_project",
                "formowl://observation/obs_optoma_slide",
            ],
        )
        self.assertEqual(result.retrieval_trace.matched_vector_ids, [])
        self.assertEqual(result.candidate_graph_proposal_seeds, [])
        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(CanonicalGraphStore(temp_dir).list_atoms(), [])

    def test_incomplete_graph_evidence_triggers_fallback_and_reviewable_candidate_seed(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-fallback-seed")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_optoma_mail",
                "asset_optoma_mail",
                "mail_message",
                "mail",
                {"thread_id": "thread_optoma"},
                "Optoma requested a revised quotation.",
            )
        )
        observation_store.create(
            _observation(
                "obs_optoma_project_fallback",
                "asset_optoma_project",
                "work_package_comment",
                "project",
                {"section_id": "work_package_fallback"},
                "Project fallback confirms the final decision.",
            )
        )
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(
            _vector(
                "vec_project_fallback",
                "obs_optoma_project_fallback",
                metadata={
                    "evidence_snippet": "Project fallback confirms the final decision.",
                    "asset_id": "asset_untrusted_vector_metadata",
                    "source_observation_ids": ["obs_untrusted_metadata"],
                    "source_asset_ids": ["asset_untrusted_metadata"],
                },
            )
        )
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_fallback",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=["obs_optoma_mail", "obs_optoma_missing"],
                    source_asset_ids=["asset_optoma_mail"],
                )
            ),
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.fallback_reason, "graph_evidence_incomplete_fallback_used")
        self.assertEqual(result.evidence_coverage, 0.5)
        self.assertEqual(result.retrieval_trace.matched_vector_ids, ["vec_project_fallback"])
        self.assertEqual(len(result.candidate_graph_proposal_seeds), 1)
        seed = result.candidate_graph_proposal_seeds[0]
        self.assertEqual(seed["status"], "pending_review")
        self.assertTrue(seed["requires_review"])
        self.assertFalse(seed["canonical_write_performed"])
        self.assertEqual(seed["source_observation_ids"], ["obs_optoma_project_fallback"])
        self.assertEqual(seed["source_asset_ids"], ["asset_optoma_project"])
        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(CanonicalGraphStore(temp_dir).list_atoms(), [])

    def test_unresolved_vector_metadata_lineage_does_not_create_candidate_seed(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-unresolved-fallback-seed")
        observation_store = ObservationStore(temp_dir)
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(
            _vector(
                "vec_unresolved_metadata",
                "obs_missing_authoritative",
                metadata={
                    "asset_id": "asset_untrusted_metadata",
                    "source_observation_ids": ["obs_untrusted_metadata"],
                    "source_asset_ids": ["asset_untrusted_metadata"],
                },
            )
        )
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_unresolved_seed",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=EffectiveGraphView(
                requester_user_id="user_pm",
                user_graph_revision_id="ugraph_empty",
                canonical_graph_revision_id="cgraph_empty",
                ontology_revision_id="ontology_empty",
                assembly_policy_id="policy_empty",
            ),
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.candidate_graph_proposal_seeds, [])
        rendered = json.dumps(result.to_dict(), sort_keys=True)
        self.assertNotIn("obs_untrusted_metadata", rendered)
        self.assertNotIn("asset_untrusted_metadata", rendered)

    def test_graph_miss_and_low_confidence_hits_use_explicit_fallback_reasons(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-miss-low-confidence")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_optoma_mail",
                "asset_optoma_mail",
                "mail_message",
                "mail",
                {"thread_id": "thread_optoma"},
                "Optoma quotation decision.",
            )
        )
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(
            _vector(
                "vec_fallback",
                "obs_fallback",
                metadata={"asset_id": "asset_fallback"},
            )
        )
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )

        graph_miss = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="unrelated payroll policy",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_graph_miss",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=["obs_optoma_mail"],
                    source_asset_ids=["asset_optoma_mail"],
                )
            ),
        )
        low_confidence = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_low_confidence",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=["obs_optoma_mail"],
                    source_asset_ids=["asset_optoma_mail"],
                    confidence=0.3,
                )
            ),
        )

        self.assertEqual(graph_miss.fallback_reason, "graph_miss_fallback_used")
        self.assertEqual(
            low_confidence.fallback_reason,
            "graph_confidence_insufficient_fallback_used",
        )
        self.assertEqual(graph_miss.retrieval_trace.matched_vector_ids, ["vec_fallback"])
        self.assertEqual(low_confidence.retrieval_trace.matched_vector_ids, ["vec_fallback"])
        self.assertEqual(
            [log.metadata["fallback_used"] for log in FileAuditLogStore(temp_dir).list()],
            [True, True],
        )

    def test_permission_denied_or_unsafe_observation_content_is_not_exposed(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-permission-leak")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_private",
                "asset_private",
                "document_block",
                "document",
                {"raw_path": "/srv/private/secret.pdf", "page_number": 2},
                "/srv/private/secret.pdf select * from private_table",
                permission_scope=PermissionScope.project("project_private").to_dict(),
            )
        )
        vector_store = FileVectorStore(temp_dir)
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_denied",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=["obs_private"],
                    source_asset_ids=["asset_private"],
                )
            ),
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.evidence, [])
        rendered = json.dumps(result.to_dict(), sort_keys=True).lower()
        self.assertNotIn("/srv/", rendered)
        self.assertNotIn("select *", rendered)
        self.assertNotIn("private_table", rendered)

    def test_visible_but_fully_redacted_observation_does_not_count_as_complete_evidence(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-redacted-evidence-coverage")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_redacted",
                "asset_redacted",
                "document_block",
                "document",
                {"page_number": 2, "raw_path": "/srv/private/source.pdf"},
                "/srv/private/source.pdf select * from private_table",
            )
        )
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(_vector("vec_safe_fallback", "obs_safe_fallback"))
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_redacted",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(
                _concept_node(
                    source_observation_ids=["obs_redacted"],
                    source_asset_ids=["asset_redacted"],
                )
            ),
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.fallback_reason, "graph_evidence_incomplete_fallback_used")
        self.assertEqual(result.evidence_coverage, 0.0)
        self.assertEqual(
            result.evidence[0]["evidence_locator"], "formowl://observation/obs_redacted"
        )
        self.assertNotIn("snippet", result.evidence[0])
        rendered = json.dumps(result.to_dict(), sort_keys=True).lower()
        self.assertNotIn("/srv/", rendered)
        self.assertNotIn("select *", rendered)

    def test_raw_asset_refs_from_graph_hits_require_explicit_grant(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-raw-asset")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_optoma_mail",
                "asset_optoma_mail",
                "mail_message",
                "mail",
                {"thread_id": "thread_optoma"},
                "Optoma quotation decision.",
            )
        )
        gateway = RetrievalGateway(
            vector_store=FileVectorStore(temp_dir),
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )
        common = {
            "query_embedding": [1.0, 0.0],
            "query_text": "Optoma quotation decision",
            "requester_user_id": "user_pm",
            "workspace_id": "workspace_main",
            "session_id": "session_raw",
            "mode": "raw_asset",
            "now": NOW,
            "effective_graph_view": _view(
                _concept_node(
                    source_observation_ids=["obs_optoma_mail"],
                    source_asset_ids=["asset_optoma_mail"],
                )
            ),
        }

        denied = gateway.query_effective_graph_view(**common)
        self.assertEqual(denied.status, "permission_denied")
        allowed = gateway.query_effective_graph_view(
            **common,
            grants=[_raw_asset_grant()],
        )
        self.assertFalse(allowed.fallback_used)
        self.assertEqual(
            allowed.raw_asset_refs,
            [
                {
                    "source_type": "graph_object",
                    "source_id": "node_optoma_decision",
                    "asset_locator": "formowl://asset/asset_optoma_mail",
                    "access": "explicit_grant_required",
                    "content_returned": False,
                }
            ],
        )

    def test_relation_hits_are_query_scored_and_view_identity_cannot_be_rebound(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-relation-view-identity")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_relation",
                "asset_relation",
                "work_package_relation",
                "project",
                {"section_id": "relation_42"},
                "The Optoma quotation decision supports milestone 42.",
            )
        )
        gateway = RetrievalGateway(
            vector_store=FileVectorStore(temp_dir),
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
        )
        view = EffectiveGraphView(
            requester_user_id="user_pm",
            user_graph_revision_id="ugraph_relation",
            canonical_graph_revision_id="cgraph_relation",
            ontology_revision_id="ontology_relation",
            assembly_policy_id="policy_relation",
            visible_nodes=[
                GraphProjectionNode(
                    node_id="node_optoma",
                    source_type="candidate_entity",
                    source_id="entity_optoma",
                    labels=["optoma", "vendor"],
                    properties={"label": "Optoma vendor"},
                    permission_scope=PUBLIC_SCOPE,
                ),
                GraphProjectionNode(
                    node_id="node_milestone",
                    source_type="candidate_milestone",
                    source_id="milestone_42",
                    labels=["milestone", "42"],
                    properties={"label": "Milestone 42"},
                    permission_scope=PUBLIC_SCOPE,
                ),
            ],
            visible_edges=[
                GraphProjectionEdge(
                    edge_id="edge_optoma_milestone",
                    source_node_id="node_optoma",
                    target_node_id="node_milestone",
                    relation_type="supports_milestone",
                    properties={
                        "label": "Optoma quotation decision supports milestone",
                        "confidence": 0.88,
                        "review_state": "candidate",
                        "source_observation_ids": ["obs_relation"],
                        "source_asset_ids": ["asset_relation"],
                    },
                    permission_scope=PUBLIC_SCOPE,
                )
            ],
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Which Optoma decision supports the milestone?",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_relation",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=view,
        )

        self.assertFalse(result.fallback_used)
        self.assertEqual(result.graph_hits[0]["graph_object_id"], "edge_optoma_milestone")
        self.assertEqual(result.graph_hits[0]["object_type"], "graph_relation")
        with self.assertRaises(ContractValidationError):
            gateway.query_effective_graph_view(
                query_embedding=[1.0, 0.0],
                query_text="Optoma milestone",
                requester_user_id="user_other",
                workspace_id="workspace_main",
                session_id="session_rebind",
                mode="evidence_snippet",
                now=NOW,
                effective_graph_view=view,
            )

    def test_caller_supplied_view_is_permission_filtered_before_matching(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-caller-view-permission-filter")
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(_vector("vec_safe_fallback", "obs_safe_fallback"))
        gateway = RetrievalGateway(vector_store=vector_store)
        private_scope = PermissionScope.project("project_private").to_dict()
        view = EffectiveGraphView(
            requester_user_id="user_pm",
            user_graph_revision_id="ugraph_untrusted",
            canonical_graph_revision_id="cgraph_untrusted",
            ontology_revision_id="ontology_untrusted",
            assembly_policy_id="policy_untrusted",
            visible_nodes=[
                GraphProjectionNode(
                    node_id="node_private_decision",
                    source_type="candidate_frame",
                    source_id="private_source_id",
                    labels=["secret", "merger", "decision"],
                    properties={
                        "label": "Secret merger decision",
                        "review_state": "private_review",
                        "source_observation_ids": ["obs_private"],
                        "source_asset_ids": ["asset_private"],
                    },
                    permission_scope=private_scope,
                ),
                GraphProjectionNode(
                    node_id="node_public_left",
                    source_type="candidate_entity",
                    source_id="public_left",
                    labels=["public", "left"],
                    properties={"label": "Public left"},
                    permission_scope=PUBLIC_SCOPE,
                ),
                GraphProjectionNode(
                    node_id="node_public_right",
                    source_type="candidate_entity",
                    source_id="public_right",
                    labels=["public", "right"],
                    properties={"label": "Public right"},
                    permission_scope=PUBLIC_SCOPE,
                ),
            ],
            visible_edges=[
                GraphProjectionEdge(
                    edge_id="edge_private_merger",
                    source_node_id="node_public_left",
                    target_node_id="node_public_right",
                    relation_type="secret_merger_relation",
                    properties={
                        "label": "Secret merger relation",
                        "review_state": "private_review",
                        "source_observation_ids": ["obs_private"],
                        "source_asset_ids": ["asset_private"],
                    },
                    permission_scope=private_scope,
                )
            ],
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="secret merger decision relation",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_untrusted_view",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=view,
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.fallback_reason, "graph_miss_fallback_used")
        self.assertEqual(result.graph_hits, [])
        self.assertEqual(result.visible_graph_snippets, [])
        self.assertEqual(
            result.retrieval_trace.visible_node_ids,
            ["node_public_left", "node_public_right"],
        )
        rendered = json.dumps(result.to_dict(), sort_keys=True).lower()
        for forbidden in (
            "node_private_decision",
            "edge_private_merger",
            "private_source_id",
            "private_review",
            "project_private",
            "obs_private",
            "asset_private",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_observation_asset_lineage_mismatch_forces_fallback_and_no_raw_ref(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-evidence-lineage-mismatch")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_lineage",
                "asset_actual",
                "mail_message",
                "mail",
                {"thread_id": "thread_lineage"},
                "Optoma quotation decision.",
            )
        )
        vector_store = FileVectorStore(temp_dir)
        vector_store.create(_vector("vec_safe_fallback", "obs_safe_fallback"))
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )
        view = _view(
            _concept_node(
                source_observation_ids=["obs_lineage"],
                source_asset_ids=["asset_unrelated"],
            )
        )
        common = {
            "query_embedding": [1.0, 0.0],
            "query_text": "Optoma quotation decision",
            "requester_user_id": "user_pm",
            "workspace_id": "workspace_main",
            "session_id": "session_lineage",
            "now": NOW,
            "effective_graph_view": view,
        }

        evidence_result = gateway.query_effective_graph_view(
            **common,
            mode="evidence_snippet",
        )
        raw_result = gateway.query_effective_graph_view(
            **common,
            mode="raw_asset",
            grants=[_raw_asset_grant()],
        )

        self.assertTrue(evidence_result.fallback_used)
        self.assertEqual(
            evidence_result.fallback_reason,
            "graph_evidence_incomplete_fallback_used",
        )
        self.assertEqual(evidence_result.evidence_coverage, 0.0)
        self.assertEqual(evidence_result.evidence, [])
        self.assertEqual(evidence_result.graph_hits[0]["source_observation_ids"], [])
        self.assertEqual(evidence_result.graph_hits[0]["source_asset_ids"], [])
        self.assertTrue(raw_result.fallback_used)
        self.assertTrue(
            all(item.get("asset_locator") is None for item in raw_result.raw_asset_refs)
        )
        rendered = json.dumps(
            {"evidence": evidence_result.to_dict(), "raw": raw_result.to_dict()},
            sort_keys=True,
        )
        self.assertNotIn("formowl://asset/asset_unrelated", rendered)
        self.assertNotIn("formowl://asset/asset_actual", rendered)

    def test_raw_asset_mode_requires_audit_and_target_scoped_grant(self) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-raw-audit-scope")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_project_raw",
                "asset_project_raw",
                "work_package_comment",
                "project",
                {"section_id": "work_package_raw"},
                "Optoma quotation decision.",
                permission_scope=PermissionScope.project("project_formowl").to_dict(),
            )
        )
        view = _view(
            GraphProjectionNode(
                **{
                    **_concept_node(
                        source_observation_ids=["obs_project_raw"],
                        source_asset_ids=["asset_project_raw"],
                    ).to_dict(),
                    "permission_scope": PermissionScope.project("project_formowl").to_dict(),
                }
            )
        )
        common = {
            "query_embedding": [1.0, 0.0],
            "query_text": "Optoma quotation decision",
            "requester_user_id": "user_pm",
            "workspace_id": "workspace_main",
            "session_id": "session_raw_scope",
            "mode": "raw_asset",
            "now": NOW,
            "effective_graph_view": view,
            "grants": [
                Grant(
                    grant_id="grant_project_read",
                    owner_user_id="user_owner",
                    grantee_user_id="user_pm",
                    scope_type="project",
                    scope_id="project_formowl",
                    permission="read",
                    expires_at="2026-07-11T00:00:00+00:00",
                ),
                _raw_asset_grant(scope_type="project", scope_id="project_other"),
            ],
        }
        no_audit_gateway = RetrievalGateway(
            vector_store=FileVectorStore(temp_dir),
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
        )
        denied_without_audit = no_audit_gateway.query_effective_graph_view(**common)
        self.assertEqual(denied_without_audit.status, "permission_denied")
        self.assertEqual(
            denied_without_audit.warnings,
            ["raw_asset_mode_requires_audit_store"],
        )

        audit_store = FileAuditLogStore(temp_dir)
        gateway = RetrievalGateway(
            vector_store=FileVectorStore(temp_dir),
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=audit_store,
        )
        denied_wrong_scope = gateway.query_effective_graph_view(**common)
        self.assertEqual(denied_wrong_scope.status, "permission_denied")
        self.assertEqual(denied_wrong_scope.raw_asset_refs, [])
        self.assertEqual(denied_wrong_scope.warnings, ["raw_asset_scope_not_authorized"])
        self.assertEqual(audit_store.list()[-1].action, "retrieval_denied")

        allowed = gateway.query_effective_graph_view(
            **{
                **common,
                "grants": [
                    *common["grants"][:1],
                    _raw_asset_grant(scope_type="project", scope_id="project_formowl"),
                ],
            },
        )
        self.assertEqual(allowed.status, "ok")
        self.assertEqual(
            allowed.raw_asset_refs[0]["asset_locator"],
            "formowl://asset/asset_project_raw",
        )

    def test_relative_internal_paths_are_filtered_from_graph_and_fallback_payloads(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("kg-first-relative-path-filter")
        observation_store = ObservationStore(temp_dir)
        observation_store.create(
            _observation(
                "obs_relative_path",
                "asset_relative_path",
                "document_block",
                "document",
                {"page_number": 4},
                "path=nas/private/customer.pst",
            )
        )
        vector_store = _FixtureVectorSearchStore(
            _vector(
                "vec_relative_path",
                "obs_missing_fallback",
                metadata={
                    "evidence_snippet": r"(scratch\run-42\payload.txt)",
                    "answer_summary": "locator:object_store/private/payload.bin",
                },
            )
        )
        gateway = RetrievalGateway(
            vector_store=vector_store,
            evidence_resolver=ObservationStoreEvidenceResolver(observation_store),
            audit_store=FileAuditLogStore(temp_dir),
        )
        unsafe_node = _concept_node(
            source_observation_ids=["obs_relative_path"],
            source_asset_ids=["asset_relative_path"],
        )
        unsafe_node = GraphProjectionNode(
            **{
                **unsafe_node.to_dict(),
                "properties": {
                    **unsafe_node.properties,
                    "summary": r"debug,workspace\private\graph.json",
                },
            }
        )

        result = gateway.query_effective_graph_view(
            query_embedding=[1.0, 0.0],
            query_text="Optoma quotation decision",
            requester_user_id="user_pm",
            workspace_id="workspace_main",
            session_id="session_relative_path",
            mode="evidence_snippet",
            now=NOW,
            effective_graph_view=_view(unsafe_node),
        )

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.fallback_reason, "graph_miss_fallback_used")
        self.assertEqual(result.graph_hits, [])
        rendered = json.dumps(result.to_dict(), sort_keys=True).lower()
        for forbidden in (
            "nas/private",
            r"scratch\\run-42",
            "object_store/private",
            r"workspace\\private",
        ):
            self.assertNotIn(forbidden, rendered)


def _view(node: GraphProjectionNode) -> EffectiveGraphView:
    return EffectiveGraphView(
        requester_user_id="user_pm",
        user_graph_revision_id="ugraph_optoma",
        canonical_graph_revision_id="cgraph_optoma",
        ontology_revision_id="ontology_optoma",
        assembly_policy_id="policy_optoma",
        visible_nodes=[node],
    )


def _concept_node(
    *,
    source_observation_ids: list[str],
    source_asset_ids: list[str],
    confidence: float = 0.91,
) -> GraphProjectionNode:
    return GraphProjectionNode(
        node_id="node_optoma_decision",
        source_type="candidate_frame",
        source_id="cframe_optoma_decision",
        labels=["optoma", "quotation", "decision"],
        properties={
            "object_type": "candidate_decision_frame",
            "label": "Final Optoma quotation decision",
            "summary": "Optoma quotation final decision",
            "confidence": confidence,
            "review_state": "candidate",
            "source_observation_ids": sorted(source_observation_ids),
            "source_asset_ids": sorted(source_asset_ids),
        },
        permission_scope=PUBLIC_SCOPE,
    )


def _observation(
    observation_id: str,
    asset_id: str,
    observation_type: str,
    modality: str,
    location: dict,
    text: str,
    *,
    permission_scope: dict | None = None,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        extractor_run_id=f"run_{observation_id}",
        observation_type=observation_type,
        modality=modality,
        location=location,
        confidence=0.9,
        permission_scope=permission_scope or PUBLIC_SCOPE,
        created_at=NOW,
        asset_id=asset_id,
        text=text,
    )


def _vector(
    vector_id: str,
    source_id: str,
    *,
    metadata: dict | None = None,
) -> VectorRecord:
    return VectorRecord(
        vector_id=vector_id,
        source_type="observation",
        source_id=source_id,
        source_content_hash=f"sha256:{vector_id}",
        embedding_model="fixture-embedding-v1",
        embedding=[1.0, 0.0],
        permission_scope=PUBLIC_SCOPE,
        metadata=metadata or {},
    )


def _raw_asset_grant(
    *,
    scope_type: str = "workspace",
    scope_id: str = "workspace_main",
) -> Grant:
    return Grant(
        grant_id=f"grant_raw_asset_{scope_type}_{scope_id}",
        owner_user_id="user_owner",
        grantee_user_id="user_pm",
        scope_type=scope_type,
        scope_id=scope_id,
        permission="asset_scoped_access",
        expires_at="2026-07-11T00:00:00+00:00",
    )


class _FixtureVectorSearchStore:
    def __init__(self, record: VectorRecord) -> None:
        self.record = record

    def search(self, *args, **kwargs) -> list[VectorSearchResult]:
        return [VectorSearchResult(record=self.record, score=1.0, stale=False)]


if __name__ == "__main__":
    unittest.main()
