from __future__ import annotations

import ctypes
import difflib
import hashlib
import os
from pathlib import Path
from typing import Callable


def _candidate_library_paths() -> list[Path]:
    configured = os.environ.get("FORMOWL_CORE_LIBRARY")
    if configured:
        return [Path(configured)]

    root = Path(__file__).resolve().parents[2]
    names = [
        "formowl_python_bindings.dll",
        "libformowl_python_bindings.so",
        "libformowl_python_bindings.dylib",
    ]
    return [root / "target" / "release" / name for name in names]


def _load_native() -> ctypes.CDLL | None:
    for path in _candidate_library_paths():
        if path.exists():
            library = ctypes.CDLL(str(path))
            library.formowl_sha256_prefixed.argtypes = [ctypes.c_char_p]
            library.formowl_sha256_prefixed.restype = ctypes.c_void_p
            library.formowl_free_string.argtypes = [ctypes.c_void_p]
            library.formowl_free_string.restype = None
            return library
    return None


_NATIVE = _load_native()


def using_native_binding() -> bool:
    return _NATIVE is not None


def _native_string_call(function: Callable[[bytes], int], payload: bytes) -> str:
    if _NATIVE is None:
        raise RuntimeError("formowl native core binding is not loaded")
    ptr = function(payload)
    if not ptr:
        raise RuntimeError("formowl native core returned a null pointer")
    try:
        return ctypes.string_at(ptr).decode("utf-8")
    finally:
        _NATIVE.formowl_free_string(ptr)


def sha256_prefixed(text: str | bytes) -> str:
    if isinstance(text, str):
        payload = text.encode("utf-8")
    else:
        payload = text
    if _NATIVE is not None:
        return _native_string_call(_NATIVE.formowl_sha256_prefixed, payload)
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def diff_lines(before: str, after: str, fromfile: str = "before", tofile: str = "after") -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = difflib.unified_diff(before_lines, after_lines, fromfile=fromfile, tofile=tofile)
    return "".join(diff)
