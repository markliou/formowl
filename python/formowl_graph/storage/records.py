from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable, Generic, Iterable, Sequence, TypeVar

from formowl_contract import (
    CandidateAssertion,
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
    Observation,
    SemanticMetadata,
    stable_candidate_assertion_id,
    stable_candidate_business_object_id,
    parse_temporal_value,
    to_plain,
)
from formowl_core import read_json_object, write_json_atomic

from ..domain_packs import DomainPackDefinition, validate_domain_pack_provenance

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
T = TypeVar("T")
_write_json = write_json_atomic


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
        return self.factory(read_json_object(path))

    def list(self) -> list[T]:
        return [
            self.factory(read_json_object(path)) for path in sorted(self.base_dir.glob("*.json"))
        ]

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


class CandidateAssertionStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonGraphRecordStore[CandidateAssertion](
            base_dir,
            collection="candidate-assertions",
            id_field="candidate_assertion_id",
            factory=CandidateAssertion.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(
        self,
        candidate_assertion: CandidateAssertion | dict[str, Any],
    ) -> CandidateAssertion:
        validated = self._store._validate(candidate_assertion)
        _persist_record_batch(
            ((self._store, [validated]),),
            conflict_message="candidate assertion already exists with different content",
        )
        return validated

    def get(self, candidate_assertion_id: str) -> CandidateAssertion | None:
        return self._store.get(candidate_assertion_id)

    def list(self) -> list[CandidateAssertion]:
        return self._store.list()

    def validate_candidate_assertion_id(self, candidate_assertion_id: str) -> None:
        self._store.validate_record_id(candidate_assertion_id)


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
        validated = self._store._validate(candidate_business_object)
        _persist_record_batch(
            ((self._store, [validated]),),
            conflict_message="candidate business object already exists with different content",
        )
        return validated

    def get(self, candidate_business_object_id: str) -> CandidateBusinessObject | None:
        return self._store.get(candidate_business_object_id)

    def list(self) -> list[CandidateBusinessObject]:
        return self._store.list()

    def validate_candidate_business_object_id(self, candidate_business_object_id: str) -> None:
        self._store.validate_record_id(candidate_business_object_id)


class DomainPackStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonGraphRecordStore[DomainPackDefinition](
            base_dir,
            collection="domain-packs",
            id_field="pack_id",
            factory=DomainPackDefinition.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(self, domain_pack: DomainPackDefinition | dict[str, Any]) -> DomainPackDefinition:
        validated = self._store._validate(domain_pack)
        _persist_record_batch(
            ((self._store, [validated]),),
            conflict_message="Domain Pack already exists with different content",
        )
        return validated

    def get(self, pack_id: str) -> DomainPackDefinition | None:
        return self._store.get(pack_id)

    def list(self) -> list[DomainPackDefinition]:
        return self._store.list()

    def validate_pack_id(self, pack_id: str) -> None:
        self._store.validate_record_id(pack_id)


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


def persist_candidate_knowledge_batch(
    *,
    domain_pack_store: DomainPackStore,
    candidate_business_object_store: CandidateBusinessObjectStore,
    candidate_assertion_store: CandidateAssertionStore,
    domain_pack: DomainPackDefinition,
    observations: Sequence[Observation],
    extractor_run_id: str,
    candidate_business_objects: list[CandidateBusinessObject],
    candidate_assertions: list[CandidateAssertion],
) -> None:
    """Persist one candidate-knowledge extraction as an all-or-nothing batch."""

    validated_pack = DomainPackDefinition.from_dict(domain_pack.to_dict())
    validated_observations = [
        Observation.from_dict(observation.to_dict()) for observation in observations
    ]
    validate_domain_pack_provenance(validated_pack, validated_observations)
    observation_by_id = {
        observation.observation_id: observation for observation in validated_observations
    }
    _validate_unique_candidate_ids(
        (candidate.candidate_business_object_id for candidate in candidate_business_objects),
        "candidate business object ids must be unique per extraction",
    )
    _validate_unique_candidate_ids(
        (assertion.candidate_assertion_id for assertion in candidate_assertions),
        "candidate assertion ids must be unique per extraction",
    )
    valid_assertion_targets = {
        (
            mapping["assertion_kind"],
            mapping["predicate"],
            mapping["epistemic_status"],
            mapping["lifecycle_status"],
        )
        for mapping in validated_pack.assertion_mappings.values()
    }
    candidate_business_object_by_id = {
        candidate.candidate_business_object_id: candidate
        for candidate in candidate_business_objects
    }
    candidate_business_object_ids = set(candidate_business_object_by_id)
    for candidate in candidate_business_objects:
        metadata = candidate.metadata
        if (
            metadata.get("domain_pack_id") != validated_pack.pack_id
            or metadata.get("domain_pack_content_hash") != validated_pack.content_hash
            or metadata.get("ontology_revision_id") != validated_pack.ontology_revision_id
            or candidate.object_supertype
            != validated_pack.resolve_core_supertype(candidate.object_type)
        ):
            raise ContractValidationError(
                "candidate business object lineage does not match the supplied Domain Pack"
            )
        _validate_candidate_review_state(
            status=candidate.status,
            requires_review=candidate.requires_review,
            metadata=metadata,
            record_name="candidate business object",
        )
        if candidate.extractor_run_id != extractor_run_id:
            raise ContractValidationError(
                "candidate business object extractor run does not match the extraction batch"
            )
        expected_candidate_id = stable_candidate_business_object_id(
            source_observation_ids=candidate.source_observation_ids,
            object_type=candidate.object_type,
            label=candidate.label,
            properties=candidate.properties,
            extractor_run_id=candidate.extractor_run_id,
            object_supertype=candidate.object_supertype,
            ontology_revision_id=validated_pack.ontology_revision_id,
            domain_pack_id=validated_pack.pack_id,
            domain_pack_content_hash=validated_pack.content_hash,
        )
        if candidate.candidate_business_object_id != expected_candidate_id:
            raise ContractValidationError(
                "candidate business object id does not match its stable lineage"
            )
        _validate_candidate_source_lineage(
            source_observation_ids=candidate.source_observation_ids,
            observation_by_id=observation_by_id,
            expected_permission_scope=candidate.access_boundary["permission_scope"],
            record_name="candidate business object",
        )
    for assertion in candidate_assertions:
        if (
            assertion.domain_pack_id != validated_pack.pack_id
            or assertion.domain_pack_content_hash != validated_pack.content_hash
            or assertion.ontology_revision_id != validated_pack.ontology_revision_id
            or (
                assertion.assertion_kind,
                assertion.predicate,
                assertion.epistemic_status,
                assertion.lifecycle_status,
            )
            not in valid_assertion_targets
        ):
            raise ContractValidationError(
                "candidate assertion lineage does not match the supplied Domain Pack"
            )
        _validate_candidate_review_state(
            status=assertion.status,
            requires_review=assertion.requires_review,
            metadata=assertion.metadata,
            record_name="candidate assertion",
        )
        if assertion.extractor_run_id != extractor_run_id:
            raise ContractValidationError(
                "candidate assertion extractor run does not match the extraction batch"
            )
        expected_assertion_id = stable_candidate_assertion_id(
            source_observation_ids=assertion.source_observation_ids,
            assertion_kind=assertion.assertion_kind,
            subject_candidate_business_object_id=(assertion.subject_candidate_business_object_id),
            predicate=assertion.predicate,
            object_candidate_business_object_id=(assertion.object_candidate_business_object_id),
            actor_candidate_business_object_id=(assertion.actor_candidate_business_object_id),
            counterparty_candidate_business_object_id=(
                assertion.counterparty_candidate_business_object_id
            ),
            value=assertion.value,
            previous_value=assertion.previous_value,
            proposed_value=assertion.proposed_value,
            temporal_context=assertion.temporal_context,
            context=assertion.context,
            epistemic_status=assertion.epistemic_status,
            lifecycle_status=assertion.lifecycle_status,
            extractor_run_id=assertion.extractor_run_id,
            ontology_revision_id=validated_pack.ontology_revision_id,
            domain_pack_id=validated_pack.pack_id,
            domain_pack_content_hash=validated_pack.content_hash,
        )
        if assertion.candidate_assertion_id != expected_assertion_id:
            raise ContractValidationError(
                "candidate assertion id does not match its stable lineage"
            )
        _validate_candidate_source_lineage(
            source_observation_ids=assertion.source_observation_ids,
            observation_by_id=observation_by_id,
            expected_permission_scope=assertion.permission_scope,
            record_name="candidate assertion",
        )
        expected_captured_at = max(
            (
                observation_by_id[observation_id].created_at
                for observation_id in assertion.source_observation_ids
            ),
            key=parse_temporal_value,
        )
        if assertion.temporal_context.get("captured_at") != expected_captured_at:
            raise ContractValidationError(
                "candidate assertion captured_at does not match source observations"
            )
        referenced_object_ids = {
            reference
            for reference in (
                assertion.subject_candidate_business_object_id,
                assertion.object_candidate_business_object_id,
                assertion.actor_candidate_business_object_id,
                assertion.counterparty_candidate_business_object_id,
            )
            if reference is not None
        }
        if not referenced_object_ids.issubset(candidate_business_object_ids):
            raise ContractValidationError(
                "candidate assertion references a business object outside the extraction batch"
            )
        assertion_permission_scope = to_plain(assertion.permission_scope)
        assertion_source_observation_ids = set(assertion.source_observation_ids)
        for referenced_object_id in referenced_object_ids:
            participant = candidate_business_object_by_id[referenced_object_id]
            if (
                to_plain(participant.access_boundary["permission_scope"])
                != assertion_permission_scope
            ):
                raise ContractValidationError(
                    "candidate assertion participant permission scope must match the assertion"
                )
            if not set(participant.source_observation_ids).issubset(
                assertion_source_observation_ids
            ):
                raise ContractValidationError(
                    "candidate assertion must include every participant source observation"
                )
    _persist_record_batch(
        (
            (domain_pack_store._store, [validated_pack]),
            (candidate_business_object_store._store, candidate_business_objects),
            (candidate_assertion_store._store, candidate_assertions),
        ),
        conflict_message="candidate record already exists with different lineage",
    )


def _validate_unique_candidate_ids(
    record_ids: Iterable[str],
    message: str,
) -> None:
    ordered_ids = list(record_ids)
    if len(set(ordered_ids)) != len(ordered_ids):
        raise ContractValidationError(message)


def _validate_candidate_source_lineage(
    *,
    source_observation_ids: list[str],
    observation_by_id: dict[str, Observation],
    expected_permission_scope: Any,
    record_name: str,
) -> None:
    missing_source_ids = set(source_observation_ids).difference(observation_by_id)
    if missing_source_ids:
        raise ContractValidationError(
            f"{record_name} source observations must be present in the extraction input"
        )
    expected_scope = to_plain(expected_permission_scope)
    if any(
        to_plain(observation_by_id[observation_id].permission_scope) != expected_scope
        for observation_id in source_observation_ids
    ):
        raise ContractValidationError(
            f"{record_name} permission scope must match every source observation"
        )


def _validate_candidate_review_state(
    *,
    status: str,
    requires_review: bool,
    metadata: dict[str, Any],
    record_name: str,
) -> None:
    if status != "pending_review" or requires_review is not True:
        raise ContractValidationError(f"{record_name} extraction output must remain pending review")
    if metadata.get("canonical_write_allowed") is not False:
        raise ContractValidationError(
            f"{record_name} extraction output cannot allow canonical writes"
        )


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
        _persist_record_batch(
            (
                (self._atom_store, atoms),
                (self._entity_store, entities),
                (self._relation_store, relations),
                (self._revision_store, [revision]),
            ),
            conflict_message="canonical record already exists with different lineage",
        )


def _persist_record_batch(
    groups: tuple[tuple[_JsonGraphRecordStore[Any], list[Any]], ...],
    *,
    conflict_message: str,
) -> None:
    prepared: list[tuple[Path, dict[str, Any], bytes | None]] = []
    prepared_payloads: dict[Path, dict[str, Any]] = {}
    for store, records in groups:
        for record in records:
            # Validate every contract and safe record path before writing
            # anything, so a late validation failure cannot leave a partial
            # candidate extraction or reviewed canonical commit.
            validated = store._validate(record)
            payload = store.serializer(validated)
            path = store._record_path(str(payload[store.id_field]))
            plain_payload = to_plain(payload)
            previous_payload = prepared_payloads.get(path)
            if previous_payload is not None:
                if previous_payload != plain_payload:
                    raise ContractValidationError(conflict_message)
                continue
            original = path.read_bytes() if path.exists() else None
            if original is not None and json.loads(original.decode("utf-8")) != plain_payload:
                raise ContractValidationError(conflict_message)
            prepared_payloads[path] = plain_payload
            prepared.append((path, payload, original))

    written: list[tuple[Path, bytes | None]] = []
    try:
        for path, payload, original in prepared:
            # Register before invoking the writer so a writer that persists and
            # then raises is also rolled back.
            written.append((path, original))
            _write_json(path, payload)
    except Exception:
        for path, original in reversed(written):
            path.with_suffix(f"{path.suffix}.tmp").unlink(missing_ok=True)
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        raise
