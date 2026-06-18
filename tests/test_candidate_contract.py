from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    CandidateAtom,
    CandidateRelation,
    ContractValidationError,
    ExternalGraphImport,
    SourceRef,
    stable_candidate_atom_id,
    stable_candidate_relation_id,
    stable_external_graph_import_id,
)


class CandidateContractTests(unittest.TestCase):
    def test_candidate_graph_contracts_round_trip(self) -> None:
        created_at = "2026-06-17T10:00:00+00:00"
        atom_id = stable_candidate_atom_id(
            source_observation_ids=["obs_001"],
            atom_type="decision",
            label="Preserve source references",
            properties={"rationale": "Traceable wiki output"},
            extractor_run_id="run_001",
        )
        relation_id = stable_candidate_relation_id(
            source_candidate_atom_id=atom_id,
            target_candidate_atom_id="catom_target",
            relation_type="supports",
            source_observation_ids=["obs_001"],
            properties={"evidence": "same observation"},
            extractor_run_id="run_001",
        )
        source_ref = SourceRef(
            source_system="fixture_graph_importer",
            source_type="candidate_graph",
            source_id="import_001",
        )
        graph_import_id = stable_external_graph_import_id(
            source_system="fixture_graph_importer",
            source_ref=source_ref,
            extractor_run_id="run_001",
            imported_at=created_at,
        )
        models = [
            CandidateAtom(
                candidate_atom_id=atom_id,
                source_observation_ids=["obs_001"],
                source_semantic_metadata_ids=["sem_001"],
                atom_type="decision",
                label="Preserve source references",
                properties={"rationale": "Traceable wiki output"},
                confidence=0.74,
                extractor_run_id="run_001",
                status="pending_review",
                requires_review=True,
                created_at=created_at,
            ),
            CandidateRelation(
                candidate_relation_id=relation_id,
                source_candidate_atom_id=atom_id,
                target_candidate_atom_id="catom_target",
                relation_type="supports",
                source_observation_ids=["obs_001"],
                source_semantic_metadata_ids=["sem_001"],
                properties={"evidence": "same observation"},
                confidence=0.68,
                extractor_run_id="run_001",
                status="pending_review",
                requires_review=True,
                created_at=created_at,
            ),
            ExternalGraphImport(
                external_graph_import_id=graph_import_id,
                source_system="fixture_graph_importer",
                source_ref=source_ref,
                extractor_run_id="run_001",
                imported_at=created_at,
                candidate_atom_ids=[atom_id],
                candidate_relation_ids=[relation_id],
                warnings=["requires_human_review"],
                metadata={"import_kind": "deterministic_fixture"},
            ),
        ]

        for model in models:
            data = model.to_dict()
            self.assertEqual(type(model).from_dict(data).to_dict(), data)
            self.assertNotIn("canonical", data)

    def test_candidate_ids_are_stable_from_provenance_payloads(self) -> None:
        atom_left = stable_candidate_atom_id(
            source_observation_ids=["obs_001"],
            atom_type="decision",
            label="Preserve source references",
            properties={"b": 2, "a": 1},
            extractor_run_id="run_001",
        )
        atom_right = stable_candidate_atom_id(
            source_observation_ids=["obs_001"],
            atom_type="decision",
            label="Preserve source references",
            properties={"a": 1, "b": 2},
            extractor_run_id="run_001",
        )
        self.assertEqual(atom_left, atom_right)
        self.assertTrue(atom_left.startswith("catom_"))

        relation_id = stable_candidate_relation_id(
            source_candidate_atom_id=atom_left,
            target_candidate_atom_id="catom_target",
            relation_type="supports",
            source_observation_ids=["obs_001"],
            properties={"confidence_basis": "same source"},
            extractor_run_id="run_001",
        )
        self.assertTrue(relation_id.startswith("crel_"))

    def test_candidate_contracts_validate_provenance_and_review_state(self) -> None:
        with self.assertRaises(ContractValidationError):
            CandidateAtom(
                candidate_atom_id="catom_001",
                source_observation_ids=[],
                atom_type="decision",
                label="Missing observation provenance",
                properties={},
                confidence=0.8,
                extractor_run_id="run_001",
                status="pending_review",
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            CandidateRelation(
                candidate_relation_id="crel_001",
                source_candidate_atom_id="catom_001",
                target_candidate_atom_id="catom_002",
                relation_type="supports",
                source_observation_ids=["obs_001"],
                properties={},
                confidence=1.4,
                extractor_run_id="run_001",
                status="pending_review",
            ).to_dict()

        with self.assertRaises(ContractValidationError):
            ExternalGraphImport(
                external_graph_import_id="egimp_001",
                source_system="fixture_graph_importer",
                source_ref={"source_system": "fixture_graph_importer"},
                extractor_run_id="run_001",
                imported_at="2026-06-17T10:00:00+00:00",
            ).to_dict()


if __name__ == "__main__":
    unittest.main()
