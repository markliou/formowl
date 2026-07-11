from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterable

from formowl_contract import assert_no_public_raw_references, sha256_json
from formowl_gateway import validate_public_gateway_payload


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def validate_hash_list(
    value: Any,
    *,
    expected_count: int,
    context: str,
    blockers: list[str],
) -> None:
    if not isinstance(value, list) or len(value) != expected_count:
        blockers.append(f"{context} must contain {expected_count} hashes")
        return
    if not all(is_sha256(item) for item in value):
        blockers.append(f"{context} must contain sha256 hashes")
    if len(set(value)) != len(value):
        blockers.append(f"{context} must contain distinct hashes")


def validate_exact_keys(
    value: dict[str, Any],
    expected_keys: set[str],
    context: str,
    blockers: list[str],
    *,
    allowed_extra: set[str] | None = None,
) -> None:
    extra = sorted(set(value) - expected_keys - (allowed_extra or set()))
    missing = sorted(expected_keys - set(value))
    if extra:
        blockers.append(
            f"{context} contains unknown keys: " f"count={len(extra)} hash={sha256_json(extra)}"
        )
    if missing:
        blockers.append(f"{context} missing keys: " + sha256_json(missing))


def public_payload_is_safe(
    payload: dict[str, Any],
    *,
    forbidden_fragments: Iterable[str],
    raw_reference_context: str,
    gateway_validator: Callable[[Any], None] = validate_public_gateway_payload,
    raw_reference_validator: Callable[[Any, str], None] = assert_no_public_raw_references,
) -> bool:
    lowered = json.dumps(payload, sort_keys=True).lower()
    if any(fragment.lower() in lowered for fragment in forbidden_fragments):
        return False
    try:
        gateway_validator(payload)
        raw_reference_validator(payload, raw_reference_context)
    except Exception:
        return False
    return True
