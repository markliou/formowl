from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from formowl_contract import to_plain


class FileWikiSnapshotStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir) / "wiki" / "snapshots"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        payload = to_plain(snapshot)
        path = self.base_dir / f"{payload['wiki_snapshot_id']}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def get_snapshot(self, wiki_snapshot_id: str) -> dict[str, Any] | None:
        path = self.base_dir / f"{wiki_snapshot_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
