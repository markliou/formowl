"""Source-neutral Observation -> Candidate Knowledge minimum pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from formowl_contract import (
    CandidateAssertion,
    CandidateBusinessObject,
    ContractValidationError,
    Observation,
    PermissionScope,
    assert_no_public_raw_references,
    normalize_temporal_context,
    parse_temporal_value,
    sha256_json,
    stable_candidate_assertion_id,
    stable_candidate_business_object_id,
    stable_resource_contract_id,
)

from .domain_packs import DomainPackDefinition, validate_domain_pack_provenance
from .storage import (
    CandidateAssertionStore,
    CandidateBusinessObjectStore,
    DomainPackStore,
    persist_candidate_knowledge_batch,
)

_PAYLOAD_KEY = "candidate_knowledge"
_OBJECT_FIELDS = {
    "local_id",
    "object_type",
    "label",
    "properties",
    "granularity_level",
    "confidence",
}
_ASSERTION_FIELDS = {
    "assertion_type",
    "subject",
    "object",
    "actor",
    "counterparty",
    "value",
    "previous_value",
    "proposed_value",
    "temporal_context",
    "context",
    "confidence",
}


@dataclass(frozen=True)
class CandidateKnowledgeExtractionResult:
    candidate_business_objects: list[CandidateBusinessObject] = field(default_factory=list)
    candidate_assertions: list[CandidateAssertion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    canonical_write_allowed: bool = field(default=False, init=False)


class DeterministicCandidateKnowledgeExtractor:
    """Interpret normalized candidate payloads without source-family branches."""

    def __init__(self, *, version: str = "0.1.0") -> None:
        self._version = version

    def name(self) -> str:
        return "deterministic_candidate_knowledge_extractor"

    def version(self) -> str:
        return self._version

    def extractor_type(self) -> str:
        return "candidate_knowledge"

    def extract(
        self,
        observations: Sequence[Observation],
        *,
        extractor_run_id: str,
        domain_pack: DomainPackDefinition,
        created_at: str,
    ) -> CandidateKnowledgeExtractionResult:
        pack = DomainPackDefinition.from_dict(domain_pack.to_dict())
        if not pack.assertion_mappings:
            raise ContractValidationError("generic candidate knowledge requires assertion mappings")
        validated_observations = [
            Observation.from_dict(observation.to_dict()) for observation in observations
        ]
        observation_by_id = {
            observation.observation_id: observation for observation in validated_observations
        }
        validate_domain_pack_provenance(pack, validated_observations)
        object_by_local_id: dict[str, CandidateBusinessObject] = {}
        object_observation_id: dict[str, str] = {}
        candidate_object_ids: set[str] = set()
        warnings: list[str] = []

        for observation in validated_observations:
            payload = _candidate_payload(observation)
            if payload is None:
                warnings.append(f"candidate_knowledge_missing:{observation.observation_id}")
                continue
            for raw_object in _require_list(
                payload.get("business_objects", []),
                f"{observation.observation_id}.business_objects",
            ):
                object_record = _require_mapping(
                    raw_object,
                    f"{observation.observation_id}.business_object",
                )
                _reject_unexpected_fields(
                    object_record,
                    _OBJECT_FIELDS,
                    f"{observation.observation_id}.business_object",
                )
                local_id = _required_string(
                    object_record,
                    "local_id",
                    f"{observation.observation_id}.business_object",
                )
                if local_id in object_by_local_id:
                    raise ContractValidationError(
                        "candidate business object local ids must be unique per extraction"
                    )
                object_type = _required_string(
                    object_record,
                    "object_type",
                    f"{observation.observation_id}.business_object",
                )
                label = _required_string(
                    object_record,
                    "label",
                    f"{observation.observation_id}.business_object",
                )
                properties = _optional_mapping(
                    object_record.get("properties", {}),
                    f"{observation.observation_id}.business_object.properties",
                )
                candidate = _build_business_object(
                    observation=observation,
                    object_record=object_record,
                    local_id=local_id,
                    object_type=object_type,
                    label=label,
                    properties=properties,
                    extractor_run_id=extractor_run_id,
                    domain_pack=pack,
                    created_at=created_at,
                )
                if candidate.candidate_business_object_id in candidate_object_ids:
                    raise ContractValidationError(
                        "candidate business object ids must be unique per extraction"
                    )
                candidate_object_ids.add(candidate.candidate_business_object_id)
                object_by_local_id[local_id] = candidate
                object_observation_id[local_id] = observation.observation_id

        assertions: list[CandidateAssertion] = []
        candidate_assertion_ids: set[str] = set()
        for observation in validated_observations:
            payload = _candidate_payload(observation)
            if payload is None:
                continue
            for raw_assertion in _require_list(
                payload.get("assertions", []),
                f"{observation.observation_id}.assertions",
            ):
                assertion_record = _require_mapping(
                    raw_assertion,
                    f"{observation.observation_id}.assertion",
                )
                _reject_unexpected_fields(
                    assertion_record,
                    _ASSERTION_FIELDS,
                    f"{observation.observation_id}.assertion",
                )
                assertion = _build_assertion(
                    observation=observation,
                    assertion_record=assertion_record,
                    object_by_local_id=object_by_local_id,
                    object_observation_id=object_observation_id,
                    observation_by_id=observation_by_id,
                    extractor_run_id=extractor_run_id,
                    domain_pack=pack,
                    created_at=created_at,
                )
                if assertion.candidate_assertion_id in candidate_assertion_ids:
                    raise ContractValidationError(
                        "candidate assertion ids must be unique per extraction"
                    )
                candidate_assertion_ids.add(assertion.candidate_assertion_id)
                assertions.append(assertion)

        if not object_by_local_id:
            warnings.append("no_candidate_business_objects")
        if not assertions:
            warnings.append("no_candidate_assertions")
        return CandidateKnowledgeExtractionResult(
            candidate_business_objects=list(object_by_local_id.values()),
            candidate_assertions=assertions,
            warnings=warnings,
        )


def extract_and_store_candidate_knowledge(
    *,
    observations: Sequence[Observation],
    domain_pack_store: DomainPackStore,
    candidate_business_object_store: CandidateBusinessObjectStore,
    candidate_assertion_store: CandidateAssertionStore,
    extractor_run_id: str,
    domain_pack: DomainPackDefinition,
    created_at: str,
    extractor: DeterministicCandidateKnowledgeExtractor | None = None,
) -> CandidateKnowledgeExtractionResult:
    active_extractor = extractor or DeterministicCandidateKnowledgeExtractor()
    validated_observations = [
        Observation.from_dict(observation.to_dict()) for observation in observations
    ]
    validate_domain_pack_provenance(domain_pack, validated_observations)
    result = active_extractor.extract(
        validated_observations,
        extractor_run_id=extractor_run_id,
        domain_pack=domain_pack,
        created_at=created_at,
    )
    candidate_assertion_ids = [
        assertion.candidate_assertion_id for assertion in result.candidate_assertions
    ]
    if len(set(candidate_assertion_ids)) != len(candidate_assertion_ids):
        raise ContractValidationError("candidate assertion ids must be unique per extraction")
    for candidate in result.candidate_business_objects:
        candidate_business_object_store.validate_candidate_business_object_id(
            candidate.candidate_business_object_id
        )
    for assertion in result.candidate_assertions:
        candidate_assertion_store.validate_candidate_assertion_id(assertion.candidate_assertion_id)
    domain_pack_store.validate_pack_id(domain_pack.pack_id)
    persist_candidate_knowledge_batch(
        domain_pack_store=domain_pack_store,
        candidate_business_object_store=candidate_business_object_store,
        candidate_assertion_store=candidate_assertion_store,
        domain_pack=domain_pack,
        observations=validated_observations,
        extractor_run_id=extractor_run_id,
        candidate_business_objects=result.candidate_business_objects,
        candidate_assertions=result.candidate_assertions,
    )
    return result


def _candidate_payload(observation: Observation) -> dict[str, Any] | None:
    payload = observation.payload or {}
    if _PAYLOAD_KEY not in payload:
        return None
    return _require_mapping(
        payload[_PAYLOAD_KEY],
        f"{observation.observation_id}.{_PAYLOAD_KEY}",
    )


def _build_business_object(
    *,
    observation: Observation,
    object_record: Mapping[str, Any],
    local_id: str,
    object_type: str,
    label: str,
    properties: dict[str, Any],
    extractor_run_id: str,
    domain_pack: DomainPackDefinition,
    created_at: str,
) -> CandidateBusinessObject:
    object_supertype = domain_pack.resolve_core_supertype(object_type)
    object_properties = {
        **properties,
        "source_observation_type": observation.observation_type,
    }
    candidate_id = stable_candidate_business_object_id(
        source_observation_ids=[observation.observation_id],
        object_type=object_type,
        label=label,
        properties=object_properties,
        extractor_run_id=extractor_run_id,
        object_supertype=object_supertype,
        ontology_revision_id=domain_pack.ontology_revision_id,
        domain_pack_id=domain_pack.pack_id,
        domain_pack_content_hash=domain_pack.content_hash,
    )
    candidate = CandidateBusinessObject.from_dict(
        {
            "candidate_business_object_id": candidate_id,
            "source_observation_ids": [observation.observation_id],
            "object_type": object_type,
            "object_supertype": object_supertype,
            "label": label,
            "domain_hints": [domain_pack.domain],
            "properties": object_properties,
            "granularity_level": object_record.get(
                "granularity_level",
                "business_object",
            ),
            "access_boundary": _access_boundary(observation),
            "confidence": object_record.get("confidence", observation.confidence),
            "extractor_run_id": extractor_run_id,
            "status": "pending_review",
            "requires_review": True,
            "source_candidate_mention_ids": [],
            "created_at": created_at,
            "metadata": {
                "source_local_id": local_id,
                "domain_pack_id": domain_pack.pack_id,
                "domain_pack_content_hash": domain_pack.content_hash,
                "ontology_revision_id": domain_pack.ontology_revision_id,
                "canonical_write_allowed": False,
            },
        }
    )
    assert_no_public_raw_references(
        candidate.to_dict(),
        "CandidateKnowledge.CandidateBusinessObject",
    )
    return candidate


def _build_assertion(
    *,
    observation: Observation,
    assertion_record: Mapping[str, Any],
    object_by_local_id: Mapping[str, CandidateBusinessObject],
    object_observation_id: Mapping[str, str],
    observation_by_id: Mapping[str, Observation],
    extractor_run_id: str,
    domain_pack: DomainPackDefinition,
    created_at: str,
) -> CandidateAssertion:
    assertion_type = _required_string(
        assertion_record,
        "assertion_type",
        f"{observation.observation_id}.assertion",
    )
    mapping = domain_pack.resolve_assertion_mapping(assertion_type)
    subject_local_id = _required_string(
        assertion_record,
        "subject",
        f"{observation.observation_id}.assertion",
    )
    subject_id = _candidate_object_id(
        subject_local_id,
        object_by_local_id,
        "subject",
    )
    object_id = _optional_candidate_object_id(
        assertion_record.get("object"),
        object_by_local_id,
        "object",
    )
    actor_id = _optional_candidate_object_id(
        assertion_record.get("actor"),
        object_by_local_id,
        "actor",
    )
    counterparty_id = _optional_candidate_object_id(
        assertion_record.get("counterparty"),
        object_by_local_id,
        "counterparty",
    )
    referenced_local_ids = [
        local_id
        for local_id in (
            subject_local_id,
            assertion_record.get("object"),
            assertion_record.get("actor"),
            assertion_record.get("counterparty"),
        )
        if isinstance(local_id, str)
    ]
    current_permission_scope = _permission_scope(observation)
    for local_id in referenced_local_ids:
        object_permission_scope = object_by_local_id[local_id].access_boundary.get(
            "permission_scope"
        )
        if object_permission_scope != current_permission_scope:
            raise ContractValidationError(
                "candidate assertion cannot join business objects across permission scopes"
            )
    source_observation_ids = sorted(
        {
            observation.observation_id,
            *(object_observation_id[local_id] for local_id in referenced_local_ids),
        }
    )
    raw_temporal_context = _optional_mapping(
        assertion_record.get("temporal_context", {}),
        f"{observation.observation_id}.assertion.temporal_context",
    )
    temporal_context = normalize_temporal_context(
        raw_temporal_context,
        temporal_roles=mapping.get("temporal_roles", {}),
    )
    captured_at = max(
        (observation_by_id[observation_id].created_at for observation_id in source_observation_ids),
        key=parse_temporal_value,
    )
    if temporal_context.get("captured_at") not in (None, captured_at):
        raise ContractValidationError(
            "CandidateAssertion.temporal_context.captured_at must match source observations"
        )
    temporal_context["captured_at"] = captured_at
    context = _optional_mapping(
        assertion_record.get("context", {}),
        f"{observation.observation_id}.assertion.context",
    )
    evidence_span = _evidence_span(observation, assertion_record)
    assertion_id = stable_candidate_assertion_id(
        source_observation_ids=source_observation_ids,
        assertion_kind=mapping["assertion_kind"],
        subject_candidate_business_object_id=subject_id,
        predicate=mapping["predicate"],
        object_candidate_business_object_id=object_id,
        actor_candidate_business_object_id=actor_id,
        counterparty_candidate_business_object_id=counterparty_id,
        value=assertion_record.get("value"),
        previous_value=assertion_record.get("previous_value"),
        proposed_value=assertion_record.get("proposed_value"),
        temporal_context=temporal_context,
        context=context,
        epistemic_status=mapping["epistemic_status"],
        lifecycle_status=mapping["lifecycle_status"],
        extractor_run_id=extractor_run_id,
        ontology_revision_id=domain_pack.ontology_revision_id,
        domain_pack_id=domain_pack.pack_id,
        domain_pack_content_hash=domain_pack.content_hash,
    )
    payload: dict[str, Any] = {
        "candidate_assertion_id": assertion_id,
        "assertion_kind": mapping["assertion_kind"],
        "subject_candidate_business_object_id": subject_id,
        "predicate": mapping["predicate"],
        "source_observation_ids": source_observation_ids,
        "evidence_spans": [evidence_span],
        "permission_scope": current_permission_scope,
        "confidence": assertion_record.get("confidence", observation.confidence),
        "extractor_run_id": extractor_run_id,
        "ontology_revision_id": domain_pack.ontology_revision_id,
        "domain_pack_id": domain_pack.pack_id,
        "domain_pack_content_hash": domain_pack.content_hash,
        "status": "pending_review",
        "requires_review": True,
        "epistemic_status": mapping["epistemic_status"],
        "lifecycle_status": mapping["lifecycle_status"],
        "temporal_context": temporal_context,
        "context": context,
        "created_at": created_at,
        "metadata": {
            "source_assertion_type": assertion_type,
            "domain": domain_pack.domain,
            "canonical_write_allowed": False,
        },
    }
    for field_name, field_value in (
        ("object_candidate_business_object_id", object_id),
        ("actor_candidate_business_object_id", actor_id),
        ("counterparty_candidate_business_object_id", counterparty_id),
    ):
        if field_value is not None:
            payload[field_name] = field_value
    for field_name in ("value", "previous_value", "proposed_value"):
        if field_name in assertion_record:
            payload[field_name] = assertion_record[field_name]
    return CandidateAssertion.from_dict(payload)


def _evidence_span(
    observation: Observation,
    assertion_record: Mapping[str, Any],
) -> dict[str, Any]:
    locator = dict(observation.location)
    if not locator:
        locator = {"observation_type": observation.observation_type}
    span_id = stable_resource_contract_id(
        "span",
        "CandidateAssertionEvidenceSpan",
        {
            "observation_id": observation.observation_id,
            "assertion_record": dict(assertion_record),
        },
    )
    return {
        "span_id": span_id,
        "source_observation_id": observation.observation_id,
        "locator": locator,
        "text_hash": sha256_json(
            {
                "text": observation.text,
                "caption": observation.caption,
                "extracted_value": observation.extracted_value,
                "assertion_record": dict(assertion_record),
            }
        ),
    }


def _access_boundary(observation: Observation) -> dict[str, Any]:
    return {
        "boundary_type": "source_observation_scope",
        "permission_scope": _permission_scope(observation),
        "raw_access_required": False,
        "redacted_slot_names": [],
    }


def _permission_scope(observation: Observation) -> dict[str, Any]:
    if isinstance(observation.permission_scope, PermissionScope):
        return observation.permission_scope.to_dict()
    return dict(observation.permission_scope)


def _candidate_object_id(
    local_id: str,
    object_by_local_id: Mapping[str, CandidateBusinessObject],
    field_name: str,
) -> str:
    try:
        return object_by_local_id[local_id].candidate_business_object_id
    except KeyError as exc:
        raise ContractValidationError(
            f"candidate assertion {field_name} references an unknown business object"
        ) from exc


def _optional_candidate_object_id(
    value: Any,
    object_by_local_id: Mapping[str, CandidateBusinessObject],
    field_name: str,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ContractValidationError(
            f"candidate assertion {field_name} must be a non-empty local id"
        )
    return _candidate_object_id(value, object_by_local_id, field_name)


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be an object")
    return dict(value)


def _optional_mapping(value: Any, field_name: str) -> dict[str, Any]:
    return _require_mapping(value, field_name)


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractValidationError(f"{field_name} must be a list")
    return list(value)


def _required_string(
    value: Mapping[str, Any],
    field_name: str,
    context: str,
) -> str:
    item = value.get(field_name)
    if not isinstance(item, str) or not item:
        raise ContractValidationError(f"{context}.{field_name} must be a non-empty string")
    return item


def _reject_unexpected_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    field_name: str,
) -> None:
    unexpected = set(value).difference(allowed)
    if unexpected:
        raise ContractValidationError(
            f"{field_name} contains unsupported fields: {', '.join(sorted(unexpected))}"
        )


__all__ = [
    "CandidateKnowledgeExtractionResult",
    "DeterministicCandidateKnowledgeExtractor",
    "extract_and_store_candidate_knowledge",
]
