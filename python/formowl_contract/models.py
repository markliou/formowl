from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from datetime import datetime
import re
from typing import Any, Literal

from .primitives import (
    ContractValidationError,
    JsonValue,
    canonical_json as canonical_json,
    from_plain as from_plain,
    now_iso as now_iso,
    sha256_json as sha256_json,
    stable_asset_id as stable_asset_id,
    stable_asset_metadata_hash as stable_asset_metadata_hash,
    stable_candidate_atom_id as stable_candidate_atom_id,
    stable_candidate_relation_id as stable_candidate_relation_id,
    stable_canonical_atom_id as stable_canonical_atom_id,
    stable_canonical_entity_id as stable_canonical_entity_id,
    stable_canonical_graph_revision_id as stable_canonical_graph_revision_id,
    stable_canonical_relation_id as stable_canonical_relation_id,
    stable_external_graph_import_id as stable_external_graph_import_id,
    stable_extractor_run_id as stable_extractor_run_id,
    stable_ingestion_job_id as stable_ingestion_job_id,
    stable_observation_id as stable_observation_id,
    stable_policy_id as stable_policy_id,
    stable_resource_contract_hash as stable_resource_contract_hash,
    stable_resource_contract_id as stable_resource_contract_id,
    stable_semantic_metadata_id as stable_semantic_metadata_id,
    stable_storage_backend_id as stable_storage_backend_id,
    stable_type_alias_id as stable_type_alias_id,
    stable_type_alignment_candidate_id as stable_type_alignment_candidate_id,
    stable_type_definition_id as stable_type_definition_id,
    stable_type_mapping_id as stable_type_mapping_id,
    stable_upload_session_id as stable_upload_session_id,
    stable_user_graph_assembly_policy_id as stable_user_graph_assembly_policy_id,
    stable_user_graph_profile_id as stable_user_graph_profile_id,
    stable_user_knowledge_graph_revision_id as stable_user_knowledge_graph_revision_id,
    stable_wiki_projection_spec_id as stable_wiki_projection_spec_id,
    to_plain,
)

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
CANONICAL_RECORD_STATUS_VALUES = ("active", "deprecated", "superseded", "archived")
CANONICAL_GRAPH_REVISION_STATUS_VALUES = ("draft", "committed", "superseded", "archived")
POLICY_STATUS_VALUES = ("draft", "active", "deprecated", "archived")
USER_GRAPH_PROFILE_STATUS_VALUES = ("active", "archived")
USER_GRAPH_REVISION_STATUS_VALUES = ("draft", "reviewed", "published", "archived")
TYPE_TIER_VALUES = ("core", "extension", "promoted")
TYPE_STATUS_VALUES = ("candidate", "active", "deprecated", "archived")
COORDINATION_FRAME_TYPES = (
    "Request",
    "Commitment",
    "Decision",
    "Assignment",
    "StatusUpdate",
    "StatusChange",
    "Blocker",
    "Risk",
    "Issue",
    "OpenQuestion",
    "Deadline",
    "Dependency",
    "Escalation",
    "Change",
    "Exception",
    "Constraint",
)
COORDINATION_OBJECT_SUPERTYPE_IDS = (
    "Actor",
    "WorkObject",
    "EvidenceObject",
    "DomainObject",
)
CORE_SUPERTYPE_IDS = (
    "Person",
    "Organization",
    "Project",
    "Artifact",
    "Document",
    "Event",
    "Concept",
    "Location",
)
JobStatus = Literal[*JOB_STATUS_VALUES]
ExtractorRunStatus = Literal[*EXTRACTOR_RUN_STATUS_VALUES]
UserStatus = Literal[*USER_STATUS_VALUES]
SessionSelectionMethod = Literal[*SESSION_SELECTION_METHOD_VALUES]
WorkspaceMemberRole = Literal[*WORKSPACE_MEMBER_ROLE_VALUES]
AccessRequestStatus = Literal[*ACCESS_REQUEST_STATUS_VALUES]
UploadSessionStatus = Literal[*UPLOAD_SESSION_STATUS_VALUES]
CandidateStatus = Literal[*CANDIDATE_STATUS_VALUES]
CanonicalRecordStatus = Literal[*CANONICAL_RECORD_STATUS_VALUES]
CanonicalGraphRevisionStatus = Literal[*CANONICAL_GRAPH_REVISION_STATUS_VALUES]
PolicyStatus = Literal[*POLICY_STATUS_VALUES]
UserGraphProfileStatus = Literal[*USER_GRAPH_PROFILE_STATUS_VALUES]
UserGraphRevisionStatus = Literal[*USER_GRAPH_REVISION_STATUS_VALUES]
TypeTier = Literal[*TYPE_TIER_VALUES]
TypeStatus = Literal[*TYPE_STATUS_VALUES]
CoordinationFrameType = Literal[*COORDINATION_FRAME_TYPES]
CoordinationObjectSupertype = Literal[*COORDINATION_OBJECT_SUPERTYPE_IDS]
_GRAPH_REFERENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RAW_SQL_REFERENCE_PATTERN = re.compile(
    r"\bselect\b[\s\S]{0,300}\bfrom\b|"
    r"\bwith\b[\s\S]{0,300}\bas\s*\(|"
    r"\bcopy\b[\s\S]{0,300}\b(from|to)\b|"
    r"\binsert\b\s+into\b|"
    r"\bupdate\b\s+[A-Za-z_][A-Za-z0-9_.]*\s+\bset\b|"
    r"\bdelete\b\s+from\b|"
    r"\bdrop\b\s+(table|schema|database|index|view)\b|"
    r"\balter\b\s+(table|schema|database|index|view)\b",
    re.IGNORECASE,
)
_RAW_REFERENCE_BOUNDARY = r"(^|[\s'\"(\[{=,])"
_RAW_RELATIVE_PATH_PREFIXES = (
    "assets",
    "customer",
    "data",
    "docs",
    "files",
    "home",
    "mnt",
    "nas",
    "private",
    "raw",
    "root",
    "scratch",
    "secret",
    "secrets",
    "share",
    "srv",
    "tmp",
    "var",
    "volumes",
    "workspace",
)
_RAW_PUBLIC_REFERENCE_PATTERNS = (
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(_RAW_REFERENCE_BOUNDARY + r"\\\\[A-Za-z0-9_.-]+\\[A-Za-z0-9$_.-]+"),
    re.compile(_RAW_REFERENCE_BOUNDARY + r"//[A-Za-z0-9_.-]+/[A-Za-z0-9$_.-]+"),
    re.compile(_RAW_REFERENCE_BOUNDARY + r"/(?!/)(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+"),
    re.compile(
        _RAW_REFERENCE_BOUNDARY
        + r"(?!https?:[\\/]{2})\.{1,2}[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*"
    ),
    re.compile(
        _RAW_REFERENCE_BOUNDARY
        + r"~(?:[A-Za-z0-9_.-]+)?[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*"
    ),
    re.compile(
        _RAW_REFERENCE_BOUNDARY
        + r"(?:"
        + "|".join(_RAW_RELATIVE_PATH_PREFIXES)
        + r")[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*",
        re.IGNORECASE,
    ),
    re.compile(r"\b(file|smb|nfs|postgres|postgresql|mysql|sqlite)://", re.IGNORECASE),
    _RAW_SQL_REFERENCE_PATTERN,
)
_USER_GRAPH_RAW_REFERENCE_BOUNDARY = r"(^|[\s'\"(\[{=:,])"
_USER_GRAPH_RELATIVE_PATH_PREFIXES = (
    "assets",
    "customer",
    "data",
    "docs",
    "files",
    "home",
    "mnt",
    "nas",
    "private",
    "raw",
    "root",
    "scratch",
    "secret",
    "secrets",
    "share",
    "srv",
    "tmp",
    "workspace",
)
_USER_GRAPH_RAW_REFERENCE_PATTERNS = (
    re.compile(_USER_GRAPH_RAW_REFERENCE_BOUNDARY + r"\\\\[A-Za-z0-9_.-]+\\"),
    re.compile(r"(^|[^A-Za-z])[A-Za-z]:[\\/]"),
    re.compile(_USER_GRAPH_RAW_REFERENCE_BOUNDARY + r"/(?!/)(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+"),
    re.compile(
        _USER_GRAPH_RAW_REFERENCE_BOUNDARY + r"(?!https?:[\\/]{2})"
        r"\.{1,2}[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*",
    ),
    re.compile(
        _USER_GRAPH_RAW_REFERENCE_BOUNDARY
        + r"(?!https?:[\\/]{2})(?:"
        + "|".join(_USER_GRAPH_RELATIVE_PATH_PREFIXES)
        + r")[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*",
        re.IGNORECASE,
    ),
    re.compile(
        _USER_GRAPH_RAW_REFERENCE_BOUNDARY + r"(?!https?:[\\/]{2})"
        r"[A-Za-z0-9_.-]+[\\/]+[A-Za-z0-9_.-]+(?:[\\/]+[A-Za-z0-9_.-]+)*"
        r"\.[A-Za-z0-9]{2,8}\b",
    ),
    re.compile(r"\b(?!https?://)[A-Za-z][A-Za-z0-9+.-]*://", re.IGNORECASE),
    re.compile(r"\bformowl://(asset|object|storage|worker|evidence)\b", re.IGNORECASE),
    re.compile(r"\b(select|with|copy|insert|update|delete|drop|alter)\b\s+", re.IGNORECASE),
)
_USER_GRAPH_RESERVED_METADATA_PATTERNS = (
    re.compile(r"\baccess[_\s-]*overlay(?=$|[^A-Za-z0-9]|_)", re.IGNORECASE),
    re.compile(r"\bcanonical[_\s-]*merge(?=$|[^A-Za-z0-9]|_)", re.IGNORECASE),
    re.compile(r"\bwiki[_\s-]*revision(?=$|[^A-Za-z0-9]|_)", re.IGNORECASE),
    re.compile(r"\bgrant[_\s-]*id(?=$|[^A-Za-z0-9]|_)", re.IGNORECASE),
    re.compile(r"\braw[_\s-]*asset(?=$|[^A-Za-z0-9]|_)", re.IGNORECASE),
    re.compile(
        r"\bgraph[_\s-]*store[_\s-]*(mutation|mutate|write|created|create|update|commit|persist)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bcanonical[_\s-]*graph[_\s-]*(mutation|mutate|write|created|create|update|commit|persist)",
        re.IGNORECASE,
    ),
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


def _validate_unique_provenance_id_list(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = True,
) -> None:
    _validate_provenance_id_list(value, field_name, allow_empty=allow_empty)
    if len(set(value)) != len(value):
        raise ContractValidationError(f"{field_name} entries must be unique")


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


def stable_candidate_mention_id(
    *,
    source_observation_ids: list[str],
    mention_type: str,
    normalized_label: str,
    location: dict[str, JsonValue],
    extractor_run_id: str,
) -> str:
    return stable_resource_contract_id(
        "cmention",
        "CandidateMention",
        {
            "source_observation_ids": sorted(source_observation_ids),
            "mention_type": mention_type,
            "normalized_label": normalized_label,
            "location": location,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_candidate_business_object_id(
    *,
    source_observation_ids: list[str],
    object_type: str,
    label: str,
    properties: dict[str, JsonValue],
    extractor_run_id: str,
) -> str:
    return stable_resource_contract_id(
        "cbobj",
        "CandidateBusinessObject",
        {
            "source_observation_ids": sorted(source_observation_ids),
            "object_type": object_type,
            "label": label,
            "properties": properties,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_candidate_frame_id(
    *,
    source_observation_ids: list[str],
    frame_type: str,
    slots: dict[str, JsonValue],
    evidence_spans: list[dict[str, JsonValue]],
    extractor_run_id: str,
) -> str:
    return stable_resource_contract_id(
        "cframe",
        "CandidateFrame",
        {
            "source_observation_ids": sorted(source_observation_ids),
            "frame_type": frame_type,
            "slots": slots,
            "evidence_spans": evidence_spans,
            "extractor_run_id": extractor_run_id,
        },
    )


def stable_canonical_frame_id(
    *,
    scope_type: str,
    scope_id: str,
    ontology_revision_id: str,
    frame_type: str,
    canonical_slots: dict[str, JsonValue],
    source_candidate_frame_ids: list[str],
) -> str:
    return stable_resource_contract_id(
        "canframe",
        "CanonicalFrame",
        {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "ontology_revision_id": ontology_revision_id,
            "frame_type": frame_type,
            "canonical_slots": canonical_slots,
            "source_candidate_frame_ids": sorted(source_candidate_frame_ids),
        },
    )


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
class TypeDefinition:
    type_id: str
    tier: TypeTier
    core_supertype_id: str
    pref_label: str
    scope_type: str
    scope_id: str
    status: TypeStatus
    ontology_revision_id: str
    confidence: float
    created_at: str
    created_by: str
    alt_labels: list[str] = field(default_factory=list)
    broader_type_ids: list[str] = field(default_factory=list)
    narrower_type_ids: list[str] = field(default_factory=list)
    related_type_ids: list[str] = field(default_factory=list)
    source_observation_ids: list[str] = field(default_factory=list)
    source_candidate_ids: list[str] = field(default_factory=list)
    description: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TypeDefinition":
        type_definition = validate_type_definition(value)
        return cls(
            type_id=str(type_definition["type_id"]),
            tier=type_definition["tier"],
            core_supertype_id=str(type_definition["core_supertype_id"]),
            pref_label=str(type_definition["pref_label"]),
            scope_type=str(type_definition["scope_type"]),
            scope_id=str(type_definition["scope_id"]),
            status=type_definition["status"],
            ontology_revision_id=str(type_definition["ontology_revision_id"]),
            confidence=float(type_definition["confidence"]),
            created_at=str(type_definition["created_at"]),
            created_by=str(type_definition["created_by"]),
            alt_labels=list(type_definition.get("alt_labels", [])),
            broader_type_ids=list(type_definition.get("broader_type_ids", [])),
            narrower_type_ids=list(type_definition.get("narrower_type_ids", [])),
            related_type_ids=list(type_definition.get("related_type_ids", [])),
            source_observation_ids=list(type_definition.get("source_observation_ids", [])),
            source_candidate_ids=list(type_definition.get("source_candidate_ids", [])),
            description=type_definition.get("description"),
            metadata=dict(type_definition.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_type_definition(data)
        return data


@dataclass(frozen=True)
class TypeAlias:
    alias_id: str
    type_id: str
    alias_label: str
    scope_type: str
    scope_id: str
    status: TypeStatus
    ontology_revision_id: str
    confidence: float
    created_at: str
    created_by: str
    source_candidate_ids: list[str] = field(default_factory=list)
    language: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TypeAlias":
        alias = validate_type_alias(value)
        return cls(
            alias_id=str(alias["alias_id"]),
            type_id=str(alias["type_id"]),
            alias_label=str(alias["alias_label"]),
            scope_type=str(alias["scope_type"]),
            scope_id=str(alias["scope_id"]),
            status=alias["status"],
            ontology_revision_id=str(alias["ontology_revision_id"]),
            confidence=float(alias["confidence"]),
            created_at=str(alias["created_at"]),
            created_by=str(alias["created_by"]),
            source_candidate_ids=list(alias.get("source_candidate_ids", [])),
            language=alias.get("language"),
            metadata=dict(alias.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_type_alias(data)
        return data


@dataclass(frozen=True)
class TypeMapping:
    mapping_id: str
    source_type_id: str
    target_core_supertype_id: str
    scope_type: str
    scope_id: str
    status: TypeStatus
    ontology_revision_id: str
    confidence: float
    created_at: str
    created_by: str
    source_candidate_ids: list[str] = field(default_factory=list)
    review_event_id: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TypeMapping":
        mapping = validate_type_mapping(value)
        return cls(
            mapping_id=str(mapping["mapping_id"]),
            source_type_id=str(mapping["source_type_id"]),
            target_core_supertype_id=str(mapping["target_core_supertype_id"]),
            scope_type=str(mapping["scope_type"]),
            scope_id=str(mapping["scope_id"]),
            status=mapping["status"],
            ontology_revision_id=str(mapping["ontology_revision_id"]),
            confidence=float(mapping["confidence"]),
            created_at=str(mapping["created_at"]),
            created_by=str(mapping["created_by"]),
            source_candidate_ids=list(mapping.get("source_candidate_ids", [])),
            review_event_id=mapping.get("review_event_id"),
            metadata=dict(mapping.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_type_mapping(data)
        return data


@dataclass(frozen=True)
class TypeAlignmentCandidate:
    alignment_candidate_id: str
    source_type_id: str
    target_type_id: str
    source_scope_type: str
    source_scope_id: str
    target_scope_type: str
    target_scope_id: str
    ontology_revision_id: str
    score: float
    score_breakdown: dict[str, JsonValue]
    evidence_links: list[dict[str, JsonValue]]
    status: CandidateStatus
    requires_review: bool
    created_at: str
    created_by: str
    canonical_type_write_allowed: bool = False
    access_grant_id: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TypeAlignmentCandidate":
        candidate = validate_type_alignment_candidate(value)
        return cls(
            alignment_candidate_id=str(candidate["alignment_candidate_id"]),
            source_type_id=str(candidate["source_type_id"]),
            target_type_id=str(candidate["target_type_id"]),
            source_scope_type=str(candidate["source_scope_type"]),
            source_scope_id=str(candidate["source_scope_id"]),
            target_scope_type=str(candidate["target_scope_type"]),
            target_scope_id=str(candidate["target_scope_id"]),
            ontology_revision_id=str(candidate["ontology_revision_id"]),
            score=float(candidate["score"]),
            score_breakdown=dict(candidate["score_breakdown"]),
            evidence_links=list(candidate["evidence_links"]),
            status=candidate["status"],
            requires_review=bool(candidate["requires_review"]),
            created_at=str(candidate["created_at"]),
            created_by=str(candidate["created_by"]),
            canonical_type_write_allowed=bool(candidate.get("canonical_type_write_allowed", False)),
            access_grant_id=candidate.get("access_grant_id"),
            metadata=dict(candidate.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_type_alignment_candidate(data)
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
class CandidateMention:
    candidate_mention_id: str
    source_observation_ids: list[str]
    mention_type: str
    normalized_label: str
    location: dict[str, JsonValue]
    text_hash: str
    confidence: float
    extractor_run_id: str
    status: CandidateStatus
    requires_review: bool = True
    created_at: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CandidateMention":
        mention = validate_candidate_mention(value)
        return cls(
            candidate_mention_id=str(mention["candidate_mention_id"]),
            source_observation_ids=list(mention["source_observation_ids"]),
            mention_type=str(mention["mention_type"]),
            normalized_label=str(mention["normalized_label"]),
            location=dict(mention["location"]),
            text_hash=str(mention["text_hash"]),
            confidence=float(mention["confidence"]),
            extractor_run_id=str(mention["extractor_run_id"]),
            status=mention["status"],
            requires_review=bool(mention.get("requires_review", True)),
            created_at=mention.get("created_at"),
            metadata=dict(mention.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_candidate_mention(data)
        return data


@dataclass(frozen=True)
class CandidateBusinessObject:
    candidate_business_object_id: str
    source_observation_ids: list[str]
    object_type: str
    object_supertype: CoordinationObjectSupertype
    label: str
    domain_hints: list[str]
    properties: dict[str, JsonValue]
    granularity_level: str
    access_boundary: dict[str, JsonValue]
    confidence: float
    extractor_run_id: str
    status: CandidateStatus
    requires_review: bool = True
    source_candidate_mention_ids: list[str] = field(default_factory=list)
    created_at: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CandidateBusinessObject":
        business_object = validate_candidate_business_object(value)
        return cls(
            candidate_business_object_id=str(business_object["candidate_business_object_id"]),
            source_observation_ids=list(business_object["source_observation_ids"]),
            object_type=str(business_object["object_type"]),
            object_supertype=business_object["object_supertype"],
            label=str(business_object["label"]),
            domain_hints=list(business_object["domain_hints"]),
            properties=dict(business_object["properties"]),
            granularity_level=str(business_object["granularity_level"]),
            access_boundary=dict(business_object["access_boundary"]),
            confidence=float(business_object["confidence"]),
            extractor_run_id=str(business_object["extractor_run_id"]),
            status=business_object["status"],
            requires_review=bool(business_object.get("requires_review", True)),
            source_candidate_mention_ids=list(
                business_object.get("source_candidate_mention_ids", [])
            ),
            created_at=business_object.get("created_at"),
            metadata=dict(business_object.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_candidate_business_object(data)
        return data


@dataclass(frozen=True)
class CandidateFrame:
    candidate_frame_id: str
    source_observation_ids: list[str]
    frame_type: CoordinationFrameType
    slots: dict[str, JsonValue]
    evidence_spans: list[dict[str, JsonValue]]
    domain_hints: list[str]
    granularity_level: str
    access_boundary: dict[str, JsonValue]
    confidence: float
    extractor_run_id: str
    ontology_revision_id: str
    status: CandidateStatus
    requires_review: bool = True
    source_candidate_mention_ids: list[str] = field(default_factory=list)
    candidate_business_object_ids: list[str] = field(default_factory=list)
    created_at: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CandidateFrame":
        frame = validate_candidate_frame(value)
        return cls(
            candidate_frame_id=str(frame["candidate_frame_id"]),
            source_observation_ids=list(frame["source_observation_ids"]),
            frame_type=frame["frame_type"],
            slots=dict(frame["slots"]),
            evidence_spans=list(frame["evidence_spans"]),
            domain_hints=list(frame["domain_hints"]),
            granularity_level=str(frame["granularity_level"]),
            access_boundary=dict(frame["access_boundary"]),
            confidence=float(frame["confidence"]),
            extractor_run_id=str(frame["extractor_run_id"]),
            ontology_revision_id=str(frame["ontology_revision_id"]),
            status=frame["status"],
            requires_review=bool(frame.get("requires_review", True)),
            source_candidate_mention_ids=list(frame.get("source_candidate_mention_ids", [])),
            candidate_business_object_ids=list(frame.get("candidate_business_object_ids", [])),
            created_at=frame.get("created_at"),
            metadata=dict(frame.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_candidate_frame(data)
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
    candidate_mention_ids: list[str] = field(default_factory=list)
    candidate_business_object_ids: list[str] = field(default_factory=list)
    candidate_frame_ids: list[str] = field(default_factory=list)
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
            candidate_mention_ids=list(graph_import.get("candidate_mention_ids", [])),
            candidate_business_object_ids=list(
                graph_import.get("candidate_business_object_ids", [])
            ),
            candidate_frame_ids=list(graph_import.get("candidate_frame_ids", [])),
            warnings=list(graph_import.get("warnings", [])),
            errors=list(graph_import.get("errors", [])),
            metadata=dict(graph_import.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_external_graph_import(data)
        return data


@dataclass(frozen=True)
class CanonicalFrame:
    canonical_frame_id: str
    scope_type: str
    scope_id: str
    frame_type: CoordinationFrameType
    canonical_slots: dict[str, JsonValue]
    evidence_spans: list[dict[str, JsonValue]]
    domain_hints: list[str]
    granularity_level: str
    access_boundary: dict[str, JsonValue]
    status: CanonicalRecordStatus
    source_candidate_frame_ids: list[str]
    source_observation_ids: list[str]
    confidence: float
    ontology_revision_id: str
    frame_policy_id: str
    created_at: str
    created_by: str
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CanonicalFrame":
        frame = validate_canonical_frame(value)
        return cls(
            canonical_frame_id=str(frame["canonical_frame_id"]),
            scope_type=str(frame["scope_type"]),
            scope_id=str(frame["scope_id"]),
            frame_type=frame["frame_type"],
            canonical_slots=dict(frame["canonical_slots"]),
            evidence_spans=list(frame["evidence_spans"]),
            domain_hints=list(frame["domain_hints"]),
            granularity_level=str(frame["granularity_level"]),
            access_boundary=dict(frame["access_boundary"]),
            status=frame["status"],
            source_candidate_frame_ids=list(frame["source_candidate_frame_ids"]),
            source_observation_ids=list(frame["source_observation_ids"]),
            confidence=float(frame["confidence"]),
            ontology_revision_id=str(frame["ontology_revision_id"]),
            frame_policy_id=str(frame["frame_policy_id"]),
            created_at=str(frame["created_at"]),
            created_by=str(frame["created_by"]),
            metadata=dict(frame.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_canonical_frame(data)
        return data


@dataclass(frozen=True)
class CanonicalAtom:
    canonical_atom_id: str
    scope_type: str
    scope_id: str
    atom_type: str
    canonical_text: str
    granularity_level: str
    status: CanonicalRecordStatus
    source_candidate_atom_ids: list[str]
    source_observation_ids: list[str]
    source_refs: list[SourceRef | dict[str, Any]]
    evidence_snapshot_ids: list[str]
    citations: list[Citation | dict[str, Any]]
    content_hash: str
    extraction_policy_id: str
    granularity_policy_id: str
    confidence: float
    created_at: str
    parent_atom_ids: list[str] = field(default_factory=list)
    child_atom_ids: list[str] = field(default_factory=list)
    related_atom_ids: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    language: str | None = None
    domain: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CanonicalAtom":
        atom = validate_canonical_atom(value)
        return cls(
            canonical_atom_id=str(atom["canonical_atom_id"]),
            scope_type=str(atom["scope_type"]),
            scope_id=str(atom["scope_id"]),
            atom_type=str(atom["atom_type"]),
            canonical_text=str(atom["canonical_text"]),
            granularity_level=str(atom["granularity_level"]),
            status=atom["status"],
            source_candidate_atom_ids=list(atom["source_candidate_atom_ids"]),
            source_observation_ids=list(atom["source_observation_ids"]),
            source_refs=list(atom["source_refs"]),
            evidence_snapshot_ids=list(atom["evidence_snapshot_ids"]),
            citations=list(atom["citations"]),
            content_hash=str(atom["content_hash"]),
            extraction_policy_id=str(atom["extraction_policy_id"]),
            granularity_policy_id=str(atom["granularity_policy_id"]),
            confidence=float(atom["confidence"]),
            created_at=str(atom["created_at"]),
            parent_atom_ids=list(atom.get("parent_atom_ids", [])),
            child_atom_ids=list(atom.get("child_atom_ids", [])),
            related_atom_ids=list(atom.get("related_atom_ids", [])),
            labels=list(atom.get("labels", [])),
            language=atom.get("language"),
            domain=atom.get("domain"),
            metadata=dict(atom.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_canonical_atom(data)
        return data


@dataclass(frozen=True)
class CanonicalEntity:
    canonical_entity_id: str
    scope_type: str
    scope_id: str
    entity_type: str
    canonical_label: str
    status: CanonicalRecordStatus
    source_candidate_atom_ids: list[str]
    source_observation_ids: list[str]
    source_refs: list[SourceRef | dict[str, Any]]
    evidence_snapshot_ids: list[str]
    citations: list[Citation | dict[str, Any]]
    confidence: float
    ontology_revision_id: str
    created_at: str
    aliases: list[str] = field(default_factory=list)
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CanonicalEntity":
        entity = validate_canonical_entity(value)
        return cls(
            canonical_entity_id=str(entity["canonical_entity_id"]),
            scope_type=str(entity["scope_type"]),
            scope_id=str(entity["scope_id"]),
            entity_type=str(entity["entity_type"]),
            canonical_label=str(entity["canonical_label"]),
            status=entity["status"],
            source_candidate_atom_ids=list(entity["source_candidate_atom_ids"]),
            source_observation_ids=list(entity["source_observation_ids"]),
            source_refs=list(entity["source_refs"]),
            evidence_snapshot_ids=list(entity["evidence_snapshot_ids"]),
            citations=list(entity["citations"]),
            confidence=float(entity["confidence"]),
            ontology_revision_id=str(entity["ontology_revision_id"]),
            created_at=str(entity["created_at"]),
            aliases=list(entity.get("aliases", [])),
            metadata=dict(entity.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_canonical_entity(data)
        return data


@dataclass(frozen=True)
class CanonicalRelation:
    canonical_relation_id: str
    scope_type: str
    scope_id: str
    source_id: str
    target_id: str
    relation_type: str
    status: CanonicalRecordStatus
    source_candidate_relation_ids: list[str]
    source_observation_ids: list[str]
    source_refs: list[SourceRef | dict[str, Any]]
    evidence_snapshot_ids: list[str]
    citations: list[Citation | dict[str, Any]]
    confidence: float
    ontology_revision_id: str
    created_at: str
    properties: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CanonicalRelation":
        relation = validate_canonical_relation(value)
        return cls(
            canonical_relation_id=str(relation["canonical_relation_id"]),
            scope_type=str(relation["scope_type"]),
            scope_id=str(relation["scope_id"]),
            source_id=str(relation["source_id"]),
            target_id=str(relation["target_id"]),
            relation_type=str(relation["relation_type"]),
            status=relation["status"],
            source_candidate_relation_ids=list(relation["source_candidate_relation_ids"]),
            source_observation_ids=list(relation["source_observation_ids"]),
            source_refs=list(relation["source_refs"]),
            evidence_snapshot_ids=list(relation["evidence_snapshot_ids"]),
            citations=list(relation["citations"]),
            confidence=float(relation["confidence"]),
            ontology_revision_id=str(relation["ontology_revision_id"]),
            created_at=str(relation["created_at"]),
            properties=dict(relation.get("properties", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_canonical_relation(data)
        return data


@dataclass(frozen=True)
class CanonicalGraphRevision:
    canonical_graph_revision_id: str
    scope_type: str
    scope_id: str
    ontology_revision_id: str
    status: CanonicalGraphRevisionStatus
    canonical_atom_ids: list[str]
    canonical_entity_ids: list[str]
    canonical_relation_ids: list[str]
    created_at: str
    created_by: str
    parent_revision_id: str | None = None
    source_candidate_atom_ids: list[str] = field(default_factory=list)
    source_candidate_relation_ids: list[str] = field(default_factory=list)
    policy_ids: list[str] = field(default_factory=list)
    commit_metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CanonicalGraphRevision":
        revision = validate_canonical_graph_revision(value)
        return cls(
            canonical_graph_revision_id=str(revision["canonical_graph_revision_id"]),
            scope_type=str(revision["scope_type"]),
            scope_id=str(revision["scope_id"]),
            ontology_revision_id=str(revision["ontology_revision_id"]),
            status=revision["status"],
            canonical_atom_ids=list(revision["canonical_atom_ids"]),
            canonical_entity_ids=list(revision["canonical_entity_ids"]),
            canonical_relation_ids=list(revision["canonical_relation_ids"]),
            created_at=str(revision["created_at"]),
            created_by=str(revision["created_by"]),
            parent_revision_id=revision.get("parent_revision_id"),
            source_candidate_atom_ids=list(revision.get("source_candidate_atom_ids", [])),
            source_candidate_relation_ids=list(revision.get("source_candidate_relation_ids", [])),
            policy_ids=list(revision.get("policy_ids", [])),
            commit_metadata=dict(revision.get("commit_metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_canonical_graph_revision(data)
        return data


@dataclass(frozen=True)
class ExtractionPolicy:
    policy_id: str
    policy_version: str
    scope_type: str
    scope_id: str
    status: PolicyStatus
    created_at: str
    created_by: str
    extractor_rules: dict[str, JsonValue] = field(default_factory=dict)
    routing_rules: dict[str, JsonValue] = field(default_factory=dict)
    review_requirements: dict[str, JsonValue] = field(default_factory=dict)
    parent_policy_id: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExtractionPolicy":
        policy = validate_extraction_policy(value)
        return cls(
            policy_id=str(policy["policy_id"]),
            policy_version=str(policy["policy_version"]),
            scope_type=str(policy["scope_type"]),
            scope_id=str(policy["scope_id"]),
            status=policy["status"],
            created_at=str(policy["created_at"]),
            created_by=str(policy["created_by"]),
            extractor_rules=dict(policy.get("extractor_rules", {})),
            routing_rules=dict(policy.get("routing_rules", {})),
            review_requirements=dict(policy.get("review_requirements", {})),
            parent_policy_id=policy.get("parent_policy_id"),
            description=policy.get("description"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_extraction_policy(data)
        return data


@dataclass(frozen=True)
class AtomGranularityPolicy:
    policy_id: str
    policy_version: str
    scope_type: str
    scope_id: str
    status: PolicyStatus
    split_rules: dict[str, JsonValue]
    merge_rules: dict[str, JsonValue]
    archive_rules: dict[str, JsonValue]
    review_requirements: dict[str, JsonValue]
    created_at: str
    created_by: str
    usage_signal_window: dict[str, JsonValue] = field(default_factory=dict)
    parent_policy_id: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AtomGranularityPolicy":
        policy = validate_atom_granularity_policy(value)
        return cls(
            policy_id=str(policy["policy_id"]),
            policy_version=str(policy["policy_version"]),
            scope_type=str(policy["scope_type"]),
            scope_id=str(policy["scope_id"]),
            status=policy["status"],
            split_rules=dict(policy["split_rules"]),
            merge_rules=dict(policy["merge_rules"]),
            archive_rules=dict(policy["archive_rules"]),
            review_requirements=dict(policy["review_requirements"]),
            created_at=str(policy["created_at"]),
            created_by=str(policy["created_by"]),
            usage_signal_window=dict(policy.get("usage_signal_window", {})),
            parent_policy_id=policy.get("parent_policy_id"),
            description=policy.get("description"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_atom_granularity_policy(data)
        return data


@dataclass(frozen=True)
class EntityResolutionPolicy:
    policy_id: str
    policy_version: str
    scope_type: str
    scope_id: str
    status: PolicyStatus
    ontology_revision_id: str
    match_rules: dict[str, JsonValue]
    threshold_rules: dict[str, JsonValue]
    clerical_review_rules: dict[str, JsonValue]
    review_requirements: dict[str, JsonValue]
    created_at: str
    created_by: str
    parent_policy_id: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EntityResolutionPolicy":
        policy = validate_entity_resolution_policy(value)
        return cls(
            policy_id=str(policy["policy_id"]),
            policy_version=str(policy["policy_version"]),
            scope_type=str(policy["scope_type"]),
            scope_id=str(policy["scope_id"]),
            status=policy["status"],
            ontology_revision_id=str(policy["ontology_revision_id"]),
            match_rules=dict(policy["match_rules"]),
            threshold_rules=dict(policy["threshold_rules"]),
            clerical_review_rules=dict(policy["clerical_review_rules"]),
            review_requirements=dict(policy["review_requirements"]),
            created_at=str(policy["created_at"]),
            created_by=str(policy["created_by"]),
            parent_policy_id=policy.get("parent_policy_id"),
            description=policy.get("description"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_entity_resolution_policy(data)
        return data


@dataclass(frozen=True)
class RelationResolutionPolicy:
    policy_id: str
    policy_version: str
    scope_type: str
    scope_id: str
    status: PolicyStatus
    ontology_revision_id: str
    relation_rules: dict[str, JsonValue]
    conversion_rules: dict[str, JsonValue]
    contradiction_rules: dict[str, JsonValue]
    review_requirements: dict[str, JsonValue]
    created_at: str
    created_by: str
    parent_policy_id: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RelationResolutionPolicy":
        policy = validate_relation_resolution_policy(value)
        return cls(
            policy_id=str(policy["policy_id"]),
            policy_version=str(policy["policy_version"]),
            scope_type=str(policy["scope_type"]),
            scope_id=str(policy["scope_id"]),
            status=policy["status"],
            ontology_revision_id=str(policy["ontology_revision_id"]),
            relation_rules=dict(policy["relation_rules"]),
            conversion_rules=dict(policy["conversion_rules"]),
            contradiction_rules=dict(policy["contradiction_rules"]),
            review_requirements=dict(policy["review_requirements"]),
            created_at=str(policy["created_at"]),
            created_by=str(policy["created_by"]),
            parent_policy_id=policy.get("parent_policy_id"),
            description=policy.get("description"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_relation_resolution_policy(data)
        return data


@dataclass(frozen=True)
class LifecyclePolicy:
    policy_id: str
    policy_version: str
    scope_type: str
    scope_id: str
    status: PolicyStatus
    lifecycle_rules: dict[str, JsonValue]
    split_rules: dict[str, JsonValue]
    merge_rules: dict[str, JsonValue]
    archive_rules: dict[str, JsonValue]
    supersede_rules: dict[str, JsonValue]
    equivalence_rules: dict[str, JsonValue]
    review_requirements: dict[str, JsonValue]
    created_at: str
    created_by: str
    parent_policy_id: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LifecyclePolicy":
        policy = validate_lifecycle_policy(value)
        return cls(
            policy_id=str(policy["policy_id"]),
            policy_version=str(policy["policy_version"]),
            scope_type=str(policy["scope_type"]),
            scope_id=str(policy["scope_id"]),
            status=policy["status"],
            lifecycle_rules=dict(policy["lifecycle_rules"]),
            split_rules=dict(policy["split_rules"]),
            merge_rules=dict(policy["merge_rules"]),
            archive_rules=dict(policy["archive_rules"]),
            supersede_rules=dict(policy["supersede_rules"]),
            equivalence_rules=dict(policy["equivalence_rules"]),
            review_requirements=dict(policy["review_requirements"]),
            created_at=str(policy["created_at"]),
            created_by=str(policy["created_by"]),
            parent_policy_id=policy.get("parent_policy_id"),
            description=policy.get("description"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_lifecycle_policy(data)
        return data


@dataclass(frozen=True)
class WikiProjectionPolicy:
    policy_id: str
    policy_version: str
    scope_type: str
    scope_id: str
    status: PolicyStatus
    allowed_projection_kinds: list[str]
    section_rules: dict[str, JsonValue]
    citation_rules: dict[str, JsonValue]
    redaction_rules: dict[str, JsonValue]
    review_requirements: dict[str, JsonValue]
    created_at: str
    created_by: str
    parent_policy_id: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WikiProjectionPolicy":
        policy = validate_wiki_projection_policy(value)
        return cls(
            policy_id=str(policy["policy_id"]),
            policy_version=str(policy["policy_version"]),
            scope_type=str(policy["scope_type"]),
            scope_id=str(policy["scope_id"]),
            status=policy["status"],
            allowed_projection_kinds=list(policy["allowed_projection_kinds"]),
            section_rules=dict(policy["section_rules"]),
            citation_rules=dict(policy["citation_rules"]),
            redaction_rules=dict(policy["redaction_rules"]),
            review_requirements=dict(policy["review_requirements"]),
            created_at=str(policy["created_at"]),
            created_by=str(policy["created_by"]),
            parent_policy_id=policy.get("parent_policy_id"),
            description=policy.get("description"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_wiki_projection_policy(data)
        return data


@dataclass(frozen=True)
class UserGraphProfile:
    graph_profile_id: str
    owner_user_id: str
    owner_scope_type: str
    owner_scope_id: str
    profile_name: str
    status: UserGraphProfileStatus
    created_at: str
    created_by: str
    description: str | None = None
    default_assembly_policy_id: str | None = None
    preferred_granularity: dict[str, JsonValue] = field(default_factory=dict)
    view_preferences: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "UserGraphProfile":
        profile = validate_user_graph_profile(value)
        return cls(
            graph_profile_id=str(profile["graph_profile_id"]),
            owner_user_id=str(profile["owner_user_id"]),
            owner_scope_type=str(profile["owner_scope_type"]),
            owner_scope_id=str(profile["owner_scope_id"]),
            profile_name=str(profile["profile_name"]),
            status=profile["status"],
            created_at=str(profile["created_at"]),
            created_by=str(profile["created_by"]),
            description=profile.get("description"),
            default_assembly_policy_id=profile.get("default_assembly_policy_id"),
            preferred_granularity=dict(profile.get("preferred_granularity", {})),
            view_preferences=dict(profile.get("view_preferences", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_user_graph_profile(data)
        return data


@dataclass(frozen=True)
class UserGraphAssemblyPolicy:
    assembly_policy_id: str
    policy_version: str
    owner_scope_type: str
    owner_scope_id: str
    graph_profile_id: str
    status: PolicyStatus
    created_at: str
    created_by: str
    include_rules: dict[str, JsonValue]
    exclude_rules: dict[str, JsonValue]
    grouping_rules: dict[str, JsonValue]
    granularity_rules: dict[str, JsonValue]
    relation_rules: dict[str, JsonValue]
    evidence_rules: dict[str, JsonValue]
    private_note_rules: dict[str, JsonValue]
    parent_policy_id: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "UserGraphAssemblyPolicy":
        policy = validate_user_graph_assembly_policy(value)
        return cls(
            assembly_policy_id=str(policy["assembly_policy_id"]),
            policy_version=str(policy["policy_version"]),
            owner_scope_type=str(policy["owner_scope_type"]),
            owner_scope_id=str(policy["owner_scope_id"]),
            graph_profile_id=str(policy["graph_profile_id"]),
            status=policy["status"],
            created_at=str(policy["created_at"]),
            created_by=str(policy["created_by"]),
            include_rules=dict(policy["include_rules"]),
            exclude_rules=dict(policy["exclude_rules"]),
            grouping_rules=dict(policy["grouping_rules"]),
            granularity_rules=dict(policy["granularity_rules"]),
            relation_rules=dict(policy["relation_rules"]),
            evidence_rules=dict(policy["evidence_rules"]),
            private_note_rules=dict(policy["private_note_rules"]),
            parent_policy_id=policy.get("parent_policy_id"),
            description=policy.get("description"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_user_graph_assembly_policy(data)
        return data


@dataclass(frozen=True)
class UserKnowledgeGraphRevision:
    user_graph_revision_id: str
    user_id: str
    graph_profile_id: str
    canonical_graph_revision_id: str
    ontology_revision_id: str
    assembly_policy_id: str
    status: UserGraphRevisionStatus
    included_atom_ids: list[str]
    included_entity_ids: list[str]
    included_relation_ids: list[str]
    source_refs: list[SourceRef | dict[str, Any]]
    evidence_snapshot_ids: list[str]
    permission_scope: PermissionScope | dict[str, Any]
    created_at: str
    created_by: str
    parent_user_graph_revision_id: str | None = None
    excluded_atom_ids: list[str] = field(default_factory=list)
    excluded_entity_ids: list[str] = field(default_factory=list)
    excluded_relation_ids: list[str] = field(default_factory=list)
    user_authored_atom_ids: list[str] = field(default_factory=list)
    private_note_ids: list[str] = field(default_factory=list)
    assembly_metadata: dict[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "UserKnowledgeGraphRevision":
        revision = validate_user_knowledge_graph_revision(value)
        return cls(
            user_graph_revision_id=str(revision["user_graph_revision_id"]),
            user_id=str(revision["user_id"]),
            graph_profile_id=str(revision["graph_profile_id"]),
            canonical_graph_revision_id=str(revision["canonical_graph_revision_id"]),
            ontology_revision_id=str(revision["ontology_revision_id"]),
            assembly_policy_id=str(revision["assembly_policy_id"]),
            status=revision["status"],
            included_atom_ids=list(revision["included_atom_ids"]),
            included_entity_ids=list(revision["included_entity_ids"]),
            included_relation_ids=list(revision["included_relation_ids"]),
            source_refs=list(revision["source_refs"]),
            evidence_snapshot_ids=list(revision["evidence_snapshot_ids"]),
            permission_scope=revision["permission_scope"],
            created_at=str(revision["created_at"]),
            created_by=str(revision["created_by"]),
            parent_user_graph_revision_id=revision.get("parent_user_graph_revision_id"),
            excluded_atom_ids=list(revision.get("excluded_atom_ids", [])),
            excluded_entity_ids=list(revision.get("excluded_entity_ids", [])),
            excluded_relation_ids=list(revision.get("excluded_relation_ids", [])),
            user_authored_atom_ids=list(revision.get("user_authored_atom_ids", [])),
            private_note_ids=list(revision.get("private_note_ids", [])),
            assembly_metadata=dict(revision.get("assembly_metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        validate_user_knowledge_graph_revision(data)
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
    session_id: str | None = None
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
            session_id=upload_session.get("session_id"),
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


def validate_type_definition(value: Any) -> dict[str, Any]:
    type_definition = _require_mapping(value, "TypeDefinition")
    _require_fields(
        type_definition,
        (
            "type_id",
            "tier",
            "core_supertype_id",
            "pref_label",
            "scope_type",
            "scope_id",
            "status",
            "ontology_revision_id",
            "confidence",
            "created_at",
            "created_by",
        ),
        "TypeDefinition",
    )
    _validate_string_fields(
        type_definition,
        (
            "type_id",
            "tier",
            "core_supertype_id",
            "pref_label",
            "scope_type",
            "scope_id",
            "status",
            "ontology_revision_id",
            "created_at",
            "created_by",
        ),
        "TypeDefinition",
    )
    _validate_optional_string_fields(type_definition, ("description",), "TypeDefinition")
    if type_definition["tier"] not in TYPE_TIER_VALUES:
        raise ContractValidationError("TypeDefinition.tier is not supported")
    if type_definition["status"] not in TYPE_STATUS_VALUES:
        raise ContractValidationError("TypeDefinition.status is not supported")
    _validate_type_common(type_definition, "TypeDefinition")
    _validate_core_supertype_id(
        type_definition["core_supertype_id"],
        "TypeDefinition.core_supertype_id",
    )
    _validate_confidence(type_definition["confidence"], "TypeDefinition.confidence")
    _validate_iso_timestamp(type_definition["created_at"], "TypeDefinition.created_at")
    for field_name in ("alt_labels",):
        _validate_string_list(type_definition.get(field_name, []), f"TypeDefinition.{field_name}")
        if any(not label for label in type_definition.get(field_name, [])):
            raise ContractValidationError(f"TypeDefinition.{field_name} entries cannot be empty")
    for field_name in ("broader_type_ids", "narrower_type_ids", "related_type_ids"):
        _validate_unique_provenance_id_list(
            type_definition.get(field_name, []),
            f"TypeDefinition.{field_name}",
        )
    for field_name in ("source_observation_ids", "source_candidate_ids"):
        _validate_unique_provenance_id_list(
            type_definition.get(field_name, []),
            f"TypeDefinition.{field_name}",
        )
    if type_definition["tier"] != "core" and not (
        type_definition.get("source_observation_ids") or type_definition.get("source_candidate_ids")
    ):
        raise ContractValidationError(
            "TypeDefinition extension and promoted tiers require source provenance"
        )
    if type_definition["tier"] == "core" and (
        type_definition["scope_type"],
        type_definition["scope_id"],
    ) != ("core", "formowl_core"):
        raise ContractValidationError("TypeDefinition core tier must use core/formowl_core scope")
    if type_definition["tier"] != "core" and type_definition["scope_type"] == "core":
        raise ContractValidationError("TypeDefinition non-core tiers require a non-core scope")
    if not isinstance(type_definition.get("metadata", {}), dict):
        raise ContractValidationError("TypeDefinition.metadata must be an object")
    _validate_no_raw_public_reference(
        {
            "pref_label": type_definition["pref_label"],
            "alt_labels": type_definition.get("alt_labels", []),
            "description": type_definition.get("description"),
            "metadata": type_definition.get("metadata", {}),
        },
        "TypeDefinition",
    )
    return type_definition


def validate_type_alias(value: Any) -> dict[str, Any]:
    alias = _require_mapping(value, "TypeAlias")
    _require_fields(
        alias,
        (
            "alias_id",
            "type_id",
            "alias_label",
            "scope_type",
            "scope_id",
            "status",
            "ontology_revision_id",
            "confidence",
            "created_at",
            "created_by",
        ),
        "TypeAlias",
    )
    _validate_string_fields(
        alias,
        (
            "alias_id",
            "type_id",
            "alias_label",
            "scope_type",
            "scope_id",
            "status",
            "ontology_revision_id",
            "created_at",
            "created_by",
        ),
        "TypeAlias",
    )
    _validate_optional_string_fields(alias, ("language",), "TypeAlias")
    if not alias["alias_label"]:
        raise ContractValidationError("TypeAlias.alias_label cannot be empty")
    if alias["status"] not in TYPE_STATUS_VALUES:
        raise ContractValidationError("TypeAlias.status is not supported")
    _validate_type_common(alias, "TypeAlias")
    _validate_confidence(alias["confidence"], "TypeAlias.confidence")
    _validate_iso_timestamp(alias["created_at"], "TypeAlias.created_at")
    _validate_unique_provenance_id_list(
        alias.get("source_candidate_ids", []),
        "TypeAlias.source_candidate_ids",
    )
    if not isinstance(alias.get("metadata", {}), dict):
        raise ContractValidationError("TypeAlias.metadata must be an object")
    _validate_no_raw_public_reference(
        {
            "alias_label": alias["alias_label"],
            "language": alias.get("language"),
            "metadata": alias.get("metadata", {}),
        },
        "TypeAlias",
    )
    return alias


def validate_type_mapping(value: Any) -> dict[str, Any]:
    mapping = _require_mapping(value, "TypeMapping")
    _require_fields(
        mapping,
        (
            "mapping_id",
            "source_type_id",
            "target_core_supertype_id",
            "scope_type",
            "scope_id",
            "status",
            "ontology_revision_id",
            "confidence",
            "created_at",
            "created_by",
        ),
        "TypeMapping",
    )
    _validate_string_fields(
        mapping,
        (
            "mapping_id",
            "source_type_id",
            "target_core_supertype_id",
            "scope_type",
            "scope_id",
            "status",
            "ontology_revision_id",
            "created_at",
            "created_by",
        ),
        "TypeMapping",
    )
    _validate_optional_string_fields(mapping, ("review_event_id",), "TypeMapping")
    if mapping["status"] not in TYPE_STATUS_VALUES:
        raise ContractValidationError("TypeMapping.status is not supported")
    _validate_type_common(mapping, "TypeMapping")
    _validate_core_supertype_id(
        mapping["target_core_supertype_id"],
        "TypeMapping.target_core_supertype_id",
    )
    _validate_confidence(mapping["confidence"], "TypeMapping.confidence")
    _validate_iso_timestamp(mapping["created_at"], "TypeMapping.created_at")
    _validate_unique_provenance_id_list(
        mapping.get("source_candidate_ids", []),
        "TypeMapping.source_candidate_ids",
    )
    if mapping.get("review_event_id") is not None:
        _validate_graph_reference_id(mapping["review_event_id"], "TypeMapping.review_event_id")
    if not isinstance(mapping.get("metadata", {}), dict):
        raise ContractValidationError("TypeMapping.metadata must be an object")
    _validate_no_raw_public_reference(mapping.get("metadata", {}), "TypeMapping")
    return mapping


def validate_type_alignment_candidate(value: Any) -> dict[str, Any]:
    candidate = _require_mapping(value, "TypeAlignmentCandidate")
    _require_fields(
        candidate,
        (
            "alignment_candidate_id",
            "source_type_id",
            "target_type_id",
            "source_scope_type",
            "source_scope_id",
            "target_scope_type",
            "target_scope_id",
            "ontology_revision_id",
            "score",
            "score_breakdown",
            "evidence_links",
            "status",
            "requires_review",
            "created_at",
            "created_by",
        ),
        "TypeAlignmentCandidate",
    )
    _validate_string_fields(
        candidate,
        (
            "alignment_candidate_id",
            "source_type_id",
            "target_type_id",
            "source_scope_type",
            "source_scope_id",
            "target_scope_type",
            "target_scope_id",
            "ontology_revision_id",
            "status",
            "created_at",
            "created_by",
        ),
        "TypeAlignmentCandidate",
    )
    _validate_optional_string_fields(candidate, ("access_grant_id",), "TypeAlignmentCandidate")
    for field_name in (
        "alignment_candidate_id",
        "source_type_id",
        "target_type_id",
        "source_scope_type",
        "source_scope_id",
        "target_scope_type",
        "target_scope_id",
        "ontology_revision_id",
        "created_by",
    ):
        _validate_graph_reference_id(candidate[field_name], f"TypeAlignmentCandidate.{field_name}")
    if (candidate["source_scope_type"], candidate["source_scope_id"]) == (
        candidate["target_scope_type"],
        candidate["target_scope_id"],
    ):
        raise ContractValidationError("TypeAlignmentCandidate must be cross-scope")
    _validate_confidence(candidate["score"], "TypeAlignmentCandidate.score")
    if not isinstance(candidate["score_breakdown"], dict) or not candidate["score_breakdown"]:
        raise ContractValidationError(
            "TypeAlignmentCandidate.score_breakdown must be a non-empty object"
        )
    for key, value_item in candidate["score_breakdown"].items():
        if not isinstance(key, str) or not key:
            raise ContractValidationError(
                "TypeAlignmentCandidate.score_breakdown keys must be non-empty strings"
            )
        _validate_confidence(
            value_item,
            f"TypeAlignmentCandidate.score_breakdown.{key}",
        )
    if not isinstance(candidate["evidence_links"], list) or not candidate["evidence_links"]:
        raise ContractValidationError(
            "TypeAlignmentCandidate.evidence_links must be a non-empty list"
        )
    for index, evidence_link in enumerate(candidate["evidence_links"]):
        _validate_type_alignment_evidence_link(evidence_link, index)
    if candidate["status"] not in CANDIDATE_STATUS_VALUES:
        raise ContractValidationError("TypeAlignmentCandidate.status is not supported")
    if not isinstance(candidate["requires_review"], bool) or not candidate["requires_review"]:
        raise ContractValidationError("TypeAlignmentCandidate.requires_review must stay true")
    if candidate.get("canonical_type_write_allowed", False):
        raise ContractValidationError("TypeAlignmentCandidate cannot allow canonical type writes")
    if candidate.get("access_grant_id") is not None:
        raise ContractValidationError("TypeAlignmentCandidate cannot carry access grants")
    _validate_iso_timestamp(candidate["created_at"], "TypeAlignmentCandidate.created_at")
    if not isinstance(candidate.get("metadata", {}), dict):
        raise ContractValidationError("TypeAlignmentCandidate.metadata must be an object")
    _validate_no_raw_public_reference(
        {
            "score_breakdown": candidate["score_breakdown"],
            "evidence_links": candidate["evidence_links"],
            "metadata": candidate.get("metadata", {}),
        },
        "TypeAlignmentCandidate",
    )
    return candidate


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


def validate_candidate_mention(value: Any) -> dict[str, Any]:
    mention = _require_mapping(value, "CandidateMention")
    _require_fields(
        mention,
        (
            "candidate_mention_id",
            "source_observation_ids",
            "mention_type",
            "normalized_label",
            "location",
            "text_hash",
            "confidence",
            "extractor_run_id",
            "status",
            "requires_review",
        ),
        "CandidateMention",
    )
    _validate_string_fields(
        mention,
        (
            "candidate_mention_id",
            "mention_type",
            "normalized_label",
            "text_hash",
            "extractor_run_id",
            "status",
        ),
        "CandidateMention",
    )
    _validate_optional_string_fields(mention, ("created_at",), "CandidateMention")
    _validate_optional_iso_timestamp_fields(mention, ("created_at",), "CandidateMention")
    _validate_graph_reference_id(
        mention["candidate_mention_id"],
        "CandidateMention.candidate_mention_id",
    )
    _validate_candidate_common(mention, "CandidateMention", properties_field="metadata")
    if not isinstance(mention["location"], dict) or not mention["location"]:
        raise ContractValidationError("CandidateMention.location must be a non-empty object")
    _validate_sha256_hash(mention["text_hash"], "CandidateMention.text_hash")
    _validate_no_raw_public_reference(
        {
            "mention_type": mention["mention_type"],
            "normalized_label": mention["normalized_label"],
            "location": mention["location"],
            "metadata": mention.get("metadata", {}),
        },
        "CandidateMention",
    )
    return mention


def validate_candidate_business_object(value: Any) -> dict[str, Any]:
    business_object = _require_mapping(value, "CandidateBusinessObject")
    _require_fields(
        business_object,
        (
            "candidate_business_object_id",
            "source_observation_ids",
            "object_type",
            "object_supertype",
            "label",
            "domain_hints",
            "properties",
            "granularity_level",
            "access_boundary",
            "confidence",
            "extractor_run_id",
            "status",
            "requires_review",
        ),
        "CandidateBusinessObject",
    )
    _validate_string_fields(
        business_object,
        (
            "candidate_business_object_id",
            "object_type",
            "object_supertype",
            "label",
            "granularity_level",
            "extractor_run_id",
            "status",
        ),
        "CandidateBusinessObject",
    )
    _validate_optional_string_fields(
        business_object,
        ("created_at",),
        "CandidateBusinessObject",
    )
    _validate_optional_iso_timestamp_fields(
        business_object,
        ("created_at",),
        "CandidateBusinessObject",
    )
    _validate_graph_reference_id(
        business_object["candidate_business_object_id"],
        "CandidateBusinessObject.candidate_business_object_id",
    )
    _validate_candidate_common(business_object, "CandidateBusinessObject")
    _validate_coordination_object_supertype(
        business_object["object_supertype"],
        "CandidateBusinessObject.object_supertype",
    )
    _validate_non_empty_unique_string_list(
        business_object["domain_hints"],
        "CandidateBusinessObject.domain_hints",
    )
    _validate_access_boundary(
        business_object["access_boundary"],
        "CandidateBusinessObject.access_boundary",
    )
    _validate_unique_provenance_id_list(
        business_object.get("source_candidate_mention_ids", []),
        "CandidateBusinessObject.source_candidate_mention_ids",
    )
    _validate_no_raw_public_reference(
        {
            "object_type": business_object["object_type"],
            "label": business_object["label"],
            "domain_hints": business_object["domain_hints"],
            "properties": business_object["properties"],
            "granularity_level": business_object["granularity_level"],
            "access_boundary": business_object["access_boundary"],
            "metadata": business_object.get("metadata", {}),
        },
        "CandidateBusinessObject",
    )
    return business_object


def validate_candidate_frame(value: Any) -> dict[str, Any]:
    frame = _require_mapping(value, "CandidateFrame")
    _require_fields(
        frame,
        (
            "candidate_frame_id",
            "source_observation_ids",
            "frame_type",
            "slots",
            "evidence_spans",
            "domain_hints",
            "granularity_level",
            "access_boundary",
            "confidence",
            "extractor_run_id",
            "ontology_revision_id",
            "status",
            "requires_review",
        ),
        "CandidateFrame",
    )
    _validate_string_fields(
        frame,
        (
            "candidate_frame_id",
            "frame_type",
            "granularity_level",
            "extractor_run_id",
            "ontology_revision_id",
            "status",
        ),
        "CandidateFrame",
    )
    _validate_optional_string_fields(frame, ("created_at",), "CandidateFrame")
    _validate_optional_iso_timestamp_fields(frame, ("created_at",), "CandidateFrame")
    _validate_graph_reference_id(frame["candidate_frame_id"], "CandidateFrame.candidate_frame_id")
    _validate_graph_reference_id(
        frame["ontology_revision_id"],
        "CandidateFrame.ontology_revision_id",
    )
    _validate_candidate_common(frame, "CandidateFrame", properties_field="slots")
    _validate_coordination_frame_type(frame["frame_type"], "CandidateFrame.frame_type")
    if not isinstance(frame["slots"], dict) or not frame["slots"]:
        raise ContractValidationError("CandidateFrame.slots must be a non-empty object")
    _validate_evidence_spans(frame["evidence_spans"], "CandidateFrame.evidence_spans")
    _validate_non_empty_unique_string_list(frame["domain_hints"], "CandidateFrame.domain_hints")
    _validate_access_boundary(frame["access_boundary"], "CandidateFrame.access_boundary")
    _validate_unique_provenance_id_list(
        frame.get("source_candidate_mention_ids", []),
        "CandidateFrame.source_candidate_mention_ids",
    )
    _validate_unique_provenance_id_list(
        frame.get("candidate_business_object_ids", []),
        "CandidateFrame.candidate_business_object_ids",
    )
    _validate_no_raw_public_reference(
        {
            "frame_type": frame["frame_type"],
            "slots": frame["slots"],
            "evidence_spans": frame["evidence_spans"],
            "domain_hints": frame["domain_hints"],
            "granularity_level": frame["granularity_level"],
            "access_boundary": frame["access_boundary"],
            "metadata": frame.get("metadata", {}),
        },
        "CandidateFrame",
    )
    return frame


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
        "candidate_mention_ids",
        "candidate_business_object_ids",
        "candidate_frame_ids",
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


def validate_canonical_frame(value: Any) -> dict[str, Any]:
    frame = _require_mapping(value, "CanonicalFrame")
    _require_fields(
        frame,
        (
            "canonical_frame_id",
            "scope_type",
            "scope_id",
            "frame_type",
            "canonical_slots",
            "evidence_spans",
            "domain_hints",
            "granularity_level",
            "access_boundary",
            "status",
            "source_candidate_frame_ids",
            "source_observation_ids",
            "confidence",
            "ontology_revision_id",
            "frame_policy_id",
            "created_at",
            "created_by",
        ),
        "CanonicalFrame",
    )
    _validate_string_fields(
        frame,
        (
            "canonical_frame_id",
            "scope_type",
            "scope_id",
            "frame_type",
            "granularity_level",
            "status",
            "ontology_revision_id",
            "frame_policy_id",
            "created_at",
            "created_by",
        ),
        "CanonicalFrame",
    )
    for field_name in (
        "canonical_frame_id",
        "scope_type",
        "scope_id",
        "ontology_revision_id",
        "frame_policy_id",
        "created_by",
    ):
        _validate_graph_reference_id(frame[field_name], f"CanonicalFrame.{field_name}")
    _validate_coordination_frame_type(frame["frame_type"], "CanonicalFrame.frame_type")
    if not isinstance(frame["canonical_slots"], dict) or not frame["canonical_slots"]:
        raise ContractValidationError("CanonicalFrame.canonical_slots must be a non-empty object")
    _validate_evidence_spans(frame["evidence_spans"], "CanonicalFrame.evidence_spans")
    _validate_non_empty_unique_string_list(frame["domain_hints"], "CanonicalFrame.domain_hints")
    _validate_access_boundary(frame["access_boundary"], "CanonicalFrame.access_boundary")
    if frame["status"] not in CANONICAL_RECORD_STATUS_VALUES:
        raise ContractValidationError("CanonicalFrame.status is not supported")
    _validate_unique_provenance_id_list(
        frame["source_candidate_frame_ids"],
        "CanonicalFrame.source_candidate_frame_ids",
        allow_empty=False,
    )
    _validate_unique_provenance_id_list(
        frame["source_observation_ids"],
        "CanonicalFrame.source_observation_ids",
        allow_empty=False,
    )
    _validate_confidence(frame["confidence"], "CanonicalFrame.confidence")
    _validate_iso_timestamp(frame["created_at"], "CanonicalFrame.created_at")
    if not isinstance(frame.get("metadata", {}), dict):
        raise ContractValidationError("CanonicalFrame.metadata must be an object")
    _validate_no_raw_public_reference(
        {
            "frame_type": frame["frame_type"],
            "canonical_slots": frame["canonical_slots"],
            "evidence_spans": frame["evidence_spans"],
            "domain_hints": frame["domain_hints"],
            "granularity_level": frame["granularity_level"],
            "access_boundary": frame["access_boundary"],
            "metadata": frame.get("metadata", {}),
        },
        "CanonicalFrame",
    )
    return frame


def validate_canonical_atom(value: Any) -> dict[str, Any]:
    atom = _require_mapping(value, "CanonicalAtom")
    _require_fields(
        atom,
        (
            "canonical_atom_id",
            "scope_type",
            "scope_id",
            "atom_type",
            "canonical_text",
            "granularity_level",
            "status",
            "source_candidate_atom_ids",
            "source_observation_ids",
            "source_refs",
            "evidence_snapshot_ids",
            "citations",
            "content_hash",
            "extraction_policy_id",
            "granularity_policy_id",
            "confidence",
            "created_at",
        ),
        "CanonicalAtom",
    )
    _validate_string_fields(
        atom,
        (
            "canonical_atom_id",
            "scope_type",
            "scope_id",
            "atom_type",
            "canonical_text",
            "granularity_level",
            "status",
            "content_hash",
            "extraction_policy_id",
            "granularity_policy_id",
            "created_at",
        ),
        "CanonicalAtom",
    )
    _validate_optional_string_fields(atom, ("language", "domain"), "CanonicalAtom")
    _validate_canonical_scope(atom, "CanonicalAtom")
    _validate_graph_reference_id(atom["canonical_atom_id"], "CanonicalAtom.canonical_atom_id")
    _validate_provenance_id_list(
        atom["source_candidate_atom_ids"],
        "CanonicalAtom.source_candidate_atom_ids",
        allow_empty=False,
    )
    _validate_canonical_source_fields(atom, "CanonicalAtom")
    _validate_provenance_id_list(
        atom.get("parent_atom_ids", []),
        "CanonicalAtom.parent_atom_ids",
    )
    _validate_provenance_id_list(atom.get("child_atom_ids", []), "CanonicalAtom.child_atom_ids")
    _validate_provenance_id_list(
        atom.get("related_atom_ids", []),
        "CanonicalAtom.related_atom_ids",
    )
    _validate_string_list(atom.get("labels", []), "CanonicalAtom.labels")
    _validate_graph_reference_id(atom["extraction_policy_id"], "CanonicalAtom.extraction_policy_id")
    _validate_graph_reference_id(
        atom["granularity_policy_id"],
        "CanonicalAtom.granularity_policy_id",
    )
    _validate_sha256_hash(atom["content_hash"], "CanonicalAtom.content_hash")
    _validate_canonical_record_status(atom["status"], "CanonicalAtom.status")
    _validate_confidence(atom["confidence"], "CanonicalAtom.confidence")
    _validate_iso_timestamp(atom["created_at"], "CanonicalAtom.created_at")
    if not isinstance(atom.get("metadata", {}), dict):
        raise ContractValidationError("CanonicalAtom.metadata must be an object")
    return atom


def validate_canonical_entity(value: Any) -> dict[str, Any]:
    entity = _require_mapping(value, "CanonicalEntity")
    _require_fields(
        entity,
        (
            "canonical_entity_id",
            "scope_type",
            "scope_id",
            "entity_type",
            "canonical_label",
            "status",
            "source_candidate_atom_ids",
            "source_observation_ids",
            "source_refs",
            "evidence_snapshot_ids",
            "citations",
            "confidence",
            "ontology_revision_id",
            "created_at",
        ),
        "CanonicalEntity",
    )
    _validate_string_fields(
        entity,
        (
            "canonical_entity_id",
            "scope_type",
            "scope_id",
            "entity_type",
            "canonical_label",
            "status",
            "ontology_revision_id",
            "created_at",
        ),
        "CanonicalEntity",
    )
    _validate_canonical_scope(entity, "CanonicalEntity")
    _validate_graph_reference_id(
        entity["canonical_entity_id"],
        "CanonicalEntity.canonical_entity_id",
    )
    _validate_provenance_id_list(
        entity["source_candidate_atom_ids"],
        "CanonicalEntity.source_candidate_atom_ids",
    )
    _validate_canonical_source_fields(entity, "CanonicalEntity")
    _validate_string_list(entity.get("aliases", []), "CanonicalEntity.aliases")
    _validate_graph_reference_id(
        entity["ontology_revision_id"],
        "CanonicalEntity.ontology_revision_id",
    )
    _validate_canonical_record_status(entity["status"], "CanonicalEntity.status")
    _validate_confidence(entity["confidence"], "CanonicalEntity.confidence")
    _validate_iso_timestamp(entity["created_at"], "CanonicalEntity.created_at")
    if not isinstance(entity.get("metadata", {}), dict):
        raise ContractValidationError("CanonicalEntity.metadata must be an object")
    return entity


def validate_canonical_relation(value: Any) -> dict[str, Any]:
    relation = _require_mapping(value, "CanonicalRelation")
    _require_fields(
        relation,
        (
            "canonical_relation_id",
            "scope_type",
            "scope_id",
            "source_id",
            "target_id",
            "relation_type",
            "status",
            "source_candidate_relation_ids",
            "source_observation_ids",
            "source_refs",
            "evidence_snapshot_ids",
            "citations",
            "confidence",
            "ontology_revision_id",
            "created_at",
        ),
        "CanonicalRelation",
    )
    _validate_string_fields(
        relation,
        (
            "canonical_relation_id",
            "scope_type",
            "scope_id",
            "source_id",
            "target_id",
            "relation_type",
            "status",
            "ontology_revision_id",
            "created_at",
        ),
        "CanonicalRelation",
    )
    _validate_canonical_scope(relation, "CanonicalRelation")
    _validate_graph_reference_id(
        relation["canonical_relation_id"],
        "CanonicalRelation.canonical_relation_id",
    )
    _validate_graph_reference_id(relation["source_id"], "CanonicalRelation.source_id")
    _validate_graph_reference_id(relation["target_id"], "CanonicalRelation.target_id")
    _validate_provenance_id_list(
        relation["source_candidate_relation_ids"],
        "CanonicalRelation.source_candidate_relation_ids",
    )
    _validate_canonical_source_fields(relation, "CanonicalRelation")
    _validate_graph_reference_id(
        relation["ontology_revision_id"],
        "CanonicalRelation.ontology_revision_id",
    )
    _validate_canonical_record_status(relation["status"], "CanonicalRelation.status")
    _validate_confidence(relation["confidence"], "CanonicalRelation.confidence")
    _validate_iso_timestamp(relation["created_at"], "CanonicalRelation.created_at")
    if not isinstance(relation.get("properties", {}), dict):
        raise ContractValidationError("CanonicalRelation.properties must be an object")
    return relation


def validate_canonical_graph_revision(value: Any) -> dict[str, Any]:
    revision = _require_mapping(value, "CanonicalGraphRevision")
    _require_fields(
        revision,
        (
            "canonical_graph_revision_id",
            "scope_type",
            "scope_id",
            "ontology_revision_id",
            "status",
            "canonical_atom_ids",
            "canonical_entity_ids",
            "canonical_relation_ids",
            "created_at",
            "created_by",
        ),
        "CanonicalGraphRevision",
    )
    _validate_string_fields(
        revision,
        (
            "canonical_graph_revision_id",
            "scope_type",
            "scope_id",
            "ontology_revision_id",
            "status",
            "created_at",
            "created_by",
        ),
        "CanonicalGraphRevision",
    )
    _validate_optional_string_fields(
        revision,
        ("parent_revision_id",),
        "CanonicalGraphRevision",
    )
    _validate_canonical_scope(revision, "CanonicalGraphRevision")
    _validate_graph_reference_id(
        revision["canonical_graph_revision_id"],
        "CanonicalGraphRevision.canonical_graph_revision_id",
    )
    _validate_graph_reference_id(
        revision["ontology_revision_id"],
        "CanonicalGraphRevision.ontology_revision_id",
    )
    _validate_graph_reference_id(revision["created_by"], "CanonicalGraphRevision.created_by")
    if revision.get("parent_revision_id") is not None:
        _validate_graph_reference_id(
            revision["parent_revision_id"],
            "CanonicalGraphRevision.parent_revision_id",
        )
    _validate_provenance_id_list(
        revision["canonical_atom_ids"],
        "CanonicalGraphRevision.canonical_atom_ids",
    )
    _validate_provenance_id_list(
        revision["canonical_entity_ids"],
        "CanonicalGraphRevision.canonical_entity_ids",
    )
    _validate_provenance_id_list(
        revision["canonical_relation_ids"],
        "CanonicalGraphRevision.canonical_relation_ids",
    )
    if not any(
        (
            revision["canonical_atom_ids"],
            revision["canonical_entity_ids"],
            revision["canonical_relation_ids"],
        )
    ):
        raise ContractValidationError("CanonicalGraphRevision must reference canonical records")
    _validate_provenance_id_list(
        revision.get("source_candidate_atom_ids", []),
        "CanonicalGraphRevision.source_candidate_atom_ids",
    )
    _validate_provenance_id_list(
        revision.get("source_candidate_relation_ids", []),
        "CanonicalGraphRevision.source_candidate_relation_ids",
    )
    _validate_provenance_id_list(
        revision.get("policy_ids", []),
        "CanonicalGraphRevision.policy_ids",
    )
    if revision["status"] not in CANONICAL_GRAPH_REVISION_STATUS_VALUES:
        raise ContractValidationError("CanonicalGraphRevision.status is not supported")
    _validate_iso_timestamp(revision["created_at"], "CanonicalGraphRevision.created_at")
    if not isinstance(revision.get("commit_metadata", {}), dict):
        raise ContractValidationError("CanonicalGraphRevision.commit_metadata must be an object")
    return revision


def validate_extraction_policy(value: Any) -> dict[str, Any]:
    policy = _require_mapping(value, "ExtractionPolicy")
    _validate_policy_common(
        policy,
        "ExtractionPolicy",
        ("extractor_rules", "routing_rules", "review_requirements"),
    )
    return policy


def validate_atom_granularity_policy(value: Any) -> dict[str, Any]:
    policy = _require_mapping(value, "AtomGranularityPolicy")
    _require_fields(
        policy,
        (
            "split_rules",
            "merge_rules",
            "archive_rules",
            "review_requirements",
        ),
        "AtomGranularityPolicy",
    )
    _validate_policy_common(
        policy,
        "AtomGranularityPolicy",
        (
            "split_rules",
            "merge_rules",
            "archive_rules",
            "review_requirements",
            "usage_signal_window",
        ),
    )
    return policy


def validate_entity_resolution_policy(value: Any) -> dict[str, Any]:
    policy = _require_mapping(value, "EntityResolutionPolicy")
    _require_fields(
        policy,
        (
            "ontology_revision_id",
            "match_rules",
            "threshold_rules",
            "clerical_review_rules",
            "review_requirements",
        ),
        "EntityResolutionPolicy",
    )
    _validate_policy_common(
        policy,
        "EntityResolutionPolicy",
        (
            "match_rules",
            "threshold_rules",
            "clerical_review_rules",
            "review_requirements",
        ),
    )
    _validate_string_fields(policy, ("ontology_revision_id",), "EntityResolutionPolicy")
    _validate_graph_reference_id(
        policy["ontology_revision_id"],
        "EntityResolutionPolicy.ontology_revision_id",
    )
    return policy


def validate_relation_resolution_policy(value: Any) -> dict[str, Any]:
    policy = _require_mapping(value, "RelationResolutionPolicy")
    _require_fields(
        policy,
        (
            "ontology_revision_id",
            "relation_rules",
            "conversion_rules",
            "contradiction_rules",
            "review_requirements",
        ),
        "RelationResolutionPolicy",
    )
    _validate_policy_common(
        policy,
        "RelationResolutionPolicy",
        (
            "relation_rules",
            "conversion_rules",
            "contradiction_rules",
            "review_requirements",
        ),
    )
    _validate_string_fields(policy, ("ontology_revision_id",), "RelationResolutionPolicy")
    _validate_graph_reference_id(
        policy["ontology_revision_id"],
        "RelationResolutionPolicy.ontology_revision_id",
    )
    return policy


def validate_lifecycle_policy(value: Any) -> dict[str, Any]:
    policy = _require_mapping(value, "LifecyclePolicy")
    _require_fields(
        policy,
        (
            "lifecycle_rules",
            "split_rules",
            "merge_rules",
            "archive_rules",
            "supersede_rules",
            "equivalence_rules",
            "review_requirements",
        ),
        "LifecyclePolicy",
    )
    _validate_policy_common(
        policy,
        "LifecyclePolicy",
        (
            "lifecycle_rules",
            "split_rules",
            "merge_rules",
            "archive_rules",
            "supersede_rules",
            "equivalence_rules",
            "review_requirements",
        ),
    )
    return policy


def validate_wiki_projection_policy(value: Any) -> dict[str, Any]:
    policy = _require_mapping(value, "WikiProjectionPolicy")
    _require_fields(
        policy,
        (
            "allowed_projection_kinds",
            "section_rules",
            "citation_rules",
            "redaction_rules",
            "review_requirements",
        ),
        "WikiProjectionPolicy",
    )
    _validate_policy_common(
        policy,
        "WikiProjectionPolicy",
        (
            "section_rules",
            "citation_rules",
            "redaction_rules",
            "review_requirements",
        ),
    )
    _validate_non_empty_unique_string_list(
        policy["allowed_projection_kinds"],
        "WikiProjectionPolicy.allowed_projection_kinds",
    )
    _validate_no_raw_public_reference(
        policy["allowed_projection_kinds"],
        "WikiProjectionPolicy.allowed_projection_kinds",
    )
    return policy


def _validate_policy_common(
    policy: dict[str, Any],
    name: str,
    rule_fields: tuple[str, ...],
) -> None:
    _require_fields(
        policy,
        (
            "policy_id",
            "policy_version",
            "scope_type",
            "scope_id",
            "status",
            "created_at",
            "created_by",
        ),
        name,
    )
    _validate_string_fields(
        policy,
        (
            "policy_id",
            "policy_version",
            "scope_type",
            "scope_id",
            "status",
            "created_at",
            "created_by",
        ),
        name,
    )
    _validate_optional_string_fields(policy, ("parent_policy_id", "description"), name)
    _validate_graph_reference_id(policy["policy_id"], f"{name}.policy_id")
    _validate_graph_reference_id(policy["policy_version"], f"{name}.policy_version")
    _validate_graph_reference_id(policy["scope_type"], f"{name}.scope_type")
    _validate_graph_reference_id(policy["scope_id"], f"{name}.scope_id")
    _validate_graph_reference_id(policy["created_by"], f"{name}.created_by")
    if policy.get("parent_policy_id") is not None:
        _validate_graph_reference_id(policy["parent_policy_id"], f"{name}.parent_policy_id")
    if policy["status"] not in POLICY_STATUS_VALUES:
        raise ContractValidationError(f"{name}.status is not supported")
    _validate_iso_timestamp(policy["created_at"], f"{name}.created_at")
    for field_name in rule_fields:
        if field_name not in policy:
            policy[field_name] = {}
        if not isinstance(policy[field_name], dict):
            raise ContractValidationError(f"{name}.{field_name} must be an object")
    _validate_no_raw_public_reference(
        {
            "policy_version": policy["policy_version"],
            "scope_type": policy["scope_type"],
            "scope_id": policy["scope_id"],
            "created_by": policy["created_by"],
            "description": policy.get("description"),
            "rules": {field_name: policy[field_name] for field_name in rule_fields},
        },
        name,
    )


def _validate_canonical_scope(value: dict[str, Any], name: str) -> None:
    _validate_graph_reference_id(value["scope_type"], f"{name}.scope_type")
    _validate_graph_reference_id(value["scope_id"], f"{name}.scope_id")


def _validate_canonical_record_status(value: Any, field_name: str) -> None:
    if value not in CANONICAL_RECORD_STATUS_VALUES:
        raise ContractValidationError(f"{field_name} is not supported")


def _validate_canonical_source_fields(value: dict[str, Any], name: str) -> None:
    _validate_provenance_id_list(
        value["source_observation_ids"],
        f"{name}.source_observation_ids",
        allow_empty=False,
    )
    if not isinstance(value["source_refs"], list):
        raise ContractValidationError(f"{name}.source_refs must be a list")
    for source_ref in value["source_refs"]:
        validate_source_ref(source_ref)
    _validate_provenance_id_list(
        value["evidence_snapshot_ids"],
        f"{name}.evidence_snapshot_ids",
    )
    _validate_citation_list(value["citations"], f"{name}.citations")


def _validate_citation_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise ContractValidationError(f"{field_name} must be a list")
    for item in value:
        citation = _require_mapping(item, "Citation")
        _require_fields(citation, ("citation_id", "source_ref"), "Citation")
        _validate_string_fields(citation, ("citation_id",), "Citation")
        _validate_graph_reference_id(citation["citation_id"], "Citation.citation_id")
        validate_source_ref(citation["source_ref"])
        _validate_optional_string_fields(citation, ("evidence_snapshot_id", "summary"), "Citation")
        if citation.get("evidence_snapshot_id") is not None:
            _validate_graph_reference_id(
                citation["evidence_snapshot_id"],
                "Citation.evidence_snapshot_id",
            )
        if citation.get("locator") is not None and not isinstance(citation["locator"], dict):
            raise ContractValidationError("Citation.locator must be an object")


def _validate_sha256_hash(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ContractValidationError(f"{field_name} must be a sha256-prefixed hash")


def _validate_candidate_common(
    candidate: dict[str, Any],
    name: str,
    *,
    properties_field: str = "properties",
) -> None:
    _validate_graph_reference_id(candidate["extractor_run_id"], f"{name}.extractor_run_id")
    _validate_provenance_id_list(
        candidate["source_observation_ids"],
        f"{name}.source_observation_ids",
        allow_empty=False,
    )
    if not isinstance(candidate.get(properties_field, {}), dict):
        raise ContractValidationError(f"{name}.{properties_field} must be an object")
    _validate_confidence(candidate["confidence"], f"{name}.confidence")
    if candidate["status"] not in CANDIDATE_STATUS_VALUES:
        raise ContractValidationError(f"{name}.status is not supported")
    if not isinstance(candidate["requires_review"], bool):
        raise ContractValidationError(f"{name}.requires_review must be boolean")


def _validate_coordination_frame_type(value: Any, field_name: str) -> None:
    if value not in COORDINATION_FRAME_TYPES:
        raise ContractValidationError(f"{field_name} must be a coordination frame type")


def _validate_coordination_object_supertype(value: Any, field_name: str) -> None:
    if value not in COORDINATION_OBJECT_SUPERTYPE_IDS:
        raise ContractValidationError(f"{field_name} must be a coordination object supertype")


def _validate_evidence_spans(value: Any, field_name: str) -> None:
    if not isinstance(value, list) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty list")
    for index, item in enumerate(value):
        span = _require_mapping(item, f"{field_name}[{index}]")
        _require_fields(
            span,
            ("source_observation_id", "span_id", "locator", "text_hash"),
            f"{field_name}[{index}]",
        )
        _validate_string_fields(
            span,
            ("source_observation_id", "span_id", "text_hash"),
            f"{field_name}[{index}]",
        )
        _validate_graph_reference_id(
            span["source_observation_id"],
            f"{field_name}[{index}].source_observation_id",
        )
        _validate_graph_reference_id(span["span_id"], f"{field_name}[{index}].span_id")
        if not isinstance(span["locator"], dict) or not span["locator"]:
            raise ContractValidationError(f"{field_name}[{index}].locator must be an object")
        _validate_sha256_hash(span["text_hash"], f"{field_name}[{index}].text_hash")
        _validate_no_raw_public_reference(span, f"{field_name}[{index}]")


def _validate_access_boundary(value: Any, field_name: str) -> None:
    boundary = _require_mapping(value, field_name)
    _require_fields(
        boundary,
        ("boundary_type", "permission_scope", "raw_access_required"),
        field_name,
    )
    _validate_string_fields(boundary, ("boundary_type",), field_name)
    validate_permission_scope(boundary["permission_scope"])
    if not isinstance(boundary["raw_access_required"], bool):
        raise ContractValidationError(f"{field_name}.raw_access_required must be boolean")
    if "redacted_slot_names" in boundary:
        _validate_string_list(boundary["redacted_slot_names"], f"{field_name}.redacted_slot_names")
    _validate_no_raw_public_reference(boundary, field_name)


def _validate_core_supertype_id(value: Any, field_name: str) -> None:
    if value not in CORE_SUPERTYPE_IDS:
        raise ContractValidationError(f"{field_name} must be a closed core supertype")


def _validate_type_common(value: dict[str, Any], name: str) -> None:
    for field_name in (
        "type_id",
        "alias_id",
        "mapping_id",
        "source_type_id",
        "scope_type",
        "scope_id",
        "ontology_revision_id",
        "created_by",
    ):
        if field_name in value:
            _validate_graph_reference_id(value[field_name], f"{name}.{field_name}")


def _validate_type_alignment_evidence_link(value: Any, index: int) -> None:
    evidence_link = _require_mapping(value, "TypeAlignmentCandidate.evidence_links entry")
    if not any(
        evidence_link.get(field_name)
        for field_name in (
            "source_observation_ids",
            "source_candidate_ids",
            "evidence_snapshot_ids",
        )
    ):
        raise ContractValidationError(
            "TypeAlignmentCandidate.evidence_links entry requires provenance ids"
        )
    for field_name in (
        "source_observation_ids",
        "source_candidate_ids",
        "evidence_snapshot_ids",
    ):
        _validate_unique_provenance_id_list(
            evidence_link.get(field_name, []),
            f"TypeAlignmentCandidate.evidence_links[{index}].{field_name}",
        )
    if "visible_to_requester" in evidence_link and not isinstance(
        evidence_link["visible_to_requester"],
        bool,
    ):
        raise ContractValidationError(
            "TypeAlignmentCandidate.evidence_links.visible_to_requester must be boolean"
        )
    if "summary" in evidence_link and not isinstance(evidence_link["summary"], str):
        raise ContractValidationError(
            "TypeAlignmentCandidate.evidence_links.summary must be string"
        )


def _validate_no_user_graph_raw_reference(value: Any, name: str) -> None:
    if isinstance(value, str):
        for pattern in _USER_GRAPH_RAW_REFERENCE_PATTERNS:
            if pattern.search(value):
                raise ContractValidationError(f"{name} must not contain raw references")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_no_user_graph_raw_reference(str(key), name)
            _validate_no_user_graph_raw_reference(item, name)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_no_user_graph_raw_reference(item, name)


def _validate_no_user_graph_side_effect_claim(value: Any, name: str) -> None:
    if isinstance(value, str):
        for pattern in _USER_GRAPH_RESERVED_METADATA_PATTERNS:
            if pattern.search(value):
                raise ContractValidationError(f"{name} must not claim side effects")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_no_user_graph_side_effect_claim(str(key), name)
            _validate_no_user_graph_side_effect_claim(item, name)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_no_user_graph_side_effect_claim(item, name)


def validate_user_graph_profile(value: Any) -> dict[str, Any]:
    profile = _require_mapping(value, "UserGraphProfile")
    _require_fields(
        profile,
        (
            "graph_profile_id",
            "owner_user_id",
            "owner_scope_type",
            "owner_scope_id",
            "profile_name",
            "status",
            "created_at",
            "created_by",
        ),
        "UserGraphProfile",
    )
    _validate_string_fields(
        profile,
        (
            "graph_profile_id",
            "owner_user_id",
            "owner_scope_type",
            "owner_scope_id",
            "profile_name",
            "status",
            "created_at",
            "created_by",
        ),
        "UserGraphProfile",
    )
    _validate_optional_string_fields(
        profile,
        ("description", "default_assembly_policy_id"),
        "UserGraphProfile",
    )
    for field_name in (
        "graph_profile_id",
        "owner_user_id",
        "owner_scope_type",
        "owner_scope_id",
        "created_by",
    ):
        _validate_graph_reference_id(profile[field_name], f"UserGraphProfile.{field_name}")
    if profile.get("default_assembly_policy_id") is not None:
        _validate_graph_reference_id(
            profile["default_assembly_policy_id"],
            "UserGraphProfile.default_assembly_policy_id",
        )
    if (
        profile["owner_scope_type"] == "private_user"
        and profile["owner_scope_id"] != profile["owner_user_id"]
    ):
        raise ContractValidationError("UserGraphProfile.owner_scope_id must match owner_user_id")
    if profile["status"] not in USER_GRAPH_PROFILE_STATUS_VALUES:
        raise ContractValidationError("UserGraphProfile.status is not supported")
    _validate_iso_timestamp(profile["created_at"], "UserGraphProfile.created_at")
    for field_name in ("preferred_granularity", "view_preferences"):
        if not isinstance(profile.get(field_name, {}), dict):
            raise ContractValidationError(f"UserGraphProfile.{field_name} must be an object")
    _validate_no_user_graph_raw_reference(
        {
            "profile_name": profile["profile_name"],
            "description": profile.get("description"),
            "preferred_granularity": profile.get("preferred_granularity", {}),
            "view_preferences": profile.get("view_preferences", {}),
        },
        "UserGraphProfile",
    )
    _validate_no_user_graph_side_effect_claim(
        {
            "profile_name": profile["profile_name"],
            "owner_scope_type": profile["owner_scope_type"],
            "owner_scope_id": profile["owner_scope_id"],
            "description": profile.get("description"),
            "preferred_granularity": profile.get("preferred_granularity", {}),
            "view_preferences": profile.get("view_preferences", {}),
        },
        "UserGraphProfile",
    )
    return profile


def validate_user_graph_assembly_policy(value: Any) -> dict[str, Any]:
    policy = _require_mapping(value, "UserGraphAssemblyPolicy")
    rule_fields = (
        "include_rules",
        "exclude_rules",
        "grouping_rules",
        "granularity_rules",
        "relation_rules",
        "evidence_rules",
        "private_note_rules",
    )
    _require_fields(
        policy,
        (
            "assembly_policy_id",
            "policy_version",
            "owner_scope_type",
            "owner_scope_id",
            "graph_profile_id",
            "status",
            "created_at",
            "created_by",
            *rule_fields,
        ),
        "UserGraphAssemblyPolicy",
    )
    _validate_string_fields(
        policy,
        (
            "assembly_policy_id",
            "policy_version",
            "owner_scope_type",
            "owner_scope_id",
            "graph_profile_id",
            "status",
            "created_at",
            "created_by",
        ),
        "UserGraphAssemblyPolicy",
    )
    _validate_optional_string_fields(
        policy,
        ("parent_policy_id", "description"),
        "UserGraphAssemblyPolicy",
    )
    for field_name in (
        "assembly_policy_id",
        "policy_version",
        "owner_scope_type",
        "owner_scope_id",
        "graph_profile_id",
        "created_by",
    ):
        _validate_graph_reference_id(policy[field_name], f"UserGraphAssemblyPolicy.{field_name}")
    if policy.get("parent_policy_id") is not None:
        _validate_graph_reference_id(
            policy["parent_policy_id"],
            "UserGraphAssemblyPolicy.parent_policy_id",
        )
    if (
        policy["owner_scope_type"] == "private_user"
        and policy["owner_scope_id"] != policy["created_by"]
    ):
        raise ContractValidationError(
            "UserGraphAssemblyPolicy.owner_scope_id must match created_by"
        )
    if policy["status"] not in POLICY_STATUS_VALUES:
        raise ContractValidationError("UserGraphAssemblyPolicy.status is not supported")
    _validate_iso_timestamp(policy["created_at"], "UserGraphAssemblyPolicy.created_at")
    for field_name in rule_fields:
        if not isinstance(policy[field_name], dict):
            raise ContractValidationError(f"UserGraphAssemblyPolicy.{field_name} must be an object")
    _validate_no_user_graph_raw_reference(
        {
            "policy_version": policy["policy_version"],
            "description": policy.get("description"),
            "rules": {field_name: policy[field_name] for field_name in rule_fields},
        },
        "UserGraphAssemblyPolicy",
    )
    _validate_no_user_graph_side_effect_claim(
        {
            "owner_scope_type": policy["owner_scope_type"],
            "owner_scope_id": policy["owner_scope_id"],
            "description": policy.get("description"),
            "rules": {field_name: policy[field_name] for field_name in rule_fields},
        },
        "UserGraphAssemblyPolicy",
    )
    return policy


def validate_user_knowledge_graph_revision(value: Any) -> dict[str, Any]:
    revision = _require_mapping(value, "UserKnowledgeGraphRevision")
    _require_fields(
        revision,
        (
            "user_graph_revision_id",
            "user_id",
            "graph_profile_id",
            "canonical_graph_revision_id",
            "ontology_revision_id",
            "assembly_policy_id",
            "status",
            "included_atom_ids",
            "included_entity_ids",
            "included_relation_ids",
            "source_refs",
            "evidence_snapshot_ids",
            "permission_scope",
            "created_at",
            "created_by",
        ),
        "UserKnowledgeGraphRevision",
    )
    _validate_string_fields(
        revision,
        (
            "user_graph_revision_id",
            "user_id",
            "graph_profile_id",
            "canonical_graph_revision_id",
            "ontology_revision_id",
            "assembly_policy_id",
            "status",
            "created_at",
            "created_by",
        ),
        "UserKnowledgeGraphRevision",
    )
    _validate_optional_string_fields(
        revision,
        ("parent_user_graph_revision_id",),
        "UserKnowledgeGraphRevision",
    )
    for field_name in (
        "user_graph_revision_id",
        "user_id",
        "graph_profile_id",
        "canonical_graph_revision_id",
        "ontology_revision_id",
        "assembly_policy_id",
        "created_by",
    ):
        _validate_graph_reference_id(
            revision[field_name],
            f"UserKnowledgeGraphRevision.{field_name}",
        )
    if revision.get("parent_user_graph_revision_id") is not None:
        _validate_graph_reference_id(
            revision["parent_user_graph_revision_id"],
            "UserKnowledgeGraphRevision.parent_user_graph_revision_id",
        )
    if revision["status"] not in USER_GRAPH_REVISION_STATUS_VALUES:
        raise ContractValidationError("UserKnowledgeGraphRevision.status is not supported")
    _validate_iso_timestamp(revision["created_at"], "UserKnowledgeGraphRevision.created_at")
    for field_name in (
        "included_atom_ids",
        "included_entity_ids",
        "included_relation_ids",
        "excluded_atom_ids",
        "excluded_entity_ids",
        "excluded_relation_ids",
        "user_authored_atom_ids",
        "private_note_ids",
    ):
        _validate_unique_provenance_id_list(
            revision.get(field_name, []),
            f"UserKnowledgeGraphRevision.{field_name}",
        )
    for included_field, excluded_field in (
        ("included_atom_ids", "excluded_atom_ids"),
        ("included_entity_ids", "excluded_entity_ids"),
        ("included_relation_ids", "excluded_relation_ids"),
    ):
        if set(revision[included_field]).intersection(revision.get(excluded_field, [])):
            raise ContractValidationError(
                f"UserKnowledgeGraphRevision.{included_field} must not overlap " f"{excluded_field}"
            )
    if set(revision["included_atom_ids"]).intersection(revision.get("user_authored_atom_ids", [])):
        raise ContractValidationError(
            "UserKnowledgeGraphRevision.user_authored_atom_ids must not overlap included_atom_ids"
        )
    if set(revision.get("excluded_atom_ids", [])).intersection(
        revision.get("user_authored_atom_ids", [])
    ):
        raise ContractValidationError(
            "UserKnowledgeGraphRevision.user_authored_atom_ids must not overlap excluded_atom_ids"
        )
    if not any(
        (
            revision["included_atom_ids"],
            revision["included_entity_ids"],
            revision["included_relation_ids"],
            revision.get("user_authored_atom_ids", []),
        )
    ):
        raise ContractValidationError("UserKnowledgeGraphRevision must include graph content")
    if not isinstance(revision["source_refs"], list):
        raise ContractValidationError("UserKnowledgeGraphRevision.source_refs must be a list")
    if not revision["source_refs"]:
        raise ContractValidationError("UserKnowledgeGraphRevision.source_refs cannot be empty")
    source_refs = [validate_source_ref(source_ref) for source_ref in revision["source_refs"]]
    revision["source_refs"] = source_refs
    _validate_provenance_id_list(
        revision["evidence_snapshot_ids"],
        "UserKnowledgeGraphRevision.evidence_snapshot_ids",
        allow_empty=False,
    )
    permission_scope = validate_permission_scope(revision["permission_scope"])
    revision["permission_scope"] = permission_scope
    _validate_no_user_graph_raw_reference(
        permission_scope,
        "UserKnowledgeGraphRevision.permission_scope",
    )
    _validate_no_user_graph_side_effect_claim(
        permission_scope,
        "UserKnowledgeGraphRevision.permission_scope",
    )
    if (
        permission_scope.get("scope_type") == "private_user"
        and permission_scope.get("scope_id") != revision["user_id"]
    ):
        raise ContractValidationError(
            "UserKnowledgeGraphRevision.permission_scope must match user_id"
        )
    if not isinstance(revision.get("assembly_metadata", {}), dict):
        raise ContractValidationError(
            "UserKnowledgeGraphRevision.assembly_metadata must be an object"
        )
    if not any(
        source_ref.get("source_type") == "canonical_graph"
        and source_ref.get("source_id") == revision["canonical_graph_revision_id"]
        for source_ref in revision["source_refs"]
    ):
        raise ContractValidationError(
            "UserKnowledgeGraphRevision.source_refs must include canonical graph revision"
        )
    _validate_no_user_graph_raw_reference(
        {
            "source_refs": revision["source_refs"],
            "assembly_metadata": revision.get("assembly_metadata", {}),
        },
        "UserKnowledgeGraphRevision",
    )
    _validate_no_user_graph_side_effect_claim(
        {
            "source_refs": revision["source_refs"],
            "assembly_metadata": revision.get("assembly_metadata", {}),
        },
        "UserKnowledgeGraphRevision",
    )
    return revision


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
        (
            "session_id",
            "project_id",
            "customer_id",
            "asset_id",
            "ingestion_job_id",
            "completed_at",
        ),
        "UploadSession",
    )
    if upload_session["status"] not in UPLOAD_SESSION_STATUS_VALUES:
        raise ContractValidationError("UploadSession.status is not supported")
    validate_permission_scope(upload_session["permission_scope"])
    return upload_session
