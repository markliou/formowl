from __future__ import annotations

import json
from pathlib import Path
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    Grant,
    PermissionScope,
    SourceRef,
    stable_user_knowledge_graph_revision_id,
)
from formowl_graph import (
    assemble_effective_graph_view,
    requester_has_effective_graph_view_access,
)
from formowl_graph.index import FileGraphProjectionStore, GraphProjectionEdge, GraphProjectionNode

NOW = "2026-06-25T12:00:00+00:00"


class EffectiveGraphViewTests(unittest.TestCase):
    def test_effective_graph_view_requires_graph_grant_for_private_fragment(self) -> None:
        temp_dir = _paths.fresh_test_dir("effective-graph-view-private-fragment")
        store = FileGraphProjectionStore(temp_dir)
        requester_scope = _private_user_scope("user_yifan")
        owner_scope = _private_user_scope("user_owner")
        store.create_node(
            _node(
                "node_requester",
                "atom_requester_note",
                requester_scope,
                label="Requester visible note",
            )
        )
        store.create_node(
            _node(
                "node_public",
                "atom_public_policy",
                {"scope_type": "public", "visibility": "public"},
                label="Public policy",
            )
        )
        store.create_node(
            _node(
                "node_owner_private",
                "atom_owner_private",
                owner_scope,
                label="Owner secret decision",
            )
        )
        store.create_edge(
            _edge(
                "rel_public",
                "node_requester",
                "node_public",
                {"scope_type": "public", "visibility": "public"},
            )
        )
        store.create_edge(
            _edge(
                "rel_private_between_visible",
                "node_requester",
                "node_public",
                owner_scope,
            )
        )
        store.create_edge(_edge("rel_shared", "node_requester", "node_owner_private", owner_scope))
        revision = _revision(
            included_atom_ids=["atom_requester_note", "atom_public_policy", "atom_owner_private"],
            included_relation_ids=["rel_private_between_visible", "rel_public", "rel_shared"],
        )

        before = _snapshot_files(temp_dir)
        no_grant = assemble_effective_graph_view(
            user_graph_revision=revision,
            graph_projection_store=store,
            requester_user_id="user_yifan",
            grants=[],
            now=NOW,
        )
        self.assertEqual(
            [node.node_id for node in no_grant.visible_nodes], ["node_public", "node_requester"]
        )
        self.assertEqual([edge.edge_id for edge in no_grant.visible_edges], ["rel_public"])
        self.assertEqual(len(no_grant.access_required), 1)
        self.assertEqual(no_grant.access_required[0].owner_user_id, "user_owner")
        self.assertEqual(no_grant.access_required[0].requestable_scope_type, "private_user")
        self.assertEqual(no_grant.access_required[0].requestable_scope_id, "user_owner")
        self.assertEqual(no_grant.access_required[0].recommended_access_level, "graph_snippet")
        self.assertEqual(no_grant.access_required[0].hidden_node_count, 1)
        self.assertEqual(no_grant.access_required[0].hidden_edge_count, 1)
        no_grant_payload = json.dumps(no_grant.to_dict(), sort_keys=True)
        self.assertNotIn("Owner secret decision", no_grant_payload)
        self.assertNotIn("atom_owner_private", no_grant_payload)
        self.assertNotIn("rel_private_between_visible", no_grant_payload)
        self.assertEqual(_snapshot_files(temp_dir), before)

        with_grant = assemble_effective_graph_view(
            user_graph_revision=revision,
            graph_projection_store=store,
            requester_user_id="user_yifan",
            grants=[_grant("grant_graph", permission="graph_snippet")],
            now=NOW,
        )
        self.assertEqual(
            [node.node_id for node in with_grant.visible_nodes],
            ["node_owner_private", "node_public", "node_requester"],
        )
        self.assertEqual(
            [edge.edge_id for edge in with_grant.visible_edges],
            ["rel_private_between_visible", "rel_public", "rel_shared"],
        )
        self.assertEqual(with_grant.access_required, [])
        self.assertEqual(with_grant.applied_grant_ids, ["grant_graph"])
        self.assertIn("Owner secret decision", json.dumps(with_grant.to_dict(), sort_keys=True))
        self.assertEqual(_snapshot_files(temp_dir), before)

    def test_private_user_graph_revision_requires_owner_or_graph_grant(self) -> None:
        temp_dir = _paths.fresh_test_dir("effective-graph-view-revision-access")
        store = FileGraphProjectionStore(temp_dir)
        store.create_node(
            _node(
                "node_public",
                "atom_public_policy",
                {"scope_type": "public", "visibility": "public"},
                label="Public policy",
            )
        )
        store.create_node(
            _node(
                "node_owner_private",
                "atom_owner_private",
                _private_user_scope("user_owner"),
                label="Owner secret decision",
            )
        )
        revision = _revision(
            included_atom_ids=["atom_public_policy", "atom_owner_private"],
        )
        before = _snapshot_files(temp_dir)

        denied = assemble_effective_graph_view(
            user_graph_revision=revision,
            graph_projection_store=store,
            requester_user_id="user_other",
            grants=[],
            now=NOW,
        )
        denied_payload = json.dumps(denied.to_dict(), sort_keys=True)
        self.assertEqual(denied.visible_nodes, [])
        self.assertEqual(denied.visible_edges, [])
        self.assertEqual(len(denied.access_required), 1)
        self.assertEqual(denied.access_required[0].requestable_scope_type, "private_user")
        self.assertEqual(denied.access_required[0].requestable_scope_id, "user_yifan")
        self.assertEqual(denied.access_required[0].owner_user_id, "user_yifan")
        self.assertEqual(denied.access_required[0].hidden_node_count, 0)
        self.assertEqual(denied.access_required[0].hidden_edge_count, 0)
        self.assertNotIn("Public policy", denied_payload)
        self.assertNotIn("atom_public_policy", denied_payload)
        self.assertNotIn("Owner secret decision", denied_payload)
        self.assertNotIn("atom_owner_private", denied_payload)
        self.assertNotIn("user_owner", denied_payload)
        self.assertEqual(_snapshot_files(temp_dir), before)

        revision_grant = _grant(
            "grant_revision_graph",
            permission="graph_snippet",
            owner_user_id="user_yifan",
            grantee_user_id="user_other",
            scope_id="user_yifan",
        )
        authorized = assemble_effective_graph_view(
            user_graph_revision=revision,
            graph_projection_store=store,
            requester_user_id="user_other",
            grants=[revision_grant],
            now=NOW,
        )
        self.assertEqual([node.node_id for node in authorized.visible_nodes], ["node_public"])
        self.assertEqual(authorized.visible_edges, [])
        self.assertEqual(authorized.applied_grant_ids, ["grant_revision_graph"])
        self.assertEqual(len(authorized.access_required), 1)
        self.assertEqual(authorized.access_required[0].requestable_scope_id, "user_owner")
        self.assertEqual(authorized.access_required[0].hidden_node_count, 1)
        self.assertEqual(_snapshot_files(temp_dir), before)

    def test_effective_graph_view_does_not_treat_other_grant_levels_as_graph_access(
        self,
    ) -> None:
        scope = _private_user_scope("user_owner")
        allowed = _grant("grant_graph", permission="graph_snippet")
        denied_grants = [
            _grant("grant_answer", permission="answer_only"),
            _grant("grant_evidence", permission="evidence_snippet"),
            _grant("grant_read", permission="read"),
            _grant("grant_search", permission="search"),
            _grant("grant_session", permission="session_access"),
            _grant("grant_query", permission="query_scoped_access"),
            _grant("grant_project", permission="project_scoped_access"),
            _grant("grant_asset", permission="asset_scoped_access"),
            _grant("grant_one_time_raw", permission="one_time_raw_asset_access"),
            _grant("grant_raw", permission="raw_asset"),
            _grant("grant_revoked", permission="graph_snippet", revoked_at=NOW),
            _grant("grant_expired", permission="graph_snippet", expires_at=NOW),
            _grant("grant_other_user", permission="graph_snippet", grantee_user_id="user_other"),
            _grant("grant_wrong_scope", permission="graph_snippet", scope_id="user_other_owner"),
            _grant("grant_wrong_owner", permission="graph_snippet", owner_user_id="user_other"),
            _grant("grant_exhausted", permission="graph_snippet", max_access_count=0),
        ]

        self.assertTrue(
            requester_has_effective_graph_view_access(
                scope,
                requester_user_id="user_yifan",
                grants=[allowed],
                now=NOW,
            )
        )
        for grant in denied_grants:
            with self.subTest(grant=grant.grant_id):
                self.assertFalse(
                    requester_has_effective_graph_view_access(
                        scope,
                        requester_user_id="user_yifan",
                        grants=[grant],
                        now=NOW,
                    )
                )

        with self.assertRaises(ContractValidationError):
            requester_has_effective_graph_view_access(
                scope,
                requester_user_id="user_yifan",
                grants=[allowed],
            )

        temp_dir = _paths.fresh_test_dir("effective-graph-view-invalid-grants")
        store = FileGraphProjectionStore(temp_dir)
        store.create_node(
            _node(
                "node_owner_private",
                "atom_owner_private",
                scope,
                label="Owner private graph",
            )
        )
        revision = _revision(included_atom_ids=["atom_owner_private"])
        for grant in denied_grants:
            view = assemble_effective_graph_view(
                user_graph_revision=revision,
                graph_projection_store=store,
                requester_user_id="user_yifan",
                grants=[grant],
                now=NOW,
            )
            with self.subTest(applied_grant=grant.grant_id):
                self.assertEqual(view.visible_nodes, [])
                self.assertEqual(view.applied_grant_ids, [])
                self.assertEqual(len(view.access_required), 1)
                self.assertNotIn(grant.grant_id, json.dumps(view.to_dict(), sort_keys=True))

        malformed_direct_grants = [
            _grant("grant_bad_negative_count", permission="graph_snippet", max_access_count=-1),
            _grant("grant_bad_string_count", permission="graph_snippet", max_access_count="0"),
        ]
        for grant in malformed_direct_grants:
            with self.subTest(malformed_grant=grant.grant_id):
                with self.assertRaises(ContractValidationError):
                    requester_has_effective_graph_view_access(
                        scope,
                        requester_user_id="user_yifan",
                        grants=[grant],
                        now=NOW,
                    )
                with self.assertRaises(ContractValidationError):
                    assemble_effective_graph_view(
                        user_graph_revision=revision,
                        graph_projection_store=store,
                        requester_user_id="user_yifan",
                        grants=[grant],
                        now=NOW,
                    )

        unsafe_grant = _grant("grant_/workspace/private.xlsx", permission="graph_snippet")
        with self.assertRaises(ContractValidationError) as direct_ctx:
            requester_has_effective_graph_view_access(
                scope,
                requester_user_id="user_yifan",
                grants=[unsafe_grant],
                now=NOW,
            )
        self.assertNotIn("/workspace/private.xlsx", str(direct_ctx.exception))
        with self.assertRaises(ContractValidationError) as view_ctx:
            assemble_effective_graph_view(
                user_graph_revision=revision,
                graph_projection_store=store,
                requester_user_id="user_yifan",
                grants=[unsafe_grant],
                now=NOW,
            )
        self.assertNotIn("/workspace/private.xlsx", str(view_ctx.exception))

    def test_effective_graph_view_rejects_raw_scope_without_echo(self) -> None:
        temp_dir = _paths.fresh_test_dir("effective-graph-view-raw-scope")
        store = FileGraphProjectionStore(temp_dir)
        store.create_node(
            _node(
                "node_raw_scope",
                "atom_raw_scope",
                {
                    "scope_type": "project",
                    "scope_id": "/workspace/private.xlsx",
                    "visibility": "restricted",
                },
                label="Raw scoped node",
            )
        )
        revision = _revision(included_atom_ids=["atom_raw_scope"])

        with self.assertRaises(ContractValidationError) as ctx:
            assemble_effective_graph_view(
                user_graph_revision=revision,
                graph_projection_store=store,
                requester_user_id="user_yifan",
                grants=[],
                now=NOW,
            )
        self.assertNotIn("/workspace/private.xlsx", str(ctx.exception))

    def test_effective_graph_view_rejects_raw_visibility_without_echo(self) -> None:
        raw_visibility = "/workspace/private.xlsx"
        node_dir = _paths.fresh_test_dir("effective-graph-view-raw-node-visibility")
        node_store = FileGraphProjectionStore(node_dir)
        node_store.create_node(
            _node(
                "node_raw_visibility",
                "atom_raw_visibility",
                {"scope_type": "public", "visibility": raw_visibility},
                label="Public graph node",
            )
        )
        node_revision = _revision(included_atom_ids=["atom_raw_visibility"])
        node_before = _snapshot_files(node_dir)

        with self.assertRaises(ContractValidationError) as node_ctx:
            assemble_effective_graph_view(
                user_graph_revision=node_revision,
                graph_projection_store=node_store,
                requester_user_id="user_yifan",
                grants=[],
                now=NOW,
            )
        self.assertNotIn(raw_visibility, str(node_ctx.exception))
        self.assertEqual(_snapshot_files(node_dir), node_before)

        edge_dir = _paths.fresh_test_dir("effective-graph-view-raw-edge-visibility")
        edge_store = FileGraphProjectionStore(edge_dir)
        public_scope = {"scope_type": "public", "visibility": "public"}
        edge_store.create_node(
            _node("node_source", "atom_source", public_scope, label="Source node")
        )
        edge_store.create_node(
            _node("node_target", "atom_target", public_scope, label="Target node")
        )
        edge_store.create_edge(
            _edge(
                "rel_raw_visibility",
                "node_source",
                "node_target",
                {"scope_type": "public", "visibility": raw_visibility},
            )
        )
        edge_revision = _revision(
            included_atom_ids=["atom_source", "atom_target"],
            included_relation_ids=["rel_raw_visibility"],
        )
        edge_before = _snapshot_files(edge_dir)

        with self.assertRaises(ContractValidationError) as edge_ctx:
            assemble_effective_graph_view(
                user_graph_revision=edge_revision,
                graph_projection_store=edge_store,
                requester_user_id="user_yifan",
                grants=[],
                now=NOW,
            )
        self.assertNotIn(raw_visibility, str(edge_ctx.exception))
        self.assertEqual(_snapshot_files(edge_dir), edge_before)

    def test_effective_graph_view_rejects_raw_locators_in_visible_payload_without_echo(
        self,
    ) -> None:
        raw_asset_locator = "formowl://asset/secret"
        node_dir = _paths.fresh_test_dir("effective-graph-view-raw-node-payload")
        node_store = FileGraphProjectionStore(node_dir)
        node_store.create_node(
            GraphProjectionNode(
                node_id="node_raw_payload",
                source_type="canonical_atom",
                source_id="atom_raw_payload",
                labels=[raw_asset_locator],
                properties={"label": "Public graph node"},
                permission_scope={"scope_type": "public", "visibility": "public"},
            )
        )
        node_revision = _revision(included_atom_ids=["atom_raw_payload"])
        node_before = _snapshot_files(node_dir)

        with self.assertRaises(ContractValidationError) as node_ctx:
            assemble_effective_graph_view(
                user_graph_revision=node_revision,
                graph_projection_store=node_store,
                requester_user_id="user_yifan",
                grants=[],
                now=NOW,
            )
        self.assertNotIn(raw_asset_locator, str(node_ctx.exception))
        self.assertEqual(_snapshot_files(node_dir), node_before)

        raw_evidence_locator = "formowl://evidence/secret"
        edge_dir = _paths.fresh_test_dir("effective-graph-view-raw-edge-payload")
        edge_store = FileGraphProjectionStore(edge_dir)
        public_scope = {"scope_type": "public", "visibility": "public"}
        edge_store.create_node(
            _node("node_source", "atom_source", public_scope, label="Source node")
        )
        edge_store.create_node(
            _node("node_target", "atom_target", public_scope, label="Target node")
        )
        edge_store.create_edge(
            GraphProjectionEdge(
                edge_id="rel_raw_payload",
                source_node_id="node_source",
                target_node_id="node_target",
                relation_type="supports",
                properties={
                    "canonical_relation_id": "rel_raw_payload",
                    "locator": raw_evidence_locator,
                },
                permission_scope=public_scope,
            )
        )
        edge_revision = _revision(
            included_atom_ids=["atom_source", "atom_target"],
            included_relation_ids=["rel_raw_payload"],
        )
        edge_before = _snapshot_files(edge_dir)

        with self.assertRaises(ContractValidationError) as edge_ctx:
            assemble_effective_graph_view(
                user_graph_revision=edge_revision,
                graph_projection_store=edge_store,
                requester_user_id="user_yifan",
                grants=[],
                now=NOW,
            )
        self.assertNotIn(raw_evidence_locator, str(edge_ctx.exception))
        self.assertEqual(_snapshot_files(edge_dir), edge_before)


def _node(
    node_id: str,
    source_id: str,
    permission_scope: dict[str, object],
    *,
    label: str,
) -> GraphProjectionNode:
    return GraphProjectionNode(
        node_id=node_id,
        source_type="canonical_atom",
        source_id=source_id,
        labels=["atom"],
        properties={"label": label},
        permission_scope=permission_scope,
    )


def _edge(
    edge_id: str,
    source_node_id: str,
    target_node_id: str,
    permission_scope: dict[str, object],
) -> GraphProjectionEdge:
    return GraphProjectionEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        relation_type="supports",
        properties={"canonical_relation_id": edge_id},
        permission_scope=permission_scope,
    )


def _revision(
    *,
    included_atom_ids: list[str],
    included_relation_ids: list[str] | None = None,
) -> dict[str, object]:
    canonical_graph_revision_id = "graph_revision_shared_001"
    ontology_revision_id = "ontology_rev_shared_001"
    source_refs = [
        SourceRef(
            source_system="fixture",
            source_type="canonical_graph",
            source_id=canonical_graph_revision_id,
            source_url="https://example.invalid/graph/revision",
        ).to_dict()
    ]
    permission_scope = PermissionScope(
        scope_type="private_user",
        scope_id="user_yifan",
        visibility="restricted",
    ).to_dict()
    created_at = "2026-06-25T12:00:00+00:00"
    revision_id = stable_user_knowledge_graph_revision_id(
        user_id="user_yifan",
        graph_profile_id="ugprofile_ops",
        canonical_graph_revision_id=canonical_graph_revision_id,
        ontology_revision_id=ontology_revision_id,
        assembly_policy_id="ugpolicy_ops",
        included_atom_ids=included_atom_ids,
        included_entity_ids=[],
        included_relation_ids=included_relation_ids or [],
        source_refs=source_refs,
        evidence_snapshot_ids=["ev_user_graph_001"],
        permission_scope=permission_scope,
        created_at=created_at,
    )
    return {
        "user_graph_revision_id": revision_id,
        "user_id": "user_yifan",
        "graph_profile_id": "ugprofile_ops",
        "canonical_graph_revision_id": canonical_graph_revision_id,
        "ontology_revision_id": ontology_revision_id,
        "assembly_policy_id": "ugpolicy_ops",
        "status": "draft",
        "included_atom_ids": included_atom_ids,
        "included_entity_ids": [],
        "included_relation_ids": included_relation_ids or [],
        "source_refs": source_refs,
        "evidence_snapshot_ids": ["ev_user_graph_001"],
        "permission_scope": permission_scope,
        "created_at": created_at,
        "created_by": "user_yifan",
        "assembly_metadata": {"reason": "effective graph view fixture"},
    }


def _private_user_scope(user_id: str) -> dict[str, object]:
    return {
        "scope_type": "private_user",
        "scope_id": user_id,
        "visibility": "restricted",
    }


def _grant(
    grant_id: str,
    *,
    permission: str,
    owner_user_id: str = "user_owner",
    grantee_user_id: str = "user_yifan",
    scope_id: str = "user_owner",
    expires_at: str = "2026-06-26T12:00:00+00:00",
    max_access_count: object | None = None,
    revoked_at: str | None = None,
) -> Grant:
    return Grant(
        grant_id=grant_id,
        owner_user_id=owner_user_id,
        grantee_user_id=grantee_user_id,
        scope_type="private_user",
        scope_id=scope_id,
        permission=permission,
        expires_at=expires_at,
        max_access_count=max_access_count,
        revoked_at=revoked_at,
    )


def _snapshot_files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


if __name__ == "__main__":
    unittest.main()
