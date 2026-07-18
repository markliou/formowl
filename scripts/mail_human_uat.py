#!/usr/bin/env python3
"""Run the temporary FormOwl mail upload and evidence human-UAT web surface."""

from __future__ import annotations

import argparse
import json
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--private-manifest", type=Path, required=True)
    parser.add_argument("--bundle-cache", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.port < 0 or args.port > 65535:
        parser.error("--port must be between 0 and 65535")

    manifest = json.loads(args.private_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        parser.error("--private-manifest must contain a JSON object")
    bundle = load_or_rebuild_may_mail_evidence_bundle(
        args.corpus_root,
        manifest,
        cache_path=args.bundle_cache,
    )
    service = MailHumanUatService(
        MailHumanUatHttpConfig(
            bundle=bundle,
            state_dir=args.state_dir,
        )
    )
    server = create_mail_human_uat_http_server(args.host, args.port, service)
    print(
        "FORMOWL_MAIL_UAT_READY "
        f"host={args.host} port={server.server_address[1]} "
        f"messages={len(bundle.messages)} upload_supported=true "
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
