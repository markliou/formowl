from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

from .adapters.openproject import MockOpenProjectAdapter
from .observability import JsonlToolCallLogger
from .storage import FileEvidenceSnapshotStore
from .tools import ProjectMcpTools


class ProjectMcpServer:
    server_name = "project-mcp"

    def __init__(self, tools: ProjectMcpTools) -> None:
        self.tools = tools

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": "search_work_items", "description": "Search work items."},
            {"name": "get_work_item", "description": "Retrieve one work item."},
            {"name": "get_work_item_context", "description": "Retrieve LLM-ready work item context."},
            {"name": "list_work_item_activities", "description": "Retrieve work item comments and activities."},
            {"name": "list_work_item_relations", "description": "Retrieve related work items."},
            {"name": "get_project_status", "description": "Retrieve project status summary."},
            {"name": "propose_work_item_comment", "description": "Prepare a proposal-only work item comment."},
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = getattr(self.tools, name, None)
        if tool is None or name.startswith("_"):
            return {
                "result_type": "tool_error",
                "status": "error",
                "data": {"message": f"Unknown Project MCP tool: {name}"},
                "warnings": [],
            }
        return tool(arguments)


def create_default_server(data_dir: str | Path | None = None) -> ProjectMcpServer:
    root = Path(data_dir or os.environ.get("FORMOWL_DATA_DIR", ".formowl/data"))
    adapter = MockOpenProjectAdapter()
    store = FileEvidenceSnapshotStore(root)
    logger = JsonlToolCallLogger(root / "logs" / "project-mcp-tool-calls.jsonl")
    return ProjectMcpServer(ProjectMcpTools(adapter, store, logger))


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
