from __future__ import annotations

import io
import json
import unittest
from unittest import mock

import jsonschema

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, Observation, sha256_json
from formowl_graph.candidates import read_and_store_source_unit
from formowl_graph.local_semantic_reader import Adapter, LocalOllamaReader, flat_schema, presented
from formowl_graph.storage import CandidateAtomStore, CandidateRelationStore, SemanticMetadataStore

BODY = "From: Person B 人乙 ( OrgB )\nPO No. 4500123 交期 2025/12/08\nPO No. 4500124 交期 2025/12/09"


def _observation(observation_id: str, text: str, payload: dict | None = None) -> Observation:
    return Observation(
        observation_id=observation_id, asset_id="asset_local_reader_001",
        extractor_run_id="run_local_reader_source_001", observation_type="email_body_segment",
        modality="mail", text=text,
        location={"message_occurrence_id": "mailocc_0123456789abcdef0123", "body_segment_index": 0},
        confidence=1.0, created_at="2026-10-25T00:00:00+00:00", payload=payload,
        permission_scope={"scope_type": "workspace", "visibility": "restricted", "scope_id": "ws_local_reader"},
    )


def _sources(*observations: Observation) -> dict:
    return {o.observation_id: o.to_dict() for o in observations}


def _record(**overrides) -> dict:
    record = {"record_type": "claim", "topic": "交期", "subject": None, "subject_label": None,
              "subject_quote": None, "item_or_row": None, "property": "交期", "value": "2025/12/08",
              "unit": None, "event_type": None, "state": None, "actor": None, "times": [],
              "evidence": [{"observation_id": "obs_body", "quote": "PO No. 4500123 交期 2025/12/08"}],
              "confidence": 0.9}
    record.update(overrides)
    return record


class AdapterLocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = Adapter(_sources(_observation("obs_body", BODY)))

    def test_exact_quote_gets_its_field_path(self) -> None:
        span = self.adapter.span({"observation_id": "obs_body", "quote": "交期 2025/12/08"})
        self.assertEqual((span["field_path"], span["quote"], span["occurrence_index"]),
                         (["text"], "交期 2025/12/08", None))
        self.assertEqual(self.adapter.relocated, 0)

    def test_whitespace_only_difference_maps_to_the_unique_source_text(self) -> None:
        span = self.adapter.span({"observation_id": "obs_body", "quote": "人乙 (OrgB)"})
        self.assertEqual(span["quote"], "人乙 ( OrgB )")
        self.assertEqual(self.adapter.relocated, 1)

    def test_other_differences_and_repeats_are_left_for_the_validator(self) -> None:
        changed = self.adapter.span({"observation_id": "obs_body", "quote": "人乙（OrgB）"})
        self.assertEqual(changed["quote"], "人乙（OrgB）")
        repeated = self.adapter.span({"observation_id": "obs_body", "quote": "PONo."})
        self.assertEqual(repeated["quote"], "PONo.")
        self.adapter.span({"observation_id": "obs_body", "quote": "PO No."})
        self.assertEqual(self.adapter.relocated, 0)
        self.assertEqual(len(self.adapter.problems), 3)  # not found, not found, repeated twice

    def test_subject_outside_its_quote_is_located_in_the_cited_observation(self) -> None:
        data = self.adapter.convert({"records": [_record(
            subject="Person B 人乙 ( OrgB )",
            subject_quote={"observation_id": "obs_body", "quote": "PO No. 4500123"})]})
        identity = data["identities"][0]
        self.assertEqual(identity["value_surface"], "Person B 人乙 ( OrgB )")
        self.assertEqual(identity["evidence"][0]["quote"], "Person B 人乙 ( OrgB )")
        self.assertEqual(data["atoms"][0]["assertion"]["target"], "Person B 人乙 ( OrgB )")
        self.assertEqual(self.adapter.counts["surface_located"], 1)

    def test_invented_label_and_subject_are_cleared_but_the_fact_is_kept(self) -> None:
        data = self.adapter.convert({"records": [
            _record(subject="4500123", subject_label="訂單編號",
                    subject_quote={"observation_id": "obs_body", "quote": "PO No. 4500123"}),
            _record(subject="虛構測試專案", subject_quote={"observation_id": "obs_body", "quote": "PO No. 4500123"})]})
        self.assertIsNone(data["identities"][0]["type_surface"])
        self.assertEqual(len(data["identities"]), 1)
        self.assertIsNone(data["atoms"][1]["assertion"]["target"])
        self.assertEqual(data["atoms"][1]["assertion"]["value"], "2025/12/08")
        self.assertEqual(self.adapter.counts["invented_label_cleared"], 1)
        self.assertEqual(self.adapter.counts["invented_subject_cleared"], 1)

    def test_fact_evidence_is_limited_to_focus_while_names_may_cite_context(self) -> None:
        schema = flat_schema(["obs_head", "obs_body"], 8, ["obs_body"])
        claim = schema["properties"]["records"]["items"]["anyOf"][1]["properties"]
        self.assertEqual(claim["evidence"]["items"]["properties"]["observation_id"]["enum"], ["obs_body"])
        subject_quote = claim["subject_quote"]["properties"]["observation_id"]["enum"]
        self.assertEqual(subject_quote, ["obs_head", "obs_body"])

    def test_named_subject_requires_an_explicit_subject_quote(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "subject quote"):
            self.adapter.convert({"records": [_record(subject="4500123")]})

    def test_targetless_fact_does_not_promote_actor_topic_or_item(self) -> None:
        data = self.adapter.convert({"records": [_record(
            topic="4500123", actor="Person B", item_or_row="4500123")]})
        self.assertIsNone(data["atoms"][0]["assertion"]["target"])
        self.assertEqual(data["identities"], [])

    def test_schema_pairs_a_named_subject_with_a_nonnull_quote(self) -> None:
        schema = flat_schema(["obs_body"], 8)
        data = {"read_status": "complete", "records": [_record(subject="4500123")], "relations": []}
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)
        data["records"][0]["subject_quote"] = {"observation_id": "obs_body", "quote": "PO No. 4500123"}
        jsonschema.validate(data, schema)
        data["records"][0] = _record(actor="Person B", item_or_row="4500123")
        jsonschema.validate(data, schema)
        self.assertIsNone(self.adapter.convert(data)["atoms"][0]["assertion"]["target"])

    def test_read_inventory_is_filled_only_for_a_reported_complete_read(self) -> None:
        self.assertEqual(self.adapter.convert({"read_status": "complete"})["read_observation_ids"], ["obs_body"])
        self.assertEqual(self.adapter.convert({"read_status": "incomplete"})["read_observation_ids"], [])

    def test_model_view_drops_only_opaque_hashes_and_ids(self) -> None:
        observation = _observation("obs_body", BODY, payload={
            "message_fingerprint": "sha256:" + "a" * 64, "thread_id": "mailthread_0123456789abcdef",
            "header_value": "Person B"})
        unit = {"observations": [observation.to_dict()], "focus_observation_ids": ["obs_body"],
                "context_observation_ids": []}
        view = presented(unit)["observations"][0]
        self.assertEqual(view["payload"], {"header_value": "Person B"})
        self.assertEqual(view["text"], BODY)
        self.assertNotIn("permission_scope", view)


class LocalReaderContractTests(unittest.TestCase):
    def test_converted_output_passes_the_unchanged_contract_validator(self) -> None:
        temp_dir = _paths.fresh_test_dir("local-semantic-reader")
        observation = _observation("obs_body", BODY)
        flat = {"read_status": "complete", "relations": [],
                "records": [_record(
                    subject="4500123", subject_label="PO No.",
                    subject_quote={"observation_id": "obs_body", "quote": "PO No. 4500123"},
                    times=[{"role": "due", "raw": "2025/12/08", "normalized": "2025-12-08",
                            "precision": "day",
                            "quote": {"observation_id": "obs_body", "quote": "交期 2025/12/08"}}])]}
        body = json.dumps({"model": "local-model", "done_reason": "stop", "prompt_eval_count": 10,
                           "eval_count": 20, "message": {"content": json.dumps(flat, ensure_ascii=False)}})
        reader = LocalOllamaReader("http://127.0.0.1:1", "local-model")
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body.encode())) as urlopen:
            result = read_and_store_source_unit(
                source_unit_id="su_local_reader_001", observations=[observation],
                expected_observation_hashes={"obs_body": sha256_json(observation.to_dict())},
                source_revision_fingerprint=sha256_json({"revision": 1}),
                permission_scope_fingerprint=sha256_json(observation.to_dict()["permission_scope"]),
                source_complete=True, extractor_run_id="semrun_local_reader_001",
                ontology_revision_id="ontology_local_reader", model_name="local-model",
                reasoning_effort="none", reader=reader.extract_structured_json,
                configuration=reader.configuration,
                semantic_metadata_store=SemanticMetadataStore(temp_dir),
                candidate_atom_store=CandidateAtomStore(temp_dir),
                candidate_relation_store=CandidateRelationStore(temp_dir))
        sent = json.loads(urlopen.call_args.args[0].data)
        self.assertNotIn("read_observation_ids", sent["format"]["properties"])
        self.assertEqual(result.read_ledger.value["coverage_counts"]["missing_observation_count"], 0)
        self.assertEqual(result.read_ledger.value["annotation_status"], "annotated")
        atom = result.candidate_atoms[0]
        self.assertEqual(atom.status, "pending_review")
        self.assertEqual(atom.properties["assertion"]["target"], "4500123")
        self.assertEqual(atom.properties["times"][0]["property"], "交期")
        self.assertEqual(result.read_ledger.value["pins"]["model_name"], "local-model")

    def test_truncated_generation_is_not_a_completed_read(self) -> None:
        body = json.dumps({"done_reason": "length", "message": {"content": "{"}})
        reader = LocalOllamaReader("http://127.0.0.1:1", "local-model")
        unit = {"observations": [_observation("obs_body", BODY).to_dict()],
                "focus_observation_ids": ["obs_body"], "context_observation_ids": []}
        schema = {"properties": {"atoms": {}}}
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body.encode())):
            with self.assertRaisesRegex(ContractValidationError, "incomplete"):
                reader.extract_structured_json(instructions="", source_unit=unit, response_schema=schema,
                                               schema_name="x")


class AtomValidationTests(unittest.TestCase):
    def read(self, text, records, *, relations=None, observations=None, mutate=None, focus_ids=None):
        root = _paths.fresh_test_dir("atom-validation-ap")
        items = observations or [_observation("obs_body", text)]
        sources = _sources(*items)
        data = Adapter(sources).convert({"read_status": "complete", "records": records,
                                         "relations": relations or []})
        if mutate:
            mutate(data)
        self.stores = dict(semantic_metadata_store=SemanticMetadataStore(root),
                          candidate_atom_store=CandidateAtomStore(root),
                          candidate_relation_store=CandidateRelationStore(root))
        return read_and_store_source_unit(
            source_unit_id="su_ap_test", observations=items,
            expected_observation_hashes={k: sha256_json(v) for k, v in sources.items()},
            source_revision_fingerprint=sha256_json("ap-source"),
            permission_scope_fingerprint=sha256_json(items[0].to_dict()["permission_scope"]),
            source_complete=True, extractor_run_id="semrun_ap_test", ontology_revision_id="ontology_ap",
            model_name="local-model", reasoning_effort="none",
            focus_observation_ids=focus_ids,
            reader=lambda **_: {"data": data, "requested_model": "local-model", "observed_model": None,
                                 "reasoning_effort": "none", "request_fingerprint": sha256_json("original-call")},
            **self.stores)

    @staticmethod
    def record(quote, **kwargs):
        return _record(evidence=[{"observation_id": "obs_body", "quote": quote}], **kwargs)

    def test_repeated_short_quote_uses_the_unique_same_atom_anchor(self):
        result = self.read("Clienta qty 2; OrgB qty 2", [self.record("2", subject="Clienta",
            subject_quote={"observation_id": "obs_body", "quote": "Clienta qty 2"})])
        span = result.candidate_atoms[0].properties["evidence_spans"][0]
        self.assertEqual((span["start"], span["end"]), (12, 13))
        self.assertEqual(result.read_ledger.value["annotation_status"], "annotated")

    def test_unique_physical_line_keeps_precedence_over_new_anchors(self):
        text = "Clienta 2\n2\nOrgB 2"
        record = self.record("2")
        record["evidence"] += [{"observation_id": "obs_body", "quote": q}
                               for q in ("Clienta 2", "OrgB 2")]
        result = self.read(text, [record])
        self.assertEqual(result.read_ledger.value["annotation_status"], "annotated")
        span = result.candidate_atoms[0].properties["evidence_spans"][0]
        self.assertEqual((span["start"], span["end"]), (10, 11))

    def test_discontinuous_lines_keep_each_original_position(self):
        text = "Model\nQty\nPO\nClienta\n500\nAX123"
        result = self.read(text, [self.record("Qty\n500")])
        spans = result.candidate_atoms[0].properties["evidence_spans"]
        self.assertEqual([s["quote"] for s in spans], ["Qty", "500"])
        self.assertEqual([(s["start"], s["end"]) for s in spans], [(6, 9), (21, 24)])
        self.assertTrue(all(text[s["start"]:s["end"]] == s["quote"] for s in spans))

    def test_segmented_repeated_piece_keeps_its_original_occurrence_index(self):
        result = self.read("2 outside\nQty\nx\n2", [self.record("Qty\n2")])
        spans = result.candidate_atoms[0].properties["evidence_spans"]
        self.assertEqual(spans[1]["occurrence_index"], 1)
        self.assertEqual(spans[1]["start"], 16)

    def test_partial_keeps_valid_atom_and_rejects_dependent_relation(self):
        result = self.read("Clienta confirmed", [self.record("Clienta confirmed"), self.record("absent")],
            relations=[{"source_record": 0, "target_record": 1, "relation_type": "updates",
                        "evidence": [{"observation_id": "obs_body", "quote": "Clienta confirmed"}],
                        "confidence": 0.9}])
        value = result.read_ledger.value
        self.assertEqual((value["annotation_status"], value["validation_status"]), ("pending", "partial"))
        self.assertEqual((value["rejected_atom_count"], value["rejected_relation_count"]), (1, 1))
        self.assertEqual(value["rejected_reasons"], {"exact_span_mismatch": 1, "dependent_atom_rejected": 1})
        self.assertEqual(len(result.candidate_atoms), 1)
        self.assertEqual(result.candidate_relations, [])
        self.assertEqual(len(value["candidate_hashes"]), 1)
        self.assertEqual(result.candidate_atoms[0].status, "pending_review")

    def test_missing_single_quote_is_not_an_annotated_zero(self):
        value = self.read("Clienta", [self.record("absent")]).read_ledger.value
        self.assertEqual((value["annotation_status"], value["validation_status"]), ("failed", "rejected_all"))
        self.assertEqual(value["candidate_count"], 0)
        self.assertEqual(value["rejected_atom_count"], 1)

    def test_true_zero_is_annotated_and_policy_is_server_pinned(self):
        value = self.read("Clienta", []).read_ledger.value
        self.assertEqual((value["annotation_status"], value["validation_status"]), ("annotated", "complete"))
        self.assertTrue(value["pins"]["validation_policy_id"])
        self.assertEqual(value["rejected_atom_count"], 0)

    def test_ambiguous_tied_conflicting_or_far_anchors_do_not_choose_an_occurrence(self):
        cases = [
            ("2 aa 2", ["aa"]),
            ("Clienta 2 / OrgB 2", ["Clienta 2", "OrgB 2"]),
            ("Clienta" + "x" * 129 + "2 / 2", ["Clienta"]),
            ("2 / 2", []),
        ]
        for text, anchors in cases:
            with self.subTest(text=text[:30]):
                record = self.record("2")
                record["evidence"] += [{"observation_id": "obs_body", "quote": q} for q in anchors]
                value = self.read(text, [record]).read_ledger.value
                self.assertEqual(value["validation_status"], "rejected_all")

    def test_multiline_missing_segment_span_gap_and_order_limits_remain_strict(self):
        cases = [("Qty\n" + "x" * 129 + "\n500", "Qty\n500"),
                 ("Qty\n" + "x" * 123 + "\n500\n" + "y" * 123 + "\nPO", "Qty\n500\nPO"),
                 ("Qty\n500", "Qty\nmissing"), ("500\nQty", "Qty\n500"),
                 ("\n".join("ABCDEFGHI"), "\n".join("ABCDEFGHI"))]
        for text, quote in cases:
            with self.subTest(quote=quote):
                # A contiguous nine-line quote remains valid; force nine separated segments.
                if quote.count("\n") == 8:
                    text = text.replace("\n", "\nx\n")
                value = self.read(text, [self.record(quote)]).read_ledger.value
                self.assertEqual(value["validation_status"], "rejected_all")

    def test_same_observation_other_scalar_cannot_anchor(self):
        item = _observation("obs_body", "2 / 2", {"anchor": "Clienta"})
        result = self.read("", [self.record("2", subject="Clienta",
            subject_quote={"observation_id": "obs_body", "quote": "Clienta"})], observations=[item])
        self.assertEqual(result.read_ledger.value["validation_status"], "rejected_all")

    def test_identity_and_time_mismatch_reject_only_the_affected_atom(self):
        for failure in ("identity", "time"):
            with self.subTest(failure=failure):
                def mutate(data):
                    if failure == "identity":
                        data["atoms"][1]["assertion"]["target"] = "OrgB"
                    else:
                        data["atoms"][1]["times"] = [{"role": "due", "raw": "tomorrow",
                            "normalized": None, "precision": None, "property": "交期",
                            "evidence": data["atoms"][1]["evidence"]}]
                result = self.read("Clienta confirmed", [self.record("Clienta confirmed"),
                    self.record("Clienta confirmed", subject="Clienta", subject_quote={
                        "observation_id": "obs_body", "quote": "Clienta confirmed"})], mutate=mutate)
                self.assertEqual(result.read_ledger.value["validation_status"], "partial")
                self.assertEqual(len(result.candidate_atoms), 1)

    def test_secondary_identity_surface_rejects_atom_but_binding_structure_stays_fatal(self):
        for failure in ("surface", "duplicate", "primary"):
            with self.subTest(failure=failure):
                def mutate(data):
                    atom = data["atoms"][1]
                    data["identities"].append({"local_id": "i_parent", "display_label": "OrgB",
                        "type_surface": None, "value_surface": "OrgB", "evidence": atom["evidence"]})
                    refs = atom["identity_refs"]
                    refs.append({"scope_role": "parent", "identity_id": "i_parent"})
                    if failure == "duplicate":
                        refs.append(dict(refs[-1]))
                    elif failure == "primary":
                        refs.append({"scope_role": "primary", "identity_id": "i_parent"})
                    if failure != "surface":
                        atom["evidence"] = [{**atom["evidence"][0], "quote": "absent"}]
                records = [self.record("Clienta confirmed"), self.record("Clienta confirmed",
                    subject="Clienta", subject_quote={"observation_id": "obs_body", "quote": "Clienta confirmed"})]
                if failure == "surface":
                    result = self.read("Clienta confirmed", records, mutate=mutate)
                    self.assertEqual(result.read_ledger.value["validation_status"], "partial")
                    self.assertEqual(result.read_ledger.value["rejected_reasons"], {"identity_surface_mismatch": 1})
                    self.assertEqual(len(result.candidate_atoms), 1)
                else:
                    with self.assertRaises(ContractValidationError):
                        self.read("Clienta confirmed", records, mutate=mutate)
                    self.assertEqual(self.stores["candidate_atom_store"].list(), [])

    def test_global_schema_inventory_and_unknown_failures_are_not_salvaged(self):
        for mutate in (lambda d: d.update(read_observation_ids=[]),
                       lambda d: d["atoms"][0].update(extra="untrusted"),
                       lambda d: d["atoms"][0]["evidence"][0].update(observation_id="outside")):
            with self.subTest(mutate=mutate):
                with self.assertRaises(ContractValidationError):
                    self.read("Clienta", [self.record("Clienta")], mutate=mutate)
                self.assertEqual(list(self.stores["candidate_atom_store"].list()), [])

    def test_bad_quote_does_not_hide_schema_or_source_errors_on_that_atom(self):
        for mutate in (lambda d: d["atoms"][1].update(confidence="high"),
                       lambda d: d["atoms"][1].update(times=[{"extra": True}]),
                       lambda d: d["atoms"][1]["evidence"].append({
                           "observation_id": "outside", "field_path": ["text"],
                           "quote": "Clienta", "occurrence_index": None})):
            with self.subTest(mutate=mutate), self.assertRaises(ContractValidationError):
                self.read("Clienta", [self.record("Clienta"), self.record("missing")], mutate=mutate)
            self.assertEqual(list(self.stores["candidate_atom_store"].list()), [])

    def test_persistence_failure_with_a_valid_subset_still_fails_the_unit(self):
        with mock.patch.object(CandidateAtomStore, "create", side_effect=OSError("synthetic failure")):
            with self.assertRaises(ContractValidationError):
                self.read("Clienta", [self.record("Clienta"), self.record("missing")])
        ledger = list(self.stores["semantic_metadata_store"].list())[0]
        self.assertEqual(ledger.value["annotation_status"], "failed")
        self.assertEqual(ledger.value["failure_phase"], "persistence")

    def test_bad_quote_cannot_hide_identity_cap_atom_focus_or_dependent_relation_focus(self):
        for kind in ("identity_cap", "atom_focus", "relation_focus"):
            with self.subTest(kind=kind):
                records = [self.record("Clienta"), self.record("missing", subject="Clienta",
                    subject_quote={"observation_id": "obs_body", "quote": "Clienta"})]
                relations = [{"source_record": 0, "target_record": 1, "relation_type": "updates",
                    "evidence": [{"observation_id": "obs_body", "quote": "missing"}], "confidence": 0.9}]
                def mutate(data):
                    if kind == "identity_cap":
                        data["identities"][0]["evidence"] *= 129
                    else:
                        data["atoms"][0]["evidence"][0]["observation_id"] = "obs_focus"
                        if kind == "relation_focus":
                            data["atoms"][1]["evidence"][0]["observation_id"] = "obs_focus"
                with self.assertRaises(ContractValidationError):
                    self.read("", records, relations=relations, mutate=mutate,
                        observations=[_observation("obs_body", "Clienta"), _observation("obs_focus", "Clienta")],
                        focus_ids=None if kind == "identity_cap" else ["obs_focus"])
                self.assertEqual(list(self.stores["candidate_atom_store"].list()), [])


if __name__ == "__main__":
    unittest.main()
