#!/usr/bin/env python3
"""Run or validate the FormOwl closed-beta readiness smoke.

This smoke uses synthetic internal fixtures to exercise the current backbone
surface for a trusted closed beta. It verifies JSON-RPC gateway behavior,
storage config redaction, worker-backed ingestion, permissioned retrieval,
the KG-eval package facade, and proposal-only wiki output. It does not claim
production readiness, live database readiness, automatic publishing, raw asset
content access, canonical graph writes, or mail adapter readiness.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any
import uuid

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_auth import FileAuditLogStore  # noqa: E402
from formowl_contract import Grant, PermissionScope, SourceRef, sha256_json  # noqa: E402
from formowl_gateway import (  # noqa: E402
    McpServerJsonRpcGateway,
    SemanticGatewaySession,
    validate_public_gateway_payload,
)
from formowl_graph.index import (  # noqa: E402
    FileGraphProjectionStore,
    FileVectorStore,
    GraphProjectionNode,
    VectorRecord,
)
from formowl_ingestion.assets import register_asset_from_local_file  # noqa: E402
from formowl_ingestion.extractors import PlainTextObservationExtractor  # noqa: E402
from formowl_ingestion.jobs import create_ingestion_job  # noqa: E402
from formowl_ingestion.observations import (  # noqa: E402
    build_context_package_from_text_observations,
)
from formowl_ingestion.storage import (  # noqa: E402
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
    StorageBackendConfig,
    StorageBackendRegistry,
    configure_storage_backend_registry,
)
from formowl_kg_eval import build_acceptance_summary, run_kg_eval_command  # noqa: E402
from formowl_project_mcp import create_default_server as create_project_server  # noqa: E402
from formowl_retrieval import RetrievalGateway  # noqa: E402
from formowl_wiki_mcp import create_default_server as create_wiki_server  # noqa: E402
from formowl_worker import IngestionWorker  # noqa: E402


DEFAULT_OUTPUT = Path("/tmp/formowl-closed-beta-smoke.json")
CREATED_AT = "2026-06-29T00:00:00+00:00"
NOW = "2026-06-29T00:00:00+00:00"
WORKSPACE_ID = "workspace_closed_beta"
PROJECT_ID = "project_closed_beta"
ACTOR_USER_ID = "user_closed_beta_pm"
SESSION_ID = "session_closed_beta_smoke"
WORKER_ID = "worker_closed_beta"

REQUIRED_TRUE_METRICS = [
    "containerized_smoke_executed",
    "storage_backend_registry_configured",
    "storage_public_envelope_redacted",
    "project_jsonrpc_initialized",
    "project_jsonrpc_tools_listed",
    "project_context_snapshot_created",
    "wiki_jsonrpc_draft_generated",
    "wiki_publish_proposal_only",
    "jsonrpc_hash_only_transcripts",
    "worker_ingestion_executed",
    "worker_job_succeeded",
    "observation_persisted",
    "worker_result_no_raw_internal_leak",
    "observation_context_package_built",
    "observation_context_wiki_draft_generated",
    "retrieval_gateway_executed",
    "retrieval_grant_check_before_content",
    "retrieval_evidence_visible_after_grant",
    "raw_asset_requires_explicit_grant",
    "raw_asset_ref_returns_formowl_locator",
    "raw_asset_ref_returns_no_content",
    "kg_eval_commands_refreshed",
    "kg_eval_facade_summary_loaded",
    "kg_eval_facade_boundary_respected",
    "public_outputs_validated",
    "safe_output_no_raw_internal_leak",
    "no_canonical_writes",
    "automatic_publish_not_performed",
    "closed_beta_smoke_passed",
]
REQUIRED_FALSE_METRICS = [
    "raw_asset_content_returned",
    "raw_storage_path_exposed",
    "live_database_required",
    "mail_adapter_exercised",
    "canonical_graph_write_performed",
]
REQUIRED_TRUE_CLAIMS = [
    "supports_trusted_internal_closed_beta_baseline_smoke_claim",
    "supports_containerized_closed_beta_smoke_claim",
]
FORBIDDEN_TRUE_CLAIMS = [
    "supports_production_ready_claim",
    "supports_live_database_readiness_claim",
    "supports_automatic_publishing_claim",
    "supports_raw_asset_content_access_claim",
    "supports_canonical_graph_write_claim",
    "supports_mail_adapter_readiness_claim",
    "supports_enterprise_scale_claim",
    "supports_top_tier_scientific_validation_claim",
]

FORBIDDEN_PUBLIC_KEYS = {
    "absolute_path",
    "bucket",
    "connection_string",
    "database_url",
    "debug_path",
    "dsn",
    "filesystem_path",
    "internal_backend_id",
    "internal_endpoint",
    "internal_sql",
    "internal_url",
    "nas_path",
    "object_key",
    "object_store_key",
    "parser_debug",
    "presigned_url",
    "raw_path",
    "secret",
    "signed_url",
    "sql",
    "stack_trace",
    "storage_key",
    "token",
    "traceback",
    "worker_scratch",
}
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"(^|[\"'\s])/(srv|home|tmp|var|mnt|opt|root|workspace)/", re.IGNORECASE),
    re.compile(r"\b[A-Za-z]:\\"),
    re.compile(
        r"\b(file|smb|nfs|s3|minio|gs|azure|postgres|postgresql|mysql|sqlite)://",
        re.IGNORECASE,
    ),
    re.compile(r"\b(select|with|copy|insert|update|delete|drop|alter)\b\s+", re.IGNORECASE),
    re.compile(r"\bTraceback \(most recent call last\):", re.IGNORECASE),
)


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def build_report() -> dict[str, Any]:
    try:
        with _temporary_smoke_dir() as temp_dir:
            initial_inventory = _workspace_file_inventory(temp_dir)

            storage = _storage_smoke(temp_dir)
            project_wiki = _project_wiki_jsonrpc_smoke(temp_dir)
            worker = _worker_ingestion_smoke(temp_dir, storage)
            retrieval = _retrieval_smoke(temp_dir, worker["asset_id"])
            observation_wiki = _observation_wiki_smoke(
                temp_dir=temp_dir,
                observations=worker["observations"],
                assets=worker["assets"],
                extractor_runs=worker["extractor_runs"],
            )
            final_inventory = _workspace_file_inventory(temp_dir)
            unexpected_canonical_artifacts = _unexpected_canonical_artifact_paths(final_inventory)

        kg_eval = _kg_eval_smoke()

        safe_outputs = {
            "storage": storage["safe_output"],
            "jsonrpc": project_wiki["safe_output"],
            "worker_ingestion": worker["safe_output"],
            "observation_wiki_bridge": observation_wiki["safe_output"],
            "retrieval": retrieval["safe_output"],
            "kg_eval": kg_eval["safe_output"],
            "state_verification": {
                "initial_file_count": len(initial_inventory),
                "final_file_count": len(final_inventory),
                "canonical_artifact_unexpected_count": len(unexpected_canonical_artifacts),
                "canonical_artifact_unexpected_paths": unexpected_canonical_artifacts,
            },
        }
        validate_public_gateway_payload(safe_outputs)

        metrics = {
            "containerized_smoke_executed": _is_containerized(),
            **storage["metrics"],
            **project_wiki["metrics"],
            **worker["metrics"],
            **observation_wiki["metrics"],
            **retrieval["metrics"],
            **kg_eval["metrics"],
            "public_outputs_validated": True,
            "safe_output_no_raw_internal_leak": not _contains_forbidden_text(safe_outputs),
            "no_canonical_writes": not unexpected_canonical_artifacts,
            "automatic_publish_not_performed": project_wiki["metrics"][
                "wiki_publish_proposal_only"
            ],
            "raw_asset_content_returned": retrieval["metrics"]["raw_asset_content_returned"],
            "raw_storage_path_exposed": False,
            "live_database_required": False,
            "mail_adapter_exercised": False,
            "canonical_graph_write_performed": False,
        }
        metrics["closed_beta_smoke_passed"] = all(
            bool(metrics.get(key))
            for key in REQUIRED_TRUE_METRICS
            if key != "closed_beta_smoke_passed"
        ) and all(metrics.get(key) is False for key in REQUIRED_FALSE_METRICS)

        claim_boundary = {
            "supports_trusted_internal_closed_beta_baseline_smoke_claim": metrics[
                "closed_beta_smoke_passed"
            ],
            "supports_containerized_closed_beta_smoke_claim": metrics["closed_beta_smoke_passed"],
            "supports_production_ready_claim": False,
            "supports_live_database_readiness_claim": False,
            "supports_automatic_publishing_claim": False,
            "supports_raw_asset_content_access_claim": False,
            "supports_canonical_graph_write_claim": False,
            "supports_mail_adapter_readiness_claim": False,
            "supports_enterprise_scale_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        }
        report = {
            "artifact_id": "formowl_closed_beta_readiness_smoke_v1",
            "run_id": os.environ.get(
                "FORMOWL_CLOSED_BETA_SMOKE_RUN_ID",
                f"formowl-closed-beta-smoke-{uuid.uuid4().hex[:12]}",
            ),
            "repo_reference": "main_repo_workspace",
            "repo_path_redacted": True,
            "image_reference": os.environ.get("FORMOWL_CLOSED_BETA_SMOKE_IMAGE", "unknown"),
            "runner_script_sha256": sha256_file(Path(__file__)),
            "input_manifest": {
                "fixture": "formowl_closed_beta_synthetic_fixture_v1",
                "created_at": CREATED_AT,
                "now": NOW,
            },
            "input_manifest_sha256": sha256_json(
                {
                    "fixture": "formowl_closed_beta_synthetic_fixture_v1",
                    "created_at": CREATED_AT,
                    "now": NOW,
                }
            ),
            "output_manifest_sha256": sha256_json(safe_outputs),
            "safe_outputs": safe_outputs,
            "metrics": metrics,
            "claim_boundary": claim_boundary,
            "blockers": [
                "synthetic fixtures only",
                "trusted internal closed-beta identity only",
                "no live database readiness claim",
                "no automatic wiki publishing",
                "no raw asset content access",
                "no canonical graph writes",
                "mail adapter readiness is excluded",
            ],
        }
        return report
    except Exception as exc:  # pragma: no cover - environment failure path.
        return {
            "artifact_id": "formowl_closed_beta_readiness_smoke_v1",
            "repo_reference": "main_repo_workspace",
            "repo_path_redacted": True,
            "metrics": {
                "containerized_smoke_executed": _is_containerized(),
                "closed_beta_smoke_passed": False,
                "raw_asset_content_returned": False,
                "raw_storage_path_exposed": False,
                "live_database_required": False,
                "mail_adapter_exercised": False,
                "canonical_graph_write_performed": False,
            },
            "error_type": type(exc).__name__,
            "error_message": _safe_error_message(str(exc)),
            "claim_boundary": {
                "supports_trusted_internal_closed_beta_baseline_smoke_claim": False,
                "supports_containerized_closed_beta_smoke_claim": False,
                "supports_production_ready_claim": False,
                "supports_live_database_readiness_claim": False,
                "supports_automatic_publishing_claim": False,
                "supports_raw_asset_content_access_claim": False,
                "supports_canonical_graph_write_claim": False,
                "supports_mail_adapter_readiness_claim": False,
                "supports_enterprise_scale_claim": False,
                "supports_top_tier_scientific_validation_claim": False,
            },
            "blockers": ["closed beta smoke failed before a valid public report was built"],
        }


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    metrics = report.get("metrics", {})
    claims = report.get("claim_boundary", {})
    safe_outputs = report.get("safe_outputs", {})

    if report.get("artifact_id") != "formowl_closed_beta_readiness_smoke_v1":
        blockers.append("unexpected artifact id")
    if report.get("repo_path_redacted") is not True:
        blockers.append("repo path must be redacted")
    if not isinstance(metrics, dict):
        blockers.append("metrics must be an object")
        metrics = {}
    if not isinstance(claims, dict):
        blockers.append("claim boundary must be an object")
        claims = {}

    for key in REQUIRED_TRUE_METRICS:
        if metrics.get(key) is not True:
            blockers.append(f"required metric failed or missing: {key}")
    for key in REQUIRED_FALSE_METRICS:
        if metrics.get(key) is not False:
            blockers.append(f"unexpected safety metric: {key}")
    for key in REQUIRED_TRUE_CLAIMS:
        if claims.get(key) is not True:
            blockers.append(f"required claim false: {key}")
    for key in FORBIDDEN_TRUE_CLAIMS:
        if claims.get(key) is not False:
            blockers.append(f"forbidden claim true: {key}")

    if metrics.get("observation_count", 0) < 1:
        blockers.append("worker ingestion did not persist observations")
    if metrics.get("retrieval_evidence_snippet_count", 0) < 1:
        blockers.append("retrieval did not expose granted evidence snippets")
    if metrics.get("raw_asset_ref_count", 0) < 1:
        blockers.append("raw-asset reference payload was not exercised")
    if metrics.get("jsonrpc_transcript_entry_count", 0) < 5:
        blockers.append("JSON-RPC transcript coverage was too small")
    if metrics.get("kg_eval_remaining_gate_count") not in {0, "0"}:
        blockers.append("KG-eval facade reports remaining gates")
    if metrics.get("canonical_artifact_unexpected_count", 0) != 0:
        blockers.append("unexpected canonical graph artifact was written")
    try:
        validate_public_gateway_payload(safe_outputs)
    except Exception:
        blockers.append("safe outputs are not valid public gateway payloads")
    if _contains_forbidden_text(report):
        blockers.append("public artifact leaks raw paths, SQL, or internal values")

    return {
        "passed": not blockers,
        "blockers": blockers,
        "metrics": metrics,
        "claim_boundary": claims,
    }


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_markdown(report: dict[str, Any], validation: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# FormOwl Closed-Beta Readiness Smoke",
        "",
        "This validates a synthetic trusted-internal closed-beta baseline path through the current FormOwl backbone.",
        "It is not production readiness and does not claim live DB readiness, automatic publishing, raw asset content access, canonical graph writes, or mail adapter readiness.",
        "",
        f"- Passed: {validation['passed']}",
        f"- Artifact: {output_path.name}",
        f"- Closed-beta smoke passed: {validation['metrics'].get('closed_beta_smoke_passed')}",
        f"- Containerized: {validation['metrics'].get('containerized_smoke_executed')}",
        "",
        "## Metrics",
        "",
    ]
    for key, value in sorted(validation["metrics"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Claim Boundary", ""])
    for key, value in sorted(validation["claim_boundary"].items()):
        lines.append(f"- {key}: {value}")
    if validation["blockers"]:
        lines.extend(["", "## Blockers", ""])
        for blocker in validation["blockers"]:
            lines.append(f"- {blocker}")
    output_path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _storage_smoke(temp_dir: Path) -> dict[str, Any]:
    registry = StorageBackendRegistry(temp_dir)
    backend = configure_storage_backend_registry(
        registry,
        [
            StorageBackendConfig(
                type="local_fs",
                storage_backend_id="storage_closed_beta_local",
                workspace_scope=WORKSPACE_ID,
                display_name="Closed beta local object backend",
                root_path=temp_dir / "object-root",
                allowed_workers=(WORKER_ID,),
            )
        ],
    )[0]
    envelope = registry.backend_mcp_envelope(backend.storage_backend_id)
    validate_public_gateway_payload(envelope)
    rendered = json.dumps(envelope, sort_keys=True)
    local_root = registry.resolve_local_root(backend.storage_backend_id)
    redacted = (
        local_root is not None
        and str(local_root) not in rendered
        and "object-root" not in rendered
        and "internal_endpoint" not in rendered
    )
    return {
        "registry": registry,
        "backend": backend,
        "safe_output": {
            "backend_status": envelope["status"],
            "backend": envelope["data"]["backend"],
            "private_root_returned": False,
        },
        "metrics": {
            "storage_backend_registry_configured": backend.storage_backend_id
            == "storage_closed_beta_local",
            "storage_public_envelope_redacted": redacted,
        },
    }


def _project_wiki_jsonrpc_smoke(temp_dir: Path) -> dict[str, Any]:
    session = SemanticGatewaySession(
        session_id=SESSION_ID,
        actor_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
    )
    project_gateway = McpServerJsonRpcGateway(
        create_project_server(temp_dir),
        session=session,
    )
    wiki_gateway = McpServerJsonRpcGateway(
        create_wiki_server(temp_dir),
        session=session,
    )
    project_init = project_gateway.handle_json_rpc(
        {"jsonrpc": "2.0", "id": "project_init", "method": "initialize"}
    )
    project_tools = project_gateway.handle_json_rpc(
        {"jsonrpc": "2.0", "id": "project_tools", "method": "tools/list"}
    )
    project_context_response = project_gateway.handle_json_rpc(
        {
            "jsonrpc": "2.0",
            "id": "project_context",
            "method": "tools/call",
            "params": {
                "name": "get_work_item_context",
                "arguments": {
                    "source_ref": {
                        "source_system": "openproject",
                        "source_type": "work_package",
                        "source_id": "123",
                    },
                    "include_comments": True,
                    "include_activities": True,
                    "include_relations": True,
                    "include_attachments": True,
                    "create_evidence_snapshot": True,
                },
            },
        }
    )
    project_context = _tool_envelope(project_context_response)
    wiki_init = wiki_gateway.handle_json_rpc(
        {"jsonrpc": "2.0", "id": "wiki_init", "method": "initialize"}
    )
    wiki_draft_response = wiki_gateway.handle_json_rpc(
        {
            "jsonrpc": "2.0",
            "id": "wiki_draft",
            "method": "tools/call",
            "params": {
                "name": "generate_wiki_draft",
                "arguments": {
                    "page_type": "adr",
                    "title": "Closed Beta JSON-RPC Draft",
                    "context_package": project_context["context_package"],
                },
            },
        }
    )
    wiki_draft = _tool_envelope(wiki_draft_response)
    publish_response = wiki_gateway.handle_json_rpc(
        {
            "jsonrpc": "2.0",
            "id": "wiki_publish",
            "method": "tools/call",
            "params": {
                "name": "publish_wiki_page",
                "arguments": {
                    "draft_id": wiki_draft["data"]["draft_id"],
                    "target": {
                        "target_system": "openproject_wiki",
                        "project_id": PROJECT_ID,
                        "page_slug": "closed-beta-jsonrpc-draft",
                    },
                    "require_review": True,
                },
            },
        }
    )
    publish = _tool_envelope(publish_response)
    transcripts = [*project_gateway.leak_transcript(), *wiki_gateway.leak_transcript()]
    transcript_text = json.dumps(transcripts, sort_keys=True)
    tool_names = {tool["name"] for tool in project_tools["result"]["tools"]}
    wiki_publish_proposal_only = (
        publish["status"] == "pending_review"
        and "published_at" not in json.dumps(publish, sort_keys=True).lower()
    )
    return {
        "safe_output": {
            "project_server": project_init["result"]["serverInfo"]["name"],
            "project_tool_count": len(tool_names),
            "project_context_status": project_context["status"],
            "project_evidence_snapshot_count": len(project_context["evidence_snapshot_ids"]),
            "wiki_server": wiki_init["result"]["serverInfo"]["name"],
            "wiki_draft_status": wiki_draft["status"],
            "wiki_draft_id": wiki_draft["data"]["draft_id"],
            "publish_status": publish["status"],
            "transcript_entry_count": len(transcripts),
        },
        "metrics": {
            "project_jsonrpc_initialized": project_init["result"]["protocolVersion"]
            == "2024-11-05",
            "project_jsonrpc_tools_listed": "get_work_item_context" in tool_names,
            "project_context_snapshot_created": project_context["status"] == "ok"
            and len(project_context["evidence_snapshot_ids"]) == 1,
            "wiki_jsonrpc_draft_generated": _wiki_draft_is_draft(wiki_draft),
            "wiki_publish_proposal_only": wiki_publish_proposal_only,
            "jsonrpc_hash_only_transcripts": _hash_only_transcripts(transcripts)
            and "reviewable ADR" not in transcript_text,
            "jsonrpc_transcript_entry_count": len(transcripts),
        },
    }


def _worker_ingestion_smoke(temp_dir: Path, storage: dict[str, Any]) -> dict[str, Any]:
    source_path = temp_dir / "incoming" / "closed_beta_notes.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        "Closed beta smoke validates FormOwl backbone readiness.\n\n"
        "The fixture must remain synthetic and proposal-only.\n",
        encoding="utf-8",
    )
    asset_store = AssetStore(temp_dir)
    job_store = JobStore(temp_dir)
    extractor_run_store = ExtractorRunStore(temp_dir)
    observation_store = ObservationStore(temp_dir)
    object_store = FileObjectStore(storage["registry"])
    asset = register_asset_from_local_file(
        source_path,
        object_store=object_store,
        asset_store=asset_store,
        storage_backend_id=storage["backend"].storage_backend_id,
        workspace_id=WORKSPACE_ID,
        owner_user_id=ACTOR_USER_ID,
        permission_scope=PermissionScope.project(PROJECT_ID),
        source_ref=SourceRef(
            source_system="formowl",
            source_type="closed_beta_fixture",
            source_id="closed_beta_notes",
            source_key="closed_beta_notes",
        ),
        mime_type="text/plain",
        created_at=CREATED_AT,
        registered_at=CREATED_AT,
    )
    job = create_ingestion_job(
        asset=asset,
        job_store=job_store,
        requested_by=ACTOR_USER_ID,
        extractor_names=["plain_text_extractor"],
        created_at=CREATED_AT,
    )
    worker = IngestionWorker(
        worker_id=WORKER_ID,
        asset_store=asset_store,
        job_store=job_store,
        object_store=object_store,
        extractor_run_store=extractor_run_store,
        observation_store=observation_store,
        extractor_adapters=[PlainTextObservationExtractor()],
    )
    worker_result = worker.run_once(started_at=NOW, completed_at=NOW)
    completed_job = job_store.get(job.ingestion_job_id)
    observations = observation_store.list()
    extractor_runs = extractor_run_store.list()
    rendered_result = json.dumps(worker_result.to_dict(), sort_keys=True)
    no_raw_leak = (
        str(source_path) not in rendered_result
        and "object-root" not in rendered_result
        and not _contains_forbidden_text(worker_result.to_dict())
    )
    return {
        "asset_id": asset.asset_id,
        "assets": [asset],
        "observations": observations,
        "extractor_runs": extractor_runs,
        "safe_output": {
            "asset_id": asset.asset_id,
            "ingestion_job_id": job.ingestion_job_id,
            "job_status": completed_job.status if completed_job is not None else "missing",
            "worker_id": worker_result.worker_id,
            "processed_job_count": len(worker_result.processed_job_ids),
            "succeeded_job_count": len(worker_result.succeeded_job_ids),
            "observation_count": len(observations),
            "extractor_run_count": len(extractor_runs),
        },
        "metrics": {
            "worker_ingestion_executed": worker_result.processed_job_ids == [job.ingestion_job_id],
            "worker_job_succeeded": completed_job is not None
            and completed_job.status == "succeeded",
            "observation_persisted": len(observations) >= 1,
            "worker_result_no_raw_internal_leak": no_raw_leak,
            "observation_count": len(observations),
        },
    }


def _observation_wiki_smoke(
    *,
    temp_dir: Path,
    observations: list[Any],
    assets: list[Any],
    extractor_runs: list[Any],
) -> dict[str, Any]:
    context_package = build_context_package_from_text_observations(
        observations,
        assets=assets,
        extractor_runs=extractor_runs,
        title="Closed Beta Smoke Observations",
    )
    wiki_gateway = McpServerJsonRpcGateway(
        create_wiki_server(temp_dir),
        session=SemanticGatewaySession(
            session_id=SESSION_ID,
            actor_user_id=ACTOR_USER_ID,
            workspace_id=WORKSPACE_ID,
        ),
    )
    draft_response = wiki_gateway.handle_json_rpc(
        {
            "jsonrpc": "2.0",
            "id": "observation_wiki_draft",
            "method": "tools/call",
            "params": {
                "name": "generate_wiki_draft",
                "arguments": {
                    "page_type": "meeting-notes",
                    "title": "Closed Beta Observation Draft",
                    "context_package": context_package.to_dict(),
                },
            },
        }
    )
    draft = _tool_envelope(draft_response)
    return {
        "safe_output": {
            "context_package_id": context_package.context_package_id,
            "context_type": context_package.context_type,
            "draft_status": draft["status"],
            "draft_id": draft["data"]["draft_id"],
            "citation_count": len(draft["citations"]),
        },
        "metrics": {
            "observation_context_package_built": context_package.context_type
            == "text_observation_context",
            "observation_context_wiki_draft_generated": _wiki_draft_is_draft(draft),
        },
    }


def _retrieval_smoke(temp_dir: Path, asset_id: str) -> dict[str, Any]:
    vector_store = FileVectorStore(temp_dir)
    graph_store = FileGraphProjectionStore(temp_dir)
    permission_scope = PermissionScope.project(PROJECT_ID).to_dict()
    vector_store.create(
        VectorRecord(
            vector_id="vec_closed_beta_visible",
            source_type="observation",
            source_id="obs_closed_beta_visible",
            source_content_hash="sha256:vec_closed_beta_visible",
            embedding_model="closed-beta-smoke-embedding-v1",
            embedding=[1.0, 0.0],
            permission_scope=permission_scope,
            metadata={
                "answer_summary": "Closed beta backbone smoke evidence",
                "evidence_snippet": "Closed beta smoke evidence is visible after grant.",
                "asset_locator": f"formowl://asset/{asset_id}",
            },
        )
    )
    graph_store.create_node(
        GraphProjectionNode(
            node_id="node_closed_beta_visible",
            source_type="candidate_atom",
            source_id="catom_closed_beta_visible",
            labels=["closed_beta"],
            properties={"summary": "Closed beta graph projection is visible after grant."},
            permission_scope=permission_scope,
            projection_state="ready",
        )
    )
    gateway = RetrievalGateway(
        vector_store=vector_store,
        graph_projection_store=graph_store,
        audit_store=FileAuditLogStore(temp_dir),
    )
    denied = gateway.query_effective_graph(
        query_embedding=[1.0, 0.0],
        query_text="closed beta backbone",
        requester_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
        session_id=SESSION_ID,
        grants=[],
        mode="evidence_snippet",
        now=NOW,
    ).to_dict()
    allowed = gateway.query_effective_graph(
        query_embedding=[1.0, 0.0],
        query_text="closed beta backbone",
        requester_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
        session_id=SESSION_ID,
        grants=[_project_grant()],
        mode="evidence_snippet",
        now=NOW,
    ).to_dict()
    raw_denied = gateway.query_effective_graph(
        query_embedding=[1.0, 0.0],
        query_text="closed beta backbone",
        requester_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
        session_id=SESSION_ID,
        grants=[_project_grant()],
        mode="raw_asset",
        now=NOW,
    ).to_dict()
    raw_allowed = gateway.query_effective_graph(
        query_embedding=[1.0, 0.0],
        query_text="closed beta backbone",
        requester_user_id=ACTOR_USER_ID,
        workspace_id=WORKSPACE_ID,
        session_id=SESSION_ID,
        grants=[_project_grant(), _project_grant(permission="asset_scoped_access")],
        mode="raw_asset",
        now=NOW,
    ).to_dict()
    raw_asset_refs = raw_allowed["raw_asset_refs"]
    return {
        "safe_output": {
            "denied_status": denied["status"],
            "denied_evidence_count": len(denied["evidence_snippets"]),
            "allowed_evidence_source_ids": [
                item["source_id"] for item in allowed["evidence_snippets"]
            ],
            "raw_denied_status": raw_denied["status"],
            "raw_asset_refs": raw_asset_refs,
        },
        "metrics": {
            "retrieval_gateway_executed": True,
            "retrieval_grant_check_before_content": denied["evidence_snippets"] == [],
            "retrieval_evidence_visible_after_grant": bool(allowed["evidence_snippets"]),
            "retrieval_evidence_snippet_count": len(allowed["evidence_snippets"]),
            "raw_asset_requires_explicit_grant": raw_denied["status"] == "permission_denied",
            "raw_asset_ref_returns_formowl_locator": bool(raw_asset_refs)
            and all(
                str(ref.get("asset_locator", "")).startswith("formowl://asset/")
                for ref in raw_asset_refs
            ),
            "raw_asset_ref_returns_no_content": bool(raw_asset_refs)
            and all(ref.get("content_returned") is False for ref in raw_asset_refs),
            "raw_asset_content_returned": any(
                ref.get("content_returned") is not False for ref in raw_asset_refs
            ),
            "raw_asset_ref_count": len(raw_asset_refs),
        },
    }


def _kg_eval_smoke() -> dict[str, Any]:
    command_results = [
        run_kg_eval_command(command, repository_root=ROOT)
        for command in ("total", "objective", "preflight", "work-orders", "progress")
    ]
    summary = build_acceptance_summary(repository_root=ROOT)
    integration_boundary = summary.get("integration_boundary", {})
    remaining_gate_count = len(summary.get("remaining_evidence", {}).get("remaining_gates", []))
    return {
        "safe_output": {
            "artifact_id": summary.get("artifact_id"),
            "command_returncodes": {
                result.command: result.returncode for result in command_results
            },
            "total_acceptance_overall_passed": summary.get("total_acceptance", {}).get(
                "overall_passed"
            ),
            "remaining_gate_count": remaining_gate_count,
            "system_agent_should_call": integration_boundary.get("system_agent_should_call"),
            "raw_backend_surfaces_exposed": integration_boundary.get(
                "raw_backend_surfaces_exposed"
            ),
        },
        "metrics": {
            "kg_eval_commands_refreshed": all(result.passed for result in command_results),
            "kg_eval_facade_summary_loaded": summary.get("artifact_id")
            == "formowl_kg_eval_acceptance_summary_v1",
            "kg_eval_facade_boundary_respected": integration_boundary.get(
                "system_agent_should_call"
            )
            == "formowl-kg-eval summary"
            and integration_boundary.get("raw_backend_surfaces_exposed") is False,
            "kg_eval_remaining_gate_count": remaining_gate_count,
        },
    }


def _project_grant(*, permission: str = "read") -> Grant:
    return Grant(
        grant_id=f"grant_closed_beta_{permission}",
        owner_user_id="user_closed_beta_admin",
        grantee_user_id=ACTOR_USER_ID,
        scope_type="project",
        scope_id=PROJECT_ID,
        permission=permission,
        expires_at="2026-06-30T00:00:00+00:00",
    )


def _tool_envelope(response: dict[str, Any]) -> dict[str, Any]:
    return response["result"]["content"][0]["json"]


def _hash_only_transcripts(entries: list[dict[str, Any]]) -> bool:
    expected = {"method", "request_hash", "response_hash", "status"}
    return bool(entries) and all(set(entry) == expected for entry in entries)


def _wiki_draft_is_draft(envelope: dict[str, Any]) -> bool:
    frontmatter = envelope.get("data", {}).get("frontmatter", {})
    return envelope.get("status") == "ok" and frontmatter.get("status") == "draft"


def _workspace_file_inventory(base_dir: Path) -> list[str]:
    return sorted(str(path.relative_to(base_dir)) for path in base_dir.rglob("*") if path.is_file())


def _unexpected_canonical_artifact_paths(paths: list[str]) -> list[str]:
    markers = (
        "canonical",
        "canonical-graph",
        "canonical_graph",
        "canonical-entities",
        "canonical_entities",
        "canonical-relations",
        "canonical_relations",
        "canonical-commits",
        "canonical_commits",
    )
    unexpected: list[str] = []
    for path in paths:
        parts = [part.lower() for part in Path(path).parts]
        if any(marker in part for part in parts for marker in markers):
            unexpected.append(path)
    return unexpected


def _is_containerized() -> bool:
    if os.environ.get("FORMOWL_CLOSED_BETA_SMOKE_CONTAINERIZED") == "1":
        return True
    return Path("/workspace").is_dir() and Path.cwd() == Path("/workspace")


def _temp_parent() -> Path:
    configured = os.environ.get("FORMOWL_CLOSED_BETA_SMOKE_TMP_ROOT")
    parent = (
        Path(configured).expanduser() if configured else ROOT / ".test-tmp" / "closed-beta-smoke"
    )
    parent.mkdir(parents=True, exist_ok=True)
    return parent


@contextmanager
def _temporary_smoke_dir():
    parent = _temp_parent().resolve()
    temp_dir = parent / f"formowl-closed-beta-smoke-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        resolved = temp_dir.resolve()
        if resolved == parent or parent not in resolved.parents:
            raise RuntimeError("refusing to clean a closed-beta smoke directory outside tmp root")
        shutil.rmtree(resolved, ignore_errors=True)


def _contains_forbidden_text(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_PUBLIC_KEYS:
                return True
            if _contains_forbidden_text(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden_text(item) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in FORBIDDEN_VALUE_PATTERNS)
    return False


def _safe_error_message(value: str) -> str:
    if _contains_forbidden_text(value):
        return "closed_beta_smoke_error_redacted"
    return value or "closed_beta_smoke_error"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--from-existing", action="store_true")
    args = parser.parse_args()

    if args.from_existing:
        report = load_report(args.output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report = build_report()
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    validation = validate_report(report)
    write_markdown(report, validation, args.output)
    if not validation["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
