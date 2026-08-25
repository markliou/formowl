from __future__ import annotations

from dataclasses import dataclass
import json
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


class Issue56SemanticPhaseTraceEndToEndTests(unittest.TestCase):
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

    def test_opt_in_trace_is_safe_and_does_not_change_semantic_result(self) -> None:
        query_text = "PO470002002 與 ORIGIN-TAIWAN-01 的關係"
        baseline = self._query(query_text=query_text)
        trace = hybrid_module.SemanticPhaseTrace()
        traced = self._query(query_text=query_text, phase_trace=trace)

        self.assertEqual(traced.to_safe_dict(), baseline.to_safe_dict())
        payload = trace.to_safe_dict()
        self.assertEqual(payload["terminal_status"], "completed")
        self.assertIsNone(payload["deadline_exhausted_phase"])
        by_phase = self._events_by_phase(payload)
        for phase in (
            "source_session_validation",
            "graph_snapshot",
            "routing_plan",
            "lineage_crosswalk",
            "strong_rag",
            "relation_projection",
            "graph_traversal",
            "scoring",
            "proof_citation_selection",
            "lineage_audit",
            "result_projection",
        ):
            self.assertEqual(by_phase[phase][0]["outcome"], "completed")
        self.assertEqual(by_phase["deterministic_exact_execution"][0]["outcome"], "skipped")
        self.assertEqual(by_phase["fallback"][0]["outcome"], "skipped")
        self.assertTrue(all(event["elapsed_ms"] >= 0.0 for event in payload["phases"]))

        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        for private_value in (
            query_text,
            "PO470002002",
            "ORIGIN-TAIWAN-01",
            "obs_issue56_semantic_current_body_1",
            REQUESTER_USER_ID,
            WORKSPACE_ID,
        ):
            self.assertNotIn(private_value, serialized)

    def test_fallback_and_rescoring_are_traced_without_result_drift(self) -> None:
        fixture = _connected_off_path_support_fixture(
            self.inputs.effective_graph_view,
        )
        baseline = self._query(
            query_text=fixture.query_text,
            effective_graph_view=fixture.view,
            seed_node_ids=(fixture.anchor_node_id,),
        )
        trace = hybrid_module.SemanticPhaseTrace()
        traced = self._query(
            query_text=fixture.query_text,
            effective_graph_view=fixture.view,
            seed_node_ids=(fixture.anchor_node_id,),
            phase_trace=trace,
        )

        self.assertEqual(traced.to_safe_dict(), baseline.to_safe_dict())
        self.assertIn(
            "bounded_relation_targeted_retraversal_attempted",
            traced.warnings,
        )
        by_phase = self._events_by_phase(trace.to_safe_dict())
        self.assertEqual(by_phase["fallback"][0]["outcome"], "completed")
        self.assertEqual(
            [event["attempt"] for event in by_phase["scoring"]],
            [1, 2],
        )
        self.assertTrue(all(event["outcome"] == "completed" for event in by_phase["scoring"]))

    def test_deadline_trace_names_exhausted_and_last_completed_phase(self) -> None:
        baseline = self._timeout_after_graph_traversal(phase_trace=None)
        trace = hybrid_module.SemanticPhaseTrace()
        traced = self._timeout_after_graph_traversal(phase_trace=trace)

        self.assertEqual(traced.to_safe_dict(), baseline.to_safe_dict())
        self.assertEqual(traced.status, "no_answer")
        self.assertEqual(
            traced.warnings,
            ("semantic_query_time_budget_exhausted",),
        )
        payload = trace.to_safe_dict()
        self.assertEqual(payload["terminal_status"], "deadline_exhausted")
        self.assertEqual(payload["deadline_exhausted_phase"], "graph_traversal")
        self.assertEqual(payload["last_completed_phase"], "relation_projection")
        by_phase = self._events_by_phase(payload)
        self.assertEqual(by_phase["graph_traversal"][0]["outcome"], "deadline_exhausted")
        for phase in (
            "scoring",
            "proof_citation_selection",
            "fallback",
            "lineage_audit",
            "result_projection",
        ):
            self.assertEqual(by_phase[phase][0]["outcome"], "skipped")

    def test_trace_is_single_use(self) -> None:
        trace = hybrid_module.SemanticPhaseTrace()
        self._query(
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            phase_trace=trace,
        )

        with self.assertRaisesRegex(
            ValueError,
            "single-use",
        ):
            self._query(
                query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
                phase_trace=trace,
            )

    def _query(
        self,
        *,
        query_text: str,
        effective_graph_view=None,
        seed_node_ids=(),
        phase_trace=None,
    ):
        return self.session.query(
            query_text=query_text,
            effective_graph_view=(effective_graph_view or self.inputs.effective_graph_view),
            allowed_relation_types=ALLOWED_RELATIONS,
            seed_node_ids=seed_node_ids,
            limits=SemanticPlanLimits(max_time_budget_ms=1_000),
            phase_trace=phase_trace,
        )

    def _timeout_after_graph_traversal(self, *, phase_trace):
        clock = _ManualMonotonicClock()
        real_traversal = hybrid_module._bounded_graph_traversal

        def expire_after_traversal(**kwargs):
            result = real_traversal(**kwargs)
            clock.advance(2.0)
            return result

        with (
            patch.object(hybrid_module, "_MONOTONIC_CLOCK", clock),
            patch.object(
                hybrid_module,
                "_bounded_graph_traversal",
                side_effect=expire_after_traversal,
            ),
        ):
            return self._query(
                query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
                phase_trace=phase_trace,
            )

    @staticmethod
    def _events_by_phase(payload):
        grouped = {}
        for event in payload["phases"]:
            grouped.setdefault(event["phase"], []).append(event)
        return grouped


if __name__ == "__main__":
    unittest.main()
