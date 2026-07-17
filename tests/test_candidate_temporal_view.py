from __future__ import annotations

from dataclasses import replace
import json
import unittest

import _paths
from formowl_contract import (
    ContractValidationError,
    Observation,
    TEMPORAL_CONTEXT_FIELDS,
    TemporalContext,
)
from formowl_graph import (
    DeterministicCandidateKnowledgeExtractor,
    DomainPackDefinition,
    build_candidate_temporal_view,
)


FIXTURE_ROOT = _paths.ROOT / "tests" / "fixtures" / "candidate_knowledge"


class CandidateTemporalViewTests(unittest.TestCase):
    def test_procurement_and_finance_map_domain_time_labels_to_one_core(self) -> None:
        results = {
            domain: _extract(domain)
            for domain in (
                "procurement",
                "finance",
            )
        }

        procurement_by_predicate = {
            assertion.predicate: assertion
            for assertion in results["procurement"].candidate_assertions
        }
        finance_by_predicate = {
            assertion.predicate: assertion for assertion in results["finance"].candidate_assertions
        }

        promised = procurement_by_predicate["promised_delivery_date"]
        self.assertEqual(promised.epistemic_status, "expected")
        self.assertEqual(
            promised.temporal_context,
            {
                "captured_at": "2026-07-15T01:00:00+00:00",
                "due_at": "2026-07-31",
                "recorded_at": "2026-07-15T01:00:00+00:00",
                "precision": "day",
            },
        )
        approval = finance_by_predicate["payment_approval"]
        self.assertEqual(approval.epistemic_status, "actual")
        self.assertEqual(
            approval.temporal_context,
            {
                "captured_at": "2026-07-15T03:00:00+00:00",
                "phenomenon_time": "2026-07-15T03:00:00+00:00",
                "recorded_at": "2026-07-15T03:00:00+00:00",
            },
        )
        for result in results.values():
            for assertion in result.candidate_assertions:
                self.assertTrue(set(assertion.temporal_context).issubset(TEMPORAL_CONTEXT_FIELDS))

    def test_bitemporal_candidate_view_blocks_future_knowledge_before_ranking(self) -> None:
        finance = _extract("finance")
        approval = next(
            assertion
            for assertion in finance.candidate_assertions
            if assertion.predicate == "payment_approval"
        )

        too_early = build_candidate_temporal_view(
            [approval],
            as_of_world_time="2026-07-15T02:59:59+00:00",
            known_as_of="2026-07-15T02:59:59+00:00",
        )
        visible = build_candidate_temporal_view(
            [approval],
            as_of_world_time="2026-07-15T03:00:00+00:00",
            known_as_of="2026-07-15T04:30:00+00:00",
            epistemic_statuses=["actual"],
        )

        self.assertEqual(too_early.candidate_assertions, [])
        self.assertIn(
            approval.candidate_assertion_id,
            too_early.excluded_assertion_ids_by_reason["known_as_of"],
        )
        self.assertEqual(visible.candidate_assertions, [approval])
        self.assertFalse(visible.canonical_write_allowed)

    def test_world_time_and_epistemic_status_are_independent_filters(self) -> None:
        procurement = _extract("procurement")
        promised = next(
            assertion
            for assertion in procurement.candidate_assertions
            if assertion.predicate == "promised_delivery_date"
        )

        before_due = build_candidate_temporal_view(
            [promised],
            as_of_world_time="2026-07-30",
            known_as_of="2026-07-16",
        )
        expected_view = build_candidate_temporal_view(
            [promised],
            as_of_world_time="2026-07-31",
            known_as_of="2026-07-16",
            epistemic_statuses=["expected"],
        )
        actual_only = build_candidate_temporal_view(
            [promised],
            as_of_world_time="2026-07-31",
            known_as_of="2026-07-16",
            epistemic_statuses=["actual"],
        )

        self.assertEqual(before_due.candidate_assertions, [promised])
        self.assertEqual(expected_view.candidate_assertions, [promised])
        self.assertEqual(actual_only.candidate_assertions, [])

    def test_world_observation_and_source_capture_are_separate_boundaries(
        self,
    ) -> None:
        finance = _extract("finance")
        payment_status = next(
            assertion
            for assertion in finance.candidate_assertions
            if assertion.predicate == "payment_status"
        )
        relation_without_recorded_time = next(
            assertion
            for assertion in finance.candidate_assertions
            if assertion.predicate == "belongs_to_cost_center"
        )

        before_observation = build_candidate_temporal_view(
            [payment_status],
            as_of_world_time="2026-07-14",
            known_as_of="2026-07-15T04:30:00+00:00",
        )
        before_source_capture = build_candidate_temporal_view(
            [relation_without_recorded_time],
            known_as_of="2026-07-15T01:59:59+00:00",
        )
        after_source_capture_before_materialization = build_candidate_temporal_view(
            [relation_without_recorded_time],
            known_as_of="2026-07-15T02:00:00+00:00",
        )
        at_materialization = build_candidate_temporal_view(
            [relation_without_recorded_time],
            known_as_of="2026-07-15T04:30:00+00:00",
        )

        self.assertEqual(before_observation.candidate_assertions, [])
        self.assertIn(
            payment_status.candidate_assertion_id,
            before_observation.excluded_assertion_ids_by_reason["as_of_world_time"],
        )
        self.assertEqual(before_source_capture.candidate_assertions, [])
        self.assertEqual(
            after_source_capture_before_materialization.candidate_assertions,
            [],
        )
        self.assertEqual(
            at_materialization.candidate_assertions,
            [relation_without_recorded_time],
        )

    def test_known_as_of_fails_closed_without_candidate_materialization_time(
        self,
    ) -> None:
        assertion = next(
            assertion
            for assertion in _extract("finance").candidate_assertions
            if assertion.predicate == "belongs_to_cost_center"
        )
        missing_materialization_time = replace(assertion, created_at=None)

        view = build_candidate_temporal_view(
            [missing_materialization_time],
            known_as_of="2026-07-16",
        )

        self.assertEqual(view.candidate_assertions, [])

    def test_known_as_of_fails_closed_without_source_knowledge_boundary(
        self,
    ) -> None:
        assertion = next(
            assertion
            for assertion in _extract("finance").candidate_assertions
            if assertion.predicate == "belongs_to_cost_center"
        )
        missing_source_knowledge_boundary = replace(assertion, temporal_context={})

        view = build_candidate_temporal_view(
            [missing_source_knowledge_boundary],
            known_as_of="2026-07-16",
        )

        self.assertEqual(view.candidate_assertions, [])

    def test_valid_and_recorded_intervals_filter_independently(self) -> None:
        payment_status = next(
            assertion
            for assertion in _extract("finance").candidate_assertions
            if assertion.predicate == "payment_status"
        )
        bounded = replace(
            payment_status,
            temporal_context={
                "valid_from": "2026-07-10",
                "valid_to": "2026-07-20",
                "recorded_from": "2026-07-15",
                "recorded_to": "2026-07-18",
            },
            created_at="2026-07-15T00:00:00+00:00",
        )

        inside = build_candidate_temporal_view(
            [bounded],
            as_of_world_time="2026-07-16",
            known_as_of="2026-07-16",
        )
        after_world_interval = build_candidate_temporal_view(
            [bounded],
            as_of_world_time="2026-07-21",
            known_as_of="2026-07-17",
        )
        after_recorded_interval = build_candidate_temporal_view(
            [bounded],
            as_of_world_time="2026-07-17",
            known_as_of="2026-07-19",
        )

        self.assertEqual(inside.candidate_assertions, [bounded])
        self.assertEqual(after_world_interval.candidate_assertions, [])
        self.assertEqual(after_recorded_interval.candidate_assertions, [])

    def test_lifecycle_is_independent_from_epistemic_status(self) -> None:
        delivery_change = next(
            assertion
            for assertion in _extract("procurement").candidate_assertions
            if assertion.predicate == "delivery_date_change"
        )
        actual_correction = replace(
            delivery_change,
            epistemic_status="actual",
            lifecycle_status="corrected",
        )

        view = build_candidate_temporal_view(
            [actual_correction],
            as_of_world_time="2026-07-31",
            known_as_of="2026-07-16",
            epistemic_statuses=["actual"],
            lifecycle_statuses=["corrected"],
        )

        self.assertEqual(view.candidate_assertions, [actual_correction])

    def test_timestamp_requires_explicit_offset(self) -> None:
        with self.assertRaises(ContractValidationError):
            TemporalContext.from_dict({"recorded_at": "2026-07-15T03:00:00"})


def _extract(domain: str):
    fixture = json.loads((FIXTURE_ROOT / f"{domain}.json").read_text())
    observations = [Observation.from_dict(observation) for observation in fixture["observations"]]
    return DeterministicCandidateKnowledgeExtractor().extract(
        observations,
        extractor_run_id=f"run_temporal_poc_{domain}",
        domain_pack=DomainPackDefinition.from_dict(fixture["domain_pack"]),
        created_at="2026-07-15T04:30:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
