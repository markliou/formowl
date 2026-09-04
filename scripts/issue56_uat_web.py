#!/usr/bin/env python3
"""Serve the minimal Issue #56 real-source browser UAT surface."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
for path in (ROOT, PYTHON_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from formowl_gateway.issue56_uat_runtime import (  # noqa: E402
    create_issue56_temporary_lan_query_service,
    create_issue56_uat_query_service,
)
from formowl_mail.human_uat_http import (  # noqa: E402
    create_mail_human_uat_http_server,
)
from formowl_mail.human_uat_orchestrator import (  # noqa: E402
    CodexAppServerConversationModel,
    CodexAppServerStdioTransport,
    build_hardened_codex_app_server_command,
    validate_codex_runtime_state,
)

_MODEL = "gpt-5.6-sol"
_MAX_PROVIDER_API_KEY_BYTES = 16 * 1024


def _read_codex_provider_api_key(path: Path) -> str:
    if not path.is_absolute():
        raise ValueError("Codex provider API key file must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("Codex provider API key file is invalid") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size <= 0
            or metadata.st_size > _MAX_PROVIDER_API_KEY_BYTES
        ):
            raise ValueError("Codex provider API key file is invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            encoded = stream.read(_MAX_PROVIDER_API_KEY_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(encoded) > _MAX_PROVIDER_API_KEY_BYTES:
        raise ValueError("Codex provider API key file is invalid")
    try:
        value = encoded.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("Codex provider API key file is invalid") from exc
    if not value or "\x00" in value:
        raise ValueError("Codex provider API key file is invalid")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--public-base-url",
        default=os.environ.get("FORMOWL_ISSUE56_UAT_PUBLIC_BASE_URL"),
    )
    parser.add_argument("--temporary-lan-diagnostic", action="store_true")
    parser.add_argument("--temporary-access-code")
    parser.add_argument("--behavior-log", type=Path)
    parser.add_argument("--record-raw-uat-interactions", action="store_true")
    parser.add_argument(
        "--codex-runtime-state-dir",
        type=Path,
        default=os.environ.get("FORMOWL_ISSUE56_UAT_CODEX_RUNTIME_STATE_DIR"),
    )
    parser.add_argument(
        "--codex-command",
        default=os.environ.get("FORMOWL_UAT_CODEX_COMMAND", "codex"),
    )
    parser.add_argument("--codex-provider-api-key-file", type=Path)
    args = parser.parse_args()
    if args.temporary_lan_diagnostic and not args.temporary_access_code:
        parser.error("--temporary-access-code is required for temporary LAN diagnostics")
    if args.temporary_access_code is not None and not args.temporary_lan_diagnostic:
        parser.error("--temporary-access-code is temporary-LAN-only")
    if bool(args.behavior_log) != args.record_raw_uat_interactions:
        parser.error("--behavior-log and --record-raw-uat-interactions must be used together")
    if (args.behavior_log or args.record_raw_uat_interactions) and not (
        args.temporary_lan_diagnostic
    ):
        parser.error("raw behavior recording is temporary-LAN-only")
    if not args.temporary_lan_diagnostic and not args.public_base_url:
        parser.error("--public-base-url or FORMOWL_ISSUE56_UAT_PUBLIC_BASE_URL is required")
    if args.codex_runtime_state_dir is None:
        parser.error(
            "--codex-runtime-state-dir or "
            "FORMOWL_ISSUE56_UAT_CODEX_RUNTIME_STATE_DIR is required"
        )
    runtime_paths = validate_codex_runtime_state(args.codex_runtime_state_dir)
    provider_env_key = runtime_paths.provider_env_key
    transport_options = {}
    if provider_env_key is None:
        if args.codex_provider_api_key_file is not None:
            parser.error("Codex provider API key file is invalid for ChatGPT runtime state")
    else:
        if args.codex_provider_api_key_file is None:
            parser.error("Codex provider API key file is required")
        try:
            provider_api_key = _read_codex_provider_api_key(args.codex_provider_api_key_file)
        except ValueError as exc:
            parser.error(str(exc))
        transport_options = {
            "environment": {provider_env_key: provider_api_key},
            "provider_env_key": provider_env_key,
        }
    conversation_model = CodexAppServerConversationModel(
        CodexAppServerStdioTransport(
            command=build_hardened_codex_app_server_command(args.codex_command),
            cwd=runtime_paths.workspace,
            codex_home=runtime_paths.codex_home,
            runtime_workspace=runtime_paths.workspace,
            **transport_options,
        ),
        workspace_dir=runtime_paths.workspace,
        model=_MODEL,
        reasoning_effort="ultra",
    )
    if args.temporary_lan_diagnostic:
        print(
            f"Temporary LAN diagnostic: http://{args.host}:{args.port}/",
            flush=True,
        )
        print(
            "WARNING: raw prompts and browser-visible results will be recorded."
            if args.record_raw_uat_interactions
            else "Raw UAT interactions are not being recorded.",
            flush=True,
        )
        query_service = create_issue56_temporary_lan_query_service(
            conversation_model,
            behavior_log_path=args.behavior_log,
            record_raw_uat_interactions=args.record_raw_uat_interactions,
        )
    else:
        try:
            query_service = asyncio.run(
                create_issue56_uat_query_service(
                    conversation_model,
                    public_base_url=args.public_base_url,
                )
            )
        except Exception:
            conversation_model.close()
            raise
    with query_service:
        server = create_mail_human_uat_http_server(
            args.host,
            args.port,
            query_service,
            temporary_access_code=(
                args.temporary_access_code if args.temporary_lan_diagnostic else None
            ),
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
