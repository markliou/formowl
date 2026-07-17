from __future__ import annotations

import builtins
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

import _paths  # noqa: F401
from formowl_contract import sha256_json
from formowl_graph import (
    CandidateEvidenceAccessBinding,
    CandidateEvidenceIndex,
    CandidateEvidenceRecord,
    CandidateEvidenceTextPolicyBinding,
    CandidateEvidenceTextPolicyRuntime,
    candidate_evidence_tokenizer_implementation_hash,
)

import test_mail_full_pst_domain_hard_case_eval_script as hard_domain_tests


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "mail_full_pst_domain_hard_kg_fusion_eval.py"
)


def _load_eval_module(module_name: str = "mail_full_pst_domain_hard_kg_fusion_eval"):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load KG fusion eval script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailFullPstDomainHardKgFusionEvalScriptTests(unittest.TestCase):
    def test_identifier_digits_do_not_trigger_measurement_ontology_signal(self) -> None:
        module = _load_eval_module()

        identifier_signals = module._source_neutral_ontology_signals(
            observation_type="erp_row",
            modality="erp",
            semantic_roles=frozenset({"identifier"}),
            tokens=frozenset({"lot-123"}),
            actor_tokens=frozenset(),
            observed_at=None,
        )
        amount_signals = module._source_neutral_ontology_signals(
            observation_type="erp_row",
            modality="erp",
            semantic_roles=frozenset({"currency_amount"}),
            tokens=frozenset({"1250"}),
            actor_tokens=frozenset(),
            observed_at=None,
        )
        numeric_query_signals = module._query_ontology_signals(
            "Show lot-123.",
            {"lot-123"},
        )

        self.assertIn("structured_record_evidence", identifier_signals)
        self.assertNotIn("measurement_bearing_evidence", identifier_signals)
        self.assertIn("measurement_bearing_evidence", amount_signals)
        self.assertNotIn("measurement_bearing_evidence", numeric_query_signals)

    def test_primary_score_is_invariant_to_rechunking_one_logical_source(self) -> None:
        module = _load_eval_module()
        whole = _minimal_kg_index(
            module,
            {"obs_whole": "source_stable"},
        )
        split = _minimal_kg_index(
            module,
            {
                "obs_part_a": "source_stable",
                "obs_part_b": "source_stable",
            },
        )

        stable_gold_case = {
            "result_kind": "owner_match",
            "required_source_observation_ids": ["obs_whole"],
            "required_logical_source_item_ids": ["source_stable"],
            "required_match_count": 1,
        }
        whole_score = module._score_selection(
            stable_gold_case,
            selected_observation_ids=("obs_whole",),
            kg_index=whole,
        )
        split_score = module._score_selection(
            stable_gold_case,
            selected_observation_ids=("obs_part_a",),
            kg_index=split,
        )

        self.assertEqual(whole_score.status, "passed")
        self.assertEqual(split_score.status, "passed")
        self.assertEqual(whole_score.required_source_item_count, 1)
        self.assertEqual(split_score.required_source_item_count, 1)
        self.assertEqual(whole_score.matched_required_source_item_count, 1)
        self.assertEqual(split_score.matched_required_source_item_count, 1)
        self.assertEqual(whole_score.matched_required_observation_count, 1)
        self.assertEqual(split_score.matched_required_observation_count, 0)
        self.assertEqual(split_score.unmapped_required_observation_count, 1)
        self.assertEqual(split_score.required_observation_count, 1)

    def test_legacy_manifest_migration_is_explicit_and_scoring_uses_bound_gold(
        self,
    ) -> None:
        module = _load_eval_module()
        original = _minimal_kg_index(module, {"obs_original": "source_stable"})
        rechunked = _minimal_kg_index(
            module,
            {
                "obs_part_a": "source_stable",
                "obs_part_b": "source_stable",
            },
        )
        manifest = {
            "cases": [
                {
                    "result_kind": "owner_match",
                    "required_source_observation_ids": ["obs_original"],
                    "required_match_count": 1,
                }
                for _ in range(module.CASE_COUNT)
            ]
        }

        migrated = module.migrate_legacy_private_manifest_logical_source_gold(
            manifest,
            segments=tuple(
                module._MailSegment(
                    observation_id=observation_id,
                    source_item_id=source_item_id,
                    source_identity_policy_id=module.EMAIL_SOURCE_IDENTITY_POLICY_ID,
                    source_version_id=f"version_{source_item_id}",
                    permission_scope_id="permission_scope_test",
                    thread_id=None,
                    message_occurrence_id=None,
                    message_id=None,
                    searchable_text="release",
                    actor_text="",
                    observed_at=None,
                    known_at="2026-07-07T12:30:00+00:00",
                    observation_type="text_block",
                    modality="text",
                    semantic_roles=frozenset(),
                    tokens=frozenset({"release"}),
                    actor_tokens=frozenset(),
                    ontology_signals=frozenset(),
                )
                for observation_id, source_item_id in original.component_by_observation_id.items()
            ),
        )
        bound_case = migrated["cases"][0]
        score = module._score_selection(
            bound_case,
            selected_observation_ids=("obs_part_b",),
            kg_index=rechunked,
        )

        self.assertEqual(
            bound_case["required_logical_source_item_ids"],
            ["source_stable"],
        )
        self.assertEqual(score.status, "passed")
        self.assertEqual(score.matched_required_observation_count, 0)
        self.assertEqual(score.unmapped_required_observation_count, 1)
        self.assertEqual(score.matched_required_source_item_count, 1)

    def test_scoring_rejects_manifest_without_stable_logical_source_gold(self) -> None:
        module = _load_eval_module()
        manifest = {
            "cases": [
                {
                    "result_kind": "owner_match",
                    "query_text": "release",
                    "private_fingerprint": "sha256:" + "a" * 64,
                    "required_source_observation_ids": ["obs_original"],
                }
                for _ in range(module.CASE_COUNT)
            ]
        }

        with self.assertRaisesRegex(
            FileNotFoundError,
            "private_manifest_logical_source_gold_missing",
        ):
            module._validate_private_manifest_cases(manifest)

    def test_retrieval_is_label_blind_and_uses_fixed_public_budget(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-label-blind")
        baseline_path, work_dir = _write_synthetic_inputs(module, temp_dir)
        calls: list[dict] = []
        original_retrieve = module.CandidateEvidenceIndex.retrieve

        def recording_retrieve(index, **kwargs):
            calls.append(dict(kwargs))
            return original_retrieve(index, **kwargs)

        module.CandidateEvidenceIndex.retrieve = recording_retrieve
        try:
            report = _run_with_opt_in(
                module,
                baseline_path=baseline_path,
                work_dir=work_dir,
            )
        finally:
            module.CandidateEvidenceIndex.retrieve = original_retrieve

        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
        self.assertEqual(len(calls), 100)
        self.assertTrue(all(call["limit"] == module.EVIDENCE_BUDGET for call in calls))
        self.assertTrue(
            all(
                call["accessible_context_ids"] == {call_context}
                and call["query_context_ids"] == {call_context}
                and call["known_as_of"] == "2026-07-07T12:30:00+00:00"
                and call["as_of_world_time"] == "2026-07-07T12:30:00+00:00"
                for call in calls
                for call_context in call["accessible_context_ids"]
            )
        )
        self.assertEqual(
            sum(not call["access_binding"].eligible_observation_ids for call in calls),
            10,
        )
        for call in calls:
            self.assertFalse(
                {
                    "result_kind",
                    "required_source_observation_ids",
                    "required_match_count",
                    "baseline_status",
                    "domain",
                    "pattern",
                }
                & set(call)
            )

    def test_denied_request_is_bound_before_query_tokenization(self) -> None:
        module = _load_eval_module()

        def fail_query_tokens(_value):
            raise AssertionError("denied request must not tokenize query text")

        kg_index = _minimal_kg_index(
            module,
            {"obs_a": "record_a"},
            tokenize_query=fail_query_tokens,
        )
        retrieval = module._retrieve_case_evidence(
            query_text="private placeholder",
            requester_user_id="denied_user",
            kg_index=kg_index,
        )

        self.assertTrue(retrieval.rejected)
        self.assertEqual(retrieval.rejection_reason, "no_accessible_evidence")
        self.assertEqual(retrieval.selected_observation_ids, ())

    def test_loader_merges_message_actor_subject_and_time_into_body_record(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-message-facets")
        observations_dir = temp_dir / "data" / "ingestion" / "observations"
        observations_dir.mkdir(parents=True)
        shared_location = {
            "message_id": "message_synthetic",
            "message_occurrence_id": "occurrence_synthetic",
            "thread_id": "thread_synthetic",
        }
        (observations_dir / "message.json").write_text(
            json.dumps(
                {
                    "observation_id": "obs_message",
                    "observation_type": "email_message",
                    "text": "Release review",
                    "created_at": "2026-07-07T12:30:00+00:00",
                    "location": shared_location,
                    "payload": {
                        **shared_location,
                        "subject": "Release review",
                        "normalized_subject": "release review",
                        "sender": "Alex Example",
                        "sent_at": "2026-05-01T09:00:00+08:00",
                    },
                }
            ),
            encoding="utf-8",
        )
        (observations_dir / "body.json").write_text(
            json.dumps(
                {
                    "observation_id": "obs_body",
                    "observation_type": "email_body_segment",
                    "text": "The shipment is blocked.",
                    "created_at": "2026-07-07T12:30:00+00:00",
                    "location": shared_location,
                    "permission_scope": {
                        "scope_type": "project",
                        "scope_id": "project_formowl",
                    },
                    "payload": shared_location,
                }
            ),
            encoding="utf-8",
        )

        segments = module._load_mail_segments(temp_dir)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].source_item_id, "message_synthetic")
        self.assertEqual(
            segments[0].source_identity_policy_id,
            module.EMAIL_SOURCE_IDENTITY_POLICY_ID,
        )
        self.assertTrue(segments[0].source_version_id)
        self.assertTrue(segments[0].permission_scope_id)
        self.assertEqual(segments[0].actor_text, "Alex Example")
        self.assertEqual(segments[0].observed_at, "2026-05-01T09:00:00+08:00")
        self.assertEqual(segments[0].known_at, "2026-07-07T12:30:00+00:00")
        self.assertIn("Release review", segments[0].searchable_text)

    def test_loader_requires_stable_source_identity_and_is_chunk_invariant(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-stable-source")
        observations_dir = temp_dir / "data" / "ingestion" / "observations"
        observations_dir.mkdir(parents=True)
        for suffix in ("a", "b"):
            (observations_dir / f"body-{suffix}.json").write_text(
                json.dumps(
                    {
                        "observation_id": f"obs_body_{suffix}",
                        "observation_type": "email_body_segment",
                        "text": f"Chunk {suffix}",
                        "created_at": "2026-07-07T12:30:00+00:00",
                        "location": {"message_id": "message_stable"},
                        "permission_scope": {
                            "scope_type": "project",
                            "scope_id": "project_formowl",
                        },
                        "payload": {"message_id": "message_stable"},
                    }
                ),
                encoding="utf-8",
            )

        segments = module._load_mail_segments(temp_dir)

        self.assertEqual(len(segments), 2)
        self.assertEqual({segment.source_item_id for segment in segments}, {"message_stable"})

        for path in observations_dir.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["location"] = {}
            payload["payload"] = {}
            path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            FileNotFoundError,
            "stable_source_identity_missing",
        ):
            module._load_mail_segments(temp_dir)

    def test_loader_fails_closed_without_permission_scope(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-permission-scope")
        observations_dir = temp_dir / "data" / "ingestion" / "observations"
        observations_dir.mkdir(parents=True)
        (observations_dir / "body.json").write_text(
            json.dumps(
                {
                    "observation_id": "obs_body",
                    "observation_type": "email_body_segment",
                    "text": "Synthetic body",
                    "location": {"message_id": "message_stable"},
                    "payload": {"message_id": "message_stable"},
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            FileNotFoundError,
            "permission_scope_missing",
        ):
            module._load_mail_segments(temp_dir)

    def test_eval_blocks_when_baseline_and_private_manifest_do_not_match(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-manifest-mismatch")
        baseline_path, work_dir = _write_synthetic_inputs(module, temp_dir)
        manifest_path = work_dir / module.PRIVATE_MANIFEST_RELATIVE
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["cases"][0]["private_fingerprint"] = sha256_json("different-case")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        report = _run_with_opt_in(
            module,
            baseline_path=baseline_path,
            work_dir=work_dir,
        )

        self.assertEqual(
            report["metrics"]["blocked_reason"],
            "baseline_manifest_binding_mismatch",
        )
        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])

    def test_blocks_without_opt_in_or_explicit_work_dir(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-blocked")
        old_value = os.environ.pop(module.RUN_OPT_IN_ENV, None)
        try:
            missing_opt_in = module.run_kg_fusion_eval(
                baseline_report_path=temp_dir / "baseline.json",
                work_dir=temp_dir / "work",
            )
            os.environ[module.RUN_OPT_IN_ENV] = "1"
            missing_work_dir = module.run_kg_fusion_eval()
        finally:
            if old_value is None:
                os.environ.pop(module.RUN_OPT_IN_ENV, None)
            else:
                os.environ[module.RUN_OPT_IN_ENV] = old_value

        self.assertEqual(
            missing_opt_in["metrics"]["blocked_reason"],
            "kg_fusion_eval_requires_explicit_opt_in",
        )
        self.assertEqual(
            missing_work_dir["metrics"]["blocked_reason"],
            "explicit_work_dir_required",
        )
        for report in (missing_opt_in, missing_work_dir):
            self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
            self.assertEqual(report["safe_outputs"]["case_count"], 0)
            self.assertFalse(
                report["claim_boundary"]["supports_candidate_only_kg_fusion_experiment_claim"]
            )
            self.assertFalse(
                report["claim_boundary"]["supports_bert_or_neural_candidate_generation_claim"]
            )

    def test_synthetic_fixture_kg_rescore_is_hash_only_and_validated(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-success")
        baseline_path, work_dir = _write_synthetic_inputs(module, temp_dir)

        report = _run_with_opt_in(module, baseline_path=baseline_path, work_dir=work_dir)

        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
        self.assertEqual(report["safe_outputs"]["case_count"], 100)
        self.assertEqual(report["safe_outputs"]["positive_case_count"], 80)
        self.assertEqual(report["safe_outputs"]["permission_denied_passed_count"], 10)
        self.assertTrue(report["metrics"]["no_bert_or_neural_dependency_used"])
        self.assertTrue(report["metrics"]["candidate_only_boundary_respected"])
        self.assertTrue(report["metrics"]["canonical_kg_wiki_side_effects_absent"])
        self.assertIn("largest_component_basis_points", report["safe_outputs"])
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("query_text", rendered)
        self.assertNotIn("source_observation_id", rendered)
        self.assertNotIn("email_message_id", rendered)
        self.assertNotIn(module.hard_eval.PRIVATE_MANIFEST_NAME.lower(), rendered)
        self.assertNotIn(str(work_dir).lower(), rendered)
        self.assertNotIn(".test-tmp", rendered)
        self.assertFalse((work_dir / "data" / "graph").exists())
        self.assertFalse((work_dir / "data" / "wiki").exists())

    def test_private_manifest_is_preserved_but_public_report_references_only_hash(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-private-manifest")
        baseline_path, work_dir = _write_synthetic_inputs(module, temp_dir)

        report = _run_with_opt_in(module, baseline_path=baseline_path, work_dir=work_dir)

        private_manifest = work_dir / module.PRIVATE_MANIFEST_RELATIVE
        self.assertTrue(private_manifest.is_file())
        self.assertEqual(
            report["safe_outputs"]["private_manifest_hash"],
            sha256_json(json.loads(private_manifest.read_text(encoding="utf-8"))),
        )
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn(private_manifest.name.lower(), rendered)
        self.assertNotIn("piece together", rendered)

    def test_validate_report_rejects_stale_row_derived_counts(self) -> None:
        module = _load_eval_module()
        report = _valid_kg_report(module)
        report["safe_outputs"]["kg_passed_case_count"] -= 1
        report["safe_outputs"]["domain_hash_counts"][sha256_json(module.hard_eval.DOMAINS[0])] -= 1
        report["safe_outputs"]["case_result_hash"] = "sha256:" + "0" * 64

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.kg_passed_case_count does not match case rows",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.domain_hash_counts does not match case rows",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.case_result_hash does not match case rows",
            validation["blockers"],
        )

    def test_validate_report_rejects_duplicate_response_hashes(self) -> None:
        module = _load_eval_module()
        report = _valid_kg_report(module)
        rows = report["safe_outputs"]["case_rows"]
        rows[1]["response_hash"] = rows[0]["response_hash"]
        report["safe_outputs"]["case_result_hash"] = sha256_json(rows)
        report["safe_outputs"]["unique_response_hash_count"] = 99
        report["safe_outputs"]["duplicate_response_hash_count"] = 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.duplicate_response_hash_count must be 0",
            validation["blockers"],
        )
        self.assertIn("case rows must contain 100 unique response hashes", validation["blockers"])

    def test_validate_report_rejects_private_fields_without_echo(self) -> None:
        module = _load_eval_module()
        report = _valid_kg_report(module)
        report["safe_outputs"]["case_rows"][0]["query_text"] = "private business question"
        report["safe_outputs"]["case_rows"][1]["source_observation_id"] = "obs_private_001"
        report["safe_outputs"]["domain_hash_counts"]["C:\\private\\archive.pst"] = 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        rendered = json.dumps(validation, sort_keys=True).lower()
        self.assertNotIn("private business question", rendered)
        self.assertNotIn("obs_private_001", rendered)
        self.assertNotIn("archive.pst", rendered)
        self.assertTrue(
            any(
                blocker.startswith("case_row contains unknown keys: count=")
                for blocker in validation["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.startswith("public report contains private field: sha256:")
                for blocker in validation["blockers"]
            )
        )

    def test_claim_boundary_rejects_neural_canonical_wiki_and_production_overclaims(
        self,
    ) -> None:
        module = _load_eval_module()
        for claim in (
            "supports_bert_or_neural_candidate_generation_claim",
            "supports_canonical_kg_write_claim",
            "supports_wiki_projection_claim",
            "supports_raw_mail_access_claim",
            "supports_business_answer_generation_claim",
            "supports_production_ready_claim",
        ):
            with self.subTest(claim=claim):
                report = _valid_kg_report(module)
                report["claim_boundary"][claim] = True

                validation = module.validate_report(report)

                self.assertFalse(validation["passed"])
                self.assertIn(
                    f"forbidden claim is not explicitly false: {claim}",
                    validation["blockers"],
                )

    def test_non_bert_path_imports_without_neural_packages(self) -> None:
        forbidden = {
            "sentence_transformers",
            "transformers",
            "torch",
            "tensorflow",
        }
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            root = str(name).split(".", 1)[0]
            if root in forbidden:
                raise AssertionError(f"neural import attempted: {root}")
            return original_import(name, *args, **kwargs)

        try:
            builtins.__import__ = guarded_import
            module = _load_eval_module("mail_full_pst_domain_hard_kg_fusion_eval_no_neural")
            temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-no-neural")
            baseline_path, work_dir = _write_synthetic_inputs(module, temp_dir)
            report = _run_with_opt_in(module, baseline_path=baseline_path, work_dir=work_dir)
        finally:
            builtins.__import__ = original_import

        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
        self.assertTrue(report["metrics"]["no_bert_or_neural_dependency_used"])
        self.assertFalse(
            report["claim_boundary"]["supports_bert_or_neural_candidate_generation_claim"]
        )

    def test_cli_validate_report_exits_nonzero_for_malformed_saved_report(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-cli-validation")
        malformed = _valid_kg_report(module)
        malformed["safe_outputs"]["case_count"] = False
        input_path = temp_dir / "malformed.json"
        output_path = temp_dir / "validation.json"
        input_path.write_text(json.dumps(malformed), encoding="utf-8")

        exit_code = module.main(
            [
                "--validate-report",
                str(input_path),
                "--output",
                str(output_path),
            ]
        )

        self.assertEqual(exit_code, 1)
        validation = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertFalse(validation["passed"])
        self.assertIn("safe_outputs.case_count does not match case rows", validation["blockers"])


def _run_with_opt_in(module, *, baseline_path: Path, work_dir: Path) -> dict:
    old_value = os.environ.get(module.RUN_OPT_IN_ENV)
    os.environ[module.RUN_OPT_IN_ENV] = "1"
    try:
        return module.run_kg_fusion_eval(
            baseline_report_path=baseline_path,
            work_dir=work_dir,
        )
    finally:
        if old_value is None:
            os.environ.pop(module.RUN_OPT_IN_ENV, None)
        else:
            os.environ[module.RUN_OPT_IN_ENV] = old_value


def _minimal_kg_index(
    module,
    source_item_by_observation_id: dict[str, str],
    *,
    tokenize_query=lambda _value: {"release"},
):
    records = [
        CandidateEvidenceRecord(
            observation_id=observation_id,
            source_item_id=source_item_id,
            source_identity_policy_id=module.EMAIL_SOURCE_IDENTITY_POLICY_ID,
            source_version_id=f"version_{source_item_id}",
            permission_scope_id="permission_scope_test",
            tokens=frozenset({"release"}),
            context_ids=frozenset({"candidate_context_test"}),
            known_at="2026-07-07T12:30:00+00:00",
        )
        for observation_id, source_item_id in source_item_by_observation_id.items()
    ]
    access_binding = CandidateEvidenceAccessBinding(
        binding_id="candidate_access_test",
        eligible_observation_ids=frozenset(record.observation_id for record in records),
        eligible_source_identity_policy_ids=frozenset(
            record.source_identity_policy_id for record in records
        ),
        eligible_permission_scope_ids=frozenset(record.permission_scope_id for record in records),
        eligible_source_version_ids=frozenset(record.source_version_id for record in records),
    )
    observation_ids_by_component: dict[str, list[str]] = {}
    for observation_id, source_item_id in source_item_by_observation_id.items():
        observation_ids_by_component.setdefault(source_item_id, []).append(observation_id)
    query_tokenizer_runtime_id = "candidate_evidence_script_test_runtime_v1"
    text_policy_binding = CandidateEvidenceTextPolicyBinding(
        normalization_policy_version="unicode_nfkc_test_v1",
        segmentation_policy_version="jieba_sentencepiece_test_v1",
        candidate_admission_policy="frozen_profile_candidate_admission_test",
        candidate_admission_policy_hash="sha256:" + ("a" * 64),
        sentencepiece_model_hash="sha256:" + ("b" * 64),
        sentencepiece_training_corpus_hash="sha256:" + ("c" * 64),
        query_tokenizer_runtime_id=query_tokenizer_runtime_id,
        query_tokenizer_implementation_hash=(
            candidate_evidence_tokenizer_implementation_hash(tokenize_query)
        ),
    )
    text_policy_runtime = CandidateEvidenceTextPolicyRuntime(
        binding=text_policy_binding,
        runtime_id=query_tokenizer_runtime_id,
        tokenize_query=tokenize_query,
    )
    return module._CandidateKgIndex(
        segmenters=None,
        compiled_policy=None,
        text_policy_runtime=text_policy_runtime,
        evidence_index=CandidateEvidenceIndex(
            records,
            access_binding=access_binding,
            text_policy_runtime=text_policy_runtime,
        ),
        evaluation_context_id="candidate_context_test",
        known_as_of="2026-07-07T12:30:00+00:00",
        as_of_world_time="2026-07-07T12:30:00+00:00",
        segment_by_observation_id={
            observation_id: object() for observation_id in source_item_by_observation_id
        },
        component_by_observation_id=dict(source_item_by_observation_id),
        observation_ids_by_component={
            source_item_id: tuple(observation_ids)
            for source_item_id, observation_ids in observation_ids_by_component.items()
        },
        tokens_by_component={
            source_item_id: frozenset({"release"})
            for source_item_id in observation_ids_by_component
        },
        component_ids_by_token={"release": tuple(sorted(observation_ids_by_component))},
        candidate_relation_count=0,
        token_relation_count=0,
        thread_relation_count=0,
    )


def _write_synthetic_inputs(module, temp_dir: Path) -> tuple[Path, Path]:
    hard_module = module.hard_eval
    baseline = hard_domain_tests._valid_baseline_report(hard_module, passed_count=20)
    baseline_path = temp_dir / "baseline.json"
    baseline_path.write_text(json.dumps(baseline, sort_keys=True), encoding="utf-8")

    work_dir = temp_dir / "work"
    observations_dir = work_dir / "data" / "ingestion" / "observations"
    artifacts_dir = work_dir / "artifacts"
    observations_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)

    rows = baseline["safe_outputs"]["case_rows"]
    cases = []
    patterns = [
        "multi_message",
        "actor_topic",
        "chronology",
        "conflict",
        "multi_message",
        "actor_topic",
        "chronology",
        "conflict",
        "no_match",
        "permission_denied",
    ]
    row_index = 0
    for domain in hard_module.DOMAINS:
        token = _unique_domain_token(domain)
        required_ids = [f"obs_body_{domain}_a", f"obs_body_{domain}_b"]
        _write_body_observation(observations_dir, required_ids[0], domain, token, suffix="a")
        _write_body_observation(observations_dir, required_ids[1], domain, token, suffix="b")
        for pattern in patterns:
            result_kind = "owner_match"
            query_text = f"Piece together separate-email {domain} updates about {token}."
            required = list(required_ids)
            required_match_count = 2
            requester = hard_module.ACTOR_USER_ID
            if pattern == "no_match":
                result_kind = "no_match"
                query_text = f"Find nonmatching synthetic topic for {domain}."
                required = []
                required_match_count = 0
            elif pattern == "permission_denied":
                result_kind = "permission_denied"
                required = []
                required_match_count = 0
                requester = hard_module.DENIED_USER_ID
            cases.append(
                {
                    "case_id": f"case_{row_index:03d}",
                    "domain": domain,
                    "intent_kind": f"{domain}_{pattern}",
                    "pattern": pattern,
                    "result_kind": result_kind,
                    "query_text": query_text,
                    "requester_user_id": requester,
                    "required_match_count": required_match_count,
                    "required_source_observation_ids": required,
                    "required_logical_source_item_ids": [
                        f"<{domain}-a@example.test>",
                        f"<{domain}-b@example.test>",
                    ]
                    if result_kind == "owner_match"
                    else [],
                    "forbidden_source_observation_ids": [],
                    "limit": 10,
                    "private_fingerprint": rows[row_index]["case_manifest_entry_hash"],
                }
            )
            row_index += 1
    manifest = {
        "manifest_type": "mail_full_pst_domain_hard_case_manifest_private",
        "generated_at": module.NOW,
        "archive_sha256": "sha256:" + "a" * 64,
        "mail_import_session_id": "mailimport_synthetic_kg",
        "mail_evidence_bundle_id": "mailevidencebundle_synthetic_kg",
        "parser_version": "0.1.0",
        "policy_version": hard_module.CASE_POLICY_VERSION,
        "case_count": 100,
        "cases": cases,
    }
    (work_dir / module.PRIVATE_MANIFEST_RELATIVE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return baseline_path, work_dir


def _write_body_observation(
    observations_dir: Path,
    observation_id: str,
    domain: str,
    token: str,
    *,
    suffix: str,
) -> None:
    message_id = f"<{domain}-{suffix}@example.test>"
    payload = {
        "observation_id": observation_id,
        "asset_id": "asset_mail_domain_hard_kg",
        "extractor_run_id": "run_mail_domain_hard_kg",
        "observation_type": "email_body_segment",
        "modality": "mail",
        "text": f"{token} synthetic mail component {suffix}",
        "location": {
            "archive_id": "archive_domain_hard_kg",
            "mailbox_id": "mailbox_domain_hard_kg",
            "folder_path_hash": "sha256:folder-domain-hard-kg",
            "message_id": message_id,
            "message_occurrence_id": f"occ_{domain}_{suffix}",
            "thread_id": f"thread_{domain}",
            "body_segment_index": 1,
        },
        "confidence": 1.0,
        "permission_scope": {"scope_type": "project", "scope_id": "project_formowl"},
        "created_at": "2026-07-07T12:30:00+00:00",
        "payload": {
            "archive_id": "archive_domain_hard_kg",
            "mailbox_id": "mailbox_domain_hard_kg",
            "message_id": message_id,
            "message_occurrence_id": f"occ_{domain}_{suffix}",
            "thread_id": f"thread_{domain}",
            "body_segment_index": 1,
        },
    }
    (observations_dir / f"{observation_id}.json").write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )


def _valid_kg_report(module) -> dict:
    temp_dir = _paths.fresh_test_dir("mail-domain-hard-kg-valid-report")
    baseline_path, work_dir = _write_synthetic_inputs(module, temp_dir)
    return copy.deepcopy(_run_with_opt_in(module, baseline_path=baseline_path, work_dir=work_dir))


def _unique_domain_token(domain: str) -> str:
    return {
        "production_management": "scrap",
        "warehouse_management": "bin",
        "financial_accounting": "accrual",
        "engineering": "api",
        "research_and_development": "hypothesis",
        "project_management": "milestone",
        "product_management": "cohort",
        "business_development": "alliance",
        "sales": "buyer",
        "distribution_channel": "rebate",
    }[domain]


if __name__ == "__main__":
    unittest.main()
