from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import unittest

import _paths  # noqa: F401
from formowl_graph import (
    CandidateEvidenceAccessBinding,
    CandidateEvidenceHarnessContract,
    CandidateEvidenceIndex,
    CandidateEvidenceRecord,
    CandidateEvidenceTextPolicyBinding,
    CandidateEvidenceTextPolicyRuntime,
    build_default_candidate_evidence_harness_contract,
    candidate_evidence_tokenizer_implementation_hash,
)


def _hash(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def _hardness_query_tokens(value: str) -> set[str]:
    return set(value.lower().split())


TEXT_POLICY_RUNTIME_ID = "candidate_evidence_hardness_runtime_v1"
TEXT_POLICY_BINDING = CandidateEvidenceTextPolicyBinding(
    normalization_policy_version="unicode_nfkc_hardness_v1",
    segmentation_policy_version="jieba_sentencepiece_hardness_v1",
    candidate_admission_policy="frozen_profile_candidate_admission_hardness",
    candidate_admission_policy_hash=_hash("hardness-admission"),
    sentencepiece_model_hash=_hash("hardness-sentencepiece-model"),
    sentencepiece_training_corpus_hash=_hash("hardness-training-corpus"),
    query_tokenizer_runtime_id=TEXT_POLICY_RUNTIME_ID,
    query_tokenizer_implementation_hash=(
        candidate_evidence_tokenizer_implementation_hash(_hardness_query_tokens)
    ),
)
TEXT_POLICY_RUNTIME = CandidateEvidenceTextPolicyRuntime(
    binding=TEXT_POLICY_BINDING,
    runtime_id=TEXT_POLICY_RUNTIME_ID,
    tokenize_query=_hardness_query_tokens,
)


def _record(
    observation_id: str,
    *,
    source_item_id: str,
    tokens: set[str],
    context_id: str,
    observed_at: str | None = None,
    ontology_signals: set[str] | None = None,
    observation_type: str | None = None,
    modality: str | None = None,
) -> CandidateEvidenceRecord:
    return CandidateEvidenceRecord(
        observation_id=observation_id,
        source_item_id=source_item_id,
        source_identity_policy_id="hardness_source_identity_v1",
        source_version_id=f"version::{source_item_id}",
        permission_scope_id="scope_hardness",
        tokens=frozenset(tokens),
        context_ids=frozenset({context_id}),
        observed_at=observed_at,
        known_at=observed_at,
        ontology_signals=frozenset(ontology_signals or set()),
        observation_type=observation_type,
        modality=modality,
    )


def _binding(records: list[CandidateEvidenceRecord]) -> CandidateEvidenceAccessBinding:
    return CandidateEvidenceAccessBinding(
        binding_id="hardness_access_v1",
        eligible_observation_ids=frozenset(record.observation_id for record in records),
        eligible_source_identity_policy_ids=frozenset(
            record.source_identity_policy_id for record in records
        ),
        eligible_permission_scope_ids=frozenset(record.permission_scope_id for record in records),
        eligible_source_version_ids=frozenset(record.source_version_id for record in records),
    )


def _index(
    records: list[CandidateEvidenceRecord],
    **kwargs,
) -> CandidateEvidenceIndex:
    kwargs.setdefault("text_policy_runtime", TEXT_POLICY_RUNTIME)
    return CandidateEvidenceIndex(records, **kwargs)


def _retrieve(index: CandidateEvidenceIndex, **kwargs):
    query_tokens = frozenset(kwargs.pop("query_tokens", ()))
    kwargs.pop("query_policy_binding_hash", None)
    ontology_query_signals = frozenset(kwargs.pop("ontology_query_signals", ()))
    if ontology_query_signals:
        kwargs["enable_ontology_rerank"] = True
    return index.retrieve_ablation(
        **kwargs,
        ablation_id="hardness_explicit_query_tokens",
        query_token_transform=lambda base: base | query_tokens,
        ontology_query_signal_transform=(
            (lambda _query_text, _tokens: ontology_query_signals)
            if ontology_query_signals
            else None
        ),
    )


class CandidateEvidenceHardnessTests(unittest.TestCase):
    def test_default_contract_rejects_every_legacy_method_switch(self) -> None:
        default = build_default_candidate_evidence_harness_contract()
        record = _record(
            "obs_default",
            source_item_id="source_default",
            tokens={"variance"},
            context_id="context_default",
        )

        for field_name, legacy_value in (
            ("evidence_unit", "observation_chunk"),
            ("access_order", "query_vocabulary_before_binding"),
            ("anchor_policy", "lexical_transitive_component"),
            ("ontology_policy", "hard_pruning"),
            ("text_policy", "regex_only"),
            ("candidate_admission_policy", "raw_segments"),
            ("query_token_source", "caller_supplied_tokens"),
            ("ablation_entrypoint", "default_retrieve"),
            ("text_policy_binding_required", False),
            ("regex_only_default_allowed", True),
            ("parser_chunk_cardinality_allowed", True),
            ("lexical_transitive_closure_allowed", True),
            ("ontology_hard_pruning_allowed", True),
            ("canonical_write_allowed", True),
        ):
            with self.subTest(field_name=field_name):
                legacy = replace(default, **{field_name: legacy_value})
                with self.assertRaisesRegex(ValueError, "ablations only"):
                    _index(
                        [record],
                        access_binding=_binding([record]),
                        harness_contract=legacy,
                    )

        self.assertIsInstance(default, CandidateEvidenceHarnessContract)
        self.assertEqual(default.evidence_unit, "logical_source_item")

    def test_one_context_api_handles_cross_domain_and_multimodal_source_shapes(self) -> None:
        shapes = (
            ("mail", "mail_message", "email"),
            ("finance", "journal_entry", "erp"),
            ("quality", "inspection_event", "table"),
            ("pdf", "page", "pdf"),
            ("ppt", "slide", "pptx"),
            ("table", "spreadsheet_row", "xlsx"),
            ("ocr", "ocr_region", "ocr"),
            ("application", "application_event", "database"),
        )
        records = [
            _record(
                f"obs_{name}",
                source_item_id=f"source_{name}",
                tokens={"variance"},
                context_id=f"context_{name}",
                observation_type=observation_type,
                modality=modality,
            )
            for name, observation_type, modality in shapes
        ]
        index = _index(records, access_binding=_binding(records))
        accessible_contexts = {f"context_{name}" for name, _, _ in shapes}

        for name, _, _ in shapes:
            with self.subTest(source_shape=name):
                context_id = f"context_{name}"
                result = _retrieve(
                    index,
                    query_text="variance",
                    query_tokens={"variance"},
                    accessible_context_ids=accessible_contexts,
                    query_context_ids={context_id},
                )
                self.assertFalse(result.rejected)
                self.assertEqual(result.selected_observation_ids, (f"obs_{name}",))

    def test_chunk_bomb_and_shared_context_do_not_inflate_or_bridge_evidence(self) -> None:
        records = [
            _record(
                f"obs_a_{index}",
                source_item_id="source_a",
                tokens={"release", "common"},
                context_id="shared_context",
            )
            for index in range(100)
        ]
        records.extend(
            [
                _record(
                    "obs_b",
                    source_item_id="source_b",
                    tokens={"release", "blocked", "common"},
                    context_id="shared_context",
                ),
                _record(
                    "obs_c",
                    source_item_id="source_c",
                    tokens={"blocked", "common"},
                    context_id="shared_context",
                ),
            ]
        )
        index = _index(records, access_binding=_binding(records))

        two_sources = _retrieve(
            index,
            query_text="Compare release evidence across two records.",
            query_tokens={"release"},
            source_item_budget=2,
            observation_budget=2,
        )
        impossible_bridge = _retrieve(
            index,
            query_text=("Find the conflict between release and blocked across two records."),
            query_tokens={"release", "blocked"},
            source_item_budget=2,
            observation_budget=2,
        )

        self.assertFalse(two_sources.rejected)
        self.assertEqual(index.source_item_count, 3)
        self.assertEqual(len(two_sources.selected_observation_ids), 2)
        self.assertTrue(impossible_bridge.rejected)
        self.assertEqual(
            impossible_bridge.rejection_reason,
            "insufficient_supported_evidence",
        )

    def test_identifiers_durations_counts_and_chronology_remain_distinct(self) -> None:
        records = [
            _record(
                f"obs_{index}",
                source_item_id=f"report_{index}",
                tokens={"delay"},
                context_id="reporting_period",
                observed_at=f"2026-0{index + 1}-01T00:00:00+00:00",
            )
            for index in range(3)
        ]
        index = _index(records, access_binding=_binding(records))

        one = _retrieve(
            index,
            query_text="What delay was reported for PO-5000 within three months?",
            query_tokens={"delay"},
            source_item_budget=3,
        )
        latest_two = _retrieve(
            index,
            query_text="Show the latest two reports about delay for PO-5000.",
            query_tokens={"delay"},
            source_item_budget=3,
            observation_budget=2,
        )

        self.assertEqual(one.plan.target_source_items, 1)
        self.assertEqual(len(one.selected_observation_ids), 1)
        self.assertEqual(latest_two.plan.target_source_items, 2)
        self.assertEqual(latest_two.selected_observation_ids, ("obs_2", "obs_1"))

    def test_ontology_can_rerank_but_cannot_delete_lexical_evidence(self) -> None:
        records = [
            _record(
                "obs_finance",
                source_item_id="finance_record",
                tokens={"variance"},
                context_id="period_q2",
            ),
            _record(
                "obs_quality",
                source_item_id="quality_record",
                tokens={"variance"},
                context_id="lot_7",
                ontology_signals={"measurement_bearing_evidence"},
            ),
        ]
        index = _index(
            records,
            access_binding=_binding(records),
            ontology_revision_id="ontology_v1",
            ontology_signal_vocabulary_hash="sha256:signals",
            ontology_contract_hash="sha256:contract",
        )

        result = _retrieve(
            index,
            query_text="Compare variance across two records.",
            query_tokens={"variance"},
            ontology_query_signals={"measurement_bearing_evidence"},
            ontology_revision_id="ontology_v1",
            ontology_signal_vocabulary_hash="sha256:signals",
            ontology_contract_hash="sha256:contract",
            source_item_budget=2,
            observation_budget=2,
        )

        self.assertFalse(result.rejected)
        self.assertEqual(result.selected_observation_ids[0], "obs_quality")
        self.assertEqual(set(result.selected_observation_ids), {"obs_finance", "obs_quality"})


if __name__ == "__main__":
    unittest.main()
