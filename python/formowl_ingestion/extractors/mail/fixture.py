from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from formowl_contract import Observation, now_iso, stable_observation_id, to_plain

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

    for message_index, message in enumerate(archive.get("messages", []), start=1):
        message_id = _required_str(message, "message_id")
        folder_path_hash = _required_str(message, "folder_path_hash")
        subject = str(message.get("subject") or "")
        sender = str(message.get("sender") or "")
        sent_at = str(message.get("sent_at") or "")
        base_location = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "folder_path_hash": folder_path_hash,
            "message_id": message_id,
        }
        yield _MailObservation(
            observation_type="email_message",
            text=subject,
            location={**base_location, "message_index": message_index},
            payload=_with_source(
                {
                    "source_ref": source_ref,
                    "archive_id": archive_id,
                    "mailbox_id": mailbox_id,
                    "message_id": message_id,
                    "subject": subject,
                    "sender": sender,
                    "sent_at": sent_at,
                    "body_hash": message.get("body_hash"),
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
                        "attachment_id": attachment_id,
                        "filename": filename,
                        "mime_type": attachment.get("mime_type"),
                        "content_hash": attachment.get("content_hash"),
                        "size_bytes": attachment.get("size_bytes"),
                    }
                ),
            )


def _body_segments(message: dict[str, Any]) -> list[str]:
    explicit_segments = message.get("body_segments")
    if isinstance(explicit_segments, list):
        return [str(segment).strip() for segment in explicit_segments if str(segment).strip()]
    body = str(message.get("body") or "")
    return [segment.strip() for segment in body.split("\n\n") if segment.strip()]


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
