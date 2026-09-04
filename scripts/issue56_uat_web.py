#!/usr/bin/env python3
"""Serve the minimal Issue #56 real-source browser UAT surface."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
for path in (ROOT, PYTHON_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from formowl_gateway.issue56_uat_runtime import (  # noqa: E402
    create_issue56_uat_query_service,
)
from formowl_mail.human_uat_http import (  # noqa: E402
    create_mail_human_uat_http_server,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    with asyncio.run(create_issue56_uat_query_service()) as query_service:
        server = create_mail_human_uat_http_server(
            args.host,
            args.port,
            query_service,
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
