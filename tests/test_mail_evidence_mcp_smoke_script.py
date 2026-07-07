from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest

import _paths  # noqa: F401


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mail_evidence_mcp_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "mail_evidence_mcp_smoke",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load mail evidence MCP smoke script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MailEvidenceMcpSmokeScriptTests(unittest.TestCase):
    def test_chatgpt_free_mail_evidence_mcp_smoke_passes_without_overclaims(
        self,
    ) -> None:
        smoke = _load_smoke_module()
        work_dir = _paths.fresh_test_dir("mail-evidence-mcp-smoke") / "run"

        report = smoke.run_mail_evidence_mcp_smoke(work_dir)

        self.assertTrue(report["validation"]["passed"])
        self.assertTrue(report["metrics"]["mail_evidence_mcp_smoke_passed"])
        self.assertTrue(
            report["claim_boundary"]["supports_chatgpt_free_mail_evidence_mcp_smoke_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"])
        self.assertFalse(report["claim_boundary"]["supports_upload_ui_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_iframe_readiness_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_pst_parser_claim"])
        self.assertFalse(report["claim_boundary"]["supports_postgresql_mail_evidence_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_worker_leasing_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("Update: Launch reviewed", rendered)
        self.assertNotIn("Blocker: Waiting on audit approval", rendered)
        self.assertNotIn("Waiting on audit approval", rendered)

    def test_smoke_rejects_existing_unmarked_work_dir_without_deleting_it(self) -> None:
        smoke = _load_smoke_module()
        work_dir = _paths.fresh_test_dir("mail-evidence-mcp-smoke-unmarked")
        keep_file = work_dir / "keep.txt"
        keep_file.write_text("do not delete", encoding="utf-8")

        with self.assertRaises(ValueError):
            smoke.run_mail_evidence_mcp_smoke(work_dir)

        self.assertEqual(keep_file.read_text(encoding="utf-8"), "do not delete")

    def test_smoke_safe_outputs_are_deterministic_across_work_dirs(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-evidence-mcp-smoke-deterministic")

        first = smoke.run_mail_evidence_mcp_smoke(temp_dir / "first")
        second = smoke.run_mail_evidence_mcp_smoke(temp_dir / "second")

        self.assertEqual(first["safe_outputs"], second["safe_outputs"])

    def test_main_writes_cli_output_and_validate_report_returns_exit_code(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-evidence-mcp-smoke-cli")
        work_dir = temp_dir / "work"
        output_path = temp_dir / "report.json"
        validation_output_path = temp_dir / "validation.json"
        invalid_report_path = temp_dir / "invalid-report.json"
        output_path.write_text("stale output", encoding="utf-8")

        exit_code = smoke.main(
            [
                "--work-dir",
                str(work_dir),
                "--output",
                str(output_path),
            ]
        )

        self.assertEqual(exit_code, 0)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertTrue(report["validation"]["passed"])
        self.assertNotEqual(output_path.read_text(encoding="utf-8"), "stale output")
        rendered = output_path.read_text(encoding="utf-8")
        self.assertNotIn("Update: Launch reviewed", rendered)
        self.assertNotIn("Blocker: Waiting on audit approval", rendered)

        invalid_report = _valid_report()
        invalid_report["metrics"]["mail_evidence_mcp_smoke_passed"] = False
        invalid_report_path.write_text(
            json.dumps(invalid_report, sort_keys=True),
            encoding="utf-8",
        )
        invalid_exit = smoke.main(
            [
                "--validate-report",
                str(invalid_report_path),
                "--output",
                str(validation_output_path),
            ]
        )

        self.assertEqual(invalid_exit, 1)
        validation = json.loads(validation_output_path.read_text(encoding="utf-8"))
        self.assertFalse(validation["passed"])

    def test_main_uses_platform_temp_dir_when_work_dir_is_not_supplied(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-evidence-mcp-smoke-default-cli")
        output_path = temp_dir / "report.json"
        original_gettempdir = smoke.tempfile.gettempdir
        smoke.tempfile.gettempdir = lambda: str(temp_dir)
        try:
            exit_code = smoke.main(["--output", str(output_path)])
        finally:
            smoke.tempfile.gettempdir = original_gettempdir

        self.assertEqual(exit_code, 0)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertTrue(report["validation"]["passed"])
        smoke_dirs = list(temp_dir.glob("formowl-mail-evidence-smoke-*"))
        self.assertEqual(len(smoke_dirs), 1)
        self.assertTrue((smoke_dirs[0] / smoke.SMOKE_SENTINEL).exists())

    def test_smoke_report_rejects_raw_leak_or_forbidden_claim(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["safe_outputs"]["debug"] = "/srv/formowl/private/mail.pst"
        report["claim_boundary"]["supports_production_ready_claim"] = True

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "public report leaks raw paths, SQL, or internal values",
            validation["blockers"],
        )
        self.assertIn(
            "forbidden claim is not explicitly false: supports_production_ready_claim",
            validation["blockers"],
        )

    def test_validate_report_rejects_missing_required_metric(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["metrics"]["case_progress_forged_grant_rejected"] = False
        report["metrics"]["mail_evidence_mcp_smoke_passed"] = False

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required smoke metric is not true: case_progress_forged_grant_rejected",
            validation["blockers"],
        )

    def test_validate_report_requires_explicit_false_claims_and_safe_shape(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        del report["claim_boundary"]["supports_real_pst_parser_claim"]
        del report["safe_outputs"]["response_hashes"]
        report["claim_boundary"]["container_verification_required"] = False
        report["safe_outputs"]["owner_query_status"] = "permission_denied"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "forbidden claim is not explicitly false: supports_real_pst_parser_claim",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs missing keys: response_hashes",
            validation["blockers"],
        )
        self.assertIn(
            "container_verification_required must be true",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.owner_query_status must be ok",
            validation["blockers"],
        )

    def test_validate_report_requires_case_progress_statuses_and_citations(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["safe_outputs"]["bundle_case_progress_status"] = "permission_denied"
        report["safe_outputs"]["denied_case_progress_status"] = "ok"
        report["safe_outputs"]["owner_case_progress_citation_count"] = 0

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.bundle_case_progress_status must be ok",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.denied_case_progress_status must be permission_denied",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.owner_case_progress_citation_count must be positive",
            validation["blockers"],
        )

    def test_validate_report_rejects_bool_counts_and_duplicate_hashes(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["safe_outputs"]["observation_count"] = True
        report["safe_outputs"]["owner_case_progress_citation_count"] = True
        report["safe_outputs"]["response_hashes"] = [
            report["safe_outputs"]["response_hashes"][0],
            report["safe_outputs"]["response_hashes"][0],
        ]

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.observation_count must be positive",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.owner_case_progress_citation_count must be positive",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.response_hashes must be distinct",
            validation["blockers"],
        )

    def test_validate_report_rejects_body_text_anywhere_in_report(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["safe_outputs"]["body_hash_label"] = "Update: Launch reviewed"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "public report includes synthetic mail body text",
            validation["blockers"],
        )

    def test_validate_report_rejects_weak_hashes_and_text_fields(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["safe_outputs"]["asset_id_hash"] = "sha256:not-a-real-hash"
        report["safe_outputs"]["transcript"][0]["request_hash"] = "sha256:short"
        report["safe_outputs"]["mail_snippet"] = "summary without sentinel"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.asset_id_hash must be a sha256 hash",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.transcript hashes must be sha256 hashes",
            validation["blockers"],
        )
        self.assertTrue(
            any(
                blocker.startswith("safe_outputs contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.startswith("public report contains evidence text field: sha256:")
                for blocker in validation["blockers"]
            )
        )
        self.assertNotIn("mail_snippet", str(validation))

    def test_validate_report_rejects_unknown_report_fields_with_ordinary_text(
        self,
    ) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["/srv/private/debug"] = {"content": "ordinary mail line without sentinel"}
        report["safe_outputs"]["mail_summary"] = "ordinary mail line without sentinel"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
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
                blocker.startswith("public report contains evidence text field: sha256:")
                for blocker in validation["blockers"]
            )
        )
        rendered_validation = str(validation)
        self.assertNotIn("/srv/private/debug", rendered_validation)
        self.assertNotIn("mail_summary", rendered_validation)
        self.assertNotIn("ordinary mail line", rendered_validation)

    def test_validate_report_rejects_unknown_metrics_and_claim_keys(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["metrics"]["real_mail_ready /srv/private"] = True
        report["claim_boundary"]["supports_real_mail_claim"] = True

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertTrue(
            any(
                blocker.startswith("metrics contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.startswith("claim_boundary contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
        self.assertNotIn("real_mail_ready", str(validation))
        self.assertNotIn("supports_real_mail_claim", str(validation))
        self.assertNotIn("/srv/private", str(validation))

    def test_validate_report_rejects_tampered_embedded_validation(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["validation"] = {
            "passed": True,
            "blockers": [],
            "claim_boundary": {
                "supports_chatgpt_free_mail_evidence_mcp_smoke_claim": True,
                "supports_production_ready_claim": False,
            },
            "mail_summary": "ordinary mail line without sentinel",
        }

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertTrue(
            any(
                blocker.startswith("validation contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
        self.assertNotIn("mail_summary", str(validation))
        self.assertNotIn("ordinary mail line", str(validation))


def _valid_report() -> dict:
    hash_a = "sha256:" + "a" * 64
    hash_b = "sha256:" + "b" * 64
    hash_c = "sha256:" + "c" * 64
    hash_d = "sha256:" + "d" * 64
    hash_e = "sha256:" + "e" * 64
    hash_f = "sha256:" + "f" * 64
    return {
        "report_type": "mail_evidence_mcp_smoke",
        "generated_at": "2026-07-05T10:00:00+00:00",
        "metrics": {
            "asset_registered": True,
            "ingestion_job_succeeded": True,
            "extractor_run_succeeded": True,
            "mail_observations_persisted": True,
            "mail_evidence_bundle_built": True,
            "jsonrpc_tool_listed": True,
            "owner_query_returned_citation": True,
            "bundle_id_query_succeeded": True,
            "case_progress_answer_returned_citation": True,
            "case_progress_bundle_id_succeeded": True,
            "case_progress_denied_redacted": True,
            "case_progress_forged_grant_rejected": True,
            "case_progress_trusted_grant_allowed": True,
            "denied_query_redacted": True,
            "forged_grant_rejected": True,
            "trusted_grant_query_allowed": True,
            "wrong_owner_trusted_grant_denied": True,
            "hash_only_transcripts": True,
            "raw_leak_guard_passed": True,
            "mail_evidence_mcp_smoke_passed": True,
        },
        "safe_outputs": {
            "asset_id_hash": hash_a,
            "ingestion_job_id_hash": hash_b,
            "mail_evidence_bundle_id_hash": hash_c,
            "mail_import_session_id_hash": hash_d,
            "observation_count": 5,
            "owner_query_status": "ok",
            "denied_query_status": "permission_denied",
            "forged_query_status": "error",
            "trusted_query_status": "ok",
            "wrong_owner_query_status": "permission_denied",
            "owner_citation_count": 1,
            "owner_case_progress_status": "ok",
            "bundle_case_progress_status": "ok",
            "denied_case_progress_status": "permission_denied",
            "forged_case_progress_status": "error",
            "trusted_case_progress_status": "ok",
            "owner_case_progress_citation_count": 1,
            "response_hashes": [hash_e],
            "transcript": [
                {
                    "method": "tools/call",
                    "request_hash": hash_f,
                    "response_hash": hash_e,
                    "status": "ok",
                }
            ],
        },
        "claim_boundary": {
            "supports_chatgpt_free_mail_evidence_mcp_smoke_claim": True,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_upload_ui_claim": False,
            "supports_production_iframe_readiness_claim": False,
            "supports_real_pst_parser_claim": False,
            "supports_postgresql_mail_evidence_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }


if __name__ == "__main__":
    unittest.main()
