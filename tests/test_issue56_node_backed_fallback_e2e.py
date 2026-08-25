from __future__ import annotations

from dataclasses import dataclass, replace
import math
import unittest
from unittest.mock import patch
from typing import Any, Sequence

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_core import (
    Issue56TargetRuntimeComponents,
    SentenceTransformerDenseEncoder,
    build_issue56_execution_component_binding,
    issue56_target_dense_embedding_profile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_graph.index import GraphProjectionEdge, GraphProjectionNode
from formowl_mail import (
    DEFAULT_SEMANTIC_PLAN_LIMITS,
    SemanticPlanLimits,
    build_authorized_semantic_mail_session,
    render_governed_evidence_answer,
    run_authorized_semantic_mail_query,
)
from formowl_mail import hybrid as hybrid_module
from scripts.issue56_semantic_execution_smoke import (
    ALLOWED_RELATIONS,
    REQUESTER_USER_ID,
    WORKSPACE_ID,
    build_semantic_poc_inputs,
)


class Issue56NodeBackedFallbackEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = _contract_only_runtime()
        cls.inputs = build_semantic_poc_inputs()
        cls.authorized_hashes = frozenset(
            sha256_json(observation.to_dict())
            for bundle_id, observations in cls.inputs.observations_by_bundle_id.items()
            if bundle_id != cls.inputs.denied_bundle.mail_evidence_bundle_id
            for observation in observations
        )

    def test_authorized_node_backed_identifier_binds_and_answers_with_citations(
        self,
    ) -> None:
        view = _view_with_node_terms(
            self.inputs.effective_graph_view,
            (
                "node_issue56_po_current",
                "protected_term_hashes",
                "PO470002004",
                ("obs_issue56_semantic_current_body_3",),
            ),
            (
                "node_issue56_origin",
                "protected_term_hashes",
                "ORIGIN-TAIWAN-01",
                ("obs_issue56_semantic_current_body_2",),
            ),
            (
                "node_issue56_supplier",
                "source_term_hashes",
                "供應商",
                ("obs_issue56_semantic_current_body_1",),
            ),
        )
        self._assert_observation_supports_term(
            observation_id="obs_issue56_semantic_current_body_3",
            term="PO470002004",
            protected=True,
        )

        with (
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                wraps=hybrid_module._bounded_graph_traversal,
            ) as traversal,
            patch.object(
                hybrid_module,
                "_semantic_evidence_scores",
                wraps=hybrid_module._semantic_evidence_scores,
            ) as scoring,
        ):
            result = self._run(
                query_text=("PO470002004 與 ORIGIN-TAIWAN-01 的供應商資訊關係"),
                effective_graph_view=view,
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_attempt_count, 1)
        self.assertIn("bounded_relation_fallback_repair_succeeded", result.warnings)
        self.assertNotIn(
            "bounded_relation_targeted_retraversal_attempted",
            result.warnings,
        )
        self.assertEqual(traversal.call_count, 1)
        self.assertEqual(scoring.call_count, 1)
        self.assertIn(
            self.inputs.ontology_only_observation_hash,
            result.answer_citation_hashes,
        )
        self._assert_exact_minimal_node_backed_citations(
            result,
            supporting_observation_hashes=(self.inputs.ontology_only_observation_hash,),
        )
        self._assert_cited_answer_and_hop_lineage(result)
        rerun = self._run(
            query_text=("PO470002004 與 ORIGIN-TAIWAN-01 的供應商資訊關係"),
            effective_graph_view=view,
        )
        self.assertEqual(
            rerun.answer_citation_hashes,
            result.answer_citation_hashes,
        )
        self.assertEqual(rerun.result_fingerprint, result.result_fingerprint)

    def test_authorized_node_backed_concept_binds_without_second_scoring(
        self,
    ) -> None:
        view = _view_with_node_terms(
            self.inputs.effective_graph_view,
            (
                "node_issue56_supplier",
                "source_term_hashes",
                "交期",
                ("obs_issue56_semantic_current_body_3",),
            ),
            (
                "node_issue56_po_current",
                "protected_term_hashes",
                "PO470002002",
                ("obs_issue56_semantic_current_body_1",),
            ),
            (
                "node_issue56_origin",
                "protected_term_hashes",
                "ORIGIN-TAIWAN-01",
                ("obs_issue56_semantic_current_body_2",),
            ),
        )
        self._assert_observation_supports_term(
            observation_id="obs_issue56_semantic_current_body_3",
            term="交期",
            protected=False,
        )

        with (
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                wraps=hybrid_module._bounded_graph_traversal,
            ) as traversal,
            patch.object(
                hybrid_module,
                "_semantic_evidence_scores",
                wraps=hybrid_module._semantic_evidence_scores,
            ) as scoring,
        ):
            result = self._run(
                query_text="PO470002002 與 ORIGIN-TAIWAN-01 的交期關係",
                effective_graph_view=view,
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_attempt_count, 1)
        self.assertIn("bounded_relation_fallback_repair_succeeded", result.warnings)
        self.assertNotIn(
            "bounded_relation_targeted_retraversal_attempted",
            result.warnings,
        )
        self.assertEqual(traversal.call_count, 1)
        self.assertEqual(scoring.call_count, 1)
        self.assertIn(
            self.inputs.ontology_only_observation_hash,
            result.answer_citation_hashes,
        )
        self._assert_exact_minimal_node_backed_citations(
            result,
            supporting_observation_hashes=(self.inputs.ontology_only_observation_hash,),
        )
        self._assert_cited_answer_and_hop_lineage(result)
        rerun = self._run(
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的交期關係",
            effective_graph_view=view,
        )
        self.assertEqual(
            rerun.answer_citation_hashes,
            result.answer_citation_hashes,
        )
        self.assertEqual(rerun.result_fingerprint, result.result_fingerprint)

    def test_node_term_requires_node_hash_and_authorized_observation_support(
        self,
    ) -> None:
        cases = (
            {
                "namespace": "identifier",
                "node_id": "node_issue56_po_current",
                "term": "PO470002004",
                "query_text": ("PO470002004 與 ORIGIN-TAIWAN-01 的供應商資訊關係"),
                "protected": True,
            },
            {
                "namespace": "concept",
                "node_id": "node_issue56_supplier",
                "term": "交期",
                "query_text": "PO470002002 與 ORIGIN-TAIWAN-01 的交期關係",
                "protected": False,
            },
        )
        for case in cases:
            with self.subTest(namespace=case["namespace"]):
                self._assert_observation_supports_term(
                    observation_id="obs_issue56_semantic_current_body_3",
                    term=case["term"],
                    protected=case["protected"],
                )
                view = (
                    _view_with_node_terms(
                        self.inputs.effective_graph_view,
                        (
                            "node_issue56_origin",
                            "protected_term_hashes",
                            "ORIGIN-TAIWAN-01",
                            ("obs_issue56_semantic_current_body_2",),
                        ),
                        (
                            "node_issue56_supplier",
                            "source_term_hashes",
                            "供應商",
                            ("obs_issue56_semantic_current_body_1",),
                        ),
                    )
                    if case["namespace"] == "identifier"
                    else _view_with_node_terms(
                        self.inputs.effective_graph_view,
                        (
                            "node_issue56_po_current",
                            "protected_term_hashes",
                            "PO470002002",
                            ("obs_issue56_semantic_current_body_1",),
                        ),
                        (
                            "node_issue56_origin",
                            "protected_term_hashes",
                            "ORIGIN-TAIWAN-01",
                            ("obs_issue56_semantic_current_body_2",),
                        ),
                    )
                )
                view = _view_with_observation_lineage_without_node_term(
                    view,
                    node_id=case["node_id"],
                    term=case["term"],
                    supporting_observation_id=("obs_issue56_semantic_current_body_3"),
                )
                selected_node = next(
                    node for node in view.visible_nodes if node.node_id == case["node_id"]
                )
                term_hash = sha256_json(
                    case["term"].casefold() if case["protected"] else case["term"]
                )
                self.assertNotIn(
                    term_hash,
                    hybrid_module._node_protected_term_hashes(selected_node),
                )
                self.assertNotIn(
                    term_hash,
                    hybrid_module._node_source_term_hashes(selected_node),
                )

                result = self._run(
                    query_text=case["query_text"],
                    effective_graph_view=view,
                )

                self.assertEqual(result.status, "no_answer")
                self.assertEqual(result.answer_citation_hashes, ())
                self.assertIn(
                    "bounded_relation_fallback_repair_exhausted",
                    result.warnings,
                )

    def test_authorized_but_term_mismatched_node_lineage_fails_closed(self) -> None:
        cases = (
            {
                "namespace": "identifier",
                "node_id": "node_issue56_po_current",
                "property_name": "protected_term_hashes",
                "term": "PO470002004",
                "query_text": ("PO470002004 與 ORIGIN-TAIWAN-01 的供應商資訊關係"),
                "protected": True,
            },
            {
                "namespace": "concept",
                "node_id": "node_issue56_supplier",
                "property_name": "source_term_hashes",
                "term": "交期",
                "query_text": "PO470002002 與 ORIGIN-TAIWAN-01 的交期關係",
                "protected": False,
            },
        )
        for case in cases:
            with self.subTest(namespace=case["namespace"]):
                self.assertFalse(
                    self._observation_supports_term(
                        observation_id="obs_issue56_semantic_current_body_1",
                        term=case["term"],
                        protected=case["protected"],
                    )
                )
                view = (
                    _view_with_node_terms(
                        self.inputs.effective_graph_view,
                        (
                            "node_issue56_origin",
                            "protected_term_hashes",
                            "ORIGIN-TAIWAN-01",
                            ("obs_issue56_semantic_current_body_2",),
                        ),
                        (
                            "node_issue56_supplier",
                            "source_term_hashes",
                            "供應商",
                            ("obs_issue56_semantic_current_body_1",),
                        ),
                    )
                    if case["namespace"] == "identifier"
                    else _view_with_node_terms(
                        self.inputs.effective_graph_view,
                        (
                            "node_issue56_po_current",
                            "protected_term_hashes",
                            "PO470002002",
                            ("obs_issue56_semantic_current_body_1",),
                        ),
                        (
                            "node_issue56_origin",
                            "protected_term_hashes",
                            "ORIGIN-TAIWAN-01",
                            ("obs_issue56_semantic_current_body_2",),
                        ),
                    )
                )
                view = _view_with_node_term(
                    view,
                    node_id=case["node_id"],
                    property_name=case["property_name"],
                    term=case["term"],
                )
                selected_node = next(
                    node for node in view.visible_nodes if node.node_id == case["node_id"]
                )
                term_hash = sha256_json(
                    case["term"].casefold() if case["protected"] else case["term"]
                )
                node_term_hashes = (
                    hybrid_module._node_protected_term_hashes(selected_node)
                    if case["protected"]
                    else hybrid_module._node_source_term_hashes(selected_node)
                )
                self.assertIn(term_hash, node_term_hashes)

                result = self._run(
                    query_text=case["query_text"],
                    effective_graph_view=view,
                )

                self.assertEqual(result.status, "no_answer")
                self.assertEqual(result.answer_citation_hashes, ())
                self.assertIn(
                    "bounded_relation_fallback_repair_exhausted",
                    result.warnings,
                )

    def test_denied_and_unsupported_nodes_do_not_supply_slot_coverage(self) -> None:
        denied_observation_id = "obs_issue56_semantic_denied_body_1"
        cases = (
            ("denied", denied_observation_id),
            ("unsupported", "obs_issue56_node_backed_missing"),
        )
        for namespace, source_observation_id in cases:
            with self.subTest(namespace=namespace):
                view = _view_with_unusable_node(
                    self.inputs.effective_graph_view,
                    namespace=namespace,
                    source_observation_id=source_observation_id,
                )
                result = self._run(
                    query_text="2026-10-01 與 ORIGIN-TAIWAN-01 的交期關係",
                    effective_graph_view=view,
                )

                self.assertEqual(result.status, "no_answer")
                self.assertEqual(result.answer_citation_hashes, ())
                self.assertIn(
                    "bounded_relation_fallback_repair_exhausted",
                    result.warnings,
                )
                self.assertTrue(
                    all(
                        set(path.cited_observation_hashes) <= self.authorized_hashes
                        for path in result.graph_paths
                    )
                )

    def test_strict_default_path_does_not_invoke_fallback_or_repeat_work(self) -> None:
        projection_builder = self._required_projection_builder()
        with (
            patch.object(
                hybrid_module,
                "_build_relation_query_projection",
                wraps=projection_builder,
            ) as projection,
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                wraps=hybrid_module._bounded_graph_traversal,
            ) as traversal,
            patch.object(
                hybrid_module,
                "_semantic_evidence_scores",
                wraps=hybrid_module._semantic_evidence_scores,
            ) as scoring,
            patch.object(
                hybrid_module,
                "_execute_bounded_relation_fallback",
                wraps=hybrid_module._execute_bounded_relation_fallback,
            ) as fallback,
        ):
            result = self._run(
                query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_attempt_count, 0)
        self.assertEqual(projection.call_count, 1)
        self.assertEqual(traversal.call_count, 1)
        self.assertEqual(scoring.call_count, 1)
        fallback.assert_not_called()
        self.assertFalse(any("fallback_repair" in warning for warning in result.warnings))
        self._assert_cited_answer_and_hop_lineage(result)

    def test_empty_initial_paths_allow_one_bounded_targeted_retraversal(self) -> None:
        safe_view = _view_with_node_terms(
            self.inputs.effective_graph_view,
            (
                "node_issue56_po_current",
                "protected_term_hashes",
                "PO470002002",
                ("obs_issue56_semantic_current_body_1",),
            ),
            (
                "node_issue56_origin",
                "protected_term_hashes",
                "ORIGIN-TAIWAN-01",
                ("obs_issue56_semantic_current_body_2",),
            ),
            (
                "node_issue56_supplier",
                "source_term_hashes",
                "供應商",
                ("obs_issue56_semantic_current_body_1",),
            ),
        )
        traversal_path_counts: list[int] = []
        real_traversal = hybrid_module._bounded_graph_traversal

        def recording_traversal(**kwargs):
            if not traversal_path_counts:
                traversal_path_counts.append(0)
                return (), 0
            paths, rejected = real_traversal(**kwargs)
            traversal_path_counts.append(len(paths))
            return paths, rejected

        with (
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                side_effect=recording_traversal,
            ) as traversal,
            patch.object(
                hybrid_module,
                "_semantic_evidence_scores",
                wraps=hybrid_module._semantic_evidence_scores,
            ) as scoring,
        ):
            result = self._run(
                query_text=("PO470002002 與 ORIGIN-TAIWAN-01 的供應商資訊關係"),
                effective_graph_view=safe_view,
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_attempt_count, 1)
        self.assertEqual(traversal.call_count, 2)
        self.assertEqual(traversal_path_counts[0], 0)
        self.assertGreater(traversal_path_counts[1], 0)
        self.assertEqual(scoring.call_count, 2)
        self.assertIn(
            "bounded_relation_targeted_retraversal_attempted",
            result.warnings,
        )
        self.assertEqual(
            result.warnings.count("bounded_relation_targeted_retraversal_attempted"), 1
        )
        self._assert_cited_answer_and_hop_lineage(result)

    def test_protected_query_can_complete_from_one_lineaged_concept_anchor(
        self,
    ) -> None:
        concept_node_id = "node_issue56_concept_completion_anchor"
        po_node_id = "node_issue56_concept_completion_po"
        origin_node_id = "node_issue56_concept_completion_origin"
        concept_observation_id = "obs_issue56_semantic_current_body_1"
        po_observation_id = "obs_issue56_semantic_current_body_3"
        origin_observation_id = "obs_issue56_semantic_current_body_2"
        view = replace(
            self.inputs.effective_graph_view,
            user_graph_revision_id="ugraph_issue56_concept_completion",
            canonical_graph_revision_id="cgraph_issue56_concept_completion",
            ontology_revision_id="ontology_issue56_concept_completion",
            assembly_policy_id="assembly_issue56_concept_completion",
            visible_nodes=[
                _proof_node(
                    concept_node_id,
                    source_observation_id=concept_observation_id,
                    labels=("authorized concept anchor",),
                    source_terms=("供應商",),
                    node_kind="candidate_entity",
                ),
                _proof_node(
                    po_node_id,
                    source_observation_id=po_observation_id,
                    labels=("non-seedable identifier support",),
                    protected_terms=("PO470002004",),
                    node_kind="canonical_entity",
                ),
                _proof_node(
                    origin_node_id,
                    source_observation_id=origin_observation_id,
                    labels=("non-seedable origin support",),
                    protected_terms=("ORIGIN-TAIWAN-01",),
                    node_kind="canonical_entity",
                ),
            ],
            visible_edges=[
                _proof_edge(
                    "edge_issue56_concept_completion_po",
                    source_node_id=concept_node_id,
                    target_node_id=po_node_id,
                    source_observation_id=concept_observation_id,
                ),
                _proof_edge(
                    "edge_issue56_concept_completion_origin",
                    source_node_id=po_node_id,
                    target_node_id=origin_node_id,
                    source_observation_id=origin_observation_id,
                ),
            ],
        )
        traversal_calls: list[dict[str, Any]] = []
        real_traversal = hybrid_module._bounded_graph_traversal

        def recording_traversal(**kwargs):
            traversal_calls.append(kwargs)
            return real_traversal(**kwargs)

        with patch.object(
            hybrid_module,
            "_bounded_graph_traversal",
            side_effect=recording_traversal,
        ):
            result = self._run(
                query_text=("PO470002004 與 ORIGIN-TAIWAN-01 的供應商資訊關係"),
                effective_graph_view=view,
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_attempt_count, 1)
        self.assertEqual(len(traversal_calls), 2)
        projection = traversal_calls[0]["relation_projection"]
        self.assertIsNotNone(projection)
        self.assertEqual(projection.initial_query_anchor_node_ids, ())
        self.assertEqual(
            projection.completion_query_anchor_node_ids,
            (concept_node_id,),
        )
        self.assertIsNone(traversal_calls[0].get("relation_proof_slots"))
        self.assertIsNotNone(traversal_calls[1]["relation_proof_slots"])
        self.assertEqual(
            traversal_calls[1]["plan"].seed_node_ids,
            (concept_node_id,),
        )
        self.assertEqual(
            result.warnings.count("bounded_relation_targeted_retraversal_attempted"),
            1,
        )
        selected_paths = [
            path
            for path in result.graph_paths
            if _path_node_hashes(path)
            == frozenset(
                sha256_json(node_id)
                for node_id in (
                    concept_node_id,
                    po_node_id,
                    origin_node_id,
                )
            )
        ]
        self.assertEqual(len(selected_paths), 1)
        selected_path = selected_paths[0]
        self.assertEqual(selected_path.hop_count, 2)
        self._assert_exact_minimal_path_and_support_citations(
            result,
            selected_path=selected_path,
            supporting_observation_hashes=(self._observation_hash(po_observation_id),),
        )
        self._assert_cited_answer_and_hop_lineage(result)

    def test_ten_incomplete_paths_complete_once_from_connected_off_path_support(
        self,
    ) -> None:
        fixture = _connected_off_path_support_fixture(
            self.inputs.effective_graph_view,
            branch_count=10,
        )
        initial_paths: list[Any] = []
        real_fallback = hybrid_module._execute_bounded_relation_fallback

        def recording_fallback(**kwargs):
            initial_paths.extend(kwargs["graph_paths"])
            return real_fallback(**kwargs)

        with (
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                wraps=hybrid_module._bounded_graph_traversal,
            ) as traversal,
            patch.object(
                hybrid_module,
                "_execute_bounded_relation_fallback",
                side_effect=recording_fallback,
            ) as fallback,
        ):
            result = self._run(
                query_text=fixture.query_text,
                effective_graph_view=fixture.view,
                seed_node_ids=(fixture.anchor_node_id,),
            )

        self.assertEqual(len(initial_paths), 10)
        self.assertTrue(
            all(
                not fixture.support_node_hashes.issubset(_path_node_hashes(path))
                for path in initial_paths
            )
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_attempt_count, 1)
        self.assertEqual(fallback.call_count, 1)
        self.assertEqual(traversal.call_count, 2)
        self.assertEqual(
            result.warnings.count("bounded_relation_targeted_retraversal_attempted"),
            1,
        )
        selected_paths = [
            path
            for path in result.graph_paths
            if fixture.support_node_hashes.issubset(_path_node_hashes(path))
        ]
        self.assertEqual(len(selected_paths), 1)
        selected_path = selected_paths[0]
        self.assertEqual(selected_path.hop_count, 2)
        self._assert_exact_minimal_path_and_support_citations(
            result,
            selected_path=selected_path,
            supporting_observation_hashes=fixture.supporting_observation_hashes,
        )
        self._assert_cited_answer_and_hop_lineage(result)

    def test_support_beyond_max_hops_fails_closed_without_repair_loop(self) -> None:
        fixture = _connected_off_path_support_fixture(
            self.inputs.effective_graph_view,
            support_depth=3,
        )
        with (
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                wraps=hybrid_module._bounded_graph_traversal,
            ) as traversal,
            patch.object(
                hybrid_module,
                "_execute_bounded_relation_fallback",
                wraps=hybrid_module._execute_bounded_relation_fallback,
            ) as fallback,
        ):
            result = self._run(
                query_text=fixture.query_text,
                effective_graph_view=fixture.view,
                seed_node_ids=(fixture.anchor_node_id,),
            )

        self.assertEqual(result.status, "no_answer")
        self.assertEqual(result.answer_citation_hashes, ())
        self.assertEqual(result.repair_attempt_count, 1)
        self.assertEqual(fallback.call_count, 1)
        self.assertLessEqual(traversal.call_count, 2)
        self.assertLessEqual(
            result.warnings.count("bounded_relation_targeted_retraversal_attempted"),
            1,
        )
        self.assertIn("bounded_relation_fallback_repair_exhausted", result.warnings)

    def test_projection_builds_once_and_term_proof_work_does_not_scale_with_paths(
        self,
    ) -> None:
        fixture = _connected_off_path_support_fixture(
            self.inputs.effective_graph_view,
        )
        projection_builder = self._required_projection_builder()
        graph_fingerprint = hybrid_module._graph_revision_fingerprint
        graph_snapshot_builder = hybrid_module._build_query_graph_snapshot
        crosswalk_builder = hybrid_module.build_evidence_identity_lineage_crosswalk
        traversal_runner = hybrid_module._bounded_graph_traversal
        graph_snapshots: list[Any] = []
        crosswalk_snapshots: list[Any] = []
        projection_snapshots: list[Any] = []
        traversal_adjacencies: list[Any] = []

        def recording_graph_snapshot(effective_graph_view):
            snapshot = graph_snapshot_builder(effective_graph_view)
            graph_snapshots.append(snapshot)
            return snapshot

        def recording_crosswalk(**kwargs):
            crosswalk_snapshots.append(kwargs["graph_snapshot"])
            return crosswalk_builder(**kwargs)

        def recording_projection(**kwargs):
            projection_snapshots.append(kwargs["graph_snapshot"])
            return projection_builder(**kwargs)

        def recording_traversal(**kwargs):
            projection = kwargs["relation_projection"]
            self.assertIsNotNone(projection)
            traversal_adjacencies.append(projection.adjacency)
            return traversal_runner(**kwargs)

        with (
            patch.object(
                hybrid_module,
                "_graph_revision_fingerprint",
                wraps=graph_fingerprint,
            ) as full_view_fingerprint,
            patch.object(
                hybrid_module,
                "_build_query_graph_snapshot",
                side_effect=recording_graph_snapshot,
            ) as build_graph_snapshot,
            patch.object(
                hybrid_module,
                "build_evidence_identity_lineage_crosswalk",
                side_effect=recording_crosswalk,
            ) as build_crosswalk,
            patch.object(
                hybrid_module,
                "_build_relation_query_projection",
                side_effect=recording_projection,
            ) as projection,
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                side_effect=recording_traversal,
            ) as traversal,
            patch.object(
                hybrid_module,
                "_graph_adjacency",
                wraps=hybrid_module._graph_adjacency,
            ) as legacy_adjacency,
        ):
            ten_path_result, ten_path_counts = self._run_with_term_proof_counts(
                fixture=fixture,
                max_results=10,
            )
        self.assertEqual(full_view_fingerprint.call_count, 1)
        self.assertEqual(build_graph_snapshot.call_count, 1)
        self.assertEqual(build_crosswalk.call_count, 1)
        self.assertEqual(projection.call_count, 1)
        self.assertEqual(traversal.call_count, 2)
        self.assertEqual(len(graph_snapshots), 1)
        self.assertEqual(crosswalk_snapshots, graph_snapshots)
        self.assertEqual(projection_snapshots, graph_snapshots)
        self.assertEqual(len(traversal_adjacencies), 2)
        self.assertIs(traversal_adjacencies[0], traversal_adjacencies[1])
        self.assertEqual(legacy_adjacency.call_count, 0)
        self._assert_frozen_projection_fixture_result(ten_path_result)

        with patch.object(
            hybrid_module,
            "_build_relation_query_projection",
            wraps=projection_builder,
        ) as projection:
            one_path_result, one_path_counts = self._run_with_term_proof_counts(
                fixture=fixture,
                max_results=1,
            )
        self.assertEqual(projection.call_count, 1)

        self.assertEqual(ten_path_result.status, "ok")
        self.assertEqual(one_path_result.status, "ok")
        self.assertEqual(ten_path_counts, one_path_counts)

    def test_identical_queries_do_not_share_projection_but_are_deterministic(
        self,
    ) -> None:
        fixture = _connected_off_path_support_fixture(
            self.inputs.effective_graph_view,
        )
        projection_builder = self._required_projection_builder()
        graph_fingerprint = hybrid_module._graph_revision_fingerprint
        graph_snapshot_builder = hybrid_module._build_query_graph_snapshot
        projections: list[Any] = []
        graph_snapshots: list[Any] = []

        def recording_projection(*args, **kwargs):
            projection = projection_builder(*args, **kwargs)
            projections.append(projection)
            return projection

        def recording_graph_snapshot(effective_graph_view):
            snapshot = graph_snapshot_builder(effective_graph_view)
            graph_snapshots.append(snapshot)
            return snapshot

        with (
            patch.object(
                hybrid_module,
                "_graph_revision_fingerprint",
                wraps=graph_fingerprint,
            ) as full_view_fingerprint,
            patch.object(
                hybrid_module,
                "_build_query_graph_snapshot",
                side_effect=recording_graph_snapshot,
            ) as build_graph_snapshot,
            patch.object(
                hybrid_module,
                "_build_relation_query_projection",
                side_effect=recording_projection,
            ) as build_projection,
        ):
            first = self._run(
                query_text=fixture.query_text,
                effective_graph_view=fixture.view,
                seed_node_ids=(fixture.anchor_node_id,),
            )
            second = self._run(
                query_text=fixture.query_text,
                effective_graph_view=fixture.view,
                seed_node_ids=(fixture.anchor_node_id,),
            )

        self.assertEqual(full_view_fingerprint.call_count, 2)
        self.assertEqual(build_graph_snapshot.call_count, 2)
        self.assertEqual(build_projection.call_count, 2)
        self.assertEqual(len(graph_snapshots), 2)
        self.assertIsNot(graph_snapshots[0], graph_snapshots[1])
        self.assertEqual(
            graph_snapshots[0].graph_revision_fingerprint,
            graph_snapshots[1].graph_revision_fingerprint,
        )
        self.assertEqual(len(projections), 2)
        self.assertIsNot(projections[0], projections[1])
        self.assertIsNot(projections[0].adjacency, projections[1].adjacency)
        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "ok")
        self.assertEqual(first.plan_fingerprint, second.plan_fingerprint)
        self.assertEqual(first.graph_paths, second.graph_paths)
        self.assertEqual(first.scores, second.scores)
        self.assertEqual(first.answer_citation_hashes, second.answer_citation_hashes)
        self.assertEqual(first.result_fingerprint, second.result_fingerprint)

    def test_requester_revision_and_index_binding_mismatches_fail_closed(self) -> None:
        fixture = _connected_off_path_support_fixture(
            self.inputs.effective_graph_view,
        )
        requester_mismatch = replace(
            fixture.view,
            requester_user_id="user_issue56_other",
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "requester",
        ):
            self._run(
                query_text=fixture.query_text,
                effective_graph_view=requester_mismatch,
                seed_node_ids=(fixture.anchor_node_id,),
            )

        real_router = hybrid_module.route_semantic_query

        def revision_mismatched_router(**kwargs):
            plan = real_router(**kwargs)
            return replace(
                plan,
                user_graph_revision_id="ugraph_issue56_mismatched",
            )

        with (
            patch.object(
                hybrid_module,
                "route_semantic_query",
                side_effect=revision_mismatched_router,
            ),
            self.assertRaisesRegex(
                ContractValidationError,
                "revision.*mismatch",
            ),
        ):
            self._run(
                query_text=fixture.query_text,
                effective_graph_view=fixture.view,
                seed_node_ids=(fixture.anchor_node_id,),
            )

        session = self._build_session()
        mismatched_index = replace(
            session.index,
            index_fingerprint=sha256_json("issue56-mismatched-index"),
        )
        mismatched_session = replace(session, index=mismatched_index)
        with (
            patch(
                "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
                return_value=self.runtime,
            ),
            self.assertRaisesRegex(
                ContractValidationError,
                "index.*mismatch",
            ),
        ):
            mismatched_session.query(
                query_text=fixture.query_text,
                effective_graph_view=fixture.view,
                allowed_relation_types=ALLOWED_RELATIONS,
                seed_node_ids=(fixture.anchor_node_id,),
            )

    def test_graph_content_and_grants_bind_projection_and_adjacency_per_view(
        self,
    ) -> None:
        fixture = _connected_off_path_support_fixture(
            self.inputs.effective_graph_view,
        )
        cases = (
            (
                "edge_content",
                _view_with_binding_revision(
                    fixture.view,
                    suffix="edge_content",
                    applied_grant_ids=("grant_issue56_binding_base",),
                ),
                _view_with_changed_authorized_edge_evidence(
                    _view_with_binding_revision(
                        fixture.view,
                        suffix="edge_content",
                        applied_grant_ids=("grant_issue56_binding_base",),
                    ),
                    edge_id="edge_issue56_completion_branch_00",
                    source_observation_id=("obs_issue56_semantic_current_body_2"),
                ),
            ),
            (
                "applied_grants",
                _view_with_binding_revision(
                    fixture.view,
                    suffix="applied_grants",
                    applied_grant_ids=("grant_issue56_binding_base",),
                ),
                _view_with_binding_revision(
                    fixture.view,
                    suffix="applied_grants",
                    applied_grant_ids=("grant_issue56_binding_changed",),
                ),
            ),
        )
        projection_builder = self._required_projection_builder()
        for namespace, first_view, second_view in cases:
            with self.subTest(namespace=namespace):
                self.assertEqual(
                    first_view.requester_user_id,
                    second_view.requester_user_id,
                )
                self.assertEqual(
                    first_view.user_graph_revision_id,
                    second_view.user_graph_revision_id,
                )
                self.assertEqual(
                    first_view.canonical_graph_revision_id,
                    second_view.canonical_graph_revision_id,
                )
                self.assertEqual(
                    first_view.ontology_revision_id,
                    second_view.ontology_revision_id,
                )
                self.assertEqual(
                    len(first_view.visible_nodes),
                    len(second_view.visible_nodes),
                )
                self.assertEqual(
                    len(first_view.visible_edges),
                    len(second_view.visible_edges),
                )

                projections: list[Any] = []
                crosswalk_cache: dict[Any, Any] = {}

                def recording_projection(*args, **kwargs):
                    projection = projection_builder(*args, **kwargs)
                    projections.append(projection)
                    return projection

                with (
                    patch.object(
                        hybrid_module,
                        "_EVIDENCE_LINEAGE_CROSSWALK_CACHE",
                        crosswalk_cache,
                    ),
                    patch.object(
                        hybrid_module,
                        "_graph_revision_fingerprint",
                        wraps=hybrid_module._graph_revision_fingerprint,
                    ) as full_view_fingerprint,
                    patch.object(
                        hybrid_module,
                        "_build_relation_query_projection",
                        side_effect=recording_projection,
                    ),
                ):
                    first = self._run(
                        query_text=fixture.query_text,
                        effective_graph_view=first_view,
                        seed_node_ids=(fixture.anchor_node_id,),
                    )
                    second = self._run(
                        query_text=fixture.query_text,
                        effective_graph_view=second_view,
                        seed_node_ids=(fixture.anchor_node_id,),
                    )

                self.assertEqual(full_view_fingerprint.call_count, 2)
                self.assertEqual(first.status, "ok")
                self.assertEqual(second.status, "ok")
                self.assertEqual(len(projections), 2)
                self.assertIsNot(projections[0], projections[1])
                self.assertIsNot(
                    projections[0].adjacency,
                    projections[1].adjacency,
                )
                self.assertNotEqual(
                    first.graph_revision_fingerprint,
                    second.graph_revision_fingerprint,
                )
                self.assertNotEqual(
                    projections[0].binding_fingerprint,
                    projections[1].binding_fingerprint,
                )
                self.assertEqual(len(crosswalk_cache), 2)
                self.assertEqual(
                    {key[1] for key in crosswalk_cache},
                    {
                        first.graph_revision_fingerprint,
                        second.graph_revision_fingerprint,
                    },
                )
                if namespace == "edge_content":
                    self.assertNotEqual(
                        projections[0].adjacency,
                        projections[1].adjacency,
                    )

                with (
                    patch.object(
                        hybrid_module,
                        "_build_relation_query_projection",
                        return_value=projections[0],
                    ),
                    self.assertRaisesRegex(
                        ContractValidationError,
                        "relation projection binding mismatch",
                    ),
                ):
                    self._run(
                        query_text=fixture.query_text,
                        effective_graph_view=second_view,
                        seed_node_ids=(fixture.anchor_node_id,),
                    )

    def _assert_frozen_projection_fixture_result(self, result) -> None:
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_attempt_count, 1)
        self.assertEqual(
            result.plan_fingerprint,
            "sha256:34e4234eaab159b46135aaf89ea6dfddf432c96b879fe4404d15d7bb04de4e6e",
        )
        self.assertEqual(
            result.graph_revision_fingerprint,
            "sha256:fd8594efd6c321f024c4acb78bd6096e4c41e1e472bae43bf193544af711056e",
        )
        self.assertEqual(
            result.result_fingerprint,
            "sha256:04b54caa19e9c91b744d6433357db5b1dc081122a141b46aa504d0bb96c0bc21",
        )
        self.assertEqual(
            sha256_json([path.to_safe_dict() for path in result.graph_paths]),
            "sha256:f5589f637e7a32f48a9243b7e4640dbb341460b043fda425ffb2e0b2654305c4",
        )
        self.assertEqual(
            sha256_json([score.to_safe_dict() for score in result.scores]),
            "sha256:150d0208927d24ca2de5cba6166325d99a753d09e4a27b0500c537ef79f10854",
        )
        self.assertEqual(
            result.answer_citation_hashes,
            (
                "sha256:5d7c0a1980c687d4ee83947379a5b01a23ca412854847d892f594caefb30a3bd",
                "sha256:8031afa3e6ce3246144c0207623b5e76a90d33c9c36fdc4943793c675ee6e806",
                "sha256:eb85db3f0bf7d164a3a341485a9ccf37d1f941c52c41696f525dd58210388425",
            ),
        )
        self.assertEqual(
            sha256_json(list(result.answer_citation_hashes)),
            "sha256:84a8bfbc257e698e477fde091aaa9717550612549d25b6f75af0c13995e7192d",
        )

    def _run(
        self,
        *,
        query_text: str,
        effective_graph_view=None,
        seed_node_ids: Sequence[str] = (),
        limits: SemanticPlanLimits = DEFAULT_SEMANTIC_PLAN_LIMITS,
    ):
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            return run_authorized_semantic_mail_query(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=self.inputs.bundles,
                query_text=query_text,
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
                effective_graph_view=(effective_graph_view or self.inputs.effective_graph_view),
                allowed_relation_types=ALLOWED_RELATIONS,
                seed_node_ids=seed_node_ids,
                limits=limits,
            )

    def _build_session(self):
        with patch(
            "formowl_mail.hybrid._load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            return build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=self.inputs.bundles,
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
            )

    def _required_projection_builder(self):
        builder = getattr(
            hybrid_module,
            "_build_relation_query_projection",
            None,
        )
        self.assertTrue(
            callable(builder),
            "runtime must expose one per-query immutable relation projection builder",
        )
        return builder

    def _run_with_term_proof_counts(
        self,
        *,
        fixture,
        max_results: int,
    ):
        with (
            patch.object(
                hybrid_module,
                "_node_source_term_hashes",
                wraps=hybrid_module._node_source_term_hashes,
            ) as source_term_hashes,
            patch.object(
                hybrid_module,
                "_node_protected_term_hashes",
                wraps=hybrid_module._node_protected_term_hashes,
            ) as protected_term_hashes,
            patch.object(
                hybrid_module,
                "_source_graph_term_hashes",
                wraps=hybrid_module._source_graph_term_hashes,
            ) as candidate_term_hashes,
        ):
            result = self._run(
                query_text=fixture.query_text,
                effective_graph_view=fixture.view,
                seed_node_ids=(fixture.anchor_node_id,),
                limits=replace(
                    DEFAULT_SEMANTIC_PLAN_LIMITS,
                    max_results=max_results,
                ),
            )
        return result, (
            source_term_hashes.call_count,
            protected_term_hashes.call_count,
            candidate_term_hashes.call_count,
        )

    def _assert_cited_answer_and_hop_lineage(self, result) -> None:
        self.assertTrue(result.answer_citation_hashes)
        self.assertTrue(set(result.answer_citation_hashes) <= self.authorized_hashes)
        answer_citations = set(result.answer_citation_hashes)
        answer_supported_paths = [
            path
            for path in result.graph_paths
            if path.hops and set(path.cited_observation_hashes) <= answer_citations
        ]
        self.assertTrue(answer_supported_paths)
        for path in result.graph_paths:
            for hop in path.hops:
                self.assertTrue(hop.cited_observation_hashes)
                self.assertTrue(set(hop.cited_observation_hashes) <= self.authorized_hashes)
        answer = render_governed_evidence_answer(result)
        self.assertEqual(answer.status, "answered")
        self.assertEqual(answer.citation_hashes, result.answer_citation_hashes)

    def _assert_exact_minimal_node_backed_citations(
        self,
        result,
        *,
        supporting_observation_hashes: Sequence[str],
    ) -> None:
        required_path_citations = {
            self.inputs.current_observation_hash,
            self._observation_hash("obs_issue56_semantic_current_body_2"),
        }
        selected_paths = [
            path
            for path in result.graph_paths
            if path.hop_count == 2 and set(path.cited_observation_hashes) == required_path_citations
        ]
        self.assertEqual(len(selected_paths), 1)
        selected_path = selected_paths[0]
        hop_citation_union = {
            observation_hash
            for hop in selected_path.hops
            for observation_hash in hop.cited_observation_hashes
        }
        self.assertEqual(
            hop_citation_union,
            set(selected_path.cited_observation_hashes),
        )
        self.assertEqual(hop_citation_union, required_path_citations)

        supporting_hashes = set(supporting_observation_hashes)
        self.assertTrue(supporting_hashes)
        self.assertTrue(supporting_hashes <= self.authorized_hashes)
        self.assertTrue(supporting_hashes.isdisjoint(required_path_citations))
        expected_citations = tuple(sorted(required_path_citations | supporting_hashes))
        self.assertEqual(result.answer_citation_hashes, expected_citations)
        self.assertEqual(
            len(result.answer_citation_hashes),
            len(required_path_citations) + len(supporting_hashes),
        )
        self.assertEqual(
            result.answer_citation_hashes,
            tuple(sorted(result.answer_citation_hashes)),
        )
        self.assertLessEqual(
            len(result.answer_citation_hashes),
            min(48, DEFAULT_SEMANTIC_PLAN_LIMITS.max_evidence),
        )

    def _assert_exact_minimal_path_and_support_citations(
        self,
        result,
        *,
        selected_path,
        supporting_observation_hashes: Sequence[str],
    ) -> None:
        hop_citation_union = {
            observation_hash
            for hop in selected_path.hops
            for observation_hash in hop.cited_observation_hashes
        }
        self.assertEqual(
            hop_citation_union,
            set(selected_path.cited_observation_hashes),
        )
        supporting_hashes = set(supporting_observation_hashes)
        self.assertTrue(supporting_hashes)
        self.assertTrue(supporting_hashes <= self.authorized_hashes)
        missing_support = supporting_hashes - hop_citation_union
        self.assertTrue(missing_support)
        expected_citations = tuple(sorted(hop_citation_union | missing_support))
        self.assertEqual(result.answer_citation_hashes, expected_citations)
        self.assertEqual(
            result.answer_citation_hashes,
            tuple(sorted(result.answer_citation_hashes)),
        )
        self.assertLessEqual(
            len(result.answer_citation_hashes),
            min(48, DEFAULT_SEMANTIC_PLAN_LIMITS.max_evidence),
        )

    def _assert_observation_supports_term(
        self,
        *,
        observation_id: str,
        term: str,
        protected: bool,
    ) -> None:
        self.assertTrue(
            self._observation_supports_term(
                observation_id=observation_id,
                term=term,
                protected=protected,
            )
        )

    def _observation_supports_term(
        self,
        *,
        observation_id: str,
        term: str,
        protected: bool,
    ) -> bool:
        observation = next(
            observation
            for observations in self.inputs.observations_by_bundle_id.values()
            for observation in observations
            if observation.observation_id == observation_id
        )
        analysis = self.runtime.tokenizer_profile.analyze(observation.text or "")
        if protected:
            return term.casefold() in {span.exact_token for span in analysis.protected_identifiers}
        return term in analysis.tokens

    def _observation_hash(self, observation_id: str) -> str:
        observation = next(
            observation
            for observations in self.inputs.observations_by_bundle_id.values()
            for observation in observations
            if observation.observation_id == observation_id
        )
        return sha256_json(observation.to_dict())


def _view_with_node_term(
    view,
    *,
    node_id: str,
    property_name: str,
    term: str,
    supporting_observation_ids: Sequence[str] = (),
):
    nodes = []
    for node in view.visible_nodes:
        if node.node_id != node_id:
            nodes.append(node)
            continue
        properties = dict(node.properties)
        normalized_term = term.casefold() if property_name == "protected_term_hashes" else term
        properties[property_name] = sorted(
            {
                *properties.get(property_name, ()),
                sha256_json(normalized_term),
            }
        )
        properties["source_observation_ids"] = sorted(
            {
                *properties.get("source_observation_ids", ()),
                *supporting_observation_ids,
            }
        )
        nodes.append(replace(node, properties=properties))
    return replace(view, visible_nodes=nodes)


def _view_with_node_terms(
    view,
    *term_specs: tuple[str, str, str, Sequence[str]],
):
    selected_view = view
    for (
        node_id,
        property_name,
        term,
        supporting_observation_ids,
    ) in term_specs:
        selected_view = _view_with_node_term(
            selected_view,
            node_id=node_id,
            property_name=property_name,
            term=term,
            supporting_observation_ids=supporting_observation_ids,
        )
    return selected_view


def _view_with_unusable_node(
    view,
    *,
    namespace: str,
    source_observation_id: str,
):
    node_id = f"node_issue56_unusable_{namespace}"
    node = GraphProjectionNode(
        node_id=node_id,
        source_type="canonical_entity",
        source_id=f"entity_{node_id}",
        labels=["redacted"],
        properties={
            "source_observation_ids": [source_observation_id],
            "temporal_state": "current",
            "core_supertype_id": "Concept",
            "type_confidence": 0.95,
            "protected_term_hashes": [sha256_json("2026-10-01")],
            "source_term_hashes": [sha256_json("交期")],
        },
        permission_scope={"scope_type": "public", "visibility": "public"},
    )
    edge = GraphProjectionEdge(
        edge_id=f"edge_issue56_unusable_{namespace}",
        source_node_id="node_issue56_supplier",
        target_node_id=node_id,
        relation_type="origin_in",
        properties={"source_observation_ids": [source_observation_id]},
        permission_scope={"scope_type": "public", "visibility": "public"},
    )
    return replace(
        view,
        visible_nodes=[*view.visible_nodes, node],
        visible_edges=[*view.visible_edges, edge],
    )


def _view_with_observation_lineage_without_node_term(
    view,
    *,
    node_id: str,
    term: str,
    supporting_observation_id: str,
):
    term_hashes = {
        sha256_json(term),
        sha256_json(term.casefold()),
    }
    nodes = []
    for node in view.visible_nodes:
        if node.node_id != node_id:
            nodes.append(node)
            continue
        properties = dict(node.properties)
        for property_name in (
            "protected_term_hashes",
            "source_term_hashes",
        ):
            properties[property_name] = [
                value for value in properties.get(property_name, ()) if value not in term_hashes
            ]
        for property_name in (
            "aliases",
            "canonical_label",
            "inventory_value",
            "label",
            "summary",
        ):
            properties.pop(property_name, None)
        properties["source_observation_ids"] = sorted(
            {
                *properties.get("source_observation_ids", ()),
                supporting_observation_id,
            }
        )
        nodes.append(
            replace(
                node,
                labels=["source bound node"],
                properties=properties,
            )
        )
    return replace(view, visible_nodes=nodes)


def _view_with_binding_revision(
    view,
    *,
    suffix: str,
    applied_grant_ids: Sequence[str],
):
    return replace(
        view,
        user_graph_revision_id=f"ugraph_issue56_binding_{suffix}",
        canonical_graph_revision_id=f"cgraph_issue56_binding_{suffix}",
        ontology_revision_id=f"ontology_issue56_binding_{suffix}",
        assembly_policy_id=f"assembly_issue56_binding_{suffix}",
        applied_grant_ids=list(applied_grant_ids),
    )


def _view_with_changed_authorized_edge_evidence(
    view,
    *,
    edge_id: str,
    source_observation_id: str,
):
    edges = []
    for edge in view.visible_edges:
        if edge.edge_id != edge_id:
            edges.append(edge)
            continue
        properties = dict(edge.properties)
        properties["source_observation_ids"] = [source_observation_id]
        edges.append(replace(edge, properties=properties))
    return replace(view, visible_edges=edges)


@dataclass(frozen=True)
class _ConnectedOffPathSupportFixture:
    view: Any
    query_text: str
    anchor_node_id: str
    support_node_hashes: frozenset[str]
    supporting_observation_hashes: tuple[str, ...]


def _connected_off_path_support_fixture(
    view,
    *,
    support_depth: int = 2,
    branch_count: int = 5,
) -> _ConnectedOffPathSupportFixture:
    if support_depth not in {2, 3}:
        raise ValueError("support_depth must remain within the bounded E2E fixture")
    if branch_count < 1:
        raise ValueError("branch_count must be positive")

    anchor_node_id = "node_issue56_completion_anchor"
    identifier_node_id = "node_issue56_completion_identifier"
    origin_node_id = "node_issue56_completion_origin"
    bridge_node_id = "node_issue56_completion_bridge"
    hop_observation_id = "obs_issue56_semantic_current_body_1"
    identifier_observation_id = "obs_issue56_semantic_current_body_3"
    origin_observation_id = "obs_issue56_semantic_current_body_2"

    nodes = [
        _proof_node(
            anchor_node_id,
            source_observation_id=hop_observation_id,
            labels=("proof anchor",),
        ),
        _proof_node(
            identifier_node_id,
            source_observation_id=identifier_observation_id,
            labels=("identifier support",),
            protected_terms=("PO470002004",),
            source_terms=("交期",),
        ),
        _proof_node(
            origin_node_id,
            source_observation_id=origin_observation_id,
            labels=("origin support",),
            protected_terms=("ORIGIN-TAIWAN-01",),
        ),
    ]
    if support_depth == 3:
        nodes.append(
            _proof_node(
                bridge_node_id,
                source_observation_id=hop_observation_id,
                labels=("proof bridge",),
            )
        )

    edges: list[GraphProjectionEdge] = []
    for branch_index in range(branch_count):
        branch_node_id = f"node_issue56_completion_branch_{branch_index:02d}"
        nodes.append(
            _proof_node(
                branch_node_id,
                source_observation_id=hop_observation_id,
                labels=("incomplete branch",),
            )
        )
        edges.append(
            _proof_edge(
                f"edge_issue56_completion_branch_{branch_index:02d}",
                source_node_id=anchor_node_id,
                target_node_id=branch_node_id,
                source_observation_id=hop_observation_id,
            )
        )
        for leaf_index in range(6):
            leaf_node_id = (
                f"node_issue56_completion_branch_{branch_index:02d}_leaf_{leaf_index:02d}"
            )
            nodes.append(
                _proof_node(
                    leaf_node_id,
                    source_observation_id=hop_observation_id,
                    labels=("incomplete leaf",),
                )
            )
            edges.append(
                _proof_edge(
                    (
                        f"edge_issue56_completion_branch_{branch_index:02d}"
                        f"_leaf_{leaf_index:02d}"
                    ),
                    source_node_id=branch_node_id,
                    target_node_id=leaf_node_id,
                    source_observation_id=hop_observation_id,
                )
            )

    edges.append(
        _proof_edge(
            "edge_issue56_completion_support_identifier",
            source_node_id=anchor_node_id,
            target_node_id=identifier_node_id,
            source_observation_id=hop_observation_id,
        )
    )
    if support_depth == 2:
        edges.append(
            _proof_edge(
                "edge_issue56_completion_support_origin",
                source_node_id=identifier_node_id,
                target_node_id=origin_node_id,
                source_observation_id=hop_observation_id,
            )
        )
    else:
        edges.extend(
            (
                _proof_edge(
                    "edge_issue56_completion_support_bridge",
                    source_node_id=identifier_node_id,
                    target_node_id=bridge_node_id,
                    source_observation_id=hop_observation_id,
                ),
                _proof_edge(
                    "edge_issue56_completion_support_origin",
                    source_node_id=bridge_node_id,
                    target_node_id=origin_node_id,
                    source_observation_id=hop_observation_id,
                ),
            )
        )

    selected_view = replace(
        view,
        user_graph_revision_id=f"ugraph_issue56_completion_depth_{support_depth}",
        canonical_graph_revision_id=(f"cgraph_issue56_completion_depth_{support_depth}"),
        ontology_revision_id=f"ontology_issue56_completion_depth_{support_depth}",
        assembly_policy_id=f"assembly_issue56_completion_depth_{support_depth}",
        visible_nodes=nodes,
        visible_edges=edges,
    )
    observation_hash_by_id = {
        observation.observation_id: sha256_json(observation.to_dict())
        for observations in build_semantic_poc_inputs().observations_by_bundle_id.values()
        for observation in observations
    }
    support_node_ids = (
        (identifier_node_id, origin_node_id)
        if support_depth == 2
        else (identifier_node_id, bridge_node_id, origin_node_id)
    )
    return _ConnectedOffPathSupportFixture(
        view=selected_view,
        query_text="PO470002004 與 ORIGIN-TAIWAN-01 的交期關係",
        anchor_node_id=anchor_node_id,
        support_node_hashes=frozenset(sha256_json(node_id) for node_id in support_node_ids),
        supporting_observation_hashes=tuple(
            sorted(
                (
                    observation_hash_by_id[identifier_observation_id],
                    observation_hash_by_id[origin_observation_id],
                )
            )
        ),
    )


def _proof_node(
    node_id: str,
    *,
    source_observation_id: str,
    labels: Sequence[str],
    protected_terms: Sequence[str] = (),
    source_terms: Sequence[str] = (),
    node_kind: str | None = None,
) -> GraphProjectionNode:
    properties: dict[str, Any] = {
        "source_observation_ids": [source_observation_id],
        "temporal_state": "current",
        "core_supertype_id": "Concept",
        "type_confidence": 0.95,
    }
    if protected_terms:
        properties["protected_term_hashes"] = [
            sha256_json(term.casefold()) for term in protected_terms
        ]
    if source_terms:
        properties["source_term_hashes"] = [sha256_json(term) for term in source_terms]
    if node_kind is not None:
        properties["node_kind"] = node_kind
    return GraphProjectionNode(
        node_id=node_id,
        source_type="canonical_entity",
        source_id=f"entity_{node_id}",
        labels=list(labels),
        properties=properties,
        permission_scope={"scope_type": "public", "visibility": "public"},
    )


def _proof_edge(
    edge_id: str,
    *,
    source_node_id: str,
    target_node_id: str,
    source_observation_id: str,
) -> GraphProjectionEdge:
    return GraphProjectionEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        relation_type="origin_in",
        properties={"source_observation_ids": [source_observation_id]},
        permission_scope={"scope_type": "public", "visibility": "public"},
    )


def _path_node_hashes(path) -> frozenset[str]:
    return frozenset(
        node_hash for hop in path.hops for node_hash in (hop.source_node_hash, hop.target_node_hash)
    )


class _ContractOnlySentenceTransformerModel:
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


if __name__ == "__main__":
    unittest.main()
