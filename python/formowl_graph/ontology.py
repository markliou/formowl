"""Scoped ontology helpers for candidate-only type governance."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import unicodedata
from typing import Any, Mapping

from formowl_contract import (
    CORE_SUPERTYPE_IDS,
    ContractValidationError,
    TypeAlignmentCandidate,
    TypeDefinition,
    stable_type_alignment_candidate_id,
    sha256_json,
)


def fold_property_label(label: str) -> str:
    """Lexical folding only; no synonyms, substrings or domain-specific rules."""
    return "".join(c for c in unicodedata.normalize("NFKC", label).casefold()
                   if not c.isspace() and not unicodedata.category(c).startswith("P"))


@dataclass(frozen=True)
class CandidatePropertyMapping:
    """Replaceable, unactivated governance data for offline candidate projections.

    Each alias explicitly names its property and any qualifiers. Conflicting
    aliases stay ambiguous. This format grants no canonical write or access.
    """

    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CandidatePropertyMapping":
        def invalid() -> None:
            raise ContractValidationError("invalid candidate property mapping")

        if (data.get("artifact_id") != "formowl_candidate_property_mapping_v1"
                or data.get("review_status") != "pending_review"
                or not isinstance(data.get("mapping_id"), str) or not data["mapping_id"].strip()):
            invalid()
        props = data.get("properties")
        if (not isinstance(props, list) or not props
                or any(not isinstance(p, str) or not p.strip() for p in props)
                or len(set(props)) != len(props)):
            invalid()
        document_props = data.get("document_level_properties", [])
        if (not isinstance(document_props, list) or any(p not in props for p in document_props)
                or len(set(document_props)) != len(document_props)):
            invalid()
        aliases, groups = data.get("aliases"), data.get("identity_groups", [])
        if not isinstance(aliases, list) or not isinstance(groups, list):
            invalid()
        for alias in aliases:
            if (not isinstance(alias, dict) or set(alias) != {"label", "property_id", "qualifiers"}
                    or not isinstance(alias["label"], str) or not fold_property_label(alias["label"])
                    or alias["property_id"] not in props or not isinstance(alias["qualifiers"], dict)
                    or any(not isinstance(k, str) or not isinstance(v, str) or not k or not v
                           for k, v in alias["qualifiers"].items())):
                invalid()
        names = set()
        for group in groups:
            if (not isinstance(group, dict) or set(group) != {"name", "properties"}
                    or not isinstance(group["name"], str) or not group["name"] or group["name"] in names
                    or not isinstance(group["properties"], list) or not group["properties"]
                    or any(p not in props for p in group["properties"])
                    or len(set(group["properties"])) != len(group["properties"])):
                invalid()
            names.add(group["name"])
        return cls(deepcopy(dict(data)))

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.data)

    def match(self, label: str | None) -> dict[str, Any]:
        folded = fold_property_label(label) if isinstance(label, str) else ""
        choices = {sha256_json([a["property_id"], a["qualifiers"]]): a for a in self.data["aliases"]
                   if folded and fold_property_label(a["label"]) == folded}
        if len(choices) != 1:
            return {"status": "ambiguous" if choices else "unmapped"}
        alias = next(iter(choices.values()))
        return {"status": "candidate", "property_id": alias["property_id"],
                "qualifiers": deepcopy(alias["qualifiers"])}

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


@dataclass(frozen=True)
class SoftTypeCompatibilityDecision:
    left_core_supertype_id: str
    right_core_supertype_id: str
    compatible: bool
    hard_reject: bool
    score_multiplier: float
    additive_score_adjustment: float
    maximum_additive_score_adjustment: float
    reason: str
    left_type_confidence: float
    right_type_confidence: float
    high_confidence_threshold: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_core_supertype_id": self.left_core_supertype_id,
            "right_core_supertype_id": self.right_core_supertype_id,
            "compatible": self.compatible,
            "hard_reject": self.hard_reject,
            "score_multiplier": self.score_multiplier,
            "additive_score_adjustment": self.additive_score_adjustment,
            "maximum_additive_score_adjustment": self.maximum_additive_score_adjustment,
            "reason": self.reason,
            "left_type_confidence": self.left_type_confidence,
            "right_type_confidence": self.right_type_confidence,
            "high_confidence_threshold": self.high_confidence_threshold,
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


def soft_core_supertypes_compatible(
    left_core_supertype_id: str,
    right_core_supertype_id: str,
    *,
    left_type_confidence: float,
    right_type_confidence: float,
    high_confidence_threshold: float = 0.9,
    mismatch_score_multiplier: float = 0.65,
    maximum_additive_score_adjustment: float = 0.2,
) -> SoftTypeCompatibilityDecision:
    """Capped additive type prior for noisy candidate retrieval.

    This deliberately does not replace the hard governance gate used by
    ``propose_type_alignment_candidate``. Inferred type compatibility may add
    a bounded rerank bonus, but an inferred mismatch never deletes or zeros a
    candidate. ``mismatch_score_multiplier`` remains a validated compatibility
    argument for older callers; the default retrieval decision no longer
    applies multiplicative mismatch pruning.
    """

    _validate_confidence(left_type_confidence, "left_type_confidence")
    _validate_confidence(right_type_confidence, "right_type_confidence")
    _validate_confidence(high_confidence_threshold, "high_confidence_threshold")
    _validate_confidence(mismatch_score_multiplier, "mismatch_score_multiplier")
    _validate_confidence(
        maximum_additive_score_adjustment,
        "maximum_additive_score_adjustment",
    )
    hard = core_supertypes_compatible(left_core_supertype_id, right_core_supertype_id)
    if hard.compatible:
        additive_score_adjustment = round(
            min(left_type_confidence, right_type_confidence)
            * maximum_additive_score_adjustment,
            6,
        )
        return SoftTypeCompatibilityDecision(
            left_core_supertype_id=left_core_supertype_id,
            right_core_supertype_id=right_core_supertype_id,
            compatible=True,
            hard_reject=False,
            score_multiplier=1.0,
            additive_score_adjustment=additive_score_adjustment,
            maximum_additive_score_adjustment=float(
                maximum_additive_score_adjustment
            ),
            reason=hard.reason,
            left_type_confidence=float(left_type_confidence),
            right_type_confidence=float(right_type_confidence),
            high_confidence_threshold=float(high_confidence_threshold),
        )
    high_confidence_mismatch = (
        left_type_confidence >= high_confidence_threshold
        and right_type_confidence >= high_confidence_threshold
    )
    if high_confidence_mismatch:
        return SoftTypeCompatibilityDecision(
            left_core_supertype_id=left_core_supertype_id,
            right_core_supertype_id=right_core_supertype_id,
            compatible=False,
            hard_reject=False,
            score_multiplier=1.0,
            additive_score_adjustment=0.0,
            maximum_additive_score_adjustment=float(
                maximum_additive_score_adjustment
            ),
            reason="high_confidence_core_supertype_mismatch_capped_additive_no_bonus",
            left_type_confidence=float(left_type_confidence),
            right_type_confidence=float(right_type_confidence),
            high_confidence_threshold=float(high_confidence_threshold),
        )
    return SoftTypeCompatibilityDecision(
        left_core_supertype_id=left_core_supertype_id,
        right_core_supertype_id=right_core_supertype_id,
        compatible=False,
        hard_reject=False,
        score_multiplier=1.0,
        additive_score_adjustment=0.0,
        maximum_additive_score_adjustment=float(maximum_additive_score_adjustment),
        reason="low_confidence_core_supertype_mismatch_capped_additive_no_bonus",
        left_type_confidence=float(left_type_confidence),
        right_type_confidence=float(right_type_confidence),
        high_confidence_threshold=float(high_confidence_threshold),
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


def _validate_confidence(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    if not 0 <= float(value) <= 1:
        raise ContractValidationError(f"{field_name} must be between 0 and 1")


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
    "SoftTypeCompatibilityDecision",
    "TypeCompatibilityDecision",
    "core_supertypes_compatible",
    "propose_type_alignment_candidate",
    "soft_core_supertypes_compatible",
]
