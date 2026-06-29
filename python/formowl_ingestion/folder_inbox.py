"""Trusted local folder ingress for FormOwl resource registration."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from formowl_auth.audit import FileAuditLogStore
from formowl_contract import (
    Asset,
    PermissionScope,
    SourceRef,
    sha256_json,
    stable_asset_id,
    stable_ingestion_job_id,
    to_plain,
)

from .assets import register_asset_from_local_file
from .extraction import ExtractorAdapter, extraction_config_hash
from .jobs import create_ingestion_job, run_ingestion_job
from .storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
)


@dataclass(frozen=True)
class FolderFileStabilitySnapshot:
    """Internal caller-held snapshot used to prove a folder file is stable."""

    source_file_token: str
    size_bytes: int
    modified_time_ns: int
    content_hash: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FolderFileStabilitySnapshot":
        return cls(
            source_file_token=str(value["source_file_token"]),
            size_bytes=int(value["size_bytes"]),
            modified_time_ns=int(value["modified_time_ns"]),
            content_hash=str(value["content_hash"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)

    def is_stable_with(self, previous: "FolderFileStabilitySnapshot | Mapping[str, Any]") -> bool:
        other = (
            previous
            if isinstance(previous, FolderFileStabilitySnapshot)
            else FolderFileStabilitySnapshot.from_dict(previous)
        )
        return (
            self.source_file_token == other.source_file_token
            and self.size_bytes == other.size_bytes
            and self.modified_time_ns == other.modified_time_ns
            and self.content_hash == other.content_hash
        )


@dataclass(frozen=True)
class FolderInboxItemResult:
    status: str
    source_file_token: str
    content_hash: str
    file_size: int
    mime_type: str | None = None
    asset_id: str | None = None
    object_uri: str | None = None
    ingestion_job_id: str | None = None
    ingestion_job_status: str | None = None
    extractor_run_ids: list[str] = field(default_factory=list)
    observation_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_plain(
            {
                "status": self.status,
                "content_hash": self.content_hash,
                "file_size": self.file_size,
                "mime_type": self.mime_type,
                "asset_id": self.asset_id,
                "object_uri": self.object_uri,
                "ingestion_job_id": self.ingestion_job_id,
                "ingestion_job_status": self.ingestion_job_status,
                "extractor_run_ids": list(self.extractor_run_ids),
                "observation_count": self.observation_count,
                "warnings": list(self.warnings),
            }
        )


@dataclass(frozen=True)
class FolderInboxScanResult:
    items: list[FolderInboxItemResult]
    snapshots: dict[str, FolderFileStabilitySnapshot]
    ignored_entry_count: int = 0

    def stability_snapshots_by_token(self) -> dict[str, FolderFileStabilitySnapshot]:
        return dict(self.snapshots)

    def to_dict(self) -> dict[str, Any]:
        counts = self.counts()
        return {
            "result_type": "local_folder_inbox_scan",
            "status": "partial"
            if counts["deferred_file_count"] or counts["failed_file_count"]
            else "ok",
            "counts": counts,
            "items": [item.to_dict() for item in self.items],
        }

    def counts(self) -> dict[str, int]:
        return {
            "scanned_file_count": len(self.items),
            "ignored_entry_count": self.ignored_entry_count,
            "stable_file_count": sum(
                1 for item in self.items if item.status != "deferred_unstable"
            ),
            "deferred_file_count": sum(
                1 for item in self.items if item.status == "deferred_unstable"
            ),
            "failed_file_count": sum(1 for item in self.items if item.status == "failed"),
            "registered_asset_count": sum(
                1 for item in self.items if item.status in {"registered", "queued", "ingested"}
            ),
            "existing_asset_count": sum(
                1 for item in self.items if "existing_asset" in item.warnings
            ),
            "created_job_count": sum(1 for item in self.items if "created_job" in item.warnings),
            "existing_job_count": sum(1 for item in self.items if "existing_job" in item.warnings),
            "extractor_run_count": sum(len(item.extractor_run_ids) for item in self.items),
            "observation_count": sum(item.observation_count for item in self.items),
        }


def scan_local_data_resource_folder(
    folder_path: str | Path,
    *,
    previous_snapshots: Mapping[str, FolderFileStabilitySnapshot | Mapping[str, Any]] | None = None,
    object_store: FileObjectStore,
    asset_store: AssetStore,
    job_store: JobStore,
    storage_backend_id: str,
    workspace_id: str,
    owner_user_id: str,
    requested_by: str,
    permission_scope: PermissionScope | dict[str, object],
    extractor_adapters: Sequence[ExtractorAdapter] | None = None,
    extractor_names: Sequence[str] | None = None,
    run_configured_extractors: bool = False,
    extractor_run_store: ExtractorRunStore | None = None,
    observation_store: ObservationStore | None = None,
    config: Mapping[str, Any] | None = None,
    project_id: str | None = None,
    created_at: str | None = None,
    registered_at: str | None = None,
    job_created_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    audit_store: FileAuditLogStore | None = None,
    actor_user_id: str | None = None,
    session_id: str | None = None,
) -> FolderInboxScanResult:
    """Scan a trusted local folder and feed stable files into the ingestion spine.

    Public result payloads intentionally omit the trusted folder path, source
    paths, object-store roots, and parser-local paths. Callers keep stability
    snapshots separately and pass them back on the next scan.
    """

    _validate_run_configuration(
        run_configured_extractors=run_configured_extractors,
        extractor_adapters=extractor_adapters,
        extractor_run_store=extractor_run_store,
        observation_store=observation_store,
    )
    folder = Path(folder_path).expanduser().resolve()
    if not folder.is_dir():
        raise FileNotFoundError("local data resource folder does not exist")

    resolved_previous = _normalize_previous_snapshots(previous_snapshots)
    names = _resolve_extractor_names(
        extractor_adapters=extractor_adapters,
        extractor_names=extractor_names,
    )
    snapshots: dict[str, FolderFileStabilitySnapshot] = {}
    items: list[FolderInboxItemResult] = []
    ignored_entry_count = 0

    for source_path in sorted(folder.iterdir(), key=lambda path: path.name):
        if not source_path.is_file() or source_path.is_symlink():
            ignored_entry_count += 1
            continue

        snapshot = _snapshot_file(source_path)
        snapshots[snapshot.source_file_token] = snapshot
        previous = resolved_previous.get(snapshot.source_file_token)
        if previous is None or not snapshot.is_stable_with(previous):
            items.append(
                FolderInboxItemResult(
                    status="deferred_unstable",
                    source_file_token=snapshot.source_file_token,
                    content_hash=snapshot.content_hash,
                    file_size=snapshot.size_bytes,
                    warnings=["stability_snapshot_required"],
                )
            )
            continue

        try:
            items.append(
                _ingest_stable_file(
                    source_path,
                    snapshot=snapshot,
                    object_store=object_store,
                    asset_store=asset_store,
                    job_store=job_store,
                    storage_backend_id=storage_backend_id,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    requested_by=requested_by,
                    permission_scope=permission_scope,
                    extractor_adapters=extractor_adapters,
                    extractor_names=names,
                    run_configured_extractors=run_configured_extractors,
                    extractor_run_store=extractor_run_store,
                    observation_store=observation_store,
                    config=config,
                    project_id=project_id,
                    created_at=created_at,
                    registered_at=registered_at,
                    job_created_at=job_created_at,
                    started_at=started_at,
                    completed_at=completed_at,
                    audit_store=audit_store,
                    actor_user_id=actor_user_id,
                    session_id=session_id,
                )
            )
        except Exception:
            items.append(
                FolderInboxItemResult(
                    status="failed",
                    source_file_token=snapshot.source_file_token,
                    content_hash=snapshot.content_hash,
                    file_size=snapshot.size_bytes,
                    warnings=["stable_file_ingestion_failed"],
                )
            )

    return FolderInboxScanResult(
        items=items,
        snapshots=snapshots,
        ignored_entry_count=ignored_entry_count,
    )


def _ingest_stable_file(
    source_path: Path,
    *,
    snapshot: FolderFileStabilitySnapshot,
    object_store: FileObjectStore,
    asset_store: AssetStore,
    job_store: JobStore,
    storage_backend_id: str,
    workspace_id: str,
    owner_user_id: str,
    requested_by: str,
    permission_scope: PermissionScope | dict[str, object],
    extractor_adapters: Sequence[ExtractorAdapter] | None,
    extractor_names: Sequence[str],
    run_configured_extractors: bool,
    extractor_run_store: ExtractorRunStore | None,
    observation_store: ObservationStore | None,
    config: Mapping[str, Any] | None,
    project_id: str | None,
    created_at: str | None,
    registered_at: str | None,
    job_created_at: str | None,
    started_at: str | None,
    completed_at: str | None,
    audit_store: FileAuditLogStore | None,
    actor_user_id: str | None,
    session_id: str | None,
) -> FolderInboxItemResult:
    source_ref = _source_ref_for_snapshot(snapshot)
    expected_asset_id = _expected_asset_id(
        snapshot=snapshot,
        storage_backend_id=storage_backend_id,
        workspace_id=workspace_id,
        source_ref=source_ref,
    )
    asset = asset_store.get(expected_asset_id)
    warnings: list[str] = []

    if asset is None:
        asset = register_asset_from_local_file(
            source_path,
            object_store=object_store,
            asset_store=asset_store,
            storage_backend_id=storage_backend_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            permission_scope=permission_scope,
            source_ref=source_ref,
            expected_content_hash=snapshot.content_hash,
            project_id=project_id,
            created_at=created_at,
            registered_at=registered_at,
            audit_store=audit_store,
            actor_user_id=actor_user_id,
            session_id=session_id,
        )
    else:
        warnings.append("existing_asset")

    if not extractor_names:
        return _item_from_asset(
            status="registered",
            snapshot=snapshot,
            asset=asset,
            warnings=warnings,
        )

    job_id = stable_ingestion_job_id(
        asset_id=asset.asset_id,
        requested_by=requested_by,
        workspace_id=asset.workspace_id,
        extractor_names=list(extractor_names),
        config_hash=extraction_config_hash(config),
    )
    job = job_store.get(job_id)
    if job is None:
        job = create_ingestion_job(
            asset=asset,
            job_store=job_store,
            requested_by=requested_by,
            extractor_names=list(extractor_names),
            config=config,
            created_at=job_created_at,
            audit_store=audit_store,
            actor_user_id=actor_user_id,
            session_id=session_id,
        )
        warnings.append("created_job")
    else:
        warnings.append("existing_job")

    if not run_configured_extractors:
        return _item_from_asset(
            status="queued",
            snapshot=snapshot,
            asset=asset,
            ingestion_job_id=job.ingestion_job_id,
            ingestion_job_status=job.status,
            warnings=warnings,
        )

    if job.status == "pending":
        job = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id,
            asset_store=asset_store,
            job_store=job_store,
            object_store=object_store,
            extractor_run_store=extractor_run_store,  # type: ignore[arg-type]
            observation_store=observation_store,  # type: ignore[arg-type]
            extractor_adapters=list(extractor_adapters or []),
            config=config,
            started_at=started_at,
            completed_at=completed_at,
        )

    return _item_from_asset(
        status=_item_status_for_job(job.status),
        snapshot=snapshot,
        asset=asset,
        ingestion_job_id=job.ingestion_job_id,
        ingestion_job_status=job.status,
        extractor_run_ids=job.extractor_run_ids,
        observation_count=len(job.observation_ids),
        warnings=warnings,
    )


def _item_from_asset(
    *,
    status: str,
    snapshot: FolderFileStabilitySnapshot,
    asset: Asset,
    ingestion_job_id: str | None = None,
    ingestion_job_status: str | None = None,
    extractor_run_ids: Sequence[str] = (),
    observation_count: int = 0,
    warnings: Sequence[str] = (),
) -> FolderInboxItemResult:
    return FolderInboxItemResult(
        status=status,
        source_file_token=snapshot.source_file_token,
        content_hash=asset.content_hash,
        file_size=asset.file_size,
        mime_type=asset.mime_type,
        asset_id=asset.asset_id,
        object_uri=asset.object_uri,
        ingestion_job_id=ingestion_job_id,
        ingestion_job_status=ingestion_job_status,
        extractor_run_ids=list(extractor_run_ids),
        observation_count=observation_count,
        warnings=list(warnings),
    )


def _item_status_for_job(job_status: str) -> str:
    if job_status == "succeeded":
        return "ingested"
    if job_status == "failed":
        return "failed"
    return "queued"


def _validate_run_configuration(
    *,
    run_configured_extractors: bool,
    extractor_adapters: Sequence[ExtractorAdapter] | None,
    extractor_run_store: ExtractorRunStore | None,
    observation_store: ObservationStore | None,
) -> None:
    if not run_configured_extractors:
        return
    if not extractor_adapters:
        raise ValueError("extractor_adapters are required when run_configured_extractors is true")
    if extractor_run_store is None or observation_store is None:
        raise ValueError(
            "extractor_run_store and observation_store are required when running extractors"
        )


def _resolve_extractor_names(
    *,
    extractor_adapters: Sequence[ExtractorAdapter] | None,
    extractor_names: Sequence[str] | None,
) -> list[str]:
    if extractor_names is not None:
        if isinstance(extractor_names, (str, bytes)):
            raise ValueError("extractor names must be a sequence of non-empty strings")
        names = list(extractor_names)
    else:
        names = [adapter.name() for adapter in extractor_adapters or []]
    if not names:
        return []
    if not all(isinstance(name, str) and name for name in names):
        raise ValueError("extractor names must be non-empty strings")
    if len(set(names)) != len(names):
        raise ValueError("extractor names must be unique")
    return names


def _normalize_previous_snapshots(
    previous_snapshots: Mapping[str, FolderFileStabilitySnapshot | Mapping[str, Any]] | None,
) -> dict[str, FolderFileStabilitySnapshot]:
    normalized: dict[str, FolderFileStabilitySnapshot] = {}
    for key, value in (previous_snapshots or {}).items():
        snapshot = (
            value
            if isinstance(value, FolderFileStabilitySnapshot)
            else FolderFileStabilitySnapshot.from_dict(value)
        )
        normalized[str(key)] = snapshot
    return normalized


def _snapshot_file(source_path: Path) -> FolderFileStabilitySnapshot:
    stat = source_path.stat()
    content_hash, size_bytes = _hash_file(source_path)
    return FolderFileStabilitySnapshot(
        source_file_token=_source_file_token(source_path.name),
        size_bytes=size_bytes,
        modified_time_ns=stat.st_mtime_ns,
        content_hash=content_hash,
    )


def _source_file_token(relative_name: str) -> str:
    return "folderfile_" + sha256_json({"relative_name": relative_name}).split(":", 1)[1][:24]


def _hash_file(source_path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0
    with source_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size_bytes += len(chunk)
    return f"sha256:{digest.hexdigest()}", size_bytes


def _source_ref_for_snapshot(snapshot: FolderFileStabilitySnapshot) -> SourceRef:
    return SourceRef(
        source_system="local_folder_inbox",
        source_type="file_content",
        source_id=snapshot.content_hash,
    )


def _expected_asset_id(
    *,
    snapshot: FolderFileStabilitySnapshot,
    storage_backend_id: str,
    workspace_id: str,
    source_ref: SourceRef,
) -> str:
    return stable_asset_id(
        storage_backend_id=storage_backend_id,
        object_uri=_expected_object_uri(
            storage_backend_id=storage_backend_id,
            workspace_id=workspace_id,
            content_hash=snapshot.content_hash,
        ),
        content_hash=snapshot.content_hash,
        workspace_id=workspace_id,
        source_ref=source_ref,
    )


def _expected_object_uri(*, storage_backend_id: str, workspace_id: str, content_hash: str) -> str:
    return (
        f"formowl://object/{storage_backend_id}/{workspace_id}/"
        f"{content_hash.removeprefix('sha256:')}"
    )


__all__ = [
    "FolderFileStabilitySnapshot",
    "FolderInboxItemResult",
    "FolderInboxScanResult",
    "scan_local_data_resource_folder",
]
