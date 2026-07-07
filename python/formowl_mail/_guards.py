from __future__ import annotations

from typing import Any

from formowl_contract import assert_no_public_raw_references, safe_public_string


def assert_public_payload_safe(payload: Any, context: str = "payload") -> None:
    assert_no_public_raw_references(payload, context)


__all__ = ["assert_public_payload_safe", "safe_public_string"]
