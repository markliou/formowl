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
from formowl_contract import sha256_json


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "mail_upload_chatgpt_connection_preflight.py"
)
REQUIRED_ENV_NAMES = [
    "FORMOWL_DATA_DIR",
    "FORMOWL_MCP_SESSION_ID",
    "FORMOWL_MCP_ACTOR_USER_ID",
    "FORMOWL_MCP_WORKSPACE_ID",
    "FORMOWL_MAIL_UPLOAD_EXPIRES_AT",
]
REQUIRED_TOOL_NAMES = ["open_upload_session"]
EXPECTED_SEQUENCE = ["initialize", "tools/list", "tools/call:open_upload_session"]
NEGATIVE_PACKAGE_PROBE_NAMES = [
    "absolute_command_path",
    "environment_values_present",
    "actual_chatgpt_overclaim",
    "upload_locator_present",
]


def _load_preflight_module():
    spec = importlib.util.spec_from_file_location(
        "mail_upload_chatgpt_connection_preflight",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ChatGPT connection preflight script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailUploadChatGptConnectionPreflightTests(unittest.TestCase):
    def test_preflight_builds_hash_only_connection_report_without_overclaims(
        self,
    ) -> None:
        preflight = _load_preflight_module()
        work_dir = _paths.fresh_test_dir("mail-upload-chatgpt-preflight") / "run"

        report = _with_command_shim(
            work_dir.parent,
            lambda: preflight.run_mail_upload_chatgpt_connection_preflight(work_dir),
        )

        self.assertTrue(report["validation"]["passed"])
        self.assertTrue(report["metrics"]["mail_upload_chatgpt_connection_preflight_passed"])
        self.assertTrue(report["metrics"]["command_smoke_validated"])
        self.assertTrue(report["metrics"]["connection_package_validated"])
        self.assertTrue(report["metrics"]["negative_package_probes_rejected"])
        self.assertTrue(
            report["claim_boundary"]["supports_chatgpt_mcp_connection_preflight_package_claim"]
        )
        self.assertTrue(
            report["claim_boundary"]["supports_chatgpt_manual_configuration_ready_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_upload_iframe_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_pst_parser_claim"])
        self.assertFalse(report["claim_boundary"]["supports_live_postgresql_readiness_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        self.assertEqual(report["safe_outputs"]["required_environment_name_count"], 5)
        self.assertEqual(report["safe_outputs"]["required_tool_count"], 1)
        self.assertEqual(report["safe_outputs"]["expected_sequence_step_count"], 3)
        self.assertEqual(report["safe_outputs"]["persisted_upload_session_count"], 1)
        self.assertEqual(report["safe_outputs"]["negative_package_probe_count"], 4)

        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn(str(work_dir).lower(), rendered)
        self.assertNotIn("formowl_data_dir", rendered)
        self.assertNotIn("formowl_mcp_session_id", rendered)
        self.assertNotIn("upload_surface_locator", rendered)
        self.assertNotIn("formowl_upload_session:upload_", rendered)
        self.assertNotIn("mail-export.pst", rendered)
        self.assertNotIn("payload.bin", rendered)
        self.assertNotIn("storage_backend_id", rendered)
        self.assertNotIn("traceback", rendered)

    def test_main_writes_cli_output_and_validate_report_returns_exit_code(self) -> None:
        preflight = _load_preflight_module()
        temp_dir = _paths.fresh_test_dir("mail-upload-chatgpt-preflight-cli")
        output_path = temp_dir / "report.json"
        validation_output_path = temp_dir / "validation.json"
        invalid_report_path = temp_dir / "invalid-report.json"
        output_path.write_text("stale output", encoding="utf-8")

        exit_code = _with_command_shim(
            temp_dir,
            lambda: preflight.main(
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
        self.assertNotIn("FORMOWL_DATA_DIR", output_path.read_text(encoding="utf-8"))

        invalid_report_path.write_text(json.dumps([], sort_keys=True), encoding="utf-8")
        invalid_exit = preflight.main(
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
        preflight = _load_preflight_module()
        temp_dir = _paths.fresh_test_dir("mail-upload-chatgpt-preflight-default-cli")
        output_path = temp_dir / "report.json"
        original_gettempdir = preflight.tempfile.gettempdir
        preflight.tempfile.gettempdir = lambda: str(temp_dir)
        try:
            exit_code = _with_command_shim(
                temp_dir,
                lambda: preflight.main(["--output", str(output_path)]),
            )
        finally:
            preflight.tempfile.gettempdir = original_gettempdir

        self.assertEqual(exit_code, 0)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertTrue(report["validation"]["passed"])
        smoke_dirs = list(temp_dir.glob("formowl-mail-upload-chatgpt-connection-*"))
        self.assertEqual(len(smoke_dirs), 1)

    def test_validate_report_rejects_overclaims_raw_leaks_and_config_values(
        self,
    ) -> None:
        preflight = _load_preflight_module()
        report = _valid_report()
        report["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"] = True
        report["safe_outputs"]["debug_path"] = "C:\\private\\mail.pst"
        report["safe_outputs"]["environment_value"] = "private"
        report["safe_outputs"]["body_text"] = "Update: Launch reviewed"

        validation = preflight.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "forbidden claim is not explicitly false: "
            "supports_actual_chatgpt_connected_upload_claim",
            validation["blockers"],
        )
        self.assertIn(
            "public report leaks raw paths, credentials, SQL, or backend internals",
            validation["blockers"],
        )
        self.assertTrue(
            any(
                blocker.startswith("public report contains environment value field:")
                for blocker in validation["blockers"]
            )
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

    def test_validate_report_rejects_bool_counts_hash_errors_and_unknown_keys(
        self,
    ) -> None:
        preflight = _load_preflight_module()
        report = copy.deepcopy(_valid_report())
        report["metrics"]["negative_package_probes_rejected"] = False
        report["metrics"]["mail_upload_chatgpt_connection_preflight_passed"] = False
        report["safe_outputs"]["required_environment_name_count"] = True
        report["safe_outputs"]["task_card_shape_hash"] = "sha256:short"
        report["safe_outputs"]["negative_package_probe_shape_hashes"] = [
            report["safe_outputs"]["negative_package_probe_shape_hashes"][0]
        ]
        report["connection_package"] = {"FORMOWL_DATA_DIR": "private"}

        validation = preflight.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required ChatGPT preflight metric is not true: " "negative_package_probes_rejected",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.required_environment_name_count must be 5",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.task_card_shape_hash must be a sha256 hash",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.negative_package_probe_shape_hashes must contain 4 hashes",
            validation["blockers"],
        )
        self.assertTrue(
            any(
                blocker.startswith("report contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
        self.assertNotIn("FORMOWL_DATA_DIR", str(validation))

    def test_validate_report_rejects_static_contract_hash_tampering(self) -> None:
        preflight = _load_preflight_module()
        report = copy.deepcopy(_valid_report())
        tampered_hash = "sha256:" + "f" * 64
        report["safe_outputs"]["required_environment_names_hash"] = tampered_hash
        report["safe_outputs"]["required_tool_names_hash"] = tampered_hash
        report["safe_outputs"]["expected_sequence_hash"] = tampered_hash
        report["safe_outputs"]["negative_package_probe_names_hash"] = tampered_hash

        validation = preflight.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.required_environment_names_hash does not match " "contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.required_tool_names_hash does not match contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.expected_sequence_hash does not match contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.negative_package_probe_names_hash does not match " "contract hash",
            validation["blockers"],
        )

    def test_validate_report_rejects_duplicate_hashes_and_embedded_overclaim(
        self,
    ) -> None:
        preflight = _load_preflight_module()
        report = copy.deepcopy(_valid_report())
        probe_hashes = report["safe_outputs"]["negative_package_probe_shape_hashes"]
        report["safe_outputs"]["negative_package_probe_shape_hashes"] = [
            probe_hashes[0],
            probe_hashes[1],
            probe_hashes[2],
            probe_hashes[0],
        ]
        report["validation"] = {
            "passed": True,
            "blockers": [],
            "claim_boundary": {
                "supports_chatgpt_mcp_connection_preflight_package_claim": True,
                "supports_actual_chatgpt_connected_upload_claim": True,
                "supports_production_ready_claim": False,
            },
        }

        validation = preflight.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "safe_outputs.negative_package_probe_shape_hashes must contain " "distinct hashes",
            validation["blockers"],
        )
        self.assertIn(
            "validation actual ChatGPT claim must be false",
            validation["blockers"],
        )

    def test_connection_package_validator_rejects_values_locators_paths_and_overclaims(
        self,
    ) -> None:
        preflight = _load_preflight_module()
        package = preflight.build_connection_package(_valid_command_report())
        self.assertTrue(preflight.validate_connection_package(package)["passed"])

        package["environment_variable_values"] = {"FORMOWL_DATA_DIR": "private"}
        package["upload_surface_locator"] = "formowl_upload_session:upload_private"
        package["command_argv"] = ["C:\\private\\formowl-semantic-mcp-jsonrpc"]
        package["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"] = True

        validation = preflight.validate_connection_package(package)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "connection_package.command_argv must use packaged command",
            validation["blockers"],
        )
        self.assertIn(
            "connection package must not include environment values",
            validation["blockers"],
        )
        self.assertIn(
            "connection package must not include upload surface locators",
            validation["blockers"],
        )
        self.assertIn(
            "connection_package forbidden claim is not explicitly false: "
            "supports_actual_chatgpt_connected_upload_claim",
            validation["blockers"],
        )
        self.assertIn(
            "connection package leaks raw paths, credentials, SQL, or " "backend internals",
            validation["blockers"],
        )
        rendered = str(validation)
        self.assertNotIn("FORMOWL_DATA_DIR", rendered)
        self.assertNotIn("upload_private", rendered)
        self.assertNotIn("C:\\private", rendered)


def _valid_report() -> dict:
    hashes = ["sha256:" + f"{index:x}" * 64 for index in range(1, 16)]
    return {
        "report_type": "mail_upload_chatgpt_connection_preflight",
        "generated_at": "2026-07-05T15:00:00+00:00",
        "metrics": {
            "command_smoke_validated": True,
            "command_preflight_claim_supported": True,
            "initialize_and_tools_preflight_succeeded": True,
            "open_upload_session_tool_available": True,
            "upload_task_card_shape_bound_to_session": True,
            "connection_package_built": True,
            "connection_package_validated": True,
            "connection_package_omits_environment_values": True,
            "connection_package_omits_session_locator": True,
            "manual_chatgpt_attach_steps_are_hash_only": True,
            "negative_package_probes_rejected": True,
            "safe_response_hashes_only": True,
            "raw_leak_guard_passed": True,
            "mail_upload_chatgpt_connection_preflight_passed": True,
        },
        "safe_outputs": {
            "connection_profile": ("formowl_semantic_mcp_jsonrpc_chatgpt_attach_preflight"),
            "command_smoke_report_hash": hashes[0],
            "connection_package_shape_hash": hashes[1],
            "mcp_server_definition_shape_hash": hashes[2],
            "required_environment_name_count": 5,
            "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
            "required_tool_count": 1,
            "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
            "expected_sequence_step_count": 3,
            "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
            "command_arg_count": 1,
            "command_smoke_response_count": 6,
            "command_smoke_tool_count": 9,
            "persisted_upload_session_count": 1,
            "upload_session_shape_hash": hashes[6],
            "task_card_shape_hash": hashes[7],
            "negative_package_probe_count": 4,
            "negative_package_probe_names_hash": sha256_json(NEGATIVE_PACKAGE_PROBE_NAMES),
            "negative_package_probe_shape_hashes": hashes[9:13],
        },
        "claim_boundary": {
            "supports_chatgpt_mcp_connection_preflight_package_claim": True,
            "supports_chatgpt_manual_configuration_ready_claim": True,
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


def _valid_command_report() -> dict:
    hashes = ["sha256:" + f"{index:x}" * 64 for index in range(1, 8)]
    return {
        "report_type": "mail_upload_mcp_command_smoke",
        "safe_outputs": {
            "task_card_shape_hash": hashes[0],
            "upload_session_shape_hash": hashes[1],
            "persisted_upload_session_count": 1,
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
