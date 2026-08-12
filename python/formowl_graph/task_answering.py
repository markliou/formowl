"""Source-neutral task understanding, evidence coverage, and answer projection."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import sys
from types import MappingProxyType
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence
from unicodedata import normalize

from formowl_contract import (
    AnswerClaim,
    AnswerClaimState,
    ClaimRequirement,
    ContractValidationError,
    CoverageAuthorizationBinding,
    CoverageLedger,
    CoverageScopeAuthority,
    SourceInventory,
    StructuralCell,
    StructuralObservation,
    VersionManifest,
)

if TYPE_CHECKING:
    from formowl_mail.query import StructuralObservationMatchFact

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
_CANONICAL_CLAIM_ERROR_CODES = frozenset(
    {
        "permission_denied",
        "store_unavailable",
        "invalid_binding",
        "invalid_evidence",
        "claim_validation_failed",
    }
)
_CANONICAL_VALUE_CLAIM_KINDS = frozenset(
    {
        "single_value",
        "latest_value",
        "current_value",
    }
)
_CANONICAL_ERROR_MESSAGES = {
    "permission_denied": "Governed evidence access was not authorized.",
    "store_unavailable": "Governed evidence was unavailable.",
    "invalid_binding": "Governed evidence bindings could not be validated.",
    "invalid_evidence": "Governed structural evidence could not be validated.",
    "claim_validation_failed": "A canonical answer claim could not be validated.",
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


class CanonicalEvidenceUnavailableError(RuntimeError):
    """Typed upstream failure that must never be converted into an AnswerClaim."""

    def __init__(self, code: str) -> None:
        if code not in {"permission_denied", "store_unavailable"}:
            raise ValueError("unsupported canonical evidence failure code")
        self.code = code
        super().__init__(_CANONICAL_ERROR_MESSAGES[code])


@dataclass(frozen=True)
class CanonicalClaimError:
    """Safe outer error; it intentionally carries no claim state or source detail."""

    code: str
    message: str

    def __post_init__(self) -> None:
        if self.code not in _CANONICAL_CLAIM_ERROR_CODES:
            raise ValueError("unsupported canonical claim error code")
        if self.message != _CANONICAL_ERROR_MESSAGES[self.code]:
            raise ValueError("canonical claim error message must use the safe fixed text")


@dataclass(frozen=True)
class CanonicalClaimOutcome:
    """Canonical claim plus one-way compatibility and enforced-rendering views."""

    status: str
    claim: AnswerClaim | None
    coverage: EvidenceCoverage | None
    answerability: AnswerabilityDecision | None
    rendered_answer: str
    canonical_values: tuple[str, ...] = ()
    matched_structural_observation_ids: tuple[str, ...] = ()
    model_prose_replaced: bool = False
    error: CanonicalClaimError | None = None

    def __post_init__(self) -> None:
        if self.status not in {"ok", "error"}:
            raise ValueError("unsupported canonical claim outcome status")
        _required_text(self.rendered_answer, "rendered_answer")
        _required_unique_text(self.canonical_values, "canonical_values")
        _required_unique_text(
            self.matched_structural_observation_ids,
            "matched_structural_observation_ids",
        )
        if type(self.model_prose_replaced) is not bool:
            raise ValueError("model_prose_replaced must be boolean")
        if self.status == "ok":
            if (
                not isinstance(self.claim, AnswerClaim)
                or not isinstance(self.coverage, EvidenceCoverage)
                or not isinstance(self.answerability, AnswerabilityDecision)
                or self.error is not None
            ):
                raise ValueError("successful canonical claim outcomes require validated views")
        elif (
            self.claim is not None
            or self.coverage is not None
            or self.answerability is not None
            or not isinstance(self.error, CanonicalClaimError)
            or self.canonical_values
            or self.matched_structural_observation_ids
        ):
            raise ValueError("failed canonical claim outcomes must not carry partial truth")


@dataclass(frozen=True)
class _CanonicalStructuralValue:
    normalized_value: str
    display_value: str
    source_observation_id: str
    source_inventory_item_id: str


@dataclass(frozen=True)
class _CanonicalStructuralDerivation:
    values: tuple[_CanonicalStructuralValue, ...]
    latest_chronology_complete: bool


@dataclass(frozen=True)
class _ResolvedStructuralMatch:
    structural_observation: StructuralObservation
    matched_row_ordinals: tuple[int, ...]
    value_column_ordinal: int


_PREVALIDATED_DIAGNOSTIC_TOPOLOGY_ATTESTATION_TOKEN = object()
_PREVALIDATED_DIAGNOSTIC_CANDIDATE_TOPOLOGY_ATTESTATION_TOKEN = object()
_PREVALIDATED_DIAGNOSTIC_CAPABILITY_TOKEN = object()


@dataclass(frozen=True)
class _PrevalidatedDiagnosticTopologyAttestation:
    """Private process-local proof for one exact structural observation tuple."""

    identity_binding: object = field(repr=False, compare=False)
    structural_observations: tuple[StructuralObservation, ...] = field(
        repr=False,
        compare=False,
    )
    _token: object = field(repr=False, compare=False, default=None)


@dataclass(frozen=True)
class _PrevalidatedDiagnosticCandidateTopologyAttestation:
    """Private proof for one exact typed-mismatch diagnostic structural tuple."""

    identity_binding: object = field(repr=False, compare=False)
    structural_observations: tuple[StructuralObservation, ...] = field(
        repr=False,
        compare=False,
    )
    _token: object = field(repr=False, compare=False, default=None)


@dataclass(frozen=True)
class _PrevalidatedDiagnosticStructuredCapability:
    """Private, process-local authority for one startup-proven query scope.

    This is deliberately not a general governance shortcut.  The factory is
    used only after a diagnostic runtime has already created and validated the
    normal typed scope and its definitive ``AnswerClaim`` records.  It retains
    object references and identifier/coordinate maps only; it never persists,
    serializes, or copies structural values.
    """

    identity_bindings: tuple[object, ...]
    coverage_ledger: CoverageLedger
    claim_requirement: ClaimRequirement
    source_inventory: SourceInventory
    version_manifest: VersionManifest
    scope_authority: CoverageScopeAuthority
    authorization_binding: CoverageAuthorizationBinding
    topology_attestation: _PrevalidatedDiagnosticTopologyAttestation = field(
        repr=False,
        compare=False,
    )
    structural_observations_by_source_id: Mapping[str, StructuralObservation]
    value_column_ordinals_by_source_id: Mapping[str, int | None]
    found_claim: AnswerClaim
    not_found_claim: AnswerClaim
    _token: object = field(repr=False, compare=False, default=None)


@dataclass(frozen=True)
class _PrevalidatedDiagnosticSelection:
    """Ephemeral selected-observation coordinate map for one diagnostic turn."""

    capability: _PrevalidatedDiagnosticStructuredCapability
    structural_observations: tuple[StructuralObservation, ...]
    selected_source_observation_ids: frozenset[str]
    cells_by_coordinate: Mapping[tuple[str, int, int], StructuralCell]
    _token: object = field(repr=False, compare=False, default=None)


_PREVALIDATED_DIAGNOSTIC_CAPABILITY_ISSUANCES: dict[
    int,
    _PrevalidatedDiagnosticStructuredCapability,
] = {}
_PREVALIDATED_DIAGNOSTIC_TOPOLOGY_ATTESTATION_ISSUANCES: dict[
    int,
    _PrevalidatedDiagnosticTopologyAttestation,
] = {}
_PREVALIDATED_DIAGNOSTIC_CANDIDATE_TOPOLOGY_ATTESTATION_ISSUANCES: dict[
    int,
    _PrevalidatedDiagnosticCandidateTopologyAttestation,
] = {}


class _CanonicalClaimFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        if code not in _CANONICAL_CLAIM_ERROR_CODES:
            raise ValueError("unsupported canonical claim failure code")
        self.code = code
        super().__init__(code)


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

    @classmethod
    def answer_canonical_claim(
        cls,
        *,
        coverage_ledger: CoverageLedger,
        claim_requirement: ClaimRequirement,
        source_inventory: SourceInventory,
        version_manifest: VersionManifest,
        scope_authority: CoverageScopeAuthority,
        authorization_binding: CoverageAuthorizationBinding,
        matched_structural_facts: Iterable[StructuralObservationMatchFact],
        structural_observations: Iterable[StructuralObservation],
        source_inventories: Iterable[SourceInventory] = (),
        version_manifests: Iterable[VersionManifest] = (),
        scope_authorities: Iterable[CoverageScopeAuthority] = (),
        authorization_bindings: Iterable[CoverageAuthorizationBinding] = (),
        evidence_snapshot_ids: Iterable[str] = (),
        model_prose: str | None = None,
    ) -> CanonicalClaimOutcome:
        """Derive, construct, validate, and render one canonical WP1 claim.

        The caller supplies typed evidence and bindings, never a proposed state
        or a completeness boolean.  The legacy candidate-retrieval ``answer``
        path below remains a compatibility path and cannot construct a
        canonical ``AnswerClaim`` without these WP1 inputs.
        """

        try:
            if model_prose is not None and type(model_prose) is not str:
                raise _CanonicalClaimFailure("invalid_evidence")
            aggregate_source_inventories = tuple(source_inventories)
            aggregate_version_manifests = tuple(version_manifests)
            aggregate_scope_authorities = tuple(scope_authorities)
            aggregate_authorization_bindings = tuple(authorization_bindings)
            _validate_canonical_claim_bindings(
                coverage_ledger=coverage_ledger,
                claim_requirement=claim_requirement,
                source_inventory=source_inventory,
                version_manifest=version_manifest,
                scope_authority=scope_authority,
                authorization_binding=authorization_binding,
                source_inventories=aggregate_source_inventories,
                version_manifests=aggregate_version_manifests,
                scope_authorities=aggregate_scope_authorities,
                authorization_bindings=aggregate_authorization_bindings,
            )
            matched_facts = _canonical_structural_match_facts(matched_structural_facts)
            structural_records = _canonical_structural_observations(structural_observations)
            resolved_matches = _resolve_structural_match_facts(
                claim_requirement,
                matched_facts,
                structural_records,
            )
            observations = _matched_structural_observations(resolved_matches)
            snapshots = _canonical_evidence_snapshot_ids(evidence_snapshot_ids)
            _validate_matched_structural_observations(
                coverage_ledger=coverage_ledger,
                source_inventory=source_inventory,
                version_manifest=version_manifest,
                scope_authority=scope_authority,
                resolved_matches=resolved_matches,
                source_inventories=aggregate_source_inventories,
                version_manifests=aggregate_version_manifests,
                scope_authorities=aggregate_scope_authorities,
            )
            structural_derivation = _derive_canonical_structural_values(
                claim_requirement,
                resolved_matches,
            )
            state = _derive_canonical_claim_state(
                coverage_ledger=coverage_ledger,
                claim_requirement=claim_requirement,
                source_inventory=source_inventory,
                version_manifest=version_manifest,
                scope_authority=scope_authority,
                authorization_binding=authorization_binding,
                structural_values=structural_derivation.values,
                latest_chronology_complete=(structural_derivation.latest_chronology_complete),
                source_inventories=aggregate_source_inventories,
                version_manifests=aggregate_version_manifests,
                scope_authorities=aggregate_scope_authorities,
                authorization_bindings=aggregate_authorization_bindings,
            )
            reason_codes = _canonical_claim_reason_codes(
                state,
                coverage_ledger=coverage_ledger,
                claim_requirement=claim_requirement,
                has_populated_values=bool(structural_derivation.values),
                latest_chronology_complete=(structural_derivation.latest_chronology_complete),
            )
            try:
                claim = AnswerClaim.create(
                    state=state,
                    reason_codes=reason_codes,
                    coverage_ledger=coverage_ledger,
                    claim_requirement=claim_requirement,
                    source_inventory=source_inventory,
                    version_manifest=version_manifest,
                    expected_scope_authority=scope_authority,
                    authorization_binding=authorization_binding,
                    source_inventories=aggregate_source_inventories,
                    version_manifests=aggregate_version_manifests,
                    scope_authorities=aggregate_scope_authorities,
                    authorization_bindings=aggregate_authorization_bindings,
                    evidence_snapshot_ids=snapshots,
                )
            except ContractValidationError as exc:
                raise _CanonicalClaimFailure("claim_validation_failed") from exc
            values = _canonical_display_values(structural_derivation.values)
            coverage, answerability = _canonical_compatibility_views(
                claim,
                coverage_ledger=coverage_ledger,
                claim_requirement=claim_requirement,
                observations=observations,
                canonical_values=values,
            )
            return CanonicalClaimOutcome(
                status="ok",
                claim=claim,
                coverage=coverage,
                answerability=answerability,
                rendered_answer=_render_enforced_canonical_answer(
                    claim,
                    claim_requirement=claim_requirement,
                    canonical_values=values,
                ),
                canonical_values=values,
                matched_structural_observation_ids=tuple(
                    observation.source_observation_id for observation in observations
                ),
                model_prose_replaced=model_prose is not None,
            )
        except CanonicalEvidenceUnavailableError as exc:
            return _canonical_claim_error_outcome(exc.code)
        except PermissionError:
            return _canonical_claim_error_outcome("permission_denied")
        except OSError:
            return _canonical_claim_error_outcome("store_unavailable")
        except _CanonicalClaimFailure as exc:
            return _canonical_claim_error_outcome(exc.code)
        except ContractValidationError:
            return _canonical_claim_error_outcome("invalid_binding")
        except (TypeError, ValueError):
            return _canonical_claim_error_outcome("invalid_evidence")

    @classmethod
    def _prepare_prevalidated_diagnostic_topology_attestation(
        cls,
        *,
        identity_binding: object,
        structural_observations: tuple[StructuralObservation, ...],
    ) -> object:
        """Validate one exact shard tuple once and issue an opaque proof."""

        if (
            identity_binding is None
            or not isinstance(structural_observations, tuple)
            or not structural_observations
            or any(
                not isinstance(observation, StructuralObservation)
                for observation in structural_observations
            )
        ):
            raise ContractValidationError("prevalidated diagnostic topology attestation is invalid")
        for observation in structural_observations:
            try:
                _validate_structural_topology(observation)
            except _CanonicalClaimFailure as exc:
                raise ContractValidationError(
                    "prevalidated diagnostic topology attestation is invalid"
                ) from exc
        attestation = _PrevalidatedDiagnosticTopologyAttestation(
            identity_binding=identity_binding,
            structural_observations=structural_observations,
            _token=_PREVALIDATED_DIAGNOSTIC_TOPOLOGY_ATTESTATION_TOKEN,
        )
        _PREVALIDATED_DIAGNOSTIC_TOPOLOGY_ATTESTATION_ISSUANCES[id(attestation)] = attestation
        return attestation

    @classmethod
    def _prepare_prevalidated_diagnostic_candidate_topology_attestation(
        cls,
        *,
        identity_binding: object,
        structural_observations: tuple[StructuralObservation, ...],
    ) -> object:
        """Issue an opaque proof for the compact-export topology surface.

        This is not a canonical topology proof. It explicitly classifies only
        the typed geometry conditions enforced by ``_validate_structural_topology``:
        row-anchor mismatch, row-span outside, column-span outside, and
        coordinate overlap. At least one such mismatch must exist. The
        returned proof is process-local and bound to the exact template and
        exact startup tuple.
        """

        if (
            identity_binding is None
            or not isinstance(structural_observations, tuple)
            or not structural_observations
            or any(
                not isinstance(observation, StructuralObservation)
                for observation in structural_observations
            )
        ):
            raise ContractValidationError("diagnostic thin topology compatibility is invalid")
        mismatch_reasons: set[str] = set()
        for observation in structural_observations:
            mismatch_reasons.update(_diagnostic_structural_topology_mismatch_reasons(observation))
        if not mismatch_reasons:
            raise ContractValidationError("diagnostic thin topology compatibility is invalid")
        attestation = _PrevalidatedDiagnosticCandidateTopologyAttestation(
            identity_binding=identity_binding,
            structural_observations=structural_observations,
            _token=(_PREVALIDATED_DIAGNOSTIC_CANDIDATE_TOPOLOGY_ATTESTATION_TOKEN),
        )
        _PREVALIDATED_DIAGNOSTIC_CANDIDATE_TOPOLOGY_ATTESTATION_ISSUANCES[id(attestation)] = (
            attestation
        )
        return attestation

    @classmethod
    def _prevalidated_diagnostic_topology_attestation_is_valid(
        cls,
        attestation: object,
        *,
        identity_binding: object,
        structural_observations: object,
    ) -> bool:
        """Check one process issuance and exact template/tuple identity."""

        return (
            isinstance(attestation, _PrevalidatedDiagnosticTopologyAttestation)
            and attestation._token is _PREVALIDATED_DIAGNOSTIC_TOPOLOGY_ATTESTATION_TOKEN
            and _PREVALIDATED_DIAGNOSTIC_TOPOLOGY_ATTESTATION_ISSUANCES.get(id(attestation))
            is attestation
            and attestation.identity_binding is identity_binding
            and isinstance(structural_observations, tuple)
            and attestation.structural_observations is structural_observations
        )

    @classmethod
    def _prevalidated_diagnostic_candidate_topology_attestation_is_valid(
        cls,
        attestation: object,
        *,
        identity_binding: object,
        structural_observations: object,
    ) -> bool:
        """Check one candidate-only issuance and exact template/tuple identity."""

        return (
            isinstance(
                attestation,
                _PrevalidatedDiagnosticCandidateTopologyAttestation,
            )
            and attestation._token is _PREVALIDATED_DIAGNOSTIC_CANDIDATE_TOPOLOGY_ATTESTATION_TOKEN
            and _PREVALIDATED_DIAGNOSTIC_CANDIDATE_TOPOLOGY_ATTESTATION_ISSUANCES.get(
                id(attestation)
            )
            is attestation
            and attestation.identity_binding is identity_binding
            and isinstance(structural_observations, tuple)
            and attestation.structural_observations is structural_observations
        )

    @classmethod
    def _prepare_prevalidated_diagnostic_structured_capability(
        cls,
        *,
        identity_bindings: Sequence[object],
        topology_attestation: object,
        coverage_ledger: CoverageLedger,
        claim_requirement: ClaimRequirement,
        source_inventory: SourceInventory,
        version_manifest: VersionManifest,
        scope_authority: CoverageScopeAuthority,
        authorization_binding: CoverageAuthorizationBinding,
        structural_observations: tuple[StructuralObservation, ...],
    ) -> _PrevalidatedDiagnosticStructuredCapability:
        """Freeze a startup-validated all-matching scope for diagnostic UAT only.

        The normal constructor and ``AnswerClaim`` factory are intentionally
        used here, at startup.  Query-time callers receive only this opaque
        capability and cannot supply a proposed definitive claim or coverage
        result through the MCP surface.
        """

        bindings = tuple(identity_bindings)
        observations = structural_observations
        if (
            len(bindings) != 5
            or any(value is None for value in bindings)
            or len({id(value) for value in bindings}) != len(bindings)
            or not cls._prevalidated_diagnostic_topology_attestation_is_valid(
                topology_attestation,
                identity_binding=bindings[-1],
                structural_observations=observations,
            )
            or not all(
                isinstance(value, expected_type)
                for value, expected_type in (
                    (coverage_ledger, CoverageLedger),
                    (claim_requirement, ClaimRequirement),
                    (source_inventory, SourceInventory),
                    (version_manifest, VersionManifest),
                    (scope_authority, CoverageScopeAuthority),
                    (authorization_binding, CoverageAuthorizationBinding),
                )
            )
            or claim_requirement.kind != "all_matching"
            or not coverage_ledger.complete_authorized_scope
            or not observations
        ):
            raise ContractValidationError("prevalidated diagnostic capability is invalid")
        observation_by_source_id: dict[str, StructuralObservation] = {}
        structural_observation_ids: set[str] = set()
        value_column_ordinals_by_source_id: dict[str, int | None] = {}
        for observation in observations:
            if not isinstance(observation, StructuralObservation):
                raise ContractValidationError("prevalidated diagnostic capability is invalid")
            existing = observation_by_source_id.get(observation.source_observation_id)
            if (
                existing is not None
                or observation.structural_observation_id in structural_observation_ids
            ):
                raise ContractValidationError("prevalidated diagnostic capability is invalid")
            observation_by_source_id[observation.source_observation_id] = observation
            structural_observation_ids.add(observation.structural_observation_id)
            try:
                value_column_ordinals_by_source_id[observation.source_observation_id] = (
                    _target_structural_column_ordinal(claim_requirement, observation)
                )
            except _CanonicalClaimFailure:
                # The generic path permits a nonmatching malformed schema to
                # remain in a complete scope and fails only if it produces a
                # fact. Preserve that behavior without query-time rescans.
                value_column_ordinals_by_source_id[observation.source_observation_id] = None
        try:
            found_claim = AnswerClaim.create(
                state=AnswerClaimState.FOUND.value,
                reason_codes=("canonical_populated_value_found",),
                coverage_ledger=coverage_ledger,
                claim_requirement=claim_requirement,
                source_inventory=source_inventory,
                version_manifest=version_manifest,
                expected_scope_authority=scope_authority,
                authorization_binding=authorization_binding,
                evidence_snapshot_ids=(),
            )
            not_found_claim = AnswerClaim.create(
                state=AnswerClaimState.NOT_FOUND_WITHIN_COMPLETE_SCOPE.value,
                reason_codes=("complete_scope_no_populated_value",),
                coverage_ledger=coverage_ledger,
                claim_requirement=claim_requirement,
                source_inventory=source_inventory,
                version_manifest=version_manifest,
                expected_scope_authority=scope_authority,
                authorization_binding=authorization_binding,
                evidence_snapshot_ids=(),
            )
        except ContractValidationError as exc:
            raise ContractValidationError("prevalidated diagnostic capability is invalid") from exc
        capability = _PrevalidatedDiagnosticStructuredCapability(
            identity_bindings=bindings,
            coverage_ledger=coverage_ledger,
            claim_requirement=claim_requirement,
            source_inventory=source_inventory,
            version_manifest=version_manifest,
            scope_authority=scope_authority,
            authorization_binding=authorization_binding,
            topology_attestation=topology_attestation,
            structural_observations_by_source_id=MappingProxyType(observation_by_source_id),
            value_column_ordinals_by_source_id=MappingProxyType(value_column_ordinals_by_source_id),
            found_claim=found_claim,
            not_found_claim=not_found_claim,
            _token=_PREVALIDATED_DIAGNOSTIC_CAPABILITY_TOKEN,
        )
        if not cls._prevalidated_diagnostic_capability_has_complete_startup_proof(capability):
            raise ContractValidationError("prevalidated diagnostic capability is invalid")
        _PREVALIDATED_DIAGNOSTIC_CAPABILITY_ISSUANCES[id(capability)] = capability
        return capability

    @classmethod
    def _prevalidated_diagnostic_capability_has_complete_startup_proof(
        cls,
        capability: object,
    ) -> bool:
        """Validate one scope capability without replaying topology."""

        if not isinstance(capability, _PrevalidatedDiagnosticStructuredCapability):
            return False
        attestation = capability.topology_attestation
        if (
            capability._token is not _PREVALIDATED_DIAGNOSTIC_CAPABILITY_TOKEN
            or len(capability.identity_bindings) != 5
            or not isinstance(
                attestation,
                _PrevalidatedDiagnosticTopologyAttestation,
            )
            or not cls._prevalidated_diagnostic_topology_attestation_is_valid(
                attestation,
                identity_binding=capability.identity_bindings[-1],
                structural_observations=attestation.structural_observations,
            )
            or not isinstance(capability.structural_observations_by_source_id, Mapping)
            or not isinstance(capability.value_column_ordinals_by_source_id, Mapping)
            or set(capability.structural_observations_by_source_id)
            != set(capability.value_column_ordinals_by_source_id)
            or not capability.structural_observations_by_source_id
            or len(capability.structural_observations_by_source_id)
            != len(attestation.structural_observations)
            or not isinstance(capability.found_claim, AnswerClaim)
            or not isinstance(capability.not_found_claim, AnswerClaim)
            or capability.found_claim.state != AnswerClaimState.FOUND.value
            or capability.not_found_claim.state
            != AnswerClaimState.NOT_FOUND_WITHIN_COMPLETE_SCOPE.value
        ):
            return False
        structural_ids: set[str] = set()
        for observation in attestation.structural_observations:
            source_observation_id = observation.source_observation_id
            value_column_ordinal = capability.value_column_ordinals_by_source_id.get(
                source_observation_id
            )
            if (
                not isinstance(source_observation_id, str)
                or not source_observation_id
                or not isinstance(observation, StructuralObservation)
                or observation.source_observation_id != source_observation_id
                or capability.structural_observations_by_source_id.get(source_observation_id)
                is not observation
                or observation.structural_observation_id in structural_ids
                or (
                    value_column_ordinal is not None
                    and (
                        not isinstance(value_column_ordinal, int)
                        or isinstance(value_column_ordinal, bool)
                        or value_column_ordinal < 0
                    )
                )
            ):
                return False
            structural_ids.add(observation.structural_observation_id)
        return True

    @classmethod
    def _prevalidated_diagnostic_capability_is_valid(
        cls,
        capability: object,
        *,
        identity_bindings: Sequence[object],
        topology_attestation: object,
        structural_observations: object,
        coverage_ledger: CoverageLedger,
        claim_requirement: ClaimRequirement,
        source_inventory: SourceInventory,
        version_manifest: VersionManifest,
        scope_authority: CoverageScopeAuthority,
        authorization_binding: CoverageAuthorizationBinding,
    ) -> bool:
        """Check process-local issuance and object identity without proof replay."""

        bindings = tuple(identity_bindings)
        if (
            not isinstance(capability, _PrevalidatedDiagnosticStructuredCapability)
            or capability._token is not _PREVALIDATED_DIAGNOSTIC_CAPABILITY_TOKEN
            or _PREVALIDATED_DIAGNOSTIC_CAPABILITY_ISSUANCES.get(id(capability)) is not capability
            or len(bindings) != 5
            or len(capability.identity_bindings) != 5
            or capability.topology_attestation is not topology_attestation
            or not cls._prevalidated_diagnostic_topology_attestation_is_valid(
                topology_attestation,
                identity_binding=bindings[-1],
                structural_observations=structural_observations,
            )
            or not all(
                actual is expected
                for actual, expected in zip(capability.identity_bindings, bindings, strict=True)
            )
            or any(value is None for value in capability.identity_bindings)
            or capability.coverage_ledger is not coverage_ledger
            or capability.claim_requirement is not claim_requirement
            or capability.source_inventory is not source_inventory
            or capability.version_manifest is not version_manifest
            or capability.scope_authority is not scope_authority
            or capability.authorization_binding is not authorization_binding
            or capability.found_claim.state != AnswerClaimState.FOUND.value
            or capability.not_found_claim.state
            != AnswerClaimState.NOT_FOUND_WITHIN_COMPLETE_SCOPE.value
        ):
            return False
        return True

    @classmethod
    def _select_prevalidated_diagnostic_structural_observations(
        cls,
        capability: _PrevalidatedDiagnosticStructuredCapability,
        *,
        structural_observations: Sequence[StructuralObservation],
    ) -> _PrevalidatedDiagnosticSelection:
        """Build one ephemeral coordinate index over the already-selected rows."""

        if (
            not isinstance(capability, _PrevalidatedDiagnosticStructuredCapability)
            or capability._token is not _PREVALIDATED_DIAGNOSTIC_CAPABILITY_TOKEN
        ):
            raise ContractValidationError("prevalidated diagnostic capability is invalid")
        selected = tuple(structural_observations)
        selected_by_source_id: set[str] = set()
        coordinates: dict[tuple[str, int, int], StructuralCell] = {}
        for observation in selected:
            if not isinstance(observation, StructuralObservation):
                raise ContractValidationError("prevalidated diagnostic selection is invalid")
            if (
                observation.source_observation_id in selected_by_source_id
                or capability.structural_observations_by_source_id.get(
                    observation.source_observation_id
                )
                is not observation
            ):
                raise ContractValidationError("prevalidated diagnostic selection is invalid")
            selected_by_source_id.add(observation.source_observation_id)
            row_ordinals = {row.row_ordinal for row in observation.rows}
            column_ordinals = {column.column_ordinal for column in observation.columns}
            for row in observation.rows:
                for cell in row.cells:
                    covered_rows = range(cell.row_ordinal, cell.row_ordinal + cell.row_span)
                    covered_columns = range(
                        cell.column_ordinal,
                        cell.column_ordinal + cell.column_span,
                    )
                    if (
                        cell.row_ordinal != row.row_ordinal
                        or not set(covered_rows).issubset(row_ordinals)
                        or not set(covered_columns).issubset(column_ordinals)
                    ):
                        raise ContractValidationError(
                            "prevalidated diagnostic selection is invalid"
                        )
                    for row_ordinal in covered_rows:
                        for column_ordinal in covered_columns:
                            key = (
                                observation.source_observation_id,
                                row_ordinal,
                                column_ordinal,
                            )
                            if key in coordinates:
                                raise ContractValidationError(
                                    "prevalidated diagnostic selection is invalid"
                                )
                            coordinates[key] = cell
        return _PrevalidatedDiagnosticSelection(
            capability=capability,
            structural_observations=selected,
            selected_source_observation_ids=frozenset(selected_by_source_id),
            cells_by_coordinate=MappingProxyType(coordinates),
            _token=_PREVALIDATED_DIAGNOSTIC_CAPABILITY_TOKEN,
        )

    @classmethod
    def _answer_prevalidated_diagnostic_structured_claim(
        cls,
        *,
        capability: object,
        structural_observations: Sequence[StructuralObservation],
        matched_structural_facts: Iterable[StructuralObservationMatchFact],
    ) -> CanonicalClaimOutcome:
        """Answer a startup-proven all-matching diagnostic scope without replay.

        This private method is intentionally narrower than
        :meth:`answer_canonical_claim`: it accepts only an opaque capability
        issued by this process after normal startup validation, accepts no
        model prose, and derives only the matched-row claim state. The generic
        governance path remains unchanged when the capability is absent.
        """

        try:
            if (
                not isinstance(capability, _PrevalidatedDiagnosticStructuredCapability)
                or _PREVALIDATED_DIAGNOSTIC_CAPABILITY_ISSUANCES.get(id(capability))
                is not capability
            ):
                raise _CanonicalClaimFailure("invalid_binding")
            selection = cls._select_prevalidated_diagnostic_structural_observations(
                capability,
                structural_observations=structural_observations,
            )
            if (
                selection._token is not _PREVALIDATED_DIAGNOSTIC_CAPABILITY_TOKEN
                or selection.capability is not capability
                or capability._token is not _PREVALIDATED_DIAGNOSTIC_CAPABILITY_TOKEN
                or capability.claim_requirement.kind != "all_matching"
            ):
                raise _CanonicalClaimFailure("invalid_binding")
            matched_facts = _canonical_structural_match_facts(matched_structural_facts)
            resolved: list[_ResolvedStructuralMatch] = []
            for fact in matched_facts:
                observation = selection.capability.structural_observations_by_source_id.get(
                    fact.source_observation_id
                )
                if (
                    observation is None
                    or observation.structural_observation_id != fact.structural_observation_id
                    or observation.source_inventory_item_id != fact.source_inventory_item_id
                    or fact.source_observation_id not in selection.selected_source_observation_ids
                ):
                    raise _CanonicalClaimFailure("invalid_evidence")
                value_column_ordinal = capability.value_column_ordinals_by_source_id.get(
                    fact.source_observation_id
                )
                if value_column_ordinal is None:
                    raise _CanonicalClaimFailure("invalid_evidence")
                for row_ordinal in fact.matched_row_ordinals:
                    if (
                        observation.source_observation_id,
                        row_ordinal,
                        value_column_ordinal,
                    ) not in selection.cells_by_coordinate:
                        raise _CanonicalClaimFailure("invalid_evidence")
                resolved.append(
                    _ResolvedStructuralMatch(
                        structural_observation=observation,
                        matched_row_ordinals=fact.matched_row_ordinals,
                        value_column_ordinal=value_column_ordinal,
                    )
                )
            resolved_matches = tuple(resolved)
            observations = _matched_structural_observations(resolved_matches)
            applicable, latest_chronology_complete = _applicable_structural_matches(
                capability.claim_requirement,
                resolved_matches,
            )
            values: list[_CanonicalStructuralValue] = []
            for match in applicable:
                observation = match.structural_observation
                for row_ordinal in match.matched_row_ordinals:
                    cell = selection.cells_by_coordinate.get(
                        (
                            observation.source_observation_id,
                            row_ordinal,
                            match.value_column_ordinal,
                        )
                    )
                    if cell is None:
                        raise _CanonicalClaimFailure("invalid_evidence")
                    if cell.cell_state != "populated":
                        continue
                    display_value = (cell.value or "").strip()
                    normalized_value = _canonical_text(cell.normalized_value or display_value)
                    if not display_value or not normalized_value:
                        raise _CanonicalClaimFailure("invalid_evidence")
                    values.append(
                        _CanonicalStructuralValue(
                            normalized_value=normalized_value,
                            display_value=display_value,
                            source_observation_id=observation.source_observation_id,
                            source_inventory_item_id=observation.source_inventory_item_id,
                        )
                    )
            structural_derivation = _CanonicalStructuralDerivation(
                values=tuple(
                    sorted(
                        values,
                        key=lambda value: (
                            value.normalized_value,
                            _canonical_text(value.display_value),
                            value.source_observation_id,
                            value.source_inventory_item_id,
                        ),
                    )
                ),
                latest_chronology_complete=latest_chronology_complete,
            )
            if not structural_derivation.latest_chronology_complete:
                raise _CanonicalClaimFailure("invalid_evidence")
            claim = (
                capability.found_claim
                if structural_derivation.values
                else capability.not_found_claim
            )
            canonical_values = _canonical_display_values(structural_derivation.values)
            coverage, answerability = _canonical_compatibility_views(
                claim,
                coverage_ledger=capability.coverage_ledger,
                claim_requirement=capability.claim_requirement,
                observations=observations,
                canonical_values=canonical_values,
            )
            return CanonicalClaimOutcome(
                status="ok",
                claim=claim,
                coverage=coverage,
                answerability=answerability,
                rendered_answer=_render_enforced_canonical_answer(
                    claim,
                    claim_requirement=capability.claim_requirement,
                    canonical_values=canonical_values,
                ),
                canonical_values=canonical_values,
                matched_structural_observation_ids=tuple(
                    observation.source_observation_id for observation in observations
                ),
            )
        except CanonicalEvidenceUnavailableError as exc:
            return _canonical_claim_error_outcome(exc.code)
        except PermissionError:
            return _canonical_claim_error_outcome("permission_denied")
        except OSError:
            return _canonical_claim_error_outcome("store_unavailable")
        except _CanonicalClaimFailure as exc:
            return _canonical_claim_error_outcome(exc.code)
        except ContractValidationError:
            return _canonical_claim_error_outcome("invalid_binding")
        except (TypeError, ValueError):
            return _canonical_claim_error_outcome("invalid_evidence")

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


def _canonical_claim_error_outcome(code: str) -> CanonicalClaimOutcome:
    message = _CANONICAL_ERROR_MESSAGES[code]
    return CanonicalClaimOutcome(
        status="error",
        claim=None,
        coverage=None,
        answerability=None,
        rendered_answer=message,
        error=CanonicalClaimError(code=code, message=message),
    )


def _canonical_structural_match_facts(
    values: Iterable[StructuralObservationMatchFact],
) -> tuple[StructuralObservationMatchFact, ...]:
    if isinstance(values, (str, bytes)):
        raise _CanonicalClaimFailure("invalid_evidence")
    matches = tuple(values)
    query_module = sys.modules.get("formowl_mail.query")
    fact_type = (
        getattr(query_module, "StructuralObservationMatchFact", None)
        if query_module is not None
        else None
    )
    if matches and (
        not isinstance(fact_type, type)
        or any(not isinstance(value, fact_type) for value in matches)
    ):
        raise _CanonicalClaimFailure("invalid_evidence")
    match_keys = [
        (
            value.source_observation_id,
            value.structural_observation_id,
            value.source_inventory_item_id,
        )
        for value in matches
    ]
    if len(match_keys) != len(set(match_keys)):
        raise _CanonicalClaimFailure("invalid_evidence")
    return tuple(
        sorted(
            matches,
            key=lambda value: (
                value.source_observation_id,
                value.structural_observation_id,
                value.source_inventory_item_id,
                value.matched_row_ordinals,
            ),
        )
    )


def _canonical_structural_observations(
    values: Iterable[StructuralObservation],
) -> tuple[StructuralObservation, ...]:
    if isinstance(values, (str, bytes)):
        raise _CanonicalClaimFailure("invalid_evidence")
    observations = tuple(values)
    if any(not isinstance(value, StructuralObservation) for value in observations):
        raise _CanonicalClaimFailure("invalid_evidence")
    source_ids = [observation.source_observation_id for observation in observations]
    structural_ids = [observation.structural_observation_id for observation in observations]
    if len(source_ids) != len(set(source_ids)) or len(structural_ids) != len(set(structural_ids)):
        raise _CanonicalClaimFailure("invalid_evidence")
    return tuple(
        sorted(
            observations,
            key=lambda observation: (
                observation.source_observation_id,
                observation.structural_observation_id,
            ),
        )
    )


def _resolve_structural_match_facts(
    requirement: ClaimRequirement,
    facts: tuple[StructuralObservationMatchFact, ...],
    structural_observations: tuple[StructuralObservation, ...],
) -> tuple[_ResolvedStructuralMatch, ...]:
    observations_by_source_id = {
        observation.source_observation_id: observation for observation in structural_observations
    }
    resolved: list[_ResolvedStructuralMatch] = []
    for fact in facts:
        observation = observations_by_source_id.get(fact.source_observation_id)
        if (
            observation is None
            or observation.structural_observation_id != fact.structural_observation_id
            or observation.source_inventory_item_id != fact.source_inventory_item_id
        ):
            raise _CanonicalClaimFailure("invalid_evidence")
        value_column_ordinal = _target_structural_column_ordinal(
            requirement,
            observation,
        )
        for row_ordinal in fact.matched_row_ordinals:
            _structural_cell_at(
                observation,
                row_ordinal=row_ordinal,
                column_ordinal=value_column_ordinal,
            )
        resolved.append(
            _ResolvedStructuralMatch(
                structural_observation=observation,
                matched_row_ordinals=fact.matched_row_ordinals,
                value_column_ordinal=value_column_ordinal,
            )
        )
    return tuple(resolved)


def _matched_structural_observations(
    matches: tuple[_ResolvedStructuralMatch, ...],
) -> tuple[StructuralObservation, ...]:
    by_source_id: dict[str, StructuralObservation] = {}
    for match in matches:
        observation = match.structural_observation
        existing = by_source_id.get(observation.source_observation_id)
        if existing is not None and existing != observation:
            raise _CanonicalClaimFailure("invalid_evidence")
        by_source_id[observation.source_observation_id] = observation
    return tuple(
        sorted(
            by_source_id.values(),
            key=lambda observation: (
                observation.source_observation_id,
                observation.structural_observation_id,
            ),
        )
    )


def _canonical_evidence_snapshot_ids(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise _CanonicalClaimFailure("invalid_evidence")
    snapshot_ids = tuple(values)
    try:
        _required_unique_text(snapshot_ids, "evidence_snapshot_ids")
    except ValueError as exc:
        raise _CanonicalClaimFailure("invalid_evidence") from exc
    return tuple(sorted(snapshot_ids))


def _validate_canonical_claim_bindings(
    *,
    coverage_ledger: CoverageLedger,
    claim_requirement: ClaimRequirement,
    source_inventory: SourceInventory,
    version_manifest: VersionManifest,
    scope_authority: CoverageScopeAuthority,
    authorization_binding: CoverageAuthorizationBinding,
    source_inventories: tuple[SourceInventory, ...] = (),
    version_manifests: tuple[VersionManifest, ...] = (),
    scope_authorities: tuple[CoverageScopeAuthority, ...] = (),
    authorization_bindings: tuple[CoverageAuthorizationBinding, ...] = (),
) -> None:
    if not all(
        isinstance(value, expected_type)
        for value, expected_type in (
            (coverage_ledger, CoverageLedger),
            (claim_requirement, ClaimRequirement),
            (source_inventory, SourceInventory),
            (version_manifest, VersionManifest),
            (scope_authority, CoverageScopeAuthority),
            (authorization_binding, CoverageAuthorizationBinding),
        )
    ):
        raise _CanonicalClaimFailure("invalid_binding")
    if (
        coverage_ledger.authorization_binding != authorization_binding
        or scope_authority.authorization_binding != authorization_binding
    ):
        if not coverage_ledger.is_aggregate:
            raise _CanonicalClaimFailure("permission_denied")
    if coverage_ledger.is_aggregate:
        if (
            not source_inventories
            or not version_manifests
            or not scope_authorities
            or not authorization_bindings
            or scope_authority != scope_authorities[0]
            or authorization_binding != authorization_bindings[0]
        ):
            raise _CanonicalClaimFailure("invalid_binding")
        try:
            if not coverage_ledger.aggregate_binding_valid_for_claim(
                source_inventories,
                claim_requirement,
                version_manifests,
                authorization_bindings,
                scope_authorities,
            ):
                raise _CanonicalClaimFailure("invalid_binding")
        except ContractValidationError as exc:
            raise _CanonicalClaimFailure("invalid_binding") from exc
        return
    if version_manifest.index_freshness != "fresh":
        raise _CanonicalClaimFailure("invalid_binding")
    if coverage_ledger.scope_partition is None:
        raise _CanonicalClaimFailure("invalid_binding")
    if coverage_ledger.scope_partition.scope_authority != scope_authority:
        raise _CanonicalClaimFailure("invalid_binding")
    try:
        scope_valid = scope_authority.validate_for_claim(
            source_inventory,
            claim_requirement,
            version_manifest,
            authorization_binding,
            scope_authority.scope_policy,
        )
        ledger_valid = coverage_ledger.binding_valid_for_claim(
            source_inventory,
            claim_requirement,
            version_manifest,
            authorization_binding,
            scope_authority,
        )
    except ContractValidationError as exc:
        raise _CanonicalClaimFailure("invalid_binding") from exc
    if not scope_valid or not ledger_valid:
        raise _CanonicalClaimFailure("invalid_binding")


def _validate_matched_structural_observations(
    *,
    coverage_ledger: CoverageLedger,
    source_inventory: SourceInventory,
    version_manifest: VersionManifest,
    scope_authority: CoverageScopeAuthority,
    resolved_matches: tuple[_ResolvedStructuralMatch, ...],
    source_inventories: tuple[SourceInventory, ...] = (),
    version_manifests: tuple[VersionManifest, ...] = (),
    scope_authorities: tuple[CoverageScopeAuthority, ...] = (),
) -> None:
    if coverage_ledger.is_aggregate:
        inventory_by_id = {
            inventory.source_inventory_id: inventory for inventory in source_inventories
        }
        component_pairs = sorted(
            zip(source_inventories, version_manifests, scope_authorities, strict=True),
            key=lambda component: component[0].source_inventory_id,
        )
        manifest_by_inventory = {
            inventory.source_inventory_id: manifest
            for inventory, manifest, _authority in component_pairs
        }
        authority_by_inventory = {
            inventory.source_inventory_id: authority
            for inventory, _manifest, authority in component_pairs
        }
        searched_ids = set(coverage_ledger.searched_structural_observation_ids)
        for observation in _matched_structural_observations(resolved_matches):
            item = next(
                (
                    candidate
                    for inventory in inventory_by_id.values()
                    for candidate in inventory.items
                    if candidate.source_inventory_item_id == observation.source_inventory_item_id
                ),
                None,
            )
            if item is None or item.source_inventory_id is None:
                raise _CanonicalClaimFailure("invalid_evidence")
            inventory = inventory_by_id.get(item.source_inventory_id)
            manifest = manifest_by_inventory.get(item.source_inventory_id)
            authority = authority_by_inventory.get(item.source_inventory_id)
            partition = next(
                (
                    candidate.observation_partition_for(item.source_inventory_item_id)
                    for candidate in coverage_ledger.scope_partitions
                    if candidate.source_inventory_id == item.source_inventory_id
                ),
                None,
            )
            matching_proof = any(
                record.source_inventory_id == item.source_inventory_id
                and record.claim_requirement_id == coverage_ledger.claim_requirement_id
                and record.version_manifest_id
                == (manifest.version_manifest_id if manifest is not None else None)
                and record.inventory_item_id == item.source_inventory_item_id
                and record.proof_kind in {"structural", "combined", "fallback"}
                and observation.source_observation_id in record.structural_observation_ids
                for record in coverage_ledger.proof_records
            )
            if (
                inventory is None
                or manifest is None
                or authority is None
                or partition is None
                or item.processing_state != "parsed"
                or item.source_inventory_item_id not in coverage_ledger.relevant_inventory_item_ids
                or item.source_inventory_item_id not in authority.authorized_relevant_item_ids
                or observation.source_observation_id not in item.source_observation_ids
                or observation.source_observation_id not in partition.structural_observation_ids
                or observation.source_observation_id not in searched_ids
                or not matching_proof
                or observation.source_asset_id != inventory.source_asset_id
                or observation.source_asset_id != item.source_asset_id
                or observation.source_fingerprint != manifest.source_fingerprint
                or observation.source_fingerprint != item.source_fingerprint
                or observation.parser_fingerprint != manifest.parser_fingerprint
                or observation.parser_fingerprint != item.parser_fingerprint
            ):
                raise _CanonicalClaimFailure("invalid_evidence")
            _validate_structural_topology(observation)
        return
    scope_partition = coverage_ledger.scope_partition
    if scope_partition is None:
        raise _CanonicalClaimFailure("invalid_binding")
    observations = _matched_structural_observations(resolved_matches)
    item_by_id = {item.source_inventory_item_id: item for item in source_inventory.items}
    relevant_item_ids = set(coverage_ledger.relevant_inventory_item_ids)
    authorized_item_ids = set(scope_authority.authorized_relevant_item_ids)
    searched_ids = set(coverage_ledger.searched_structural_observation_ids)
    for observation in observations:
        item = item_by_id.get(observation.source_inventory_item_id)
        partition = scope_partition.observation_partition_for(observation.source_inventory_item_id)
        matching_proof = any(
            record.source_inventory_id == source_inventory.source_inventory_id
            and record.claim_requirement_id == coverage_ledger.claim_requirement_id
            and record.version_manifest_id == version_manifest.version_manifest_id
            and record.inventory_item_id == observation.source_inventory_item_id
            and record.proof_kind in {"structural", "combined", "fallback"}
            and observation.source_observation_id in record.structural_observation_ids
            for record in coverage_ledger.proof_records
        )
        if (
            item is None
            or partition is None
            or item.processing_state != "parsed"
            or item.source_inventory_item_id not in relevant_item_ids
            or item.source_inventory_item_id not in authorized_item_ids
            or observation.source_observation_id not in item.source_observation_ids
            or observation.source_observation_id not in partition.structural_observation_ids
            or observation.source_observation_id not in searched_ids
            or not matching_proof
            or observation.source_asset_id != source_inventory.source_asset_id
            or observation.source_asset_id != item.source_asset_id
            or observation.source_fingerprint != version_manifest.source_fingerprint
            or observation.source_fingerprint != item.source_fingerprint
            or observation.parser_fingerprint != version_manifest.parser_fingerprint
            or observation.parser_fingerprint != item.parser_fingerprint
        ):
            raise _CanonicalClaimFailure("invalid_evidence")
        _validate_structural_topology(observation)


def _validate_structural_topology(observation: StructuralObservation) -> None:
    column_ordinals = {column.column_ordinal for column in observation.columns}
    row_ordinals = {row.row_ordinal for row in observation.rows}
    occupied_coordinates: set[tuple[int, int]] = set()
    for row in observation.rows:
        for cell in row.cells:
            covered_rows = set(
                range(
                    cell.row_ordinal,
                    cell.row_ordinal + cell.row_span,
                )
            )
            covered_columns = set(
                range(
                    cell.column_ordinal,
                    cell.column_ordinal + cell.column_span,
                )
            )
            covered_coordinates = {
                (row_ordinal, column_ordinal)
                for row_ordinal in covered_rows
                for column_ordinal in covered_columns
            }
            if (
                cell.row_ordinal != row.row_ordinal
                or not covered_rows.issubset(row_ordinals)
                or not covered_columns.issubset(column_ordinals)
                or occupied_coordinates & covered_coordinates
            ):
                raise _CanonicalClaimFailure("invalid_evidence")
            occupied_coordinates.update(covered_coordinates)


def _diagnostic_structural_topology_mismatch_reasons(
    observation: StructuralObservation,
) -> frozenset[str]:
    """Classify only the typed geometry surface used by canonical validation."""

    column_ordinals = {column.column_ordinal for column in observation.columns}
    row_ordinals = {row.row_ordinal for row in observation.rows}
    occupied_coordinates: set[tuple[int, int]] = set()
    reasons: set[str] = set()
    for row in observation.rows:
        for cell in row.cells:
            covered_rows = set(
                range(
                    cell.row_ordinal,
                    cell.row_ordinal + cell.row_span,
                )
            )
            covered_columns = set(
                range(
                    cell.column_ordinal,
                    cell.column_ordinal + cell.column_span,
                )
            )
            covered_coordinates = {
                (row_ordinal, column_ordinal)
                for row_ordinal in covered_rows
                for column_ordinal in covered_columns
            }
            if cell.row_ordinal != row.row_ordinal:
                reasons.add("row_anchor_mismatch")
            if not covered_rows.issubset(row_ordinals):
                reasons.add("row_span_outside")
            if not covered_columns.issubset(column_ordinals):
                reasons.add("column_span_outside")
            if occupied_coordinates & covered_coordinates:
                reasons.add("coordinate_overlap")
            occupied_coordinates.update(covered_coordinates)
    return frozenset(reasons)


def _derive_canonical_structural_values(
    requirement: ClaimRequirement,
    resolved_matches: tuple[_ResolvedStructuralMatch, ...],
) -> _CanonicalStructuralDerivation:
    applicable, latest_chronology_complete = _applicable_structural_matches(
        requirement,
        resolved_matches,
    )
    values: list[_CanonicalStructuralValue] = []
    for match in applicable:
        observation = match.structural_observation
        for row_ordinal in match.matched_row_ordinals:
            cell = _structural_cell_at(
                observation,
                row_ordinal=row_ordinal,
                column_ordinal=match.value_column_ordinal,
            )
            if cell.cell_state != "populated":
                continue
            display_value = (cell.value or "").strip()
            normalized_value = _canonical_text(cell.normalized_value or display_value)
            if not display_value or not normalized_value:
                raise _CanonicalClaimFailure("invalid_evidence")
            values.append(
                _CanonicalStructuralValue(
                    normalized_value=normalized_value,
                    display_value=display_value,
                    source_observation_id=observation.source_observation_id,
                    source_inventory_item_id=observation.source_inventory_item_id,
                )
            )
    return _CanonicalStructuralDerivation(
        values=tuple(
            sorted(
                values,
                key=lambda value: (
                    value.normalized_value,
                    _canonical_text(value.display_value),
                    value.source_observation_id,
                    value.source_inventory_item_id,
                ),
            )
        ),
        latest_chronology_complete=latest_chronology_complete,
    )


def _target_structural_column_ordinal(
    requirement: ClaimRequirement,
    observation: StructuralObservation,
) -> int:
    field_name = requirement.predicate or requirement.target
    normalized_field_name = _canonical_text(field_name)
    matching_columns = tuple(
        column.column_ordinal
        for column in observation.columns
        if normalized_field_name
        in {
            _canonical_text(column.normalized_header),
            _canonical_text(column.original_header),
        }
    )
    if len(matching_columns) != 1:
        raise _CanonicalClaimFailure("invalid_evidence")
    return matching_columns[0]


def _structural_cell_at(
    observation: StructuralObservation,
    *,
    row_ordinal: int,
    column_ordinal: int,
) -> StructuralCell:
    if not any(row.row_ordinal == row_ordinal for row in observation.rows):
        raise _CanonicalClaimFailure("invalid_evidence")
    covering_cells = tuple(
        cell
        for row in observation.rows
        for cell in row.cells
        if cell.row_ordinal <= row_ordinal < cell.row_ordinal + cell.row_span
        and cell.column_ordinal <= column_ordinal < cell.column_ordinal + cell.column_span
    )
    if len(covering_cells) != 1:
        raise _CanonicalClaimFailure("invalid_evidence")
    return covering_cells[0]


def _applicable_structural_matches(
    requirement: ClaimRequirement,
    matches: tuple[_ResolvedStructuralMatch, ...],
) -> tuple[tuple[_ResolvedStructuralMatch, ...], bool]:
    chronology_complete = True
    as_of_value = requirement.parameters.get("as_of_world_time")
    as_of_instant = None
    if as_of_value is not None:
        as_of_instant = _canonical_observed_at(as_of_value)
        if as_of_instant is None:
            chronology_complete = False
        else:
            filtered_matches: list[_ResolvedStructuralMatch] = []
            for match in matches:
                observed_at = _canonical_observed_at(match.structural_observation.observed_at)
                if observed_at is None:
                    chronology_complete = False
                    filtered_matches.append(match)
                elif observed_at <= as_of_instant:
                    filtered_matches.append(match)
            matches = tuple(filtered_matches)
    if requirement.kind not in _CANONICAL_VALUE_CLAIM_KINDS:
        return matches, chronology_complete
    by_lineage: dict[str, list[_ResolvedStructuralMatch]] = {}
    for match in matches:
        observation = match.structural_observation
        lineage_id = observation.message_lineage_id or observation.source_inventory_item_id
        by_lineage.setdefault(lineage_id, []).append(match)
    selected: list[_ResolvedStructuralMatch] = []
    for group in by_lineage.values():
        current = [
            match
            for match in group
            if match.structural_observation.current_depth == 0
            and match.structural_observation.quoted_depth == 0
        ]
        if current:
            selected.extend(current)
            continue
        if requirement.kind == "current_value":
            continue
        nearest_depth = min(
            (
                match.structural_observation.quoted_depth,
                match.structural_observation.current_depth,
            )
            for match in group
        )
        selected.extend(
            match
            for match in group
            if (
                match.structural_observation.quoted_depth,
                match.structural_observation.current_depth,
            )
            == nearest_depth
        )
    latest_chronology_complete = chronology_complete
    if requirement.kind == "latest_value":
        dated = tuple(
            (
                _canonical_observed_at(match.structural_observation.observed_at),
                match,
            )
            for match in selected
        )
        latest_chronology_complete = latest_chronology_complete and all(
            instant is not None for instant, _ in dated
        )
        if latest_chronology_complete and dated:
            latest = max(instant for instant, _ in dated if instant is not None)
            selected = [match for instant, match in dated if instant == latest]
    return (
        tuple(
            sorted(
                selected,
                key=lambda match: (
                    match.structural_observation.source_observation_id,
                    match.matched_row_ordinals,
                    match.value_column_ordinal,
                    match.structural_observation.structural_observation_id,
                ),
            )
        ),
        latest_chronology_complete,
    )


def _canonical_observed_at(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _canonical_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(normalize("NFKC", value).casefold().split())


def _derive_canonical_claim_state(
    *,
    coverage_ledger: CoverageLedger,
    claim_requirement: ClaimRequirement,
    source_inventory: SourceInventory,
    version_manifest: VersionManifest,
    scope_authority: CoverageScopeAuthority,
    authorization_binding: CoverageAuthorizationBinding,
    structural_values: tuple[_CanonicalStructuralValue, ...],
    latest_chronology_complete: bool,
    source_inventories: tuple[SourceInventory, ...] = (),
    version_manifests: tuple[VersionManifest, ...] = (),
    scope_authorities: tuple[CoverageScopeAuthority, ...] = (),
    authorization_bindings: tuple[CoverageAuthorizationBinding, ...] = (),
) -> str:
    try:
        if coverage_ledger.is_aggregate:
            complete = coverage_ledger.aggregate_usable_for_claim(
                source_inventories,
                claim_requirement,
                version_manifests,
                authorization_bindings,
                scope_authorities,
            )
        else:
            complete = coverage_ledger.usable_for_claim(
                source_inventory,
                claim_requirement,
                version_manifest,
                authorization_binding,
                scope_authority,
            )
    except ContractValidationError as exc:
        raise _CanonicalClaimFailure("invalid_binding") from exc
    if "as_of_world_time" in claim_requirement.parameters and not latest_chronology_complete:
        return AnswerClaimState.INSUFFICIENT_COVERAGE.value
    distinct_values = {value.normalized_value for value in structural_values}
    if claim_requirement.kind in _CANONICAL_VALUE_CLAIM_KINDS and len(distinct_values) > 1:
        if (
            complete
            or (
                not coverage_ledger.is_aggregate
                and coverage_ledger.has_direct_incompatible_values(
                    source_inventory,
                    claim_requirement,
                    version_manifest,
                    authorization_binding,
                    scope_authority,
                )
            )
            or (
                coverage_ledger.is_aggregate
                and coverage_ledger.has_aggregate_direct_incompatible_values(
                    source_inventories,
                    claim_requirement,
                    version_manifests,
                    authorization_bindings,
                    scope_authorities,
                )
            )
        ):
            return AnswerClaimState.CONFLICT.value
        return AnswerClaimState.INSUFFICIENT_COVERAGE.value
    if not latest_chronology_complete and claim_requirement.kind == "latest_value":
        return AnswerClaimState.INSUFFICIENT_COVERAGE.value
    if structural_values:
        if complete:
            return AnswerClaimState.FOUND.value
        if (
            claim_requirement.kind == "existential_witness"
            and claim_requirement.parameters.get("support_only_completeness") is True
            and coverage_ledger.has_direct_authorized_witness(
                source_inventory,
                claim_requirement,
                version_manifest,
                authorization_binding,
                scope_authority,
            )
        ):
            return AnswerClaimState.FOUND.value
        return AnswerClaimState.INSUFFICIENT_COVERAGE.value
    if complete:
        return AnswerClaimState.NOT_FOUND_WITHIN_COMPLETE_SCOPE.value
    return AnswerClaimState.INSUFFICIENT_COVERAGE.value


def _canonical_claim_reason_codes(
    state: str,
    *,
    coverage_ledger: CoverageLedger,
    claim_requirement: ClaimRequirement,
    has_populated_values: bool,
    latest_chronology_complete: bool,
) -> tuple[str, ...]:
    if state == AnswerClaimState.FOUND.value:
        return ("canonical_populated_value_found",)
    if state == AnswerClaimState.CONFLICT.value:
        return ("canonical_incompatible_current_values",)
    if state == AnswerClaimState.NOT_FOUND_WITHIN_COMPLETE_SCOPE.value:
        return ("complete_scope_no_populated_value",)
    reasons: list[str] = [
        (
            "populated_value_without_sufficient_coverage"
            if has_populated_values
            else "no_match_without_complete_scope"
        )
    ]
    if coverage_ledger.omitted_inventory_item_ids:
        reasons.append("coverage_omitted_inventory")
    if coverage_ledger.failed_inventory_item_ids:
        reasons.append("coverage_failed_inventory")
    if coverage_ledger.unsupported_inventory_item_ids:
        reasons.append("coverage_unsupported_inventory")
    if coverage_ledger.redacted_inventory_item_ids:
        reasons.append("coverage_redacted_inventory")
    if coverage_ledger.fallback_usage.status not in {"not_required", "completed"}:
        reasons.append(f"coverage_fallback_{coverage_ledger.fallback_usage.status}")
    if not latest_chronology_complete:
        reasons.append(
            "latest_value_chronology_incomplete"
            if claim_requirement.kind == "latest_value"
            else "as_of_world_time_chronology_incomplete"
        )
    return tuple(reasons)


def _canonical_display_values(
    values: tuple[_CanonicalStructuralValue, ...],
) -> tuple[str, ...]:
    display_by_normalized: dict[str, str] = {}
    for value in values:
        existing = display_by_normalized.get(value.normalized_value)
        if existing is None or _canonical_text(value.display_value) < _canonical_text(existing):
            display_by_normalized[value.normalized_value] = value.display_value
    return tuple(dict.fromkeys(display_by_normalized[key] for key in sorted(display_by_normalized)))


def _canonical_compatibility_views(
    claim: AnswerClaim,
    *,
    coverage_ledger: CoverageLedger,
    claim_requirement: ClaimRequirement,
    observations: tuple[StructuralObservation, ...],
    canonical_values: tuple[str, ...],
) -> tuple[EvidenceCoverage, AnswerabilityDecision]:
    field_name = claim_requirement.predicate or claim_requirement.target
    target_found = claim.state in {
        AnswerClaimState.FOUND.value,
        AnswerClaimState.CONFLICT.value,
    }
    conflict = claim.state == AnswerClaimState.CONFLICT.value
    matched_item_count = len({observation.source_inventory_item_id for observation in observations})
    exhaustive = coverage_ledger.complete_authorized_scope
    coverage = EvidenceCoverage(
        target_found=target_found,
        total_source_item_count=len(coverage_ledger.relevant_inventory_item_ids),
        returned_source_item_count=(matched_item_count if target_found else 0),
        expected_assembled_observation_count=len(observations),
        assembled_observation_count=len(observations),
        assembly_complete=(claim.state != AnswerClaimState.INSUFFICIENT_COVERAGE.value),
        required_properties=(field_name,),
        covered_properties=((field_name,) if target_found and canonical_values else ()),
        missing_properties=(() if target_found else (field_name,)),
        required_projection_fields=(),
        covered_projection_fields=(),
        missing_projection_fields=(),
        conflicting_assertion_keys=((field_name,) if conflict else ()),
        is_exhaustive=exhaustive,
        has_more=coverage_ledger.display_pagination.has_more,
    )
    status_by_claim = {
        AnswerClaimState.FOUND.value: "sufficient_evidence",
        AnswerClaimState.CONFLICT.value: "conflicting_evidence",
        AnswerClaimState.NOT_FOUND_WITHIN_COMPLETE_SCOPE.value: "target_not_found",
        AnswerClaimState.INSUFFICIENT_COVERAGE.value: "partial_evidence",
    }
    return (
        coverage,
        AnswerabilityDecision(
            status=status_by_claim[claim.state],
            reason_codes=claim.reason_codes,
        ),
    )


def _render_enforced_canonical_answer(
    claim: AnswerClaim,
    *,
    claim_requirement: ClaimRequirement,
    canonical_values: tuple[str, ...],
) -> str:
    field_name = claim_requirement.predicate or claim_requirement.target
    if claim.state == AnswerClaimState.FOUND.value:
        rendered_values = ", ".join(canonical_values)
        return f"FOUND: Governed evidence supports {field_name}: " f"{rendered_values}."
    if claim.state == AnswerClaimState.CONFLICT.value:
        return (
            "CONFLICT: Governed evidence contains incompatible current "
            f"values for {field_name}; no single value is selected."
        )
    if claim.state == AnswerClaimState.NOT_FOUND_WITHIN_COMPLETE_SCOPE.value:
        return (
            "NOT_FOUND_WITHIN_COMPLETE_SCOPE: No populated value was found "
            "within the complete authorized scope."
        )
    return (
        "INSUFFICIENT_COVERAGE: Coverage is insufficient; no definitive "
        "positive or negative answer is permitted."
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
