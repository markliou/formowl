#!/usr/bin/env python3
"""Scoped ontology/type-governance recovery experiment.

The experiment is intentionally deterministic. It proves the method boundary
for ontology use in FormOwl: type candidates are scoped, revision-pinned,
shape-checked, and review-gated. It does not claim a company-wide ontology,
OWL reasoning, or direct LLM type commits.
"""

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
    ontology_revision_id = "ontology_rev_workspace_finance_ops_001"
    return {
        "artifact_id": "scoped_ontology_integration_fixture_v1",
        "ontology_revision_id": ontology_revision_id,
        "core_type_ids": [
            "type:agent",
            "type:organization",
            "type:person",
            "type:document",
            "type:financial_obligation",
            "type:meeting_decision",
            "type:evidence_source",
        ],
        "scoped_extension_types": [
            {
                "type_id": "workspace:finance_ops:type:invoice_escalation",
                "scope_id": "workspace:finance_ops",
                "parent_type_id": "type:financial_obligation",
                "review_status": "accepted",
                "source_observation_ids": ["obs_mail_invoice_001", "obs_xlsx_amount_due_001"],
            }
        ],
        "aliases": [
            {
                "alias": "amount due",
                "type_id": "type:financial_obligation",
                "scope_id": "workspace:finance_ops",
            },
            {
                "alias": "decision item",
                "type_id": "type:meeting_decision",
                "scope_id": "workspace:finance_ops",
            },
        ],
        "relation_schemas": [
            {
                "relation_type_id": "relation:owes_amount",
                "source_type_id": "type:organization",
                "target_type_id": "type:financial_obligation",
                "required_slots": ["amount", "currency", "due_date", "evidence_source_id"],
            },
            {
                "relation_type_id": "relation:meeting_decision_affects_obligation",
                "source_type_id": "type:meeting_decision",
                "target_type_id": "type:financial_obligation",
                "required_slots": ["decision_time", "participant_ids", "evidence_source_id"],
            },
        ],
        "candidate_type_rows": [
            {
                "candidate_id": "cand_type_invoice_001",
                "source_observation_id": "obs_mail_invoice_001",
                "proposed_type_id": "workspace:finance_ops:type:invoice_escalation",
                "ontology_revision_id": ontology_revision_id,
                "action": "accept_as_scoped_extension",
                "llm_direct_commit": False,
            },
            {
                "candidate_id": "cand_type_unknown_vendor_001",
                "source_observation_id": "obs_xlsx_vendor_001",
                "proposed_type_id": "type:organization",
                "ontology_revision_id": ontology_revision_id,
                "action": "accept_core_type",
                "llm_direct_commit": False,
            },
        ],
        "relation_rows": [
            {
                "relation_id": "cand_rel_invoice_amount_001",
                "relation_type_id": "relation:owes_amount",
                "source_type_id": "type:organization",
                "target_type_id": "type:financial_obligation",
                "slots": {
                    "amount": "12500.00",
                    "currency": "USD",
                    "due_date": "2026-07-31",
                    "evidence_source_id": "obs_mail_invoice_001",
                },
                "ontology_revision_id": ontology_revision_id,
            },
            {
                "relation_id": "cand_rel_decision_invoice_001",
                "relation_type_id": "relation:meeting_decision_affects_obligation",
                "source_type_id": "type:meeting_decision",
                "target_type_id": "type:financial_obligation",
                "slots": {
                    "decision_time": "2026-06-18T10:30:00Z",
                    "participant_ids": ["person:finance_lead", "person:sales_ops"],
                    "evidence_source_id": "obs_meeting_segment_004",
                },
                "ontology_revision_id": ontology_revision_id,
            },
        ],
        "revision_mappings": [
            {
                "from_ontology_revision_id": "ontology_rev_workspace_finance_ops_000",
                "to_ontology_revision_id": ontology_revision_id,
                "mapping_type": "supersedes",
                "old_type_id": "workspace:finance_ops:type:invoice_issue",
                "new_type_id": "workspace:finance_ops:type:invoice_escalation",
            }
        ],
    }


def validate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    ontology_revision_id = fixture.get("ontology_revision_id")
    if not isinstance(ontology_revision_id, str) or not ontology_revision_id:
        blockers.append("ontology revision id missing")

    core_type_ids = set(fixture.get("core_type_ids", []))
    if len(core_type_ids) < 5:
        blockers.append("closed core type set is too small")

    scoped_types = fixture.get("scoped_extension_types", [])
    if not isinstance(scoped_types, list) or not scoped_types:
        blockers.append("scoped extension type evidence missing")
        scoped_types = []
    scoped_type_ids = set()
    for row in scoped_types:
        if not isinstance(row, dict):
            blockers.append("scoped extension type row malformed")
            continue
        type_id = row.get("type_id")
        scoped_type_ids.add(type_id)
        if not isinstance(type_id, str) or not type_id.startswith("workspace:"):
            blockers.append("scoped extension type id is not scoped")
        if not isinstance(row.get("scope_id"), str) or not row["scope_id"]:
            blockers.append("scoped extension type scope id missing")
        if row.get("parent_type_id") not in core_type_ids:
            blockers.append("scoped extension parent type is not in closed core")
        if row.get("review_status") != "accepted":
            blockers.append("scoped extension type is not review accepted")
        if not row.get("source_observation_ids"):
            blockers.append("scoped extension type lacks source observations")

    allowed_type_ids = core_type_ids | scoped_type_ids
    aliases = fixture.get("aliases", [])
    if not isinstance(aliases, list) or not aliases:
        blockers.append("type alias mapping evidence missing")
        aliases = []
    for row in aliases:
        if not isinstance(row, dict) or row.get("type_id") not in allowed_type_ids:
            blockers.append("alias maps to unknown type")
        if isinstance(row, dict) and row.get("scope_id") == "*":
            blockers.append("alias uses unscoped global wildcard")

    schemas = {
        row.get("relation_type_id"): row
        for row in fixture.get("relation_schemas", [])
        if isinstance(row, dict)
    }
    if not schemas:
        blockers.append("relation schema evidence missing")
    for schema in schemas.values():
        if schema.get("source_type_id") not in allowed_type_ids:
            blockers.append("relation schema source type unknown")
        if schema.get("target_type_id") not in allowed_type_ids:
            blockers.append("relation schema target type unknown")
        if not isinstance(schema.get("required_slots"), list) or not schema["required_slots"]:
            blockers.append("relation schema required slots missing")

    candidate_rows = fixture.get("candidate_type_rows", [])
    if not isinstance(candidate_rows, list) or not candidate_rows:
        blockers.append("candidate type rows missing")
        candidate_rows = []
    for row in candidate_rows:
        if not isinstance(row, dict):
            blockers.append("candidate type row malformed")
            continue
        if row.get("ontology_revision_id") != ontology_revision_id:
            blockers.append("candidate type row ontology revision mismatch")
        if row.get("proposed_type_id") not in allowed_type_ids:
            blockers.append("candidate type row proposes unknown type")
        if row.get("llm_direct_commit") is not False:
            blockers.append("candidate type row allows LLM direct commit")
        if row.get("action") not in {"accept_core_type", "accept_as_scoped_extension", "needs_review"}:
            blockers.append("candidate type row has unsupported governance action")
        if not isinstance(row.get("source_observation_id"), str) or not row["source_observation_id"]:
            blockers.append("candidate type row lacks source observation")

    relation_rows = fixture.get("relation_rows", [])
    if not isinstance(relation_rows, list) or not relation_rows:
        blockers.append("typed relation rows missing")
        relation_rows = []
    for row in relation_rows:
        if not isinstance(row, dict):
            blockers.append("typed relation row malformed")
            continue
        schema = schemas.get(row.get("relation_type_id"))
        if schema is None:
            blockers.append("typed relation row references unknown schema")
            continue
        if row.get("ontology_revision_id") != ontology_revision_id:
            blockers.append("typed relation row ontology revision mismatch")
        if row.get("source_type_id") != schema.get("source_type_id"):
            blockers.append("typed relation source type violates schema")
        if row.get("target_type_id") != schema.get("target_type_id"):
            blockers.append("typed relation target type violates schema")
        slots = row.get("slots")
        if not isinstance(slots, dict):
            blockers.append("typed relation row slots malformed")
            continue
        for slot in schema.get("required_slots", []):
            if slot not in slots:
                blockers.append(f"typed relation row missing required slot: {slot}")

    mappings = fixture.get("revision_mappings", [])
    if not isinstance(mappings, list) or not mappings:
        blockers.append("ontology revision mapping evidence missing")
    elif not any(row.get("to_ontology_revision_id") == ontology_revision_id for row in mappings if isinstance(row, dict)):
        blockers.append("ontology revision mapping does not target current revision")

    metrics = {
        "core_type_count": len(core_type_ids),
        "scoped_extension_type_count": len(scoped_type_ids),
        "candidate_type_row_count": len(candidate_rows),
        "typed_relation_row_count": len(relation_rows),
        "schema_violation_count": len([blocker for blocker in blockers if "violates schema" in blocker or "missing required slot" in blocker]),
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
        "artifact_id": "scoped_ontology_integration_recovery_v1",
        "fixture_sha256": sha256_json(fixture),
        "ontology_revision_id": fixture.get("ontology_revision_id"),
        "passed": validation["passed"],
        "metrics": validation["metrics"],
        "blockers": validation["blockers"],
        "claim_boundary": {
            "supports_scoped_ontology_integration_method_claim": validation["passed"],
            "supports_company_wide_ontology_claim": False,
            "supports_owl_reasoner_claim": False,
            "supports_llm_direct_type_commit_claim": False,
            "supports_unreviewed_cross_scope_type_merge_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "scoped_ontology_integration_recovery.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
