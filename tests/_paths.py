from __future__ import annotations

from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = ROOT / ".test-tmp"
TEST_TMP_ROOT.mkdir(exist_ok=True)

for relative in [
    "python",
    "python/formowl_project_mcp",
    "python/formowl_wiki_mcp",
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
