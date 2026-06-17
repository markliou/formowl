from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from formowl_contract import to_plain


class JsonlToolCallLogger:
    def __init__(self, log_path: str | Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(to_plain(event), ensure_ascii=False, sort_keys=True) + "\n")
