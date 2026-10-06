from __future__ import annotations

from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_graph import EffectiveGraphView
from formowl_mail import (
    RelationProjectionBaseColdDiagnostic,
    build_authorized_semantic_mail_session,
    build_authorized_source_backed_effective_graph_view,
    precompute_effective_graph_content_snapshot,
    precompute_relation_projection_base_cold_diagnostic,
)
from formowl_mail import hybrid as hybrid_module
from scripts.issue56_semantic_execution_smoke import (
    ALLOWED_RELATIONS,
    REQUESTER_USER_ID,
    WORKSPACE_ID,
    build_semantic_poc_inputs,
)
from test_issue56_node_backed_fallback_e2e import _contract_only_runtime


class Issue56RelationProjectionBaseColdDiagnosticEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = _contract_only_runtime()

    def setUp(self) -> None:
        self.inputs = build_semantic_poc_inputs()
        with patch.object(
            hybrid_module,
            "_load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            self.session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=self.inputs.bundles,
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
                mail_evidence_bundle_id=(self.inputs.current_bundle.mail_evidence_bundle_id),
            )
        graph_build = build_authorized_source_backed_effective_graph_view(
            session=self.session,
            observations_by_bundle_id=self.inputs.observations_by_bundle_id,
            source_binding_fingerprint=sha256_json(
                "issue56 cold relation projection diagnostic fixture"
            ),
        )
        self.source_view = graph_build.effective_graph_view
        self.query_text = "PO470002002 與 ORIGIN-TAIWAN-01 的供應商資訊關係"

    def test_cold_helper_records_exact_build_and_query_reuses_publication(
        self,
    ) -> None:
        view = self._fresh_view()
        graph_fingerprint, view_fingerprint = self._preseal(view)
        real_binding_scan = hybrid_module._relation_projection_candidate_binding_inputs
        real_base_builder = hybrid_module._build_relation_projection_base
        diagnostic_clock = unittest.mock.Mock(
            side_effect=(
                1_000_000_000,
                1_125_000_000,
                2_000_000_000,
                2_250_000_000,
            )
        )
        with (
            patch.object(
                hybrid_module,
                "_RELATION_PROJECTION_COLD_DIAGNOSTIC_CLOCK_NS",
                diagnostic_clock,
            ),
            patch.object(
                hybrid_module,
                "_relation_projection_candidate_binding_inputs",
                wraps=real_binding_scan,
            ) as binding_scan,
            patch.object(
                hybrid_module,
                "_build_relation_projection_base",
                wraps=real_base_builder,
            ) as base_builder,
        ):
            evidence = precompute_relation_projection_base_cold_diagnostic(
                session=self.session,
                effective_graph_view=view,
                expected_graph_revision_fingerprint=graph_fingerprint,
                expected_effective_graph_view_fingerprint=view_fingerprint,
            )
            result = self._query(view)

        self.assertIsInstance(
            evidence,
            RelationProjectionBaseColdDiagnostic,
        )
        self.assertEqual(binding_scan.call_count, 1)
        self.assertEqual(base_builder.call_count, 1)
        self.assertEqual(diagnostic_clock.call_count, 4)
        self.assertEqual(
            (
                evidence.before_binding_cache_entry_count,
                evidence.before_base_cache_entry_count,
                evidence.after_binding_cache_entry_count,
                evidence.after_base_cache_entry_count,
            ),
            (0, 0, 1, 1),
        )
        self.assertEqual(evidence.binding_invocation_count, 1)
        self.assertEqual(evidence.base_builder_invocation_count, 1)
        self.assertEqual(evidence.binding_elapsed_ms, 125.0)
        self.assertEqual(evidence.base_builder_elapsed_ms, 250.0)
        self.assertEqual(evidence.binding_publication_status, "published")
        self.assertEqual(evidence.base_publication_status, "published")
        self.assertEqual(self._cache_counts(view), (1, 1))
        self.assertNotEqual(result.status, "permission_denied")

        safe = evidence.to_safe_dict()
        self.assertEqual(safe["status"], "passed")
        self.assertEqual(safe["deadline_mode"], "offline_no_query_deadline")
        self.assertEqual(
            safe["phases"]["binding"],
            {
                "started": True,
                "completed": True,
                "elapsed_ms": 125.0,
                "invocation_count": 1,
                "publication_status": "published",
            },
        )
        rendered = json.dumps(safe, ensure_ascii=False, sort_keys=True)
        for private_value in (
            self.query_text,
            "PO470002002",
            "PO470002004",
            "ORIGIN-TAIWAN-01",
            self.session.requester_user_id,
            self.session.workspace_id,
            self.source_view.visible_nodes[0].node_id,
            '"tenant"',
            '"tenant_id"',
            "/tmp/",
        ):
            self.assertNotIn(private_value, rendered)

    def test_isolated_presealed_views_have_timing_free_equivalent_queries(
        self,
    ) -> None:
        before_view = self._fresh_view()
        after_view = self._fresh_view()
        before_graph, before_view_fingerprint = self._preseal(before_view)
        after_graph, after_view_fingerprint = self._preseal(after_view)
        self.assertEqual(before_graph, after_graph)
        self.assertEqual(before_view_fingerprint, after_view_fingerprint)

        before_evidence = precompute_relation_projection_base_cold_diagnostic(
            session=self.session,
            effective_graph_view=before_view,
            expected_graph_revision_fingerprint=before_graph,
            expected_effective_graph_view_fingerprint=(before_view_fingerprint),
        )
        after_precompute = hybrid_module.precompute_relation_projection_base(
            session=self.session,
            effective_graph_view=after_view,
        )
        self.assertEqual(
            before_evidence.cache_binding_fingerprint,
            after_precompute.cache_binding_fingerprint,
        )

        before_snapshot = hybrid_module._build_query_graph_snapshot(before_view)
        after_snapshot = hybrid_module._build_query_graph_snapshot(after_view)
        self.assertIsNot(
            before_snapshot.content_snapshot,
            after_snapshot.content_snapshot,
        )
        self.assertIsNot(
            before_snapshot.content_snapshot.relation_projection_base_lock,
            after_snapshot.content_snapshot.relation_projection_base_lock,
        )
        self.assertIsNot(
            before_snapshot.content_snapshot.relation_projection_cache_binding_snapshots,
            after_snapshot.content_snapshot.relation_projection_cache_binding_snapshots,
        )
        self.assertIsNot(
            before_snapshot.content_snapshot.relation_projection_bases,
            after_snapshot.content_snapshot.relation_projection_bases,
        )

        real_binding_scan = hybrid_module._relation_projection_candidate_binding_inputs
        real_base_builder = hybrid_module._build_relation_projection_base
        with (
            patch.object(
                hybrid_module,
                "_relation_projection_candidate_binding_inputs",
                wraps=real_binding_scan,
            ) as binding_scan,
            patch.object(
                hybrid_module,
                "_build_relation_projection_base",
                wraps=real_base_builder,
            ) as base_builder,
        ):
            before_result = self._query(before_view)
            after_result = self._query(after_view)

        self.assertEqual(binding_scan.call_count, 0)
        self.assertEqual(base_builder.call_count, 0)
        self.assertEqual(before_result.to_safe_dict(), after_result.to_safe_dict())
        self.assertEqual(
            before_result.plan_fingerprint,
            after_result.plan_fingerprint,
        )
        self.assertEqual(
            before_result.result_fingerprint,
            after_result.result_fingerprint,
        )
        self.assertEqual(before_result.graph_paths, after_result.graph_paths)
        self.assertEqual(before_result.scores, after_result.scores)
        self.assertEqual(
            before_result.answer_citation_hashes,
            after_result.answer_citation_hashes,
        )
        self.assertEqual(self._cache_counts(before_view), (1, 1))
        self.assertEqual(self._cache_counts(after_view), (1, 1))

    def test_helper_requires_presealed_cold_caches_and_rejects_reuse(
        self,
    ) -> None:
        unsealed = self._fresh_view()
        expected_view_fingerprint = sha256_json(unsealed.to_dict())
        expected_graph_fingerprint = hybrid_module._graph_revision_pin_fingerprint(unsealed)
        with self.assertRaisesRegex(
            ContractValidationError,
            "content snapshot is unavailable",
        ):
            precompute_relation_projection_base_cold_diagnostic(
                session=self.session,
                effective_graph_view=unsealed,
                expected_graph_revision_fingerprint=(expected_graph_fingerprint),
                expected_effective_graph_view_fingerprint=(expected_view_fingerprint),
            )

        view = self._fresh_view()
        graph_fingerprint, view_fingerprint = self._preseal(view)
        precompute_relation_projection_base_cold_diagnostic(
            session=self.session,
            effective_graph_view=view,
            expected_graph_revision_fingerprint=graph_fingerprint,
            expected_effective_graph_view_fingerprint=view_fingerprint,
        )
        with self.assertRaisesRegex(
            ContractValidationError,
            "requires empty caches",
        ):
            precompute_relation_projection_base_cold_diagnostic(
                session=self.session,
                effective_graph_view=view,
                expected_graph_revision_fingerprint=graph_fingerprint,
                expected_effective_graph_view_fingerprint=view_fingerprint,
            )

    def test_graph_index_candidate_requester_and_permission_drift_fail_closed(
        self,
    ) -> None:
        with self.subTest("expected graph revision"):
            view = self._fresh_view()
            graph_fingerprint, view_fingerprint = self._preseal(view)
            with self.assertRaisesRegex(
                ContractValidationError,
                "graph revision mismatch",
            ):
                precompute_relation_projection_base_cold_diagnostic(
                    session=self.session,
                    effective_graph_view=view,
                    expected_graph_revision_fingerprint=sha256_json("stale graph"),
                    expected_effective_graph_view_fingerprint=view_fingerprint,
                )
            self.assertEqual(self._cache_counts(view), (0, 0))
            self.assertNotEqual(graph_fingerprint, sha256_json("stale graph"))

        with self.subTest("index fingerprint"):
            view = self._fresh_view()
            graph_fingerprint, view_fingerprint = self._preseal(view)
            changed_index_fingerprint = sha256_json("stale index")
            changed_index = replace(
                self.session.index,
                index_fingerprint=changed_index_fingerprint,
            )
            with self.assertRaisesRegex(
                ContractValidationError,
                "mail session binding mismatch|mail evidence index binding mismatch",
            ):
                precompute_relation_projection_base_cold_diagnostic(
                    session=replace(self.session, index=changed_index),
                    effective_graph_view=view,
                    expected_graph_revision_fingerprint=graph_fingerprint,
                    expected_effective_graph_view_fingerprint=view_fingerprint,
                )
            self.assertEqual(self._cache_counts(view), (0, 0))

        with self.subTest("candidate tuple identity"):
            view = self._fresh_view()
            graph_fingerprint, view_fingerprint = self._preseal(view)
            replacement_candidates = tuple(candidate for candidate in self.session.index.candidates)
            self.assertIsNot(
                replacement_candidates,
                self.session.index.candidates,
            )
            changed_index = replace(
                self.session.index,
                candidates=replacement_candidates,
                _integrity_fingerprint=(
                    hybrid_module._hybrid_index_integrity_fingerprint(
                        index_fingerprint=(self.session.index.index_fingerprint),
                        tokenizer_id=self.session.index.tokenizer_id,
                        profile_fingerprint=(self.session.index.profile_fingerprint),
                        execution_component_fingerprint=(
                            self.session.index.execution_component_fingerprint
                        ),
                        candidates=replacement_candidates,
                    )
                ),
            )
            with self.assertRaisesRegex(
                ContractValidationError,
                "mail index binding mismatch|candidate content snapshot mismatch",
            ):
                precompute_relation_projection_base_cold_diagnostic(
                    session=replace(self.session, index=changed_index),
                    effective_graph_view=view,
                    expected_graph_revision_fingerprint=graph_fingerprint,
                    expected_effective_graph_view_fingerprint=view_fingerprint,
                )
            self.assertEqual(self._cache_counts(view), (0, 0))

        with self.subTest("requester"):
            view = self._fresh_view()
            changed_view = replace(
                view,
                requester_user_id="user_issue56_other",
            )
            graph_fingerprint, view_fingerprint = self._seal_without_validation(changed_view)
            with self.assertRaisesRegex(
                ContractValidationError,
                "requester mismatch",
            ):
                precompute_relation_projection_base_cold_diagnostic(
                    session=self.session,
                    effective_graph_view=changed_view,
                    expected_graph_revision_fingerprint=graph_fingerprint,
                    expected_effective_graph_view_fingerprint=view_fingerprint,
                )
            self.assertEqual(self._cache_counts(changed_view), (0, 0))

        with self.subTest("permission"):
            view = self._fresh_view()
            changed_node = replace(
                view.visible_nodes[0],
                permission_scope={
                    "scope_type": "project",
                    "scope_id": "project_issue56_permission_drift",
                    "visibility": "public",
                },
            )
            changed_view = replace(
                view,
                visible_nodes=[
                    changed_node,
                    *view.visible_nodes[1:],
                ],
            )
            graph_fingerprint, view_fingerprint = self._seal_without_validation(changed_view)
            with self.assertRaisesRegex(
                ContractValidationError,
                "permission.*mismatch|node permission lineage mismatch",
            ):
                precompute_relation_projection_base_cold_diagnostic(
                    session=self.session,
                    effective_graph_view=changed_view,
                    expected_graph_revision_fingerprint=graph_fingerprint,
                    expected_effective_graph_view_fingerprint=view_fingerprint,
                )
            self.assertEqual(self._cache_counts(changed_view), (0, 0))

    def test_active_deadline_fails_and_default_paths_do_not_touch_clock(
        self,
    ) -> None:
        view = self._fresh_view()
        graph_fingerprint, view_fingerprint = self._preseal(view)
        deadline = hybrid_module._QueryExecutionDeadline.start(budget_ms=1_500)
        token = hybrid_module._ACTIVE_QUERY_EXECUTION_DEADLINE.set(deadline)
        try:
            with self.assertRaisesRegex(
                ContractValidationError,
                "cannot run under a query deadline",
            ):
                precompute_relation_projection_base_cold_diagnostic(
                    session=self.session,
                    effective_graph_view=view,
                    expected_graph_revision_fingerprint=graph_fingerprint,
                    expected_effective_graph_view_fingerprint=view_fingerprint,
                )
        finally:
            hybrid_module._ACTIVE_QUERY_EXECUTION_DEADLINE.reset(token)
        self.assertEqual(self._cache_counts(view), (0, 0))

        default_view = self._fresh_view()
        self._preseal(default_view)
        diagnostic_clock = unittest.mock.Mock(
            side_effect=AssertionError("diagnostic clock must remain unused")
        )
        with patch.object(
            hybrid_module,
            "_RELATION_PROJECTION_COLD_DIAGNOSTIC_CLOCK_NS",
            diagnostic_clock,
        ):
            hybrid_module.precompute_relation_projection_base(
                session=self.session,
                effective_graph_view=default_view,
            )
            self._query(default_view)
        diagnostic_clock.assert_not_called()
        self.assertEqual(self._cache_counts(default_view), (1, 1))

    def _fresh_view(self) -> EffectiveGraphView:
        source = self.source_view
        return EffectiveGraphView(
            requester_user_id=source.requester_user_id,
            user_graph_revision_id=source.user_graph_revision_id,
            canonical_graph_revision_id=source.canonical_graph_revision_id,
            ontology_revision_id=source.ontology_revision_id,
            assembly_policy_id=source.assembly_policy_id,
            visible_nodes=list(source.visible_nodes),
            visible_edges=list(source.visible_edges),
            access_required=list(source.access_required),
            applied_grant_ids=list(source.applied_grant_ids),
        )

    def _preseal(self, view: EffectiveGraphView) -> tuple[str, str]:
        view_fingerprint = sha256_json(view.to_dict())
        graph_fingerprint = hybrid_module._graph_revision_fingerprint(view)
        evidence = precompute_effective_graph_content_snapshot(
            session=self.session,
            effective_graph_view=view,
            expected_graph_revision_fingerprint=graph_fingerprint,
            expected_effective_graph_view_fingerprint=view_fingerprint,
        )
        self.assertEqual(
            (
                evidence.relation_projection_cache_binding_entry_count,
                evidence.relation_projection_base_entry_count,
            ),
            (0, 0),
        )
        return graph_fingerprint, view_fingerprint

    @staticmethod
    def _seal_without_validation(
        view: EffectiveGraphView,
    ) -> tuple[str, str]:
        view_fingerprint = sha256_json(view.to_dict())
        graph_fingerprint = hybrid_module._graph_revision_fingerprint(view)
        return graph_fingerprint, view_fingerprint

    @staticmethod
    def _cache_counts(view: EffectiveGraphView) -> tuple[int, int]:
        snapshot = hybrid_module._build_query_graph_snapshot(view).content_snapshot
        with snapshot.relation_projection_base_lock:
            return (
                len(snapshot.relation_projection_cache_binding_snapshots),
                len(snapshot.relation_projection_bases),
            )

    def _query(self, view: EffectiveGraphView):
        return self.session.query(
            query_text=self.query_text,
            effective_graph_view=view,
            allowed_relation_types=ALLOWED_RELATIONS,
        )


if __name__ == "__main__":
    unittest.main()
