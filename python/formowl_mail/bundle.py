from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from formowl_contract import (
    ContractValidationError,
    Observation,
    now_iso,
    sha256_json,
    stable_resource_contract_id,
    to_plain,
)

from ._guards import assert_public_payload_safe, safe_public_string

_RETENTION_POLICIES = {
    "delete_after_successful_extract",
    "retain_7_days",
    "retain_30_days",
    "retain_indefinitely",
}
_RETENTION_DECISIONS = _RETENTION_POLICIES | {
    "pending_extract",
    "deleted_after_extract",
    "retained_by_policy",
}
_PRODUCER_TYPES = {"server_side_parser", "local_companion_parser", "fixture_parser"}


@dataclass(frozen=True)
class MailImportSession:
    mail_import_session_id: str
    workspace_id: str
    owner_user_id: str
    source_asset_id: str
    archive_sha256: str
    retention_policy: str
    raw_archive_retention_decision: str
    created_at: str
    upload_session_id: str | None = None
    import_profile: str = "mail_archive_phase1"
    status: str = "succeeded"

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "mail_import_session")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MailImportSession":
        item = _require_dict(value, "mail_import_session")
        session = cls(
            mail_import_session_id=_required_str(item, "mail_import_session_id"),
            workspace_id=_required_str(item, "workspace_id"),
            owner_user_id=_required_str(item, "owner_user_id"),
            source_asset_id=_required_str(item, "source_asset_id"),
            archive_sha256=_required_str(item, "archive_sha256"),
            retention_policy=_required_choice(
                item,
                "retention_policy",
                _RETENTION_POLICIES,
            ),
            raw_archive_retention_decision=_required_choice(
                item,
                "raw_archive_retention_decision",
                _RETENTION_DECISIONS,
            ),
            created_at=_required_str(item, "created_at"),
            upload_session_id=_optional_str(item, "upload_session_id"),
            import_profile=_optional_str(item, "import_profile") or "mail_archive_phase1",
            status=_optional_str(item, "status") or "succeeded",
        )
        session.to_dict()
        return session


@dataclass(frozen=True)
class MailArchiveOccurrence:
    mail_archive_occurrence_id: str
    mail_import_session_id: str
    source_asset_id: str
    archive_id: str
    mailbox_id: str
    archive_sha256: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "mail_archive_occurrence")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MailArchiveOccurrence":
        return _from_required_fields(
            cls,
            value,
            "mail_archive_occurrence",
            (
                "mail_archive_occurrence_id",
                "mail_import_session_id",
                "source_asset_id",
                "archive_id",
                "mailbox_id",
                "archive_sha256",
                "created_at",
            ),
        )


@dataclass(frozen=True)
class MailFolderOccurrence:
    mail_folder_occurrence_id: str
    mail_archive_occurrence_id: str
    archive_id: str
    mailbox_id: str
    folder_path_hash: str
    source_observation_id: str
    folder_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "mail_folder_occurrence")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MailFolderOccurrence":
        item = _require_dict(value, "mail_folder_occurrence")
        folder = cls(
            mail_folder_occurrence_id=_required_str(item, "mail_folder_occurrence_id"),
            mail_archive_occurrence_id=_required_str(item, "mail_archive_occurrence_id"),
            archive_id=_required_str(item, "archive_id"),
            mailbox_id=_required_str(item, "mailbox_id"),
            folder_path_hash=_required_str(item, "folder_path_hash"),
            source_observation_id=_required_str(item, "source_observation_id"),
            folder_label=_optional_str(item, "folder_label"),
        )
        folder.to_dict()
        return folder


@dataclass(frozen=True)
class EmailMessage:
    email_message_id: str
    message_fingerprint: str
    message_id: str
    archive_id: str
    mailbox_id: str
    source_observation_ids: list[str]
    subject: str | None = None
    normalized_subject: str | None = None
    sender: str | None = None
    sent_at: str | None = None
    body_hash: str | None = None
    thread_id: str | None = None
    fingerprint_policy: str = "formowl_mail_fingerprint_v1"
    source_body_char_count: int | None = None
    stored_body_char_count: int | None = None
    body_segment_count: int | None = None
    body_evidence_state: str = "unknown"
    body_redacted_segment_count: int = 0
    unresolved_attachment_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "email_message")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EmailMessage":
        item = _require_dict(value, "email_message")
        message = cls(
            email_message_id=_required_str(item, "email_message_id"),
            message_fingerprint=_required_str(item, "message_fingerprint"),
            message_id=_required_str(item, "message_id"),
            archive_id=_required_str(item, "archive_id"),
            mailbox_id=_required_str(item, "mailbox_id"),
            source_observation_ids=_str_list(item.get("source_observation_ids")),
            subject=_optional_str(item, "subject"),
            normalized_subject=_optional_str(item, "normalized_subject"),
            sender=_optional_str(item, "sender"),
            sent_at=_optional_str(item, "sent_at"),
            body_hash=_optional_str(item, "body_hash"),
            thread_id=_optional_str(item, "thread_id"),
            fingerprint_policy=_optional_str(item, "fingerprint_policy")
            or "formowl_mail_fingerprint_v1",
            source_body_char_count=_optional_int(item, "source_body_char_count"),
            stored_body_char_count=_optional_int(item, "stored_body_char_count"),
            body_segment_count=_optional_int(item, "body_segment_count"),
            body_evidence_state=_optional_str(item, "body_evidence_state") or "unknown",
            body_redacted_segment_count=_optional_int(item, "body_redacted_segment_count") or 0,
            unresolved_attachment_count=_optional_int(item, "unresolved_attachment_count") or 0,
        )
        message.to_dict()
        return message


@dataclass(frozen=True)
class EmailMessageOccurrence:
    email_message_occurrence_id: str
    email_message_id: str
    mail_archive_occurrence_id: str
    message_occurrence_id: str
    message_id: str
    archive_id: str
    mailbox_id: str
    folder_path_hash: str
    source_observation_id: str
    thread_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "email_message_occurrence")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EmailMessageOccurrence":
        item = _require_dict(value, "email_message_occurrence")
        occurrence = cls(
            email_message_occurrence_id=_required_str(item, "email_message_occurrence_id"),
            email_message_id=_required_str(item, "email_message_id"),
            mail_archive_occurrence_id=_required_str(item, "mail_archive_occurrence_id"),
            message_occurrence_id=_required_str(item, "message_occurrence_id"),
            message_id=_required_str(item, "message_id"),
            archive_id=_required_str(item, "archive_id"),
            mailbox_id=_required_str(item, "mailbox_id"),
            folder_path_hash=_required_str(item, "folder_path_hash"),
            source_observation_id=_required_str(item, "source_observation_id"),
            thread_id=_optional_str(item, "thread_id"),
        )
        occurrence.to_dict()
        return occurrence


@dataclass(frozen=True)
class EmailBodySegment:
    email_body_segment_id: str
    email_message_id: str
    message_occurrence_id: str
    source_observation_id: str
    text: str
    body_segment_hash: str
    body_segment_index: int | None = None
    segment_source_type: str = "message_body"
    attachment_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    body_segment_count: int | None = None
    source_body_char_count: int | None = None
    stored_body_char_count: int | None = None
    body_evidence_state: str = "unknown"
    content_publicly_unsafe: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _private_payload(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EmailBodySegment":
        item = _require_private_dict(value, "email_body_segment")
        _assert_private_body_segment_envelope_safe(item)
        segment = cls(
            email_body_segment_id=_required_str(item, "email_body_segment_id"),
            email_message_id=_required_str(item, "email_message_id"),
            message_occurrence_id=_required_str(item, "message_occurrence_id"),
            source_observation_id=_required_str(item, "source_observation_id"),
            text=_required_private_str(item, "text"),
            body_segment_hash=_required_str(item, "body_segment_hash"),
            body_segment_index=_optional_int(item, "body_segment_index"),
            segment_source_type=_optional_str(item, "segment_source_type") or "message_body",
            attachment_id=_optional_str(item, "attachment_id"),
            char_start=_optional_int(item, "char_start"),
            char_end=_optional_int(item, "char_end"),
            body_segment_count=_optional_int(item, "body_segment_count"),
            source_body_char_count=_optional_int(item, "source_body_char_count"),
            stored_body_char_count=_optional_int(item, "stored_body_char_count"),
            body_evidence_state=_optional_str(item, "body_evidence_state") or "unknown",
            content_publicly_unsafe=_optional_bool(item, "content_publicly_unsafe") or False,
        )
        segment.to_dict()
        return segment


@dataclass(frozen=True)
class EmailAttachment:
    email_attachment_id: str
    attachment_fingerprint: str
    filename: str
    mime_type: str | None = None
    content_hash: str | None = None
    size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "email_attachment")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EmailAttachment":
        item = _require_dict(value, "email_attachment")
        attachment = cls(
            email_attachment_id=_required_str(item, "email_attachment_id"),
            attachment_fingerprint=_required_str(item, "attachment_fingerprint"),
            filename=_required_str(item, "filename"),
            mime_type=_optional_str(item, "mime_type"),
            content_hash=_optional_str(item, "content_hash"),
            size_bytes=_optional_int(item, "size_bytes"),
        )
        attachment.to_dict()
        return attachment


@dataclass(frozen=True)
class EmailAttachmentOccurrence:
    email_attachment_occurrence_id: str
    email_attachment_id: str
    email_message_id: str
    message_occurrence_id: str
    source_observation_id: str
    attachment_id: str
    attachment_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "email_attachment_occurrence")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EmailAttachmentOccurrence":
        item = _require_dict(value, "email_attachment_occurrence")
        occurrence = cls(
            email_attachment_occurrence_id=_required_str(
                item,
                "email_attachment_occurrence_id",
            ),
            email_attachment_id=_required_str(item, "email_attachment_id"),
            email_message_id=_required_str(item, "email_message_id"),
            message_occurrence_id=_required_str(item, "message_occurrence_id"),
            source_observation_id=_required_str(item, "source_observation_id"),
            attachment_id=_required_str(item, "attachment_id"),
            attachment_index=_optional_int(item, "attachment_index"),
        )
        occurrence.to_dict()
        return occurrence


@dataclass(frozen=True)
class QuotedMessageCandidate:
    quoted_message_candidate_id: str
    email_message_id: str
    source_observation_id: str
    quoted_text_hash: str
    confidence: float = 0.0
    matched_email_message_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "quoted_message_candidate")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QuotedMessageCandidate":
        item = _require_dict(value, "quoted_message_candidate")
        candidate = cls(
            quoted_message_candidate_id=_required_str(item, "quoted_message_candidate_id"),
            email_message_id=_required_str(item, "email_message_id"),
            source_observation_id=_required_str(item, "source_observation_id"),
            quoted_text_hash=_required_str(item, "quoted_text_hash"),
            confidence=_optional_float(item, "confidence") or 0.0,
            matched_email_message_id=_optional_str(item, "matched_email_message_id"),
        )
        candidate.to_dict()
        return candidate


@dataclass(frozen=True)
class EmbeddedMessageRelation:
    embedded_message_relation_id: str
    parent_email_message_id: str
    embedded_email_message_id: str
    source_attachment_occurrence_id: str
    source_observation_id: str

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "embedded_message_relation")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EmbeddedMessageRelation":
        return _from_required_fields(
            cls,
            value,
            "embedded_message_relation",
            (
                "embedded_message_relation_id",
                "parent_email_message_id",
                "embedded_email_message_id",
                "source_attachment_occurrence_id",
                "source_observation_id",
            ),
        )


@dataclass(frozen=True)
class MailParseRun:
    mail_parse_run_id: str
    mail_import_session_id: str
    extractor_run_id: str
    parser_name: str
    parser_version: str
    input_hash: str
    config_hash: str
    status: str
    started_at: str
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "mail_parse_run")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MailParseRun":
        item = _require_dict(value, "mail_parse_run")
        parse_run = cls(
            mail_parse_run_id=_required_str(item, "mail_parse_run_id"),
            mail_import_session_id=_required_str(item, "mail_import_session_id"),
            extractor_run_id=_required_str(item, "extractor_run_id"),
            parser_name=_required_str(item, "parser_name"),
            parser_version=_required_str(item, "parser_version"),
            input_hash=_required_str(item, "input_hash"),
            config_hash=_required_str(item, "config_hash"),
            status=_required_str(item, "status"),
            started_at=_required_str(item, "started_at"),
            completed_at=_optional_str(item, "completed_at"),
        )
        parse_run.to_dict()
        return parse_run


@dataclass(frozen=True)
class MailParseWarning:
    mail_parse_warning_id: str
    mail_parse_run_id: str
    warning_code: str
    message: str
    source_observation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _public_payload(self, "mail_parse_warning")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MailParseWarning":
        item = _require_dict(value, "mail_parse_warning")
        warning = cls(
            mail_parse_warning_id=_required_str(item, "mail_parse_warning_id"),
            mail_parse_run_id=_required_str(item, "mail_parse_run_id"),
            warning_code=_required_str(item, "warning_code"),
            message=_required_str(item, "message"),
            source_observation_id=_optional_str(item, "source_observation_id"),
        )
        warning.to_dict()
        return warning


@dataclass(frozen=True)
class MailEvidenceBundle:
    mail_evidence_bundle_id: str
    producer_type: str
    mail_import_session: MailImportSession
    archive_occurrences: list[MailArchiveOccurrence]
    folder_occurrences: list[MailFolderOccurrence]
    messages: list[EmailMessage]
    message_occurrences: list[EmailMessageOccurrence]
    body_segments: list[EmailBodySegment]
    attachments: list[EmailAttachment]
    attachment_occurrences: list[EmailAttachmentOccurrence]
    quoted_message_candidates: list[QuotedMessageCandidate]
    embedded_message_relations: list[EmbeddedMessageRelation]
    mail_parse_run: MailParseRun
    parse_warnings: list[MailParseWarning] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return _private_payload(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MailEvidenceBundle":
        item = _require_private_dict(value, "mail_evidence_bundle")
        _assert_private_mail_bundle_envelope_safe(item)
        bundle = cls(
            mail_evidence_bundle_id=_required_str(item, "mail_evidence_bundle_id"),
            producer_type=_required_choice(item, "producer_type", _PRODUCER_TYPES),
            mail_import_session=MailImportSession.from_dict(item["mail_import_session"]),
            archive_occurrences=_record_list(
                item,
                "archive_occurrences",
                MailArchiveOccurrence,
            ),
            folder_occurrences=_record_list(item, "folder_occurrences", MailFolderOccurrence),
            messages=_record_list(item, "messages", EmailMessage),
            message_occurrences=_record_list(
                item,
                "message_occurrences",
                EmailMessageOccurrence,
            ),
            body_segments=_record_list(item, "body_segments", EmailBodySegment),
            attachments=_record_list(item, "attachments", EmailAttachment),
            attachment_occurrences=_record_list(
                item,
                "attachment_occurrences",
                EmailAttachmentOccurrence,
            ),
            quoted_message_candidates=_record_list(
                item,
                "quoted_message_candidates",
                QuotedMessageCandidate,
            ),
            embedded_message_relations=_record_list(
                item,
                "embedded_message_relations",
                EmbeddedMessageRelation,
            ),
            mail_parse_run=MailParseRun.from_dict(item["mail_parse_run"]),
            parse_warnings=_record_list(
                item,
                "parse_warnings",
                MailParseWarning,
                required=False,
            ),
            created_at=_required_str(item, "created_at"),
        )
        bundle.to_dict()
        return bundle


def build_mail_evidence_bundle(
    observations: Sequence[Observation],
    *,
    workspace_id: str,
    owner_user_id: str,
    source_asset_id: str,
    archive_sha256: str,
    producer_type: str = "server_side_parser",
    parser_name: str = "formowl_mail_parser",
    parser_version: str = "0.1.0",
    upload_session_id: str | None = None,
    retention_policy: str = "retain_7_days",
    raw_archive_retention_decision: str = "retained_by_policy",
    created_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    parse_warnings: Sequence[str] = (),
) -> MailEvidenceBundle:
    resolved_created_at = created_at or now_iso()
    _required_choice({"producer_type": producer_type}, "producer_type", _PRODUCER_TYPES)
    if producer_type == "server_side_parser" and not upload_session_id:
        raise ContractValidationError("server_side_parser mail import requires upload_session_id")
    observation_payloads = [observation.to_dict() for observation in observations]
    for observation_payload in observation_payloads:
        _assert_private_observation_envelope_safe(observation_payload)
    normalized = [Observation.from_dict(observation) for observation in observation_payloads]
    mail_observations = [
        observation for observation in normalized if observation.modality == "mail"
    ]
    if not mail_observations:
        raise ContractValidationError("mail evidence bundle requires mail observations")
    first_mail = mail_observations[0]
    extractor_run_id = first_mail.extractor_run_id
    archive_id = _observation_location(first_mail, "archive_id")
    mailbox_id = _observation_location(first_mail, "mailbox_id")
    _validate_single_archive_mail_observations(
        mail_observations,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
    )
    mail_import_session_id = stable_resource_contract_id(
        "mailimport",
        "MailImportSession",
        {
            "upload_session_id": upload_session_id,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "source_asset_id": source_asset_id,
            "archive_sha256": archive_sha256,
        },
    )
    import_session = MailImportSession.from_dict(
        {
            "mail_import_session_id": mail_import_session_id,
            "workspace_id": workspace_id,
            "owner_user_id": owner_user_id,
            "source_asset_id": source_asset_id,
            "archive_sha256": archive_sha256,
            "retention_policy": retention_policy,
            "raw_archive_retention_decision": raw_archive_retention_decision,
            "created_at": resolved_created_at,
            "upload_session_id": upload_session_id,
            "import_profile": "mail_archive_phase1",
            "status": "succeeded",
        }
    )
    archive_occurrence = _archive_occurrence(
        import_session=import_session,
        archive_id=archive_id,
        mailbox_id=mailbox_id,
        created_at=resolved_created_at,
    )
    parse_run = _parse_run(
        import_session=import_session,
        extractor_run_id=extractor_run_id,
        parser_name=parser_name,
        parser_version=parser_version,
        started_at=started_at or resolved_created_at,
        completed_at=completed_at or resolved_created_at,
        status="succeeded",
    )
    folder_occurrences = _folder_occurrences(mail_observations, archive_occurrence)
    messages, message_occurrences = _messages_and_occurrences(
        mail_observations,
        archive_occurrence,
    )
    message_ids_by_fingerprint = {
        message.message_fingerprint: message.email_message_id for message in messages
    }
    message_ids_by_occurrence_id = {
        occurrence.message_occurrence_id: occurrence.email_message_id
        for occurrence in message_occurrences
    }
    body_segments = _body_segments(
        mail_observations,
        message_ids_by_fingerprint,
        message_ids_by_occurrence_id,
    )
    attachments, attachment_occurrences = _attachments(
        mail_observations,
        message_ids_by_fingerprint,
        message_ids_by_occurrence_id,
    )
    warnings = _parse_warnings(parse_run, parse_warnings)
    bundle_id = stable_resource_contract_id(
        "mailevidencebundle",
        "MailEvidenceBundle",
        {
            "mail_import_session_id": import_session.mail_import_session_id,
            "producer_type": producer_type,
            "message_ids": [message.email_message_id for message in messages],
            "message_occurrence_ids": [
                occurrence.email_message_occurrence_id for occurrence in message_occurrences
            ],
            "attachment_occurrence_ids": [
                occurrence.email_attachment_occurrence_id for occurrence in attachment_occurrences
            ],
        },
    )
    bundle = MailEvidenceBundle(
        mail_evidence_bundle_id=bundle_id,
        producer_type=producer_type,
        mail_import_session=import_session,
        archive_occurrences=[archive_occurrence],
        folder_occurrences=folder_occurrences,
        messages=messages,
        message_occurrences=message_occurrences,
        body_segments=body_segments,
        attachments=attachments,
        attachment_occurrences=attachment_occurrences,
        quoted_message_candidates=[],
        embedded_message_relations=[],
        mail_parse_run=parse_run,
        parse_warnings=warnings,
        created_at=resolved_created_at,
    )
    bundle.to_dict()
    return bundle


def _archive_occurrence(
    *,
    import_session: MailImportSession,
    archive_id: str,
    mailbox_id: str,
    created_at: str,
) -> MailArchiveOccurrence:
    occurrence_id = stable_resource_contract_id(
        "mailarchiveocc",
        "MailArchiveOccurrence",
        {
            "mail_import_session_id": import_session.mail_import_session_id,
            "source_asset_id": import_session.source_asset_id,
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "archive_sha256": import_session.archive_sha256,
        },
    )
    return MailArchiveOccurrence.from_dict(
        {
            "mail_archive_occurrence_id": occurrence_id,
            "mail_import_session_id": import_session.mail_import_session_id,
            "source_asset_id": import_session.source_asset_id,
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "archive_sha256": import_session.archive_sha256,
            "created_at": created_at,
        }
    )


def _validate_single_archive_mail_observations(
    observations: Sequence[Observation],
    *,
    archive_id: str,
    mailbox_id: str,
) -> None:
    for observation in observations:
        if _observation_location(observation, "archive_id") != archive_id:
            raise ContractValidationError("mail evidence bundle cannot mix archive_id values")
        if _observation_location(observation, "mailbox_id") != mailbox_id:
            raise ContractValidationError("mail evidence bundle cannot mix mailbox_id values")


def _parse_run(
    *,
    import_session: MailImportSession,
    extractor_run_id: str,
    parser_name: str,
    parser_version: str,
    started_at: str,
    completed_at: str,
    status: str,
) -> MailParseRun:
    config_hash = sha256_json(
        {
            "parser_name": parser_name,
            "parser_version": parser_version,
            "retention_policy": import_session.retention_policy,
        }
    )
    parse_run_id = stable_resource_contract_id(
        "mailparserun",
        "MailParseRun",
        {
            "mail_import_session_id": import_session.mail_import_session_id,
            "extractor_run_id": extractor_run_id,
            "parser_name": parser_name,
            "parser_version": parser_version,
            "input_hash": import_session.archive_sha256,
            "config_hash": config_hash,
        },
    )
    return MailParseRun.from_dict(
        {
            "mail_parse_run_id": parse_run_id,
            "mail_import_session_id": import_session.mail_import_session_id,
            "extractor_run_id": extractor_run_id,
            "parser_name": parser_name,
            "parser_version": parser_version,
            "input_hash": import_session.archive_sha256,
            "config_hash": config_hash,
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
        }
    )


def _folder_occurrences(
    observations: Sequence[Observation],
    archive_occurrence: MailArchiveOccurrence,
) -> list[MailFolderOccurrence]:
    folders: dict[str, MailFolderOccurrence] = {}
    for observation in observations:
        if observation.observation_type != "mail_folder_occurrence":
            continue
        folder_path_hash = _observation_location(observation, "folder_path_hash")
        folder_id = _folder_occurrence_id(
            archive_occurrence,
            folder_path_hash,
            observation.observation_id,
        )
        folders[folder_id] = MailFolderOccurrence.from_dict(
            {
                "mail_folder_occurrence_id": folder_id,
                "mail_archive_occurrence_id": archive_occurrence.mail_archive_occurrence_id,
                "archive_id": archive_occurrence.archive_id,
                "mailbox_id": archive_occurrence.mailbox_id,
                "folder_path_hash": folder_path_hash,
                "source_observation_id": observation.observation_id,
                "folder_label": observation.payload.get("folder_label")
                if observation.payload
                else observation.text,
            }
        )
    return sorted(folders.values(), key=lambda item: item.mail_folder_occurrence_id)


def _messages_and_occurrences(
    observations: Sequence[Observation],
    archive_occurrence: MailArchiveOccurrence,
) -> tuple[list[EmailMessage], list[EmailMessageOccurrence]]:
    message_records: dict[str, dict[str, Any]] = {}
    occurrences: list[EmailMessageOccurrence] = []
    for observation in observations:
        if observation.observation_type != "email_message":
            continue
        payload = observation.payload or {}
        fingerprint = _safe_payload_str(payload, "message_fingerprint") or sha256_json(
            {
                "message_id": _observation_location(observation, "message_id"),
                "normalized_subject": payload.get("normalized_subject"),
                "sender": payload.get("sender"),
                "sent_at": payload.get("sent_at"),
                "body_hash": payload.get("body_hash"),
            }
        )
        message_id = stable_resource_contract_id(
            "emailmsg",
            "EmailMessage",
            {"message_fingerprint": fingerprint},
        )
        record = message_records.setdefault(
            fingerprint,
            {
                "email_message_id": message_id,
                "message_fingerprint": fingerprint,
                "message_id": _observation_location(observation, "message_id"),
                "archive_id": archive_occurrence.archive_id,
                "mailbox_id": archive_occurrence.mailbox_id,
                "source_observation_ids": [],
                "subject": payload.get("subject"),
                "normalized_subject": payload.get("normalized_subject"),
                "sender": payload.get("sender"),
                "sent_at": payload.get("sent_at"),
                "body_hash": payload.get("body_hash"),
                "thread_id": payload.get("thread_id"),
                "fingerprint_policy": payload.get("fingerprint_policy")
                or "formowl_mail_fingerprint_v1",
                "source_body_char_count": payload.get("source_body_char_count"),
                "stored_body_char_count": payload.get("stored_body_char_count"),
                "body_segment_count": payload.get("body_segment_count"),
                "body_evidence_state": payload.get("body_evidence_state") or "unknown",
                "body_redacted_segment_count": payload.get("body_redacted_segment_count") or 0,
                "unresolved_attachment_count": payload.get("unresolved_attachment_count") or 0,
            },
        )
        record["source_observation_ids"].append(observation.observation_id)
        message_occurrence_id = _observation_location(observation, "message_occurrence_id")
        occurrences.append(
            EmailMessageOccurrence.from_dict(
                {
                    "email_message_occurrence_id": stable_resource_contract_id(
                        "emailmsgocc",
                        "EmailMessageOccurrence",
                        {
                            "mail_archive_occurrence_id": (
                                archive_occurrence.mail_archive_occurrence_id
                            ),
                            "message_occurrence_id": message_occurrence_id,
                        },
                    ),
                    "email_message_id": message_id,
                    "mail_archive_occurrence_id": (archive_occurrence.mail_archive_occurrence_id),
                    "message_occurrence_id": message_occurrence_id,
                    "message_id": record["message_id"],
                    "archive_id": archive_occurrence.archive_id,
                    "mailbox_id": archive_occurrence.mailbox_id,
                    "folder_path_hash": _observation_location(observation, "folder_path_hash"),
                    "source_observation_id": observation.observation_id,
                    "thread_id": payload.get("thread_id"),
                }
            )
        )
    messages = [
        EmailMessage.from_dict(
            {
                **record,
                "source_observation_ids": sorted(set(record["source_observation_ids"])),
            }
        )
        for record in message_records.values()
    ]
    return (
        sorted(messages, key=lambda item: item.email_message_id),
        sorted(occurrences, key=lambda item: item.email_message_occurrence_id),
    )


def _body_segments(
    observations: Sequence[Observation],
    message_ids_by_fingerprint: dict[str, str],
    message_ids_by_occurrence_id: dict[str, str],
) -> list[EmailBodySegment]:
    segments: dict[str, EmailBodySegment] = {}
    for observation in observations:
        if observation.observation_type not in {
            "email_body_segment",
            "email_attachment_text_segment",
        }:
            continue
        email_message_id = _email_message_id_for_observation(
            observation,
            message_ids_by_fingerprint,
            message_ids_by_occurrence_id,
        )
        message_occurrence_id = _observation_location(observation, "message_occurrence_id")
        text = _private_observation_text(observation)
        payload = observation.payload or {}
        segment_source_type = (
            "attachment_text"
            if observation.observation_type == "email_attachment_text_segment"
            else "message_body"
        )
        segment_index = (
            observation.location.get("attachment_text_segment_index")
            if segment_source_type == "attachment_text"
            else observation.location.get("body_segment_index")
        )
        body_segment_hash = sha256_json(
            {
                "email_message_id": email_message_id,
                "segment_source_type": segment_source_type,
                "attachment_id": observation.location.get("attachment_id"),
                "body_segment_index": segment_index,
                "text": text,
            }
        )
        segment_id = stable_resource_contract_id(
            "emailbodyseg",
            "EmailBodySegment",
            {
                "message_occurrence_id": message_occurrence_id,
                "body_segment_hash": body_segment_hash,
            },
        )
        segments.setdefault(
            segment_id,
            EmailBodySegment.from_dict(
                {
                    "email_body_segment_id": segment_id,
                    "email_message_id": email_message_id,
                    "message_occurrence_id": message_occurrence_id,
                    "source_observation_id": observation.observation_id,
                    "text": text,
                    "body_segment_hash": body_segment_hash,
                    "body_segment_index": segment_index,
                    "segment_source_type": segment_source_type,
                    "attachment_id": observation.location.get("attachment_id"),
                    "char_start": observation.location.get("char_start"),
                    "char_end": observation.location.get("char_end"),
                    "body_segment_count": payload.get("body_segment_count")
                    or payload.get("attachment_text_segment_count"),
                    "source_body_char_count": payload.get("source_body_char_count"),
                    "stored_body_char_count": payload.get("stored_body_char_count"),
                    "body_evidence_state": payload.get("body_evidence_state")
                    or payload.get("text_extraction_state")
                    or "unknown",
                    "content_publicly_unsafe": payload.get("content_publicly_unsafe") is True,
                }
            ),
        )
    return sorted(
        segments.values(),
        key=lambda item: (
            item.email_message_id,
            item.segment_source_type,
            item.attachment_id or "",
            item.body_segment_index or 0,
            item.email_body_segment_id,
        ),
    )


def _attachments(
    observations: Sequence[Observation],
    message_ids_by_fingerprint: dict[str, str],
    message_ids_by_occurrence_id: dict[str, str],
) -> tuple[list[EmailAttachment], list[EmailAttachmentOccurrence]]:
    attachments: dict[str, EmailAttachment] = {}
    occurrences: list[EmailAttachmentOccurrence] = []
    for observation in observations:
        if observation.observation_type != "email_attachment_occurrence":
            continue
        payload = observation.payload or {}
        content_hash = _safe_payload_str(payload, "content_hash")
        attachment_id_value = _safe_payload_str(payload, "attachment_id")
        attachment_fingerprint = content_hash or sha256_json(
            {
                "attachment_id": attachment_id_value,
                "filename": payload.get("filename"),
            }
        )
        email_attachment_id = stable_resource_contract_id(
            "emailatt",
            "EmailAttachment",
            {"attachment_fingerprint": attachment_fingerprint},
        )
        attachments.setdefault(
            email_attachment_id,
            EmailAttachment.from_dict(
                {
                    "email_attachment_id": email_attachment_id,
                    "attachment_fingerprint": attachment_fingerprint,
                    "filename": payload.get("filename") or attachment_id_value,
                    "mime_type": payload.get("mime_type"),
                    "content_hash": content_hash,
                    "size_bytes": payload.get("size_bytes"),
                }
            ),
        )
        email_message_id = _email_message_id_for_observation(
            observation,
            message_ids_by_fingerprint,
            message_ids_by_occurrence_id,
        )
        message_occurrence_id = _observation_location(observation, "message_occurrence_id")
        occurrence_id = stable_resource_contract_id(
            "emailattocc",
            "EmailAttachmentOccurrence",
            {
                "email_attachment_id": email_attachment_id,
                "message_occurrence_id": message_occurrence_id,
                "source_observation_id": observation.observation_id,
            },
        )
        occurrences.append(
            EmailAttachmentOccurrence.from_dict(
                {
                    "email_attachment_occurrence_id": occurrence_id,
                    "email_attachment_id": email_attachment_id,
                    "email_message_id": email_message_id,
                    "message_occurrence_id": message_occurrence_id,
                    "source_observation_id": observation.observation_id,
                    "attachment_id": attachment_id_value,
                    "attachment_index": observation.location.get("attachment_index"),
                }
            )
        )
    return (
        sorted(attachments.values(), key=lambda item: item.email_attachment_id),
        sorted(occurrences, key=lambda item: item.email_attachment_occurrence_id),
    )


def _parse_warnings(
    parse_run: MailParseRun,
    warnings: Sequence[str],
) -> list[MailParseWarning]:
    parsed: list[MailParseWarning] = []
    for index, warning in enumerate(warnings, start=1):
        message = safe_public_string(warning, "mail_parse_warning.message")
        warning_id = stable_resource_contract_id(
            "mailparsewarn",
            "MailParseWarning",
            {
                "mail_parse_run_id": parse_run.mail_parse_run_id,
                "warning_index": index,
                "message": message,
            },
        )
        parsed.append(
            MailParseWarning.from_dict(
                {
                    "mail_parse_warning_id": warning_id,
                    "mail_parse_run_id": parse_run.mail_parse_run_id,
                    "warning_code": f"parser_warning_{index}",
                    "message": message,
                }
            )
        )
    return parsed


def _email_message_id_for_observation(
    observation: Observation,
    message_ids_by_fingerprint: dict[str, str],
    message_ids_by_occurrence_id: dict[str, str],
) -> str:
    fingerprint = (observation.payload or {}).get("message_fingerprint")
    if isinstance(fingerprint, str) and fingerprint in message_ids_by_fingerprint:
        return message_ids_by_fingerprint[fingerprint]
    message_occurrence_id = observation.location.get("message_occurrence_id")
    if (
        isinstance(message_occurrence_id, str)
        and message_occurrence_id in message_ids_by_occurrence_id
    ):
        return message_ids_by_occurrence_id[message_occurrence_id]
    raise ContractValidationError("mail observation references unknown message_occurrence_id")


def _folder_occurrence_id(
    archive_occurrence: MailArchiveOccurrence,
    folder_path_hash: str,
    source_observation_id: str,
) -> str:
    return stable_resource_contract_id(
        "mailfolderocc",
        "MailFolderOccurrence",
        {
            "mail_archive_occurrence_id": archive_occurrence.mail_archive_occurrence_id,
            "folder_path_hash": folder_path_hash,
            "source_observation_id": source_observation_id,
        },
    )


def _observation_location(observation: Observation | None, field_name: str) -> str:
    if observation is None:
        raise ContractValidationError(f"mail observation missing location field: {field_name}")
    value = observation.location.get(field_name)
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"mail observation missing location field: {field_name}")
    return safe_public_string(value, field_name)


def _safe_payload_str(payload: dict[str, Any], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    return safe_public_string(value, field_name)


def _private_observation_text(observation: Observation) -> str:
    value = observation.text
    if not isinstance(value, str) or not value:
        raise ContractValidationError("email evidence segment text must be a non-empty string")
    return value


def _assert_private_observation_envelope_safe(value: Mapping[str, Any]) -> None:
    safe_view = dict(value)
    if safe_view.get("observation_type") in {
        "email_body_segment",
        "email_attachment_text_segment",
    }:
        safe_view["text"] = "[governed_private_mail_text]"
    assert_public_payload_safe(safe_view, "mail_evidence_bundle.observation_envelope")


def _assert_private_body_segment_envelope_safe(value: Mapping[str, Any]) -> None:
    safe_view = dict(value)
    safe_view["text"] = "[governed_private_mail_text]"
    assert_public_payload_safe(safe_view, "email_body_segment.private_envelope")


def _assert_private_mail_bundle_envelope_safe(value: Mapping[str, Any]) -> None:
    safe_view = dict(value)
    body_segments = value.get("body_segments")
    safe_view["body_segments"] = []
    assert_public_payload_safe(safe_view, "mail_evidence_bundle.private_envelope")
    if isinstance(body_segments, list):
        for segment in body_segments:
            if isinstance(segment, Mapping):
                _assert_private_body_segment_envelope_safe(segment)


def _public_payload(value: Any, context: str) -> dict[str, Any]:
    payload = to_plain(value)
    assert_public_payload_safe(payload, context)
    return payload


def _private_payload(value: Any) -> dict[str, Any]:
    payload = to_plain(value)
    if not isinstance(payload, dict):
        raise ContractValidationError("private mail evidence payload must be an object")
    return payload


def _require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{context} must be an object")
    assert_public_payload_safe(value, context)
    return value


def _require_private_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{context} must be an object")
    return value


def _required_str(value: dict[str, Any], field_name: str) -> str:
    item = value.get(field_name)
    if not isinstance(item, str) or not item:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return safe_public_string(item, field_name)


def _required_private_str(value: dict[str, Any], field_name: str) -> str:
    item = value.get(field_name)
    if not isinstance(item, str) or not item:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return item


def _optional_str(value: dict[str, Any], field_name: str) -> str | None:
    item = value.get(field_name)
    if item is None:
        return None
    text = safe_public_string(item, field_name)
    return text or None


def _required_choice(
    value: dict[str, Any],
    field_name: str,
    allowed: set[str],
) -> str:
    item = _required_str(value, field_name)
    if item not in allowed:
        raise ContractValidationError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")
    return item


def _optional_int(value: dict[str, Any], field_name: str) -> int | None:
    item = value.get(field_name)
    if item is None:
        return None
    if not isinstance(item, int) or isinstance(item, bool):
        raise ContractValidationError(f"{field_name} must be an integer")
    return item


def _optional_bool(value: dict[str, Any], field_name: str) -> bool | None:
    item = value.get(field_name)
    if item is None:
        return None
    if not isinstance(item, bool):
        raise ContractValidationError(f"{field_name} must be a boolean")
    return item


def _optional_float(value: dict[str, Any], field_name: str) -> float | None:
    item = value.get(field_name)
    if item is None:
        return None
    if not isinstance(item, (int, float)) or isinstance(item, bool):
        raise ContractValidationError(f"{field_name} must be numeric")
    return float(item)


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ContractValidationError("expected a list of strings")
    return [safe_public_string(item, "list_item") for item in value]


def _record_list(
    value: dict[str, Any],
    field_name: str,
    record_type: Any,
    *,
    required: bool = True,
) -> list[Any]:
    if field_name not in value:
        if required:
            raise ContractValidationError(f"{field_name} is required")
        return []
    items = value[field_name]
    if not isinstance(items, list):
        raise ContractValidationError(f"{field_name} must be a list")
    return [record_type.from_dict(item) for item in items]


def _from_required_fields(
    record_type: Any,
    value: dict[str, Any],
    context: str,
    fields: tuple[str, ...],
) -> Any:
    item = _require_dict(value, context)
    record = record_type(**{field_name: _required_str(item, field_name) for field_name in fields})
    record.to_dict()
    return record


__all__ = [
    "EmailAttachment",
    "EmailAttachmentOccurrence",
    "EmailBodySegment",
    "EmailMessage",
    "EmailMessageOccurrence",
    "EmbeddedMessageRelation",
    "MailArchiveOccurrence",
    "MailEvidenceBundle",
    "MailFolderOccurrence",
    "MailImportSession",
    "MailParseRun",
    "MailParseWarning",
    "QuotedMessageCandidate",
    "build_mail_evidence_bundle",
]
