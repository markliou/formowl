"""Packaged facade for FormOwl KG research-evaluation authority."""

from .runner import (
    KG_EVAL_COMMANDS,
    KGEvalCommandResult,
    build_acceptance_summary,
    kg_eval_workspace,
    run_kg_eval_command,
)

__all__ = [
    "KG_EVAL_COMMANDS",
    "KGEvalCommandResult",
    "build_acceptance_summary",
    "kg_eval_workspace",
    "run_kg_eval_command",
]
