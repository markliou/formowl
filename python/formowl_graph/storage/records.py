from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable, Generic, TypeVar

from formowl_contract import CandidateAtom, CandidateRelation, SemanticMetadata, to_plain

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
