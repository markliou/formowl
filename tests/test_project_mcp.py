from __future__ import annotations

from pathlib import Path
import unittest

import _paths
from formowl_project_mcp import create_default_server


WORK_ITEM_REF = {
    "source_system": "openproject",
    "source_type": "work_package",
    "source_id": "123",
}


class ProjectMcpTests(unittest.TestCase):
    def test_get_work_item_context_creates_context_package_and_snapshot(self) -> None:
        temp_dir = _paths.fresh_test_dir("project-context")
        server = create_default_server(temp_dir)

        result = server.call_tool(
            "get_work_item_context",
            {
                "source_ref": WORK_ITEM_REF,
                "include_comments": True,
                "include_activities": True,
                "include_relations": True,
                "include_attachments": True,
                "create_evidence_snapshot": True,
            },
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result_type"], "work_item_context")
        self.assertIn("context_package", result)
        self.assertEqual(result["context_package"]["context_type"], "work_item_context")
        self.assertEqual(len(result["evidence_snapshot_ids"]), 1)
        self.assertIn("reviewable ADR", result["context_package"]["context_markdown"])

        metadata_files = list(Path(temp_dir).glob("raw/evidence/openproject/*/*/*/*/metadata.json"))
        self.assertEqual(len(metadata_files), 1)
        log_file = Path(temp_dir) / "logs" / "project-mcp-tool-calls.jsonl"
        self.assertTrue(log_file.exists())

    def test_propose_work_item_comment_is_pending_review(self) -> None:
        temp_dir = _paths.fresh_test_dir("project-propose-comment")
        server = create_default_server(temp_dir)
        result = server.call_tool(
            "propose_work_item_comment",
            {
                "source_ref": WORK_ITEM_REF,
                "body": "Please review the generated wiki draft.",
                "reason": "Generated from reviewed draft",
            },
        )
        self.assertEqual(result["status"], "pending_review")
        self.assertIn("No project-system write", result["warnings"][0])


if __name__ == "__main__":
    unittest.main()
