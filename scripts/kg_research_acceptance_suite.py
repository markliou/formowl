#!/usr/bin/env python3
"""Print the FormOwl KG research acceptance report."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_graph.research_acceptance import (  # noqa: E402
    report_to_json,
    run_kg_research_acceptance_suite,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when the report contains failed or blocked requirements.",
    )
    args = parser.parse_args()
    report = run_kg_research_acceptance_suite(repository_root=ROOT)
    print(report_to_json(report))
    if args.strict and (
        report.known_failed_requirement_ids or report.known_blocked_requirement_ids
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
