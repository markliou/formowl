"""Bounded structural-evidence recovery for the diagnostic MCP sidecar."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
from typing import Any, Mapping, Sequence
import uuid

from formowl_contract import (
    Asset,
    ClaimRequirement,
    ContractValidationError,
    CoverageAuthorizationBinding,
    CoverageItemAuthorizationDecision,
    CoverageItemRelevanceDecision,
    CoverageLedger,
    CoverageObservationPartition,
    CoverageProofRecord,
    CoverageScopeAuthority,
    CoverageScopeAuthorityVerifier,
    CoverageScopePartition,
    CoverageScopePolicyBinding,
    CoverageVersionBinding,
    DisplayPagination,
    SourceInventory,
    StructuralObservation,
    VersionManifest,
    sha256_json,
    stable_resource_contract_id,
    validate_permission_scope,
)
from formowl_ingestion.extraction import ExtractionInput
from formowl_ingestion.extractors.mail.pst import (
    PST_INVENTORY_CARRIER_OBSERVATION_TYPE,
    PST_SOURCE_UNIT_OBSERVATION_TYPE,
    PST_READPST_PARALLEL_JOBS,
    PstMailArchiveExtractor,
    PstReadpstMessageSelector,
    _parser_config,
    _pst_parser_fingerprint,
    _PST_SOURCE_UNIT_ATTACHMENT,
    _PST_SOURCE_UNIT_MESSAGE,
    _PST_SOURCE_UNIT_SIDECAR,
    _source_unit_kind_for_path,
    export_pst_to_readpst_directory,
    extract_readpst_export,
    extract_selected_readpst_export,
    select_readpst_export_messages,
)
from formowl_ingestion.storage import AssetStore, ObservationStore, UploadSessionStore

from .bundle import MailEvidenceBundle, build_mail_evidence_bundle
from .diagnostic_mcp import DiagnosticSemanticProfile
from .persistence import (
    DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND,
    DIAGNOSTIC_STRUCTURAL_BRIDGE_IMPLEMENTATION_VERSION,
    DIAGNOSTIC_STRUCTURAL_BRIDGE_PRODUCER_TYPE,
    DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID,
    DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_VERSION,
    DiagnosticExistingExportVerification,
    DiagnosticStructuralAggregateManifest,
    DiagnosticStructuralShardRecord,
    FileDiagnosticStructuralShardStore,
    FileMailEvidenceBundleStore,
    diagnostic_structural_baseline_parameters,
    diagnostic_structural_implementation_fingerprint,
    diagnostic_structural_scope_policy_fingerprint,
    sha256_file,
)

_DEFAULT_PST_MIME_TYPE = "application/vnd.ms-outlook"
_READPST_PER_JOB_MEMORY_RESERVE_BYTES = 2 * 1024 * 1024 * 1024
_MATERIALIZATION_MEMORY_POLICY_BYTES = 20 * 1024 * 1024 * 1024
_BUNDLE_BODY_SEGMENT_MEMORY_RESERVE_BYTES = 24 * 1024
_BUNDLE_MESSAGE_MEMORY_RESERVE_BYTES = 96 * 1024
_SCOPE_AUTHORITY_ROOT_FILE_MAX_BYTES = 4096
_EXISTING_EXPORT_READ_BUFFER_BYTES = 1024 * 1024
_LEGACY_CHECKPOINT_ARTIFACT_TYPES = frozenset(
    {
        "diagnostic_readpst_export_checkpoint_v1",
        "diagnostic_structural_selection_checkpoint_v1",
        "diagnostic_structural_materialization_state_v1",
    }
)
_READPST_EXPORT_CHECKPOINT_ARTIFACT_TYPE = "diagnostic_readpst_export_checkpoint_v2"
_SELECTION_CHECKPOINT_ARTIFACT_TYPE = "diagnostic_structural_selection_checkpoint_v2"
_CURRENT_EXPORT_NATIVE_SELECTION_CHECKPOINT_ARTIFACT_TYPE = (
    "diagnostic_current_export_native_selection_checkpoint_v1"
)
_MATERIALIZATION_STATE_ARTIFACT_TYPE = "diagnostic_structural_materialization_state_v2"
_SHARD_CHECKPOINT_ARTIFACT_TYPE = "diagnostic_structural_shard_checkpoint_v3"
_HISTORICAL_SCOPE_COMPATIBILITY_CHECKPOINT_ARTIFACT_TYPE = (
    "diagnostic_historical_scope_compatibility_checkpoint_v1"
)
_HISTORICAL_SCOPE_COMPATIBILITY_CHECKPOINT_MAX_BYTES = 64 * 1024 * 1024
_SCOPE_MANIFEST_FILE_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_DIAGNOSTIC_SHARD_BATCH_SIZE = 128
_MAX_DIAGNOSTIC_SHARD_BATCH_SIZE = 1024
_DIAGNOSTIC_ANCILLARY_PROCESSING_STATES = frozenset(
    {
        "parsed",
        "preserved_unparsed",
        "unsupported",
    }
)


@dataclass(frozen=True)
class DiagnosticStructuralBridgePublication:
    """The canonical bundle published for one bounded selected-export recovery."""

    mail_evidence_bundle_id: str
    bundle_path: Path
    selected_message_count: int
    structural_observation_count: int
    created: bool


@dataclass(frozen=True)
class DiagnosticStructuralScopeSelector:
    """One private historical-mail selector with an explicit multiplicity."""

    selector_id: str
    message_id: str
    folder_path_hash: str
    body_hash: str
    expected_occurrence_count: int

    def __post_init__(self) -> None:
        for field_name in ("selector_id", "message_id", "folder_path_hash", "body_hash"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"diagnostic scope {field_name} is invalid")
        if (
            not isinstance(self.expected_occurrence_count, int)
            or isinstance(self.expected_occurrence_count, bool)
            or self.expected_occurrence_count < 1
        ):
            raise ContractValidationError("diagnostic scope selector count is invalid")

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "selector_id": self.selector_id,
            "message_id": self.message_id,
            "folder_path_hash": self.folder_path_hash,
            "body_hash": self.body_hash,
            "expected_occurrence_count": self.expected_occurrence_count,
        }

    @classmethod
    def from_private_dict(cls, value: Mapping[str, Any]) -> "DiagnosticStructuralScopeSelector":
        if not isinstance(value, Mapping) or set(value) != {
            "selector_id",
            "message_id",
            "folder_path_hash",
            "body_hash",
            "expected_occurrence_count",
        }:
            raise ContractValidationError("diagnostic scope selector is invalid")
        return cls(
            selector_id=_required_private_text(value, "selector_id"),
            message_id=_required_private_text(value, "message_id"),
            folder_path_hash=_required_private_text(value, "folder_path_hash"),
            body_hash=_required_private_text(value, "body_hash"),
            expected_occurrence_count=value["expected_occurrence_count"],
        )


@dataclass(frozen=True)
class DiagnosticStructuralScopeManifest:
    """Private, source-bound definition of the complete existing MAY scope."""

    scope_manifest_id: str
    source_asset_id: str
    source_fingerprint: str
    workspace_id: str
    owner_user_id: str
    permission_scope: Mapping[str, Any]
    expected_message_count: int
    expected_body_segment_count: int
    source_observation_set_fingerprint: str
    selectors: tuple[DiagnosticStructuralScopeSelector, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "scope_manifest_id",
            "source_asset_id",
            "source_fingerprint",
            "workspace_id",
            "owner_user_id",
            "source_observation_set_fingerprint",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"diagnostic scope manifest {field_name} is invalid")
        if (
            not isinstance(self.expected_message_count, int)
            or isinstance(self.expected_message_count, bool)
            or self.expected_message_count < 1
            or not isinstance(self.expected_body_segment_count, int)
            or isinstance(self.expected_body_segment_count, bool)
            or self.expected_body_segment_count < 0
        ):
            raise ContractValidationError("diagnostic scope manifest counts are invalid")
        normalized_scope = validate_permission_scope(dict(self.permission_scope))
        object.__setattr__(self, "permission_scope", normalized_scope)
        selectors = tuple(sorted(self.selectors, key=lambda item: item.selector_id))
        if not selectors or any(
            not isinstance(item, DiagnosticStructuralScopeSelector) for item in selectors
        ):
            raise ContractValidationError("diagnostic scope manifest selectors are invalid")
        if sum(item.expected_occurrence_count for item in selectors) != self.expected_message_count:
            raise ContractValidationError("diagnostic scope manifest selector count mismatch")
        selector_ids = [item.selector_id for item in selectors]
        if len(selector_ids) != len(set(selector_ids)):
            raise ContractValidationError("diagnostic scope manifest selector ids are not unique")
        expected_id = _scope_manifest_id(
            source_asset_id=self.source_asset_id,
            source_fingerprint=self.source_fingerprint,
            workspace_id=self.workspace_id,
            owner_user_id=self.owner_user_id,
            permission_scope=normalized_scope,
            expected_message_count=self.expected_message_count,
            expected_body_segment_count=self.expected_body_segment_count,
            source_observation_set_fingerprint=self.source_observation_set_fingerprint,
            selectors=selectors,
        )
        if self.scope_manifest_id != expected_id:
            raise ContractValidationError("diagnostic scope manifest identity is invalid")
        object.__setattr__(self, "selectors", selectors)

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "diagnostic_structural_scope_manifest_v1",
            "scope_manifest_id": self.scope_manifest_id,
            "source_asset_id": self.source_asset_id,
            "source_fingerprint": self.source_fingerprint,
            "workspace_id": self.workspace_id,
            "owner_user_id": self.owner_user_id,
            "permission_scope": dict(self.permission_scope),
            "expected_message_count": self.expected_message_count,
            "expected_body_segment_count": self.expected_body_segment_count,
            "source_observation_set_fingerprint": self.source_observation_set_fingerprint,
            "selectors": [item.to_private_dict() for item in self.selectors],
        }

    @classmethod
    def from_private_dict(cls, value: Mapping[str, Any]) -> "DiagnosticStructuralScopeManifest":
        if not isinstance(value, Mapping) or value.get("artifact_type") != (
            "diagnostic_structural_scope_manifest_v1"
        ):
            raise ContractValidationError("diagnostic scope manifest is invalid")
        required = {
            "artifact_type",
            "scope_manifest_id",
            "source_asset_id",
            "source_fingerprint",
            "workspace_id",
            "owner_user_id",
            "permission_scope",
            "expected_message_count",
            "expected_body_segment_count",
            "source_observation_set_fingerprint",
            "selectors",
        }
        if set(value) != required or not isinstance(value["permission_scope"], Mapping):
            raise ContractValidationError("diagnostic scope manifest is invalid")
        raw_selectors = value["selectors"]
        if not isinstance(raw_selectors, list):
            raise ContractValidationError("diagnostic scope manifest selectors are invalid")
        return cls(
            scope_manifest_id=_required_private_text(value, "scope_manifest_id"),
            source_asset_id=_required_private_text(value, "source_asset_id"),
            source_fingerprint=_required_private_text(value, "source_fingerprint"),
            workspace_id=_required_private_text(value, "workspace_id"),
            owner_user_id=_required_private_text(value, "owner_user_id"),
            permission_scope=dict(value["permission_scope"]),
            expected_message_count=value["expected_message_count"],
            expected_body_segment_count=value["expected_body_segment_count"],
            source_observation_set_fingerprint=_required_private_text(
                value,
                "source_observation_set_fingerprint",
            ),
            selectors=tuple(
                DiagnosticStructuralScopeSelector.from_private_dict(item) for item in raw_selectors
            ),
        )


@dataclass(frozen=True)
class DiagnosticCurrentExportNativeSelectionCheckpoint:
    """Private current-parser selection checkpoint for one complete export.

    The checkpoint is generated only after parsing the whole already-preserved
    export with the current parser.  It intentionally keeps relative paths
    private while binding them, the exact manifest bytes, parser identity, and
    byte-level export verification into one restartable materialization input.
    """

    checkpoint_fingerprint: str
    scope_manifest_id: str
    scope_manifest_sha256: str
    parser_fingerprint: str
    parser_source_inventory_id: str
    selected_message_paths: tuple[str, ...]
    selected_path_set_fingerprint: str
    scanned_message_count: int
    matched_occurrence_count: int
    existing_export_verification: DiagnosticExistingExportVerification

    def __post_init__(self) -> None:
        for field_name in (
            "checkpoint_fingerprint",
            "scope_manifest_sha256",
            "parser_fingerprint",
            "selected_path_set_fingerprint",
        ):
            _required_private_sha256(getattr(self, field_name), field_name)
        for field_name in ("scope_manifest_id", "parser_source_inventory_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ContractValidationError(
                    "diagnostic current-export selection checkpoint is invalid"
                )
        paths = tuple(_private_relative_export_path(path) for path in self.selected_message_paths)
        if (
            not paths
            or len(paths) != len(set(paths))
            or paths != tuple(sorted(paths))
            or self.selected_path_set_fingerprint != sha256_json(list(paths))
        ):
            raise ContractValidationError(
                "diagnostic current-export selection checkpoint paths are invalid"
            )
        for field_name, value in (
            ("scanned message count", self.scanned_message_count),
            ("matched occurrence count", self.matched_occurrence_count),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ContractValidationError(
                    f"diagnostic current-export selection checkpoint {field_name} is invalid"
                )
        verification = self.existing_export_verification
        if (
            not isinstance(verification, DiagnosticExistingExportVerification)
            or verification.scope_manifest_id != self.scope_manifest_id
            or verification.historical_compatibility_checkpoint_fingerprint is not None
            or verification.export_message_file_count != self.scanned_message_count
            or verification.parsed_export_message_count != len(paths)
            or verification.matched_message_occurrence_count != self.matched_occurrence_count
            or self.scanned_message_count != len(paths)
            or self.matched_occurrence_count != len(paths)
        ):
            raise ContractValidationError(
                "diagnostic current-export selection checkpoint coverage is invalid"
            )
        expected_fingerprint = _current_export_native_selection_checkpoint_fingerprint(
            scope_manifest_id=self.scope_manifest_id,
            scope_manifest_sha256=self.scope_manifest_sha256,
            parser_fingerprint=self.parser_fingerprint,
            parser_source_inventory_id=self.parser_source_inventory_id,
            selected_message_paths=paths,
            selected_path_set_fingerprint=self.selected_path_set_fingerprint,
            scanned_message_count=self.scanned_message_count,
            matched_occurrence_count=self.matched_occurrence_count,
            existing_export_verification=verification,
        )
        if self.checkpoint_fingerprint != expected_fingerprint:
            raise ContractValidationError(
                "diagnostic current-export selection checkpoint identity is invalid"
            )
        object.__setattr__(self, "selected_message_paths", paths)

    @classmethod
    def create(
        cls,
        *,
        scope_manifest: DiagnosticStructuralScopeManifest,
        parser_fingerprint: str,
        parser_source_inventory_id: str,
        selected_message_paths: Sequence[str],
        scanned_message_count: int,
        matched_occurrence_count: int,
        existing_export_verification: DiagnosticExistingExportVerification,
    ) -> "DiagnosticCurrentExportNativeSelectionCheckpoint":
        if not isinstance(scope_manifest, DiagnosticStructuralScopeManifest):
            raise ContractValidationError("diagnostic current-export scope manifest is invalid")
        paths = tuple(
            sorted(_private_relative_export_path(path) for path in selected_message_paths)
        )
        selected_path_set_fingerprint = sha256_json(list(paths))
        scope_manifest_sha256 = sha256_json(scope_manifest.to_private_dict())
        values = {
            "scope_manifest_id": scope_manifest.scope_manifest_id,
            "scope_manifest_sha256": scope_manifest_sha256,
            "parser_fingerprint": parser_fingerprint,
            "parser_source_inventory_id": parser_source_inventory_id,
            "selected_message_paths": paths,
            "selected_path_set_fingerprint": selected_path_set_fingerprint,
            "scanned_message_count": scanned_message_count,
            "matched_occurrence_count": matched_occurrence_count,
            "existing_export_verification": existing_export_verification,
        }
        return cls(
            checkpoint_fingerprint=_current_export_native_selection_checkpoint_fingerprint(
                **values
            ),
            **values,
        )

    def to_private_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": _CURRENT_EXPORT_NATIVE_SELECTION_CHECKPOINT_ARTIFACT_TYPE,
            "checkpoint_fingerprint": self.checkpoint_fingerprint,
            "scope_manifest_id": self.scope_manifest_id,
            "scope_manifest_sha256": self.scope_manifest_sha256,
            "parser_fingerprint": self.parser_fingerprint,
            "parser_source_inventory_id": self.parser_source_inventory_id,
            "selected_message_paths": list(self.selected_message_paths),
            "selected_path_set_fingerprint": self.selected_path_set_fingerprint,
            "scanned_message_count": self.scanned_message_count,
            "matched_occurrence_count": self.matched_occurrence_count,
            "existing_export_verification": self.existing_export_verification.to_private_dict(),
        }

    @classmethod
    def from_private_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "DiagnosticCurrentExportNativeSelectionCheckpoint":
        required = {
            "artifact_type",
            "checkpoint_fingerprint",
            "scope_manifest_id",
            "scope_manifest_sha256",
            "parser_fingerprint",
            "parser_source_inventory_id",
            "selected_message_paths",
            "selected_path_set_fingerprint",
            "scanned_message_count",
            "matched_occurrence_count",
            "existing_export_verification",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != required
            or value.get("artifact_type")
            != _CURRENT_EXPORT_NATIVE_SELECTION_CHECKPOINT_ARTIFACT_TYPE
            or not isinstance(value["selected_message_paths"], list)
            or not isinstance(value["existing_export_verification"], Mapping)
        ):
            raise ContractValidationError(
                "diagnostic current-export selection checkpoint is invalid"
            )
        return cls(
            checkpoint_fingerprint=value["checkpoint_fingerprint"],
            scope_manifest_id=value["scope_manifest_id"],
            scope_manifest_sha256=value["scope_manifest_sha256"],
            parser_fingerprint=value["parser_fingerprint"],
            parser_source_inventory_id=value["parser_source_inventory_id"],
            selected_message_paths=tuple(value["selected_message_paths"]),
            selected_path_set_fingerprint=value["selected_path_set_fingerprint"],
            scanned_message_count=value["scanned_message_count"],
            matched_occurrence_count=value["matched_occurrence_count"],
            existing_export_verification=DiagnosticExistingExportVerification.from_private_dict(
                value["existing_export_verification"]
            ),
        )

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "scope_manifest_id": self.scope_manifest_id,
            "checkpoint_fingerprint": self.checkpoint_fingerprint,
            "parser_fingerprint": self.parser_fingerprint,
            "selected_message_count": len(self.selected_message_paths),
            "scanned_message_count": self.scanned_message_count,
            "matched_occurrence_count": self.matched_occurrence_count,
            "existing_export_verification": self.existing_export_verification.to_safe_dict(),
        }


@dataclass(frozen=True)
class DiagnosticCurrentExportNativeScope:
    """One private full-scope manifest plus its native selected-message checkpoint."""

    manifest: DiagnosticStructuralScopeManifest
    selection_checkpoint: DiagnosticCurrentExportNativeSelectionCheckpoint

    def __post_init__(self) -> None:
        if (
            not isinstance(self.manifest, DiagnosticStructuralScopeManifest)
            or not isinstance(
                self.selection_checkpoint,
                DiagnosticCurrentExportNativeSelectionCheckpoint,
            )
            or self.selection_checkpoint.scope_manifest_id != self.manifest.scope_manifest_id
        ):
            raise ContractValidationError("diagnostic current-export native scope is invalid")

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "status": "written",
            "scope_manifest_id": self.manifest.scope_manifest_id,
            "expected_message_count": self.manifest.expected_message_count,
            "expected_body_segment_count": self.manifest.expected_body_segment_count,
            "selector_count": len(self.manifest.selectors),
            "native_selection_checkpoint": self.selection_checkpoint.to_safe_dict(),
            "claim_boundary": "diagnostic_existing_export_only",
        }


@dataclass(frozen=True)
class _HistoricalScopeCompatibilityCheckpoint:
    """Private historical-scope binding independent of current parser identity.

    The checkpoint is intentionally consumed only by the materializer.  Its
    relative paths and selector assignments are never copied to bridge output,
    aggregate manifests, shard records, or public CLI JSON.
    """

    checkpoint_fingerprint: str
    scope_manifest_id: str
    scope_manifest_sha256: str
    legacy_parser_sha256: str
    selected_path_count: int
    matched_occurrence_count: int
    selector_coverage_fingerprint: str
    selected_paths: tuple[str, ...]
    selector_counts: Mapping[str, int]

    def shard_scope_fragment_fingerprint(self, selected_paths: Sequence[str]) -> str:
        paths = tuple(sorted(selected_paths))
        if not paths or any(path not in self.selected_paths for path in paths):
            raise ContractValidationError(
                "diagnostic historical compatibility shard paths are invalid"
            )
        return sha256_json(
            {
                "historical_compatibility_checkpoint_fingerprint": (self.checkpoint_fingerprint),
                "selected_path_fingerprint": sha256_json(list(paths)),
            }
        )


@dataclass(frozen=True)
class DiagnosticStructuralMaterializationPlan:
    """Safe preflight estimate; it deliberately contains no source paths/text."""

    scope_manifest_id: str
    expected_message_count: int
    expected_body_segment_count: int
    materialization_mode: str
    required_pst_scan_count: int
    required_export_selection_scan_count: int
    parallel_jobs: int
    parser_worker_count: int
    shard_batch_size: int
    shard_count: int
    estimated_peak_memory_bytes: int
    memory_policy_limit_bytes: int
    estimated_export_disk_bytes: int | None
    available_scratch_disk_bytes: int | None
    can_resume_after_readpst: bool

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "status": "planned",
            "scope_manifest_id": self.scope_manifest_id,
            "expected_message_count": self.expected_message_count,
            "expected_body_segment_count": self.expected_body_segment_count,
            "materialization_mode": self.materialization_mode,
            "required_pst_scan_count": self.required_pst_scan_count,
            "required_export_selection_scan_count": self.required_export_selection_scan_count,
            "parallel_jobs": self.parallel_jobs,
            "parser_worker_count": self.parser_worker_count,
            "shard_batch_size": self.shard_batch_size,
            "shard_count": self.shard_count,
            "estimated_peak_memory_bytes": self.estimated_peak_memory_bytes,
            "memory_policy_limit_bytes": self.memory_policy_limit_bytes,
            "estimated_export_disk_bytes": self.estimated_export_disk_bytes,
            "available_scratch_disk_bytes": self.available_scratch_disk_bytes,
            "can_resume_after_readpst": self.can_resume_after_readpst,
        }


@dataclass(frozen=True)
class DiagnosticStructuralMaterializationPublication:
    """Published full-scope bridge plus restart-safe accounting."""

    publication: DiagnosticStructuralBridgePublication | None
    scope_manifest_id: str
    scanned_message_count: int
    selected_export_message_count: int
    pst_scan_count: int
    resumed_readpst_export: bool
    existing_export_verification: "DiagnosticExistingExportVerification | None" = None
    aggregate_manifest_id: str | None = None
    shard_count: int = 1
    aggregate_created: bool = False

    def to_safe_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "published",
            "scope_manifest_id": self.scope_manifest_id,
            "selected_export_message_count": self.selected_export_message_count,
            "scanned_message_count": self.scanned_message_count,
            "pst_scan_count": self.pst_scan_count,
            "resumed_readpst_export": self.resumed_readpst_export,
        }
        if self.aggregate_manifest_id is not None:
            payload.update(
                {
                    "aggregate_manifest_id": self.aggregate_manifest_id,
                    "shard_count": self.shard_count,
                    "created": self.aggregate_created,
                }
            )
        elif self.publication is not None:
            payload.update(
                {
                    "mail_evidence_bundle_id": self.publication.mail_evidence_bundle_id,
                    "structural_observation_count": (self.publication.structural_observation_count),
                    "created": self.publication.created,
                }
            )
        else:
            raise ContractValidationError("diagnostic structural publication is incomplete")
        if self.existing_export_verification is not None:
            payload["existing_export_verification"] = (
                self.existing_export_verification.to_safe_dict()
            )
        return payload


def read_message_path_list(path: str | Path) -> tuple[str, ...]:
    """Read a newline-delimited selected-export path list without scanning it."""

    try:
        content = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractValidationError("diagnostic message path list is unavailable") from exc
    return tuple(
        line
        for raw_line in content.splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    )


def read_message_path_manifest(path: str | Path) -> tuple[str, ...]:
    """Read a JSON manifest containing a path list from one explicit file."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractValidationError("diagnostic message path manifest is invalid") from exc
    if isinstance(payload, Mapping):
        payload = payload.get("message_paths")
    if not isinstance(payload, list) or any(not isinstance(item, str) for item in payload):
        raise ContractValidationError("diagnostic message path manifest is invalid")
    return tuple(payload)


def produce_diagnostic_structural_bridge(
    *,
    export_root: str | Path,
    selected_message_paths: Sequence[str | Path],
    bridge_dir: str | Path,
    source_asset_id: str,
    source_fingerprint: str,
    workspace_id: str,
    owner_user_id: str,
    permission_scope: Mapping[str, Any],
    created_at: str,
    scope_authority_verifier: CoverageScopeAuthorityVerifier | None = None,
    semantic_profile: DiagnosticSemanticProfile | None = None,
    existing_export_verification: DiagnosticExistingExportVerification | None = None,
    historical_compatibility_scope: bool = False,
    extractor_config: Mapping[str, Any] | None = None,
    adapter: PstMailArchiveExtractor | None = None,
) -> DiagnosticStructuralBridgePublication:
    """Persist canonical structural evidence for selected existing export files.

    The caller supplies an explicit bounded set.  No raw PST parser command is
    executed and the producer does not walk or index any unselected export
    files.  The output uses ``FileMailEvidenceBundleStore`` unchanged, so the
    diagnostic MCP can load the normal private canonical bundle persistence
    format read-only.
    """

    normalized_paths = _normalized_selected_paths(
        export_root=export_root,
        selected_message_paths=selected_message_paths,
    )
    if not isinstance(historical_compatibility_scope, bool):
        raise ContractValidationError("diagnostic historical compatibility scope flag is invalid")
    if historical_compatibility_scope and (
        not isinstance(existing_export_verification, DiagnosticExistingExportVerification)
        or existing_export_verification.historical_compatibility_checkpoint_fingerprint is None
    ):
        raise ContractValidationError("diagnostic historical compatibility scope is unbound")
    if not isinstance(permission_scope, Mapping) or not permission_scope:
        raise ContractValidationError("diagnostic structural bridge permission scope is invalid")
    normalized_permission_scope = validate_permission_scope(dict(permission_scope))
    active_adapter = adapter or PstMailArchiveExtractor()
    if not isinstance(active_adapter, PstMailArchiveExtractor):
        raise ContractValidationError("diagnostic structural bridge requires a PST extractor")
    asset = Asset(
        asset_id=source_asset_id,
        storage_backend_id="diagnostic_structural_bridge",
        object_uri="diagnostic://selected-readpst-export",
        content_hash=source_fingerprint,
        file_size=0,
        mime_type=_DEFAULT_PST_MIME_TYPE,
        created_at=created_at,
        registered_at=created_at,
        owner_user_id=owner_user_id,
        workspace_id=workspace_id,
        permission_scope=normalized_permission_scope,
        lifecycle_state="active",
    )
    extraction_input = ExtractionInput(
        asset=asset,
        object_path=Path(export_root),
        extractor_run_id=stable_resource_contract_id(
            "extractor",
            "DiagnosticSelectedReadpstExport",
            {
                "source_asset_id": source_asset_id,
                "source_fingerprint": source_fingerprint,
                "selected_message_paths": normalized_paths,
                "parser_version": active_adapter.version(),
            },
        ),
        config=dict(extractor_config or {}),
        created_at=created_at,
    )
    return _publish_diagnostic_bridge_result(
        result=extract_selected_readpst_export(
            extraction_input=extraction_input,
            export_root=export_root,
            selected_message_paths=normalized_paths,
            adapter=active_adapter,
        ),
        bridge_dir=bridge_dir,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        source_asset_id=source_asset_id,
        source_fingerprint=source_fingerprint,
        parser_name=active_adapter.name(),
        parser_version=active_adapter.version(),
        created_at=created_at,
        scope_authority_verifier=scope_authority_verifier,
        semantic_profile=semantic_profile,
        existing_export_verification=existing_export_verification,
        historical_selected_message_paths=(
            normalized_paths if historical_compatibility_scope else None
        ),
    )


def produce_complete_diagnostic_structural_bridge(
    *,
    export_root: str | Path,
    bridge_dir: str | Path,
    source_asset_id: str,
    source_fingerprint: str,
    workspace_id: str,
    owner_user_id: str,
    permission_scope: Mapping[str, Any],
    created_at: str,
    scope_authority_verifier: CoverageScopeAuthorityVerifier | None = None,
    semantic_profile: DiagnosticSemanticProfile | None = None,
    existing_export_verification: DiagnosticExistingExportVerification | None = None,
    extractor_config: Mapping[str, Any] | None = None,
    adapter: PstMailArchiveExtractor | None = None,
) -> DiagnosticStructuralBridgePublication:
    """Publish one complete existing export after its archive binding is proven."""

    if not isinstance(permission_scope, Mapping) or not permission_scope:
        raise ContractValidationError("diagnostic structural bridge permission scope is invalid")
    normalized_permission_scope = validate_permission_scope(dict(permission_scope))
    active_adapter = adapter or PstMailArchiveExtractor()
    if not isinstance(active_adapter, PstMailArchiveExtractor):
        raise ContractValidationError("diagnostic structural bridge requires a PST extractor")
    asset = Asset(
        asset_id=source_asset_id,
        storage_backend_id="diagnostic_structural_bridge",
        object_uri="diagnostic://complete-readpst-export",
        content_hash=source_fingerprint,
        file_size=0,
        mime_type=_DEFAULT_PST_MIME_TYPE,
        created_at=created_at,
        registered_at=created_at,
        owner_user_id=owner_user_id,
        workspace_id=workspace_id,
        permission_scope=normalized_permission_scope,
        lifecycle_state="active",
    )
    extraction_input = ExtractionInput(
        asset=asset,
        object_path=Path(export_root),
        extractor_run_id=stable_resource_contract_id(
            "extractor",
            "DiagnosticCompleteReadpstExport",
            {
                "source_asset_id": source_asset_id,
                "source_fingerprint": source_fingerprint,
                "parser_version": active_adapter.version(),
            },
        ),
        config=dict(extractor_config or {}),
        created_at=created_at,
    )
    return _publish_diagnostic_bridge_result(
        result=extract_readpst_export(
            extraction_input=extraction_input,
            export_root=export_root,
            adapter=active_adapter,
        ),
        bridge_dir=bridge_dir,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        source_asset_id=source_asset_id,
        source_fingerprint=source_fingerprint,
        parser_name=active_adapter.name(),
        parser_version=active_adapter.version(),
        created_at=created_at,
        scope_authority_verifier=scope_authority_verifier,
        semantic_profile=semantic_profile,
        existing_export_verification=existing_export_verification,
    )


def _publish_diagnostic_bridge_result(
    *,
    result: Any,
    bridge_dir: str | Path,
    workspace_id: str,
    owner_user_id: str,
    source_asset_id: str,
    source_fingerprint: str,
    parser_name: str,
    parser_version: str,
    created_at: str,
    scope_authority_verifier: CoverageScopeAuthorityVerifier | None,
    semantic_profile: DiagnosticSemanticProfile | None,
    existing_export_verification: DiagnosticExistingExportVerification | None,
    historical_selected_message_paths: Sequence[str] | None = None,
) -> DiagnosticStructuralBridgePublication:
    """Convert one typed PST result into the canonical persisted bundle."""

    if result.errors:
        raise RuntimeError("diagnostic structural bridge extraction failed")
    if result.source_inventory is None:
        raise RuntimeError("diagnostic structural bridge inventory is unavailable")
    _validate_optional_semantic_binding_inputs(
        scope_authority_verifier=scope_authority_verifier,
        semantic_profile=semantic_profile,
        existing_export_verification=existing_export_verification,
    )
    source_inventory = result.source_inventory
    structural_observations = tuple(result.structural_observations)
    if historical_selected_message_paths is not None:
        if (
            not isinstance(
                existing_export_verification,
                DiagnosticExistingExportVerification,
            )
            or existing_export_verification.historical_compatibility_checkpoint_fingerprint is None
        ):
            raise ContractValidationError("diagnostic historical compatibility scope is unbound")
        selected_top_level_lineage_ids = _selected_top_level_message_lineage_ids(
            source_inventory,
            selected_paths=historical_selected_message_paths,
        )
        structural_observations = tuple(
            observation
            for observation in structural_observations
            if observation.message_lineage_id in selected_top_level_lineage_ids
        )
    parse_warnings = tuple(result.warnings)
    selected_message_count = sum(
        item.structure_kind == "exported_message_occurrence" for item in source_inventory.items
    )
    evidence_observations = [
        observation
        for observation in result.observations
        if observation.observation_type
        not in {
            PST_SOURCE_UNIT_OBSERVATION_TYPE,
            PST_INVENTORY_CARRIER_OBSERVATION_TYPE,
        }
    ]
    # The extraction result also owns one source-unit observation per inventory
    # item and one private carrier containing complete serialized inventory and
    # structural graphs.  Neither family enters the canonical mail bundle.
    # Consume the result before constructing another full persistence graph so
    # those redundant private payloads cannot overlap bundle validation.
    result.observations.clear()
    del result
    bundle = build_mail_evidence_bundle(
        evidence_observations,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        source_asset_id=source_asset_id,
        archive_sha256=source_fingerprint,
        producer_type=DIAGNOSTIC_STRUCTURAL_BRIDGE_PRODUCER_TYPE,
        parser_name=parser_name,
        parser_version=parser_version,
        retention_policy="retain_indefinitely",
        raw_archive_retention_decision="retained_by_policy",
        created_at=created_at,
        started_at=created_at,
        completed_at=created_at,
        parse_warnings=parse_warnings,
    )
    del evidence_observations
    claim_requirements: tuple[ClaimRequirement, ...] = ()
    coverage_ledgers: tuple[CoverageLedger, ...] = ()
    version_manifests: tuple[VersionManifest, ...] = ()
    expected_scope_authorities: dict[str, CoverageScopeAuthority] = {}
    bundle_updates: dict[str, Any] = {
        "source_inventory": [source_inventory],
        "structural_observations": list(structural_observations),
    }
    if semantic_profile is not None:
        (
            claim_requirements,
            coverage_ledgers,
            version_manifests,
            expected_scope_authorities,
        ) = _build_structural_semantic_bindings(
            source_inventory=source_inventory,
            structural_observations=structural_observations,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            source_asset_id=source_asset_id,
            source_fingerprint=source_fingerprint,
            parser_name=parser_name,
            parser_version=parser_version,
            created_at=created_at,
            scope_authority_verifier=scope_authority_verifier,
            semantic_profile=semantic_profile,
            existing_export_verification=existing_export_verification,
        )
        bundle_updates.update(
            {
                "claim_requirements": list(claim_requirements),
                "coverage_ledgers": list(coverage_ledgers),
                "version_manifests": list(version_manifests),
                "_expected_scope_authorities": expected_scope_authorities,
            }
        )
    publication_bundle = replace(bundle, **bundle_updates)
    expected_bundle_id = publication_bundle.mail_evidence_bundle_id
    structural_observation_count = len(publication_bundle.structural_observations)
    publication_owner = [publication_bundle]
    del (
        bundle,
        bundle_updates,
        publication_bundle,
        source_inventory,
        structural_observations,
        claim_requirements,
        coverage_ledgers,
        version_manifests,
        expected_scope_authorities,
    )
    store = FileMailEvidenceBundleStore(bridge_dir)
    publication = store.publish_verified_bundle(
        publication_owner.pop(),
        verify=lambda restored: _verify_bridge_bundle(
            restored,
            expected_bundle_id=expected_bundle_id,
            scope_authority_verifier=scope_authority_verifier,
            existing_export_verification=existing_export_verification,
            semantic_profile=semantic_profile,
        ),
    )
    return DiagnosticStructuralBridgePublication(
        mail_evidence_bundle_id=expected_bundle_id,
        bundle_path=store.root / f"{expected_bundle_id}.json",
        selected_message_count=selected_message_count,
        structural_observation_count=structural_observation_count,
        created=publication.created,
    )


def _validate_optional_semantic_binding_inputs(
    *,
    scope_authority_verifier: CoverageScopeAuthorityVerifier | None,
    semantic_profile: DiagnosticSemanticProfile | None,
    existing_export_verification: DiagnosticExistingExportVerification | None = None,
) -> None:
    """Require the private root when semantic contracts are requested."""

    if semantic_profile is not None and scope_authority_verifier is None:
        raise ContractValidationError(
            "diagnostic structural semantic profile requires an authority root"
        )
    if scope_authority_verifier is not None and not isinstance(
        scope_authority_verifier,
        CoverageScopeAuthorityVerifier,
    ):
        raise ContractValidationError("diagnostic structural bridge authority verifier is invalid")
    if semantic_profile is not None and not isinstance(semantic_profile, DiagnosticSemanticProfile):
        raise ContractValidationError("diagnostic structural semantic scope profile is invalid")
    if existing_export_verification is not None and not isinstance(
        existing_export_verification,
        DiagnosticExistingExportVerification,
    ):
        raise ContractValidationError("diagnostic structural export verification is invalid")
    if existing_export_verification is not None and semantic_profile is None:
        raise ContractValidationError(
            "diagnostic structural export verification requires semantic authority"
        )


def _normalized_selected_paths(
    *,
    export_root: str | Path,
    selected_message_paths: Sequence[str | Path],
) -> tuple[str, ...]:
    """Normalize only caller-supplied paths for deterministic producer identity."""

    root = Path(os.path.abspath(os.fspath(export_root)))
    normalized: set[str] = set()
    for raw_path in selected_message_paths:
        if not isinstance(raw_path, (str, Path)):
            raise ContractValidationError("diagnostic selected message path is invalid")
        candidate_input = Path(raw_path)
        candidate = Path(
            os.path.abspath(
                os.fspath(
                    candidate_input if candidate_input.is_absolute() else root / candidate_input
                )
            )
        )
        try:
            normalized.add(candidate.relative_to(root).as_posix())
        except ValueError as exc:
            raise ContractValidationError(
                "diagnostic selected message path escapes export root"
            ) from exc
    if not normalized:
        raise ContractValidationError("diagnostic structural bridge requires selected messages")
    return tuple(sorted(normalized))


def _verify_bridge_bundle(
    bundle: MailEvidenceBundle,
    *,
    expected_bundle_id: str,
    scope_authority_verifier: CoverageScopeAuthorityVerifier | None,
    existing_export_verification: DiagnosticExistingExportVerification | None = None,
    semantic_profile: DiagnosticSemanticProfile | None = None,
) -> dict[str, Any]:
    """Minimal local persistence verification; no query or raw data projection."""

    if bundle.mail_evidence_bundle_id != expected_bundle_id:
        raise ContractValidationError("diagnostic structural bridge bundle identity changed")
    if not bundle.source_inventory:
        raise ContractValidationError("diagnostic structural bridge bundle is incomplete")
    if bundle.claim_requirements or bundle.coverage_ledgers or bundle.version_manifests:
        if not isinstance(scope_authority_verifier, CoverageScopeAuthorityVerifier):
            raise ContractValidationError(
                "diagnostic structural bridge authority verifier is unavailable"
            )
        _revalidate_complete_structural_claim_bindings(
            bundle,
            scope_authority_verifier=scope_authority_verifier,
            existing_export_verification=existing_export_verification,
            semantic_profile=semantic_profile,
        )
    elif existing_export_verification is not None:
        raise ContractValidationError("diagnostic structural bridge export authority is incomplete")
    return {
        "status": "verified",
        "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
        "structural_observation_count": len(bundle.structural_observations),
        "claim_requirement_count": len(bundle.claim_requirements),
    }


def _build_structural_semantic_bindings(
    *,
    source_inventory: SourceInventory,
    structural_observations: Sequence[StructuralObservation],
    workspace_id: str,
    owner_user_id: str,
    source_asset_id: str,
    source_fingerprint: str,
    parser_name: str,
    parser_version: str,
    created_at: str,
    scope_authority_verifier: CoverageScopeAuthorityVerifier,
    semantic_profile: DiagnosticSemanticProfile,
    existing_export_verification: DiagnosticExistingExportVerification | None,
) -> tuple[
    tuple[ClaimRequirement, ...],
    tuple[CoverageLedger, ...],
    tuple[VersionManifest, ...],
    dict[str, CoverageScopeAuthority],
]:
    """Persist one complete predicate-neutral structural baseline.

    ``CoverageScopeAuthority`` carries one decision per inventory item.  The
    bridge therefore emits exactly one authority and one ledger for the whole
    inventory instead of multiplying those decisions by profile predicates or
    observed headers.  Predicate-specific requirements are derived only in
    ``diagnostic_mcp`` after permission-first semantic grounding.
    """

    if not isinstance(source_inventory, SourceInventory):
        raise ContractValidationError("diagnostic structural source inventory is invalid")
    if not isinstance(scope_authority_verifier, CoverageScopeAuthorityVerifier):
        raise ContractValidationError("diagnostic structural bridge authority verifier is invalid")
    if not isinstance(semantic_profile, DiagnosticSemanticProfile):
        raise ContractValidationError("diagnostic structural semantic scope profile is invalid")
    if existing_export_verification is not None and not isinstance(
        existing_export_verification,
        DiagnosticExistingExportVerification,
    ):
        raise ContractValidationError("diagnostic structural export verification is invalid")
    if source_inventory.source_asset_id != source_asset_id:
        raise ContractValidationError("diagnostic structural inventory asset is invalid")
    if source_inventory.source_fingerprint != source_fingerprint:
        raise ContractValidationError("diagnostic structural inventory source is invalid")
    if (
        semantic_profile.workspace_id != workspace_id
        or semantic_profile.owner_user_id != owner_user_id
    ):
        raise ContractValidationError("diagnostic structural semantic scope is out of context")

    observations = tuple(
        sorted(
            (
                observation
                for observation in structural_observations
                if isinstance(observation, StructuralObservation)
            ),
            key=lambda observation: (
                observation.source_inventory_item_id,
                observation.source_observation_id,
                observation.structural_observation_id,
            ),
        )
    )
    if len(observations) != len(structural_observations):
        raise ContractValidationError("diagnostic structural observations are invalid")
    items_by_id = {item.source_inventory_item_id: item for item in source_inventory.items}
    if not items_by_id:
        raise ContractValidationError("diagnostic structural inventory items are unavailable")

    structural_observation_ids_by_item: dict[str, set[str]] = {}
    for observation in observations:
        item = items_by_id.get(observation.source_inventory_item_id)
        if item is None or observation.source_observation_id not in item.source_observation_ids:
            raise ContractValidationError(
                "diagnostic structural observation is outside the source inventory"
            )
        structural_observation_ids_by_item.setdefault(item.source_inventory_item_id, set()).add(
            observation.source_observation_id
        )

    version_manifest = VersionManifest.create(
        source_fingerprint=source_inventory.source_fingerprint,
        parser_fingerprint=source_inventory.parser_fingerprint,
        tokenizer_fingerprint=sha256_json(
            {
                "kind": "structural_topology",
                "materializer": "diagnostic_structural_bridge_v1",
            }
        ),
        index_fingerprint=sha256_json(
            {
                "source_inventory": source_inventory.to_persistence_dict(),
                "structural_observations": [
                    observation.to_persistence_dict() for observation in observations
                ],
            }
        ),
        implementation_fingerprint=(
            diagnostic_structural_implementation_fingerprint(
                producer_type=DIAGNOSTIC_STRUCTURAL_BRIDGE_PRODUCER_TYPE,
                parser_name=parser_name,
                parser_version=parser_version,
                semantic_profile_fingerprint=semantic_profile.profile_fingerprint,
                verification=existing_export_verification,
            )
            if existing_export_verification is not None
            else sha256_json(
                {
                    "producer_type": DIAGNOSTIC_STRUCTURAL_BRIDGE_PRODUCER_TYPE,
                    "parser_name": parser_name,
                    "parser_version": parser_version,
                    "semantic_profile_fingerprint": semantic_profile.profile_fingerprint,
                    "semantic_materialization": (DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND),
                }
            )
        ),
        parser_version=parser_version,
        tokenizer_version="structural_topology_v1",
        index_version="structural_baseline_v1",
        implementation_version=(
            DIAGNOSTIC_STRUCTURAL_BRIDGE_IMPLEMENTATION_VERSION
            if existing_export_verification is not None
            else "diagnostic_structural_bridge_v1"
        ),
        created_at=created_at,
    )
    authorization = CoverageAuthorizationBinding(
        actor_context_id=semantic_profile.actor_context_id,
        permission_revision=sha256_json(
            {
                "workspace_id": workspace_id,
                "owner_user_id": owner_user_id,
                "source_asset_id": source_asset_id,
                "permission_scopes": [
                    dict(item.permission_scope) for item in source_inventory.items
                ],
            }
        ),
        grant_revision=sha256_json(
            {
                "source_fingerprint": source_fingerprint,
                "source_inventory_id": source_inventory.source_inventory_id,
                "permission_scopes": [
                    dict(item.permission_scope) for item in source_inventory.items
                ],
            }
        ),
    )
    scope_policy = CoverageScopePolicyBinding.create(
        scope_policy_id=DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID,
        scope_policy_version=(
            DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_VERSION
            if existing_export_verification is not None
            else "1"
        ),
        scope_policy_fingerprint=(
            diagnostic_structural_scope_policy_fingerprint(existing_export_verification)
            if existing_export_verification is not None
            else sha256_json(
                {
                    "scope_policy_id": DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID,
                    "scope_policy_version": "1",
                    "mode": "complete_authorized_structural_baseline",
                }
            )
        ),
    )
    authorizations = tuple(
        CoverageItemAuthorizationDecision.create(
            source_inventory_item=item,
            authorization_binding=authorization,
            decision_state="authorized",
        )
        for item in source_inventory.items
    )
    # Every parsed source unit is relevant to an all-matching structural scan:
    # units with no table provide ordinary proof that no structured row was
    # omitted. Restricting the baseline to table-bearing units would make a
    # definitive no-match impossible and would not prove complete scope.
    required_scope = tuple(
        sorted(
            item_id for item_id, item in items_by_id.items() if item.processing_state == "parsed"
        )
    )
    if not required_scope:
        raise ContractValidationError("diagnostic structural parsed source scope is unavailable")
    required_scope_set = set(required_scope)
    requirement = ClaimRequirement.create(
        query_id=stable_resource_contract_id(
            "query",
            "DiagnosticCompactBaseline",
            (
                {
                    "source_inventory_id": source_inventory.source_inventory_id,
                    "existing_export_verification_fingerprint": (
                        existing_export_verification.verification_fingerprint
                    ),
                }
                if existing_export_verification is not None
                else {"source_inventory_id": source_inventory.source_inventory_id}
            ),
        ),
        kind="all_matching",
        target="structural_row",
        predicate="structural_scope",
        parameters=(
            diagnostic_structural_baseline_parameters(existing_export_verification)
            if existing_export_verification is not None
            else {"scope_kind": DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND}
        ),
        required_scope=required_scope,
        created_at=created_at,
    )
    relevance = tuple(
        CoverageItemRelevanceDecision.create(
            source_inventory_item=item,
            claim_requirement=requirement,
            scope_policy=scope_policy,
            decision_state=(
                "relevant" if item.source_inventory_item_id in required_scope_set else "irrelevant"
            ),
        )
        for item in source_inventory.items
    )
    authority = CoverageScopeAuthority.create(
        source_inventory=source_inventory,
        claim_requirement=requirement,
        authorization_binding=authorization,
        version_manifest=version_manifest,
        scope_policy=scope_policy,
        authorization_decisions=authorizations,
        relevance_decisions=relevance,
        authority_verifier=scope_authority_verifier,
    )
    partitions = tuple(
        CoverageObservationPartition(
            inventory_item_id=item_id,
            structural_observation_ids=tuple(
                sorted(structural_observation_ids_by_item.get(item_id, ()))
            ),
            ordinary_observation_ids=tuple(
                sorted(
                    set(items_by_id[item_id].source_observation_ids)
                    - structural_observation_ids_by_item.get(item_id, set())
                )
            ),
        )
        for item_id in required_scope
    )
    scope_partition = CoverageScopePartition.create(
        scope_authority=authority,
        observation_partitions=partitions,
    )
    proofs = tuple(
        CoverageProofRecord.create(
            source_inventory_id=source_inventory.source_inventory_id,
            claim_requirement_id=requirement.claim_requirement_id,
            version_manifest_id=version_manifest.version_manifest_id,
            inventory_item_id=partition.inventory_item_id,
            proof_kind=(
                "combined"
                if partition.structural_observation_ids and partition.ordinary_observation_ids
                else "structural"
                if partition.structural_observation_ids
                else "ordinary"
            ),
            structural_observation_ids=partition.structural_observation_ids,
            ordinary_observation_ids=partition.ordinary_observation_ids,
        )
        for partition in partitions
    )
    ledger = CoverageLedger.create(
        query_id=requirement.query_id,
        claim_requirement_id=requirement.claim_requirement_id,
        source_inventory_id=source_inventory.source_inventory_id,
        relevant_inventory_item_ids=required_scope,
        searched_structural_observation_ids=tuple(
            observation_id
            for partition in partitions
            for observation_id in partition.structural_observation_ids
        ),
        searched_ordinary_observation_ids=tuple(
            observation_id
            for partition in partitions
            for observation_id in partition.ordinary_observation_ids
        ),
        authorization_binding=authorization,
        version_binding=CoverageVersionBinding.from_manifest(version_manifest),
        scope_partition=scope_partition,
        proof_records=proofs,
        complete_authorized_scope=True,
        display_pagination=DisplayPagination(page_size=1),
    )
    return (
        (requirement,),
        (ledger,),
        (version_manifest,),
        {f"{requirement.claim_requirement_id}:{source_inventory.source_inventory_id}": authority},
    )


def _revalidate_complete_structural_claim_bindings(
    bundle: MailEvidenceBundle,
    *,
    scope_authority_verifier: CoverageScopeAuthorityVerifier,
    existing_export_verification: DiagnosticExistingExportVerification | None = None,
    semantic_profile: DiagnosticSemanticProfile | None = None,
) -> None:
    """Require one persisted baseline scope to validate under one root."""

    if not isinstance(scope_authority_verifier, CoverageScopeAuthorityVerifier):
        raise ContractValidationError("diagnostic structural bridge authority verifier is invalid")
    if existing_export_verification is not None and (
        not isinstance(
            existing_export_verification,
            DiagnosticExistingExportVerification,
        )
        or not isinstance(semantic_profile, DiagnosticSemanticProfile)
    ):
        raise ContractValidationError("diagnostic structural bridge export authority is invalid")
    inventories = {
        inventory.source_inventory_id: inventory for inventory in bundle.source_inventory
    }
    requirements = {
        requirement.claim_requirement_id: requirement for requirement in bundle.claim_requirements
    }
    manifests = {manifest.version_manifest_id: manifest for manifest in bundle.version_manifests}
    if (
        len(bundle.source_inventory) != 1
        or len(bundle.claim_requirements) != 1
        or len(bundle.coverage_ledgers) != 1
        or len(bundle.version_manifests) != 1
    ):
        raise ContractValidationError("diagnostic structural bridge claim coverage is incomplete")
    ledger = bundle.coverage_ledgers[0]
    requirement = requirements.get(ledger.claim_requirement_id)
    inventory = inventories.get(ledger.source_inventory_id)
    manifest = (
        manifests.get(ledger.version_binding.version_manifest_id)
        if ledger.version_binding is not None
        else None
    )
    authority = (
        ledger.scope_partition.scope_authority if ledger.scope_partition is not None else None
    )
    if not all(
        isinstance(value, expected_type)
        for value, expected_type in (
            (requirement, ClaimRequirement),
            (inventory, SourceInventory),
            (manifest, VersionManifest),
            (authority, CoverageScopeAuthority),
        )
    ):
        raise ContractValidationError("diagnostic structural bridge binding is incomplete")
    expected_query_identity: dict[str, Any] = {"source_inventory_id": inventory.source_inventory_id}
    expected_parameters: dict[str, Any] = {"scope_kind": DIAGNOSTIC_STRUCTURAL_BASELINE_SCOPE_KIND}
    if existing_export_verification is not None:
        expected_query_identity["existing_export_verification_fingerprint"] = (
            existing_export_verification.verification_fingerprint
        )
        expected_parameters = diagnostic_structural_baseline_parameters(
            existing_export_verification
        )
    if (
        requirement.query_id
        != stable_resource_contract_id(
            "query",
            "DiagnosticCompactBaseline",
            expected_query_identity,
        )
        or requirement.kind != "all_matching"
        or requirement.target != "structural_row"
        or requirement.predicate != "structural_scope"
        or dict(requirement.parameters) != expected_parameters
        or set(requirement.required_scope)
        != {
            item.source_inventory_item_id
            for item in inventory.items
            if item.processing_state == "parsed"
        }
    ):
        raise ContractValidationError("diagnostic structural bridge baseline is invalid")
    inventory_item_ids = {item.source_inventory_item_id for item in inventory.items}
    parsed_inventory_item_ids = {
        item.source_inventory_item_id
        for item in inventory.items
        if item.processing_state == "parsed"
    }
    authorization_by_item = {
        decision.inventory_item_id: decision for decision in authority.authorization_decisions
    }
    relevance_by_item = {
        decision.inventory_item_id: decision for decision in authority.relevance_decisions
    }
    trusted_authority = scope_authority_verifier.revalidate(authority)
    expected_scope_policy_fingerprint = (
        diagnostic_structural_scope_policy_fingerprint(existing_export_verification)
        if existing_export_verification is not None
        else sha256_json(
            {
                "scope_policy_id": DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID,
                "scope_policy_version": "1",
                "mode": "complete_authorized_structural_baseline",
            }
        )
    )
    expected_scope_policy_version = (
        DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_VERSION
        if existing_export_verification is not None
        else "1"
    )
    expected_implementation_fingerprint = (
        diagnostic_structural_implementation_fingerprint(
            producer_type=DIAGNOSTIC_STRUCTURAL_BRIDGE_PRODUCER_TYPE,
            parser_name=bundle.mail_parse_run.parser_name,
            parser_version=bundle.mail_parse_run.parser_version,
            semantic_profile_fingerprint=semantic_profile.profile_fingerprint,
            verification=existing_export_verification,
        )
        if existing_export_verification is not None
        else manifest.implementation_fingerprint
    )
    if (
        authority.scope_policy.scope_policy_id != DIAGNOSTIC_STRUCTURAL_SCOPE_POLICY_ID
        or authority.scope_policy.scope_policy_version != expected_scope_policy_version
        or authority.scope_policy.scope_policy_fingerprint != expected_scope_policy_fingerprint
        or manifest.implementation_fingerprint != expected_implementation_fingerprint
        or (
            existing_export_verification is not None
            and manifest.implementation_version
            != DIAGNOSTIC_STRUCTURAL_BRIDGE_IMPLEMENTATION_VERSION
        )
        or set(ledger.relevant_inventory_item_ids) != parsed_inventory_item_ids
        or set(trusted_authority.authorized_relevant_item_ids) != parsed_inventory_item_ids
        or set(authorization_by_item) != inventory_item_ids
        or any(
            decision.decision_state != "authorized" for decision in authorization_by_item.values()
        )
        or set(relevance_by_item) != inventory_item_ids
        or {
            item_id
            for item_id, decision in relevance_by_item.items()
            if decision.decision_state == "relevant"
        }
        != parsed_inventory_item_ids
        or {
            item_id
            for item_id, decision in relevance_by_item.items()
            if decision.decision_state == "irrelevant"
        }
        != inventory_item_ids - parsed_inventory_item_ids
        or not ledger.usable_for_claim(
            inventory,
            requirement,
            manifest,
            ledger.authorization_binding,
            trusted_authority,
        )
    ):
        raise ContractValidationError("diagnostic structural bridge coverage binding is invalid")
    if (
        existing_export_verification is not None
        and existing_export_verification.historical_compatibility_checkpoint_fingerprint is not None
    ):
        selected_top_level_lineage_ids = _top_level_exported_message_lineage_ids(inventory)
        if not selected_top_level_lineage_ids or any(
            observation.message_lineage_id not in selected_top_level_lineage_ids
            for observation in bundle.structural_observations
        ):
            raise ContractValidationError(
                "diagnostic historical compatibility structural scope is invalid"
            )


def build_diagnostic_structural_scope_manifest(
    preserved_work_dir: str | Path,
) -> DiagnosticStructuralScopeManifest:
    """Build a complete historical MAY scope from persisted message records.

    The prior MAY corpus has message/body observations but no table topology.
    This function uses it only as an immutable selector manifest; it never
    treats body-text co-occurrence as structured evidence.
    """

    data_dir = Path(preserved_work_dir) / "data"
    assets = AssetStore(data_dir).list()
    upload_sessions = UploadSessionStore(data_dir).list()
    observations = ObservationStore(data_dir).list()
    message_records = [
        observation
        for observation in observations
        if observation.modality == "mail" and observation.observation_type == "email_message"
    ]
    if not message_records:
        raise ContractValidationError("diagnostic scope has no persisted mail messages")
    source_asset_ids = {record.asset_id for record in message_records}
    if len(source_asset_ids) != 1:
        raise ContractValidationError("diagnostic scope has multiple source assets")
    source_asset_id = next(iter(source_asset_ids))
    asset_by_id = {asset.asset_id: asset for asset in assets}
    asset = asset_by_id.get(source_asset_id)
    if asset is None:
        raise ContractValidationError("diagnostic scope source asset is unavailable")
    sessions = [
        session
        for session in upload_sessions
        if session.asset_id == source_asset_id and session.workspace_id == asset.workspace_id
    ]
    if len(sessions) != 1:
        raise ContractValidationError("diagnostic scope upload session binding is invalid")

    counts_by_key: dict[tuple[str, str, str], int] = {}
    message_occurrence_ids: set[str] = set()
    source_observation_ids: list[str] = []
    for record in message_records:
        location = dict(record.location)
        payload = dict(record.payload or {})
        occurrence_id = _required_private_text_from_sources(
            location,
            payload,
            "message_occurrence_id",
        )
        if occurrence_id in message_occurrence_ids:
            raise ContractValidationError("diagnostic scope message occurrences are not unique")
        message_occurrence_ids.add(occurrence_id)
        selector_key = (
            _required_private_text_from_sources(location, payload, "message_id"),
            _required_private_text(location, "folder_path_hash"),
            _required_private_text(payload, "body_hash"),
        )
        counts_by_key[selector_key] = counts_by_key.get(selector_key, 0) + 1
        source_observation_ids.append(record.observation_id)

    body_records = [
        observation
        for observation in observations
        if (
            observation.asset_id == source_asset_id
            and observation.modality == "mail"
            and observation.observation_type == "email_body_segment"
        )
    ]
    for record in body_records:
        location = dict(record.location)
        payload = dict(record.payload or {})
        occurrence_id = _required_private_text_from_sources(
            location,
            payload,
            "message_occurrence_id",
        )
        if occurrence_id not in message_occurrence_ids:
            raise ContractValidationError("diagnostic scope body segment is not bound to a message")
        source_observation_ids.append(record.observation_id)

    selectors = tuple(
        DiagnosticStructuralScopeSelector(
            selector_id=sha256_json(
                {
                    "message_id": message_id,
                    "folder_path_hash": folder_path_hash,
                    "body_hash": body_hash,
                }
            ),
            message_id=message_id,
            folder_path_hash=folder_path_hash,
            body_hash=body_hash,
            expected_occurrence_count=count,
        )
        for (message_id, folder_path_hash, body_hash), count in counts_by_key.items()
    )
    source_observation_set_fingerprint = sha256_json(sorted(source_observation_ids))
    scope_manifest_id = _scope_manifest_id(
        source_asset_id=asset.asset_id,
        source_fingerprint=asset.content_hash,
        workspace_id=asset.workspace_id,
        owner_user_id=asset.owner_user_id,
        permission_scope=asset.permission_scope,
        expected_message_count=len(message_records),
        expected_body_segment_count=len(body_records),
        source_observation_set_fingerprint=source_observation_set_fingerprint,
        selectors=selectors,
    )
    return DiagnosticStructuralScopeManifest(
        scope_manifest_id=scope_manifest_id,
        source_asset_id=asset.asset_id,
        source_fingerprint=asset.content_hash,
        workspace_id=asset.workspace_id,
        owner_user_id=asset.owner_user_id,
        permission_scope=asset.permission_scope,
        expected_message_count=len(message_records),
        expected_body_segment_count=len(body_records),
        source_observation_set_fingerprint=source_observation_set_fingerprint,
        selectors=selectors,
    )


def write_diagnostic_structural_scope_manifest(
    manifest: DiagnosticStructuralScopeManifest,
    path: str | Path,
) -> None:
    """Atomically write a private scope manifest; paths/text never enter it."""

    if not isinstance(manifest, DiagnosticStructuralScopeManifest):
        raise ContractValidationError("diagnostic scope manifest is invalid")
    _atomic_private_json(Path(path), manifest.to_private_dict())


def load_diagnostic_structural_scope_manifest(
    path: str | Path,
) -> DiagnosticStructuralScopeManifest:
    try:
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise OSError("unsafe scope manifest")
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractValidationError("diagnostic scope manifest is unavailable") from exc
    return DiagnosticStructuralScopeManifest.from_private_dict(payload)


def build_diagnostic_current_export_native_scope(
    *,
    export_root: str | Path,
    source_asset_id: str,
    source_fingerprint: str,
    workspace_id: str,
    owner_user_id: str,
    permission_scope: Mapping[str, Any],
    created_at: str,
    parser_worker_count: int = 1,
    max_message_file_bytes: int = 25 * 1024 * 1024,
) -> DiagnosticCurrentExportNativeScope:
    """Parse one existing export into a complete current-parser private scope.

    This diagnostic-only constructor never invokes ``readpst`` or reaches a
    raw PST.  It uses the current parser over the already-preserved export,
    rejects parser/identity/coverage failures, and keeps every relative path in
    a private checkpoint rather than a public CLI response or MCP result.
    """

    parser_fingerprint = _diagnostic_current_parser_fingerprint(
        parser_worker_count=parser_worker_count,
        max_message_file_bytes=max_message_file_bytes,
    )
    asset = Asset(
        asset_id=source_asset_id,
        storage_backend_id="diagnostic_existing_export",
        object_uri="diagnostic://current-export-native-scope",
        content_hash=source_fingerprint,
        file_size=0,
        mime_type=_DEFAULT_PST_MIME_TYPE,
        created_at=created_at,
        registered_at=created_at,
        owner_user_id=owner_user_id,
        workspace_id=workspace_id,
        permission_scope=dict(permission_scope),
        lifecycle_state="active",
    )
    root = _safe_existing_export_root(Path(export_root))
    result = extract_readpst_export(
        extraction_input=ExtractionInput(
            asset=asset,
            object_path=root,
            extractor_run_id=stable_resource_contract_id(
                "extractorrun",
                "DiagnosticCurrentExportNativeScope",
                {
                    "source_asset_id": asset.asset_id,
                    "source_fingerprint": asset.content_hash,
                    "parser_fingerprint": parser_fingerprint,
                },
            ),
            config={
                "parser_workers": parser_worker_count,
                "max_message_file_bytes": max_message_file_bytes,
            },
            created_at=created_at,
        ),
        export_root=root,
    )
    if result.errors:
        raise ContractValidationError("diagnostic current-export parser reported errors")
    inventory = result.source_inventory
    if (
        inventory is None
        or inventory.source_asset_id != asset.asset_id
        or inventory.source_fingerprint != asset.content_hash
        or inventory.parser_fingerprint != parser_fingerprint
        or not inventory.items
        or any(
            item.intentional_exclusion_proof is not None
            or item.processing_state in {"failed", "unknown"}
            for item in inventory.items
        )
    ):
        raise ContractValidationError("diagnostic current-export parser inventory is invalid")

    selected_paths = _current_export_message_paths(root)
    top_level_occurrence_ids = _selected_top_level_message_occurrence_ids_from_inventory(
        inventory,
        selected_paths=selected_paths,
    )
    message_records = [
        observation
        for observation in result.observations
        if (
            observation.asset_id == asset.asset_id
            and observation.modality == "mail"
            and observation.observation_type == "email_message"
        )
    ]
    body_records = [
        observation
        for observation in result.observations
        if (
            observation.asset_id == asset.asset_id
            and observation.modality == "mail"
            and observation.observation_type == "email_body_segment"
        )
    ]
    if not message_records or len(message_records) != len(selected_paths):
        raise ContractValidationError("diagnostic current-export message coverage is incomplete")

    counts_by_key: dict[tuple[str, str, str], int] = {}
    message_occurrence_ids: set[str] = set()
    source_observation_ids: set[str] = set()
    for record in message_records:
        location = dict(record.location)
        payload = dict(record.payload or {})
        occurrence_id = _required_private_text_from_sources(
            location,
            payload,
            "message_occurrence_id",
        )
        if occurrence_id in message_occurrence_ids:
            raise ContractValidationError(
                "diagnostic current-export message identities are duplicated"
            )
        message_occurrence_ids.add(occurrence_id)
        if record.observation_id in source_observation_ids:
            raise ContractValidationError("diagnostic current-export observations are duplicated")
        source_observation_ids.add(record.observation_id)
        key = (
            _required_private_text_from_sources(location, payload, "message_id"),
            _required_private_text(location, "folder_path_hash"),
            _required_private_text(payload, "body_hash"),
        )
        counts_by_key[key] = counts_by_key.get(key, 0) + 1
    if message_occurrence_ids != top_level_occurrence_ids:
        raise ContractValidationError(
            "diagnostic current-export embedded message topology is unsupported"
        )

    for record in body_records:
        location = dict(record.location)
        payload = dict(record.payload or {})
        occurrence_id = _required_private_text_from_sources(
            location,
            payload,
            "message_occurrence_id",
        )
        if occurrence_id not in message_occurrence_ids:
            raise ContractValidationError(
                "diagnostic current-export body segment is not bound to a message"
            )
        if record.observation_id in source_observation_ids:
            raise ContractValidationError("diagnostic current-export observations are duplicated")
        source_observation_ids.add(record.observation_id)

    selectors = tuple(
        DiagnosticStructuralScopeSelector(
            selector_id=sha256_json(
                {
                    "message_id": message_id,
                    "folder_path_hash": folder_path_hash,
                    "body_hash": body_hash,
                }
            ),
            message_id=message_id,
            folder_path_hash=folder_path_hash,
            body_hash=body_hash,
            expected_occurrence_count=count,
        )
        for (message_id, folder_path_hash, body_hash), count in counts_by_key.items()
    )
    values = {
        "source_asset_id": asset.asset_id,
        "source_fingerprint": asset.content_hash,
        "workspace_id": asset.workspace_id,
        "owner_user_id": asset.owner_user_id,
        "permission_scope": asset.permission_scope,
        "expected_message_count": len(message_records),
        "expected_body_segment_count": len(body_records),
        "source_observation_set_fingerprint": sha256_json(sorted(source_observation_ids)),
        "selectors": selectors,
    }
    manifest = DiagnosticStructuralScopeManifest(
        scope_manifest_id=_scope_manifest_id(**values),
        **values,
    )
    verification = _verify_operator_bound_existing_export(
        export_root=root,
        selected_message_paths=selected_paths,
        scanned_message_count=len(selected_paths),
        matched_occurrence_count=len(message_records),
        manifest=manifest,
        full_scope_source_asset_id=manifest.source_asset_id,
        full_scope_source_fingerprint=manifest.source_fingerprint,
    )
    return DiagnosticCurrentExportNativeScope(
        manifest=manifest,
        selection_checkpoint=DiagnosticCurrentExportNativeSelectionCheckpoint.create(
            scope_manifest=manifest,
            parser_fingerprint=parser_fingerprint,
            parser_source_inventory_id=inventory.source_inventory_id,
            selected_message_paths=selected_paths,
            scanned_message_count=len(selected_paths),
            matched_occurrence_count=len(message_records),
            existing_export_verification=verification,
        ),
    )


def write_diagnostic_current_export_native_scope(
    scope: DiagnosticCurrentExportNativeScope,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """Atomically publish a private scope-manifest/checkpoint directory."""

    if not isinstance(scope, DiagnosticCurrentExportNativeScope):
        raise ContractValidationError("diagnostic current-export native scope is invalid")
    output = Path(output_dir)
    if output.is_symlink() or output.exists():
        raise ContractValidationError("diagnostic current-export scope output already exists")
    parent = output.parent
    _create_private_directory_if_missing(
        parent,
        error_message="diagnostic current-export scope parent is invalid",
    )
    if parent.is_symlink() or not parent.is_dir():
        raise ContractValidationError("diagnostic current-export scope parent is invalid")
    temporary = parent / f".{output.name}.{uuid.uuid4().hex}.tmp"
    manifest_path = temporary / "scope-manifest.private.json"
    checkpoint_path = temporary / "selected-message-checkpoint.private.json"
    try:
        _create_private_directory_if_missing(
            temporary,
            error_message="diagnostic current-export scope output is invalid",
        )
        _atomic_private_json(manifest_path, scope.manifest.to_private_dict())
        if sha256_file(manifest_path) != scope.selection_checkpoint.scope_manifest_sha256:
            raise ContractValidationError(
                "diagnostic current-export scope manifest fingerprint is invalid"
            )
        _atomic_private_json(checkpoint_path, scope.selection_checkpoint.to_private_dict())
        _fsync_directory(temporary)
        os.replace(temporary, output)
        _fsync_directory(parent)
    except Exception:
        if temporary.exists() and temporary.is_dir() and not temporary.is_symlink():
            for child in temporary.iterdir():
                if child.is_file() and not child.is_symlink():
                    child.unlink()
            temporary.rmdir()
        raise
    return output / manifest_path.name, output / checkpoint_path.name


def load_diagnostic_current_export_native_selection_checkpoint(
    path: str | Path,
    *,
    manifest: DiagnosticStructuralScopeManifest,
    scope_manifest_path: str | Path,
    parser_worker_count: int,
    max_message_file_bytes: int,
) -> DiagnosticCurrentExportNativeSelectionCheckpoint:
    """Load a native checkpoint only when bytes and current parser identity bind."""

    if not isinstance(manifest, DiagnosticStructuralScopeManifest):
        raise ContractValidationError("diagnostic current-export scope manifest is invalid")
    manifest_path = Path(scope_manifest_path)
    try:
        manifest_bytes = _read_private_regular_file_bytes(
            manifest_path,
            max_bytes=_SCOPE_MANIFEST_FILE_MAX_BYTES,
            error_message="diagnostic current-export scope manifest is unavailable",
        )
        checkpoint_bytes = _read_private_regular_file_bytes(
            Path(path),
            max_bytes=_SCOPE_MANIFEST_FILE_MAX_BYTES,
            error_message="diagnostic current-export selection checkpoint is unavailable",
        )
        checkpoint_payload = json.loads(checkpoint_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError(
            "diagnostic current-export selection checkpoint is unavailable"
        ) from exc
    parsed = DiagnosticCurrentExportNativeSelectionCheckpoint.from_private_dict(checkpoint_payload)
    if (
        parsed.scope_manifest_id != manifest.scope_manifest_id
        or "sha256:" + hashlib.sha256(manifest_bytes).hexdigest() != parsed.scope_manifest_sha256
        or parsed.parser_fingerprint
        != _diagnostic_current_parser_fingerprint(
            parser_worker_count=parser_worker_count,
            max_message_file_bytes=max_message_file_bytes,
        )
    ):
        raise ContractValidationError("diagnostic current-export selection checkpoint is stale")
    return parsed


def _read_private_regular_file_bytes(
    path: str | Path,
    *,
    max_bytes: int,
    error_message: str,
) -> bytes:
    """Read one private regular file with an inode-stable TOCTOU check."""

    candidate = Path(path)
    descriptor: int | None = None
    try:
        before = candidate.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
            or not 1 <= before.st_size <= max_bytes
        ):
            raise OSError("unsafe private file")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(candidate, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
            or _stable_file_identity(opened) != _stable_file_identity(before)
        ):
            raise OSError("private file changed while opening")
        payload = bytearray()
        while chunk := os.read(descriptor, _EXISTING_EXPORT_READ_BUFFER_BYTES):
            payload.extend(chunk)
            if len(payload) > max_bytes:
                raise OSError("private file exceeds limit")
        after = os.fstat(descriptor)
        path_after = candidate.lstat()
        if (
            len(payload) != opened.st_size
            or _stable_file_identity(after) != _stable_file_identity(opened)
            or _stable_file_identity(path_after) != _stable_file_identity(opened)
        ):
            raise OSError("private file changed while reading")
        return bytes(payload)
    except OSError as exc:
        raise ContractValidationError(error_message) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _private_relative_export_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ContractValidationError("diagnostic historical compatibility path is invalid")
    try:
        value.encode("utf-8", "strict")
    except UnicodeError as exc:
        raise ContractValidationError(
            "diagnostic historical compatibility path is invalid"
        ) from exc
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or candidate.name in {"", ".", ".."}
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or candidate.as_posix() != value
    ):
        raise ContractValidationError("diagnostic historical compatibility path is invalid")
    return value


def _current_export_message_paths(export_root: Path) -> tuple[str, ...]:
    """Return every safely named top-level message leaf in a preserved export."""

    root = _safe_existing_export_root(Path(os.path.abspath(os.fspath(export_root))))
    paths: list[str] = []

    def fail_walk(error: OSError) -> None:
        raise error

    try:
        for current_root, directory_names, file_names in os.walk(
            root,
            topdown=True,
            onerror=fail_walk,
            followlinks=False,
        ):
            directory_names.sort(key=os.fsencode)
            file_names.sort(key=os.fsencode)
            current = Path(current_root)
            current_metadata = current.lstat()
            if stat.S_ISLNK(current_metadata.st_mode) or not stat.S_ISDIR(current_metadata.st_mode):
                raise ContractValidationError("diagnostic current-export traversal is invalid")
            for name in directory_names:
                candidate = current / name
                metadata = candidate.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise ContractValidationError("diagnostic current-export traversal is invalid")
            for name in file_names:
                candidate = current / name
                metadata = candidate.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise ContractValidationError("diagnostic current-export traversal is invalid")
                if _source_unit_kind_for_path(candidate) == _PST_SOURCE_UNIT_MESSAGE:
                    paths.append(
                        _private_relative_export_path(candidate.relative_to(root).as_posix())
                    )
    except ContractValidationError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractValidationError("diagnostic current-export traversal is invalid") from exc
    normalized = tuple(sorted(paths))
    if not normalized or len(normalized) != len(set(normalized)):
        raise ContractValidationError("diagnostic current-export message paths are invalid")
    return normalized


def _selected_top_level_message_occurrence_ids_from_inventory(
    source_inventory: SourceInventory,
    *,
    selected_paths: Sequence[str],
) -> frozenset[str]:
    if not isinstance(source_inventory, SourceInventory):
        raise ContractValidationError("diagnostic current-export inventory is invalid")
    items = _selected_top_level_message_inventory_items(
        source_inventory,
        selected_paths=selected_paths,
    )
    occurrence_ids: set[str] = set()
    for item in items:
        occurrence_id = dict(item.location).get("message_occurrence_id")
        if (
            not isinstance(occurrence_id, str)
            or not occurrence_id
            or occurrence_id in occurrence_ids
        ):
            raise ContractValidationError(
                "diagnostic current-export message identities are invalid"
            )
        occurrence_ids.add(occurrence_id)
    return frozenset(occurrence_ids)


def _diagnostic_current_parser_fingerprint(
    *,
    parser_worker_count: int,
    max_message_file_bytes: int,
) -> str:
    config = _parser_config(
        {
            "parser_workers": parser_worker_count,
            "max_message_file_bytes": max_message_file_bytes,
        }
    )
    return _pst_parser_fingerprint(PstMailArchiveExtractor(), config=config)


def _current_export_native_selection_checkpoint_fingerprint(
    *,
    scope_manifest_id: str,
    scope_manifest_sha256: str,
    parser_fingerprint: str,
    parser_source_inventory_id: str,
    selected_message_paths: Sequence[str],
    selected_path_set_fingerprint: str,
    scanned_message_count: int,
    matched_occurrence_count: int,
    existing_export_verification: DiagnosticExistingExportVerification,
) -> str:
    if not isinstance(existing_export_verification, DiagnosticExistingExportVerification):
        raise ContractValidationError("diagnostic current-export selection checkpoint is invalid")
    return sha256_json(
        {
            "scope_manifest_id": scope_manifest_id,
            "scope_manifest_sha256": scope_manifest_sha256,
            "parser_fingerprint": parser_fingerprint,
            "parser_source_inventory_id": parser_source_inventory_id,
            "selected_message_paths": list(selected_message_paths),
            "selected_path_set_fingerprint": selected_path_set_fingerprint,
            "scanned_message_count": scanned_message_count,
            "matched_occurrence_count": matched_occurrence_count,
            "existing_export_verification": existing_export_verification.to_private_dict(),
        }
    )


def _private_selector_coverage(
    value: Any,
    *,
    error_message: str,
) -> dict[str, int]:
    if not isinstance(value, list) or not value:
        raise ContractValidationError(error_message)
    coverage: dict[str, int] = {}
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"selector_id", "occurrence_count"}:
            raise ContractValidationError(error_message)
        selector_id = item.get("selector_id")
        count = item.get("occurrence_count")
        if (
            not isinstance(selector_id, str)
            or not selector_id
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
            or selector_id in coverage
        ):
            raise ContractValidationError(error_message)
        coverage[selector_id] = count
    if list(coverage) != sorted(coverage):
        raise ContractValidationError(error_message)
    return coverage


def _private_compatibility_group_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value[0].isalnum()
        or any(not (character.isalnum() or character in "_.:-") for character in value)
    ):
        raise ContractValidationError("diagnostic historical compatibility group is invalid")
    return value


def _bound_scope_manifest_file_sha256(
    *,
    scope_manifest_path: str | Path | None,
    manifest: DiagnosticStructuralScopeManifest,
) -> str:
    if scope_manifest_path is None:
        raise ContractValidationError(
            "diagnostic historical compatibility requires the scope manifest file"
        )
    payload = _read_private_regular_file_bytes(
        scope_manifest_path,
        max_bytes=_SCOPE_MANIFEST_FILE_MAX_BYTES,
        error_message="diagnostic historical compatibility scope manifest is unavailable",
    )
    try:
        restored = DiagnosticStructuralScopeManifest.from_private_dict(json.loads(payload))
    except (TypeError, ValueError, json.JSONDecodeError, ContractValidationError) as exc:
        raise ContractValidationError(
            "diagnostic historical compatibility scope manifest is unavailable"
        ) from exc
    if restored != manifest:
        raise ContractValidationError(
            "diagnostic historical compatibility scope manifest does not match"
        )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _load_historical_scope_compatibility_checkpoint(
    path: str | Path,
    *,
    manifest: DiagnosticStructuralScopeManifest,
    scope_manifest_path: str | Path | None,
) -> _HistoricalScopeCompatibilityCheckpoint:
    """Load a closed private checkpoint that maps historical scope to paths.

    Current parser identities are intentionally absent from this schema.  A
    trusted external process must have bound the historical selectors before
    this local materializer can parse the selected current export files.
    """

    raw = _read_private_regular_file_bytes(
        path,
        max_bytes=_HISTORICAL_SCOPE_COMPATIBILITY_CHECKPOINT_MAX_BYTES,
        error_message="diagnostic historical compatibility checkpoint is unavailable",
    )
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractValidationError(
            "diagnostic historical compatibility checkpoint is unavailable"
        ) from exc
    required = {
        "artifact_type",
        "scope_manifest_id",
        "scope_manifest_sha256",
        "legacy_parser_sha256",
        "selected_path_count",
        "matched_occurrence_count",
        "selector_coverage_fingerprint",
        "path_bindings",
        "compatibility_groups",
    }
    if (
        not isinstance(payload, Mapping)
        or set(payload) != required
        or payload.get("artifact_type") != _HISTORICAL_SCOPE_COMPATIBILITY_CHECKPOINT_ARTIFACT_TYPE
    ):
        raise ContractValidationError("diagnostic historical compatibility checkpoint is invalid")
    scope_manifest_sha256 = payload.get("scope_manifest_sha256")
    legacy_parser_sha256 = payload.get("legacy_parser_sha256")
    selector_coverage_fingerprint = payload.get("selector_coverage_fingerprint")
    selected_path_count = payload.get("selected_path_count")
    matched_occurrence_count = payload.get("matched_occurrence_count")
    if (
        payload.get("scope_manifest_id") != manifest.scope_manifest_id
        or scope_manifest_sha256
        != _bound_scope_manifest_file_sha256(
            scope_manifest_path=scope_manifest_path,
            manifest=manifest,
        )
        or any(
            not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71
            for value in (
                scope_manifest_sha256,
                legacy_parser_sha256,
                selector_coverage_fingerprint,
            )
        )
        or any(
            character not in "0123456789abcdef"
            for value in (
                scope_manifest_sha256,
                legacy_parser_sha256,
                selector_coverage_fingerprint,
            )
            for character in value.removeprefix("sha256:")
        )
        or not isinstance(selected_path_count, int)
        or isinstance(selected_path_count, bool)
        or selected_path_count < 1
        or not isinstance(matched_occurrence_count, int)
        or isinstance(matched_occurrence_count, bool)
        or matched_occurrence_count < 1
    ):
        raise ContractValidationError("diagnostic historical compatibility checkpoint is invalid")

    expected_selector_counts = {
        item.selector_id: item.expected_occurrence_count for item in manifest.selectors
    }
    path_owner: set[str] = set()
    selector_counts = {selector_id: 0 for selector_id in expected_selector_counts}
    path_bindings = payload.get("path_bindings")
    if not isinstance(path_bindings, list):
        raise ContractValidationError("diagnostic historical compatibility checkpoint is invalid")
    previous_path: str | None = None
    for binding in path_bindings:
        if not isinstance(binding, Mapping) or set(binding) != {
            "relative_path",
            "selector_coverage",
        }:
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint is invalid"
            )
        relative_path = _private_relative_export_path(binding.get("relative_path"))
        if previous_path is not None and relative_path <= previous_path:
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint path ordering is invalid"
            )
        previous_path = relative_path
        if relative_path in path_owner:
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint path ownership is invalid"
            )
        coverage = _private_selector_coverage(
            binding.get("selector_coverage"),
            error_message="diagnostic historical compatibility checkpoint is invalid",
        )
        if any(selector_id not in expected_selector_counts for selector_id in coverage):
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint selector is invalid"
            )
        path_owner.add(relative_path)
        for selector_id, count in coverage.items():
            selector_counts[selector_id] += count

    groups = payload.get("compatibility_groups")
    if not isinstance(groups, list):
        raise ContractValidationError("diagnostic historical compatibility checkpoint is invalid")
    group_ids: set[str] = set()
    previous_group_id: str | None = None
    for group in groups:
        if not isinstance(group, Mapping) or set(group) != {
            "group_id",
            "relative_paths",
            "selected_path_set_fingerprint",
            "selector_coverage",
            "selector_coverage_fingerprint",
        }:
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint group is invalid"
            )
        group_id = _private_compatibility_group_id(group.get("group_id"))
        if group_id in group_ids or (
            previous_group_id is not None and group_id <= previous_group_id
        ):
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint group ordering is invalid"
            )
        group_ids.add(group_id)
        previous_group_id = group_id
        raw_paths = group.get("relative_paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint group is invalid"
            )
        group_paths = tuple(_private_relative_export_path(item) for item in raw_paths)
        if tuple(sorted(group_paths)) != group_paths or len(group_paths) != len(set(group_paths)):
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint group paths are invalid"
            )
        if any(path in path_owner for path in group_paths):
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint path ownership is invalid"
            )
        coverage = _private_selector_coverage(
            group.get("selector_coverage"),
            error_message="diagnostic historical compatibility checkpoint group is invalid",
        )
        if any(selector_id not in expected_selector_counts for selector_id in coverage):
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint selector is invalid"
            )
        if group.get("selected_path_set_fingerprint") != sha256_json(
            list(group_paths)
        ) or group.get("selector_coverage_fingerprint") != _selector_coverage_fingerprint(coverage):
            raise ContractValidationError(
                "diagnostic historical compatibility checkpoint group binding is invalid"
            )
        path_owner.update(group_paths)
        for selector_id, count in coverage.items():
            selector_counts[selector_id] += count

    selected_paths = tuple(sorted(path_owner))
    if (
        not selected_paths
        or len(selected_paths) != selected_path_count
        or matched_occurrence_count != manifest.expected_message_count
        or sum(selector_counts.values()) != matched_occurrence_count
        or selector_counts != expected_selector_counts
        or selector_coverage_fingerprint != _selector_coverage_fingerprint(selector_counts)
    ):
        raise ContractValidationError("diagnostic historical compatibility coverage is invalid")
    return _HistoricalScopeCompatibilityCheckpoint(
        checkpoint_fingerprint="sha256:" + hashlib.sha256(raw).hexdigest(),
        scope_manifest_id=manifest.scope_manifest_id,
        scope_manifest_sha256=scope_manifest_sha256,
        legacy_parser_sha256=legacy_parser_sha256,
        selected_path_count=selected_path_count,
        matched_occurrence_count=matched_occurrence_count,
        selector_coverage_fingerprint=selector_coverage_fingerprint,
        selected_paths=selected_paths,
        selector_counts=selector_counts,
    )


def load_diagnostic_structural_scope_authority_verifier(
    path: str | Path,
) -> CoverageScopeAuthorityVerifier:
    """Load one private stable root for persisted authority revalidation.

    The root is deliberately never added to a bundle, checkpoint, CLI JSON
    result, or semantic profile. A later MCP process must load this exact
    private root and revalidate persisted authorities before definitive use.
    """

    try:
        candidate = Path(path)
        metadata = candidate.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
            or not 16 <= metadata.st_size <= _SCOPE_AUTHORITY_ROOT_FILE_MAX_BYTES
        ):
            raise OSError("unsafe scope authority root")
        root = candidate.read_bytes()
        verified_metadata = candidate.lstat()
        if (
            verified_metadata.st_dev != metadata.st_dev
            or verified_metadata.st_ino != metadata.st_ino
            or verified_metadata.st_size != metadata.st_size
            or verified_metadata.st_mode != metadata.st_mode
        ):
            raise OSError("scope authority root changed while reading")
        return CoverageScopeAuthorityVerifier.from_external_root(root)
    except (OSError, TypeError, ValueError, ContractValidationError) as exc:
        raise ContractValidationError(
            "diagnostic structural scope authority root is unavailable"
        ) from exc


def initialize_diagnostic_structural_scope_authority_root(path: str | Path) -> str:
    """Create one new private authority root without rotating an existing one.

    The previous root is external trust material and cannot be reconstructed
    from a persisted bundle.  This operation intentionally creates a distinct
    chain for a fresh existing-export materialization; its output reveals only
    the verifier fingerprint, never root bytes.
    """

    candidate = Path(path)
    parent = _safe_private_directory(candidate.parent)
    if candidate.parent != parent or candidate.name in {"", ".", ".."}:
        raise ContractValidationError("diagnostic scope authority root path is invalid")
    if candidate.exists() or candidate.is_symlink():
        raise ContractValidationError("diagnostic scope authority root already exists")
    root = secrets.token_bytes(32)
    descriptor: int | None = None
    created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(
            candidate,
            flags,
            0o600,
        )
        created = True
        _write_all_private_bytes(descriptor, root)
        os.fsync(descriptor)
    except OSError as exc:
        if created:
            candidate.unlink(missing_ok=True)
        raise ContractValidationError("diagnostic scope authority root is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _fsync_directory(parent)
    return load_diagnostic_structural_scope_authority_verifier(candidate).verifier_fingerprint


def load_diagnostic_semantic_profile(path: str | Path) -> DiagnosticSemanticProfile:
    """Load the same private semantic profile consumed by ``diagnostic_mcp``."""

    try:
        candidate = Path(path)
        metadata = candidate.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
            or not 1 <= metadata.st_size <= 512 * 1024
        ):
            raise OSError("unsafe semantic scope profile")
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        verified_metadata = candidate.lstat()
        if (
            verified_metadata.st_dev != metadata.st_dev
            or verified_metadata.st_ino != metadata.st_ino
            or verified_metadata.st_size != metadata.st_size
            or verified_metadata.st_mode != metadata.st_mode
        ):
            raise OSError("semantic scope profile changed while reading")
        if not isinstance(payload, Mapping):
            raise ValueError("semantic scope profile is invalid")
        return DiagnosticSemanticProfile.from_private_dict(payload)
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ContractValidationError,
    ) as exc:
        raise ContractValidationError(
            "diagnostic structural semantic scope profile is unavailable"
        ) from exc


def plan_diagnostic_structural_materialization(
    manifest: DiagnosticStructuralScopeManifest,
    *,
    pst_path: str | Path | None = None,
    export_root: str | Path | None = None,
    full_scope_source_asset_id: str | None = None,
    full_scope_source_fingerprint: str | None = None,
    parallel_jobs: int = 1,
    parser_worker_count: int = 1,
    shard_batch_size: int = DEFAULT_DIAGNOSTIC_SHARD_BATCH_SIZE,
    max_message_file_bytes: int = 25 * 1024 * 1024,
    memory_policy_limit_bytes: int = _MATERIALIZATION_MEMORY_POLICY_BYTES,
    scratch_dir: str | Path | None = None,
    scratch_disk_budget_bytes: int | None = None,
) -> DiagnosticStructuralMaterializationPlan:
    """Return the bounded work plan without invoking ``readpst`` or parsing mail."""

    if not isinstance(manifest, DiagnosticStructuralScopeManifest):
        raise ContractValidationError("diagnostic materialization manifest is invalid")
    _validate_materialization_sources(pst_path=pst_path, export_root=export_root)
    if not _full_scope_archive_binding_matches(
        manifest,
        source_asset_id=full_scope_source_asset_id,
        source_fingerprint=full_scope_source_fingerprint,
    ):
        raise ContractValidationError(
            "diagnostic materialization requires operator-bound source identity"
        )
    if parallel_jobs not in PST_READPST_PARALLEL_JOBS:
        raise ContractValidationError("diagnostic readpst parallel jobs are invalid")
    if (
        not isinstance(parser_worker_count, int)
        or isinstance(parser_worker_count, bool)
        or parser_worker_count != 1
    ):
        raise ContractValidationError("diagnostic parser worker count is invalid")
    if (
        not isinstance(max_message_file_bytes, int)
        or isinstance(max_message_file_bytes, bool)
        or max_message_file_bytes < 1024
    ):
        raise ContractValidationError("diagnostic max message file bytes is invalid")
    if (
        not isinstance(shard_batch_size, int)
        or isinstance(shard_batch_size, bool)
        or not 1 <= shard_batch_size <= _MAX_DIAGNOSTIC_SHARD_BATCH_SIZE
    ):
        raise ContractValidationError("diagnostic shard batch size is invalid")
    if (
        not isinstance(memory_policy_limit_bytes, int)
        or isinstance(memory_policy_limit_bytes, bool)
        or memory_policy_limit_bytes < 1024 * 1024 * 1024
    ):
        raise ContractValidationError("diagnostic memory policy limit is invalid")
    if scratch_disk_budget_bytes is not None and (
        not isinstance(scratch_disk_budget_bytes, int)
        or isinstance(scratch_disk_budget_bytes, bool)
        or scratch_disk_budget_bytes < 1
    ):
        raise ContractValidationError("diagnostic scratch disk budget is invalid")
    estimated_export_disk_bytes: int | None = None
    available_scratch_disk_bytes: int | None = None
    if pst_path is not None:
        _, size = _validated_pst_input(pst_path)
        # readpst has no output-size preflight. Four times source bytes is an
        # intentionally conservative operator budget, not a size guarantee.
        estimated_export_disk_bytes = size * 4
        if scratch_dir is None:
            raise ContractValidationError("diagnostic PST plan requires a scratch directory")
        if not _is_home_checkpoint_filesystem(Path(scratch_dir)):
            raise ContractValidationError("diagnostic PST checkpoint requires a /home filesystem")
        available_scratch_disk_bytes = _available_scratch_disk_bytes(Path(scratch_dir))
        if available_scratch_disk_bytes < estimated_export_disk_bytes:
            raise ContractValidationError("diagnostic scratch disk capacity is insufficient")
        if (
            scratch_disk_budget_bytes is not None
            and scratch_disk_budget_bytes < estimated_export_disk_bytes
        ):
            raise ContractValidationError("diagnostic scratch disk budget is insufficient")
    shard_message_count = min(manifest.expected_message_count, shard_batch_size)
    shard_body_segment_count = min(
        manifest.expected_body_segment_count,
        max(
            shard_message_count,
            math.ceil(
                manifest.expected_body_segment_count
                * shard_message_count
                / manifest.expected_message_count
            )
            * 2,
        ),
    )
    # The parser retains decoded messages for the whole shard, and canonical
    # publication performs one bundle/JSON round trip. Bound both copies by
    # the configured source-file ceiling instead of accounting for only the
    # single currently active parser worker.
    shard_payload_memory_bytes = shard_message_count * max_message_file_bytes * 2
    estimated_peak_memory_bytes = (
        parallel_jobs * _READPST_PER_JOB_MEMORY_RESERVE_BYTES
        + shard_payload_memory_bytes
        + parser_worker_count * max_message_file_bytes
        + shard_body_segment_count * _BUNDLE_BODY_SEGMENT_MEMORY_RESERVE_BYTES
        + shard_message_count * _BUNDLE_MESSAGE_MEMORY_RESERVE_BYTES
        + 64 * 1024 * 1024
    )
    if estimated_peak_memory_bytes > memory_policy_limit_bytes:
        raise ContractValidationError("diagnostic materialization memory policy is insufficient")
    return DiagnosticStructuralMaterializationPlan(
        scope_manifest_id=manifest.scope_manifest_id,
        expected_message_count=manifest.expected_message_count,
        expected_body_segment_count=manifest.expected_body_segment_count,
        materialization_mode="bounded_sharded_selector",
        required_pst_scan_count=1 if pst_path is not None else 0,
        required_export_selection_scan_count=1,
        parallel_jobs=parallel_jobs,
        parser_worker_count=parser_worker_count,
        shard_batch_size=shard_batch_size,
        shard_count=math.ceil(manifest.expected_message_count / shard_batch_size),
        estimated_peak_memory_bytes=estimated_peak_memory_bytes,
        memory_policy_limit_bytes=memory_policy_limit_bytes,
        estimated_export_disk_bytes=estimated_export_disk_bytes,
        available_scratch_disk_bytes=available_scratch_disk_bytes,
        can_resume_after_readpst=True,
    )


def materialize_diagnostic_structural_scope(
    manifest: DiagnosticStructuralScopeManifest,
    *,
    bridge_dir: str | Path,
    checkpoint_dir: str | Path,
    created_at: str,
    scope_authority_verifier: CoverageScopeAuthorityVerifier | None = None,
    semantic_profile: DiagnosticSemanticProfile | None = None,
    pst_path: str | Path | None = None,
    export_root: str | Path | None = None,
    full_scope_source_asset_id: str | None = None,
    full_scope_source_fingerprint: str | None = None,
    parser_command: str = "readpst",
    timeout_seconds: int = 8 * 60 * 60,
    parallel_jobs: int = 1,
    parser_worker_count: int = 1,
    shard_batch_size: int = DEFAULT_DIAGNOSTIC_SHARD_BATCH_SIZE,
    max_message_file_bytes: int = 25 * 1024 * 1024,
    memory_policy_limit_bytes: int = _MATERIALIZATION_MEMORY_POLICY_BYTES,
    scratch_disk_budget_bytes: int | None = None,
    reader_uid: int = 65532,
    reader_gid: int = 65532,
    historical_compatibility_checkpoint: str | Path | None = None,
    native_selection_checkpoint: str | Path | None = None,
    scope_manifest_path: str | Path | None = None,
) -> DiagnosticStructuralMaterializationPublication:
    """Materialize exactly the manifest scope as restartable bounded shards.

    A raw PST route invokes ``readpst`` at most once.  An existing-export route
    either performs one bounded selector scan or consumes a source-bound native
    selection checkpoint. Each deterministic path slice is then published to
    its own atomic canonical bundle followed by a path-free checkpoint. A
    complete aggregate manifest becomes visible only after every shard and
    global multiplicity/count invariant has passed.
    """

    if historical_compatibility_checkpoint is not None and pst_path is not None:
        raise ContractValidationError(
            "diagnostic historical compatibility requires an existing export"
        )
    if native_selection_checkpoint is not None and (
        pst_path is not None or historical_compatibility_checkpoint is not None
    ):
        raise ContractValidationError(
            "diagnostic current-export selection requires an existing export only"
        )
    if native_selection_checkpoint is not None and scope_manifest_path is None:
        raise ContractValidationError(
            "diagnostic current-export selection requires the private scope manifest"
        )
    historical_compatibility = (
        _load_historical_scope_compatibility_checkpoint(
            historical_compatibility_checkpoint,
            manifest=manifest,
            scope_manifest_path=scope_manifest_path,
        )
        if historical_compatibility_checkpoint is not None
        else None
    )
    plan_diagnostic_structural_materialization(
        manifest,
        pst_path=pst_path,
        export_root=export_root,
        full_scope_source_asset_id=full_scope_source_asset_id,
        full_scope_source_fingerprint=full_scope_source_fingerprint,
        parallel_jobs=parallel_jobs,
        parser_worker_count=parser_worker_count,
        shard_batch_size=shard_batch_size,
        max_message_file_bytes=max_message_file_bytes,
        memory_policy_limit_bytes=memory_policy_limit_bytes,
        scratch_dir=checkpoint_dir,
        scratch_disk_budget_bytes=scratch_disk_budget_bytes,
    )
    _validate_optional_semantic_binding_inputs(
        scope_authority_verifier=scope_authority_verifier,
        semantic_profile=semantic_profile,
    )
    if not isinstance(scope_authority_verifier, CoverageScopeAuthorityVerifier) or not isinstance(
        semantic_profile, DiagnosticSemanticProfile
    ):
        raise ContractValidationError(
            "diagnostic sharded materialization requires profile authority"
        )

    root = _safe_private_directory(Path(checkpoint_dir))
    state_path = root / "materialization-state.json"
    state = _load_private_checkpoint(state_path)
    _validate_checkpoint_manifest(
        state,
        manifest,
        historical_compatibility_checkpoint_fingerprint=(
            historical_compatibility.checkpoint_fingerprint
            if historical_compatibility is not None
            else None
        ),
    )
    resumed_readpst_export = False
    pst_scan_count = 0
    if export_root is None:
        assert pst_path is not None
        exported_root = root / "readpst-export"
        export_state_path = root / "readpst-export-complete.json"
        export_state = _load_private_checkpoint(export_state_path)
        if _checkpoint_matches_export(export_state, manifest, pst_path):
            exported_root = _safe_existing_export_root(exported_root)
            resumed_readpst_export = True
        else:
            if exported_root.exists() and any(exported_root.iterdir()):
                raise ContractValidationError(
                    "diagnostic readpst checkpoint is incomplete; use a new empty checkpoint"
                )
            export_pst_to_readpst_directory(
                pst_path=pst_path,
                export_root=exported_root,
                timeout_seconds=timeout_seconds,
                parser_command=parser_command,
                parallel_jobs=parallel_jobs,
            )
            _atomic_private_json(
                export_state_path,
                _export_checkpoint_payload(manifest, pst_path),
            )
            pst_scan_count = 1
    else:
        exported_root = _safe_existing_export_root(Path(export_root))

    native_selection = (
        load_diagnostic_current_export_native_selection_checkpoint(
            native_selection_checkpoint,
            manifest=manifest,
            scope_manifest_path=scope_manifest_path,
            parser_worker_count=parser_worker_count,
            max_message_file_bytes=max_message_file_bytes,
        )
        if native_selection_checkpoint is not None
        else None
    )
    selector_path = root / "selected-message-paths.private.json"
    selection_state = _load_private_checkpoint(selector_path)
    if historical_compatibility is not None:
        selected_paths = historical_compatibility.selected_paths
        selection = None
    elif native_selection is not None:
        selected_paths = native_selection.selected_message_paths
        selection = None
    else:
        if _checkpoint_matches_selection(selection_state, manifest):
            selected_paths = _load_selected_paths(selection_state)
            selection = None
        else:
            selection = select_readpst_export_messages(
                export_root=exported_root,
                selectors=tuple(
                    PstReadpstMessageSelector(
                        selector_id=item.selector_id,
                        message_id=item.message_id,
                        folder_path_hash=item.folder_path_hash,
                        body_hash=item.body_hash,
                        expected_occurrence_count=item.expected_occurrence_count,
                    )
                    for item in manifest.selectors
                ),
                extractor_config={
                    "parser_workers": parser_worker_count,
                    "max_message_file_bytes": max_message_file_bytes,
                },
            )
            if not selection.complete or not selection.selected_message_paths:
                _atomic_private_json(
                    state_path,
                    _materialization_state_payload(
                        manifest,
                        state="selection_incomplete",
                        scanned_message_count=selection.scanned_message_count,
                        selected_export_message_count=selection.matched_occurrence_count,
                        pst_scan_count=pst_scan_count,
                    ),
                )
                raise ContractValidationError("diagnostic scope selector coverage is incomplete")
            _atomic_private_json(
                selector_path,
                {
                    "artifact_type": _SELECTION_CHECKPOINT_ARTIFACT_TYPE,
                    "scope_manifest_id": manifest.scope_manifest_id,
                    "selected_message_paths": list(selection.selected_message_paths),
                    "scanned_message_count": selection.scanned_message_count,
                    "matched_occurrence_count": selection.matched_occurrence_count,
                    "selected_message_count": selection.matched_occurrence_count,
                },
            )
            selected_paths = selection.selected_message_paths

    selection_scanned_message_count = (
        selection.scanned_message_count
        if selection is not None
        else (
            historical_compatibility.selected_path_count
            if historical_compatibility is not None
            else (
                native_selection.scanned_message_count
                if native_selection is not None
                else _required_checkpoint_integer(
                    selection_state,
                    "scanned_message_count",
                )
            )
        )
    )
    matched_occurrence_count = (
        selection.matched_occurrence_count
        if selection is not None
        else (
            historical_compatibility.matched_occurrence_count
            if historical_compatibility is not None
            else (
                native_selection.matched_occurrence_count
                if native_selection is not None
                else _required_checkpoint_integer(
                    selection_state,
                    "matched_occurrence_count",
                )
            )
        )
    )
    existing_export_verification = _verify_operator_bound_existing_export(
        export_root=exported_root,
        selected_message_paths=selected_paths,
        scanned_message_count=selection_scanned_message_count,
        matched_occurrence_count=matched_occurrence_count,
        manifest=manifest,
        full_scope_source_asset_id=full_scope_source_asset_id,
        full_scope_source_fingerprint=full_scope_source_fingerprint,
        historical_compatibility=historical_compatibility,
    )
    if (
        native_selection is not None
        and existing_export_verification != native_selection.existing_export_verification
    ):
        raise ContractValidationError(
            "diagnostic current-export selection checkpoint source drift is detected"
        )
    scanned_message_count = existing_export_verification.export_message_file_count
    path_batches = _deterministic_path_batches(
        selected_paths,
        shard_batch_size=shard_batch_size,
    )
    shard_store = FileDiagnosticStructuralShardStore(bridge_dir)
    selected_path_set_fingerprint = sha256_json(list(selected_paths))
    expected_selector_coverage_fingerprint = _selector_coverage_fingerprint(
        {item.selector_id: item.expected_occurrence_count for item in manifest.selectors}
    )
    if historical_compatibility is not None:
        expected_selector_coverage_fingerprint = (
            historical_compatibility.selector_coverage_fingerprint
        )
    if shard_store.aggregate_manifest_path.exists():
        aggregate = shard_store.load_complete_manifest()
        _validate_aggregate_manifest_binding(
            aggregate,
            manifest=manifest,
            semantic_profile=semantic_profile,
            shard_batch_size=shard_batch_size,
            path_batches=path_batches,
            selected_path_set_fingerprint=selected_path_set_fingerprint,
            expected_selector_coverage_fingerprint=(expected_selector_coverage_fingerprint),
            existing_export_verification=existing_export_verification,
            historical_compatibility=historical_compatibility,
        )
        return DiagnosticStructuralMaterializationPublication(
            publication=None,
            scope_manifest_id=manifest.scope_manifest_id,
            scanned_message_count=scanned_message_count,
            selected_export_message_count=aggregate.expected_message_count,
            pst_scan_count=pst_scan_count,
            resumed_readpst_export=resumed_readpst_export,
            existing_export_verification=existing_export_verification,
            aggregate_manifest_id=aggregate.aggregate_manifest_id,
            shard_count=len(aggregate.shards),
            aggregate_created=False,
        )

    checkpoint_root = _safe_private_directory(root / "shard-checkpoints.private")
    checkpoint_records = _complete_checkpoint_records_for_fast_republish(
        checkpoint_root=checkpoint_root,
        manifest=manifest,
        path_batches=path_batches,
        shard_store=shard_store,
        existing_export_verification=existing_export_verification,
        historical_compatibility=historical_compatibility,
    )
    records: list[DiagnosticStructuralShardRecord] = []
    if checkpoint_records is not None:
        # This shortcut is deliberately all-or-nothing.  Every deterministic
        # batch has a checkpoint whose scope/path/verification binding is
        # valid and whose exact bundle name/fingerprint remains present.  The
        # aggregate source split is still recomputed below from those bundles.
        records.extend(checkpoint_records)
        for record in checkpoint_records:
            _grant_mcp_read_only_access(
                bridge_dir=shard_store.shard_dir(record.ordinal),
                bundle_path=shard_store.checkpoint_bound_bundle_path(record),
                reader_uid=reader_uid,
                reader_gid=reader_gid,
            )
    else:
        aggregate_selector_counts = {item.selector_id: 0 for item in manifest.selectors}
        for ordinal, selected_batch in enumerate(path_batches):
            checkpoint_path = checkpoint_root / f"{ordinal:08d}.json"
            checkpoint = _load_private_checkpoint(checkpoint_path)
            record: DiagnosticStructuralShardRecord | None = None
            if checkpoint is not None:
                record = _shard_record_from_checkpoint(
                    checkpoint,
                    manifest=manifest,
                    ordinal=ordinal,
                    selected_paths=selected_batch,
                    existing_export_verification=existing_export_verification,
                    historical_compatibility=historical_compatibility,
                )

            shard_dir = shard_store.root / f"{ordinal:08d}"
            existing_bundle_path = (
                shard_store.unique_bundle_path(ordinal)
                if shard_dir.is_dir() and not shard_dir.is_symlink()
                else None
            )
            if existing_bundle_path is None:
                if record is not None:
                    raise ContractValidationError(
                        "diagnostic structural shard checkpoint has no bundle"
                    )
                publication = produce_diagnostic_structural_bridge(
                    export_root=exported_root,
                    selected_message_paths=selected_batch,
                    bridge_dir=shard_store.shard_dir(ordinal, create=True),
                    source_asset_id=manifest.source_asset_id,
                    source_fingerprint=manifest.source_fingerprint,
                    workspace_id=manifest.workspace_id,
                    owner_user_id=manifest.owner_user_id,
                    permission_scope=manifest.permission_scope,
                    created_at=created_at,
                    scope_authority_verifier=scope_authority_verifier,
                    semantic_profile=semantic_profile,
                    existing_export_verification=existing_export_verification,
                    historical_compatibility_scope=historical_compatibility is not None,
                    extractor_config={
                        "parser_workers": parser_worker_count,
                        "max_message_file_bytes": max_message_file_bytes,
                    },
                )
                existing_bundle_path = publication.bundle_path

            bundle = FileMailEvidenceBundleStore._read(existing_bundle_path)
            computed_record, selector_counts = _validated_shard_record(
                bundle,
                bundle_path=existing_bundle_path,
                manifest=manifest,
                ordinal=ordinal,
                selected_paths=selected_batch,
                scope_authority_verifier=scope_authority_verifier,
                semantic_profile=semantic_profile,
                existing_export_verification=existing_export_verification,
                parser_version=PstMailArchiveExtractor().version(),
                historical_compatibility=historical_compatibility,
            )
            if record is not None and record != computed_record:
                raise ContractValidationError(
                    "diagnostic structural shard checkpoint does not match bundle"
                )
            if record is None:
                _atomic_private_json(
                    checkpoint_path,
                    {
                        "artifact_type": _SHARD_CHECKPOINT_ARTIFACT_TYPE,
                        "scope_manifest_id": manifest.scope_manifest_id,
                        **computed_record.to_private_dict(),
                    },
                )
                record = computed_record
            if historical_compatibility is None:
                for selector_id, count in selector_counts.items():
                    aggregate_selector_counts[selector_id] += count
            records.append(record)
            _grant_mcp_read_only_access(
                bridge_dir=shard_store.shard_dir(ordinal),
                bundle_path=existing_bundle_path,
                reader_uid=reader_uid,
                reader_gid=reader_gid,
            )
            del bundle

        if historical_compatibility is None and aggregate_selector_counts != {
            item.selector_id: item.expected_occurrence_count for item in manifest.selectors
        }:
            raise ContractValidationError(
                "diagnostic structural aggregate selector coverage is incomplete"
            )

    aggregate_selector_coverage_fingerprint = (
        historical_compatibility.selector_coverage_fingerprint
        if historical_compatibility is not None
        else (
            expected_selector_coverage_fingerprint
            if checkpoint_records is not None
            else _selector_coverage_fingerprint(aggregate_selector_counts)
        )
    )
    body_segment_accounting = shard_store.recompute_body_segment_accounting(tuple(records))
    aggregate = DiagnosticStructuralAggregateManifest.create(
        scope_manifest_id=manifest.scope_manifest_id,
        source_asset_id=manifest.source_asset_id,
        source_fingerprint=manifest.source_fingerprint,
        workspace_id=manifest.workspace_id,
        owner_user_id=manifest.owner_user_id,
        semantic_profile_fingerprint=semantic_profile.profile_fingerprint,
        existing_export_verification=existing_export_verification,
        shard_batch_size=shard_batch_size,
        selected_path_set_fingerprint=selected_path_set_fingerprint,
        selector_coverage_fingerprint=aggregate_selector_coverage_fingerprint,
        expected_message_count=manifest.expected_message_count,
        expected_body_segment_count=manifest.expected_body_segment_count,
        total_structural_observation_count=sum(
            item.structural_observation_count for item in records
        ),
        shards=tuple(records),
        historical_compatibility_checkpoint_fingerprint=(
            historical_compatibility.checkpoint_fingerprint
            if historical_compatibility is not None
            else None
        ),
        selected_top_level_message_count=sum(
            item.selected_top_level_message_count for item in records
        ),
        materialized_message_occurrence_count=sum(item.selected_message_count for item in records),
        materialized_body_segment_count=body_segment_accounting.total_body_segment_count,
        materialized_message_body_segment_count=(
            body_segment_accounting.message_body_segment_count
        ),
        materialized_attachment_text_segment_count=(
            body_segment_accounting.attachment_text_segment_count
        ),
    )
    aggregate_created = shard_store.publish_complete_manifest(aggregate)
    _grant_sharded_mcp_read_only_access(
        bridge_dir=Path(bridge_dir),
        shard_store=shard_store,
        reader_gid=reader_gid,
    )
    _atomic_private_json(
        state_path,
        _materialization_state_payload(
            manifest,
            state="published",
            scanned_message_count=scanned_message_count,
            selected_export_message_count=aggregate.expected_message_count,
            pst_scan_count=pst_scan_count,
            existing_export_verification=existing_export_verification,
            historical_compatibility_checkpoint_fingerprint=(
                historical_compatibility.checkpoint_fingerprint
                if historical_compatibility is not None
                else None
            ),
        ),
    )
    return DiagnosticStructuralMaterializationPublication(
        publication=None,
        scope_manifest_id=manifest.scope_manifest_id,
        scanned_message_count=scanned_message_count,
        selected_export_message_count=aggregate.expected_message_count,
        pst_scan_count=pst_scan_count,
        resumed_readpst_export=resumed_readpst_export,
        existing_export_verification=existing_export_verification,
        aggregate_manifest_id=aggregate.aggregate_manifest_id,
        shard_count=len(aggregate.shards),
        aggregate_created=aggregate_created,
    )


def _deterministic_path_batches(
    selected_paths: Sequence[str],
    *,
    shard_batch_size: int,
) -> tuple[tuple[str, ...], ...]:
    if (
        not isinstance(shard_batch_size, int)
        or isinstance(shard_batch_size, bool)
        or not 1 <= shard_batch_size <= _MAX_DIAGNOSTIC_SHARD_BATCH_SIZE
    ):
        raise ContractValidationError("diagnostic shard batch size is invalid")
    paths = tuple(selected_paths)
    if (
        not paths
        or any(not isinstance(path, str) or not path for path in paths)
        or len(paths) != len(set(paths))
    ):
        raise ContractValidationError("diagnostic selected message paths are invalid")
    canonical = tuple(sorted(paths))
    return tuple(
        canonical[offset : offset + shard_batch_size]
        for offset in range(0, len(canonical), shard_batch_size)
    )


def _selector_coverage_fingerprint(counts: Mapping[str, int]) -> str:
    if not isinstance(counts, Mapping) or any(
        not isinstance(selector_id, str)
        or not selector_id
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        for selector_id, count in counts.items()
    ):
        raise ContractValidationError("diagnostic structural selector accounting is invalid")
    return sha256_json(
        [
            {"selector_id": selector_id, "occurrence_count": counts[selector_id]}
            for selector_id in sorted(counts)
        ]
    )


def _shard_record_from_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    manifest: DiagnosticStructuralScopeManifest,
    ordinal: int,
    selected_paths: Sequence[str],
    existing_export_verification: DiagnosticExistingExportVerification,
    historical_compatibility: _HistoricalScopeCompatibilityCheckpoint | None,
) -> DiagnosticStructuralShardRecord:
    required = {
        "artifact_type",
        "scope_manifest_id",
        "ordinal",
        "mail_evidence_bundle_id",
        "bundle_fingerprint",
        "existing_export_verification_fingerprint",
        "selected_path_fingerprint",
        "selector_coverage_fingerprint",
        "selected_message_count",
        "body_segment_count",
        "structural_observation_count",
        "selected_top_level_message_count",
        "embedded_message_occurrence_count",
        "historical_compatibility_checkpoint_fingerprint",
    }
    if (
        set(checkpoint) != required
        or checkpoint.get("artifact_type") != _SHARD_CHECKPOINT_ARTIFACT_TYPE
        or checkpoint.get("scope_manifest_id") != manifest.scope_manifest_id
    ):
        raise ContractValidationError("diagnostic structural shard checkpoint is invalid")
    record = DiagnosticStructuralShardRecord.from_private_dict(
        {key: checkpoint[key] for key in required - {"artifact_type", "scope_manifest_id"}}
    )
    if (
        record.ordinal != ordinal
        or record.existing_export_verification_fingerprint
        != existing_export_verification.verification_fingerprint
        or record.selected_path_fingerprint != sha256_json(list(selected_paths))
        or record.selected_top_level_message_count != len(selected_paths)
        or record.historical_compatibility_checkpoint_fingerprint
        != (
            historical_compatibility.checkpoint_fingerprint
            if historical_compatibility is not None
            else None
        )
        or (
            historical_compatibility is not None
            and record.selector_coverage_fingerprint
            != historical_compatibility.shard_scope_fragment_fingerprint(selected_paths)
        )
        or (
            historical_compatibility is None
            and (
                record.selected_message_count != len(selected_paths)
                or record.embedded_message_occurrence_count != 0
            )
        )
    ):
        raise ContractValidationError("diagnostic structural shard checkpoint is out of sequence")
    return record


def _complete_checkpoint_records_for_fast_republish(
    *,
    checkpoint_root: Path,
    manifest: DiagnosticStructuralScopeManifest,
    path_batches: Sequence[Sequence[str]],
    shard_store: FileDiagnosticStructuralShardStore,
    existing_export_verification: DiagnosticExistingExportVerification,
    historical_compatibility: _HistoricalScopeCompatibilityCheckpoint | None,
) -> tuple[DiagnosticStructuralShardRecord, ...] | None:
    """Return every bound checkpoint record, or no shortcut at all.

    A resume can skip full shard validation only after every deterministic
    batch has an exact checkpoint and its checkpoint-bound canonical bundle.
    Any absent, malformed, out-of-sequence, or hash-drifted item returns
    ``None`` so the established recovery/materialization loop remains the
    only path that can repair or reject it.
    """

    records: list[DiagnosticStructuralShardRecord] = []
    try:
        for ordinal, selected_paths in enumerate(path_batches):
            checkpoint = _load_private_checkpoint(checkpoint_root / f"{ordinal:08d}.json")
            if checkpoint is None:
                return None
            record = _shard_record_from_checkpoint(
                checkpoint,
                manifest=manifest,
                ordinal=ordinal,
                selected_paths=selected_paths,
                existing_export_verification=existing_export_verification,
                historical_compatibility=historical_compatibility,
            )
            shard_store.checkpoint_bound_bundle_path(record)
            records.append(record)
    except ContractValidationError:
        return None
    return tuple(records)


def _selected_export_file_source_local_key(relative_path: str) -> str:
    normalized = _private_relative_export_path(relative_path)
    return "file:" + hashlib.sha256(normalized.encode("utf-8", "strict")).hexdigest()[:24]


def _selected_top_level_message_occurrence_ids(
    bundle: MailEvidenceBundle,
    *,
    selected_paths: Sequence[str],
) -> frozenset[str]:
    if len(bundle.source_inventory) != 1:
        raise ContractValidationError("diagnostic structural shard source inventory is invalid")
    items = _selected_top_level_message_inventory_items(
        bundle.source_inventory[0],
        selected_paths=selected_paths,
    )
    occurrence_ids: set[str] = set()
    for item in items:
        occurrence_id = dict(item.location).get("message_occurrence_id")
        if (
            not isinstance(occurrence_id, str)
            or not occurrence_id
            or occurrence_id in occurrence_ids
        ):
            raise ContractValidationError(
                "diagnostic structural shard top-level source binding is invalid"
            )
        occurrence_ids.add(occurrence_id)
    return frozenset(occurrence_ids)


def _selected_top_level_message_lineage_ids(
    source_inventory: SourceInventory,
    *,
    selected_paths: Sequence[str],
) -> frozenset[str]:
    """Return exactly the selected top-level message lineage keys."""

    return frozenset(
        str(dict(item.location)["source_local_key"])
        for item in _selected_top_level_message_inventory_items(
            source_inventory,
            selected_paths=selected_paths,
        )
    )


def _selected_top_level_message_inventory_items(
    source_inventory: SourceInventory,
    *,
    selected_paths: Sequence[str],
) -> tuple[Any, ...]:
    expected_file_keys = {_selected_export_file_source_local_key(path) for path in selected_paths}
    if len(expected_file_keys) != len(selected_paths):
        raise ContractValidationError("diagnostic structural shard selected paths are invalid")
    top_level_items_by_key = _top_level_exported_message_inventory_items(source_inventory)
    expected_message_keys = {f"{key}:message" for key in expected_file_keys}
    if set(top_level_items_by_key) != expected_message_keys:
        raise ContractValidationError(
            "diagnostic structural shard top-level source coverage is incomplete"
        )
    return tuple(top_level_items_by_key[key] for key in sorted(expected_message_keys))


def _top_level_exported_message_lineage_ids(
    source_inventory: SourceInventory,
) -> frozenset[str]:
    """Return every top-level selected-export message lineage in one bundle."""

    return frozenset(_top_level_exported_message_inventory_items(source_inventory))


def _top_level_exported_message_inventory_items(
    source_inventory: SourceInventory,
) -> dict[str, Any]:
    """Validate and return one parsed top-level message per message source unit."""

    file_items_by_key: dict[str, Any] = {}
    top_level_file_keys: set[str] = set()
    top_level_items_by_key: dict[str, Any] = {}
    for item in source_inventory.items:
        if item.structure_kind not in {
            "exported_file",
            "exported_message_occurrence",
        }:
            continue
        location = dict(item.location)
        source_local_key = location.get("source_local_key")
        if not isinstance(source_local_key, str) or not source_local_key:
            raise ContractValidationError(
                "diagnostic structural shard top-level source binding is invalid"
            )
        if item.structure_kind == "exported_file":
            if source_local_key in file_items_by_key:
                raise ContractValidationError(
                    "diagnostic structural shard source inventory is ambiguous"
                )
            file_items_by_key[source_local_key] = item
            source_unit_kind = location.get("source_unit_kind")
            if source_unit_kind is None:
                # Legacy inventories did not label units.  Preserve their
                # fail-closed message topology requirement rather than
                # guessing that an unlabeled exported file is ancillary.
                top_level_file_keys.add(source_local_key)
            elif source_unit_kind == _PST_SOURCE_UNIT_MESSAGE:
                top_level_file_keys.add(source_local_key)
            elif source_unit_kind in {
                _PST_SOURCE_UNIT_ATTACHMENT,
                _PST_SOURCE_UNIT_SIDECAR,
            }:
                if item.processing_state not in _DIAGNOSTIC_ANCILLARY_PROCESSING_STATES:
                    raise ContractValidationError(
                        "diagnostic structural shard top-level source binding is invalid"
                    )
            else:
                raise ContractValidationError(
                    "diagnostic structural shard top-level source binding is invalid"
                )
        elif item.structure_kind == "exported_message_occurrence":
            if source_local_key in top_level_items_by_key:
                raise ContractValidationError(
                    "diagnostic structural shard source inventory is ambiguous"
                )
            top_level_items_by_key[source_local_key] = item
    expected_message_keys = {f"{key}:message" for key in top_level_file_keys}
    if set(top_level_items_by_key) != expected_message_keys:
        raise ContractValidationError(
            "diagnostic structural shard top-level source coverage is incomplete"
        )
    for file_key in top_level_file_keys:
        file_item = file_items_by_key.get(file_key)
        top_level_item = top_level_items_by_key.get(f"{file_key}:message")
        if file_item is None or top_level_item is None:
            raise ContractValidationError(
                "diagnostic structural shard top-level source coverage is incomplete"
            )
        file_location = dict(file_item.location)
        top_level_location = dict(top_level_item.location)
        source_unit_kind = file_location.get("source_unit_kind")
        if (
            file_item.processing_state != "parsed"
            or file_item.content_type != "message/rfc822"
            or (source_unit_kind is not None and source_unit_kind != _PST_SOURCE_UNIT_MESSAGE)
            or top_level_location.get("parent_source_local_key") != file_key
        ):
            raise ContractValidationError(
                "diagnostic structural shard top-level source binding is invalid"
            )
    return top_level_items_by_key


def _validated_shard_record(
    bundle: MailEvidenceBundle,
    *,
    bundle_path: Path,
    manifest: DiagnosticStructuralScopeManifest,
    ordinal: int,
    selected_paths: Sequence[str],
    scope_authority_verifier: CoverageScopeAuthorityVerifier,
    semantic_profile: DiagnosticSemanticProfile,
    existing_export_verification: DiagnosticExistingExportVerification,
    parser_version: str,
    historical_compatibility: _HistoricalScopeCompatibilityCheckpoint | None,
) -> tuple[DiagnosticStructuralShardRecord, dict[str, int]]:
    _verify_bridge_bundle(
        bundle,
        expected_bundle_id=bundle.mail_evidence_bundle_id,
        scope_authority_verifier=scope_authority_verifier,
        existing_export_verification=existing_export_verification,
        semantic_profile=semantic_profile,
    )
    session = bundle.mail_import_session
    if (
        session.source_asset_id != manifest.source_asset_id
        or session.archive_sha256 != manifest.source_fingerprint
        or session.workspace_id != manifest.workspace_id
        or session.owner_user_id != manifest.owner_user_id
        or session.status != "succeeded"
        or len(bundle.source_inventory) != 1
        or bundle.source_inventory[0].source_asset_id != manifest.source_asset_id
        or bundle.source_inventory[0].source_fingerprint != manifest.source_fingerprint
        or any(
            dict(item.permission_scope) != dict(manifest.permission_scope)
            for item in bundle.source_inventory[0].items
        )
    ):
        raise ContractValidationError("diagnostic structural shard source binding is invalid")
    expected_extractor_run_id = stable_resource_contract_id(
        "extractor",
        "DiagnosticSelectedReadpstExport",
        {
            "source_asset_id": manifest.source_asset_id,
            "source_fingerprint": manifest.source_fingerprint,
            "selected_message_paths": tuple(selected_paths),
            "parser_version": parser_version,
        },
    )
    if bundle.mail_parse_run.extractor_run_id != expected_extractor_run_id:
        raise ContractValidationError("diagnostic structural shard path binding is invalid")
    selected_top_level_occurrence_ids = _selected_top_level_message_occurrence_ids(
        bundle,
        selected_paths=selected_paths,
    )
    materialized_occurrence_ids = {
        item.message_occurrence_id for item in bundle.message_occurrences
    }
    if (
        len(selected_top_level_occurrence_ids) != len(selected_paths)
        or not selected_top_level_occurrence_ids <= materialized_occurrence_ids
    ):
        raise ContractValidationError(
            "diagnostic structural shard top-level message accounting is incomplete"
        )
    embedded_message_occurrence_count = len(bundle.message_occurrences) - len(
        selected_top_level_occurrence_ids
    )
    if historical_compatibility is None and (
        embedded_message_occurrence_count != 0
        or len(bundle.message_occurrences) != len(selected_paths)
    ):
        raise ContractValidationError(
            "diagnostic structural shard message accounting is incomplete"
        )
    if (
        len(bundle.claim_requirements) != 1
        or len(bundle.coverage_ledgers) != 1
        or len(bundle.version_manifests) != 1
    ):
        raise ContractValidationError(
            "diagnostic structural shard semantic authority is incomplete"
        )

    selector_counts = {item.selector_id: 0 for item in manifest.selectors}
    if historical_compatibility is None:
        selector_by_key = {
            (item.message_id, item.folder_path_hash, item.body_hash): item
            for item in manifest.selectors
        }
        message_by_id = {item.email_message_id: item for item in bundle.messages}
        for occurrence in bundle.message_occurrences:
            if occurrence.message_occurrence_id not in selected_top_level_occurrence_ids:
                continue
            message = message_by_id.get(occurrence.email_message_id)
            selector = (
                selector_by_key.get(
                    (
                        occurrence.message_id,
                        occurrence.folder_path_hash,
                        message.body_hash,
                    )
                )
                if message is not None and message.body_hash
                else None
            )
            if selector is None:
                raise ContractValidationError(
                    "diagnostic structural shard contains an unscoped message"
                )
            selector_counts[selector.selector_id] += 1
            if selector_counts[selector.selector_id] > selector.expected_occurrence_count:
                raise ContractValidationError(
                    "diagnostic structural shard selector coverage overlaps"
                )
        selector_coverage_fingerprint = _selector_coverage_fingerprint(
            {selector_id: count for selector_id, count in selector_counts.items() if count}
        )
    else:
        selector_coverage_fingerprint = historical_compatibility.shard_scope_fragment_fingerprint(
            selected_paths
        )
    record = DiagnosticStructuralShardRecord(
        ordinal=ordinal,
        mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
        bundle_fingerprint=sha256_file(bundle_path),
        existing_export_verification_fingerprint=(
            existing_export_verification.verification_fingerprint
        ),
        selected_path_fingerprint=sha256_json(list(selected_paths)),
        selector_coverage_fingerprint=selector_coverage_fingerprint,
        selected_message_count=len(bundle.message_occurrences),
        body_segment_count=len(bundle.body_segments),
        structural_observation_count=len(bundle.structural_observations),
        selected_top_level_message_count=len(selected_top_level_occurrence_ids),
        embedded_message_occurrence_count=embedded_message_occurrence_count,
        historical_compatibility_checkpoint_fingerprint=(
            historical_compatibility.checkpoint_fingerprint
            if historical_compatibility is not None
            else None
        ),
    )
    return record, selector_counts


def _validate_aggregate_manifest_binding(
    aggregate: DiagnosticStructuralAggregateManifest,
    *,
    manifest: DiagnosticStructuralScopeManifest,
    semantic_profile: DiagnosticSemanticProfile,
    shard_batch_size: int,
    path_batches: Sequence[Sequence[str]],
    selected_path_set_fingerprint: str,
    expected_selector_coverage_fingerprint: str,
    existing_export_verification: DiagnosticExistingExportVerification,
    historical_compatibility: _HistoricalScopeCompatibilityCheckpoint | None,
) -> None:
    if (
        aggregate.scope_manifest_id != manifest.scope_manifest_id
        or aggregate.source_asset_id != manifest.source_asset_id
        or aggregate.source_fingerprint != manifest.source_fingerprint
        or aggregate.workspace_id != manifest.workspace_id
        or aggregate.owner_user_id != manifest.owner_user_id
        or aggregate.semantic_profile_fingerprint != semantic_profile.profile_fingerprint
        or aggregate.existing_export_verification != existing_export_verification
        or aggregate.shard_batch_size != shard_batch_size
        or aggregate.selected_path_set_fingerprint != selected_path_set_fingerprint
        or aggregate.selector_coverage_fingerprint != expected_selector_coverage_fingerprint
        or aggregate.expected_message_count != manifest.expected_message_count
        or aggregate.expected_body_segment_count != manifest.expected_body_segment_count
        or aggregate.historical_compatibility_checkpoint_fingerprint
        != (
            historical_compatibility.checkpoint_fingerprint
            if historical_compatibility is not None
            else None
        )
        or aggregate.selected_top_level_message_count
        != len(tuple(path for batch in path_batches for path in batch))
        or len(aggregate.shards) != len(path_batches)
        or any(
            record.selected_top_level_message_count != len(path_batch)
            or record.selected_path_fingerprint != sha256_json(list(path_batch))
            or record.historical_compatibility_checkpoint_fingerprint
            != (
                historical_compatibility.checkpoint_fingerprint
                if historical_compatibility is not None
                else None
            )
            or (
                historical_compatibility is not None
                and record.selector_coverage_fingerprint
                != historical_compatibility.shard_scope_fragment_fingerprint(path_batch)
            )
            or (
                historical_compatibility is None
                and (
                    record.selected_message_count != len(path_batch)
                    or record.embedded_message_occurrence_count != 0
                )
            )
            for record, path_batch in zip(
                aggregate.shards,
                path_batches,
                strict=True,
            )
        )
    ):
        raise ContractValidationError(
            "diagnostic structural aggregate does not match requested scope"
        )


def _grant_sharded_mcp_read_only_access(
    *,
    bridge_dir: Path,
    shard_store: FileDiagnosticStructuralShardStore,
    reader_gid: int,
) -> None:
    if not isinstance(reader_gid, int) or isinstance(reader_gid, bool) or reader_gid < 0:
        raise ContractValidationError("diagnostic bridge reader identity is invalid")
    publisher_uid = os.getuid()
    targets = (
        (bridge_dir, 0o750),
        (shard_store.root, 0o750),
        (shard_store.aggregate_manifest_path, 0o640),
    )
    for path, mode in targets:
        if path.is_symlink() or not path.exists():
            raise ContractValidationError("diagnostic structural aggregate access path is invalid")
        try:
            os.chown(path, publisher_uid, reader_gid)
        except PermissionError:
            existing = path.stat()
            if existing.st_uid != publisher_uid or existing.st_gid != reader_gid:
                raise ContractValidationError(
                    "diagnostic structural aggregate cannot be assigned to the MCP reader"
                ) from None
        os.chmod(path, mode)
        if stat.S_IMODE(path.stat().st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
            raise ContractValidationError("diagnostic structural aggregate is world writable")


def _scope_manifest_id(
    *,
    source_asset_id: str,
    source_fingerprint: str,
    workspace_id: str,
    owner_user_id: str,
    permission_scope: Mapping[str, Any],
    expected_message_count: int,
    expected_body_segment_count: int,
    source_observation_set_fingerprint: str,
    selectors: Sequence[DiagnosticStructuralScopeSelector],
) -> str:
    return stable_resource_contract_id(
        "diagnosticscope",
        "DiagnosticStructuralScopeManifest",
        {
            "source_asset_id": source_asset_id,
            "source_fingerprint": source_fingerprint,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "permission_scope": dict(permission_scope),
            "expected_message_count": expected_message_count,
            "expected_body_segment_count": expected_body_segment_count,
            "source_observation_set_fingerprint": source_observation_set_fingerprint,
            "selectors": [
                item.to_private_dict()
                for item in sorted(selectors, key=lambda item: item.selector_id)
            ],
        },
    )


def _required_private_text(value: Mapping[str, Any], field_name: str) -> str:
    candidate = value.get(field_name)
    if not isinstance(candidate, str) or not candidate:
        raise ContractValidationError(f"diagnostic scope {field_name} is invalid")
    return candidate


def _required_private_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise ContractValidationError(
            f"diagnostic current-export selection checkpoint {field_name} is invalid"
        )
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ContractValidationError(
            f"diagnostic current-export selection checkpoint {field_name} is invalid"
        ) from exc
    return value


def _required_private_text_from_sources(
    primary: Mapping[str, Any],
    fallback: Mapping[str, Any],
    field_name: str,
) -> str:
    candidate = primary.get(field_name)
    if not isinstance(candidate, str) or not candidate:
        candidate = fallback.get(field_name)
    if not isinstance(candidate, str) or not candidate:
        raise ContractValidationError(f"diagnostic scope {field_name} is unavailable")
    return candidate


def _validate_materialization_sources(
    *,
    pst_path: str | Path | None,
    export_root: str | Path | None,
) -> None:
    if (pst_path is None) == (export_root is None):
        raise ContractValidationError(
            "diagnostic materialization requires exactly one PST or existing export source"
        )


def _full_scope_archive_binding_matches(
    manifest: DiagnosticStructuralScopeManifest,
    *,
    source_asset_id: str | None,
    source_fingerprint: str | None,
) -> bool:
    if source_asset_id is None and source_fingerprint is None:
        return False
    if (
        not isinstance(source_asset_id, str)
        or not source_asset_id
        or not isinstance(source_fingerprint, str)
        or not source_fingerprint
    ):
        raise ContractValidationError("diagnostic full-scope archive binding is incomplete")
    if source_asset_id != manifest.source_asset_id:
        raise ContractValidationError("diagnostic full-scope archive asset does not match MAY")
    if source_fingerprint != manifest.source_fingerprint:
        raise ContractValidationError(
            "diagnostic full-scope archive fingerprint does not match MAY"
        )
    return True


def _safe_private_directory(path: Path) -> Path:
    _create_private_directory_if_missing(
        path,
        error_message="diagnostic checkpoint directory is invalid",
    )
    return path


def _create_private_directory_if_missing(path: Path, *, error_message: str) -> bool:
    """Create one private leaf directory without mutating an existing parent."""

    if path.is_symlink():
        raise ContractValidationError(error_message)
    created = False
    try:
        path.mkdir(parents=True, mode=0o700)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise ContractValidationError(error_message) from exc
    if path.is_symlink() or not path.is_dir():
        raise ContractValidationError(error_message)
    if created:
        os.chmod(path, 0o700)
    return created


def _validated_pst_input(path: str | Path) -> tuple[Path, int]:
    """Validate a raw archive reference without traversing its contents."""

    candidate = Path(path)
    try:
        mode = candidate.lstat().st_mode
    except OSError as exc:
        raise ContractValidationError("diagnostic PST input is unavailable") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ContractValidationError("diagnostic PST input is invalid")
    try:
        size = candidate.stat().st_size
    except OSError as exc:
        raise ContractValidationError("diagnostic PST input is unavailable") from exc
    if size < 1:
        raise ContractValidationError("diagnostic PST input is empty")
    return candidate, size


def _is_home_checkpoint_filesystem(path: Path) -> bool:
    """Require raw-PST checkpoints on the host's persistent ``/home`` storage."""

    absolute_path = Path(os.path.abspath(os.fspath(path)))
    home_root = Path("/home")
    try:
        absolute_path.relative_to(home_root)
    except ValueError:
        return False
    try:
        home_mode = home_root.lstat().st_mode
    except OSError:
        return False
    return not stat.S_ISLNK(home_mode) and stat.S_ISDIR(home_mode)


def _available_scratch_disk_bytes(path: Path) -> int:
    """Return available bytes on the filesystem that would hold this checkpoint."""

    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise ContractValidationError("diagnostic scratch directory is unavailable")
        candidate = parent
    if candidate.is_symlink() or not candidate.is_dir():
        raise ContractValidationError("diagnostic scratch directory is invalid")
    try:
        filesystem = os.statvfs(candidate)
    except OSError as exc:
        raise ContractValidationError("diagnostic scratch directory is unavailable") from exc
    available = filesystem.f_frsize * filesystem.f_bavail
    if available < 1:
        raise ContractValidationError("diagnostic scratch disk capacity is unavailable")
    return available


def _safe_existing_export_root(path: Path) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise ContractValidationError("diagnostic readpst export is unavailable")
    return path


def _atomic_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.parent.is_symlink():
        raise ContractValidationError("diagnostic private checkpoint directory is invalid")
    _create_private_directory_if_missing(
        path.parent,
        error_message="diagnostic private checkpoint directory is invalid",
    )
    if path.exists() and path.is_symlink():
        raise ContractValidationError("diagnostic private checkpoint path is invalid")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        encoded = json.dumps(
            dict(payload),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(descriptor, remaining)
            if written < 1:
                raise OSError("diagnostic checkpoint write failed")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _write_all_private_bytes(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written < 1:
            raise OSError("diagnostic private write failed")
        remaining = remaining[written:]


def _load_private_checkpoint(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ContractValidationError("diagnostic checkpoint is invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractValidationError("diagnostic checkpoint is invalid") from exc
    if not isinstance(payload, Mapping):
        raise ContractValidationError("diagnostic checkpoint is invalid")
    return payload


def _checkpoint_matches_export(
    checkpoint: Mapping[str, Any] | None,
    manifest: DiagnosticStructuralScopeManifest,
    pst_path: str | Path,
) -> bool:
    if checkpoint is None:
        return False
    _reject_legacy_checkpoint(checkpoint)
    if checkpoint.get("artifact_type") != _READPST_EXPORT_CHECKPOINT_ARTIFACT_TYPE:
        return False
    if checkpoint.get("scope_manifest_id") != manifest.scope_manifest_id:
        return False
    try:
        source_stat = Path(pst_path).stat()
    except OSError as exc:
        raise ContractValidationError("diagnostic PST input is unavailable") from exc
    return checkpoint.get("source_stat") == _safe_source_stat(source_stat)


def _export_checkpoint_payload(
    manifest: DiagnosticStructuralScopeManifest,
    pst_path: str | Path,
) -> dict[str, Any]:
    try:
        source_stat = Path(pst_path).stat()
    except OSError as exc:
        raise ContractValidationError("diagnostic PST input is unavailable") from exc
    return {
        "artifact_type": _READPST_EXPORT_CHECKPOINT_ARTIFACT_TYPE,
        "scope_manifest_id": manifest.scope_manifest_id,
        "source_fingerprint": manifest.source_fingerprint,
        "source_stat": _safe_source_stat(source_stat),
    }


def _safe_source_stat(source_stat: os.stat_result) -> dict[str, int]:
    return {
        "device": source_stat.st_dev,
        "inode": source_stat.st_ino,
        "size_bytes": source_stat.st_size,
        "mtime_ns": source_stat.st_mtime_ns,
    }


def _checkpoint_matches_selection(
    checkpoint: Mapping[str, Any] | None,
    manifest: DiagnosticStructuralScopeManifest,
) -> bool:
    if checkpoint is None:
        return False
    _reject_legacy_checkpoint(checkpoint)
    if checkpoint.get("artifact_type") != _SELECTION_CHECKPOINT_ARTIFACT_TYPE:
        return False
    if checkpoint.get("scope_manifest_id") != manifest.scope_manifest_id:
        return False
    try:
        selected = _load_selected_paths(checkpoint)
        scanned = _required_checkpoint_integer(checkpoint, "scanned_message_count")
        matched = _required_checkpoint_integer(checkpoint, "matched_occurrence_count")
        selected_message_count = _required_checkpoint_integer(
            checkpoint,
            "selected_message_count",
        )
    except ContractValidationError:
        return False
    return (
        bool(selected)
        and scanned >= len(selected)
        and matched == manifest.expected_message_count
        and selected_message_count == manifest.expected_message_count
    )


def _load_selected_paths(checkpoint: Mapping[str, Any]) -> tuple[str, ...]:
    values = checkpoint.get("selected_message_paths")
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(item, str) or not item for item in values)
    ):
        raise ContractValidationError("diagnostic selection checkpoint paths are invalid")
    if len(values) != len(set(values)):
        raise ContractValidationError("diagnostic selection checkpoint paths are duplicated")
    return tuple(sorted(values))


def _required_checkpoint_integer(checkpoint: Mapping[str, Any] | None, field_name: str) -> int:
    if checkpoint is None:
        raise ContractValidationError("diagnostic checkpoint is unavailable")
    value = checkpoint.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractValidationError("diagnostic checkpoint count is invalid")
    return value


def _validate_checkpoint_manifest(
    checkpoint: Mapping[str, Any] | None,
    manifest: DiagnosticStructuralScopeManifest,
    *,
    historical_compatibility_checkpoint_fingerprint: str | None = None,
) -> None:
    if checkpoint is None:
        return
    _reject_legacy_checkpoint(checkpoint)
    if checkpoint.get("scope_manifest_id") != manifest.scope_manifest_id:
        raise ContractValidationError("diagnostic checkpoint belongs to another source scope")
    if checkpoint.get("historical_compatibility_checkpoint_fingerprint") != (
        historical_compatibility_checkpoint_fingerprint
    ):
        raise ContractValidationError("diagnostic checkpoint compatibility binding is invalid")


def _reject_legacy_checkpoint(checkpoint: Mapping[str, Any]) -> None:
    if checkpoint.get("artifact_type") in _LEGACY_CHECKPOINT_ARTIFACT_TYPES:
        raise ContractValidationError("diagnostic legacy checkpoint cannot be reused")


def _materialization_state_payload(
    manifest: DiagnosticStructuralScopeManifest,
    *,
    state: str,
    scanned_message_count: int,
    selected_export_message_count: int,
    pst_scan_count: int,
    mail_evidence_bundle_id: str | None = None,
    existing_export_verification: DiagnosticExistingExportVerification | None = None,
    historical_compatibility_checkpoint_fingerprint: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_type": _MATERIALIZATION_STATE_ARTIFACT_TYPE,
        "scope_manifest_id": manifest.scope_manifest_id,
        "state": state,
        "scanned_message_count": scanned_message_count,
        "selected_export_message_count": selected_export_message_count,
        "pst_scan_count": pst_scan_count,
    }
    if mail_evidence_bundle_id is not None:
        payload["mail_evidence_bundle_id"] = mail_evidence_bundle_id
    if existing_export_verification is not None:
        payload["existing_export_verification"] = existing_export_verification.to_safe_dict()
    if historical_compatibility_checkpoint_fingerprint is not None:
        payload["historical_compatibility_checkpoint_fingerprint"] = (
            historical_compatibility_checkpoint_fingerprint
        )
    return payload


def _validate_materialized_scope(
    bundle: MailEvidenceBundle,
    manifest: DiagnosticStructuralScopeManifest,
) -> None:
    if bundle.mail_import_session.source_asset_id != manifest.source_asset_id:
        raise ContractValidationError("materialized bundle source asset is invalid")
    if bundle.mail_import_session.archive_sha256 != manifest.source_fingerprint:
        raise ContractValidationError("materialized bundle source fingerprint is invalid")
    message_by_id = {item.email_message_id: item for item in bundle.messages}
    selector_counts: dict[str, int] = {item.selector_id: 0 for item in manifest.selectors}
    selector_by_key = {
        (item.message_id, item.folder_path_hash, item.body_hash): item
        for item in manifest.selectors
    }
    for occurrence in bundle.message_occurrences:
        message = message_by_id.get(occurrence.email_message_id)
        if message is None or not message.body_hash:
            raise ContractValidationError("materialized bundle message binding is invalid")
        selector = selector_by_key.get(
            (occurrence.message_id, occurrence.folder_path_hash, message.body_hash)
        )
        if selector is None:
            raise ContractValidationError("materialized bundle contains an unscoped message")
        selector_counts[selector.selector_id] += 1
    if len(bundle.message_occurrences) != manifest.expected_message_count:
        raise ContractValidationError("materialized bundle message count is incomplete")
    if len(bundle.body_segments) != manifest.expected_body_segment_count:
        raise ContractValidationError("materialized bundle body segment count is incomplete")
    for selector in manifest.selectors:
        if selector_counts[selector.selector_id] != selector.expected_occurrence_count:
            raise ContractValidationError("materialized bundle selector coverage is incomplete")
    if not bundle.source_inventory or not bundle.structural_observations:
        raise ContractValidationError("materialized bundle structural evidence is incomplete")


def _verify_operator_bound_existing_export(
    *,
    export_root: str | Path,
    selected_message_paths: Sequence[str | Path],
    scanned_message_count: int,
    matched_occurrence_count: int,
    manifest: DiagnosticStructuralScopeManifest,
    full_scope_source_asset_id: str | None,
    full_scope_source_fingerprint: str | None,
    historical_compatibility: _HistoricalScopeCompatibilityCheckpoint | None = None,
) -> DiagnosticExistingExportVerification:
    """Stream one existing export into a path-free complete-scope proof.

    The traversal retains only the selected relative-path set and fixed-size
    digest state. It never constructs a whole-export message, observation, or
    inventory payload. Every filesystem leaf must be a regular file. Ordinary
    selection requires every currently classified message to be selected. A
    historical compatibility checkpoint permits extra current messages only
    after they were traversal-hashed and explicitly excluded from historical
    scope accounting.
    """

    if not isinstance(manifest, DiagnosticStructuralScopeManifest):
        raise ContractValidationError("diagnostic existing-export scope is invalid")
    if not _full_scope_archive_binding_matches(
        manifest,
        source_asset_id=full_scope_source_asset_id,
        source_fingerprint=full_scope_source_fingerprint,
    ):
        raise ContractValidationError("diagnostic existing-export binding is invalid")
    for field_name, value in (
        ("scanned message count", scanned_message_count),
        ("matched occurrence count", matched_occurrence_count),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ContractValidationError(f"diagnostic existing-export {field_name} is invalid")

    root = _safe_existing_export_root(Path(os.path.abspath(os.fspath(export_root))))
    selected_paths = _normalized_selected_paths(
        export_root=root,
        selected_message_paths=selected_message_paths,
    )
    if len(selected_paths) != len(selected_message_paths):
        raise ContractValidationError("diagnostic existing-export selected paths are duplicated")
    remaining_selected_paths = set(selected_paths)
    traversal_digest = hashlib.sha256()
    export_file_count = 0
    export_message_file_count = 0
    parsed_export_message_count = 0

    def fail_walk(error: OSError) -> None:
        raise error

    try:
        for current_root, directory_names, file_names in os.walk(
            root,
            topdown=True,
            onerror=fail_walk,
            followlinks=False,
        ):
            directory_names.sort(key=os.fsencode)
            file_names.sort(key=os.fsencode)
            current = Path(current_root)
            for directory_name in directory_names:
                directory = current / directory_name
                mode = directory.lstat().st_mode
                if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                    raise ContractValidationError(
                        "diagnostic existing-export traversal is incomplete"
                    )
            for file_name in file_names:
                candidate = current / file_name
                relative_path = candidate.relative_to(root).as_posix()
                source_size, source_content_fingerprint = _hash_existing_export_regular_file(
                    candidate
                )
                source_unit_kind = _source_unit_kind_for_path(candidate)
                export_file_count += 1
                if source_unit_kind == _PST_SOURCE_UNIT_MESSAGE:
                    export_message_file_count += 1
                    if relative_path in remaining_selected_paths:
                        remaining_selected_paths.remove(relative_path)
                        parsed_export_message_count += 1
                _update_existing_export_traversal_digest(
                    traversal_digest,
                    {
                        "ordinal": export_file_count,
                        "relative_path_fingerprint": (
                            "sha256:" + hashlib.sha256(os.fsencode(relative_path)).hexdigest()
                        ),
                        "source_unit_kind": source_unit_kind,
                        "source_size_bytes": source_size,
                        "source_content_fingerprint": (source_content_fingerprint),
                    },
                )
    except ContractValidationError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractValidationError("diagnostic existing-export traversal is incomplete") from exc

    if export_file_count < 1:
        raise ContractValidationError("diagnostic existing-export traversal is incomplete")
    nonparsed_export_message_count = export_message_file_count - parsed_export_message_count
    ordinary_selection = historical_compatibility is None
    if (
        remaining_selected_paths
        or matched_occurrence_count != manifest.expected_message_count
        or parsed_export_message_count != len(selected_paths)
        or (
            ordinary_selection
            and (
                scanned_message_count != export_message_file_count
                or parsed_export_message_count != manifest.expected_message_count
                or nonparsed_export_message_count != 0
            )
        )
        or (
            not ordinary_selection
            and (
                selected_paths != historical_compatibility.selected_paths
                or scanned_message_count != historical_compatibility.selected_path_count
                or matched_occurrence_count != historical_compatibility.matched_occurrence_count
            )
        )
    ):
        raise ContractValidationError("diagnostic existing-export message accounting is incomplete")

    operator_scope_binding_fingerprint = sha256_json(
        {
            "scope_manifest_id": manifest.scope_manifest_id,
            "source_asset_id": full_scope_source_asset_id,
            "source_fingerprint": full_scope_source_fingerprint,
        }
    )
    raw_byte_export_traversal_fingerprint = f"sha256:{traversal_digest.hexdigest()}"
    source_inventory_id = stable_resource_contract_id(
        "diagnosticinventory",
        "DiagnosticExistingExportInventory",
        {
            "scope_manifest_id": manifest.scope_manifest_id,
            "operator_scope_binding_fingerprint": (operator_scope_binding_fingerprint),
            "raw_byte_export_traversal_fingerprint": (raw_byte_export_traversal_fingerprint),
            "export_file_count": export_file_count,
            "export_message_file_count": export_message_file_count,
        },
    )
    return DiagnosticExistingExportVerification.create(
        scope_manifest_id=manifest.scope_manifest_id,
        source_inventory_id=source_inventory_id,
        operator_scope_binding_fingerprint=operator_scope_binding_fingerprint,
        raw_byte_export_traversal_fingerprint=(raw_byte_export_traversal_fingerprint),
        export_file_count=export_file_count,
        export_message_file_count=export_message_file_count,
        parsed_export_message_count=parsed_export_message_count,
        nonparsed_export_message_count=nonparsed_export_message_count,
        matched_message_occurrence_count=matched_occurrence_count,
        historical_compatibility_checkpoint_fingerprint=(
            historical_compatibility.checkpoint_fingerprint
            if historical_compatibility is not None
            else None
        ),
    )


def _hash_existing_export_regular_file(candidate: Path) -> tuple[int, str]:
    try:
        path_metadata = candidate.lstat()
    except OSError as exc:
        raise ContractValidationError(
            "diagnostic existing-export raw-byte traversal is incomplete"
        ) from exc
    if stat.S_ISLNK(path_metadata.st_mode) or not stat.S_ISREG(path_metadata.st_mode):
        raise ContractValidationError("diagnostic existing-export traversal is incomplete")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(candidate, flags)
        opened_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(opened_metadata.st_mode) or _stable_file_identity(
            opened_metadata
        ) != _stable_file_identity(path_metadata):
            raise ContractValidationError(
                "diagnostic existing-export raw-byte traversal is incomplete"
            )
        digest = hashlib.sha256()
        byte_count = 0
        while chunk := os.read(descriptor, _EXISTING_EXPORT_READ_BUFFER_BYTES):
            byte_count += len(chunk)
            digest.update(chunk)
        final_metadata = os.fstat(descriptor)
    except ContractValidationError:
        raise
    except OSError as exc:
        raise ContractValidationError(
            "diagnostic existing-export raw-byte traversal is incomplete"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

    try:
        final_path_metadata = candidate.lstat()
    except OSError as exc:
        raise ContractValidationError(
            "diagnostic existing-export raw-byte traversal is incomplete"
        ) from exc
    if (
        byte_count != opened_metadata.st_size
        or _stable_file_identity(final_metadata) != _stable_file_identity(opened_metadata)
        or _stable_file_identity(final_path_metadata) != _stable_file_identity(opened_metadata)
    ):
        raise ContractValidationError("diagnostic existing-export raw-byte traversal is incomplete")
    return byte_count, f"sha256:{digest.hexdigest()}"


def _stable_file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _update_existing_export_traversal_digest(
    digest: Any,
    row: Mapping[str, Any],
) -> None:
    if not callable(getattr(digest, "update", None)):
        raise ContractValidationError("diagnostic existing-export traversal digest is invalid")
    encoded = json.dumps(
        dict(row),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _grant_mcp_read_only_access(
    *,
    bridge_dir: Path,
    bundle_path: Path,
    reader_uid: int,
    reader_gid: int,
) -> None:
    if (
        not isinstance(reader_uid, int)
        or isinstance(reader_uid, bool)
        or reader_uid < 0
        or not isinstance(reader_gid, int)
        or isinstance(reader_gid, bool)
        or reader_gid < 0
    ):
        raise ContractValidationError("diagnostic bridge reader identity is invalid")
    publisher_uid = os.getuid()
    targets = (
        (bridge_dir, 0o750),
        (bridge_dir / "mail-evidence", 0o750),
        (bridge_dir / "mail-evidence" / "canonical-bundles.private", 0o750),
        (bundle_path, 0o640),
    )
    for path, mode in targets:
        if path.is_symlink() or not path.exists():
            raise ContractValidationError("diagnostic bridge access path is invalid")
        try:
            # MCP receives group read access only. Making it the owner would
            # leave the reader able to mutate the bundle or relax permissions.
            os.chown(path, publisher_uid, reader_gid)
        except PermissionError:
            existing = path.stat()
            if existing.st_uid != publisher_uid or existing.st_gid != reader_gid:
                raise ContractValidationError(
                    "diagnostic bridge output cannot be assigned to the MCP reader"
                ) from None
        os.chmod(path, mode)
        current_mode = stat.S_IMODE(path.stat().st_mode)
        if current_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ContractValidationError("diagnostic bridge output is world writable")
    bundle_stat = bundle_path.stat()
    if bundle_stat.st_uid != publisher_uid or bundle_stat.st_gid != reader_gid:
        raise ContractValidationError("diagnostic bridge bundle reader ownership is invalid")
    if not bundle_stat.st_mode & stat.S_IRGRP:
        raise ContractValidationError("diagnostic bridge bundle is not readable")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
