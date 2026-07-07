from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from formowl_contract import ContractValidationError, now_iso, to_plain

from .evidence import MailEvidencePack, MailEvidenceRecord


@dataclass(frozen=True)
class CaseProgressItem:
    text: str
    message_id: str
    observation_id: str
    sent_at: str | None = None
    sender: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True)
class CaseProgressAnswer:
    case_id: str
    generated_at: str
    latest_updates: list[CaseProgressItem] = field(default_factory=list)
    blockers: list[CaseProgressItem] = field(default_factory=list)
    responsible_parties: list[CaseProgressItem] = field(default_factory=list)
    next_actions: list[CaseProgressItem] = field(default_factory=list)
    deadlines: list[CaseProgressItem] = field(default_factory=list)
    citations: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


def build_case_progress_answer(
    pack: MailEvidencePack,
    *,
    case_id: str,
    generated_at: str | None = None,
) -> CaseProgressAnswer:
    if not isinstance(case_id, str) or not case_id.strip():
        raise ContractValidationError("case_id must be a non-empty string")
    resolved_generated_at = generated_at or now_iso()
    latest_updates: list[CaseProgressItem] = []
    blockers: list[CaseProgressItem] = []
    responsible_parties: list[CaseProgressItem] = []
    next_actions: list[CaseProgressItem] = []
    deadlines: list[CaseProgressItem] = []

    for record in sorted(pack.records, key=lambda item: item.sent_at or "", reverse=True):
        for observation_id, marker, text in _case_lines(record):
            item = CaseProgressItem(
                text=text,
                message_id=record.message_id,
                observation_id=observation_id,
                sent_at=record.sent_at,
                sender=record.sender,
            )
            if marker == "update":
                latest_updates.append(item)
            elif marker == "blocker":
                blockers.append(item)
            elif marker == "responsible_party":
                responsible_parties.append(item)
            elif marker == "next_action":
                next_actions.append(item)
            elif marker == "deadline":
                deadlines.append(item)

    citations = _citations(
        [
            *latest_updates,
            *blockers,
            *responsible_parties,
            *next_actions,
            *deadlines,
        ]
    )
    warnings: list[str] = []
    if not citations:
        warnings.append("no_case_progress_evidence")
    return CaseProgressAnswer(
        case_id=case_id,
        generated_at=resolved_generated_at,
        latest_updates=latest_updates,
        blockers=blockers,
        responsible_parties=responsible_parties,
        next_actions=next_actions,
        deadlines=deadlines,
        citations=citations,
        warnings=warnings,
    )


def _case_lines(record: MailEvidenceRecord) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    for segment in record.body_segments:
        for line in segment.text.splitlines():
            marker_text, separator, text = line.partition(":")
            if not separator:
                continue
            marker = _marker(marker_text)
            if marker is None:
                continue
            text = text.strip()
            if text:
                items.append((segment.observation_id, marker, text))
    return items


def _marker(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in {"update", "status"}:
        return "update"
    if normalized == "blocker":
        return "blocker"
    if normalized in {"owner", "responsible"}:
        return "responsible_party"
    if normalized in {"next action", "action item"}:
        return "next_action"
    if normalized == "deadline":
        return "deadline"
    return None


def _citations(items: list[CaseProgressItem]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    citations: list[dict[str, str]] = []
    for item in items:
        key = (item.observation_id, item.message_id)
        if key in seen:
            continue
        seen.add(key)
        citation = {
            "observation_id": item.observation_id,
            "message_id": item.message_id,
        }
        if item.sent_at:
            citation["sent_at"] = item.sent_at
        if item.sender:
            citation["sender"] = item.sender
        citations.append(citation)
    return citations


__all__ = [
    "CaseProgressAnswer",
    "CaseProgressItem",
    "build_case_progress_answer",
]
