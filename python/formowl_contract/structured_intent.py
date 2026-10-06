"""Closed contracts for permission-first structured semantic intent.

The contract intentionally separates an ungrounded task skeleton from a
grounded executable plan.  A caller must establish the admissible evidence
scope before asking this module to resolve schema aliases or values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence
import unicodedata

from .models import ContractValidationError, canonical_json, sha256_json


CLAIM_REQUIREMENT_KIND_VALUES = (
    "single_value",
    "latest_value",
    "current_value",
    "all_matching",
    "aggregation",
    "existential_witness",
)
TRANSITION_INTENT_VALUES = (
    "new_task",
    "task_refinement",
    "evidence_scope_refinement",
)
EVIDENCE_SCOPE_PROPERTY_VALUES = (
    "attachments",
    "version",
    "missing_fields",
)
SEMANTIC_QUERY_CLASS_VALUES = ("attribute_filter",)
SEMANTIC_OPERATOR_VALUES = ("equals",)
SEMANTIC_CARDINALITY_VALUES = ("all_matching",)
SEMANTIC_ORDER_DIRECTION_VALUES = ("ascending", "descending")
SEMANTIC_ORDER_BY_VALUES = ("source_observation_id", "row_ordinal", "projection")
SEMANTIC_VALUE_DOMAIN_VALUES = ("closed_enum", "open_public_value")
_STRUCTURED_INTENT_KEYS = frozenset(
    {
        "claim_requirement_kind",
        "transition_intent",
        "evidence_scope_properties",
    }
)
_SEMANTIC_REQUIRED_CONSTRAINT_SLOTS = frozenset({"object_type", "predicate", "value"})
_SEMANTIC_REQUIRED_PROJECTION_SLOTS = frozenset({"projection"})
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
_SEMANTIC_REQUEST_MENTION_FIELDS = (
    "object_type_mention",
    "predicate_mention",
    "value_mention",
    "projection_mention",
)
_SEMANTIC_REQUEST_MAX_PAGE_SIZE = 100
_SEMANTIC_REQUEST_MAX_PAGE_NUMBER = 10_000
_WHITESPACE = re.compile(r"\s+")


class SemanticPlanClarificationRequired(ContractValidationError):
    """The request cannot be grounded safely enough to execute."""


# This object remains the single public structured-intent schema source used by
# the public transport adapters.  Semantic plans below are server-owned
# internal contracts and are deliberately not accepted as free-form client data.
STRUCTURED_INTENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_requirement_kind": {
            "type": "string",
            "enum": list(CLAIM_REQUIREMENT_KIND_VALUES),
        },
        "transition_intent": {
            "type": "string",
            "enum": list(TRANSITION_INTENT_VALUES),
        },
        "evidence_scope_properties": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": list(EVIDENCE_SCOPE_PROPERTY_VALUES),
            },
            "uniqueItems": True,
        },
    },
    "required": [
        "claim_requirement_kind",
        "transition_intent",
        "evidence_scope_properties",
    ],
    "additionalProperties": False,
}

QueryMailEvidenceSchemaProfile = Literal["codex_dynamic", "semantic_jsonrpc"]


def structured_intent_json_schema() -> dict[str, Any]:
    """Return a detached copy of the exact shared object schema."""

    import json

    return json.loads(canonical_json(STRUCTURED_INTENT_JSON_SCHEMA))


def semantic_request_json_schema() -> dict[str, Any]:
    """Return the one public UAT-to-diagnostic semantic request schema."""

    return {
        "type": "object",
        "properties": {
            "query_class": {"type": "string", "enum": list(SEMANTIC_QUERY_CLASS_VALUES)},
            "object_type_mention": {"type": "string"},
            "predicate_mention": {"type": "string"},
            "operator": {"type": "string", "enum": list(SEMANTIC_OPERATOR_VALUES)},
            "value_mention": {"type": "string"},
            "projection_mention": {"type": "string"},
            "cardinality": {"type": "string", "enum": list(SEMANTIC_CARDINALITY_VALUES)},
            "page_size": {
                "type": "integer",
                "minimum": 1,
                "maximum": _SEMANTIC_REQUEST_MAX_PAGE_SIZE,
            },
            "page_number": {
                "type": "integer",
                "minimum": 1,
                "maximum": _SEMANTIC_REQUEST_MAX_PAGE_NUMBER,
            },
        },
        "required": sorted(_SEMANTIC_REQUEST_KEYS),
        "additionalProperties": False,
    }


def validate_semantic_request(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the shared nine-field ungrounded semantic request boundary."""

    if not isinstance(value, Mapping) or set(value) != _SEMANTIC_REQUEST_KEYS:
        raise ContractValidationError("semantic request fields are invalid")
    result = dict(value)
    if result["query_class"] not in SEMANTIC_QUERY_CLASS_VALUES:
        raise ContractValidationError("semantic request query class is invalid")
    if result["operator"] not in SEMANTIC_OPERATOR_VALUES:
        raise ContractValidationError("semantic request operator is invalid")
    if result["cardinality"] not in SEMANTIC_CARDINALITY_VALUES:
        raise ContractValidationError("semantic request cardinality is invalid")
    for field_name in _SEMANTIC_REQUEST_MENTION_FIELDS:
        raw = result[field_name]
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 8_000:
            raise ContractValidationError(f"semantic request {field_name} is invalid")
    for field_name, maximum in (
        ("page_size", _SEMANTIC_REQUEST_MAX_PAGE_SIZE),
        ("page_number", _SEMANTIC_REQUEST_MAX_PAGE_NUMBER),
    ):
        raw = result[field_name]
        if not isinstance(raw, int) or isinstance(raw, bool) or not 1 <= raw <= maximum:
            raise ContractValidationError(f"semantic request {field_name} is invalid")
    return result


def query_mail_evidence_input_schema(
    profile: QueryMailEvidenceSchemaProfile,
) -> dict[str, Any]:
    """Return one authoritative closed public query input schema."""

    common_properties: dict[str, Any] = {
        "query_text": {"type": "string"},
        "structured_intent": structured_intent_json_schema(),
    }
    if profile == "semantic_jsonrpc":
        return {
            "type": "object",
            "properties": {
                **common_properties,
                "mail_import_session_id": {"type": "string"},
                "mail_evidence_bundle_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["query_text", "structured_intent"],
            "additionalProperties": False,
        }
    if profile == "codex_dynamic":
        return {
            "type": "object",
            "properties": {
                "query_text": {
                    "type": "string",
                    "description": "A standalone source-neutral evidence query.",
                },
                "required_terms": {
                    "type": "array",
                    "description": (
                        "Explicit identifiers, names, or codes that must literally "
                        "appear in each matched source item."
                    ),
                    "items": {"type": "string"},
                    "maxItems": 12,
                },
                "sort": {"type": "string", "enum": ["relevance", "recent"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "structured_intent": common_properties["structured_intent"],
            },
            "required": [
                "query_text",
                "required_terms",
                "sort",
                "limit",
                "structured_intent",
            ],
            "additionalProperties": False,
        }
    raise ContractValidationError("query mail evidence schema profile is invalid")


@dataclass(frozen=True)
class StructuredIntent:
    """Typed claim requirement and closed task-transition intent."""

    claim_requirement_kind: str
    transition_intent: str
    evidence_scope_properties: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.claim_requirement_kind) is not str
            or self.claim_requirement_kind not in CLAIM_REQUIREMENT_KIND_VALUES
        ):
            raise ContractValidationError("structured intent claim kind is invalid")
        if (
            type(self.transition_intent) is not str
            or self.transition_intent not in TRANSITION_INTENT_VALUES
        ):
            raise ContractValidationError("structured intent transition is invalid")
        properties = self.evidence_scope_properties
        if not isinstance(properties, (tuple, list)):
            raise ContractValidationError("structured intent scope properties are invalid")
        normalized = tuple(properties)
        if any(
            type(value) is not str or value not in EVIDENCE_SCOPE_PROPERTY_VALUES
            for value in normalized
        ):
            raise ContractValidationError("structured intent scope properties are invalid")
        if len(set(normalized)) != len(normalized):
            raise ContractValidationError("structured intent scope properties must be unique")
        canonical_properties = tuple(
            value for value in EVIDENCE_SCOPE_PROPERTY_VALUES if value in normalized
        )
        if self.transition_intent == "evidence_scope_refinement":
            if not canonical_properties:
                raise ContractValidationError("evidence scope refinement requires scope properties")
        elif canonical_properties:
            raise ContractValidationError(
                "scope properties are only valid for evidence scope refinement"
            )
        object.__setattr__(self, "evidence_scope_properties", canonical_properties)

    @property
    def identity_payload(self) -> dict[str, Any]:
        return self.to_dict()

    @property
    def identity(self) -> str:
        return canonical_json(self.identity_payload)

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.identity_payload)

    @property
    def semantic_identity(self) -> str:
        return self.fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_requirement_kind": self.claim_requirement_kind,
            "transition_intent": self.transition_intent,
            "evidence_scope_properties": list(self.evidence_scope_properties),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuredIntent":
        if not isinstance(value, Mapping):
            raise ContractValidationError("structured intent must be an object")
        if set(value) != _STRUCTURED_INTENT_KEYS:
            raise ContractValidationError("structured intent fields are invalid")
        properties = value["evidence_scope_properties"]
        if not isinstance(properties, list):
            raise ContractValidationError("structured intent scope properties are invalid")
        return cls(
            claim_requirement_kind=value["claim_requirement_kind"],
            transition_intent=value["transition_intent"],
            evidence_scope_properties=tuple(properties),
        )


def _semantic_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} is invalid")
    normalized = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).strip()).casefold()
    if not normalized:
        raise ContractValidationError(f"{field_name} is invalid")
    return normalized


def _semantic_texts(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ContractValidationError(f"{field_name} is invalid")
    normalized = tuple(_semantic_text(value, field_name) for value in values)
    if not normalized or len(set(normalized)) != len(normalized):
        raise ContractValidationError(f"{field_name} is invalid")
    return normalized


@dataclass(frozen=True)
class SemanticTaskSkeleton:
    """Permission-neutral shape with no schema or alias-grounded vocabulary."""

    query_class: str
    projection_slots: tuple[str, ...]
    constraint_slots: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.query_class not in SEMANTIC_QUERY_CLASS_VALUES:
            raise ContractValidationError("semantic task query class is invalid")
        projection_slots = _semantic_texts(self.projection_slots, "projection slots")
        constraint_slots = _semantic_texts(self.constraint_slots, "constraint slots")
        if not _SEMANTIC_REQUIRED_PROJECTION_SLOTS.issubset(projection_slots):
            raise ContractValidationError("semantic task projection slots are incomplete")
        if not _SEMANTIC_REQUIRED_CONSTRAINT_SLOTS.issubset(constraint_slots):
            raise ContractValidationError("semantic task constraint slots are incomplete")
        object.__setattr__(self, "projection_slots", projection_slots)
        object.__setattr__(self, "constraint_slots", constraint_slots)


@dataclass(frozen=True)
class AdmissibleSemanticScope:
    """The completed non-semantic gate required before schema grounding."""

    permission_admissible: bool
    source_admissible: bool
    version_admissible: bool
    context_admissible: bool
    time_admissible: bool
    status_admissible: bool

    def __post_init__(self) -> None:
        for field_name in (
            "permission_admissible",
            "source_admissible",
            "version_admissible",
            "context_admissible",
            "time_admissible",
            "status_admissible",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ContractValidationError(f"{field_name} is invalid")

    def require_complete(self) -> None:
        if not all(
            (
                self.permission_admissible,
                self.source_admissible,
                self.version_admissible,
                self.context_admissible,
                self.time_admissible,
                self.status_admissible,
            )
        ):
            raise SemanticPlanClarificationRequired(
                "semantic plan requires a complete admissible evidence scope"
            )


@dataclass(frozen=True)
class SemanticSchemaAliasMap:
    """A source-neutral map of canonical schema labels and value-domain policy."""

    object_aliases: Mapping[str, Sequence[str]]
    predicate_aliases: Mapping[str, Sequence[str]]
    value_aliases: Mapping[str, Mapping[str, Sequence[str]]]
    value_domains: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object_aliases = _canonical_alias_mapping(self.object_aliases, "object aliases")
        predicate_aliases = _canonical_alias_mapping(self.predicate_aliases, "predicate aliases")
        value_aliases: dict[str, Mapping[str, tuple[str, ...]]] = {}
        for predicate, values in self.value_aliases.items():
            canonical_predicate = _semantic_text(predicate, "value alias predicate")
            if canonical_predicate not in predicate_aliases:
                raise ContractValidationError("value alias predicate is unknown")
            value_aliases[canonical_predicate] = MappingProxyType(
                _canonical_alias_mapping(values, "value aliases")
            )
        raw_value_domains = self.value_domains
        if not isinstance(raw_value_domains, Mapping):
            raise ContractValidationError("value domains are invalid")
        value_domains: dict[str, str] = {predicate: "closed_enum" for predicate in value_aliases}
        for predicate, domain in raw_value_domains.items():
            canonical_predicate = _semantic_text(predicate, "value domain predicate")
            if canonical_predicate not in predicate_aliases:
                raise ContractValidationError("value domain predicate is unknown")
            if domain not in SEMANTIC_VALUE_DOMAIN_VALUES:
                raise ContractValidationError("value domain is invalid")
            value_domains[canonical_predicate] = domain
        for predicate, domain in value_domains.items():
            has_closed_values = predicate in value_aliases
            if domain == "closed_enum" and not has_closed_values:
                raise ContractValidationError("closed value domain requires value aliases")
            if domain == "open_public_value" and has_closed_values:
                raise ContractValidationError("open value domain must not enumerate values")
        object.__setattr__(self, "object_aliases", MappingProxyType(object_aliases))
        object.__setattr__(self, "predicate_aliases", MappingProxyType(predicate_aliases))
        object.__setattr__(self, "value_aliases", MappingProxyType(value_aliases))
        object.__setattr__(self, "value_domains", MappingProxyType(value_domains))

    def resolve_object(self, value: str) -> str:
        return _resolve_alias(self.object_aliases, value, "object type")

    def object_forms(self, object_type: str) -> tuple[str, ...]:
        return _alias_forms(self.object_aliases, object_type, "object type")

    def resolve_predicate(self, value: str) -> str:
        return _resolve_alias(self.predicate_aliases, value, "predicate")

    def resolve_value(self, predicate: str, value: str) -> str:
        """Return the server-policy-admissible normalized exact filter value.

        ``open_public_value`` deliberately has no ontology enumeration.  Its
        caller supplies the exact public lookup term after the isolated
        terminology-grounding stage; this contract normalizes that term for
        equality matching but never promotes it into the alias map, ontology,
        or graph.  Closed domains remain alias-resolved and fail closed for an
        unknown value.
        """

        domain = self.value_domain(predicate)
        if domain == "open_public_value":
            return _semantic_text(value, "value")
        values = self.value_aliases.get(predicate)
        if values is None:
            raise SemanticPlanClarificationRequired("predicate has no grounded value map")
        return _resolve_alias(values, value, "value")

    def value_domain(self, predicate: str) -> str:
        canonical_predicate = self.resolve_predicate(predicate)
        domain = self.value_domains.get(canonical_predicate)
        if domain is None:
            raise SemanticPlanClarificationRequired("predicate has no value domain")
        return domain

    def predicate_forms(self, predicate: str) -> tuple[str, ...]:
        return _alias_forms(self.predicate_aliases, predicate, "predicate")

    def value_forms(self, predicate: str, value: str) -> tuple[str, ...]:
        if self.value_domain(predicate) == "open_public_value":
            return (self.resolve_value(predicate, value),)
        values = self.value_aliases.get(predicate)
        if values is None:
            raise SemanticPlanClarificationRequired("predicate has no grounded value map")
        return _alias_forms(values, value, "value")


def _canonical_alias_mapping(
    aliases: Mapping[str, Sequence[str]],
    field_name: str,
) -> dict[str, tuple[str, ...]]:
    if not isinstance(aliases, Mapping) or not aliases:
        raise ContractValidationError(f"{field_name} are invalid")
    canonical_mapping: dict[str, tuple[str, ...]] = {}
    occupied: set[str] = set()
    for canonical, values in aliases.items():
        canonical_key = _semantic_text(canonical, field_name)
        alias_values = _semantic_texts(values, field_name)
        forms = tuple(dict.fromkeys((canonical_key, *alias_values)))
        if occupied.intersection(forms):
            raise ContractValidationError(f"{field_name} are ambiguous")
        occupied.update(forms)
        canonical_mapping[canonical_key] = forms
    return canonical_mapping


def _resolve_alias(
    aliases: Mapping[str, tuple[str, ...]],
    value: str,
    field_name: str,
) -> str:
    normalized = _semantic_text(value, field_name)
    matches = [canonical for canonical, forms in aliases.items() if normalized in forms]
    if len(matches) != 1:
        raise SemanticPlanClarificationRequired(f"{field_name} is not grounded")
    return matches[0]


def _alias_forms(
    aliases: Mapping[str, tuple[str, ...]],
    canonical: str,
    field_name: str,
) -> tuple[str, ...]:
    forms = aliases.get(canonical)
    if forms is None:
        raise SemanticPlanClarificationRequired(f"{field_name} is not grounded")
    return forms


@dataclass(frozen=True)
class ExecutableSemanticPlan:
    """A complete, grounded plan for a structured attribute-filtered set."""

    query_class: str
    object_type: str
    predicate: str
    operator: str
    value: str
    cardinality: str
    projection: str
    order_by: str
    order_direction: str
    page_size: int
    page_number: int
    object_type_match_forms: tuple[str, ...]
    predicate_match_forms: tuple[str, ...]
    value_match_forms: tuple[str, ...]
    projection_match_forms: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.query_class not in SEMANTIC_QUERY_CLASS_VALUES:
            raise ContractValidationError("semantic plan query class is invalid")
        if self.operator not in SEMANTIC_OPERATOR_VALUES:
            raise ContractValidationError("semantic plan operator is invalid")
        if self.cardinality not in SEMANTIC_CARDINALITY_VALUES:
            raise ContractValidationError("semantic plan cardinality is invalid")
        if self.order_by not in SEMANTIC_ORDER_BY_VALUES:
            raise ContractValidationError("semantic plan order is invalid")
        if self.order_direction not in SEMANTIC_ORDER_DIRECTION_VALUES:
            raise ContractValidationError("semantic plan order direction is invalid")
        for field_name in ("object_type", "predicate", "value", "projection"):
            object.__setattr__(
                self,
                field_name,
                _semantic_text(getattr(self, field_name), f"semantic plan {field_name}"),
            )
        for field_name in (
            "object_type_match_forms",
            "predicate_match_forms",
            "value_match_forms",
            "projection_match_forms",
        ):
            object.__setattr__(
                self,
                field_name,
                _semantic_texts(getattr(self, field_name), f"semantic plan {field_name}"),
            )
        if self.predicate not in self.predicate_match_forms:
            raise ContractValidationError("semantic plan predicate forms are invalid")
        if self.object_type not in self.object_type_match_forms:
            raise ContractValidationError("semantic plan object type forms are invalid")
        if self.value not in self.value_match_forms:
            raise ContractValidationError("semantic plan value forms are invalid")
        if self.projection not in self.projection_match_forms:
            raise ContractValidationError("semantic plan projection forms are invalid")
        for field_name in ("page_size", "page_number"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 1:
                raise ContractValidationError(f"semantic plan {field_name} is invalid")


class PermissionFirstSemanticPlanner:
    """Ground an executable plan only after non-semantic admissibility."""

    def ground_all_matching(
        self,
        *,
        skeleton: SemanticTaskSkeleton,
        scope: AdmissibleSemanticScope,
        aliases: SemanticSchemaAliasMap,
        object_type: str,
        predicate: str,
        value: str,
        projection: str,
        operator: str = "equals",
        order_by: str = "projection",
        order_direction: str = "ascending",
        page_size: int = 100,
        page_number: int = 1,
    ) -> ExecutableSemanticPlan:
        # This must remain before *any* lookup in ``aliases``.  The alias map
        # may represent governed schema/ontology vocabulary.
        scope.require_complete()
        if skeleton.query_class != "attribute_filter":
            raise SemanticPlanClarificationRequired("semantic query class is unsupported")
        if "projection" not in skeleton.projection_slots:
            raise SemanticPlanClarificationRequired("projection is not declared by task skeleton")
        canonical_predicate = aliases.resolve_predicate(predicate)
        canonical_value = aliases.resolve_value(canonical_predicate, value)
        canonical_projection = aliases.resolve_predicate(projection)
        try:
            canonical_object = aliases.resolve_object(object_type)
        except SemanticPlanClarificationRequired:
            try:
                object_mention_predicate = aliases.resolve_predicate(object_type)
            except SemanticPlanClarificationRequired:
                raise SemanticPlanClarificationRequired("object type is not grounded") from None
            if object_mention_predicate != canonical_projection or len(aliases.object_aliases) != 1:
                raise SemanticPlanClarificationRequired("object type is not grounded")
            canonical_object = next(iter(aliases.object_aliases))
        return ExecutableSemanticPlan(
            query_class=skeleton.query_class,
            object_type=canonical_object,
            predicate=canonical_predicate,
            operator=operator,
            value=canonical_value,
            cardinality="all_matching",
            projection=canonical_projection,
            order_by=order_by,
            order_direction=order_direction,
            page_size=page_size,
            page_number=page_number,
            object_type_match_forms=aliases.object_forms(canonical_object),
            predicate_match_forms=aliases.predicate_forms(canonical_predicate),
            value_match_forms=aliases.value_forms(canonical_predicate, canonical_value),
            projection_match_forms=aliases.predicate_forms(canonical_projection),
        )
