from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

import _paths  # noqa: F401
from formowl_contract import sha256_json


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "mail_upload_chatgpt_result_intake.py"
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
NEGATIVE_PACKET_PROBE_NAMES = [
    "environment_values_present",
    "upload_locator_present",
    "mail_body_text_present",
    "actual_upload_overclaim",
    "tampered_preflight_contract_hash",
    "raw_command_path_present",
]


def _load_intake_module():
    spec = importlib.util.spec_from_file_location(
        "mail_upload_chatgpt_result_intake",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ChatGPT result intake script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailUploadChatGptResultIntakeTests(unittest.TestCase):
    def test_intake_accepts_bounded_operator_packet_without_overclaims(self) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()

        report = intake.build_chatgpt_result_intake_report(packet)

        self.assertTrue(report["validation"]["passed"])
        self.assertTrue(report["metrics"]["mail_upload_chatgpt_result_intake_passed"])
        self.assertTrue(report["metrics"]["preflight_contract_hashes_bound"])
        self.assertTrue(report["metrics"]["chatgpt_mcp_sequence_observed"])
        self.assertTrue(report["metrics"]["open_upload_session_tool_available"])
        self.assertTrue(report["metrics"]["open_upload_session_called"])
        self.assertTrue(report["metrics"]["upload_task_card_shape_verified"])
        self.assertTrue(report["metrics"]["negative_packet_probes_rejected"])
        self.assertTrue(report["claim_boundary"]["supports_chatgpt_result_intake_validation_claim"])
        self.assertTrue(
            report["claim_boundary"][
                "supports_operator_supplied_chatgpt_open_upload_session_packet_claim"
            ]
        )
        self.assertFalse(report["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"])
        self.assertFalse(
            report["claim_boundary"]["supports_direct_chatgpt_session_verification_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_real_upload_iframe_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_pst_parser_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        self.assertEqual(report["safe_outputs"]["required_environment_name_count"], 5)
        self.assertEqual(report["safe_outputs"]["required_tool_count"], 1)
        self.assertEqual(report["safe_outputs"]["expected_sequence_step_count"], 3)
        self.assertEqual(report["safe_outputs"]["observed_sequence_step_count"], 3)
        self.assertEqual(report["safe_outputs"]["negative_packet_probe_count"], 6)

        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("formowl_data_dir", rendered)
        self.assertNotIn("formowl_mcp_session_id", rendered)
        self.assertNotIn("upload_surface_locator", rendered)
        self.assertNotIn("formowl_upload_session:upload_", rendered)
        self.assertNotIn("mail-export.pst", rendered)
        self.assertNotIn("payload.bin", rendered)
        self.assertNotIn("storage_backend_id", rendered)
        self.assertNotIn("private launch message", rendered)
        self.assertNotIn(str(SCRIPT_PATH.parent.parent).lower(), rendered)

    def test_main_reads_packet_writes_report_and_validates_report(self) -> None:
        intake = _load_intake_module()
        temp_dir = _paths.fresh_test_dir("mail-upload-chatgpt-result-intake-cli")
        input_path = temp_dir / "packet.json"
        output_path = temp_dir / "report.json"
        validation_path = temp_dir / "validation.json"
        invalid_path = temp_dir / "invalid.json"
        malformed_packet_path = temp_dir / "malformed-packet.json"
        malformed_output_path = temp_dir / "malformed-report.json"
        bad_json_path = temp_dir / "bad-json.json"
        bad_json_output_path = temp_dir / "bad-json-report.json"
        conflict_output_path = temp_dir / "conflict-report.json"
        input_path.write_text(
            json.dumps(_valid_result_packet(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        output_path.write_text("stale", encoding="utf-8")

        exit_code = intake.main(["--input", str(input_path), "--output", str(output_path)])

        self.assertEqual(exit_code, 0)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertTrue(report["validation"]["passed"])
        self.assertNotEqual(output_path.read_text(encoding="utf-8"), "stale")
        self.assertNotIn("FORMOWL_DATA_DIR", output_path.read_text(encoding="utf-8"))

        invalid_path.write_text(json.dumps([], sort_keys=True), encoding="utf-8")
        invalid_exit = intake.main(
            [
                "--validate-report",
                str(invalid_path),
                "--output",
                str(validation_path),
            ]
        )

        self.assertEqual(invalid_exit, 1)
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertFalse(validation["passed"])
        self.assertEqual(validation["blockers"], ["report must be an object"])

        malformed_packet_path.write_text(
            json.dumps([], sort_keys=True),
            encoding="utf-8",
        )
        malformed_exit = intake.main(
            [
                "--input",
                str(malformed_packet_path),
                "--output",
                str(malformed_output_path),
            ]
        )

        self.assertEqual(malformed_exit, 1)
        malformed_report = json.loads(malformed_output_path.read_text(encoding="utf-8"))
        self.assertFalse(malformed_report["validation"]["passed"])
        self.assertIn(
            "required ChatGPT result intake metric is not true: result_packet_loaded",
            malformed_report["validation"]["blockers"],
        )

        bad_json_path.write_text("{not json", encoding="utf-8")
        bad_json_exit = intake.main(
            [
                "--input",
                str(bad_json_path),
                "--output",
                str(bad_json_output_path),
            ]
        )

        self.assertEqual(bad_json_exit, 1)
        bad_json_report = json.loads(bad_json_output_path.read_text(encoding="utf-8"))
        self.assertFalse(bad_json_report["passed"])
        self.assertEqual(
            bad_json_report["blockers"],
            ["result packet JSON could not be loaded"],
        )

        conflict_exit = intake.main(
            [
                "--input",
                str(input_path),
                "--validate-report",
                str(output_path),
                "--output",
                str(conflict_output_path),
            ]
        )

        self.assertEqual(conflict_exit, 1)
        conflict_report = json.loads(conflict_output_path.read_text(encoding="utf-8"))
        self.assertFalse(conflict_report["passed"])
        self.assertEqual(
            conflict_report["blockers"],
            ["--input and --validate-report are mutually exclusive"],
        )

    def test_build_report_handles_malformed_nested_packet_without_probe_traceback(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = {"packet_type": "formowl_chatgpt_mcp_result_packet_v1"}

        report = intake.build_chatgpt_result_intake_report(packet)

        self.assertFalse(report["validation"]["passed"])
        self.assertFalse(report["metrics"]["negative_packet_probes_rejected"])
        self.assertEqual(report["safe_outputs"]["negative_packet_probe_count"], 0)
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("traceback", rendered)
        self.assertNotIn(str(SCRIPT_PATH.parent.parent).lower(), rendered)

    def test_validate_result_packet_rejects_sequence_tool_and_task_shape_gaps(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        packet["observed_session"]["sequence"][2]["step"] = "tools/call:wrong_tool"
        packet["observed_session"]["observed_required_tool_names"] = []
        packet["observed_session"]["observed_tool_names_hash"] = sha256_json([])
        packet["open_upload_session_result"]["called"] = False
        packet["open_upload_session_result"]["validation_passed"] = False
        packet["open_upload_session_result"]["task_card_type"] = "generic_upload"
        packet["open_upload_session_result"]["task_card_shape_hash"] = "sha256:short"
        packet["open_upload_session_result"]["upload_session_shape_hash"] = True
        packet["open_upload_session_result"]["accepted_asset_types"] = ["pst"]

        validation = intake.validate_result_packet(packet)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "observed_session.observed_required_tool_names mismatch",
            validation["blockers"],
        )
        self.assertIn(
            "observed_session.observed_tool_names_hash mismatch",
            validation["blockers"],
        )
        self.assertIn(
            "observed_session.sequence steps mismatch",
            validation["blockers"],
        )
        self.assertIn(
            "open_upload_session_result.called must be true",
            validation["blockers"],
        )
        self.assertIn(
            "open_upload_session_result.validation_passed must be true",
            validation["blockers"],
        )
        self.assertIn(
            "open_upload_session_result.task_card_type mismatch",
            validation["blockers"],
        )
        self.assertIn(
            "open_upload_session_result.task_card_shape_hash must be a sha256 hash",
            validation["blockers"],
        )
        self.assertIn(
            "open_upload_session_result.upload_session_shape_hash must be a " "sha256 hash",
            validation["blockers"],
        )
        self.assertIn(
            "open_upload_session_result.accepted_asset_types mismatch",
            validation["blockers"],
        )

    def test_validate_result_packet_rejects_non_object_bool_counts_duplicate_hashes(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        first_hash = packet["observed_session"]["sequence"][0]["response_shape_hash"]
        packet["observed_session"]["sequence"][2]["response_shape_hash"] = first_hash
        packet["preflight_contract"]["required_environment_name_count"] = True
        packet["claim_boundary"]["supports_kg_write_claim"] = True

        validation = intake.validate_result_packet(packet)
        non_object_validation = intake.validate_result_packet([])

        self.assertFalse(validation["passed"])
        self.assertIn(
            "observed_session response hashes must be distinct",
            validation["blockers"],
        )
        self.assertIn(
            "preflight_contract.required_environment_name_count must be 5",
            validation["blockers"],
        )
        self.assertIn(
            "result_packet forbidden claim is not explicitly false: " "supports_kg_write_claim",
            validation["blockers"],
        )
        self.assertFalse(non_object_validation["passed"])
        self.assertEqual(
            non_object_validation["blockers"],
            ["result packet must be an object"],
        )

    def test_build_report_sanitizes_invalid_packet_values_before_safe_outputs(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        packet["observed_session"]["observed_tool_count"] = "C:\\private\\mail.pst"
        packet["open_upload_session_result"]["task_card_shape_hash"] = "FORMOWL_DATA_DIR=private"
        packet["open_upload_session_result"]["upload_session_shape_hash"] = (
            "formowl_upload_session:upload_private"
        )

        report = intake.build_chatgpt_result_intake_report(packet)

        self.assertFalse(report["validation"]["passed"])
        self.assertIsNone(report["safe_outputs"]["observed_tool_count"])
        self.assertIsNone(report["safe_outputs"]["task_card_shape_hash"])
        self.assertIsNone(report["safe_outputs"]["upload_session_shape_hash"])
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("C:\\private", rendered)
        self.assertNotIn("FORMOWL_DATA_DIR=private", rendered)
        self.assertNotIn("upload_private", rendered)

    def test_validate_result_packet_rejects_hash_tampering(self) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        tampered_hash = "sha256:" + "f" * 64
        packet["preflight_contract"]["required_environment_names_hash"] = tampered_hash
        packet["preflight_contract"]["required_tool_names_hash"] = tampered_hash
        packet["preflight_contract"]["expected_sequence_hash"] = tampered_hash

        validation = intake.validate_result_packet(packet)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "preflight_contract.required_environment_names_hash does not match " "contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "preflight_contract.required_tool_names_hash does not match contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "preflight_contract.expected_sequence_hash does not match contract hash",
            validation["blockers"],
        )

    def test_validate_result_packet_rejects_leaks_and_overclaims(self) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        packet["environment_values"] = {"FORMOWL_DATA_DIR": "private"}
        packet["open_upload_session_result"]["upload_surface_locator"] = (
            "formowl_upload_session:upload_private"
        )
        packet["open_upload_session_result"]["mail_body_text"] = "private launch message"
        packet["mcp_server_command_label"] = "C:\\private\\formowl.exe"
        packet["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"] = True

        validation = intake.validate_result_packet(packet)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "result packet must not include environment values",
            validation["blockers"],
        )
        self.assertIn(
            "result packet must not include upload session locators",
            validation["blockers"],
        )
        self.assertIn(
            "result packet must not include private mail payload",
            validation["blockers"],
        )
        self.assertIn(
            "result_packet forbidden claim is not explicitly false: "
            "supports_actual_chatgpt_connected_upload_claim",
            validation["blockers"],
        )
        self.assertIn(
            "result packet leaks raw paths, credentials, SQL, or backend internals",
            validation["blockers"],
        )
        rendered = str(validation)
        self.assertNotIn("FORMOWL_DATA_DIR", rendered)
        self.assertNotIn("upload_private", rendered)
        self.assertNotIn("private launch message", rendered)
        self.assertNotIn("C:\\private", rendered)

    def test_validate_report_rejects_counts_hash_errors_and_embedded_overclaim(
        self,
    ) -> None:
        intake = _load_intake_module()
        report = intake.build_chatgpt_result_intake_report(_valid_result_packet())
        report["metrics"]["negative_packet_probes_rejected"] = False
        report["metrics"]["mail_upload_chatgpt_result_intake_passed"] = False
        report["safe_outputs"]["required_environment_name_count"] = True
        report["safe_outputs"]["expected_sequence_hash"] = "sha256:" + "f" * 64
        response_hashes = report["safe_outputs"]["chatgpt_response_shape_hashes"]
        report["safe_outputs"]["chatgpt_response_shape_hashes"] = [
            response_hashes[0],
            response_hashes[1],
            response_hashes[0],
        ]
        report["validation"] = {
            "passed": True,
            "blockers": [],
            "claim_boundary": {
                "supports_chatgpt_result_intake_validation_claim": True,
                "supports_actual_chatgpt_connected_upload_claim": True,
                "supports_production_ready_claim": False,
            },
        }

        validation = intake.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required ChatGPT result intake metric is not true: " "negative_packet_probes_rejected",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.required_environment_name_count must be 5",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.expected_sequence_hash does not match contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.chatgpt_response_shape_hashes must contain distinct hashes",
            validation["blockers"],
        )
        self.assertIn(
            "validation actual ChatGPT upload claim must be false",
            validation["blockers"],
        )

    def test_validate_report_rejects_unknown_keys_without_echoing_names(self) -> None:
        intake = _load_intake_module()
        report = intake.build_chatgpt_result_intake_report(_valid_result_packet())
        report["raw_debug_path"] = "C:\\private\\mail.pst"

        validation = intake.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertTrue(
            any(
                blocker.startswith("report contains unknown keys: count=1 hash=sha256:")
                for blocker in validation["blockers"]
            )
        )
        self.assertIn(
            "public report leaks raw paths, credentials, SQL, or backend internals",
            validation["blockers"],
        )
        self.assertNotIn("raw_debug_path", str(validation))
        self.assertNotIn("C:\\private", str(validation))


def _valid_result_packet() -> dict:
    hashes = ["sha256:" + f"{index:x}" * 64 for index in range(1, 16)]
    return {
        "packet_type": "formowl_chatgpt_mcp_result_packet_v1",
        "evidence_mode": "operator_supplied_chatgpt_mcp_session_result",
        "server_label": "formowl_mail_upload_phase1",
        "mcp_server_command_label": "formowl-semantic-mcp-jsonrpc",
        "preflight_contract": {
            "connection_preflight_report_type": ("mail_upload_chatgpt_connection_preflight"),
            "required_environment_name_count": 5,
            "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
            "required_tool_count": 1,
            "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
            "expected_sequence_step_count": 3,
            "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
        },
        "observed_session": {
            "chatgpt_client_label": "chatgpt",
            "transport": "stdio_jsonrpc",
            "sequence": [
                {
                    "step": "initialize",
                    "status": "ok",
                    "response_shape_hash": hashes[0],
                },
                {
                    "step": "tools/list",
                    "status": "ok",
                    "response_shape_hash": hashes[1],
                },
                {
                    "step": "tools/call:open_upload_session",
                    "status": "ok",
                    "response_shape_hash": hashes[2],
                },
            ],
            "observed_tool_count": 9,
            "observed_required_tool_names": ["open_upload_session"],
            "observed_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
        },
        "open_upload_session_result": {
            "called": True,
            "status": "ok",
            "result_type": "upload_session_request",
            "task_card_type": "mail_archive_upload_task",
            "next_required_action": "upload_mail_archive",
            "upload_locator_kind": "formowl_upload_session",
            "validation_passed": True,
            "task_card_shape_hash": hashes[3],
            "upload_session_shape_hash": hashes[4],
            "accepted_asset_types": ["pst", "ost", "msg", "eml", "mbox"],
        },
        "operator_attestation": {
            "chatgpt_mcp_session_used": True,
            "chatgpt_detail_payload_excluded": True,
            "environment_values_excluded": True,
            "session_locator_excluded": True,
            "mail_payload_excluded": True,
            "actual_file_upload_not_claimed": True,
            "source_is_operator_supplied": True,
            "not_cryptographic_proof": True,
        },
        "claim_boundary": {
            "supports_operator_supplied_chatgpt_mcp_result_intake_claim": True,
            "supports_chatgpt_open_upload_session_result_packet_claim": True,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_direct_chatgpt_session_verification_claim": False,
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


if __name__ == "__main__":
    unittest.main()
