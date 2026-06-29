from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import (
    CandidateAtom,
    CandidateRelation,
    ContractValidationError,
    Observation,
    to_plain,
)
from formowl_graph import DeterministicTextCandidateExtractor, extract_and_store_candidates
from formowl_graph.storage import CandidateAtomStore, CandidateRelationStore


class CandidateExtractionTests(unittest.TestCase):
    def test_marked_text_creates_stable_reviewable_candidate_atoms(self) -> None:
        observation = _text_observation(
            observation_id="obs_candidates_001",
            text=(
                "Decision: Keep graph candidates reviewable\n"
                "Action Item: Review candidate proposals\n"
                "Risk: Canonical graph state leak"
            ),
        )
        extractor = DeterministicTextCandidateExtractor()

        first = extractor.extract(
            [observation],
            extractor_run_id="run_candidate_001",
            created_at="2026-06-17T10:00:00+00:00",
        )
        second = extractor.extract(
            [observation],
            extractor_run_id="run_candidate_001",
            created_at="2026-06-18T10:00:00+00:00",
        )

        self.assertEqual(
            [atom.candidate_atom_id for atom in first.candidate_atoms],
            [atom.candidate_atom_id for atom in second.candidate_atoms],
        )
        self.assertEqual(
            [(atom.atom_type, atom.label) for atom in first.candidate_atoms],
            [
                ("decision", "Keep graph candidates reviewable"),
                ("action_item", "Review candidate proposals"),
                ("risk", "Canonical graph state leak"),
            ],
        )
        for atom in first.candidate_atoms:
            with self.subTest(candidate_atom_id=atom.candidate_atom_id):
                data = atom.to_dict()
                self.assertEqual(atom.status, "pending_review")
                self.assertTrue(atom.requires_review)
                self.assertEqual(atom.confidence, 1.0)
                self.assertEqual(atom.source_observation_ids, [observation.observation_id])
                self.assertEqual(atom.extractor_run_id, "run_candidate_001")
                self.assertNotIn("canonical_atom_id", data)
                self.assertNotIn("canonical_relation_id", data)
                self.assertNotIn("canonical_entity_id", data)
        self.assertEqual(first.candidate_relations, [])
        self.assertEqual(first.warnings, [])

    def test_store_helper_persists_candidates_without_canonical_state(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-store")
        observation = _text_observation(
            observation_id="obs_candidates_store_001",
            text="Decision: Store only candidate proposals",
        )

        result = extract_and_store_candidates(
            observations=[observation],
            candidate_atom_store=CandidateAtomStore(temp_dir),
            extractor_run_id="run_candidate_store_001",
            created_at="2026-06-17T10:00:00+00:00",
        )

        persisted_atoms = CandidateAtomStore(temp_dir).list()
        self.assertEqual(
            [atom.to_dict() for atom in persisted_atoms],
            [atom.to_dict() for atom in result.candidate_atoms],
        )
        graph_root = temp_dir / "graph"
        graph_entries = {entry.name for entry in graph_root.iterdir()}
        self.assertEqual(graph_entries, {"candidate-atoms"})
        graph_paths = [path.relative_to(graph_root).as_posix() for path in graph_root.rglob("*")]
        self.assertFalse(any("canonical" in path for path in graph_paths))
        self.assertFalse((graph_root / "semantic-metadata").exists())
        self.assertFalse((temp_dir / "wiki").exists())

    def test_candidate_payload_omits_raw_observation_paths_and_locators(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-redaction")
        observation = _text_observation(
            observation_id="obs_candidates_redaction_001",
            text="Decision: Keep raw storage internals out of candidates",
            location={
                "line_start": 1,
                "line_end": 1,
                "raw_path": r"C:\raw\secret.txt",
                "object_uri": "formowl://asset/internal",
            },
            payload={
                "object_uri": "smb://nas/share/secret.txt",
                "scratch_path": "/tmp/formowl/secret.txt",
            },
        )

        result = extract_and_store_candidates(
            observations=[observation],
            candidate_atom_store=CandidateAtomStore(temp_dir),
            extractor_run_id="run_candidate_redaction_001",
            created_at="2026-06-17T10:00:00+00:00",
        )

        self.assertEqual(len(result.candidate_atoms), 1)
        persisted = CandidateAtomStore(temp_dir).get(result.candidate_atoms[0].candidate_atom_id)
        self.assertIsNotNone(persisted)
        serialized = json.dumps(persisted.to_dict(), sort_keys=True)
        self.assertNotIn(r"C:\raw", serialized)
        self.assertNotIn("smb://", serialized)
        self.assertNotIn("/tmp/formowl", serialized)
        self.assertNotIn("object_uri", serialized)
        self.assertEqual(persisted.source_observation_ids, [observation.observation_id])

    def test_empty_and_unsupported_observations_do_not_persist_candidates(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-empty")
        observations = [
            _text_observation(observation_id="obs_candidates_empty_001", text="   "),
            _text_observation(
                observation_id="obs_candidates_image_001",
                text="Decision: Ignore non-text modality",
                modality="image",
            ),
        ]

        result = extract_and_store_candidates(
            observations=observations,
            candidate_atom_store=CandidateAtomStore(temp_dir),
            extractor_run_id="run_candidate_empty_001",
        )

        self.assertEqual(result.candidate_atoms, [])
        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])
        self.assertIn("empty_text_observation:obs_candidates_empty_001", result.warnings)
        self.assertIn(
            "unsupported_observation_modality:obs_candidates_image_001",
            result.warnings,
        )
        self.assertIn("no_candidate_atoms", result.warnings)

    def test_unmarked_text_observations_do_not_persist_candidates(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-unmarked")
        observation = _text_observation(
            observation_id="obs_candidates_unmarked_001",
            text="This is plain text without fixture candidate markers.",
        )

        result = extract_and_store_candidates(
            observations=[observation],
            candidate_atom_store=CandidateAtomStore(temp_dir),
            extractor_run_id="run_candidate_unmarked_001",
        )

        self.assertEqual(result.candidate_atoms, [])
        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])
        self.assertIn("no_candidate_markers:obs_candidates_unmarked_001", result.warnings)
        self.assertIn("no_candidate_atoms", result.warnings)

    def test_malformed_observation_lineage_fails_before_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-bad-lineage")
        observations = [
            _text_observation(
                observation_id="obs_candidates_valid_001",
                text="Decision: This must not be partially persisted",
            ),
            _text_observation(
                observation_id="../obs_escape",
                text="Decision: Invalid source observation id",
            ),
        ]

        with self.assertRaises(ContractValidationError):
            extract_and_store_candidates(
                observations=observations,
                candidate_atom_store=CandidateAtomStore(temp_dir),
                extractor_run_id="run_candidate_bad_lineage_001",
            )

        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_malformed_source_extractor_lineage_fails_before_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-bad-source-run")
        observations = [
            _text_observation(
                observation_id="obs_candidates_valid_source_run_001",
                text="Decision: This must not be partially persisted",
            ),
            _text_observation(
                observation_id="obs_candidates_bad_source_run_001",
                extractor_run_id="formowl://asset/source-run",
                text="Decision: Invalid source extractor run id",
            ),
        ]

        with self.assertRaises(ContractValidationError):
            extract_and_store_candidates(
                observations=observations,
                candidate_atom_store=CandidateAtomStore(temp_dir),
                extractor_run_id="run_candidate_bad_source_run_001",
            )

        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_malformed_candidate_extractor_run_id_fails_before_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-bad-run")
        observation = _text_observation(
            observation_id="obs_candidates_bad_run_001",
            text="Decision: Invalid candidate run id",
        )

        with self.assertRaises(ContractValidationError):
            extract_and_store_candidates(
                observations=[observation],
                candidate_atom_store=CandidateAtomStore(temp_dir),
                extractor_run_id="formowl://asset/run",
            )

        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_malformed_created_at_fails_before_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-bad-created-at")
        observation = _text_observation(
            observation_id="obs_candidates_bad_created_at_001",
            text="Decision: Invalid candidate timestamp",
        )

        invalid_values = ["", 0, False, "not-a-timestamp"]
        for invalid_created_at in invalid_values:
            with self.subTest(invalid_created_at=invalid_created_at):
                with self.assertRaises(ContractValidationError):
                    extract_and_store_candidates(
                        observations=[observation],
                        candidate_atom_store=CandidateAtomStore(temp_dir),
                        extractor_run_id="run_candidate_bad_created_at_001",
                        created_at=invalid_created_at,  # type: ignore[arg-type]
                    )

        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_candidate_store_rejects_malformed_created_at_without_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-store-created-at")
        invalid_atom = CandidateAtom(
            candidate_atom_id="catom_bad_created_at_001",
            source_observation_ids=["obs_candidates_created_at_001"],
            atom_type="decision",
            label="Malformed candidate timestamp",
            properties={"marker": "decision"},
            confidence=1.0,
            extractor_run_id="run_candidate_created_at_001",
            status="pending_review",
            created_at="not-a-timestamp",
        )
        invalid_relation = CandidateRelation(
            candidate_relation_id="crel_bad_created_at_001",
            source_candidate_atom_id="catom_created_at_001",
            target_candidate_atom_id="catom_created_at_002",
            relation_type="supports",
            source_observation_ids=["obs_candidates_created_at_001"],
            properties={"marker": "decision"},
            confidence=1.0,
            extractor_run_id="run_candidate_created_at_001",
            status="pending_review",
            created_at="not-a-timestamp",
        )

        with self.assertRaises(ContractValidationError):
            CandidateAtomStore(temp_dir).create(invalid_atom)
        with self.assertRaises(ContractValidationError):
            CandidateRelationStore(temp_dir).create(invalid_relation)
        with self.assertRaises(ContractValidationError):
            CandidateAtomStore(temp_dir).create(to_plain(invalid_atom))
        with self.assertRaises(ContractValidationError):
            CandidateRelationStore(temp_dir).create(to_plain(invalid_relation))

        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(CandidateRelationStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_raw_path_marker_labels_fail_before_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-raw-marker")
        raw_label_cases = [
            r"Decision: C:\raw\secret.txt",
            "Decision: smb://nas/share/secret.txt",
            "Decision: /tmp/formowl/secret.txt",
            "Decision: see (/tmp/formowl/secret.txt)",
            "Decision: see '/workspace/formowl/secret.txt'",
            "Decision: /etc/passwd",
            "Decision: see (/root/secret.txt)",
        ]

        for index, text in enumerate(raw_label_cases, start=1):
            with self.subTest(text=text):
                with self.assertRaises(ContractValidationError):
                    extract_and_store_candidates(
                        observations=[
                            _text_observation(
                                observation_id=f"obs_candidates_raw_marker_{index}",
                                text=text,
                            )
                        ],
                        candidate_atom_store=CandidateAtomStore(temp_dir),
                        extractor_run_id=f"run_candidate_raw_marker_{index}",
                    )

        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_later_raw_marker_failure_does_not_persist_earlier_candidates(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-raw-marker-partial")
        observation = _text_observation(
            observation_id="obs_candidates_raw_marker_partial_001",
            text="Decision: Valid candidate proposal\nRisk: /tmp/formowl/secret.txt",
        )

        with self.assertRaises(ContractValidationError):
            extract_and_store_candidates(
                observations=[observation],
                candidate_atom_store=CandidateAtomStore(temp_dir),
                extractor_run_id="run_candidate_raw_marker_partial_001",
            )

        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_malformed_source_observation_created_at_fails_before_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-bad-source-created-at")
        observations = [
            _text_observation(
                observation_id="obs_candidates_valid_source_created_at_001",
                text="Decision: This must not be partially persisted",
            ),
            _text_observation(
                observation_id="obs_candidates_bad_source_created_at_001",
                text="Decision: Invalid source timestamp",
                created_at="not-a-timestamp",
            ),
        ]

        with self.assertRaises(ContractValidationError):
            extract_and_store_candidates(
                observations=observations,
                candidate_atom_store=CandidateAtomStore(temp_dir),
                extractor_run_id="run_candidate_bad_source_created_at_001",
            )

        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])

    def test_empty_marker_labels_are_skipped_without_candidate_writes(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-extraction-empty-labels")
        observation = _text_observation(
            observation_id="obs_candidates_empty_label_001",
            text="Decision:\nAction Item:",
        )

        result = extract_and_store_candidates(
            observations=[observation],
            candidate_atom_store=CandidateAtomStore(temp_dir),
            extractor_run_id="run_candidate_empty_label_001",
        )

        self.assertEqual(result.candidate_atoms, [])
        self.assertEqual(CandidateAtomStore(temp_dir).list(), [])
        self.assertEqual(list((temp_dir / "graph").rglob("*.json")), [])
        self.assertIn("empty_candidate_label:obs_candidates_empty_label_001:1", result.warnings)
        self.assertIn("empty_candidate_label:obs_candidates_empty_label_001:2", result.warnings)
        self.assertIn("no_candidate_atoms", result.warnings)


def _text_observation(
    *,
    observation_id: str,
    text: str,
    modality: str = "text",
    extractor_run_id: str = "run_observation_source_001",
    location: dict[str, object] | None = None,
    payload: dict[str, object] | None = None,
    created_at: str = "2026-06-17T10:00:00+00:00",
) -> Observation:
    return Observation(
        observation_id=observation_id,
        asset_id="asset_candidates_001",
        extractor_run_id=extractor_run_id,
        observation_type="paragraph",
        modality=modality,
        text=text,
        location=location or {"line_start": 1, "line_end": max(1, len(text.splitlines()))},
        confidence=1.0,
        permission_scope={
            "scope_type": "workspace",
            "visibility": "restricted",
            "scope_id": "ws_candidates_001",
        },
        created_at=created_at,
        payload=payload,
    )


if __name__ == "__main__":
    unittest.main()
