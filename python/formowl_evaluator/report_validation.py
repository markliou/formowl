from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from formowl_contract import assert_no_public_raw_references, sha256_json
from formowl_gateway import validate_public_gateway_payload

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def dict_or_empty(value: Any, context: str, blockers: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        blockers.append(f"{context} must be an object")
        return {}
    return value


def mapping_dict_or_empty(value: Any, context: str, blockers: list[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        blockers.append(f"{context} must be an object")
        return {}
    return dict(value)


def mapping_or_empty(value: Any, context: str, blockers: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        blockers.append(f"{context} must be an object")
        return {}
    return value


def validate_exact_keys(
    value: Mapping[str, Any],
    expected_keys: set[str],
    context: str,
    blockers: list[str],
    *,
    allowed_extra: set[str] | None = None,
) -> None:
    actual_keys = set(value)
    extra = sorted(actual_keys - expected_keys - (allowed_extra or set()))
    missing = sorted(expected_keys - actual_keys)
    if extra:
        blockers.append(
            f"{context} contains unknown keys: count={len(extra)} hash={sha256_json(extra)}"
        )
    if missing:
        blockers.append(f"{context} missing keys: count={len(missing)} hash={sha256_json(missing)}")


def validate_exact_keys_missing_first(
    value: Mapping[str, Any],
    expected_keys: set[str],
    context: str,
    blockers: list[str],
    *,
    allowed_extra: set[str] | None = None,
) -> None:
    actual_keys = set(value)
    missing = sorted(expected_keys - actual_keys)
    extra = sorted(actual_keys - expected_keys - (allowed_extra or set()))
    if missing:
        blockers.append(f"{context} missing keys: count={len(missing)} hash={sha256_json(missing)}")
    if extra:
        blockers.append(
            f"{context} contains unknown keys: count={len(extra)} hash={sha256_json(extra)}"
        )


def require_sha256(value: Any, context: str, blockers: list[str]) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        blockers.append(f"{context} must be a sha256 hash")


def basis_points(numerator: int, denominator: int) -> int:
    return int((numerator * 10000) / denominator) if denominator else 0


def basis_points_via_ratio(numerator: int, denominator: int) -> int:
    return int((numerator / denominator) * 10000) if denominator else 0


def basis_points_via_positive_ratio(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return int((numerator / denominator) * 10000)


def public_outputs_are_safe(
    report: Mapping[str, Any],
    *,
    forbidden_fragments: Sequence[str] = (),
    raw_reference_context: str | None = None,
) -> bool:
    rendered = json.dumps(report, sort_keys=True).lower()
    if any(fragment in rendered for fragment in forbidden_fragments):
        return False
    try:
        validate_public_gateway_payload(report)
        if raw_reference_context is not None:
            assert_no_public_raw_references(report, raw_reference_context)
    except Exception:
        return False
    return True
