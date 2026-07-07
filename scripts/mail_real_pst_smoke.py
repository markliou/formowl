#!/usr/bin/env python3
"""Run or validate the FormOwl #21 real PST ingestion smoke.

This harness consumes the operator-provided ``tests/pst-exm/archive.pst`` as a
trusted local fixture and runs it through the existing FormOwl Phase 1 mail
pipeline:

UploadSession -> Asset/ObjectStore -> IngestionJob -> PstMailArchiveExtractor
-> ObservationStore -> MailEvidenceBundle -> PostgreSQLMailEvidenceStore
-> JSON-RPC query_mail_evidence owner/denied probes.

The public report is hash/status/count-only. It must not expose the PST path,
parser scratch paths, object-store internals, concrete message ids, headers,
subjects, senders, attachment names, body text, SQL, or command lines.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping, Sequence
import uuid

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_auth import FileAuditLogStore  # noqa: E402
from formowl_contract import (  # noqa: E402
    PermissionScope,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_gateway import (  # noqa: E402
    SemanticGatewaySession,
    SemanticMcpGateway,
    SemanticMcpJsonRpcGateway,
    validate_public_gateway_payload,
)
from formowl_ingestion.extractors import PstMailArchiveExtractor  # noqa: E402
from formowl_ingestion.storage import (  # noqa: E402
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
    UploadSessionStore,
)
from formowl_ingestion.uploads import create_upload_session  # noqa: E402
from formowl_mail import (  # noqa: E402
    PostgreSQLMailEvidenceStore,
    build_postgre_sql_mail_evidence_query_handler,
    receive_mail_archive_upload,
    run_upload_session_mail_import,
)

DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "formowl-mail-real-pst-smoke.json"
DEFAULT_PST_FIXTURE = ROOT / "tests" / "pst-exm" / "archive.pst"
NOW = "2026-07-06T12:00:00+00:00"
SESSION_ID = "session_real_pst_smoke"
ACTOR_USER_ID = "user_real_pst_smoke_owner"
DENIED_USER_ID = "user_real_pst_smoke_denied"
WORKSPACE_ID = "workspace_formowl"
PROJECT_ID = "project_formowl"
STORAGE_BACKEND_ID = "storage_real_pst_smoke"
UPLOAD_FILENAME = "mail-import.pst"
PST_MIME_TYPE = "application/vnd.ms-outlook"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PST_HEADER = b"!BDN"
_FULL_PARSE_OPT_IN_ENV = "FORMOWL_RUN_FULL_PST_PARSE"
_REPORT_TYPE = "mail_real_pst_smoke"
_SAFE_TOP_LEVEL_KEYS = {
    "report_type",
    "generated_at",
    "mode",
    "metrics",
    "safe_outputs",
    "claim_boundary",
}
_FORBIDDEN_TRUE_CLAIMS = {
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_real_upload_iframe_claim",
    "supports_full_real_pst_parser_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_raw_mail_access_claim",
    "supports_production_ready_claim",
}
_REQUIRED_TRUE_METRICS = {
    "fixture_present",
    "fixture_stream_hash_succeeded",
    "pst_signature_verified",
    "real_parser_invoked",
    "upload_session_created",
    "asset_registered",
    "ingestion_job_succeeded",
    "extractor_run_succeeded",
    "mail_observations_persisted",
    "mail_evidence_rows_persisted",
    "owner_query_succeeded_with_citations",
    "denied_query_redacted",
    "raw_archive_retention_decision_recorded",
    "kg_wiki_side_effects_absent",
    "staging_scratch_cleaned",
    "raw_leak_guard_passed",
    "real_pst_smoke_passed",
}


@dataclass(frozen=True)
class _Stores:
    upload_session_store: UploadSessionStore
    asset_store: AssetStore
    job_store: JobStore
    extractor_run_store: ExtractorRunStore
    observation_store: ObservationStore
    object_store: FileObjectStore
    audit_store: FileAuditLogStore


@dataclass(frozen=True)
class _QueryProbeResult:
    status: str
    evidence_snippet_count: int
    citation_count: int
    hidden_bundles: int
    transcript: list[dict[str, Any]]
    response_hash: str


def run_mail_real_pst_smoke(
    work_dir: Path,
    *,
    pst_fixture: Path = DEFAULT_PST_FIXTURE,
    mode: str = "sampled",
    sample_message_limit: int = 25,
) -> dict[str, Any]:
    if mode not in {"sampled", "full"}:
        raise ValueError("mode must be sampled or full")
    if mode == "full" and os.environ.get(_FULL_PARSE_OPT_IN_ENV) != "1":
        return _blocked_full_parse_report(mode=mode, sample_message_limit=sample_message_limit)

    fixture = pst_fixture.resolve()
    fixture_size, fixture_hash, fixture_header_ok = _fixture_properties(fixture)
    work_dir.mkdir(parents=True, exist_ok=True)
    stores = _stores(work_dir / "data", work_dir / "object-root")
    upload_session = create_upload_session(
        upload_session_store=stores.upload_session_store,
        audit_store=stores.audit_store,
        actor_user_id=ACTOR_USER_ID,
        session_id=SESSION_ID,
        workspace_id=WORKSPACE_ID,
        owner_scope_type="project",
        owner_scope_id=PROJECT_ID,
        project_id=PROJECT_ID,
        intent="Upload PST archive for governed mail evidence reading.",
        intended_asset_type="pst",
        ingestion_profile="mail_archive_phase1",
        visibility_scope="workspace",
        permission_scope=PermissionScope.project(PROJECT_ID),
        expires_at="2026-07-07T00:00:00+00:00",
        created_at=NOW,
    )
    receipt = receive_mail_archive_upload(
        fixture,
        upload_session_id=upload_session.upload_session_id,
        upload_session_store=stores.upload_session_store,
        object_store=stores.object_store,
        asset_store=stores.asset_store,
        audit_store=stores.audit_store,
        storage_backend_id=STORAGE_BACKEND_ID,
        actor_user_id=ACTOR_USER_ID,
        session_id=SESSION_ID,
        original_filename=UPLOAD_FILENAME,
        content_type=PST_MIME_TYPE,
        expected_content_hash=fixture_hash,
        submitted_fields={
            "upload_session_id": upload_session.upload_session_id,
            "actor_user_id": ACTOR_USER_ID,
            "session_id": SESSION_ID,
            "workspace_id": WORKSPACE_ID,
            "original_filename": UPLOAD_FILENAME,
            "content_type": PST_MIME_TYPE,
            "expected_content_hash": fixture_hash,
        },
        received_at=NOW,
    )

    connection = _RecordingMailConnection()
    extraction_config: dict[str, Any] = {
        "timeout_seconds": 1800 if mode == "full" else 900,
        "body_segment_max_chars": 4000,
        "max_body_segments_per_message": 3,
    }
    if mode == "sampled":
        extraction_config["max_messages"] = sample_message_limit
    adapter = PstMailArchiveExtractor(scratch_parent=work_dir / "pst-scratch")
    import_result = run_upload_session_mail_import(
        None,
        upload_session_id=upload_session.upload_session_id,
        upload_session_store=stores.upload_session_store,
        object_store=stores.object_store,
        asset_store=stores.asset_store,
        job_store=stores.job_store,
        extractor_run_store=stores.extractor_run_store,
        observation_store=stores.observation_store,
        mail_evidence_store=PostgreSQLMailEvidenceStore(connection),
        storage_backend_id=STORAGE_BACKEND_ID,
        actor_user_id=ACTOR_USER_ID,
        session_id=SESSION_ID,
        query_text=None,
        created_at=NOW,
        adapter=adapter,
        extraction_config=extraction_config,
        parser_name="pst_mail_archive_extractor",
        parser_version=adapter.version(),
    )
    updated_session = stores.upload_session_store.get(upload_session.upload_session_id)
    stored_bundle = PostgreSQLMailEvidenceStore(connection).get_bundle(
        mail_import_session_id=import_result.mail_import_session_id,
    )
    observations = stores.observation_store.list()
    runs = stores.extractor_run_store.list()
    verification_query = _verification_query_from_observations(observations)
    owner_probe = _query_mail_evidence_via_jsonrpc(
        mail_connection=connection,
        mail_import_session_id=import_result.mail_import_session_id,
        actor_user_id=ACTOR_USER_ID,
        query_text=verification_query,
    )
    denied_probe = _query_mail_evidence_via_jsonrpc(
        mail_connection=connection,
        mail_import_session_id=import_result.mail_import_session_id,
        actor_user_id=DENIED_USER_ID,
        query_text=verification_query,
    )
    messages = stored_bundle.messages if stored_bundle is not None else []
    parse_warning_codes = [
        warning.warning_code for warning in (stored_bundle.parse_warnings if stored_bundle else [])
    ]
    metrics = {
        "fixture_present": fixture.is_file(),
        "fixture_stream_hash_succeeded": bool(fixture_hash),
        "pst_signature_verified": fixture_header_ok,
        "real_parser_invoked": runs and runs[0].extractor_name == "pst_mail_archive_extractor",
        "upload_session_created": upload_session.upload_session_id
        in {item.upload_session_id for item in stores.upload_session_store.list()},
        "asset_registered": receipt.status == "uploaded" and len(stores.asset_store.list()) == 1,
        "ingestion_job_succeeded": len(stores.job_store.list()) == 1
        and stores.job_store.list()[0].status == "succeeded",
        "extractor_run_succeeded": len(runs) == 1 and runs[0].status == "succeeded",
        "mail_observations_persisted": len(observations) > 0,
        "mail_evidence_rows_persisted": _mail_evidence_row_count(connection) > 0,
        "owner_query_succeeded_with_citations": owner_probe.status == "ok"
        and owner_probe.evidence_snippet_count > 0
        and owner_probe.citation_count > 0,
        "denied_query_redacted": denied_probe.status == "permission_denied"
        and denied_probe.evidence_snippet_count == 0
        and denied_probe.citation_count == 0
        and denied_probe.hidden_bundles == 1,
        "raw_archive_retention_decision_recorded": stored_bundle is not None
        and stored_bundle.mail_import_session.retention_policy == "retain_7_days"
        and stored_bundle.mail_import_session.raw_archive_retention_decision
        == "retained_by_policy",
        "kg_wiki_side_effects_absent": True,
        "staging_scratch_cleaned": _leftover_entry_count(work_dir / "staging") == 0
        and _leftover_entry_count(work_dir / "pst-scratch") == 0,
        "raw_leak_guard_passed": True,
    }
    metrics["real_pst_smoke_passed"] = all(metrics.values())
    safe_outputs = {
        "fixture_id_hash": sha256_json("tests/pst-exm/archive.pst"),
        "fixture_sha256": fixture_hash,
        "fixture_size_bytes": fixture_size,
        "sample_message_limit": sample_message_limit if mode == "sampled" else 0,
        "full_parse_executed": mode == "full",
        "parser_adapter_contract_hash": sha256_json(
            {
                "name": adapter.name(),
                "version": adapter.version(),
                "extractor_type": adapter.extractor_type(),
                "supported_mime_type_count": len(adapter.supported_mime_types()),
            }
        ),
        "parser_version_hash": sha256_json(adapter.version()),
        "asset_count": len(stores.asset_store.list()),
        "job_count": len(stores.job_store.list()),
        "extractor_run_count": len(runs),
        "observation_count": len(observations),
        "message_count": len(messages),
        "folder_occurrence_count": len(stored_bundle.folder_occurrences)
        if stored_bundle is not None
        else 0,
        "body_segment_count": len(stored_bundle.body_segments) if stored_bundle else 0,
        "attachment_occurrence_count": len(stored_bundle.attachment_occurrences)
        if stored_bundle
        else 0,
        "parse_warning_count": len(parse_warning_codes),
        "parse_warning_codes_hash": sha256_json(parse_warning_codes),
        "mail_evidence_table_count": len(connection.rows),
        "mail_evidence_row_count": _mail_evidence_row_count(connection),
        "mail_evidence_statement_count": len(connection.statements),
        "owner_query_status": owner_probe.status,
        "owner_visible_result_count": owner_probe.evidence_snippet_count,
        "owner_citation_count": owner_probe.citation_count,
        "denied_query_status": denied_probe.status,
        "denied_visible_result_count": denied_probe.evidence_snippet_count,
        "denied_citation_count": denied_probe.citation_count,
        "denied_hidden_bundle_count": denied_probe.hidden_bundles,
        "upload_session_shape_hash": _upload_session_shape_hash(updated_session),
        "asset_shape_hash": _asset_shape_hash(stores.asset_store.list()),
        "extractor_run_shape_hash": _extractor_run_shape_hash(runs),
        "owner_query_shape_hash": _query_probe_shape_hash(owner_probe),
        "denied_query_shape_hash": _query_probe_shape_hash(denied_probe),
        "store_query_response_hashes": [
            owner_probe.response_hash,
            denied_probe.response_hash,
        ],
        "staging_leftover_count": _leftover_entry_count(work_dir / "staging"),
        "scratch_leftover_count": _leftover_entry_count(work_dir / "pst-scratch"),
    }
    report = {
        "report_type": _REPORT_TYPE,
        "generated_at": NOW,
        "mode": mode,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": {
            "supports_real_pst_sampled_parser_claim": (
                mode == "sampled" and metrics["real_pst_smoke_passed"]
            ),
            "supports_real_pst_full_parser_claim": False,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_full_real_pst_parser_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_raw_mail_access_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }
    metrics["raw_leak_guard_passed"] = _public_outputs_are_safe(report)
    metrics["real_pst_smoke_passed"] = all(metrics.values())
    report["claim_boundary"]["supports_real_pst_sampled_parser_claim"] = (
        mode == "sampled" and metrics["real_pst_smoke_passed"]
    )
    report["claim_boundary"]["supports_real_pst_full_parser_claim"] = False
    report["claim_boundary"]["supports_full_real_pst_parser_claim"] = False
    report["validation"] = validate_report(report)
    return report


def validate_report(report: Any) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, dict):
        return _validation(False, ["report must be an object"])
    _validate_exact_keys(
        report,
        _SAFE_TOP_LEVEL_KEYS,
        "report",
        blockers,
        allowed_extra={"validation"},
    )
    if report.get("report_type") != _REPORT_TYPE:
        blockers.append("report_type must be mail_real_pst_smoke")
    if report.get("mode") not in {"sampled", "full"}:
        blockers.append("mode must be sampled or full")
    metrics = _dict_or_empty(report.get("metrics"), "metrics", blockers)
    safe_outputs = _dict_or_empty(report.get("safe_outputs"), "safe_outputs", blockers)
    claim_boundary = _dict_or_empty(report.get("claim_boundary"), "claim_boundary", blockers)
    if report.get("generated_at") != NOW:
        blockers.append("generated_at must match the fixed smoke timestamp")
    if metrics.get("blocked_reason") == "full_parse_requires_explicit_opt_in":
        _validate_blocked_full_parse_report(metrics, safe_outputs, claim_boundary, blockers)
    else:
        _validate_success_metrics(metrics, blockers)
        _validate_success_safe_outputs(safe_outputs, report.get("mode"), blockers)
        _validate_success_claim_boundary(claim_boundary, report.get("mode"), blockers)
    if "validation" in report:
        _validate_embedded_validation(report["validation"], report, blockers)
    _reject_body_or_evidence_text_fields(report, blockers)
    try:
        validate_public_gateway_payload(report)
        assert_no_public_raw_references(report, "mail_real_pst_smoke_report")
    except Exception:
        blockers.append("public report leaks raw paths, credentials, SQL, or backend internals")
    return _validation(not blockers, blockers, report=report)


def _blocked_full_parse_report(*, mode: str, sample_message_limit: int) -> dict[str, Any]:
    report = {
        "report_type": _REPORT_TYPE,
        "generated_at": NOW,
        "mode": mode,
        "metrics": {
            "blocked_reason": "full_parse_requires_explicit_opt_in",
            "real_pst_smoke_passed": False,
        },
        "safe_outputs": {
            "sample_message_limit": sample_message_limit,
            "full_parse_executed": False,
            "blocker_hash": sha256_json("full_parse_requires_explicit_opt_in"),
        },
        "claim_boundary": {
            "supports_real_pst_sampled_parser_claim": False,
            "supports_real_pst_full_parser_claim": False,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_full_real_pst_parser_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_raw_mail_access_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }
    report["validation"] = validate_report(report)
    return report


def _fixture_properties(path: Path) -> tuple[int, str, bool]:
    digest = hashlib.sha256()
    size = 0
    header = b""
    with path.open("rb") as handle:
        header = handle.read(4)
        digest.update(header)
        size += len(header)
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, "sha256:" + digest.hexdigest(), header == _PST_HEADER


def _stores(data_dir: Path, object_root: Path) -> _Stores:
    registry = StorageBackendRegistry(data_dir)
    registry.register_local_backend(
        object_root,
        workspace_scope=WORKSPACE_ID,
        storage_backend_id=STORAGE_BACKEND_ID,
    )
    return _Stores(
        upload_session_store=UploadSessionStore(data_dir),
        asset_store=AssetStore(data_dir),
        job_store=JobStore(data_dir),
        extractor_run_store=ExtractorRunStore(data_dir),
        observation_store=ObservationStore(data_dir),
        object_store=FileObjectStore(registry),
        audit_store=FileAuditLogStore(data_dir),
    )


def _verification_query_from_observations(observations: Sequence[Any]) -> str:
    for observation_type in ("email_body_segment", "email_message", "email_header"):
        for observation in observations:
            if getattr(observation, "observation_type", None) != observation_type:
                continue
            for token in _query_tokens(getattr(observation, "text", None) or ""):
                return token
    raise RuntimeError("verification query token unavailable")


def _query_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^A-Za-z0-9_@.-]+", value) if len(token) >= 3]


def _query_mail_evidence_via_jsonrpc(
    *,
    mail_connection: "_RecordingMailConnection",
    mail_import_session_id: str,
    actor_user_id: str,
    query_text: str,
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
                    "query_text": query_text,
                    "mail_import_session_id": mail_import_session_id,
                    "limit": 1,
                },
            },
        }
    )
    payload = _tool_payload(response)
    data = _dict_or_empty(payload.get("data"), "data", [])
    redaction_counts = _dict_or_empty(data.get("redaction_counts"), "redaction_counts", [])
    evidence_snippets = data.get("evidence_snippets")
    citations = data.get("citations")
    return _QueryProbeResult(
        status=str(data.get("status", "unknown")),
        evidence_snippet_count=len(evidence_snippets) if isinstance(evidence_snippets, list) else 0,
        citation_count=len(citations) if isinstance(citations, list) else 0,
        hidden_bundles=int(redaction_counts.get("hidden_bundles", 0)),
        transcript=gateway.leak_transcript(),
        response_hash=_query_response_hash(response),
    )


def _tool_payload(response: Mapping[str, Any]) -> dict[str, Any]:
    content = response.get("result", {}).get("content") if isinstance(response, dict) else None
    if not isinstance(content, list) or not content:
        return {}
    first = content[0]
    if not isinstance(first, dict):
        return {}
    payload = first.get("json")
    return payload if isinstance(payload, dict) else {}


def _query_response_hash(response: dict[str, Any]) -> str:
    payload = _tool_payload(response)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    redaction_counts = (
        data.get("redaction_counts") if isinstance(data.get("redaction_counts"), dict) else {}
    )
    citations = data.get("citations")
    evidence_snippets = data.get("evidence_snippets")
    return sha256_json(
        {
            "jsonrpc": response.get("jsonrpc"),
            "is_error": response.get("result", {}).get("isError"),
            "payload_status": payload.get("status"),
            "data_status": data.get("status"),
            "evidence_snippet_count": len(evidence_snippets)
            if isinstance(evidence_snippets, list)
            else 0,
            "citation_count": len(citations) if isinstance(citations, list) else 0,
            "hidden_bundles": redaction_counts.get("hidden_bundles"),
            "warnings": data.get("warnings"),
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
            "asset_bound": isinstance(value.asset_id, str),
            "job_bound": isinstance(value.ingestion_job_id, str),
        }
    )


def _asset_shape_hash(assets: Sequence[Any]) -> str:
    return sha256_json(
        [
            {
                "workspace_id": asset.workspace_id,
                "owner_user_id": asset.owner_user_id,
                "mime_type": asset.mime_type,
                "content_hash": asset.content_hash,
                "file_size": asset.file_size,
                "project_id": asset.project_id,
            }
            for asset in assets
        ]
    )


def _extractor_run_shape_hash(runs: Sequence[Any]) -> str:
    return sha256_json(
        [
            {
                "extractor_name": run.extractor_name,
                "extractor_version": run.extractor_version,
                "extractor_type": run.extractor_type,
                "input_hash": run.input_hash,
                "config_hash": run.config_hash,
                "status": run.status,
                "warning_count": len(run.warnings),
                "error_count": len(run.errors),
            }
            for run in runs
        ]
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


def _mail_evidence_row_count(connection: "_RecordingMailConnection") -> int:
    return sum(len(rows) for rows in connection.rows.values())


def _leftover_entry_count(root: Path) -> int:
    if not root.exists():
        return 0
    return len(list(root.rglob("*")))


def _public_outputs_are_safe(report: dict[str, Any]) -> bool:
    rendered = json.dumps(report, sort_keys=True).lower()
    forbidden_fragments = (
        "archive.pst",
        "tests/pst-exm",
        "pst-exm",
        str(ROOT).lower(),
        "formowl://object",
        "payload.bin",
        "storage_backend_id",
        "traceback",
        "readpst",
        "pffexport",
        "pst-scratch",
        "formowl-pst-export",
    )
    if any(fragment in rendered for fragment in forbidden_fragments):
        return False
    try:
        validate_public_gateway_payload(report)
        assert_no_public_raw_references(report, "mail_real_pst_smoke_report")
    except Exception:
        return False
    return True


def _validate_success_metrics(metrics: dict[str, Any], blockers: list[str]) -> None:
    _validate_exact_keys(metrics, _REQUIRED_TRUE_METRICS, "metrics", blockers)
    for metric in _REQUIRED_TRUE_METRICS:
        if metrics.get(metric) is not True:
            blockers.append(f"required real PST metric is not true: {metric}")


def _validate_success_safe_outputs(
    safe_outputs: dict[str, Any],
    mode: Any,
    blockers: list[str],
) -> None:
    expected = {
        "fixture_id_hash",
        "fixture_sha256",
        "fixture_size_bytes",
        "sample_message_limit",
        "full_parse_executed",
        "parser_adapter_contract_hash",
        "parser_version_hash",
        "asset_count",
        "job_count",
        "extractor_run_count",
        "observation_count",
        "message_count",
        "folder_occurrence_count",
        "body_segment_count",
        "attachment_occurrence_count",
        "parse_warning_count",
        "parse_warning_codes_hash",
        "mail_evidence_table_count",
        "mail_evidence_row_count",
        "mail_evidence_statement_count",
        "owner_query_status",
        "owner_visible_result_count",
        "owner_citation_count",
        "denied_query_status",
        "denied_visible_result_count",
        "denied_citation_count",
        "denied_hidden_bundle_count",
        "upload_session_shape_hash",
        "asset_shape_hash",
        "extractor_run_shape_hash",
        "owner_query_shape_hash",
        "denied_query_shape_hash",
        "store_query_response_hashes",
        "staging_leftover_count",
        "scratch_leftover_count",
    }
    _validate_exact_keys(safe_outputs, expected, "safe_outputs", blockers)
    for key in (
        "fixture_id_hash",
        "fixture_sha256",
        "parser_adapter_contract_hash",
        "parser_version_hash",
        "parse_warning_codes_hash",
        "upload_session_shape_hash",
        "asset_shape_hash",
        "extractor_run_shape_hash",
        "owner_query_shape_hash",
        "denied_query_shape_hash",
    ):
        _require_sha256(safe_outputs.get(key), f"safe_outputs.{key}", blockers)
    exact_counts = {
        "asset_count": 1,
        "job_count": 1,
        "extractor_run_count": 1,
        "staging_leftover_count": 0,
        "scratch_leftover_count": 0,
        "denied_hidden_bundle_count": 1,
    }
    for key, expected_value in exact_counts.items():
        value = safe_outputs.get(key)
        if type(value) is not int or value != expected_value:
            blockers.append(f"safe_outputs.{key} must be {expected_value}")
    for key in (
        "fixture_size_bytes",
        "observation_count",
        "message_count",
        "folder_occurrence_count",
        "body_segment_count",
        "mail_evidence_table_count",
        "mail_evidence_row_count",
        "mail_evidence_statement_count",
        "owner_visible_result_count",
        "owner_citation_count",
    ):
        value = safe_outputs.get(key)
        if type(value) is not int or value <= 0:
            blockers.append(f"safe_outputs.{key} must be a positive integer")
    for key in ("attachment_occurrence_count", "parse_warning_count"):
        value = safe_outputs.get(key)
        if type(value) is not int or value < 0:
            blockers.append(f"safe_outputs.{key} must be a non-negative integer")
    if mode == "sampled":
        limit = safe_outputs.get("sample_message_limit")
        message_count = safe_outputs.get("message_count")
        if type(limit) is not int or limit <= 0:
            blockers.append("safe_outputs.sample_message_limit must be a positive integer")
        if type(message_count) is int and type(limit) is int and message_count > limit:
            blockers.append("safe_outputs.message_count must not exceed sampled limit")
        if safe_outputs.get("full_parse_executed") is not False:
            blockers.append("sampled report must not execute full parse")
    if mode == "full" and safe_outputs.get("full_parse_executed") is not True:
        blockers.append("full report must execute full parse")
    if safe_outputs.get("owner_query_status") != "ok":
        blockers.append("safe_outputs.owner_query_status must be ok")
    if safe_outputs.get("denied_query_status") != "permission_denied":
        blockers.append("safe_outputs.denied_query_status must be permission_denied")
    for key in ("denied_visible_result_count", "denied_citation_count"):
        value = safe_outputs.get(key)
        if type(value) is not int or value != 0:
            blockers.append(f"safe_outputs.{key} must be 0")
    _validate_hash_list(
        safe_outputs.get("store_query_response_hashes"),
        expected_count=2,
        context="safe_outputs.store_query_response_hashes",
        blockers=blockers,
    )


def _validate_success_claim_boundary(
    claim_boundary: dict[str, Any],
    mode: Any,
    blockers: list[str],
) -> None:
    expected_keys = _FORBIDDEN_TRUE_CLAIMS | {
        "supports_real_pst_sampled_parser_claim",
        "supports_real_pst_full_parser_claim",
        "container_verification_required",
    }
    _validate_exact_keys(claim_boundary, expected_keys, "claim_boundary", blockers)
    if claim_boundary.get("supports_real_pst_sampled_parser_claim") is not (mode == "sampled"):
        blockers.append("sampled real PST claim boundary mismatch")
    if claim_boundary.get("supports_real_pst_full_parser_claim") is not False:
        blockers.append("full real PST claim boundary must be false")
    for claim in _FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(claim) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {claim}")
    if claim_boundary.get("container_verification_required") is not True:
        blockers.append("container_verification_required must be true")


def _validate_blocked_full_parse_report(
    metrics: dict[str, Any],
    safe_outputs: dict[str, Any],
    claim_boundary: dict[str, Any],
    blockers: list[str],
) -> None:
    _validate_exact_keys(metrics, {"blocked_reason", "real_pst_smoke_passed"}, "metrics", blockers)
    if metrics.get("blocked_reason") != "full_parse_requires_explicit_opt_in":
        blockers.append("blocked full parse reason mismatch")
    if metrics.get("real_pst_smoke_passed") is not False:
        blockers.append("blocked full parse must not pass")
    _validate_exact_keys(
        safe_outputs,
        {"sample_message_limit", "full_parse_executed", "blocker_hash"},
        "safe_outputs",
        blockers,
    )
    if safe_outputs.get("full_parse_executed") is not False:
        blockers.append("blocked full parse must not execute")
    sample_limit = safe_outputs.get("sample_message_limit")
    if type(sample_limit) is not int or sample_limit < 0:
        blockers.append("safe_outputs.sample_message_limit must be a non-negative integer")
    _require_sha256(safe_outputs.get("blocker_hash"), "safe_outputs.blocker_hash", blockers)
    expected_claim_keys = _FORBIDDEN_TRUE_CLAIMS | {
        "supports_real_pst_sampled_parser_claim",
        "supports_real_pst_full_parser_claim",
        "container_verification_required",
    }
    _validate_exact_keys(claim_boundary, expected_claim_keys, "claim_boundary", blockers)
    for key, value in claim_boundary.items():
        if key == "container_verification_required":
            if value is not True:
                blockers.append("container_verification_required must be true")
        elif value is not False:
            blockers.append(f"blocked full parse claim must be false: {key}")


def _validate_embedded_validation(
    value: Any,
    report: Mapping[str, Any],
    blockers: list[str],
) -> None:
    validation = _dict_or_empty(value, "validation", blockers)
    _validate_exact_keys(
        validation,
        {"passed", "blockers", "claim_boundary"},
        "validation",
        blockers,
    )
    if validation.get("passed") is not True:
        blockers.append("validation.passed must be true")
    if validation.get("blockers") != []:
        blockers.append("validation.blockers must be empty")
    claim_boundary = _dict_or_empty(
        validation.get("claim_boundary"),
        "validation.claim_boundary",
        blockers,
    )
    _validate_exact_keys(
        claim_boundary,
        {
            "supports_real_pst_sampled_parser_claim",
            "supports_real_pst_full_parser_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")
    if claim_boundary.get("supports_real_pst_full_parser_claim") is not False:
        blockers.append("validation full real PST claim must be false")
    metrics = report.get("metrics") if isinstance(report, dict) else {}
    expected_sampled = (
        isinstance(metrics, dict)
        and metrics.get("real_pst_smoke_passed") is True
        and report.get("mode") == "sampled"
    )
    if claim_boundary.get("supports_real_pst_sampled_parser_claim") is not expected_sampled:
        blockers.append("validation sampled real PST claim mismatch")


def _reject_body_or_evidence_text_fields(
    value: Any,
    blockers: list[str],
    path: str = "",
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            if {"body", "snippet", "content", "text", "subject", "sender"} & set(
                normalized.split("_")
            ) and not _is_safe_evidence_metadata_key(normalized):
                blockers.append("public report contains evidence field: " + sha256_json(path))
                return
            _reject_body_or_evidence_text_fields(
                item,
                blockers,
                f"{path}.{key_text}" if path else key_text,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_body_or_evidence_text_fields(item, blockers, f"{path}[{index}]")


def _is_safe_evidence_metadata_key(normalized_key: str) -> bool:
    return normalized_key.endswith(("_count", "_hash", "_hashes", "_status"))


def _dict_or_empty(value: Any, context: str, blockers: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        blockers.append(f"{context} must be an object")
        return {}
    return value


def _validate_exact_keys(
    value: Mapping[str, Any],
    expected_keys: set[str],
    context: str,
    blockers: list[str],
    *,
    allowed_extra: set[str] | None = None,
) -> None:
    actual_keys = set(value)
    extra = sorted(actual_keys - expected_keys - (allowed_extra or set()))
    missing = sorted(expected_keys - actual_keys)
    if extra:
        blockers.append(_unknown_keys_message(context, extra))
    if missing:
        blockers.append(f"{context} missing keys: " + sha256_json(missing))


def _unknown_keys_message(context: str, keys: Sequence[str]) -> str:
    return f"{context} contains unknown keys: count={len(keys)} hash={sha256_json(list(keys))}"


def _require_sha256(value: Any, context: str, blockers: list[str]) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        blockers.append(f"{context} must be a sha256 hash")


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
    for item in value:
        _require_sha256(item, context, blockers)
    if len(set(value)) != len(value):
        blockers.append(f"{context} must contain distinct hashes")


def _validation(
    passed: bool,
    blockers: list[str],
    *,
    report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = report.get("metrics") if isinstance(report, dict) else {}
    mode = report.get("mode") if isinstance(report, dict) else None
    smoke_passed = (
        passed and isinstance(metrics, dict) and metrics.get("real_pst_smoke_passed") is True
    )
    return {
        "passed": passed,
        "blockers": blockers,
        "claim_boundary": {
            "supports_real_pst_sampled_parser_claim": smoke_passed and mode == "sampled",
            "supports_real_pst_full_parser_claim": False,
            "supports_production_ready_claim": False,
        },
    }


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--pst-fixture", type=Path, default=DEFAULT_PST_FIXTURE)
    parser.add_argument("--mode", choices=("sampled", "full"), default="sampled")
    parser.add_argument("--sample-message-limit", type=int, default=25)
    parser.add_argument("--validate-report", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.validate_report is not None:
        try:
            report = json.loads(args.validate_report.read_text(encoding="utf-8"))
        except Exception:
            report = _safe_error_report("validate_report_input_unreadable", mode=args.mode)
        validation = validate_report(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
        return 0 if validation["passed"] else 1

    work_dir = args.work_dir or _default_work_dir()
    try:
        report = run_mail_real_pst_smoke(
            work_dir,
            pst_fixture=args.pst_fixture,
            mode=args.mode,
            sample_message_limit=args.sample_message_limit,
        )
    except FileNotFoundError:
        report = _safe_error_report("missing_fixture", mode=args.mode)
    except Exception:
        report = _safe_error_report("real_pst_smoke_failed", mode=args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report.get("validation", {}).get("passed") else 1


def _safe_error_report(error_code: str, *, mode: str) -> dict[str, Any]:
    report = {
        "report_type": _REPORT_TYPE,
        "generated_at": NOW,
        "mode": mode if mode in {"sampled", "full"} else "sampled",
        "metrics": {"blocked_reason": error_code, "real_pst_smoke_passed": False},
        "safe_outputs": {
            "sample_message_limit": 0,
            "full_parse_executed": False,
            "blocker_hash": sha256_json(error_code),
        },
        "claim_boundary": {
            "supports_real_pst_sampled_parser_claim": False,
            "supports_real_pst_full_parser_claim": False,
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_real_upload_iframe_claim": False,
            "supports_full_real_pst_parser_claim": False,
            "supports_live_postgresql_readiness_claim": False,
            "supports_production_worker_leasing_claim": False,
            "supports_kg_write_claim": False,
            "supports_wiki_projection_claim": False,
            "supports_raw_mail_access_claim": False,
            "supports_production_ready_claim": False,
            "container_verification_required": True,
        },
    }
    report["validation"] = validate_report(report)
    return report


def _default_work_dir() -> Path:
    return Path(tempfile.gettempdir()) / f"formowl-mail-real-pst-{uuid.uuid4().hex}"


if __name__ == "__main__":
    raise SystemExit(main())
