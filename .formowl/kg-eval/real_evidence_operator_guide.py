#!/usr/bin/env python3
"""Generate a human-readable guide for collecting remaining KG evidence.

The guide is derived from ``real_evidence_collection_work_orders.py``. It is
operator guidance only: it does not accept evidence, promote packets, write
canonical inputs, or replace the authoritative validators.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import real_evidence_collection_work_orders as work_orders


ROOT = Path(__file__).resolve().parent
WORK_PACKETS = ROOT / "work_packets"
DEFAULT_OUTPUT_PATH = WORK_PACKETS / "remaining_real_evidence_operator_guide.md"


def _list_lines(items: list[Any], *, indent: str = "- ") -> list[str]:
    return [f"{indent}{item}" for item in items]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _command_block(command: str) -> list[str]:
    return ["```sh", command, "```"]


def _authority_section(report: dict[str, Any]) -> list[str]:
    authority = report.get("work_order_authority", {})
    return [
        "## Authority Boundary",
        "",
        "This guide is not an acceptance artifact. It is generated from the",
        "non-authoritative collection work-order report so an operator can",
        "prepare real evidence without turning templates, fixtures, or",
        "candidate artifacts into broad KG acceptance.",
        "",
        f"- accepts evidence: {bool(authority.get('accepts_evidence'))}",
        f"- promotes evidence: {bool(authority.get('promotes_evidence'))}",
        f"- writes assembly manifests: {bool(authority.get('writes_assembly_manifests'))}",
        f"- writes canonical packets: {bool(authority.get('writes_canonical_packets'))}",
        f"- counts as acceptance gate: {bool(authority.get('counts_as_acceptance_gate'))}",
        "- manual governance approval is still required before any canonical",
        "  input packet can affect acceptance.",
        "",
    ]


def _summary_section(report: dict[str, Any]) -> list[str]:
    summary = report.get("summary", {})
    blocked = _as_list(summary.get("preflight_blocked_gate_ids"))
    lines = [
        "## Current Blocked Gates",
        "",
        f"- work-order state: {report.get('work_order_state', 'unknown')}",
        f"- preflight state: {summary.get('preflight_state', 'unknown')}",
        f"- total acceptance state: {summary.get('total_acceptance_state', 'unknown')}",
        f"- work-order count: {summary.get('work_order_count', 0)}",
        "",
        "Blocked gate ids:",
        "",
    ]
    lines.extend(_list_lines(blocked))
    lines.append("")
    return lines


def _submission_manifest_section() -> list[str]:
    return [
        "## Submission Manifest Preflight",
        "",
        "Before running any candidate-only intake command, fill a copy of the",
        "submission manifest template with the operator response-packet paths,",
        "operator run ids, candidate output dirs, and work-packet manifest",
        "outputs. Put each response packet directly under the matching ignored",
        "`inputs/*_real/<operator_run_id>/operator_response_packet.json` path.",
        "Operator-filled submission manifests and generated candidate manifests",
        "under `work_packets/` are intentionally ignored by Git; keep the",
        "tracked template, preview packets, and this guide as the portable",
        "non-evidence handoff.",
        "The preflight validates path and command contracts only; it does not",
        "read response packet contents, write candidate artifacts, promote",
        "evidence, or write canonical packets.",
        "",
        "Tracked non-evidence template:",
        "",
        "```text",
        "work_packets/remaining_real_evidence_submission_manifest.template.json",
        "```",
        "",
        "Check that the tracked template is current:",
        "",
        "```sh",
        "python3 real_evidence_submission_manifest.py --check-template",
        "```",
        "",
        "Validate the operator-filled submission manifest before intake:",
        "",
        "```sh",
        "python3 real_evidence_submission_manifest.py --manifest "
        "work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json",
        "```",
        "",
    ]


def _response_contract_section(contract: dict[str, Any]) -> list[str]:
    if not contract:
        return []
    lines = [
        "Response intake contract:",
        "",
        f"- response packet type: {contract.get('response_packet_type')}",
        f"- work packet: {contract.get('work_packet_path')}",
        f"- candidate output dir: {contract.get('candidate_output_dir')}",
        f"- candidate manifest output: {contract.get('assembly_manifest_output')}",
        f"- canonical packet not written: {contract.get('canonical_packet_not_written')}",
        f"- writes canonical packet: {bool(contract.get('writes_canonical_packet'))}",
        f"- promotes evidence: {bool(contract.get('promotes_evidence'))}",
        f"- counts as acceptance gate: {bool(contract.get('counts_as_acceptance_gate'))}",
        "",
        "Required intake controls:",
        "",
    ]
    lines.extend(_list_lines(_as_list(contract.get("required_controls"))))
    lines.append("")
    return lines


def _gate_specific_requirements(order: dict[str, Any]) -> list[str]:
    tasks = order.get("operator_tasks", {})
    gate_id = order.get("gate_id")
    lines = ["Required evidence and controls:", ""]

    if gate_id == "fair_external_baseline_comparison":
        source_lock = tasks.get("source_lock", {})
        lines.append(
            f"- required source lock sha256: {source_lock.get('required_source_lock_sha256')}"
        )
        lines.append("- baseline package runs:")
        for row in _as_list(tasks.get("baseline_package_runs")):
            lines.append(f"  - {row.get('baseline_id')}")
            lines.extend(
                f"    - source id: {source_id}"
                for source_id in _as_list(row.get("required_source_ids"))
            )
            lines.extend(
                f"    - artifact field: {field}"
                for field in _as_list(row.get("required_artifact_fields"))
            )
            lines.extend(
                f"    - equalized hash: {field}"
                for field in _as_list(row.get("required_equalized_hashes"))
            )
        lines.append("- human answer adjudication:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("human_answer_adjudication")))
        lines.append("- graph quality validation:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("graph_quality_validation")))
        lines.append("- permission probe evidence:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("permission_probe_evidence")))
    elif gate_id == "annotation_adjudication_protocol":
        lines.append("- required artifacts:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("required_artifacts")))
        lines.append("- human controls:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("human_controls")))
        lines.append("- custody controls:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("custody_controls")))
    elif gate_id == "multimodal_semantic_validation":
        lines.append("- required modalities:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("required_modalities")))
        lines.append("- required artifacts:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("required_artifacts")))
        lines.append("- controls:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("controls")))
    elif gate_id == "production_adapter_paths":
        lines.append("- required components:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("required_components")))
        lines.append("- required artifacts:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("required_artifacts")))
        lines.append("- required audit actions:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("required_audit_actions")))
        lines.append("- controls:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("controls")))
    else:
        lines.append("- no gate-specific requirements were available")

    lines.extend(["", *_response_contract_section(tasks.get("response_packet_contract", {}))])
    return lines


def _commands_section(order: dict[str, Any]) -> list[str]:
    commands = order.get("commands", {})
    seal_commands = [
        value
        for key, value in commands.items()
        if isinstance(value, str) and key.startswith("seal_")
    ]
    lines = [
        "Candidate-only intake command:",
        "",
        "Replace the operator placeholders with real response packet paths and",
        "a unique operator run id. This command writes only candidate artifacts.",
        "",
    ]
    if seal_commands:
        lines.extend(_command_block(seal_commands[0]))
    else:
        lines.append("- no candidate intake command is available")
    scaffold_command = commands.get("generate_non_evidence_assembly_manifest_scaffold")
    if isinstance(scaffold_command, str):
        lines.extend(
            [
                "",
                "Optional non-evidence scaffold command:",
                "",
                "Use this only to inspect the expected assembly-manifest shape.",
                "It is not the candidate manifest emitted by response intake.",
                "",
            ]
        )
        lines.extend(_command_block(scaffold_command))
    candidate_manifest_path = commands.get("candidate_manifest_path")
    if isinstance(candidate_manifest_path, str):
        lines.extend(
            [
                "",
                "Candidate manifest emitted by intake:",
                "",
                "```text",
                candidate_manifest_path,
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "Validation sequence after candidate artifacts exist:",
            "",
        ]
    )
    for key in (
        "validate_candidate_packet",
        "run_gate_validator_after_manual_packet_review",
        "rerun_total_acceptance",
        "rerun_objective_audit",
        "rerun_preflight",
    ):
        command = commands.get(key)
        if isinstance(command, str):
            lines.append(f"{key}:")
            lines.extend(_command_block(command))
            lines.append("")
    followup = commands.get("operator_followup_after_validation")
    if isinstance(followup, str):
        lines.extend(["Manual follow-up:", "", f"- {followup}", ""])
    return lines


def _safety_section(order: dict[str, Any]) -> list[str]:
    safety = order.get("safety", {})
    lines = [
        "Safety rules:",
        "",
        f"- real artifacts must live under: {safety.get('real_artifacts_must_live_under')}",
        "- canonical packet must be created only by the assembler:",
        f"  {safety.get('canonical_packet_must_be_created_only_by_assembler')}",
        f"- assembly manifest must not live under real root: "
        f"{bool(safety.get('assembly_manifest_must_not_live_under_real_artifact_root'))}",
        "- forbidden sources:",
    ]
    lines.extend(f"  - {item}" for item in _as_list(safety.get("forbidden_sources")))
    lines.append("- operator must not claim:")
    lines.extend(f"  - {item}" for item in _as_list(safety.get("operator_must_not_claim")))
    lines.append("")
    return lines


def _work_order_section(order: dict[str, Any]) -> list[str]:
    lines = [
        f"## {order.get('gate_id')}",
        "",
        f"- work order id: {order.get('work_order_id')}",
        f"- requirement id: {order.get('requirement_id')}",
        f"- collection status: {order.get('collection_status')}",
        f"- canonical input packet: {order.get('canonical_input_packet')}",
        f"- required packet artifact id: {order.get('required_packet_artifact_id')}",
        f"- required evidence kind: {order.get('required_evidence_kind')}",
        f"- real artifact root: {order.get('real_artifact_root')}",
        f"- validator module: {order.get('validator_module')}",
        f"- assembler module: {order.get('assembler_module')}",
        "",
        "Current blockers:",
        "",
    ]
    lines.extend(_list_lines(_as_list(order.get("current_blockers"))))
    lines.extend(["", *_gate_specific_requirements(order)])
    lines.extend(_commands_section(order))
    lines.extend(_safety_section(order))
    return lines


def build_guide(report: dict[str, Any] | None = None) -> str:
    report = report if report is not None else work_orders.build_report()
    lines = [
        "# Remaining KG Real-Evidence Operator Guide",
        "",
        f"Source report: `{report.get('artifact_id', 'unknown')}`",
        f"Source report sha256: `{report.get('report_sha256', 'unknown')}`",
        "",
    ]
    lines.extend(_authority_section(report))
    lines.extend(_summary_section(report))
    lines.extend(_submission_manifest_section())
    if report.get("sync", {}).get("status") != "synchronized":
        lines.extend(
            [
                "## Guide Withheld",
                "",
                "The collection work-order report is not synchronized with the",
                "preflight/checklist state. Rerun the KG-eval preflight and work-order",
                "commands before using operator guidance.",
                "",
            ]
        )
    else:
        for order in report.get("work_orders", []):
            if isinstance(order, dict):
                lines.extend(_work_order_section(order))
    lines.extend(
        [
            "## Regeneration",
            "",
            "Regenerate this guide from current work orders with:",
            "",
            "```sh",
            "python3 real_evidence_operator_guide.py",
            "```",
            "",
            "Check whether the tracked guide is current with:",
            "",
            "```sh",
            "python3 real_evidence_operator_guide.py --check",
            "```",
            "",
            "Then rerun the authoritative KG-eval validators. This guide remains",
            "operator guidance only.",
            "",
        ]
    )
    return "\n".join(lines)


def safe_output_path(output: str) -> Path:
    path = (ROOT / output).resolve()
    work_packets_root = WORK_PACKETS.resolve()
    try:
        path.relative_to(work_packets_root)
    except ValueError as exc:
        raise ValueError("operator guide output must stay under work_packets/") from exc
    if path.suffix != ".md":
        raise ValueError("operator guide output must be a markdown file")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH.relative_to(ROOT)),
        help="work_packets-relative markdown output path",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if the generated guide differs from the output file",
    )
    args = parser.parse_args(argv)
    output_path = safe_output_path(args.output)
    guide = build_guide()
    status = {
        "artifact_id": "kg_real_evidence_operator_guide_v1",
        "output": str(output_path.relative_to(ROOT)),
        "authority": {
            "accepts_evidence": False,
            "promotes_evidence": False,
            "writes_canonical_packets": False,
            "counts_as_acceptance_gate": False,
        },
    }
    if args.check:
        current = output_path.read_text(encoding="utf-8") if output_path.exists() else None
        status["check"] = {
            "mode": "check",
            "exists": output_path.exists(),
            "up_to_date": current == guide,
        }
        print(json.dumps(status, indent=2, sort_keys=True))
        if current != guide:
            print("operator guide is stale; rerun real_evidence_operator_guide.py", file=sys.stderr)
            return 1
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(guide, encoding="utf-8")
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
