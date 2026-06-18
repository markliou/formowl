"""ChatGPT session capture workflow for source-backed ingestion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from formowl_auth.audit import (
    FileAuditLogStore,
    record_chatgpt_session_capture,
)
from formowl_contract import (
    Asset,
    ContractValidationError,
    IngestionJob,
    PermissionScope,
    SourceRef,
    stable_resource_contract_hash,
    stable_resource_contract_id,
    to_plain,
    validate_permission_scope,
)

from .assets import register_asset_from_local_file
from .jobs import create_ingestion_job
from .storage import AssetStore, FileObjectStore, JobStore

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class ChatGptSessionCapture:
    capture_id: str
    source_system: str
    source_account_id: str
    source_account_identity_hash: str
    capture_method: str
    captured_by: str
    captured_at: str
    ingested_at: str
    workspace_id: str
    visibility_scope: str
    permission_scope: PermissionScope | dict[str, Any]
    source_account_metadata: dict[str, Any]
    manifest_hash: str
    audit_log_id: str
    asset_id: str
    ingestion_job_id: str
    project_id: str | None = None
    customer_id: str | None = None
    asset_object_uri: str | None = None
    processing_status: str = "queued"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ChatGptSessionCapture":
        _validate_capture(value)
        return cls(
            capture_id=str(value["capture_id"]),
            source_system=str(value["source_system"]),
            source_account_id=str(value["source_account_id"]),
            source_account_identity_hash=str(value["source_account_identity_hash"]),
            capture_method=str(value["capture_method"]),
            captured_by=str(value["captured_by"]),
            captured_at=str(value["captured_at"]),
            ingested_at=str(value["ingested_at"]),
            workspace_id=str(value["workspace_id"]),
            visibility_scope=str(value["visibility_scope"]),
            permission_scope=value["permission_scope"],
            source_account_metadata=dict(value.get("source_account_metadata", {})),
            manifest_hash=str(value["manifest_hash"]),
            audit_log_id=str(value["audit_log_id"]),
            asset_id=str(value["asset_id"]),
            ingestion_job_id=str(value["ingestion_job_id"]),
            project_id=value.get("project_id"),
            customer_id=value.get("customer_id"),
            asset_object_uri=value.get("asset_object_uri"),
            processing_status=str(value.get("processing_status", "queued")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = to_plain(self)
        _validate_capture(data)
        return data


@dataclass(frozen=True)
class ChatGptSessionCaptureResult:
    capture: ChatGptSessionCapture
    asset: Asset
    ingestion_job: IngestionJob

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


class ChatGptSessionCaptureStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir) / "ingestion" / "chatgpt-session-captures"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create(self, capture: ChatGptSessionCapture | dict[str, Any]) -> ChatGptSessionCapture:
        validated = (
            ChatGptSessionCapture.from_dict(capture)
            if isinstance(capture, dict)
            else ChatGptSessionCapture.from_dict(capture.to_dict())
        )
        _write_json(self._record_path(validated.capture_id), validated.to_dict())
        return validated

    def get(self, capture_id: str) -> ChatGptSessionCapture | None:
        path = self._record_path(capture_id)
        if not path.exists():
            return None
        return ChatGptSessionCapture.from_dict(_read_json(path))

    def list(self) -> list[ChatGptSessionCapture]:
        return [
            ChatGptSessionCapture.from_dict(_read_json(path))
            for path in sorted(self.base_dir.glob("*.json"))
        ]

    def _record_path(self, capture_id: str) -> Path:
        if not capture_id or not _SAFE_RECORD_ID.fullmatch(capture_id):
            raise ValueError("capture_id must be a safe file name")
        return self.base_dir / f"{capture_id}.json"


def capture_current_chatgpt_session(
    *,
    messages: Sequence[Mapping[str, Any]],
    capture_store: ChatGptSessionCaptureStore,
    object_store: FileObjectStore,
    asset_store: AssetStore,
    job_store: JobStore,
    audit_store: FileAuditLogStore,
    storage_backend_id: str,
    actor_user_id: str,
    session_id: str,
    workspace_id: str,
    permission_scope: PermissionScope | dict[str, object],
    source_account_id: str,
    visibility_scope: str,
    capture_method: str,
    captured_at: str,
    ingested_at: str,
    extractor_names: Sequence[str],
    source_account_metadata: Mapping[str, Any] | None = None,
    project_id: str | None = None,
    customer_id: str | None = None,
) -> ChatGptSessionCaptureResult:
    _validate_capture_workflow_inputs(
        messages=messages,
        object_store=object_store,
        storage_backend_id=storage_backend_id,
        actor_user_id=actor_user_id,
        session_id=session_id,
        workspace_id=workspace_id,
        permission_scope=permission_scope,
        source_account_id=source_account_id,
        visibility_scope=visibility_scope,
        capture_method=capture_method,
        captured_at=captured_at,
        ingested_at=ingested_at,
        source_account_metadata=source_account_metadata,
        project_id=project_id,
        customer_id=customer_id,
    )
    normalized_messages = [dict(message) for message in messages]
    resolved_extractor_names = _validate_extractor_names(extractor_names)

    manifest = {
        "messages": normalized_messages,
        "source_account_metadata": dict(source_account_metadata or {}),
        "capture_method": capture_method,
        "source_account_id": source_account_id,
    }
    manifest_hash = stable_resource_contract_hash("ChatGptSessionCaptureManifest", manifest)
    capture_id = stable_resource_contract_id(
        "cap",
        "ChatGptSessionCapture",
        {
            "actor_user_id": actor_user_id,
            "workspace_id": workspace_id,
            "source_account_id": source_account_id,
            "manifest_hash": manifest_hash,
            "captured_at": captured_at,
        },
    )
    audit_log = record_chatgpt_session_capture(
        audit_store,
        actor_user_id=actor_user_id,
        capture_id=capture_id,
        workspace_id=workspace_id,
        session_id=session_id,
        timestamp=captured_at,
    )
    source_ref = SourceRef(
        source_system="chatgpt",
        source_type="session_capture",
        source_id=capture_id,
        source_key=capture_id,
    )
    rendered = _render_session_markdown(
        capture_id=capture_id,
        messages=normalized_messages,
        manifest_hash=manifest_hash,
    )

    # A short-lived backend-local scratch file lets the existing object-store
    # path copy bytes through the same asset boundary as other source artifacts.
    capture_path = _write_backend_scratch_capture(
        object_store=object_store,
        storage_backend_id=storage_backend_id,
        capture_id=capture_id,
        rendered=rendered,
    )
    try:
        asset = register_asset_from_local_file(
            capture_path,
            object_store=object_store,
            asset_store=asset_store,
            storage_backend_id=storage_backend_id,
            workspace_id=workspace_id,
            owner_user_id=actor_user_id,
            permission_scope=permission_scope,
            source_ref=source_ref,
            mime_type="text/markdown",
            project_id=project_id,
            created_at=captured_at,
            registered_at=ingested_at,
            audit_store=audit_store,
            actor_user_id=actor_user_id,
            session_id=session_id,
        )
    finally:
        capture_path.unlink(missing_ok=True)

    ingestion_job = create_ingestion_job(
        asset=asset,
        job_store=job_store,
        requested_by=actor_user_id,
        extractor_names=resolved_extractor_names,
        created_at=ingested_at,
        audit_store=audit_store,
        actor_user_id=actor_user_id,
        session_id=session_id,
    )
    capture = ChatGptSessionCapture(
        capture_id=capture_id,
        source_system="chatgpt",
        source_account_id=source_account_id,
        source_account_identity_hash=stable_resource_contract_hash(
            "ChatGptSourceAccountIdentity",
            {"source_system": "chatgpt", "source_account_id": source_account_id},
        ),
        capture_method=capture_method,
        captured_by=actor_user_id,
        captured_at=captured_at,
        ingested_at=ingested_at,
        workspace_id=workspace_id,
        visibility_scope=visibility_scope,
        permission_scope=permission_scope,
        source_account_metadata=dict(source_account_metadata or {}),
        manifest_hash=manifest_hash,
        audit_log_id=audit_log.audit_log_id,
        asset_id=asset.asset_id,
        ingestion_job_id=ingestion_job.ingestion_job_id,
        project_id=project_id,
        customer_id=customer_id,
        asset_object_uri=asset.object_uri,
        processing_status="queued",
    )
    return ChatGptSessionCaptureResult(
        capture=capture_store.create(capture),
        asset=asset,
        ingestion_job=ingestion_job,
    )


def _validate_capture_workflow_inputs(
    *,
    messages: Sequence[Mapping[str, Any]],
    object_store: FileObjectStore,
    storage_backend_id: str,
    actor_user_id: str,
    session_id: str,
    workspace_id: str,
    permission_scope: PermissionScope | dict[str, object],
    source_account_id: str,
    visibility_scope: str,
    capture_method: str,
    captured_at: str,
    ingested_at: str,
    source_account_metadata: Mapping[str, Any] | None,
    project_id: str | None,
    customer_id: str | None,
) -> None:
    # All workflow inputs that can invalidate the capture must be checked before
    # audit, scratch, object, asset, job, or capture records are written.
    if not messages:
        raise ValueError("messages cannot be empty")
    if not all(isinstance(message, Mapping) for message in messages):
        raise ContractValidationError("messages entries must be objects")
    for index, message in enumerate(messages, start=1):
        content = message.get("content")
        if not isinstance(content, str):
            raise ContractValidationError(f"messages[{index}].content must be a string")
        for field_name in ("role", "message_id"):
            value = message.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ContractValidationError(
                    f"messages[{index}].{field_name} must be a string"
                )
    for field_name, value in (
        ("storage_backend_id", storage_backend_id),
        ("actor_user_id", actor_user_id),
        ("session_id", session_id),
        ("workspace_id", workspace_id),
        ("source_account_id", source_account_id),
        ("visibility_scope", visibility_scope),
        ("capture_method", capture_method),
        ("captured_at", captured_at),
        ("ingested_at", ingested_at),
    ):
        if not isinstance(value, str) or not value:
            raise ContractValidationError(f"{field_name} must be a non-empty string")
    validate_permission_scope(permission_scope)
    if source_account_metadata is not None and not isinstance(source_account_metadata, Mapping):
        raise ContractValidationError("source_account_metadata must be an object")
    for field_name, value in (("project_id", project_id), ("customer_id", customer_id)):
        if value is not None and not isinstance(value, str):
            raise ContractValidationError(f"{field_name} must be a string")
    if object_store.backend_registry.resolve_local_root(storage_backend_id) is None:
        raise FileNotFoundError(f"local storage backend not found: {storage_backend_id}")


def _validate_extractor_names(extractor_names: Sequence[str]) -> list[str]:
    names = list(extractor_names)
    if not names:
        raise ValueError("at least one extractor name is required")
    if not all(isinstance(name, str) and name for name in names):
        raise ValueError("extractor names must be non-empty strings")
    if len(set(names)) != len(names):
        raise ValueError("extractor names must be unique")
    return names


def _render_session_markdown(
    *,
    capture_id: str,
    messages: Sequence[Mapping[str, Any]],
    manifest_hash: str,
) -> str:
    lines = [
        f"# ChatGPT Session Capture {capture_id}",
        "",
        f"- Manifest hash: {manifest_hash}",
        "",
    ]
    for index, message in enumerate(messages, start=1):
        role = str(message.get("role") or "unknown")
        message_id = str(message.get("message_id") or index)
        content = str(message.get("content") or "")
        lines.extend([f"## {index}. {role} ({message_id})", "", content, ""])
    return "\n".join(lines)


def _write_backend_scratch_capture(
    *,
    object_store: FileObjectStore,
    storage_backend_id: str,
    capture_id: str,
    rendered: str,
) -> Path:
    local_root = object_store.backend_registry.resolve_local_root(storage_backend_id)
    if local_root is None:
        raise FileNotFoundError(f"local storage backend not found: {storage_backend_id}")
    scratch_dir = local_root / "scratch" / "chatgpt-session-captures"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    capture_path = scratch_dir / f"{capture_id}.md"
    capture_path.write_text(rendered, encoding="utf-8")
    return capture_path


def _validate_capture(value: dict[str, Any]) -> None:
    required_fields = (
        "capture_id",
        "source_system",
        "source_account_id",
        "source_account_identity_hash",
        "capture_method",
        "captured_by",
        "captured_at",
        "ingested_at",
        "workspace_id",
        "visibility_scope",
        "permission_scope",
        "source_account_metadata",
        "manifest_hash",
        "audit_log_id",
        "asset_id",
        "ingestion_job_id",
    )
    missing = [field for field in required_fields if value.get(field) in (None, "")]
    if missing:
        raise ContractValidationError(
            f"ChatGptSessionCapture missing field(s): {', '.join(missing)}"
        )
    _validate_capture_string_fields(
        value,
        (
            "capture_id",
            "source_system",
            "source_account_id",
            "source_account_identity_hash",
            "capture_method",
            "captured_by",
            "captured_at",
            "ingested_at",
            "workspace_id",
            "visibility_scope",
            "manifest_hash",
            "audit_log_id",
            "asset_id",
            "ingestion_job_id",
        ),
    )
    _validate_optional_capture_string_fields(
        value,
        ("project_id", "customer_id", "asset_object_uri", "processing_status"),
    )
    if value["source_system"] != "chatgpt":
        raise ContractValidationError("ChatGptSessionCapture.source_system must be chatgpt")
    if not isinstance(value["source_account_metadata"], dict):
        raise ContractValidationError(
            "ChatGptSessionCapture.source_account_metadata must be an object"
        )
    asset_object_uri = value.get("asset_object_uri")
    if asset_object_uri is not None and not asset_object_uri.startswith("formowl://"):
        raise ContractValidationError(
            "ChatGptSessionCapture.asset_object_uri must be a FormOwl locator"
        )
    validate_permission_scope(value["permission_scope"])


def _validate_capture_string_fields(value: dict[str, Any], field_names: tuple[str, ...]) -> None:
    for field_name in field_names:
        if not isinstance(value[field_name], str):
            raise ContractValidationError(f"ChatGptSessionCapture.{field_name} must be a string")


def _validate_optional_capture_string_fields(
    value: dict[str, Any],
    field_names: tuple[str, ...],
) -> None:
    for field_name in field_names:
        if (
            field_name in value
            and value[field_name] is not None
            and not isinstance(value[field_name], str)
        ):
            raise ContractValidationError(f"ChatGptSessionCapture.{field_name} must be a string")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(to_plain(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


__all__ = [
    "ChatGptSessionCapture",
    "ChatGptSessionCaptureResult",
    "ChatGptSessionCaptureStore",
    "capture_current_chatgpt_session",
]
