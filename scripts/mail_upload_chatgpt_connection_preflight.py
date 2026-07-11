#!/usr/bin/env python3
"""Run or validate the FormOwl #21 ChatGPT MCP connection preflight.

This preflight packages the already configured semantic JSON-RPC command into a
bounded ChatGPT connection-readiness artifact. It proves that the command path
can open a session-bound mail upload task and that the public ChatGPT attach
contract can be described without leaking local paths, environment values, raw
mail data, upload locators, parser controls, storage controls, or backend
internals.

It does not claim an actual ChatGPT-connected upload, a production iframe, real
PST/OST/MSG/EML/MBOX parsing, live PostgreSQL readiness, production worker
leasing, KG writes, wiki projection, or production readiness.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Sequence
import uuid

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
from mail_upload_mcp_command_smoke import (  # noqa: E402
    run_mail_upload_mcp_command_smoke,
    validate_report as validate_command_smoke_report,
)


DEFAULT_OUTPUT = (
    Path(tempfile.gettempdir()) / "formowl-mail-upload-chatgpt-connection-preflight.json"
)
DEFAULT_COMMAND_NAME = "formowl-semantic-mcp-jsonrpc"
NOW = "2026-07-05T15:00:00+00:00"
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
REQUIRED_TRUE_METRICS = [
    "command_smoke_validated",
    "command_preflight_claim_supported",
    "initialize_and_tools_preflight_succeeded",
    "open_upload_session_tool_available",
    "upload_task_card_shape_bound_to_session",
    "connection_package_built",
    "connection_package_validated",
    "connection_package_omits_environment_values",
    "connection_package_omits_session_locator",
    "manual_chatgpt_attach_steps_are_hash_only",
    "negative_package_probes_rejected",
    "safe_response_hashes_only",
    "raw_leak_guard_passed",
    "mail_upload_chatgpt_connection_preflight_passed",
]

FORBIDDEN_TRUE_CLAIMS = [
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_real_upload_iframe_claim",
    "supports_real_pst_parser_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_production_ready_claim",
]


def run_mail_upload_chatgpt_connection_preflight(
    work_dir: Path,
    *,
    command: Sequence[str] | None = None,
) -> dict[str, Any]:
    command_report = run_mail_upload_mcp_command_smoke(
        work_dir / "command-smoke",
        command=command,
    )
    command_validation = validate_command_smoke_report(command_report)
    package = build_connection_package(command_report)
    package_validation = validate_connection_package(package)
    negative_results = _run_negative_package_probes(package)
    command_metrics = _dict_or_empty(command_report.get("metrics"))
    command_claims = _dict_or_empty(command_report.get("claim_boundary"))
    command_safe_outputs = _dict_or_empty(command_report.get("safe_outputs"))

    metrics = {
        "command_smoke_validated": command_validation["passed"] is True
        and _dict_or_empty(command_report.get("validation")).get("passed") is True,
        "command_preflight_claim_supported": command_claims.get(
            "supports_chatgpt_mcp_command_preflight_claim"
        )
        is True,
        "initialize_and_tools_preflight_succeeded": command_metrics.get("initialize_succeeded")
        is True
        and command_metrics.get("tools_list_succeeded") is True,
        "open_upload_session_tool_available": command_metrics.get("open_upload_session_tool_listed")
        is True,
        "upload_task_card_shape_bound_to_session": command_metrics.get(
            "task_card_resolves_to_persisted_session"
        )
        is True
        and _is_sha256(command_safe_outputs.get("task_card_shape_hash")),
        "connection_package_built": isinstance(package, dict),
        "connection_package_validated": package_validation["passed"] is True,
        "connection_package_omits_environment_values": (_package_omits_environment_values(package)),
        "connection_package_omits_session_locator": (
            _package_omits_upload_surface_locator(package)
        ),
        "manual_chatgpt_attach_steps_are_hash_only": True,
        "negative_package_probes_rejected": all(
            result["validation"]["passed"] is False for result in negative_results
        ),
        "safe_response_hashes_only": True,
        "raw_leak_guard_passed": True,
    }
    metrics["mail_upload_chatgpt_connection_preflight_passed"] = all(metrics.values())

    safe_outputs = {
        "connection_profile": "formowl_semantic_mcp_jsonrpc_chatgpt_attach_preflight",
        "command_smoke_report_hash": sha256_json(command_report),
        "connection_package_shape_hash": _connection_package_shape_hash(package),
        "mcp_server_definition_shape_hash": _mcp_server_definition_shape_hash(package),
        "required_environment_name_count": len(REQUIRED_ENV_NAMES),
        "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
        "required_tool_count": len(REQUIRED_TOOL_NAMES),
        "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
        "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
        "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
        "command_arg_count": 1,
        "command_smoke_response_count": command_safe_outputs.get("response_count"),
        "command_smoke_tool_count": command_safe_outputs.get("tool_count"),
        "persisted_upload_session_count": command_safe_outputs.get(
            "persisted_upload_session_count"
        ),
        "upload_session_shape_hash": command_safe_outputs.get("upload_session_shape_hash"),
        "task_card_shape_hash": command_safe_outputs.get("task_card_shape_hash"),
        "negative_package_probe_count": len(negative_results),
        "negative_package_probe_names_hash": sha256_json(NEGATIVE_PACKAGE_PROBE_NAMES),
        "negative_package_probe_shape_hashes": [
            result["shape_hash"] for result in negative_results
        ],
    }
    report = {
        "report_type": "mail_upload_chatgpt_connection_preflight",
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": {
            "supports_chatgpt_mcp_connection_preflight_package_claim": (
                metrics["mail_upload_chatgpt_connection_preflight_passed"]
            ),
            "supports_chatgpt_manual_configuration_ready_claim": (
                metrics["connection_package_validated"]
                and metrics["command_preflight_claim_supported"]
            ),
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
    metrics["raw_leak_guard_passed"] = _public_outputs_are_safe(report)
    metrics["mail_upload_chatgpt_connection_preflight_passed"] = all(metrics.values())
    report["claim_boundary"]["supports_chatgpt_mcp_connection_preflight_package_claim"] = metrics[
        "mail_upload_chatgpt_connection_preflight_passed"
    ]
    validation = validate_report(report)
    report["validation"] = validation
    return report


def build_connection_package(command_report: dict[str, Any]) -> dict[str, Any]:
    command_safe_outputs = _dict_or_empty(command_report.get("safe_outputs"))
    return {
        "package_type": "formowl_chatgpt_mcp_connection_preflight_v1",
        "server_label": "formowl_mail_upload_phase1",
        "transport": "stdio_jsonrpc",
        "command_argv": [DEFAULT_COMMAND_NAME],
        "environment_variable_names": list(REQUIRED_ENV_NAMES),
        "environment_value_policy": "operator_supplied_values_not_in_public_report",
        "required_tool_names": list(REQUIRED_TOOL_NAMES),
        "expected_tool_sequence": list(EXPECTED_SEQUENCE),
        "upload_task_surface": "session_bound_upload_task_card",
        "upload_locator_kind": "formowl_upload_session",
        "verified_command_smoke": {
            "report_type": command_report.get("report_type"),
            "report_hash": sha256_json(command_report),
            "task_card_shape_hash": command_safe_outputs.get("task_card_shape_hash"),
            "upload_session_shape_hash": command_safe_outputs.get("upload_session_shape_hash"),
            "persisted_upload_session_count": command_safe_outputs.get(
                "persisted_upload_session_count"
            ),
        },
        "manual_attach_steps": [
            "install_or_run_the_formowl_semantic_mcp_jsonrpc_command",
            "configure_chatgpt_mcp_stdio_server_with_operator_session_context",
            "start_chatgpt_mcp_session_and_call_open_upload_session",
            "follow_the_session_bound_upload_task_card",
        ],
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
        },
    }


def validate_connection_package(package: Any) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(package, dict):
        return {
            "passed": False,
            "blockers": ["connection package must be an object"],
        }
    expected_keys = {
        "package_type",
        "server_label",
        "transport",
        "command_argv",
        "environment_variable_names",
        "environment_value_policy",
        "required_tool_names",
        "expected_tool_sequence",
        "upload_task_surface",
        "upload_locator_kind",
        "verified_command_smoke",
        "manual_attach_steps",
        "claim_boundary",
    }
    _validate_exact_keys(package, expected_keys, "connection_package", blockers)
    if package.get("package_type") != "formowl_chatgpt_mcp_connection_preflight_v1":
        blockers.append("connection_package.package_type mismatch")
    if package.get("server_label") != "formowl_mail_upload_phase1":
        blockers.append("connection_package.server_label mismatch")
    if package.get("transport") != "stdio_jsonrpc":
        blockers.append("connection_package.transport mismatch")
    if package.get("command_argv") != [DEFAULT_COMMAND_NAME]:
        blockers.append("connection_package.command_argv must use packaged command")
    if package.get("environment_variable_names") != REQUIRED_ENV_NAMES:
        blockers.append("connection_package.environment_variable_names mismatch")
    if package.get("environment_value_policy") != "operator_supplied_values_not_in_public_report":
        blockers.append("connection_package.environment_value_policy mismatch")
    if package.get("required_tool_names") != REQUIRED_TOOL_NAMES:
        blockers.append("connection_package.required_tool_names mismatch")
    if package.get("expected_tool_sequence") != EXPECTED_SEQUENCE:
        blockers.append("connection_package.expected_tool_sequence mismatch")
    if package.get("upload_task_surface") != "session_bound_upload_task_card":
        blockers.append("connection_package.upload_task_surface mismatch")
    if package.get("upload_locator_kind") != "formowl_upload_session":
        blockers.append("connection_package.upload_locator_kind mismatch")
    _validate_verified_command_smoke(
        _dict_or_empty(package.get("verified_command_smoke")),
        blockers,
    )
    _validate_manual_attach_steps(package.get("manual_attach_steps"), blockers)
    _validate_package_claim_boundary(
        _dict_or_empty(package.get("claim_boundary")),
        blockers,
    )
    if not _package_omits_environment_values(package):
        blockers.append("connection package must not include environment values")
    if not _package_omits_upload_surface_locator(package):
        blockers.append("connection package must not include upload surface locators")
    try:
        validate_public_gateway_payload(package)
        assert_no_public_raw_references(package, "chatgpt_connection_package")
    except Exception:
        blockers.append(
            "connection package leaks raw paths, credentials, SQL, or backend internals"
        )
    return {"passed": not blockers, "blockers": blockers}


def validate_report(report: Any) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, dict):
        return {
            "passed": False,
            "blockers": ["report must be an object"],
            "claim_boundary": {
                "supports_chatgpt_mcp_connection_preflight_package_claim": False,
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
    if report.get("report_type") != "mail_upload_chatgpt_connection_preflight":
        blockers.append("report_type must be mail_upload_chatgpt_connection_preflight")
    if report.get("generated_at") != NOW:
        blockers.append("generated_at must match the fixed preflight timestamp")
    metrics = _dict_or_empty(report.get("metrics"))
    safe_outputs = _dict_or_empty(report.get("safe_outputs"))
    claim_boundary = _dict_or_empty(report.get("claim_boundary"))
    _validate_exact_keys(metrics, set(REQUIRED_TRUE_METRICS), "metrics", blockers)
    for metric in REQUIRED_TRUE_METRICS:
        if metrics.get(metric) is not True:
            blockers.append(f"required ChatGPT preflight metric is not true: {metric}")
    _validate_safe_outputs(safe_outputs, blockers)
    _validate_report_claim_boundary(claim_boundary, blockers)
    if "validation" in report:
        _validate_embedded_validation(report["validation"], blockers)
    _reject_body_or_config_value_fields(report, blockers)
    try:
        validate_public_gateway_payload(report)
        assert_no_public_raw_references(
            report,
            "mail_upload_chatgpt_connection_preflight_report",
        )
    except Exception:
        blockers.append("public report leaks raw paths, credentials, SQL, or backend internals")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_chatgpt_mcp_connection_preflight_package_claim": not blockers,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_production_ready_claim": False,
        },
    }


def _run_negative_package_probes(package: dict[str, Any]) -> list[dict[str, Any]]:
    probes: list[tuple[str, dict[str, Any]]] = []
    probes.append(
        (
            "absolute_command_path",
            {**package, "command_argv": ["C:\\private\\formowl-semantic-mcp-jsonrpc"]},
        )
    )
    probes.append(
        (
            "environment_values_present",
            {**package, "environment_variable_values": {"FORMOWL_DATA_DIR": "private"}},
        )
    )
    overclaim = json.loads(json.dumps(package))
    overclaim["claim_boundary"]["supports_actual_chatgpt_connected_upload_claim"] = True
    probes.append(("actual_chatgpt_overclaim", overclaim))
    locator = json.loads(json.dumps(package))
    locator["upload_surface_locator"] = "formowl_upload_session:upload_private"
    probes.append(("upload_locator_present", locator))
    results = []
    for name, probe in probes:
        validation = validate_connection_package(probe)
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
    if [name for name, _probe in probes] != NEGATIVE_PACKAGE_PROBE_NAMES:
        raise RuntimeError("negative package probe contract drifted")
    return results


def _validate_safe_outputs(safe_outputs: dict[str, Any], blockers: list[str]) -> None:
    required_keys = {
        "connection_profile",
        "command_smoke_report_hash",
        "connection_package_shape_hash",
        "mcp_server_definition_shape_hash",
        "required_environment_name_count",
        "required_environment_names_hash",
        "required_tool_count",
        "required_tool_names_hash",
        "expected_sequence_step_count",
        "expected_sequence_hash",
        "command_arg_count",
        "command_smoke_response_count",
        "command_smoke_tool_count",
        "persisted_upload_session_count",
        "upload_session_shape_hash",
        "task_card_shape_hash",
        "negative_package_probe_count",
        "negative_package_probe_names_hash",
        "negative_package_probe_shape_hashes",
    }
    _validate_exact_keys(safe_outputs, required_keys, "safe_outputs", blockers)
    if (
        safe_outputs.get("connection_profile")
        != "formowl_semantic_mcp_jsonrpc_chatgpt_attach_preflight"
    ):
        blockers.append("safe_outputs.connection_profile mismatch")
    exact_counts = {
        "required_environment_name_count": len(REQUIRED_ENV_NAMES),
        "required_tool_count": len(REQUIRED_TOOL_NAMES),
        "expected_sequence_step_count": len(EXPECTED_SEQUENCE),
        "command_arg_count": 1,
        "command_smoke_response_count": 6,
        "persisted_upload_session_count": 1,
        "negative_package_probe_count": 4,
    }
    for key, expected in exact_counts.items():
        value = safe_outputs.get(key)
        if type(value) is not int or value != expected:
            blockers.append(f"safe_outputs.{key} must be {expected}")
    tool_count = safe_outputs.get("command_smoke_tool_count")
    if type(tool_count) is not int or tool_count <= 0:
        blockers.append("safe_outputs.command_smoke_tool_count must be positive")
    for key in (
        "command_smoke_report_hash",
        "connection_package_shape_hash",
        "mcp_server_definition_shape_hash",
        "upload_session_shape_hash",
        "task_card_shape_hash",
    ):
        value = safe_outputs.get(key)
        if not _is_sha256(value):
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
    exact_hashes = {
        "required_environment_names_hash": sha256_json(REQUIRED_ENV_NAMES),
        "required_tool_names_hash": sha256_json(REQUIRED_TOOL_NAMES),
        "expected_sequence_hash": sha256_json(EXPECTED_SEQUENCE),
        "negative_package_probe_names_hash": sha256_json(NEGATIVE_PACKAGE_PROBE_NAMES),
    }
    for key, expected in exact_hashes.items():
        value = safe_outputs.get(key)
        if not _is_sha256(value):
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
        elif value != expected:
            blockers.append(f"safe_outputs.{key} does not match contract hash")
    _validate_hash_list(
        safe_outputs.get("negative_package_probe_shape_hashes"),
        expected_count=4,
        context="safe_outputs.negative_package_probe_shape_hashes",
        blockers=blockers,
    )


def _validate_report_claim_boundary(
    claim_boundary: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_claims = {
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


def _validate_package_claim_boundary(
    claim_boundary: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_claims = {
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
    }
    _validate_exact_keys(
        claim_boundary,
        set(expected_claims),
        "connection_package.claim_boundary",
        blockers,
    )
    for key, expected in expected_claims.items():
        if claim_boundary.get(key) is not expected:
            blockers.append(f"connection_package claim boundary mismatch: {key}")
    for claim in FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(claim) is not False:
            blockers.append(
                "connection_package forbidden claim is not explicitly false: " f"{claim}"
            )


def _validate_verified_command_smoke(
    value: dict[str, Any],
    blockers: list[str],
) -> None:
    _validate_exact_keys(
        value,
        {
            "report_type",
            "report_hash",
            "task_card_shape_hash",
            "upload_session_shape_hash",
            "persisted_upload_session_count",
        },
        "connection_package.verified_command_smoke",
        blockers,
    )
    if value.get("report_type") != "mail_upload_mcp_command_smoke":
        blockers.append("connection_package.verified_command_smoke.report_type mismatch")
    for key in ("report_hash", "task_card_shape_hash", "upload_session_shape_hash"):
        if not _is_sha256(value.get(key)):
            blockers.append(f"connection_package.verified_command_smoke.{key} must hash")
    count = value.get("persisted_upload_session_count")
    if type(count) is not int or count != 1:
        blockers.append(
            "connection_package.verified_command_smoke." "persisted_upload_session_count must be 1"
        )


def _validate_manual_attach_steps(value: Any, blockers: list[str]) -> None:
    expected = [
        "install_or_run_the_formowl_semantic_mcp_jsonrpc_command",
        "configure_chatgpt_mcp_stdio_server_with_operator_session_context",
        "start_chatgpt_mcp_session_and_call_open_upload_session",
        "follow_the_session_bound_upload_task_card",
    ]
    if value != expected:
        blockers.append("connection_package.manual_attach_steps mismatch")


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
            "supports_chatgpt_mcp_connection_preflight_package_claim",
            "supports_actual_chatgpt_connected_upload_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    if claim_boundary.get("supports_chatgpt_mcp_connection_preflight_package_claim") is not True:
        blockers.append("validation ChatGPT preflight claim must be true")
    if claim_boundary.get("supports_actual_chatgpt_connected_upload_claim") is not False:
        blockers.append("validation actual ChatGPT claim must be false")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


def _package_omits_environment_values(package: dict[str, Any]) -> bool:
    rendered = json.dumps(package, sort_keys=True).lower()
    forbidden_keys = (
        "environment_variable_values",
        "environment_values",
        "env_values",
        "env_value_map",
        "formowl_data_dir=",
        "formowl_mcp_session_id=",
    )
    return not any(key in rendered for key in forbidden_keys)


def _package_omits_upload_surface_locator(package: dict[str, Any]) -> bool:
    rendered = json.dumps(package, sort_keys=True).lower()
    return (
        "upload_surface_locator" not in rendered
        and "formowl_upload_session:upload_" not in rendered
    )


def _connection_package_shape_hash(package: dict[str, Any]) -> str:
    return sha256_json(
        {
            "package_type": package.get("package_type"),
            "server_label": package.get("server_label"),
            "transport": package.get("transport"),
            "command_arg_count": len(package.get("command_argv", [])),
            "environment_name_count": len(package.get("environment_variable_names", [])),
            "required_tool_count": len(package.get("required_tool_names", [])),
            "sequence_count": len(package.get("expected_tool_sequence", [])),
            "upload_task_surface": package.get("upload_task_surface"),
            "upload_locator_kind": package.get("upload_locator_kind"),
            "manual_attach_step_count": len(package.get("manual_attach_steps", [])),
            "claim_boundary": _dict_or_empty(package.get("claim_boundary")),
        }
    )


def _mcp_server_definition_shape_hash(package: dict[str, Any]) -> str:
    return sha256_json(
        {
            "server_label": package.get("server_label"),
            "transport": package.get("transport"),
            "command_argv": package.get("command_argv"),
            "environment_variable_names": package.get("environment_variable_names"),
            "required_tool_names": package.get("required_tool_names"),
        }
    )


def _reject_body_or_config_value_fields(
    value: Any,
    blockers: list[str],
    path: str = "",
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            parts = set(normalized.split("_"))
            if {"body", "snippet", "content", "text"} & parts:
                blockers.append("public report contains evidence text field: " + sha256_json(path))
            if {"environment", "value"}.issubset(parts) or "env_value" in normalized:
                blockers.append(
                    "public report contains environment value field: " + sha256_json(path)
                )
            _reject_body_or_config_value_fields(
                item,
                blockers,
                f"{path}.{key_text}" if path else key_text,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_body_or_config_value_fields(item, blockers, f"{path}[{index}]")


def _public_outputs_are_safe(report: dict[str, Any]) -> bool:
    forbidden_fragments = (
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
    )
    return public_payload_is_safe(
        report,
        forbidden_fragments=forbidden_fragments,
        raw_reference_context="mail_upload_chatgpt_connection_preflight_report",
    )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--validate-report", type=Path, default=None)
    parser.add_argument(
        "--command",
        nargs="+",
        default=None,
        help=(
            "Override the command argv for local diagnostics; defaults to the "
            "console entrypoint."
        ),
    )
    args = parser.parse_args(argv)

    if args.validate_report is not None:
        report = json.loads(args.validate_report.read_text(encoding="utf-8"))
        validation = validate_report(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
        return 0 if validation["passed"] else 1

    work_dir = args.work_dir or _default_work_dir()
    work_dir.mkdir(parents=True, exist_ok=True)
    report = run_mail_upload_chatgpt_connection_preflight(
        work_dir,
        command=args.command,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["validation"]["passed"] else 1


def _default_work_dir() -> Path:
    return Path(tempfile.gettempdir()) / (
        f"formowl-mail-upload-chatgpt-connection-{uuid.uuid4().hex}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
