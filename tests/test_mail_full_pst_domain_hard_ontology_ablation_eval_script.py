from __future__ import annotations

import builtins
import copy
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

import _paths  # noqa: F401
from formowl_contract import sha256_json

import test_mail_full_pst_domain_hard_kg_fusion_eval_script as kg_tests


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "mail_full_pst_domain_hard_ontology_ablation_eval.py"
)


def _load_eval_module(module_name: str = "mail_full_pst_domain_hard_ontology_ablation_eval"):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ontology ablation eval script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailFullPstDomainHardOntologyAblationEvalScriptTests(unittest.TestCase):
    def test_blocks_without_opt_in_or_explicit_work_dir(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-ontology-blocked")
        old_value = os.environ.pop(module.RUN_OPT_IN_ENV, None)
        try:
            missing_opt_in = module.run_ontology_ablation_eval(
                baseline_report_path=temp_dir / "baseline.json",
                work_dir=temp_dir / "work",
            )
            os.environ[module.RUN_OPT_IN_ENV] = "1"
            missing_work_dir = module.run_ontology_ablation_eval()
        finally:
            if old_value is None:
                os.environ.pop(module.RUN_OPT_IN_ENV, None)
            else:
                os.environ[module.RUN_OPT_IN_ENV] = old_value

        self.assertEqual(
            missing_opt_in["metrics"]["blocked_reason"],
            "ontology_ablation_requires_explicit_opt_in",
        )
        self.assertEqual(
            missing_work_dir["metrics"]["blocked_reason"],
            "explicit_work_dir_required",
        )
        for report in (missing_opt_in, missing_work_dir):
            self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
            self.assertEqual(report["safe_outputs"]["case_count"], 0)
            self.assertFalse(
                report["claim_boundary"]["supports_ontology_guided_candidate_kg_ablation_claim"]
            )
            self.assertFalse(
                report["claim_boundary"]["supports_formal_ontology_governance_completion_claim"]
            )

    def test_synthetic_three_arm_ablation_is_hash_only_and_validated(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-ontology-success")
        baseline_path, work_dir = kg_tests._write_synthetic_inputs(module.kg_eval, temp_dir)

        report = _run_with_opt_in(module, baseline_path=baseline_path, work_dir=work_dir)

        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
        self.assertEqual(report["safe_outputs"]["case_count"], 100)
        self.assertEqual(report["safe_outputs"]["positive_case_count"], 80)
        self.assertEqual(report["safe_outputs"]["permission_denied_case_count"], 10)
        self.assertTrue(report["metrics"]["uses_formal_formowl_ontology_contracts"])
        self.assertTrue(report["metrics"]["uses_source_neutral_evidence_facet_mappings"])
        self.assertTrue(report["metrics"]["uses_type_evidence"])
        self.assertTrue(report["metrics"]["no_bert_or_neural_dependency_used"])
        self.assertEqual(report["safe_outputs"]["ontology_type_definition_count"], 10)
        self.assertEqual(report["safe_outputs"]["ontology_type_mapping_count"], 10)
        self.assertEqual(report["safe_outputs"]["ontology_invalid_mapping_count"], 0)
        self.assertGreaterEqual(
            report["safe_outputs"]["ontology_supported_relation_count"],
            0,
        )
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("query_text", rendered)
        self.assertNotIn("source_observation_id", rendered)
        self.assertNotIn("ontology_revision_mail_domain_hard", rendered)
        self.assertNotIn("production management", rendered)
        self.assertNotIn("workspace_formowl", rendered)
        self.assertNotIn(str(work_dir).lower(), rendered)
        self.assertNotIn(".test-tmp", rendered)
        self.assertFalse((work_dir / "data" / "graph").exists())
        self.assertFalse((work_dir / "data" / "wiki").exists())

    def test_denied_request_is_bound_before_ontology_query_vocabulary(self) -> None:
        module = _load_eval_module()
        kg_index = kg_tests._minimal_kg_index(module.kg_eval, {"obs_a": "record_a"})
        ontology_index = module._OntologyIndex(
            evidence_index=kg_index.evidence_index,
            ontology_contract_hash="sha256:" + "b" * 64,
            ontology_signal_vocabulary_hash="sha256:" + "c" * 64,
            supported_signals=frozenset({"concept_evidence"}),
            signals_by_observation_id={},
            signal_scores_by_component={},
            component_ids_by_signal={},
        )
        case = {
            "case_id": "permission_case",
            "query_text": "private placeholder",
            "requester_user_id": "denied_user",
            "result_kind": "permission_denied",
            "required_source_observation_ids": [],
            "required_source_item_ids": [],
            "required_match_count": 0,
        }
        original_query_tokens = module.kg_eval._query_tokens

        def fail_query_tokens(*_args, **_kwargs):
            raise AssertionError("denied request must not tokenize query text")

        module.kg_eval._query_tokens = fail_query_tokens
        try:
            row = module._score_case_with_ontology(
                case,
                kg_index=kg_index,
                ontology_index=ontology_index,
                baseline_row=None,
            )
        finally:
            module.kg_eval._query_tokens = original_query_tokens

        self.assertEqual(row["ontology_status"], "passed")
        self.assertEqual(row["ontology_selected_evidence_count"], 0)

    def test_context_time_rejection_does_not_retokenize_for_diagnostics(self) -> None:
        module = _load_eval_module()

        def fail_query_tokens(_value: str):
            raise AssertionError("inadmissible evidence must not tokenize query text")

        kg_index = kg_tests._minimal_kg_index(
            module.kg_eval,
            {"obs_a": "record_a"},
            tokenize_query=fail_query_tokens,
        )
        kg_index = replace(
            kg_index,
            known_as_of="2026-07-06T12:30:00+00:00",
            as_of_world_time="2026-07-06T12:30:00+00:00",
        )
        ontology_index = module._OntologyIndex(
            evidence_index=kg_index.evidence_index,
            ontology_contract_hash="sha256:" + "b" * 64,
            ontology_signal_vocabulary_hash="sha256:" + "c" * 64,
            supported_signals=frozenset({"concept_evidence"}),
            signals_by_observation_id={},
            signal_scores_by_component={},
            component_ids_by_signal={},
        )
        case = {
            "case_id": "future_case",
            "query_text": "release",
            "requester_user_id": "owner_user",
            "result_kind": "owner_match",
            "required_source_observation_ids": ["obs_a"],
            "required_source_item_ids": ["record_a"],
            "required_match_count": 1,
        }

        broad_binding = module.kg_eval._access_binding_for_records(
            kg_index.evidence_index.records,
            binding_context="ontology_context_time_test",
        )
        original_binding = module.kg_eval._access_binding_for_requester
        module.kg_eval._access_binding_for_requester = lambda *_args, **_kwargs: broad_binding
        try:
            row = module._score_case_with_ontology(
                case,
                kg_index=kg_index,
                ontology_index=ontology_index,
                baseline_row=None,
            )
        finally:
            module.kg_eval._access_binding_for_requester = original_binding

        self.assertEqual(row["ontology_selected_evidence_count"], 0)
        self.assertEqual(row["ontology_query_domain_count"], 0)

    def test_eval_blocks_when_baseline_and_private_manifest_do_not_match(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-ontology-manifest-mismatch")
        baseline_path, work_dir = kg_tests._write_synthetic_inputs(module.kg_eval, temp_dir)
        manifest_path = work_dir / module.kg_eval.PRIVATE_MANIFEST_RELATIVE
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

    def test_report_binds_all_three_arms_to_same_case_rows(self) -> None:
        module = _load_eval_module()
        report = _valid_ontology_report(module)
        rows = report["safe_outputs"]["ablation_rows"]

        self.assertEqual(len({row["case_id_hash"] for row in rows}), 100)
        self.assertEqual(len({row["case_manifest_entry_hash"] for row in rows}), 100)
        for row in rows:
            self.assertIn(row["baseline_status"], {"passed", "failed", "unknown"})
            self.assertIn(row["kg_status"], {"passed", "failed"})
            self.assertIn(row["ontology_status"], {"passed", "failed"})
            self.assertRegex(row["kg_response_hash"], r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(row["ontology_response_hash"], r"^sha256:[0-9a-f]{64}$")

    def test_validate_report_rejects_stale_row_derived_counts_and_deltas(self) -> None:
        module = _load_eval_module()
        report = _valid_ontology_report(module)
        report["safe_outputs"]["ontology_passed_case_count"] -= 1
        report["safe_outputs"]["ontology_delta_vs_kg_passed_case_count"] += 1
        report["safe_outputs"]["domain_hash_counts"][
            report["safe_outputs"]["ablation_rows"][0]["domain_hash"]
        ] -= 1
        report["safe_outputs"]["case_result_hash"] = "sha256:" + "0" * 64

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.ontology_passed_case_count does not match ablation rows",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.domain_hash_counts does not match ablation rows",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.case_result_hash does not match ablation rows",
            validation["blockers"],
        )

    def test_validate_report_rejects_duplicate_comparison_hashes(self) -> None:
        module = _load_eval_module()
        report = _valid_ontology_report(module)
        rows = report["safe_outputs"]["ablation_rows"]
        rows[1]["comparison_hash"] = rows[0]["comparison_hash"]
        report["safe_outputs"]["case_result_hash"] = sha256_json(rows)
        report["safe_outputs"]["unique_comparison_hash_count"] = 99
        report["safe_outputs"]["duplicate_comparison_hash_count"] = 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.duplicate_comparison_hash_count must be 0",
            validation["blockers"],
        )
        self.assertIn(
            "ablation rows must contain 100 unique comparison hashes",
            validation["blockers"],
        )

    def test_validate_report_rejects_private_fields_without_echo(self) -> None:
        module = _load_eval_module()
        report = _valid_ontology_report(module)
        report["safe_outputs"]["ablation_rows"][0]["query_text"] = "private hard question"
        report["safe_outputs"]["ablation_rows"][1]["message_id"] = "message-private"
        report["safe_outputs"]["ontology_label"] = "Production Management"

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        rendered = json.dumps(validation, sort_keys=True).lower()
        self.assertNotIn("private hard question", rendered)
        self.assertNotIn("message-private", rendered)
        self.assertNotIn("production management", rendered)
        self.assertTrue(
            any(
                blocker.startswith("ablation_row contains unknown keys: count=")
                for blocker in validation["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.startswith("public report contains private field: sha256:")
                for blocker in validation["blockers"]
            )
        )

    def test_claim_boundary_rejects_neural_canonical_wiki_raw_and_production_overclaims(
        self,
    ) -> None:
        module = _load_eval_module()
        for claim in (
            "supports_bert_or_neural_candidate_generation_claim",
            "supports_formal_ontology_governance_completion_claim",
            "supports_canonical_kg_write_claim",
            "supports_user_graph_write_claim",
            "supports_wiki_projection_claim",
            "supports_raw_mail_access_claim",
            "supports_business_answer_generation_claim",
            "supports_production_ready_claim",
        ):
            with self.subTest(claim=claim):
                report = _valid_ontology_report(module)
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
            module = _load_eval_module("mail_full_pst_domain_hard_ontology_ablation_eval_no_neural")
            temp_dir = _paths.fresh_test_dir("mail-domain-hard-ontology-no-neural")
            baseline_path, work_dir = kg_tests._write_synthetic_inputs(
                module.kg_eval,
                temp_dir,
            )
            report = _run_with_opt_in(module, baseline_path=baseline_path, work_dir=work_dir)
        finally:
            builtins.__import__ = original_import

        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
        self.assertTrue(report["metrics"]["no_bert_or_neural_dependency_used"])
        for name in forbidden:
            self.assertNotIn(name, sys.modules)

    def test_cli_validate_report_exits_nonzero_for_malformed_saved_report(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-ontology-cli-validation")
        malformed = _valid_ontology_report(module)
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
        self.assertIn(
            "safe_outputs.case_count does not match ablation rows", validation["blockers"]
        )


def _run_with_opt_in(module, *, baseline_path: Path, work_dir: Path) -> dict:
    old_value = os.environ.get(module.RUN_OPT_IN_ENV)
    os.environ[module.RUN_OPT_IN_ENV] = "1"
    try:
        return module.run_ontology_ablation_eval(
            baseline_report_path=baseline_path,
            work_dir=work_dir,
        )
    finally:
        if old_value is None:
            os.environ.pop(module.RUN_OPT_IN_ENV, None)
        else:
            os.environ[module.RUN_OPT_IN_ENV] = old_value


def _valid_ontology_report(module) -> dict:
    temp_dir = _paths.fresh_test_dir("mail-domain-hard-ontology-valid-report")
    baseline_path, work_dir = kg_tests._write_synthetic_inputs(module.kg_eval, temp_dir)
    return copy.deepcopy(_run_with_opt_in(module, baseline_path=baseline_path, work_dir=work_dir))


if __name__ == "__main__":
    unittest.main()
