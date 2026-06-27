#!/usr/bin/env python3
"""Production adapter control recovery fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
REQUIRED_ACTIONS = [
    "deploy_started",
    "grant_check_before_content",
    "revoked_grant_blocks_content",
    "hidden_private_candidates_redacted",
    "canonical_merge_guard_rejected",
    "raw_asset_read_guard_rejected",
    "wiki_projection_draft_not_published",
    "deploy_completed",
]


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def row_hash(row: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in row.items() if key != "row_sha256"})


def with_row_hash(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["row_sha256"] = row_hash(payload)
    return payload


def default_fixture() -> dict[str, Any]:
    request_id = "deploy_req_001"
    resource_ref = "formowl://graph-view/recovery"
    policy_id = "production_adapter_policy_recovery_v1"
    audit_events = []
    for index, action in enumerate(REQUIRED_ACTIONS):
        decision = "allow" if action in {"deploy_started", "grant_check_before_content", "wiki_projection_draft_not_published", "deploy_completed"} else "deny"
        row = {
            "event_id": f"event_{index:02d}_{action}",
            "sequence": index,
            "action": action,
            "request_id": request_id,
            "resource_ref": resource_ref,
            "policy_id": policy_id,
            "decision": decision,
            "outcome_sha256": f"{index + 1:064x}",
        }
        if action == "grant_check_before_content":
            row["grant_state"] = "active"
        if action == "revoked_grant_blocks_content":
            row["grant_state"] = "revoked"
            row["denial_reason"] = "grant revoked"
        if action in {"canonical_merge_guard_rejected", "raw_asset_read_guard_rejected"}:
            row["denial_reason"] = "guard rejected"
        if action == "wiki_projection_draft_not_published":
            row["published"] = False
            row["draft_output_sha256"] = "a" * 64
        audit_events.append(with_row_hash(row))
    return {
        "artifact_id": "production_adapter_fixture_v1",
        "non_synthetic_deployment_present": False,
        "human_reviewed_false_merge_labels_present": False,
        "request_id": request_id,
        "resource_ref": resource_ref,
        "policy_id": policy_id,
        "audit_events": audit_events,
        "claim_boundary": {
            "supports_production_ready_claim": False,
            "supports_non_synthetic_deployment_claim": False,
            "supports_human_reviewed_false_merge_labels_claim": False,
            "supports_canonical_write_claim": False,
            "supports_raw_access_claim": False,
        },
    }


def validate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if not all(
        isinstance(fixture.get(field), str) and fixture[field]
        for field in ("request_id", "resource_ref", "policy_id")
    ):
        blockers.append("production fixture request/resource/policy binding missing")
    events = fixture.get("audit_events", [])
    if not isinstance(events, list) or not events:
        blockers.append("production audit events missing")
        events = []
    seen_ids = set()
    actions = []
    request_ids = set()
    for row in events:
        if not isinstance(row, dict) or row.get("row_sha256") != row_hash(row):
            blockers.append("production audit event hash mismatch")
            continue
        if row.get("event_id") in seen_ids:
            blockers.append("duplicate production audit event id")
        seen_ids.add(row.get("event_id"))
        actions.append(row.get("action"))
        request_ids.add(row.get("request_id"))
        for field in ("request_id", "resource_ref", "policy_id"):
            if not isinstance(row.get(field), str) or not row[field]:
                blockers.append("production audit event request/resource/policy binding missing")
        if row.get("resource_ref") != fixture.get("resource_ref"):
            blockers.append("production audit event resource mismatch")
        if row.get("policy_id") != fixture.get("policy_id"):
            blockers.append("production audit event policy mismatch")
    if actions != REQUIRED_ACTIONS:
        blockers.append("production audit control sequence mismatch")
    if request_ids != {fixture.get("request_id")}:
        blockers.append("production audit events do not bind one request id")
    by_action = {row.get("action"): row for row in events if isinstance(row, dict)}
    if by_action.get("revoked_grant_blocks_content", {}).get("decision") != "deny":
        blockers.append("revoked grant control does not deny content")
    if by_action.get("revoked_grant_blocks_content", {}).get("grant_state") != "revoked":
        blockers.append("revoked grant control does not bind revoked state")
    for action in ("canonical_merge_guard_rejected", "raw_asset_read_guard_rejected"):
        row = by_action.get(action, {})
        if row.get("decision") != "deny" or not row.get("denial_reason"):
            blockers.append(f"{action} is not an explicit deny guard")
    wiki = by_action.get("wiki_projection_draft_not_published", {})
    if wiki.get("published") is not False or not isinstance(wiki.get("draft_output_sha256"), str):
        blockers.append("wiki projection control did not remain draft-only")
    claims = fixture.get("claim_boundary", {})
    for flag in (
        "supports_production_ready_claim",
        "supports_non_synthetic_deployment_claim",
        "supports_human_reviewed_false_merge_labels_claim",
        "supports_canonical_write_claim",
        "supports_raw_access_claim",
    ):
        if claims.get(flag) is True:
            blockers.append(f"production adapter fixture overclaims {flag}")
    return {
        "passed": not blockers,
        "blockers": sorted(set(blockers)),
        "metrics": {
            "required_audit_action_count": len(REQUIRED_ACTIONS),
            "audit_event_count": len(events),
            "non_synthetic_deployment_present": fixture.get("non_synthetic_deployment_present") is True,
            "human_reviewed_false_merge_labels_present": fixture.get("human_reviewed_false_merge_labels_present") is True,
        },
    }


def build_report(fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    fixture = default_fixture() if fixture is None else fixture
    validation = validate_fixture(fixture)
    return {
        "artifact_id": "production_adapter_recovery_v1",
        "fixture_sha256": sha256_json(fixture),
        "passed": validation["passed"],
        "metrics": validation["metrics"],
        "blockers": validation["blockers"],
        "claim_boundary": {
            "supports_production_adapter_control_fixture_claim": validation["passed"],
            "supports_production_ready_claim": False,
            "supports_non_synthetic_deployment_claim": False,
            "supports_human_reviewed_false_merge_labels_claim": False,
            "supports_canonical_write_claim": False,
            "supports_raw_access_claim": False,
        },
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "production_adapter_recovery.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
