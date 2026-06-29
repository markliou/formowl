from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from formowl_contract import IngestionJob, to_plain
from formowl_ingestion.extraction import ExtractorAdapter
from formowl_ingestion.jobs import run_ingestion_job
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    JobStore,
    ObservationStore,
)


@dataclass(frozen=True)
class IngestionWorkerResult:
    worker_id: str
    processed_job_ids: list[str] = field(default_factory=list)
    succeeded_job_ids: list[str] = field(default_factory=list)
    failed_job_ids: list[str] = field(default_factory=list)
    skipped_job_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


class IngestionWorker:
    """Run pending ingestion jobs outside the MCP request path.

    This boundary deliberately reuses the existing `IngestionJob` records and
    `run_ingestion_job` transition logic. It does not add lease fields or raw
    worker paths to public job state.
    """

    def __init__(
        self,
        *,
        worker_id: str,
        asset_store: AssetStore,
        job_store: JobStore,
        object_store: FileObjectStore,
        extractor_run_store: ExtractorRunStore,
        observation_store: ObservationStore,
        extractor_adapters: Sequence[ExtractorAdapter],
        config: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id:
            raise ValueError("worker_id must be a non-empty string")
        self.worker_id = worker_id
        self.asset_store = asset_store
        self.job_store = job_store
        self.object_store = object_store
        self.extractor_run_store = extractor_run_store
        self.observation_store = observation_store
        self.extractor_adapters = list(extractor_adapters)
        self.config = dict(config or {})

    def run_once(
        self,
        *,
        max_jobs: int = 1,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> IngestionWorkerResult:
        if max_jobs < 1:
            raise ValueError("max_jobs must be at least 1")

        processed: list[str] = []
        succeeded: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        warnings: list[str] = []

        for job in self._pending_jobs()[:max_jobs]:
            if not self._can_run_job(job):
                skipped.append(job.ingestion_job_id)
                warnings.append(f"worker_not_allowed:{job.ingestion_job_id}")
                continue

            completed = run_ingestion_job(
                ingestion_job_id=job.ingestion_job_id,
                asset_store=self.asset_store,
                job_store=self.job_store,
                object_store=self.object_store,
                extractor_run_store=self.extractor_run_store,
                observation_store=self.observation_store,
                extractor_adapters=self.extractor_adapters,
                config=self.config,
                started_at=started_at,
                completed_at=completed_at,
            )
            processed.append(completed.ingestion_job_id)
            if completed.status == "succeeded":
                succeeded.append(completed.ingestion_job_id)
            elif completed.status == "failed":
                failed.append(completed.ingestion_job_id)
            else:
                warnings.append(
                    f"unexpected_terminal_status:{completed.ingestion_job_id}:{completed.status}"
                )

        return IngestionWorkerResult(
            worker_id=self.worker_id,
            processed_job_ids=processed,
            succeeded_job_ids=succeeded,
            failed_job_ids=failed,
            skipped_job_ids=skipped,
            warnings=warnings,
        )

    def _pending_jobs(self) -> list[IngestionJob]:
        return [job for job in self.job_store.list() if job.status == "pending"]

    def _can_run_job(self, job: IngestionJob) -> bool:
        asset = self.asset_store.get(job.asset_id)
        if asset is None:
            return True
        backend = self.object_store.backend_registry.get_backend(asset.storage_backend_id)
        if backend is None or not backend.allowed_workers:
            return True
        return self.worker_id in backend.allowed_workers


__all__ = [
    "IngestionWorker",
    "IngestionWorkerResult",
]
