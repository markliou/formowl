from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import shutil
from typing import Any
import uuid

from formowl_contract import to_plain
from formowl_auth.audit import FileAuditLogStore, record_evidence_fetch


class FileEvidenceSnapshotStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)

    def save_snapshot(self, write: dict[str, Any]) -> dict[str, str]:
        snapshot = to_plain(write["snapshot"])
        snapshot_id = _validate_snapshot_id(snapshot["evidence_snapshot_id"])
        source = _first_source(snapshot)
        captured_at = _parse_datetime(str(snapshot["captured_at"]))
        directory = (
            self.base_dir
            / "raw"
            / "evidence"
            / source
            / f"{captured_at.year:04d}"
            / f"{captured_at.month:02d}"
            / f"{captured_at.day:02d}"
            / snapshot_id
        )
        parent_directory = directory.parent
        parent_directory.mkdir(parents=True, exist_ok=True)
        storage_uri = directory.as_posix()
        snapshot["storage_uri"] = storage_uri
        if directory.exists():
            if _is_complete_snapshot_directory(directory):
                return {"evidence_snapshot_id": snapshot_id, "storage_uri": storage_uri}
            raise RuntimeError(f"Evidence snapshot directory is incomplete: {snapshot_id}")

        temporary_directory = parent_directory / f"{snapshot_id}.tmp-{uuid.uuid4().hex}"
        temporary_directory.mkdir()
        try:
            _write_json(temporary_directory / "request.json", write.get("request_payload", {}))
            _write_json(temporary_directory / "response.json", write.get("response_payload", {}))
            normalized = str(write.get("normalized_markdown") or "")
            (temporary_directory / "normalized.md").write_text(normalized, encoding="utf-8")
            _write_json(
                temporary_directory / "metadata.json",
                {"snapshot": snapshot, "metadata": write.get("metadata", {})},
            )
            _write_json(temporary_directory / "snapshot.json", snapshot)
            temporary_directory.rename(directory)
        except BaseException:
            shutil.rmtree(temporary_directory, ignore_errors=True)
            raise
        return {"evidence_snapshot_id": snapshot_id, "storage_uri": storage_uri}

    def get_snapshot(
        self,
        evidence_snapshot_id: str,
        *,
        audit_store: FileAuditLogStore | None = None,
        actor_user_id: str | None = None,
        session_id: str | None = None,
        workspace_id: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any] | None:
        evidence_snapshot_id = _validate_snapshot_id(evidence_snapshot_id)
        for path in self.base_dir.glob(
            f"raw/evidence/*/*/*/*/{evidence_snapshot_id}/metadata.json"
        ):
            if not _is_complete_snapshot_directory(path.parent):
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            _log_evidence_fetch(
                audit_store=audit_store,
                actor_user_id=actor_user_id,
                session_id=session_id,
                workspace_id=workspace_id,
                evidence_snapshot_id=evidence_snapshot_id,
                timestamp=timestamp,
                status="ok",
            )
            return payload.get("snapshot")
        _log_evidence_fetch(
            audit_store=audit_store,
            actor_user_id=actor_user_id,
            session_id=session_id,
            workspace_id=workspace_id,
            evidence_snapshot_id=evidence_snapshot_id,
            timestamp=timestamp,
            status="not_found",
        )
        return None

    def get_snapshot_payload(
        self,
        evidence_snapshot_id: str,
        *,
        audit_store: FileAuditLogStore | None = None,
        actor_user_id: str | None = None,
        session_id: str | None = None,
        workspace_id: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any] | None:
        evidence_snapshot_id = _validate_snapshot_id(evidence_snapshot_id)
        for path in self.base_dir.glob(
            f"raw/evidence/*/*/*/*/{evidence_snapshot_id}/response.json"
        ):
            if not _is_complete_snapshot_directory(path.parent):
                continue
            _log_evidence_fetch(
                audit_store=audit_store,
                actor_user_id=actor_user_id,
                session_id=session_id,
                workspace_id=workspace_id,
                evidence_snapshot_id=evidence_snapshot_id,
                timestamp=timestamp,
                status="ok",
            )
            return json.loads(path.read_text(encoding="utf-8"))
        _log_evidence_fetch(
            audit_store=audit_store,
            actor_user_id=actor_user_id,
            session_id=session_id,
            workspace_id=workspace_id,
            evidence_snapshot_id=evidence_snapshot_id,
            timestamp=timestamp,
            status="not_found",
        )
        return None


def _first_source(snapshot: dict[str, Any]) -> str:
    source_refs = snapshot.get("source_refs") or []
    if source_refs and isinstance(source_refs[0], dict):
        return str(source_refs[0].get("source_system") or "unknown")
    return "unknown"


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(to_plain(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


_REQUIRED_SNAPSHOT_FILES = {
    "request.json",
    "response.json",
    "normalized.md",
    "metadata.json",
    "snapshot.json",
}
_SAFE_SNAPSHOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _is_complete_snapshot_directory(directory: Path) -> bool:
    return all((directory / name).is_file() for name in _REQUIRED_SNAPSHOT_FILES)


def _validate_snapshot_id(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_SNAPSHOT_ID.fullmatch(value):
        raise ValueError("evidence_snapshot_id must be a safe FormOwl identifier")
    return value


def _log_evidence_fetch(
    *,
    audit_store: FileAuditLogStore | None,
    actor_user_id: str | None,
    session_id: str | None,
    workspace_id: str | None,
    evidence_snapshot_id: str,
    timestamp: str | None,
    status: str,
) -> None:
    if audit_store is None:
        return
    # Existing prototype calls can read snapshots without audit context; any
    # user-facing gateway path that fetches evidence should supply it.
    if not actor_user_id or not session_id or not workspace_id:
        raise ValueError(
            "actor_user_id, session_id, and workspace_id are required when audit_store is provided"
        )
    record_evidence_fetch(
        audit_store,
        actor_user_id=actor_user_id,
        evidence_snapshot_id=evidence_snapshot_id,
        workspace_id=workspace_id,
        session_id=session_id,
        timestamp=timestamp,
        status=status,
    )
