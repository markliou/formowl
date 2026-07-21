#!/usr/bin/env python3
"""Provision or run the isolated Codex app-server sidecar for FormOwl UAT."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import ContractValidationError  # noqa: E402
from formowl_mail.human_uat_orchestrator import (  # noqa: E402
    build_codex_runtime_environment,
    build_hardened_codex_app_server_command,
    prepare_codex_runtime_state,
    prepare_codex_runtime_state_from_auth_cache,
    validate_codex_runtime_state,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "serve"))
    parser.add_argument("--state-dir", type=Path, required=True)
    auth_group = parser.add_mutually_exclusive_group()
    auth_group.add_argument(
        "--api-key-file",
        type=Path,
        help="Required only for the one-shot init command.",
    )
    auth_group.add_argument(
        "--chatgpt-auth-stdin",
        action="store_true",
        help="Read an existing Codex ChatGPT auth.json from stdin during init.",
    )
    parser.add_argument(
        "--socket-path",
        type=Path,
        help="Required only for the serve command.",
    )
    parser.add_argument(
        "--codex-command",
        default=os.environ.get("FORMOWL_UAT_CODEX_COMMAND", "codex"),
    )
    args = parser.parse_args()

    if os.geteuid() == 0:
        parser.error("the Codex UAT sidecar must run as a non-root user")

    try:
        if args.command == "init":
            if args.api_key_file is None and not args.chatgpt_auth_stdin:
                parser.error("init requires exactly one Codex authentication source")
            if args.socket_path is not None:
                parser.error("init does not accept --socket-path")
            if args.chatgpt_auth_stdin:
                paths = prepare_codex_runtime_state_from_auth_cache(
                    state_dir=args.state_dir,
                    auth_cache=_read_auth_cache_stdin(),
                )
            else:
                api_key = _read_secret(args.api_key_file)
                paths = prepare_codex_runtime_state(
                    codex_command=args.codex_command,
                    state_dir=args.state_dir,
                    api_key=api_key,
                )
            print(
                "FORMOWL_CODEX_UAT_RUNTIME_INITIALIZED "
                f"state_dir={paths.state_dir} login_method={paths.login_method}",
                flush=True,
            )
            return 0

        if args.socket_path is None:
            parser.error("serve requires --socket-path")
        if args.api_key_file is not None or args.chatgpt_auth_stdin:
            parser.error("serve does not accept authentication input")
        paths = validate_codex_runtime_state(args.state_dir)
        socket_path = _prepare_socket_path(args.socket_path)
        command = build_hardened_codex_app_server_command(
            args.codex_command,
            listen_url=f"unix://{socket_path}",
        )
        environment = build_codex_runtime_environment(paths.codex_home)
        os.execvpe(command[0], command, environment)
    except (ContractValidationError, OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


def _read_secret(path: Path) -> str:
    if path.is_symlink():
        raise ContractValidationError("API key file must not be a symlink")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ContractValidationError("API key file could not be read") from exc
    if not value:
        raise ContractValidationError("API key file is empty")
    return value


def _read_auth_cache_stdin() -> str:
    value = sys.stdin.read(64 * 1024 + 1)
    if len(value.encode("utf-8")) > 64 * 1024:
        raise ContractValidationError("Codex ChatGPT auth cache is invalid")
    if not value.strip():
        raise ContractValidationError("Codex ChatGPT auth cache is empty")
    return value


def _prepare_socket_path(path: Path) -> Path:
    if not path.is_absolute():
        raise ContractValidationError("Codex app-server socket path must be absolute")
    parent = path.parent
    for candidate in (parent, *parent.parents):
        try:
            mode = os.lstat(candidate).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ContractValidationError(
                "Codex app-server socket ancestry could not be inspected"
            ) from exc
        if stat.S_ISLNK(mode):
            raise ContractValidationError(
                "Codex app-server socket ancestry must not contain symlinks"
            )
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        mode = os.lstat(path).st_mode
        if not stat.S_ISSOCK(mode):
            raise ContractValidationError("Codex app-server socket path is occupied")
        path.unlink()
    return path


if __name__ == "__main__":
    raise SystemExit(main())
