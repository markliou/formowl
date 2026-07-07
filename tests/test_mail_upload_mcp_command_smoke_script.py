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


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mail_upload_mcp_command_smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "mail_upload_mcp_command_smoke",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load mail upload MCP command smoke script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MailUploadMcpCommandSmokeScriptTests(unittest.TestCase):
    def test_chatgpt_mcp_command_preflight_opens_persisted_session_without_overclaims(
        self,
    ) -> None:
        smoke = _load_smoke_module()
        work_dir = _paths.fresh_test_dir("mail-upload-mcp-command-smoke") / "run"

        report = _with_command_shim(
            work_dir.parent,
            lambda: smoke.run_mail_upload_mcp_command_smoke(work_dir),
        )

        self.assertTrue(report["validation"]["passed"])
        self.assertTrue(report["metrics"]["mail_upload_mcp_command_smoke_passed"])
        self.assertTrue(report["metrics"]["task_card_resolves_to_persisted_session"])
        self.assertTrue(report["claim_boundary"]["supports_chatgpt_mcp_command_preflight_claim"])
        self.assertFalse(report["claim_boundary"]["supports_actual_chatgpt_smoke_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_upload_iframe_claim"])
        self.assertFalse(report["claim_boundary"]["supports_file_transfer_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_pst_parser_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        self.assertEqual(
            report["safe_outputs"]["command_profile"],
            "formowl_semantic_mcp_jsonrpc_console",
        )
        self.assertEqual(report["safe_outputs"]["persisted_upload_session_count"], 1)
        self.assertEqual(report["safe_outputs"]["infra_probe_audit_log_count"], 0)
        self.assertEqual(report["safe_outputs"]["non_object_error_code"], -32600)
        self.assertEqual(report["safe_outputs"]["startup_failure_error_code"], -32000)
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn(str(work_dir).lower(), rendered)
        self.assertNotIn("formowl_data_dir", rendered)
        self.assertNotIn("upload_surface_locator", rendered)
        self.assertNotIn("fast_mail_workers", rendered)
        self.assertNotIn("traceback", rendered)

    def test_command_smoke_safe_outputs_are_stable_across_work_dirs(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-upload-mcp-command-smoke-stable")

        first = _with_command_shim(
            temp_dir,
            lambda: smoke.run_mail_upload_mcp_command_smoke(temp_dir / "first"),
        )
        second = _with_command_shim(
            temp_dir,
            lambda: smoke.run_mail_upload_mcp_command_smoke(temp_dir / "second"),
        )

        self.assertEqual(first["safe_outputs"], second["safe_outputs"])

    def test_main_writes_cli_output_and_validate_report_returns_exit_code(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-upload-mcp-command-smoke-cli")
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

        invalid_report = _valid_report()
        invalid_report["metrics"]["infra_control_probe_denied"] = False
        invalid_report["metrics"]["mail_upload_mcp_command_smoke_passed"] = False
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
        self.assertIn("report must be an object", validation["blockers"])

    def test_main_uses_platform_temp_dir_when_work_dir_is_not_supplied(self) -> None:
        smoke = _load_smoke_module()
        temp_dir = _paths.fresh_test_dir("mail-upload-mcp-command-smoke-default-cli")
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
        smoke_dirs = list(temp_dir.glob("formowl-mail-upload-command-*"))
        self.assertEqual(len(smoke_dirs), 1)

    def test_validate_report_rejects_overclaims_and_raw_leaks(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["claim_boundary"]["supports_actual_chatgpt_smoke_claim"] = True
        report["claim_boundary"]["supports_production_ready_claim"] = True
        report["safe_outputs"]["debug"] = "C:\\private\\mail.pst"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "forbidden claim is not explicitly false: supports_actual_chatgpt_smoke_claim",
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

    def test_validate_report_rejects_missing_probe_and_weak_hashes(self) -> None:
        smoke = _load_smoke_module()
        report = copy.deepcopy(_valid_report())
        report["metrics"]["startup_failure_redacted"] = False
        report["metrics"]["mail_upload_mcp_command_smoke_passed"] = False
        report["safe_outputs"]["startup_failure_error_code"] = 0
        report["safe_outputs"]["tool_count"] = True
        report["safe_outputs"]["infra_probe_audit_log_count"] = False
        report["safe_outputs"]["upload_session_shape_hash"] = "sha256:short"
        report["safe_outputs"]["valid_response_hashes"] = [
            "sha256:" + "1" * 64,
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
        ]
        report["safe_outputs"]["failure_response_hashes"] = [
            report["safe_outputs"]["failure_response_hashes"][0]
        ]

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required command smoke metric is not true: startup_failure_redacted",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.startup_failure_error_code must be -32000",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.infra_probe_audit_log_count must be 0",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.tool_count must be a positive integer",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.upload_session_shape_hash must be a sha256 hash",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.valid_response_hashes must contain distinct hashes",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.failure_response_hashes must contain 3 hashes",
            validation["blockers"],
        )

    def test_validate_report_rejects_secret_like_allowed_values(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["generated_at"] = "password=swordfish"

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "generated_at must match the fixed smoke generation timestamp",
            validation["blockers"],
        )
        self.assertIn(
            "public report leaks raw paths, credentials, SQL, or backend internals",
            validation["blockers"],
        )
        self.assertNotIn("swordfish", str(validation))

    def test_validate_report_safely_rejects_non_object_reports(self) -> None:
        smoke = _load_smoke_module()

        validation = smoke.validate_report([])

        self.assertFalse(validation["passed"])
        self.assertEqual(validation["blockers"], ["report must be an object"])

    def test_validate_report_rejects_unknown_public_keys_without_echoing_them(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["raw_debug_path"] = "ordinary"
        report["safe_outputs"]["upload_response_body"] = "ordinary"
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
        self.assertNotIn("upload_response_body", rendered)
        self.assertNotIn("supports_full_issue_21_claim", rendered)

    def test_validate_report_rejects_tampered_embedded_validation(self) -> None:
        smoke = _load_smoke_module()
        report = _valid_report()
        report["validation"] = {
            "passed": True,
            "blockers": [],
            "claim_boundary": {
                "supports_chatgpt_mcp_command_preflight_claim": True,
                "supports_actual_chatgpt_smoke_claim": True,
                "supports_production_ready_claim": False,
            },
        }

        validation = smoke.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "validation actual ChatGPT smoke claim must be false",
            validation["blockers"],
        )


def _valid_report() -> dict:
    hash_a = "sha256:" + "a" * 64
    hash_b = "sha256:" + "b" * 64
    hash_c = "sha256:" + "c" * 64
    hash_d = "sha256:" + "d" * 64
    hash_e = "sha256:" + "e" * 64
    hash_f = "sha256:" + "f" * 64
    hash_1 = "sha256:" + "1" * 64
    hash_2 = "sha256:" + "2" * 64
    return {
        "report_type": "mail_upload_mcp_command_smoke",
        "generated_at": "2026-07-05T10:00:00+00:00",
        "metrics": {
            "command_started": True,
            "initialize_succeeded": True,
            "tools_list_succeeded": True,
            "open_upload_session_tool_listed": True,
            "upload_session_call_succeeded": True,
            "upload_task_card_validated": True,
            "upload_session_persisted": True,
            "persisted_session_bound_to_env": True,
            "task_card_resolves_to_persisted_session": True,
            "infra_control_probe_denied": True,
            "infra_control_probe_no_side_effects": True,
            "non_object_json_rejected": True,
            "startup_failure_redacted": True,
            "safe_response_hashes_only": True,
            "raw_leak_guard_passed": True,
            "mail_upload_mcp_command_smoke_passed": True,
        },
        "safe_outputs": {
            "command_profile": "formowl_semantic_mcp_jsonrpc_console",
            "response_count": 6,
            "tool_count": 9,
            "persisted_upload_session_count": 1,
            "infra_probe_audit_log_count": 0,
            "upload_session_shape_hash": hash_a,
            "task_card_shape_hash": hash_b,
            "valid_response_hashes": [hash_c, hash_e, hash_f],
            "failure_response_hashes": [hash_d, hash_1, hash_2],
            "infra_probe_is_error": True,
            "non_object_error_code": -32600,
            "startup_failure_error_code": -32000,
        },
        "claim_boundary": {
            "supports_chatgpt_mcp_command_preflight_claim": True,
            "supports_actual_chatgpt_smoke_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_file_transfer_claim": False,
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
