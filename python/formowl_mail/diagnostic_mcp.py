"""Real candidate-KG MCP gateway for the internal diagnostic UAT.

This server owns the preserved diagnostic evidence work directory.  It exposes
one read-only MCP tool whose canonical schema name is
``query_effective_graph_view``.  The actual retrieval layer is deliberately
and explicitly narrower: it invokes the default
``CandidateEvidenceIndex.retrieve`` path over a candidate-only evidence index.
It does not load, write, or claim a canonical effective graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping, Sequence
import unicodedata

from formowl_contract import (
    AdmissibleSemanticScope,
    ClaimRequirement,
    ContractValidationError,
    CoverageAuthorizationBinding,
    CoverageItemRelevanceDecision,
    CoverageLedger,
    CoverageObservationPartition,
    CoverageScopeAuthority,
    CoverageScopeAuthorityVerifier,
    CoverageScopePartition,
    CoverageProofRecord,
    CoverageVersionBinding,
    DisplayPagination,
    PermissionFirstSemanticPlanner,
    SemanticPlanClarificationRequired,
    SemanticSchemaAliasMap,
    SemanticTaskSkeleton,
    SourceInventory,
    StructuralObservation,
    VersionManifest,
    sha256_json,
    stable_resource_contract_id,
)
from formowl_graph.candidate_retrieval import DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID
from formowl_graph.task_answering import TaskAnsweringEngine

from .bundle import MailEvidenceBundle
from .persistence import (
    DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND,
    DIAGNOSTIC_STRUCTURAL_BRIDGE_IMPLEMENTATION_VERSION,
    DIAGNOSTIC_STRUCTURAL_BRIDGE_PRODUCER_TYPE,
    DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID,
    DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_VERSION,
    DiagnosticStructuralAggregateManifest,
    DiagnosticStructuralShardRecord,
    FileDiagnosticStructuralShardStore,
    diagnostic_structural_baseline_parameters,
    diagnostic_structural_implementation_fingerprint,
    diagnostic_structural_scope_policy_fingerprint,
)
from .query import execute_authorized_structured_set


MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_NAME = "formowl"
MCP_TOOL_NAME = "query_effective_graph_view"
RETRIEVAL_PATH = "mail_candidate_kg_default_retrieval"
RETRIEVAL_LAYER = "candidate_only_kg_evidence"
SEMANTIC_RETRIEVAL_PATH = "mail_authorized_structured_set"
SEMANTIC_RETRIEVAL_LAYER = "canonical_mail_structural_evidence"
SEMANTIC_THIN_TOPOLOGY_COMPATIBILITY_LAYER = "candidate_only_kg_evidence"
ONTOLOGY_RERANK_ENABLED = False
CANONICAL_KG = False
_MAX_QUERY_CHARS = 8_000
_MAX_LIMIT = 20
_MAX_SEMANTIC_PAGE_SIZE = 100
_MAX_SEMANTIC_PAGE_NUMBER = 10_000
# The complete-set transport limit is deliberately server-owned.  It is
# independent of the caller-controlled display page and remains small enough
# that the one-call UAT model can receive and render the exact projection
# without unbounded context or response growth.
SEMANTIC_COMPLETE_SET_MAX_ITEMS = 256
SEMANTIC_COMPLETE_SET_MAX_SERIALIZED_BYTES = 8 * 1024
_MAX_HTTP_REQUEST_BYTES = 32 * 1024
_MAX_SNIPPET_CHARS = 1_200
_MAX_SUBJECT_CHARS = 500
_MAX_EVIDENCE_ITEMS_PER_SOURCE = 4
_MAX_EVIDENCE_ITEMS_OVERALL = 20
_MAX_QUERY_COVERAGE_TERMS = 64
_EXACT_IDENTIFIER_ATTRIBUTE_SOURCE_LIMIT = 1
_MIXED_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*)(?![A-Za-z0-9])"
)
_ASCII_QUERY_WORD_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9_-]{2,}(?![A-Za-z0-9])")
_CJK_QUERY_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
_MULTI_SOURCE_INTENT_RE = re.compile(r"(?i)\b(?:all|every|each)\b|全部|所有|每(?:一|個|筆)")
_QUERY_STOPWORDS = frozenset(
    {
        "about",
        "are",
        "can",
        "could",
        "does",
        "find",
        "for",
        "from",
        "have",
        "how",
        "please",
        "show",
        "that",
        "the",
        "this",
        "what",
        "where",
        "which",
        "with",
        "可以",
        "是否",
        "有沒有",
        "請問",
    }
)
_CJK_QUERY_PREFIX_STOPWORDS = ("有沒有", "請問", "是否", "想知道", "查詢", "尋找", "有", "的", "或")
_CJK_QUERY_SUFFIX_STOPWORDS = ("可以嗎", "是否", "嗎", "呢", "的")
_SEMANTIC_REQUEST_KEYS = frozenset(
    {
        "query_class",
        "object_type_mention",
        "predicate_mention",
        "operator",
        "value_mention",
        "projection_mention",
        "cardinality",
        "page_size",
        "page_number",
    }
)
_SEMANTIC_PROFILE_FINGERPRINT_KEYS = frozenset(
    {
        "profile_id",
        "profile_version",
        "scope",
        "aliases",
    }
)
_SEMANTIC_PROFILE_SCOPE_KEYS = frozenset(
    {
        "workspace_id",
        "owner_user_id",
        "actor_context_id",
        "known_as_of",
    }
)
_SEMANTIC_RUNTIME_SCOPE_KIND = "runtime_grounded_structured_set_v1"


@dataclass(frozen=True)
class DiagnosticSemanticProfile:
    """Server-owned, versioned semantic aliases and admissibility context.

    The profile is intentionally not part of the MCP tool schema.  It is
    loaded from a private deployment file, fingerprinted before the runtime is
    created, and is the only source of aliases and actor/workspace context for
    structured set requests.
    """

    profile_id: str
    profile_version: str
    profile_fingerprint: str
    schema_alias_map: SemanticSchemaAliasMap
    workspace_id: str
    owner_user_id: str
    actor_context_id: str
    known_as_of: str

    def __post_init__(self) -> None:
        for field_name in (
            "profile_id",
            "profile_version",
            "workspace_id",
            "owner_user_id",
            "actor_context_id",
            "known_as_of",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"semantic profile {field_name} is invalid")
        if not isinstance(self.profile_fingerprint, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.profile_fingerprint
        ):
            raise ValueError("semantic profile fingerprint is invalid")
        if not isinstance(self.schema_alias_map, SemanticSchemaAliasMap):
            raise ValueError("semantic profile aliases are invalid")
        if len(self.schema_alias_map.predicate_aliases) < 2:
            raise ValueError("semantic profile must support multiple predicates")
        if _parse_iso_instant(self.known_as_of) is None:
            raise ValueError("semantic profile known-as-of is invalid")
        if self.profile_fingerprint != sha256_json(self.fingerprint_payload):
            raise ValueError("semantic profile fingerprint does not match contents")

    @property
    def fingerprint_payload(self) -> dict[str, Any]:
        return self.fingerprint_payload_for(
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            schema_alias_map=self.schema_alias_map,
            workspace_id=self.workspace_id,
            owner_user_id=self.owner_user_id,
            actor_context_id=self.actor_context_id,
            known_as_of=self.known_as_of,
        )

    @staticmethod
    def fingerprint_payload_for(
        *,
        profile_id: str,
        profile_version: str,
        schema_alias_map: SemanticSchemaAliasMap,
        workspace_id: str,
        owner_user_id: str,
        actor_context_id: str,
        known_as_of: str,
    ) -> dict[str, Any]:
        return {
            "profile_id": profile_id,
            "profile_version": profile_version,
            "scope": {
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "actor_context_id": actor_context_id,
                "known_as_of": known_as_of,
            },
            "aliases": {
                "object_aliases": {
                    key: list(value) for key, value in schema_alias_map.object_aliases.items()
                },
                "predicate_aliases": {
                    key: list(value) for key, value in schema_alias_map.predicate_aliases.items()
                },
                "value_aliases": {
                    predicate: {value: list(forms) for value, forms in values.items()}
                    for predicate, values in schema_alias_map.value_aliases.items()
                },
            },
        }

    @classmethod
    def fingerprint_for(
        cls,
        *,
        profile_id: str,
        profile_version: str,
        schema_alias_map: SemanticSchemaAliasMap,
        workspace_id: str,
        owner_user_id: str,
        actor_context_id: str,
        known_as_of: str,
    ) -> str:
        return sha256_json(
            cls.fingerprint_payload_for(
                profile_id=profile_id,
                profile_version=profile_version,
                schema_alias_map=schema_alias_map,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                actor_context_id=actor_context_id,
                known_as_of=known_as_of,
            )
        )

    @classmethod
    def from_private_dict(cls, value: Mapping[str, Any]) -> "DiagnosticSemanticProfile":
        if not isinstance(value, Mapping) or set(value) != (
            _SEMANTIC_PROFILE_FINGERPRINT_KEYS | {"profile_fingerprint"}
        ):
            raise ValueError("semantic profile fields are invalid")
        scope = value.get("scope")
        aliases = value.get("aliases")
        if not isinstance(scope, Mapping) or set(scope) != _SEMANTIC_PROFILE_SCOPE_KEYS:
            raise ValueError("semantic profile scope is invalid")
        if not isinstance(aliases, Mapping) or set(aliases) != {
            "object_aliases",
            "predicate_aliases",
            "value_aliases",
        }:
            raise ValueError("semantic profile aliases are invalid")
        return cls(
            profile_id=value["profile_id"],
            profile_version=value["profile_version"],
            profile_fingerprint=value["profile_fingerprint"],
            schema_alias_map=SemanticSchemaAliasMap(
                object_aliases=aliases["object_aliases"],
                predicate_aliases=aliases["predicate_aliases"],
                value_aliases=aliases["value_aliases"],
            ),
            workspace_id=scope["workspace_id"],
            owner_user_id=scope["owner_user_id"],
            actor_context_id=scope["actor_context_id"],
            known_as_of=scope["known_as_of"],
        )


@dataclass(frozen=True)
class _SemanticMcpRequest:
    """Closed caller-provided skeleton; it contains no grounded vocabulary."""

    query_class: str
    object_type_mention: str
    predicate_mention: str
    operator: str
    value_mention: str
    projection_mention: str
    cardinality: str
    page_size: int
    page_number: int

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "_SemanticMcpRequest":
        if not isinstance(value, Mapping) or set(value) != _SEMANTIC_REQUEST_KEYS:
            raise ContractValidationError("semantic request fields are invalid")
        request = cls(
            query_class=value["query_class"],
            object_type_mention=value["object_type_mention"],
            predicate_mention=value["predicate_mention"],
            operator=value["operator"],
            value_mention=value["value_mention"],
            projection_mention=value["projection_mention"],
            cardinality=value["cardinality"],
            page_size=value["page_size"],
            page_number=value["page_number"],
        )
        request._validate()
        return request

    def _validate(self) -> None:
        if self.query_class != "attribute_filter":
            raise ContractValidationError("semantic request query class is invalid")
        if self.operator != "equals":
            raise ContractValidationError("semantic request operator is invalid")
        if self.cardinality != "all_matching":
            raise ContractValidationError("semantic request cardinality is invalid")
        for field_name in (
            "object_type_mention",
            "predicate_mention",
            "value_mention",
            "projection_mention",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or len(value) > _MAX_QUERY_CHARS:
                raise ContractValidationError(f"semantic request {field_name} is invalid")
        for field_name, maximum in (
            ("page_size", _MAX_SEMANTIC_PAGE_SIZE),
            ("page_number", _MAX_SEMANTIC_PAGE_NUMBER),
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
                raise ContractValidationError(f"semantic request {field_name} is invalid")


@dataclass(frozen=True)
class _ResolvedSemanticScope:
    """One complete server-owned structural scope, before schema grounding."""

    bundle: MailEvidenceBundle
    coverage_ledger: CoverageLedger
    claim_requirement: ClaimRequirement
    source_inventory: SourceInventory
    version_manifest: VersionManifest
    scope_authority: CoverageScopeAuthority
    authorization_binding: CoverageAuthorizationBinding
    structural_observations: tuple[StructuralObservation, ...]
    authorized_inventory_item_ids: tuple[str, ...]
    admissibility: AdmissibleSemanticScope


@dataclass(frozen=True)
class PrevalidatedSemanticShardTemplate:
    """One startup-proven baseline scope for the diagnostic aggregate cache.

    This is an in-memory deployment boundary, not a persisted graph or query
    result cache.  It retains existing immutable evidence-object references and
    identifier-only maps so a request does not re-run the complete permission
    and scope-admissibility pass or rebuild the item-by-observation cross
    product. Query-specific scopes are materialized and verified only during
    startup, then held by exact object identity for the process lifetime.
    """

    aggregate: DiagnosticStructuralAggregateManifest
    profile: DiagnosticSemanticProfile
    scope_authority_verifier: CoverageScopeAuthorityVerifier
    shard_record: DiagnosticStructuralShardRecord
    bundle: MailEvidenceBundle
    baseline_scope: _ResolvedSemanticScope
    structural_relevant_item_ids: tuple[str, ...]
    authorized_item_ids: tuple[str, ...]
    authorized_item_id_set: frozenset[str]
    item_by_id: Mapping[str, Any]
    observations_by_item: Mapping[str, tuple[str, ...]]
    ordinary_observations_by_item: Mapping[str, tuple[str, ...]]
    schema_candidate_observation_ordinals: Mapping[tuple[str, str], tuple[int, ...]]
    schema_unindexed_observation_ordinals: tuple[int, ...]
    topology_attestation: object
    thin_topology_compatibility: bool
    prevalidated_execution_scopes: Mapping[
        tuple[str, str],
        "_PrevalidatedDiagnosticExecutionScope",
    ]


@dataclass(frozen=True)
class _PrevalidatedDiagnosticExecutionScope:
    """One request-derived, query-keyed complete scope plus opaque task proof."""

    template: PrevalidatedSemanticShardTemplate
    object_type: str
    predicate: str
    query_scope: _ResolvedSemanticScope
    task_capability: object


_PREVALIDATED_TEMPLATE_ISSUANCES: dict[
    int,
    PrevalidatedSemanticShardTemplate,
] = {}


@dataclass(frozen=True)
class CandidateGraphQueryRuntime:
    """Bounded adapter around the evaluator's loaded candidate-KG index.

    ``candidate_index`` is the evaluator's private ``_CandidateKgIndex``.  It
    intentionally stays duck-typed here: the evaluator remains the owner of
    the validated loader, candidate admission policy, text policy runtime,
    temporal scope, and shared internal access binding.
    """

    candidate_index: Any
    access_binding: Any
    retrieval_scope: Mapping[str, Any]
    structural_bundles: tuple[MailEvidenceBundle, ...] = ()
    structural_shard_store: FileDiagnosticStructuralShardStore | None = None
    semantic_profile: DiagnosticSemanticProfile | None = None
    scope_authority_verifier: CoverageScopeAuthorityVerifier | None = None
    prevalidated_semantic_shard_templates: tuple[PrevalidatedSemanticShardTemplate, ...] = ()
    candidate_method_id: str = DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID
    ontology_rerank_enabled: bool = ONTOLOGY_RERANK_ENABLED

    def __post_init__(self) -> None:
        if self.candidate_method_id != DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID:
            raise ValueError("diagnostic UAT must use the default candidate retrieval method")
        if self.ontology_rerank_enabled is not False:
            raise ValueError("diagnostic UAT ontology rerank is not configured")
        if not isinstance(self.retrieval_scope, Mapping):
            raise ValueError("candidate retrieval scope is required")
        evidence_index = getattr(self.candidate_index, "evidence_index", None)
        segments = getattr(self.candidate_index, "segment_by_observation_id", None)
        text_policy_runtime = getattr(self.candidate_index, "text_policy_runtime", None)
        if (
            evidence_index is None
            or not isinstance(segments, Mapping)
            or not callable(getattr(text_policy_runtime, "tokenize", None))
        ):
            raise ValueError("candidate KG runtime is invalid")
        if any(not isinstance(bundle, MailEvidenceBundle) for bundle in self.structural_bundles):
            raise ValueError("diagnostic structural bundles are invalid")
        if self.structural_shard_store is not None and not isinstance(
            self.structural_shard_store,
            FileDiagnosticStructuralShardStore,
        ):
            raise ValueError("diagnostic structural shard store is invalid")
        if self.structural_bundles and self.structural_shard_store is not None:
            raise ValueError("diagnostic structural runtime source is ambiguous")
        if self.semantic_profile is not None and not isinstance(
            self.semantic_profile,
            DiagnosticSemanticProfile,
        ):
            raise ValueError("diagnostic semantic profile is invalid")
        if self.scope_authority_verifier is not None and not isinstance(
            self.scope_authority_verifier,
            CoverageScopeAuthorityVerifier,
        ):
            raise ValueError("diagnostic scope authority verifier is invalid")
        if not isinstance(self.prevalidated_semantic_shard_templates, tuple) or any(
            not isinstance(template, PrevalidatedSemanticShardTemplate)
            for template in self.prevalidated_semantic_shard_templates
        ):
            raise ValueError("diagnostic prevalidated shard templates are invalid")
        if self.prevalidated_semantic_shard_templates and self.structural_shard_store is None:
            raise ValueError("diagnostic prevalidated shard templates require a shard store")

    def retrieve(self, *, query_text: str, limit: int) -> Mapping[str, Any]:
        """Run bounded recall, diagnostic rerank, and source-group projection."""

        evidence_index = self.candidate_index.evidence_index
        retrieval = evidence_index.retrieve(
            query_text=query_text,
            limit=_MAX_LIMIT,
            enable_ontology_rerank=self.ontology_rerank_enabled,
            access_binding=self.access_binding,
            **dict(self.retrieval_scope),
        )
        selected_ids = _selected_observation_ids(retrieval)
        assembled_ids = _proof_neighborhood_observation_ids(
            retrieval,
            segments_by_observation_id=self.candidate_index.segment_by_observation_id,
            text_policy_runtime=self.candidate_index.text_policy_runtime,
            query_text=query_text,
            source_limit=limit,
        )
        results = [
            _safe_candidate_result(self.candidate_index.segment_by_observation_id[observation_id])
            for observation_id in assembled_ids
            if observation_id in self.candidate_index.segment_by_observation_id
        ]
        status = "ok" if results else "insufficient"
        payload: dict[str, Any] = {
            "status": status,
            "results": results,
            "total_result_count": _nonnegative_int(
                getattr(retrieval, "total_source_item_count", len(results))
            ),
            "displayed_result_count": len(results),
            "retrieval_path": RETRIEVAL_PATH,
            "retrieval_layer": RETRIEVAL_LAYER,
            "candidate_method_id": self.candidate_method_id,
            "ontology_rerank_enabled": self.ontology_rerank_enabled,
            "canonical_kg": CANONICAL_KG,
            "retrieval_trace": {
                # Anchor observations decide source-item ranking. The model
                # receives the assembled proof neighborhood, because an
                # answer-bearing field may be in a sibling segment of the
                # same selected logical source item.
                "ranking_selected_observation_count": len(selected_ids),
                "assembled_observation_count": len(assembled_ids),
                "per_source_evidence_cap": _MAX_EVIDENCE_ITEMS_PER_SOURCE,
                "overall_evidence_cap": _MAX_EVIDENCE_ITEMS_OVERALL,
                "requested_source_limit": limit,
                "internal_recall_source_limit": _MAX_LIMIT,
                "query_coverage_rerank": True,
            },
        }
        if status != "ok":
            payload["insufficiency_reason"] = _safe_insufficiency_reason(retrieval)
        return payload

    def execute_semantic_request(
        self,
        request: _SemanticMcpRequest,
    ) -> Mapping[str, Any]:
        """Run one permission-first, complete-scope structured set request.

        This is deliberately separate from candidate retrieval.  No candidate
        rank, alias lookup, or row value inspection occurs until the runtime
        has assembled a complete, authenticated, version-bound structural
        scope.  If that cannot be proven, the result is insufficient rather
        than a definitive no-match.
        """

        profile = self.semantic_profile
        if profile is None:
            return _semantic_insufficient_payload(request)
        if self.structural_shard_store is not None:
            return _execute_sharded_semantic_request(
                request=request,
                profile=profile,
                shard_store=self.structural_shard_store,
                scope_authority_verifier=self.scope_authority_verifier,
                prevalidated_templates=self.prevalidated_semantic_shard_templates,
            )
        if self.structural_bundles:
            # Legacy standalone bundles have no independently authenticated
            # whole-export verification. Even a cryptographically valid
            # per-bundle coverage authority cannot prove that the bundle is
            # the complete recovery universe, so it must not reach alias
            # grounding or produce a definitive complete-scope claim.
            return _semantic_insufficient_payload(request)
        scopes = _resolved_semantic_scopes(
            bundles=self.structural_bundles,
            profile=profile,
        )
        admissible_scope = _combined_admissibility(scopes, profile=profile)
        try:
            plan = PermissionFirstSemanticPlanner().ground_all_matching(
                skeleton=SemanticTaskSkeleton(
                    query_class=request.query_class,
                    projection_slots=("projection",),
                    constraint_slots=("object_type", "predicate", "value"),
                ),
                scope=admissible_scope,
                aliases=profile.schema_alias_map,
                object_type=request.object_type_mention,
                predicate=request.predicate_mention,
                value=request.value_mention,
                projection=request.projection_mention,
                operator=request.operator,
                page_size=request.page_size,
                page_number=request.page_number,
            )
        except SemanticPlanClarificationRequired:
            if not admissible_scope_complete(admissible_scope):
                if _semantic_permission_denied(
                    bundles=self.structural_bundles,
                    profile=profile,
                ):
                    return _semantic_permission_denied_payload(request)
                return _semantic_insufficient_payload(request)
            return _semantic_clarification_payload(request)

        matching_scopes = tuple(
            scope
            for scope in scopes
            if _normalized_semantic_text(scope.claim_requirement.predicate) == plan.predicate
        )
        if len(matching_scopes) == 1:
            scope = matching_scopes[0]
        elif (
            len(matching_scopes) == 0
            and (baseline_scope := _baseline_semantic_scope(scopes)) is not None
        ):
            try:
                scope = _derive_runtime_query_scope(
                    baseline_scope=baseline_scope,
                    plan=plan,
                    authority_verifier=self.scope_authority_verifier,
                )
            except (ContractValidationError, ValueError):
                return _semantic_insufficient_payload(request)
        else:
            # The caller's aliases are grounded only after the initial
            # permission/source/version/context/time/status gate.  A
            # predicate-specific coverage ledger must then be unique; merging
            # different scopes here could turn a partial set into an apparent
            # complete set.
            return _semantic_clarification_payload(request)
        execution = execute_authorized_structured_set(
            plan=plan,
            structural_observations=scope.structural_observations,
            authorized_inventory_item_ids=scope.authorized_inventory_item_ids,
            coverage_ledger=scope.coverage_ledger,
        )
        outcome = TaskAnsweringEngine.answer_canonical_claim(
            coverage_ledger=scope.coverage_ledger,
            claim_requirement=scope.claim_requirement,
            source_inventory=scope.source_inventory,
            version_manifest=scope.version_manifest,
            scope_authority=scope.scope_authority,
            authorization_binding=scope.authorization_binding,
            matched_structural_facts=execution.matched_structural_facts,
            structural_observations=scope.structural_observations,
        )
        if outcome.status != "ok" or outcome.claim is None:
            return _semantic_insufficient_payload(request)
        claim_state = outcome.claim.state
        complete_projection = (
            _semantic_complete_projection(execution.matches)
            if claim_state in {"FOUND", "NOT_FOUND_WITHIN_COMPLETE_SCOPE"}
            else _semantic_complete_projection_unavailable()
        )
        complete_projection_state = complete_projection["state"]
        result_is_transport_complete = complete_projection_state == "complete"
        return {
            # The claim state remains exclusively TaskAnswering-owned.  A
            # complete scope can still be too large to return as a single
            # deterministic set, in which case this transport response is
            # intentionally insufficient rather than an apparent complete
            # FOUND answer.
            "status": ("ok" if result_is_transport_complete else "insufficient"),
            "retrieval_path": SEMANTIC_RETRIEVAL_PATH,
            "retrieval_layer": SEMANTIC_RETRIEVAL_LAYER,
            "execution_mode": "authorized_structured_set",
            "query_class": request.query_class,
            "cardinality": request.cardinality,
            "claim_state": claim_state,
            "complete_projection": complete_projection,
            "display_pagination": {
                "page_size": execution.display_pagination.page_size,
                "page_number": execution.display_pagination.page_number,
                "displayed_count": execution.display_pagination.displayed_count,
                "has_more": execution.display_pagination.has_more,
            },
            # Do not disclose a display page or evidence handles when the
            # complete set could not safely cross the one-call boundary.
            "citation_handles": (
                _citation_handles(execution.displayed_matches)
                if result_is_transport_complete
                else []
            ),
            "canonical_kg": CANONICAL_KG,
        }


def _execute_sharded_semantic_request(
    *,
    request: _SemanticMcpRequest,
    profile: DiagnosticSemanticProfile,
    shard_store: FileDiagnosticStructuralShardStore,
    scope_authority_verifier: CoverageScopeAuthorityVerifier | None,
    prevalidated_templates: tuple[PrevalidatedSemanticShardTemplate, ...] = (),
) -> Mapping[str, Any]:
    """Validate all shards first, then ground and execute one aggregate call."""

    if prevalidated_templates:
        return _execute_prevalidated_sharded_semantic_request(
            request=request,
            profile=profile,
            shard_store=shard_store,
            scope_authority_verifier=scope_authority_verifier,
            templates=prevalidated_templates,
        )
    if not isinstance(scope_authority_verifier, CoverageScopeAuthorityVerifier):
        return _semantic_insufficient_payload(request)
    try:
        aggregate = shard_store.load_complete_manifest()
    except (ContractValidationError, OSError, ValueError):
        return _semantic_insufficient_payload(request)
    if (
        aggregate.workspace_id != profile.workspace_id
        or aggregate.owner_user_id != profile.owner_user_id
    ):
        return _semantic_permission_denied_payload(request)
    if aggregate.semantic_profile_fingerprint != profile.profile_fingerprint:
        return _semantic_insufficient_payload(request)

    # Phase one deliberately validates the complete aggregate without alias
    # grounding or row-value inspection. Each yielded bundle is released before
    # the next one is loaded.
    validated_bundle_count = 0
    try:
        for record, bundle in zip(
            aggregate.shards,
            shard_store.iter_bundles(
                aggregate,
                scope_authority_verifier=scope_authority_verifier,
            ),
            strict=True,
        ):
            if not _shard_bundle_matches_existing_export_verification(
                bundle=bundle,
                record=record,
                aggregate=aggregate,
                profile=profile,
            ):
                return _semantic_insufficient_payload(request)
            scopes = _resolved_semantic_scopes(bundles=(bundle,), profile=profile)
            baseline = _baseline_semantic_scope(scopes)
            if baseline is None or not admissible_scope_complete(
                _combined_admissibility(scopes, profile=profile)
            ):
                if _semantic_permission_denied(bundles=(bundle,), profile=profile):
                    return _semantic_permission_denied_payload(request)
                return _semantic_insufficient_payload(request)
            validated_bundle_count += 1
            del baseline
            del scopes
            del bundle
    except (ContractValidationError, OSError, ValueError):
        return _semantic_insufficient_payload(request)
    if validated_bundle_count != len(aggregate.shards):
        return _semantic_insufficient_payload(request)

    admissible_scope = AdmissibleSemanticScope(
        permission_admissible=True,
        source_admissible=True,
        version_admissible=True,
        context_admissible=True,
        time_admissible=True,
        status_admissible=True,
    )
    try:
        plan = PermissionFirstSemanticPlanner().ground_all_matching(
            skeleton=SemanticTaskSkeleton(
                query_class=request.query_class,
                projection_slots=("projection",),
                constraint_slots=("object_type", "predicate", "value"),
            ),
            scope=admissible_scope,
            aliases=profile.schema_alias_map,
            object_type=request.object_type_mention,
            predicate=request.predicate_mention,
            value=request.value_mention,
            projection=request.projection_mention,
            operator=request.operator,
            page_size=request.page_size,
            page_number=request.page_number,
        )
    except SemanticPlanClarificationRequired:
        return _semantic_clarification_payload(request)

    unique_projections: set[tuple[str, ...]] = set()
    projection_state = "complete"
    serialized_bytes = 2
    found_in_any_complete_shard = False
    try:
        for record, bundle in zip(
            aggregate.shards,
            shard_store.iter_bundles(
                aggregate,
                scope_authority_verifier=scope_authority_verifier,
            ),
            strict=True,
        ):
            if not _shard_bundle_matches_existing_export_verification(
                bundle=bundle,
                record=record,
                aggregate=aggregate,
                profile=profile,
            ):
                return _semantic_insufficient_payload(request)
            scopes = _resolved_semantic_scopes(bundles=(bundle,), profile=profile)
            baseline = _baseline_semantic_scope(scopes)
            if baseline is None:
                return _semantic_insufficient_payload(request)
            scope = _derive_runtime_query_scope(
                baseline_scope=baseline,
                plan=plan,
                authority_verifier=scope_authority_verifier,
            )
            if scope.structural_observations:
                execution = execute_authorized_structured_set(
                    plan=plan,
                    structural_observations=scope.structural_observations,
                    authorized_inventory_item_ids=scope.authorized_inventory_item_ids,
                    coverage_ledger=scope.coverage_ledger,
                )
                matches = execution.matches
                matched_facts = execution.matched_structural_facts
            else:
                matches = ()
                matched_facts = ()
            outcome = TaskAnsweringEngine.answer_canonical_claim(
                coverage_ledger=scope.coverage_ledger,
                claim_requirement=scope.claim_requirement,
                source_inventory=scope.source_inventory,
                version_manifest=scope.version_manifest,
                scope_authority=scope.scope_authority,
                authorization_binding=scope.authorization_binding,
                matched_structural_facts=matched_facts,
                structural_observations=scope.structural_observations,
            )
            if (
                outcome.status != "ok"
                or outcome.claim is None
                or outcome.claim.state not in {"FOUND", "NOT_FOUND_WITHIN_COMPLETE_SCOPE"}
            ):
                return _semantic_insufficient_payload(request)
            found_in_any_complete_shard = (
                found_in_any_complete_shard or outcome.claim.state == "FOUND"
            )
            for match in matches:
                projection = getattr(match, "projection_values", None)
                if (
                    not isinstance(projection, tuple)
                    or not projection
                    or any(not isinstance(value, str) or not value.strip() for value in projection)
                ):
                    projection_state = "projection_unavailable"
                    continue
                if projection in unique_projections:
                    continue
                projected_bytes = len(
                    json.dumps(
                        {"values": list(projection)},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                if (
                    len(unique_projections) >= SEMANTIC_COMPLETE_SET_MAX_ITEMS
                    or serialized_bytes + projected_bytes + (1 if unique_projections else 0)
                    > SEMANTIC_COMPLETE_SET_MAX_SERIALIZED_BYTES
                ):
                    projection_state = "result_budget_exceeded"
                    continue
                unique_projections.add(projection)
                serialized_bytes += projected_bytes + (1 if len(unique_projections) > 1 else 0)
            del scope
            del baseline
            del scopes
            del bundle
    except (ContractValidationError, OSError, TypeError, ValueError):
        return _semantic_insufficient_payload(request)

    ordered_projections = tuple(
        sorted(
            unique_projections,
            key=lambda values: (
                tuple(_normalized_semantic_text(value) for value in values),
                values,
            ),
        )
    )
    if projection_state == "complete":
        complete_projection = {
            "state": "complete",
            "values": [{"values": list(projection)} for projection in ordered_projections],
            "safe_result_budget": _semantic_complete_result_budget(),
        }
    elif projection_state == "projection_unavailable":
        complete_projection = _semantic_complete_projection_unavailable_projection()
    else:
        complete_projection = _semantic_complete_projection_budget_exceeded()
    page_start = (request.page_number - 1) * request.page_size
    displayed_count = len(ordered_projections[page_start : page_start + request.page_size])
    return {
        "status": "ok" if projection_state == "complete" else "insufficient",
        "retrieval_path": SEMANTIC_RETRIEVAL_PATH,
        "retrieval_layer": SEMANTIC_RETRIEVAL_LAYER,
        "execution_mode": "authorized_structured_set",
        "query_class": request.query_class,
        "cardinality": request.cardinality,
        "claim_state": (
            "FOUND" if found_in_any_complete_shard else "NOT_FOUND_WITHIN_COMPLETE_SCOPE"
        ),
        "complete_projection": complete_projection,
        "display_pagination": {
            "page_size": request.page_size,
            "page_number": request.page_number,
            "displayed_count": displayed_count,
            "has_more": len(ordered_projections) > page_start + displayed_count,
        },
        # Aggregate runtime intentionally emits no shard-derived citation or
        # storage handle. Evidence remains available only through a later
        # governed request when a user explicitly asks for it.
        "citation_handles": [],
        "canonical_kg": CANONICAL_KG,
    }


def prepare_prevalidated_semantic_shard_templates(
    *,
    aggregate: DiagnosticStructuralAggregateManifest,
    bundles: Sequence[MailEvidenceBundle],
    profile: DiagnosticSemanticProfile,
    scope_authority_verifier: CoverageScopeAuthorityVerifier,
) -> tuple[PrevalidatedSemanticShardTemplate, ...]:
    """Build immutable request templates only after full startup validation.

    The caller must retain the returned templates only in the in-memory,
    read-only diagnostic aggregate cache.  This function deliberately repeats
    the normal Phase-1 checks at startup, before any template is returned.
    """

    if (
        not isinstance(aggregate, DiagnosticStructuralAggregateManifest)
        or not isinstance(profile, DiagnosticSemanticProfile)
        or not isinstance(scope_authority_verifier, CoverageScopeAuthorityVerifier)
    ):
        raise ContractValidationError("diagnostic prevalidated shard templates are invalid")
    records = tuple(aggregate.shards)
    cached_bundles = tuple(bundles)
    if (
        not records
        or len(cached_bundles) != len(records)
        or any(not isinstance(bundle, MailEvidenceBundle) for bundle in cached_bundles)
    ):
        raise ContractValidationError("diagnostic prevalidated shard templates are invalid")
    if (
        aggregate.workspace_id != profile.workspace_id
        or aggregate.owner_user_id != profile.owner_user_id
        or aggregate.semantic_profile_fingerprint != profile.profile_fingerprint
    ):
        raise ContractValidationError("diagnostic prevalidated shard templates are invalid")

    templates: list[PrevalidatedSemanticShardTemplate] = []
    for ordinal, (record, bundle) in enumerate(zip(records, cached_bundles, strict=True)):
        if record.ordinal != ordinal or not _shard_bundle_matches_existing_export_verification(
            bundle=bundle,
            record=record,
            aggregate=aggregate,
            profile=profile,
        ):
            raise ContractValidationError("diagnostic prevalidated shard templates are invalid")
        scopes = _resolved_semantic_scopes(bundles=(bundle,), profile=profile)
        baseline = _baseline_semantic_scope(scopes)
        if baseline is None or not admissible_scope_complete(
            _combined_admissibility(scopes, profile=profile)
        ):
            raise ContractValidationError("diagnostic prevalidated shard templates are invalid")
        templates.append(
            _prepare_prevalidated_semantic_shard_template(
                aggregate=aggregate,
                profile=profile,
                scope_authority_verifier=scope_authority_verifier,
                shard_record=record,
                baseline_scope=baseline,
            )
        )
    return tuple(templates)


def _prepare_prevalidated_semantic_shard_template(
    *,
    aggregate: DiagnosticStructuralAggregateManifest,
    profile: DiagnosticSemanticProfile,
    scope_authority_verifier: CoverageScopeAuthorityVerifier,
    shard_record: DiagnosticStructuralShardRecord,
    baseline_scope: _ResolvedSemanticScope,
) -> PrevalidatedSemanticShardTemplate:
    """Freeze identifier-only derivation inputs after the Phase-1 proof."""

    structural_relevant_item_ids = tuple(sorted(baseline_scope.authorized_inventory_item_ids))
    authorized_item_ids = tuple(
        sorted(
            decision.inventory_item_id
            for decision in baseline_scope.scope_authority.authorization_decisions
            if decision.decision_state == "authorized"
        )
    )
    authorized_item_id_set = frozenset(authorized_item_ids)
    if not structural_relevant_item_ids or not set(structural_relevant_item_ids).issubset(
        authorized_item_id_set
    ):
        raise ContractValidationError("diagnostic prevalidated shard templates are invalid")

    item_by_id = {
        item.source_inventory_item_id: item
        for item in baseline_scope.source_inventory.items
        if item.source_inventory_item_id in authorized_item_id_set
    }
    if set(item_by_id) != authorized_item_id_set:
        raise ContractValidationError("diagnostic prevalidated shard templates are invalid")

    observation_ids_by_item = {item_id: [] for item_id in structural_relevant_item_ids}
    for observation in baseline_scope.structural_observations:
        bucket = observation_ids_by_item.get(observation.source_inventory_item_id)
        if bucket is None:
            raise ContractValidationError("diagnostic prevalidated shard templates are invalid")
        bucket.append(observation.source_observation_id)
    observations_by_item = MappingProxyType(
        {
            item_id: tuple(sorted(observation_ids_by_item[item_id]))
            for item_id in structural_relevant_item_ids
        }
    )
    observed_ids = {
        observation_id
        for observation_ids in observations_by_item.values()
        for observation_id in observation_ids
    }
    if observed_ids != set(baseline_scope.coverage_ledger.searched_structural_observation_ids):
        raise ContractValidationError("diagnostic prevalidated shard templates are invalid")

    baseline_partition = baseline_scope.coverage_ledger.scope_partition
    if baseline_partition is None:
        raise ContractValidationError("diagnostic prevalidated shard templates are invalid")
    ordinary_observations_by_item = MappingProxyType(
        {
            partition.inventory_item_id: tuple(partition.ordinary_observation_ids)
            for partition in baseline_partition.observation_partitions
        }
    )
    if set(ordinary_observations_by_item) != set(structural_relevant_item_ids):
        raise ContractValidationError("diagnostic prevalidated shard templates are invalid")

    (
        schema_candidate_observation_ordinals,
        schema_unindexed_observation_ordinals,
    ) = _prevalidated_schema_candidate_index(baseline_scope.structural_observations)
    thin_topology_compatibility = _thin_topology_compatibility_is_admissible(
        structural_observations=baseline_scope.structural_observations,
        schema_candidate_observation_ordinals=schema_candidate_observation_ordinals,
        schema_unindexed_observation_ordinals=schema_unindexed_observation_ordinals,
    )
    template = PrevalidatedSemanticShardTemplate(
        aggregate=aggregate,
        profile=profile,
        scope_authority_verifier=scope_authority_verifier,
        shard_record=shard_record,
        bundle=baseline_scope.bundle,
        baseline_scope=baseline_scope,
        structural_relevant_item_ids=structural_relevant_item_ids,
        authorized_item_ids=authorized_item_ids,
        authorized_item_id_set=authorized_item_id_set,
        item_by_id=MappingProxyType(item_by_id),
        observations_by_item=observations_by_item,
        ordinary_observations_by_item=ordinary_observations_by_item,
        schema_candidate_observation_ordinals=schema_candidate_observation_ordinals,
        schema_unindexed_observation_ordinals=schema_unindexed_observation_ordinals,
        topology_attestation=None,
        thin_topology_compatibility=thin_topology_compatibility,
        prevalidated_execution_scopes=MappingProxyType({}),
    )
    if not thin_topology_compatibility:
        # The topology proof binds this exact template object before any
        # supported query-pair capability is issued.
        object.__setattr__(
            template,
            "topology_attestation",
            TaskAnsweringEngine._prepare_prevalidated_diagnostic_topology_attestation(
                identity_binding=template,
                structural_observations=baseline_scope.structural_observations,
            ),
        )
    object.__setattr__(
        template,
        "prevalidated_execution_scopes",
        _prevalidated_execution_scopes(template),
    )
    if not _prevalidated_template_has_complete_startup_proof(template):
        raise ContractValidationError("diagnostic prevalidated shard templates are invalid")
    _PREVALIDATED_TEMPLATE_ISSUANCES[id(template)] = template
    return template


def _thin_topology_compatibility_is_admissible(
    *,
    structural_observations: tuple[StructuralObservation, ...],
    schema_candidate_observation_ordinals: Mapping[tuple[str, str], tuple[int, ...]],
    schema_unindexed_observation_ordinals: tuple[int, ...],
) -> bool:
    """Allow one candidate-only route for a compact export contract mismatch.

    The compatibility boundary is deliberately narrower than generic
    malformed-evidence handling: every observation must be schema-unindexed,
    no exact schema pair may be claimed, and the only observed topology
    failure class must be the typed diagnostic thin-export mismatch recognized
    by ``TaskAnsweringEngine``.  Canonical capabilities are never issued for
    this mode.
    """

    if (
        not isinstance(structural_observations, tuple)
        or not structural_observations
        or not isinstance(schema_candidate_observation_ordinals, Mapping)
        or not isinstance(schema_unindexed_observation_ordinals, tuple)
        or schema_candidate_observation_ordinals
        or schema_unindexed_observation_ordinals
        != tuple(range(len(structural_observations)))
    ):
        return False
    return TaskAnsweringEngine._diagnostic_thin_topology_compatibility_is_admissible(
        structural_observations=structural_observations
    )


def _template_has_runtime_topology_proof(
    template: PrevalidatedSemanticShardTemplate,
) -> bool:
    """Check the startup-selected topology mode without replaying validation."""

    if not isinstance(template, PrevalidatedSemanticShardTemplate):
        return False
    if template.thin_topology_compatibility:
        return (
            template.topology_attestation is None
            and not template.schema_candidate_observation_ordinals
            and template.schema_unindexed_observation_ordinals
            == tuple(range(len(template.baseline_scope.structural_observations)))
        )
    return TaskAnsweringEngine._prevalidated_diagnostic_topology_attestation_is_valid(
        template.topology_attestation,
        identity_binding=template,
        structural_observations=template.baseline_scope.structural_observations,
    )


def _prevalidated_schema_candidate_index(
    observations: Sequence[StructuralObservation],
) -> tuple[
    Mapping[tuple[str, str], tuple[int, ...]],
    tuple[int, ...],
]:
    """Index only exact schema metadata while retaining conservative fallbacks."""

    if isinstance(observations, (str, bytes)):
        raise ContractValidationError("diagnostic prevalidated shard templates are invalid")
    by_schema: dict[tuple[str, str], list[int]] = {}
    unindexed: list[int] = []
    for ordinal, observation in enumerate(observations):
        if not isinstance(observation, StructuralObservation):
            raise ContractValidationError("diagnostic prevalidated shard templates are invalid")
        structure_kind = _normalized_semantic_text(observation.structure_kind)
        if not structure_kind:
            unindexed.append(ordinal)
            continue
        header_counts: dict[str, int] = {}
        for column in observation.columns:
            column_headers: set[str] = set()
            for header in (column.original_header, column.normalized_header):
                normalized_header = _normalized_semantic_text(header)
                if normalized_header:
                    column_headers.add(normalized_header)
            for header in column_headers:
                header_counts[header] = header_counts.get(header, 0) + 1
        # A table without a full, explicit header schema is a conservative
        # fallback candidate.  It must never be pruned by a diagnostic index.
        if not header_counts:
            unindexed.append(ordinal)
            continue
        # A repeated header makes the *observation* a fallback candidate, but
        # must not erase its independently unique object/predicate pairs.
        # Retaining those exact pairs avoids treating a supported request as
        # globally unavailable merely because another column is ambiguous.
        # The whole observation remains in ``unindexed`` and is therefore
        # still included for every retained pair.
        if any(count != 1 for count in header_counts.values()):
            unindexed.append(ordinal)
        for header, count in header_counts.items():
            if count != 1:
                continue
            by_schema.setdefault((structure_kind, header), []).append(ordinal)
    return (
        MappingProxyType(
            {
                key: tuple(values)
                for key, values in sorted(by_schema.items())
                if values == sorted(set(values))
            }
        ),
        tuple(unindexed),
    )


def _prevalidated_pair_is_provably_unsupported(
    *,
    template: PrevalidatedSemanticShardTemplate,
    object_type: str,
    predicate: str,
) -> bool:
    """Return true only when verified schema metadata excludes one pair.

    A missing exact schema key is safe to omit from the optimized cached path:
    request execution then returns ``insufficient`` without executing rows,
    never a definitive no-match. Unindexed observations remain attached to
    every retained supported pair as conservative fallback candidates. Invalid
    index metadata is an invariant failure, not an unsupported-pair signal.
    """

    if (
        not isinstance(template, PrevalidatedSemanticShardTemplate)
        or not isinstance(object_type, str)
        or not object_type
        or not isinstance(predicate, str)
        or not predicate
        or not _template_has_runtime_topology_proof(template)
    ):
        raise ContractValidationError("diagnostic prevalidated schema support is invalid")
    observations = template.baseline_scope.structural_observations
    index = template.schema_candidate_observation_ordinals
    unindexed = template.schema_unindexed_observation_ordinals
    if not isinstance(index, Mapping) or not isinstance(unindexed, tuple):
        raise ContractValidationError("diagnostic prevalidated schema support is invalid")

    observation_count = len(observations)
    for ordinal in unindexed:
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or not 0 <= ordinal < observation_count
        ):
            raise ContractValidationError("diagnostic prevalidated schema support is invalid")
    candidates = index.get((object_type, predicate))
    if candidates is None:
        return True
    if (
        not isinstance(candidates, tuple)
        or not candidates
        or candidates != tuple(sorted(set(candidates)))
        or any(
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or not 0 <= ordinal < observation_count
            for ordinal in candidates
        )
    ):
        raise ContractValidationError("diagnostic prevalidated schema support is invalid")
    return False


def _validate_prevalidated_schema_index(template: PrevalidatedSemanticShardTemplate) -> None:
    """Require the startup schema index to exactly bind attested observations."""

    if (
        not isinstance(template, PrevalidatedSemanticShardTemplate)
        or not _template_has_runtime_topology_proof(template)
    ):
        raise ContractValidationError("diagnostic prevalidated schema index is invalid")
    expected_index, expected_unindexed = _prevalidated_schema_candidate_index(
        template.baseline_scope.structural_observations
    )
    if (
        template.schema_candidate_observation_ordinals != expected_index
        or template.schema_unindexed_observation_ordinals != expected_unindexed
    ):
        raise ContractValidationError("diagnostic prevalidated schema index is invalid")


def _prevalidated_execution_scopes(
    template: PrevalidatedSemanticShardTemplate,
) -> Mapping[tuple[str, str], _PrevalidatedDiagnosticExecutionScope]:
    """Prebuild capabilities for supported schema pairs only."""

    if (
        not isinstance(template, PrevalidatedSemanticShardTemplate)
        or template.prevalidated_execution_scopes
        or not template.profile.schema_alias_map.object_aliases
        or not template.profile.schema_alias_map.predicate_aliases
        or not _template_has_runtime_topology_proof(template)
    ):
        raise ContractValidationError("diagnostic prevalidated execution scopes are invalid")
    _validate_prevalidated_schema_index(template)
    if template.thin_topology_compatibility:
        return MappingProxyType({})
    scopes: dict[tuple[str, str], _PrevalidatedDiagnosticExecutionScope] = {}
    for object_type in sorted(template.profile.schema_alias_map.object_aliases):
        for predicate in sorted(template.profile.schema_alias_map.predicate_aliases):
            if not isinstance(object_type, str) or not object_type:
                raise ContractValidationError(
                    "diagnostic prevalidated execution scopes are invalid"
                )
            if not isinstance(predicate, str) or not predicate:
                raise ContractValidationError(
                    "diagnostic prevalidated execution scopes are invalid"
                )
            if _prevalidated_pair_is_provably_unsupported(
                template=template,
                object_type=object_type,
                predicate=predicate,
            ):
                continue
            query_scope = _derive_runtime_query_scope(
                baseline_scope=template.baseline_scope,
                plan=SimpleNamespace(
                    object_type=object_type,
                    predicate=predicate,
                    page_size=1,
                ),
                authority_verifier=template.scope_authority_verifier,
                prevalidated_template=template,
            )
            capability = TaskAnsweringEngine._prepare_prevalidated_diagnostic_structured_capability(
                identity_bindings=(
                    template.aggregate,
                    template.profile,
                    template.scope_authority_verifier,
                    template.shard_record,
                    template,
                ),
                topology_attestation=template.topology_attestation,
                coverage_ledger=query_scope.coverage_ledger,
                claim_requirement=query_scope.claim_requirement,
                source_inventory=query_scope.source_inventory,
                version_manifest=query_scope.version_manifest,
                scope_authority=query_scope.scope_authority,
                authorization_binding=query_scope.authorization_binding,
                structural_observations=query_scope.structural_observations,
            )
            key = object_type, predicate
            if (
                key in scopes
                or not TaskAnsweringEngine._prevalidated_diagnostic_capability_is_valid(
                    capability,
                    identity_bindings=(
                        template.aggregate,
                        template.profile,
                        template.scope_authority_verifier,
                        template.shard_record,
                        template,
                    ),
                    topology_attestation=template.topology_attestation,
                    structural_observations=query_scope.structural_observations,
                    coverage_ledger=query_scope.coverage_ledger,
                    claim_requirement=query_scope.claim_requirement,
                    source_inventory=query_scope.source_inventory,
                    version_manifest=query_scope.version_manifest,
                    scope_authority=query_scope.scope_authority,
                    authorization_binding=query_scope.authorization_binding,
                )
            ):
                raise ContractValidationError(
                    "diagnostic prevalidated execution scopes are invalid"
                )
            scopes[key] = _PrevalidatedDiagnosticExecutionScope(
                template=template,
                object_type=object_type,
                predicate=predicate,
                query_scope=query_scope,
                task_capability=capability,
            )
    return MappingProxyType(scopes)


def _prevalidated_templates_are_runtime_bound(
    *,
    templates: tuple[PrevalidatedSemanticShardTemplate, ...],
    profile: DiagnosticSemanticProfile,
    scope_authority_verifier: CoverageScopeAuthorityVerifier,
) -> bool:
    """Require exact startup-issued templates before alias grounding."""

    aggregate = templates[0].aggregate if templates else None
    if (
        not templates
        or not isinstance(aggregate, DiagnosticStructuralAggregateManifest)
        or len(templates) != len(aggregate.shards)
        or aggregate.workspace_id != profile.workspace_id
        or aggregate.owner_user_id != profile.owner_user_id
        or aggregate.semantic_profile_fingerprint != profile.profile_fingerprint
    ):
        return False
    for ordinal, (record, template) in enumerate(zip(aggregate.shards, templates, strict=True)):
        if (
            not isinstance(template, PrevalidatedSemanticShardTemplate)
            or record.ordinal != ordinal
            or template.aggregate is not aggregate
            or template.profile is not profile
            or template.scope_authority_verifier is not scope_authority_verifier
            or template.shard_record is not record
            or template.baseline_scope.bundle is not template.bundle
            or template.bundle.mail_evidence_bundle_id != record.mail_evidence_bundle_id
            or len(template.bundle.structural_observations) != record.structural_observation_count
            or not isinstance(template.schema_candidate_observation_ordinals, Mapping)
            or not isinstance(template.schema_unindexed_observation_ordinals, tuple)
            or not isinstance(template.thin_topology_compatibility, bool)
            or not isinstance(template.prevalidated_execution_scopes, Mapping)
            or not _template_has_runtime_topology_proof(template)
            or _PREVALIDATED_TEMPLATE_ISSUANCES.get(id(template)) is not template
        ):
            return False
    return True


def _prevalidated_template_has_complete_startup_proof(
    template: PrevalidatedSemanticShardTemplate,
) -> bool:
    """Verify every supported pair before template issuance."""

    if (
        not isinstance(template, PrevalidatedSemanticShardTemplate)
        or not admissible_scope_complete(template.baseline_scope.admissibility)
        or not isinstance(template.prevalidated_execution_scopes, Mapping)
        or not template.profile.schema_alias_map.object_aliases
        or not template.profile.schema_alias_map.predicate_aliases
        or not _template_has_runtime_topology_proof(template)
    ):
        return False
    if template.thin_topology_compatibility:
        return not template.prevalidated_execution_scopes
    expected_execution_keys: set[tuple[str, str]] = set()
    for object_type in template.profile.schema_alias_map.object_aliases:
        for predicate in template.profile.schema_alias_map.predicate_aliases:
            if _prevalidated_pair_is_provably_unsupported(
                template=template,
                object_type=object_type,
                predicate=predicate,
            ):
                continue
            expected_execution_keys.add((object_type, predicate))
    if set(template.prevalidated_execution_scopes) != expected_execution_keys:
        return False
    for key, execution_scope in template.prevalidated_execution_scopes.items():
        if (
            not isinstance(execution_scope, _PrevalidatedDiagnosticExecutionScope)
            or execution_scope.template is not template
            or key != (execution_scope.object_type, execution_scope.predicate)
            or execution_scope.query_scope.bundle is not template.bundle
            or execution_scope.query_scope.structural_observations
            is not template.baseline_scope.structural_observations
            or execution_scope.query_scope.authorized_inventory_item_ids
            is not template.structural_relevant_item_ids
            or not TaskAnsweringEngine._prevalidated_diagnostic_capability_is_valid(
                execution_scope.task_capability,
                identity_bindings=(
                    template.aggregate,
                    template.profile,
                    template.scope_authority_verifier,
                    template.shard_record,
                    template,
                ),
                topology_attestation=template.topology_attestation,
                structural_observations=execution_scope.query_scope.structural_observations,
                coverage_ledger=execution_scope.query_scope.coverage_ledger,
                claim_requirement=execution_scope.query_scope.claim_requirement,
                source_inventory=execution_scope.query_scope.source_inventory,
                version_manifest=execution_scope.query_scope.version_manifest,
                scope_authority=execution_scope.query_scope.scope_authority,
                authorization_binding=execution_scope.query_scope.authorization_binding,
            )
        ):
            return False
    return True


def _select_prevalidated_schema_candidates(
    template: PrevalidatedSemanticShardTemplate,
    *,
    plan: Any,
) -> tuple[StructuralObservation, ...]:
    """Return an ordered, conservative schema-compatible observation subset.

    Only observations with complete index metadata are pruned.  A missing or
    ambiguous structure/header leaves the observation in the fallback set, so
    the diagnostic execution cannot turn uncertainty into a definitive
    no-match.  This helper reads no evidence values.
    """

    if not isinstance(template, PrevalidatedSemanticShardTemplate):
        raise ContractValidationError("diagnostic prevalidated schema index is invalid")
    observations = template.baseline_scope.structural_observations
    index = template.schema_candidate_observation_ordinals
    unindexed = template.schema_unindexed_observation_ordinals
    if (
        not isinstance(index, Mapping)
        or not isinstance(unindexed, tuple)
        or not isinstance(observations, tuple)
    ):
        raise ContractValidationError("diagnostic prevalidated schema index is invalid")
    try:
        object_forms = {
            _normalized_semantic_text(value) for value in tuple(plan.object_type_match_forms)
        }
        predicate_forms = {
            _normalized_semantic_text(value) for value in tuple(plan.predicate_match_forms)
        }
        projection_forms = {
            _normalized_semantic_text(value) for value in tuple(plan.projection_match_forms)
        }
    except (AttributeError, TypeError, ValueError):
        return observations
    if (
        not object_forms
        or not predicate_forms
        or not projection_forms
        or "" in (object_forms | predicate_forms | projection_forms)
    ):
        return observations

    observation_count = len(observations)

    def _valid_ordinals(values: object) -> tuple[int, ...]:
        if not isinstance(values, tuple) or any(
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or not 0 <= ordinal < observation_count
            for ordinal in values
        ):
            raise ContractValidationError("diagnostic prevalidated schema index is invalid")
        if values != tuple(sorted(set(values))):
            raise ContractValidationError("diagnostic prevalidated schema index is invalid")
        return values

    selected_ordinals = set(_valid_ordinals(unindexed))
    predicate_ordinals: set[int] = set()
    for key, values in index.items():
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or any(not isinstance(value, str) or not value for value in key)
        ):
            raise ContractValidationError("diagnostic prevalidated schema index is invalid")
        structure_kind, header = key
        ordinals = _valid_ordinals(values)
        if structure_kind not in object_forms:
            continue
        if header in predicate_forms:
            predicate_ordinals.update(ordinals)
    # A predicate-compatible row can still produce a match fact when its
    # requested display projection is unavailable. The generic path then
    # returns the governed projection-unavailable result; pruning it here
    # would incorrectly convert that state into a definitive no-match.
    selected_ordinals.update(predicate_ordinals)
    return tuple(
        observation
        for ordinal, observation in enumerate(observations)
        if ordinal in selected_ordinals
    )


def _execute_prevalidated_sharded_semantic_request(
    *,
    request: _SemanticMcpRequest,
    profile: DiagnosticSemanticProfile,
    shard_store: FileDiagnosticStructuralShardStore,
    scope_authority_verifier: CoverageScopeAuthorityVerifier | None,
    templates: tuple[PrevalidatedSemanticShardTemplate, ...],
) -> Mapping[str, Any]:
    """Execute one query from startup-proven scopes without a second Phase 1."""

    if not isinstance(scope_authority_verifier, CoverageScopeAuthorityVerifier):
        return _semantic_insufficient_payload(request)
    aggregate = templates[0].aggregate if templates else None
    if isinstance(aggregate, DiagnosticStructuralAggregateManifest) and (
        aggregate.workspace_id != profile.workspace_id
        or aggregate.owner_user_id != profile.owner_user_id
    ):
        return _semantic_permission_denied_payload(request)
    if not _prevalidated_templates_are_runtime_bound(
        templates=templates,
        profile=profile,
        scope_authority_verifier=scope_authority_verifier,
    ):
        return _semantic_insufficient_payload(request)

    admissible_scope = _combined_admissibility(
        tuple(template.baseline_scope for template in templates),
        profile=profile,
    )
    if not admissible_scope_complete(admissible_scope):
        return _semantic_insufficient_payload(request)
    try:
        plan = PermissionFirstSemanticPlanner().ground_all_matching(
            skeleton=SemanticTaskSkeleton(
                query_class=request.query_class,
                projection_slots=("projection",),
                constraint_slots=("object_type", "predicate", "value"),
            ),
            scope=admissible_scope,
            aliases=profile.schema_alias_map,
            object_type=request.object_type_mention,
            predicate=request.predicate_mention,
            value=request.value_mention,
            projection=request.projection_mention,
            operator=request.operator,
            page_size=request.page_size,
            page_number=request.page_number,
        )
    except SemanticPlanClarificationRequired:
        return _semantic_clarification_payload(request)

    unique_projections: set[tuple[str, ...]] = set()
    projection_state = "complete"
    serialized_bytes = 2
    found_in_any_complete_shard = False
    thin_topology_candidate_only = False
    matched_in_any_shard = False
    try:
        for template in templates:
            execution_scope = template.prevalidated_execution_scopes.get(
                (plan.object_type, plan.predicate)
            )
            if isinstance(execution_scope, _PrevalidatedDiagnosticExecutionScope):
                if (
                    execution_scope.template is not template
                    or execution_scope.object_type != plan.object_type
                    or execution_scope.predicate != plan.predicate
                    or not TaskAnsweringEngine._prevalidated_diagnostic_capability_is_valid(
                        execution_scope.task_capability,
                        identity_bindings=(
                            template.aggregate,
                            template.profile,
                            template.scope_authority_verifier,
                            template.shard_record,
                            template,
                        ),
                        topology_attestation=template.topology_attestation,
                        structural_observations=execution_scope.query_scope.structural_observations,
                        coverage_ledger=execution_scope.query_scope.coverage_ledger,
                        claim_requirement=execution_scope.query_scope.claim_requirement,
                        source_inventory=execution_scope.query_scope.source_inventory,
                        version_manifest=execution_scope.query_scope.version_manifest,
                        scope_authority=execution_scope.query_scope.scope_authority,
                        authorization_binding=execution_scope.query_scope.authorization_binding,
                    )
                ):
                    return _semantic_insufficient_payload(request)
                selected_observations = _select_prevalidated_schema_candidates(
                    template,
                    plan=plan,
                )
                execution = execute_authorized_structured_set(
                    plan=plan,
                    structural_observations=selected_observations,
                    authorized_inventory_item_ids=(
                        execution_scope.query_scope.authorized_inventory_item_ids
                    ),
                    coverage_ledger=execution_scope.query_scope.coverage_ledger,
                )
                matches = execution.matches
                outcome = TaskAnsweringEngine._answer_prevalidated_diagnostic_structured_claim(
                    capability=execution_scope.task_capability,
                    matched_structural_facts=execution.matched_structural_facts,
                    structural_observations=selected_observations,
                )
                if (
                    outcome.status != "ok"
                    or outcome.claim is None
                    or outcome.claim.state not in {"FOUND", "NOT_FOUND_WITHIN_COMPLETE_SCOPE"}
                ):
                    return _semantic_insufficient_payload(request)
                found_in_any_complete_shard = (
                    found_in_any_complete_shard or outcome.claim.state == "FOUND"
                )
            elif template.thin_topology_compatibility and _template_has_runtime_topology_proof(
                template
            ):
                # The compact/thin export has already passed the
                # permission/source/version/coverage binding gates, but its
                # cell topology is not admissible for a canonical AnswerClaim.
                # This branch runs the authorized exact row executor only and
                # publishes no no-match or canonical truth claim.
                execution = execute_authorized_structured_set(
                    plan=plan,
                    structural_observations=template.baseline_scope.structural_observations,
                    authorized_inventory_item_ids=template.structural_relevant_item_ids,
                    coverage_ledger=template.baseline_scope.coverage_ledger,
                )
                matches = execution.matches
                thin_topology_candidate_only = True
            else:
                return _semantic_insufficient_payload(request)
            matched_in_any_shard = matched_in_any_shard or bool(matches)
            for match in matches:
                projection = getattr(match, "projection_values", None)
                if (
                    not isinstance(projection, tuple)
                    or not projection
                    or any(not isinstance(value, str) or not value.strip() for value in projection)
                ):
                    projection_state = "projection_unavailable"
                    continue
                if projection in unique_projections:
                    continue
                projected_bytes = len(
                    json.dumps(
                        {"values": list(projection)},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                if (
                    len(unique_projections) >= SEMANTIC_COMPLETE_SET_MAX_ITEMS
                    or serialized_bytes + projected_bytes + (1 if unique_projections else 0)
                    > SEMANTIC_COMPLETE_SET_MAX_SERIALIZED_BYTES
                ):
                    projection_state = "result_budget_exceeded"
                    continue
                unique_projections.add(projection)
                serialized_bytes += projected_bytes + (1 if len(unique_projections) > 1 else 0)
    except (ContractValidationError, OSError, TypeError, ValueError):
        return _semantic_insufficient_payload(request)

    if thin_topology_candidate_only and not matched_in_any_shard:
        return _semantic_insufficient_payload(request)

    ordered_projections = tuple(
        sorted(
            unique_projections,
            key=lambda values: (
                tuple(_normalized_semantic_text(value) for value in values),
                values,
            ),
        )
    )
    if projection_state == "complete":
        complete_projection = {
            "state": "complete",
            "values": [{"values": list(projection)} for projection in ordered_projections],
            "safe_result_budget": _semantic_complete_result_budget(),
        }
    elif projection_state == "projection_unavailable":
        complete_projection = _semantic_complete_projection_unavailable_projection()
    else:
        complete_projection = _semantic_complete_projection_budget_exceeded()
    page_start = (request.page_number - 1) * request.page_size
    displayed_count = len(ordered_projections[page_start : page_start + request.page_size])
    return {
        "status": "ok" if projection_state == "complete" else "insufficient",
        "retrieval_path": SEMANTIC_RETRIEVAL_PATH,
        "retrieval_layer": (
            SEMANTIC_THIN_TOPOLOGY_COMPATIBILITY_LAYER
            if thin_topology_candidate_only
            else SEMANTIC_RETRIEVAL_LAYER
        ),
        "execution_mode": "authorized_structured_set",
        "query_class": request.query_class,
        "cardinality": request.cardinality,
        "claim_state": (
            "CANDIDATE_MATCHES"
            if thin_topology_candidate_only
            else (
                "FOUND" if found_in_any_complete_shard else "NOT_FOUND_WITHIN_COMPLETE_SCOPE"
            )
        ),
        "complete_projection": complete_projection,
        "display_pagination": {
            "page_size": request.page_size,
            "page_number": request.page_number,
            "displayed_count": displayed_count,
            "has_more": len(ordered_projections) > page_start + displayed_count,
        },
        # Aggregate runtime intentionally emits no shard-derived citation or
        # storage handle. Evidence remains available only through a later
        # governed request when a user explicitly asks for it.
        "citation_handles": [],
        "canonical_kg": CANONICAL_KG,
    }


def _shard_bundle_matches_existing_export_verification(
    *,
    bundle: MailEvidenceBundle,
    record: DiagnosticStructuralShardRecord,
    aggregate: DiagnosticStructuralAggregateManifest,
    profile: DiagnosticSemanticProfile,
) -> bool:
    """Check aggregate/export authority without grounding aliases or rows."""

    if (
        not isinstance(bundle, MailEvidenceBundle)
        or not isinstance(record, DiagnosticStructuralShardRecord)
        or not isinstance(aggregate, DiagnosticStructuralAggregateManifest)
        or not isinstance(profile, DiagnosticSemanticProfile)
    ):
        return False
    verification = aggregate.existing_export_verification
    if (
        record.existing_export_verification_fingerprint != verification.verification_fingerprint
        or len(bundle.message_occurrences) != record.selected_message_count
        or len(bundle.body_segments) != record.body_segment_count
        or len(bundle.structural_observations) != record.structural_observation_count
        or len(bundle.source_inventory) != 1
        or len(bundle.claim_requirements) != 1
        or len(bundle.coverage_ledgers) != 1
        or len(bundle.version_manifests) != 1
    ):
        return False

    inventory = bundle.source_inventory[0]
    requirement = bundle.claim_requirements[0]
    ledger = bundle.coverage_ledgers[0]
    version_manifest = bundle.version_manifests[0]
    authority = (
        ledger.scope_partition.scope_authority if ledger.scope_partition is not None else None
    )
    session = bundle.mail_import_session
    if not isinstance(authority, CoverageScopeAuthority):
        return False
    expected_query_id = stable_resource_contract_id(
        "query",
        "DiagnosticCompactBaseline",
        {
            "source_inventory_id": inventory.source_inventory_id,
            "existing_export_verification_fingerprint": (verification.verification_fingerprint),
        },
    )
    try:
        expected_implementation_fingerprint = diagnostic_structural_implementation_fingerprint(
            producer_type=DIAGNOSTIC_STRUCTURAL_BRIDGE_PRODUCER_TYPE,
            parser_name=bundle.mail_parse_run.parser_name,
            parser_version=bundle.mail_parse_run.parser_version,
            semantic_profile_fingerprint=profile.profile_fingerprint,
            verification=verification,
        )
        expected_scope_policy_fingerprint = diagnostic_structural_scope_policy_fingerprint(
            verification
        )
    except ContractValidationError:
        return False
    return bool(
        session.source_asset_id == aggregate.source_asset_id
        and session.archive_sha256 == aggregate.source_fingerprint
        and session.workspace_id == aggregate.workspace_id
        and session.owner_user_id == aggregate.owner_user_id
        and session.status == "succeeded"
        and inventory.source_asset_id == aggregate.source_asset_id
        and inventory.source_fingerprint == aggregate.source_fingerprint
        and requirement.query_id == expected_query_id
        and requirement.kind == "all_matching"
        and requirement.target == "structural_row"
        and requirement.predicate == "structural_scope"
        and dict(requirement.parameters) == diagnostic_structural_baseline_parameters(verification)
        and ledger.claim_requirement_id == requirement.claim_requirement_id
        and ledger.source_inventory_id == inventory.source_inventory_id
        and authority.claim_requirement_id == requirement.claim_requirement_id
        and authority.source_inventory_id == inventory.source_inventory_id
        and authority.scope_policy.scope_policy_id == DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID
        and authority.scope_policy.scope_policy_version
        == DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_VERSION
        and authority.scope_policy.scope_policy_fingerprint == expected_scope_policy_fingerprint
        and version_manifest.implementation_version
        == DIAGNOSTIC_STRUCTURAL_BRIDGE_IMPLEMENTATION_VERSION
        and version_manifest.implementation_fingerprint == expected_implementation_fingerprint
    )


def _semantic_evidence_time_admissible(
    *,
    profile: DiagnosticSemanticProfile,
    bundle: MailEvidenceBundle,
    version_manifests: Sequence[VersionManifest],
    structural_observations: Sequence[StructuralObservation],
) -> bool:
    """Require an authorized temporal scope without conflating time roles.

    ``DiagnosticSemanticProfile.known_as_of`` is a source-world cutoff, while
    the import, parse, bundle, and manifest timestamps establish the authority
    of the frozen captured evidence.  A capture made after the source-world
    cutoff therefore does not redefine that cutoff.  A structural observation's
    optional ``observed_at`` is source-world time: unknown source time is
    admissible only through the already-validated frozen authority, but a
    supplied value must be a valid instant no later than both the source-world
    cutoff and completed parse.
    """

    if (
        not isinstance(profile, DiagnosticSemanticProfile)
        or not isinstance(bundle, MailEvidenceBundle)
        or not version_manifests
        or any(not isinstance(manifest, VersionManifest) for manifest in version_manifests)
        or any(
            not isinstance(observation, StructuralObservation)
            for observation in structural_observations
        )
    ):
        return False
    known_as_of = _parse_iso_instant(profile.known_as_of)
    evidence_known_values = (
        bundle.mail_import_session.created_at,
        bundle.mail_parse_run.started_at,
        bundle.mail_parse_run.completed_at,
        bundle.created_at,
        *(manifest.created_at for manifest in version_manifests),
    )
    evidence_known_instants = tuple(_parse_iso_instant(value) for value in evidence_known_values)
    if known_as_of is None or any(value is None for value in evidence_known_instants):
        return False
    parse_started_at = evidence_known_instants[1]
    parse_completed_at = evidence_known_instants[2]
    if (
        parse_started_at is None
        or parse_completed_at is None
        or parse_started_at > parse_completed_at
    ):
        return False
    for observation in structural_observations:
        if observation.observed_at is None:
            continue
        observed_at = _parse_iso_instant(observation.observed_at)
        if observed_at is None or observed_at > known_as_of or observed_at > parse_completed_at:
            return False
    return True


def validate_diagnostic_semantic_profile_binding(
    *,
    profile: DiagnosticSemanticProfile,
    bundles: Sequence[MailEvidenceBundle],
    scope_authority_verifier: CoverageScopeAuthorityVerifier | None = None,
) -> None:
    """Fail closed unless one private profile matches trusted bundle scope facts.

    This startup gate intentionally has no public return value. A profile is
    server-owned deployment input, while a bundle's workspace, owner,
    authorization bindings, timestamps, and trusted coverage authorities are
    persisted evidence facts. Validating the relationship before accepting
    requests prevents a correctly fingerprinted profile from being applied to
    the wrong private structural scope.
    """

    if not isinstance(profile, DiagnosticSemanticProfile):
        raise ValueError("diagnostic semantic profile is invalid")
    if not bundles or any(not isinstance(bundle, MailEvidenceBundle) for bundle in bundles):
        raise ValueError("diagnostic semantic profile bundle binding is invalid")
    for bundle in bundles:
        session = bundle.mail_import_session
        if (
            session.workspace_id != profile.workspace_id
            or session.owner_user_id != profile.owner_user_id
        ):
            raise ValueError("diagnostic semantic profile bundle binding is invalid")
        authorization_bindings = _bundle_authorization_bindings(bundle)
        if not authorization_bindings or any(
            binding.actor_context_id != profile.actor_context_id
            for binding in authorization_bindings
        ):
            raise ValueError("diagnostic semantic profile bundle binding is invalid")
        if not _semantic_evidence_time_admissible(
            profile=profile,
            bundle=bundle,
            version_manifests=bundle.version_manifests,
            structural_observations=bundle.structural_observations,
        ):
            raise ValueError("diagnostic semantic profile bundle binding is invalid")

    scopes = _resolved_semantic_scopes(bundles=bundles, profile=profile)
    predicates_with_complete_scope = {
        _normalized_semantic_text(scope.claim_requirement.predicate) for scope in scopes
    }
    profile_predicates = set(profile.schema_alias_map.predicate_aliases)
    has_legacy_predicate_scopes = profile_predicates.issubset(
        predicates_with_complete_scope
    ) and len(scopes) == len(predicates_with_complete_scope)
    has_compact_baseline_scope = _baseline_semantic_scope(scopes) is not None and isinstance(
        scope_authority_verifier, CoverageScopeAuthorityVerifier
    )
    if not (has_legacy_predicate_scopes or has_compact_baseline_scope):
        raise ValueError("diagnostic semantic profile bundle binding is invalid")


def _bundle_authorization_bindings(
    bundle: MailEvidenceBundle,
) -> tuple[CoverageAuthorizationBinding, ...]:
    """Return every persisted authorization binding without inventing scope."""

    bindings: list[CoverageAuthorizationBinding] = []
    for ledger in bundle.coverage_ledgers:
        if ledger.authorization_binding is not None:
            bindings.append(ledger.authorization_binding)
        bindings.extend(ledger.authorization_bindings)
    return tuple(bindings)


def _baseline_semantic_scope(
    scopes: Sequence[_ResolvedSemanticScope],
) -> _ResolvedSemanticScope | None:
    """Find one complete predicate-neutral structural baseline, if supplied."""

    candidates = tuple(
        scope
        for scope in scopes
        if scope.claim_requirement.parameters.get("scope_kind")
        == DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND
    )
    return candidates[0] if len(candidates) == 1 else None


def _derive_runtime_query_scope(
    *,
    baseline_scope: _ResolvedSemanticScope,
    plan: Any,
    authority_verifier: CoverageScopeAuthorityVerifier | None,
    prevalidated_template: PrevalidatedSemanticShardTemplate | None = None,
) -> _ResolvedSemanticScope:
    """Build one ephemeral predicate scope after permission-first grounding.

    The bridge persists one complete predicate-neutral authority/ledger over
    the structural inventory. This function derives the predicate-specific
    claim and coverage accounting only for the current already-grounded plan,
    retaining ``TaskAnsweringEngine`` ownership of the final claim. Nothing
    derived here is persisted or exposed through MCP.
    """

    if not isinstance(authority_verifier, CoverageScopeAuthorityVerifier):
        raise ValueError("diagnostic scope authority verifier is unavailable")
    if not baseline_scope.scope_authority._is_trusted_for_authoritative_use:
        raise ValueError("diagnostic baseline scope authority is untrusted")

    inventory = baseline_scope.source_inventory
    if prevalidated_template is None:
        structural_relevant_item_ids = tuple(sorted(baseline_scope.authorized_inventory_item_ids))
        authorized_item_ids = tuple(
            sorted(
                decision.inventory_item_id
                for decision in baseline_scope.scope_authority.authorization_decisions
                if decision.decision_state == "authorized"
            )
        )
        authorized_item_id_set = frozenset(authorized_item_ids)
        if not set(structural_relevant_item_ids).issubset(authorized_item_id_set):
            raise ValueError("diagnostic baseline scope authorization is invalid")
        item_by_id = {
            item.source_inventory_item_id: item
            for item in inventory.items
            if item.source_inventory_item_id in authorized_item_id_set
        }
        if set(item_by_id) != authorized_item_id_set:
            raise ValueError("diagnostic baseline scope inventory is invalid")
        observations_by_item: Mapping[str, tuple[str, ...]] = {
            item_id: tuple(
                sorted(
                    observation.source_observation_id
                    for observation in baseline_scope.structural_observations
                    if observation.source_inventory_item_id == item_id
                )
            )
            for item_id in structural_relevant_item_ids
        }
        if set(observations_by_item) != set(structural_relevant_item_ids):
            raise ValueError("diagnostic baseline scope observations are invalid")
        baseline_partition = baseline_scope.coverage_ledger.scope_partition
        if baseline_partition is None:
            raise ValueError("diagnostic baseline scope partition is unavailable")
        ordinary_observations_by_item: Mapping[str, tuple[str, ...]] = {
            partition.inventory_item_id: tuple(partition.ordinary_observation_ids)
            for partition in baseline_partition.observation_partitions
        }
        if set(ordinary_observations_by_item) != set(structural_relevant_item_ids):
            raise ValueError("diagnostic baseline ordinary proof is incomplete")
    else:
        if (
            prevalidated_template.baseline_scope is not baseline_scope
            or prevalidated_template.scope_authority_verifier is not authority_verifier
        ):
            raise ValueError("diagnostic prevalidated shard template is invalid")
        structural_relevant_item_ids = prevalidated_template.structural_relevant_item_ids
        authorized_item_ids = prevalidated_template.authorized_item_ids
        authorized_item_id_set = prevalidated_template.authorized_item_id_set
        item_by_id = prevalidated_template.item_by_id
        observations_by_item = prevalidated_template.observations_by_item
        ordinary_observations_by_item = prevalidated_template.ordinary_observations_by_item
        if (
            not set(structural_relevant_item_ids).issubset(authorized_item_id_set)
            or set(item_by_id) != authorized_item_id_set
            or set(observations_by_item) != set(structural_relevant_item_ids)
            or set(ordinary_observations_by_item) != set(structural_relevant_item_ids)
        ):
            raise ValueError("diagnostic prevalidated shard template is invalid")

    requirement = ClaimRequirement.create(
        query_id=stable_resource_contract_id(
            "query",
            "DiagnosticRuntimeStructuredSet",
            {
                "source_inventory_id": inventory.source_inventory_id,
                "version_manifest_id": baseline_scope.version_manifest.version_manifest_id,
                "authorization_binding": baseline_scope.authorization_binding.to_dict(),
                "object_type": plan.object_type,
                "predicate": plan.predicate,
            },
        ),
        kind="all_matching",
        target="structural_row",
        predicate=plan.predicate,
        parameters={
            "scope_kind": _SEMANTIC_RUNTIME_SCOPE_KIND,
            "object_type": plan.object_type,
            "source_inventory_id": inventory.source_inventory_id,
        },
        required_scope=structural_relevant_item_ids,
        created_at=baseline_scope.version_manifest.created_at,
    )
    relevance_decisions = tuple(
        CoverageItemRelevanceDecision.create(
            source_inventory_item=item_by_id[item_id],
            claim_requirement=requirement,
            scope_policy=baseline_scope.scope_authority.scope_policy,
            decision_state=("relevant" if item_id in observations_by_item else "irrelevant"),
        )
        for item_id in authorized_item_ids
    )
    authority = CoverageScopeAuthority.create(
        source_inventory=inventory,
        claim_requirement=requirement,
        authorization_binding=baseline_scope.authorization_binding,
        version_manifest=baseline_scope.version_manifest,
        scope_policy=baseline_scope.scope_authority.scope_policy,
        authorization_decisions=baseline_scope.scope_authority.authorization_decisions,
        relevance_decisions=relevance_decisions,
        authority_verifier=authority_verifier,
    )
    partitions = tuple(
        CoverageObservationPartition(
            inventory_item_id=item_id,
            structural_observation_ids=observations_by_item[item_id],
            ordinary_observation_ids=ordinary_observations_by_item[item_id],
        )
        for item_id in structural_relevant_item_ids
    )
    scope_partition = CoverageScopePartition.create(
        scope_authority=authority,
        observation_partitions=partitions,
    )
    proof_records = tuple(
        CoverageProofRecord.create(
            source_inventory_id=inventory.source_inventory_id,
            claim_requirement_id=requirement.claim_requirement_id,
            version_manifest_id=baseline_scope.version_manifest.version_manifest_id,
            inventory_item_id=partition.inventory_item_id,
            proof_kind=(
                "combined"
                if partition.structural_observation_ids and partition.ordinary_observation_ids
                else "structural"
                if partition.structural_observation_ids
                else "ordinary"
            ),
            structural_observation_ids=partition.structural_observation_ids,
            ordinary_observation_ids=partition.ordinary_observation_ids,
        )
        for partition in partitions
    )
    coverage_ledger = CoverageLedger.create(
        query_id=requirement.query_id,
        claim_requirement_id=requirement.claim_requirement_id,
        source_inventory_id=inventory.source_inventory_id,
        relevant_inventory_item_ids=structural_relevant_item_ids,
        searched_structural_observation_ids=tuple(
            observation_id
            for partition in partitions
            for observation_id in partition.structural_observation_ids
        ),
        searched_ordinary_observation_ids=tuple(
            observation_id
            for partition in partitions
            for observation_id in partition.ordinary_observation_ids
        ),
        authorization_binding=baseline_scope.authorization_binding,
        version_binding=CoverageVersionBinding.from_manifest(baseline_scope.version_manifest),
        scope_partition=scope_partition,
        proof_records=proof_records,
        complete_authorized_scope=True,
        display_pagination=DisplayPagination(page_size=plan.page_size),
    )
    return _ResolvedSemanticScope(
        bundle=baseline_scope.bundle,
        coverage_ledger=coverage_ledger,
        claim_requirement=requirement,
        source_inventory=inventory,
        version_manifest=baseline_scope.version_manifest,
        scope_authority=authority,
        authorization_binding=baseline_scope.authorization_binding,
        structural_observations=baseline_scope.structural_observations,
        authorized_inventory_item_ids=structural_relevant_item_ids,
        admissibility=baseline_scope.admissibility,
    )


def _combined_admissibility(
    scopes: Sequence[_ResolvedSemanticScope],
    *,
    profile: DiagnosticSemanticProfile | None,
) -> AdmissibleSemanticScope:
    """Combine only fully server-owned scope facts before alias grounding."""

    if profile is None or not scopes:
        return AdmissibleSemanticScope(
            permission_admissible=False,
            source_admissible=False,
            version_admissible=False,
            context_admissible=False,
            time_admissible=False,
            status_admissible=False,
        )
    return AdmissibleSemanticScope(
        permission_admissible=all(scope.admissibility.permission_admissible for scope in scopes),
        source_admissible=all(scope.admissibility.source_admissible for scope in scopes),
        version_admissible=all(scope.admissibility.version_admissible for scope in scopes),
        context_admissible=all(scope.admissibility.context_admissible for scope in scopes),
        time_admissible=all(scope.admissibility.time_admissible for scope in scopes),
        status_admissible=all(scope.admissibility.status_admissible for scope in scopes),
    )


def admissible_scope_complete(scope: AdmissibleSemanticScope) -> bool:
    """Return the closed six-gate decision without exposing scope internals."""

    try:
        scope.require_complete()
    except SemanticPlanClarificationRequired:
        return False
    return True


def _resolved_semantic_scopes(
    *,
    bundles: Sequence[MailEvidenceBundle],
    profile: DiagnosticSemanticProfile | None,
) -> tuple[_ResolvedSemanticScope, ...]:
    """Return only a complete, server-authorized single-inventory scope.

    A future aggregate bundle must use its aggregate claim path explicitly.
    It is safer for this narrow UAT boundary to reject it than to splice
    independently complete inventories into an apparent complete set.
    """

    if profile is None:
        return ()
    scopes: list[_ResolvedSemanticScope] = []
    for bundle in bundles:
        for ledger in bundle.coverage_ledgers:
            scope = _resolved_semantic_scope_from_ledger(
                bundle=bundle,
                coverage_ledger=ledger,
                profile=profile,
            )
            if scope is not None:
                scopes.append(scope)
    return tuple(scopes)


def _resolved_semantic_scope_from_ledger(
    *,
    bundle: MailEvidenceBundle,
    coverage_ledger: CoverageLedger,
    profile: DiagnosticSemanticProfile,
) -> _ResolvedSemanticScope | None:
    """Bind one all-matching ledger to its existing canonical evidence facts."""

    if coverage_ledger.is_aggregate:
        return None
    requirement = next(
        (
            candidate
            for candidate in bundle.claim_requirements
            if candidate.claim_requirement_id == coverage_ledger.claim_requirement_id
            and candidate.kind == "all_matching"
        ),
        None,
    )
    inventory = next(
        (
            candidate
            for candidate in bundle.source_inventory
            if candidate.source_inventory_id == coverage_ledger.source_inventory_id
        ),
        None,
    )
    version_binding = coverage_ledger.version_binding
    manifest = next(
        (
            candidate
            for candidate in bundle.version_manifests
            if version_binding is not None
            and candidate.version_manifest_id == version_binding.version_manifest_id
        ),
        None,
    )
    authorization = coverage_ledger.authorization_binding
    authority = _trusted_scope_authority(
        bundle=bundle,
        coverage_ledger=coverage_ledger,
        claim_requirement=requirement,
        source_inventory=inventory,
    )
    if not all(
        isinstance(value, expected)
        for value, expected in (
            (requirement, ClaimRequirement),
            (inventory, SourceInventory),
            (manifest, VersionManifest),
            (authorization, CoverageAuthorizationBinding),
            (authority, CoverageScopeAuthority),
        )
    ):
        return None
    authorized_item_ids = tuple(authority.authorized_relevant_item_ids)
    structural_observations = tuple(
        observation
        for observation in bundle.structural_observations
        if observation.source_inventory_item_id in set(authorized_item_ids)
    )
    observed_ids = {observation.source_observation_id for observation in structural_observations}
    expected_ids = set(coverage_ledger.searched_structural_observation_ids)
    source_admissible = (
        set(authorized_item_ids) == set(coverage_ledger.relevant_inventory_item_ids)
        and observed_ids == expected_ids
        and all(
            observation.source_inventory_item_id in set(authorized_item_ids)
            for observation in structural_observations
        )
    )
    version_admissible = bool(
        manifest.index_freshness == "fresh"
        and manifest.source_fingerprint == inventory.source_fingerprint
        and manifest.parser_fingerprint == inventory.parser_fingerprint
        and all(
            observation.source_fingerprint == manifest.source_fingerprint
            and observation.parser_fingerprint == manifest.parser_fingerprint
            for observation in structural_observations
        )
    )
    try:
        authority_valid = (
            authority._is_trusted_for_authoritative_use
            and authority.validate_for_claim(
                inventory,
                requirement,
                manifest,
                authorization,
                authority.scope_policy,
            )
        )
        ledger_usable = coverage_ledger.usable_for_claim(
            inventory,
            requirement,
            manifest,
            authorization,
            authority,
        )
    except ContractValidationError:
        authority_valid = False
        ledger_usable = False
    permission_admissible = bool(
        authority_valid
        and authorization.actor_context_id == profile.actor_context_id
        and authority.authorization_binding == authorization
        and set(authority.authorized_relevant_item_ids) == set(authorized_item_ids)
    )
    context_admissible = (
        bundle.mail_import_session.workspace_id == profile.workspace_id
        and bundle.mail_import_session.owner_user_id == profile.owner_user_id
    )
    time_admissible = _semantic_evidence_time_admissible(
        profile=profile,
        bundle=bundle,
        version_manifests=(manifest,),
        structural_observations=structural_observations,
    )
    status_admissible = bool(
        bundle.mail_import_session.status == "succeeded"
        and coverage_ledger.complete_authorized_scope
        and coverage_ledger.fallback_usage.status in {"not_required", "completed"}
        and not (
            coverage_ledger.omitted_inventory_item_ids
            or coverage_ledger.failed_inventory_item_ids
            or coverage_ledger.unsupported_inventory_item_ids
            or coverage_ledger.redacted_inventory_item_ids
        )
        and all(
            item.processing_state == "parsed"
            for item in inventory.items
            if item.source_inventory_item_id in set(authorized_item_ids)
        )
        and ledger_usable
    )
    admissibility = AdmissibleSemanticScope(
        permission_admissible=permission_admissible,
        source_admissible=source_admissible,
        version_admissible=version_admissible,
        context_admissible=context_admissible,
        time_admissible=time_admissible,
        status_admissible=status_admissible,
    )
    if not admissible_scope_complete(admissibility):
        return None
    return _ResolvedSemanticScope(
        bundle=bundle,
        coverage_ledger=coverage_ledger,
        claim_requirement=requirement,
        source_inventory=inventory,
        version_manifest=manifest,
        scope_authority=authority,
        authorization_binding=authorization,
        structural_observations=structural_observations,
        authorized_inventory_item_ids=authorized_item_ids,
        admissibility=admissibility,
    )


def _trusted_scope_authority(
    *,
    bundle: MailEvidenceBundle,
    coverage_ledger: CoverageLedger,
    claim_requirement: ClaimRequirement | None,
    source_inventory: SourceInventory | None,
) -> CoverageScopeAuthority | None:
    if claim_requirement is None or source_inventory is None:
        return None
    candidates: list[CoverageScopeAuthority] = []
    configured = getattr(bundle, "_expected_scope_authorities", {})
    if isinstance(configured, Mapping):
        for key in (
            f"{claim_requirement.claim_requirement_id}:{source_inventory.source_inventory_id}",
            source_inventory.source_inventory_id,
            claim_requirement.claim_requirement_id,
        ):
            candidate = configured.get(key)
            if (
                isinstance(candidate, CoverageScopeAuthority)
                and candidate._is_trusted_for_authoritative_use
            ):
                candidates.append(candidate)
    # Persisted ledger authorities are deliberately untrusted after process
    # restart.  The bundle loader must revalidate them using the external
    # verifier root and install the trusted result above; never fall back to
    # an authority merely because it was serialized inside the bundle.
    matching_by_id = {
        candidate.authority_id: candidate
        for candidate in candidates
        if candidate.source_inventory_id == source_inventory.source_inventory_id
        and candidate.claim_requirement_id == claim_requirement.claim_requirement_id
        and candidate.authorization_binding == coverage_ledger.authorization_binding
    }
    return next(iter(matching_by_id.values())) if len(matching_by_id) == 1 else None


def _semantic_base_payload(
    request: _SemanticMcpRequest,
    *,
    status: str,
    claim_state: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "retrieval_path": SEMANTIC_RETRIEVAL_PATH,
        "retrieval_layer": SEMANTIC_RETRIEVAL_LAYER,
        "execution_mode": "authorized_structured_set",
        "query_class": request.query_class,
        "cardinality": request.cardinality,
        "claim_state": claim_state,
        "complete_projection": _semantic_complete_projection_unavailable(),
        "display_pagination": {
            "page_size": request.page_size,
            "page_number": request.page_number,
            "displayed_count": 0,
            "has_more": False,
        },
        "citation_handles": [],
        "canonical_kg": CANONICAL_KG,
    }


def _semantic_complete_projection(
    matches: Sequence[Any],
) -> dict[str, Any]:
    """Return the full unique projection only when its safe budget permits it.

    Matching remains complete and happens before display pagination.  This
    function is only a bounded transport projection: it keeps the first
    occurrence of each deterministic projection tuple from the already
    ordered execution and never exposes source/row identities.  If either
    server-owned bound is reached, no partial values are returned because a
    page-shaped subset must not be mistaken for an all-matching result.
    """

    projected_values: list[dict[str, list[str]]] = []
    seen_projections: set[tuple[str, ...]] = set()
    serialized_bytes = 2  # JSON ``[]`` for the values sequence.
    for match in matches:
        projection = getattr(match, "projection_values", None)
        if (
            not isinstance(projection, tuple)
            or not projection
            or any(not isinstance(value, str) or not value.strip() for value in projection)
        ):
            # A matching row without the requested projection is not an
            # absent match.  Returning the other rows would silently turn an
            # incomplete projection into an apparent all-matching set.
            return _semantic_complete_projection_unavailable_projection()
        if projection in seen_projections:
            continue
        projected = {"values": list(projection)}
        projected_bytes = len(
            json.dumps(
                projected,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if (
            len(projected_values) >= SEMANTIC_COMPLETE_SET_MAX_ITEMS
            or serialized_bytes + projected_bytes + (1 if projected_values else 0)
            > SEMANTIC_COMPLETE_SET_MAX_SERIALIZED_BYTES
        ):
            return _semantic_complete_projection_budget_exceeded()
        seen_projections.add(projection)
        projected_values.append(projected)
        serialized_bytes += projected_bytes + (1 if len(projected_values) > 1 else 0)
    return {
        "state": "complete",
        "values": projected_values,
        "safe_result_budget": _semantic_complete_result_budget(),
    }


def _semantic_complete_projection_unavailable() -> dict[str, Any]:
    return {
        "state": "not_available",
        "values": [],
        "safe_result_budget": _semantic_complete_result_budget(),
    }


def _semantic_complete_projection_budget_exceeded() -> dict[str, Any]:
    return {
        "state": "result_budget_exceeded",
        "values": [],
        "safe_result_budget": _semantic_complete_result_budget(),
    }


def _semantic_complete_projection_unavailable_projection() -> dict[str, Any]:
    return {
        "state": "projection_unavailable",
        "values": [],
        "safe_result_budget": _semantic_complete_result_budget(),
    }


def _semantic_complete_result_budget() -> dict[str, int]:
    return {
        "max_unique_projection_rows": SEMANTIC_COMPLETE_SET_MAX_ITEMS,
        "max_serialized_bytes": SEMANTIC_COMPLETE_SET_MAX_SERIALIZED_BYTES,
    }


def _semantic_insufficient_payload(request: _SemanticMcpRequest) -> dict[str, Any]:
    return _semantic_base_payload(
        request,
        status="insufficient",
        claim_state="UNRESOLVED",
    )


def _semantic_clarification_payload(request: _SemanticMcpRequest) -> dict[str, Any]:
    return _semantic_base_payload(
        request,
        status="clarification_required",
        claim_state="UNRESOLVED",
    )


def _semantic_permission_denied_payload(request: _SemanticMcpRequest) -> dict[str, Any]:
    return _semantic_base_payload(
        request,
        status="permission_denied",
        claim_state="UNRESOLVED",
    )


def _semantic_permission_denied(
    *,
    bundles: Sequence[MailEvidenceBundle],
    profile: DiagnosticSemanticProfile,
) -> bool:
    """Recognize a server-side access mismatch without exposing any scope data."""

    return any(
        bundle.mail_import_session.workspace_id == profile.workspace_id
        and bundle.mail_import_session.owner_user_id == profile.owner_user_id
        and any(
            ledger.authorization_binding is not None
            and ledger.authorization_binding.actor_context_id != profile.actor_context_id
            for ledger in bundle.coverage_ledgers
        )
        for bundle in bundles
    )


def _citation_handles(matches: Sequence[Any]) -> list[str]:
    """Return opaque, answer-bound handles rather than source payloads."""

    return [
        "citation:"
        + sha256_json(
            {
                "source_observation_id": getattr(match, "source_observation_id", ""),
                "structural_observation_id": getattr(match, "structural_observation_id", ""),
                "row_ordinal": getattr(match, "row_ordinal", -1),
            }
        )[7:23]
        for match in matches
    ]


def _normalized_semantic_text(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _parse_iso_instant(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class FormOwlDiagnosticMcpService:
    """Serve exactly one read-only candidate-KG MCP tool over JSON-RPC."""

    runtime: CandidateGraphQueryRuntime

    def handle(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(method, str):
            return _error_response(request_id, -32600, "Invalid request")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return _result_response(
                request_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": MCP_SERVER_NAME, "version": "0.2.0"},
                },
            )
        if method == "tools/list":
            return _result_response(request_id, {"tools": [_tool_schema()]})
        if method == "tools/call":
            if not isinstance(params, Mapping):
                return _error_response(request_id, -32602, "Invalid tool arguments")
            return self._call_tool(request_id, params)
        return _error_response(request_id, -32601, "Method not found")

    def _call_tool(self, request_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        if params.get("name") != MCP_TOOL_NAME or not isinstance(params.get("arguments"), Mapping):
            return _error_response(request_id, -32602, "Invalid tool arguments")
        try:
            evidence = self._query_effective_graph_view(params["arguments"])
        except (ContractValidationError, TypeError, ValueError):
            return _tool_result_response(
                request_id,
                _error_payload("invalid_request"),
                is_error=True,
            )
        except Exception:
            return _tool_result_response(
                request_id,
                _error_payload("candidate_retrieval_unavailable"),
                is_error=True,
            )
        return _tool_result_response(
            request_id,
            evidence,
            # An insufficient candidate result is evidence of no answer, not a
            # transport failure. The model must explain that result itself.
            is_error=evidence.get("status") == "error",
        )

    def _query_effective_graph_view(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        _validate_tool_arguments(arguments)
        semantic_request = arguments.get("semantic_request")
        if semantic_request is not None:
            return dict(
                self.runtime.execute_semantic_request(
                    _SemanticMcpRequest.from_dict(semantic_request)
                )
            )
        query_text = str(arguments["query_text"])
        requested_source_limit = int(arguments.get("limit", 5))
        exact_identifier_attribute_lookup = _is_exact_identifier_attribute_lookup(query_text)
        effective_source_limit = (
            _EXACT_IDENTIFIER_ATTRIBUTE_SOURCE_LIMIT
            if exact_identifier_attribute_lookup
            else requested_source_limit
        )
        payload = dict(self.runtime.retrieve(query_text=query_text, limit=effective_source_limit))
        trace = payload.get("retrieval_trace")
        if not isinstance(trace, Mapping):
            raise ContractValidationError("candidate retrieval trace is invalid")
        payload["retrieval_trace"] = {
            **dict(trace),
            "requested_source_limit": requested_source_limit,
            "effective_source_limit": effective_source_limit,
            "exact_identifier_attribute_lookup": exact_identifier_attribute_lookup,
        }
        return payload


def create_formowl_diagnostic_mcp_http_server(
    host: str,
    port: int,
    service: FormOwlDiagnosticMcpService,
) -> ThreadingHTTPServer:
    """Create the minimal real HTTP transport for the FormOwl MCP server."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "FormOwlDiagnosticMcp/0.2"

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/mcp":
                self.send_error(404)
                return
            content_type = self.headers.get("Content-Type", "")
            if not content_type.lower().startswith("application/json"):
                self._write_json(415, {"error": "unsupported_media_type"})
                return
            content_length = self.headers.get("Content-Length", "")
            if not content_length.isdigit():
                self._write_json(400, {"error": "bad_request"})
                return
            size = int(content_length)
            if size <= 0 or size > _MAX_HTTP_REQUEST_BYTES:
                self._write_json(400, {"error": "bad_request"})
                return
            try:
                request = json.loads(self.rfile.read(size).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._write_json(400, {"error": "bad_request"})
                return
            if not isinstance(request, dict):
                self._write_json(400, {"error": "bad_request"})
                return
            response = service.handle(request)
            if response is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._write_json(200, response)

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/health":
                self.send_error(404)
                return
            self._write_json(
                200,
                {
                    "status": "ready",
                    "server": MCP_SERVER_NAME,
                    "tool": MCP_TOOL_NAME,
                    "retrieval_path": RETRIEVAL_PATH,
                    "retrieval_layer": RETRIEVAL_LAYER,
                    "candidate_method_id": DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID,
                    "ontology_rerank_enabled": ONTOLOGY_RERANK_ENABLED,
                    "canonical_kg": CANONICAL_KG,
                },
            )

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _write_json(self, status: int, payload: Mapping[str, Any]) -> None:
            encoded = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return ThreadingHTTPServer((host, port), Handler)


def _tool_schema() -> dict[str, Any]:
    return {
        "name": MCP_TOOL_NAME,
        "description": (
            "Read candidate-only FormOwl KG evidence using the default candidate "
            "retrieval method. It does not expose a canonical effective graph. "
            "For one exact mixed letter-and-digit identifier paired with a "
            "specific requested attribute or status, request limit 1 unless "
            "the user explicitly asks for all matching sources."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query_text": {
                    "type": "string",
                    "description": "The user's evidence question.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_LIMIT,
                    "description": (
                        "Use 1 for a focused single-identifier attribute lookup; "
                        "request more only when the user needs multiple sources."
                    ),
                },
                "semantic_request": {
                    "type": "object",
                    "description": (
                        "Use only for an all-matching attribute-filter set request. "
                        "Pass ungrounded user mentions only; FormOwl binds permission, "
                        "scope, versions, aliases, coverage, and claim state server-side."
                    ),
                    "properties": {
                        "query_class": {"type": "string", "enum": ["attribute_filter"]},
                        "object_type_mention": {"type": "string"},
                        "predicate_mention": {"type": "string"},
                        "operator": {"type": "string", "enum": ["equals"]},
                        "value_mention": {"type": "string"},
                        "projection_mention": {"type": "string"},
                        "cardinality": {"type": "string", "enum": ["all_matching"]},
                        "page_size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": _MAX_SEMANTIC_PAGE_SIZE,
                        },
                        "page_number": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": _MAX_SEMANTIC_PAGE_NUMBER,
                        },
                    },
                    "required": [
                        "query_class",
                        "object_type_mention",
                        "predicate_mention",
                        "operator",
                        "value_mention",
                        "projection_mention",
                        "cardinality",
                        "page_size",
                        "page_number",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": ["query_text"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    }


def _validate_tool_arguments(arguments: Mapping[str, Any]) -> None:
    if set(arguments) - {"query_text", "limit", "semantic_request"}:
        raise ContractValidationError("MCP tool arguments are invalid")
    query_text = arguments.get("query_text")
    if (
        not isinstance(query_text, str)
        or not query_text.strip()
        or len(query_text) > _MAX_QUERY_CHARS
    ):
        raise ContractValidationError("MCP tool query is invalid")
    limit = arguments.get("limit", 5)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_LIMIT:
        raise ContractValidationError("MCP tool limit is invalid")
    semantic_request = arguments.get("semantic_request")
    if semantic_request is not None and not isinstance(semantic_request, Mapping):
        raise ContractValidationError("MCP semantic request is invalid")


def _is_exact_identifier_attribute_lookup(query_text: str) -> bool:
    """Recognize a focused one-identifier question without using domain aliases.

    This only controls the diagnostic source projection budget. Candidate
    retrieval remains the default index path and still performs its bounded
    recall before the one-source projection is applied.
    """

    identifiers = _mixed_identifiers(query_text)
    return (
        len(identifiers) == 1
        and bool(_query_text_terms(query_text, query_identifiers=identifiers))
        and _MULTI_SOURCE_INTENT_RE.search(unicodedata.normalize("NFKC", query_text)) is None
    )


def _selected_observation_ids(retrieval: Any) -> tuple[str, ...]:
    values = getattr(retrieval, "selected_observation_ids", ())
    if not isinstance(values, tuple):
        return ()
    return tuple(value for value in values if isinstance(value, str) and value)


def _proof_neighborhood_observation_ids(
    retrieval: Any,
    *,
    segments_by_observation_id: Mapping[str, Any],
    text_policy_runtime: Any,
    query_text: str,
    source_limit: int,
) -> tuple[str, ...]:
    """Rerank recalled source groups, then project bounded proof neighborhoods.

    Candidate retrieval ranks one or more anchor observations but also returns
    ``assembled_observation_ids``: every admissible observation belonging to
    the selected logical source items. Diagnostic UAT recalls a fixed bounded
    pool, merges query coverage across each logical source, applies a stable
    source-group rerank, and only then applies the client source limit.
    """

    raw_assembled_ids = getattr(retrieval, "assembled_observation_ids", ())
    if not isinstance(raw_assembled_ids, tuple):
        return ()
    assembled_ids = tuple(
        observation_id
        for observation_id in raw_assembled_ids
        if isinstance(observation_id, str)
        and observation_id
        and observation_id in segments_by_observation_id
    )
    source_keys = _selected_source_item_keys(retrieval)
    grouped: dict[tuple[str, str], list[str]] = {}
    source_order: list[tuple[str, str]] = []
    for observation_id in assembled_ids:
        source_key = _source_item_key(segments_by_observation_id[observation_id])
        if source_key not in grouped:
            grouped[source_key] = []
            source_order.append(source_key)
        if observation_id not in grouped[source_key]:
            grouped[source_key].append(observation_id)

    ordered_source_keys = [source_key for source_key in source_keys if source_key in grouped] + [
        source_key for source_key in source_order if source_key not in source_keys
    ]
    query_tokens = _normalized_query_tokens(text_policy_runtime.tokenize(query_text))
    query_identifiers = _mixed_identifiers(query_text)
    query_terms = _query_text_terms(
        query_text,
        query_identifiers=query_identifiers,
    )
    ranked_source_keys = [
        (
            _source_group_query_coverage(
                grouped[source_key],
                segments_by_observation_id=segments_by_observation_id,
                query_tokens=query_tokens,
                query_identifiers=query_identifiers,
                query_terms=query_terms,
            ),
            source_index,
            source_key,
        )
        for source_index, source_key in enumerate(ordered_source_keys)
    ]
    ranked_source_keys.sort(
        key=lambda item: (
            -item[0][0],
            -item[0][1],
            -item[0][2],
            item[1],
        )
    )
    result: list[str] = []
    for _score, _source_index, source_key in ranked_source_keys[:source_limit]:
        observation_ids = sorted(
            grouped[source_key],
            key=lambda observation_id: _version_projection_sort_key(
                segments_by_observation_id[observation_id],
                observation_id=observation_id,
            ),
        )
        for observation_id in observation_ids[:_MAX_EVIDENCE_ITEMS_PER_SOURCE]:
            if len(result) >= _MAX_EVIDENCE_ITEMS_OVERALL:
                return tuple(result)
            result.append(observation_id)
    return tuple(result)


def _version_projection_sort_key(
    segment: Any,
    *,
    observation_id: str,
) -> tuple[int, int, int, str]:
    """Keep current evidence before quoted context in one logical source.

    The candidate index still decides which logical sources are admissible and
    retrieved. This projection ordering only makes the existing structural
    version context explicit and bounded for the model.
    """

    representation = getattr(segment, "source_version_representation", None)
    if representation == "current":
        representation_rank = 0
    elif representation == "current_context":
        representation_rank = 1
    elif representation == "quoted":
        representation_rank = 3
    else:
        representation_rank = 2
    return (
        representation_rank,
        _nonnegative_int(getattr(segment, "source_version_current_depth", 0)),
        _nonnegative_int(getattr(segment, "source_version_quoted_depth", 0)),
        observation_id,
    )


def _source_group_query_coverage(
    observation_ids: list[str],
    *,
    segments_by_observation_id: Mapping[str, Any],
    query_tokens: frozenset[str],
    query_identifiers: frozenset[str],
    query_terms: frozenset[str],
) -> tuple[int, int, int]:
    segment_tokens: set[str] = set()
    identifier_hits: set[str] = set()
    query_term_hits: set[str] = set()
    for observation_id in observation_ids:
        segment = segments_by_observation_id[observation_id]
        segment_tokens.update(_normalized_query_tokens(getattr(segment, "tokens", ())))
        searchable_text = getattr(segment, "searchable_text", "")
        if not isinstance(searchable_text, str):
            continue
        identifier_hits.update(
            identifier
            for identifier in query_identifiers
            if _contains_exact_identifier(searchable_text, identifier)
        )
        query_term_hits.update(
            term for term in query_terms if _contains_query_term(searchable_text, term)
        )
    return (
        len(identifier_hits),
        len(query_term_hits),
        len(query_tokens & segment_tokens),
    )


def _normalized_query_tokens(values: Any) -> frozenset[str]:
    if isinstance(values, str):
        return frozenset()
    try:
        return frozenset(
            value.strip().casefold() for value in values if isinstance(value, str) and value.strip()
        )
    except TypeError:
        return frozenset()


def _mixed_identifiers(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value)
    return frozenset(
        token.casefold()
        for token in _MIXED_IDENTIFIER_RE.findall(normalized)
        if len(token) >= 4
        and any(character.isalpha() for character in token)
        and any(character.isdigit() for character in token)
    )


def _query_text_terms(
    value: str,
    *,
    query_identifiers: frozenset[str],
) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value)
    masked = normalized
    for identifier in sorted(query_identifiers, key=len, reverse=True):
        masked = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(identifier)}(?![A-Za-z0-9])",
            " ",
            masked,
            flags=re.IGNORECASE,
        )
    terms: list[str] = []
    seen: set[str] = set()
    for match in _ASCII_QUERY_WORD_RE.finditer(masked):
        term = match.group(0).casefold()
        if term in _QUERY_STOPWORDS or term in seen:
            continue
        terms.append(term)
        seen.add(term)
        if len(terms) >= _MAX_QUERY_COVERAGE_TERMS:
            return frozenset(terms)
    for run in _CJK_QUERY_RUN_RE.findall(masked):
        trimmed = _trim_cjk_query_run(run)
        if len(trimmed) < 2:
            continue
        for width in range(min(4, len(trimmed)), 1, -1):
            for start in range(len(trimmed) - width + 1):
                term = trimmed[start : start + width]
                if term in _QUERY_STOPWORDS or term in seen:
                    continue
                terms.append(term)
                seen.add(term)
                if len(terms) >= _MAX_QUERY_COVERAGE_TERMS:
                    return frozenset(terms)
    return frozenset(terms)


def _trim_cjk_query_run(value: str) -> str:
    trimmed = value
    changed = True
    while changed and trimmed:
        changed = False
        for prefix in _CJK_QUERY_PREFIX_STOPWORDS:
            if trimmed.startswith(prefix):
                trimmed = trimmed[len(prefix) :]
                changed = True
                break
        for suffix in _CJK_QUERY_SUFFIX_STOPWORDS:
            if trimmed.endswith(suffix):
                trimmed = trimmed[: -len(suffix)]
                changed = True
                break
    return trimmed


def _contains_exact_identifier(value: str, identifier: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    return (
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(identifier)}(?![A-Za-z0-9])",
            normalized,
            flags=re.IGNORECASE,
        )
        is not None
    )


def _contains_query_term(value: str, term: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    if term.isascii():
        return (
            re.search(
                rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])",
                normalized,
                flags=re.IGNORECASE,
            )
            is not None
        )
    return term in normalized


def _selected_source_item_keys(retrieval: Any) -> tuple[tuple[str, str], ...]:
    values = getattr(retrieval, "selected_source_item_keys", ())
    if not isinstance(values, tuple):
        return ()
    keys: list[tuple[str, str]] = []
    for value in values:
        if (
            isinstance(value, tuple)
            and len(value) == 2
            and all(isinstance(item, str) and item for item in value)
            and value not in keys
        ):
            keys.append(value)
    return tuple(keys)


def _source_item_key(segment: Any) -> tuple[str, str]:
    return (
        _safe_text(getattr(segment, "source_identity_policy_id", None), 500),
        _safe_text(getattr(segment, "source_item_id", None), 500),
    )


def _safe_candidate_result(segment: Any) -> dict[str, Any]:
    source_item_id = getattr(segment, "source_item_id", "")
    result: dict[str, Any] = {
        "source_identity": "mail:" + sha256_json({"source_item_id": source_item_id})[-20:],
        "subject": _safe_text(getattr(segment, "subject", None), _MAX_SUBJECT_CHARS),
        "sent_at": _safe_text(getattr(segment, "sent_at", None), 100),
        "snippet": _safe_text(getattr(segment, "searchable_text", None), _MAX_SNIPPET_CHARS),
    }
    representation = getattr(segment, "source_version_representation", None)
    if representation in {"current", "current_context", "quoted"}:
        result["version_provenance"] = {
            "representation": representation,
            "current_depth": _nonnegative_int(getattr(segment, "source_version_current_depth", 0)),
            "quoted_depth": _nonnegative_int(getattr(segment, "source_version_quoted_depth", 0)),
            "answer_precedence": {
                "current": "preferred_current",
                "current_context": "current_context",
                "quoted": "quoted_context",
            }[representation],
        }
    return result


def _safe_text(value: Any, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:maximum]


def _safe_insufficiency_reason(retrieval: Any) -> str:
    reason = getattr(retrieval, "rejection_reason", None)
    if isinstance(reason, str) and reason in {
        "no_supported_evidence",
        "insufficient_supported_evidence",
        "no_admissible_evidence",
        "no_accessible_evidence",
    }:
        return reason
    return "no_candidate_evidence"


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _tool_result_response(
    request_id: Any,
    payload: Mapping[str, Any],
    *,
    is_error: bool,
) -> dict[str, Any]:
    rendered = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": rendered}],
        "structuredContent": dict(payload),
    }
    if is_error:
        result["isError"] = True
    return _result_response(request_id, result)


def _error_payload(error_code: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error_code": error_code,
        "retrieval_path": RETRIEVAL_PATH,
        "retrieval_layer": RETRIEVAL_LAYER,
        "candidate_method_id": DEFAULT_CANDIDATE_EVIDENCE_METHOD_ID,
        "ontology_rerank_enabled": ONTOLOGY_RERANK_ENABLED,
        "canonical_kg": CANONICAL_KG,
    }


def _result_response(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


__all__ = [
    "CANONICAL_KG",
    "CandidateGraphQueryRuntime",
    "FormOwlDiagnosticMcpService",
    "MCP_PROTOCOL_VERSION",
    "MCP_SERVER_NAME",
    "MCP_TOOL_NAME",
    "ONTOLOGY_RERANK_ENABLED",
    "RETRIEVAL_LAYER",
    "RETRIEVAL_PATH",
    "SEMANTIC_COMPLETE_SET_MAX_ITEMS",
    "SEMANTIC_COMPLETE_SET_MAX_SERIALIZED_BYTES",
    "create_formowl_diagnostic_mcp_http_server",
]
