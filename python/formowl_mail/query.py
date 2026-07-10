from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Mapping, Sequence

from formowl_contract import (
    ContractValidationError,
    Grant,
    redact_public_raw_references,
    sha256_json,
    to_plain,
)

from ._guards import assert_public_payload_safe, safe_public_string
from .bundle import MailEvidenceBundle

_MAIL_EVIDENCE_PERMISSIONS = {"read", "evidence_snippet", "mail_evidence_read"}
_SEMANTIC_GATEWAY_TEXT_REDACTIONS = (
    re.compile(r"\bwith\s+.+\s+as\s*\(", re.IGNORECASE),
    re.compile(r"\bcopy\s+.+\s+from\b", re.IGNORECASE),
    re.compile(r"\bTraceback \(most recent call last\):", re.IGNORECASE),
)


@dataclass(frozen=True)
class MailEvidenceQueryResult:
    status: str
    mail_import_session_id: str | None
    query_hash: str
    evidence_snippets: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    redaction_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = to_plain(self)
        assert_public_payload_safe(payload, "mail_evidence_query_result")
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
        matching_bundles = self._matching_bundles(
            mail_import_session_id=mail_import_session_id,
            mail_evidence_bundle_id=mail_evidence_bundle_id,
        )
        if not matching_bundles:
            return MailEvidenceQueryResult(
                status="not_found",
                mail_import_session_id=mail_import_session_id,
                query_hash=query_hash,
                redaction_counts={"hidden_bundles": 0, "hidden_messages": 0},
                warnings=["mail_evidence_not_found"],
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
            return MailEvidenceQueryResult(
                status="permission_denied",
                mail_import_session_id=mail_import_session_id,
                query_hash=query_hash,
                redaction_counts={
                    "hidden_bundles": len(matching_bundles),
                    "hidden_messages": sum(len(bundle.messages) for bundle in matching_bundles),
                },
                warnings=["mail_evidence_permission_denied"],
            )

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


def _search_visible_bundles(
    bundles: Sequence[MailEvidenceBundle],
    *,
    query_text: str,
    limit: int,
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
    indexes: set[int] = set()
    for term in terms:
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
                    "source_type": "mail_body_segment",
                    "source_observation_id": segment.source_observation_id,
                    "mail_import_session_id": bundle.mail_import_session.mail_import_session_id,
                    "email_message_id": segment.email_message_id,
                    "message_occurrence_id": segment.message_occurrence_id,
                    "subject": message.subject if message else None,
                    "snippet": segment.text,
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


def _tokenize(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-zA-Z0-9_@.-]+", value.lower()) if token}


__all__ = [
    "MailEvidenceQueryGateway",
    "MailEvidenceQueryResult",
    "build_mail_evidence_query_handler",
]
