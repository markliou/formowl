from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    CanonicalAtom,
    CanonicalEntity,
    CanonicalGraphRevision,
    CanonicalRelation,
    ContractValidationError,
    SourceRef,
    sha256_json,
    stable_canonical_atom_id,
    stable_canonical_entity_id,
    stable_canonical_graph_revision_id,
    stable_canonical_relation_id,
)


class CanonicalContractTests(unittest.TestCase):
    def test_canonical_graph_contracts_round_trip(self) -> None:
        atom = CanonicalAtom.from_dict(_valid_canonical_atom())
        entity = CanonicalEntity.from_dict(_valid_canonical_entity())
        relation = CanonicalRelation.from_dict(_valid_canonical_relation())
        revision = CanonicalGraphRevision.from_dict(
            _valid_canonical_graph_revision(
                canonical_atom_ids=[atom.canonical_atom_id],
                canonical_entity_ids=[entity.canonical_entity_id],
                canonical_relation_ids=[relation.canonical_relation_id],
            )
        )

        for model in (atom, entity, relation, revision):
            data = model.to_dict()
            self.assertEqual(type(model).from_dict(data).to_dict(), data)

        self.assertEqual(revision.status, "committed")
        self.assertEqual(atom.status, "active")
        self.assertEqual(relation.source_id, entity.canonical_entity_id)

    def test_canonical_record_ids_are_stable_across_graph_revisions(self) -> None:
        atom_id = stable_canonical_atom_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            atom_type="decision",
            canonical_text="Keep canonical graph commits governed.",
            source_candidate_atom_ids=["catom_001"],
        )
        entity_id = stable_canonical_entity_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            entity_type="Concept",
            canonical_label="Governed canonical graph",
        )
        relation_id = stable_canonical_relation_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            source_id=entity_id,
            target_id=atom_id,
            relation_type="supports",
            properties={"basis": "approved candidate"},
        )

        first_revision_id = stable_canonical_graph_revision_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_001",
            canonical_atom_ids=[atom_id],
            canonical_entity_ids=[entity_id],
            canonical_relation_ids=[relation_id],
            created_at="2026-06-17T10:00:00+00:00",
        )
        second_revision_id = stable_canonical_graph_revision_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_001",
            canonical_atom_ids=[atom_id],
            canonical_entity_ids=[entity_id],
            canonical_relation_ids=[relation_id],
            created_at="2026-06-17T10:05:00+00:00",
            parent_revision_id=first_revision_id,
        )

        self.assertNotEqual(first_revision_id, second_revision_id)
        self.assertEqual(
            atom_id,
            stable_canonical_atom_id(
                scope_type="workspace",
                scope_id="workspace_formowl",
                atom_type="decision",
                canonical_text="Keep canonical graph commits governed.",
                source_candidate_atom_ids=["catom_001"],
            ),
        )
        self.assertEqual(
            entity_id,
            stable_canonical_entity_id(
                scope_type="workspace",
                scope_id="workspace_formowl",
                entity_type="Concept",
                canonical_label="Governed canonical graph",
            ),
        )
        self.assertEqual(
            relation_id,
            stable_canonical_relation_id(
                scope_type="workspace",
                scope_id="workspace_formowl",
                source_id=entity_id,
                target_id=atom_id,
                relation_type="supports",
                properties={"basis": "approved candidate"},
            ),
        )

    def test_canonical_contracts_validate_governance_and_lineage(self) -> None:
        invalid_atom_cases = [
            ("scope_id", "../workspace"),
            ("source_candidate_atom_ids", []),
            ("source_observation_ids", []),
            ("content_hash", "not-a-hash"),
            ("confidence", True),
            ("status", "pending_review"),
            ("created_at", "not-a-timestamp"),
            ("citations", [{"citation_id": "cit_001"}]),
        ]
        for field_name, invalid_value in invalid_atom_cases:
            payload = _valid_canonical_atom()
            payload[field_name] = invalid_value
            with self.subTest(model="CanonicalAtom", field_name=field_name):
                with self.assertRaises(ContractValidationError):
                    CanonicalAtom.from_dict(payload)

        invalid_entity_cases = [
            ("canonical_entity_id", "formowl://asset/entity_001"),
            ("aliases", ["Graph", 123]),
            ("metadata", []),
            ("ontology_revision_id", "ontology/rev"),
        ]
        for field_name, invalid_value in invalid_entity_cases:
            payload = _valid_canonical_entity()
            payload[field_name] = invalid_value
            with self.subTest(model="CanonicalEntity", field_name=field_name):
                with self.assertRaises(ContractValidationError):
                    CanonicalEntity.from_dict(payload)

        invalid_relation_cases = [
            ("source_id", r"C:\raw\entity"),
            ("target_id", "/tmp/atom"),
            ("source_observation_ids", []),
            ("properties", []),
        ]
        for field_name, invalid_value in invalid_relation_cases:
            payload = _valid_canonical_relation()
            payload[field_name] = invalid_value
            with self.subTest(model="CanonicalRelation", field_name=field_name):
                with self.assertRaises(ContractValidationError):
                    CanonicalRelation.from_dict(payload)

        invalid_revision_cases = [
            ("status", "active"),
            ("created_by", "users/yifan"),
            ("canonical_atom_ids", []),
            ("commit_metadata", []),
        ]
        for field_name, invalid_value in invalid_revision_cases:
            payload = _valid_canonical_graph_revision()
            if field_name == "canonical_atom_ids":
                payload["canonical_entity_ids"] = []
                payload["canonical_relation_ids"] = []
            payload[field_name] = invalid_value
            with self.subTest(model="CanonicalGraphRevision", field_name=field_name):
                with self.assertRaises(ContractValidationError):
                    CanonicalGraphRevision.from_dict(payload)


def _source_ref() -> dict[str, object]:
    return SourceRef(
        source_system="fixture_graph_review",
        source_type="candidate_atom",
        source_id="catom_001",
    ).to_dict()


def _citation() -> dict[str, object]:
    return {
        "citation_id": "cit_001",
        "source_ref": _source_ref(),
        "evidence_snapshot_id": "ev_001",
        "locator": {"type": "observation", "id": "obs_001"},
        "summary": "Approved candidate source.",
    }


def _valid_canonical_atom() -> dict[str, object]:
    canonical_text = "Keep canonical graph commits governed."
    return {
        "canonical_atom_id": stable_canonical_atom_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            atom_type="decision",
            canonical_text=canonical_text,
            source_candidate_atom_ids=["catom_001"],
        ),
        "scope_type": "workspace",
        "scope_id": "workspace_formowl",
        "atom_type": "decision",
        "canonical_text": canonical_text,
        "granularity_level": "decision",
        "status": "active",
        "source_candidate_atom_ids": ["catom_001"],
        "source_observation_ids": ["obs_001"],
        "source_refs": [_source_ref()],
        "evidence_snapshot_ids": ["ev_001"],
        "citations": [_citation()],
        "content_hash": sha256_json({"canonical_text": canonical_text}),
        "extraction_policy_id": "extraction_policy_001",
        "granularity_policy_id": "granularity_policy_001",
        "confidence": 0.91,
        "created_at": "2026-06-17T10:00:00+00:00",
        "parent_atom_ids": [],
        "child_atom_ids": [],
        "related_atom_ids": [],
        "labels": ["governance"],
        "language": "en",
        "domain": "knowledge_management",
        "metadata": {"review_state": "approved"},
    }


def _valid_canonical_entity() -> dict[str, object]:
    return {
        "canonical_entity_id": stable_canonical_entity_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            entity_type="Concept",
            canonical_label="Governed canonical graph",
        ),
        "scope_type": "workspace",
        "scope_id": "workspace_formowl",
        "entity_type": "Concept",
        "canonical_label": "Governed canonical graph",
        "status": "active",
        "source_candidate_atom_ids": ["catom_001"],
        "source_observation_ids": ["obs_001"],
        "source_refs": [_source_ref()],
        "evidence_snapshot_ids": ["ev_001"],
        "citations": [_citation()],
        "confidence": 0.86,
        "ontology_revision_id": "ontology_rev_001",
        "created_at": "2026-06-17T10:00:00+00:00",
        "aliases": ["canonical graph"],
        "metadata": {"core_supertype": "Concept"},
    }


def _valid_canonical_relation() -> dict[str, object]:
    source_id = _valid_canonical_entity()["canonical_entity_id"]
    target_id = _valid_canonical_atom()["canonical_atom_id"]
    return {
        "canonical_relation_id": stable_canonical_relation_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            source_id=str(source_id),
            target_id=str(target_id),
            relation_type="supports",
            properties={"basis": "approved candidate"},
        ),
        "scope_type": "workspace",
        "scope_id": "workspace_formowl",
        "source_id": source_id,
        "target_id": target_id,
        "relation_type": "supports",
        "status": "active",
        "source_candidate_relation_ids": ["crel_001"],
        "source_observation_ids": ["obs_001"],
        "source_refs": [_source_ref()],
        "evidence_snapshot_ids": ["ev_001"],
        "citations": [_citation()],
        "confidence": 0.82,
        "ontology_revision_id": "ontology_rev_001",
        "created_at": "2026-06-17T10:00:00+00:00",
        "properties": {"basis": "approved candidate"},
    }


def _valid_canonical_graph_revision(
    *,
    canonical_atom_ids: list[str] | None = None,
    canonical_entity_ids: list[str] | None = None,
    canonical_relation_ids: list[str] | None = None,
) -> dict[str, object]:
    atom_ids = canonical_atom_ids or [_valid_canonical_atom()["canonical_atom_id"]]
    entity_ids = canonical_entity_ids or [_valid_canonical_entity()["canonical_entity_id"]]
    relation_ids = canonical_relation_ids or [_valid_canonical_relation()["canonical_relation_id"]]
    created_at = "2026-06-17T10:00:00+00:00"
    return {
        "canonical_graph_revision_id": stable_canonical_graph_revision_id(
            scope_type="workspace",
            scope_id="workspace_formowl",
            ontology_revision_id="ontology_rev_001",
            canonical_atom_ids=[str(item) for item in atom_ids],
            canonical_entity_ids=[str(item) for item in entity_ids],
            canonical_relation_ids=[str(item) for item in relation_ids],
            created_at=created_at,
        ),
        "scope_type": "workspace",
        "scope_id": "workspace_formowl",
        "ontology_revision_id": "ontology_rev_001",
        "status": "committed",
        "canonical_atom_ids": atom_ids,
        "canonical_entity_ids": entity_ids,
        "canonical_relation_ids": relation_ids,
        "created_at": created_at,
        "created_by": "user_yifan",
        "source_candidate_atom_ids": ["catom_001"],
        "source_candidate_relation_ids": ["crel_001"],
        "policy_ids": ["granularity_policy_001"],
        "commit_metadata": {"approval": "fixture_review"},
    }


if __name__ == "__main__":
    unittest.main()
