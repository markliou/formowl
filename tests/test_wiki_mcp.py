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
        self.assertEqual(publish["data"]["backend"]["publish_mode"], "proposal_only")
        self.assertFalse(publish["data"]["backend"]["external_write_performed"])
        self.assertFalse(publish["data"]["backend"]["automatic_publish_enabled"])
        self.assertIn("No wiki page was published", publish["warnings"][0])

    def test_openproject_wiki_publish_adapter_returns_safe_backend_specific_proposal(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("wiki-openproject-publish-proposal")
        server = create_default_server(temp_dir)
        draft = server.call_tool(
            "generate_wiki_draft",
            {
                "page_type": "adr",
                "title": "OpenProject Wiki Proposal",
                "context_package": sample_context_package(),
            },
        )

        publish = server.call_tool(
            "publish_wiki_page",
            {
                "draft_id": draft["data"]["draft_id"],
                "target": {
                    "target_system": "openproject_wiki",
                    "source_instance": "openproject_primary",
                    "project_id": "formowl",
                    "page_slug": "openproject-wiki-proposal",
                    "api_url": "https://openproject.example.test/api/v3",
                    "api_token": "secret-token",
                },
                "auto_publish": True,
                "require_review": False,
            },
        )

        rendered = str(publish)
        self.assertEqual(publish["status"], "pending_review")
        self.assertEqual(
            publish["data"]["target"],
            {
                "target_system": "openproject_wiki",
                "source_instance": "openproject_primary",
                "project_id": "formowl",
                "page_slug": "openproject-wiki-proposal",
            },
        )
        self.assertEqual(publish["data"]["backend"]["type"], "openproject_wiki")
        self.assertEqual(publish["data"]["backend"]["operation"], "upsert_wiki_page")
        self.assertEqual(
            publish["data"]["backend"]["source_ref"]["source_id"],
            "formowl:openproject-wiki-proposal",
        )
        self.assertTrue(publish["data"]["backend"]["automatic_publish_requested"])
        self.assertFalse(publish["data"]["backend"]["automatic_publish_enabled"])
        self.assertFalse(publish["data"]["backend"]["external_write_performed"])
        self.assertIn("Automatic wiki publishing is disabled", publish["warnings"][1])
        self.assertIn("unsafe target fields were omitted", publish["warnings"][2])
        self.assertNotIn("/api/v3", rendered)
        self.assertNotIn("secret-token", rendered)

    def test_publish_target_rejects_unsafe_required_fields_without_side_effects(self) -> None:
        temp_dir = _paths.fresh_test_dir("wiki-openproject-unsafe-target")
        server = create_default_server(temp_dir)
        draft = server.call_tool(
            "generate_wiki_draft",
            {
                "page_type": "adr",
                "title": "Unsafe OpenProject Wiki Proposal",
                "context_package": sample_context_package(),
            },
        )

        publish = server.call_tool(
            "publish_wiki_page",
            {
                "draft_id": draft["data"]["draft_id"],
                "target": {
                    "target_system": "openproject_wiki",
                    "project_id": "formowl",
                    "page_slug": "../private-page",
                },
            },
        )

        self.assertEqual(publish["status"], "error")
        self.assertEqual(publish["data"]["error_code"], "invalid_publish_target")
        self.assertNotIn("../private-page", str(publish))

    def test_publish_target_rejects_non_mapping_target_without_side_effects(self) -> None:
        temp_dir = _paths.fresh_test_dir("wiki-non-mapping-target")
        server = create_default_server(temp_dir)
        draft = server.call_tool(
            "generate_wiki_draft",
            {
                "page_type": "adr",
                "title": "Non Mapping Target",
                "context_package": sample_context_package(),
            },
        )

        publish = server.call_tool(
            "publish_wiki_page",
            {
                "draft_id": draft["data"]["draft_id"],
                "target": "postgresql://internal/wiki",
                "auto_publish": True,
            },
        )

        self.assertEqual(publish["status"], "error")
        self.assertEqual(publish["data"]["error_code"], "invalid_publish_target")
        self.assertNotIn("postgresql://internal/wiki", str(publish))
        self.assertIn(
            "Wiki publish target was rejected before any publish side effect.",
            publish["warnings"],
        )


if __name__ == "__main__":
    unittest.main()
