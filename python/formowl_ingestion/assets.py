"""Asset registration helpers for the resource extraction spine."""

from __future__ import annotations

from datetime import datetime, timezone
import mimetypes
from pathlib import Path

from formowl_contract import (
    Asset,
    ContractValidationError,
    PermissionScope,
    SourceRef,
    now_iso,
    stable_asset_id,
    validate_permission_scope,
    validate_source_ref,
)
from formowl_auth.audit import FileAuditLogStore, record_asset_registration

from .storage import AssetStore, FileObjectStore


def register_asset_from_local_file(
    source_path: str | Path,
    *,
    object_store: FileObjectStore,
    asset_store: AssetStore,
    storage_backend_id: str,
    workspace_id: str,
    owner_user_id: str,
    permission_scope: PermissionScope | dict[str, object],
    source_ref: SourceRef | dict[str, object] | None = None,
    mime_type: str | None = None,
    project_id: str | None = None,
    created_at: str | None = None,
    registered_at: str | None = None,
    audit_store: FileAuditLogStore | None = None,
    actor_user_id: str | None = None,
    session_id: str | None = None,
) -> Asset:
    """Register a trusted local file as a FormOwl asset for internal tests.

    The returned and persisted asset exposes only FormOwl object locators and
    source identity, not the raw local source path.
    """

    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source file does not exist: {source}")
    audit_identity = None
    if audit_store is not None:
        # Audit-bound calls must prove actor/session context before bytes or
        # asset records are written.
        audit_identity = _require_audit_identity(
            actor_user_id=actor_user_id,
            session_id=session_id,
        )

    resolved_source_ref = source_ref or SourceRef(
        source_system="local",
        source_type="file",
        source_id=source.name,
        source_key=source.name,
    )
    resolved_mime_type = mime_type or _guess_mime_type(source)
    _validate_asset_registration_inputs(
        storage_backend_id=storage_backend_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        permission_scope=permission_scope,
        source_ref=resolved_source_ref,
        mime_type=resolved_mime_type,
        project_id=project_id,
        created_at=created_at,
        registered_at=registered_at,
    )
    stored = object_store.copy_local_file(
        source,
        storage_backend_id=storage_backend_id,
        workspace_id=workspace_id,
        original_filename=source.name,
    )
    asset = Asset(
        asset_id=stable_asset_id(
            storage_backend_id=stored.storage_backend_id,
            object_uri=stored.object_uri,
            content_hash=stored.content_hash,
            workspace_id=stored.workspace_id,
            source_ref=resolved_source_ref,
        ),
        storage_backend_id=stored.storage_backend_id,
        object_uri=stored.object_uri,
        content_hash=stored.content_hash,
        file_size=stored.file_size,
        mime_type=resolved_mime_type,
        created_at=created_at or _file_modified_at(source),
        registered_at=registered_at or now_iso(),
        owner_user_id=owner_user_id,
        workspace_id=stored.workspace_id,
        permission_scope=permission_scope,
        lifecycle_state="active",
        source_ref=resolved_source_ref,
        original_filename=source.name,
        project_id=project_id,
    )
    registered_asset = asset_store.create(asset)
    # Trusted internal tests may omit audit_store, but user-facing paths pass
    # actor/session context so asset registration becomes traceable.
    if audit_store is not None and audit_identity is not None:
        record_asset_registration(
            audit_store,
            actor_user_id=audit_identity[0],
            asset_id=registered_asset.asset_id,
            workspace_id=registered_asset.workspace_id,
            session_id=audit_identity[1],
            timestamp=registered_asset.registered_at,
        )
    return registered_asset


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _file_modified_at(path: Path) -> str:
    return (
        datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def _require_audit_identity(
    *,
    actor_user_id: str | None,
    session_id: str | None,
) -> tuple[str, str]:
    if (
        not isinstance(actor_user_id, str)
        or not actor_user_id
        or not isinstance(session_id, str)
        or not session_id
    ):
        raise ValueError("actor_user_id and session_id are required when audit_store is provided")
    return actor_user_id, session_id


def _validate_asset_registration_inputs(
    *,
    storage_backend_id: str,
    workspace_id: str,
    owner_user_id: str,
    permission_scope: PermissionScope | dict[str, object],
    source_ref: SourceRef | dict[str, object],
    mime_type: str,
    project_id: str | None,
    created_at: str | None,
    registered_at: str | None,
) -> None:
    # Validate caller-controlled metadata before copying bytes so rejected
    # imports cannot leave untracked object-store payloads behind.
    for field_name, value in (
        ("storage_backend_id", storage_backend_id),
        ("workspace_id", workspace_id),
        ("owner_user_id", owner_user_id),
        ("mime_type", mime_type),
    ):
        _require_non_empty_string(value, f"Asset.{field_name}")
    for field_name, value in (
        ("project_id", project_id),
        ("created_at", created_at),
        ("registered_at", registered_at),
    ):
        if value is not None and (not isinstance(value, str) or not value):
            raise ContractValidationError(f"Asset.{field_name} must be a string")
    validate_source_ref(source_ref)
    validate_permission_scope(permission_scope)


def _require_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")


__all__ = [
    "register_asset_from_local_file",
]
