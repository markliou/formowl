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
