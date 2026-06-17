from __future__ import annotations

import difflib
import hashlib


def sha256_prefixed(text: str | bytes) -> str:
    if isinstance(text, str):
        payload = text.encode("utf-8")
    else:
        payload = text
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def diff_lines(before: str, after: str, fromfile: str = "before", tofile: str = "after") -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = difflib.unified_diff(before_lines, after_lines, fromfile=fromfile, tofile=tofile)
    return "".join(diff)
