#!/usr/bin/env python3
"""Recovered objective-completion audit for the KG method goal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import kg_total_acceptance_suite as suite


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

OBJECTIVE = (
    "完成 FormOwl Knowledge Graph 方法探索與驗收：補齊外部近期文獻比較、"
    "ontology 結合方法、不同使用者 KG 與 KG 融合實驗、多模態企業資料驗證、"
    "標註/裁決流程（legacy human 或四專業 LLM subagent panel）、"
    "production adapter gate，並用總驗收套件清楚標示已通過與未通過項目。"
)


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_snapshot() -> dict[str, Any]:
    path = RESULTS / "kg_total_acceptance_snapshot.json"
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            gate_ids = {
                gate.get("gate_id") for gate in loaded.get("gates", []) if isinstance(gate, dict)
            }
            required_current_gates = {
                "external_recent_literature_baseline_protocol",
                "scoped_ontology_integration_method",
                "different_user_kg_fusion_method",
                "fair_external_baseline_comparison",
                "annotation_adjudication_protocol",
                "multimodal_semantic_validation",
                "production_adapter_paths",
                "overclaim_guard",
            }
            if required_current_gates.issubset(gate_ids):
                return loaded
    return suite.build_report()


def gate_by_id(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        gate.get("gate_id"): gate
        for gate in snapshot.get("gates", [])
        if isinstance(gate, dict) and isinstance(gate.get("gate_id"), str)
    }


def requirement(
    requirement_id: str,
    description: str,
    required_gate_ids: list[str],
    gates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    gate_rows = []
    blockers: list[str] = []
    for gate_id in required_gate_ids:
        gate = gates.get(gate_id, {})
        passed = gate.get("passed") is True
        gate_blockers = gate.get("blockers", [])
        if not isinstance(gate_blockers, list):
            gate_blockers = ["gate blockers malformed"]
        if not passed:
            blockers.extend(f"{gate_id}: {blocker}" for blocker in gate_blockers)
        gate_rows.append(
            {
                "gate_id": gate_id,
                "present": bool(gate),
                "passed": passed,
                "blockers": gate_blockers,
            }
        )
    proved = all(row["present"] and row["passed"] for row in gate_rows)
    return {
        "requirement_id": requirement_id,
        "description": description,
        "status": "proved" if proved else "incomplete",
        "proved": proved,
        "required_gate_results": gate_rows,
        "blockers": blockers,
    }


def build_report() -> dict[str, Any]:
    snapshot = load_snapshot()
    gates = gate_by_id(snapshot)
    rows = [
        requirement(
            "external_recent_literature_comparison",
            "External recent literature comparison and baseline-selection rationale.",
            ["external_recent_literature_baseline_protocol"],
            gates,
        ),
        requirement(
            "fair_external_baseline_validation",
            "Fair external baseline validation with real package runs and adjudication.",
            ["fair_external_baseline_comparison"],
            gates,
        ),
        requirement(
            "ontology_integration_method",
            "Ontology integration method and type-governed graph validation.",
            ["scoped_ontology_integration_method"],
            gates,
        ),
        requirement(
            "different_user_kg_and_fusion",
            "Different-user KG and KG fusion experiment evidence.",
            ["different_user_kg_fusion_method"],
            gates,
        ),
        requirement(
            "multimodal_enterprise_validation",
            "Multimodal enterprise data validation.",
            ["multimodal_semantic_validation"],
            gates,
        ),
        requirement(
            "human_annotation_adjudication_protocol",
            "Annotation/adjudication evidence through legacy human workflow or four-specialist LLM subagent panel.",
            ["annotation_adjudication_protocol"],
            gates,
        ),
        requirement(
            "production_adapter_gate",
            "Production adapter path and non-synthetic deployment evidence.",
            ["production_adapter_paths"],
            gates,
        ),
        requirement(
            "total_acceptance_reporting",
            "Total acceptance suite clearly marks passed and failed gates.",
            ["overclaim_guard"],
            gates,
        ),
        requirement(
            "current_recovery_overclaim_boundary",
            "Recovered current state rejects unsupported production/top-tier/autonomous claims.",
            ["overclaim_guard"],
            gates,
        ),
    ]
    incomplete = [row for row in rows if not row["proved"]]
    failed_gate_ids = snapshot.get("summary", {}).get("failed_gate_ids", [])
    report = {
        "artifact_id": "kg_objective_completion_audit_recovery_v1",
        "objective": OBJECTIVE,
        "objective_complete": not incomplete,
        "requirement_count": len(rows),
        "proved_requirement_count": len(rows) - len(incomplete),
        "incomplete_requirement_count": len(incomplete),
        "failed_gate_ids": failed_gate_ids,
        "requirement_rows": rows,
        "claim_boundary": {
            "supports_goal_complete_claim": False,
            "supports_objective_completion_audit_claim": True,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
            "supports_unreviewed_business_judgment_claim": False,
            "supports_unreviewed_cross_user_merge_claim": False,
        },
    }
    report["audit_sha256"] = sha256_json(
        {
            "objective_complete": report["objective_complete"],
            "proved_requirement_count": report["proved_requirement_count"],
            "incomplete_requirement_count": report["incomplete_requirement_count"],
            "failed_gate_ids": failed_gate_ids,
        }
    )
    return report


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (RESULTS / "kg_objective_completion_audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
