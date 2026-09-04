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
    prepare_codex_runtime_state_for_custom_provider,
    prepare_codex_runtime_state_from_auth_cache,
    prepare_codex_runtime_state_with_device_auth,
    validate_codex_runtime_state,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "serve"))
    parser.add_argument("--state-dir", type=Path, required=True)
    auth_group = parser.add_mutually_exclusive_group()
    auth_group.add_argument(
        "--device-auth",
        action="store_true",
        help="Run isolated ChatGPT device authentication during init.",
    )
    auth_group.add_argument(
        "--chatgpt-auth-stdin",
        action="store_true",
        help="Read an existing Codex ChatGPT auth.json from stdin during init.",
    )
    auth_group.add_argument(
        "--custom-provider",
        action="store_true",
        help="Provision a secretless runtime for one explicit custom provider.",
    )
    parser.add_argument("--custom-provider-base-url")
    parser.add_argument("--custom-provider-env-key")
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
            if not any(
                (
                    args.device_auth,
                    args.chatgpt_auth_stdin,
                    args.custom_provider,
                )
            ):
                parser.error("init requires exactly one Codex authentication source")
            if args.socket_path is not None:
                parser.error("init does not accept --socket-path")
            if args.custom_provider:
                if not args.custom_provider_base_url or not args.custom_provider_env_key:
                    parser.error("custom-provider init requires base URL and environment key")
                paths = prepare_codex_runtime_state_for_custom_provider(
                    state_dir=args.state_dir,
                    base_url=args.custom_provider_base_url,
                    env_key=args.custom_provider_env_key,
                )
            elif args.custom_provider_base_url or args.custom_provider_env_key:
                parser.error("custom-provider metadata requires --custom-provider")
            elif args.chatgpt_auth_stdin:
                paths = prepare_codex_runtime_state_from_auth_cache(
                    state_dir=args.state_dir,
                    auth_cache=_read_auth_cache_stdin(),
                )
            else:
                paths = prepare_codex_runtime_state_with_device_auth(
                    codex_command=args.codex_command,
                    state_dir=args.state_dir,
                )
            print(
                "FORMOWL_CODEX_UAT_RUNTIME_INITIALIZED "
                f"state_dir={paths.state_dir} login_method={paths.login_method}",
                flush=True,
            )
            return 0

        if args.socket_path is None:
            parser.error("serve requires --socket-path")
        if (
            args.device_auth
            or args.chatgpt_auth_stdin
            or args.custom_provider
            or args.custom_provider_base_url
            or args.custom_provider_env_key
        ):
            parser.error("serve does not accept authentication input")
        paths = validate_codex_runtime_state(args.state_dir)
        socket_path = _prepare_socket_path(args.socket_path)
        command = build_hardened_codex_app_server_command(
            args.codex_command,
            listen_url=f"unix://{socket_path}",
        )
        environment = build_codex_runtime_environment(
            paths.codex_home,
            provider_env_key=paths.provider_env_key,
        )
        os.execvpe(command[0], command, environment)
    except (ContractValidationError, OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


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
