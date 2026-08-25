from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from typing import Any, Mapping, Sequence

from .primitives import (
    ContractValidationError,
    sha256_json,
    stable_resource_contract_id,
    to_plain,
)
from .public_safety import assert_no_public_raw_references


class SourceInventoryProcessingState(StrEnum):
    PARSED = "parsed"
    PRESERVED_UNPARSED = "preserved_unparsed"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    INTENTIONALLY_EXCLUDED = "intentionally_excluded"


class SourceInventoryRawRetentionState(StrEnum):
    RETAINED = "retained"
    DELETED_BY_POLICY = "deleted_by_policy"
    EXTERNALLY_MANAGED = "externally_managed"


_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNSAFE_LOCATION_PARTS = {
    "backend",
    "directory",
    "filename",
    "object",
    "path",
    "raw",
    "scratch",
    "uri",
    "url",
}
_EXCLUSION_FIELD_NAMES = {
    "exclusion_policy_id",
    "exclusion_policy_version",
    "exclusion_authorized_actor_id",
    "exclusion_reason",
    "exclusion_out_of_scope_proof_fingerprint",
}


@dataclass(frozen=True)
class SourceInventoryItem:
    source_inventory_item_id: str
    source_asset_id: str
    structure_kind: str
    content_type: str
    ordinal: int
    processing_state: SourceInventoryProcessingState
    raw_retention_state: SourceInventoryRawRetentionState
    source_fingerprint: str
    parser_fingerprint: str
    permission_fingerprint: str
    permission_scope: dict[str, Any]
    location: dict[str, Any]
    exclusion_policy_id: str | None = None
    exclusion_policy_version: str | None = None
    exclusion_authorized_actor_id: str | None = None
    exclusion_reason: str | None = None
    exclusion_out_of_scope_proof_fingerprint: str | None = None

    @classmethod
    def create(
        cls,
        *,
        source_asset_id: str,
        structure_kind: str,
        content_type: str,
        ordinal: int,
        processing_state: str | SourceInventoryProcessingState,
        raw_retention_state: str | SourceInventoryRawRetentionState,
        source_fingerprint: str,
        parser_fingerprint: str,
        permission_scope: Mapping[str, Any] | Any,
        location: Mapping[str, Any],
        exclusion_policy_id: str | None = None,
        exclusion_policy_version: str | None = None,
        exclusion_authorized_actor_id: str | None = None,
        exclusion_reason: str | None = None,
        exclusion_out_of_scope_proof_fingerprint: str | None = None,
    ) -> "SourceInventoryItem":
        canonical_permission_scope = _canonical_mapping(permission_scope, "permission_scope")
        canonical_location = _canonical_mapping(location, "location")
        permission_fingerprint = sha256_json(canonical_permission_scope)
        identity = _source_inventory_item_identity(
            source_asset_id=source_asset_id,
            structure_kind=structure_kind,
            ordinal=ordinal,
            source_fingerprint=source_fingerprint,
            permission_fingerprint=permission_fingerprint,
            location=canonical_location,
            exclusion_policy_id=exclusion_policy_id,
            exclusion_policy_version=exclusion_policy_version,
            exclusion_authorized_actor_id=exclusion_authorized_actor_id,
            exclusion_reason=exclusion_reason,
            exclusion_out_of_scope_proof_fingerprint=(exclusion_out_of_scope_proof_fingerprint),
        )
        item = cls(
            source_inventory_item_id=stable_resource_contract_id(
                "srcinvitem",
                "SourceInventoryItem",
                identity,
            ),
            source_asset_id=source_asset_id,
            structure_kind=structure_kind,
            content_type=content_type,
            ordinal=ordinal,
            processing_state=_processing_state(processing_state),
            raw_retention_state=_raw_retention_state(raw_retention_state),
            source_fingerprint=source_fingerprint,
            parser_fingerprint=parser_fingerprint,
            permission_fingerprint=permission_fingerprint,
            permission_scope=canonical_permission_scope,
            location=canonical_location,
            exclusion_policy_id=exclusion_policy_id,
            exclusion_policy_version=exclusion_policy_version,
            exclusion_authorized_actor_id=exclusion_authorized_actor_id,
            exclusion_reason=exclusion_reason,
            exclusion_out_of_scope_proof_fingerprint=(exclusion_out_of_scope_proof_fingerprint),
        )
        item._validate()
        return item

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceInventoryItem":
        data = _canonical_mapping(value, "SourceInventoryItem")
        _require_keys(
            data,
            required={
                "source_inventory_item_id",
                "source_asset_id",
                "structure_kind",
                "content_type",
                "ordinal",
                "processing_state",
                "raw_retention_state",
                "source_fingerprint",
                "parser_fingerprint",
                "permission_fingerprint",
                "permission_scope",
                "location",
            },
            optional=_EXCLUSION_FIELD_NAMES,
            context="SourceInventoryItem",
        )
        item = cls(
            source_inventory_item_id=_nonempty_string(
                data["source_inventory_item_id"],
                "SourceInventoryItem.source_inventory_item_id",
            ),
            source_asset_id=_nonempty_string(
                data["source_asset_id"],
                "SourceInventoryItem.source_asset_id",
            ),
            structure_kind=_nonempty_string(
                data["structure_kind"],
                "SourceInventoryItem.structure_kind",
            ),
            content_type=_nonempty_string(
                data["content_type"],
                "SourceInventoryItem.content_type",
            ),
            ordinal=_nonnegative_int(data["ordinal"], "SourceInventoryItem.ordinal"),
            processing_state=_processing_state(data["processing_state"]),
            raw_retention_state=_raw_retention_state(data["raw_retention_state"]),
            source_fingerprint=_fingerprint(
                data["source_fingerprint"],
                "SourceInventoryItem.source_fingerprint",
            ),
            parser_fingerprint=_fingerprint(
                data["parser_fingerprint"],
                "SourceInventoryItem.parser_fingerprint",
            ),
            permission_fingerprint=_fingerprint(
                data["permission_fingerprint"],
                "SourceInventoryItem.permission_fingerprint",
            ),
            permission_scope=_canonical_mapping(
                data["permission_scope"],
                "SourceInventoryItem.permission_scope",
            ),
            location=_canonical_mapping(
                data["location"],
                "SourceInventoryItem.location",
            ),
            exclusion_policy_id=data.get("exclusion_policy_id"),
            exclusion_policy_version=data.get("exclusion_policy_version"),
            exclusion_authorized_actor_id=data.get("exclusion_authorized_actor_id"),
            exclusion_reason=data.get("exclusion_reason"),
            exclusion_out_of_scope_proof_fingerprint=data.get(
                "exclusion_out_of_scope_proof_fingerprint"
            ),
        )
        item._validate()
        return item

    def to_dict(self) -> dict[str, Any]:
        self._validate()
        data = {
            "source_inventory_item_id": self.source_inventory_item_id,
            "source_asset_id": self.source_asset_id,
            "structure_kind": self.structure_kind,
            "content_type": self.content_type,
            "ordinal": self.ordinal,
            "processing_state": self.processing_state.value,
            "raw_retention_state": self.raw_retention_state.value,
            "source_fingerprint": self.source_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "permission_fingerprint": self.permission_fingerprint,
            "permission_scope": to_plain(self.permission_scope),
            "location": to_plain(self.location),
        }
        for field_name in _EXCLUSION_FIELD_NAMES:
            field_value = getattr(self, field_name)
            if field_value is not None:
                data[field_name] = field_value
        return data

    def _validate(self) -> None:
        _nonempty_string(
            self.source_inventory_item_id,
            "SourceInventoryItem.source_inventory_item_id",
        )
        _nonempty_string(self.source_asset_id, "SourceInventoryItem.source_asset_id")
        _nonempty_string(self.structure_kind, "SourceInventoryItem.structure_kind")
        _nonempty_string(self.content_type, "SourceInventoryItem.content_type")
        _nonnegative_int(self.ordinal, "SourceInventoryItem.ordinal")
        _processing_state(self.processing_state)
        _raw_retention_state(self.raw_retention_state)
        _fingerprint(self.source_fingerprint, "SourceInventoryItem.source_fingerprint")
        _fingerprint(self.parser_fingerprint, "SourceInventoryItem.parser_fingerprint")
        _fingerprint(
            self.permission_fingerprint,
            "SourceInventoryItem.permission_fingerprint",
        )
        permission_scope = _canonical_mapping(
            self.permission_scope,
            "SourceInventoryItem.permission_scope",
        )
        location = _canonical_mapping(self.location, "SourceInventoryItem.location")
        if not location.get("source_local_key"):
            raise ContractValidationError(
                "SourceInventoryItem.location.source_local_key is required"
            )
        _validate_location_keys(location)
        assert_no_public_raw_references(permission_scope, "source_inventory_permission_scope")
        assert_no_public_raw_references(location, "source_inventory_location")
        _validate_exclusion_contract(
            processing_state=self.processing_state,
            exclusion_policy_id=self.exclusion_policy_id,
            exclusion_policy_version=self.exclusion_policy_version,
            exclusion_authorized_actor_id=self.exclusion_authorized_actor_id,
            exclusion_reason=self.exclusion_reason,
            exclusion_out_of_scope_proof_fingerprint=(
                self.exclusion_out_of_scope_proof_fingerprint
            ),
            source_fingerprint=self.source_fingerprint,
            parser_fingerprint=self.parser_fingerprint,
            permission_fingerprint=self.permission_fingerprint,
        )
        expected_permission_fingerprint = sha256_json(permission_scope)
        if self.permission_fingerprint != expected_permission_fingerprint:
            raise ContractValidationError(
                "SourceInventoryItem.permission_fingerprint does not match permission_scope"
            )
        expected_id = stable_resource_contract_id(
            "srcinvitem",
            "SourceInventoryItem",
            _source_inventory_item_identity(
                source_asset_id=self.source_asset_id,
                structure_kind=self.structure_kind,
                ordinal=self.ordinal,
                source_fingerprint=self.source_fingerprint,
                permission_fingerprint=self.permission_fingerprint,
                location=location,
                exclusion_policy_id=self.exclusion_policy_id,
                exclusion_policy_version=self.exclusion_policy_version,
                exclusion_authorized_actor_id=self.exclusion_authorized_actor_id,
                exclusion_reason=self.exclusion_reason,
                exclusion_out_of_scope_proof_fingerprint=(
                    self.exclusion_out_of_scope_proof_fingerprint
                ),
            ),
        )
        if self.source_inventory_item_id != expected_id:
            raise ContractValidationError(
                "SourceInventoryItem.source_inventory_item_id is not deterministic"
            )


@dataclass(frozen=True)
class SourceInventory:
    source_inventory_id: str
    source_asset_id: str
    source_fingerprint: str
    parser_fingerprint: str
    permission_fingerprint: str
    items: tuple[SourceInventoryItem, ...]
    created_at: str

    @classmethod
    def create(
        cls,
        *,
        source_asset_id: str,
        items: Sequence[SourceInventoryItem | Mapping[str, Any]],
        source_fingerprint: str,
        parser_fingerprint: str,
        created_at: str,
        permission_fingerprint: str | None = None,
    ) -> "SourceInventory":
        canonical_items = tuple(
            sorted(
                (
                    item
                    if isinstance(item, SourceInventoryItem)
                    else SourceInventoryItem.from_dict(item)
                    for item in items
                ),
                key=lambda item: (item.ordinal, item.source_inventory_item_id),
            )
        )
        if canonical_items:
            item_permission_fingerprints = {item.permission_fingerprint for item in canonical_items}
            if len(item_permission_fingerprints) != 1:
                raise ContractValidationError(
                    "SourceInventory items must share one permission_fingerprint"
                )
            derived_permission_fingerprint = next(iter(item_permission_fingerprints))
            if (
                permission_fingerprint is not None
                and permission_fingerprint != derived_permission_fingerprint
            ):
                raise ContractValidationError(
                    "SourceInventory.permission_fingerprint does not match items"
                )
            permission_fingerprint = derived_permission_fingerprint
        if permission_fingerprint is None:
            raise ContractValidationError(
                "SourceInventory.permission_fingerprint is required for an empty inventory"
            )
        inventory = cls(
            source_inventory_id=stable_resource_contract_id(
                "srcinv",
                "SourceInventory",
                _source_inventory_identity(
                    source_asset_id=source_asset_id,
                    source_fingerprint=source_fingerprint,
                    parser_fingerprint=parser_fingerprint,
                    permission_fingerprint=permission_fingerprint,
                    items=canonical_items,
                ),
            ),
            source_asset_id=source_asset_id,
            source_fingerprint=source_fingerprint,
            parser_fingerprint=parser_fingerprint,
            permission_fingerprint=permission_fingerprint,
            items=canonical_items,
            created_at=created_at,
        )
        inventory._validate()
        return inventory

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceInventory":
        data = _canonical_mapping(value, "SourceInventory")
        _require_keys(
            data,
            required={
                "source_inventory_id",
                "source_asset_id",
                "source_fingerprint",
                "parser_fingerprint",
                "permission_fingerprint",
                "items",
                "created_at",
            },
            context="SourceInventory",
        )
        raw_items = data["items"]
        if not isinstance(raw_items, list):
            raise ContractValidationError("SourceInventory.items must be a list")
        inventory = cls(
            source_inventory_id=_nonempty_string(
                data["source_inventory_id"],
                "SourceInventory.source_inventory_id",
            ),
            source_asset_id=_nonempty_string(
                data["source_asset_id"],
                "SourceInventory.source_asset_id",
            ),
            source_fingerprint=_fingerprint(
                data["source_fingerprint"],
                "SourceInventory.source_fingerprint",
            ),
            parser_fingerprint=_fingerprint(
                data["parser_fingerprint"],
                "SourceInventory.parser_fingerprint",
            ),
            permission_fingerprint=_fingerprint(
                data["permission_fingerprint"],
                "SourceInventory.permission_fingerprint",
            ),
            items=tuple(SourceInventoryItem.from_dict(item) for item in raw_items),
            created_at=_timestamp(data["created_at"], "SourceInventory.created_at"),
        )
        inventory._validate()
        return inventory

    def to_dict(self) -> dict[str, Any]:
        self._validate()
        return {
            "source_inventory_id": self.source_inventory_id,
            "source_asset_id": self.source_asset_id,
            "source_fingerprint": self.source_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "permission_fingerprint": self.permission_fingerprint,
            "items": [item.to_dict() for item in self.items],
            "created_at": self.created_at,
        }

    def _validate(self) -> None:
        _nonempty_string(self.source_inventory_id, "SourceInventory.source_inventory_id")
        _nonempty_string(self.source_asset_id, "SourceInventory.source_asset_id")
        _fingerprint(self.source_fingerprint, "SourceInventory.source_fingerprint")
        _fingerprint(self.parser_fingerprint, "SourceInventory.parser_fingerprint")
        _fingerprint(
            self.permission_fingerprint,
            "SourceInventory.permission_fingerprint",
        )
        _timestamp(self.created_at, "SourceInventory.created_at")
        canonical_items = tuple(
            sorted(self.items, key=lambda item: (item.ordinal, item.source_inventory_item_id))
        )
        if self.items != canonical_items:
            raise ContractValidationError("SourceInventory.items must use canonical ordering")
        item_ids: set[str] = set()
        source_local_keys: set[str] = set()
        for item in self.items:
            item._validate()
            if item.source_asset_id != self.source_asset_id:
                raise ContractValidationError(
                    "SourceInventory item source_asset_id does not match inventory"
                )
            if item.source_fingerprint != self.source_fingerprint:
                raise ContractValidationError(
                    "SourceInventory item source_fingerprint does not match inventory"
                )
            if item.parser_fingerprint != self.parser_fingerprint:
                raise ContractValidationError(
                    "SourceInventory item parser_fingerprint does not match inventory"
                )
            if item.permission_fingerprint != self.permission_fingerprint:
                raise ContractValidationError(
                    "SourceInventory item permission_fingerprint does not match inventory"
                )
            if item.source_inventory_item_id in item_ids:
                raise ContractValidationError("SourceInventory item ids must be unique")
            item_ids.add(item.source_inventory_item_id)
            source_local_key = str(item.location["source_local_key"])
            if source_local_key in source_local_keys:
                raise ContractValidationError(
                    "SourceInventory location.source_local_key values must be unique"
                )
            source_local_keys.add(source_local_key)
        expected_id = stable_resource_contract_id(
            "srcinv",
            "SourceInventory",
            _source_inventory_identity(
                source_asset_id=self.source_asset_id,
                source_fingerprint=self.source_fingerprint,
                parser_fingerprint=self.parser_fingerprint,
                permission_fingerprint=self.permission_fingerprint,
                items=self.items,
            ),
        )
        if self.source_inventory_id != expected_id:
            raise ContractValidationError(
                "SourceInventory.source_inventory_id is not deterministic"
            )
        assert_no_public_raw_references(self.to_safe_payload(), "source_inventory")

    def to_safe_payload(self) -> dict[str, Any]:
        return {
            "source_inventory_id": self.source_inventory_id,
            "source_asset_id": self.source_asset_id,
            "source_fingerprint": self.source_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "permission_fingerprint": self.permission_fingerprint,
            "items": [
                {
                    **item.to_dict(),
                }
                for item in self.items
            ],
            "created_at": self.created_at,
        }


def _source_inventory_item_identity(
    *,
    source_asset_id: str,
    structure_kind: str,
    ordinal: int,
    source_fingerprint: str,
    permission_fingerprint: str,
    location: Mapping[str, Any],
    exclusion_policy_id: str | None,
    exclusion_policy_version: str | None,
    exclusion_authorized_actor_id: str | None,
    exclusion_reason: str | None,
    exclusion_out_of_scope_proof_fingerprint: str | None,
) -> dict[str, Any]:
    return {
        "source_asset_id": source_asset_id,
        "structure_kind": structure_kind,
        "ordinal": ordinal,
        "source_fingerprint": source_fingerprint,
        "permission_fingerprint": permission_fingerprint,
        "location": to_plain(location),
        "exclusion_policy_id": exclusion_policy_id,
        "exclusion_policy_version": exclusion_policy_version,
        "exclusion_authorized_actor_id": exclusion_authorized_actor_id,
        "exclusion_reason": exclusion_reason,
        "exclusion_out_of_scope_proof_fingerprint": (exclusion_out_of_scope_proof_fingerprint),
    }


def _source_inventory_identity(
    *,
    source_asset_id: str,
    source_fingerprint: str,
    parser_fingerprint: str,
    permission_fingerprint: str,
    items: Sequence[SourceInventoryItem],
) -> dict[str, Any]:
    return {
        "source_asset_id": source_asset_id,
        "source_fingerprint": source_fingerprint,
        "parser_fingerprint": parser_fingerprint,
        "permission_fingerprint": permission_fingerprint,
        "source_inventory_item_ids": [item.source_inventory_item_id for item in items],
    }


def _canonical_mapping(value: Any, field_name: str) -> dict[str, Any]:
    plain = to_plain(value)
    if not isinstance(plain, dict):
        raise ContractValidationError(f"{field_name} must be an object")
    return {str(key): item for key, item in plain.items()}


def _require_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    context: str,
) -> None:
    actual = set(value)
    allowed = required | set(optional or ())
    if not required.issubset(actual) or not actual.issubset(allowed):
        missing = sorted(required - actual)
        unexpected = sorted(actual - allowed)
        raise ContractValidationError(
            f"{context} fields do not match contract; "
            f"missing={missing}, unexpected={unexpected}"
        )


def _nonempty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    assert_no_public_raw_references(value, field_name)
    return value


def _nonnegative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractValidationError(f"{field_name} must be a non-negative integer")
    return value


def _fingerprint(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_RE.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a sha256 fingerprint")
    return value


def _timestamp(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty ISO timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} must be an ISO timestamp") from exc
    return value


def _processing_state(value: Any) -> SourceInventoryProcessingState:
    try:
        return SourceInventoryProcessingState(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            "SourceInventoryItem.processing_state must be one of "
            + ", ".join(state.value for state in SourceInventoryProcessingState)
        ) from exc


def _raw_retention_state(value: Any) -> SourceInventoryRawRetentionState:
    try:
        return SourceInventoryRawRetentionState(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            "SourceInventoryItem.raw_retention_state must be one of "
            + ", ".join(state.value for state in SourceInventoryRawRetentionState)
        ) from exc


def _validate_exclusion_contract(
    *,
    processing_state: SourceInventoryProcessingState,
    exclusion_policy_id: Any,
    exclusion_policy_version: Any,
    exclusion_authorized_actor_id: Any,
    exclusion_reason: Any,
    exclusion_out_of_scope_proof_fingerprint: Any,
    source_fingerprint: str,
    parser_fingerprint: str,
    permission_fingerprint: str,
) -> None:
    values = {
        "exclusion_policy_id": exclusion_policy_id,
        "exclusion_policy_version": exclusion_policy_version,
        "exclusion_authorized_actor_id": exclusion_authorized_actor_id,
        "exclusion_reason": exclusion_reason,
        "exclusion_out_of_scope_proof_fingerprint": (exclusion_out_of_scope_proof_fingerprint),
    }
    if processing_state != SourceInventoryProcessingState.INTENTIONALLY_EXCLUDED:
        populated = sorted(key for key, value in values.items() if value is not None)
        if populated:
            raise ContractValidationError(
                "exclusion proof fields are only valid for intentionally_excluded items: "
                + ", ".join(populated)
            )
        return

    policy_id = _nonempty_string(
        exclusion_policy_id,
        "SourceInventoryItem.exclusion_policy_id",
    )
    policy_version = _nonempty_string(
        exclusion_policy_version,
        "SourceInventoryItem.exclusion_policy_version",
    )
    actor_id = _nonempty_string(
        exclusion_authorized_actor_id,
        "SourceInventoryItem.exclusion_authorized_actor_id",
    )
    reason = _nonempty_string(
        exclusion_reason,
        "SourceInventoryItem.exclusion_reason",
    )
    proof_fingerprint = _fingerprint(
        exclusion_out_of_scope_proof_fingerprint,
        "SourceInventoryItem.exclusion_out_of_scope_proof_fingerprint",
    )
    assert_no_public_raw_references(
        {
            "exclusion_policy_id": policy_id,
            "exclusion_policy_version": policy_version,
            "exclusion_authorized_actor_id": actor_id,
            "exclusion_reason": reason,
            "exclusion_out_of_scope_proof_fingerprint": proof_fingerprint,
        },
        "source_inventory_exclusion_proof",
    )
    if proof_fingerprint in {
        source_fingerprint,
        parser_fingerprint,
        permission_fingerprint,
    }:
        raise ContractValidationError(
            "intentionally_excluded requires an independent out-of-scope proof fingerprint"
        )


def _validate_location_keys(location: Mapping[str, Any]) -> None:
    for key in location:
        normalized_key = re.sub(r"[^A-Za-z0-9]+", "_", str(key)).strip("_").lower()
        if (
            normalized_key in _EXCLUSION_FIELD_NAMES
            or normalized_key.startswith("exclusion_")
            or "out_of_scope" in normalized_key
        ):
            raise ContractValidationError(
                "SourceInventoryItem exclusion proof must use canonical typed fields"
            )
        normalized_parts = {part for part in normalized_key.split("_") if part}
        if normalized_parts & _UNSAFE_LOCATION_PARTS and not str(key).endswith("_fingerprint"):
            raise ContractValidationError(
                f"SourceInventoryItem.location field {key!r} may expose a raw locator"
            )


__all__ = [
    "SourceInventory",
    "SourceInventoryItem",
    "SourceInventoryProcessingState",
    "SourceInventoryRawRetentionState",
]
