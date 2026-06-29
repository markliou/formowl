"""Command line entry point for packaged KG research-evaluation tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .runner import KG_EVAL_COMMANDS, build_acceptance_summary, run_kg_eval_command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="formowl-kg-eval",
        description="Run or summarize the FormOwl KG research-evaluation harness.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="FormOwl repository root. Defaults to FORMOWL_REPOSITORY_ROOT or the editable checkout.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("summary", help="Print a stable JSON summary for system integration.")
    subparsers.add_parser("all", help="Run total, objective, preflight, work-orders, and progress.")
    for command in sorted(KG_EVAL_COMMANDS):
        subparsers.add_parser(command, help=f"Run the authoritative {command} KG eval script.")

    args = parser.parse_args(argv)
    if args.command == "summary":
        print(
            json.dumps(
                build_acceptance_summary(repository_root=args.repo_root), indent=2, sort_keys=True
            )
        )
        return 0
    if args.command == "all":
        return _run_many(list(KG_EVAL_COMMANDS), repository_root=args.repo_root)
    return _run_many([args.command], repository_root=args.repo_root)


def _run_many(commands: list[str], *, repository_root: Path | None) -> int:
    final_returncode = 0
    for command in commands:
        result = run_kg_eval_command(command, repository_root=repository_root)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode and final_returncode == 0:
            final_returncode = result.returncode
    return final_returncode


if __name__ == "__main__":
    raise SystemExit(main())
