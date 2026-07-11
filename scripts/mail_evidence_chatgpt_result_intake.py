#!/usr/bin/env python3
"""Validate a bounded FormOwl #21 ChatGPT mail evidence smoke result packet.

This intake is for the step after an operator manually connects ChatGPT to a
FormOwl MCP server and calls the fixture-backed ``query_mail_evidence`` and
``answer_mail_case_progress`` tools. It validates only a hash/status/count
packet. It must not receive raw ChatGPT transcripts, raw tool payloads, mail
body text, snippets, concrete mail identifiers, upload locators, environment
values, raw paths, SQL, parser internals, storage internals, or worker internals.

The intake does not directly control ChatGPT, provide cryptographic proof of a
ChatGPT session, prove file transfer, claim a production iframe, claim real
PST/OST/MSG/EML/MBOX parsing, claim live PostgreSQL readiness, claim production
worker leasing, write KG/wiki state, or claim production readiness.
"""

from __future__ import annotations

import argparse
from functools import lru_cache
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
SCRIPTS_ROOT = ROOT / "scripts"
for import_root in (PYTHON_ROOT, SCRIPTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_contract import assert_no_public_raw_references, sha256_json  # noqa: E402
from formowl_evaluator.intake import (  # noqa: E402
    is_sha256 as _is_sha256,
    public_payload_is_safe,
    validate_exact_keys as _validate_exact_keys,
    validate_hash_list as _validate_hash_list,
)
from formowl_gateway import validate_public_gateway_payload  # noqa: E402


DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "formowl-mail-evidence-chatgpt-result-intake.json"
NOW = "2026-07-06T08:00:00+00:00"
RESULT_PACKET_TYPE = "formowl_mail_evidence_chatgpt_mcp_result_packet_v1"
EVIDENCE_MODE = "operator_supplied_chatgpt_mcp_mail_evidence_smoke_result"
SERVER_LABEL = "formowl_mail_evidence_phase1"
DEFAULT_COMMAND_NAME = "formowl-semantic-mcp-jsonrpc"
CHATGPT_FREE_SMOKE_REPORT_TYPE = "mail_evidence_mcp_smoke"
FIXTURE_PROFILE = "formowl_fixture_backed_mail_evidence_phase1"
REQUIRED_ENV_NAMES = [
    "FORMOWL_DATA_DIR",
    "FORMOWL_MCP_SESSION_ID",
    "FORMOWL_MCP_ACTOR_USER_ID",
    "FORMOWL_MCP_WORKSPACE_ID",
    "FORMOWL_MAIL_UPLOAD_EXPIRES_AT",
]
REQUIRED_TOOL_NAMES = [
    "query_mail_evidence",
    "answer_mail_case_progress",
]
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
EXPECTED_SELECTOR_KIND = "mail_import_session_hash"
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
REQUIRED_TRUE_METRICS = [
    "result_packet_loaded",
    "smoke_contract_bound",
    "server_label_matches",
    "chatgpt_mcp_sequence_observed",
    "required_tools_available",
    "query_mail_evidence_owner_passed",
    "query_mail_evidence_denied_redacted",
    "answer_mail_case_progress_owner_passed",
    "answer_mail_case_progress_denied_redacted",
    "operator_attestation_complete",
    "packet_claim_boundary_honest",
    "packet_omits_private_payloads",
    "negative_packet_probes_rejected",
    "safe_outputs_hash_status_count_only",
    "raw_leak_guard_passed",
    "mail_evidence_chatgpt_result_intake_passed",
]

FORBIDDEN_TRUE_CLAIMS = [
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_actual_file_transfer_claim",
    "supports_upload_ui_claim",
    "supports_production_iframe_readiness_claim",
    "supports_real_pst_parser_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_postgresql_mail_evidence_claim",
    "supports_production_worker_leasing_claim",
    "supports_raw_mail_content_access_claim",
    "supports_live_mailbox_access_claim",
    "supports_database_control_surface_claim",
    "supports_permission_bypass_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_production_ready_claim",
    "supports_direct_chatgpt_session_verification_claim",
    "supports_cryptographic_chatgpt_proof_claim",
]

TRUE_PACKET_CLAIMS = [
    "supports_operator_supplied_chatgpt_mail_evidence_smoke_packet_claim",
    "supports_chatgpt_fixture_backed_mail_evidence_result_intake_claim",
    "supports_chatgpt_fixture_backed_case_progress_result_intake_claim",
    "container_verification_required",
]

TRUE_REPORT_CLAIMS = [
    "supports_mail_evidence_chatgpt_result_intake_validation_claim",
    "supports_operator_supplied_chatgpt_mail_evidence_smoke_packet_claim",
    "supports_chatgpt_fixture_backed_mail_evidence_result_intake_claim",
    "supports_chatgpt_fixture_backed_case_progress_result_intake_claim",
    "container_verification_required",
]


def build_mail_evidence_chatgpt_result_intake_report(
    packet: Any,
) -> dict[str, Any]:
    packet_validation = validate_result_packet(packet)
    packet_dict = packet if isinstance(packet, dict) else {}
    smoke_contract = _dict_or_empty(packet_dict.get("smoke_contract"))
    observed_session = _dict_or_empty(packet_dict.get("observed_session"))
    query_result = _dict_or_empty(packet_dict.get("query_mail_evidence_result"))
    case_result = _dict_or_empty(packet_dict.get("answer_mail_case_progress_result"))
    negative_results = (
        _run_negative_packet_probes(packet_dict) if packet_validation["passed"] is True else []
    )
    metrics = {
        "result_packet_loaded": isinstance(packet, dict),
        "smoke_contract_bound": _smoke_contract_bound(smoke_contract),
        "server_label_matches": packet_dict.get("server_label") == SERVER_LABEL
        and packet_dict.get("mcp_server_command_label") == DEFAULT_COMMAND_NAME,
        "chatgpt_mcp_sequence_observed": _observed_sequence_steps(observed_session)
        == EXPECTED_SEQUENCE,
        "required_tools_available": observed_session.get("observed_required_tool_names")
        == REQUIRED_TOOL_NAMES
        and observed_session.get("observed_tool_names_hash") == sha256_json(REQUIRED_TOOL_NAMES),
        "query_mail_evidence_owner_passed": _query_owner_passed(query_result),
        "query_mail_evidence_denied_redacted": _query_denied_redacted(query_result),
        "answer_mail_case_progress_owner_passed": _case_owner_passed(case_result),
        "answer_mail_case_progress_denied_redacted": _case_denied_redacted(case_result),
        "operator_attestation_complete": _operator_attestation_complete(
            _dict_or_empty(packet_dict.get("operator_attestation"))
        ),
        "packet_claim_boundary_honest": _packet_claim_boundary_honest(
            _dict_or_empty(packet_dict.get("claim_boundary"))
        ),
        "packet_omits_private_payloads": _packet_omits_private_payloads(packet_dict),
        "negative_packet_probes_rejected": packet_validation["passed"] is True
        and bool(negative_results)
        and all(result["validation"]["passed"] is False for result in negative_results),
        "safe_outputs_hash_status_count_only": True,
        "raw_leak_guard_passed": True,
    }
    metrics["mail_evidence_chatgpt_result_intake_passed"] = packet_validation[
        "passed"
    ] is True and all(metrics.values())
    safe_outputs = {
        "result_profile": ("operator_supplied_chatgpt_mcp_fixture_mail_evidence_result"),
        "packet_shape_hash": _result_packet_shape_hash(packet_dict),
        "smoke_contract_shape_hash": _smoke_contract_shape_hash(smoke_contract),
        "required_environment_name_count": len(REQUIRED_ENV_NAMES),
        "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
        "required_tool_count": len(REQUIRED_TOOL_NAMES),
        "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
        "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
        "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
        "observed_sequence_step_count": len(_observed_sequence_steps(observed_session)),
        "observed_sequence_hash": sha256_json(_observed_sequence_steps(observed_session)),
        "observed_tool_count": _safe_int_or_none(observed_session.get("observed_tool_count")),
        "observed_required_tool_names_hash": _safe_hash_or_none(
            observed_session.get("observed_tool_names_hash")
        ),
        "fixture_smoke_report_hash": _safe_hash_or_none(
            smoke_contract.get("fixture_smoke_report_hash")
        ),
        "fixture_asset_id_hash": _safe_hash_or_none(smoke_contract.get("asset_id_hash")),
        "fixture_mail_evidence_bundle_id_hash": _safe_hash_or_none(
            smoke_contract.get("mail_evidence_bundle_id_hash")
        ),
        "fixture_mail_import_session_id_hash": _safe_hash_or_none(
            smoke_contract.get("mail_import_session_id_hash")
        ),
        "fixture_observation_count": _safe_int_or_none(smoke_contract.get("observation_count")),
        "query_owner_status": _safe_status_or_none(query_result.get("owner_status")),
        "query_owner_evidence_snippet_count": _safe_int_or_none(
            query_result.get("owner_evidence_snippet_count")
        ),
        "query_owner_citation_count": _safe_int_or_none(query_result.get("owner_citation_count")),
        "query_denied_status": _safe_status_or_none(query_result.get("denied_status")),
        "query_denied_evidence_snippet_count": _safe_int_or_none(
            query_result.get("denied_evidence_snippet_count")
        ),
        "query_denied_citation_count": _safe_int_or_none(query_result.get("denied_citation_count")),
        "query_denied_hidden_bundle_count": _safe_int_or_none(
            query_result.get("denied_hidden_bundle_count")
        ),
        "query_denied_hidden_message_count": _safe_int_or_none(
            query_result.get("denied_hidden_message_count")
        ),
        "case_progress_owner_status": _safe_status_or_none(case_result.get("owner_status")),
        "case_progress_owner_answer_item_count": _case_owner_answer_item_count(case_result),
        "case_progress_owner_citation_count": _safe_int_or_none(
            case_result.get("owner_citation_count")
        ),
        "case_progress_denied_status": _safe_status_or_none(case_result.get("denied_status")),
        "case_progress_denied_answer_item_count": _case_denied_answer_item_count(case_result),
        "case_progress_denied_citation_count": _safe_int_or_none(
            case_result.get("denied_citation_count")
        ),
        "case_progress_denied_hidden_bundle_count": _safe_int_or_none(
            case_result.get("denied_hidden_bundle_count")
        ),
        "case_progress_denied_hidden_message_count": _safe_int_or_none(
            case_result.get("denied_hidden_message_count")
        ),
        "tool_call_request_shape_hashes": _tool_call_request_shape_hashes(
            query_result,
            case_result,
        ),
        "chatgpt_response_shape_hashes": _observed_sequence_response_hashes(observed_session),
        "operator_attestation_shape_hash": sha256_json(
            _dict_or_empty(packet_dict.get("operator_attestation"))
        ),
        "negative_packet_probe_count": len(negative_results),
        "negative_packet_probe_names_hash": sha256_json(NEGATIVE_PACKET_PROBE_NAMES),
        "negative_packet_probe_shape_hashes": [result["shape_hash"] for result in negative_results],
    }
    report = {
        "report_type": "mail_evidence_chatgpt_result_intake",
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": _report_claim_boundary(
            metrics["mail_evidence_chatgpt_result_intake_passed"],
            packet_validation["passed"] is True,
        ),
    }
    metrics["raw_leak_guard_passed"] = _public_outputs_are_safe(report)
    metrics["mail_evidence_chatgpt_result_intake_passed"] = packet_validation[
        "passed"
    ] is True and all(metrics.values())
    report["claim_boundary"] = _report_claim_boundary(
        metrics["mail_evidence_chatgpt_result_intake_passed"],
        packet_validation["passed"] is True,
    )
    report["validation"] = validate_report(report)
    return report


def validate_result_packet(packet: Any) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(packet, dict):
        return {
            "passed": False,
            "blockers": ["result packet must be an object"],
        }
    expected_keys = {
        "packet_type",
        "evidence_mode",
        "server_label",
        "mcp_server_command_label",
        "smoke_contract",
        "observed_session",
        "query_mail_evidence_result",
        "answer_mail_case_progress_result",
        "operator_attestation",
        "claim_boundary",
    }
    _validate_exact_keys(packet, expected_keys, "result_packet", blockers)
    if packet.get("packet_type") != RESULT_PACKET_TYPE:
        blockers.append("result_packet.packet_type mismatch")
    if packet.get("evidence_mode") != EVIDENCE_MODE:
        blockers.append("result_packet.evidence_mode mismatch")
    if packet.get("server_label") != SERVER_LABEL:
        blockers.append("result_packet.server_label mismatch")
    if packet.get("mcp_server_command_label") != DEFAULT_COMMAND_NAME:
        blockers.append("result_packet.mcp_server_command_label must use packaged command label")
    smoke_contract = _dict_or_empty(packet.get("smoke_contract"))
    observed_session = _dict_or_empty(packet.get("observed_session"))
    query_result = _dict_or_empty(packet.get("query_mail_evidence_result"))
    case_result = _dict_or_empty(packet.get("answer_mail_case_progress_result"))
    _validate_smoke_contract(smoke_contract, blockers)
    _validate_observed_session(observed_session, blockers)
    _validate_query_result(query_result, observed_session, blockers)
    _validate_case_progress_result(case_result, observed_session, blockers)
    _validate_operator_attestation(
        _dict_or_empty(packet.get("operator_attestation")),
        blockers,
    )
    _validate_packet_claim_boundary(
        _dict_or_empty(packet.get("claim_boundary")),
        blockers,
    )
    _reject_private_payload_fields(packet, blockers)
    _reject_concrete_identifier_fields(packet, blockers)
    if not _packet_omits_private_payloads(packet):
        blockers.append("result packet must not include private raw payloads")
    try:
        validate_public_gateway_payload(packet)
        assert_no_public_raw_references(packet, "mail_evidence_chatgpt_packet")
    except Exception:
        blockers.append("result packet leaks raw paths, credentials, SQL, or backend internals")
    return {"passed": not blockers, "blockers": blockers}


def validate_report(report: Any) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, dict):
        return _failure_validation("report must be an object")
    expected_top_level = {
        "report_type",
        "generated_at",
        "metrics",
        "safe_outputs",
        "claim_boundary",
    }
    _validate_exact_keys(
        report,
        expected_top_level,
        "report",
        blockers,
        allowed_extra={"validation"},
    )
    if report.get("report_type") != "mail_evidence_chatgpt_result_intake":
        blockers.append("report_type must be mail_evidence_chatgpt_result_intake")
    if report.get("generated_at") != NOW:
        blockers.append("generated_at must match the fixed intake timestamp")
    metrics = _dict_or_empty(report.get("metrics"))
    safe_outputs = _dict_or_empty(report.get("safe_outputs"))
    claim_boundary = _dict_or_empty(report.get("claim_boundary"))
    _validate_exact_keys(metrics, set(REQUIRED_TRUE_METRICS), "metrics", blockers)
    for metric in REQUIRED_TRUE_METRICS:
        if metrics.get(metric) is not True:
            blockers.append("required mail evidence ChatGPT result metric is not true: " + metric)
    _validate_safe_outputs(safe_outputs, blockers)
    _validate_report_claim_boundary(claim_boundary, blockers)
    if "validation" in report:
        _validate_embedded_validation(report["validation"], blockers)
    _reject_private_payload_fields(report, blockers)
    _reject_concrete_identifier_fields(report, blockers)
    try:
        validate_public_gateway_payload(report)
        assert_no_public_raw_references(
            report,
            "mail_evidence_chatgpt_result_intake_report",
        )
    except Exception:
        blockers.append("public report leaks raw paths, credentials, SQL, or backend internals")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_mail_evidence_chatgpt_result_intake_validation_claim": (not blockers),
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_production_ready_claim": False,
        },
    }


def _run_negative_packet_probes(packet: dict[str, Any]) -> list[dict[str, Any]]:
    probes: list[tuple[str, dict[str, Any]]] = []

    environment_probe = _clone(packet)
    environment_probe["environment_values"] = {"FORMOWL_DATA_DIR": "private"}
    probes.append(("environment_values_present", environment_probe))

    fixture_id_probe = _clone(packet)
    fixture_id_probe["smoke_contract"]["mail_evidence_bundle_id"] = "mailbundle_raw"
    probes.append(("raw_fixture_identifier_present", fixture_id_probe))

    selector_probe = _clone(packet)
    selector_probe["query_mail_evidence_result"]["owner_selector_kind"] = (
        "mail_import_session_id_raw"
    )
    probes.append(("unsupported_selector_kind_present", selector_probe))

    mail_payload_probe = _clone(packet)
    mail_payload_probe["query_mail_evidence_result"]["mail_body"] = (
        "Blocker: Waiting on audit approval"
    )
    probes.append(("mail_payload_text_present", mail_payload_probe))

    raw_query_probe = _clone(packet)
    raw_query_probe["query_mail_evidence_result"]["query_text"] = "What is the latest blocker?"
    probes.append(("raw_query_or_case_text_present", raw_query_probe))

    transcript_probe = _clone(packet)
    transcript_probe["raw_chatgpt_transcript"] = [
        {"role": "assistant", "content": "private tool output"}
    ]
    probes.append(("raw_chatgpt_transcript_present", transcript_probe))

    pending_probe = _clone(packet)
    pending_probe["query_mail_evidence_result"]["owner_status"] = "pending_review"
    pending_probe["query_mail_evidence_result"]["pending_handler_warning_count"] = 1
    probes.append(("pending_handler_fallback_present", pending_probe))

    tampered_probe = _clone(packet)
    tampered_probe["smoke_contract"]["required_tool_names_hash"] = "sha256:" + "f" * 64
    probes.append(("tampered_smoke_contract_hash", tampered_probe))

    duplicate_hash_probe = _clone(packet)
    duplicate_hash = duplicate_hash_probe["observed_session"]["sequence"][0]["response_shape_hash"]
    duplicate_hash_probe["observed_session"]["sequence"][5]["response_shape_hash"] = duplicate_hash
    duplicate_hash_probe["answer_mail_case_progress_result"]["denied_response_shape_hash"] = (
        duplicate_hash
    )
    probes.append(("duplicate_response_hash", duplicate_hash_probe))

    raw_command_probe = _clone(packet)
    raw_command_probe["mcp_server_command_label"] = "C:\\private\\formowl.exe"
    probes.append(("raw_command_path_present", raw_command_probe))

    sql_probe = _clone(packet)
    sql_probe["sql"] = "select * from private_mail"
    probes.append(("raw_sql_present", sql_probe))

    parser_probe = _clone(packet)
    parser_probe["parser_debug"] = "worker scratch parser detail"
    probes.append(("parser_internal_present", parser_probe))

    upload_locator_probe = _clone(packet)
    upload_locator_probe["upload_surface_locator"] = "formowl_upload_session:upload_private"
    probes.append(("upload_locator_present", upload_locator_probe))

    actual_upload_probe = _clone(packet)
    actual_upload_probe["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"] = True
    actual_upload_probe["claim_boundary"]["supports_actual_file_transfer_claim"] = True
    probes.append(("actual_upload_or_file_transfer_overclaim", actual_upload_probe))

    production_probe = _clone(packet)
    production_probe["claim_boundary"]["supports_production_ready_claim"] = True
    probes.append(("production_ready_overclaim", production_probe))

    kg_probe = _clone(packet)
    kg_probe["claim_boundary"]["supports_kg_write_claim"] = True
    kg_probe["claim_boundary"]["supports_wiki_projection_claim"] = True
    probes.append(("kg_or_wiki_overclaim", kg_probe))

    permission_probe = _clone(packet)
    permission_probe["claim_boundary"]["supports_permission_bypass_claim"] = True
    probes.append(("permission_bypass_overclaim", permission_probe))

    unknown_probe = _clone(packet)
    unknown_probe["raw_debug_path"] = "C:\\private\\mail.pst"
    probes.append(("unknown_extra_key_present", unknown_probe))

    bool_count_probe = _clone(packet)
    bool_count_probe["query_mail_evidence_result"]["owner_evidence_snippet_count"] = True
    probes.append(("bool_count_present", bool_count_probe))

    wrong_sequence_probe = _clone(packet)
    wrong_sequence_probe["observed_session"]["sequence"][2]["step"] = (
        "tools/call:query_mail_evidence"
    )
    probes.append(("wrong_tool_sequence", wrong_sequence_probe))

    missing_case_probe = _clone(packet)
    del missing_case_probe["answer_mail_case_progress_result"]
    probes.append(("missing_case_progress_result", missing_case_probe))

    if [name for name, _probe in probes] != NEGATIVE_PACKET_PROBE_NAMES:
        raise RuntimeError("negative packet probe contract drifted")
    results = []
    for name, probe in probes:
        validation = validate_result_packet(probe)
        results.append(
            {
                "name": name,
                "validation": validation,
                "shape_hash": sha256_json(
                    {
                        "name": name,
                        "passed": validation["passed"],
                        "blocker_count": len(validation["blockers"]),
                    }
                ),
            }
        )
    return results


def _validate_smoke_contract(
    value: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = {
        "chatgpt_free_smoke_report_type",
        "fixture_profile",
        "fixture_smoke_report_hash",
        "asset_id_hash",
        "mail_evidence_bundle_id_hash",
        "mail_import_session_id_hash",
        "observation_count",
        "required_environment_name_count",
        "required_environment_names_hash",
        "required_tool_count",
        "required_tool_names_hash",
        "expected_sequence_step_count",
        "expected_sequence_hash",
        "expected_status_contract_hash",
    }
    _validate_exact_keys(value, expected_keys, "smoke_contract", blockers)
    if value.get("chatgpt_free_smoke_report_type") != CHATGPT_FREE_SMOKE_REPORT_TYPE:
        blockers.append("smoke_contract.chatgpt_free_smoke_report_type mismatch")
    if value.get("fixture_profile") != FIXTURE_PROFILE:
        blockers.append("smoke_contract.fixture_profile mismatch")
    for key in (
        "fixture_smoke_report_hash",
        "asset_id_hash",
        "mail_evidence_bundle_id_hash",
        "mail_import_session_id_hash",
    ):
        if not _is_sha256(value.get(key)):
            blockers.append(f"smoke_contract.{key} must be a sha256 hash")
    expected_contract = build_expected_smoke_contract()
    if expected_contract.get("checkpoint_o_smoke_validation_passed") is not True:
        blockers.append("checkpoint O smoke validation must pass before result intake")
    for key in (
        "fixture_smoke_report_hash",
        "asset_id_hash",
        "mail_evidence_bundle_id_hash",
        "mail_import_session_id_hash",
    ):
        if _is_sha256(value.get(key)) and value.get(key) != expected_contract[key]:
            blockers.append(f"smoke_contract.{key} does not match checkpoint O smoke")
    exact_counts = {
        "required_environment_name_count": len(REQUIRED_ENV_NAMES),
        "required_tool_count": len(REQUIRED_TOOL_NAMES),
        "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
    }
    for key, expected in exact_counts.items():
        item = value.get(key)
        if type(item) is not int or item != expected:
            blockers.append(f"smoke_contract.{key} must be {expected}")
    observation_count = value.get("observation_count")
    if type(observation_count) is not int or observation_count <= 0:
        blockers.append("smoke_contract.observation_count must be positive")
    elif observation_count != expected_contract["observation_count"]:
        blockers.append("smoke_contract.observation_count does not match checkpoint O smoke")
    exact_hashes = {
        "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
        "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
        "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
        "expected_status_contract_hash": sha256_json(EXPECTED_STATUS_CONTRACT),
    }
    for key, expected in exact_hashes.items():
        item = value.get(key)
        if not _is_sha256(item):
            blockers.append(f"smoke_contract.{key} must be a sha256 hash")
        elif item != expected:
            blockers.append(f"smoke_contract.{key} does not match contract hash")


def _validate_observed_session(
    value: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = {
        "chatgpt_client_label",
        "transport",
        "sequence",
        "observed_tool_count",
        "observed_required_tool_names",
        "observed_tool_names_hash",
    }
    _validate_exact_keys(value, expected_keys, "observed_session", blockers)
    if value.get("chatgpt_client_label") != "chatgpt":
        blockers.append("observed_session.chatgpt_client_label mismatch")
    if value.get("transport") != "stdio_jsonrpc":
        blockers.append("observed_session.transport mismatch")
    tool_count = value.get("observed_tool_count")
    if type(tool_count) is not int or tool_count < len(REQUIRED_TOOL_NAMES):
        blockers.append("observed_session.observed_tool_count must cover required tools")
    if value.get("observed_required_tool_names") != REQUIRED_TOOL_NAMES:
        blockers.append("observed_session.observed_required_tool_names mismatch")
    tool_hash = value.get("observed_tool_names_hash")
    if not _is_sha256(tool_hash):
        blockers.append("observed_session.observed_tool_names_hash must be a hash")
    elif tool_hash != sha256_json(REQUIRED_TOOL_NAMES):
        blockers.append("observed_session.observed_tool_names_hash mismatch")
    sequence = value.get("sequence")
    if not isinstance(sequence, list) or len(sequence) != len(EXPECTED_SEQUENCE):
        blockers.append("observed_session.sequence must contain expected steps")
        return
    steps: list[str] = []
    response_hashes: list[str] = []
    for index, item in enumerate(sequence):
        if not isinstance(item, dict):
            blockers.append("observed_session.sequence item must be an object")
            return
        _validate_exact_keys(
            item,
            {"step", "status", "response_shape_hash"},
            f"observed_session.sequence[{index}]",
            blockers,
        )
        step = item.get("step")
        if isinstance(step, str):
            steps.append(step)
        if item.get("status") != "ok":
            blockers.append(f"observed_session.sequence[{index}].status must be ok")
        response_hash = item.get("response_shape_hash")
        if not _is_sha256(response_hash):
            blockers.append(f"observed_session.sequence[{index}].response_shape_hash must hash")
        else:
            response_hashes.append(response_hash)
    if steps != EXPECTED_SEQUENCE:
        blockers.append("observed_session.sequence steps mismatch")
    if len(response_hashes) == len(EXPECTED_SEQUENCE) and len(set(response_hashes)) != len(
        response_hashes
    ):
        blockers.append("observed_session response hashes must be distinct")


def _validate_query_result(
    value: dict[str, Any],
    observed_session: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = {
        "called",
        "result_type",
        "owner_status",
        "denied_status",
        "owner_selector_kind",
        "denied_selector_kind",
        "owner_validation_passed",
        "denied_validation_passed",
        "owner_request_shape_hash",
        "denied_request_shape_hash",
        "owner_response_shape_hash",
        "denied_response_shape_hash",
        "owner_evidence_snippet_count",
        "owner_citation_count",
        "denied_evidence_snippet_count",
        "denied_citation_count",
        "denied_hidden_bundle_count",
        "denied_hidden_message_count",
        "pending_handler_warning_count",
    }
    _validate_exact_keys(value, expected_keys, "query_mail_evidence_result", blockers)
    if value.get("called") is not True:
        blockers.append("query_mail_evidence_result.called must be true")
    if value.get("result_type") != "mail_evidence_query":
        blockers.append("query_mail_evidence_result.result_type mismatch")
    if value.get("owner_status") != "ok":
        blockers.append("query_mail_evidence_result.owner_status must be ok")
    if value.get("denied_status") != "permission_denied":
        blockers.append("query_mail_evidence_result.denied_status must be permission_denied")
    for key in ("owner_selector_kind", "denied_selector_kind"):
        if value.get(key) != EXPECTED_SELECTOR_KIND:
            blockers.append(f"query_mail_evidence_result.{key} must be {EXPECTED_SELECTOR_KIND}")
    for key in ("owner_validation_passed", "denied_validation_passed"):
        if value.get(key) is not True:
            blockers.append(f"query_mail_evidence_result.{key} must be true")
    for key in (
        "owner_request_shape_hash",
        "denied_request_shape_hash",
        "owner_response_shape_hash",
        "denied_response_shape_hash",
    ):
        if not _is_sha256(value.get(key)):
            blockers.append(f"query_mail_evidence_result.{key} must be a sha256 hash")
    _validate_distinct_hashes(
        [
            value.get("owner_request_shape_hash"),
            value.get("denied_request_shape_hash"),
            value.get("owner_response_shape_hash"),
            value.get("denied_response_shape_hash"),
        ],
        "query_mail_evidence_result request/response hashes",
        blockers,
    )
    expected_request_hashes = _expected_request_shape_hashes()
    for key in ("owner_request_shape_hash", "denied_request_shape_hash"):
        if _is_sha256(value.get(key)) and value.get(key) != expected_request_hashes[key]:
            blockers.append(f"query_mail_evidence_result.{key} does not match expected shape")
    expected_response_hashes = _observed_sequence_response_hashes(observed_session)
    if len(expected_response_hashes) == len(EXPECTED_SEQUENCE):
        if value.get("owner_response_shape_hash") != expected_response_hashes[2]:
            blockers.append(
                "query_mail_evidence_result.owner_response_shape_hash sequence mismatch"
            )
        if value.get("denied_response_shape_hash") != expected_response_hashes[3]:
            blockers.append(
                "query_mail_evidence_result.denied_response_shape_hash sequence mismatch"
            )
    if not _is_positive_int(value.get("owner_evidence_snippet_count")):
        blockers.append("query_mail_evidence_result.owner_evidence_snippet_count must be positive")
    if not _is_positive_int(value.get("owner_citation_count")):
        blockers.append("query_mail_evidence_result.owner_citation_count must be positive")
    for key in ("denied_evidence_snippet_count", "denied_citation_count"):
        if not _is_zero_int(value.get(key)):
            blockers.append(f"query_mail_evidence_result.{key} must be zero")
    for key in ("denied_hidden_bundle_count", "denied_hidden_message_count"):
        if not _is_positive_int(value.get(key)):
            blockers.append(f"query_mail_evidence_result.{key} must be positive")
    if not _is_zero_int(value.get("pending_handler_warning_count")):
        blockers.append("query_mail_evidence_result.pending_handler_warning_count must be zero")


def _validate_case_progress_result(
    value: dict[str, Any],
    observed_session: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = {
        "called",
        "result_type",
        "owner_status",
        "denied_status",
        "owner_selector_kind",
        "denied_selector_kind",
        "owner_validation_passed",
        "denied_validation_passed",
        "owner_request_shape_hash",
        "denied_request_shape_hash",
        "owner_response_shape_hash",
        "denied_response_shape_hash",
        "owner_latest_update_count",
        "owner_blocker_count",
        "owner_responsible_party_count",
        "owner_next_action_count",
        "owner_deadline_count",
        "owner_citation_count",
        "denied_latest_update_count",
        "denied_blocker_count",
        "denied_responsible_party_count",
        "denied_next_action_count",
        "denied_deadline_count",
        "denied_citation_count",
        "denied_hidden_bundle_count",
        "denied_hidden_message_count",
        "pending_handler_warning_count",
    }
    _validate_exact_keys(
        value,
        expected_keys,
        "answer_mail_case_progress_result",
        blockers,
    )
    if value.get("called") is not True:
        blockers.append("answer_mail_case_progress_result.called must be true")
    if value.get("result_type") != "mail_case_progress_answer":
        blockers.append("answer_mail_case_progress_result.result_type mismatch")
    if value.get("owner_status") != "ok":
        blockers.append("answer_mail_case_progress_result.owner_status must be ok")
    if value.get("denied_status") != "permission_denied":
        blockers.append("answer_mail_case_progress_result.denied_status must be permission_denied")
    for key in ("owner_selector_kind", "denied_selector_kind"):
        if value.get(key) != EXPECTED_SELECTOR_KIND:
            blockers.append(
                f"answer_mail_case_progress_result.{key} must be {EXPECTED_SELECTOR_KIND}"
            )
    for key in ("owner_validation_passed", "denied_validation_passed"):
        if value.get(key) is not True:
            blockers.append(f"answer_mail_case_progress_result.{key} must be true")
    for key in (
        "owner_request_shape_hash",
        "denied_request_shape_hash",
        "owner_response_shape_hash",
        "denied_response_shape_hash",
    ):
        if not _is_sha256(value.get(key)):
            blockers.append(f"answer_mail_case_progress_result.{key} must be a sha256 hash")
    _validate_distinct_hashes(
        [
            value.get("owner_request_shape_hash"),
            value.get("denied_request_shape_hash"),
            value.get("owner_response_shape_hash"),
            value.get("denied_response_shape_hash"),
        ],
        "answer_mail_case_progress_result request/response hashes",
        blockers,
    )
    expected_request_hashes = _expected_request_shape_hashes()
    request_hash_map = {
        "owner_request_shape_hash": "case_progress_owner_request_shape_hash",
        "denied_request_shape_hash": "case_progress_denied_request_shape_hash",
    }
    for key, expected_key in request_hash_map.items():
        if _is_sha256(value.get(key)) and value.get(key) != expected_request_hashes[expected_key]:
            blockers.append(f"answer_mail_case_progress_result.{key} does not match expected shape")
    expected_response_hashes = _observed_sequence_response_hashes(observed_session)
    if len(expected_response_hashes) == len(EXPECTED_SEQUENCE):
        if value.get("owner_response_shape_hash") != expected_response_hashes[4]:
            blockers.append(
                "answer_mail_case_progress_result.owner_response_shape_hash sequence mismatch"
            )
        if value.get("denied_response_shape_hash") != expected_response_hashes[5]:
            blockers.append(
                "answer_mail_case_progress_result.denied_response_shape_hash sequence mismatch"
            )
    owner_item_count = _case_owner_answer_item_count(value)
    if type(owner_item_count) is not int or owner_item_count <= 0:
        blockers.append("answer_mail_case_progress_result owner answer item count must be positive")
    if not _is_positive_int(value.get("owner_citation_count")):
        blockers.append("answer_mail_case_progress_result.owner_citation_count must be positive")
    for key in (
        "denied_latest_update_count",
        "denied_blocker_count",
        "denied_responsible_party_count",
        "denied_next_action_count",
        "denied_deadline_count",
        "denied_citation_count",
    ):
        if not _is_zero_int(value.get(key)):
            blockers.append(f"answer_mail_case_progress_result.{key} must be zero")
    for key in ("denied_hidden_bundle_count", "denied_hidden_message_count"):
        if not _is_positive_int(value.get(key)):
            blockers.append(f"answer_mail_case_progress_result.{key} must be positive")
    if not _is_zero_int(value.get("pending_handler_warning_count")):
        blockers.append(
            "answer_mail_case_progress_result.pending_handler_warning_count must be zero"
        )


def _validate_operator_attestation(
    value: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = {
        "chatgpt_mcp_session_used",
        "chatgpt_detail_payload_excluded",
        "raw_tool_payload_excluded",
        "raw_mail_text_excluded",
        "concrete_mail_identifiers_excluded",
        "environment_values_excluded",
        "upload_locators_excluded",
        "paths_sql_parser_storage_worker_internals_excluded",
        "denied_probe_redaction_observed",
        "actual_file_upload_not_claimed",
        "source_is_operator_supplied",
        "not_direct_codex_chatgpt_verification",
        "not_cryptographic_proof",
    }
    _validate_exact_keys(value, expected_keys, "operator_attestation", blockers)
    for key in expected_keys:
        if value.get(key) is not True:
            blockers.append(f"operator_attestation.{key} must be true")


def _validate_packet_claim_boundary(
    claim_boundary: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_claims = {
        **{key: True for key in TRUE_PACKET_CLAIMS},
        **{key: False for key in FORBIDDEN_TRUE_CLAIMS},
    }
    _validate_exact_keys(
        claim_boundary,
        set(expected_claims),
        "result_packet.claim_boundary",
        blockers,
    )
    for key, expected in expected_claims.items():
        if claim_boundary.get(key) is not expected:
            blockers.append(f"result_packet claim boundary mismatch: {key}")
    for claim in FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(claim) is not False:
            blockers.append("result_packet forbidden claim is not explicitly false: " + claim)


def _validate_safe_outputs(safe_outputs: dict[str, Any], blockers: list[str]) -> None:
    required_keys = {
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
    }
    _validate_exact_keys(safe_outputs, required_keys, "safe_outputs", blockers)
    if (
        safe_outputs.get("result_profile")
        != "operator_supplied_chatgpt_mcp_fixture_mail_evidence_result"
    ):
        blockers.append("safe_outputs.result_profile mismatch")
    exact_counts = {
        "required_environment_name_count": len(REQUIRED_ENV_NAMES),
        "required_tool_count": len(REQUIRED_TOOL_NAMES),
        "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
        "observed_sequence_step_count": len(EXPECTED_SEQUENCE),
        "negative_packet_probe_count": len(NEGATIVE_PACKET_PROBE_NAMES),
        "query_denied_evidence_snippet_count": 0,
        "query_denied_citation_count": 0,
        "case_progress_denied_answer_item_count": 0,
        "case_progress_denied_citation_count": 0,
    }
    for key, expected in exact_counts.items():
        item = safe_outputs.get(key)
        if type(item) is not int or item != expected:
            blockers.append(f"safe_outputs.{key} must be {expected}")
    positive_counts = (
        "observed_tool_count",
        "fixture_observation_count",
        "query_owner_evidence_snippet_count",
        "query_owner_citation_count",
        "query_denied_hidden_bundle_count",
        "query_denied_hidden_message_count",
        "case_progress_owner_answer_item_count",
        "case_progress_owner_citation_count",
        "case_progress_denied_hidden_bundle_count",
        "case_progress_denied_hidden_message_count",
    )
    for key in positive_counts:
        if not _is_positive_int(safe_outputs.get(key)):
            blockers.append(f"safe_outputs.{key} must be positive")
    exact_statuses = {
        "query_owner_status": "ok",
        "query_denied_status": "permission_denied",
        "case_progress_owner_status": "ok",
        "case_progress_denied_status": "permission_denied",
    }
    for key, expected in exact_statuses.items():
        if safe_outputs.get(key) != expected:
            blockers.append(f"safe_outputs.{key} must be {expected}")
    exact_hashes = {
        "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
        "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
        "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
        "observed_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
        "observed_required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
        "negative_packet_probe_names_hash": sha256_json(NEGATIVE_PACKET_PROBE_NAMES),
    }
    for key, expected in exact_hashes.items():
        item = safe_outputs.get(key)
        if not _is_sha256(item):
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
        elif item != expected:
            blockers.append(f"safe_outputs.{key} does not match contract hash")
    for key in (
        "packet_shape_hash",
        "smoke_contract_shape_hash",
        "fixture_smoke_report_hash",
        "fixture_asset_id_hash",
        "fixture_mail_evidence_bundle_id_hash",
        "fixture_mail_import_session_id_hash",
        "operator_attestation_shape_hash",
    ):
        if not _is_sha256(safe_outputs.get(key)):
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
    expected_contract = build_expected_smoke_contract()
    if expected_contract.get("checkpoint_o_smoke_validation_passed") is not True:
        blockers.append("checkpoint O smoke validation must pass before report validation")
    expected_fixture_values = {
        "fixture_smoke_report_hash": expected_contract["fixture_smoke_report_hash"],
        "fixture_asset_id_hash": expected_contract["asset_id_hash"],
        "fixture_mail_evidence_bundle_id_hash": expected_contract["mail_evidence_bundle_id_hash"],
        "fixture_mail_import_session_id_hash": expected_contract["mail_import_session_id_hash"],
        "fixture_observation_count": expected_contract["observation_count"],
    }
    for key, expected in expected_fixture_values.items():
        if safe_outputs.get(key) != expected:
            blockers.append(f"safe_outputs.{key} does not match checkpoint O smoke")
    _validate_hash_list(
        safe_outputs.get("tool_call_request_shape_hashes"),
        expected_count=4,
        context="safe_outputs.tool_call_request_shape_hashes",
        blockers=blockers,
    )
    expected_request_hashes = build_expected_request_shape_hashes()
    expected_request_hash_list = [
        expected_request_hashes["owner_request_shape_hash"],
        expected_request_hashes["denied_request_shape_hash"],
        expected_request_hashes["case_progress_owner_request_shape_hash"],
        expected_request_hashes["case_progress_denied_request_shape_hash"],
    ]
    if safe_outputs.get("tool_call_request_shape_hashes") != expected_request_hash_list:
        blockers.append(
            "safe_outputs.tool_call_request_shape_hashes does not match expected shapes"
        )
    _validate_hash_list(
        safe_outputs.get("chatgpt_response_shape_hashes"),
        expected_count=len(EXPECTED_SEQUENCE),
        context="safe_outputs.chatgpt_response_shape_hashes",
        blockers=blockers,
    )
    _validate_hash_list(
        safe_outputs.get("negative_packet_probe_shape_hashes"),
        expected_count=len(NEGATIVE_PACKET_PROBE_NAMES),
        context="safe_outputs.negative_packet_probe_shape_hashes",
        blockers=blockers,
    )


def _validate_report_claim_boundary(
    claim_boundary: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_claims = {
        **{key: True for key in TRUE_REPORT_CLAIMS},
        **{key: False for key in FORBIDDEN_TRUE_CLAIMS},
    }
    _validate_exact_keys(claim_boundary, set(expected_claims), "claim_boundary", blockers)
    for key, expected in expected_claims.items():
        if claim_boundary.get(key) is not expected:
            blockers.append(f"claim boundary mismatch: {key}")
    for claim in FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(claim) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {claim}")


def _validate_embedded_validation(value: Any, blockers: list[str]) -> None:
    if not isinstance(value, dict):
        blockers.append("validation must be an object")
        return
    _validate_exact_keys(
        value,
        {"passed", "blockers", "claim_boundary"},
        "validation",
        blockers,
    )
    if value.get("passed") is not True:
        blockers.append("validation.passed must be true")
    if value.get("blockers") != []:
        blockers.append("validation.blockers must be empty")
    claim_boundary = _dict_or_empty(value.get("claim_boundary"))
    _validate_exact_keys(
        claim_boundary,
        {
            "supports_mail_evidence_chatgpt_result_intake_validation_claim",
            "supports_actual_chatgpt_connected_upload_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    if (
        claim_boundary.get("supports_mail_evidence_chatgpt_result_intake_validation_claim")
        is not True
    ):
        blockers.append("validation result intake claim must be true")
    if claim_boundary.get("supports_actual_chatgpt_connected_upload_claim") is not False:
        blockers.append("validation actual ChatGPT upload claim must be false")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


def _report_claim_boundary(passed: bool, packet_valid: bool) -> dict[str, Any]:
    return {
        "supports_mail_evidence_chatgpt_result_intake_validation_claim": passed,
        "supports_operator_supplied_chatgpt_mail_evidence_smoke_packet_claim": (packet_valid),
        "supports_chatgpt_fixture_backed_mail_evidence_result_intake_claim": (packet_valid),
        "supports_chatgpt_fixture_backed_case_progress_result_intake_claim": (packet_valid),
        **{key: False for key in FORBIDDEN_TRUE_CLAIMS},
        "container_verification_required": True,
    }


def build_expected_smoke_contract() -> dict[str, Any]:
    """Return the current checkpoint O smoke contract this intake accepts."""

    return dict(_cached_checkpoint_o_smoke_contract())


@lru_cache(maxsize=1)
def _cached_checkpoint_o_smoke_contract() -> tuple[tuple[str, Any], ...]:
    from mail_evidence_mcp_smoke import run_mail_evidence_mcp_smoke

    work_dir = (
        Path(tempfile.gettempdir()) / "formowl-mail-evidence-chatgpt-intake-checkpoint-o-smoke"
    )
    try:
        report = run_mail_evidence_mcp_smoke(work_dir)
        safe_outputs = report["safe_outputs"]
        contract = {
            "checkpoint_o_smoke_validation_passed": report.get("validation", {}).get("passed")
            is True,
            "chatgpt_free_smoke_report_type": CHATGPT_FREE_SMOKE_REPORT_TYPE,
            "fixture_profile": FIXTURE_PROFILE,
            "fixture_smoke_report_hash": sha256_json(report),
            "asset_id_hash": safe_outputs["asset_id_hash"],
            "mail_evidence_bundle_id_hash": safe_outputs["mail_evidence_bundle_id_hash"],
            "mail_import_session_id_hash": safe_outputs["mail_import_session_id_hash"],
            "observation_count": safe_outputs["observation_count"],
            "required_environment_name_count": len(REQUIRED_ENV_NAMES),
            "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
            "required_tool_count": len(REQUIRED_TOOL_NAMES),
            "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
            "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
            "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
            "expected_status_contract_hash": sha256_json(EXPECTED_STATUS_CONTRACT),
        }
    except Exception:
        contract = {
            "checkpoint_o_smoke_validation_passed": False,
            "chatgpt_free_smoke_report_type": CHATGPT_FREE_SMOKE_REPORT_TYPE,
            "fixture_profile": FIXTURE_PROFILE,
            "fixture_smoke_report_hash": sha256_json("checkpoint_o_smoke_unavailable"),
            "asset_id_hash": sha256_json("checkpoint_o_asset_unavailable"),
            "mail_evidence_bundle_id_hash": sha256_json("checkpoint_o_bundle_unavailable"),
            "mail_import_session_id_hash": sha256_json("checkpoint_o_import_session_unavailable"),
            "observation_count": 0,
            "required_environment_name_count": len(REQUIRED_ENV_NAMES),
            "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
            "required_tool_count": len(REQUIRED_TOOL_NAMES),
            "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
            "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
            "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
            "expected_status_contract_hash": sha256_json(EXPECTED_STATUS_CONTRACT),
        }
    return tuple(sorted(contract.items()))


def build_expected_request_shape_hashes() -> dict[str, str]:
    return dict(_cached_expected_request_shape_hashes())


@lru_cache(maxsize=1)
def _cached_expected_request_shape_hashes() -> tuple[tuple[str, str], ...]:
    shapes = {
        "owner_request_shape_hash": {
            "tool_name": "query_mail_evidence",
            "selector_kind": EXPECTED_SELECTOR_KIND,
            "visibility_path": "owner",
            "argument_keys": ["query_text", "mail_import_session_id"],
        },
        "denied_request_shape_hash": {
            "tool_name": "query_mail_evidence",
            "selector_kind": EXPECTED_SELECTOR_KIND,
            "visibility_path": "denied",
            "argument_keys": ["query_text", "mail_import_session_id"],
        },
        "case_progress_owner_request_shape_hash": {
            "tool_name": "answer_mail_case_progress",
            "selector_kind": EXPECTED_SELECTOR_KIND,
            "visibility_path": "owner",
            "argument_keys": ["case_id", "mail_import_session_id"],
        },
        "case_progress_denied_request_shape_hash": {
            "tool_name": "answer_mail_case_progress",
            "selector_kind": EXPECTED_SELECTOR_KIND,
            "visibility_path": "denied",
            "argument_keys": ["case_id", "mail_import_session_id"],
        },
    }
    return tuple(sorted((key, sha256_json(value)) for key, value in shapes.items()))


def _expected_request_shape_hashes() -> dict[str, str]:
    return build_expected_request_shape_hashes()


def _smoke_contract_bound(value: dict[str, Any]) -> bool:
    expected_contract = build_expected_smoke_contract()
    return (
        expected_contract.get("checkpoint_o_smoke_validation_passed") is True
        and value.get("chatgpt_free_smoke_report_type") == CHATGPT_FREE_SMOKE_REPORT_TYPE
        and value.get("fixture_profile") == FIXTURE_PROFILE
        and value.get("fixture_smoke_report_hash") == expected_contract["fixture_smoke_report_hash"]
        and value.get("asset_id_hash") == expected_contract["asset_id_hash"]
        and value.get("mail_evidence_bundle_id_hash")
        == expected_contract["mail_evidence_bundle_id_hash"]
        and value.get("mail_import_session_id_hash")
        == expected_contract["mail_import_session_id_hash"]
        and value.get("observation_count") == expected_contract["observation_count"]
        and value.get("required_environment_name_count") == len(REQUIRED_ENV_NAMES)
        and value.get("required_environment_names_hash") == sha256_json(REQUIRED_ENV_NAMES)
        and value.get("required_tool_count") == len(REQUIRED_TOOL_NAMES)
        and value.get("required_tool_names_hash") == sha256_json(REQUIRED_TOOL_NAMES)
        and value.get("expected_sequence_step_count") == len(EXPECTED_SEQUENCE)
        and value.get("expected_sequence_hash") == sha256_json(EXPECTED_SEQUENCE)
        and value.get("expected_status_contract_hash") == sha256_json(EXPECTED_STATUS_CONTRACT)
        and _is_sha256(value.get("fixture_smoke_report_hash"))
        and _is_sha256(value.get("asset_id_hash"))
        and _is_sha256(value.get("mail_evidence_bundle_id_hash"))
        and _is_sha256(value.get("mail_import_session_id_hash"))
        and _is_positive_int(value.get("observation_count"))
    )


def _query_owner_passed(value: dict[str, Any]) -> bool:
    return (
        value.get("called") is True
        and value.get("result_type") == "mail_evidence_query"
        and value.get("owner_status") == "ok"
        and value.get("owner_validation_passed") is True
        and _is_positive_int(value.get("owner_evidence_snippet_count"))
        and _is_positive_int(value.get("owner_citation_count"))
        and _is_sha256(value.get("owner_request_shape_hash"))
        and _is_sha256(value.get("owner_response_shape_hash"))
    )


def _query_denied_redacted(value: dict[str, Any]) -> bool:
    return (
        value.get("called") is True
        and value.get("denied_status") == "permission_denied"
        and value.get("denied_validation_passed") is True
        and _is_zero_int(value.get("denied_evidence_snippet_count"))
        and _is_zero_int(value.get("denied_citation_count"))
        and _is_positive_int(value.get("denied_hidden_bundle_count"))
        and _is_positive_int(value.get("denied_hidden_message_count"))
        and _is_zero_int(value.get("pending_handler_warning_count"))
        and _is_sha256(value.get("denied_request_shape_hash"))
        and _is_sha256(value.get("denied_response_shape_hash"))
    )


def _case_owner_passed(value: dict[str, Any]) -> bool:
    owner_item_count = _case_owner_answer_item_count(value)
    return (
        value.get("called") is True
        and value.get("result_type") == "mail_case_progress_answer"
        and value.get("owner_status") == "ok"
        and value.get("owner_validation_passed") is True
        and type(owner_item_count) is int
        and owner_item_count > 0
        and _is_positive_int(value.get("owner_citation_count"))
        and _is_sha256(value.get("owner_request_shape_hash"))
        and _is_sha256(value.get("owner_response_shape_hash"))
    )


def _case_denied_redacted(value: dict[str, Any]) -> bool:
    return (
        value.get("called") is True
        and value.get("denied_status") == "permission_denied"
        and value.get("denied_validation_passed") is True
        and _case_denied_answer_item_count(value) == 0
        and _is_zero_int(value.get("denied_citation_count"))
        and _is_positive_int(value.get("denied_hidden_bundle_count"))
        and _is_positive_int(value.get("denied_hidden_message_count"))
        and _is_zero_int(value.get("pending_handler_warning_count"))
        and _is_sha256(value.get("denied_request_shape_hash"))
        and _is_sha256(value.get("denied_response_shape_hash"))
    )


def _operator_attestation_complete(value: dict[str, Any]) -> bool:
    required = {
        "chatgpt_mcp_session_used",
        "chatgpt_detail_payload_excluded",
        "raw_tool_payload_excluded",
        "raw_mail_text_excluded",
        "concrete_mail_identifiers_excluded",
        "environment_values_excluded",
        "upload_locators_excluded",
        "paths_sql_parser_storage_worker_internals_excluded",
        "denied_probe_redaction_observed",
        "actual_file_upload_not_claimed",
        "source_is_operator_supplied",
        "not_direct_codex_chatgpt_verification",
        "not_cryptographic_proof",
    }
    return set(value) == required and all(value.get(key) is True for key in required)


def _packet_claim_boundary_honest(claim_boundary: dict[str, Any]) -> bool:
    return (
        all(claim_boundary.get(key) is True for key in TRUE_PACKET_CLAIMS)
        and all(claim_boundary.get(key) is False for key in FORBIDDEN_TRUE_CLAIMS)
        and set(claim_boundary) == set(TRUE_PACKET_CLAIMS + FORBIDDEN_TRUE_CLAIMS)
    )


def _packet_omits_private_payloads(packet: dict[str, Any]) -> bool:
    blockers: list[str] = []
    _reject_private_payload_fields(packet, blockers)
    _reject_concrete_identifier_fields(packet, blockers)
    rendered = json.dumps(packet, sort_keys=True).lower()
    forbidden = (
        "formowl_data_dir",
        "formowl_mcp_session_id",
        "formowl_mcp_actor_user_id",
        "formowl_mcp_workspace_id",
        "formowl_mail_upload_expires_at",
        "formowl_upload_session:",
        "formowl://",
        "object://",
        "mailbundle_raw",
        "message-id",
        "thread_raw",
        "blocker: waiting on audit approval",
        "waiting on audit approval",
        "update: launch reviewed",
        "select * from",
        "traceback",
    )
    return not blockers and not any(item in rendered for item in forbidden)


def _observed_sequence_steps(value: dict[str, Any]) -> list[str]:
    sequence = value.get("sequence")
    if not isinstance(sequence, list):
        return []
    steps: list[str] = []
    for item in sequence:
        if isinstance(item, dict) and isinstance(item.get("step"), str):
            steps.append(item["step"])
    return steps


def _observed_sequence_response_hashes(value: dict[str, Any]) -> list[str]:
    sequence = value.get("sequence")
    if not isinstance(sequence, list):
        return []
    hashes: list[str] = []
    for item in sequence:
        if isinstance(item, dict) and _is_sha256(item.get("response_shape_hash")):
            hashes.append(item["response_shape_hash"])
    return hashes


def _tool_call_request_shape_hashes(
    query_result: dict[str, Any],
    case_result: dict[str, Any],
) -> list[str]:
    keys = (
        (query_result, "owner_request_shape_hash"),
        (query_result, "denied_request_shape_hash"),
        (case_result, "owner_request_shape_hash"),
        (case_result, "denied_request_shape_hash"),
    )
    return [value[key] for value, key in keys if _is_sha256(value.get(key))]


def _case_owner_answer_item_count(value: dict[str, Any]) -> int | None:
    keys = (
        "owner_latest_update_count",
        "owner_blocker_count",
        "owner_responsible_party_count",
        "owner_next_action_count",
        "owner_deadline_count",
    )
    counts = [value.get(key) for key in keys]
    if not all(type(item) is int for item in counts):
        return None
    return sum(counts)


def _case_denied_answer_item_count(value: dict[str, Any]) -> int | None:
    keys = (
        "denied_latest_update_count",
        "denied_blocker_count",
        "denied_responsible_party_count",
        "denied_next_action_count",
        "denied_deadline_count",
    )
    counts = [value.get(key) for key in keys]
    if not all(type(item) is int for item in counts):
        return None
    return sum(counts)


def _result_packet_shape_hash(packet: dict[str, Any]) -> str:
    observed_session = _dict_or_empty(packet.get("observed_session"))
    query_result = _dict_or_empty(packet.get("query_mail_evidence_result"))
    case_result = _dict_or_empty(packet.get("answer_mail_case_progress_result"))
    return sha256_json(
        {
            "packet_type": packet.get("packet_type"),
            "evidence_mode": packet.get("evidence_mode"),
            "server_label": packet.get("server_label"),
            "mcp_server_command_label": packet.get("mcp_server_command_label"),
            "smoke_contract": _smoke_contract_safe_shape(
                _dict_or_empty(packet.get("smoke_contract"))
            ),
            "observed_sequence_steps": _observed_sequence_steps(observed_session),
            "observed_tool_count": observed_session.get("observed_tool_count"),
            "observed_required_tool_names": observed_session.get("observed_required_tool_names"),
            "query_result": _result_block_safe_shape(query_result),
            "case_progress_result": _result_block_safe_shape(case_result),
            "operator_attestation": _dict_or_empty(packet.get("operator_attestation")),
            "claim_boundary": _dict_or_empty(packet.get("claim_boundary")),
        }
    )


def _smoke_contract_shape_hash(value: dict[str, Any]) -> str:
    return sha256_json(_smoke_contract_safe_shape(value))


def _smoke_contract_safe_shape(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "chatgpt_free_smoke_report_type": value.get("chatgpt_free_smoke_report_type"),
        "fixture_profile": value.get("fixture_profile"),
        "fixture_smoke_report_hash": _safe_hash_or_none(value.get("fixture_smoke_report_hash")),
        "asset_id_hash": _safe_hash_or_none(value.get("asset_id_hash")),
        "mail_evidence_bundle_id_hash": _safe_hash_or_none(
            value.get("mail_evidence_bundle_id_hash")
        ),
        "mail_import_session_id_hash": _safe_hash_or_none(value.get("mail_import_session_id_hash")),
        "observation_count": _safe_int_or_none(value.get("observation_count")),
        "required_environment_name_count": _safe_int_or_none(
            value.get("required_environment_name_count")
        ),
        "required_environment_names_hash": _safe_hash_or_none(
            value.get("required_environment_names_hash")
        ),
        "required_tool_count": _safe_int_or_none(value.get("required_tool_count")),
        "required_tool_names_hash": _safe_hash_or_none(value.get("required_tool_names_hash")),
        "expected_sequence_step_count": _safe_int_or_none(
            value.get("expected_sequence_step_count")
        ),
        "expected_sequence_hash": _safe_hash_or_none(value.get("expected_sequence_hash")),
        "expected_status_contract_hash": _safe_hash_or_none(
            value.get("expected_status_contract_hash")
        ),
    }


def _result_block_safe_shape(value: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if key.endswith("_hash"):
            safe[key] = _safe_hash_or_none(item)
        elif key.endswith("_count"):
            safe[key] = _safe_int_or_none(item)
        elif key in {
            "called",
            "result_type",
            "owner_status",
            "denied_status",
            "owner_selector_kind",
            "denied_selector_kind",
            "owner_validation_passed",
            "denied_validation_passed",
        }:
            safe[key] = item
    return safe


def _public_outputs_are_safe(report: dict[str, Any]) -> bool:
    forbidden = (
        str(ROOT).lower(),
        "formowl_data_dir",
        "formowl_mcp_session_id",
        "formowl_mcp_actor_user_id",
        "formowl_mcp_workspace_id",
        "formowl_mail_upload_expires_at",
        "formowl_upload_session:",
        "upload_surface_locator",
        "mail_body",
        "mail_snippet",
        "raw_chatgpt_transcript",
        "query_text",
        "case_text",
        "message-id",
        "mailbundle_raw",
        "blocker: waiting on audit approval",
        "waiting on audit approval",
        "update: launch reviewed",
        "select * from",
        "traceback",
        "worker_scratch",
        "parser_debug",
        "storage_backend_id",
        "object://",
        "formowl://object",
        "c:\\private",
        "/workspace",
    )
    return public_payload_is_safe(
        report,
        forbidden_fragments=forbidden,
        raw_reference_context="mail_evidence_chatgpt_result_intake_report",
    )


def _validate_distinct_hashes(
    values: Sequence[Any],
    context: str,
    blockers: list[str],
) -> None:
    hashes = [value for value in values if _is_sha256(value)]
    if len(hashes) == len(values) and len(set(hashes)) != len(hashes):
        blockers.append(f"{context} must be distinct")


def _reject_private_payload_fields(
    value: Any,
    blockers: list[str],
    path: str = "",
) -> None:
    forbidden_exact = {
        "transcript",
        "messages",
        "content",
        "text",
        "body",
        "snippet",
        "summary",
        "tool_response",
        "raw_json",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            parts = set(normalized.split("_"))
            is_safe_attestation = normalized.endswith("_excluded")
            is_safe_claim = normalized.startswith("supports_") and normalized.endswith("_claim")
            is_safe_count = normalized.endswith("_count")
            if not (is_safe_attestation or is_safe_claim or is_safe_count) and (
                forbidden_exact & parts or normalized in forbidden_exact
            ):
                item_path = f"{path}.{key_text}" if path else key_text
                blockers.append(
                    "public packet contains private payload field: " + sha256_json(item_path)
                )
            _reject_private_payload_fields(
                item,
                blockers,
                f"{path}.{key_text}" if path else key_text,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_private_payload_fields(item, blockers, f"{path}[{index}]")


def _reject_concrete_identifier_fields(
    value: Any,
    blockers: list[str],
    path: str = "",
) -> None:
    forbidden = {
        "asset_id",
        "observation_id",
        "mail_import_session_id",
        "mail_evidence_bundle_id",
        "message_id",
        "thread_id",
        "citation_id",
        "upload_session_id",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            if normalized in forbidden:
                item_path = f"{path}.{key_text}" if path else key_text
                blockers.append(
                    "public packet contains concrete identifier field: " + sha256_json(item_path)
                )
            _reject_concrete_identifier_fields(
                item,
                blockers,
                f"{path}.{key_text}" if path else key_text,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_concrete_identifier_fields(item, blockers, f"{path}[{index}]")


def _is_positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _is_zero_int(value: Any) -> bool:
    return type(value) is int and value == 0


def _safe_hash_or_none(value: Any) -> str | None:
    return value if _is_sha256(value) else None


def _safe_int_or_none(value: Any) -> int | None:
    return value if type(value) is int else None


def _safe_status_or_none(value: Any) -> str | None:
    if value in {"ok", "permission_denied", "not_found", "error", "pending_review"}:
        return value
    return None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clone(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def _failure_validation(message: str) -> dict[str, Any]:
    return {
        "passed": False,
        "blockers": [message],
        "claim_boundary": {
            "supports_mail_evidence_chatgpt_result_intake_validation_claim": False,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_production_ready_claim": False,
        },
    }


def _load_json_or_failure(
    path: Path,
    message: str,
) -> tuple[Any | None, dict[str, Any] | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception:
        return None, _failure_validation(message)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Bounded operator-supplied ChatGPT MCP mail evidence result packet.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path for the generated intake report or validation failure JSON.",
    )
    parser.add_argument(
        "--validate-report",
        type=Path,
        default=None,
        help="Validate an existing result-intake report instead of reading a packet.",
    )
    args = parser.parse_args(argv)

    if args.input is not None and args.validate_report is not None:
        _write_json(
            args.output,
            _failure_validation("--input and --validate-report are mutually exclusive"),
        )
        return 1

    if args.validate_report is not None:
        report, failure = _load_json_or_failure(
            args.validate_report,
            "report JSON could not be loaded",
        )
        if failure is not None:
            _write_json(args.output, failure)
            return 1
        validation = validate_report(report)
        _write_json(args.output, validation)
        return 0 if validation["passed"] else 1

    if args.input is None:
        parser.error("--input is required unless --validate-report is supplied")
    packet, failure = _load_json_or_failure(
        args.input,
        "result packet JSON could not be loaded",
    )
    if failure is not None:
        _write_json(args.output, failure)
        return 1
    report = build_mail_evidence_chatgpt_result_intake_report(packet)
    _write_json(args.output, report)
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
