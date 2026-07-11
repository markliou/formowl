"""File-backed audit logging for Phase 0 identity and ingestion flows."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from formowl_contract import AuditLog, now_iso, stable_resource_contract_id
from formowl_core import read_json_object, write_json_atomic

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class FileAuditLogStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir) / "audit" / "logs"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create(self, audit_log: AuditLog | dict[str, Any]) -> AuditLog:
        validated = _validate_audit_log(audit_log)
        payload = validated.to_dict()
        write_json_atomic(self._record_path(validated.audit_log_id), payload)
        return validated

    def get(self, audit_log_id: str) -> AuditLog | None:
        path = self._record_path(audit_log_id)
        if not path.exists():
            return None
        return AuditLog.from_dict(read_json_object(path))

    def delete(self, audit_log_id: str) -> None:
        path = self._record_path(audit_log_id)
        if path.exists():
            path.unlink()

    def list(self) -> list[AuditLog]:
        return [
            AuditLog.from_dict(read_json_object(path))
            for path in sorted(self.base_dir.glob("*.json"))
        ]

    def _record_path(self, audit_log_id: str) -> Path:
        if not audit_log_id or not _SAFE_RECORD_ID.fullmatch(audit_log_id):
            raise ValueError("audit_log_id must be a safe file name")
        return self.base_dir / f"{audit_log_id}.json"


def write_audit_log(
    audit_store: FileAuditLogStore,
    *,
    actor_user_id: str,
    action: str,
    target_type: str,
    target_id: str,
    session_id: str,
    timestamp: str | None = None,
    workspace_id: str | None = None,
    status: str | None = None,
    grant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    audit_log_id: str | None = None,
) -> AuditLog:
    resolved_timestamp = timestamp or now_iso()
    # Content-derived ids keep file-backed tests deterministic while still
    # preserving the event fields that make each audit record traceable.
    resolved_audit_log_id = audit_log_id or stable_resource_contract_id(
        "audit",
        "AuditLog",
        {
            "actor_user_id": actor_user_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "session_id": session_id,
            "timestamp": resolved_timestamp,
            "workspace_id": workspace_id,
            "status": status,
            "grant_id": grant_id,
            "metadata": metadata,
        },
    )
    return audit_store.create(
        AuditLog(
            audit_log_id=resolved_audit_log_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            grant_id=grant_id,
            session_id=session_id,
            workspace_id=workspace_id,
            status=status,
            timestamp=resolved_timestamp,
            metadata=metadata,
        )
    )


def record_actor_selection(
    audit_store: FileAuditLogStore,
    *,
    actor_user_id: str,
    session_id: str,
    workspace_id: str | None = None,
    timestamp: str | None = None,
    status: str = "ok",
) -> AuditLog:
    return write_audit_log(
        audit_store,
        actor_user_id=actor_user_id,
        action="actor_selected",
        target_type="user",
        target_id=actor_user_id,
        session_id=session_id,
        workspace_id=workspace_id,
        timestamp=timestamp,
        status=status,
    )


def record_asset_registration(
    audit_store: FileAuditLogStore,
    *,
    actor_user_id: str,
    asset_id: str,
    workspace_id: str,
    session_id: str,
    timestamp: str | None = None,
    status: str = "ok",
) -> AuditLog:
    return write_audit_log(
        audit_store,
        actor_user_id=actor_user_id,
        action="asset_registered",
        target_type="asset",
        target_id=asset_id,
        session_id=session_id,
        workspace_id=workspace_id,
        timestamp=timestamp,
        status=status,
    )


def record_asset_reference_upload(
    audit_store: FileAuditLogStore,
    *,
    actor_user_id: str,
    asset_id: str,
    workspace_id: str,
    session_id: str,
    controlled_import_reason: str,
    timestamp: str | None = None,
    status: str = "ok",
) -> AuditLog:
    return write_audit_log(
        audit_store,
        actor_user_id=actor_user_id,
        action="asset_reference_uploaded",
        target_type="asset",
        target_id=asset_id,
        session_id=session_id,
        workspace_id=workspace_id,
        timestamp=timestamp,
        status=status,
        metadata={"controlled_import_reason": controlled_import_reason},
    )


def record_ingestion_job_creation(
    audit_store: FileAuditLogStore,
    *,
    actor_user_id: str,
    ingestion_job_id: str,
    workspace_id: str,
    session_id: str,
    timestamp: str | None = None,
    status: str = "ok",
) -> AuditLog:
    return write_audit_log(
        audit_store,
        actor_user_id=actor_user_id,
        action="ingestion_job_created",
        target_type="ingestion_job",
        target_id=ingestion_job_id,
        session_id=session_id,
        workspace_id=workspace_id,
        timestamp=timestamp,
        status=status,
    )


def record_chatgpt_session_capture(
    audit_store: FileAuditLogStore,
    *,
    actor_user_id: str,
    capture_id: str,
    workspace_id: str,
    session_id: str,
    timestamp: str | None = None,
    status: str = "ok",
) -> AuditLog:
    return write_audit_log(
        audit_store,
        actor_user_id=actor_user_id,
        action="chatgpt_session_captured",
        target_type="chatgpt_session_capture",
        target_id=capture_id,
        session_id=session_id,
        workspace_id=workspace_id,
        timestamp=timestamp,
        status=status,
    )


def record_evidence_fetch(
    audit_store: FileAuditLogStore,
    *,
    actor_user_id: str,
    evidence_snapshot_id: str,
    workspace_id: str,
    session_id: str,
    timestamp: str | None = None,
    status: str = "ok",
) -> AuditLog:
    return write_audit_log(
        audit_store,
        actor_user_id=actor_user_id,
        action="evidence_fetched",
        target_type="evidence_snapshot",
        target_id=evidence_snapshot_id,
        session_id=session_id,
        workspace_id=workspace_id,
        timestamp=timestamp,
        status=status,
    )


def record_permission_denied(
    audit_store: FileAuditLogStore,
    *,
    actor_user_id: str,
    target_type: str,
    target_id: str,
    workspace_id: str,
    session_id: str,
    timestamp: str | None = None,
    reason: str | None = None,
) -> AuditLog:
    metadata = {"reason": reason} if reason else None
    return write_audit_log(
        audit_store,
        actor_user_id=actor_user_id,
        action="permission_denied",
        target_type=target_type,
        target_id=target_id,
        session_id=session_id,
        workspace_id=workspace_id,
        timestamp=timestamp,
        status="permission_denied",
        metadata=metadata,
    )


def record_upload_session_creation(
    audit_store: FileAuditLogStore,
    *,
    actor_user_id: str,
    upload_session_id: str,
    workspace_id: str,
    session_id: str,
    timestamp: str | None = None,
    status: str = "ok",
    audit_log_id: str | None = None,
) -> AuditLog:
    return write_audit_log(
        audit_store,
        actor_user_id=actor_user_id,
        action="upload_session_created",
        target_type="upload_session",
        target_id=upload_session_id,
        session_id=session_id,
        workspace_id=workspace_id,
        timestamp=timestamp,
        status=status,
        audit_log_id=audit_log_id,
    )


def record_upload_session_file_received(
    audit_store: FileAuditLogStore,
    *,
    actor_user_id: str,
    upload_session_id: str,
    asset_id: str,
    workspace_id: str,
    session_id: str,
    accepted_file_type: str,
    file_size_bytes: int,
    timestamp: str | None = None,
    status: str = "ok",
) -> AuditLog:
    return write_audit_log(
        audit_store,
        actor_user_id=actor_user_id,
        action="upload_session_file_received",
        target_type="upload_session",
        target_id=upload_session_id,
        session_id=session_id,
        workspace_id=workspace_id,
        timestamp=timestamp,
        status=status,
        metadata={
            "asset_id": asset_id,
            "accepted_file_type": accepted_file_type,
            "file_size_bytes": file_size_bytes,
        },
    )


def _validate_audit_log(audit_log: AuditLog | dict[str, Any]) -> AuditLog:
    if isinstance(audit_log, dict):
        return AuditLog.from_dict(audit_log)
    return AuditLog.from_dict(audit_log.to_dict())
