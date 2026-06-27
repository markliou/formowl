from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Sequence

from formowl_contract import (
    CandidateAtom,
    CandidateRelation,
    ContractValidationError,
    to_plain,
)

from .storage import CandidateAtomStore, CandidateRelationStore

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RAW_REFERENCE_PATTERNS = (
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://"),
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"(^|[^A-Za-z0-9_])/[^\s:]+"),
    re.compile(r"\\\\"),
)
_RELATIVE_FILE_REFERENCE_PATTERN = re.compile(
    r"(?i)(^|[\s:'\"([{`])"
    r"(?:\.{1,2}[\\/])?"
    r"(?:[^\\/\s:'\"()]+[\\/])+"
    r"[^\\/\s:'\"()]+(?:\.[A-Za-z0-9]{1,12})?"
    r"($|[\s'\"\])},;:`])"
)
_DOT_RELATIVE_FILE_REFERENCE_PATTERN = re.compile(
    r"(?i)(^|[\s:'\"([{`])"
    r"\.{1,2}\\[^\\/\s:'\"()]+(?:\.[A-Za-z0-9]{1,12})?"
    r"($|[\s'\"\])},;:`])"
)
_POSIX_DOT_RELATIVE_FILE_REFERENCE_PATTERN = re.compile(
    r"(?i)(^|[\s:'\"([{`])"
    r"\.{1,2}/[^\\/\s:'\"()]+(?:\.[A-Za-z0-9]{1,12})?"
    r"($|[\s'\"\])},;:`])"
)
_LOW_CONFIDENCE_THRESHOLD = 0.75
_ATOM_PENDING_REVIEW_ACTIONS = ("approve", "reject", "defer", "split", "merge")
_RELATION_PENDING_REVIEW_ACTIONS = ("approve", "reject", "defer")
_CLOSED_REVIEW_ACTIONS = ("reopen_review",)


@dataclass(frozen=True)
class CandidatePreviewItem:
    item_type: str
    candidate_id: str
    candidate_type: str
    label: str | None
    status: str
    requires_review: bool
    confidence: float
    provenance: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    review_actions: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "item_type": self.item_type,
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "label": self.label,
            "status": self.status,
            "requires_review": self.requires_review,
            "confidence": self.confidence,
            "provenance": to_plain(self.provenance),
            "warnings": list(self.warnings),
            "review_actions": list(self.review_actions),
            "properties": to_plain(self.properties),
        }
        _validate_preview_payload(data)
        return data


@dataclass(frozen=True)
class CandidatePreviewResult:
    items: list[CandidatePreviewItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
        }
        _validate_preview_payload(data)
        return data


def preview_candidates(
    *,
    candidate_atom_store: CandidateAtomStore,
    candidate_relation_store: CandidateRelationStore | None = None,
    candidate_atom_ids: Sequence[str] | None = None,
    candidate_relation_ids: Sequence[str] | None = None,
) -> CandidatePreviewResult:
    atom_filter = _normalize_filter_ids(candidate_atom_ids, "candidate_atom_ids")
    relation_filter = _normalize_filter_ids(candidate_relation_ids, "candidate_relation_ids")
    if relation_filter is not None and candidate_relation_store is None:
        raise ContractValidationError(
            "candidate_relation_store is required when candidate_relation_ids are provided"
        )

    warnings: list[str] = []
    filters_active = atom_filter is not None or relation_filter is not None
    atoms = (
        _load_atoms(candidate_atom_store, atom_filter, warnings)
        if atom_filter is not None or not filters_active
        else []
    )
    relations = (
        _load_relations(candidate_relation_store, relation_filter, warnings)
        if candidate_relation_store is not None
        and (relation_filter is not None or not filters_active)
        else []
    )

    items: list[CandidatePreviewItem] = [_atom_preview_item(atom) for atom in atoms] + [
        _relation_preview_item(relation, candidate_atom_store) for relation in relations
    ]

    # Preview output is a user-facing review surface. Validate the complete
    # payload before returning so one unsafe later item cannot leak after earlier
    # items were already accepted by the caller.
    result = CandidatePreviewResult(items=items, warnings=warnings)
    result.to_dict()
    return result


def _load_atoms(
    store: CandidateAtomStore,
    candidate_atom_ids: list[str] | None,
    warnings: list[str],
) -> list[CandidateAtom]:
    if candidate_atom_ids is None:
        return store.list()

    atoms: list[CandidateAtom] = []
    for candidate_atom_id in candidate_atom_ids:
        atom = store.get(candidate_atom_id)
        if atom is None:
            warnings.append(f"candidate_atom_not_found:{candidate_atom_id}")
            continue
        atoms.append(atom)
    return atoms


def _load_relations(
    store: CandidateRelationStore | None,
    candidate_relation_ids: list[str] | None,
    warnings: list[str],
) -> list[CandidateRelation]:
    if store is None:
        return []
    if candidate_relation_ids is None:
        return store.list()

    relations: list[CandidateRelation] = []
    for candidate_relation_id in candidate_relation_ids:
        relation = store.get(candidate_relation_id)
        if relation is None:
            warnings.append(f"candidate_relation_not_found:{candidate_relation_id}")
            continue
        relations.append(relation)
    return relations


def _atom_preview_item(atom: CandidateAtom) -> CandidatePreviewItem:
    return CandidatePreviewItem(
        item_type="candidate_atom",
        candidate_id=atom.candidate_atom_id,
        candidate_type=atom.atom_type,
        label=atom.label,
        status=atom.status,
        requires_review=atom.requires_review,
        confidence=atom.confidence,
        provenance={
            "source_observation_ids": list(atom.source_observation_ids),
            "source_semantic_metadata_ids": list(atom.source_semantic_metadata_ids),
            "extractor_run_id": atom.extractor_run_id,
            "created_at": atom.created_at,
        },
        warnings=_candidate_warnings(
            status=atom.status,
            requires_review=atom.requires_review,
            confidence=atom.confidence,
        ),
        review_actions=_review_actions(
            status=atom.status,
            pending_actions=_ATOM_PENDING_REVIEW_ACTIONS,
        ),
        properties=to_plain(atom.properties),
    )


def _relation_preview_item(
    relation: CandidateRelation,
    candidate_atom_store: CandidateAtomStore,
) -> CandidatePreviewItem:
    warnings = _candidate_warnings(
        status=relation.status,
        requires_review=relation.requires_review,
        confidence=relation.confidence,
    )
    if candidate_atom_store.get(relation.source_candidate_atom_id) is None:
        warnings.append(f"source_candidate_atom_not_found:{relation.source_candidate_atom_id}")
    if candidate_atom_store.get(relation.target_candidate_atom_id) is None:
        warnings.append(f"target_candidate_atom_not_found:{relation.target_candidate_atom_id}")

    return CandidatePreviewItem(
        item_type="candidate_relation",
        candidate_id=relation.candidate_relation_id,
        candidate_type=relation.relation_type,
        label=None,
        status=relation.status,
        requires_review=relation.requires_review,
        confidence=relation.confidence,
        provenance={
            "source_candidate_atom_id": relation.source_candidate_atom_id,
            "target_candidate_atom_id": relation.target_candidate_atom_id,
            "source_observation_ids": list(relation.source_observation_ids),
            "source_semantic_metadata_ids": list(relation.source_semantic_metadata_ids),
            "extractor_run_id": relation.extractor_run_id,
            "created_at": relation.created_at,
        },
        warnings=warnings,
        review_actions=_review_actions(
            status=relation.status,
            pending_actions=_RELATION_PENDING_REVIEW_ACTIONS,
        ),
        properties=to_plain(relation.properties),
    )


def _candidate_warnings(
    *,
    status: str,
    requires_review: bool,
    confidence: float,
) -> list[str]:
    warnings: list[str] = []
    if requires_review:
        warnings.append("requires_review")
    if confidence < _LOW_CONFIDENCE_THRESHOLD:
        warnings.append(f"low_confidence:{confidence:.2f}")
    if status != "pending_review":
        warnings.append(f"status_not_pending_review:{status}")
    return warnings


def _review_actions(*, status: str, pending_actions: Sequence[str]) -> list[str]:
    if status == "pending_review":
        return list(pending_actions)
    if status in {"approved", "rejected", "deferred"}:
        return list(_CLOSED_REVIEW_ACTIONS)
    return []


def _normalize_filter_ids(
    candidate_ids: Sequence[str] | None,
    field_name: str,
) -> list[str] | None:
    if candidate_ids is None:
        return None
    if isinstance(candidate_ids, (str, bytes)) or not isinstance(candidate_ids, Sequence):
        raise ContractValidationError(f"{field_name} must be a sequence of candidate ids")
    normalized: list[str] = []
    for candidate_id in candidate_ids:
        _validate_candidate_id(candidate_id, field_name)
        normalized.append(candidate_id)
    return normalized


def _validate_candidate_id(candidate_id: str, field_name: str) -> None:
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ContractValidationError(f"{field_name} entries must be non-empty strings")
    if not _SAFE_RECORD_ID.fullmatch(candidate_id):
        raise ContractValidationError(f"{field_name} entries must be stable record ids")


def _validate_preview_payload(payload: Any) -> None:
    _validate_no_raw_reference(payload, "candidate preview")


def _validate_no_raw_reference(value: Any, field_name: str) -> None:
    if isinstance(value, str):
        for pattern in _RAW_REFERENCE_PATTERNS:
            if pattern.search(value):
                raise ContractValidationError(
                    f"{field_name} must not contain raw paths or locators"
                )
        if _RELATIVE_FILE_REFERENCE_PATTERN.search(value):
            raise ContractValidationError(f"{field_name} must not contain raw paths or locators")
        if _DOT_RELATIVE_FILE_REFERENCE_PATTERN.search(value):
            raise ContractValidationError(f"{field_name} must not contain raw paths or locators")
        if _POSIX_DOT_RELATIVE_FILE_REFERENCE_PATTERN.search(value):
            raise ContractValidationError(f"{field_name} must not contain raw paths or locators")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_no_raw_reference(str(key), field_name)
            _validate_no_raw_reference(item, field_name)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_no_raw_reference(item, field_name)


__all__ = [
    "CandidatePreviewItem",
    "CandidatePreviewResult",
    "preview_candidates",
]
