from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
from formowl_graph import (
    CandidateGenerationProfile,
    build_candidate_generation_capability_summary,
    select_candidate_generation_profile,
)


class CandidateGenerationCapabilityTests(unittest.TestCase):
    def test_low_spec_profile_is_non_neural_and_candidate_only(self) -> None:
        profile = select_candidate_generation_profile("low_spec_cpu").to_dict()

        self.assertEqual(profile["profile_id"], "deterministic_cpu_candidate_generation_v1")
        self.assertFalse(profile["uses_neural_networks"])
        self.assertFalse(profile["produces_embeddings"])
        self.assertFalse(profile["requires_gpu"])
        self.assertFalse(profile["canonical_write_allowed"])
        self.assertFalse(profile["raw_access_allowed"])
        self.assertIn("FusionCandidate", profile["output_records"])
        self.assertIn("rapidfuzz_compatible_lexical_matching", profile["candidate_generators"])
        self.assertTrue(profile["profile_hash"].startswith("sha256:"))

    def test_embedding_and_neural_profiles_restore_bert_as_optional_adapter_slots(
        self,
    ) -> None:
        standard = select_candidate_generation_profile("standard_cpu").to_dict()
        accelerated = select_candidate_generation_profile("accelerated_gpu").to_dict()

        self.assertTrue(standard["uses_neural_networks"])
        self.assertTrue(standard["produces_embeddings"])
        self.assertFalse(standard["requires_gpu"])
        self.assertIn("BERT-family encoder", standard["model_families"])
        self.assertIn("sentence_transformer_embedding_adapter", standard["candidate_generators"])
        self.assertIn("score_breakdown.embedding", standard["output_records"])

        self.assertTrue(accelerated["uses_neural_networks"])
        self.assertTrue(accelerated["requires_gpu"])
        self.assertIn("BERT-family NER", accelerated["model_families"])
        self.assertIn(
            "bert_family_relation_extraction_adapter", accelerated["candidate_generators"]
        )
        self.assertFalse(accelerated["canonical_write_allowed"])
        self.assertFalse(accelerated["raw_access_allowed"])

    def test_remote_model_worker_selects_accelerated_profile(self) -> None:
        remote = select_candidate_generation_profile("remote_model_worker").to_dict()

        self.assertEqual(remote["profile_id"], "accelerated_neural_candidate_generation_v1")
        self.assertTrue(remote["uses_neural_networks"])

    def test_capability_summary_exposes_system_integration_boundary(self) -> None:
        summary = build_candidate_generation_capability_summary()

        self.assertEqual(
            summary["artifact_id"],
            "formowl_kg_candidate_generation_capability_profiles_v1",
        )
        self.assertTrue(summary["selection_boundary"]["low_spec_remote_workers_supported"])
        self.assertTrue(summary["selection_boundary"]["neural_models_optional"])
        self.assertTrue(
            summary["selection_boundary"]["bert_or_sentence_transformer_available_as_adapter_slot"]
        )
        self.assertTrue(summary["selection_boundary"]["candidate_output_only"])
        self.assertFalse(summary["selection_boundary"]["canonical_write_allowed"])
        self.assertEqual(len(summary["profiles"]), 3)

    def test_profiles_reject_canonical_write_or_raw_access_claims(self) -> None:
        with self.assertRaises(ContractValidationError):
            CandidateGenerationProfile(
                profile_id="bad_profile",
                worker_tier="bad_tier",
                display_name="Bad profile",
                description="Bad profile",
                candidate_generators=("bad_generator",),
                output_records=("CanonicalGraphStore",),
                minimum_capabilities={"cpu_required": True},
                canonical_write_allowed=True,
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            CandidateGenerationProfile(
                profile_id="bad_profile",
                worker_tier="bad_tier",
                display_name="Bad profile",
                description="Bad profile",
                candidate_generators=("bad_generator",),
                output_records=("raw_asset",),
                minimum_capabilities={"cpu_required": True},
                raw_access_allowed=True,
            ).to_dict()


if __name__ == "__main__":
    unittest.main()
