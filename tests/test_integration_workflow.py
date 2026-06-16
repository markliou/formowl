from __future__ import annotations

import unittest

import _paths
from formowl_project_mcp import create_default_server as create_project_server
from formowl_wiki_mcp import create_default_server as create_wiki_server


class IntegrationWorkflowTests(unittest.TestCase):
    def test_project_context_can_generate_wiki_draft(self) -> None:
        temp_dir = _paths.fresh_test_dir("integration-project-to-wiki")
        project = create_project_server(temp_dir)
        wiki = create_wiki_server(temp_dir)

        context_result = project.call_tool(
            "get_work_item_context",
            {
                "source_ref": {
                    "source_system": "openproject",
                    "source_type": "work_package",
                    "source_id": "123",
                },
                "include_comments": True,
                "include_activities": True,
                "include_relations": True,
                "include_attachments": True,
                "create_evidence_snapshot": True,
            },
        )
        draft_result = wiki.call_tool(
            "generate_wiki_draft",
            {
                "page_type": "adr",
                "title": "Source Preserving Wiki Draft Workflow",
                "context_package": context_result["context_package"],
            },
        )

        self.assertEqual(context_result["status"], "ok")
        self.assertEqual(draft_result["status"], "ok")
        self.assertEqual(
            draft_result["evidence_snapshot_ids"],
            context_result["context_package"]["evidence_snapshot_ids"],
        )
        self.assertIn("Source Preserving Wiki Draft Workflow", draft_result["data"]["markdown"])
        self.assertIn("OP-123", draft_result["data"]["markdown"])


if __name__ == "__main__":
    unittest.main()
