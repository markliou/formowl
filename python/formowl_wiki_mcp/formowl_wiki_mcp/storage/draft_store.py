from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from formowl_contract import to_plain


class FileDraftStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir) / "wiki" / "drafts"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        payload = to_plain(draft)
        path = self.base_dir / f"{payload['draft_id']}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        path = self.base_dir / f"{draft_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_drafts(self, project: str | None = None) -> list[dict[str, Any]]:
        drafts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(self.base_dir.glob("*.json"))]
        if project is None:
            return drafts
        return [draft for draft in drafts if draft.get("frontmatter", {}).get("project") == project]
