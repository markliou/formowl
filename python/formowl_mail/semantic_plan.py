"""Deterministic, fail-closed semantic query plans for Issue #56 POC execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Sequence

from formowl_contract import CORE_SUPERTYPE_IDS, ContractValidationError, sha256_json
from formowl_graph import EffectiveGraphView

from ._guards import assert_public_payload_safe, safe_public_string

SEMANTIC_QUERY_CLASSES = (
    "evidence_lookup",
    "relation_reasoning",
    "exact_set_or_inventory",
    "global_summarization",
)
AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND = "authorized_mail_observation"
GITHUB_PROJECT_OBSERVATION_SOURCE_KIND = "github_project_observation"
_SOURCE_OCCURRENCE_SCHEMA_BY_KIND = {
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND: "mail_message_occurrence_v1",
    GITHUB_PROJECT_OBSERVATION_SOURCE_KIND: "github_issue_comment_occurrence_v1",
}
_CLAIM_STRENGTH_BY_CLASS = {
    "evidence_lookup": "cited_evidence",
    "relation_reasoning": "bounded_relation",
    "exact_set_or_inventory": "complete_authorized_scope",
    "global_summarization": "bounded_summary",
}
_PERMISSION_REQUIREMENTS_BY_CLASS = {
    "evidence_lookup": ("evidence_snippet",),
    "relation_reasoning": ("evidence_snippet", "graph_snippet"),
    "exact_set_or_inventory": ("evidence_snippet", "graph_snippet"),
    "global_summarization": ("evidence_snippet",),
}
_EXACT_TERMS = (
    "count",
    "exact set",
    "inventory",
    "list all",
    "how many",
    "全部",
    "列出",
    "清單",
    "盤點",
    "多少",
)
_RELATION_TERMS = (
    "relation",
    "related",
    "relationship",
    "cross-message",
    "through",
    "關係",
    "關聯",
    "跨訊息",
    "透過",
)
_SUMMARY_TERMS = (
    "summarize",
    "summary",
    "overview",
    "總結",
    "摘要",
    "概況",
)


@dataclass(frozen=True)
class SemanticPlanLimits:
    max_hops: int = 2
    max_fanout: int = 8
    max_candidates: int = 24
    max_results: int = 64
    max_evidence: int = 96
    max_time_budget_ms: int = 2_000
    max_repairs: int = 1


DEFAULT_SEMANTIC_PLAN_LIMITS = SemanticPlanLimits()


@dataclass(frozen=True)
class AuthorizedSemanticSource:
    """One validated source-kind and authorization-scope binding."""

    source_kind: str
    workspace_id: str
    source_scope_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonempty_public_string(self.source_kind, "source_kind")
        if self.source_kind not in _SOURCE_OCCURRENCE_SCHEMA_BY_KIND:
            raise ContractValidationError("semantic query source kind is unsupported")
        _require_nonempty_public_string(self.workspace_id, "workspace_id")
        if not self.source_scope_ids or self.source_scope_ids != tuple(
            sorted(set(self.source_scope_ids))
        ):
            raise ContractValidationError("semantic query source scope is invalid")
        for source_scope_id in self.source_scope_ids:
            _require_nonempty_public_string(source_scope_id, "source_scope_id")

    @property
    def occurrence_schema_id(self) -> str:
        return _SOURCE_OCCURRENCE_SCHEMA_BY_KIND[self.source_kind]

    @property
    def authorization_fingerprint(self) -> str:
        return sha256_json(
            {
                "schema_version": 1,
                "source_kind": self.source_kind,
                "occurrence_schema_id": self.occurrence_schema_id,
                "workspace_id": self.workspace_id,
                "source_scope_ids": list(self.source_scope_ids),
            }
        )


def validated_authorized_semantic_source(
    *,
    source_kind: str,
    workspace_id: str,
    source_scope_ids: Sequence[str],
) -> AuthorizedSemanticSource:
    """Validate one upstream-authorized source scope without accepting mixed kinds."""

    return AuthorizedSemanticSource(
        source_kind=source_kind,
        workspace_id=workspace_id,
        source_scope_ids=tuple(sorted(set(source_scope_ids))),
    )


@dataclass(frozen=True)
class SemanticQueryPlan:
    """A revision-pinned plan whose scope can only be narrowed during repair."""

    query_hash: str
    query_class: str
    source_kind: str
    source_scope_ids: tuple[str, ...]
    workspace_id: str
    requester_user_id: str
    required_permissions: tuple[str, ...]
    user_graph_revision_id: str
    canonical_graph_revision_id: str
    ontology_revision_id: str
    assembly_policy_id: str
    allowed_paths: tuple[tuple[str, str], ...]
    seed_node_ids: tuple[str, ...]
    max_hops: int
    max_fanout: int
    candidate_limit: int
    result_limit: int
    evidence_budget: int
    time_budget_ms: int
    repair_budget: int
    repair_attempt_count: int
    claim_strength: str
    exact_operation: str | None = None
    exact_inventory_kind: str | None = None
    exact_filter_term_hashes: tuple[str, ...] = ()
    exact_identifier_term_hashes: tuple[str, ...] = ()
    exact_topic_term_hashes: tuple[str, ...] = ()
    exact_normalized_field: str | None = None
    exact_predicate: str | None = None
    exact_operator: str | None = None
    target_core_supertype_id: str | None = None
    include_superseded: bool = False
    relation_repair_identifier_term_hashes: tuple[str, ...] = ()
    relation_repair_concept_term_hashes: tuple[str, ...] = ()
    relation_repair_policy_fingerprint: str | None = None
    relation_repair_vocabulary_fingerprint: str | None = None

    @property
    def plan_fingerprint(self) -> str:
        return sha256_json(self._fingerprint_payload())

    def _fingerprint_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "query_hash": self.query_hash,
            "query_class": self.query_class,
            "source_kind": self.source_kind,
            "source_scope_ids": list(self.source_scope_ids),
            "workspace_id": self.workspace_id,
            "requester_user_id": self.requester_user_id,
            "required_permissions": list(self.required_permissions),
            "user_graph_revision_id": self.user_graph_revision_id,
            "canonical_graph_revision_id": self.canonical_graph_revision_id,
            "ontology_revision_id": self.ontology_revision_id,
            "assembly_policy_id": self.assembly_policy_id,
            "allowed_paths": [list(path) for path in self.allowed_paths],
            "seed_node_ids": list(self.seed_node_ids),
            "max_hops": self.max_hops,
            "max_fanout": self.max_fanout,
            "candidate_limit": self.candidate_limit,
            "result_limit": self.result_limit,
            "evidence_budget": self.evidence_budget,
            "time_budget_ms": self.time_budget_ms,
            "repair_budget": self.repair_budget,
            "repair_attempt_count": self.repair_attempt_count,
            "claim_strength": self.claim_strength,
            "exact_operation": self.exact_operation,
            "exact_inventory_kind": self.exact_inventory_kind,
            "exact_filter_term_hashes": list(self.exact_filter_term_hashes),
            "exact_identifier_term_hashes": list(self.exact_identifier_term_hashes),
            "exact_topic_term_hashes": list(self.exact_topic_term_hashes),
            "target_core_supertype_id": self.target_core_supertype_id,
            "include_superseded": self.include_superseded,
        }
        if self.exact_normalized_field is not None:
            payload["exact_source_occurrence"] = [
                self.exact_normalized_field,
                self.exact_predicate,
                self.exact_operator,
            ]
        if self.relation_repair_policy_fingerprint is not None:
            payload["relation_repair"] = {
                "identifier_term_hashes": list(self.relation_repair_identifier_term_hashes),
                "concept_term_hashes": list(self.relation_repair_concept_term_hashes),
                "policy_fingerprint": self.relation_repair_policy_fingerprint,
                "vocabulary_fingerprint": (self.relation_repair_vocabulary_fingerprint),
            }
        return payload

    def to_safe_dict(self) -> dict[str, Any]:
        payload = {
            "artifact_id": "formowl_semantic_query_plan_v1",
            "query_hash": self.query_hash,
            "query_class": self.query_class,
            "plan_fingerprint": self.plan_fingerprint,
            "source_kind_hash": sha256_json(self.source_kind),
            "source_scope_hashes": [
                sha256_json(source_scope_id) for source_scope_id in self.source_scope_ids
            ],
            "workspace_hash": sha256_json(self.workspace_id),
            "requester_hash": sha256_json(self.requester_user_id),
            "permission_hashes": [
                sha256_json(permission) for permission in self.required_permissions
            ],
            "revision_hashes": {
                "user_graph": sha256_json(self.user_graph_revision_id),
                "canonical_graph": sha256_json(self.canonical_graph_revision_id),
                "ontology": sha256_json(self.ontology_revision_id),
                "assembly_policy": sha256_json(self.assembly_policy_id),
            },
            "allowed_path_hashes": [
                sha256_json({"relation_type": relation_type, "direction": direction})
                for relation_type, direction in self.allowed_paths
            ],
            "seed_node_hashes": [sha256_json(node_id) for node_id in self.seed_node_ids],
            "max_hops": self.max_hops,
            "max_fanout": self.max_fanout,
            "candidate_limit": self.candidate_limit,
            "result_limit": self.result_limit,
            "evidence_budget": self.evidence_budget,
            "time_budget_ms": self.time_budget_ms,
            "repair_budget": self.repair_budget,
            "repair_attempt_count": self.repair_attempt_count,
            "claim_strength": self.claim_strength,
            "exact_operation_hash": (
                sha256_json(self.exact_operation) if self.exact_operation else None
            ),
            "exact_inventory_kind_hash": (
                sha256_json(self.exact_inventory_kind) if self.exact_inventory_kind else None
            ),
            "exact_filter_term_hashes": list(self.exact_filter_term_hashes),
            "exact_identifier_term_hashes": list(self.exact_identifier_term_hashes),
            "exact_topic_term_hashes": list(self.exact_topic_term_hashes),
            "target_core_supertype_hash": (
                sha256_json(self.target_core_supertype_id)
                if self.target_core_supertype_id
                else None
            ),
            "include_superseded": self.include_superseded,
        }
        if self.relation_repair_policy_fingerprint is not None:
            payload["relation_repair"] = {
                "identifier_term_hashes": list(self.relation_repair_identifier_term_hashes),
                "concept_term_hashes": list(self.relation_repair_concept_term_hashes),
                "policy_fingerprint": self.relation_repair_policy_fingerprint,
                "vocabulary_fingerprint": (self.relation_repair_vocabulary_fingerprint),
            }
        assert_public_payload_safe(payload, "semantic_query_plan")
        return payload


def deterministic_query_class(query_text: str) -> str:
    """Classify a query without model calls, hidden state, or nondeterministic repair."""

    _require_nonempty_public_string(query_text, "query_text")
    normalized = query_text.casefold()
    if any(term in normalized for term in _EXACT_TERMS):
        return "exact_set_or_inventory"
    if any(term in normalized for term in _RELATION_TERMS):
        return "relation_reasoning"
    if any(term in normalized for term in _SUMMARY_TERMS):
        return "global_summarization"
    return "evidence_lookup"


def route_semantic_query(
    *,
    query_text: str,
    requester_user_id: str,
    workspace_id: str,
    source_scope_ids: Sequence[str],
    effective_graph_view: EffectiveGraphView,
    allowed_relation_types: Sequence[str] = (),
    allowed_directions: Sequence[str] = ("out",),
    seed_node_ids: Sequence[str] = (),
    target_core_supertype_id: str | None = None,
    exact_inventory_kind: str | None = None,
    exact_filter_term_hashes: Sequence[str] = (),
    exact_identifier_term_hashes: Sequence[str] = (),
    exact_topic_term_hashes: Sequence[str] = (),
    exact_normalized_field: str | None = None,
    exact_predicate: str | None = None,
    exact_operator: str | None = None,
    limits: SemanticPlanLimits = DEFAULT_SEMANTIC_PLAN_LIMITS,
    authorized_source: AuthorizedSemanticSource | None = None,
    query_class_override: str | None = None,
) -> SemanticQueryPlan:
    """Build and validate the smallest deterministic plan for the query class."""

    resolved_source = _resolve_authorized_source(
        authorized_source=authorized_source,
        workspace_id=workspace_id,
        source_scope_ids=source_scope_ids,
    )
    if query_class_override is not None and (
        query_class_override != "exact_set_or_inventory"
        or not all(
            isinstance(value, str) and value.strip()
            for value in (exact_normalized_field, exact_predicate, exact_operator)
        )
    ):
        raise ContractValidationError("semantic query class override is invalid")
    query_class = (
        query_class_override
        if query_class_override is not None
        else deterministic_query_class(query_text)
    )
    relation_types = tuple(sorted(set(allowed_relation_types)))
    directions = tuple(sorted(set(allowed_directions)))
    allowed_paths = (
        tuple(
            (relation_type, direction)
            for relation_type in relation_types
            for direction in directions
        )
        if query_class == "relation_reasoning"
        else ()
    )
    inventory_kind = (
        exact_inventory_kind or _deterministic_inventory_kind(query_text)
        if query_class == "exact_set_or_inventory"
        else None
    )
    plan = SemanticQueryPlan(
        query_hash=sha256_json(query_text),
        query_class=query_class,
        source_kind=resolved_source.source_kind,
        source_scope_ids=tuple(sorted(set(source_scope_ids))),
        workspace_id=workspace_id,
        requester_user_id=requester_user_id,
        required_permissions=_PERMISSION_REQUIREMENTS_BY_CLASS[query_class],
        user_graph_revision_id=effective_graph_view.user_graph_revision_id,
        canonical_graph_revision_id=effective_graph_view.canonical_graph_revision_id,
        ontology_revision_id=effective_graph_view.ontology_revision_id,
        assembly_policy_id=effective_graph_view.assembly_policy_id,
        allowed_paths=allowed_paths,
        seed_node_ids=tuple(sorted(set(seed_node_ids))),
        max_hops=min(2, limits.max_hops) if query_class == "relation_reasoning" else 0,
        max_fanout=min(6, limits.max_fanout),
        candidate_limit=min(24, limits.max_candidates),
        result_limit=min(
            20 if query_class == "exact_set_or_inventory" else 10,
            limits.max_results,
        ),
        evidence_budget=min(48, limits.max_evidence),
        time_budget_ms=min(1_500, limits.max_time_budget_ms),
        repair_budget=min(1, limits.max_repairs),
        repair_attempt_count=0,
        claim_strength=_CLAIM_STRENGTH_BY_CLASS[query_class],
        exact_operation=(
            "inventory_with_count" if query_class == "exact_set_or_inventory" else None
        ),
        exact_inventory_kind=inventory_kind,
        exact_filter_term_hashes=(
            tuple(sorted(set(exact_filter_term_hashes)))
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_identifier_term_hashes=(
            tuple(sorted(set(exact_identifier_term_hashes)))
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_topic_term_hashes=(
            tuple(sorted(set(exact_topic_term_hashes)))
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_normalized_field=exact_normalized_field,
        exact_predicate=exact_predicate,
        exact_operator=exact_operator,
        target_core_supertype_id=target_core_supertype_id,
        include_superseded=False,
    )
    return validate_semantic_query_plan(
        plan,
        effective_graph_view=effective_graph_view,
        authorized_workspace_id=workspace_id,
        authorized_source_scope_ids=source_scope_ids,
        supported_relation_types=allowed_relation_types,
        limits=limits,
        allow_bounded_repair=True,
        authorized_source=resolved_source,
    )


def validate_semantic_query_plan(
    plan: SemanticQueryPlan,
    *,
    effective_graph_view: EffectiveGraphView,
    authorized_workspace_id: str,
    authorized_source_scope_ids: Sequence[str],
    supported_relation_types: Sequence[str],
    limits: SemanticPlanLimits = DEFAULT_SEMANTIC_PLAN_LIMITS,
    allow_bounded_repair: bool = True,
    authorized_source: AuthorizedSemanticSource | None = None,
) -> SemanticQueryPlan:
    """Validate pins and scope; the only repair is one cap-reducing pass."""

    if not isinstance(plan, SemanticQueryPlan):
        raise ContractValidationError("semantic query plan is invalid")
    repaired = _bounded_cap_repair(plan, limits=limits) if allow_bounded_repair else plan
    _validate_plan_strings(repaired)
    if repaired.query_class not in SEMANTIC_QUERY_CLASSES:
        raise ContractValidationError("semantic query class is unsupported")
    resolved_source = _resolve_authorized_source(
        authorized_source=authorized_source,
        workspace_id=authorized_workspace_id,
        source_scope_ids=authorized_source_scope_ids,
    )
    if repaired.source_kind != resolved_source.source_kind:
        raise ContractValidationError("semantic query source kind mismatch")
    authorized_sources = set(authorized_source_scope_ids)
    if not repaired.source_scope_ids or not set(repaired.source_scope_ids).issubset(
        authorized_sources
    ):
        raise ContractValidationError("semantic query plan would widen source scope")
    if repaired.workspace_id != authorized_workspace_id:
        raise ContractValidationError("semantic query workspace scope mismatch")
    if repaired.requester_user_id != effective_graph_view.requester_user_id:
        raise ContractValidationError("semantic query requester scope mismatch")
    if (
        repaired.user_graph_revision_id != effective_graph_view.user_graph_revision_id
        or repaired.canonical_graph_revision_id != effective_graph_view.canonical_graph_revision_id
        or repaired.ontology_revision_id != effective_graph_view.ontology_revision_id
        or repaired.assembly_policy_id != effective_graph_view.assembly_policy_id
    ):
        raise ContractValidationError("semantic query revision pin mismatch")
    expected_permissions = _PERMISSION_REQUIREMENTS_BY_CLASS[repaired.query_class]
    if repaired.required_permissions != expected_permissions:
        raise ContractValidationError("semantic query permission scope mismatch")
    if repaired.claim_strength != _CLAIM_STRENGTH_BY_CLASS[repaired.query_class]:
        raise ContractValidationError("semantic query claim strength is invalid")
    _validate_numeric_caps(repaired, limits=limits)
    _validate_query_class_shape(
        repaired,
        effective_graph_view=effective_graph_view,
        supported_relation_types=supported_relation_types,
    )
    repaired.to_safe_dict()
    return repaired


def _resolve_authorized_source(
    *,
    authorized_source: AuthorizedSemanticSource | None,
    workspace_id: str,
    source_scope_ids: Sequence[str],
) -> AuthorizedSemanticSource:
    expected_scope_ids = tuple(sorted(set(source_scope_ids)))
    if authorized_source is None:
        return validated_authorized_semantic_source(
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            workspace_id=workspace_id,
            source_scope_ids=expected_scope_ids,
        )
    if not isinstance(authorized_source, AuthorizedSemanticSource):
        raise ContractValidationError("semantic query authorized source is invalid")
    if (
        authorized_source.workspace_id != workspace_id
        or authorized_source.source_scope_ids != expected_scope_ids
    ):
        raise ContractValidationError("semantic query authorized source scope mismatch")
    return authorized_source


def _bounded_cap_repair(
    plan: SemanticQueryPlan,
    *,
    limits: SemanticPlanLimits,
) -> SemanticQueryPlan:
    over_cap = (
        plan.max_hops > limits.max_hops
        or plan.max_fanout > limits.max_fanout
        or plan.candidate_limit > limits.max_candidates
        or plan.result_limit > limits.max_results
        or plan.evidence_budget > limits.max_evidence
        or plan.time_budget_ms > limits.max_time_budget_ms
        or plan.repair_budget > limits.max_repairs
    )
    if not over_cap:
        return plan
    if plan.repair_budget < 1 or plan.repair_attempt_count >= 1:
        raise ContractValidationError("semantic query plan exceeds execution caps")
    return replace(
        plan,
        max_hops=min(plan.max_hops, limits.max_hops),
        max_fanout=min(plan.max_fanout, limits.max_fanout),
        candidate_limit=min(plan.candidate_limit, limits.max_candidates),
        result_limit=min(plan.result_limit, limits.max_results),
        evidence_budget=min(plan.evidence_budget, limits.max_evidence),
        time_budget_ms=min(plan.time_budget_ms, limits.max_time_budget_ms),
        repair_budget=min(plan.repair_budget, limits.max_repairs),
        repair_attempt_count=plan.repair_attempt_count + 1,
    )


def _validate_plan_strings(plan: SemanticQueryPlan) -> None:
    for field_name, value in (
        ("query_hash", plan.query_hash),
        ("source_kind", plan.source_kind),
        ("workspace_id", plan.workspace_id),
        ("requester_user_id", plan.requester_user_id),
        ("user_graph_revision_id", plan.user_graph_revision_id),
        ("canonical_graph_revision_id", plan.canonical_graph_revision_id),
        ("ontology_revision_id", plan.ontology_revision_id),
        ("assembly_policy_id", plan.assembly_policy_id),
        ("claim_strength", plan.claim_strength),
    ):
        _require_nonempty_public_string(value, field_name)
    for field_name, values in (
        ("source_scope_ids", plan.source_scope_ids),
        ("required_permissions", plan.required_permissions),
        ("seed_node_ids", plan.seed_node_ids),
        ("exact_filter_term_hashes", plan.exact_filter_term_hashes),
        ("exact_identifier_term_hashes", plan.exact_identifier_term_hashes),
        ("exact_topic_term_hashes", plan.exact_topic_term_hashes),
        (
            "relation_repair_identifier_term_hashes",
            plan.relation_repair_identifier_term_hashes,
        ),
        (
            "relation_repair_concept_term_hashes",
            plan.relation_repair_concept_term_hashes,
        ),
    ):
        for value in values:
            _require_nonempty_public_string(value, f"{field_name} entry")
    for relation_type, direction in plan.allowed_paths:
        _require_nonempty_public_string(relation_type, "allowed relation type")
        _require_nonempty_public_string(direction, "allowed direction")
    if plan.exact_operation is not None:
        _require_nonempty_public_string(plan.exact_operation, "exact_operation")
    if plan.exact_inventory_kind is not None:
        _require_nonempty_public_string(plan.exact_inventory_kind, "exact_inventory_kind")
    exact_source_fields = (plan.exact_normalized_field, plan.exact_predicate, plan.exact_operator)
    if any(value is not None for value in exact_source_fields) and not all(
        isinstance(value, str) and value for value in exact_source_fields
    ):
        raise ContractValidationError("exact source occurrence binding is incomplete")
    for term_hash in (
        *plan.exact_filter_term_hashes,
        *plan.exact_identifier_term_hashes,
        *plan.exact_topic_term_hashes,
        *plan.relation_repair_identifier_term_hashes,
        *plan.relation_repair_concept_term_hashes,
    ):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", term_hash) is None:
            raise ContractValidationError("semantic query term hash is invalid")
    for field_name, fingerprint in (
        (
            "relation_repair_policy_fingerprint",
            plan.relation_repair_policy_fingerprint,
        ),
        (
            "relation_repair_vocabulary_fingerprint",
            plan.relation_repair_vocabulary_fingerprint,
        ),
    ):
        if fingerprint is None:
            continue
        if re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint) is None:
            raise ContractValidationError(f"semantic query {field_name} is invalid")
    if plan.target_core_supertype_id is not None:
        _require_nonempty_public_string(
            plan.target_core_supertype_id,
            "target_core_supertype_id",
        )
        if plan.target_core_supertype_id not in CORE_SUPERTYPE_IDS:
            raise ContractValidationError("semantic query target type is unsupported")


def _validate_numeric_caps(
    plan: SemanticQueryPlan,
    *,
    limits: SemanticPlanLimits,
) -> None:
    for field_name, value, maximum, allow_zero in (
        ("max_hops", plan.max_hops, limits.max_hops, True),
        ("max_fanout", plan.max_fanout, limits.max_fanout, False),
        ("candidate_limit", plan.candidate_limit, limits.max_candidates, False),
        ("result_limit", plan.result_limit, limits.max_results, False),
        ("evidence_budget", plan.evidence_budget, limits.max_evidence, False),
        ("time_budget_ms", plan.time_budget_ms, limits.max_time_budget_ms, False),
        ("repair_budget", plan.repair_budget, limits.max_repairs, True),
        ("repair_attempt_count", plan.repair_attempt_count, 1, True),
    ):
        minimum = 0 if allow_zero else 1
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < minimum
            or value > maximum
        ):
            raise ContractValidationError(f"semantic query {field_name} is invalid")
    if plan.repair_attempt_count > plan.repair_budget:
        raise ContractValidationError("semantic query repair budget is invalid")


def _validate_query_class_shape(
    plan: SemanticQueryPlan,
    *,
    effective_graph_view: EffectiveGraphView,
    supported_relation_types: Sequence[str],
) -> None:
    supported = set(supported_relation_types)
    visible_node_ids = {node.node_id for node in effective_graph_view.visible_nodes}
    if not set(plan.seed_node_ids).issubset(visible_node_ids):
        raise ContractValidationError("semantic query seed scope is unavailable")
    if plan.query_class == "relation_reasoning":
        if plan.max_hops < 1 or not plan.allowed_paths:
            raise ContractValidationError("relation reasoning requires bounded paths")
        for relation_type, direction in plan.allowed_paths:
            if relation_type not in supported:
                raise ContractValidationError("semantic query contains an unsupported hop")
            if direction not in {"out", "in"}:
                raise ContractValidationError("semantic query direction is unsupported")
        if (
            plan.exact_operation is not None
            or plan.exact_inventory_kind is not None
            or plan.exact_filter_term_hashes
            or plan.exact_identifier_term_hashes
            or plan.exact_topic_term_hashes
            or plan.exact_normalized_field is not None
        ):
            raise ContractValidationError("relation reasoning cannot carry exact execution")
        repair_fields_present = (
            bool(plan.relation_repair_identifier_term_hashes),
            bool(plan.relation_repair_concept_term_hashes),
            plan.relation_repair_policy_fingerprint is not None,
            plan.relation_repair_vocabulary_fingerprint is not None,
        )
        if any(repair_fields_present) and not all(repair_fields_present[1:]):
            raise ContractValidationError("relation fallback repair binding is incomplete")
        if any(repair_fields_present) and plan.repair_attempt_count != 1:
            raise ContractValidationError("relation fallback repair attempt is invalid")
        return
    if (
        plan.allowed_paths
        or plan.seed_node_ids
        or plan.max_hops != 0
        or plan.relation_repair_identifier_term_hashes
        or plan.relation_repair_concept_term_hashes
        or plan.relation_repair_policy_fingerprint is not None
        or plan.relation_repair_vocabulary_fingerprint is not None
    ):
        raise ContractValidationError("semantic query plan would widen graph scope")
    if plan.query_class == "exact_set_or_inventory":
        if plan.exact_operation != "inventory_with_count" or not plan.exact_inventory_kind:
            raise ContractValidationError("exact query requires structured inventory scope")
        expected_filter_hashes = tuple(
            sorted(set(plan.exact_identifier_term_hashes) | set(plan.exact_topic_term_hashes))
        )
        if plan.exact_filter_term_hashes != expected_filter_hashes:
            raise ContractValidationError("exact query filter slots are inconsistent")
        return
    if (
        plan.exact_operation is not None
        or plan.exact_inventory_kind is not None
        or plan.exact_filter_term_hashes
        or plan.exact_identifier_term_hashes
        or plan.exact_topic_term_hashes
        or plan.exact_normalized_field is not None
    ):
        raise ContractValidationError("non-exact query cannot carry exact execution")


def _deterministic_inventory_kind(query_text: str) -> str:
    normalized = query_text.casefold()
    if "purchase order" in normalized or "採購單" in normalized or re.search(r"\bpo\b", normalized):
        return "purchase_order"
    if any(term in normalized for term in ("message", "email", "mail", "訊息", "郵件")):
        return "mail_observation"
    return "generic_identifier"


def repair_relation_plan_once(
    plan: SemanticQueryPlan,
    *,
    seed_node_ids: Sequence[str],
    required_identifier_term_hashes: Sequence[str],
    required_concept_term_hashes: Sequence[str],
    policy_fingerprint: str,
    vocabulary_fingerprint: str,
) -> SemanticQueryPlan:
    """Create the one scope-preserving relation fallback plan."""

    if plan.query_class != "relation_reasoning":
        raise ContractValidationError("relation fallback repair is unavailable")
    if plan.repair_budget < 1 or plan.repair_attempt_count >= plan.repair_budget:
        raise ContractValidationError("semantic relation repair budget is exhausted")
    identifier_hashes = tuple(sorted(set(required_identifier_term_hashes)))
    concept_hashes = tuple(sorted(set(required_concept_term_hashes)))
    if not concept_hashes:
        raise ContractValidationError("relation fallback concept scope is unavailable")
    if plan.seed_node_ids and not set(seed_node_ids).issubset(plan.seed_node_ids):
        raise ContractValidationError("relation fallback would widen seed scope")
    repaired = replace(
        plan,
        seed_node_ids=tuple(sorted(set(seed_node_ids))),
        repair_attempt_count=plan.repair_attempt_count + 1,
        relation_repair_identifier_term_hashes=identifier_hashes,
        relation_repair_concept_term_hashes=concept_hashes,
        relation_repair_policy_fingerprint=policy_fingerprint,
        relation_repair_vocabulary_fingerprint=vocabulary_fingerprint,
    )
    _validate_plan_strings(repaired)
    return repaired


def _require_nonempty_public_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} is required")
    safe_public_string(value, field_name)


__all__ = [
    "AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND",
    "GITHUB_PROJECT_OBSERVATION_SOURCE_KIND",
    "AuthorizedSemanticSource",
    "DEFAULT_SEMANTIC_PLAN_LIMITS",
    "SEMANTIC_QUERY_CLASSES",
    "SemanticPlanLimits",
    "SemanticQueryPlan",
    "deterministic_query_class",
    "repair_relation_plan_once",
    "route_semantic_query",
    "validated_authorized_semantic_source",
    "validate_semantic_query_plan",
]
