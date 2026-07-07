from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Sequence

from formowl_contract import (
    ContractValidationError,
    Observation,
    now_iso,
    stable_resource_contract_id,
    to_plain,
)

from ._guards import assert_public_payload_safe, safe_public_string

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class MailBodySegment:
    observation_id: str
    text: str
    body_segment_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class MailEvidenceRecord:
    record_key: str
    observation_ids: list[str]
    archive_id: str
    mailbox_id: str
    folder_path_hash: str
    message_id: str
    thread_id: str | None = None
    subject: str | None = None
    normalized_subject: str | None = None
    sender: str | None = None
    sent_at: str | None = None
    message_fingerprint: str | None = None
    message_occurrence_id: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body_segments: list[MailBodySegment] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "mail_evidence_record")
        return payload


@dataclass(frozen=True)
class MailSearchResult:
    record_key: str
    score: int
    matched_terms: list[str]
    snippets: list[str]
    observation_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "mail_search_result")
        return payload


@dataclass(frozen=True)
class MailEvidencePack:
    mail_evidence_pack_id: str
    source_observation_ids: list[str]
    records: list[MailEvidenceRecord]
    query_index: dict[str, list[str]]
    created_at: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "mail_evidence_pack")
        return payload

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MailEvidencePack":
        if not isinstance(value, dict):
            raise ContractValidationError("MailEvidencePack must be an object")
        records = [
            MailEvidenceRecord(
                record_key=str(record["record_key"]),
                observation_ids=list(record["observation_ids"]),
                archive_id=str(record["archive_id"]),
                mailbox_id=str(record["mailbox_id"]),
                folder_path_hash=str(record["folder_path_hash"]),
                message_id=str(record["message_id"]),
                thread_id=record.get("thread_id"),
                subject=record.get("subject"),
                normalized_subject=record.get("normalized_subject"),
                sender=record.get("sender"),
                sent_at=record.get("sent_at"),
                message_fingerprint=record.get("message_fingerprint"),
                message_occurrence_id=record.get("message_occurrence_id"),
                headers=dict(record.get("headers", {})),
                body_segments=[
                    MailBodySegment(
                        observation_id=str(segment["observation_id"]),
                        text=str(segment["text"]),
                        body_segment_index=segment.get("body_segment_index"),
                    )
                    for segment in record.get("body_segments", [])
                ],
                attachments=list(record.get("attachments", [])),
            )
            for record in value.get("records", [])
        ]
        pack = cls(
            mail_evidence_pack_id=str(value["mail_evidence_pack_id"]),
            source_observation_ids=list(value["source_observation_ids"]),
            records=records,
            query_index={
                str(key): list(items) for key, items in value.get("query_index", {}).items()
            },
            created_at=str(value["created_at"]),
            warnings=list(value.get("warnings", [])),
        )
        assert_public_payload_safe(pack.to_dict(), "mail_evidence_pack")
        return pack


class MailEvidencePackStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir) / "mail" / "evidence-packs"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create(self, pack: MailEvidencePack | dict[str, Any]) -> MailEvidencePack:
        validated = pack if isinstance(pack, MailEvidencePack) else MailEvidencePack.from_dict(pack)
        _record_path(self.base_dir, validated.mail_evidence_pack_id)
        _write_json(
            _record_path(self.base_dir, validated.mail_evidence_pack_id), validated.to_dict()
        )
        return validated

    def get(self, mail_evidence_pack_id: str) -> MailEvidencePack | None:
        path = _record_path(self.base_dir, mail_evidence_pack_id)
        if not path.exists():
            return None
        return MailEvidencePack.from_dict(_read_json(path))

    def list(self) -> list[MailEvidencePack]:
        return [
            MailEvidencePack.from_dict(_read_json(path))
            for path in sorted(self.base_dir.glob("*.json"))
        ]


def build_mail_evidence_pack(
    observations: Sequence[Observation],
    *,
    created_at: str | None = None,
) -> MailEvidencePack:
    normalized = [Observation.from_dict(observation.to_dict()) for observation in observations]
    mail_observations = [
        observation for observation in normalized if observation.modality == "mail"
    ]
    records_by_key: dict[str, dict[str, Any]] = {}
    thread_messages: dict[str, set[str]] = {}
    warnings: list[str] = []

    for observation in mail_observations:
        if observation.observation_type == "email_thread":
            thread_id = _string_or_none(observation.location.get("thread_id"))
            message_ids = observation.payload.get("message_ids") if observation.payload else None
            if thread_id and isinstance(message_ids, list):
                thread_messages[thread_id] = {str(message_id) for message_id in message_ids}
            continue
        if observation.observation_type not in {
            "email_message",
            "email_header",
            "email_body_segment",
            "email_attachment_occurrence",
        }:
            continue
        key = _message_record_key(observation)
        record = records_by_key.setdefault(key, _empty_record(key, observation))
        _merge_observation(record, observation)

    records = [_final_record(record, thread_messages) for record in records_by_key.values()]
    source_observation_ids = sorted(observation.observation_id for observation in mail_observations)
    if not records:
        warnings.append("no_mail_evidence_records")
    query_index = {record.record_key: _query_terms(record) for record in records}
    pack_id = _stable_mail_evidence_pack_id(
        "MailEvidencePack",
        {
            "source_observation_ids": source_observation_ids,
            "record_keys": [record.record_key for record in records],
            "query_index": query_index,
        },
    )
    return MailEvidencePack(
        mail_evidence_pack_id=pack_id,
        source_observation_ids=source_observation_ids,
        records=records,
        query_index=query_index,
        created_at=created_at or now_iso(),
        warnings=warnings,
    )


def search_mail_evidence(
    pack: MailEvidencePack,
    *,
    query: str,
    limit: int = 5,
) -> list[MailSearchResult]:
    if not isinstance(query, str) or not query.strip():
        raise ContractValidationError("query must be a non-empty string")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ContractValidationError("limit must be a non-negative integer")
    terms = _tokenize(query)
    results: list[MailSearchResult] = []
    records_by_key = {record.record_key: record for record in pack.records}
    for record_key, indexed_terms in pack.query_index.items():
        matched_terms = sorted(term for term in terms if term in indexed_terms)
        if not matched_terms:
            continue
        record = records_by_key[record_key]
        snippets = [
            segment.text
            for segment in record.body_segments
            if any(term in _tokenize(segment.text) for term in matched_terms)
        ][:3]
        if not snippets and record.subject:
            snippets = [record.subject]
        results.append(
            MailSearchResult(
                record_key=record_key,
                score=len(matched_terms),
                matched_terms=matched_terms,
                snippets=snippets,
                observation_ids=list(record.observation_ids),
            )
        )
    return sorted(results, key=lambda result: (-result.score, result.record_key))[:limit]


def _empty_record(record_key: str, observation: Observation) -> dict[str, Any]:
    return {
        "record_key": record_key,
        "observation_ids": [],
        "archive_id": _required_location(observation, "archive_id"),
        "mailbox_id": _required_location(observation, "mailbox_id"),
        "folder_path_hash": _required_location(observation, "folder_path_hash"),
        "message_id": _required_location(observation, "message_id"),
        "thread_id": _string_or_none(observation.location.get("thread_id")),
        "headers": {},
        "body_segments": [],
        "attachments": [],
    }


def _merge_observation(record: dict[str, Any], observation: Observation) -> None:
    record["observation_ids"].append(observation.observation_id)
    payload = observation.payload or {}
    if observation.observation_type == "email_message":
        for key in (
            "subject",
            "normalized_subject",
            "sender",
            "sent_at",
            "message_fingerprint",
            "message_occurrence_id",
            "thread_id",
        ):
            if payload.get(key) is not None:
                record[key] = _safe_string(payload[key], key)
    elif observation.observation_type == "email_header":
        header_name = _safe_string(payload.get("header_name"), "header_name")
        header_value = _safe_string(payload.get("header_value"), "header_value")
        record["headers"][header_name] = header_value
    elif observation.observation_type == "email_body_segment":
        record["body_segments"].append(
            MailBodySegment(
                observation_id=observation.observation_id,
                text=_safe_string(observation.text or "", "body_segment"),
                body_segment_index=observation.location.get("body_segment_index"),
            )
        )
    elif observation.observation_type == "email_attachment_occurrence":
        record["attachments"].append(
            {
                "observation_id": observation.observation_id,
                "attachment_id": _safe_string(payload.get("attachment_id"), "attachment_id"),
                "filename": _safe_string(payload.get("filename"), "filename"),
                "mime_type": _safe_string(payload.get("mime_type"), "mime_type"),
                "content_hash": _safe_string(payload.get("content_hash"), "content_hash"),
                "size_bytes": payload.get("size_bytes"),
            }
        )


def _final_record(
    record: dict[str, Any],
    thread_messages: dict[str, set[str]],
) -> MailEvidenceRecord:
    thread_id = record.get("thread_id")
    if thread_id and record["message_id"] not in thread_messages.get(
        thread_id, {record["message_id"]}
    ):
        record["thread_id"] = None
    record["observation_ids"] = sorted(set(record["observation_ids"]))
    return MailEvidenceRecord(**record)


def _message_record_key(observation: Observation) -> str:
    return stable_resource_contract_id(
        "mailrecord",
        "MailEvidenceRecord",
        {
            "archive_id": _required_location(observation, "archive_id"),
            "mailbox_id": _required_location(observation, "mailbox_id"),
            "folder_path_hash": _required_location(observation, "folder_path_hash"),
            "message_id": _required_location(observation, "message_id"),
            "message_occurrence_id": observation.location.get("message_occurrence_id")
            or (observation.payload or {}).get("message_occurrence_id"),
        },
    )


def _query_terms(record: MailEvidenceRecord) -> list[str]:
    values = [
        record.subject,
        record.normalized_subject,
        record.sender,
        record.message_id,
        record.thread_id,
        *record.headers.keys(),
        *record.headers.values(),
        *(segment.text for segment in record.body_segments),
        *(attachment.get("filename") for attachment in record.attachments),
    ]
    terms: set[str] = set()
    for value in values:
        if isinstance(value, str):
            terms.update(_tokenize(value))
    return sorted(terms)


def _tokenize(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-zA-Z0-9_@.-]+", value.lower()) if token}


def _required_location(observation: Observation, field_name: str) -> str:
    value = observation.location.get(field_name)
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"mail observation missing location field: {field_name}")
    return value


def _safe_string(value: Any, field_name: str) -> str:
    return safe_public_string(value, field_name)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return _safe_string(value, "value")


def _record_path(base_dir: Path, record_id: str) -> Path:
    if not isinstance(record_id, str) or not _SAFE_RECORD_ID.fullmatch(record_id):
        raise ValueError("mail_evidence_pack_id must be a safe file name")
    return base_dir / f"{record_id}.json"


def _stable_mail_evidence_pack_id(contract_name: str, payload: Any) -> str:
    pack_id = stable_resource_contract_id("mailpack", contract_name, payload)
    if not _SAFE_RECORD_ID.fullmatch(pack_id):
        raise ContractValidationError(
            "mail_evidence_pack_id generator produced an unsafe file name"
        )
    return pack_id


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
    "MailBodySegment",
    "MailEvidencePack",
    "MailEvidencePackStore",
    "MailEvidenceRecord",
    "MailSearchResult",
    "build_mail_evidence_pack",
    "search_mail_evidence",
]
