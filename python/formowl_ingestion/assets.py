"""Asset registration helpers for the resource extraction spine."""

from __future__ import annotations

from datetime import datetime, timezone
import mimetypes
from pathlib import Path

from formowl_contract import (
    Asset,
    PermissionScope,
    SourceRef,
    now_iso,
    stable_asset_id,
)

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
) -> Asset:
    """Register a trusted local file as a FormOwl asset for internal tests.

    The returned and persisted asset exposes only FormOwl object locators and
    source identity, not the raw local source path.
    """

    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source file does not exist: {source}")

    resolved_source_ref = source_ref or SourceRef(
        source_system="local",
        source_type="file",
        source_id=source.name,
        source_key=source.name,
    )
    resolved_mime_type = mime_type or _guess_mime_type(source)
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
    return asset_store.create(asset)


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


__all__ = [
    "register_asset_from_local_file",
]
