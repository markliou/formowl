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
class CoverageLedger:
    query_id: str
    claim_requirement_id: str
    relevant_inventory_item_ids: tuple[str, ...]
    searched_observation_ids: tuple[str, ...]
    omitted_inventory_item_ids: tuple[str, ...] = ()
    failed_inventory_item_ids: tuple[str, ...] = ()
    unsupported_inventory_item_ids: tuple[str, ...] = ()
    redacted_inventory_item_ids: tuple[str, ...] = ()
    fallback_facts: tuple[Mapping[str, Any], ...] = ()
    freshness_facts: Mapping[str, Any] = field(default_factory=dict)
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
        relevant_inventory_item_ids: Sequence[str],
        searched_observation_ids: Sequence[str],
        omitted_inventory_item_ids: Sequence[str] = (),
        failed_inventory_item_ids: Sequence[str] = (),
        unsupported_inventory_item_ids: Sequence[str] = (),
        redacted_inventory_item_ids: Sequence[str] = (),
        fallback_facts: Sequence[Mapping[str, Any]] = (),
        freshness_facts: Mapping[str, Any] | None = None,
        complete_authorized_scope: bool = False,
        display_pagination: DisplayPagination | None = None,
    ) -> "CoverageLedger":
        return cls(
            query_id=query_id,
            claim_requirement_id=claim_requirement_id,
            relevant_inventory_item_ids=tuple(relevant_inventory_item_ids),
            searched_observation_ids=tuple(searched_observation_ids),
            omitted_inventory_item_ids=tuple(omitted_inventory_item_ids),
            failed_inventory_item_ids=tuple(failed_inventory_item_ids),
            unsupported_inventory_item_ids=tuple(unsupported_inventory_item_ids),
            redacted_inventory_item_ids=tuple(redacted_inventory_item_ids),
            fallback_facts=tuple(fallback_facts),
            freshness_facts=dict(freshness_facts or {}),
            complete_authorized_scope=complete_authorized_scope,
            display_pagination=display_pagination or DisplayPagination(page_size=1),
        )

    def __post_init__(self) -> None:
        _id(self.query_id, "coverage_ledger.query_id")
        _id(self.claim_requirement_id, "coverage_ledger.claim_requirement_id")
        for field_name in (
            "relevant_inventory_item_ids",
            "searched_observation_ids",
            "omitted_inventory_item_ids",
            "failed_inventory_item_ids",
            "unsupported_inventory_item_ids",
            "redacted_inventory_item_ids",
        ):
            _tuple_of_strings(getattr(self, field_name), field_name, ids=True)
        _safe_mapping_sequence(self.fallback_facts, "coverage_ledger.fallback_facts")
        _safe_mapping(self.freshness_facts, "coverage_ledger.freshness_facts")
        _strict_bool(self.complete_authorized_scope, "complete_authorized_scope")
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
        if self.complete_authorized_scope and (
            self.omitted_inventory_item_ids
            or self.failed_inventory_item_ids
            or self.unsupported_inventory_item_ids
            or self.redacted_inventory_item_ids
        ):
            raise ContractValidationError(
                "complete authorized coverage cannot contain omitted or unresolved inventory"
            )
        if self.complete_authorized_scope and not self._freshness_is_usable():
            raise ContractValidationError(
                "complete authorized coverage cannot bind stale or mismatched index data"
            )
        object.__setattr__(
            self,
            "fallback_facts",
            tuple(_freeze_mapping(item) for item in self.fallback_facts),
        )
        object.__setattr__(
            self,
            "freshness_facts",
            _freeze_mapping(self.freshness_facts),
        )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "claim_requirement_id": self.claim_requirement_id,
            "relevant_inventory_item_ids": list(self.relevant_inventory_item_ids),
            "searched_observation_ids": list(self.searched_observation_ids),
            "omitted_inventory_item_ids": list(self.omitted_inventory_item_ids),
            "failed_inventory_item_ids": list(self.failed_inventory_item_ids),
            "unsupported_inventory_item_ids": list(self.unsupported_inventory_item_ids),
            "redacted_inventory_item_ids": list(self.redacted_inventory_item_ids),
            "fallback_facts": [_public_plain(dict(item)) for item in self.fallback_facts],
            "freshness_facts": _public_plain(dict(self.freshness_facts)),
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

    def _freshness_is_usable(self) -> bool:
        facts = self.freshness_facts
        for key in ("index_fresh", "fingerprints_match", "manifest_fresh"):
            if key in facts and facts[key] is not True:
                return False
        for key in ("index_freshness", "freshness_state"):
            if key in facts and facts[key] != "fresh":
                return False
        return True

    def usable_for_claim(self) -> bool:
        return self.complete_authorized_scope and self._freshness_is_usable()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageLedger":
        item = _mapping(value, "coverage_ledger")
        return cls(
            query_id=_required_str(item, "query_id"),
            claim_requirement_id=_required_str(item, "claim_requirement_id"),
            relevant_inventory_item_ids=_tuple_strings(item, "relevant_inventory_item_ids"),
            searched_observation_ids=_tuple_strings(item, "searched_observation_ids"),
            omitted_inventory_item_ids=_tuple_strings(item, "omitted_inventory_item_ids"),
            failed_inventory_item_ids=_tuple_strings(item, "failed_inventory_item_ids"),
            unsupported_inventory_item_ids=_tuple_strings(item, "unsupported_inventory_item_ids"),
            redacted_inventory_item_ids=_tuple_strings(item, "redacted_inventory_item_ids"),
            fallback_facts=tuple(
                _required_mapping(entry, "fallback_fact")
                for entry in _required_list(item, "fallback_facts")
            ),
            freshness_facts=_required_mapping(item, "freshness_facts"),
            complete_authorized_scope=_required_bool(item, "complete_authorized_scope"),
            display_pagination=DisplayPagination.from_dict(
                _required_mapping(item, "display_pagination")
            ),
            coverage_ledger_id=_required_str(item, "coverage_ledger_id"),
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
                "tfp" if key in {"tokenizer_fingerprint", "tokenizer_version"} else key
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
    "CoverageLedger",
    "DisplayPagination",
    "EvidenceVersionManifest",
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
