"""Private structured-answer gold contracts and deterministic usefulness scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from typing import Any, Callable, Literal, Mapping, Sequence

from formowl_contract import ContractValidationError, to_plain


AnswerOutcome = Literal["answerable", "no_match", "permission_denied"]
LifecycleState = Literal["open", "resolved", "reopened", "superseded"]
DeadlineDisclosure = Literal["explicit", "missing", "not_applicable"]
_OUTCOMES = {"answerable", "no_match", "permission_denied"}
_LIFECYCLE_STATES = {"open", "resolved", "reopened", "superseded"}
_DEADLINE_DISCLOSURES = {"explicit", "missing", "not_applicable"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


@dataclass(frozen=True)
class GoldCitation:
    citation_id: str
    evidence_id: str
    supported_claim_ids: tuple[str, ...]
    excerpt_hash: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    case_scope_id: str | None = None
    thread_id: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.citation_id, "GoldCitation.citation_id")
        _require_id(self.evidence_id, "GoldCitation.evidence_id")
        _require_unique_ids(self.supported_claim_ids, "GoldCitation.supported_claim_ids")
        if not self.supported_claim_ids:
            raise ContractValidationError("GoldCitation.supported_claim_ids is required")
        _optional_text(self.excerpt_hash, "GoldCitation.excerpt_hash")
        _optional_id(self.case_scope_id, "GoldCitation.case_scope_id")
        _optional_id(self.thread_id, "GoldCitation.thread_id")
        _temporal_window(self.valid_from, self.valid_to, "GoldCitation")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> GoldCitation:
        return cls(
            citation_id=_required_string(payload, "citation_id"),
            evidence_id=_required_string(payload, "evidence_id"),
            supported_claim_ids=_string_tuple(payload.get("supported_claim_ids", ())),
            excerpt_hash=_optional_string(payload.get("excerpt_hash")),
            valid_from=_optional_string(payload.get("valid_from")),
            valid_to=_optional_string(payload.get("valid_to")),
            case_scope_id=_optional_string(payload.get("case_scope_id")),
            thread_id=_optional_string(payload.get("thread_id")),
        )


@dataclass(frozen=True)
class GoldFact:
    claim_id: str
    text: str
    citation_ids: tuple[str, ...]
    valid_from: str | None = None
    valid_to: str | None = None
    case_scope_id: str | None = None
    thread_id: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.claim_id, "GoldFact.claim_id")
        _require_text(self.text, "GoldFact.text")
        _require_unique_ids(self.citation_ids, "GoldFact.citation_ids")
        if not self.citation_ids:
            raise ContractValidationError("GoldFact.citation_ids is required")
        _optional_id(self.case_scope_id, "GoldFact.case_scope_id")
        _optional_id(self.thread_id, "GoldFact.thread_id")
        _temporal_window(self.valid_from, self.valid_to, "GoldFact")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> GoldFact:
        return cls(
            claim_id=_required_string(payload, "claim_id"),
            text=_required_string(payload, "text"),
            citation_ids=_string_tuple(payload.get("citation_ids", ())),
            valid_from=_optional_string(payload.get("valid_from")),
            valid_to=_optional_string(payload.get("valid_to")),
            case_scope_id=_optional_string(payload.get("case_scope_id")),
            thread_id=_optional_string(payload.get("thread_id")),
        )


@dataclass(frozen=True)
class GoldAction(GoldFact):
    responsible_party_claim_ids: tuple[str, ...] = ()
    deadline_claim_ids: tuple[str, ...] = ()
    dependency_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_unique_ids(
            self.responsible_party_claim_ids,
            "GoldAction.responsible_party_claim_ids",
        )
        _require_unique_ids(self.deadline_claim_ids, "GoldAction.deadline_claim_ids")
        _require_unique_ids(self.dependency_claim_ids, "GoldAction.dependency_claim_ids")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> GoldAction:
        return cls(
            claim_id=_required_string(payload, "claim_id"),
            text=_required_string(payload, "text"),
            citation_ids=_string_tuple(payload.get("citation_ids", ())),
            valid_from=_optional_string(payload.get("valid_from")),
            valid_to=_optional_string(payload.get("valid_to")),
            case_scope_id=_optional_string(payload.get("case_scope_id")),
            thread_id=_optional_string(payload.get("thread_id")),
            responsible_party_claim_ids=_string_tuple(
                payload.get("responsible_party_claim_ids", ())
            ),
            deadline_claim_ids=_string_tuple(payload.get("deadline_claim_ids", ())),
            dependency_claim_ids=_string_tuple(payload.get("dependency_claim_ids", ())),
        )


@dataclass(frozen=True)
class LifecycleBinding:
    binding_id: str
    subject_claim_id: str
    state: LifecycleState
    valid_from: str
    citation_ids: tuple[str, ...]
    valid_to: str | None = None
    superseded_by: str | None = None
    resolved_by: str | None = None
    reopened_by: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.binding_id, "LifecycleBinding.binding_id")
        _require_id(self.subject_claim_id, "LifecycleBinding.subject_claim_id")
        if self.state not in _LIFECYCLE_STATES:
            raise ContractValidationError("LifecycleBinding.state is invalid")
        _require_unique_ids(self.citation_ids, "LifecycleBinding.citation_ids")
        if not self.citation_ids:
            raise ContractValidationError("LifecycleBinding.citation_ids is required")
        _temporal_window(self.valid_from, self.valid_to, "LifecycleBinding")
        for field_name, value in (
            ("superseded_by", self.superseded_by),
            ("resolved_by", self.resolved_by),
            ("reopened_by", self.reopened_by),
        ):
            if value is not None:
                _require_id(value, f"LifecycleBinding.{field_name}")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LifecycleBinding:
        return cls(
            binding_id=_required_string(payload, "binding_id"),
            subject_claim_id=_required_string(payload, "subject_claim_id"),
            state=_required_string(payload, "state"),  # type: ignore[arg-type]
            valid_from=_required_string(payload, "valid_from"),
            valid_to=_optional_string(payload.get("valid_to")),
            superseded_by=_optional_string(payload.get("superseded_by")),
            resolved_by=_optional_string(payload.get("resolved_by")),
            reopened_by=_optional_string(payload.get("reopened_by")),
            citation_ids=_string_tuple(payload.get("citation_ids", ())),
        )


@dataclass(frozen=True)
class PrivateStructuredAnswerGold:
    case_id: str
    outcome: AnswerOutcome
    case_scope_id: str | None = None
    thread_ids: tuple[str, ...] = ()
    latest_status: GoldFact | None = None
    open_blockers: tuple[GoldFact, ...] = ()
    blocker_history: tuple[GoldFact, ...] = ()
    responsible_parties: tuple[GoldFact, ...] = ()
    deadlines: tuple[GoldFact, ...] = ()
    deadline_disclosure: DeadlineDisclosure = "not_applicable"
    next_actions: tuple[GoldAction, ...] = ()
    dependencies: tuple[GoldFact, ...] = ()
    citations: tuple[GoldCitation, ...] = ()
    uncertainties: tuple[GoldFact, ...] = ()
    lifecycle_bindings: tuple[LifecycleBinding, ...] = ()

    def __post_init__(self) -> None:
        _require_id(self.case_id, "PrivateStructuredAnswerGold.case_id")
        _require_outcome(self.outcome)
        _optional_id(self.case_scope_id, "PrivateStructuredAnswerGold.case_scope_id")
        _require_unique_ids(self.thread_ids, "PrivateStructuredAnswerGold.thread_ids")
        _require_deadline_disclosure(self.deadline_disclosure)
        if self.outcome != "answerable":
            if _has_gold_content(self):
                raise ContractValidationError(
                    "no_match and permission_denied gold records must not contain answer content"
                )
            return
        if self.latest_status is None:
            raise ContractValidationError("answerable gold requires latest_status")
        claims = _gold_claims(self)
        _require_unique_values([claim.claim_id for claim in claims], "gold claim ids")
        _require_unique_values(
            [citation.citation_id for citation in self.citations], "gold citation ids"
        )
        _require_unique_values(
            [binding.binding_id for binding in self.lifecycle_bindings],
            "lifecycle binding ids",
        )
        claim_ids = {claim.claim_id for claim in claims}
        citation_ids = {citation.citation_id for citation in self.citations}
        for claim in claims:
            _require_subset(claim.citation_ids, citation_ids, f"claim {claim.claim_id} citations")
        for citation in self.citations:
            _require_subset(
                citation.supported_claim_ids,
                claim_ids,
                f"citation {citation.citation_id} supported claims",
            )
            if self.case_scope_id and citation.case_scope_id != self.case_scope_id:
                raise ContractValidationError("citation case scope does not match gold case scope")
            if self.thread_ids and citation.thread_id not in self.thread_ids:
                raise ContractValidationError("citation thread is outside gold thread scope")
        party_ids = {claim.claim_id for claim in self.responsible_parties}
        deadline_ids = {claim.claim_id for claim in self.deadlines}
        dependency_ids = {claim.claim_id for claim in self.dependencies}
        for action in self.next_actions:
            _require_subset(
                action.responsible_party_claim_ids,
                party_ids,
                f"action {action.claim_id} responsible parties",
            )
            _require_subset(
                action.deadline_claim_ids,
                deadline_ids,
                f"action {action.claim_id} deadlines",
            )
            _require_subset(
                action.dependency_claim_ids,
                dependency_ids,
                f"action {action.claim_id} dependencies",
            )
        if self.deadlines and self.deadline_disclosure != "explicit":
            raise ContractValidationError("gold with deadlines requires explicit disclosure")
        if self.next_actions and not self.deadlines and self.deadline_disclosure != "missing":
            raise ContractValidationError(
                "gold actions without deadlines require missing-deadline disclosure"
            )
        for binding in self.lifecycle_bindings:
            if binding.subject_claim_id not in claim_ids:
                raise ContractValidationError("lifecycle subject_claim_id is unknown")
            _require_subset(
                binding.citation_ids,
                citation_ids,
                f"lifecycle {binding.binding_id} citations",
            )

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PrivateStructuredAnswerGold:
        return cls(
            case_id=_required_string(payload, "case_id"),
            outcome=_required_string(payload, "outcome"),  # type: ignore[arg-type]
            case_scope_id=_optional_string(payload.get("case_scope_id")),
            thread_ids=_string_tuple(payload.get("thread_ids", ())),
            latest_status=_optional_fact(payload.get("latest_status")),
            open_blockers=_fact_tuple(payload.get("open_blockers", ())),
            blocker_history=_fact_tuple(payload.get("blocker_history", ())),
            responsible_parties=_fact_tuple(payload.get("responsible_parties", ())),
            deadlines=_fact_tuple(payload.get("deadlines", ())),
            deadline_disclosure=_deadline_disclosure_from_payload(payload),
            next_actions=_action_tuple(payload.get("next_actions", ())),
            dependencies=_fact_tuple(payload.get("dependencies", ())),
            citations=_citation_tuple(payload.get("citations", ())),
            uncertainties=_fact_tuple(payload.get("uncertainties", ())),
            lifecycle_bindings=_lifecycle_tuple(payload.get("lifecycle_bindings", ())),
        )


@dataclass(frozen=True)
class PredictedFact:
    claim_id: str
    text: str
    citation_ids: tuple[str, ...] = ()
    valid_from: str | None = None
    valid_to: str | None = None
    case_scope_id: str | None = None
    thread_id: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.claim_id, "PredictedFact.claim_id")
        _require_text(self.text, "PredictedFact.text")
        _require_unique_ids(self.citation_ids, "PredictedFact.citation_ids")
        _optional_id(self.case_scope_id, "PredictedFact.case_scope_id")
        _optional_id(self.thread_id, "PredictedFact.thread_id")
        _temporal_window(self.valid_from, self.valid_to, "PredictedFact")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PredictedFact:
        return cls(
            claim_id=_required_string(payload, "claim_id"),
            text=_required_string(payload, "text"),
            citation_ids=_string_tuple(payload.get("citation_ids", ())),
            valid_from=_optional_string(payload.get("valid_from")),
            valid_to=_optional_string(payload.get("valid_to")),
            case_scope_id=_optional_string(payload.get("case_scope_id")),
            thread_id=_optional_string(payload.get("thread_id")),
        )


@dataclass(frozen=True)
class PredictedAction(PredictedFact):
    responsible_party_claim_ids: tuple[str, ...] = ()
    deadline_claim_ids: tuple[str, ...] = ()
    dependency_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_unique_ids(
            self.responsible_party_claim_ids,
            "PredictedAction.responsible_party_claim_ids",
        )
        _require_unique_ids(self.deadline_claim_ids, "PredictedAction.deadline_claim_ids")
        _require_unique_ids(
            self.dependency_claim_ids,
            "PredictedAction.dependency_claim_ids",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PredictedAction:
        return cls(
            claim_id=_required_string(payload, "claim_id"),
            text=_required_string(payload, "text"),
            citation_ids=_string_tuple(payload.get("citation_ids", ())),
            valid_from=_optional_string(payload.get("valid_from")),
            valid_to=_optional_string(payload.get("valid_to")),
            case_scope_id=_optional_string(payload.get("case_scope_id")),
            thread_id=_optional_string(payload.get("thread_id")),
            responsible_party_claim_ids=_string_tuple(
                payload.get("responsible_party_claim_ids", ())
            ),
            deadline_claim_ids=_string_tuple(payload.get("deadline_claim_ids", ())),
            dependency_claim_ids=_string_tuple(payload.get("dependency_claim_ids", ())),
        )


@dataclass(frozen=True)
class StructuredAnswerPrediction:
    outcome: AnswerOutcome
    case_scope_id: str | None = None
    thread_ids: tuple[str, ...] = ()
    latest_status: PredictedFact | None = None
    open_blockers: tuple[PredictedFact, ...] = ()
    blocker_history: tuple[PredictedFact, ...] = ()
    responsible_parties: tuple[PredictedFact, ...] = ()
    deadlines: tuple[PredictedFact, ...] = ()
    deadline_disclosure: DeadlineDisclosure = "not_applicable"
    next_actions: tuple[PredictedAction, ...] = ()
    dependencies: tuple[PredictedFact, ...] = ()
    uncertainties: tuple[PredictedFact, ...] = ()
    lifecycle_bindings: tuple[LifecycleBinding, ...] = ()

    def __post_init__(self) -> None:
        _require_outcome(self.outcome)
        _optional_id(self.case_scope_id, "StructuredAnswerPrediction.case_scope_id")
        _require_unique_ids(self.thread_ids, "StructuredAnswerPrediction.thread_ids")
        _require_deadline_disclosure(self.deadline_disclosure)
        claims = _predicted_claims(self)
        _require_unique_values([claim.claim_id for claim in claims], "prediction claim ids")
        _require_unique_values(
            [binding.binding_id for binding in self.lifecycle_bindings],
            "prediction lifecycle binding ids",
        )
        claim_ids = {claim.claim_id for claim in claims}
        party_ids = {claim.claim_id for claim in self.responsible_parties}
        deadline_ids = {claim.claim_id for claim in self.deadlines}
        dependency_ids = {claim.claim_id for claim in self.dependencies}
        for action in self.next_actions:
            _require_subset(
                action.responsible_party_claim_ids,
                party_ids,
                f"prediction action {action.claim_id} responsible parties",
            )
            _require_subset(
                action.deadline_claim_ids,
                deadline_ids,
                f"prediction action {action.claim_id} deadlines",
            )
            _require_subset(
                action.dependency_claim_ids,
                dependency_ids,
                f"prediction action {action.claim_id} dependencies",
            )
        for binding in self.lifecycle_bindings:
            if binding.subject_claim_id not in claim_ids:
                raise ContractValidationError("prediction lifecycle subject is unknown")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StructuredAnswerPrediction:
        return cls(
            outcome=_required_string(payload, "outcome"),  # type: ignore[arg-type]
            case_scope_id=_optional_string(payload.get("case_scope_id")),
            thread_ids=_string_tuple(payload.get("thread_ids", ())),
            latest_status=(
                PredictedFact.from_dict(payload["latest_status"])
                if isinstance(payload.get("latest_status"), Mapping)
                else None
            ),
            open_blockers=tuple(
                PredictedFact.from_dict(item)
                for item in _mapping_tuple(payload.get("open_blockers", ()), "open_blockers")
            ),
            blocker_history=tuple(
                PredictedFact.from_dict(item)
                for item in _mapping_tuple(payload.get("blocker_history", ()), "blocker_history")
            ),
            responsible_parties=tuple(
                PredictedFact.from_dict(item)
                for item in _mapping_tuple(
                    payload.get("responsible_parties", ()), "responsible_parties"
                )
            ),
            deadlines=tuple(
                PredictedFact.from_dict(item)
                for item in _mapping_tuple(payload.get("deadlines", ()), "deadlines")
            ),
            deadline_disclosure=_deadline_disclosure_from_payload(payload),
            next_actions=tuple(
                PredictedAction.from_dict(item)
                for item in _mapping_tuple(payload.get("next_actions", ()), "next_actions")
            ),
            dependencies=tuple(
                PredictedFact.from_dict(item)
                for item in _mapping_tuple(payload.get("dependencies", ()), "dependencies")
            ),
            uncertainties=tuple(
                PredictedFact.from_dict(item)
                for item in _mapping_tuple(payload.get("uncertainties", ()), "uncertainties")
            ),
            lifecycle_bindings=tuple(
                LifecycleBinding.from_dict(item)
                for item in _mapping_tuple(
                    payload.get("lifecycle_bindings", ()), "lifecycle_bindings"
                )
            ),
        )


@dataclass(frozen=True)
class DimensionScore:
    matched: int
    expected: int
    predicted: int
    precision: float
    recall: float
    f1: float
    applicable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class StructuredAnswerScore:
    outcome_correct: bool
    safe_response: bool
    overall_score: float
    dimensions: dict[str, DimensionScore] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


CitationEntailmentHook = Callable[[GoldFact, PredictedFact, GoldCitation], bool]


def score_structured_answer(
    gold: PrivateStructuredAnswerGold,
    prediction: StructuredAnswerPrediction,
    *,
    citation_entailment_hook: CitationEntailmentHook | None = None,
) -> StructuredAnswerScore:
    """Score answer usefulness without reading or inferring retrieval status."""

    if gold.outcome != "answerable":
        safe = prediction.outcome == gold.outcome and not _has_prediction_content(prediction)
        safety = _binary_dimension(safe)
        return StructuredAnswerScore(
            outcome_correct=prediction.outcome == gold.outcome,
            safe_response=safe,
            overall_score=safety.f1,
            dimensions={"safe_response": safety},
        )

    if prediction.outcome != "answerable":
        dimensions = {
            name: _zero_dimension(expected)
            for name, expected in _expected_dimension_counts(gold).items()
        }
        return StructuredAnswerScore(
            outcome_correct=False,
            safe_response=False,
            overall_score=0.0,
            dimensions=dimensions,
        )

    dimensions: dict[str, DimensionScore] = {}
    claim_map: dict[str, str] = {}
    dimensions["case_thread_scope"] = _binary_dimension(
        gold.case_scope_id == prediction.case_scope_id
        and set(gold.thread_ids) == set(prediction.thread_ids)
    )
    latest = _score_fact_sequence(
        (gold.latest_status,) if gold.latest_status else (),
        (prediction.latest_status,) if prediction.latest_status else (),
        claim_map,
    )
    dimensions["latest_status"] = latest
    for name, gold_items, predicted_items in (
        ("open_blockers", gold.open_blockers, prediction.open_blockers),
        ("blocker_history", gold.blocker_history, prediction.blocker_history),
        ("responsible_parties", gold.responsible_parties, prediction.responsible_parties),
        ("deadlines", gold.deadlines, prediction.deadlines),
        ("next_actions", gold.next_actions, prediction.next_actions),
        ("dependencies", gold.dependencies, prediction.dependencies),
        ("uncertainties", gold.uncertainties, prediction.uncertainties),
    ):
        dimensions[name] = _score_fact_sequence(gold_items, predicted_items, claim_map)
    dimensions["deadline_disclosure"] = _binary_dimension(
        gold.deadline_disclosure == prediction.deadline_disclosure
    )
    dimensions["action_links"] = _score_action_links(gold, prediction, claim_map)
    dimensions["lifecycle_temporal"] = _score_lifecycle(gold, prediction, claim_map)
    dimensions["citations"] = _score_citations(
        gold,
        prediction,
        claim_map,
        citation_entailment_hook or default_citation_entailment,
    )
    applicable = [dimension.f1 for dimension in dimensions.values() if dimension.applicable]
    overall = sum(applicable) / len(applicable) if applicable else 1.0
    return StructuredAnswerScore(
        outcome_correct=True,
        safe_response=True,
        overall_score=round(overall, 6),
        dimensions=dimensions,
    )


def default_citation_entailment(
    gold_claim: GoldFact,
    predicted_claim: PredictedFact,
    gold_citation: GoldCitation,
) -> bool:
    """Default hook: citation is gold-approved for the matched claim and time window."""

    return (
        gold_claim.claim_id in gold_citation.supported_claim_ids
        and gold_citation.citation_id in predicted_claim.citation_ids
        and gold_claim.case_scope_id == predicted_claim.case_scope_id
        and gold_claim.thread_id == predicted_claim.thread_id
        and gold_citation.case_scope_id == gold_claim.case_scope_id
        and gold_citation.thread_id == gold_claim.thread_id
        and _windows_compatible(gold_claim, predicted_claim)
    )


def _score_fact_sequence(
    gold_items: Sequence[GoldFact],
    predicted_items: Sequence[PredictedFact],
    claim_map: dict[str, str],
) -> DimensionScore:
    remaining = list(gold_items)
    matched = 0
    for predicted in predicted_items:
        match_index = next(
            (
                index
                for index, gold in enumerate(remaining)
                if _normalize(gold.text) == _normalize(predicted.text)
                and _windows_compatible(gold, predicted)
            ),
            None,
        )
        if match_index is None:
            continue
        gold = remaining.pop(match_index)
        claim_map[predicted.claim_id] = gold.claim_id
        matched += 1
    return _dimension(matched, len(gold_items), len(predicted_items))


def _score_action_links(
    gold: PrivateStructuredAnswerGold,
    prediction: StructuredAnswerPrediction,
    claim_map: Mapping[str, str],
) -> DimensionScore:
    gold_by_id = {action.claim_id: action for action in gold.next_actions}
    expected = sum(
        len(action.responsible_party_claim_ids)
        + len(action.deadline_claim_ids)
        + len(action.dependency_claim_ids)
        for action in gold.next_actions
    )
    predicted_count = sum(
        len(action.responsible_party_claim_ids)
        + len(action.deadline_claim_ids)
        + len(action.dependency_claim_ids)
        for action in prediction.next_actions
    )
    matched = 0
    for action in prediction.next_actions:
        gold_action = gold_by_id.get(claim_map.get(action.claim_id, ""))
        if gold_action is None:
            continue
        mapped_parties = {claim_map.get(value) for value in action.responsible_party_claim_ids}
        mapped_deadlines = {claim_map.get(value) for value in action.deadline_claim_ids}
        mapped_dependencies = {claim_map.get(value) for value in action.dependency_claim_ids}
        matched += len(mapped_parties & set(gold_action.responsible_party_claim_ids))
        matched += len(mapped_deadlines & set(gold_action.deadline_claim_ids))
        matched += len(mapped_dependencies & set(gold_action.dependency_claim_ids))
    return _dimension(matched, expected, predicted_count)


def _score_lifecycle(
    gold: PrivateStructuredAnswerGold,
    prediction: StructuredAnswerPrediction,
    claim_map: Mapping[str, str],
) -> DimensionScore:
    expected_keys = {_lifecycle_key(binding, {}) for binding in gold.lifecycle_bindings}
    predicted_keys = {
        _lifecycle_key(binding, claim_map) for binding in prediction.lifecycle_bindings
    }
    return _dimension(
        len(expected_keys & predicted_keys),
        len(expected_keys),
        len(predicted_keys),
    )


def _score_citations(
    gold: PrivateStructuredAnswerGold,
    prediction: StructuredAnswerPrediction,
    claim_map: Mapping[str, str],
    entailment_hook: CitationEntailmentHook,
) -> DimensionScore:
    gold_claims = {claim.claim_id: claim for claim in _gold_claims(gold)}
    gold_citations = {citation.citation_id: citation for citation in gold.citations}
    expected = {
        (claim.claim_id, citation_id)
        for claim in gold_claims.values()
        for citation_id in claim.citation_ids
    }
    predicted_pairs: set[tuple[str, str]] = set()
    matched = 0
    for predicted_claim in _predicted_claims(prediction):
        gold_claim_id = claim_map.get(predicted_claim.claim_id)
        if gold_claim_id is None:
            predicted_pairs.update(
                (predicted_claim.claim_id, citation_id)
                for citation_id in predicted_claim.citation_ids
            )
            continue
        gold_claim = gold_claims[gold_claim_id]
        for citation_id in predicted_claim.citation_ids:
            pair = (gold_claim_id, citation_id)
            predicted_pairs.add(pair)
            citation = gold_citations.get(citation_id)
            if (
                pair in expected
                and citation
                and entailment_hook(gold_claim, predicted_claim, citation)
            ):
                matched += 1
    return _dimension(matched, len(expected), len(predicted_pairs))


def _lifecycle_key(
    binding: LifecycleBinding,
    claim_map: Mapping[str, str],
) -> tuple[str | None, ...]:
    subject = claim_map.get(binding.subject_claim_id, binding.subject_claim_id)
    return (
        subject,
        binding.state,
        binding.valid_from,
        binding.valid_to,
        binding.superseded_by,
        binding.resolved_by,
        binding.reopened_by,
        *sorted(binding.citation_ids),
    )


def _expected_dimension_counts(gold: PrivateStructuredAnswerGold) -> dict[str, int]:
    return {
        "case_thread_scope": 1,
        "latest_status": 1,
        "open_blockers": len(gold.open_blockers),
        "blocker_history": len(gold.blocker_history),
        "responsible_parties": len(gold.responsible_parties),
        "deadlines": len(gold.deadlines),
        "deadline_disclosure": 1,
        "next_actions": len(gold.next_actions),
        "dependencies": len(gold.dependencies),
        "uncertainties": len(gold.uncertainties),
        "action_links": sum(
            len(action.responsible_party_claim_ids)
            + len(action.deadline_claim_ids)
            + len(action.dependency_claim_ids)
            for action in gold.next_actions
        ),
        "lifecycle_temporal": len(gold.lifecycle_bindings),
        "citations": sum(len(claim.citation_ids) for claim in _gold_claims(gold)),
    }


def _dimension(matched: int, expected: int, predicted: int) -> DimensionScore:
    applicable = expected > 0 or predicted > 0
    if not applicable:
        return DimensionScore(0, 0, 0, 1.0, 1.0, 1.0, applicable=False)
    precision = matched / predicted if predicted else 0.0
    recall = matched / expected if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return DimensionScore(
        matched=matched,
        expected=expected,
        predicted=predicted,
        precision=round(precision, 6),
        recall=round(recall, 6),
        f1=round(f1, 6),
    )


def _binary_dimension(value: bool) -> DimensionScore:
    score = 1.0 if value else 0.0
    return DimensionScore(int(value), 1, 1, score, score, score)


def _zero_dimension(expected: int) -> DimensionScore:
    return _dimension(0, expected, 0)


def _gold_claims(gold: PrivateStructuredAnswerGold) -> tuple[GoldFact, ...]:
    latest = (gold.latest_status,) if gold.latest_status else ()
    return (
        latest
        + gold.open_blockers
        + gold.blocker_history
        + gold.responsible_parties
        + gold.deadlines
        + gold.next_actions
        + gold.dependencies
        + gold.uncertainties
    )


def _predicted_claims(prediction: StructuredAnswerPrediction) -> tuple[PredictedFact, ...]:
    latest = (prediction.latest_status,) if prediction.latest_status else ()
    return (
        latest
        + prediction.open_blockers
        + prediction.blocker_history
        + prediction.responsible_parties
        + prediction.deadlines
        + prediction.next_actions
        + prediction.dependencies
        + prediction.uncertainties
    )


def _has_gold_content(gold: PrivateStructuredAnswerGold) -> bool:
    return bool(
        gold.latest_status
        or gold.open_blockers
        or gold.blocker_history
        or gold.responsible_parties
        or gold.deadlines
        or gold.next_actions
        or gold.dependencies
        or gold.citations
        or gold.uncertainties
        or gold.lifecycle_bindings
    )


def _has_prediction_content(prediction: StructuredAnswerPrediction) -> bool:
    return bool(
        _predicted_claims(prediction)
        or prediction.lifecycle_bindings
        or prediction.case_scope_id
        or prediction.thread_ids
    )


def _windows_compatible(gold: GoldFact, predicted: PredictedFact) -> bool:
    return gold.valid_from == predicted.valid_from and gold.valid_to == predicted.valid_to


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _require_outcome(value: str) -> None:
    if value not in _OUTCOMES:
        raise ContractValidationError("outcome is invalid")


def _require_id(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    if not _SAFE_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a safe identifier")


def _optional_id(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_id(value, field_name)


def _require_deadline_disclosure(value: str) -> None:
    if value not in _DEADLINE_DISCLOSURES:
        raise ContractValidationError("deadline_disclosure is invalid")


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} is required")


def _optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_unique_ids(values: Sequence[str], field_name: str) -> None:
    for value in values:
        _require_id(value, field_name)
    _require_unique_values(values, field_name)


def _require_unique_values(values: Sequence[str], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ContractValidationError(f"{field_name} must be unique")


def _require_subset(values: Sequence[str], allowed: set[str], field_name: str) -> None:
    if not set(values) <= allowed:
        raise ContractValidationError(f"{field_name} contains unknown references")


def _temporal_window(valid_from: str | None, valid_to: str | None, field_name: str) -> None:
    start = _parse_timestamp(valid_from, f"{field_name}.valid_from")
    end = _parse_timestamp(valid_to, f"{field_name}.valid_to")
    if start and end and end < start:
        raise ContractValidationError(f"{field_name}.valid_to precedes valid_from")


def _parse_timestamp(value: str | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    _require_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError(f"{field_name} must include a timezone")
    if not math.isfinite(parsed.timestamp()):
        raise ContractValidationError(f"{field_name} is invalid")
    return parsed


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    _require_text(value, key)
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractValidationError("optional string field must be a string")
    return value


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractValidationError("list field must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise ContractValidationError("list field must contain strings")
    return tuple(value)


def _mapping_tuple(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractValidationError(f"{field_name} must be a list")
    if not all(isinstance(item, Mapping) for item in value):
        raise ContractValidationError(f"{field_name} entries must be objects")
    return tuple(value)


def _optional_fact(value: Any) -> GoldFact | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ContractValidationError("latest_status must be an object")
    return GoldFact.from_dict(value)


def _deadline_disclosure_from_payload(payload: Mapping[str, Any]) -> DeadlineDisclosure:
    value = payload.get("deadline_disclosure")
    if value is None:
        deadlines = payload.get("deadlines", ())
        actions = payload.get("next_actions", ())
        return "explicit" if deadlines else "missing" if actions else "not_applicable"
    if not isinstance(value, str):
        raise ContractValidationError("deadline_disclosure must be a string")
    _require_deadline_disclosure(value)
    return value  # type: ignore[return-value]


def _fact_tuple(value: Any) -> tuple[GoldFact, ...]:
    return tuple(GoldFact.from_dict(item) for item in _mapping_tuple(value, "facts"))


def _action_tuple(value: Any) -> tuple[GoldAction, ...]:
    return tuple(GoldAction.from_dict(item) for item in _mapping_tuple(value, "actions"))


def _citation_tuple(value: Any) -> tuple[GoldCitation, ...]:
    return tuple(GoldCitation.from_dict(item) for item in _mapping_tuple(value, "citations"))


def _lifecycle_tuple(value: Any) -> tuple[LifecycleBinding, ...]:
    return tuple(
        LifecycleBinding.from_dict(item) for item in _mapping_tuple(value, "lifecycle_bindings")
    )


__all__ = [
    "CitationEntailmentHook",
    "DimensionScore",
    "DeadlineDisclosure",
    "GoldAction",
    "GoldCitation",
    "GoldFact",
    "LifecycleBinding",
    "PredictedAction",
    "PredictedFact",
    "PrivateStructuredAnswerGold",
    "StructuredAnswerPrediction",
    "StructuredAnswerScore",
    "default_citation_entailment",
    "score_structured_answer",
]
