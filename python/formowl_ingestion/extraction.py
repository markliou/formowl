from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Protocol, runtime_checkable

from formowl_contract import (
    Asset,
    ContractValidationError,
    ExtractorRun,
    Observation,
    SourceRef,
    now_iso,
    stable_asset_id,
    stable_extractor_run_id,
    stable_resource_contract_hash,
    to_plain,
)

from .assets import register_asset_from_local_file
from .storage import (
    AssetRecordStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
)


@dataclass
class AttachmentMaterializationContext:
    """Small internal receipt set for governed attachment child assets."""

    parent_asset: Asset
    asset_store: AssetRecordStore
    object_store: FileObjectStore
    _receipts: list[tuple[str, str, str, bool]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )
    _closed: bool = field(default=False, init=False, repr=False)

    def materialize(
        self,
        *,
        content: bytes,
        expected_content_hash: str,
        mime_type: str,
        source_ref: SourceRef,
    ) -> str:
        if self._closed:
            raise RuntimeError("attachment materialization context is closed")
        object_uri = self.object_store.object_uri_for_content(
            storage_backend_id=self.parent_asset.storage_backend_id,
            workspace_id=self.parent_asset.workspace_id,
            content_hash=expected_content_hash,
        )
        object_preexisted = self.object_store.get_object(object_uri) is not None
        child_asset_id = stable_asset_id(
            storage_backend_id=self.parent_asset.storage_backend_id,
            object_uri=object_uri,
            content_hash=expected_content_hash,
            workspace_id=self.parent_asset.workspace_id,
            source_ref=source_ref,
        )
        if self.asset_store.get(child_asset_id) is not None:
            raise ContractValidationError("attachment child asset is already registered")
        with tempfile.NamedTemporaryFile(prefix="formowl-attachment-", suffix=".bin") as temporary:
            temporary.write(content)
            temporary.flush()
            try:
                child_asset = register_asset_from_local_file(
                    temporary.name,
                    object_store=self.object_store,
                    asset_store=self.asset_store,
                    storage_backend_id=self.parent_asset.storage_backend_id,
                    workspace_id=self.parent_asset.workspace_id,
                    owner_user_id=self.parent_asset.owner_user_id,
                    permission_scope=self.parent_asset.permission_scope,
                    source_ref=source_ref,
                    mime_type=mime_type,
                    expected_content_hash=expected_content_hash,
                    project_id=self.parent_asset.project_id,
                    created_at=self.parent_asset.created_at,
                    registered_at=self.parent_asset.registered_at,
                )
            except Exception:
                if not object_preexisted:
                    self.object_store.delete_object(object_uri)
                raise
        self._receipts.append(
            (
                child_asset.asset_id,
                child_asset.object_uri,
                child_asset.content_hash,
                object_preexisted,
            )
        )
        return child_asset.asset_id

    def validate_observations(self, observations: list[Observation]) -> None:
        expected = {(receipt[0], receipt[2]) for receipt in self._receipts}
        actual = [
            (
                str(payload.get("child_asset_id") or ""),
                str(payload.get("content_hash") or ""),
            )
            for observation in observations
            if observation.observation_type == "email_attachment_occurrence"
            and (payload := observation.payload or {}).get("child_asset_id")
        ]
        if set(actual) != expected or len(actual) != len(expected):
            raise ContractValidationError("attachment child asset observation binding mismatch")

@dataclass(frozen=True)
class ExtractionInput:
    """Internal extractor input resolved from a registered FormOwl asset."""

    asset: Asset
    object_path: Path
    extractor_run_id: str
    config: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    attachment_materialization: AttachmentMaterializationContext | None = None


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
    attachment_asset_store: AssetRecordStore | None = None,
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
    attachment_materialization = None
    if attachment_asset_store is not None:
        if not callable(getattr(attachment_asset_store, "delete", None)):
            raise TypeError("attachment materialization requires deletion-capable asset store")
        parent_asset = attachment_asset_store.get(asset.asset_id)
        if parent_asset is None or parent_asset.to_dict() != asset.to_dict():
            raise ContractValidationError(
                "attachment asset store is not bound to extraction asset"
            )
        attachment_materialization = AttachmentMaterializationContext(
            parent_asset=asset,
            asset_store=attachment_asset_store,
            object_store=object_store,
        )
    extraction_input = ExtractionInput(
        asset=asset,
        object_path=object_path,
        extractor_run_id=run_id,
        config=normalized_config,
        created_at=run_started_at,
        attachment_materialization=attachment_materialization,
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
        if attachment_materialization is not None:
            if status == "succeeded":
                attachment_materialization.validate_observations(
                    persisted_observations
                )
            else:
                _rollback_attachment_materialization(attachment_materialization)
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
            if attachment_materialization is not None:
                attachment_materialization._receipts.clear()
                attachment_materialization._closed = True
        return StoredExtractionResult(
            extractor_run=run,
            observations=persisted_observations,
        )
    except Exception as exc:
        if attachment_materialization is not None and not attachment_materialization._closed:
            _rollback_attachment_materialization(attachment_materialization)
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
            errors=[_safe_extractor_error(exc)],
        )
        extractor_run_store.create(failed_run)
        raise


def _rollback_attachment_materialization(
    context: AttachmentMaterializationContext,
) -> None:
    failed = False
    for asset_id, object_uri, _, object_preexisted in reversed(context._receipts):
        try:
            context.asset_store.delete(asset_id)
            if not object_preexisted:
                context.object_store.delete_object(object_uri)
        except Exception:
            failed = True
    context._receipts.clear()
    context._closed = True
    if failed:
        raise RuntimeError("attachment materialization rollback failed")


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


def _safe_extractor_error(exc: Exception) -> str:
    text = str(exc)
    if _looks_like_raw_diagnostic(text):
        return exc.__class__.__name__
    return text or exc.__class__.__name__


def _looks_like_raw_diagnostic(value: str) -> bool:
    lowered = value.lower()
    return bool(
        re.search(r"(^|[\s'\"([{=,:;])(/|[a-z]:[\\/]|\\\\)", value, re.IGNORECASE)
        or "formowl://object" in lowered
        or "payload.bin" in lowered
        or "traceback" in lowered
        or re.search(r"\b(select\s+.+\s+from|insert\s+into|update\s+\w+\s+set)\b", lowered)
    )


__all__ = [
    "AttachmentMaterializationContext",
    "ExtractionInput",
    "ExtractionResult",
    "ExtractorAdapter",
    "StoredExtractionResult",
    "extraction_config_hash",
    "run_extractor",
]
