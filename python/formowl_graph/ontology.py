"""Scoped ontology helpers for candidate-only type governance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from formowl_contract import (
    CORE_SUPERTYPE_IDS,
    ContractValidationError,
    TypeAlignmentCandidate,
    TypeDefinition,
    stable_type_alignment_candidate_id,
)

_CORE_SUPERTYPE_PARENTS = {
    "Document": "Artifact",
}


@dataclass(frozen=True)
class TypeCompatibilityDecision:
    left_core_supertype_id: str
    right_core_supertype_id: str
    compatible: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_core_supertype_id": self.left_core_supertype_id,
            "right_core_supertype_id": self.right_core_supertype_id,
            "compatible": self.compatible,
            "reason": self.reason,
        }


def core_supertypes_compatible(
    left_core_supertype_id: str,
    right_core_supertype_id: str,
) -> TypeCompatibilityDecision:
    _validate_core_supertype(left_core_supertype_id, "left_core_supertype_id")
    _validate_core_supertype(right_core_supertype_id, "right_core_supertype_id")
    if left_core_supertype_id == right_core_supertype_id:
        return TypeCompatibilityDecision(
            left_core_supertype_id=left_core_supertype_id,
            right_core_supertype_id=right_core_supertype_id,
            compatible=True,
            reason="same_core_supertype",
        )
    if _is_core_ancestor(left_core_supertype_id, right_core_supertype_id) or _is_core_ancestor(
        right_core_supertype_id,
        left_core_supertype_id,
    ):
        return TypeCompatibilityDecision(
            left_core_supertype_id=left_core_supertype_id,
            right_core_supertype_id=right_core_supertype_id,
            compatible=True,
            reason="core_supertype_ancestor_match",
        )
    return TypeCompatibilityDecision(
        left_core_supertype_id=left_core_supertype_id,
        right_core_supertype_id=right_core_supertype_id,
        compatible=False,
        reason="core_supertype_incompatible",
    )


def propose_type_alignment_candidate(
    *,
    source_type: TypeDefinition | Mapping[str, Any],
    target_type: TypeDefinition | Mapping[str, Any],
    ontology_revision_id: str,
    score_breakdown: Mapping[str, float],
    created_by: str,
    created_at: str,
    evidence_links: list[dict[str, Any]] | None = None,
) -> TypeAlignmentCandidate:
    source = _coerce_type_definition(source_type)
    target = _coerce_type_definition(target_type)
    if (source.scope_type, source.scope_id) == (target.scope_type, target.scope_id):
        raise ContractValidationError("type alignment candidates must be cross-scope")
    compatibility = core_supertypes_compatible(
        source.core_supertype_id,
        target.core_supertype_id,
    )
    if not compatibility.compatible:
        raise ContractValidationError("type alignment requires compatible core supertypes")
    score = _score_from_breakdown(score_breakdown)
    candidate_id = stable_type_alignment_candidate_id(
        source_type_id=source.type_id,
        target_type_id=target.type_id,
        source_scope_type=source.scope_type,
        source_scope_id=source.scope_id,
        target_scope_type=target.scope_type,
        target_scope_id=target.scope_id,
        ontology_revision_id=ontology_revision_id,
    )
    links = evidence_links or [
        {
            "source_candidate_ids": sorted(
                set(source.source_candidate_ids).union(target.source_candidate_ids)
            ),
            "source_observation_ids": sorted(
                set(source.source_observation_ids).union(target.source_observation_ids)
            ),
            "visible_to_requester": False,
            "summary": "Cross-scope type alignment evidence is redacted until access review.",
        }
    ]
    return TypeAlignmentCandidate(
        alignment_candidate_id=candidate_id,
        source_type_id=source.type_id,
        target_type_id=target.type_id,
        source_scope_type=source.scope_type,
        source_scope_id=source.scope_id,
        target_scope_type=target.scope_type,
        target_scope_id=target.scope_id,
        ontology_revision_id=ontology_revision_id,
        score=score,
        score_breakdown=dict(score_breakdown),
        evidence_links=links,
        status="pending_review",
        requires_review=True,
        created_at=created_at,
        created_by=created_by,
        canonical_type_write_allowed=False,
        access_grant_id=None,
        metadata={"compatibility": compatibility.to_dict()},
    )


def _coerce_type_definition(value: TypeDefinition | Mapping[str, Any]) -> TypeDefinition:
    if isinstance(value, TypeDefinition):
        return value
    return TypeDefinition.from_dict(dict(value))


def _validate_core_supertype(value: str, field_name: str) -> None:
    if value not in CORE_SUPERTYPE_IDS:
        raise ContractValidationError(f"{field_name} must be a closed core supertype")


def _is_core_ancestor(possible_ancestor: str, child: str) -> bool:
    current = child
    while current in _CORE_SUPERTYPE_PARENTS:
        current = _CORE_SUPERTYPE_PARENTS[current]
        if current == possible_ancestor:
            return True
    return False


def _score_from_breakdown(score_breakdown: Mapping[str, float]) -> float:
    if not isinstance(score_breakdown, Mapping) or not score_breakdown:
        raise ContractValidationError("score_breakdown must be a non-empty object")
    scores: list[float] = []
    for key, value in score_breakdown.items():
        if not isinstance(key, str) or not key:
            raise ContractValidationError("score_breakdown keys must be non-empty strings")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContractValidationError("score_breakdown values must be numeric")
        if not 0 <= float(value) <= 1:
            raise ContractValidationError("score_breakdown values must be between 0 and 1")
        scores.append(float(value))
    return round(sum(scores) / len(scores), 6)


__all__ = [
    "TypeCompatibilityDecision",
    "core_supertypes_compatible",
    "propose_type_alignment_candidate",
]
