from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import _paths  # noqa: F401
from formowl_contract import Observation, PermissionScope, sha256_json
from formowl_mail import build_mail_evidence_bundle


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "mail_full_pst_domain_hard_case_eval.py"
)


def _load_eval_module():
    spec = importlib.util.spec_from_file_location(
        "mail_full_pst_domain_hard_case_eval",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load hard-domain eval script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailFullPstDomainHardCaseEvalScriptTests(unittest.TestCase):
    def test_domain_manifest_has_10_cases_per_domain_without_pass_preflight(self) -> None:
        module = _load_eval_module()
        bundle = _domain_synthetic_bundle(module)

        cases = module._generate_domain_case_manifest(
            bundle,
            archive_sha256="sha256:" + "a" * 64,
            parser_version="0.1.0",
        )

        self.assertEqual(len(cases), 100)
        self.assertEqual(len({case.case_id for case in cases}), 100)
        domain_counts = {}
        result_counts = {}
        pattern_counts = {}
        for case in cases:
            domain_counts[case.domain] = domain_counts.get(case.domain, 0) + 1
            result_counts[case.result_kind] = result_counts.get(case.result_kind, 0) + 1
            pattern_counts[case.pattern] = pattern_counts.get(case.pattern, 0) + 1
            if case.result_kind == "owner_match":
                self.assertGreaterEqual(len(case.required_source_observation_ids), 2)
                self.assertEqual(case.required_match_count, 2)
            if case.result_kind == "no_match":
                self.assertNotIn("unconfirmed-", case.query_text)
                self.assertNotIn("sha256", case.query_text)
        self.assertEqual(set(domain_counts), set(module.DOMAINS))
        self.assertTrue(all(count == 10 for count in domain_counts.values()))
        self.assertEqual(
            result_counts, {"owner_match": 80, "no_match": 10, "permission_denied": 10}
        )
        self.assertEqual(set(pattern_counts), set(module.PATTERNS))
        self.assertTrue(all(count > 0 for count in pattern_counts.values()))

    def test_validate_report_accepts_low_pass_rate_baseline(self) -> None:
        module = _load_eval_module()
        report = _valid_baseline_report(module, passed_count=37)

        validation = module.validate_report(report)

        self.assertTrue(validation["passed"], validation["blockers"])
        self.assertTrue(
            validation["claim_boundary"][
                "supports_operator_provided_full_pst_domain_hard_baseline_claim"
            ]
        )
        self.assertFalse(validation["claim_boundary"]["supports_production_ready_claim"])

    def test_validate_report_rejects_stale_domain_and_pattern_counts(self) -> None:
        module = _load_eval_module()
        report = _valid_baseline_report(module, passed_count=37)
        report["safe_outputs"]["domain_hash_counts"][sha256_json(module.DOMAINS[0])] -= 1
        report["safe_outputs"]["pattern_hash_counts"][sha256_json("multi_message")] -= 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.domain_hash_counts does not match case rows",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.pattern_hash_counts does not match case rows",
            validation["blockers"],
        )

    def test_measured_case_quality_metrics_are_not_baseline_blockers(self) -> None:
        module = _load_eval_module()
        report = _valid_baseline_report(module, passed_count=37)
        report["metrics"]["permission_denied_cases_redacted"] = False
        report["metrics"]["no_match_cases_non_leaking"] = False

        validation = module.validate_report(report)

        self.assertTrue(validation["passed"], validation["blockers"])
        self.assertTrue(
            validation["claim_boundary"][
                "supports_operator_provided_full_pst_domain_hard_baseline_claim"
            ]
        )

    def test_validate_report_rejects_duplicate_response_hashes(self) -> None:
        module = _load_eval_module()
        report = _valid_baseline_report(module, passed_count=37)
        rows = report["safe_outputs"]["case_rows"]
        rows[1]["response_hash"] = rows[0]["response_hash"]
        report["safe_outputs"]["case_result_hash"] = sha256_json(rows)
        report["safe_outputs"]["unique_response_hash_count"] = 99
        report["safe_outputs"]["duplicate_response_hash_count"] = 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.duplicate_response_hash_count must be 0", validation["blockers"]
        )
        self.assertIn("case rows must contain 100 unique response hashes", validation["blockers"])

    def test_validate_report_rejects_public_query_or_evidence_fields_without_echo(self) -> None:
        module = _load_eval_module()
        report = _valid_baseline_report(module, passed_count=37)
        report["safe_outputs"]["case_rows"][0]["query_text"] = "private query"
        report["safe_outputs"]["case_rows"][1]["message_body"] = "private body"
        report["safe_outputs"]["domain_hash_counts"]["C:\\private\\archive.pst"] = 1
        report["claim_boundary"]["private_query_text"] = False

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        rendered = json.dumps(validation, sort_keys=True)
        self.assertNotIn("private query", rendered)
        self.assertNotIn("private body", rendered)
        self.assertNotIn("query_text", rendered)
        self.assertNotIn("archive.pst", rendered.lower())
        self.assertNotIn("private_query_text", rendered)
        self.assertTrue(
            any(
                blocker.startswith("case_row contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.startswith("public report contains evidence field: sha256:")
                for blocker in validation["blockers"]
            )
        )

    def test_build_report_preserves_private_manifest_and_public_report_omits_path(self) -> None:
        module = _load_eval_module()
        bundle = _domain_synthetic_bundle(module)
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-report")
        work_dir = temp_dir / "work"
        module._prepare_work_dir(work_dir)

        report = module._build_report_for_bundle(
            bundle,
            work_dir=work_dir,
            archive_sha256="sha256:" + "a" * 64,
            parser_version="0.1.0",
            fixture_size_bytes=1234,
            fixture_header_ok=True,
            receipt_uploaded=True,
            asset_count=1,
            job_count=1,
            extractor_run_count=1,
            observation_count=500,
            mail_evidence_table_count=8,
            mail_evidence_row_count=300,
            mail_evidence_statement_count=300,
            parser_worker_count=4,
            extraction_config_shape_hash=_hash("config"),
            fixture_hash_elapsed_ms=1,
            upload_elapsed_ms=1,
            import_elapsed_ms=1,
            bundle_read_elapsed_ms=0,
        )
        report["metrics"]["raw_leak_guard_passed"] = module._public_outputs_are_safe(report)
        report["metrics"]["domain_hard_case_baseline_completed"] = (
            module._domain_hard_baseline_completed(report)
        )
        report["claim_boundary"][
            "supports_operator_provided_full_pst_domain_hard_baseline_claim"
        ] = report["metrics"]["domain_hard_case_baseline_completed"]
        report["validation"] = module.validate_report(report)

        private_manifest = work_dir / "artifacts" / module.PRIVATE_MANIFEST_NAME
        self.assertTrue(private_manifest.is_file())
        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn(str(private_manifest).lower(), rendered)
        self.assertNotIn(module.PRIVATE_MANIFEST_NAME.lower(), rendered)
        self.assertFalse(report["safe_outputs"]["work_dir_cleaned"])

    def test_blocked_report_requires_opt_in_and_stays_safe(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-blocked")
        old_value = module.os.environ.pop(module.FULL_EVAL_OPT_IN_ENV, None)
        try:
            report = module.run_domain_hard_case_eval(temp_dir / "work")
        finally:
            if old_value is not None:
                module.os.environ[module.FULL_EVAL_OPT_IN_ENV] = old_value

        self.assertEqual(
            report["metrics"]["blocked_reason"],
            "domain_hard_eval_requires_explicit_opt_in",
        )
        self.assertFalse(report["metrics"]["domain_hard_case_baseline_completed"])
        self.assertFalse(report["safe_outputs"]["full_parse_executed"])
        self.assertTrue(report["validation"]["passed"])
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("archive.pst", rendered)
        self.assertNotIn("readpst", rendered)
        self.assertNotIn("traceback", rendered)

    def test_blocked_report_rejects_invalid_reason_without_echo(self) -> None:
        module = _load_eval_module()
        report = module._blocked_report("missing_fixture", work_dir_cleaned=False)
        report["metrics"]["blocked_reason"] = "private customer path archive.pst"
        report["safe_outputs"]["case_count"] = False
        report["safe_outputs"]["work_dir_cleaned"] = "not bool"

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("blocked_reason must be a configured safe enum", validation["blockers"])
        self.assertIn("blocked report case_count must be 0", validation["blockers"])
        self.assertIn("blocked report work_dir_cleaned must be boolean", validation["blockers"])
        rendered = json.dumps(validation, sort_keys=True).lower()
        self.assertNotIn("private customer", rendered)
        self.assertNotIn("archive.pst", rendered)

    def test_missing_fixture_blocked_report_stays_safe(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-missing-fixture")
        old_value = module.os.environ.get(module.FULL_EVAL_OPT_IN_ENV)
        module.os.environ[module.FULL_EVAL_OPT_IN_ENV] = "1"
        try:
            report = module.run_domain_hard_case_eval(
                temp_dir / "work",
                pst_fixture=temp_dir / "missing" / "archive.pst",
            )
        finally:
            if old_value is None:
                module.os.environ.pop(module.FULL_EVAL_OPT_IN_ENV, None)
            else:
                module.os.environ[module.FULL_EVAL_OPT_IN_ENV] = old_value

        self.assertEqual(report["metrics"]["blocked_reason"], "missing_fixture")
        self.assertFalse(report["safe_outputs"]["full_parse_executed"])
        self.assertTrue(report["validation"]["passed"], report["validation"]["blockers"])
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("archive.pst", rendered)
        self.assertNotIn(str(temp_dir).lower(), rendered)

    def test_cleanup_is_opt_in_and_guarded_by_sentinel(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-domain-hard-cleanup")
        work_dir = temp_dir / "marked"
        module._prepare_work_dir(work_dir)
        (work_dir / "scratch").mkdir()
        self.assertFalse(module._cleanup(temp_dir))
        self.assertTrue(temp_dir.exists())

        self.assertTrue(module._cleanup(work_dir))
        self.assertFalse(work_dir.exists())


def _valid_baseline_report(module, *, passed_count: int) -> dict:
    rows = _case_rows(module, passed_count=passed_count)
    aggregate = module._aggregate_scores(rows)
    domain_counts = module._row_counts(rows, "domain_hash")
    pattern_counts = module._row_counts(rows, "pattern_hash")
    result_kind_counts = module._row_counts(rows, "result_kind")
    domain_passed_counts = module._passed_row_counts(rows, "domain_hash")
    pattern_passed_counts = module._passed_row_counts(rows, "pattern_hash")
    return {
        "report_type": module.REPORT_TYPE,
        "generated_at": module.NOW,
        "metrics": {
            "fixture_present": True,
            "fixture_stream_hash_succeeded": True,
            "pst_signature_verified": True,
            "full_parse_executed": True,
            "no_sampling_config_used": True,
            "real_parser_invoked": True,
            "mail_observations_persisted": True,
            "mail_evidence_rows_persisted": True,
            "domain_case_manifest_generated": True,
            "domain_case_count_is_100": True,
            "each_domain_has_10_cases": True,
            "each_domain_has_no_match_case": True,
            "each_domain_has_permission_denied_case": True,
            "each_domain_has_positive_patterns": True,
            "positive_cases_require_multi_evidence": True,
            "pattern_coverage_met": True,
            "scored_case_count_is_100": True,
            "pass_rate_recorded": True,
            "row_derived_validation_recomputed": True,
            "permission_denied_cases_redacted": True,
            "no_match_cases_non_leaking": True,
            "private_manifest_preserved": True,
            "raw_archive_retention_decision_recorded": True,
            "kg_wiki_side_effects_absent": True,
            "cleanup_policy_respected": True,
            "raw_leak_guard_passed": True,
            "domain_hard_case_baseline_completed": True,
        },
        "safe_outputs": {
            "fixture_id_hash": _hash("fixture-id"),
            "fixture_sha256": _hash("fixture-sha"),
            "fixture_size_bytes": 3_152_323_584,
            "full_parse_executed": True,
            "sample_message_limit": 0,
            "sampling_config_used": False,
            "parser_adapter_contract_hash": _hash("parser-contract"),
            "parser_version_hash": _hash("parser-version"),
            "extraction_config_shape_hash": _hash("extraction-config"),
            "asset_count": 1,
            "job_count": 1,
            "extractor_run_count": 1,
            "observation_count": 500,
            "message_count": 180,
            "folder_occurrence_count": 1,
            "body_segment_count": 180,
            "attachment_occurrence_count": 0,
            "parse_warning_count": 0,
            "parse_warning_codes_hash": _hash("warnings"),
            "mail_evidence_table_count": 8,
            "mail_evidence_row_count": 400,
            "mail_evidence_statement_count": 400,
            "parser_worker_count": 4,
            "case_policy_hash": _hash("policy"),
            "case_manifest_hash": sha256_json([row["case_manifest_entry_hash"] for row in rows]),
            "case_result_hash": sha256_json(rows),
            "private_manifest_hash": _hash("private-manifest"),
            "private_manifest_case_count": 100,
            "private_manifest_write_elapsed_ms": 1,
            "fixture_hash_elapsed_ms": 1,
            "upload_elapsed_ms": 1,
            "import_elapsed_ms": 1,
            "bundle_read_elapsed_ms": 0,
            "case_manifest_elapsed_ms": 1,
            "scoring_elapsed_ms": 1,
            "query_runner_setup_elapsed_ms": 0,
            "case_query_loop_elapsed_ms": 1,
            "case_count": aggregate["case_count"],
            "scored_case_count": aggregate["scored_case_count"],
            "passed_case_count": aggregate["passed_case_count"],
            "failed_case_count": aggregate["failed_case_count"],
            "pass_rate_basis_points": aggregate["pass_rate_basis_points"],
            "positive_case_count": result_kind_counts["owner_match"],
            "permission_denied_case_count": result_kind_counts["permission_denied"],
            "no_match_case_count": result_kind_counts["no_match"],
            "unique_case_id_hash_count": len({row["case_id_hash"] for row in rows}),
            "unique_response_hash_count": len({row["response_hash"] for row in rows}),
            "duplicate_response_hash_count": 0,
            "domain_hash_counts": domain_counts,
            "domain_hash_passed_counts": domain_passed_counts,
            "pattern_hash_counts": pattern_counts,
            "pattern_hash_passed_counts": pattern_passed_counts,
            "result_kind_counts": result_kind_counts,
            "case_rows": copy.deepcopy(rows),
            "artifact_retained_entry_count": 2,
            "artifact_retained_size_bytes": 200,
            "staging_leftover_count": 0,
            "scratch_leftover_count": 0,
            "staging_retained_entry_count": 0,
            "staging_retained_size_bytes": 0,
            "scratch_retained_entry_count": 0,
            "scratch_retained_size_bytes": 0,
            "work_dir_cleaned": False,
        },
        "claim_boundary": {
            "supports_operator_provided_full_pst_domain_hard_baseline_claim": True,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_general_full_pst_parser_readiness_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_business_answer_generation_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_raw_mail_access_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }


def _case_rows(module, *, passed_count: int) -> list[dict]:
    rows: list[dict] = []
    index = 0
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
    for domain in module.DOMAINS:
        for domain_index, pattern in enumerate(patterns):
            if pattern == "no_match":
                result_kind = "no_match"
                visible = citation = hidden_bundle = hidden_message = 0
                required = matched = 0
                warning = 1
            elif pattern == "permission_denied":
                result_kind = "permission_denied"
                visible = citation = matched = 0
                hidden_bundle = hidden_message = 1
                required = 0
                warning = 1
            else:
                result_kind = "owner_match"
                visible = citation = required = matched = 2
                hidden_bundle = hidden_message = 0
                warning = 0
            status = "passed" if index < passed_count else "failed"
            if status == "failed":
                matched = 0 if result_kind == "owner_match" else matched
            rows.append(
                {
                    "case_id_hash": _hash(f"case-{index}"),
                    "case_manifest_entry_hash": _hash(f"manifest-{index}"),
                    "domain_hash": sha256_json(domain),
                    "intent_kind_hash": _hash(f"{domain}-{domain_index}"),
                    "pattern_hash": sha256_json(pattern),
                    "result_kind": result_kind,
                    "status": status,
                    "response_hash": _hash(f"response-{index}"),
                    "visible_result_count": visible,
                    "citation_count": citation,
                    "hidden_bundle_count": hidden_bundle,
                    "hidden_message_count": hidden_message,
                    "required_evidence_count": required,
                    "matched_required_evidence_count": matched,
                    "forbidden_evidence_match_count": 0,
                    "warning_count": warning,
                    "elapsed_ms": 1,
                }
            )
            index += 1
    return rows


def _domain_synthetic_bundle(module):
    permission_scope = PermissionScope.project("project_formowl")
    observations = [
        Observation(
            observation_id="obs_folder_001",
            asset_id="asset_mail_domain_eval",
            extractor_run_id="run_mail_domain_eval",
            observation_type="mail_folder_occurrence",
            modality="mail",
            text="Inbox",
            location={
                "archive_id": "archive_domain_eval",
                "mailbox_id": "mailbox_domain_eval",
                "folder_path_hash": "sha256:folder-inbox",
            },
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-07-07T12:00:00+00:00",
            payload={
                "archive_id": "archive_domain_eval",
                "mailbox_id": "mailbox_domain_eval",
                "folder_path_hash": "sha256:folder-inbox",
                "folder_label": "Inbox",
            },
        )
    ]
    message_index = 0
    for domain in module.DOMAINS:
        domain_tokens = sorted(module.DOMAIN_VOCABULARY[domain])[:6]
        domain_text = " ".join(domain_tokens)
        sender = f"{domain.replace('_', '')} owner"
        for offset in range(12):
            message_id = f"<domain-{message_index:03d}@example.test>"
            occurrence_id = f"mailocc_domain_{message_index:03d}"
            thread_id = f"thread_domain_{message_index // 3:03d}"
            fingerprint = sha256_json({"message": message_index})
            base_location = {
                "archive_id": "archive_domain_eval",
                "mailbox_id": "mailbox_domain_eval",
                "folder_path_hash": "sha256:folder-inbox",
                "message_id": message_id,
                "message_occurrence_id": occurrence_id,
                "thread_id": thread_id,
            }
            observations.append(
                Observation(
                    observation_id=f"obs_msg_domain_{message_index:03d}",
                    asset_id="asset_mail_domain_eval",
                    extractor_run_id="run_mail_domain_eval",
                    observation_type="email_message",
                    modality="mail",
                    text=f"{domain_text} delay risk approved",
                    location={**base_location, "message_index": message_index + 1},
                    confidence=1.0,
                    permission_scope=permission_scope,
                    created_at="2026-07-07T12:00:00+00:00",
                    payload={
                        "archive_id": "archive_domain_eval",
                        "mailbox_id": "mailbox_domain_eval",
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": thread_id,
                        "subject": f"{domain_text} delay risk approved",
                        "normalized_subject": f"{domain_text} delay risk approved",
                        "sender": sender,
                        "sent_at": f"2026-07-07T12:{offset:02d}:00+00:00",
                        "body_hash": sha256_json({"body": message_index}),
                        "message_fingerprint": fingerprint,
                        "fingerprint_policy": "formowl_mail_fingerprint_v1",
                    },
                )
            )
            observations.append(
                Observation(
                    observation_id=f"obs_body_domain_{message_index:03d}",
                    asset_id="asset_mail_domain_eval",
                    extractor_run_id="run_mail_domain_eval",
                    observation_type="email_body_segment",
                    modality="mail",
                    text=(
                        f"{domain_text} delay risk approved blocked change "
                        f"evidence token{message_index:03d}"
                    ),
                    location={**base_location, "body_segment_index": 1},
                    confidence=1.0,
                    permission_scope=permission_scope,
                    created_at="2026-07-07T12:00:00+00:00",
                    payload={
                        "archive_id": "archive_domain_eval",
                        "mailbox_id": "mailbox_domain_eval",
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": thread_id,
                        "body_segment_index": 1,
                        "message_fingerprint": fingerprint,
                    },
                )
            )
            message_index += 1
    return build_mail_evidence_bundle(
        observations,
        workspace_id="workspace_formowl",
        owner_user_id="user_full_pst_domain_hard_case_eval_owner",
        source_asset_id="asset_mail_domain_eval",
        archive_sha256="sha256:" + "a" * 64,
        parser_name="pst_mail_archive_extractor",
        parser_version="0.1.0",
        upload_session_id="upload_session_domain_eval",
        created_at="2026-07-07T12:00:00+00:00",
    )


def _hash(value: str) -> str:
    return "sha256:" + sha256_json(value)[-64:]


if __name__ == "__main__":
    unittest.main()
