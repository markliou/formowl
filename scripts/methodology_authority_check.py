#!/usr/bin/env python3
"""Validate FormOwl's active methodology authority and readiness gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_core.methodology_authority import (  # noqa: E402
    check_methodology_authority,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="Validate manifest/runtime consistency without requiring readiness.",
    )
    mode.add_argument(
        "--require-ready",
        action="store_true",
        help="Fail unless every methodology/runtime gate is passed.",
    )
    parser.add_argument(
        "--authority",
        type=Path,
        default=None,
        help="Optional authority manifest override for validation tests.",
    )
    args = parser.parse_args(argv)

    authority_path = args.authority
    if authority_path is not None and not authority_path.is_absolute():
        authority_path = ROOT / authority_path
    result = check_methodology_authority(
        repository_root=ROOT,
        authority_path=authority_path,
    )
    print(json.dumps(result.to_safe_dict(), indent=2, sort_keys=True))
    if not result.authority_valid:
        return 2
    if args.require_ready and not result.methodology_ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
