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
import real_evidence_response_packet_templates as response_templates


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


def _progress_report_section() -> list[str]:
    return [
        "## Gate Progress Report",
        "",
        "Use the progress report when you need a compact machine-readable",
        "summary of the current remaining gate stages before or after candidate",
        "intake. It reads persisted preflight/work-order reports plus safe",
        "work-packet surfaces, but it does not refresh preflight, read",
        "operator response packets, read candidate artifact contents, write",
        "candidate artifacts, promote evidence, write canonical packets, or",
        "count as an acceptance gate.",
        "",
        "Refresh the progress report:",
        "",
        "```sh",
        "python3 real_evidence_gate_progress.py",
        "```",
        "",
        "Check whether the persisted progress report is current:",
        "",
        "```sh",
        "python3 real_evidence_gate_progress.py --check",
        "```",
        "",
        "The report stages are status labels only:",
        "",
        "- `missing_operator_response`",
        "- `candidate_artifacts_present_without_manifest`",
        "- `candidate_manifest_present_pending_validation`",
        "- `candidate_validation_failed_or_stale`",
        "- `candidate_validation_clear_pending_approval`",
        "- `approval_valid_pending_promotion`",
        "- `canonical_packet_present_needs_validator_clear`",
        "- `canonical_packet_validator_clear`",
        "",
        "A gate still requires a",
        "validator-accepted canonical packet and the total acceptance suite",
        "before it can count as completed.",
        "",
    ]


def _submission_manifest_section() -> list[str]:
    template_paths = [
        str(path.relative_to(ROOT)) for path in response_templates.TEMPLATE_PATHS.values()
    ]
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
        "Tracked non-evidence response packet templates:",
        "",
        "```text",
        *template_paths,
        "```",
        "",
        "Check that the tracked response packet templates are current:",
        "",
        "```sh",
        "python3 real_evidence_response_packet_templates.py --check-templates",
        "```",
        "",
        "Use these only as starting points. Copy a template to the matching",
        "`inputs/*_real/<operator_run_id>/operator_response_packet.json` path,",
        "replace every `OPERATOR_*` placeholder with real reviewed values, and",
        "remove `template_only`, `do_not_submit_as_evidence`, `gate_id`,",
        "`claim_boundary`, and `operator_instructions` before candidate intake.",
        "The templates are deliberately rejected by response-intake helpers as-is.",
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
        "Do not pass generated `*_candidate_manifest.json` files or intake-plan",
        "JSON files back into `--manifest`; those are downstream non-evidence",
        "outputs, not operator-filled submission manifests.",
        "Do not hardlink operator-filled manifests or response packets to",
        "templates, fixtures, canonical packets, generated candidate manifests,",
        "or other files. The preflight rejects hardlink aliases.",
        "",
        "Optionally emit a non-evidence intake execution plan from the validated manifest:",
        "",
        "```sh",
        "python3 real_evidence_submission_manifest.py --manifest "
        "work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json "
        "--emit-intake-plan work_packets/OPERATOR_INTAKE_PLAN.json",
        "```",
        "",
        "The intake plan is ignored by Git and does not execute commands. Review it before",
        "running any listed response preflight or candidate-only intake command.",
        "It lists paired response-preflight commands and candidate-only intake",
        "commands for the same operator response packet paths and output dirs.",
        "",
        "Before executing candidate-only intake, run each gate-specific",
        "`--preflight-response` command in this guide against the exact",
        "operator response packet and output surface. Response preflight reads",
        "the response packet contents, validates the intake contract and planned",
        "artifact surface, writes no candidate artifacts, writes no candidate",
        "manifest, never passes a promotion flag, never writes canonical input",
        "packets, and still does not count as an acceptance gate.",
        "",
        "The validated submission manifest can also run the four response",
        "preflight commands through one controlled non-evidence runner:",
        "",
        "```sh",
        "python3 real_evidence_submission_manifest.py --manifest "
        "work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json "
        "--preflight-responses",
        "```",
        "",
        "This response-preflight runner reads operator response-packet",
        "contents through the existing intake preflight helpers, writes no",
        "candidate artifacts, writes no candidate manifest, never passes a",
        "promotion flag, never writes canonical input packets, and still does",
        "not count as an acceptance gate. It stops on the first failed response",
        "preflight and fails closed if a preflight helper leaves a final-state",
        "candidate output surface or canonical packet surface changed.",
        "",
        "After reviewing the validated manifest and optional plan, the same manifest",
        "can execute the four candidate-only intake commands through the controlled",
        "runner:",
        "",
        "```sh",
        "python3 real_evidence_submission_manifest.py --manifest "
        "work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json "
        "--execute-candidate-intakes",
        "```",
        "",
        "This execution mode reads operator response-packet contents and writes",
        "candidate artifacts plus generated candidate manifests only. It stops on",
        "the first failed intake, never passes a promotion flag, never writes canonical",
        "input packets, and still does not count as an acceptance gate. Candidate",
        "artifacts from earlier successful intake commands remain for operator",
        "review and are not automatically promoted or rolled back by this runner.",
        "The runner snapshots canonical input packet state and fails closed if",
        "any candidate-only helper exits with a canonical packet path created",
        "or changed. It also refuses to launch subprocesses when a canonical",
        "input packet path is already a symlink, hardlink alias, non-regular",
        "file, or unreadable surface.",
        "",
        "After candidate manifests exist, validate them through the controlled",
        "validate-only runner:",
        "",
        "```sh",
        "python3 real_evidence_submission_manifest.py --manifest "
        "work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json "
        "--validate-candidate-manifests",
        "```",
        "",
        "This validation mode reads emitted candidate manifests and their referenced",
        "candidate artifacts through the existing assembler `--validate` commands.",
        "It runs no response intake commands, writes no candidate artifacts, never",
        "passes a promotion flag, never writes canonical input packets, and still",
        "does not count as an acceptance gate.",
        "The validate-only runner also fails closed if any assembler exits with",
        "a canonical packet path created or changed. It refuses to launch",
        "assembler subprocesses while any canonical input packet path is already",
        "a symlink, hardlink alias, non-regular file, or unreadable surface.",
        "",
        "Optionally persist that validate-only result as an ignored non-evidence",
        "report for manual governance review:",
        "",
        "```sh",
        "python3 real_evidence_submission_manifest.py --manifest "
        "work_packets/OPERATOR_FILLED_SUBMISSION_MANIFEST.json "
        "--validate-candidate-manifests "
        "--emit-candidate-validation-report "
        "work_packets/OPERATOR_CANDIDATE_VALIDATION_REPORT_candidate_validation_report.json",
        "```",
        "",
        "The persisted validation report is not evidence and does not authorize",
        "promotion by itself. It is a review aid that records the validate-only",
        "assembler result without writing canonical input packets.",
        "",
        "After manual governance review, fill an operator approval manifest",
        "from the tracked non-evidence approval template. The approval manifest",
        "must bind the candidate validation report hash, candidate manifest",
        "hash, selected gate id, canonical packet target, and governance",
        "approval controls.",
        "",
        "Check that the tracked governance approval template is current:",
        "",
        "```sh",
        "python3 real_evidence_governance_approval.py --check-template",
        "```",
        "",
        "Tracked non-evidence approval template:",
        "",
        "```text",
        "work_packets/remaining_real_evidence_governance_approval.template.json",
        "```",
        "",
        "Validate the operator-filled approval manifest before any canonical",
        "packet update:",
        "",
        "```sh",
        "python3 real_evidence_governance_approval.py --approval-manifest "
        "work_packets/OPERATOR_GOVERNANCE_APPROVAL.json",
        "```",
        "",
        "Only after that validation passes, the same approval manifest can execute",
        "the approved canonical packet update through the governance runner:",
        "",
        "```sh",
        "python3 real_evidence_governance_approval.py --approval-manifest "
        "work_packets/OPERATOR_GOVERNANCE_APPROVAL.json "
        "--execute-approved-promotion",
        "```",
        "",
        "The approval manifest remains non-evidence and does not count as an",
        "acceptance gate. The governance runner refuses stale hashes, unsupported",
        "approvers, pre-existing canonical packet targets, canonical packet path",
        "hazards, and validation reports that do not have a passing target gate",
        "row. During execution, the runner passes the approved candidate",
        "manifest hash to the assembler so the manifest bytes consumed for",
        "promotion are bound to the governance approval. If execution fails",
        "after creating the target canonical packet, the runner removes that",
        "newly created target packet before reporting failure. After any successful",
        "canonical packet update, rerun the specific broad validator and the",
        "total acceptance reports.",
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
        lines.append("- answer-quality adjudication:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("answer_quality_adjudication")))
        lines.append("- graph quality validation:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("graph_quality_validation")))
        lines.append("- permission probe evidence:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("permission_probe_evidence")))
    elif gate_id == "annotation_adjudication_protocol":
        lines.append("- required artifacts:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("required_artifacts")))
        lines.append("- adjudication controls:")
        lines.extend(f"  - {item}" for item in _as_list(tasks.get("adjudication_controls")))
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
    preflight_commands = [
        value
        for key, value in commands.items()
        if isinstance(value, str) and key.startswith("preflight_")
    ]
    seal_commands = [
        value
        for key, value in commands.items()
        if isinstance(value, str) and key.startswith("seal_")
    ]
    lines = [
        "Response packet preflight command:",
        "",
        "Run this first with the final operator response packet and output",
        "surface. It writes no candidate artifacts, no candidate manifest, and",
        "no canonical packet.",
        "",
    ]
    if preflight_commands:
        lines.extend(_command_block(preflight_commands[0]))
    else:
        lines.append("- no response preflight command is available")
    lines.extend(
        [
            "",
            "Candidate-only intake command:",
            "",
            "Replace the operator placeholders with real response packet paths and",
            "a unique operator run id. This command writes only candidate artifacts.",
            "",
        ]
    )
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
    lines.append("- accepted evidence source modes:")
    lines.extend(f"  - {item}" for item in _as_list(safety.get("accepted_evidence_source_modes")))
    lines.append("- public reproducible mode requirements:")
    lines.extend(
        f"  - {item}" for item in _as_list(safety.get("public_reproducible_mode_requirements"))
    )
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
    lines.extend(_progress_report_section())
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
