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
from formowl_graph import ontology, reconciliation

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


class CandidateFactRowTests(unittest.TestCase):
    def members(self, unit="unit-clienta", *, row="row-1", partial=False, header_properties=()):
        root = _paths.fresh_test_dir("candidate-fact-row")
        observation = _observation("obs_" + unit, "Clienta ZX-742 ticket R-007 expected 2030-06-01")
        header = Observation.from_dict({**observation.to_dict(), "observation_id": "obs_date_" + unit,
            "observation_type": "email_header", "text": "Wed, 01 Jan 2031 00:00:00 +0000",
            "payload": {"header_name": "Date", "header_value": "Wed, 01 Jan 2031 00:00:00 +0000"}})
        records = [{"record_type": "claim", "topic": "Clienta", "subject": "ZX-742", "subject_label": None,
                    "subject_quote": {"observation_id": observation.observation_id, "quote": "ZX-742"},
                    "item_or_row": None if prop in header_properties else row,
                    "property": prop, "value": value, "unit": None, "event_type": None,
                    "state": None, "actor": None, "times": [], "confidence": 0.9,
                    "evidence": [{"observation_id": observation.observation_id, "quote": observation.text}]}
                   for prop, value in (("Asset Code", "ZX-742"), ("Ticket", "R-007"), ("Expected Date", "2030-06-01"))]
        body = json.dumps({"model": "m", "done_reason": "stop", "message": {"content": json.dumps(
            {"read_status": "complete", "records": records, "relations": []})}})
        reader = LocalOllamaReader("http://127.0.0.1:1", "m")
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body.encode())):
            result = read_and_store_source_unit(
                source_unit_id="su_" + sha256_json(unit)[7:39], observations=[observation, header],
                expected_observation_hashes={o.observation_id: sha256_json(o.to_dict()) for o in (observation, header)},
                source_revision_fingerprint=sha256_json("revision-clienta"),
                permission_scope_fingerprint=sha256_json(observation.to_dict()["permission_scope"]),
                source_complete=True, extractor_run_id="semrun_" + unit, ontology_revision_id="ontology_clienta",
                model_name="m", reasoning_effort="none", reader=reader.extract_structured_json,
                configuration=reader.configuration, semantic_metadata_store=SemanticMetadataStore(root),
                candidate_atom_store=CandidateAtomStore(root), candidate_relation_store=CandidateRelationStore(root))
        ledger = result.read_ledger.to_dict()
        if partial:
            ledger["value"].update(annotation_status="pending", validation_status="partial")
        return [{"atom": atom.to_dict(), "ledger": deepcopy(ledger), "unit_id": unit,
                 "observations": {o.observation_id: o.to_dict() for o in (observation, header)}}
                for atom in result.candidate_atoms]

    @staticmethod
    def mapping():
        return ontology.CandidatePropertyMapping.from_dict({
            "artifact_id": "formowl_candidate_property_mapping_v1", "mapping_id": "clienta_v1",
            "review_status": "pending_review", "properties": ["asset_code", "ticket_code", "target_date"],
            "aliases": [{"label": label, "property_id": prop, "qualifiers": extra}
                        for label, prop, extra in (("Asset Code", "asset_code", {}), ("Ticket", "ticket_code", {}),
                                                 ("Expected Date", "target_date", {"kind": "expected"}))],
            "identity_groups": [{"name": "asset_ticket", "properties": ["asset_code", "ticket_code"]}]})

    def test_rows_preserve_values_sources_and_link_only_same_scoped_identity(self):
        members = self.members() + self.members("unit-second", partial=True)
        original = deepcopy(members)
        rows = reconciliation.project_candidate_fact_rows(members, mapping=self.mapping())
        self.assertEqual(members, original)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["identity_candidates"], rows[1]["identity_candidates"])
        self.assertEqual({r["unit_validation_status"] for r in rows}, {"complete", "partial"})
        for r in rows:
            self.assertEqual(r["review_status"], "pending_review")
            self.assertEqual(r["fields"]["target_date"][0]["value"], "2030-06-01")
            self.assertEqual(r["fields"]["target_date"][0]["qualifiers"], {"kind": "expected"})
            self.assertTrue(r["fields"]["target_date"][0]["evidence_spans"][0]["quote"])
            self.assertEqual(r["outer_mail_date"]["value"], "2031-01-01T00:00:00+00:00")
            self.assertTrue(r["outer_mail_date"]["evidence"])

    def test_null_items_do_not_join_and_conflicts_are_not_overwritten(self):
        rows = reconciliation.project_candidate_fact_rows(self.members(row=None), mapping=self.mapping())
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(not r["identity_candidates"] for r in rows))
        members = self.members()
        extra = deepcopy(members[0]);extra["atom"]["candidate_atom_id"] += "_alternative"
        extra["atom"]["properties"]["assertion"]["value"] = "ZX742"
        extra["ledger"]["value"]["candidate_hashes"][extra["atom"]["candidate_atom_id"]] = sha256_json(extra["atom"])
        for member in members:
            member["ledger"] = deepcopy(extra["ledger"])
        rows = reconciliation.project_candidate_fact_rows([*members, extra], mapping=self.mapping())
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["fields"]["asset_code"]), 2)
        self.assertIn("asset_code", rows[0]["conflicting_properties"])
        self.assertFalse(rows[0]["identity_candidates"])

    def test_rejected_changed_atom_or_source_cannot_enter_rows(self):
        for change in ("rejected", "atom", "source", "span"):
            with self.subTest(change=change):
                members = self.members();m = members[0]
                if change == "rejected":
                    m["ledger"]["value"].update(annotation_status="failed", validation_status="rejected_all")
                elif change == "atom":
                    m["atom"]["properties"]["assertion"]["value"] = "invented"
                elif change == "source":
                    next(iter(m["observations"].values()))["text"] += " changed"
                else:
                    m["atom"]["properties"]["evidence_spans"][0]["quote"] = "invented"
                    m["ledger"]["value"]["candidate_hashes"][m["atom"]["candidate_atom_id"]] = sha256_json(m["atom"])
                with self.assertRaises(ContractValidationError):
                    reconciliation.project_candidate_fact_rows(members, mapping=self.mapping())

    def test_configured_unique_header_is_inherited_with_original_provenance(self):
        members = self.members(header_properties=("Ticket", "Expected Date"), partial=True)
        config = self.mapping().data
        config["document_level_properties"] = ["ticket_code", "target_date"]
        rows = reconciliation.project_candidate_fact_rows(
            members, mapping=ontology.CandidatePropertyMapping.from_dict(config))
        detail = next(row for row in rows if row["item_or_row"] == "row-1")
        self.assertEqual(len(rows), 3)  # the two original singleton header rows remain
        self.assertEqual(set(detail["fields"]), {"asset_code", "ticket_code", "target_date"})
        self.assertTrue(detail["identity_candidates"])
        for prop in ("ticket_code", "target_date"):
            inherited = detail["fields"][prop][0]
            original = next(row["fields"][prop][0] for row in rows if row["item_or_row"] is None and prop in row["fields"])
            self.assertTrue(inherited["inherited_from_document_header"])
            self.assertEqual({k: v for k, v in inherited.items() if k != "inherited_from_document_header"}, original)
            self.assertEqual(inherited["unit_validation_status"], "partial")
        self.assertNotIn("inherited_from_document_header", detail["fields"]["asset_code"][0])
        unconfigured = reconciliation.project_candidate_fact_rows(members, mapping=self.mapping())
        self.assertEqual(set(next(r for r in unconfigured if r["item_or_row"] is not None)["fields"]), {"asset_code"})

    def test_header_conflicts_and_other_units_do_not_supply_a_detail_value(self):
        members = self.members(header_properties=("Ticket",))
        extra = deepcopy(next(m for m in members if m["atom"]["properties"]["assertion"].get("property") == "Ticket"))
        extra["atom"]["candidate_atom_id"] += "_alternative"
        extra["atom"]["properties"]["assertion"]["value"] = "R-008"
        extra["ledger"]["value"]["candidate_hashes"][extra["atom"]["candidate_atom_id"]] = sha256_json(extra["atom"])
        for member in members:
            member["ledger"] = deepcopy(extra["ledger"])
        config = self.mapping().data
        config["document_level_properties"] = ["ticket_code"]
        mapping = ontology.CandidatePropertyMapping.from_dict(config)
        rows = reconciliation.project_candidate_fact_rows([*members, extra], mapping=mapping)
        detail = next(row for row in rows if row["item_or_row"] == "row-1")
        self.assertNotIn("ticket_code", detail["fields"])
        self.assertIn("ticket_code", detail["document_header_conflicts"])
        self.assertFalse(detail["identity_candidates"])
        header = [extra]
        other = [m for m in self.members("unit-other") if m["atom"]["properties"]["assertion"].get("property") == "Asset Code"]
        rows = reconciliation.project_candidate_fact_rows(header + other, mapping=mapping)
        self.assertEqual(set(next(r for r in rows if r["unit_id"] == "unit-other")["fields"]), {"asset_code"})


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

    def _member_with_source(self, observation_id: str, text: str, value: str, quote: str) -> GroupMember:
        observation = _observation(observation_id, text)
        atom = _annotate(self.temp_dir, observation, value, quote)
        return GroupMember(
            atom, f"mailocc_{observation_id}", "2026-01-15T09:00:00+08:00",
            {"subject": "通知"}, {observation_id: observation.to_dict()},
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

    def test_update_value_inside_part_number_is_not_an_independent_word(self) -> None:
        older = self._with_value(self.old, "20")
        newer = self._member_with_source(
            "obs_new_part_number", "通知：PO 4500123 更新料號 SP.Z6L22G001", "22",
            "更新料號 SP.Z6L22G001",
        )
        relation = {"source": 1, "target": 0, "relation_type": "updates", "confidence": 0.8,
                    "evidence": [{"observation_id": "obs_new_part_number",
                                  "quote": "更新料號 SP.Z6L22G001"}]}
        with self.assertRaisesRegex(ContractValidationError, "independent word"):
            self._run_members([older, newer], [relation], "recon_sku_substring")

    def test_quantity_value_with_ascii_word_boundaries_is_accepted(self) -> None:
        older = self._with_value(self.old, "280")
        newer = self._member_with_source(
            "obs_new_quantity", "通知：PO 4500123 Q'ty: 320 PCS", "320", "Q'ty: 320 PCS",
        )
        relation = {"source": 1, "target": 0, "relation_type": "updates", "confidence": 0.8,
                    "evidence": [{"observation_id": "obs_new_quantity", "quote": "Q'ty: 320 PCS"}]}
        result = self._run_members([older, newer], [relation], "recon_ascii_boundaries")
        self.assertEqual(result.relations[0].relation_type, "updates")

    def test_value_adjacent_to_cjk_is_accepted(self) -> None:
        newer = self._member_with_source(
            "obs_new_cjk_boundary", "通知：PO 4500123 交期改為1/27", "1/27", "改為1/27",
        )
        relation = {"source": 1, "target": 0, "relation_type": "supersedes", "confidence": 0.8,
                    "evidence": [{"observation_id": "obs_new_cjk_boundary", "quote": "改為1/27"}]}
        result = self._run_members([self.old, newer], [relation], "recon_cjk_boundary")
        self.assertEqual(result.relations[0].relation_type, "supersedes")

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
