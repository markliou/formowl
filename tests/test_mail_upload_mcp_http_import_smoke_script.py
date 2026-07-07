from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import unittest

import _paths  # noqa: F401


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "mail_upload_mcp_http_import_smoke.py"
)


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "mail_upload_mcp_http_import_smoke",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load mail upload MCP HTTP import smoke script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailUploadMcpHttpImportSmokeScriptTests(unittest.TestCase):
    def test_mcp_http_upload_import_smoke_queries_store_without_overclaims(self) -> None:
        smoke = _load_smoke_module()
        work_dir = _paths.fresh_test_dir("mail-upload-mcp-http-import-smoke") / "run"

        report = _with_command_shim(
            work_dir.parent,
            lambda: smoke.run_mail_upload_mcp_http_import_smoke(work_dir),
        )

        self.assertTrue(report["validation"]["passed"])
        self.assertTrue(report["metrics"]["mail_upload_mcp_http_import_smoke_passed"])
        self.assertTrue(report["metrics"]["server_side_import_succeeded"])
        self.assertTrue(report["metrics"]["upload_session_marked_mail_evidence_ready"])
        self.assertTrue(report["metrics"]["store_backed_owner_jsonrpc_query_succeeded"])
        self.assertTrue(report["metrics"]["store_backed_denied_jsonrpc_query_redacted"])
        self.assertTrue(report["metrics"]["negative_import_probes_rejected_without_success"])
        self.assertTrue(
            report["claim_boundary"]["supports_mcp_command_to_http_import_query_contract_claim"]
        )
        self.assertTrue(
            report["claim_boundary"][
                "supports_synthetic_upload_to_postgresql_evidence_contract_claim"
            ]
        )
        self.assertFalse(report["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_upload_iframe_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_pst_parser_claim"])
        self.assertFalse(report["claim_boundary"]["supports_live_postgresql_readiness_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        self.assertEqual(report["safe_outputs"]["persisted_upload_session_count"], 1)
        self.assertEqual(report["safe_outputs"]["asset_count_after_import"], 1)
        self.assertEqual(report["safe_outputs"]["job_count_after_import"], 1)
        self.assertEqual(report["safe_outputs"]["extractor_run_count_after_import"], 1)
        self.assertEqual(report["safe_outputs"]["audit_event_count_after_import"], 3)
        self.assertEqual(report["safe_outputs"]["staging_leftover_count"], 0)
        self.assertEqual(report["safe_outputs"]["owner_query_status"], "ok")
        self.assertGreater(report["safe_outputs"]["owner_visible_result_count"], 0)
        self.assertEqual(
            report["safe_outputs"]["denied_query_status"],
            "permission_denied",
        )
        self.assertEqual(report["safe_outputs"]["denied_visible_result_count"], 0)
        self.assertEqual(report["safe_outputs"]["negative_probe_count"], 5)

        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn(str(work_dir).lower(), rendered)
        self.assertNotIn("mail-export.pst", rendered)
        self.assertNotIn("upload_surface_locator", rendered)
        self.assertNotIn("formowl://object", rendered)
        self.assertNotIn("payload.bin", rendered)
        self.assertNotIn("storage_backend_id", rendered)
        self.assertNotIn("update: launch reviewed", rendered)
        self.assertNotIn("waiting on audit approval", rendered)
        self.assertNotIn("traceback", rendered)

    def test_main_writes_cli_output_and_validate_report_returns_exit_code(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-upload-mcp-http-import-cli")
        output_path = temp_dir / "report.json"
        validation_output_path = temp_dir / "validation.json"
        invalid_report_path = temp_dir / "invalid-report.json"
        output_path.write_text("stale output", encoding="utf-8")

        exit_code = _with_command_shim(
            temp_dir,
            lambda: smoke.main(
                [
                    "--work-dir",
                    str(temp_dir / "work"),
                    "--output",
                    str(output_path),
                ]
            ),
        )

        self.assertEqual(exit_code, 0)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertTrue(report["validation"]["passed"])
        self.assertNotEqual(output_path.read_text(encoding="utf-8"), "stale output")
        self.assertNotIn("upload_surface_locator", output_path.read_text(encoding="utf-8"))

        invalid_report_path.write_text(json.dumps([], sort_keys=True), encoding="utf-8")
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
        self.assertEqual(validation["blockers"], ["report must be an object"])

    def test_main_uses_platform_temp_dir_when_work_dir_is_not_supplied(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-upload-mcp-http-import-default-cli")
        output_path = temp_dir / "report.json"
        original_gettempdir = smoke.tempfile.gettempdir
        smoke.tempfile.gettempdir = lambda: str(temp_dir)
        try:
            exit_code = _with_command_shim(
                temp_dir,
                lambda: smoke.main(["--output", str(output_path)]),
            )
        finally:
            smoke.tempfile.gettempdir = original_gettempdir

        self.assertEqual(exit_code, 0)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertTrue(report["validation"]["passed"])
        smoke_dirs = list(temp_dir.glob("formowl-mail-upload-mcp-http-import-*"))
        self.assertEqual(len(smoke_dirs), 1)

    def test_validate_report_rejects_overclaims_raw_leaks_and_body_fields(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"] = True
        report["claim_boundary"]["supports_production_ready_claim"] = True
        report["safe_outputs"]["debug_path"] = "C:\\private\\mail.pst"
        report["safe_outputs"]["body_text"] = "Update: Launch reviewed"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "forbidden claim is not explicitly false: "
            "supports_actual_chatgpt_connected_upload_claim",
            validation["blockers"],
        )
        self.assertIn(
            "forbidden claim is not explicitly false: supports_production_ready_claim",
            validation["blockers"],
        )
        self.assertIn(
            "public report leaks raw paths, credentials, SQL, or backend internals",
            validation["blockers"],
        )
        self.assertTrue(
            any(
                blocker.startswith("public report contains evidence text field:")
                for blocker in validation["blockers"]
            )
        )
        rendered_validation = str(validation)
        self.assertNotIn("C:\\private", rendered_validation)
        self.assertNotIn("Launch reviewed", rendered_validation)

    def test_validate_report_rejects_negative_probe_failure_and_bool_counts(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["metrics"]["negative_import_probes_rejected_without_success"] = False
        report["metrics"]["mail_upload_mcp_http_import_smoke_passed"] = False
        report["safe_outputs"]["asset_count_after_import"] = True
        report["safe_outputs"]["denied_visible_result_count"] = False
        report["safe_outputs"]["negative_probe_shape_hashes"] = [
            report["safe_outputs"]["negative_probe_shape_hashes"][0]
        ]
        report["safe_outputs"]["asset_shape_hash"] = "sha256:short"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required MCP HTTP import metric is not true: "
            "negative_import_probes_rejected_without_success",
            validation["blockers"],
        )
        self.assertIn("safe_outputs.asset_count_after_import must be 1", validation["blockers"])
        self.assertIn(
            "safe_outputs.denied_visible_result_count must be 0",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.negative_probe_shape_hashes must contain 5 hashes",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.asset_shape_hash must be a sha256 hash",
            validation["blockers"],
        )

    def test_validate_report_rejects_unknown_public_keys_without_echoing_them(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["raw_debug_path"] = "ordinary"
        report["safe_outputs"]["mail_body_snippet"] = "ordinary"
        report["claim_boundary"]["supports_full_issue_21_claim"] = True

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
                blocker.startswith("claim_boundary contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
        rendered = str(validation)
        self.assertNotIn("raw_debug_path", rendered)
        self.assertNotIn("mail_body_snippet", rendered)
        self.assertNotIn("supports_full_issue_21_claim", rendered)

    def test_validate_report_rejects_tampered_embedded_validation(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["validation"] = {
            "passed": True,
            "blockers": [],
            "claim_boundary": {
                "supports_mcp_command_to_http_import_query_contract_claim": True,
                "supports_actual_chatgpt_connected_upload_claim": True,
                "supports_production_ready_claim": False,
            },
        }

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "validation actual ChatGPT claim must be false",
            validation["blockers"],
        )


def _valid_report() -> dict:
    hashes = ["sha256:" + f"{index:x}" * 64 for index in range(1, 16)]
    return {
        "report_type": "mail_upload_mcp_http_import_smoke",
        "generated_at": "2026-07-05T14:00:00+00:00",
        "metrics": {
            "command_started": True,
            "initialize_succeeded": True,
            "tools_list_succeeded": True,
            "open_upload_session_tool_listed": True,
            "upload_session_call_succeeded": True,
            "upload_session_persisted": True,
            "persisted_session_bound_to_env": True,
            "http_post_upload_succeeded": True,
            "http_post_result_validated": True,
            "upload_session_asset_bound_before_import": True,
            "server_side_import_succeeded": True,
            "upload_session_marked_mail_evidence_ready": True,
            "ingestion_job_and_run_persisted": True,
            "mail_observations_persisted": True,
            "mail_evidence_rows_persisted": True,
            "store_backed_owner_jsonrpc_query_succeeded": True,
            "store_backed_denied_jsonrpc_query_redacted": True,
            "raw_archive_retention_decision_recorded": True,
            "negative_import_probes_rejected_without_success": True,
            "safe_response_hashes_only": True,
            "raw_leak_guard_passed": True,
            "mail_upload_mcp_http_import_smoke_passed": True,
        },
        "safe_outputs": {
            "command_profile": "formowl_semantic_mcp_jsonrpc_to_local_http_import_query",
            "jsonrpc_command_response_count": 3,
            "tool_count": 9,
            "persisted_upload_session_count": 1,
            "asset_count_after_import": 1,
            "job_count_after_import": 1,
            "extractor_run_count_after_import": 1,
            "observation_count_after_import": 9,
            "audit_event_count_after_import": 3,
            "stored_payload_count_after_import": 1,
            "staging_leftover_count": 0,
            "post_status_code": 201,
            "mail_evidence_table_count": 7,
            "mail_evidence_row_count": 9,
            "mail_evidence_statement_count": 9,
            "owner_query_status": "ok",
            "owner_visible_result_count": 1,
            "denied_query_status": "permission_denied",
            "denied_visible_result_count": 0,
            "negative_probe_count": 5,
            "negative_probe_names_hash": hashes[0],
            "upload_session_shape_hash": hashes[1],
            "asset_shape_hash": hashes[2],
            "http_post_result_shape_hash": hashes[3],
            "import_summary_shape_hash": hashes[4],
            "owner_query_shape_hash": hashes[5],
            "denied_query_shape_hash": hashes[6],
            "jsonrpc_command_response_hashes": hashes[7:10],
            "store_query_response_hashes": hashes[10:12],
            "negative_probe_shape_hashes": hashes[12:15] + [hashes[0], hashes[1]],
        },
        "claim_boundary": {
            "supports_mcp_command_to_http_import_query_contract_claim": True,
            "supports_synthetic_upload_to_postgresql_evidence_contract_claim": True,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_real_pst_parser_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }


def _with_command_shim(temp_dir: Path, callback):
    bin_dir = _install_command_shim(temp_dir)
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(bin_dir) + os.pathsep + old_path
    try:
        return callback()
    finally:
        os.environ["PATH"] = old_path


def _install_command_shim(temp_dir: Path) -> Path:
    bin_dir = temp_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    posix_shim = bin_dir / "formowl-semantic-mcp-jsonrpc"
    posix_shim.write_text(
        "#!/bin/sh\n" f'exec "{sys.executable}" -m formowl_gateway.cli "$@"\n',
        encoding="utf-8",
    )
    posix_shim.chmod(posix_shim.stat().st_mode | stat.S_IXUSR)
    cmd_shim = bin_dir / "formowl-semantic-mcp-jsonrpc.cmd"
    cmd_shim.write_text(
        "@echo off\r\n" f'"{sys.executable}" -m formowl_gateway.cli %*\r\n',
        encoding="utf-8",
    )
    return bin_dir


if __name__ == "__main__":
    unittest.main()
