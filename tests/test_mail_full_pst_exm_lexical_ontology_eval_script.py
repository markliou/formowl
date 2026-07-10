from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
import types
import unittest

import _paths  # noqa: F401


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "mail_full_pst_exm_lexical_ontology_eval.py"
)


def _load_eval_module(module_name: str = "mail_full_pst_exm_lexical_ontology_eval"):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load lexical ontology eval script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailFullPstExmLexicalOntologyEvalScriptTests(unittest.TestCase):
    def test_blocks_without_opt_in_or_parsed_corpus(self) -> None:
        module = _load_eval_module()
        old_env = module.os.environ.pop(module.RUN_OPT_IN_ENV, None)
        try:
            missing_opt_in = module.run_exm_lexical_ontology_eval(
                parsed_corpus_dirs=[Path("missing")]
            )
            module.os.environ[module.RUN_OPT_IN_ENV] = "1"
            missing_input = module.run_exm_lexical_ontology_eval(parsed_corpus_dirs=[])
        finally:
            if old_env is None:
                module.os.environ.pop(module.RUN_OPT_IN_ENV, None)
            else:
                module.os.environ[module.RUN_OPT_IN_ENV] = old_env

        self.assertEqual(
            missing_opt_in["metrics"]["blocked_reason"],
            "exm_lexical_eval_requires_explicit_opt_in",
        )
        self.assertEqual(
            missing_input["metrics"]["blocked_reason"], "explicit_parsed_corpus_required"
        )
        for report in (missing_opt_in, missing_input):
            self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
            self.assertFalse(
                report["claim_boundary"]["supports_exm_50000_lexical_ontology_eval_claim"]
            )

    def test_requires_external_segmenters_by_default(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-exm-lexical-missing-segmenters")
        parsed = _write_synthetic_parsed_corpus(temp_dir / "parsed")
        old_env = module.os.environ.get(module.RUN_OPT_IN_ENV)
        old_optional_import = module._optional_import
        module._optional_import = (
            lambda name: None if name in {"jieba", "sentencepiece"} else old_optional_import(name)
        )
        module.os.environ[module.RUN_OPT_IN_ENV] = "1"
        try:
            report = module.run_exm_lexical_ontology_eval(
                parsed_corpus_dirs=[parsed],
                output_private_dir=temp_dir / "private",
                case_count=50,
                expected_parsed_corpus_count=1,
            )
        finally:
            module._optional_import = old_optional_import
            if old_env is None:
                module.os.environ.pop(module.RUN_OPT_IN_ENV, None)
            else:
                module.os.environ[module.RUN_OPT_IN_ENV] = old_env

        self.assertEqual(report["metrics"]["blocked_reason"], "external_segmenters_required")
        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])

    def test_synthetic_run_is_hash_only_and_lexical_arm_beats_regex_on_cjk_cases(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-exm-lexical-success")
        parsed = _write_synthetic_parsed_corpus(temp_dir / "parsed")
        old_env = module.os.environ.get(module.RUN_OPT_IN_ENV)
        old_modules = _install_fake_segmenters()
        module.os.environ[module.RUN_OPT_IN_ENV] = "1"
        try:
            report = module.run_exm_lexical_ontology_eval(
                parsed_corpus_dirs=[parsed],
                output_private_dir=temp_dir / "private",
                case_count=50,
                expected_parsed_corpus_count=1,
            )
        finally:
            _restore_modules(old_modules)
            if old_env is None:
                module.os.environ.pop(module.RUN_OPT_IN_ENV, None)
            else:
                module.os.environ[module.RUN_OPT_IN_ENV] = old_env

        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
        self.assertEqual(report["safe_outputs"]["case_count"], 50)
        self.assertEqual(report["safe_outputs"]["positive_case_count"], 40)
        self.assertEqual(report["safe_outputs"]["no_match_case_count"], 5)
        self.assertEqual(report["safe_outputs"]["permission_denied_case_count"], 5)
        self.assertGreater(report["safe_outputs"]["protected_span_case_count"], 0)
        summaries = report["safe_outputs"]["arm_summaries"]
        self.assertEqual(tuple(report["safe_outputs"]["arm_names"]), module.ARMS)
        self.assertIn(module.ARM_DATA_DRIVEN_ONTOLOGY, summaries)
        self.assertIn(module.ARM_FROZEN_ONTOLOGY, summaries)
        self.assertEqual(summaries[module.ARM_DATA_DRIVEN_ONTOLOGY]["case_count"], 50)
        self.assertEqual(summaries[module.ARM_FROZEN_ONTOLOGY]["case_count"], 50)
        self.assertGreater(
            summaries[module.ARM_LEXICAL_KG]["passed_case_count"],
            summaries[module.ARM_REGEX_KG]["passed_case_count"],
        )
        self.assertGreater(
            report["safe_outputs"]["lexical_ontology_delta_vs_regex_current_passed_case_count"],
            0,
        )
        self.assertEqual(
            report["safe_outputs"]["programmatic_neural_model_version"],
            module.PROGRAMMATIC_NEURAL_MODEL_VERSION,
        )
        self.assertRegex(
            report["safe_outputs"]["programmatic_neural_model_hash"], r"^sha256:[0-9a-f]{64}$"
        )
        self.assertGreater(report["safe_outputs"]["programmatic_neural_training_example_count"], 0)
        policy_summaries = report["safe_outputs"]["programmatic_policy_summaries"]
        self.assertEqual(
            policy_summaries[module.PROGRAMMATIC_SCORER_DATA_DRIVEN]["training_example_count"],
            0,
        )
        self.assertEqual(
            policy_summaries[module.PROGRAMMATIC_SCORER_FROZEN_PROFILE]["training_epoch_count"],
            0,
        )
        self.assertGreater(
            policy_summaries[module.PROGRAMMATIC_SCORER_WEAK_LABEL_MLP]["training_example_count"],
            0,
        )
        self.assertTrue((temp_dir / "private" / module.PRIVATE_MANIFEST_NAME).is_file())
        rendered = json.dumps(report, ensure_ascii=False, sort_keys=True).lower()
        self.assertNotIn("query_text", rendered)
        self.assertNotIn("source_observation_id", rendered)
        self.assertNotIn("email_message_id", rendered)
        self.assertNotIn("中光電", rendered)
        self.assertNotIn(str(temp_dir).lower(), rendered)
        self.assertNotIn(".test-tmp", rendered)

    def test_component_evidence_uses_lexeme_index_with_bounded_fallback(self) -> None:
        module = _load_eval_module()
        segment_ids = [f"seg_{index:03d}" for index in range(200)]
        segments = {
            segment_id: module._Segment(
                segment_id=segment_id,
                corpus_id_hash="sha256:" + "1" * 64,
                observation_id_hash="sha256:" + str(index % 10) * 64,
                message_key=f"message_{index}",
                thread_key="thread_large",
                text=f"fallback segment {index:03d}",
                lexemes_by_policy={
                    module.POLICY_LEXICAL: frozenset({"zh:target"}) if index == 199 else frozenset()
                }
                | {
                    module.POLICY_DATA_DRIVEN_PROGRAMMATIC: (
                        frozenset({"zh:target"}) if index == 199 else frozenset()
                    ),
                    module.POLICY_FROZEN_PROGRAMMATIC: (
                        frozenset({"zh:target"}) if index == 199 else frozenset()
                    ),
                    module.POLICY_PROGRAMMATIC: (
                        frozenset({"zh:target"}) if index == 199 else frozenset()
                    ),
                },
                categories=frozenset(),
                term_occurrences=(),
            )
            for index, segment_id in enumerate(segment_ids)
        }
        segmenters = module._SegmenterBundle(
            jieba_module=None,
            sentencepiece_module=None,
            sentencepiece_processor=None,
            sentencepiece_vocab_size=0,
            sentencepiece_model_hash="sha256:" + "0" * 64,
            training_corpus_hash="sha256:" + "0" * 64,
            user_symbol_count=0,
            external_jieba_available=False,
            external_sentencepiece_available=False,
        )
        kg_index = module._KgIndex(
            policy_name=module.POLICY_LEXICAL,
            segmenters=segmenters,
            compiled_policy=None,
            segment_by_id=segments,
            component_by_segment_id={segment_id: "component_large" for segment_id in segment_ids},
            segment_ids_by_component={"component_large": tuple(segment_ids)},
            lexemes_by_component={"component_large": frozenset({"zh:target"})},
            component_ids_by_lexeme={"zh:target": ("component_large",)},
            segment_ids_by_component_lexeme={"component_large": {"zh:target": ("seg_199",)}},
            fallback_segment_ids_by_component={
                "component_large": tuple(segment_ids[: module.MAX_COMPONENT_FALLBACK_SCAN_SEGMENTS])
            },
            relation_count=199,
            thread_relation_count=199,
            lexical_relation_count=0,
        )

        indexed = module._evidence_from_components(
            ("component_large",),
            query_lexemes={"zh:target"},
            kg_index=kg_index,
            limit=10,
        )
        fallback = module._evidence_from_components(
            ("component_large",),
            query_lexemes={"zh:missing"},
            kg_index=kg_index,
            limit=1000,
        )

        self.assertEqual(indexed, ("seg_199",))
        self.assertEqual(len(fallback), module.MAX_COMPONENT_FALLBACK_SCAN_SEGMENTS)
        self.assertNotIn("seg_199", fallback)

    def test_programmatic_policy_filters_ascii_pieces_and_keeps_typed_terms(self) -> None:
        module = _load_eval_module()
        segments = (
            _segment_for_policy_test(
                module,
                "seg_org_a",
                "msg_a",
                {"org:中光電有限公司", "zh:中光電", "sp:absentlexicalcase"},
                (
                    module._TermOccurrence(
                        lexeme="org:中光電有限公司",
                        display="中光電有限公司",
                        bucket="cjk_organization",
                        categories=frozenset({"organization", "cjk"}),
                    ),
                ),
            ),
            _segment_for_policy_test(
                module,
                "seg_org_b",
                "msg_b",
                {"org:中光電有限公司", "zh:中光電", "sp:absentlexicalcase"},
                (
                    module._TermOccurrence(
                        lexeme="org:中光電有限公司",
                        display="中光電有限公司",
                        bucket="cjk_organization",
                        categories=frozenset({"organization", "cjk"}),
                    ),
                ),
            ),
        )

        policy = module._compile_programmatic_ontology_policy(segments)
        important = module._important_lexemes(
            {"org:中光電有限公司", "zh:中光電", "sp:absentlexicalcase"},
            module.POLICY_PROGRAMMATIC,
            compiled_policy=policy,
        )

        self.assertIn("org:中光電有限公司", policy.accepted_lexemes)
        self.assertNotIn("sp:absentlexicalcase", policy.accepted_lexemes)
        self.assertEqual(policy.neural_model_version, module.PROGRAMMATIC_NEURAL_MODEL_VERSION)
        self.assertRegex(policy.neural_model_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertGreater(policy.neural_training_example_count, 0)
        self.assertIn("org:中光電有限公司", important)
        self.assertNotIn("sp:absentlexicalcase", important)

    def test_programmatic_ontology_does_not_use_category_only_fallback(self) -> None:
        module = _load_eval_module()
        segmenters = module._SegmenterBundle(
            jieba_module=None,
            sentencepiece_module=None,
            sentencepiece_processor=None,
            sentencepiece_vocab_size=0,
            sentencepiece_model_hash="sha256:" + "0" * 64,
            training_corpus_hash="sha256:" + "0" * 64,
            user_symbol_count=0,
            external_jieba_available=False,
            external_sentencepiece_available=False,
        )
        policy = module._CompiledOntologyPolicy(
            policy_hash="sha256:" + "1" * 64,
            scorer_kind=module.PROGRAMMATIC_SCORER_WEAK_LABEL_MLP,
            scorer_requires_training=True,
            candidate_lexeme_count=1,
            accepted_lexeme_count=0,
            rejected_lexeme_count=1,
            protected_accepted_lexeme_count=0,
            cjk_accepted_lexeme_count=0,
            ascii_piece_rejected_count=1,
            frequency_rejected_lexeme_count=0,
            neural_scored_lexeme_count=0,
            neural_accepted_lexeme_count=0,
            neural_model_version=module.PROGRAMMATIC_NEURAL_MODEL_VERSION,
            neural_model_hash="sha256:" + "2" * 64,
            neural_training_example_count=1,
            neural_training_positive_count=0,
            neural_training_negative_count=1,
            neural_training_epoch_count=module.PROGRAMMATIC_NEURAL_TRAINING_EPOCHS,
            neural_feature_count=len(module._PROGRAMMATIC_NEURAL_FEATURE_NAMES),
            accepted_lexemes=frozenset(),
        )
        segment = _segment_for_policy_test(
            module,
            "seg_identifier",
            "msg_identifier",
            {"id:known-id"},
            (),
        )
        kg_index = module._KgIndex(
            policy_name=module.POLICY_PROGRAMMATIC,
            segmenters=segmenters,
            compiled_policy=policy,
            segment_by_id={"seg_identifier": segment},
            component_by_segment_id={"seg_identifier": "component_identifier"},
            segment_ids_by_component={"component_identifier": ("seg_identifier",)},
            lexemes_by_component={"component_identifier": frozenset()},
            component_ids_by_lexeme={},
            segment_ids_by_component_lexeme={},
            fallback_segment_ids_by_component={"component_identifier": ("seg_identifier",)},
            relation_count=0,
            thread_relation_count=0,
            lexical_relation_count=0,
        )
        ontology_index = module._OntologyIndex(
            categories_by_segment_id={"seg_identifier": frozenset({"identifier"})},
            category_scores_by_component={"component_identifier": {"identifier": 1}},
            component_ids_by_category={"identifier": ("component_identifier",)},
        )

        selected = module._rank_components_with_ontology(
            {"id:absent-id"},
            query_categories={"identifier"},
            kg_index=kg_index,
            ontology_index=ontology_index,
            limit=6,
        )

        self.assertEqual(selected, ())

    def test_frozen_programmatic_ontology_does_not_use_category_only_fallback(self) -> None:
        module = _load_eval_module()
        segmenters = module._SegmenterBundle(
            jieba_module=None,
            sentencepiece_module=None,
            sentencepiece_processor=None,
            sentencepiece_vocab_size=0,
            sentencepiece_model_hash="sha256:" + "0" * 64,
            training_corpus_hash="sha256:" + "0" * 64,
            user_symbol_count=0,
            external_jieba_available=False,
            external_sentencepiece_available=False,
        )
        policy = module._CompiledOntologyPolicy(
            policy_hash="sha256:" + "1" * 64,
            scorer_kind=module.PROGRAMMATIC_SCORER_FROZEN_PROFILE,
            scorer_requires_training=False,
            candidate_lexeme_count=1,
            accepted_lexeme_count=0,
            rejected_lexeme_count=1,
            protected_accepted_lexeme_count=0,
            cjk_accepted_lexeme_count=0,
            ascii_piece_rejected_count=1,
            frequency_rejected_lexeme_count=0,
            neural_scored_lexeme_count=0,
            neural_accepted_lexeme_count=0,
            neural_model_version=module.PROGRAMMATIC_FROZEN_MODEL_VERSION,
            neural_model_hash="sha256:" + "2" * 64,
            neural_training_example_count=0,
            neural_training_positive_count=0,
            neural_training_negative_count=0,
            neural_training_epoch_count=0,
            neural_feature_count=len(module._PROGRAMMATIC_NEURAL_FEATURE_NAMES),
            accepted_lexemes=frozenset(),
        )
        segment = _segment_for_policy_test(
            module,
            "seg_frozen_identifier",
            "msg_identifier",
            {"id:known-id"},
            (),
        )
        kg_index = module._KgIndex(
            policy_name=module.POLICY_FROZEN_PROGRAMMATIC,
            segmenters=segmenters,
            compiled_policy=policy,
            segment_by_id={"seg_frozen_identifier": segment},
            component_by_segment_id={"seg_frozen_identifier": "component_identifier"},
            segment_ids_by_component={"component_identifier": ("seg_frozen_identifier",)},
            lexemes_by_component={"component_identifier": frozenset()},
            component_ids_by_lexeme={},
            segment_ids_by_component_lexeme={},
            fallback_segment_ids_by_component={"component_identifier": ("seg_frozen_identifier",)},
            relation_count=0,
            thread_relation_count=0,
            lexical_relation_count=0,
        )
        ontology_index = module._OntologyIndex(
            categories_by_segment_id={"seg_frozen_identifier": frozenset({"identifier"})},
            category_scores_by_component={"component_identifier": {"identifier": 1}},
            component_ids_by_category={"identifier": ("component_identifier",)},
        )

        selected = module._rank_components_with_ontology(
            {"id:absent-id"},
            query_categories={"identifier"},
            kg_index=kg_index,
            ontology_index=ontology_index,
            limit=6,
        )

        self.assertEqual(selected, ())

    def test_frozen_profile_model_hash_binds_scoring_rules(self) -> None:
        module = _load_eval_module()

        scorer = module._static_candidate_scorer(module.PROGRAMMATIC_SCORER_FROZEN_PROFILE)
        expected_hash = module.sha256_json(
            {
                "model_version": module.PROGRAMMATIC_FROZEN_MODEL_VERSION,
                "scorer_kind": module.PROGRAMMATIC_SCORER_FROZEN_PROFILE,
                "requires_training": False,
                "basis": "fixed_sigmoid_profile_not_fit_on_eval_corpus",
                "threshold_basis_points": module.PROGRAMMATIC_NEURAL_SCORE_THRESHOLD_BP,
                "feature_names": module._PROGRAMMATIC_NEURAL_FEATURE_NAMES,
                "rules": module._FROZEN_PROFILE_SCORE_RULES,
            }
        )

        self.assertEqual(scorer.model_hash, expected_hash)
        self.assertEqual(scorer.training_example_count, 0)
        self.assertEqual(scorer.training_epoch_count, 0)
        self.assertEqual(
            scorer.score_basis_points(
                "zh:採購交期",
                document_frequency=8,
                categories=frozenset({"cjk"}),
            ),
            module._frozen_profile_candidate_score_basis_points(
                "zh:採購交期",
                document_frequency=8,
                categories=frozenset({"cjk"}),
            ),
        )

    def test_identifier_regex_does_not_promote_plain_lowercase_words(self) -> None:
        module = _load_eval_module()

        plain = module._query_protected_lexemes(
            "Find separate evidence about absentlexicalcase04882."
        )
        coded = module._query_protected_lexemes("Find PO-ABC123 and RFQ 778899.")

        self.assertEqual(plain, set())
        self.assertIn("id:po-abc123", coded)
        self.assertIn("id:rfq 778899", coded)

    def test_validate_report_rejects_overclaims_and_public_leaks(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        report["claim_boundary"]["supports_production_ready_claim"] = True
        report["safe_outputs"]["leaky_query_text"] = "private question"

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "forbidden claim is not explicitly false: supports_production_ready_claim",
            validation["blockers"],
        )
        rendered = json.dumps(validation, sort_keys=True).lower()
        self.assertNotIn("private question", rendered)

    def test_validate_report_recomputes_completion_predicate(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        report["safe_outputs"]["case_count"] = module.CASE_COUNT - 1
        report["metrics"]["exm_lexical_ontology_eval_completed"] = True
        report["claim_boundary"]["supports_exm_50000_lexical_ontology_eval_claim"] = True
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "completion metric does not match recomputed completion predicate",
            validation["blockers"],
        )
        self.assertIn(
            "claim boundary does not match recomputed completion predicate",
            validation["blockers"],
        )

    def test_validate_report_rejects_tampered_arm_summary_counts(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        summary = report["safe_outputs"]["arm_summaries"][module.ARM_PROGRAMMATIC_ONTOLOGY]
        summary["passed_case_count"] += 1
        summary["failed_case_count"] -= 1
        summary["pass_rate_basis_points"] += 1
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("arm summary hash mismatch", validation["blockers"])
        self.assertIn("arm summary pass rate mismatch", validation["blockers"])
        self.assertIn("best passed case count mismatch", validation["blockers"])

    def test_validate_report_rejects_tampered_result_kind_counts(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        summary = report["safe_outputs"]["arm_summaries"][module.ARM_PROGRAMMATIC_ONTOLOGY]
        summary["no_match_passed_count"] += 1
        payload_for_hash = {key: value for key, value in summary.items() if key != "summary_hash"}
        summary["summary_hash"] = module.sha256_json(payload_for_hash)
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "arm summary result-kind passed counts do not sum",
            validation["blockers"],
        )

    def test_validate_report_rejects_tampered_no_training_policy_summary(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        summary = report["safe_outputs"]["programmatic_policy_summaries"][
            module.PROGRAMMATIC_SCORER_FROZEN_PROFILE
        ]
        summary["training_example_count"] = 1
        summary["training_positive_count"] = 1
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("no-training policy summary has training examples", validation["blockers"])

    def test_validate_report_rejects_tampered_frozen_delta(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        report["safe_outputs"][
            "programmatic_ontology_delta_vs_frozen_profile_passed_case_count"
        ] += 1
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "programmatic_ontology_delta_vs_frozen_profile_passed_case_count mismatch",
            validation["blockers"],
        )

    def test_validate_report_rejects_swapped_result_kind_counts(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        summary = report["safe_outputs"]["arm_summaries"][module.ARM_PROGRAMMATIC_ONTOLOGY]
        summary["positive_passed_count"] -= 1
        summary["no_match_passed_count"] += 1
        payload_for_hash = {key: value for key, value in summary.items() if key != "summary_hash"}
        summary["summary_hash"] = module.sha256_json(payload_for_hash)
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "arm summary no-match passed count does not match bucket",
            validation["blockers"],
        )
        self.assertIn(
            "arm summary positive passed count does not match buckets",
            validation["blockers"],
        )

    def test_validate_report_rejects_negative_result_kind_counts(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        summary = report["safe_outputs"]["arm_summaries"][module.ARM_PROGRAMMATIC_ONTOLOGY]
        summary["no_match_passed_count"] = -1
        summary["positive_passed_count"] = (
            summary["passed_case_count"] - summary["permission_denied_passed_count"] + 1
        )
        summary["bucket_passed_counts"]["false_positive_guard"] = -1
        positive_bucket = next(
            key
            for key in summary["bucket_passed_counts"]
            if key not in {"access_boundary", "false_positive_guard"}
        )
        summary["bucket_passed_counts"][positive_bucket] += 1
        payload_for_hash = {key: value for key, value in summary.items() if key != "summary_hash"}
        summary["summary_hash"] = module.sha256_json(payload_for_hash)
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "arm summary count must be a non-negative integer: no_match_passed_count",
            validation["blockers"],
        )
        self.assertIn(
            "arm summary bucket passed counts must be non-negative integers",
            validation["blockers"],
        )

    def test_validate_report_rejects_unknown_bucket_passed_key(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        summary = report["safe_outputs"]["arm_summaries"][module.ARM_PROGRAMMATIC_ONTOLOGY]
        positive_bucket = next(
            key
            for key in summary["bucket_passed_counts"]
            if key not in {"access_boundary", "false_positive_guard"}
        )
        summary["bucket_passed_counts"][positive_bucket] -= 1
        summary["bucket_passed_counts"]["fake_positive_bucket"] = 1
        payload_for_hash = {key: value for key, value in summary.items() if key != "summary_hash"}
        summary["summary_hash"] = module.sha256_json(payload_for_hash)
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "arm summary bucket passed keys must be bucket-count subset",
            validation["blockers"],
        )

    def test_validate_report_rejects_bucket_passed_count_above_total(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        summary = report["safe_outputs"]["arm_summaries"][module.ARM_PROGRAMMATIC_ONTOLOGY]
        positive_bucket = next(
            key
            for key in summary["bucket_passed_counts"]
            if key not in {"access_boundary", "false_positive_guard"}
        )
        summary["bucket_passed_counts"][positive_bucket] = (
            summary["bucket_counts"][positive_bucket] + 1
        )
        summary["positive_passed_count"] = (
            summary["positive_passed_count"]
            - sum(summary["bucket_passed_counts"].values())
            + summary["passed_case_count"]
        )
        payload_for_hash = {key: value for key, value in summary.items() if key != "summary_hash"}
        summary["summary_hash"] = module.sha256_json(payload_for_hash)
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "arm summary bucket passed count exceeds bucket total",
            validation["blockers"],
        )

    def test_validate_report_rejects_tampered_bucket_counts(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        summary = report["safe_outputs"]["arm_summaries"][module.ARM_PROGRAMMATIC_ONTOLOGY]
        positive_bucket = next(
            key
            for key in summary["bucket_passed_counts"]
            if key not in {"access_boundary", "false_positive_guard"}
        )
        summary["bucket_counts"][positive_bucket] -= 1
        summary["bucket_counts"]["fake_positive_bucket"] = 1
        summary["bucket_passed_counts"][positive_bucket] -= 1
        summary["bucket_passed_counts"]["fake_positive_bucket"] = 1
        payload_for_hash = {key: value for key, value in summary.items() if key != "summary_hash"}
        summary["summary_hash"] = module.sha256_json(payload_for_hash)
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "arm summary bucket counts must match case bucket counts",
            validation["blockers"],
        )

    def test_validate_report_rejects_tampered_report_level_bucket_counts(self) -> None:
        module = _load_eval_module()
        report = _valid_synthetic_report(module)
        safe_outputs = report["safe_outputs"]
        positive_bucket = next(
            key
            for key in safe_outputs["case_bucket_counts"]
            if key not in {"access_boundary", "false_positive_guard"}
        )
        safe_outputs["case_bucket_counts"][positive_bucket] -= 1
        safe_outputs["case_bucket_counts"]["fake_positive_bucket"] = 1
        for summary in safe_outputs["arm_summaries"].values():
            summary["bucket_counts"][positive_bucket] -= 1
            summary["bucket_counts"]["fake_positive_bucket"] = 1
            if summary["bucket_passed_counts"].get(positive_bucket, 0) > 0:
                summary["bucket_passed_counts"][positive_bucket] -= 1
                summary["bucket_passed_counts"]["fake_positive_bucket"] = 1
            payload_for_hash = {
                key: value for key, value in summary.items() if key != "summary_hash"
            }
            summary["summary_hash"] = module.sha256_json(payload_for_hash)
        report.pop("validation", None)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("case bucket counts contain unknown bucket", validation["blockers"])


def _valid_synthetic_report(module) -> dict:
    temp_dir = _paths.fresh_test_dir("mail-exm-lexical-valid-report")
    parsed = _write_synthetic_parsed_corpus(temp_dir / "parsed")
    old_env = module.os.environ.get(module.RUN_OPT_IN_ENV)
    old_modules = _install_fake_segmenters()
    module.os.environ[module.RUN_OPT_IN_ENV] = "1"
    try:
        return module.run_exm_lexical_ontology_eval(
            parsed_corpus_dirs=[parsed],
            output_private_dir=temp_dir / "private",
            case_count=50,
            expected_parsed_corpus_count=1,
        )
    finally:
        _restore_modules(old_modules)
        if old_env is None:
            module.os.environ.pop(module.RUN_OPT_IN_ENV, None)
        else:
            module.os.environ[module.RUN_OPT_IN_ENV] = old_env


def _segment_for_policy_test(
    module,
    segment_id: str,
    message_key: str,
    lexemes: set[str],
    occurrences: tuple,
):
    return module._Segment(
        segment_id=segment_id,
        corpus_id_hash="sha256:" + "2" * 64,
        observation_id_hash="sha256:" + segment_id[-1] * 64,
        message_key=message_key,
        thread_key=None,
        text="programmatic policy fixture",
        lexemes_by_policy={
            module.POLICY_REGEX: frozenset(),
            module.POLICY_LEXICAL: frozenset(lexemes),
            module.POLICY_DATA_DRIVEN_PROGRAMMATIC: frozenset(lexemes),
            module.POLICY_FROZEN_PROGRAMMATIC: frozenset(lexemes),
            module.POLICY_PROGRAMMATIC: frozenset(lexemes),
        },
        categories=frozenset({"organization", "cjk"}),
        term_occurrences=occurrences,
    )


def _write_synthetic_parsed_corpus(base_dir: Path) -> Path:
    observations_dir = base_dir / "data" / "ingestion" / "observations"
    observations_dir.mkdir(parents=True)
    rows = [
        ("obs_cjk_a", "msg_cjk_a", "thread_cjk", "中光電有限公司 purchase approval update"),
        ("obs_cjk_b", "msg_cjk_b", "thread_cjk", "中光電有限公司 purchase schedule update"),
        ("obs_org_a", "msg_org_a", "thread_org", "宏達電子公司 invoice shipment update"),
        ("obs_org_b", "msg_org_b", "thread_org", "宏達電子公司 invoice payment update"),
        ("obs_id_a", "msg_id_a", "thread_id", "PO-ABC123 purchase shipment update"),
        ("obs_id_b", "msg_id_b", "thread_id", "PO-ABC123 invoice delivery update"),
        ("obs_ascii_a", "msg_ascii_a", "thread_ascii", "purchase approval schedule update"),
        ("obs_ascii_b", "msg_ascii_b", "thread_ascii", "purchase approval payment update"),
    ]
    for index, (observation_id, message_id, thread_id, text) in enumerate(rows):
        payload = {
            "observation_id": observation_id,
            "asset_id": "asset_exm_lexical_test",
            "extractor_run_id": "run_exm_lexical_test",
            "observation_type": "email_body_segment",
            "modality": "mail",
            "text": text,
            "location": {
                "archive_id": "archive_exm_lexical_test",
                "mailbox_id": "mailbox_exm_lexical_test",
                "folder_path_hash": "sha256:folder-exm-lexical-test",
                "message_id": message_id,
                "message_occurrence_id": f"occ_{index}",
                "thread_id": thread_id,
                "body_segment_index": 1,
            },
            "confidence": 1.0,
            "permission_scope": {"scope_type": "project", "scope_id": "project_formowl"},
            "created_at": "2026-07-09T16:00:00+08:00",
            "payload": {
                "archive_id": "archive_exm_lexical_test",
                "mailbox_id": "mailbox_exm_lexical_test",
                "message_id": message_id,
                "message_occurrence_id": f"occ_{index}",
                "thread_id": thread_id,
                "body_segment_index": 1,
            },
        }
        (observations_dir / f"{observation_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    return base_dir


def _install_fake_segmenters() -> dict[str, object | None]:
    old = {"jieba": sys.modules.get("jieba"), "sentencepiece": sys.modules.get("sentencepiece")}
    jieba = types.ModuleType("jieba")

    def cut(value, cut_all=False):
        del cut_all
        return re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z0-9_.-]+", str(value))

    jieba.cut = cut

    sentencepiece = types.ModuleType("sentencepiece")

    class _Trainer:
        @staticmethod
        def Train(**kwargs):
            model_path = Path(str(kwargs["model_prefix"]) + ".model")
            model_path.write_text("fake sentencepiece model\n", encoding="utf-8")

    class _Processor:
        def __init__(self, model_file=None):
            self.model_file = model_file

        def Load(self, model_file):
            self.model_file = model_file
            return True

        def encode(self, value, out_type=str):
            del out_type
            return re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z0-9_.-]+", str(value))

        def EncodeAsPieces(self, value):
            return self.encode(value)

    sentencepiece.SentencePieceTrainer = _Trainer
    sentencepiece.SentencePieceProcessor = _Processor
    sys.modules["jieba"] = jieba
    sys.modules["sentencepiece"] = sentencepiece
    return old


def _restore_modules(old: dict[str, object | None]) -> None:
    for name, module in old.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()
