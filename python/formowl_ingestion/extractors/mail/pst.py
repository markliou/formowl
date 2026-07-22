from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence
import uuid

from formowl_contract import (
    Observation,
    assert_no_public_raw_references,
    now_iso,
    sha256_json,
    stable_observation_id,
    stable_resource_contract_id,
)

from ...extraction import ExtractionInput, ExtractionResult
from .fixture import _normalize_subject

_PST_MIME_TYPES = [
    "application/vnd.ms-outlook",
    "application/vnd.ms-outlook-pst",
    "application/vnd.ms-pst",
    "application/x-pst",
]
_PST_HEADER = b"!BDN"
_SAFE_HEADER_NAMES = {
    "message-id",
    "subject",
    "from",
    "to",
    "cc",
    "date",
    "in-reply-to",
    "references",
}


@dataclass(frozen=True)
class _ParserCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


_ParserRunner = Callable[[Sequence[str], int], _ParserCommandResult]


@dataclass(frozen=True)
class _ParsedAttachment:
    attachment_id: str
    filename: str
    mime_type: str | None = None
    content_hash: str | None = None
    size_bytes: int | None = None
    extracted_text_segments: list[str] = field(default_factory=list)
    text_extraction_state: str = "not_text"


@dataclass(frozen=True)
class _ParsedBodySegment:
    text: str
    char_start: int
    char_end: int
    content_publicly_unsafe: bool = False


@dataclass(frozen=True)
class _ParsedMessage:
    folder_path_hash: str
    folder_label: str
    message_id: str
    subject: str
    normalized_subject: str
    sender: str
    sent_at: str
    headers: dict[str, str]
    body_segments: list[_ParsedBodySegment]
    body_hash: str
    source_body_char_count: int
    stored_body_char_count: int
    body_evidence_state: str
    body_redacted_segment_count: int
    unresolved_attachment_count: int
    attachments: list[_ParsedAttachment]
    references: list[str] = field(default_factory=list)
    in_reply_to: str | None = None


@dataclass(frozen=True)
class _PstParserConfig:
    max_messages: int | None
    timeout_seconds: int
    max_message_file_bytes: int
    body_segment_max_chars: int
    max_body_segments_per_message: int | None
    max_attachment_hash_bytes: int
    max_attachment_text_bytes: int
    preserve_private_body_text: bool
    include_deleted_items: bool
    parser_workers: int


class PstMailArchiveExtractor:
    """Server-side PST adapter that emits FormOwl mail observations.

    The adapter shells out to a configured PST parser command and then parses
    exported RFC822 messages with the Python standard library. Parser paths and
    scratch directories remain internal to the extractor and are never copied
    into observations.
    """

    def __init__(
        self,
        *,
        version: str = "0.2.0",
        parser_command: str = "readpst",
        runner: _ParserRunner | None = None,
        scratch_parent: str | Path | None = None,
    ) -> None:
        self._version = version
        self._parser_command = parser_command
        self._runner = runner or _run_parser_command
        self._scratch_parent = Path(scratch_parent) if scratch_parent is not None else None

    def name(self) -> str:
        return "pst_mail_archive_extractor"

    def version(self) -> str:
        return self._version

    def supported_mime_types(self) -> list[str]:
        return list(_PST_MIME_TYPES)

    def extractor_type(self) -> str:
        return "mail_archive"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        config = _parser_config(extraction_input.config)
        if not _looks_like_pst(extraction_input.object_path):
            return ExtractionResult(errors=["pst_parser_input_signature_mismatch"])

        scratch_path = _create_scratch_dir(self._scratch_parent)
        try:
            command = _readpst_command(
                self._parser_command,
                extraction_input.object_path,
                scratch_path,
                include_deleted_items=config.include_deleted_items,
            )
            try:
                completed = self._runner(command, config.timeout_seconds)
            except FileNotFoundError:
                return ExtractionResult(errors=["pst_parser_unavailable"])
            except subprocess.TimeoutExpired:
                return ExtractionResult(errors=["pst_parser_timeout"])
            if completed.returncode != 0:
                return ExtractionResult(errors=["pst_parser_failed"])

            parsed_messages, parse_warnings = _parse_exported_messages(
                scratch_path,
                config=config,
            )
        finally:
            shutil.rmtree(scratch_path, ignore_errors=True)

        if not parsed_messages:
            return ExtractionResult(
                warnings=parse_warnings,
                errors=["pst_parser_no_messages"],
            )

        observations = _mail_observations_from_messages(
            parsed_messages,
            extraction_input=extraction_input,
        )
        warnings = list(parse_warnings)
        if config.max_messages is not None and len(parsed_messages) >= config.max_messages:
            warnings.append("pst_parser_message_limit_reached")
        return ExtractionResult(observations=observations, warnings=warnings)


def _run_parser_command(command: Sequence[str], timeout_seconds: int) -> _ParserCommandResult:
    completed = subprocess.run(
        list(command),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
    )
    return _ParserCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _create_scratch_dir(scratch_parent: Path | None) -> Path:
    parent = scratch_parent or Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        candidate = parent / f"formowl-pst-export-{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
            if os.name != "nt":
                candidate.chmod(0o700)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("pst parser scratch allocation failed")


def _readpst_command(
    parser_command: str,
    pst_path: Path,
    output_dir: Path,
    *,
    include_deleted_items: bool,
) -> list[str]:
    command = [parser_command, "-S", "-o", str(output_dir)]
    if include_deleted_items:
        command.append("-D")
    command.append(str(pst_path))
    return command


def _looks_like_pst(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == _PST_HEADER
    except OSError:
        return False


def _parser_config(config: Mapping[str, Any]) -> _PstParserConfig:
    return _PstParserConfig(
        max_messages=_optional_positive_int(config.get("max_messages"), "max_messages"),
        timeout_seconds=_positive_int(config.get("timeout_seconds", 900), "timeout_seconds"),
        max_message_file_bytes=_positive_int(
            config.get("max_message_file_bytes", 25 * 1024 * 1024),
            "max_message_file_bytes",
        ),
        body_segment_max_chars=_positive_int(
            config.get("body_segment_max_chars", 4000),
            "body_segment_max_chars",
        ),
        max_body_segments_per_message=_optional_positive_int(
            config.get("max_body_segments_per_message"),
            "max_body_segments_per_message",
        ),
        max_attachment_hash_bytes=_positive_int(
            config.get("max_attachment_hash_bytes", 5 * 1024 * 1024),
            "max_attachment_hash_bytes",
        ),
        max_attachment_text_bytes=_positive_int(
            config.get("max_attachment_text_bytes", 5 * 1024 * 1024),
            "max_attachment_text_bytes",
        ),
        preserve_private_body_text=_bool_config(
            config.get("preserve_private_body_text", True),
            "preserve_private_body_text",
        ),
        include_deleted_items=_bool_config(
            config.get("include_deleted_items", False),
            "include_deleted_items",
        ),
        parser_workers=_positive_int(config.get("parser_workers", 1), "parser_workers"),
    )


def _positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _bool_config(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _parse_exported_messages(
    export_root: Path,
    *,
    config: _PstParserConfig,
) -> tuple[list[_ParsedMessage], list[str]]:
    if config.parser_workers > 1 and config.max_messages is None:
        return _parse_exported_messages_parallel(export_root, config=config)
    parsed: list[_ParsedMessage] = []
    warnings: list[str] = []
    for candidate in _iter_exported_files(export_root):
        if config.max_messages is not None and len(parsed) >= config.max_messages:
            break
        try:
            if candidate.stat().st_size > config.max_message_file_bytes:
                warnings.append("pst_parser_large_message_file_skipped")
                continue
            message = BytesParser(policy=policy.default).parsebytes(candidate.read_bytes())
        except Exception:
            warnings.append("pst_parser_message_file_skipped")
            continue
        if not _is_mail_message(message):
            continue
        parsed_message = _parsed_message_from_email(
            message,
            candidate_path=candidate,
            export_root=export_root,
            message_index=len(parsed) + 1,
            config=config,
            warnings=warnings,
        )
        parsed.append(parsed_message)
    return parsed, warnings


def _parse_exported_messages_parallel(
    export_root: Path,
    *,
    config: _PstParserConfig,
) -> tuple[list[_ParsedMessage], list[str]]:
    candidates = list(_iter_exported_files(export_root))
    parsed: list[_ParsedMessage] = []
    warnings: list[str] = []
    executor_type = ThreadPoolExecutor if os.name == "nt" else ProcessPoolExecutor
    with executor_type(max_workers=config.parser_workers) as executor:
        results = executor.map(
            _parse_exported_message_file_job,
            (
                (candidate, export_root, index + 1, config)
                for index, candidate in enumerate(candidates)
            ),
            chunksize=25,
        )
        for parsed_message, parse_warnings in results:
            warnings.extend(parse_warnings)
            if parsed_message is not None:
                parsed.append(parsed_message)
    return parsed, warnings


def _parse_exported_message_file_job(
    args: tuple[Path, Path, int, _PstParserConfig],
) -> tuple[_ParsedMessage | None, list[str]]:
    candidate, export_root, message_index, config = args
    return _parse_exported_message_file(
        candidate,
        export_root=export_root,
        message_index=message_index,
        config=config,
    )


def _parse_exported_message_file(
    candidate: Path,
    *,
    export_root: Path,
    message_index: int,
    config: _PstParserConfig,
) -> tuple[_ParsedMessage | None, list[str]]:
    warnings: list[str] = []
    try:
        if candidate.stat().st_size > config.max_message_file_bytes:
            return None, ["pst_parser_large_message_file_skipped"]
        message = BytesParser(policy=policy.default).parsebytes(candidate.read_bytes())
    except Exception:
        return None, ["pst_parser_message_file_skipped"]
    if not _is_mail_message(message):
        return None, []
    parsed_message = _parsed_message_from_email(
        message,
        candidate_path=candidate,
        export_root=export_root,
        message_index=message_index,
        config=config,
        warnings=warnings,
    )
    return parsed_message, warnings


def _iter_exported_files(export_root: Path) -> Iterable[Path]:
    stack = [export_root]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in reversed(children):
            if child.is_dir():
                stack.append(child)
            elif child.is_file():
                yield child


def _is_mail_message(message: EmailMessage) -> bool:
    return any(
        message.get(header_name) is not None
        for header_name in ("subject", "from", "to", "date", "message-id")
    )


def _parsed_message_from_email(
    message: EmailMessage,
    *,
    candidate_path: Path,
    export_root: Path,
    message_index: int,
    config: _PstParserConfig,
    warnings: list[str],
) -> _ParsedMessage:
    relative_parent = _safe_relative_parent(candidate_path, export_root)
    folder_label = _folder_label(relative_parent)
    folder_path_hash = sha256_json(str(relative_parent).replace("\\", "/"))
    subject = _safe_mail_text(message.get("subject") or "", "subject")
    sender = _safe_mail_text(message.get("from") or "", "sender")
    sent_at = _safe_date(message.get("date") or "")
    raw_body = _plain_body(message)
    body_hash = sha256_json(raw_body)
    body_segments, body_evidence_state, body_redacted_segment_count = _safe_body_segments(
        raw_body,
        max_chars=config.body_segment_max_chars,
        max_segments=config.max_body_segments_per_message,
        preserve_private_text=config.preserve_private_body_text,
        warnings=warnings,
    )
    normalized_subject = _normalize_subject(subject)
    message_id = _message_id(
        message,
        fallback_parts=(
            folder_path_hash,
            normalized_subject,
            sender,
            sent_at,
            body_hash,
        ),
    )
    headers = _safe_headers(message, warnings=warnings)
    references = _safe_header_tokens(message.get("references") or "", "references")
    in_reply_to = _safe_optional_header(message.get("in-reply-to"), "in_reply_to")
    attachments = _attachments(message, config=config, warnings=warnings)
    unresolved_attachment_count = sum(
        attachment.text_extraction_state in {"unsupported", "failed", "too_large"}
        for attachment in attachments
    )
    return _ParsedMessage(
        folder_path_hash=folder_path_hash,
        folder_label=folder_label,
        message_id=message_id,
        subject=subject,
        normalized_subject=normalized_subject,
        sender=sender,
        sent_at=sent_at,
        headers=headers,
        body_segments=body_segments,
        body_hash=body_hash,
        source_body_char_count=len(raw_body),
        stored_body_char_count=sum(len(segment.text) for segment in body_segments),
        body_evidence_state=body_evidence_state,
        body_redacted_segment_count=body_redacted_segment_count,
        unresolved_attachment_count=unresolved_attachment_count,
        attachments=attachments,
        references=references,
        in_reply_to=in_reply_to,
    )


def _safe_relative_parent(candidate_path: Path, export_root: Path) -> Path:
    try:
        relative = candidate_path.parent.relative_to(export_root)
    except ValueError:
        return Path("mailbox")
    return relative if str(relative) not in {"", "."} else Path("mailbox")


def _folder_label(relative_parent: Path) -> str:
    label = " / ".join(part for part in relative_parent.parts if part not in {"", "."})
    return _safe_mail_text(label or "Mailbox", "folder_label")


def _message_id(message: EmailMessage, *, fallback_parts: tuple[Any, ...]) -> str:
    value = str(message.get("message-id") or "").strip()
    if value:
        return _safe_mail_text(value, "message_id")
    return stable_resource_contract_id("mailmsg", "PstMessage", {"fallback": fallback_parts})


def _safe_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return _safe_mail_text(text, "date")
    return parsed.isoformat()


def _safe_headers(message: EmailMessage, *, warnings: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in message.items():
        header_name = str(name).strip().lower()
        if header_name not in _SAFE_HEADER_NAMES:
            continue
        safe_name = _safe_header_name(header_name)
        try:
            headers[safe_name] = _safe_mail_text(str(value), f"header_{safe_name}")
        except ValueError:
            warnings.append("pst_parser_header_redacted")
    if "message-id" not in headers and message.get("message-id"):
        headers["message-id"] = _message_id(message, fallback_parts=("header",))
    return headers


def _safe_header_name(name: str) -> str:
    assert_no_public_raw_references(name, "pst_mail_header_name")
    return name


def _safe_header_tokens(value: str, field_name: str) -> list[str]:
    tokens = [item for item in re.split(r"\s+", str(value or "").strip()) if item]
    return [_safe_mail_text(token, field_name) for token in tokens[:25]]


def _safe_optional_header(value: str | None, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    return _safe_mail_text(str(value), field_name)


def _safe_mail_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if field_name == "filename" and _looks_like_unsafe_attachment_filename(text):
        return f"redacted_{field_name}_{sha256_json(text)[-16:]}"
    try:
        assert_no_public_raw_references(text, f"pst_mail_{field_name}")
    except Exception:
        return f"redacted_{field_name}_{sha256_json(text)[-16:]}"
    return text


def _looks_like_unsafe_attachment_filename(value: str) -> bool:
    text = str(value or "")
    lowered = text.lower()
    return bool(
        re.search(r"^[a-z]:", text, re.IGNORECASE)
        or "/" in text
        or "\\" in text
        or "archive.pst" in lowered
        or "pst-exm" in lowered
    )


def _plain_body(message: EmailMessage) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in message.walk() if message.is_multipart() else [message]:
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        if disposition == "attachment":
            continue
        content_type = part.get_content_type()
        try:
            content = part.get_content()
        except Exception:
            continue
        if not isinstance(content, str):
            continue
        if content_type == "text/plain":
            plain_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(_html_to_text(content))
    body = "\n\n".join(part.strip() for part in plain_parts if part.strip())
    if body:
        return body
    return "\n\n".join(part.strip() for part in html_parts if part.strip())


def _safe_body_segments(
    text: str,
    *,
    max_chars: int,
    max_segments: int | None,
    preserve_private_text: bool,
    warnings: list[str],
) -> tuple[list[_ParsedBodySegment], str, int]:
    segments: list[_ParsedBodySegment] = []
    redacted_segment_count = 0
    for start in range(0, len(text), max_chars):
        if max_segments is not None and len(segments) >= max_segments:
            warnings.append("pst_parser_body_segment_limit_reached")
            return segments, "truncated", redacted_segment_count
        chunk = text[start : start + max_chars]
        safe_text, publicly_unsafe = _safe_body_segment(
            chunk,
            preserve_private_text=preserve_private_text,
            warnings=warnings,
        )
        if publicly_unsafe and not preserve_private_text:
            redacted_segment_count += 1
        segments.append(
            _ParsedBodySegment(
                text=safe_text,
                char_start=start,
                char_end=start + len(chunk),
                content_publicly_unsafe=publicly_unsafe,
            )
        )
    if not text:
        return [], "complete", 0
    if redacted_segment_count:
        return segments, "redacted", redacted_segment_count
    return segments, "complete", 0


def _safe_body_segment(
    value: str,
    *,
    preserve_private_text: bool,
    warnings: list[str],
) -> tuple[str, bool]:
    try:
        assert_no_public_raw_references(value, "pst_mail_body_segment")
    except Exception:
        if preserve_private_text:
            warnings.append("pst_parser_body_segment_contains_publicly_unsafe_text")
            return value, True
        warnings.append("pst_parser_body_segment_redacted")
        return f"redacted_mail_body_segment {sha256_json(value)}", True
    return value, False


def _attachments(
    message: EmailMessage,
    *,
    config: _PstParserConfig,
    warnings: list[str],
) -> list[_ParsedAttachment]:
    attachments: list[_ParsedAttachment] = []
    for part in message.walk() if message.is_multipart() else []:
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if not filename and disposition != "attachment":
            continue
        attachment_index = len(attachments) + 1
        safe_filename = _safe_mail_text(filename or f"attachment-{attachment_index}", "filename")
        payload = part.get_payload(decode=True)
        size_bytes = len(payload) if isinstance(payload, bytes) else None
        content_hash = None
        if isinstance(payload, bytes) and len(payload) <= config.max_attachment_hash_bytes:
            content_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
        elif isinstance(payload, bytes):
            warnings.append("pst_parser_large_attachment_hash_skipped")
        attachment_id = stable_resource_contract_id(
            "mailatt",
            "PstAttachment",
            {
                "filename": safe_filename,
                "content_hash": content_hash,
                "size_bytes": size_bytes,
                "attachment_index": attachment_index,
            },
        )
        extracted_text_segments, text_extraction_state = _attachment_text_segments(
            payload,
            mime_type=part.get_content_type(),
            max_bytes=config.max_attachment_text_bytes,
            body_segment_max_chars=config.body_segment_max_chars,
            preserve_private_text=config.preserve_private_body_text,
            warnings=warnings,
        )
        attachments.append(
            _ParsedAttachment(
                attachment_id=attachment_id,
                filename=safe_filename,
                mime_type=_safe_mail_text(part.get_content_type(), "attachment_mime_type"),
                content_hash=content_hash,
                size_bytes=size_bytes,
                extracted_text_segments=extracted_text_segments,
                text_extraction_state=text_extraction_state,
            )
        )
    return attachments


def _attachment_text_segments(
    payload: bytes | str | None,
    *,
    mime_type: str,
    max_bytes: int,
    body_segment_max_chars: int,
    preserve_private_text: bool,
    warnings: list[str],
) -> tuple[list[str], str]:
    normalized_mime_type = str(mime_type or "").lower()
    supported = normalized_mime_type.startswith("text/") or normalized_mime_type in {
        "application/json",
        "application/xml",
        "application/xhtml+xml",
        "message/rfc822",
    }
    if not supported:
        return [], "unsupported"
    if payload is None:
        return [], "failed"
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(raw) > max_bytes:
        warnings.append("pst_parser_attachment_text_limit_reached")
        return [], "too_large"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        warnings.append("pst_parser_attachment_text_decode_replaced")
    if not text:
        return [], "complete"
    parsed, state, _ = _safe_body_segments(
        text,
        max_chars=body_segment_max_chars,
        max_segments=None,
        preserve_private_text=preserve_private_text,
        warnings=warnings,
    )
    return [segment.text for segment in parsed], state


def _mail_observations_from_messages(
    messages: Sequence[_ParsedMessage],
    *,
    extraction_input: ExtractionInput,
) -> list[Observation]:
    created_at = extraction_input.created_at or now_iso()
    archive_id = stable_resource_contract_id(
        "mailarchive",
        "PstArchive",
        {
            "asset_id": extraction_input.asset.asset_id,
            "archive_sha256": extraction_input.asset.content_hash,
        },
    )
    mailbox_id = stable_resource_contract_id(
        "mailbox",
        "PstMailbox",
        {"asset_id": extraction_input.asset.asset_id},
    )
    parsed_observations = list(
        _iter_mail_observations(
            messages,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
        )
    )
    observations: list[Observation] = []
    for parsed in parsed_observations:
        observation_id = stable_observation_id(
            asset_id=extraction_input.asset.asset_id,
            extractor_run_id=extraction_input.extractor_run_id,
            observation_type=parsed["observation_type"],
            modality="mail",
            location=parsed["location"],
            text=parsed.get("text"),
            payload=parsed["payload"],
        )
        observations.append(
            Observation(
                observation_id=observation_id,
                asset_id=extraction_input.asset.asset_id,
                extractor_run_id=extraction_input.extractor_run_id,
                observation_type=parsed["observation_type"],
                modality="mail",
                text=parsed.get("text"),
                location=parsed["location"],
                confidence=1.0,
                permission_scope=extraction_input.asset.permission_scope,
                created_at=created_at,
                payload=parsed["payload"],
            )
        )
    return observations


def _iter_mail_observations(
    messages: Sequence[_ParsedMessage],
    *,
    archive_id: str,
    mailbox_id: str,
) -> Iterable[dict[str, Any]]:
    folder_labels: dict[str, str] = {}
    for message in messages:
        folder_labels.setdefault(message.folder_path_hash, message.folder_label)
    for folder_index, (folder_path_hash, folder_label) in enumerate(
        sorted(folder_labels.items()),
        start=1,
    ):
        yield {
            "observation_type": "mail_folder_occurrence",
            "text": folder_label,
            "location": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "folder_index": folder_index,
            },
            "payload": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "folder_label": folder_label,
            },
        }

    thread_payloads = _thread_payloads(messages, archive_id=archive_id, mailbox_id=mailbox_id)
    for thread_index, payload in enumerate(thread_payloads, start=1):
        yield {
            "observation_type": "email_thread",
            "text": payload["normalized_subject"],
            "location": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "thread_id": payload["thread_id"],
                "thread_index": thread_index,
            },
            "payload": payload,
        }

    duplicate_ordinals: dict[tuple[str, str, str], int] = {}
    for message_index, message in enumerate(messages, start=1):
        thread_id = _thread_id(message)
        message_fingerprint = _message_fingerprint(message)
        occurrence_key = (
            message.folder_path_hash,
            message.message_id,
            message_fingerprint,
        )
        duplicate_ordinal = duplicate_ordinals.get(occurrence_key, 0) + 1
        duplicate_ordinals[occurrence_key] = duplicate_ordinal
        occurrence_id = stable_resource_contract_id(
            "mailocc",
            "PstMessageOccurrence",
            {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": message.folder_path_hash,
                "message_id": message.message_id,
                "message_fingerprint": message_fingerprint,
                "duplicate_ordinal": duplicate_ordinal,
            },
        )
        base_location = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "folder_path_hash": message.folder_path_hash,
            "message_id": message.message_id,
            "message_occurrence_id": occurrence_id,
            "thread_id": thread_id,
        }
        yield {
            "observation_type": "email_message",
            "text": message.subject,
            "location": {**base_location, "message_index": message_index},
            "payload": {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "message_id": message.message_id,
                "message_occurrence_id": occurrence_id,
                "message_occurrence_identity_policy": ("formowl_pst_message_occurrence_content_v2"),
                "duplicate_ordinal": duplicate_ordinal,
                "thread_id": thread_id,
                "subject": message.subject,
                "normalized_subject": message.normalized_subject,
                "sender": message.sender,
                "sent_at": message.sent_at,
                "body_hash": message.body_hash,
                "source_body_char_count": message.source_body_char_count,
                "stored_body_char_count": message.stored_body_char_count,
                "body_segment_count": len(message.body_segments),
                "body_evidence_state": message.body_evidence_state,
                "body_redacted_segment_count": message.body_redacted_segment_count,
                "unresolved_attachment_count": message.unresolved_attachment_count,
                "message_fingerprint": message_fingerprint,
                "fingerprint_policy": "formowl_mail_fingerprint_v1",
            },
        }
        for header_index, (header_name, header_value) in enumerate(
            sorted(message.headers.items()),
            start=1,
        ):
            yield {
                "observation_type": "email_header",
                "text": f"{header_name}: {header_value}",
                "location": {
                    **base_location,
                    "header_index": header_index,
                    "header_name": header_name,
                },
                "payload": {
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message.message_id,
                    "message_occurrence_id": occurrence_id,
                    "message_occurrence_identity_policy": (
                        "formowl_pst_message_occurrence_content_v2"
                    ),
                    "duplicate_ordinal": duplicate_ordinal,
                    "thread_id": thread_id,
                    "header_name": header_name,
                    "header_value": header_value,
                },
            }
        for segment_index, body_segment in enumerate(message.body_segments, start=1):
            yield {
                "observation_type": "email_body_segment",
                "text": body_segment.text,
                "location": {
                    **base_location,
                    "body_segment_index": segment_index,
                    "char_start": body_segment.char_start,
                    "char_end": body_segment.char_end,
                },
                "payload": {
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message.message_id,
                    "message_occurrence_id": occurrence_id,
                    "message_occurrence_identity_policy": (
                        "formowl_pst_message_occurrence_content_v2"
                    ),
                    "duplicate_ordinal": duplicate_ordinal,
                    "thread_id": thread_id,
                    "body_segment_index": segment_index,
                    "body_segment_count": len(message.body_segments),
                    "source_body_char_count": message.source_body_char_count,
                    "stored_body_char_count": message.stored_body_char_count,
                    "body_evidence_state": message.body_evidence_state,
                    "content_publicly_unsafe": body_segment.content_publicly_unsafe,
                    "message_fingerprint": message_fingerprint,
                },
            }
        for attachment_index, attachment in enumerate(message.attachments, start=1):
            yield {
                "observation_type": "email_attachment_occurrence",
                "text": attachment.filename,
                "location": {
                    **base_location,
                    "attachment_index": attachment_index,
                    "attachment_id": attachment.attachment_id,
                },
                "payload": {
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message.message_id,
                    "message_occurrence_id": occurrence_id,
                    "message_occurrence_identity_policy": (
                        "formowl_pst_message_occurrence_content_v2"
                    ),
                    "duplicate_ordinal": duplicate_ordinal,
                    "thread_id": thread_id,
                    "attachment_id": attachment.attachment_id,
                    "filename": attachment.filename,
                    "mime_type": attachment.mime_type,
                    "content_hash": attachment.content_hash,
                    "size_bytes": attachment.size_bytes,
                    "text_extraction_state": attachment.text_extraction_state,
                    "extracted_text_segment_count": len(attachment.extracted_text_segments),
                    "message_fingerprint": message_fingerprint,
                },
            }
            for attachment_text_index, attachment_text in enumerate(
                attachment.extracted_text_segments,
                start=1,
            ):
                yield {
                    "observation_type": "email_attachment_text_segment",
                    "text": attachment_text,
                    "location": {
                        **base_location,
                        "attachment_index": attachment_index,
                        "attachment_id": attachment.attachment_id,
                        "attachment_text_segment_index": attachment_text_index,
                    },
                    "payload": {
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message.message_id,
                        "message_occurrence_id": occurrence_id,
                        "message_occurrence_identity_policy": (
                            "formowl_pst_message_occurrence_content_v2"
                        ),
                        "duplicate_ordinal": duplicate_ordinal,
                        "thread_id": thread_id,
                        "attachment_id": attachment.attachment_id,
                        "attachment_index": attachment_index,
                        "attachment_text_segment_index": attachment_text_index,
                        "attachment_text_segment_count": len(attachment.extracted_text_segments),
                        "text_extraction_state": attachment.text_extraction_state,
                        "message_fingerprint": message_fingerprint,
                    },
                }


def _message_fingerprint(message: _ParsedMessage) -> str:
    attachment_hashes = sorted(
        attachment.content_hash for attachment in message.attachments if attachment.content_hash
    )
    return sha256_json(
        {
            "message_id": message.message_id,
            "normalized_subject": message.normalized_subject,
            "sender": message.sender,
            "sent_at": message.sent_at,
            "body_hash": message.body_hash,
            "attachment_hashes": attachment_hashes,
        }
    )


def _thread_payloads(
    messages: Sequence[_ParsedMessage],
    *,
    archive_id: str,
    mailbox_id: str,
) -> list[dict[str, Any]]:
    threads: dict[str, dict[str, Any]] = {}
    for message in messages:
        thread_id = _thread_id(message)
        thread = threads.setdefault(
            thread_id,
            {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "thread_id": thread_id,
                "normalized_subject": message.normalized_subject,
                "message_ids": [],
                "participants": [],
                "sent_at_values": [],
                "thread_identity_policy": "formowl_mail_thread_identity_v1",
            },
        )
        thread["message_ids"].append(message.message_id)
        if message.sender and message.sender not in thread["participants"]:
            thread["participants"].append(message.sender)
        if message.sent_at:
            thread["sent_at_values"].append(message.sent_at)
    results: list[dict[str, Any]] = []
    for thread in threads.values():
        sent_at_values = sorted(thread.pop("sent_at_values"))
        if sent_at_values:
            thread["first_sent_at"] = sent_at_values[0]
            thread["last_sent_at"] = sent_at_values[-1]
        thread["message_count"] = len(thread["message_ids"])
        results.append(thread)
    return sorted(results, key=lambda item: item["thread_id"])


def _thread_id(message: _ParsedMessage) -> str:
    if message.references:
        return stable_resource_contract_id(
            "mailthread",
            "PstThread",
            {"references": message.references},
        )
    if message.in_reply_to:
        return stable_resource_contract_id(
            "mailthread",
            "PstThread",
            {"in_reply_to": message.in_reply_to},
        )
    return stable_resource_contract_id(
        "mailthread",
        "PstThread",
        {"normalized_subject": message.normalized_subject or message.message_id},
    )


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self._parts)


def _html_to_text(value: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(value)
    return parser.text()


__all__ = [
    "PstMailArchiveExtractor",
]
