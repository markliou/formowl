#!/usr/bin/env python3
"""Shared four-specialist LLM subagent adjudication contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any


HEX64_CHARS = set("0123456789abcdef")
PANEL_ARTIFACT_TYPE = "four_specialist_llm_subagent_adjudication_v1"
REQUIRED_SPECIALTIES = (
    "baseline_methodology",
    "annotation_adjudication",
    "multimodal_semantics",
    "production_governance",
)
REQUIRED_PROFESSIONAL_ROLES = {
    "baseline_methodology": "external_baseline_methodologist",
    "annotation_adjudication": "annotation_adjudication_protocol_specialist",
    "multimodal_semantics": "multimodal_semantics_validation_specialist",
    "production_governance": "production_governance_adapter_specialist",
}
PANEL_ALLOWED_FIELDS = {
    "artifact_type",
    "panel_id",
    "adjudication_target",
    "completed",
    "final_decision",
    "human_adjudication_claimed",
    "input_artifact_sha256s",
    "rubric_sha256",
    "specialist_subagents",
    "panel_decision_sha256",
}
SUBAGENT_ALLOWED_FIELDS = {
    "subagent_id",
    "specialty",
    "professional_role",
    "model_name",
    "model_version",
    "prompt_sha256",
    "rubric_sha256",
    "run_id",
    "temperature",
    "independent",
    "decision",
    "blocking_findings",
    "reviewed_artifact_sha256s",
    "output_sha256",
}


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def strong_hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in HEX64_CHARS for char in value)
        and len(set(value)) > 1
    )


def panel_decision_sha256(panel: dict[str, Any]) -> str:
    """Return the stable hash that binds a panel's final decision rows."""

    subagents = panel.get("specialist_subagents")
    if not isinstance(subagents, list):
        subagents = []
    normalized_subagents = []
    for row in subagents:
        if not isinstance(row, dict):
            continue
        normalized_subagents.append(
            {
                "subagent_id": row.get("subagent_id"),
                "specialty": row.get("specialty"),
                "prompt_sha256": row.get("prompt_sha256"),
                "run_id": row.get("run_id"),
                "decision": row.get("decision"),
                "output_sha256": row.get("output_sha256"),
                "reviewed_artifact_sha256s": sorted(row.get("reviewed_artifact_sha256s", []))
                if isinstance(row.get("reviewed_artifact_sha256s"), list)
                else row.get("reviewed_artifact_sha256s"),
            }
        )
    return sha256_json(
        {
            "adjudication_target": panel.get("adjudication_target"),
            "final_decision": panel.get("final_decision"),
            "input_artifact_sha256s": sorted(panel.get("input_artifact_sha256s", []))
            if isinstance(panel.get("input_artifact_sha256s"), list)
            else panel.get("input_artifact_sha256s"),
            "specialist_subagents": sorted(
                normalized_subagents,
                key=lambda row: str(row.get("specialty")),
            ),
        }
    )


def validate_four_specialist_panel(
    panel: object,
    blockers: list[str],
    *,
    label: str,
    expected_target: str,
    expected_input_sha256s: list[str] | tuple[str, ...] | None = None,
) -> None:
    """Validate that a panel contains exactly four professional PASS decisions."""

    if not isinstance(panel, dict):
        blockers.append(f"{label} four-specialist LLM subagent panel missing")
        return
    unsupported_fields = sorted(set(panel) - PANEL_ALLOWED_FIELDS)
    if unsupported_fields:
        blockers.append(
            f"{label} four-specialist LLM panel has unsupported fields: "
            + ", ".join(unsupported_fields)
        )
    if panel.get("artifact_type") != PANEL_ARTIFACT_TYPE:
        blockers.append(f"{label} four-specialist LLM panel artifact type mismatch")
    if not isinstance(panel.get("panel_id"), str) or not panel["panel_id"]:
        blockers.append(f"{label} four-specialist LLM panel id missing")
    if panel.get("adjudication_target") != expected_target:
        blockers.append(f"{label} four-specialist LLM panel target mismatch")
    if panel.get("completed") is not True:
        blockers.append(f"{label} four-specialist LLM panel is not complete")
    if panel.get("final_decision") != "PASS":
        blockers.append(f"{label} four-specialist LLM panel final decision is not PASS")
    if panel.get("human_adjudication_claimed") is not False:
        blockers.append(f"{label} four-specialist LLM panel must not claim human adjudication")
    if not strong_hex64(panel.get("rubric_sha256")):
        blockers.append(f"{label} four-specialist LLM panel rubric hash missing")

    input_hashes = panel.get("input_artifact_sha256s")
    if (
        not isinstance(input_hashes, list)
        or not input_hashes
        or not all(strong_hex64(value) for value in input_hashes)
    ):
        blockers.append(f"{label} four-specialist LLM panel input artifact hashes missing")
        input_hashes = []
    if expected_input_sha256s is not None and sorted(input_hashes) != sorted(
        expected_input_sha256s
    ):
        blockers.append(f"{label} four-specialist LLM panel input artifact binding mismatch")

    subagents = panel.get("specialist_subagents")
    if not isinstance(subagents, list) or len(subagents) != len(REQUIRED_SPECIALTIES):
        blockers.append(f"{label} four-specialist LLM panel must include exactly four subagents")
        subagents = []
    specialties: set[str] = set()
    subagent_ids: set[str] = set()
    run_ids: set[str] = set()
    prompt_hashes: set[str] = set()
    output_hashes: set[str] = set()
    for row in subagents:
        if not isinstance(row, dict):
            blockers.append(f"{label} four-specialist LLM subagent row is not an object")
            continue
        unsupported_row_fields = sorted(set(row) - SUBAGENT_ALLOWED_FIELDS)
        if unsupported_row_fields:
            blockers.append(
                f"{label} four-specialist LLM subagent has unsupported fields: "
                + ", ".join(unsupported_row_fields)
            )
        subagent_id = row.get("subagent_id")
        if not isinstance(subagent_id, str) or not subagent_id:
            blockers.append(f"{label} four-specialist LLM subagent id missing")
        elif subagent_id in subagent_ids:
            blockers.append(f"{label} four-specialist LLM subagent ids are not distinct")
        else:
            subagent_ids.add(subagent_id)
        specialty = row.get("specialty")
        if specialty in REQUIRED_SPECIALTIES:
            specialties.add(specialty)
        else:
            blockers.append(f"{label} four-specialist LLM subagent specialty invalid")
        professional_role = row.get("professional_role")
        if not isinstance(professional_role, str) or not professional_role:
            blockers.append(f"{label} four-specialist LLM subagent professional_role missing")
        elif (
            specialty in REQUIRED_PROFESSIONAL_ROLES
            and professional_role != REQUIRED_PROFESSIONAL_ROLES[specialty]
        ):
            blockers.append(f"{label} four-specialist LLM subagent professional role mismatch")
        for field in ("model_name", "model_version"):
            if not isinstance(row.get(field), str) or not row[field]:
                blockers.append(f"{label} four-specialist LLM subagent {field} missing")
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            blockers.append(f"{label} four-specialist LLM subagent run_id missing")
        elif run_id in run_ids:
            blockers.append(f"{label} four-specialist LLM subagent run_ids are not distinct")
        else:
            run_ids.add(run_id)
        for field in ("prompt_sha256", "rubric_sha256", "output_sha256"):
            if not strong_hex64(row.get(field)):
                blockers.append(f"{label} four-specialist LLM subagent {field} missing")
        prompt_hash = row.get("prompt_sha256")
        if strong_hex64(prompt_hash):
            if prompt_hash in prompt_hashes:
                blockers.append(
                    f"{label} four-specialist LLM subagent prompt hashes are not distinct"
                )
            else:
                prompt_hashes.add(prompt_hash)
        output_hash = row.get("output_sha256")
        if strong_hex64(output_hash):
            if output_hash in output_hashes:
                blockers.append(
                    f"{label} four-specialist LLM subagent output hashes are not distinct"
                )
            else:
                output_hashes.add(output_hash)
        if row.get("rubric_sha256") != panel.get("rubric_sha256"):
            blockers.append(f"{label} four-specialist LLM subagent rubric binding mismatch")
        temperature = row.get("temperature")
        if (
            not isinstance(temperature, int | float)
            or isinstance(temperature, bool)
            or temperature < 0
            or temperature > 1
        ):
            blockers.append(f"{label} four-specialist LLM subagent temperature invalid")
        if row.get("independent") is not True:
            blockers.append(f"{label} four-specialist LLM subagent is not independent")
        if row.get("decision") != "PASS":
            blockers.append(f"{label} four-specialist LLM subagent decision is not PASS")
        blockers_field = row.get("blocking_findings")
        if blockers_field != []:
            blockers.append(f"{label} four-specialist LLM subagent has blocking findings")
        reviewed_hashes = row.get("reviewed_artifact_sha256s")
        if (
            not isinstance(reviewed_hashes, list)
            or not reviewed_hashes
            or not all(strong_hex64(value) for value in reviewed_hashes)
        ):
            blockers.append(f"{label} four-specialist LLM subagent reviewed hashes missing")
        elif expected_input_sha256s is not None and sorted(reviewed_hashes) != sorted(
            expected_input_sha256s
        ):
            blockers.append(f"{label} four-specialist LLM subagent reviewed hash mismatch")
    if specialties != set(REQUIRED_SPECIALTIES):
        blockers.append(f"{label} four-specialist LLM panel specialty coverage mismatch")
    if panel.get("panel_decision_sha256") != panel_decision_sha256(panel):
        blockers.append(f"{label} four-specialist LLM panel decision hash mismatch")
