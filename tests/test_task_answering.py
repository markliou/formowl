from __future__ import annotations

from hashlib import sha256
import re
import unittest

import _paths  # noqa: F401
from formowl_graph import (
    CandidateEvidenceAccessBinding,
    CandidateEvidenceIndex,
    CandidateEvidenceRecord,
    CandidateEvidenceTextPolicyBinding,
    CandidateEvidenceTextPolicyRuntime,
    EvidenceField,
    EvidenceRequirement,
    ProjectionSpec,
    TaskAnchor,
    TaskAnsweringEngine,
    TaskEvidenceObservation,
    TaskFrame,
    candidate_evidence_tokenizer_implementation_hash,
    revise_task_frame,
)


_TOKEN_RE = re.compile(r"[A-Za-z0-9_@.-]+|[\u3400-\u9fff]{2,12}")


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(value)}


def _hash(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


_RUNTIME_ID = "task_answering_test_runtime_v1"
_TEXT_RUNTIME = CandidateEvidenceTextPolicyRuntime(
    binding=CandidateEvidenceTextPolicyBinding(
        normalization_policy_version="unicode_nfkc_task_answering_test_v1",
        segmentation_policy_version="jieba_sentencepiece_task_answering_test_v1",
        candidate_admission_policy="frozen_profile_task_answering_test",
        candidate_admission_policy_hash=_hash("task-answering-admission"),
        sentencepiece_model_hash=_hash("task-answering-model"),
        sentencepiece_training_corpus_hash=_hash("task-answering-corpus"),
        query_tokenizer_runtime_id=_RUNTIME_ID,
        query_tokenizer_implementation_hash=(
            candidate_evidence_tokenizer_implementation_hash(_tokens)
        ),
    ),
    runtime_id=_RUNTIME_ID,
    tokenize_query=_tokens,
)


def _record(
    observation_id: str,
    *,
    source_item_id: str,
    tokens: set[str],
    observation_type: str,
    modality: str,
) -> CandidateEvidenceRecord:
    return CandidateEvidenceRecord(
        observation_id=observation_id,
        source_item_id=source_item_id,
        source_identity_policy_id="task_answering_logical_source_v1",
        source_version_id=f"source_version::{source_item_id}",
        permission_scope_id="permission_scope_task_answering",
        tokens=frozenset(tokens),
        observation_type=observation_type,
        modality=modality,
    )


def _task_observation(
    record: CandidateEvidenceRecord,
    *,
    fields: tuple[EvidenceField, ...],
    assertion_key: str | None = None,
    assertion_value: str | None = None,
) -> TaskEvidenceObservation:
    return TaskEvidenceObservation(
        observation_id=record.observation_id,
        source_identity_policy_id=record.source_identity_policy_id,
        source_item_id=record.source_item_id,
        fields=fields,
        citation_locator=f"formowl://observation/{record.observation_id}",
        assertion_key=assertion_key,
        assertion_value=assertion_value,
    )


def _engine(
    records: list[CandidateEvidenceRecord],
    observations: list[TaskEvidenceObservation],
) -> TaskAnsweringEngine:
    binding = CandidateEvidenceAccessBinding(
        binding_id="task_answering_access_v1",
        eligible_observation_ids=frozenset(record.observation_id for record in records),
        eligible_source_identity_policy_ids=frozenset(
            record.source_identity_policy_id for record in records
        ),
        eligible_permission_scope_ids=frozenset(record.permission_scope_id for record in records),
        eligible_source_version_ids=frozenset(record.source_version_id for record in records),
    )
    index = CandidateEvidenceIndex(
        records,
        text_policy_runtime=_TEXT_RUNTIME,
        access_binding=binding,
    )
    return TaskAnsweringEngine(index, observations)


def _frame(
    query_text: str,
    *,
    requirement: EvidenceRequirement | None = None,
    projection: ProjectionSpec | None = None,
) -> TaskFrame:
    return TaskFrame(
        task_frame_id="task_frame_test_v1",
        revision=1,
        retrieval_query_text=query_text,
        latest_utterance=query_text,
        anchors=(
            TaskAnchor(
                anchor_id="topic",
                anchor_type="topic",
                value=query_text,
            ),
        ),
        hard_constraints=(),
        evidence_requirement=requirement
        or EvidenceRequirement(
            requirement_id="evidence_requirement_test",
            cardinality_mode="all_matching",
        ),
        projection=projection or ProjectionSpec(),
    )


class TaskAnsweringMethodologyTests(unittest.TestCase):
    def test_mail_body_is_primary_and_headers_are_not_projected_by_default(
        self,
    ) -> None:
        header = _record(
            "obs_mail_header",
            source_item_id="mail_message_1",
            tokens={"shipment", "delay"},
            observation_type="email_header",
            modality="mail",
        )
        body = _record(
            "obs_mail_body",
            source_item_id="mail_message_1",
            tokens={"revised", "production", "schedule"},
            observation_type="email_body_segment",
            modality="mail",
        )
        engine = _engine(
            [header, body],
            [
                _task_observation(
                    header,
                    fields=(
                        EvidenceField("sender", "sender@example.test"),
                        EvidenceField("recipient", "recipient@example.test"),
                    ),
                ),
                _task_observation(
                    body,
                    fields=(
                        EvidenceField(
                            "content",
                            "The production schedule moved because qualification is incomplete.",
                        ),
                    ),
                ),
            ],
        )

        answer = engine.answer(_frame("shipment delay"))

        self.assertEqual(answer.answerability.status, "sufficient_evidence")
        self.assertEqual(answer.retrieval.selected_observation_ids, ("obs_mail_header",))
        self.assertEqual(
            set(answer.retrieval.assembled_observation_ids),
            {"obs_mail_header", "obs_mail_body"},
        )
        self.assertEqual(
            tuple(field.name for field in answer.projection.items[0].primary_fields),
            ("content",),
        )
        self.assertEqual(answer.projection.items[0].secondary_fields, ())
        projected_values = {
            field.value
            for field in answer.projection.items[0].primary_fields
            + answer.projection.items[0].secondary_fields
        }
        self.assertNotIn("sender@example.test", projected_values)
        self.assertNotIn("recipient@example.test", projected_values)

    def test_metadata_becomes_primary_only_when_projection_requests_it(self) -> None:
        record = _record(
            "obs_mail",
            source_item_id="mail_message_1",
            tokens={"shipment"},
            observation_type="email_message",
            modality="mail",
        )
        engine = _engine(
            [record],
            [
                _task_observation(
                    record,
                    fields=(
                        EvidenceField("content", "Shipment detail."),
                        EvidenceField("sender", "sender@example.test"),
                    ),
                )
            ],
        )

        answer = engine.answer(
            _frame(
                "shipment",
                projection=ProjectionSpec(primary_fields=("sender",)),
            )
        )

        self.assertEqual(len(answer.projection.items[0].primary_fields), 1)
        self.assertEqual(
            answer.projection.items[0].primary_fields[0].name,
            "sender",
        )

    def test_missing_primary_content_is_partial_not_a_metadata_substitute(self) -> None:
        record = _record(
            "obs_header_only",
            source_item_id="mail_message_header_only",
            tokens={"shipment"},
            observation_type="email_header",
            modality="mail",
        )
        engine = _engine(
            [record],
            [
                _task_observation(
                    record,
                    fields=(
                        EvidenceField("sender", "sender@example.test"),
                        EvidenceField("recipient", "recipient@example.test"),
                    ),
                )
            ],
        )

        answer = engine.answer(_frame("shipment"))

        self.assertEqual(answer.answerability.status, "partial_evidence")
        self.assertEqual(
            answer.coverage.missing_projection_fields,
            ("content",),
        )
        self.assertEqual(answer.projection.items[0].primary_fields, ())
        self.assertEqual(answer.projection.items[0].secondary_fields, ())

    def test_missing_normalized_observation_fields_are_reported_as_partial(
        self,
    ) -> None:
        header = _record(
            "obs_partial_header",
            source_item_id="mail_message_partial",
            tokens={"shipment"},
            observation_type="email_header",
            modality="mail",
        )
        body = _record(
            "obs_partial_body",
            source_item_id="mail_message_partial",
            tokens={"detail"},
            observation_type="email_body_segment",
            modality="mail",
        )
        engine = _engine(
            [header, body],
            [
                _task_observation(
                    header,
                    fields=(EvidenceField("sender", "sender@example.test"),),
                )
            ],
        )

        answer = engine.answer(_frame("shipment"))

        self.assertFalse(answer.coverage.assembly_complete)
        self.assertEqual(
            answer.coverage.expected_assembled_observation_count,
            2,
        )
        self.assertEqual(answer.coverage.assembled_observation_count, 1)
        self.assertEqual(answer.answerability.status, "partial_evidence")
        self.assertIn(
            "evidence_assembly_incomplete",
            answer.answerability.reason_codes,
        )

    def test_table_page_size_does_not_limit_all_matching_finance_coverage(self) -> None:
        records = [
            _record(
                f"obs_finance_{index:02d}",
                source_item_id=f"finance_row_{index:02d}",
                tokens={"variance", "forecast"},
                observation_type="spreadsheet_row",
                modality="xlsx",
            )
            for index in range(12)
        ]
        engine = _engine(
            records,
            [
                _task_observation(
                    record,
                    fields=(
                        EvidenceField(
                            "content",
                            f"Forecast variance row {index:02d}",
                        ),
                        EvidenceField("amount", str(index * 100)),
                    ),
                )
                for index, record in enumerate(records)
            ],
        )

        answer = engine.answer(
            _frame(
                "variance forecast",
                projection=ProjectionSpec(output_format="table", page_size=3),
            )
        )

        self.assertEqual(answer.coverage.total_source_item_count, 12)
        self.assertEqual(answer.coverage.returned_source_item_count, 12)
        self.assertTrue(answer.coverage.is_exhaustive)
        self.assertFalse(answer.coverage.has_more)
        self.assertEqual(answer.projection.displayed_source_item_count, 3)
        self.assertTrue(answer.projection.has_more)
        self.assertEqual(answer.answerability.status, "sufficient_evidence")

    def test_all_matching_budget_reports_partial_instead_of_silent_completion(
        self,
    ) -> None:
        records = [
            _record(
                f"obs_event_{index}",
                source_item_id=f"event_{index}",
                tokens={"inspection"},
                observation_type="application_event",
                modality="application",
            )
            for index in range(6)
        ]
        engine = _engine(
            records,
            [
                _task_observation(
                    record,
                    fields=(EvidenceField("content", f"Inspection {index}"),),
                )
                for index, record in enumerate(records)
            ],
        )

        answer = engine.answer(
            _frame("inspection"),
            retrieval_options={"source_item_budget": 4},
        )

        self.assertEqual(answer.coverage.total_source_item_count, 6)
        self.assertEqual(answer.coverage.returned_source_item_count, 4)
        self.assertFalse(answer.coverage.is_exhaustive)
        self.assertTrue(answer.coverage.has_more)
        self.assertEqual(answer.answerability.status, "partial_evidence")

    def test_target_found_but_requested_property_absent_is_distinct(self) -> None:
        record = _record(
            "obs_agreement",
            source_item_id="agreement_section_1",
            tokens={"agreement", "renewal"},
            observation_type="document_section",
            modality="pdf",
        )
        engine = _engine(
            [record],
            [
                _task_observation(
                    record,
                    fields=(
                        EvidenceField(
                            "content",
                            "This section discusses renewal but states no termination date.",
                        ),
                    ),
                )
            ],
        )

        answer = engine.answer(
            _frame(
                "agreement renewal",
                requirement=EvidenceRequirement(
                    requirement_id="termination_property",
                    cardinality_mode="all_matching",
                    requested_properties=("termination_date",),
                ),
            )
        )

        self.assertTrue(answer.coverage.target_found)
        self.assertEqual(
            answer.coverage.missing_properties,
            ("termination_date",),
        )
        self.assertEqual(answer.answerability.status, "property_absent")

    def test_conflicting_evidence_is_not_ordinary_multi_source_aggregation(
        self,
    ) -> None:
        first = _record(
            "obs_status_open",
            source_item_id="project_event_1",
            tokens={"status"},
            observation_type="project_event",
            modality="application",
        )
        second = _record(
            "obs_status_closed",
            source_item_id="project_event_2",
            tokens={"status"},
            observation_type="project_event",
            modality="application",
        )
        engine = _engine(
            [first, second],
            [
                _task_observation(
                    first,
                    fields=(EvidenceField("content", "Status is open."),),
                    assertion_key="state::status",
                    assertion_value="open",
                ),
                _task_observation(
                    second,
                    fields=(EvidenceField("content", "Status is closed."),),
                    assertion_key="state::status",
                    assertion_value="closed",
                ),
            ],
        )

        answer = engine.answer(_frame("status"))

        self.assertEqual(
            answer.coverage.conflicting_assertion_keys,
            ("state::status",),
        )
        self.assertEqual(answer.answerability.status, "conflicting_evidence")

    def test_projection_only_follow_up_preserves_task_semantics(self) -> None:
        original = _frame("shipment delay")

        revision = revise_task_frame(original, "我只想看到表格")

        self.assertEqual(revision.changed_dimensions, ("projection",))
        self.assertEqual(revision.task_frame.anchors, original.anchors)
        self.assertEqual(
            revision.task_frame.evidence_requirement,
            original.evidence_requirement,
        )
        self.assertEqual(
            revision.task_frame.retrieval_query_text,
            original.retrieval_query_text,
        )
        self.assertEqual(revision.task_frame.projection.output_format, "table")
        self.assertEqual(
            revision.task_frame.prior_task_frame_id,
            original.task_frame_id,
        )

    def test_anchor_refinement_revises_prior_frame_without_losing_context(self) -> None:
        original = _frame("shipment delay")
        refined = revise_task_frame(
            original,
            "只看第二季",
            anchor_updates=(
                TaskAnchor(
                    anchor_id="reporting_period",
                    anchor_type="context",
                    value="Q2",
                ),
            ),
        )

        self.assertEqual(
            tuple(anchor.anchor_id for anchor in refined.task_frame.anchors),
            ("topic", "reporting_period"),
        )
        self.assertEqual(
            refined.task_frame.retrieval_query_text,
            "shipment delay Q2",
        )
        self.assertIn("anchors", refined.changed_dimensions)
        self.assertIn("retrieval_query", refined.changed_dimensions)

    def test_same_method_contract_handles_document_table_and_event_shapes(self) -> None:
        shapes = (
            ("pdf", "document_section"),
            ("txt", "document_paragraph"),
            ("xlsx", "spreadsheet_row"),
            ("application", "application_event"),
        )
        for index, (modality, observation_type) in enumerate(shapes):
            with self.subTest(modality=modality):
                record = _record(
                    f"obs_shape_{index}",
                    source_item_id=f"source_shape_{index}",
                    tokens={"milestone"},
                    observation_type=observation_type,
                    modality=modality,
                )
                engine = _engine(
                    [record],
                    [
                        _task_observation(
                            record,
                            fields=(
                                EvidenceField(
                                    "content",
                                    f"Milestone evidence from {modality}.",
                                ),
                            ),
                        )
                    ],
                )

                answer = engine.answer(_frame("milestone"))

                self.assertEqual(
                    answer.answerability.status,
                    "sufficient_evidence",
                )
                self.assertEqual(answer.coverage.total_source_item_count, 1)
                self.assertTrue(answer.coverage.is_exhaustive)


if __name__ == "__main__":
    unittest.main()
