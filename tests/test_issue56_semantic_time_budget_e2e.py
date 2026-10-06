from __future__ import annotations

from dataclasses import dataclass
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_mail import SemanticPlanLimits, build_authorized_semantic_mail_session
from formowl_mail import hybrid as hybrid_module
from scripts.issue56_semantic_execution_smoke import (
    ALLOWED_RELATIONS,
    REQUESTER_USER_ID,
    WORKSPACE_ID,
    build_semantic_poc_inputs,
)
from test_issue56_node_backed_fallback_e2e import (
    _connected_off_path_support_fixture,
    _contract_only_runtime,
)


@dataclass
class _ManualMonotonicClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Issue56SemanticTimeBudgetEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = build_semantic_poc_inputs()
        cls.runtime = _contract_only_runtime()

    def setUp(self) -> None:
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
            )
        self.limits = SemanticPlanLimits(max_time_budget_ms=1_000)

    def test_completed_strict_traversal_after_deadline_returns_no_partial_proof(
        self,
    ) -> None:
        first = self._strict_timeout_result()
        second = self._strict_timeout_result()

        self._assert_timeout_result(first)
        self.assertEqual(first.result_fingerprint, second.result_fingerprint)
        self.assertEqual(first.plan_fingerprint, second.plan_fingerprint)
        self.assertEqual(
            first.graph_revision_fingerprint,
            second.graph_revision_fingerprint,
        )

    def test_completion_shares_deadline_and_timeout_does_not_poison_cache(
        self,
    ) -> None:
        fixture = _connected_off_path_support_fixture(
            self.inputs.effective_graph_view,
        )
        clock = _ManualMonotonicClock()
        traversal_runner = hybrid_module._bounded_graph_traversal
        projection_base_builder = hybrid_module._build_relation_projection_base
        traversal_count = 0

        def expire_after_completion_traversal(**kwargs):
            nonlocal traversal_count
            traversal_count += 1
            result = traversal_runner(**kwargs)
            if traversal_count == 2:
                clock.advance(2.0)
            return result

        with (
            patch.object(hybrid_module, "_MONOTONIC_CLOCK", clock),
            patch.object(
                hybrid_module,
                "_build_relation_projection_base",
                wraps=projection_base_builder,
            ) as build_projection_base,
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                side_effect=expire_after_completion_traversal,
            ),
        ):
            timed_out = self._run_fixture(fixture)

        self.assertEqual(traversal_count, 2)
        self.assertEqual(build_projection_base.call_count, 1)
        self._assert_timeout_result(timed_out)

        with (
            patch.object(hybrid_module, "_MONOTONIC_CLOCK", clock),
            patch.object(
                hybrid_module,
                "_build_relation_projection_base",
                wraps=projection_base_builder,
            ) as rebuild_projection_base,
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                wraps=traversal_runner,
            ) as retry_traversal,
        ):
            retry = self._run_fixture(fixture)

        self.assertEqual(rebuild_projection_base.call_count, 0)
        self.assertEqual(retry_traversal.call_count, 2)
        self.assertEqual(retry.status, "ok")
        self.assertTrue(retry.answer_citation_hashes)
        self.assertTrue(retry.graph_paths)
        self.assertIn(
            "bounded_relation_targeted_retraversal_attempted",
            retry.warnings,
        )

    def test_permission_denial_precedes_deadline_and_materializes_no_candidates(
        self,
    ) -> None:
        with patch.object(
            hybrid_module,
            "_load_pinned_issue56_runtime_components",
            return_value=self.runtime,
        ):
            denied_session = build_authorized_semantic_mail_session(
                observations_by_bundle_id=self.inputs.observations_by_bundle_id,
                bundles=self.inputs.bundles,
                requester_user_id=REQUESTER_USER_ID,
                workspace_id=WORKSPACE_ID,
                mail_evidence_bundle_id=(self.inputs.denied_bundle.mail_evidence_bundle_id),
            )

        with patch.object(
            hybrid_module,
            "_MONOTONIC_CLOCK",
            side_effect=AssertionError("denied query must not start a deadline"),
        ):
            result = denied_session.query(
                query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
                effective_graph_view=self.inputs.effective_graph_view,
                allowed_relation_types=ALLOWED_RELATIONS,
                limits=self.limits,
            )

        self.assertEqual(result.status, "permission_denied")
        self.assertEqual(result.materialized_candidate_count, 0)
        self.assertEqual(result.graph_paths, ())
        self.assertEqual(result.scores, ())
        self.assertEqual(result.answer_citation_hashes, ())
        self.assertEqual(result.warnings, ("mail_evidence_permission_denied",))

    def _strict_timeout_result(self):
        clock = _ManualMonotonicClock()
        traversal_runner = hybrid_module._bounded_graph_traversal

        def expire_after_traversal(**kwargs):
            result = traversal_runner(**kwargs)
            clock.advance(2.0)
            return result

        with (
            patch.object(hybrid_module, "_MONOTONIC_CLOCK", clock),
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                side_effect=expire_after_traversal,
            ) as traversal,
        ):
            result = self.session.query(
                query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
                effective_graph_view=self.inputs.effective_graph_view,
                allowed_relation_types=ALLOWED_RELATIONS,
                limits=self.limits,
            )
        self.assertEqual(traversal.call_count, 1)
        return result

    def _run_fixture(self, fixture):
        return self.session.query(
            query_text=fixture.query_text,
            effective_graph_view=fixture.view,
            allowed_relation_types=ALLOWED_RELATIONS,
            seed_node_ids=(fixture.anchor_node_id,),
            limits=self.limits,
        )

    def _assert_timeout_result(self, result) -> None:
        self.assertEqual(result.status, "no_answer")
        self.assertEqual(
            result.warnings,
            ("semantic_query_time_budget_exhausted",),
        )
        self.assertEqual(result.claim_strength, "no_claim")
        self.assertIsNotNone(result.plan_fingerprint)
        self.assertEqual(result.graph_paths, ())
        self.assertEqual(result.scores, ())
        self.assertEqual(result.answer_citation_hashes, ())
        self.assertIsNone(result.exact_result)
        self.assertIsNone(result.lineage_audit)
        self.assertEqual(result.graph_path_count, 0)
        self.assertEqual(result.semantic_result_count, 0)
        self.assertEqual(result.rejected_hop_count, 0)
        self.assertEqual(result.exact_executor_status, "not_started")


if __name__ == "__main__":
    unittest.main()
