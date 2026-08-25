"""Select one private, source-backed Issue #56 relation prompt.

The selector consumes only an already-authorized semantic session, its sealed
candidate-only identifier inventory, and the matching permission-filtered
effective graph view.  It does not execute a query, add graph relations, or
fall back to synthetic identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from formowl_contract import (
    CandidateMention,
    ContractValidationError,
    Observation,
    sha256_json,
    to_plain,
)
from formowl_graph import EffectiveGraphView
from formowl_graph.index import GraphProjectionEdge, GraphProjectionNode

from ._guards import assert_public_payload_safe
from .candidates import (
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT,
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID,
    SourceBoundIdentifierMentionBatch,
    SourceIdentifierIdentityScope,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
)
from .hybrid import AuthorizedSemanticMailSession
from . import hybrid as _hybrid


SELECTION_ALGORITHM_ID = "issue56_source_backed_connected_identifier_prompt_selection_v1"
SELECTION_SCHEMA_VERSION = 1
_PROMPT_TEMPLATE_ID = "issue56_private_identifier_relation_prompt_zh_v1"
_ALLOWED_IDENTIFIER_KINDS = frozenset({"business_identifier"})
_MAX_IDENTIFIER_LENGTH = 256


class SourceBackedIdentifierPromptSelectionError(ContractValidationError):
    """Fail-closed selector error with a stable, non-private reason code."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class SourceBackedConnectedIdentifierPromptSelection:
    """One private prompt and its hash/count-only selection proof."""

    runtime_prompt: str = field(repr=False, compare=False)
    safe_selection_proof: Mapping[str, Any]

    def to_safe_dict(self) -> dict[str, Any]:
        payload = dict(self.safe_selection_proof)
        assert_public_payload_safe(
            payload,
            "issue56_source_backed_connected_identifier_prompt_selection",
        )
        _reject_tenant_key(payload)
        return payload


@dataclass(frozen=True)
class _IdentifierOccurrence:
    term_hash: str
    runtime_term: str = field(repr=False, compare=False)
    identifier_kind: str
    observation_id: str = field(repr=False, compare=False)
    observation_hash: str
    permission_fingerprint: str
    mention_hash: str


class _CachingTokenizerProfile:
    """Query-local adapter that preserves the pinned profile and caches analyses."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self._analysis_by_text: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def analyze(self, text: str) -> Any:
        analysis = self._analysis_by_text.get(text)
        if analysis is None:
            analysis = self._delegate.analyze(text)
            self._analysis_by_text[text] = analysis
        return analysis


@dataclass(frozen=True)
class _IdentifierNodeSupport:
    term_hash: str
    node_id: str = field(repr=False, compare=False)
    node_hash: str
    support_observation_ids: tuple[str, ...] = field(repr=False, compare=False)
    support_observation_hashes: tuple[str, ...]


@dataclass(frozen=True)
class _ValidatedGraph:
    nodes_by_id: Mapping[str, GraphProjectionNode] = field(repr=False, compare=False)
    node_evidence_ids: Mapping[str, tuple[str, ...]] = field(
        repr=False,
        compare=False,
    )
    edges_by_id: Mapping[str, GraphProjectionEdge] = field(repr=False, compare=False)
    edge_evidence_ids: Mapping[str, tuple[str, ...]] = field(
        repr=False,
        compare=False,
    )
    allowed_edge_ids: tuple[str, ...] = field(repr=False, compare=False)
    adjacency: Mapping[str, tuple[tuple[str, str], ...]] = field(
        repr=False,
        compare=False,
    )
    graph_revision_fingerprint: str


@dataclass(frozen=True)
class _PathCandidate:
    left: _IdentifierNodeSupport = field(repr=False, compare=False)
    right: _IdentifierNodeSupport = field(repr=False, compare=False)
    node_ids: tuple[str, ...] = field(repr=False, compare=False)
    edge_ids: tuple[str, ...] = field(repr=False, compare=False)
    node_hashes: tuple[str, ...]
    edge_hashes: tuple[str, ...]

    @property
    def hop_count(self) -> int:
        return len(self.edge_ids)


def select_source_backed_connected_identifier_prompt(
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
    candidate_inventory: SourceBoundIdentifierMentionBatch,
    allowed_relation_types: Sequence[str],
    max_hops: int = 2,
) -> SourceBackedConnectedIdentifierPromptSelection:
    """Select a deterministic connected pair without executing the query.

    Only ``business_identifier`` protected spans are eligible.  Every selected
    term must be present in the authorized Observation, in the authorized
    lexical index, and on the selected source-backed graph node.  Every path
    hop must carry authorized Observation evidence under the same permission
    boundary.  If no such pair exists, the function fails closed.
    """

    if not isinstance(session, AuthorizedSemanticMailSession):
        raise SourceBackedIdentifierPromptSelectionError("session_contract_invalid")
    if not isinstance(effective_graph_view, EffectiveGraphView):
        raise SourceBackedIdentifierPromptSelectionError("effective_graph_view_contract_invalid")
    relations = _validated_relation_types(allowed_relation_types)
    if isinstance(max_hops, bool) or not isinstance(max_hops, int) or not 1 <= max_hops <= 2:
        raise SourceBackedIdentifierPromptSelectionError("max_hops_contract_invalid")

    try:
        _hybrid._validate_hybrid_index_runtime(session.index)
    except ContractValidationError as exc:
        raise SourceBackedIdentifierPromptSelectionError(
            "authorized_index_binding_invalid"
        ) from exc
    if effective_graph_view.requester_user_id != session.requester_user_id:
        raise SourceBackedIdentifierPromptSelectionError("graph_requester_binding_mismatch")

    observations_by_id, observation_hash_by_id = _validated_authorized_observations(session)
    identity_scope, mentions = _validated_candidate_inventory(
        session=session,
        candidate_inventory=candidate_inventory,
    )
    occurrences = _validated_identifier_occurrences(
        session=session,
        observations_by_id=observations_by_id,
        observation_hash_by_id=observation_hash_by_id,
        candidate_inventory=candidate_inventory,
        identity_scope=identity_scope,
        mentions=mentions,
    )
    if len({item.term_hash for item in occurrences}) < 2:
        raise SourceBackedIdentifierPromptSelectionError("connected_identifier_pair_unavailable")

    validated_graph = _validated_graph(
        session=session,
        effective_graph_view=effective_graph_view,
        identity_scope=identity_scope,
        observations_by_id=observations_by_id,
        observation_hash_by_id=observation_hash_by_id,
        allowed_relation_types=relations,
    )
    supports = _identifier_node_supports(
        occurrences=occurrences,
        graph=validated_graph,
        observations_by_id=observations_by_id,
        observation_hash_by_id=observation_hash_by_id,
    )
    selected = _select_path_candidate(
        supports=supports,
        graph=validated_graph,
        max_hops=max_hops,
    )
    if selected is None:
        raise SourceBackedIdentifierPromptSelectionError("connected_identifier_pair_unavailable")

    occurrence_by_term_hash = _deterministic_occurrence_by_term_hash(occurrences)
    left_occurrence = occurrence_by_term_hash[selected.left.term_hash]
    right_occurrence = occurrence_by_term_hash[selected.right.term_hash]
    runtime_prompt = f"{left_occurrence.runtime_term} 與 {right_occurrence.runtime_term} 的關係"
    if (
        not runtime_prompt
        or len(left_occurrence.runtime_term) > _MAX_IDENTIFIER_LENGTH
        or len(right_occurrence.runtime_term) > _MAX_IDENTIFIER_LENGTH
    ):
        raise SourceBackedIdentifierPromptSelectionError("private_prompt_contract_invalid")

    minimal_support_by_term_hash = _minimal_support_observation_ids(
        selected,
        observation_hash_by_id=observation_hash_by_id,
    )
    path_observation_ids = set(minimal_support_by_term_hash.values())
    path_observation_ids.update(
        observation_id
        for edge_id in selected.edge_ids
        for observation_id in validated_graph.edge_evidence_ids[edge_id]
    )
    if not set(minimal_support_by_term_hash.values()).issubset(path_observation_ids):
        raise SourceBackedIdentifierPromptSelectionError("path_slot_evidence_incomplete")
    path_observation_hashes = tuple(
        sorted(observation_hash_by_id[item] for item in path_observation_ids)
    )
    support_rows = (
        {
            "term_hash": selected.left.term_hash,
            "node_hash": selected.left.node_hash,
            "support_observation_hashes": [
                observation_hash_by_id[minimal_support_by_term_hash[selected.left.term_hash]]
            ],
        },
        {
            "term_hash": selected.right.term_hash,
            "node_hash": selected.right.node_hash,
            "support_observation_hashes": [
                observation_hash_by_id[minimal_support_by_term_hash[selected.right.term_hash]]
            ],
        },
    )
    session_binding_fingerprint = _selection_session_binding_fingerprint(
        session=session,
        observation_hash_by_id=observation_hash_by_id,
    )
    source_access_fingerprint = (
        session.authorized_source.authorization_fingerprint
        if session.authorized_source is not None
        else sha256_json(
            {
                "workspace_hash": sha256_json(session.workspace_id),
                "authorized_source_scope_hashes": sorted(
                    sha256_json(item) for item in session.authorized_source_scope_ids
                ),
            }
        )
    )
    proof_without_self = {
        "artifact_id": ("formowl_issue56_source_backed_connected_identifier_prompt_selection_v1"),
        "schema_version": SELECTION_SCHEMA_VERSION,
        "status": "selected",
        "claim_boundary": "diagnostic_prompt_selection_only_no_query_executed",
        "selection_algorithm_id": SELECTION_ALGORITHM_ID,
        "prompt_template_fingerprint": sha256_json(_PROMPT_TEMPLATE_ID),
        "selected_identifier_count": 2,
        "selected_term_hashes": [
            selected.left.term_hash,
            selected.right.term_hash,
        ],
        "selected_node_hashes": list(selected.node_hashes),
        "selected_edge_hashes": list(selected.edge_hashes),
        "selected_observation_hashes": list(path_observation_hashes),
        "identifier_support": list(support_rows),
        "path_hop_count": selected.hop_count,
        "path_node_count": len(selected.node_ids),
        "path_edge_count": len(selected.edge_ids),
        "path_observation_count": len(path_observation_hashes),
        "allowed_relation_type_hashes": [sha256_json(item) for item in relations],
        "max_hops": max_hops,
        "index_fingerprint": session.index.index_fingerprint,
        "graph_revision_fingerprint": (validated_graph.graph_revision_fingerprint),
        "source_access_fingerprint": source_access_fingerprint,
        "source_session_binding_fingerprint": session_binding_fingerprint,
        "candidate_inventory_fingerprint": candidate_inventory.batch_fingerprint,
        "identity_scope_mode_fingerprint": sha256_json(candidate_inventory.identity_scope_mode),
        "identity_scope_fingerprint": candidate_inventory.identity_scope_fingerprint,
        "workspace_scope_fingerprint": sha256_json(session.workspace_id),
        "requester_fingerprint": sha256_json(session.requester_user_id),
        "synthetic_fallback_used": False,
        "query_executed": False,
    }
    proof = {
        **proof_without_self,
        "selection_proof_fingerprint": sha256_json(proof_without_self),
    }
    assert_public_payload_safe(
        proof,
        "issue56_source_backed_connected_identifier_prompt_selection",
    )
    _reject_tenant_key(proof)
    return SourceBackedConnectedIdentifierPromptSelection(
        runtime_prompt=runtime_prompt,
        safe_selection_proof=MappingProxyType(proof),
    )


def _validated_relation_types(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise SourceBackedIdentifierPromptSelectionError("allowed_relation_types_contract_invalid")
    relations = tuple(sorted(set(values)))
    if not relations or any(
        not isinstance(item, str)
        or not item
        or len(item) > 128
        or not item.replace("_", "").isalnum()
        for item in relations
    ):
        raise SourceBackedIdentifierPromptSelectionError("allowed_relation_types_contract_invalid")
    return relations


def _validated_authorized_observations(
    session: AuthorizedSemanticMailSession,
) -> tuple[dict[str, Observation], dict[str, str]]:
    observations_by_id: dict[str, Observation] = {}
    observation_hash_by_id: dict[str, str] = {}
    for observation in session.authorized_observations:
        try:
            validated = Observation.from_dict(observation.to_dict())
        except (AttributeError, TypeError, ContractValidationError) as exc:
            raise SourceBackedIdentifierPromptSelectionError(
                "authorized_observation_contract_invalid"
            ) from exc
        if validated.observation_id in observations_by_id:
            raise SourceBackedIdentifierPromptSelectionError(
                "authorized_observation_identity_duplicate"
            )
        observations_by_id[validated.observation_id] = validated
        observation_hash_by_id[validated.observation_id] = sha256_json(validated.to_dict())
    if (
        not observations_by_id
        or tuple(sorted(observation_hash_by_id.items())) != session.authorized_observation_hashes
    ):
        raise SourceBackedIdentifierPromptSelectionError("authorized_observation_binding_mismatch")
    if (
        session.authorized_source is None
        or session.authorized_source.workspace_id != session.workspace_id
        or session.authorized_source.source_scope_ids != session.authorized_source_scope_ids
    ):
        raise SourceBackedIdentifierPromptSelectionError("authorized_source_binding_mismatch")
    return observations_by_id, observation_hash_by_id


def _validated_candidate_inventory(
    *,
    session: AuthorizedSemanticMailSession,
    candidate_inventory: SourceBoundIdentifierMentionBatch,
) -> tuple[SourceIdentifierIdentityScope, tuple[CandidateMention, ...]]:
    if not isinstance(candidate_inventory, SourceBoundIdentifierMentionBatch):
        raise SourceBackedIdentifierPromptSelectionError("candidate_inventory_contract_invalid")
    try:
        identity_scope = SourceIdentifierIdentityScope(
            identity_scope_mode=candidate_inventory.identity_scope_mode,
            identity_scope_fingerprint=(candidate_inventory.identity_scope_fingerprint),
            workspace_id=candidate_inventory.workspace_id,
            identity_scope_attestation_fingerprint=(
                candidate_inventory.identity_scope_attestation_fingerprint
            ),
            identity_scope_policy_fingerprint=(
                candidate_inventory.identity_scope_policy_fingerprint
            ),
            operator_approval_fingerprint=(candidate_inventory.operator_approval_fingerprint),
            tenant_id=candidate_inventory.tenant_id,
            spec_approval_fingerprint=(candidate_inventory.spec_approval_fingerprint),
        )
    except (AttributeError, TypeError, ContractValidationError) as exc:
        raise SourceBackedIdentifierPromptSelectionError(
            "candidate_identity_scope_invalid"
        ) from exc
    if (
        identity_scope.identity_scope_mode != WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
        or identity_scope.tenant_id is not None
        or identity_scope.workspace_id != session.workspace_id
        or candidate_inventory.tokenizer_id != session.index.tokenizer_id
        or candidate_inventory.tokenizer_profile_fingerprint != session.index.profile_fingerprint
        or candidate_inventory.extraction_policy_id != SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_ID
        or candidate_inventory.extraction_policy_fingerprint
        != SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
    ):
        raise SourceBackedIdentifierPromptSelectionError("candidate_inventory_binding_mismatch")
    _reject_tenant_key(candidate_inventory.to_dict())
    try:
        mentions = tuple(
            CandidateMention.from_dict(item.to_dict())
            for item in candidate_inventory.candidate_mentions
        )
    except (AttributeError, TypeError, ContractValidationError) as exc:
        raise SourceBackedIdentifierPromptSelectionError(
            "candidate_mention_contract_invalid"
        ) from exc
    mention_ids = tuple(item.candidate_mention_id for item in mentions)
    expected_batch_fingerprint = sha256_json(
        {
            "candidate_mention_ids": list(mention_ids),
            "extraction_policy_fingerprint": (
                SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
            ),
            "identity_scope": identity_scope.to_dict(),
            "tokenizer_profile_fingerprint": session.index.profile_fingerprint,
        }
    )
    if (
        candidate_inventory.occurrence_count != len(mentions)
        or mention_ids != tuple(sorted(mention_ids))
        or len(set(mention_ids)) != len(mention_ids)
        or candidate_inventory.batch_fingerprint != expected_batch_fingerprint
    ):
        raise SourceBackedIdentifierPromptSelectionError("candidate_inventory_seal_mismatch")
    return identity_scope, mentions


def _validated_identifier_occurrences(
    *,
    session: AuthorizedSemanticMailSession,
    observations_by_id: Mapping[str, Observation],
    observation_hash_by_id: Mapping[str, str],
    candidate_inventory: SourceBoundIdentifierMentionBatch,
    identity_scope: SourceIdentifierIdentityScope,
    mentions: Sequence[CandidateMention],
) -> tuple[_IdentifierOccurrence, ...]:
    profile = _CachingTokenizerProfile(session.index._runtime_components.tokenizer_profile)
    index_candidates_by_observation_hash: dict[str, list[Any]] = {}
    for candidate in session.index.candidates:
        index_candidates_by_observation_hash.setdefault(
            candidate.source_observation_hash,
            [],
        ).append(candidate)
    occurrences: list[_IdentifierOccurrence] = []
    for mention in mentions:
        if len(mention.source_observation_ids) != 1:
            raise SourceBackedIdentifierPromptSelectionError(
                "candidate_observation_lineage_invalid"
            )
        observation_id = mention.source_observation_ids[0]
        observation = observations_by_id.get(observation_id)
        if observation is None:
            continue
        try:
            _hybrid._source_graph_validate_identifier_mention(
                mention,
                batch=candidate_inventory,
                identity_scope=identity_scope,
                observation=observation,
                tokenizer_profile=profile,
            )
        except ContractValidationError as exc:
            raise SourceBackedIdentifierPromptSelectionError(
                "candidate_exact_term_lineage_invalid"
            ) from exc
        identifier_kind = mention.location.get("identifier_kind")
        if identifier_kind not in _ALLOWED_IDENTIFIER_KINDS:
            continue
        span_start = mention.location.get("span_start")
        span_end = mention.location.get("span_end")
        if (
            isinstance(span_start, bool)
            or isinstance(span_end, bool)
            or not isinstance(span_start, int)
            or not isinstance(span_end, int)
            or not isinstance(observation.text, str)
        ):
            raise SourceBackedIdentifierPromptSelectionError("candidate_exact_term_lineage_invalid")
        matching_spans = [
            span
            for span in profile.analyze(observation.text).protected_identifiers
            if span.start == span_start
            and span.end == span_end
            and span.identifier_kind == identifier_kind
            and sha256_json(span.exact_token) == mention.text_hash
        ]
        if len(matching_spans) != 1:
            raise SourceBackedIdentifierPromptSelectionError("candidate_exact_term_lineage_invalid")
        matched_span = matching_spans[0]
        candidates = index_candidates_by_observation_hash.get(
            observation_hash_by_id[observation_id],
            (),
        )
        if not any(
            matched_span.exact_token in candidate.observation_protected_identifier_tokens
            for candidate in candidates
        ):
            raise SourceBackedIdentifierPromptSelectionError("candidate_lexical_anchor_missing")
        permission_fingerprint = sha256_json(to_plain(observation.permission_scope))
        occurrences.append(
            _IdentifierOccurrence(
                term_hash=mention.text_hash,
                runtime_term=matched_span.exact_token,
                identifier_kind=identifier_kind,
                observation_id=observation_id,
                observation_hash=observation_hash_by_id[observation_id],
                permission_fingerprint=permission_fingerprint,
                mention_hash=sha256_json(mention.candidate_mention_id),
            )
        )
    return tuple(
        sorted(
            occurrences,
            key=lambda item: (
                item.term_hash,
                item.observation_hash,
                item.mention_hash,
            ),
        )
    )


def _validated_graph(
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
    identity_scope: SourceIdentifierIdentityScope,
    observations_by_id: Mapping[str, Observation],
    observation_hash_by_id: Mapping[str, str],
    allowed_relation_types: Sequence[str],
) -> _ValidatedGraph:
    try:
        graph_revision_fingerprint = _hybrid._graph_revision_fingerprint(effective_graph_view)
        expected_identity_binding = _hybrid._source_graph_identity_scope_graph_binding(
            identity_scope
        )
    except ContractValidationError as exc:
        raise SourceBackedIdentifierPromptSelectionError("effective_graph_binding_invalid") from exc
    nodes_by_id: dict[str, GraphProjectionNode] = {}
    node_evidence_ids: dict[str, tuple[str, ...]] = {}
    for node in effective_graph_view.visible_nodes:
        if node.node_id in nodes_by_id:
            raise SourceBackedIdentifierPromptSelectionError(
                "effective_graph_node_identity_duplicate"
            )
        _reject_tenant_key(node.to_dict())
        evidence_ids = _validated_graph_item_evidence(
            item=node,
            observations_by_id=observations_by_id,
            observation_hash_by_id=observation_hash_by_id,
            expected_identity_binding=expected_identity_binding,
        )
        nodes_by_id[node.node_id] = node
        node_evidence_ids[node.node_id] = evidence_ids
    if not nodes_by_id:
        raise SourceBackedIdentifierPromptSelectionError("effective_graph_nodes_unavailable")

    allowed_set = set(allowed_relation_types)
    edges_by_id: dict[str, GraphProjectionEdge] = {}
    edge_evidence_ids: dict[str, tuple[str, ...]] = {}
    adjacency: dict[str, list[tuple[str, str]]] = {}
    allowed_edge_ids: list[str] = []
    for edge in effective_graph_view.visible_edges:
        if edge.edge_id in edges_by_id:
            raise SourceBackedIdentifierPromptSelectionError(
                "effective_graph_edge_identity_duplicate"
            )
        if edge.source_node_id not in nodes_by_id or edge.target_node_id not in nodes_by_id:
            raise SourceBackedIdentifierPromptSelectionError(
                "effective_graph_edge_endpoint_invalid"
            )
        _reject_tenant_key(edge.to_dict())
        evidence_ids = _validated_graph_item_evidence(
            item=edge,
            observations_by_id=observations_by_id,
            observation_hash_by_id=observation_hash_by_id,
            expected_identity_binding=expected_identity_binding,
        )
        edges_by_id[edge.edge_id] = edge
        edge_evidence_ids[edge.edge_id] = evidence_ids
        if edge.relation_type in allowed_set:
            allowed_edge_ids.append(edge.edge_id)
            adjacency.setdefault(edge.source_node_id, []).append(
                (edge.target_node_id, edge.edge_id)
            )
            adjacency.setdefault(edge.target_node_id, []).append(
                (edge.source_node_id, edge.edge_id)
            )
    frozen_adjacency = {
        node_id: tuple(
            sorted(
                neighbors,
                key=lambda item: (
                    sha256_json(item[0]),
                    sha256_json(item[1]),
                ),
            )
        )
        for node_id, neighbors in adjacency.items()
    }
    return _ValidatedGraph(
        nodes_by_id=MappingProxyType(nodes_by_id),
        node_evidence_ids=MappingProxyType(node_evidence_ids),
        edges_by_id=MappingProxyType(edges_by_id),
        edge_evidence_ids=MappingProxyType(edge_evidence_ids),
        allowed_edge_ids=tuple(
            sorted(
                allowed_edge_ids,
                key=sha256_json,
            )
        ),
        adjacency=MappingProxyType(frozen_adjacency),
        graph_revision_fingerprint=graph_revision_fingerprint,
    )


def _validated_graph_item_evidence(
    *,
    item: GraphProjectionNode | GraphProjectionEdge,
    observations_by_id: Mapping[str, Observation],
    observation_hash_by_id: Mapping[str, str],
    expected_identity_binding: Mapping[str, str],
) -> tuple[str, ...]:
    if any(item.properties.get(key) != value for key, value in expected_identity_binding.items()):
        raise SourceBackedIdentifierPromptSelectionError("effective_graph_identity_scope_mismatch")
    values = item.properties.get("source_observation_ids")
    if (
        not isinstance(values, (list, tuple))
        or not values
        or any(not isinstance(value, str) or not value for value in values)
    ):
        raise SourceBackedIdentifierPromptSelectionError("effective_graph_evidence_lineage_invalid")
    evidence_ids = tuple(sorted(set(values)))
    if any(item not in observation_hash_by_id for item in evidence_ids):
        raise SourceBackedIdentifierPromptSelectionError("effective_graph_evidence_not_authorized")
    permission_scope = to_plain(item.permission_scope)
    if any(
        to_plain(observations_by_id[observation_id].permission_scope) != permission_scope
        for observation_id in evidence_ids
    ):
        raise SourceBackedIdentifierPromptSelectionError(
            "effective_graph_permission_lineage_mismatch"
        )
    return evidence_ids


def _identifier_node_supports(
    *,
    occurrences: Sequence[_IdentifierOccurrence],
    graph: _ValidatedGraph,
    observations_by_id: Mapping[str, Observation],
    observation_hash_by_id: Mapping[str, str],
) -> tuple[_IdentifierNodeSupport, ...]:
    occurrence_ids_by_term_hash: dict[str, set[str]] = {}
    for occurrence in occurrences:
        occurrence_ids_by_term_hash.setdefault(occurrence.term_hash, set()).add(
            occurrence.observation_id
        )
    supports: list[_IdentifierNodeSupport] = []
    for node_id, node in graph.nodes_by_id.items():
        if (
            node.source_type != "mail_candidate_identifier"
            or node.properties.get("node_kind") != "candidate_identifier"
        ):
            continue
        protected_hashes = _hash_values(node.properties.get("protected_term_hashes"))
        if not protected_hashes:
            continue
        node_evidence_ids = set(graph.node_evidence_ids[node_id])
        node_permission_fingerprint = sha256_json(to_plain(node.permission_scope))
        for term_hash in sorted(protected_hashes):
            supporting_ids = tuple(
                sorted(
                    node_evidence_ids & occurrence_ids_by_term_hash.get(term_hash, set()),
                    key=lambda item: observation_hash_by_id[item],
                )
            )
            if not supporting_ids:
                continue
            if any(
                sha256_json(to_plain(observations_by_id[observation_id].permission_scope))
                != node_permission_fingerprint
                for observation_id in supporting_ids
            ):
                raise SourceBackedIdentifierPromptSelectionError(
                    "identifier_node_permission_lineage_mismatch"
                )
            supports.append(
                _IdentifierNodeSupport(
                    term_hash=term_hash,
                    node_id=node_id,
                    node_hash=sha256_json(node_id),
                    support_observation_ids=supporting_ids,
                    support_observation_hashes=tuple(
                        observation_hash_by_id[item] for item in supporting_ids
                    ),
                )
            )
    return tuple(
        sorted(
            supports,
            key=lambda item: (
                item.term_hash,
                item.node_hash,
                item.support_observation_hashes,
            ),
        )
    )


def _select_path_candidate(
    *,
    supports: Sequence[_IdentifierNodeSupport],
    graph: _ValidatedGraph,
    max_hops: int,
) -> _PathCandidate | None:
    supports_by_node_id: dict[str, list[_IdentifierNodeSupport]] = {}
    for support in supports:
        supports_by_node_id.setdefault(support.node_id, []).append(support)
    frozen_supports_by_node_id = {
        node_id: tuple(
            sorted(
                node_supports,
                key=lambda item: (
                    item.term_hash,
                    item.node_hash,
                    item.support_observation_hashes,
                ),
            )
        )
        for node_id, node_supports in supports_by_node_id.items()
    }

    selected: _PathCandidate | None = None
    for edge_id in graph.allowed_edge_ids:
        edge = graph.edges_by_id[edge_id]
        selected = _best_candidate_for_path(
            selected=selected,
            node_ids=(edge.source_node_id, edge.target_node_id),
            edge_ids=(edge.edge_id,),
            supports_by_node_id=frozen_supports_by_node_id,
        )
    if selected is not None or max_hops == 1:
        return selected

    for middle_node_id in sorted(graph.adjacency, key=sha256_json):
        supported_neighbors = tuple(
            (adjacent_node_id, edge_id)
            for adjacent_node_id, edge_id in graph.adjacency[middle_node_id]
            if adjacent_node_id in frozen_supports_by_node_id
        )
        for left_neighbor, right_neighbor in combinations(supported_neighbors, 2):
            left_node_id, left_edge_id = left_neighbor
            right_node_id, right_edge_id = right_neighbor
            if left_node_id == right_node_id or left_edge_id == right_edge_id:
                continue
            selected = _best_candidate_for_path(
                selected=selected,
                node_ids=(left_node_id, middle_node_id, right_node_id),
                edge_ids=(left_edge_id, right_edge_id),
                supports_by_node_id=frozen_supports_by_node_id,
            )
    return selected


def _best_candidate_for_path(
    *,
    selected: _PathCandidate | None,
    node_ids: tuple[str, ...],
    edge_ids: tuple[str, ...],
    supports_by_node_id: Mapping[str, Sequence[_IdentifierNodeSupport]],
) -> _PathCandidate | None:
    left_supports = supports_by_node_id.get(node_ids[0], ())
    right_supports = supports_by_node_id.get(node_ids[-1], ())
    for left in left_supports:
        for right in right_supports:
            if left.term_hash == right.term_hash:
                continue
            candidate_left = left
            candidate_right = right
            candidate_node_ids = node_ids
            candidate_edge_ids = edge_ids
            if right.term_hash < left.term_hash:
                candidate_left, candidate_right = right, left
                candidate_node_ids = tuple(reversed(candidate_node_ids))
                candidate_edge_ids = tuple(reversed(candidate_edge_ids))
            candidate = _PathCandidate(
                left=candidate_left,
                right=candidate_right,
                node_ids=candidate_node_ids,
                edge_ids=candidate_edge_ids,
                node_hashes=tuple(sha256_json(item) for item in candidate_node_ids),
                edge_hashes=tuple(sha256_json(item) for item in candidate_edge_ids),
            )
            if selected is None or _path_candidate_key(candidate) < _path_candidate_key(selected):
                selected = candidate
    return selected


def _path_candidate_key(candidate: _PathCandidate) -> tuple[Any, ...]:
    return (
        candidate.hop_count,
        candidate.left.term_hash,
        candidate.right.term_hash,
        candidate.node_hashes,
        candidate.edge_hashes,
        candidate.left.support_observation_hashes,
        candidate.right.support_observation_hashes,
    )


def _deterministic_occurrence_by_term_hash(
    occurrences: Sequence[_IdentifierOccurrence],
) -> dict[str, _IdentifierOccurrence]:
    selected: dict[str, _IdentifierOccurrence] = {}
    for occurrence in occurrences:
        selected.setdefault(occurrence.term_hash, occurrence)
    return selected


def _minimal_support_observation_ids(
    selected: _PathCandidate,
    *,
    observation_hash_by_id: Mapping[str, str],
) -> dict[str, str]:
    left_ids = set(selected.left.support_observation_ids)
    right_ids = set(selected.right.support_observation_ids)
    common = left_ids & right_ids
    if common:
        shared = min(common, key=lambda item: observation_hash_by_id[item])
        return {
            selected.left.term_hash: shared,
            selected.right.term_hash: shared,
        }
    return {
        selected.left.term_hash: min(
            left_ids,
            key=lambda item: observation_hash_by_id[item],
        ),
        selected.right.term_hash: min(
            right_ids,
            key=lambda item: observation_hash_by_id[item],
        ),
    }


def _selection_session_binding_fingerprint(
    *,
    session: AuthorizedSemanticMailSession,
    observation_hash_by_id: Mapping[str, str],
) -> str:
    return sha256_json(
        {
            "requester_fingerprint": sha256_json(session.requester_user_id),
            "workspace_scope_fingerprint": sha256_json(session.workspace_id),
            "selected_source_scope_hashes": sorted(
                sha256_json(item) for item in session.selected_source_scope_ids
            ),
            "authorized_source_scope_hashes": sorted(
                sha256_json(item) for item in session.authorized_source_scope_ids
            ),
            "authorized_observation_hashes": sorted(observation_hash_by_id.values()),
            "authorized_source_access_fingerprint": (
                session.authorized_source.authorization_fingerprint
                if session.authorized_source is not None
                else None
            ),
            "existing_source_session_binding_fingerprint": (
                session.source_session_binding_fingerprint
            ),
            "index_fingerprint": session.index.index_fingerprint,
        }
    )


def _hash_values(value: Any) -> frozenset[str]:
    if not isinstance(value, (list, tuple)):
        return frozenset()
    return frozenset(
        item
        for item in value
        if isinstance(item, str)
        and len(item) == 71
        and item.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in item[7:])
    )


def _reject_tenant_key(value: Any) -> None:
    if isinstance(value, Mapping):
        if "tenant_id" in value:
            raise SourceBackedIdentifierPromptSelectionError("tenant_dimension_forbidden")
        for item in value.values():
            _reject_tenant_key(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_tenant_key(item)


__all__ = [
    "SELECTION_ALGORITHM_ID",
    "SourceBackedConnectedIdentifierPromptSelection",
    "SourceBackedIdentifierPromptSelectionError",
    "select_source_backed_connected_identifier_prompt",
]
