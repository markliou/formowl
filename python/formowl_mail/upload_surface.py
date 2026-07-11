from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from formowl_auth.audit import (
    FileAuditLogStore,
    record_asset_registration,
    record_upload_session_file_received,
)
from formowl_contract import (
    Asset,
    ContractValidationError,
    SourceRef,
    UploadSession,
    now_iso,
    sha256_json,
)
from formowl_gateway import validate_public_gateway_payload
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.storage import AssetStore, FileObjectStore, UploadSessionRecordStore

from ._guards import assert_public_payload_safe, safe_public_string
from ._validation import dict_or_empty, expect_exact_keys
from .upload_session import _upload_surface_locator

_MAIL_UPLOAD_INTENDED_ASSET_TYPES = {"mail_archive", "pst", "ost", "msg", "eml", "mbox"}
_MAIL_UPLOAD_INGESTION_PROFILE = "mail_archive_phase1"
_RECEIVABLE_UPLOAD_STATUSES = {"pending"}
_RECEIVABLE_PROCESSING_STATUS = "waiting_for_upload"
_SUPPORTED_UPLOAD_EXTENSIONS = {
    "pst": "application/vnd.ms-outlook",
    "ost": "application/vnd.ms-outlook",
    "msg": "application/vnd.ms-outlook",
    "eml": "message/rfc822",
    "mbox": "application/mbox",
}
_ALLOWED_FORM_FIELDS = {
    "upload_session_id",
    "actor_user_id",
    "session_id",
    "workspace_id",
    "original_filename",
    "content_type",
    "expected_content_hash",
}
_FORBIDDEN_FORM_FIELD_PARTS = {
    "backend",
    "bucket",
    "database",
    "dsn",
    "folder",
    "key",
    "nas",
    "object",
    "parser",
    "path",
    "queue",
    "secret",
    "storage",
    "token",
    "worker",
}
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_LOCATOR_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_REQUIRED_TRUE_CHECKS = {
    "upload_session_loaded",
    "upload_session_bound_to_actor",
    "upload_session_bound_to_session",
    "mail_profile_bound",
    "asset_registered",
    "upload_session_asset_bound",
    "file_transfer_recorded",
    "no_user_infrastructure_controls_exposed",
    "raw_leak_guard_passed",
}
_FORBIDDEN_TRUE_CLAIMS = {
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_real_upload_iframe_claim",
    "supports_real_pst_parser_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_production_ready_claim",
}


@dataclass(frozen=True)
class MailUploadSurfaceReceipt:
    status: str
    upload_session_id: str
    asset_id: str
    accepted_file_type: str
    file_size_bytes: int
    content_hash: str
    original_filename: str
    duplicate_object_payload_reused: bool
    audit_event_count: int
    received_at: str

    def to_public_dict(self) -> dict[str, Any]:
        checks = {
            "upload_session_loaded": bool(self.upload_session_id),
            "upload_session_bound_to_actor": self.status == "uploaded",
            "upload_session_bound_to_session": self.status == "uploaded",
            "mail_profile_bound": self.accepted_file_type in _SUPPORTED_UPLOAD_EXTENSIONS,
            "asset_registered": bool(self.asset_id),
            "upload_session_asset_bound": self.status == "uploaded" and bool(self.asset_id),
            "file_transfer_recorded": self.file_size_bytes > 0,
            "no_user_infrastructure_controls_exposed": True,
            "raw_leak_guard_passed": True,
        }
        payload = {
            "report_type": "mail_upload_surface_receipt",
            "generated_at": self.received_at,
            "status": self.status,
            "upload_session_id": self.upload_session_id,
            "next_required_action": "server_side_mail_import",
            "upload_surface_locator": _upload_surface_locator(self.upload_session_id),
            "public_checks": checks,
            "safe_outputs": {
                "upload_session_id_hash": sha256_json(self.upload_session_id),
                "asset_id_hash": sha256_json(self.asset_id),
                "content_hash_hash": sha256_json(self.content_hash),
                "original_filename_hash": sha256_json(self.original_filename),
                "accepted_file_type": self.accepted_file_type,
                "file_size_bytes": self.file_size_bytes,
                "duplicate_object_payload_reused": self.duplicate_object_payload_reused,
                "audit_event_count": self.audit_event_count,
            },
            "claim_boundary": {
                "supports_upload_session_bound_file_transfer_claim": self.status == "uploaded",
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
        validation = validate_mail_upload_surface_receipt(payload)
        payload["validation"] = validation
        return payload


def receive_mail_archive_upload(
    staged_upload_path: str | Path,
    *,
    upload_session_id: str,
    upload_session_store: UploadSessionRecordStore,
    object_store: FileObjectStore,
    asset_store: AssetStore,
    audit_store: FileAuditLogStore,
    storage_backend_id: str,
    actor_user_id: str,
    session_id: str,
    original_filename: str,
    content_type: str | None = None,
    expected_content_hash: str | None = None,
    submitted_fields: Mapping[str, Any] | None = None,
    received_at: str | None = None,
) -> MailUploadSurfaceReceipt:
    """Register a file received by a session-bound mail upload surface.

    This is the backend intake boundary behind an iframe/widget or internal
    upload link. It accepts a server-staged file selected by trusted upload
    infrastructure, not a user-supplied local path or storage control.
    """

    upload_session = _validated_upload_session(
        upload_session_store=upload_session_store,
        upload_session_id=upload_session_id,
        actor_user_id=actor_user_id,
        session_id=session_id,
    )
    safe_filename = _safe_original_filename(original_filename)
    accepted_file_type = _accepted_file_type(
        safe_filename,
        intended_asset_type=upload_session.intended_asset_type,
    )
    resolved_content_type = _safe_content_type(content_type, accepted_file_type)
    _validate_submitted_fields(
        submitted_fields,
        expected={
            "upload_session_id": upload_session.upload_session_id,
            "actor_user_id": actor_user_id,
            "session_id": session_id,
            "workspace_id": upload_session.workspace_id,
            "original_filename": safe_filename,
            "content_type": resolved_content_type,
            "expected_content_hash": expected_content_hash,
        },
    )
    _require_safe_locator_segment(storage_backend_id, "storage_backend_id")
    staged = _validated_staged_upload_path(staged_upload_path)
    content_hash, file_size = _hash_file(staged)
    if file_size <= 0:
        raise ContractValidationError("mail upload archive must not be empty")
    if expected_content_hash is not None and expected_content_hash != content_hash:
        raise ContractValidationError("mail upload content hash did not match")
    object_uri = _object_uri_for_content(
        storage_backend_id=storage_backend_id,
        workspace_id=upload_session.workspace_id,
        content_hash=content_hash,
    )
    object_preexisted = object_store.verify_object(object_uri, content_hash)
    timestamp = received_at or now_iso()
    asset: Asset | None = None
    asset_audit_log_id: str | None = None
    receipt_audit_log_id: str | None = None
    try:
        asset = register_asset_from_local_file(
            staged,
            object_store=object_store,
            asset_store=asset_store,
            storage_backend_id=storage_backend_id,
            workspace_id=upload_session.workspace_id,
            owner_user_id=upload_session.actor_user_id,
            permission_scope=upload_session.permission_scope,
            source_ref=SourceRef(
                source_system="formowl_upload_session",
                source_type="mail_archive_upload",
                source_id=upload_session.upload_session_id,
                source_key=upload_session.upload_session_id,
            ),
            mime_type=resolved_content_type,
            expected_content_hash=content_hash,
            project_id=upload_session.project_id,
            created_at=timestamp,
            registered_at=timestamp,
        )
        asset_audit = record_asset_registration(
            audit_store,
            actor_user_id=actor_user_id,
            asset_id=asset.asset_id,
            workspace_id=upload_session.workspace_id,
            session_id=session_id,
            timestamp=timestamp,
        )
        asset_audit_log_id = asset_audit.audit_log_id
        receipt_audit = record_upload_session_file_received(
            audit_store,
            actor_user_id=actor_user_id,
            upload_session_id=upload_session.upload_session_id,
            asset_id=asset.asset_id,
            workspace_id=upload_session.workspace_id,
            session_id=session_id,
            accepted_file_type=accepted_file_type,
            file_size_bytes=file_size,
            timestamp=timestamp,
        )
        receipt_audit_log_id = receipt_audit.audit_log_id
        updated_session = upload_session_store.create(
            replace(
                upload_session,
                status="uploading",
                source_preparation_state="uploaded",
                processing_status="archive_uploaded",
                asset_id=asset.asset_id,
            )
        )
    except Exception:
        _rollback_upload_receipt(
            asset_store=asset_store,
            object_store=object_store,
            audit_store=audit_store,
            asset_id=asset.asset_id if asset is not None else None,
            object_uri=object_uri,
            object_preexisted=object_preexisted,
            asset_audit_log_id=asset_audit_log_id,
            receipt_audit_log_id=receipt_audit_log_id,
        )
        raise

    receipt = MailUploadSurfaceReceipt(
        status="uploaded",
        upload_session_id=updated_session.upload_session_id,
        asset_id=asset.asset_id,
        accepted_file_type=accepted_file_type,
        file_size_bytes=file_size,
        content_hash=content_hash,
        original_filename=safe_filename,
        duplicate_object_payload_reused=object_preexisted,
        audit_event_count=2,
        received_at=timestamp,
    )
    validate_mail_upload_surface_receipt(receipt.to_public_dict())
    return receipt


def validate_mail_upload_surface_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    value = dict(payload)
    expect_exact_keys(
        value,
        {
            "report_type",
            "generated_at",
            "status",
            "upload_session_id",
            "next_required_action",
            "upload_surface_locator",
            "public_checks",
            "safe_outputs",
            "claim_boundary",
            "validation",
        }
        if "validation" in value
        else {
            "report_type",
            "generated_at",
            "status",
            "upload_session_id",
            "next_required_action",
            "upload_surface_locator",
            "public_checks",
            "safe_outputs",
            "claim_boundary",
        },
        "mail_upload_surface_receipt",
        blockers,
    )
    if value.get("report_type") != "mail_upload_surface_receipt":
        blockers.append("report_type must be mail_upload_surface_receipt")
    if value.get("status") != "uploaded":
        blockers.append("status must be uploaded")
    upload_session_id = value.get("upload_session_id")
    if not isinstance(upload_session_id, str) or not upload_session_id:
        blockers.append("upload_session_id must be a non-empty string")
    if value.get("next_required_action") != "server_side_mail_import":
        blockers.append("next_required_action must be server_side_mail_import")
    if isinstance(upload_session_id, str) and value.get(
        "upload_surface_locator"
    ) != _upload_surface_locator(upload_session_id):
        blockers.append("upload_surface_locator must be bound to the upload session")

    public_checks = dict_or_empty(value.get("public_checks"), "public_checks", blockers)
    expect_exact_keys(public_checks, _REQUIRED_TRUE_CHECKS, "public_checks", blockers)
    for check in _REQUIRED_TRUE_CHECKS:
        if public_checks.get(check) is not True:
            blockers.append(f"public check is not true: {check}")

    safe_outputs = dict_or_empty(value.get("safe_outputs"), "safe_outputs", blockers)
    _validate_safe_outputs(safe_outputs, blockers)

    claim_boundary = dict_or_empty(value.get("claim_boundary"), "claim_boundary", blockers)
    expected_claim_keys = _FORBIDDEN_TRUE_CLAIMS | {
        "supports_upload_session_bound_file_transfer_claim",
        "container_verification_required",
    }
    expect_exact_keys(claim_boundary, expected_claim_keys, "claim_boundary", blockers)
    if claim_boundary.get("supports_upload_session_bound_file_transfer_claim") is not True:
        blockers.append("upload-session-bound file transfer claim is not supported")
    if claim_boundary.get("container_verification_required") is not True:
        blockers.append("container_verification_required must be true")
    for claim in _FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(claim) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {claim}")
    if "validation" in value:
        _validate_embedded_validation(value["validation"], blockers)
    try:
        validate_public_gateway_payload(value)
        assert_public_payload_safe(value, "mail_upload_surface_receipt")
    except Exception:
        blockers.append("mail upload surface receipt leaks raw paths or backend controls")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_upload_session_bound_file_transfer_claim": not blockers,
            "supports_production_ready_claim": False,
        },
    }


def _validated_upload_session(
    *,
    upload_session_store: UploadSessionRecordStore,
    upload_session_id: str,
    actor_user_id: str,
    session_id: str,
) -> UploadSession:
    _require_public_string(upload_session_id, "upload_session_id")
    _require_public_string(actor_user_id, "actor_user_id")
    _require_public_string(session_id, "session_id")
    upload_session = upload_session_store.get(upload_session_id)
    if upload_session is None:
        raise ContractValidationError("mail upload requires an existing UploadSession")
    assert_public_payload_safe(upload_session.to_dict(), "mail_upload_session")
    if upload_session.actor_user_id != actor_user_id:
        raise ContractValidationError("UploadSession actor does not match request actor")
    if upload_session.session_id != session_id:
        raise ContractValidationError("UploadSession session does not match request session")
    if upload_session.status not in _RECEIVABLE_UPLOAD_STATUSES:
        raise ContractValidationError("UploadSession is not waiting for an upload")
    if upload_session.processing_status != _RECEIVABLE_PROCESSING_STATUS:
        raise ContractValidationError("UploadSession processing status is not waiting")
    if upload_session.asset_id or upload_session.ingestion_job_id:
        raise ContractValidationError("UploadSession is already bound to an uploaded asset")
    if upload_session.intended_asset_type not in _MAIL_UPLOAD_INTENDED_ASSET_TYPES:
        raise ContractValidationError("UploadSession is not for a mail archive upload")
    if upload_session.ingestion_profile != _MAIL_UPLOAD_INGESTION_PROFILE:
        raise ContractValidationError("UploadSession does not use the mail archive profile")
    return upload_session


def _validated_staged_upload_path(value: str | Path) -> Path:
    staged = Path(value).expanduser().resolve()
    if not staged.is_file():
        raise FileNotFoundError("staged mail upload does not exist")
    return staged


def _safe_original_filename(value: str) -> str:
    filename = _require_public_string(value, "original_filename").strip()
    if filename in {".", ".."} or "/" in filename or "\\" in filename or ":" in filename:
        raise ContractValidationError("original_filename must be a file name")
    return filename


def _accepted_file_type(filename: str, *, intended_asset_type: str) -> str:
    suffix = Path(filename).suffix.lower().removeprefix(".")
    if suffix not in _SUPPORTED_UPLOAD_EXTENSIONS:
        raise ContractValidationError("mail upload file type is not supported")
    if intended_asset_type in _SUPPORTED_UPLOAD_EXTENSIONS and suffix != intended_asset_type:
        raise ContractValidationError("mail upload file type does not match UploadSession")
    return suffix


def _safe_content_type(value: str | None, accepted_file_type: str) -> str:
    if value in (None, ""):
        return _SUPPORTED_UPLOAD_EXTENSIONS[accepted_file_type]
    return _require_public_string(value, "content_type")


def _validate_submitted_fields(
    fields: Mapping[str, Any] | None,
    *,
    expected: Mapping[str, str | None],
) -> None:
    if fields is None:
        return
    if not isinstance(fields, Mapping):
        raise ContractValidationError("submitted upload fields must be an object")
    validate_public_gateway_payload(fields)
    _reject_user_infrastructure_controls(fields)
    unknown = sorted(set(fields) - _ALLOWED_FORM_FIELDS)
    if unknown:
        raise ContractValidationError(
            "mail upload form contains unsupported public fields: " + sha256_json(unknown)
        )
    for key, expected_value in expected.items():
        if key not in fields:
            continue
        if expected_value is None:
            raise ContractValidationError("mail upload form does not match UploadSession")
        actual = _require_public_string(fields[key], key)
        if actual != expected_value:
            raise ContractValidationError("mail upload form does not match UploadSession")


def _reject_user_infrastructure_controls(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _normalize_public_key(str(key))
            if set(normalized.split("_")) & _FORBIDDEN_FORM_FIELD_PARTS:
                raise ContractValidationError("mail upload form must not expose infrastructure")
            _reject_user_infrastructure_controls(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_user_infrastructure_controls(item)


def _normalize_public_key(value: str) -> str:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.strip())
    return re.sub(r"[^a-z0-9]+", "_", camel_split.lower()).strip("_")


def _rollback_upload_receipt(
    *,
    asset_store: AssetStore,
    object_store: FileObjectStore,
    audit_store: FileAuditLogStore,
    asset_id: str | None,
    object_uri: str,
    object_preexisted: bool,
    asset_audit_log_id: str | None,
    receipt_audit_log_id: str | None,
) -> None:
    if receipt_audit_log_id is not None:
        audit_store.delete(receipt_audit_log_id)
    if asset_audit_log_id is not None:
        audit_store.delete(asset_audit_log_id)
    if asset_id is not None:
        asset_store.delete(asset_id)
    if not object_preexisted:
        object_store.delete_object(object_uri)


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    file_size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            file_size += len(chunk)
    return f"sha256:{digest.hexdigest()}", file_size


def _object_uri_for_content(
    *,
    storage_backend_id: str,
    workspace_id: str,
    content_hash: str,
) -> str:
    _require_safe_locator_segment(storage_backend_id, "storage_backend_id")
    _require_safe_locator_segment(workspace_id, "workspace_id")
    if _SHA256_RE.fullmatch(content_hash) is None:
        raise ContractValidationError("content hash must be sha256")
    return (
        f"formowl://object/{storage_backend_id}/{workspace_id}/"
        f"{content_hash.removeprefix('sha256:')}"
    )


def _require_safe_locator_segment(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value or _SAFE_LOCATOR_SEGMENT.fullmatch(value) is None:
        raise ContractValidationError(f"{field_name} must be a safe locator segment")


def _require_public_string(value: Any, field_name: str) -> str:
    text = safe_public_string(value, field_name)
    if not text.strip():
        raise ContractValidationError(f"{field_name} is required")
    return text


def _validate_safe_outputs(value: Mapping[str, Any], blockers: list[str]) -> None:
    expected = {
        "upload_session_id_hash",
        "asset_id_hash",
        "content_hash_hash",
        "original_filename_hash",
        "accepted_file_type",
        "file_size_bytes",
        "duplicate_object_payload_reused",
        "audit_event_count",
    }
    expect_exact_keys(value, expected, "safe_outputs", blockers)
    for key in (
        "upload_session_id_hash",
        "asset_id_hash",
        "content_hash_hash",
        "original_filename_hash",
    ):
        item = value.get(key)
        if not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None:
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
    if value.get("accepted_file_type") not in _SUPPORTED_UPLOAD_EXTENSIONS:
        blockers.append("safe_outputs.accepted_file_type is not supported")
    for key in ("file_size_bytes", "audit_event_count"):
        item = value.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            blockers.append(f"safe_outputs.{key} must be a positive integer")
    if not isinstance(value.get("duplicate_object_payload_reused"), bool):
        blockers.append("safe_outputs.duplicate_object_payload_reused must be a boolean")


def _validate_embedded_validation(value: Any, blockers: list[str]) -> None:
    validation = dict_or_empty(value, "validation", blockers)
    expect_exact_keys(
        validation,
        {"passed", "blockers", "claim_boundary"},
        "validation",
        blockers,
    )
    if validation.get("passed") is not True:
        blockers.append("validation.passed must be true")
    if validation.get("blockers") != []:
        blockers.append("validation.blockers must be empty")
    claim_boundary = dict_or_empty(
        validation.get("claim_boundary"),
        "validation.claim_boundary",
        blockers,
    )
    expect_exact_keys(
        claim_boundary,
        {
            "supports_upload_session_bound_file_transfer_claim",
            "supports_production_ready_claim",
        },
        "validation.claim_boundary",
        blockers,
    )
    if claim_boundary.get("supports_upload_session_bound_file_transfer_claim") is not True:
        blockers.append("validation upload file-transfer claim must be true")
    if claim_boundary.get("supports_production_ready_claim") is not False:
        blockers.append("validation production claim must be false")


__all__ = [
    "MailUploadSurfaceReceipt",
    "receive_mail_archive_upload",
    "validate_mail_upload_surface_receipt",
]
