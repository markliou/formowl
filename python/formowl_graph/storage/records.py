from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable, Generic, TypeVar

from formowl_contract import (
    CandidateAtom,
    CandidateBusinessObject,
    CandidateFrame,
    CandidateMention,
    CandidateRelation,
    CanonicalAtom,
    CanonicalEntity,
    CanonicalGraphRevision,
    CanonicalRelation,
    ContractValidationError,
    SemanticMetadata,
    to_plain,
)

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
T = TypeVar("T")


class _JsonGraphRecordStore(Generic[T]):
    def __init__(
        self,
        base_dir: str | Path,
        *,
        collection: str,
        id_field: str,
        factory: Callable[[dict[str, Any]], T],
        serializer: Callable[[T], dict[str, Any]],
    ) -> None:
        # Graph stores in this module are proposal/intermediate stores only.
        # Canonical graph collections must be introduced behind their own review
        # workflow, not as a side effect of writing candidate records.
        self.base_dir = Path(base_dir) / "graph" / collection
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.id_field = id_field
        self.factory = factory
        self.serializer = serializer

    def create(self, record: T | dict[str, Any]) -> T:
        validated = self._validate(record)
        payload = self.serializer(validated)
        record_id = str(payload[self.id_field])
        _write_json(self._record_path(record_id), payload)
        return validated

    def get(self, record_id: str) -> T | None:
        path = self._record_path(record_id)
        if not path.exists():
            return None
        return self.factory(_read_json(path))

    def list(self) -> list[T]:
        return [self.factory(_read_json(path)) for path in sorted(self.base_dir.glob("*.json"))]

    def validate_record_id(self, record_id: str) -> None:
        self._record_path(record_id)

    def _validate(self, record: T | dict[str, Any]) -> T:
        if isinstance(record, dict):
            return self.factory(record)
        return self.factory(self.serializer(record))

    def _record_path(self, record_id: str) -> Path:
        if not record_id or not _SAFE_RECORD_ID.fullmatch(record_id):
            raise ValueError(f"{self.id_field} must be a safe file name")
        return self.base_dir / f"{record_id}.json"


class SemanticMetadataStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonGraphRecordStore[SemanticMetadata](
            base_dir,
            collection="semantic-metadata",
            id_field="semantic_metadata_id",
            factory=SemanticMetadata.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(self, semantic_metadata: SemanticMetadata | dict[str, Any]) -> SemanticMetadata:
        return self._store.create(semantic_metadata)

    def get(self, semantic_metadata_id: str) -> SemanticMetadata | None:
        return self._store.get(semantic_metadata_id)

    def list(self) -> list[SemanticMetadata]:
        return self._store.list()

    def validate_semantic_metadata_id(self, semantic_metadata_id: str) -> None:
        self._store.validate_record_id(semantic_metadata_id)


class CandidateAtomStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonGraphRecordStore[CandidateAtom](
            base_dir,
            collection="candidate-atoms",
            id_field="candidate_atom_id",
            factory=CandidateAtom.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(self, candidate_atom: CandidateAtom | dict[str, Any]) -> CandidateAtom:
        return self._store.create(candidate_atom)

    def get(self, candidate_atom_id: str) -> CandidateAtom | None:
        return self._store.get(candidate_atom_id)

    def list(self) -> list[CandidateAtom]:
        return self._store.list()

    def validate_candidate_atom_id(self, candidate_atom_id: str) -> None:
        self._store.validate_record_id(candidate_atom_id)


class CandidateRelationStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonGraphRecordStore[CandidateRelation](
            base_dir,
            collection="candidate-relations",
            id_field="candidate_relation_id",
            factory=CandidateRelation.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(
        self,
        candidate_relation: CandidateRelation | dict[str, Any],
    ) -> CandidateRelation:
        return self._store.create(candidate_relation)

    def get(self, candidate_relation_id: str) -> CandidateRelation | None:
        return self._store.get(candidate_relation_id)

    def list(self) -> list[CandidateRelation]:
        return self._store.list()

    def validate_candidate_relation_id(self, candidate_relation_id: str) -> None:
        self._store.validate_record_id(candidate_relation_id)


class CandidateMentionStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonGraphRecordStore[CandidateMention](
            base_dir,
            collection="candidate-mentions",
            id_field="candidate_mention_id",
            factory=CandidateMention.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(self, candidate_mention: CandidateMention | dict[str, Any]) -> CandidateMention:
        return self._store.create(candidate_mention)

    def get(self, candidate_mention_id: str) -> CandidateMention | None:
        return self._store.get(candidate_mention_id)

    def list(self) -> list[CandidateMention]:
        return self._store.list()

    def validate_candidate_mention_id(self, candidate_mention_id: str) -> None:
        self._store.validate_record_id(candidate_mention_id)


class CandidateBusinessObjectStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonGraphRecordStore[CandidateBusinessObject](
            base_dir,
            collection="candidate-business-objects",
            id_field="candidate_business_object_id",
            factory=CandidateBusinessObject.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(
        self,
        candidate_business_object: CandidateBusinessObject | dict[str, Any],
    ) -> CandidateBusinessObject:
        return self._store.create(candidate_business_object)

    def get(self, candidate_business_object_id: str) -> CandidateBusinessObject | None:
        return self._store.get(candidate_business_object_id)

    def list(self) -> list[CandidateBusinessObject]:
        return self._store.list()

    def validate_candidate_business_object_id(self, candidate_business_object_id: str) -> None:
        self._store.validate_record_id(candidate_business_object_id)


class CandidateFrameStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonGraphRecordStore[CandidateFrame](
            base_dir,
            collection="candidate-frames",
            id_field="candidate_frame_id",
            factory=CandidateFrame.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(self, candidate_frame: CandidateFrame | dict[str, Any]) -> CandidateFrame:
        return self._store.create(candidate_frame)

    def get(self, candidate_frame_id: str) -> CandidateFrame | None:
        return self._store.get(candidate_frame_id)

    def list(self) -> list[CandidateFrame]:
        return self._store.list()

    def validate_candidate_frame_id(self, candidate_frame_id: str) -> None:
        self._store.validate_record_id(candidate_frame_id)


class CanonicalGraphStore:
    """File-backed canonical graph store behind the reviewed commit workflow.

    The public surface intentionally has no generic ``create`` methods. Canonical
    records are persisted through ``formowl_graph.canonical`` after review and
    policy validation.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._atom_store = _JsonGraphRecordStore[CanonicalAtom](
            base_dir,
            collection="canonical-atoms",
            id_field="canonical_atom_id",
            factory=CanonicalAtom.from_dict,
            serializer=lambda value: value.to_dict(),
        )
        self._entity_store = _JsonGraphRecordStore[CanonicalEntity](
            base_dir,
            collection="canonical-entities",
            id_field="canonical_entity_id",
            factory=CanonicalEntity.from_dict,
            serializer=lambda value: value.to_dict(),
        )
        self._relation_store = _JsonGraphRecordStore[CanonicalRelation](
            base_dir,
            collection="canonical-relations",
            id_field="canonical_relation_id",
            factory=CanonicalRelation.from_dict,
            serializer=lambda value: value.to_dict(),
        )
        self._revision_store = _JsonGraphRecordStore[CanonicalGraphRevision](
            base_dir,
            collection="canonical-graph-revisions",
            id_field="canonical_graph_revision_id",
            factory=CanonicalGraphRevision.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def get_atom(self, canonical_atom_id: str) -> CanonicalAtom | None:
        return self._atom_store.get(canonical_atom_id)

    def list_atoms(self) -> list[CanonicalAtom]:
        return self._atom_store.list()

    def get_entity(self, canonical_entity_id: str) -> CanonicalEntity | None:
        return self._entity_store.get(canonical_entity_id)

    def list_entities(self) -> list[CanonicalEntity]:
        return self._entity_store.list()

    def get_relation(self, canonical_relation_id: str) -> CanonicalRelation | None:
        return self._relation_store.get(canonical_relation_id)

    def list_relations(self) -> list[CanonicalRelation]:
        return self._relation_store.list()

    def get_revision(self, canonical_graph_revision_id: str) -> CanonicalGraphRevision | None:
        return self._revision_store.get(canonical_graph_revision_id)

    def list_revisions(self) -> list[CanonicalGraphRevision]:
        return self._revision_store.list()

    def _persist_reviewed_commit(
        self,
        *,
        atoms: list[CanonicalAtom],
        entities: list[CanonicalEntity],
        relations: list[CanonicalRelation],
        revision: CanonicalGraphRevision,
    ) -> None:
        prepared: list[tuple[Path, dict[str, Any], bytes | None]] = []
        for store, records in (
            (self._atom_store, atoms),
            (self._entity_store, entities),
            (self._relation_store, relations),
            (self._revision_store, [revision]),
        ):
            for record in records:
                # Validate the full contract and safe record path before writing
                # anything, so governance failures do not leave partial commits.
                validated = store._validate(record)
                payload = store.serializer(validated)
                path = store._record_path(str(payload[store.id_field]))
                original = path.read_bytes() if path.exists() else None
                if original is not None and json.loads(original.decode("utf-8")) != to_plain(
                    payload
                ):
                    raise ContractValidationError(
                        "canonical record already exists with different lineage"
                    )
                prepared.append((path, payload, original))

        written: list[tuple[Path, bytes | None]] = []
        try:
            for path, payload, original in prepared:
                _write_json(path, payload)
                written.append((path, original))
        except Exception:
            for path, original in reversed(written):
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(original)
            raise


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(to_plain(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)
