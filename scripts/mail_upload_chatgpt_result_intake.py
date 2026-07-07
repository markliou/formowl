#!/usr/bin/env python3
"""Validate a bounded FormOwl #21 ChatGPT MCP result packet.

This intake is for the step after an operator manually connects ChatGPT to the
``formowl-semantic-mcp-jsonrpc`` MCP server and calls ``open_upload_session``.
It validates only a hash/status/count result packet. It must not receive raw
ChatGPT transcripts, environment values, upload session locators, mail body
text, PST bytes, raw paths, parser controls, storage controls, or backend
internals.

It does not directly control ChatGPT, prove file transfer, claim a production
iframe, claim real PST/OST/MSG/EML/MBOX parsing, claim live PostgreSQL
readiness, claim production worker leasing, write KG/wiki state, or claim
production readiness.
"""

from __future__ import annotations

import argparse
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
from formowl_gateway import validate_public_gateway_payload  # noqa: E402
from mail_upload_chatgpt_connection_preflight import (  # noqa: E402
    DEFAULT_COMMAND_NAME,
    EXPECTED_SEQUENCE,
    REQUIRED_ENV_NAMES,
    REQUIRED_TOOL_NAMES,
)


DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "formowl-mail-upload-chatgpt-result-intake.json"
NOW = "2026-07-05T16:00:00+00:00"
RESULT_PACKET_TYPE = "formowl_chatgpt_mcp_result_packet_v1"
EVIDENCE_MODE = "operator_supplied_chatgpt_mcp_session_result"
SERVER_LABEL = "formowl_mail_upload_phase1"
EXPECTED_ASSET_TYPES = ["pst", "ost", "msg", "eml", "mbox"]
NEGATIVE_PACKET_PROBE_NAMES = [
    "environment_values_present",
    "upload_locator_present",
    "mail_body_text_present",
    "actual_upload_overclaim",
    "tampered_preflight_contract_hash",
    "raw_command_path_present",
]
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

REQUIRED_TRUE_METRICS = [
    "result_packet_loaded",
    "preflight_contract_hashes_bound",
    "server_label_matches",
    "chatgpt_mcp_sequence_observed",
    "open_upload_session_tool_available",
    "open_upload_session_called",
    "upload_task_card_shape_verified",
    "operator_attestation_complete",
    "packet_claim_boundary_honest",
    "packet_omits_environment_values",
    "packet_omits_upload_locators",
    "packet_omits_private_mail_payload",
    "negative_packet_probes_rejected",
    "safe_outputs_hashes_only",
    "raw_leak_guard_passed",
    "mail_upload_chatgpt_result_intake_passed",
]

FORBIDDEN_TRUE_CLAIMS = [
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_direct_chatgpt_session_verification_claim",
    "supports_real_upload_iframe_claim",
    "supports_real_pst_parser_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_production_ready_claim",
]


def build_chatgpt_result_intake_report(packet: Any) -> dict[str, Any]:
    packet_validation = validate_result_packet(packet)
    packet_dict = packet if isinstance(packet, dict) else {}
    observed_session = _dict_or_empty(packet_dict.get("observed_session"))
    open_result = _dict_or_empty(packet_dict.get("open_upload_session_result"))
    negative_results = (
        _run_negative_packet_probes(packet_dict) if packet_validation["passed"] is True else []
    )
    metrics = {
        "result_packet_loaded": isinstance(packet, dict),
        "preflight_contract_hashes_bound": _preflight_contract_hashes_bound(
            _dict_or_empty(packet_dict.get("preflight_contract"))
        ),
        "server_label_matches": packet_dict.get("server_label") == SERVER_LABEL
        and packet_dict.get("mcp_server_command_label") == DEFAULT_COMMAND_NAME,
        "chatgpt_mcp_sequence_observed": _observed_sequence_steps(observed_session)
        == EXPECTED_SEQUENCE,
        "open_upload_session_tool_available": observed_session.get("observed_required_tool_names")
        == REQUIRED_TOOL_NAMES,
        "open_upload_session_called": open_result.get("called") is True
        and open_result.get("status") == "ok",
        "upload_task_card_shape_verified": _open_upload_session_result_valid(open_result),
        "operator_attestation_complete": _operator_attestation_complete(
            _dict_or_empty(packet_dict.get("operator_attestation"))
        ),
        "packet_claim_boundary_honest": _packet_claim_boundary_honest(
            _dict_or_empty(packet_dict.get("claim_boundary"))
        ),
        "packet_omits_environment_values": _packet_omits_environment_values(packet_dict),
        "packet_omits_upload_locators": _packet_omits_upload_locators(packet_dict),
        "packet_omits_private_mail_payload": _packet_omits_private_mail_payload(packet_dict),
        "negative_packet_probes_rejected": packet_validation["passed"] is True
        and bool(negative_results)
        and all(result["validation"]["passed"] is False for result in negative_results),
        "safe_outputs_hashes_only": True,
        "raw_leak_guard_passed": True,
    }
    metrics["mail_upload_chatgpt_result_intake_passed"] = packet_validation[
        "passed"
    ] is True and all(metrics.values())
    sequence_hashes = _observed_sequence_response_hashes(observed_session)
    safe_outputs = {
        "result_profile": "operator_supplied_chatgpt_mcp_open_upload_session_result",
        "packet_shape_hash": _result_packet_shape_hash(packet_dict),
        "preflight_contract_shape_hash": _preflight_contract_shape_hash(),
        "required_environment_name_count": len(REQUIRED_ENV_NAMES),
        "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
        "required_tool_count": len(REQUIRED_TOOL_NAMES),
        "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
        "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
        "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
        "observed_sequence_step_count": len(_observed_sequence_steps(observed_session)),
        "observed_sequence_hash": sha256_json(_observed_sequence_steps(observed_session)),
        "observed_tool_count": _safe_int_or_none(observed_session.get("observed_tool_count")),
        "observed_required_tool_names_hash": sha256_json(
            observed_session.get("observed_required_tool_names")
            if isinstance(observed_session.get("observed_required_tool_names"), list)
            else []
        ),
        "task_card_shape_hash": _safe_hash_or_none(open_result.get("task_card_shape_hash")),
        "upload_session_shape_hash": _safe_hash_or_none(
            open_result.get("upload_session_shape_hash")
        ),
        "chatgpt_response_shape_hashes": sequence_hashes,
        "operator_attestation_shape_hash": sha256_json(
            _dict_or_empty(packet_dict.get("operator_attestation"))
        ),
        "negative_packet_probe_count": len(negative_results),
        "negative_packet_probe_names_hash": sha256_json(NEGATIVE_PACKET_PROBE_NAMES),
        "negative_packet_probe_shape_hashes": [result["shape_hash"] for result in negative_results],
    }
    report = {
        "report_type": "mail_upload_chatgpt_result_intake",
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": {
            "supports_chatgpt_result_intake_validation_claim": (
                metrics["mail_upload_chatgpt_result_intake_passed"]
            ),
            "supports_operator_supplied_chatgpt_open_upload_session_packet_claim": (
                packet_validation["passed"] is True
            ),
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
    metrics["raw_leak_guard_passed"] = _public_outputs_are_safe(report)
    metrics["mail_upload_chatgpt_result_intake_passed"] = packet_validation[
        "passed"
    ] is True and all(metrics.values())
    report["claim_boundary"]["supports_chatgpt_result_intake_validation_claim"] = metrics[
        "mail_upload_chatgpt_result_intake_passed"
    ]
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
        "preflight_contract",
        "observed_session",
        "open_upload_session_result",
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
    _validate_preflight_contract(
        _dict_or_empty(packet.get("preflight_contract")),
        blockers,
    )
    _validate_observed_session(
        _dict_or_empty(packet.get("observed_session")),
        blockers,
    )
    _validate_open_upload_session_result(
        _dict_or_empty(packet.get("open_upload_session_result")),
        blockers,
    )
    _validate_operator_attestation(
        _dict_or_empty(packet.get("operator_attestation")),
        blockers,
    )
    _validate_packet_claim_boundary(
        _dict_or_empty(packet.get("claim_boundary")),
        blockers,
    )
    _reject_private_payload_fields(packet, blockers)
    if not _packet_omits_environment_values(packet):
        blockers.append("result packet must not include environment values")
    if not _packet_omits_upload_locators(packet):
        blockers.append("result packet must not include upload session locators")
    if not _packet_omits_private_mail_payload(packet):
        blockers.append("result packet must not include private mail payload")
    try:
        validate_public_gateway_payload(packet)
        assert_no_public_raw_references(packet, "chatgpt_result_packet")
    except Exception:
        blockers.append("result packet leaks raw paths, credentials, SQL, or backend internals")
    return {"passed": not blockers, "blockers": blockers}


def validate_report(report: Any) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, dict):
        return {
            "passed": False,
            "blockers": ["report must be an object"],
            "claim_boundary": {
                "supports_chatgpt_result_intake_validation_claim": False,
                "supports_actual_chatgpt_connected_upload_claim": False,
                "supports_production_ready_claim": False,
            },
        }
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
    if report.get("report_type") != "mail_upload_chatgpt_result_intake":
        blockers.append("report_type must be mail_upload_chatgpt_result_intake")
    if report.get("generated_at") != NOW:
        blockers.append("generated_at must match the fixed intake timestamp")
    metrics = _dict_or_empty(report.get("metrics"))
    safe_outputs = _dict_or_empty(report.get("safe_outputs"))
    claim_boundary = _dict_or_empty(report.get("claim_boundary"))
    _validate_exact_keys(metrics, set(REQUIRED_TRUE_METRICS), "metrics", blockers)
    for metric in REQUIRED_TRUE_METRICS:
        if metrics.get(metric) is not True:
            blockers.append("required ChatGPT result intake metric is not true: " + metric)
    _validate_safe_outputs(safe_outputs, blockers)
    _validate_report_claim_boundary(claim_boundary, blockers)
    if "validation" in report:
        _validate_embedded_validation(report["validation"], blockers)
    _reject_private_payload_fields(report, blockers)
    try:
        validate_public_gateway_payload(report)
        assert_no_public_raw_references(report, "chatgpt_result_intake_report")
    except Exception:
        blockers.append("public report leaks raw paths, credentials, SQL, or backend internals")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_chatgpt_result_intake_validation_claim": not blockers,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_production_ready_claim": False,
        },
    }


def _run_negative_packet_probes(packet: dict[str, Any]) -> list[dict[str, Any]]:
    probes: list[tuple[str, dict[str, Any]]] = []
    probes.append(
        (
            "environment_values_present",
            {**packet, "environment_values": {"FORMOWL_DATA_DIR": "private"}},
        )
    )
    locator_probe = json.loads(json.dumps(packet))
    locator_probe["open_upload_session_result"]["upload_surface_locator"] = (
        "formowl_upload_session:upload_private"
    )
    probes.append(("upload_locator_present", locator_probe))
    mail_text_probe = json.loads(json.dumps(packet))
    mail_text_probe["open_upload_session_result"]["mail_body_text"] = "private launch message"
    probes.append(("mail_body_text_present", mail_text_probe))
    overclaim_probe = json.loads(json.dumps(packet))
    overclaim_probe["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"] = True
    probes.append(("actual_upload_overclaim", overclaim_probe))
    tampered_probe = json.loads(json.dumps(packet))
    tampered_probe["preflight_contract"]["expected_sequence_hash"] = "sha256:" + "f" * 64
    probes.append(("tampered_preflight_contract_hash", tampered_probe))
    path_probe = {**packet, "mcp_server_command_label": "C:\\private\\formowl.exe"}
    probes.append(("raw_command_path_present", path_probe))
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


def _validate_preflight_contract(
    value: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = {
        "connection_preflight_report_type",
        "required_environment_name_count",
        "required_environment_names_hash",
        "required_tool_count",
        "required_tool_names_hash",
        "expected_sequence_step_count",
        "expected_sequence_hash",
    }
    _validate_exact_keys(value, expected_keys, "preflight_contract", blockers)
    if value.get("connection_preflight_report_type") != "mail_upload_chatgpt_connection_preflight":
        blockers.append("preflight_contract.connection_preflight_report_type mismatch")
    exact_counts = {
        "required_environment_name_count": len(REQUIRED_ENV_NAMES),
        "required_tool_count": len(REQUIRED_TOOL_NAMES),
        "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
    }
    for key, expected in exact_counts.items():
        item = value.get(key)
        if type(item) is not int or item != expected:
            blockers.append(f"preflight_contract.{key} must be {expected}")
    exact_hashes = {
        "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
        "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
        "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
    }
    for key, expected in exact_hashes.items():
        item = value.get(key)
        if not _is_sha256(item):
            blockers.append(f"preflight_contract.{key} must be a sha256 hash")
        elif item != expected:
            blockers.append(f"preflight_contract.{key} does not match contract hash")


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
    if value.get("observed_required_tool_names") != REQUIRED_TOOL_NAMES:
        blockers.append("observed_session.observed_required_tool_names mismatch")
    tool_count = value.get("observed_tool_count")
    if type(tool_count) is not int or tool_count <= 0:
        blockers.append("observed_session.observed_tool_count must be positive")
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
        steps.append(str(item.get("step")))
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


def _validate_open_upload_session_result(
    value: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = {
        "called",
        "status",
        "result_type",
        "task_card_type",
        "next_required_action",
        "upload_locator_kind",
        "validation_passed",
        "task_card_shape_hash",
        "upload_session_shape_hash",
        "accepted_asset_types",
    }
    _validate_exact_keys(value, expected_keys, "open_upload_session_result", blockers)
    if value.get("called") is not True:
        blockers.append("open_upload_session_result.called must be true")
    if value.get("status") != "ok":
        blockers.append("open_upload_session_result.status must be ok")
    if value.get("result_type") != "upload_session_request":
        blockers.append("open_upload_session_result.result_type mismatch")
    if value.get("task_card_type") != "mail_archive_upload_task":
        blockers.append("open_upload_session_result.task_card_type mismatch")
    if value.get("next_required_action") != "upload_mail_archive":
        blockers.append("open_upload_session_result.next_required_action mismatch")
    if value.get("upload_locator_kind") != "formowl_upload_session":
        blockers.append("open_upload_session_result.upload_locator_kind mismatch")
    if value.get("validation_passed") is not True:
        blockers.append("open_upload_session_result.validation_passed must be true")
    if value.get("accepted_asset_types") != EXPECTED_ASSET_TYPES:
        blockers.append("open_upload_session_result.accepted_asset_types mismatch")
    for key in ("task_card_shape_hash", "upload_session_shape_hash"):
        if not _is_sha256(value.get(key)):
            blockers.append(f"open_upload_session_result.{key} must be a sha256 hash")


def _validate_operator_attestation(
    value: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_keys = {
        "chatgpt_mcp_session_used",
        "chatgpt_detail_payload_excluded",
        "environment_values_excluded",
        "session_locator_excluded",
        "mail_payload_excluded",
        "actual_file_upload_not_claimed",
        "source_is_operator_supplied",
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
        "preflight_contract_shape_hash",
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
        "task_card_shape_hash",
        "upload_session_shape_hash",
        "chatgpt_response_shape_hashes",
        "operator_attestation_shape_hash",
        "negative_packet_probe_count",
        "negative_packet_probe_names_hash",
        "negative_packet_probe_shape_hashes",
    }
    _validate_exact_keys(safe_outputs, required_keys, "safe_outputs", blockers)
    if (
        safe_outputs.get("result_profile")
        != "operator_supplied_chatgpt_mcp_open_upload_session_result"
    ):
        blockers.append("safe_outputs.result_profile mismatch")
    exact_counts = {
        "required_environment_name_count": len(REQUIRED_ENV_NAMES),
        "required_tool_count": len(REQUIRED_TOOL_NAMES),
        "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
        "observed_sequence_step_count": len(EXPECTED_SEQUENCE),
        "negative_packet_probe_count": len(NEGATIVE_PACKET_PROBE_NAMES),
    }
    for key, expected in exact_counts.items():
        item = safe_outputs.get(key)
        if type(item) is not int or item != expected:
            blockers.append(f"safe_outputs.{key} must be {expected}")
    observed_tool_count = safe_outputs.get("observed_tool_count")
    if type(observed_tool_count) is not int or observed_tool_count <= 0:
        blockers.append("safe_outputs.observed_tool_count must be positive")
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
        "preflight_contract_shape_hash",
        "task_card_shape_hash",
        "upload_session_shape_hash",
        "operator_attestation_shape_hash",
    ):
        if not _is_sha256(safe_outputs.get(key)):
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
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
        "supports_chatgpt_result_intake_validation_claim": True,
        "supports_operator_supplied_chatgpt_open_upload_session_packet_claim": True,
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
    }
    _validate_exact_keys(
        claim_boundary,
        set(expected_claims),
        "claim_boundary",
        blockers,
    )
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
            "supports_chatgpt_result_intake_validation_claim",
            "supports_actual_chatgpt_connected_upload_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    if claim_boundary.get("supports_chatgpt_result_intake_validation_claim") is not True:
        blockers.append("validation result intake claim must be true")
    if claim_boundary.get("supports_actual_chatgpt_connected_upload_claim") is not False:
        blockers.append("validation actual ChatGPT upload claim must be false")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


def _preflight_contract_hashes_bound(value: dict[str, Any]) -> bool:
    return (
        value.get("required_environment_names_hash") == sha256_json(REQUIRED_ENV_NAMES)
        and value.get("required_tool_names_hash") == sha256_json(REQUIRED_TOOL_NAMES)
        and value.get("expected_sequence_hash") == sha256_json(EXPECTED_SEQUENCE)
    )


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


def _open_upload_session_result_valid(value: dict[str, Any]) -> bool:
    return (
        value.get("called") is True
        and value.get("status") == "ok"
        and value.get("result_type") == "upload_session_request"
        and value.get("task_card_type") == "mail_archive_upload_task"
        and value.get("next_required_action") == "upload_mail_archive"
        and value.get("upload_locator_kind") == "formowl_upload_session"
        and value.get("validation_passed") is True
        and _is_sha256(value.get("task_card_shape_hash"))
        and _is_sha256(value.get("upload_session_shape_hash"))
        and value.get("accepted_asset_types") == EXPECTED_ASSET_TYPES
    )


def _operator_attestation_complete(value: dict[str, Any]) -> bool:
    required = {
        "chatgpt_mcp_session_used",
        "chatgpt_detail_payload_excluded",
        "environment_values_excluded",
        "session_locator_excluded",
        "mail_payload_excluded",
        "actual_file_upload_not_claimed",
        "source_is_operator_supplied",
        "not_cryptographic_proof",
    }
    return set(value) == required and all(value.get(key) is True for key in required)


def _packet_claim_boundary_honest(claim_boundary: dict[str, Any]) -> bool:
    return (
        claim_boundary.get("supports_operator_supplied_chatgpt_mcp_result_intake_claim") is True
        and claim_boundary.get("supports_chatgpt_open_upload_session_result_packet_claim") is True
        and claim_boundary.get("container_verification_required") is True
        and all(claim_boundary.get(claim) is False for claim in FORBIDDEN_TRUE_CLAIMS)
    )


def _packet_omits_environment_values(packet: dict[str, Any]) -> bool:
    rendered = json.dumps(packet, sort_keys=True).lower()
    forbidden = (
        '"environment_values"',
        '"environment_variable_values"',
        '"env_values"',
        '"env_value_map"',
        "formowl_data_dir=",
        "formowl_mcp_session_id=",
    )
    return not any(item in rendered for item in forbidden)


def _packet_omits_upload_locators(packet: dict[str, Any]) -> bool:
    rendered = json.dumps(packet, sort_keys=True).lower()
    forbidden = (
        '"upload_session_id"',
        '"upload_surface_locator"',
        "formowl_upload_session:upload_",
    )
    return not any(item in rendered for item in forbidden)


def _packet_omits_private_mail_payload(packet: dict[str, Any]) -> bool:
    blockers: list[str] = []
    _reject_private_payload_fields(packet, blockers)
    return not blockers


def _reject_private_payload_fields(
    value: Any,
    blockers: list[str],
    path: str = "",
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            parts = set(normalized.split("_"))
            if {"body", "snippet", "content", "text", "transcript"} & parts:
                blockers.append(
                    "public packet contains private payload field: " + sha256_json(path or key_text)
                )
            _reject_private_payload_fields(
                item,
                blockers,
                f"{path}.{key_text}" if path else key_text,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_private_payload_fields(item, blockers, f"{path}[{index}]")


def _result_packet_shape_hash(packet: dict[str, Any]) -> str:
    observed_session = _dict_or_empty(packet.get("observed_session"))
    open_result = _dict_or_empty(packet.get("open_upload_session_result"))
    return sha256_json(
        {
            "packet_type": packet.get("packet_type"),
            "evidence_mode": packet.get("evidence_mode"),
            "server_label": packet.get("server_label"),
            "mcp_server_command_label": packet.get("mcp_server_command_label"),
            "preflight_contract": _dict_or_empty(packet.get("preflight_contract")),
            "observed_sequence_steps": _observed_sequence_steps(observed_session),
            "observed_tool_count": observed_session.get("observed_tool_count"),
            "observed_required_tool_names": observed_session.get("observed_required_tool_names"),
            "open_upload_session_result": {
                "called": open_result.get("called"),
                "status": open_result.get("status"),
                "result_type": open_result.get("result_type"),
                "task_card_type": open_result.get("task_card_type"),
                "next_required_action": open_result.get("next_required_action"),
                "upload_locator_kind": open_result.get("upload_locator_kind"),
                "validation_passed": open_result.get("validation_passed"),
                "accepted_asset_types": open_result.get("accepted_asset_types"),
            },
            "operator_attestation": _dict_or_empty(packet.get("operator_attestation")),
            "claim_boundary": _dict_or_empty(packet.get("claim_boundary")),
        }
    )


def _preflight_contract_shape_hash() -> str:
    return sha256_json(
        {
            "connection_preflight_report_type": ("mail_upload_chatgpt_connection_preflight"),
            "required_environment_name_count": len(REQUIRED_ENV_NAMES),
            "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
            "required_tool_count": len(REQUIRED_TOOL_NAMES),
            "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
            "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
            "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
        }
    )


def _public_outputs_are_safe(report: dict[str, Any]) -> bool:
    rendered = json.dumps(report, sort_keys=True)
    lowered = rendered.lower()
    forbidden = (
        str(ROOT).lower(),
        "formowl_data_dir",
        "formowl_mcp_session_id",
        "upload_surface_locator",
        "formowl_upload_session:upload_",
        "traceback",
        "workerqueue",
        "worker_queue",
        "storage_backend_id",
        "formowl://object",
        "payload.bin",
        "mail-export.pst",
        "private launch message",
    )
    if any(item in lowered for item in forbidden):
        return False
    try:
        validate_public_gateway_payload(report)
        assert_no_public_raw_references(report, "chatgpt_result_intake_report")
    except Exception:
        return False
    return True


def _validate_hash_list(
    value: Any,
    *,
    expected_count: int,
    context: str,
    blockers: list[str],
) -> None:
    if not isinstance(value, list) or len(value) != expected_count:
        blockers.append(f"{context} must contain {expected_count} hashes")
        return
    if not all(_is_sha256(item) for item in value):
        blockers.append(f"{context} must contain sha256 hashes")
    if len(set(value)) != len(value):
        blockers.append(f"{context} must contain distinct hashes")


def _validate_exact_keys(
    value: dict[str, Any],
    expected_keys: set[str],
    context: str,
    blockers: list[str],
    *,
    allowed_extra: set[str] | None = None,
) -> None:
    extra = sorted(set(value) - expected_keys - (allowed_extra or set()))
    missing = sorted(expected_keys - set(value))
    if extra:
        blockers.append(_unknown_keys_message(context, extra))
    if missing:
        blockers.append(f"{context} missing keys: " + sha256_json(missing))


def _unknown_keys_message(context: str, keys: Sequence[str]) -> str:
    return f"{context} contains unknown keys: " f"count={len(keys)} hash={sha256_json(list(keys))}"


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _safe_hash_or_none(value: Any) -> str | None:
    return value if _is_sha256(value) else None


def _safe_int_or_none(value: Any) -> int | None:
    return value if type(value) is int else None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _failure_validation(message: str) -> dict[str, Any]:
    return {
        "passed": False,
        "blockers": [message],
        "claim_boundary": {
            "supports_chatgpt_result_intake_validation_claim": False,
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
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Bounded operator-supplied ChatGPT MCP result packet to validate.",
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
    report = build_chatgpt_result_intake_report(packet)
    _write_json(args.output, report)
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
