from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import re
import unittest
from typing import Iterable

import _paths  # noqa: F401
from formowl_graph import (
    CandidateEvidenceAccessBinding,
    CandidateEvidenceIndex as _ProductionCandidateEvidenceIndex,
    CandidateEvidenceRecord,
    CandidateEvidenceTextPolicyBinding,
    CandidateEvidenceTextPolicyRuntime,
    candidate_evidence_tokenizer_implementation_hash,
    infer_evidence_ontology_signals,
)


def _hash(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


_TEST_QUERY_TERM_RE = re.compile(r"[A-Za-z0-9_@.-]+|[\u3400-\u9fff]{2,12}")


def _test_query_tokens(value: str) -> set[str]:
    return {token.lower() for token in _TEST_QUERY_TERM_RE.findall(value)}


TEST_QUERY_TOKENIZER_RUNTIME_ID = "candidate_evidence_test_runtime_v1"
TEST_TEXT_POLICY_BINDING = CandidateEvidenceTextPolicyBinding(
    normalization_policy_version="unicode_nfkc_test_v1",
    segmentation_policy_version="jieba_sentencepiece_protected_spans_test_v1",
    candidate_admission_policy="frozen_profile_candidate_admission_test",
    candidate_admission_policy_hash=_hash("test-admission"),
    sentencepiece_model_hash=_hash("test-sentencepiece-model"),
    sentencepiece_training_corpus_hash=_hash("test-training-corpus"),
    query_tokenizer_runtime_id=TEST_QUERY_TOKENIZER_RUNTIME_ID,
    query_tokenizer_implementation_hash=(
        candidate_evidence_tokenizer_implementation_hash(_test_query_tokens)
    ),
)
TEST_TEXT_POLICY_RUNTIME = CandidateEvidenceTextPolicyRuntime(
    binding=TEST_TEXT_POLICY_BINDING,
    runtime_id=TEST_QUERY_TOKENIZER_RUNTIME_ID,
    tokenize_query=_test_query_tokens,
)


class _TestBoundCandidateEvidenceIndex:
    def __init__(self, index: _ProductionCandidateEvidenceIndex) -> None:
        self._index = index

    def __getattr__(self, name):
        return getattr(self._index, name)

    def retrieve(self, **kwargs):
        query_tokens = kwargs.pop("query_tokens", None)
        kwargs.pop("query_policy_binding_hash", None)
        ontology_query_signals = kwargs.pop("ontology_query_signals", ())
        ontology_requested = ontology_query_signals != ()
        if ontology_requested:
            kwargs["enable_ontology_rerank"] = True
        if query_tokens is None:
            if not ontology_requested:
                return self._index.retrieve(**kwargs)
            return self._index.retrieve_ablation(
                **kwargs,
                ablation_id="test_explicit_ontology_signals",
                query_token_transform=lambda base: base,
                ontology_query_signal_transform=(
                    lambda _query_text, _tokens: frozenset(ontology_query_signals)
                ),
            )
        return self._index.retrieve_ablation(
            **kwargs,
            ablation_id="test_explicit_query_tokens",
            query_token_transform=lambda base: base | frozenset(query_tokens),
            ontology_query_signal_transform=(
                (lambda _query_text, _tokens: frozenset(ontology_query_signals))
                if ontology_requested
                else None
            ),
        )


def _record(
    observation_id: str,
    *,
    source_item_id: str,
    tokens: set[str],
    actor_tokens: set[str] | None = None,
    context_ids: set[str] | None = None,
    observed_at: str | None = None,
    known_at: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    epistemic_status: str | None = None,
    lifecycle_status: str | None = None,
    ontology_signals: set[str] | None = None,
    source_identity_policy_id: str = "test_logical_source_identity_v1",
    source_version_id: str | None = None,
    permission_scope_id: str = "permission_scope_test",
) -> CandidateEvidenceRecord:
    return CandidateEvidenceRecord(
        observation_id=observation_id,
        source_item_id=source_item_id,
        source_identity_policy_id=source_identity_policy_id,
        source_version_id=source_version_id or f"source_version::{source_item_id}",
        permission_scope_id=permission_scope_id,
        tokens=frozenset(tokens),
        actor_tokens=frozenset(actor_tokens or set()),
        context_ids=frozenset(context_ids or set()),
        observed_at=observed_at,
        known_at=known_at,
        valid_from=valid_from,
        valid_to=valid_to,
        epistemic_status=epistemic_status,
        lifecycle_status=lifecycle_status,
        ontology_signals=frozenset(ontology_signals or set()),
    )


def _access_binding(
    records: Iterable[CandidateEvidenceRecord],
    *,
    binding_id: str = "candidate_access_test",
) -> CandidateEvidenceAccessBinding:
    bounded = tuple(records)
    return CandidateEvidenceAccessBinding(
        binding_id=binding_id,
        eligible_observation_ids=frozenset(record.observation_id for record in bounded),
        eligible_source_identity_policy_ids=frozenset(
            record.source_identity_policy_id for record in bounded
        ),
        eligible_permission_scope_ids=frozenset(record.permission_scope_id for record in bounded),
        eligible_source_version_ids=frozenset(record.source_version_id for record in bounded),
    )


def CandidateEvidenceIndex(
    records: Iterable[CandidateEvidenceRecord],
    **kwargs,
) -> _TestBoundCandidateEvidenceIndex:
    bounded = tuple(records)
    kwargs.setdefault("access_binding", _access_binding(bounded))
    kwargs.setdefault("text_policy_runtime", TEST_TEXT_POLICY_RUNTIME)
    return _TestBoundCandidateEvidenceIndex(_ProductionCandidateEvidenceIndex(bounded, **kwargs))


def ProductionCandidateEvidenceIndex(
    records: Iterable[CandidateEvidenceRecord],
    **kwargs,
) -> _TestBoundCandidateEvidenceIndex:
    bounded = tuple(records)
    kwargs.setdefault("text_policy_runtime", TEST_TEXT_POLICY_RUNTIME)
    return _TestBoundCandidateEvidenceIndex(_ProductionCandidateEvidenceIndex(bounded, **kwargs))


class _FailOnIteration:
    def __iter__(self):
        raise AssertionError("query vocabulary must not be consumed before access")


class CandidateEvidenceIndexTests(unittest.TestCase):
    def test_evidence_record_rejects_whitespace_only_access_axis_ids(self) -> None:
        base = {
            "observation_id": "obs_a",
            "source_item_id": "record_a",
            "source_identity_policy_id": "identity_v1",
            "source_version_id": "version_v1",
            "permission_scope_id": "scope_v1",
            "tokens": frozenset({"variance"}),
        }
        for field_name in (
            "observation_id",
            "source_item_id",
            "source_identity_policy_id",
            "source_version_id",
            "permission_scope_id",
        ):
            with self.subTest(field_name=field_name):
                values = dict(base)
                values[field_name] = " \t "
                with self.assertRaises(ValueError):
                    CandidateEvidenceRecord(**values)

    def test_access_binding_rejects_whitespace_only_ids_on_every_axis(self) -> None:
        base = {
            "binding_id": "binding_v1",
            "eligible_observation_ids": frozenset({"obs_a"}),
            "eligible_source_identity_policy_ids": frozenset({"identity_v1"}),
            "eligible_permission_scope_ids": frozenset({"scope_v1"}),
            "eligible_source_version_ids": frozenset({"version_v1"}),
        }
        field_values = {
            "binding_id": " \t ",
            "eligible_observation_ids": frozenset({" \t "}),
            "eligible_source_identity_policy_ids": frozenset({" \t "}),
            "eligible_permission_scope_ids": frozenset({" \t "}),
            "eligible_source_version_ids": frozenset({" \t "}),
        }
        for field_name, invalid_value in field_values.items():
            with self.subTest(field_name=field_name):
                values = dict(base)
                values[field_name] = invalid_value
                with self.assertRaises(ValueError):
                    CandidateEvidenceAccessBinding(**values)

    def test_access_binding_requires_immutable_exact_string_collections(self) -> None:
        base = {
            "binding_id": "binding_v1",
            "eligible_observation_ids": frozenset({"obs_a"}),
            "eligible_source_identity_policy_ids": frozenset({"identity_v1"}),
            "eligible_permission_scope_ids": frozenset({"scope_v1"}),
            "eligible_source_version_ids": frozenset({"version_v1"}),
        }
        collection_fields = (
            "eligible_observation_ids",
            "eligible_source_identity_policy_ids",
            "eligible_permission_scope_ids",
            "eligible_source_version_ids",
        )
        for field_name in collection_fields:
            with self.subTest(field_name=field_name, invalid_kind="mutable_set"):
                values = dict(base)
                values[field_name] = {"mutable"}
                with self.assertRaisesRegex(ValueError, "must be a frozenset"):
                    CandidateEvidenceAccessBinding(**values)
            with self.subTest(field_name=field_name, invalid_kind="non_string"):
                values = dict(base)
                values[field_name] = frozenset({1})
                with self.assertRaisesRegex(
                    ValueError,
                    "must contain exact nonblank strings",
                ):
                    CandidateEvidenceAccessBinding(**values)

    def test_index_rejects_duck_typed_access_binding_during_construction(self) -> None:
        class DuckTypedAccessBinding:
            binding_id = "duck_binding"
            eligible_observation_ids = frozenset({"obs_a"})
            eligible_source_identity_policy_ids = frozenset({"identity_v1"})
            eligible_permission_scope_ids = frozenset({"scope_v1"})
            eligible_source_version_ids = frozenset({"version_v1"})

        with self.assertRaisesRegex(
            ValueError,
            "must use CandidateEvidenceAccessBinding",
        ):
            _ProductionCandidateEvidenceIndex(
                [_record("obs_a", source_item_id="record_a", tokens={"variance"})],
                text_policy_runtime=TEST_TEXT_POLICY_RUNTIME,
                access_binding=DuckTypedAccessBinding(),
            )

    def test_production_index_requires_a_structured_default_text_policy_runtime(
        self,
    ) -> None:
        records = [_record("obs_a", source_item_id="record_a", tokens={"variance"})]

        with self.assertRaisesRegex(ValueError, "text policy runtime is required"):
            _ProductionCandidateEvidenceIndex(records)

        with self.assertRaisesRegex(ValueError, "regex-only"):
            CandidateEvidenceTextPolicyBinding(
                normalization_policy_version="unicode_nfkc_test_v1",
                segmentation_policy_version="regex_only_test_v1",
                candidate_admission_policy="frozen_profile_candidate_admission_test",
                candidate_admission_policy_hash=_hash("test-admission"),
                sentencepiece_model_hash=_hash("test-sentencepiece-model"),
                sentencepiece_training_corpus_hash=_hash("test-training-corpus"),
                query_tokenizer_runtime_id=TEST_QUERY_TOKENIZER_RUNTIME_ID,
                query_tokenizer_implementation_hash=(
                    candidate_evidence_tokenizer_implementation_hash(_test_query_tokens)
                ),
                regex_only=True,
            )

        with self.assertRaisesRegex(ValueError, "SHA-256"):
            CandidateEvidenceTextPolicyBinding(
                normalization_policy_version="unicode_nfkc_test_v1",
                segmentation_policy_version="jieba_sentencepiece_test_v1",
                candidate_admission_policy="frozen_profile_candidate_admission_test",
                candidate_admission_policy_hash="sha256:placeholder",
                sentencepiece_model_hash=_hash("test-sentencepiece-model"),
                sentencepiece_training_corpus_hash=_hash("test-training-corpus"),
                query_tokenizer_runtime_id=TEST_QUERY_TOKENIZER_RUNTIME_ID,
                query_tokenizer_implementation_hash=(
                    candidate_evidence_tokenizer_implementation_hash(_test_query_tokens)
                ),
            )

    def test_text_policy_identity_and_runtime_code_binding_fail_closed(self) -> None:
        for field_name, invalid_value, expected_error in (
            (
                "normalization_policy_version",
                "not_unicode_not_nfkc_v1",
                "Unicode NFKC",
            ),
            (
                "segmentation_policy_version",
                "no_jieba_sentencepiece_v1",
                "Jieba and SentencePiece",
            ),
            (
                "candidate_admission_policy",
                "not_frozen_profile_candidate_admission",
                "frozen-profile",
            ),
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValueError, expected_error):
                    replace(
                        TEST_TEXT_POLICY_BINDING,
                        **{field_name: invalid_value},
                    )

        def different_query_tokens(value: str) -> set[str]:
            return set(value.lower().split())

        with self.assertRaisesRegex(ValueError, "runtime id mismatch"):
            CandidateEvidenceTextPolicyRuntime(
                binding=TEST_TEXT_POLICY_BINDING,
                runtime_id="different_candidate_evidence_runtime_v1",
                tokenize_query=_test_query_tokens,
            )

        with self.assertRaisesRegex(ValueError, "implementation hash mismatch"):
            CandidateEvidenceTextPolicyRuntime(
                binding=TEST_TEXT_POLICY_BINDING,
                runtime_id=TEST_QUERY_TOKENIZER_RUNTIME_ID,
                tokenize_query=different_query_tokens,
            )

        for field_name in (
            "protected_ascii_identifier_extraction",
            "jieba_segmentation",
            "corpus_bound_sentencepiece",
            "frozen_profile_admission",
            "regex_only",
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValueError, "flags must be booleans"):
                    replace(
                        TEST_TEXT_POLICY_BINDING,
                        **{field_name: "false"},
                    )

        class DuckTypedRuntime:
            binding = TEST_TEXT_POLICY_BINDING

            @staticmethod
            def tokenize(_value: str) -> frozenset[str]:
                return frozenset({"variance"})

        with self.assertRaisesRegex(
            ValueError,
            "must use CandidateEvidenceTextPolicyRuntime",
        ):
            _ProductionCandidateEvidenceIndex(
                [_record("obs_a", source_item_id="record_a", tokens={"variance"})],
                text_policy_runtime=DuckTypedRuntime(),
            )

    def test_production_index_requires_a_trusted_access_binding(self) -> None:
        index = ProductionCandidateEvidenceIndex(
            [_record("obs_a", source_item_id="record_a", tokens={"variance"})]
        )

        result = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "access_binding_required")

    def test_missing_binding_does_not_consume_query_vocabulary(self) -> None:
        index = ProductionCandidateEvidenceIndex(
            [_record("obs_a", source_item_id="record_a", tokens={"variance"})]
        )

        result = index.retrieve(
            query_text="variance",
            query_tokens=_FailOnIteration(),
            ontology_query_signals=_FailOnIteration(),
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "access_binding_required")

    def test_empty_effective_access_does_not_consume_query_vocabulary(self) -> None:
        records = [_record("obs_a", source_item_id="record_a", tokens={"variance"})]
        index = ProductionCandidateEvidenceIndex(
            records,
            access_binding=_access_binding(records),
        )
        denied_binding = CandidateEvidenceAccessBinding(
            binding_id="denied_binding",
            eligible_observation_ids=frozenset(),
            eligible_source_identity_policy_ids=frozenset(),
            eligible_permission_scope_ids=frozenset(),
            eligible_source_version_ids=frozenset(),
        )

        result = index.retrieve(
            query_text="variance",
            query_tokens=_FailOnIteration(),
            ontology_query_signals=_FailOnIteration(),
            access_binding=denied_binding,
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "no_accessible_evidence")

    def test_request_rejects_duck_typed_access_binding_cleanly(self) -> None:
        records = [_record("obs_a", source_item_id="record_a", tokens={"variance"})]
        index = ProductionCandidateEvidenceIndex(
            records,
            access_binding=_access_binding(records),
        )

        class DuckTypedAccessBinding:
            binding_id = "duck_binding"
            eligible_observation_ids = frozenset({"obs_a"})
            eligible_source_identity_policy_ids = frozenset({"test_logical_source_identity_v1"})
            eligible_permission_scope_ids = frozenset({"permission_scope_test"})
            eligible_source_version_ids = frozenset({"source_version::record_a"})

        result = index.retrieve(
            query_text="variance",
            access_binding=DuckTypedAccessBinding(),
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "invalid_access_binding")

    def test_default_query_tokens_are_owned_by_the_bound_runtime(self) -> None:
        records = [_record("obs_a", source_item_id="record_a", tokens={"variance"})]
        index = _ProductionCandidateEvidenceIndex(
            records,
            access_binding=_access_binding(records),
            text_policy_runtime=TEST_TEXT_POLICY_RUNTIME,
        )

        with self.assertRaises(TypeError):
            index.retrieve(
                query_text="variance",
                query_tokens={"regex-only-token"},
            )

        replaced_default = index.retrieve_ablation(
            query_text="variance",
            ablation_id="drop_normative_tokens",
            query_token_transform=lambda _base: {"regex-only-token"},
        )

        self.assertTrue(replaced_default.rejected)
        self.assertEqual(
            replaced_default.rejection_reason,
            "ablation_tokens_must_extend_default",
        )

    def test_specialized_plan_cannot_restore_runtime_rejected_raw_terms(self) -> None:
        records = [
            _record(
                "obs_raw_bypass",
                source_item_id="record_raw_bypass",
                tokens={"rawbypass"},
                observed_at="2026-05-01T00:00:00+00:00",
            )
        ]

        def admit_only_runtime_token(_value: str) -> set[str]:
            return {"admitted"}

        runtime_id = "candidate_evidence_runtime_admission_guard_v1"
        binding = replace(
            TEST_TEXT_POLICY_BINDING,
            query_tokenizer_runtime_id=runtime_id,
            query_tokenizer_implementation_hash=(
                candidate_evidence_tokenizer_implementation_hash(admit_only_runtime_token)
            ),
        )
        runtime = CandidateEvidenceTextPolicyRuntime(
            binding=binding,
            runtime_id=runtime_id,
            tokenize_query=admit_only_runtime_token,
        )
        index = _ProductionCandidateEvidenceIndex(
            records,
            access_binding=_access_binding(records),
            text_policy_runtime=runtime,
        )

        result = index.retrieve(query_text="Show the latest rawbypass record.")

        self.assertEqual(result.plan.intent, "chronology")
        self.assertEqual(result.plan.anchor_tokens, ())
        self.assertEqual(result.selected_observation_ids, ())
        self.assertTrue(result.rejected)
        self.assertEqual(
            result.rejection_reason,
            "insufficient_supported_evidence",
        )

    def test_context_and_time_admissibility_precede_query_tokenization(self) -> None:
        records = [
            _record(
                "obs_future",
                source_item_id="record_future",
                tokens={"variance"},
                context_ids={"period_q3"},
                known_at="2026-08-01T00:00:00+00:00",
            )
        ]

        def fail_query_tokens(_value: str):
            raise AssertionError("inadmissible evidence must not tokenize query text")

        runtime_id = "candidate_evidence_fail_if_tokenized_v1"
        binding = replace(
            TEST_TEXT_POLICY_BINDING,
            query_tokenizer_runtime_id=runtime_id,
            query_tokenizer_implementation_hash=(
                candidate_evidence_tokenizer_implementation_hash(fail_query_tokens)
            ),
        )
        runtime = CandidateEvidenceTextPolicyRuntime(
            binding=binding,
            runtime_id=runtime_id,
            tokenize_query=fail_query_tokens,
        )
        index = _ProductionCandidateEvidenceIndex(
            records,
            access_binding=_access_binding(records),
            text_policy_runtime=runtime,
        )

        result = index.retrieve(
            query_text="variance",
            accessible_context_ids={"period_q3"},
            query_context_ids={"period_q3"},
            known_as_of="2026-07-31T23:59:59+00:00",
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "no_admissible_evidence")

    def test_missing_access_binding_precedes_ontology_binding_diagnostics(self) -> None:
        index = ProductionCandidateEvidenceIndex(
            [_record("obs_a", source_item_id="record_a", tokens={"variance"})],
        )

        result = index.retrieve(
            query_text="variance",
            ontology_query_signals={"measurement"},
            ontology_revision_id="ontology_revision_missing",
            ontology_signal_vocabulary_hash="sha256:missing",
            ontology_contract_hash="sha256:missing",
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "access_binding_required")

    def test_numeric_identifier_is_not_inferred_as_measurement(self) -> None:
        signals = infer_evidence_ontology_signals(
            observation_type="erp_row",
            modality="erp",
            semantic_roles={"identifier"},
        )

        self.assertIn("structured_record_evidence", signals)
        self.assertNotIn("measurement_bearing_evidence", signals)

    def test_explicit_amount_or_quantity_role_is_measurement_evidence(self) -> None:
        amount_signals = infer_evidence_ontology_signals(
            observation_type="ledger_entry",
            modality="spreadsheet",
            semantic_roles={"currency_amount"},
        )
        quantity_signals = infer_evidence_ontology_signals(
            observation_type="inspection_event",
            modality="application",
            semantic_roles={"quantity"},
        )

        self.assertIn("measurement_bearing_evidence", amount_signals)
        self.assertIn("measurement_bearing_evidence", quantity_signals)

    def test_document_table_audio_and_event_inputs_have_distinct_facets(self) -> None:
        pdf = infer_evidence_ontology_signals(
            observation_type="document_page",
            modality="pdf",
        )
        slide = infer_evidence_ontology_signals(
            observation_type="slide",
            modality="pptx",
        )
        row = infer_evidence_ontology_signals(
            observation_type="erp_row",
            modality="erp",
        )
        audio = infer_evidence_ontology_signals(
            observation_type="audio_transcript",
            modality="audio",
        )
        event = infer_evidence_ontology_signals(
            observation_type="application_event",
            modality="application",
        )

        self.assertIn("document_evidence", pdf)
        self.assertIn("document_evidence", slide)
        self.assertIn("structured_record_evidence", row)
        self.assertIn("audio_visual_evidence", audio)
        self.assertIn("event_evidence", event)
        self.assertNotIn("document_evidence", row)
        self.assertNotIn("document_evidence", audio)
        self.assertNotIn("document_evidence", event)

    def test_chronology_selects_earliest_and_latest_distinct_source_items(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_middle",
                    source_item_id="record_middle",
                    tokens={"shipment", "eta"},
                    observed_at="2026-05-04T09:00:00+08:00",
                ),
                _record(
                    "obs_latest",
                    source_item_id="record_latest",
                    tokens={"shipment", "eta"},
                    observed_at="2026-05-03T23:30:00-04:00",
                ),
                _record(
                    "obs_earliest",
                    source_item_id="record_earliest",
                    tokens={"shipment", "eta"},
                    observed_at="2026-05-03T08:00:00+08:00",
                ),
            ]
        )

        result = index.retrieve(
            query_text="Show the earliest and latest shipment ETA updates.",
            query_tokens={"shipment", "eta"},
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.intent, "chronology")
        self.assertEqual(result.selected_observation_ids, ("obs_earliest", "obs_latest"))

    def test_actor_topic_requires_the_actor_and_topic_on_each_selected_item(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_alex_first",
                    source_item_id="record_1",
                    tokens={"defect", "inspection"},
                    actor_tokens={"alex"},
                ),
                _record(
                    "obs_alex_second",
                    source_item_id="record_2",
                    tokens={"defect", "inspection"},
                    actor_tokens={"alex"},
                ),
                _record(
                    "obs_other_actor",
                    source_item_id="record_3",
                    tokens={"defect", "inspection"},
                    actor_tokens={"sam"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="What did Alex report about the defect across multiple records?",
            query_tokens={"alex", "defect"},
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.intent, "actor_topic")
        self.assertEqual(
            set(result.selected_observation_ids),
            {"obs_alex_first", "obs_alex_second"},
        )

    def test_actor_topic_can_return_one_authoritative_source(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_alex",
                    source_item_id="record_1",
                    tokens={"defect"},
                    actor_tokens={"alex"},
                )
            ]
        )

        result = index.retrieve(
            query_text="What did Alex report about the defect?",
            query_tokens={"alex", "defect"},
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.minimum_source_items, 1)
        self.assertEqual(result.selected_observation_ids, ("obs_alex",))

    def test_conflict_uses_conjunctive_anchors_instead_of_token_union(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_budget_only",
                    source_item_id="record_budget",
                    tokens={"budget", "forecast"},
                ),
                _record(
                    "obs_forecast_only",
                    source_item_id="record_forecast",
                    tokens={"forecast", "variance"},
                ),
                _record(
                    "obs_both_a",
                    source_item_id="record_both_a",
                    tokens={"budget", "variance"},
                ),
                _record(
                    "obs_both_b",
                    source_item_id="record_both_b",
                    tokens={"budget", "variance"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="Reconcile the conflicting budget variance records.",
            query_tokens={"budget", "variance"},
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.anchor_tokens, ("budget", "variance"))
        self.assertEqual(
            set(result.selected_observation_ids),
            {"obs_both_a", "obs_both_b"},
        )

    def test_conflict_fails_closed_when_only_one_source_supports_both_anchors(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_only",
                    source_item_id="record_only",
                    tokens={"budget", "variance"},
                ),
                _record(
                    "obs_distractor",
                    source_item_id="record_distractor",
                    tokens={"budget"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="Reconcile the conflicting budget variance records.",
            query_tokens={"budget", "variance"},
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.plan.intent, "conflict")
        self.assertEqual(result.plan.minimum_source_items, 2)
        self.assertEqual(result.rejection_reason, "insufficient_supported_evidence")

    def test_multi_record_query_returns_two_distinct_source_items(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record("obs_a", source_item_id="row_a", tokens={"invoice", "hold"}),
                _record("obs_b", source_item_id="row_b", tokens={"invoice", "hold"}),
                _record("obs_c", source_item_id="row_c", tokens={"invoice"}),
            ]
        )

        result = index.retrieve(
            query_text="Summarize the invoice hold across multiple records.",
            query_tokens={"invoice", "hold"},
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.intent, "multi_record")
        self.assertEqual(set(result.selected_observation_ids), {"obs_a", "obs_b"})

    def test_no_match_rejects_without_supported_anchor(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record("obs_a", source_item_id="record_a", tokens={"invoice", "hold"}),
                _record("obs_b", source_item_id="record_b", tokens={"invoice", "hold"}),
            ]
        )

        result = index.retrieve(
            query_text="Find the approved decision and reconcile the lunar allocation.",
            query_tokens={"lunar", "allocation"},
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.plan.intent, "approval_decision")
        self.assertEqual(result.selected_observation_ids, ())

    def test_permission_filter_is_applied_before_query_planning(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record("obs_allowed", source_item_id="record_a", tokens={"invoice", "hold"}),
                _record("obs_denied", source_item_id="record_b", tokens={"invoice", "hold"}),
            ]
        )

        result = index.retrieve(
            query_text="Summarize the invoice hold across multiple records.",
            query_tokens={"invoice", "hold"},
            eligible_observation_ids={"obs_allowed"},
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.selected_observation_ids, ())

    def test_scope_version_and_identity_policy_filter_before_planning_and_idf(
        self,
    ) -> None:
        allowed = _record(
            "obs_allowed",
            source_item_id="record_allowed",
            tokens={"invoice", "variance"},
            source_identity_policy_id="table_row_identity_v1",
            source_version_id="version_allowed",
            permission_scope_id="scope_allowed",
        )
        denied_scope = _record(
            "obs_denied_scope",
            source_item_id="record_denied_scope",
            tokens={"secret"},
            source_identity_policy_id="table_row_identity_v1",
            source_version_id="version_denied_scope",
            permission_scope_id="scope_denied",
        )
        denied_version = _record(
            "obs_denied_version",
            source_item_id="record_denied_version",
            tokens={"secret"},
            source_identity_policy_id="table_row_identity_v1",
            source_version_id="version_denied",
            permission_scope_id="scope_allowed",
        )
        denied_policy = _record(
            "obs_denied_policy",
            source_item_id="record_denied_policy",
            tokens={"secret"},
            source_identity_policy_id="untrusted_chunk_identity_v1",
            source_version_id="version_allowed",
            permission_scope_id="scope_allowed",
        )
        records = (allowed, denied_scope, denied_version, denied_policy)
        binding = CandidateEvidenceAccessBinding(
            binding_id="access_scope_version_policy",
            eligible_observation_ids=frozenset(record.observation_id for record in records),
            eligible_source_identity_policy_ids=frozenset({"table_row_identity_v1"}),
            eligible_permission_scope_ids=frozenset({"scope_allowed"}),
            eligible_source_version_ids=frozenset({"version_allowed"}),
        )
        index = ProductionCandidateEvidenceIndex(records, access_binding=binding)

        allowed_result = index.retrieve(
            query_text="invoice variance",
            query_tokens={"invoice", "variance"},
        )
        denied_result = index.retrieve(
            query_text="secret",
            query_tokens={"secret"},
        )

        self.assertEqual(
            allowed_result.selected_observation_ids,
            ("obs_allowed",),
        )
        self.assertTrue(denied_result.rejected)
        self.assertEqual(denied_result.plan.anchor_tokens, ())

    def test_per_call_binding_cannot_broaden_an_index_binding(self) -> None:
        allowed = _record(
            "obs_allowed",
            source_item_id="record_allowed",
            tokens={"invoice"},
        )
        denied = _record(
            "obs_denied",
            source_item_id="record_denied",
            tokens={"secret"},
        )
        index = ProductionCandidateEvidenceIndex(
            (allowed, denied),
            access_binding=_access_binding((allowed,), binding_id="index_access"),
        )

        result = index.retrieve(
            query_text="secret",
            query_tokens={"secret"},
            access_binding=_access_binding(
                (allowed, denied),
                binding_id="broader_query_access",
            ),
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.selected_observation_ids, ())

    def test_denied_records_cannot_change_planning_or_ranking(self) -> None:
        allowed = [
            _record(
                "obs_allowed_a",
                source_item_id="record_a",
                tokens={"invoice", "variance"},
                observed_at="2026-05-01T08:00:00+00:00",
            ),
            _record(
                "obs_allowed_b",
                source_item_id="record_b",
                tokens={"invoice", "variance"},
                observed_at="2026-05-02T08:00:00+00:00",
            ),
        ]
        with_denied = CandidateEvidenceIndex(
            allowed
            + [
                _record(
                    "obs_denied_secret",
                    source_item_id="record_a",
                    tokens={"secret"},
                    actor_tokens={"private_actor"},
                    observed_at="2020-01-01T00:00:00+00:00",
                ),
                _record(
                    "obs_denied_rank",
                    source_item_id="record_c",
                    tokens={"invoice", "variance"},
                ),
            ]
        )
        allowed_only = CandidateEvidenceIndex(allowed)
        eligible_ids = {"obs_allowed_a", "obs_allowed_b"}

        expected = allowed_only.retrieve(
            query_text="Compare invoice variance across multiple records.",
            query_tokens={"invoice", "variance"},
            eligible_observation_ids=eligible_ids,
        )
        actual = with_denied.retrieve(
            query_text="Compare invoice variance across multiple records.",
            query_tokens={"invoice", "variance"},
            eligible_observation_ids=eligible_ids,
        )
        denied_anchor = with_denied.retrieve(
            query_text="Compare secret evidence across multiple records.",
            query_tokens={"secret"},
            eligible_observation_ids=eligible_ids,
        )

        self.assertEqual(actual.plan, expected.plan)
        self.assertEqual(actual.selected_observation_ids, expected.selected_observation_ids)
        self.assertTrue(denied_anchor.rejected)
        self.assertEqual(denied_anchor.plan.anchor_tokens, ())

    def test_ontology_bonus_can_rerank_but_cannot_remove_lexical_candidates(self) -> None:
        records = [
            _record(
                "obs_plain",
                source_item_id="record_plain",
                tokens={"variance"},
            ),
            _record(
                "obs_typed",
                source_item_id="record_typed",
                tokens={"variance"},
                ontology_signals={"measurement"},
            ),
        ]
        index = CandidateEvidenceIndex(
            records,
            ontology_revision_id="ontology_revision_1",
            ontology_signal_vocabulary_hash="sha256:signals",
            ontology_contract_hash="sha256:contract",
        )

        lexical = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            limit=2,
        )
        ontology = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            ontology_query_signals={"measurement"},
            ontology_revision_id="ontology_revision_1",
            ontology_signal_vocabulary_hash="sha256:signals",
            ontology_contract_hash="sha256:contract",
            limit=2,
        )

        self.assertEqual(set(lexical.selected_observation_ids), {"obs_plain", "obs_typed"})
        self.assertEqual(set(ontology.selected_observation_ids), {"obs_plain", "obs_typed"})
        self.assertEqual(ontology.selected_observation_ids[0], "obs_typed")

    def test_ontology_soft_rerank_also_applies_to_specialized_plans(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record("obs_a", source_item_id="record_a", tokens={"release"}),
                _record(
                    "obs_b",
                    source_item_id="record_b",
                    tokens={"release"},
                    ontology_signals={"event"},
                ),
                _record(
                    "obs_c",
                    source_item_id="record_c",
                    tokens={"release"},
                    ontology_signals={"event"},
                ),
            ],
            ontology_revision_id="ontology_revision_1",
            ontology_signal_vocabulary_hash="sha256:signals",
            ontology_contract_hash="sha256:contract",
        )

        lexical = index.retrieve(
            query_text="Compare release evidence across multiple records.",
            query_tokens={"release"},
            limit=2,
        )
        ontology = index.retrieve(
            query_text="Compare release evidence across multiple records.",
            query_tokens={"release"},
            ontology_query_signals={"event"},
            ontology_revision_id="ontology_revision_1",
            ontology_signal_vocabulary_hash="sha256:signals",
            ontology_contract_hash="sha256:contract",
            limit=2,
        )

        self.assertEqual(lexical.selected_observation_ids, ("obs_a", "obs_b"))
        self.assertEqual(ontology.selected_observation_ids, ("obs_b", "obs_c"))
        self.assertEqual(
            set(ontology.selected_observation_ids),
            {"obs_b", "obs_c"},
        )

    def test_ontology_signals_require_complete_bound_contract(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_a",
                    source_item_id="record_a",
                    tokens={"variance"},
                    ontology_signals={"measurement"},
                )
            ]
        )

        result = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            ontology_query_signals={"measurement"},
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "ontology_binding_required")

    def test_configured_ontology_bindings_fail_closed(self) -> None:
        index = CandidateEvidenceIndex(
            [_record("obs_a", source_item_id="record_a", tokens={"variance"})],
            ontology_revision_id="ontology_revision_1",
            ontology_signal_vocabulary_hash="sha256:signals",
            ontology_contract_hash="sha256:contract",
        )

        ontology_mismatch = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            ontology_query_signals={"measurement"},
            ontology_revision_id="ontology_revision_2",
            ontology_signal_vocabulary_hash="sha256:signals",
            ontology_contract_hash="sha256:contract",
        )
        ontology_contract_mismatch = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            ontology_query_signals={"measurement"},
            ontology_revision_id="ontology_revision_1",
            ontology_signal_vocabulary_hash="sha256:signals",
            ontology_contract_hash="sha256:other",
        )

        self.assertTrue(ontology_mismatch.rejected)
        self.assertEqual(
            ontology_mismatch.rejection_reason,
            "ontology_revision_mismatch",
        )
        self.assertTrue(ontology_contract_mismatch.rejected)
        self.assertEqual(
            ontology_contract_mismatch.rejection_reason,
            "ontology_contract_mismatch",
        )

    def test_time_context_and_status_admissibility_precede_planning(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_allowed",
                    source_item_id="row_allowed",
                    tokens={"variance"},
                    context_ids={"finance_period_q2"},
                    known_at="2026-05-02T08:00:00+00:00",
                    valid_from="2026-05-01T00:00:00+00:00",
                    valid_to="2026-05-31T23:59:59+00:00",
                    epistemic_status="actual",
                    lifecycle_status="active",
                ),
                _record(
                    "obs_future",
                    source_item_id="row_future",
                    tokens={"variance"},
                    context_ids={"finance_period_q2"},
                    known_at="2026-06-02T08:00:00+00:00",
                    valid_from="2026-06-01T00:00:00+00:00",
                    epistemic_status="forecast",
                    lifecycle_status="active",
                ),
                _record(
                    "obs_other_context",
                    source_item_id="quality_record",
                    tokens={"variance"},
                    context_ids={"inspection_lot_9"},
                    known_at="2026-05-01T08:00:00+00:00",
                    epistemic_status="actual",
                    lifecycle_status="superseded",
                ),
            ]
        )

        result = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            eligible_context_ids={"finance_period_q2"},
            known_as_of="2026-05-31T12:00:00+00:00",
            as_of_world_time="2026-05-15T12:00:00+00:00",
            allowed_epistemic_statuses={"actual"},
            allowed_lifecycle_statuses={"active"},
        )

        self.assertEqual(result.selected_observation_ids, ("obs_allowed",))

    def test_missing_known_time_fails_closed_when_knowledge_boundary_is_requested(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [_record("obs_unknown", source_item_id="row_unknown", tokens={"variance"})]
        )

        result = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            known_as_of="2026-05-31T12:00:00+00:00",
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.selected_observation_ids, ())

    def test_unknown_observation_time_cannot_become_latest_chronology_result(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_early",
                    source_item_id="record_early",
                    tokens={"release"},
                    observed_at="2026-05-01T08:00:00+00:00",
                ),
                _record(
                    "obs_late",
                    source_item_id="record_late",
                    tokens={"release"},
                    observed_at="2026-05-03T08:00:00+00:00",
                ),
                _record(
                    "obs_unknown",
                    source_item_id="record_unknown",
                    tokens={"release"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="Compare the earliest and latest records that mention release.",
            query_tokens={"release"},
        )

        self.assertEqual(result.selected_observation_ids, ("obs_early", "obs_late"))

    def test_latest_only_chronology_does_not_return_the_earliest_item(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_early",
                    source_item_id="record_early",
                    tokens={"release"},
                    observed_at="2026-05-01T08:00:00+00:00",
                ),
                _record(
                    "obs_late",
                    source_item_id="record_late",
                    tokens={"release"},
                    observed_at="2026-05-03T08:00:00+00:00",
                ),
            ]
        )

        result = index.retrieve(
            query_text="Show the latest release update.",
            query_tokens={"release"},
        )

        self.assertEqual(result.plan.chronology_mode, "latest")
        self.assertEqual(result.selected_observation_ids, ("obs_late",))

    def test_earliest_only_chronology_returns_one_earliest_item(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_early",
                    source_item_id="record_early",
                    tokens={"release"},
                    observed_at="2026-05-01T08:00:00+00:00",
                ),
                _record(
                    "obs_late",
                    source_item_id="record_late",
                    tokens={"release"},
                    observed_at="2026-05-03T08:00:00+00:00",
                ),
            ]
        )

        result = index.retrieve(
            query_text="Which release update was earliest?",
            query_tokens={"release"},
        )

        self.assertEqual(result.plan.chronology_mode, "earliest")
        self.assertEqual(result.selected_observation_ids, ("obs_early",))

    def test_after_boundary_returns_the_first_later_source_item(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_before",
                    source_item_id="record_before",
                    tokens={"release"},
                    observed_at="2026-05-01T08:00:00+00:00",
                ),
                _record(
                    "obs_after_first",
                    source_item_id="record_after_first",
                    tokens={"release"},
                    observed_at="2026-05-03T08:00:00+00:00",
                ),
                _record(
                    "obs_after_second",
                    source_item_id="record_after_second",
                    tokens={"release"},
                    observed_at="2026-05-04T08:00:00+00:00",
                ),
            ]
        )

        result = index.retrieve(
            query_text="Show the release update after 2026-05-02.",
            query_tokens={"release"},
            query_timezone="UTC",
        )

        self.assertEqual(result.plan.chronology_mode, "after")
        self.assertEqual(result.plan.chronology_boundary, "2026-05-02")
        self.assertEqual(result.selected_observation_ids, ("obs_after_first",))

    def test_date_boundary_uses_query_timezone_across_source_offsets(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_after_in_utc",
                    source_item_id="record_after",
                    tokens={"release"},
                    observed_at="2026-05-02T23:30:00-04:00",
                ),
                _record(
                    "obs_before_in_utc",
                    source_item_id="record_before",
                    tokens={"release"},
                    observed_at="2026-05-03T00:30:00+08:00",
                ),
            ]
        )

        result = index.retrieve(
            query_text="Show the release update after 2026-05-02.",
            query_tokens={"release"},
            query_timezone="UTC",
        )

        self.assertEqual(result.selected_observation_ids, ("obs_after_in_utc",))

    def test_date_boundary_without_query_timezone_fails_closed(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_release",
                    source_item_id="record_release",
                    tokens={"release"},
                    observed_at="2026-05-03T08:00:00+00:00",
                )
            ]
        )

        result = index.retrieve(
            query_text="Show the release update after 2026-05-02.",
            query_tokens={"release"},
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.selected_observation_ids, ())

    def test_before_boundary_returns_the_nearest_earlier_source_item(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_first",
                    source_item_id="record_first",
                    tokens={"release"},
                    observed_at="2026-05-01T08:00:00+00:00",
                ),
                _record(
                    "obs_second",
                    source_item_id="record_second",
                    tokens={"release"},
                    observed_at="2026-05-02T08:00:00+00:00",
                ),
                _record(
                    "obs_after",
                    source_item_id="record_after",
                    tokens={"release"},
                    observed_at="2026-05-03T08:00:00+00:00",
                ),
            ]
        )

        result = index.retrieve(
            query_text="Show the release update before 2026-05-03T00:00:00+00:00.",
            query_tokens={"release"},
        )

        self.assertEqual(result.plan.chronology_mode, "before")
        self.assertEqual(
            result.plan.chronology_boundary,
            "2026-05-03t00:00:00+00:00",
        )
        self.assertEqual(result.selected_observation_ids, ("obs_second",))

    def test_before_or_after_without_time_boundary_fails_closed(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_release",
                    source_item_id="record_release",
                    tokens={"release"},
                    observed_at="2026-05-01T08:00:00+00:00",
                )
            ]
        )

        result = index.retrieve(
            query_text="What happened after the release?",
            query_tokens={"release"},
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "insufficient_supported_evidence")

    def test_context_filter_isolates_one_deck_without_context_union(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_deck_a",
                    source_item_id="slide_a",
                    tokens={"release"},
                    context_ids={"deck_a"},
                ),
                _record(
                    "obs_deck_b",
                    source_item_id="slide_b",
                    tokens={"release"},
                    context_ids={"deck_b"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="release",
            query_tokens={"release"},
            eligible_context_ids={"deck_b"},
        )

        self.assertEqual(result.selected_observation_ids, ("obs_deck_b",))

    def test_actor_and_topic_can_be_proven_by_separate_observations_of_one_source(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_header",
                    source_item_id="quality_report_1",
                    tokens={"report"},
                    actor_tokens={"alex"},
                ),
                _record(
                    "obs_body",
                    source_item_id="quality_report_1",
                    tokens={"defect"},
                ),
                _record(
                    "obs_other_actor",
                    source_item_id="quality_report_2",
                    tokens={"defect"},
                    actor_tokens={"sam"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="What did Alex report about the defect?",
            query_tokens={"alex", "defect"},
            observation_budget=2,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(
            set(result.selected_observation_ids),
            {"obs_header", "obs_body"},
        )

    def test_accessible_contexts_do_not_define_the_query_context(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_period_1",
                    source_item_id="finance_row_1",
                    tokens={"variance"},
                    context_ids={"period_1"},
                ),
                _record(
                    "obs_period_2",
                    source_item_id="finance_row_2",
                    tokens={"variance"},
                    context_ids={"period_2"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            accessible_context_ids={"period_1", "period_2"},
            query_context_ids={"period_1"},
        )

        self.assertEqual(result.selected_observation_ids, ("obs_period_1",))

    def test_inaccessible_query_context_fails_closed(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_period_2",
                    source_item_id="finance_row_2",
                    tokens={"variance"},
                    context_ids={"period_2"},
                )
            ]
        )

        result = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            accessible_context_ids={"period_1"},
            query_context_ids={"period_2"},
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "query_context_not_accessible")

    def test_multiple_query_contexts_require_explicit_comparison_authorization(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_period_1",
                    source_item_id="finance_row_1",
                    tokens={"variance"},
                    context_ids={"period_1"},
                ),
                _record(
                    "obs_period_2",
                    source_item_id="finance_row_2",
                    tokens={"variance"},
                    context_ids={"period_2"},
                ),
            ]
        )

        rejected = index.retrieve(
            query_text="Compare variance across multiple records.",
            query_tokens={"variance"},
            accessible_context_ids={"period_1", "period_2"},
            query_context_ids={"period_1", "period_2"},
        )
        allowed = index.retrieve(
            query_text="Compare variance across multiple records.",
            query_tokens={"variance"},
            source_item_budget=2,
            observation_budget=2,
            accessible_context_ids={"period_1", "period_2"},
            query_context_ids={"period_1", "period_2"},
            allow_cross_context_comparison=True,
        )

        self.assertTrue(rejected.rejected)
        self.assertEqual(
            rejected.rejection_reason,
            "cross_context_comparison_not_allowed",
        )
        self.assertFalse(allowed.rejected)
        self.assertEqual(
            set(allowed.selected_observation_ids),
            {"obs_period_1", "obs_period_2"},
        )

    def test_cross_context_authorization_requires_an_actual_boolean(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_period_1",
                    source_item_id="finance_row_1",
                    tokens={"variance"},
                    context_ids={"period_1"},
                ),
                _record(
                    "obs_period_2",
                    source_item_id="finance_row_2",
                    tokens={"variance"},
                    context_ids={"period_2"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="Compare variance across multiple records.",
            query_tokens={"variance"},
            source_item_budget=2,
            observation_budget=2,
            accessible_context_ids={"period_1", "period_2"},
            query_context_ids={"period_1", "period_2"},
            allow_cross_context_comparison="false",
        )

        self.assertTrue(result.rejected)
        self.assertEqual(
            result.rejection_reason,
            "invalid_cross_context_comparison_authorization",
        )

    def test_multiple_accessible_contexts_require_an_explicit_query_context(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_period_1",
                    source_item_id="finance_row_1",
                    tokens={"variance"},
                    context_ids={"period_1"},
                ),
                _record(
                    "obs_period_2",
                    source_item_id="finance_row_2",
                    tokens={"variance"},
                    context_ids={"period_2"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="Compare variance across multiple records.",
            query_tokens={"variance"},
            accessible_context_ids={"period_1", "period_2"},
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "query_context_required")

    def test_split_observations_can_jointly_support_one_logical_source_item(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_page_a_budget",
                    source_item_id="pdf_page_a",
                    tokens={"budget"},
                ),
                _record(
                    "obs_page_a_variance",
                    source_item_id="pdf_page_a",
                    tokens={"variance"},
                ),
                _record(
                    "obs_page_b_both",
                    source_item_id="pdf_page_b",
                    tokens={"budget", "variance"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="Find budget variance across two pages.",
            query_tokens={"budget", "variance"},
            limit=5,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.target_source_items, 2)
        self.assertEqual(
            set(result.selected_observation_ids),
            {"obs_page_a_budget", "obs_page_a_variance", "obs_page_b_both"},
        )

    def test_numeric_identifier_does_not_change_requested_evidence_cardinality(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_first",
                    source_item_id="record_first",
                    tokens={"release"},
                    actor_tokens={"01-sd16004"},
                ),
                _record(
                    "obs_second",
                    source_item_id="record_second",
                    tokens={"release"},
                    actor_tokens={"01-sd16004"},
                ),
            ]
        )

        result = index.retrieve(
            query_text=("What did 01-sd16004 say across multiple records about release?"),
            query_tokens={"01-sd16004", "release"},
        )

        self.assertEqual(result.plan.target_source_items, 2)
        self.assertEqual(len(result.selected_observation_ids), 2)

    def test_compact_alphanumeric_identifier_is_not_evidence_cardinality(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"record_{item}",
                    tokens={"variance"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text="Review PO12345 across reports about variance.",
            query_tokens={"variance"},
            source_item_budget=5,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.target_source_items, 2)

    def test_labeled_numeric_identifier_is_not_evidence_cardinality(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"record_{item}",
                    tokens={"variance"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text="Review invoice number 12345 across reports about variance.",
            query_tokens={"variance"},
            source_item_budget=5,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.target_source_items, 2)

    def test_business_record_labels_keep_numeric_ids_out_of_cardinality(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"record_{item}",
                    tokens={"variance"},
                )
                for item in range(4)
            ]
        )

        for query_text in (
            "Find lot 123 reports about variance.",
            "Find invoice 123 records about variance.",
            "Find batch 42 reports about variance.",
            "找出批次 42 的 variance 報告。",
        ):
            with self.subTest(query_text=query_text):
                result = index.retrieve(
                    query_text=query_text,
                    query_tokens={"variance"},
                    source_item_budget=5,
                )

                self.assertFalse(result.rejected)
                self.assertEqual(result.plan.target_source_items, 1)

    def test_explicit_three_record_request_returns_three_logical_sources(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(f"obs_{index}", source_item_id=f"row_{index}", tokens={"variance"})
                for index in range(4)
            ]
        )

        result = index.retrieve(
            query_text="Compare variance across three records.",
            query_tokens={"variance"},
            limit=5,
        )

        self.assertEqual(result.plan.target_source_items, 3)
        self.assertEqual(len(result.selected_observation_ids), 3)

    def test_explicit_three_inspection_reports_is_source_neutral_cardinality(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"inspection_report_{item}",
                    tokens={"defect"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text="Review three inspection reports about the defect.",
            query_tokens={"defect"},
            source_item_budget=3,
            observation_budget=3,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.intent, "multi_record")
        self.assertEqual(result.plan.target_source_items, 3)
        self.assertEqual(len(result.selected_observation_ids), 3)

    def test_explicit_three_lots_is_source_neutral_cardinality(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"quality_lot_{item}",
                    tokens={"variance"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text="Compare variance in three lots.",
            query_tokens={"variance"},
            source_item_budget=3,
            observation_budget=3,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.target_source_items, 3)
        self.assertEqual(len(result.selected_observation_ids), 3)

    def test_chinese_explicit_three_items_preserves_cardinality(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"finance_record_{item}",
                    tokens={"發票差異"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text="彙整三筆發票差異。",
            query_tokens={"發票差異"},
            source_item_budget=3,
            observation_budget=3,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.target_source_items, 3)
        self.assertEqual(len(result.selected_observation_ids), 3)

    def test_chinese_generic_classifier_requires_a_source_noun(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"quality_report_{item}",
                    tokens={"品質異常"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text="彙整三個品質檢驗報告中的品質異常。",
            query_tokens={"品質異常"},
            source_item_budget=3,
            observation_budget=3,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.target_source_items, 3)
        self.assertEqual(len(result.selected_observation_ids), 3)

    def test_chinese_period_report_nouns_remain_evidence_cardinality(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"report_{item}",
                    tokens={"風險"},
                )
                for item in range(4)
            ]
        )

        for report_name in ("日報", "週報", "月報", "季報", "年報"):
            with self.subTest(report_name=report_name):
                result = index.retrieve(
                    query_text=f"比較三個{report_name}中的風險。",
                    query_tokens={"風險"},
                    source_item_budget=3,
                    observation_budget=3,
                )

                self.assertFalse(result.rejected)
                self.assertEqual(result.plan.target_source_items, 3)
                self.assertEqual(len(result.selected_observation_ids), 3)

    def test_chinese_month_duration_is_not_evidence_cardinality(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"quality_record_{item}",
                    tokens={"品質異常"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text="彙整最近三個月的品質異常紀錄。",
            query_tokens={"品質異常"},
            source_item_budget=5,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.target_source_items, 1)

    def test_chinese_workday_duration_is_not_evidence_cardinality(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"quality_record_{item}",
                    tokens={"延遲"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text="三個工作天內回報的延遲是什麼？",
            query_tokens={"延遲"},
            source_item_budget=5,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.target_source_items, 1)

    def test_structured_cardinality_hint_supports_future_query_parsers(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"future_modality_item_{item}",
                    tokens={"variance"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            requested_source_item_count=3,
            source_item_budget=3,
            observation_budget=3,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.intent, "multi_record")
        self.assertEqual(result.plan.target_source_items, 3)
        self.assertEqual(len(result.selected_observation_ids), 3)

    def test_invalid_structured_cardinality_hint_fails_closed(self) -> None:
        index = CandidateEvidenceIndex(
            [_record("obs_a", source_item_id="record_a", tokens={"variance"})]
        )

        result = index.retrieve(
            query_text="variance",
            query_tokens={"variance"},
            requested_source_item_count=0,
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.rejection_reason, "invalid_evidence_cardinality")

    def test_duration_number_does_not_become_evidence_cardinality(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_a",
                    source_item_id="record_a",
                    tokens={"delay"},
                ),
                _record(
                    "obs_b",
                    source_item_id="record_b",
                    tokens={"delay"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="What delay was reported within three days?",
            query_tokens={"delay"},
        )

        self.assertEqual(result.plan.target_source_items, 1)
        self.assertEqual(len(result.selected_observation_ids), 1)

    def test_modified_duration_number_does_not_become_evidence_cardinality(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"record_{item}",
                    tokens={"delay"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text=("What delay was reported within three business days across reports?"),
            query_tokens={"delay"},
            source_item_budget=5,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.target_source_items, 2)
        self.assertEqual(len(result.selected_observation_ids), 2)

    def test_explicit_cardinality_larger_than_budget_fails_closed(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"record_{item}",
                    tokens={"variance"},
                )
                for item in range(4)
            ]
        )

        result = index.retrieve(
            query_text="Review three reports about variance.",
            query_tokens={"variance"},
            source_item_budget=2,
            observation_budget=3,
        )

        self.assertTrue(result.rejected)
        self.assertEqual(result.plan.target_source_items, 3)
        self.assertEqual(result.rejection_reason, "evidence_budget_exhausted")

    def test_same_source_id_under_different_identity_policies_stays_distinct(
        self,
    ) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_pdf",
                    source_item_id="item_1",
                    source_identity_policy_id="pdf_page_identity_v1",
                    tokens={"variance"},
                ),
                _record(
                    "obs_sheet",
                    source_item_id="item_1",
                    source_identity_policy_id="spreadsheet_row_identity_v1",
                    tokens={"variance"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="Compare variance across two records.",
            query_tokens={"variance"},
            source_item_budget=2,
            observation_budget=2,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(index.source_item_count, 2)
        self.assertEqual(
            set(result.selected_observation_ids),
            {"obs_pdf", "obs_sheet"},
        )

    def test_three_item_chronology_range_returns_three_ordered_sources(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_{item}",
                    source_item_id=f"record_{item}",
                    tokens={"release"},
                    observed_at=f"2026-05-0{item}T08:00:00+00:00",
                )
                for item in range(1, 6)
            ]
        )

        result = index.retrieve(
            query_text="Show the release timeline across three records.",
            query_tokens={"release"},
            source_item_budget=3,
            observation_budget=3,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.chronology_mode, "range")
        self.assertEqual(
            result.selected_observation_ids,
            ("obs_1", "obs_3", "obs_5"),
        )

    def test_source_item_and_observation_budgets_are_independent(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    f"obs_page_{page}_budget",
                    source_item_id=f"pdf_page_{page}",
                    tokens={"budget"},
                )
                for page in range(3)
            ]
            + [
                _record(
                    f"obs_page_{page}_variance",
                    source_item_id=f"pdf_page_{page}",
                    tokens={"variance"},
                )
                for page in range(3)
            ]
        )

        enough = index.retrieve(
            query_text="Find budget variance across three pages.",
            query_tokens={"budget", "variance"},
            source_item_budget=3,
            observation_budget=6,
        )
        too_small = index.retrieve(
            query_text="Find budget variance across three pages.",
            query_tokens={"budget", "variance"},
            source_item_budget=3,
            observation_budget=5,
        )

        self.assertFalse(enough.rejected)
        self.assertEqual(enough.plan.target_source_items, 3)
        self.assertEqual(len(enough.selected_observation_ids), 6)
        self.assertTrue(too_small.rejected)
        self.assertEqual(too_small.selected_observation_ids, ())

    def test_non_actor_query_does_not_treat_domain_term_as_actor_filter(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_a",
                    source_item_id="record_a",
                    tokens={"account", "customer", "sales"},
                ),
                _record(
                    "obs_b",
                    source_item_id="record_b",
                    tokens={"account", "customer", "sales"},
                ),
                _record(
                    "obs_sender_only",
                    source_item_id="record_sender",
                    tokens={"other"},
                    actor_tokens={"sales"},
                ),
            ]
        )

        result = index.retrieve(
            query_text=(
                "Find possible sales tension between account and customer "
                "across separate records."
            ),
            query_tokens={"sales", "account", "customer"},
        )

        self.assertFalse(result.rejected)
        self.assertEqual(set(result.selected_observation_ids), {"obs_a", "obs_b"})

    def test_chinese_actor_topic_uses_the_same_source_neutral_plan(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_quality_a",
                    source_item_id="inspection_record_a",
                    tokens={"品質異常"},
                    actor_tokens={"王小美"},
                ),
                _record(
                    "obs_quality_b",
                    source_item_id="inspection_record_b",
                    tokens={"品質異常"},
                    actor_tokens={"王小美"},
                ),
                _record(
                    "obs_other_actor",
                    source_item_id="inspection_record_c",
                    tokens={"品質異常"},
                    actor_tokens={"其他人"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="王小美在多筆紀錄中提到什麼品質異常？",
            query_tokens={"王小美", "品質異常"},
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.intent, "actor_topic")
        self.assertEqual(
            set(result.selected_observation_ids),
            {"obs_quality_a", "obs_quality_b"},
        )

    def test_chinese_chronology_uses_normalized_timestamps(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_late",
                    source_item_id="quality_lot_late",
                    tokens={"批次", "檢驗結果"},
                    observed_at="2026-05-03T08:00:00+08:00",
                ),
                _record(
                    "obs_early",
                    source_item_id="quality_lot_early",
                    tokens={"批次", "檢驗結果"},
                    observed_at="2026-05-01T08:00:00+08:00",
                ),
            ]
        )

        result = index.retrieve(
            query_text="找出批次檢驗結果最早與最新的紀錄。",
            query_tokens={"批次", "檢驗結果"},
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.intent, "chronology")
        self.assertEqual(result.selected_observation_ids, ("obs_early", "obs_late"))

    def test_chinese_multi_record_question_keeps_explicit_cardinality(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record(
                    "obs_finance_a",
                    source_item_id="finance_row_a",
                    tokens={"發票", "凍結"},
                ),
                _record(
                    "obs_finance_b",
                    source_item_id="finance_row_b",
                    tokens={"發票", "凍結"},
                ),
            ]
        )

        result = index.retrieve(
            query_text="彙整多筆發票凍結紀錄。",
            query_tokens={"發票", "凍結"},
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.plan.intent, "multi_record")
        self.assertEqual(result.plan.target_source_items, 2)
        self.assertEqual(
            set(result.selected_observation_ids),
            {"obs_finance_a", "obs_finance_b"},
        )

    def test_logical_source_idf_is_invariant_to_observation_chunk_count(self) -> None:
        base_records = [
            _record("obs_alpha", source_item_id="document_a", tokens={"alpha"}),
            _record("obs_beta_b", source_item_id="document_b", tokens={"beta"}),
            _record("obs_beta_c", source_item_id="document_c", tokens={"beta"}),
        ]
        chunked_records = base_records + [
            _record(
                f"zz_chunk_{index:03d}",
                source_item_id="document_a",
                tokens={"alpha"},
            )
            for index in range(100)
        ]

        base = CandidateEvidenceIndex(base_records).retrieve(
            query_text="alpha beta",
            query_tokens={"alpha", "beta"},
            limit=1,
        )
        chunked = CandidateEvidenceIndex(chunked_records).retrieve(
            query_text="alpha beta",
            query_tokens={"alpha", "beta"},
            limit=1,
        )

        self.assertEqual(base.selected_observation_ids, ("obs_alpha",))
        self.assertEqual(chunked.selected_observation_ids, base.selected_observation_ids)

    def test_general_query_ranks_logical_sources_before_observation_chunks(self) -> None:
        index = CandidateEvidenceIndex(
            [
                _record("obs_a_1", source_item_id="document_a", tokens={"release"}),
                _record("obs_a_2", source_item_id="document_a", tokens={"release"}),
                _record("obs_a_3", source_item_id="document_a", tokens={"release"}),
                _record("obs_b", source_item_id="document_b", tokens={"release"}),
                _record("obs_c", source_item_id="document_c", tokens={"release"}),
            ]
        )

        result = index.retrieve(
            query_text="release",
            query_tokens={"release"},
            limit=3,
        )

        self.assertEqual(
            set(result.selected_observation_ids),
            {"obs_a_1", "obs_b", "obs_c"},
        )

    def test_context_boundary_is_shared_by_finance_quality_pdf_and_ppt(self) -> None:
        contexts = {
            "finance_period_q2": "obs_finance",
            "inspection_lot_9": "obs_quality",
            "pdf_document_4": "obs_pdf",
            "ppt_deck_7": "obs_ppt",
        }
        index = CandidateEvidenceIndex(
            [
                _record(
                    observation_id,
                    source_item_id=f"source_{observation_id}",
                    tokens={"variance"},
                    context_ids={context_id},
                )
                for context_id, observation_id in contexts.items()
            ]
        )

        for context_id, observation_id in contexts.items():
            with self.subTest(context_id=context_id):
                result = index.retrieve(
                    query_text="variance",
                    query_tokens={"variance"},
                    eligible_context_ids={context_id},
                )
                self.assertEqual(result.selected_observation_ids, (observation_id,))

    def test_same_api_handles_mail_table_quality_pdf_and_slide_observations(self) -> None:
        records = [
            _record(
                "obs_mail",
                source_item_id="mail_message_1",
                tokens={"release", "blocked"},
                context_ids={"mail_thread_1"},
            ),
            _record(
                "obs_finance",
                source_item_id="finance_row_1",
                tokens={"release", "blocked"},
                context_ids={"sheet_budget"},
            ),
            _record(
                "obs_quality",
                source_item_id="quality_record_1",
                tokens={"release", "blocked"},
                context_ids={"inspection_lot_1"},
            ),
            _record(
                "obs_pdf",
                source_item_id="pdf_page_4",
                tokens={"release", "blocked"},
                context_ids={"pdf_document_1"},
            ),
            _record(
                "obs_slide",
                source_item_id="ppt_slide_7",
                tokens={"release", "blocked"},
                context_ids={"presentation_1"},
            ),
        ]
        index = CandidateEvidenceIndex(records)

        result = index.retrieve(
            query_text="Compare release blockers across multiple records.",
            query_tokens={"release", "blocked"},
            limit=2,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(len(result.selected_observation_ids), 2)
        self.assertEqual(index.source_item_count, 5)

    def test_shared_context_or_common_term_does_not_create_transitive_components(self) -> None:
        records = [
            _record(
                f"obs_{index}",
                source_item_id=f"source_{index}",
                tokens={"common", f"specific_{index}"},
                context_ids={"same_container"},
            )
            for index in range(100)
        ]
        index = CandidateEvidenceIndex(records)

        result = index.retrieve(
            query_text="specific_99",
            query_tokens={"specific_99"},
            limit=10,
        )

        self.assertEqual(result.selected_observation_ids, ("obs_99",))
        self.assertEqual(index.record_count, 100)
        self.assertEqual(index.source_item_count, 100)


if __name__ == "__main__":
    unittest.main()
