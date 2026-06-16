from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from formowl_contract import to_plain


class FileEvidenceSnapshotStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)

    def save_snapshot(self, write: dict[str, Any]) -> dict[str, str]:
        snapshot = to_plain(write["snapshot"])
        snapshot_id = str(snapshot["evidence_snapshot_id"])
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
        directory.mkdir(parents=True, exist_ok=True)
        storage_uri = directory.as_posix()
        snapshot["storage_uri"] = storage_uri

        _write_json(directory / "request.json", write.get("request_payload", {}))
        _write_json(directory / "response.json", write.get("response_payload", {}))
        normalized = str(write.get("normalized_markdown") or "")
        (directory / "normalized.md").write_text(normalized, encoding="utf-8")
        _write_json(directory / "metadata.json", {"snapshot": snapshot, "metadata": write.get("metadata", {})})
        _write_json(directory / "snapshot.json", snapshot)
        return {"evidence_snapshot_id": snapshot_id, "storage_uri": storage_uri}

    def get_snapshot(self, evidence_snapshot_id: str) -> dict[str, Any] | None:
        for path in self.base_dir.glob(f"raw/evidence/*/*/*/*/{evidence_snapshot_id}/metadata.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload.get("snapshot")
        return None

    def get_snapshot_payload(self, evidence_snapshot_id: str) -> dict[str, Any] | None:
        for path in self.base_dir.glob(f"raw/evidence/*/*/*/*/{evidence_snapshot_id}/response.json"):
            return json.loads(path.read_text(encoding="utf-8"))
        return None


def _first_source(snapshot: dict[str, Any]) -> str:
    source_refs = snapshot.get("source_refs") or []
    if source_refs and isinstance(source_refs[0], dict):
        return str(source_refs[0].get("source_system") or "unknown")
    return "unknown"


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(to_plain(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
