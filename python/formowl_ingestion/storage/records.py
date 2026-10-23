from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Generic, TypeVar
import uuid

from formowl_contract import (
    Asset,
    ExtractorRun,
    IngestionJob,
    Observation,
    UploadSession,
    to_plain,
)

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
T = TypeVar("T")


class _JsonRecordStore(Generic[T]):
    def __init__(
        self,
        base_dir: str | Path,
        *,
        collection: str,
        id_field: str,
        factory: Callable[[dict[str, Any]], T],
        serializer: Callable[[T], dict[str, Any]],
        sharded: bool = False,
        create_directory: bool = True,
        new_records_sharded: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir) / "ingestion" / collection
        if create_directory:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        self.id_field = id_field
        self.factory = factory
        self.serializer = serializer
        self._sharded = sharded
        self._new_records_sharded = new_records_sharded

    def create(self, record: T | dict[str, Any]) -> T:
        validated = self._validate(record)
        payload = self.serializer(validated)
        record_id = str(payload[self.id_field])
        path = self._record_path(record_id)
        _write_json(
            path, payload,
            staging_directory=(
                self._shard_record_path(record_id).parent
                if self._sharded and (path.parent != self.base_dir or path.exists())
                else None
            ),
        )
        return validated

    def get(self, record_id: str) -> T | None:
        path = self._record_path(record_id)
        try:
            payload = _read_json(path)
        except FileNotFoundError:
            return None
        return self.factory(payload)

    def delete(self, record_id: str) -> None:
        path = self._record_path(record_id)
        if path.exists():
            path.unlink()

    def list(self) -> list[T]:
        paths = list(self.base_dir.glob("*.json"))
        if self._sharded:
            paths.extend(self.base_dir.glob("_shards/[0-9a-f][0-9a-f]/*.json"))
            if len({path.name for path in paths}) != len(paths):
                raise ValueError("duplicate record identity across storage layouts")
            if any(
                path.parent != self.base_dir and path != self._shard_record_path(path.stem)
                for path in paths
            ):
                raise ValueError("invalid sharded record location")
        return [self.factory(_read_json(path)) for path in sorted(paths, key=lambda path: path.name)]

    def validate_record_id(self, record_id: str) -> None:
        self._legacy_record_path(record_id)

    def _validate(self, record: T | dict[str, Any]) -> T:
        if isinstance(record, dict):
            return self.factory(record)
        return self.factory(self.serializer(record))

    def _record_path(self, record_id: str) -> Path:
        legacy = self._legacy_record_path(record_id)
        if not self._sharded:
            return legacy
        sharded = self._shard_record_path(record_id)
        # Existing IDs keep their physical location. Two copies are ambiguous,
        # even if identical; never select one as an implicit source of truth.
        if legacy.exists():
            if sharded.exists():
                raise ValueError("duplicate record identity across storage layouts")
            return legacy
        # Computing a keyed path never creates directories or scans records.
        # Only the existing write owner creates the shard on a new write.
        if self._new_records_sharded or sharded.exists():
            return sharded
        return legacy

    def _shard_record_path(self, record_id: str) -> Path:
        bucket = hashlib.sha256(record_id.encode("utf-8")).hexdigest()[:2]
        return self.base_dir / "_shards" / bucket / f"{record_id}.json"

    def _legacy_record_path(self, record_id: str) -> Path:
        if not record_id or not _SAFE_RECORD_ID.fullmatch(record_id):
            raise ValueError(f"{self.id_field} must be a safe file name")
        return self.base_dir / f"{record_id}.json"


class AssetStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonRecordStore[Asset](
            base_dir,
            collection="assets",
            id_field="asset_id",
            factory=Asset.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(self, asset: Asset | dict[str, Any]) -> Asset:
        return self._store.create(asset)

    def get(self, asset_id: str) -> Asset | None:
        return self._store.get(asset_id)

    def list(self) -> list[Asset]:
        return self._store.list()

    def delete(self, asset_id: str) -> None:
        self._store.delete(asset_id)


class JobStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonRecordStore[IngestionJob](
            base_dir,
            collection="jobs",
            id_field="ingestion_job_id",
            factory=IngestionJob.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(self, job: IngestionJob | dict[str, Any]) -> IngestionJob:
        return self._store.create(job)

    def get(self, ingestion_job_id: str) -> IngestionJob | None:
        return self._store.get(ingestion_job_id)

    def list(self) -> list[IngestionJob]:
        return self._store.list()


class ExtractorRunStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonRecordStore[ExtractorRun](
            base_dir,
            collection="extractor-runs",
            id_field="extractor_run_id",
            factory=ExtractorRun.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(self, run: ExtractorRun | dict[str, Any]) -> ExtractorRun:
        return self._store.create(run)

    def get(self, extractor_run_id: str) -> ExtractorRun | None:
        return self._store.get(extractor_run_id)

    def list(self) -> list[ExtractorRun]:
        return self._store.list()


class ObservationStore:
    def __init__(
        self, base_dir: str | Path, *, create_directory: bool = True,
        write_layout: str = "sharded",
    ) -> None:
        if write_layout not in {"sharded", "flat"}:
            raise ValueError("Observation write layout is invalid")
        self._store = _JsonRecordStore[Observation](
            base_dir,
            collection="observations",
            id_field="observation_id",
            factory=Observation.from_dict,
            serializer=lambda value: value.to_dict(),
            sharded=True,
            create_directory=create_directory,
            # A finite sealed export may require flat NEW records. Reads and
            # existing identities still use both layouts without migration.
            new_records_sharded=write_layout == "sharded",
        )

    def create(self, observation: Observation | dict[str, Any]) -> Observation:
        return self._store.create(observation)

    def get(self, observation_id: str) -> Observation | None:
        return self._store.get(observation_id)

    def list(self) -> list[Observation]:
        return self._store.list()

    def validate_observation_id(self, observation_id: str) -> None:
        self._store.validate_record_id(observation_id)


class UploadSessionStore:
    def __init__(self, base_dir: str | Path) -> None:
        self._store = _JsonRecordStore[UploadSession](
            base_dir,
            collection="upload-sessions",
            id_field="upload_session_id",
            factory=UploadSession.from_dict,
            serializer=lambda value: value.to_dict(),
        )

    def create(self, upload_session: UploadSession | dict[str, Any]) -> UploadSession:
        return self._store.create(upload_session)

    def get(self, upload_session_id: str) -> UploadSession | None:
        return self._store.get(upload_session_id)

    def list(self) -> list[UploadSession]:
        return self._store.list()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any, *, staging_directory: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    directory = staging_directory if staging_directory is not None else path.parent
    if directory != path.parent:
        directory.mkdir(parents=True, exist_ok=True)
    # Legacy replacements use a shard-local temporary entry: the saturated
    # flat directory needs no new name. Rename remains atomic on this filesystem.
    temp_path = directory / f".{path.name}.{uuid.uuid4().hex}.tmp"
    temp_path.write_text(
        json.dumps(to_plain(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    last_error: PermissionError | None = None
    for attempt in range(5):
        try:
            temp_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    if temp_path.exists():
        temp_path.unlink(missing_ok=True)
    if last_error is not None:
        raise last_error
