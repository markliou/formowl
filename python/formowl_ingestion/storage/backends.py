from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from formowl_contract import (
    McpResultEnvelope,
    StorageBackend,
    sha256_json,
    stable_resource_contract_id,
    to_plain,
)

_SAFE_BACKEND_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class StorageBackendRegistry:
    """File-backed registry for physical storage backend metadata."""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.registry_dir = self.base_dir / "ingestion" / "storage-backends"
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    def register_local_backend(
        self,
        root_path: str | Path,
        *,
        workspace_scope: str,
        display_name: str = "Local filesystem backend",
        access_mode: str = "read_write",
        trust_level: str = "trusted_internal",
        health_status: str = "healthy",
        bandwidth_class: str | None = None,
        latency_class: str | None = None,
        allowed_workers: list[str] | None = None,
        storage_backend_id: str | None = None,
    ) -> StorageBackend:
        local_root_path = Path(root_path).expanduser().resolve()
        local_root_path.mkdir(parents=True, exist_ok=True)
        root_identity_hash = _short_hash({"local_root_path": str(local_root_path)})
        backend_id = storage_backend_id or stable_resource_contract_id(
            "storage",
            "StorageBackend",
            {
                "type": "local_fs",
                "workspace_scope": workspace_scope,
                "root_identity_hash": root_identity_hash,
                "display_name": display_name,
            },
        )
        backend = StorageBackend(
            storage_backend_id=backend_id,
            type="local_fs",
            display_name=display_name,
            access_mode=access_mode,
            trust_level=trust_level,
            workspace_scope=workspace_scope,
            health_status=health_status,
            root_prefix=f"formowl://storage/{backend_id}",
            bandwidth_class=bandwidth_class,
            latency_class=latency_class,
            allowed_workers=allowed_workers or [],
        )
        return self.register_backend(
            backend,
            private_config={"local_root_path": str(local_root_path)},
        )

    def register_backend(
        self,
        backend: StorageBackend | dict[str, Any],
        *,
        private_config: dict[str, Any] | None = None,
    ) -> StorageBackend:
        validated_backend = StorageBackend.from_dict(to_plain(backend))
        public_backend = _public_backend_dict(validated_backend)
        private = to_plain(private_config or {})
        if validated_backend.internal_endpoint is not None:
            private.setdefault("internal_endpoint", validated_backend.internal_endpoint)
        backend_id = str(public_backend["storage_backend_id"])
        record = {
            "backend": public_backend,
            "private": private,
        }
        _write_json(self._record_path(backend_id), record)
        return StorageBackend.from_dict(public_backend)

    def get_backend(self, storage_backend_id: str) -> StorageBackend | None:
        record = self._read_record(storage_backend_id)
        if record is None:
            return None
        return StorageBackend.from_dict(record["backend"])

    def list_backends(self) -> list[StorageBackend]:
        backends: list[StorageBackend] = []
        for path in sorted(self.registry_dir.glob("*.json")):
            record = _read_json(path)
            backends.append(StorageBackend.from_dict(record["backend"]))
        return backends

    def resolve_local_root(self, storage_backend_id: str) -> Path | None:
        record = self._read_record(storage_backend_id)
        if record is None:
            return None
        if record["backend"].get("type") != "local_fs":
            return None
        root_path = record.get("private", {}).get("local_root_path")
        if not root_path:
            return None
        return Path(str(root_path)).resolve()

    def public_backend_dict(self, storage_backend_id: str) -> dict[str, Any] | None:
        backend = self.get_backend(storage_backend_id)
        if backend is None:
            return None
        return backend.to_dict()

    def backend_mcp_envelope(self, storage_backend_id: str) -> dict[str, Any]:
        backend = self.public_backend_dict(storage_backend_id)
        if backend is None:
            return McpResultEnvelope(
                result_type="storage_backend",
                status="not_found",
                data={"storage_backend_id": storage_backend_id},
                warnings=[],
            ).to_dict()
        return McpResultEnvelope(
            result_type="storage_backend",
            status="ok",
            data={"backend": backend},
            warnings=[],
        ).to_dict()

    def _read_record(self, storage_backend_id: str) -> dict[str, Any] | None:
        path = self._record_path(storage_backend_id)
        if not path.exists():
            return None
        return _read_json(path)

    def _record_path(self, storage_backend_id: str) -> Path:
        if not storage_backend_id or not _SAFE_BACKEND_ID.fullmatch(storage_backend_id):
            raise ValueError("storage_backend_id must be a safe file name")
        return self.registry_dir / f"{storage_backend_id}.json"


def _public_backend_dict(backend: StorageBackend) -> dict[str, Any]:
    data = backend.to_dict()
    data.pop("internal_endpoint", None)
    return data


def _short_hash(payload: Any) -> str:
    return sha256_json(payload).split(":", 1)[1][:16]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(to_plain(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)
