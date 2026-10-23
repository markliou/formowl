#!/usr/bin/env python3
"""Verify the container boundary for the private issue #20 runner sentinels."""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
from typing import Sequence


_MOUNTINFO_ESCAPE_RE = re.compile(r"\\(040|011|012|134)")
_MOUNTINFO_ESCAPES = {
    "040": " ",
    "011": "\t",
    "012": "\n",
    "134": "\\",
}
_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_INVOCATION_LOCK_FD = 9
_INVOCATION_LOCK_ADDRESS_PREFIX = b"\0formowl-issue20-evidence-runner-v1-uid-"
_CAPABILITY_STATUS_FIELDS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
_CAMPAIGN_ARTIFACT_TYPE = "issue20_containerized_evidence_campaign_pin_v1"
_CAMPAIGN_KEYS = {
    "artifact_type",
    "boundary_sha256",
    "dev_image_id",
    "docker_authority",
    "git_base_commit",
    "git_head_commit",
    "git_metadata_sha256",
    "implementation_contract_hash",
    "runner_sha256",
    "sandboxed_untrusted_source",
    "source_snapshot_sha256",
    "status",
}
_DOCKER_AUTHORITY = "trusted_operator_docker_daemon"
_OPERATOR_AUTHORITY_NAMES = (
    "operator-postgresql-execution-authority.json",
    "operator-postgresql-execution-authority-pin.json",
)
_RUNNER_FAILURE_DIAGNOSTIC_NAME = "live-postgresql-failure-diagnostic.json"
_RUNNER_FAILURE_DIAGNOSTIC_ARTIFACT_TYPE = "issue20_runner_failure_diagnostic_v1"
_RUNNER_FAILURE_DIAGNOSTIC_KEYS = {
    "artifact_type",
    "failure_code",
    "mode",
    "schema_version",
    "stage",
    "status",
}
_RUNNER_FAILURE_DIAGNOSTIC_PAIRS = {
    ("live_postgresql_execution", "command_failed"),
    ("live_postgresql_execution", "report_persist_failed"),
    ("live_postgresql_report", "report_rejected"),
    ("live_postgresql_report_validation", "command_failed"),
    ("live_postgresql_validation", "validation_rejected"),
}
_RUNNER_FAILURE_DIAGNOSTIC_MAXIMUM_SIZE = 1024
_LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME = "live-postgresql-execution-error.json"
_LIVE_POSTGRESQL_EXECUTION_CAPTURE_MAXIMUM_SIZE = 512
_LIVE_POSTGRESQL_EXECUTION_ERROR_KEYS = {"error", "status"}
_LIVE_POSTGRESQL_EXECUTION_ERROR_CODES = {
    "live_e2e_report_persist_failed": "report_persist_failed",
}
_INVOCATION_LOG_DIRECTORY_RE = re.compile(r"invocation\.[A-Za-z0-9]{10}\Z")
_OUTER_MODES = (
    "preflight",
    "operator",
    "operator-layer",
    "live-postgresql",
    "lifecycle-a",
    "lifecycle-b",
    "lifecycle-aggregate",
    "local-harness",
)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _read_regular_file(
    path: Path,
    *,
    expected_uid: int,
    expected_mode: int | None = None,
    maximum_size: int = 16 * 1024 * 1024,
) -> bytes:
    path_metadata = path.lstat()
    if path.is_symlink() or path.resolve(strict=True) != path:
        raise OSError
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened_metadata = os.fstat(descriptor)
        current_metadata = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or opened_metadata.st_uid != expected_uid
            or opened_metadata.st_nlink != 1
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (current_metadata.st_dev, current_metadata.st_ino)
            or opened_metadata.st_size < 1
            or opened_metadata.st_size > maximum_size
            or (
                expected_mode is not None and stat.S_IMODE(opened_metadata.st_mode) != expected_mode
            )
        ):
            raise OSError
        payload = bytearray()
        while len(payload) <= maximum_size:
            chunk = os.read(descriptor, min(1024 * 1024, maximum_size + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != opened_metadata.st_size:
            raise OSError
        return bytes(payload)
    finally:
        os.close(descriptor)


def _open_trusted_private_directory(
    path: Path,
    *,
    expected_path: Path,
    expected_uid: int,
) -> int:
    if path != expected_path:
        raise OSError
    path_metadata = path.lstat()
    if path.is_symlink() or path.resolve(strict=True) != path:
        raise OSError
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        opened_metadata = os.fstat(descriptor)
        current_metadata = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened_metadata.st_mode)
            or opened_metadata.st_uid != expected_uid
            or stat.S_IMODE(opened_metadata.st_mode) != 0o700
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (current_metadata.st_dev, current_metadata.st_ino)
        ):
            raise OSError
        return descriptor
    except OSError:
        os.close(descriptor)
        raise


def _open_runner_failure_directory(
    *,
    scratch_root: Path,
    private_log_dir: Path,
    expected_uid: int,
) -> int:
    scratch_descriptor = _open_trusted_private_directory(
        scratch_root,
        expected_path=scratch_root,
        expected_uid=expected_uid,
    )
    try:
        return _open_trusted_private_directory(
            private_log_dir,
            expected_path=scratch_root / "private-logs",
            expected_uid=expected_uid,
        )
    finally:
        os.close(scratch_descriptor)


def _runner_failure_payload(
    *,
    stage: str,
    failure_code: str,
) -> bytes:
    if (stage, failure_code) not in _RUNNER_FAILURE_DIAGNOSTIC_PAIRS:
        raise ValueError
    return (
        json.dumps(
            {
                "artifact_type": _RUNNER_FAILURE_DIAGNOSTIC_ARTIFACT_TYPE,
                "failure_code": failure_code,
                "mode": "live-postgresql",
                "schema_version": 1,
                "stage": stage,
                "status": "failed",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def write_runner_failure_diagnostic(
    *,
    scratch_root: Path,
    private_log_dir: Path,
    stage: str,
    failure_code: str,
) -> bool:
    expected_uid = os.getuid()
    directory_descriptor: int | None = None
    diagnostic_descriptor: int | None = None
    created_identity: tuple[int, int] | None = None
    try:
        payload = _runner_failure_payload(
            stage=stage,
            failure_code=failure_code,
        )
        directory_descriptor = _open_runner_failure_directory(
            scratch_root=scratch_root,
            private_log_dir=private_log_dir,
            expected_uid=expected_uid,
        )
        diagnostic_descriptor = os.open(
            _RUNNER_FAILURE_DIAGNOSTIC_NAME,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o400,
            dir_fd=directory_descriptor,
        )
        opened_metadata = os.fstat(diagnostic_descriptor)
        created_identity = (opened_metadata.st_dev, opened_metadata.st_ino)
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or opened_metadata.st_uid != expected_uid
            or stat.S_IMODE(opened_metadata.st_mode) != 0o400
            or opened_metadata.st_nlink != 1
            or opened_metadata.st_size != 0
        ):
            raise OSError
        remaining = memoryview(payload)
        while remaining:
            written = os.write(diagnostic_descriptor, remaining)
            if written < 1:
                raise OSError
            remaining = remaining[written:]
        os.fsync(diagnostic_descriptor)
        finalized_metadata = os.fstat(diagnostic_descriptor)
        if (
            (finalized_metadata.st_dev, finalized_metadata.st_ino) != created_identity
            or finalized_metadata.st_size != len(payload)
            or stat.S_IMODE(finalized_metadata.st_mode) != 0o400
        ):
            raise OSError
        os.close(diagnostic_descriptor)
        diagnostic_descriptor = None
        current_metadata = os.stat(
            _RUNNER_FAILURE_DIAGNOSTIC_NAME,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(current_metadata.st_mode)
            or current_metadata.st_uid != expected_uid
            or stat.S_IMODE(current_metadata.st_mode) != 0o400
            or current_metadata.st_nlink != 1
            or (current_metadata.st_dev, current_metadata.st_ino) != created_identity
            or current_metadata.st_size != len(payload)
        ):
            raise OSError
        os.fsync(directory_descriptor)
        return True
    except (OSError, ValueError):
        if diagnostic_descriptor is not None:
            try:
                os.close(diagnostic_descriptor)
            except OSError:
                pass
        if directory_descriptor is not None and created_identity is not None:
            try:
                current_metadata = os.stat(
                    _RUNNER_FAILURE_DIAGNOSTIC_NAME,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if (
                    stat.S_ISREG(current_metadata.st_mode)
                    and (
                        current_metadata.st_dev,
                        current_metadata.st_ino,
                    )
                    == created_identity
                ):
                    os.unlink(
                        _RUNNER_FAILURE_DIAGNOSTIC_NAME,
                        dir_fd=directory_descriptor,
                    )
                    os.fsync(directory_descriptor)
            except OSError:
                pass
        return False
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def consume_runner_failure_diagnostic(
    *,
    scratch_root: Path,
    private_log_dir: Path,
    expected_uid: int | None = None,
) -> tuple[str, str] | None:
    trusted_uid = os.getuid() if expected_uid is None else expected_uid
    directory_descriptor: int | None = None
    diagnostic_descriptor: int | None = None
    try:
        directory_descriptor = _open_runner_failure_directory(
            scratch_root=scratch_root,
            private_log_dir=private_log_dir,
            expected_uid=trusted_uid,
        )
        path_metadata = os.stat(
            _RUNNER_FAILURE_DIAGNOSTIC_NAME,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if stat.S_ISLNK(path_metadata.st_mode):
            raise OSError
        diagnostic_descriptor = os.open(
            _RUNNER_FAILURE_DIAGNOSTIC_NAME,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_descriptor,
        )
        opened_metadata = os.fstat(diagnostic_descriptor)
        current_metadata = os.stat(
            _RUNNER_FAILURE_DIAGNOSTIC_NAME,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or opened_metadata.st_uid != trusted_uid
            or stat.S_IMODE(opened_metadata.st_mode) != 0o400
            or opened_metadata.st_nlink != 1
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (current_metadata.st_dev, current_metadata.st_ino)
            or opened_metadata.st_size < 2
            or opened_metadata.st_size > _RUNNER_FAILURE_DIAGNOSTIC_MAXIMUM_SIZE
        ):
            raise OSError
        payload = bytearray()
        while len(payload) <= _RUNNER_FAILURE_DIAGNOSTIC_MAXIMUM_SIZE:
            chunk = os.read(
                diagnostic_descriptor,
                _RUNNER_FAILURE_DIAGNOSTIC_MAXIMUM_SIZE + 1 - len(payload),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != opened_metadata.st_size:
            raise OSError
        value = json.loads(
            bytes(payload).decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
        if (
            type(value) is not dict
            or set(value) != _RUNNER_FAILURE_DIAGNOSTIC_KEYS
            or value.get("artifact_type") != _RUNNER_FAILURE_DIAGNOSTIC_ARTIFACT_TYPE
            or value.get("mode") != "live-postgresql"
            or type(value.get("schema_version")) is not int
            or value.get("schema_version") != 1
            or value.get("status") != "failed"
            or type(value.get("stage")) is not str
            or type(value.get("failure_code")) is not str
            or (value["stage"], value["failure_code"]) not in _RUNNER_FAILURE_DIAGNOSTIC_PAIRS
        ):
            raise OSError
        final_path_metadata = os.stat(
            _RUNNER_FAILURE_DIAGNOSTIC_NAME,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (final_path_metadata.st_dev, final_path_metadata.st_ino) != (
            opened_metadata.st_dev,
            opened_metadata.st_ino,
        ):
            raise OSError
        os.unlink(
            _RUNNER_FAILURE_DIAGNOSTIC_NAME,
            dir_fd=directory_descriptor,
        )
        if os.fstat(diagnostic_descriptor).st_nlink != 0:
            raise OSError
        try:
            os.stat(
                _RUNNER_FAILURE_DIAGNOSTIC_NAME,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise OSError
        os.fsync(directory_descriptor)
        return value["stage"], value["failure_code"]
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    finally:
        if diagnostic_descriptor is not None:
            os.close(diagnostic_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _open_live_postgresql_execution_capture_directory(
    *,
    scratch_root: Path,
    private_log_dir: Path,
    expected_uid: int,
) -> int:
    private_log_base = scratch_root / "private-logs"
    invocation_log_dir = private_log_dir.parent
    if (
        private_log_dir.name != "inner-logs"
        or invocation_log_dir.parent != private_log_base
        or _INVOCATION_LOG_DIRECTORY_RE.fullmatch(invocation_log_dir.name) is None
    ):
        raise OSError
    descriptors: list[int] = []
    try:
        for path, expected_path in (
            (scratch_root, scratch_root),
            (private_log_base, scratch_root / "private-logs"),
            (invocation_log_dir, private_log_base / invocation_log_dir.name),
        ):
            descriptors.append(
                _open_trusted_private_directory(
                    path,
                    expected_path=expected_path,
                    expected_uid=expected_uid,
                )
            )
        return _open_trusted_private_directory(
            private_log_dir,
            expected_path=invocation_log_dir / "inner-logs",
            expected_uid=expected_uid,
        )
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _consume_live_postgresql_execution_capture(
    *,
    scratch_root: Path,
    private_log_dir: Path,
    expected_uid: int,
) -> bytes | None:
    directory_descriptor: int | None = None
    capture_descriptor: int | None = None
    try:
        directory_descriptor = _open_live_postgresql_execution_capture_directory(
            scratch_root=scratch_root,
            private_log_dir=private_log_dir,
            expected_uid=expected_uid,
        )
        path_metadata = os.stat(
            _LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if stat.S_ISLNK(path_metadata.st_mode):
            raise OSError
        capture_descriptor = os.open(
            _LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_descriptor,
        )
        opened_metadata = os.fstat(capture_descriptor)
        current_metadata = os.stat(
            _LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or opened_metadata.st_uid != expected_uid
            or stat.S_IMODE(opened_metadata.st_mode) != 0o600
            or opened_metadata.st_nlink != 1
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or (opened_metadata.st_dev, opened_metadata.st_ino)
            != (current_metadata.st_dev, current_metadata.st_ino)
            or opened_metadata.st_size > _LIVE_POSTGRESQL_EXECUTION_CAPTURE_MAXIMUM_SIZE
        ):
            raise OSError
        payload = bytearray()
        while len(payload) <= _LIVE_POSTGRESQL_EXECUTION_CAPTURE_MAXIMUM_SIZE:
            chunk = os.read(
                capture_descriptor,
                _LIVE_POSTGRESQL_EXECUTION_CAPTURE_MAXIMUM_SIZE + 1 - len(payload),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != opened_metadata.st_size:
            raise OSError
        final_path_metadata = os.stat(
            _LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (final_path_metadata.st_dev, final_path_metadata.st_ino) != (
            opened_metadata.st_dev,
            opened_metadata.st_ino,
        ):
            raise OSError
        os.unlink(
            _LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME,
            dir_fd=directory_descriptor,
        )
        if os.fstat(capture_descriptor).st_nlink != 0:
            raise OSError
        try:
            os.stat(
                _LIVE_POSTGRESQL_EXECUTION_CAPTURE_NAME,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise OSError
        os.fsync(directory_descriptor)
        return bytes(payload)
    except OSError:
        return None
    finally:
        if capture_descriptor is not None:
            os.close(capture_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def clear_live_postgresql_execution_capture(
    *,
    scratch_root: Path,
    private_log_dir: Path,
    expected_uid: int | None = None,
) -> bool:
    trusted_uid = os.getuid() if expected_uid is None else expected_uid
    return (
        _consume_live_postgresql_execution_capture(
            scratch_root=scratch_root,
            private_log_dir=private_log_dir,
            expected_uid=trusted_uid,
        )
        == b""
    )


def consume_live_postgresql_execution_error(
    *,
    scratch_root: Path,
    private_log_dir: Path,
    expected_uid: int | None = None,
) -> str | None:
    trusted_uid = os.getuid() if expected_uid is None else expected_uid
    payload = _consume_live_postgresql_execution_capture(
        scratch_root=scratch_root,
        private_log_dir=private_log_dir,
        expected_uid=trusted_uid,
    )
    if payload is None or not payload:
        return None
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return None
    if (
        type(value) is not dict
        or set(value) != _LIVE_POSTGRESQL_EXECUTION_ERROR_KEYS
        or value.get("status") != "error"
        or type(value.get("error")) is not str
    ):
        return None
    return _LIVE_POSTGRESQL_EXECUTION_ERROR_CODES.get(value["error"])


def file_sha256(path: Path, *, expected_uid: int) -> str:
    return _sha256_bytes(_read_regular_file(path, expected_uid=expected_uid))


def tree_sha256(root: Path, *, expected_uid: int) -> str:
    canonical_root = root.resolve(strict=True)
    root_metadata = root.lstat()
    if (
        root.is_symlink()
        or canonical_root != root
        or not root.is_dir()
        or root_metadata.st_uid != expected_uid
    ):
        raise OSError
    digest = hashlib.sha256()
    pending = [root]
    while pending:
        directory = pending.pop()
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
        for entry in entries:
            metadata = entry.lstat()
            relative = entry.relative_to(root).as_posix().encode("utf-8")
            if stat.S_ISLNK(metadata.st_mode):
                raise OSError
            if stat.S_ISDIR(metadata.st_mode):
                if metadata.st_uid != expected_uid:
                    raise OSError
                digest.update(b"D\0")
                digest.update(relative)
                digest.update(b"\0")
                digest.update(f"{stat.S_IMODE(metadata.st_mode):04o}".encode("ascii"))
                digest.update(b"\0")
                pending.append(entry)
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != expected_uid:
                raise OSError
            payload = _read_regular_file(entry, expected_uid=expected_uid)
            digest.update(b"F\0")
            digest.update(relative)
            digest.update(b"\0")
            digest.update(f"{stat.S_IMODE(metadata.st_mode):04o}".encode("ascii"))
            digest.update(b"\0")
            digest.update(str(len(payload)).encode("ascii"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(payload).digest())
    return f"sha256:{digest.hexdigest()}"


def _implementation_contract_hash(root: Path) -> str:
    module_path = root / "python" / "formowl_evidence" / "issue20.py"
    spec = importlib.util.spec_from_file_location(
        f"_formowl_issue20_campaign_{os.getpid()}_{id(root)}",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise OSError
    module = importlib.util.module_from_spec(spec)
    previous_dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    value = module.issue20_implementation_contract_hash(root)
    if not isinstance(value, str) or _IMAGE_ID_RE.fullmatch(value) is None:
        raise OSError
    return value


def _git_output(arguments: list[str]) -> str:
    result = subprocess.run(
        arguments,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.stdout.strip()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _read_campaign_pin(path: Path, *, expected_uid: int) -> dict[str, object]:
    payload = _read_regular_file(
        path,
        expected_uid=expected_uid,
        expected_mode=0o400,
        maximum_size=8192,
    )
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    if (
        type(value) is not dict
        or set(value) != _CAMPAIGN_KEYS
        or value.get("artifact_type") != _CAMPAIGN_ARTIFACT_TYPE
        or value.get("docker_authority") != _DOCKER_AUTHORITY
        or value.get("sandboxed_untrusted_source") is not False
        or value.get("status") != "frozen"
    ):
        raise OSError
    for key in (
        "boundary_sha256",
        "dev_image_id",
        "git_metadata_sha256",
        "implementation_contract_hash",
        "runner_sha256",
        "source_snapshot_sha256",
    ):
        if type(value.get(key)) is not str or _IMAGE_ID_RE.fullmatch(value[key]) is None:
            raise OSError
    for key in ("git_base_commit", "git_head_commit"):
        if type(value.get(key)) is not str or re.fullmatch(r"[0-9a-f]{40}", value[key]) is None:
            raise OSError
    return value


def create_campaign_pin(
    *,
    current_root: Path,
    source_snapshot_root: Path,
    git_metadata_root: Path,
    pin_path: Path,
    image_id: str,
    git_base_commit: str,
) -> bool:
    expected_uid = os.getuid()
    created_pin: tuple[int, int] | None = None
    if _IMAGE_ID_RE.fullmatch(image_id) is None:
        return False
    try:
        current_head = _git_output(["/usr/bin/git", "-C", str(current_root), "rev-parse", "HEAD"])
        snapshot_head = _git_output(
            ["/usr/bin/git", f"--git-dir={git_metadata_root}", "rev-parse", "HEAD"]
        )
        _git_output(
            [
                "/usr/bin/git",
                f"--git-dir={git_metadata_root}",
                "cat-file",
                "-e",
                f"{git_base_commit}^{{commit}}",
            ]
        )
        current_contract = _implementation_contract_hash(current_root)
        snapshot_contract = _implementation_contract_hash(source_snapshot_root)
        current_runner = file_sha256(
            current_root / "scripts" / "issue20_containerized_evidence_runner.sh",
            expected_uid=expected_uid,
        )
        snapshot_runner = file_sha256(
            source_snapshot_root / "scripts" / "issue20_containerized_evidence_runner.sh",
            expected_uid=expected_uid,
        )
        current_boundary = file_sha256(
            current_root / "scripts" / "issue20_runner_boundary.py",
            expected_uid=expected_uid,
        )
        snapshot_boundary = file_sha256(
            source_snapshot_root / "scripts" / "issue20_runner_boundary.py",
            expected_uid=expected_uid,
        )
        if (
            current_head != snapshot_head
            or current_contract != snapshot_contract
            or current_runner != snapshot_runner
            or current_boundary != snapshot_boundary
        ):
            return False
        value = {
            "artifact_type": _CAMPAIGN_ARTIFACT_TYPE,
            "boundary_sha256": current_boundary,
            "dev_image_id": image_id,
            "docker_authority": _DOCKER_AUTHORITY,
            "git_base_commit": git_base_commit,
            "git_head_commit": current_head,
            "git_metadata_sha256": tree_sha256(
                git_metadata_root,
                expected_uid=expected_uid,
            ),
            "implementation_contract_hash": current_contract,
            "runner_sha256": current_runner,
            "sandboxed_untrusted_source": False,
            "source_snapshot_sha256": tree_sha256(
                source_snapshot_root,
                expected_uid=expected_uid,
            ),
            "status": "frozen",
        }
        payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
        descriptor = os.open(
            pin_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o400,
        )
        try:
            opened_metadata = os.fstat(descriptor)
            created_pin = (opened_metadata.st_dev, opened_metadata.st_ino)
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return _read_campaign_pin(pin_path, expected_uid=expected_uid) == value
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        if created_pin is not None:
            try:
                current_metadata = pin_path.stat(follow_symlinks=False)
                if (
                    stat.S_ISREG(current_metadata.st_mode)
                    and (current_metadata.st_dev, current_metadata.st_ino) == created_pin
                ):
                    pin_path.unlink()
            except OSError:
                pass
        return False


def verify_campaign(
    *,
    current_root: Path | None,
    source_snapshot_root: Path,
    git_metadata_root: Path,
    pin_path: Path,
) -> dict[str, object] | None:
    expected_uid = os.getuid()
    try:
        value = _read_campaign_pin(pin_path, expected_uid=expected_uid)
        snapshot_head = _git_output(
            ["/usr/bin/git", f"--git-dir={git_metadata_root}", "rev-parse", "HEAD"]
        )
        _git_output(
            [
                "/usr/bin/git",
                f"--git-dir={git_metadata_root}",
                "cat-file",
                "-e",
                f"{value['git_base_commit']}^{{commit}}",
            ]
        )
        checks = (
            snapshot_head == value["git_head_commit"],
            tree_sha256(source_snapshot_root, expected_uid=expected_uid)
            == value["source_snapshot_sha256"],
            tree_sha256(git_metadata_root, expected_uid=expected_uid)
            == value["git_metadata_sha256"],
            _implementation_contract_hash(source_snapshot_root)
            == value["implementation_contract_hash"],
            file_sha256(
                source_snapshot_root / "scripts" / "issue20_containerized_evidence_runner.sh",
                expected_uid=expected_uid,
            )
            == value["runner_sha256"],
            file_sha256(
                source_snapshot_root / "scripts" / "issue20_runner_boundary.py",
                expected_uid=expected_uid,
            )
            == value["boundary_sha256"],
        )
        if not all(checks):
            return None
        if current_root is not None:
            current_head = _git_output(
                ["/usr/bin/git", "-C", str(current_root), "rev-parse", "HEAD"]
            )
            current_checks = (
                current_head == value["git_head_commit"],
                _implementation_contract_hash(current_root)
                == value["implementation_contract_hash"],
                file_sha256(
                    current_root / "scripts" / "issue20_containerized_evidence_runner.sh",
                    expected_uid=expected_uid,
                )
                == value["runner_sha256"],
                file_sha256(
                    current_root / "scripts" / "issue20_runner_boundary.py",
                    expected_uid=expected_uid,
                )
                == value["boundary_sha256"],
            )
            if not all(current_checks):
                return None
        return value
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        return None


def clear_operator_candidates(candidate_dir: Path) -> bool:
    try:
        if not trusted_private_directory(
            candidate_dir,
            expected_path=candidate_dir,
        ):
            return False
        for entry in candidate_dir.iterdir():
            if entry.name not in (*_OPERATOR_AUTHORITY_NAMES, "outer-validation.json"):
                return False
            metadata = entry.lstat()
            if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                return False
        for entry in candidate_dir.iterdir():
            entry.unlink()
        return True
    except OSError:
        return False


def seal_operator_trust_inputs(
    *,
    candidate_dir: Path,
    trust_input_dir: Path,
) -> bool:
    expected_uid = os.getuid()
    try:
        if not trusted_private_directory(
            candidate_dir,
            expected_path=candidate_dir,
        ) or not trusted_private_directory(
            trust_input_dir,
            expected_path=trust_input_dir,
        ):
            return False
        entries = {entry.name for entry in candidate_dir.iterdir()}
        if entries != {*_OPERATOR_AUTHORITY_NAMES, "outer-validation.json"}:
            return False
        validation = json.loads(
            _read_regular_file(
                candidate_dir / "outer-validation.json",
                expected_uid=expected_uid,
                maximum_size=1024 * 1024,
            ).decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
        if (
            type(validation) is not dict
            or validation.get("passed") is not True
            or validation.get("blockers") not in (None, [])
        ):
            return False
        payloads = {
            name: _read_regular_file(
                candidate_dir / name,
                expected_uid=expected_uid,
                expected_mode=0o400,
                maximum_size=1024 * 1024,
            )
            for name in _OPERATOR_AUTHORITY_NAMES
        }
        if any((trust_input_dir / name).exists() for name in _OPERATOR_AUTHORITY_NAMES):
            return False
        created: list[tuple[Path, int, int]] = []
        try:
            for name in _OPERATOR_AUTHORITY_NAMES:
                destination = trust_input_dir / name
                descriptor = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o400,
                )
                try:
                    opened_metadata = os.fstat(descriptor)
                    created.append(
                        (
                            destination,
                            opened_metadata.st_dev,
                            opened_metadata.st_ino,
                        )
                    )
                    remaining = memoryview(payloads[name])
                    while remaining:
                        written = os.write(descriptor, remaining)
                        if written < 1:
                            raise OSError
                        remaining = remaining[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            if not all(
                _read_regular_file(
                    trust_input_dir / name,
                    expected_uid=expected_uid,
                    expected_mode=0o400,
                    maximum_size=1024 * 1024,
                )
                == payloads[name]
                for name in _OPERATOR_AUTHORITY_NAMES
            ):
                raise OSError
            return True
        except OSError:
            for destination, device, inode in reversed(created):
                try:
                    current_metadata = destination.stat(follow_symlinks=False)
                    if stat.S_ISREG(current_metadata.st_mode) and (
                        current_metadata.st_dev,
                        current_metadata.st_ino,
                    ) == (device, inode):
                        destination.unlink()
                except OSError:
                    pass
            return False
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def trusted_executable(path: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError:
        return False
    return (
        resolved.is_file()
        and os.access(resolved, os.X_OK)
        and metadata.st_uid == 0
        and stat.S_IMODE(metadata.st_mode) & 0o022 == 0
    )


def trusted_private_directory(
    path: Path,
    *,
    expected_path: Path,
    require_empty: bool = False,
) -> bool:
    try:
        canonical = path.resolve(strict=True)
        metadata = path.lstat()
        has_entries = any(path.iterdir())
    except OSError:
        return False
    return (
        path.is_dir()
        and not path.is_symlink()
        and canonical == expected_path
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o700
        and (not require_empty or not has_entries)
    )


def invocation_lock_address() -> bytes:
    return _INVOCATION_LOCK_ADDRESS_PREFIX + str(os.getuid()).encode("ascii")


def trusted_invocation_lock_descriptor(descriptor: int) -> bool:
    try:
        metadata = os.fstat(descriptor)
        duplicate = socket.fromfd(descriptor, socket.AF_UNIX, socket.SOCK_STREAM)
    except OSError:
        return False
    try:
        address = duplicate.getsockname()
        socket_type = duplicate.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
    except OSError:
        return False
    finally:
        duplicate.close()
    return (
        stat.S_ISSOCK(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and socket_type == socket.SOCK_STREAM
        and address == invocation_lock_address()
    )


def acquire_invocation_lock() -> tuple[int | None, str | None]:
    """Bind and retain the fixed per-UID abstract-socket lock descriptor."""

    try:
        handle = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except OSError:
        return None, "unavailable"
    try:
        handle.bind(invocation_lock_address())
    except OSError as error:
        handle.close()
        if error.errno == errno.EADDRINUSE:
            return None, "busy"
        return None, "unavailable"
    try:
        descriptor = handle.fileno()
        if not trusted_invocation_lock_descriptor(descriptor):
            handle.close()
            return None, "unavailable"
        handle.set_inheritable(True)
        descriptor = handle.detach()
    except OSError:
        handle.close()
        return None, "unavailable"
    return descriptor, None


def verify_held_invocation_lock(descriptor: int) -> bool:
    return trusted_invocation_lock_descriptor(descriptor)


def decode_mountinfo_field(value: str) -> str:
    """Decode the four kernel escapes permitted in mountinfo path fields."""

    return _MOUNTINFO_ESCAPE_RE.sub(
        lambda match: _MOUNTINFO_ESCAPES[match.group(1)],
        value,
    )


def mount_options(path: Path, *, mountinfo_path: Path = Path("/proc/self/mountinfo")) -> set[str]:
    try:
        target = str(path)
        matched_options: set[str] = set()
        for line in mountinfo_path.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) > 5 and decode_mountinfo_field(fields[4]) == target:
                matched_options = set(fields[5].split(","))
    except OSError:
        return set()
    return matched_options


def process_status(*, status_path: Path = Path("/proc/self/status")) -> dict[str, str]:
    try:
        lines = status_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    return {
        key.strip(): value.strip()
        for line in lines
        if ":" in line
        for key, value in (line.split(":", 1),)
        if key.strip()
    }


def verify_inner_boundary(
    *,
    mode: str,
    root: Path,
    scratch_root: Path,
    source_snapshot_root: Path,
    git_metadata_root: Path,
    campaign_pin: Path,
    reports_dir: Path,
    candidate_dir: Path,
    trust_input_dir: Path,
    script_path: Path,
    python_bin: Path,
    docker_bin: Path,
    docker_socket: Path,
    home_dir: Path,
    docker_config_dir: Path,
    tmp_dir: Path,
    private_log_dir: Path,
    image_id: str,
) -> bool:
    try:
        canonical_root = root.resolve(strict=True)
        canonical_script = script_path.resolve(strict=True)
        canonical_scratch = scratch_root.resolve(strict=True)
        canonical_source_snapshot = source_snapshot_root.resolve(strict=True)
        canonical_git_metadata = git_metadata_root.resolve(strict=True)
        canonical_campaign_pin = campaign_pin.resolve(strict=True)
        canonical_reports = reports_dir.resolve(strict=True)
        canonical_candidate = candidate_dir.resolve(strict=True)
        canonical_trust_inputs = trust_input_dir.resolve(strict=True)
        canonical_socket = docker_socket.resolve(strict=True)
        canonical_home = home_dir.resolve(strict=True)
        canonical_docker_config = docker_config_dir.resolve(strict=True)
        canonical_tmp = tmp_dir.resolve(strict=True)
        canonical_private_log = private_log_dir.resolve(strict=True)
        scratch_metadata = scratch_root.lstat()
        socket_metadata = canonical_socket.stat()
    except OSError:
        return False
    try:
        campaign = verify_campaign(
            current_root=None,
            source_snapshot_root=source_snapshot_root,
            git_metadata_root=git_metadata_root,
            pin_path=campaign_pin,
        )
        campaign_pin_sha256 = file_sha256(campaign_pin, expected_uid=os.getuid())
    except OSError:
        return False
    if campaign is None:
        return False
    status = process_status()
    capability_set_is_empty = all(
        isinstance(value, str)
        and re.fullmatch(r"[0-9A-Fa-f]+", value) is not None
        and int(value, 16) == 0
        for value in (status.get(field) for field in _CAPABILITY_STATUS_FIELDS)
    )
    scratch_children_trusted = all(
        trusted_private_directory(
            scratch_root / child_name,
            expected_path=canonical_scratch / child_name,
        )
        for child_name in (
            "campaign",
            "handoff-candidates",
            "home",
            "tmp",
            "reports",
            "private-logs",
            "trust-inputs",
        )
    )
    fresh_directories_trusted = all(
        (
            trusted_private_directory(
                home_dir,
                expected_path=home_dir,
                require_empty=True,
            ),
            canonical_home.is_relative_to(canonical_scratch / "home"),
            trusted_private_directory(
                docker_config_dir,
                expected_path=docker_config_dir,
                require_empty=True,
            ),
            canonical_docker_config.is_relative_to(canonical_scratch / "home"),
            trusted_private_directory(
                tmp_dir,
                expected_path=tmp_dir,
                require_empty=True,
            ),
            canonical_tmp.is_relative_to(canonical_scratch / "tmp"),
            trusted_private_directory(
                private_log_dir,
                expected_path=private_log_dir,
                require_empty=True,
            ),
            canonical_private_log.is_relative_to(canonical_scratch / "private-logs"),
        )
    )
    forbidden_environment = (
        "DOCKER_CONTEXT",
        "DOCKER_CLI_PLUGIN_EXTRA_DIRS",
        "BUILDX_CONFIG",
        "BUILDKIT_HOST",
        "COMPOSE_FILE",
        "COMPOSE_PROFILES",
        "COMPOSE_PROJECT_NAME",
        "COMPOSE_ENV_FILES",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    )
    return all(
        (
            os.getppid() == 1,
            canonical_script
            == canonical_root / "scripts" / "issue20_containerized_evidence_runner.sh",
            canonical_source_snapshot == canonical_root,
            Path.cwd().resolve() == canonical_root,
            (canonical_root / "containers" / "dev" / "Dockerfile").is_file(),
            Path("/.dockerenv").is_file(),
            trusted_executable(python_bin),
            trusted_executable(docker_bin),
            "ro" in mount_options(Path("/")),
            "ro" in mount_options(canonical_root),
            scratch_root.is_dir(),
            not scratch_root.is_symlink(),
            canonical_scratch == scratch_root,
            scratch_metadata.st_uid == os.getuid(),
            stat.S_IMODE(scratch_metadata.st_mode) == 0o700,
            scratch_children_trusted,
            fresh_directories_trusted,
            canonical_git_metadata.is_relative_to(canonical_scratch / "campaign"),
            canonical_campaign_pin.is_relative_to(canonical_trust_inputs),
            canonical_reports == canonical_scratch / "reports",
            canonical_candidate == canonical_scratch / "handoff-candidates",
            canonical_trust_inputs == canonical_scratch / "trust-inputs",
            "rw" in mount_options(canonical_reports),
            "rw" in mount_options(canonical_private_log),
            "rw" in mount_options(canonical_home),
            "rw" in mount_options(canonical_docker_config),
            "rw" in mount_options(canonical_tmp),
            (
                "rw" in mount_options(canonical_candidate)
                if mode == "operator"
                else "ro" in mount_options(canonical_candidate)
            ),
            "ro" in mount_options(canonical_trust_inputs),
            "ro" in mount_options(canonical_git_metadata),
            os.environ.get("DOCKER_HOST") == "unix:///var/run/docker.sock",
            os.environ.get("HOME") == str(home_dir),
            os.environ.get("DOCKER_CONFIG") == str(docker_config_dir),
            os.environ.get("TMPDIR") == str(tmp_dir),
            os.environ.get("FORMOWL_RUNNER_PRIVATE_LOG_DIR") == str(private_log_dir),
            os.environ.get("FORMOWL_RUNNER_IMAGE_ID") == image_id,
            os.environ.get("FORMOWL_RUNNER_CAMPAIGN_PIN") == str(campaign_pin),
            os.environ.get("FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256") == campaign_pin_sha256,
            os.environ.get("FORMOWL_RUNNER_DOCKER_AUTHORITY") == _DOCKER_AUTHORITY,
            os.environ.get("FORMOWL_RUNNER_SANDBOXED_UNTRUSTED_SOURCE") == "0",
            campaign.get("dev_image_id") == image_id,
            _IMAGE_ID_RE.fullmatch(image_id) is not None,
            os.environ.get("COMPOSE_DISABLE_ENV_FILE") == "1",
            all(name not in os.environ for name in forbidden_environment),
            stat.S_ISSOCK(socket_metadata.st_mode),
            "rw" in mount_options(canonical_socket),
            status.get("NoNewPrivs") == "1",
            capability_set_is_empty,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    lock_and_exec_parser = subparsers.add_parser("lock-and-exec")
    lock_and_exec_parser.add_argument("--root", type=Path, required=True)
    lock_and_exec_parser.add_argument("--script-path", type=Path, required=True)
    lock_and_exec_parser.add_argument("--mode", choices=_OUTER_MODES, required=True)
    verify_lock_parser = subparsers.add_parser("verify-held-lock")
    verify_lock_parser.add_argument("--lock-fd", type=int, required=True)
    verify_inner_parser = subparsers.add_parser("verify-inner")
    verify_inner_parser.add_argument("--mode", choices=_OUTER_MODES, required=True)
    verify_inner_parser.add_argument("--root", type=Path, required=True)
    verify_inner_parser.add_argument("--scratch-root", type=Path, required=True)
    verify_inner_parser.add_argument("--source-snapshot-root", type=Path, required=True)
    verify_inner_parser.add_argument("--git-metadata-root", type=Path, required=True)
    verify_inner_parser.add_argument("--campaign-pin", type=Path, required=True)
    verify_inner_parser.add_argument("--reports-dir", type=Path, required=True)
    verify_inner_parser.add_argument("--candidate-dir", type=Path, required=True)
    verify_inner_parser.add_argument("--trust-input-dir", type=Path, required=True)
    verify_inner_parser.add_argument("--script-path", type=Path, required=True)
    verify_inner_parser.add_argument("--python-bin", type=Path, required=True)
    verify_inner_parser.add_argument("--docker-bin", type=Path, required=True)
    verify_inner_parser.add_argument("--docker-socket", type=Path, required=True)
    verify_inner_parser.add_argument("--home-dir", type=Path, required=True)
    verify_inner_parser.add_argument("--docker-config-dir", type=Path, required=True)
    verify_inner_parser.add_argument("--tmp-dir", type=Path, required=True)
    verify_inner_parser.add_argument("--private-log-dir", type=Path, required=True)
    verify_inner_parser.add_argument("--image-id", required=True)
    create_campaign_parser = subparsers.add_parser("create-campaign-pin")
    create_campaign_parser.add_argument("--current-root", type=Path, required=True)
    create_campaign_parser.add_argument("--source-snapshot-root", type=Path, required=True)
    create_campaign_parser.add_argument("--git-metadata-root", type=Path, required=True)
    create_campaign_parser.add_argument("--pin-path", type=Path, required=True)
    create_campaign_parser.add_argument("--image-id", required=True)
    create_campaign_parser.add_argument("--git-base-commit", required=True)
    verify_campaign_parser = subparsers.add_parser("verify-campaign")
    verify_campaign_parser.add_argument("--current-root", type=Path)
    verify_campaign_parser.add_argument("--source-snapshot-root", type=Path, required=True)
    verify_campaign_parser.add_argument("--git-metadata-root", type=Path, required=True)
    verify_campaign_parser.add_argument("--pin-path", type=Path, required=True)
    clear_candidates_parser = subparsers.add_parser("clear-operator-candidates")
    clear_candidates_parser.add_argument("--candidate-dir", type=Path, required=True)
    seal_candidates_parser = subparsers.add_parser("seal-operator-trust-inputs")
    seal_candidates_parser.add_argument("--candidate-dir", type=Path, required=True)
    seal_candidates_parser.add_argument("--trust-input-dir", type=Path, required=True)
    write_failure_parser = subparsers.add_parser("write-runner-failure-diagnostic")
    write_failure_parser.add_argument("--scratch-root", type=Path, required=True)
    write_failure_parser.add_argument("--private-log-dir", type=Path, required=True)
    write_failure_parser.add_argument("--stage", required=True)
    write_failure_parser.add_argument("--failure-code", required=True)
    consume_failure_parser = subparsers.add_parser("consume-runner-failure-diagnostic")
    consume_failure_parser.add_argument("--scratch-root", type=Path, required=True)
    consume_failure_parser.add_argument("--private-log-dir", type=Path, required=True)
    clear_execution_capture_parser = subparsers.add_parser(
        "clear-live-postgresql-execution-capture"
    )
    clear_execution_capture_parser.add_argument("--scratch-root", type=Path, required=True)
    clear_execution_capture_parser.add_argument("--private-log-dir", type=Path, required=True)
    consume_execution_error_parser = subparsers.add_parser(
        "consume-live-postgresql-execution-error"
    )
    consume_execution_error_parser.add_argument("--scratch-root", type=Path, required=True)
    consume_execution_error_parser.add_argument("--private-log-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "lock-and-exec":
        script_descriptor: int | None = None
        try:
            canonical_root = args.root.resolve(strict=True)
            canonical_script = args.script_path.resolve(strict=True)
        except OSError:
            canonical_root = None
            canonical_script = None
        target_is_trusted = (
            canonical_root is not None
            and canonical_root == args.root
            and canonical_script == args.script_path
            and canonical_script
            == canonical_root / "scripts" / "issue20_containerized_evidence_runner.sh"
        )
        if target_is_trusted:
            try:
                script_descriptor = os.open(
                    canonical_script,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                )
                descriptor_metadata = os.fstat(script_descriptor)
                path_metadata = canonical_script.stat()
                target_is_trusted = (
                    stat.S_ISREG(descriptor_metadata.st_mode)
                    and descriptor_metadata.st_dev == path_metadata.st_dev
                    and descriptor_metadata.st_ino == path_metadata.st_ino
                    and descriptor_metadata.st_uid == path_metadata.st_uid
                    and stat.S_IMODE(descriptor_metadata.st_mode)
                    == stat.S_IMODE(path_metadata.st_mode)
                    and stat.S_IMODE(descriptor_metadata.st_mode) & 0o022 == 0
                )
                if target_is_trusted and script_descriptor == _INVOCATION_LOCK_FD:
                    duplicate = os.dup(script_descriptor)
                    try:
                        os.close(script_descriptor)
                    except OSError:
                        try:
                            os.close(duplicate)
                        except OSError:
                            pass
                        raise
                    script_descriptor = duplicate
                if target_is_trusted:
                    os.set_inheritable(script_descriptor, True)
            except OSError:
                target_is_trusted = False
        if not target_is_trusted:
            if script_descriptor is not None:
                try:
                    os.close(script_descriptor)
                except OSError:
                    pass
            print('{"error":"runner_invocation_lock_unavailable","status":"error"}')
            return 1
        descriptor, error = acquire_invocation_lock()
        if error == "busy":
            try:
                os.close(script_descriptor)
            except OSError:
                pass
            print('{"error":"runner_invocation_busy","status":"error"}')
            return 75
        if descriptor is None:
            try:
                os.close(script_descriptor)
            except OSError:
                pass
            print('{"error":"runner_invocation_lock_unavailable","status":"error"}')
            return 1
        original_lock_descriptor = descriptor
        original_lock_open = True
        installed_lock_descriptor: int | None = (
            descriptor if descriptor == _INVOCATION_LOCK_FD else None
        )
        replaced_lock_descriptor_backup: int | None = None
        replaced_lock_descriptor_inheritable = False
        lock_descriptor_replaced = False
        try:
            if descriptor != _INVOCATION_LOCK_FD:
                try:
                    replaced_lock_descriptor_inheritable = os.get_inheritable(_INVOCATION_LOCK_FD)
                    replaced_lock_descriptor_backup = os.dup(_INVOCATION_LOCK_FD)
                except OSError as error:
                    if error.errno != errno.EBADF:
                        raise
                os.dup2(descriptor, _INVOCATION_LOCK_FD, inheritable=True)
                lock_descriptor_replaced = True
                installed_lock_descriptor = _INVOCATION_LOCK_FD
                os.close(descriptor)
                original_lock_open = False
            else:
                os.set_inheritable(descriptor, True)
            os.execve(
                "/bin/sh",
                [
                    "/bin/sh",
                    f"/proc/self/fd/{script_descriptor}",
                    "__locked-outer",
                    args.mode,
                ],
                dict(os.environ),
            )
        except OSError:
            if lock_descriptor_replaced and replaced_lock_descriptor_backup is not None:
                try:
                    os.dup2(
                        replaced_lock_descriptor_backup,
                        _INVOCATION_LOCK_FD,
                        inheritable=replaced_lock_descriptor_inheritable,
                    )
                except OSError:
                    pass
                else:
                    # Restoring fd 9 atomically closes the installed lock duplicate.
                    installed_lock_descriptor = None
            if replaced_lock_descriptor_backup is not None:
                try:
                    os.close(replaced_lock_descriptor_backup)
                except OSError:
                    pass
            if original_lock_open and original_lock_descriptor != installed_lock_descriptor:
                try:
                    os.close(original_lock_descriptor)
                except OSError:
                    pass
            if installed_lock_descriptor is not None:
                try:
                    os.close(installed_lock_descriptor)
                except OSError:
                    pass
            try:
                os.close(script_descriptor)
            except OSError:
                pass
            print('{"error":"runner_invocation_lock_unavailable","status":"error"}')
            return 1
    if args.command == "verify-held-lock":
        return 0 if verify_held_invocation_lock(args.lock_fd) else 1
    if args.command == "create-campaign-pin":
        return (
            0
            if create_campaign_pin(
                current_root=args.current_root,
                source_snapshot_root=args.source_snapshot_root,
                git_metadata_root=args.git_metadata_root,
                pin_path=args.pin_path,
                image_id=args.image_id,
                git_base_commit=args.git_base_commit,
            )
            else 1
        )
    if args.command == "verify-campaign":
        value = verify_campaign(
            current_root=args.current_root,
            source_snapshot_root=args.source_snapshot_root,
            git_metadata_root=args.git_metadata_root,
            pin_path=args.pin_path,
        )
        if value is None:
            return 1
        print(value["dev_image_id"])
        return 0
    if args.command == "clear-operator-candidates":
        return 0 if clear_operator_candidates(args.candidate_dir) else 1
    if args.command == "seal-operator-trust-inputs":
        return (
            0
            if seal_operator_trust_inputs(
                candidate_dir=args.candidate_dir,
                trust_input_dir=args.trust_input_dir,
            )
            else 1
        )
    if args.command == "write-runner-failure-diagnostic":
        return (
            0
            if write_runner_failure_diagnostic(
                scratch_root=args.scratch_root,
                private_log_dir=args.private_log_dir,
                stage=args.stage,
                failure_code=args.failure_code,
            )
            else 1
        )
    if args.command == "consume-runner-failure-diagnostic":
        diagnostic = consume_runner_failure_diagnostic(
            scratch_root=args.scratch_root,
            private_log_dir=args.private_log_dir,
        )
        if diagnostic is None:
            return 1
        print(f"{diagnostic[0]}:{diagnostic[1]}")
        return 0
    if args.command == "clear-live-postgresql-execution-capture":
        return (
            0
            if clear_live_postgresql_execution_capture(
                scratch_root=args.scratch_root,
                private_log_dir=args.private_log_dir,
            )
            else 1
        )
    if args.command == "consume-live-postgresql-execution-error":
        failure_code = consume_live_postgresql_execution_error(
            scratch_root=args.scratch_root,
            private_log_dir=args.private_log_dir,
        )
        if failure_code is None:
            return 1
        print(failure_code)
        return 0
    return (
        0
        if verify_inner_boundary(
            mode=args.mode,
            root=args.root,
            scratch_root=args.scratch_root,
            source_snapshot_root=args.source_snapshot_root,
            git_metadata_root=args.git_metadata_root,
            campaign_pin=args.campaign_pin,
            reports_dir=args.reports_dir,
            candidate_dir=args.candidate_dir,
            trust_input_dir=args.trust_input_dir,
            script_path=args.script_path,
            python_bin=args.python_bin,
            docker_bin=args.docker_bin,
            docker_socket=args.docker_socket,
            home_dir=args.home_dir,
            docker_config_dir=args.docker_config_dir,
            tmp_dir=args.tmp_dir,
            private_log_dir=args.private_log_dir,
            image_id=args.image_id,
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
