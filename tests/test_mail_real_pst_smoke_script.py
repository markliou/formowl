from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import _paths  # noqa: F401


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mail_real_pst_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "mail_real_pst_smoke",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load real PST smoke script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailRealPstSmokeScriptTests(unittest.TestCase):
    def test_full_mode_is_blocked_without_explicit_opt_in(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-real-pst-smoke-full-blocked")
        original = smoke.os.environ.pop(smoke._FULL_PARSE_OPT_IN_ENV, None)
        try:
            report = smoke.run_mail_real_pst_smoke(temp_dir / "work", mode="full")
        finally:
            if original is not None:
                smoke.os.environ[smoke._FULL_PARSE_OPT_IN_ENV] = original

        self.assertTrue(report["validation"]["passed"])
        self.assertEqual(report["metrics"]["blocked_reason"], "full_parse_requires_explicit_opt_in")
        self.assertFalse(report["metrics"]["real_pst_smoke_passed"])
        self.assertFalse(report["safe_outputs"]["full_parse_executed"])
        self.assertFalse(report["claim_boundary"]["supports_real_pst_sampled_parser_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_pst_full_parser_claim"])
        self.assertFalse(report["claim_boundary"]["supports_full_real_pst_parser_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])

    def test_missing_fixture_cli_returns_safe_nonpassing_report(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-real-pst-smoke-missing-fixture")
        output_path = temp_dir / "report.json"
        missing_fixture = temp_dir / "missing" / "archive.pst"

        exit_code = smoke.main(
            [
                "--pst-fixture",
                str(missing_fixture),
                "--work-dir",
                str(temp_dir / "work"),
                "--output",
                str(output_path),
            ]
        )

        self.assertEqual(exit_code, 1)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(report["metrics"]["blocked_reason"], "missing_fixture")
        self.assertFalse(report["metrics"]["real_pst_smoke_passed"])
        self.assertFalse(report["validation"]["passed"])
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn(str(missing_fixture), rendered)
        self.assertNotIn("archive.pst", rendered)
        self.assertNotIn("traceback", rendered.lower())
        self.assertNotIn("readpst", rendered.lower())
        self.assertFalse(report["claim_boundary"]["supports_real_pst_sampled_parser_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])

    def test_validate_report_accepts_hash_status_count_sampled_success_shape(self) -> None:
        smoke = _load_smoke_module()

        validation = smoke.validate_report(_valid_sampled_success_report())

        self.assertTrue(validation["passed"])
        self.assertTrue(validation["claim_boundary"]["supports_real_pst_sampled_parser_claim"])
        self.assertFalse(validation["claim_boundary"]["supports_real_pst_full_parser_claim"])
        self.assertFalse(validation["claim_boundary"]["supports_production_ready_claim"])

    def test_validate_report_rejects_raw_leaks_overclaims_and_unknown_keys(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_sampled_success_report()
        report["raw_debug_path"] = "C:\\private\\archive.pst"
        report["safe_outputs"]["body_text"] = "private mail body"
        report["claim_boundary"]["supports_production_ready_claim"] = True

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "public report leaks raw paths, credentials, SQL, or backend internals",
            validation["blockers"],
        )
        self.assertIn(
            "forbidden claim is not explicitly false: supports_production_ready_claim",
            validation["blockers"],
        )
        self.assertTrue(
            any(
                blocker.startswith("report contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.startswith("safe_outputs contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.startswith("public report contains evidence field: sha256:")
                for blocker in validation["blockers"]
            )
        )
        rendered = str(validation)
        self.assertNotIn("C:\\private", rendered)
        self.assertNotIn("archive.pst", rendered)
        self.assertNotIn("body_text", rendered)
        self.assertNotIn("private mail body", rendered)

    def test_validate_report_rejects_bool_counts_and_duplicate_hashes(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_sampled_success_report())
        report["safe_outputs"]["message_count"] = True
        report["safe_outputs"]["attachment_occurrence_count"] = True
        report["safe_outputs"]["parse_warning_count"] = True
        report["safe_outputs"]["denied_hidden_bundle_count"] = True
        report["safe_outputs"]["store_query_response_hashes"] = [
            report["safe_outputs"]["store_query_response_hashes"][0],
            report["safe_outputs"]["store_query_response_hashes"][0],
        ]

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.message_count must be a positive integer", validation["blockers"]
        )
        self.assertIn(
            "safe_outputs.attachment_occurrence_count must be a non-negative integer",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.parse_warning_count must be a non-negative integer",
            validation["blockers"],
        )
        self.assertIn("safe_outputs.denied_hidden_bundle_count must be 1", validation["blockers"])
        self.assertIn(
            "safe_outputs.store_query_response_hashes must contain distinct hashes",
            validation["blockers"],
        )

    def test_validate_report_rejects_full_parser_overclaim(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_sampled_success_report())
        report["mode"] = "full"
        report["safe_outputs"]["full_parse_executed"] = True
        report["claim_boundary"]["supports_real_pst_sampled_parser_claim"] = False
        report["claim_boundary"]["supports_real_pst_full_parser_claim"] = True
        report["claim_boundary"]["supports_full_real_pst_parser_claim"] = True

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("full real PST claim boundary must be false", validation["blockers"])
        self.assertIn(
            "forbidden claim is not explicitly false: supports_full_real_pst_parser_claim",
            validation["blockers"],
        )
        self.assertFalse(validation["claim_boundary"]["supports_real_pst_full_parser_claim"])

    def test_validate_report_rejects_tampered_embedded_validation(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_sampled_success_report()
        report["validation"] = {
            "passed": True,
            "blockers": [],
            "claim_boundary": {
                "supports_real_pst_sampled_parser_claim": True,
                "supports_real_pst_full_parser_claim": True,
                "supports_production_ready_claim": True,
            },
        }

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn("validation production claim must be false", validation["blockers"])
        self.assertIn("validation full real PST claim must be false", validation["blockers"])

    def test_validate_report_cli_returns_bounded_failure_for_malformed_input(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-real-pst-smoke-malformed-validate-report")
        input_path = temp_dir / "bad-report.json"
        output_path = temp_dir / "validation.json"
        input_path.write_text("{ not json from C:\\private\\archive.pst", encoding="utf-8")

        exit_code = smoke.main(
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
        self.assertNotIn(str(input_path), rendered)
        self.assertNotIn("C:\\private", rendered)
        self.assertNotIn("archive.pst", rendered)
        self.assertNotIn("traceback", rendered.lower())


def _valid_sampled_success_report() -> dict:
    hashes = ["sha256:" + f"{index:x}" * 64 for index in range(1, 16)]
    return {
        "report_type": "mail_real_pst_smoke",
        "generated_at": "2026-07-06T12:00:00+00:00",
        "mode": "sampled",
        "metrics": {
            "fixture_present": True,
            "fixture_stream_hash_succeeded": True,
            "pst_signature_verified": True,
            "real_parser_invoked": True,
            "upload_session_created": True,
            "asset_registered": True,
            "ingestion_job_succeeded": True,
            "extractor_run_succeeded": True,
            "mail_observations_persisted": True,
            "mail_evidence_rows_persisted": True,
            "owner_query_succeeded_with_citations": True,
            "denied_query_redacted": True,
            "raw_archive_retention_decision_recorded": True,
            "kg_wiki_side_effects_absent": True,
            "staging_scratch_cleaned": True,
            "raw_leak_guard_passed": True,
            "real_pst_smoke_passed": True,
        },
        "safe_outputs": {
            "fixture_id_hash": hashes[0],
            "fixture_sha256": hashes[1],
            "fixture_size_bytes": 3_152_323_584,
            "sample_message_limit": 25,
            "full_parse_executed": False,
            "parser_adapter_contract_hash": hashes[2],
            "parser_version_hash": hashes[3],
            "asset_count": 1,
            "job_count": 1,
            "extractor_run_count": 1,
            "observation_count": 10,
            "message_count": 2,
            "folder_occurrence_count": 1,
            "body_segment_count": 2,
            "attachment_occurrence_count": 0,
            "parse_warning_count": 0,
            "parse_warning_codes_hash": hashes[4],
            "mail_evidence_table_count": 7,
            "mail_evidence_row_count": 9,
            "mail_evidence_statement_count": 9,
            "owner_query_status": "ok",
            "owner_visible_result_count": 1,
            "owner_citation_count": 1,
            "denied_query_status": "permission_denied",
            "denied_visible_result_count": 0,
            "denied_citation_count": 0,
            "denied_hidden_bundle_count": 1,
            "upload_session_shape_hash": hashes[5],
            "asset_shape_hash": hashes[6],
            "extractor_run_shape_hash": hashes[7],
            "owner_query_shape_hash": hashes[8],
            "denied_query_shape_hash": hashes[9],
            "store_query_response_hashes": [hashes[10], hashes[11]],
            "staging_leftover_count": 0,
            "scratch_leftover_count": 0,
        },
        "claim_boundary": {
            "supports_real_pst_sampled_parser_claim": True,
            "supports_real_pst_full_parser_claim": False,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_full_real_pst_parser_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_raw_mail_access_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }


if __name__ == "__main__":
    unittest.main()
