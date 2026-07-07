from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from formowl_contract import (
    Observation,
    now_iso,
    sha256_json,
    stable_observation_id,
    stable_resource_contract_id,
    to_plain,
)

from ...extraction import ExtractionInput, ExtractionResult

_SUPPORTED_MAIL_MIME_TYPES = [
    "application/vnd.formowl.mail-archive+json",
    "application/json",
    "message/rfc822",
]


@dataclass(frozen=True)
class _MailObservation:
    observation_type: str
    text: str | None
    location: dict[str, Any]
    payload: dict[str, Any]


class FixtureMailArchiveExtractor:
    """Deterministic mail/archive adapter for JSON-backed Phase 0 fixtures."""

    def __init__(self, *, version: str = "0.1.0") -> None:
        self._version = version

    def name(self) -> str:
        return "fixture_mail_archive_extractor"

    def version(self) -> str:
        return self._version

    def supported_mime_types(self) -> list[str]:
        return list(_SUPPORTED_MAIL_MIME_TYPES)

    def extractor_type(self) -> str:
        return "mail_archive"

    def extract(self, extraction_input: ExtractionInput) -> ExtractionResult:
        created_at = extraction_input.created_at or now_iso()
        archive = json.loads(extraction_input.object_path.read_text(encoding="utf-8"))
        archive_id = _required_str(archive, "archive_id")
        mailbox_id = _required_str(archive, "mailbox_id")
        source_ref = _source_payload(extraction_input.asset.source_ref)
        observations: list[Observation] = []

        # Mail import keeps archive, mailbox, folder, message, body, and
        # attachment occurrence identity separate so dedupe cannot erase lineage.
        for parsed in _iter_mail_observations(
            archive,
            archive_id=archive_id,
            mailbox_id=mailbox_id,
            source_ref=source_ref,
        ):
            observation_id = stable_observation_id(
                asset_id=extraction_input.asset.asset_id,
                extractor_run_id=extraction_input.extractor_run_id,
                observation_type=parsed.observation_type,
                modality="mail",
                location=parsed.location,
                text=parsed.text,
                payload=parsed.payload,
            )
            observations.append(
                Observation(
                    observation_id=observation_id,
                    asset_id=extraction_input.asset.asset_id,
                    extractor_run_id=extraction_input.extractor_run_id,
                    observation_type=parsed.observation_type,
                    modality="mail",
                    text=parsed.text,
                    location=parsed.location,
                    confidence=1.0,
                    permission_scope=extraction_input.asset.permission_scope,
                    created_at=created_at,
                    payload=parsed.payload,
                )
            )

        warnings = [] if observations else ["no_mail_observations"]
        return ExtractionResult(observations=observations, warnings=warnings)


def _iter_mail_observations(
    archive: dict[str, Any],
    *,
    archive_id: str,
    mailbox_id: str,
    source_ref: dict[str, Any] | None,
) -> Iterable[_MailObservation]:
    messages = _mail_messages(archive)
    for folder_index, folder in enumerate(archive.get("folders", []), start=1):
        folder_path_hash = _required_str(folder, "folder_path_hash")
        folder_label = str(folder.get("label") or folder.get("folder_label") or "folder")
        yield _MailObservation(
            observation_type="mail_folder_occurrence",
            text=folder_label,
            location={
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "folder_index": folder_index,
            },
            payload=_with_source(
                {
                    "source_ref": source_ref,
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "folder_path_hash": folder_path_hash,
                    "folder_label": folder_label,
                }
            ),
        )

    for thread_index, thread in enumerate(
        _iter_thread_observations(messages, archive_id=archive_id, mailbox_id=mailbox_id),
        start=1,
    ):
        yield _MailObservation(
            observation_type="email_thread",
            text=thread["normalized_subject"],
            location={
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "thread_id": thread["thread_id"],
                "thread_index": thread_index,
            },
            payload=_with_source({"source_ref": source_ref, **thread}),
        )

    for message_index, message in enumerate(messages, start=1):
        message_id = _required_str(message, "message_id")
        folder_path_hash = _required_str(message, "folder_path_hash")
        subject = str(message.get("subject") or "")
        sender = str(message.get("sender") or "")
        sent_at = str(message.get("sent_at") or "")
        normalized_subject = _normalize_subject(subject)
        thread_id = _thread_id(message, normalized_subject=normalized_subject)
        message_fingerprint = _message_fingerprint(
            archive_id=archive_id,
            mailbox_id=mailbox_id,
            message=message,
            normalized_subject=normalized_subject,
            sender=sender,
            sent_at=sent_at,
        )
        occurrence_id = stable_resource_contract_id(
            "mailocc",
            "MailMessageOccurrence",
            {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "message_id": message_id,
                "message_index": message_index,
            },
        )
        base_location = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "folder_path_hash": folder_path_hash,
            "message_id": message_id,
            "thread_id": thread_id,
        }
        yield _MailObservation(
            observation_type="email_message",
            text=subject,
            location={
                **base_location,
                "message_index": message_index,
                "message_occurrence_id": occurrence_id,
            },
            payload=_with_source(
                {
                    "source_ref": source_ref,
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message_id,
                    "message_occurrence_id": occurrence_id,
                    "thread_id": thread_id,
                    "subject": subject,
                    "normalized_subject": normalized_subject,
                    "sender": sender,
                    "sent_at": sent_at,
                    "body_hash": message.get("body_hash"),
                    "message_fingerprint": message_fingerprint,
                    "fingerprint_policy": "formowl_mail_fingerprint_v1",
                }
            ),
        )

        for header_index, header in enumerate(_headers(message), start=1):
            yield _MailObservation(
                observation_type="email_header",
                text=f"{header['header_name']}: {header['header_value']}",
                location={
                    **base_location,
                    "header_index": header_index,
                    "header_name": header["header_name"],
                },
                payload=_with_source(
                    {
                        "source_ref": source_ref,
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": thread_id,
                        **header,
                    }
                ),
            )

        for segment_index, body_segment in enumerate(_body_segments(message), start=1):
            yield _MailObservation(
                observation_type="email_body_segment",
                text=body_segment,
                location={**base_location, "body_segment_index": segment_index},
                payload=_with_source(
                    {
                        "source_ref": source_ref,
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": thread_id,
                        "body_segment_index": segment_index,
                    }
                ),
            )

        for attachment_index, attachment in enumerate(message.get("attachments", []), start=1):
            attachment_id = str(
                attachment.get("attachment_id")
                or attachment.get("content_hash")
                or f"{message_id}:{attachment_index}"
            )
            filename = str(attachment.get("filename") or "attachment")
            yield _MailObservation(
                observation_type="email_attachment_occurrence",
                text=filename,
                location={
                    **base_location,
                    "attachment_index": attachment_index,
                    "attachment_id": attachment_id,
                },
                payload=_with_source(
                    {
                        "source_ref": source_ref,
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": thread_id,
                        "attachment_id": attachment_id,
                        "filename": filename,
                        "mime_type": attachment.get("mime_type"),
                        "content_hash": attachment.get("content_hash"),
                        "size_bytes": attachment.get("size_bytes"),
                    }
                ),
            )


def _mail_messages(archive: dict[str, Any]) -> list[dict[str, Any]]:
    messages = archive.get("messages", [])
    if messages is None:
        return []
    if not isinstance(messages, list):
        raise ValueError("mail archive fixture field must be a list: messages")
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("mail archive fixture message must be an object")
    return list(messages)


def _iter_thread_observations(
    messages: list[dict[str, Any]],
    *,
    archive_id: str,
    mailbox_id: str,
) -> Iterable[dict[str, Any]]:
    threads: dict[str, dict[str, Any]] = {}
    for message in messages:
        message_id = _required_str(message, "message_id")
        subject = str(message.get("subject") or "")
        sender = str(message.get("sender") or "")
        sent_at = str(message.get("sent_at") or "")
        normalized_subject = _normalize_subject(subject)
        thread_id = _thread_id(message, normalized_subject=normalized_subject)
        thread = threads.setdefault(
            thread_id,
            {
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "thread_id": thread_id,
                "normalized_subject": normalized_subject,
                "message_ids": [],
                "participants": [],
                "sent_at_values": [],
                "thread_identity_policy": "formowl_mail_thread_identity_v1",
            },
        )
        thread["message_ids"].append(message_id)
        if sender and sender not in thread["participants"]:
            thread["participants"].append(sender)
        if sent_at:
            thread["sent_at_values"].append(sent_at)

    for thread in threads.values():
        sent_at_values = sorted(thread.pop("sent_at_values"))
        if sent_at_values:
            thread["first_sent_at"] = sent_at_values[0]
            thread["last_sent_at"] = sent_at_values[-1]
        thread["message_count"] = len(thread["message_ids"])
        yield thread


def _body_segments(message: dict[str, Any]) -> list[str]:
    explicit_segments = message.get("body_segments")
    if isinstance(explicit_segments, list):
        return [str(segment).strip() for segment in explicit_segments if str(segment).strip()]
    body = str(message.get("body") or "")
    return [segment.strip() for segment in body.split("\n\n") if segment.strip()]


def _headers(message: dict[str, Any]) -> list[dict[str, str]]:
    headers = message.get("headers")
    if headers is None:
        headers = {
            "message-id": message.get("message_id"),
            "subject": message.get("subject"),
            "from": message.get("sender"),
            "date": message.get("sent_at"),
        }
    if not isinstance(headers, dict):
        raise ValueError("mail archive fixture field must be an object: headers")

    normalized: list[dict[str, str]] = []
    for name, value in sorted(headers.items(), key=lambda item: str(item[0]).lower()):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("mail archive fixture header name must be a non-empty string")
        values = value if isinstance(value, list) else [value]
        if not all(isinstance(item, str) for item in values):
            raise ValueError(f"mail archive fixture header value must be a string: {name}")
        header_value = ", ".join(item.strip() for item in values if item.strip())
        if header_value:
            normalized.append(
                {
                    "header_name": name.strip().lower(),
                    "header_value": header_value,
                }
            )
    return normalized


def _thread_id(message: dict[str, Any], *, normalized_subject: str) -> str:
    explicit_thread_id = message.get("thread_id")
    if explicit_thread_id not in (None, ""):
        if not isinstance(explicit_thread_id, str):
            raise ValueError("mail archive fixture field must be a string: thread_id")
        return explicit_thread_id

    references = message.get("references")
    if references not in (None, ""):
        if isinstance(references, list):
            if not all(isinstance(item, str) for item in references):
                raise ValueError("mail archive fixture references must contain only strings")
            if references:
                return stable_resource_contract_id(
                    "mailthread",
                    "MailThread",
                    {"references": references},
                )
        elif isinstance(references, str):
            return stable_resource_contract_id(
                "mailthread",
                "MailThread",
                {"references": references},
            )
        else:
            raise ValueError("mail archive fixture field must be a string or list: references")

    in_reply_to = message.get("in_reply_to")
    if in_reply_to not in (None, ""):
        if not isinstance(in_reply_to, str):
            raise ValueError("mail archive fixture field must be a string: in_reply_to")
        return stable_resource_contract_id(
            "mailthread",
            "MailThread",
            {"in_reply_to": in_reply_to},
        )

    return stable_resource_contract_id(
        "mailthread",
        "MailThread",
        {"normalized_subject": normalized_subject or _required_str(message, "message_id")},
    )


def _normalize_subject(subject: str) -> str:
    normalized = subject.strip()
    while True:
        lowered = normalized.lower()
        for prefix in ("re:", "fw:", "fwd:"):
            if lowered.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                break
        else:
            return " ".join(normalized.split()).lower()


def _message_fingerprint(
    *,
    archive_id: str,
    mailbox_id: str,
    message: dict[str, Any],
    normalized_subject: str,
    sender: str,
    sent_at: str,
) -> str:
    attachment_hashes = []
    for attachment in message.get("attachments", []):
        if isinstance(attachment, dict) and attachment.get("content_hash") is not None:
            attachment_hashes.append(str(attachment["content_hash"]))
    return sha256_json(
        {
            "message_id": _required_str(message, "message_id"),
            "normalized_subject": normalized_subject,
            "sender": sender,
            "sent_at": sent_at,
            "body_hash": message.get("body_hash"),
            "attachment_hashes": sorted(attachment_hashes),
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
        }
    )


def _required_str(value: dict[str, Any], field_name: str) -> str:
    item = value.get(field_name)
    if item in (None, ""):
        raise ValueError(f"mail archive fixture missing required field: {field_name}")
    if not isinstance(item, str):
        raise ValueError(f"mail archive fixture field must be a string: {field_name}")
    return item


def _with_source(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _source_payload(source_ref: Any) -> dict[str, Any] | None:
    if source_ref is None:
        return None
    return to_plain(source_ref)
