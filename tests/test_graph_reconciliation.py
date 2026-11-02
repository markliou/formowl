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
    def members(self, unit="unit-clienta", *, row="row-1", partial=False, header_properties=(),
                subject="ZX-742", subject_label=None, identity_text=None, text=None, property_values=None,
                document=None, revision="revision-clienta", scope="ws_recon", run_id=None):
        root = _paths.fresh_test_dir("candidate-fact-row")
        observation = _observation("obs_" + unit, text or "Clienta ZX-742 ticket R-007 expected 2030-06-01")
        observation = Observation.from_dict({**observation.to_dict(), "permission_scope": {
            **observation.to_dict()["permission_scope"], "scope_id": scope}})
        if document:
            observation = Observation.from_dict({**observation.to_dict(), "asset_id": "asset_" + document,
                "modality": "document", "observation_type": "paragraph", "location": {"block_index": 0}})
        header = Observation.from_dict({**observation.to_dict(), "observation_id": "obs_date_" + unit,
            "observation_type": "email_header", "text": "Wed, 01 Jan 2031 00:00:00 +0000",
            "payload": {"header_name": "Date", "header_value": "Wed, 01 Jan 2031 00:00:00 +0000"}})
        identity_source = _observation("obs_identity_" + unit, identity_text) if identity_text else observation
        if identity_text:
            identity_source = Observation.from_dict({**observation.to_dict(),
                "observation_id": "obs_identity_" + unit, "text": identity_text})
        sources = [observation, header] + ([identity_source] if identity_text else [])
        records = [{"record_type": "claim", "topic": "Clienta", "subject": subject, "subject_label": subject_label,
                    "subject_quote": {"observation_id": identity_source.observation_id,
                                      "quote": identity_text or subject},
                    "item_or_row": None if prop in header_properties else row,
                    "property": prop, "value": value, "unit": None, "event_type": None,
                    "state": None, "actor": None, "times": [], "confidence": 0.9,
                    "evidence": [{"observation_id": observation.observation_id, "quote": observation.text}]}
                   for prop, value in (property_values or (
                       ("Asset Code", "ZX-742"), ("Ticket", "R-007"), ("Expected Date", "2030-06-01")))]
        body = json.dumps({"model": "m", "done_reason": "stop", "message": {"content": json.dumps(
            {"read_status": "complete", "records": records, "relations": []})}})
        reader = LocalOllamaReader("http://127.0.0.1:1", "m")
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body.encode())):
            result = read_and_store_source_unit(
                source_unit_id="su_" + sha256_json(unit)[7:39], observations=sources,
                expected_observation_hashes={o.observation_id: sha256_json(o.to_dict()) for o in sources},
                source_revision_fingerprint=sha256_json(revision),
                permission_scope_fingerprint=sha256_json(observation.to_dict()["permission_scope"]),
                source_complete=True, extractor_run_id=run_id or "semrun_" + unit, ontology_revision_id="ontology_clienta",
                model_name="m", reasoning_effort="none", reader=reader.extract_structured_json,
                configuration=reader.configuration, semantic_metadata_store=SemanticMetadataStore(root),
                candidate_atom_store=CandidateAtomStore(root), candidate_relation_store=CandidateRelationStore(root))
        ledger = result.read_ledger.to_dict()
        if partial:
            ledger["value"].update(annotation_status="pending", validation_status="partial")
        return [{"atom": atom.to_dict(), "ledger": deepcopy(ledger), "unit_id": unit,
                 "observations": {o.observation_id: o.to_dict() for o in sources}}
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

    def test_cross_unit_headers_preserve_every_donor_in_purchase_and_lab_documents(self):
        for domain, target, code, labels in (
            ("purchase", "ZX-742", "ZX74200001", ("Part", "PO No.", "Order Date")),
            ("lab", "SAMPLE-7", "LAB009", ("Specimen", "Report ID", "Report Date")),
        ):
            with self.subTest(domain=domain):
                mapping = ontology.CandidatePropertyMapping.from_dict({
                    "artifact_id": "formowl_candidate_property_mapping_v1", "mapping_id": domain,
                    "review_status": "pending_review", "properties": ["item", "document", "date"],
                    "aliases": [{"label": label, "property_id": prop, "qualifiers": {}}
                                for label, prop in zip(labels, ("item", "document", "date"))],
                    "document_level_properties": ["document", "date"],
                    "identity_groups": [{"name": "item_document", "properties": ["item", "document"]}]})
                headers = []
                for suffix in ("a", "b"):
                    headers += self.members(domain + "-header-" + suffix, document=domain, row=None,
                        subject=code, text=f"{labels[1]} {code}; {labels[2]} 2030-06-01",
                        property_values=((labels[1], code), (labels[2], "2030-06-01")))
                detail = self.members(domain + "-rows", document=domain, partial=True, subject=target,
                    text=f"{labels[0]} {target}", property_values=((labels[0], target),))
                members, before = headers + detail, deepcopy(headers + detail)
                rows = reconciliation.project_candidate_fact_rows(members, mapping=mapping)
                result = next(r for r in rows if r["item_or_row"] is not None)
                self.assertEqual(members, before)
                self.assertEqual(len(rows), 5)
                self.assertEqual(result["unit_validation_status"], "partial")
                for prop, value in (("document", code), ("date", "2030-06-01")):
                    fields = result["fields"][prop]
                    self.assertEqual(len(fields), 2)
                    self.assertEqual({f["value"] for f in fields}, {value})
                    for field in fields:
                        donor = next(r["fields"][prop][0] for r in rows if r["item_or_row"] is None
                                     and prop in r["fields"] and r["fields"][prop][0]["candidate_atom_id"] == field["candidate_atom_id"])
                        self.assertEqual({k: v for k, v in field.items() if k != "inherited_from_document_header"}, donor)
                        self.assertTrue(field["inherited_from_document_header"])
                        self.assertEqual(field["unit_validation_status"], "complete")
                self.assertTrue(result["identity_candidates"])

    def test_cross_unit_conflicts_and_detail_only_values_never_fill_headers(self):
        config = self.mapping().data
        config["document_level_properties"] = ["ticket_code"]
        mapping = ontology.CandidatePropertyMapping.from_dict(config)
        header = self.members("header", document="contract", row=None, property_values=(("Ticket", "R-007"),))
        missing = self.members("missing", document="contract", property_values=(("Asset Code", "ZX-742"),))
        for row in (None, "another-row"):
            with self.subTest(conflicting_item=row):
                conflict = self.members("conflict", document="contract", row=row,
                    text="ZX-742 ticket R-008", property_values=(("Ticket", "R-008"),))
                rows = reconciliation.project_candidate_fact_rows(header + conflict + missing, mapping=mapping)
                result = next(r for r in rows if r["unit_id"] == "missing")
                self.assertNotIn("ticket_code", result["fields"])
                self.assertEqual(set(result["document_header_conflicts"]["ticket_code"]),
                    {m["atom"]["candidate_atom_id"] for m in header + conflict})
                self.assertFalse(result["identity_candidates"])
        detail_only = self.members("detail-only", document="contract", property_values=(("Ticket", "R-007"),))
        rows = reconciliation.project_candidate_fact_rows(detail_only + missing, mapping=mapping)
        self.assertNotIn("ticket_code", next(r for r in rows if r["unit_id"] == "missing")["fields"])

    def test_cross_unit_headers_require_document_revision_and_permission_boundaries(self):
        config = self.mapping().data
        config["document_level_properties"] = ["ticket_code"]
        mapping = ontology.CandidatePropertyMapping.from_dict(config)
        for change in ({"document": None}, {"document": "other"},
                       {"revision": "other"}, {"scope": "ws_other"}):
            with self.subTest(change=change):
                header = self.members("header", document=None if change.get("document", "same") is None else "same",
                    row=None, property_values=(("Ticket", "R-007"),))
                detail = self.members("rows", **({"document": "same"} | change),
                    property_values=(("Asset Code", "ZX-742"),))
                before = reconciliation.project_candidate_fact_rows(detail, mapping=mapping)
                after = reconciliation.project_candidate_fact_rows(header + detail, mapping=mapping)
                self.assertEqual(next(r for r in after if r["unit_id"] == "rows"), before[0])

    def test_larger_document_context_removes_prior_inheritance_when_a_conflict_appears(self):
        config = self.mapping().data
        config["document_level_properties"] = ["ticket_code"]
        mapping = ontology.CandidatePropertyMapping.from_dict(config)
        header = self.members("header", document="contract", row=None, property_values=(("Ticket", "R-007"),))
        detail = self.members("rows", document="contract", property_values=(("Asset Code", "ZX-742"),))
        conflict = self.members("other-export", document="contract", row=None,
            text="ZX-742 ticket R-008", property_values=(("Ticket", "R-008"),))
        rows = reconciliation.project_candidate_fact_rows(header + detail, mapping=mapping)
        self.assertTrue(next(r for r in rows if r["unit_id"] == "rows")["identity_candidates"])
        rows += reconciliation.project_candidate_fact_rows(conflict, mapping=mapping)
        keys = {r["row_id"]: {reconciliation._fact_document_key(next(iter(detail[0]["observations"].values())))} for r in rows}
        reconciliation._inherit_document_headers(rows, ["ticket_code"], keys)
        reconciliation._finalize_candidate_fact_rows(rows, mapping=mapping)
        result = next(r for r in rows if r["unit_id"] == "rows")
        self.assertNotIn("ticket_code", result["fields"])
        self.assertIn("ticket_code", result["document_header_conflicts"])
        self.assertFalse(result["identity_candidates"])
        before = deepcopy(rows)
        reconciliation._inherit_document_headers(rows, ["ticket_code"], keys)
        reconciliation._finalize_candidate_fact_rows(rows, mapping=mapping)
        self.assertEqual(rows, before)

    def test_entity_projection_uses_existing_label_match_and_own_surface_evidence(self):
        member = self.members(subject="R-007", subject_label="Ticket", identity_text="Ticket R-007")[0]
        atom = member["atom"]
        atom["atom_type"] = "entity"
        atom["properties"]["assertion"].update(property=None, value=None)
        member["ledger"]["value"]["candidate_hashes"][atom["candidate_atom_id"]] = sha256_json(atom)
        rows = reconciliation.project_candidate_fact_rows([member], mapping=self.mapping())
        field = rows[0]["fields"]["ticket_code"][0]
        self.assertEqual((field["raw_property"], field["value"], field["value_origin"]), ("Ticket", "R-007", "entity_surface"))
        self.assertEqual(field["evidence_spans"], atom["properties"]["target_identity"]["evidence_spans"])
        self.assertNotEqual(field["evidence_spans"], atom["properties"]["evidence_spans"])
        for kind in ("unmapped", "claim", "existing_property", "surface"):
            with self.subTest(kind=kind):
                bad = deepcopy(member)
                props = bad["atom"]["properties"]
                if kind == "unmapped":
                    props["target_identity"]["type_surface"] = "Unmapped document label"
                elif kind == "claim":
                    bad["atom"]["atom_type"] = "claim"
                elif kind == "existing_property":
                    props["assertion"]["property"] = "Unmapped property"
                else:
                    props["target_identity"]["value_surface"] = "UNSUPPORTED"
                bad["ledger"]["value"]["candidate_hashes"][atom["candidate_atom_id"]] = sha256_json(bad["atom"])
                if kind == "surface":
                    with self.assertRaisesRegex(ContractValidationError, "entity surface"):
                        reconciliation.project_candidate_fact_rows([bad], mapping=self.mapping())
                else:
                    self.assertEqual(reconciliation.project_candidate_fact_rows([bad], mapping=self.mapping()), [])

    def test_entity_field_does_not_replace_the_original_item_subject(self):
        members = self.members(subject="ZX-742", identity_text="Ticket R-007 ZX-742")
        atom = next(m["atom"] for m in members if m["atom"]["properties"]["assertion"]["property"] == "Asset Code")
        atom["atom_type"] = "entity"
        atom["properties"]["assertion"].update(property=None, value=None, target="R-007")
        atom["properties"]["target_identity"].update(type_surface="Ticket", value_surface="R-007")
        for member in members:
            member["ledger"]["value"]["candidate_hashes"][atom["candidate_atom_id"]] = sha256_json(atom)
        rows = reconciliation.project_candidate_fact_rows(members, mapping=self.mapping())
        self.assertEqual(rows[0]["subject_identity"]["value"], "zx-742")
        self.assertEqual({f["value"] for f in rows[0]["fields"]["ticket_code"]}, {"R-007"})

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

    def test_every_field_keeps_its_own_source_unit_permission_and_identity_lineage(self):
        members = self.members(header_properties=("Ticket",))
        config = self.mapping().data
        config["document_level_properties"] = ["ticket_code"]
        rows = reconciliation.project_candidate_fact_rows(
            members, mapping=ontology.CandidatePropertyMapping.from_dict(config))
        detail = next(row for row in rows if row["item_or_row"] is not None)
        for fields in detail["fields"].values():
            for field in fields:
                member = next(m for m in members if m["atom"]["candidate_atom_id"] == field["candidate_atom_id"])
                pins, props = member["ledger"]["value"]["pins"], member["atom"]["properties"]
                self.assertIn("unit_id", field)
                self.assertEqual(field["unit_id"], member["unit_id"])
                for key in ("source_unit_id", "source_revision_fingerprint", "permission_scope_fingerprint"):
                    self.assertEqual(field[key], pins[key])
                self.assertEqual(field["permission_scope"], props["permission_scope"])
                self.assertEqual(field["source_observation_ids"], member["atom"]["source_observation_ids"])
                self.assertEqual(field["observation_hashes"], {
                    oid: pins["observation_hashes"][oid] for oid in field["source_observation_ids"]})
                for key in ("target_identity", "identity_bindings", "evidence_spans"):
                    self.assertEqual(field[key], props[key])
        self.assertNotEqual(detail["outer_mail_date"]["value"], detail["fields"]["target_date"][0]["value"])

    def test_multiple_temporal_roles_and_same_role_alternatives_remain_source_bound(self):
        members = self.members()
        base = next(m for m in members if m["atom"]["properties"]["assertion"]["property"] == "Expected Date")
        config = self.mapping().data
        config["aliases"].append({"label": "Committed Date", "property_id": "target_date",
                                  "qualifiers": {"kind": "committed"}})
        alternatives = []
        for suffix, label, value in (("_requested2", "Expected Date", "2030-06-02"),
                                     ("_committed", "Committed Date", "2030-06-03")):
            member = deepcopy(base)
            member["atom"]["candidate_atom_id"] += suffix
            member["atom"]["properties"]["assertion"].update(property=label, value=value)
            alternatives.append(member)
        ledger = deepcopy(base["ledger"])
        for member in alternatives:
            ledger["value"]["candidate_hashes"][member["atom"]["candidate_atom_id"]] = sha256_json(member["atom"])
        for member in members + alternatives:
            member["ledger"] = deepcopy(ledger)
        rows = reconciliation.project_candidate_fact_rows(
            members + alternatives, mapping=ontology.CandidatePropertyMapping.from_dict(config))
        fields = rows[0]["fields"]["target_date"]
        self.assertEqual({(f["value"], f["qualifiers"]["kind"]) for f in fields},
                         {("2030-06-01", "expected"), ("2030-06-02", "expected"), ("2030-06-03", "committed")})
        self.assertEqual(rows[0]["conflicting_properties"], ["target_date"])
        self.assertTrue(all(f.get("unit_id") == "unit-clienta" and f["evidence_spans"] for f in fields))

    def test_project_cli_reports_safe_field_coverage_including_missing_fields(self):
        from test_issue56_semantic_annotation import CandidateProjectionCommandTests, annotation
        fixture = CandidateProjectionCommandTests()
        root, args = fixture.fixture()
        config = json.loads((root / "mapping").read_text())
        config["properties"].append("unobserved_property")
        (root / "mapping").write_text(json.dumps(config))
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no provider calls")):
            self.assertEqual(annotation.main(["project", "--units", args.units,
                "--annotation-output", args.annotation_output, "--run-id", args.run_id,
                "--mapping", args.mapping, "--output", args.output]), 0)
        result = json.loads((root / "export" / "manifest.json").read_text())
        self.assertIn("field_coverage", result)
        self.assertEqual(result["field_coverage"]["asset_code"],
                         {"rows": 1, "values": 1, "units": 1, "conflicting_rows": 0,
                          "document_header_conflict_rows": 0, "conflicting_identity_groups": 0})
        self.assertEqual(result["field_coverage"]["unobserved_property"]["rows"], 0)
        self.assertEqual(result["conflict_counts"],
                         {"row_properties": 0, "document_header_properties": 0, "linked_identity_properties": 0})
        self.assertFalse(result["scope_complete"])
        self.assertFalse(result["semantic_correctness_verified"])
        self.assertNotIn("ZX-742", json.dumps(result))
        self.assertEqual((root / "export" / "manifest.json").stat().st_mode & 0o777, 0o600)


class CandidateSubjectIdentityTests(unittest.TestCase):
    def members(self, **kwargs):
        return [m for m in CandidateFactRowTests().members(**kwargs)
                if m["atom"]["properties"]["assertion"]["property"] != "Asset Code"]

    def project(self, members, mapping=None):
        return reconciliation.project_candidate_fact_rows(members, mapping=mapping or CandidateFactRowTests.mapping())

    @staticmethod
    def repin(members):
        for member in members:
            member["ledger"]["value"]["candidate_hashes"].update(
                {m["atom"]["candidate_atom_id"]: sha256_json(m["atom"]) for m in members})

    def test_shared_subject_is_untyped_and_keeps_each_original_identity_source(self):
        for label in (None, "Ticket"):
            with self.subTest(label=label):
                members = self.members(subject_label=label, identity_text="Ticket ZX-742")
                before = deepcopy(members)
                row = self.project(members)[0]
                self.assertIn("subject_identity", row)
                subject = row["subject_identity"]
                self.assertEqual((subject["value"], subject["type"], subject["origin"], subject["review_status"]),
                                 ("zx-742", None, "annotation_target", "pending_review"))
                self.assertFalse(subject["semantic_correctness_verified"])
                self.assertEqual(len(subject["sources"]), len(members))
                for source in subject["sources"]:
                    member = next(m for m in members if m["atom"]["candidate_atom_id"] == source["candidate_atom_id"])
                    identity = member["atom"]["properties"]["target_identity"]
                    self.assertEqual(source["value_surface"], "ZX-742")
                    self.assertEqual(source["target_identity"], identity)
                    self.assertEqual(source["evidence_spans"], identity["evidence_spans"])
                    self.assertEqual(source["unit_id"], member["unit_id"])
                    self.assertEqual(source["source_revision_fingerprint"],
                                     member["ledger"]["value"]["pins"]["source_revision_fingerprint"])
                    self.assertEqual(source["permission_scope"], member["atom"]["properties"]["permission_scope"])
                    for span in source["evidence_spans"]:
                        self.assertIn(span["observation_id"], source["source_observation_ids"])
                        self.assertEqual(source["observation_hashes"][span["observation_id"]], span["observation_hash"])
                        self.assertTrue(span["observation_id"].startswith("obs_identity_"))
                self.assertEqual(members, before)
                self.assertEqual(self.project(list(reversed(members)))[0]["subject_identity"], subject)

    def test_subject_agreement_normalizes_whole_surfaces_and_preserves_raw_values(self):
        members = self.members(subject="ＺＸ-００７", identity_text="ＺＸ-００７ zx-007")
        identity = members[1]["atom"]["properties"]["target_identity"]
        identity["value_surface"] = "zx-007"
        members[1]["atom"]["properties"]["assertion"]["target"] = "zx-007"
        self.repin(members)
        row = self.project(members)[0]
        self.assertIn("subject_identity", row)
        self.assertEqual(row["subject_identity"]["value"], "zx-007")
        self.assertEqual({s["value_surface"] for s in row["subject_identity"]["sources"]}, {"ＺＸ-００７", "zx-007"})

    def test_missing_conflicting_colliding_and_singleton_subjects_are_not_selected(self):
        cases = ("missing", "missing_identity", "blank", "different", "punctuation", "zero", "field", "singleton")
        for case in cases:
            with self.subTest(case=case):
                members = self.members(subject="ZX-007", identity_text="ZX-007 ZX-7 ZX007 Clienta")
                props = members[0]["atom"]["properties"]
                if case == "missing":
                    props["target_identity"].pop("value_surface", None)
                elif case == "missing_identity":
                    props.pop("target_identity")
                elif case == "blank":
                    props["target_identity"]["value_surface"] = " \t"
                elif case in ("different", "punctuation", "zero"):
                    props["target_identity"]["value_surface"] = {
                        "different": "Clienta", "punctuation": "ZX007", "zero": "ZX-7"}[case]
                elif case == "field":
                    props["assertion"]["value"] = "ｚｘ-００７"
                else:
                    for m in members:
                        m["atom"]["properties"]["assertion"]["item_or_row"] = None
                self.repin(members)
                self.assertTrue(all("subject_identity" not in row for row in self.project(members)))

    def test_identity_spans_are_revalidated_even_when_field_spans_are_valid(self):
        for change in ("missing", "offset", "hash", "locator", "extractor", "outside", "source_permission"):
            with self.subTest(change=change):
                members = self.members(identity_text="Subject ZX-742")
                props = members[0]["atom"]["properties"]
                span = props["target_identity"]["evidence_spans"][0]
                if change == "missing":
                    props["target_identity"]["evidence_spans"] = []
                elif change == "offset":
                    span["start"] += 1
                elif change == "hash":
                    span["observation_hash"] = sha256_json("different")
                elif change == "locator":
                    span["native_locator"] = {"page": 99}
                elif change == "extractor":
                    span["source_extractor_run_id"] = "run_other"
                elif change == "outside":
                    members[0]["atom"]["source_observation_ids"].remove(span["observation_id"])
                else:
                    members[0]["observations"][span["observation_id"]]["permission_scope"]["scope_id"] = "ws_other"
                self.repin(members)
                with self.assertRaises(ContractValidationError):
                    self.project(members)

    def test_inherited_header_targets_do_not_vote_but_inherited_values_can_exclude(self):
        members = self.members(header_properties=("Ticket",), identity_text="ZX-742 R-007")
        header = next(m for m in members if m["atom"]["properties"]["assertion"].get("item_or_row") is None)
        header["atom"]["properties"]["target_identity"]["value_surface"] = "R-007"
        header["atom"]["properties"]["assertion"]["target"] = "R-007"
        self.repin(members)
        data = CandidateFactRowTests.mapping().data
        data["document_level_properties"] = ["ticket_code"]
        mapping = ontology.CandidatePropertyMapping.from_dict(data)
        rows = self.project(members, mapping)
        detail = next(row for row in rows if row["item_or_row"] is not None)
        self.assertIn("subject_identity", detail)
        self.assertEqual(len(detail["subject_identity"]["sources"]), 1)
        self.assertTrue(detail["fields"]["ticket_code"][0]["inherited_from_document_header"])
        self.assertTrue(all("subject_identity" not in row for row in rows if row["item_or_row"] is None))
        header["atom"]["properties"]["assertion"]["value"] = "ＺＸ-７４２"
        self.repin(members)
        detail = next(row for row in self.project(members, mapping) if row["item_or_row"] is not None)
        self.assertNotIn("subject_identity", detail)


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
