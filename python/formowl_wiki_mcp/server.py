from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

from .observability import JsonlToolCallLogger
from .storage import FileDraftStore, FileWikiSnapshotStore
from .tools import WikiMcpTools


class WikiMcpServer:
    server_name = "wiki-mcp"

    def __init__(self, tools: WikiMcpTools) -> None:
        self.tools = tools

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": "search_wiki_pages", "description": "Search existing wiki or markdown pages."},
            {"name": "get_wiki_page", "description": "Retrieve one wiki or markdown page."},
            {
                "name": "generate_wiki_draft",
                "description": "Generate a markdown draft from a context package.",
            },
            {
                "name": "generate_wiki_draft_from_graph_view",
                "description": "Generate a markdown draft from a WikiProjectionSpec and visible graph view.",
            },
            {"name": "update_wiki_draft", "description": "Update an existing markdown draft."},
            {
                "name": "publish_wiki_page",
                "description": "Prepare a proposal-only wiki publishing action.",
            },
            {"name": "capture_wiki_snapshot", "description": "Capture a wiki page snapshot."},
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = getattr(self.tools, name, None)
        if tool is None or name.startswith("_"):
            return {
                "result_type": "tool_error",
                "status": "error",
                "data": {"message": f"Unknown Wiki MCP tool: {name}"},
                "warnings": [],
            }
        return tool(arguments)


def create_default_server(data_dir: str | Path | None = None) -> WikiMcpServer:
    root = Path(data_dir or os.environ.get("FORMOWL_DATA_DIR", ".formowl/data"))
    draft_store = FileDraftStore(root)
    snapshot_store = FileWikiSnapshotStore(root)
    logger = JsonlToolCallLogger(root / "logs" / "wiki-mcp-tool-calls.jsonl")
    return WikiMcpServer(WikiMcpTools(draft_store, snapshot_store, logger))


def main() -> None:
    server = create_default_server()
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        if request.get("method") == "list_tools":
            response = {"tools": server.list_tools()}
        else:
            response = server.call_tool(str(request.get("tool")), request.get("arguments") or {})
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
