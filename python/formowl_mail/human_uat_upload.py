from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
from typing import Iterable

from formowl_contract import (
    Asset,
    ContractValidationError,
    PermissionScope,
    now_iso,
    sha256_json,
)
from formowl_ingestion.extraction import ExtractionInput
from formowl_ingestion.extractors.mail import PstMailArchiveExtractor

from ._guards import assert_authorized_evidence_payload_safe
from .bundle import (
    EmailBodySegment,
    EmailMessage as MailEvidenceMessage,
    MailEvidenceBundle,
    MailImportSession,
    MailParseRun,
    build_mail_evidence_bundle,
)
from .query import _redact_mail_public_text

_UPLOAD_FIELD = "mail_files"
_UPLOAD_IMPORT_SESSION_ID = "mailimport_may_human_uat_uploads"
_BOUNDARY_RE = re.compile(r"^[A-Za-z0-9'()+_,./:=?-]{1,70}$")
_CONTENT_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_STORED_FILE_RE = re.compile(r"^(?P<digest>[0-9a-f]{64})\.(?P<format>eml|pdf|pst|txt)$")
_SUPPORTED_FORMATS = frozenset({"eml", "pdf", "pst", "txt"})
_STANDARD_FILE_MAX_BYTES = 25 * 1024 * 1024
_MAX_BODY_CHARS = 48_000
_BODY_SEGMENT_CHARS = 4_000
_MAX_BODY_SEGMENTS = 12
_MAX_DOCUMENT_CHARS = 1_000_000
_MAX_DOCUMENT_SEGMENTS = 250
_PST_TIMEOUT_SECONDS = 30 * 60
_PDF_TIMEOUT_SECONDS = 3 * 60


@dataclass(frozen=True)
class UatUploadedResourcePart:
    filename: str
    content: bytes

    @property
    def source_format(self) -> str:
        return _source_format_from_filename(self.filename)


@dataclass(frozen=True)
class StoredUatResource:
    content_hash: str
    source_format: str
    path: Path


@dataclass(frozen=True)
class ParsedUatResourceUpload:
    content_hash: str
    source_format: str
    bundles: tuple[MailEvidenceBundle, ...]
    warnings: tuple[str, ...]

    @property
    def message_count(self) -> int:
        return sum(len(bundle.messages) for bundle in self.bundles)


@dataclass(frozen=True)
class ParsedUatMailUpload:
    content_hash: str
    bundle: MailEvidenceBundle
    warnings: tuple[str, ...]


class UatUploadRequestTooLarge(ContractValidationError):
    pass


class PrivateUatMailUploadStore:
    """Private persistent storage for temporary human-UAT source uploads."""

    def __init__(self, state_dir: str | Path, *, max_file_bytes: int) -> None:
        root = Path(state_dir)
        if root.is_symlink():
            raise ContractValidationError("UAT state directory must not be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        self.root = root / "mail-human-uat-uploads.private"
        if self.root.is_symlink():
            raise ContractValidationError("UAT upload directory must not be a symlink")
        self.root.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.max_file_bytes = max_file_bytes

    def load(self) -> list[StoredUatResource]:
        loaded: list[StoredUatResource] = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            match = _STORED_FILE_RE.fullmatch(path.name)
            if path.is_symlink() or not path.is_file() or match is None:
                raise ContractValidationError("UAT upload store contains an invalid entry")
            size = path.stat().st_size
            if size <= 0 or size > self.max_file_bytes:
                raise ContractValidationError("UAT upload store contains an invalid file")
            digest = _sha256_path(path)
            if digest != match.group("digest"):
                raise ContractValidationError("UAT upload store content hash does not match")
            loaded.append(
                StoredUatResource(
                    content_hash=f"sha256:{digest}",
                    source_format=match.group("format"),
                    path=path,
                )
            )
        return loaded

    def store(self, content_hash: str, source_format: str, content: bytes) -> bool:
        digest = _content_hash_digest(content_hash)
        resolved_format = _validated_source_format(source_format)
        final_path = self.root / f"{digest}.{resolved_format}"
        if final_path.exists():
            if final_path.is_symlink() or not final_path.is_file():
                raise ContractValidationError("UAT upload target is invalid")
            if hashlib.sha256(final_path.read_bytes()).hexdigest() != digest:
                raise ContractValidationError("UAT upload target content hash does not match")
            return False

        temp_path = self.root / f".{digest}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temp_path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(content)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("private UAT upload write failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
        except Exception:
            os.close(descriptor)
            temp_path.unlink(missing_ok=True)
            raise
        else:
            os.close(descriptor)
        try:
            os.replace(temp_path, final_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return True

    def remove(self, content_hash: str, source_format: str) -> None:
        digest = _content_hash_digest(content_hash)
        resolved_format = _validated_source_format(source_format)
        path = self.root / f"{digest}.{resolved_format}"
        if path.is_symlink():
            raise ContractValidationError("UAT upload target is invalid")
        path.unlink(missing_ok=True)


def parse_uat_resource_multipart(
    content_type: str,
    body: bytes,
    *,
    max_files: int,
    max_file_bytes: int,
) -> list[UatUploadedResourcePart]:
    if not isinstance(body, bytes):
        raise ContractValidationError("UAT upload body must be bytes")
    boundary = _multipart_boundary(content_type)
    message_bytes = (
        f"Content-Type: multipart/form-data; boundary={boundary}\r\n" "MIME-Version: 1.0\r\n\r\n"
    ).encode("ascii") + body
    multipart = BytesParser(policy=policy.default).parsebytes(message_bytes)
    if not multipart.is_multipart() or multipart.defects:
        raise ContractValidationError("UAT upload body must be valid multipart data")

    files: list[UatUploadedResourcePart] = []
    for part in multipart.iter_parts():
        if part.defects or part.get_content_disposition() != "form-data":
            raise ContractValidationError("UAT upload multipart part is invalid")
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        if name != _UPLOAD_FIELD or not isinstance(filename, str) or not filename:
            raise ContractValidationError("UAT upload accepts mail_files only")
        if len(files) >= max_files:
            raise ContractValidationError("UAT upload contains too many files")
        safe_filename = _validated_resource_filename(filename)
        source_format = _source_format_from_filename(safe_filename)
        content = part.get_payload(decode=True)
        if content is None and part.get_content_type() == "message/rfc822":
            nested_payload = part.get_payload()
            if (
                isinstance(nested_payload, list)
                and len(nested_payload) == 1
                and isinstance(nested_payload[0], Message)
            ):
                content = nested_payload[0].as_bytes(policy=policy.default)
        if not isinstance(content, bytes):
            raise ContractValidationError("UAT upload file content is invalid")
        size_limit = (
            max_file_bytes
            if source_format == "pst"
            else min(max_file_bytes, _STANDARD_FILE_MAX_BYTES)
        )
        if not content or len(content) > size_limit:
            raise UatUploadRequestTooLarge("UAT upload file size is invalid")
        files.append(UatUploadedResourcePart(filename=safe_filename, content=content))
    if not files:
        raise ContractValidationError("UAT upload requires at least one supported file")
    return files


def parse_uat_uploaded_resource(
    uploaded: UatUploadedResourcePart,
    *,
    owner_user_id: str,
    workspace_id: str,
    created_at: str | None = None,
    scratch_parent: str | Path | None = None,
) -> ParsedUatResourceUpload:
    source_format = uploaded.source_format
    resolved_created_at = created_at or now_iso()
    content_hash = f"sha256:{hashlib.sha256(uploaded.content).hexdigest()}"
    if source_format == "eml":
        parsed = parse_uat_uploaded_eml(
            uploaded.content,
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            created_at=resolved_created_at,
        )
        return ParsedUatResourceUpload(
            content_hash=parsed.content_hash,
            source_format="eml",
            bundles=(parsed.bundle,),
            warnings=parsed.warnings,
        )
    if source_format == "txt":
        text = _decode_uploaded_text(uploaded.content)
        return _parsed_document_upload(
            text,
            content_hash=content_hash,
            source_format=source_format,
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            created_at=resolved_created_at,
        )

    with _temporary_uploaded_path(
        uploaded.content,
        source_format=source_format,
        scratch_parent=scratch_parent,
    ) as source_path:
        return _parse_path_resource(
            source_path,
            content_hash=content_hash,
            source_format=source_format,
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            created_at=resolved_created_at,
            scratch_parent=scratch_parent,
        )


def parse_uat_stored_resource(
    stored: StoredUatResource,
    *,
    owner_user_id: str,
    workspace_id: str,
    created_at: str | None = None,
    scratch_parent: str | Path | None = None,
) -> ParsedUatResourceUpload:
    resolved_created_at = created_at or now_iso()
    if stored.source_format == "eml":
        parsed = parse_uat_uploaded_eml(
            stored.path.read_bytes(),
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            created_at=resolved_created_at,
        )
        return ParsedUatResourceUpload(
            content_hash=parsed.content_hash,
            source_format="eml",
            bundles=(parsed.bundle,),
            warnings=parsed.warnings,
        )
    if stored.source_format == "txt":
        return _parsed_document_upload(
            _decode_uploaded_text(stored.path.read_bytes()),
            content_hash=stored.content_hash,
            source_format="txt",
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            created_at=resolved_created_at,
        )
    return _parse_path_resource(
        stored.path,
        content_hash=stored.content_hash,
        source_format=stored.source_format,
        owner_user_id=owner_user_id,
        workspace_id=workspace_id,
        created_at=resolved_created_at,
        scratch_parent=scratch_parent,
    )


def _parse_path_resource(
    source_path: Path,
    *,
    content_hash: str,
    source_format: str,
    owner_user_id: str,
    workspace_id: str,
    created_at: str,
    scratch_parent: str | Path | None,
) -> ParsedUatResourceUpload:
    if source_format == "pdf":
        text = _extract_pdf_text(source_path)
        return _parsed_document_upload(
            text,
            content_hash=content_hash,
            source_format="pdf",
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            created_at=created_at,
        )
    if source_format == "pst":
        return _parse_uat_uploaded_pst(
            source_path,
            content_hash=content_hash,
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            created_at=created_at,
            scratch_parent=scratch_parent,
        )
    raise ContractValidationError("UAT upload source format is invalid")


def _parse_uat_uploaded_pst(
    source_path: Path,
    *,
    content_hash: str,
    owner_user_id: str,
    workspace_id: str,
    created_at: str,
    scratch_parent: str | Path | None,
) -> ParsedUatResourceUpload:
    suffix = _content_hash_digest(content_hash)[:24]
    asset = Asset(
        asset_id=f"asset_uat_{suffix}",
        storage_backend_id="storage_uat_private",
        object_uri=f"object://mail-human-uat/{suffix}.pst",
        content_hash=content_hash,
        file_size=source_path.stat().st_size,
        mime_type="application/vnd.ms-outlook",
        created_at=created_at,
        registered_at=created_at,
        owner_user_id=owner_user_id,
        workspace_id=workspace_id,
        permission_scope=PermissionScope.project("project_human_uat"),
        lifecycle_state="active",
    )
    adapter = PstMailArchiveExtractor(
        scratch_parent=Path(scratch_parent) if scratch_parent is not None else None,
    )
    result = adapter.extract(
        ExtractionInput(
            asset=asset,
            object_path=source_path,
            extractor_run_id=f"extractorrun_uat_{suffix}",
            config={
                "timeout_seconds": _PST_TIMEOUT_SECONDS,
                "body_segment_max_chars": _BODY_SEGMENT_CHARS,
                "max_body_segments_per_message": _MAX_BODY_SEGMENTS,
                "parser_workers": 1,
            },
            created_at=created_at,
        )
    )
    if result.errors or not result.observations:
        raise ContractValidationError("uploaded PST could not be parsed")
    bundle = build_mail_evidence_bundle(
        result.observations,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        source_asset_id=asset.asset_id,
        archive_sha256=content_hash,
        upload_session_id=f"upload_uat_{suffix}",
        parser_name=adapter.name(),
        parser_version=adapter.version(),
        created_at=created_at,
        started_at=created_at,
        completed_at=created_at,
        retention_policy="retain_30_days",
        parse_warnings=result.warnings,
    )
    assert_authorized_evidence_payload_safe(
        bundle.to_dict(),
        "mail_human_uat_uploaded_pst_bundle",
    )
    return ParsedUatResourceUpload(
        content_hash=content_hash,
        source_format="pst",
        bundles=(bundle,),
        warnings=tuple(sorted(set(result.warnings))),
    )


def _parsed_document_upload(
    text: str,
    *,
    content_hash: str,
    source_format: str,
    owner_user_id: str,
    workspace_id: str,
    created_at: str,
) -> ParsedUatResourceUpload:
    warnings: list[str] = []
    if len(text) > _MAX_DOCUMENT_CHARS:
        text = text[:_MAX_DOCUMENT_CHARS]
        warnings.append(f"uat_{source_format}_text_truncated")
    safe_text = _safe_mail_text(text)
    if not safe_text:
        raise ContractValidationError("uploaded reference file has no searchable text")
    suffix = _content_hash_digest(content_hash)[:24]
    title = _document_title(safe_text, source_format)
    body_segments: list[EmailBodySegment] = []
    for index, segment in enumerate(_document_body_segments(safe_text), start=1):
        observation_id = f"obs_uat_{suffix}_{source_format}_{index}"
        body_segments.append(
            EmailBodySegment(
                email_body_segment_id=f"emailbody_uat_{suffix}_{index}",
                email_message_id=f"emailmessage_uat_{suffix}",
                message_occurrence_id=f"resourceocc_uat_{suffix}",
                source_observation_id=observation_id,
                text=segment,
                body_segment_hash=sha256_json(segment),
                body_segment_index=index,
            )
        )
    if not body_segments:
        raise ContractValidationError("uploaded reference file has no searchable text")

    import_session = MailImportSession(
        mail_import_session_id=f"mailimport_uat_{suffix}",
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        source_asset_id=f"asset_uat_{suffix}",
        archive_sha256=content_hash,
        retention_policy="retain_30_days",
        raw_archive_retention_decision="retained_by_policy",
        created_at=created_at,
        upload_session_id=f"upload_uat_{suffix}",
        import_profile=f"human_uat_{source_format}_reference",
    )
    evidence_message = MailEvidenceMessage(
        email_message_id=f"emailmessage_uat_{suffix}",
        message_fingerprint=content_hash,
        message_id=f"resource_uat_{suffix}",
        archive_id=f"resourcearchive_uat_{suffix}",
        mailbox_id="mailbox_shared_human_uat",
        source_observation_ids=[segment.source_observation_id for segment in body_segments],
        subject=title,
        normalized_subject=title.casefold(),
        sent_at=created_at,
        body_hash=sha256_json(safe_text),
        thread_id=f"resourcethread_uat_{suffix}",
    )
    parser_name = "pdftotext" if source_format == "pdf" else "python_text_decoder"
    parse_run = MailParseRun(
        mail_parse_run_id=f"mailparserun_uat_{suffix}",
        mail_import_session_id=import_session.mail_import_session_id,
        extractor_run_id=f"extractorrun_uat_{suffix}",
        parser_name=parser_name,
        parser_version="0.1.0",
        input_hash=content_hash,
        config_hash=sha256_json(
            {
                "max_document_chars": _MAX_DOCUMENT_CHARS,
                "body_segment_chars": _BODY_SEGMENT_CHARS,
                "max_document_segments": _MAX_DOCUMENT_SEGMENTS,
            }
        ),
        status="succeeded",
        started_at=created_at,
        completed_at=created_at,
    )
    bundle = MailEvidenceBundle(
        mail_evidence_bundle_id=f"mailevidencebundle_uat_{suffix}",
        producer_type="server_side_parser",
        mail_import_session=import_session,
        archive_occurrences=[],
        folder_occurrences=[],
        messages=[evidence_message],
        message_occurrences=[],
        body_segments=body_segments,
        attachments=[],
        attachment_occurrences=[],
        quoted_message_candidates=[],
        embedded_message_relations=[],
        mail_parse_run=parse_run,
        parse_warnings=[],
        created_at=created_at,
    )
    assert_authorized_evidence_payload_safe(
        bundle.to_dict(),
        "mail_human_uat_uploaded_reference_bundle",
    )
    return ParsedUatResourceUpload(
        content_hash=content_hash,
        source_format=source_format,
        bundles=(bundle,),
        warnings=tuple(warnings),
    )


def parse_uat_uploaded_eml(
    content: bytes,
    *,
    owner_user_id: str,
    workspace_id: str,
    created_at: str | None = None,
) -> ParsedUatMailUpload:
    if not isinstance(content, bytes) or not content:
        raise ContractValidationError("uploaded EML content is required")
    resolved_created_at = created_at or now_iso()
    digest = hashlib.sha256(content).hexdigest()
    content_hash = f"sha256:{digest}"
    suffix = digest[:24]
    try:
        message = BytesParser(policy=policy.default).parsebytes(content)
    except Exception as exc:
        raise ContractValidationError("uploaded EML could not be parsed") from exc
    if not _looks_like_mail_message(message):
        raise ContractValidationError("uploaded EML is not a supported mail message")

    warnings: list[str] = []
    if message.defects:
        warnings.append("uat_eml_parser_defects")
    subject = _safe_mail_text(str(message.get("subject") or "").strip())
    sender = _safe_mail_text(str(message.get("from") or "").strip())
    sent_at = _mail_sent_at(str(message.get("date") or "").strip(), warnings=warnings)
    body = _mail_body(message)
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS]
        warnings.append("uat_eml_body_truncated")
    safe_body = _safe_mail_text(body)
    if not safe_body:
        safe_body = subject
    if not safe_body:
        raise ContractValidationError("uploaded EML has no searchable subject or body")
    if _attachment_count(message):
        warnings.append("uat_eml_attachments_not_indexed")

    email_message_id = f"emailmessage_uat_{suffix}"
    message_occurrence_id = f"mailocc_uat_{suffix}"
    body_segments: list[EmailBodySegment] = []
    for index, segment in enumerate(_body_segments(safe_body), start=1):
        observation_id = f"obs_uat_{suffix}_body_{index}"
        body_segments.append(
            EmailBodySegment(
                email_body_segment_id=f"emailbody_uat_{suffix}_{index}",
                email_message_id=email_message_id,
                message_occurrence_id=message_occurrence_id,
                source_observation_id=observation_id,
                text=segment,
                body_segment_hash=sha256_json(segment),
                body_segment_index=index,
            )
        )

    import_session = MailImportSession(
        mail_import_session_id=_UPLOAD_IMPORT_SESSION_ID,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        source_asset_id=f"asset_uat_{suffix}",
        archive_sha256=content_hash,
        retention_policy="retain_30_days",
        raw_archive_retention_decision="retained_by_policy",
        created_at=resolved_created_at,
        upload_session_id=f"upload_uat_{suffix}",
        import_profile="mail_human_uat_eml",
    )
    evidence_message = MailEvidenceMessage(
        email_message_id=email_message_id,
        message_fingerprint=content_hash,
        message_id=f"message_uat_{suffix}",
        archive_id=f"mailarchive_uat_{suffix}",
        mailbox_id="mailbox_may_human_uat",
        source_observation_ids=[segment.source_observation_id for segment in body_segments],
        subject=subject or None,
        normalized_subject=_normalized_subject(subject) or None,
        sender=sender or None,
        sent_at=sent_at or None,
        body_hash=sha256_json(safe_body),
        thread_id=f"mailthread_uat_{sha256_json(_normalized_subject(subject) or suffix)[-24:]}",
    )
    parse_run = MailParseRun(
        mail_parse_run_id=f"mailparserun_uat_{suffix}",
        mail_import_session_id=_UPLOAD_IMPORT_SESSION_ID,
        extractor_run_id=f"extractorrun_uat_{suffix}",
        parser_name="python_stdlib_eml",
        parser_version="0.1.0",
        input_hash=content_hash,
        config_hash=sha256_json(
            {
                "max_body_chars": _MAX_BODY_CHARS,
                "body_segment_chars": _BODY_SEGMENT_CHARS,
                "max_body_segments": _MAX_BODY_SEGMENTS,
                "attachments_indexed": False,
            }
        ),
        status="succeeded",
        started_at=resolved_created_at,
        completed_at=resolved_created_at,
    )
    bundle = MailEvidenceBundle(
        mail_evidence_bundle_id=f"mailevidencebundle_uat_{suffix}",
        producer_type="server_side_parser",
        mail_import_session=import_session,
        archive_occurrences=[],
        folder_occurrences=[],
        messages=[evidence_message],
        message_occurrences=[],
        body_segments=body_segments,
        attachments=[],
        attachment_occurrences=[],
        quoted_message_candidates=[],
        embedded_message_relations=[],
        mail_parse_run=parse_run,
        parse_warnings=[],
        created_at=resolved_created_at,
    )
    assert_authorized_evidence_payload_safe(
        bundle.to_dict(),
        "mail_human_uat_uploaded_bundle",
    )
    return ParsedUatMailUpload(
        content_hash=content_hash,
        bundle=bundle,
        warnings=tuple(sorted(set(warnings))),
    )


def upload_import_session_id() -> str:
    return _UPLOAD_IMPORT_SESSION_ID


def _multipart_boundary(content_type: str) -> str:
    message = Message()
    message["Content-Type"] = content_type
    boundary = message.get_param("boundary", header="content-type")
    if (
        message.get_content_type() != "multipart/form-data"
        or not isinstance(boundary, str)
        or not _BOUNDARY_RE.fullmatch(boundary)
    ):
        raise ContractValidationError(
            "UAT upload Content-Type must be multipart/form-data with a boundary"
        )
    return boundary


def _validated_resource_filename(value: str) -> str:
    if "\x00" in value or "/" in value or "\\" in value:
        raise ContractValidationError("UAT upload filename is invalid")
    filename = Path(value).name
    _source_format_from_filename(filename)
    if len(filename) > 255:
        raise ContractValidationError("UAT upload filename is too long")
    return filename


def _source_format_from_filename(value: str) -> str:
    source_format = Path(value).suffix.lower().removeprefix(".")
    return _validated_source_format(source_format)


def _validated_source_format(value: str) -> str:
    if not isinstance(value, str) or value not in _SUPPORTED_FORMATS:
        raise ContractValidationError("UAT upload file type is not supported")
    return value


@contextmanager
def _temporary_uploaded_path(
    content: bytes,
    *,
    source_format: str,
    scratch_parent: str | Path | None,
):
    resolved_format = _validated_source_format(source_format)
    parent = Path(scratch_parent) if scratch_parent is not None else None
    if parent is not None:
        if parent.is_symlink():
            raise ContractValidationError("UAT upload scratch directory is invalid")
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(parent, 0o700)
    with tempfile.TemporaryDirectory(
        prefix="formowl-uat-resource-",
        dir=str(parent) if parent is not None else None,
    ) as temporary_root:
        temporary_path = Path(temporary_root)
        if os.name != "nt":
            temporary_path.chmod(0o700)
        source_path = temporary_path / f"payload.{resolved_format}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(source_path, flags, 0o600)
        try:
            remaining = memoryview(content)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("temporary UAT upload write failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        yield source_path


def _extract_pdf_text(source_path: Path) -> str:
    try:
        with source_path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ContractValidationError("uploaded PDF signature is invalid")
        completed = subprocess.run(
            [
                "pdftotext",
                "-layout",
                "-enc",
                "UTF-8",
                str(source_path),
                "-",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_PDF_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise ContractValidationError("PDF text extraction is unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise ContractValidationError("uploaded PDF text extraction timed out") from exc
    except OSError as exc:
        raise ContractValidationError("uploaded PDF could not be read") from exc
    if completed.returncode != 0:
        raise ContractValidationError("uploaded PDF could not be parsed")
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        raise ContractValidationError("uploaded PDF has no extractable text")
    return text


def _decode_uploaded_text(content: bytes) -> str:
    if not content:
        raise ContractValidationError("uploaded TXT content is required")
    encodings = ["utf-8-sig", "utf-16", "cp950"]
    for encoding in encodings:
        try:
            decoded = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in decoded:
            continue
        if decoded.strip():
            return decoded
    raise ContractValidationError("uploaded TXT encoding is not supported")


def _document_title(text: str, source_format: str) -> str:
    label = "PDF 參考資料" if source_format == "pdf" else "TXT 參考資料"
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return label
    first_line = re.sub(r"\s+", " ", first_line)[:120].strip()
    return f"{label}｜{first_line}" if first_line else label


def _document_body_segments(value: str) -> list[str]:
    paragraphs = [
        item.strip()
        for item in re.split(r"\n\s*\n", value.replace("\r\n", "\n").replace("\r", "\n"))
        if item.strip()
    ]
    if not paragraphs:
        paragraphs = [value.strip()]
    segments: list[str] = []
    for paragraph in paragraphs:
        for start in range(0, len(paragraph), _BODY_SEGMENT_CHARS):
            chunk = paragraph[start : start + _BODY_SEGMENT_CHARS].strip()
            if chunk:
                segments.append(chunk)
            if len(segments) >= _MAX_DOCUMENT_SEGMENTS:
                return segments
    return segments


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_like_mail_message(message: EmailMessage) -> bool:
    return any(
        message.get(header_name) is not None
        for header_name in ("subject", "from", "to", "date", "message-id")
    )


def _mail_sent_at(value: str, *, warnings: list[str]) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        warnings.append("uat_eml_date_not_normalized")
        return ""
    if parsed.tzinfo is None:
        warnings.append("uat_eml_date_timezone_missing")
    return parsed.isoformat()


def _mail_body(message: EmailMessage) -> str:
    plain: list[str] = []
    html: list[str] = []
    for part in _iter_indexable_body_parts(message):
        try:
            content = part.get_content()
        except Exception:
            continue
        if not isinstance(content, str):
            continue
        if part.get_content_type() == "text/plain":
            plain.append(content)
        elif part.get_content_type() == "text/html":
            html.append(_html_to_text(content))
    selected = plain if any(item.strip() for item in plain) else html
    return "\n\n".join(item.strip() for item in selected if item.strip())


def _attachment_count(message: EmailMessage) -> int:
    def visit(part: Message, *, root: bool = False) -> int:
        if not root and _is_attachment_part(part):
            return 1
        payload = part.get_payload()
        if not part.is_multipart() or not isinstance(payload, list):
            return 0
        return sum(visit(child) for child in payload if isinstance(child, Message))

    return visit(message, root=True)


def _iter_indexable_body_parts(message: Message) -> Iterable[Message]:
    if _is_attachment_part(message):
        return
    payload = message.get_payload()
    if message.is_multipart() and isinstance(payload, list):
        for child in payload:
            if isinstance(child, Message):
                yield from _iter_indexable_body_parts(child)
        return
    yield message


def _is_attachment_part(part: Message) -> bool:
    return (
        part.get_content_disposition() == "attachment"
        or part.get_filename() is not None
        or part.get_content_type() == "message/rfc822"
    )


def _body_segments(value: str) -> list[str]:
    paragraphs = [
        item.strip()
        for item in re.split(r"\n\s*\n", value.replace("\r\n", "\n").replace("\r", "\n"))
        if item.strip()
    ]
    if not paragraphs:
        paragraphs = [value.strip()]
    segments: list[str] = []
    for paragraph in paragraphs:
        for start in range(0, len(paragraph), _BODY_SEGMENT_CHARS):
            chunk = paragraph[start : start + _BODY_SEGMENT_CHARS].strip()
            if chunk:
                segments.append(chunk)
            if len(segments) >= _MAX_BODY_SEGMENTS:
                return segments
    return segments


def _safe_mail_text(value: str) -> str:
    redacted, _ = _redact_mail_public_text(value)
    return redacted.strip()


def _normalized_subject(value: str) -> str:
    normalized = value.strip()
    while True:
        updated = re.sub(r"^(?:re|fw|fwd)\s*:\s*", "", normalized, flags=re.IGNORECASE)
        if updated == normalized:
            return normalized.casefold()
        normalized = updated.strip()


def _content_hash_digest(content_hash: str) -> str:
    if not isinstance(content_hash, str) or not _CONTENT_HASH_RE.fullmatch(content_hash):
        raise ContractValidationError("UAT upload content hash is invalid")
    return content_hash.split(":", 1)[1]


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        lowered = tag.casefold()
        if lowered in {"script", "style"}:
            self._ignored_depth += 1
        elif not self._ignored_depth and lowered in {"br", "div", "li", "p", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and lowered in {"div", "li", "p", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _html_to_text(value: str) -> str:
    parser = _HtmlTextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return ""
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()


__all__ = [
    "ParsedUatMailUpload",
    "ParsedUatResourceUpload",
    "PrivateUatMailUploadStore",
    "StoredUatResource",
    "UatUploadRequestTooLarge",
    "UatUploadedResourcePart",
    "parse_uat_resource_multipart",
    "parse_uat_stored_resource",
    "parse_uat_uploaded_eml",
    "parse_uat_uploaded_resource",
    "upload_import_session_id",
]
