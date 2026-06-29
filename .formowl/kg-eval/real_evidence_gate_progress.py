#!/usr/bin/env python3
"""Summarize remaining real-evidence gate progress without accepting evidence.

This report is an operator/status aid. It reads persisted preflight and
work-order reports plus safe work-packet surfaces, but it does not refresh
preflight, read operator response packets, read candidate artifact contents,
assemble packets, promote evidence, write canonical input packets, or count as
an acceptance gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from collections import Counter
from pathlib import Path
from typing import Any

import real_evidence_collection_work_orders as work_orders
import real_evidence_governance_approval as governance_approval
import real_evidence_preflight as preflight
import real_evidence_submission_manifest as submission_manifest


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
WORK_PACKETS = ROOT / "work_packets"
OUTPUT_PATH = RESULTS / "real_evidence_gate_progress.json"
VALIDATION_REPORT_SUFFIX = "_candidate_validation_report.json"
APPROVAL_NAME_MARKER = "approval"
HISTORICAL_GATE_IDS = list(preflight.EXPECTED_GATES)


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _safe_rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return "<outside-kg-eval>"


def work_packet_surface(path: Path) -> dict[str, Any]:
    rel = _safe_rel(path)
    surface: dict[str, Any] = {
        "path": rel,
        "state": "missing",
        "sha256": None,
        "present": False,
        "regular": False,
        "hardlink_alias": False,
    }
    try:
        resolved = path.resolve()
        resolved.relative_to(WORK_PACKETS.resolve())
    except (OSError, ValueError):
        surface["state"] = "outside_work_packets_rejected"
        return surface
    if len(path.relative_to(ROOT).parts) != 2:
        surface["state"] = "nested_work_packet_rejected"
        return surface
    if path.is_symlink():
        surface.update({"state": "symlink_rejected", "present": True})
        return surface
    if not path.exists():
        return surface
    try:
        metadata = path.stat()
    except OSError:
        surface.update({"state": "metadata_unreadable", "present": True})
        return surface
    surface["present"] = True
    if not stat.S_ISREG(metadata.st_mode):
        surface["state"] = "non_regular_rejected"
        return surface
    surface["regular"] = True
    if metadata.st_nlink > 1:
        surface.update({"state": "hardlink_rejected", "hardlink_alias": True})
        return surface
    surface.update({"state": "regular", "sha256": _sha256_file(path)})
    return surface


def _candidate_manifest_surfaces() -> dict[str, dict[str, Any]]:
    surfaces: dict[str, dict[str, Any]] = {}
    for expected in submission_manifest.EXPECTED_SUBMISSIONS:
        path = ROOT / expected.assembly_manifest_output
        surfaces[expected.gate_id] = work_packet_surface(path)
    return surfaces


def _validation_report_candidates() -> list[Path]:
    return sorted(WORK_PACKETS.glob(f"*{VALIDATION_REPORT_SUFFIX}"))


def _validation_rows_by_gate(
    candidate_manifest_surfaces: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_gate: dict[str, list[dict[str, Any]]] = {
        expected.gate_id: [] for expected in submission_manifest.EXPECTED_SUBMISSIONS
    }
    for path in _validation_report_candidates():
        surface = work_packet_surface(path)
        payload = _load_json(path) if surface["state"] == "regular" else {}
        artifact_id = payload.get("artifact_id")
        if artifact_id != "kg_real_evidence_candidate_manifest_validation_v1":
            continue
        for row in payload.get("validation_results", []):
            if not isinstance(row, dict):
                continue
            gate_id = row.get("gate_id")
            expected = submission_manifest.EXPECTED_BY_GATE.get(gate_id)
            if expected is None:
                continue
            if gate_id not in by_gate:
                continue
            candidate_manifest = row.get("candidate_manifest")
            current_manifest_surface = candidate_manifest_surfaces.get(gate_id, {})
            current_manifest_sha = (
                current_manifest_surface.get("sha256")
                if current_manifest_surface.get("state") == "regular"
                else None
            )
            candidate_manifest_matches_gate = (
                candidate_manifest == expected.assembly_manifest_output
            )
            candidate_manifest_sha256 = row.get("candidate_manifest_sha256")
            candidate_manifest_sha256_current = (
                isinstance(candidate_manifest_sha256, str)
                and current_manifest_surface.get("state") == "regular"
                and candidate_manifest_sha256 == current_manifest_sha
            )
            status = row.get("status")
            by_gate[gate_id].append(
                {
                    "report": surface["path"],
                    "report_sha256": surface["sha256"],
                    "candidate_manifest": candidate_manifest
                    if candidate_manifest_matches_gate
                    else "<unexpected-candidate-manifest>",
                    "candidate_manifest_matches_gate": candidate_manifest_matches_gate,
                    "candidate_manifest_surface_state": current_manifest_surface.get(
                        "state", "unknown"
                    ),
                    "candidate_manifest_sha256_current": candidate_manifest_sha256_current,
                    "assembler_exit_code": row.get("exit_code")
                    if isinstance(row.get("exit_code"), int)
                    else None,
                    "candidate_validation_clear": (
                        status == "passed"
                        and candidate_manifest_matches_gate
                        and candidate_manifest_sha256_current
                    ),
                    "candidate_validation_status": status
                    if status in {"passed", "failed"}
                    else "unknown",
                    "canonical_packet_integrity_clear": bool(
                        row.get("canonical_packet_integrity", {}).get("passed")
                    ),
                }
            )
    for rows in by_gate.values():
        rows.sort(key=lambda item: item["report"])
    return by_gate


def _approval_manifest_candidates() -> list[Path]:
    candidates: list[Path] = []
    for path in sorted(WORK_PACKETS.glob("*.json")):
        name = path.name.lower()
        if APPROVAL_NAME_MARKER not in name:
            continue
        if name.endswith(".template.json"):
            continue
        candidates.append(path)
    return candidates


def _progress_authority() -> dict[str, bool]:
    return {
        "accepts_evidence": False,
        "reads_operator_response_packets": False,
        "reads_candidate_artifact_contents": False,
        "writes_candidate_artifacts": False,
        "writes_canonical_packets": False,
        "promotes_evidence": False,
        "counts_as_acceptance_gate": False,
        "replaces_authoritative_validators": False,
    }


def _approval_rows_by_gate() -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    by_gate: dict[str, list[dict[str, Any]]] = {
        expected.gate_id: [] for expected in submission_manifest.EXPECTED_SUBMISSIONS
    }
    rejected_surfaces: list[dict[str, Any]] = []
    for path in _approval_manifest_candidates():
        surface = work_packet_surface(path)
        if surface["state"] != "regular":
            rejected_surfaces.append(
                {
                    "approval_manifest": surface["path"],
                    "approval_surface_state": surface["state"],
                    "reason": "approval manifest surface is not a safe regular work packet",
                }
            )
            continue
        payload = _load_json(path)
        gate_id = payload.get("gate_id")
        if gate_id not in by_gate:
            if gate_id in submission_manifest.EXPECTED_BY_GATE:
                continue
            rejected_surfaces.append(
                {
                    "approval_manifest": surface["path"],
                    "approval_manifest_sha256": surface["sha256"],
                    "approval_surface_state": surface["state"],
                    "reason": "approval manifest gate_id is missing or unexpected",
                }
            )
            continue
        validation = governance_approval.validate_approval_manifest(payload, manifest_path=path)
        by_gate[gate_id].append(
            {
                "approval_manifest": surface["path"],
                "approval_manifest_sha256": surface["sha256"],
                "approval_validation_valid": validation.get("valid") is True,
                "approval_validation_blocker_count": len(validation.get("blockers", []))
                if isinstance(validation.get("blockers"), list)
                else 0,
                "approval_surface_state": surface["state"],
            }
        )
    for rows in by_gate.values():
        rows.sort(key=lambda item: item["approval_manifest"])
    rejected_surfaces.sort(key=lambda item: item["approval_manifest"])
    return by_gate, rejected_surfaces


def _gate_ids_from_preflight(preflight_report: dict[str, Any]) -> list[Any]:
    return [
        row.get("gate_id") for row in preflight_report.get("gates", []) if isinstance(row, dict)
    ]


def _gate_ids_from_work_orders(work_order_report: dict[str, Any]) -> list[Any]:
    return [
        row.get("gate_id")
        for row in work_order_report.get("work_orders", [])
        if isinstance(row, dict)
    ]


def _source_report_contract(
    preflight_report: dict[str, Any],
    work_order_report: dict[str, Any],
) -> dict[str, Any]:
    preflight_summary = preflight_report.get("summary", {})
    work_order_summary = work_order_report.get("summary", {})
    current_blocked_gate_ids = preflight_summary.get("blocked_gate_ids")
    if not isinstance(current_blocked_gate_ids, list):
        current_blocked_gate_ids = []
    current_blocked_gate_ids = list(current_blocked_gate_ids)
    preflight_gate_ids = _gate_ids_from_preflight(preflight_report)
    work_order_gate_ids = _gate_ids_from_work_orders(work_order_report)
    checks = {
        "preflight_artifact_id": (
            preflight_report.get("artifact_id") == "kg_real_evidence_preflight_v1"
        ),
        "work_order_artifact_id": (
            work_order_report.get("artifact_id") == "kg_real_evidence_collection_work_orders_v1"
        ),
        "preflight_checklist_synchronized": (
            preflight_report.get("checklist_sync", {}).get("status") == "synchronized"
        ),
        "work_order_sync_synchronized": (
            work_order_report.get("sync", {}).get("status") == "synchronized"
        ),
        "preflight_gate_ids_cover_historical_monitored_gates": preflight_gate_ids
        == HISTORICAL_GATE_IDS,
        "current_blocked_gate_ids_are_historical_subset": all(
            gate_id in HISTORICAL_GATE_IDS for gate_id in current_blocked_gate_ids
        ),
        "work_order_gate_ids_match_current_blocked_gates": work_order_gate_ids
        == current_blocked_gate_ids,
        "work_order_blocked_gate_ids_match_preflight": work_order_summary.get(
            "preflight_blocked_gate_ids"
        )
        == current_blocked_gate_ids,
        "work_order_gate_status_hash_matches_preflight": work_order_summary.get(
            "gate_status_sha256"
        )
        == preflight_summary.get("gate_status_sha256"),
        "work_order_source_preflight_path": (
            work_order_report.get("source_preflight") == "results/real_evidence_preflight.json"
        ),
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return {
        "valid": not blockers,
        "status": "valid" if not blockers else "invalid",
        "checks": checks,
        "blockers": blockers,
        "historical_monitored_gate_ids": HISTORICAL_GATE_IDS,
        "current_blocked_gate_ids": current_blocked_gate_ids,
        "expected_gate_ids": current_blocked_gate_ids,
        "preflight_gate_ids": preflight_gate_ids,
        "work_order_gate_ids": work_order_gate_ids,
    }


def _stage_for_gate(
    *,
    preflight_row: dict[str, Any],
    manifest_surface: dict[str, Any],
    validation_rows: list[dict[str, Any]],
    approval_rows: list[dict[str, Any]],
) -> str:
    packet_state = preflight_row.get("packet_surface", {}).get("packet_state")
    if packet_state == "validator_clear":
        return "canonical_packet_validator_clear"
    if packet_state not in {None, "missing"}:
        return "canonical_packet_present_needs_validator_clear"
    if any(row.get("approval_validation_valid") is True for row in approval_rows):
        return "approval_valid_pending_promotion"
    if any(row.get("candidate_validation_clear") is True for row in validation_rows):
        return "candidate_validation_clear_pending_approval"
    if validation_rows:
        return "candidate_validation_failed_or_stale"
    if manifest_surface.get("state") == "regular":
        return "candidate_manifest_present_pending_validation"
    real_root_scan = preflight_row.get("real_root_scan", {})
    if real_root_scan.get("candidate_artifact_count", 0) > 0:
        return "candidate_artifacts_present_without_manifest"
    return "missing_operator_response"


def _next_action(stage: str) -> str:
    return {
        "canonical_packet_validator_clear": "rerun total acceptance and objective audit",
        "canonical_packet_present_needs_validator_clear": (
            "fix the canonical packet until the broad validator clears"
        ),
        "approval_valid_pending_promotion": (
            "execute governed approved promotion, then run the target validator"
        ),
        "candidate_validation_clear_pending_approval": (
            "perform manual governance review and create an approval manifest"
        ),
        "candidate_validation_failed_or_stale": (
            "fix candidate artifacts or rerun validate-candidate-manifests"
        ),
        "candidate_manifest_present_pending_validation": (
            "run validate-candidate-manifests and emit a candidate validation report"
        ),
        "candidate_artifacts_present_without_manifest": (
            "rerun candidate intake with candidate-manifest output"
        ),
        "missing_operator_response": "collect and seal the operator response packet",
    }[stage]


def build_report(
    *,
    preflight_report_override: dict[str, Any] | None = None,
    work_order_report_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preflight_report = (
        preflight_report_override
        if preflight_report_override is not None
        else _load_json(preflight.OUTPUT_PATH)
    )
    work_order_report = (
        work_order_report_override
        if work_order_report_override is not None
        else _load_json(work_orders.OUTPUT_PATH)
    )
    source_contract = _source_report_contract(preflight_report, work_order_report)
    if not source_contract["valid"]:
        report = {
            "artifact_id": "kg_real_evidence_gate_progress_v1",
            "workspace": ".formowl/kg-eval",
            "source_preflight": "results/real_evidence_preflight.json",
            "source_work_orders": "results/real_evidence_collection_work_orders.json",
            "progress_authority": _progress_authority(),
            "progress_state": "withheld_due_to_source_report_contract",
            "source_report_contract": source_contract,
            "summary": {
                "gate_count": 0,
                "gate_ids": [],
                "stage_counts": {},
                "blocked_gate_ids": [],
                "total_acceptance_state": None,
                "candidate_manifest_regular_gate_count": 0,
                "candidate_validation_clear_gate_count": 0,
                "valid_approval_manifest_gate_count": 0,
                "canonical_validator_clear_gate_count": 0,
                "rejected_approval_manifest_surface_count": 0,
            },
            "work_packet_hazards": {
                "rejected_approval_manifest_surface_count": 0,
                "rejected_approval_manifest_surfaces": [],
            },
            "gate_progress": [],
        }
        report["report_sha256"] = sha256_json(
            {key: value for key, value in report.items() if key != "report_sha256"}
        )
        return report
    preflight_by_gate = {
        row.get("gate_id"): row
        for row in preflight_report.get("gates", [])
        if isinstance(row, dict)
    }
    work_orders_by_gate = {
        row.get("gate_id"): row
        for row in work_order_report.get("work_orders", [])
        if isinstance(row, dict)
    }
    candidate_manifests = _candidate_manifest_surfaces()
    validation_by_gate = _validation_rows_by_gate(candidate_manifests)
    approval_by_gate, rejected_approval_surfaces = _approval_rows_by_gate()
    gate_rows: list[dict[str, Any]] = []
    for gate_id in source_contract["current_blocked_gate_ids"]:
        expected = submission_manifest.EXPECTED_BY_GATE.get(gate_id)
        if expected is None:
            continue
        preflight_row = preflight_by_gate.get(gate_id, {})
        manifest_surface = candidate_manifests[gate_id]
        validation_rows = validation_by_gate.get(gate_id, [])
        approval_rows = approval_by_gate.get(gate_id, [])
        stage = _stage_for_gate(
            preflight_row=preflight_row,
            manifest_surface=manifest_surface,
            validation_rows=validation_rows,
            approval_rows=approval_rows,
        )
        work_order = work_orders_by_gate.get(gate_id, {})
        real_root_scan = preflight_row.get("real_root_scan", {})
        packet_surface = preflight_row.get("packet_surface", {})
        gate_rows.append(
            {
                "gate_id": gate_id,
                "requirement_id": preflight_row.get("requirement_id") or expected.gate_id,
                "stage": stage,
                "next_action": _next_action(stage),
                "current_blockers": list(work_order.get("current_blockers", []))
                if isinstance(work_order.get("current_blockers"), list)
                else list(preflight_row.get("current_total_gate_blockers", [])),
                "canonical_packet": {
                    "path": expected.canonical_packet,
                    "packet_state": packet_surface.get("packet_state", "unknown"),
                    "validator_status": preflight_row.get("validator_status", "unknown"),
                    "sha256": packet_surface.get("sha256"),
                },
                "real_root": {
                    "path": expected.real_root,
                    "file_count": real_root_scan.get("file_count", 0),
                    "candidate_artifact_count": real_root_scan.get("candidate_artifact_count", 0),
                    "disappeared_file_count": real_root_scan.get("disappeared_file_count", 0),
                    "root_ready": bool(real_root_scan.get("root_ready")),
                },
                "candidate_manifest": manifest_surface,
                "candidate_validation": {
                    "report_count": len(validation_rows),
                    "clear_report_count": sum(
                        1 for row in validation_rows if row["candidate_validation_clear"]
                    ),
                    "reports": validation_rows,
                },
                "governance_approval": {
                    "approval_manifest_count": len(approval_rows),
                    "valid_approval_manifest_count": sum(
                        1 for row in approval_rows if row["approval_validation_valid"]
                    ),
                    "approval_manifests": approval_rows,
                },
            }
        )
    stage_counts = dict(Counter(row["stage"] for row in gate_rows))
    report = {
        "artifact_id": "kg_real_evidence_gate_progress_v1",
        "workspace": ".formowl/kg-eval",
        "source_preflight": "results/real_evidence_preflight.json",
        "source_work_orders": "results/real_evidence_collection_work_orders.json",
        "progress_authority": _progress_authority(),
        "progress_state": "report_current_from_persisted_sources",
        "source_report_contract": source_contract,
        "summary": {
            "gate_count": len(gate_rows),
            "gate_ids": [row["gate_id"] for row in gate_rows],
            "stage_counts": stage_counts,
            "blocked_gate_ids": preflight_report.get("summary", {}).get("blocked_gate_ids", []),
            "total_acceptance_state": preflight_report.get("summary", {}).get(
                "total_acceptance_state"
            ),
            "candidate_manifest_regular_gate_count": sum(
                1 for row in gate_rows if row["candidate_manifest"]["state"] == "regular"
            ),
            "candidate_validation_clear_gate_count": sum(
                1 for row in gate_rows if row["candidate_validation"]["clear_report_count"] > 0
            ),
            "valid_approval_manifest_gate_count": sum(
                1
                for row in gate_rows
                if row["governance_approval"]["valid_approval_manifest_count"] > 0
            ),
            "canonical_validator_clear_gate_count": stage_counts.get(
                "canonical_packet_validator_clear", 0
            ),
            "rejected_approval_manifest_surface_count": len(rejected_approval_surfaces),
        },
        "work_packet_hazards": {
            "rejected_approval_manifest_surface_count": len(rejected_approval_surfaces),
            "rejected_approval_manifest_surfaces": rejected_approval_surfaces,
        },
        "gate_progress": gate_rows,
    }
    report["report_sha256"] = sha256_json(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if the current progress report differs from results/",
    )
    args = parser.parse_args(argv)
    report = build_report()
    if args.check:
        current = _load_json(OUTPUT_PATH) if OUTPUT_PATH.exists() else None
        status = {
            "artifact_id": "kg_real_evidence_gate_progress_check_v1",
            "output": str(OUTPUT_PATH.relative_to(ROOT)),
            "up_to_date": current == report,
            "authority": report["progress_authority"],
        }
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0 if current == report else 1
    RESULTS.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
