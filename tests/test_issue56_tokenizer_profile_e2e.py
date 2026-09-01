from __future__ import annotations

import importlib.metadata
import importlib.util
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import sha256_json
from formowl_core import (
    ASCII_IDENTIFIER_REGEX_TOKENIZER_ID,
    ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT,
    JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
    build_ascii_identifier_regex_tokenizer_profile,
    load_default_mail_candidate_admission_tokenizer_profile,
    load_issue56_target_mail_tokenizer_profile,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIRECTORY = (
    ROOT
    / "python"
    / "formowl_core"
    / "tokenizer_profiles"
    / JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID
)


def _load_smoke_module() -> object:
    spec = importlib.util.spec_from_file_location(
        "issue56_tokenizer_profile_smoke",
        ROOT / "scripts" / "issue56_tokenizer_profile_smoke.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Issue #56 tokenizer smoke is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SMOKE = _load_smoke_module()


class Issue56TokenizerProfileE2ETests(unittest.TestCase):
    def test_packaged_profile_is_reproducible_and_fully_fingerprinted(self) -> None:
        first = load_issue56_target_mail_tokenizer_profile()
        second = load_default_mail_candidate_admission_tokenizer_profile()

        self.assertEqual(
            first.tokenizer_id,
            JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        )
        self.assertEqual(first.profile_fingerprint, second.profile_fingerprint)
        self.assertEqual(first.fingerprint_payload(), second.fingerprint_payload())
        self.assertEqual(
            first.profile_fingerprint,
            sha256_json(first.fingerprint_payload()),
        )
        self.assertRegex(first.profile_fingerprint, r"^sha256:[0-9a-f]{64}$")
        for field_name in (
            "artifact_manifest_sha256",
            "calibration_corpus_sha256",
            "jieba_dictionary_sha256",
            "jieba_user_dictionary_sha256",
            "model_sha256",
            "sentencepiece_vocabulary_sha256",
            "sentencepiece_vocabulary_artifact_sha256",
            "dependency_requirements_sha256",
            "dependency_versions_sha256",
        ):
            self.assertRegex(
                str(getattr(first, field_name)),
                r"^sha256:[0-9a-f]{64}$",
                field_name,
            )
        self.assertEqual(first.package_name, "formowl")
        self.assertEqual(first.package_version, "0.1.0")

    def test_observation_to_query_evidence_index_smoke_is_real_and_bounded(self) -> None:
        report = SMOKE.run_smoke()
        e2e = report["e2e"]

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["claim_state"], "diagnostic_poc_only")
        self.assertEqual(
            report["profile"]["tokenizer_id"],
            JIEBA_SENTENCEPIECE_FROZEN_PROFILE_TOKENIZER_ID,
        )
        self.assertEqual(e2e["input_kind"], "existing_observations_only")
        self.assertEqual(e2e["query_status"], "ok")
        self.assertGreater(e2e["evidence_snippet_count"], 0)
        self.assertGreater(e2e["evidence_pack_result_count"], 0)
        self.assertEqual(
            e2e["query_profile_fingerprint"],
            e2e["evidence_profile_fingerprint"],
        )
        self.assertEqual(
            e2e["observation_index_fingerprint"],
            e2e["rerun_observation_index_fingerprint"],
        )
        self.assertEqual(
            e2e["query_index_fingerprint"],
            e2e["rerun_query_index_fingerprint"],
        )
        self.assertEqual(
            e2e["evidence_index_fingerprint"],
            e2e["rerun_evidence_index_fingerprint"],
        )
        self.assertTrue(e2e["rerun_deterministic"])
        self.assertFalse(e2e["ascii_fallback_used"])
        self.assertTrue({"zx-2048-alpha", "交期"}.issubset(e2e["query_runtime_tokens"]))
        self.assertEqual(e2e["raw_source_read_count"], 0)
        self.assertEqual(e2e["parser_invocation_count"], 0)
        self.assertEqual(e2e["new_extractor_run_count"], 0)
        self.assertEqual(
            e2e["protected_identifier_kinds"],
            ["business_identifier", "date", "email", "url"],
        )
        self.assertTrue(report["drift_probe"]["artifact_drift_rejected"])
        self.assertEqual(report["methodology_authority"]["status"], "blocked")
        self.assertFalse(report["methodology_authority"]["methodology_ready"])

    def test_manifest_artifact_or_dependency_drift_fails_without_ascii(self) -> None:
        scenarios = (
            ("manifest", self._drift_manifest),
            ("missing_vocab", self._remove_vocabulary),
            ("model", self._drift_model),
        )
        for scenario_name, mutate in scenarios:
            with self.subTest(scenario=scenario_name):
                with tempfile.TemporaryDirectory(
                    prefix="formowl-issue56-profile-test-"
                ) as temp_dir:
                    copied_profile = Path(temp_dir) / "profile"
                    shutil.copytree(PROFILE_DIRECTORY, copied_profile)
                    mutate(copied_profile)
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "^frozen tokenizer profile is unavailable$",
                    ):
                        load_issue56_target_mail_tokenizer_profile(
                            artifact_directory=copied_profile
                        )

        real_version = importlib.metadata.version

        def package_missing(package_name: str) -> str:
            if package_name == "sentencepiece":
                raise importlib.metadata.PackageNotFoundError(package_name)
            return real_version(package_name)

        with patch(
            "formowl_core.tokenization.importlib.metadata.version",
            side_effect=package_missing,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "^frozen tokenizer profile is unavailable$",
            ):
                load_issue56_target_mail_tokenizer_profile()

        baseline = build_ascii_identifier_regex_tokenizer_profile()
        self.assertEqual(baseline.tokenizer_id, ASCII_IDENTIFIER_REGEX_TOKENIZER_ID)

    def test_calibration_manifest_excludes_holdout_private_and_oracle_content(self) -> None:
        manifest = json.loads((PROFILE_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["source_partition"], "calibration")
        self.assertEqual(
            manifest["source_policy"]["content_kind"],
            "tracked_synthetic_cross_domain_calibration_text",
        )
        self.assertFalse(manifest["source_policy"]["contains_private_source"])
        self.assertFalse(manifest["source_policy"]["contains_oracle"])
        self.assertFalse(manifest["source_policy"]["contains_uat_or_holdout_questions"])

    def test_ordered_query_grounding_preserves_spans_roles_and_profile_contract(
        self,
    ) -> None:
        profile = load_issue56_target_mail_tokenizer_profile()
        query = "哪些記錄是由模組產生的，以及版本 ALPHA-42 與 alpha-42"
        baseline_analysis = profile.analyze(query)
        baseline_fingerprint = profile.profile_fingerprint

        grounding = profile.analyze_query_grounding(query)
        rerun = profile.analyze_query_grounding(query)

        self.assertEqual(grounding, rerun)
        self.assertRegex(
            grounding.grammar_policy_fingerprint,
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertEqual(
            [(term.start, term.end) for term in grounding.terms],
            sorted((term.start, term.end) for term in grounding.terms),
        )
        for term in grounding.terms:
            self.assertEqual(
                term.normalized_term,
                profile.normalize_exact_identifier_surface(query[term.start : term.end]),
            )
        role_by_term = {
            term.normalized_term: term.grammar_role for term in grounding.terms
        }
        self.assertTrue(
            {term.grammar_role for term in grounding.terms}
            <= {
                "conjunction",
                "lexical",
                "operator",
                "particle",
                "preposition",
                "pronoun",
                "verb",
            }
        )
        self.assertEqual(role_by_term["哪些"], "pronoun")
        self.assertEqual(role_by_term["是"], "verb")
        self.assertEqual(role_by_term["由"], "preposition")
        self.assertEqual(role_by_term["生"], "verb")
        self.assertEqual(role_by_term["的"], "particle")
        self.assertEqual(role_by_term["以及"], "conjunction")
        self.assertEqual(role_by_term["版本"], "lexical")
        repeated_values = [
            term
            for term in grounding.terms
            if term.normalized_term == "alpha-42"
        ]
        self.assertEqual(len(repeated_values), 2)
        self.assertTrue(all(term.grammar_role == "lexical" for term in repeated_values))
        self.assertNotEqual(repeated_values[0].start, repeated_values[1].start)
        self.assertEqual(profile.analyze(query), baseline_analysis)
        self.assertEqual(profile.profile_fingerprint, baseline_fingerprint)
        self.assertEqual(
            profile.profile_fingerprint,
            ISSUE56_TARGET_MAIL_TOKENIZER_PROFILE_FINGERPRINT,
        )

    def test_ordered_query_grounding_keeps_paraphrased_term_order(self) -> None:
        profile = load_issue56_target_mail_tokenizer_profile()
        first = profile.analyze_query_grounding("哪些記錄是由模組產生的")
        second = profile.analyze_query_grounding("模組產生哪些記錄")

        first_terms = tuple(term.normalized_term for term in first.terms)
        second_terms = tuple(term.normalized_term for term in second.terms)
        self.assertEqual(first_terms.count("哪些"), 1)
        self.assertEqual(second_terms.count("哪些"), 1)
        self.assertLess(first_terms.index("哪些"), first_terms.index("模"))
        self.assertGreater(second_terms.index("哪些"), second_terms.index("模"))
        self.assertEqual(
            first.grammar_policy_fingerprint,
            second.grammar_policy_fingerprint,
        )

    def test_ordered_query_grounding_missing_pos_runtime_fails_closed(self) -> None:
        profile = replace(
            load_issue56_target_mail_tokenizer_profile(),
            _jieba_module=None,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "^frozen tokenizer query grounding is unavailable$",
        ):
            profile.analyze_query_grounding("中性查詢")

    @staticmethod
    def _drift_manifest(profile_directory: Path) -> None:
        manifest_path = profile_directory / "manifest.json"
        manifest_path.write_text(
            manifest_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _remove_vocabulary(profile_directory: Path) -> None:
        (profile_directory / "sentencepiece.vocab").unlink()

    @staticmethod
    def _drift_model(profile_directory: Path) -> None:
        model_path = profile_directory / "sentencepiece.model"
        model = bytearray(model_path.read_bytes())
        model[-1] ^= 1
        model_path.write_bytes(model)


if __name__ == "__main__":
    unittest.main()
