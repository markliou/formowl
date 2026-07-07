from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

import _paths  # noqa: F401
from formowl_contract import sha256_json


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "mail_evidence_chatgpt_result_intake.py"
)
REQUIRED_ENV_NAMES = [
    "FORMOWL_DATA_DIR",
    "FORMOWL_MCP_SESSION_ID",
    "FORMOWL_MCP_ACTOR_USER_ID",
    "FORMOWL_MCP_WORKSPACE_ID",
    "FORMOWL_MAIL_UPLOAD_EXPIRES_AT",
]
REQUIRED_TOOL_NAMES = ["query_mail_evidence", "answer_mail_case_progress"]
EXPECTED_SEQUENCE = [
    "initialize",
    "tools/list",
    "tools/call:query_mail_evidence:owner",
    "tools/call:query_mail_evidence:denied",
    "tools/call:answer_mail_case_progress:owner",
    "tools/call:answer_mail_case_progress:denied",
]
EXPECTED_STATUS_CONTRACT = {
    "query_owner_status": "ok",
    "query_denied_status": "permission_denied",
    "case_progress_owner_status": "ok",
    "case_progress_denied_status": "permission_denied",
}
NEGATIVE_PACKET_PROBE_NAMES = [
    "environment_values_present",
    "raw_fixture_identifier_present",
    "unsupported_selector_kind_present",
    "mail_payload_text_present",
    "raw_query_or_case_text_present",
    "raw_chatgpt_transcript_present",
    "pending_handler_fallback_present",
    "tampered_smoke_contract_hash",
    "duplicate_response_hash",
    "raw_command_path_present",
    "raw_sql_present",
    "parser_internal_present",
    "upload_locator_present",
    "actual_upload_or_file_transfer_overclaim",
    "production_ready_overclaim",
    "kg_or_wiki_overclaim",
    "permission_bypass_overclaim",
    "unknown_extra_key_present",
    "bool_count_present",
    "wrong_tool_sequence",
    "missing_case_progress_result",
]


def _load_intake_module():
    spec = importlib.util.spec_from_file_location(
        "mail_evidence_chatgpt_result_intake",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load mail evidence ChatGPT intake script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailEvidenceChatGptResultIntakeTests(unittest.TestCase):
    def test_intake_accepts_bounded_mail_evidence_packet_without_overclaims(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()

        report = intake.build_mail_evidence_chatgpt_result_intake_report(packet)

        self.assertTrue(report["validation"]["passed"])
        self.assertTrue(report["metrics"]["mail_evidence_chatgpt_result_intake_passed"])
        self.assertTrue(report["metrics"]["smoke_contract_bound"])
        self.assertTrue(report["metrics"]["chatgpt_mcp_sequence_observed"])
        self.assertTrue(report["metrics"]["required_tools_available"])
        self.assertTrue(report["metrics"]["query_mail_evidence_owner_passed"])
        self.assertTrue(report["metrics"]["query_mail_evidence_denied_redacted"])
        self.assertTrue(report["metrics"]["answer_mail_case_progress_owner_passed"])
        self.assertTrue(report["metrics"]["answer_mail_case_progress_denied_redacted"])
        self.assertTrue(report["metrics"]["negative_packet_probes_rejected"])
        self.assertTrue(
            report["claim_boundary"][
                "supports_mail_evidence_chatgpt_result_intake_validation_claim"
            ]
        )
        self.assertTrue(
            report["claim_boundary"][
                "supports_operator_supplied_chatgpt_mail_evidence_smoke_packet_claim"
            ]
        )
        self.assertTrue(
            report["claim_boundary"][
                "supports_chatgpt_fixture_backed_mail_evidence_result_intake_claim"
            ]
        )
        self.assertFalse(report["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"])
        self.assertFalse(
            report["claim_boundary"]["supports_direct_chatgpt_session_verification_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_cryptographic_chatgpt_proof_claim"])
        self.assertFalse(report["claim_boundary"]["supports_actual_file_transfer_claim"])
        self.assertFalse(report["claim_boundary"]["supports_upload_ui_claim"])
        self.assertFalse(report["claim_boundary"]["supports_real_pst_parser_claim"])
        self.assertFalse(report["claim_boundary"]["supports_kg_write_claim"])
        self.assertFalse(report["claim_boundary"]["supports_wiki_projection_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])
        self.assertEqual(report["safe_outputs"]["required_environment_name_count"], 5)
        self.assertEqual(report["safe_outputs"]["required_tool_count"], 2)
        self.assertEqual(report["safe_outputs"]["expected_sequence_step_count"], 6)
        self.assertEqual(report["safe_outputs"]["observed_sequence_step_count"], 6)
        self.assertEqual(
            report["safe_outputs"]["negative_packet_probe_count"],
            len(NEGATIVE_PACKET_PROBE_NAMES),
        )
        self.assertEqual(report["safe_outputs"]["query_owner_status"], "ok")
        self.assertEqual(
            report["safe_outputs"]["query_denied_status"],
            "permission_denied",
        )
        self.assertEqual(report["safe_outputs"]["query_owner_citation_count"], 2)
        self.assertEqual(report["safe_outputs"]["query_denied_citation_count"], 0)
        self.assertEqual(report["safe_outputs"]["case_progress_owner_status"], "ok")
        self.assertEqual(
            report["safe_outputs"]["case_progress_denied_status"],
            "permission_denied",
        )
        self.assertEqual(
            report["safe_outputs"]["case_progress_owner_citation_count"],
            2,
        )
        self.assertEqual(
            report["safe_outputs"]["case_progress_denied_citation_count"],
            0,
        )

        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("formowl_data_dir", rendered)
        self.assertNotIn("formowl_mcp_session_id", rendered)
        self.assertNotIn("formowl_upload_session:", rendered)
        self.assertNotIn("mailbundle_raw", rendered)
        self.assertNotIn("message-id", rendered)
        self.assertNotIn("mail_body", rendered)
        self.assertNotIn("query_text", rendered)
        self.assertNotIn("waiting on audit approval", rendered)
        self.assertNotIn("select * from", rendered)
        self.assertNotIn(str(SCRIPT_PATH.parent.parent).lower(), rendered)

    def test_report_contains_only_safe_hash_status_count_outputs(self) -> None:
        intake = _load_intake_module()

        report = intake.build_mail_evidence_chatgpt_result_intake_report(_valid_result_packet())

        self.assertEqual(
            set(report),
            {
                "report_type",
                "generated_at",
                "metrics",
                "safe_outputs",
                "claim_boundary",
                "validation",
            },
        )
        self.assertEqual(
            set(report["safe_outputs"]),
            {
                "result_profile",
                "packet_shape_hash",
                "smoke_contract_shape_hash",
                "required_environment_name_count",
                "required_environment_names_hash",
                "required_tool_count",
                "required_tool_names_hash",
                "expected_sequence_step_count",
                "expected_sequence_hash",
                "observed_sequence_step_count",
                "observed_sequence_hash",
                "observed_tool_count",
                "observed_required_tool_names_hash",
                "fixture_smoke_report_hash",
                "fixture_asset_id_hash",
                "fixture_mail_evidence_bundle_id_hash",
                "fixture_mail_import_session_id_hash",
                "fixture_observation_count",
                "query_owner_status",
                "query_owner_evidence_snippet_count",
                "query_owner_citation_count",
                "query_denied_status",
                "query_denied_evidence_snippet_count",
                "query_denied_citation_count",
                "query_denied_hidden_bundle_count",
                "query_denied_hidden_message_count",
                "case_progress_owner_status",
                "case_progress_owner_answer_item_count",
                "case_progress_owner_citation_count",
                "case_progress_denied_status",
                "case_progress_denied_answer_item_count",
                "case_progress_denied_citation_count",
                "case_progress_denied_hidden_bundle_count",
                "case_progress_denied_hidden_message_count",
                "tool_call_request_shape_hashes",
                "chatgpt_response_shape_hashes",
                "operator_attestation_shape_hash",
                "negative_packet_probe_count",
                "negative_packet_probe_names_hash",
                "negative_packet_probe_shape_hashes",
            },
        )
        self.assertEqual(
            report["safe_outputs"]["required_environment_names_hash"],
            sha256_json(REQUIRED_ENV_NAMES),
        )
        self.assertEqual(
            report["safe_outputs"]["required_tool_names_hash"],
            sha256_json(REQUIRED_TOOL_NAMES),
        )
        self.assertEqual(
            report["safe_outputs"]["expected_sequence_hash"],
            sha256_json(EXPECTED_SEQUENCE),
        )
        self.assertEqual(
            report["safe_outputs"]["negative_packet_probe_names_hash"],
            sha256_json(NEGATIVE_PACKET_PROBE_NAMES),
        )
        self.assertEqual(
            len(report["safe_outputs"]["tool_call_request_shape_hashes"]),
            4,
        )
        self.assertEqual(
            len(report["safe_outputs"]["chatgpt_response_shape_hashes"]),
            6,
        )

    def test_main_reads_packet_writes_report_and_validates_report(self) -> None:
        intake = _load_intake_module()
        temp_dir = _paths.fresh_test_dir("mail-evidence-chatgpt-intake-cli")
        input_path = temp_dir / "packet.json"
        output_path = temp_dir / "report.json"
        validation_path = temp_dir / "validation.json"
        invalid_report_path = temp_dir / "invalid-report.json"
        bad_packet_path = temp_dir / "bad-packet.json"
        bad_packet_output_path = temp_dir / "bad-packet-output.json"
        bad_report_path = temp_dir / "bad-report.json"
        bad_report_output_path = temp_dir / "bad-report-output.json"
        conflict_output_path = temp_dir / "conflict-output.json"
        input_path.write_text(
            json.dumps(_valid_result_packet(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        output_path.write_text("stale output", encoding="utf-8")

        exit_code = intake.main(["--input", str(input_path), "--output", str(output_path)])

        self.assertEqual(exit_code, 0)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertTrue(report["validation"]["passed"])
        self.assertNotEqual(output_path.read_text(encoding="utf-8"), "stale output")

        validation_exit = intake.main(
            [
                "--validate-report",
                str(output_path),
                "--output",
                str(validation_path),
            ]
        )
        self.assertEqual(validation_exit, 0)
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertTrue(validation["passed"])

        invalid_report_path.write_text(json.dumps([], sort_keys=True), encoding="utf-8")
        invalid_exit = intake.main(
            [
                "--validate-report",
                str(invalid_report_path),
                "--output",
                str(validation_path),
            ]
        )
        self.assertEqual(invalid_exit, 1)
        invalid_validation = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertFalse(invalid_validation["passed"])
        self.assertEqual(invalid_validation["blockers"], ["report must be an object"])

        bad_packet_path.write_text("{not json", encoding="utf-8")
        bad_packet_exit = intake.main(
            [
                "--input",
                str(bad_packet_path),
                "--output",
                str(bad_packet_output_path),
            ]
        )
        self.assertEqual(bad_packet_exit, 1)
        bad_packet_output = json.loads(bad_packet_output_path.read_text(encoding="utf-8"))
        self.assertEqual(
            bad_packet_output["blockers"],
            ["result packet JSON could not be loaded"],
        )

        bad_report_path.write_text("{not json", encoding="utf-8")
        bad_report_exit = intake.main(
            [
                "--validate-report",
                str(bad_report_path),
                "--output",
                str(bad_report_output_path),
            ]
        )
        self.assertEqual(bad_report_exit, 1)
        bad_report_output = json.loads(bad_report_output_path.read_text(encoding="utf-8"))
        self.assertEqual(
            bad_report_output["blockers"],
            ["report JSON could not be loaded"],
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
        conflict_output = json.loads(conflict_output_path.read_text(encoding="utf-8"))
        self.assertEqual(
            conflict_output["blockers"],
            ["--input and --validate-report are mutually exclusive"],
        )

    def test_build_report_handles_malformed_nested_packet_without_probe_traceback(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = {"packet_type": "formowl_mail_evidence_chatgpt_mcp_result_packet_v1"}

        report = intake.build_mail_evidence_chatgpt_result_intake_report(packet)

        self.assertFalse(report["validation"]["passed"])
        self.assertFalse(report["metrics"]["negative_packet_probes_rejected"])
        self.assertEqual(report["safe_outputs"]["negative_packet_probe_count"], 0)
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("traceback", rendered)
        self.assertNotIn(str(SCRIPT_PATH.parent.parent).lower(), rendered)

    def test_validate_result_packet_rejects_tool_sequence_and_result_gaps(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        packet["observed_session"]["sequence"][2]["step"] = "tools/call:wrong"
        packet["observed_session"]["observed_required_tool_names"] = ["query_mail_evidence"]
        packet["observed_session"]["observed_tool_names_hash"] = sha256_json(
            ["query_mail_evidence"]
        )
        packet["query_mail_evidence_result"]["owner_status"] = "pending_review"
        packet["query_mail_evidence_result"]["owner_citation_count"] = 0
        packet["answer_mail_case_progress_result"]["called"] = False
        packet["answer_mail_case_progress_result"]["owner_status"] = "error"
        packet["answer_mail_case_progress_result"]["owner_citation_count"] = 0

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
            "query_mail_evidence_result.owner_status must be ok",
            validation["blockers"],
        )
        self.assertIn(
            "query_mail_evidence_result.owner_citation_count must be positive",
            validation["blockers"],
        )
        self.assertIn(
            "answer_mail_case_progress_result.called must be true",
            validation["blockers"],
        )
        self.assertIn(
            "answer_mail_case_progress_result.owner_status must be ok",
            validation["blockers"],
        )
        self.assertIn(
            "answer_mail_case_progress_result.owner_citation_count must be positive",
            validation["blockers"],
        )

    def test_validate_result_packet_rejects_bool_counts_and_duplicate_hashes(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        first_hash = packet["observed_session"]["sequence"][0]["response_shape_hash"]
        packet["observed_session"]["sequence"][5]["response_shape_hash"] = first_hash
        packet["answer_mail_case_progress_result"]["denied_response_shape_hash"] = first_hash
        packet["smoke_contract"]["observation_count"] = True
        packet["query_mail_evidence_result"]["owner_evidence_snippet_count"] = True
        packet["claim_boundary"]["supports_permission_bypass_claim"] = True

        validation = intake.validate_result_packet(packet)
        non_object_validation = intake.validate_result_packet([])

        self.assertFalse(validation["passed"])
        self.assertIn(
            "observed_session response hashes must be distinct",
            validation["blockers"],
        )
        self.assertIn(
            "smoke_contract.observation_count must be positive",
            validation["blockers"],
        )
        self.assertIn(
            "query_mail_evidence_result.owner_evidence_snippet_count must be positive",
            validation["blockers"],
        )
        self.assertIn(
            "result_packet forbidden claim is not explicitly false: "
            "supports_permission_bypass_claim",
            validation["blockers"],
        )
        self.assertFalse(non_object_validation["passed"])
        self.assertEqual(
            non_object_validation["blockers"],
            ["result packet must be an object"],
        )

    def test_validate_result_packet_rejects_selector_kind_tampering_without_echo(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        packet["query_mail_evidence_result"]["owner_selector_kind"] = "mail_import_session_id_raw"
        packet["query_mail_evidence_result"]["denied_selector_kind"] = "message_id"
        packet["answer_mail_case_progress_result"]["owner_selector_kind"] = "not_fixture_bound"
        packet["answer_mail_case_progress_result"]["denied_selector_kind"] = "case_id"

        validation = intake.validate_result_packet(packet)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "query_mail_evidence_result.owner_selector_kind must be " "mail_import_session_hash",
            validation["blockers"],
        )
        self.assertIn(
            "query_mail_evidence_result.denied_selector_kind must be " "mail_import_session_hash",
            validation["blockers"],
        )
        self.assertIn(
            "answer_mail_case_progress_result.owner_selector_kind must be "
            "mail_import_session_hash",
            validation["blockers"],
        )
        self.assertIn(
            "answer_mail_case_progress_result.denied_selector_kind must be "
            "mail_import_session_hash",
            validation["blockers"],
        )
        rendered = str(validation)
        self.assertNotIn("mail_import_session_id_raw", rendered)
        self.assertNotIn("not_fixture_bound", rendered)
        self.assertNotIn("message_id", rendered)
        self.assertNotIn("case_id", rendered)

    def test_validate_result_packet_rejects_static_hash_tampering(self) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        tampered = "sha256:" + "f" * 64
        packet["smoke_contract"]["fixture_smoke_report_hash"] = tampered
        packet["smoke_contract"]["asset_id_hash"] = tampered
        packet["smoke_contract"]["required_environment_names_hash"] = tampered
        packet["smoke_contract"]["required_tool_names_hash"] = tampered
        packet["smoke_contract"]["expected_sequence_hash"] = tampered
        packet["smoke_contract"]["expected_status_contract_hash"] = tampered
        packet["query_mail_evidence_result"]["owner_request_shape_hash"] = tampered
        packet["answer_mail_case_progress_result"]["owner_request_shape_hash"] = tampered

        validation = intake.validate_result_packet(packet)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "smoke_contract.fixture_smoke_report_hash does not match " "checkpoint O smoke",
            validation["blockers"],
        )
        self.assertIn(
            "smoke_contract.asset_id_hash does not match checkpoint O smoke",
            validation["blockers"],
        )
        self.assertIn(
            "smoke_contract.required_environment_names_hash does not match " "contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "smoke_contract.required_tool_names_hash does not match contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "smoke_contract.expected_sequence_hash does not match contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "smoke_contract.expected_status_contract_hash does not match " "contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "query_mail_evidence_result.owner_request_shape_hash does not match " "expected shape",
            validation["blockers"],
        )
        self.assertIn(
            "answer_mail_case_progress_result.owner_request_shape_hash does not "
            "match expected shape",
            validation["blockers"],
        )

    def test_validate_result_packet_rejects_leaks_and_overclaims_without_echo(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        packet["environment_values"] = {"FORMOWL_DATA_DIR": "private"}
        packet["upload_surface_locator"] = "formowl_upload_session:upload_private"
        packet["query_mail_evidence_result"]["query_text"] = "What is the latest blocker?"
        packet["answer_mail_case_progress_result"]["mail_body"] = (
            "Blocker: Waiting on audit approval"
        )
        packet["mcp_server_command_label"] = "C:\\private\\formowl.exe"
        packet["sql"] = "select * from private_mail"
        packet["claim_boundary"]["supports_actual_file_transfer_claim"] = True

        validation = intake.validate_result_packet(packet)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "result packet must not include private raw payloads",
            validation["blockers"],
        )
        self.assertIn(
            "result_packet forbidden claim is not explicitly false: "
            "supports_actual_file_transfer_claim",
            validation["blockers"],
        )
        self.assertIn(
            "result packet leaks raw paths, credentials, SQL, or backend internals",
            validation["blockers"],
        )
        rendered_validation = str(validation)
        self.assertNotIn("FORMOWL_DATA_DIR", rendered_validation)
        self.assertNotIn("upload_private", rendered_validation)
        self.assertNotIn("What is the latest blocker?", rendered_validation)
        self.assertNotIn("Waiting on audit approval", rendered_validation)
        self.assertNotIn("C:\\private", rendered_validation)
        self.assertNotIn("private_mail", rendered_validation)

    def test_build_report_sanitizes_invalid_packet_values_before_safe_outputs(
        self,
    ) -> None:
        intake = _load_intake_module()
        packet = _valid_result_packet()
        packet["observed_session"]["observed_tool_count"] = "C:\\private\\mail.pst"
        packet["smoke_contract"]["fixture_smoke_report_hash"] = "FORMOWL_DATA_DIR=private"
        packet["query_mail_evidence_result"]["owner_response_shape_hash"] = (
            "formowl_upload_session:upload_private"
        )

        report = intake.build_mail_evidence_chatgpt_result_intake_report(packet)

        self.assertFalse(report["validation"]["passed"])
        self.assertIsNone(report["safe_outputs"]["observed_tool_count"])
        self.assertIsNone(report["safe_outputs"]["fixture_smoke_report_hash"])
        self.assertNotIn(
            "formowl_upload_session:upload_private",
            json.dumps(report, sort_keys=True),
        )
        self.assertNotIn("FORMOWL_DATA_DIR=private", json.dumps(report, sort_keys=True))
        self.assertNotIn("C:\\private", json.dumps(report, sort_keys=True))

    def test_validate_report_rejects_counts_hashes_and_embedded_overclaim(
        self,
    ) -> None:
        intake = _load_intake_module()
        report = intake.build_mail_evidence_chatgpt_result_intake_report(_valid_result_packet())
        report["metrics"]["negative_packet_probes_rejected"] = False
        report["metrics"]["mail_evidence_chatgpt_result_intake_passed"] = False
        report["safe_outputs"]["required_tool_count"] = True
        report["safe_outputs"]["expected_sequence_hash"] = "sha256:" + "f" * 64
        report["safe_outputs"]["fixture_smoke_report_hash"] = "sha256:" + "e" * 64
        response_hashes = report["safe_outputs"]["chatgpt_response_shape_hashes"]
        report["safe_outputs"]["chatgpt_response_shape_hashes"] = [
            response_hashes[0],
            response_hashes[1],
            response_hashes[0],
            response_hashes[3],
            response_hashes[4],
            response_hashes[5],
        ]
        request_hashes = report["safe_outputs"]["tool_call_request_shape_hashes"]
        report["safe_outputs"]["tool_call_request_shape_hashes"] = [
            request_hashes[1],
            request_hashes[0],
            request_hashes[2],
            request_hashes[3],
        ]
        report["validation"] = {
            "passed": True,
            "blockers": [],
            "claim_boundary": {
                "supports_mail_evidence_chatgpt_result_intake_validation_claim": True,
                "supports_actual_chatgpt_connected_upload_claim": True,
                "supports_production_ready_claim": False,
            },
        }

        validation = intake.validate_report(report)

        self.assertFalse(validation["passed"])
        self.assertIn(
            "required mail evidence ChatGPT result metric is not true: "
            "negative_packet_probes_rejected",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.required_tool_count must be 2",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.expected_sequence_hash does not match contract hash",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.fixture_smoke_report_hash does not match checkpoint O smoke",
            validation["blockers"],
        )
        self.assertIn(
            "safe_outputs.tool_call_request_shape_hashes does not match expected shapes",
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
        report = intake.build_mail_evidence_chatgpt_result_intake_report(_valid_result_packet())
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
    intake = _intake_for_packet_helpers()
    smoke_contract = intake.build_expected_smoke_contract()
    request_hashes = intake.build_expected_request_shape_hashes()
    hashes = [_hash(f"mail-evidence-chatgpt-{index}") for index in range(30)]
    return {
        "packet_type": "formowl_mail_evidence_chatgpt_mcp_result_packet_v1",
        "evidence_mode": "operator_supplied_chatgpt_mcp_mail_evidence_smoke_result",
        "server_label": "formowl_mail_evidence_phase1",
        "mcp_server_command_label": "formowl-semantic-mcp-jsonrpc",
        "smoke_contract": {
            "chatgpt_free_smoke_report_type": "mail_evidence_mcp_smoke",
            "fixture_profile": "formowl_fixture_backed_mail_evidence_phase1",
            "fixture_smoke_report_hash": smoke_contract["fixture_smoke_report_hash"],
            "asset_id_hash": smoke_contract["asset_id_hash"],
            "mail_evidence_bundle_id_hash": smoke_contract["mail_evidence_bundle_id_hash"],
            "mail_import_session_id_hash": smoke_contract["mail_import_session_id_hash"],
            "observation_count": smoke_contract["observation_count"],
            "required_environment_name_count": 5,
            "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
            "required_tool_count": 2,
            "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
            "expected_sequence_step_count": 6,
            "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
            "expected_status_contract_hash": sha256_json(EXPECTED_STATUS_CONTRACT),
        },
        "observed_session": {
            "chatgpt_client_label": "chatgpt",
            "transport": "stdio_jsonrpc",
            "sequence": [
                {
                    "step": EXPECTED_SEQUENCE[0],
                    "status": "ok",
                    "response_shape_hash": hashes[4],
                },
                {
                    "step": EXPECTED_SEQUENCE[1],
                    "status": "ok",
                    "response_shape_hash": hashes[5],
                },
                {
                    "step": EXPECTED_SEQUENCE[2],
                    "status": "ok",
                    "response_shape_hash": hashes[6],
                },
                {
                    "step": EXPECTED_SEQUENCE[3],
                    "status": "ok",
                    "response_shape_hash": hashes[7],
                },
                {
                    "step": EXPECTED_SEQUENCE[4],
                    "status": "ok",
                    "response_shape_hash": hashes[8],
                },
                {
                    "step": EXPECTED_SEQUENCE[5],
                    "status": "ok",
                    "response_shape_hash": hashes[9],
                },
            ],
            "observed_tool_count": 9,
            "observed_required_tool_names": REQUIRED_TOOL_NAMES,
            "observed_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
        },
        "query_mail_evidence_result": {
            "called": True,
            "result_type": "mail_evidence_query",
            "owner_status": "ok",
            "denied_status": "permission_denied",
            "owner_selector_kind": "mail_import_session_hash",
            "denied_selector_kind": "mail_import_session_hash",
            "owner_validation_passed": True,
            "denied_validation_passed": True,
            "owner_request_shape_hash": request_hashes["owner_request_shape_hash"],
            "denied_request_shape_hash": request_hashes["denied_request_shape_hash"],
            "owner_response_shape_hash": hashes[6],
            "denied_response_shape_hash": hashes[7],
            "owner_evidence_snippet_count": 2,
            "owner_citation_count": 2,
            "denied_evidence_snippet_count": 0,
            "denied_citation_count": 0,
            "denied_hidden_bundle_count": 1,
            "denied_hidden_message_count": 1,
            "pending_handler_warning_count": 0,
        },
        "answer_mail_case_progress_result": {
            "called": True,
            "result_type": "mail_case_progress_answer",
            "owner_status": "ok",
            "denied_status": "permission_denied",
            "owner_selector_kind": "mail_import_session_hash",
            "denied_selector_kind": "mail_import_session_hash",
            "owner_validation_passed": True,
            "denied_validation_passed": True,
            "owner_request_shape_hash": request_hashes["case_progress_owner_request_shape_hash"],
            "denied_request_shape_hash": request_hashes["case_progress_denied_request_shape_hash"],
            "owner_response_shape_hash": hashes[8],
            "denied_response_shape_hash": hashes[9],
            "owner_latest_update_count": 1,
            "owner_blocker_count": 1,
            "owner_responsible_party_count": 1,
            "owner_next_action_count": 1,
            "owner_deadline_count": 0,
            "owner_citation_count": 2,
            "denied_latest_update_count": 0,
            "denied_blocker_count": 0,
            "denied_responsible_party_count": 0,
            "denied_next_action_count": 0,
            "denied_deadline_count": 0,
            "denied_citation_count": 0,
            "denied_hidden_bundle_count": 1,
            "denied_hidden_message_count": 1,
            "pending_handler_warning_count": 0,
        },
        "operator_attestation": {
            "chatgpt_mcp_session_used": True,
            "chatgpt_detail_payload_excluded": True,
            "raw_tool_payload_excluded": True,
            "raw_mail_text_excluded": True,
            "concrete_mail_identifiers_excluded": True,
            "environment_values_excluded": True,
            "upload_locators_excluded": True,
            "paths_sql_parser_storage_worker_internals_excluded": True,
            "denied_probe_redaction_observed": True,
            "actual_file_upload_not_claimed": True,
            "source_is_operator_supplied": True,
            "not_direct_codex_chatgpt_verification": True,
            "not_cryptographic_proof": True,
        },
        "claim_boundary": {
            "supports_operator_supplied_chatgpt_mail_evidence_smoke_packet_claim": True,
            "supports_chatgpt_fixture_backed_mail_evidence_result_intake_claim": True,
            "supports_chatgpt_fixture_backed_case_progress_result_intake_claim": True,
            "container_verification_required": True,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_actual_file_transfer_claim": False,
            "supports_upload_ui_claim": False,
            "supports_production_iframe_readiness_claim": False,
            "supports_real_pst_parser_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_postgresql_mail_evidence_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_raw_mail_content_access_claim": False,
            "supports_live_mailbox_access_claim": False,
            "supports_database_control_surface_claim": False,
            "supports_permission_bypass_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_production_ready_claim": False,
            "supports_direct_chatgpt_session_verification_claim": False,
            "supports_cryptographic_chatgpt_proof_claim": False,
        },
    }


def _hash(label: str) -> str:
    return sha256_json({"label": label})


def _intake_for_packet_helpers():
    module = sys.modules.get("mail_evidence_chatgpt_result_intake")
    if module is not None:
        return module
    return _load_intake_module()


if __name__ == "__main__":
    unittest.main()
