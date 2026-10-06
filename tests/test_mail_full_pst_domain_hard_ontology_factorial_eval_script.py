from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import _paths  # noqa: F401

import test_mail_full_pst_domain_hard_kg_fusion_eval_script as kg_tests


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "mail_full_pst_domain_hard_ontology_factorial_eval.py"
)


def _load_eval_module(module_name: str = "mail_full_pst_domain_hard_ontology_factorial_eval"):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ontology factorial eval script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailFullPstDomainHardOntologyFactorialEvalScriptTests(unittest.TestCase):
    def test_blocks_without_opt_in_or_explicit_work_dir(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-factorial-blocked")
        old_value = os.environ.pop(module.RUN_OPT_IN_ENV, None)
        try:
            missing_opt_in = module.run_ontology_factorial_eval(
                baseline_report_path=temp_dir / "baseline.json",
                work_dir=temp_dir / "work",
            )
            os.environ[module.RUN_OPT_IN_ENV] = "1"
            missing_work_dir = module.run_ontology_factorial_eval()
        finally:
            if old_value is None:
                os.environ.pop(module.RUN_OPT_IN_ENV, None)
            else:
                os.environ[module.RUN_OPT_IN_ENV] = old_value

        self.assertEqual(
            missing_opt_in["metrics"]["blocked_reason"],
            "ontology_factorial_requires_explicit_opt_in",
        )
        self.assertEqual(
            missing_work_dir["metrics"]["blocked_reason"],
            "explicit_work_dir_required",
        )
        for report in (missing_opt_in, missing_work_dir):
            self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
            self.assertEqual(report["safe_outputs"]["case_count"], 0)
            self.assertFalse(
                report["claim_boundary"]["supports_ontology_operator_factorial_experiment_claim"]
            )

    def test_synthetic_factorial_scores_all_ordered_subsets_safely(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-factorial-success")
        baseline_path, work_dir = kg_tests._write_synthetic_inputs(module.kg_eval, temp_dir)

        report = _run_with_opt_in(module, baseline_path=baseline_path, work_dir=work_dir)

        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
        safe = report["safe_outputs"]
        self.assertEqual(safe["operator_count"], 5)
        self.assertEqual(safe["ordered_arm_count"], 326)
        self.assertEqual(safe["scored_arm_count"], 326)
        self.assertEqual(
            safe["ordered_arm_count_by_length"],
            {"0": 1, "1": 5, "2": 20, "3": 60, "4": 120, "5": 120},
        )
        self.assertEqual(len(safe["arm_summaries"]), 326)
        self.assertGreaterEqual(safe["kg_only_passed_case_count"], 0)
        self.assertLessEqual(safe["kg_only_passed_case_count"], 100)
        self.assertGreaterEqual(safe["best_passed_case_count"], safe["kg_only_passed_case_count"])
        self.assertEqual(
            safe["best_delta_vs_kg_only_passed_case_count"],
            safe["best_passed_case_count"] - safe["kg_only_passed_case_count"],
        )
        self.assertEqual(
            safe["arms_better_than_kg_only_count"]
            + safe["arms_equal_to_kg_only_count"]
            + safe["arms_worse_than_kg_only_count"],
            326,
        )
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("query_text", rendered)
        self.assertNotIn("source_observation_id", rendered)
        self.assertNotIn("selected_evidence", rendered)
        self.assertNotIn(str(work_dir).lower(), rendered)
        self.assertNotIn(".test-tmp", rendered)
        self.assertFalse((work_dir / "data" / "graph").exists())
        self.assertFalse((work_dir / "data" / "wiki").exists())

    def test_permission_denied_label_still_uses_configured_ablation_arm(self) -> None:
        module = _load_eval_module()
        kg_index = kg_tests._minimal_kg_index(module.kg_eval, {"obs_a": "record_a"})
        ontology_index = module.ontology_eval._OntologyIndex(
            evidence_index=kg_index.evidence_index,
            ontology_contract_hash="sha256:" + "b" * 64,
            ontology_signal_vocabulary_hash="sha256:" + "c" * 64,
            supported_signals=frozenset(),
            signals_by_observation_id={},
            signal_scores_by_component={},
            component_ids_by_signal={},
        )
        factorial_index = module._FactorialIndex(
            ontology_index=ontology_index,
            type_scores_by_component={},
            component_ids_by_type={},
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

        def fail_query_tokens(*_args, **_kwargs):
            raise AssertionError("denied request must not tokenize query text")

        with (
            patch.object(
                type(kg_index.evidence_index),
                "retrieve",
                side_effect=AssertionError(
                    "permission label must not force the default retrieval arm"
                ),
            ),
            patch.object(module.kg_eval, "_query_tokens", fail_query_tokens),
        ):
            row = module._score_case_for_arm(
                case,
                arm=(module.SHACL_PRUNING,),
                baseline_row=None,
                kg_index=kg_index,
                factorial_index=factorial_index,
            )

        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["selected_evidence_count"], 0)

    def test_permission_denied_label_does_not_auto_pass_with_broad_binding(self) -> None:
        module = _load_eval_module()
        kg_index = kg_tests._minimal_kg_index(module.kg_eval, {"obs_a": "record_a"})
        ontology_index = module.ontology_eval._OntologyIndex(
            evidence_index=kg_index.evidence_index,
            ontology_contract_hash="sha256:" + "b" * 64,
            ontology_signal_vocabulary_hash="sha256:" + "c" * 64,
            supported_signals=frozenset(),
            signals_by_observation_id={},
            signal_scores_by_component={},
            component_ids_by_signal={},
        )
        factorial_index = module._FactorialIndex(
            ontology_index=ontology_index,
            type_scores_by_component={},
            component_ids_by_type={},
        )
        case = {
            "case_id": "permission_case",
            "query_text": "release",
            "requester_user_id": "denied_user",
            "result_kind": "permission_denied",
            "required_source_observation_ids": [],
            "required_source_item_ids": [],
            "required_match_count": 0,
        }
        broad_binding = module.kg_eval._access_binding_for_records(
            kg_index.evidence_index.records,
            binding_context="factorial_test_broad",
        )
        original_binding = module.kg_eval._access_binding_for_requester
        module.kg_eval._access_binding_for_requester = lambda *_args, **_kwargs: broad_binding
        try:
            row = module._score_case_for_arm(
                case,
                arm=(),
                baseline_row=None,
                kg_index=kg_index,
                factorial_index=factorial_index,
            )
        finally:
            module.kg_eval._access_binding_for_requester = original_binding

        self.assertEqual(row["status"], "failed")

    def test_eval_blocks_when_baseline_and_private_manifest_do_not_match(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-factorial-manifest-mismatch")
        baseline_path, work_dir = kg_tests._write_synthetic_inputs(module.kg_eval, temp_dir)
        manifest_path = work_dir / module.kg_eval.PRIVATE_MANIFEST_RELATIVE
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["cases"][0]["private_fingerprint"] = module.sha256_json("different-case")
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

    def test_validate_report_rejects_stale_arm_derived_counts(self) -> None:
        module = _load_eval_module()
        report = _valid_factorial_report(module)
        report["safe_outputs"]["best_passed_case_count"] -= 1
        report["safe_outputs"]["arms_better_than_kg_only_count"] += 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.best_passed_case_count does not match arms",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.arms_better_than_kg_only_count does not match arms",
            validation["blockers"],
        )

    def test_validate_report_rejects_duplicate_or_missing_arms(self) -> None:
        module = _load_eval_module()
        report = _valid_factorial_report(module)
        summaries = report["safe_outputs"]["arm_summaries"]
        summaries[1]["arm_id_hash"] = summaries[0]["arm_id_hash"]
        report["safe_outputs"]["arm_summary_hash"] = module.sha256_json(summaries)

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("arm summaries must have unique arm ids", validation["blockers"])

    def test_cli_validate_report_exits_nonzero_for_malformed_saved_report(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-factorial-cli-validation")
        malformed = _valid_factorial_report(module)
        malformed["safe_outputs"]["ordered_arm_count"] = False
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
        self.assertIn("safe_outputs.ordered_arm_count must be an integer", validation["blockers"])


def _run_with_opt_in(module, *, baseline_path: Path, work_dir: Path) -> dict:
    old_value = os.environ.get(module.RUN_OPT_IN_ENV)
    os.environ[module.RUN_OPT_IN_ENV] = "1"
    try:
        return module.run_ontology_factorial_eval(
            baseline_report_path=baseline_path,
            work_dir=work_dir,
        )
    finally:
        if old_value is None:
            os.environ.pop(module.RUN_OPT_IN_ENV, None)
        else:
            os.environ[module.RUN_OPT_IN_ENV] = old_value


def _valid_factorial_report(module) -> dict:
    temp_dir = _paths.fresh_test_dir("mail-domain-hard-factorial-valid-report")
    baseline_path, work_dir = kg_tests._write_synthetic_inputs(module.kg_eval, temp_dir)
    return copy.deepcopy(_run_with_opt_in(module, baseline_path=baseline_path, work_dir=work_dir))


if __name__ == "__main__":
    unittest.main()
