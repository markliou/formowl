"""Upload session helpers for user-initiated ingestion workflows."""

from __future__ import annotations

from pathlib import Path

from formowl_auth.audit import (
    FileAuditLogStore,
    record_asset_reference_upload,
    record_upload_session_creation,
)
from formowl_contract import (
    Asset,
    ContractValidationError,
    PermissionScope,
    SourceRef,
    UploadSession,
    now_iso,
    stable_resource_contract_id,
    stable_upload_session_id,
)

from .assets import register_asset_from_local_file
from .storage import AssetStore, FileObjectStore, UploadSessionStore


def create_upload_session(
    *,
    upload_session_store: UploadSessionStore,
    audit_store: FileAuditLogStore,
    actor_user_id: str,
    session_id: str,
    workspace_id: str,
    owner_scope_type: str,
    owner_scope_id: str,
    intent: str,
    intended_asset_type: str,
    ingestion_profile: str,
    visibility_scope: str,
    permission_scope: PermissionScope | dict[str, object],
    expires_at: str,
    source_preparation_state: str = "not_started",
    processing_status: str = "waiting_for_upload",
    status: str = "pending",
    created_at: str | None = None,
    project_id: str | None = None,
    customer_id: str | None = None,
) -> UploadSession:
    """Create an audited UploadSession before a normal user upload begins."""

    actor_user_id, session_id = _require_audit_identity(
        actor_user_id=actor_user_id,
        session_id=session_id,
    )
    if created_at is not None and (not isinstance(created_at, str) or not created_at):
        raise ContractValidationError("UploadSession.created_at must be a string")
    timestamp = created_at or now_iso()
    # Normal user uploads must have an auditable task identity before any
    # bytes are transferred or source-preparation guidance is followed.
    upload_session_id = stable_upload_session_id(
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        owner_scope_type=owner_scope_type,
        owner_scope_id=owner_scope_id,
        intent=intent,
        intended_asset_type=intended_asset_type,
        ingestion_profile=ingestion_profile,
        created_at=timestamp,
    )
    audit_log_id = _upload_session_creation_audit_log_id(
        actor_user_id=actor_user_id,
        upload_session_id=upload_session_id,
        workspace_id=workspace_id,
        session_id=session_id,
        timestamp=timestamp,
    )
    upload_session = UploadSession(
        upload_session_id=upload_session_id,
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        owner_scope_type=owner_scope_type,
        owner_scope_id=owner_scope_id,
        intent=intent,
        intended_asset_type=intended_asset_type,
        ingestion_profile=ingestion_profile,
        visibility_scope=visibility_scope,
        permission_scope=permission_scope,
        expires_at=expires_at,
        source_preparation_state=source_preparation_state,
        processing_status=processing_status,
        status=status,  # type: ignore[arg-type]
        created_at=timestamp,
        audit_log_id=audit_log_id,
        session_id=session_id,
        project_id=project_id,
        customer_id=customer_id,
    )
    # Validate before any durable write, then write audit before the session.
    # This keeps invalid requests and audit-store failures from leaving a
    # partially tracked UploadSession.
    upload_session = UploadSession.from_dict(upload_session.to_dict())
    record_upload_session_creation(
        audit_store,
        actor_user_id=actor_user_id,
        upload_session_id=upload_session_id,
        workspace_id=workspace_id,
        session_id=session_id,
        timestamp=timestamp,
        audit_log_id=audit_log_id,
    )
    try:
        return upload_session_store.create(upload_session)
    except Exception:
        audit_store.delete(audit_log_id)
        raise


def upload_asset_reference(
    source_path: str | Path,
    *,
    object_store: FileObjectStore,
    asset_store: AssetStore,
    audit_store: FileAuditLogStore,
    storage_backend_id: str,
    workspace_id: str,
    owner_user_id: str,
    actor_user_id: str,
    session_id: str,
    permission_scope: PermissionScope | dict[str, object],
    source_ref: SourceRef | dict[str, object],
    controlled_import_reason: str,
    mime_type: str | None = None,
    project_id: str | None = None,
    created_at: str | None = None,
    registered_at: str | None = None,
) -> Asset:
    """Register a trusted backend reference without treating it as a normal user upload."""

    if not controlled_import_reason.strip():
        raise ValueError("controlled_import_reason is required")

    # This path is for migrations and trusted backend references only. Normal
    # user uploads still start with UploadSession intent capture.
    asset = register_asset_from_local_file(
        source_path,
        object_store=object_store,
        asset_store=asset_store,
        storage_backend_id=storage_backend_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        permission_scope=permission_scope,
        source_ref=source_ref,
        mime_type=mime_type,
        project_id=project_id,
        created_at=created_at,
        registered_at=registered_at,
        audit_store=audit_store,
        actor_user_id=actor_user_id,
        session_id=session_id,
    )
    record_asset_reference_upload(
        audit_store,
        actor_user_id=actor_user_id,
        asset_id=asset.asset_id,
        workspace_id=asset.workspace_id,
        session_id=session_id,
        controlled_import_reason=controlled_import_reason,
        timestamp=asset.registered_at,
    )
    return asset


__all__ = [
    "create_upload_session",
    "upload_asset_reference",
]


def _upload_session_creation_audit_log_id(
    *,
    actor_user_id: str,
    upload_session_id: str,
    workspace_id: str,
    session_id: str,
    timestamp: str,
) -> str:
    return stable_resource_contract_id(
        "audit",
        "AuditLog",
        {
            "actor_user_id": actor_user_id,
            "action": "upload_session_created",
            "target_type": "upload_session",
            "target_id": upload_session_id,
            "session_id": session_id,
            "timestamp": timestamp,
            "workspace_id": workspace_id,
            "status": "ok",
            "grant_id": None,
            "metadata": None,
        },
    )


def _require_audit_identity(*, actor_user_id: str, session_id: str) -> tuple[str, str]:
    if (
        not isinstance(actor_user_id, str)
        or not actor_user_id
        or not isinstance(session_id, str)
        or not session_id
    ):
        raise ValueError("actor_user_id and session_id are required")
    return actor_user_id, session_id
