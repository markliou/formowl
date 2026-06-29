"""Stable package facade over the repo-local KG evaluation harness.

The authoritative validators still live under `.formowl/kg-eval`. This module
provides a narrow API and CLI-friendly runner so downstream system work can call
the research harness without importing ad hoc script paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from formowl_graph import build_candidate_generation_capability_summary

from .benchmarks import build_benchmark_summary


KG_EVAL_COMMANDS: dict[str, str] = {
    "total": "kg_total_acceptance_suite.py",
    "objective": "kg_objective_completion_audit.py",
    "preflight": "real_evidence_preflight.py",
    "work-orders": "real_evidence_collection_work_orders.py",
    "progress": "real_evidence_gate_progress.py",
}

REPORT_PATHS: dict[str, str] = {
    "total": "results/kg_total_acceptance_snapshot.json",
    "objective": "results/kg_objective_completion_audit.json",
    "preflight": "results/real_evidence_preflight.json",
    "work_orders": "results/real_evidence_collection_work_orders.json",
    "progress": "results/real_evidence_gate_progress.json",
    "checklist": "remaining_evidence_checklist.json",
}


@dataclass(frozen=True)
class KGEvalCommandResult:
    """Result from invoking one KG evaluation command."""

    command: str
    script: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def default_repository_root() -> Path:
    """Return the repository root for an editable checkout or configured install."""

    configured = os.environ.get("FORMOWL_REPOSITORY_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def kg_eval_workspace(repository_root: Path | str | None = None) -> Path:
    """Resolve the repo-local KG evaluation workspace."""

    root = (
        Path(repository_root).expanduser().resolve()
        if repository_root
        else default_repository_root()
    )
    workspace = root / ".formowl" / "kg-eval"
    if not workspace.is_dir():
        raise FileNotFoundError(f"KG evaluation workspace not found: {workspace}")
    return workspace


def run_kg_eval_command(
    command: str,
    *,
    repository_root: Path | str | None = None,
    extra_args: list[str] | tuple[str, ...] = (),
) -> KGEvalCommandResult:
    """Run one authoritative KG evaluation script through the package facade."""

    if command not in KG_EVAL_COMMANDS:
        allowed = ", ".join(sorted(KG_EVAL_COMMANDS))
        raise ValueError(f"unknown KG eval command {command!r}; expected one of: {allowed}")
    workspace = kg_eval_workspace(repository_root)
    script = KG_EVAL_COMMANDS[command]
    script_path = workspace / script
    if not script_path.is_file():
        raise FileNotFoundError(f"KG evaluation script not found: {script_path}")
    completed = subprocess.run(
        [sys.executable, script, *extra_args],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )
    repository_root = workspace.parents[1]
    return KGEvalCommandResult(
        command=command,
        script=script,
        returncode=completed.returncode,
        stdout=_redact_local_paths(
            completed.stdout,
            repository_root=repository_root,
            workspace=workspace,
        ),
        stderr=_redact_local_paths(
            completed.stderr,
            repository_root=repository_root,
            workspace=workspace,
        ),
    )


def load_report(report_name: str, *, repository_root: Path | str | None = None) -> dict[str, Any]:
    """Load one persisted KG evaluation report by stable package name."""

    if report_name not in REPORT_PATHS:
        allowed = ", ".join(sorted(REPORT_PATHS))
        raise ValueError(f"unknown KG eval report {report_name!r}; expected one of: {allowed}")
    report_path = kg_eval_workspace(repository_root) / REPORT_PATHS[report_name]
    if not report_path.is_file():
        raise FileNotFoundError(f"KG evaluation report not found: {report_path}")
    with report_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"KG evaluation report is not a JSON object: {report_path}")
    return payload


def build_acceptance_summary(*, repository_root: Path | str | None = None) -> dict[str, Any]:
    """Build a stable, redacted summary for system integration."""

    total = load_report("total", repository_root=repository_root)
    objective = load_report("objective", repository_root=repository_root)
    preflight = load_report("preflight", repository_root=repository_root)
    work_orders = load_report("work_orders", repository_root=repository_root)
    progress = load_report("progress", repository_root=repository_root)
    checklist = load_report("checklist", repository_root=repository_root)

    total_summary = _dict_at(total, "summary")
    preflight_summary = _dict_at(preflight, "summary")
    work_order_summary = _dict_at(work_orders, "summary")
    progress_summary = _dict_at(progress, "summary")

    return {
        "artifact_id": "formowl_kg_eval_acceptance_summary_v1",
        "claim_boundary": {
            "supports_broad_kg_real_evidence_acceptance_claim": bool(
                total_summary.get("overall_passed")
            ),
            "supports_full_product_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
            "supports_raw_asset_access_claim": False,
            "supports_canonical_graph_write_claim": False,
            "supports_enterprise_latency_scalability_claim": False,
        },
        "total_acceptance": {
            "overall_passed": total_summary.get("overall_passed"),
            "passed_gate_count": total_summary.get("passed_gate_count"),
            "failed_gate_count": total_summary.get("failed_gate_count"),
            "failed_gate_ids": total_summary.get("failed_gate_ids", []),
            "gate_status_sha256": total_summary.get("gate_status_sha256"),
        },
        "objective_audit": {
            "objective_complete": objective.get("objective_complete"),
            "proved_requirement_count": objective.get("proved_requirement_count"),
            "incomplete_requirement_count": objective.get("incomplete_requirement_count"),
            "audit_sha256": objective.get("audit_sha256"),
        },
        "remaining_evidence": {
            "overall_passed": checklist.get("overall_passed"),
            "passed_gate_count": checklist.get("passed_gate_count"),
            "failed_gate_count": checklist.get("failed_gate_count"),
            "remaining_gates": checklist.get("remaining_gates", []),
        },
        "preflight": {
            "state": preflight.get("preflight_state"),
            "blocked_gate_count": preflight_summary.get("blocked_gate_count"),
            "blocked_gate_ids": preflight_summary.get("blocked_gate_ids", []),
            "validator_clear_gate_ids": preflight_summary.get("validator_clear_gate_ids", []),
        },
        "work_orders": {
            "work_order_count": work_order_summary.get("work_order_count"),
            "work_order_gate_ids": work_order_summary.get("work_order_gate_ids", []),
        },
        "progress": {
            "gate_count": progress_summary.get("gate_count"),
            "blocked_gate_ids": progress_summary.get("blocked_gate_ids", []),
            "total_acceptance_state": progress_summary.get("total_acceptance_state"),
        },
        "candidate_generation_capabilities": build_candidate_generation_capability_summary(),
        "kg_benchmark_results": build_benchmark_summary(repository_root=repository_root),
        "integration_boundary": {
            "authoritative_workspace": ".formowl/kg-eval",
            "system_agent_should_call": "formowl-kg-eval summary",
            "system_agent_should_not_import": "repo-local KG eval scripts directly",
            "raw_backend_surfaces_exposed": False,
        },
    }


def _dict_at(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        return {}
    return value


def _redact_local_paths(
    text: str,
    *,
    repository_root: Path,
    workspace: Path,
) -> str:
    if not text:
        return text
    redacted = text
    redacted = redacted.replace(str(workspace), ".formowl/kg-eval")
    redacted = redacted.replace(str(repository_root), "<FORMOWL_REPOSITORY_ROOT>")
    return redacted
