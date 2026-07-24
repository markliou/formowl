"""Source-neutral evidence coverage and answer-claim contracts.

These contracts are deliberately independent from mail, retrieval, MCP, and
task-answering implementations.  They are the durable boundary between
source onboarding, evidence persistence, and any later consumer.

The public representation contains identifiers, governed hashes, and bounded
facts only.  Raw paths, backend locators, SQL, credentials, and private
payloads are rejected rather than silently serialized.
"""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .primitives import (
    ContractValidationError,
    now_iso,
    stable_resource_contract_id,
)
from .public_safety import assert_no_public_raw_references


PROCESSING_STATE_VALUES = (
    "parsed",
    "preserved_unparsed",
    "unsupported",
    "failed",
    "intentionally_excluded",
)
RAW_RETENTION_STATE_VALUES = (
    "retained",
    "deleted_by_policy",
    "externally_managed",
)
EXCLUSION_REASON_CODE_VALUES = (
    "outside_claim_scope",
    "policy_scope_exclusion",
    "privacy_restriction",
    "unsupported_by_policy",
    "user_requested_exclusion",
    "duplicate_source",
)
CLAIM_REQUIREMENT_KIND_VALUES = (
    "single_value",
    "latest_value",
    "current_value",
    "all_matching",
    "aggregation",
    "existential_witness",
)
ANSWER_CLAIM_STATE_VALUES = (
    "FOUND",
    "CONFLICT",
    "NOT_FOUND_WITHIN_COMPLETE_SCOPE",
    "INSUFFICIENT_COVERAGE",
)
INDEX_FRESHNESS_VALUES = ("fresh", "stale", "mismatch", "unavailable")
COVERAGE_FALLBACK_STATUS_VALUES = (
    "not_required",
    "completed",
    "budget_exhausted",
    "failed",
    "cancelled",
)
COVERAGE_PROOF_KIND_VALUES = (
    "structural",
    "ordinary",
    "combined",
    "intentionally_excluded",
    "fallback",
)
CELL_STATE_VALUES = ("populated", "blank", "absent")

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SAFE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_FORBIDDEN_PUBLIC_KEYS = {
    "backend",
    "backend_locator",
    "connection_string",
    "file_path",
    "internal",
    "object_store_locator",
    "private_payload",
    "raw_locator",
    "raw_path",
    "raw_payload",
    "scratch_path",
    "sql",
    "storage_locator",
}
_ANSWER_CLAIM_PUBLIC_KEYS = frozenset(
    {
        "state",
        "reason_codes",
        "claim_requirement_id",
        "coverage_ledger_id",
        "evidence_snapshot_ids",
        "source_fingerprint",
        "parser_fingerprint",
        "tokenizer_fingerprint",
        "index_fingerprint",
    }
)
_ANSWER_CLAIM_PERSISTENCE_KEYS = _ANSWER_CLAIM_PUBLIC_KEYS | {
    "answer_claim_id",
    "version_manifest_id",
    "implementation_fingerprint",
}


class ProcessingState(str, Enum):
    PARSED = "parsed"
    PRESERVED_UNPARSED = "preserved_unparsed"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    INTENTIONALLY_EXCLUDED = "intentionally_excluded"


class RawRetentionState(str, Enum):
    RETAINED = "retained"
    DELETED_BY_POLICY = "deleted_by_policy"
    EXTERNALLY_MANAGED = "externally_managed"


class ClaimRequirementKind(str, Enum):
    SINGLE_VALUE = "single_value"
    LATEST_VALUE = "latest_value"
    CURRENT_VALUE = "current_value"
    ALL_MATCHING = "all_matching"
    AGGREGATION = "aggregation"
    EXISTENTIAL_WITNESS = "existential_witness"


class AnswerClaimState(str, Enum):
    FOUND = "FOUND"
    CONFLICT = "CONFLICT"
    NOT_FOUND_WITHIN_COMPLETE_SCOPE = "NOT_FOUND_WITHIN_COMPLETE_SCOPE"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"


class IndexFreshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


class CoverageFallbackStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CoverageProofKind(str, Enum):
    STRUCTURAL = "structural"
    ORDINARY = "ordinary"
    COMBINED = "combined"
    INTENTIONALLY_EXCLUDED = "intentionally_excluded"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class DisplayPagination:
    """Presentation pagination, intentionally separate from claim coverage."""

    page_size: int
    page_number: int = 1
    displayed_count: int = 0
    has_more: bool = False

    def __post_init__(self) -> None:
        _positive_int(self.page_size, "display_pagination.page_size")
        _nonnegative_int(self.page_number, "display_pagination.page_number")
        _nonnegative_int(self.displayed_count, "display_pagination.displayed_count")
        _strict_bool(self.has_more, "display_pagination.has_more")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "page_size": self.page_size,
            "page_number": self.page_number,
            "displayed_count": self.displayed_count,
            "has_more": self.has_more,
        }
        _assert_public_contract(payload, "display_pagination")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DisplayPagination":
        item = _mapping(value, "display_pagination")
        return cls(
            page_size=_required_int(item, "page_size"),
            page_number=_optional_int(item, "page_number", 1),
            displayed_count=_optional_int(item, "displayed_count", 0),
            has_more=_required_bool(item, "has_more"),
        )


@dataclass(frozen=True)
class StructuralCell:
    """One table cell preserving topology and blank/absent distinction."""

    cell_state: str
    row_ordinal: int
    column_ordinal: int
    row_span: int = 1
    column_span: int = 1
    value: str | None = None
    normalized_value: str | None = None

    def __post_init__(self) -> None:
        _choice(self.cell_state, CELL_STATE_VALUES, "structural_cell.cell_state")
        _nonnegative_int(self.row_ordinal, "structural_cell.row_ordinal")
        _nonnegative_int(self.column_ordinal, "structural_cell.column_ordinal")
        _positive_int(self.row_span, "structural_cell.row_span")
        _positive_int(self.column_span, "structural_cell.column_span")
        _optional_text(self.value, "structural_cell.value")
        _optional_text(self.normalized_value, "structural_cell.normalized_value")
        if self.cell_state == "populated" and self.value is None:
            raise ContractValidationError("populated structural cell requires value")
        if self.cell_state != "populated" and self.value is not None:
            raise ContractValidationError("blank or absent structural cell must not carry a value")

    def to_dict(self) -> dict[str, Any]:
        payload = _dataclass_payload(self)
        _assert_public_contract(payload, "structural_cell")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuralCell":
        item = _mapping(value, "structural_cell")
        return cls(
            cell_state=_required_str(item, "cell_state"),
            row_ordinal=_required_int(item, "row_ordinal"),
            column_ordinal=_required_int(item, "column_ordinal"),
            row_span=_optional_int(item, "row_span", 1),
            column_span=_optional_int(item, "column_span", 1),
            value=_optional_str(item, "value"),
            normalized_value=_optional_str(item, "normalized_value"),
        )


@dataclass(frozen=True)
class StructuralColumn:
    column_ordinal: int
    original_header: str | None = None
    normalized_header: str | None = None

    def __post_init__(self) -> None:
        _nonnegative_int(self.column_ordinal, "structural_column.column_ordinal")
        _optional_text(self.original_header, "structural_column.original_header")
        _optional_text(self.normalized_header, "structural_column.normalized_header")

    def to_dict(self) -> dict[str, Any]:
        payload = _dataclass_payload(self)
        _assert_public_contract(payload, "structural_column")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuralColumn":
        item = _mapping(value, "structural_column")
        return cls(
            column_ordinal=_required_int(item, "column_ordinal"),
            original_header=_optional_str(item, "original_header"),
            normalized_header=_optional_str(item, "normalized_header"),
        )


@dataclass(frozen=True)
class StructuralRow:
    row_ordinal: int
    cells: tuple[StructuralCell, ...]

    def __post_init__(self) -> None:
        _nonnegative_int(self.row_ordinal, "structural_row.row_ordinal")
        _tuple_of(self.cells, StructuralCell, "structural_row.cells")
        ordinals = [cell.column_ordinal for cell in self.cells]
        if ordinals != sorted(set(ordinals)):
            raise ContractValidationError("structural row cell ordinals must be ordered and unique")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "row_ordinal": self.row_ordinal,
            "cells": [cell.to_dict() for cell in self.cells],
        }
        _assert_public_contract(payload, "structural_row")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuralRow":
        item = _mapping(value, "structural_row")
        return cls(
            row_ordinal=_required_int(item, "row_ordinal"),
            cells=tuple(StructuralCell.from_dict(cell) for cell in _required_list(item, "cells")),
        )


@dataclass(frozen=True)
class SourceInventoryItem:
    """One raw source structure and its independent processing/retention state."""

    source_inventory_item_id: str
    source_asset_id: str
    structure_kind: str
    content_type: str
    ordinal: int
    processing_state: str
    raw_retention_state: str
    source_fingerprint: str
    parser_fingerprint: str
    permission_scope: Mapping[str, Any]
    exclusion_policy_version_id: str | None = None
    exclusion_authorized_actor_id: str | None = None
    exclusion_reason_code: str | None = None
    exclusion_claim_scope_proof_sha256: str | None = None
    parent_inventory_item_id: str | None = None
    location: Mapping[str, Any] = field(default_factory=dict)
    version_lineage: tuple[str, ...] = ()
    source_observation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.source_inventory_item_id, "source_inventory_item_id")
        _id(self.source_asset_id, "source_asset_id")
        _text(self.structure_kind, "source_inventory_item.structure_kind")
        _text(self.content_type, "source_inventory_item.content_type")
        _nonnegative_int(self.ordinal, "source_inventory_item.ordinal")
        _choice(self.processing_state, PROCESSING_STATE_VALUES, "processing_state")
        _choice(self.raw_retention_state, RAW_RETENTION_STATE_VALUES, "raw_retention_state")
        _fingerprint(self.source_fingerprint, "source_fingerprint")
        _fingerprint(self.parser_fingerprint, "parser_fingerprint")
        _safe_mapping(self.permission_scope, "source_inventory_item.permission_scope")
        _validate_exclusion_proof(self)
        _optional_id(self.parent_inventory_item_id, "parent_inventory_item_id")
        _safe_mapping(self.location, "source_inventory_item.location")
        _tuple_of_strings(self.version_lineage, "version_lineage", ids=True)
        _tuple_of_strings(self.source_observation_ids, "source_observation_ids", ids=True)
        object.__setattr__(self, "permission_scope", _freeze_mapping(self.permission_scope))
        object.__setattr__(self, "location", _freeze_mapping(self.location))

    @classmethod
    def create(cls, **values: Any) -> "SourceInventoryItem":
        values = dict(values)
        for field_name in ("version_lineage", "source_observation_ids"):
            if field_name in values:
                values[field_name] = list(values[field_name])
        for field_name in (
            "exclusion_policy_version_id",
            "exclusion_authorized_actor_id",
            "exclusion_reason_code",
            "exclusion_claim_scope_proof_sha256",
        ):
            values.setdefault(field_name, None)
        values.setdefault(
            "source_inventory_item_id",
            stable_resource_contract_id(
                "inventory",
                "SourceInventoryItem",
                {key: values[key] for key in sorted(values) if key != "source_inventory_item_id"},
            ),
        )
        return cls.from_dict(values)

    def to_dict(self) -> dict[str, Any]:
        payload = _dataclass_payload(self)
        _assert_public_contract(payload, "source_inventory_item")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceInventoryItem":
        item = _mapping(value, "source_inventory_item")
        return cls(
            source_inventory_item_id=_required_str(item, "source_inventory_item_id"),
            source_asset_id=_required_str(item, "source_asset_id"),
            structure_kind=_required_str(item, "structure_kind"),
            content_type=_required_str(item, "content_type"),
            ordinal=_required_int(item, "ordinal"),
            processing_state=_required_str(item, "processing_state"),
            raw_retention_state=_required_str(item, "raw_retention_state"),
            source_fingerprint=_required_str(item, "source_fingerprint"),
            parser_fingerprint=_required_str(item, "parser_fingerprint"),
            permission_scope=_required_mapping(item, "permission_scope"),
            exclusion_policy_version_id=_optional_str(item, "exclusion_policy_version_id"),
            exclusion_authorized_actor_id=_optional_str(item, "exclusion_authorized_actor_id"),
            exclusion_reason_code=_optional_str(item, "exclusion_reason_code"),
            exclusion_claim_scope_proof_sha256=_optional_str(
                item, "exclusion_claim_scope_proof_sha256"
            ),
            parent_inventory_item_id=_optional_str(item, "parent_inventory_item_id"),
            location=_optional_mapping(item, "location", {}),
            version_lineage=_tuple_strings(item, "version_lineage"),
            source_observation_ids=_tuple_strings(item, "source_observation_ids"),
        )


@dataclass(frozen=True)
class SourceInventory:
    source_inventory_id: str
    source_asset_id: str
    source_fingerprint: str
    parser_fingerprint: str
    items: tuple[SourceInventoryItem, ...]
    created_at: str

    def __post_init__(self) -> None:
        _id(self.source_inventory_id, "source_inventory_id")
        _id(self.source_asset_id, "source_asset_id")
        _fingerprint(self.source_fingerprint, "source_fingerprint")
        _fingerprint(self.parser_fingerprint, "parser_fingerprint")
        _tuple_of(self.items, SourceInventoryItem, "source_inventory.items")
        _text(self.created_at, "source_inventory.created_at")
        if any(item.source_asset_id != self.source_asset_id for item in self.items):
            raise ContractValidationError("source inventory items must share source_asset_id")

    @classmethod
    def create(
        cls,
        *,
        source_asset_id: str,
        source_fingerprint: str,
        parser_fingerprint: str,
        items: Sequence[SourceInventoryItem],
        created_at: str | None = None,
    ) -> "SourceInventory":
        item_values = tuple(items)
        return cls(
            source_inventory_id=stable_resource_contract_id(
                "inventoryset",
                "SourceInventory",
                {
                    "source_asset_id": source_asset_id,
                    "source_fingerprint": source_fingerprint,
                    "parser_fingerprint": parser_fingerprint,
                    "items": [item.to_dict() for item in item_values],
                },
            ),
            source_asset_id=source_asset_id,
            source_fingerprint=source_fingerprint,
            parser_fingerprint=parser_fingerprint,
            items=item_values,
            created_at=created_at or now_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "source_inventory_id": self.source_inventory_id,
            "source_asset_id": self.source_asset_id,
            "source_fingerprint": self.source_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "items": [item.to_dict() for item in self.items],
            "created_at": self.created_at,
        }
        _assert_public_contract(payload, "source_inventory")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceInventory":
        item = _mapping(value, "source_inventory")
        return cls(
            source_inventory_id=_required_str(item, "source_inventory_id"),
            source_asset_id=_required_str(item, "source_asset_id"),
            source_fingerprint=_required_str(item, "source_fingerprint"),
            parser_fingerprint=_required_str(item, "parser_fingerprint"),
            items=tuple(
                SourceInventoryItem.from_dict(entry) for entry in _required_list(item, "items")
            ),
            created_at=_required_str(item, "created_at"),
        )


@dataclass(frozen=True)
class StructuralObservation:
    structural_observation_id: str
    source_inventory_item_id: str
    source_asset_id: str
    source_observation_id: str
    structure_kind: str
    columns: tuple[StructuralColumn, ...]
    rows: tuple[StructuralRow, ...]
    header_relationships: tuple[Mapping[str, Any], ...]
    source_fingerprint: str
    parser_fingerprint: str
    occurrence_lineage: tuple[str, ...] = ()
    message_lineage_id: str | None = None
    parent_observation_id: str | None = None
    current_depth: int = 0
    quoted_depth: int = 0
    table_ordinal: int | None = None
    mime_ordinal: int | None = None
    attachment_ordinal: int | None = None
    sender_fingerprint: str | None = None
    observed_at: str | None = None
    version_lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.structural_observation_id, "structural_observation_id")
        _id(self.source_inventory_item_id, "source_inventory_item_id")
        _id(self.source_asset_id, "source_asset_id")
        _id(self.source_observation_id, "source_observation_id")
        _text(self.structure_kind, "structural_observation.structure_kind")
        _tuple_of(self.columns, StructuralColumn, "structural_observation.columns")
        _tuple_of(self.rows, StructuralRow, "structural_observation.rows")
        _safe_mapping_sequence(
            self.header_relationships,
            "structural_observation.header_relationships",
        )
        _fingerprint(self.source_fingerprint, "source_fingerprint")
        _fingerprint(self.parser_fingerprint, "parser_fingerprint")
        _tuple_of_strings(self.occurrence_lineage, "occurrence_lineage", ids=True)
        _optional_id(self.message_lineage_id, "message_lineage_id")
        _optional_id(self.parent_observation_id, "parent_observation_id")
        _nonnegative_int(self.current_depth, "current_depth")
        _nonnegative_int(self.quoted_depth, "quoted_depth")
        for field_name in ("table_ordinal", "mime_ordinal", "attachment_ordinal"):
            value = getattr(self, field_name)
            if value is not None:
                _nonnegative_int(value, f"structural_observation.{field_name}")
        _optional_fingerprint(self.sender_fingerprint, "sender_fingerprint")
        _optional_text(self.observed_at, "structural_observation.observed_at")
        _tuple_of_strings(self.version_lineage, "version_lineage", ids=True)
        column_ordinals = [column.column_ordinal for column in self.columns]
        if column_ordinals != sorted(set(column_ordinals)):
            raise ContractValidationError(
                "structural observation columns must be ordered and unique"
            )
        row_ordinals = [row.row_ordinal for row in self.rows]
        if row_ordinals != sorted(set(row_ordinals)):
            raise ContractValidationError("structural observation rows must be ordered and unique")
        object.__setattr__(
            self,
            "header_relationships",
            tuple(_freeze_mapping(item) for item in self.header_relationships),
        )

    @classmethod
    def create(cls, **values: Any) -> "StructuralObservation":
        values = dict(values)
        for field_name in (
            "columns",
            "rows",
            "header_relationships",
            "occurrence_lineage",
            "version_lineage",
        ):
            if field_name in values:
                values[field_name] = list(values[field_name])
        values["columns"] = [
            item.to_dict() if isinstance(item, StructuralColumn) else item
            for item in values.get("columns", [])
        ]
        values["rows"] = [
            item.to_dict() if isinstance(item, StructuralRow) else item
            for item in values.get("rows", [])
        ]
        values["header_relationships"] = [
            dict(item) for item in values.get("header_relationships", [])
        ]
        values.setdefault(
            "structural_observation_id",
            stable_resource_contract_id(
                "structobs",
                "StructuralObservation",
                {key: values[key] for key in sorted(values) if key != "structural_observation_id"},
            ),
        )
        return cls.from_dict(values)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "structural_observation_id": self.structural_observation_id,
            "source_inventory_item_id": self.source_inventory_item_id,
            "source_asset_id": self.source_asset_id,
            "source_observation_id": self.source_observation_id,
            "structure_kind": self.structure_kind,
            "columns": [column.to_dict() for column in self.columns],
            "rows": [row.to_dict() for row in self.rows],
            "header_relationships": [
                _public_plain(dict(item)) for item in self.header_relationships
            ],
            "source_fingerprint": self.source_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "occurrence_lineage": list(self.occurrence_lineage),
            "message_lineage_id": self.message_lineage_id,
            "parent_observation_id": self.parent_observation_id,
            "current_depth": self.current_depth,
            "quoted_depth": self.quoted_depth,
            "table_ordinal": self.table_ordinal,
            "mime_ordinal": self.mime_ordinal,
            "attachment_ordinal": self.attachment_ordinal,
            "sender_fingerprint": self.sender_fingerprint,
            "observed_at": self.observed_at,
            "version_lineage": list(self.version_lineage),
        }
        payload = _without_none(payload)
        _assert_public_contract(payload, "structural_observation")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuralObservation":
        item = _mapping(value, "structural_observation")
        return cls(
            structural_observation_id=_required_str(item, "structural_observation_id"),
            source_inventory_item_id=_required_str(item, "source_inventory_item_id"),
            source_asset_id=_required_str(item, "source_asset_id"),
            source_observation_id=_required_str(item, "source_observation_id"),
            structure_kind=_required_str(item, "structure_kind"),
            columns=tuple(
                StructuralColumn.from_dict(entry) for entry in _required_list(item, "columns")
            ),
            rows=tuple(StructuralRow.from_dict(entry) for entry in _required_list(item, "rows")),
            header_relationships=tuple(
                _mapping(entry, "header_relationship")
                for entry in _required_list(item, "header_relationships")
            ),
            source_fingerprint=_required_str(item, "source_fingerprint"),
            parser_fingerprint=_required_str(item, "parser_fingerprint"),
            occurrence_lineage=_tuple_strings(item, "occurrence_lineage"),
            message_lineage_id=_optional_str(item, "message_lineage_id"),
            parent_observation_id=_optional_str(item, "parent_observation_id"),
            current_depth=_optional_int(item, "current_depth", 0),
            quoted_depth=_optional_int(item, "quoted_depth", 0),
            table_ordinal=_optional_int(item, "table_ordinal", None),
            mime_ordinal=_optional_int(item, "mime_ordinal", None),
            attachment_ordinal=_optional_int(item, "attachment_ordinal", None),
            sender_fingerprint=_optional_str(item, "sender_fingerprint"),
            observed_at=_optional_str(item, "observed_at"),
            version_lineage=_tuple_strings(item, "version_lineage"),
        )


@dataclass(frozen=True)
class ClaimRequirement:
    claim_requirement_id: str
    query_id: str
    kind: str
    target: str
    predicate: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    required_scope: tuple[str, ...] = ()
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        _id(self.claim_requirement_id, "claim_requirement_id")
        _id(self.query_id, "query_id")
        _choice(self.kind, CLAIM_REQUIREMENT_KIND_VALUES, "claim_requirement.kind")
        _text(self.target, "claim_requirement.target")
        _optional_text(self.predicate, "claim_requirement.predicate")
        _safe_mapping(self.parameters, "claim_requirement.parameters")
        _tuple_of_strings(self.required_scope, "claim_requirement.required_scope", ids=True)
        _text(self.created_at, "claim_requirement.created_at")
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters))

    @classmethod
    def create(
        cls,
        *,
        query_id: str,
        kind: str,
        target: str,
        predicate: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        required_scope: Sequence[str] = (),
        created_at: str | None = None,
    ) -> "ClaimRequirement":
        body = {
            "query_id": query_id,
            "kind": kind,
            "target": target,
            "predicate": predicate,
            "parameters": dict(parameters or {}),
            "required_scope": list(required_scope),
        }
        return cls(
            claim_requirement_id=stable_resource_contract_id("claimreq", "ClaimRequirement", body),
            query_id=query_id,
            kind=kind,
            target=target,
            predicate=predicate,
            parameters=dict(parameters or {}),
            required_scope=tuple(required_scope),
            created_at=created_at or now_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = _dataclass_payload(self)
        _assert_public_contract(payload, "claim_requirement")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimRequirement":
        item = _mapping(value, "claim_requirement")
        return cls(
            claim_requirement_id=_required_str(item, "claim_requirement_id"),
            query_id=_required_str(item, "query_id"),
            kind=_required_str(item, "kind"),
            target=_required_str(item, "target"),
            predicate=_optional_str(item, "predicate"),
            parameters=_optional_mapping(item, "parameters", {}),
            required_scope=_tuple_strings(item, "required_scope"),
            created_at=_required_str(item, "created_at"),
        )


@dataclass(frozen=True)
class VersionManifest:
    """Version binding for persisted evidence and index consumers."""

    version_manifest_id: str
    source_fingerprint: str
    parser_fingerprint: str
    tokenizer_fingerprint: str
    index_fingerprint: str
    implementation_fingerprint: str
    index_freshness: str = "fresh"
    source_version: str = "1"
    parser_version: str = "1"
    tokenizer_version: str = "1"
    index_version: str = "1"
    implementation_version: str = "1"
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        _id(self.version_manifest_id, "version_manifest_id")
        for field_name in (
            "source_fingerprint",
            "parser_fingerprint",
            "tokenizer_fingerprint",
            "index_fingerprint",
            "implementation_fingerprint",
        ):
            _fingerprint(getattr(self, field_name), field_name)
        _choice(self.index_freshness, INDEX_FRESHNESS_VALUES, "index_freshness")
        for field_name in (
            "source_version",
            "parser_version",
            "tokenizer_version",
            "index_version",
            "implementation_version",
            "created_at",
        ):
            _text(getattr(self, field_name), f"version_manifest.{field_name}")

    @classmethod
    def create(
        cls,
        *,
        source_fingerprint: str,
        parser_fingerprint: str,
        tokenizer_fingerprint: str,
        index_fingerprint: str,
        implementation_fingerprint: str,
        index_freshness: str = "fresh",
        source_version: str = "1",
        parser_version: str = "1",
        tokenizer_version: str = "1",
        index_version: str = "1",
        implementation_version: str = "1",
        created_at: str | None = None,
    ) -> "VersionManifest":
        body = {
            "source_fingerprint": source_fingerprint,
            "parser_fingerprint": parser_fingerprint,
            "tokenizer_fingerprint": tokenizer_fingerprint,
            "index_fingerprint": index_fingerprint,
            "implementation_fingerprint": implementation_fingerprint,
            "index_freshness": index_freshness,
            "source_version": source_version,
            "parser_version": parser_version,
            "tokenizer_version": tokenizer_version,
            "index_version": index_version,
            "implementation_version": implementation_version,
        }
        return cls(
            version_manifest_id=stable_resource_contract_id("version", "VersionManifest", body),
            **body,
            created_at=created_at or now_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = _dataclass_payload(self)
        _assert_public_contract(payload, "version_manifest")
        return payload

    def matches(self, other: "VersionManifest") -> bool:
        if not isinstance(other, VersionManifest):
            raise ContractValidationError("version manifest comparison requires VersionManifest")
        return all(
            getattr(self, field_name) == getattr(other, field_name)
            for field_name in (
                "source_fingerprint",
                "parser_fingerprint",
                "tokenizer_fingerprint",
                "index_fingerprint",
                "implementation_fingerprint",
                "source_version",
                "parser_version",
                "tokenizer_version",
                "index_version",
                "implementation_version",
            )
        )

    def usable_for_claim(self, expected: "VersionManifest") -> bool:
        return self.index_freshness == "fresh" and self.matches(expected)

    def assert_usable_for_claim(self, expected: "VersionManifest") -> None:
        if not self.usable_for_claim(expected):
            raise ContractValidationError(
                "version manifest is stale or mismatched for claim consumption"
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VersionManifest":
        item = _mapping(value, "version_manifest")
        return cls(
            version_manifest_id=_required_str(item, "version_manifest_id"),
            source_fingerprint=_required_str(item, "source_fingerprint"),
            parser_fingerprint=_required_str(item, "parser_fingerprint"),
            tokenizer_fingerprint=_required_str(item, "tokenizer_fingerprint"),
            index_fingerprint=_required_str(item, "index_fingerprint"),
            implementation_fingerprint=_required_str(item, "implementation_fingerprint"),
            index_freshness=_optional_str(item, "index_freshness") or "fresh",
            source_version=_optional_str(item, "source_version") or "1",
            parser_version=_optional_str(item, "parser_version") or "1",
            tokenizer_version=_optional_str(item, "tokenizer_version") or "1",
            index_version=_optional_str(item, "index_version") or "1",
            implementation_version=_optional_str(item, "implementation_version") or "1",
            created_at=_required_str(item, "created_at"),
        )


# Explicit aliases keep the contract name stable for adapters that describe
# the same persisted object as a fingerprint manifest or evidence manifest.
FingerprintManifest = VersionManifest
EvidenceVersionManifest = VersionManifest
SourceInventoryRecord = SourceInventoryItem


@dataclass(frozen=True)
class CoverageAuthorizationBinding:
    """Opaque authorization inputs used to scope a coverage proof."""

    actor_context_id: str
    permission_revision: str
    grant_revision: str

    def __post_init__(self) -> None:
        _opaque_binding(self.actor_context_id, "coverage_authorization.actor_context_id")
        _opaque_binding(self.permission_revision, "coverage_authorization.permission_revision")
        _opaque_binding(self.grant_revision, "coverage_authorization.grant_revision")

    def to_dict(self) -> dict[str, Any]:
        payload = _dataclass_payload(self)
        _assert_public_contract(payload, "coverage_authorization")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageAuthorizationBinding":
        item = _mapping(value, "coverage_authorization")
        _require_exact_keys(
            item,
            {"actor_context_id", "permission_revision", "grant_revision"},
            "coverage_authorization",
        )
        return cls(
            actor_context_id=_required_str(item, "actor_context_id"),
            permission_revision=_required_str(item, "permission_revision"),
            grant_revision=_required_str(item, "grant_revision"),
        )


@dataclass(frozen=True)
class CoverageVersionBinding:
    """The manifest and fingerprints used when the ledger was produced."""

    version_manifest_id: str
    source_fingerprint: str
    parser_fingerprint: str
    tokenizer_fingerprint: str
    index_fingerprint: str
    implementation_fingerprint: str
    freshness_state: str = "fresh"

    @classmethod
    def from_manifest(cls, manifest: VersionManifest) -> "CoverageVersionBinding":
        if not isinstance(manifest, VersionManifest):
            raise ContractValidationError("coverage version binding requires VersionManifest")
        return cls(
            version_manifest_id=manifest.version_manifest_id,
            source_fingerprint=manifest.source_fingerprint,
            parser_fingerprint=manifest.parser_fingerprint,
            tokenizer_fingerprint=manifest.tokenizer_fingerprint,
            index_fingerprint=manifest.index_fingerprint,
            implementation_fingerprint=manifest.implementation_fingerprint,
            freshness_state=manifest.index_freshness,
        )

    def __post_init__(self) -> None:
        _id(self.version_manifest_id, "coverage_version_binding.version_manifest_id")
        for field_name in (
            "source_fingerprint",
            "parser_fingerprint",
            "tokenizer_fingerprint",
            "index_fingerprint",
            "implementation_fingerprint",
        ):
            _fingerprint(getattr(self, field_name), f"coverage_version_binding.{field_name}")
        _choice(
            self.freshness_state,
            INDEX_FRESHNESS_VALUES,
            "coverage_version_binding.freshness_state",
        )

    def matches_manifest(self, manifest: VersionManifest) -> bool:
        if not isinstance(manifest, VersionManifest):
            raise ContractValidationError("coverage manifest comparison requires VersionManifest")
        return self == CoverageVersionBinding.from_manifest(manifest)

    def to_dict(self) -> dict[str, Any]:
        payload = _dataclass_payload(self)
        _assert_public_contract(payload, "coverage_version_binding")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageVersionBinding":
        item = _mapping(value, "coverage_version_binding")
        _require_exact_keys(
            item,
            {
                "version_manifest_id",
                "source_fingerprint",
                "parser_fingerprint",
                "tokenizer_fingerprint",
                "index_fingerprint",
                "implementation_fingerprint",
                "freshness_state",
            },
            "coverage_version_binding",
        )
        return cls(
            version_manifest_id=_required_str(item, "version_manifest_id"),
            source_fingerprint=_required_str(item, "source_fingerprint"),
            parser_fingerprint=_required_str(item, "parser_fingerprint"),
            tokenizer_fingerprint=_required_str(item, "tokenizer_fingerprint"),
            index_fingerprint=_required_str(item, "index_fingerprint"),
            implementation_fingerprint=_required_str(item, "implementation_fingerprint"),
            freshness_state=_required_str(item, "freshness_state"),
        )


@dataclass(frozen=True)
class CoverageFallbackUsage:
    """Closed fallback outcome with bounded, strictly typed resource usage."""

    status: str = "not_required"
    items: int = 0
    bytes: int = 0
    elapsed_ms: int = 0
    attempt_count: int = 0
    item_budget: int = 0
    byte_budget: int = 0
    elapsed_ms_budget: int = 0
    attempt_budget: int = 0

    def __post_init__(self) -> None:
        _choice(self.status, COVERAGE_FALLBACK_STATUS_VALUES, "fallback_usage.status")
        for field_name in (
            "items",
            "bytes",
            "elapsed_ms",
            "attempt_count",
            "item_budget",
            "byte_budget",
            "elapsed_ms_budget",
            "attempt_budget",
        ):
            _nonnegative_int(getattr(self, field_name), f"fallback_usage.{field_name}")
        usage_budget_pairs = (
            ("items", "item_budget"),
            ("bytes", "byte_budget"),
            ("elapsed_ms", "elapsed_ms_budget"),
            ("attempt_count", "attempt_budget"),
        )
        for usage_name, budget_name in usage_budget_pairs:
            usage = getattr(self, usage_name)
            budget = getattr(self, budget_name)
            if usage > budget:
                raise ContractValidationError(f"fallback_usage.{usage_name} exceeds {budget_name}")
        if self.status == "not_required":
            if any(
                getattr(self, field_name)
                for field_name in (
                    "items",
                    "bytes",
                    "elapsed_ms",
                    "attempt_count",
                    "item_budget",
                    "byte_budget",
                    "elapsed_ms_budget",
                    "attempt_budget",
                )
            ):
                raise ContractValidationError(
                    "not_required fallback must have zero usage and budgets"
                )
        elif self.status == "completed" and self.attempt_count == 0:
            raise ContractValidationError("completed fallback requires an attempt")
        elif self.status == "budget_exhausted":
            if not any(
                getattr(self, usage_name) == getattr(self, budget_name) > 0
                for usage_name, budget_name in usage_budget_pairs
            ):
                raise ContractValidationError(
                    "budget_exhausted fallback must consume a positive budget"
                )

    def to_dict(self) -> dict[str, Any]:
        payload = _dataclass_payload(self)
        _assert_public_contract(payload, "coverage_fallback_usage")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageFallbackUsage":
        item = _mapping(value, "coverage_fallback_usage")
        fields = {
            "status",
            "items",
            "bytes",
            "elapsed_ms",
            "attempt_count",
            "item_budget",
            "byte_budget",
            "elapsed_ms_budget",
            "attempt_budget",
        }
        _require_exact_keys(item, fields, "coverage_fallback_usage")
        return cls(
            status=_required_str(item, "status"),
            items=_required_int(item, "items"),
            bytes=_required_int(item, "bytes"),
            elapsed_ms=_required_int(item, "elapsed_ms"),
            attempt_count=_required_int(item, "attempt_count"),
            item_budget=_required_int(item, "item_budget"),
            byte_budget=_required_int(item, "byte_budget"),
            elapsed_ms_budget=_required_int(item, "elapsed_ms_budget"),
            attempt_budget=_required_int(item, "attempt_budget"),
        )


@dataclass(frozen=True)
class CoverageProofRecord:
    """One closed proof that a relevant inventory item was handled."""

    proof_id: str
    source_inventory_id: str
    claim_requirement_id: str
    version_manifest_id: str
    inventory_item_id: str
    proof_kind: str
    structural_observation_ids: tuple[str, ...] = ()
    ordinary_observation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "proof_id",
            "source_inventory_id",
            "claim_requirement_id",
            "version_manifest_id",
            "inventory_item_id",
        ):
            _id(getattr(self, field_name), f"coverage_proof.{field_name}")
        _choice(self.proof_kind, COVERAGE_PROOF_KIND_VALUES, "coverage_proof.proof_kind")
        _tuple_of_strings(
            self.structural_observation_ids,
            "coverage_proof.structural_observation_ids",
            ids=True,
        )
        _tuple_of_strings(
            self.ordinary_observation_ids,
            "coverage_proof.ordinary_observation_ids",
            ids=True,
        )
        if self.proof_kind == "structural" and not self.structural_observation_ids:
            raise ContractValidationError("structural proof requires structural observations")
        if self.proof_kind == "structural" and self.ordinary_observation_ids:
            raise ContractValidationError("structural proof must not carry ordinary observations")
        if self.proof_kind == "ordinary" and not self.ordinary_observation_ids:
            raise ContractValidationError("ordinary proof requires ordinary observations")
        if self.proof_kind == "ordinary" and self.structural_observation_ids:
            raise ContractValidationError("ordinary proof must not carry structural observations")
        if self.proof_kind == "combined" and (
            not self.structural_observation_ids or not self.ordinary_observation_ids
        ):
            raise ContractValidationError("combined proof requires both observation sets")
        if self.proof_kind in {"intentionally_excluded", "fallback"} and (
            self.structural_observation_ids or self.ordinary_observation_ids
        ):
            raise ContractValidationError(
                f"{self.proof_kind} proof must not carry observation identifiers"
            )
        object.__setattr__(
            self,
            "structural_observation_ids",
            tuple(self.structural_observation_ids),
        )
        object.__setattr__(
            self,
            "ordinary_observation_ids",
            tuple(self.ordinary_observation_ids),
        )

    @classmethod
    def create(cls, **values: Any) -> "CoverageProofRecord":
        values = dict(values)
        for field_name in ("structural_observation_ids", "ordinary_observation_ids"):
            values[field_name] = list(values.get(field_name, ()))
        values.setdefault(
            "proof_id",
            stable_resource_contract_id(
                "coverageproof",
                "CoverageProofRecord",
                {key: values[key] for key in sorted(values) if key != "proof_id"},
            ),
        )
        return cls.from_dict(values)

    def to_dict(self) -> dict[str, Any]:
        payload = _dataclass_payload(self)
        _assert_public_contract(payload, "coverage_proof")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageProofRecord":
        item = _mapping(value, "coverage_proof")
        _require_exact_keys(
            item,
            {
                "proof_id",
                "source_inventory_id",
                "claim_requirement_id",
                "version_manifest_id",
                "inventory_item_id",
                "proof_kind",
                "structural_observation_ids",
                "ordinary_observation_ids",
            },
            "coverage_proof",
        )
        return cls(
            proof_id=_required_str(item, "proof_id"),
            source_inventory_id=_required_str(item, "source_inventory_id"),
            claim_requirement_id=_required_str(item, "claim_requirement_id"),
            version_manifest_id=_required_str(item, "version_manifest_id"),
            inventory_item_id=_required_str(item, "inventory_item_id"),
            proof_kind=_required_str(item, "proof_kind"),
            structural_observation_ids=_tuple_strings(item, "structural_observation_ids"),
            ordinary_observation_ids=_tuple_strings(item, "ordinary_observation_ids"),
        )


@dataclass(frozen=True)
class CoverageLedger:
    query_id: str
    claim_requirement_id: str
    source_inventory_id: str
    relevant_inventory_item_ids: tuple[str, ...]
    searched_structural_observation_ids: tuple[str, ...] = ()
    searched_ordinary_observation_ids: tuple[str, ...] = ()
    omitted_inventory_item_ids: tuple[str, ...] = ()
    failed_inventory_item_ids: tuple[str, ...] = ()
    unsupported_inventory_item_ids: tuple[str, ...] = ()
    redacted_inventory_item_ids: tuple[str, ...] = ()
    authorization_binding: CoverageAuthorizationBinding | None = None
    version_binding: CoverageVersionBinding | None = None
    fallback_usage: CoverageFallbackUsage = field(default_factory=CoverageFallbackUsage)
    proof_records: tuple[CoverageProofRecord, ...] = ()
    complete_authorized_scope: bool = False
    display_pagination: DisplayPagination = field(
        default_factory=lambda: DisplayPagination(page_size=1)
    )
    coverage_ledger_id: str = ""

    @classmethod
    def create(
        cls,
        *,
        query_id: str,
        claim_requirement_id: str,
        source_inventory_id: str,
        relevant_inventory_item_ids: Sequence[str],
        searched_structural_observation_ids: Sequence[str] = (),
        searched_ordinary_observation_ids: Sequence[str] = (),
        omitted_inventory_item_ids: Sequence[str] = (),
        failed_inventory_item_ids: Sequence[str] = (),
        unsupported_inventory_item_ids: Sequence[str] = (),
        redacted_inventory_item_ids: Sequence[str] = (),
        authorization_binding: CoverageAuthorizationBinding | None = None,
        version_binding: CoverageVersionBinding | None = None,
        fallback_usage: CoverageFallbackUsage | None = None,
        proof_records: Sequence[CoverageProofRecord] = (),
        complete_authorized_scope: bool = False,
        display_pagination: DisplayPagination | None = None,
    ) -> "CoverageLedger":
        return cls(
            query_id=query_id,
            claim_requirement_id=claim_requirement_id,
            source_inventory_id=source_inventory_id,
            relevant_inventory_item_ids=tuple(relevant_inventory_item_ids),
            searched_structural_observation_ids=tuple(searched_structural_observation_ids),
            searched_ordinary_observation_ids=tuple(searched_ordinary_observation_ids),
            omitted_inventory_item_ids=tuple(omitted_inventory_item_ids),
            failed_inventory_item_ids=tuple(failed_inventory_item_ids),
            unsupported_inventory_item_ids=tuple(unsupported_inventory_item_ids),
            redacted_inventory_item_ids=tuple(redacted_inventory_item_ids),
            authorization_binding=authorization_binding,
            version_binding=version_binding,
            fallback_usage=fallback_usage or CoverageFallbackUsage(),
            proof_records=tuple(proof_records),
            complete_authorized_scope=complete_authorized_scope,
            display_pagination=display_pagination or DisplayPagination(page_size=1),
        )

    def __post_init__(self) -> None:
        _id(self.query_id, "coverage_ledger.query_id")
        _id(self.claim_requirement_id, "coverage_ledger.claim_requirement_id")
        _id(self.source_inventory_id, "coverage_ledger.source_inventory_id")
        for field_name in (
            "relevant_inventory_item_ids",
            "searched_structural_observation_ids",
            "searched_ordinary_observation_ids",
            "omitted_inventory_item_ids",
            "failed_inventory_item_ids",
            "unsupported_inventory_item_ids",
            "redacted_inventory_item_ids",
        ):
            _tuple_of_strings(getattr(self, field_name), field_name, ids=True)
            if len(getattr(self, field_name)) != len(set(getattr(self, field_name))):
                raise ContractValidationError(f"{field_name} must not contain duplicates")
        unresolved_sets = (
            self.omitted_inventory_item_ids,
            self.failed_inventory_item_ids,
            self.unsupported_inventory_item_ids,
            self.redacted_inventory_item_ids,
        )
        if set().union(*map(set, unresolved_sets)) - set(self.relevant_inventory_item_ids):
            raise ContractValidationError("unresolved inventory items must be relevant")
        if not (
            self.authorization_binding is None
            or isinstance(self.authorization_binding, CoverageAuthorizationBinding)
        ):
            raise ContractValidationError("coverage ledger authorization binding is invalid")
        if not (
            self.version_binding is None or isinstance(self.version_binding, CoverageVersionBinding)
        ):
            raise ContractValidationError("coverage ledger version binding is invalid")
        if not isinstance(self.fallback_usage, CoverageFallbackUsage):
            raise ContractValidationError("coverage ledger fallback usage is invalid")
        _tuple_of(self.proof_records, CoverageProofRecord, "coverage_ledger.proof_records")
        if not isinstance(self.display_pagination, DisplayPagination):
            raise ContractValidationError("coverage ledger display_pagination is invalid")
        if self.coverage_ledger_id:
            _id(self.coverage_ledger_id, "coverage_ledger_id")
        else:
            object.__setattr__(
                self,
                "coverage_ledger_id",
                stable_resource_contract_id(
                    "coverage",
                    "CoverageLedger",
                    self._identity_payload(),
                ),
            )
        if self.complete_authorized_scope:
            self._assert_complete_proof_shape()

    def _assert_complete_proof_shape(self) -> None:
        if self.authorization_binding is None:
            raise ContractValidationError("complete coverage requires authorization binding")
        if self.version_binding is None or self.version_binding.freshness_state != "fresh":
            raise ContractValidationError(
                "complete coverage requires a fresh version manifest binding"
            )
        if not self.relevant_inventory_item_ids:
            raise ContractValidationError("complete coverage requires a non-empty relevant scope")
        if not self.proof_records:
            raise ContractValidationError("complete coverage requires a non-empty proof set")
        if (
            self.omitted_inventory_item_ids
            or self.failed_inventory_item_ids
            or self.unsupported_inventory_item_ids
            or self.redacted_inventory_item_ids
        ):
            raise ContractValidationError(
                "complete authorized coverage cannot contain unresolved inventory"
            )
        if self.fallback_usage.status not in {"not_required", "completed"}:
            raise ContractValidationError(
                "complete authorized coverage requires completed or unnecessary fallback"
            )
        proof_item_ids = [record.inventory_item_id for record in self.proof_records]
        if len(proof_item_ids) != len(set(proof_item_ids)):
            raise ContractValidationError("complete coverage proof items must be unique")
        if set(proof_item_ids) != set(self.relevant_inventory_item_ids):
            raise ContractValidationError(
                "complete coverage proof set must cover exactly the relevant inventory"
            )
        for record in self.proof_records:
            if (
                record.source_inventory_id != self.source_inventory_id
                or record.claim_requirement_id != self.claim_requirement_id
                or record.version_manifest_id != self.version_binding.version_manifest_id
            ):
                raise ContractValidationError(
                    "complete coverage proof records must bind the ledger scope and manifest"
                )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "claim_requirement_id": self.claim_requirement_id,
            "source_inventory_id": self.source_inventory_id,
            "relevant_inventory_item_ids": list(self.relevant_inventory_item_ids),
            "searched_structural_observation_ids": list(self.searched_structural_observation_ids),
            "searched_ordinary_observation_ids": list(self.searched_ordinary_observation_ids),
            "omitted_inventory_item_ids": list(self.omitted_inventory_item_ids),
            "failed_inventory_item_ids": list(self.failed_inventory_item_ids),
            "unsupported_inventory_item_ids": list(self.unsupported_inventory_item_ids),
            "redacted_inventory_item_ids": list(self.redacted_inventory_item_ids),
            "authorization_binding": (
                self.authorization_binding.to_dict() if self.authorization_binding else None
            ),
            "version_binding": self.version_binding.to_dict() if self.version_binding else None,
            "fallback_usage": self.fallback_usage.to_dict(),
            "proof_records": [record.to_dict() for record in self.proof_records],
            "complete_authorized_scope": self.complete_authorized_scope,
            "display_pagination": self.display_pagination.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = {
            **self._identity_payload(),
            "coverage_ledger_id": self.coverage_ledger_id,
        }
        _assert_public_contract(payload, "coverage_ledger")
        return payload

    def to_persistence_dict(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageLedger":
        item = _mapping(value, "coverage_ledger")
        _require_exact_keys(
            item,
            {
                "query_id",
                "claim_requirement_id",
                "source_inventory_id",
                "relevant_inventory_item_ids",
                "searched_structural_observation_ids",
                "searched_ordinary_observation_ids",
                "omitted_inventory_item_ids",
                "failed_inventory_item_ids",
                "unsupported_inventory_item_ids",
                "redacted_inventory_item_ids",
                "authorization_binding",
                "version_binding",
                "fallback_usage",
                "proof_records",
                "complete_authorized_scope",
                "display_pagination",
                "coverage_ledger_id",
            },
            "coverage_ledger",
        )
        authorization_value = item["authorization_binding"]
        version_value = item["version_binding"]
        return cls(
            query_id=_required_str(item, "query_id"),
            claim_requirement_id=_required_str(item, "claim_requirement_id"),
            source_inventory_id=_required_str(item, "source_inventory_id"),
            relevant_inventory_item_ids=_tuple_strings(item, "relevant_inventory_item_ids"),
            searched_structural_observation_ids=_tuple_strings(
                item, "searched_structural_observation_ids"
            ),
            searched_ordinary_observation_ids=_tuple_strings(
                item, "searched_ordinary_observation_ids"
            ),
            omitted_inventory_item_ids=_tuple_strings(item, "omitted_inventory_item_ids"),
            failed_inventory_item_ids=_tuple_strings(item, "failed_inventory_item_ids"),
            unsupported_inventory_item_ids=_tuple_strings(item, "unsupported_inventory_item_ids"),
            redacted_inventory_item_ids=_tuple_strings(item, "redacted_inventory_item_ids"),
            authorization_binding=(
                None
                if authorization_value is None
                else CoverageAuthorizationBinding.from_dict(
                    _mapping(authorization_value, "authorization_binding")
                )
            ),
            version_binding=(
                None
                if version_value is None
                else CoverageVersionBinding.from_dict(_mapping(version_value, "version_binding"))
            ),
            fallback_usage=CoverageFallbackUsage.from_dict(
                _mapping(item["fallback_usage"], "fallback_usage")
            ),
            proof_records=tuple(
                CoverageProofRecord.from_dict(entry)
                for entry in _required_list(item, "proof_records")
            ),
            complete_authorized_scope=_required_bool(item, "complete_authorized_scope"),
            display_pagination=DisplayPagination.from_dict(
                _required_mapping(item, "display_pagination")
            ),
            coverage_ledger_id=_required_str(item, "coverage_ledger_id"),
        )

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "CoverageLedger":
        return cls.from_dict(value)

    def usable_for_claim(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding | None = None,
    ) -> bool:
        """Return true only after validating all typed proof inputs."""

        if not isinstance(source_inventory, SourceInventory):
            raise ContractValidationError("usable_for_claim requires SourceInventory")
        if not isinstance(claim_requirement, ClaimRequirement):
            raise ContractValidationError("usable_for_claim requires ClaimRequirement")
        if not isinstance(expected_manifest, VersionManifest):
            raise ContractValidationError("usable_for_claim requires VersionManifest")
        if expected_authorization_binding is not None and not isinstance(
            expected_authorization_binding,
            CoverageAuthorizationBinding,
        ):
            raise ContractValidationError("usable_for_claim expected authorization must be typed")
        if not self.complete_authorized_scope:
            return False
        if self.source_inventory_id != source_inventory.source_inventory_id:
            return False
        if self.claim_requirement_id != claim_requirement.claim_requirement_id:
            return False
        if self.query_id != claim_requirement.query_id:
            return False
        if self.authorization_binding is None or self.version_binding is None:
            return False
        if expected_authorization_binding is not None and (
            self.authorization_binding != expected_authorization_binding
        ):
            return False
        if expected_manifest.index_freshness != "fresh":
            return False
        if not self.version_binding.matches_manifest(expected_manifest):
            return False
        if (
            source_inventory.source_fingerprint != expected_manifest.source_fingerprint
            or source_inventory.parser_fingerprint != expected_manifest.parser_fingerprint
        ):
            return False
        item_by_id = {item.source_inventory_item_id: item for item in source_inventory.items}
        if set(self.relevant_inventory_item_ids) - set(item_by_id):
            return False
        if set(self.searched_structural_observation_ids) & set(
            self.searched_ordinary_observation_ids
        ):
            return False
        searched_observation_ids = set(self.searched_structural_observation_ids) | set(
            self.searched_ordinary_observation_ids
        )
        relevant_observation_ids = {
            observation_id
            for item_id in self.relevant_inventory_item_ids
            for observation_id in item_by_id[item_id].source_observation_ids
        }
        if not searched_observation_ids.issubset(relevant_observation_ids):
            return False
        proof_by_item = {record.inventory_item_id: record for record in self.proof_records}
        if set(proof_by_item) != set(self.relevant_inventory_item_ids):
            return False
        for record in self.proof_records:
            if (
                record.source_inventory_id != self.source_inventory_id
                or record.claim_requirement_id != self.claim_requirement_id
                or record.version_manifest_id != expected_manifest.version_manifest_id
            ):
                return False
            inventory_item = item_by_id.get(record.inventory_item_id)
            if inventory_item is None:
                return False
            if (
                inventory_item.source_fingerprint != expected_manifest.source_fingerprint
                or inventory_item.parser_fingerprint != expected_manifest.parser_fingerprint
            ):
                return False
            source_observation_ids = set(inventory_item.source_observation_ids)
            if not set(record.structural_observation_ids).issubset(
                source_observation_ids
            ) or not set(record.ordinary_observation_ids).issubset(source_observation_ids):
                return False
            if not set(record.structural_observation_ids).issubset(
                set(self.searched_structural_observation_ids)
            ):
                return False
            if not set(record.ordinary_observation_ids).issubset(
                set(self.searched_ordinary_observation_ids)
            ):
                return False
            if (
                record.proof_kind == "intentionally_excluded"
                and inventory_item.processing_state != "intentionally_excluded"
            ):
                return False
            if record.proof_kind == "fallback" and self.fallback_usage.status != "completed":
                return False
            if inventory_item.processing_state in {"failed", "unsupported"}:
                return False
            if (
                inventory_item.processing_state == "preserved_unparsed"
                and record.proof_kind != "fallback"
            ):
                return False
        return True

    @property
    def searched_observation_ids(self) -> tuple[str, ...]:
        """Compatibility view; wire serialization keeps the two sets separate."""

        return self.searched_structural_observation_ids + tuple(
            item
            for item in self.searched_ordinary_observation_ids
            if item not in self.searched_structural_observation_ids
        )

    @property
    def claim_scope_complete(self) -> bool:
        return self.complete_authorized_scope


@dataclass(frozen=True)
class AnswerClaim:
    state: str
    reason_codes: tuple[str, ...]
    claim_requirement_id: str
    coverage_ledger_id: str
    evidence_snapshot_ids: tuple[str, ...]
    source_fingerprint: str
    parser_fingerprint: str
    tokenizer_fingerprint: str
    index_fingerprint: str
    answer_claim_id: str = ""
    version_manifest_id: str | None = None
    implementation_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _choice(self.state, ANSWER_CLAIM_STATE_VALUES, "answer_claim.state")
        if not self.reason_codes:
            raise ContractValidationError("answer claim requires at least one reason code")
        _tuple_of_strings(self.reason_codes, "answer_claim.reason_codes", codes=True)
        _id(self.claim_requirement_id, "claim_requirement_id")
        _id(self.coverage_ledger_id, "coverage_ledger_id")
        _tuple_of_strings(self.evidence_snapshot_ids, "evidence_snapshot_ids", ids=True)
        _fingerprint(self.source_fingerprint, "source_fingerprint")
        _fingerprint(self.parser_fingerprint, "parser_fingerprint")
        _fingerprint(self.tokenizer_fingerprint, "tokenizer_fingerprint")
        _fingerprint(self.index_fingerprint, "index_fingerprint")
        _optional_id(self.version_manifest_id, "version_manifest_id")
        _optional_fingerprint(
            self.implementation_fingerprint,
            "implementation_fingerprint",
        )
        if self.answer_claim_id:
            _id(self.answer_claim_id, "answer_claim_id")
        else:
            object.__setattr__(
                self,
                "answer_claim_id",
                stable_resource_contract_id(
                    "claim",
                    "AnswerClaim",
                    {
                        "state": self.state,
                        "reason_codes": list(self.reason_codes),
                        "claim_requirement_id": self.claim_requirement_id,
                        "coverage_ledger_id": self.coverage_ledger_id,
                        "evidence_snapshot_ids": list(self.evidence_snapshot_ids),
                        "source_fingerprint": self.source_fingerprint,
                        "parser_fingerprint": self.parser_fingerprint,
                        "tokenizer_fingerprint": self.tokenizer_fingerprint,
                        "index_fingerprint": self.index_fingerprint,
                        "version_manifest_id": self.version_manifest_id,
                        "implementation_fingerprint": self.implementation_fingerprint,
                    },
                ),
            )

    @classmethod
    def create(cls, **values: Any) -> "AnswerClaim":
        values = dict(values)
        for field_name in ("reason_codes", "evidence_snapshot_ids"):
            if field_name in values:
                values[field_name] = list(values[field_name])
        if {"answer_claim_id", "version_manifest_id", "implementation_fingerprint"}.intersection(
            values
        ):
            return cls.from_persistence_dict(values)
        return cls.from_dict(values)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "state": self.state,
            "reason_codes": list(self.reason_codes),
            "claim_requirement_id": self.claim_requirement_id,
            "coverage_ledger_id": self.coverage_ledger_id,
            "evidence_snapshot_ids": list(self.evidence_snapshot_ids),
            "source_fingerprint": self.source_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "tokenizer_fingerprint": self.tokenizer_fingerprint,
            "index_fingerprint": self.index_fingerprint,
        }
        _assert_public_contract(payload, "answer_claim")
        return payload

    def to_persistence_dict(self) -> dict[str, Any]:
        payload = {
            "answer_claim_id": self.answer_claim_id,
            **self.to_dict(),
            "version_manifest_id": self.version_manifest_id,
            "implementation_fingerprint": self.implementation_fingerprint,
        }
        payload = _without_none(payload)
        _assert_public_contract(payload, "answer_claim.persistence")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnswerClaim":
        item = _mapping(value, "answer_claim")
        _require_exact_keys(item, _ANSWER_CLAIM_PUBLIC_KEYS, "answer_claim")
        return cls(
            state=_required_str(item, "state"),
            reason_codes=_tuple_strings(item, "reason_codes", codes=True),
            claim_requirement_id=_required_str(item, "claim_requirement_id"),
            coverage_ledger_id=_required_str(item, "coverage_ledger_id"),
            evidence_snapshot_ids=_tuple_strings(item, "evidence_snapshot_ids", ids=True),
            source_fingerprint=_required_str(item, "source_fingerprint"),
            parser_fingerprint=_required_str(item, "parser_fingerprint"),
            tokenizer_fingerprint=_required_str(item, "tokenizer_fingerprint"),
            index_fingerprint=_required_str(item, "index_fingerprint"),
        )

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "AnswerClaim":
        item = _mapping(value, "answer_claim.persistence")
        _require_exact_keys(
            item,
            _ANSWER_CLAIM_PERSISTENCE_KEYS,
            "answer_claim.persistence",
            required={"answer_claim_id"} | _ANSWER_CLAIM_PUBLIC_KEYS,
        )
        return cls(
            answer_claim_id=_required_str(item, "answer_claim_id"),
            state=_required_str(item, "state"),
            reason_codes=_tuple_strings(item, "reason_codes", codes=True),
            claim_requirement_id=_required_str(item, "claim_requirement_id"),
            coverage_ledger_id=_required_str(item, "coverage_ledger_id"),
            evidence_snapshot_ids=_tuple_strings(item, "evidence_snapshot_ids", ids=True),
            source_fingerprint=_required_str(item, "source_fingerprint"),
            parser_fingerprint=_required_str(item, "parser_fingerprint"),
            tokenizer_fingerprint=_required_str(item, "tokenizer_fingerprint"),
            index_fingerprint=_required_str(item, "index_fingerprint"),
            version_manifest_id=_optional_str(item, "version_manifest_id"),
            implementation_fingerprint=_optional_str(item, "implementation_fingerprint"),
        )


def fingerprint_manifest(
    *,
    source_fingerprint: str,
    parser_fingerprint: str,
    tokenizer_fingerprint: str,
    index_fingerprint: str,
    implementation_fingerprint: str,
    index_freshness: str = "fresh",
    **versions: str,
) -> VersionManifest:
    """Named factory kept small for downstream index/persistence adapters."""

    return VersionManifest.create(
        source_fingerprint=source_fingerprint,
        parser_fingerprint=parser_fingerprint,
        tokenizer_fingerprint=tokenizer_fingerprint,
        index_fingerprint=index_fingerprint,
        implementation_fingerprint=implementation_fingerprint,
        index_freshness=index_freshness,
        **versions,
    )


def validate_fingerprint_binding(
    observed: VersionManifest,
    expected: VersionManifest,
) -> bool:
    if not isinstance(observed, VersionManifest) or not isinstance(expected, VersionManifest):
        raise ContractValidationError("fingerprint binding requires VersionManifest values")
    return observed.usable_for_claim(expected)


def _dataclass_payload(value: Any) -> dict[str, Any]:
    payload = _public_plain(value)
    if not isinstance(payload, dict):
        raise ContractValidationError("contract payload must be an object")
    return payload


def _validate_exclusion_proof(item: SourceInventoryItem) -> None:
    fields = (
        item.exclusion_policy_version_id,
        item.exclusion_authorized_actor_id,
        item.exclusion_reason_code,
        item.exclusion_claim_scope_proof_sha256,
    )
    if item.processing_state == "intentionally_excluded":
        if any(value is None for value in fields):
            raise ContractValidationError(
                "intentionally_excluded inventory items require complete exclusion proof"
            )
        _id(item.exclusion_policy_version_id, "exclusion_policy_version_id")
        _id(item.exclusion_authorized_actor_id, "exclusion_authorized_actor_id")
        _choice(
            item.exclusion_reason_code,
            EXCLUSION_REASON_CODE_VALUES,
            "exclusion_reason_code",
        )
        _fingerprint(
            item.exclusion_claim_scope_proof_sha256,
            "exclusion_claim_scope_proof_sha256",
        )
        return
    if any(value is not None for value in fields):
        raise ContractValidationError(
            "exclusion proof fields are only valid for intentionally_excluded items"
        )


def _public_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {
            key: _public_plain(item) for key, item in value.__dict__.items() if item is not None
        }
    if isinstance(value, Mapping):
        return {str(key): _public_plain(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_public_plain(item) for item in value]
    return value


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _assert_public_contract(payload: Any, context: str) -> None:
    _walk_forbidden_keys(payload, context)
    # The shared public-safety helper intentionally rejects fields containing
    # words such as ``token``.  ``tokenizer_fingerprint`` is an approved
    # opaque version binding in this contract, so validate its values while
    # shielding only that approved field name from the generic field-name rule.
    assert_no_public_raw_references(_public_safety_view(payload), context)


def _public_safety_view(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            (
                "tfp"
                if key in {"tokenizer_fingerprint", "tokenizer_version"}
                else "ab"
                if key == "authorization_binding"
                else key
            ): _public_safety_view(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_public_safety_view(item) for item in value]
    return value


def _walk_forbidden_keys(value: Any, context: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _FORBIDDEN_PUBLIC_KEYS or normalized.endswith("_locator"):
                raise ContractValidationError(f"{context} contains forbidden public field {key!r}")
            _walk_forbidden_keys(item, f"{context}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk_forbidden_keys(item, f"{context}[{index}]")


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{context} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    allowed: set[str] | frozenset[str],
    context: str,
    *,
    required: set[str] | frozenset[str] | None = None,
) -> None:
    required_keys = allowed if required is None else required
    unknown = set(value) - set(allowed)
    missing = set(required_keys) - set(value)
    if unknown:
        raise ContractValidationError(
            f"{context} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise ContractValidationError(
            f"{context} is missing required fields: {', '.join(sorted(missing))}"
        )


def _required_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if field_name not in value:
        raise ContractValidationError(f"{field_name} is required")
    return _mapping(value[field_name], field_name)


def _optional_mapping(
    value: Mapping[str, Any], field_name: str, default: Mapping[str, Any]
) -> Mapping[str, Any]:
    if field_name not in value or value[field_name] is None:
        return default
    return _mapping(value[field_name], field_name)


def _required_list(value: Mapping[str, Any], field_name: str) -> list[Any]:
    if field_name not in value or not isinstance(value[field_name], list):
        raise ContractValidationError(f"{field_name} must be a list")
    return value[field_name]


def _required_str(value: Mapping[str, Any], field_name: str) -> str:
    if field_name not in value:
        raise ContractValidationError(f"{field_name} is required")
    return _text(value[field_name], field_name)


def _optional_str(value: Mapping[str, Any], field_name: str) -> str | None:
    if field_name not in value or value[field_name] is None:
        return None
    return _text(value[field_name], field_name)


def _required_int(value: Mapping[str, Any], field_name: str) -> int:
    if field_name not in value:
        raise ContractValidationError(f"{field_name} is required")
    return _strict_int(value[field_name], field_name)


def _optional_int(value: Mapping[str, Any], field_name: str, default: int) -> int:
    if field_name not in value or value[field_name] is None:
        return default
    return _strict_int(value[field_name], field_name)


def _required_bool(value: Mapping[str, Any], field_name: str) -> bool:
    if field_name not in value:
        raise ContractValidationError(f"{field_name} is required")
    return _strict_bool(value[field_name], field_name)


def _strict_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    return value


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractValidationError(f"{field_name} must be a boolean")
    return value


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    if "\x00" in value:
        raise ContractValidationError(f"{field_name} contains NUL")
    return value


def _optional_text(value: Any, field_name: str) -> None:
    if value is not None:
        _text(value, field_name)


def _id(value: Any, field_name: str) -> str:
    result = _text(value, field_name)
    if not _SAFE_ID.fullmatch(result):
        raise ContractValidationError(f"{field_name} must be a safe identifier")
    return result


def _optional_id(value: Any, field_name: str) -> None:
    if value is not None:
        _id(value, field_name)


def _opaque_binding(value: Any, field_name: str) -> str:
    result = _text(value, field_name)
    if _SHA256.fullmatch(result) or _SAFE_ID.fullmatch(result):
        return result
    raise ContractValidationError(
        f"{field_name} must be a safe opaque identifier or sha256 fingerprint"
    )


def _fingerprint(value: Any, field_name: str) -> str:
    result = _text(value, field_name)
    if not _SHA256.fullmatch(result):
        raise ContractValidationError(f"{field_name} must be a sha256 fingerprint")
    return result


def _optional_fingerprint(value: Any, field_name: str) -> None:
    if value is not None:
        _fingerprint(value, field_name)


def _choice(value: Any, choices: Sequence[str], field_name: str) -> str:
    result = _text(value, field_name)
    if result not in choices:
        raise ContractValidationError(f"{field_name} must be one of {', '.join(choices)}")
    return result


def _positive_int(value: Any, field_name: str) -> int:
    result = _strict_int(value, field_name)
    if result <= 0:
        raise ContractValidationError(f"{field_name} must be positive")
    return result


def _nonnegative_int(value: Any, field_name: str) -> int:
    result = _strict_int(value, field_name)
    if result < 0:
        raise ContractValidationError(f"{field_name} must be non-negative")
    return result


def _safe_mapping(value: Mapping[str, Any], field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be an object")
    _validate_json_value(value, field_name)
    _assert_public_contract(value, field_name)


def _safe_mapping_sequence(value: Sequence[Mapping[str, Any]], field_name: str) -> None:
    if not isinstance(value, tuple):
        raise ContractValidationError(f"{field_name} must be an immutable tuple")
    for entry in value:
        _safe_mapping(entry, field_name)


def _validate_json_value(value: Any, field_name: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError(f"{field_name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractValidationError(f"{field_name} keys must be strings")
            _validate_json_value(item, f"{field_name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{field_name}[{index}]")
        return
    raise ContractValidationError(f"{field_name} contains an unsupported value")


def _tuple_of(value: Any, item_type: type[Any], field_name: str) -> None:
    if not isinstance(value, tuple) or any(not isinstance(item, item_type) for item in value):
        raise ContractValidationError(f"{field_name} must be an immutable tuple of records")


def _tuple_of_strings(
    value: Any, field_name: str, *, ids: bool = False, codes: bool = False
) -> None:
    if not isinstance(value, tuple):
        raise ContractValidationError(f"{field_name} must be an immutable tuple")
    for item in value:
        if codes:
            result = _text(item, field_name)
            if not _SAFE_CODE.fullmatch(result):
                raise ContractValidationError(f"{field_name} contains an invalid reason code")
        elif ids:
            _id(item, field_name)
        else:
            _text(item, field_name)


def _tuple_strings(
    value: Mapping[str, Any],
    field_name: str,
    *,
    ids: bool = False,
    codes: bool = False,
) -> tuple[str, ...]:
    if field_name not in value:
        return ()
    raw = value[field_name]
    if not isinstance(raw, list):
        raise ContractValidationError(f"{field_name} must be a list")
    result = tuple(_text(item, field_name) for item in raw)
    if ids:
        _tuple_of_strings(result, field_name, ids=True)
    if codes:
        _tuple_of_strings(result, field_name, codes=True)
    return result


def _without_none(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


__all__ = [
    "ANSWER_CLAIM_STATE_VALUES",
    "AnswerClaim",
    "AnswerClaimState",
    "CELL_STATE_VALUES",
    "ClaimRequirement",
    "ClaimRequirementKind",
    "COVERAGE_FALLBACK_STATUS_VALUES",
    "COVERAGE_PROOF_KIND_VALUES",
    "CoverageAuthorizationBinding",
    "CoverageFallbackStatus",
    "CoverageFallbackUsage",
    "CoverageLedger",
    "CoverageProofKind",
    "CoverageProofRecord",
    "CoverageVersionBinding",
    "DisplayPagination",
    "EvidenceVersionManifest",
    "EXCLUSION_REASON_CODE_VALUES",
    "FingerprintManifest",
    "INDEX_FRESHNESS_VALUES",
    "IndexFreshness",
    "PROCESSING_STATE_VALUES",
    "ProcessingState",
    "RAW_RETENTION_STATE_VALUES",
    "RawRetentionState",
    "SourceInventory",
    "SourceInventoryItem",
    "SourceInventoryRecord",
    "StructuralCell",
    "StructuralColumn",
    "StructuralObservation",
    "StructuralRow",
    "VersionManifest",
    "fingerprint_manifest",
    "validate_fingerprint_binding",
]
