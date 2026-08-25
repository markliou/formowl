"""Deterministic exact inventory execution over an authorized EffectiveGraphView."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

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

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "item_hash": self.item_hash,
            "cited_observation_hashes": list(self.cited_observation_hashes),
            "citation_count": len(self.cited_observation_hashes),
        }
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
        assert_public_payload_safe(payload, "deterministic_exact_execution_result")
        return payload


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
    "DeterministicExactExecutionResult",
    "ExactCoverageContract",
    "ExactInventoryItem",
    "execute_deterministic_exact_inventory",
]
