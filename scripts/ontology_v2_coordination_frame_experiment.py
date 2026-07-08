#!/usr/bin/env python3
"""Run the issue #28 Ontology v2 coordination-frame fixture experiment.

The experiment compares a flat current-path semantic labeling baseline against
a minimal Ontology v2 coordination-frame representation over synthetic
cross-domain email cases. It is fixture-only, candidate-only, and writes no
canonical graph/type/user-graph/wiki state.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    CandidateBusinessObject,
    CandidateFrame,
    CandidateMention,
    ContractValidationError,
    DomainPackDefinition,
    Observation,
    assert_no_public_raw_references,
    sha256_json,
    stable_candidate_business_object_id,
    stable_candidate_frame_id,
    stable_candidate_mention_id,
    stable_domain_pack_id,
    stable_observation_id,
)

REPORT_TYPE = "ontology_v2_coordination_frame_experiment"
DEFAULT_FIXTURE_PATH = ROOT / "examples" / "ontology-v2-cross-domain-email-cases.json"
DEFAULT_OUTPUT_PATH = ROOT / ".test-tmp" / "ontology-v2-coordination-frame-experiment.json"
GENERATED_AT = "2026-07-08T00:00:00+00:00"
EXTRACTOR_RUN_ID = "run_ontology_v2_coordination_fixture"
ONTOLOGY_REVISION_ID = "ontology_rev_coordination_v2_fixture_001"
WORKSPACE_ID = "workspace_issue28"
PERMISSION_SCOPE = {
    "scope_type": "workspace",
    "scope_id": WORKSPACE_ID,
    "visibility": "private",
}
COMPETENCY_QUESTION_IDS = (
    "who_requested_what",
    "who_committed_to_what",
    "what_was_decided",
    "what_is_blocked",
    "what_deadline_matters",
    "what_changed_status",
    "what_evidence_supports_frame",
    "which_domain_belongs",
    "mention_or_coordination_obligation",
    "follow_up_queue_item",
)
_TOP_LEVEL_KEYS = {"report_type", "generated_at", "metrics", "safe_outputs", "claim_boundary"}
_FORBIDDEN_TRUE_CLAIMS = {
    "supports_canonical_frame_write_claim",
    "supports_canonical_type_write_claim",
    "supports_canonical_kg_write_claim",
    "supports_user_graph_write_claim",
    "supports_wiki_projection_claim",
    "supports_raw_mail_access_claim",
    "supports_real_mail_parser_claim",
    "supports_production_ready_claim",
}
_DOMAIN_PACKS: dict[str, dict[str, Any]] = {
    "sales": {
        "business_object_types": ["Quote", "Opportunity", "CustomerRequest"],
        "frame_specializations": {
            "QuoteApproval": "Decision",
            "CustomerCommitment": "Commitment",
            "CustomerRequest": "Request",
        },
        "aliases": {"CustomerRequest": ["complaint", "customer issue"]},
    },
    "rd": {
        "business_object_types": ["FirmwareSpec", "Requirement", "Release"],
        "frame_specializations": {
            "FirmwareCapabilityQuestion": "OpenQuestion",
            "FirmwareReleaseDecision": "Decision",
        },
        "aliases": {"FirmwareSpec": ["firmware capability", "spec"]},
    },
    "warehouse": {
        "business_object_types": ["InventoryItem", "Shipment", "Stockout"],
        "frame_specializations": {
            "InventoryShortage": "Blocker",
            "ShipmentDelay": "Issue",
        },
        "aliases": {"InventoryItem": ["material", "stock"]},
    },
    "production": {
        "business_object_types": ["WorkOrder", "Batch", "LineStop"],
        "frame_specializations": {
            "LineStopIncident": "Blocker",
            "ProductionDelay": "StatusUpdate",
        },
        "aliases": {"WorkOrder": ["WO", "work order"]},
    },
    "finance": {
        "business_object_types": ["Invoice", "PaymentTerm", "CostCenter"],
        "frame_specializations": {
            "InvoiceApproval": "Decision",
            "PaymentDelay": "Issue",
        },
        "aliases": {"Invoice": ["INV", "payment issue"]},
    },
    "management": {
        "business_object_types": ["Project", "Task", "DecisionRecord"],
        "frame_specializations": {
            "LaunchDecision": "Decision",
            "DependencyReview": "Dependency",
        },
        "aliases": {"Project": ["program", "launch"]},
    },
    "project": {
        "business_object_types": ["Project", "Task", "Milestone"],
        "frame_specializations": {
            "ProjectDependency": "Dependency",
            "ProjectStatusUpdate": "StatusUpdate",
        },
        "aliases": {"Task": ["action item", "follow-up"]},
    },
}


@dataclass(frozen=True)
class ExtractedCase:
    scenario_id: str
    domains: tuple[str, ...]
    observation: Observation
    mentions: tuple[CandidateMention, ...]
    business_objects: tuple[CandidateBusinessObject, ...]
    frames: tuple[CandidateFrame, ...]
    mention_only_count: int


def run_experiment(fixture_path: Path = DEFAULT_FIXTURE_PATH) -> dict[str, Any]:
    fixture = _load_fixture(fixture_path)
    domain_packs = _build_domain_packs(fixture)
    cases = tuple(_extract_case(case) for case in fixture["cases"])
    case_rows = [_score_case(case) for case in cases]
    safe_outputs = _safe_outputs(fixture, domain_packs, cases, case_rows)
    metrics = {
        "fixture_loaded": True,
        "domain_packs_loaded": len(domain_packs) >= 5,
        "candidate_mentions_created": safe_outputs["candidate_mention_count"] > 0,
        "candidate_business_objects_created": safe_outputs["candidate_business_object_count"] > 0,
        "candidate_frames_created": safe_outputs["candidate_frame_count"] > 0,
        "compared_against_current_flat_path": True,
        "v2_improves_answerability": safe_outputs["v2_delta_answerable_count"] > 0,
        "candidate_only_boundary_respected": True,
        "canonical_side_effects_absent": True,
        "raw_leak_guard_passed": False,
    }
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": GENERATED_AT,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": _claim_boundary(),
    }
    report["metrics"]["raw_leak_guard_passed"] = _raw_leak_guard_passes(report)
    report["validation"] = validate_report(report, fixture_path)
    return report


def validate_report(
    report: Mapping[str, Any],
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, Mapping):
        return {"passed": False, "blockers": ["report must be an object"]}
    unexpected = set(report) - (_TOP_LEVEL_KEYS | {"validation"})
    if unexpected:
        blockers.append(f"unexpected top-level keys: {sorted(unexpected)}")
    if report.get("report_type") != REPORT_TYPE:
        blockers.append("report_type mismatch")
    metrics = _mapping_or_empty(report.get("metrics"), "metrics", blockers)
    safe = _mapping_or_empty(report.get("safe_outputs"), "safe_outputs", blockers)
    claim_boundary = _mapping_or_empty(report.get("claim_boundary"), "claim_boundary", blockers)
    _validate_claim_boundary(claim_boundary, blockers)
    expected_safe = _expected_safe_outputs_for_fixture(fixture_path, blockers)
    expected_questions = len(COMPETENCY_QUESTION_IDS)
    scenario_count = _integer_value(safe, "scenario_count", blockers)
    mention_only_count = _integer_value(safe, "mention_only_count", blockers)
    v1_total = _integer_value(safe, "v1_answerable_count", blockers)
    v2_total = _integer_value(safe, "v2_answerable_count", blockers)
    delta = _integer_value(safe, "v2_delta_answerable_count", blockers)
    if safe.get("competency_question_count") != expected_questions:
        blockers.append("safe_outputs.competency_question_count mismatch")
    if scenario_count is not None:
        expected_total = scenario_count * expected_questions
        if safe.get("total_question_case_count") != expected_total:
            blockers.append("safe_outputs.total_question_case_count mismatch")
    if None not in (v1_total, v2_total, delta) and v2_total - v1_total != delta:
        blockers.append("safe_outputs.v2_delta_answerable_count mismatch")
    if None not in (v1_total, v2_total) and v2_total <= v1_total:
        blockers.append("v2 must improve answerability over the flat baseline")
    if None not in (scenario_count, mention_only_count) and mention_only_count < scenario_count:
        blockers.append("safe_outputs.mention_only_count must cover every scenario")
    case_rows = safe.get("case_rows")
    if isinstance(case_rows, list):
        if scenario_count is not None and len(case_rows) != scenario_count:
            blockers.append("safe_outputs.case_rows length must match scenario_count")
        if any(_case_row_mention_only_count(row) < 1 for row in case_rows):
            blockers.append(
                "safe_outputs.case_rows must include mention-only coverage for every scenario"
            )
    else:
        blockers.append("safe_outputs.case_rows must be a list")
    if metrics.get("candidate_only_boundary_respected") is not True:
        blockers.append("candidate_only_boundary_respected must be true")
    if metrics.get("canonical_side_effects_absent") is not True:
        blockers.append("canonical_side_effects_absent must be true")
    if metrics.get("raw_leak_guard_passed") is not True:
        blockers.append("raw_leak_guard_passed must be true")
    if safe.get("domain_pack_count", 0) < 5:
        blockers.append("safe_outputs.domain_pack_count must cover at least five domains")
    if safe.get("candidate_frame_type_count", 0) < 6:
        blockers.append("safe_outputs.candidate_frame_type_count must cover coordination frames")
    if expected_safe:
        _validate_fixture_bound_hashes(safe, expected_safe, blockers)
    try:
        assert_no_public_raw_references(report, "ontology_v2_coordination_report")
    except ContractValidationError as exc:
        blockers.append(str(exc))
    return {"passed": not blockers, "blockers": blockers}


def _expected_safe_outputs_for_fixture(
    fixture_path: Path,
    blockers: list[str],
) -> Mapping[str, Any]:
    try:
        fixture = _load_fixture(fixture_path)
        domain_packs = _build_domain_packs(fixture)
        cases = tuple(_extract_case(case) for case in fixture["cases"])
        case_rows = [_score_case(case) for case in cases]
        return _safe_outputs(fixture, domain_packs, cases, case_rows)
    except (ContractValidationError, OSError, json.JSONDecodeError) as exc:
        blockers.append(f"current fixture could not be validated: {exc}")
        return {}


def _validate_fixture_bound_hashes(
    safe: Mapping[str, Any],
    expected_safe: Mapping[str, Any],
    blockers: list[str],
) -> None:
    for field_name in ("fixture_hash", "case_row_hash"):
        if safe.get(field_name) != expected_safe.get(field_name):
            blockers.append(f"safe_outputs.{field_name} must match current fixture")


def _case_row_mention_only_count(row: Any) -> int:
    if not isinstance(row, Mapping):
        return 0
    value = row.get("mention_only_count")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ContractValidationError("fixture must contain cases")
    if len(data["cases"]) < 4:
        raise ContractValidationError("fixture must contain at least four cases")
    return data


def _build_domain_packs(fixture: Mapping[str, Any]) -> tuple[DomainPackDefinition, ...]:
    fixture_domains = sorted({domain for case in fixture["cases"] for domain in case["domains"]})
    packs: list[DomainPackDefinition] = []
    for domain in fixture_domains:
        config = _DOMAIN_PACKS[domain]
        packs.append(
            DomainPackDefinition.from_dict(
                {
                    "domain_pack_id": stable_domain_pack_id(
                        domain_name=domain,
                        scope_type="workspace",
                        scope_id=WORKSPACE_ID,
                        ontology_revision_id=ONTOLOGY_REVISION_ID,
                    ),
                    "domain_name": domain,
                    "scope_type": "workspace",
                    "scope_id": WORKSPACE_ID,
                    "ontology_revision_id": ONTOLOGY_REVISION_ID,
                    "business_object_types": config["business_object_types"],
                    "frame_specializations": config["frame_specializations"],
                    "created_at": GENERATED_AT,
                    "created_by": "issue28_experiment",
                    "aliases": config["aliases"],
                    "metadata": {"pack_kind": "fixture_domain_pack"},
                }
            )
        )
    return tuple(packs)


def _extract_case(case: Mapping[str, Any]) -> ExtractedCase:
    scenario_id = str(case["scenario_id"])
    body_lines = [str(line) for line in case["body_lines"]]
    text = "\n".join(body_lines)
    observation = _observation_for_case(case, text)
    mentions: list[CandidateMention] = []
    business_objects: list[CandidateBusinessObject] = []
    frames: list[CandidateFrame] = []
    mention_only_count = 0
    for line_number, line in enumerate(body_lines, start=1):
        frame_type, slots = _parse_frame_line(line)
        evidence_span = {
            "kind": "email_body_line",
            "line_start": line_number,
            "line_end": line_number,
        }
        line_mentions = _mentions_for_slots(observation, frame_type, slots, evidence_span)
        mentions.extend(line_mentions)
        if frame_type == "Mention":
            mention_only_count += 1
            continue
        line_business_objects = _business_objects_for_slots(observation, slots, line_mentions)
        business_objects.extend(line_business_objects)
        frames.append(
            _candidate_frame(
                observation=observation,
                frame_type=frame_type,
                slots=slots,
                evidence_span=evidence_span,
                mentions=line_mentions,
                business_objects=line_business_objects,
            )
        )
    return ExtractedCase(
        scenario_id=scenario_id,
        domains=tuple(case["domains"]),
        observation=observation,
        mentions=tuple(mentions),
        business_objects=tuple(business_objects),
        frames=tuple(frames),
        mention_only_count=mention_only_count,
    )


def _observation_for_case(case: Mapping[str, Any], text: str) -> Observation:
    scenario_id = str(case["scenario_id"])
    location = {
        "source_kind": "synthetic_email",
        "scenario_id": scenario_id,
        "line_count": len(case["body_lines"]),
    }
    observation_id = stable_observation_id(
        extractor_run_id=EXTRACTOR_RUN_ID,
        observation_type="email_body_segment",
        modality="mail",
        location=location,
        asset_id=f"asset_{scenario_id}",
        text=text,
        payload={"subject_hash": sha256_json({"subject": case["subject"]})},
    )
    return Observation.from_dict(
        {
            "observation_id": observation_id,
            "extractor_run_id": EXTRACTOR_RUN_ID,
            "observation_type": "email_body_segment",
            "modality": "mail",
            "location": location,
            "confidence": 1.0,
            "permission_scope": PERMISSION_SCOPE,
            "created_at": GENERATED_AT,
            "asset_id": f"asset_{scenario_id}",
            "text": text,
            "payload": {"synthetic_case": scenario_id},
        }
    )


def _parse_frame_line(line: str) -> tuple[str, dict[str, Any]]:
    parts = [part.strip() for part in line.split("|")]
    frame_type = parts[0]
    slots: dict[str, Any] = {}
    for part in parts[1:]:
        key, separator, value = part.partition("=")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if key == "domain_hints":
            slots[key] = [item.strip() for item in value.split(",") if item.strip()]
        else:
            slots[key] = value
    return frame_type, slots


def _mentions_for_slots(
    observation: Observation,
    frame_type: str,
    slots: Mapping[str, Any],
    evidence_span: Mapping[str, Any],
) -> tuple[CandidateMention, ...]:
    mentions: list[CandidateMention] = []
    for key in ("actor", "follow_up_owner"):
        if key in slots:
            mentions.append(
                _candidate_mention(observation, "Actor", slots[key], evidence_span, key)
            )
    if "target" in slots:
        mentions.append(
            _candidate_mention(observation, "WorkObject", slots["target"], evidence_span, "target")
        )
    for key in ("deadline", "status", "changed_status", "blocker", "dependency"):
        if key in slots:
            mentions.append(
                _candidate_mention(observation, "Value", slots[key], evidence_span, key)
            )
    for domain in slots.get("domain_hints", []):
        mentions.append(
            _candidate_mention(observation, "DomainHint", domain, evidence_span, frame_type)
        )
    mentions.append(
        _candidate_mention(observation, "EvidenceSpan", frame_type, evidence_span, "frame")
    )
    return tuple(mentions)


def _candidate_mention(
    observation: Observation,
    mention_type: str,
    label: Any,
    evidence_span: Mapping[str, Any],
    slot_name: str,
) -> CandidateMention:
    label_text = str(label)
    mention_id = stable_candidate_mention_id(
        source_observation_ids=[observation.observation_id],
        mention_type=mention_type,
        label=label_text,
        evidence_span=dict(evidence_span),
        extractor_run_id=EXTRACTOR_RUN_ID,
        ontology_revision_id=ONTOLOGY_REVISION_ID,
    )
    return CandidateMention.from_dict(
        {
            "candidate_mention_id": mention_id,
            "source_observation_ids": [observation.observation_id],
            "mention_type": mention_type,
            "label": label_text,
            "normalized_value": label_text.lower().replace(" ", "_"),
            "evidence_span": dict(evidence_span),
            "confidence": 0.95,
            "extractor_run_id": EXTRACTOR_RUN_ID,
            "ontology_revision_id": ONTOLOGY_REVISION_ID,
            "status": "pending_review",
            "requires_review": True,
            "created_at": GENERATED_AT,
            "properties": {"slot_name": slot_name},
        }
    )


def _business_objects_for_slots(
    observation: Observation,
    slots: Mapping[str, Any],
    mentions: Sequence[CandidateMention],
) -> tuple[CandidateBusinessObject, ...]:
    target_mentions = [
        mention for mention in mentions if mention.properties.get("slot_name") == "target"
    ]
    if "target" not in slots or not target_mentions:
        return ()
    source_mention_ids = [mention.candidate_mention_id for mention in target_mentions]
    object_id = stable_candidate_business_object_id(
        object_type=str(slots.get("target_type", "WorkObject")),
        label=str(slots["target"]),
        source_mention_ids=source_mention_ids,
        ontology_revision_id=ONTOLOGY_REVISION_ID,
        extractor_run_id=EXTRACTOR_RUN_ID,
    )
    return (
        CandidateBusinessObject.from_dict(
            {
                "candidate_business_object_id": object_id,
                "object_type": str(slots.get("target_type", "WorkObject")),
                "label": str(slots["target"]),
                "source_mention_ids": source_mention_ids,
                "source_observation_ids": [observation.observation_id],
                "ontology_revision_id": ONTOLOGY_REVISION_ID,
                "confidence": 0.9,
                "extractor_run_id": EXTRACTOR_RUN_ID,
                "status": "pending_review",
                "requires_review": True,
                "domain_hints": list(slots.get("domain_hints", [])),
                "created_at": GENERATED_AT,
                "properties": {"source_slot": "target"},
            }
        ),
    )


def _candidate_frame(
    *,
    observation: Observation,
    frame_type: str,
    slots: Mapping[str, Any],
    evidence_span: Mapping[str, Any],
    mentions: Sequence[CandidateMention],
    business_objects: Sequence[CandidateBusinessObject],
) -> CandidateFrame:
    frame_id = stable_candidate_frame_id(
        frame_type=frame_type,
        slots=dict(slots),
        source_observation_ids=[observation.observation_id],
        ontology_revision_id=ONTOLOGY_REVISION_ID,
        extractor_run_id=EXTRACTOR_RUN_ID,
    )
    return CandidateFrame.from_dict(
        {
            "candidate_frame_id": frame_id,
            "frame_type": frame_type,
            "source_observation_ids": [observation.observation_id],
            "ontology_revision_id": ONTOLOGY_REVISION_ID,
            "slots": dict(slots),
            "evidence_span": dict(evidence_span),
            "confidence": 0.88,
            "extractor_run_id": EXTRACTOR_RUN_ID,
            "status": "pending_review",
            "requires_review": True,
            "source_mention_ids": _unique_ids(mention.candidate_mention_id for mention in mentions),
            "source_business_object_ids": _unique_ids(
                business_object.candidate_business_object_id for business_object in business_objects
            ),
            "domain_hints": list(slots.get("domain_hints", [])),
            "created_at": GENERATED_AT,
            "properties": {"representation": "ontology_v2_coordination_frame"},
        }
    )


def _score_case(case: ExtractedCase) -> dict[str, Any]:
    v1_answered = _v1_answered_questions(case)
    v2_answered = _v2_answered_questions(case)
    return {
        "scenario_id": case.scenario_id,
        "domain_count": len(set(case.domains)),
        "frame_count": len(case.frames),
        "mention_only_count": case.mention_only_count,
        "v1_answered_question_ids": sorted(v1_answered),
        "v2_answered_question_ids": sorted(v2_answered),
        "v1_answerable_count": len(v1_answered),
        "v2_answerable_count": len(v2_answered),
        "delta_answerable_count": len(v2_answered) - len(v1_answered),
    }


def _v1_answered_questions(case: ExtractedCase) -> set[str]:
    frame_types = {frame.frame_type for frame in case.frames}
    answered = {
        "what_evidence_supports_frame",
        "which_domain_belongs",
    }
    if "Decision" in frame_types:
        answered.add("what_was_decided")
    if "Blocker" in frame_types or "Risk" in frame_types:
        answered.add("what_is_blocked")
    return answered


def _v2_answered_questions(case: ExtractedCase) -> set[str]:
    frames = list(case.frames)
    answered: set[str] = set()
    if _has_frame_with_slots(frames, "Request", ("actor", "requested_action", "target")):
        answered.add("who_requested_what")
    if _has_frame_with_slots(frames, "Commitment", ("actor", "committed_action", "target")):
        answered.add("who_committed_to_what")
    if _has_frame_with_slots(frames, "Decision", ("actor", "decision", "target")):
        answered.add("what_was_decided")
    if any(
        frame.frame_type in {"Blocker", "Risk", "Dependency"}
        and ("blocker" in frame.slots or "dependency" in frame.slots)
        for frame in frames
    ):
        answered.add("what_is_blocked")
    if any("deadline" in frame.slots for frame in frames):
        answered.add("what_deadline_matters")
    if _has_frame_with_slots(frames, "StatusUpdate", ("status", "changed_status", "target")):
        answered.add("what_changed_status")
    if all(frame.evidence_span and frame.source_observation_ids for frame in frames):
        answered.add("what_evidence_supports_frame")
    if any(frame.domain_hints for frame in frames):
        answered.add("which_domain_belongs")
    if (
        any(frame.slots.get("obligation") == "coordination_obligation" for frame in frames)
        and case.mention_only_count > 0
    ):
        answered.add("mention_or_coordination_obligation")
    if any(
        frame.slots.get("follow_up_owner")
        and frame.slots.get("deadline")
        and frame.slots.get("target")
        for frame in frames
    ):
        answered.add("follow_up_queue_item")
    return answered


def _has_frame_with_slots(
    frames: Sequence[CandidateFrame],
    frame_type: str,
    required_slots: Sequence[str],
) -> bool:
    return any(
        frame.frame_type == frame_type and all(frame.slots.get(slot) for slot in required_slots)
        for frame in frames
    )


def _unique_ids(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _safe_outputs(
    fixture: Mapping[str, Any],
    domain_packs: Sequence[DomainPackDefinition],
    cases: Sequence[ExtractedCase],
    case_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    v1_total = sum(int(row["v1_answerable_count"]) for row in case_rows)
    v2_total = sum(int(row["v2_answerable_count"]) for row in case_rows)
    frame_types = sorted({frame.frame_type for case in cases for frame in case.frames})
    domains = sorted({domain for case in cases for domain in case.domains})
    return {
        "fixture_hash": sha256_json(fixture),
        "ontology_revision_id": ONTOLOGY_REVISION_ID,
        "scenario_count": len(cases),
        "domain_count": len(domains),
        "domain_pack_count": len(domain_packs),
        "competency_question_count": len(COMPETENCY_QUESTION_IDS),
        "total_question_case_count": len(cases) * len(COMPETENCY_QUESTION_IDS),
        "candidate_mention_count": sum(len(case.mentions) for case in cases),
        "candidate_business_object_count": sum(len(case.business_objects) for case in cases),
        "candidate_frame_count": sum(len(case.frames) for case in cases),
        "mention_only_count": sum(case.mention_only_count for case in cases),
        "candidate_frame_type_count": len(frame_types),
        "candidate_frame_type_hash": sha256_json(frame_types),
        "domain_hash": sha256_json(domains),
        "case_row_hash": sha256_json(case_rows),
        "case_rows": list(case_rows),
        "v1_answerable_count": v1_total,
        "v2_answerable_count": v2_total,
        "v2_delta_answerable_count": v2_total - v1_total,
        "v1_arm": "current_flat_atom_path",
        "v2_arm": "ontology_v2_coordination_frame_path",
    }


def _claim_boundary() -> dict[str, bool]:
    claims = {key: False for key in _FORBIDDEN_TRUE_CLAIMS}
    claims["supports_fixture_coordination_frame_experiment_claim"] = True
    claims["supports_competency_question_answerability_claim"] = True
    claims["container_verification_required"] = True
    return claims


def _validate_claim_boundary(claim_boundary: Mapping[str, Any], blockers: list[str]) -> None:
    for key in _FORBIDDEN_TRUE_CLAIMS:
        if claim_boundary.get(key) is not False:
            blockers.append(f"forbidden claim is not explicitly false: {key}")
    if claim_boundary.get("supports_fixture_coordination_frame_experiment_claim") is not True:
        blockers.append("fixture experiment claim must be true")
    if claim_boundary.get("supports_competency_question_answerability_claim") is not True:
        blockers.append("competency answerability claim must be true")
    if claim_boundary.get("container_verification_required") is not True:
        blockers.append("container_verification_required must be true")


def _mapping_or_empty(value: Any, field_name: str, blockers: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        blockers.append(f"{field_name} must be an object")
        return {}
    return value


def _integer_value(
    value: Mapping[str, Any],
    field_name: str,
    blockers: list[str],
) -> int | None:
    item = value.get(field_name)
    if isinstance(item, bool) or not isinstance(item, int):
        blockers.append(f"safe_outputs.{field_name} must be an integer")
        return None
    return item


def _raw_leak_guard_passes(report: Mapping[str, Any]) -> bool:
    try:
        assert_no_public_raw_references(report, "ontology_v2_coordination_report")
    except ContractValidationError:
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--validate-report", type=Path)
    args = parser.parse_args(argv)
    if args.validate_report is not None:
        report = json.loads(args.validate_report.read_text(encoding="utf-8"))
        validation = validate_report(report, args.fixture)
        payload = validation
        exit_code = 0 if validation["passed"] else 1
    else:
        payload = run_experiment(args.fixture)
        exit_code = 0 if payload["validation"]["passed"] else 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
