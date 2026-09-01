from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields, FrozenInstanceError, replace
import inspect
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from typing import Sequence

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_core import (
    DenseEmbeddingUnavailableError,
    ISSUE56_TARGET_DENSE_MODEL_ID,
    ISSUE56_TARGET_DENSE_MODEL_REVISION,
    Issue56TargetRuntimeComponents,
    SentenceTransformerDenseEncoder,
    build_issue56_execution_component_binding,
    issue56_target_dense_embedding_profile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_mail import (
    DEFAULT_SEMANTIC_PLAN_LIMITS,
    ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
    ISSUE56_TARGET_RUNTIME_METHOD_ID,
    SemanticPlanLimits,
    build_authorized_semantic_mail_session,
    build_authorized_source_backed_effective_graph_view,
    deterministic_query_class,
    route_semantic_query,
    run_authorized_semantic_mail_query,
    validate_semantic_query_plan,
)
from formowl_mail import hybrid as hybrid_module
from formowl_mail import exact as exact_module
from formowl_mail.exact import (
    AuthorizedSourceOccurrence,
    SourceOccurrenceProvider,
    authorized_source_occurrence_scope_fingerprint,
    execute_deterministic_source_occurrence_inventory,
)
from formowl_mail.semantic_plan import repair_relation_plan_once
from scripts.issue56_semantic_execution_smoke import (
    ALLOWED_RELATIONS,
    REQUESTER_USER_ID,
    WORKSPACE_ID,
    _semantic_poc_identity_scope,
    build_semantic_poc_inputs,
)

ROOT = Path(__file__).resolve().parents[1]


class Issue56SemanticExecutionEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = _contract_only_runtime()
        cls.inputs = build_semantic_poc_inputs()

    def test_semantic_runtime_helpers_are_module_bound(self) -> None:
        for helper_name in (
            "_semantic_evidence_scores",
            "_bounded_semantic_answer_citation_hashes",
            "_deterministic_required_relation_slots",
            "_rank_relation_graph_paths",
            "_minimal_relation_proof_citations",
            "_deterministic_relation_fallback_slots",
            "_matched_relation_fallback_seed_nodes",
            "_connected_relation_fallback_citations",
            "_execute_bounded_relation_fallback",
            "_result_lineage_audit",
            "build_evidence_identity_lineage_crosswalk",
        ):
            self.assertTrue(callable(getattr(hybrid_module, helper_name, None)))
            self.assertNotIn(
                helper_name,
                inspect.getclosurevars(hybrid_module.AuthorizedSemanticMailSession.query).unbound,
            )

    def test_typed_router_and_plan_validation_fail_closed_without_scope_widening(
        self,
    ) -> None:
        self.assertEqual(
            deterministic_query_class("PO470002002 交期"),
            "evidence_lookup",
        )
        self.assertEqual(
            deterministic_query_class("PO470002002 與供應商的關係"),
            "relation_reasoning",
        )
        self.assertEqual(
            deterministic_query_class("列出全部採購單並計數"),
            "exact_set_or_inventory",
        )
        self.assertEqual(
            deterministic_query_class("請摘要目前採購狀況"),
            "global_summarization",
        )
        source_scope_ids = (
            self.inputs.current_bundle.mail_evidence_bundle_id,
            self.inputs.superseded_bundle.mail_evidence_bundle_id,
        )
        plan = route_semantic_query(
            query_text="PO470002002 與供應商的關係",
            requester_user_id=REQUESTER_USER_ID,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=source_scope_ids,
            effective_graph_view=self.inputs.effective_graph_view,
            allowed_relation_types=ALLOWED_RELATIONS,
        )
        self.assertEqual(plan.query_class, "relation_reasoning")
        self.assertEqual(plan.max_hops, 2)
        self.assertEqual(plan.repair_attempt_count, 0)

        with self.assertRaisesRegex(
            ContractValidationError,
            "class override is invalid",
        ):
            route_semantic_query(
                query_text="PO470002002 交期",
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
                source_scope_ids=source_scope_ids,
                effective_graph_view=self.inputs.effective_graph_view,
                exact_normalized_field="participant.any.local_part",
                exact_predicate="source_occurrence_involves",
                exact_operator="case_insensitive_exact",
                query_class_override="evidence_lookup",
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "class override is invalid",
        ):
            route_semantic_query(
                query_text="PO470002002 交期",
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
                source_scope_ids=source_scope_ids,
                effective_graph_view=self.inputs.effective_graph_view,
                query_class_override="exact_set_or_inventory",
            )

        repaired = validate_semantic_query_plan(
            replace(plan, candidate_limit=999),
            effective_graph_view=self.inputs.effective_graph_view,
            authorized_workspace_id=WORKSPACE_ID,
            authorized_source_scope_ids=source_scope_ids,
            supported_relation_types=ALLOWED_RELATIONS,
        )
        self.assertEqual(
            repaired.candidate_limit,
            DEFAULT_SEMANTIC_PLAN_LIMITS.max_candidates,
        )
        self.assertEqual(repaired.repair_attempt_count, 1)

        with self.assertRaisesRegex(
            ContractValidationError,
            "widen source scope",
        ):
            validate_semantic_query_plan(
                replace(plan, source_scope_ids=(*source_scope_ids, "bundle_unapproved")),
                effective_graph_view=self.inputs.effective_graph_view,
                authorized_workspace_id=WORKSPACE_ID,
                authorized_source_scope_ids=source_scope_ids,
                supported_relation_types=ALLOWED_RELATIONS,
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "revision pin mismatch",
        ):
            validate_semantic_query_plan(
                replace(plan, ontology_revision_id="ontology_unpinned"),
                effective_graph_view=self.inputs.effective_graph_view,
                authorized_workspace_id=WORKSPACE_ID,
                authorized_source_scope_ids=source_scope_ids,
                supported_relation_types=ALLOWED_RELATIONS,
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "unsupported hop",
        ):
            validate_semantic_query_plan(
                replace(
                    plan,
                    allowed_paths=(("unbounded_association", "out"),),
                ),
                effective_graph_view=self.inputs.effective_graph_view,
                authorized_workspace_id=WORKSPACE_ID,
                authorized_source_scope_ids=source_scope_ids,
                supported_relation_types=ALLOWED_RELATIONS,
            )

    def test_relation_reasoning_traverses_two_messages_with_authorized_evidence(
        self,
    ) -> None:
        result = self._run(
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            allowed_relation_types=ALLOWED_RELATIONS,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.query_class, "relation_reasoning")
        self.assertEqual(result.claim_strength, "bounded_relation")
        self.assertEqual(result.dense_encoder_status, "pinned_real_e5")
        self.assertGreater(result.rejected_hop_count, 0)
        two_hop_paths = [path for path in result.graph_paths if path.hop_count == 2]
        self.assertEqual(len(two_hop_paths), 1)
        self.assertEqual(len(two_hop_paths[0].cited_observation_hashes), 2)
        self.assertTrue(all(hop.cited_observation_hashes for hop in two_hop_paths[0].hops))
        self.assertTrue(
            set(two_hop_paths[0].cited_observation_hashes).issubset(result.answer_citation_hashes)
        )
        self.assertTrue(result.scores)
        for score in result.scores:
            self.assertGreaterEqual(score.lexical_score, 0.0)
            self.assertGreaterEqual(score.dense_score, 0.0)
            self.assertGreaterEqual(score.entity_score, 0.0)
            self.assertGreaterEqual(score.graph_path_score, 0.0)
            self.assertGreaterEqual(score.temporal_current_score, 0.0)
            self.assertEqual(score.provenance_coverage_score, 1.0)
            self.assertLessEqual(score.ontology_bonus, score.ontology_bonus_cap)

    def test_relation_answer_cites_only_minimal_slot_supporting_graph_evidence(
        self,
    ) -> None:
        irrelevant_edge = next(
            edge
            for edge in self.inputs.effective_graph_view.visible_edges
            if edge.relation_type == "unbounded_association"
        )
        view_with_allowed_distractor = replace(
            self.inputs.effective_graph_view,
            visible_edges=[
                *self.inputs.effective_graph_view.visible_edges,
                replace(
                    irrelevant_edge,
                    edge_id="edge_issue56_allowed_but_irrelevant",
                    relation_type="origin_in",
                ),
            ],
        )
        current_observations = self.inputs.observations_by_bundle_id[
            self.inputs.current_bundle.mail_evidence_bundle_id
        ]
        required_hashes = {
            sha256_json(
                next(
                    observation
                    for observation in current_observations
                    if observation.observation_id == "obs_issue56_semantic_current_body_1"
                ).to_dict()
            ),
            sha256_json(
                next(
                    observation
                    for observation in current_observations
                    if observation.observation_id == "obs_issue56_semantic_current_body_2"
                ).to_dict()
            ),
        }
        irrelevant_hash = sha256_json(
            next(
                observation
                for observation in current_observations
                if observation.observation_id == "obs_issue56_semantic_current_body_3"
            ).to_dict()
        )

        result = self._run(
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            effective_graph_view=view_with_allowed_distractor,
            allowed_relation_types=ALLOWED_RELATIONS,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(set(result.answer_citation_hashes), required_hashes)
        self.assertNotIn(irrelevant_hash, result.answer_citation_hashes)
        self.assertTrue(result.graph_paths)
        self.assertTrue(
            set(result.answer_citation_hashes)
            <= {
                evidence_hash
                for path in result.graph_paths
                for evidence_hash in path.cited_observation_hashes
            }
        )

    def test_relation_answer_fails_closed_when_required_slot_is_disconnected(
        self,
    ) -> None:
        disconnected_view = replace(
            self.inputs.effective_graph_view,
            visible_edges=[
                edge
                for edge in self.inputs.effective_graph_view.visible_edges
                if edge.relation_type != "origin_in"
            ],
        )
        origin_observation = next(
            observation
            for observation in self.inputs.observations_by_bundle_id[
                self.inputs.current_bundle.mail_evidence_bundle_id
            ]
            if observation.observation_id == "obs_issue56_semantic_current_body_2"
        )
        origin_observation_hash = sha256_json(origin_observation.to_dict())

        result = self._run(
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            effective_graph_view=disconnected_view,
            allowed_relation_types=ALLOWED_RELATIONS,
        )

        self.assertEqual(result.status, "no_answer")
        self.assertEqual(result.answer_citation_hashes, ())
        self.assertTrue(result.graph_paths)
        self.assertIn(
            origin_observation_hash,
            {score.source_observation_hash for score in result.scores},
        )
        self.assertIn("required_relation_slots_unresolved", result.warnings)

    def test_strict_relation_precedes_fallback_and_preserves_fingerprint(self) -> None:
        first = self._run(
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            allowed_relation_types=ALLOWED_RELATIONS,
        )
        second = self._run(
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            allowed_relation_types=ALLOWED_RELATIONS,
        )

        self.assertEqual(first.status, "ok")
        self.assertEqual(first.plan_fingerprint, second.plan_fingerprint)
        self.assertEqual(first.result_fingerprint, second.result_fingerprint)
        self.assertEqual(first.repair_attempt_count, 0)
        self.assertIsNone(first.relation_repair_policy_fingerprint)
        self.assertIsNone(first.relation_repair_vocabulary_fingerprint)
        self.assertFalse(any("fallback_repair" in warning for warning in first.warnings))

    def test_relation_fallback_uses_one_connected_authorized_multi_hop_proof(
        self,
    ) -> None:
        lineaged_view = _view_with_lineaged_relation_terms(self.inputs.effective_graph_view)
        result = self._run(
            query_text=("PO470002002 與 ORIGIN-TAIWAN-01 的供應商資訊關係"),
            effective_graph_view=lineaged_view,
            allowed_relation_types=ALLOWED_RELATIONS,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_attempt_count, 1)
        self.assertRegex(
            result.relation_repair_policy_fingerprint or "",
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertRegex(
            result.relation_repair_vocabulary_fingerprint or "",
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertIn(
            "bounded_relation_fallback_repair_succeeded",
            result.warnings,
        )
        selected_paths = [
            path
            for path in result.graph_paths
            if path.cited_observation_hashes == result.answer_citation_hashes
        ]
        self.assertEqual(len(selected_paths), 1)
        self.assertEqual(selected_paths[0].hop_count, 2)
        self.assertEqual(
            _path_node_hashes(selected_paths[0]),
            {
                sha256_json("node_issue56_po_current"),
                sha256_json("node_issue56_supplier"),
                sha256_json("node_issue56_origin"),
            },
        )
        authorized_hashes = {
            sha256_json(observation.to_dict())
            for observations in self.inputs.observations_by_bundle_id.values()
            for observation in observations
            if observations
            is not self.inputs.observations_by_bundle_id[
                self.inputs.denied_bundle.mail_evidence_bundle_id
            ]
        }
        expected_citations = tuple(
            sorted(
                sha256_json(observation.to_dict())
                for observation in self.inputs.observations_by_bundle_id[
                    self.inputs.current_bundle.mail_evidence_bundle_id
                ]
                if observation.observation_id
                in {
                    "obs_issue56_semantic_current_body_1",
                    "obs_issue56_semantic_current_body_2",
                }
            )
        )
        self.assertEqual(result.answer_citation_hashes, expected_citations)
        self.assertEqual(
            {
                citation
                for hop in selected_paths[0].hops
                for citation in hop.cited_observation_hashes
            },
            set(result.answer_citation_hashes),
        )
        self.assertTrue(set(result.answer_citation_hashes).issubset(authorized_hashes))
        for hop in selected_paths[0].hops:
            self.assertTrue(hop.cited_observation_hashes)
            self.assertTrue(set(hop.cited_observation_hashes).issubset(authorized_hashes))

    def test_relation_fallback_uses_maximal_authorized_cjk_concept_not_fragments(
        self,
    ) -> None:
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=self.inputs.bundles,
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        authorized_hash_by_id = dict(session.authorized_observation_hashes)
        candidates_by_hash = {
            candidate.source_observation_hash: candidate for candidate in session.index.candidates
        }
        selection = hybrid_module._deterministic_relation_fallback_slots(
            "PO470002002 與 ORIGIN-TAIWAN-01 的供應商資訊關係",
            tokenizer_profile=session.index._runtime_components.tokenizer_profile,
            document_frequency=dict(session.index.document_frequency),
            document_count=len(session.index.candidates),
            index_fingerprint=session.index.index_fingerprint,
            graph_revision_fingerprint=hybrid_module._graph_revision_fingerprint(
                self.inputs.effective_graph_view
            ),
            effective_graph_view=self.inputs.effective_graph_view,
            authorized_observation_hash_by_id=authorized_hash_by_id,
            candidates_by_hash=candidates_by_hash,
        )

        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(selection.concept_term_hashes, (sha256_json("供應商"),))
        self.assertNotIn(sha256_json("供應"), selection.concept_term_hashes)
        self.assertNotIn(sha256_json("應商"), selection.concept_term_hashes)
        self.assertNotIn(sha256_json("資訊"), selection.concept_term_hashes)

    def test_relation_fallback_can_targeted_retraverse_safe_visible_nodes(
        self,
    ) -> None:
        lineaged_view = _view_with_lineaged_relation_terms(self.inputs.effective_graph_view)
        real_traversal = hybrid_module._bounded_graph_traversal
        traversal_calls = []

        def first_empty_then_real(**kwargs):
            traversal_calls.append(kwargs)
            if len(traversal_calls) == 1:
                return (), 0
            return real_traversal(**kwargs)

        with patch.object(
            hybrid_module,
            "_bounded_graph_traversal",
            side_effect=first_empty_then_real,
        ):
            result = self._run(
                query_text=("PO470002002 與 ORIGIN-TAIWAN-01 的供應商資訊關係"),
                effective_graph_view=lineaged_view,
                allowed_relation_types=ALLOWED_RELATIONS,
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_attempt_count, 1)
        self.assertEqual(len(traversal_calls), 2)
        self.assertEqual(
            result.warnings.count("bounded_relation_targeted_retraversal_attempted"),
            1,
        )
        self.assertNotIn("relation_proof_slots", traversal_calls[0])
        self.assertIsNotNone(traversal_calls[1]["relation_proof_slots"])
        initial_projection = traversal_calls[0]["relation_projection"]
        self.assertIsNotNone(initial_projection)
        initial_anchor_hashes = {
            sha256_json(node_id) for node_id in initial_projection.initial_query_anchor_node_ids
        }
        self.assertTrue(initial_anchor_hashes)

        selected_paths = [
            path
            for path in result.graph_paths
            if path.cited_observation_hashes == result.answer_citation_hashes
        ]
        self.assertEqual(len(selected_paths), 1)
        selected_path = selected_paths[0]
        self.assertEqual(selected_path.hop_count, 2)
        selected_node_hashes = _path_node_hashes(selected_path)
        self.assertTrue(selected_node_hashes & initial_anchor_hashes)
        self.assertEqual(
            selected_node_hashes,
            {
                sha256_json("node_issue56_po_current"),
                sha256_json("node_issue56_supplier"),
                sha256_json("node_issue56_origin"),
            },
        )
        projection = traversal_calls[1]["relation_projection"]
        self.assertIn(
            sha256_json("po470002002"),
            projection.node_by_id["node_issue56_po_current"].bound_candidate_identifier_term_hashes
            & projection.node_by_id["node_issue56_po_current"].protected_term_hashes,
        )
        self.assertIn(
            sha256_json("origin-taiwan-01"),
            projection.node_by_id["node_issue56_origin"].bound_candidate_identifier_term_hashes
            & projection.node_by_id["node_issue56_origin"].protected_term_hashes,
        )
        self.assertIn(
            sha256_json("供應商"),
            projection.node_by_id["node_issue56_supplier"].bound_candidate_concept_term_hashes
            & projection.node_by_id["node_issue56_supplier"].source_term_hashes,
        )
        authorized_hashes = {
            sha256_json(observation.to_dict())
            for observations in self.inputs.observations_by_bundle_id.values()
            for observation in observations
            if observations
            is not self.inputs.observations_by_bundle_id[
                self.inputs.denied_bundle.mail_evidence_bundle_id
            ]
        }
        expected_citations = tuple(
            sorted(
                sha256_json(observation.to_dict())
                for observation in self.inputs.observations_by_bundle_id[
                    self.inputs.current_bundle.mail_evidence_bundle_id
                ]
                if observation.observation_id
                in {
                    "obs_issue56_semantic_current_body_1",
                    "obs_issue56_semantic_current_body_2",
                }
            )
        )
        self.assertEqual(result.answer_citation_hashes, expected_citations)
        self.assertEqual(
            {citation for hop in selected_path.hops for citation in hop.cited_observation_hashes},
            set(result.answer_citation_hashes),
        )
        for hop in selected_path.hops:
            self.assertTrue(hop.cited_observation_hashes)
            self.assertTrue(set(hop.cited_observation_hashes).issubset(authorized_hashes))

    def test_relation_fallback_negatives_fail_closed_and_repair_exhausts(
        self,
    ) -> None:
        disconnected_view = replace(
            self.inputs.effective_graph_view,
            visible_edges=[
                edge
                for edge in self.inputs.effective_graph_view.visible_edges
                if edge.relation_type != "origin_in"
            ],
        )
        disconnected = self._run(
            query_text=("PO470002002 與 ORIGIN-TAIWAN-01 的供應商資訊關係"),
            effective_graph_view=disconnected_view,
            allowed_relation_types=ALLOWED_RELATIONS,
        )
        self.assertEqual(disconnected.status, "no_answer")
        self.assertEqual(disconnected.repair_attempt_count, 1)
        self.assertEqual(disconnected.answer_citation_hashes, ())
        self.assertIn(
            "bounded_relation_fallback_repair_exhausted",
            disconnected.warnings,
        )

        missing_identifier = self._run(
            query_text=("PO470002002 與 ORIGIN-MISSING-99 的供應商資訊關係"),
            allowed_relation_types=ALLOWED_RELATIONS,
        )
        self.assertEqual(missing_identifier.status, "no_answer")
        self.assertEqual(missing_identifier.repair_attempt_count, 0)
        self.assertEqual(missing_identifier.answer_citation_hashes, ())

        denied = self._run(
            query_text=("SECRET-PO-99001 與 PRIVATE-TERM-77 的供應商資訊關係"),
            allowed_relation_types=ALLOWED_RELATIONS,
            mail_evidence_bundle_id=(self.inputs.denied_bundle.mail_evidence_bundle_id),
        )
        self.assertEqual(denied.status, "permission_denied")
        self.assertEqual(denied.repair_attempt_count, 0)
        self.assertEqual(denied.materialized_candidate_count, 0)

        source_scope_ids = (
            self.inputs.current_bundle.mail_evidence_bundle_id,
            self.inputs.superseded_bundle.mail_evidence_bundle_id,
        )
        strict_plan = route_semantic_query(
            query_text="PO470002002 與供應商的關係",
            requester_user_id=REQUESTER_USER_ID,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=source_scope_ids,
            effective_graph_view=self.inputs.effective_graph_view,
            allowed_relation_types=ALLOWED_RELATIONS,
        )
        repaired_plan = repair_relation_plan_once(
            strict_plan,
            seed_node_ids=(),
            required_identifier_term_hashes=(sha256_json("PO470002002"),),
            required_concept_term_hashes=(sha256_json("供應商"),),
            policy_fingerprint=sha256_json("relation_repair_policy"),
            vocabulary_fingerprint=sha256_json("relation_repair_vocabulary"),
        )
        self.assertEqual(repaired_plan.repair_attempt_count, 1)
        self.assertIn("relation_repair", repaired_plan.to_safe_dict())
        with self.assertRaisesRegex(
            ContractValidationError,
            "repair budget is exhausted",
        ):
            repair_relation_plan_once(
                repaired_plan,
                seed_node_ids=(),
                required_identifier_term_hashes=(sha256_json("PO470002002"),),
                required_concept_term_hashes=(sha256_json("供應商"),),
                policy_fingerprint=sha256_json("relation_repair_policy"),
                vocabulary_fingerprint=sha256_json("relation_repair_vocabulary"),
            )

    def test_exact_inventory_enumerates_full_authorized_scope_with_coverage(
        self,
    ) -> None:
        result = self._run(
            query_text="列出全部採購單並計數",
            exact_inventory_kind="purchase_order",
        )

        self.assertEqual(result.status, "complete_authorized_scope")
        self.assertEqual(result.exact_executor_status, "complete_authorized_scope")
        exact = result.exact_result
        assert exact is not None
        self.assertEqual(exact.exact_count, 2)
        self.assertEqual(exact.returned_item_count, 2)
        self.assertTrue(exact.coverage.authorized_scope_complete)
        self.assertEqual(exact.coverage.missing_evidence_record_count, 0)
        self.assertEqual(exact.cited_observation_count, 2)
        self.assertEqual(result.scores, ())
        expected_citations = tuple(
            dict.fromkeys(
                observation_hash
                for item in exact.items
                for observation_hash in item.cited_observation_hashes
            )
        )
        self.assertEqual(result.answer_citation_hashes, expected_citations)
        assert result.lineage_audit is not None
        self.assertEqual(
            set(result.lineage_audit.exact_item_evidence_hashes),
            set(expected_citations),
        )
        self.assertEqual(result.lineage_audit.unresolved_evidence_hashes, ())

        bounded = self._run(
            query_text="列出全部採購單並計數",
            exact_inventory_kind="purchase_order",
            limits=SemanticPlanLimits(max_results=1),
        )
        bounded_exact = bounded.exact_result
        assert bounded_exact is not None
        self.assertEqual(bounded.status, "incomplete")
        self.assertEqual(bounded_exact.exact_count, 2)
        self.assertEqual(bounded_exact.returned_item_count, 0)
        self.assertFalse(bounded_exact.coverage.authorized_scope_complete)

    def test_source_occurrence_provider_rejects_stale_lineage_fingerprint(
        self,
    ) -> None:
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=(self.inputs.current_bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        query_text = "列出全部 PO470002002 郵件"
        identifier_hash = hybrid_module._deterministic_exact_filter_slots(
            query_text,
            tokenizer_profile=self.runtime.tokenizer_profile,
        ).identifier_hashes[0]
        source_observation = next(
            observation
            for observation in session.authorized_observations
            if sha256_json(observation.to_dict()) == self.inputs.current_observation_hash
        )
        source_lineage = next(
            lineage
            for lineage in session.occurrence_lineages
            if lineage.source_observation_id == source_observation.observation_id
        )
        scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_observation_hashes=session.authorized_observation_hashes,
            source_session_binding_fingerprint=(
                session.source_session_binding_fingerprint or ""
            ),
        )
        provider = SourceOccurrenceProvider(
            provider_id="mail_source_occurrence_provider_v1",
            inventory_kind_alias="mail_observation",
            resource_kind="mail_message_occurrence",
            normalized_field="participant.any.local_part",
            predicate="source_occurrence_involves",
            operator="case_insensitive_exact",
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_scope_fingerprint=scope_fingerprint,
            occurrences=(
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json(source_lineage.occurrence_id),
                    value_bindings=(
                        (
                            identifier_hash,
                            sha256_json("synthetic@example.test"),
                            self.inputs.current_observation_hash,
                            sha256_json("stale_occurrence_lineage"),
                        ),
                    ),
                ),
            ),
        )
        stale_session = replace(
            session,
            source_occurrence_providers=(provider,),
        )

        with self.assertRaisesRegex(
            ContractValidationError,
            "provenance binding mismatch",
        ):
            stale_session.query(
                query_text=query_text,
                effective_graph_view=self.inputs.effective_graph_view,
            )

    def test_explicit_exact_field_routes_source_occurrence_without_exact_wording(
        self,
    ) -> None:
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=(self.inputs.current_bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        query_text = "查詢 synthetic@example.test 郵件"
        self.assertEqual(deterministic_query_class(query_text), "evidence_lookup")
        identifier_hash = hybrid_module._deterministic_exact_filter_slots(
            query_text,
            tokenizer_profile=self.runtime.tokenizer_profile,
        ).identifier_hashes[0]
        source_observation = next(
            observation
            for observation in session.authorized_observations
            if sha256_json(observation.to_dict()) == self.inputs.current_observation_hash
        )
        source_lineage = next(
            lineage
            for lineage in session.occurrence_lineages
            if lineage.source_observation_id == source_observation.observation_id
        )
        provider = SourceOccurrenceProvider(
            provider_id="mail_source_occurrence_provider_v1",
            inventory_kind_alias="mail_observation",
            resource_kind="mail_message_occurrence",
            normalized_field="participant.any.local_part",
            predicate="source_occurrence_involves",
            operator="case_insensitive_exact",
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_scope_fingerprint=authorized_source_occurrence_scope_fingerprint(
                requester_user_id=session.requester_user_id,
                workspace_id=session.workspace_id,
                source_scope_ids=session.authorized_source_scope_ids,
                authorized_observation_hashes=session.authorized_observation_hashes,
                source_session_binding_fingerprint=(
                    session.source_session_binding_fingerprint or ""
                ),
            ),
            occurrences=(
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json(source_lineage.occurrence_id),
                    value_bindings=(
                        (
                            identifier_hash,
                            sha256_json("synthetic@example.test"),
                            self.inputs.current_observation_hash,
                            source_lineage.lineage_fingerprint,
                        ),
                    ),
                ),
            ),
        )

        result = replace(
            session,
            source_occurrence_providers=(provider,),
        ).query(
            query_text=query_text,
            effective_graph_view=self.inputs.effective_graph_view,
            exact_field="participant.any.local_part",
        )

        self.assertEqual(result.query_class, "exact_set_or_inventory")
        self.assertEqual(result.status, "complete_authorized_scope")
        exact = result.exact_result
        assert exact is not None
        self.assertEqual(exact.exact_count, 1)
        self.assertEqual(exact.returned_item_count, 1)
        self.assertTrue(exact.coverage.authorized_scope_complete)

    def test_typed_participant_slots_preserve_complete_dot_atom_identifiers(
        self,
    ) -> None:
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=(self.inputs.current_bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        normalized_field = "participant.any.local_part"
        local_parts = ("alpha.beta+tag", "gamma.delta%ops")
        query_text = f"列出全部 {' '.join(local_parts)} 郵件"
        local_hashes = tuple(
            sha256_json(
                self.runtime.tokenizer_profile.normalize_exact_identifier_surface(
                    value
                )
            )
            for value in local_parts
        )
        expected_hashes = tuple(sorted(local_hashes))
        slots = hybrid_module._deterministic_exact_filter_slots(
            query_text,
            tokenizer_profile=self.runtime.tokenizer_profile,
            exact_inventory_kind="mail_observation",
            exact_field=normalized_field,
        )
        self.assertEqual(slots.identifier_hashes, expected_hashes)
        unrelated_identifier = "ORDER-9001"
        unrelated_hash = sha256_json(
            self.runtime.tokenizer_profile.normalize_exact_identifier_surface(
                unrelated_identifier
            )
        )
        single_participant_query = (
            f"列出全部 {local_parts[0]} {unrelated_identifier} 郵件"
        )
        single_participant_slots = hybrid_module._deterministic_exact_filter_slots(
            single_participant_query,
            tokenizer_profile=self.runtime.tokenizer_profile,
            exact_inventory_kind="mail_observation",
            exact_field=normalized_field,
        )
        self.assertEqual(single_participant_slots.identifier_hashes, (local_hashes[0],))
        self.assertIn(unrelated_hash, single_participant_slots.topic_hashes)
        self.assertEqual(
            hybrid_module._deterministic_exact_filter_slots(
                query_text,
                tokenizer_profile=self.runtime.tokenizer_profile,
                exact_inventory_kind="mail_observation",
            ),
            hybrid_module._deterministic_exact_filter_slots(
                query_text,
                tokenizer_profile=self.runtime.tokenizer_profile,
            ),
        )

        full_address = f"{local_parts[0]}@example.test"
        full_address_hash = sha256_json(
            self.runtime.tokenizer_profile.normalize_exact_identifier_surface(
                full_address
            )
        )
        self.assertEqual(
            hybrid_module._deterministic_exact_filter_slots(
                f"查詢 {full_address} 郵件",
                tokenizer_profile=self.runtime.tokenizer_profile,
                exact_inventory_kind="mail_observation",
                exact_field=normalized_field,
            ).identifier_hashes,
            (full_address_hash,),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "typed participant identifier slot is unavailable",
        ):
            hybrid_module._deterministic_exact_filter_slots(
                "review status. next step",
                tokenizer_profile=self.runtime.tokenizer_profile,
                exact_inventory_kind="mail_observation",
                exact_field=normalized_field,
            )

        authorized_hash_by_id = dict(session.authorized_observation_hashes)
        lineages_by_occurrence = {}
        for lineage in session.occurrence_lineages:
            if (
                lineage.source_observation_id in authorized_hash_by_id
                and lineage.occurrence_id not in lineages_by_occurrence
            ):
                lineages_by_occurrence[lineage.occurrence_id] = lineage
        selected_lineages = tuple(lineages_by_occurrence.values())[:2]
        self.assertEqual(len(selected_lineages), 2)
        scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_observation_hashes=session.authorized_observation_hashes,
            source_session_binding_fingerprint=(
                session.source_session_binding_fingerprint or ""
            ),
        )
        provider = SourceOccurrenceProvider(
            provider_id="mail_source_occurrence_provider_v1",
            inventory_kind_alias="mail_observation",
            resource_kind="mail_message_occurrence",
            normalized_field=normalized_field,
            predicate="source_occurrence_involves",
            operator="case_insensitive_exact",
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_scope_fingerprint=scope_fingerprint,
            occurrences=tuple(
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json(["participant-occurrence", index]),
                    value_bindings=(
                        (
                            local_hashes[index],
                            sha256_json(f"{local_parts[index]}@example.test"),
                            authorized_hash_by_id[lineage.source_observation_id],
                            lineage.lineage_fingerprint,
                        ),
                    ),
                )
                for index, lineage in enumerate(selected_lineages)
            ),
        )
        routed_session = replace(
            session,
            source_occurrence_providers=(provider,),
        )
        with patch.object(
            hybrid_module,
            "route_semantic_query",
            wraps=hybrid_module.route_semantic_query,
        ) as route:
            single_result = routed_session.query(
                query_text=single_participant_query,
                effective_graph_view=self.inputs.effective_graph_view,
                exact_inventory_kind="mail_observation",
                exact_field=normalized_field,
            )
        assert route.call_args is not None
        self.assertEqual(
            route.call_args.kwargs["exact_identifier_term_hashes"],
            (local_hashes[0],),
        )
        self.assertEqual(
            route.call_args.kwargs["exact_filter_term_hashes"],
            (local_hashes[0],),
        )
        assert single_result.exact_result is not None
        self.assertEqual(single_result.exact_result.exact_count, 1)
        result = routed_session.query(
            query_text=query_text,
            effective_graph_view=self.inputs.effective_graph_view,
            exact_inventory_kind="mail_observation",
            exact_field=normalized_field,
            page_size=100,
        )
        exact_result = result.exact_result
        assert exact_result is not None
        self.assertEqual(exact_result.exact_count, 2)
        self.assertEqual(
            {
                matched_hash
                for item in exact_result.items
                for matched_hash in item.matched_normalized_value_hashes
            },
            set(expected_hashes),
        )
        full_result = routed_session.query(
            query_text=f"查詢 {full_address} 郵件",
            effective_graph_view=self.inputs.effective_graph_view,
            exact_inventory_kind="mail_observation",
            exact_field=normalized_field,
        )
        assert full_result.exact_result is not None
        self.assertEqual(full_result.exact_result.exact_count, 1)
        self.assertFalse(full_result.exact_result.items[0].ambiguous_identifier)

        with self.assertRaisesRegex(
            ContractValidationError,
            "source occurrence identifier binding is incomplete",
        ):
            replace(
                routed_session,
                source_occurrence_providers=(
                    replace(provider, occurrences=(provider.occurrences[0],)),
                ),
            ).query(
                query_text=query_text,
                effective_graph_view=self.inputs.effective_graph_view,
                exact_inventory_kind="mail_observation",
                exact_field=normalized_field,
            )

    def test_source_occurrence_exact_matches_local_or_full_binding_dimension(
        self,
    ) -> None:
        source_scope_ids = (self.inputs.current_bundle.mail_evidence_bundle_id,)
        local_hash = sha256_json("synthetic-local")
        variant_hashes = (
            sha256_json("synthetic-local@example.test"),
            sha256_json("synthetic-local@example.invalid"),
        )
        citation_hashes = (sha256_json("citation-one"), sha256_json("citation-two"))
        lineage_hashes = (sha256_json("lineage-one"), sha256_json("lineage-two"))
        scope_fingerprint = sha256_json("authorized-source-scope")
        first_binding = (
            local_hash,
            variant_hashes[0],
            citation_hashes[0],
            lineage_hashes[0],
        )
        second_binding = (
            local_hash,
            variant_hashes[1],
            citation_hashes[1],
            lineage_hashes[1],
        )
        provider = SourceOccurrenceProvider(
            provider_id="mail_source_occurrence_provider_v1",
            inventory_kind_alias="mail_observation",
            resource_kind="mail_message_occurrence",
            normalized_field="participant.any.local_part",
            predicate="source_occurrence_involves",
            operator="case_insensitive_exact",
            requester_user_id=REQUESTER_USER_ID,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=source_scope_ids,
            authorized_scope_fingerprint=scope_fingerprint,
            occurrences=(
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json(["occurrence", 0]),
                    value_bindings=(first_binding, first_binding),
                ),
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json(["occurrence", 1]),
                    value_bindings=(second_binding,),
                ),
            ),
        )
        expected_provider_fingerprint = sha256_json(
            {
                "contract": [
                    provider.provider_id,
                    provider.inventory_kind_alias,
                    provider.resource_kind,
                    provider.normalized_field,
                    provider.predicate,
                    provider.operator,
                    provider.requester_user_id,
                    provider.workspace_id,
                    *provider.source_scope_ids,
                    provider.authorized_scope_fingerprint,
                    provider.duplicate_policy,
                ],
                "occurrences": [
                    [
                        item.item_hash,
                        [list(binding) for binding in item.value_bindings],
                    ]
                    for item in provider.occurrences
                ],
                "counts": [
                    provider.unresolved_count,
                    provider.unsupported_count,
                    provider.redacted_count,
                ],
            }
        )
        self.assertEqual(provider.provider_fingerprint, expected_provider_fingerprint)
        expected_provider_fields = (
            "provider_id",
            "inventory_kind_alias",
            "resource_kind",
            "normalized_field",
            "predicate",
            "operator",
            "requester_user_id",
            "workspace_id",
            "source_scope_ids",
            "authorized_scope_fingerprint",
            "occurrences",
            "filter_slot_policy",
            "unresolved_count",
            "unsupported_count",
            "encrypted_count",
            "redacted_count",
            "authorized_occurrence_scope_count",
            "extractable_occurrence_scope_count",
            "source_asset_reason_counts",
            "duplicate_policy",
        )
        self.assertEqual(
            tuple(provider_field.name for provider_field in fields(provider)),
            expected_provider_fields,
        )
        self.assertEqual(tuple(asdict(provider)), expected_provider_fields)
        self.assertIs(deepcopy(provider), provider)
        with self.assertRaises(FrozenInstanceError):
            provider._provider_fingerprint = sha256_json("changed")
        with self.assertRaises(TypeError):
            provider._value_hash_postings[local_hash] = ()
        with self.assertRaises(TypeError):
            provider._ordered_occurrences[0] = provider.occurrences[1]
        with self.assertRaises(AttributeError):
            provider._normalized_variant_hashes[local_hash].add(
                sha256_json("changed")
            )
        foreign_provider = replace(
            provider,
            provider_id="mail_source_occurrence_provider_foreign_v1",
        )

        def execute(
            query_hashes: str | Sequence[str],
            *,
            cursor: str | None = None,
            page_size: int = 1,
            selected_provider: SourceOccurrenceProvider = provider,
            query_text: str = "synthetic exact inventory",
        ):
            resolved_hashes = (
                (query_hashes,) if isinstance(query_hashes, str) else tuple(query_hashes)
            )
            plan = route_semantic_query(
                query_text=query_text,
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
                source_scope_ids=source_scope_ids,
                effective_graph_view=self.inputs.effective_graph_view,
                exact_inventory_kind=selected_provider.resource_kind,
                exact_filter_term_hashes=resolved_hashes,
                exact_identifier_term_hashes=resolved_hashes,
                exact_normalized_field=selected_provider.normalized_field,
                exact_predicate=selected_provider.predicate,
                exact_operator=selected_provider.operator,
                query_class_override="exact_set_or_inventory",
            )
            return execute_deterministic_source_occurrence_inventory(
                plan=plan,
                provider=selected_provider,
                expected_authorized_scope_fingerprint=scope_fingerprint,
                page_size=page_size,
                cursor=cursor,
            )

        with patch.object(
            exact_module,
            "sha256_json",
            wraps=sha256_json,
        ) as exact_sha256:
            self.assertEqual(provider.provider_fingerprint, expected_provider_fingerprint)
            first_local_page = execute(local_hash)
            local_cursor = first_local_page.source_occurrence_page["next_cursor"]
            second_local_page = execute(local_hash, cursor=local_cursor)
            multi_result = execute(variant_hashes, page_size=100)
            full_result = execute(variant_hashes[0])
            with self.assertRaisesRegex(
                ContractValidationError,
                "source occurrence cursor binding mismatch",
            ):
                execute(local_hash, cursor=local_cursor, page_size=2)
            with self.assertRaisesRegex(
                ContractValidationError,
                "source occurrence cursor binding mismatch",
            ):
                execute(
                    local_hash,
                    cursor=local_cursor,
                    selected_provider=foreign_provider,
                )
            with self.assertRaisesRegex(
                ContractValidationError,
                "source occurrence cursor binding mismatch",
            ):
                execute(
                    local_hash,
                    cursor=local_cursor,
                    query_text="synthetic exact inventory replay",
                )
            provider_fingerprint_calls = [
                call
                for call in exact_sha256.call_args_list
                if call.args
                and isinstance(call.args[0], dict)
                and set(call.args[0]) == {"contract", "occurrences", "counts"}
            ]
            self.assertEqual(provider_fingerprint_calls, [])

        local_items = (*first_local_page.items, *second_local_page.items)
        self.assertEqual(
            {item.item_hash for item in local_items},
            {occurrence.item_hash for occurrence in provider.occurrences},
        )
        self.assertEqual(len(local_items), 2)
        self.assertTrue(all(item.ambiguous_identifier for item in local_items))
        self.assertTrue(
            all(item.matched_normalized_value_hashes == (local_hash,) for item in local_items)
        )

        self.assertEqual(multi_result.exact_count, 2)
        self.assertEqual(multi_result.returned_item_count, 2)
        self.assertEqual(
            {item.item_hash for item in multi_result.items},
            {occurrence.item_hash for occurrence in provider.occurrences},
        )
        self.assertEqual(full_result.exact_count, 1)
        self.assertEqual(full_result.items[0].cited_observation_hashes, (citation_hashes[0],))
        self.assertEqual(
            full_result.items[0].governed_references,
            ((citation_hashes[0], lineage_hashes[0]),),
        )
        self.assertEqual(
            full_result.items[0].matched_normalized_value_hashes,
            (local_hash,),
        )
        self.assertFalse(full_result.items[0].ambiguous_identifier)

    def test_direct_identifier_provider_routes_uniquely_without_scope_expansion(
        self,
    ) -> None:
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=(self.inputs.current_bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        query_text = "列出全部 DIRECT-CASE-1001 郵件"
        query_hash = hybrid_module._deterministic_exact_filter_slots(
            query_text,
            tokenizer_profile=self.runtime.tokenizer_profile,
        ).identifier_hashes[0]
        multi_query_text = "列出全部 DIRECT-CASE-1001 DIRECT-CASE-2002 郵件"
        multi_query_hashes = hybrid_module._deterministic_exact_filter_slots(
            multi_query_text,
            tokenizer_profile=self.runtime.tokenizer_profile,
        ).identifier_hashes
        self.assertEqual(len(multi_query_hashes), 2)
        second_query_hash = next(
            value for value in multi_query_hashes if value != query_hash
        )
        authorized_hash_by_id = dict(session.authorized_observation_hashes)
        lineage_by_id = {
            lineage.source_observation_id: lineage
            for lineage in session.occurrence_lineages
        }
        first_observation_id = "obs_issue56_semantic_current_body_1"
        same_thread_observation_id = "obs_issue56_semantic_current_body_2"
        first_reference = (
            authorized_hash_by_id[first_observation_id],
            lineage_by_id[first_observation_id].lineage_fingerprint,
        )
        same_thread_reference = (
            authorized_hash_by_id[same_thread_observation_id],
            lineage_by_id[same_thread_observation_id].lineage_fingerprint,
        )
        scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_observation_hashes=session.authorized_observation_hashes,
            source_session_binding_fingerprint=(
                session.source_session_binding_fingerprint or ""
            ),
        )

        def provider(
            normalized_field: str,
            *,
            matching_hash: str,
            same_thread_hash: str,
            inventory_kind_alias: str = "source_identifier_observation",
            unresolved_count: int = 0,
        ) -> SourceOccurrenceProvider:
            return SourceOccurrenceProvider(
                provider_id=(
                    "mail_message_occurrence_direct_source_identifier_provider_v1"
                ),
                inventory_kind_alias=inventory_kind_alias,
                resource_kind="mail_message_occurrence",
                normalized_field=normalized_field,
                predicate="source_occurrence_has_identifier",
                operator="case_insensitive_exact",
                requester_user_id=session.requester_user_id,
                workspace_id=session.workspace_id,
                source_scope_ids=session.authorized_source_scope_ids,
                authorized_scope_fingerprint=scope_fingerprint,
                occurrences=(
                    AuthorizedSourceOccurrence(
                        item_hash=sha256_json(
                            lineage_by_id[first_observation_id].occurrence_id
                        ),
                        value_bindings=(
                            (
                                matching_hash,
                                matching_hash,
                                *first_reference,
                            ),
                        ),
                    ),
                    AuthorizedSourceOccurrence(
                        item_hash=sha256_json(
                            lineage_by_id[same_thread_observation_id].occurrence_id
                        ),
                        value_bindings=(
                            (
                                same_thread_hash,
                                same_thread_hash,
                                *same_thread_reference,
                            ),
                        ),
                    ),
                ),
                unresolved_count=unresolved_count,
            )

        direct_provider = provider(
            "message_occurrence.direct_source_identifier_v1",
            matching_hash=query_hash,
            same_thread_hash=second_query_hash,
        )
        participant_provider = provider(
            "participant.any.local_part",
            matching_hash=sha256_json("unrelated-participant"),
            same_thread_hash=sha256_json("unrelated-participant-peer"),
            inventory_kind_alias="participant_local_part",
        )
        routed_session = replace(
            session,
            source_occurrence_providers=(direct_provider, participant_provider),
        )
        result = routed_session.query(
            query_text=query_text,
            effective_graph_view=self.inputs.effective_graph_view,
        )

        self.assertEqual(result.query_class, "exact_set_or_inventory")
        self.assertEqual(result.status, "complete_authorized_scope")
        self.assertEqual(result.graph_paths, ())
        exact = result.exact_result
        assert exact is not None
        self.assertEqual(exact.exact_count, 1)
        self.assertEqual(exact.returned_item_count, 1)
        self.assertEqual(exact.items[0].governed_references, (first_reference,))
        self.assertNotEqual(
            exact.items[0].item_hash,
            sha256_json(lineage_by_id[same_thread_observation_id].occurrence_id),
        )

        typed_query_text = "DIRECT-CASE-1001 status"
        self.assertEqual(deterministic_query_class(typed_query_text), "evidence_lookup")
        with patch.object(
            hybrid_module,
            "_validate_hybrid_index_runtime",
            side_effect=AssertionError("full candidate integrity validation invoked"),
        ) as full_index_validation:
            typed_result = routed_session.query(
                query_text=typed_query_text,
                effective_graph_view=self.inputs.effective_graph_view,
                exact_inventory_kind=direct_provider.inventory_kind_alias,
            )
            with self.assertRaisesRegex(
                ContractValidationError,
                "source occurrence identifier binding is incomplete",
            ):
                replace(
                    session,
                    source_occurrence_providers=(
                        replace(
                            direct_provider,
                            occurrences=(direct_provider.occurrences[0],),
                        ),
                        participant_provider,
                    ),
                ).query(
                    query_text=multi_query_text,
                    effective_graph_view=self.inputs.effective_graph_view,
                    exact_inventory_kind=direct_provider.inventory_kind_alias,
                )
            with self.assertRaisesRegex(
                ContractValidationError,
                "source occurrence exact binding is invalid",
            ):
                replace(
                    session,
                    source_occurrence_providers=(
                        replace(
                            direct_provider,
                            authorized_scope_fingerprint=sha256_json("foreign-scope"),
                        ),
                        participant_provider,
                    ),
                ).query(
                    query_text=typed_query_text,
                    effective_graph_view=self.inputs.effective_graph_view,
                    exact_inventory_kind=direct_provider.inventory_kind_alias,
                )
        full_index_validation.assert_not_called()
        self.assertEqual(typed_result.query_class, "exact_set_or_inventory")
        typed_exact = typed_result.exact_result
        assert typed_exact is not None
        self.assertEqual(typed_exact.exact_count, 1)
        self.assertEqual(typed_exact.items[0].governed_references, (first_reference,))
        with self.assertRaisesRegex(
            ContractValidationError,
            "source occurrence provider selection is invalid",
        ):
            routed_session.query(
                query_text=typed_query_text,
                effective_graph_view=self.inputs.effective_graph_view,
                exact_inventory_kind="unknown_resource_kind",
            )

        multi_result = routed_session.query(
            query_text=multi_query_text,
            effective_graph_view=self.inputs.effective_graph_view,
        )
        self.assertEqual(multi_result.graph_paths, ())
        multi_exact = multi_result.exact_result
        assert multi_exact is not None
        self.assertEqual(multi_exact.exact_count, 2)
        self.assertEqual(multi_exact.returned_item_count, 2)
        self.assertEqual(
            {item.governed_references for item in multi_exact.items},
            {(first_reference,), (same_thread_reference,)},
        )

        partial_provider = replace(
            direct_provider,
            occurrences=(direct_provider.occurrences[0],),
        )
        partial_plan = route_semantic_query(
            query_text=multi_query_text,
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            effective_graph_view=self.inputs.effective_graph_view,
            exact_inventory_kind=partial_provider.resource_kind,
            exact_filter_term_hashes=multi_query_hashes,
            exact_identifier_term_hashes=multi_query_hashes,
            exact_normalized_field=partial_provider.normalized_field,
            exact_predicate=partial_provider.predicate,
            exact_operator=partial_provider.operator,
            authorized_source=session.authorized_source,
            query_class_override="exact_set_or_inventory",
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "source occurrence identifier binding is incomplete",
        ):
            execute_deterministic_source_occurrence_inventory(
                plan=partial_plan,
                provider=partial_provider,
                expected_authorized_scope_fingerprint=scope_fingerprint,
                page_size=20,
                cursor=None,
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "source occurrence identifier binding is incomplete",
        ):
            replace(
                session,
                source_occurrence_providers=(partial_provider, participant_provider),
            ).query(
                query_text=multi_query_text,
                effective_graph_view=self.inputs.effective_graph_view,
            )

        incomplete = replace(
            session,
            source_occurrence_providers=(
                replace(direct_provider, unresolved_count=1),
                participant_provider,
            ),
        ).query(
            query_text=query_text,
            effective_graph_view=self.inputs.effective_graph_view,
        )
        assert incomplete.exact_result is not None
        self.assertEqual(incomplete.status, "incomplete")
        self.assertFalse(incomplete.exact_result.coverage.authorized_scope_complete)

        ambiguous_provider = provider(
            "source_identifier.protected_identifier",
            matching_hash=query_hash,
            same_thread_hash=sha256_json("unrelated-ambiguous-peer"),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "source occurrence provider selection is ambiguous",
        ):
            replace(
                session,
                source_occurrence_providers=(
                    direct_provider,
                    participant_provider,
                    ambiguous_provider,
                ),
            ).query(
                query_text=query_text,
                effective_graph_view=self.inputs.effective_graph_view,
            )

    def test_source_backed_term_graph_and_exact_predicate_use_authorized_observations(
        self,
    ) -> None:
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=(self.inputs.current_bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
            graph_build = build_authorized_source_backed_effective_graph_view(
                session=session,
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                source_binding_fingerprint="sha256:" + "a" * 64,
            )
            lineage_crosswalk = hybrid_module.build_evidence_identity_lineage_crosswalk(
                session=session,
                effective_graph_view=graph_build.effective_graph_view,
            )
            relation = session.query(
                query_text="供應商 產地 關係",
                effective_graph_view=graph_build.effective_graph_view,
                allowed_relation_types=("co_occurs_with",),
                allowed_directions=("in", "out"),
            )
            exact = session.query(
                query_text="列出全部 產地 郵件",
                effective_graph_view=graph_build.effective_graph_view,
            )

        self.assertEqual(relation.status, "ok")
        self.assertTrue(relation.graph_paths)
        self.assertTrue(any(score.entity_score > 0.0 for score in relation.scores))
        authorized_hashes = dict(session.authorized_observation_hashes)
        for path in relation.graph_paths:
            self.assertTrue(path.cited_observation_hashes)
            self.assertTrue(set(path.cited_observation_hashes).issubset(authorized_hashes.values()))
        self.assertTrue(
            any(
                node.properties.get("node_kind") == "candidate_source_term"
                for node in graph_build.effective_graph_view.visible_nodes
            )
        )
        parent_only_identifier = "supplier-current@example.test"
        body_candidate = next(
            candidate
            for candidate in session.index.candidates
            if candidate.source_observation_hash == self.inputs.current_observation_hash
        )
        self.assertIn(
            parent_only_identifier,
            body_candidate.protected_identifier_tokens,
        )
        self.assertNotIn(
            parent_only_identifier,
            body_candidate.observation_protected_identifier_tokens,
        )
        body_node = next(
            node
            for node in graph_build.effective_graph_view.visible_nodes
            if node.properties.get("source_observation_ids")
            == ["obs_issue56_semantic_current_body_1"]
        )
        self.assertNotIn(
            sha256_json(parent_only_identifier),
            body_node.properties["protected_term_hashes"],
        )
        lineage_entries = {
            entry.source_observation_hash: entry for entry in lineage_crosswalk.entries
        }
        for path in relation.graph_paths:
            for evidence_hash in path.cited_observation_hashes:
                entry = lineage_entries[evidence_hash]
                self.assertTrue(entry.index_binding_hashes)
                self.assertTrue(entry.occurrence_hashes)
                self.assertTrue(entry.graph_edge_hashes)
        unindexed_entries = [
            entry for entry in lineage_crosswalk.entries if not entry.index_binding_hashes
        ]
        self.assertTrue(unindexed_entries)
        self.assertTrue(all(not entry.graph_edge_hashes for entry in unindexed_entries))
        assert_no_public_raw_references(
            graph_build.to_safe_dict(),
            "issue56_source_backed_term_graph",
        )
        assert_no_public_raw_references(
            lineage_crosswalk.to_safe_dict(),
            "issue56_hash_only_evidence_identity_lineage",
        )

        exact_result = exact.exact_result
        assert exact_result is not None
        self.assertEqual(exact.status, "complete_authorized_scope")
        self.assertGreater(exact_result.coverage.filter_term_count, 0)
        self.assertGreater(
            exact_result.coverage.inventory_schema_record_count,
            exact_result.exact_count,
        )
        self.assertGreater(exact_result.exact_count, 0)
        self.assertEqual(
            exact_result.cited_observation_count,
            exact_result.exact_count,
        )

    def test_lineage_crosswalk_cache_isolated_by_authorized_session_binding(
        self,
    ) -> None:
        source_scope_id = self.inputs.current_bundle.mail_evidence_bundle_id
        extra_observation = replace(
            self.inputs.observations_by_bundle_id[source_scope_id][0],
            observation_id="obs_issue56_semantic_authorization_superset",
        )
        authorization_observations = dict(self.inputs.observations_by_bundle_id)
        authorization_observations[source_scope_id] = (
            *authorization_observations[source_scope_id],
            extra_observation,
        )
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            baseline_session, expanded_session = (
                build_authorized_semantic_mail_session(
                    observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                    authorization_observations_by_bundle_id=authorization,
                    bundles=(self.inputs.current_bundle,),
                    requester_user_id=REQUESTER_USER_ID,
                    workspace_id=WORKSPACE_ID,
                )
                for authorization in (None, authorization_observations)
            )

        self.assertEqual(
            baseline_session.index.index_fingerprint,
            expanded_session.index.index_fingerprint,
        )
        self.assertNotEqual(
            baseline_session.source_session_binding_fingerprint,
            expanded_session.source_session_binding_fingerprint,
        )
        extra_observation_hash = sha256_json(extra_observation.to_dict())
        with patch.dict(
            hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE,
            clear=True,
        ):
            baseline_crosswalk, expanded_crosswalk = (
                hybrid_module.build_evidence_identity_lineage_crosswalk(
                    session=session,
                    effective_graph_view=self.inputs.effective_graph_view,
                )
                for session in (baseline_session, expanded_session)
            )
            cached_crosswalks = dict(
                hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE
            )

        self.assertEqual(
            baseline_crosswalk.graph_revision_fingerprint,
            expanded_crosswalk.graph_revision_fingerprint,
        )
        expected_cache_keys = {
            (
                session.index.index_fingerprint,
                crosswalk.graph_revision_fingerprint,
                session.source_session_binding_fingerprint,
            )
            for session, crosswalk in (
                (baseline_session, baseline_crosswalk),
                (expanded_session, expanded_crosswalk),
            )
        }
        self.assertEqual(set(cached_crosswalks), expected_cache_keys)
        self.assertEqual(len(cached_crosswalks), 2)
        self.assertIsNot(baseline_crosswalk, expanded_crosswalk)
        self.assertNotEqual(
            baseline_crosswalk.crosswalk_fingerprint,
            expanded_crosswalk.crosswalk_fingerprint,
        )
        self.assertEqual(
            expanded_crosswalk.authorized_evidence_count,
            baseline_crosswalk.authorized_evidence_count + 1,
        )
        evidence_sets = tuple(
            {entry.source_observation_hash for entry in crosswalk.entries}
            for crosswalk in (baseline_crosswalk, expanded_crosswalk)
        )
        self.assertNotIn(extra_observation_hash, evidence_sets[0])
        self.assertIn(extra_observation_hash, evidence_sets[1])

    def test_permission_denied_materializes_no_candidate_or_exact_result(self) -> None:
        result = self._run(
            query_text="SECRET-PO-99001",
            mail_evidence_bundle_id=self.inputs.denied_bundle.mail_evidence_bundle_id,
        )

        self.assertEqual(result.status, "permission_denied")
        self.assertEqual(result.authorized_bundle_count, 0)
        self.assertEqual(result.materialized_candidate_count, 0)
        self.assertEqual(result.semantic_result_count, 0)
        self.assertIsNone(result.exact_result)
        self.assertIsNone(result.plan_fingerprint)

    def test_current_and_soft_ontology_scores_never_force_or_delete_evidence(
        self,
    ) -> None:
        compatible = self._run(
            query_text="PO470002002",
            target_core_supertype_id="Artifact",
        )
        compatible_by_hash = {score.source_observation_hash: score for score in compatible.scores}
        current = compatible_by_hash[self.inputs.current_observation_hash]
        superseded = compatible_by_hash[self.inputs.superseded_observation_hash]
        self.assertEqual(current.temporal_current_score, 1.0)
        self.assertEqual(superseded.temporal_current_score, 0.0)
        self.assertGreater(current.total_score, superseded.total_score)
        self.assertGreater(current.ontology_bonus, 0.0)
        self.assertLessEqual(current.ontology_bonus, 0.2)

        bounded_answer = self._run(
            query_text="PO470002002",
            target_core_supertype_id="Artifact",
            limits=SemanticPlanLimits(max_evidence=1),
        )
        self.assertTrue(
            {
                self.inputs.current_observation_hash,
                self.inputs.superseded_observation_hash,
            }.issubset({score.source_observation_hash for score in bounded_answer.scores})
        )
        self.assertEqual(
            bounded_answer.answer_citation_hashes,
            (self.inputs.current_observation_hash,),
        )

        mismatch = self._run(
            query_text="PO470002002",
            target_core_supertype_id="Person",
        )
        mismatch_by_hash = {score.source_observation_hash: score for score in mismatch.scores}
        self.assertIn(self.inputs.current_observation_hash, mismatch_by_hash)
        self.assertIn(self.inputs.superseded_observation_hash, mismatch_by_hash)
        self.assertEqual(
            mismatch_by_hash[self.inputs.current_observation_hash].ontology_bonus,
            0.0,
        )

        ontology_only = self._run(
            query_text="PO999999999",
            target_core_supertype_id="Artifact",
        )
        self.assertEqual(ontology_only.status, "no_answer")
        self.assertTrue(ontology_only.scores)
        self.assertEqual(ontology_only.answer_citation_hashes, ())
        self.assertTrue(
            all(score.provenance_coverage_score == 1.0 for score in ontology_only.scores)
        )

    def test_global_summary_is_bounded_evidence_route_not_completion_claim(self) -> None:
        result = self._run(query_text="請摘要 PO470002002 目前狀況")

        self.assertEqual(result.query_class, "global_summarization")
        self.assertEqual(result.claim_strength, "bounded_summary")
        self.assertIn(
            "bounded_summary_evidence_only_no_answer_model",
            result.warnings,
        )
        self.assertNotEqual(result.status, "complete_authorized_scope")

    def test_rerun_fingerprint_is_deterministic(self) -> None:
        first = self._run(
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            allowed_relation_types=ALLOWED_RELATIONS,
        )
        second = self._run(
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            allowed_relation_types=ALLOWED_RELATIONS,
        )
        self.assertEqual(first.plan_fingerprint, second.plan_fingerprint)
        self.assertEqual(first.result_fingerprint, second.result_fingerprint)
        self.assertEqual(
            first.execution_component_fingerprint,
            second.execution_component_fingerprint,
        )

    def test_normal_smoke_is_real_e5_or_explicit_safe_blocker(self) -> None:
        identity_scope = _semantic_poc_identity_scope()
        self.assertEqual(identity_scope.identity_scope_mode, "workspace_only_v1")
        self.assertIsNone(identity_scope.tenant_id)
        self.assertRegex(
            identity_scope.spec_approval_fingerprint,
            r"^sha256:[0-9a-f]{64}$",
        )
        script_source = (ROOT / "scripts" / "issue56_semantic_execution_smoke.py").read_text()
        self.assertNotIn('tenant_id="tenant_issue56_semantic_poc"', script_source)
        self.assertNotIn("DeterministicDiagnosticDenseEncoder", script_source)
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/issue56_semantic_execution_smoke.py",
                "--allow-blocked",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(completed.stdout)
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertEqual(
            report["artifact_id"],
            "formowl_issue56_semantic_execution_e2e_poc_v2",
        )
        self.assertFalse(report["fallback_used"])
        self.assertEqual(
            report["dense_retrieval"]["model_id"],
            ISSUE56_TARGET_DENSE_MODEL_ID,
        )
        self.assertEqual(
            report["dense_retrieval"]["model_revision"],
            ISSUE56_TARGET_DENSE_MODEL_REVISION,
        )
        if report["status"] == "blocked":
            self.assertFalse(report["e2e_executed"])
            self.assertIn("blocker", report)
        else:
            self.assertEqual(report["status"], "passed")
            self.assertTrue(report["e2e_executed"])
            self.assertEqual(
                report["runtime_method"]["method_id"],
                ISSUE56_TARGET_RUNTIME_METHOD_ID,
            )
            self.assertEqual(
                report["runtime_method"]["method_fingerprint"],
                ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
            )
            self.assertTrue(report["runtime_method"]["strong_rag_active"])
            self.assertTrue(report["runtime_method"]["entity_signal_active"])
            self.assertTrue(report["runtime_method"]["candidate_graph_signal_active"])
            self.assertEqual(
                report["runtime_method"]["candidate_graph_policy_id"],
                "source_backed_mail_candidate_graph_v2",
            )
            self.assertTrue(report["runtime_method"]["candidate_graph_only"])
            self.assertEqual(
                report["runtime_method"]["identity_scope_mode"],
                "workspace_only_v1",
            )
            self.assertFalse(report["runtime_method"]["tenant_identity_present"])
            self.assertRegex(
                report["runtime_method"]["identity_scope_fingerprint"],
                r"^sha256:[0-9a-f]{64}$",
            )
            self.assertRegex(
                report["runtime_method"]["spec_approval_fingerprint"],
                r"^sha256:[0-9a-f]{64}$",
            )
            self.assertEqual(
                report["runtime_method"]["candidate_graph_relation_type_hashes"],
                sorted(
                    (
                        sha256_json("co_occurs_with"),
                        sha256_json("mentions_identifier"),
                    )
                ),
            )
            self.assertTrue(report["runtime_method"]["soft_ontology_signal_active"])
            self.assertTrue(report["runtime_method"]["graph_signal_active"])
            self.assertTrue(report["runtime_method"]["exact_path_active"])
            self.assertTrue(report["runtime_method"]["cited_answer_active"])
            self.assertFalse(report["runtime_method"]["legacy_path_used"])
            self.assertFalse(report["runtime_method"]["fallback_used"])
            self.assertEqual(
                report["scenarios"]["deterministic_rerun"]["status"],
                "matched",
            )
            self.assertEqual(
                report["scenarios"]["permission_denied"]["status"],
                "permission_denied",
            )
            self.assertEqual(
                report["scenarios"]["exact_inventory_count"]["exact_result"]["exact_count"],
                2,
            )
        for private_value in (
            "PO470002002",
            "PO470002004",
            "ORIGIN-TAIWAN-01",
            "SUPPLIER-ALPHA-01",
            "SECRET-PO-99001",
            "PRIVATE-TERM-77",
            str(ROOT),
        ):
            self.assertNotIn(private_value, serialized)

    def test_real_e5_semantic_path_when_snapshot_is_available(self) -> None:
        arguments = {
            "observations_by_bundle_id": self.inputs.observations_by_bundle_id,
            "bundles": self.inputs.bundles,
            "query_text": "PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            "requester_user_id": REQUESTER_USER_ID,
            "workspace_id": WORKSPACE_ID,
            "effective_graph_view": self.inputs.effective_graph_view,
            "allowed_relation_types": ALLOWED_RELATIONS,
        }
        try:
            result = run_authorized_semantic_mail_query(**arguments)
        except DenseEmbeddingUnavailableError as exc:
            self.skipTest(exc.reason_code)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.runtime_method_id, ISSUE56_TARGET_RUNTIME_METHOD_ID)
        self.assertEqual(
            result.runtime_method_fingerprint,
            ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        )
        self.assertEqual(result.dense_encoder_status, "pinned_real_e5")

    def _run(self, *, query_text: str, **overrides):
        arguments = {
            "observations_by_bundle_id": self.inputs.observations_by_bundle_id,
            "bundles": self.inputs.bundles,
            "query_text": query_text,
            "requester_user_id": REQUESTER_USER_ID,
            "workspace_id": WORKSPACE_ID,
            "effective_graph_view": self.inputs.effective_graph_view,
        }
        arguments.update(overrides)
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            return run_authorized_semantic_mail_query(**arguments)


class _ContractOnlySentenceTransformerModel:
    """Test-only model double; normal scripts never inject or import it."""

    def encode(self, texts: Sequence[str], **_kwargs):
        rows = []
        for text in texts:
            vector = [0.0] * 384
            for character in text.casefold():
                vector[ord(character) % len(vector)] += 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            rows.append(_VectorRow(value / norm for value in vector))
        return rows


class _VectorRow(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


def _contract_only_runtime() -> Issue56TargetRuntimeComponents:
    tokenizer_profile = load_issue56_target_mail_tokenizer_profile()
    dense_profile = issue56_target_dense_embedding_profile()
    encoder = SentenceTransformerDenseEncoder(
        profile=dense_profile,
        _model=_ContractOnlySentenceTransformerModel(),
    )
    binding = build_issue56_execution_component_binding(
        tokenizer_profile=tokenizer_profile,
        dense_profile=dense_profile,
    )
    return Issue56TargetRuntimeComponents(
        tokenizer_profile=tokenizer_profile,
        dense_encoder=encoder,
        execution_binding=binding,
    )


def _view_with_lineaged_relation_terms(view):
    required_terms = {
        "node_issue56_po_current": (
            "protected_term_hashes",
            sha256_json("po470002002"),
            "obs_issue56_semantic_current_body_1",
        ),
        "node_issue56_supplier": (
            "source_term_hashes",
            sha256_json("供應商"),
            "obs_issue56_semantic_current_body_1",
        ),
        "node_issue56_origin": (
            "protected_term_hashes",
            sha256_json("origin-taiwan-01"),
            "obs_issue56_semantic_current_body_2",
        ),
    }
    nodes = []
    for node in view.visible_nodes:
        required = required_terms.get(node.node_id)
        if required is None:
            nodes.append(node)
            continue
        property_name, term_hash, observation_id = required
        source_observation_ids = set(node.properties.get("source_observation_ids", ()))
        if observation_id not in source_observation_ids:
            raise AssertionError("fixture node lacks required source Observation lineage")
        properties = dict(node.properties)
        properties[property_name] = sorted({*properties.get(property_name, ()), term_hash})
        nodes.append(replace(node, properties=properties))
    return replace(view, visible_nodes=nodes)


def _path_node_hashes(path) -> set[str]:
    return {
        node_hash for hop in path.hops for node_hash in (hop.source_node_hash, hop.target_node_hash)
    }


if __name__ == "__main__":
    unittest.main()
