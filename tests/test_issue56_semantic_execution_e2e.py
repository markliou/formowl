from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields, FrozenInstanceError, replace
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from typing import Sequence

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    Observation,
    PermissionScope,
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
from formowl_mail.semantic_plan import (
    repair_relation_plan_once,
    validate_semantic_request_contract,
)
from formowl_gateway import issue56_sealed_source_loader as gateway_loader
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
            deterministic_query_class("請把 alpha.beta 的信件都調閱出來"),
            "exact_set_or_inventory",
        )
        self.assertEqual(
            deterministic_query_class("請把值甲的欄位乙跟欄位丙整理出來"),
            "evidence_lookup",
        )
        self.assertEqual(
            deterministic_query_class("哪些記錄屬於值乙"),
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

    def test_request_contract_reuses_query_class_claim_and_runtime_source_labels(
        self,
    ) -> None:
        contract = {
            "original_query_hash": sha256_json("generic source request"),
            "query_class": "evidence_lookup",
            "source_family_scope": ["ticket"],
            "requested_fields": ["status"],
            "maximum_claim_strength": "cited_evidence",
        }
        self.assertEqual(
            validate_semantic_request_contract(
                contract,
                available_source_families=("ticket", "calendar"),
            ),
            contract,
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "source scope is unavailable",
        ):
            validate_semantic_request_contract(
                contract,
                available_source_families=("mail",),
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "claim strength is invalid",
        ):
            validate_semantic_request_contract(
                {
                    **contract,
                    "maximum_claim_strength": "complete_authorized_scope",
                },
                available_source_families=("ticket",),
            )

        expanded_query = "列出 CASE-0001 的 Synthetic evidence"
        self.assertEqual(
            deterministic_query_class(expanded_query),
            "exact_set_or_inventory",
        )
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
        result = session.query(
            query_text=expanded_query,
            request_contract={
                "original_query_hash": sha256_json("CASE-0001 的 Synthetic evidence"),
                "query_class": "evidence_lookup",
                "source_family_scope": ["mail"],
                "requested_fields": [],
                "maximum_claim_strength": "cited_evidence",
            },
            effective_graph_view=self.inputs.effective_graph_view,
        )
        self.assertEqual(result.query_class, "evidence_lookup")
        self.assertIsNone(result.exact_result)

        relation_query = "PO470002002 與 ORIGIN-TAIWAN-01 的關係"
        with patch.object(
            hybrid_module,
            "_build_relation_query_projection",
            wraps=hybrid_module._build_relation_query_projection,
        ) as relation_projection:
            relation_result = session.query(
                query_text=relation_query,
                request_contract={
                    "original_query_hash": sha256_json(relation_query),
                    "query_class": "relation_reasoning",
                    "source_family_scope": ["mail"],
                    "requested_fields": [],
                    "maximum_claim_strength": "bounded_relation",
                },
                effective_graph_view=self.inputs.effective_graph_view,
                allowed_relation_types=ALLOWED_RELATIONS,
            )
        self.assertEqual(relation_result.query_class, "relation_reasoning")
        relation_arguments = relation_projection.call_args.kwargs
        scoped_observation_hashes = set(
            relation_arguments["authorized_observation_hash_by_id"].values()
        )
        self.assertEqual(
            scoped_observation_hashes,
            set(relation_arguments["candidates_by_hash"]),
        )
        self.assertLess(
            len(scoped_observation_hashes),
            len(session.authorized_observation_hashes),
        )

        with self.assertRaisesRegex(
            ContractValidationError,
            "source family is unsupported",
        ):
            hybrid_module._source_occurrence_provider_family(
                SimpleNamespace(
                    filter_slot_policy="identifier_union_v1",
                    resource_kind="future_record_occurrence",
                )
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
            source_session_binding_fingerprint=(session.source_session_binding_fingerprint or ""),
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
            hybrid_module.attach_authorized_source_occurrence_providers(
                session,
                (provider,),
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "provenance binding mismatch",
        ):
            stale_session.query(
                query_text=query_text,
                effective_graph_view=self.inputs.effective_graph_view,
            )

        valid_provider = replace(
            provider,
            occurrences=(
                replace(
                    provider.occurrences[0],
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
        attached_session = hybrid_module.attach_authorized_source_occurrence_providers(
            session,
            (valid_provider,),
        )
        with patch.object(
            hybrid_module,
            "_validated_source_occurrence_providers",
            side_effect=AssertionError("full provider provenance scan invoked"),
        ) as full_provider_validation:
            result = attached_session.query(
                query_text=query_text,
                effective_graph_view=self.inputs.effective_graph_view,
            )
            copied_result = replace(attached_session).query(
                query_text=query_text,
                effective_graph_view=self.inputs.effective_graph_view,
            )
        full_provider_validation.assert_not_called()
        self.assertEqual(copied_result.result_fingerprint, result.result_fingerprint)
        with self.assertRaisesRegex(
            ContractValidationError,
            "provenance seal mismatch",
        ):
            replace(
                attached_session,
                source_occurrence_providers=(provider,),
            ).query(
                query_text=query_text,
                effective_graph_view=self.inputs.effective_graph_view,
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "provenance seal mismatch",
        ):
            replace(
                attached_session,
                source_occurrence_providers=(replace(valid_provider, provider_id="moved"),),
            ).query(
                query_text=query_text,
                effective_graph_view=self.inputs.effective_graph_view,
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "provenance seal mismatch",
        ):
            replace(
                attached_session,
                workspace_id="workspace_moved",
            ).query(
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
            sha256_json(self.runtime.tokenizer_profile.normalize_exact_identifier_surface(value))
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
            self.runtime.tokenizer_profile.normalize_exact_identifier_surface(unrelated_identifier)
        )
        single_participant_query = f"列出全部 {local_parts[0]} {unrelated_identifier} 郵件"
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
        untyped_query = "請 把 alpha.beta 的 信件 都 調閱出來"
        untyped_inventory = hybrid_module._deterministic_exact_filter_slots(
            untyped_query,
            tokenizer_profile=self.runtime.tokenizer_profile,
        )
        untyped_protected = tuple(
            span.exact_token
            for span in self.runtime.tokenizer_profile.analyze(untyped_query).protected_identifiers
        )
        self.assertEqual(
            untyped_inventory.identifier_hashes,
            hybrid_module._source_graph_term_hashes(untyped_protected),
        )
        first_inventory = hybrid_module._deterministic_exact_filter_slots(
            "list all amber region code",
            tokenizer_profile=self.runtime.tokenizer_profile,
        )
        second_inventory = hybrid_module._deterministic_exact_filter_slots(
            "inventory code amber region",
            tokenizer_profile=self.runtime.tokenizer_profile,
        )
        self.assertEqual(first_inventory.identifier_hashes, ())
        self.assertEqual(first_inventory, second_inventory)
        self.assertEqual(
            first_inventory.topic_hashes,
            hybrid_module._source_graph_term_hashes(
                tuple(self.runtime.tokenizer_profile.analyze("amber region code").tokens)
            ),
        )

        full_address = f"{local_parts[0]}@example.test"
        full_address_hash = sha256_json(
            self.runtime.tokenizer_profile.normalize_exact_identifier_surface(full_address)
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
            source_session_binding_fingerprint=(session.source_session_binding_fingerprint or ""),
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
            provider._normalized_variant_hashes[local_hash].add(sha256_json("changed"))
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

    def test_zero_token_lexical_grounding_preserves_provider_local_ledger(
        self,
    ) -> None:
        grammar_fingerprint = sha256_json("generic_zero_token_grammar")
        tokenizer_profile = SimpleNamespace(
            analyze_query_grounding=lambda _value: SimpleNamespace(
                terms=(
                    SimpleNamespace(
                        start=0,
                        end=1,
                        normalized_term="x",
                        grammar_role="lexical",
                    ),
                ),
                grammar_policy_fingerprint=grammar_fingerprint,
            ),
            analyze=lambda _value: SimpleNamespace(tokens=frozenset()),
        )

        ordered_terms, resolved_grammar_fingerprint = (
            hybrid_module._ordered_source_occurrence_query_grounding(
                "x",
                tokenizer_profile=tokenizer_profile,
            )
        )

        self.assertEqual(resolved_grammar_fingerprint, grammar_fingerprint)
        self.assertEqual(ordered_terms[0][1:], ("lexical", ()))

    def test_kg_miss_uses_authorized_exact_source_fallback_with_citation(self) -> None:
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
        source_observation_id = "obs_issue56_semantic_current_body_1"
        observation = next(
            item
            for item in session.authorized_observations
            if item.observation_id == source_observation_id
        )
        lineage = next(
            item
            for item in session.occurrence_lineages
            if item.source_observation_id == source_observation_id
        )
        identifier = "DIRECT-CASE-1001"
        identifier_hash = hybrid_module._deterministic_exact_filter_slots(
            identifier,
            tokenizer_profile=self.runtime.tokenizer_profile,
        ).identifier_hashes[0]
        scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_observation_hashes=session.authorized_observation_hashes,
            source_session_binding_fingerprint=(session.source_session_binding_fingerprint or ""),
        )
        provider = SourceOccurrenceProvider(
            provider_id="mail_message_occurrence_direct_source_identifier_provider_v1",
            inventory_kind_alias="source_identifier_observation",
            resource_kind="mail_message_occurrence",
            normalized_field="message_occurrence.direct_source_identifier_v1",
            predicate="source_occurrence_has_identifier",
            operator="case_insensitive_exact",
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_scope_fingerprint=scope_fingerprint,
            occurrences=(
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json(lineage.occurrence_id),
                    value_bindings=(
                        (
                            identifier_hash,
                            identifier_hash,
                            sha256_json(observation.to_dict()),
                            lineage.lineage_fingerprint,
                        ),
                    ),
                ),
            ),
        )
        routed_session = replace(session, source_occurrence_providers=(provider,))
        request_contract = {
            "original_query_hash": sha256_json(f"{identifier} 交期"),
            "query_class": "evidence_lookup",
            "source_family_scope": ["mail"],
            "requested_fields": [],
            "maximum_claim_strength": "cited_evidence",
        }
        limits = replace(DEFAULT_SEMANTIC_PLAN_LIMITS, max_time_budget_ms=1_234)
        phase_trace = hybrid_module.SemanticPhaseTrace()
        session_calls: list[tuple[object, dict[str, object]]] = []
        route_calls: list[dict[str, object]] = []

        original_session_query = hybrid_module.AuthorizedSemanticMailSession.query

        def recording_session_query(bound_session, *args, **kwargs):
            session_calls.append((bound_session, kwargs))
            return original_session_query(bound_session, *args, **kwargs)

        original_route = hybrid_module.route_semantic_query

        def recording_route(**kwargs):
            route_calls.append(kwargs)
            return original_route(**kwargs)

        with (
            patch.object(
                hybrid_module.AuthorizedSemanticMailSession,
                "query",
                new=recording_session_query,
            ),
            patch.object(
                hybrid_module,
                "route_semantic_query",
                side_effect=recording_route,
            ),
        ):
            result, _, _ = hybrid_module.execute_bounded_adaptive_query(
                session=routed_session,
                query_text=f"{identifier} 交期",
                request_contract=request_contract,
                effective_graph_view=self.inputs.effective_graph_view,
                limits=limits,
                phase_trace=phase_trace,
            )
        assert result is not None
        self.assertIn("authorized_source_exact_fallback_used", result.warnings)
        self.assertTrue(result.answer_citation_hashes)
        self.assertEqual(result.claim_strength, "cited_evidence")
        self.assertIsNotNone(result.exact_result)
        self.assertEqual(
            result.exact_result.items[0].cited_observation_hashes,
            (sha256_json(observation.to_dict()),),
        )
        self.assertEqual(len(session_calls), 2)
        first_session, first_call = session_calls[0]
        fallback_session, fallback_call = session_calls[1]
        self.assertIs(first_session, routed_session)
        self.assertIs(fallback_session, routed_session)
        self.assertEqual(
            first_call["request_contract"],
            request_contract,
        )
        self.assertIs(
            first_call["request_contract"],
            fallback_call["request_contract"],
        )
        self.assertIs(first_call["phase_trace"], phase_trace)
        self.assertIs(fallback_call["phase_trace"], phase_trace)
        self.assertEqual(
            [call["limits"].max_time_budget_ms for _, call in session_calls],
            [1_234, 1_234],
        )
        self.assertIs(
            first_call["execution_deadline"],
            fallback_call["execution_deadline"],
        )
        self.assertIsNone(first_call["exact_inventory_kind"])
        self.assertEqual(
            fallback_call["exact_inventory_kind"],
            provider.inventory_kind_alias,
        )
        self.assertEqual(
            fallback_call["exact_field"],
            provider.normalized_field,
        )
        for bound_session, _ in session_calls:
            self.assertEqual(
                bound_session.requester_user_id,
                session.requester_user_id,
            )
            self.assertEqual(bound_session.workspace_id, session.workspace_id)
            self.assertEqual(
                bound_session.authorized_source_scope_ids,
                session.authorized_source_scope_ids,
            )
        self.assertEqual(len(route_calls), 2)
        for call in route_calls:
            self.assertEqual(call["requester_user_id"], session.requester_user_id)
            self.assertEqual(call["workspace_id"], session.workspace_id)
            self.assertEqual(
                call["source_scope_ids"],
                session.authorized_source_scope_ids,
            )
        self.assertEqual(phase_trace.to_safe_dict()["terminal_status"], "completed")

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
        second_query_hash = next(value for value in multi_query_hashes if value != query_hash)
        authorized_hash_by_id = dict(session.authorized_observation_hashes)
        lineage_by_id = {
            lineage.source_observation_id: lineage for lineage in session.occurrence_lineages
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
            source_session_binding_fingerprint=(session.source_session_binding_fingerprint or ""),
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
                provider_id=("mail_message_occurrence_direct_source_identifier_provider_v1"),
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
                        item_hash=sha256_json(lineage_by_id[first_observation_id].occurrence_id),
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

        participant_query = "請 把 alpha.beta 的 信件 都 調閱出來"
        participant_hash = hybrid_module._deterministic_exact_filter_slots(
            participant_query,
            tokenizer_profile=self.runtime.tokenizer_profile,
        ).identifier_hashes[0]
        participant_any_provider = replace(
            provider(
                "participant.any.local_part",
                matching_hash=participant_hash,
                same_thread_hash=sha256_json("participant-any-peer"),
                inventory_kind_alias="participant_local_part",
            ),
            provider_id="participant_any_source_occurrence_provider_v1",
        )
        participant_from_provider = replace(
            participant_any_provider,
            provider_id="participant_from_source_occurrence_provider_v1",
            normalized_field="participant.from.local_part",
        )
        participant_to_provider = replace(
            participant_any_provider,
            provider_id="participant_to_source_occurrence_provider_v1",
            normalized_field="participant.to.local_part",
        )
        unrelated_column_hash = exact_module.source_occurrence_column_capability_hash(
            "generic-unrelated-field"
        )
        unrelated_column_candidate_hash = sha256_json("generic-unrelated-field")
        unrelated_value_hash = sha256_json("generic-unrelated-value")
        unrelated_projection = (
            "GenericUnrelatedField",
            "generic-unrelated-value",
            *first_reference,
        )
        unrelated_combined_provider = replace(
            direct_provider,
            provider_id="generic_unrelated_structured_provider_v1",
            inventory_kind_alias="attachment_table_row",
            resource_kind="attachment_table_row_occurrence",
            normalized_field="table.row.cell_value",
            predicate="source_occurrence_row_contains",
            filter_slot_policy="combined_present_intersection_v1",
            occurrences=(
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json("generic-unrelated-row"),
                    value_bindings=(
                        (
                            unrelated_column_candidate_hash,
                            exact_module.source_occurrence_projection_capability_hash(
                                unrelated_column_candidate_hash
                            ),
                            *first_reference,
                        ),
                        (
                            unrelated_value_hash,
                            unrelated_value_hash,
                            *first_reference,
                        ),
                    ),
                    projection_bindings=(unrelated_projection,),
                    structure_status="candidate_only",
                    structured_column_bindings=(
                        (
                            unrelated_column_hash,
                            unrelated_column_candidate_hash,
                            unrelated_value_hash,
                            *unrelated_projection,
                        ),
                    ),
                ),
            ),
        )
        participant_session = replace(
            session,
            source_occurrence_providers=(
                participant_any_provider,
                participant_from_provider,
                participant_to_provider,
                unrelated_combined_provider,
            ),
        )
        participant_result = participant_session.query(
            query_text=participant_query,
            effective_graph_view=self.inputs.effective_graph_view,
        )
        assert participant_result.exact_result is not None
        self.assertEqual(
            participant_result.exact_result.source_occurrence_page["provider_fingerprint"],
            participant_any_provider.provider_fingerprint,
        )
        typed_from_result = participant_session.query(
            query_text=participant_query,
            effective_graph_view=self.inputs.effective_graph_view,
            exact_field="participant.from.local_part",
        )
        assert typed_from_result.exact_result is not None
        self.assertEqual(
            typed_from_result.exact_result.source_occurrence_page["provider_fingerprint"],
            participant_from_provider.provider_fingerprint,
        )
        combined_only_session = replace(
            session,
            source_occurrence_providers=(unrelated_combined_provider,),
        )
        with (
            patch.object(
                hybrid_module.AuthorizedHybridMailIndex,
                "query",
                side_effect=AssertionError("ranked top-k fallback invoked"),
            ),
            self.assertRaisesRegex(
                ContractValidationError,
                "source occurrence provider selection is invalid",
            ),
        ):
            combined_only_session.query(
                query_text=participant_query,
                effective_graph_view=self.inputs.effective_graph_view,
            )
        evidence_miss_query = "GENERIC-MISSING-9001"
        self.assertTrue(hybrid_module._deterministic_exact_filter_slots(
            evidence_miss_query, tokenizer_profile=self.runtime.tokenizer_profile,
        ).identifier_hashes)
        evidence_miss = combined_only_session.query(
            query_text=evidence_miss_query,
            effective_graph_view=self.inputs.effective_graph_view,
        )
        self.assertEqual(evidence_miss.query_class, "evidence_lookup")
        self.assertEqual(evidence_miss.status, "incomplete")
        self.assertIsNone(evidence_miss.exact_result)
        self.assertEqual(evidence_miss.answer_citation_hashes, ())
        self.assertEqual(evidence_miss.warnings, ("authorized_evidence_identifier_not_found",))
        fallback_trace = hybrid_module.SemanticPhaseTrace()
        fallback = combined_only_session.query(
            query_text="generic status lookup",
            effective_graph_view=self.inputs.effective_graph_view,
            phase_trace=fallback_trace,
        )
        fallback_phases = {
            item["phase"]: item["outcome"] for item in fallback_trace.to_safe_dict()["phases"]
        }
        self.assertEqual(fallback.query_class, "evidence_lookup")
        self.assertIsNone(fallback.exact_result)
        self.assertEqual(fallback_phases["strong_rag"], "completed")

        exact_attachment_query = "列出全部 DIRECT-CASE-1001 記錄"
        with (
            patch.object(
                hybrid_module.AuthorizedHybridMailIndex,
                "query",
                side_effect=AssertionError("ranked top-k fallback invoked"),
            ),
            self.assertRaisesRegex(
                ContractValidationError,
                "source occurrence provider selection is invalid",
            ),
        ):
            participant_session.query(
                query_text=exact_attachment_query,
                request_contract={
                    "original_query_hash": sha256_json(exact_attachment_query),
                    "query_class": "exact_set_or_inventory",
                    "source_family_scope": ["attachment_table"],
                    "requested_fields": [],
                    "maximum_claim_strength": "complete_authorized_scope",
                },
                effective_graph_view=self.inputs.effective_graph_view,
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
            cached_crosswalks = dict(hybrid_module._EVIDENCE_LINEAGE_CROSSWALK_CACHE)

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

    def test_built_source_neutral_session_does_not_repeat_full_validation_for_queries(
        self,
    ) -> None:
        workspace_id = "workspace_source_neutral_validation"
        source_scope_id = "project_source_neutral_validation"
        authorized_source = hybrid_module.validated_authorized_semantic_source(
            source_kind=hybrid_module.GITHUB_PROJECT_OBSERVATION_SOURCE_KIND,
            workspace_id=workspace_id,
            source_scope_ids=(source_scope_id,),
        )
        permission_scope = PermissionScope.project(source_scope_id)
        issue_key = "generic_issue_validation"

        def observation(
            observation_id,
            observation_type,
            source_local_key,
            text,
            *,
            parent_source_local_key=None,
        ):
            source_record_fingerprint = sha256_json(
                {
                    "observation_id": observation_id,
                    "record_kind": observation_type,
                    "source_local_key": source_local_key,
                }
            )
            location = {
                "source_local_key": source_local_key,
                "source_record_fingerprint": source_record_fingerprint,
                "record_kind": observation_type,
            }
            if parent_source_local_key is not None:
                location["parent_source_local_key"] = parent_source_local_key
            payload = {
                **location,
                "issue_number": 1,
                "created_at": "2026-08-30T00:00:00Z",
                "updated_at": "2026-08-30T00:01:00Z",
                "source_native_issue_references": [],
            }
            if observation_type == "issue_record":
                payload.update({"state": "open", "label_names": ["generic"]})
            return Observation.from_dict(
                Observation(
                    observation_id=observation_id,
                    extractor_run_id="run_source_neutral_validation",
                    observation_type=observation_type,
                    modality="project",
                    location=location,
                    confidence=1.0,
                    permission_scope=permission_scope,
                    created_at="2026-08-30T00:01:00Z",
                    asset_id="asset_source_neutral_validation",
                    payload=payload,
                    extracted_value={
                        "stable_values": [source_local_key],
                    },
                    text=text,
                ).to_dict()
            )

        observations = (
            observation(
                "obs_source_neutral_validation_issue",
                "issue_record",
                issue_key,
                "Generic issue record for deterministic inventory.",
            ),
            observation(
                "obs_source_neutral_validation_comment",
                "top_level_issue_comment",
                "generic_comment_validation",
                "Generic comment preserving source lineage.",
                parent_source_local_key=issue_key,
            ),
        )
        authorized_hashes = {
            item.observation_id: sha256_json(item.to_dict()) for item in observations
        }
        lineages = tuple(
            hybrid_module.source_occurrence_lineage_from_observation(
                item,
                authorized_source=authorized_source,
            )
            for item in observations
        )
        snippet_index, snippet_manifest = hybrid_module.build_authorized_observation_snippet_index(
            observations,
            authorized_source=authorized_source,
            occurrence_lineages=lineages,
            authorized_observation_hash_by_id=authorized_hashes,
            tokenizer_profile=self.runtime.tokenizer_profile,
        )
        dense_vector = (
            1.0,
            *([0.0] * (self.runtime.dense_encoder.dimension - 1)),
        )
        immutable_dense_vectors = tuple(dense_vector for _snippet in snippet_index.snippets)
        candidate_builder = hybrid_module._hybrid_candidate_from_observation_snippet
        with patch.object(
            hybrid_module,
            "_hybrid_candidate_from_observation_snippet",
            wraps=candidate_builder,
        ) as candidate_calls:
            hybrid_module._build_authorized_hybrid_observation_index(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                runtime_components=self.runtime,
                dense_vectors=immutable_dense_vectors,
            )
        self.assertTrue(
            all(
                call.kwargs["dense_vector"] is immutable_dense_vectors[index]
                for index, call in enumerate(candidate_calls.call_args_list)
            )
        )
        for mutable_dense_vectors in (
            list(immutable_dense_vectors),
            tuple(list(vector) for vector in immutable_dense_vectors),
        ):
            with self.assertRaisesRegex(
                ContractValidationError,
                "dense vectors must be immutable",
            ):
                hybrid_module._build_authorized_hybrid_observation_index(
                    authorized_source=authorized_source,
                    snippet_index=snippet_index,
                    authorized_observations=observations,
                    occurrence_lineages=lineages,
                    runtime_components=self.runtime,
                    dense_vectors=mutable_dense_vectors,
                )
        full_validation = hybrid_module._validated_source_neutral_inputs
        full_graph_validation = hybrid_module._validate_source_neutral_graph_binding
        with (
            patch(
                "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
                return_value=self.runtime,
            ),
            patch.object(
                hybrid_module,
                "_validated_source_neutral_inputs",
                wraps=full_validation,
            ) as validated_inputs,
            patch.object(
                hybrid_module,
                "_validate_source_neutral_graph_binding",
                wraps=full_graph_validation,
            ) as validated_graph_binding,
        ):
            session = hybrid_module.build_authorized_semantic_observation_session(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=observations,
                occurrence_lineages=lineages,
                requester_user_id="user_source_neutral_validation",
            )
            graph_build = build_authorized_source_backed_effective_graph_view(
                session=session,
                source_binding_fingerprint=snippet_manifest.index_fingerprint,
            )
            build_validation_calls = validated_inputs.call_count
            build_graph_validation_calls = validated_graph_binding.call_count
            traces = (
                hybrid_module.SemanticPhaseTrace(),
                hybrid_module.SemanticPhaseTrace(),
            )
            results = tuple(
                session.query(
                    query_text="List all generic issue records.",
                    effective_graph_view=graph_build.effective_graph_view,
                    exact_inventory_kind="issue_record",
                    limits=SemanticPlanLimits(max_time_budget_ms=1_500),
                    phase_trace=trace,
                )
                for trace in traces
            )

        self.assertGreater(build_validation_calls, 0)
        self.assertEqual(validated_inputs.call_count, build_validation_calls)
        self.assertGreater(build_graph_validation_calls, 0)
        self.assertEqual(
            validated_graph_binding.call_count,
            build_graph_validation_calls,
        )
        self.assertEqual(
            snippet_index.source_access_fingerprint,
            authorized_source.authorization_fingerprint,
        )
        self.assertRegex(
            session.source_session_binding_fingerprint or "",
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertRegex(session.index.index_fingerprint, r"^sha256:[0-9a-f]{64}$")
        for result, trace in zip(results, traces, strict=True):
            self.assertEqual(result.status, "complete_authorized_scope")
            self.assertEqual(
                result.exact_executor_status,
                "complete_authorized_scope",
            )
            phase_report = trace.to_safe_dict()
            phase_outcomes = {item["phase"]: item["outcome"] for item in phase_report["phases"]}
            self.assertEqual(phase_report["terminal_status"], "completed")
            self.assertIsNone(phase_report["deadline_exhausted_phase"])
            for phase in (
                "source_session_validation",
                "routing_plan",
                "deterministic_exact_execution",
            ):
                self.assertEqual(phase_outcomes[phase], "completed")
        self.assertEqual(results[0].plan_fingerprint, results[1].plan_fingerprint)
        self.assertEqual(results[0].result_fingerprint, results[1].result_fingerprint)

        query_kwargs = {
            "query_text": "List all generic issue records.",
            "effective_graph_view": graph_build.effective_graph_view,
            "exact_inventory_kind": "issue_record",
            "limits": SemanticPlanLimits(max_time_budget_ms=1_500),
        }
        copied_observations = tuple(list(session.authorized_observations))
        copied_lineages = tuple(list(session.occurrence_lineages))
        copied_retrieval_hashes = tuple(list(session.retrieval_observation_hashes))
        copied_authorized_hashes = tuple(list(session.authorized_observation_hashes))
        # A wrapper preserving all immutable owner-bound objects is supported;
        # changing the requester while reusing those objects is not.
        self.assertEqual(replace(session).query(**query_kwargs).result_fingerprint,
                         results[0].result_fingerprint)
        with self.assertRaisesRegex(
            ContractValidationError,
            "effective graph requester mismatch",
        ):
            hybrid_module.AuthorizedSemanticObservationSession(
                index=session.index,
                requester_user_id="user_unbound_snapshot",
                workspace_id=session.workspace_id,
                selected_source_scope_ids=session.selected_source_scope_ids,
                authorized_source_scope_ids=session.authorized_source_scope_ids,
                retrieval_observation_hashes=session.retrieval_observation_hashes,
                authorized_observation_hashes=session.authorized_observation_hashes,
                authorized_source=session.authorized_source,
                authorized_observations=session.authorized_observations,
                occurrence_lineages=session.occurrence_lineages,
                source_session_binding_fingerprint=(session.source_session_binding_fingerprint),
            ).query(**query_kwargs)
        with self.assertRaisesRegex(
            ContractValidationError,
            "session binding mismatch",
        ):
            hybrid_module.AuthorizedSemanticObservationSession(
                index=session.index,
                requester_user_id=session.requester_user_id,
                workspace_id=session.workspace_id,
                selected_source_scope_ids=session.selected_source_scope_ids,
                authorized_source_scope_ids=session.authorized_source_scope_ids,
                retrieval_observation_hashes=copied_retrieval_hashes,
                authorized_observation_hashes=copied_authorized_hashes,
                authorized_source=session.authorized_source,
                authorized_observations=copied_observations,
                occurrence_lineages=copied_lineages,
                source_session_binding_fingerprint=(session.source_session_binding_fingerprint),
            ).query(**query_kwargs)
        with self.assertRaisesRegex(
            ContractValidationError,
            "session binding mismatch",
        ):
            replace(session, source_authority_fingerprint=sha256_json("unbound_authority")).query(
                **query_kwargs
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "session binding mismatch",
        ):
            replace(
                session,
                authorized_observations=copied_observations,
            ).query(**query_kwargs)
        with self.assertRaisesRegex(
            ContractValidationError,
            "source binding mismatch",
        ):
            replace(
                session,
                authorized_source=replace(
                    authorized_source,
                    workspace_id="workspace_not_authorized",
                ),
            ).query(**query_kwargs)
        with self.assertRaisesRegex(
            ContractValidationError,
            "session binding mismatch",
        ):
            replace(
                session,
                source_session_binding_fingerprint=sha256_json("stale_source_session"),
            ).query(**query_kwargs)
        with self.assertRaisesRegex(
            ContractValidationError,
            "index binding mismatch",
        ):
            replace(
                session,
                index=replace(
                    session.index,
                    index_fingerprint=sha256_json("stale_index"),
                ),
            ).query(**query_kwargs)
        sealed_observation = next(
            item
            for item in session.authorized_observations
            if item.observation_type == "issue_record"
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "snapshot is immutable",
        ):
            sealed_observation.location["source_local_key"] = "mutated"
        with self.assertRaisesRegex(
            ContractValidationError,
            "snapshot is immutable",
        ):
            sealed_observation.payload["label_names"].append("mutated")
        with self.assertRaisesRegex(
            ContractValidationError,
            "snapshot is immutable",
        ):
            sealed_observation.permission_scope["scope_id"] = "mutated"
        with self.assertRaisesRegex(
            ContractValidationError,
            "snapshot is immutable",
        ):
            sealed_observation.extracted_value["stable_values"].append("mutated")
        graph_node = graph_build.effective_graph_view.visible_nodes[0]
        with self.assertRaisesRegex(
            ContractValidationError,
            "snapshot is immutable",
        ):
            graph_node.properties["source_kind_hash"] = sha256_json("different_source_kind")
        graph_properties = dict(graph_node.properties)
        graph_properties["source_kind_hash"] = sha256_json("different_source_kind")
        with self.assertRaisesRegex(
            ContractValidationError,
            "effective graph content snapshot is unavailable",
        ):
            session.query(
                **{
                    **query_kwargs,
                    "effective_graph_view": replace(
                        graph_build.effective_graph_view,
                        visible_nodes=[
                            replace(
                                graph_node,
                                properties=graph_properties,
                            ),
                            *graph_build.effective_graph_view.visible_nodes[1:],
                        ],
                    ),
                }
            )

    def test_sealed_source_schema_capability_manifest_is_strictly_bound(self) -> None:
        source_session_fingerprint = sha256_json("source_session")
        scope_fingerprint = sha256_json("authorized_scope")
        safe_binding = {
            "retrieval_snapshot_byte_sha256": sha256_json("retrieval_bytes"),
            "retrieval_snapshot_fingerprint": sha256_json("retrieval_snapshot"),
            "source_snapshot_fingerprint": sha256_json("source_snapshot"),
        }
        session = SimpleNamespace(
            index=SimpleNamespace(_runtime_components=self.runtime),
            requester_user_id="user_schema_contract",
            workspace_id="workspace_formowl",
            authorized_source_scope_ids=("source_scope_schema_contract",),
            source_session_binding_fingerprint=source_session_fingerprint,
        )
        column_hash = exact_module.source_occurrence_column_capability_hash("neutralfield")
        candidate_hash = sha256_json("neutralfield")
        columns = [
            {
                "column_hash": column_hash,
                "candidate_hashes": [candidate_hash],
            }
        ]
        provider_binding_fingerprint = sha256_json(
            {
                "artifact_id": "attachment_table_row_provider_capability_binding_v1",
                "provider_id": "attachment_table_row_source_occurrence_provider_v1",
                "inventory_kind_alias": "attachment_table_row",
                "resource_kind": "attachment_table_row_occurrence",
                "normalized_field": "table.row.cell_value",
                "predicate": "source_occurrence_row_contains",
                "operator": "case_insensitive_exact",
                "filter_slot_policy": "combined_present_intersection_v1",
                "requester_user_id": session.requester_user_id,
                "workspace_id": session.workspace_id,
                "source_scope_ids": list(session.authorized_source_scope_ids),
                "authorized_scope_fingerprint": scope_fingerprint,
                "policy_id": gateway_loader._SOURCE_SCHEMA_CAPABILITY_POLICY_ID,
            }
        )
        manifest = {
            "artifact_id": (gateway_loader._SOURCE_SCHEMA_CAPABILITY_MANIFEST_ARTIFACT_ID),
            "schema_version": 1,
            "policy_id": gateway_loader._SOURCE_SCHEMA_CAPABILITY_POLICY_ID,
            "review_status": "candidate_only_unreviewed",
            "human_review_complete": False,
            "identity_scope_mode": "workspace_only_v1",
            "workspace_fingerprint": sha256_json(session.workspace_id),
            **safe_binding,
            "source_session_binding_fingerprint": source_session_fingerprint,
            "authorized_scope_fingerprint": scope_fingerprint,
            "provider_binding_fingerprint": provider_binding_fingerprint,
            "tokenizer_profile_fingerprint": (self.runtime.tokenizer_profile.profile_fingerprint),
            "column_count": 1,
            "candidate_hash_count": 1,
            "columns": columns,
            "mapping_fingerprint": sha256_json([[column_hash, [candidate_hash]]]),
        }

        with TemporaryDirectory() as directory:
            path = Path(directory) / "candidate-manifest.json"

            def write_sealed(payload):
                sealed = dict(payload)
                sealed["manifest_fingerprint"] = sha256_json(sealed)
                raw = json.dumps(
                    sealed,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                path.write_bytes(raw)
                return "sha256:" + hashlib.sha256(raw).hexdigest()

            byte_sha256 = write_sealed(manifest)
            environment = {
                gateway_loader._SOURCE_SCHEMA_CAPABILITY_MANIFEST_PATH_ENV: str(path),
                gateway_loader._SOURCE_SCHEMA_CAPABILITY_MANIFEST_SHA256_ENV: (byte_sha256),
            }
            with patch.dict(os.environ, environment, clear=False):
                self.assertEqual(
                    gateway_loader._load_source_schema_capability_mapping(
                        session,
                        safe_binding=safe_binding,
                        authorized_scope_fingerprint=scope_fingerprint,
                    ),
                    {column_hash: frozenset({candidate_hash})},
                )
                with patch.dict(
                    os.environ,
                    {
                        gateway_loader._SOURCE_SCHEMA_CAPABILITY_MANIFEST_SHA256_ENV: (
                            sha256_json("different_bytes")
                        )
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(
                        ContractValidationError,
                        "manifest binding is invalid",
                    ):
                        gateway_loader._load_source_schema_capability_mapping(
                            session,
                            safe_binding=safe_binding,
                            authorized_scope_fingerprint=scope_fingerprint,
                        )

                for mutation in (
                    {"tenant_id": "forbidden"},
                    {"policy_id": "different_candidate_policy"},
                ):
                    changed_byte_sha256 = write_sealed({**manifest, **mutation})
                    with patch.dict(
                        os.environ,
                        {
                            gateway_loader._SOURCE_SCHEMA_CAPABILITY_MANIFEST_SHA256_ENV: (
                                changed_byte_sha256
                            )
                        },
                        clear=False,
                    ):
                        with self.assertRaisesRegex(
                            ContractValidationError,
                            "manifest binding is invalid",
                        ):
                            gateway_loader._load_source_schema_capability_mapping(
                                session,
                                safe_binding=safe_binding,
                                authorized_scope_fingerprint=scope_fingerprint,
                            )

    def test_sealed_source_schema_candidates_are_provider_bound_and_incomplete(
        self,
    ) -> None:
        permission_scope = PermissionScope.project("source_scope_schema_contract")

        def observation(
            observation_id,
            observation_type,
            *,
            modality,
            asset_id,
            location,
            payload,
            text=None,
        ):
            return Observation(
                observation_id=observation_id,
                extractor_run_id="run_schema_contract",
                observation_type=observation_type,
                modality=modality,
                location=location,
                confidence=1.0,
                permission_scope=permission_scope,
                created_at="2026-08-30T00:00:00Z",
                asset_id=asset_id,
                payload=payload,
                text=text,
            )

        parent = observation(
            "obs_schema_parent",
            "email_attachment_occurrence",
            modality="mail",
            asset_id="asset_schema_parent",
            location={"message_occurrence_id": "message_schema_contract"},
            payload={"child_asset_id": "asset_schema_child"},
        )
        row_location = {"sheet_name": "sheet", "table_index": 1, "row_index": 2}
        row = observation(
            "obs_schema_row",
            "table_row",
            modality="document",
            asset_id="asset_schema_child",
            location=row_location,
            payload={
                "table_structure": {
                    "structure_status": "source_provided",
                    "row_role": "data",
                }
            },
        )
        cell = observation(
            "obs_schema_cell",
            "table_cell",
            modality="document",
            asset_id="asset_schema_child",
            location={**row_location, "cell_index": 1},
            payload={"table_structure": {"column_name": "NeutralField"}},
            text="neutral-value",
        )
        observations = (parent, row, cell)
        session = SimpleNamespace(
            authorized_observations=observations,
            authorized_observation_hashes=tuple(
                sorted(
                    (
                        observation.observation_id,
                        sha256_json(observation.to_dict()),
                    )
                    for observation in observations
                )
            ),
            occurrence_lineages=(
                SimpleNamespace(
                    source_observation_id=row.observation_id,
                    parent_occurrence_id="message_schema_contract",
                    lineage_fingerprint=sha256_json("row_lineage"),
                ),
                SimpleNamespace(
                    source_observation_id=cell.observation_id,
                    parent_occurrence_id="message_schema_contract",
                    lineage_fingerprint=sha256_json("cell_lineage"),
                ),
            ),
            index=SimpleNamespace(_runtime_components=self.runtime),
            requester_user_id="user_schema_contract",
            workspace_id="workspace_formowl",
            authorized_source_scope_ids=("source_scope_schema_contract",),
        )
        profile = self.runtime.tokenizer_profile
        normalized_field = profile.normalize_exact_identifier_surface("NeutralField")
        column_hash = exact_module.source_occurrence_column_capability_hash(normalized_field)
        candidate_hashes = frozenset(
            sha256_json(token) for token in profile.analyze("NeutralField").tokens if token
        )
        provider = gateway_loader._build_attachment_table_row_provider(
            session,
            authorized_scope_fingerprint=sha256_json("schema_scope"),
            source_schema_capability_mapping={column_hash: candidate_hashes},
        )
        assert provider is not None
        self.assertEqual(
            sum(
                occurrence.structure_status == "candidate_only"
                for occurrence in provider.occurrences
            ),
            1,
        )
        self.assertEqual(provider.occurrences[0].structure_status, "candidate_only")
        self.assertEqual(
            {binding[1] for binding in provider.occurrences[0].structured_column_bindings},
            set(candidate_hashes),
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "capability coverage is incomplete",
        ):
            gateway_loader._build_attachment_table_row_provider(
                session,
                authorized_scope_fingerprint=sha256_json("schema_scope"),
                source_schema_capability_mapping={},
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "capability binding is invalid",
        ):
            gateway_loader._build_attachment_table_row_provider(
                session,
                authorized_scope_fingerprint=sha256_json("schema_scope"),
                source_schema_capability_mapping={
                    column_hash: frozenset({sha256_json("different_candidate")})
                },
            )

    def test_candidate_less_column_is_non_projectable_but_evidence_preserved(
        self,
    ) -> None:
        source_scope_id = "source_scope_candidate_less_contract"
        permission_scope = PermissionScope.project(source_scope_id)

        def observation(
            observation_id,
            observation_type,
            *,
            modality,
            asset_id,
            location,
            payload,
            text=None,
        ):
            return Observation(
                observation_id=observation_id,
                extractor_run_id="run_candidate_less_contract",
                observation_type=observation_type,
                modality=modality,
                location=location,
                confidence=1.0,
                permission_scope=permission_scope,
                created_at="2026-08-30T00:00:00Z",
                asset_id=asset_id,
                payload=payload,
                text=text,
            )

        parent = observation(
            "obs_candidate_less_parent",
            "email_attachment_occurrence",
            modality="mail",
            asset_id="asset_candidate_less_parent",
            location={"message_occurrence_id": "message_candidate_less_contract"},
            payload={"child_asset_id": "asset_candidate_less_child"},
        )
        row_location = {
            "sheet_name": "sheet",
            "table_index": 1,
            "row_index": 2,
        }
        row = observation(
            "obs_candidate_less_row",
            "table_row",
            modality="document",
            asset_id="asset_candidate_less_child",
            location=row_location,
            payload={
                "table_structure": {
                    "structure_status": "source_provided",
                    "row_role": "data",
                }
            },
        )
        projectable_field = "NeutralField"
        projectable_cell = observation(
            "obs_candidate_less_projectable_cell",
            "table_cell",
            modality="document",
            asset_id="asset_candidate_less_child",
            location={**row_location, "cell_index": 1},
            payload={"table_structure": {"column_name": projectable_field}},
            text="neutral-value",
        )
        candidate_less_field = "※"
        candidate_less_cell = observation(
            "obs_candidate_less_structural_cell",
            "table_cell",
            modality="document",
            asset_id="asset_candidate_less_child",
            location={**row_location, "cell_index": 2},
            payload={"table_structure": {"column_name": candidate_less_field}},
            text="structural-value",
        )
        observations = (
            parent,
            row,
            projectable_cell,
            candidate_less_cell,
        )
        row_lineage_fingerprint = sha256_json("candidate_less_row_lineage")
        projectable_lineage_fingerprint = sha256_json("candidate_less_projectable_lineage")
        candidate_less_lineage_fingerprint = sha256_json("candidate_less_structural_lineage")
        authorized_hashes = tuple(
            sorted(
                (
                    item.observation_id,
                    sha256_json(item.to_dict()),
                )
                for item in observations
            )
        )
        session = SimpleNamespace(
            authorized_observations=observations,
            authorized_observation_hashes=authorized_hashes,
            occurrence_lineages=(
                SimpleNamespace(
                    source_observation_id=row.observation_id,
                    parent_occurrence_id="message_candidate_less_contract",
                    lineage_fingerprint=row_lineage_fingerprint,
                ),
                SimpleNamespace(
                    source_observation_id=projectable_cell.observation_id,
                    parent_occurrence_id="message_candidate_less_contract",
                    lineage_fingerprint=projectable_lineage_fingerprint,
                ),
                SimpleNamespace(
                    source_observation_id=candidate_less_cell.observation_id,
                    parent_occurrence_id="message_candidate_less_contract",
                    lineage_fingerprint=candidate_less_lineage_fingerprint,
                ),
            ),
            index=SimpleNamespace(_runtime_components=self.runtime),
            requester_user_id=REQUESTER_USER_ID,
            workspace_id=WORKSPACE_ID,
            authorized_source_scope_ids=(source_scope_id,),
        )
        profile = self.runtime.tokenizer_profile
        projectable_tokens = profile.analyze(projectable_field).tokens
        candidate_less_tokens = profile.analyze(candidate_less_field).tokens
        self.assertTrue(projectable_tokens)
        self.assertEqual(candidate_less_tokens, frozenset())

        projectable_column_hash = exact_module.source_occurrence_column_capability_hash(
            profile.normalize_exact_identifier_surface(projectable_field)
        )
        candidate_less_column_hash = exact_module.source_occurrence_column_capability_hash(
            profile.normalize_exact_identifier_surface(candidate_less_field)
        )
        projectable_candidate_hashes = frozenset(sha256_json(token) for token in projectable_tokens)
        scope_fingerprint = sha256_json("candidate_less_schema_scope")
        unsealed = gateway_loader._build_attachment_table_row_provider(
            session,
            authorized_scope_fingerprint=scope_fingerprint,
        )
        sealed = gateway_loader._build_attachment_table_row_provider(
            session,
            authorized_scope_fingerprint=scope_fingerprint,
            source_schema_capability_mapping={
                projectable_column_hash: projectable_candidate_hashes,
            },
        )
        assert unsealed is not None
        assert sealed is not None
        self.assertEqual(len(unsealed.occurrences), 1)
        self.assertEqual(len(sealed.occurrences), 1)
        unsealed_occurrence = unsealed.occurrences[0]
        sealed_occurrence = sealed.occurrences[0]

        self.assertEqual(
            unsealed_occurrence.structured_column_bindings,
            sealed_occurrence.structured_column_bindings,
        )
        self.assertEqual(
            set(unsealed._column_postings),
            {projectable_column_hash},
        )
        self.assertEqual(
            set(sealed._column_postings),
            {projectable_column_hash},
        )
        self.assertNotIn(candidate_less_column_hash, unsealed._column_postings)
        self.assertNotIn(candidate_less_column_hash, sealed._column_postings)

        candidate_less_cell_hash = dict(authorized_hashes)[candidate_less_cell.observation_id]
        candidate_less_projection_binding = (
            candidate_less_field,
            candidate_less_cell.text,
            candidate_less_cell_hash,
            candidate_less_lineage_fingerprint,
        )
        self.assertEqual(
            unsealed_occurrence.projection_bindings,
            sealed_occurrence.projection_bindings,
        )
        self.assertIn(
            candidate_less_projection_binding,
            unsealed_occurrence.projection_bindings,
        )
        self.assertEqual(
            unsealed_occurrence.value_bindings,
            sealed_occurrence.value_bindings,
        )
        candidate_less_value_hashes = {
            sha256_json(token) for token in profile.analyze(candidate_less_cell.text or "").tokens
        }
        self.assertTrue(candidate_less_value_hashes)
        self.assertTrue(
            any(
                normalized_hash in candidate_less_value_hashes
                and citation_hash == candidate_less_cell_hash
                and lineage_fingerprint == candidate_less_lineage_fingerprint
                for (
                    normalized_hash,
                    _variant_hash,
                    citation_hash,
                    lineage_fingerprint,
                ) in sealed_occurrence.value_bindings
            )
        )

        with self.assertRaisesRegex(
            ContractValidationError,
            "capability coverage is incomplete",
        ):
            gateway_loader._build_attachment_table_row_provider(
                session,
                authorized_scope_fingerprint=scope_fingerprint,
                source_schema_capability_mapping={},
            )
        with self.assertRaisesRegex(
            ContractValidationError,
            "capability binding is invalid",
        ):
            gateway_loader._build_attachment_table_row_provider(
                session,
                authorized_scope_fingerprint=scope_fingerprint,
                source_schema_capability_mapping={
                    projectable_column_hash: projectable_candidate_hashes,
                    candidate_less_column_hash: frozenset({candidate_less_column_hash}),
                },
            )

        self.assertEqual(sealed_occurrence.structure_status, "candidate_only")
        projectable_value_candidates = tuple(
            sha256_json(token)
            for token in sorted(profile.analyze(projectable_cell.text or "").tokens)
        )
        partition = sealed.partition_ordered_lexical_candidates(
            (
                (
                    sha256_json("candidate_less_filter_term"),
                    projectable_value_candidates,
                ),
                (
                    sha256_json("candidate_less_projection_term"),
                    tuple(sorted(projectable_candidate_hashes)),
                ),
            )
        )
        plan = route_semantic_query(
            query_text="generic structured inventory",
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            effective_graph_view=self.inputs.effective_graph_view,
            exact_inventory_kind=sealed.resource_kind,
            exact_filter_term_hashes=partition.filter_term_hashes,
            exact_projection_term_hashes=partition.projection_column_hashes,
            exact_column_value_hash_pairs=partition.column_value_hash_pairs,
            exact_lexical_term_ledger=partition.lexical_term_ledger,
            exact_grammar_policy_fingerprint=sha256_json("candidate_less_generic_grammar_policy"),
            exact_source_occurrence_provider_fingerprint=(sealed.provider_fingerprint),
            exact_topic_term_hashes=partition.filter_term_hashes,
            exact_normalized_field=sealed.normalized_field,
            exact_predicate=sealed.predicate,
            exact_operator=sealed.operator,
            query_class_override="exact_set_or_inventory",
        )
        result = execute_deterministic_source_occurrence_inventory(
            plan=plan,
            provider=sealed,
            expected_authorized_scope_fingerprint=scope_fingerprint,
            page_size=20,
            cursor=None,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertFalse(result.coverage.authorized_scope_complete)
        self.assertEqual(
            result.source_occurrence_page["candidate_only_occurrence_count"],
            1,
        )

    def test_structured_filter_value_unions_columns_and_distinct_values_intersect(
        self,
    ) -> None:
        value_a = sha256_json("generic_value_a")
        value_b = sha256_json("generic_value_b")
        shared_projection = sha256_json("generic_shared_projection")
        other_projection = sha256_json("generic_other_projection")
        columns = tuple(
            exact_module.source_occurrence_column_capability_hash(name)
            for name in ("generic_column_a", "generic_column_b", "generic_column_c")
        )

        def occurrence(item: str, bindings):
            citation = sha256_json([item, "citation"])
            lineage = sha256_json([item, "lineage"])
            structured = tuple(
                (
                    column,
                    projection,
                    value,
                    "field",
                    "value",
                    citation,
                    lineage,
                )
                for column, projection, value in bindings
            )
            return AuthorizedSourceOccurrence(
                item_hash=sha256_json(item),
                value_bindings=tuple(
                    sorted(
                        {
                            (value, value, citation, lineage)
                            for _column, _projection, value in bindings
                        }
                        | {
                            (
                                projection,
                                exact_module.source_occurrence_projection_capability_hash(
                                    projection
                                ),
                                citation,
                                lineage,
                            )
                            for _column, projection, _value in bindings
                        }
                    )
                ),
                projection_bindings=(("field", "value", citation, lineage),),
                # This case tests native row filtering, not candidate admission.
                structure_status="source_provided",
                structured_column_bindings=structured,
            )

        provider = SourceOccurrenceProvider(
            provider_id="generic_multi_column_provider",
            inventory_kind_alias="generic_rows",
            resource_kind="generic_row_occurrence",
            normalized_field="generic.row.value",
            predicate="generic_row_contains",
            operator="case_insensitive_exact",
            requester_user_id=REQUESTER_USER_ID,
            workspace_id=WORKSPACE_ID,
            source_scope_ids=("generic_scope",),
            authorized_scope_fingerprint=sha256_json("generic_scope"),
            filter_slot_policy="combined_present_intersection_v1",
            occurrences=(
                occurrence("row_a", ((columns[0], shared_projection, value_a),)),
                occurrence(
                    "row_ab",
                    (
                        (columns[1], shared_projection, value_a),
                        (columns[2], other_projection, value_b),
                    ),
                ),
                occurrence("row_b", ((columns[2], other_projection, value_b),)),
            ),
        )
        term_a = sha256_json("generic_term_a")
        term_b = sha256_json("generic_term_b")
        public_partition = provider.partition_ordered_lexical_candidates(((term_a, (value_a,)),))
        private_partition, grammar = hybrid_module._partition_source_occurrence_query_grounding(
            provider=provider,
            ordered_terms=((term_a, "lexical", (value_a,)),),
        )
        self.assertEqual(private_partition, public_partition)
        self.assertEqual(grammar, ())
        self.assertEqual(public_partition.filter_term_hashes, (value_a,))
        self.assertEqual(len(public_partition.column_value_hash_pairs), 2)
        self.assertEqual(len(public_partition.lexical_term_ledger), 2)

        def execute(partition, provider=provider):
            plan = route_semantic_query(
                query_text="generic structured inventory",
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
                source_scope_ids=provider.source_scope_ids,
                effective_graph_view=self.inputs.effective_graph_view,
                exact_inventory_kind=provider.resource_kind,
                exact_filter_term_hashes=partition.filter_term_hashes,
                exact_projection_term_hashes=partition.projection_column_hashes,
                exact_column_value_hash_pairs=partition.column_value_hash_pairs,
                exact_lexical_term_ledger=partition.lexical_term_ledger,
                exact_grammar_policy_fingerprint=sha256_json("generic_grammar"),
                exact_source_occurrence_provider_fingerprint=provider.provider_fingerprint,
                exact_topic_term_hashes=partition.filter_term_hashes,
                exact_normalized_field=provider.normalized_field,
                exact_predicate=provider.predicate,
                exact_operator=provider.operator,
                query_class_override="exact_set_or_inventory",
            )
            return execute_deterministic_source_occurrence_inventory(
                plan=plan,
                provider=provider,
                expected_authorized_scope_fingerprint=provider.authorized_scope_fingerprint,
                page_size=20,
                cursor=None,
            )

        self.assertEqual(execute(public_partition).exact_count, 2)
        and_partition = provider.partition_ordered_lexical_candidates(
            ((term_a, (value_a,)), (term_b, (value_b,)))
        )
        self.assertEqual(execute(and_partition).exact_count, 1)
        candidate_provider = replace(provider, occurrences=tuple(
            replace(item, structure_status="candidate_only") for item in provider.occurrences
        ))
        candidate_result = execute(public_partition, provider=candidate_provider)
        self.assertEqual(candidate_result.exact_count, 0)
        self.assertEqual(candidate_result.returned_item_count, 0)
        self.assertEqual(candidate_result.status, "incomplete")
        self.assertFalse(candidate_result.coverage.authorized_scope_complete)
        self.assertEqual(candidate_result.source_occurrence_page["candidate_only_occurrence_count"], 3)
        self.assertEqual(candidate_result.source_occurrence_page["unresolved_count"], 0)
        with self.assertRaisesRegex(
            ContractValidationError,
            "column binding is ambiguous",
        ):
            provider.partition_ordered_lexical_candidates(
                ((sha256_json("projection_term"), (shared_projection,)),)
            )
        private_projection, _ = hybrid_module._partition_source_occurrence_query_grounding(
            provider=provider,
            ordered_terms=(
                (term_a, "lexical", (value_a,)),
                (
                    sha256_json("projection_term"),
                    "lexical",
                    (shared_projection,),
                ),
            ),
        )
        self.assertEqual(
            private_projection.projection_column_hashes,
            tuple(sorted(columns[:2])),
        )

    def test_ambiguous_projection_candidates_reach_normal_exact_execution(
        self,
    ) -> None:
        query_text = "alpha beta"
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components", return_value=self.runtime
        ):
            session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=(self.inputs.current_bundle,),
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )
        terms, _ = hybrid_module._ordered_source_occurrence_query_grounding(
            query_text, tokenizer_profile=self.runtime.tokenizer_profile
        )
        filter_candidate, projection_candidate = (term[2][0] for term in terms)
        columns = tuple(
            map(
                exact_module.source_occurrence_column_capability_hash,
                ("generic_filter", "generic_projection_0", "generic_projection_1", "generic_link"),
            )
        )
        observation_hashes = dict(session.authorized_observation_hashes)
        references = tuple(
            (observation_hashes[lineage.source_observation_id], lineage.lineage_fingerprint)
            for lineage in session.occurrence_lineages[:3]
        )
        shared_link = sha256_json("generic_shared_link")
        values = (
            sha256_json("generic_projection_value_0"),
            sha256_json("generic_projection_value_1"),
        )
        source_projected = (
            ("generic_filter", "filter", *references[0]),
            ("generic_link", "link", *references[1]),
        )
        target_projected = (
            ("generic_link", "link", *references[2]),
            ("generic_field_0", "value_0", *references[2]),
            ("generic_field_1", "value_1", *references[2]),
        )
        provider = SourceOccurrenceProvider(
            provider_id="generic_ambiguous_projection_provider_v1",
            inventory_kind_alias="generic_rows",
            resource_kind="generic_row_occurrence",
            normalized_field="generic.row.value",
            predicate="generic_row_contains",
            operator="case_insensitive_exact",
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_scope_fingerprint=authorized_source_occurrence_scope_fingerprint(
                requester_user_id=session.requester_user_id,
                workspace_id=session.workspace_id,
                source_scope_ids=session.authorized_source_scope_ids,
                authorized_observation_hashes=session.authorized_observation_hashes,
                source_session_binding_fingerprint=session.source_session_binding_fingerprint or "",
            ),
            filter_slot_policy="combined_present_intersection_v1",
            occurrences=(
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json("generic_filter_row"),
                    value_bindings=tuple(
                        sorted(
                            (
                                (filter_candidate, filter_candidate, *references[0]),
                                (shared_link, shared_link, *references[1]),
                            )
                        )
                    ),
                    projection_bindings=source_projected,
                    structure_status="candidate_only",
                    structured_column_bindings=(
                        (columns[0], sha256_json("filter"), filter_candidate, *source_projected[0]),
                        (columns[3], sha256_json("link"), shared_link, *source_projected[1]),
                    ),
                ),
                AuthorizedSourceOccurrence(
                    item_hash=sha256_json("generic_target_row"),
                    value_bindings=tuple(
                        sorted(
                            (
                                (shared_link, shared_link, *references[2]),
                                (values[0], values[0], *references[2]),
                                (values[1], values[1], *references[2]),
                                (
                                    projection_candidate,
                                    exact_module.source_occurrence_projection_capability_hash(
                                        projection_candidate
                                    ),
                                    *references[2],
                                ),
                            )
                        )
                    ),
                    projection_bindings=target_projected,
                    structure_status="candidate_only",
                    structured_column_bindings=(
                        (columns[3], sha256_json("link"), shared_link, *target_projected[0]),
                        (columns[1], projection_candidate, values[0], *target_projected[1]),
                        (columns[2], projection_candidate, values[1], *target_projected[2]),
                    ),
                ),
            ),
        )
        result = hybrid_module.attach_authorized_source_occurrence_providers(
            session, (provider,)
        ).query(
            query_text=query_text,
            effective_graph_view=self.inputs.effective_graph_view,
            exact_inventory_kind=provider.inventory_kind_alias,
        )
        exact_result = result.exact_result
        assert exact_result is not None
        self.assertEqual(result.status, "incomplete")
        self.assertEqual((exact_result.exact_count, exact_result.returned_item_count), (0, 1))
        self.assertFalse(exact_result.coverage.authorized_scope_complete)
        self.assertEqual(exact_result.source_occurrence_page["candidate_only_occurrence_count"], 2)
        self.assertEqual(exact_result.source_occurrence_page["unresolved_count"], 0)
        item = exact_result.items[0]
        self.assertEqual(item.structure_status, "candidate_only")
        self.assertEqual(len(item.structured_values), 2)
        self.assertEqual(set(item.governed_references), set(references))

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
