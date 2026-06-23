from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Literal

from formowl_core import sha256_prefixed, sha256_prefixed_id

JsonValue = Any
McpResultStatus = Literal[
    "ok",
    "partial",
    "not_found",
    "permission_denied",
    "pending_review",
    "error",
]
JOB_STATUS_VALUES = ("pending", "running", "succeeded", "failed", "cancelled")
EXTRACTOR_RUN_STATUS_VALUES = JOB_STATUS_VALUES
USER_STATUS_VALUES = ("active", "disabled")
SESSION_SELECTION_METHOD_VALUES = ("manual_trusted_internal",)
WORKSPACE_MEMBER_ROLE_VALUES = ("owner", "member", "viewer")
ACCESS_REQUEST_STATUS_VALUES = ("pending", "approved", "denied", "expired")
UPLOAD_SESSION_STATUS_VALUES = (
    "pending",
    "uploading",
    "waiting_external",
    "succeeded",
    "failed",
    "cancelled",
    "expired",
)
CANDIDATE_STATUS_VALUES = ("pending_review", "approved", "rejected", "deferred")
JobStatus = Literal[*JOB_STATUS_VALUES]
ExtractorRunStatus = Literal[*EXTRACTOR_RUN_STATUS_VALUES]
UserStatus = Literal[*USER_STATUS_VALUES]
SessionSelectionMethod = Literal[*SESSION_SELECTION_METHOD_VALUES]
WorkspaceMemberRole = Literal[*WORKSPACE_MEMBER_ROLE_VALUES]
AccessRequestStatus = Literal[*ACCESS_REQUEST_STATUS_VALUES]
UploadSessionStatus = Literal[*UPLOAD_SESSION_STATUS_VALUES]
CandidateStatus = Literal[*CANDIDATE_STATUS_VALUES]
_GRAPH_REFERENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RAW_PUBLIC_REFERENCE_PATTERNS = (
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"(^|[\s'\"])/(srv|home|tmp|var|mnt|opt|root)/", re.IGNORECASE),
    re.compile(r"\b(file|smb|nfs|postgres|postgresql|mysql|sqlite)://", re.IGNORECASE),
    re.compile(r"\b(select|with|copy|insert|update|delete|drop|alter)\b\s+", re.IGNORECASE),
)


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


def stable_resource_contract_hash(contract_name: str, payload: Any) -> str:
    if not contract_name:
        raise ContractValidationError("contract_name is required")
    return sha256_json({"contract_name": contract_name, "payload": payload})


def stable_resource_contract_id(prefix: str, contract_name: str, payload: Any) -> str:
    if not contract_name:
        raise ContractValidationError("contract_name is required")
    return sha256_prefixed_id(
        prefix,
        canonical_json({"contract_name": contract_name, "payload": payload}),
    )


def stable_storage_backend_id(
    *,
    backend_type: str,
    workspace_scope: str,
    root_prefix: str | None = None,
    display_name: str | None = None,
) -> str:
    return stable_resource_contract_id(
        "storage",
        "StorageBackend",
        {
            "type": backend_type,
            "workspace_scope": workspace_scope,
            "root_prefix": root_prefix,
            "display_name": display_name,
        },
    )


def stable_asset_id(
    *,
    storage_backend_id: str,
    object_uri: str,
    content_hash: str,
    workspace_id: str,
    source_ref: SourceRef | dict[str, Any] | None = None,
) -> str:
    return stable_resource_contract_id(
        "asset",
        "Asset",
        {
            "storage_backend_id": storage_backend_id,
            "object_uri": object_uri,
            "content_hash": content_hash,
            "workspace_id": workspace_id,
            "source_ref": source_ref,
        },
    )


def stable_asset_metadata_hash(
    *,
    asset_id: str,
    metadata_type: str,
    metadata: dict[str, JsonValue],
    extractor_run_id: str | None = None,
) -> str:
    return stable_resource_contract_hash(
        "AssetMetadata",
        {
            "asset_id": asset_id,
            "metadata_type": metadata_type,
            "metadata": metadata,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_ingestion_job_id(
    *,
    asset_id: str,
    requested_by: str,
    workspace_id: str,
    extractor_names: list[str] | tuple[str, ...],
    config_hash: str | None = None,
) -> str:
    return stable_resource_contract_id(
        "job",
        "IngestionJob",
        {
            "asset_id": asset_id,
            "requested_by": requested_by,
            "workspace_id": workspace_id,
            "extractor_names": list(extractor_names),
            "config_hash": config_hash,
        },
    )


def stable_extractor_run_id(
    *,
    asset_id: str,
    extractor_name: str,
    extractor_version: str,
    extractor_type: str,
    input_hash: str,
    config_hash: str,
    model_name: str | None = None,
    model_version: str | None = None,
    prompt_hash: str | None = None,
) -> str:
    return stable_resource_contract_id(
        "run",
        "ExtractorRun",
        {
            "asset_id": asset_id,
            "extractor_name": extractor_name,
            "extractor_version": extractor_version,
            "extractor_type": extractor_type,
            "input_hash": input_hash,
            "config_hash": config_hash,
            "model_name": model_name,
            "model_version": model_version,
            "prompt_hash": prompt_hash,
        },
    )


def stable_observation_id(
    *,
    extractor_run_id: str,
    observation_type: str,
    modality: str,
    location: dict[str, JsonValue],
    asset_id: str | None = None,
    evidence_snapshot_id: str | None = None,
    text: str | None = None,
    caption: str | None = None,
    payload: dict[str, JsonValue] | None = None,
    extracted_value: JsonValue | None = None,
) -> str:
    if _is_missing_optional_id(asset_id) and _is_missing_optional_id(evidence_snapshot_id):
        raise ContractValidationError("Observation id requires asset_id or evidence_snapshot_id")
    return stable_resource_contract_id(
        "obs",
        "Observation",
        {
            "asset_id": asset_id,
            "evidence_snapshot_id": evidence_snapshot_id,
            "extractor_run_id": extractor_run_id,
            "observation_type": observation_type,
            "modality": modality,
            "location": location,
            "text": text,
            "caption": caption,
            "payload": payload,
            "extracted_value": extracted_value,
        },
    )


def stable_semantic_metadata_id(
    *,
    source_observation_ids: list[str] | tuple[str, ...],
    metadata_type: str,
    value: dict[str, JsonValue],
    extractor_run_id: str,
) -> str:
    return stable_resource_contract_id(
        "sem",
        "SemanticMetadata",
        {
            "source_observation_ids": list(source_observation_ids),
            "metadata_type": metadata_type,
            "value": value,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_candidate_atom_id(
    *,
    source_observation_ids: list[str] | tuple[str, ...],
    atom_type: str,
    label: str,
    properties: dict[str, JsonValue],
    extractor_run_id: str,
) -> str:
    return stable_resource_contract_id(
        "catom",
        "CandidateAtom",
        {
            "source_observation_ids": list(source_observation_ids),
            "atom_type": atom_type,
            "label": label,
            "properties": properties,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_candidate_relation_id(
    *,
    source_candidate_atom_id: str,
    target_candidate_atom_id: str,
    relation_type: str,
    source_observation_ids: list[str] | tuple[str, ...],
    properties: dict[str, JsonValue],
    extractor_run_id: str,
) -> str:
    return stable_resource_contract_id(
        "crel",
        "CandidateRelation",
        {
            "source_candidate_atom_id": source_candidate_atom_id,
            "target_candidate_atom_id": target_candidate_atom_id,
            "relation_type": relation_type,
            "source_observation_ids": list(source_observation_ids),
            "properties": properties,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_external_graph_import_id(
    *,
    source_system: str,
    source_ref: SourceRef | dict[str, Any],
    extractor_run_id: str,
    imported_at: str,
) -> str:
    return stable_resource_contract_id(
        "egimp",
        "ExternalGraphImport",
        {
            "source_system": source_system,
            "source_ref": source_ref,
            "extractor_run_id": extractor_run_id,
            "imported_at": imported_at,
        },
    )


def stable_upload_session_id(
    *,
    actor_user_id: str,
    workspace_id: str,
    owner_scope_type: str,
    owner_scope_id: str,
    intent: str,
    intended_asset_type: str,
    ingestion_profile: str,
    created_at: str,
) -> str:
    return stable_resource_contract_id(
        "upload",
        "UploadSession",
        {
            "actor_user_id": actor_user_id,
            "workspace_id": workspace_id,
            "owner_scope_type": owner_scope_type,
            "owner_scope_id": owner_scope_id,
            "intent": intent,
            "intended_asset_type": intended_asset_type,
            "ingestion_profile": ingestion_profile,
            "created_at": created_at,
        },
    )


def stable_wiki_projection_spec_id(
    *,
    projection_kind: str,
    graph_revision_id: str,
    ontology_revision_id: str,
    title: str,
    source_refs: list[SourceRef | dict[str, Any]] | tuple[SourceRef | dict[str, Any], ...],
    evidence_snapshot_ids: list[str] | tuple[str, ...],
    citation_behavior: str,
) -> str:
    return stable_resource_contract_id(
        "projection",
        "WikiProjectionSpec",
        {
            "projection_kind": projection_kind,
            "graph_revision_id": graph_revision_id,
            "ontology_revision_id": ontology_revision_id,
            "title": title,
            "source_refs": list(source_refs),
            "evidence_snapshot_ids": list(evidence_snapshot_ids),
            "citation_behavior": citation_behavior,
        },
    )


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


def _validate_string_fields(value: dict[str, Any], fields: tuple[str, ...], name: str) -> None:
    # Do not allow contract ids or labels to be silently normalized through str().
    for field_name in fields:
        if field_name in value and not isinstance(value[field_name], str):
            raise ContractValidationError(f"{name}.{field_name} must be a string")


def _validate_optional_string_fields(
    value: dict[str, Any],
    fields: tuple[str, ...],
    name: str,
) -> None:
    for field_name in fields:
        if (
            field_name in value
            and value[field_name] is not None
            and not isinstance(value[field_name], str)
        ):
            raise ContractValidationError(f"{name}.{field_name} must be a string")


def _is_missing_optional_id(value: Any) -> bool:
    return value is None or value == ""


def _validate_string_list(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = True,
) -> None:
    if not isinstance(value, list):
        raise ContractValidationError(f"{field_name} must be a list")
    if not allow_empty and not value:
        raise ContractValidationError(f"{field_name} cannot be empty")
    if not all(isinstance(item, str) for item in value):
        raise ContractValidationError(f"{field_name} entries must be strings")


def _validate_non_empty_unique_string_list(value: Any, field_name: str) -> None:
    _validate_string_list(value, field_name, allow_empty=False)
    if any(not item for item in value):
        raise ContractValidationError(f"{field_name} entries must be non-empty strings")
    if len(set(value)) != len(value):
        raise ContractValidationError(f"{field_name} entries must be unique")


def _validate_provenance_id_list(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = True,
) -> None:
    _validate_string_list(value, field_name, allow_empty=allow_empty)
    for item in value:
        _validate_graph_reference_id(item, f"{field_name} entry")


def _validate_graph_reference_id(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    # Graph lineage stores stable record ids only; paths and locators belong behind retrieval APIs.
    if not _GRAPH_REFERENCE_ID.fullmatch(value):
        raise ContractValidationError(f"{field_name} must be a stable record id")


def _validate_confidence(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    if not 0 <= float(value) <= 1:
        raise ContractValidationError(f"{field_name} must be between 0 and 1")


def _validate_iso_timestamp(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{field_name} must be an ISO timestamp") from exc


def _validate_optional_iso_timestamp_fields(
    value: dict[str, Any],
    fields: tuple[str, ...],
    name: str,
) -> None:
    for field_name in fields:
        if field_name in value and value[field_name] is not None:
            _validate_iso_timestamp(value[field_name], f"{name}.{field_name}")


def _validate_formowl_locator(value: str, field_name: str) -> None:
    if not value.startswith("formowl://"):
        raise ContractValidationError(f"{field_name} must be a FormOwl locator")


def _validate_no_raw_public_reference(value: Any, field_name: str) -> None:
    if isinstance(value, str):
        for pattern in _RAW_PUBLIC_REFERENCE_PATTERNS:
            if pattern.search(value):
                raise ContractValidationError(
                    f"{field_name} must not contain raw paths, SQL, or private locators"
                )
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_no_raw_public_reference(str(key), field_name)
            _validate_no_raw_public_reference(item, field_name)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_no_raw_public_reference(item, field_name)


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
    projection_spec_id: str | None = None
    graph_revision_id: str | None = None
    ontology_revision_id: str | None = None
    user_graph_revision_id: str | None = None
    graph_view_hash: str | None = None
    evidence_snapshot_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class WikiProjectionSpec:
    projection_spec_id: str
    projection_kind: str
    title: str
    graph_revision_id: str
    ontology_revision_id: str
    source_refs: list[SourceRef | dict[str, Any]]
    evidence_snapshot_ids: list[str]
    citation_behavior: str
    redaction_policy: str
    created_by: str
    created_at: str
    projection_rules: dict[str, JsonValue] = field(default_factory=dict)
    user_graph_revision_id: str | None = None
    permission_scope: PermissionScope | dict[str, Any] | None = None
    draft_target: dict[str, JsonValue] | None = None
    include_private_evidence: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WikiProjectionSpec":
        spec = validate_wiki_projection_spec(value)
        return cls(
            projection_spec_id=str(spec["projection_spec_id"]),
            projection_kind=str(spec["projection_kind"]),
            title=str(spec["title"]),
            graph_revision_id=str(spec["graph_revision_id"]),
            ontology_revision_id=str(spec["ontology_revision_id"]),
            source_refs=list(spec["source_refs"]),
            evidence_snapshot_ids=list(spec["evidence_snapshot_ids"]),
            citation_behavior=str(spec["citation_behavior"]),
            redaction_policy=str(spec["redaction_policy"]),
            created_by=str(spec["created_by"]),
            created_at=str(spec["created_at"]),
            projection_rules=dict(spec.get("projection_rules", {})),
            user_graph_revision_id=spec.get("user_graph_revision_id"),
            permission_scope=spec.get("permission_scope"),
            draft_target=spec.get("draft_target"),
            include_private_evidence=bool(spec.get("include_private_evidence", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_wiki_projection_spec(data)
        return data


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


@dataclass(frozen=True)
class CandidateAtom:
    candidate_atom_id: str
    source_observation_ids: list[str]
    atom_type: str
    label: str
    properties: dict[str, JsonValue]
    confidence: float
    extractor_run_id: str
    status: CandidateStatus
    requires_review: bool = True
    source_semantic_metadata_ids: list[str] = field(default_factory=list)
    created_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CandidateAtom":
        atom = validate_candidate_atom(value)
        return cls(
            candidate_atom_id=str(atom["candidate_atom_id"]),
            source_observation_ids=list(atom["source_observation_ids"]),
            atom_type=str(atom["atom_type"]),
            label=str(atom["label"]),
            properties=dict(atom["properties"]),
            confidence=float(atom["confidence"]),
            extractor_run_id=str(atom["extractor_run_id"]),
            status=atom["status"],
            requires_review=bool(atom.get("requires_review", True)),
            source_semantic_metadata_ids=list(atom.get("source_semantic_metadata_ids", [])),
            created_at=atom.get("created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_candidate_atom(data)
        return data


@dataclass(frozen=True)
class CandidateRelation:
    candidate_relation_id: str
    source_candidate_atom_id: str
    target_candidate_atom_id: str
    relation_type: str
    source_observation_ids: list[str]
    properties: dict[str, JsonValue]
    confidence: float
    extractor_run_id: str
    status: CandidateStatus
    requires_review: bool = True
    source_semantic_metadata_ids: list[str] = field(default_factory=list)
    created_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CandidateRelation":
        relation = validate_candidate_relation(value)
        return cls(
            candidate_relation_id=str(relation["candidate_relation_id"]),
            source_candidate_atom_id=str(relation["source_candidate_atom_id"]),
            target_candidate_atom_id=str(relation["target_candidate_atom_id"]),
            relation_type=str(relation["relation_type"]),
            source_observation_ids=list(relation["source_observation_ids"]),
            properties=dict(relation["properties"]),
            confidence=float(relation["confidence"]),
            extractor_run_id=str(relation["extractor_run_id"]),
            status=relation["status"],
            requires_review=bool(relation.get("requires_review", True)),
            source_semantic_metadata_ids=list(relation.get("source_semantic_metadata_ids", [])),
            created_at=relation.get("created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_candidate_relation(data)
        return data


@dataclass(frozen=True)
class ExternalGraphImport:
    external_graph_import_id: str
    source_system: str
    source_ref: SourceRef | dict[str, Any]
    extractor_run_id: str
    imported_at: str
    candidate_atom_ids: list[str] = field(default_factory=list)
    candidate_relation_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExternalGraphImport":
        graph_import = validate_external_graph_import(value)
        return cls(
            external_graph_import_id=str(graph_import["external_graph_import_id"]),
            source_system=str(graph_import["source_system"]),
            source_ref=graph_import["source_ref"],
            extractor_run_id=str(graph_import["extractor_run_id"]),
            imported_at=str(graph_import["imported_at"]),
            candidate_atom_ids=list(graph_import.get("candidate_atom_ids", [])),
            candidate_relation_ids=list(graph_import.get("candidate_relation_ids", [])),
            warnings=list(graph_import.get("warnings", [])),
            errors=list(graph_import.get("errors", [])),
            metadata=dict(graph_import.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_external_graph_import(data)
        return data


@dataclass(frozen=True)
class User:
    user_id: str
    display_name: str
    status: UserStatus
    created_at: str
    email: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "User":
        user = validate_user(value)
        return cls(
            user_id=str(user["user_id"]),
            display_name=str(user["display_name"]),
            status=user["status"],
            created_at=str(user["created_at"]),
            email=user.get("email"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_user(data)
        return data


@dataclass(frozen=True)
class SessionIdentity:
    session_id: str
    selected_user_id: str
    selected_at: str
    selection_method: SessionSelectionMethod

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SessionIdentity":
        session_identity = validate_session_identity(value)
        return cls(
            session_id=str(session_identity["session_id"]),
            selected_user_id=str(session_identity["selected_user_id"]),
            selected_at=str(session_identity["selected_at"]),
            selection_method=session_identity["selection_method"],
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_session_identity(data)
        return data


@dataclass(frozen=True)
class WorkspaceMember:
    workspace_id: str
    user_id: str
    role: WorkspaceMemberRole

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkspaceMember":
        workspace_member = validate_workspace_member(value)
        return cls(
            workspace_id=str(workspace_member["workspace_id"]),
            user_id=str(workspace_member["user_id"]),
            role=workspace_member["role"],
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_workspace_member(data)
        return data


@dataclass(frozen=True)
class AccessRequest:
    request_id: str
    requester_user_id: str
    owner_user_id: str
    requested_scope_type: str
    requested_scope_id: str
    requested_access_level: str
    reason: str
    status: AccessRequestStatus
    created_at: str
    resolved_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AccessRequest":
        access_request = validate_access_request(value)
        return cls(
            request_id=str(access_request["request_id"]),
            requester_user_id=str(access_request["requester_user_id"]),
            owner_user_id=str(access_request["owner_user_id"]),
            requested_scope_type=str(access_request["requested_scope_type"]),
            requested_scope_id=str(access_request["requested_scope_id"]),
            requested_access_level=str(access_request["requested_access_level"]),
            reason=str(access_request["reason"]),
            status=access_request["status"],
            created_at=str(access_request["created_at"]),
            resolved_at=access_request.get("resolved_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_access_request(data)
        return data


@dataclass(frozen=True)
class Grant:
    grant_id: str
    owner_user_id: str
    grantee_user_id: str
    scope_type: str
    scope_id: str
    permission: str
    expires_at: str
    max_access_count: int | None = None
    revoked_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Grant":
        grant = validate_grant(value)
        return cls(
            grant_id=str(grant["grant_id"]),
            owner_user_id=str(grant["owner_user_id"]),
            grantee_user_id=str(grant["grantee_user_id"]),
            scope_type=str(grant["scope_type"]),
            scope_id=str(grant["scope_id"]),
            permission=str(grant["permission"]),
            expires_at=str(grant["expires_at"]),
            max_access_count=grant.get("max_access_count"),
            revoked_at=grant.get("revoked_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_grant(data)
        return data


@dataclass(frozen=True)
class AuditLog:
    audit_log_id: str
    actor_user_id: str
    action: str
    target_type: str
    target_id: str
    session_id: str
    timestamp: str
    grant_id: str | None = None
    workspace_id: str | None = None
    status: str | None = None
    metadata: dict[str, JsonValue] | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AuditLog":
        audit_log = validate_audit_log(value)
        return cls(
            audit_log_id=str(audit_log["audit_log_id"]),
            actor_user_id=str(audit_log["actor_user_id"]),
            action=str(audit_log["action"]),
            target_type=str(audit_log["target_type"]),
            target_id=str(audit_log["target_id"]),
            session_id=str(audit_log["session_id"]),
            timestamp=str(audit_log["timestamp"]),
            grant_id=audit_log.get("grant_id"),
            workspace_id=audit_log.get("workspace_id"),
            status=audit_log.get("status"),
            metadata=audit_log.get("metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_audit_log(data)
        return data


@dataclass(frozen=True)
class UploadSession:
    upload_session_id: str
    actor_user_id: str
    workspace_id: str
    owner_scope_type: str
    owner_scope_id: str
    intent: str
    intended_asset_type: str
    ingestion_profile: str
    visibility_scope: str
    permission_scope: PermissionScope | dict[str, Any]
    expires_at: str
    source_preparation_state: str
    processing_status: str
    status: UploadSessionStatus
    created_at: str
    audit_log_id: str
    project_id: str | None = None
    customer_id: str | None = None
    asset_id: str | None = None
    ingestion_job_id: str | None = None
    completed_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "UploadSession":
        upload_session = validate_upload_session(value)
        return cls(
            upload_session_id=str(upload_session["upload_session_id"]),
            actor_user_id=str(upload_session["actor_user_id"]),
            workspace_id=str(upload_session["workspace_id"]),
            owner_scope_type=str(upload_session["owner_scope_type"]),
            owner_scope_id=str(upload_session["owner_scope_id"]),
            intent=str(upload_session["intent"]),
            intended_asset_type=str(upload_session["intended_asset_type"]),
            ingestion_profile=str(upload_session["ingestion_profile"]),
            visibility_scope=str(upload_session["visibility_scope"]),
            permission_scope=upload_session["permission_scope"],
            expires_at=str(upload_session["expires_at"]),
            source_preparation_state=str(upload_session["source_preparation_state"]),
            processing_status=str(upload_session["processing_status"]),
            status=upload_session["status"],
            created_at=str(upload_session["created_at"]),
            audit_log_id=str(upload_session["audit_log_id"]),
            project_id=upload_session.get("project_id"),
            customer_id=upload_session.get("customer_id"),
            asset_id=upload_session.get("asset_id"),
            ingestion_job_id=upload_session.get("ingestion_job_id"),
            completed_at=upload_session.get("completed_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_upload_session(data)
        return data


def validate_source_ref(value: Any) -> dict[str, Any]:
    source_ref = _require_mapping(value, "SourceRef")
    _require_fields(source_ref, ("source_system", "source_type", "source_id"), "SourceRef")
    _validate_string_fields(
        source_ref,
        ("source_system", "source_type", "source_id"),
        "SourceRef",
    )
    _validate_optional_string_fields(
        source_ref,
        ("source_instance", "source_key", "source_url"),
        "SourceRef",
    )
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
    _validate_string_list(
        context_package.get("evidence_snapshot_ids", []),
        "ContextPackage.evidence_snapshot_ids",
    )
    if not isinstance(context_package.get("citations", []), list):
        raise ContractValidationError("ContextPackage.citations must be a list")
    return context_package


def validate_wiki_projection_spec(value: Any) -> dict[str, Any]:
    spec = _require_mapping(value, "WikiProjectionSpec")
    _require_fields(
        spec,
        (
            "projection_spec_id",
            "projection_kind",
            "title",
            "graph_revision_id",
            "ontology_revision_id",
            "source_refs",
            "evidence_snapshot_ids",
            "citation_behavior",
            "redaction_policy",
            "created_by",
            "created_at",
        ),
        "WikiProjectionSpec",
    )
    _validate_string_fields(
        spec,
        (
            "projection_spec_id",
            "projection_kind",
            "title",
            "graph_revision_id",
            "ontology_revision_id",
            "citation_behavior",
            "redaction_policy",
            "created_by",
            "created_at",
        ),
        "WikiProjectionSpec",
    )
    _validate_optional_string_fields(
        spec,
        ("user_graph_revision_id",),
        "WikiProjectionSpec",
    )
    _validate_graph_reference_id(
        spec["projection_spec_id"],
        "WikiProjectionSpec.projection_spec_id",
    )
    _validate_graph_reference_id(
        spec["graph_revision_id"],
        "WikiProjectionSpec.graph_revision_id",
    )
    _validate_graph_reference_id(
        spec["ontology_revision_id"],
        "WikiProjectionSpec.ontology_revision_id",
    )
    if spec.get("user_graph_revision_id") is not None:
        _validate_graph_reference_id(
            spec["user_graph_revision_id"],
            "WikiProjectionSpec.user_graph_revision_id",
        )
    _validate_iso_timestamp(spec["created_at"], "WikiProjectionSpec.created_at")
    if not isinstance(spec["source_refs"], list) or not spec["source_refs"]:
        raise ContractValidationError("WikiProjectionSpec.source_refs must be a non-empty list")
    for source_ref in spec["source_refs"]:
        validate_source_ref(source_ref)
    _validate_provenance_id_list(
        spec["evidence_snapshot_ids"],
        "WikiProjectionSpec.evidence_snapshot_ids",
        allow_empty=False,
    )
    if not isinstance(spec.get("projection_rules", {}), dict):
        raise ContractValidationError("WikiProjectionSpec.projection_rules must be an object")
    if spec.get("permission_scope") is not None:
        validate_permission_scope(spec["permission_scope"])
    if spec.get("draft_target") is not None and not isinstance(spec["draft_target"], dict):
        raise ContractValidationError("WikiProjectionSpec.draft_target must be an object")
    if not isinstance(spec.get("include_private_evidence", False), bool):
        raise ContractValidationError("WikiProjectionSpec.include_private_evidence must be boolean")
    if spec.get("include_private_evidence", False):
        raise ContractValidationError(
            "WikiProjectionSpec.include_private_evidence must stay false for public projection"
        )
    _validate_no_raw_public_reference(
        {
            "title": spec["title"],
            "projection_kind": spec["projection_kind"],
            "citation_behavior": spec["citation_behavior"],
            "redaction_policy": spec["redaction_policy"],
            "projection_rules": spec.get("projection_rules", {}),
            "draft_target": spec.get("draft_target") or {},
        },
        "WikiProjectionSpec",
    )
    return spec


def validate_permission_scope(value: Any) -> dict[str, Any]:
    permission_scope = _require_mapping(value, "PermissionScope")
    _require_fields(permission_scope, ("scope_type", "visibility"), "PermissionScope")
    _validate_string_fields(permission_scope, ("scope_type", "visibility"), "PermissionScope")
    _validate_optional_string_fields(
        permission_scope,
        ("scope_id", "inherited_from"),
        "PermissionScope",
    )
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
    _validate_string_fields(
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
    _validate_optional_string_fields(backend, ("root_prefix",), "StorageBackend")
    root_prefix = backend.get("root_prefix")
    if root_prefix is not None and not str(root_prefix).startswith("formowl://storage/"):
        raise ContractValidationError(
            "StorageBackend.root_prefix must be a FormOwl storage locator"
        )
    _validate_string_list(backend.get("allowed_workers", []), "StorageBackend.allowed_workers")
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
    _validate_string_fields(
        asset,
        (
            "asset_id",
            "storage_backend_id",
            "object_uri",
            "content_hash",
            "mime_type",
            "created_at",
            "registered_at",
            "owner_user_id",
            "workspace_id",
            "lifecycle_state",
        ),
        "Asset",
    )
    _validate_optional_string_fields(
        asset,
        ("original_filename", "project_id", "customer_id"),
        "Asset",
    )
    if not isinstance(asset["file_size"], int) or asset["file_size"] < 0:
        raise ContractValidationError("Asset.file_size must be a non-negative integer")
    _validate_formowl_locator(asset["object_uri"], "Asset.object_uri")
    validate_permission_scope(asset["permission_scope"])
    if "source_ref" in asset:
        validate_source_ref(asset["source_ref"])
    return asset


def validate_asset_metadata(value: Any) -> dict[str, Any]:
    metadata = _require_mapping(value, "AssetMetadata")
    _require_fields(metadata, ("asset_id", "metadata_type"), "AssetMetadata")
    _validate_string_fields(metadata, ("asset_id", "metadata_type"), "AssetMetadata")
    _validate_optional_string_fields(metadata, ("extractor_run_id",), "AssetMetadata")
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
    _validate_string_fields(
        job,
        (
            "ingestion_job_id",
            "asset_id",
            "status",
            "requested_by",
            "workspace_id",
            "created_at",
        ),
        "IngestionJob",
    )
    _validate_optional_string_fields(
        job,
        ("started_at", "completed_at", "error"),
        "IngestionJob",
    )
    _validate_iso_timestamp(job["created_at"], "IngestionJob.created_at")
    _validate_optional_iso_timestamp_fields(
        job,
        ("started_at", "completed_at"),
        "IngestionJob",
    )
    if job["status"] not in JOB_STATUS_VALUES:
        raise ContractValidationError("IngestionJob.status is not supported")
    validate_permission_scope(job["permission_scope"])
    _validate_non_empty_unique_string_list(
        job.get("extractor_names", []),
        "IngestionJob.extractor_names",
    )
    for field_name in ("extractor_run_ids", "observation_ids"):
        _validate_string_list(job.get(field_name, []), f"IngestionJob.{field_name}")
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
    _validate_string_fields(
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
    _validate_optional_string_fields(
        run,
        ("completed_at", "model_name", "model_version", "prompt_hash"),
        "ExtractorRun",
    )
    _validate_iso_timestamp(run["started_at"], "ExtractorRun.started_at")
    _validate_optional_iso_timestamp_fields(run, ("completed_at",), "ExtractorRun")
    if run["status"] not in EXTRACTOR_RUN_STATUS_VALUES:
        raise ContractValidationError("ExtractorRun.status is not supported")
    for field_name in ("warnings", "errors"):
        _validate_string_list(run.get(field_name, []), f"ExtractorRun.{field_name}")
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
    _validate_string_fields(
        observation,
        ("observation_id", "extractor_run_id", "observation_type", "modality", "created_at"),
        "Observation",
    )
    _validate_optional_string_fields(
        observation,
        ("asset_id", "evidence_snapshot_id", "text", "caption"),
        "Observation",
    )
    _validate_iso_timestamp(observation["created_at"], "Observation.created_at")
    if _is_missing_optional_id(observation.get("asset_id")) and _is_missing_optional_id(
        observation.get("evidence_snapshot_id")
    ):
        raise ContractValidationError("Observation requires asset_id or evidence_snapshot_id")
    if not isinstance(observation["location"], dict):
        raise ContractValidationError("Observation.location must be an object")
    _validate_confidence(observation["confidence"], "Observation.confidence")
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
    _validate_string_fields(
        metadata,
        ("semantic_metadata_id", "metadata_type", "extractor_run_id"),
        "SemanticMetadata",
    )
    _validate_optional_string_fields(metadata, ("created_at",), "SemanticMetadata")
    _validate_graph_reference_id(
        metadata["semantic_metadata_id"],
        "SemanticMetadata.semantic_metadata_id",
    )
    _validate_graph_reference_id(
        metadata["extractor_run_id"],
        "SemanticMetadata.extractor_run_id",
    )
    _validate_provenance_id_list(
        metadata["source_observation_ids"],
        "SemanticMetadata.source_observation_ids",
        allow_empty=False,
    )
    if not isinstance(metadata["value"], dict):
        raise ContractValidationError("SemanticMetadata.value must be an object")
    _validate_confidence(metadata["confidence"], "SemanticMetadata.confidence")
    if not isinstance(metadata["requires_review"], bool):
        raise ContractValidationError("SemanticMetadata.requires_review must be boolean")
    return metadata


def validate_candidate_atom(value: Any) -> dict[str, Any]:
    atom = _require_mapping(value, "CandidateAtom")
    _require_fields(
        atom,
        (
            "candidate_atom_id",
            "source_observation_ids",
            "atom_type",
            "label",
            "properties",
            "confidence",
            "extractor_run_id",
            "status",
            "requires_review",
        ),
        "CandidateAtom",
    )
    _validate_string_fields(
        atom,
        ("candidate_atom_id", "atom_type", "label", "extractor_run_id", "status"),
        "CandidateAtom",
    )
    _validate_optional_string_fields(atom, ("created_at",), "CandidateAtom")
    _validate_optional_iso_timestamp_fields(atom, ("created_at",), "CandidateAtom")
    _validate_graph_reference_id(atom["candidate_atom_id"], "CandidateAtom.candidate_atom_id")
    _validate_candidate_common(atom, "CandidateAtom")
    _validate_provenance_id_list(
        atom.get("source_semantic_metadata_ids", []),
        "CandidateAtom.source_semantic_metadata_ids",
    )
    return atom


def validate_candidate_relation(value: Any) -> dict[str, Any]:
    relation = _require_mapping(value, "CandidateRelation")
    _require_fields(
        relation,
        (
            "candidate_relation_id",
            "source_candidate_atom_id",
            "target_candidate_atom_id",
            "relation_type",
            "source_observation_ids",
            "properties",
            "confidence",
            "extractor_run_id",
            "status",
            "requires_review",
        ),
        "CandidateRelation",
    )
    _validate_string_fields(
        relation,
        (
            "candidate_relation_id",
            "source_candidate_atom_id",
            "target_candidate_atom_id",
            "relation_type",
            "extractor_run_id",
            "status",
        ),
        "CandidateRelation",
    )
    _validate_optional_string_fields(relation, ("created_at",), "CandidateRelation")
    _validate_optional_iso_timestamp_fields(relation, ("created_at",), "CandidateRelation")
    _validate_graph_reference_id(
        relation["candidate_relation_id"],
        "CandidateRelation.candidate_relation_id",
    )
    _validate_graph_reference_id(
        relation["source_candidate_atom_id"],
        "CandidateRelation.source_candidate_atom_id",
    )
    _validate_graph_reference_id(
        relation["target_candidate_atom_id"],
        "CandidateRelation.target_candidate_atom_id",
    )
    _validate_candidate_common(relation, "CandidateRelation")
    _validate_provenance_id_list(
        relation.get("source_semantic_metadata_ids", []),
        "CandidateRelation.source_semantic_metadata_ids",
    )
    return relation


def validate_external_graph_import(value: Any) -> dict[str, Any]:
    graph_import = _require_mapping(value, "ExternalGraphImport")
    _require_fields(
        graph_import,
        (
            "external_graph_import_id",
            "source_system",
            "source_ref",
            "extractor_run_id",
            "imported_at",
        ),
        "ExternalGraphImport",
    )
    _validate_string_fields(
        graph_import,
        ("external_graph_import_id", "source_system", "extractor_run_id", "imported_at"),
        "ExternalGraphImport",
    )
    validate_source_ref(graph_import["source_ref"])
    for field_name in (
        "candidate_atom_ids",
        "candidate_relation_ids",
        "warnings",
        "errors",
    ):
        _validate_string_list(
            graph_import.get(field_name, []),
            f"ExternalGraphImport.{field_name}",
        )
    if not isinstance(graph_import.get("metadata", {}), dict):
        raise ContractValidationError("ExternalGraphImport.metadata must be an object")
    return graph_import


def _validate_candidate_common(candidate: dict[str, Any], name: str) -> None:
    _validate_graph_reference_id(candidate["extractor_run_id"], f"{name}.extractor_run_id")
    _validate_provenance_id_list(
        candidate["source_observation_ids"],
        f"{name}.source_observation_ids",
        allow_empty=False,
    )
    if not isinstance(candidate["properties"], dict):
        raise ContractValidationError(f"{name}.properties must be an object")
    _validate_confidence(candidate["confidence"], f"{name}.confidence")
    if candidate["status"] not in CANDIDATE_STATUS_VALUES:
        raise ContractValidationError(f"{name}.status is not supported")
    if not isinstance(candidate["requires_review"], bool):
        raise ContractValidationError(f"{name}.requires_review must be boolean")


def validate_user(value: Any) -> dict[str, Any]:
    user = _require_mapping(value, "User")
    _require_fields(user, ("user_id", "display_name", "status", "created_at"), "User")
    _validate_string_fields(user, ("user_id", "display_name", "status", "created_at"), "User")
    _validate_optional_string_fields(user, ("email",), "User")
    if user["status"] not in USER_STATUS_VALUES:
        raise ContractValidationError("User.status is not supported")
    return user


def validate_session_identity(value: Any) -> dict[str, Any]:
    session_identity = _require_mapping(value, "SessionIdentity")
    _require_fields(
        session_identity,
        ("session_id", "selected_user_id", "selected_at", "selection_method"),
        "SessionIdentity",
    )
    _validate_string_fields(
        session_identity,
        ("session_id", "selected_user_id", "selected_at", "selection_method"),
        "SessionIdentity",
    )
    if session_identity["selection_method"] not in SESSION_SELECTION_METHOD_VALUES:
        raise ContractValidationError("SessionIdentity.selection_method is not supported")
    return session_identity


def validate_workspace_member(value: Any) -> dict[str, Any]:
    workspace_member = _require_mapping(value, "WorkspaceMember")
    _require_fields(workspace_member, ("workspace_id", "user_id", "role"), "WorkspaceMember")
    _validate_string_fields(
        workspace_member,
        ("workspace_id", "user_id", "role"),
        "WorkspaceMember",
    )
    if workspace_member["role"] not in WORKSPACE_MEMBER_ROLE_VALUES:
        raise ContractValidationError("WorkspaceMember.role is not supported")
    return workspace_member


def validate_access_request(value: Any) -> dict[str, Any]:
    access_request = _require_mapping(value, "AccessRequest")
    _require_fields(
        access_request,
        (
            "request_id",
            "requester_user_id",
            "owner_user_id",
            "requested_scope_type",
            "requested_scope_id",
            "requested_access_level",
            "reason",
            "status",
            "created_at",
        ),
        "AccessRequest",
    )
    _validate_string_fields(
        access_request,
        (
            "request_id",
            "requester_user_id",
            "owner_user_id",
            "requested_scope_type",
            "requested_scope_id",
            "requested_access_level",
            "reason",
            "status",
            "created_at",
        ),
        "AccessRequest",
    )
    _validate_optional_string_fields(
        access_request,
        ("decided_at", "decided_by"),
        "AccessRequest",
    )
    if access_request["status"] not in ACCESS_REQUEST_STATUS_VALUES:
        raise ContractValidationError("AccessRequest.status is not supported")
    return access_request


def validate_grant(value: Any) -> dict[str, Any]:
    grant = _require_mapping(value, "Grant")
    _require_fields(
        grant,
        (
            "grant_id",
            "owner_user_id",
            "grantee_user_id",
            "scope_type",
            "scope_id",
            "permission",
            "expires_at",
        ),
        "Grant",
    )
    _validate_string_fields(
        grant,
        (
            "grant_id",
            "owner_user_id",
            "grantee_user_id",
            "scope_type",
            "scope_id",
            "permission",
            "expires_at",
        ),
        "Grant",
    )
    _validate_optional_string_fields(grant, ("created_at", "revoked_at"), "Grant")
    if "max_access_count" in grant:
        max_access_count = grant["max_access_count"]
        if not isinstance(max_access_count, int) or max_access_count < 0:
            raise ContractValidationError("Grant.max_access_count must be a non-negative integer")
    return grant


def validate_audit_log(value: Any) -> dict[str, Any]:
    audit_log = _require_mapping(value, "AuditLog")
    _require_fields(
        audit_log,
        (
            "audit_log_id",
            "actor_user_id",
            "action",
            "target_type",
            "target_id",
            "session_id",
            "timestamp",
        ),
        "AuditLog",
    )
    _validate_string_fields(
        audit_log,
        (
            "audit_log_id",
            "actor_user_id",
            "action",
            "target_type",
            "target_id",
            "session_id",
            "timestamp",
        ),
        "AuditLog",
    )
    _validate_optional_string_fields(
        audit_log,
        ("grant_id", "workspace_id", "status"),
        "AuditLog",
    )
    if "metadata" in audit_log and not isinstance(audit_log["metadata"], dict):
        raise ContractValidationError("AuditLog.metadata must be an object")
    return audit_log


def validate_upload_session(value: Any) -> dict[str, Any]:
    upload_session = _require_mapping(value, "UploadSession")
    _require_fields(
        upload_session,
        (
            "upload_session_id",
            "actor_user_id",
            "workspace_id",
            "owner_scope_type",
            "owner_scope_id",
            "intent",
            "intended_asset_type",
            "ingestion_profile",
            "visibility_scope",
            "permission_scope",
            "expires_at",
            "source_preparation_state",
            "processing_status",
            "status",
            "created_at",
            "audit_log_id",
        ),
        "UploadSession",
    )
    _validate_string_fields(
        upload_session,
        (
            "upload_session_id",
            "actor_user_id",
            "workspace_id",
            "owner_scope_type",
            "owner_scope_id",
            "intent",
            "intended_asset_type",
            "ingestion_profile",
            "visibility_scope",
            "expires_at",
            "source_preparation_state",
            "processing_status",
            "status",
            "created_at",
            "audit_log_id",
        ),
        "UploadSession",
    )
    _validate_optional_string_fields(
        upload_session,
        ("project_id", "customer_id", "asset_id", "ingestion_job_id", "completed_at"),
        "UploadSession",
    )
    if upload_session["status"] not in UPLOAD_SESSION_STATUS_VALUES:
        raise ContractValidationError("UploadSession.status is not supported")
    validate_permission_scope(upload_session["permission_scope"])
    return upload_session
