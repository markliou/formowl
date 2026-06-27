from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from formowl_contract import (
    Asset,
    ContractValidationError,
    ExtractorRun,
    Observation,
    now_iso,
    stable_extractor_run_id,
    stable_resource_contract_hash,
    to_plain,
)

from .storage import ExtractorRunStore, FileObjectStore, ObservationStore


@dataclass(frozen=True)
class ExtractionInput:
    """Internal extractor input resolved from a registered FormOwl asset."""

    asset: Asset
    object_path: Path
    extractor_run_id: str
    config: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    observations: list[Observation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StoredExtractionResult:
    extractor_run: ExtractorRun
    observations: list[Observation] = field(default_factory=list)


@runtime_checkable
class ExtractorAdapter(Protocol):
    def name(self) -> str: ...

    def version(self) -> str: ...

    def supported_mime_types(self) -> list[str]: ...

    def extractor_type(self) -> str: ...

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult: ...


def extraction_config_hash(config: Mapping[str, Any] | None = None) -> str:
    return stable_resource_contract_hash("ExtractionConfig", dict(config or {}))


def run_extractor(
    *,
    asset: Asset,
    object_store: FileObjectStore,
    extractor_run_store: ExtractorRunStore,
    observation_store: ObservationStore,
    adapter: ExtractorAdapter,
    config: Mapping[str, Any] | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> StoredExtractionResult:
    # Caller-supplied extraction timestamps become run provenance, so reject
    # malformed explicit values before object verification or persistence.
    _validate_optional_timestamp("ExtractorRun.started_at", started_at)
    _validate_optional_timestamp("ExtractorRun.completed_at", completed_at)
    if not _supports_mime_type(asset.mime_type, adapter.supported_mime_types()):
        raise ValueError(f"{adapter.name()} does not support asset MIME type {asset.mime_type!r}")

    object_path = object_store.resolve_object_path(asset.object_uri)
    if object_path is None or not object_store.verify_object(
        asset.object_uri,
        expected_content_hash=asset.content_hash,
    ):
        raise FileNotFoundError(
            f"asset object is not readable or failed verification: {asset.asset_id}"
        )

    normalized_config = to_plain(dict(config or {}))
    config_hash = extraction_config_hash(normalized_config)
    run_id = stable_extractor_run_id(
        asset_id=asset.asset_id,
        extractor_name=adapter.name(),
        extractor_version=adapter.version(),
        extractor_type=adapter.extractor_type(),
        input_hash=asset.content_hash,
        config_hash=config_hash,
    )
    run_started_at = started_at or now_iso()
    extraction_input = ExtractionInput(
        asset=asset,
        object_path=object_path,
        extractor_run_id=run_id,
        config=normalized_config,
        created_at=run_started_at,
    )

    try:
        result = adapter.extract(extraction_input)
        status = "failed" if result.errors else "succeeded"
        persisted_observations = (
            _validate_observations(
                result.observations,
                asset=asset,
                extractor_run_id=run_id,
                observation_store=observation_store,
            )
            if status == "succeeded"
            else []
        )
        run = ExtractorRun(
            extractor_run_id=run_id,
            asset_id=asset.asset_id,
            extractor_name=adapter.name(),
            extractor_version=adapter.version(),
            extractor_type=adapter.extractor_type(),
            input_hash=asset.content_hash,
            config_hash=config_hash,
            status=status,
            started_at=run_started_at,
            completed_at=completed_at or now_iso(),
            warnings=list(result.warnings),
            errors=list(result.errors),
        )
        extractor_run_store.create(run)
        if status == "succeeded":
            for observation in persisted_observations:
                observation_store.create(observation)
        return StoredExtractionResult(
            extractor_run=run,
            observations=persisted_observations,
        )
    except Exception as exc:
        failed_run = ExtractorRun(
            extractor_run_id=run_id,
            asset_id=asset.asset_id,
            extractor_name=adapter.name(),
            extractor_version=adapter.version(),
            extractor_type=adapter.extractor_type(),
            input_hash=asset.content_hash,
            config_hash=config_hash,
            status="failed",
            started_at=run_started_at,
            completed_at=completed_at or now_iso(),
            errors=[str(exc)],
        )
        extractor_run_store.create(failed_run)
        raise


def _validate_observations(
    observations: list[Observation],
    *,
    asset: Asset,
    extractor_run_id: str,
    observation_store: ObservationStore,
) -> list[Observation]:
    # Validate every observation and its storage id before any write so a bad
    # later record cannot leave earlier records orphaned in the observation store.
    validated_observations = [
        Observation.from_dict(observation.to_dict()) for observation in observations
    ]
    for observation in validated_observations:
        observation_store.validate_observation_id(observation.observation_id)
        if observation.asset_id != asset.asset_id:
            raise ContractValidationError("Observation.asset_id must match extraction asset_id")
        if observation.extractor_run_id != extractor_run_id:
            raise ContractValidationError(
                "Observation.extractor_run_id must match extraction run id"
            )
        if to_plain(observation.permission_scope) != to_plain(asset.permission_scope):
            raise ContractValidationError(
                "Observation.permission_scope must match extraction asset permission_scope"
            )
    return validated_observations


def _supports_mime_type(mime_type: str, supported_mime_types: list[str]) -> bool:
    for supported in supported_mime_types:
        if supported == "*/*" or supported == mime_type:
            return True
        # Technical metadata adapters can declare family-wide support without
        # enumerating every MIME type that may appear in tests or imports.
        if supported.endswith("/*") and mime_type.startswith(supported.removesuffix("*")):
            return True
    return False


def _validate_optional_timestamp(field_name: str, value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    if value is not None:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractValidationError(f"{field_name} must be an ISO timestamp") from exc


__all__ = [
    "ExtractionInput",
    "ExtractionResult",
    "ExtractorAdapter",
    "StoredExtractionResult",
    "extraction_config_hash",
    "run_extractor",
]
