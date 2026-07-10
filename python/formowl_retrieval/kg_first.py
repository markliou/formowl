from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Protocol, Sequence

from formowl_contract import Grant, Observation, sha256_json, to_plain
from formowl_graph import EffectiveGraphView
from formowl_graph.index import GraphProjectionEdge, GraphProjectionNode, requester_has_graph_access
from formowl_ingestion.storage.interfaces import ObservationRecordStore

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_UNSAFE_TEXT = re.compile(
    r"(^|[^A-Za-z0-9_.-])(/|[A-Za-z]:[\\/]|\\\\|file://|s3://|smb://|nfs://|"
    r"(?:artifacts|cache|data|nas|object_store|objects|scratch|share|srv|tmp|workspace)"
    r"[\\/]+|"
    r"postgres(?:ql)?://|\bselect\b\s+|\bwith\b\s+|\binsert\b\s+|\bupdate\b\s+|"
    r"\bdelete\b\s+|\bdrop\b\s+)",
    re.IGNORECASE,
)
_PUBLIC_LOCATION_KEYS = {
    "attachment_id",
    "block_id",
    "cell_range",
    "end_ms",
    "message_id",
    "occurrence_id",
    "page",
    "page_number",
    "paragraph_index",
    "section",
    "section_id",
    "shape_id",
    "sheet",
    "slide",
    "slide_number",
    "start_ms",
    "table_id",
    "thread_id",
    "timestamp",
}


@dataclass(frozen=True)
class GraphHit:
    graph_object_id: str
    object_type: str
    label: str
    score: float
    confidence: float
    review_state: str
    source_observation_ids: list[str]
    source_asset_ids: list[str]
    permission_scope: dict[str, Any]
    evidence_locators: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class EvidenceContext:
    observation_id: str
    asset_id: str | None
    observation_type: str
    modality: str
    evidence_locator: str
    snippet: str | None
    location: dict[str, Any]
    confidence: float
    permission_scope: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class CandidateGraphProposalSeed:
    proposal_seed_id: str
    query_hash: str
    source_observation_ids: list[str]
    source_asset_ids: list[str]
    status: str = "pending_review"
    requires_review: bool = True
    canonical_write_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


class EvidenceResolver(Protocol):
    def resolve(
        self,
        observation_ids: Sequence[str],
        *,
        requester_user_id: str,
        grants: Sequence[Grant | dict[str, Any]],
        now: str,
    ) -> tuple[list[EvidenceContext], list[str]]: ...


@dataclass
class ObservationStoreEvidenceResolver:
    observation_store: ObservationRecordStore

    def resolve(
        self,
        observation_ids: Sequence[str],
        *,
        requester_user_id: str,
        grants: Sequence[Grant | dict[str, Any]],
        now: str,
    ) -> tuple[list[EvidenceContext], list[str]]:
        resolved: list[EvidenceContext] = []
        unresolved: list[str] = []
        for observation_id in _safe_ids(observation_ids):
            observation = self.observation_store.get(observation_id)
            if observation is None or not requester_has_graph_access(
                to_plain(observation.permission_scope),
                requester_user_id=requester_user_id,
                grants=list(grants),
                now=now,
            ):
                unresolved.append(observation_id)
                continue
            resolved.append(_evidence_context(observation))
        return resolved, unresolved


def match_effective_graph_view(
    view: EffectiveGraphView,
    query_text: str,
    *,
    limit: int,
    score_threshold: float,
) -> list[GraphHit]:
    query_tokens = _tokens(query_text)
    if not query_tokens:
        return []
    hits = [
        hit
        for hit in (
            *(_node_hit(node, query_tokens) for node in view.visible_nodes),
            *(_edge_hit(edge, query_tokens) for edge in view.visible_edges),
        )
        if hit.score >= score_threshold
    ]
    return sorted(hits, key=lambda hit: (-hit.score, -hit.confidence, hit.graph_object_id))[:limit]


def proposal_seeds_from_fallback(
    *,
    query_text: str,
    fallback_records: Sequence[dict[str, Any]],
) -> list[CandidateGraphProposalSeed]:
    query_hash = sha256_json({"query_text": query_text})
    seeds: list[CandidateGraphProposalSeed] = []
    seen: set[tuple[str, ...]] = set()
    for record in fallback_records:
        source_type = str(record.get("source_type") or "")
        source_id = str(record.get("source_id") or "")
        observation_ids = (
            [source_id] if source_type == "observation" and _safe_id(source_id) else []
        )
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        observation_ids.extend(_safe_ids(metadata.get("source_observation_ids", [])))
        observation_ids = sorted(set(observation_ids))
        if not observation_ids or tuple(observation_ids) in seen:
            continue
        seen.add(tuple(observation_ids))
        asset_ids = _safe_ids(metadata.get("source_asset_ids", []))
        asset_id = metadata.get("asset_id")
        if _safe_id(asset_id):
            asset_ids.append(str(asset_id))
        asset_ids = sorted(set(asset_ids))
        seed_id = (
            "proposal_seed_"
            + sha256_json(
                {
                    "query_hash": query_hash,
                    "source_observation_ids": observation_ids,
                    "source_asset_ids": asset_ids,
                }
            ).split(":", 1)[-1][:24]
        )
        seeds.append(
            CandidateGraphProposalSeed(
                proposal_seed_id=seed_id,
                query_hash=query_hash,
                source_observation_ids=observation_ids,
                source_asset_ids=asset_ids,
            )
        )
    return seeds


def _node_hit(node: GraphProjectionNode, query_tokens: set[str]) -> GraphHit:
    properties = node.properties
    label = _label(
        [properties.get("label"), properties.get("summary"), *node.labels],
        node.source_id,
    )
    score = _match_score(
        query_tokens,
        [label, properties.get("summary"), *node.labels, node.source_type, node.source_id],
    )
    return GraphHit(
        graph_object_id=node.node_id,
        object_type=str(properties.get("object_type") or node.source_type),
        label=label,
        score=score,
        confidence=_confidence(properties.get("confidence"), score),
        review_state=str(properties.get("review_state") or node.projection_state),
        source_observation_ids=_safe_ids(properties.get("source_observation_ids", [])),
        source_asset_ids=_safe_ids(properties.get("source_asset_ids", [])),
        permission_scope=to_plain(node.permission_scope),
    )


def _edge_hit(edge: GraphProjectionEdge, query_tokens: set[str]) -> GraphHit:
    properties = edge.properties
    label = _label(
        [properties.get("label"), properties.get("summary"), edge.relation_type],
        edge.relation_type,
    )
    score = _match_score(query_tokens, [label, edge.relation_type])
    return GraphHit(
        graph_object_id=edge.edge_id,
        object_type=str(properties.get("object_type") or "graph_relation"),
        label=label,
        score=score,
        confidence=_confidence(properties.get("confidence"), score),
        review_state=str(properties.get("review_state") or edge.projection_state),
        source_observation_ids=_safe_ids(properties.get("source_observation_ids", [])),
        source_asset_ids=_safe_ids(properties.get("source_asset_ids", [])),
        permission_scope=to_plain(edge.permission_scope),
    )


def _evidence_context(observation: Observation) -> EvidenceContext:
    return EvidenceContext(
        observation_id=observation.observation_id,
        asset_id=observation.asset_id if _safe_id(observation.asset_id) else None,
        observation_type=observation.observation_type,
        modality=observation.modality,
        evidence_locator=f"formowl://observation/{observation.observation_id}",
        snippet=_safe_snippet(observation),
        location=_safe_location(observation.location),
        confidence=observation.confidence,
        permission_scope=to_plain(observation.permission_scope),
    )


def _safe_snippet(observation: Observation) -> str | None:
    for value in (observation.text, observation.caption, observation.extracted_value):
        if isinstance(value, str) and value.strip() and not _UNSAFE_TEXT.search(value):
            return value.strip()
    return None


def _safe_location(location: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in location.items():
        if key not in _PUBLIC_LOCATION_KEYS or not isinstance(value, (str, int, float, bool)):
            continue
        if isinstance(value, str) and _UNSAFE_TEXT.search(value):
            continue
        result[key] = value
    return result


def _match_score(query_tokens: set[str], values: Sequence[Any]) -> float:
    candidate_tokens = _tokens(" ".join(str(value) for value in values if value is not None))
    if not candidate_tokens:
        return 0.0
    overlap = query_tokens & candidate_tokens
    if not overlap:
        return 0.0
    return round(len(overlap) / len(query_tokens), 6)


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN.findall(value)}


def _label(values: Sequence[Any], fallback: str) -> str:
    for value in values:
        if isinstance(value, str) and value.strip() and not _UNSAFE_TEXT.search(value):
            return value.strip()
    return fallback


def _confidence(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    return fallback


def _safe_ids(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    return sorted({str(value) for value in values if _safe_id(value)})


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_SAFE_ID.fullmatch(value))


__all__ = [
    "CandidateGraphProposalSeed",
    "EvidenceContext",
    "EvidenceResolver",
    "GraphHit",
    "ObservationStoreEvidenceResolver",
    "match_effective_graph_view",
    "proposal_seeds_from_fallback",
]
