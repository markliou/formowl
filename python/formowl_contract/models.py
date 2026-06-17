from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
import json
from typing import Any, Literal

from formowl_core import sha256_prefixed

JsonValue = Any
McpResultStatus = Literal[
    "ok",
    "partial",
    "not_found",
    "permission_denied",
    "pending_review",
    "error",
]
JobStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
ExtractorRunStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


class ContractValidationError(ValueError):
    """Raised when data does not match the shared formowl contract."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_plain(item) for key, item in asdict(value).items() if item is not None}
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    return value


def from_plain(value: Any) -> Any:
    if is_dataclass(value):
        return to_plain(value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(to_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return sha256_prefixed(canonical_json(value))


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if is_dataclass(value):
        value = to_plain(value)
    if not isinstance(value, dict):
        raise ContractValidationError(f"{name} must be an object")
    return value


def _require_fields(value: dict[str, Any], fields: tuple[str, ...], name: str) -> None:
    missing = [field for field in fields if value.get(field) in (None, "")]
    if missing:
        raise ContractValidationError(f"{name} missing required field(s): {', '.join(missing)}")


@dataclass(frozen=True)
class SourceRef:
    source_system: str
    source_type: str
    source_id: str
    source_instance: str | None = None
    source_key: str | None = None
    source_url: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SourceRef":
        validate_source_ref(value)
        return cls(
            source_system=str(value["source_system"]),
            source_type=str(value["source_type"]),
            source_id=str(value["source_id"]),
            source_instance=value.get("source_instance"),
            source_key=value.get("source_key"),
            source_url=value.get("source_url"),
        )

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class PermissionScope:
    scope_type: str
    visibility: str
    scope_id: str | None = None
    inherited_from: str | None = None

    @classmethod
    def project(cls, scope_id: str, inherited_from: str | None = None) -> "PermissionScope":
        return cls(
            scope_type="project",
            scope_id=scope_id,
            visibility="restricted",
            inherited_from=inherited_from,
        )

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class Citation:
    citation_id: str
    source_ref: SourceRef | dict[str, Any]
    evidence_snapshot_id: str | None = None
    locator: dict[str, Any] | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class EvidenceSnapshot:
    evidence_snapshot_id: str
    mcp_server: str
    tool_name: str
    captured_at: str
    permission_scope: PermissionScope | dict[str, Any]
    source_refs: list[SourceRef | dict[str, Any]]
    requested_by: str | None = None
    source_account_id: str | None = None
    request_hash: str | None = None
    response_hash: str | None = None
    storage_uri: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class ContextPackage:
    context_package_id: str
    context_type: str
    context_markdown: str
    source_refs: list[SourceRef | dict[str, Any]]
    evidence_snapshot_ids: list[str]
    citations: list[Citation | dict[str, Any]]
    permission_scope: PermissionScope | dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_context_package(data)
        return data


@dataclass(frozen=True)
class WikiRevision:
    revision_id: str
    title: str
    status: str
    change_kind: str
    markdown_hash: str
    source_refs: list[SourceRef | dict[str, Any]]
    evidence_snapshot_ids: list[str]
    citations: list[Citation | dict[str, Any]]
    created_at: str
    page_ref: dict[str, Any] | None = None
    draft_id: str | None = None
    parent_revision_id: str | None = None
    author_id: str | None = None
    reviewer_id: str | None = None
    reviewed_at: str | None = None
    published_at: str | None = None
    backend_ref: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class McpResultEnvelope:
    result_type: str
    status: McpResultStatus
    data: Any
    context_package: ContextPackage | dict[str, Any] | None = None
    source_refs: list[SourceRef | dict[str, Any]] | None = None
    evidence_snapshot_ids: list[str] | None = None
    citations: list[Citation | dict[str, Any]] | None = None
    permission_scope: PermissionScope | dict[str, Any] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class StorageBackend:
    storage_backend_id: str
    type: str
    display_name: str
    access_mode: str
    trust_level: str
    workspace_scope: str
    health_status: str
    internal_endpoint: str | None = None
    root_prefix: str | None = None
    bandwidth_class: str | None = None
    latency_class: str | None = None
    allowed_workers: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StorageBackend":
        backend = validate_storage_backend(value)
        return cls(
            storage_backend_id=str(backend["storage_backend_id"]),
            type=str(backend["type"]),
            display_name=str(backend["display_name"]),
            access_mode=str(backend["access_mode"]),
            trust_level=str(backend["trust_level"]),
            workspace_scope=str(backend["workspace_scope"]),
            health_status=str(backend["health_status"]),
            internal_endpoint=backend.get("internal_endpoint"),
            root_prefix=backend.get("root_prefix"),
            bandwidth_class=backend.get("bandwidth_class"),
            latency_class=backend.get("latency_class"),
            allowed_workers=list(backend.get("allowed_workers", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_storage_backend(data)
        return data


@dataclass(frozen=True)
class Asset:
    asset_id: str
    storage_backend_id: str
    object_uri: str
    content_hash: str
    file_size: int
    mime_type: str
    created_at: str
    registered_at: str
    owner_user_id: str
    workspace_id: str
    permission_scope: PermissionScope | dict[str, Any]
    lifecycle_state: str
    source_ref: SourceRef | dict[str, Any] | None = None
    original_filename: str | None = None
    project_id: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Asset":
        asset = validate_asset(value)
        return cls(
            asset_id=str(asset["asset_id"]),
            storage_backend_id=str(asset["storage_backend_id"]),
            object_uri=str(asset["object_uri"]),
            content_hash=str(asset["content_hash"]),
            file_size=int(asset["file_size"]),
            mime_type=str(asset["mime_type"]),
            created_at=str(asset["created_at"]),
            registered_at=str(asset["registered_at"]),
            owner_user_id=str(asset["owner_user_id"]),
            workspace_id=str(asset["workspace_id"]),
            permission_scope=asset["permission_scope"],
            lifecycle_state=str(asset["lifecycle_state"]),
            source_ref=asset.get("source_ref"),
            original_filename=asset.get("original_filename"),
            project_id=asset.get("project_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_asset(data)
        return data


@dataclass(frozen=True)
class AssetMetadata:
    asset_id: str
    metadata_type: str
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    extractor_run_id: str | None = None
    created_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AssetMetadata":
        metadata = validate_asset_metadata(value)
        return cls(
            asset_id=str(metadata["asset_id"]),
            metadata_type=str(metadata["metadata_type"]),
            metadata=dict(metadata.get("metadata", {})),
            extractor_run_id=metadata.get("extractor_run_id"),
            created_at=metadata.get("created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_asset_metadata(data)
        return data


@dataclass(frozen=True)
class IngestionJob:
    ingestion_job_id: str
    asset_id: str
    status: JobStatus
    requested_by: str
    workspace_id: str
    permission_scope: PermissionScope | dict[str, Any]
    created_at: str
    extractor_names: list[str] = field(default_factory=list)
    extractor_run_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "IngestionJob":
        job = validate_ingestion_job(value)
        return cls(
            ingestion_job_id=str(job["ingestion_job_id"]),
            asset_id=str(job["asset_id"]),
            status=job["status"],
            requested_by=str(job["requested_by"]),
            workspace_id=str(job["workspace_id"]),
            permission_scope=job["permission_scope"],
            created_at=str(job["created_at"]),
            extractor_names=list(job.get("extractor_names", [])),
            extractor_run_ids=list(job.get("extractor_run_ids", [])),
            observation_ids=list(job.get("observation_ids", [])),
            started_at=job.get("started_at"),
            completed_at=job.get("completed_at"),
            error=job.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_ingestion_job(data)
        return data


@dataclass(frozen=True)
class ExtractorRun:
    extractor_run_id: str
    asset_id: str
    extractor_name: str
    extractor_version: str
    extractor_type: str
    input_hash: str
    config_hash: str
    status: ExtractorRunStatus
    started_at: str
    completed_at: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    prompt_hash: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExtractorRun":
        run = validate_extractor_run(value)
        return cls(
            extractor_run_id=str(run["extractor_run_id"]),
            asset_id=str(run["asset_id"]),
            extractor_name=str(run["extractor_name"]),
            extractor_version=str(run["extractor_version"]),
            extractor_type=str(run["extractor_type"]),
            input_hash=str(run["input_hash"]),
            config_hash=str(run["config_hash"]),
            status=run["status"],
            started_at=str(run["started_at"]),
            completed_at=run.get("completed_at"),
            model_name=run.get("model_name"),
            model_version=run.get("model_version"),
            prompt_hash=run.get("prompt_hash"),
            warnings=list(run.get("warnings", [])),
            errors=list(run.get("errors", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_extractor_run(data)
        return data


@dataclass(frozen=True)
class Observation:
    observation_id: str
    extractor_run_id: str
    observation_type: str
    modality: str
    location: dict[str, JsonValue]
    confidence: float
    permission_scope: PermissionScope | dict[str, Any]
    created_at: str
    asset_id: str | None = None
    evidence_snapshot_id: str | None = None
    text: str | None = None
    caption: str | None = None
    payload: dict[str, JsonValue] | None = None
    extracted_value: JsonValue | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Observation":
        observation = validate_observation(value)
        return cls(
            observation_id=str(observation["observation_id"]),
            extractor_run_id=str(observation["extractor_run_id"]),
            observation_type=str(observation["observation_type"]),
            modality=str(observation["modality"]),
            location=dict(observation["location"]),
            confidence=float(observation["confidence"]),
            permission_scope=observation["permission_scope"],
            created_at=str(observation["created_at"]),
            asset_id=observation.get("asset_id"),
            evidence_snapshot_id=observation.get("evidence_snapshot_id"),
            text=observation.get("text"),
            caption=observation.get("caption"),
            payload=observation.get("payload"),
            extracted_value=observation.get("extracted_value"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_observation(data)
        return data


@dataclass(frozen=True)
class SemanticMetadata:
    semantic_metadata_id: str
    source_observation_ids: list[str]
    metadata_type: str
    value: dict[str, JsonValue]
    confidence: float
    extractor_run_id: str
    requires_review: bool
    created_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SemanticMetadata":
        metadata = validate_semantic_metadata(value)
        return cls(
            semantic_metadata_id=str(metadata["semantic_metadata_id"]),
            source_observation_ids=list(metadata["source_observation_ids"]),
            metadata_type=str(metadata["metadata_type"]),
            value=dict(metadata["value"]),
            confidence=float(metadata["confidence"]),
            extractor_run_id=str(metadata["extractor_run_id"]),
            requires_review=bool(metadata["requires_review"]),
            created_at=metadata.get("created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_semantic_metadata(data)
        return data


def validate_source_ref(value: Any) -> dict[str, Any]:
    source_ref = _require_mapping(value, "SourceRef")
    _require_fields(source_ref, ("source_system", "source_type", "source_id"), "SourceRef")
    return source_ref


def validate_context_package(value: Any) -> dict[str, Any]:
    context_package = _require_mapping(value, "ContextPackage")
    _require_fields(
        context_package,
        ("context_package_id", "context_type", "context_markdown"),
        "ContextPackage",
    )
    if not isinstance(context_package.get("source_refs", []), list):
        raise ContractValidationError("ContextPackage.source_refs must be a list")
    for source_ref in context_package.get("source_refs", []):
        validate_source_ref(source_ref)
    if not isinstance(context_package.get("evidence_snapshot_ids", []), list):
        raise ContractValidationError("ContextPackage.evidence_snapshot_ids must be a list")
    if not isinstance(context_package.get("citations", []), list):
        raise ContractValidationError("ContextPackage.citations must be a list")
    return context_package


def validate_permission_scope(value: Any) -> dict[str, Any]:
    permission_scope = _require_mapping(value, "PermissionScope")
    _require_fields(permission_scope, ("scope_type", "visibility"), "PermissionScope")
    return permission_scope


def validate_storage_backend(value: Any) -> dict[str, Any]:
    backend = _require_mapping(value, "StorageBackend")
    _require_fields(
        backend,
        (
            "storage_backend_id",
            "type",
            "display_name",
            "access_mode",
            "trust_level",
            "workspace_scope",
            "health_status",
        ),
        "StorageBackend",
    )
    if not isinstance(backend.get("allowed_workers", []), list):
        raise ContractValidationError("StorageBackend.allowed_workers must be a list")
    return backend


def validate_asset(value: Any) -> dict[str, Any]:
    asset = _require_mapping(value, "Asset")
    _require_fields(
        asset,
        (
            "asset_id",
            "storage_backend_id",
            "object_uri",
            "content_hash",
            "file_size",
            "mime_type",
            "created_at",
            "registered_at",
            "owner_user_id",
            "workspace_id",
            "permission_scope",
            "lifecycle_state",
        ),
        "Asset",
    )
    if not isinstance(asset["file_size"], int) or asset["file_size"] < 0:
        raise ContractValidationError("Asset.file_size must be a non-negative integer")
    validate_permission_scope(asset["permission_scope"])
    if "source_ref" in asset:
        validate_source_ref(asset["source_ref"])
    return asset


def validate_asset_metadata(value: Any) -> dict[str, Any]:
    metadata = _require_mapping(value, "AssetMetadata")
    _require_fields(metadata, ("asset_id", "metadata_type"), "AssetMetadata")
    if not isinstance(metadata.get("metadata", {}), dict):
        raise ContractValidationError("AssetMetadata.metadata must be an object")
    return metadata


def validate_ingestion_job(value: Any) -> dict[str, Any]:
    job = _require_mapping(value, "IngestionJob")
    _require_fields(
        job,
        (
            "ingestion_job_id",
            "asset_id",
            "status",
            "requested_by",
            "workspace_id",
            "permission_scope",
            "created_at",
        ),
        "IngestionJob",
    )
    if job["status"] not in ("pending", "running", "succeeded", "failed", "cancelled"):
        raise ContractValidationError("IngestionJob.status is not supported")
    validate_permission_scope(job["permission_scope"])
    for field_name in ("extractor_names", "extractor_run_ids", "observation_ids"):
        if not isinstance(job.get(field_name, []), list):
            raise ContractValidationError(f"IngestionJob.{field_name} must be a list")
    return job


def validate_extractor_run(value: Any) -> dict[str, Any]:
    run = _require_mapping(value, "ExtractorRun")
    _require_fields(
        run,
        (
            "extractor_run_id",
            "asset_id",
            "extractor_name",
            "extractor_version",
            "extractor_type",
            "input_hash",
            "config_hash",
            "status",
            "started_at",
        ),
        "ExtractorRun",
    )
    if run["status"] not in ("pending", "running", "succeeded", "failed", "cancelled"):
        raise ContractValidationError("ExtractorRun.status is not supported")
    for field_name in ("warnings", "errors"):
        if not isinstance(run.get(field_name, []), list):
            raise ContractValidationError(f"ExtractorRun.{field_name} must be a list")
    return run


def validate_observation(value: Any) -> dict[str, Any]:
    observation = _require_mapping(value, "Observation")
    _require_fields(
        observation,
        (
            "observation_id",
            "extractor_run_id",
            "observation_type",
            "modality",
            "location",
            "confidence",
            "permission_scope",
            "created_at",
        ),
        "Observation",
    )
    if not observation.get("asset_id") and not observation.get("evidence_snapshot_id"):
        raise ContractValidationError("Observation requires asset_id or evidence_snapshot_id")
    if not isinstance(observation["location"], dict):
        raise ContractValidationError("Observation.location must be an object")
    if not isinstance(observation["confidence"], (int, float)):
        raise ContractValidationError("Observation.confidence must be numeric")
    if not 0 <= float(observation["confidence"]) <= 1:
        raise ContractValidationError("Observation.confidence must be between 0 and 1")
    if "payload" in observation and not isinstance(observation["payload"], dict):
        raise ContractValidationError("Observation.payload must be an object")
    validate_permission_scope(observation["permission_scope"])
    return observation


def validate_semantic_metadata(value: Any) -> dict[str, Any]:
    metadata = _require_mapping(value, "SemanticMetadata")
    _require_fields(
        metadata,
        (
            "semantic_metadata_id",
            "source_observation_ids",
            "metadata_type",
            "value",
            "confidence",
            "extractor_run_id",
            "requires_review",
        ),
        "SemanticMetadata",
    )
    if not isinstance(metadata["source_observation_ids"], list):
        raise ContractValidationError("SemanticMetadata.source_observation_ids must be a list")
    if not metadata["source_observation_ids"]:
        raise ContractValidationError("SemanticMetadata.source_observation_ids cannot be empty")
    if not isinstance(metadata["value"], dict):
        raise ContractValidationError("SemanticMetadata.value must be an object")
    if not isinstance(metadata["confidence"], (int, float)):
        raise ContractValidationError("SemanticMetadata.confidence must be numeric")
    if not 0 <= float(metadata["confidence"]) <= 1:
        raise ContractValidationError("SemanticMetadata.confidence must be between 0 and 1")
    if not isinstance(metadata["requires_review"], bool):
        raise ContractValidationError("SemanticMetadata.requires_review must be boolean")
    return metadata
