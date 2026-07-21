from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from typing import Any

from formowl_core import sha256_prefixed, sha256_prefixed_id

JsonValue = Any


class ContractValidationError(ValueError):
    """Raised when data does not match the shared formowl contract."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_plain(item) for key, item in asdict(value).items() if item is not None}
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    return value


def from_plain(value: Any) -> Any:
    if is_dataclass(value):
        return to_plain(value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(to_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return sha256_prefixed(canonical_json(value))


def stable_resource_contract_hash(contract_name: str, payload: Any) -> str:
    if not contract_name:
        raise ContractValidationError("contract_name is required")
    return sha256_json({"contract_name": contract_name, "payload": payload})


def stable_resource_contract_id(prefix: str, contract_name: str, payload: Any) -> str:
    if not contract_name:
        raise ContractValidationError("contract_name is required")
    return sha256_prefixed_id(
        prefix,
        canonical_json({"contract_name": contract_name, "payload": payload}),
    )


def stable_storage_backend_id(
    *,
    backend_type: str,
    workspace_scope: str,
    root_prefix: str | None = None,
    display_name: str | None = None,
) -> str:
    return stable_resource_contract_id(
        "storage",
        "StorageBackend",
        {
            "type": backend_type,
            "workspace_scope": workspace_scope,
            "root_prefix": root_prefix,
            "display_name": display_name,
        },
    )


def stable_asset_id(
    *,
    storage_backend_id: str,
    object_uri: str,
    content_hash: str,
    workspace_id: str,
    source_ref: Any | None = None,
) -> str:
    return stable_resource_contract_id(
        "asset",
        "Asset",
        {
            "storage_backend_id": storage_backend_id,
            "object_uri": object_uri,
            "content_hash": content_hash,
            "workspace_id": workspace_id,
            "source_ref": source_ref,
        },
    )


def stable_asset_metadata_hash(
    *,
    asset_id: str,
    metadata_type: str,
    metadata: dict[str, JsonValue],
    extractor_run_id: str | None = None,
) -> str:
    return stable_resource_contract_hash(
        "AssetMetadata",
        {
            "asset_id": asset_id,
            "metadata_type": metadata_type,
            "metadata": metadata,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_ingestion_job_id(
    *,
    asset_id: str,
    requested_by: str,
    workspace_id: str,
    extractor_names: list[str] | tuple[str, ...],
    config_hash: str | None = None,
) -> str:
    return stable_resource_contract_id(
        "job",
        "IngestionJob",
        {
            "asset_id": asset_id,
            "requested_by": requested_by,
            "workspace_id": workspace_id,
            "extractor_names": list(extractor_names),
            "config_hash": config_hash,
        },
    )


def stable_extractor_run_id(
    *,
    asset_id: str,
    extractor_name: str,
    extractor_version: str,
    extractor_type: str,
    input_hash: str,
    config_hash: str,
    model_name: str | None = None,
    model_version: str | None = None,
    prompt_hash: str | None = None,
) -> str:
    return stable_resource_contract_id(
        "run",
        "ExtractorRun",
        {
            "asset_id": asset_id,
            "extractor_name": extractor_name,
            "extractor_version": extractor_version,
            "extractor_type": extractor_type,
            "input_hash": input_hash,
            "config_hash": config_hash,
            "model_name": model_name,
            "model_version": model_version,
            "prompt_hash": prompt_hash,
        },
    )


def _is_missing_optional_id(value: Any) -> bool:
    return value is None or value == ""


def stable_observation_id(
    *,
    extractor_run_id: str,
    observation_type: str,
    modality: str,
    location: dict[str, JsonValue],
    asset_id: str | None = None,
    evidence_snapshot_id: str | None = None,
    text: str | None = None,
    caption: str | None = None,
    payload: dict[str, JsonValue] | None = None,
    extracted_value: JsonValue | None = None,
) -> str:
    if _is_missing_optional_id(asset_id) and _is_missing_optional_id(evidence_snapshot_id):
        raise ContractValidationError("Observation id requires asset_id or evidence_snapshot_id")
    return stable_resource_contract_id(
        "obs",
        "Observation",
        {
            "asset_id": asset_id,
            "evidence_snapshot_id": evidence_snapshot_id,
            "extractor_run_id": extractor_run_id,
            "observation_type": observation_type,
            "modality": modality,
            "location": location,
            "text": text,
            "caption": caption,
            "payload": payload,
            "extracted_value": extracted_value,
        },
    )


def stable_semantic_metadata_id(
    *,
    source_observation_ids: list[str] | tuple[str, ...],
    metadata_type: str,
    value: dict[str, JsonValue],
    extractor_run_id: str,
) -> str:
    return stable_resource_contract_id(
        "sem",
        "SemanticMetadata",
        {
            "source_observation_ids": list(source_observation_ids),
            "metadata_type": metadata_type,
            "value": value,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_candidate_atom_id(
    *,
    source_observation_ids: list[str] | tuple[str, ...],
    atom_type: str,
    label: str,
    properties: dict[str, JsonValue],
    extractor_run_id: str,
) -> str:
    return stable_resource_contract_id(
        "catom",
        "CandidateAtom",
        {
            "source_observation_ids": list(source_observation_ids),
            "atom_type": atom_type,
            "label": label,
            "properties": properties,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_candidate_relation_id(
    *,
    source_candidate_atom_id: str,
    target_candidate_atom_id: str,
    relation_type: str,
    source_observation_ids: list[str] | tuple[str, ...],
    properties: dict[str, JsonValue],
    extractor_run_id: str,
) -> str:
    return stable_resource_contract_id(
        "crel",
        "CandidateRelation",
        {
            "source_candidate_atom_id": source_candidate_atom_id,
            "target_candidate_atom_id": target_candidate_atom_id,
            "relation_type": relation_type,
            "source_observation_ids": list(source_observation_ids),
            "properties": properties,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_candidate_assertion_id(
    *,
    source_observation_ids: list[str] | tuple[str, ...],
    assertion_kind: str,
    subject_candidate_business_object_id: str,
    predicate: str,
    extractor_run_id: str,
    ontology_revision_id: str,
    domain_pack_id: str,
    domain_pack_content_hash: str,
    object_candidate_business_object_id: str | None = None,
    actor_candidate_business_object_id: str | None = None,
    counterparty_candidate_business_object_id: str | None = None,
    value: JsonValue | None = None,
    previous_value: JsonValue | None = None,
    proposed_value: JsonValue | None = None,
    temporal_context: dict[str, JsonValue] | None = None,
    context: dict[str, JsonValue] | None = None,
    epistemic_status: str = "asserted",
    lifecycle_status: str = "active",
) -> str:
    return stable_resource_contract_id(
        "cassert",
        "CandidateAssertion",
        {
            "source_observation_ids": sorted(source_observation_ids),
            "assertion_kind": assertion_kind,
            "subject_candidate_business_object_id": subject_candidate_business_object_id,
            "predicate": predicate,
            "object_candidate_business_object_id": object_candidate_business_object_id,
            "actor_candidate_business_object_id": actor_candidate_business_object_id,
            "counterparty_candidate_business_object_id": (
                counterparty_candidate_business_object_id
            ),
            "value": value,
            "previous_value": previous_value,
            "proposed_value": proposed_value,
            "temporal_context": temporal_context or {},
            "context": context or {},
            "epistemic_status": epistemic_status,
            "lifecycle_status": lifecycle_status,
            "extractor_run_id": extractor_run_id,
            "ontology_revision_id": ontology_revision_id,
            "domain_pack_id": domain_pack_id,
            "domain_pack_content_hash": domain_pack_content_hash,
        },
    )


def stable_external_graph_import_id(
    *,
    source_system: str,
    source_ref: Any,
    extractor_run_id: str,
    imported_at: str,
) -> str:
    return stable_resource_contract_id(
        "egimp",
        "ExternalGraphImport",
        {
            "source_system": source_system,
            "source_ref": source_ref,
            "extractor_run_id": extractor_run_id,
            "imported_at": imported_at,
        },
    )


def stable_canonical_atom_id(
    *,
    scope_type: str,
    scope_id: str,
    atom_type: str,
    canonical_text: str,
    source_candidate_atom_ids: list[str] | tuple[str, ...],
) -> str:
    return stable_resource_contract_id(
        "atom",
        "CanonicalAtom",
        {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "atom_type": atom_type,
            "canonical_text": canonical_text,
            "source_candidate_atom_ids": list(source_candidate_atom_ids),
        },
    )


def stable_canonical_entity_id(
    *,
    scope_type: str,
    scope_id: str,
    entity_type: str,
    canonical_label: str,
) -> str:
    return stable_resource_contract_id(
        "entity",
        "CanonicalEntity",
        {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "entity_type": entity_type,
            "canonical_label": canonical_label,
        },
    )


def stable_canonical_relation_id(
    *,
    scope_type: str,
    scope_id: str,
    source_id: str,
    target_id: str,
    relation_type: str,
    properties: dict[str, JsonValue] | None = None,
) -> str:
    return stable_resource_contract_id(
        "rel",
        "CanonicalRelation",
        {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation_type,
            "properties": properties or {},
        },
    )


def stable_canonical_graph_revision_id(
    *,
    scope_type: str,
    scope_id: str,
    ontology_revision_id: str,
    canonical_atom_ids: list[str] | tuple[str, ...],
    canonical_entity_ids: list[str] | tuple[str, ...],
    canonical_relation_ids: list[str] | tuple[str, ...],
    created_at: str,
    parent_revision_id: str | None = None,
) -> str:
    return stable_resource_contract_id(
        "graphrev",
        "CanonicalGraphRevision",
        {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "ontology_revision_id": ontology_revision_id,
            "canonical_atom_ids": list(canonical_atom_ids),
            "canonical_entity_ids": list(canonical_entity_ids),
            "canonical_relation_ids": list(canonical_relation_ids),
            "created_at": created_at,
            "parent_revision_id": parent_revision_id,
        },
    )


def stable_type_definition_id(
    *,
    tier: str,
    core_supertype_id: str,
    pref_label: str,
    scope_type: str,
    scope_id: str,
    ontology_revision_id: str,
) -> str:
    return stable_resource_contract_id(
        "type",
        "TypeDefinition",
        {
            "tier": tier,
            "core_supertype_id": core_supertype_id,
            "pref_label": pref_label,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "ontology_revision_id": ontology_revision_id,
        },
    )


def stable_type_alias_id(
    *,
    type_id: str,
    alias_label: str,
    scope_type: str,
    scope_id: str,
    ontology_revision_id: str,
) -> str:
    return stable_resource_contract_id(
        "typealias",
        "TypeAlias",
        {
            "type_id": type_id,
            "alias_label": alias_label,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "ontology_revision_id": ontology_revision_id,
        },
    )


def stable_type_mapping_id(
    *,
    source_type_id: str,
    target_core_supertype_id: str,
    scope_type: str,
    scope_id: str,
    ontology_revision_id: str,
) -> str:
    return stable_resource_contract_id(
        "typemap",
        "TypeMapping",
        {
            "source_type_id": source_type_id,
            "target_core_supertype_id": target_core_supertype_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "ontology_revision_id": ontology_revision_id,
        },
    )


def stable_type_alignment_candidate_id(
    *,
    source_type_id: str,
    target_type_id: str,
    source_scope_type: str,
    source_scope_id: str,
    target_scope_type: str,
    target_scope_id: str,
    ontology_revision_id: str,
) -> str:
    return stable_resource_contract_id(
        "typealign",
        "TypeAlignmentCandidate",
        {
            "source_type_id": source_type_id,
            "target_type_id": target_type_id,
            "source_scope_type": source_scope_type,
            "source_scope_id": source_scope_id,
            "target_scope_type": target_scope_type,
            "target_scope_id": target_scope_id,
            "ontology_revision_id": ontology_revision_id,
        },
    )


def stable_policy_id(
    *,
    policy_kind: str,
    policy_version: str,
    scope_type: str,
    scope_id: str,
    rules: dict[str, JsonValue],
    parent_policy_id: str | None = None,
) -> str:
    return stable_resource_contract_id(
        "policy",
        "GovernancePolicy",
        {
            "policy_kind": policy_kind,
            "policy_version": policy_version,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "rules": rules,
            "parent_policy_id": parent_policy_id,
        },
    )


def stable_upload_session_id(
    *,
    actor_user_id: str,
    workspace_id: str,
    owner_scope_type: str,
    owner_scope_id: str,
    intent: str,
    intended_asset_type: str,
    ingestion_profile: str,
    created_at: str,
) -> str:
    return stable_resource_contract_id(
        "upload",
        "UploadSession",
        {
            "actor_user_id": actor_user_id,
            "workspace_id": workspace_id,
            "owner_scope_type": owner_scope_type,
            "owner_scope_id": owner_scope_id,
            "intent": intent,
            "intended_asset_type": intended_asset_type,
            "ingestion_profile": ingestion_profile,
            "created_at": created_at,
        },
    )


def stable_wiki_projection_spec_id(
    *,
    projection_kind: str,
    graph_revision_id: str,
    ontology_revision_id: str,
    title: str,
    source_refs: list[Any] | tuple[Any, ...],
    evidence_snapshot_ids: list[str] | tuple[str, ...],
    citation_behavior: str,
) -> str:
    return stable_resource_contract_id(
        "projection",
        "WikiProjectionSpec",
        {
            "projection_kind": projection_kind,
            "graph_revision_id": graph_revision_id,
            "ontology_revision_id": ontology_revision_id,
            "title": title,
            "source_refs": list(source_refs),
            "evidence_snapshot_ids": list(evidence_snapshot_ids),
            "citation_behavior": citation_behavior,
        },
    )


def stable_user_graph_profile_id(
    *,
    owner_user_id: str,
    owner_scope_type: str,
    owner_scope_id: str,
    profile_name: str,
) -> str:
    return stable_resource_contract_id(
        "ugprofile",
        "UserGraphProfile",
        {
            "owner_user_id": owner_user_id,
            "owner_scope_type": owner_scope_type,
            "owner_scope_id": owner_scope_id,
            "profile_name": profile_name,
        },
    )


def stable_user_graph_assembly_policy_id(
    *,
    policy_version: str,
    owner_scope_type: str,
    owner_scope_id: str,
    graph_profile_id: str,
    rules: dict[str, JsonValue],
    parent_policy_id: str | None = None,
) -> str:
    return stable_resource_contract_id(
        "ugpolicy",
        "UserGraphAssemblyPolicy",
        {
            "policy_version": policy_version,
            "owner_scope_type": owner_scope_type,
            "owner_scope_id": owner_scope_id,
            "graph_profile_id": graph_profile_id,
            "rules": rules,
            "parent_policy_id": parent_policy_id,
        },
    )


def stable_user_knowledge_graph_revision_id(
    *,
    user_id: str,
    graph_profile_id: str,
    canonical_graph_revision_id: str,
    ontology_revision_id: str,
    assembly_policy_id: str,
    included_atom_ids: list[str] | tuple[str, ...],
    included_entity_ids: list[str] | tuple[str, ...],
    included_relation_ids: list[str] | tuple[str, ...],
    created_at: str,
    parent_user_graph_revision_id: str | None = None,
    excluded_atom_ids: list[str] | tuple[str, ...] = (),
    excluded_entity_ids: list[str] | tuple[str, ...] = (),
    excluded_relation_ids: list[str] | tuple[str, ...] = (),
    user_authored_atom_ids: list[str] | tuple[str, ...] = (),
    private_note_ids: list[str] | tuple[str, ...] = (),
    source_refs: list[Any] | tuple[Any, ...] = (),
    evidence_snapshot_ids: list[str] | tuple[str, ...] = (),
    permission_scope: Any | None = None,
) -> str:
    return stable_resource_contract_id(
        "ugrev",
        "UserKnowledgeGraphRevision",
        {
            "user_id": user_id,
            "graph_profile_id": graph_profile_id,
            "canonical_graph_revision_id": canonical_graph_revision_id,
            "ontology_revision_id": ontology_revision_id,
            "assembly_policy_id": assembly_policy_id,
            "included_atom_ids": list(included_atom_ids),
            "included_entity_ids": list(included_entity_ids),
            "included_relation_ids": list(included_relation_ids),
            "excluded_atom_ids": list(excluded_atom_ids),
            "excluded_entity_ids": list(excluded_entity_ids),
            "excluded_relation_ids": list(excluded_relation_ids),
            "user_authored_atom_ids": list(user_authored_atom_ids),
            "private_note_ids": list(private_note_ids),
            "source_refs": list(source_refs),
            "evidence_snapshot_ids": list(evidence_snapshot_ids),
            "permission_scope": permission_scope,
            "created_at": created_at,
            "parent_user_graph_revision_id": parent_user_graph_revision_id,
        },
    )
