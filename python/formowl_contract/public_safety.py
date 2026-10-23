from __future__ import annotations

import re
from typing import Any

from .primitives import ContractValidationError

_RAW_PATH = re.compile(r"(^|[\s'\"([{=,:;])(/|[A-Za-z]:[\\/]|\\\\)", re.IGNORECASE)
_BACKEND_LOCATOR = re.compile(
    r"\b(?:"
    r"file|s3|gs|gcs|minio|object|webdav|dav|smb|nfs|"
    r"postgres(?:ql)?|mysql|mariadb|sqlite|mssql|sqlserver|oracle|"
    r"redis(?:s)?|mongodb(?:\+srv)?|amqp|rabbitmq|kafka|"
    r"imap(?:s)?|smtp(?:s)?|pop3(?:s)?|mapi|ews"
    r"):\/\/[^\s'\"<>]+",
    re.IGNORECASE,
)
_URL_USERINFO = re.compile(
    r"\b[A-Za-z][A-Za-z0-9+.-]*://[^/\s@]+@",
    re.IGNORECASE,
)
_INTERNAL_FORMOWL_LOCATOR = re.compile(
    r"\bformowl://(?:object|storage|backend|scratch|raw)(?:/[^\s'\"<>]*)?",
    re.IGNORECASE,
)
_SQL_TEXT = re.compile(
    r"\b("
    r"select\s+.+\s+from|"
    r"insert\s+into|"
    r"update\s+[A-Za-z_][\w.]*\s+set|"
    r"delete\s+from|"
    r"drop\s+table|"
    r"alter\s+table|"
    r"create\s+table|"
    r"truncate\s+table"
    r")\b",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_TEXT = re.compile(
    r"\b(?:"
    r"access[_-]?key|access[_-]?token|api[_-]?key|auth[_-]?token|"
    r"authorization|bearer[_-]?token|client[_-]?secret|credential|"
    r"password|passwd|private[_-]?key|pwd|refresh[_-]?token|"
    r"secret|secret[_-]?key|token"
    r")\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_BEARER_CREDENTIAL_TEXT = re.compile(
    r"\bauthorization\s*:\s*bearer\s+\S+|\bbearer\s+[A-Za-z0-9._~+/-]{8,}",
    re.IGNORECASE,
)
_SECRET_FIELD_NAMES = {
    "access_key",
    "access_token",
    "api_key",
    "auth_token",
    "authorization",
    "bearer_token",
    "client_secret",
    "credential",
    "credentials",
    "id_token",
    "password",
    "passwd",
    "private_key",
    "pwd",
    "refresh_token",
    "secret",
    "secret_key",
    "token",
}
_SECRET_COMPACT_FIELD_NAMES = {name.replace("_", "") for name in _SECRET_FIELD_NAMES}
# Detection admits bare roots and Unicode paths. Consume those same spans so
# unrelated evidence survives; the final unsafe-string guard remains fail closed.
_RAW_PATH_TOKEN = re.compile(
    r"(?:(?<=^)|(?<=[\s'\"([{=,:;]))(?:/[^\s\"<>]*|"
    r"[A-Za-z]:[\\/][^\s'\"<>]*|\\\\[^\s'\"<>]*)",
    re.IGNORECASE,
)
_LOCATOR_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+", re.IGNORECASE)


def _numeric_division_positions(value: str) -> set[int]:
    # Only a spaced binary operator between bounded numeric operands. Bare
    # roots, numeric paths, path suffixes and other slashes remain unsafe.
    return {match.start("slash") for match in re.finditer(
        r"(?<![\w./\\])[0-9]+(?:\.[0-9]+)?[ \t]+(?P<slash>/)[ \t]+"
        r"[0-9]+(?:\.[0-9]+)?(?![\w./\\])", value,
    )}


def _has_raw_path(value: str) -> bool:
    division = _numeric_division_positions(value)
    return any(match.start(2) not in division for match in _RAW_PATH.finditer(value))


def safe_public_string(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be a string")
    assert_no_public_raw_references(value, field_name)
    return value


def assert_no_public_raw_references(payload: Any, context: str = "payload") -> None:
    violations: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for index, (key, item) in enumerate(value.items()):
                item_path = _dict_item_path(path, key, index)
                if isinstance(key, str) and (
                    _unsafe_public_string(key) or _unsafe_public_field_name(key)
                ):
                    violations.append(f"{item_path}.key")
                walk(item, item_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str) and _unsafe_public_string(value):
            violations.append(path)

    walk(payload, context)
    if violations:
        raise ContractValidationError(
            "public payload contains raw, backend, credential, secret, or SQL references: "
            + ", ".join(sorted(violations))
        )


def redact_public_raw_references(value: str) -> tuple[str, int]:
    """Redact unsafe locator, credential, and SQL spans from user evidence text."""

    if not isinstance(value, str):
        raise ContractValidationError("redacted public value must be a string")
    redacted = value
    replacements = 0
    for pattern, replacement in (
        (_SECRET_ASSIGNMENT_TEXT, "[redacted_credential]"),
        (_BEARER_CREDENTIAL_TEXT, "[redacted_credential]"),
        (_SQL_TEXT, "[redacted_sql]"),
        (_INTERNAL_FORMOWL_LOCATOR, "[redacted_internal_locator]"),
        (_BACKEND_LOCATOR, "[redacted_internal_locator]"),
        (_URL_USERINFO, "[redacted_url_credentials]"),
        (_LOCATOR_TOKEN, "[redacted_locator]"),
    ):
        redacted, count = pattern.subn(replacement, redacted)
        replacements += count
    division = _numeric_division_positions(redacted)
    def redact_path(match: re.Match[str]) -> str:
        nonlocal replacements
        if match.start() in division and match[0] == "/":
            return match[0]
        replacements += 1
        return "[redacted_path]"
    redacted = _RAW_PATH_TOKEN.sub(redact_path, redacted)
    if _unsafe_public_string(redacted):
        return "[redacted_mail_evidence]", max(1, replacements)
    return redacted, replacements


def _unsafe_public_string(value: str) -> bool:
    return bool(
        _has_raw_path(value)
        or _BACKEND_LOCATOR.search(value)
        or _URL_USERINFO.search(value)
        or _INTERNAL_FORMOWL_LOCATOR.search(value)
        or _SQL_TEXT.search(value)
        or _SECRET_ASSIGNMENT_TEXT.search(value)
        or _BEARER_CREDENTIAL_TEXT.search(value)
    )


def _unsafe_public_field_name(value: str) -> bool:
    normalized = _normalize_public_field_name(value)
    if normalized in _SECRET_FIELD_NAMES:
        return True
    compact = normalized.replace("_", "")
    if compact in _SECRET_COMPACT_FIELD_NAMES or _contains_compact_secret_name(compact):
        return True
    parts = {part for part in normalized.split("_") if part}
    if {"password", "passwd", "pwd", "authorization"} & parts:
        return True
    if {"secret", "credential", "credentials"} & parts:
        return True
    if "token" in parts:
        return True
    return {"api", "key"}.issubset(parts) or {"private", "key"}.issubset(parts)


def _normalize_public_field_name(value: str) -> str:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.strip())
    return re.sub(r"[^A-Za-z0-9]+", "_", camel_split).strip("_").lower()


def _contains_compact_secret_name(value: str) -> bool:
    return any(secret in value for secret in _SECRET_COMPACT_FIELD_NAMES if len(secret) >= 5)


def _dict_item_path(base_path: str, key: Any, index: int) -> str:
    if isinstance(key, str) and not (_unsafe_public_string(key) or _unsafe_public_field_name(key)):
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,79}", key):
            return f"{base_path}.{key}" if base_path else key
    return f"{base_path}.item[{index}]" if base_path else f"item[{index}]"


def private_public_safety_rejection_summary(
    *, answer_text: str, coverage_note: str,
) -> dict[str, Any]:
    """Hash-only private diagnostics; this does not decide public acceptance."""
    from .primitives import sha256_json

    if not isinstance(answer_text, str) or not isinstance(coverage_note, str):
        raise ContractValidationError("private safety diagnostic fields must be strings")
    fields = {"answer_text": answer_text, "coverage_note": coverage_note}
    patterns = (
        ("raw_path", _RAW_PATH),
        ("backend_locator", _BACKEND_LOCATOR),
        ("url_userinfo", _URL_USERINFO),
        ("internal_locator", _INTERNAL_FORMOWL_LOCATOR),
        ("sql_text", _SQL_TEXT),
        ("secret_assignment", _SECRET_ASSIGNMENT_TEXT),
        ("bearer_credential", _BEARER_CREDENTIAL_TEXT),
    )
    field_rules = {
        name: [code for code, pattern in patterns
               if (_has_raw_path(value) if code == "raw_path" else pattern.search(value))]
        for name, value in fields.items()
    }
    affected = [name for name, rules in field_rules.items() if rules]
    codes = sorted({code for rules in field_rules.values() for code in rules})
    return {
        "rule_codes": codes,
        "affected_fields": affected,
        "field_hashes": {name: sha256_json(fields[name]) for name in affected},
        "draft_hash": sha256_json(fields),
        "matched_rule_count": len(codes),
        "affected_field_count": len(affected),
    }
