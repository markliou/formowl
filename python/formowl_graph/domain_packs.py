"""Scoped domain vocabulary over FormOwl's stable candidate-knowledge core."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from formowl_contract import (
    ASSERTION_KIND_VALUES,
    ASSERTION_LIFECYCLE_STATUS_VALUES,
    COORDINATION_FRAME_TYPES,
    COORDINATION_OBJECT_SUPERTYPE_IDS,
    CORE_SUPERTYPE_IDS,
    ContractValidationError,
    EPISTEMIC_STATUS_VALUES,
    Observation,
    TEMPORAL_CONTEXT_FIELDS,
    assert_no_public_raw_references,
    sha256_json,
)

_GRAPH_REFERENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class DomainPackDefinition:
    """Small scoped vocabulary that cannot replace candidate governance.

    ``object_types`` maps domain object labels to FormOwl core supertypes.
    Legacy coordination-only packs that still use ``WorkObject`` and related
    supertypes remain readable by the coordination-frame experiment, but the
    generic candidate-knowledge pipeline requires a closed core supertype.
    """

    pack_id: str
    domain: str
    ontology_revision_id: str
    source_observation_ids: list[str]
    object_types: dict[str, str]
    assertion_mappings: dict[str, dict[str, Any]] = field(default_factory=dict)
    frame_extensions: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DomainPackDefinition":
        pack = dict(value)
        supported_fields = {
            "pack_id",
            "domain",
            "ontology_revision_id",
            "source_observation_ids",
            "object_types",
            "assertion_mappings",
            "frame_extensions",
            "aliases",
            "content_hash",
        }
        unexpected_fields = set(pack).difference(supported_fields)
        if unexpected_fields:
            raise ContractValidationError(
                "DomainPackDefinition contains unsupported fields: "
                + ", ".join(sorted(unexpected_fields))
            )
        required = (
            "pack_id",
            "domain",
            "ontology_revision_id",
            "source_observation_ids",
            "object_types",
        )
        missing = [field_name for field_name in required if pack.get(field_name) in (None, "")]
        if missing:
            raise ContractValidationError(
                f"DomainPackDefinition missing required field(s): {', '.join(missing)}"
            )
        if not all(
            isinstance(pack[field_name], str) and pack[field_name]
            for field_name in ("pack_id", "domain", "ontology_revision_id")
        ):
            raise ContractValidationError(
                "DomainPackDefinition ids and domain must be non-empty strings"
            )
        for field_name in ("pack_id", "ontology_revision_id"):
            if not _GRAPH_REFERENCE_ID.fullmatch(pack[field_name]):
                raise ContractValidationError(
                    f"DomainPackDefinition.{field_name} must be a governed graph id"
                )
        source_observation_ids = pack["source_observation_ids"]
        if not isinstance(source_observation_ids, list) or not source_observation_ids:
            raise ContractValidationError("DomainPackDefinition requires source observations")
        if not all(isinstance(item, str) and item for item in source_observation_ids):
            raise ContractValidationError(
                "DomainPackDefinition source observations must be strings"
            )
        if not all(_GRAPH_REFERENCE_ID.fullmatch(item) for item in source_observation_ids):
            raise ContractValidationError(
                "DomainPackDefinition source observations must be governed graph ids"
            )
        if len(set(source_observation_ids)) != len(source_observation_ids):
            raise ContractValidationError("DomainPackDefinition source observations must be unique")

        object_types = pack["object_types"]
        if not isinstance(object_types, dict) or not object_types:
            raise ContractValidationError("DomainPackDefinition.object_types must be non-empty")
        supported_object_supertypes = set(CORE_SUPERTYPE_IDS).union(
            COORDINATION_OBJECT_SUPERTYPE_IDS
        )
        for object_type, supertype in object_types.items():
            if not isinstance(object_type, str) or not object_type:
                raise ContractValidationError("domain object names must be non-empty strings")
            if supertype not in supported_object_supertypes:
                raise ContractValidationError("domain objects must target a FormOwl core supertype")

        assertion_mappings = pack.get("assertion_mappings", {})
        if not isinstance(assertion_mappings, dict):
            raise ContractValidationError(
                "DomainPackDefinition.assertion_mappings must be an object"
            )
        normalized_assertion_mappings: dict[str, dict[str, Any]] = {}
        for assertion_type, mapping in assertion_mappings.items():
            if not isinstance(assertion_type, str) or not assertion_type:
                raise ContractValidationError("domain assertion names must be non-empty strings")
            if not isinstance(mapping, Mapping):
                raise ContractValidationError("domain assertion mappings must be objects")
            unexpected = set(mapping).difference(
                {
                    "assertion_kind",
                    "predicate",
                    "epistemic_status",
                    "lifecycle_status",
                    "temporal_roles",
                }
            )
            if unexpected:
                raise ContractValidationError(
                    "domain assertion mappings contain unsupported fields"
                )
            assertion_kind = mapping.get("assertion_kind")
            predicate = mapping.get("predicate")
            epistemic_status = mapping.get("epistemic_status", "asserted")
            lifecycle_status = mapping.get("lifecycle_status", "active")
            temporal_roles = mapping.get("temporal_roles", {})
            if assertion_kind not in ASSERTION_KIND_VALUES:
                raise ContractValidationError(
                    "domain assertions must target a universal assertion kind"
                )
            if not isinstance(predicate, str) or not predicate:
                raise ContractValidationError(
                    "domain assertion mappings require a non-empty predicate"
                )
            if assertion_kind == "coordination" and predicate not in COORDINATION_FRAME_TYPES:
                raise ContractValidationError(
                    "coordination assertions must target a core coordination frame"
                )
            if epistemic_status not in EPISTEMIC_STATUS_VALUES:
                raise ContractValidationError(
                    "domain assertions must use a supported epistemic status"
                )
            if lifecycle_status not in ASSERTION_LIFECYCLE_STATUS_VALUES:
                raise ContractValidationError(
                    "domain assertions must use a supported lifecycle status"
                )
            if not isinstance(temporal_roles, Mapping):
                raise ContractValidationError("domain assertion temporal_roles must be an object")
            normalized_temporal_roles: dict[str, str] = {}
            for source_field, target_field in temporal_roles.items():
                if (
                    not isinstance(source_field, str)
                    or not source_field
                    or not isinstance(target_field, str)
                    or target_field not in TEMPORAL_CONTEXT_FIELDS
                    or target_field == "captured_at"
                ):
                    raise ContractValidationError(
                        "domain temporal roles must map non-empty labels "
                        "to TemporalContext fields"
                    )
                normalized_temporal_roles[source_field] = target_field
            if len(set(normalized_temporal_roles.values())) != len(normalized_temporal_roles):
                raise ContractValidationError(
                    "domain temporal roles must not target the same TemporalContext field"
                )
            normalized_assertion_mappings[assertion_type] = {
                "assertion_kind": assertion_kind,
                "predicate": predicate,
                "epistemic_status": epistemic_status,
                "lifecycle_status": lifecycle_status,
                "temporal_roles": normalized_temporal_roles,
            }

        frame_extensions = pack.get("frame_extensions", {})
        if not isinstance(frame_extensions, dict):
            raise ContractValidationError("DomainPackDefinition.frame_extensions must be an object")
        for domain_frame, core_frame in frame_extensions.items():
            if not isinstance(domain_frame, str) or not domain_frame:
                raise ContractValidationError("domain frame names must be non-empty strings")
            if core_frame not in COORDINATION_FRAME_TYPES:
                raise ContractValidationError("domain frame extensions must target core frames")

        aliases = pack.get("aliases", {})
        if not isinstance(aliases, dict):
            raise ContractValidationError("DomainPackDefinition.aliases must be an object")
        normalized_aliases: dict[str, list[str]] = {}
        for key, items in aliases.items():
            if not isinstance(key, str) or not key or not isinstance(items, list):
                raise ContractValidationError(
                    "DomainPackDefinition.aliases must map strings to lists"
                )
            if not all(isinstance(item, str) and item for item in items):
                raise ContractValidationError("DomainPackDefinition.alias entries must be strings")
            if len(set(items)) != len(items):
                raise ContractValidationError("DomainPackDefinition.alias entries must be unique")
            normalized_aliases[key] = list(items)

        normalized = {
            "pack_id": pack["pack_id"],
            "domain": pack["domain"],
            "ontology_revision_id": pack["ontology_revision_id"],
            "source_observation_ids": list(source_observation_ids),
            "object_types": dict(object_types),
            "assertion_mappings": normalized_assertion_mappings,
            "frame_extensions": dict(frame_extensions),
            "aliases": normalized_aliases,
        }
        content_hash = sha256_json(_content_hash_payload(normalized))
        provided_content_hash = pack.get("content_hash")
        if provided_content_hash is not None and provided_content_hash != content_hash:
            raise ContractValidationError(
                "DomainPackDefinition.content_hash does not match normalized content"
            )
        assert_no_public_raw_references(normalized, "DomainPackDefinition")
        return cls(**normalized)

    def to_dict(self) -> dict[str, Any]:
        valid = type(self).from_dict(
            {
                "pack_id": self.pack_id,
                "domain": self.domain,
                "ontology_revision_id": self.ontology_revision_id,
                "source_observation_ids": list(self.source_observation_ids),
                "object_types": dict(self.object_types),
                "assertion_mappings": {
                    key: dict(mapping) for key, mapping in self.assertion_mappings.items()
                },
                "frame_extensions": dict(self.frame_extensions),
                "aliases": {key: list(items) for key, items in self.aliases.items()},
            }
        )
        return {
            "pack_id": valid.pack_id,
            "domain": valid.domain,
            "ontology_revision_id": valid.ontology_revision_id,
            "source_observation_ids": valid.source_observation_ids,
            "object_types": valid.object_types,
            "assertion_mappings": valid.assertion_mappings,
            "frame_extensions": valid.frame_extensions,
            "aliases": valid.aliases,
            "content_hash": valid.content_hash,
        }

    @property
    def content_hash(self) -> str:
        return sha256_json(_content_hash_payload(self.to_unhashed_dict()))

    def to_unhashed_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "domain": self.domain,
            "ontology_revision_id": self.ontology_revision_id,
            "source_observation_ids": list(self.source_observation_ids),
            "object_types": dict(self.object_types),
            "assertion_mappings": {
                key: dict(mapping) for key, mapping in self.assertion_mappings.items()
            },
            "frame_extensions": dict(self.frame_extensions),
            "aliases": {key: list(items) for key, items in self.aliases.items()},
        }

    def resolve_core_supertype(self, object_type: str) -> str:
        try:
            supertype = self.object_types[object_type]
        except KeyError as exc:
            raise ContractValidationError(
                f"DomainPackDefinition does not define object type {object_type!r}"
            ) from exc
        if supertype not in CORE_SUPERTYPE_IDS:
            raise ContractValidationError(
                "generic candidate knowledge requires a closed core supertype"
            )
        return supertype

    def resolve_assertion_mapping(self, assertion_type: str) -> dict[str, Any]:
        try:
            return dict(self.assertion_mappings[assertion_type])
        except KeyError as exc:
            raise ContractValidationError(
                f"DomainPackDefinition does not define assertion type {assertion_type!r}"
            ) from exc


def validate_domain_pack_provenance(
    domain_pack: DomainPackDefinition,
    observations: list[Observation],
) -> None:
    validated_pack = DomainPackDefinition.from_dict(domain_pack.to_dict())
    validated_observations = [
        Observation.from_dict(observation.to_dict()) for observation in observations
    ]
    observation_by_id = {
        observation.observation_id: observation for observation in validated_observations
    }
    missing_pack_sources = set(validated_pack.source_observation_ids).difference(observation_by_id)
    if missing_pack_sources:
        raise ContractValidationError(
            "Domain Pack provenance observations must be present in the extraction input"
        )

    definition_observation_count = 0
    for observation_id in validated_pack.source_observation_ids:
        observation = observation_by_id[observation_id]
        if observation.observation_type != "domain_pack_definition":
            continue
        definition_observation_count += 1
        raw_definition = (observation.payload or {}).get("domain_pack_definition")
        if not isinstance(raw_definition, Mapping):
            raise ContractValidationError(
                "Domain Pack definition observation must contain a definition payload"
            )
        observed_pack = DomainPackDefinition.from_dict(raw_definition)
        if (
            observed_pack.pack_id != validated_pack.pack_id
            or observed_pack.content_hash != validated_pack.content_hash
        ):
            raise ContractValidationError(
                "Domain Pack definition observation does not match the supplied pack"
            )
    if definition_observation_count == 0:
        raise ContractValidationError(
            "Domain Pack provenance requires a domain_pack_definition observation"
        )


def _content_hash_payload(pack: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: pack[key]
        for key in (
            "domain",
            "ontology_revision_id",
            "source_observation_ids",
            "object_types",
            "assertion_mappings",
            "frame_extensions",
            "aliases",
        )
    }


__all__ = ["DomainPackDefinition", "validate_domain_pack_provenance"]
