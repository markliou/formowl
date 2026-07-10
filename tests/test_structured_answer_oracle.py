from __future__ import annotations

from dataclasses import replace
import unittest

from formowl_contract import ContractValidationError, to_plain
from formowl_kg_eval.structured_answer import (
    GoldAction,
    GoldCitation,
    GoldFact,
    LifecycleBinding,
    PredictedAction,
    PredictedFact,
    PrivateStructuredAnswerGold,
    StructuredAnswerPrediction,
    score_structured_answer,
)


T0 = "2026-07-01T09:00:00+00:00"
T1 = "2026-07-02T09:00:00+00:00"
T2 = "2026-07-03T09:00:00+00:00"
SCOPE = "case_supply_001"
THREAD = "thread_procurement_001"


class StructuredAnswerOracleTests(unittest.TestCase):
    def test_prediction_round_trip_preserves_scoreable_contract(self) -> None:
        prediction = _perfect_prediction()
        rebuilt = StructuredAnswerPrediction.from_dict(to_plain(prediction))
        self.assertEqual(to_plain(rebuilt), to_plain(prediction))

    def test_perfect_answer_scores_business_dimensions(self) -> None:
        score = score_structured_answer(_answerable_gold(), _perfect_prediction())

        self.assertEqual(score.overall_score, 1.0)
        self.assertEqual(
            set(score.dimensions),
            {
                "case_thread_scope",
                "latest_status",
                "open_blockers",
                "blocker_history",
                "responsible_parties",
                "deadlines",
                "deadline_disclosure",
                "next_actions",
                "dependencies",
                "uncertainties",
                "action_links",
                "lifecycle_temporal",
                "citations",
            },
        )
        self.assertTrue(all(item.f1 == 1.0 for item in score.dimensions.values()))

    def test_stale_status_is_rejected(self) -> None:
        prediction = replace(
            _perfect_prediction(),
            latest_status=PredictedFact(
                "pred_status",
                "Shipment was awaiting customs review",
                ("cite_status_old",),
                T0,
                case_scope_id=SCOPE,
                thread_id=THREAD,
            ),
        )

        score = score_structured_answer(_answerable_gold(), prediction)

        self.assertEqual(score.dimensions["latest_status"].f1, 0.0)
        self.assertLess(score.overall_score, 1.0)

    def test_resolved_blocker_cannot_replace_reopened_lifecycle(self) -> None:
        prediction = replace(
            _perfect_prediction(),
            lifecycle_bindings=_perfect_prediction().lifecycle_bindings[:-1],
            open_blockers=(),
        )

        score = score_structured_answer(_answerable_gold(), prediction)

        self.assertLess(score.dimensions["lifecycle_temporal"].recall, 1.0)
        self.assertEqual(score.dimensions["open_blockers"].recall, 0.0)

    def test_wrong_owner_breaks_party_and_link_scores(self) -> None:
        wrong_owner = replace(
            _perfect_prediction().responsible_parties[0],
            text="Bob Lee",
        )
        prediction = replace(
            _perfect_prediction(),
            responsible_parties=(wrong_owner,),
        )

        score = score_structured_answer(_answerable_gold(), prediction)

        self.assertEqual(score.dimensions["responsible_parties"].f1, 0.0)
        self.assertLess(score.dimensions["action_links"].recall, 1.0)

    def test_wrong_deadline_breaks_deadline_and_link_scores(self) -> None:
        wrong_deadline = replace(
            _perfect_prediction().deadlines[0],
            text="2026-07-09",
        )
        prediction = replace(_perfect_prediction(), deadlines=(wrong_deadline,))

        score = score_structured_answer(_answerable_gold(), prediction)

        self.assertEqual(score.dimensions["deadlines"].f1, 0.0)
        self.assertLess(score.dimensions["action_links"].recall, 1.0)

    def test_unsupported_action_is_rejected_even_with_valid_retrieval(self) -> None:
        action = replace(
            _perfect_prediction().next_actions[0],
            text="Cancel the supplier contract immediately",
        )
        score = score_structured_answer(
            _answerable_gold(),
            replace(_perfect_prediction(), next_actions=(action,)),
        )

        self.assertEqual(score.dimensions["next_actions"].f1, 0.0)

    def test_wrong_thread_citation_is_not_entailing(self) -> None:
        action = replace(
            _perfect_prediction().next_actions[0],
            thread_id="thread_unrelated",
        )
        score = score_structured_answer(
            _answerable_gold(),
            replace(_perfect_prediction(), next_actions=(action,)),
        )

        self.assertLess(score.dimensions["citations"].f1, 1.0)
        self.assertEqual(score.dimensions["next_actions"].f1, 1.0)

    def test_missing_deadline_must_be_explicitly_disclosed(self) -> None:
        gold = _missing_deadline_gold()
        prediction = _missing_deadline_prediction()
        correct = score_structured_answer(gold, prediction)
        omitted = score_structured_answer(
            gold,
            replace(prediction, deadline_disclosure="not_applicable"),
        )

        self.assertEqual(correct.dimensions["deadline_disclosure"].f1, 1.0)
        self.assertEqual(omitted.dimensions["deadline_disclosure"].f1, 0.0)

    def test_dependency_mismatch_breaks_fact_and_link_scores(self) -> None:
        wrong_dependency = replace(
            _perfect_prediction().dependencies[0],
            text="marketing approval",
        )
        score = score_structured_answer(
            _answerable_gold(),
            replace(_perfect_prediction(), dependencies=(wrong_dependency,)),
        )

        self.assertEqual(score.dimensions["dependencies"].f1, 0.0)
        self.assertLess(score.dimensions["action_links"].recall, 1.0)

    def test_no_match_and_denied_require_zero_disclosure(self) -> None:
        for outcome in ("no_match", "permission_denied"):
            with self.subTest(outcome=outcome):
                gold = PrivateStructuredAnswerGold(case_id=f"case_{outcome}", outcome=outcome)
                safe = score_structured_answer(gold, StructuredAnswerPrediction(outcome=outcome))
                unsafe = score_structured_answer(
                    gold,
                    StructuredAnswerPrediction(
                        outcome=outcome,
                        uncertainties=(PredictedFact("leak", "A private thread may exist"),),
                    ),
                )
                self.assertEqual(safe.overall_score, 1.0)
                self.assertEqual(unsafe.overall_score, 0.0)

    def test_answerable_no_match_counts_scope_failure_in_micro_dimensions(self) -> None:
        score = score_structured_answer(
            _answerable_gold(),
            StructuredAnswerPrediction(outcome="no_match"),
        )

        scope = score.dimensions["case_thread_scope"]
        self.assertTrue(scope.applicable)
        self.assertEqual(scope.matched, 0)
        self.assertEqual(scope.expected, 1)
        self.assertEqual(scope.predicted, 0)
        self.assertEqual(scope.f1, 0.0)
        self.assertEqual(
            sum(dimension.expected for dimension in score.dimensions.values()),
            1
            + sum(
                dimension.expected
                for name, dimension in score.dimensions.items()
                if name != "case_thread_scope"
            ),
        )

    def test_private_gold_round_trip_and_reference_validation(self) -> None:
        gold = _answerable_gold()
        self.assertEqual(PrivateStructuredAnswerGold.from_dict(gold.to_dict()), gold)
        with self.assertRaises(ContractValidationError):
            replace(
                gold,
                next_actions=(replace(gold.next_actions[0], dependency_claim_ids=("unknown",)),),
            )


def _fact(claim_id: str, text: str, citation: str, valid_from: str) -> GoldFact:
    return GoldFact(
        claim_id,
        text,
        (citation,),
        valid_from,
        case_scope_id=SCOPE,
        thread_id=THREAD,
    )


def _pred(claim_id: str, text: str, citation: str, valid_from: str) -> PredictedFact:
    return PredictedFact(
        claim_id,
        text,
        (citation,),
        valid_from,
        case_scope_id=SCOPE,
        thread_id=THREAD,
    )


def _answerable_gold() -> PrivateStructuredAnswerGold:
    status = _fact("status_latest", "Shipment blocker reopened", "cite_reopen", T2)
    history = _fact("blocker_history", "Customs packet is incomplete", "cite_open", T0)
    blocker = _fact("blocker_open", "Shipment blocker reopened", "cite_reopen", T2)
    owner = _fact("owner_may", "May Chen", "cite_action", T2)
    deadline = _fact("deadline_friday", "2026-07-03", "cite_action", T2)
    dependency = _fact("dependency_docs", "signed customs documents", "cite_action", T2)
    action = GoldAction(
        **_fact(
            "action_escalate",
            "May Chen must escalate by 2026-07-03 and depends on signed customs documents",
            "cite_action",
            T2,
        ).__dict__,
        responsible_party_claim_ids=("owner_may",),
        deadline_claim_ids=("deadline_friday",),
        dependency_claim_ids=("dependency_docs",),
    )
    uncertainty = _fact("uncertainty_eta", "Release ETA is unconfirmed", "cite_reopen", T2)
    citations = (
        GoldCitation(
            "cite_open",
            "obs_open",
            ("blocker_history",),
            valid_from=T0,
            case_scope_id=SCOPE,
            thread_id=THREAD,
        ),
        GoldCitation(
            "cite_resolved",
            "obs_resolved",
            ("blocker_history",),
            valid_from=T1,
            case_scope_id=SCOPE,
            thread_id=THREAD,
        ),
        GoldCitation(
            "cite_reopen",
            "obs_reopen",
            ("status_latest", "blocker_open", "blocker_history", "uncertainty_eta"),
            valid_from=T2,
            case_scope_id=SCOPE,
            thread_id=THREAD,
        ),
        GoldCitation(
            "cite_action",
            "obs_action",
            ("owner_may", "deadline_friday", "dependency_docs", "action_escalate"),
            valid_from=T2,
            case_scope_id=SCOPE,
            thread_id=THREAD,
        ),
    )
    return PrivateStructuredAnswerGold(
        case_id=SCOPE,
        outcome="answerable",
        case_scope_id=SCOPE,
        thread_ids=(THREAD,),
        latest_status=status,
        open_blockers=(blocker,),
        blocker_history=(history,),
        responsible_parties=(owner,),
        deadlines=(deadline,),
        deadline_disclosure="explicit",
        next_actions=(action,),
        dependencies=(dependency,),
        uncertainties=(uncertainty,),
        citations=citations,
        lifecycle_bindings=(
            LifecycleBinding("life_open", "blocker_history", "open", T0, ("cite_open",)),
            LifecycleBinding(
                "life_resolved",
                "blocker_history",
                "resolved",
                T1,
                ("cite_resolved",),
                resolved_by="event_resolution",
            ),
            LifecycleBinding(
                "life_reopened",
                "blocker_history",
                "reopened",
                T2,
                ("cite_reopen",),
                reopened_by="event_reopen",
            ),
        ),
    )


def _perfect_prediction() -> StructuredAnswerPrediction:
    action = PredictedAction(
        **_pred(
            "pred_action",
            "May Chen must escalate by 2026-07-03 and depends on signed customs documents",
            "cite_action",
            T2,
        ).__dict__,
        responsible_party_claim_ids=("pred_owner",),
        deadline_claim_ids=("pred_deadline",),
        dependency_claim_ids=("pred_dependency",),
    )
    return StructuredAnswerPrediction(
        outcome="answerable",
        case_scope_id=SCOPE,
        thread_ids=(THREAD,),
        latest_status=_pred("pred_status", "Shipment blocker reopened", "cite_reopen", T2),
        open_blockers=(_pred("pred_blocker", "Shipment blocker reopened", "cite_reopen", T2),),
        blocker_history=(_pred("pred_history", "Customs packet is incomplete", "cite_open", T0),),
        responsible_parties=(_pred("pred_owner", "May Chen", "cite_action", T2),),
        deadlines=(_pred("pred_deadline", "2026-07-03", "cite_action", T2),),
        deadline_disclosure="explicit",
        next_actions=(action,),
        dependencies=(_pred("pred_dependency", "signed customs documents", "cite_action", T2),),
        uncertainties=(_pred("pred_uncertainty", "Release ETA is unconfirmed", "cite_reopen", T2),),
        lifecycle_bindings=(
            LifecycleBinding("pred_open", "pred_history", "open", T0, ("cite_open",)),
            LifecycleBinding(
                "pred_resolved",
                "pred_history",
                "resolved",
                T1,
                ("cite_resolved",),
                resolved_by="event_resolution",
            ),
            LifecycleBinding(
                "pred_reopened",
                "pred_history",
                "reopened",
                T2,
                ("cite_reopen",),
                reopened_by="event_reopen",
            ),
        ),
    )


def _missing_deadline_gold() -> PrivateStructuredAnswerGold:
    gold = _answerable_gold()
    action = replace(gold.next_actions[0], deadline_claim_ids=())
    citations = tuple(
        replace(
            citation,
            supported_claim_ids=tuple(
                claim_id
                for claim_id in citation.supported_claim_ids
                if claim_id != "deadline_friday"
            ),
        )
        for citation in gold.citations
    )
    return replace(
        gold,
        deadlines=(),
        deadline_disclosure="missing",
        next_actions=(action,),
        citations=citations,
    )


def _missing_deadline_prediction() -> StructuredAnswerPrediction:
    prediction = _perfect_prediction()
    action = replace(prediction.next_actions[0], deadline_claim_ids=())
    return replace(
        prediction,
        deadlines=(),
        deadline_disclosure="missing",
        next_actions=(action,),
    )


if __name__ == "__main__":
    unittest.main()
