#!/usr/bin/env python3
"""Validate and execute governed real-evidence canonical packet promotion.

This helper bridges a validate-only candidate report to a canonical input
packet update only after an operator supplies an explicit governance approval
manifest. The approval manifest is not evidence, and this helper is not an
acceptance gate. Authoritative broad validators must still pass after any
canonical packet is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import real_evidence_submission_manifest as submission_manifest


ROOT = Path(__file__).resolve().parent
WORK_PACKETS = ROOT / "work_packets"
MANIFEST_TYPE = "kg_real_evidence_governance_approval_v1"
DEFAULT_TEMPLATE_OUTPUT = WORK_PACKETS / "remaining_real_evidence_governance_approval.template.json"
SAFE_APPROVER_RE = re.compile(r"^human:[A-Za-z0-9][A-Za-z0-9_.@-]{1,96}$")
TIMESTAMP_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

APPROVAL_SCOPE = {
    "reviewed_candidate_validation_report": True,
    "reviewed_candidate_manifest": True,
    "reviewed_real_artifacts": True,
    "confirmed_no_templates_fixtures_or_sandbox_artifacts": True,
    "confirmed_no_raw_internal_paths": True,
    "confirmed_candidate_only_boundary": True,
    "confirmed_authoritative_validator_required_after_promotion": True,
}
CLAIM_BOUNDARY = {
    "approval_manifest_is_evidence": False,
    "candidate_validation_report_is_evidence": False,
    "execute_mode_promotes_canonical_packet": True,
    "execute_mode_writes_canonical_packet": True,
    "execute_mode_counts_as_acceptance_gate": False,
    "authoritative_validators_required_after_promotion": True,
}
APPROVAL_ALLOWED_FIELDS = {
    "manifest_type",
    "gate_id",
    "candidate_validation_report",
    "candidate_validation_report_sha256",
    "candidate_manifest",
    "candidate_manifest_sha256",
    "canonical_packet",
    "approved_by",
    "approval_timestamp_utc",
    "manual_governance_review_completed",
    "target_candidate_validation_passed",
    "canonical_packet_update_approved",
    "approval_scope",
    "claim_boundary",
}


class ApprovalError(ValueError):
    """Raised when a governance approval manifest is malformed."""


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ApprovalError(f"{label} JSON must be an object")
    return loaded


def _expected_for_gate(gate_id: object) -> submission_manifest.ExpectedSubmission | None:
    if not isinstance(gate_id, str):
        return None
    return submission_manifest.EXPECTED_BY_GATE.get(gate_id)


def _strong_sha(value: object, field_name: str) -> list[str]:
    if not isinstance(value, str) or not SHA256_RE.match(value):
        return [f"{field_name} must be a lowercase 64-hex sha256"]
    return []


def _safe_work_packet_existing(
    path_value: object, field_name: str
) -> tuple[Path | None, list[str]]:
    path, blockers = submission_manifest._safe_work_packets_path(path_value, field_name)
    if path is None:
        return None, blockers
    blockers.extend(submission_manifest._existing_regular_file_blockers(path, field_name))
    return (ROOT / path), blockers


def safe_template_output(path_value: str) -> Path:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ApprovalError("approval template output must be a non-empty string")
    path = Path(path_value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise ApprovalError("approval template output must be a safe repo-relative path")
    if path != DEFAULT_TEMPLATE_OUTPUT.relative_to(ROOT):
        raise ApprovalError(
            "approval template output must be the tracked governance approval template path"
        )
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(WORK_PACKETS.resolve())
    except ValueError as exc:
        raise ApprovalError("approval template output escapes work_packets/") from exc
    return resolved


def safe_approval_manifest_input(path_value: object) -> Path:
    path, blockers = submission_manifest._safe_work_packets_path(
        path_value,
        "approval manifest input",
    )
    if path is None:
        raise ApprovalError("; ".join(blockers))
    lowered = path.name.lower()
    if path.suffix != ".json":
        blockers.append("approval manifest input must be a JSON file")
    if path == DEFAULT_TEMPLATE_OUTPUT.relative_to(ROOT) or lowered.endswith(".template.json"):
        blockers.append("approval manifest input must be operator-filled, not a template")
    if lowered.endswith("_candidate_manifest.json"):
        blockers.append("approval manifest input must not be a candidate manifest")
    if lowered.endswith("_candidate_validation_report.json"):
        blockers.append("approval manifest input must not be a candidate validation report")
    if lowered.endswith("_intake_plan.json"):
        blockers.append("approval manifest input must not be an intake plan")
    blockers.extend(
        submission_manifest._existing_regular_file_blockers(path, "approval manifest input")
    )
    if blockers:
        raise ApprovalError("; ".join(blockers))
    return ROOT / path


def build_template() -> dict[str, Any]:
    return {
        "manifest_type": MANIFEST_TYPE,
        "template_only": True,
        "do_not_submit_as_evidence": True,
        "gate_id": "annotation_adjudication_protocol",
        "candidate_validation_report": ("work_packets/OPERATOR_candidate_validation_report.json"),
        "candidate_validation_report_sha256": "fill-with-64-hex-report-sha256",
        "candidate_manifest": (
            "work_packets/annotation_adjudication_protocol_candidate_manifest.json"
        ),
        "candidate_manifest_sha256": "fill-with-64-hex-candidate-manifest-sha256",
        "canonical_packet": "inputs/human_annotation_results_v1.json",
        "approved_by": "human:REVIEWER_ID",
        "approval_timestamp_utc": "YYYY-MM-DDTHH:MM:SSZ",
        "manual_governance_review_completed": True,
        "target_candidate_validation_passed": True,
        "canonical_packet_update_approved": True,
        "approval_scope": dict(APPROVAL_SCOPE),
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }


def _validate_claim_boundary(approval: dict[str, Any], blockers: list[str]) -> None:
    boundary = approval.get("claim_boundary")
    if boundary != CLAIM_BOUNDARY:
        blockers.append("claim_boundary must exactly match the governance approval boundary")


def _validate_approval_scope(approval: dict[str, Any], blockers: list[str]) -> None:
    scope = approval.get("approval_scope")
    if scope != APPROVAL_SCOPE:
        blockers.append("approval_scope must exactly confirm every governance review control")


def _validation_row_for_gate(
    report: dict[str, Any],
    gate_id: str,
) -> dict[str, Any] | None:
    rows = report.get("validation_results")
    if not isinstance(rows, list):
        return None
    matches = [row for row in rows if isinstance(row, dict) and row.get("gate_id") == gate_id]
    if len(matches) != 1:
        return None
    return matches[0]


def _validate_candidate_report(
    approval: dict[str, Any],
    expected: submission_manifest.ExpectedSubmission,
    blockers: list[str],
) -> dict[str, Any] | None:
    report_path, report_path_blockers = _safe_work_packet_existing(
        approval.get("candidate_validation_report"),
        "candidate_validation_report",
    )
    blockers.extend(report_path_blockers)
    blockers.extend(
        _strong_sha(
            approval.get("candidate_validation_report_sha256"),
            "candidate_validation_report_sha256",
        )
    )
    if report_path is None or report_path_blockers:
        return None
    if not report_path.name.endswith("_candidate_validation_report.json"):
        blockers.append(
            "candidate_validation_report must use *_candidate_validation_report.json naming"
        )
    report_sha = _sha256_file(report_path)
    if approval.get("candidate_validation_report_sha256") != report_sha:
        blockers.append("candidate_validation_report_sha256 does not match current file")
    report = _load_json_object(report_path, "candidate validation report")
    if report.get("artifact_id") != "kg_real_evidence_candidate_manifest_validation_v1":
        blockers.append("candidate validation report artifact_id mismatch")
    if report.get("valid_manifest") is not True:
        blockers.append("candidate validation report did not validate its submission manifest")
    if report.get("candidate_manifest_preflight_passed") is not True:
        blockers.append("candidate validation report preflight did not pass")
    authority = report.get("authority")
    if not isinstance(authority, dict):
        blockers.append("candidate validation report authority missing")
    else:
        expected_false = {
            "accepts_evidence",
            "promotes_evidence",
            "writes_candidate_artifacts",
            "writes_canonical_packets",
            "counts_as_acceptance_gate",
        }
        for field in expected_false:
            if authority.get(field) is not False:
                blockers.append(f"candidate validation report authority.{field} must be False")
    row = _validation_row_for_gate(report, expected.gate_id)
    if row is None:
        blockers.append("candidate validation report must contain exactly one target gate row")
        return report
    if row.get("status") != "passed":
        blockers.append("target candidate validation row did not pass")
    if row.get("candidate_manifest") != expected.assembly_manifest_output:
        blockers.append("candidate validation report target candidate manifest mismatch")
    if row.get("candidate_manifest_sha256") != approval.get("candidate_manifest_sha256"):
        blockers.append("candidate validation report candidate manifest hash mismatch")
    if row.get("assembler_script") != expected.assembler_script:
        blockers.append("candidate validation report assembler script mismatch")
    if row.get("canonical_packet_not_written") != expected.canonical_packet:
        blockers.append("candidate validation report canonical packet target mismatch")
    stdout_summary = row.get("stdout_summary")
    if not isinstance(stdout_summary, dict) or stdout_summary.get("passed") is not True:
        blockers.append("candidate validation report stdout summary did not pass")
    canonical_integrity = row.get("canonical_packet_integrity")
    if not isinstance(canonical_integrity, dict) or canonical_integrity.get("passed") is not True:
        blockers.append("candidate validation row reported canonical packet drift")
    expected_argv = [
        "python3",
        expected.assembler_script,
        "--assembly-manifest",
        expected.assembly_manifest_output,
        "--validate",
    ]
    if row.get("argv") != expected_argv:
        blockers.append("candidate validation report target row argv is not validate-only")
    return report


def _validate_canonical_surface(
    expected: submission_manifest.ExpectedSubmission,
    blockers: list[str],
) -> dict[str, Any]:
    snapshot = submission_manifest._canonical_packet_snapshot()
    baseline = submission_manifest._canonical_packet_baseline_hazards(snapshot)
    if not baseline["passed"]:
        blockers.extend(submission_manifest._canonical_packet_baseline_blockers(baseline))
    target = snapshot.get(expected.canonical_packet)
    if not isinstance(target, dict) or target.get("state") != "missing":
        blockers.append("canonical packet target must be missing before approved promotion")
    return {
        "snapshot": snapshot,
        "baseline": baseline,
        "target": target,
    }


def validate_approval_manifest(
    approval: dict[str, Any],
    *,
    manifest_path: Path,
) -> dict[str, Any]:
    blockers: list[str] = []
    unsupported = sorted(set(approval) - APPROVAL_ALLOWED_FIELDS)
    if unsupported:
        blockers.append("unsupported approval fields: " + ", ".join(unsupported))
    missing = sorted(APPROVAL_ALLOWED_FIELDS - set(approval))
    if missing:
        blockers.append("missing approval fields: " + ", ".join(missing))
    if approval.get("manifest_type") != MANIFEST_TYPE:
        blockers.append("manifest_type mismatch")
    expected = _expected_for_gate(approval.get("gate_id"))
    if expected is None:
        blockers.append("gate_id must be one remaining KG real-evidence gate")
    if not isinstance(approval.get("approved_by"), str) or not SAFE_APPROVER_RE.match(
        approval.get("approved_by", "")
    ):
        blockers.append("approved_by must identify a human reviewer as human:<id>")
    approver_lower = (
        approval["approved_by"].lower() if isinstance(approval.get("approved_by"), str) else ""
    )
    if any(marker in approver_lower for marker in ("agent", "llm", "template", "synthetic")):
        blockers.append("approved_by must not be an agent, LLM, template, or synthetic actor")
    if not isinstance(approval.get("approval_timestamp_utc"), str) or not TIMESTAMP_UTC_RE.match(
        approval.get("approval_timestamp_utc", "")
    ):
        blockers.append("approval_timestamp_utc must use YYYY-MM-DDTHH:MM:SSZ")
    for field in (
        "manual_governance_review_completed",
        "target_candidate_validation_passed",
        "canonical_packet_update_approved",
    ):
        if approval.get(field) is not True:
            blockers.append(f"{field} must be true")
    _validate_claim_boundary(approval, blockers)
    _validate_approval_scope(approval, blockers)
    target_surface: dict[str, Any] | None = None
    if expected is not None:
        if approval.get("candidate_manifest") != expected.assembly_manifest_output:
            blockers.append("candidate_manifest must match the selected gate")
        if approval.get("canonical_packet") != expected.canonical_packet:
            blockers.append("canonical_packet must match the selected gate")
        candidate_path, candidate_blockers = _safe_work_packet_existing(
            approval.get("candidate_manifest"),
            "candidate_manifest",
        )
        blockers.extend(candidate_blockers)
        blockers.extend(
            _strong_sha(approval.get("candidate_manifest_sha256"), "candidate_manifest_sha256")
        )
        if candidate_path is not None and not candidate_blockers:
            if not candidate_path.name.endswith("_candidate_manifest.json"):
                blockers.append("candidate_manifest must use *_candidate_manifest.json naming")
            candidate_sha = _sha256_file(candidate_path)
            if approval.get("candidate_manifest_sha256") != candidate_sha:
                blockers.append("candidate_manifest_sha256 does not match current file")
        _validate_candidate_report(approval, expected, blockers)
        target_surface = _validate_canonical_surface(expected, blockers)
    promotion_target = None
    if expected is not None:
        promotion_target = {
            "gate_id": expected.gate_id,
            "candidate_manifest": expected.assembly_manifest_output,
            "candidate_manifest_sha256": approval.get("candidate_manifest_sha256"),
            "candidate_validation_report": approval.get("candidate_validation_report"),
            "candidate_validation_report_sha256": approval.get(
                "candidate_validation_report_sha256"
            ),
            "canonical_packet": expected.canonical_packet,
            "assembler_script": expected.assembler_script,
        }
    return {
        "artifact_id": "kg_real_evidence_governance_approval_validation_v1",
        "manifest": str(manifest_path.relative_to(ROOT)),
        "manifest_type": MANIFEST_TYPE,
        "gate_id": approval.get("gate_id"),
        "valid": not blockers,
        "blockers": blockers,
        "promotion_target": promotion_target,
        "canonical_packet_baseline": target_surface["baseline"] if target_surface else None,
        "authority": {
            "approval_manifest_is_evidence": False,
            "writes_canonical_packets": False,
            "promotes_evidence": False,
            "counts_as_acceptance_gate": False,
            "requires_authoritative_validator_after_promotion": True,
        },
        "next_step": (
            "after validation, run this helper in execute-approved-promotion mode; "
            "then run the specific broad validator and total acceptance suite"
        ),
    }


def _promotion_integrity(
    before: dict[str, dict[str, Any]],
    *,
    target_packet: str,
) -> dict[str, Any]:
    blockers: list[str] = []
    changed_packets: list[dict[str, Any]] = []
    target_after: dict[str, Any] | None = None
    for packet_path in sorted(submission_manifest.CANONICAL_INPUT_PACKETS):
        before_surface = before.get(packet_path)
        after_surface = submission_manifest._canonical_packet_surface(packet_path)
        if packet_path == target_packet:
            target_after = after_surface
            if before_surface != {"state": "missing", "sha256": None, "hardlink_alias": False}:
                blockers.append("target canonical packet was not missing before promotion")
            if after_surface.get("state") != "regular":
                blockers.append("target canonical packet was not written as a regular file")
            if after_surface.get("hardlink_alias") is True:
                blockers.append("target canonical packet has hardlink aliases after promotion")
            if before_surface != after_surface:
                changed_packets.append(
                    {
                        "packet": packet_path,
                        "before": before_surface,
                        "after": after_surface,
                    }
                )
        elif before_surface != after_surface:
            blockers.append(f"non-target canonical packet changed: {packet_path}")
            changed_packets.append(
                {
                    "packet": packet_path,
                    "before": before_surface,
                    "after": after_surface,
                }
            )
    return {
        "passed": not blockers,
        "blockers": blockers,
        "changed_packet_count": len(changed_packets),
        "changed_packets": changed_packets,
        "target_packet": target_packet,
        "target_after": target_after,
    }


def _candidate_manifest_hash_integrity(
    expected: submission_manifest.ExpectedSubmission,
    approved_sha256: object,
) -> dict[str, Any]:
    candidate_path = ROOT / expected.assembly_manifest_output
    blockers: list[str] = []
    current_sha: str | None = None
    try:
        current_sha = _sha256_file(candidate_path)
    except FileNotFoundError:
        blockers.append("candidate manifest disappeared during promotion")
    except OSError:
        blockers.append("candidate manifest could not be inspected after promotion")
    if current_sha is not None and current_sha != approved_sha256:
        blockers.append("candidate manifest hash changed during promotion")
    return {
        "passed": not blockers,
        "expected_sha256": approved_sha256,
        "current_sha256": current_sha,
        "blockers": blockers,
    }


def _rollback_target_packet_created_by_promotion(
    before: dict[str, dict[str, Any]],
    *,
    target_packet: str,
) -> dict[str, Any]:
    before_surface = before.get(target_packet)
    after_surface = submission_manifest._canonical_packet_surface(target_packet)
    if before_surface != {"state": "missing", "sha256": None, "hardlink_alias": False}:
        return {
            "attempted": False,
            "removed": False,
            "reason": "target canonical packet was not missing before promotion",
        }
    if after_surface.get("state") not in {"regular", "symlink", "hardlink_alias"}:
        return {
            "attempted": False,
            "removed": False,
            "reason": f"target canonical packet has unsafe state: {after_surface.get('state')}",
        }
    path = ROOT / target_packet
    try:
        path.unlink()
    except OSError as exc:
        return {
            "attempted": True,
            "removed": False,
            "reason": str(exc),
        }
    return {
        "attempted": True,
        "removed": True,
        "reason": None,
    }


def _target_packet_created_by_promotion(
    before: dict[str, dict[str, Any]],
    *,
    target_packet: str,
) -> bool:
    before_surface = before.get(target_packet)
    after_surface = submission_manifest._canonical_packet_surface(target_packet)
    return before_surface == {
        "state": "missing",
        "sha256": None,
        "hardlink_alias": False,
    } and after_surface.get("state") in {"regular", "symlink", "hardlink_alias"}


def _promotion_stdout_summary(stdout: str) -> dict[str, Any]:
    try:
        loaded = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "json_stdout": False,
            "stdout_line_count": len([line for line in stdout.splitlines() if line.strip()]),
        }
    if not isinstance(loaded, dict):
        return {"json_stdout": True, "stdout_type": type(loaded).__name__}
    report = loaded.get("validation_report")
    if not isinstance(report, dict):
        return {
            "json_stdout": True,
            "validation_report_present": False,
            "packet_present": isinstance(loaded.get("packet"), dict),
        }
    blockers = report.get("blockers")
    return {
        "json_stdout": True,
        "validation_report_present": True,
        "packet_present": isinstance(loaded.get("packet"), dict),
        "artifact_id": report.get("artifact_id"),
        "passed": report.get("passed"),
        "blocker_count": len(blockers) if isinstance(blockers, list) else None,
    }


def execute_approved_promotion(
    approval: dict[str, Any],
    *,
    manifest_path: Path,
) -> dict[str, Any]:
    validation = validate_approval_manifest(approval, manifest_path=manifest_path)
    if not validation["valid"]:
        return {
            "artifact_id": "kg_real_evidence_governance_promotion_execution_v1",
            "manifest": str(manifest_path.relative_to(ROOT)),
            "gate_id": approval.get("gate_id"),
            "overall_success": False,
            "approval_validation": validation,
            "executed": False,
            "authority": {
                "approval_manifest_is_evidence": False,
                "writes_canonical_packets": False,
                "promotes_evidence": False,
                "counts_as_acceptance_gate": False,
                "requires_authoritative_validator_after_promotion": True,
            },
            "execution_result": None,
        }
    target = validation["promotion_target"]
    assert isinstance(target, dict)
    before = submission_manifest._canonical_packet_snapshot()
    expected = submission_manifest.EXPECTED_BY_GATE[target["gate_id"]]
    approved_candidate_manifest_sha256 = target["candidate_manifest_sha256"]
    assert isinstance(approved_candidate_manifest_sha256, str)
    argv = [
        "python3",
        expected.assembler_script,
        "--assembly-manifest",
        expected.assembly_manifest_output,
        "--assembly-manifest-sha256",
        approved_candidate_manifest_sha256,
        "--promote",
    ]
    subprocess_error = None
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        completed = None
        subprocess_error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    integrity = _promotion_integrity(before, target_packet=expected.canonical_packet)
    candidate_manifest_integrity = _candidate_manifest_hash_integrity(
        expected,
        target["candidate_manifest_sha256"],
    )
    rollback_after_candidate_manifest_drift = None
    rollback_after_failed_promotion = None
    if not candidate_manifest_integrity["passed"]:
        rollback_after_candidate_manifest_drift = _rollback_target_packet_created_by_promotion(
            before,
            target_packet=expected.canonical_packet,
        )
        integrity = _promotion_integrity(before, target_packet=expected.canonical_packet)
    stdout_summary = (
        _promotion_stdout_summary(completed.stdout)
        if completed is not None
        else {
            "json_stdout": False,
            "validation_report_present": False,
            "packet_present": False,
            "subprocess_error": subprocess_error,
        }
    )
    success = (
        completed is not None
        and completed.returncode == 0
        and stdout_summary.get("passed") is True
        and candidate_manifest_integrity["passed"]
        and integrity["passed"]
    )
    if (
        not success
        and candidate_manifest_integrity["passed"]
        and _target_packet_created_by_promotion(before, target_packet=expected.canonical_packet)
    ):
        rollback_after_failed_promotion = _rollback_target_packet_created_by_promotion(
            before,
            target_packet=expected.canonical_packet,
        )
        integrity = _promotion_integrity(before, target_packet=expected.canonical_packet)
    return {
        "artifact_id": "kg_real_evidence_governance_promotion_execution_v1",
        "manifest": str(manifest_path.relative_to(ROOT)),
        "gate_id": expected.gate_id,
        "overall_success": success,
        "approval_validation": validation,
        "executed": True,
        "authority": {
            "approval_manifest_is_evidence": False,
            "writes_canonical_packets": True,
            "promotes_evidence": True,
            "counts_as_acceptance_gate": False,
            "requires_authoritative_validator_after_promotion": True,
        },
        "execution_effects": {
            "reads_candidate_manifest_contents": True,
            "reads_candidate_artifacts": True,
            "writes_canonical_packets": True,
            "counts_as_acceptance_gate": False,
        },
        "execution_result": {
            "assembler_script": expected.assembler_script,
            "candidate_manifest": expected.assembly_manifest_output,
            "candidate_manifest_sha256": approved_candidate_manifest_sha256,
            "canonical_packet": expected.canonical_packet,
            "exit_code": completed.returncode if completed is not None else None,
            "subprocess_error": subprocess_error,
            "status": "succeeded" if success else "failed",
            "stdout_summary": stdout_summary,
            "stderr_line_count": len(
                [line for line in completed.stderr.splitlines() if line.strip()]
            )
            if completed is not None
            else 0,
            "candidate_manifest_integrity": candidate_manifest_integrity,
            "canonical_packet_promotion_integrity": integrity,
            "rollback_after_candidate_manifest_drift": rollback_after_candidate_manifest_drift,
            "rollback_after_failed_promotion": rollback_after_failed_promotion,
        },
        "next_step": (
            "run the specific broad validator, then kg_total_acceptance_suite.py, "
            "kg_objective_completion_audit.py, real_evidence_preflight.py, and "
            "real_evidence_collection_work_orders.py"
        ),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--approval-manifest",
        help="operator-filled governance approval manifest under work_packets/",
    )
    parser.add_argument(
        "--execute-approved-promotion",
        action="store_true",
        help=(
            "execute the approved canonical packet update after validation; "
            "the approval manifest itself remains non-evidence"
        ),
    )
    parser.add_argument(
        "--emit-template",
        action="store_true",
        help="write the tracked non-evidence governance approval template",
    )
    parser.add_argument(
        "--check-template",
        action="store_true",
        help="exit nonzero if the tracked governance approval template is stale",
    )
    parser.add_argument(
        "--template-output",
        default=str(DEFAULT_TEMPLATE_OUTPUT.relative_to(ROOT)),
        help="tracked governance approval template output path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    template_output = safe_template_output(args.template_output)
    template = build_template()
    if args.emit_template:
        template_output.parent.mkdir(parents=True, exist_ok=True)
        template_output.write_text(_json_text(template), encoding="utf-8")
        print(
            json.dumps(
                {
                    "artifact_id": "kg_real_evidence_governance_approval_template_v1",
                    "output": str(template_output.relative_to(ROOT)),
                    "authority": {
                        "approval_manifest_is_evidence": False,
                        "writes_canonical_packets": False,
                        "counts_as_acceptance_gate": False,
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.check_template:
        current = template_output.read_text(encoding="utf-8") if template_output.exists() else None
        up_to_date = current == _json_text(template)
        print(
            json.dumps(
                {
                    "artifact_id": "kg_real_evidence_governance_approval_template_check_v1",
                    "output": str(template_output.relative_to(ROOT)),
                    "exists": template_output.exists(),
                    "up_to_date": up_to_date,
                },
                indent=2,
                sort_keys=True,
            )
        )
        if not up_to_date:
            print(
                "governance approval template is stale; rerun "
                "real_evidence_governance_approval.py --emit-template",
                file=sys.stderr,
            )
            return 1
        return 0
    if not args.approval_manifest:
        raise ApprovalError(
            "either --approval-manifest, --emit-template, or --check-template is required"
        )
    manifest_path = safe_approval_manifest_input(args.approval_manifest)
    approval = _load_json_object(manifest_path, "approval manifest")
    if args.execute_approved_promotion:
        execution = execute_approved_promotion(approval, manifest_path=manifest_path)
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0 if execution["overall_success"] else 1
    validation = validate_approval_manifest(approval, manifest_path=manifest_path)
    print(json.dumps(validation, indent=2, sort_keys=True))
    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApprovalError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
