from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

JsonValue = Any
McpResultStatus = Literal[
    "ok",
    "partial",
    "not_found",
    "permission_denied",
    "pending_review",
    "error",
]


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
    payload = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


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
