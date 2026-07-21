"""Source-neutral task understanding, evidence coverage, and answer projection."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from typing import Iterable, Mapping

from .candidate_retrieval import (
    CandidateEvidenceAccessBinding,
    CandidateEvidenceIndex,
    CandidateRetrievalResult,
)


_CARDINALITY_MODES = frozenset({"sufficient", "exact", "at_least", "all_matching"})
_ANSWERABILITY_STATES = frozenset(
    {
        "permission_denied",
        "target_not_found",
        "property_absent",
        "partial_evidence",
        "conflicting_evidence",
        "sufficient_evidence",
    }
)
_PROJECTION_FORMATS = frozenset({"narrative", "table", "list", "timeline"})
_ACCESS_REJECTION_REASONS = frozenset(
    {
        "access_binding_required",
        "invalid_access_binding",
        "no_accessible_evidence",
        "query_context_not_accessible",
        "cross_context_comparison_not_allowed",
    }
)
_PRESENTATION_TERMS = {
    "table": ("表格", "table", "tabular"),
    "list": ("條列", "清單", "list", "bullet"),
    "timeline": ("時間軸", "時序", "timeline"),
    "narrative": ("敘述", "摘要", "narrative", "summary"),
}


def _required_text(value: object, field_name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} is required")


def _required_unique_text(values: tuple[str, ...], field_name: str) -> None:
    if any(type(value) is not str or not value.strip() for value in values):
        raise ValueError(f"{field_name} must contain nonblank strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")


@dataclass(frozen=True)
class TaskAnchor:
    """One typed semantic anchor retained across conversational revisions."""

    anchor_id: str
    anchor_type: str
    value: str
    required: bool = True

    def __post_init__(self) -> None:
        _required_text(self.anchor_id, "anchor_id")
        _required_text(self.anchor_type, "anchor_type")
        _required_text(self.value, "value")
        if type(self.required) is not bool:
            raise ValueError("required must be boolean")


@dataclass(frozen=True)
class TaskConstraint:
    """A source-neutral hard constraint such as context, time, or state."""

    name: str
    operator: str
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        _required_text(self.name, "constraint name")
        _required_text(self.operator, "constraint operator")
        if not self.values:
            raise ValueError("constraint values are required")
        _required_unique_text(self.values, "constraint values")


@dataclass(frozen=True)
class EvidenceRequirement:
    """Evidence sufficiency requirements independent of display pagination."""

    requirement_id: str
    cardinality_mode: str = "sufficient"
    source_item_count: int | None = None
    requested_properties: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required_text(self.requirement_id, "requirement_id")
        if self.cardinality_mode not in _CARDINALITY_MODES:
            raise ValueError("unsupported cardinality_mode")
        if self.cardinality_mode in {"exact", "at_least"}:
            if type(self.source_item_count) is not int or self.source_item_count <= 0:
                raise ValueError(
                    "exact and at_least requirements need a positive source_item_count"
                )
        elif self.cardinality_mode == "all_matching" and self.source_item_count is not None:
            raise ValueError("all_matching must not use source_item_count")
        elif self.source_item_count is not None:
            if type(self.source_item_count) is not int or self.source_item_count <= 0:
                raise ValueError("source_item_count must be a positive integer")
        _required_unique_text(self.requested_properties, "requested_properties")


@dataclass(frozen=True)
class ProjectionSpec:
    """Presentation rules that never redefine evidence completeness."""

    output_format: str = "narrative"
    primary_fields: tuple[str, ...] = ("content",)
    secondary_fields: tuple[str, ...] = ()
    page_size: int = 10
    page_offset: int = 0
    include_citations: bool = True

    def __post_init__(self) -> None:
        if self.output_format not in _PROJECTION_FORMATS:
            raise ValueError("unsupported output_format")
        if not self.primary_fields:
            raise ValueError("primary_fields are required")
        _required_unique_text(self.primary_fields, "primary_fields")
        _required_unique_text(self.secondary_fields, "secondary_fields")
        if set(self.primary_fields) & set(self.secondary_fields):
            raise ValueError("primary_fields and secondary_fields must not overlap")
        if type(self.page_size) is not int or self.page_size <= 0:
            raise ValueError("page_size must be a positive integer")
        if type(self.page_offset) is not int or self.page_offset < 0:
            raise ValueError("page_offset must be a nonnegative integer")
        if type(self.include_citations) is not bool:
            raise ValueError("include_citations must be boolean")


@dataclass(frozen=True)
class TaskFrame:
    """Persistent task semantics separated from the latest utterance."""

    task_frame_id: str
    revision: int
    retrieval_query_text: str
    latest_utterance: str
    anchors: tuple[TaskAnchor, ...]
    hard_constraints: tuple[TaskConstraint, ...]
    evidence_requirement: EvidenceRequirement
    projection: ProjectionSpec = field(default_factory=ProjectionSpec)
    prior_task_frame_id: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.task_frame_id, "task_frame_id")
        if type(self.revision) is not int or self.revision <= 0:
            raise ValueError("revision must be a positive integer")
        _required_text(self.retrieval_query_text, "retrieval_query_text")
        _required_text(self.latest_utterance, "latest_utterance")
        anchor_ids = tuple(anchor.anchor_id for anchor in self.anchors)
        if len(set(anchor_ids)) != len(anchor_ids):
            raise ValueError("anchors must have unique anchor ids")
        constraint_names = tuple(constraint.name for constraint in self.hard_constraints)
        if len(set(constraint_names)) != len(constraint_names):
            raise ValueError("hard constraints must have unique names")
        if self.prior_task_frame_id is not None:
            _required_text(self.prior_task_frame_id, "prior_task_frame_id")


@dataclass(frozen=True)
class TaskFrameRevision:
    """Auditable revision result for a follow-up utterance."""

    previous_task_frame_id: str
    task_frame: TaskFrame
    changed_dimensions: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceField:
    """One normalized evidence field emitted by a source adapter."""

    name: str
    value: str

    def __post_init__(self) -> None:
        _required_text(self.name, "evidence field name")
        _required_text(self.value, "evidence field value")


@dataclass(frozen=True)
class TaskEvidenceObservation:
    """Presentation-neutral fields associated with one citeable observation."""

    observation_id: str
    source_identity_policy_id: str
    source_item_id: str
    fields: tuple[EvidenceField, ...]
    citation_locator: str
    assertion_key: str | None = None
    assertion_value: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.observation_id, "observation_id")
        _required_text(self.source_identity_policy_id, "source_identity_policy_id")
        _required_text(self.source_item_id, "source_item_id")
        _required_text(self.citation_locator, "citation_locator")
        field_names = tuple(field.name for field in self.fields)
        if len(set(field_names)) != len(field_names):
            raise ValueError("evidence fields must have unique names")
        if (self.assertion_key is None) != (self.assertion_value is None):
            raise ValueError("assertion_key and assertion_value must be supplied together")
        if self.assertion_key is not None:
            _required_text(self.assertion_key, "assertion_key")
            _required_text(self.assertion_value, "assertion_value")

    @property
    def source_item_key(self) -> tuple[str, str]:
        return (self.source_identity_policy_id, self.source_item_id)

    def field_value(self, name: str) -> str | None:
        return next((field.value for field in self.fields if field.name == name), None)


@dataclass(frozen=True)
class EvidenceCoverage:
    """Coverage facts computed before answer presentation."""

    target_found: bool
    total_source_item_count: int
    returned_source_item_count: int
    expected_assembled_observation_count: int
    assembled_observation_count: int
    assembly_complete: bool
    required_properties: tuple[str, ...]
    covered_properties: tuple[str, ...]
    missing_properties: tuple[str, ...]
    required_projection_fields: tuple[str, ...]
    covered_projection_fields: tuple[str, ...]
    missing_projection_fields: tuple[str, ...]
    conflicting_assertion_keys: tuple[str, ...]
    is_exhaustive: bool
    has_more: bool


@dataclass(frozen=True)
class AnswerabilityDecision:
    """Reasoned outcome distinct from retrieval rejection and UI rendering."""

    status: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in _ANSWERABILITY_STATES:
            raise ValueError("unsupported answerability status")
        _required_unique_text(self.reason_codes, "reason_codes")


@dataclass(frozen=True)
class ProjectedField:
    name: str
    value: str


@dataclass(frozen=True)
class ProjectedEvidenceItem:
    """One display item with content and metadata kept explicitly separate."""

    source_item_key: tuple[str, str]
    primary_fields: tuple[ProjectedField, ...]
    secondary_fields: tuple[ProjectedField, ...]
    citation_locators: tuple[str, ...]


@dataclass(frozen=True)
class AnswerProjection:
    """Paged presentation derived from complete retrieval and coverage facts."""

    output_format: str
    items: tuple[ProjectedEvidenceItem, ...]
    total_source_item_count: int
    returned_source_item_count: int
    displayed_source_item_count: int
    is_exhaustive: bool
    has_more: bool


@dataclass(frozen=True)
class TaskAnswer:
    task_frame: TaskFrame
    retrieval: CandidateRetrievalResult
    coverage: EvidenceCoverage
    answerability: AnswerabilityDecision
    projection: AnswerProjection


def revise_task_frame(
    prior: TaskFrame,
    utterance: str,
    *,
    anchor_updates: Iterable[TaskAnchor] = (),
    remove_anchor_ids: Iterable[str] = (),
    constraint_updates: Iterable[TaskConstraint] = (),
    remove_constraint_names: Iterable[str] = (),
    evidence_requirement: EvidenceRequirement | None = None,
    projection: ProjectionSpec | None = None,
    retrieval_query_text: str | None = None,
) -> TaskFrameRevision:
    """Revise prior semantics rather than treating a follow-up as a new search."""

    _required_text(utterance, "utterance")
    anchors_by_id = {anchor.anchor_id: anchor for anchor in prior.anchors}
    removed_anchor_ids = frozenset(remove_anchor_ids)
    anchors_by_id = {
        anchor_id: anchor
        for anchor_id, anchor in anchors_by_id.items()
        if anchor_id not in removed_anchor_ids
    }
    for anchor in anchor_updates:
        anchors_by_id[anchor.anchor_id] = anchor

    constraints_by_name = {constraint.name: constraint for constraint in prior.hard_constraints}
    removed_constraint_names = frozenset(remove_constraint_names)
    constraints_by_name = {
        name: constraint
        for name, constraint in constraints_by_name.items()
        if name not in removed_constraint_names
    }
    for constraint in constraint_updates:
        constraints_by_name[constraint.name] = constraint

    revised_projection = projection or _projection_from_follow_up(
        utterance,
        prior.projection,
    )
    revised_requirement = evidence_requirement or prior.evidence_requirement
    revised_anchors = tuple(anchors_by_id.values())
    revised_constraints = tuple(constraints_by_name.values())

    semantic_revision = (
        revised_anchors != prior.anchors
        or revised_constraints != prior.hard_constraints
        or revised_requirement != prior.evidence_requirement
    )
    if retrieval_query_text is not None:
        _required_text(retrieval_query_text, "retrieval_query_text")
        revised_query = retrieval_query_text
    elif semantic_revision and revised_anchors:
        revised_query = " ".join(anchor.value for anchor in revised_anchors)
    else:
        revised_query = prior.retrieval_query_text

    changed_dimensions: list[str] = []
    if revised_anchors != prior.anchors:
        changed_dimensions.append("anchors")
    if revised_constraints != prior.hard_constraints:
        changed_dimensions.append("hard_constraints")
    if revised_requirement != prior.evidence_requirement:
        changed_dimensions.append("evidence_requirement")
    if revised_projection != prior.projection:
        changed_dimensions.append("projection")
    if revised_query != prior.retrieval_query_text:
        changed_dimensions.append("retrieval_query")

    next_revision = prior.revision + 1
    task_frame_id = _revised_task_frame_id(
        prior.task_frame_id,
        revision=next_revision,
        utterance=utterance,
        retrieval_query_text=revised_query,
        anchors=revised_anchors,
        hard_constraints=revised_constraints,
        evidence_requirement=revised_requirement,
        projection=revised_projection,
    )
    revised = TaskFrame(
        task_frame_id=task_frame_id,
        revision=next_revision,
        retrieval_query_text=revised_query,
        latest_utterance=utterance,
        anchors=revised_anchors,
        hard_constraints=revised_constraints,
        evidence_requirement=revised_requirement,
        projection=revised_projection,
        prior_task_frame_id=prior.task_frame_id,
    )
    return TaskFrameRevision(
        previous_task_frame_id=prior.task_frame_id,
        task_frame=revised,
        changed_dimensions=tuple(changed_dimensions),
    )


class TaskAnsweringEngine:
    """Compose retrieval, evidence assembly, answerability, and projection."""

    def __init__(
        self,
        evidence_index: CandidateEvidenceIndex,
        observations: Iterable[TaskEvidenceObservation],
    ) -> None:
        if not isinstance(evidence_index, CandidateEvidenceIndex):
            raise ValueError("evidence_index must use CandidateEvidenceIndex")
        by_id: dict[str, TaskEvidenceObservation] = {}
        indexed_records = {record.observation_id: record for record in evidence_index.records}
        for observation in observations:
            if observation.observation_id in by_id:
                raise ValueError("duplicate task evidence observation id")
            indexed_record = indexed_records.get(observation.observation_id)
            if indexed_record is None:
                raise ValueError("task evidence observation must exist in the evidence index")
            if observation.source_item_key != (
                indexed_record.source_identity_policy_id,
                indexed_record.source_item_id,
            ):
                raise ValueError(
                    "task evidence observation source identity does not match the index"
                )
            by_id[observation.observation_id] = observation
        self._evidence_index = evidence_index
        self._observations = by_id

    def answer(
        self,
        task_frame: TaskFrame,
        *,
        access_binding: CandidateEvidenceAccessBinding | None = None,
        retrieval_options: Mapping[str, object] | None = None,
    ) -> TaskAnswer:
        options = dict(retrieval_options or {})
        forbidden = {
            "query_text",
            "cardinality_mode",
            "requested_source_item_count",
        } & set(options)
        if forbidden:
            raise ValueError(
                "retrieval_options must not override task semantics: "
                + ", ".join(sorted(forbidden))
            )
        constraint_options = _retrieval_options_from_constraints(task_frame.hard_constraints)
        for key, value in constraint_options.items():
            if key in options and options[key] != value:
                raise ValueError(f"retrieval_options conflict with hard constraint: {key}")
            options[key] = value
        retrieval = self._evidence_index.retrieve(
            query_text=task_frame.retrieval_query_text,
            cardinality_mode=task_frame.evidence_requirement.cardinality_mode,
            requested_source_item_count=(task_frame.evidence_requirement.source_item_count),
            access_binding=access_binding,
            **options,
        )
        assembled = tuple(
            self._observations[observation_id]
            for observation_id in retrieval.assembled_observation_ids
            if observation_id in self._observations
        )
        coverage = _build_coverage(
            task_frame.evidence_requirement,
            task_frame.projection,
            retrieval,
            assembled,
        )
        answerability = _decide_answerability(
            task_frame.evidence_requirement,
            retrieval,
            coverage,
        )
        projection = _build_projection(
            task_frame.projection,
            retrieval,
            assembled,
        )
        return TaskAnswer(
            task_frame=task_frame,
            retrieval=retrieval,
            coverage=coverage,
            answerability=answerability,
            projection=projection,
        )


def _projection_from_follow_up(
    utterance: str,
    prior: ProjectionSpec,
) -> ProjectionSpec:
    normalized = utterance.casefold()
    for output_format, terms in _PRESENTATION_TERMS.items():
        if any(term in normalized for term in terms):
            return replace(prior, output_format=output_format)
    return prior


def _retrieval_options_from_constraints(
    constraints: tuple[TaskConstraint, ...],
) -> dict[str, object]:
    options: dict[str, object] = {}
    collection_constraints = {
        "query_context_ids",
        "allowed_epistemic_statuses",
        "allowed_lifecycle_statuses",
    }
    scalar_constraints = {
        "known_as_of",
        "as_of_world_time",
        "query_timezone",
    }
    for constraint in constraints:
        if constraint.name in collection_constraints:
            if constraint.operator not in {"equals", "in"}:
                raise ValueError(
                    f"unsupported operator for {constraint.name}: " f"{constraint.operator}"
                )
            options[constraint.name] = constraint.values
        elif constraint.name in scalar_constraints:
            if constraint.operator != "equals" or len(constraint.values) != 1:
                raise ValueError(f"{constraint.name} requires one equals value")
            options[constraint.name] = constraint.values[0]
        else:
            raise ValueError(f"unsupported task hard constraint: {constraint.name}")
    return options


def _revised_task_frame_id(
    prior_task_frame_id: str,
    *,
    revision: int,
    utterance: str,
    retrieval_query_text: str,
    anchors: tuple[TaskAnchor, ...],
    hard_constraints: tuple[TaskConstraint, ...],
    evidence_requirement: EvidenceRequirement,
    projection: ProjectionSpec,
) -> str:
    payload = {
        "prior_task_frame_id": prior_task_frame_id,
        "revision": revision,
        "utterance": utterance,
        "retrieval_query_text": retrieval_query_text,
        "anchors": [
            {
                "anchor_id": anchor.anchor_id,
                "anchor_type": anchor.anchor_type,
                "value": anchor.value,
                "required": anchor.required,
            }
            for anchor in anchors
        ],
        "hard_constraints": [
            {
                "name": constraint.name,
                "operator": constraint.operator,
                "values": constraint.values,
            }
            for constraint in hard_constraints
        ],
        "evidence_requirement": {
            "requirement_id": evidence_requirement.requirement_id,
            "cardinality_mode": evidence_requirement.cardinality_mode,
            "source_item_count": evidence_requirement.source_item_count,
            "requested_properties": evidence_requirement.requested_properties,
        },
        "projection": {
            "output_format": projection.output_format,
            "primary_fields": projection.primary_fields,
            "secondary_fields": projection.secondary_fields,
            "page_size": projection.page_size,
            "page_offset": projection.page_offset,
            "include_citations": projection.include_citations,
        },
    }
    digest = sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"task_frame_{digest[:24]}"


def _build_coverage(
    requirement: EvidenceRequirement,
    projection: ProjectionSpec,
    retrieval: CandidateRetrievalResult,
    observations: tuple[TaskEvidenceObservation, ...],
) -> EvidenceCoverage:
    available_fields = {
        evidence_field.name for observation in observations for evidence_field in observation.fields
    }
    required_properties = requirement.requested_properties
    covered_properties = tuple(
        property_name for property_name in required_properties if property_name in available_fields
    )
    missing_properties = tuple(
        property_name
        for property_name in required_properties
        if property_name not in available_fields
    )
    covered_projection_fields = tuple(
        field_name for field_name in projection.primary_fields if field_name in available_fields
    )
    missing_projection_fields = tuple(
        field_name for field_name in projection.primary_fields if field_name not in available_fields
    )
    assertion_values: dict[str, set[str]] = {}
    for observation in observations:
        if observation.assertion_key is None:
            continue
        assertion_values.setdefault(observation.assertion_key, set()).add(
            observation.assertion_value or ""
        )
    conflicting_keys = tuple(
        sorted(key for key, values in assertion_values.items() if len(values) > 1)
    )
    return EvidenceCoverage(
        target_found=retrieval.total_source_item_count > 0,
        total_source_item_count=retrieval.total_source_item_count,
        returned_source_item_count=retrieval.returned_source_item_count,
        expected_assembled_observation_count=len(retrieval.assembled_observation_ids),
        assembled_observation_count=len(observations),
        assembly_complete=(len(observations) == len(retrieval.assembled_observation_ids)),
        required_properties=required_properties,
        covered_properties=covered_properties,
        missing_properties=missing_properties,
        required_projection_fields=projection.primary_fields,
        covered_projection_fields=covered_projection_fields,
        missing_projection_fields=missing_projection_fields,
        conflicting_assertion_keys=conflicting_keys,
        is_exhaustive=retrieval.is_exhaustive,
        has_more=retrieval.has_more,
    )


def _decide_answerability(
    requirement: EvidenceRequirement,
    retrieval: CandidateRetrievalResult,
    coverage: EvidenceCoverage,
) -> AnswerabilityDecision:
    if retrieval.rejection_reason in _ACCESS_REJECTION_REASONS:
        return AnswerabilityDecision(
            status="permission_denied",
            reason_codes=(retrieval.rejection_reason or "permission_denied",),
        )
    if not coverage.target_found:
        return AnswerabilityDecision(
            status="target_not_found",
            reason_codes=(retrieval.rejection_reason or "no_matching_target",),
        )
    if (
        coverage.required_properties
        and not coverage.covered_properties
        and coverage.assembled_observation_count > 0
        and coverage.assembly_complete
        and coverage.is_exhaustive
    ):
        return AnswerabilityDecision(
            status="property_absent",
            reason_codes=("requested_property_absent",),
        )
    if coverage.conflicting_assertion_keys:
        return AnswerabilityDecision(
            status="conflicting_evidence",
            reason_codes=("conflicting_assertion_values",),
        )
    cardinality_incomplete = (
        requirement.cardinality_mode == "all_matching" and not coverage.is_exhaustive
    ) or (
        requirement.cardinality_mode in {"exact", "at_least"}
        and requirement.source_item_count is not None
        and coverage.returned_source_item_count < requirement.source_item_count
    )
    if (
        retrieval.rejected
        or coverage.missing_properties
        or coverage.missing_projection_fields
        or cardinality_incomplete
        or not coverage.assembly_complete
        or coverage.assembled_observation_count == 0
    ):
        reasons: list[str] = []
        if retrieval.rejection_reason is not None:
            reasons.append(retrieval.rejection_reason)
        if coverage.missing_properties:
            reasons.append("requested_properties_partially_covered")
        if coverage.missing_projection_fields:
            reasons.append("primary_projection_fields_not_available")
        if cardinality_incomplete:
            reasons.append("evidence_cardinality_incomplete")
        if not coverage.assembly_complete:
            reasons.append("evidence_assembly_incomplete")
        if coverage.assembled_observation_count == 0:
            reasons.append("evidence_fields_not_assembled")
        return AnswerabilityDecision(
            status="partial_evidence",
            reason_codes=tuple(dict.fromkeys(reasons)),
        )
    return AnswerabilityDecision(
        status="sufficient_evidence",
        reason_codes=("evidence_requirement_satisfied",),
    )


def _build_projection(
    spec: ProjectionSpec,
    retrieval: CandidateRetrievalResult,
    observations: tuple[TaskEvidenceObservation, ...],
) -> AnswerProjection:
    observations_by_source: dict[
        tuple[str, str],
        list[TaskEvidenceObservation],
    ] = {}
    for observation in observations:
        observations_by_source.setdefault(observation.source_item_key, []).append(observation)
    ordered_source_keys = tuple(
        source_item_key
        for source_item_key in retrieval.selected_source_item_keys
        if source_item_key in observations_by_source
    )
    page_start = spec.page_offset
    page_end = page_start + spec.page_size
    page_source_keys = ordered_source_keys[page_start:page_end]
    items: list[ProjectedEvidenceItem] = []
    for source_item_key in page_source_keys:
        source_observations = observations_by_source[source_item_key]
        primary_fields = _project_fields(source_observations, spec.primary_fields)
        secondary_fields = _project_fields(source_observations, spec.secondary_fields)
        citation_locators = (
            tuple(
                dict.fromkeys(observation.citation_locator for observation in source_observations)
            )
            if spec.include_citations
            else ()
        )
        items.append(
            ProjectedEvidenceItem(
                source_item_key=source_item_key,
                primary_fields=primary_fields,
                secondary_fields=secondary_fields,
                citation_locators=citation_locators,
            )
        )
    projection_has_more = retrieval.has_more or page_end < len(ordered_source_keys)
    return AnswerProjection(
        output_format=spec.output_format,
        items=tuple(items),
        total_source_item_count=retrieval.total_source_item_count,
        returned_source_item_count=retrieval.returned_source_item_count,
        displayed_source_item_count=len(items),
        is_exhaustive=retrieval.is_exhaustive,
        has_more=projection_has_more,
    )


def _project_fields(
    observations: Iterable[TaskEvidenceObservation],
    requested_fields: tuple[str, ...],
) -> tuple[ProjectedField, ...]:
    projected: list[ProjectedField] = []
    for field_name in requested_fields:
        for observation in observations:
            value = observation.field_value(field_name)
            if value is not None:
                projected.append(ProjectedField(name=field_name, value=value))
    return tuple(projected)
