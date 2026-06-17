from __future__ import annotations

import difflib
import hashlib


def sha256_prefixed(text: str | bytes) -> str:
    if isinstance(text, str):
        payload = text.encode("utf-8")
    else:
        payload = text
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def sha256_prefixed_id(prefix: str, text: str | bytes, length: int = 24) -> str:
    if not prefix or "_" in prefix:
        raise ValueError("prefix must be non-empty and must not contain underscores")
    if length < 8 or length > 64:
        raise ValueError("length must be between 8 and 64")
    digest = sha256_prefixed(text).removeprefix("sha256:")
    return f"{prefix}_{digest[:length]}"


def diff_lines(before: str, after: str, fromfile: str = "before", tofile: str = "after") -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = difflib.unified_diff(before_lines, after_lines, fromfile=fromfile, tofile=tofile)
    return "".join(diff)
