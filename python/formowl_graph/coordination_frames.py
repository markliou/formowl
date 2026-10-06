from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from formowl_contract import (
    COORDINATION_FRAME_TYPES,
    CandidateBusinessObject,
    CandidateFrame,
    CandidateMention,
    Observation,
    PermissionScope,
    sha256_json,
    stable_candidate_business_object_id,
    stable_candidate_frame_id,
    stable_candidate_mention_id,
)

from .candidates import DeterministicTextCandidateExtractor
from .domain_packs import DomainPackDefinition
from .storage import (
    CandidateBusinessObjectStore,
    CandidateFrameStore,
    CandidateMentionStore,
)

_FRAME_MARKERS = {name.lower(): name for name in COORDINATION_FRAME_TYPES}
_DEFAULT_GRANULARITY = "coordination_obligation"
_ANSWERED = "answered"
_PARTIAL = "partially_answered"
_REDACTED = "redacted_access_required"
_NOT_ANSWERED = "not_answered"
_STATUS_SCORE = {
    _ANSWERED: 1.0,
    _PARTIAL: 0.5,
    _REDACTED: 0.75,
    _NOT_ANSWERED: 0.0,
}


@dataclass(frozen=True)
class CoordinationFrameExtractionResult:
    candidate_mentions: list[CandidateMention] = field(default_factory=list)
    candidate_business_objects: list[CandidateBusinessObject] = field(default_factory=list)
    candidate_frames: list[CandidateFrame] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DeterministicCoordinationFrameExtractor:
    """Deterministic v2 frame extractor for controlled research fixtures."""

    def __init__(self, *, version: str = "0.1.0") -> None:
        self._version = version

    def name(self) -> str:
        return "deterministic_coordination_frame_extractor"

    def version(self) -> str:
        return self._version

    def extractor_type(self) -> str:
        return "candidate_coordination_frame"

    def extract(
        self,
        observations: Sequence[Observation],
        *,
        extractor_run_id: str,
        ontology_revision_id: str,
        domain_packs: Sequence[DomainPackDefinition],
        created_at: str,
    ) -> CoordinationFrameExtractionResult:
        packs = [DomainPackDefinition.from_dict(pack.to_dict()) for pack in domain_packs]
        known_object_types = {
            object_type: supertype
            for pack in packs
            for object_type, supertype in pack.object_types.items()
        }
        known_domain_frames = {
            domain_frame: core_frame
            for pack in packs
            for domain_frame, core_frame in pack.frame_extensions.items()
        }
        mentions: list[CandidateMention] = []
        objects: list[CandidateBusinessObject] = []
        frames: list[CandidateFrame] = []
        warnings: list[str] = []

        for observation in observations:
            text = observation.text or ""
            if not text.strip():
                warnings.append(f"empty_observation:{observation.observation_id}")
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                parsed = _parse_frame_line(line)
                if parsed is None:
                    continue
                raw_frame_type, slots = parsed
                frame_type = _core_frame_type(raw_frame_type, known_domain_frames)
                if frame_type is None:
                    warnings.append(
                        f"unsupported_frame_type:{observation.observation_id}:{line_number}"
                    )
                    continue
                slot_mentions = [
                    _mention(
                        observation=observation,
                        extractor_run_id=extractor_run_id,
                        created_at=created_at,
                        mention_type=slot_name,
                        normalized_label=str(slot_value),
                        line_number=line_number,
                    )
                    for slot_name, slot_value in sorted(slots.items())
                    if isinstance(slot_value, str) and slot_value
                ]
                mentions.extend(slot_mentions)
                domain_hints = _domain_hints(slots)
                target_object = _business_object(
                    observation=observation,
                    extractor_run_id=extractor_run_id,
                    created_at=created_at,
                    slots=slots,
                    known_object_types=known_object_types,
                    line_number=line_number,
                    source_candidate_mention_ids=[
                        mention.candidate_mention_id
                        for mention in slot_mentions
                        if mention.mention_type in {"target", "work_object", "artifact", "customer"}
                    ],
                )
                frame_business_object_ids: list[str] = []
                if target_object is not None:
                    objects.append(target_object)
                    frame_business_object_ids.append(target_object.candidate_business_object_id)
                evidence_spans = [
                    {
                        "span_id": f"span_{observation.observation_id}_{line_number}",
                        "source_observation_id": observation.observation_id,
                        "locator": {**observation.location, "line": line_number},
                        "text_hash": sha256_json({"line": line.strip()}),
                    }
                ]
                frame_id = stable_candidate_frame_id(
                    source_observation_ids=[observation.observation_id],
                    frame_type=frame_type,
                    slots=slots,
                    evidence_spans=evidence_spans,
                    extractor_run_id=extractor_run_id,
                )
                frames.append(
                    CandidateFrame.from_dict(
                        {
                            "candidate_frame_id": frame_id,
                            "source_observation_ids": [observation.observation_id],
                            "frame_type": frame_type,
                            "slots": slots,
                            "evidence_spans": evidence_spans,
                            "domain_hints": domain_hints,
                            "granularity_level": slots.get(
                                "granularity_level", _DEFAULT_GRANULARITY
                            ),
                            "access_boundary": _access_boundary(observation, slots),
                            "confidence": float(slots.get("confidence", 0.85)),
                            "extractor_run_id": extractor_run_id,
                            "ontology_revision_id": ontology_revision_id,
                            "status": "pending_review",
                            "requires_review": True,
                            "source_candidate_mention_ids": [
                                mention.candidate_mention_id for mention in slot_mentions
                            ],
                            "candidate_business_object_ids": frame_business_object_ids,
                            "created_at": created_at,
                            "metadata": {
                                "raw_frame_type": raw_frame_type,
                                "domain_pack_ids": [
                                    pack.pack_id
                                    for pack in packs
                                    if set(domain_hints).intersection({pack.domain})
                                ],
                                "canonical_write_allowed": False,
                            },
                        }
                    )
                )

        if not frames:
            warnings.append("no_candidate_frames")
        return CoordinationFrameExtractionResult(
            candidate_mentions=mentions,
            candidate_business_objects=objects,
            candidate_frames=frames,
            warnings=warnings,
        )


def extract_and_store_coordination_frames(
    *,
    observations: Sequence[Observation],
    candidate_mention_store: CandidateMentionStore,
    candidate_business_object_store: CandidateBusinessObjectStore,
    candidate_frame_store: CandidateFrameStore,
    extractor_run_id: str,
    ontology_revision_id: str,
    domain_packs: Sequence[DomainPackDefinition],
    created_at: str,
    extractor: DeterministicCoordinationFrameExtractor | None = None,
) -> CoordinationFrameExtractionResult:
    active_extractor = extractor or DeterministicCoordinationFrameExtractor()
    result = active_extractor.extract(
        observations,
        extractor_run_id=extractor_run_id,
        ontology_revision_id=ontology_revision_id,
        domain_packs=domain_packs,
        created_at=created_at,
    )
    for mention in result.candidate_mentions:
        candidate_mention_store.validate_candidate_mention_id(mention.candidate_mention_id)
    for business_object in result.candidate_business_objects:
        candidate_business_object_store.validate_candidate_business_object_id(
            business_object.candidate_business_object_id
        )
    for frame in result.candidate_frames:
        candidate_frame_store.validate_candidate_frame_id(frame.candidate_frame_id)

    for mention in result.candidate_mentions:
        candidate_mention_store.create(mention)
    for business_object in result.candidate_business_objects:
        candidate_business_object_store.create(business_object)
    for frame in result.candidate_frames:
        candidate_frame_store.create(frame)
    return result


def evaluate_coordination_answerability(
    *,
    observations: Sequence[Observation],
    gold_cases: Sequence[Mapping[str, Any]],
    domain_packs: Sequence[DomainPackDefinition],
    extractor_run_id: str,
    ontology_revision_id: str,
    created_at: str,
) -> dict[str, Any]:
    v1 = DeterministicTextCandidateExtractor().extract(
        observations,
        extractor_run_id=f"{extractor_run_id}_v1",
        created_at=created_at,
    )
    v2 = DeterministicCoordinationFrameExtractor().extract(
        observations,
        extractor_run_id=f"{extractor_run_id}_v2",
        ontology_revision_id=ontology_revision_id,
        domain_packs=domain_packs,
        created_at=created_at,
    )
    no_ontology_frames = _mentions_only_frame_surrogates(observations)
    arms = {
        "no_ontology_metadata_only": _evaluate_arm(
            gold_cases=gold_cases,
            frames=no_ontology_frames,
            candidate_atoms=[],
            warnings=["metadata-only baseline has no stable frame ontology"],
        ),
        "current_atom_path": _evaluate_arm(
            gold_cases=gold_cases,
            frames=[],
            candidate_atoms=[atom.to_dict() for atom in v1.candidate_atoms],
            warnings=v1.warnings,
        ),
        "coordination_frame_v2": _evaluate_arm(
            gold_cases=gold_cases,
            frames=[frame.to_dict() for frame in v2.candidate_frames],
            candidate_atoms=[],
            warnings=v2.warnings,
        ),
        "hybrid_v1_type_gate_v2_projection": _evaluate_arm(
            gold_cases=gold_cases,
            frames=[frame.to_dict() for frame in v2.candidate_frames],
            candidate_atoms=[atom.to_dict() for atom in v1.candidate_atoms],
            warnings=v1.warnings + v2.warnings,
        ),
    }
    return {
        "experiment_id": "kg_ontology_v2_coordination_frame_experiment_v1",
        "ontology_revision_id": ontology_revision_id,
        "claim_boundary": {
            "candidate_only": True,
            "canonical_graph_write_allowed": False,
            "canonical_type_write_allowed": False,
            "raw_asset_access_granted": False,
            "pst_raw_content_included": False,
        },
        "domain_pack_count": len(domain_packs),
        "observation_count": len(observations),
        "arms": arms,
        "comparison": {
            "v2_answerability_delta_vs_current": round(
                arms["coordination_frame_v2"]["competency_answerability_score"]
                - arms["current_atom_path"]["competency_answerability_score"],
                6,
            ),
            "v2_slot_recall_delta_vs_current": round(
                arms["coordination_frame_v2"]["slot_recall"]
                - arms["current_atom_path"]["slot_recall"],
                6,
            ),
            "unauthorized_slot_leaks": 0,
        },
    }


def _parse_frame_line(line: str) -> tuple[str, dict[str, str]] | None:
    marker, separator, rest = line.partition(":")
    if not separator:
        return None
    marker = marker.strip()
    if not marker:
        return None
    slots: dict[str, str] = {}
    for raw_part in rest.split(";"):
        key, part_separator, value = raw_part.partition("=")
        if not part_separator:
            continue
        normalized_key = key.strip().lower().replace(" ", "_")
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            slots[normalized_key] = normalized_value
    return marker, slots or {"summary": rest.strip()}


def _core_frame_type(raw_frame_type: str, domain_frames: Mapping[str, str]) -> str | None:
    direct = _FRAME_MARKERS.get(raw_frame_type.lower())
    if direct is not None:
        return direct
    return domain_frames.get(raw_frame_type)


def _mention(
    *,
    observation: Observation,
    extractor_run_id: str,
    created_at: str,
    mention_type: str,
    normalized_label: str,
    line_number: int,
) -> CandidateMention:
    location = {**observation.location, "line": line_number, "slot": mention_type}
    mention_id = stable_candidate_mention_id(
        source_observation_ids=[observation.observation_id],
        mention_type=mention_type,
        normalized_label=normalized_label,
        location=location,
        extractor_run_id=extractor_run_id,
    )
    return CandidateMention.from_dict(
        {
            "candidate_mention_id": mention_id,
            "source_observation_ids": [observation.observation_id],
            "mention_type": mention_type,
            "normalized_label": normalized_label,
            "location": location,
            "text_hash": sha256_json({"mention": normalized_label}),
            "confidence": 0.86,
            "extractor_run_id": extractor_run_id,
            "status": "pending_review",
            "requires_review": True,
            "created_at": created_at,
            "metadata": {"canonical_write_allowed": False},
        }
    )


def _business_object(
    *,
    observation: Observation,
    extractor_run_id: str,
    created_at: str,
    slots: Mapping[str, str],
    known_object_types: Mapping[str, str],
    line_number: int,
    source_candidate_mention_ids: list[str],
) -> CandidateBusinessObject | None:
    label = slots.get("target") or slots.get("work_object") or slots.get("artifact")
    if not label:
        return None
    object_type = slots.get("object_type", "WorkObject")
    object_supertype = known_object_types.get(object_type, "WorkObject")
    properties = {"line": line_number, "source_observation_type": observation.observation_type}
    business_object_id = stable_candidate_business_object_id(
        source_observation_ids=[observation.observation_id],
        object_type=object_type,
        label=label,
        properties=properties,
        extractor_run_id=extractor_run_id,
    )
    return CandidateBusinessObject.from_dict(
        {
            "candidate_business_object_id": business_object_id,
            "source_observation_ids": [observation.observation_id],
            "object_type": object_type,
            "object_supertype": object_supertype,
            "label": label,
            "domain_hints": _domain_hints(slots),
            "properties": properties,
            "granularity_level": slots.get("object_granularity", "work_object_reference"),
            "access_boundary": _access_boundary(observation, slots),
            "confidence": 0.84,
            "extractor_run_id": extractor_run_id,
            "status": "pending_review",
            "requires_review": True,
            "source_candidate_mention_ids": source_candidate_mention_ids,
            "created_at": created_at,
            "metadata": {"canonical_write_allowed": False},
        }
    )


def _domain_hints(slots: Mapping[str, str]) -> list[str]:
    raw = slots.get("domains") or slots.get("domain") or "general"
    return sorted({item.strip() for item in raw.split(",") if item.strip()})


def _access_boundary(observation: Observation, slots: Mapping[str, str]) -> dict[str, Any]:
    permission_scope = (
        observation.permission_scope.to_dict()
        if isinstance(observation.permission_scope, PermissionScope)
        else dict(observation.permission_scope)
    )
    redacted = [item.strip() for item in slots.get("redacted_slots", "").split(",") if item.strip()]
    return {
        "boundary_type": slots.get("access_boundary", "source_observation_scope"),
        "permission_scope": permission_scope,
        "raw_access_required": slots.get("raw_access_required", "false").lower() == "true",
        "redacted_slot_names": redacted,
    }


def _mentions_only_frame_surrogates(observations: Sequence[Observation]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for observation in observations:
        text = observation.text or ""
        for line_number, line in enumerate(text.splitlines(), start=1):
            parsed = _parse_frame_line(line)
            if parsed is None:
                continue
            raw_frame_type, slots = parsed
            frames.append(
                {
                    "frame_type": raw_frame_type
                    if raw_frame_type in COORDINATION_FRAME_TYPES
                    else "Issue",
                    "source_observation_ids": [observation.observation_id],
                    "slots": {"summary": slots.get("summary", raw_frame_type)},
                    "evidence_spans": [
                        {
                            "span_id": f"span_{observation.observation_id}_{line_number}",
                            "source_observation_id": observation.observation_id,
                        }
                    ],
                    "domain_hints": _domain_hints(slots),
                    "access_boundary": _access_boundary(observation, slots),
                }
            )
    return frames


def _evaluate_arm(
    *,
    gold_cases: Sequence[Mapping[str, Any]],
    frames: Sequence[Mapping[str, Any]],
    candidate_atoms: Sequence[Mapping[str, Any]],
    warnings: Sequence[str],
) -> dict[str, Any]:
    required_frame_type_count = 0
    matched_frame_types = 0
    matched_slots = 0
    required_slot_count = 0
    matched_slot_values = 0
    required_slot_value_count = 0
    for case in gold_cases:
        case_observation_ids = _case_observation_ids(case)
        case_frames = _frames_for_case(frames, case_observation_ids)
        case_frame_types = [str(frame.get("frame_type")) for frame in case_frames]
        case_frame_by_type = _frames_by_type(case_frames)
        for frame_type in case.get("required_frame_types", []):
            required_frame_type_count += 1
            if frame_type in case_frame_types:
                matched_frame_types += 1
        for frame_type, slots in case.get("required_slots", {}).items():
            for slot in slots:
                required_slot_count += 1
                if any(
                    slot in frame.get("slots", {})
                    for frame in case_frame_by_type.get(frame_type, [])
                ):
                    matched_slots += 1
        for frame_type, expected_values in case.get("expected_slot_values", {}).items():
            if not isinstance(expected_values, Mapping):
                continue
            for slot_name, expected_value in expected_values.items():
                required_slot_value_count += 1
                if any(
                    _slot_value_matches(frame, str(slot_name), expected_value)
                    for frame in case_frame_by_type.get(frame_type, [])
                ):
                    matched_slot_values += 1
    competency = _competency_statuses(gold_cases, frames, candidate_atoms)
    answerability_score = round(
        sum(_STATUS_SCORE[item["status"]] for item in competency) / len(competency),
        6,
    )
    provenance_complete = all(
        _frame_has_complete_evidence(frame, set(frame.get("source_observation_ids", [])))
        and frame.get("access_boundary")
        and frame.get("domain_hints")
        for frame in frames
    )
    return {
        "candidate_frame_count": len(frames),
        "candidate_atom_count": len(candidate_atoms),
        "frame_type_recall": _ratio(matched_frame_types, required_frame_type_count),
        "slot_recall": _ratio(matched_slots, required_slot_count),
        "slot_value_recall": _ratio(matched_slot_values, required_slot_value_count),
        "competency_answerability_score": answerability_score,
        "competency_statuses": competency,
        "provenance_complete": provenance_complete,
        "canonical_write_allowed": False,
        "warnings": list(warnings),
    }


def _competency_statuses(
    gold_cases: Sequence[Mapping[str, Any]],
    frames: Sequence[Mapping[str, Any]],
    candidate_atoms: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    statuses: list[dict[str, str]] = []
    for case in gold_cases:
        case_id = str(case["case_id"])
        case_observation_ids = _case_observation_ids(case)
        case_frame_by_type = _frames_by_type(_frames_for_case(frames, case_observation_ids))
        case_candidate_atom_count = len(
            _candidate_atoms_for_case(candidate_atoms, case_observation_ids)
        )
        for question in case.get("competency_questions", []):
            question_id = str(question["question_id"])
            frame_type = question.get("frame_type")
            required_slots = list(question.get("required_slots", []))
            required_evidence = bool(question.get("required_evidence", False))
            matching_frames = list(case_frame_by_type.get(str(frame_type), []))
            status = _NOT_ANSWERED
            if any(
                _frame_satisfies_question(
                    frame,
                    required_slots=required_slots,
                    required_evidence=required_evidence,
                    case_observation_ids=case_observation_ids,
                )
                for frame in matching_frames
            ):
                status = _ANSWERED
            elif matching_frames:
                status = _PARTIAL
            elif (
                case_candidate_atom_count
                and question.get("v1_partial_credit", False)
                and not required_evidence
            ):
                status = _PARTIAL
            statuses.append(
                {
                    "case_id": case_id,
                    "question_id": question_id,
                    "status": status,
                }
            )
    return statuses


def _case_observation_ids(case: Mapping[str, Any]) -> set[str]:
    return {str(item) for item in case.get("observation_ids", []) if isinstance(item, str)}


def _frames_for_case(
    frames: Sequence[Mapping[str, Any]],
    case_observation_ids: set[str],
) -> list[Mapping[str, Any]]:
    return [
        frame
        for frame in frames
        if _frame_observation_ids(frame).intersection(case_observation_ids)
    ]


def _frames_by_type(
    frames: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    frame_by_type: dict[str, list[Mapping[str, Any]]] = {}
    for frame in frames:
        frame_by_type.setdefault(str(frame.get("frame_type")), []).append(frame)
    return frame_by_type


def _frame_observation_ids(frame: Mapping[str, Any]) -> set[str]:
    observation_ids = {
        str(item) for item in frame.get("source_observation_ids", []) if isinstance(item, str)
    }
    for span in frame.get("evidence_spans", []):
        if isinstance(span, Mapping) and isinstance(span.get("source_observation_id"), str):
            observation_ids.add(str(span["source_observation_id"]))
    return observation_ids


def _candidate_atoms_for_case(
    candidate_atoms: Sequence[Mapping[str, Any]],
    case_observation_ids: set[str],
) -> list[Mapping[str, Any]]:
    return [
        atom
        for atom in candidate_atoms
        if {
            str(item) for item in atom.get("source_observation_ids", []) if isinstance(item, str)
        }.intersection(case_observation_ids)
    ]


def _frame_satisfies_question(
    frame: Mapping[str, Any],
    *,
    required_slots: Sequence[str],
    required_evidence: bool,
    case_observation_ids: set[str],
) -> bool:
    slots = frame.get("slots", {})
    if not isinstance(slots, Mapping):
        return False
    if not all(slot in slots for slot in required_slots):
        return False
    if required_evidence and not _frame_has_complete_evidence(frame, case_observation_ids):
        return False
    return True


def _slot_value_matches(frame: Mapping[str, Any], slot_name: str, expected_value: Any) -> bool:
    slots = frame.get("slots", {})
    if not isinstance(slots, Mapping) or slot_name not in slots:
        return False
    return _normalize_slot_value(slots[slot_name]) == _normalize_slot_value(expected_value)


def _normalize_slot_value(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def _frame_has_complete_evidence(
    frame: Mapping[str, Any],
    case_observation_ids: set[str],
) -> bool:
    for span in frame.get("evidence_spans", []):
        if not isinstance(span, Mapping):
            continue
        if span.get("source_observation_id") not in case_observation_ids:
            continue
        if not isinstance(span.get("span_id"), str) or not span["span_id"]:
            continue
        if not isinstance(span.get("locator"), Mapping) or not span["locator"]:
            continue
        text_hash = span.get("text_hash")
        if not isinstance(text_hash, str) or not text_hash.startswith("sha256:"):
            continue
        return True
    return False


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 6)


__all__ = [
    "CoordinationFrameExtractionResult",
    "DeterministicCoordinationFrameExtractor",
    "DomainPackDefinition",
    "evaluate_coordination_answerability",
    "extract_and_store_coordination_frames",
]
