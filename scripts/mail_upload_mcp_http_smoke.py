#!/usr/bin/env python3
"""Run or validate the FormOwl #21 MCP-command-to-HTTP upload smoke.

This local smoke connects the configured ChatGPT-facing semantic JSON-RPC
command path to the stdlib local HTTP upload-surface contract harness:

initialize -> tools/list -> tools/call open_upload_session
-> GET /mail/upload/<upload_session_id>
-> POST multipart mail_archive to the same session-bound surface

It proves only the local command-to-HTTP upload contract. It does not claim that
ChatGPT itself is connected, that a production iframe is ready, or that real
PST/OST/MSG/EML/MBOX parsing is implemented.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Sequence
import uuid

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_auth import FileAuditLogStore  # noqa: E402
from formowl_contract import assert_no_public_raw_references, sha256_json  # noqa: E402
from formowl_evaluator.http_smoke import (  # noqa: E402
    RunningMailUploadHttpSurface as _RunningHttpSurface,
    asset_shape_hash as _asset_shape_hash,
    build_mail_upload_http_config,
    build_multipart_mail_archive,
    decode_json_lines as _decode_json_lines,
    decode_json_object as _decode_json_object,
    dict_or_empty as _dict_or_empty,
    jsonrpc_response_hash as _jsonrpc_response_hash,
    open_upload_session_via_command,
    response_by_id as _response_by_id,
    run_gateway_command,
    tool_payload as _tool_payload,
    upload_session_shape_hash,
    validate_claim_boundary as validate_common_claim_boundary,
    validate_embedded_validation as validate_common_embedded_validation,
    validate_exact_keys as _validate_exact_keys,
    validate_hash_list as _validate_hash_list,
)
from formowl_gateway import validate_public_gateway_payload  # noqa: E402
from formowl_ingestion.storage import (  # noqa: E402
    AssetStore,
    FileObjectStore,
    StorageBackendRegistry,
    UploadSessionStore,
)
from formowl_mail import (  # noqa: E402
    validate_mail_upload_http_post_result,
)

DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "formowl-mail-upload-mcp-http-smoke.json"
DEFAULT_COMMAND = ("formowl-semantic-mcp-jsonrpc",)
NOW = "2026-07-05T13:00:00+00:00"
SESSION_ID = "session_chatgpt_mcp_http_smoke"
ACTOR_USER_ID = "user_chatgpt_mcp_http_smoke"
WORKSPACE_ID = "workspace_formowl"
PROJECT_ID = "project_formowl"
EXPIRES_AT = "2026-07-06T00:00:00+00:00"
STORAGE_BACKEND_ID = "storage_mail_upload_mcp_http_smoke"
UPLOAD_BYTES = b"synthetic pst carrier bytes for local http upload smoke\n"
UPLOAD_FILENAME = "mail-export.pst"
UPLOAD_CONTENT_TYPE = "application/vnd.ms-outlook"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

REQUIRED_TRUE_METRICS = [
    "command_started",
    "initialize_succeeded",
    "tools_list_succeeded",
    "open_upload_session_tool_listed",
    "upload_session_call_succeeded",
    "upload_session_persisted",
    "persisted_session_bound_to_env",
    "task_card_resolves_to_persisted_session",
    "http_get_surface_available",
    "http_post_upload_succeeded",
    "http_post_result_validated",
    "upload_session_asset_bound",
    "asset_registered",
    "stored_payload_verified",
    "audit_events_recorded",
    "staging_cleaned",
    "negative_probes_rejected_without_side_effects",
    "command_startup_failure_redacted",
    "safe_response_hashes_only",
    "raw_leak_guard_passed",
    "mail_upload_mcp_http_smoke_passed",
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

EXPECTED_NEGATIVE_STATUS_CODES = [404, 400, 400, 400, 400, 400, 413]


@dataclass(frozen=True)
class _NegativeProbeResult:
    name: str
    status_code: int
    response_payload: dict[str, Any]
    passed: bool


def run_mail_upload_mcp_http_smoke(
    work_dir: Path,
    *,
    command: Sequence[str] | None = None,
) -> dict[str, Any]:
    data_dir = work_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    opened = _open_upload_session_via_command(data_dir, command=command)
    stores = _upload_surface_stores(data_dir, work_dir / "object-root")
    upload_session_id = opened.upload_session_id or "missing_upload_session"
    config = _http_config(work_dir, stores)
    body, content_type = _multipart_body(
        {
            "upload_session_id": upload_session_id,
            "workspace_id": WORKSPACE_ID,
        },
        filename=UPLOAD_FILENAME,
        content=UPLOAD_BYTES,
    )

    with _RunningHttpSurface(config) as surface:
        get_response, get_body = surface.request(
            "GET",
            f"/mail/upload/{upload_session_id}",
        )
        post_response, post_body = surface.request(
            "POST",
            f"/mail/upload/{upload_session_id}",
            body=body,
            headers={"Content-Type": content_type, "Content-Length": str(len(body))},
        )

    post_payload = _decode_json_object(post_body)
    post_validation = validate_mail_upload_http_post_result(post_payload)
    updated_session = stores["upload_session_store"].get(upload_session_id)
    asset = (
        stores["asset_store"].get(updated_session.asset_id)
        if updated_session is not None and updated_session.asset_id
        else None
    )
    negative_results = _run_negative_probes(work_dir / "negative", command=command)
    startup_run = _run_command_startup_failure(work_dir / "startup-failure", command=command)
    startup_responses = _decode_json_lines(startup_run.stdout)
    startup_response = startup_responses[0] if startup_responses else {}

    metrics = {
        "command_started": opened.run.returncode == 0 and len(opened.responses) == 3,
        "initialize_succeeded": _response_by_id(opened.responses, "initialize")
        .get("result", {})
        .get("protocolVersion")
        == "2024-11-05",
        "tools_list_succeeded": bool(opened.tool_names),
        "open_upload_session_tool_listed": "open_upload_session" in opened.tool_names,
        "upload_session_call_succeeded": _tool_payload(
            _response_by_id(opened.responses, "open_upload_session")
        ).get("status")
        == "ok",
        "upload_session_persisted": opened.persisted_session is not None,
        "persisted_session_bound_to_env": opened.persisted_session is not None
        and opened.persisted_session.session_id == SESSION_ID
        and opened.persisted_session.actor_user_id == ACTOR_USER_ID
        and opened.persisted_session.workspace_id == WORKSPACE_ID,
        "task_card_resolves_to_persisted_session": _task_card_resolves_to_persisted_session(
            _dict_or_empty(
                _tool_payload(_response_by_id(opened.responses, "open_upload_session")).get("data")
            ),
            opened.persisted_session,
        ),
        "http_get_surface_available": get_response.status == 200
        and b'enctype="multipart/form-data"' in get_body
        and b'name="mail_archive"' in get_body,
        "http_post_upload_succeeded": post_response.status == 201,
        "http_post_result_validated": post_validation["passed"] is True
        and post_payload.get("validation", {}).get("passed") is True,
        "upload_session_asset_bound": updated_session is not None
        and updated_session.status == "uploading"
        and updated_session.processing_status == "archive_uploaded"
        and isinstance(updated_session.asset_id, str),
        "asset_registered": asset is not None,
        "stored_payload_verified": asset is not None
        and stores["object_store"].verify_object(asset.object_uri, asset.content_hash),
        "audit_events_recorded": set(_audit_actions(stores["audit_store"]))
        == {
            "upload_session_created",
            "asset_registered",
            "upload_session_file_received",
        }
        and len(_audit_actions(stores["audit_store"])) == 3,
        "staging_cleaned": _leftover_entry_count(work_dir / "staging") == 0,
        "negative_probes_rejected_without_side_effects": all(
            result.passed for result in negative_results
        ),
        "command_startup_failure_redacted": startup_response.get("error", {}).get("code") == -32000
        and startup_response.get("error", {}).get("message") == "internal_error"
        and startup_run.returncode == 0
        and startup_run.stderr == "",
        "safe_response_hashes_only": True,
        "raw_leak_guard_passed": _public_outputs_are_safe(
            opened.run,
            startup_run,
            post_payload,
            [result.response_payload for result in negative_results],
        ),
    }
    metrics["mail_upload_mcp_http_smoke_passed"] = all(metrics.values())

    http_hashes = [_http_payload_hash("positive_upload", post_payload)] + [
        _http_payload_hash(result.name, result.response_payload) for result in negative_results
    ]
    safe_outputs = {
        "command_profile": "formowl_semantic_mcp_jsonrpc_console_to_local_http_surface",
        "jsonrpc_response_count": len(opened.responses) + len(startup_responses),
        "tool_count": len(opened.tool_names),
        "persisted_upload_session_count": len(stores["upload_session_store"].list()),
        "asset_count_after_upload": len(stores["asset_store"].list()),
        "audit_event_count_after_upload": len(stores["audit_store"].list()),
        "stored_payload_count_after_upload": _stored_payload_count(work_dir / "object-root"),
        "staging_leftover_count": _leftover_entry_count(work_dir / "staging"),
        "get_status_code": get_response.status,
        "post_status_code": post_response.status,
        "negative_probe_count": len(negative_results),
        "negative_probe_status_codes": [result.status_code for result in negative_results],
        "upload_session_shape_hash": _upload_session_shape_hash(updated_session),
        "asset_shape_hash": _asset_shape_hash(asset, updated_session),
        "post_result_shape_hash": _post_result_shape_hash(post_payload),
        "jsonrpc_response_hashes": [
            _jsonrpc_response_hash(response) for response in (opened.responses + startup_responses)
        ],
        "http_response_hashes": http_hashes,
        "command_startup_failure_error_code": startup_response.get("error", {}).get("code"),
    }
    report = {
        "report_type": "mail_upload_mcp_http_smoke",
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": {
            "supports_mcp_command_to_local_http_upload_surface_claim": (
                metrics["mail_upload_mcp_http_smoke_passed"]
            ),
            "supports_local_http_file_transfer_contract_claim": (
                metrics["http_post_upload_succeeded"] and metrics["http_post_result_validated"]
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
                "supports_mcp_command_to_local_http_upload_surface_claim": False,
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
    if report.get("report_type") != "mail_upload_mcp_http_smoke":
        blockers.append("report_type must be mail_upload_mcp_http_smoke")
    if report.get("generated_at") != NOW:
        blockers.append("generated_at must match the fixed smoke generation timestamp")
    metrics = _dict_or_empty(report.get("metrics"))
    safe_outputs = _dict_or_empty(report.get("safe_outputs"))
    claim_boundary = _dict_or_empty(report.get("claim_boundary"))
    _validate_exact_keys(metrics, set(REQUIRED_TRUE_METRICS), "metrics", blockers)
    for metric in REQUIRED_TRUE_METRICS:
        if metrics.get(metric) is not True:
            blockers.append(f"required MCP HTTP smoke metric is not true: {metric}")
    _validate_safe_outputs(safe_outputs, blockers)
    _validate_claim_boundary(claim_boundary, blockers)
    if "validation" in report:
        _validate_embedded_validation(report["validation"], blockers)
    try:
        validate_public_gateway_payload(report)
        assert_no_public_raw_references(report, "mail_upload_mcp_http_smoke_report")
    except Exception:
        blockers.append("public report leaks raw paths, credentials, SQL, or backend internals")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_mcp_command_to_local_http_upload_surface_claim": not blockers,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_production_ready_claim": False,
        },
    }


def _open_upload_session_via_command(
    data_dir: Path,
    *,
    command: Sequence[str] | None,
) -> Any:
    return open_upload_session_via_command(
        data_dir,
        command=command,
        default_command=DEFAULT_COMMAND,
        root=ROOT,
        python_root=PYTHON_ROOT,
        session_id=SESSION_ID,
        actor_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        expires_at=EXPIRES_AT,
        upload_session_store_factory=UploadSessionStore,
    )


def _run_negative_probes(
    root: Path,
    *,
    command: Sequence[str] | None,
) -> list[_NegativeProbeResult]:
    probes = [
        "missing_route",
        "wrong_session_route",
        "wrong_workspace",
        "infra_field",
        "duplicate_file",
        "malformed_multipart",
        "oversize",
    ]
    return [_run_negative_probe(root / probe, probe, command=command) for probe in probes]


def _run_negative_probe(
    work_dir: Path,
    probe_name: str,
    *,
    command: Sequence[str] | None,
) -> _NegativeProbeResult:
    data_dir = work_dir / "data"
    opened = _open_upload_session_via_command(data_dir, command=command)
    upload_session_id = opened.upload_session_id or "missing_upload_session"
    stores = _upload_surface_stores(data_dir, work_dir / "object-root")
    max_request_bytes = 64 if probe_name == "oversize" else 1024 * 1024
    config = _http_config(work_dir, stores, max_request_bytes=max_request_bytes)
    route = f"/mail/upload/{upload_session_id}"
    body = b""
    headers: dict[str, str] = {}
    if probe_name == "missing_route":
        route = f"/not-mail/upload/{upload_session_id}"
    elif probe_name == "wrong_session_route":
        body, content_type = _multipart_body(
            {"upload_session_id": upload_session_id, "workspace_id": WORKSPACE_ID},
            filename=UPLOAD_FILENAME,
            content=UPLOAD_BYTES,
        )
        route = "/mail/upload/upload_missing_session"
        headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
    elif probe_name == "wrong_workspace":
        body, content_type = _multipart_body(
            {"upload_session_id": upload_session_id, "workspace_id": "workspace_other"},
            filename=UPLOAD_FILENAME,
            content=UPLOAD_BYTES,
        )
        headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
    elif probe_name == "infra_field":
        body, content_type = _multipart_body(
            {
                "upload_session_id": upload_session_id,
                "workspace_id": WORKSPACE_ID,
                "storageBackendName": "default",
            },
            filename=UPLOAD_FILENAME,
            content=UPLOAD_BYTES,
        )
        headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
    elif probe_name == "duplicate_file":
        body, content_type = _multipart_body_parts(
            [("upload_session_id", upload_session_id), ("workspace_id", WORKSPACE_ID)],
            files=[
                (UPLOAD_FILENAME, UPLOAD_BYTES),
                ("mail-export-second.pst", b"second upload bytes\n"),
            ],
        )
        headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
    elif probe_name == "malformed_multipart":
        body, content_type = _multipart_body(
            {"upload_session_id": upload_session_id, "workspace_id": WORKSPACE_ID},
            filename=UPLOAD_FILENAME,
            content=UPLOAD_BYTES,
        )
        body = body.rsplit(b"----FormOwlMailUploadHttpBoundary--", 1)[0]
        headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
    elif probe_name == "oversize":
        body, content_type = _multipart_body(
            {"upload_session_id": upload_session_id, "workspace_id": WORKSPACE_ID},
            filename=UPLOAD_FILENAME,
            content=b"x" * 128,
        )
        headers = {"Content-Type": content_type, "Content-Length": str(len(body))}

    with _RunningHttpSurface(config) as surface:
        response, response_body = surface.request(
            "POST",
            route,
            body=body,
            headers=headers,
        )
    payload = _decode_json_object(response_body)
    updated_session = stores["upload_session_store"].get(upload_session_id)
    expected_status = 400
    if probe_name == "missing_route":
        expected_status = 404
    elif probe_name == "oversize":
        expected_status = 413
    no_side_effects = (
        response.status == expected_status
        and stores["asset_store"].list() == []
        and _stored_payload_count(work_dir / "object-root") == 0
        and _leftover_entry_count(work_dir / "staging") == 0
        and updated_session is not None
        and updated_session.asset_id is None
        and updated_session.status == "pending"
        and _audit_actions(stores["audit_store"]) == ["upload_session_created"]
    )
    try:
        validate_public_gateway_payload(payload)
        assert_no_public_raw_references(payload, f"negative_probe.{probe_name}")
    except Exception:
        no_side_effects = False
    return _NegativeProbeResult(
        name=probe_name,
        status_code=response.status,
        response_payload=payload,
        passed=no_side_effects,
    )


def _run_command_startup_failure(
    work_dir: Path,
    *,
    command: Sequence[str] | None,
) -> subprocess.CompletedProcess[str]:
    work_dir.mkdir(parents=True, exist_ok=True)
    blocked_data_dir = work_dir / "not-a-directory"
    blocked_data_dir.write_text("occupied", encoding="utf-8")
    return _run_gateway_command(
        [{"jsonrpc": "2.0", "id": "startup_failure", "method": "initialize"}],
        command=command,
        data_dir=blocked_data_dir,
        session_id=SESSION_ID,
        actor_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
    )


def _run_gateway_command(
    requests: list[dict[str, Any]],
    *,
    command: Sequence[str] | None,
    data_dir: Path,
    session_id: str,
    actor_user_id: str,
    workspace_id: str,
) -> subprocess.CompletedProcess[str]:
    return run_gateway_command(
        requests,
        command=command,
        default_command=DEFAULT_COMMAND,
        root=ROOT,
        python_root=PYTHON_ROOT,
        data_dir=data_dir,
        session_id=session_id,
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        expires_at=EXPIRES_AT,
    )


def _upload_surface_stores(data_dir: Path, object_root: Path) -> dict[str, Any]:
    registry = StorageBackendRegistry(data_dir)
    registry.register_local_backend(
        object_root,
        workspace_scope=WORKSPACE_ID,
        storage_backend_id=STORAGE_BACKEND_ID,
    )
    return {
        "upload_session_store": UploadSessionStore(data_dir),
        "asset_store": AssetStore(data_dir),
        "object_store": FileObjectStore(registry),
        "audit_store": FileAuditLogStore(data_dir),
    }


def _http_config(
    work_dir: Path,
    stores: dict[str, Any],
    *,
    max_request_bytes: int = 1024 * 1024,
) -> Any:
    return build_mail_upload_http_config(
        work_dir,
        stores,
        storage_backend_id=STORAGE_BACKEND_ID,
        actor_user_id=ACTOR_USER_ID,
        session_id=SESSION_ID,
        workspace_id=WORKSPACE_ID,
        received_at=NOW,
        max_request_bytes=max_request_bytes,
    )


def _multipart_body(
    fields: dict[str, str],
    *,
    filename: str | None,
    content: bytes,
    file_content_type: str = UPLOAD_CONTENT_TYPE,
) -> tuple[bytes, str]:
    return build_multipart_mail_archive(
        fields,
        files=[] if filename is None else [(filename, content)],
        file_content_type=file_content_type,
    )


def _multipart_body_parts(
    field_pairs: list[tuple[str, str]],
    *,
    files: list[tuple[str, bytes]],
    file_content_type: str = UPLOAD_CONTENT_TYPE,
) -> tuple[bytes, str]:
    return build_multipart_mail_archive(
        field_pairs,
        files=files,
        file_content_type=file_content_type,
    )


def _task_card_resolves_to_persisted_session(payload: dict[str, Any], persisted: Any) -> bool:
    if persisted is None:
        return False
    task_card = _dict_or_empty(payload.get("upload_task_card"))
    return (
        payload.get("upload_session_id") == persisted.upload_session_id
        and task_card.get("upload_session_id") == persisted.upload_session_id
        and task_card.get("upload_surface_locator")
        == f"formowl_upload_session:{persisted.upload_session_id}"
    )


def _http_payload_hash(name: str, payload: dict[str, Any]) -> str:
    normalized = {
        "name": name,
        "report_type": payload.get("report_type"),
        "status": payload.get("status"),
        "http_status_code": payload.get("http_status_code"),
        "error_code": payload.get("error_code"),
        "validation_passed": _dict_or_empty(payload.get("validation")).get("passed"),
        "claim_boundary": _dict_or_empty(payload.get("claim_boundary")),
    }
    return sha256_json(normalized)


def _upload_session_shape_hash(value: Any) -> str:
    return upload_session_shape_hash(
        value,
        session_id=SESSION_ID,
        project_id=PROJECT_ID,
        include_job_binding=False,
    )


def _post_result_shape_hash(payload: dict[str, Any]) -> str:
    receipt = _dict_or_empty(payload.get("receipt"))
    receipt_safe_outputs = _dict_or_empty(receipt.get("safe_outputs"))
    return sha256_json(
        {
            "report_type": payload.get("report_type"),
            "status": payload.get("status"),
            "http_status_code": payload.get("http_status_code"),
            "receipt_status": receipt.get("status"),
            "accepted_file_type": receipt_safe_outputs.get("accepted_file_type"),
            "file_size_bytes": receipt_safe_outputs.get("file_size_bytes"),
            "duplicate_payload_reused": receipt_safe_outputs.get("duplicate_object_payload_reused"),
            "public_checks": _dict_or_empty(payload.get("public_checks")),
            "claim_boundary": _dict_or_empty(payload.get("claim_boundary")),
        }
    )


def _audit_actions(audit_store: FileAuditLogStore) -> list[str]:
    return [audit.action for audit in audit_store.list()]


def _stored_payload_count(root: Path) -> int:
    if not root.exists():
        return 0
    return len(list(root.rglob("payload.bin")))


def _leftover_entry_count(root: Path) -> int:
    if not root.exists():
        return 0
    return len(list(root.rglob("*")))


def _validate_claim_boundary(
    claim_boundary: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_claims = {
        "supports_mcp_command_to_local_http_upload_surface_claim": True,
        "supports_local_http_file_transfer_contract_claim": True,
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
    validate_common_claim_boundary(
        claim_boundary,
        expected_claims=expected_claims,
        forbidden_true_claims=FORBIDDEN_TRUE_CLAIMS,
        blockers=blockers,
    )


def _validate_safe_outputs(safe_outputs: dict[str, Any], blockers: list[str]) -> None:
    required_keys = {
        "command_profile",
        "jsonrpc_response_count",
        "tool_count",
        "persisted_upload_session_count",
        "asset_count_after_upload",
        "audit_event_count_after_upload",
        "stored_payload_count_after_upload",
        "staging_leftover_count",
        "get_status_code",
        "post_status_code",
        "negative_probe_count",
        "negative_probe_status_codes",
        "upload_session_shape_hash",
        "asset_shape_hash",
        "post_result_shape_hash",
        "jsonrpc_response_hashes",
        "http_response_hashes",
        "command_startup_failure_error_code",
    }
    _validate_exact_keys(safe_outputs, required_keys, "safe_outputs", blockers)
    if (
        safe_outputs.get("command_profile")
        != "formowl_semantic_mcp_jsonrpc_console_to_local_http_surface"
    ):
        blockers.append("safe_outputs.command_profile must identify the local smoke path")
    expected_counts = {
        "jsonrpc_response_count": 4,
        "persisted_upload_session_count": 1,
        "asset_count_after_upload": 1,
        "audit_event_count_after_upload": 3,
        "stored_payload_count_after_upload": 1,
        "staging_leftover_count": 0,
        "get_status_code": 200,
        "post_status_code": 201,
        "negative_probe_count": len(EXPECTED_NEGATIVE_STATUS_CODES),
        "command_startup_failure_error_code": -32000,
    }
    for key, expected in expected_counts.items():
        value = safe_outputs.get(key)
        if type(value) is not int or value != expected:
            blockers.append(f"safe_outputs.{key} must be {expected}")
    tool_count = safe_outputs.get("tool_count")
    if type(tool_count) is not int or tool_count <= 0:
        blockers.append("safe_outputs.tool_count must be a positive integer")
    if safe_outputs.get("negative_probe_status_codes") != EXPECTED_NEGATIVE_STATUS_CODES:
        blockers.append("safe_outputs.negative_probe_status_codes mismatch")
    for key in (
        "upload_session_shape_hash",
        "asset_shape_hash",
        "post_result_shape_hash",
    ):
        value = safe_outputs.get(key)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
    _validate_hash_list(
        safe_outputs.get("jsonrpc_response_hashes"),
        expected_count=4,
        context="safe_outputs.jsonrpc_response_hashes",
        blockers=blockers,
    )
    _validate_hash_list(
        safe_outputs.get("http_response_hashes"),
        expected_count=1 + len(EXPECTED_NEGATIVE_STATUS_CODES),
        context="safe_outputs.http_response_hashes",
        blockers=blockers,
    )


def _validate_embedded_validation(value: Any, blockers: list[str]) -> None:
    validate_common_embedded_validation(
        value,
        expected_claims={
            "supports_mcp_command_to_local_http_upload_surface_claim": True,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_production_ready_claim": False,
        },
        claim_error_messages={
            "supports_mcp_command_to_local_http_upload_surface_claim": (
                "validation MCP-to-HTTP upload claim must be true"
            ),
            "supports_actual_chatgpt_connected_upload_claim": (
                "validation actual ChatGPT claim must be false"
            ),
            "supports_production_ready_claim": "validation production claim must be false",
        },
        blockers=blockers,
    )


def _public_outputs_are_safe(
    command_run: subprocess.CompletedProcess[str],
    startup_run: subprocess.CompletedProcess[str],
    post_payload: dict[str, Any],
    negative_payloads: list[dict[str, Any]],
) -> bool:
    combined = "\n".join(
        [
            command_run.stdout,
            command_run.stderr,
            startup_run.stdout,
            startup_run.stderr,
            json.dumps(post_payload, sort_keys=True),
            json.dumps(negative_payloads, sort_keys=True),
        ]
    )
    lowered = combined.lower()
    forbidden_fragments = (
        str(ROOT).lower(),
        "formowl_data_dir",
        "traceback",
        "workerqueue",
        "worker_queue",
        "storage_backend_id",
        "formowl://object",
        "payload.bin",
        UPLOAD_FILENAME,
    )
    if any(fragment in lowered for fragment in forbidden_fragments):
        return False
    try:
        validate_public_gateway_payload(combined)
        assert_no_public_raw_references(post_payload, "mail_upload_http_post")
        for index, payload in enumerate(negative_payloads):
            assert_no_public_raw_references(payload, f"negative_probe[{index}]")
    except Exception:
        return False
    return command_run.returncode == 0 and startup_run.returncode == 0


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
    report = run_mail_upload_mcp_http_smoke(work_dir, command=args.command)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["validation"]["passed"] else 1


def _default_work_dir() -> Path:
    return Path(tempfile.gettempdir()) / f"formowl-mail-upload-mcp-http-{uuid.uuid4().hex}"


if __name__ == "__main__":
    raise SystemExit(main())
