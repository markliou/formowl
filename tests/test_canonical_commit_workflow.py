from __future__ import annotations

import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import (
    CandidateAtom,
    CandidateRelation,
    CanonicalEntity,
    CanonicalGraphRevision,
    CanonicalRelation,
    ContractValidationError,
    SourceRef,
    stable_canonical_entity_id,
    stable_canonical_relation_id,
)
from formowl_graph import (
    CanonicalCommitPolicyPins,
    commit_reviewed_candidates_to_canonical_graph,
)
from formowl_graph.storage import CandidateAtomStore, CandidateRelationStore, CanonicalGraphStore
import formowl_graph.storage.records as storage_records


class CanonicalCommitWorkflowTests(unittest.TestCase):
    def test_approved_candidates_commit_with_policy_ontology_and_lineage(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-success")
        atom_store = CandidateAtomStore(temp_dir)
        relation_store = CandidateRelationStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        source_atom = atom_store.create(_candidate_atom("catom_commit_source", "Source claim"))
        target_atom = atom_store.create(_candidate_atom("catom_commit_target", "Target claim"))
        relation = relation_store.create(
            _candidate_relation(
                "crel_commit_supports",
                source_atom.candidate_atom_id,
                target_atom.candidate_atom_id,
            )
        )
        source_ref = SourceRef(
            source_system="fixture_review",
            source_type="review_packet",
            source_id="review_packet_001",
            source_url="https://example.invalid/review_packet_001",
        ).to_dict()
        citation = {
            "citation_id": "cit_commit_001",
            "source_ref": source_ref,
            "evidence_snapshot_id": "ev_commit_001",
            "locator": {"type": "observation", "id": "obs_commit_source"},
            "summary": "Reviewer approved the candidate source.",
        }

        result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            candidate_relation_store=relation_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[source_atom.candidate_atom_id, target_atom.candidate_atom_id],
            candidate_relation_ids=[relation.candidate_relation_id],
            source_refs_by_candidate_id={source_atom.candidate_atom_id: [source_ref]},
            evidence_snapshot_ids_by_candidate_id={
                source_atom.candidate_atom_id: ["ev_commit_001"],
                relation.candidate_relation_id: ["ev_commit_relation_001"],
            },
            citations_by_candidate_id={source_atom.candidate_atom_id: [citation]},
            review_decision_ids=["review_decision_001", "review_decision_002"],
            created_at="2026-06-25T10:00:00+00:00",
            commit_metadata={"approval_protocol": "two_reviewer_fixture"},
        )

        revision = result.canonical_graph_revision
        self.assertIsNotNone(revision)
        self.assertEqual(revision.ontology_revision_id, "ontology_rev_commit_001")
        self.assertEqual(revision.policy_ids, _policy_pins().policy_ids())
        self.assertEqual(
            revision.source_candidate_atom_ids,
            [source_atom.candidate_atom_id, target_atom.candidate_atom_id],
        )
        self.assertEqual(revision.source_candidate_relation_ids, [relation.candidate_relation_id])
        self.assertEqual(
            revision.commit_metadata["review_decision_ids"],
            ["review_decision_001", "review_decision_002"],
        )

        committed_source_atom = next(
            atom for atom in result.canonical_atoms if atom.canonical_text == source_atom.label
        )
        self.assertEqual(
            committed_source_atom.source_candidate_atom_ids, [source_atom.candidate_atom_id]
        )
        self.assertEqual(
            committed_source_atom.source_observation_ids, source_atom.source_observation_ids
        )
        self.assertEqual(committed_source_atom.source_refs, [source_ref])
        self.assertEqual(committed_source_atom.evidence_snapshot_ids, ["ev_commit_001"])
        self.assertEqual(committed_source_atom.citations, [citation])
        self.assertEqual(
            committed_source_atom.extraction_policy_id, _policy_pins().extraction_policy_id
        )
        self.assertEqual(
            committed_source_atom.granularity_policy_id, _policy_pins().granularity_policy_id
        )
        self.assertEqual(
            committed_source_atom.metadata["ontology_revision_id"],
            "ontology_rev_commit_001",
        )

        committed_relation = result.canonical_relations[0]
        self.assertIn(committed_relation.source_id, revision.canonical_atom_ids)
        self.assertIn(committed_relation.target_id, revision.canonical_atom_ids)
        self.assertEqual(
            committed_relation.source_candidate_relation_ids, [relation.candidate_relation_id]
        )
        self.assertEqual(committed_relation.ontology_revision_id, "ontology_rev_commit_001")
        self.assertEqual(committed_relation.evidence_snapshot_ids, ["ev_commit_relation_001"])

        restarted = CanonicalGraphStore(temp_dir)
        self.assertEqual(
            restarted.get_atom(committed_source_atom.canonical_atom_id).to_dict(),
            committed_source_atom.to_dict(),
        )
        self.assertEqual(
            restarted.get_relation(committed_relation.canonical_relation_id).to_dict(),
            committed_relation.to_dict(),
        )
        self.assertEqual(
            restarted.get_revision(revision.canonical_graph_revision_id).to_dict(),
            revision.to_dict(),
        )
        self.assertEqual(atom_store.get(source_atom.candidate_atom_id).status, "approved")
        self.assertFalse(hasattr(canonical_store, "create"))
        graph_paths = [
            path.relative_to(temp_dir / "graph").as_posix()
            for path in (temp_dir / "graph").rglob("*")
        ]
        self.assertFalse(any("user-graph" in path or "wiki" in path for path in graph_paths))

    def test_pending_rejected_and_deferred_candidates_cannot_commit(self) -> None:
        for status in ("pending_review", "rejected", "deferred"):
            temp_dir = _paths.fresh_test_dir(f"canonical-commit-status-{status}")
            atom_store = CandidateAtomStore(temp_dir)
            canonical_store = CanonicalGraphStore(temp_dir)
            candidate = atom_store.create(
                _candidate_atom(f"catom_commit_{status}", f"{status} claim", status=status)
            )

            with self.subTest(status=status):
                with self.assertRaises(ContractValidationError):
                    commit_reviewed_candidates_to_canonical_graph(
                        candidate_atom_store=atom_store,
                        canonical_graph_store=canonical_store,
                        scope_type="workspace",
                        scope_id="workspace_formowl",
                        ontology_revision_id="ontology_rev_commit_001",
                        created_by="user_reviewer_001",
                        policy_pins=_policy_pins(),
                        candidate_atom_ids=[candidate.candidate_atom_id],
                        review_decision_ids=["review_decision_001"],
                        created_at="2026-06-25T10:00:00+00:00",
                    )
                self.assertEqual(_canonical_json_paths(temp_dir), [])

    def test_empty_canonical_commit_is_rejected_without_side_effects(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-empty")
        atom_store = CandidateAtomStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)

        with self.assertRaises(ContractValidationError):
            commit_reviewed_candidates_to_canonical_graph(
                candidate_atom_store=atom_store,
                canonical_graph_store=canonical_store,
                scope_type="workspace",
                scope_id="workspace_formowl",
                ontology_revision_id="ontology_rev_commit_001",
                created_by="user_reviewer_001",
                policy_pins=_policy_pins(),
                candidate_atom_ids=[],
                review_decision_ids=["review_decision_001"],
                created_at="2026-06-25T10:00:00+00:00",
            )
        self.assertEqual(_canonical_json_paths(temp_dir), [])

    def test_relation_endpoints_must_be_resolved_in_the_canonical_commit(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-unresolved-relation")
        atom_store = CandidateAtomStore(temp_dir)
        relation_store = CandidateRelationStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        source_atom = atom_store.create(_candidate_atom("catom_commit_source", "Source claim"))
        target_atom = atom_store.create(_candidate_atom("catom_commit_target", "Target claim"))
        relation = relation_store.create(
            _candidate_relation(
                "crel_commit_missing_endpoint",
                source_atom.candidate_atom_id,
                target_atom.candidate_atom_id,
            )
        )

        with self.assertRaises(ContractValidationError):
            commit_reviewed_candidates_to_canonical_graph(
                candidate_atom_store=atom_store,
                candidate_relation_store=relation_store,
                canonical_graph_store=canonical_store,
                scope_type="workspace",
                scope_id="workspace_formowl",
                ontology_revision_id="ontology_rev_commit_001",
                created_by="user_reviewer_001",
                policy_pins=_policy_pins(),
                candidate_atom_ids=[source_atom.candidate_atom_id],
                candidate_relation_ids=[relation.candidate_relation_id],
                review_decision_ids=["review_decision_001"],
                created_at="2026-06-25T10:00:00+00:00",
            )
        self.assertEqual(_canonical_json_paths(temp_dir), [])

    def test_incremental_commit_retains_parent_revision_membership(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-parent-membership")
        atom_store = CandidateAtomStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        first_atom = atom_store.create(_candidate_atom("catom_commit_first", "First claim"))
        second_atom = atom_store.create(_candidate_atom("catom_commit_second", "Second claim"))

        first_result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[first_atom.candidate_atom_id],
            review_decision_ids=["review_decision_001"],
            created_at="2026-06-25T10:00:00+00:00",
        )

        second_result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[second_atom.candidate_atom_id],
            parent_revision_id=first_result.canonical_graph_revision.canonical_graph_revision_id,
            review_decision_ids=["review_decision_002"],
            created_at="2026-06-25T10:05:00+00:00",
        )

        first_revision = first_result.canonical_graph_revision
        second_revision = second_result.canonical_graph_revision
        self.assertEqual(
            second_revision.parent_revision_id, first_revision.canonical_graph_revision_id
        )
        self.assertEqual(
            second_revision.canonical_atom_ids,
            sorted(
                [
                    first_result.canonical_atoms[0].canonical_atom_id,
                    second_result.canonical_atoms[0].canonical_atom_id,
                ]
            ),
        )
        self.assertEqual(
            canonical_store.get_revision(second_revision.canonical_graph_revision_id).to_dict(),
            second_revision.to_dict(),
        )
        self.assertEqual(
            canonical_store.get_revision(first_revision.canonical_graph_revision_id).to_dict(),
            first_revision.to_dict(),
        )

    def test_incremental_commit_retains_parent_entities_and_relations(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-parent-all-membership")
        atom_store = CandidateAtomStore(temp_dir)
        relation_store = CandidateRelationStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        source_atom = atom_store.create(_candidate_atom("catom_commit_source", "Source claim"))
        target_atom = atom_store.create(_candidate_atom("catom_commit_target", "Target claim"))
        next_atom = atom_store.create(_candidate_atom("catom_commit_next", "Next claim"))
        first_relation = relation_store.create(
            _candidate_relation(
                "crel_commit_existing_parent_relation",
                source_atom.candidate_atom_id,
                target_atom.candidate_atom_id,
            )
        )

        first_result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            candidate_relation_store=relation_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[source_atom.candidate_atom_id, target_atom.candidate_atom_id],
            candidate_relation_ids=[first_relation.candidate_relation_id],
            review_decision_ids=["review_decision_001"],
            created_at="2026-06-25T10:00:00+00:00",
        )
        parent_entity = _canonical_entity(
            "parent_concept",
            source_candidate_atom_id=source_atom.candidate_atom_id,
        )
        parent_entity_relation = _canonical_relation(
            "crel_parent_entity_relation",
            source_id=parent_entity.canonical_entity_id,
            target_id=first_result.canonical_atoms[0].canonical_atom_id,
        )
        parent_payload = first_result.canonical_graph_revision.to_dict()
        parent_payload.update(
            {
                "canonical_graph_revision_id": "graphrev_parent_with_entity_relation",
                "canonical_entity_ids": [parent_entity.canonical_entity_id],
                "canonical_relation_ids": sorted(
                    [
                        first_result.canonical_relations[0].canonical_relation_id,
                        parent_entity_relation.canonical_relation_id,
                    ]
                ),
                "created_at": "2026-06-25T10:02:00+00:00",
                "source_candidate_relation_ids": [
                    first_relation.candidate_relation_id,
                    "crel_parent_entity_relation",
                ],
            }
        )
        parent_revision = CanonicalGraphRevision.from_dict(parent_payload)
        canonical_store._persist_reviewed_commit(
            atoms=[],
            entities=[parent_entity],
            relations=[parent_entity_relation],
            revision=parent_revision,
        )

        child_result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[next_atom.candidate_atom_id],
            parent_revision_id=parent_revision.canonical_graph_revision_id,
            review_decision_ids=["review_decision_002"],
            created_at="2026-06-25T10:05:00+00:00",
        )

        self.assertEqual(
            child_result.canonical_graph_revision.canonical_atom_ids,
            sorted(
                [
                    first_result.canonical_atoms[0].canonical_atom_id,
                    first_result.canonical_atoms[1].canonical_atom_id,
                    child_result.canonical_atoms[0].canonical_atom_id,
                ]
            ),
        )
        self.assertEqual(
            child_result.canonical_graph_revision.canonical_entity_ids,
            [parent_entity.canonical_entity_id],
        )
        self.assertEqual(
            child_result.canonical_graph_revision.canonical_relation_ids,
            sorted(
                [
                    first_result.canonical_relations[0].canonical_relation_id,
                    parent_entity_relation.canonical_relation_id,
                ]
            ),
        )

    def test_incremental_relation_can_resolve_against_parent_canonical_endpoint(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-parent-relation-endpoint")
        atom_store = CandidateAtomStore(temp_dir)
        relation_store = CandidateRelationStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        source_atom = atom_store.create(_candidate_atom("catom_commit_source", "Source claim"))
        target_atom = atom_store.create(_candidate_atom("catom_commit_target", "Target claim"))

        first_result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[source_atom.candidate_atom_id],
            review_decision_ids=["review_decision_001"],
            created_at="2026-06-25T10:00:00+00:00",
        )
        relation = relation_store.create(
            _candidate_relation(
                "crel_commit_parent_endpoint",
                source_atom.candidate_atom_id,
                target_atom.candidate_atom_id,
            )
        )

        second_result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            candidate_relation_store=relation_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[target_atom.candidate_atom_id],
            candidate_relation_ids=[relation.candidate_relation_id],
            parent_revision_id=first_result.canonical_graph_revision.canonical_graph_revision_id,
            review_decision_ids=["review_decision_002"],
            created_at="2026-06-25T10:05:00+00:00",
        )

        committed_relation = second_result.canonical_relations[0]
        self.assertEqual(
            committed_relation.source_id,
            first_result.canonical_atoms[0].canonical_atom_id,
        )
        self.assertEqual(
            committed_relation.target_id,
            second_result.canonical_atoms[0].canonical_atom_id,
        )
        self.assertEqual(
            second_result.canonical_graph_revision.canonical_atom_ids,
            sorted([committed_relation.source_id, committed_relation.target_id]),
        )
        self.assertEqual(
            second_result.canonical_graph_revision.canonical_relation_ids,
            [committed_relation.canonical_relation_id],
        )

    def test_relation_only_commit_can_resolve_both_endpoints_from_parent_revision(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-parent-relation-only")
        atom_store = CandidateAtomStore(temp_dir)
        relation_store = CandidateRelationStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        source_atom = atom_store.create(_candidate_atom("catom_commit_source", "Source claim"))
        target_atom = atom_store.create(_candidate_atom("catom_commit_target", "Target claim"))

        first_result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[source_atom.candidate_atom_id, target_atom.candidate_atom_id],
            review_decision_ids=["review_decision_001"],
            created_at="2026-06-25T10:00:00+00:00",
        )
        relation = relation_store.create(
            _candidate_relation(
                "crel_commit_parent_only",
                source_atom.candidate_atom_id,
                target_atom.candidate_atom_id,
            )
        )

        second_result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            candidate_relation_store=relation_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[],
            candidate_relation_ids=[relation.candidate_relation_id],
            parent_revision_id=first_result.canonical_graph_revision.canonical_graph_revision_id,
            review_decision_ids=["review_decision_002"],
            created_at="2026-06-25T10:05:00+00:00",
        )

        committed_relation = second_result.canonical_relations[0]
        self.assertEqual(second_result.canonical_atoms, [])
        self.assertEqual(
            {committed_relation.source_id, committed_relation.target_id},
            {atom.canonical_atom_id for atom in first_result.canonical_atoms},
        )
        self.assertEqual(
            second_result.canonical_graph_revision.canonical_atom_ids,
            first_result.canonical_graph_revision.canonical_atom_ids,
        )
        self.assertEqual(
            second_result.canonical_graph_revision.canonical_relation_ids,
            [committed_relation.canonical_relation_id],
        )

    def test_parent_relation_endpoint_must_still_be_revision_member(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-parent-relation-corrupt")
        atom_store = CandidateAtomStore(temp_dir)
        relation_store = CandidateRelationStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        source_atom = atom_store.create(_candidate_atom("catom_commit_source", "Source claim"))
        target_atom = atom_store.create(_candidate_atom("catom_commit_target", "Target claim"))
        next_atom = atom_store.create(_candidate_atom("catom_commit_next", "Next claim"))
        relation = relation_store.create(
            _candidate_relation(
                "crel_commit_corrupt_parent",
                source_atom.candidate_atom_id,
                target_atom.candidate_atom_id,
            )
        )
        first_result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            candidate_relation_store=relation_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[source_atom.candidate_atom_id, target_atom.candidate_atom_id],
            candidate_relation_ids=[relation.candidate_relation_id],
            review_decision_ids=["review_decision_001"],
            created_at="2026-06-25T10:00:00+00:00",
        )

        corrupt_parent_payload = first_result.canonical_graph_revision.to_dict()
        corrupt_parent_payload.update(
            {
                "canonical_graph_revision_id": "graphrev_corrupt_parent",
                "canonical_atom_ids": [first_result.canonical_atoms[0].canonical_atom_id],
                "created_at": "2026-06-25T10:02:00+00:00",
            }
        )
        corrupt_parent = CanonicalGraphRevision.from_dict(corrupt_parent_payload)
        canonical_store._persist_reviewed_commit(
            atoms=[],
            entities=[],
            relations=[],
            revision=corrupt_parent,
        )

        with self.assertRaises(ContractValidationError):
            commit_reviewed_candidates_to_canonical_graph(
                candidate_atom_store=atom_store,
                canonical_graph_store=canonical_store,
                scope_type="workspace",
                scope_id="workspace_formowl",
                ontology_revision_id="ontology_rev_commit_001",
                created_by="user_reviewer_001",
                policy_pins=_policy_pins(),
                candidate_atom_ids=[next_atom.candidate_atom_id],
                parent_revision_id=corrupt_parent.canonical_graph_revision_id,
                review_decision_ids=["review_decision_002"],
                created_at="2026-06-25T10:05:00+00:00",
            )
        self.assertEqual(
            {atom.canonical_atom_id for atom in canonical_store.list_atoms()},
            {atom.canonical_atom_id for atom in first_result.canonical_atoms},
        )

    def test_missing_ontology_policy_or_review_pins_fail_without_canonical_side_effects(
        self,
    ) -> None:
        cases = [
            ("ontology", {"ontology_revision_id": ""}),
            (
                "policy",
                {"policy_pins": _policy_pins(extraction_policy_id="")},
            ),
            ("review", {"review_decision_ids": []}),
        ]
        for name, overrides in cases:
            temp_dir = _paths.fresh_test_dir(f"canonical-commit-missing-{name}")
            atom_store = CandidateAtomStore(temp_dir)
            canonical_store = CanonicalGraphStore(temp_dir)
            candidate = atom_store.create(
                _candidate_atom(f"catom_commit_missing_{name}", "Pinned claim")
            )
            kwargs = {
                "candidate_atom_store": atom_store,
                "canonical_graph_store": canonical_store,
                "scope_type": "workspace",
                "scope_id": "workspace_formowl",
                "ontology_revision_id": "ontology_rev_commit_001",
                "created_by": "user_reviewer_001",
                "policy_pins": _policy_pins(),
                "candidate_atom_ids": [candidate.candidate_atom_id],
                "review_decision_ids": ["review_decision_001"],
                "created_at": "2026-06-25T10:00:00+00:00",
            }
            kwargs.update(overrides)

            with self.subTest(name=name):
                with self.assertRaises(ContractValidationError):
                    commit_reviewed_candidates_to_canonical_graph(**kwargs)
                self.assertEqual(_canonical_json_paths(temp_dir), [])

    def test_raw_candidate_values_are_rejected_without_echo_or_canonical_write(self) -> None:
        cases = [
            _candidate_atom("catom_commit_raw_label", "/tmp/customer-secret.pdf"),
            _candidate_atom(
                "catom_commit_raw_locator",
                "Safe label",
                properties={"source": "formowl://asset/asset_secret_001"},
            ),
            _candidate_atom(
                "catom_commit_s3_locator",
                "Safe label",
                properties={"source": "s3://private-bucket/customer-secret.pdf"},
            ),
        ]
        for candidate in cases:
            temp_dir = _paths.fresh_test_dir(f"canonical-commit-raw-{candidate.candidate_atom_id}")
            atom_store = CandidateAtomStore(temp_dir)
            canonical_store = CanonicalGraphStore(temp_dir)
            atom_store.create(candidate)

            with self.subTest(candidate=candidate.candidate_atom_id):
                with self.assertRaises(ContractValidationError) as ctx:
                    commit_reviewed_candidates_to_canonical_graph(
                        candidate_atom_store=atom_store,
                        canonical_graph_store=canonical_store,
                        scope_type="workspace",
                        scope_id="workspace_formowl",
                        ontology_revision_id="ontology_rev_commit_001",
                        created_by="user_reviewer_001",
                        policy_pins=_policy_pins(),
                        candidate_atom_ids=[candidate.candidate_atom_id],
                        review_decision_ids=["review_decision_001"],
                        created_at="2026-06-25T10:00:00+00:00",
                    )
                self.assertNotIn("/tmp/customer-secret.pdf", str(ctx.exception))
                self.assertNotIn("formowl://asset", str(ctx.exception))
                self.assertNotIn("s3://private-bucket", str(ctx.exception))
                self.assertEqual(_canonical_json_paths(temp_dir), [])

    def test_write_failure_rolls_back_partial_canonical_side_effects(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-write-rollback")
        atom_store = CandidateAtomStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        candidate = atom_store.create(_candidate_atom("catom_commit_rollback", "Rollback claim"))
        original_write_json = storage_records._write_json

        def fail_on_revision(path, payload):
            if "canonical-graph-revisions" in path.as_posix():
                raise OSError("simulated revision write failure")
            original_write_json(path, payload)

        with mock.patch.object(storage_records, "_write_json", side_effect=fail_on_revision):
            with self.assertRaises(OSError):
                commit_reviewed_candidates_to_canonical_graph(
                    candidate_atom_store=atom_store,
                    canonical_graph_store=canonical_store,
                    scope_type="workspace",
                    scope_id="workspace_formowl",
                    ontology_revision_id="ontology_rev_commit_001",
                    created_by="user_reviewer_001",
                    policy_pins=_policy_pins(),
                    candidate_atom_ids=[candidate.candidate_atom_id],
                    review_decision_ids=["review_decision_001"],
                    created_at="2026-06-25T10:00:00+00:00",
                )

        self.assertEqual(_canonical_json_paths(temp_dir), [])

    def test_duplicate_canonical_relation_ids_fail_without_lineage_overwrite(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-duplicate-relation")
        atom_store = CandidateAtomStore(temp_dir)
        relation_store = CandidateRelationStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        source_atom = atom_store.create(_candidate_atom("catom_commit_source", "Source claim"))
        target_atom = atom_store.create(_candidate_atom("catom_commit_target", "Target claim"))
        first_relation = relation_store.create(
            _candidate_relation(
                "crel_commit_duplicate_first",
                source_atom.candidate_atom_id,
                target_atom.candidate_atom_id,
            )
        )
        second_relation = relation_store.create(
            _candidate_relation(
                "crel_commit_duplicate_second",
                source_atom.candidate_atom_id,
                target_atom.candidate_atom_id,
            )
        )

        with self.assertRaises(ContractValidationError):
            commit_reviewed_candidates_to_canonical_graph(
                candidate_atom_store=atom_store,
                candidate_relation_store=relation_store,
                canonical_graph_store=canonical_store,
                scope_type="workspace",
                scope_id="workspace_formowl",
                ontology_revision_id="ontology_rev_commit_001",
                created_by="user_reviewer_001",
                policy_pins=_policy_pins(),
                candidate_atom_ids=[source_atom.candidate_atom_id, target_atom.candidate_atom_id],
                candidate_relation_ids=[
                    first_relation.candidate_relation_id,
                    second_relation.candidate_relation_id,
                ],
                review_decision_ids=["review_decision_001"],
                created_at="2026-06-25T10:00:00+00:00",
            )

        self.assertEqual(_canonical_json_paths(temp_dir), [])

    def test_cross_commit_duplicate_relation_id_cannot_overwrite_prior_lineage(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-cross-duplicate-relation")
        atom_store = CandidateAtomStore(temp_dir)
        relation_store = CandidateRelationStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        source_atom = atom_store.create(_candidate_atom("catom_commit_source", "Source claim"))
        target_atom = atom_store.create(_candidate_atom("catom_commit_target", "Target claim"))
        first_relation = relation_store.create(
            _candidate_relation(
                "crel_commit_cross_first",
                source_atom.candidate_atom_id,
                target_atom.candidate_atom_id,
                source_observation_ids=["obs_relation_first"],
            )
        )
        first_result = commit_reviewed_candidates_to_canonical_graph(
            candidate_atom_store=atom_store,
            candidate_relation_store=relation_store,
            canonical_graph_store=canonical_store,
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_commit_001",
            created_by="user_reviewer_001",
            policy_pins=_policy_pins(),
            candidate_atom_ids=[source_atom.candidate_atom_id, target_atom.candidate_atom_id],
            candidate_relation_ids=[first_relation.candidate_relation_id],
            review_decision_ids=["review_decision_001"],
            created_at="2026-06-25T10:00:00+00:00",
        )
        stored_relation = first_result.canonical_relations[0]

        second_relation = relation_store.create(
            _candidate_relation(
                "crel_commit_cross_second",
                source_atom.candidate_atom_id,
                target_atom.candidate_atom_id,
                source_observation_ids=["obs_relation_second"],
            )
        )
        with self.assertRaises(ContractValidationError):
            commit_reviewed_candidates_to_canonical_graph(
                candidate_atom_store=atom_store,
                candidate_relation_store=relation_store,
                canonical_graph_store=canonical_store,
                scope_type="workspace",
                scope_id="workspace_formowl",
                ontology_revision_id="ontology_rev_commit_001",
                created_by="user_reviewer_001",
                policy_pins=_policy_pins(),
                candidate_atom_ids=[source_atom.candidate_atom_id, target_atom.candidate_atom_id],
                candidate_relation_ids=[second_relation.candidate_relation_id],
                review_decision_ids=["review_decision_002"],
                created_at="2026-06-25T10:05:00+00:00",
            )

        self.assertEqual(
            canonical_store.get_relation(stored_relation.canonical_relation_id).to_dict(),
            stored_relation.to_dict(),
        )
        self.assertEqual(
            canonical_store.get_relation(
                stored_relation.canonical_relation_id
            ).source_candidate_relation_ids,
            [first_relation.candidate_relation_id],
        )
        self.assertEqual(
            canonical_store.get_relation(
                stored_relation.canonical_relation_id
            ).source_observation_ids,
            ["obs_relation_first"],
        )

    def test_lineage_for_unknown_candidates_fails_without_canonical_write(self) -> None:
        temp_dir = _paths.fresh_test_dir("canonical-commit-unknown-lineage")
        atom_store = CandidateAtomStore(temp_dir)
        canonical_store = CanonicalGraphStore(temp_dir)
        candidate = atom_store.create(_candidate_atom("catom_commit_known", "Known claim"))

        with self.assertRaises(ContractValidationError):
            commit_reviewed_candidates_to_canonical_graph(
                candidate_atom_store=atom_store,
                canonical_graph_store=canonical_store,
                scope_type="workspace",
                scope_id="workspace_formowl",
                ontology_revision_id="ontology_rev_commit_001",
                created_by="user_reviewer_001",
                policy_pins=_policy_pins(),
                candidate_atom_ids=[candidate.candidate_atom_id],
                evidence_snapshot_ids_by_candidate_id={"catom_unknown": ["ev_commit_001"]},
                review_decision_ids=["review_decision_001"],
                created_at="2026-06-25T10:00:00+00:00",
            )
        self.assertEqual(_canonical_json_paths(temp_dir), [])

    def test_commit_ids_are_deterministic_for_same_reviewed_inputs(self) -> None:
        results = []
        for name in ("a", "b"):
            temp_dir = _paths.fresh_test_dir(f"canonical-commit-deterministic-{name}")
            atom_store = CandidateAtomStore(temp_dir)
            canonical_store = CanonicalGraphStore(temp_dir)
            candidate = atom_store.create(
                _candidate_atom("catom_commit_deterministic", "Stable claim")
            )
            results.append(
                commit_reviewed_candidates_to_canonical_graph(
                    candidate_atom_store=atom_store,
                    canonical_graph_store=canonical_store,
                    scope_type="workspace",
                    scope_id="workspace_formowl",
                    ontology_revision_id="ontology_rev_commit_001",
                    created_by="user_reviewer_001",
                    policy_pins=_policy_pins(),
                    candidate_atom_ids=[candidate.candidate_atom_id],
                    review_decision_ids=["review_decision_001"],
                    created_at="2026-06-25T10:00:00+00:00",
                )
            )

        self.assertEqual(
            results[0].canonical_atoms[0].canonical_atom_id,
            results[1].canonical_atoms[0].canonical_atom_id,
        )
        self.assertEqual(
            results[0].canonical_graph_revision.canonical_graph_revision_id,
            results[1].canonical_graph_revision.canonical_graph_revision_id,
        )


def _policy_pins(**overrides: str) -> CanonicalCommitPolicyPins:
    values = {
        "extraction_policy_id": "extraction_policy_commit_001",
        "granularity_policy_id": "granularity_policy_commit_001",
        "entity_resolution_policy_id": "entity_resolution_policy_commit_001",
        "relation_resolution_policy_id": "relation_resolution_policy_commit_001",
        "lifecycle_policy_id": "lifecycle_policy_commit_001",
    }
    values.update(overrides)
    return CanonicalCommitPolicyPins(**values)


def _candidate_atom(
    candidate_atom_id: str,
    label: str,
    *,
    status: str = "approved",
    properties: dict[str, object] | None = None,
) -> CandidateAtom:
    return CandidateAtom(
        candidate_atom_id=candidate_atom_id,
        source_observation_ids=[f"obs_{candidate_atom_id}"],
        atom_type="claim",
        label=label,
        properties=properties or {"granularity_level": "claim"},
        confidence=0.87,
        extractor_run_id="run_commit_001",
        status=status,
        requires_review=True,
        source_semantic_metadata_ids=[f"sem_{candidate_atom_id}"],
        created_at="2026-06-25T09:00:00+00:00",
    )


def _candidate_relation(
    candidate_relation_id: str,
    source_candidate_atom_id: str,
    target_candidate_atom_id: str,
    *,
    status: str = "approved",
    source_observation_ids: list[str] | None = None,
) -> CandidateRelation:
    return CandidateRelation(
        candidate_relation_id=candidate_relation_id,
        source_candidate_atom_id=source_candidate_atom_id,
        target_candidate_atom_id=target_candidate_atom_id,
        relation_type="supports",
        source_observation_ids=source_observation_ids or ["obs_relation_commit_001"],
        properties={"basis": "reviewed relation candidate"},
        confidence=0.79,
        extractor_run_id="run_commit_001",
        status=status,
        requires_review=True,
        source_semantic_metadata_ids=["sem_relation_commit_001"],
        created_at="2026-06-25T09:00:00+00:00",
    )


def _canonical_entity(
    label: str,
    *,
    source_candidate_atom_id: str,
) -> CanonicalEntity:
    return CanonicalEntity(
        canonical_entity_id=stable_canonical_entity_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            entity_type="Concept",
            canonical_label=label,
        ),
        scope_type="workspace",
        scope_id="workspace_formowl",
        entity_type="Concept",
        canonical_label=label,
        status="active",
        source_candidate_atom_ids=[source_candidate_atom_id],
        source_observation_ids=[f"obs_{source_candidate_atom_id}"],
        source_refs=[
            SourceRef(
                source_system="formowl_candidate_graph",
                source_type="candidate_atom",
                source_id=source_candidate_atom_id,
            ).to_dict()
        ],
        evidence_snapshot_ids=[],
        citations=[],
        confidence=0.84,
        ontology_revision_id="ontology_rev_commit_001",
        created_at="2026-06-25T10:01:00+00:00",
        aliases=[],
        metadata={"seeded_for_parent_membership_test": True},
    )


def _canonical_relation(
    source_candidate_relation_id: str,
    *,
    source_id: str,
    target_id: str,
) -> CanonicalRelation:
    return CanonicalRelation(
        canonical_relation_id=stable_canonical_relation_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            source_id=source_id,
            target_id=target_id,
            relation_type="describes",
            properties={"basis": "seeded parent membership fixture"},
        ),
        scope_type="workspace",
        scope_id="workspace_formowl",
        source_id=source_id,
        target_id=target_id,
        relation_type="describes",
        status="active",
        source_candidate_relation_ids=[source_candidate_relation_id],
        source_observation_ids=[f"obs_{source_candidate_relation_id}"],
        source_refs=[
            SourceRef(
                source_system="formowl_candidate_graph",
                source_type="candidate_relation",
                source_id=source_candidate_relation_id,
            ).to_dict()
        ],
        evidence_snapshot_ids=[],
        citations=[],
        confidence=0.81,
        ontology_revision_id="ontology_rev_commit_001",
        created_at="2026-06-25T10:01:00+00:00",
        properties={"basis": "seeded parent membership fixture"},
    )


def _canonical_json_paths(temp_dir) -> list[str]:
    graph_root = temp_dir / "graph"
    if not graph_root.exists():
        return []
    return sorted(
        path.relative_to(graph_root).as_posix()
        for path in graph_root.rglob("*.json")
        if "canonical-" in path.relative_to(graph_root).as_posix()
    )


if __name__ == "__main__":
    unittest.main()
