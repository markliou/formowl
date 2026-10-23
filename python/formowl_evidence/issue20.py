"""Current-source binding for issue #20 runtime and external evidence."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
import stat


ISSUE20_IMPLEMENTATION_DEPLOY_CONTRACT_PATHS = (
    "deploy/connected/Caddyfile.example",
    "deploy/connected/compose.env.example",
    "deploy/connected/operator_config.py",
    "deploy/connected/secrets/README.md",
    "deploy/connected/signing-key-set.example.json",
)

ISSUE20_IMPLEMENTATION_CONTRACT_GLOBS = (
    "pyproject.toml",
    "compose.yaml",
    "containers/dev/Dockerfile",
    "containers/runtime/Dockerfile",
    *ISSUE20_IMPLEMENTATION_DEPLOY_CONTRACT_PATHS,
    "python/formowl_auth/**/*.py",
    "python/formowl_contract/**/*.py",
    "python/formowl_evidence/**/*.py",
    "python/formowl_gateway/**/*.py",
    "python/formowl_graph/storage/**/*.py",
    "python/formowl_graph/storage/migrations/*.sql",
    "python/formowl_ingestion/storage/**/*.py",
    "python/formowl_ingestion/uploads.py",
    "python/formowl_mail/__init__.py",
    "python/formowl_mail/upload_session.py",
    "scripts/connected_runtime_container_lifecycle_probe.py",
    "scripts/connected_runtime_postgres_live_e2e.py",
    "scripts/connected_operator_postgres_live_journey.py",
    "scripts/issue20_containerized_evidence_runner.sh",
    "scripts/issue20_runner_boundary.py",
    "scripts/oauth_mcp_harness.py",
    "tests/oauth_harness.py",
)


def issue20_implementation_contract_hash(root: Path) -> str:
    """Hash the current issue #20 runtime, deploy, migration, and harness contract."""

    file_hashes: dict[str, str] = {}
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    file_flags |= getattr(os, "O_NOFOLLOW", 0)
    file_flags |= getattr(os, "O_NONBLOCK", 0)
    absolute_root = root.absolute()
    root_descriptor: int | None = None
    try:
        root_descriptor = os.open("/", directory_flags)
        for component in absolute_root.parts[1:]:
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=root_descriptor,
            )
            os.close(root_descriptor)
            root_descriptor = next_descriptor
        if not stat.S_ISDIR(os.fstat(root_descriptor).st_mode):
            raise OSError

        for pattern in ISSUE20_IMPLEMENTATION_CONTRACT_GLOBS:
            components = tuple(pattern.split("/"))
            if not components or any(component in {"", ".", ".."} for component in components):
                raise OSError
            match_count = 0
            pending = [(os.dup(root_descriptor), tuple(), 0)]
            try:
                while pending:
                    directory_descriptor, relative_parts, component_index = pending.pop()
                    try:
                        component = components[component_index]
                        if component == "**":
                            pending.append(
                                (
                                    os.dup(directory_descriptor),
                                    relative_parts,
                                    component_index + 1,
                                )
                            )
                            with os.scandir(directory_descriptor) as entries:
                                for entry in sorted(entries, key=lambda item: item.name):
                                    metadata = entry.stat(follow_symlinks=False)
                                    if stat.S_ISLNK(metadata.st_mode):
                                        raise OSError
                                    if stat.S_ISDIR(metadata.st_mode):
                                        child_descriptor = os.open(
                                            entry.name,
                                            directory_flags,
                                            dir_fd=directory_descriptor,
                                        )
                                        pending.append(
                                            (
                                                child_descriptor,
                                                (*relative_parts, entry.name),
                                                component_index,
                                            )
                                        )
                                    elif not stat.S_ISREG(metadata.st_mode):
                                        raise OSError
                            continue

                        wildcard = any(marker in component for marker in "*?[")
                        if wildcard:
                            with os.scandir(directory_descriptor) as entries:
                                names = sorted(
                                    entry.name
                                    for entry in entries
                                    if fnmatch.fnmatchcase(entry.name, component)
                                )
                        else:
                            names = [component]
                        for name in names:
                            try:
                                metadata = os.stat(
                                    name,
                                    dir_fd=directory_descriptor,
                                    follow_symlinks=False,
                                )
                            except FileNotFoundError:
                                continue
                            if stat.S_ISLNK(metadata.st_mode):
                                raise OSError
                            relative = (*relative_parts, name)
                            if component_index + 1 < len(components):
                                if not stat.S_ISDIR(metadata.st_mode):
                                    if wildcard:
                                        continue
                                    raise OSError
                                child_descriptor = os.open(
                                    name,
                                    directory_flags,
                                    dir_fd=directory_descriptor,
                                )
                                pending.append(
                                    (
                                        child_descriptor,
                                        relative,
                                        component_index + 1,
                                    )
                                )
                                continue
                            if not stat.S_ISREG(metadata.st_mode):
                                raise OSError
                            file_descriptor = os.open(
                                name,
                                file_flags,
                                dir_fd=directory_descriptor,
                            )
                            try:
                                opened_metadata = os.fstat(file_descriptor)
                                if not stat.S_ISREG(opened_metadata.st_mode):
                                    raise OSError
                                chunks: list[bytes] = []
                                while chunk := os.read(file_descriptor, 1024 * 1024):
                                    chunks.append(chunk)
                            finally:
                                os.close(file_descriptor)
                            match_count += 1
                            relative_path = "/".join(relative)
                            file_hashes[relative_path] = (
                                "sha256:" + hashlib.sha256(b"".join(chunks)).hexdigest()
                            )
                    finally:
                        os.close(directory_descriptor)
            finally:
                for directory_descriptor, _, _ in pending:
                    os.close(directory_descriptor)
            if match_count == 0:
                raise RuntimeError("issue20_implementation_contract_missing")
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("issue20_implementation_contract_invalid") from None
    finally:
        if root_descriptor is not None:
            os.close(root_descriptor)
    payload = json.dumps(
        {
            "contract_type": "issue20_current_implementation_contract_v1",
            "files": file_hashes,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
