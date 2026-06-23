from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    PermissionScope,
    SourceRef,
    WikiRevision,
    WikiProjectionSpec,
    stable_wiki_projection_spec_id,
)

CREATED_AT = "2026-06-21T00:00:00+00:00"


class WikiProjectionSpecContractTests(unittest.TestCase):
    def test_projection_spec_round_trips_with_graph_ontology_and_source_lineage(
        self,
    ) -> None:
        spec = _projection_spec()

        data = spec.to_dict()

        self.assertEqual(WikiProjectionSpec.from_dict(data).to_dict(), data)
        self.assertEqual(data["graph_revision_id"], "graph_revision_orion_001")
        self.assertEqual(data["ontology_revision_id"], "ontology_revision_core_001")
        self.assertEqual(data["evidence_snapshot_ids"], ["ev_project_001"])
        self.assertFalse(data["include_private_evidence"])

    def test_projection_spec_id_is_stable_from_lineage_payload(self) -> None:
        source_ref = SourceRef(
            source_system="formowl",
            source_type="user_graph_revision",
            source_id="ugraph_orion_001",
        )
        left = stable_wiki_projection_spec_id(
            projection_kind="project_summary",
            graph_revision_id="graph_revision_orion_001",
            ontology_revision_id="ontology_revision_core_001",
            title="Project Orion Summary",
            source_refs=[source_ref],
            evidence_snapshot_ids=["ev_project_001"],
            citation_behavior="required_inline_citations",
        )
        right = stable_wiki_projection_spec_id(
            projection_kind="project_summary",
            graph_revision_id="graph_revision_orion_001",
            ontology_revision_id="ontology_revision_core_001",
            title="Project Orion Summary",
            source_refs=[source_ref.to_dict()],
            evidence_snapshot_ids=["ev_project_001"],
            citation_behavior="required_inline_citations",
        )

        self.assertEqual(left, right)
        self.assertTrue(left.startswith("projection_"))

    def test_projection_spec_rejects_missing_or_malformed_lineage(self) -> None:
        base = _projection_spec().to_dict()
        invalid_cases = [
            {"ontology_revision_id": ""},
            {"graph_revision_id": "../graph"},
            {"evidence_snapshot_ids": []},
            {"source_refs": []},
            {"created_at": "not-a-timestamp"},
            {"include_private_evidence": True},
        ]

        for patch in invalid_cases:
            payload = {**base, **patch}
            with self.subTest(patch=patch):
                with self.assertRaises(ContractValidationError):
                    WikiProjectionSpec.from_dict(payload)

    def test_projection_spec_rejects_raw_paths_sql_and_private_locator_targets(self) -> None:
        base = _projection_spec().to_dict()
        invalid_cases = [
            {"draft_target": {"raw_path": "/srv/formowl/wiki.md"}},
            {"projection_rules": {"sql": "select * from graph"}},
            {"projection_rules": {"source": "smb://nas/private"}},
            {"title": "Read /home/formowl/private"},
        ]

        for patch in invalid_cases:
            payload = {**base, **patch}
            with self.subTest(patch=patch):
                with self.assertRaises(ContractValidationError):
                    WikiProjectionSpec.from_dict(payload)

    def test_wiki_revision_can_carry_projection_and_graph_lineage(self) -> None:
        spec = _projection_spec()

        revision = WikiRevision(
            revision_id="rev_wiki_orion_001",
            title=spec.title,
            status="draft",
            change_kind="generated",
            markdown_hash="sha256:abc123",
            source_refs=spec.source_refs,
            evidence_snapshot_ids=spec.evidence_snapshot_ids,
            citations=[],
            created_at=CREATED_AT,
            projection_spec_id=spec.projection_spec_id,
            graph_revision_id=spec.graph_revision_id,
            ontology_revision_id=spec.ontology_revision_id,
            user_graph_revision_id=spec.user_graph_revision_id,
            graph_view_hash="sha256:graphview",
            evidence_snapshot_refs=[{"evidence_snapshot_id": "ev_project_001"}],
        )
        data = revision.to_dict()

        self.assertEqual(data["projection_spec_id"], spec.projection_spec_id)
        self.assertEqual(data["graph_revision_id"], "graph_revision_orion_001")
        self.assertEqual(data["ontology_revision_id"], "ontology_revision_core_001")
        self.assertEqual(data["user_graph_revision_id"], "ugraph_orion_001")
        self.assertEqual(
            data["evidence_snapshot_refs"], [{"evidence_snapshot_id": "ev_project_001"}]
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
        title="Project Orion Summary",
        source_refs=[source_ref],
        evidence_snapshot_ids=["ev_project_001"],
        citation_behavior="required_inline_citations",
    )
    return WikiProjectionSpec(
        projection_spec_id=projection_spec_id,
        projection_kind="project_summary",
        title="Project Orion Summary",
        graph_revision_id="graph_revision_orion_001",
        ontology_revision_id="ontology_revision_core_001",
        user_graph_revision_id="ugraph_orion_001",
        source_refs=[source_ref],
        evidence_snapshot_ids=["ev_project_001"],
        citation_behavior="required_inline_citations",
        redaction_policy="visible_evidence_only",
        projection_rules={"sections": ["decisions", "risks"], "max_citations": 12},
        draft_target={"backend": "markdown_draft", "page_slug": "project-orion-summary"},
        permission_scope=PermissionScope.project("project_orion").to_dict(),
        created_by="user_yifan",
        created_at=CREATED_AT,
    )


if __name__ == "__main__":
    unittest.main()
