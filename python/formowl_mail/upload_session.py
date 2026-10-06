from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping, Sequence

from formowl_auth import FileAuditLogStore
from formowl_contract import (
    ContractValidationError,
    PermissionScope,
    UploadSession,
    now_iso,
    sha256_json,
)
from formowl_gateway import validate_public_gateway_payload
from formowl_ingestion.storage import UploadSessionRecordStore
from formowl_ingestion.uploads import create_upload_session

from ._guards import assert_public_payload_safe, safe_public_string
from ._validation import dict_or_empty

_MAIL_INTENDED_ASSET_TYPES = {"mail_archive", "pst", "ost", "msg", "eml", "mbox"}
_MAIL_INGESTION_PROFILE = "mail_archive_phase1"
_UPLOAD_SURFACE_PREFIX = "formowl_upload_session:"
_SUPPORTED_MAIL_EXTENSIONS = ("pst", "ost", "msg", "eml", "mbox")
_OWNER_SCOPE_TYPES = {"workspace", "project", "customer", "private_user"}
_VISIBILITY_SCOPES = {"private", "workspace", "project", "customer"}
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ALLOWED_PUBLIC_INPUT_KEYS = {
    "requester_user_id",
    "session_id",
    "workspace_id",
    "intent",
    "intended_asset_type",
    "ingestion_profile",
    "owner_scope_type",
    "owner_scope_id",
    "visibility_scope",
    "permission_scope",
    "project_id",
    "customer_id",
}
_FORBIDDEN_USER_CONTROL_KEYS = {
    "backend",
    "bucket",
    "bucket_name",
    "companion_manifest_path",
    "connection_string",
    "database_url",
    "dsn",
    "local_path",
    "mailbox_password",
    "nas_path",
    "object_key",
    "object_store",
    "object_store_uri",
    "parser",
    "parser_config",
    "parser_name",
    "parser_path",
    "pst_path",
    "raw_path",
    "retention_override",
    "signed_url",
    "storage_backend",
    "storage_backend_id",
    "token",
    "worker",
    "worker_queue",
}
_FORBIDDEN_COMPACT_USER_CONTROL_KEYS = {
    re.sub(r"[^a-z0-9]+", "", key.lower()) for key in _FORBIDDEN_USER_CONTROL_KEYS
}
_FORBIDDEN_USER_CONTROL_PARTS = {
    "backend",
    "bucket",
    "dsn",
    "nas",
    "object",
    "parser",
    "password",
    "path",
    "queue",
    "secret",
    "storage",
    "token",
    "worker",
}


@dataclass(frozen=True)
class MailUploadSessionTaskResult:
    upload_session: UploadSession
    upload_surface_locator: str
    generated_at: str

    def to_public_dict(self) -> dict[str, Any]:
        upload_session = self.upload_session
        task_card = {
            "card_type": "mail_archive_upload_task",
            "upload_session_id": upload_session.upload_session_id,
            "current_user_id": upload_session.actor_user_id,
            "workspace_id": upload_session.workspace_id,
            "owner_scope": {
                "scope_type": upload_session.owner_scope_type,
                "scope_id": upload_session.owner_scope_id,
            },
            "project_id": upload_session.project_id,
            "customer_id": upload_session.customer_id,
            "intended_asset_type": upload_session.intended_asset_type,
            "accepted_file_types": list(_SUPPORTED_MAIL_EXTENSIONS),
            "ingestion_profile": upload_session.ingestion_profile,
            "visibility_scope": upload_session.visibility_scope,
            "source_preparation_state": upload_session.source_preparation_state,
            "processing_status": upload_session.processing_status,
            "upload_surface_locator": self.upload_surface_locator,
            "next_required_action": "upload_prepared_mail_archive",
        }
        payload = {
            "status": "ok",
            "upload_session_id": upload_session.upload_session_id,
            "next_required_action": "upload_prepared_mail_archive",
            "upload_task_card": task_card,
            "source_preparation_guidance": {
                "guide_type": "mail_archive_export",
                "ordinary_phase1_requires_local_companion": False,
                "user_must_choose_storage_backend": False,
                "user_must_choose_parser_or_worker": False,
                "instructions": [
                    "Export the mailbox or selected mail folder as PST, OST, MSG, EML, or MBOX.",
                    "Return to this FormOwl upload task and attach the prepared archive.",
                    (
                        "Keep the upload tied to this session so ownership, "
                        "scope, and audit stay intact."
                    ),
                ],
            },
            "public_checks": {
                "upload_session_created": True,
                "session_bound": bool(upload_session.session_id),
                "mail_profile_bound": upload_session.ingestion_profile == _MAIL_INGESTION_PROFILE,
                "no_user_infrastructure_controls_exposed": True,
                "upload_surface_is_session_bound": self.upload_surface_locator
                == _upload_surface_locator(upload_session.upload_session_id),
            },
            "safe_outputs": {
                "upload_session_id_hash": sha256_json(upload_session.upload_session_id),
                "task_card_hash": sha256_json(task_card),
            },
            "claim_boundary": {
                "supports_chatgpt_mail_upload_task_card_claim": True,
                "supports_real_upload_iframe_claim": False,
                "supports_real_pst_parser_claim": False,
                "supports_live_postgresql_readiness_claim": False,
                "supports_production_worker_leasing_claim": False,
                "supports_kg_write_claim": False,
                "supports_wiki_projection_claim": False,
                "supports_production_ready_claim": False,
                "container_verification_required": True,
            },
        }
        validation = validate_mail_upload_session_task(payload)
        payload["validation"] = validation
        return payload


def build_mail_upload_session_handler(
    *,
    upload_session_store: UploadSessionRecordStore,
    audit_store: FileAuditLogStore,
    expires_at: str | None = None,
    expires_at_provider: Callable[[], str] | None = None,
    created_at: str | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    if (expires_at is None) == (expires_at_provider is None):
        raise ContractValidationError("exactly one upload session expiry source must be configured")

    def handler(input_data: dict[str, Any]) -> dict[str, Any]:
        resolved_expires_at = (
            expires_at_provider() if expires_at_provider is not None else expires_at
        )
        result = open_mail_upload_session(
            input_data,
            upload_session_store=upload_session_store,
            audit_store=audit_store,
            expires_at=_required_public_string(resolved_expires_at, "expires_at"),
            created_at=created_at,
        )
        return result.to_public_dict()

    return handler


def open_mail_upload_session(
    input_data: Mapping[str, Any],
    *,
    upload_session_store: UploadSessionRecordStore,
    audit_store: FileAuditLogStore,
    expires_at: str,
    created_at: str | None = None,
) -> MailUploadSessionTaskResult:
    validate_public_gateway_payload(input_data)
    _reject_unknown_public_input_keys(input_data)
    _reject_user_infrastructure_controls(input_data)
    actor_user_id = _required_public_string(input_data.get("requester_user_id"), "requester")
    session_id = _required_public_string(input_data.get("session_id"), "session")
    workspace_id = _required_public_string(input_data.get("workspace_id"), "workspace")
    intent = _required_public_string(
        input_data.get("intent"),
        "Upload mail archive for FormOwl mail evidence reading.",
    )
    intended_asset_type = _mail_asset_type(input_data.get("intended_asset_type"))
    requested_profile = input_data.get("ingestion_profile")
    if requested_profile not in (None, "", _MAIL_INGESTION_PROFILE):
        raise ContractValidationError("mail upload sessions must use the Phase 1 mail profile")
    owner_scope_type = _optional_public_string(input_data.get("owner_scope_type"), "workspace")
    if owner_scope_type not in _OWNER_SCOPE_TYPES:
        raise ContractValidationError("mail upload owner scope type is not supported")
    owner_scope_id = _optional_public_string(input_data.get("owner_scope_id"), workspace_id)
    visibility_scope = _optional_public_string(input_data.get("visibility_scope"), "workspace")
    if visibility_scope not in _VISIBILITY_SCOPES:
        raise ContractValidationError("mail upload visibility scope is not supported")
    project_id = _optional_public_string_or_none(input_data.get("project_id"))
    customer_id = _optional_public_string_or_none(input_data.get("customer_id"))
    if owner_scope_type == "project" and project_id is None:
        project_id = owner_scope_id
    permission_scope = _matching_permission_scope(
        input_data.get("permission_scope"),
        owner_scope_type=owner_scope_type,
        owner_scope_id=owner_scope_id,
    )
    timestamp = created_at or now_iso()
    upload_session = create_upload_session(
        upload_session_store=upload_session_store,
        audit_store=audit_store,
        actor_user_id=actor_user_id,
        session_id=session_id,
        workspace_id=workspace_id,
        owner_scope_type=owner_scope_type,
        owner_scope_id=owner_scope_id,
        intent=intent,
        intended_asset_type=intended_asset_type,
        ingestion_profile=_MAIL_INGESTION_PROFILE,
        visibility_scope=visibility_scope,
        permission_scope=permission_scope,
        expires_at=_required_public_string(expires_at, "expires_at"),
        source_preparation_state="mail_archive_export_guidance_attached",
        processing_status="waiting_for_upload",
        created_at=timestamp,
        project_id=project_id,
        customer_id=customer_id,
    )
    assert_public_payload_safe(upload_session.to_dict(), "mail_upload_session")
    return MailUploadSessionTaskResult(
        upload_session=upload_session,
        upload_surface_locator=_upload_surface_locator(upload_session.upload_session_id),
        generated_at=timestamp,
    )


def validate_mail_upload_session_task(payload: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    value = dict(payload)
    _expect_keys(
        value,
        {
            "status",
            "upload_session_id",
            "next_required_action",
            "upload_task_card",
            "source_preparation_guidance",
            "public_checks",
            "safe_outputs",
            "claim_boundary",
        },
        "mail_upload_session_task",
        blockers,
        allow_validation=True,
    )
    if value.get("status") != "ok":
        blockers.append("status must be ok")
    if not isinstance(value.get("upload_session_id"), str) or not value["upload_session_id"]:
        blockers.append("upload_session_id must be a non-empty string")
    if value.get("next_required_action") != "upload_prepared_mail_archive":
        blockers.append("next_required_action must require mail archive upload")
    task_card = dict_or_empty(value.get("upload_task_card"), "upload_task_card", blockers)
    _expect_keys(
        task_card,
        {
            "card_type",
            "upload_session_id",
            "current_user_id",
            "workspace_id",
            "owner_scope",
            "project_id",
            "customer_id",
            "intended_asset_type",
            "accepted_file_types",
            "ingestion_profile",
            "visibility_scope",
            "source_preparation_state",
            "processing_status",
            "upload_surface_locator",
            "next_required_action",
        },
        "upload_task_card",
        blockers,
    )
    if task_card.get("card_type") != "mail_archive_upload_task":
        blockers.append("upload_task_card.card_type must be mail_archive_upload_task")
    owner_scope = dict_or_empty(
        task_card.get("owner_scope"),
        "upload_task_card.owner_scope",
        blockers,
    )
    _expect_keys(
        owner_scope,
        {"scope_type", "scope_id"},
        "upload_task_card.owner_scope",
        blockers,
    )
    if task_card.get("upload_session_id") != value.get("upload_session_id"):
        blockers.append("task card must use the same upload session id")
    if task_card.get("ingestion_profile") != _MAIL_INGESTION_PROFILE:
        blockers.append("task card must bind the mail ingestion profile")
    if tuple(task_card.get("accepted_file_types", ())) != _SUPPORTED_MAIL_EXTENSIONS:
        blockers.append("task card must list exactly the supported mail archive types")
    expected_locator = _upload_surface_locator(str(value.get("upload_session_id", "")))
    if task_card.get("upload_surface_locator") != expected_locator:
        blockers.append("upload surface locator must be session-bound")
    guidance = dict_or_empty(
        value.get("source_preparation_guidance"),
        "source_preparation_guidance",
        blockers,
    )
    _expect_keys(
        guidance,
        {
            "guide_type",
            "ordinary_phase1_requires_local_companion",
            "user_must_choose_storage_backend",
            "user_must_choose_parser_or_worker",
            "instructions",
        },
        "source_preparation_guidance",
        blockers,
    )
    if guidance.get("ordinary_phase1_requires_local_companion") is not False:
        blockers.append("ordinary Phase 1 must not require Local Companion")
    if guidance.get("user_must_choose_storage_backend") is not False:
        blockers.append("users must not choose storage backends")
    if guidance.get("user_must_choose_parser_or_worker") is not False:
        blockers.append("users must not choose parsers or workers")
    if not isinstance(guidance.get("instructions"), list) or not guidance["instructions"]:
        blockers.append("source preparation guidance must include instructions")
    public_checks = dict_or_empty(value.get("public_checks"), "public_checks", blockers)
    _expect_keys(
        public_checks,
        {
            "upload_session_created",
            "session_bound",
            "mail_profile_bound",
            "no_user_infrastructure_controls_exposed",
            "upload_surface_is_session_bound",
        },
        "public_checks",
        blockers,
    )
    for key in (
        "upload_session_created",
        "session_bound",
        "mail_profile_bound",
        "no_user_infrastructure_controls_exposed",
        "upload_surface_is_session_bound",
    ):
        if public_checks.get(key) is not True:
            blockers.append(f"public check is not true: {key}")
    safe_outputs = dict_or_empty(value.get("safe_outputs"), "safe_outputs", blockers)
    _expect_keys(
        safe_outputs,
        {"upload_session_id_hash", "task_card_hash"},
        "safe_outputs",
        blockers,
    )
    for key in ("upload_session_id_hash", "task_card_hash"):
        item = safe_outputs.get(key)
        if not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None:
            blockers.append(f"safe output must be sha256: {key}")
    claim_boundary = dict_or_empty(value.get("claim_boundary"), "claim_boundary", blockers)
    expected_claim_boundary = {
        "supports_chatgpt_mail_upload_task_card_claim": True,
        "supports_real_upload_iframe_claim": False,
        "supports_real_pst_parser_claim": False,
        "supports_live_postgresql_readiness_claim": False,
        "supports_production_worker_leasing_claim": False,
        "supports_kg_write_claim": False,
        "supports_wiki_projection_claim": False,
        "supports_production_ready_claim": False,
        "container_verification_required": True,
    }
    _expect_keys(
        claim_boundary,
        set(expected_claim_boundary),
        "claim_boundary",
        blockers,
    )
    for key, expected in expected_claim_boundary.items():
        if claim_boundary.get(key) is not expected:
            blockers.append(f"claim boundary mismatch: {key}")
    if "validation" in value:
        validation = dict_or_empty(value["validation"], "validation", blockers)
        _expect_keys(
            validation,
            {"passed", "blockers", "claim_boundary"},
            "validation",
            blockers,
        )
        if validation.get("passed") is not True:
            blockers.append("embedded validation must pass")
        if validation.get("blockers") != []:
            blockers.append("embedded validation blockers must be empty")
        validation_claim_boundary = dict_or_empty(
            validation.get("claim_boundary"),
            "validation.claim_boundary",
            blockers,
        )
        _expect_keys(
            validation_claim_boundary,
            {
                "supports_chatgpt_mail_upload_task_card_claim",
                "supports_production_ready_claim",
            },
            "validation.claim_boundary",
            blockers,
        )
        if (
            validation_claim_boundary.get("supports_chatgpt_mail_upload_task_card_claim")
            is not True
        ):
            blockers.append("validation mail upload task claim must be true")
        if validation_claim_boundary.get("supports_production_ready_claim") is not False:
            blockers.append("validation production claim must be false")
    try:
        validate_public_gateway_payload(value)
        assert_public_payload_safe(value, "mail_upload_session_task")
    except Exception:
        blockers.append("mail upload task leaks raw paths or backend controls")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_chatgpt_mail_upload_task_card_claim": not blockers,
            "supports_production_ready_claim": False,
        },
    }


def _reject_user_infrastructure_controls(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            normalized = _normalize_public_key(key_text)
            compact = normalized.replace("_", "")
            if (
                normalized in _FORBIDDEN_USER_CONTROL_KEYS
                or compact in _FORBIDDEN_COMPACT_USER_CONTROL_KEYS
                or _has_forbidden_control_parts(normalized)
            ):
                raise ContractValidationError("mail upload tasks must not expose infrastructure")
            _reject_user_infrastructure_controls(
                item,
                f"{path}.{key_text}" if path else key_text,
            )
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_user_infrastructure_controls(item, f"{path}[{index}]")


def _normalize_public_key(value: str) -> str:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.strip())
    return re.sub(r"[^a-z0-9]+", "_", camel_split.lower()).strip("_")


def _has_forbidden_control_parts(normalized_key: str) -> bool:
    parts = {part for part in normalized_key.split("_") if part}
    return bool(parts & _FORBIDDEN_USER_CONTROL_PARTS)


def _reject_unknown_public_input_keys(input_data: Mapping[str, Any]) -> None:
    unknown = sorted(set(input_data) - _ALLOWED_PUBLIC_INPUT_KEYS)
    if unknown:
        raise ContractValidationError(
            "mail upload task contains unsupported public input keys: " + sha256_json(unknown)
        )


def _matching_permission_scope(
    value: Any,
    *,
    owner_scope_type: str,
    owner_scope_id: str,
) -> PermissionScope:
    if value in (None, ""):
        return PermissionScope(
            scope_type=owner_scope_type,
            scope_id=owner_scope_id,
            visibility="restricted",
        )
    if not isinstance(value, Mapping):
        raise ContractValidationError("permission_scope must be an object")
    validate_public_gateway_payload(value)
    _reject_unknown_permission_scope_keys(value)
    scope_type = _required_public_string(value.get("scope_type"), "scope_type")
    scope_id = _required_public_string(value.get("scope_id"), "scope_id")
    visibility = _optional_public_string(value.get("visibility"), "restricted")
    if visibility != "restricted":
        raise ContractValidationError("mail upload permission_scope visibility must be restricted")
    if scope_type != owner_scope_type or scope_id != owner_scope_id:
        raise ContractValidationError("permission_scope must match the upload owner scope")
    return PermissionScope(scope_type=scope_type, scope_id=scope_id, visibility=visibility)


def _reject_unknown_permission_scope_keys(value: Mapping[str, Any]) -> None:
    unknown = sorted(set(value) - {"scope_type", "scope_id", "visibility"})
    if unknown:
        raise ContractValidationError(
            "permission_scope contains unsupported keys: " + sha256_json(unknown)
        )


def _mail_asset_type(value: Any) -> str:
    intended_asset_type = _optional_public_string(value, "mail_archive").lower()
    if intended_asset_type not in _MAIL_INTENDED_ASSET_TYPES:
        raise ContractValidationError("open_upload_session is configured for mail archives")
    return intended_asset_type


def _upload_surface_locator(upload_session_id: str) -> str:
    locator = _UPLOAD_SURFACE_PREFIX + upload_session_id
    validate_public_gateway_payload(locator)
    return locator


def _required_public_string(value: Any, fallback: str) -> str:
    text = safe_public_string(value, fallback)
    if not text.strip():
        raise ContractValidationError("public string value is required")
    return text


def _optional_public_string(value: Any, fallback: str) -> str:
    text = safe_public_string(value, fallback)
    if not text.strip():
        return fallback
    return text


def _optional_public_string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return _optional_public_string(value, "")


def _expect_keys(
    value: Mapping[str, Any],
    expected: set[str],
    context: str,
    blockers: list[str],
    *,
    allow_validation: bool = False,
) -> None:
    actual = set(value)
    allowed = set(expected)
    if allow_validation:
        allowed.add("validation")
    extra = sorted(actual - allowed)
    missing = sorted(expected - actual)
    if extra:
        blockers.append(f"{context} contains unexpected keys: {sha256_json(extra)}")
    if missing:
        blockers.append(f"{context} missing keys: {sha256_json(missing)}")


__all__ = [
    "MailUploadSessionTaskResult",
    "build_mail_upload_session_handler",
    "open_mail_upload_session",
    "validate_mail_upload_session_task",
]
