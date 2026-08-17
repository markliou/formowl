#!/usr/bin/env python3
"""Provision or run the isolated Codex app-server sidecar for FormOwl UAT."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import ContractValidationError  # noqa: E402
from formowl_mail import human_uat_orchestrator as _uat_orchestrator  # noqa: E402
from formowl_mail.human_uat_orchestrator import (  # noqa: E402
    CodexAppServerStdioTransport,
    CodexRuntimePaths,
    build_codex_app_server_proxy_command,
    build_codex_runtime_environment,
    build_hardened_codex_app_server_command,
    prepare_codex_runtime_state,
    prepare_codex_runtime_state_from_auth_cache,
    validate_codex_runtime_state,
)

_PRIVATE_PLANNER_ROLE = "private-planner"
_PUBLIC_WEB_GROUNDER_ROLE = "public-web-grounder"
_RUNTIME_ROLES = (_PRIVATE_PLANNER_ROLE, _PUBLIC_WEB_GROUNDER_ROLE)
_MODEL_READINESS_MARKER = "FORMOWL_CODEX_UAT_MODEL_READY"
_MODEL_READINESS_TIMEOUT_SECONDS = 45.0
_MODEL_READINESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "readiness": {
            "type": "string",
            "enum": [_MODEL_READINESS_MARKER],
        }
    },
    "required": ["readiness"],
}
_CODEX_RUNTIME_MARKER = _uat_orchestrator._CODEX_RUNTIME_MARKER  # noqa: SLF001
_CODEX_LOGIN_METHODS = _uat_orchestrator._CODEX_LOGIN_METHODS  # noqa: SLF001
_render_hardened_codex_config = (  # noqa: SLF001
    _uat_orchestrator._render_hardened_codex_config
)
_validate_private_auth_file = (  # noqa: SLF001
    _uat_orchestrator._validate_private_auth_file
)
_validate_chatgpt_auth_cache = (  # noqa: SLF001
    _uat_orchestrator._validate_chatgpt_auth_cache
)


def _role_allows_public_web_search(role: str) -> bool:
    if role not in _RUNTIME_ROLES:
        raise ContractValidationError("Codex UAT runtime role is invalid")
    return role == _PUBLIC_WEB_GROUNDER_ROLE


def _require_dual_runtime_api() -> None:
    """Refuse to provision a web role against the legacy no-web runtime API."""

    for function in (
        prepare_codex_runtime_state,
        prepare_codex_runtime_state_from_auth_cache,
        validate_codex_runtime_state,
        build_hardened_codex_app_server_command,
    ):
        try:
            signature = inspect.signature(function)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("Codex semantic dual-runtime API is unavailable") from exc
        if "allow_public_web_search" not in signature.parameters:
            raise ContractValidationError("Codex semantic dual-runtime API is unavailable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "serve", "probe"))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument(
        "--runtime-role",
        choices=_RUNTIME_ROLES,
        required=True,
        help=(
            "private-planner disables web access; public-web-grounder enables "
            "web search and must use a separate state root and socket."
        ),
    )
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
        _require_dual_runtime_api()
        allow_public_web_search = _role_allows_public_web_search(args.runtime_role)
        if args.command == "init":
            if args.api_key_file is None and not args.chatgpt_auth_stdin:
                parser.error("init requires exactly one Codex authentication source")
            if args.socket_path is not None:
                parser.error("init does not accept --socket-path")
            if args.chatgpt_auth_stdin:
                paths = prepare_codex_runtime_state_from_auth_cache(
                    state_dir=args.state_dir,
                    auth_cache=_read_auth_cache_stdin(),
                    allow_public_web_search=allow_public_web_search,
                )
            else:
                api_key = _read_secret(args.api_key_file)
                paths = prepare_codex_runtime_state(
                    codex_command=args.codex_command,
                    state_dir=args.state_dir,
                    api_key=api_key,
                    allow_public_web_search=allow_public_web_search,
                )
            print(
                "FORMOWL_CODEX_UAT_RUNTIME_INITIALIZED "
                f"runtime_role={args.runtime_role} "
                f"state_dir={paths.state_dir} login_method={paths.login_method}",
                flush=True,
            )
            return 0

        if args.socket_path is None:
            parser.error(f"{args.command} requires --socket-path")
        if args.api_key_file is not None or args.chatgpt_auth_stdin:
            parser.error(f"{args.command} does not accept authentication input")
        if args.command == "probe":
            if allow_public_web_search:
                parser.error("probe requires the private-planner runtime")
            paths = _validate_codex_runtime_state_readonly(
                args.state_dir,
                allow_public_web_search=False,
            )
            _probe_authenticated_model_response(
                paths=paths,
                socket_path=args.socket_path,
            )
            print(_MODEL_READINESS_MARKER, flush=True)
            return 0
        paths = validate_codex_runtime_state(
            args.state_dir,
            allow_public_web_search=allow_public_web_search,
        )
        socket_path = _prepare_socket_path(args.socket_path)
        command = build_hardened_codex_app_server_command(
            args.codex_command,
            listen_url=f"unix://{socket_path}",
            allow_public_web_search=allow_public_web_search,
        )
        environment = build_codex_runtime_environment(paths.codex_home)
        os.execvpe(command[0], command, environment)
    except (ContractValidationError, OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


def _probe_authenticated_model_response(
    *,
    paths: CodexRuntimePaths,
    socket_path: Path,
) -> None:
    """Require one bounded authenticated model turn without tools or MCP."""

    command = build_codex_app_server_proxy_command(socket_path=socket_path)
    with tempfile.TemporaryDirectory(prefix="formowl-uat-model-probe-") as temporary:
        proxy_root = Path(temporary)
        proxy_home = proxy_root / "proxy-home"
        proxy_workspace = proxy_root / "proxy-workspace"
        proxy_home.mkdir(mode=0o700)
        proxy_workspace.mkdir(mode=0o700)
        transport = CodexAppServerStdioTransport(
            command=command,
            cwd=proxy_workspace,
            codex_home=proxy_home,
            runtime_workspace=paths.workspace,
            timeout_seconds=_MODEL_READINESS_TIMEOUT_SECONDS,
            allow_public_web_search=False,
        )
        thread_id: str | None = None
        try:
            thread = transport.start_thread(
                model=None,
                cwd=paths.workspace,
                base_instructions=(
                    "You are a bounded FormOwl UAT model-readiness probe. "
                    "Return only the JSON object required by the output schema."
                ),
                developer_instructions=(
                    "Do not use tools, MCP, files, network search, or private data."
                ),
                dynamic_tools=(),
                timeout_seconds=_MODEL_READINESS_TIMEOUT_SECONDS,
            )
            thread_id = thread.thread_id
            turn = transport.run_turn(
                thread_id=thread_id,
                user_text="Return the required readiness object now.",
                additional_context={},
                output_schema=_MODEL_READINESS_SCHEMA,
                reasoning_effort="low",
                client_metadata={"surface": "formowl_uat_model_readiness"},
                tool_handler=_reject_probe_tool_call,
                timeout_seconds=_MODEL_READINESS_TIMEOUT_SECONDS,
            )
            try:
                payload = json.loads(turn.final_message)
            except (json.JSONDecodeError, TypeError) as exc:
                raise RuntimeError("Codex authenticated model readiness probe failed") from exc
            if payload != {"readiness": _MODEL_READINESS_MARKER}:
                raise RuntimeError("Codex authenticated model readiness probe failed")
        finally:
            if thread_id is not None:
                transport.delete_thread(
                    thread_id,
                    timeout_seconds=min(_MODEL_READINESS_TIMEOUT_SECONDS, 10.0),
                )
            transport.close()


def _validate_codex_runtime_state_readonly(
    state_dir: Path,
    *,
    allow_public_web_search: bool,
) -> CodexRuntimePaths:
    """Validate mounted runtime state without mkdir or chmod side effects."""

    state = _existing_private_directory(state_dir, "Codex runtime state")
    home = _existing_private_directory(state / "codex-home", "Codex home")
    workspace = _existing_private_directory(
        state / "codex-workspace",
        "Codex app-server workspace",
        require_empty=True,
    )
    marker_path = state / _CODEX_RUNTIME_MARKER
    config_path = home / "config.toml"
    allowed_state_entries = {
        home.name,
        workspace.name,
        marker_path.name,
    }
    if {entry.name for entry in state.iterdir()} != allowed_state_entries:
        raise ContractValidationError("Codex runtime state contains unexpected data")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        config_text = config_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractValidationError("Codex runtime state is not provisioned") from exc
    login_method = marker.get("login_method") if isinstance(marker, dict) else None
    if login_method not in _CODEX_LOGIN_METHODS:
        raise ContractValidationError("Codex runtime state integrity check failed")
    expected_marker = {
        "format": "formowl_uat_codex_runtime",
        "version": 3,
        "login_method": login_method,
        "allow_public_web_search": allow_public_web_search,
        "config_sha256": hashlib.sha256(config_text.encode("utf-8")).hexdigest(),
    }
    if marker != expected_marker or config_text != _render_hardened_codex_config(
        home,
        login_method=login_method,
        allow_public_web_search=allow_public_web_search,
    ):
        raise ContractValidationError("Codex runtime state integrity check failed")
    auth_path = home / "auth.json"
    _validate_private_auth_file(auth_path)
    if login_method == "chatgpt":
        try:
            auth_cache = auth_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ContractValidationError("Codex runtime state is not provisioned") from exc
        _validate_chatgpt_auth_cache(auth_cache)
    return CodexRuntimePaths(
        state_dir=state,
        codex_home=home,
        workspace=workspace,
        login_method=login_method,
    )


def _existing_private_directory(
    path: Path,
    label: str,
    *,
    require_empty: bool = False,
) -> Path:
    if not path.is_absolute():
        raise ContractValidationError(f"{label} must be absolute")
    _reject_symlink_ancestry(path, label)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ContractValidationError(f"{label} is invalid") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ContractValidationError(f"{label} is invalid")
    if require_empty and any(path.iterdir()):
        raise ContractValidationError(f"{label} must be empty")
    return path


def _reject_probe_tool_call(
    _tool_name: str,
    _arguments: object,
) -> dict[str, object]:
    raise RuntimeError("Codex model readiness probe must not invoke tools")


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
    _reject_symlink_ancestry(parent, "Codex app-server socket")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        mode = os.lstat(path).st_mode
        if not stat.S_ISSOCK(mode):
            raise ContractValidationError("Codex app-server socket path is occupied")
        path.unlink()
    return path


def _reject_symlink_ancestry(path: Path, label: str) -> None:
    for candidate in (path, *path.parents):
        try:
            mode = os.lstat(candidate).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ContractValidationError(f"{label} ancestry could not be inspected") from exc
        if stat.S_ISLNK(mode):
            raise ContractValidationError(f"{label} ancestry must not contain symlinks")


if __name__ == "__main__":
    raise SystemExit(main())
