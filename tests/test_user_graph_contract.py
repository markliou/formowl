from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    CanonicalGraphRevision,
    ContractValidationError,
    PermissionScope,
    SourceRef,
    UserGraphAssemblyPolicy,
    UserGraphProfile,
    UserKnowledgeGraphRevision,
    stable_canonical_graph_revision_id,
    stable_user_graph_assembly_policy_id,
    stable_user_graph_profile_id,
    stable_user_knowledge_graph_revision_id,
)


class UserGraphContractTests(unittest.TestCase):
    def test_two_users_can_express_different_views_from_same_canonical_graph(self) -> None:
        canonical_graph = CanonicalGraphRevision.from_dict(_canonical_graph_revision_payload())
        manager_profile = UserGraphProfile.from_dict(
            _profile_payload("user_manager", "operations_summary")
        )
        reviewer_profile = UserGraphProfile.from_dict(
            _profile_payload("user_reviewer", "policy_detail")
        )
        manager_policy = UserGraphAssemblyPolicy.from_dict(
            _policy_payload(
                manager_profile.graph_profile_id,
                "user_manager",
                include_rules={"atom_types": ["decision", "risk"]},
                granularity_rules={"default": "coarse"},
            )
        )
        reviewer_policy = UserGraphAssemblyPolicy.from_dict(
            _policy_payload(
                reviewer_profile.graph_profile_id,
                "user_reviewer",
                include_rules={"atom_types": ["decision", "requirement", "exception"]},
                granularity_rules={"default": "fine"},
            )
        )
        manager_revision = UserKnowledgeGraphRevision.from_dict(
            _revision_payload(
                user_id="user_manager",
                graph_profile_id=manager_profile.graph_profile_id,
                assembly_policy_id=manager_policy.assembly_policy_id,
                included_atom_ids=["atom_decision_summary"],
                included_entity_ids=["entity_project"],
                included_relation_ids=["rel_decision_risk"],
                canonical_graph_revision_id=canonical_graph.canonical_graph_revision_id,
                ontology_revision_id=canonical_graph.ontology_revision_id,
            )
        )
        reviewer_revision = UserKnowledgeGraphRevision.from_dict(
            _revision_payload(
                user_id="user_reviewer",
                graph_profile_id=reviewer_profile.graph_profile_id,
                assembly_policy_id=reviewer_policy.assembly_policy_id,
                included_atom_ids=["atom_decision_detail", "atom_policy_exception"],
                included_entity_ids=["entity_policy"],
                included_relation_ids=["rel_exception_source"],
                canonical_graph_revision_id=canonical_graph.canonical_graph_revision_id,
                ontology_revision_id=canonical_graph.ontology_revision_id,
            )
        )

        self.assertEqual(
            manager_revision.canonical_graph_revision_id,
            canonical_graph.canonical_graph_revision_id,
        )
        self.assertEqual(
            reviewer_revision.canonical_graph_revision_id,
            canonical_graph.canonical_graph_revision_id,
        )
        self.assertEqual(
            manager_revision.ontology_revision_id, reviewer_revision.ontology_revision_id
        )
        self.assertNotEqual(
            manager_revision.user_graph_revision_id, reviewer_revision.user_graph_revision_id
        )
        self.assertEqual(manager_revision.included_atom_ids, ["atom_decision_summary"])
        self.assertEqual(
            reviewer_revision.included_atom_ids,
            ["atom_decision_detail", "atom_policy_exception"],
        )
        self.assertEqual(manager_revision.permission_scope["visibility"], "restricted")
        self.assertLessEqual(
            set(manager_revision.included_atom_ids),
            set(canonical_graph.canonical_atom_ids),
        )
        self.assertLessEqual(
            set(reviewer_revision.included_atom_ids),
            set(canonical_graph.canonical_atom_ids),
        )
        self.assertLessEqual(
            set(manager_revision.included_entity_ids),
            set(canonical_graph.canonical_entity_ids),
        )
        self.assertLessEqual(
            set(reviewer_revision.included_entity_ids),
            set(canonical_graph.canonical_entity_ids),
        )
        self.assertLessEqual(
            set(manager_revision.included_relation_ids),
            set(canonical_graph.canonical_relation_ids),
        )
        self.assertLessEqual(
            set(reviewer_revision.included_relation_ids),
            set(canonical_graph.canonical_relation_ids),
        )
        self.assertEqual(
            manager_revision.source_refs[0]["source_id"],
            canonical_graph.canonical_graph_revision_id,
        )
        nested_revision_payload = _revision_payload(
            canonical_graph_revision_id="graph_revision_shared_001",
            ontology_revision_id="ontology_rev_shared_001",
        )
        nested_revision_payload["source_refs"] = [
            SourceRef(
                source_system="fixture",
                source_type="canonical_graph",
                source_id="graph_revision_shared_001",
                source_url="https://example.invalid/graph/revision",
            )
        ]
        nested_revision_payload["permission_scope"] = PermissionScope(
            scope_type="private_user",
            scope_id="user_manager",
            visibility="restricted",
        )
        nested_revision = UserKnowledgeGraphRevision.from_dict(nested_revision_payload)
        self.assertEqual(nested_revision.source_refs[0]["source_id"], "graph_revision_shared_001")
        self.assertEqual(nested_revision.permission_scope["scope_id"], "user_manager")

        for model in (
            canonical_graph,
            manager_profile,
            reviewer_profile,
            manager_policy,
            reviewer_policy,
            manager_revision,
            reviewer_revision,
        ):
            data = model.to_dict()
            self.assertEqual(type(model).from_dict(data).to_dict(), data)

    def test_user_graph_stable_ids_are_reproducible_and_view_sensitive(self) -> None:
        source_refs = [
            SourceRef(
                source_system="fixture",
                source_type="canonical_graph",
                source_id="graph_revision_shared_001",
                source_url="https://example.invalid/graph/revision",
            ).to_dict()
        ]
        permission_scope = PermissionScope(
            scope_type="private_user",
            scope_id="user_manager",
            visibility="restricted",
        ).to_dict()
        base_revision_kwargs = {
            "user_id": "user_manager",
            "graph_profile_id": "ugprofile_ops",
            "canonical_graph_revision_id": "graph_revision_shared_001",
            "ontology_revision_id": "ontology_rev_shared_001",
            "assembly_policy_id": "ugpolicy_ops",
            "included_atom_ids": ["atom_a"],
            "included_entity_ids": ["entity_project"],
            "included_relation_ids": ["rel_a"],
            "source_refs": source_refs,
            "evidence_snapshot_ids": ["ev_user_graph_001"],
            "permission_scope": permission_scope,
            "created_at": "2026-06-25T12:00:00+00:00",
        }
        first = stable_user_knowledge_graph_revision_id(**base_revision_kwargs)
        same = stable_user_knowledge_graph_revision_id(**base_revision_kwargs)
        different_view = stable_user_knowledge_graph_revision_id(
            **{**base_revision_kwargs, "included_atom_ids": ["atom_b"]}
        )
        different_exclusion = stable_user_knowledge_graph_revision_id(
            **{**base_revision_kwargs, "excluded_atom_ids": ["atom_hidden"]}
        )
        different_user_authored = stable_user_knowledge_graph_revision_id(
            **{**base_revision_kwargs, "user_authored_atom_ids": ["uatom_private"]}
        )
        different_private_note = stable_user_knowledge_graph_revision_id(
            **{**base_revision_kwargs, "private_note_ids": ["note_private_001"]}
        )
        different_source_ref = stable_user_knowledge_graph_revision_id(
            **{
                **base_revision_kwargs,
                "source_refs": [
                    SourceRef(
                        source_system="fixture",
                        source_type="canonical_graph",
                        source_id="graph_revision_other_001",
                        source_url="https://example.invalid/graph/other",
                    ).to_dict()
                ],
            }
        )
        different_evidence = stable_user_knowledge_graph_revision_id(
            **{**base_revision_kwargs, "evidence_snapshot_ids": ["ev_user_graph_002"]}
        )
        different_permission = stable_user_knowledge_graph_revision_id(
            **{
                **base_revision_kwargs,
                "permission_scope": PermissionScope(
                    scope_type="project",
                    scope_id="workspace_formowl",
                    visibility="restricted",
                ).to_dict(),
            }
        )
        different_user = stable_user_knowledge_graph_revision_id(
            **{**base_revision_kwargs, "user_id": "user_reviewer"}
        )
        different_profile = stable_user_knowledge_graph_revision_id(
            **{**base_revision_kwargs, "graph_profile_id": "ugprofile_policy_detail"}
        )
        different_canonical_graph = stable_user_knowledge_graph_revision_id(
            **{
                **base_revision_kwargs,
                "canonical_graph_revision_id": "graph_revision_shared_002",
            }
        )
        different_ontology = stable_user_knowledge_graph_revision_id(
            **{**base_revision_kwargs, "ontology_revision_id": "ontology_rev_shared_002"}
        )
        different_policy = stable_user_knowledge_graph_revision_id(
            **{**base_revision_kwargs, "assembly_policy_id": "ugpolicy_policy_detail"}
        )
        different_parent = stable_user_knowledge_graph_revision_id(
            **{
                **base_revision_kwargs,
                "parent_user_graph_revision_id": "ugrev_parent_001",
            }
        )
        different_timestamp = stable_user_knowledge_graph_revision_id(
            **{**base_revision_kwargs, "created_at": "2026-06-25T12:01:00+00:00"}
        )

        self.assertEqual(first, same)
        self.assertNotEqual(first, different_view)
        self.assertNotEqual(first, different_exclusion)
        self.assertNotEqual(first, different_user_authored)
        self.assertNotEqual(first, different_private_note)
        self.assertNotEqual(first, different_source_ref)
        self.assertNotEqual(first, different_evidence)
        self.assertNotEqual(first, different_permission)
        self.assertNotEqual(first, different_user)
        self.assertNotEqual(first, different_profile)
        self.assertNotEqual(first, different_canonical_graph)
        self.assertNotEqual(first, different_ontology)
        self.assertNotEqual(first, different_policy)
        self.assertNotEqual(first, different_parent)
        self.assertNotEqual(first, different_timestamp)
        profile_id = stable_user_graph_profile_id(
            owner_user_id="user_manager",
            owner_scope_type="private_user",
            owner_scope_id="user_manager",
            profile_name="operations_summary",
        )
        same_profile_id = stable_user_graph_profile_id(
            owner_user_id="user_manager",
            owner_scope_type="private_user",
            owner_scope_id="user_manager",
            profile_name="operations_summary",
        )
        different_profile_id = stable_user_graph_profile_id(
            owner_user_id="user_reviewer",
            owner_scope_type="private_user",
            owner_scope_id="user_reviewer",
            profile_name="operations_summary",
        )
        policy_id = stable_user_graph_assembly_policy_id(
            policy_version="v1",
            owner_scope_type="private_user",
            owner_scope_id="user_manager",
            graph_profile_id="ugprofile_ops",
            rules={"include_rules": {"atom_types": ["decision"]}},
        )
        same_policy_id = stable_user_graph_assembly_policy_id(
            policy_version="v1",
            owner_scope_type="private_user",
            owner_scope_id="user_manager",
            graph_profile_id="ugprofile_ops",
            rules={"include_rules": {"atom_types": ["decision"]}},
        )
        different_policy_id = stable_user_graph_assembly_policy_id(
            policy_version="v2",
            owner_scope_type="private_user",
            owner_scope_id="user_manager",
            graph_profile_id="ugprofile_ops",
            rules={"include_rules": {"atom_types": ["decision"]}},
        )
        self.assertEqual(profile_id, same_profile_id)
        self.assertNotEqual(profile_id, different_profile_id)
        self.assertTrue(profile_id.startswith("ugprofile_"))
        self.assertEqual(policy_id, same_policy_id)
        self.assertNotEqual(policy_id, different_policy_id)
        self.assertTrue(policy_id.startswith("ugpolicy_"))

    def test_user_graph_contracts_reject_malformed_permissions_lineage_and_raw_references(
        self,
    ) -> None:
        invalid_profile_cases = [
            _replace(_profile_payload("user_manager", "ops"), graph_profile_id="/tmp/profile"),
            _replace(_profile_payload("user_manager", "ops"), owner_scope_id="user_reviewer"),
            _replace(_profile_payload("user_manager", "ops"), owner_scope_type="access_overlay"),
            _replace(
                _profile_payload("user_manager", "access-overlay approved"),
            ),
            _replace(_profile_payload("user_manager", "ops"), status="draft"),
            _replace(_profile_payload("user_manager", "ops"), preferred_granularity=[]),
            _replace(
                _profile_payload("user_manager", "ops"),
                description="exports wiki_revision_id rev_001",
            ),
            _replace(
                _profile_payload("user_manager", "ops"),
                description="access overlay approved for this profile",
            ),
            _replace(
                _profile_payload("user_manager", "ops"),
                view_preferences={"source": "formowl://asset/asset_secret"},
            ),
            _replace(
                _profile_payload("user_manager", "ops"),
                view_preferences={"wiki_revision_id": "rev_001"},
            ),
            _replace(
                _profile_payload("user_manager", "ops"),
                view_preferences={"note": "grant id grant_001"},
            ),
        ]
        for payload in invalid_profile_cases:
            with self.subTest(model="UserGraphProfile", payload=payload):
                with self.assertRaises(ContractValidationError):
                    UserGraphProfile.from_dict(payload)

        invalid_policy_cases = [
            _replace(
                _policy_payload("ugprofile_ops", "user_manager"), owner_scope_id="user_reviewer"
            ),
            _replace(
                _policy_payload("ugprofile_ops", "user_manager"),
                owner_scope_type="canonical_merge",
            ),
            _replace(
                _policy_payload("ugprofile_ops", "user_manager"),
                description="uses access_overlay_id overlay_001",
            ),
            _replace(
                _policy_payload("ugprofile_ops", "user_manager"),
                description="canonical merge committed",
            ),
            _replace(_policy_payload("ugprofile_ops", "user_manager"), include_rules=[]),
            _replace(_policy_payload("ugprofile_ops", "user_manager"), status="pending_review"),
            _replace(
                _policy_payload("ugprofile_ops", "user_manager"),
                evidence_rules={"raw_path": "/workspace/private.xlsx"},
            ),
            _replace(
                _policy_payload("ugprofile_ops", "user_manager"),
                evidence_rules={"access_overlay_id": "overlay_001"},
            ),
            _replace(
                _policy_payload("ugprofile_ops", "user_manager"),
                private_note_rules={"grant_id": "grant_001"},
            ),
            _replace(
                _policy_payload("ugprofile_ops", "user_manager"),
                private_note_rules={"claim": "raw asset can be opened"},
            ),
        ]
        for payload in invalid_policy_cases:
            with self.subTest(model="UserGraphAssemblyPolicy", payload=payload):
                with self.assertRaises(ContractValidationError):
                    UserGraphAssemblyPolicy.from_dict(payload)

        invalid_revision_cases = [
            _replace(
                _revision_payload(),
                included_atom_ids=[],
                included_entity_ids=[],
                included_relation_ids=[],
            ),
            _replace(_revision_payload(), included_atom_ids=["atom_a", "atom_a"]),
            _replace(_revision_payload(), excluded_atom_ids=["atom_hidden", "atom_hidden"]),
            _replace(
                _revision_payload(),
                included_atom_ids=["atom_a"],
                excluded_atom_ids=["atom_a"],
            ),
            _replace(
                _revision_payload(),
                included_entity_ids=["entity_a"],
                excluded_entity_ids=["entity_a"],
            ),
            _replace(
                _revision_payload(),
                included_relation_ids=["rel_a"],
                excluded_relation_ids=["rel_a"],
            ),
            _replace(
                _revision_payload(),
                included_atom_ids=["atom_a"],
                user_authored_atom_ids=["atom_a"],
            ),
            _replace(
                _revision_payload(),
                excluded_atom_ids=["atom_a"],
                user_authored_atom_ids=["atom_a"],
            ),
            _replace(_revision_payload(), source_refs=[]),
            _replace(_revision_payload(), evidence_snapshot_ids=[]),
            _replace(
                _revision_payload(),
                permission_scope={"scope_type": "project", "visibility": 3},
            ),
            _replace(
                _revision_payload(),
                permission_scope={
                    "scope_type": "access_overlay",
                    "scope_id": "overlay_001",
                    "visibility": "restricted",
                },
            ),
            _replace(
                _revision_payload(),
                permission_scope={
                    "scope_type": "wiki revision",
                    "scope_id": "rev_001",
                    "visibility": "restricted",
                },
            ),
            _replace(
                _revision_payload(),
                permission_scope={
                    "scope_type": "private_user",
                    "scope_id": "user_other",
                    "visibility": "restricted",
                },
            ),
            _replace(
                _revision_payload(),
                permission_scope={
                    "scope_type": "project",
                    "scope_id": "/workspace/private.xlsx",
                    "visibility": "restricted",
                },
            ),
            _replace(
                _revision_payload(),
                permission_scope={
                    "scope_type": "project",
                    "scope_id": "workspace_formowl",
                    "visibility": "restricted",
                    "inherited_from": "formowl://asset/asset_secret",
                },
            ),
            _replace(_revision_payload(), status="committed"),
            _replace(_revision_payload(), assembly_metadata=[]),
            _replace(_revision_payload(), assembly_metadata={"source": "reports/private.pdf"}),
            _replace(_revision_payload(), assembly_metadata={"access_overlay_id": "overlay_001"}),
            _replace(_revision_payload(), assembly_metadata={"claim": "access overlay approved"}),
            _replace(
                _revision_payload(),
                assembly_metadata={"claim": "canonical_merge_status:approved"},
            ),
            _replace(
                _revision_payload(),
                assembly_metadata={"claim": "canonical graph mutation persisted"},
            ),
            _replace(
                _revision_payload(),
                assembly_metadata={"graph_store_mutation": "created"},
            ),
            _replace(_revision_payload(), assembly_metadata={"wiki_revision_id": "rev_001"}),
            _replace(_revision_payload(), assembly_metadata={"claim": "wiki revision created"}),
            _replace(
                _revision_payload(),
                source_refs=[
                    SourceRef(
                        source_system="fixture",
                        source_type="canonical_graph",
                        source_id="graph_revision_other_001",
                        source_url="https://example.invalid/graph/other",
                    ).to_dict()
                ],
            ),
            _replace(
                _revision_payload(),
                source_refs=[
                    SourceRef(
                        source_system="fixture",
                        source_type="canonical_graph",
                        source_id="graph_revision_shared_001",
                        source_url="s3://private-bucket/graph.json",
                    )
                ],
            ),
            _replace(
                _revision_payload(),
                source_refs=[
                    SourceRef(
                        source_system="fixture",
                        source_type="canonical_graph",
                        source_id="graph_revision_shared_001",
                        source_url="https://example.invalid/graph/revision",
                    ).to_dict(),
                    SourceRef(
                        source_system="fixture",
                        source_type="access overlay",
                        source_id="overlay_001",
                        source_url="https://example.invalid/overlay",
                    ).to_dict(),
                ],
            ),
            _replace(
                _revision_payload(),
                source_refs=[
                    SourceRef(
                        source_system="fixture",
                        source_type="canonical_graph",
                        source_id="graph_revision_shared_001",
                        source_url="s3://private-bucket/graph.json",
                    ).to_dict()
                ],
            ),
        ]
        for payload in invalid_revision_cases:
            with self.subTest(model="UserKnowledgeGraphRevision", payload=payload):
                with self.assertRaises(ContractValidationError):
                    UserKnowledgeGraphRevision.from_dict(payload)


def _replace(payload: dict[str, object], **changes: object) -> dict[str, object]:
    updated = dict(payload)
    updated.update(changes)
    return updated


def _profile_payload(owner_user_id: str, profile_name: str) -> dict[str, object]:
    profile_id = stable_user_graph_profile_id(
        owner_user_id=owner_user_id,
        owner_scope_type="private_user",
        owner_scope_id=owner_user_id,
        profile_name=profile_name,
    )
    return {
        "graph_profile_id": profile_id,
        "owner_user_id": owner_user_id,
        "owner_scope_type": "private_user",
        "owner_scope_id": owner_user_id,
        "profile_name": profile_name,
        "status": "active",
        "created_at": "2026-06-25T12:00:00+00:00",
        "created_by": owner_user_id,
        "description": f"{profile_name} graph profile",
        "preferred_granularity": {"decision": "coarse"},
        "view_preferences": {"safe_label": "split/merge review"},
    }


def _policy_payload(
    graph_profile_id: str,
    owner_user_id: str,
    *,
    include_rules: dict[str, object] | None = None,
    granularity_rules: dict[str, object] | None = None,
) -> dict[str, object]:
    rules = {
        "include_rules": include_rules or {"atom_types": ["decision"]},
        "exclude_rules": {"statuses": ["archived"]},
        "grouping_rules": {"group_by": "topic"},
        "granularity_rules": granularity_rules or {"default": "coarse"},
        "relation_rules": {"include_supporting_relations": True},
        "evidence_rules": {"include_visible_evidence": True},
        "private_note_rules": {"include_private_notes": False},
    }
    return {
        "assembly_policy_id": stable_user_graph_assembly_policy_id(
            policy_version="v1",
            owner_scope_type="private_user",
            owner_scope_id=owner_user_id,
            graph_profile_id=graph_profile_id,
            rules=rules,
        ),
        "policy_version": "v1",
        "owner_scope_type": "private_user",
        "owner_scope_id": owner_user_id,
        "graph_profile_id": graph_profile_id,
        "status": "active",
        "created_at": "2026-06-25T12:00:00+00:00",
        "created_by": owner_user_id,
        **rules,
    }


def _canonical_graph_revision_payload() -> dict[str, object]:
    atom_ids = [
        "atom_decision_summary",
        "atom_decision_detail",
        "atom_policy_exception",
    ]
    entity_ids = ["entity_project", "entity_policy"]
    relation_ids = ["rel_decision_risk", "rel_exception_source"]
    created_at = "2026-06-25T11:55:00+00:00"
    revision_id = stable_canonical_graph_revision_id(
        scope_type="workspace",
        scope_id="workspace_formowl",
        ontology_revision_id="ontology_rev_shared_001",
        canonical_atom_ids=atom_ids,
        canonical_entity_ids=entity_ids,
        canonical_relation_ids=relation_ids,
        created_at=created_at,
    )
    return {
        "canonical_graph_revision_id": revision_id,
        "scope_type": "workspace",
        "scope_id": "workspace_formowl",
        "ontology_revision_id": "ontology_rev_shared_001",
        "status": "committed",
        "canonical_atom_ids": atom_ids,
        "canonical_entity_ids": entity_ids,
        "canonical_relation_ids": relation_ids,
        "created_at": created_at,
        "created_by": "user_graph_reviewer",
        "source_candidate_atom_ids": ["catom_decision_summary"],
        "source_candidate_relation_ids": ["crel_decision_risk"],
        "policy_ids": ["lifecycle_policy_lifecycle_001"],
        "commit_metadata": {"fixture": "shared canonical graph"},
    }


def _revision_payload(
    *,
    user_id: str = "user_manager",
    graph_profile_id: str = "ugprofile_ops",
    assembly_policy_id: str = "ugpolicy_ops",
    included_atom_ids: list[str] | None = None,
    included_entity_ids: list[str] | None = None,
    included_relation_ids: list[str] | None = None,
    excluded_atom_ids: list[str] | None = None,
    excluded_entity_ids: list[str] | None = None,
    excluded_relation_ids: list[str] | None = None,
    user_authored_atom_ids: list[str] | None = None,
    private_note_ids: list[str] | None = None,
    canonical_graph_revision_id: str = "graph_revision_shared_001",
    ontology_revision_id: str = "ontology_rev_shared_001",
) -> dict[str, object]:
    atom_ids = included_atom_ids if included_atom_ids is not None else ["atom_decision_summary"]
    entity_ids = included_entity_ids if included_entity_ids is not None else ["entity_project"]
    relation_ids = included_relation_ids if included_relation_ids is not None else ["rel_decision"]
    excluded_atoms = excluded_atom_ids or []
    excluded_entities = excluded_entity_ids or []
    excluded_relations = excluded_relation_ids or []
    user_authored_atoms = user_authored_atom_ids or []
    private_notes = private_note_ids or []
    created_at = "2026-06-25T12:05:00+00:00"
    source_refs = [
        SourceRef(
            source_system="fixture",
            source_type="canonical_graph",
            source_id=canonical_graph_revision_id,
            source_url="https://example.invalid/graph/revision",
        ).to_dict()
    ]
    evidence_snapshot_ids = ["ev_user_graph_001"]
    permission_scope = PermissionScope(
        scope_type="private_user",
        scope_id=user_id,
        visibility="restricted",
    ).to_dict()
    revision_id = stable_user_knowledge_graph_revision_id(
        user_id=user_id,
        graph_profile_id=graph_profile_id,
        canonical_graph_revision_id=canonical_graph_revision_id,
        ontology_revision_id=ontology_revision_id,
        assembly_policy_id=assembly_policy_id,
        included_atom_ids=atom_ids,
        included_entity_ids=entity_ids,
        included_relation_ids=relation_ids,
        excluded_atom_ids=excluded_atoms,
        excluded_entity_ids=excluded_entities,
        excluded_relation_ids=excluded_relations,
        user_authored_atom_ids=user_authored_atoms,
        private_note_ids=private_notes,
        source_refs=source_refs,
        evidence_snapshot_ids=evidence_snapshot_ids,
        permission_scope=permission_scope,
        created_at=created_at,
    )
    return {
        "user_graph_revision_id": revision_id,
        "user_id": user_id,
        "graph_profile_id": graph_profile_id,
        "canonical_graph_revision_id": canonical_graph_revision_id,
        "ontology_revision_id": ontology_revision_id,
        "assembly_policy_id": assembly_policy_id,
        "status": "draft",
        "included_atom_ids": atom_ids,
        "included_entity_ids": entity_ids,
        "included_relation_ids": relation_ids,
        "source_refs": source_refs,
        "evidence_snapshot_ids": evidence_snapshot_ids,
        "permission_scope": permission_scope,
        "created_at": created_at,
        "created_by": user_id,
        "excluded_atom_ids": excluded_atoms,
        "excluded_entity_ids": excluded_entities,
        "excluded_relation_ids": excluded_relations,
        "user_authored_atom_ids": user_authored_atoms,
        "private_note_ids": private_notes,
        "assembly_metadata": {"reason": "role-specific graph view"},
    }


if __name__ == "__main__":
    unittest.main()
