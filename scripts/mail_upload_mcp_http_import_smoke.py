#!/usr/bin/env python3
"""Run or validate the FormOwl #21 local upload-to-import MCP smoke.

This smoke extends the local MCP-command-to-HTTP upload contract:

initialize -> tools/list -> tools/call open_upload_session
-> POST multipart mail_archive to the local HTTP upload surface
-> run server-side UploadSession-bound mail import
-> write normalized mail evidence through the PostgreSQL adapter contract
-> query the store-backed JSON-RPC `query_mail_evidence` surface

It proves only a local synthetic end-to-end contract. It does not claim that
ChatGPT itself is connected, that a production iframe is ready, that a real
PST/OST/MSG/EML/MBOX parser exists, or that live PostgreSQL is deployed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, Sequence
import uuid

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_auth import FileAuditLogStore  # noqa: E402
from formowl_contract import (  # noqa: E402
    ContractValidationError,
    PermissionScope,
    SourceRef,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_gateway import (  # noqa: E402
    SemanticGatewaySession,
    SemanticMcpGateway,
    SemanticMcpJsonRpcGateway,
    validate_public_gateway_payload,
)
from formowl_ingestion.assets import register_asset_from_local_file  # noqa: E402
from formowl_ingestion.extraction import ExtractionResult  # noqa: E402
from formowl_ingestion.storage import (  # noqa: E402
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
    UploadSessionStore,
)
from formowl_mail import (  # noqa: E402
    MailUploadHttpSurfaceConfig,
    PostgreSQLMailEvidenceStore,
    build_postgre_sql_mail_evidence_query_handler,
    create_mail_upload_http_surface_server,
    run_upload_session_mail_import,
    validate_mail_upload_http_post_result,
    validate_mail_upload_import_summary,
)

DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "formowl-mail-upload-mcp-http-import-smoke.json"
DEFAULT_COMMAND = ("formowl-semantic-mcp-jsonrpc",)
NOW = "2026-07-05T14:00:00+00:00"
SESSION_ID = "session_chatgpt_mcp_http_import_smoke"
ACTOR_USER_ID = "user_chatgpt_mcp_http_import_smoke"
DENIED_USER_ID = "user_denied_mail_import_smoke"
WORKSPACE_ID = "workspace_formowl"
PROJECT_ID = "project_formowl"
EXPIRES_AT = "2026-07-06T00:00:00+00:00"
STORAGE_BACKEND_ID = "storage_mail_upload_mcp_http_import_smoke"
UPLOAD_FILENAME = "mail-export.pst"
UPLOAD_CONTENT_TYPE = "application/vnd.formowl.mail-archive+json"
QUERY_TEXT = "audit approval"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

REQUIRED_TRUE_METRICS = [
    "command_started",
    "initialize_succeeded",
    "tools_list_succeeded",
    "open_upload_session_tool_listed",
    "upload_session_call_succeeded",
    "upload_session_persisted",
    "persisted_session_bound_to_env",
    "http_post_upload_succeeded",
    "http_post_result_validated",
    "upload_session_asset_bound_before_import",
    "server_side_import_succeeded",
    "upload_session_marked_mail_evidence_ready",
    "ingestion_job_and_run_persisted",
    "mail_observations_persisted",
    "mail_evidence_rows_persisted",
    "store_backed_owner_jsonrpc_query_succeeded",
    "store_backed_denied_jsonrpc_query_redacted",
    "raw_archive_retention_decision_recorded",
    "negative_import_probes_rejected_without_success",
    "safe_response_hashes_only",
    "raw_leak_guard_passed",
    "mail_upload_mcp_http_import_smoke_passed",
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

NEGATIVE_PROBES = [
    "missing_asset",
    "wrong_asset_source_ref",
    "parser_failure",
    "store_failure",
    "query_failure",
]


@dataclass(frozen=True)
class _OpenedUploadSession:
    upload_session_id: str | None
    responses: list[dict[str, Any]]
    tool_names: set[str]
    persisted_session: Any
    run: subprocess.CompletedProcess[str]


@dataclass(frozen=True)
class _HttpUploadResult:
    response_status: int
    response_payload: dict[str, Any]
    updated_session: Any
    asset: Any


@dataclass(frozen=True)
class _QueryProbeResult:
    status: str
    evidence_snippet_count: int
    citation_count: int
    hidden_bundles: int
    transcript: list[dict[str, Any]]
    response_hash: str


@dataclass(frozen=True)
class _ImportNegativeProbeResult:
    name: str
    passed: bool
    status: str
    shape_hash: str


def run_mail_upload_mcp_http_import_smoke(
    work_dir: Path,
    *,
    command: Sequence[str] | None = None,
) -> dict[str, Any]:
    data_dir = work_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    opened = _open_upload_session_via_command(data_dir, command=command)
    stores = _mail_stores(data_dir, work_dir / "object-root")
    upload_session_id = opened.upload_session_id or "missing_upload_session"
    upload_result = _upload_fixture_archive_over_http(
        work_dir=work_dir,
        stores=stores,
        upload_session_id=upload_session_id,
    )
    mail_connection = _RecordingMailConnection()
    import_result = run_upload_session_mail_import(
        None,
        upload_session_id=upload_session_id,
        upload_session_store=stores["upload_session_store"],
        object_store=stores["object_store"],
        asset_store=stores["asset_store"],
        job_store=stores["job_store"],
        extractor_run_store=stores["extractor_run_store"],
        observation_store=stores["observation_store"],
        mail_evidence_store=PostgreSQLMailEvidenceStore(mail_connection),
        storage_backend_id=STORAGE_BACKEND_ID,
        actor_user_id=ACTOR_USER_ID,
        session_id=SESSION_ID,
        query_text=QUERY_TEXT,
        created_at=NOW,
    )
    import_summary = import_result.to_public_dict()
    import_validation = validate_mail_upload_import_summary(import_summary)
    updated_session = stores["upload_session_store"].get(upload_session_id)
    stored_bundle = PostgreSQLMailEvidenceStore(mail_connection).get_bundle(
        mail_import_session_id=import_result.mail_import_session_id,
    )
    owner_probe = _query_mail_evidence_via_jsonrpc(
        mail_connection=mail_connection,
        mail_import_session_id=import_result.mail_import_session_id,
        actor_user_id=ACTOR_USER_ID,
    )
    denied_probe = _query_mail_evidence_via_jsonrpc(
        mail_connection=mail_connection,
        mail_import_session_id=import_result.mail_import_session_id,
        actor_user_id=DENIED_USER_ID,
    )
    negative_results = _run_import_negative_probes(
        work_dir / "negative",
        command=command,
    )
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
        "http_post_upload_succeeded": upload_result.response_status == 201,
        "http_post_result_validated": validate_mail_upload_http_post_result(
            upload_result.response_payload
        )["passed"]
        is True,
        "upload_session_asset_bound_before_import": upload_result.updated_session is not None
        and upload_result.updated_session.status == "uploading"
        and upload_result.updated_session.processing_status == "archive_uploaded"
        and isinstance(upload_result.updated_session.asset_id, str),
        "server_side_import_succeeded": import_result.status == "succeeded"
        and import_validation["passed"] is True,
        "upload_session_marked_mail_evidence_ready": updated_session is not None
        and updated_session.status == "succeeded"
        and updated_session.processing_status == "mail_evidence_ready"
        and updated_session.ingestion_job_id == import_result.ingestion_job_id,
        "ingestion_job_and_run_persisted": len(stores["job_store"].list()) == 1
        and len(stores["extractor_run_store"].list()) == 1,
        "mail_observations_persisted": len(stores["observation_store"].list()) > 0,
        "mail_evidence_rows_persisted": _mail_evidence_row_count(mail_connection) > 0,
        "store_backed_owner_jsonrpc_query_succeeded": owner_probe.status == "ok"
        and owner_probe.evidence_snippet_count > 0
        and owner_probe.citation_count > 0,
        "store_backed_denied_jsonrpc_query_redacted": denied_probe.status == "permission_denied"
        and denied_probe.evidence_snippet_count == 0
        and denied_probe.citation_count == 0
        and denied_probe.hidden_bundles == 1,
        "raw_archive_retention_decision_recorded": stored_bundle is not None
        and stored_bundle.mail_import_session.retention_policy == "retain_7_days"
        and stored_bundle.mail_import_session.raw_archive_retention_decision
        == "retained_by_policy",
        "negative_import_probes_rejected_without_success": all(
            result.passed for result in negative_results
        ),
        "safe_response_hashes_only": True,
        "raw_leak_guard_passed": True,
    }
    metrics["mail_upload_mcp_http_import_smoke_passed"] = all(metrics.values())

    safe_outputs = {
        "command_profile": "formowl_semantic_mcp_jsonrpc_to_local_http_import_query",
        "jsonrpc_command_response_count": len(opened.responses),
        "tool_count": len(opened.tool_names),
        "persisted_upload_session_count": len(stores["upload_session_store"].list()),
        "asset_count_after_import": len(stores["asset_store"].list()),
        "job_count_after_import": len(stores["job_store"].list()),
        "extractor_run_count_after_import": len(stores["extractor_run_store"].list()),
        "observation_count_after_import": len(stores["observation_store"].list()),
        "audit_event_count_after_import": len(stores["audit_store"].list()),
        "stored_payload_count_after_import": _stored_payload_count(work_dir / "object-root"),
        "staging_leftover_count": _leftover_entry_count(work_dir / "staging"),
        "post_status_code": upload_result.response_status,
        "mail_evidence_table_count": len(mail_connection.rows),
        "mail_evidence_row_count": _mail_evidence_row_count(mail_connection),
        "mail_evidence_statement_count": len(mail_connection.statements),
        "owner_query_status": owner_probe.status,
        "owner_visible_result_count": owner_probe.evidence_snippet_count,
        "denied_visible_result_count": denied_probe.evidence_snippet_count,
        "denied_query_status": denied_probe.status,
        "negative_probe_count": len(negative_results),
        "negative_probe_names_hash": sha256_json([item.name for item in negative_results]),
        "upload_session_shape_hash": _upload_session_shape_hash(updated_session),
        "asset_shape_hash": _asset_shape_hash(upload_result.asset, updated_session),
        "http_post_result_shape_hash": _http_post_result_shape_hash(upload_result.response_payload),
        "import_summary_shape_hash": _import_summary_shape_hash(import_summary),
        "owner_query_shape_hash": _query_probe_shape_hash(owner_probe),
        "denied_query_shape_hash": _query_probe_shape_hash(denied_probe),
        "jsonrpc_command_response_hashes": [
            _jsonrpc_response_hash(response) for response in opened.responses
        ],
        "store_query_response_hashes": [
            owner_probe.response_hash,
            denied_probe.response_hash,
        ],
        "negative_probe_shape_hashes": [item.shape_hash for item in negative_results],
    }
    report = {
        "report_type": "mail_upload_mcp_http_import_smoke",
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": {
            "supports_mcp_command_to_http_import_query_contract_claim": (
                metrics["mail_upload_mcp_http_import_smoke_passed"]
            ),
            "supports_synthetic_upload_to_postgresql_evidence_contract_claim": (
                metrics["server_side_import_succeeded"]
                and metrics["store_backed_owner_jsonrpc_query_succeeded"]
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
    metrics["raw_leak_guard_passed"] = _public_outputs_are_safe(
        opened.run,
        upload_result.response_payload,
        import_summary,
        owner_probe,
        denied_probe,
        negative_results,
        report,
    )
    metrics["mail_upload_mcp_http_import_smoke_passed"] = all(metrics.values())
    report["claim_boundary"]["supports_mcp_command_to_http_import_query_contract_claim"] = metrics[
        "mail_upload_mcp_http_import_smoke_passed"
    ]
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
                "supports_mcp_command_to_http_import_query_contract_claim": False,
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
    if report.get("report_type") != "mail_upload_mcp_http_import_smoke":
        blockers.append("report_type must be mail_upload_mcp_http_import_smoke")
    if report.get("generated_at") != NOW:
        blockers.append("generated_at must match the fixed smoke generation timestamp")
    metrics = _dict_or_empty(report.get("metrics"))
    safe_outputs = _dict_or_empty(report.get("safe_outputs"))
    claim_boundary = _dict_or_empty(report.get("claim_boundary"))
    _validate_exact_keys(metrics, set(REQUIRED_TRUE_METRICS), "metrics", blockers)
    for metric in REQUIRED_TRUE_METRICS:
        if metrics.get(metric) is not True:
            blockers.append(f"required MCP HTTP import metric is not true: {metric}")
    _validate_safe_outputs(safe_outputs, blockers)
    _validate_claim_boundary(claim_boundary, blockers)
    if "validation" in report:
        _validate_embedded_validation(report["validation"], blockers)
    _reject_body_or_evidence_text_fields(report, blockers)
    try:
        validate_public_gateway_payload(report)
        assert_no_public_raw_references(report, "mail_upload_mcp_http_import_report")
    except Exception:
        blockers.append("public report leaks raw paths, credentials, SQL, or backend internals")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_mcp_command_to_http_import_query_contract_claim": not blockers,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_production_ready_claim": False,
        },
    }


def _open_upload_session_via_command(
    data_dir: Path,
    *,
    command: Sequence[str] | None,
) -> _OpenedUploadSession:
    requests = [
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
                    "owner_scope_id": PROJECT_ID,
                    "project_id": PROJECT_ID,
                },
            },
        },
    ]
    run = _run_gateway_command(
        requests,
        command=command,
        data_dir=data_dir,
        session_id=SESSION_ID,
        actor_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
    )
    responses = _decode_json_lines(run.stdout)
    tools_response = _response_by_id(responses, "tools")
    tool_names = {
        tool["name"]
        for tool in tools_response.get("result", {}).get("tools", [])
        if isinstance(tool, dict)
    }
    upload_payload = _tool_payload(_response_by_id(responses, "open_upload_session"))
    upload_data = _dict_or_empty(upload_payload.get("data"))
    upload_session_id = upload_data.get("upload_session_id")
    sessions = UploadSessionStore(data_dir).list()
    persisted = sessions[0] if len(sessions) == 1 else None
    return _OpenedUploadSession(
        upload_session_id=upload_session_id if isinstance(upload_session_id, str) else None,
        responses=responses,
        tool_names=tool_names,
        persisted_session=persisted,
        run=run,
    )


def _upload_fixture_archive_over_http(
    *,
    work_dir: Path,
    stores: dict[str, Any],
    upload_session_id: str,
) -> _HttpUploadResult:
    body, content_type = _multipart_body(
        {
            "upload_session_id": upload_session_id,
            "workspace_id": WORKSPACE_ID,
        },
        filename=UPLOAD_FILENAME,
        content=_mail_archive_bytes(),
    )
    config = _http_config(work_dir, stores)
    with _RunningHttpSurface(config) as surface:
        response, response_body = surface.request(
            "POST",
            f"/mail/upload/{upload_session_id}",
            body=body,
            headers={"Content-Type": content_type, "Content-Length": str(len(body))},
        )
    payload = _decode_json_object(response_body)
    updated_session = stores["upload_session_store"].get(upload_session_id)
    asset = (
        stores["asset_store"].get(updated_session.asset_id)
        if updated_session is not None and updated_session.asset_id
        else None
    )
    return _HttpUploadResult(
        response_status=response.status,
        response_payload=payload,
        updated_session=updated_session,
        asset=asset,
    )


def _run_import_negative_probes(
    root: Path,
    *,
    command: Sequence[str] | None,
) -> list[_ImportNegativeProbeResult]:
    return [
        _run_import_negative_probe(root / probe, probe, command=command)
        for probe in NEGATIVE_PROBES
    ]


def _run_import_negative_probe(
    work_dir: Path,
    probe_name: str,
    *,
    command: Sequence[str] | None,
) -> _ImportNegativeProbeResult:
    data_dir = work_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    opened = _open_upload_session_via_command(data_dir, command=command)
    stores = _mail_stores(data_dir, work_dir / "object-root")
    upload_session_id = opened.upload_session_id or "missing_upload_session"
    connection = _RecordingMailConnection(
        fail_after_execute=2 if probe_name == "store_failure" else None
    )
    status = "unknown"
    passed = False

    if probe_name == "missing_asset":
        try:
            run_upload_session_mail_import(
                None,
                upload_session_id=upload_session_id,
                upload_session_store=stores["upload_session_store"],
                object_store=stores["object_store"],
                asset_store=stores["asset_store"],
                job_store=stores["job_store"],
                extractor_run_store=stores["extractor_run_store"],
                observation_store=stores["observation_store"],
                mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
                storage_backend_id=STORAGE_BACKEND_ID,
                actor_user_id=ACTOR_USER_ID,
                session_id=SESSION_ID,
                query_text=QUERY_TEXT,
                created_at=NOW,
            )
        except (ContractValidationError, FileNotFoundError):
            status = "missing_asset_rejected"
            session = stores["upload_session_store"].get(upload_session_id)
            passed = (
                session is not None
                and session.status == "pending"
                and session.asset_id is None
                and _no_import_side_effects(stores, connection)
                and _audit_actions(stores["audit_store"]) == ["upload_session_created"]
            )
    elif probe_name == "wrong_asset_source_ref":
        _bind_wrong_source_ref_asset(work_dir, upload_session_id, stores)
        try:
            run_upload_session_mail_import(
                None,
                upload_session_id=upload_session_id,
                upload_session_store=stores["upload_session_store"],
                object_store=stores["object_store"],
                asset_store=stores["asset_store"],
                job_store=stores["job_store"],
                extractor_run_store=stores["extractor_run_store"],
                observation_store=stores["observation_store"],
                mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
                storage_backend_id=STORAGE_BACKEND_ID,
                actor_user_id=ACTOR_USER_ID,
                session_id=SESSION_ID,
                query_text=QUERY_TEXT,
                created_at=NOW,
            )
        except ContractValidationError:
            status = "wrong_asset_source_ref_rejected"
            session = stores["upload_session_store"].get(upload_session_id)
            passed = (
                session is not None
                and session.status == "uploading"
                and session.ingestion_job_id is None
                and stores["job_store"].list() == []
                and stores["extractor_run_store"].list() == []
                and stores["observation_store"].list() == []
                and connection.rows == {}
                and connection.actions == []
            )
    elif probe_name in {"parser_failure", "store_failure", "query_failure"}:
        _upload_fixture_archive_over_http(
            work_dir=work_dir,
            stores=stores,
            upload_session_id=upload_session_id,
        )
        adapter = _FailingMailArchiveExtractor() if probe_name == "parser_failure" else None
        query_text = "nonmatchingterm" if probe_name == "query_failure" else QUERY_TEXT
        try:
            run_upload_session_mail_import(
                None,
                upload_session_id=upload_session_id,
                upload_session_store=stores["upload_session_store"],
                object_store=stores["object_store"],
                asset_store=stores["asset_store"],
                job_store=stores["job_store"],
                extractor_run_store=stores["extractor_run_store"],
                observation_store=stores["observation_store"],
                mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
                storage_backend_id=STORAGE_BACKEND_ID,
                actor_user_id=ACTOR_USER_ID,
                session_id=SESSION_ID,
                query_text=query_text,
                created_at=NOW,
                adapter=adapter,
            )
        except RuntimeError:
            session = stores["upload_session_store"].get(upload_session_id)
            if probe_name == "parser_failure":
                status = "parser_failure_marked_failed"
                passed = (
                    session is not None
                    and session.status == "failed"
                    and session.processing_status == "mail_parser_failed"
                    and stores["observation_store"].list() == []
                    and connection.rows == {}
                )
            elif probe_name == "store_failure":
                status = "store_failure_rolled_back"
                passed = (
                    session is not None
                    and session.status == "failed"
                    and session.processing_status == "mail_evidence_store_failed"
                    and connection.actions == ["begin", "execute", "execute", "rollback"]
                    and connection.rows == {}
                )
            else:
                status = "query_failure_rolled_back"
                passed = (
                    session is not None
                    and session.status == "failed"
                    and session.processing_status == "mail_evidence_query_failed"
                    and connection.actions[0] == "begin"
                    and connection.actions[-1] == "rollback"
                    and connection.rows == {}
                )

    result = _ImportNegativeProbeResult(
        name=probe_name,
        passed=passed,
        status=status,
        shape_hash=sha256_json(
            {
                "name": probe_name,
                "passed": passed,
                "status": status,
                "asset_count": len(stores["asset_store"].list()),
                "job_count": len(stores["job_store"].list()),
                "run_count": len(stores["extractor_run_store"].list()),
                "observation_count": len(stores["observation_store"].list()),
                "mail_evidence_row_count": _mail_evidence_row_count(connection),
            }
        ),
    )
    validate_public_gateway_payload(result.status)
    return result


def _query_mail_evidence_via_jsonrpc(
    *,
    mail_connection: "_RecordingMailConnection",
    mail_import_session_id: str,
    actor_user_id: str,
) -> _QueryProbeResult:
    gateway = SemanticMcpJsonRpcGateway(
        semantic_gateway=SemanticMcpGateway(
            mail_evidence_handler=build_postgre_sql_mail_evidence_query_handler(
                PostgreSQLMailEvidenceStore(mail_connection),
                now=NOW,
            )
        ),
        session=SemanticGatewaySession(
            session_id=SESSION_ID,
            actor_user_id=actor_user_id,
            workspace_id=WORKSPACE_ID,
        ),
    )
    response = gateway.handle_json_rpc(
        {
            "jsonrpc": "2.0",
            "id": f"query_{actor_user_id}",
            "method": "tools/call",
            "params": {
                "name": "query_mail_evidence",
                "arguments": {
                    "query_text": QUERY_TEXT,
                    "mail_import_session_id": mail_import_session_id,
                },
            },
        }
    )
    payload = _tool_payload(response)
    data = _dict_or_empty(payload.get("data"))
    redaction_counts = _dict_or_empty(data.get("redaction_counts"))
    evidence_snippets = data.get("evidence_snippets")
    citations = data.get("citations")
    return _QueryProbeResult(
        status=str(data.get("status", "unknown")),
        evidence_snippet_count=(
            len(evidence_snippets) if isinstance(evidence_snippets, list) else 0
        ),
        citation_count=len(citations) if isinstance(citations, list) else 0,
        hidden_bundles=int(redaction_counts.get("hidden_bundles", 0)),
        transcript=gateway.leak_transcript(),
        response_hash=_query_response_hash(response),
    )


def _bind_wrong_source_ref_asset(
    work_dir: Path,
    upload_session_id: str,
    stores: dict[str, Any],
) -> None:
    source_path = work_dir / "wrong-source-ref" / "mail-archive.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(_mail_archive_bytes())
    session = stores["upload_session_store"].get(upload_session_id)
    if session is None:
        raise ContractValidationError("probe upload session missing")
    asset = register_asset_from_local_file(
        source_path,
        object_store=stores["object_store"],
        asset_store=stores["asset_store"],
        storage_backend_id=STORAGE_BACKEND_ID,
        workspace_id=WORKSPACE_ID,
        owner_user_id=ACTOR_USER_ID,
        permission_scope=PermissionScope.project(PROJECT_ID),
        source_ref=SourceRef(
            source_system="formowl_upload_session",
            source_type="mail_archive_upload",
            source_id="upload_other_session",
            source_key="upload_other_session",
        ),
        mime_type=UPLOAD_CONTENT_TYPE,
        created_at=NOW,
        registered_at=NOW,
    )
    stores["upload_session_store"].create(
        replace(
            session,
            status="uploading",
            source_preparation_state="uploaded",
            processing_status="archive_uploaded",
            asset_id=asset.asset_id,
        )
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
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PYTHON_ROOT)
    env["FORMOWL_DATA_DIR"] = str(data_dir)
    env["FORMOWL_MCP_SESSION_ID"] = session_id
    env["FORMOWL_MCP_ACTOR_USER_ID"] = actor_user_id
    env["FORMOWL_MCP_WORKSPACE_ID"] = workspace_id
    env["FORMOWL_MAIL_UPLOAD_EXPIRES_AT"] = EXPIRES_AT
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


def _mail_stores(data_dir: Path, object_root: Path) -> dict[str, Any]:
    registry = StorageBackendRegistry(data_dir)
    registry.register_local_backend(
        object_root,
        workspace_scope=WORKSPACE_ID,
        storage_backend_id=STORAGE_BACKEND_ID,
    )
    return {
        "upload_session_store": UploadSessionStore(data_dir),
        "asset_store": AssetStore(data_dir),
        "job_store": JobStore(data_dir),
        "extractor_run_store": ExtractorRunStore(data_dir),
        "observation_store": ObservationStore(data_dir),
        "object_store": FileObjectStore(registry),
        "audit_store": FileAuditLogStore(data_dir),
    }


def _http_config(
    work_dir: Path,
    stores: dict[str, Any],
    *,
    max_request_bytes: int = 1024 * 1024,
) -> MailUploadHttpSurfaceConfig:
    return MailUploadHttpSurfaceConfig(
        upload_session_store=stores["upload_session_store"],
        object_store=stores["object_store"],
        asset_store=stores["asset_store"],
        audit_store=stores["audit_store"],
        storage_backend_id=STORAGE_BACKEND_ID,
        actor_user_id=ACTOR_USER_ID,
        session_id=SESSION_ID,
        workspace_id=WORKSPACE_ID,
        staging_dir=work_dir / "staging",
        received_at=NOW,
        max_request_bytes=max_request_bytes,
    )


class _RunningHttpSurface:
    def __init__(self, config: MailUploadHttpSurfaceConfig) -> None:
        self.server = create_mail_upload_http_surface_server("127.0.0.1", 0, config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_RunningHttpSurface":
        self.thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[Any, bytes]:
        connection = http.client.HTTPConnection(
            self.server.server_address[0],
            self.server.server_address[1],
            timeout=5,
        )
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            response_body = response.read()
            return response, response_body
        finally:
            connection.close()


def _multipart_body(
    fields: dict[str, str],
    *,
    filename: str,
    content: bytes,
) -> tuple[bytes, str]:
    boundary = "----FormOwlMailUploadHttpImportBoundary"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    parts.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="mail_archive"; '
                f'filename="{filename}"\r\n'
            ).encode("ascii"),
            f"Content-Type: {UPLOAD_CONTENT_TYPE}\r\n\r\n".encode("ascii"),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _mail_archive_bytes() -> bytes:
    archive = {
        "archive_id": "archive_launch",
        "mailbox_id": "mailbox_formowl",
        "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
        "messages": [
            {
                "message_id": "<launch-001@example.test>",
                "thread_id": "thread_launch",
                "folder_path_hash": "sha256:folder-inbox",
                "subject": "Launch checklist",
                "sender": "pm@example.test",
                "sent_at": NOW,
                "body": ("Update: Launch reviewed\n\n" "Blocker: Waiting on audit approval"),
                "body_hash": "sha256:body-launch",
            }
        ],
    }
    return json.dumps(archive, sort_keys=True).encode("utf-8")


class _RecordingMailConnection:
    def __init__(self, *, fail_after_execute: int | None = None) -> None:
        self.fail_after_execute = fail_after_execute
        self.actions: list[str] = []
        self.statements: list[Any] = []
        self.rows: dict[str, dict[str, dict[str, Any]]] = {}
        self.executed_count = 0
        self._transaction_snapshot: dict[str, dict[str, dict[str, Any]]] | None = None

    def execute(self, statement: Any) -> None:
        self.actions.append("execute")
        self.statements.append(statement)
        self.executed_count += 1
        if self.fail_after_execute is not None and self.executed_count >= self.fail_after_execute:
            raise RuntimeError("simulated mail evidence write failure")
        table_name = statement.sql.split("INSERT INTO ", 1)[1].split(" ", 1)[0]
        record_id = _statement_record_id(table_name, statement.parameters)
        if "DO NOTHING" in statement.sql and record_id in self.rows.get(table_name, {}):
            return
        self.rows.setdefault(table_name, {})[record_id] = {
            **statement.parameters,
            "payload": statement.parameters["payload"],
            "payload_hash": statement.parameters["payload_hash"],
        }

    def query_one(self, statement: Any) -> dict[str, Any] | None:
        self.actions.append("query_one")
        self.statements.append(statement)
        table_name = statement.sql.split(" FROM ", 1)[1].split(" ", 1)[0]
        rows = list(self.rows.get(table_name, {}).values())
        for row in rows:
            if _matches_optional(row, statement.parameters, "mail_import_session_id") and (
                _matches_optional(row, statement.parameters, "mail_evidence_bundle_id")
            ):
                return {
                    "payload": row["payload"],
                    "mail_evidence_bundle_id": row["mail_evidence_bundle_id"],
                    "producer_type": row["producer_type"],
                    "bundle_created_at": row["bundle_created_at"],
                }
        return None

    def query_all(self, statement: Any) -> list[dict[str, Any]]:
        self.actions.append("query_all")
        self.statements.append(statement)
        table_name = statement.sql.split(" FROM ", 1)[1].split(" ", 1)[0]
        rows = list(self.rows.get(table_name, {}).values())
        if "mail_import_session_id" in statement.parameters:
            expected = statement.parameters["mail_import_session_id"]
            rows = [row for row in rows if row.get("mail_import_session_id") == expected]
        for key, value in statement.parameters.items():
            if key.endswith("_ids"):
                id_field = key[:-1]
                allowed = set(value)
                rows = [row for row in rows if row.get(id_field) in allowed]
        return [
            {"payload": row["payload"]} for row in sorted(rows, key=lambda row: row["payload_hash"])
        ]

    def begin(self) -> None:
        self.actions.append("begin")
        self._transaction_snapshot = {
            table: {record_id: dict(row) for record_id, row in records.items()}
            for table, records in self.rows.items()
        }

    def commit(self) -> None:
        self.actions.append("commit")
        self._transaction_snapshot = None

    def rollback(self) -> None:
        self.actions.append("rollback")
        if self._transaction_snapshot is not None:
            self.rows = {
                table: {record_id: dict(row) for record_id, row in records.items()}
                for table, records in self._transaction_snapshot.items()
            }
            self._transaction_snapshot = None


class _FailingMailArchiveExtractor:
    def name(self) -> str:
        return "failing_mail_archive_extractor"

    def version(self) -> str:
        return "0.1.0"

    def supported_mime_types(self) -> list[str]:
        return [UPLOAD_CONTENT_TYPE]

    def extractor_type(self) -> str:
        return "mail_archive"

    def extract(self, extraction_input: Any) -> ExtractionResult:
        return ExtractionResult(errors=["simulated parser failure"])


def _statement_record_id(table_name: str, parameters: dict[str, Any]) -> str:
    id_fields = {
        "mail_import_session": "mail_import_session_id",
        "mail_archive_occurrence": "mail_archive_occurrence_id",
        "mail_folder_occurrence": "mail_folder_occurrence_id",
        "email_message": "email_message_id",
        "email_message_occurrence": "email_message_occurrence_id",
        "email_body_segment": "email_body_segment_id",
        "email_attachment": "email_attachment_id",
        "email_attachment_occurrence": "email_attachment_occurrence_id",
        "quoted_message_candidate": "quoted_message_candidate_id",
        "embedded_message_relation": "embedded_message_relation_id",
        "mail_parse_run": "mail_parse_run_id",
        "mail_parse_warning": "mail_parse_warning_id",
    }
    return str(parameters[id_fields[table_name]])


def _matches_optional(row: dict[str, Any], parameters: dict[str, Any], key: str) -> bool:
    return parameters.get(key) is None or row.get(key) == parameters[key]


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


def _decode_json_object(value: bytes) -> dict[str, Any]:
    decoded = json.loads(value.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("HTTP response body must be a JSON object")
    return decoded


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


def _jsonrpc_response_hash(response: dict[str, Any]) -> str:
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
            normalized["result"]["tool_payload"] = {
                "result_type": payload.get("result_type"),
                "status": payload.get("status"),
                "data_status": data.get("status"),
                "task_card_type": task_card.get("card_type"),
                "validation_passed": _dict_or_empty(data.get("validation")).get("passed"),
            }
    return sha256_json(normalized)


def _query_response_hash(response: dict[str, Any]) -> str:
    payload = _tool_payload(response)
    data = _dict_or_empty(payload.get("data"))
    redaction_counts = _dict_or_empty(data.get("redaction_counts"))
    citations = data.get("citations")
    return sha256_json(
        {
            "jsonrpc": response.get("jsonrpc"),
            "is_error": response.get("result", {}).get("isError"),
            "payload_status": payload.get("status"),
            "data_status": data.get("status"),
            "evidence_snippet_count": (
                len(data.get("evidence_snippets"))
                if isinstance(data.get("evidence_snippets"), list)
                else 0
            ),
            "citation_count": len(citations) if isinstance(citations, list) else 0,
            "hidden_bundles": redaction_counts.get("hidden_bundles"),
            "warnings": data.get("warnings"),
        }
    )


def _http_post_result_shape_hash(payload: dict[str, Any]) -> str:
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
            "public_checks": _dict_or_empty(payload.get("public_checks")),
            "claim_boundary": _dict_or_empty(payload.get("claim_boundary")),
        }
    )


def _import_summary_shape_hash(payload: dict[str, Any]) -> str:
    safe_outputs = _dict_or_empty(payload.get("safe_outputs"))
    return sha256_json(
        {
            "report_type": payload.get("report_type"),
            "status": payload.get("status"),
            "metrics": _dict_or_empty(payload.get("metrics")),
            "observation_count": safe_outputs.get("observation_count"),
            "extractor_run_count": safe_outputs.get("extractor_run_count"),
            "mail_evidence_statement_count": safe_outputs.get("mail_evidence_statement_count"),
            "owner_query_status": safe_outputs.get("owner_query_status"),
            "claim_boundary": _dict_or_empty(payload.get("claim_boundary")),
        }
    )


def _query_probe_shape_hash(value: _QueryProbeResult) -> str:
    return sha256_json(
        {
            "status": value.status,
            "evidence_snippet_count": value.evidence_snippet_count,
            "citation_count": value.citation_count,
            "hidden_bundles": value.hidden_bundles,
            "transcript": value.transcript,
        }
    )


def _upload_session_shape_hash(value: Any) -> str:
    if value is None:
        return sha256_json("")
    return sha256_json(
        {
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
            "asset_bound": isinstance(value.asset_id, str),
            "job_bound": isinstance(value.ingestion_job_id, str),
            "project_bound": value.project_id == PROJECT_ID,
        }
    )


def _asset_shape_hash(asset: Any, upload_session: Any) -> str:
    if asset is None or upload_session is None:
        return sha256_json("")
    source_ref = _dict_or_empty(asset.source_ref)
    return sha256_json(
        {
            "workspace_id": asset.workspace_id,
            "owner_user_id": asset.owner_user_id,
            "mime_type": asset.mime_type,
            "content_hash": asset.content_hash,
            "file_size": asset.file_size,
            "project_id": asset.project_id,
            "source_ref_bound_to_upload_session": source_ref.get("source_id")
            == upload_session.upload_session_id,
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


def _mail_evidence_row_count(connection: _RecordingMailConnection) -> int:
    return sum(len(rows) for rows in connection.rows.values())


def _no_import_side_effects(
    stores: dict[str, Any],
    connection: _RecordingMailConnection,
) -> bool:
    return (
        stores["asset_store"].list() == []
        and stores["job_store"].list() == []
        and stores["extractor_run_store"].list() == []
        and stores["observation_store"].list() == []
        and connection.actions == []
        and connection.rows == {}
    )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _validate_safe_outputs(safe_outputs: dict[str, Any], blockers: list[str]) -> None:
    required_keys = {
        "command_profile",
        "jsonrpc_command_response_count",
        "tool_count",
        "persisted_upload_session_count",
        "asset_count_after_import",
        "job_count_after_import",
        "extractor_run_count_after_import",
        "observation_count_after_import",
        "audit_event_count_after_import",
        "stored_payload_count_after_import",
        "staging_leftover_count",
        "post_status_code",
        "mail_evidence_table_count",
        "mail_evidence_row_count",
        "mail_evidence_statement_count",
        "owner_query_status",
        "owner_visible_result_count",
        "denied_query_status",
        "denied_visible_result_count",
        "negative_probe_count",
        "negative_probe_names_hash",
        "upload_session_shape_hash",
        "asset_shape_hash",
        "http_post_result_shape_hash",
        "import_summary_shape_hash",
        "owner_query_shape_hash",
        "denied_query_shape_hash",
        "jsonrpc_command_response_hashes",
        "store_query_response_hashes",
        "negative_probe_shape_hashes",
    }
    _validate_exact_keys(safe_outputs, required_keys, "safe_outputs", blockers)
    if (
        safe_outputs.get("command_profile")
        != "formowl_semantic_mcp_jsonrpc_to_local_http_import_query"
    ):
        blockers.append("safe_outputs.command_profile must identify the local smoke path")
    exact_counts = {
        "jsonrpc_command_response_count": 3,
        "persisted_upload_session_count": 1,
        "asset_count_after_import": 1,
        "job_count_after_import": 1,
        "extractor_run_count_after_import": 1,
        "audit_event_count_after_import": 3,
        "stored_payload_count_after_import": 1,
        "staging_leftover_count": 0,
        "post_status_code": 201,
        "negative_probe_count": len(NEGATIVE_PROBES),
    }
    for key, expected in exact_counts.items():
        value = safe_outputs.get(key)
        if type(value) is not int or value != expected:
            blockers.append(f"safe_outputs.{key} must be {expected}")
    for key in (
        "tool_count",
        "observation_count_after_import",
        "mail_evidence_table_count",
        "mail_evidence_row_count",
        "mail_evidence_statement_count",
    ):
        value = safe_outputs.get(key)
        if type(value) is not int or value <= 0:
            blockers.append(f"safe_outputs.{key} must be a positive integer")
    if safe_outputs.get("owner_query_status") != "ok":
        blockers.append("safe_outputs.owner_query_status must be ok")
    owner_snippet_count = safe_outputs.get("owner_visible_result_count")
    if type(owner_snippet_count) is not int or owner_snippet_count <= 0:
        blockers.append("safe_outputs.owner_visible_result_count must be positive")
    if safe_outputs.get("denied_query_status") != "permission_denied":
        blockers.append("safe_outputs.denied_query_status must be permission_denied")
    denied_visible_count = safe_outputs.get("denied_visible_result_count")
    if type(denied_visible_count) is not int or denied_visible_count != 0:
        blockers.append("safe_outputs.denied_visible_result_count must be 0")
    for key in (
        "negative_probe_names_hash",
        "upload_session_shape_hash",
        "asset_shape_hash",
        "http_post_result_shape_hash",
        "import_summary_shape_hash",
        "owner_query_shape_hash",
        "denied_query_shape_hash",
    ):
        value = safe_outputs.get(key)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
    _validate_hash_list(
        safe_outputs.get("jsonrpc_command_response_hashes"),
        expected_count=3,
        context="safe_outputs.jsonrpc_command_response_hashes",
        blockers=blockers,
    )
    _validate_hash_list(
        safe_outputs.get("store_query_response_hashes"),
        expected_count=2,
        context="safe_outputs.store_query_response_hashes",
        blockers=blockers,
    )
    _validate_hash_list(
        safe_outputs.get("negative_probe_shape_hashes"),
        expected_count=len(NEGATIVE_PROBES),
        context="safe_outputs.negative_probe_shape_hashes",
        blockers=blockers,
    )


def _validate_claim_boundary(
    claim_boundary: dict[str, Any],
    blockers: list[str],
) -> None:
    expected_claims = {
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
    if not all(isinstance(item, str) and _SHA256_RE.fullmatch(item) for item in value):
        blockers.append(f"{context} must contain sha256 hashes")
    if len(set(value)) != len(value):
        blockers.append(f"{context} must contain distinct hashes")


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
            "supports_mcp_command_to_http_import_query_contract_claim",
            "supports_actual_chatgpt_connected_upload_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    if claim_boundary.get("supports_mcp_command_to_http_import_query_contract_claim") is not True:
        blockers.append("validation local import-query claim must be true")
    if claim_boundary.get("supports_actual_chatgpt_connected_upload_claim") is not False:
        blockers.append("validation actual ChatGPT claim must be false")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


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


def _reject_body_or_evidence_text_fields(
    value: Any,
    blockers: list[str],
    path: str = "",
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            if {"body", "snippet", "content", "text"} & set(normalized.split("_")):
                blockers.append("public report contains evidence text field: " + sha256_json(path))
                return
            _reject_body_or_evidence_text_fields(
                item,
                blockers,
                f"{path}.{key_text}" if path else key_text,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_body_or_evidence_text_fields(item, blockers, f"{path}[{index}]")


def _unknown_keys_message(context: str, keys: Sequence[str]) -> str:
    return f"{context} contains unknown keys: " f"count={len(keys)} hash={sha256_json(list(keys))}"


def _public_outputs_are_safe(
    command_run: subprocess.CompletedProcess[str],
    post_payload: dict[str, Any],
    import_summary: dict[str, Any],
    owner_probe: _QueryProbeResult,
    denied_probe: _QueryProbeResult,
    negative_results: list[_ImportNegativeProbeResult],
    report: dict[str, Any],
) -> bool:
    safe_combined = "\n".join(
        [
            command_run.stdout,
            command_run.stderr,
            json.dumps(post_payload, sort_keys=True),
            json.dumps(import_summary, sort_keys=True),
            json.dumps([item.shape_hash for item in negative_results], sort_keys=True),
            json.dumps(report, sort_keys=True),
            owner_probe.response_hash,
            denied_probe.response_hash,
        ]
    )
    lowered = safe_combined.lower()
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
        "update: launch reviewed",
        "waiting on audit approval",
    )
    if any(fragment in lowered for fragment in forbidden_fragments):
        return False
    try:
        validate_public_gateway_payload(safe_combined)
        assert_no_public_raw_references(report, "mail_upload_mcp_http_import_report")
    except Exception:
        return False
    return command_run.returncode == 0


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
    report = run_mail_upload_mcp_http_import_smoke(work_dir, command=args.command)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["validation"]["passed"] else 1


def _default_work_dir() -> Path:
    return Path(tempfile.gettempdir()) / (f"formowl-mail-upload-mcp-http-import-{uuid.uuid4().hex}")


if __name__ == "__main__":
    raise SystemExit(main())
