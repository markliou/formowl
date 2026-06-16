from __future__ import annotations

import unittest

import _paths
from formowl_wiki_mcp import create_default_server


def sample_context_package() -> dict:
    return {
        "context_package_id": "ctx_project_001",
        "context_type": "work_item_context",
        "context_markdown": "# Work item\n\nThe draft must be reviewable and preserve sources.",
        "source_refs": [
            {
                "source_system": "openproject",
                "source_type": "work_package",
                "source_id": "123",
                "source_key": "OP-123",
                "source_url": "https://openproject.example.test/work_packages/123",
            }
        ],
        "evidence_snapshot_ids": ["ev_project_001"],
        "citations": [],
        "permission_scope": {
            "scope_type": "project",
            "scope_id": "formowl",
            "visibility": "restricted",
        },
    }


class WikiMcpTests(unittest.TestCase):
    def test_generate_wiki_draft_adds_frontmatter_sources_and_citations(self) -> None:
        temp_dir = _paths.fresh_test_dir("wiki-generate")
        server = create_default_server(temp_dir)
        result = server.call_tool(
            "generate_wiki_draft",
            {
                "page_type": "adr",
                "title": "Data Retention Architecture Decision",
                "context_package": sample_context_package(),
            },
        )

        self.assertEqual(result["status"], "ok")
        markdown = result["data"]["markdown"]
        self.assertTrue(markdown.startswith("---\n"))
        self.assertIn("source_refs:", markdown)
        self.assertIn("ev_project_001", markdown)
        self.assertIn("## Citations", markdown)
        self.assertEqual(result["citations"][0]["citation_id"], "cit_001")

    def test_publish_wiki_page_is_proposal_only(self) -> None:
        temp_dir = _paths.fresh_test_dir("wiki-publish")
        server = create_default_server(temp_dir)
        draft = server.call_tool(
            "generate_wiki_draft",
            {
                "page_type": "adr",
                "title": "Reviewable Wiki Publish",
                "context_package": sample_context_package(),
            },
        )
        draft_id = draft["data"]["draft_id"]
        publish = server.call_tool(
            "publish_wiki_page",
            {
                "draft_id": draft_id,
                "target": {
                    "target_system": "openproject_wiki",
                    "project_id": "formowl",
                    "page_slug": "reviewable-wiki-publish",
                },
                "require_review": True,
            },
        )

        self.assertEqual(publish["status"], "pending_review")
        self.assertEqual(publish["data"]["draft_id"], draft_id)
        self.assertIn("No wiki page was published", publish["warnings"][0])


if __name__ == "__main__":
    unittest.main()
