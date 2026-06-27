from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.parse import urlparse

from formowl_contract import McpResultEnvelope, to_plain

from .backends import StorageBackendRegistry

_SAFE_LOCATOR_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA256_HEX = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class StoredObject:
    object_uri: str
    storage_backend_id: str
    workspace_id: str
    content_hash: str
    file_size: int
    original_filename: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


class FileObjectStore:
    """File-backed object store for copied local bytes."""

    def __init__(self, backend_registry: StorageBackendRegistry) -> None:
        self.backend_registry = backend_registry

    def copy_local_file(
        self,
        source_path: str | Path,
        *,
        storage_backend_id: str,
        workspace_id: str,
        expected_content_hash: str | None = None,
        original_filename: str | None = None,
    ) -> StoredObject:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"source file does not exist: {source}")
        _require_safe_segment(storage_backend_id, "storage_backend_id")
        _require_safe_segment(workspace_id, "workspace_id")
        resolved_original_filename = _resolve_original_filename(
            original_filename,
            default=source.name,
        )
        local_root = self._local_root(storage_backend_id)
        content_hash, file_size = _hash_file(source)
        if expected_content_hash is not None and expected_content_hash != content_hash:
            raise ValueError("source content hash does not match expected_content_hash")

        digest = content_hash.removeprefix("sha256:")
        object_uri = _object_uri(storage_backend_id, workspace_id, digest)
        object_dir = _object_dir(local_root, workspace_id, digest)
        object_dir.mkdir(parents=True, exist_ok=True)
        payload_path = object_dir / "payload.bin"
        metadata_path = object_dir / "metadata.json"

        if not payload_path.exists() or _hash_file(payload_path)[0] != content_hash:
            temp_path = object_dir / "payload.bin.tmp"
            shutil.copyfile(source, temp_path)
            copied_hash, copied_size = _hash_file(temp_path)
            if copied_hash != content_hash or copied_size != file_size:
                temp_path.unlink(missing_ok=True)
                raise ValueError("copied object hash verification failed")
            temp_path.replace(payload_path)

        stored = StoredObject(
            object_uri=object_uri,
            storage_backend_id=storage_backend_id,
            workspace_id=workspace_id,
            content_hash=content_hash,
            file_size=file_size,
            original_filename=resolved_original_filename,
        )
        _write_json(metadata_path, stored.to_dict())
        return stored

    def get_object(self, object_uri: str) -> StoredObject | None:
        try:
            storage_backend_id, workspace_id, digest = _parse_object_uri(object_uri)
            local_root = self._local_root(storage_backend_id)
        except (FileNotFoundError, ValueError):
            return None
        metadata_path = _object_dir(local_root, workspace_id, digest) / "metadata.json"
        if not metadata_path.exists():
            return None
        return StoredObject(**_read_json(metadata_path))

    def verify_object(self, object_uri: str, expected_content_hash: str | None = None) -> bool:
        stored = self.get_object(object_uri)
        if stored is None:
            return False
        expected_hash = expected_content_hash or stored.content_hash
        payload_path = self.resolve_object_path(object_uri)
        if payload_path is None or not payload_path.exists():
            return False
        actual_hash, actual_size = _hash_file(payload_path)
        return actual_hash == expected_hash and actual_size == stored.file_size

    def public_object_dict(self, object_uri: str) -> dict[str, Any] | None:
        stored = self.get_object(object_uri)
        if stored is None:
            return None
        return stored.to_dict()

    def object_mcp_envelope(self, object_uri: str) -> dict[str, Any]:
        safe_object_uri = _safe_public_object_uri(object_uri)
        if safe_object_uri is None:
            # Malformed caller input may be a host path, so never mirror it into MCP-facing data.
            return McpResultEnvelope(
                result_type="stored_object",
                status="not_found",
                data={},
                warnings=["Object URI was malformed."],
            ).to_dict()
        stored = self.public_object_dict(object_uri)
        if stored is None:
            return McpResultEnvelope(
                result_type="stored_object",
                status="not_found",
                data={"object_uri": safe_object_uri},
                warnings=[],
            ).to_dict()
        return McpResultEnvelope(
            result_type="stored_object",
            status="ok",
            data={"object": stored},
            warnings=[],
        ).to_dict()

    def resolve_object_path(self, object_uri: str) -> Path | None:
        try:
            storage_backend_id, workspace_id, digest = _parse_object_uri(object_uri)
            local_root = self._local_root(storage_backend_id)
        except (FileNotFoundError, ValueError):
            return None
        path = (_object_dir(local_root, workspace_id, digest) / "payload.bin").resolve()
        if not path.is_relative_to(local_root):
            raise ValueError("object path escaped storage backend root")
        if not path.exists():
            return None
        return path

    def _local_root(self, storage_backend_id: str) -> Path:
        local_root = self.backend_registry.resolve_local_root(storage_backend_id)
        if local_root is None:
            raise FileNotFoundError(f"local storage backend not found: {storage_backend_id}")
        return local_root


def _object_uri(storage_backend_id: str, workspace_id: str, digest: str) -> str:
    return f"formowl://object/{storage_backend_id}/{workspace_id}/{digest}"


def _parse_object_uri(object_uri: str) -> tuple[str, str, str]:
    if not isinstance(object_uri, str) or not object_uri:
        raise ValueError("object_uri must be a string")
    parsed = urlparse(object_uri)
    if parsed.scheme != "formowl" or parsed.netloc != "object":
        raise ValueError("object_uri must use formowl://object")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) != 3:
        raise ValueError("object_uri must include backend, workspace, and digest")
    storage_backend_id, workspace_id, digest = segments
    _require_safe_segment(storage_backend_id, "storage_backend_id")
    _require_safe_segment(workspace_id, "workspace_id")
    if not _SHA256_HEX.fullmatch(digest):
        raise ValueError("object_uri digest must be a sha256 hex digest")
    return storage_backend_id, workspace_id, digest


def _safe_public_object_uri(object_uri: str) -> str | None:
    try:
        _parse_object_uri(object_uri)
    except ValueError:
        return None
    return object_uri


def _object_dir(local_root: Path, workspace_id: str, digest: str) -> Path:
    return local_root / "objects" / workspace_id / digest[:2] / digest


def _require_safe_segment(value: str, name: str) -> None:
    if not value or value in {".", ".."} or not _SAFE_LOCATOR_SEGMENT.fullmatch(value):
        raise ValueError(f"{name} must be a safe locator segment")


def _resolve_original_filename(value: str | None, *, default: str) -> str:
    if value is None:
        return default
    # Stored object metadata is MCP-facing, so reject path-shaped caller input
    # instead of attempting to preserve or redact it later.
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or ":" in value
    ):
        raise ValueError("original_filename must be a file name, not a path")
    return value


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    file_size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            file_size += len(chunk)
    return f"sha256:{digest.hexdigest()}", file_size


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(to_plain(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
