from __future__ import annotations

from dataclasses import replace
import unittest

from formowl_kg_eval.evidence_answer import (
    EvidenceDocument,
    build_prediction_from_evidence,
    build_private_gold_from_evidence,
)
from formowl_kg_eval.structured_answer import score_structured_answer


class EvidenceStructuredAnswerTests(unittest.TestCase):
    def test_evidence_timestamps_are_normalized_to_utc(self) -> None:
        naive = EvidenceDocument(
            "obs_naive",
            "Shipment is blocked.",
            "2026-07-10T01:00:00",
        )
        zulu = EvidenceDocument(
            "obs_zulu",
            "Shipment is blocked.",
            "2026-07-10T01:00:00Z",
        )
        offset = EvidenceDocument(
            "obs_offset",
            "Shipment is blocked.",
            "2026-07-10T09:00:00+08:00",
        )

        self.assertEqual(naive.sent_at, "2026-07-10T01:00:00+00:00")
        self.assertEqual(zulu.sent_at, "2026-07-10T01:00:00+00:00")
        self.assertEqual(offset.sent_at, "2026-07-10T01:00:00+00:00")
        prediction = build_prediction_from_evidence(
            case_id="case_naive_time",
            result_kind="owner_match",
            query_text="What is blocked?",
            documents=(naive,),
        )
        self.assertEqual(prediction.latest_status.valid_from, naive.sent_at)

    def test_duplicate_lifecycle_sentences_keep_unique_event_bindings(self) -> None:
        documents = (
            EvidenceDocument(
                "obs_duplicate_lifecycle",
                "Shipment is blocked. Shipment is blocked.",
                "2026-07-10T01:00:00+00:00",
                thread_id="thread_procurement",
            ),
        )

        gold = build_private_gold_from_evidence(
            case_id="case_duplicate_lifecycle",
            result_kind="owner_match",
            query_text="What is blocked?",
            documents=documents,
        )
        prediction = build_prediction_from_evidence(
            case_id="case_duplicate_lifecycle",
            result_kind="owner_match",
            query_text="What is blocked?",
            documents=documents,
        )

        self.assertEqual(len(gold.lifecycle_bindings), 2)
        self.assertEqual(len(prediction.lifecycle_bindings), 2)
        self.assertEqual(
            len({item.binding_id for item in gold.lifecycle_bindings}),
            2,
        )
        self.assertEqual(
            len({item.binding_id for item in prediction.lifecycle_bindings}),
            2,
        )

    def test_independent_pipelines_recover_same_evidence_grounded_business_answer(self) -> None:
        documents = _business_documents()
        gold = build_private_gold_from_evidence(
            case_id="case_1",
            result_kind="owner_match",
            query_text="What blocks the shipment, who acts, and what is the deadline?",
            documents=documents,
        )
        prediction = build_prediction_from_evidence(
            case_id="case_1",
            result_kind="owner_match",
            query_text="What blocks the shipment, who acts, and what is the deadline?",
            documents=documents,
        )

        score = score_structured_answer(gold, prediction)

        self.assertEqual(score.overall_score, 1.0)
        self.assertEqual(gold.case_scope_id, "case_1")
        self.assertEqual(gold.thread_ids, ("thread_procurement",))
        self.assertEqual(gold.deadline_disclosure, "explicit")
        self.assertEqual(gold.responsible_parties[0].text, "May Chen")
        self.assertEqual(gold.dependencies[0].text, "signed customs documents")
        self.assertEqual(
            [item.state for item in gold.lifecycle_bindings],
            ["open", "resolved", "reopened"],
        )
        self.assertIsNotNone(gold.lifecycle_bindings[1].resolved_by)
        self.assertIsNotNone(gold.lifecycle_bindings[2].reopened_by)

    def test_query_prediction_does_not_copy_strict_gold_extraction(self) -> None:
        documents = (
            EvidenceDocument(
                "obs_query_action",
                "Shipment is blocked. Please send the customs packet by 2026-07-14 after legal approval.",
                "2026-07-13T01:00:00+00:00",
                thread_id="thread_procurement",
            ),
        )

        gold = build_private_gold_from_evidence(
            case_id="case_method_independence",
            result_kind="owner_match",
            query_text="What should we send after the shipment blocker?",
            documents=documents,
        )
        prediction = build_prediction_from_evidence(
            case_id="case_method_independence",
            result_kind="owner_match",
            query_text="What should we send after the shipment blocker?",
            documents=documents,
        )

        self.assertEqual(gold.next_actions, ())
        self.assertEqual(gold.deadlines, ())
        self.assertEqual(gold.dependencies, ())
        self.assertEqual(len(prediction.next_actions), 1)
        self.assertEqual(prediction.deadlines[0].text, "2026-07-14")
        self.assertEqual(prediction.dependencies[0].text, "legal approval")
        self.assertLess(score_structured_answer(gold, prediction).overall_score, 1.0)

    def test_sender_is_not_naively_promoted_to_responsible_party(self) -> None:
        documents = (
            EvidenceDocument(
                "obs_1",
                "Customs packet is blocked. The release date is unknown.",
                "2026-07-10T01:00:00+00:00",
                "alice@example.com",
                "thread_procurement",
            ),
        )

        gold = build_private_gold_from_evidence(
            case_id="case_sender",
            result_kind="owner_match",
            query_text="Who owns the blocker?",
            documents=documents,
        )

        self.assertEqual(gold.responsible_parties, ())
        self.assertNotIn("alice@example.com", str(gold.to_dict()))

    def test_missing_deadline_is_explicitly_disclosed(self) -> None:
        documents = (
            EvidenceDocument(
                "obs_action",
                "Customs packet is blocked. May Chen must escalate the customs packet.",
                "2026-07-10T01:00:00+00:00",
                thread_id="thread_procurement",
            ),
        )
        gold = build_private_gold_from_evidence(
            case_id="case_missing_deadline",
            result_kind="owner_match",
            query_text="What happens next?",
            documents=documents,
        )
        prediction = build_prediction_from_evidence(
            case_id="case_missing_deadline",
            result_kind="owner_match",
            query_text="What happens next?",
            documents=documents,
        )

        self.assertEqual(gold.deadlines, ())
        self.assertEqual(gold.deadline_disclosure, "missing")
        self.assertEqual(prediction.deadline_disclosure, "missing")
        self.assertEqual(score_structured_answer(gold, prediction).overall_score, 1.0)

    def test_wrong_selected_evidence_fails_without_reading_retrieval_status(self) -> None:
        gold = build_private_gold_from_evidence(
            case_id="case_2",
            result_kind="owner_match",
            query_text="What blocks the shipment?",
            documents=_business_documents(),
        )
        wrong_prediction = build_prediction_from_evidence(
            case_id="case_2",
            result_kind="owner_match",
            query_text="What blocks the shipment?",
            documents=(
                EvidenceDocument(
                    "obs_wrong",
                    "Marketing launch is complete. Dana must publish by 2026-07-20.",
                    "2026-07-12T02:00:00+00:00",
                    thread_id="thread_marketing",
                ),
            ),
        )

        score = score_structured_answer(gold, wrong_prediction)

        self.assertLess(score.overall_score, 0.5)
        self.assertEqual(score.dimensions["case_thread_scope"].f1, 0.0)
        self.assertEqual(score.dimensions["open_blockers"].recall, 0.0)

    def test_wrong_thread_prediction_cannot_reuse_valid_citation(self) -> None:
        documents = _business_documents()
        gold = build_private_gold_from_evidence(
            case_id="case_thread",
            result_kind="owner_match",
            query_text="What is the action?",
            documents=documents,
        )
        prediction = build_prediction_from_evidence(
            case_id="case_thread",
            result_kind="owner_match",
            query_text="What is the action?",
            documents=documents,
        )
        wrong_action = replace(prediction.next_actions[0], thread_id="thread_unrelated")

        score = score_structured_answer(
            gold,
            replace(prediction, next_actions=(wrong_action,)),
        )

        self.assertLess(score.dimensions["citations"].f1, 1.0)

    def test_no_match_and_denied_are_safe_only_without_answer_content(self) -> None:
        for result_kind in ("no_match", "permission_denied"):
            gold = build_private_gold_from_evidence(
                case_id="case_safe_" + result_kind,
                result_kind=result_kind,
                query_text="private query",
                documents=(),
            )
            prediction = build_prediction_from_evidence(
                case_id="case_safe_" + result_kind,
                result_kind=result_kind,
                query_text="private query",
                documents=(),
                permission_denied=result_kind == "permission_denied",
            )
            score = score_structured_answer(gold, prediction)
            self.assertEqual(score.overall_score, 1.0)


def _business_documents() -> tuple[EvidenceDocument, ...]:
    return (
        EvidenceDocument(
            "obs_open",
            "Customs packet is blocked. Release ETA is unconfirmed.",
            "2026-07-10T01:00:00+00:00",
            "alice@example.com",
            "thread_procurement",
        ),
        EvidenceDocument(
            "obs_resolved",
            "Customs packet is resolved.",
            "2026-07-11T01:00:00+00:00",
            "bob@example.com",
            "thread_procurement",
        ),
        EvidenceDocument(
            "obs_reopened",
            "Customs packet reopened. May Chen must escalate by 2026-07-12 and depends on signed customs documents.",
            "2026-07-12T01:00:00+00:00",
            "operations@example.com",
            "thread_procurement",
        ),
    )


if __name__ == "__main__":
    unittest.main()
