from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from formowl_contract import (
    ContractValidationError,
    SourceRef,
    UploadSession,
    sha256_json,
    to_plain,
)
from formowl_gateway import (
    SemanticGatewaySession,
    SemanticMcpGateway,
    SemanticMcpJsonRpcGateway,
    validate_public_gateway_payload,
)
from formowl_graph.storage import PostgreSQLUnitOfWork
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import ExtractorAdapter
from formowl_ingestion.extractors import FixtureMailArchiveExtractor, PstMailArchiveExtractor
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job
from formowl_ingestion.storage import (
    AssetRecordStore,
    ExtractorRunRecordStore,
    FileObjectStore,
    JobRecordStore,
    ObservationRecordStore,
    UploadSessionRecordStore,
)

from ._guards import assert_public_payload_safe, safe_public_string
from ._validation import dict_or_empty
from .bundle import MailEvidenceBundle, build_mail_evidence_bundle
from .postgres import (
    PostgreSQLMailEvidenceStore,
    build_postgre_sql_mail_evidence_query_handler,
)

_MAIL_UPLOAD_INTENDED_ASSET_TYPES = {"mail_archive", "pst", "ost", "msg", "eml", "mbox"}
_MAIL_UPLOAD_INGESTION_PROFILE = "mail_archive_phase1"
_IMPORTABLE_UPLOAD_STATUSES = {"pending", "uploading"}
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_FIXTURE_MAIL_MIME_TYPE = "application/vnd.formowl.mail-archive+json"
_OUTLOOK_MAIL_MIME_TYPE = "application/vnd.ms-outlook"
_FIXTURE_PARSER_NAME = "formowl_server_side_fixture_mail_parser"

_REQUIRED_TRUE_METRICS = {
    "upload_session_loaded",
    "upload_session_bound_to_actor",
    "upload_session_bound_to_session",
    "asset_registered",
    "ingestion_job_succeeded",
    "mail_observations_persisted",
    "mail_evidence_bundle_built",
    "mail_evidence_store_written",
    "store_backed_jsonrpc_query_succeeded",
    "no_user_infrastructure_controls_exposed",
    "raw_leak_guard_passed",
    "mail_upload_import_workflow_passed",
}
_FORBIDDEN_TRUE_CLAIMS = {
    "supports_real_pst_parser_claim",
    "supports_upload_ui_or_iframe_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_production_ready_claim",
}
_SAFE_OUTPUT_HASH_KEYS = {
    "upload_session_id_hash",
    "asset_id_hash",
    "ingestion_job_id_hash",
    "mail_import_session_id_hash",
    "mail_evidence_bundle_id_hash",
}


@dataclass(frozen=True)
class MailUploadImportWorkflowResult:
    status: str
    upload_session_id: str
    asset_id: str
    ingestion_job_id: str
    mail_import_session_id: str
    mail_evidence_bundle_id: str
    observation_count: int
    extractor_run_count: int
    mail_evidence_statement_count: int
    owner_query_status: str
    owner_citation_count: int
    transcript: list[dict[str, Any]]
    generated_at: str

    def to_public_dict(self) -> dict[str, Any]:
        metrics = {
            "upload_session_loaded": bool(self.upload_session_id),
            "upload_session_bound_to_actor": self.status == "succeeded",
            "upload_session_bound_to_session": self.status == "succeeded",
            "asset_registered": bool(self.asset_id),
            "ingestion_job_succeeded": bool(self.ingestion_job_id),
            "mail_observations_persisted": self.observation_count > 0,
            "mail_evidence_bundle_built": bool(self.mail_evidence_bundle_id),
            "mail_evidence_store_written": self.mail_evidence_statement_count > 0,
            "store_backed_jsonrpc_query_succeeded": self.owner_query_status == "ok",
            "no_user_infrastructure_controls_exposed": True,
            "raw_leak_guard_passed": True,
        }
        metrics["mail_upload_import_workflow_passed"] = all(metrics.values())
        summary = {
            "report_type": "mail_upload_import_workflow",
            "generated_at": self.generated_at,
            "status": self.status,
            "metrics": metrics,
            "safe_outputs": {
                "upload_session_id_hash": sha256_json(self.upload_session_id),
                "asset_id_hash": sha256_json(self.asset_id),
                "ingestion_job_id_hash": sha256_json(self.ingestion_job_id),
                "mail_import_session_id_hash": sha256_json(self.mail_import_session_id),
                "mail_evidence_bundle_id_hash": sha256_json(self.mail_evidence_bundle_id),
                "observation_count": self.observation_count,
                "extractor_run_count": self.extractor_run_count,
                "mail_evidence_statement_count": self.mail_evidence_statement_count,
                "owner_query_status": self.owner_query_status,
                "owner_citation_count": self.owner_citation_count,
                "transcript": self.transcript,
            },
            "claim_boundary": {
                "supports_upload_session_bound_mail_import_workflow_claim": (
                    self.status == "succeeded" and metrics["mail_upload_import_workflow_passed"]
                ),
                "supports_real_pst_parser_claim": False,
                "supports_upload_ui_or_iframe_claim": False,
                "supports_live_postgresql_readiness_claim": False,
                "supports_production_worker_leasing_claim": False,
                "supports_kg_write_claim": False,
                "supports_wiki_projection_claim": False,
                "supports_production_ready_claim": False,
                "container_verification_required": True,
            },
        }
        validation = validate_mail_upload_import_summary(summary)
        summary["validation"] = validation
        return summary


def run_upload_session_mail_import(
    staged_archive_path: str | Path | None,
    *,
    upload_session_id: str,
    upload_session_store: UploadSessionRecordStore,
    object_store: FileObjectStore,
    asset_store: AssetRecordStore,
    job_store: JobRecordStore,
    extractor_run_store: ExtractorRunRecordStore,
    observation_store: ObservationRecordStore,
    mail_evidence_store: PostgreSQLMailEvidenceStore,
    storage_backend_id: str,
    actor_user_id: str,
    session_id: str,
    query_text: str | None,
    created_at: str,
    started_at: str | None = None,
    completed_at: str | None = None,
    adapter: ExtractorAdapter | None = None,
    extraction_config: Mapping[str, Any] | None = None,
    asset_mime_type: str | None = None,
    parser_name: str | None = None,
    parser_version: str | None = None,
    retention_policy: str = "retain_7_days",
    raw_archive_retention_decision: str = "retained_by_policy",
) -> MailUploadImportWorkflowResult:
    """Run a narrow #21 server-side mail import from an existing UploadSession.

    This is an internal service workflow, not a ChatGPT-facing backend control
    plane. Callers inject stores and storage configuration from trusted server
    context; the public result exposes only ids as hashes, counts, statuses, and
    claim boundaries.
    """

    upload_session = _validated_mail_upload_session(
        upload_session_store=upload_session_store,
        upload_session_id=upload_session_id,
        actor_user_id=actor_user_id,
        session_id=session_id,
    )
    if query_text is not None:
        _require_non_empty_public_string(query_text, "query_text")
    _require_non_empty_public_string(storage_backend_id, "storage_backend_id")
    _require_non_empty_public_string(created_at, "created_at")

    resolved_started_at = started_at or created_at
    resolved_completed_at = completed_at or created_at
    requested_asset_mime_type = asset_mime_type or _FIXTURE_MAIL_MIME_TYPE
    asset = _loaded_or_registered_upload_asset(
        staged_archive_path,
        upload_session=upload_session,
        object_store=object_store,
        asset_store=asset_store,
        storage_backend_id=storage_backend_id,
        mime_type=requested_asset_mime_type,
        created_at=created_at,
    )
    mail_adapter = adapter or _adapter_for_asset(asset.mime_type)
    resolved_parser_name = parser_name or _parser_name_for_adapter(mail_adapter)
    resolved_parser_version = parser_version or mail_adapter.version()
    job = create_ingestion_job(
        asset=asset,
        job_store=job_store,
        requested_by=upload_session.actor_user_id,
        extractor_adapters=[mail_adapter],
        config=extraction_config,
        created_at=created_at,
    )
    finished_job = run_ingestion_job(
        ingestion_job_id=job.ingestion_job_id,
        asset_store=asset_store,
        job_store=job_store,
        object_store=object_store,
        extractor_run_store=extractor_run_store,
        observation_store=observation_store,
        extractor_adapters=[mail_adapter],
        config=extraction_config,
        started_at=resolved_started_at,
        completed_at=resolved_completed_at,
    )
    if finished_job.status != "succeeded":
        upload_session_store.create(
            replace(
                upload_session,
                status="failed",
                processing_status="mail_parser_failed",
                asset_id=asset.asset_id,
                ingestion_job_id=finished_job.ingestion_job_id,
                completed_at=resolved_completed_at,
            )
        )
        raise RuntimeError("mail upload import parser failed")

    observation_ids = set(finished_job.observation_ids)
    observations = [
        observation
        for observation in observation_store.list()
        if observation.observation_id in observation_ids
    ]
    extractor_runs = [
        extractor_run
        for extractor_run in extractor_run_store.list()
        if extractor_run.extractor_run_id in set(finished_job.extractor_run_ids)
    ]
    resolved_query_text = query_text or _verification_query_from_observations(observations)
    bundle = build_mail_evidence_bundle(
        observations,
        workspace_id=upload_session.workspace_id,
        owner_user_id=upload_session.actor_user_id,
        source_asset_id=asset.asset_id,
        archive_sha256=asset.content_hash,
        producer_type="server_side_parser",
        parser_name=resolved_parser_name,
        parser_version=resolved_parser_version,
        upload_session_id=upload_session.upload_session_id,
        retention_policy=retention_policy,
        raw_archive_retention_decision=raw_archive_retention_decision,
        created_at=created_at,
        started_at=resolved_started_at,
        completed_at=resolved_completed_at,
        parse_warnings=[
            warning for extractor_run in extractor_runs for warning in extractor_run.warnings
        ],
    )
    try:
        statements, owner_query = _upsert_bundle_after_verified_query(
            mail_evidence_store=mail_evidence_store,
            upload_session=upload_session,
            session_id=session_id,
            query_text=resolved_query_text,
            bundle=bundle,
        )
    except _MailEvidenceQueryVerificationError:
        upload_session_store.create(
            replace(
                upload_session,
                status="failed",
                processing_status="mail_evidence_query_failed",
                asset_id=asset.asset_id,
                ingestion_job_id=finished_job.ingestion_job_id,
                completed_at=resolved_completed_at,
            )
        )
        raise
    except Exception:
        upload_session_store.create(
            replace(
                upload_session,
                status="failed",
                processing_status="mail_evidence_store_failed",
                asset_id=asset.asset_id,
                ingestion_job_id=finished_job.ingestion_job_id,
                completed_at=resolved_completed_at,
            )
        )
        raise

    owner_payload = owner_query["response"]["result"]["content"][0]["json"]
    updated_session = upload_session_store.create(
        replace(
            upload_session,
            status="succeeded",
            source_preparation_state="uploaded",
            processing_status="mail_evidence_ready",
            asset_id=asset.asset_id,
            ingestion_job_id=finished_job.ingestion_job_id,
            completed_at=resolved_completed_at,
        )
    )
    result = MailUploadImportWorkflowResult(
        status=updated_session.status,
        upload_session_id=updated_session.upload_session_id,
        asset_id=asset.asset_id,
        ingestion_job_id=finished_job.ingestion_job_id,
        mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
        mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
        observation_count=len(observations),
        extractor_run_count=len(finished_job.extractor_run_ids),
        mail_evidence_statement_count=len(statements),
        owner_query_status=str(owner_payload.get("status", "unknown")),
        owner_citation_count=len(owner_payload.get("data", {}).get("citations", [])),
        transcript=owner_query["transcript"],
        generated_at=created_at,
    )
    validate_mail_upload_import_summary(result.to_public_dict())
    return result


def validate_mail_upload_import_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    payload = dict(summary)
    allowed_top_level = {
        "report_type",
        "generated_at",
        "status",
        "metrics",
        "safe_outputs",
        "claim_boundary",
        "validation",
    }
    _validate_allowed_keys(payload, allowed_top_level, "summary", blockers)
    if payload.get("report_type") != "mail_upload_import_workflow":
        blockers.append("report_type must be mail_upload_import_workflow")
    if payload.get("status") != "succeeded":
        blockers.append("status must be succeeded")
    metrics = dict_or_empty(payload.get("metrics"), "metrics", blockers)
    safe_outputs = dict_or_empty(payload.get("safe_outputs"), "safe_outputs", blockers)
    claim_boundary = dict_or_empty(
        payload.get("claim_boundary"),
        "claim_boundary",
        blockers,
    )
    if "validation" in payload:
        _validate_embedded_validation(payload["validation"], blockers)

    _validate_exact_keys(metrics, _REQUIRED_TRUE_METRICS, "metrics", blockers)
    for metric in _REQUIRED_TRUE_METRICS:
        if metrics.get(metric) is not True:
            blockers.append(f"required import workflow metric is not true: {metric}")

    expected_claim_keys = _FORBIDDEN_TRUE_CLAIMS | {
        "supports_upload_session_bound_mail_import_workflow_claim",
        "container_verification_required",
    }
    _validate_exact_keys(claim_boundary, expected_claim_keys, "claim_boundary", blockers)
    if claim_boundary.get("supports_upload_session_bound_mail_import_workflow_claim") is not True:
        blockers.append("upload-session-bound import workflow claim is not supported")
    if claim_boundary.get("container_verification_required") is not True:
        blockers.append("container_verification_required must be true")
    for claim in _FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(claim) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {claim}")

    _validate_safe_outputs(safe_outputs, blockers)
    _reject_body_or_evidence_text_fields(payload, blockers)
    rendered_summary = str(to_plain(payload))
    for phrase in ("Update: Launch reviewed", "Blocker: Waiting on audit approval"):
        if phrase in rendered_summary:
            blockers.append("public summary includes synthetic mail body text")
            break
    try:
        validate_public_gateway_payload(payload)
        assert_public_payload_safe(payload, "mail_upload_import_summary")
    except Exception:
        blockers.append("public summary leaks raw paths, SQL, secrets, or backend internals")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_upload_session_bound_mail_import_workflow_claim": not blockers,
            "supports_production_ready_claim": False,
        },
    }


def _validated_mail_upload_session(
    *,
    upload_session_store: UploadSessionRecordStore,
    upload_session_id: str,
    actor_user_id: str,
    session_id: str,
) -> UploadSession:
    _require_non_empty_public_string(upload_session_id, "upload_session_id")
    _require_non_empty_public_string(actor_user_id, "actor_user_id")
    _require_non_empty_public_string(session_id, "session_id")
    upload_session = upload_session_store.get(upload_session_id)
    if upload_session is None:
        raise ContractValidationError("mail import requires an existing UploadSession")
    assert_public_payload_safe(upload_session.to_dict(), "mail_upload_session")
    if upload_session.actor_user_id != actor_user_id:
        raise ContractValidationError("UploadSession actor does not match request actor")
    if upload_session.session_id != session_id:
        raise ContractValidationError("UploadSession session does not match request session")
    if upload_session.status not in _IMPORTABLE_UPLOAD_STATUSES:
        raise ContractValidationError("UploadSession is not importable")
    if upload_session.ingestion_job_id:
        raise ContractValidationError("UploadSession is already bound to an import")
    if upload_session.intended_asset_type not in _MAIL_UPLOAD_INTENDED_ASSET_TYPES:
        raise ContractValidationError("UploadSession is not for a mail archive import")
    if upload_session.ingestion_profile != _MAIL_UPLOAD_INGESTION_PROFILE:
        raise ContractValidationError("UploadSession does not use the mail archive profile")
    if upload_session.asset_id and (
        upload_session.status != "uploading"
        or upload_session.processing_status != "archive_uploaded"
    ):
        raise ContractValidationError("UploadSession asset is not ready for import")
    return upload_session


def _loaded_or_registered_upload_asset(
    staged_archive_path: str | Path | None,
    *,
    upload_session: UploadSession,
    object_store: FileObjectStore,
    asset_store: AssetRecordStore,
    storage_backend_id: str,
    mime_type: str,
    created_at: str,
) -> Any:
    if upload_session.asset_id:
        asset = asset_store.get(upload_session.asset_id)
        if asset is None:
            raise ContractValidationError("UploadSession asset is missing")
        if asset.workspace_id != upload_session.workspace_id:
            raise ContractValidationError("UploadSession asset workspace does not match")
        if asset.owner_user_id != upload_session.actor_user_id:
            raise ContractValidationError("UploadSession asset owner does not match")
        if asset.permission_scope != upload_session.permission_scope:
            raise ContractValidationError("UploadSession asset permission scope does not match")
        if not object_store.verify_object(asset.object_uri, asset.content_hash):
            raise ContractValidationError("UploadSession asset object verification failed")
        source_ref = asset.source_ref
        if not isinstance(source_ref, dict):
            raise ContractValidationError("UploadSession asset source ref is invalid")
        if (
            source_ref.get("source_system") != "formowl_upload_session"
            or source_ref.get("source_type") != "mail_archive_upload"
            or source_ref.get("source_id") != upload_session.upload_session_id
            or source_ref.get("source_key") != upload_session.upload_session_id
        ):
            raise ContractValidationError("UploadSession asset source ref does not match")
        return asset

    archive_path = _validated_staged_archive_path(staged_archive_path)
    source_ref = SourceRef(
        source_system="formowl_upload_session",
        source_type="mail_archive",
        source_id=upload_session.upload_session_id,
        source_key=upload_session.upload_session_id,
    )
    return register_asset_from_local_file(
        archive_path,
        object_store=object_store,
        asset_store=asset_store,
        storage_backend_id=storage_backend_id,
        workspace_id=upload_session.workspace_id,
        owner_user_id=upload_session.actor_user_id,
        permission_scope=upload_session.permission_scope,
        source_ref=source_ref,
        mime_type=mime_type,
        created_at=created_at,
        registered_at=created_at,
    )


def _adapter_for_asset(mime_type: str) -> ExtractorAdapter:
    if mime_type == _FIXTURE_MAIL_MIME_TYPE or mime_type == "application/json":
        return FixtureMailArchiveExtractor()
    if mime_type in set(PstMailArchiveExtractor().supported_mime_types()):
        return PstMailArchiveExtractor()
    raise ContractValidationError("no configured mail parser supports uploaded asset MIME type")


def _parser_name_for_adapter(adapter: ExtractorAdapter) -> str:
    if adapter.name() == "fixture_mail_archive_extractor":
        return _FIXTURE_PARSER_NAME
    return adapter.name()


def _validated_staged_archive_path(path: str | Path | None) -> Path:
    if path is None:
        raise ContractValidationError("staged mail archive is required")
    staged = Path(path).expanduser().resolve()
    if not staged.is_file():
        raise FileNotFoundError("staged mail archive does not exist")
    return staged


def _require_non_empty_public_string(value: Any, field_name: str) -> str:
    text = safe_public_string(value, field_name)
    if not text.strip():
        raise ContractValidationError(f"{field_name} is required")
    return text


def _verification_query_from_observations(observations: Sequence[Any]) -> str:
    for observation_type in ("email_body_segment", "email_message", "email_header"):
        for observation in observations:
            if observation.observation_type != observation_type:
                continue
            for token in _query_tokens(observation.text or ""):
                return token
    raise ContractValidationError("mail import could not derive a verification query")


def _query_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for token in re.split(r"[^A-Za-z0-9_@.-]+", value):
        if len(token) < 3:
            continue
        try:
            safe_public_string(token, "verification_query_token")
        except ContractValidationError:
            continue
        tokens.append(token)
    return tokens


def _upsert_bundle_after_verified_query(
    *,
    mail_evidence_store: PostgreSQLMailEvidenceStore,
    upload_session: UploadSession,
    session_id: str,
    query_text: str,
    bundle: MailEvidenceBundle,
) -> tuple[list[Any], dict[str, Any]]:
    # Keep evidence writes and the verification read in one transaction. If the
    # store-backed query cannot see usable evidence, the rows are rolled back
    # before the UploadSession can be considered ready.
    with PostgreSQLUnitOfWork(mail_evidence_store.connection) as unit:
        statements = mail_evidence_store.upsert_bundle(bundle)
        owner_query = _query_store_backed_jsonrpc(
            mail_evidence_store=mail_evidence_store,
            upload_session=upload_session,
            session_id=session_id,
            query_text=query_text,
            bundle=bundle,
        )
        owner_payload = owner_query["response"]["result"]["content"][0]["json"]
        if owner_payload.get("status") != "ok" or not owner_payload.get("data", {}).get(
            "citations"
        ):
            raise _MailEvidenceQueryVerificationError("mail evidence query verification failed")
        unit.commit()
    return statements, owner_query


class _MailEvidenceQueryVerificationError(RuntimeError):
    pass


def _query_store_backed_jsonrpc(
    *,
    mail_evidence_store: PostgreSQLMailEvidenceStore,
    upload_session: UploadSession,
    session_id: str,
    query_text: str,
    bundle: MailEvidenceBundle,
) -> dict[str, Any]:
    gateway = SemanticMcpJsonRpcGateway(
        semantic_gateway=SemanticMcpGateway(
            mail_evidence_handler=build_postgre_sql_mail_evidence_query_handler(
                mail_evidence_store,
            )
        ),
        session=SemanticGatewaySession(
            session_id=session_id,
            actor_user_id=upload_session.actor_user_id,
            workspace_id=upload_session.workspace_id,
        ),
    )
    response = gateway.handle_json_rpc(
        {
            "jsonrpc": "2.0",
            "id": "mail_upload_import_owner_query",
            "method": "tools/call",
            "params": {
                "name": "query_mail_evidence",
                "arguments": {
                    "query_text": query_text,
                    "mail_import_session_id": (bundle.mail_import_session.mail_import_session_id),
                },
            },
        }
    )
    return {"response": response, "transcript": gateway.leak_transcript()}


def _validate_embedded_validation(value: Any, blockers: list[str]) -> None:
    validation = dict_or_empty(value, "validation", blockers)
    expected_keys = {"passed", "blockers", "claim_boundary"}
    _validate_exact_keys(validation, expected_keys, "validation", blockers)
    if validation.get("passed") is not True:
        blockers.append("validation.passed must be true")
    if validation.get("blockers") != []:
        blockers.append("validation.blockers must be empty")
    claim_boundary = dict_or_empty(
        validation.get("claim_boundary"),
        "validation.claim_boundary",
        blockers,
    )
    _validate_exact_keys(
        claim_boundary,
        {
            "supports_upload_session_bound_mail_import_workflow_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    if claim_boundary.get("supports_upload_session_bound_mail_import_workflow_claim") is not True:
        blockers.append("validation import workflow claim must be true")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


def _validate_safe_outputs(value: dict[str, Any], blockers: list[str]) -> None:
    expected_keys = _SAFE_OUTPUT_HASH_KEYS | {
        "observation_count",
        "extractor_run_count",
        "mail_evidence_statement_count",
        "owner_query_status",
        "owner_citation_count",
        "transcript",
    }
    _validate_exact_keys(value, expected_keys, "safe_outputs", blockers)
    for key in _SAFE_OUTPUT_HASH_KEYS:
        item = value.get(key)
        if not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None:
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
    for key in (
        "observation_count",
        "extractor_run_count",
        "mail_evidence_statement_count",
        "owner_citation_count",
    ):
        item = value.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            blockers.append(f"safe_outputs.{key} must be a positive integer")
    if value.get("owner_query_status") != "ok":
        blockers.append("safe_outputs.owner_query_status must be ok")
    transcript = value.get("transcript")
    if not isinstance(transcript, list) or not transcript:
        blockers.append("safe_outputs.transcript must be a non-empty list")
        return
    for entry in transcript:
        if not isinstance(entry, dict) or set(entry) != {
            "method",
            "request_hash",
            "response_hash",
            "status",
        }:
            blockers.append("safe_outputs.transcript must be hash-only")
            return
        for key in ("request_hash", "response_hash"):
            item = entry.get(key)
            if not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None:
                blockers.append("safe_outputs.transcript hashes must be sha256 hashes")
                return


def _validate_exact_keys(
    value: Mapping[str, Any],
    expected_keys: set[str],
    context: str,
    blockers: list[str],
) -> None:
    actual_keys = set(value)
    extra = sorted(actual_keys - expected_keys)
    missing = sorted(expected_keys - actual_keys)
    if extra:
        blockers.append(_unknown_keys_message(context, extra))
    if missing:
        blockers.append(f"{context} missing keys: " + ", ".join(missing))


def _validate_allowed_keys(
    value: Mapping[str, Any],
    allowed_keys: set[str],
    context: str,
    blockers: list[str],
) -> None:
    extra = sorted(set(value) - allowed_keys)
    if extra:
        blockers.append(_unknown_keys_message(context, extra))


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
                blockers.append("public summary contains evidence text field: " + sha256_json(path))
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
    return f"{context} contains unknown keys: count={len(keys)} hash={sha256_json(list(keys))}"


__all__ = [
    "MailUploadImportWorkflowResult",
    "run_upload_session_mail_import",
    "validate_mail_upload_import_summary",
]
