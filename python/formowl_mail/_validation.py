from __future__ import annotations

from typing import Any, Mapping

from formowl_contract import sha256_json


def dict_or_empty(value: Any, context: str, blockers: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        blockers.append(f"{context} must be an object")
        return {}
    return value


def expect_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    context: str,
    blockers: list[str],
) -> None:
    extra = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if extra:
        blockers.append(f"{context} contains unknown keys: {sha256_json(extra)}")
    if missing:
        blockers.append(f"{context} missing keys: {sha256_json(missing)}")
