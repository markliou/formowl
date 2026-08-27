"""Fail-closed initialization for connected-runtime deployment secrets."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import tempfile
from typing import Mapping
from urllib.parse import quote, unquote, urlsplit

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_SAFE_POSTGRES_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_SAFE_POSTGRES_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_SAFE_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_GENERATED_PASSWORD = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_SECRET_DIRECTORY_MODE = 0o700
_SECRET_FILE_MODE = 0o400
_MAX_SECRET_BYTES = 64 * 1024
_CURRENT_KEY_MOUNT = "/run/secrets/formowl_signing_key_current"
_SECRET_FILENAMES = (
    "postgres-password",
    "database-dsn",
    "state-encryption-key",
    "signing-key-set.json",
    "signing-current.pem",
    "signing-previous.pem",
)


class SecretInitializationError(RuntimeError):
    """Machine-safe initialization failure that never contains secret values or paths."""

    def __init__(self, code: str) -> None:
        safe_code = code if _SAFE_ERROR_CODE.fullmatch(code) else "secret_initialization_failed"
        self.code = safe_code
        super().__init__(safe_code)


def initialize_connected_secrets(
    output_dir: Path,
    *,
    postgres_host: str = "postgres",
    postgres_port: int = 5432,
    postgres_user: str = "formowl",
    postgres_database: str = "formowl",
    recover_partial: bool = False,
) -> dict[str, object]:
    """Create or validate one complete connected-runtime secret set.

    A complete valid set is an idempotent success. A partial, invalid, symlinked,
    or concurrently modified set fails without replacing any existing secret.
    """

    try:
        _validate_initialization_arguments(
            output_dir=output_dir,
            postgres_host=postgres_host,
            postgres_port=postgres_port,
            postgres_user=postgres_user,
            postgres_database=postgres_database,
        )
        output_dir.mkdir(parents=True, mode=_SECRET_DIRECTORY_MODE, exist_ok=True)
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise SecretInitializationError("secret_directory_invalid")
        os.chmod(output_dir, _SECRET_DIRECTORY_MODE)
        lock_descriptor = _acquire_initialization_lock(output_dir)
        try:
            target_paths = {name: output_dir / name for name in _SECRET_FILENAMES}
            existing_names = {name for name, path in target_paths.items() if os.path.lexists(path)}
            stale_staging_paths = tuple(
                path
                for path in output_dir.iterdir()
                if path.name.startswith(".formowl-secret-init-")
            )
            recovered_file_count = 0
            recovered_staging_entry_count = 0
            if existing_names == set(_SECRET_FILENAMES):
                if stale_staging_paths:
                    if not recover_partial:
                        raise SecretInitializationError("secret_recovery_required")
                    recovered_file_count, recovered_staging_entry_count = (
                        _quarantine_partial_secret_set(
                            output_dir,
                            target_paths=target_paths,
                            existing_names=set(),
                            stale_staging_paths=stale_staging_paths,
                        )
                    )
                _validate_existing_secret_set(
                    target_paths,
                    postgres_host=postgres_host,
                    postgres_port=postgres_port,
                    postgres_user=postgres_user,
                    postgres_database=postgres_database,
                )
                created_file_count = 0
                secret_set_state = "recovered" if recovered_staging_entry_count else "unchanged"
            else:
                if existing_names or stale_staging_paths:
                    if not recover_partial:
                        raise SecretInitializationError("secret_recovery_required")
                    recovered_file_count, recovered_staging_entry_count = (
                        _quarantine_partial_secret_set(
                            output_dir,
                            target_paths=target_paths,
                            existing_names=existing_names,
                            stale_staging_paths=stale_staging_paths,
                        )
                    )
                payloads = _prepare_secret_payloads(
                    postgres_host=postgres_host,
                    postgres_port=postgres_port,
                    postgres_user=postgres_user,
                    postgres_database=postgres_database,
                )
                _write_new_secret_set(output_dir, target_paths, payloads)
                _validate_existing_secret_set(
                    target_paths,
                    postgres_host=postgres_host,
                    postgres_port=postgres_port,
                    postgres_user=postgres_user,
                    postgres_database=postgres_database,
                )
                created_file_count = len(_SECRET_FILENAMES)
                secret_set_state = (
                    "recovered"
                    if recovered_file_count or recovered_staging_entry_count
                    else "created"
                )
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)
        return {
            "status": "ok",
            "secret_set_state": secret_set_state,
            "secret_file_count": len(_SECRET_FILENAMES),
            "created_file_count": created_file_count,
            "recovered_file_count": recovered_file_count,
            "recovered_staging_entry_count": recovered_staging_entry_count,
            "active_signing_key_count": 1,
            "standby_signing_slot_count": 1,
            "google_client_secret_generated": False,
            "requires_operator_google_client_secret": True,
            "supports_connected_preflight_ready": False,
            "initialization_contract_hash": _initialization_contract_hash(
                postgres_host=postgres_host,
                postgres_port=postgres_port,
                postgres_user=postgres_user,
                postgres_database=postgres_database,
            ),
        }
    except SecretInitializationError:
        raise
    except Exception:
        raise SecretInitializationError("secret_initialization_failed") from None


def _validate_initialization_arguments(
    *,
    output_dir: Path,
    postgres_host: str,
    postgres_port: int,
    postgres_user: str,
    postgres_database: str,
) -> None:
    if not isinstance(output_dir, Path) or not str(output_dir) or "\x00" in str(output_dir):
        raise SecretInitializationError("secret_directory_invalid")
    if not isinstance(postgres_host, str) or not _SAFE_POSTGRES_HOST.fullmatch(postgres_host):
        raise SecretInitializationError("secret_postgres_config_invalid")
    if isinstance(postgres_port, bool) or not isinstance(postgres_port, int):
        raise SecretInitializationError("secret_postgres_config_invalid")
    if not 1 <= postgres_port <= 65535:
        raise SecretInitializationError("secret_postgres_config_invalid")
    if not isinstance(postgres_user, str) or not _SAFE_POSTGRES_NAME.fullmatch(postgres_user):
        raise SecretInitializationError("secret_postgres_config_invalid")
    if not isinstance(postgres_database, str) or not _SAFE_POSTGRES_NAME.fullmatch(
        postgres_database
    ):
        raise SecretInitializationError("secret_postgres_config_invalid")


def _acquire_initialization_lock(output_dir: Path) -> int:
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(output_dir / ".formowl-secret-init.lock", flags, 0o600)
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor
    except (OSError, BlockingIOError):
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise SecretInitializationError("secret_initialization_locked") from None


def _prepare_secret_payloads(
    *,
    postgres_host: str,
    postgres_port: int,
    postgres_user: str,
    postgres_database: str,
) -> dict[str, bytes]:
    password = secrets.token_urlsafe(48)
    if not _SAFE_GENERATED_PASSWORD.fullmatch(password):
        raise SecretInitializationError("secret_random_source_invalid")
    current_key = _generate_private_key_pem()
    standby_key = _generate_private_key_pem()
    if _public_key_numbers(current_key) == _public_key_numbers(standby_key):
        raise SecretInitializationError("secret_random_source_invalid")
    manifest = {
        "version": 1,
        "keys": [
            {
                "kid": f"formowl-current-{secrets.token_hex(12)}",
                "private_key_file": _CURRENT_KEY_MOUNT,
                "active": True,
            }
        ],
    }
    database_dsn = _build_postgres_dsn(
        host=postgres_host,
        port=postgres_port,
        user=postgres_user,
        password=password,
        database=postgres_database,
    )
    return {
        "postgres-password": f"{password}\n".encode("ascii"),
        "database-dsn": f"{database_dsn}\n".encode("ascii"),
        "state-encryption-key": Fernet.generate_key() + b"\n",
        "signing-key-set.json": (
            json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
        ).encode("utf-8"),
        "signing-current.pem": current_key,
        "signing-previous.pem": standby_key,
    }


def _write_new_secret_set(
    output_dir: Path,
    target_paths: Mapping[str, Path],
    payloads: Mapping[str, bytes],
) -> None:
    if set(payloads) != set(_SECRET_FILENAMES):
        raise SecretInitializationError("secret_payload_invalid")
    staging_dir = Path(tempfile.mkdtemp(prefix=".formowl-secret-init-", dir=output_dir))
    os.chmod(staging_dir, _SECRET_DIRECTORY_MODE)
    created_targets: list[Path] = []
    try:
        for name in _SECRET_FILENAMES:
            staging_path = staging_dir / name
            descriptor = os.open(
                staging_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                _SECRET_FILE_MODE,
            )
            try:
                os.fchmod(descriptor, _SECRET_FILE_MODE)
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(payloads[name])
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(descriptor)
        if any(os.path.lexists(path) for path in target_paths.values()):
            raise SecretInitializationError("secret_set_conflict")
        for name in _SECRET_FILENAMES:
            target = target_paths[name]
            os.link(staging_dir / name, target, follow_symlinks=False)
            created_targets.append(target)
        directory_descriptor = os.open(output_dir, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except SecretInitializationError:
        for target in reversed(created_targets):
            target.unlink(missing_ok=True)
        raise
    except Exception:
        for target in reversed(created_targets):
            target.unlink(missing_ok=True)
        raise SecretInitializationError("secret_set_write_failed") from None
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _quarantine_partial_secret_set(
    output_dir: Path,
    *,
    target_paths: Mapping[str, Path],
    existing_names: set[str],
    stale_staging_paths: tuple[Path, ...],
) -> tuple[int, int]:
    quarantine = output_dir / f".formowl-secret-recovery-{secrets.token_hex(16)}"
    staging_root = quarantine / "stale-staging"
    moved_entries: list[tuple[Path, Path]] = []
    quarantine_created = False
    staging_root_created = False
    try:
        quarantine.mkdir(mode=_SECRET_DIRECTORY_MODE)
        quarantine_created = True
        os.chmod(quarantine, _SECRET_DIRECTORY_MODE)
        for name in sorted(existing_names):
            source = target_paths[name]
            destination = quarantine / name
            os.rename(source, destination)
            moved_entries.append((destination, source))
        if stale_staging_paths:
            staging_root.mkdir(mode=_SECRET_DIRECTORY_MODE)
            staging_root_created = True
            os.chmod(staging_root, _SECRET_DIRECTORY_MODE)
        for index, stale_path in enumerate(stale_staging_paths, start=1):
            destination = staging_root / f"entry-{index}"
            os.rename(stale_path, destination)
            moved_entries.append((destination, stale_path))
        directory_descriptor = os.open(output_dir, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        # Preserve operator data if any exact-path restoration fails; only empty
        # quarantine structure may be removed after every move is reversed.
        rollback_complete = True
        for destination, source in reversed(moved_entries):
            try:
                os.rename(destination, source)
            except Exception:
                rollback_complete = False
        if rollback_complete:
            try:
                if staging_root_created:
                    staging_root.rmdir()
                if quarantine_created:
                    quarantine.rmdir()
            except Exception:
                pass
        raise SecretInitializationError("secret_recovery_failed") from None
    return len(existing_names), len(stale_staging_paths)


def _validate_existing_secret_set(
    target_paths: Mapping[str, Path],
    *,
    postgres_host: str,
    postgres_port: int,
    postgres_user: str,
    postgres_database: str,
) -> None:
    if set(target_paths) != set(_SECRET_FILENAMES):
        raise SecretInitializationError("secret_set_invalid")
    values: dict[str, bytes] = {}
    for name in _SECRET_FILENAMES:
        path = target_paths[name]
        try:
            metadata = path.lstat()
        except OSError:
            raise SecretInitializationError("secret_set_invalid") from None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != _SECRET_FILE_MODE
        ):
            raise SecretInitializationError("secret_permissions_invalid")
        try:
            value = path.read_bytes()
        except OSError:
            raise SecretInitializationError("secret_set_invalid") from None
        if not value or len(value) > _MAX_SECRET_BYTES or b"\x00" in value:
            raise SecretInitializationError("secret_set_invalid")
        values[name] = value.strip()

    try:
        password = values["postgres-password"].decode("ascii")
        dsn = values["database-dsn"].decode("ascii")
        state_key = values["state-encryption-key"].decode("ascii")
        manifest = json.loads(values["signing-key-set.json"].decode("utf-8"))
        Fernet(state_key.encode("ascii"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise SecretInitializationError("secret_set_invalid") from None
    if not _SAFE_GENERATED_PASSWORD.fullmatch(password):
        raise SecretInitializationError("secret_set_invalid")
    _validate_postgres_dsn(
        dsn,
        expected_host=postgres_host,
        expected_port=postgres_port,
        expected_user=postgres_user,
        expected_password=password,
        expected_database=postgres_database,
    )
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"version", "keys"}
        or manifest.get("version") != 1
        or not isinstance(manifest.get("keys"), list)
        or len(manifest["keys"]) != 1
    ):
        raise SecretInitializationError("secret_set_invalid")
    key_entry = manifest["keys"][0]
    if (
        not isinstance(key_entry, dict)
        or set(key_entry) != {"kid", "private_key_file", "active"}
        or not isinstance(key_entry.get("kid"), str)
        or not _SAFE_KEY_ID.fullmatch(key_entry["kid"])
        or key_entry.get("private_key_file") != _CURRENT_KEY_MOUNT
        or key_entry.get("active") is not True
    ):
        raise SecretInitializationError("secret_set_invalid")
    current_numbers = _public_key_numbers(values["signing-current.pem"])
    standby_numbers = _public_key_numbers(values["signing-previous.pem"])
    if current_numbers == standby_numbers:
        raise SecretInitializationError("secret_set_invalid")


def _generate_private_key_pem() -> bytes:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _public_key_numbers(private_key_pem: bytes) -> tuple[int, int]:
    try:
        private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    except (TypeError, ValueError):
        raise SecretInitializationError("secret_set_invalid") from None
    if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < 2048:
        raise SecretInitializationError("secret_set_invalid")
    numbers = private_key.public_key().public_numbers()
    return numbers.e, numbers.n


def _build_postgres_dsn(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
) -> str:
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@"
        f"{host}:{port}/{quote(database, safe='')}"
    )


def _validate_postgres_dsn(
    dsn: str,
    *,
    expected_host: str,
    expected_port: int,
    expected_user: str,
    expected_password: str,
    expected_database: str,
) -> None:
    try:
        parsed = urlsplit(dsn)
        parsed_port = parsed.port
    except (TypeError, ValueError):
        raise SecretInitializationError("secret_set_invalid") from None
    if (
        parsed.scheme != "postgresql"
        or parsed.hostname != expected_host
        or parsed_port != expected_port
        or unquote(parsed.username or "") != expected_user
        or unquote(parsed.password or "") != expected_password
        or unquote(parsed.path.removeprefix("/")) != expected_database
        or parsed.query
        or parsed.fragment
    ):
        raise SecretInitializationError("secret_set_invalid")


def _initialization_contract_hash(
    *,
    postgres_host: str,
    postgres_port: int,
    postgres_user: str,
    postgres_database: str,
) -> str:
    payload = {
        "version": 1,
        "secret_files": [
            {"name": name, "mode": format(_SECRET_FILE_MODE, "04o")} for name in _SECRET_FILENAMES
        ],
        "directory_mode": format(_SECRET_DIRECTORY_MODE, "04o"),
        "postgres": {
            "host": postgres_host,
            "port": postgres_port,
            "user": postgres_user,
            "database": postgres_database,
        },
        "active_signing_key_count": 1,
        "standby_signing_slot_count": 1,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "SecretInitializationError",
    "initialize_connected_secrets",
]
