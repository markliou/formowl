"""Ingestion job orchestration helpers for deterministic local workflows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Mapping, Sequence

from formowl_contract import (
    Asset,
    ContractValidationError,
    IngestionJob,
    now_iso,
    stable_extractor_run_id,
    stable_ingestion_job_id,
)
from formowl_auth.audit import FileAuditLogStore, record_ingestion_job_creation

from .extraction import ExtractorAdapter, extraction_config_hash, run_extractor
from .storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
)


def create_ingestion_job(
    *,
    asset: Asset,
    job_store: JobStore,
    requested_by: str,
    extractor_adapters: Sequence[ExtractorAdapter] | None = None,
    extractor_names: Sequence[str] | None = None,
    config: Mapping[str, Any] | None = None,
    created_at: str | None = None,
    audit_store: FileAuditLogStore | None = None,
    actor_user_id: str | None = None,
    session_id: str | None = None,
) -> IngestionJob:
    """Create a pending ingestion job for a registered asset."""

    audit_identity = None
    if audit_store is not None:
        # Audit-bound calls must validate actor/session context before the job
        # record is written.
        audit_identity = _require_audit_identity(
            actor_user_id=actor_user_id,
            session_id=session_id,
        )
    _validate_optional_timestamp("IngestionJob.created_at", created_at)
    names = _extractor_names(extractor_adapters=extractor_adapters, extractor_names=extractor_names)
    config_hash = extraction_config_hash(config)
    job = IngestionJob(
        ingestion_job_id=stable_ingestion_job_id(
            asset_id=asset.asset_id,
            requested_by=requested_by,
            workspace_id=asset.workspace_id,
            extractor_names=names,
            config_hash=config_hash,
        ),
        asset_id=asset.asset_id,
        status="pending",
        requested_by=requested_by,
        workspace_id=asset.workspace_id,
        permission_scope=asset.permission_scope,
        created_at=created_at or now_iso(),
        extractor_names=names,
    )
    created_job = job_store.create(job)
    # Job creation audit is optional only for trusted internal helpers; gateway
    # and upload-session flows should provide actor/session context.
    if audit_store is not None and audit_identity is not None:
        record_ingestion_job_creation(
            audit_store,
            actor_user_id=audit_identity[0],
            ingestion_job_id=created_job.ingestion_job_id,
            workspace_id=created_job.workspace_id,
            session_id=audit_identity[1],
            timestamp=created_job.created_at,
        )
    return created_job


def run_ingestion_job(
    *,
    ingestion_job_id: str,
    asset_store: AssetStore,
    job_store: JobStore,
    object_store: FileObjectStore,
    extractor_run_store: ExtractorRunStore,
    observation_store: ObservationStore,
    extractor_adapters: Sequence[ExtractorAdapter],
    config: Mapping[str, Any] | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> IngestionJob:
    """Run a pending local ingestion job through deterministic extractors."""

    job = job_store.get(ingestion_job_id)
    if job is None:
        raise KeyError(f"ingestion job was not found: {ingestion_job_id}")
    if job.status != "pending":
        raise ValueError(f"ingestion job must be pending before it can run: {ingestion_job_id}")
    # Caller-supplied timestamps are part of persisted lineage, so reject
    # malformed values before the job can be moved into running state.
    _validate_optional_timestamp("IngestionJob.started_at", started_at)
    _validate_optional_timestamp("IngestionJob.completed_at", completed_at)
    adapters = _adapters_by_name(extractor_adapters)

    run_started_at = started_at or now_iso()
    running_job = job_store.create(
        replace(
            job,
            status="running",
            started_at=run_started_at,
            completed_at=None,
            error=None,
        )
    )

    asset = asset_store.get(running_job.asset_id)
    if asset is None:
        return _finish_job(
            job_store,
            running_job,
            status="failed",
            completed_at=completed_at,
            error=f"asset was not found: {running_job.asset_id}",
        )

    extractor_run_ids: list[str] = []
    observation_ids: list[str] = []

    try:
        expected_run_id: str | None = None
        for extractor_name in running_job.extractor_names:
            adapter = adapters.get(extractor_name)
            if adapter is None:
                raise ValueError(f"extractor adapter was not provided: {extractor_name}")
            expected_run_id = _expected_extractor_run_id(
                asset=asset,
                adapter=adapter,
                config=config,
            )

            stored = run_extractor(
                asset=asset,
                object_store=object_store,
                extractor_run_store=extractor_run_store,
                observation_store=observation_store,
                adapter=adapter,
                config=config,
                started_at=run_started_at,
                completed_at=completed_at,
            )
            extractor_run_ids.append(stored.extractor_run.extractor_run_id)
            if stored.extractor_run.status != "succeeded":
                return _finish_job(
                    job_store,
                    running_job,
                    status="failed",
                    extractor_run_ids=extractor_run_ids,
                    observation_ids=observation_ids,
                    completed_at=completed_at,
                    error=_run_error(stored.extractor_run.errors, extractor_name),
                )
            # Failed extractor results do not persist observations, so only
            # successful runs may contribute observation lineage to the job.
            observation_ids.extend(
                observation.observation_id for observation in stored.observations
            )
    except Exception as exc:
        # run_extractor records failed runs for adapter exceptions before
        # raising. Preserve that run lineage on the failed job when it exists.
        if expected_run_id is not None:
            failed_run = extractor_run_store.get(expected_run_id)
            if failed_run is not None and expected_run_id not in extractor_run_ids:
                extractor_run_ids.append(expected_run_id)
        return _finish_job(
            job_store,
            running_job,
            status="failed",
            extractor_run_ids=extractor_run_ids,
            observation_ids=observation_ids,
            completed_at=completed_at,
            error=str(exc),
        )

    return _finish_job(
        job_store,
        running_job,
        status="succeeded",
        extractor_run_ids=extractor_run_ids,
        observation_ids=observation_ids,
        completed_at=completed_at,
    )


def _extractor_names(
    *,
    extractor_adapters: Sequence[ExtractorAdapter] | None,
    extractor_names: Sequence[str] | None,
) -> list[str]:
    if extractor_names is not None:
        if isinstance(extractor_names, (str, bytes)):
            raise ValueError("extractor names must be a sequence of non-empty strings")
        names = list(extractor_names)
    else:
        names = [adapter.name() for adapter in extractor_adapters or []]
    if not names:
        raise ValueError("at least one extractor name is required")
    if not all(isinstance(name, str) and name for name in names):
        raise ValueError("extractor names must be non-empty strings")
    if len(set(names)) != len(names):
        raise ValueError("extractor names must be unique")
    return names


def _adapters_by_name(adapters: Sequence[ExtractorAdapter]) -> dict[str, ExtractorAdapter]:
    by_name: dict[str, ExtractorAdapter] = {}
    for adapter in adapters:
        name = adapter.name()
        if name in by_name:
            raise ValueError(f"duplicate extractor adapter name: {name}")
        by_name[name] = adapter
    return by_name


def _finish_job(
    job_store: JobStore,
    job: IngestionJob,
    *,
    status: str,
    extractor_run_ids: list[str] | None = None,
    observation_ids: list[str] | None = None,
    completed_at: str | None = None,
    error: str | None = None,
) -> IngestionJob:
    return job_store.create(
        replace(
            job,
            status=status,  # type: ignore[arg-type]
            extractor_run_ids=extractor_run_ids or [],
            observation_ids=observation_ids or [],
            completed_at=completed_at or now_iso(),
            error=error,
        )
    )


def _run_error(errors: list[str], extractor_name: str) -> str:
    if errors:
        return "; ".join(errors)
    return f"extractor failed: {extractor_name}"


def _expected_extractor_run_id(
    *,
    asset: Asset,
    adapter: ExtractorAdapter,
    config: Mapping[str, Any] | None,
) -> str:
    return stable_extractor_run_id(
        asset_id=asset.asset_id,
        extractor_name=adapter.name(),
        extractor_version=adapter.version(),
        extractor_type=adapter.extractor_type(),
        input_hash=asset.content_hash,
        config_hash=extraction_config_hash(config),
    )


def _validate_optional_timestamp(field_name: str, value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    if value is not None:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractValidationError(
                f"{field_name} must be an ISO timestamp"
            ) from exc


def _require_audit_identity(
    *,
    actor_user_id: str | None,
    session_id: str | None,
) -> tuple[str, str]:
    if (
        not isinstance(actor_user_id, str)
        or not actor_user_id
        or not isinstance(session_id, str)
        or not session_id
    ):
        raise ValueError("actor_user_id and session_id are required when audit_store is provided")
    return actor_user_id, session_id


__all__ = [
    "create_ingestion_job",
    "run_ingestion_job",
]
