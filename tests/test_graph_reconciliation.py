from __future__ import annotations

import io
import json
from copy import deepcopy
import unittest
from unittest import mock

import _paths
from formowl_contract import CandidateAtom, ContractValidationError, Observation, sha256_json
from formowl_graph.candidates import read_and_store_source_unit
from formowl_graph.local_semantic_reader import LocalOllamaReader
from formowl_graph.reconciliation import GroupMember, build_groups, reconcile_group
from formowl_graph.storage import CandidateAtomStore, CandidateRelationStore, SemanticMetadataStore

OLD = "PO 4500123 交期 1/20"
NEW = "通知：PO 4500123 交期改為 1/27"


def _observation(observation_id: str, text: str) -> Observation:
    return Observation(
        observation_id=observation_id, asset_id="asset_recon_001", extractor_run_id="run_recon_source",
        observation_type="email_body_segment", modality="mail", text=text, location={"body_segment_index": 0},
        confidence=1.0, created_at="2026-10-25T00:00:00+00:00",
        permission_scope={"scope_type": "workspace", "visibility": "restricted", "scope_id": "ws_recon"})


def _annotate(temp_dir, observation: Observation, value: str, quote: str):
    record = {"record_type": "claim", "topic": "交期", "subject": "4500123", "subject_label": None,
              "subject_quote": {"observation_id": observation.observation_id, "quote": "PO 4500123"},
              "item_or_row": None, "property": "交期", "value": value, "unit": None, "event_type": None,
              "state": None, "actor": None, "times": [],
              "evidence": [{"observation_id": observation.observation_id, "quote": quote}], "confidence": 0.9}
    body = json.dumps({"model": "m", "done_reason": "stop", "message": {"content": json.dumps(
        {"read_status": "complete", "records": [record], "relations": []}, ensure_ascii=False)}})
    reader = LocalOllamaReader("http://127.0.0.1:1", "m")
    with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body.encode())):
        result = read_and_store_source_unit(
            source_unit_id="su_" + observation.observation_id, observations=[observation],
            expected_observation_hashes={observation.observation_id: sha256_json(observation.to_dict())},
            source_revision_fingerprint=sha256_json({"revision": 1}),
            permission_scope_fingerprint=sha256_json(observation.to_dict()["permission_scope"]),
            source_complete=True, extractor_run_id="semrun_recon_read", ontology_revision_id="ontology_recon",
            model_name="m", reasoning_effort="none", reader=reader.extract_structured_json,
            configuration=reader.configuration, semantic_metadata_store=SemanticMetadataStore(temp_dir),
            candidate_atom_store=CandidateAtomStore(temp_dir), candidate_relation_store=CandidateRelationStore(temp_dir))
    return result.candidate_atoms[0]


class ReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = _paths.fresh_test_dir("graph-reconciliation")
        old, new = _observation("obs_old", OLD), _observation("obs_new", NEW)
        self.old = GroupMember(_annotate(self.temp_dir, old, "1/20", "交期 1/20"), "mailocc_old",
                               "2026-01-05T09:00:00+08:00", {"subject": "PO"}, {"obs_old": old.to_dict()})
        self.new = GroupMember(_annotate(self.temp_dir, new, "1/27", "交期改為 1/27"), "mailocc_new",
                               "2026-01-15T09:00:00+08:00", {"subject": "通知"}, {"obs_new": new.to_dict()})

    def _run(self, relations, run_id="recon_run_001"):
        return self._run_members([self.old, self.new], relations, run_id)

    def _run_members(self, members, relations, run_id):
        reader = mock.Mock()
        reader.complete_json.return_value = ({"relations": relations},
                                             {"requested_model": "m", "observed_model": "m",
                                              "request_fingerprint": sha256_json({"r": run_id})})
        return reconcile_group(members, reader=reader, extractor_run_id=run_id, model_name="m",
                               semantic_metadata_store=SemanticMetadataStore(self.temp_dir),
                               candidate_relation_store=CandidateRelationStore(self.temp_dir))

    def _with_value(self, member: GroupMember, value: str) -> GroupMember:
        atom = member.atom.to_dict()
        atom["properties"] = deepcopy(atom["properties"])
        atom["properties"]["assertion"]["value"] = value
        return GroupMember(
            CandidateAtom.from_dict(atom), member.message_key, member.message_time,
            member.context, member.observations,
        )

    def _with_item_scope(self, member: GroupMember, item_or_row: str) -> GroupMember:
        atom = member.atom.to_dict()
        atom["properties"] = deepcopy(atom["properties"])
        atom["properties"]["assertion"]["item_or_row"] = item_or_row
        return GroupMember(
            CandidateAtom.from_dict(atom), member.message_key, member.message_time,
            member.context, member.observations,
        )

    def test_groups_need_the_same_target_and_property_across_messages(self) -> None:
        same_message = GroupMember(self.old.atom, "mailocc_new", None)
        self.assertEqual(len(build_groups([self.old, self.new])), 1)
        self.assertEqual(build_groups([self.old]), [])
        self.assertEqual(build_groups([same_message, self.new]), [])

    def test_groups_keep_different_item_rows_separate(self) -> None:
        scoped = self._with_item_scope(self.new, "row-2")
        groups = build_groups([self.old, self.new, scoped])
        self.assertEqual(len(groups), 1)
        self.assertEqual({member.atom.candidate_atom_id for member in groups[0]},
                         {self.old.atom.candidate_atom_id, self.new.atom.candidate_atom_id})

    def test_groups_keep_different_parent_group_item_bindings_separate(self) -> None:
        for role in ("parent", "group", "item"):
            with self.subTest(role=role):
                atom = self.new.atom.to_dict()
                atom["properties"] = deepcopy(atom["properties"])
                atom["properties"]["identity_bindings"].append({
                    "scope_role": role, "type_surface": "order", "value_surface": "scope-2",
                    "evidence_spans": [],
                })
                scoped = GroupMember(CandidateAtom.from_dict(atom), self.new.message_key,
                                     self.new.message_time, self.new.context, self.new.observations)
                self.assertEqual(build_groups([self.old, scoped]), [])

    def test_relation_crossing_item_scope_fails_the_group(self) -> None:
        scoped = self._with_item_scope(self.new, "row-2")
        reader = mock.Mock()
        reader.complete_json.return_value = (
            {"relations": [{"source": 1, "target": 0, "relation_type": "updates",
                             "confidence": 0.8,
                             "evidence": [{"observation_id": "obs_new", "quote": "交期改為 1/27"}]}]},
            {"requested_model": "m", "observed_model": "m", "request_fingerprint": sha256_json({"r": 1})},
        )
        with self.assertRaisesRegex(ContractValidationError, "reconciliation relation crosses scope"):
            reconcile_group([self.old, scoped], reader=reader, extractor_run_id="recon_scope_bad",
                            model_name="m", semantic_metadata_store=SemanticMetadataStore(self.temp_dir),
                            candidate_relation_store=CandidateRelationStore(self.temp_dir))

    def test_update_quoted_from_the_later_source_becomes_a_pending_relation(self) -> None:
        result = self._run([{"source": 1, "target": 0, "relation_type": "updates", "confidence": 0.8,
                             "evidence": [{"observation_id": "obs_new", "quote": "交期改為 1/27"}]}])
        relation = result.relations[0]
        self.assertEqual((relation.relation_type, relation.status), ("updates", "pending_review"))
        self.assertEqual(relation.source_candidate_atom_id, self.new.atom.candidate_atom_id)
        self.assertEqual(relation.properties["evidence_spans"][0]["quote"], "交期改為 1/27")
        self.assertEqual(result.ledger.value["reconciliation_status"], "reconciled")
        self.assertEqual(CandidateRelationStore(self.temp_dir).get(relation.candidate_relation_id), relation)

    def test_updates_and_supersedes_require_distinct_values_and_value_bearing_evidence(self) -> None:
        relation_template = {"source": 1, "target": 0, "relation_type": "updates", "confidence": 0.8,
                             "evidence": [{"observation_id": "obs_new", "quote": "交期改為 1/27"}]}
        cases = [
            ("same_value", self.old, self._with_value(self.new, "１/２０"), "交期改為 1/27",
             "values must differ"),
            ("empty_source", self.old, self._with_value(self.new, "  \t"), "交期改為 1/27",
             "values must be non-empty"),
            ("empty_target", self._with_value(self.old, "  "), self.new, "交期改為 1/27",
             "values must be non-empty"),
            ("evidence_omits_new_value", self.old, self.new, "交期改為", "contain the source value"),
        ]
        for index, (case, older, newer, quote, error) in enumerate(cases):
            for kind in ("updates", "supersedes"):
                with self.subTest(case=case, kind=kind):
                    relation = {**relation_template, "relation_type": kind,
                                "evidence": [{"observation_id": "obs_new", "quote": quote}]}
                    with self.assertRaisesRegex(ContractValidationError, error):
                        self._run_members([older, newer], [relation], f"recon_value_bad_{index}_{kind}")

    def test_update_value_and_evidence_comparison_uses_nfkc_casefold(self) -> None:
        newer = self._with_value(self.new, "１/２７")
        result = self._run_members(
            [self.old, newer],
            [{"source": 1, "target": 0, "relation_type": "updates", "confidence": 0.8,
              "evidence": [{"observation_id": "obs_new", "quote": "交期改為 1/27"}]}],
            "recon_nfkc_value_match",
        )
        self.assertEqual(len(result.relations), 1)

    def test_update_without_later_source_wording_or_against_time_fails_the_group(self) -> None:
        cases = [([{"source": 1, "target": 0, "relation_type": "updates", "confidence": 0.8,
                    "evidence": [{"observation_id": "obs_old", "quote": "交期 1/20"}]}], "later source"),
                 ([{"source": 0, "target": 1, "relation_type": "supersedes", "confidence": 0.8,
                    "evidence": [{"observation_id": "obs_old", "quote": "交期 1/20"}]}], "message time"),
                 ([{"source": 1, "target": 0, "relation_type": "updates", "confidence": 0.8, "evidence": []}],
                  "later source")]
        for index, (relations, message) in enumerate(cases):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ContractValidationError, message):
                    self._run(relations, run_id=f"recon_bad_{index}")
        failed = [m for m in SemanticMetadataStore(self.temp_dir).list() if m.metadata_type == "cross_unit_reconciliation"]
        self.assertTrue(all(m.value["reconciliation_status"] == "failed" for m in failed))
        self.assertEqual(CandidateRelationStore(self.temp_dir).list(), [])

    def test_no_relation_is_a_recorded_result_and_a_rerun_reuses_it(self) -> None:
        first = self._run([])
        self.assertEqual((first.ledger.value["reconciliation_status"], first.relations), ("reconciled", []))
        self.assertEqual(self._run([]).ledger.semantic_metadata_id, first.ledger.semantic_metadata_id)


if __name__ == "__main__":
    unittest.main()
