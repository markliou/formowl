"""Deterministic exact inventory execution over an authorized EffectiveGraphView."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from formowl_contract import ContractValidationError, sha256_json
from formowl_graph import EffectiveGraphView

from ._guards import assert_public_payload_safe
from .semantic_plan import SemanticQueryPlan

_CURRENT_STATES = {"active", "current", "effective", "valid"}
_SUPERSEDED_STATES = {"expired", "stale", "superseded", "withdrawn"}


@dataclass(frozen=True)
class ExactInventoryItem:
    item_hash: str
    cited_observation_hashes: tuple[str, ...]
    governed_references: tuple[tuple[str, str], ...] = ()
    matched_normalized_value_hashes: tuple[str, ...] = ()
    ambiguous_identifier: bool = False

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
    unresolved_count: int = 0
    unsupported_count: int = 0
    redacted_count: int = 0
    duplicate_policy: str = "preserve_source_occurrence_v1"

    def __post_init__(self) -> None:
        ordered_occurrences = tuple(
            sorted(self.occurrences, key=lambda value: value.item_hash)
        )
        postings: dict[str, list[int]] = {}
        normalized_variants: dict[str, set[str]] = {}
        for position, item in enumerate(ordered_occurrences):
            occurrence_value_hashes: set[str] = set()
            for normalized_hash, variant_hash, _, _ in item.value_bindings:
                occurrence_value_hashes.update((normalized_hash, variant_hash))
                normalized_variants.setdefault(normalized_hash, set()).add(
                    variant_hash
                )
            for value_hash in occurrence_value_hashes:
                postings.setdefault(value_hash, []).append(position)
        object.__setattr__(
            self,
            "_provider_fingerprint",
            sha256_json(
                {
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
                        [
                            item.item_hash,
                            [list(binding) for binding in item.value_bindings],
                        ]
                        for item in self.occurrences
                    ],
                    "counts": [
                        self.unresolved_count,
                        self.unsupported_count,
                        self.redacted_count,
                    ],
                }
            ),
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

    @property
    def provider_fingerprint(self) -> str:
        return self._provider_fingerprint

    def __deepcopy__(self, memo: dict[int, Any]) -> SourceOccurrenceProvider:
        memo[id(self)] = self
        return self


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
        or not plan.exact_identifier_term_hashes
        or not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or not 1 <= page_size <= 100
    ):
        raise ContractValidationError("source occurrence exact binding is invalid")
    plan_fingerprint = plan.plan_fingerprint
    provider_fingerprint = provider.provider_fingerprint
    query_hashes = frozenset(plan.exact_identifier_term_hashes)
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
    matched = tuple(
        provider._ordered_occurrences[position] for position in matched_positions
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
    if offset > len(matched):
        raise ContractValidationError("source occurrence cursor offset is invalid")
    selected = matched[offset : offset + page_size]
    next_offset = offset + len(selected)
    next_cursor = (
        _source_occurrence_cursor(
            next_offset,
            plan_fingerprint=plan_fingerprint,
            provider_fingerprint=provider_fingerprint,
            authorized_scope_fingerprint=provider.authorized_scope_fingerprint,
            page_size=page_size,
        )
        if next_offset < len(matched)
        else None
    )
    projected_items: list[ExactInventoryItem] = []
    for item in selected:
        citation_hashes: set[str] = set()
        governed_references: set[tuple[str, str]] = set()
        matched_normalized_hashes: set[str] = set()
        matched_ambiguous = False
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
        projected_items.append(
            ExactInventoryItem(
                item_hash=item.item_hash,
                cited_observation_hashes=tuple(sorted(citation_hashes)),
                governed_references=tuple(sorted(governed_references)),
                matched_normalized_value_hashes=tuple(
                    sorted(matched_normalized_hashes)
                ),
                ambiguous_identifier=matched_ambiguous,
            ),
        )
    items = tuple(projected_items)
    incomplete = provider.unresolved_count + provider.unsupported_count + provider.redacted_count
    status = "complete_authorized_scope" if incomplete == 0 else "incomplete"
    coverage_status = (
        "incomplete"
        if next_cursor is None and incomplete
        else "complete"
        if next_cursor is None
        else "complete_page"
    )
    reason_hashes = (
        () if incomplete == 0 else (sha256_json("source_occurrence_provider_incomplete"),)
    )
    coverage_payload = [
        plan_fingerprint,
        provider_fingerprint,
        len(matched),
        len(items),
        offset,
        coverage_status,
        *reason_hashes,
    ]
    coverage = ExactCoverageContract(
        coverage_fingerprint=sha256_json(coverage_payload),
        view_revision_fingerprint=provider.authorized_scope_fingerprint,
        visible_node_count=0,
        inventory_schema_record_count=len(provider.occurrences),
        filter_term_count=len(query_hashes),
        identifier_filter_count=len(query_hashes),
        topic_filter_count=0,
        eligible_record_count=len(matched),
        enumerated_record_count=len(matched),
        cited_observation_count=len(items),
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
        exact_count=len(matched),
        returned_item_count=len(items),
        cited_observation_count=len(items),
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
            "redacted_count": provider.redacted_count,
            "duplicate_policy": provider.duplicate_policy,
            "ambiguous_identifier_count": len(ambiguous),
            "provider_fingerprint": provider_fingerprint,
            "page_size": page_size,
            "cursor_present": cursor is not None,
        },
    )
    result.to_safe_dict()
    return result


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
    "SourceOccurrenceProvider",
    "authorized_source_occurrence_scope_fingerprint",
    "execute_deterministic_exact_inventory",
    "execute_deterministic_source_occurrence_inventory",
]
