from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from formowl_contract import StorageBackend, to_plain

from .backends import StorageBackendRegistry

_SAFE_BACKEND_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_SECRET_KEY = re.compile(r"(secret|password|token|credential|access[_-]?key)", re.IGNORECASE)
_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_SUPPORTED_BACKEND_TYPES = {
    "ingress_only",
    "local_fs",
    "minio",
    "s3_compatible",
    "synology_nfs",
    "synology_smb",
}
_CONFIG_FIELDS = {
    "access_mode",
    "allowed_workers",
    "bandwidth_class",
    "display_name",
    "health_status",
    "internal_endpoint",
    "latency_class",
    "private_config",
    "root_path",
    "root_prefix",
    "storage_backend_id",
    "trust_level",
    "type",
    "workspace_scope",
}


@dataclass(frozen=True)
class StorageBackendConfig:
    """Deployment-facing storage backend config.

    Public backend fields are validated before they are registered. Private
    details such as a local root path or internal endpoint remain in the
    registry's private record and are not returned through public envelopes.
    """

    type: str
    workspace_scope: str
    display_name: str = "Local filesystem backend"
    access_mode: str = "read_write"
    trust_level: str = "trusted_internal"
    health_status: str = "healthy"
    storage_backend_id: str | None = None
    root_path: str | Path | None = None
    internal_endpoint: str | None = None
    root_prefix: str | None = None
    bandwidth_class: str | None = None
    latency_class: str | None = None
    allowed_workers: tuple[str, ...] = ()
    private_config: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StorageBackendConfig":
        if not isinstance(value, Mapping):
            raise ValueError("storage backend config must be an object")
        payload = to_plain(dict(value))
        extra_fields = sorted(set(payload) - _CONFIG_FIELDS)
        if extra_fields:
            raise ValueError(
                "unsupported storage backend config field(s): " + ", ".join(extra_fields)
            )
        return cls(
            type=_optional_string(payload.get("type"), default="local_fs"),
            workspace_scope=_optional_string(
                payload.get("workspace_scope"),
                default="workspace_default",
            ),
            display_name=_optional_string(
                payload.get("display_name"),
                default="Local filesystem backend",
            ),
            access_mode=_optional_string(payload.get("access_mode"), default="read_write"),
            trust_level=_optional_string(
                payload.get("trust_level"),
                default="trusted_internal",
            ),
            health_status=_optional_string(payload.get("health_status"), default="healthy"),
            storage_backend_id=_optional_string_or_none(payload.get("storage_backend_id")),
            root_path=_optional_string_or_path(payload.get("root_path")),
            internal_endpoint=_optional_string_or_none(payload.get("internal_endpoint")),
            root_prefix=_optional_string_or_none(payload.get("root_prefix")),
            bandwidth_class=_optional_string_or_none(payload.get("bandwidth_class")),
            latency_class=_optional_string_or_none(payload.get("latency_class")),
            allowed_workers=tuple(_string_list(payload.get("allowed_workers", []))),
            private_config=_private_config(payload.get("private_config", {})),
        )


def load_storage_backend_configs_from_env(
    environ: Mapping[str, str] | None = None,
) -> list[StorageBackendConfig]:
    env = os.environ if environ is None else environ
    structured = _clean_env(env.get("FORMOWL_STORAGE_BACKENDS_JSON"))
    if structured:
        decoded = json.loads(structured)
        if not isinstance(decoded, list):
            raise ValueError("FORMOWL_STORAGE_BACKENDS_JSON must be a JSON array")
        return [StorageBackendConfig.from_dict(item) for item in decoded]

    backend_type = _clean_env(env.get("FORMOWL_STORAGE_BACKEND_TYPE")) or "local_fs"
    data_dir = _clean_env(env.get("FORMOWL_DATA_DIR")) or ".formowl/data"
    root_path = _clean_env(env.get("FORMOWL_STORAGE_BACKEND_ROOT"))
    if backend_type == "local_fs" and root_path is None:
        root_path = str(Path(data_dir) / "object-store")

    private_config: dict[str, Any] = {}
    object_store_bucket = _clean_env(env.get("FORMOWL_OBJECT_STORE_BUCKET"))
    object_store_region = _clean_env(env.get("FORMOWL_OBJECT_STORE_REGION"))
    if object_store_bucket is not None:
        private_config["bucket"] = object_store_bucket
    if object_store_region is not None:
        private_config["region"] = object_store_region

    return [
        StorageBackendConfig(
            type=backend_type,
            storage_backend_id=_clean_env(env.get("FORMOWL_STORAGE_BACKEND_ID")),
            workspace_scope=_clean_env(env.get("FORMOWL_WORKSPACE_ID")) or "workspace_default",
            display_name=_clean_env(env.get("FORMOWL_STORAGE_BACKEND_DISPLAY_NAME"))
            or "Local filesystem backend",
            access_mode=_clean_env(env.get("FORMOWL_STORAGE_BACKEND_ACCESS_MODE")) or "read_write",
            trust_level=_clean_env(env.get("FORMOWL_STORAGE_BACKEND_TRUST_LEVEL"))
            or "trusted_internal",
            health_status=_clean_env(env.get("FORMOWL_STORAGE_BACKEND_HEALTH_STATUS")) or "healthy",
            root_path=root_path,
            internal_endpoint=_clean_env(env.get("FORMOWL_STORAGE_INTERNAL_ENDPOINT"))
            or _clean_env(env.get("FORMOWL_OBJECT_STORE_ENDPOINT")),
            root_prefix=_clean_env(env.get("FORMOWL_STORAGE_BACKEND_ROOT_PREFIX")),
            bandwidth_class=_clean_env(env.get("FORMOWL_STORAGE_BACKEND_BANDWIDTH_CLASS")),
            latency_class=_clean_env(env.get("FORMOWL_STORAGE_BACKEND_LATENCY_CLASS")),
            allowed_workers=tuple(
                _comma_list(_clean_env(env.get("FORMOWL_STORAGE_ALLOWED_WORKERS")))
            ),
            private_config=private_config,
        )
    ]


def configure_storage_backend_registry(
    registry: StorageBackendRegistry,
    configs: Sequence[StorageBackendConfig | Mapping[str, Any]],
) -> list[StorageBackend]:
    return [_register_config(registry, _coerce_config(config)) for config in configs]


def configure_storage_backend_registry_from_env(
    registry: StorageBackendRegistry,
    environ: Mapping[str, str] | None = None,
) -> list[StorageBackend]:
    return configure_storage_backend_registry(
        registry,
        load_storage_backend_configs_from_env(environ),
    )


def _register_config(
    registry: StorageBackendRegistry,
    config: StorageBackendConfig,
) -> StorageBackend:
    _validate_config(config)
    if config.type == "local_fs":
        return registry.register_local_backend(
            config.root_path or "",
            workspace_scope=config.workspace_scope,
            display_name=config.display_name,
            access_mode=config.access_mode,
            trust_level=config.trust_level,
            health_status=config.health_status,
            bandwidth_class=config.bandwidth_class,
            latency_class=config.latency_class,
            allowed_workers=list(config.allowed_workers),
            storage_backend_id=config.storage_backend_id,
        )

    backend_id = config.storage_backend_id
    if backend_id is None:
        raise ValueError("non-local storage backend config requires storage_backend_id")
    backend = StorageBackend(
        storage_backend_id=backend_id,
        type=config.type,
        display_name=config.display_name,
        access_mode=config.access_mode,
        trust_level=config.trust_level,
        workspace_scope=config.workspace_scope,
        health_status=config.health_status,
        internal_endpoint=config.internal_endpoint,
        root_prefix=config.root_prefix or f"formowl://storage/{backend_id}",
        bandwidth_class=config.bandwidth_class,
        latency_class=config.latency_class,
        allowed_workers=list(config.allowed_workers),
    )
    return registry.register_backend(
        backend,
        private_config=dict(config.private_config),
    )


def _coerce_config(config: StorageBackendConfig | Mapping[str, Any]) -> StorageBackendConfig:
    if isinstance(config, StorageBackendConfig):
        return config
    return StorageBackendConfig.from_dict(config)


def _validate_config(config: StorageBackendConfig) -> None:
    if config.type not in _SUPPORTED_BACKEND_TYPES:
        raise ValueError(f"unsupported storage backend type: {config.type}")
    if config.storage_backend_id is not None:
        _require_safe_backend_id(config.storage_backend_id)
    _require_public_safe_string(config.type, "type")
    _require_public_safe_string(config.workspace_scope, "workspace_scope")
    _require_public_safe_string(config.display_name, "display_name")
    _require_public_safe_string(config.access_mode, "access_mode")
    _require_public_safe_string(config.trust_level, "trust_level")
    _require_public_safe_string(config.health_status, "health_status")
    for worker in config.allowed_workers:
        _require_public_safe_string(worker, "allowed_workers")
    for field_name in ("bandwidth_class", "latency_class", "root_prefix"):
        value = getattr(config, field_name)
        if value is not None:
            _require_public_safe_string(value, field_name)
    if config.type == "local_fs" and config.root_path is None:
        raise ValueError("local_fs storage backend config requires root_path")
    if config.type != "local_fs" and config.root_path is not None:
        raise ValueError("root_path is only supported for local_fs storage backend config")
    if config.internal_endpoint is not None and not isinstance(config.internal_endpoint, str):
        raise ValueError("internal_endpoint must be a string")
    _validate_private_config(config.private_config)


def _validate_private_config(private_config: Mapping[str, Any]) -> None:
    if not isinstance(private_config, Mapping):
        raise ValueError("private_config must be an object")
    for key in private_config:
        if not isinstance(key, str) or not key:
            raise ValueError("private_config keys must be non-empty strings")
        if _SECRET_KEY.search(key):
            raise ValueError("storage backend private_config must not include secrets")


def _require_safe_backend_id(value: str) -> None:
    if value in {".", ".."} or not _SAFE_BACKEND_ID.fullmatch(value):
        raise ValueError("storage_backend_id must be a safe backend id")


def _require_public_safe_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    if value.startswith("formowl://"):
        return
    if _looks_like_raw_locator(value):
        raise ValueError(f"{field_name} must not expose raw backend locators")


def _looks_like_raw_locator(value: str) -> bool:
    stripped = value.strip()
    lowered = stripped.lower()
    return (
        _DRIVE_PATH.match(stripped) is not None
        or stripped.startswith(("/", "\\", "~"))
        or "\\" in stripped
        or "/" in stripped
        or lowered.startswith(
            (
                "file://",
                "http://",
                "https://",
                "minio://",
                "nfs://",
                "postgres://",
                "postgresql://",
                "s3://",
                "smb://",
                "webdav://",
            )
        )
    )


def _optional_string(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ValueError("storage backend config values must be non-empty strings")
    return value


def _optional_string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("storage backend config values must be non-empty strings")
    return value


def _optional_string_or_path(value: Any) -> str | Path | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    if not isinstance(value, str) or not value:
        raise ValueError("root_path must be a non-empty string or path")
    return value


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("allowed_workers must be a list")
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError("allowed_workers values must be non-empty strings")
    return list(value)


def _private_config(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("private_config must be an object")
    _validate_private_config(value)
    return dict(value)


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _comma_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


__all__ = [
    "StorageBackendConfig",
    "configure_storage_backend_registry",
    "configure_storage_backend_registry_from_env",
    "load_storage_backend_configs_from_env",
]
