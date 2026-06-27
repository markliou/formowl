from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def _test_tmp_root() -> Path:
    configured = os.environ.get("FORMOWL_TEST_TMP_ROOT")
    candidates = [Path(configured)] if configured else [ROOT / ".test-tmp"]
    if not configured:
        candidates.append(Path(tempfile.gettempdir()) / f"formowl-test-tmp-{os.getuid()}")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue
    raise RuntimeError("no writable FormOwl test temporary directory is available")


TEST_TMP_ROOT = _test_tmp_root()

for relative in [
    "python",
]:
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)


def fresh_test_dir(name: str) -> Path:
    path = TEST_TMP_ROOT / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
