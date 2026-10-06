"""Deterministic, fail-closed semantic query plans for Issue #56 POC execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Sequence

from formowl_contract import (
    CORE_SUPERTYPE_IDS,
    ContractValidationError,
    PermissionScope,
    sha256_json,
    to_plain,
    validate_permission_scope,
)
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
EXACT_QUERY_GRAMMAR_ROLES = (
    "conjunction",
    "operator",
    "particle",
    "preposition",
    "pronoun",
    "verb",
)
_EXACT_QUERY_LEXICAL_ROLES = {
    "filter_value",
    "projection_field",
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
    "哪些",
    "明細",
)
_CJK_EXACT_OUTPUT_GRAMMAR_V1 = (
    ("列出", "列舉", "調閱", "整理"),
    ("出來",),
    ("全部", "都", "所有"),
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
    authorized_permission_scopes: tuple[PermissionScope, ...] = ()

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
        if not isinstance(self.authorized_permission_scopes, tuple):
            raise ContractValidationError("semantic query permission scope binding is invalid")
        normalized_scopes: list[tuple[str, PermissionScope]] = []
        scope_ids: set[str] = set()
        for permission_scope in self.authorized_permission_scopes:
            normalized = _canonical_permission_scope(permission_scope)
            scope_id = normalized["scope_id"]
            assert isinstance(scope_id, str)
            if scope_id not in self.source_scope_ids or scope_id in scope_ids:
                raise ContractValidationError(
                    "semantic query permission scope binding is invalid"
                )
            scope_ids.add(scope_id)
            normalized_scopes.append((sha256_json(normalized), permission_scope))
        if tuple(hash_value for hash_value, _scope in normalized_scopes) != tuple(
            sorted(hash_value for hash_value, _scope in normalized_scopes)
        ):
            raise ContractValidationError(
                "semantic query permission scope binding is not canonical"
            )

    @property
    def occurrence_schema_id(self) -> str:
        return _SOURCE_OCCURRENCE_SCHEMA_BY_KIND[self.source_kind]

    @property
    def authorization_fingerprint(self) -> str:
        payload = {
            "schema_version": 1,
            "source_kind": self.source_kind,
            "occurrence_schema_id": self.occurrence_schema_id,
            "workspace_id": self.workspace_id,
            "source_scope_ids": list(self.source_scope_ids),
        }
        if self.authorized_permission_scopes:
            payload["authorized_permission_scope_hashes"] = [
                sha256_json(scope.to_dict())
                for scope in self.authorized_permission_scopes
            ]
        return sha256_json(payload)


def validated_authorized_semantic_source(
    *,
    source_kind: str,
    workspace_id: str,
    source_scope_ids: Sequence[str],
    authorized_permission_scopes: Sequence[PermissionScope] = (),
) -> AuthorizedSemanticSource:
    """Validate one upstream-authorized source scope without accepting mixed kinds."""

    normalized_scopes = tuple(
        sorted(
            authorized_permission_scopes,
            key=lambda scope: sha256_json(_canonical_permission_scope(scope)),
        )
    )
    return AuthorizedSemanticSource(
        source_kind=source_kind,
        workspace_id=workspace_id,
        source_scope_ids=tuple(sorted(set(source_scope_ids))),
        authorized_permission_scopes=normalized_scopes,
    )


def authorized_permission_scope_matches(
    permission_scope: Any,
    *,
    authorized_source: AuthorizedSemanticSource,
) -> bool:
    """Check a source permission scope without widening legacy mail/GitHub paths."""

    normalized = to_plain(permission_scope)
    if not isinstance(normalized, dict):
        return False
    scope_type = normalized.get("scope_type")
    scope_id = normalized.get("scope_id")
    if not isinstance(scope_type, str) or not isinstance(scope_id, str) or not scope_id:
        return False
    if authorized_source.source_kind == GITHUB_PROJECT_OBSERVATION_SOURCE_KIND:
        return scope_type == "project" and scope_id in authorized_source.source_scope_ids
    if authorized_source.source_kind != AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND:
        return False
    if scope_type == "workspace":
        return scope_id == authorized_source.workspace_id
    if scope_type == "mail_import_session":
        return scope_id in authorized_source.source_scope_ids
    if scope_type != "project":
        return False
    return any(
        scope.to_dict() == normalized
        for scope in authorized_source.authorized_permission_scopes
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
    exact_projection_term_hashes: tuple[str, ...] = ()
    exact_column_value_hash_pairs: tuple[tuple[str, str], ...] = ()
    exact_lexical_term_ledger: tuple[tuple[str, str, str, str], ...] = ()
    exact_grammar_term_ledger: tuple[tuple[str, str], ...] = ()
    exact_grammar_policy_fingerprint: str | None = None
    exact_source_occurrence_provider_fingerprint: str | None = None
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
        if self.exact_projection_term_hashes:
            payload["exact_projection_term_hashes"] = list(
                self.exact_projection_term_hashes
            )
        if self.exact_lexical_term_ledger:
            payload["exact_structured_query_binding"] = {
                "column_value_hash_pairs": [
                    list(pair) for pair in self.exact_column_value_hash_pairs
                ],
                "lexical_term_ledger": [
                    list(binding) for binding in self.exact_lexical_term_ledger
                ],
                "grammar_term_ledger": [
                    list(binding) for binding in self.exact_grammar_term_ledger
                ],
                "grammar_policy_fingerprint": (
                    self.exact_grammar_policy_fingerprint
                ),
                "provider_fingerprint": (
                    self.exact_source_occurrence_provider_fingerprint
                ),
            }
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
            **(
                {"exact_projection_term_hashes": list(self.exact_projection_term_hashes)}
                if self.exact_projection_term_hashes
                else {}
            ),
            **(
                {
                    "exact_structured_query_binding": {
                        "column_value_hash_pairs": [
                            list(pair)
                            for pair in self.exact_column_value_hash_pairs
                        ],
                        "lexical_term_ledger": [
                            list(binding)
                            for binding in self.exact_lexical_term_ledger
                        ],
                        "grammar_term_ledger": [
                            list(binding)
                            for binding in self.exact_grammar_term_ledger
                        ],
                        "grammar_policy_fingerprint": (
                            self.exact_grammar_policy_fingerprint
                        ),
                        "provider_fingerprint": (
                            self.exact_source_occurrence_provider_fingerprint
                        ),
                    }
                }
                if self.exact_lexical_term_ledger
                else {}
            ),
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
    (
        output_verbs,
        completion_markers,
        inventory_markers,
    ) = _CJK_EXACT_OUTPUT_GRAMMAR_V1
    if (
        any(term in normalized for term in output_verbs)
        and (
            any(marker in normalized for marker in completion_markers)
            or any(marker in normalized for marker in inventory_markers)
        )
    ):
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
    exact_projection_term_hashes: Sequence[str] = (),
    exact_column_value_hash_pairs: Sequence[tuple[str, str]] = (),
    exact_lexical_term_ledger: Sequence[tuple[str, str, str, str]] = (),
    exact_grammar_term_ledger: Sequence[tuple[str, str]] = (),
    exact_grammar_policy_fingerprint: str | None = None,
    exact_source_occurrence_provider_fingerprint: str | None = None,
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
        exact_projection_term_hashes=(
            tuple(sorted(set(exact_projection_term_hashes)))
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_column_value_hash_pairs=(
            tuple(sorted(set(exact_column_value_hash_pairs)))
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_lexical_term_ledger=(
            tuple(exact_lexical_term_ledger)
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_grammar_term_ledger=(
            tuple(exact_grammar_term_ledger)
            if query_class == "exact_set_or_inventory"
            else ()
        ),
        exact_grammar_policy_fingerprint=(
            exact_grammar_policy_fingerprint
            if query_class == "exact_set_or_inventory"
            else None
        ),
        exact_source_occurrence_provider_fingerprint=(
            exact_source_occurrence_provider_fingerprint
            if query_class == "exact_set_or_inventory"
            else None
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
        ("exact_projection_term_hashes", plan.exact_projection_term_hashes),
        (
            "exact_column_value_hash_pairs",
            tuple(
                value
                for pair in plan.exact_column_value_hash_pairs
                for value in pair
            ),
        ),
        (
            "exact_lexical_term_ledger",
            tuple(
                value
                for binding in plan.exact_lexical_term_ledger
                for value in binding
            ),
        ),
        (
            "exact_grammar_term_ledger",
            tuple(
                value
                for binding in plan.exact_grammar_term_ledger
                for value in binding
            ),
        ),
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
        *plan.exact_projection_term_hashes,
        *(
            value
            for pair in plan.exact_column_value_hash_pairs
            for value in pair
        ),
        *(
            value
            for term_hash, _role, column_hash, grounded_hash in (
                plan.exact_lexical_term_ledger
            )
            for value in (term_hash, column_hash, grounded_hash)
        ),
        *(term_hash for term_hash, _role in plan.exact_grammar_term_ledger),
        *plan.exact_identifier_term_hashes,
        *plan.exact_topic_term_hashes,
        *plan.relation_repair_identifier_term_hashes,
        *plan.relation_repair_concept_term_hashes,
    ):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", term_hash) is None:
            raise ContractValidationError("semantic query term hash is invalid")
    for _term_hash, role, _column_hash, _grounded_hash in (
        plan.exact_lexical_term_ledger
    ):
        if role not in _EXACT_QUERY_LEXICAL_ROLES:
            raise ContractValidationError(
                "semantic query lexical term role is invalid"
            )
    for _term_hash, role in plan.exact_grammar_term_ledger:
        if role not in EXACT_QUERY_GRAMMAR_ROLES:
            raise ContractValidationError(
                "semantic query grammar term role is invalid"
            )
    lexical_occurrence_hashes = tuple(
        term_hash
        for term_hash, _role, _column_hash, _grounded_hash in (
            plan.exact_lexical_term_ledger
        )
    )
    grammar_occurrence_hashes = tuple(
        term_hash for term_hash, _role in plan.exact_grammar_term_ledger
    )
    lexical_bindings_by_term: dict[str, set[tuple[str, str, str]]] = {}
    for term_hash, role, column_hash, grounded_hash in plan.exact_lexical_term_ledger:
        lexical_bindings_by_term.setdefault(term_hash, set()).add(
            (role, column_hash, grounded_hash)
        )
    if (
        len(set(plan.exact_lexical_term_ledger))
        != len(plan.exact_lexical_term_ledger)
        or any(
            len(bindings) > 1
            and (
                {role for role, _column_hash, _grounded_hash in bindings}
                != {"filter_value"}
                or len(
                    {
                        grounded_hash
                        for _role, _column_hash, grounded_hash in bindings
                    }
                )
                != 1
            )
            for bindings in lexical_bindings_by_term.values()
        )
        or len(set(grammar_occurrence_hashes)) != len(grammar_occurrence_hashes)
        or set(lexical_occurrence_hashes).intersection(
            grammar_occurrence_hashes
        )
    ):
        raise ContractValidationError(
            "semantic query grounding ledger is invalid"
        )
    for field_name, fingerprint in (
        (
            "exact_grammar_policy_fingerprint",
            plan.exact_grammar_policy_fingerprint,
        ),
        (
            "exact_source_occurrence_provider_fingerprint",
            plan.exact_source_occurrence_provider_fingerprint,
        ),
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
    if plan.seed_node_ids:
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
            or plan.exact_projection_term_hashes
            or plan.exact_column_value_hash_pairs
            or plan.exact_lexical_term_ledger
            or plan.exact_grammar_term_ledger
            or plan.exact_grammar_policy_fingerprint is not None
            or plan.exact_source_occurrence_provider_fingerprint is not None
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
        if set(plan.exact_filter_term_hashes).intersection(
            plan.exact_projection_term_hashes
        ):
            raise ContractValidationError(
                "exact query filter and projection slots overlap"
            )
        structured_fields_present = (
            bool(plan.exact_column_value_hash_pairs),
            bool(plan.exact_lexical_term_ledger),
            bool(plan.exact_grammar_term_ledger),
            plan.exact_grammar_policy_fingerprint is not None,
            plan.exact_source_occurrence_provider_fingerprint is not None,
        )
        if any(structured_fields_present):
            if not (
                plan.exact_column_value_hash_pairs
                and plan.exact_lexical_term_ledger
                and plan.exact_grammar_policy_fingerprint is not None
                and plan.exact_source_occurrence_provider_fingerprint is not None
            ):
                raise ContractValidationError(
                    "exact structured query binding is incomplete"
                )
            filter_pairs = tuple(
                sorted(
                    {
                        (column_hash, grounded_hash)
                        for (
                            _term_hash,
                            role,
                            column_hash,
                            grounded_hash,
                        ) in plan.exact_lexical_term_ledger
                        if role == "filter_value"
                    }
                )
            )
            projection_columns = tuple(
                sorted(
                    {
                        column_hash
                        for (
                            _term_hash,
                            role,
                            column_hash,
                            _grounded_hash,
                        ) in plan.exact_lexical_term_ledger
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
            ):
                raise ContractValidationError(
                    "exact structured query slots are inconsistent"
                )
        return
    if (
        plan.exact_operation is not None
        or plan.exact_inventory_kind is not None
        or plan.exact_filter_term_hashes
        or plan.exact_projection_term_hashes
        or plan.exact_column_value_hash_pairs
        or plan.exact_lexical_term_ledger
        or plan.exact_grammar_term_ledger
        or plan.exact_grammar_policy_fingerprint is not None
        or plan.exact_source_occurrence_provider_fingerprint is not None
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


def _canonical_permission_scope(value: PermissionScope) -> dict[str, Any]:
    if not isinstance(value, PermissionScope):
        raise ContractValidationError("semantic query permission scope binding is invalid")
    normalized = to_plain(value)
    if not isinstance(normalized, dict):
        raise ContractValidationError("semantic query permission scope binding is invalid")
    try:
        validate_permission_scope(normalized)
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise ContractValidationError(
            "semantic query permission scope binding is invalid"
        ) from exc
    if set(normalized) not in (
        {"scope_type", "scope_id", "visibility"},
        {"scope_type", "scope_id", "visibility", "inherited_from"},
    ):
        raise ContractValidationError("semantic query permission scope binding is invalid")
    if normalized.get("scope_type") not in {
        "workspace",
        "mail_import_session",
        "project",
    } or normalized.get("visibility") != "restricted":
        raise ContractValidationError("semantic query permission scope binding is invalid")
    _require_nonempty_public_string(normalized.get("scope_id"), "permission_scope.scope_id")
    inherited_from = normalized.get("inherited_from")
    if inherited_from is not None:
        _require_nonempty_public_string(
            inherited_from,
            "permission_scope.inherited_from",
        )
    return normalized


__all__ = [
    "AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND",
    "GITHUB_PROJECT_OBSERVATION_SOURCE_KIND",
    "AuthorizedSemanticSource",
    "DEFAULT_SEMANTIC_PLAN_LIMITS",
    "EXACT_QUERY_GRAMMAR_ROLES",
    "SEMANTIC_QUERY_CLASSES",
    "SemanticPlanLimits",
    "SemanticQueryPlan",
    "authorized_permission_scope_matches",
    "deterministic_query_class",
    "repair_relation_plan_once",
    "route_semantic_query",
    "validated_authorized_semantic_source",
    "validate_semantic_query_plan",
]
