from __future__ import annotations

from typing import Any, Protocol

from formowl_contract import Asset, ExtractorRun, IngestionJob, Observation, UploadSession


class AssetRecordStore(Protocol):
    def create(self, asset: Asset | dict[str, Any]) -> Asset: ...

    def get(self, asset_id: str) -> Asset | None: ...

    def list(self) -> list[Asset]: ...


class JobRecordStore(Protocol):
    def create(self, job: IngestionJob | dict[str, Any]) -> IngestionJob: ...

    def get(self, ingestion_job_id: str) -> IngestionJob | None: ...

    def list(self) -> list[IngestionJob]: ...


class ExtractorRunRecordStore(Protocol):
    def create(self, run: ExtractorRun | dict[str, Any]) -> ExtractorRun: ...

    def get(self, extractor_run_id: str) -> ExtractorRun | None: ...

    def list(self) -> list[ExtractorRun]: ...


class ObservationRecordStore(Protocol):
    def create(self, observation: Observation | dict[str, Any]) -> Observation: ...

    def get(self, observation_id: str) -> Observation | None: ...

    def list(self) -> list[Observation]: ...

    def validate_observation_id(self, observation_id: str) -> None: ...


class UploadSessionRecordStore(Protocol):
    def create(self, upload_session: UploadSession | dict[str, Any]) -> UploadSession: ...

    def get(self, upload_session_id: str) -> UploadSession | None: ...

    def list(self) -> list[UploadSession]: ...


def ingestion_record_store_interface_names() -> tuple[str, ...]:
    return (
        "AssetRecordStore",
        "JobRecordStore",
        "ExtractorRunRecordStore",
        "ObservationRecordStore",
        "UploadSessionRecordStore",
    )
