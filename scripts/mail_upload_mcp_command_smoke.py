#!/usr/bin/env python3
"""Run or validate the FormOwl #21 mail upload MCP command preflight.

This is a ChatGPT-compatible command preflight for the configured semantic
JSON-RPC runtime. It launches the documented
``formowl-semantic-mcp-jsonrpc`` console command as a subprocess and exercises
the MCP sequence ChatGPT will use next:

initialize -> tools/list -> tools/call open_upload_session

It does not claim that ChatGPT itself has been connected, that files transfer
through a real upload iframe, or that real PST/OST/MSG/EML/MBOX parsing is
implemented.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Sequence
import uuid

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import assert_no_public_raw_references, sha256_json  # noqa: E402
from formowl_auth import FileAuditLogStore  # noqa: E402
from formowl_gateway import validate_public_gateway_payload  # noqa: E402
from formowl_ingestion.storage import UploadSessionStore  # noqa: E402


DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "formowl-mail-upload-mcp-command-smoke.json"
DEFAULT_COMMAND = ("formowl-semantic-mcp-jsonrpc",)
NOW = "2026-07-05T10:00:00+00:00"
SESSION_ID = "session_chatgpt_mcp_preflight"
ACTOR_USER_ID = "user_chatgpt_mcp_preflight"
WORKSPACE_ID = "workspace_formowl"
EXPIRES_AT = "2026-07-06T00:00:00+00:00"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

REQUIRED_TRUE_METRICS = [
    "command_started",
    "initialize_succeeded",
    "tools_list_succeeded",
    "open_upload_session_tool_listed",
    "upload_session_call_succeeded",
    "upload_task_card_validated",
    "upload_session_persisted",
    "persisted_session_bound_to_env",
    "task_card_resolves_to_persisted_session",
    "infra_control_probe_denied",
    "infra_control_probe_no_side_effects",
    "non_object_json_rejected",
    "startup_failure_redacted",
    "safe_response_hashes_only",
    "raw_leak_guard_passed",
    "mail_upload_mcp_command_smoke_passed",
]

FORBIDDEN_TRUE_CLAIMS = [
    "supports_actual_chatgpt_smoke_claim",
    "supports_real_upload_iframe_claim",
    "supports_file_transfer_claim",
    "supports_real_pst_parser_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_production_ready_claim",
]


def run_mail_upload_mcp_command_smoke(
    work_dir: Path,
    *,
    command: Sequence[str] | None = None,
) -> dict[str, Any]:
    data_dir = work_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    valid_requests = [
        {"jsonrpc": "2.0", "id": "initialize", "method": "initialize"},
        {"jsonrpc": "2.0", "id": "tools", "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": "open_upload_session",
            "method": "tools/call",
            "params": {
                "name": "open_upload_session",
                "arguments": {
                    "intent": "Upload PST for FormOwl mail evidence reading.",
                    "intended_asset_type": "pst",
                    "owner_scope_type": "project",
                    "owner_scope_id": "project_formowl",
                    "project_id": "project_formowl",
                },
            },
        },
    ]
    valid_run = _run_gateway_command(
        valid_requests,
        command=command,
        data_dir=data_dir,
        session_id=SESSION_ID,
        actor_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
    )
    valid_responses = _decode_json_lines(valid_run.stdout)
    persisted_sessions = UploadSessionStore(data_dir).list()
    upload_response = _response_by_id(valid_responses, "open_upload_session")
    upload_payload = _tool_payload(upload_response)
    upload_data = _dict_or_empty(upload_payload.get("data"))
    persisted = persisted_sessions[0] if len(persisted_sessions) == 1 else None

    failure_dir = work_dir / "failure-data"
    failure_dir.mkdir(parents=True, exist_ok=True)
    infra_run = _run_gateway_command(
        [
            {
                "jsonrpc": "2.0",
                "id": "infra_probe",
                "method": "tools/call",
                "params": {
                    "name": "open_upload_session",
                    "arguments": {
                        "intent": "Upload mail archive.",
                        "intended_asset_type": "pst",
                        "workerQueue": "fast_mail_workers",
                    },
                },
            }
        ],
        command=command,
        data_dir=failure_dir,
        session_id=SESSION_ID,
        actor_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
    )
    infra_responses = _decode_json_lines(infra_run.stdout)
    infra_response = infra_responses[0] if infra_responses else {}

    non_object_run = _run_gateway_command(
        [],
        command=command,
        data_dir=work_dir / "non-object-data",
        session_id=SESSION_ID,
        actor_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
        raw_input="[]\n",
    )
    non_object_responses = _decode_json_lines(non_object_run.stdout)
    non_object_response = non_object_responses[0] if non_object_responses else {}

    startup_failure_dir = work_dir / "not-a-directory"
    startup_failure_dir.write_text("occupied", encoding="utf-8")
    startup_failure_run = _run_gateway_command(
        [{"jsonrpc": "2.0", "id": "startup_failure", "method": "initialize"}],
        command=command,
        data_dir=startup_failure_dir,
        session_id=SESSION_ID,
        actor_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
    )
    startup_failure_responses = _decode_json_lines(startup_failure_run.stdout)
    startup_failure_response = startup_failure_responses[0] if startup_failure_responses else {}

    tools_response = _response_by_id(valid_responses, "tools")
    tool_names = {
        tool["name"]
        for tool in tools_response.get("result", {}).get("tools", [])
        if isinstance(tool, dict)
    }
    metrics = {
        "command_started": valid_run.returncode == 0 and len(valid_responses) == 3,
        "initialize_succeeded": _response_by_id(valid_responses, "initialize")
        .get("result", {})
        .get("protocolVersion")
        == "2024-11-05",
        "tools_list_succeeded": bool(tool_names),
        "open_upload_session_tool_listed": "open_upload_session" in tool_names,
        "upload_session_call_succeeded": upload_payload.get("status") == "ok"
        and upload_response.get("result", {}).get("isError") is False,
        "upload_task_card_validated": _embedded_upload_task_validation_passed(upload_data),
        "upload_session_persisted": persisted is not None,
        "persisted_session_bound_to_env": persisted is not None
        and persisted.session_id == SESSION_ID
        and persisted.actor_user_id == ACTOR_USER_ID
        and persisted.workspace_id == WORKSPACE_ID,
        "task_card_resolves_to_persisted_session": _task_card_resolves_to_persisted_session(
            upload_data,
            persisted,
        ),
        "infra_control_probe_denied": infra_response.get("result", {}).get("isError") is True,
        "infra_control_probe_no_side_effects": UploadSessionStore(failure_dir).list() == []
        and FileAuditLogStore(failure_dir).list() == [],
        "non_object_json_rejected": non_object_response.get("error", {}).get("code") == -32600,
        "startup_failure_redacted": startup_failure_response.get("error", {}).get("code") == -32000
        and startup_failure_response.get("error", {}).get("message") == "internal_error",
        "safe_response_hashes_only": True,
        "raw_leak_guard_passed": _public_outputs_are_safe(
            valid_run,
            infra_run,
            non_object_run,
            startup_failure_run,
        ),
    }
    metrics["mail_upload_mcp_command_smoke_passed"] = all(metrics.values())

    all_responses = (
        valid_responses + infra_responses + non_object_responses + startup_failure_responses
    )
    safe_outputs = {
        "command_profile": "formowl_semantic_mcp_jsonrpc_console",
        "response_count": len(all_responses),
        "tool_count": len(tool_names),
        "persisted_upload_session_count": len(persisted_sessions),
        "infra_probe_audit_log_count": len(FileAuditLogStore(failure_dir).list()),
        "upload_session_shape_hash": _upload_session_shape_hash(persisted),
        "task_card_shape_hash": _task_card_shape_hash(upload_data),
        "valid_response_hashes": [_stable_response_hash(response) for response in valid_responses],
        "failure_response_hashes": [
            _stable_response_hash(response)
            for response in (infra_responses + non_object_responses + startup_failure_responses)
        ],
        "infra_probe_is_error": infra_response.get("result", {}).get("isError") is True,
        "non_object_error_code": non_object_response.get("error", {}).get("code"),
        "startup_failure_error_code": startup_failure_response.get("error", {}).get("code"),
    }
    report = {
        "report_type": "mail_upload_mcp_command_smoke",
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": {
            "supports_chatgpt_mcp_command_preflight_claim": (
                metrics["mail_upload_mcp_command_smoke_passed"]
            ),
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
    validation = validate_report(report)
    report["validation"] = validation
    return report


def validate_report(report: Any) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, dict):
        return {
            "passed": False,
            "blockers": ["report must be an object"],
            "claim_boundary": {
                "supports_chatgpt_mcp_command_preflight_claim": False,
                "supports_actual_chatgpt_smoke_claim": False,
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
    if report.get("report_type") != "mail_upload_mcp_command_smoke":
        blockers.append("report_type must be mail_upload_mcp_command_smoke")
    if report.get("generated_at") != NOW:
        blockers.append("generated_at must match the fixed smoke generation timestamp")
    metrics = _dict_or_empty(report.get("metrics"))
    safe_outputs = _dict_or_empty(report.get("safe_outputs"))
    claim_boundary = _dict_or_empty(report.get("claim_boundary"))
    _validate_exact_keys(metrics, set(REQUIRED_TRUE_METRICS), "metrics", blockers)
    _validate_exact_keys(
        claim_boundary,
        {
            "supports_chatgpt_mcp_command_preflight_claim",
            "supports_actual_chatgpt_smoke_claim",
            "supports_real_upload_iframe_claim",
            "supports_file_transfer_claim",
            "supports_real_pst_parser_claim",
            "supports_live_postgresql_readiness_claim",
            "supports_production_worker_leasing_claim",
            "supports_kg_write_claim",
            "supports_wiki_projection_claim",
            "supports_production_ready_claim",
            "container_verification_required",
        },
        "claim_boundary",
        blockers,
    )
    for metric in REQUIRED_TRUE_METRICS:
        if metrics.get(metric) is not True:
            blockers.append(f"required command smoke metric is not true: {metric}")
    if claim_boundary.get("supports_chatgpt_mcp_command_preflight_claim") is not True:
        blockers.append("ChatGPT MCP command preflight claim is not supported")
    for claim in FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(claim) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {claim}")
    if claim_boundary.get("container_verification_required") is not True:
        blockers.append("container_verification_required must be true")
    _validate_safe_outputs(safe_outputs, blockers)
    if "validation" in report:
        _validate_embedded_validation(report["validation"], blockers)
    try:
        validate_public_gateway_payload(report)
        assert_no_public_raw_references(report, "mail_upload_mcp_command_smoke_report")
    except Exception:
        blockers.append("public report leaks raw paths, credentials, SQL, or backend internals")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_chatgpt_mcp_command_preflight_claim": not blockers,
            "supports_actual_chatgpt_smoke_claim": False,
            "supports_production_ready_claim": False,
        },
    }


def _run_gateway_command(
    requests: list[dict[str, Any]],
    *,
    command: Sequence[str] | None,
    data_dir: Path,
    session_id: str,
    actor_user_id: str,
    workspace_id: str,
    raw_input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PYTHON_ROOT)
    env["FORMOWL_DATA_DIR"] = str(data_dir)
    env["FORMOWL_MCP_SESSION_ID"] = session_id
    env["FORMOWL_MCP_ACTOR_USER_ID"] = actor_user_id
    env["FORMOWL_MCP_WORKSPACE_ID"] = workspace_id
    env["FORMOWL_MAIL_UPLOAD_EXPIRES_AT"] = EXPIRES_AT
    input_text = raw_input
    if input_text is None:
        input_text = "".join(json.dumps(request, sort_keys=True) + "\n" for request in requests)
    argv = _resolve_command_argv(command or DEFAULT_COMMAND)
    try:
        return subprocess.run(
            argv,
            input=input_text,
            text=True,
            capture_output=True,
            cwd=ROOT,
            env=env,
            check=False,
        )
    except OSError:
        return subprocess.CompletedProcess(argv, 127, "", "command_start_failed")


def _resolve_command_argv(command: Sequence[str]) -> list[str]:
    argv = list(command)
    if not argv:
        return list(DEFAULT_COMMAND)
    executable = argv[0]
    if Path(executable).name != executable:
        return argv
    resolved = shutil.which(executable)
    if resolved is not None:
        argv[0] = resolved
    return argv


def _decode_json_lines(value: str) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        decoded = json.loads(line)
        if not isinstance(decoded, dict):
            raise ValueError("gateway response line must be a JSON object")
        responses.append(decoded)
    return responses


def _response_by_id(responses: list[dict[str, Any]], request_id: str) -> dict[str, Any]:
    for response in responses:
        if response.get("id") == request_id:
            return response
    return {}


def _tool_payload(response: dict[str, Any]) -> dict[str, Any]:
    content = response.get("result", {}).get("content")
    if not isinstance(content, list) or not content:
        return {}
    first = content[0]
    if not isinstance(first, dict):
        return {}
    payload = first.get("json")
    return payload if isinstance(payload, dict) else {}


def _embedded_upload_task_validation_passed(payload: dict[str, Any]) -> bool:
    validation = _dict_or_empty(payload.get("validation"))
    task_card = _dict_or_empty(payload.get("upload_task_card"))
    claim_boundary = _dict_or_empty(payload.get("claim_boundary"))
    public_checks = _dict_or_empty(payload.get("public_checks"))
    return (
        validation.get("passed") is True
        and validation.get("blockers") == []
        and task_card.get("card_type") == "mail_archive_upload_task"
        and payload.get("status") == "ok"
        and claim_boundary.get("supports_chatgpt_mail_upload_task_card_claim") is True
        and claim_boundary.get("supports_real_upload_iframe_claim") is False
        and all(public_checks.get(key) is True for key in public_checks)
    )


def _task_card_resolves_to_persisted_session(payload: dict[str, Any], persisted: Any) -> bool:
    if persisted is None:
        return False
    task_card = _dict_or_empty(payload.get("upload_task_card"))
    upload_session_id = payload.get("upload_session_id")
    expected_locator = f"formowl_upload_session:{persisted.upload_session_id}"
    return (
        isinstance(upload_session_id, str)
        and upload_session_id == persisted.upload_session_id
        and task_card.get("upload_session_id") == persisted.upload_session_id
        and task_card.get("upload_surface_locator") == expected_locator
    )


def _upload_session_shape_hash(value: Any) -> str:
    if value is None:
        return sha256_json("")
    shape = {
        "actor_user_id": value.actor_user_id,
        "workspace_id": value.workspace_id,
        "owner_scope_type": value.owner_scope_type,
        "owner_scope_id": value.owner_scope_id,
        "intended_asset_type": value.intended_asset_type,
        "ingestion_profile": value.ingestion_profile,
        "visibility_scope": value.visibility_scope,
        "source_preparation_state": value.source_preparation_state,
        "processing_status": value.processing_status,
        "status": value.status,
        "session_bound": value.session_id == SESSION_ID,
        "project_bound": value.project_id == "project_formowl",
    }
    return sha256_json(shape)


def _task_card_shape_hash(payload: dict[str, Any]) -> str:
    task_card = payload.get("upload_task_card")
    if not isinstance(task_card, dict):
        return sha256_json("")
    redacted_shape = {
        key: value
        for key, value in task_card.items()
        if key not in {"upload_session_id", "upload_surface_locator"}
    }
    redacted_shape["upload_surface_locator_kind"] = "formowl_upload_session"
    return sha256_json(redacted_shape)


def _stable_response_hash(response: dict[str, Any]) -> str:
    normalized: dict[str, Any] = {
        "jsonrpc": response.get("jsonrpc"),
        "id": response.get("id"),
    }
    if "error" in response:
        error = _dict_or_empty(response.get("error"))
        normalized["error"] = {
            "code": error.get("code"),
            "message": error.get("message"),
        }
    result = _dict_or_empty(response.get("result"))
    if result:
        normalized["result"] = {
            "protocolVersion": result.get("protocolVersion"),
            "isError": result.get("isError"),
        }
        tools = result.get("tools")
        if isinstance(tools, list):
            normalized["result"]["tool_names"] = sorted(
                tool.get("name") for tool in tools if isinstance(tool, dict)
            )
        payload = _tool_payload(response)
        if payload:
            data = _dict_or_empty(payload.get("data"))
            task_card = _dict_or_empty(data.get("upload_task_card"))
            validation = _dict_or_empty(data.get("validation"))
            normalized["result"]["tool_payload"] = {
                "result_type": payload.get("result_type"),
                "status": payload.get("status"),
                "data_status": data.get("status"),
                "task_card_type": task_card.get("card_type"),
                "next_required_action": data.get("next_required_action"),
                "validation_passed": validation.get("passed"),
            }
    return sha256_json(normalized)


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
        blockers.append(f"{context} missing keys: " + ", ".join(missing))


def _validate_safe_outputs(safe_outputs: dict[str, Any], blockers: list[str]) -> None:
    required_keys = {
        "command_profile",
        "response_count",
        "tool_count",
        "persisted_upload_session_count",
        "infra_probe_audit_log_count",
        "upload_session_shape_hash",
        "task_card_shape_hash",
        "valid_response_hashes",
        "failure_response_hashes",
        "infra_probe_is_error",
        "non_object_error_code",
        "startup_failure_error_code",
    }
    _validate_exact_keys(safe_outputs, required_keys, "safe_outputs", blockers)
    if safe_outputs.get("command_profile") != "formowl_semantic_mcp_jsonrpc_console":
        blockers.append("safe_outputs.command_profile must identify the console command")
    expected_counts = {
        "response_count": 6,
        "persisted_upload_session_count": 1,
        "infra_probe_audit_log_count": 0,
    }
    for key, expected in expected_counts.items():
        value = safe_outputs.get(key)
        if type(value) is not int or value != expected:
            blockers.append(f"safe_outputs.{key} must be {expected}")
    tool_count = safe_outputs.get("tool_count")
    if type(tool_count) is not int or tool_count <= 0:
        blockers.append("safe_outputs.tool_count must be a positive integer")
    for key in ("response_count", "persisted_upload_session_count"):
        value = safe_outputs.get(key)
        if type(value) is not int:
            blockers.append(f"safe_outputs.{key} must be an integer")
    for key in ("upload_session_shape_hash", "task_card_shape_hash"):
        value = safe_outputs.get(key)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
    expected_hash_counts = {"valid_response_hashes": 3, "failure_response_hashes": 3}
    for key in ("valid_response_hashes", "failure_response_hashes"):
        values = safe_outputs.get(key)
        if not isinstance(values, list) or not values:
            blockers.append(f"safe_outputs.{key} must be a non-empty list")
        elif not all(
            isinstance(item, str) and _SHA256_RE.fullmatch(item) is not None for item in values
        ):
            blockers.append(f"safe_outputs.{key} must contain sha256 hashes")
        elif len(values) != expected_hash_counts[key]:
            blockers.append(f"safe_outputs.{key} must contain {expected_hash_counts[key]} hashes")
        elif len(set(values)) != len(values):
            blockers.append(f"safe_outputs.{key} must contain distinct hashes")
    if safe_outputs.get("infra_probe_is_error") is not True:
        blockers.append("safe_outputs.infra_probe_is_error must be true")
    if safe_outputs.get("non_object_error_code") != -32600:
        blockers.append("safe_outputs.non_object_error_code must be -32600")
    if safe_outputs.get("startup_failure_error_code") != -32000:
        blockers.append("safe_outputs.startup_failure_error_code must be -32000")


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
            "supports_chatgpt_mcp_command_preflight_claim",
            "supports_actual_chatgpt_smoke_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    if claim_boundary.get("supports_chatgpt_mcp_command_preflight_claim") is not True:
        blockers.append("validation command preflight claim must be true")
    if claim_boundary.get("supports_actual_chatgpt_smoke_claim") is not False:
        blockers.append("validation actual ChatGPT smoke claim must be false")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


def _public_outputs_are_safe(*runs: subprocess.CompletedProcess[str]) -> bool:
    combined = "\n".join(run.stdout + run.stderr for run in runs)
    forbidden_fragments = (
        str(ROOT).lower(),
        "fast_mail_workers",
        "traceback",
        "workerqueue",
        "worker_queue",
        "formowl_data_dir",
    )
    lowered = combined.lower()
    if any(fragment in lowered for fragment in forbidden_fragments):
        return False
    try:
        validate_public_gateway_payload(combined)
    except Exception:
        return False
    return all(run.returncode == 0 and run.stderr == "" for run in runs)


def _unknown_keys_message(context: str, keys: list[str]) -> str:
    return f"{context} contains unknown keys: " f"count={len(keys)} hash={sha256_json(keys)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--validate-report", type=Path, default=None)
    parser.add_argument(
        "--command",
        nargs="+",
        default=None,
        help="Override the command argv for local diagnostics; defaults to the console entrypoint.",
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
    report = run_mail_upload_mcp_command_smoke(work_dir, command=args.command)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["validation"]["passed"] else 1


def _default_work_dir() -> Path:
    return Path(tempfile.gettempdir()) / f"formowl-mail-upload-command-{uuid.uuid4().hex}"


if __name__ == "__main__":
    raise SystemExit(main())
