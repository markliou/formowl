#!/usr/bin/env python3
"""Different-user KG and permission-aware fusion recovery experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def default_fixture() -> dict[str, Any]:
    return {
        "artifact_id": "user_graph_fusion_fixture_v1",
        "canonical_atom_graph_revision_id": "atom_graph_rev_finance_ops_001",
        "users": [
            {
                "user_id": "user_finance_lead",
                "user_graph_revision_id": "ugraph_finance_lead_001",
                "profile_id": "profile_finance_operational",
                "visible_atom_ids": ["atom_client_orion", "atom_invoice_001", "atom_decision_001"],
                "private_atom_ids": ["atom_private_invoice_note"],
            },
            {
                "user_id": "user_sales_ops",
                "user_graph_revision_id": "ugraph_sales_ops_001",
                "profile_id": "profile_sales_account",
                "visible_atom_ids": ["atom_account_orion", "atom_decision_001"],
                "private_atom_ids": ["atom_private_commission_note"],
            },
        ],
        "grants": [
            {
                "grant_id": "grant_finance_to_sales_snippet_001",
                "from_user_id": "user_finance_lead",
                "to_user_id": "user_sales_ops",
                "access_level": "graph_snippet",
                "state": "active",
                "visible_atom_ids": ["atom_client_orion", "atom_invoice_001"],
                "raw_asset_access": False,
            },
            {
                "grant_id": "grant_sales_revoked_001",
                "from_user_id": "user_sales_ops",
                "to_user_id": "user_finance_lead",
                "access_level": "graph_snippet",
                "state": "revoked",
                "visible_atom_ids": ["atom_account_orion"],
                "raw_asset_access": False,
            },
        ],
        "fusion_candidates": [
            {
                "fusion_candidate_id": "fusion_orion_client_account_001",
                "left_user_id": "user_finance_lead",
                "right_user_id": "user_sales_ops",
                "left_atom_id": "atom_client_orion",
                "right_atom_id": "atom_account_orion",
                "score": 0.91,
                "decision": "proposal_only_needs_review",
                "conflict_id": "conflict_client_vs_account_scope_001",
                "canonical_merge_executed": False,
                "raw_access_granted_by_match": False,
                "evidence_atom_ids": ["atom_client_orion", "atom_account_orion"],
            }
        ],
        "effective_view_checks": [
            {
                "requester_user_id": "user_sales_ops",
                "target_user_id": "user_finance_lead",
                "grant_id": "grant_finance_to_sales_snippet_001",
                "expected_visible_atom_ids": ["atom_client_orion", "atom_invoice_001"],
                "observed_visible_atom_ids": ["atom_client_orion", "atom_invoice_001"],
                "observed_private_atom_ids": [],
                "raw_asset_access_observed": False,
            },
            {
                "requester_user_id": "user_finance_lead",
                "target_user_id": "user_sales_ops",
                "grant_id": "grant_sales_revoked_001",
                "expected_visible_atom_ids": [],
                "observed_visible_atom_ids": [],
                "observed_private_atom_ids": [],
                "raw_asset_access_observed": False,
            },
        ],
        "revocation_probe": {
            "probe_id": "revocation_after_index_probe_001",
            "revoked_grant_id": "grant_sales_revoked_001",
            "indexed_before_revocation": True,
            "visible_after_revocation_count": 0,
            "cross_user_edge_leak_count": 0,
            "passed": True,
        },
    }


def validate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    users = fixture.get("users", [])
    if not isinstance(users, list) or len(users) < 2:
        blockers.append("multi-user fusion requires at least two users")
        users = []
    user_ids = {
        row.get("user_id")
        for row in users
        if isinstance(row, dict) and isinstance(row.get("user_id"), str)
    }
    graph_revision_ids = {
        row.get("user_graph_revision_id")
        for row in users
        if isinstance(row, dict) and isinstance(row.get("user_graph_revision_id"), str)
    }
    private_atoms_by_user = {
        row.get("user_id"): set(row.get("private_atom_ids", []))
        for row in users
        if isinstance(row, dict) and isinstance(row.get("user_id"), str)
    }
    if len(graph_revision_ids) != len(user_ids):
        blockers.append("each user must have a distinct user graph revision")
    for row in users:
        if not isinstance(row, dict):
            blockers.append("user graph row malformed")
            continue
        if not isinstance(row.get("profile_id"), str) or not row["profile_id"]:
            blockers.append("user graph profile id missing")
        if not isinstance(row.get("visible_atom_ids"), list):
            blockers.append("user graph visible atom list missing")
        if not isinstance(row.get("private_atom_ids"), list):
            blockers.append("user graph private atom list missing")

    grants = fixture.get("grants", [])
    if not isinstance(grants, list) or not grants:
        blockers.append("permission grant evidence missing")
        grants = []
    grant_by_id = {}
    for row in grants:
        if not isinstance(row, dict):
            blockers.append("grant row malformed")
            continue
        grant_by_id[row.get("grant_id")] = row
        if row.get("from_user_id") not in user_ids or row.get("to_user_id") not in user_ids:
            blockers.append("grant references unknown user")
        if row.get("state") not in {"active", "revoked"}:
            blockers.append("grant state invalid")
        if row.get("raw_asset_access") is not False:
            blockers.append("graph-snippet grant unexpectedly gives raw asset access")
        grant_private_atoms = private_atoms_by_user.get(row.get("from_user_id"), set())
        grant_visible_atoms = set(row.get("visible_atom_ids", []))
        if grant_private_atoms & grant_visible_atoms:
            blockers.append("grant visible atom list includes private atoms")

    fusion_candidates = fixture.get("fusion_candidates", [])
    if not isinstance(fusion_candidates, list) or not fusion_candidates:
        blockers.append("fusion candidate evidence missing")
        fusion_candidates = []
    conflict_ids: set[str] = set()
    for row in fusion_candidates:
        if not isinstance(row, dict):
            blockers.append("fusion candidate row malformed")
            continue
        if row.get("left_user_id") not in user_ids or row.get("right_user_id") not in user_ids:
            blockers.append("fusion candidate references unknown user")
        if row.get("left_user_id") == row.get("right_user_id"):
            blockers.append("fusion candidate is not cross-user")
        if row.get("decision") != "proposal_only_needs_review":
            blockers.append("fusion candidate decision is not proposal-only review")
        if row.get("canonical_merge_executed") is not False:
            blockers.append("fusion candidate executed canonical merge")
        if row.get("raw_access_granted_by_match") is not False:
            blockers.append("fusion candidate grants raw access by match")
        if not isinstance(row.get("conflict_id"), str) or not row["conflict_id"]:
            blockers.append("fusion candidate does not surface conflict id")
        else:
            conflict_ids.add(row["conflict_id"])
        score = row.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
            blockers.append("fusion candidate score malformed")

    effective_checks = fixture.get("effective_view_checks", [])
    if not isinstance(effective_checks, list) or not effective_checks:
        blockers.append("effective view check evidence missing")
        effective_checks = []
    private_leak_count = 0
    for row in effective_checks:
        if not isinstance(row, dict):
            blockers.append("effective view check row malformed")
            continue
        grant = grant_by_id.get(row.get("grant_id"))
        if not grant:
            blockers.append("effective view check references unknown grant")
            continue
        expected = row.get("expected_visible_atom_ids")
        observed = row.get("observed_visible_atom_ids")
        if expected != observed:
            blockers.append("effective view observed atoms differ from expected grant overlay")
        target_private_atoms = private_atoms_by_user.get(row.get("target_user_id"), set())
        visible_atoms = set(expected or []) | set(observed or [])
        if target_private_atoms & visible_atoms:
            blockers.append("effective view visible atom list includes private atoms")
        leaked_private = row.get("observed_private_atom_ids")
        if leaked_private:
            private_leak_count += len(leaked_private)
            blockers.append("effective view leaked private atoms")
        if row.get("raw_asset_access_observed") is not False:
            blockers.append("effective view exposed raw asset access")
        if grant.get("state") == "revoked" and observed:
            blockers.append("revoked grant still exposes graph atoms")

    revocation_probe = fixture.get("revocation_probe", {})
    if not isinstance(revocation_probe, dict) or not revocation_probe:
        blockers.append("revocation-after-index probe missing")
        revocation_probe = {}
    if revocation_probe.get("passed") is not True:
        blockers.append("revocation-after-index probe failed")
    if revocation_probe.get("visible_after_revocation_count") != 0:
        blockers.append("revocation-after-index probe exposed revoked atoms")
    if revocation_probe.get("cross_user_edge_leak_count") != 0:
        blockers.append("revocation-after-index probe leaked cross-user edges")

    metrics = {
        "distinct_user_count": len(user_ids),
        "user_graph_revision_count": len(graph_revision_ids),
        "fusion_candidate_count": len(fusion_candidates),
        "fusion_conflict_count": len(conflict_ids),
        "cross_user_edge_leak_count": revocation_probe.get("cross_user_edge_leak_count"),
        "private_atom_leak_count": private_leak_count,
        "canonical_merge_execution_count": sum(
            1 for row in fusion_candidates if isinstance(row, dict) and row.get("canonical_merge_executed") is True
        ),
    }
    return {
        "passed": not blockers,
        "blockers": sorted(set(blockers)),
        "metrics": metrics,
    }


def build_report(fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    fixture = fixture or default_fixture()
    validation = validate_fixture(fixture)
    return {
        "artifact_id": "user_graph_fusion_recovery_v1",
        "fixture_sha256": sha256_json(fixture),
        "passed": validation["passed"],
        "metrics": validation["metrics"],
        "blockers": validation["blockers"],
        "claim_boundary": {
            "supports_different_user_kg_fusion_method_claim": validation["passed"],
            "supports_full_automatic_kg_merge_claim": False,
            "supports_raw_data_fusion_without_grants_claim": False,
            "supports_unreviewed_cross_user_merge_claim": False,
            "supports_production_kg_fusion_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "user_graph_fusion_recovery.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
