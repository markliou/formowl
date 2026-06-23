from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    PermissionScope,
    SourceRef,
    WikiProjectionSpec,
    stable_wiki_projection_spec_id,
)
from formowl_wiki_mcp import create_default_server

CREATED_AT = "2026-06-21T00:00:00+00:00"


class GraphWikiProjectionTests(unittest.TestCase):
    def test_projection_spec_driven_draft_generation_preserves_graph_lineage(
        self,
    ) -> None:
        temp_dir = _paths.fresh_test_dir("graph-wiki-projection")
        server = create_default_server(temp_dir)
        projection_spec = _projection_spec()
        graph_view = _graph_view(summary="Decision risk is visible to the requester.")

        result = server.call_tool(
            "generate_wiki_draft_from_graph_view",
            {"projection_spec": projection_spec.to_dict(), "graph_view": graph_view},
        )

        self.assertEqual(result["status"], "ok")
        frontmatter = result["data"]["frontmatter"]
        markdown = result["data"]["markdown"]
        projection_spec_driven_draft_generation = result["data"]["draft_id"].startswith(
            "draft_graph_"
        )
        visible_evidence_only = graph_view["visible_evidence_only"] is True
        visible_evidence_only_graph_projection_tests = visible_evidence_only
        ontology_revision_pin = (
            frontmatter["ontology_revision_id"] == projection_spec.ontology_revision_id
        )
        source_lineage_preserved = (
            result["source_refs"] == [projection_spec.source_refs[0].to_dict()]
            and result["evidence_snapshot_ids"] == projection_spec.evidence_snapshot_ids
        )
        graph_user_graph_revision_lineage_in_wiki_frontmatter = (
            frontmatter["projection_spec_id"] == projection_spec.projection_spec_id
            and frontmatter["graph_revision_id"] == projection_spec.graph_revision_id
            and frontmatter["user_graph_revision_id"] == projection_spec.user_graph_revision_id
        )
        draft_not_publish = (
            result["data"]["revision_status"] == "draft"
            and "no wiki page was published" in result["warnings"][0].lower()
        )
        silent_publish = "published_at" in str(result).lower()

        self.assertTrue(projection_spec_driven_draft_generation)
        self.assertTrue(visible_evidence_only)
        self.assertTrue(visible_evidence_only_graph_projection_tests)
        self.assertTrue(ontology_revision_pin)
        self.assertTrue(source_lineage_preserved)
        self.assertTrue(graph_user_graph_revision_lineage_in_wiki_frontmatter)
        self.assertTrue(draft_not_publish)
        self.assertFalse(silent_publish)
        self.assertEqual(frontmatter["projection_spec_id"], projection_spec.projection_spec_id)
        self.assertEqual(frontmatter["graph_revision_id"], "graph_revision_orion_001")
        self.assertEqual(frontmatter["user_graph_revision_id"], "ugraph_orion_001")
        self.assertEqual(frontmatter["redaction_policy"], "visible_evidence_only")
        self.assertEqual(frontmatter["included_graph_node_ids"], ["node_decision_001"])
        self.assertIn("Decision risk is visible", markdown)
        self.assertIn("cit_graph_001", markdown)
        self.assertIn("ev_project_001", markdown)
        self.assertNotIn("raw_path", str(result))
        self.assertNotIn("CanonicalGraphCommit", str(result))

    def test_diff_created_on_refresh_for_graph_derived_pages(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-wiki-projection-refresh")
        server = create_default_server(temp_dir)
        projection_spec = _projection_spec()

        first = server.call_tool(
            "generate_wiki_draft_from_graph_view",
            {
                "projection_spec": projection_spec.to_dict(),
                "graph_view": _graph_view(summary="Initial visible risk."),
            },
        )
        refreshed = server.call_tool(
            "generate_wiki_draft_from_graph_view",
            {
                "projection_spec": projection_spec.to_dict(),
                "graph_view": _graph_view(summary="Updated visible risk."),
            },
        )

        diff_created_on_refresh = bool(refreshed["data"]["diff_markdown"])
        diff_on_refresh_for_graph_derived_pages = diff_created_on_refresh
        self.assertTrue(diff_created_on_refresh)
        self.assertTrue(diff_on_refresh_for_graph_derived_pages)
        self.assertNotEqual(first["data"]["draft_id"], refreshed["data"]["draft_id"])
        self.assertEqual(
            refreshed["data"]["frontmatter"]["parent_revision_id"],
            first["data"]["frontmatter"]["revision_id"],
        )
        self.assertEqual(refreshed["data"]["frontmatter"]["change_kind"], "source_refresh")
        self.assertIn("-Initial visible risk.", refreshed["data"]["diff_markdown"])
        self.assertIn("+Updated visible risk.", refreshed["data"]["diff_markdown"])
        self.assertEqual(len(server.tools.draft_store.list_drafts()), 2)

    def test_projection_rejects_hidden_or_raw_private_evidence(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-wiki-projection-private")
        server = create_default_server(temp_dir)
        projection_spec = _projection_spec()
        hidden_view = _graph_view(summary="Visible summary")
        hidden_view["evidence_snippets"][0]["visible"] = False
        raw_path_view = _graph_view(summary="Visible summary")
        raw_path_view["evidence_snippets"][0]["raw_path"] = "/srv/formowl/private.xlsx"
        not_visible_only = _graph_view(summary="Visible summary")
        not_visible_only["visible_evidence_only"] = False

        for graph_view in [hidden_view, raw_path_view, not_visible_only]:
            raw_private_evidence_projection = graph_view
            with self.subTest(graph_view=graph_view):
                with self.assertRaises(ContractValidationError):
                    server.call_tool(
                        "generate_wiki_draft_from_graph_view",
                        {
                            "projection_spec": projection_spec.to_dict(),
                            "graph_view": raw_private_evidence_projection,
                        },
                    )

    def test_projection_rejects_graph_and_ontology_revision_mismatch(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-wiki-projection-mismatch")
        server = create_default_server(temp_dir)
        projection_spec = _projection_spec()
        mismatched_graph = _graph_view(summary="Visible summary")
        mismatched_graph["graph_revision_id"] = "graph_revision_other"
        mismatched_ontology = _graph_view(summary="Visible summary")
        mismatched_ontology["ontology_revision_id"] = "ontology_revision_other"

        for graph_view in [mismatched_graph, mismatched_ontology]:
            with self.subTest(graph_view=graph_view):
                with self.assertRaises(ContractValidationError):
                    server.call_tool(
                        "generate_wiki_draft_from_graph_view",
                        {"projection_spec": projection_spec.to_dict(), "graph_view": graph_view},
                    )


def _projection_spec() -> WikiProjectionSpec:
    source_ref = SourceRef(
        source_system="formowl",
        source_type="user_graph_revision",
        source_id="ugraph_orion_001",
    )
    projection_spec_id = stable_wiki_projection_spec_id(
        projection_kind="project_summary",
        graph_revision_id="graph_revision_orion_001",
        ontology_revision_id="ontology_revision_core_001",
        title="Project Orion Graph Summary",
        source_refs=[source_ref],
        evidence_snapshot_ids=["ev_project_001"],
        citation_behavior="required_inline_citations",
    )
    return WikiProjectionSpec(
        projection_spec_id=projection_spec_id,
        projection_kind="project_summary",
        title="Project Orion Graph Summary",
        graph_revision_id="graph_revision_orion_001",
        ontology_revision_id="ontology_revision_core_001",
        user_graph_revision_id="ugraph_orion_001",
        source_refs=[source_ref],
        evidence_snapshot_ids=["ev_project_001"],
        citation_behavior="required_inline_citations",
        redaction_policy="visible_evidence_only",
        projection_rules={"sections": ["decisions", "risks"]},
        draft_target={"backend": "markdown_draft", "page_slug": "project-orion-summary"},
        permission_scope=PermissionScope.project("project_orion").to_dict(),
        created_by="user_yifan",
        created_at=CREATED_AT,
    )


def _graph_view(*, summary: str) -> dict:
    return {
        "graph_revision_id": "graph_revision_orion_001",
        "ontology_revision_id": "ontology_revision_core_001",
        "user_graph_revision_id": "ugraph_orion_001",
        "visible_evidence_only": True,
        "summary": summary,
        "nodes": [
            {
                "node_id": "node_decision_001",
                "label": "Orion delivery decision",
                "summary": "Decision node projected from visible graph evidence.",
                "visible": True,
            }
        ],
        "relations": [
            {
                "relation_id": "rel_decision_risk_001",
                "label": "has_risk",
                "visible": True,
            }
        ],
        "evidence_snippets": [
            {
                "citation_id": "cit_graph_001",
                "source_ref": SourceRef(
                    source_system="formowl",
                    source_type="user_graph_revision",
                    source_id="ugraph_orion_001",
                ).to_dict(),
                "evidence_snapshot_id": "ev_project_001",
                "summary": "Visible graph evidence supports the projected summary.",
                "visible": True,
            }
        ],
        "redaction_counts": {"hidden_records": 2},
    }


if __name__ == "__main__":
    unittest.main()
