from __future__ import annotations

import json
import unittest

import _paths  # noqa: F401
from formowl_contract import CandidateAtom, CandidateRelation, ContractValidationError
from formowl_graph import CandidatePreviewItem, CandidatePreviewResult, preview_candidates
from formowl_graph.storage import CandidateAtomStore, CandidateRelationStore


class CandidatePreviewTests(unittest.TestCase):
    def test_atom_preview_includes_review_fields_without_mutating_store(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-preview-atoms")
        atom = _candidate_atom(
            candidate_atom_id="catom_preview_atom_001",
            confidence=0.62,
        )
        CandidateAtomStore(temp_dir).create(atom)
        before_files = _graph_state(temp_dir)

        result = preview_candidates(candidate_atom_store=CandidateAtomStore(temp_dir))

        self.assertEqual(_graph_state(temp_dir), before_files)
        data = result.to_dict()
        self.assertEqual(data["warnings"], [])
        self.assertEqual(len(data["items"]), 1)
        item = data["items"][0]
        self.assertEqual(item["item_type"], "candidate_atom")
        self.assertEqual(item["candidate_id"], atom.candidate_atom_id)
        self.assertEqual(item["candidate_type"], atom.atom_type)
        self.assertEqual(item["label"], atom.label)
        self.assertEqual(item["confidence"], 0.62)
        self.assertEqual(item["status"], "pending_review")
        self.assertTrue(item["requires_review"])
        self.assertEqual(
            item["provenance"],
            {
                "source_observation_ids": ["obs_preview_001"],
                "source_semantic_metadata_ids": ["sem_preview_001"],
                "extractor_run_id": "run_preview_001",
                "created_at": "2026-06-17T10:00:00+00:00",
            },
        )
        self.assertEqual(item["warnings"], ["requires_review", "low_confidence:0.62"])
        self.assertEqual(
            item["review_actions"],
            ["approve", "reject", "defer", "split", "merge"],
        )
        serialized = json.dumps(data, sort_keys=True)
        self.assertNotIn("canonical", serialized)
        self.assertFalse((temp_dir / "wiki").exists())

    def test_relation_preview_includes_endpoint_lineage_and_review_fields(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-preview-relations")
        source_atom = _candidate_atom(candidate_atom_id="catom_preview_relation_source")
        target_atom = _candidate_atom(candidate_atom_id="catom_preview_relation_target")
        relation = _candidate_relation(
            candidate_relation_id="crel_preview_relation_001",
            source_candidate_atom_id=source_atom.candidate_atom_id,
            target_candidate_atom_id="catom_preview_relation_missing_target",
            confidence=0.68,
        )
        missing_source_relation = _candidate_relation(
            candidate_relation_id="crel_preview_relation_missing_source",
            source_candidate_atom_id="catom_preview_relation_missing_source",
            target_candidate_atom_id=target_atom.candidate_atom_id,
            confidence=0.69,
        )
        CandidateAtomStore(temp_dir).create(source_atom)
        CandidateAtomStore(temp_dir).create(target_atom)
        CandidateRelationStore(temp_dir).create(relation)
        CandidateRelationStore(temp_dir).create(missing_source_relation)
        before_files = _graph_state(temp_dir)

        result = preview_candidates(
            candidate_atom_store=CandidateAtomStore(temp_dir),
            candidate_relation_store=CandidateRelationStore(temp_dir),
        )

        self.assertEqual(_graph_state(temp_dir), before_files)
        data = result.to_dict()
        relation_items = [
            item for item in data["items"] if item["item_type"] == "candidate_relation"
        ]
        self.assertEqual(len(relation_items), 2)
        item_by_id = {item["candidate_id"]: item for item in relation_items}
        item = item_by_id[relation.candidate_relation_id]
        self.assertEqual(item["candidate_id"], relation.candidate_relation_id)
        self.assertEqual(item["candidate_type"], "supports")
        self.assertIsNone(item["label"])
        self.assertEqual(item["confidence"], 0.68)
        self.assertEqual(
            item["provenance"],
            {
                "source_candidate_atom_id": source_atom.candidate_atom_id,
                "target_candidate_atom_id": "catom_preview_relation_missing_target",
                "source_observation_ids": ["obs_preview_001"],
                "source_semantic_metadata_ids": ["sem_preview_001"],
                "extractor_run_id": "run_preview_001",
                "created_at": "2026-06-17T10:00:00+00:00",
            },
        )
        self.assertEqual(
            item["warnings"],
            [
                "requires_review",
                "low_confidence:0.68",
                "target_candidate_atom_not_found:catom_preview_relation_missing_target",
            ],
        )
        self.assertEqual(item["review_actions"], ["approve", "reject", "defer"])
        missing_source_item = item_by_id[missing_source_relation.candidate_relation_id]
        self.assertEqual(
            missing_source_item["warnings"],
            [
                "requires_review",
                "low_confidence:0.69",
                "source_candidate_atom_not_found:catom_preview_relation_missing_source",
            ],
        )
        self.assertFalse(any("canonical" in path for path in _graph_paths(temp_dir)))

    def test_preview_filters_return_requested_candidates_and_reject_bad_ids(self) -> None:
        temp_dir = _paths.fresh_test_dir("candidate-preview-filters")
        first = _candidate_atom(candidate_atom_id="catom_preview_filter_001")
        second = _candidate_atom(candidate_atom_id="catom_preview_filter_002")
        relation = _candidate_relation(
            candidate_relation_id="crel_preview_filter_001",
            source_candidate_atom_id=first.candidate_atom_id,
            target_candidate_atom_id=second.candidate_atom_id,
        )
        CandidateAtomStore(temp_dir).create(first)
        CandidateAtomStore(temp_dir).create(second)
        CandidateRelationStore(temp_dir).create(relation)
        before_files = _graph_state(temp_dir)

        result = preview_candidates(
            candidate_atom_store=CandidateAtomStore(temp_dir),
            candidate_relation_store=CandidateRelationStore(temp_dir),
            candidate_atom_ids=["catom_preview_filter_002", "catom_preview_missing"],
        )
        self.assertEqual(_graph_state(temp_dir), before_files)

        data = result.to_dict()
        self.assertEqual(
            [item["candidate_id"] for item in data["items"]],
            ["catom_preview_filter_002"],
        )
        self.assertEqual(data["warnings"], ["candidate_atom_not_found:catom_preview_missing"])
        relation_result = preview_candidates(
            candidate_atom_store=CandidateAtomStore(temp_dir),
            candidate_relation_store=CandidateRelationStore(temp_dir),
            candidate_relation_ids=["crel_preview_filter_001", "crel_preview_missing"],
        )
        self.assertEqual(_graph_state(temp_dir), before_files)
        relation_data = relation_result.to_dict()
        self.assertEqual(
            [item["candidate_id"] for item in relation_data["items"]],
            ["crel_preview_filter_001"],
        )
        self.assertEqual(
            relation_data["warnings"],
            ["candidate_relation_not_found:crel_preview_missing"],
        )
        invalid_filters = [
            ["../catom"],
            ["formowl://asset/catom"],
            [""],
            [7],
            r"C:\raw\catom",
        ]
        for invalid_filter in invalid_filters:
            with self.subTest(invalid_filter=invalid_filter):
                with self.assertRaises(ContractValidationError) as atom_exc:
                    preview_candidates(
                        candidate_atom_store=CandidateAtomStore(temp_dir),
                        candidate_atom_ids=invalid_filter,  # type: ignore[arg-type]
                    )
                _assert_exception_omits_filter_value(self, atom_exc.exception, invalid_filter)
                with self.assertRaises(ContractValidationError) as relation_exc:
                    preview_candidates(
                        candidate_atom_store=CandidateAtomStore(temp_dir),
                        candidate_relation_store=CandidateRelationStore(temp_dir),
                        candidate_relation_ids=invalid_filter,  # type: ignore[arg-type]
                    )
                _assert_exception_omits_filter_value(
                    self,
                    relation_exc.exception,
                    invalid_filter,
                )
                self.assertEqual(_graph_state(temp_dir), before_files)

        with self.assertRaises(ContractValidationError):
            preview_candidates(
                candidate_atom_store=CandidateAtomStore(temp_dir),
                candidate_relation_ids=["crel_preview_filter_001"],
            )
        invalid_filter_shapes = [
            "catom_preview_filter_002",
            b"catom_preview_filter_002",
            42,
        ]
        for invalid_filter in invalid_filter_shapes:
            with self.subTest(invalid_filter_shape=invalid_filter):
                with self.assertRaises(ContractValidationError) as atom_exc:
                    preview_candidates(
                        candidate_atom_store=CandidateAtomStore(temp_dir),
                        candidate_atom_ids=invalid_filter,  # type: ignore[arg-type]
                    )
                _assert_exception_omits_filter_value(self, atom_exc.exception, invalid_filter)
                with self.assertRaises(ContractValidationError) as relation_exc:
                    preview_candidates(
                        candidate_atom_store=CandidateAtomStore(temp_dir),
                        candidate_relation_store=CandidateRelationStore(temp_dir),
                        candidate_relation_ids=invalid_filter,  # type: ignore[arg-type]
                    )
                _assert_exception_omits_filter_value(
                    self,
                    relation_exc.exception,
                    invalid_filter,
                )
                self.assertEqual(_graph_state(temp_dir), before_files)

        self.assertEqual(_graph_state(temp_dir), before_files)

    def test_closed_review_states_expose_reopen_action_without_pending_actions(self) -> None:
        for status in ("approved", "rejected", "deferred"):
            temp_dir = _paths.fresh_test_dir(f"candidate-preview-closed-{status}")
            source_atom = _candidate_atom(
                candidate_atom_id=f"catom_preview_closed_source_{status}",
                status=status,
                requires_review=False,
            )
            target_atom = _candidate_atom(
                candidate_atom_id=f"catom_preview_closed_target_{status}",
                status=status,
                requires_review=False,
            )
            relation = _candidate_relation(
                candidate_relation_id=f"crel_preview_closed_{status}",
                source_candidate_atom_id=source_atom.candidate_atom_id,
                target_candidate_atom_id=target_atom.candidate_atom_id,
                status=status,
                requires_review=False,
            )
            CandidateAtomStore(temp_dir).create(source_atom)
            CandidateAtomStore(temp_dir).create(target_atom)
            CandidateRelationStore(temp_dir).create(relation)
            before_files = _graph_state(temp_dir)

            data = preview_candidates(
                candidate_atom_store=CandidateAtomStore(temp_dir),
                candidate_relation_store=CandidateRelationStore(temp_dir),
            ).to_dict()
            self.assertEqual(_graph_state(temp_dir), before_files)
            self.assertFalse(any("canonical" in path for path in _graph_paths(temp_dir)))
            item_by_id = {item["candidate_id"]: item for item in data["items"]}
            self.assertEqual(
                set(item_by_id),
                {
                    source_atom.candidate_atom_id,
                    target_atom.candidate_atom_id,
                    relation.candidate_relation_id,
                },
            )
            self.assertEqual(
                {candidate_id: item["item_type"] for candidate_id, item in item_by_id.items()},
                {
                    source_atom.candidate_atom_id: "candidate_atom",
                    target_atom.candidate_atom_id: "candidate_atom",
                    relation.candidate_relation_id: "candidate_relation",
                },
            )

            for item in item_by_id.values():
                with self.subTest(status=status, candidate_id=item["candidate_id"]):
                    self.assertEqual(item["review_actions"], ["reopen_review"])
                    self.assertEqual(item["warnings"], [f"status_not_pending_review:{status}"])
                    self.assertNotIn("approve", item["review_actions"])
                    self.assertNotIn("reject", item["review_actions"])
                    self.assertNotIn("defer", item["review_actions"])
                    self.assertNotIn("split", item["review_actions"])
                    self.assertNotIn("merge", item["review_actions"])

    def test_preview_rejects_raw_paths_and_internal_locators_in_display_payload(self) -> None:
        raw_atom_cases = [
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_raw_label",
                    label=r"C:\raw\secret.txt",
                ),
                r"C:\raw\secret.txt",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_raw_property",
                    properties={"source_line": "Decision: smb://nas/share/secret.txt"},
                ),
                "smb://nas/share/secret.txt",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_raw_nested_property",
                    properties={"nested": {"scratch_path": "/tmp/formowl/secret.txt"}},
                ),
                "/tmp/formowl/secret.txt",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_raw_property_key",
                    properties={"formowl://asset/secret": "hidden"},
                ),
                "formowl://asset/secret",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_relative_label",
                    label="docs/customer-secret.pdf",
                ),
                "docs/customer-secret.pdf",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_extensionless_relative_label",
                    label="docs/secrets",
                ),
                "docs/secrets",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_relative_property",
                    properties={"note": r"scratch\secret.txt"},
                ),
                r"scratch\secret.txt",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_dot_relative_label",
                    label=r".\customer-secret.pdf",
                ),
                r".\customer-secret.pdf",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_parent_relative_property",
                    properties={"note": r"..\customer-secret.pdf"},
                ),
                r"..\customer-secret.pdf",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_posix_dot_relative_label",
                    label="./customer-secret.pdf",
                ),
                "./customer-secret.pdf",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_posix_parent_relative_property",
                    properties={"note": "../customer-secret.pdf"},
                ),
                "../customer-secret.pdf",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_posix_dot_extensionless_label",
                    label="./secrets",
                ),
                "./secrets",
            ),
            (
                _candidate_atom(
                    candidate_atom_id="catom_preview_posix_parent_extensionless_property",
                    properties={"note": "../secrets"},
                ),
                "../secrets",
            ),
        ]

        for index, (atom, raw_value) in enumerate(raw_atom_cases, start=1):
            temp_dir = _paths.fresh_test_dir(f"candidate-preview-raw-atom-{index}")
            CandidateAtomStore(temp_dir).create(atom)
            before_files = _graph_state(temp_dir)
            with self.subTest(candidate_atom_id=atom.candidate_atom_id):
                with self.assertRaises(ContractValidationError) as exc:
                    preview_candidates(candidate_atom_store=CandidateAtomStore(temp_dir))
                self.assertNotIn(raw_value, str(exc.exception))
                self.assertEqual(_graph_state(temp_dir), before_files)

        temp_dir = _paths.fresh_test_dir("candidate-preview-raw-relation")
        source_atom = _candidate_atom(candidate_atom_id="catom_preview_raw_relation_source")
        relation = _candidate_relation(
            candidate_relation_id="crel_preview_raw_relation",
            source_candidate_atom_id=source_atom.candidate_atom_id,
            target_candidate_atom_id="catom_preview_raw_relation_target",
            properties={"locator": "formowl://asset/secret"},
        )
        CandidateAtomStore(temp_dir).create(source_atom)
        CandidateRelationStore(temp_dir).create(relation)
        before_files = _graph_state(temp_dir)

        with self.assertRaises(ContractValidationError) as exc:
            preview_candidates(
                candidate_atom_store=CandidateAtomStore(temp_dir),
                candidate_relation_store=CandidateRelationStore(temp_dir),
            )
        self.assertNotIn("formowl://asset/secret", str(exc.exception))
        self.assertEqual(_graph_state(temp_dir), before_files)

        relation_raw_cases = [
            (
                "candidate-preview-raw-relation-key",
                _candidate_relation(
                    candidate_relation_id="crel_preview_raw_relation_key",
                    source_candidate_atom_id=source_atom.candidate_atom_id,
                    target_candidate_atom_id="catom_preview_raw_relation_target",
                    properties={"smb://nas/share/secret.txt": "hidden"},
                ),
                "smb://nas/share/secret.txt",
            ),
            (
                "candidate-preview-raw-relation-relative-property",
                _candidate_relation(
                    candidate_relation_id="crel_preview_raw_relation_relative",
                    source_candidate_atom_id=source_atom.candidate_atom_id,
                    target_candidate_atom_id="catom_preview_raw_relation_target",
                    properties={"note": "docs/customer-secret.pdf"},
                ),
                "docs/customer-secret.pdf",
            ),
            (
                "candidate-preview-raw-relation-extensionless-relative-property",
                _candidate_relation(
                    candidate_relation_id="crel_preview_raw_relation_extensionless_relative",
                    source_candidate_atom_id=source_atom.candidate_atom_id,
                    target_candidate_atom_id="catom_preview_raw_relation_target",
                    properties={"note": "docs/secrets"},
                ),
                "docs/secrets",
            ),
            (
                "candidate-preview-raw-relation-windows-extensionless-relative-property",
                _candidate_relation(
                    candidate_relation_id="crel_preview_raw_relation_windows_extensionless",
                    source_candidate_atom_id=source_atom.candidate_atom_id,
                    target_candidate_atom_id="catom_preview_raw_relation_target",
                    properties={"note": r"scratch\secret"},
                ),
                r"scratch\secret",
            ),
            (
                "candidate-preview-raw-relation-posix-dot-relative-property",
                _candidate_relation(
                    candidate_relation_id="crel_preview_raw_relation_posix_dot_relative",
                    source_candidate_atom_id=source_atom.candidate_atom_id,
                    target_candidate_atom_id="catom_preview_raw_relation_target",
                    properties={"note": "./customer-secret.pdf"},
                ),
                "./customer-secret.pdf",
            ),
            (
                "candidate-preview-raw-relation-posix-parent-extensionless-property",
                _candidate_relation(
                    candidate_relation_id="crel_preview_raw_relation_posix_parent_extensionless",
                    source_candidate_atom_id=source_atom.candidate_atom_id,
                    target_candidate_atom_id="catom_preview_raw_relation_target",
                    properties={"note": "../secrets"},
                ),
                "../secrets",
            ),
        ]
        for name, raw_relation, raw_value in relation_raw_cases:
            relation_temp_dir = _paths.fresh_test_dir(name)
            CandidateAtomStore(relation_temp_dir).create(source_atom)
            CandidateRelationStore(relation_temp_dir).create(raw_relation)
            before_relation_files = _graph_state(relation_temp_dir)
            with self.subTest(candidate_relation_id=raw_relation.candidate_relation_id):
                with self.assertRaises(ContractValidationError) as relation_exc:
                    preview_candidates(
                        candidate_atom_store=CandidateAtomStore(relation_temp_dir),
                        candidate_relation_store=CandidateRelationStore(relation_temp_dir),
                    )
                self.assertNotIn(raw_value, str(relation_exc.exception))
                self.assertEqual(_graph_state(relation_temp_dir), before_relation_files)

    def test_preview_payload_rejects_raw_paths_in_warning_text(self) -> None:
        warning_cases = [
            (
                CandidatePreviewResult(warnings=["unsafe:formowl://asset/secret"]),
                "formowl://asset/secret",
            ),
            (
                CandidatePreviewResult(warnings=["unsafe:docs/secrets"]),
                "docs/secrets",
            ),
            (
                CandidatePreviewItem(
                    item_type="candidate_atom",
                    candidate_id="catom_preview_warning_redaction",
                    candidate_type="decision",
                    label="Reviewable warning redaction",
                    status="pending_review",
                    requires_review=True,
                    confidence=0.82,
                    provenance={
                        "source_observation_ids": ["obs_preview_001"],
                        "source_semantic_metadata_ids": [],
                        "extractor_run_id": "run_preview_001",
                        "created_at": "2026-06-17T10:00:00+00:00",
                    },
                    warnings=[r"unsafe:C:\raw\secret.txt"],
                    review_actions=["approve"],
                    properties={},
                ),
                r"C:\raw\secret.txt",
            ),
            (
                CandidatePreviewItem(
                    item_type="candidate_relation",
                    candidate_id="crel_preview_warning_redaction",
                    candidate_type="supports",
                    label=None,
                    status="pending_review",
                    requires_review=True,
                    confidence=0.82,
                    provenance={
                        "source_candidate_atom_id": "catom_preview_warning_source",
                        "target_candidate_atom_id": "catom_preview_warning_target",
                        "source_observation_ids": ["obs_preview_001"],
                        "source_semantic_metadata_ids": [],
                        "extractor_run_id": "run_preview_001",
                        "created_at": "2026-06-17T10:00:00+00:00",
                    },
                    warnings=["unsafe:../secrets"],
                    review_actions=["approve"],
                    properties={},
                ),
                "../secrets",
            ),
        ]

        for payload, raw_value in warning_cases:
            with self.subTest(raw_value=raw_value):
                with self.assertRaises(ContractValidationError) as exc:
                    payload.to_dict()
                self.assertNotIn(raw_value, str(exc.exception))


def _candidate_atom(
    *,
    candidate_atom_id: str,
    label: str = "Keep candidate previews reviewable",
    confidence: float = 0.82,
    status: str = "pending_review",
    requires_review: bool = True,
    properties: dict[str, object] | None = None,
) -> CandidateAtom:
    return CandidateAtom(
        candidate_atom_id=candidate_atom_id,
        source_observation_ids=["obs_preview_001"],
        source_semantic_metadata_ids=["sem_preview_001"],
        atom_type="decision",
        label=label,
        properties=properties or {"basis": "candidate proposal"},
        confidence=confidence,
        extractor_run_id="run_preview_001",
        status=status,  # type: ignore[arg-type]
        requires_review=requires_review,
        created_at="2026-06-17T10:00:00+00:00",
    )


def _candidate_relation(
    *,
    candidate_relation_id: str,
    source_candidate_atom_id: str,
    target_candidate_atom_id: str,
    confidence: float = 0.81,
    status: str = "pending_review",
    requires_review: bool = True,
    properties: dict[str, object] | None = None,
) -> CandidateRelation:
    return CandidateRelation(
        candidate_relation_id=candidate_relation_id,
        source_candidate_atom_id=source_candidate_atom_id,
        target_candidate_atom_id=target_candidate_atom_id,
        relation_type="supports",
        source_observation_ids=["obs_preview_001"],
        source_semantic_metadata_ids=["sem_preview_001"],
        properties=properties or {"basis": "same source observation"},
        confidence=confidence,
        extractor_run_id="run_preview_001",
        status=status,  # type: ignore[arg-type]
        requires_review=requires_review,
        created_at="2026-06-17T10:00:00+00:00",
    )


def _graph_state(temp_dir) -> dict[str, str]:
    graph_root = temp_dir / "graph"
    if not graph_root.exists():
        return {}
    state: dict[str, str] = {}
    for path in sorted(graph_root.rglob("*")):
        relative_path = path.relative_to(graph_root).as_posix()
        if path.is_dir():
            state[f"{relative_path}/"] = "<dir>"
        else:
            state[relative_path] = path.read_text(encoding="utf-8")
    return state


def _graph_paths(temp_dir) -> list[str]:
    graph_root = temp_dir / "graph"
    if not graph_root.exists():
        return []
    return [path.relative_to(graph_root).as_posix() for path in graph_root.rglob("*")]


def _assert_exception_omits_filter_value(
    test_case: unittest.TestCase,
    exc: ContractValidationError,
    invalid_filter: object,
) -> None:
    if isinstance(invalid_filter, list):
        raw_values = [value for value in invalid_filter if isinstance(value, str) and value]
    elif isinstance(invalid_filter, str):
        raw_values = [invalid_filter]
    elif isinstance(invalid_filter, bytes):
        raw_values = [invalid_filter.decode("utf-8")]
    else:
        raw_values = []
    for raw_value in raw_values:
        test_case.assertNotIn(raw_value, str(exc))


if __name__ == "__main__":
    unittest.main()
