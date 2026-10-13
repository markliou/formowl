from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any, Callable
from urllib.parse import urlparse
import uuid

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

    def __init__(
        self,
        backend_registry: StorageBackendRegistry,
        *,
        verification_observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.backend_registry = backend_registry
        self.verification_observer = verification_observer

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

    def object_uri_for_content(
        self,
        *,
        storage_backend_id: str,
        workspace_id: str,
        content_hash: str,
    ) -> str:
        _require_safe_segment(storage_backend_id, "storage_backend_id")
        _require_safe_segment(workspace_id, "workspace_id")
        if not isinstance(content_hash, str) or not content_hash.startswith("sha256:"):
            raise ValueError("content_hash must be sha256")
        digest = content_hash.removeprefix("sha256:")
        if not _SHA256_HEX.fullmatch(digest):
            raise ValueError("content_hash must be sha256")
        return _object_uri(storage_backend_id, workspace_id, digest)

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
        facts: dict[str, Any] = {
            "expected_content_hash": None,
            "expected_file_size": None,
            "opened_file_size": None,
            "actual_content_hash": None,
            "actual_file_size": None,
            "read_completed": False,
            "file_stat_stable": None,
            "path_stat_matches": None,
        }
        try:
            stored = self.get_object(object_uri)
        except (OSError, ValueError, TypeError):
            return self._verification_result(facts, "metadata_unreadable")
        if stored is None:
            return self._verification_result(facts, "metadata_unavailable")
        expected_hash = stored.content_hash if expected_content_hash is None else expected_content_hash
        if (
            not isinstance(expected_hash, str)
            or not expected_hash.startswith("sha256:")
            or not _SHA256_HEX.fullmatch(expected_hash.removeprefix("sha256:"))
            or type(stored.file_size) is not int or stored.file_size < 0
        ):
            return self._verification_result(facts, "verification_expectation_invalid")
        facts.update(expected_content_hash=expected_hash, expected_file_size=stored.file_size)
        try:
            payload_path = self.resolve_object_path(object_uri)
            if payload_path is None:
                return self._verification_result(facts, "payload_unavailable")
            actual_hash, actual_size = _hash_file(payload_path, verification_details=facts)
            # The governed locator may traverse a symlink. Its resolved target
            # must still be the path checked against the opened descriptor;
            # checking only that old target misses a link/directory swap.
            if self.resolve_object_path(object_uri) != payload_path:
                facts["path_stat_matches"] = False
                return self._verification_result(facts, "path_changed_during_read")
        except _FileChangedDuringHash:
            if not facts["file_stat_stable"]:
                reason = "file_changed_during_read"
            elif not facts["path_stat_matches"]:
                reason = "path_changed_during_read"
            else:
                reason = "read_size_mismatch"
            return self._verification_result(facts, reason)
        except (OSError, ValueError):
            return self._verification_result(facts, "payload_read_failed")
        if actual_size != stored.file_size:
            return self._verification_result(facts, "size_mismatch")
        if actual_hash != expected_hash:
            return self._verification_result(facts, "hash_mismatch")
        return self._verification_result(facts, "verified")

    def _verification_result(self, facts: dict[str, Any], reason_code: str) -> bool:
        verified = reason_code == "verified"
        if self.verification_observer is not None:
            self.verification_observer({**facts, "verified": verified, "reason_code": reason_code})
        return verified

    def delete_object(self, object_uri: str) -> None:
        payload_path = self.resolve_object_path(object_uri)
        if payload_path is None:
            return
        object_dir = payload_path.parent
        metadata_path = object_dir / "metadata.json"
        payload_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        _remove_empty_parents(object_dir, stop_at=object_dir.parents[2])

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


class _FileChangedDuringHash(OSError):
    """The bytes read cannot be bound to one stable file at the requested path."""


def _stat_signature(value: os.stat_result) -> tuple[int, ...]:
    # Exclude atime: reading a file may update it without changing its bytes.
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _hash_file(
    path: Path, *, verification_details: dict[str, Any] | None = None,
) -> tuple[str, int]:
    digest = hashlib.sha256()
    file_size = 0
    details = verification_details if verification_details is not None else {}
    details.update(actual_file_size=0, read_completed=False)
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        details["opened_file_size"] = before.st_size
        try:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                file_size += len(chunk)
        finally:
            details["actual_file_size"] = file_size
        content_hash = f"sha256:{digest.hexdigest()}"
        details.update(actual_content_hash=content_hash, read_completed=True)
        after = os.fstat(handle.fileno())
        stable = _stat_signature(before) == _stat_signature(after)
        try:
            path_matches = _stat_signature(after) == _stat_signature(path.stat())
        except FileNotFoundError:
            path_matches = False
        details.update(file_stat_stable=stable, path_stat_matches=path_matches)
        if not stable or not path_matches or file_size != before.st_size:
            raise _FileChangedDuringHash("file changed during hashing")
    return content_hash, file_size


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    serialized = json.dumps(to_plain(payload), ensure_ascii=False, indent=2, sort_keys=True)
    # Same-content imports can publish this metadata concurrently. Keep the
    # previous complete record visible until this writer's private file is ready.
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = None  # The stream now owns the descriptor.
        with handle as stream:
            stream.write(serialized)
            stream.flush()
            try:
                mode = stat.S_IMODE(path.stat().st_mode)
            except FileNotFoundError:
                # Measure normal create permissions without changing the
                # process-wide umask or exposing metadata in a readable file.
                # This separate probe stays empty for its entire lifetime.
                probe = temporary.with_suffix(".mode")
                probe_handle = probe.open("x", encoding="utf-8")
                try:
                    with probe_handle:
                        mode = stat.S_IMODE(os.fstat(probe_handle.fileno()).st_mode)
                finally:
                    probe.unlink(missing_ok=True)
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _remove_empty_parents(path: Path, *, stop_at: Path) -> None:
    current = path
    stop = stop_at.resolve()
    while current.exists() and current.resolve().is_relative_to(stop):
        if current.resolve() == stop:
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
