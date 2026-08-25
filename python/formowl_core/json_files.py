from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any


def read_json_object(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    value = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_descriptor = os.open(path.parent, directory_flags)
    temporary_descriptor: int | None = None
    temporary_identity: tuple[int, int] | None = None
    temporary_created = False
    backup_name: str | None = None
    backup_identity: tuple[int, int] | None = None
    replacement_committed = False
    try:
        temporary_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        temporary_flags |= getattr(os, "O_CLOEXEC", 0)
        temporary_flags |= getattr(os, "O_NOFOLLOW", 0)
        temporary_descriptor = os.open(
            temporary_path.name,
            temporary_flags,
            0o666,
            dir_fd=directory_descriptor,
        )
        temporary_metadata = os.fstat(temporary_descriptor)
        if not stat.S_ISREG(temporary_metadata.st_mode):
            raise OSError("atomic JSON temporary target is not a regular file")
        temporary_identity = (temporary_metadata.st_dev, temporary_metadata.st_ino)
        temporary_created = True
        remaining = memoryview(value)
        while remaining:
            written = os.write(temporary_descriptor, remaining)
            if written <= 0 or written > len(remaining):
                raise OSError("atomic JSON temporary write failed")
            remaining = remaining[written:]
        os.fsync(temporary_descriptor)
        os.close(temporary_descriptor)
        temporary_descriptor = None
        current_metadata = os.stat(
            temporary_path.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(current_metadata.st_mode)
            or (current_metadata.st_dev, current_metadata.st_ino) != temporary_identity
        ):
            raise OSError("atomic JSON temporary target changed")
        try:
            destination_metadata = os.stat(
                path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            destination_metadata = None
        if destination_metadata is not None and not stat.S_ISDIR(destination_metadata.st_mode):
            for _ in range(16):
                candidate = f".{path.name}.{secrets.token_hex(16)}.bak"
                try:
                    os.link(
                        path.name,
                        candidate,
                        src_dir_fd=directory_descriptor,
                        dst_dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    continue
                backup_name = candidate
                backup_metadata = os.stat(
                    candidate,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                backup_identity = (backup_metadata.st_dev, backup_metadata.st_ino)
                if (
                    backup_metadata.st_dev,
                    backup_metadata.st_ino,
                ) != (
                    destination_metadata.st_dev,
                    destination_metadata.st_ino,
                ):
                    raise OSError("atomic JSON backup target changed")
                os.fsync(directory_descriptor)
                break
            else:
                raise OSError("atomic JSON backup creation failed")
        os.replace(
            temporary_path.name,
            path.name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        temporary_created = False
        replacement_committed = True
        os.fsync(directory_descriptor)
        if backup_name is not None and backup_identity is not None:
            backup_metadata = os.stat(
                backup_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (backup_metadata.st_dev, backup_metadata.st_ino) != backup_identity:
                raise OSError("atomic JSON backup target changed")
            os.unlink(backup_name, dir_fd=directory_descriptor)
            backup_name = None
            backup_identity = None
    except Exception:
        if temporary_descriptor is not None:
            try:
                os.close(temporary_descriptor)
            except OSError:
                pass
        if replacement_committed:
            if backup_name is not None and backup_identity is not None:
                backup_metadata = os.stat(
                    backup_name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if (backup_metadata.st_dev, backup_metadata.st_ino) != backup_identity:
                    raise OSError("atomic JSON backup target changed") from None
                os.replace(
                    backup_name,
                    path.name,
                    src_dir_fd=directory_descriptor,
                    dst_dir_fd=directory_descriptor,
                )
                backup_name = None
                backup_identity = None
            else:
                os.unlink(path.name, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
        elif temporary_created and temporary_identity is not None:
            try:
                current_metadata = os.stat(
                    temporary_path.name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                if (
                    stat.S_ISREG(current_metadata.st_mode)
                    and (
                        current_metadata.st_dev,
                        current_metadata.st_ino,
                    )
                    == temporary_identity
                ):
                    os.unlink(temporary_path.name, dir_fd=directory_descriptor)
        if backup_name is not None and backup_identity is not None:
            backup_metadata = os.stat(
                backup_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (backup_metadata.st_dev, backup_metadata.st_ino) != backup_identity:
                raise OSError("atomic JSON backup target changed") from None
            os.unlink(backup_name, dir_fd=directory_descriptor)
        raise
    finally:
        try:
            os.close(directory_descriptor)
        except OSError:
            pass
