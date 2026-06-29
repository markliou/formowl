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
        self.assertEqual(
            standard["default_model_profile"]["profile_id"],
            "legacy_cpu_bert",
        )
        self.assertEqual(
            standard["default_model_profile"]["default_model"],
            "sentence-transformers/bert-base-nli-mean-tokens",
        )
        self.assertEqual(standard["default_model_profile"]["default_threshold"], 0.70)

        self.assertTrue(accelerated["uses_neural_networks"])
        self.assertTrue(accelerated["requires_gpu"])
        self.assertIn("BERT-family NER", accelerated["model_families"])
        self.assertEqual(
            accelerated["default_model_profile"]["profile_id"],
            "gpu_bge_large_en_v1_5",
        )
        self.assertEqual(
            accelerated["default_model_profile"]["default_model"],
            "BAAI/bge-large-en-v1.5",
        )
        self.assertEqual(accelerated["default_model_profile"]["default_threshold"], 0.62)
        self.assertEqual(
            accelerated["default_model_profile"]["minimum_gpu"],
            "NVIDIA GeForce GTX 1080 Ti",
        )
        self.assertEqual(accelerated["minimum_capabilities"]["gpu_vram_gb_floor"], 11)
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
        self.assertTrue(summary["selection_boundary"]["legacy_cpu_bert_preserved"])
        self.assertTrue(
            summary["selection_boundary"]["gpu_default_model_requires_1080ti_or_better"]
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
