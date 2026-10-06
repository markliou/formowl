from __future__ import annotations

from dataclasses import replace
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import sha256_json
from formowl_core import dense_embedding as dense_embedding_runtime
from formowl_core import (
    ASCII_IDENTIFIER_REGEX_TOKENIZER_ID,
    DenseEmbeddingUnavailableError,
    ISSUE56_TARGET_DENSE_DIMENSION,
    ISSUE56_TARGET_DENSE_MODEL_FILE_SHA256,
    ISSUE56_TARGET_DENSE_MODEL_ID,
    ISSUE56_TARGET_DENSE_MODEL_REVISION,
    ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT,
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    build_ascii_identifier_regex_tokenizer_profile,
    build_issue56_execution_component_binding,
    issue56_target_dense_embedding_profile,
    load_default_mail_candidate_admission_tokenizer_profile,
    load_issue56_target_dense_encoder,
)

ROOT = Path(__file__).resolve().parents[1]


def _load_smoke_module() -> object:
    spec = importlib.util.spec_from_file_location(
        "issue56_dense_embedding_smoke",
        ROOT / "scripts" / "issue56_dense_embedding_smoke.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Issue #56 dense embedding smoke is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SMOKE = _load_smoke_module()


class Issue56DenseEmbeddingEndToEndTests(unittest.TestCase):
    def test_multilingual_profile_is_exact_revision_and_fully_fingerprinted(
        self,
    ) -> None:
        profile = issue56_target_dense_embedding_profile()

        self.assertEqual(profile.model_id, ISSUE56_TARGET_DENSE_MODEL_ID)
        self.assertEqual(
            profile.model_revision,
            ISSUE56_TARGET_DENSE_MODEL_REVISION,
        )
        self.assertEqual(profile.dimension, ISSUE56_TARGET_DENSE_DIMENSION)
        self.assertEqual(
            profile.profile_fingerprint,
            ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT,
        )
        self.assertEqual(
            profile.profile_fingerprint,
            sha256_json(profile.fingerprint_payload()),
        )
        self.assertFalse(
            any(
                legacy in profile.model_id.casefold()
                for legacy in ("bert-base-nli-mean-tokens", "bge-large-en")
            )
        )
        self.assertNotIn("hash", profile.encoder_id.casefold())
        self.assertEqual(
            profile.model_file_sha256,
            "sha256:1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477",
        )
        self.assertRegex(
            profile.model_artifact_fingerprint,
            r"^sha256:[0-9a-f]{64}$",
        )

    def test_cpu_image_download_contract_matches_runtime_loader(self) -> None:
        dockerfile = (ROOT / "containers" / "kg-bert-cpu" / "Dockerfile").read_text(
            encoding="utf-8"
        )

        self.assertIn(ISSUE56_TARGET_DENSE_MODEL_ID, dockerfile)
        self.assertIn(ISSUE56_TARGET_DENSE_MODEL_REVISION, dockerfile)
        self.assertIn(ISSUE56_TARGET_DENSE_MODEL_FILE_SHA256, dockerfile)
        self.assertIn(ISSUE56_TARGET_DENSE_PROFILE_FINGERPRINT, dockerfile)
        self.assertIn('weights = snapshot / "model.safetensors"', dockerfile)
        self.assertIn('"pytorch_model.bin"', dockerfile)
        self.assertIn('"onnx/**"', dockerfile)
        dense_embedding_source = (
            ROOT / "python" / "formowl_core" / "dense_embedding.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'model_kwargs={"use_safetensors": True}',
            dense_embedding_source,
        )

    def test_model_embedding_capacity_is_not_tokenizer_vocabulary_size(self) -> None:
        model_contract = dense_embedding_runtime._MODEL_CONFIGURATION_CONTRACT
        tokenizer_contract = dense_embedding_runtime._TOKENIZER_CONFIGURATION_CONTRACT

        self.assertEqual(model_contract["model_embedding_vocabulary_size"], 250037)
        self.assertEqual(tokenizer_contract["serialized_vocabulary_size"], 250002)
        self.assertNotEqual(
            model_contract["model_embedding_vocabulary_size"],
            tokenizer_contract["serialized_vocabulary_size"],
        )
        self.assertEqual(model_contract["max_position_embeddings"], 512)
        self.assertEqual(tokenizer_contract["model_max_length"], 512)

    def test_target_runtime_tokenizer_and_execution_binding_are_explicit(
        self,
    ) -> None:
        tokenizer_profile = load_default_mail_candidate_admission_tokenizer_profile()
        dense_profile = issue56_target_dense_embedding_profile()
        binding = build_issue56_execution_component_binding(
            tokenizer_profile=tokenizer_profile,
            dense_profile=dense_profile,
        )

        self.assertEqual(
            tokenizer_profile.tokenizer_id,
            JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        )
        self.assertEqual(
            binding.tokenizer_profile_fingerprint,
            tokenizer_profile.profile_fingerprint,
        )
        self.assertEqual(
            binding.dense_profile_fingerprint,
            dense_profile.profile_fingerprint,
        )
        self.assertEqual(
            binding.execution_component_fingerprint,
            sha256_json(binding.fingerprint_payload()),
        )
        serialized = json.dumps(binding.fingerprint_payload(), sort_keys=True)
        self.assertNotIn(str(ROOT), serialized)
        self.assertNotIn("secret", serialized.casefold())

        legacy = build_ascii_identifier_regex_tokenizer_profile()
        self.assertEqual(legacy.tokenizer_id, ASCII_IDENTIFIER_REGEX_TOKENIZER_ID)
        with self.assertRaisesRegex(
            DenseEmbeddingUnavailableError,
            "^issue56 target dense embedding model is unavailable$",
        ) as caught:
            build_issue56_execution_component_binding(
                tokenizer_profile=legacy,
                dense_profile=dense_profile,
            )
        self.assertEqual(
            caught.exception.reason_code,
            "target_tokenizer_profile_required",
        )
        with self.assertRaisesRegex(
            DenseEmbeddingUnavailableError,
            "^issue56 target dense embedding model is unavailable$",
        ) as dense_drift:
            build_issue56_execution_component_binding(
                tokenizer_profile=tokenizer_profile,
                dense_profile=replace(
                    dense_profile,
                    dimension=dense_profile.dimension + 1,
                ),
            )
        self.assertEqual(
            dense_drift.exception.reason_code,
            "dense_profile_fingerprint_mismatch",
        )

    def test_loader_fails_closed_on_profile_or_dependency_version_drift(self) -> None:
        with self.assertRaisesRegex(
            DenseEmbeddingUnavailableError,
            "^issue56 target dense embedding model is unavailable$",
        ) as fingerprint_error:
            load_issue56_target_dense_encoder(expected_profile_fingerprint="sha256:" + ("f" * 64))
        self.assertEqual(
            fingerprint_error.exception.reason_code,
            "profile_fingerprint_mismatch",
        )

        expected_versions = dict(issue56_target_dense_embedding_profile().dependency_versions)

        def drifted_version(package_name: str) -> str:
            if package_name == "sentence-transformers":
                return "0.0.0"
            try:
                return expected_versions[package_name]
            except KeyError:
                return importlib.metadata.version(package_name)

        with (
            patch(
                "formowl_core.dense_embedding.platform.python_version",
                return_value="3.12.11",
            ),
            patch(
                "formowl_core.dense_embedding.importlib.metadata.version",
                side_effect=drifted_version,
            ),
        ):
            with self.assertRaisesRegex(
                DenseEmbeddingUnavailableError,
                "^issue56 target dense embedding model is unavailable$",
            ) as dependency_error:
                load_issue56_target_dense_encoder()
        self.assertEqual(
            dependency_error.exception.reason_code,
            "dense_dependency_version_mismatch",
        )

    def test_missing_model_or_runtime_never_falls_back_to_diagnostic_vectors(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="formowl-issue56-empty-model-cache-"
        ) as cache_directory:
            try:
                load_issue56_target_dense_encoder(cache_directory=cache_directory)
            except DenseEmbeddingUnavailableError as exc:
                self.assertIn(
                    exc.reason_code,
                    {
                        "python_runtime_version_mismatch",
                        "dense_dependency_unavailable",
                        "dense_dependency_version_mismatch",
                        "multilingual_model_snapshot_unavailable",
                    },
                )
            else:
                self.fail("empty model cache unexpectedly loaded a dense encoder")

    def test_smoke_is_real_rank_path_or_explicit_safe_blocker(self) -> None:
        report = SMOKE.run_smoke()

        self.assertEqual(report["claim_state"], "diagnostic_poc_only")
        self.assertFalse(report["fallback_used"])
        self.assertEqual(
            report["dense_profile"]["model_id"],
            ISSUE56_TARGET_DENSE_MODEL_ID,
        )
        self.assertEqual(
            report["dense_profile"]["model_revision"],
            ISSUE56_TARGET_DENSE_MODEL_REVISION,
        )
        self.assertFalse(report["methodology_authority"]["methodology_ready"])
        if report["status"] == "blocked":
            self.assertFalse(report["e2e_executed"])
            self.assertIn(
                report["blocker"],
                {
                    "python_runtime_version_mismatch",
                    "dense_dependency_unavailable",
                    "dense_dependency_version_mismatch",
                    "multilingual_model_snapshot_unavailable",
                    "target_tokenizer_runtime_unavailable",
                    "model_artifact_fingerprint_mismatch",
                    "model_configuration_drift",
                    "tokenizer_configuration_drift",
                    "sentence_transformer_configuration_drift",
                    "model_load_failed",
                    "model_runtime_configuration_drift",
                },
            )
            return

        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["e2e_executed"])
        self.assertEqual(report["rank"]["relevant_rank"], 1)
        self.assertGreater(
            report["rank"]["relevant_score"],
            report["rank"]["near_miss_score"],
        )
        self.assertEqual(
            report["determinism"]["query_vector_hash"],
            report["determinism"]["rerun_vector_hash"],
        )
        for norm_name in ("query_norm", "relevant_norm", "near_miss_norm"):
            self.assertAlmostEqual(
                report["determinism"][norm_name],
                1.0,
                places=5,
            )

    def test_real_model_load_embed_and_rank_when_snapshot_is_available(self) -> None:
        try:
            load_issue56_target_dense_encoder()
        except DenseEmbeddingUnavailableError as exc:
            self.skipTest(exc.reason_code)

        report = SMOKE.run_smoke()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["path_executed"],
            [
                "load_verified_multilingual_model",
                "load_frozen_target_tokenizer",
                "embed_query",
                "embed_relevant_evidence",
                "embed_near_miss_evidence",
                "deterministic_cosine_rank",
            ],
        )


if __name__ == "__main__":
    unittest.main()
