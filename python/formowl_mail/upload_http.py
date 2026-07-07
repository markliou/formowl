from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from html import escape
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

from formowl_auth.audit import FileAuditLogStore
from formowl_contract import ContractValidationError, now_iso, sha256_json
from formowl_gateway import validate_public_gateway_payload
from formowl_ingestion.storage import AssetStore, FileObjectStore, UploadSessionRecordStore

from ._guards import assert_public_payload_safe
from .upload_surface import (
    receive_mail_archive_upload,
    validate_mail_upload_surface_receipt,
)

_UPLOAD_PATH_PREFIX = ("mail", "upload")
_UPLOAD_FILE_FIELD = "mail_archive"
_ALLOWED_MULTIPART_FIELDS = {
    _UPLOAD_FILE_FIELD,
    "upload_session_id",
    "workspace_id",
    "expected_content_hash",
}
_FORBIDDEN_FORM_FIELD_PARTS = {
    "backend",
    "bucket",
    "database",
    "dsn",
    "folder",
    "key",
    "nas",
    "object",
    "parser",
    "path",
    "queue",
    "secret",
    "storage",
    "token",
    "worker",
}
_SAFE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SUPPORTED_ACCEPT_EXTENSIONS = ".pst,.ost,.msg,.eml,.mbox"
_MAIL_INTENDED_ASSET_TYPES = {"mail_archive", "pst", "ost", "msg", "eml", "mbox"}
_DEFAULT_MAX_REQUEST_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class MailUploadHttpSurfaceConfig:
    upload_session_store: UploadSessionRecordStore
    object_store: FileObjectStore
    asset_store: AssetStore
    audit_store: FileAuditLogStore
    storage_backend_id: str
    actor_user_id: str
    session_id: str
    workspace_id: str
    staging_dir: str | Path
    received_at: str | None = None
    max_request_bytes: int = _DEFAULT_MAX_REQUEST_BYTES


@dataclass(frozen=True)
class MailUploadHttpSurfacePostResult:
    status: str
    http_status_code: int
    upload_session_id: str
    receipt: dict[str, Any]
    generated_at: str

    def to_public_dict(self) -> dict[str, Any]:
        payload = {
            "report_type": "mail_upload_http_surface_post",
            "generated_at": self.generated_at,
            "status": self.status,
            "http_status_code": self.http_status_code,
            "upload_session_id": self.upload_session_id,
            "receipt": self.receipt,
            "public_checks": {
                "http_upload_surface_received_multipart": True,
                "upload_session_bound_to_route": True,
                "backend_intake_receipt_validated": True,
                "no_user_infrastructure_controls_exposed": True,
                "staging_file_removed_after_intake": True,
            },
            "safe_outputs": {
                "upload_session_id_hash": sha256_json(self.upload_session_id),
                "receipt_hash": sha256_json(self.receipt),
                "http_status_code": self.http_status_code,
            },
            "claim_boundary": {
                "supports_local_http_upload_surface_contract_claim": True,
                "supports_actual_chatgpt_connected_upload_claim": False,
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
        validation = validate_mail_upload_http_post_result(payload)
        payload["validation"] = validation
        return payload


def build_mail_upload_http_surface_handler(
    config: MailUploadHttpSurfaceConfig,
) -> type[BaseHTTPRequestHandler]:
    """Build a stdlib HTTP handler for local upload-surface contract tests."""

    class MailUploadHttpSurfaceHandler(BaseHTTPRequestHandler):
        server_version = "FormOwlMailUploadHTTP/0.1"

        def do_GET(self) -> None:  # noqa: N802
            upload_session_id = _upload_session_id_from_path(self.path)
            if upload_session_id is None:
                self._send_json_error(HTTPStatus.NOT_FOUND, "upload_route_not_found")
                return
            try:
                _validate_get_session(config, upload_session_id)
            except Exception:
                self._send_json_error(
                    HTTPStatus.NOT_FOUND,
                    "upload_session_not_available",
                    upload_session_id=upload_session_id,
                )
                return
            body = render_mail_upload_http_form(
                upload_session_id=upload_session_id,
                workspace_id=config.workspace_id,
            )
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:  # noqa: N802
            upload_session_id = _upload_session_id_from_path(self.path)
            if upload_session_id is None:
                self._send_json_error(HTTPStatus.NOT_FOUND, "upload_route_not_found")
                return
            try:
                content_length = _validated_content_length(self.headers, config)
                body = _read_request_body(self.rfile, content_length)
                result = receive_mail_archive_http_multipart(
                    self.headers.get("Content-Type", ""),
                    body,
                    upload_session_id=upload_session_id,
                    config=config,
                )
            except _RequestTooLarge:
                self._send_json_error(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "upload_request_too_large",
                    upload_session_id=upload_session_id,
                )
                return
            except Exception:
                self._send_json_error(
                    HTTPStatus.BAD_REQUEST,
                    "upload_request_rejected",
                    upload_session_id=upload_session_id,
                )
                return
            self._send_json(HTTPStatus.CREATED, result.to_public_dict())

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json_error(
            self,
            status_code: HTTPStatus,
            error_code: str,
            *,
            upload_session_id: str | None = None,
        ) -> None:
            self._send_json(
                status_code,
                mail_upload_http_error_payload(
                    status_code=status_code,
                    error_code=error_code,
                    upload_session_id=upload_session_id,
                ),
            )

        def _send_json(self, status_code: HTTPStatus, payload: Mapping[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return MailUploadHttpSurfaceHandler


def create_mail_upload_http_surface_server(
    host: str,
    port: int,
    config: MailUploadHttpSurfaceConfig,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), build_mail_upload_http_surface_handler(config))


def render_mail_upload_http_form(*, upload_session_id: str, workspace_id: str) -> str:
    _require_safe_path_segment(upload_session_id, "upload_session_id")
    _require_safe_path_segment(workspace_id, "workspace_id")
    escaped_upload_session_id = escape(upload_session_id, quote=True)
    escaped_workspace_id = escape(workspace_id, quote=True)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        '<head><meta charset="utf-8"><title>FormOwl Mail Upload</title></head>\n'
        "<body>\n"
        "<main>\n"
        "<h1>FormOwl Mail Upload</h1>\n"
        f'<form method="post" enctype="multipart/form-data" '
        f'action="/mail/upload/{escaped_upload_session_id}">\n'
        f'<input type="hidden" name="upload_session_id" value="{escaped_upload_session_id}">\n'
        f'<input type="hidden" name="workspace_id" value="{escaped_workspace_id}">\n'
        f'<input type="file" name="{_UPLOAD_FILE_FIELD}" '
        f'accept="{_SUPPORTED_ACCEPT_EXTENSIONS}" required>\n'
        '<input type="text" name="expected_content_hash" inputmode="text" '
        'autocomplete="off">\n'
        '<button type="submit">Upload</button>\n'
        "</form>\n"
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


def receive_mail_archive_http_multipart(
    content_type: str,
    body: bytes,
    *,
    upload_session_id: str,
    config: MailUploadHttpSurfaceConfig,
) -> MailUploadHttpSurfacePostResult:
    _require_safe_path_segment(upload_session_id, "upload_session_id")
    if not isinstance(body, bytes):
        raise ContractValidationError("HTTP upload body must be bytes")
    if len(body) > config.max_request_bytes:
        raise _RequestTooLarge("HTTP upload body exceeds configured maximum")
    fields, uploaded_file = _parse_multipart_form_data(content_type, body)
    _validate_http_form_fields(fields, route_upload_session_id=upload_session_id, config=config)
    if len(uploaded_file.content) > config.max_request_bytes:
        raise _RequestTooLarge("HTTP upload file exceeds configured maximum")
    timestamp = config.received_at or now_iso()
    staged_path = _write_staged_upload_file(
        config.staging_dir,
        upload_session_id=upload_session_id,
        content=uploaded_file.content,
    )
    try:
        receipt = receive_mail_archive_upload(
            staged_path,
            upload_session_id=upload_session_id,
            upload_session_store=config.upload_session_store,
            object_store=config.object_store,
            asset_store=config.asset_store,
            audit_store=config.audit_store,
            storage_backend_id=config.storage_backend_id,
            actor_user_id=config.actor_user_id,
            session_id=config.session_id,
            original_filename=uploaded_file.filename,
            content_type=uploaded_file.content_type,
            expected_content_hash=fields.get("expected_content_hash") or None,
            submitted_fields={
                "upload_session_id": upload_session_id,
                "workspace_id": config.workspace_id,
                "original_filename": uploaded_file.filename,
                "content_type": uploaded_file.content_type,
                **(
                    {"expected_content_hash": fields["expected_content_hash"]}
                    if fields.get("expected_content_hash")
                    else {}
                ),
            },
            received_at=timestamp,
        )
        receipt_payload = receipt.to_public_dict()
        validate_mail_upload_surface_receipt(receipt_payload)
        return MailUploadHttpSurfacePostResult(
            status="uploaded",
            http_status_code=HTTPStatus.CREATED,
            upload_session_id=upload_session_id,
            receipt=receipt_payload,
            generated_at=timestamp,
        )
    finally:
        _remove_staged_upload_file(staged_path, stop_at=Path(config.staging_dir))


def validate_mail_upload_http_post_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    value = dict(payload)
    expected = {
        "report_type",
        "generated_at",
        "status",
        "http_status_code",
        "upload_session_id",
        "receipt",
        "public_checks",
        "safe_outputs",
        "claim_boundary",
    }
    if "validation" in value:
        expected.add("validation")
    _expect_exact_keys(value, expected, "mail_upload_http_surface_post", blockers)
    if value.get("report_type") != "mail_upload_http_surface_post":
        blockers.append("report_type must be mail_upload_http_surface_post")
    if value.get("status") != "uploaded":
        blockers.append("status must be uploaded")
    if value.get("http_status_code") != int(HTTPStatus.CREATED):
        blockers.append("http_status_code must be 201")
    upload_session_id = value.get("upload_session_id")
    if not isinstance(upload_session_id, str) or not upload_session_id:
        blockers.append("upload_session_id must be a non-empty string")
    receipt = _dict_or_empty(value.get("receipt"), "receipt", blockers)
    receipt_validation = validate_mail_upload_surface_receipt(receipt)
    if not receipt_validation["passed"]:
        blockers.append("embedded upload receipt must validate")
    if receipt.get("upload_session_id") != upload_session_id:
        blockers.append("embedded receipt must use the route upload session")
    public_checks = _dict_or_empty(value.get("public_checks"), "public_checks", blockers)
    _expect_exact_keys(
        public_checks,
        {
            "http_upload_surface_received_multipart",
            "upload_session_bound_to_route",
            "backend_intake_receipt_validated",
            "no_user_infrastructure_controls_exposed",
            "staging_file_removed_after_intake",
        },
        "public_checks",
        blockers,
    )
    for key, item in public_checks.items():
        if item is not True:
            blockers.append(f"public check is not true: {key}")
    safe_outputs = _dict_or_empty(value.get("safe_outputs"), "safe_outputs", blockers)
    _expect_exact_keys(
        safe_outputs,
        {"upload_session_id_hash", "receipt_hash", "http_status_code"},
        "safe_outputs",
        blockers,
    )
    for key in ("upload_session_id_hash", "receipt_hash"):
        item = safe_outputs.get(key)
        if not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None:
            blockers.append(f"safe_outputs.{key} must be a sha256 hash")
    if safe_outputs.get("http_status_code") != int(HTTPStatus.CREATED):
        blockers.append("safe_outputs.http_status_code must be 201")
    claim_boundary = _dict_or_empty(value.get("claim_boundary"), "claim_boundary", blockers)
    expected_claims = {
        "supports_local_http_upload_surface_contract_claim": True,
        "supports_actual_chatgpt_connected_upload_claim": False,
        "supports_real_upload_iframe_claim": False,
        "supports_real_pst_parser_claim": False,
        "supports_live_postgresql_readiness_claim": False,
        "supports_production_worker_leasing_claim": False,
        "supports_kg_write_claim": False,
        "supports_wiki_projection_claim": False,
        "supports_production_ready_claim": False,
        "container_verification_required": True,
    }
    _expect_exact_keys(claim_boundary, set(expected_claims), "claim_boundary", blockers)
    for key, expected_value in expected_claims.items():
        if claim_boundary.get(key) is not expected_value:
            blockers.append(f"claim boundary mismatch: {key}")
    if "validation" in value:
        validation = _dict_or_empty(value["validation"], "validation", blockers)
        _expect_exact_keys(
            validation,
            {"passed", "blockers", "claim_boundary"},
            "validation",
            blockers,
        )
        if validation.get("passed") is not True:
            blockers.append("validation.passed must be true")
        if validation.get("blockers") != []:
            blockers.append("validation.blockers must be empty")
        validation_claim_boundary = _dict_or_empty(
            validation.get("claim_boundary"),
            "validation.claim_boundary",
            blockers,
        )
        _expect_exact_keys(
            validation_claim_boundary,
            {
                "supports_local_http_upload_surface_contract_claim",
                "supports_production_ready_claim",
            },
            "validation.claim_boundary",
            blockers,
        )
        if (
            validation_claim_boundary.get("supports_local_http_upload_surface_contract_claim")
            is not True
        ):
            blockers.append("validation local HTTP upload surface claim must be true")
        if validation_claim_boundary.get("supports_production_ready_claim") is not False:
            blockers.append("validation production claim must be false")
    try:
        validate_public_gateway_payload(value)
        assert_public_payload_safe(value, "mail_upload_http_surface_post")
    except Exception:
        blockers.append("mail upload HTTP response leaks raw paths or backend controls")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "claim_boundary": {
            "supports_local_http_upload_surface_contract_claim": not blockers,
            "supports_production_ready_claim": False,
        },
    }


def mail_upload_http_error_payload(
    *,
    status_code: int,
    error_code: str,
    upload_session_id: str | None = None,
) -> dict[str, Any]:
    safe_error_code = _safe_error_code(error_code)
    payload = {
        "report_type": "mail_upload_http_surface_error",
        "status": "error",
        "http_status_code": int(status_code),
        "error_code": safe_error_code,
        "safe_outputs": {
            "upload_session_id_hash": sha256_json(upload_session_id or "unknown"),
            "error_code_hash": sha256_json(safe_error_code),
        },
        "claim_boundary": {
            "supports_local_http_upload_surface_contract_claim": False,
            "supports_actual_chatgpt_connected_upload_claim": False,
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
    validate_public_gateway_payload(payload)
    assert_public_payload_safe(payload, "mail_upload_http_surface_error")
    return payload


@dataclass(frozen=True)
class _UploadedFile:
    filename: str
    content_type: str
    content: bytes


class _RequestTooLarge(Exception):
    pass


def _validate_get_session(
    config: MailUploadHttpSurfaceConfig,
    upload_session_id: str,
) -> None:
    session = config.upload_session_store.get(upload_session_id)
    if session is None:
        raise ContractValidationError("upload session not found")
    if session.actor_user_id != config.actor_user_id:
        raise ContractValidationError("upload session actor mismatch")
    if session.session_id != config.session_id:
        raise ContractValidationError("upload session id mismatch")
    if session.workspace_id != config.workspace_id:
        raise ContractValidationError("upload session workspace mismatch")
    if session.status != "pending" or session.processing_status != "waiting_for_upload":
        raise ContractValidationError("upload session is not waiting for upload")
    if session.ingestion_profile != "mail_archive_phase1":
        raise ContractValidationError("upload session profile mismatch")
    if session.intended_asset_type not in _MAIL_INTENDED_ASSET_TYPES:
        raise ContractValidationError("upload session is not for a mail archive")
    if session.asset_id or session.ingestion_job_id:
        raise ContractValidationError("upload session already has upload side effects")


def _validated_content_length(headers: Any, config: MailUploadHttpSurfaceConfig) -> int:
    raw_lengths = headers.get_all("Content-Length") if hasattr(headers, "get_all") else None
    if raw_lengths is not None and len(raw_lengths) != 1:
        raise ContractValidationError("exactly one Content-Length header is required")
    raw_length = headers.get("Content-Length")
    if raw_length is None:
        raise ContractValidationError("Content-Length is required")
    try:
        content_length = int(raw_length)
    except ValueError as exc:
        raise ContractValidationError("Content-Length must be an integer") from exc
    if content_length < 0:
        raise ContractValidationError("Content-Length must not be negative")
    if content_length > config.max_request_bytes:
        raise _RequestTooLarge("HTTP upload request exceeds configured maximum")
    return content_length


def _read_request_body(stream: Any, expected_length: int) -> bytes:
    body = stream.read(expected_length)
    if not isinstance(body, bytes) or len(body) != expected_length:
        raise ContractValidationError("HTTP upload body ended before Content-Length")
    return body


def _parse_multipart_form_data(
    content_type: str,
    body: bytes,
) -> tuple[dict[str, str], _UploadedFile]:
    boundary = _multipart_boundary(content_type)
    message_bytes = (
        f"Content-Type: multipart/form-data; boundary={boundary}\r\n" "MIME-Version: 1.0\r\n\r\n"
    ).encode("ascii") + body
    message = BytesParser(policy=policy.default).parsebytes(message_bytes)
    if not message.is_multipart():
        raise ContractValidationError("HTTP upload body must be multipart")
    _reject_multipart_defects(message)
    fields: dict[str, str] = {}
    uploaded_file: _UploadedFile | None = None
    for part in message.iter_parts():
        _reject_multipart_defects(part)
        if part.get_content_disposition() != "form-data":
            raise ContractValidationError("multipart part must be form-data")
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str) or not name:
            raise ContractValidationError("multipart part name is required")
        _reject_forbidden_field_name(name)
        if name not in _ALLOWED_MULTIPART_FIELDS:
            raise ContractValidationError("multipart field is not supported")
        filename = part.get_filename()
        content = part.get_payload(decode=True) or b""
        if name == _UPLOAD_FILE_FIELD:
            if uploaded_file is not None:
                raise ContractValidationError("only one mail archive file is allowed")
            if not isinstance(filename, str) or not filename:
                raise ContractValidationError("mail archive filename is required")
            uploaded_file = _UploadedFile(
                filename=filename,
                content_type=part.get_content_type(),
                content=content,
            )
            continue
        if filename:
            raise ContractValidationError("text form fields must not include files")
        if name in fields:
            raise ContractValidationError("duplicate multipart fields are not allowed")
        try:
            fields[name] = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractValidationError("multipart text fields must be utf-8") from exc
    if uploaded_file is None:
        raise ContractValidationError("mail archive file is required")
    return fields, uploaded_file


def _reject_multipart_defects(message: Any) -> None:
    if getattr(message, "defects", None):
        raise ContractValidationError("multipart body is malformed")


def _multipart_boundary(content_type: str) -> str:
    message = Message()
    message["Content-Type"] = content_type
    media_type = message.get_content_type()
    boundary = message.get_param("boundary", header="content-type")
    if media_type != "multipart/form-data" or not isinstance(boundary, str) or not boundary:
        raise ContractValidationError("Content-Type must be multipart/form-data with a boundary")
    if not re.fullmatch(r"[A-Za-z0-9'()+_,./:=?-]{1,70}", boundary):
        raise ContractValidationError("multipart boundary is not supported")
    return boundary


def _validate_http_form_fields(
    fields: Mapping[str, str],
    *,
    route_upload_session_id: str,
    config: MailUploadHttpSurfaceConfig,
) -> None:
    unknown = set(fields) - (_ALLOWED_MULTIPART_FIELDS - {_UPLOAD_FILE_FIELD})
    if unknown:
        raise ContractValidationError("multipart field is not supported")
    if fields.get("upload_session_id") != route_upload_session_id:
        raise ContractValidationError("multipart upload_session_id must match route")
    if fields.get("workspace_id") != config.workspace_id:
        raise ContractValidationError("multipart workspace_id must match session")
    for key, value in fields.items():
        _reject_forbidden_field_name(key)
        if not isinstance(value, str):
            raise ContractValidationError("multipart field value must be a string")
        validate_public_gateway_payload(value)
        assert_public_payload_safe(value, f"multipart.{key}")


def _write_staged_upload_file(
    staging_dir: str | Path,
    *,
    upload_session_id: str,
    content: bytes,
) -> Path:
    root = Path(staging_dir)
    _require_safe_path_segment(upload_session_id, "upload_session_id")
    target_dir = root / upload_session_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "upload-body.bin"
    target.write_bytes(content)
    return target


def _remove_staged_upload_file(path: Path, *, stop_at: Path) -> None:
    path.unlink(missing_ok=True)
    current = path.parent
    stop = stop_at.resolve()
    while current.exists() and current.resolve().is_relative_to(stop):
        if current.resolve() == stop:
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _upload_session_id_from_path(path: str) -> str | None:
    parsed = urlparse(path)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    if len(segments) != 3 or tuple(segments[:2]) != _UPLOAD_PATH_PREFIX:
        return None
    upload_session_id = segments[2]
    if _SAFE_PATH_SEGMENT.fullmatch(upload_session_id) is None:
        return None
    return upload_session_id


def _require_safe_path_segment(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _SAFE_PATH_SEGMENT.fullmatch(value) is None:
        raise ContractValidationError(f"{field_name} must be a safe path segment")


def _reject_forbidden_field_name(value: str) -> None:
    normalized = _normalize_field_name(value)
    if set(normalized.split("_")) & _FORBIDDEN_FORM_FIELD_PARTS:
        raise ContractValidationError("mail upload HTTP form must not expose infrastructure")


def _normalize_field_name(value: str) -> str:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.strip())
    return re.sub(r"[^a-z0-9]+", "_", camel_split.lower()).strip("_")


def _safe_error_code(value: str) -> str:
    normalized = _normalize_field_name(value)
    if not normalized:
        return "upload_request_rejected"
    return normalized[:80]


def _dict_or_empty(value: Any, context: str, blockers: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        blockers.append(f"{context} must be an object")
        return {}
    return value


def _expect_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    context: str,
    blockers: list[str],
) -> None:
    extra = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if extra:
        blockers.append(f"{context} contains unknown keys: {sha256_json(extra)}")
    if missing:
        blockers.append(f"{context} missing keys: {sha256_json(missing)}")


__all__ = [
    "MailUploadHttpSurfaceConfig",
    "MailUploadHttpSurfacePostResult",
    "build_mail_upload_http_surface_handler",
    "create_mail_upload_http_surface_server",
    "mail_upload_http_error_payload",
    "receive_mail_archive_http_multipart",
    "render_mail_upload_http_form",
    "validate_mail_upload_http_post_result",
]
