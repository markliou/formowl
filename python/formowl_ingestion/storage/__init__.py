"""File-backed storage package boundary for ingestion records."""

from .backends import StorageBackendRegistry
from .config import (
    StorageBackendConfig,
    configure_storage_backend_registry,
    configure_storage_backend_registry_from_env,
    load_storage_backend_configs_from_env,
)
from .objects import FileObjectStore, StoredObject
from .records import AssetStore, ExtractorRunStore, JobStore, ObservationStore, UploadSessionStore

__all__ = [
    "AssetStore",
    "ExtractorRunStore",
    "FileObjectStore",
    "JobStore",
    "ObservationStore",
    "StorageBackendConfig",
    "StoredObject",
    "StorageBackendRegistry",
    "UploadSessionStore",
    "configure_storage_backend_registry",
    "configure_storage_backend_registry_from_env",
    "load_storage_backend_configs_from_env",
]
