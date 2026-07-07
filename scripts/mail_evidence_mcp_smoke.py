#!/usr/bin/env python3
"""Run or validate the FormOwl #21 mail evidence MCP smoke.

This smoke is a ChatGPT-free preflight for the governed mail evidence query
surface. It uses a synthetic mail fixture and proves the current normalized
bundle path through JSON-RPC. It does not claim real PST parsing, upload UI,
PostgreSQL mail evidence persistence, KG writes, wiki projection, or
production readiness.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any
import uuid

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import Grant, PermissionScope, SourceRef, sha256_json  # noqa: E402
from formowl_gateway import (  # noqa: E402
    SemanticGatewaySession,
    SemanticMcpGateway,
    SemanticMcpJsonRpcGateway,
    validate_public_gateway_payload,
)
from formowl_ingestion.assets import register_asset_from_local_file  # noqa: E402
from formowl_ingestion.extractors import FixtureMailArchiveExtractor  # noqa: E402
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job  # noqa: E402
from formowl_ingestion.storage import (  # noqa: E402
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendRegistry,
)
from formowl_mail import (  # noqa: E402
    build_mail_case_progress_handler,
    build_mail_evidence_bundle,
    build_mail_evidence_query_handler,
)


DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "formowl-mail-evidence-mcp-smoke.json"
NOW = "2026-07-05T10:00:00+00:00"
WORKSPACE_ID = "workspace_formowl"
OWNER_USER_ID = "user_yifan"
OTHER_USER_ID = "user_other"
SESSION_OWNER = "session_mail_smoke_owner"
SESSION_OTHER = "session_mail_smoke_other"
SMOKE_SENTINEL = ".formowl-mail-evidence-mcp-smoke"
SMOKE_STORAGE_BACKEND_ID = "storage_mail_evidence_mcp_smoke"

REQUIRED_TRUE_METRICS = [
    "asset_registered",
    "ingestion_job_succeeded",
    "extractor_run_succeeded",
    "mail_observations_persisted",
    "mail_evidence_bundle_built",
    "jsonrpc_tool_listed",
    "owner_query_returned_citation",
    "bundle_id_query_succeeded",
    "case_progress_answer_returned_citation",
    "case_progress_bundle_id_succeeded",
    "case_progress_denied_redacted",
    "case_progress_forged_grant_rejected",
    "case_progress_trusted_grant_allowed",
    "denied_query_redacted",
    "forged_grant_rejected",
    "trusted_grant_query_allowed",
    "wrong_owner_trusted_grant_denied",
    "hash_only_transcripts",
    "raw_leak_guard_passed",
    "mail_evidence_mcp_smoke_passed",
]

FORBIDDEN_TRUE_CLAIMS = [
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_upload_ui_claim",
    "supports_production_iframe_readiness_claim",
    "supports_real_pst_parser_claim",
    "supports_postgresql_mail_evidence_claim",
    "supports_production_worker_leasing_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_production_ready_claim",
]
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def run_mail_evidence_mcp_smoke(work_dir: Path) -> dict[str, Any]:
    _prepare_work_dir(work_dir)

    source_path = work_dir / "incoming" / "mail-archive.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(json.dumps(_mail_archive(), sort_keys=True), encoding="utf-8")

    asset_store = AssetStore(work_dir)
    job_store = JobStore(work_dir)
    extractor_run_store = ExtractorRunStore(work_dir)
    observation_store = ObservationStore(work_dir)
    registry = StorageBackendRegistry(work_dir)
    backend = registry.register_local_backend(
        work_dir / "object-root",
        workspace_scope=WORKSPACE_ID,
        storage_backend_id=SMOKE_STORAGE_BACKEND_ID,
    )
    object_store = FileObjectStore(registry)
    adapter = FixtureMailArchiveExtractor()

    asset = register_asset_from_local_file(
        source_path,
        object_store=object_store,
        asset_store=asset_store,
        storage_backend_id=backend.storage_backend_id,
        workspace_id=WORKSPACE_ID,
        owner_user_id=OWNER_USER_ID,
        permission_scope=PermissionScope.project("project_formowl"),
        source_ref=SourceRef(
            source_system="local",
            source_type="mail_archive",
            source_id="mail-archive.json",
        ),
        mime_type="application/vnd.formowl.mail-archive+json",
        created_at=NOW,
        registered_at=NOW,
    )
    job = create_ingestion_job(
        asset=asset,
        job_store=job_store,
        requested_by=OWNER_USER_ID,
        extractor_adapters=[adapter],
        created_at=NOW,
    )
    finished_job = run_ingestion_job(
        ingestion_job_id=job.ingestion_job_id,
        asset_store=asset_store,
        job_store=job_store,
        object_store=object_store,
        extractor_run_store=extractor_run_store,
        observation_store=observation_store,
        extractor_adapters=[adapter],
        started_at=NOW,
        completed_at=NOW,
    )
    observations = [
        observation
        for observation in observation_store.list()
        if observation.observation_id in set(finished_job.observation_ids)
    ]
    bundle = build_mail_evidence_bundle(
        observations,
        workspace_id=WORKSPACE_ID,
        owner_user_id=OWNER_USER_ID,
        source_asset_id=asset.asset_id,
        archive_sha256="sha256:archive-launch",
        upload_session_id="upload_session_mail_smoke",
        created_at=NOW,
        started_at=NOW,
        completed_at=NOW,
    )

    owner_gateway = _jsonrpc_gateway(
        bundle,
        actor_user_id=OWNER_USER_ID,
        session_id=SESSION_OWNER,
    )
    other_gateway = _jsonrpc_gateway(
        bundle,
        actor_user_id=OTHER_USER_ID,
        session_id=SESSION_OTHER,
    )
    trusted_gateway = _jsonrpc_gateway(
        bundle,
        actor_user_id=OTHER_USER_ID,
        session_id="session_mail_smoke_trusted",
        trusted_grants=[_trusted_mail_grant(bundle)],
    )
    wrong_owner_gateway = _jsonrpc_gateway(
        bundle,
        actor_user_id=OTHER_USER_ID,
        session_id="session_mail_smoke_wrong_owner",
        trusted_grants=[
            _trusted_mail_grant(bundle, owner_user_id="user_wrong_owner"),
        ],
    )

    tools = owner_gateway.handle_json_rpc({"jsonrpc": "2.0", "id": "tools", "method": "tools/list"})
    owner_query = _call_query(
        owner_gateway,
        request_id="owner_query",
        arguments={
            "query_text": "audit approval",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        },
    )
    bundle_query = _call_query(
        owner_gateway,
        request_id="bundle_query",
        arguments={
            "query_text": "audit approval",
            "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
        },
    )
    denied_query = _call_query(
        other_gateway,
        request_id="denied_query",
        arguments={
            "query_text": "audit approval",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        },
    )
    forged_query = _call_query(
        other_gateway,
        request_id="forged_query",
        arguments={
            "query_text": "audit approval",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
            "grants": [_trusted_mail_grant(bundle).to_dict()],
        },
    )
    trusted_query = _call_query(
        trusted_gateway,
        request_id="trusted_query",
        arguments={
            "query_text": "audit approval",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        },
    )
    wrong_owner_query = _call_query(
        wrong_owner_gateway,
        request_id="wrong_owner_query",
        arguments={
            "query_text": "audit approval",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        },
    )
    case_progress_owner = _call_case_progress(
        owner_gateway,
        request_id="case_progress_owner",
        arguments={
            "case_id": "case_launch",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        },
    )
    case_progress_bundle = _call_case_progress(
        owner_gateway,
        request_id="case_progress_bundle",
        arguments={
            "case_id": "case_launch",
            "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
        },
    )
    case_progress_denied = _call_case_progress(
        other_gateway,
        request_id="case_progress_denied",
        arguments={
            "case_id": "case_launch",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        },
    )
    case_progress_forged = _call_case_progress(
        other_gateway,
        request_id="case_progress_forged",
        arguments={
            "case_id": "case_launch",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
            "grants": [_trusted_mail_grant(bundle).to_dict()],
        },
    )
    case_progress_trusted = _call_case_progress(
        trusted_gateway,
        request_id="case_progress_trusted",
        arguments={
            "case_id": "case_launch",
            "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        },
    )

    owner_payload = _tool_payload(owner_query)
    bundle_payload = _tool_payload(bundle_query)
    denied_payload = _tool_payload(denied_query)
    forged_payload = _tool_payload(forged_query)
    trusted_payload = _tool_payload(trusted_query)
    wrong_owner_payload = _tool_payload(wrong_owner_query)
    case_progress_owner_payload = _tool_payload(case_progress_owner)
    case_progress_bundle_payload = _tool_payload(case_progress_bundle)
    case_progress_denied_payload = _tool_payload(case_progress_denied)
    case_progress_forged_payload = _tool_payload(case_progress_forged)
    case_progress_trusted_payload = _tool_payload(case_progress_trusted)
    transcripts = (
        owner_gateway.leak_transcript()
        + other_gateway.leak_transcript()
        + trusted_gateway.leak_transcript()
        + wrong_owner_gateway.leak_transcript()
    )

    metrics = {
        "asset_registered": bool(asset.asset_id),
        "ingestion_job_succeeded": finished_job.status == "succeeded",
        "extractor_run_succeeded": bool(finished_job.extractor_run_ids),
        "mail_observations_persisted": len(observations) >= 4,
        "mail_evidence_bundle_built": bool(bundle.mail_evidence_bundle_id),
        "jsonrpc_tool_listed": {
            "answer_mail_case_progress",
            "query_mail_evidence",
        }.issubset({tool["name"] for tool in tools.get("result", {}).get("tools", [])}),
        "owner_query_returned_citation": _ok_with_citation(owner_payload),
        "bundle_id_query_succeeded": _ok_with_citation(bundle_payload),
        "case_progress_answer_returned_citation": _case_progress_ok_with_citation(
            case_progress_owner_payload
        ),
        "case_progress_bundle_id_succeeded": _case_progress_ok_with_citation(
            case_progress_bundle_payload
        ),
        "case_progress_denied_redacted": _case_progress_denied_without_content(
            case_progress_denied_payload
        ),
        "case_progress_forged_grant_rejected": _safe_unsafe_tool_rejection_without_content(
            case_progress_forged_payload
        ),
        "case_progress_trusted_grant_allowed": _case_progress_ok_with_citation(
            case_progress_trusted_payload
        ),
        "denied_query_redacted": _denied_without_content(denied_payload),
        "forged_grant_rejected": _safe_unsafe_tool_rejection_without_content(forged_payload),
        "trusted_grant_query_allowed": _ok_with_citation(trusted_payload),
        "wrong_owner_trusted_grant_denied": _denied_without_content(wrong_owner_payload),
        "hash_only_transcripts": all(
            set(entry) == {"method", "request_hash", "response_hash", "status"}
            for entry in transcripts
        ),
        "raw_leak_guard_passed": True,
    }
    metrics["mail_evidence_mcp_smoke_passed"] = all(metrics.values())

    report = {
        "report_type": "mail_evidence_mcp_smoke",
        "generated_at": NOW,
        "metrics": metrics,
        "safe_outputs": {
            "asset_id_hash": sha256_json(asset.asset_id),
            "ingestion_job_id_hash": sha256_json(finished_job.ingestion_job_id),
            "mail_evidence_bundle_id_hash": sha256_json(bundle.mail_evidence_bundle_id),
            "mail_import_session_id_hash": sha256_json(
                bundle.mail_import_session.mail_import_session_id
            ),
            "observation_count": len(observations),
            "owner_query_status": owner_payload["status"],
            "denied_query_status": denied_payload["status"],
            "forged_query_status": forged_payload["status"],
            "trusted_query_status": trusted_payload["status"],
            "wrong_owner_query_status": wrong_owner_payload["status"],
            "owner_citation_count": len(owner_payload["data"]["citations"]),
            "response_hashes": [
                sha256_json(item)
                for item in (
                    tools,
                    owner_query,
                    bundle_query,
                    denied_query,
                    forged_query,
                    trusted_query,
                    wrong_owner_query,
                    case_progress_owner,
                    case_progress_bundle,
                    case_progress_denied,
                    case_progress_forged,
                    case_progress_trusted,
                )
            ],
            "transcript": transcripts,
            "owner_case_progress_status": case_progress_owner_payload["status"],
            "bundle_case_progress_status": case_progress_bundle_payload["status"],
            "denied_case_progress_status": case_progress_denied_payload["status"],
            "forged_case_progress_status": case_progress_forged_payload["status"],
            "trusted_case_progress_status": case_progress_trusted_payload["status"],
            "owner_case_progress_citation_count": len(
                case_progress_owner_payload["data"]["citations"]
            ),
        },
        "claim_boundary": {
            "supports_chatgpt_free_mail_evidence_mcp_smoke_claim": (
                metrics["mail_evidence_mcp_smoke_passed"]
            ),
            "supports_actual_chatgpt_connected_upload_claim": False,
            "supports_upload_ui_claim": False,
            "supports_production_iframe_readiness_claim": False,
            "supports_real_pst_parser_claim": False,
            "supports_postgresql_mail_evidence_claim": False,
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


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    allowed_top_level = {
        "report_type",
        "generated_at",
        "metrics",
        "safe_outputs",
        "claim_boundary",
        "validation",
    }
    extra_top_level = sorted(set(report) - allowed_top_level)
    if extra_top_level:
        blockers.append(_unknown_keys_message("report", extra_top_level))
    metrics = report.get("metrics")
    safe_outputs = report.get("safe_outputs")
    claim_boundary = report.get("claim_boundary")
    if report.get("report_type") != "mail_evidence_mcp_smoke":
        blockers.append("report_type must be mail_evidence_mcp_smoke")
    if "validation" in report:
        _validate_embedded_validation(report["validation"], blockers)
    if not isinstance(metrics, dict):
        blockers.append("metrics must be an object")
        metrics = {}
    if not isinstance(safe_outputs, dict):
        blockers.append("safe_outputs must be an object")
        safe_outputs = {}
    if not isinstance(claim_boundary, dict):
        blockers.append("claim_boundary must be an object")
        claim_boundary = {}
    _validate_exact_keys(
        metrics,
        set(REQUIRED_TRUE_METRICS),
        "metrics",
        blockers,
    )
    _validate_exact_keys(
        claim_boundary,
        {
            "supports_chatgpt_free_mail_evidence_mcp_smoke_claim",
            "supports_actual_chatgpt_connected_upload_claim",
            "supports_upload_ui_claim",
            "supports_production_iframe_readiness_claim",
            "supports_real_pst_parser_claim",
            "supports_postgresql_mail_evidence_claim",
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
            blockers.append(f"required smoke metric is not true: {metric}")
    for claim in FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(claim) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {claim}")
    if claim_boundary.get("supports_chatgpt_free_mail_evidence_mcp_smoke_claim") is not True:
        blockers.append("chatgpt-free smoke claim is not supported")
    if claim_boundary.get("container_verification_required") is not True:
        blockers.append("container_verification_required must be true")
    _validate_safe_outputs(safe_outputs, blockers)
    _reject_body_or_snippet_fields(report, blockers)
    rendered_report = json.dumps(report, sort_keys=True)
    for phrase in _synthetic_body_fragments():
        if phrase in rendered_report:
            blockers.append("public report includes synthetic mail body text")
            break
    try:
        validate_public_gateway_payload(report)
    except Exception:
        blockers.append("public report leaks raw paths, SQL, or internal values")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_chatgpt_free_mail_evidence_mcp_smoke_claim": (
                not blockers
                and claim_boundary.get("supports_chatgpt_free_mail_evidence_mcp_smoke_claim")
                is True
            ),
            "supports_production_ready_claim": False,
        },
    }


def _validate_embedded_validation(value: Any, blockers: list[str]) -> None:
    if not isinstance(value, dict):
        blockers.append("validation must be an object")
        return
    expected_keys = {"passed", "blockers", "claim_boundary"}
    _validate_exact_keys(value, expected_keys, "validation", blockers)
    if value.get("passed") is not True:
        blockers.append("validation.passed must be true")
    if value.get("blockers") != []:
        blockers.append("validation.blockers must be empty")
    claim_boundary = value.get("claim_boundary")
    if not isinstance(claim_boundary, dict):
        blockers.append("validation.claim_boundary must be an object")
        return
    _validate_exact_keys(
        claim_boundary,
        {
            "supports_chatgpt_free_mail_evidence_mcp_smoke_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    if claim_boundary.get("supports_chatgpt_free_mail_evidence_mcp_smoke_claim") is not True:
        blockers.append("validation smoke claim must be true")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


def _validate_exact_keys(
    value: dict[str, Any],
    expected_keys: set[str],
    context: str,
    blockers: list[str],
) -> None:
    extra = sorted(set(value) - expected_keys)
    missing = sorted(expected_keys - set(value))
    if extra:
        blockers.append(_unknown_keys_message(context, extra))
    if missing:
        blockers.append(f"{context} missing keys: " + ", ".join(missing))


def _validate_safe_outputs(safe_outputs: dict[str, Any], blockers: list[str]) -> None:
    required_keys = {
        "asset_id_hash",
        "ingestion_job_id_hash",
        "mail_evidence_bundle_id_hash",
        "mail_import_session_id_hash",
        "observation_count",
        "owner_query_status",
        "denied_query_status",
        "forged_query_status",
        "trusted_query_status",
        "wrong_owner_query_status",
        "owner_citation_count",
        "owner_case_progress_status",
        "bundle_case_progress_status",
        "denied_case_progress_status",
        "forged_case_progress_status",
        "trusted_case_progress_status",
        "owner_case_progress_citation_count",
        "response_hashes",
        "transcript",
    }
    extra = sorted(set(safe_outputs) - required_keys)
    if extra:
        blockers.append(_unknown_keys_message("safe_outputs", extra))
    missing = sorted(required_keys - set(safe_outputs))
    if missing:
        blockers.append("safe_outputs missing keys: " + ", ".join(missing))
    for key in (
        "asset_id_hash",
        "ingestion_job_id_hash",
        "mail_evidence_bundle_id_hash",
        "mail_import_session_id_hash",
    ):
        value = safe_outputs.get(key)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
    response_hashes = safe_outputs.get("response_hashes")
    if not isinstance(response_hashes, list) or not response_hashes:
        blockers.append("safe_outputs.response_hashes must be a non-empty list")
    elif not all(
        isinstance(item, str) and _SHA256_RE.fullmatch(item) is not None for item in response_hashes
    ):
        blockers.append("safe_outputs.response_hashes must contain sha256 hashes")
    elif len(set(response_hashes)) != len(response_hashes):
        blockers.append("safe_outputs.response_hashes must be distinct")
    transcript = safe_outputs.get("transcript")
    if not isinstance(transcript, list) or not transcript:
        blockers.append("safe_outputs.transcript must be a non-empty list")
    else:
        for entry in transcript:
            if not isinstance(entry, dict) or set(entry) != {
                "method",
                "request_hash",
                "response_hash",
                "status",
            }:
                blockers.append("safe_outputs.transcript must be hash-only")
                break
            if (
                not isinstance(entry.get("request_hash"), str)
                or _SHA256_RE.fullmatch(entry["request_hash"]) is None
                or not isinstance(entry.get("response_hash"), str)
                or _SHA256_RE.fullmatch(entry["response_hash"]) is None
            ):
                blockers.append("safe_outputs.transcript hashes must be sha256 hashes")
                break
    expected_statuses = {
        "owner_query_status": "ok",
        "denied_query_status": "permission_denied",
        "forged_query_status": "error",
        "trusted_query_status": "ok",
        "wrong_owner_query_status": "permission_denied",
        "owner_case_progress_status": "ok",
        "bundle_case_progress_status": "ok",
        "denied_case_progress_status": "permission_denied",
        "forged_case_progress_status": "error",
        "trusted_case_progress_status": "ok",
    }
    for key, expected in expected_statuses.items():
        if safe_outputs.get(key) != expected:
            blockers.append(f"safe_outputs.{key} must be {expected}")
    observation_count = safe_outputs.get("observation_count")
    if not _is_positive_int(observation_count):
        blockers.append("safe_outputs.observation_count must be positive")
    owner_citation_count = safe_outputs.get("owner_citation_count")
    if not _is_positive_int(owner_citation_count):
        blockers.append("safe_outputs.owner_citation_count must be positive")
    case_progress_citation_count = safe_outputs.get("owner_case_progress_citation_count")
    if not _is_positive_int(case_progress_citation_count):
        blockers.append("safe_outputs.owner_case_progress_citation_count must be positive")


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _reject_body_or_snippet_fields(value: Any, blockers: list[str], path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "_", key_text.lower()).strip("_")
            if {"body", "snippet", "content", "text"} & set(normalized.split("_")):
                item_path = f"{path}.{key_text}" if path else key_text
                blockers.append(
                    "public report contains evidence text field: " + sha256_json(item_path)
                )
                return
            _reject_body_or_snippet_fields(
                item,
                blockers,
                f"{path}.{key_text}" if path else key_text,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_body_or_snippet_fields(item, blockers, f"{path}[{index}]")


def _synthetic_body_fragments() -> tuple[str, ...]:
    return (
        "Update: Launch reviewed",
        "Blocker: Waiting on audit approval",
        "Waiting on audit approval",
    )


def _unknown_keys_message(context: str, keys: list[str]) -> str:
    return f"{context} contains unknown keys: " f"count={len(keys)} hash={sha256_json(keys)}"


def _prepare_work_dir(work_dir: Path) -> None:
    sentinel = work_dir / SMOKE_SENTINEL
    if work_dir.exists() and not sentinel.exists():
        raise ValueError("mail evidence smoke work-dir already exists without the smoke sentinel")
    if work_dir.exists():
        for child in work_dir.iterdir():
            if child.name == SMOKE_SENTINEL:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    else:
        work_dir.mkdir(parents=True)
    sentinel.write_text("formowl mail evidence mcp smoke\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--validate-report", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.validate_report is not None:
        report = json.loads(args.validate_report.read_text(encoding="utf-8"))
        validation = validate_report(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
        return 0 if validation["passed"] else 1

    work_dir = args.work_dir or _default_work_dir()
    report = run_mail_evidence_mcp_smoke(work_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["validation"]["passed"] else 1


def _default_work_dir() -> Path:
    return Path(tempfile.gettempdir()) / f"formowl-mail-evidence-smoke-{uuid.uuid4().hex}"


def _jsonrpc_gateway(
    bundle: Any,
    *,
    actor_user_id: str,
    session_id: str,
    trusted_grants: list[Grant] | None = None,
) -> SemanticMcpJsonRpcGateway:
    return SemanticMcpJsonRpcGateway(
        semantic_gateway=SemanticMcpGateway(
            mail_evidence_handler=build_mail_evidence_query_handler(
                [bundle],
                grants=trusted_grants or [],
                now=NOW,
            ),
            mail_case_progress_handler=build_mail_case_progress_handler(
                [bundle],
                grants=trusted_grants or [],
                now=NOW,
                generated_at=NOW,
            ),
        ),
        session=SemanticGatewaySession(
            session_id=session_id,
            actor_user_id=actor_user_id,
            workspace_id=WORKSPACE_ID,
        ),
    )


def _call_query(
    gateway: SemanticMcpJsonRpcGateway,
    *,
    request_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return gateway.handle_json_rpc(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "query_mail_evidence", "arguments": arguments},
        }
    )


def _call_case_progress(
    gateway: SemanticMcpJsonRpcGateway,
    *,
    request_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return gateway.handle_json_rpc(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "answer_mail_case_progress", "arguments": arguments},
        }
    )


def _tool_payload(response: dict[str, Any]) -> dict[str, Any]:
    return response["result"]["content"][0]["json"]


def _ok_with_citation(payload: dict[str, Any]) -> bool:
    return (
        payload.get("status") == "ok"
        and bool(payload.get("data", {}).get("evidence_snippets"))
        and bool(payload.get("data", {}).get("citations"))
    )


def _denied_without_content(payload: dict[str, Any]) -> bool:
    return (
        payload.get("status") == "permission_denied"
        and payload.get("data", {}).get("evidence_snippets") == []
        and payload.get("data", {}).get("citations") == []
        and "Waiting on audit approval" not in str(payload)
    )


def _safe_unsafe_tool_rejection_without_content(payload: dict[str, Any]) -> bool:
    data = payload.get("data", {})
    return (
        payload.get("status") == "error"
        and data.get("error_code") == "unsafe_tool_payload"
        and "evidence_snippets" not in data
        and "citations" not in data
        and "latest_updates" not in data
        and "blockers" not in data
        and "Waiting on audit approval" not in str(payload)
    )


def _case_progress_ok_with_citation(payload: dict[str, Any]) -> bool:
    data = payload.get("data", {})
    return (
        payload.get("status") == "ok"
        and bool(data.get("blockers"))
        and bool(data.get("citations"))
        and data.get("claim_boundary", {}).get("supports_mail_case_progress_answer_claim") is True
    )


def _case_progress_denied_without_content(payload: dict[str, Any]) -> bool:
    data = payload.get("data", {})
    return (
        payload.get("status") == "permission_denied"
        and data.get("latest_updates") == []
        and data.get("blockers") == []
        and data.get("responsible_parties") == []
        and data.get("next_actions") == []
        and data.get("deadlines") == []
        and data.get("citations") == []
        and "Waiting on audit approval" not in str(payload)
    )


def _trusted_mail_grant(
    bundle: Any,
    *,
    owner_user_id: str = OWNER_USER_ID,
) -> Grant:
    return Grant(
        grant_id="grant_mail_smoke_user_other",
        owner_user_id=owner_user_id,
        grantee_user_id=OTHER_USER_ID,
        scope_type="mail_import_session",
        scope_id=bundle.mail_import_session.mail_import_session_id,
        permission="evidence_snippet",
        expires_at="2026-07-06T00:00:00+00:00",
    )


def _mail_archive() -> dict[str, Any]:
    return {
        "archive_id": "archive_launch",
        "mailbox_id": "mailbox_yifan",
        "folders": [{"folder_path_hash": "sha256:folder-inbox", "label": "Inbox"}],
        "messages": [
            {
                "message_id": "<launch-001@example.test>",
                "thread_id": "thread_launch",
                "folder_path_hash": "sha256:folder-inbox",
                "subject": "Launch checklist",
                "sender": "pm@example.test",
                "sent_at": NOW,
                "body": "Update: Launch reviewed\n\nBlocker: Waiting on audit approval",
                "body_hash": "sha256:body-launch",
            }
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
