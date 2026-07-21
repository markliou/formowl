#!/usr/bin/env python3
"""Run the temporary FormOwl mail upload and evidence human-UAT web surface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_evaluator import load_or_rebuild_may_mail_evidence_bundle  # noqa: E402
from formowl_mail.human_uat_http import (  # noqa: E402
    MailHumanUatHttpConfig,
    MailHumanUatService,
    create_mail_human_uat_http_server,
)
from formowl_mail.human_uat_orchestrator import (  # noqa: E402
    CodexAppServerConversationModel,
    CodexAppServerStdioTransport,
    build_codex_app_server_proxy_command,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--private-manifest", type=Path, required=True)
    parser.add_argument("--bundle-cache", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--codex-socket", type=Path, required=True)
    parser.add_argument(
        "--codex-runtime-state-dir",
        type=Path,
        default=Path("/codex-state"),
        help=(
            "Path used by the isolated Codex sidecar; only the derived "
            "<path>/codex-workspace is sent over the private socket."
        ),
    )
    args = parser.parse_args()

    if args.port < 0 or args.port > 65535:
        parser.error("--port must be between 0 and 65535")

    manifest = json.loads(args.private_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        parser.error("--private-manifest must contain a JSON object")
    proxy_home = args.state_dir / "codex-proxy-home"
    proxy_workspace = args.state_dir / "codex-proxy-workspace"
    codex_runtime_workspace = args.codex_runtime_state_dir / "codex-workspace"
    model_name = os.environ.get(
        "FORMOWL_UAT_CODEX_MODEL",
        os.environ.get("FORMOWL_UAT_MODEL", ""),
    ).strip()
    reasoning_effort = os.environ.get(
        "FORMOWL_UAT_CODEX_REASONING_EFFORT",
        os.environ.get("FORMOWL_UAT_REASONING_EFFORT", "low"),
    )
    transport = CodexAppServerStdioTransport(
        command=build_codex_app_server_proxy_command(
            socket_path=args.codex_socket,
        ),
        cwd=proxy_workspace,
        codex_home=proxy_home,
        runtime_workspace=codex_runtime_workspace,
    )
    conversation_model = CodexAppServerConversationModel(
        transport,
        workspace_dir=codex_runtime_workspace,
        model=model_name or None,
        reasoning_effort=reasoning_effort,
    )
    try:
        bundle = load_or_rebuild_may_mail_evidence_bundle(
            args.corpus_root,
            manifest,
            cache_path=args.bundle_cache,
        )
        service = MailHumanUatService(
            MailHumanUatHttpConfig(
                bundle=bundle,
                state_dir=args.state_dir,
                conversation_model=conversation_model,
            )
        )
        server = create_mail_human_uat_http_server(args.host, args.port, service)
        print(
            "FORMOWL_MAIL_UAT_READY "
            f"host={args.host} port={server.server_address[1]} "
            f"messages={len(bundle.messages)} upload_supported=true "
            f"orchestrator_model={conversation_model.model_name} "
            "conversation_engine=codex_app_server "
            "authentication_required=false shared_uat=true "
            "business_systems_read_only=true",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        conversation_model.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
