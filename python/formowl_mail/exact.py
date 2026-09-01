"""Deterministic exact inventory execution over an authorized EffectiveGraphView."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from formowl_contract import ContractValidationError, sha256_json
from formowl_graph import EffectiveGraphView

from ._guards import assert_public_payload_safe
from .semantic_plan import EXACT_QUERY_GRAMMAR_ROLES, SemanticQueryPlan

_CURRENT_STATES = {"active", "current", "effective", "valid"}
_SUPERSEDED_STATES = {"expired", "stale", "superseded", "withdrawn"}
SOURCE_OCCURRENCE_FILTER_SLOT_POLICIES = (
    "identifier_union_v1",
    "combined_present_intersection_v1",
)
_SOURCE_OCCURRENCE_PROJECTION_STATUSES = {
    "source_provided",
    "candidate_only",
}
_SOURCE_ASSET_GAP_REASONS = {
    "encrypted",
    "redacted",
    "unresolved",
    "unsupported",
}
_SOURCE_OCCURRENCE_PROJECTION_CAPABILITY_BINDING_V1 = (
    "source_occurrence_projection_capability_binding_v1"
)
_SOURCE_OCCURRENCE_COLUMN_CAPABILITY_BINDING_V1 = (
    "source_occurrence_column_capability_binding_v1"
)
SOURCE_OCCURRENCE_LEXICAL_TERM_ROLES = (
    "filter_value",
    "projection_field",
)


def source_occurrence_projection_capability_hash(value_hash: str) -> str:
    return sha256_json(
        [_SOURCE_OCCURRENCE_PROJECTION_CAPABILITY_BINDING_V1, value_hash]
    )


def source_occurrence_column_capability_hash(normalized_field: str) -> str:
    return sha256_json(
        [_SOURCE_OCCURRENCE_COLUMN_CAPABILITY_BINDING_V1, normalized_field]
    )


@dataclass(frozen=True)
class ExactInventoryItem:
    item_hash: str
    cited_observation_hashes: tuple[str, ...]
    governed_references: tuple[tuple[str, str], ...] = ()
    matched_normalized_value_hashes: tuple[str, ...] = ()
    ambiguous_identifier: bool = False
    structured_values: tuple[tuple[str, str, str, str], ...] = ()
    structure_status: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "item_hash": self.item_hash,
            "cited_observation_hashes": list(self.cited_observation_hashes),
            "citation_count": len(self.cited_observation_hashes),
        }
        if self.governed_references:
            payload.update(
                governed_references=[
                    {
                        "citation_hash": citation_hash,
                        "occurrence_lineage_fingerprint": lineage_fingerprint,
                    }
                    for citation_hash, lineage_fingerprint in self.governed_references
                ],
                matched_normalized_value_hashes=list(
                    self.matched_normalized_value_hashes
                ),
                ambiguous_identifier=self.ambiguous_identifier,
            )
        if self.structured_values:
            payload["structured_values"] = [
                {
                    "field": field,
                    "value": value,
                    "citation_hash": citation_hash,
                    "occurrence_lineage_fingerprint": lineage_fingerprint,
                }
                for field, value, citation_hash, lineage_fingerprint in self.structured_values
            ]
            payload["structure_status"] = self.structure_status
        assert_public_payload_safe(payload, "exact_inventory_item")
        return payload


@dataclass(frozen=True)
class ExactCoverageContract:
    coverage_fingerprint: str
    view_revision_fingerprint: str
    visible_node_count: int
    inventory_schema_record_count: int
    filter_term_count: int
    identifier_filter_count: int
    topic_filter_count: int
    eligible_record_count: int
    enumerated_record_count: int
    cited_observation_count: int
    missing_evidence_record_count: int
    access_required_scope_count: int
    authorized_scope_complete: bool
    global_scope_complete: bool
    incompleteness_reason_hashes: tuple[str, ...]

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "coverage_fingerprint": self.coverage_fingerprint,
            "view_revision_fingerprint": self.view_revision_fingerprint,
            "visible_node_count": self.visible_node_count,
            "inventory_schema_record_count": self.inventory_schema_record_count,
            "filter_term_count": self.filter_term_count,
            "identifier_filter_count": self.identifier_filter_count,
            "topic_filter_count": self.topic_filter_count,
            "eligible_record_count": self.eligible_record_count,
            "enumerated_record_count": self.enumerated_record_count,
            "cited_observation_count": self.cited_observation_count,
            "missing_evidence_record_count": self.missing_evidence_record_count,
            "access_required_scope_count": self.access_required_scope_count,
            "authorized_scope_complete": self.authorized_scope_complete,
            "global_scope_complete": self.global_scope_complete,
            "incompleteness_reason_hashes": list(self.incompleteness_reason_hashes),
        }
        assert_public_payload_safe(payload, "exact_coverage_contract")
        return payload


@dataclass(frozen=True)
class DeterministicExactExecutionResult:
    status: str
    query_hash: str
    plan_fingerprint: str
    operation_hash: str
    inventory_kind_hash: str
    exact_count: int
    returned_item_count: int
    cited_observation_count: int
    items: tuple[ExactInventoryItem, ...]
    coverage: ExactCoverageContract
    result_fingerprint: str
    source_occurrence_page: Mapping[str, Any] | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": "formowl_deterministic_exact_execution_result_v1",
            "status": self.status,
            "query_hash": self.query_hash,
            "plan_fingerprint": self.plan_fingerprint,
            "operation_hash": self.operation_hash,
            "inventory_kind_hash": self.inventory_kind_hash,
            "exact_count": self.exact_count,
            "returned_item_count": self.returned_item_count,
            "cited_observation_count": self.cited_observation_count,
            "items": [item.to_safe_dict() for item in self.items],
            "coverage": self.coverage.to_safe_dict(),
            "result_fingerprint": self.result_fingerprint,
        }
        if self.source_occurrence_page is not None:
            payload["source_occurrence_page"] = dict(self.source_occurrence_page)
        assert_public_payload_safe(payload, "deterministic_exact_execution_result")
        return payload


@dataclass(frozen=True)
class AuthorizedSourceOccurrence:
    item_hash: str
    value_bindings: tuple[tuple[str, str, str, str], ...]
    projection_bindings: tuple[tuple[str, str, str, str], ...] = ()
    structure_status: str | None = None
    structured_column_bindings: tuple[
        tuple[str, str, str, str, str, str, str], ...
    ] = ()


@dataclass(frozen=True)
class SourceOccurrenceQueryPartition:
    filter_term_hashes: tuple[str, ...]
    projection_column_hashes: tuple[str, ...]
    column_value_hash_pairs: tuple[tuple[str, str], ...]
    lexical_term_ledger: tuple[tuple[str, str, str, str], ...]


@dataclass(frozen=True)
class SourceOccurrenceProvider:
    provider_id: str
    inventory_kind_alias: str
    resource_kind: str
    normalized_field: str
    predicate: str
    operator: str
    requester_user_id: str
    workspace_id: str
    source_scope_ids: tuple[str, ...]
    authorized_scope_fingerprint: str
    occurrences: tuple[AuthorizedSourceOccurrence, ...]
    filter_slot_policy: str = "identifier_union_v1"
    unresolved_count: int = 0
    unsupported_count: int = 0
    encrypted_count: int = 0
    redacted_count: int = 0
    authorized_occurrence_scope_count: int | None = None
    extractable_occurrence_scope_count: int | None = None
    source_asset_reason_counts: tuple[tuple[str, int], ...] = ()
    duplicate_policy: str = "preserve_source_occurrence_v1"

    def __post_init__(self) -> None:
        if self.filter_slot_policy not in SOURCE_OCCURRENCE_FILTER_SLOT_POLICIES:
            raise ContractValidationError(
                "source occurrence filter slot policy is invalid"
            )
        for count in (
            self.unresolved_count,
            self.unsupported_count,
            self.encrypted_count,
            self.redacted_count,
        ):
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ContractValidationError("source occurrence coverage is invalid")
        if (
            self.source_asset_reason_counts
            != tuple(sorted(self.source_asset_reason_counts))
            or len({reason for reason, _ in self.source_asset_reason_counts})
            != len(self.source_asset_reason_counts)
            or any(
                reason not in _SOURCE_ASSET_GAP_REASONS
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count < 1
                for reason, count in self.source_asset_reason_counts
            )
        ):
            raise ContractValidationError("source asset coverage reasons are invalid")
        explicit_scope_counts = (
            self.authorized_occurrence_scope_count,
            self.extractable_occurrence_scope_count,
        )
        if any(value is not None for value in explicit_scope_counts):
            if not all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
                for value in explicit_scope_counts
            ):
                raise ContractValidationError("source occurrence coverage is invalid")
            assert self.authorized_occurrence_scope_count is not None
            assert self.extractable_occurrence_scope_count is not None
            if self.authorized_occurrence_scope_count != (
                self.extractable_occurrence_scope_count
                + self.unresolved_count
                + self.unsupported_count
                + self.encrypted_count
                + self.redacted_count
            ):
                raise ContractValidationError(
                    "source occurrence coverage partition is invalid"
                )
        ordered_occurrences = tuple(
            sorted(self.occurrences, key=lambda value: value.item_hash)
        )
        postings: dict[str, list[int]] = {}
        normalized_variants: dict[str, set[str]] = {}
        projection_capability_hashes: set[str] = set()
        projection_candidate_columns: dict[str, set[str]] = {}
        value_candidate_columns: dict[str, set[str]] = {}
        column_value_postings: dict[tuple[str, str], list[int]] = {}
        column_postings: dict[str, list[int]] = {}
        for position, item in enumerate(ordered_occurrences):
            projection_reference_pairs = {
                (citation_hash, lineage_fingerprint)
                for _, _, citation_hash, lineage_fingerprint in item.projection_bindings
            }
            value_reference_pairs = {
                (citation_hash, lineage_fingerprint)
                for _, _, citation_hash, lineage_fingerprint in item.value_bindings
            }
            if item.projection_bindings:
                if (
                    item.structure_status
                    not in _SOURCE_OCCURRENCE_PROJECTION_STATUSES
                    or not projection_reference_pairs <= value_reference_pairs
                ):
                    raise ContractValidationError(
                        "source occurrence structured projection is invalid"
                    )
            elif item.structure_status is not None:
                raise ContractValidationError(
                    "source occurrence structured projection is invalid"
                )
            structured_projection_bindings = {
                (field, value, citation_hash, lineage_fingerprint)
                for (
                    _column_hash,
                    _column_candidate_hash,
                    _value_hash,
                    field,
                    value,
                    citation_hash,
                    lineage_fingerprint,
                ) in item.structured_column_bindings
            }
            if (
                item.structured_column_bindings
                and (
                    self.filter_slot_policy
                    != "combined_present_intersection_v1"
                    or not structured_projection_bindings
                    <= set(item.projection_bindings)
                )
            ):
                raise ContractValidationError(
                    "source occurrence structured column binding is invalid"
                )
            occurrence_column_hashes: set[str] = set()
            occurrence_column_value_pairs: set[tuple[str, str]] = set()
            for (
                column_hash,
                column_candidate_hash,
                value_hash,
                _field,
                _value,
                _citation_hash,
                _lineage_fingerprint,
            ) in item.structured_column_bindings:
                if not all(
                    isinstance(value, str)
                    and value.startswith("sha256:")
                    and len(value) == len("sha256:") + 64
                    for value in (
                        column_hash,
                        column_candidate_hash,
                        value_hash,
                    )
                ):
                    raise ContractValidationError(
                        "source occurrence structured column binding is invalid"
                    )
                projection_candidate_columns.setdefault(
                    column_candidate_hash,
                    set(),
                ).add(column_hash)
                value_candidate_columns.setdefault(value_hash, set()).add(
                    column_hash
                )
                occurrence_column_hashes.add(column_hash)
                occurrence_column_value_pairs.add((column_hash, value_hash))
            for column_hash in occurrence_column_hashes:
                column_postings.setdefault(column_hash, []).append(position)
            for pair in occurrence_column_value_pairs:
                column_value_postings.setdefault(pair, []).append(position)
            occurrence_value_hashes: set[str] = set()
            for normalized_hash, variant_hash, _, _ in item.value_bindings:
                if variant_hash == source_occurrence_projection_capability_hash(
                    normalized_hash
                ):
                    projection_capability_hashes.add(normalized_hash)
                    continue
                occurrence_value_hashes.update((normalized_hash, variant_hash))
                normalized_variants.setdefault(normalized_hash, set()).add(
                    variant_hash
                )
            for value_hash in occurrence_value_hashes:
                postings.setdefault(value_hash, []).append(position)
        extended_contract = (
            self.filter_slot_policy != "identifier_union_v1"
            or self.encrypted_count != 0
            or self.authorized_occurrence_scope_count is not None
            or self.extractable_occurrence_scope_count is not None
            or bool(self.source_asset_reason_counts)
            or any(
                item.projection_bindings
                or item.structure_status is not None
                or item.structured_column_bindings
                for item in self.occurrences
            )
        )
        fingerprint_payload = {
            "contract": [
                self.provider_id,
                self.inventory_kind_alias,
                self.resource_kind,
                self.normalized_field,
                self.predicate,
                self.operator,
                self.requester_user_id,
                self.workspace_id,
                *self.source_scope_ids,
                self.authorized_scope_fingerprint,
                self.duplicate_policy,
            ],
            "occurrences": [
                (
                    [
                        item.item_hash,
                        [list(binding) for binding in item.value_bindings],
                        [list(binding) for binding in item.projection_bindings],
                        item.structure_status,
                        [
                            list(binding)
                            for binding in item.structured_column_bindings
                        ],
                    ]
                    if extended_contract
                    else [
                        item.item_hash,
                        [list(binding) for binding in item.value_bindings],
                    ]
                )
                for item in self.occurrences
            ],
            "counts": (
                [
                    self.unresolved_count,
                    self.unsupported_count,
                    self.encrypted_count,
                    self.redacted_count,
                    self.authorized_occurrence_scope_count,
                    self.extractable_occurrence_scope_count,
                ]
                if extended_contract
                else [
                    self.unresolved_count,
                    self.unsupported_count,
                    self.redacted_count,
                ]
            ),
        }
        if extended_contract:
            fingerprint_payload.update(
                filter_slot_policy=self.filter_slot_policy,
                source_asset_reason_counts=[
                    list(item) for item in self.source_asset_reason_counts
                ],
            )
        object.__setattr__(
            self,
            "_provider_fingerprint",
            sha256_json(fingerprint_payload),
        )
        object.__setattr__(self, "_ordered_occurrences", ordered_occurrences)
        object.__setattr__(
            self,
            "_value_hash_postings",
            MappingProxyType(
                {
                    value_hash: tuple(postings[value_hash])
                    for value_hash in sorted(postings)
                }
            ),
        )
        object.__setattr__(
            self,
            "_normalized_variant_hashes",
            MappingProxyType(
                {
                    normalized_hash: frozenset(
                        normalized_variants[normalized_hash]
                    )
                    for normalized_hash in sorted(normalized_variants)
                }
            ),
        )
        object.__setattr__(
            self,
            "_projection_capability_hashes",
            frozenset(projection_capability_hashes),
        )
        object.__setattr__(
            self,
            "_projection_candidate_columns",
            MappingProxyType(
                {
                    candidate_hash: frozenset(
                        projection_candidate_columns[candidate_hash]
                    )
                    for candidate_hash in sorted(projection_candidate_columns)
                }
            ),
        )
        object.__setattr__(
            self,
            "_value_candidate_columns",
            MappingProxyType(
                {
                    candidate_hash: frozenset(
                        value_candidate_columns[candidate_hash]
                    )
                    for candidate_hash in sorted(value_candidate_columns)
                }
            ),
        )
        object.__setattr__(
            self,
            "_column_value_postings",
            MappingProxyType(
                {
                    pair: tuple(column_value_postings[pair])
                    for pair in sorted(column_value_postings)
                }
            ),
        )
        object.__setattr__(
            self,
            "_column_postings",
            MappingProxyType(
                {
                    column_hash: tuple(column_postings[column_hash])
                    for column_hash in sorted(column_postings)
                }
            ),
        )

    @property
    def provider_fingerprint(self) -> str:
        return self._provider_fingerprint

    def __deepcopy__(self, memo: dict[int, Any]) -> SourceOccurrenceProvider:
        memo[id(self)] = self
        return self

    def partition_ordered_lexical_candidates(
        self,
        ordered_term_candidates: Sequence[tuple[str, Sequence[str]]],
    ) -> SourceOccurrenceQueryPartition:
        """Resolve ordered lexical terms through source-backed table columns."""

        if (
            self.filter_slot_policy != "combined_present_intersection_v1"
            or not ordered_term_candidates
            or not self._column_value_postings
        ):
            raise ContractValidationError(
                "source occurrence query value binding is incomplete"
            )
        lexical_ledger: list[tuple[str, str, str, str]] = []
        column_value_pairs: set[tuple[str, str]] = set()
        projection_columns: set[str] = set()
        for term_hash, raw_candidates in ordered_term_candidates:
            candidates = tuple(raw_candidates)
            if (
                not isinstance(term_hash, str)
                or not term_hash.startswith("sha256:")
                or len(term_hash) != len("sha256:") + 64
                or not candidates
                or len(set(candidates)) != len(candidates)
                or any(
                    not isinstance(candidate_hash, str)
                    or not candidate_hash.startswith("sha256:")
                    or len(candidate_hash) != len("sha256:") + 64
                    for candidate_hash in candidates
                )
            ):
                raise ContractValidationError(
                    "source occurrence lexical candidate binding is invalid"
                )
            grounded_hash: str | None = None
            grounded_role: str | None = None
            grounded_columns: frozenset[str] = frozenset()
            for candidate_hash in candidates:
                value_columns = self._value_candidate_columns.get(
                    candidate_hash,
                    frozenset(),
                )
                projection_columns_for_candidate = (
                    self._projection_candidate_columns.get(
                        candidate_hash,
                        frozenset(),
                    )
                )
                if value_columns and projection_columns_for_candidate:
                    raise ContractValidationError(
                        "source occurrence query lexical binding is ambiguous"
                    )
                if value_columns:
                    grounded_hash = candidate_hash
                    grounded_role = "filter_value"
                    grounded_columns = value_columns
                    break
                if projection_columns_for_candidate:
                    grounded_hash = candidate_hash
                    grounded_role = "projection_field"
                    grounded_columns = projection_columns_for_candidate
                    break
            if grounded_hash is None or grounded_role is None:
                raise ContractValidationError(
                    "source occurrence query candidate binding is incomplete"
                )
            if grounded_role == "filter_value":
                for column_hash in sorted(grounded_columns):
                    column_value_pairs.add((column_hash, grounded_hash))
                    lexical_ledger.append(
                        (term_hash, grounded_role, column_hash, grounded_hash)
                    )
                continue
            if len(grounded_columns) != 1:
                raise ContractValidationError(
                    "source occurrence query column binding is ambiguous"
                )
            column_hash = next(iter(grounded_columns))
            projection_columns.add(column_hash)
            lexical_ledger.append(
                (term_hash, grounded_role, column_hash, grounded_hash)
            )
        if not column_value_pairs:
            raise ContractValidationError(
                "source occurrence query value binding is incomplete"
            )
        return SourceOccurrenceQueryPartition(
            filter_term_hashes=tuple(
                sorted(
                    {
                        value_hash
                        for _column_hash, value_hash in column_value_pairs
                    }
                )
            ),
            projection_column_hashes=tuple(sorted(projection_columns)),
            column_value_hash_pairs=tuple(sorted(column_value_pairs)),
            lexical_term_ledger=tuple(lexical_ledger),
        )


def authorized_source_occurrence_scope_fingerprint(
    *,
    requester_user_id: str,
    workspace_id: str,
    source_scope_ids: Sequence[str],
    authorized_observation_hashes: Sequence[tuple[str, str]],
    source_session_binding_fingerprint: str,
) -> str:
    return sha256_json(
        [
            requester_user_id,
            workspace_id,
            sorted(set(source_scope_ids)),
            sorted(authorized_observation_hashes),
            source_session_binding_fingerprint,
        ]
    )


def _bounded_source_occurrence_candidate_links(
    *,
    plan: SemanticQueryPlan,
    provider: SourceOccurrenceProvider,
    filter_positions: set[int],
) -> dict[int, tuple[set[tuple[str, str]], set[str]]]:
    key_limit = min(24, plan.candidate_limit)
    if len(filter_positions) > key_limit:
        raise ContractValidationError("candidate link source limit exceeded")
    requested_pairs = set(plan.exact_column_value_hash_pairs)
    requested_values = {value_hash for _, value_hash in requested_pairs}
    sources = {}
    for position in sorted(filter_positions):
        bindings = provider._ordered_occurrences[position].structured_column_bindings
        filter_references = {
            (binding[5], binding[6])
            for binding in bindings
            if (binding[0], binding[2]) in requested_pairs
        }
        if not filter_references:
            raise ContractValidationError("candidate filter lineage is incomplete")
        for binding in bindings:
            link_hash = binding[2]
            if link_hash in requested_values:
                continue
            positions, references = sources.setdefault(link_hash, (set(), set()))
            positions.add(position)
            references.update((*filter_references, (binding[5], binding[6])))
            if len(references) > key_limit:
                raise ContractValidationError("candidate link reference limit exceeded")
        if len(sources) > key_limit:
            raise ContractValidationError("candidate link key limit exceeded")
    matches = {}
    for link_hash, (source_positions, source_references) in sorted(sources.items()):
        postings = frozenset(provider._value_hash_postings.get(link_hash, ()))
        if (
            not source_positions <= postings
            or len(postings - source_positions) > min(6, plan.max_fanout)
        ):
            raise ContractValidationError(
                "source occurrence candidate link fanout exceeds limit"
            )
        for target_position in sorted(postings - filter_positions):
            target = provider._ordered_occurrences[target_position]
            if not set(plan.exact_projection_term_hashes) <= {
                binding[0] for binding in target.structured_column_bindings
            }:
                continue
            target_references = {
                (binding[5], binding[6])
                for binding in target.structured_column_bindings
                if binding[2] == link_hash
            }
            if not target_references:
                continue
            references, hashes = matches.setdefault(target_position, (set(), set()))
            references.update(source_references | target_references)
            hashes.update((*requested_values, link_hash))
    return matches


def execute_deterministic_source_occurrence_inventory(
    *,
    plan: SemanticQueryPlan,
    provider: SourceOccurrenceProvider,
    expected_authorized_scope_fingerprint: str,
    page_size: int,
    cursor: str | None,
) -> DeterministicExactExecutionResult:
    """Page exact authorized source occurrences without top-k inference."""

    if (
        plan.query_class != "exact_set_or_inventory"
        or plan.exact_inventory_kind != provider.resource_kind
        or plan.exact_normalized_field != provider.normalized_field
        or plan.exact_predicate != provider.predicate
        or plan.exact_operator != provider.operator
        or plan.requester_user_id != provider.requester_user_id
        or plan.workspace_id != provider.workspace_id
        or plan.source_scope_ids != provider.source_scope_ids
        or provider.authorized_scope_fingerprint != expected_authorized_scope_fingerprint
        or provider.source_scope_ids != tuple(sorted(set(provider.source_scope_ids)))
        or not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or not 1 <= page_size <= 100
    ):
        raise ContractValidationError("source occurrence exact binding is invalid")
    plan_fingerprint = plan.plan_fingerprint
    provider_fingerprint = provider.provider_fingerprint
    query_hashes = _source_occurrence_query_hashes(plan=plan, provider=provider)
    candidate_links = None
    if provider.filter_slot_policy == "identifier_union_v1":
        if not all(
            query_hash in provider._value_hash_postings for query_hash in query_hashes
        ):
            raise ContractValidationError(
                "source occurrence identifier binding is incomplete"
            )
        matched_positions = tuple(
            sorted(
                {
                    position
                    for query_hash in query_hashes
                    for position in provider._value_hash_postings[query_hash]
                }
            )
        )
    else:
        postings_by_value: dict[str, set[int]] = {}
        for pair in plan.exact_column_value_hash_pairs:
            postings_by_value.setdefault(pair[1], set()).update(
                provider._column_value_postings[pair]
            )
        filter_matched_position_set = {
            position
            for position in set.intersection(*postings_by_value.values())
            if provider._ordered_occurrences[position].structure_status
            != "candidate_only"
        }
        matched_position_set = set(filter_matched_position_set)
        for column_hash in plan.exact_projection_term_hashes:
            matched_position_set.intersection_update(
                provider._column_postings[column_hash]
            )
        if not matched_position_set and plan.exact_projection_term_hashes:
            candidate_links = _bounded_source_occurrence_candidate_links(
                plan=plan,
                provider=provider,
                filter_positions=filter_matched_position_set,
            )
            matched_position_set = set()
        matched_positions = tuple(sorted(matched_position_set))
    if provider.filter_slot_policy != "identifier_union_v1":
        matched_positions = tuple(
            position
            for position in matched_positions
            if provider._ordered_occurrences[position].structure_status
            != "candidate_only"
        )
    local_query_hashes = frozenset(
        query_hash
        for query_hash in query_hashes
        if query_hash in provider._normalized_variant_hashes
    )
    ambiguous = {
        query_hash
        for query_hash in local_query_hashes
        if len(provider._normalized_variant_hashes[query_hash]) > 1
    }
    offset = _source_occurrence_cursor_offset(
        cursor,
        plan_fingerprint=plan_fingerprint,
        provider_fingerprint=provider_fingerprint,
        authorized_scope_fingerprint=provider.authorized_scope_fingerprint,
        page_size=page_size,
    )
    if offset > len(matched_positions):
        raise ContractValidationError("source occurrence cursor offset is invalid")
    selected_positions = matched_positions[offset : offset + page_size]
    selected = tuple(
        provider._ordered_occurrences[position] for position in selected_positions
    )
    next_offset = offset + len(selected)
    next_cursor = (
        _source_occurrence_cursor(
            next_offset,
            plan_fingerprint=plan_fingerprint,
            provider_fingerprint=provider_fingerprint,
            authorized_scope_fingerprint=provider.authorized_scope_fingerprint,
            page_size=page_size,
        )
        if next_offset < len(matched_positions)
        else None
    )
    candidate_links_by_position = candidate_links or {}
    projected_items: list[ExactInventoryItem] = []
    for position, item in zip(selected_positions, selected, strict=True):
        citation_hashes: set[str] = set()
        governed_references: set[tuple[str, str]] = set()
        matched_normalized_hashes: set[str] = set()
        matched_ambiguous = False
        if provider.filter_slot_policy == "identifier_union_v1":
            for (
                normalized_hash,
                variant_hash,
                citation_hash,
                lineage_fingerprint,
            ) in item.value_bindings:
                if (
                    normalized_hash not in query_hashes
                    and variant_hash not in query_hashes
                ):
                    continue
                citation_hashes.add(citation_hash)
                governed_references.add((citation_hash, lineage_fingerprint))
                matched_normalized_hashes.add(normalized_hash)
                if normalized_hash in ambiguous:
                    matched_ambiguous = True
            projection_bindings = item.projection_bindings
        else:
            requested_pairs = set(plan.exact_column_value_hash_pairs)
            requested_value_hashes = {
                value_hash for _column_hash, value_hash in requested_pairs
            }
            requested_columns = set(plan.exact_projection_term_hashes)
            projection_bindings_set: set[tuple[str, str, str, str]] = set()
            for (
                normalized_hash,
                variant_hash,
                citation_hash,
                lineage_fingerprint,
            ) in item.value_bindings:
                if (
                    normalized_hash not in requested_value_hashes
                    and variant_hash not in requested_value_hashes
                ):
                    continue
                citation_hashes.add(citation_hash)
                governed_references.add(
                    (citation_hash, lineage_fingerprint)
                )
            for (
                column_hash,
                _column_candidate_hash,
                value_hash,
                field,
                value,
                citation_hash,
                lineage_fingerprint,
            ) in item.structured_column_bindings:
                if (column_hash, value_hash) in requested_pairs:
                    citation_hashes.add(citation_hash)
                    governed_references.add(
                        (citation_hash, lineage_fingerprint)
                    )
                    matched_normalized_hashes.add(value_hash)
                if not requested_columns or column_hash in requested_columns:
                    projection_bindings_set.add(
                        (
                            field,
                            value,
                            citation_hash,
                            lineage_fingerprint,
                        )
                    )
            projection_bindings = tuple(sorted(projection_bindings_set))
            candidate_link_references, candidate_link_hashes = (
                candidate_links_by_position.get(position, ((), ()))
            )
            governed_references.update(candidate_link_references)
            citation_hashes.update(
                citation_hash
                for citation_hash, _lineage_fingerprint in (
                    candidate_link_references
                )
            )
            matched_normalized_hashes.update(candidate_link_hashes)
        projected_items.append(
            ExactInventoryItem(
                item_hash=item.item_hash,
                cited_observation_hashes=tuple(
                    sorted(
                        citation_hashes
                        | {
                            binding[2]
                            for binding in projection_bindings
                        }
                    )
                ),
                governed_references=tuple(
                    sorted(
                        governed_references
                        | {
                            (binding[2], binding[3])
                            for binding in projection_bindings
                        }
                    )
                ),
                matched_normalized_value_hashes=tuple(
                    sorted(matched_normalized_hashes)
                ),
                ambiguous_identifier=matched_ambiguous,
                structured_values=projection_bindings,
                structure_status=(
                    "candidate_only"
                    if candidate_links is not None
                    else item.structure_status
                ),
            ),
        )
    items = tuple(projected_items)
    occurrence_gap_count = (
        provider.unresolved_count
        + provider.unsupported_count
        + provider.encrypted_count
        + provider.redacted_count
    )
    candidate_only_count = sum(
        item.structure_status == "candidate_only" for item in provider.occurrences
    )
    source_asset_gap_count = sum(
        count for _, count in provider.source_asset_reason_counts
    )
    incomplete = bool(
        occurrence_gap_count
        or candidate_only_count
        or source_asset_gap_count
        or candidate_links is not None
    )
    status = "incomplete" if incomplete else "complete_authorized_scope"
    coverage_status = (
        "incomplete"
        if next_cursor is None and incomplete
        else "complete"
        if next_cursor is None
        else "complete_page"
    )
    reason_hashes = tuple(
        sha256_json(reason)
        for reason in (
            *(
                ("source_occurrence_provider_incomplete",)
                if occurrence_gap_count
                else ()
            ),
            *(
                ("source_occurrence_structure_candidate_only",)
                if candidate_only_count or candidate_links is not None
                else ()
            ),
            *(
                ("source_asset_extraction_incomplete",)
                if source_asset_gap_count
                else ()
            ),
        )
    )
    exact_match_count = 0 if candidate_links is not None else len(matched_positions)
    coverage_payload = [
        plan_fingerprint,
        provider_fingerprint,
        exact_match_count,
        len(items),
        offset,
        coverage_status,
        *reason_hashes,
    ]
    cited_hashes = {
        observation_hash
        for item in items
        for observation_hash in item.cited_observation_hashes
    }
    authorized_scope_count = (
        provider.authorized_occurrence_scope_count
        if provider.authorized_occurrence_scope_count is not None
        else len(provider.occurrences) + occurrence_gap_count
    )
    coverage = ExactCoverageContract(
        coverage_fingerprint=sha256_json(coverage_payload),
        view_revision_fingerprint=provider.authorized_scope_fingerprint,
        visible_node_count=0,
        inventory_schema_record_count=len(provider.occurrences),
        filter_term_count=len(query_hashes),
        identifier_filter_count=len(query_hashes),
        topic_filter_count=0,
        eligible_record_count=exact_match_count,
        enumerated_record_count=exact_match_count,
        cited_observation_count=len(cited_hashes),
        missing_evidence_record_count=provider.unresolved_count,
        access_required_scope_count=provider.redacted_count,
        authorized_scope_complete=incomplete == 0,
        global_scope_complete=incomplete == 0,
        incompleteness_reason_hashes=reason_hashes,
    )
    result = DeterministicExactExecutionResult(
        status=status,
        query_hash=plan.query_hash,
        plan_fingerprint=plan_fingerprint,
        operation_hash=sha256_json(plan.exact_operation),
        inventory_kind_hash=sha256_json(plan.exact_inventory_kind),
        exact_count=exact_match_count,
        returned_item_count=len(items),
        cited_observation_count=len(cited_hashes),
        items=items,
        coverage=coverage,
        result_fingerprint=sha256_json(
            [coverage_payload, [item.item_hash for item in items], next_cursor]
        ),
        source_occurrence_page={
            "coverage_status": coverage_status,
            "next_cursor": next_cursor,
            "unresolved_count": provider.unresolved_count,
            "unsupported_count": provider.unsupported_count,
            "encrypted_count": provider.encrypted_count,
            "redacted_count": provider.redacted_count,
            "authorized_occurrence_scope_count": authorized_scope_count,
            "extractable_occurrence_scope_count": (
                provider.extractable_occurrence_scope_count
                if provider.extractable_occurrence_scope_count is not None
                else len(provider.occurrences)
            ),
            "candidate_only_occurrence_count": candidate_only_count,
            "source_asset_reason_counts": [
                {
                    "reason": reason,
                    "asset_count": count,
                }
                for reason, count in provider.source_asset_reason_counts
            ],
            "duplicate_policy": provider.duplicate_policy,
            "ambiguous_identifier_count": len(ambiguous),
            "provider_fingerprint": provider_fingerprint,
            "page_size": page_size,
            "cursor_present": cursor is not None,
        },
    )
    result.to_safe_dict()
    return result


def _source_occurrence_query_hashes(
    *,
    plan: SemanticQueryPlan,
    provider: SourceOccurrenceProvider,
) -> frozenset[str]:
    if provider.filter_slot_policy == "identifier_union_v1":
        query_hashes = frozenset(plan.exact_identifier_term_hashes)
        if not query_hashes:
            raise ContractValidationError(
                "source occurrence identifier binding is incomplete"
            )
        return query_hashes
    if (
        plan.exact_source_occurrence_provider_fingerprint
        != provider.provider_fingerprint
        or not plan.exact_column_value_hash_pairs
        or not plan.exact_lexical_term_ledger
        or plan.exact_grammar_policy_fingerprint is None
        or any(
            role not in EXACT_QUERY_GRAMMAR_ROLES
            for _term_hash, role in plan.exact_grammar_term_ledger
        )
    ):
        raise ContractValidationError(
            "source occurrence structured query binding is incomplete"
        )
    filter_pairs = tuple(
        sorted(
            {
                (column_hash, grounded_hash)
                for _term_hash, role, column_hash, grounded_hash in (
                    plan.exact_lexical_term_ledger
                )
                if role == "filter_value"
            }
        )
    )
    projection_columns = tuple(
        sorted(
            {
                column_hash
                for _term_hash, role, column_hash, _grounded_hash in (
                    plan.exact_lexical_term_ledger
                )
                if role == "projection_field"
            }
        )
    )
    if (
        filter_pairs != plan.exact_column_value_hash_pairs
        or tuple(
            sorted(
                {
                    value_hash
                    for _column_hash, value_hash in filter_pairs
                }
            )
        )
        != plan.exact_filter_term_hashes
        or projection_columns != plan.exact_projection_term_hashes
        or any(
            pair not in provider._column_value_postings
            for pair in filter_pairs
        )
        or any(
            column_hash not in provider._column_postings
            for column_hash in projection_columns
        )
        or any(
            (
                role == "filter_value"
                and column_hash
                not in provider._value_candidate_columns.get(
                    grounded_hash,
                    (),
                )
            )
            or (
                role == "projection_field"
                and column_hash
                not in provider._projection_candidate_columns.get(
                    grounded_hash,
                    (),
                )
            )
            for _term_hash, role, column_hash, grounded_hash in (
                plan.exact_lexical_term_ledger
            )
        )
    ):
        raise ContractValidationError(
            "source occurrence query filter slots are inconsistent"
        )
    return frozenset(plan.exact_filter_term_hashes)


def _source_occurrence_cursor(
    offset: int,
    *,
    plan_fingerprint: str,
    provider_fingerprint: str,
    authorized_scope_fingerprint: str,
    page_size: int,
) -> str:
    digest = sha256_json(
        [
            plan_fingerprint,
            provider_fingerprint,
            authorized_scope_fingerprint,
            page_size,
            offset,
        ]
    )
    return f"source_occurrence_cursor_v1:{offset}:{digest}"


def _source_occurrence_cursor_offset(
    cursor: str | None,
    *,
    plan_fingerprint: str,
    provider_fingerprint: str,
    authorized_scope_fingerprint: str,
    page_size: int,
) -> int:
    if cursor is None:
        return 0
    try:
        prefix, raw_offset, _ = cursor.split(":", 2)
        offset = int(raw_offset)
    except (AttributeError, TypeError, ValueError):
        raise ContractValidationError("source occurrence cursor is invalid") from None
    if (
        prefix != "source_occurrence_cursor_v1"
        or offset < 0
        or cursor
        != _source_occurrence_cursor(
            offset,
            plan_fingerprint=plan_fingerprint,
            provider_fingerprint=provider_fingerprint,
            authorized_scope_fingerprint=authorized_scope_fingerprint,
            page_size=page_size,
        )
    ):
        raise ContractValidationError("source occurrence cursor binding mismatch")
    return offset


def execute_deterministic_exact_inventory(
    *,
    plan: SemanticQueryPlan,
    effective_graph_view: EffectiveGraphView,
    authorized_observation_hash_by_id: Mapping[str, str],
) -> DeterministicExactExecutionResult:
    """Enumerate the full structured authorized scope; never infer from top-k."""

    if plan.query_class != "exact_set_or_inventory":
        raise ContractValidationError("deterministic exact executor requires exact query class")
    if plan.exact_operation != "inventory_with_count" or not plan.exact_inventory_kind:
        raise ContractValidationError("deterministic exact executor plan is invalid")

    grouped_citations: dict[str, set[str]] = {}
    inventory_schema_record_count = 0
    eligible_record_count = 0
    missing_evidence_record_count = 0
    incompleteness_reasons: set[str] = set()
    for node in sorted(effective_graph_view.visible_nodes, key=lambda item: item.node_id):
        properties = node.properties
        if properties.get("inventory_kind") != plan.exact_inventory_kind:
            continue
        temporal_state = str(properties.get("temporal_state", "current")).casefold()
        if temporal_state in _SUPERSEDED_STATES and not plan.include_superseded:
            continue
        inventory_schema_record_count += 1
        if plan.exact_filter_term_hashes:
            source_term_hashes = _source_term_hashes(properties)
            if not set(plan.exact_identifier_term_hashes).issubset(source_term_hashes):
                continue
            if plan.exact_topic_term_hashes and not (
                set(plan.exact_topic_term_hashes) & source_term_hashes
            ):
                continue
        eligible_record_count += 1
        if properties.get("review_state") == "diagnostic_policy_admitted":
            missing_evidence_record_count += 1
            incompleteness_reasons.add("candidate_inventory_requires_reviewed_structured_record")
            continue
        inventory_value = properties.get("inventory_value")
        observation_ids = _source_observation_ids(properties)
        evidence_hashes = tuple(
            sorted(
                authorized_observation_hash_by_id[observation_id]
                for observation_id in observation_ids
                if observation_id in authorized_observation_hash_by_id
            )
        )
        if (
            not isinstance(inventory_value, str)
            or not inventory_value.strip()
            or not observation_ids
            or len(evidence_hashes) != len(observation_ids)
        ):
            missing_evidence_record_count += 1
            incompleteness_reasons.add("structured_record_missing_authorized_evidence")
            continue
        item_hash = sha256_json(
            {
                "inventory_kind": plan.exact_inventory_kind,
                "inventory_value": inventory_value,
            }
        )
        grouped_citations.setdefault(item_hash, set()).update(evidence_hashes)

    items = tuple(
        ExactInventoryItem(
            item_hash=item_hash,
            cited_observation_hashes=tuple(sorted(citation_hashes)),
        )
        for item_hash, citation_hashes in sorted(grouped_citations.items())
    )
    if len(items) > plan.result_limit:
        incompleteness_reasons.add("exact_inventory_result_budget_exceeded")
    if inventory_schema_record_count == 0:
        incompleteness_reasons.add("structured_inventory_coverage_unavailable")
    authorized_scope_complete = (
        inventory_schema_record_count > 0
        and missing_evidence_record_count == 0
        and len(items) <= plan.result_limit
    )
    returned_items = items if authorized_scope_complete else ()
    access_required_scope_count = len(effective_graph_view.access_required)
    global_scope_complete = authorized_scope_complete and access_required_scope_count == 0
    if not effective_graph_view.visible_nodes and access_required_scope_count:
        status = "permission_denied"
    elif authorized_scope_complete:
        status = "complete_authorized_scope"
    else:
        status = "incomplete"
    cited_hashes = {
        observation_hash
        for item in returned_items
        for observation_hash in item.cited_observation_hashes
    }
    view_revision_fingerprint = sha256_json(
        {
            "user_graph_revision_id": effective_graph_view.user_graph_revision_id,
            "canonical_graph_revision_id": effective_graph_view.canonical_graph_revision_id,
            "ontology_revision_id": effective_graph_view.ontology_revision_id,
        }
    )
    reason_hashes = tuple(sorted(sha256_json(reason) for reason in incompleteness_reasons))
    coverage_payload = {
        "plan_fingerprint": plan.plan_fingerprint,
        "view_revision_fingerprint": view_revision_fingerprint,
        "visible_node_count": len(effective_graph_view.visible_nodes),
        "inventory_schema_record_count": inventory_schema_record_count,
        "filter_term_count": len(plan.exact_filter_term_hashes),
        "identifier_filter_count": len(plan.exact_identifier_term_hashes),
        "topic_filter_count": len(plan.exact_topic_term_hashes),
        "eligible_record_count": eligible_record_count,
        "enumerated_record_count": len(items),
        "missing_evidence_record_count": missing_evidence_record_count,
        "access_required_scope_count": access_required_scope_count,
        "authorized_scope_complete": authorized_scope_complete,
        "global_scope_complete": global_scope_complete,
        "incompleteness_reason_hashes": list(reason_hashes),
    }
    coverage = ExactCoverageContract(
        coverage_fingerprint=sha256_json(coverage_payload),
        view_revision_fingerprint=view_revision_fingerprint,
        visible_node_count=len(effective_graph_view.visible_nodes),
        inventory_schema_record_count=inventory_schema_record_count,
        filter_term_count=len(plan.exact_filter_term_hashes),
        identifier_filter_count=len(plan.exact_identifier_term_hashes),
        topic_filter_count=len(plan.exact_topic_term_hashes),
        eligible_record_count=eligible_record_count,
        enumerated_record_count=len(items),
        cited_observation_count=len(cited_hashes),
        missing_evidence_record_count=missing_evidence_record_count,
        access_required_scope_count=access_required_scope_count,
        authorized_scope_complete=authorized_scope_complete,
        global_scope_complete=global_scope_complete,
        incompleteness_reason_hashes=reason_hashes,
    )
    result_payload = {
        "status": status,
        "query_hash": plan.query_hash,
        "plan_fingerprint": plan.plan_fingerprint,
        "operation_hash": sha256_json(plan.exact_operation),
        "inventory_kind_hash": sha256_json(plan.exact_inventory_kind),
        "exact_count": len(items),
        "returned_item_hashes": [item.item_hash for item in returned_items],
        "cited_observation_hashes": sorted(cited_hashes),
        "coverage_fingerprint": coverage.coverage_fingerprint,
    }
    result = DeterministicExactExecutionResult(
        status=status,
        query_hash=plan.query_hash,
        plan_fingerprint=plan.plan_fingerprint,
        operation_hash=sha256_json(plan.exact_operation),
        inventory_kind_hash=sha256_json(plan.exact_inventory_kind),
        exact_count=len(items),
        returned_item_count=len(returned_items),
        cited_observation_count=len(cited_hashes),
        items=returned_items,
        coverage=coverage,
        result_fingerprint=sha256_json(result_payload),
    )
    result.to_safe_dict()
    return result


def _source_observation_ids(properties: Mapping[str, Any]) -> tuple[str, ...]:
    values = properties.get("source_observation_ids", ())
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(sorted({value for value in values if isinstance(value, str) and value.strip()}))


def _source_term_hashes(properties: Mapping[str, Any]) -> set[str]:
    values = properties.get("source_term_hashes", ())
    if not isinstance(values, (list, tuple)):
        return set()
    return {
        value
        for value in values
        if isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == len("sha256:") + 64
    }


__all__ = [
    "AuthorizedSourceOccurrence",
    "DeterministicExactExecutionResult",
    "ExactCoverageContract",
    "ExactInventoryItem",
    "SOURCE_OCCURRENCE_FILTER_SLOT_POLICIES",
    "SOURCE_OCCURRENCE_LEXICAL_TERM_ROLES",
    "SourceOccurrenceQueryPartition",
    "SourceOccurrenceProvider",
    "authorized_source_occurrence_scope_fingerprint",
    "execute_deterministic_exact_inventory",
    "execute_deterministic_source_occurrence_inventory",
    "source_occurrence_column_capability_hash",
    "source_occurrence_projection_capability_hash",
]
