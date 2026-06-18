from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Sequence

from formowl_contract import (
    CandidateAtom,
    CandidateRelation,
    ContractValidationError,
    Observation,
    now_iso,
    stable_candidate_atom_id,
)

from .storage import CandidateAtomStore, CandidateRelationStore

_GRAPH_REFERENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_TEXT_MODALITIES = {"text"}
_MARKERS = {
    "decision": "decision",
    "action": "action_item",
    "action item": "action_item",
    "risk": "risk",
    "requirement": "requirement",
    "topic": "topic",
}
_RAW_REFERENCE_PATTERNS = (
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://"),
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"(^|[^A-Za-z0-9_])/[^\s:]+"),
    re.compile(r"\\\\"),
)


@dataclass(frozen=True)
class CandidateExtractionResult:
    candidate_atoms: list[CandidateAtom] = field(default_factory=list)
    candidate_relations: list[CandidateRelation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DeterministicTextCandidateExtractor:
    """Deterministic candidate extractor for simple text fixture markers."""

    def __init__(self, *, version: str = "0.1.0") -> None:
        self._version = version

    def name(self) -> str:
        return "deterministic_text_candidate_extractor"

    def version(self) -> str:
        return self._version

    def extractor_type(self) -> str:
        return "candidate_graph"

    def supported_modalities(self) -> list[str]:
        return sorted(_TEXT_MODALITIES)

    def extract(
        self,
        observations: Sequence[Observation],
        *,
        extractor_run_id: str,
        created_at: str | None = None,
    ) -> CandidateExtractionResult:
        _validate_graph_reference_id(extractor_run_id, "extractor_run_id")
        _validate_optional_timestamp("created_at", created_at)
        validated_observations = _validate_observations(observations)
        candidate_atoms: list[CandidateAtom] = []
        warnings: list[str] = []
        candidate_created_at = created_at or now_iso()

        for observation in validated_observations:
            if observation.modality not in _TEXT_MODALITIES:
                warnings.append(f"unsupported_observation_modality:{observation.observation_id}")
                continue

            text = observation.text or ""
            if not text.strip():
                warnings.append(f"empty_text_observation:{observation.observation_id}")
                continue

            found_marker = False
            for line_number, line in enumerate(text.splitlines(), start=1):
                marker = _parse_marker_line(line)
                if marker is None:
                    continue
                found_marker = True
                marker_name, atom_type, label = marker
                if not label:
                    warnings.append(
                        f"empty_candidate_label:{observation.observation_id}:{line_number}"
                    )
                    continue
                _validate_no_raw_reference(label, "candidate label")
                candidate_atoms.append(
                    _candidate_atom(
                        observation=observation,
                        extractor_run_id=extractor_run_id,
                        atom_type=atom_type,
                        label=label,
                        marker_name=marker_name,
                        line_number=line_number,
                        source_line=line.strip(),
                        created_at=candidate_created_at,
                    )
                )

            if not found_marker:
                warnings.append(f"no_candidate_markers:{observation.observation_id}")

        if not candidate_atoms:
            warnings.append("no_candidate_atoms")
        return CandidateExtractionResult(candidate_atoms=candidate_atoms, warnings=warnings)


def extract_and_store_candidates(
    *,
    observations: Sequence[Observation],
    candidate_atom_store: CandidateAtomStore,
    extractor_run_id: str,
    extractor: DeterministicTextCandidateExtractor | None = None,
    candidate_relation_store: CandidateRelationStore | None = None,
    created_at: str | None = None,
) -> CandidateExtractionResult:
    active_extractor = extractor or DeterministicTextCandidateExtractor()
    result = active_extractor.extract(
        observations,
        extractor_run_id=extractor_run_id,
        created_at=created_at,
    )
    validated_atoms = [CandidateAtom.from_dict(atom.to_dict()) for atom in result.candidate_atoms]
    validated_relations = [
        CandidateRelation.from_dict(relation.to_dict()) for relation in result.candidate_relations
    ]

    # Validate every store id before any write so one malformed candidate cannot
    # leave earlier candidate proposals persisted without a complete extraction result.
    for atom in validated_atoms:
        candidate_atom_store.validate_candidate_atom_id(atom.candidate_atom_id)
    if validated_relations and candidate_relation_store is None:
        raise ContractValidationError("candidate_relation_store is required for relation output")
    if candidate_relation_store is not None:
        for relation in validated_relations:
            candidate_relation_store.validate_candidate_relation_id(relation.candidate_relation_id)

    for atom in validated_atoms:
        candidate_atom_store.create(atom)
    if candidate_relation_store is not None:
        for relation in validated_relations:
            candidate_relation_store.create(relation)

    return CandidateExtractionResult(
        candidate_atoms=validated_atoms,
        candidate_relations=validated_relations,
        warnings=list(result.warnings),
    )


def _candidate_atom(
    *,
    observation: Observation,
    extractor_run_id: str,
    atom_type: str,
    label: str,
    marker_name: str,
    line_number: int,
    source_line: str,
    created_at: str,
) -> CandidateAtom:
    properties = {
        "marker": marker_name,
        "source_line": source_line,
        "source_line_number": line_number,
        "source_observation_type": observation.observation_type,
    }
    candidate_atom_id = stable_candidate_atom_id(
        source_observation_ids=[observation.observation_id],
        atom_type=atom_type,
        label=label,
        properties=properties,
        extractor_run_id=extractor_run_id,
    )
    atom = CandidateAtom(
        candidate_atom_id=candidate_atom_id,
        source_observation_ids=[observation.observation_id],
        atom_type=atom_type,
        label=label,
        properties=properties,
        confidence=1.0,
        extractor_run_id=extractor_run_id,
        status="pending_review",
        requires_review=True,
        created_at=created_at,
    )
    return CandidateAtom.from_dict(atom.to_dict())


def _parse_marker_line(line: str) -> tuple[str, str, str] | None:
    marker_text, separator, label = line.partition(":")
    if not separator:
        return None
    normalized_marker = marker_text.strip().lower()
    atom_type = _MARKERS.get(normalized_marker)
    if atom_type is None:
        return None
    return normalized_marker, atom_type, label.strip()


def _validate_observations(observations: Sequence[Observation]) -> list[Observation]:
    validated = [Observation.from_dict(observation.to_dict()) for observation in observations]
    for observation in validated:
        _validate_graph_reference_id(observation.observation_id, "Observation.observation_id")
        _validate_graph_reference_id(observation.extractor_run_id, "Observation.extractor_run_id")
    return validated


def _validate_graph_reference_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    if not _GRAPH_REFERENCE_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a stable record id")


def _validate_optional_timestamp(field_name: str, value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    if value is not None:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractValidationError(f"{field_name} must be an ISO timestamp") from exc


def _validate_no_raw_reference(value: str, field_name: str) -> None:
    for pattern in _RAW_REFERENCE_PATTERNS:
        if pattern.search(value):
            raise ContractValidationError(f"{field_name} must not contain raw paths or locators")


__all__ = [
    "CandidateExtractionResult",
    "DeterministicTextCandidateExtractor",
    "extract_and_store_candidates",
]
