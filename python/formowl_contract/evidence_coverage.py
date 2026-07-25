"""Source-neutral evidence coverage and answer-claim contracts.

These contracts are deliberately independent from mail, retrieval, MCP, and
task-answering implementations.  They are the durable boundary between
source onboarding, evidence persistence, and any later consumer.

The public representation contains identifiers, governed hashes, and bounded
facts only.  Raw paths, backend locators, SQL, credentials, and private
payloads are rejected rather than silently serialized.
"""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass, replace
from enum import Enum
import hashlib
import hmac
import math
import re
import secrets
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .primitives import (
    ContractValidationError,
    now_iso,
    sha256_json,
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
_ANSWER_CLAIM_FACTORY_TOKEN = object()
_COVERAGE_AUTHORITY_CAPABILITY_TOKEN = object()
INDEX_FRESHNESS_VALUES = ("fresh", "stale", "mismatch", "unavailable")
COVERAGE_FALLBACK_STATUS_VALUES = (
    "not_required",
    "completed",
    "budget_exhausted",
    "failed",
    "cancelled",
)
COVERAGE_NON_SEARCH_REASON_VALUES = (
    "not_searched",
    "not_authorized",
    "redacted",
    "failed",
    "unsupported",
    "intentionally_excluded",
)
COVERAGE_PROOF_KIND_VALUES = (
    "structural",
    "ordinary",
    "combined",
    "intentionally_excluded",
    "fallback",
)
COVERAGE_ITEM_AUTHORIZATION_STATE_VALUES = ("authorized", "ineligible")
COVERAGE_ITEM_RELEVANCE_STATE_VALUES = ("relevant", "irrelevant")
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
    "scope_authority",
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


class CoverageNonSearchReason(str, Enum):
    NOT_SEARCHED = "not_searched"
    NOT_AUTHORIZED = "not_authorized"
    REDACTED = "redacted"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    INTENTIONALLY_EXCLUDED = "intentionally_excluded"


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

    def to_persistence_dict(self) -> dict[str, Any]:
        return _persistence_dataclass_payload(self)

    def to_public_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
    ) -> dict[str, Any]:
        decision = _require_structural_scope_decision(scope_decision)
        if decision.decision_state == "denied":
            return _structural_denial()
        return _structural_public_summary(
            decision,
            "structural_cell",
            {"cell_state": self.cell_state},
            self.to_persistence_dict(),
        )

    def to_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
    ) -> dict[str, Any]:
        return self.to_public_dict(scope_decision=scope_decision)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuralCell":
        return cls.from_persistence_dict(value)

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "StructuralCell":
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

    def to_persistence_dict(self) -> dict[str, Any]:
        return _persistence_dataclass_payload(self)

    def to_public_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
    ) -> dict[str, Any]:
        decision = _require_structural_scope_decision(scope_decision)
        if decision.decision_state == "denied":
            return _structural_denial()
        return _structural_public_summary(
            decision,
            "structural_column",
            {},
            self.to_persistence_dict(),
        )

    def to_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
    ) -> dict[str, Any]:
        return self.to_public_dict(scope_decision=scope_decision)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuralColumn":
        return cls.from_persistence_dict(value)

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "StructuralColumn":
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

    def to_persistence_dict(self) -> dict[str, Any]:
        return {
            "row_ordinal": self.row_ordinal,
            "cells": [cell.to_persistence_dict() for cell in self.cells],
        }

    def to_public_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
    ) -> dict[str, Any]:
        decision = _require_structural_scope_decision(scope_decision)
        if decision.decision_state == "denied":
            return _structural_denial()
        return _structural_public_summary(
            decision,
            "structural_row",
            {},
            self.to_persistence_dict(),
        )

    def to_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
    ) -> dict[str, Any]:
        return self.to_public_dict(scope_decision=scope_decision)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuralRow":
        return cls.from_persistence_dict(value)

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "StructuralRow":
        item = _mapping(value, "structural_row")
        return cls(
            row_ordinal=_required_int(item, "row_ordinal"),
            cells=tuple(
                StructuralCell.from_persistence_dict(cell) for cell in _required_list(item, "cells")
            ),
        )


@dataclass(frozen=True)
class IntentionalExclusionProof:
    """Typed proof that one raw unit is outside one exact claim scope.

    The proof is deliberately derived from typed source, claim, version, and
    authorization records.  It does not accept a caller-provided digest as
    evidence.  ``proof_fingerprint`` is only the deterministic fingerprint of
    this closed record and is validated on every persistence read.
    """

    source_unit_fingerprint: str
    claim_requirement_id: str
    claim_requirement_fingerprint: str
    version_manifest_id: str
    source_fingerprint: str
    parser_fingerprint: str
    permission_scope_fingerprint: str
    authorization_binding: "CoverageAuthorizationBinding"
    scope_policy: "CoverageScopePolicyBinding"
    exclusion_policy_version_id: str
    authorized_actor_id: str
    reason_code: str
    source_inventory_id: str | None = None
    source_inventory_item_id: str | None = None
    proof_id: str = ""
    proof_fingerprint: str = ""

    def __post_init__(self) -> None:
        _fingerprint(self.source_unit_fingerprint, "exclusion.source_unit_fingerprint")
        _id(self.claim_requirement_id, "exclusion.claim_requirement_id")
        _fingerprint(
            self.claim_requirement_fingerprint,
            "exclusion.claim_requirement_fingerprint",
        )
        _id(self.version_manifest_id, "exclusion.version_manifest_id")
        _fingerprint(self.source_fingerprint, "exclusion.source_fingerprint")
        _fingerprint(self.parser_fingerprint, "exclusion.parser_fingerprint")
        _fingerprint(
            self.permission_scope_fingerprint,
            "exclusion.permission_scope_fingerprint",
        )
        if not isinstance(self.authorization_binding, CoverageAuthorizationBinding):
            raise ContractValidationError("exclusion authorization binding is invalid")
        if not isinstance(self.scope_policy, CoverageScopePolicyBinding):
            raise ContractValidationError("exclusion scope policy is invalid")
        _id(
            self.exclusion_policy_version_id,
            "exclusion.exclusion_policy_version_id",
        )
        _id(self.authorized_actor_id, "exclusion.authorized_actor_id")
        _optional_id(self.source_inventory_id, "exclusion.source_inventory_id")
        _optional_id(
            self.source_inventory_item_id,
            "exclusion.source_inventory_item_id",
        )
        if (self.source_inventory_id is None) != (self.source_inventory_item_id is None):
            raise ContractValidationError(
                "exclusion aggregate and item membership bindings must be paired"
            )
        if self.authorized_actor_id != self.authorization_binding.actor_context_id:
            raise ContractValidationError(
                "exclusion authorized actor must match authorization binding"
            )
        _choice(self.reason_code, EXCLUSION_REASON_CODE_VALUES, "exclusion.reason_code")
        expected_id = stable_resource_contract_id(
            "intentional-exclusion",
            "IntentionalExclusionProof",
            self._identity_payload(),
        )
        expected_fingerprint = sha256_json(self._identity_payload())
        if self.proof_id:
            _id(self.proof_id, "exclusion.proof_id")
            if self.proof_id != expected_id:
                raise ContractValidationError("exclusion proof id does not match identity")
        else:
            object.__setattr__(self, "proof_id", expected_id)
        if self.proof_fingerprint:
            _fingerprint(self.proof_fingerprint, "exclusion.proof_fingerprint")
            if self.proof_fingerprint != expected_fingerprint:
                raise ContractValidationError("exclusion proof fingerprint does not match identity")
        else:
            object.__setattr__(self, "proof_fingerprint", expected_fingerprint)

    @classmethod
    def create(
        cls,
        *,
        source_inventory_item: "SourceInventoryItem",
        claim_requirement: "ClaimRequirement",
        version_manifest: "VersionManifest",
        authorization_binding: "CoverageAuthorizationBinding",
        scope_policy: "CoverageScopePolicyBinding",
        exclusion_policy_version_id: str,
        reason_code: str = "outside_claim_scope",
        authorized_actor_id: str | None = None,
    ) -> "IntentionalExclusionProof":
        if not isinstance(source_inventory_item, SourceInventoryItem):
            raise ContractValidationError("exclusion proof requires SourceInventoryItem")
        if not isinstance(claim_requirement, ClaimRequirement):
            raise ContractValidationError("exclusion proof requires ClaimRequirement")
        if not isinstance(version_manifest, VersionManifest):
            raise ContractValidationError("exclusion proof requires VersionManifest")
        if not isinstance(authorization_binding, CoverageAuthorizationBinding):
            raise ContractValidationError("exclusion proof authorization must be typed")
        if not isinstance(scope_policy, CoverageScopePolicyBinding):
            raise ContractValidationError("exclusion proof scope policy must be typed")
        actor_id = authorized_actor_id or authorization_binding.actor_context_id
        return cls(
            source_unit_fingerprint=_source_unit_fingerprint(source_inventory_item),
            claim_requirement_id=claim_requirement.claim_requirement_id,
            claim_requirement_fingerprint=sha256_json(claim_requirement.to_dict()),
            version_manifest_id=version_manifest.version_manifest_id,
            source_fingerprint=version_manifest.source_fingerprint,
            parser_fingerprint=version_manifest.parser_fingerprint,
            permission_scope_fingerprint=sha256_json(
                _persistence_plain(source_inventory_item.permission_scope)
            ),
            authorization_binding=authorization_binding,
            scope_policy=scope_policy,
            exclusion_policy_version_id=exclusion_policy_version_id,
            authorized_actor_id=actor_id,
            reason_code=reason_code,
            source_inventory_id=None,
            source_inventory_item_id=None,
        )

    def bind_to_inventory(
        self,
        *,
        source_inventory_id: str,
        source_inventory_item_id: str,
    ) -> "IntentionalExclusionProof":
        """Bind the proof after canonical inventory and item IDs exist."""

        _id(source_inventory_id, "exclusion.source_inventory_id")
        _id(source_inventory_item_id, "exclusion.source_inventory_item_id")
        return replace(
            self,
            source_inventory_id=source_inventory_id,
            source_inventory_item_id=source_inventory_item_id,
            proof_id="",
            proof_fingerprint="",
        )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "source_unit_fingerprint": self.source_unit_fingerprint,
            "claim_requirement_id": self.claim_requirement_id,
            "claim_requirement_fingerprint": self.claim_requirement_fingerprint,
            "version_manifest_id": self.version_manifest_id,
            "source_fingerprint": self.source_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "permission_scope_fingerprint": self.permission_scope_fingerprint,
            "authorization_binding": self.authorization_binding.to_dict(),
            "scope_policy": self.scope_policy.to_dict(),
            "exclusion_policy_version_id": self.exclusion_policy_version_id,
            "authorized_actor_id": self.authorized_actor_id,
            "reason_code": self.reason_code,
            "source_inventory_id": self.source_inventory_id,
            "source_inventory_item_id": self.source_inventory_item_id,
        }

    def to_persistence_dict(self) -> dict[str, Any]:
        return {
            **self._identity_payload(),
            "proof_id": self.proof_id,
            "proof_fingerprint": self.proof_fingerprint,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = {"status": "redacted", "reason_code": "intentionally_excluded"}
        _assert_public_contract(payload, "intentional_exclusion_proof.public")
        return payload

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "IntentionalExclusionProof":
        item = _mapping(value, "intentional_exclusion_proof")
        _require_exact_keys(
            item,
            {
                "source_unit_fingerprint",
                "claim_requirement_id",
                "claim_requirement_fingerprint",
                "version_manifest_id",
                "source_fingerprint",
                "parser_fingerprint",
                "permission_scope_fingerprint",
                "authorization_binding",
                "scope_policy",
                "exclusion_policy_version_id",
                "authorized_actor_id",
                "reason_code",
                "source_inventory_id",
                "source_inventory_item_id",
                "proof_id",
                "proof_fingerprint",
            },
            "intentional_exclusion_proof",
        )
        return cls(
            source_unit_fingerprint=_required_str(item, "source_unit_fingerprint"),
            claim_requirement_id=_required_str(item, "claim_requirement_id"),
            claim_requirement_fingerprint=_required_str(
                item,
                "claim_requirement_fingerprint",
            ),
            version_manifest_id=_required_str(item, "version_manifest_id"),
            source_fingerprint=_required_str(item, "source_fingerprint"),
            parser_fingerprint=_required_str(item, "parser_fingerprint"),
            permission_scope_fingerprint=_required_str(
                item,
                "permission_scope_fingerprint",
            ),
            authorization_binding=CoverageAuthorizationBinding.from_dict(
                _required_mapping(item, "authorization_binding")
            ),
            scope_policy=CoverageScopePolicyBinding.from_dict(
                _required_mapping(item, "scope_policy")
            ),
            exclusion_policy_version_id=_required_str(
                item,
                "exclusion_policy_version_id",
            ),
            authorized_actor_id=_required_str(item, "authorized_actor_id"),
            reason_code=_required_str(item, "reason_code"),
            source_inventory_id=_optional_str(item, "source_inventory_id"),
            source_inventory_item_id=_optional_str(item, "source_inventory_item_id"),
            proof_id=_required_str(item, "proof_id"),
            proof_fingerprint=_required_str(item, "proof_fingerprint"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntentionalExclusionProof":
        return cls.from_persistence_dict(value)

    def validate_for_claim(
        self,
        *,
        source_inventory: "SourceInventory",
        source_inventory_item: "SourceInventoryItem",
        claim_requirement: "ClaimRequirement",
        expected_manifest: "VersionManifest",
        expected_authorization_binding: "CoverageAuthorizationBinding",
        expected_scope_authority: "CoverageScopeAuthority | None" = None,
        definitive: bool = False,
    ) -> bool:
        if not all(
            isinstance(value, expected_type)
            for value, expected_type in (
                (source_inventory, SourceInventory),
                (source_inventory_item, SourceInventoryItem),
                (claim_requirement, ClaimRequirement),
                (expected_manifest, VersionManifest),
                (expected_authorization_binding, CoverageAuthorizationBinding),
            )
        ):
            raise ContractValidationError("exclusion validation requires typed inputs")
        if source_inventory_item.processing_state != "intentionally_excluded":
            return False
        if (
            source_inventory_item.source_inventory_id != source_inventory.source_inventory_id
            or self.source_inventory_id != source_inventory.source_inventory_id
            or self.source_inventory_item_id != source_inventory_item.source_inventory_item_id
            or source_inventory_item.intentional_exclusion_proof != self
            or self.source_unit_fingerprint != _source_unit_fingerprint(source_inventory_item)
            or self.claim_requirement_id != claim_requirement.claim_requirement_id
            or self.claim_requirement_fingerprint != sha256_json(claim_requirement.to_dict())
            or self.version_manifest_id != expected_manifest.version_manifest_id
            or self.source_fingerprint != expected_manifest.source_fingerprint
            or self.parser_fingerprint != expected_manifest.parser_fingerprint
            or self.permission_scope_fingerprint
            != sha256_json(_persistence_plain(source_inventory_item.permission_scope))
            or self.authorization_binding != expected_authorization_binding
            or self.authorized_actor_id != expected_authorization_binding.actor_context_id
            or expected_manifest.index_freshness != "fresh"
        ):
            return False
        if expected_scope_authority is not None:
            if not expected_scope_authority._is_trusted_for_authoritative_use:
                return False
            if not expected_scope_authority.validate_for_claim(
                source_inventory,
                claim_requirement,
                expected_manifest,
                expected_authorization_binding,
                self.scope_policy,
            ):
                return False
            if (
                source_inventory_item.source_inventory_item_id
                not in expected_scope_authority.authorized_irrelevant_item_ids
            ):
                return False
        elif definitive:
            return False
        if definitive and self.reason_code not in {
            "outside_claim_scope",
            "policy_scope_exclusion",
        }:
            return False
        return True


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
    source_inventory_id: str | None = None
    intentional_exclusion_proof: IntentionalExclusionProof | None = None
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
        _optional_id(self.source_inventory_id, "source_inventory_id")
        _validate_exclusion_proof(self)
        if self.intentional_exclusion_proof is not None and not isinstance(
            self.intentional_exclusion_proof,
            IntentionalExclusionProof,
        ):
            raise ContractValidationError("intentional exclusion proof is invalid")
        if self.intentional_exclusion_proof is not None:
            if self.source_inventory_id is not None and (
                self.intentional_exclusion_proof.source_inventory_id is None
                or self.intentional_exclusion_proof.source_inventory_item_id is None
            ):
                raise ContractValidationError(
                    "bound inventory items require bound exclusion proof membership"
                )
            if self.intentional_exclusion_proof.source_inventory_id not in (
                None,
                self.source_inventory_id,
            ):
                raise ContractValidationError(
                    "intentional exclusion proof is bound to another inventory"
                )
            if (
                self.intentional_exclusion_proof.source_inventory_item_id is not None
                and self.intentional_exclusion_proof.source_inventory_item_id
                != self.source_inventory_item_id
            ):
                raise ContractValidationError(
                    "intentional exclusion proof is bound to another inventory item"
                )
            expected_item_id = stable_resource_contract_id(
                "inventory",
                "SourceInventoryItem",
                _source_inventory_item_identity_payload(self),
            )
            if self.source_inventory_item_id != expected_item_id:
                raise ContractValidationError(
                    "source inventory item id does not match typed exclusion proof identity"
                )
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
        values.setdefault("intentional_exclusion_proof", None)
        if isinstance(values["intentional_exclusion_proof"], IntentionalExclusionProof):
            values["intentional_exclusion_proof"] = values[
                "intentional_exclusion_proof"
            ].to_persistence_dict()
        values.setdefault(
            "source_inventory_item_id",
            stable_resource_contract_id(
                "inventory",
                "SourceInventoryItem",
                _source_inventory_item_identity_payload_from_mapping(values),
            ),
        )
        return cls.from_persistence_dict(values)

    def to_persistence_dict(self) -> dict[str, Any]:
        return _persistence_dataclass_payload(self)

    def to_public_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
    ) -> dict[str, Any]:
        decision = _require_structural_scope_decision(scope_decision)
        if decision.decision_state == "denied":
            return _structural_denial()
        decision.assert_matches_permission_scope(self.permission_scope)
        return _structural_public_summary(
            decision,
            "source_inventory_item",
            {
                "structure_kind": self.structure_kind,
                "processing_state": self.processing_state,
            },
            self.to_persistence_dict(),
        )

    def to_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
    ) -> dict[str, Any]:
        return self.to_public_dict(scope_decision=scope_decision)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceInventoryItem":
        return cls.from_persistence_dict(value)

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "SourceInventoryItem":
        item = _mapping(value, "source_inventory_item")
        if {
            "exclusion_policy_version_id",
            "exclusion_authorized_actor_id",
            "exclusion_reason_code",
            "exclusion_claim_scope_proof_sha256",
        } & set(item):
            raise ContractValidationError(
                "legacy scalar exclusion fields are not accepted; use typed exclusion proof"
            )
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
            source_inventory_id=_optional_str(item, "source_inventory_id"),
            intentional_exclusion_proof=(
                None
                if item.get("intentional_exclusion_proof") is None
                else IntentionalExclusionProof.from_persistence_dict(
                    _mapping(
                        item["intentional_exclusion_proof"],
                        "source_inventory_item.intentional_exclusion_proof",
                    )
                )
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
        item_ids = [item.source_inventory_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ContractValidationError("source inventory items must have unique ids")
        for item in self.items:
            if item.source_inventory_id != self.source_inventory_id:
                raise ContractValidationError(
                    "source inventory items must belong to source_inventory_id"
                )
            if item.intentional_exclusion_proof is not None:
                if (
                    item.intentional_exclusion_proof.source_inventory_id != self.source_inventory_id
                    or item.intentional_exclusion_proof.source_inventory_item_id
                    != item.source_inventory_item_id
                ):
                    raise ContractValidationError(
                        "source inventory exclusion proof membership does not match aggregate"
                    )
            if item.source_asset_id != self.source_asset_id:
                raise ContractValidationError("source inventory items must share source_asset_id")
            if item.source_fingerprint != self.source_fingerprint:
                raise ContractValidationError(
                    "source inventory items must share source_fingerprint"
                )
            if item.parser_fingerprint != self.parser_fingerprint:
                raise ContractValidationError(
                    "source inventory items must share parser_fingerprint"
                )
        expected_source_inventory_id = self._canonical_source_inventory_id(
            source_asset_id=self.source_asset_id,
            source_fingerprint=self.source_fingerprint,
            parser_fingerprint=self.parser_fingerprint,
            items=self.items,
        )
        if self.source_inventory_id != expected_source_inventory_id:
            raise ContractValidationError(
                "source inventory id does not match canonical aggregate identity"
            )

    @staticmethod
    def _canonical_source_inventory_id(
        *,
        source_asset_id: str,
        source_fingerprint: str,
        parser_fingerprint: str,
        items: Sequence[SourceInventoryItem],
    ) -> str:
        item_payloads = [_inventory_item_identity_payload(item) for item in items]
        item_payloads.sort(
            key=lambda item: (
                item["ordinal"],
                sha256_json(item),
            )
        )
        return stable_resource_contract_id(
            "inventoryset",
            "SourceInventory",
            {
                "source_asset_id": source_asset_id,
                "source_fingerprint": source_fingerprint,
                "parser_fingerprint": parser_fingerprint,
                "items": item_payloads,
            },
        )

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
        for item in item_values:
            if not isinstance(item, SourceInventoryItem):
                raise ContractValidationError("source inventory items must be SourceInventoryItem")
            if item.source_asset_id != source_asset_id:
                raise ContractValidationError(
                    "source inventory item asset does not match aggregate"
                )
            if item.source_fingerprint != source_fingerprint:
                raise ContractValidationError(
                    "source inventory item source fingerprint does not match aggregate"
                )
            if item.parser_fingerprint != parser_fingerprint:
                raise ContractValidationError(
                    "source inventory item parser fingerprint does not match aggregate"
                )
        source_inventory_id = cls._canonical_source_inventory_id(
            source_asset_id=source_asset_id,
            source_fingerprint=source_fingerprint,
            parser_fingerprint=parser_fingerprint,
            items=item_values,
        )
        bound_items = []
        for item in item_values:
            if item.source_inventory_id not in (None, source_inventory_id):
                raise ContractValidationError(
                    "source inventory item points at a different aggregate"
                )
            if (
                item.intentional_exclusion_proof is not None
                and item.intentional_exclusion_proof.source_inventory_id
                not in (None, source_inventory_id)
            ):
                raise ContractValidationError(
                    "source inventory exclusion proof points at a different aggregate"
                )
            item_values_for_binding = item.to_persistence_dict()
            item_values_for_binding.pop("source_inventory_item_id", None)
            item_values_for_binding["source_inventory_id"] = source_inventory_id
            proof = item.intentional_exclusion_proof
            if proof is not None:
                item_id = stable_resource_contract_id(
                    "inventory",
                    "SourceInventoryItem",
                    _source_inventory_item_identity_payload_from_mapping(item_values_for_binding),
                )
                proof = proof.bind_to_inventory(
                    source_inventory_id=source_inventory_id,
                    source_inventory_item_id=item_id,
                )
                item_values_for_binding["intentional_exclusion_proof"] = proof.to_persistence_dict()
                item_values_for_binding["source_inventory_item_id"] = item_id
                bound_item = SourceInventoryItem.from_persistence_dict(item_values_for_binding)
            else:
                bound_item = SourceInventoryItem.create(**item_values_for_binding)
            bound_items.append(bound_item)
        return cls(
            source_inventory_id=source_inventory_id,
            source_asset_id=source_asset_id,
            source_fingerprint=source_fingerprint,
            parser_fingerprint=parser_fingerprint,
            items=tuple(bound_items),
            created_at=created_at or now_iso(),
        )

    def to_persistence_dict(self) -> dict[str, Any]:
        return {
            "source_inventory_id": self.source_inventory_id,
            "source_asset_id": self.source_asset_id,
            "source_fingerprint": self.source_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "items": [item.to_persistence_dict() for item in self.items],
            "created_at": self.created_at,
        }

    def to_public_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
    ) -> dict[str, Any]:
        decision = _require_structural_scope_decision(scope_decision)
        if decision.decision_state == "denied":
            return _structural_denial()
        if not self.items:
            raise ContractValidationError(
                "public source inventory serialization requires a scoped inventory item"
            )
        for item in self.items:
            decision.assert_matches_permission_scope(item.permission_scope)
        return _structural_public_summary(
            decision,
            "source_inventory",
            {"structure_kind": "inventory"},
            self.to_persistence_dict(),
        )

    def to_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
    ) -> dict[str, Any]:
        return self.to_public_dict(scope_decision=scope_decision)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceInventory":
        return cls.from_persistence_dict(value)

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "SourceInventory":
        item = _mapping(value, "source_inventory")
        return cls(
            source_inventory_id=_required_str(item, "source_inventory_id"),
            source_asset_id=_required_str(item, "source_asset_id"),
            source_fingerprint=_required_str(item, "source_fingerprint"),
            parser_fingerprint=_required_str(item, "parser_fingerprint"),
            items=tuple(
                SourceInventoryItem.from_persistence_dict(entry)
                for entry in _required_list(item, "items")
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
            item.to_persistence_dict() if isinstance(item, StructuralColumn) else item
            for item in values.get("columns", [])
        ]
        values["rows"] = [
            item.to_persistence_dict() if isinstance(item, StructuralRow) else item
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
        return cls.from_persistence_dict(values)

    def to_persistence_dict(self) -> dict[str, Any]:
        payload = {
            "structural_observation_id": self.structural_observation_id,
            "source_inventory_item_id": self.source_inventory_item_id,
            "source_asset_id": self.source_asset_id,
            "source_observation_id": self.source_observation_id,
            "structure_kind": self.structure_kind,
            "columns": [column.to_persistence_dict() for column in self.columns],
            "rows": [row.to_persistence_dict() for row in self.rows],
            "header_relationships": [
                _persistence_plain(dict(item)) for item in self.header_relationships
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
        return payload

    def to_public_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
        source_inventory_item: SourceInventoryItem | None = None,
    ) -> dict[str, Any]:
        decision = _require_structural_scope_decision(scope_decision)
        if decision.decision_state == "denied":
            return _structural_denial()
        if not isinstance(source_inventory_item, SourceInventoryItem):
            raise ContractValidationError(
                "public structural observation serialization requires its inventory item"
            )
        if (
            source_inventory_item.source_inventory_item_id != self.source_inventory_item_id
            or source_inventory_item.source_asset_id != self.source_asset_id
            or source_inventory_item.source_fingerprint != self.source_fingerprint
            or source_inventory_item.parser_fingerprint != self.parser_fingerprint
        ):
            raise ContractValidationError(
                "structural observation public scope item relationship is inconsistent"
            )
        decision.assert_matches_permission_scope(source_inventory_item.permission_scope)
        return _structural_public_summary(
            decision,
            "structural_observation",
            {"structure_kind": self.structure_kind},
            self.to_persistence_dict(),
        )

    def to_dict(
        self,
        *,
        scope_decision: "StructuralPublicScopeDecision | None" = None,
        source_inventory_item: SourceInventoryItem | None = None,
    ) -> dict[str, Any]:
        return self.to_public_dict(
            scope_decision=scope_decision,
            source_inventory_item=source_inventory_item,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StructuralObservation":
        return cls.from_persistence_dict(value)

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "StructuralObservation":
        item = _mapping(value, "structural_observation")
        return cls(
            structural_observation_id=_required_str(item, "structural_observation_id"),
            source_inventory_item_id=_required_str(item, "source_inventory_item_id"),
            source_asset_id=_required_str(item, "source_asset_id"),
            source_observation_id=_required_str(item, "source_observation_id"),
            structure_kind=_required_str(item, "structure_kind"),
            columns=tuple(
                StructuralColumn.from_persistence_dict(entry)
                for entry in _required_list(item, "columns")
            ),
            rows=tuple(
                StructuralRow.from_persistence_dict(entry) for entry in _required_list(item, "rows")
            ),
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
class StructuralPublicScopeDecision:
    """Typed authorization result for structural public projections.

    The decision is intentionally not a boolean.  Its opaque scope
    fingerprint binds the complete private permission scope to the exact
    actor/permission/grant revision tuple that produced the decision.  A
    caller can therefore not turn a record into public data by passing an
    untyped ``visible=True`` flag.
    """

    decision_state: str
    authorization_binding: CoverageAuthorizationBinding
    permission_scope_fingerprint: str

    def __post_init__(self) -> None:
        _choice(
            self.decision_state,
            ("authorized", "denied"),
            "structural_public_scope_decision.decision_state",
        )
        if not isinstance(self.authorization_binding, CoverageAuthorizationBinding):
            raise ContractValidationError(
                "structural public scope decision authorization must be typed"
            )
        _fingerprint(
            self.permission_scope_fingerprint,
            "structural_public_scope_decision.permission_scope_fingerprint",
        )

    @classmethod
    def authorize(
        cls,
        *,
        permission_scope: Mapping[str, Any],
        authorization_binding: CoverageAuthorizationBinding,
    ) -> "StructuralPublicScopeDecision":
        if not isinstance(authorization_binding, CoverageAuthorizationBinding):
            raise ContractValidationError(
                "structural public scope decision authorization must be typed"
            )
        _safe_mapping(permission_scope, "structural_public_scope_decision.permission_scope")
        return cls(
            decision_state="authorized",
            authorization_binding=authorization_binding,
            permission_scope_fingerprint=sha256_json(
                {
                    "permission_scope": _persistence_plain(permission_scope),
                    "authorization_binding": authorization_binding.to_dict(),
                }
            ),
        )

    @classmethod
    def deny(
        cls,
        *,
        authorization_binding: CoverageAuthorizationBinding,
    ) -> "StructuralPublicScopeDecision":
        if not isinstance(authorization_binding, CoverageAuthorizationBinding):
            raise ContractValidationError(
                "structural public scope decision authorization must be typed"
            )
        return cls(
            decision_state="denied",
            authorization_binding=authorization_binding,
            permission_scope_fingerprint=sha256_json(
                {
                    "decision_state": "denied",
                    "authorization_binding": authorization_binding.to_dict(),
                }
            ),
        )

    def assert_matches_permission_scope(self, permission_scope: Mapping[str, Any]) -> None:
        if self.decision_state != "authorized":
            raise ContractValidationError("structural public scope decision is denied")
        _safe_mapping(permission_scope, "structural_public_scope_decision.permission_scope")
        expected = sha256_json(
            {
                "permission_scope": _persistence_plain(permission_scope),
                "authorization_binding": self.authorization_binding.to_dict(),
            }
        )
        if expected != self.permission_scope_fingerprint:
            raise ContractValidationError(
                "structural public scope decision actor or permission revision does not match"
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
class CoverageObservationPartition:
    """The typed observation universe for one authorized-relevant item."""

    inventory_item_id: str
    structural_observation_ids: tuple[str, ...] = ()
    ordinary_observation_ids: tuple[str, ...] = ()
    non_search_observation_ids: tuple[str, ...] = ()
    non_search_reason_code: str | None = None

    def __post_init__(self) -> None:
        _id(self.inventory_item_id, "coverage_observation_partition.inventory_item_id")
        for field_name in (
            "structural_observation_ids",
            "ordinary_observation_ids",
            "non_search_observation_ids",
        ):
            values = getattr(self, field_name)
            _tuple_of_strings(values, field_name, ids=True)
            if len(values) != len(set(values)):
                raise ContractValidationError(f"{field_name} must not contain duplicates")
        structural = set(self.structural_observation_ids)
        ordinary = set(self.ordinary_observation_ids)
        non_search = set(self.non_search_observation_ids)
        if structural & ordinary or structural & non_search or ordinary & non_search:
            raise ContractValidationError(
                "coverage observation partition categories must be disjoint"
            )
        if non_search:
            if self.non_search_reason_code is None:
                raise ContractValidationError(
                    "non-search observations require a closed disposition reason"
                )
            _choice(
                self.non_search_reason_code,
                COVERAGE_NON_SEARCH_REASON_VALUES,
                "coverage_observation_partition.non_search_reason_code",
            )
        elif self.non_search_reason_code is not None:
            raise ContractValidationError(
                "non-search disposition is only valid with non-search observations"
            )
        object.__setattr__(
            self,
            "structural_observation_ids",
            tuple(sorted(self.structural_observation_ids)),
        )
        object.__setattr__(
            self,
            "ordinary_observation_ids",
            tuple(sorted(self.ordinary_observation_ids)),
        )
        object.__setattr__(
            self,
            "non_search_observation_ids",
            tuple(sorted(self.non_search_observation_ids)),
        )

    @property
    def all_observation_ids(self) -> frozenset[str]:
        return frozenset(
            self.structural_observation_ids
            + self.ordinary_observation_ids
            + self.non_search_observation_ids
        )

    def to_persistence_dict(self) -> dict[str, Any]:
        return _without_none(_persistence_dataclass_payload(self))

    def to_dict(self) -> dict[str, Any]:
        return self.to_persistence_dict()

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "CoverageObservationPartition":
        item = _mapping(value, "coverage_observation_partition")
        _require_exact_keys(
            item,
            {
                "inventory_item_id",
                "structural_observation_ids",
                "ordinary_observation_ids",
                "non_search_observation_ids",
                "non_search_reason_code",
            },
            "coverage_observation_partition",
            required={
                "inventory_item_id",
                "structural_observation_ids",
                "ordinary_observation_ids",
                "non_search_observation_ids",
            },
        )
        return cls(
            inventory_item_id=_required_str(item, "inventory_item_id"),
            structural_observation_ids=_tuple_strings(
                item,
                "structural_observation_ids",
                ids=True,
            ),
            ordinary_observation_ids=_tuple_strings(
                item,
                "ordinary_observation_ids",
                ids=True,
            ),
            non_search_observation_ids=_tuple_strings(
                item,
                "non_search_observation_ids",
                ids=True,
            ),
            non_search_reason_code=_optional_str(item, "non_search_reason_code"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageObservationPartition":
        return cls.from_persistence_dict(value)


@dataclass(frozen=True)
class CoverageScopePolicyBinding:
    """Opaque, versioned proof identity supplied by the scope authority."""

    scope_policy_id: str
    scope_policy_version: str
    scope_policy_fingerprint: str

    def __post_init__(self) -> None:
        _id(self.scope_policy_id, "coverage_scope_policy.scope_policy_id")
        _text(self.scope_policy_version, "coverage_scope_policy.scope_policy_version")
        _fingerprint(
            self.scope_policy_fingerprint,
            "coverage_scope_policy.scope_policy_fingerprint",
        )

    @classmethod
    def create(
        cls,
        *,
        scope_policy_id: str,
        scope_policy_version: str,
        scope_policy_fingerprint: str,
    ) -> "CoverageScopePolicyBinding":
        return cls(
            scope_policy_id=scope_policy_id,
            scope_policy_version=scope_policy_version,
            scope_policy_fingerprint=scope_policy_fingerprint,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = _dataclass_payload(self)
        _assert_public_contract(payload, "coverage_scope_policy")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageScopePolicyBinding":
        item = _mapping(value, "coverage_scope_policy")
        _require_exact_keys(
            item,
            {"scope_policy_id", "scope_policy_version", "scope_policy_fingerprint"},
            "coverage_scope_policy",
        )
        return cls(
            scope_policy_id=_required_str(item, "scope_policy_id"),
            scope_policy_version=_required_str(item, "scope_policy_version"),
            scope_policy_fingerprint=_required_str(item, "scope_policy_fingerprint"),
        )


@dataclass(frozen=True)
class CoverageItemAuthorizationDecision:
    """One typed authorization/eligibility decision for one inventory item."""

    source_inventory_id: str
    inventory_item_id: str
    authorization_binding: CoverageAuthorizationBinding
    permission_scope_fingerprint: str
    decision_state: str
    decision_id: str = ""

    def __post_init__(self) -> None:
        _id(self.source_inventory_id, "coverage_item_authorization.source_inventory_id")
        _id(self.inventory_item_id, "coverage_item_authorization.inventory_item_id")
        if not isinstance(self.authorization_binding, CoverageAuthorizationBinding):
            raise ContractValidationError("coverage item authorization binding is invalid")
        _fingerprint(
            self.permission_scope_fingerprint,
            "coverage_item_authorization.permission_scope_fingerprint",
        )
        _choice(
            self.decision_state,
            COVERAGE_ITEM_AUTHORIZATION_STATE_VALUES,
            "coverage_item_authorization.decision_state",
        )
        expected_id = stable_resource_contract_id(
            "coverage-item-authorization",
            "CoverageItemAuthorizationDecision",
            self._identity_payload(),
        )
        if self.decision_id:
            _id(self.decision_id, "coverage_item_authorization.decision_id")
            if self.decision_id != expected_id:
                raise ContractValidationError(
                    "coverage item authorization decision id does not match identity"
                )
        else:
            object.__setattr__(self, "decision_id", expected_id)

    @classmethod
    def create(
        cls,
        *,
        source_inventory_item: SourceInventoryItem,
        authorization_binding: CoverageAuthorizationBinding,
        decision_state: str,
    ) -> "CoverageItemAuthorizationDecision":
        if not isinstance(source_inventory_item, SourceInventoryItem):
            raise ContractValidationError("item authorization requires SourceInventoryItem")
        return cls(
            source_inventory_id=source_inventory_item.source_inventory_id or "inventory_unbound",
            inventory_item_id=source_inventory_item.source_inventory_item_id,
            authorization_binding=authorization_binding,
            permission_scope_fingerprint=sha256_json(
                _persistence_plain(source_inventory_item.permission_scope)
            ),
            decision_state=decision_state,
        )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "source_inventory_id": self.source_inventory_id,
            "inventory_item_id": self.inventory_item_id,
            "authorization_binding": self.authorization_binding.to_dict(),
            "permission_scope_fingerprint": self.permission_scope_fingerprint,
            "decision_state": self.decision_state,
        }

    def to_persistence_dict(self) -> dict[str, Any]:
        return {**self._identity_payload(), "decision_id": self.decision_id}

    def to_dict(self) -> dict[str, Any]:
        return self.to_persistence_dict()

    @classmethod
    def from_persistence_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "CoverageItemAuthorizationDecision":
        item = _mapping(value, "coverage_item_authorization")
        _require_exact_keys(
            item,
            {
                "source_inventory_id",
                "inventory_item_id",
                "authorization_binding",
                "permission_scope_fingerprint",
                "decision_state",
                "decision_id",
            },
            "coverage_item_authorization",
        )
        return cls(
            source_inventory_id=_required_str(item, "source_inventory_id"),
            inventory_item_id=_required_str(item, "inventory_item_id"),
            authorization_binding=CoverageAuthorizationBinding.from_dict(
                _required_mapping(item, "authorization_binding")
            ),
            permission_scope_fingerprint=_required_str(item, "permission_scope_fingerprint"),
            decision_state=_required_str(item, "decision_state"),
            decision_id=_required_str(item, "decision_id"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageItemAuthorizationDecision":
        return cls.from_persistence_dict(value)

    def validate_for_item(
        self,
        source_inventory: SourceInventory,
        item: SourceInventoryItem,
        expected_authorization_binding: CoverageAuthorizationBinding,
    ) -> bool:
        if not isinstance(source_inventory, SourceInventory) or not isinstance(
            item, SourceInventoryItem
        ):
            raise ContractValidationError("item authorization validation requires typed inputs")
        if not isinstance(expected_authorization_binding, CoverageAuthorizationBinding):
            raise ContractValidationError("item authorization expected binding must be typed")
        if (
            item.source_inventory_id != source_inventory.source_inventory_id
            or self.source_inventory_id != source_inventory.source_inventory_id
            or self.inventory_item_id != item.source_inventory_item_id
            or self.authorization_binding != expected_authorization_binding
            or self.permission_scope_fingerprint
            != sha256_json(_persistence_plain(item.permission_scope))
        ):
            return False
        return True


@dataclass(frozen=True)
class CoverageItemRelevanceDecision:
    """One typed claim-relevance decision bound to an external scope policy."""

    source_inventory_id: str
    inventory_item_id: str
    claim_requirement_id: str
    claim_requirement_fingerprint: str
    scope_policy: CoverageScopePolicyBinding
    decision_state: str
    decision_id: str = ""

    def __post_init__(self) -> None:
        _id(self.source_inventory_id, "coverage_item_relevance.source_inventory_id")
        _id(self.inventory_item_id, "coverage_item_relevance.inventory_item_id")
        _id(self.claim_requirement_id, "coverage_item_relevance.claim_requirement_id")
        _fingerprint(
            self.claim_requirement_fingerprint,
            "coverage_item_relevance.claim_requirement_fingerprint",
        )
        if not isinstance(self.scope_policy, CoverageScopePolicyBinding):
            raise ContractValidationError("coverage item relevance policy is invalid")
        _choice(
            self.decision_state,
            COVERAGE_ITEM_RELEVANCE_STATE_VALUES,
            "coverage_item_relevance.decision_state",
        )
        expected_id = stable_resource_contract_id(
            "coverage-item-relevance",
            "CoverageItemRelevanceDecision",
            self._identity_payload(),
        )
        if self.decision_id:
            _id(self.decision_id, "coverage_item_relevance.decision_id")
            if self.decision_id != expected_id:
                raise ContractValidationError(
                    "coverage item relevance decision id does not match identity"
                )
        else:
            object.__setattr__(self, "decision_id", expected_id)

    @classmethod
    def create(
        cls,
        *,
        source_inventory_item: SourceInventoryItem,
        claim_requirement: ClaimRequirement,
        scope_policy: CoverageScopePolicyBinding,
        decision_state: str,
    ) -> "CoverageItemRelevanceDecision":
        if not isinstance(source_inventory_item, SourceInventoryItem):
            raise ContractValidationError("item relevance requires SourceInventoryItem")
        if not isinstance(claim_requirement, ClaimRequirement):
            raise ContractValidationError("item relevance requires ClaimRequirement")
        return cls(
            source_inventory_id=source_inventory_item.source_inventory_id or "inventory_unbound",
            inventory_item_id=source_inventory_item.source_inventory_item_id,
            claim_requirement_id=claim_requirement.claim_requirement_id,
            claim_requirement_fingerprint=sha256_json(claim_requirement.to_dict()),
            scope_policy=scope_policy,
            decision_state=decision_state,
        )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "source_inventory_id": self.source_inventory_id,
            "inventory_item_id": self.inventory_item_id,
            "claim_requirement_id": self.claim_requirement_id,
            "claim_requirement_fingerprint": self.claim_requirement_fingerprint,
            "scope_policy": self.scope_policy.to_dict(),
            "decision_state": self.decision_state,
        }

    def to_persistence_dict(self) -> dict[str, Any]:
        return {**self._identity_payload(), "decision_id": self.decision_id}

    def to_dict(self) -> dict[str, Any]:
        return self.to_persistence_dict()

    @classmethod
    def from_persistence_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "CoverageItemRelevanceDecision":
        item = _mapping(value, "coverage_item_relevance")
        _require_exact_keys(
            item,
            {
                "source_inventory_id",
                "inventory_item_id",
                "claim_requirement_id",
                "claim_requirement_fingerprint",
                "scope_policy",
                "decision_state",
                "decision_id",
            },
            "coverage_item_relevance",
        )
        return cls(
            source_inventory_id=_required_str(item, "source_inventory_id"),
            inventory_item_id=_required_str(item, "inventory_item_id"),
            claim_requirement_id=_required_str(item, "claim_requirement_id"),
            claim_requirement_fingerprint=_required_str(
                item,
                "claim_requirement_fingerprint",
            ),
            scope_policy=CoverageScopePolicyBinding.from_dict(
                _required_mapping(item, "scope_policy")
            ),
            decision_state=_required_str(item, "decision_state"),
            decision_id=_required_str(item, "decision_id"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageItemRelevanceDecision":
        return cls.from_persistence_dict(value)

    def validate_for_claim(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_scope_policy: CoverageScopePolicyBinding,
    ) -> bool:
        if not isinstance(source_inventory, SourceInventory) or not isinstance(
            claim_requirement, ClaimRequirement
        ):
            raise ContractValidationError("item relevance validation requires typed inputs")
        if not isinstance(expected_scope_policy, CoverageScopePolicyBinding):
            raise ContractValidationError("item relevance expected policy must be typed")
        item = next(
            (
                candidate
                for candidate in source_inventory.items
                if candidate.source_inventory_item_id == self.inventory_item_id
            ),
            None,
        )
        return bool(
            item is not None
            and self.source_inventory_id == source_inventory.source_inventory_id
            and self.claim_requirement_id == claim_requirement.claim_requirement_id
            and self.claim_requirement_fingerprint == sha256_json(claim_requirement.to_dict())
            and self.scope_policy == expected_scope_policy
        )


class _CoverageScopeAuthorityCapability:
    __slots__ = ("authority_id", "verifier_fingerprint", "proof")

    def __init__(
        self,
        authority_id: str,
        verifier_fingerprint: str,
        proof: str,
        *,
        _constructor_token: object,
    ) -> None:
        if _constructor_token is not _COVERAGE_AUTHORITY_CAPABILITY_TOKEN:
            raise ContractValidationError(
                "scope authority capability is not publicly constructible"
            )
        self.authority_id = authority_id
        self.verifier_fingerprint = verifier_fingerprint
        self.proof = proof

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("scope authority capability cannot be serialized")

    def __copy__(self) -> object:
        raise TypeError("scope authority capability cannot be copied")

    def __deepcopy__(self, memo: dict[int, object]) -> object:
        raise TypeError("scope authority capability cannot be deep-copied")


class CoverageScopeAuthorityVerifier:
    """External authority root for scope validation.

    The root is intentionally process/external state.  Only its derived
    fingerprint is persisted with an authority; the root and the capability
    issued from it are never serialized.  Revalidation after restart therefore
    requires the same externally retained root, while a newly generated
    verifier cannot validate an older persisted authority.
    """

    __slots__ = ("_root", "_verifier_fingerprint")

    def __init__(self, root: bytes | str) -> None:
        if isinstance(root, str):
            root_bytes = root.encode("utf-8")
        elif isinstance(root, bytes):
            root_bytes = root
        else:
            raise ContractValidationError("scope authority verifier root must be bytes or string")
        if len(root_bytes) < 16:
            raise ContractValidationError(
                "scope authority verifier root must contain at least 16 bytes"
            )
        self._root = root_bytes
        self._verifier_fingerprint = (
            "sha256:"
            + hashlib.sha256(b"formowl:coverage-scope-authority-verifier:" + root_bytes).hexdigest()
        )

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("scope authority verifier cannot be serialized")

    def __copy__(self) -> object:
        raise TypeError("scope authority verifier cannot be copied")

    def __deepcopy__(self, memo: dict[int, object]) -> object:
        raise TypeError("scope authority verifier cannot be deep-copied")

    @classmethod
    def generate(cls) -> "CoverageScopeAuthorityVerifier":
        return cls(secrets.token_bytes(32))

    @classmethod
    def from_external_root(cls, root: bytes | str) -> "CoverageScopeAuthorityVerifier":
        return cls(root)

    @property
    def verifier_fingerprint(self) -> str:
        return self._verifier_fingerprint

    def _capability_for(self, authority_id: str) -> _CoverageScopeAuthorityCapability:
        _id(authority_id, "coverage_scope_authority.authority_id")
        proof = hmac.new(
            self._root,
            (self._verifier_fingerprint + ":" + authority_id).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return _CoverageScopeAuthorityCapability(
            authority_id=authority_id,
            verifier_fingerprint=self._verifier_fingerprint,
            proof=proof,
            _constructor_token=_COVERAGE_AUTHORITY_CAPABILITY_TOKEN,
        )

    def _trust(self, authority: "CoverageScopeAuthority") -> "CoverageScopeAuthority":
        if not isinstance(authority, CoverageScopeAuthority):
            raise ContractValidationError("scope authority verifier requires a typed authority")
        if authority.authority_verifier_fingerprint != self._verifier_fingerprint:
            raise ContractValidationError(
                "scope authority was issued by a different external verifier"
            )
        trusted = replace(authority)
        object.__setattr__(
            trusted,
            "_authority_capability",
            self._capability_for(trusted.authority_id),
        )
        object.__setattr__(trusted, "_authority_provenance", "trusted")
        return trusted

    def revalidate(self, authority: "CoverageScopeAuthority") -> "CoverageScopeAuthority":
        """Reattach trusted process-local capability to persisted authority data."""

        return self._trust(authority)


@dataclass(frozen=True)
class CoverageScopeAuthority:
    """The independently supplied typed authority from which categories derive."""

    source_inventory_id: str
    claim_requirement_id: str
    authorization_binding: CoverageAuthorizationBinding
    version_binding: CoverageVersionBinding
    scope_policy: CoverageScopePolicyBinding
    authorization_decisions: tuple[CoverageItemAuthorizationDecision, ...]
    relevance_decisions: tuple[CoverageItemRelevanceDecision, ...]
    authority_verifier_fingerprint: str = ""
    authority_id: str = ""
    _authority_provenance: str = field(
        default="untrusted_constructor",
        init=False,
        repr=False,
        compare=False,
    )
    _authority_capability: _CoverageScopeAuthorityCapability | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _id(self.source_inventory_id, "coverage_scope_authority.source_inventory_id")
        _id(self.claim_requirement_id, "coverage_scope_authority.claim_requirement_id")
        if self.authority_verifier_fingerprint:
            _fingerprint(
                self.authority_verifier_fingerprint,
                "coverage_scope_authority.authority_verifier_fingerprint",
            )
        if not isinstance(self.authorization_binding, CoverageAuthorizationBinding):
            raise ContractValidationError("coverage scope authority authorization is invalid")
        if not isinstance(self.version_binding, CoverageVersionBinding):
            raise ContractValidationError("coverage scope authority version is invalid")
        if not isinstance(self.scope_policy, CoverageScopePolicyBinding):
            raise ContractValidationError("coverage scope authority policy is invalid")
        _tuple_of(
            self.authorization_decisions,
            CoverageItemAuthorizationDecision,
            "coverage_scope_authority.authorization_decisions",
        )
        _tuple_of(
            self.relevance_decisions,
            CoverageItemRelevanceDecision,
            "coverage_scope_authority.relevance_decisions",
        )
        authorization_ids = [item.inventory_item_id for item in self.authorization_decisions]
        relevance_ids = [item.inventory_item_id for item in self.relevance_decisions]
        if len(authorization_ids) != len(set(authorization_ids)):
            raise ContractValidationError("scope authorization decisions must be unique")
        if len(relevance_ids) != len(set(relevance_ids)):
            raise ContractValidationError("scope relevance decisions must be unique")
        if set(relevance_ids) - set(authorization_ids):
            raise ContractValidationError(
                "scope relevance decisions require authorization decisions"
            )
        if any(
            decision.decision_state != "authorized"
            for decision in self.authorization_decisions
            if decision.inventory_item_id in set(relevance_ids)
        ):
            raise ContractValidationError("ineligible items cannot have relevance decisions")
        expected_id = stable_resource_contract_id(
            "coverage-scope-authority",
            "CoverageScopeAuthority",
            self._identity_payload(),
        )
        if self.authority_id:
            _id(self.authority_id, "coverage_scope_authority.authority_id")
            if self.authority_id != expected_id:
                raise ContractValidationError("scope authority id does not match identity")
        else:
            object.__setattr__(self, "authority_id", expected_id)

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("scope authority cannot be serialized; use to_persistence_dict instead")

    def __copy__(self) -> object:
        raise TypeError("scope authority cannot be copied")

    def __deepcopy__(self, memo: dict[int, object]) -> object:
        raise TypeError("scope authority cannot be deep-copied")

    @classmethod
    def create(
        cls,
        *,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        authorization_binding: CoverageAuthorizationBinding,
        version_manifest: VersionManifest,
        scope_policy: CoverageScopePolicyBinding,
        authorization_decisions: Sequence[CoverageItemAuthorizationDecision],
        relevance_decisions: Sequence[CoverageItemRelevanceDecision],
        authority_verifier: CoverageScopeAuthorityVerifier | None = None,
    ) -> "CoverageScopeAuthority":
        if not all(
            isinstance(value, expected_type)
            for value, expected_type in (
                (source_inventory, SourceInventory),
                (claim_requirement, ClaimRequirement),
                (authorization_binding, CoverageAuthorizationBinding),
                (version_manifest, VersionManifest),
                (scope_policy, CoverageScopePolicyBinding),
            )
        ):
            raise ContractValidationError("scope authority requires typed inputs")
        if not isinstance(authority_verifier, CoverageScopeAuthorityVerifier):
            raise ContractValidationError(
                "scope authority creation requires an independent external verifier"
            )
        authority = cls(
            source_inventory_id=source_inventory.source_inventory_id,
            claim_requirement_id=claim_requirement.claim_requirement_id,
            authorization_binding=authorization_binding,
            version_binding=CoverageVersionBinding.from_manifest(version_manifest),
            scope_policy=scope_policy,
            authorization_decisions=tuple(authorization_decisions),
            relevance_decisions=tuple(relevance_decisions),
            authority_verifier_fingerprint=authority_verifier.verifier_fingerprint,
        )
        if not authority.validate_for_claim(
            source_inventory,
            claim_requirement,
            version_manifest,
            authorization_binding,
            scope_policy,
        ):
            raise ContractValidationError("scope authority decisions do not match typed inputs")
        return authority_verifier._trust(authority)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "source_inventory_id": self.source_inventory_id,
            "claim_requirement_id": self.claim_requirement_id,
            "authorization_binding": self.authorization_binding.to_dict(),
            "version_binding": self.version_binding.to_dict(),
            "scope_policy": self.scope_policy.to_dict(),
            "authority_verifier_fingerprint": self.authority_verifier_fingerprint,
            "authorization_decisions": [
                decision.to_persistence_dict() for decision in self.authorization_decisions
            ],
            "relevance_decisions": [
                decision.to_persistence_dict() for decision in self.relevance_decisions
            ],
        }

    @property
    def authorized_relevant_item_ids(self) -> tuple[str, ...]:
        relevant = {
            decision.inventory_item_id
            for decision in self.relevance_decisions
            if decision.decision_state == "relevant"
        }
        return tuple(sorted(relevant))

    @property
    def authorized_irrelevant_item_ids(self) -> tuple[str, ...]:
        irrelevant = {
            decision.inventory_item_id
            for decision in self.relevance_decisions
            if decision.decision_state == "irrelevant"
        }
        return tuple(sorted(irrelevant))

    @property
    def ineligible_item_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                decision.inventory_item_id
                for decision in self.authorization_decisions
                if decision.decision_state == "ineligible"
            )
        )

    def to_persistence_dict(self) -> dict[str, Any]:
        return {
            **self._identity_payload(),
            "authority_id": self.authority_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_persistence_dict()

    @property
    def _is_trusted_for_authoritative_use(self) -> bool:
        capability = self._authority_capability
        return bool(
            self._authority_provenance == "trusted"
            and isinstance(capability, _CoverageScopeAuthorityCapability)
            and capability.authority_id == self.authority_id
            and capability.verifier_fingerprint == self.authority_verifier_fingerprint
        )

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "CoverageScopeAuthority":
        item = _mapping(value, "coverage_scope_authority")
        _require_exact_keys(
            item,
            {
                "source_inventory_id",
                "claim_requirement_id",
                "authorization_binding",
                "version_binding",
                "scope_policy",
                "authority_verifier_fingerprint",
                "authorization_decisions",
                "relevance_decisions",
                "authority_id",
            },
            "coverage_scope_authority",
        )
        authority = cls(
            source_inventory_id=_required_str(item, "source_inventory_id"),
            claim_requirement_id=_required_str(item, "claim_requirement_id"),
            authorization_binding=CoverageAuthorizationBinding.from_dict(
                _required_mapping(item, "authorization_binding")
            ),
            version_binding=CoverageVersionBinding.from_dict(
                _required_mapping(item, "version_binding")
            ),
            scope_policy=CoverageScopePolicyBinding.from_dict(
                _required_mapping(item, "scope_policy")
            ),
            authority_verifier_fingerprint=_required_str(
                item,
                "authority_verifier_fingerprint",
            ),
            authorization_decisions=tuple(
                CoverageItemAuthorizationDecision.from_persistence_dict(entry)
                for entry in _required_list(item, "authorization_decisions")
            ),
            relevance_decisions=tuple(
                CoverageItemRelevanceDecision.from_persistence_dict(entry)
                for entry in _required_list(item, "relevance_decisions")
            ),
            authority_id=_required_str(item, "authority_id"),
        )
        object.__setattr__(authority, "_authority_provenance", "untrusted_persistence")
        return authority

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageScopeAuthority":
        return cls.from_persistence_dict(value)

    def validate_for_claim(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding,
        expected_scope_policy: CoverageScopePolicyBinding,
    ) -> bool:
        if not all(
            isinstance(value, expected_type)
            for value, expected_type in (
                (source_inventory, SourceInventory),
                (claim_requirement, ClaimRequirement),
                (expected_manifest, VersionManifest),
                (expected_authorization_binding, CoverageAuthorizationBinding),
                (expected_scope_policy, CoverageScopePolicyBinding),
            )
        ):
            raise ContractValidationError("scope authority validation requires typed inputs")
        if (
            self.source_inventory_id != source_inventory.source_inventory_id
            or self.claim_requirement_id != claim_requirement.claim_requirement_id
            or self.authorization_binding != expected_authorization_binding
            or self.scope_policy != expected_scope_policy
            or expected_manifest.index_freshness != "fresh"
            or not self.version_binding.matches_manifest(expected_manifest)
            or source_inventory.source_fingerprint != expected_manifest.source_fingerprint
            or source_inventory.parser_fingerprint != expected_manifest.parser_fingerprint
        ):
            return False
        inventory_items = {item.source_inventory_item_id: item for item in source_inventory.items}
        if set(decision.inventory_item_id for decision in self.authorization_decisions) != set(
            inventory_items
        ):
            return False
        authorization_by_item = {
            decision.inventory_item_id: decision for decision in self.authorization_decisions
        }
        for item_id, item in inventory_items.items():
            if not authorization_by_item[item_id].validate_for_item(
                source_inventory,
                item,
                expected_authorization_binding,
            ):
                return False
        relevant_decision_ids = {
            decision.inventory_item_id for decision in self.relevance_decisions
        }
        authorized_ids = {
            item_id
            for item_id, decision in authorization_by_item.items()
            if decision.decision_state == "authorized"
        }
        if relevant_decision_ids - authorized_ids:
            return False
        if relevant_decision_ids != authorized_ids:
            return False
        for decision in self.relevance_decisions:
            if not decision.validate_for_claim(
                source_inventory,
                claim_requirement,
                expected_scope_policy,
            ):
                return False
        return True


@dataclass(frozen=True)
class CoverageScopePartition:
    """Observation accounting derived from independently supplied decisions."""

    scope_authority: CoverageScopeAuthority
    observation_partitions: tuple[CoverageObservationPartition, ...]
    scope_partition_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.scope_authority, CoverageScopeAuthority):
            raise ContractValidationError("coverage scope partition authority is invalid")
        _tuple_of(
            self.observation_partitions,
            CoverageObservationPartition,
            "coverage_scope_partition.observation_partitions",
        )
        observation_item_ids = [
            partition.inventory_item_id for partition in self.observation_partitions
        ]
        if len(observation_item_ids) != len(set(observation_item_ids)):
            raise ContractValidationError("coverage observation partitions must be unique")
        if set(observation_item_ids) - set(self.authorized_relevant_item_ids):
            raise ContractValidationError(
                "observation partitions must belong to authorized-relevant items"
            )
        object.__setattr__(
            self,
            "observation_partitions",
            tuple(sorted(self.observation_partitions, key=lambda item: item.inventory_item_id)),
        )
        all_observations: list[str] = []
        for partition in self.observation_partitions:
            all_observations.extend(partition.all_observation_ids)
        if len(all_observations) != len(set(all_observations)):
            raise ContractValidationError("coverage scope observation IDs must be globally unique")
        expected_id = stable_resource_contract_id(
            "coverage-scope",
            "CoverageScopePartition",
            self._identity_payload(),
        )
        if self.scope_partition_id:
            _id(self.scope_partition_id, "scope_partition_id")
            if self.scope_partition_id != expected_id:
                raise ContractValidationError(
                    "coverage scope partition id does not match its canonical identity"
                )
        else:
            object.__setattr__(self, "scope_partition_id", expected_id)

    @property
    def source_inventory_id(self) -> str:
        return self.scope_authority.source_inventory_id

    @property
    def claim_requirement_id(self) -> str:
        return self.scope_authority.claim_requirement_id

    @property
    def authorization_binding(self) -> CoverageAuthorizationBinding:
        return self.scope_authority.authorization_binding

    @property
    def version_binding(self) -> CoverageVersionBinding:
        return self.scope_authority.version_binding

    @property
    def scope_policy(self) -> CoverageScopePolicyBinding:
        return self.scope_authority.scope_policy

    @property
    def authorized_relevant_item_ids(self) -> tuple[str, ...]:
        return self.scope_authority.authorized_relevant_item_ids

    @property
    def authorized_irrelevant_item_ids(self) -> tuple[str, ...]:
        return self.scope_authority.authorized_irrelevant_item_ids

    @property
    def ineligible_item_ids(self) -> tuple[str, ...]:
        return self.scope_authority.ineligible_item_ids

    @classmethod
    def create(
        cls,
        *,
        scope_authority: CoverageScopeAuthority,
        observation_partitions: Sequence[CoverageObservationPartition],
    ) -> "CoverageScopePartition":
        if not isinstance(scope_authority, CoverageScopeAuthority):
            raise ContractValidationError(
                "scope partition requires an already-produced typed scope authority"
            )
        return cls(
            scope_authority=scope_authority,
            observation_partitions=tuple(observation_partitions),
        )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "scope_authority": self.scope_authority.to_persistence_dict(),
            "observation_partitions": [
                partition.to_persistence_dict() for partition in self.observation_partitions
            ],
        }

    def to_persistence_dict(self) -> dict[str, Any]:
        return {**self._identity_payload(), "scope_partition_id": self.scope_partition_id}

    def to_dict(self) -> dict[str, Any]:
        return self.to_persistence_dict()

    @classmethod
    def from_persistence_dict(cls, value: Mapping[str, Any]) -> "CoverageScopePartition":
        item = _mapping(value, "coverage_scope_partition")
        _require_exact_keys(
            item,
            {"scope_authority", "observation_partitions", "scope_partition_id"},
            "coverage_scope_partition",
        )
        return cls(
            scope_authority=CoverageScopeAuthority.from_persistence_dict(
                _required_mapping(item, "scope_authority")
            ),
            observation_partitions=tuple(
                CoverageObservationPartition.from_persistence_dict(entry)
                for entry in _required_list(item, "observation_partitions")
            ),
            scope_partition_id=_required_str(item, "scope_partition_id"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageScopePartition":
        return cls.from_persistence_dict(value)

    def observation_partition_for(
        self,
        inventory_item_id: str,
    ) -> CoverageObservationPartition | None:
        return next(
            (
                partition
                for partition in self.observation_partitions
                if partition.inventory_item_id == inventory_item_id
            ),
            None,
        )

    def validate_for_claim(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding,
        expected_scope_authority: CoverageScopeAuthority,
    ) -> bool:
        """Validate decisions and observation accounting against typed authority."""

        if not isinstance(expected_scope_authority, CoverageScopeAuthority):
            raise ContractValidationError("scope partition requires typed scope authority")
        if not expected_scope_authority._is_trusted_for_authoritative_use:
            return False
        return self._validate_against_scope_authority(
            source_inventory,
            claim_requirement,
            expected_manifest,
            expected_authorization_binding,
            expected_scope_authority,
        )

    def _validate_against_scope_authority(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding,
        expected_scope_authority: CoverageScopeAuthority,
    ) -> bool:
        """Validate against an authority, including private embedded replay data."""

        if self.scope_authority != expected_scope_authority:
            return False
        if not self.scope_authority.validate_for_claim(
            source_inventory,
            claim_requirement,
            expected_manifest,
            expected_authorization_binding,
            expected_scope_authority.scope_policy,
        ):
            return False
        inventory_items = {item.source_inventory_item_id: item for item in source_inventory.items}
        observation_owner: dict[str, str] = {}
        for item in source_inventory.items:
            if len(item.source_observation_ids) != len(set(item.source_observation_ids)):
                return False
            for observation_id in item.source_observation_ids:
                if observation_id in observation_owner:
                    return False
                observation_owner[observation_id] = item.source_inventory_item_id
        observation_partitions_by_item = {
            partition.inventory_item_id: partition for partition in self.observation_partitions
        }
        if set(observation_partitions_by_item) != set(self.authorized_relevant_item_ids):
            return False
        seen_partition_observations: set[str] = set()
        for item_id in self.authorized_relevant_item_ids:
            item = inventory_items[item_id]
            partition = observation_partitions_by_item[item_id]
            if partition.all_observation_ids != frozenset(item.source_observation_ids):
                return False
            for observation_id in partition.all_observation_ids:
                if observation_owner.get(observation_id) != item_id:
                    return False
                if observation_id in seen_partition_observations:
                    return False
                seen_partition_observations.add(observation_id)
        return True


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
    populated_value_fingerprint: str | None = None
    intentional_exclusion_proof: IntentionalExclusionProof | None = None

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
        if len(self.structural_observation_ids) != len(set(self.structural_observation_ids)):
            raise ContractValidationError(
                "coverage proof structural observation IDs must be unique"
            )
        if len(self.ordinary_observation_ids) != len(set(self.ordinary_observation_ids)):
            raise ContractValidationError("coverage proof ordinary observation IDs must be unique")
        if set(self.structural_observation_ids) & set(self.ordinary_observation_ids):
            raise ContractValidationError(
                "coverage proof structural and ordinary observations must be disjoint"
            )
        _optional_fingerprint(
            self.populated_value_fingerprint,
            "coverage_proof.populated_value_fingerprint",
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
        if self.proof_kind in {"intentionally_excluded", "fallback"} and (
            self.populated_value_fingerprint is not None
        ):
            raise ContractValidationError(
                f"{self.proof_kind} proof must not carry a populated value"
            )
        if self.proof_kind == "intentionally_excluded":
            if self.intentional_exclusion_proof is None:
                raise ContractValidationError(
                    "intentionally_excluded proof requires a typed exclusion proof"
                )
            if (
                self.intentional_exclusion_proof.source_inventory_id != self.source_inventory_id
                or self.intentional_exclusion_proof.source_inventory_item_id
                != self.inventory_item_id
            ):
                raise ContractValidationError(
                    "coverage exclusion proof membership does not match proof record"
                )
        elif self.intentional_exclusion_proof is not None:
            raise ContractValidationError(
                "typed exclusion proof is only valid for intentionally_excluded records"
            )
        if self.populated_value_fingerprint is not None and not (
            self.structural_observation_ids or self.ordinary_observation_ids
        ):
            raise ContractValidationError("populated value proof requires direct observations")
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
        if isinstance(values.get("intentional_exclusion_proof"), IntentionalExclusionProof):
            values["intentional_exclusion_proof"] = values[
                "intentional_exclusion_proof"
            ].to_persistence_dict()
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
        payload = {
            "proof_id": self.proof_id,
            "source_inventory_id": self.source_inventory_id,
            "claim_requirement_id": self.claim_requirement_id,
            "version_manifest_id": self.version_manifest_id,
            "inventory_item_id": self.inventory_item_id,
            "proof_kind": self.proof_kind,
            "structural_observation_ids": list(self.structural_observation_ids),
            "ordinary_observation_ids": list(self.ordinary_observation_ids),
        }
        if self.populated_value_fingerprint is not None:
            payload["populated_value_fingerprint"] = self.populated_value_fingerprint
        if self.intentional_exclusion_proof is not None:
            payload["intentional_exclusion_proof"] = (
                self.intentional_exclusion_proof.to_persistence_dict()
            )
        _assert_public_contract(payload, "coverage_proof")
        return payload

    def to_persistence_dict(self) -> dict[str, Any]:
        return self.to_dict()

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
                "populated_value_fingerprint",
                "intentional_exclusion_proof",
            },
            "coverage_proof",
            required={
                "proof_id",
                "source_inventory_id",
                "claim_requirement_id",
                "version_manifest_id",
                "inventory_item_id",
                "proof_kind",
                "structural_observation_ids",
                "ordinary_observation_ids",
            },
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
            populated_value_fingerprint=_optional_str(item, "populated_value_fingerprint"),
            intentional_exclusion_proof=(
                None
                if item.get("intentional_exclusion_proof") is None
                else IntentionalExclusionProof.from_persistence_dict(
                    _mapping(
                        item["intentional_exclusion_proof"],
                        "coverage_proof.intentional_exclusion_proof",
                    )
                )
            ),
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
    scope_partition: CoverageScopePartition | None = None
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
        scope_partition: CoverageScopePartition | None = None,
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
            scope_partition=scope_partition,
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
        if not (
            self.scope_partition is None or isinstance(self.scope_partition, CoverageScopePartition)
        ):
            raise ContractValidationError("coverage ledger scope partition is invalid")
        if self.scope_partition is not None:
            if set(self.searched_structural_observation_ids) & set(
                self.searched_ordinary_observation_ids
            ):
                raise ContractValidationError(
                    "coverage ledger searched observation categories must be disjoint"
                )
            if (
                self.scope_partition.source_inventory_id != self.source_inventory_id
                or self.scope_partition.claim_requirement_id != self.claim_requirement_id
            ):
                raise ContractValidationError(
                    "coverage ledger scope partition does not bind the ledger"
                )
            if self.authorization_binding != self.scope_partition.authorization_binding:
                raise ContractValidationError(
                    "coverage ledger authorization does not match scope partition"
                )
            if self.version_binding != self.scope_partition.version_binding:
                raise ContractValidationError(
                    "coverage ledger version does not match scope partition"
                )
            if set(self.relevant_inventory_item_ids) - set(
                self.scope_partition.authorized_relevant_item_ids
            ):
                raise ContractValidationError(
                    "coverage ledger relevant items must be authorized-relevant"
                )
            partition_observation_ids = {
                observation_id
                for partition in self.scope_partition.observation_partitions
                for observation_id in partition.all_observation_ids
            }
            if set(self.searched_structural_observation_ids) - partition_observation_ids:
                raise ContractValidationError(
                    "coverage ledger searched structural observations are outside the partition"
                )
            if set(self.searched_ordinary_observation_ids) - partition_observation_ids:
                raise ContractValidationError(
                    "coverage ledger searched ordinary observations are outside the partition"
                )
        if not isinstance(self.fallback_usage, CoverageFallbackUsage):
            raise ContractValidationError("coverage ledger fallback usage is invalid")
        _tuple_of(self.proof_records, CoverageProofRecord, "coverage_ledger.proof_records")
        proof_ids = [record.proof_id for record in self.proof_records]
        if len(proof_ids) != len(set(proof_ids)):
            raise ContractValidationError("coverage ledger proof IDs must be unique")
        proof_semantics = [_coverage_proof_semantic_key(record) for record in self.proof_records]
        if len(proof_semantics) != len(set(proof_semantics)):
            raise ContractValidationError("coverage ledger proof records must be unique")
        if not isinstance(self.display_pagination, DisplayPagination):
            raise ContractValidationError("coverage ledger display_pagination is invalid")
        expected_coverage_ledger_id = stable_resource_contract_id(
            "coverage",
            "CoverageLedger",
            self._identity_payload(),
        )
        if self.coverage_ledger_id:
            _id(self.coverage_ledger_id, "coverage_ledger_id")
            if self.coverage_ledger_id != expected_coverage_ledger_id:
                raise ContractValidationError(
                    "coverage ledger id does not match semantic coverage identity"
                )
        else:
            object.__setattr__(self, "coverage_ledger_id", expected_coverage_ledger_id)
        if self.complete_authorized_scope:
            self._assert_complete_proof_shape()

    def _assert_complete_proof_shape(self) -> None:
        if self.authorization_binding is None:
            raise ContractValidationError("complete coverage requires authorization binding")
        if self.version_binding is None or self.version_binding.freshness_state != "fresh":
            raise ContractValidationError(
                "complete coverage requires a fresh version manifest binding"
            )
        if self.scope_partition is None:
            raise ContractValidationError(
                "complete coverage requires an independently bound scope partition"
            )
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
        ordinary_proof_item_ids = {
            record.inventory_item_id
            for record in self.proof_records
            if record.proof_kind != "intentionally_excluded"
        }
        if ordinary_proof_item_ids != set(self.relevant_inventory_item_ids):
            raise ContractValidationError(
                "complete coverage proof set must cover exactly the relevant inventory"
            )
        if not self.relevant_inventory_item_ids and not any(
            record.proof_kind == "intentionally_excluded" for record in self.proof_records
        ):
            raise ContractValidationError(
                "complete coverage with an empty relevant scope requires exclusion proof"
            )
        if set(self.relevant_inventory_item_ids) != set(
            self.scope_partition.authorized_relevant_item_ids
        ):
            raise ContractValidationError(
                "complete coverage relevant scope must equal the authorized-relevant partition"
            )
        if any(
            partition.non_search_observation_ids
            for partition in self.scope_partition.observation_partitions
        ):
            raise ContractValidationError(
                "complete coverage cannot contain non-search observation dispositions"
            )
        expected_structural = {
            observation_id
            for partition in self.scope_partition.observation_partitions
            for observation_id in partition.structural_observation_ids
        }
        expected_ordinary = {
            observation_id
            for partition in self.scope_partition.observation_partitions
            for observation_id in partition.ordinary_observation_ids
        }
        if set(self.searched_structural_observation_ids) != expected_structural:
            raise ContractValidationError(
                "complete coverage must search every partitioned structural observation"
            )
        if set(self.searched_ordinary_observation_ids) != expected_ordinary:
            raise ContractValidationError(
                "complete coverage must search every partitioned ordinary observation"
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
            if record.proof_kind == "intentionally_excluded":
                if record.structural_observation_ids or record.ordinary_observation_ids:
                    raise ContractValidationError(
                        "complete exclusion proofs must not carry observations"
                    )
                continue
            partition = self.scope_partition.observation_partition_for(record.inventory_item_id)
            if partition is None:
                raise ContractValidationError(
                    "complete coverage proof record lacks an observation partition"
                )
            if set(record.structural_observation_ids) != set(
                partition.structural_observation_ids
            ) or set(record.ordinary_observation_ids) != set(partition.ordinary_observation_ids):
                raise ContractValidationError(
                    "complete coverage proof records must cover their item observation partition"
                )
            if partition.non_search_observation_ids:
                raise ContractValidationError(
                    "complete coverage proof cannot omit partitioned observations"
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
            "scope_partition": (
                self.scope_partition.to_persistence_dict()
                if self.scope_partition is not None
                else None
            ),
            "fallback_usage": self.fallback_usage.to_dict(),
            "proof_records": [record.to_dict() for record in self.proof_records],
            "complete_authorized_scope": self.complete_authorized_scope,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = {
            **self._identity_payload(),
            "display_pagination": self.display_pagination.to_dict(),
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
                "scope_partition",
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
        scope_partition_value = item.get("scope_partition")
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
            scope_partition=(
                None
                if scope_partition_value is None
                else CoverageScopePartition.from_persistence_dict(
                    _mapping(scope_partition_value, "scope_partition")
                )
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

    def binding_valid_for_claim(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding | None = None,
        expected_scope_authority: CoverageScopeAuthority | None = None,
    ) -> bool:
        """Validate typed referential and version bindings without requiring completeness.

        An incomplete ledger is a valid input to an ``INSUFFICIENT_COVERAGE``
        claim.  Definitive claim states use ``usable_for_claim`` below, which
        adds the complete-scope proof requirements.
        """

        if not self._base_binding_valid_for_claim(
            source_inventory,
            claim_requirement,
            expected_manifest,
            expected_authorization_binding,
        ):
            return False
        if self.scope_partition is not None:
            if expected_authorization_binding is None or not isinstance(
                expected_scope_authority, CoverageScopeAuthority
            ):
                return False
            if not expected_scope_authority._is_trusted_for_authoritative_use:
                return False
            if not self.scope_partition.validate_for_claim(
                source_inventory,
                claim_requirement,
                expected_manifest,
                expected_authorization_binding,
                expected_scope_authority,
            ):
                return False
            if set(self.relevant_inventory_item_ids) - set(
                self.scope_partition.authorized_relevant_item_ids
            ):
                return False
        if (
            expected_scope_authority is not None
            and self.authorization_binding is not None
            and isinstance(expected_scope_authority, CoverageScopeAuthority)
        ):
            for record in self.proof_records:
                if not _validate_ledger_exclusion_record(
                    record,
                    source_inventory=source_inventory,
                    claim_requirement=claim_requirement,
                    expected_manifest=expected_manifest,
                    expected_authorization_binding=self.authorization_binding,
                    expected_scope_authority=expected_scope_authority,
                    definitive=False,
                ):
                    return False
        return True

    def _binding_valid_for_incomplete_claim(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding | None = None,
    ) -> bool:
        """Validate an incomplete claim without treating embedded scope as trusted.

        This private path is intentionally narrower than ``binding_valid_for_claim``:
        it checks only the typed ledger/inventory/requirement/manifest binding and
        the internal consistency of any embedded partition.  It never accepts an
        externally supplied authority and is only used for
        ``INSUFFICIENT_COVERAGE`` persistence/round trips.
        """

        if not self._base_binding_valid_for_claim(
            source_inventory,
            claim_requirement,
            expected_manifest,
            expected_authorization_binding,
        ):
            return False
        if self.authorization_binding is not None:
            for record in self.proof_records:
                if not _validate_ledger_exclusion_record(
                    record,
                    source_inventory=source_inventory,
                    claim_requirement=claim_requirement,
                    expected_manifest=expected_manifest,
                    expected_authorization_binding=self.authorization_binding,
                    expected_scope_authority=None,
                    definitive=False,
                ):
                    return False
        if self.scope_partition is None:
            return True
        if self.authorization_binding is None:
            return False
        return self.scope_partition._validate_against_scope_authority(
            source_inventory,
            claim_requirement,
            expected_manifest,
            self.authorization_binding,
            self.scope_partition.scope_authority,
        )

    def _base_binding_valid_for_claim(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding | None = None,
    ) -> bool:
        """Validate only non-authority ledger bindings for a private path."""

        if not isinstance(source_inventory, SourceInventory):
            raise ContractValidationError("binding validation requires SourceInventory")
        if not isinstance(claim_requirement, ClaimRequirement):
            raise ContractValidationError("binding validation requires ClaimRequirement")
        if not isinstance(expected_manifest, VersionManifest):
            raise ContractValidationError("binding validation requires VersionManifest")
        if expected_authorization_binding is not None and not isinstance(
            expected_authorization_binding,
            CoverageAuthorizationBinding,
        ):
            raise ContractValidationError("binding validation authorization must be typed")
        if self.source_inventory_id != source_inventory.source_inventory_id:
            return False
        if self.claim_requirement_id != claim_requirement.claim_requirement_id:
            return False
        if self.query_id != claim_requirement.query_id:
            return False
        if self.version_binding is None:
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
        if self.authorization_binding is None:
            if expected_authorization_binding is not None:
                return False
        elif expected_authorization_binding != self.authorization_binding:
            return False
        item_by_id = {item.source_inventory_item_id: item for item in source_inventory.items}
        return not (set(self.relevant_inventory_item_ids) - set(item_by_id))

    def _direct_proof_records_for_claim(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding | None = None,
        expected_scope_authority: CoverageScopeAuthority | None = None,
    ) -> tuple[CoverageProofRecord, ...]:
        """Return direct, typed proof records valid for this claim binding."""

        if not self.binding_valid_for_claim(
            source_inventory,
            claim_requirement,
            expected_manifest,
            expected_authorization_binding,
            expected_scope_authority,
        ):
            return ()
        if self.authorization_binding is None or self.scope_partition is None:
            return ()
        item_by_id = {item.source_inventory_item_id: item for item in source_inventory.items}
        unresolved = (
            set(self.omitted_inventory_item_ids)
            | set(self.failed_inventory_item_ids)
            | set(self.unsupported_inventory_item_ids)
            | set(self.redacted_inventory_item_ids)
        )
        searched_structural = set(self.searched_structural_observation_ids)
        searched_ordinary = set(self.searched_ordinary_observation_ids)
        direct_records: list[CoverageProofRecord] = []
        for record in self.proof_records:
            if record.proof_kind not in {"structural", "ordinary", "combined"}:
                continue
            item = item_by_id.get(record.inventory_item_id)
            if (
                item is None
                or item.source_inventory_item_id not in self.relevant_inventory_item_ids
            ):
                continue
            if item.source_inventory_item_id in unresolved or item.processing_state != "parsed":
                continue
            if (
                record.source_inventory_id != self.source_inventory_id
                or record.claim_requirement_id != self.claim_requirement_id
                or record.version_manifest_id != expected_manifest.version_manifest_id
            ):
                continue
            source_observation_ids = set(item.source_observation_ids)
            structural_ids = set(record.structural_observation_ids)
            ordinary_ids = set(record.ordinary_observation_ids)
            if not structural_ids.issubset(source_observation_ids) or not ordinary_ids.issubset(
                source_observation_ids
            ):
                continue
            partition = self.scope_partition.observation_partition_for(
                item.source_inventory_item_id
            )
            if partition is None:
                continue
            if not structural_ids.issubset(
                set(partition.structural_observation_ids)
            ) or not ordinary_ids.issubset(set(partition.ordinary_observation_ids)):
                continue
            if not structural_ids.issubset(searched_structural) or not ordinary_ids.issubset(
                searched_ordinary
            ):
                continue
            if not structural_ids and not ordinary_ids:
                continue
            direct_records.append(record)
        return tuple(direct_records)

    def has_direct_authorized_witness(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding | None = None,
        expected_scope_authority: CoverageScopeAuthority | None = None,
    ) -> bool:
        return bool(
            self._direct_proof_records_for_claim(
                source_inventory,
                claim_requirement,
                expected_manifest,
                expected_authorization_binding,
                expected_scope_authority,
            )
        )

    def has_direct_incompatible_values(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding | None = None,
        expected_scope_authority: CoverageScopeAuthority | None = None,
    ) -> bool:
        """Require two distinct typed populated-value proofs for partial conflict."""

        direct_values = [
            (
                record.populated_value_fingerprint,
                frozenset(record.structural_observation_ids)
                | frozenset(record.ordinary_observation_ids),
            )
            for record in self._direct_proof_records_for_claim(
                source_inventory,
                claim_requirement,
                expected_manifest,
                expected_authorization_binding,
                expected_scope_authority,
            )
            if record.populated_value_fingerprint is not None
        ]
        return any(
            first_fingerprint != second_fingerprint
            and first_observations.isdisjoint(second_observations)
            for index, (first_fingerprint, first_observations) in enumerate(direct_values)
            for second_fingerprint, second_observations in direct_values[index + 1 :]
        )

    def usable_for_claim(
        self,
        source_inventory: SourceInventory,
        claim_requirement: ClaimRequirement,
        expected_manifest: VersionManifest,
        expected_authorization_binding: CoverageAuthorizationBinding | None = None,
        expected_scope_authority: CoverageScopeAuthority | None = None,
    ) -> bool:
        """Return true only after validating all typed proof inputs."""

        if not self.binding_valid_for_claim(
            source_inventory,
            claim_requirement,
            expected_manifest,
            expected_authorization_binding,
            expected_scope_authority,
        ):
            return False
        if not self.complete_authorized_scope:
            return False
        if self.authorization_binding is None or self.version_binding is None:
            return False
        if self.scope_partition is None:
            return False
        if not self.scope_partition.validate_for_claim(
            source_inventory,
            claim_requirement,
            expected_manifest,
            self.authorization_binding,
            expected_scope_authority,
        ):
            return False
        if set(self.relevant_inventory_item_ids) != set(
            self.scope_partition.authorized_relevant_item_ids
        ):
            return False
        if any(
            partition.non_search_observation_ids
            for partition in self.scope_partition.observation_partitions
        ):
            return False
        item_by_id = {item.source_inventory_item_id: item for item in source_inventory.items}
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
        partition_structural_ids = {
            observation_id
            for partition in self.scope_partition.observation_partitions
            for observation_id in partition.structural_observation_ids
        }
        partition_ordinary_ids = {
            observation_id
            for partition in self.scope_partition.observation_partitions
            for observation_id in partition.ordinary_observation_ids
        }
        if (
            set(self.searched_structural_observation_ids) != partition_structural_ids
            or set(self.searched_ordinary_observation_ids) != partition_ordinary_ids
            or searched_observation_ids != relevant_observation_ids
        ):
            return False
        proof_by_item = {record.inventory_item_id: record for record in self.proof_records}
        ordinary_proof_by_item = {
            item_id: record
            for item_id, record in proof_by_item.items()
            if record.proof_kind != "intentionally_excluded"
        }
        if set(ordinary_proof_by_item) != set(self.relevant_inventory_item_ids):
            return False
        excluded_item_ids = {
            item.source_inventory_item_id
            for item in source_inventory.items
            if item.processing_state == "intentionally_excluded"
        }
        exclusion_proof_by_item = {
            item_id: record
            for item_id, record in proof_by_item.items()
            if record.proof_kind == "intentionally_excluded"
        }
        if set(exclusion_proof_by_item) != excluded_item_ids:
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
            if record.proof_kind == "intentionally_excluded":
                if (
                    record.inventory_item_id in self.relevant_inventory_item_ids
                    or not _validate_ledger_exclusion_record(
                        record,
                        source_inventory=source_inventory,
                        claim_requirement=claim_requirement,
                        expected_manifest=expected_manifest,
                        expected_authorization_binding=self.authorization_binding,
                        expected_scope_authority=expected_scope_authority,
                        definitive=True,
                    )
                ):
                    return False
                continue
            partition = self.scope_partition.observation_partition_for(record.inventory_item_id)
            if partition is None:
                return False
            if set(record.structural_observation_ids) != set(
                partition.structural_observation_ids
            ) or set(record.ordinary_observation_ids) != set(partition.ordinary_observation_ids):
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
    coverage_ledger: CoverageLedger | None = field(default=None, repr=False, compare=False)
    claim_requirement: ClaimRequirement | None = field(default=None, repr=False, compare=False)
    source_inventory: SourceInventory | None = field(default=None, repr=False, compare=False)
    version_manifest: VersionManifest | None = field(default=None, repr=False, compare=False)
    scope_authority: CoverageScopeAuthority | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _untrusted_scope_authority: CoverageScopeAuthority | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    authorization_binding: CoverageAuthorizationBinding | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _wire_only: bool = field(default=False, repr=False, compare=False)
    _factory_token: object | None = field(default=None, repr=False, compare=False)

    def __reduce_ex__(self, protocol: int) -> object:
        raise TypeError("answer claims cannot be serialized; use to_persistence_dict instead")

    def __copy__(self) -> object:
        raise TypeError("answer claims cannot be copied")

    def __deepcopy__(self, memo: dict[int, object]) -> object:
        raise TypeError("answer claims cannot be deep-copied")

    def __post_init__(self) -> None:
        if self._wire_only:
            if any(
                binding is not None
                for binding in (
                    self.coverage_ledger,
                    self.claim_requirement,
                    self.source_inventory,
                    self.version_manifest,
                    self.scope_authority,
                    self._untrusted_scope_authority,
                    self.authorization_binding,
                )
            ):
                raise ContractValidationError("wire-only answer claims cannot carry bindings")
        else:
            if (
                self.state != "INSUFFICIENT_COVERAGE"
                and self._factory_token is not _ANSWER_CLAIM_FACTORY_TOKEN
            ):
                raise ContractValidationError(
                    "definitive answer claims must be constructed through the validated factory"
                )
            binding_values = {
                "claim_requirement_id": self.claim_requirement_id,
                "coverage_ledger_id": self.coverage_ledger_id,
                "source_fingerprint": self.source_fingerprint,
                "parser_fingerprint": self.parser_fingerprint,
                "tokenizer_fingerprint": self.tokenizer_fingerprint,
                "index_fingerprint": self.index_fingerprint,
                "version_manifest_id": self.version_manifest_id,
                "implementation_fingerprint": self.implementation_fingerprint,
            }
            if self.state == "INSUFFICIENT_COVERAGE" and self.scope_authority is None:
                normalized = _validated_incomplete_answer_claim_binding(
                    binding_values,
                    coverage_ledger=self.coverage_ledger,
                    claim_requirement=self.claim_requirement,
                    source_inventory=self.source_inventory,
                    version_manifest=self.version_manifest,
                    authorization_binding=self.authorization_binding,
                )
            else:
                normalized = _validated_answer_claim_binding(
                    binding_values,
                    coverage_ledger=self.coverage_ledger,
                    claim_requirement=self.claim_requirement,
                    source_inventory=self.source_inventory,
                    version_manifest=self.version_manifest,
                    scope_authority=self.scope_authority,
                    authorization_binding=self.authorization_binding,
                )
            for field_name, value in normalized.items():
                object.__setattr__(self, field_name, value)
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
        if not self._wire_only:
            _validate_answer_claim_state(
                state=self.state,
                claim_requirement=self.claim_requirement,
                coverage_ledger=self.coverage_ledger,
                source_inventory=self.source_inventory,
                version_manifest=self.version_manifest,
                scope_authority=self.scope_authority,
                authorization_binding=self.authorization_binding,
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
    def create(
        cls,
        *,
        coverage_ledger: CoverageLedger | None = None,
        claim_requirement: ClaimRequirement | None = None,
        source_inventory: SourceInventory | None = None,
        version_manifest: VersionManifest | None = None,
        expected_scope_authority: CoverageScopeAuthority | None = None,
        scope_authority: CoverageScopeAuthority | None = None,
        authorization_binding: CoverageAuthorizationBinding | None = None,
        **values: Any,
    ) -> "AnswerClaim":
        if scope_authority is not None:
            raise ContractValidationError(
                "answer claim creation requires expected_scope_authority; "
                "scope_authority is an internal validated binding"
            )
        values = dict(values)
        for field_name in ("reason_codes", "evidence_snapshot_ids"):
            if field_name in values:
                values[field_name] = tuple(values[field_name])
        if values.get("state") == "INSUFFICIENT_COVERAGE" and expected_scope_authority is None:
            normalized = _validated_incomplete_answer_claim_binding(
                values,
                coverage_ledger=coverage_ledger,
                claim_requirement=claim_requirement,
                source_inventory=source_inventory,
                version_manifest=version_manifest,
                authorization_binding=authorization_binding,
            )
        else:
            normalized = _validated_answer_claim_binding(
                values,
                coverage_ledger=coverage_ledger,
                claim_requirement=claim_requirement,
                source_inventory=source_inventory,
                version_manifest=version_manifest,
                scope_authority=expected_scope_authority,
                authorization_binding=authorization_binding,
            )
        values.update(normalized)
        return cls(
            **values,
            coverage_ledger=coverage_ledger,
            claim_requirement=claim_requirement,
            source_inventory=source_inventory,
            version_manifest=version_manifest,
            scope_authority=expected_scope_authority,
            authorization_binding=authorization_binding,
            _factory_token=_ANSWER_CLAIM_FACTORY_TOKEN,
        )

    def to_dict(self) -> dict[str, Any]:
        if self._wire_only and self.state != "INSUFFICIENT_COVERAGE":
            raise ContractValidationError(
                "wire-only answer claims cannot emit authoritative success states"
            )
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
        if self._wire_only:
            raise ContractValidationError(
                "wire-only answer claims cannot be persisted without validated bindings"
            )
        binding_values = {
            "claim_requirement_id": self.claim_requirement_id,
            "coverage_ledger_id": self.coverage_ledger_id,
            "source_fingerprint": self.source_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "tokenizer_fingerprint": self.tokenizer_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "version_manifest_id": self.version_manifest_id,
            "implementation_fingerprint": self.implementation_fingerprint,
        }
        if self.state == "INSUFFICIENT_COVERAGE" and self.scope_authority is None:
            _validated_incomplete_answer_claim_binding(
                binding_values,
                coverage_ledger=self.coverage_ledger,
                claim_requirement=self.claim_requirement,
                source_inventory=self.source_inventory,
                version_manifest=self.version_manifest,
                authorization_binding=self.authorization_binding,
            )
        else:
            _validated_answer_claim_binding(
                binding_values,
                coverage_ledger=self.coverage_ledger,
                claim_requirement=self.claim_requirement,
                source_inventory=self.source_inventory,
                version_manifest=self.version_manifest,
                scope_authority=self.scope_authority,
                authorization_binding=self.authorization_binding,
            )
        payload = {
            "answer_claim_id": self.answer_claim_id,
            **self.to_dict(),
            "version_manifest_id": self.version_manifest_id,
            "implementation_fingerprint": self.implementation_fingerprint,
            "scope_authority": (
                self.scope_authority.to_persistence_dict()
                if self.scope_authority is not None
                else (
                    self._untrusted_scope_authority.to_persistence_dict()
                    if self._untrusted_scope_authority is not None
                    else None
                )
            ),
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
            _wire_only=True,
        )

    @classmethod
    def from_persistence_dict(
        cls,
        value: Mapping[str, Any],
        *,
        coverage_ledger: CoverageLedger | None = None,
        claim_requirement: ClaimRequirement | None = None,
        source_inventory: SourceInventory | None = None,
        version_manifest: VersionManifest | None = None,
        expected_scope_authority: CoverageScopeAuthority | None = None,
        scope_authority: CoverageScopeAuthority | None = None,
        authorization_binding: CoverageAuthorizationBinding | None = None,
    ) -> "AnswerClaim":
        item = _mapping(value, "answer_claim.persistence")
        _require_exact_keys(
            item,
            _ANSWER_CLAIM_PERSISTENCE_KEYS,
            "answer_claim.persistence",
            required=_ANSWER_CLAIM_PERSISTENCE_KEYS - {"scope_authority"},
        )
        if scope_authority is not None:
            raise ContractValidationError(
                "answer claim persistence requires expected_scope_authority; "
                "scope_authority is not a trusted input"
            )
        trusted_scope_authority = expected_scope_authority
        persisted_state = _required_str(item, "state")
        persisted_scope_authority = item.get("scope_authority")
        parsed_scope_authority = None
        if persisted_scope_authority is not None:
            parsed_scope_authority = CoverageScopeAuthority.from_persistence_dict(
                _mapping(persisted_scope_authority, "answer_claim.scope_authority")
            )
            if (
                trusted_scope_authority is not None
                and trusted_scope_authority != parsed_scope_authority
            ):
                raise ContractValidationError(
                    "answer claim scope authority does not match persistence"
                )
        if persisted_state != "INSUFFICIENT_COVERAGE" and (
            trusted_scope_authority is None or persisted_scope_authority is None
        ):
            raise ContractValidationError(
                "authoritative persisted claims require an independently supplied "
                "scope authority binding"
            )
        if persisted_state == "INSUFFICIENT_COVERAGE" and trusted_scope_authority is None:
            normalized = _validated_incomplete_answer_claim_binding(
                item,
                coverage_ledger=coverage_ledger,
                claim_requirement=claim_requirement,
                source_inventory=source_inventory,
                version_manifest=version_manifest,
                authorization_binding=authorization_binding,
            )
        else:
            normalized = _validated_answer_claim_binding(
                item,
                coverage_ledger=coverage_ledger,
                claim_requirement=claim_requirement,
                source_inventory=source_inventory,
                version_manifest=version_manifest,
                scope_authority=trusted_scope_authority,
                authorization_binding=authorization_binding,
            )
        return cls(
            answer_claim_id=_required_str(item, "answer_claim_id"),
            state=persisted_state,
            reason_codes=_tuple_strings(item, "reason_codes", codes=True),
            claim_requirement_id=normalized["claim_requirement_id"],
            coverage_ledger_id=normalized["coverage_ledger_id"],
            evidence_snapshot_ids=_tuple_strings(item, "evidence_snapshot_ids", ids=True),
            source_fingerprint=normalized["source_fingerprint"],
            parser_fingerprint=normalized["parser_fingerprint"],
            tokenizer_fingerprint=normalized["tokenizer_fingerprint"],
            index_fingerprint=normalized["index_fingerprint"],
            version_manifest_id=normalized["version_manifest_id"],
            implementation_fingerprint=normalized["implementation_fingerprint"],
            coverage_ledger=coverage_ledger,
            claim_requirement=claim_requirement,
            source_inventory=source_inventory,
            version_manifest=version_manifest,
            scope_authority=trusted_scope_authority,
            _untrusted_scope_authority=(
                parsed_scope_authority
                if persisted_state == "INSUFFICIENT_COVERAGE" and trusted_scope_authority is None
                else None
            ),
            authorization_binding=authorization_binding,
            _factory_token=_ANSWER_CLAIM_FACTORY_TOKEN,
        )


def _validated_answer_claim_fields(
    values: Mapping[str, Any],
    *,
    coverage_ledger: CoverageLedger | None,
    claim_requirement: ClaimRequirement | None,
    source_inventory: SourceInventory | None,
    version_manifest: VersionManifest | None,
    authorization_binding: CoverageAuthorizationBinding | None,
) -> dict[str, Any]:
    if not isinstance(coverage_ledger, CoverageLedger):
        raise ContractValidationError("answer claim requires a typed CoverageLedger")
    if not isinstance(claim_requirement, ClaimRequirement):
        raise ContractValidationError("answer claim requires a typed ClaimRequirement")
    if not isinstance(source_inventory, SourceInventory):
        raise ContractValidationError("answer claim requires a typed SourceInventory")
    if not isinstance(version_manifest, VersionManifest):
        raise ContractValidationError("answer claim requires a typed VersionManifest")
    if authorization_binding is not None and not isinstance(
        authorization_binding,
        CoverageAuthorizationBinding,
    ):
        raise ContractValidationError("answer claim authorization binding must be typed")
    expected_authorization = coverage_ledger.authorization_binding
    if expected_authorization is not None:
        if authorization_binding is None or authorization_binding != expected_authorization:
            raise ContractValidationError(
                "answer claim authorization binding does not match coverage"
            )
    elif authorization_binding is not None:
        raise ContractValidationError(
            "answer claim supplied authorization without a ledger binding"
        )

    derived = {
        "claim_requirement_id": claim_requirement.claim_requirement_id,
        "coverage_ledger_id": coverage_ledger.coverage_ledger_id,
        "source_fingerprint": version_manifest.source_fingerprint,
        "parser_fingerprint": version_manifest.parser_fingerprint,
        "tokenizer_fingerprint": version_manifest.tokenizer_fingerprint,
        "index_fingerprint": version_manifest.index_fingerprint,
        "version_manifest_id": version_manifest.version_manifest_id,
        "implementation_fingerprint": version_manifest.implementation_fingerprint,
    }
    for field_name, expected_value in derived.items():
        supplied_value = values.get(field_name)
        if supplied_value is not None and supplied_value != expected_value:
            raise ContractValidationError("answer claim binding fields do not match typed evidence")
    return derived


def _validated_answer_claim_binding(
    values: Mapping[str, Any],
    *,
    coverage_ledger: CoverageLedger | None,
    claim_requirement: ClaimRequirement | None,
    source_inventory: SourceInventory | None,
    version_manifest: VersionManifest | None,
    scope_authority: CoverageScopeAuthority | None,
    authorization_binding: CoverageAuthorizationBinding | None,
) -> dict[str, Any]:
    derived = _validated_answer_claim_fields(
        values,
        coverage_ledger=coverage_ledger,
        claim_requirement=claim_requirement,
        source_inventory=source_inventory,
        version_manifest=version_manifest,
        authorization_binding=authorization_binding,
    )
    if coverage_ledger is None:
        raise ContractValidationError("answer claim requires a typed CoverageLedger")
    if coverage_ledger.scope_partition is not None:
        if scope_authority is None:
            raise ContractValidationError(
                "authoritative claims require the independent scope authority bound to coverage"
            )
        if scope_authority != coverage_ledger.scope_partition.scope_authority:
            raise ContractValidationError("answer claim scope authority does not match coverage")
    elif scope_authority is not None:
        raise ContractValidationError(
            "answer claim supplied scope authority without a scope partition"
        )
    if not coverage_ledger.binding_valid_for_claim(
        source_inventory,
        claim_requirement,
        version_manifest,
        authorization_binding,
        scope_authority,
    ):
        raise ContractValidationError("answer claim coverage binding is not usable")
    return derived


def _validated_incomplete_answer_claim_binding(
    values: Mapping[str, Any],
    *,
    coverage_ledger: CoverageLedger | None,
    claim_requirement: ClaimRequirement | None,
    source_inventory: SourceInventory | None,
    version_manifest: VersionManifest | None,
    authorization_binding: CoverageAuthorizationBinding | None,
) -> dict[str, Any]:
    derived = _validated_answer_claim_fields(
        values,
        coverage_ledger=coverage_ledger,
        claim_requirement=claim_requirement,
        source_inventory=source_inventory,
        version_manifest=version_manifest,
        authorization_binding=authorization_binding,
    )
    if not coverage_ledger._binding_valid_for_incomplete_claim(
        source_inventory,
        claim_requirement,
        version_manifest,
        authorization_binding,
    ):
        raise ContractValidationError("answer claim incomplete coverage binding is not valid")
    return derived


def _validate_answer_claim_state(
    *,
    state: str,
    claim_requirement: ClaimRequirement | None,
    coverage_ledger: CoverageLedger | None,
    source_inventory: SourceInventory | None,
    version_manifest: VersionManifest | None,
    scope_authority: CoverageScopeAuthority | None,
    authorization_binding: CoverageAuthorizationBinding | None,
) -> None:
    if not isinstance(claim_requirement, ClaimRequirement):
        raise ContractValidationError("answer claim state requires a typed ClaimRequirement")
    if not isinstance(coverage_ledger, CoverageLedger):
        raise ContractValidationError("answer claim state requires a typed CoverageLedger")
    if not isinstance(source_inventory, SourceInventory):
        raise ContractValidationError("answer claim state requires a typed SourceInventory")
    if not isinstance(version_manifest, VersionManifest):
        raise ContractValidationError("answer claim state requires a typed VersionManifest")
    _choice(state, ANSWER_CLAIM_STATE_VALUES, "answer_claim.state")
    if state == "INSUFFICIENT_COVERAGE":
        return
    support_only = _support_only_completeness(claim_requirement)
    complete = coverage_ledger.usable_for_claim(
        source_inventory,
        claim_requirement,
        version_manifest,
        authorization_binding,
        scope_authority,
    )
    if state == "FOUND":
        if complete:
            return
        if (
            claim_requirement.kind == "existential_witness"
            and support_only
            and coverage_ledger.has_direct_authorized_witness(
                source_inventory,
                claim_requirement,
                version_manifest,
                authorization_binding,
                scope_authority,
            )
        ):
            return
        raise ContractValidationError(
            "answer claim FOUND requires complete claim proof or an authorized existential witness"
        )
    if state == "CONFLICT":
        if complete:
            return
        if claim_requirement.kind in {"single_value", "latest_value", "current_value"} and (
            coverage_ledger.has_direct_incompatible_values(
                source_inventory,
                claim_requirement,
                version_manifest,
                authorization_binding,
                scope_authority,
            )
        ):
            return
        raise ContractValidationError(
            "answer claim CONFLICT requires complete proof or typed direct incompatible values"
        )
    if not complete:
        raise ContractValidationError(
            "answer claim NOT_FOUND_WITHIN_COMPLETE_SCOPE requires complete claim proof"
        )


def _support_only_completeness(requirement: ClaimRequirement) -> bool:
    if "support_only_completeness" not in requirement.parameters:
        return False
    return _strict_bool(
        requirement.parameters["support_only_completeness"],
        "claim_requirement.parameters.support_only_completeness",
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


def _persistence_dataclass_payload(value: Any) -> dict[str, Any]:
    if not is_dataclass(value):
        raise ContractValidationError("contract persistence payload requires a record")
    return {
        key: _persistence_plain(item) for key, item in value.__dict__.items() if item is not None
    }


def _source_inventory_item_identity_payload_from_mapping(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        str(key): _persistence_plain(item)
        for key, item in value.items()
        if key != "source_inventory_item_id"
    }
    proof = payload.get("intentional_exclusion_proof")
    if isinstance(proof, Mapping):
        proof_payload = dict(proof)
        for key in (
            "source_inventory_id",
            "source_inventory_item_id",
            "proof_id",
            "proof_fingerprint",
        ):
            proof_payload.pop(key, None)
        payload["intentional_exclusion_proof"] = proof_payload
    return payload


def _source_inventory_item_identity_payload(
    item: SourceInventoryItem,
) -> dict[str, Any]:
    return _source_inventory_item_identity_payload_from_mapping(item.to_persistence_dict())


def _inventory_item_identity_payload(item: SourceInventoryItem) -> dict[str, Any]:
    payload = _source_inventory_item_identity_payload(item)
    payload.pop("source_inventory_id", None)
    return payload


def _coverage_proof_semantic_key(record: CoverageProofRecord) -> tuple[Any, ...]:
    return (
        record.source_inventory_id,
        record.claim_requirement_id,
        record.version_manifest_id,
        record.inventory_item_id,
        record.proof_kind,
        frozenset(record.structural_observation_ids),
        frozenset(record.ordinary_observation_ids),
        record.populated_value_fingerprint,
        (
            None
            if record.intentional_exclusion_proof is None
            else record.intentional_exclusion_proof.proof_fingerprint
        ),
    )


def _structural_denial() -> dict[str, Any]:
    """One existence/cardinality-neutral denial shape for all structures."""

    return {"status": "denied", "reason_code": "scope_denied"}


def _require_structural_scope_decision(
    value: Any,
) -> StructuralPublicScopeDecision:
    if not isinstance(value, StructuralPublicScopeDecision):
        raise ContractValidationError(
            "structural public serialization requires a typed scope decision"
        )
    return value


def _structural_public_summary(
    decision: StructuralPublicScopeDecision,
    record_type: str,
    summary: Mapping[str, Any],
    private_payload: Mapping[str, Any],
) -> dict[str, Any]:
    if decision.decision_state != "authorized":
        return _structural_denial()
    payload = {
        "status": "authorized",
        "record_type": record_type,
        "summary": dict(summary),
        "governed_reference": (
            f"governed:{record_type}:"
            f"{sha256_json({'record_type': record_type, 'payload': _persistence_plain(private_payload), 'scope': decision.permission_scope_fingerprint})[7:]}"
        ),
    }
    _assert_public_contract(payload, f"{record_type}.public")
    return payload


def _validate_exclusion_proof(item: SourceInventoryItem) -> None:
    if item.processing_state == "intentionally_excluded":
        if item.intentional_exclusion_proof is None:
            raise ContractValidationError(
                "intentionally_excluded inventory items require a typed exclusion proof"
            )
        return
    if item.intentional_exclusion_proof is not None:
        raise ContractValidationError(
            "typed exclusion proof is only valid for intentionally_excluded items"
        )


def _validate_ledger_exclusion_record(
    record: CoverageProofRecord,
    *,
    source_inventory: SourceInventory,
    claim_requirement: ClaimRequirement,
    expected_manifest: VersionManifest,
    expected_authorization_binding: CoverageAuthorizationBinding | None,
    expected_scope_authority: CoverageScopeAuthority | None,
    definitive: bool,
) -> bool:
    if record.proof_kind != "intentionally_excluded":
        return True
    item = next(
        (
            candidate
            for candidate in source_inventory.items
            if candidate.source_inventory_item_id == record.inventory_item_id
        ),
        None,
    )
    if item is None or expected_authorization_binding is None:
        return False
    proof = record.intentional_exclusion_proof
    if proof is None:
        return False
    return proof.validate_for_claim(
        source_inventory=source_inventory,
        source_inventory_item=item,
        claim_requirement=claim_requirement,
        expected_manifest=expected_manifest,
        expected_authorization_binding=expected_authorization_binding,
        expected_scope_authority=expected_scope_authority,
        definitive=definitive,
    )


def _source_unit_fingerprint(item: SourceInventoryItem) -> str:
    """Fingerprint the raw logical unit without circular identity fields."""

    payload = item.to_persistence_dict()
    payload.pop("source_inventory_item_id", None)
    payload.pop("source_inventory_id", None)
    payload.pop("processing_state", None)
    payload.pop("raw_retention_state", None)
    payload.pop("intentional_exclusion_proof", None)
    return sha256_json(payload)


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


def _persistence_plain(value: Any) -> Any:
    if isinstance(value, IntentionalExclusionProof):
        return value.to_persistence_dict()
    if isinstance(value, StructuralCell):
        return value.to_persistence_dict()
    if isinstance(value, StructuralColumn):
        return value.to_persistence_dict()
    if isinstance(value, StructuralRow):
        return value.to_persistence_dict()
    if isinstance(value, SourceInventoryItem):
        return value.to_persistence_dict()
    if isinstance(value, SourceInventory):
        return value.to_persistence_dict()
    if isinstance(value, StructuralObservation):
        return value.to_persistence_dict()
    if is_dataclass(value):
        return {
            key: _persistence_plain(item)
            for key, item in value.__dict__.items()
            if item is not None
        }
    if isinstance(value, Mapping):
        return {
            str(key): _persistence_plain(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, (list, tuple)):
        return [_persistence_plain(item) for item in value]
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
                if key
                in {
                    "authorization_binding",
                    "authorization_decisions",
                    "scope_authority",
                }
                else "rd"
                if key == "relevance_decisions"
                else "sp"
                if key == "scope_policy"
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
    "COVERAGE_ITEM_AUTHORIZATION_STATE_VALUES",
    "COVERAGE_ITEM_RELEVANCE_STATE_VALUES",
    "COVERAGE_NON_SEARCH_REASON_VALUES",
    "COVERAGE_PROOF_KIND_VALUES",
    "CoverageAuthorizationBinding",
    "CoverageItemAuthorizationDecision",
    "CoverageItemRelevanceDecision",
    "CoverageFallbackStatus",
    "CoverageFallbackUsage",
    "CoverageLedger",
    "CoverageNonSearchReason",
    "CoverageObservationPartition",
    "CoverageProofKind",
    "CoverageProofRecord",
    "CoverageScopePartition",
    "CoverageScopeAuthority",
    "CoverageScopeAuthorityVerifier",
    "CoverageScopePolicyBinding",
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
    "StructuralPublicScopeDecision",
    "StructuralRow",
    "VersionManifest",
    "fingerprint_manifest",
    "validate_fingerprint_binding",
]
