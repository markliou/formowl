from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence

from formowl_contract import (
    CandidateAtom,
    CandidateRelation,
    CanonicalAtom,
    CanonicalEntity,
    CanonicalGraphRevision,
    CanonicalRelation,
    ContractValidationError,
    SourceRef,
    now_iso,
    sha256_json,
    stable_canonical_atom_id,
    stable_canonical_graph_revision_id,
    stable_canonical_relation_id,
    to_plain,
)

from .storage import CandidateAtomStore, CandidateRelationStore, CanonicalGraphStore

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RAW_PUBLIC_REFERENCE_PATTERNS = (
    re.compile(r"(^|[^A-Za-z])[A-Za-z]:[\\/]"),
    re.compile(r"(^|[\s'\"])/(srv|home|tmp|var|mnt|opt|root)/", re.IGNORECASE),
    re.compile(r"\b(?!https?://)[A-Za-z][A-Za-z0-9+.-]*://", re.IGNORECASE),
    re.compile(r"\b(file|smb|nfs|postgres|postgresql|mysql|sqlite)://", re.IGNORECASE),
    re.compile(r"\bformowl://(asset|object|storage|worker|evidence)\b", re.IGNORECASE),
    re.compile(r"\b(select|with|copy|insert|update|delete|drop|alter)\b\s+", re.IGNORECASE),
)


@dataclass(frozen=True)
class CanonicalCommitPolicyPins:
    extraction_policy_id: str
    granularity_policy_id: str
    entity_resolution_policy_id: str
    relation_resolution_policy_id: str
    lifecycle_policy_id: str

    def policy_ids(self) -> list[str]:
        values = [
            self.extraction_policy_id,
            self.granularity_policy_id,
            self.entity_resolution_policy_id,
            self.relation_resolution_policy_id,
            self.lifecycle_policy_id,
        ]
        for value in values:
            _validate_record_id(value, "policy_id")
        if len(set(values)) != len(values):
            raise ContractValidationError("canonical commit policy pins must be unique")
        return values


@dataclass(frozen=True)
class CanonicalCommitResult:
    canonical_atoms: list[CanonicalAtom] = field(default_factory=list)
    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    canonical_relations: list[CanonicalRelation] = field(default_factory=list)
    canonical_graph_revision: CanonicalGraphRevision | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.canonical_graph_revision is None:
            raise ContractValidationError("canonical commit result requires a graph revision")
        return {
            "canonical_atoms": [atom.to_dict() for atom in self.canonical_atoms],
            "canonical_entities": [entity.to_dict() for entity in self.canonical_entities],
            "canonical_relations": [relation.to_dict() for relation in self.canonical_relations],
            "canonical_graph_revision": self.canonical_graph_revision.to_dict(),
        }


def commit_reviewed_candidates_to_canonical_graph(
    *,
    candidate_atom_store: CandidateAtomStore,
    canonical_graph_store: CanonicalGraphStore,
    scope_type: str,
    scope_id: str,
    ontology_revision_id: str,
    created_by: str,
    policy_pins: CanonicalCommitPolicyPins,
    candidate_atom_ids: Sequence[str],
    candidate_relation_store: CandidateRelationStore | None = None,
    candidate_relation_ids: Sequence[str] = (),
    source_refs_by_candidate_id: Mapping[str, Sequence[dict[str, Any] | SourceRef]] | None = None,
    evidence_snapshot_ids_by_candidate_id: Mapping[str, Sequence[str]] | None = None,
    citations_by_candidate_id: Mapping[str, Sequence[dict[str, Any]]] | None = None,
    created_at: str | None = None,
    parent_revision_id: str | None = None,
    review_decision_ids: Sequence[str] = (),
    commit_metadata: Mapping[str, Any] | None = None,
) -> CanonicalCommitResult:
    """Commit approved candidate graph records through the governed backend path."""

    created_at = created_at or now_iso()
    atom_ids = _validate_id_sequence(candidate_atom_ids, "candidate_atom_ids", allow_empty=False)
    relation_ids = _validate_id_sequence(
        candidate_relation_ids,
        "candidate_relation_ids",
        allow_empty=True,
    )
    review_ids = _validate_id_sequence(
        review_decision_ids,
        "review_decision_ids",
        allow_empty=False,
    )
    _validate_record_id(scope_type, "scope_type")
    _validate_record_id(scope_id, "scope_id")
    _validate_record_id(ontology_revision_id, "ontology_revision_id")
    _validate_record_id(created_by, "created_by")
    if parent_revision_id is not None:
        _validate_record_id(parent_revision_id, "parent_revision_id")
    policy_ids = policy_pins.policy_ids()

    metadata = {
        "workflow": "reviewed_canonical_graph_commit_v1",
        "review_decision_ids": review_ids,
        "committed_by": created_by,
        **dict(commit_metadata or {}),
    }
    _validate_no_raw_public_reference(metadata, "canonical commit metadata")

    atom_lineage = _lineage_mapping(source_refs_by_candidate_id)
    evidence_lineage = _id_lineage_mapping(evidence_snapshot_ids_by_candidate_id)
    citation_lineage = _citation_mapping(citations_by_candidate_id)
    known_candidate_ids = set(atom_ids) | set(relation_ids)
    _validate_lineage_keys(atom_lineage, known_candidate_ids)
    _validate_lineage_keys(evidence_lineage, known_candidate_ids)
    _validate_lineage_keys(citation_lineage, known_candidate_ids)

    candidate_atoms = [_load_approved_atom(candidate_atom_store, atom_id) for atom_id in atom_ids]
    candidate_relations = [
        _load_approved_relation(candidate_relation_store, relation_id)
        for relation_id in relation_ids
    ]
    _validate_no_raw_public_reference(
        [atom.to_dict() for atom in candidate_atoms],
        "approved candidate atoms",
    )
    _validate_no_raw_public_reference(
        [relation.to_dict() for relation in candidate_relations],
        "approved candidate relations",
    )

    canonical_atoms = [
        _canonical_atom_from_candidate(
            candidate,
            scope_type=scope_type,
            scope_id=scope_id,
            ontology_revision_id=ontology_revision_id,
            policy_pins=policy_pins,
            created_at=created_at,
            source_refs=atom_lineage.get(
                candidate.candidate_atom_id,
                [_default_candidate_source_ref(candidate.candidate_atom_id, "candidate_atom")],
            ),
            evidence_snapshot_ids=evidence_lineage.get(candidate.candidate_atom_id, []),
            citations=citation_lineage.get(candidate.candidate_atom_id, []),
            review_decision_ids=review_ids,
        )
        for candidate in candidate_atoms
    ]
    atom_id_by_candidate_id = {
        candidate.candidate_atom_id: canonical_atom.canonical_atom_id
        for candidate, canonical_atom in zip(candidate_atoms, canonical_atoms, strict=True)
    }

    canonical_relations = [
        _canonical_relation_from_candidate(
            relation,
            scope_type=scope_type,
            scope_id=scope_id,
            ontology_revision_id=ontology_revision_id,
            created_at=created_at,
            atom_id_by_candidate_id=atom_id_by_candidate_id,
            source_refs=atom_lineage.get(
                relation.candidate_relation_id,
                [
                    _default_candidate_source_ref(
                        relation.candidate_relation_id,
                        "candidate_relation",
                    )
                ],
            ),
            evidence_snapshot_ids=evidence_lineage.get(relation.candidate_relation_id, []),
            citations=citation_lineage.get(relation.candidate_relation_id, []),
            review_decision_ids=review_ids,
        )
        for relation in candidate_relations
    ]
    _validate_unique_canonical_ids(
        [atom.canonical_atom_id for atom in canonical_atoms],
        "canonical atom ids",
    )
    _validate_unique_canonical_ids(
        [relation.canonical_relation_id for relation in canonical_relations],
        "canonical relation ids",
    )

    revision = CanonicalGraphRevision.from_dict(
        {
            "canonical_graph_revision_id": stable_canonical_graph_revision_id(
                scope_type=scope_type,
                scope_id=scope_id,
                ontology_revision_id=ontology_revision_id,
                canonical_atom_ids=sorted(atom.canonical_atom_id for atom in canonical_atoms),
                canonical_entity_ids=[],
                canonical_relation_ids=sorted(
                    relation.canonical_relation_id for relation in canonical_relations
                ),
                created_at=created_at,
                parent_revision_id=parent_revision_id,
            ),
            "scope_type": scope_type,
            "scope_id": scope_id,
            "ontology_revision_id": ontology_revision_id,
            "status": "committed",
            "canonical_atom_ids": sorted(atom.canonical_atom_id for atom in canonical_atoms),
            "canonical_entity_ids": [],
            "canonical_relation_ids": sorted(
                relation.canonical_relation_id for relation in canonical_relations
            ),
            "created_at": created_at,
            "created_by": created_by,
            "parent_revision_id": parent_revision_id,
            "source_candidate_atom_ids": atom_ids,
            "source_candidate_relation_ids": relation_ids,
            "policy_ids": policy_ids,
            "commit_metadata": metadata,
        }
    )

    result = CanonicalCommitResult(
        canonical_atoms=canonical_atoms,
        canonical_entities=[],
        canonical_relations=canonical_relations,
        canonical_graph_revision=revision,
    )
    _validate_no_raw_public_reference(result.to_dict(), "canonical commit result")
    canonical_graph_store._persist_reviewed_commit(
        atoms=canonical_atoms,
        entities=[],
        relations=canonical_relations,
        revision=revision,
    )
    return result


def _canonical_atom_from_candidate(
    candidate: CandidateAtom,
    *,
    scope_type: str,
    scope_id: str,
    ontology_revision_id: str,
    policy_pins: CanonicalCommitPolicyPins,
    created_at: str,
    source_refs: Sequence[dict[str, Any] | SourceRef],
    evidence_snapshot_ids: Sequence[str],
    citations: Sequence[dict[str, Any]],
    review_decision_ids: Sequence[str],
) -> CanonicalAtom:
    source_candidate_atom_ids = [candidate.candidate_atom_id]
    canonical_atom_id = stable_canonical_atom_id(
        scope_type=scope_type,
        scope_id=scope_id,
        atom_type=candidate.atom_type,
        canonical_text=candidate.label,
        source_candidate_atom_ids=source_candidate_atom_ids,
    )
    return CanonicalAtom.from_dict(
        {
            "canonical_atom_id": canonical_atom_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "atom_type": candidate.atom_type,
            "canonical_text": candidate.label,
            "granularity_level": _granularity_level(candidate),
            "status": "active",
            "source_candidate_atom_ids": source_candidate_atom_ids,
            "source_observation_ids": list(candidate.source_observation_ids),
            "source_refs": [to_plain(item) for item in source_refs],
            "evidence_snapshot_ids": list(evidence_snapshot_ids),
            "citations": [to_plain(item) for item in citations],
            "content_hash": sha256_json(
                {
                    "canonical_text": candidate.label,
                    "source_candidate_atom_ids": source_candidate_atom_ids,
                    "source_observation_ids": list(candidate.source_observation_ids),
                }
            ),
            "extraction_policy_id": policy_pins.extraction_policy_id,
            "granularity_policy_id": policy_pins.granularity_policy_id,
            "confidence": candidate.confidence,
            "created_at": created_at,
            "labels": [candidate.label],
            "metadata": {
                "ontology_revision_id": ontology_revision_id,
                "source_candidate_status": candidate.status,
                "source_extractor_run_id": candidate.extractor_run_id,
                "source_semantic_metadata_ids": list(candidate.source_semantic_metadata_ids),
                "review_decision_ids": list(review_decision_ids),
                "candidate_properties": to_plain(candidate.properties),
            },
        }
    )


def _canonical_relation_from_candidate(
    relation: CandidateRelation,
    *,
    scope_type: str,
    scope_id: str,
    ontology_revision_id: str,
    created_at: str,
    atom_id_by_candidate_id: Mapping[str, str],
    source_refs: Sequence[dict[str, Any] | SourceRef],
    evidence_snapshot_ids: Sequence[str],
    citations: Sequence[dict[str, Any]],
    review_decision_ids: Sequence[str],
) -> CanonicalRelation:
    try:
        source_id = atom_id_by_candidate_id[relation.source_candidate_atom_id]
        target_id = atom_id_by_candidate_id[relation.target_candidate_atom_id]
    except KeyError as exc:
        raise ContractValidationError("canonical relation endpoints must resolve") from exc
    return CanonicalRelation.from_dict(
        {
            "canonical_relation_id": stable_canonical_relation_id(
                scope_type=scope_type,
                scope_id=scope_id,
                source_id=source_id,
                target_id=target_id,
                relation_type=relation.relation_type,
                properties=relation.properties,
            ),
            "scope_type": scope_type,
            "scope_id": scope_id,
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation.relation_type,
            "status": "active",
            "source_candidate_relation_ids": [relation.candidate_relation_id],
            "source_observation_ids": list(relation.source_observation_ids),
            "source_refs": [to_plain(item) for item in source_refs],
            "evidence_snapshot_ids": list(evidence_snapshot_ids),
            "citations": [to_plain(item) for item in citations],
            "confidence": relation.confidence,
            "ontology_revision_id": ontology_revision_id,
            "created_at": created_at,
            "properties": {
                **dict(relation.properties),
                "review_decision_ids": list(review_decision_ids),
                "source_extractor_run_id": relation.extractor_run_id,
                "source_semantic_metadata_ids": list(relation.source_semantic_metadata_ids),
            },
        }
    )


def _load_approved_atom(store: CandidateAtomStore, candidate_atom_id: str) -> CandidateAtom:
    candidate = store.get(candidate_atom_id)
    if candidate is None:
        raise ContractValidationError("candidate atom is missing")
    if candidate.status != "approved":
        raise ContractValidationError("candidate atom is not approved for canonical commit")
    return candidate


def _load_approved_relation(
    store: CandidateRelationStore | None,
    candidate_relation_id: str,
) -> CandidateRelation:
    if store is None:
        raise ContractValidationError("candidate relation store is required")
    relation = store.get(candidate_relation_id)
    if relation is None:
        raise ContractValidationError("candidate relation is missing")
    if relation.status != "approved":
        raise ContractValidationError("candidate relation is not approved for canonical commit")
    return relation


def _granularity_level(candidate: CandidateAtom) -> str:
    value = candidate.properties.get("granularity_level", candidate.atom_type)
    if isinstance(value, str) and value:
        _validate_record_id(value, "granularity_level")
        return value
    return candidate.atom_type


def _default_candidate_source_ref(candidate_id: str, source_type: str) -> dict[str, Any]:
    return SourceRef(
        source_system="formowl_candidate_graph",
        source_type=source_type,
        source_id=candidate_id,
    ).to_dict()


def _lineage_mapping(
    value: Mapping[str, Sequence[dict[str, Any] | SourceRef]] | None,
) -> dict[str, list[dict[str, Any] | SourceRef]]:
    result: dict[str, list[dict[str, Any] | SourceRef]] = {}
    for key, refs in dict(value or {}).items():
        _validate_record_id(key, "lineage candidate id")
        if isinstance(refs, (str, bytes)) or not isinstance(refs, Sequence):
            raise ContractValidationError("source refs lineage must be sequences")
        for ref in refs:
            SourceRef.from_dict(to_plain(ref))
        result[key] = list(refs)
    _validate_no_raw_public_reference(to_plain(result), "source refs lineage")
    return result


def _id_lineage_mapping(value: Mapping[str, Sequence[str]] | None) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, ids in dict(value or {}).items():
        _validate_record_id(key, "lineage candidate id")
        result[key] = _validate_id_sequence(ids, "lineage ids", allow_empty=True)
    return result


def _citation_mapping(
    value: Mapping[str, Sequence[dict[str, Any]]] | None,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for key, citations in dict(value or {}).items():
        _validate_record_id(key, "lineage candidate id")
        if isinstance(citations, (str, bytes)) or not isinstance(citations, Sequence):
            raise ContractValidationError("citation lineage must be sequences")
        result[key] = [dict(citation) for citation in citations]
    _validate_no_raw_public_reference(result, "citation lineage")
    return result


def _validate_lineage_keys(
    value: Mapping[str, Sequence[Any]],
    known_candidate_ids: set[str],
) -> None:
    if set(value) - known_candidate_ids:
        raise ContractValidationError("lineage references unknown candidates")


def _validate_unique_canonical_ids(values: Sequence[str], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ContractValidationError(f"{field_name} would overwrite canonical lineage")


def _validate_id_sequence(
    value: Sequence[str],
    field_name: str,
    *,
    allow_empty: bool,
) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractValidationError(f"{field_name} must be a sequence")
    ids = list(value)
    if not allow_empty and not ids:
        raise ContractValidationError(f"{field_name} cannot be empty")
    for item in ids:
        _validate_record_id(item, f"{field_name} entry")
    if len(set(ids)) != len(ids):
        raise ContractValidationError(f"{field_name} entries must be unique")
    return ids


def _validate_record_id(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value or not _SAFE_RECORD_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a stable record id")


def _validate_no_raw_public_reference(value: Any, field_name: str) -> None:
    if isinstance(value, str):
        for pattern in _RAW_PUBLIC_REFERENCE_PATTERNS:
            if pattern.search(value):
                raise ContractValidationError(f"{field_name} must not contain raw references")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_no_raw_public_reference(str(key), field_name)
            _validate_no_raw_public_reference(item, field_name)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _validate_no_raw_public_reference(item, field_name)


__all__ = [
    "CanonicalCommitPolicyPins",
    "CanonicalCommitResult",
    "commit_reviewed_candidates_to_canonical_graph",
]
