from __future__ import annotations

from dataclasses import replace
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    CandidateAtom,
    CandidateRelation,
    ContractValidationError,
    SemanticMetadata,
)
from formowl_graph.storage import (
    CandidateAtomStore,
    CandidateRelationStore,
    SemanticMetadataStore,
)


class GraphRecordStoreTests(unittest.TestCase):
    def test_create_get_list_records_persist_after_store_restart(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-record-stores")
        records = _valid_graph_records()

        self.assertEqual(
            SemanticMetadataStore(temp_dir).create(records.semantic_metadata).to_dict(),
            records.semantic_metadata.to_dict(),
        )
        self.assertEqual(
            CandidateAtomStore(temp_dir).create(records.candidate_atom).to_dict(),
            records.candidate_atom.to_dict(),
        )
        self.assertEqual(
            CandidateRelationStore(temp_dir).create(records.candidate_relation).to_dict(),
            records.candidate_relation.to_dict(),
        )

        restarted_semantic_store = SemanticMetadataStore(temp_dir)
        restarted_atom_store = CandidateAtomStore(temp_dir)
        restarted_relation_store = CandidateRelationStore(temp_dir)

        self.assertEqual(
            restarted_semantic_store.get(records.semantic_metadata.semantic_metadata_id).to_dict(),
            records.semantic_metadata.to_dict(),
        )
        self.assertEqual(
            restarted_atom_store.get(records.candidate_atom.candidate_atom_id).to_dict(),
            records.candidate_atom.to_dict(),
        )
        self.assertEqual(
            restarted_relation_store.get(
                records.candidate_relation.candidate_relation_id,
            ).to_dict(),
            records.candidate_relation.to_dict(),
        )
        self.assertEqual(
            [item.to_dict() for item in restarted_semantic_store.list()],
            [records.semantic_metadata.to_dict()],
        )
        self.assertEqual(
            [item.to_dict() for item in restarted_atom_store.list()],
            [records.candidate_atom.to_dict()],
        )
        self.assertEqual(
            [item.to_dict() for item in restarted_relation_store.list()],
            [records.candidate_relation.to_dict()],
        )

        graph_root = temp_dir / "graph"
        directory_names = {child.name for child in graph_root.iterdir() if child.is_dir()}
        self.assertEqual(
            directory_names,
            {"semantic-metadata", "candidate-atoms", "candidate-relations"},
        )
        self.assertFalse(any("canonical" in name for name in directory_names))

    def test_create_accepts_dict_payloads_and_validates_contracts(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-record-stores-dict-validation")
        records = _valid_graph_records()

        self.assertEqual(
            SemanticMetadataStore(temp_dir)
            .create(records.semantic_metadata.to_dict())
            .to_dict(),
            records.semantic_metadata.to_dict(),
        )
        self.assertEqual(
            CandidateAtomStore(temp_dir).create(records.candidate_atom.to_dict()).to_dict(),
            records.candidate_atom.to_dict(),
        )
        self.assertEqual(
            CandidateRelationStore(temp_dir)
            .create(records.candidate_relation.to_dict())
            .to_dict(),
            records.candidate_relation.to_dict(),
        )

        expected_semantic_metadata = [records.semantic_metadata.to_dict()]
        expected_atoms = [records.candidate_atom.to_dict()]
        expected_relations = [records.candidate_relation.to_dict()]

        invalid_semantic_metadata = records.semantic_metadata.to_dict()
        invalid_semantic_metadata["source_observation_ids"] = []
        invalid_atom = records.candidate_atom.to_dict()
        invalid_atom["status"] = "canonical"
        invalid_relation = records.candidate_relation.to_dict()
        invalid_relation["confidence"] = True

        with self.assertRaises(ContractValidationError):
            SemanticMetadataStore(temp_dir).create(invalid_semantic_metadata)
        with self.assertRaises(ContractValidationError):
            CandidateAtomStore(temp_dir).create(invalid_atom)
        with self.assertRaises(ContractValidationError):
            CandidateRelationStore(temp_dir).create(invalid_relation)

        self.assertEqual(
            [item.to_dict() for item in SemanticMetadataStore(temp_dir).list()],
            expected_semantic_metadata,
        )
        self.assertEqual(
            [item.to_dict() for item in CandidateAtomStore(temp_dir).list()],
            expected_atoms,
        )
        self.assertEqual(
            [item.to_dict() for item in CandidateRelationStore(temp_dir).list()],
            expected_relations,
        )

    def test_stores_reject_empty_provenance_ids_without_partial_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-record-stores-empty-provenance")
        records = _valid_graph_records()
        invalid_cases = [
            (
                SemanticMetadataStore,
                replace(records.semantic_metadata, source_observation_ids=[""]),
            ),
            (
                CandidateAtomStore,
                replace(records.candidate_atom, source_observation_ids=[""]),
            ),
            (
                CandidateAtomStore,
                replace(records.candidate_atom, source_semantic_metadata_ids=[""]),
            ),
            (
                CandidateRelationStore,
                replace(records.candidate_relation, source_observation_ids=[""]),
            ),
            (
                CandidateRelationStore,
                replace(records.candidate_relation, source_semantic_metadata_ids=[""]),
            ),
        ]

        for store_type, invalid_record in invalid_cases:
            store = store_type(temp_dir)
            with self.subTest(store_type=store_type.__name__, record=invalid_record):
                with self.assertRaises(ContractValidationError):
                    store.create(invalid_record)
                self.assertEqual(store.list(), [])

    def test_stores_reject_unsafe_record_ids_without_partial_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-record-stores-safe-ids")
        records = _valid_graph_records()
        unsafe_cases = [
            (
                SemanticMetadataStore,
                replace(records.semantic_metadata, semantic_metadata_id="../sem_escape"),
            ),
            (
                CandidateAtomStore,
                replace(records.candidate_atom, candidate_atom_id="../catom_escape"),
            ),
            (
                CandidateRelationStore,
                replace(records.candidate_relation, candidate_relation_id="../crel_escape"),
            ),
        ]

        for store_type, invalid_record in unsafe_cases:
            store = store_type(temp_dir)
            with self.subTest(store_type=store_type.__name__):
                with self.assertRaises(ValueError):
                    store.create(invalid_record)
                with self.assertRaises(ValueError):
                    store.get("../escape")
                self.assertEqual(store.list(), [])

    def test_missing_records_return_none(self) -> None:
        temp_dir = _paths.fresh_test_dir("graph-record-stores-missing")

        self.assertIsNone(SemanticMetadataStore(temp_dir).get("sem_missing"))
        self.assertIsNone(CandidateAtomStore(temp_dir).get("catom_missing"))
        self.assertIsNone(CandidateRelationStore(temp_dir).get("crel_missing"))


class _GraphRecords:
    def __init__(
        self,
        *,
        semantic_metadata: SemanticMetadata,
        candidate_atom: CandidateAtom,
        candidate_relation: CandidateRelation,
    ) -> None:
        self.semantic_metadata = semantic_metadata
        self.candidate_atom = candidate_atom
        self.candidate_relation = candidate_relation


def _valid_graph_records() -> _GraphRecords:
    created_at = "2026-06-17T10:00:00+00:00"
    semantic_metadata = SemanticMetadata(
        semantic_metadata_id="sem_record_001",
        source_observation_ids=["obs_record_001"],
        metadata_type="decision",
        value={"decision": "Keep candidate graph proposals reviewable."},
        confidence=0.82,
        extractor_run_id="run_record_001",
        requires_review=True,
        created_at=created_at,
    )
    candidate_atom = CandidateAtom(
        candidate_atom_id="catom_record_001",
        source_observation_ids=["obs_record_001"],
        source_semantic_metadata_ids=[semantic_metadata.semantic_metadata_id],
        atom_type="decision",
        label="Keep candidate graph proposals reviewable",
        properties={"basis": "semantic metadata proposal"},
        confidence=0.74,
        extractor_run_id="run_record_001",
        status="pending_review",
        requires_review=True,
        created_at=created_at,
    )
    candidate_relation = CandidateRelation(
        candidate_relation_id="crel_record_001",
        source_candidate_atom_id=candidate_atom.candidate_atom_id,
        target_candidate_atom_id="catom_record_002",
        relation_type="supports",
        source_observation_ids=["obs_record_001"],
        source_semantic_metadata_ids=[semantic_metadata.semantic_metadata_id],
        properties={"basis": "same source observation"},
        confidence=0.68,
        extractor_run_id="run_record_001",
        status="pending_review",
        requires_review=True,
        created_at=created_at,
    )
    return _GraphRecords(
        semantic_metadata=semantic_metadata,
        candidate_atom=candidate_atom,
        candidate_relation=candidate_relation,
    )


if __name__ == "__main__":
    unittest.main()
