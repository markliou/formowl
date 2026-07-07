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


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mail_full_pst_100_case_eval.py"


def _load_eval_module():
    spec = importlib.util.spec_from_file_location(
        "mail_full_pst_100_case_eval",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load full PST eval script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailFullPst100CaseEvalScriptTests(unittest.TestCase):
    def test_validate_report_accepts_hash_status_count_success_shape(self) -> None:
        module = _load_eval_module()

        validation = module.validate_report(_valid_success_report())

        self.assertTrue(validation["passed"])
        self.assertTrue(
            validation["claim_boundary"]["supports_operator_provided_full_pst_100_case_eval_claim"]
        )
        self.assertFalse(validation["claim_boundary"]["supports_production_ready_claim"])

    def test_validate_report_rejects_98_of_100_and_aggregate_mismatch(self) -> None:
        module = _load_eval_module()
        report = _valid_success_report()
        for index in (0, 1):
            report["safe_outputs"]["case_rows"][index]["status"] = "failed"
        report["safe_outputs"]["passed_case_count"] = 98
        report["safe_outputs"]["failed_case_count"] = 2
        report["safe_outputs"]["pass_rate_basis_points"] = 9800

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.passed_case_count must be at least 99",
            validation["blockers"],
        )
        self.assertIn(
            "case row pass/fail totals do not satisfy 99/100 threshold",
            validation["blockers"],
        )

    def test_validate_report_rejects_duplicate_case_and_response_hashes(self) -> None:
        module = _load_eval_module()
        report = _valid_success_report()
        rows = report["safe_outputs"]["case_rows"]
        rows[1]["case_id_hash"] = rows[0]["case_id_hash"]
        rows[1]["response_hash"] = rows[0]["response_hash"]
        report["safe_outputs"]["unique_case_id_hash_count"] = 99
        report["safe_outputs"]["unique_response_hash_count"] = 99
        report["safe_outputs"]["duplicate_response_hash_count"] = 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("safe_outputs.unique_case_id_hash_count must be 100", validation["blockers"])
        self.assertIn(
            "safe_outputs.duplicate_response_hash_count must be 0", validation["blockers"]
        )
        self.assertIn("case rows must contain 100 unique case hashes", validation["blockers"])
        self.assertIn("case rows must contain 100 unique response hashes", validation["blockers"])

    def test_validate_report_rejects_category_counts_that_do_not_match_rows(self) -> None:
        module = _load_eval_module()
        report = _valid_success_report()
        report["safe_outputs"]["category_counts"]["cat_keyword"] -= 1
        report["safe_outputs"]["category_counts"]["cat_topic_pair"] += 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.category_counts does not match case rows",
            validation["blockers"],
        )

    def test_validate_report_rejects_category_passed_counts_that_do_not_match_rows(
        self,
    ) -> None:
        module = _load_eval_module()
        report = _valid_success_report()
        report["safe_outputs"]["category_passed_counts"]["cat_ai_progress"] += 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.category_passed_counts does not match case rows",
            validation["blockers"],
        )

    def test_validate_report_rejects_case_result_hash_not_bound_to_case_rows(self) -> None:
        module = _load_eval_module()
        report = _valid_success_report()
        report["safe_outputs"]["case_rows"][0]["warning_count"] += 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.case_result_hash does not match case rows",
            validation["blockers"],
        )

    def test_validate_report_rejects_bool_counts_at_aggregate_and_case_levels(self) -> None:
        module = _load_eval_module()
        report = _valid_success_report()
        report["safe_outputs"]["message_count"] = True
        report["safe_outputs"]["case_rows"][0]["visible_result_count"] = True

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.message_count must be a positive integer", validation["blockers"]
        )
        self.assertIn(
            "case_row.visible_result_count must be a non-negative integer", validation["blockers"]
        )

    def test_validate_report_rejects_nested_raw_leaks_without_echoing_values(self) -> None:
        module = _load_eval_module()
        report = _valid_success_report()
        report["raw_debug_path"] = "C:\\private\\archive.pst"
        report["safe_outputs"]["case_rows"][0]["query_text"] = "C:\\private\\archive.pst"
        report["safe_outputs"]["case_rows"][1]["mail_body"] = "private mail body"

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        rendered = json.dumps(validation, sort_keys=True)
        self.assertNotIn("C:\\private", rendered)
        self.assertNotIn("archive.pst", rendered)
        self.assertNotIn("private mail body", rendered)
        self.assertNotIn("query_text", rendered)
        self.assertTrue(
            any(
                blocker.startswith("report contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
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

    def test_validate_report_rejects_success_without_citations_and_denied_content(self) -> None:
        module = _load_eval_module()
        report = _valid_success_report()
        owner_row = next(
            row
            for row in report["safe_outputs"]["case_rows"]
            if row["result_kind"] == "owner_match"
        )
        owner_row["citation_count"] = 0
        owner_row["matched_required_evidence_count"] = 0
        denied_row = next(
            row
            for row in report["safe_outputs"]["case_rows"]
            if row["result_kind"] == "permission_denied"
        )
        denied_row["visible_result_count"] = 1

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "passed owner_match case must have visible evidence and citation",
            validation["blockers"],
        )
        self.assertIn(
            "passed owner_match case must match required evidence",
            validation["blockers"],
        )
        self.assertIn(
            "passed permission_denied case must expose no evidence",
            validation["blockers"],
        )

    def test_blocked_report_requires_no_opt_in_and_stays_safe(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-full-pst-100-case-blocked")
        old_value = module.os.environ.pop(module.FULL_EVAL_OPT_IN_ENV, None)
        try:
            report = module.run_full_pst_100_case_eval(temp_dir / "work")
        finally:
            if old_value is not None:
                module.os.environ[module.FULL_EVAL_OPT_IN_ENV] = old_value

        self.assertEqual(report["metrics"]["blocked_reason"], "full_eval_requires_explicit_opt_in")
        self.assertFalse(report["metrics"]["full_pst_100_case_eval_passed"])
        self.assertFalse(report["safe_outputs"]["full_parse_executed"])
        self.assertEqual(report["safe_outputs"]["case_count"], 0)
        self.assertTrue(report["validation"]["passed"])
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("archive.pst", rendered)
        self.assertNotIn("readpst", rendered)
        self.assertNotIn("traceback", rendered)

    def test_cleanup_refuses_unmarked_work_dir_without_deleting_contents(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-full-pst-100-case-cleanup-guard")
        work_dir = temp_dir / "operator-owned"
        work_dir.mkdir()
        keep_file = work_dir / "keep.txt"
        keep_file.write_text("keep", encoding="utf-8")

        self.assertFalse(module._cleanup(work_dir))

        self.assertTrue(work_dir.exists())
        self.assertEqual(keep_file.read_text(encoding="utf-8"), "keep")

    def test_prepare_work_dir_refuses_unmarked_nonempty_directory(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-full-pst-100-case-prepare-guard")
        work_dir = temp_dir / "operator-owned"
        work_dir.mkdir()
        keep_file = work_dir / "keep.txt"
        keep_file.write_text("keep", encoding="utf-8")

        with self.assertRaises(RuntimeError):
            module._prepare_work_dir(work_dir)

        self.assertTrue(work_dir.exists())
        self.assertEqual(keep_file.read_text(encoding="utf-8"), "keep")

    def test_cleanup_removes_only_marked_work_dir(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-full-pst-100-case-cleanup-marked")
        work_dir = temp_dir / "marked"
        module._prepare_work_dir(work_dir)
        (work_dir / "scratch").mkdir()
        (work_dir / "scratch" / "safe-temp.txt").write_text("temp", encoding="utf-8")

        self.assertTrue(module._cleanup(work_dir))

        self.assertFalse(work_dir.exists())

    def test_case_manifest_generation_produces_exactly_100_unique_cases(self) -> None:
        module = _load_eval_module()
        bundle = _large_synthetic_bundle()

        cases = module._generate_case_manifest(
            bundle,
            archive_sha256="sha256:" + "a" * 64,
            parser_version="0.1.0",
            case_count=100,
        )

        self.assertEqual(len(cases), 100)
        self.assertEqual(len({case.case_id for case in cases}), 100)
        categories = {case.category for case in cases}
        self.assertIn("permission_denied", categories)
        self.assertIn("no_match", categories)
        self.assertIn("ai_progress_topic", categories)
        scores = module._score_cases(bundle, cases)
        self.assertEqual(sum(1 for score in scores if score.passed), 100)
        self.assertEqual(sum(1 for case in cases if case.result_kind == "owner_match"), 90)
        self.assertEqual(sum(1 for case in cases if case.result_kind == "no_match"), 5)
        self.assertEqual(sum(1 for case in cases if case.result_kind == "permission_denied"), 5)

    def test_score_cases_reuses_one_query_handler_for_batch(self) -> None:
        module = _load_eval_module()
        bundle = _large_synthetic_bundle()
        cases = [
            module._positive_case(
                category="body_keyword",
                query_text="alpha000",
                required_observation_ids=("obs_body_000",),
                seed="unit",
            ),
            module._positive_case(
                category="body_keyword",
                query_text="alpha001",
                required_observation_ids=("obs_body_001",),
                seed="unit",
            ),
            module._EvalCase(
                case_id="mailevalcase_unit_no_match",
                category="no_match",
                result_kind="no_match",
                query_text="formowl_no_match_canary_unit",
                requester_user_id=module.ACTOR_USER_ID,
                required_source_observation_ids=(),
                required_match_count=0,
            ),
        ]
        original = module.build_mail_evidence_query_handler
        call_count = 0

        def spy(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return original(*args, **kwargs)

        module.build_mail_evidence_query_handler = spy
        try:
            scores = module._score_cases(bundle, cases)
        finally:
            module.build_mail_evidence_query_handler = original

        self.assertEqual(call_count, 1)
        self.assertTrue(all(score.passed for score in scores))

    def test_response_shape_hash_is_case_bound_without_public_detail(self) -> None:
        module = _load_eval_module()
        response = {
            "jsonrpc": "2.0",
            "id": "case_one",
            "result": {
                "isError": False,
                "content": [
                    {
                        "type": "json",
                        "json": {
                            "status": "ok",
                            "data": {
                                "status": "ok",
                                "query_hash": _hash("query"),
                                "evidence_snippets": [],
                                "citations": [],
                                "redaction_counts": {
                                    "hidden_bundles": 0,
                                    "hidden_messages": 0,
                                },
                                "warnings": ["no_visible_mail_evidence_matched"],
                            },
                        },
                    }
                ],
            },
        }
        other_response = copy.deepcopy(response)
        other_response["id"] = "case_two"

        self.assertNotEqual(
            module._response_shape_hash(response),
            module._response_shape_hash(other_response),
        )

    def test_validate_report_cli_returns_safe_failure_for_malformed_input(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-full-pst-100-case-malformed")
        input_path = temp_dir / "bad-report.json"
        output_path = temp_dir / "validation.json"
        input_path.write_text("{ bad json C:\\private\\archive.pst", encoding="utf-8")

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
        rendered = json.dumps(validation, sort_keys=True)
        self.assertNotIn("C:\\private", rendered)
        self.assertNotIn("archive.pst", rendered)
        self.assertNotIn("traceback", rendered.lower())


def _valid_success_report() -> dict:
    rows = _case_rows()
    category_counts: dict[str, int] = {}
    category_passed_counts: dict[str, int] = {}
    for row in rows:
        category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1
        if row["status"] == "passed":
            category_passed_counts[row["category"]] = (
                category_passed_counts.get(row["category"], 0) + 1
            )
    for category in (
        "cat_keyword",
        "cat_topic_pair",
        "cat_actor_pair",
        "cat_thread",
        "cat_multi",
        "cat_ai_progress",
        "cat_no_match",
        "cat_permission_denied",
    ):
        category_passed_counts.setdefault(category, 0)
    return {
        "report_type": "mail_full_pst_100_case_eval",
        "generated_at": "2026-07-07T12:00:00+00:00",
        "metrics": {
            "fixture_present": True,
            "fixture_stream_hash_succeeded": True,
            "pst_signature_verified": True,
            "full_parse_executed": True,
            "no_sampling_config_used": True,
            "real_parser_invoked": True,
            "upload_session_created": True,
            "asset_registered": True,
            "ingestion_job_succeeded": True,
            "extractor_run_succeeded": True,
            "mail_observations_persisted": True,
            "mail_evidence_rows_persisted": True,
            "case_manifest_generated": True,
            "case_count_is_100": True,
            "scored_case_count_is_100": True,
            "passed_case_threshold_met": True,
            "aggregate_scoring_recomputed": True,
            "permission_denied_cases_redacted": True,
            "no_match_cases_non_leaking": True,
            "message_limit_not_reached": True,
            "raw_archive_retention_decision_recorded": True,
            "kg_wiki_side_effects_absent": True,
            "cleanup_succeeded": True,
            "raw_leak_guard_passed": True,
            "full_pst_100_case_eval_passed": True,
        },
        "safe_outputs": {
            "fixture_id_hash": _hash("fixture-id"),
            "fixture_sha256": _hash("fixture-sha"),
            "fixture_size_bytes": 3_152_323_584,
            "full_parse_executed": True,
            "sample_message_limit": 0,
            "sampling_config_used": False,
            "message_limit_warning_count": 0,
            "parser_adapter_contract_hash": _hash("parser-contract"),
            "parser_version_hash": _hash("parser-version"),
            "extraction_config_shape_hash": _hash("extraction-config"),
            "asset_count": 1,
            "job_count": 1,
            "extractor_run_count": 1,
            "observation_count": 300,
            "message_count": 100,
            "folder_occurrence_count": 1,
            "body_segment_count": 100,
            "attachment_occurrence_count": 0,
            "parse_warning_count": 0,
            "parse_warning_codes_hash": _hash("parse-warnings"),
            "mail_evidence_table_count": 8,
            "mail_evidence_row_count": 250,
            "mail_evidence_statement_count": 250,
            "import_elapsed_ms": 1,
            "case_manifest_elapsed_ms": 1,
            "scoring_elapsed_ms": 1,
            "parser_worker_count": 4,
            "case_policy_hash": _hash("case-policy"),
            "case_manifest_hash": sha256_json([row["case_manifest_entry_hash"] for row in rows]),
            "case_result_hash": sha256_json(rows),
            "case_count": 100,
            "scored_case_count": 100,
            "passed_case_count": 100,
            "failed_case_count": 0,
            "pass_rate_basis_points": 10000,
            "owner_match_case_count": 90,
            "permission_denied_case_count": 5,
            "no_match_case_count": 5,
            "ai_progress_related_case_count": 5,
            "ai_progress_related_passed_count": 5,
            "unique_case_id_hash_count": 100,
            "unique_response_hash_count": 100,
            "duplicate_response_hash_count": 0,
            "category_counts": category_counts,
            "category_passed_counts": category_passed_counts,
            "case_rows": copy.deepcopy(rows),
            "staging_leftover_count": 0,
            "scratch_leftover_count": 0,
            "work_dir_cleaned": True,
        },
        "claim_boundary": {
            "supports_operator_provided_full_pst_100_case_eval_claim": True,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_general_full_pst_parser_readiness_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_raw_mail_access_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }


def _case_rows() -> list[dict]:
    layout = [
        ("cat_keyword", "owner_match", 35),
        ("cat_topic_pair", "owner_match", 20),
        ("cat_actor_pair", "owner_match", 15),
        ("cat_thread", "owner_match", 10),
        ("cat_multi", "owner_match", 5),
        ("cat_ai_progress", "owner_match", 5),
        ("cat_no_match", "no_match", 5),
        ("cat_permission_denied", "permission_denied", 5),
    ]
    rows: list[dict] = []
    index = 0
    for category, result_kind, count in layout:
        for _ in range(count):
            if result_kind == "owner_match":
                visible = citation = matched = 1
                hidden_bundle = hidden_message = 0
                warning = 0
            elif result_kind == "permission_denied":
                visible = citation = matched = 0
                hidden_bundle = hidden_message = 1
                warning = 1
            else:
                visible = citation = matched = hidden_bundle = hidden_message = 0
                warning = 1
            rows.append(
                {
                    "case_id_hash": _hash(f"case-{index}"),
                    "case_manifest_entry_hash": _hash(f"manifest-{index}"),
                    "category": category,
                    "result_kind": result_kind,
                    "status": "passed",
                    "response_hash": _hash(f"response-{index}"),
                    "visible_result_count": visible,
                    "citation_count": citation,
                    "hidden_bundle_count": hidden_bundle,
                    "hidden_message_count": hidden_message,
                    "matched_required_evidence_count": matched,
                    "forbidden_evidence_match_count": 0,
                    "warning_count": warning,
                }
            )
            index += 1
    return rows


def _large_synthetic_bundle():
    permission_scope = PermissionScope.project("project_formowl")
    observations = [
        Observation(
            observation_id="obs_folder_001",
            asset_id="asset_mail_eval",
            extractor_run_id="run_mail_eval",
            observation_type="mail_folder_occurrence",
            modality="mail",
            text="Inbox",
            location={
                "archive_id": "archive_eval",
                "mailbox_id": "mailbox_eval",
                "folder_path_hash": "sha256:folder-inbox",
            },
            confidence=1.0,
            permission_scope=permission_scope,
            created_at="2026-07-07T12:00:00+00:00",
            payload={
                "archive_id": "archive_eval",
                "mailbox_id": "mailbox_eval",
                "folder_path_hash": "sha256:folder-inbox",
                "folder_label": "Inbox",
            },
        )
    ]
    for index in range(120):
        message_id = f"<eval-{index:03d}@example.test>"
        occurrence_id = f"mailocc_eval_{index:03d}"
        thread_id = f"thread_eval_{index // 3:03d}"
        fingerprint = sha256_json({"message": index})
        base_location = {
            "archive_id": "archive_eval",
            "mailbox_id": "mailbox_eval",
            "folder_path_hash": "sha256:folder-inbox",
            "message_id": message_id,
            "message_occurrence_id": occurrence_id,
            "thread_id": thread_id,
        }
        observations.append(
            Observation(
                observation_id=f"obs_msg_{index:03d}",
                asset_id="asset_mail_eval",
                extractor_run_id="run_mail_eval",
                observation_type="email_message",
                modality="mail",
                text=f"Topic {index:03d} model progress",
                location={**base_location, "message_index": index + 1},
                confidence=1.0,
                permission_scope=permission_scope,
                created_at="2026-07-07T12:00:00+00:00",
                payload={
                    "archive_id": "archive_eval",
                    "mailbox_id": "mailbox_eval",
                    "message_id": message_id,
                    "message_occurrence_id": occurrence_id,
                    "thread_id": thread_id,
                    "subject": f"Topic {index:03d} model progress",
                    "normalized_subject": f"topic {index:03d} model progress",
                    "sender": f"owner{index:03d}@example.test",
                    "sent_at": "2026-07-07T12:00:00+00:00",
                    "body_hash": sha256_json({"body": index}),
                    "message_fingerprint": fingerprint,
                    "fingerprint_policy": "formowl_mail_fingerprint_v1",
                },
            )
        )
        observations.append(
            Observation(
                observation_id=f"obs_body_{index:03d}",
                asset_id="asset_mail_eval",
                extractor_run_id="run_mail_eval",
                observation_type="email_body_segment",
                modality="mail",
                text=(
                    f"update progress model alpha{index:03d} beta{index:03d} " f"gamma{index:03d}"
                ),
                location={**base_location, "body_segment_index": 1},
                confidence=1.0,
                permission_scope=permission_scope,
                created_at="2026-07-07T12:00:00+00:00",
                payload={
                    "archive_id": "archive_eval",
                    "mailbox_id": "mailbox_eval",
                    "message_id": message_id,
                    "message_occurrence_id": occurrence_id,
                    "thread_id": thread_id,
                    "body_segment_index": 1,
                    "message_fingerprint": fingerprint,
                },
            )
        )
    return build_mail_evidence_bundle(
        observations,
        workspace_id="workspace_formowl",
        owner_user_id="user_full_pst_100_case_eval_owner",
        source_asset_id="asset_mail_eval",
        archive_sha256="sha256:" + "a" * 64,
        parser_name="pst_mail_archive_extractor",
        parser_version="0.1.0",
        upload_session_id="upload_session_eval",
        created_at="2026-07-07T12:00:00+00:00",
    )


def _hash(value: str) -> str:
    return "sha256:" + sha256_json(value)[-64:]


if __name__ == "__main__":
    unittest.main()
