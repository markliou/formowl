from __future__ import annotations

import re
from typing import Any

from formowl_contract import (
    ContractValidationError,
    assert_no_public_raw_references,
    safe_public_string,
)

_AUTHORIZED_EVIDENCE_SCALAR_FIELDS = frozenset(
    {
        "assistant_text",
        "normalized_subject",
        "sender",
        "snippet",
        "subject",
        "text",
    }
)
_AUTHORIZED_EVIDENCE_SEQUENCE_FIELDS = frozenset(
    {
        "matched_required_terms",
        "matched_terms",
    }
)
_SECRET_ASSIGNMENT_TEXT = re.compile(
    r"\b(?:"
    r"access[_-]?key|access[_-]?token|api[_-]?key|auth[_-]?token|"
    r"authorization|bearer[_-]?token|client[_-]?secret|credential|"
    r"password|passwd|private[_-]?key|pwd|refresh[_-]?token|"
    r"secret|secret[_-]?key|token"
    r")\s*[:=]\s*(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|\S+)",
    re.IGNORECASE,
)
_AUTHORIZATION_CREDENTIAL_TEXT = re.compile(
    r"\bauthorization\s*:\s*(?:(?:bearer|basic|digest|token|apikey)\s+)?\S+"
    r"|\bbearer\s+[A-Za-z0-9._~+/-]{8,}",
    re.IGNORECASE,
)
_URL_USERINFO_TOKEN = re.compile(
    r"\b[A-Za-z][A-Za-z0-9+.-]*://[^/\s@]+@[^\s'\"<>]*",
    re.IGNORECASE,
)
_INTERNAL_FORMOWL_LOCATOR_TOKEN = re.compile(
    r"\bformowl://(?:object|storage|backend|scratch|raw)(?:/|$)[^\s'\"<>]*",
    re.IGNORECASE,
)
_BACKEND_LOCATOR_TOKEN = re.compile(
    r"\b(?:"
    r"file|s3|gs|gcs|minio|object|webdav|dav|smb|nfs|"
    r"postgres(?:ql)?|mysql|mariadb|sqlite|mssql|sqlserver|oracle|"
    r"redis(?:s)?|mongodb(?:\+srv)?|amqp|rabbitmq|kafka|"
    r"imap(?:s)?|smtp(?:s)?|pop3(?:s)?|mapi|ews"
    r")://[^\s'\"<>]+",
    re.IGNORECASE,
)
_INTERNAL_POSIX_PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9._-])(?:"
    r"/(?:srv|opt)/formowl(?:/[^\s'\"<>]*)?|"
    r"/var/(?:lib|run|log)/formowl(?:/[^\s'\"<>]*)?|"
    r"/tmp(?:/[^\s'\"<>]*)?|"
    r"/workspace(?:/[^\s'\"<>]*)?|"
    r"/home/[^/\s]+/formowl(?:/[^\s'\"<>]*)?|"
    r"\.formowl(?:/[^\s'\"<>]*)?"
    r")",
    re.IGNORECASE,
)
_INTERNAL_WINDOWS_PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9._-])(?:"
    r"[A-Za-z]:\\(?:tmp|formowl)(?:\\[^\s'\"<>]*)?|"
    r"\\\\[^\s'\"<>]+"
    r")",
    re.IGNORECASE,
)
_TRACEBACK_BLOCK = re.compile(
    r"(?ms)^Traceback \(most recent call last\):.*?(?=^\s*$|\Z)",
)
_SQL_TEXT_PATTERNS = (
    re.compile(
        r"\bselect\b[^\r\n;]{0,300}?\bfrom\b\s+"
        r"(?:[A-Za-z_][A-Za-z0-9_.]*|\"[^\r\n\"]+\"|'[^\r\n']+')",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwith\s+[A-Za-z_][A-Za-z0-9_]*" r"(?:\s*\([^)\r\n]{0,200}\))?\s+as\s*\(",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bcopy\s+"
        r"(?:[A-Za-z_][A-Za-z0-9_.]*(?:\s*\([^\r\n)]{0,200}\))?"
        r"|\([^\r\n)]{1,300}\))\s+"
        r"(?:from|to)\s+"
        r"(?:stdin\b|stdout\b|program\s+\S+|"
        r"'[^'\r\n]*'|\"[^\"\r\n]*\"|/[^\s;\r\n]+|[A-Za-z]:\\[^\s;\r\n]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:insert\s+into|delete\s+from|merge\s+into|"
        r"update\s+[A-Za-z_][A-Za-z0-9_.]*\s+set|"
        r"call\s+[A-Za-z_][A-Za-z0-9_.]*\s*\(|"
        r"(?:drop|alter|create)\s+(?:table|schema|database|index|view)|"
        r"truncate\s+table)\b"
        r"(?:\s+[A-Za-z_][A-Za-z0-9_.]*)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:grant|revoke)\b[^\r\n;]{0,120}\bon\b[^\r\n;]{0,120}" r"\b(?:to|from)\b",
        re.IGNORECASE,
    ),
)


def assert_public_payload_safe(payload: Any, context: str = "payload") -> None:
    assert_no_public_raw_references(payload, context)


def redact_authorized_evidence_text(value: str) -> tuple[str, int]:
    """Locally redact high-confidence secrets and implementation details.

    This policy is intentionally narrower than the generic public metadata
    policy.  Authorized source evidence may contain ordinary URLs, dates,
    slash-separated prose, and user document paths without becoming an
    infrastructure disclosure.
    """

    if not isinstance(value, str):
        raise ContractValidationError("authorized evidence text must be a string")
    redacted = value
    replacements = 0
    for pattern, replacement in (
        (_AUTHORIZATION_CREDENTIAL_TEXT, "[redacted_credential]"),
        (_SECRET_ASSIGNMENT_TEXT, "[redacted_credential]"),
        (_TRACEBACK_BLOCK, "[redacted_traceback]"),
    ):
        redacted, count = pattern.subn(replacement, redacted)
        replacements += count
    for pattern in _SQL_TEXT_PATTERNS:
        redacted, count = pattern.subn("[redacted_sql]", redacted)
        replacements += count
    for pattern, replacement in (
        (_URL_USERINFO_TOKEN, "[redacted_url_credentials]"),
        (_INTERNAL_FORMOWL_LOCATOR_TOKEN, "[redacted_internal_locator]"),
        (_BACKEND_LOCATOR_TOKEN, "[redacted_internal_locator]"),
        (_INTERNAL_POSIX_PATH_TOKEN, "[redacted_internal_path]"),
        (_INTERNAL_WINDOWS_PATH_TOKEN, "[redacted_internal_path]"),
    ):
        redacted, count = pattern.subn(replacement, redacted)
        replacements += count
    assert_authorized_evidence_text_safe(redacted, "authorized_evidence_text")
    return redacted, replacements


def assert_authorized_evidence_text_safe(
    value: str,
    context: str = "authorized_evidence_text",
) -> None:
    if not isinstance(value, str):
        raise ContractValidationError(f"{context} must be a string")
    if _authorized_evidence_text_is_unsafe(value):
        raise ContractValidationError(
            f"{context} contains credential or internal implementation details"
        )


def assert_authorized_evidence_payload_safe(
    payload: Any,
    context: str = "authorized_evidence_payload",
) -> None:
    """Validate structure strictly while allowing sanitized evidence fields."""

    masked = _mask_authorized_evidence_fields(payload, context)
    assert_public_payload_safe(masked, context)


def _mask_authorized_evidence_fields(value: Any, context: str) -> Any:
    if isinstance(value, dict):
        masked: dict[Any, Any] = {}
        for key, item in value.items():
            field_context = f"{context}.{key}" if isinstance(key, str) else context
            if key in _AUTHORIZED_EVIDENCE_SCALAR_FIELDS:
                if item is None:
                    masked[key] = None
                    continue
                assert_authorized_evidence_text_safe(item, field_context)
                masked[key] = "[authorized_evidence_text]"
                continue
            if key in _AUTHORIZED_EVIDENCE_SEQUENCE_FIELDS:
                if not isinstance(item, (list, tuple)):
                    raise ContractValidationError(f"{field_context} must be a list of strings")
                for index, evidence_text in enumerate(item):
                    assert_authorized_evidence_text_safe(
                        evidence_text,
                        f"{field_context}[{index}]",
                    )
                masked[key] = ["[authorized_evidence_text]" for _ in item]
                continue
            masked[key] = _mask_authorized_evidence_fields(item, field_context)
        return masked
    if isinstance(value, list):
        return [
            _mask_authorized_evidence_fields(item, f"{context}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, tuple):
        return tuple(
            _mask_authorized_evidence_fields(item, f"{context}[{index}]")
            for index, item in enumerate(value)
        )
    return value


def _authorized_evidence_text_is_unsafe(value: str) -> bool:
    return bool(
        _SECRET_ASSIGNMENT_TEXT.search(value)
        or _AUTHORIZATION_CREDENTIAL_TEXT.search(value)
        or _TRACEBACK_BLOCK.search(value)
        or _URL_USERINFO_TOKEN.search(value)
        or _INTERNAL_FORMOWL_LOCATOR_TOKEN.search(value)
        or _BACKEND_LOCATOR_TOKEN.search(value)
        or _INTERNAL_POSIX_PATH_TOKEN.search(value)
        or _INTERNAL_WINDOWS_PATH_TOKEN.search(value)
        or any(pattern.search(value) for pattern in _SQL_TEXT_PATTERNS)
    )


__all__ = [
    "assert_authorized_evidence_payload_safe",
    "assert_authorized_evidence_text_safe",
    "assert_public_payload_safe",
    "redact_authorized_evidence_text",
    "safe_public_string",
]
