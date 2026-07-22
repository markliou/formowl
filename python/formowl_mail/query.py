from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence

from formowl_contract import (
    ContractValidationError,
    Grant,
    redact_public_raw_references,
    sha256_json,
    to_plain,
)
from formowl_core import (
    configured_mail_candidate_admission_tokens,
    configured_mail_tokenizer_id,
)

from ._access import grant_expired, matching_bundles, normalize_grants
from ._guards import assert_public_payload_safe, safe_public_string
from .bundle import MailEvidenceBundle

MAIL_TOKENIZER_ID = configured_mail_tokenizer_id()
_MAIL_EVIDENCE_PERMISSIONS = {"read", "evidence_snippet", "mail_evidence_read"}
_SEMANTIC_GATEWAY_TEXT_REDACTIONS = (
    re.compile(r"\bwith\s+.+\s+as\s*\(", re.IGNORECASE),
    re.compile(r"\bcopy\s+.+\s+from\b", re.IGNORECASE),
    re.compile(r"\bTraceback \(most recent call last\):", re.IGNORECASE),
)
_PROTECTED_IDENTIFIER_TOKEN = re.compile(r"(?=.{5,}\Z)(?=.*\d)[a-z0-9_@.-]+\Z")


@dataclass(frozen=True)
class MailEvidenceQueryResult:
    status: str
    mail_import_session_id: str | None
    query_hash: str
    evidence_snippets: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    redaction_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    evidence_completeness: str = "unknown"
    answerability_state: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "mail_evidence_query_result")
        return payload


@dataclass(frozen=True)
class MailEvidenceReadResult:
    status: str
    mail_import_session_id: str | None
    evidence_segments: list[dict[str, Any]] = field(default_factory=list)
    redaction_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    evidence_completeness: str = "unknown"
    answerability_state: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "mail_evidence_read_result")
        return payload


@dataclass(frozen=True)
class _IndexedMailSnippet:
    mail_evidence_bundle_id: str
    searchable_tokens: set[str]
    payload: dict[str, Any]


@dataclass(frozen=True)
class _MailSnippetIndex:
    snippets: tuple[_IndexedMailSnippet, ...]
    snippet_indexes_by_token: dict[str, tuple[int, ...]]


class MailEvidenceQueryGateway:
    """Permission-checked query facade over normalized mail evidence bundles."""

    def __init__(self, bundles: Sequence[MailEvidenceBundle]) -> None:
        self._bundles = list(bundles)
        self._snippet_index_by_bundle_id = {
            bundle.mail_evidence_bundle_id: _build_snippet_index(bundle) for bundle in self._bundles
        }

    def query_mail_evidence(
        self,
        *,
        query_text: str,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
        grants: Sequence[Grant | dict[str, Any]] = (),
        limit: int = 5,
        now: str | None = None,
    ) -> MailEvidenceQueryResult:
        _validate_query_inputs(
            query_text=query_text,
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
            limit=limit,
        )
        query_hash = sha256_json(query_text)
        selected_bundles = matching_bundles(
            self._bundles,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
        )
        if not selected_bundles:
            return MailEvidenceQueryResult(
                status="not_found",
                mail_import_session_id=mail_import_session_id,
                query_hash=query_hash,
                redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
                warnings=["mail_evidence_not_found"],
                evidence_completeness="unknown",
                answerability_state="source_not_found",
            )

        resolved_now = now or "9999-12-31T23:59:59+00:00"
        grant_objects = normalize_grants(grants)
        visible_bundles = [
            bundle
            for bundle in selected_bundles
            if bundle.mail_import_session.workspace_id == workspace_id
            and _can_read_bundle(
                bundle,
                requester_user_id=requester_user_id,
                grants=grant_objects,
                now=resolved_now,
            )
        ]
        if not visible_bundles:
            return MailEvidenceQueryResult(
                status="permission_denied",
                mail_import_session_id=mail_import_session_id,
                query_hash=query_hash,
                redaction_counts={
                    "hidden_bundles": len(selected_bundles),
                    "hidden_messages": sum(len(bundle.messages) for bundle in selected_bundles),
                },
                warnings=["mail_evidence_permission_denied"],
                evidence_completeness="unknown",
                answerability_state="permission_denied",
            )

        source_completeness = _source_completeness(visible_bundles)
        snippets = _search_visible_bundles(
            visible_bundles,
            query_text=query_text,
            limit=limit,
            snippet_index_by_bundle_id=self._snippet_index_by_bundle_id,
        )
        if not snippets:
            return MailEvidenceQueryResult(
                status="ok",
                mail_import_session_id=(
                    visible_bundles[0].mail_import_session.mail_import_session_id
                ),
                query_hash=query_hash,
                redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
                warnings=["no_visible_mail_evidence_matched"],
                evidence_completeness=source_completeness,
                answerability_state=(
                    "target_not_found_in_complete_source"
                    if source_completeness == "complete"
                    else "source_incomplete"
                ),
            )
        citations = [_citation_for_snippet(snippet) for snippet in snippets]
        unsafe_snippet_count = sum(bool(snippet.get("content_redacted")) for snippet in snippets)
        return MailEvidenceQueryResult(
            status="ok",
            mail_import_session_id=visible_bundles[0].mail_import_session.mail_import_session_id,
            query_hash=query_hash,
            evidence_snippets=snippets,
            citations=citations,
            redaction_counts={
                "hidden_bundles": 0,
                "hidden_messages": 0,
                "unsafe_snippets": unsafe_snippet_count,
            },
            warnings=(["unsafe_mail_evidence_content_redacted"] if unsafe_snippet_count else []),
            evidence_completeness=_matched_evidence_completeness(snippets),
            answerability_state=(
                "evidence_found_complete"
                if _matched_evidence_completeness(snippets) == "complete"
                else "evidence_found_source_incomplete"
            ),
        )

    def read_mail_evidence(
        self,
        *,
        requester_user_id: str,
        workspace_id: str,
        session_id: str,
        mail_import_session_id: str | None = None,
        mail_evidence_bundle_id: str | None = None,
        source_observation_ids: Sequence[str] = (),
        email_message_ids: Sequence[str] = (),
        grants: Sequence[Grant | dict[str, Any]] = (),
        limit: int | None = None,
        now: str | None = None,
    ) -> MailEvidenceReadResult:
        _validate_read_inputs(
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            session_id=session_id,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
            source_observation_ids=source_observation_ids,
            email_message_ids=email_message_ids,
            limit=limit,
        )
        selected_bundles = matching_bundles(
            self._bundles,
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
        )
        if not selected_bundles:
            return MailEvidenceReadResult(
                status="not_found",
                mail_import_session_id=mail_import_session_id,
                warnings=["mail_evidence_not_found"],
                answerability_state="source_not_found",
            )
        resolved_now = now or "9999-12-31T23:59:59+00:00"
        grant_objects = normalize_grants(grants)
        visible_bundles = [
            bundle
            for bundle in selected_bundles
            if bundle.mail_import_session.workspace_id == workspace_id
            and _can_read_bundle(
                bundle,
                requester_user_id=requester_user_id,
                grants=grant_objects,
                now=resolved_now,
            )
        ]
        if not visible_bundles:
            return MailEvidenceReadResult(
                status="permission_denied",
                mail_import_session_id=mail_import_session_id,
                redaction_counts={
                    "hidden_bundles": len(selected_bundles),
                    "hidden_messages": sum(len(bundle.messages) for bundle in selected_bundles),
                },
                warnings=["mail_evidence_permission_denied"],
                answerability_state="permission_denied",
            )
        requested_observations = set(source_observation_ids)
        requested_messages = set(email_message_ids)
        segments: list[dict[str, Any]] = []
        for bundle in visible_bundles:
            message_by_id = {message.email_message_id: message for message in bundle.messages}
            for segment in bundle.body_segments:
                if (
                    segment.source_observation_id not in requested_observations
                    and segment.email_message_id not in requested_messages
                ):
                    continue
                message = message_by_id.get(segment.email_message_id)
                segments.append(_safe_snippet(_segment_payload(bundle, segment, message)))
        segments = sorted(
            segments,
            key=lambda item: (
                str(item["email_message_id"]),
                str(item.get("segment_source_type", "")),
                str(item.get("attachment_id", "")),
                int(item.get("body_segment_index") or 0),
                str(item["source_observation_id"]),
            ),
        )
        if not segments:
            return MailEvidenceReadResult(
                status="not_found",
                mail_import_session_id=visible_bundles[
                    0
                ].mail_import_session.mail_import_session_id,
                warnings=["requested_mail_evidence_not_found"],
                evidence_completeness=_source_completeness(visible_bundles),
                answerability_state="requested_evidence_not_found",
            )
        limit_reached = limit is not None and len(segments) > limit
        if limit is not None:
            segments = segments[:limit]
        unsafe_segment_count = sum(bool(item.get("content_redacted")) for item in segments)
        completeness = _matched_evidence_completeness(segments)
        return MailEvidenceReadResult(
            status="partial" if limit_reached else "ok",
            mail_import_session_id=visible_bundles[0].mail_import_session.mail_import_session_id,
            evidence_segments=segments,
            redaction_counts={"unsafe_segments": unsafe_segment_count},
            warnings=[
                *(["unsafe_mail_evidence_content_redacted"] if unsafe_segment_count else []),
                *(["mail_evidence_read_limit_reached"] if limit_reached else []),
            ],
            evidence_completeness="incomplete" if limit_reached else completeness,
            answerability_state=(
                "read_limit_reached"
                if limit_reached
                else (
                    "evidence_read_complete"
                    if completeness == "complete"
                    else "evidence_read_source_incomplete"
                )
            ),
        )


def build_mail_evidence_query_handler(
    bundles: Sequence[MailEvidenceBundle],
    *,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
) -> Any:
    gateway = MailEvidenceQueryGateway(bundles)
    trusted_grants = tuple(grants)

    def handler(input_data: dict[str, Any]) -> dict[str, Any]:
        result = gateway.query_mail_evidence(
            query_text=input_data.get("query_text", ""),
            requester_user_id=input_data.get("requester_user_id", ""),
            workspace_id=input_data.get("workspace_id", ""),
            session_id=input_data.get("session_id", "semantic_gateway_session"),
            mail_import_session_id=input_data.get("mail_import_session_id"),
            mail_evidence_bundle_id=input_data.get("mail_evidence_bundle_id"),
            grants=trusted_grants,
            limit=input_data.get("limit", 5),
            now=now,
        )
        return result.to_dict()

    return handler


def build_mail_evidence_read_handler(
    bundles: Sequence[MailEvidenceBundle],
    *,
    grants: Sequence[Grant | dict[str, Any]] = (),
    now: str | None = None,
) -> Any:
    gateway = MailEvidenceQueryGateway(bundles)
    trusted_grants = tuple(grants)

    def handler(input_data: dict[str, Any]) -> dict[str, Any]:
        result = gateway.read_mail_evidence(
            requester_user_id=input_data.get("requester_user_id", ""),
            workspace_id=input_data.get("workspace_id", ""),
            session_id=input_data.get("session_id", "semantic_gateway_session"),
            mail_import_session_id=input_data.get("mail_import_session_id"),
            mail_evidence_bundle_id=input_data.get("mail_evidence_bundle_id"),
            source_observation_ids=input_data.get("source_observation_ids", ()),
            email_message_ids=input_data.get("email_message_ids", ()),
            grants=trusted_grants,
            limit=input_data.get("limit"),
            now=now,
        )
        return result.to_dict()

    return handler


def _search_visible_bundles(
    bundles: Sequence[MailEvidenceBundle],
    *,
    query_text: str,
    limit: int | None,
    snippet_index_by_bundle_id: Mapping[str, _MailSnippetIndex] | None = None,
) -> list[dict[str, Any]]:
    terms = _tokenize(query_text)
    snippets: list[dict[str, Any]] = []
    for bundle in bundles:
        if snippet_index_by_bundle_id is None:
            snippet_index = _build_snippet_index(bundle)
        else:
            snippet_index = snippet_index_by_bundle_id.get(bundle.mail_evidence_bundle_id)
            if snippet_index is None:
                snippet_index = _build_snippet_index(bundle)
        candidate_indexes = _candidate_snippet_indexes(snippet_index, terms)
        for snippet_index_value in candidate_indexes:
            indexed = snippet_index.snippets[snippet_index_value]
            matched_terms = sorted(term for term in terms if term in indexed.searchable_tokens)
            if not matched_terms:
                continue
            snippets.append(
                _safe_snippet(
                    {
                        **indexed.payload,
                        "score": len(matched_terms),
                        "matched_terms": matched_terms,
                    }
                )
            )
    return sorted(
        snippets,
        key=lambda snippet: (-int(snippet["score"]), str(snippet["source_observation_id"])),
    )[:limit]


def _candidate_snippet_indexes(
    snippet_index: _MailSnippetIndex, terms: set[str]
) -> tuple[int, ...]:
    identifier_anchors = {term for term in terms if _PROTECTED_IDENTIFIER_TOKEN.fullmatch(term)}
    candidate_terms = identifier_anchors or terms
    indexes: set[int] = set()
    for term in candidate_terms:
        indexes.update(snippet_index.snippet_indexes_by_token.get(term, ()))
    return tuple(sorted(indexes))


def _build_snippet_index(bundle: MailEvidenceBundle) -> _MailSnippetIndex:
    messages_by_id = {message.email_message_id: message for message in bundle.messages}
    indexed: list[_IndexedMailSnippet] = []
    indexes_by_token: dict[str, list[int]] = {}
    for segment in bundle.body_segments:
        message = messages_by_id.get(segment.email_message_id)
        searchable = " ".join(
            item
            for item in (
                segment.text,
                message.subject if message else None,
                message.sender if message else None,
                message.message_id if message else None,
            )
            if isinstance(item, str)
        )
        tokens = _tokenize(searchable)
        if not tokens:
            continue
        snippet_index = len(indexed)
        indexed.append(
            _IndexedMailSnippet(
                mail_evidence_bundle_id=bundle.mail_evidence_bundle_id,
                searchable_tokens=tokens,
                payload={
                    **_segment_payload(bundle, segment, message),
                },
            )
        )
        for token in tokens:
            indexes_by_token.setdefault(token, []).append(snippet_index)
    return _MailSnippetIndex(
        snippets=tuple(indexed),
        snippet_indexes_by_token={
            token: tuple(indexes) for token, indexes in indexes_by_token.items()
        },
    )


def _segment_payload(bundle: MailEvidenceBundle, segment: Any, message: Any) -> dict[str, Any]:
    return {
        "source_type": (
            "mail_attachment_text_segment"
            if segment.segment_source_type == "attachment_text"
            else "mail_body_segment"
        ),
        "source_observation_id": segment.source_observation_id,
        "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
        "email_message_id": segment.email_message_id,
        "message_occurrence_id": segment.message_occurrence_id,
        "subject": message.subject if message else None,
        "snippet": segment.text,
        "segment_source_type": segment.segment_source_type,
        "attachment_id": segment.attachment_id,
        "body_segment_index": segment.body_segment_index,
        "body_segment_count": segment.body_segment_count,
        "source_body_char_count": segment.source_body_char_count,
        "stored_body_char_count": segment.stored_body_char_count,
        "body_evidence_state": (
            segment.body_evidence_state
            if segment.body_evidence_state != "unknown"
            else (message.body_evidence_state if message else "unknown")
        ),
        "unresolved_attachment_count": (message.unresolved_attachment_count if message else 0),
    }


def _source_completeness(bundles: Sequence[MailEvidenceBundle]) -> str:
    messages = [message for bundle in bundles for message in bundle.messages]
    if not messages:
        return "unknown"
    if any(
        message.body_evidence_state != "complete"
        or message.unresolved_attachment_count > 0
        or (
            message.source_body_char_count is not None
            and message.stored_body_char_count != message.source_body_char_count
        )
        for message in messages
    ):
        return "incomplete"
    return "complete"


def _matched_evidence_completeness(snippets: Sequence[Mapping[str, Any]]) -> str:
    if not snippets:
        return "unknown"
    if any(
        snippet.get("body_evidence_state") != "complete"
        or int(snippet.get("unresolved_attachment_count") or 0) > 0
        or (
            snippet.get("source_body_char_count") is not None
            and snippet.get("stored_body_char_count") != snippet.get("source_body_char_count")
        )
        for snippet in snippets
    ):
        return "incomplete"
    return "complete"


def _safe_snippet(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: value for key, value in payload.items() if value is not None}
    redaction_count = 0
    for field_name in ("subject", "snippet"):
        value = cleaned.get(field_name)
        if not isinstance(value, str):
            continue
        redacted, field_redaction_count = _redact_mail_public_text(value)
        cleaned[field_name] = redacted
        redaction_count += field_redaction_count
    if redaction_count:
        cleaned["content_redacted"] = True
    assert_public_payload_safe(cleaned, "mail_evidence_snippet")
    return cleaned


def _redact_mail_public_text(value: str) -> tuple[str, int]:
    redacted, count = redact_public_raw_references(value)
    for pattern in _SEMANTIC_GATEWAY_TEXT_REDACTIONS:
        redacted, replacement_count = pattern.subn("[redacted_mail_evidence]", redacted)
        count += replacement_count
    return redacted, count


def _citation_for_snippet(snippet: dict[str, Any]) -> dict[str, Any]:
    citation = {
        "citation_id": "mailcitation_"
        + sha256_json(
            {
                "mail_import_session_id": snippet["mail_import_session_id"],
                "source_observation_id": snippet["source_observation_id"],
            }
        )[-24:],
        "source_type": snippet["source_type"],
        "source_observation_id": snippet["source_observation_id"],
        "mail_import_session_id": snippet["mail_import_session_id"],
        "email_message_id": snippet["email_message_id"],
        "message_occurrence_id": snippet["message_occurrence_id"],
    }
    assert_public_payload_safe(citation, "mail_evidence_citation")
    return citation


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
        if grant.permission not in _MAIL_EVIDENCE_PERMISSIONS:
            continue
        if grant.revoked_at or grant_expired(grant, now):
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


def _validate_query_inputs(
    *,
    query_text: str,
    requester_user_id: str,
    workspace_id: str,
    session_id: str,
    mail_import_session_id: str | None,
    mail_evidence_bundle_id: str | None,
    limit: int,
) -> None:
    safe_public_string(query_text, "query_text")
    for field_name, value in (
        ("query_text", query_text),
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
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ContractValidationError("limit must be a non-negative integer")


def _validate_read_inputs(
    *,
    requester_user_id: str,
    workspace_id: str,
    session_id: str,
    mail_import_session_id: str | None,
    mail_evidence_bundle_id: str | None,
    source_observation_ids: Sequence[str],
    email_message_ids: Sequence[str],
    limit: int,
) -> None:
    for field_name, value in (
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
    if not source_observation_ids and not email_message_ids:
        raise ContractValidationError("source_observation_ids or email_message_ids is required")
    for field_name, values in (
        ("source_observation_ids", source_observation_ids),
        ("email_message_ids", email_message_ids),
    ):
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ContractValidationError(f"{field_name} must be a list")
        for value in values:
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"{field_name} must contain non-empty strings")
            safe_public_string(value, field_name)
    if mail_import_session_id is not None:
        safe_public_string(mail_import_session_id, "mail_import_session_id")
    if mail_evidence_bundle_id is not None:
        safe_public_string(mail_evidence_bundle_id, "mail_evidence_bundle_id")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
        raise ContractValidationError("limit must be a positive integer")


def _tokenize(value: str) -> set[str]:
    return configured_mail_candidate_admission_tokens(value)


__all__ = [
    "MailEvidenceQueryGateway",
    "MailEvidenceQueryResult",
    "MailEvidenceReadResult",
    "build_mail_evidence_query_handler",
    "build_mail_evidence_read_handler",
]
