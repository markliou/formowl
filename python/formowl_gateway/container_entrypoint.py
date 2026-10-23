"""Stage root-owned container secrets, drop privileges, and exec FormOwl."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping, Sequence


SERVICE_UID = 10001
SERVICE_GID = 10001
SECRET_SOURCE_ROOT = Path("/run/secrets")
STAGED_SECRET_ROOT = Path("/run/formowl-secrets")
_MAX_SECRET_BYTES = 64 * 1024
_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_SAFE_SECRET_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FILE_SECRET_ENV = {
    "FORMOWL_DATABASE_DSN_FILE": ("formowl_database_dsn", "formowl_database_dsn"),
    "FORMOWL_GOOGLE_CLIENT_SECRET_FILE": (
        "formowl_google_client_secret",
        "formowl_google_client_secret",
    ),
    "FORMOWL_OAUTH_STATE_ENCRYPTION_KEY_FILE": (
        "formowl_state_encryption_key",
        "formowl_state_encryption_key",
    ),
}
_SIGNING_MANIFEST_ENV = "FORMOWL_OAUTH_SIGNING_KEY_SET_FILE"
_SIGNING_MANIFEST_SOURCE = "formowl_signing_key_set"
_ALLOWED_SIGNING_KEY_SOURCES = {
    SECRET_SOURCE_ROOT / "formowl_signing_key_current",
    SECRET_SOURCE_ROOT / "formowl_signing_key_previous",
}
_SAFE_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_EXTERNAL_SECRET_STAGE_ENV = "FORMOWL_CONTAINER_STAGE_SECRETS"
_PR_CAPBSET_DROP = 24
_PR_SET_NO_NEW_PRIVS = 38
_CAP_LAST_CAP_PATH = Path("/proc/sys/kernel/cap_last_cap")
_PROCESS_STATUS_PATH = Path("/proc/self/status")
_MAX_CAPABILITY_INDEX = 255
_FORMOWL_COMMANDS = {
    "init-secrets",
    "migrate",
    "preflight",
    "serve",
    "bootstrap-owner",
    "invite-user",
    "lookup-user",
    "list-users",
    "remove-workspace-member",
    "restore-workspace-member",
    "lookup-token-session",
    "list-token-sessions",
    "export-issue20-live-audit",
    "revoke-token-session",
}


class ContainerEntrypointError(RuntimeError):
    """Machine-safe launcher failure without secret values or host paths."""

    def __init__(self, code: str) -> None:
        safe_code = code if _SAFE_ERROR_CODE.fullmatch(code) else "container_entrypoint_failed"
        self.code = safe_code
        super().__init__(safe_code)


def _source_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ContainerEntrypointError("container_secret_source_invalid")
    path = Path(value)
    if not path.is_absolute() or path.parent != SECRET_SOURCE_ROOT:
        raise ContainerEntrypointError("container_secret_source_invalid")
    return path


def _expected_source_path(value: str, expected_name: str) -> Path:
    path = _source_path(value)
    if path != SECRET_SOURCE_ROOT / expected_name:
        raise ContainerEntrypointError("container_secret_source_invalid")
    return path


def _read_secret(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_SECRET_BYTES:
            raise ContainerEntrypointError("container_secret_source_invalid")
        chunks: list[bytes] = []
        remaining = _MAX_SECRET_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks)
    except ContainerEntrypointError:
        raise
    except OSError:
        raise ContainerEntrypointError("container_secret_source_unavailable") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                raise ContainerEntrypointError("container_secret_source_unavailable") from None
    if not value or len(value) > _MAX_SECRET_BYTES or b"\x00" in value:
        raise ContainerEntrypointError("container_secret_source_invalid")
    return value


def _prepare_staging_root() -> None:
    try:
        if STAGED_SECRET_ROOT.is_symlink() or not STAGED_SECRET_ROOT.is_dir():
            raise ContainerEntrypointError("container_secret_stage_unavailable")
        if any(STAGED_SECRET_ROOT.iterdir()):
            raise ContainerEntrypointError("container_secret_stage_not_empty")
        os.chown(STAGED_SECRET_ROOT, 0, 0)
        os.chmod(STAGED_SECRET_ROOT, 0o700)
    except ContainerEntrypointError:
        raise
    except OSError:
        raise ContainerEntrypointError("container_secret_stage_unavailable") from None


def _write_staged_secret(name: str, value: bytes) -> Path:
    if not _SAFE_SECRET_NAME.fullmatch(name):
        raise ContainerEntrypointError("container_secret_stage_invalid")
    path = STAGED_SECRET_ROOT / name
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(path, flags, 0o400)
        created = True
        os.fchmod(descriptor, 0o400)
        os.fchown(descriptor, SERVICE_UID, SERVICE_GID)
        offset = 0
        while offset < len(value):
            written = os.write(descriptor, value[offset:])
            if written <= 0:
                raise OSError("staged secret write made no progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if created:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                raise ContainerEntrypointError("container_secret_stage_failed") from None
        raise ContainerEntrypointError("container_secret_stage_failed") from None
    return path


def _stage_signing_manifest(source: Path) -> Path:
    try:
        manifest = json.loads(_read_secret(source).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ContainerEntrypointError("container_signing_manifest_invalid") from None
    if not isinstance(manifest, dict) or set(manifest) != {"version", "keys"}:
        raise ContainerEntrypointError("container_signing_manifest_invalid")
    keys = manifest.get("keys")
    if manifest.get("version") != 1 or not isinstance(keys, list) or not keys:
        raise ContainerEntrypointError("container_signing_manifest_invalid")
    rewritten_keys: list[dict[str, Any]] = []
    source_paths: set[Path] = set()
    key_ids: set[str] = set()
    for index, item in enumerate(keys):
        if (
            not isinstance(item, Mapping)
            or not {"kid", "private_key_file", "active"} <= set(item)
            or not set(item) <= {"kid", "private_key_file", "active", "verify_until"}
        ):
            raise ContainerEntrypointError("container_signing_manifest_invalid")
        kid = item.get("kid")
        private_key_file = item.get("private_key_file")
        active = item.get("active")
        verify_until = item.get("verify_until")
        if (
            not isinstance(kid, str)
            or not _SAFE_KEY_ID.fullmatch(kid)
            or kid in key_ids
            or not isinstance(private_key_file, str)
            or not isinstance(active, bool)
            or (active and verify_until is not None)
            or (not active and not isinstance(verify_until, str))
        ):
            raise ContainerEntrypointError("container_signing_manifest_invalid")
        key_source = _source_path(private_key_file)
        if key_source not in _ALLOWED_SIGNING_KEY_SOURCES or key_source in source_paths:
            raise ContainerEntrypointError("container_signing_manifest_invalid")
        key_ids.add(kid)
        source_paths.add(key_source)
        key_path = _write_staged_secret(
            f"formowl_signing_key_{index}",
            _read_secret(key_source),
        )
        rewritten_keys.append({**dict(item), "private_key_file": str(key_path)})
    if (
        len(rewritten_keys) > len(_ALLOWED_SIGNING_KEY_SOURCES)
        or sum(item["active"] is True for item in rewritten_keys) != 1
    ):
        raise ContainerEntrypointError("container_signing_manifest_invalid")
    payload = json.dumps(
        {"version": 1, "keys": rewritten_keys},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _write_staged_secret("formowl_signing_key_set", payload)


def stage_configured_secrets(environ: dict[str, str]) -> int:
    configured = [name for name in (*_FILE_SECRET_ENV, _SIGNING_MANIFEST_ENV) if environ.get(name)]
    if not configured:
        return 0
    original_environ = dict(environ)
    _prepare_staging_root()
    try:
        staged_count = 0
        for environment_name, (source_name, staged_name) in _FILE_SECRET_ENV.items():
            configured_path = environ.get(environment_name)
            if configured_path is None:
                raise ContainerEntrypointError("container_secret_configuration_incomplete")
            staged_path = _write_staged_secret(
                staged_name,
                _read_secret(_expected_source_path(configured_path, source_name)),
            )
            environ[environment_name] = str(staged_path)
            staged_count += 1
        manifest_path = environ.get(_SIGNING_MANIFEST_ENV)
        if manifest_path is None:
            raise ContainerEntrypointError("container_secret_configuration_incomplete")
        environ[_SIGNING_MANIFEST_ENV] = str(
            _stage_signing_manifest(_expected_source_path(manifest_path, _SIGNING_MANIFEST_SOURCE))
        )
        staged_count += 1
        try:
            os.chmod(STAGED_SECRET_ROOT, 0o700)
            os.chown(STAGED_SECRET_ROOT, SERVICE_UID, SERVICE_GID)
        except OSError:
            raise ContainerEntrypointError("container_secret_stage_failed") from None
    except BaseException:
        try:
            # The root was proven empty before this transaction, so every entry
            # now present was created by this failed call.
            for path in STAGED_SECRET_ROOT.iterdir():
                path.unlink()
        except OSError:
            raise ContainerEntrypointError("container_secret_stage_failed") from None
        finally:
            try:
                environ.clear()
                environ.update(original_environ)
            except (OSError, TypeError, ValueError):
                raise ContainerEntrypointError("container_secret_stage_failed") from None
        raise
    return staged_count


def _drop_privileges() -> None:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl failed")
        capability_limit = _CAP_LAST_CAP_PATH.read_text(encoding="utf-8").strip()
        if (
            not re.fullmatch(r"(?:0|[1-9][0-9]{0,2})", capability_limit)
            or int(capability_limit) > _MAX_CAPABILITY_INDEX
        ):
            raise OSError("capability limit invalid")
        # Dropping UID clears the effective sets but not the Linux bounding set.
        # Remove every bounding capability while CAP_SETPCAP is still effective.
        for capability in range(int(capability_limit) + 1):
            if libc.prctl(_PR_CAPBSET_DROP, capability, 0, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), "capability bounding-set drop failed")
        os.setgroups([])
        os.setgid(SERVICE_GID)
        os.setuid(SERVICE_UID)
        os.umask(0o077)
    except (OSError, ValueError):
        raise ContainerEntrypointError("container_privilege_drop_failed") from None
    if os.geteuid() != SERVICE_UID or os.getegid() != SERVICE_GID or os.getgroups():
        raise ContainerEntrypointError("container_privilege_drop_failed")
    try:
        status = {
            key.rstrip(":"): value.strip()
            for key, value in (
                line.split(maxsplit=1)
                for line in _PROCESS_STATUS_PATH.read_text(encoding="utf-8").splitlines()
                if line.startswith(
                    ("CapInh:", "CapPrm:", "CapEff:", "CapBnd:", "CapAmb:", "NoNewPrivs:")
                )
            )
        }
    except (OSError, ValueError):
        raise ContainerEntrypointError("container_privilege_drop_unverified") from None
    capability_fields = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
    if (
        any(
            not re.fullmatch(r"[0-9A-Fa-f]+", status.get(field, "")) or int(status[field], 16) != 0
            for field in capability_fields
        )
        or status.get("NoNewPrivs") != "1"
    ):
        raise ContainerEntrypointError("container_privilege_drop_unverified")
    try:
        os.seteuid(0)
    except OSError:
        pass
    else:
        raise ContainerEntrypointError("container_privilege_drop_unverified")


def _resolved_command(arguments: Sequence[str]) -> list[str]:
    values = list(arguments)
    if not values:
        values = ["serve"]
    if values[0] in _FORMOWL_COMMANDS or values[0].startswith("-"):
        return ["formowl-connected-mcp", *values]
    return values


def _requires_connected_secrets(arguments: Sequence[str], environ: Mapping[str, str]) -> bool:
    values = list(arguments)
    first = values[0] if values else "serve"
    if first == "init-secrets":
        return False
    if first in _FORMOWL_COMMANDS or first.startswith("-"):
        return True
    return environ.get(_EXTERNAL_SECRET_STAGE_ENV) == "1"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if os.geteuid() == 0:
            if _requires_connected_secrets(arguments, os.environ):
                stage_configured_secrets(os.environ)
            _drop_privileges()
        command = _resolved_command(arguments)
        os.execvpe(command[0], command, os.environ)
    except ContainerEntrypointError as error:
        code = error.code
    except OSError:
        code = "container_exec_failed"
    print(
        json.dumps(
            {"error": code, "status": "error"},
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
