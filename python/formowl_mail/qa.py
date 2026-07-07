from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from formowl_contract import (
    ContractValidationError,
    Grant,
    now_iso,
    stable_resource_contract_id,
    to_plain,
)

from ._guards import assert_public_payload_safe, safe_public_string
from .bundle import MailEvidenceBundle
from .evidence import (
    MailBodySegment,
    MailEvidencePack,
    MailEvidenceRecord,
    _stable_mail_evidence_pack_id,
)

_MAIL_CASE_PROGRESS_PERMISSIONS = {"read", "evidence_snippet", "mail_evidence_read"}
_FORBIDDEN_TRUE_CLAIMS = {
    "supports_actual_chatgpt_connected_upload_claim",
    "supports_upload_ui_claim",
    "supports_production_iframe_readiness_claim",
    "supports_real_pst_parser_claim",
    "supports_live_postgresql_readiness_claim",
    "supports_production_worker_leasing_claim",
    "supports_kg_write_claim",
    "supports_wiki_projection_claim",
    "supports_production_ready_claim",
}


@dataclass(frozen=True)
class CaseProgressItem:
    text: str
    message_id: str
    observation_id: str
    sent_at: str | None = None
    sender: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "case_progress_item")
        return payload


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
        payload = to_plain(self)
        assert_public_payload_safe(payload, "case_progress_answer")
        return payload


@dataclass(frozen=True)
class MailCaseProgressAnswerResult:
    status: str
    mail_import_session_id: str | None
    mail_evidence_bundle_id: str | None
    case_id: str | None
    latest_updates: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    responsible_parties: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[dict[str, Any]] = field(default_factory=list)
    deadlines: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    redaction_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    claim_boundary: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "mail_case_progress_answer_result")
        return payload


class MailCaseProgressGateway:
    """Permission-checked case-progress read model over mail evidence bundles."""

    def __init__(self, bundles: Sequence[MailEvidenceBundle]) -> None:
        self._bundles = list(bundles)

    def answer_case_progress(
        self,
        *,
        case_id: str,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
        grants: Sequence[Grant | dict[str, Any]] = (),
        generated_at: str | None = None,
        now: str | None = None,
    ) -> MailCaseProgressAnswerResult:
        _validate_case_progress_inputs(
            case_id=case_id,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
        )
        matching_bundles = self._matching_bundles(
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
        )
        if not matching_bundles:
            return MailCaseProgressAnswerResult(
                status="not_found",
                mail_import_session_id=mail_import_session_id,
                mail_evidence_bundle_id=mail_evidence_bundle_id,
                case_id=safe_public_string(case_id.strip(), "case_id"),
                redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
                warnings=["mail_case_progress_not_found"],
                claim_boundary=_case_progress_claim_boundary(False),
            )

        resolved_now = now or "9999-12-31T23:59:59+00:00"
        grant_objects = _normalize_grants(grants)
        visible_bundles = [
            bundle
            for bundle in matching_bundles
            if bundle.mail_import_session.workspace_id == workspace_id
            and _can_read_bundle(
                bundle,
                requester_user_id=requester_user_id,
                grants=grant_objects,
                now=resolved_now,
            )
        ]
        if not visible_bundles:
            return MailCaseProgressAnswerResult(
                status="permission_denied",
                mail_import_session_id=mail_import_session_id,
                mail_evidence_bundle_id=mail_evidence_bundle_id,
                case_id=safe_public_string(case_id.strip(), "case_id"),
                redaction_counts={
                    "hidden_bundles": len(matching_bundles),
                    "hidden_messages": sum(len(bundle.messages) for bundle in matching_bundles),
                },
                warnings=["mail_case_progress_permission_denied"],
                claim_boundary=_case_progress_claim_boundary(False),
            )

        bundle = visible_bundles[0]
        pack = _mail_evidence_pack_from_bundle(bundle)
        answer = build_case_progress_answer(
            pack,
            case_id=case_id,
            generated_at=generated_at or now_iso(),
        ).to_dict()
        return MailCaseProgressAnswerResult(
            status="ok",
            mail_import_session_id=bundle.mail_import_session.mail_import_session_id,
            mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
            case_id=answer["case_id"],
            latest_updates=answer["latest_updates"],
            blockers=answer["blockers"],
            responsible_parties=answer["responsible_parties"],
            next_actions=answer["next_actions"],
            deadlines=answer["deadlines"],
            citations=answer["citations"],
            redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
            warnings=answer["warnings"],
            claim_boundary=_case_progress_claim_boundary(True),
        )

    def _matching_bundles(
        self,
        *,
        mail_import_session_id: str | None,
        mail_evidence_bundle_id: str | None,
    ) -> list[MailEvidenceBundle]:
        matching: list[MailEvidenceBundle] = []
        for bundle in self._bundles:
            if (
                mail_import_session_id is not None
                and bundle.mail_import_session.mail_import_session_id != mail_import_session_id
            ):
                continue
            if (
                mail_evidence_bundle_id is not None
                and bundle.mail_evidence_bundle_id != mail_evidence_bundle_id
            ):
                continue
            matching.append(bundle)
        return matching


def build_mail_case_progress_handler(
    bundles: Sequence[MailEvidenceBundle],
    *,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
    generated_at: str | None = None,
) -> Any:
    gateway = MailCaseProgressGateway(bundles)
    trusted_grants = tuple(grants)

    def handler(input_data: dict[str, Any]) -> dict[str, Any]:
        result = gateway.answer_case_progress(
            case_id=input_data.get("case_id", ""),
            requester_user_id=input_data.get("requester_user_id", ""),
            workspace_id=input_data.get("workspace_id", ""),
            session_id=input_data.get("session_id", "semantic_gateway_session"),
            mail_import_session_id=input_data.get("mail_import_session_id"),
            mail_evidence_bundle_id=input_data.get("mail_evidence_bundle_id"),
            grants=trusted_grants,
            generated_at=generated_at,
            now=now,
        )
        return result.to_dict()

    return handler


def build_case_progress_answer(
    pack: MailEvidencePack,
    *,
    case_id: str,
    generated_at: str | None = None,
) -> CaseProgressAnswer:
    if not isinstance(case_id, str) or not case_id.strip():
        raise ContractValidationError("case_id must be a non-empty string")
    resolved_case_id = safe_public_string(case_id.strip(), "case_id")
    pack.to_dict()
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
        case_id=resolved_case_id,
        generated_at=resolved_generated_at,
        latest_updates=latest_updates,
        blockers=blockers,
        responsible_parties=responsible_parties,
        next_actions=next_actions,
        deadlines=deadlines,
        citations=citations,
        warnings=warnings,
    )


def _mail_evidence_pack_from_bundle(bundle: MailEvidenceBundle) -> MailEvidencePack:
    messages_by_id = {message.email_message_id: message for message in bundle.messages}
    occurrences_by_key = {
        (occurrence.email_message_id, occurrence.message_occurrence_id): occurrence
        for occurrence in bundle.message_occurrences
    }
    records: list[MailEvidenceRecord] = []
    for segment in bundle.body_segments:
        message = messages_by_id.get(segment.email_message_id)
        occurrence = occurrences_by_key.get(
            (segment.email_message_id, segment.message_occurrence_id)
        )
        if message is None or occurrence is None:
            raise ContractValidationError(
                "mail case-progress bundle has incomplete message lineage"
            )
        record_key = stable_resource_contract_id(
            "mailrecord",
            "MailCaseProgressRecord",
            {
                "mail_import_session_id": (bundle.mail_import_session.mail_import_session_id),
                "email_message_id": segment.email_message_id,
                "message_occurrence_id": segment.message_occurrence_id,
            },
        )
        records.append(
            MailEvidenceRecord(
                record_key=record_key,
                observation_ids=[segment.source_observation_id],
                archive_id=message.archive_id,
                mailbox_id=message.mailbox_id,
                folder_path_hash=occurrence.folder_path_hash,
                message_id=message.message_id,
                thread_id=message.thread_id or occurrence.thread_id,
                subject=message.subject,
                normalized_subject=message.normalized_subject,
                sender=message.sender,
                sent_at=message.sent_at,
                message_fingerprint=message.message_fingerprint,
                message_occurrence_id=segment.message_occurrence_id,
                body_segments=[
                    MailBodySegment(
                        observation_id=segment.source_observation_id,
                        text=segment.text,
                        body_segment_index=segment.body_segment_index,
                    )
                ],
            )
        )
    source_observation_ids = sorted(
        {segment.source_observation_id for segment in bundle.body_segments}
    )
    pack = MailEvidencePack(
        mail_evidence_pack_id=_stable_mail_evidence_pack_id(
            "MailCaseProgressPack",
            {
                "mail_evidence_bundle_id": bundle.mail_evidence_bundle_id,
                "source_observation_ids": source_observation_ids,
            },
        ),
        source_observation_ids=source_observation_ids,
        records=records,
        query_index={record.record_key: [] for record in records},
        created_at=bundle.created_at,
        warnings=[] if records else ["no_mail_evidence_records"],
    )
    pack.to_dict()
    return pack


def _can_read_bundle(
    bundle: MailEvidenceBundle,
    *,
    requester_user_id: str,
    grants: Sequence[Grant],
    now: str,
) -> bool:
    if requester_user_id == bundle.mail_import_session.owner_user_id:
        return True
    for grant in grants:
        if grant.owner_user_id != bundle.mail_import_session.owner_user_id:
            continue
        if grant.grantee_user_id != requester_user_id:
            continue
        if grant.permission not in _MAIL_CASE_PROGRESS_PERMISSIONS:
            continue
        if grant.revoked_at or _grant_expired(grant, now):
            continue
        if (
            grant.scope_type == "workspace"
            and grant.scope_id == bundle.mail_import_session.workspace_id
        ):
            return True
        if (
            grant.scope_type == "mail_import_session"
            and grant.scope_id == bundle.mail_import_session.mail_import_session_id
        ):
            return True
    return False


def _grant_expired(grant: Grant, now: str) -> bool:
    try:
        expires = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        return True
    return expires <= current


def _normalize_grants(grants: Sequence[Grant | dict[str, Any]]) -> list[Grant]:
    if isinstance(grants, (str, bytes)) or not isinstance(grants, Sequence):
        raise ContractValidationError("grants must be a list")
    return [grant if isinstance(grant, Grant) else Grant.from_dict(grant) for grant in grants]


def _validate_case_progress_inputs(
    *,
    case_id: str,
    requester_user_id: str,
    workspace_id: str,
    session_id: str,
    mail_import_session_id: str | None,
    mail_evidence_bundle_id: str | None,
) -> None:
    for field_name, value in (
        ("case_id", case_id),
        ("requester_user_id", requester_user_id),
        ("workspace_id", workspace_id),
        ("session_id", session_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(f"{field_name} is required")
        safe_public_string(value, field_name)
    if not mail_import_session_id and not mail_evidence_bundle_id:
        raise ContractValidationError(
            "mail_import_session_id or mail_evidence_bundle_id is required"
        )
    if mail_import_session_id is not None:
        safe_public_string(mail_import_session_id, "mail_import_session_id")
    if mail_evidence_bundle_id is not None:
        safe_public_string(mail_evidence_bundle_id, "mail_evidence_bundle_id")


def _case_progress_claim_boundary(supported: bool) -> dict[str, bool]:
    claims = {
        "supports_mail_case_progress_answer_claim": supported,
        "supports_actual_chatgpt_connected_upload_claim": False,
        "supports_upload_ui_claim": False,
        "supports_production_iframe_readiness_claim": False,
        "supports_real_pst_parser_claim": False,
        "supports_live_postgresql_readiness_claim": False,
        "supports_production_worker_leasing_claim": False,
        "supports_kg_write_claim": False,
        "supports_wiki_projection_claim": False,
        "supports_production_ready_claim": False,
    }
    if any(claims[key] for key in _FORBIDDEN_TRUE_CLAIMS):
        raise ContractValidationError("case-progress result overclaims unsupported work")
    return claims


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
    "MailCaseProgressAnswerResult",
    "MailCaseProgressGateway",
    "build_case_progress_answer",
    "build_mail_case_progress_handler",
]
