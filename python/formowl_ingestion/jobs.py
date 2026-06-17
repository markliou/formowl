"""Ingestion job orchestration helpers for deterministic local workflows."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from formowl_contract import Asset, IngestionJob, now_iso, stable_ingestion_job_id

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
) -> IngestionJob:
    """Create a pending ingestion job for a registered asset."""

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
    return job_store.create(job)


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

    adapters = _adapters_by_name(extractor_adapters)
    extractor_run_ids: list[str] = []
    observation_ids: list[str] = []

    try:
        for extractor_name in running_job.extractor_names:
            adapter = adapters.get(extractor_name)
            if adapter is None:
                raise ValueError(f"extractor adapter was not provided: {extractor_name}")

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
            observation_ids.extend(
                observation.observation_id for observation in stored.observations
            )
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
    except Exception as exc:
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
        names = [str(name) for name in extractor_names]
    else:
        names = [adapter.name() for adapter in extractor_adapters or []]
    if not names:
        raise ValueError("at least one extractor name is required")
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


__all__ = [
    "create_ingestion_job",
    "run_ingestion_job",
]
