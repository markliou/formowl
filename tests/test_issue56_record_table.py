import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from formowl_gateway import issue56_record_table as records, issue56_sealed_source_loader as loader
from formowl_mail.human_uat_orchestrator import compact_evidence_for_model
import test_issue56_uat_handler_composition as fixtures


class RecordTableTests(unittest.TestCase):
    def setUp(self):
        # A synthetic configured mount enables fixture capability labels. The
        # test suite never reads an operator's derived vocabulary.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.alias_path = Path(directory.name) / "fictional-aliases.json"
        self.alias_path.write_text(json.dumps({"properties": {}}))
        configured = patch.dict(os.environ, {"FORMOWL_RECORD_ALIASES_PATH": str(self.alias_path)})
        configured.start()
        self.addCleanup(configured.stop)

    def test_standard_ontology_labels_share_whitespace_and_unicode_normalization(self):
        fields = {"Part Number": "part_number", "Item Number": "part_number", "PO Qty": "quantity",
            "Quantity": "quantity", "Order Qty": "quantity", "Delivery Date": "delivery_date",
            "PO Number": "po_number", "PO No.": "po_number", "Manufacturer": "manufacturer",
            "Country of Origin": "origin_country", "Origin": "origin_country", "製造\n產地": "origin_country",
            "Supplier": "supplier", "Vendor": "supplier", "Ｐａｒｔ\tＮｕｍｂｅｒ": "part_number"}
        for label, prop in fields.items():
            with self.subTest(field=label):
                plan = records.plan_for({"filters": [{"field": label, "value": "sample"}],
                                         "projection_fields": [label]}, {}, [])
                self.assertEqual(plan["filters"][0]["property"], prop)
                self.assertEqual(plan["return"], [prop])
        resolve = records._field_resolver({"properties": {"supplier": ["Case\nSensitive Alias"]}})
        self.assertEqual(resolve("ＣＡＳＥ sensitive\talias"), "supplier")
        with self.assertRaises(records.RecordFieldValidationError):
            records._field_resolver({"properties": {"supplier": ["A B"], "manufacturer": ["a\nb"]}})("a\tb")

    def test_validation_guidance_has_three_main_aliases_per_property(self):
        guidance = records.RecordFieldValidationError({}).guidance
        encoded = guidance.split(": ", 1)[1].split("; use column:", 1)[0]
        aliases = json.loads(encoded)
        self.assertTrue(all(len(labels) <= 3 for labels in aliases.values()))
        self.assertEqual(aliases["part_number"], ["Part Number", "Item Number", "Part No."])
        self.assertEqual(aliases["quantity"], ["Quantity", "Qty", "Order Qty"])

    def test_raw_namespace_resolves_server_catalog_instead_of_prompt_listing(self):
        from formowl_records import store
        query = {"filters": [{"field": "column:料號", "value": "AX-703"}],
                 "projection_fields": ["column:PO qty"]}
        plan = records.plan_for(query, {"raw_columns": [], "raw_column_listing_truncated": True}, [])
        def resolve(labels, scopes, **kwargs):
            self.assertEqual(labels, {"料號", "PO qty"})
            self.assertEqual(scopes, ["blue"])
            self.assertEqual(kwargs["source_revision_sha256"], "bound pin")
            self.assertIs(kwargs["_admit"], admit)
            return {"料號": ["料\n號", "料號"], "PO qty": ["PO Qty", "PO\nQty"]}
        admit = object()
        with patch.object(store, "resolve_raw_columns", side_effect=resolve):
            resolved = records._resolve_raw_plan(plan, ["blue"], "bound pin", object(), admit=admit)
        self.assertEqual(resolved["filters"][0]["property"], "column:料號")
        self.assertEqual(resolved["return"], ["column:PO qty"])
        self.assertEqual(resolved["column_variants"]["column:PO qty"], ["PO Qty", "PO\nQty"])

    def test_aliases_and_literal_column_namespace(self):
        cap = {"properties":{"origin_country":["COO","產地"], "part_number":["料號"]}, "raw_columns":["Packing Label"]}
        query = {"filters":[{"field":"coo","value":"CN"}], "projection_fields":["料號","Packing Label","column:COO"]}
        plan = records.plan_for(query, cap, ["part_number","Packing Label"])
        self.assertEqual(plan["filters"], [{"property":"origin_country","op":"eq","values":["CN"]}])
        self.assertEqual(plan["return"], ["part_number","column:Packing Label","column:COO"])

    def test_explicit_unknown_and_ambiguous_fields_return_safe_guidance(self):
        caps = {"properties": {"part_number": ["shared label"], "po_number": ["shared label"]}}
        for field in ("unknown private label", "shared label"):
            for projection in (True, False):
                query = {"filters": [{"field": "part_number" if projection else field, "value": "AX-703"}],
                         "projection_fields": [field if projection else "quantity"]}
                with self.subTest(field=field, projection=projection), self.assertRaises(records.RecordFieldValidationError) as raised:
                    records.plan_for(query, caps, ["a high level description"])
                self.assertNotIn(field, str(raised.exception) if field.startswith("unknown") else "")
                self.assertIn("origin_country", raised.exception.guidance)
                self.assertLess(len(raised.exception.guidance.encode()), 6000)
        query = {"filters": [{"field": "part_number", "value": "AX-703"}],
                 "projection_fields": ["quantity"]}
        plan = records.plan_for(query, caps, ["a high level description", "po_number"])
        self.assertEqual(plan["filters"][0]["values"], ["AX-703"])
        self.assertEqual(plan["return"], ["quantity"])

    def test_full_mapped_alias_vocabulary_is_server_side(self):
        from formowl_records.store import PROPERTY_TYPES
        # Fictional labels exercise vocabulary beyond the public prompt cap.
        from string import ascii_lowercase
        fictional = {prop: [f"Fictional {prop} label {letter}" for letter in ascii_lowercase[:12]]
                     for prop in PROPERTY_TYPES}
        self.alias_path.write_text(json.dumps({"properties": fictional}))
        aliases = records._mapped_aliases()
        caps = {"properties": {prop: labels[:records._MAJOR_ALIAS_LIMIT] for prop, labels in aliases.items()}}
        self.assertEqual(set(aliases), set(PROPERTY_TYPES))
        self.assertTrue(all(len(labels) <= 8 for labels in caps["properties"].values()))
        folded = {}
        for prop, labels in aliases.items():
            for label in labels:
                folded.setdefault(records._fold(label), set()).add(prop)
        # Exercise a mapped alias beyond the prompt catalog, independent of
        # particular live questions or source values.
        prop, label = next((prop, label) for prop, labels in aliases.items() for label in labels[8:]
                           if len(folded[records._fold(label)]) == 1 and not label.startswith("column:"))
        query = {"filters": [{"field": "part_number", "value": "AX-703"}], "projection_fields": [label]}
        self.assertEqual(records.plan_for(query, caps, [])["return"], [prop])

    def test_private_alias_path_unset_missing_and_invalid_use_generic_only(self):
        capabilities = {"properties": {"supplier": ["Fictional Vendor Label"]}}
        for configured in ("", str(self.alias_path.parent / "missing.json")):
            with self.subTest(configured=bool(configured)), patch.dict(os.environ, {"FORMOWL_RECORD_ALIASES_PATH": configured}):
                self.assertEqual(records._mapped_aliases(), {})
                self.assertEqual(records._property_aliases(capabilities), records._ontology_aliases())
                self.assertIsNone(records._field_resolver(capabilities)("Fictional Vendor Label", strict=False))
                self.assertEqual(records._field_resolver(capabilities)("Vendor"), "supplier")
        for payload in ("{", "[]", '{"properties": []}'):
            self.alias_path.write_text(payload)
            self.assertEqual(records._property_aliases(capabilities), records._ontology_aliases())

    def test_private_and_capability_aliases_filter_values_without_blocking_raw_columns(self):
        rejected = ["123", "20420317", "2042-03-17", "1/2", "1月", "2日", "AX-703", "PO 204", "ＡＸ－７０３", "１２３", "½"]
        self.alias_path.write_text(json.dumps({"properties": {"supplier": ["Fictional Source Vendor", *rejected]}}))
        caps = {"properties": {"supplier": ["Fictional Scoped Vendor", *rejected]}, "raw_columns": ["AX-703"]}
        aliases = records._property_aliases(caps)["supplier"]
        self.assertIn("Fictional Source Vendor", aliases)
        self.assertIn("Fictional Scoped Vendor", aliases)
        self.assertFalse(set(rejected) & set(aliases))
        resolve = records._field_resolver(caps)
        self.assertEqual(resolve("Fictional Source Vendor"), "supplier")
        self.assertEqual(resolve("AX-703"), "column:AX-703")
        self.assertEqual(resolve("column:PO 204"), "column:PO 204")
        for label in rejected:
            if records._fold(label) != records._fold("AX-703"):
                self.assertIsNone(resolve(label, strict=False))

    def test_automatic_plan_keeps_all_known_terms_and_falls_back_to_all_properties(self):
        from formowl_records import store
        predicates = [{"property": "part_number", "op": "eq", "values": ["ax-703"]},
                      {"property": "po_number", "op": "eq", "values": ["po-204"]}]
        caps = {"properties": {"delivery_date": ["arrival"]}}
        with patch.object(store, "known_entity_filters", return_value=(predicates, False)) as resolve:
            plan, reason = records._automatic_plan(("AX-703", "PO-204"), caps, ["arrival"], ["blue"], "pin", object())
            self.assertIsNone(reason)
            self.assertEqual(plan["filters"], predicates)
            self.assertEqual(plan["return"], ["delivery_date"])
            self.assertEqual(resolve.call_args.args[0], ("AX-703", "PO-204"))
            plan, _ = records._automatic_plan(("AX-703",), caps, ["information about it"], ["blue"], "pin", object())
            self.assertEqual(plan["return"], list(store.PROPERTY_TYPES))
        for result, reason in ((([], False), "no_known_entity"), (([], True), "ambiguous_entity")):
            with patch.object(store, "known_entity_filters", return_value=result):
                self.assertEqual(records._automatic_plan(("AX-703",), caps, [], ["blue"], "pin", object()), (None, reason))

    def test_automatic_plan_accepts_explicit_capability_labels_without_private_mount(self):
        from formowl_records import store
        caps = {"properties": {"po_number": ["Order Code", "Shared Code", "PO 204"],
                               "part_number": ["Shared Code"]}}
        with patch.dict(os.environ, {"FORMOWL_RECORD_ALIASES_PATH": ""}), patch.object(
                store, "known_entity_filters", return_value=([], False)) as lookup:
            records._automatic_plan(("Order Code\u3000803715", "Shared Code 803715", "PO 204 803715"),
                                    caps, [], ["blue"], "pin", object())
        self.assertEqual(lookup.call_args.kwargs["_term_identity_hints"],
                         {"order code 803715": "po_number"})

    def test_runtime_vocabulary_filters_revision_aliases_before_automatic_planning(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from unittest.mock import Mock
        import time
        from formowl_contract import sha256_json
        from formowl_records import store
        revision = SimpleNamespace(candidate_fact_pin=object(),
            authorized_source=SimpleNamespace(source_scope_ids=["blue"]),
            safe_binding={"source_revision_sha256": sha256_json("source")},
            candidate_fact_rows=SimpleNamespace(aliases=(("Fictional Order Label", "po_number"),)))
        fields = {"properties": {"part_number": ["Fictional Part Label"]}, "raw_columns": ["AX-703"]}
        caps = {"record_table_fields": fields, "source_families": ["mail"]}
        contract = {"source_family_scope": ["mail"], "requested_fields": []}
        db = Mock()
        db.execute.return_value.fetchall.return_value = [("AX-703",)]
        invalid_path = self.alias_path.parent / "invalid.json"
        invalid_path.write_text("{")
        for configured in ("", str(self.alias_path.parent / "missing.json"), str(invalid_path), str(self.alias_path)):
            enabled = configured == str(self.alias_path)
            with self.subTest(configured=configured), patch.dict(os.environ, {
                    "FORMOWL_RECORD_ALIASES_PATH": configured}), patch.object(
                    records, "_SECRET", Mock(is_file=Mock(return_value=True))), patch.object(
                    records, "_connection", return_value=nullcontext(db)), patch.object(
                    store, "known_entity_filters", return_value=([], False)) as lookup:
                catalog = records.catalog(revision)
                self.assertEqual(catalog["raw_columns"], ["AX-703"])
                if not enabled:
                    self.assertEqual(catalog["properties"], {
                        prop: labels[:records._MAJOR_ALIAS_LIMIT]
                        for prop, labels in records._ontology_aliases().items()})
                budget = {"deadline": time.monotonic() + 10, "reads": 0}
                self.assertEqual(records.query_records(revision, None, contract, caps, None, budget, 100,
                    required_terms=("Fictional Order Label 803715", "Fictional Part Label 803715")), ([], None))
                self.assertEqual(lookup.call_args.kwargs["_term_identity_hints"], {
                    "fictional order label 803715": "po_number", "fictional part label 803715": "part_number"
                } if enabled else {})
        self.assertEqual(fields["properties"], {"part_number": ["Fictional Part Label"]})

    def test_query_entry_automatically_plans_and_retains_fixed_reasons(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from unittest.mock import Mock
        import time
        from formowl_records import store
        from formowl_contract import sha256_json
        revision = SimpleNamespace(authorized_source=SimpleNamespace(source_scope_ids=["blue"]),
            safe_binding={"source_revision_sha256": sha256_json("source")},
            candidate_fact_rows=SimpleNamespace(aliases=(), read_selected=Mock(return_value={})))
        caps = {"record_table_fields": {"properties": {}}, "source_families": ["mail", "attachment_table"]}
        contract = {"source_family_scope": ["mail", "attachment_table"], "requested_fields": ["origin_country"]}
        predicates = [{"property": "part_number", "op": "eq", "values": ["ax-703"]}]
        page = {"rows": [], "result_groups": [], "total": 0, "without_projection": 0, "quantity_only": 0}
        budget = {"deadline": time.monotonic()+10, "reads": 0}
        with patch.object(records, "_connection", return_value=nullcontext(Mock())), \
                patch.object(store, "known_entity_filters", return_value=(predicates, False)), \
                patch.object(store, "execute", return_value=page) as execute:
            rows, counts = records.query_records(revision, None, contract, caps, None, budget, 100,
                                                required_terms=("AX-703",))
        self.assertEqual((rows, counts["total"], budget["record_lookup_reason"]), ([], 0, "no_matches"))
        self.assertTrue(budget["record_lookup_queried"])
        self.assertEqual(budget["record_identifier_lookup"], "no_matches")
        self.assertIsNone(execute.call_args.kwargs["_native_source_families"])
        self.assertIsNone(execute.call_args.kwargs["_admit"])
        self.assertTrue(execute.call_args.kwargs["_require_unresolved_summary"])
        self.assertEqual(execute.call_args.kwargs["_summary_source_families"], contract["source_family_scope"])
        self.assertEqual(execute.call_args.args[0]["filters"], predicates)
        self.assertEqual(execute.call_args.args[0]["return"], ["origin_country"])
        self.assertEqual(execute.call_args.kwargs["source_revision_sha256"], revision.safe_binding["source_revision_sha256"])
        self.assertEqual(records.query_records(revision, None, contract, caps, None, budget, 100), ([], None))
        self.assertEqual(budget["record_lookup_reason"], "not_requested")
        self.assertFalse(budget["record_lookup_queried"])
        self.assertNotIn("record_identifier_lookup", budget)
        with patch.object(records, "_connection", side_effect=TimeoutError), self.assertLogs(records._LOG, level="WARNING"):
            self.assertEqual(records.query_records(revision, None, contract, caps, None, budget, 100,
                                                  required_terms=("AX-703",)), ([], None))
        self.assertEqual(budget["record_lookup_reason"], "lookup_timeout")
        self.assertFalse(budget["record_lookup_queried"])

    def test_no_match_outcome_requires_one_grounded_canonical_identifier_equality(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from unittest.mock import Mock
        import time
        from formowl_records import store
        revision = SimpleNamespace(authorized_source=SimpleNamespace(source_scope_ids=["blue"]),
            safe_binding={"source_revision_sha256": "sha256:" + "1" * 64},
            candidate_fact_rows=SimpleNamespace(aliases=(), read_selected=Mock(return_value={})))
        caps = {"record_table_fields": {"properties": {}}, "source_families": ["mail", "attachment_table"]}
        contract = {"source_family_scope": ["mail", "attachment_table"], "requested_fields": []}
        page = {"rows": [], "result_groups": [], "total": 0, "without_projection": 0, "quantity_only": 0}
        identity = {"field": "Part Number", "value": "AX-703"}
        cases = [([identity], ("ＡＸ-703",), True),
                 ([{"field": "MPN", "value": "AX-703"}], ("AX-703",), True),
                 ([{"field": "PO Number", "value": "AX-703"}], ("AX-703",), True),
                 ([identity], ("AX-704",), False), ([identity], None, False),
                 ([{**identity, "op": "contains"}], ("AX-703",), False),
                 ([identity, {"field": "origin_country", "value": "CA"}], ("AX-703",), False),
                 ([identity, {"field": "po_number", "value": "PO-204"}], ("AX-703", "PO-204"), False),
                 ([{"field": "supplier", "value": "AX-703"}], ("AX-703",), False)]
        for filters, terms, eligible in cases:
            with self.subTest(filters=filters, grounded=terms is not None):
                budget = {"deadline": time.monotonic()+10, "reads": 0}
                with patch.object(records, "_connection", return_value=nullcontext(Mock())), \
                        patch.object(store, "execute", return_value=page):
                    _, counts = records.query_records(revision,
                        {"filters": filters, "projection_fields": ["delivery_date"]},
                        contract, caps, None, budget, 100, required_terms=terms)
                self.assertEqual(counts["total"], 0)
                self.assertEqual(budget.get("record_identifier_lookup") == "no_matches", eligible)
        budget = {"deadline": time.monotonic()+10, "reads": 0}
        with patch.object(records, "_connection", return_value=nullcontext(Mock())), \
                patch.object(store, "execute", return_value={**page, "total": 1}):
            _, counts = records.query_records(revision,
                {"filters": [identity], "projection_fields": ["delivery_date"]},
                contract, caps, None, budget, 100, required_terms=("AX-703",))
        self.assertEqual(counts["total"], 1)
        self.assertNotIn("record_identifier_lookup", budget)

    def test_identifier_no_matches_survives_normal_handler_compaction_and_keeps_fallback(self):
        from contextlib import nullcontext
        from unittest.mock import Mock
        from formowl_records import store
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp))
            cap = {"properties": {"part_number": ["Asset"], "quantity": ["Ticket"]}}
            with patch.object(records, "catalog", return_value=cap):
                handler = loader._build_source_start_semantic_handler(bound, mail_tool=False)
            page = {"rows": [], "result_groups": [], "total": 0, "without_projection": 0, "quantity_only": 0}
            for explicit in (True, False):
                with self.subTest(explicit=explicit):
                    args = fixture._arguments(families=("mail", "attachment_table"), terms=("ZX-999",))
                    if explicit:
                        args["table_query"] = {"filters": [{"field": "Asset", "value": "ZX-999"}],
                                               "projection_fields": ["Ticket"]}
                    predicates = [{"property": "part_number", "op": "eq", "values": ["ZX-999"]}]
                    with patch.object(records, "_connection", return_value=nullcontext(Mock())), \
                            patch.object(store, "known_entity_filters", return_value=(predicates, False)), \
                            patch.object(store, "execute", return_value=page):
                        result = handler(args)
                    wire = compact_evidence_for_model(result)
                    self.assertEqual(wire["citations"], [])
                    self.assertEqual(wire["evidence"], [])
                    self.assertEqual(wire["coverage"]["record_identifier_lookup"], "no_matches")
                    self.assertFalse(wire["coverage"]["absence_claim"])
                    self.assertIn("這不代表它一定不存在", wire["coverage"]["disclosure"])
                    self.assertNotIn("ZX-999", wire["coverage"]["disclosure"])
            args = fixture._arguments(families=("mail", "attachment_table"))
            predicates = [{"property": "part_number", "op": "eq", "values": ["ZX-742"]}]
            with patch.object(records, "_connection", return_value=nullcontext(Mock())), \
                    patch.object(store, "known_entity_filters", return_value=(predicates, False)), \
                    patch.object(store, "execute", return_value=page):
                native = handler(args)
                self.assertTrue(native["citations"])
                self.assertNotIn("record_identifier_lookup", native.get("coverage", {}))
                args["table_query"] = {"filters": [{"field": "Asset", "value": "ZX-742"}],
                                       "projection_fields": ["Ticket"]}
                for status in ("permission_denied", "error", "failed"):
                    with self.subTest(fallback_status=status), patch.object(loader, "_execute_source_start_table",
                            return_value={"status": status, "citations": [], "evidence": []}):
                        denied = handler(args)
                    self.assertNotIn("record_identifier_lookup", denied.get("coverage", {}))
                args["requester_user_id"] = "unavailable-actor"
                denied = handler(args)
                self.assertEqual(denied["status"], "permission_denied")
                self.assertNotIn("record_identifier_lookup", denied.get("coverage", {}))

    def test_partial_date_contains_revalidates_against_the_full_normalized_source_date(self):
        fact = {"value": "2032/3/9", "raw_property": "Due", "permission_scope": {"scope_id": "blue"},
                "evidence_spans": [{"observation_hash": "h"}]}
        record = {"record_id": "r", "kind": "passage", "export_row_ids": ["r"], "permission_scope": "blue",
                  "values": [{"export_row_id": "r", "property_id": "delivery_date", "column_name_raw": "Due",
                              "raw_value": "2032/3/9", "norm_status": "ok", "norm_value": "2032-03-09",
                              "citation_hash": "h"}], "entities": [], "projection_hits": 1, "projection_date": "2032-03-09"}
        plan = {"filters": [{"property": "delivery_date", "op": "contains", "values": ["2032-03"]}],
                "return": ["delivery_date"]}
        result = records._candidate(record, None, plan, {}, {"r": {"fields": {"delivery_date": [fact]}}}, {})
        self.assertEqual(result["fields"]["delivery_date"][0]["value"], "2032/3/9")
        self.assertEqual(result["fields"]["delivery_date"][0]["_record_normalized"], "2032-03-09")
        plan["filters"][0]["values"] = ["2032-04"]
        self.assertIsNone(records._candidate(record, None, plan, {}, {"r": {"fields": {"delivery_date": [fact]}}}, {}))

    def test_explicit_order_contract_resolves_authorized_fields_and_defaults_desc(self):
        from formowl_gateway.remote import _STRUCTURED_TABLE_QUERY_INPUT_SCHEMA, _validate_structured_table_query_argument
        from formowl_mail.human_uat_orchestrator import _validate_table_query
        from formowl_contract import ContractValidationError

        base = {"filters": [{"field": "PO Number", "value": "REF-704"}], "projection_fields": ["Quantity"]}
        self.assertNotIn("order_by", _STRUCTURED_TABLE_QUERY_INPUT_SCHEMA["required"])
        self.assertEqual(_STRUCTURED_TABLE_QUERY_INPUT_SCHEMA["properties"]["order_by"]["required"], ["field"])
        for field, expected in [("source_date", "source_date"), ("Delivery Date", "delivery_date"),
                                ("Fictional score", "column:Fictional score")]:
            query = {**base, "order_by": {"field": field}}
            _validate_structured_table_query_argument(query)
            _validate_table_query(query)
            plan = records.plan_for(query, {"raw_columns": ["Fictional score"]}, [])
            self.assertEqual(plan["order_by"], {"field": expected, "direction": "desc"})
            if expected.startswith("column:"):
                self.assertEqual(records._raw_plan_columns(plan), {"Fictional score"})
        self.assertEqual(records.plan_for(base, {}, ["latest"])["order_by"], "projection_coverage")
        for invalid in (None, {}, {"field": " "}, {"field": "x" * 121}, {"field": "source_date", "direction": "later"},
                        {"field": "source_date", "offset": 2}):
            for validate in (_validate_table_query, _validate_structured_table_query_argument):
                with self.subTest(invalid=invalid, validator=validate.__name__), self.assertRaises(ContractValidationError):
                    validate({**base, "order_by": invalid})
        with self.assertRaises(records.RecordFieldValidationError):
            records.plan_for({**base, "order_by": {"field": "unknown fixture"}}, {}, [])

    def test_explicit_order_and_group_dates_survive_citation_bound_presentation(self):
        import time
        from copy import deepcopy
        from formowl_contract import sha256_json
        from formowl_mail.human_uat_orchestrator import _candidate_fact_table_refs

        rows, selected, groups = [], {}, []
        for i, (value, stamp) in enumerate([("2", "2032-03-08T08:03:42Z"), ("7", None)]):
            rid = f"r{i}"
            digest = sha256_json(rid)
            span = {"observation_hash": digest, "observation_id": rid, "native_locator": {"page": i + 1},
                    "source_extractor_run_id": "run", "quote": value, "start": 0, "end": 1}
            field = {"value": value, "raw_property": "Qty", "evidence_spans": [span]}
            row = {"row_id": rid, "item_or_row": rid, "fields": {"quantity": [field]}, "_projection_rank": (i, "")}
            rows.append(row)
            selected[digest] = [{"span": span, "row": row, "field": field, "property": "quantity"}]
            groups.append({"cells": [{value: {("Qty", None)}}], "count": 1, "detail_span": span,
                           "representative": rid, "earliest_source_date": stamp, "latest_source_date": stamp})

        counts = {"columns": ["quantity"], "total": 2, "without_projection": 0, "quantity_only": 2,
                  "groups": groups, "order_by": {"field": "source_date", "direction": "desc"},
                  "null_source_date_count": 1, "export_revision": sha256_json("serving")}
        def render(current):
            return loader._candidate_fact_table(rows, selected, sha256_json("pin"), deadline=time.monotonic()+10,
                                                record_total=current)

        item = render(counts)
        refs = set(selected)
        self.assertEqual(_candidate_fact_table_refs(item, refs), refs)
        model = compact_evidence_for_model({"status": "partial", "coverage": {"status": "incomplete"},
                                           "evidence": [item], "citations": sorted(refs)})
        table = json.loads(model["evidence"][0]["snippet"].split("\n", 1)[1])
        self.assertEqual([row["item"] for row in table["rows"]], ["r0", "r1"])
        rs = table["result_set"]
        self.assertEqual(rs["order_by"], counts["order_by"])
        self.assertEqual(rs["null_source_date_count"], 1)
        self.assertEqual([g["latest_source_date"] for g in rs["groups"]], ["2032-03-08T08:03:42Z", None])
        self.assertEqual([g["earliest_source_date"] for g in rs["groups"]], ["2032-03-08T08:03:42Z", None])
        for invalid in ("not a timestamp", "2032-02-31", None, "2031-01-10T12:00:00Z"):
            changed = deepcopy(counts)
            changed["groups"][0]["latest_source_date"] = invalid
            self.assertIsNone(_candidate_fact_table_refs(render(changed), refs))

    def test_operator_contract_and_native_rejection(self):
        from formowl_contract import ContractValidationError
        from formowl_gateway.remote import _validate_structured_table_query_argument
        from formowl_mail.human_uat_orchestrator import _validate_table_query
        caps={"properties":{"delivery_date":["Due"], "part_number":["Item"]}}
        query={"filters":[{"field":"Due","op":"gte","value":"2031-04-01"},
                          {"field":"Due","op":"lte","value":"2031-04-30"}],
               "projection_fields":["Due"]}
        for validate in (_validate_table_query, _validate_structured_table_query_argument):
            validate(query)
            with self.assertRaises(ContractValidationError):
                validate({**query,"filters":[{"field":"Due","op":"between","value":"2031-04"}]})
        plan = records.plan_for(query,caps,[])
        self.assertEqual([f["op"] for f in plan["filters"]],["gte","lte"])
        contains = {**query, "filters": [{"field": "Item", "op": "contains", "value": "x-7"}]}
        self.assertEqual(records.plan_for(contains, caps, [])["filters"][0],
                         {"property": "part_number", "op": "contains", "values": ["x-7"]})
        with self.assertRaisesRegex(ContractValidationError,"date or quantity"):
            records.plan_for({**query,"filters":[{"field":"Item","op":"gte","value":"22"}]},caps,[])
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp))
            names = {fact["raw_property"] for row in bound.candidate_fact_rows
                     for facts in row["fields"].values() for fact in facts if isinstance(fact.get("raw_property"), str)}
            self.assertEqual(set(bound.candidate_fact_rows.raw_columns), names)
            args = fixture._arguments(families=("mail","attachment_table"))
            args["table_query"] = query
            with patch.object(records,"catalog",return_value={}):
                handler=loader._build_source_start_semantic_handler(bound,mail_tool=False)
                with self.assertRaisesRegex(ContractValidationError,"only equality"):
                    handler(args)
            with patch.object(records,"catalog",return_value=caps),patch.object(records,"query_records",
                    return_value=([],dict(total=0,without_projection=0,quantity_only=0,unresolved_value_count=2))):
                raw=loader._build_source_start_semantic_handler(bound,mail_tool=False)(args)
            coverage=compact_evidence_for_model(raw)["coverage"]
            self.assertEqual(coverage["unresolved_value_count"],2)
            self.assertIn("2 筆值無法解析未納入比較",coverage["disclosure"])

    def test_database_unavailable_uses_existing_native_result(self):
        import psycopg
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp))
            args = fixture._arguments(families=("mail","attachment_table"))
            args["table_query"] = {"filters":[{"field":"part_number","value":"ZX-742"}],"projection_fields":["delivery_date"]}
            baseline = loader._build_source_start_semantic_handler(bound,mail_tool=False)(args)
            with patch.object(records,"catalog",return_value={"properties":{}}), patch.object(records,"_connection",
                    side_effect=psycopg.OperationalError("offline")), self.assertLogs(records._LOG,level="WARNING"):
                actual = loader._build_source_start_semantic_handler(bound,mail_tool=False)(args)
            self.assertEqual(actual["status"],baseline["status"])
            self.assertEqual(actual["citations"],baseline["citations"])

    def test_timed_out_equality_lookup_can_use_cited_source_evidence_within_original_budget(self):
        import time
        import psycopg
        from formowl_records import store
        from contextlib import nullcontext
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            revision, _ = fixture._native(Path(tmp), cells=True)
            args = fixture._arguments(families=("mail", "attachment_table"))
            args["request_contract"]["requested_fields"] = ["expected date for the identified part"]
            args["table_query"] = {"filters": [{"field": "Part Number", "value": "ZX-742"}],
                                   "projection_fields": ["Delivery Date"]}
            deadlines = []
            record_query = records.query_records
            native_query = loader._execute_source_start_table
            def record(*params, **kwargs):
                deadlines.append(params[5]["deadline"])
                return record_query(*params, **kwargs)
            def cancel(*params, **kwargs):
                time.sleep(max(0, kwargs["_deadline"] - time.monotonic()))
                raise psycopg.errors.QueryCanceled()
            def native(*params, **kwargs):
                deadlines.append(kwargs["source_budget"]["deadline"])
                return native_query(*params, **kwargs)
            with patch.object(records, "catalog", return_value={"properties": {}}):
                handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
            with patch.object(records, "query_records", side_effect=record), patch.object(
                    records, "_connection", return_value=nullcontext(Mock())), patch.object(
                    store, "execute", side_effect=cancel), patch.object(loader, "_execute_source_start_table",
                    side_effect=native), self.assertLogs(records._LOG, level="WARNING"):
                started = time.monotonic()
                result = handler(args)
            self.assertEqual(len(deadlines), 2)
            self.assertLess(deadlines[0], deadlines[1])
            self.assertLessEqual(deadlines[1] - started, 2.0)
            self.assertTrue(result["citations"])
            self.assertFalse(result["deterministic_exact"])
            self.assertFalse(result["coverage"]["absence_claim"])
            self.assertIn("逾時", result["coverage"]["disclosure"])
            self.assertTrue(compact_evidence_for_model(result)["citations"])

    def test_timeout_keeps_typed_filters_without_a_matching_required_identifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            revision, _ = fixture._native(Path(tmp))
            args = fixture._arguments(families=("mail", "attachment_table"))
            args["request_contract"]["requested_fields"] = ["expected date for the identified part"]
            args["table_query"] = {"filters": [{"field": "Part Number", "value": "ZX-999"}],
                                   "projection_fields": ["Delivery Date"]}
            with patch.object(records, "catalog", return_value={"properties": {}}), patch.object(
                    records, "_connection", side_effect=TimeoutError), self.assertLogs(records._LOG, level="WARNING"):
                result = loader._build_source_start_semantic_handler(revision, mail_tool=False)(args)
            self.assertEqual(result["status"], "clarification_required")
            self.assertFalse(result["citations"])

    def test_verified_records_keep_total_and_links_after_compaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp))
            args = fixture._arguments(families=("mail","attachment_table"))
            args["table_query"] = {"filters":[{"field":"Asset","value":"ZX-742"}],"projection_fields":["Ticket"]}
            rows = list(bound.candidate_fact_rows)
            for r in rows:
                f = next(iter(r["fields"].values()))[0]
                # Subject proof carries a surface and quotes, without an annotated value.
                proof = {k: v for k, v in f.items() if k != "value"}
                r["fields"]["_link_proof"] = [proof]
                r["_projection_rank"] = (1, "")
                r["_record_parts"] = [{"value": f["value"], "via": "quote_mention", "spans": f["evidence_spans"]}]
                r["item_or_row"] += "x" * 25000
            with patch.object(records,"catalog",return_value={"properties":{}}), patch.object(records,"query_records",
                    return_value=(rows, {"total":193, "without_projection":5, "quantity_only":0})):
                raw = loader._build_source_start_semantic_handler(bound,mail_tool=False)(args)
            compact=compact_evidence_for_model(raw)
            item=compact["evidence"][0]
            table=json.loads(item["snippet"].split("\n",1)[1])
            self.assertEqual((item["source_type"],table["total"],table["shown"]),("candidate_fact_table",193,1))
            self.assertIn("共 193 筆，顯示 1 列", table["disclosure"])
            self.assertEqual(table["without_requested_values"], 5)
            self.assertEqual(table["rows"][0]["parts"][0]["via"], "quote_mention")
            self.assertNotIn("_link_proof", table["columns"])
            self.assertEqual(set(item["source_context"]["required_citation_hashes"]),set(compact["citations"]))


    def test_requested_coverage_orders_before_fit_and_identical_values_merge(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp))
            args = fixture._arguments(families=("mail","attachment_table"))
            args["table_query"] = {"filters":[{"field":"Asset","value":"ZX-742"}],"projection_fields":["Ticket","Expected"]}
            recent, older = list(bound.candidate_fact_rows)
            recent["_projection_rank"] = (2,"2032-04-19")
            older["_projection_rank"] = (1,"2032-04-20")
            duplicate = deepcopy(recent)
            duplicate["row_id"] += "_copy"
            counter = {"total":7, "without_projection":4, "quantity_only":0}
            with patch.object(records,"catalog",return_value={"properties":{}}), patch.object(records,"query_records",
                    return_value=([older, duplicate, recent], counter)):
                raw = loader._build_source_start_semantic_handler(bound,mail_tool=False)(args)
            compact = compact_evidence_for_model(raw)
            table = json.loads(compact["evidence"][0]["snippet"].split("\n",1)[1])
            self.assertEqual([r["record_count"] for r in table["rows"]], [2,1])
            self.assertEqual((table["represented_records"],table["without_requested_values"]), (3,4))


    def test_same_projected_value_keeps_distinct_source_headers_after_compaction(self):
        from copy import deepcopy
        from formowl_mail.human_uat_orchestrator import _candidate_fact_table_refs
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp), cells=True)
            args = fixture._arguments(families=("mail", "attachment_table"))
            args["table_query"] = {"filters": [{"field": "Asset", "value": "ZX-742"}],
                                   "projection_fields": ["Expected"]}
            row = next(iter(bound.candidate_fact_rows))
            fact = next(iter(row["fields"].values()))[0]
            row["fields"] = {"delivery_date": [dict(fact, raw_property="CRD", _record_normalized="2031-04-02"),
                                               dict(fact, raw_property="ETD")]}
            row["_projection_rank"] = (1, "")
            row["_native_record"] = True
            counts = {"total": 1, "without_projection": 0, "quantity_only": 0}
            with patch.object(records, "catalog", return_value={"properties": {}}), patch.object(
                    records, "query_records", return_value=([row], counts)):
                raw = loader._build_source_start_semantic_handler(bound, mail_tool=False)(args)
            item = compact_evidence_for_model(raw)["evidence"][0]
            prefix, encoded = item["snippet"].split("\n", 1)
            table = json.loads(encoded)
            self.assertEqual(table["mapping_status"], "pending_review")
            cells = table["rows"][0]["values"][0]
            self.assertEqual([table["names"][c["n"]] for c in cells], ["CRD", "ETD"])
            self.assertEqual(cells[0]["normalized"], "2031-04-02")
            self.assertNotIn("normalized", cells[1])
            self.assertTrue(all("column_name_raw" not in c for c in cells))
            tampered = deepcopy(table)
            tampered["rows"][0]["values"][0][0]["n"] = "n999"
            self.assertIsNone(_candidate_fact_table_refs(
                {**raw["evidence"][0], "snippet": prefix + "\n" + json.dumps(tampered)}, set(raw["citations"])))

    def test_link_only_citation_uses_same_closure_and_rejects_invalid_offsets(self):
        from formowl_mail.human_uat_orchestrator import _candidate_fact_table_refs
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp), cells=True)
            args = fixture._arguments(families=("mail","attachment_table"))
            args["table_query"] = {"filters":[{"field":"Asset","value":"ZX-742"}],"projection_fields":["Ticket"]}
            row = next(iter(bound.candidate_fact_rows))
            prop = next(iter(row["fields"]))
            proof = row["fields"].pop(prop)[0]
            row["fields"]["_link_proof"] = [proof]
            row["_record_parts"] = [{"value":proof["value"], "via":"quote_mention", "spans":proof["evidence_spans"]}]
            row["_projection_rank"] = (1,"")
            counts = {"total":1, "without_projection":0, "quantity_only":0}
            with patch.object(records,"catalog",return_value={"properties":{}}), patch.object(records,"query_records",
                    return_value=([row],counts)):
                raw = loader._build_source_start_semantic_handler(bound,mail_tool=False)(args)
            item = compact_evidence_for_model(raw)["evidence"][0]
            # The validator consumes the server-side proof before model projection.
            self.assertNotIn("record_citation_proof", item["source_context"])
            item = raw["evidence"][0]
            refs = set(raw["citations"])
            self.assertEqual(_candidate_fact_table_refs(item,refs), refs)
            label, encoded = item["snippet"].split("\n",1)
            self.assertEqual(_candidate_fact_table_refs({**item,"snippet":"來源記錄（含原生表格，語意對應待審）\n"+encoded},refs),refs)
            table = json.loads(encoded)
            table["rows"][0]["parts"][0]["quotes"][0][0] += 100
            self.assertIsNone(_candidate_fact_table_refs({**item,"snippet":label+"\n"+json.dumps(table)},refs))


    def test_record_citation_round_trip_and_browser_response(self):
        from copy import deepcopy
        from formowl_mail.human_uat_http import _normalize_query_response
        from formowl_mail.human_uat_orchestrator import (
            _candidate_fact_table_refs, _TurnCitationPresentation, _validate_evidence_bound_decision,
        )
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp), inline_html=(
                "<table><tr><th>Asset</th><th>Ticket</th><th>Expected</th></tr>"
                "<tr><td>ZX-742</td><td>R-007</td><td>2031-04-02</td></tr>"
                "<tr><td>ZX-742</td><td>R-008</td><td>2031-04-09</td></tr></table>"))
            args = fixture._arguments()
            args["table_query"] = {"filters": [{"field": "Asset", "value": "ZX-742"}],
                                   "projection_fields": ["Ticket"]}
            rows = list(bound.candidate_fact_rows)
            for row in rows:
                row["_projection_rank"] = (1, "")
            counts = {"total": len(rows), "without_projection": 0, "quantity_only": 0}
            with patch.object(records, "catalog", return_value={"properties": {}}), patch.object(
                    records, "query_records", return_value=(rows, counts)):
                raw = loader._build_source_start_semantic_handler(bound, mail_tool=False)(args)
            original = raw["evidence"][0]
            proof = original["source_context"]["record_citation_proof"]["citations"]
            compact = compact_evidence_for_model(raw)
            presentation = _TurnCitationPresentation(set())
            model = presentation.present(compact)
            encoded = json.dumps(model, ensure_ascii=False)
            for key in ("record_citation_proof", "source_observation_id", "source_extractor_run_id", "native_locator"):
                self.assertNotIn(key, encoded)
            table = json.loads(model["evidence"][0]["snippet"].split("\n", 1)[1])
            citations = table["citations"]
            self.assertTrue(all(set(c) == {"ref", "citation_hash", "source_label"} for c in citations))
            self.assertEqual({c["source_label"] for c in citations}, {"2026-09-01"})
            handles = [c["citation_hash"] for c in citations]
            canonical = presentation.decode(handles)
            decision = {"citation_ids": canonical, "response_kind": "answer", "coverage_status": "incomplete"}
            _validate_evidence_bound_decision(decision, evidence_results=[raw])
            self.assertEqual(_normalize_query_response({"citations": canonical}),
                             _normalize_query_response({"citations": [p["citation_hash"] for p in proof]}))
            for key, value in (("citation_hash", "sha256:" + "0" * 64), ("spans", [[10, 20]])):
                bad = deepcopy(original)
                bad["source_context"]["record_citation_proof"]["citations"][0][key] = value
                self.assertIsNone(_candidate_fact_table_refs(bad, set(raw["citations"])))
                rejected = compact_evidence_for_model({**raw, "evidence": [bad]})
                self.assertFalse(rejected.get("citations"))
            bad = deepcopy(original)
            label, encoded = bad["snippet"].split("\n", 1)
            table = json.loads(encoded)
            table["citations"][0]["citation_hash"] = "sha256:" + "0" * 64
            bad["snippet"] = label + "\n" + json.dumps(table)
            self.assertIsNone(_candidate_fact_table_refs(bad, set(raw["citations"])))

    def test_scoped_result_combinations_merge_headers_and_keep_same_record_values(self):
        groups = {}
        columns = ["delivery_date", "quantity"]
        bounds = {"delivery_date": [("gte", "2031-04-01"), ("lte", "2031-04-30")]}
        def add(name, qty):
            def value(raw, header):
                return {"raw_value": raw, "column_name_raw": header, "evidence_spans": [{"quote": str(raw)}]}
            date = [value("2031-04-02", name), value("2031-05-01", name)]
            quantities = [value(raw, "Qty") for raw in qty]
            record = {"kind": "table_row", "source_observation_id": "row", "source_hash": "digest",
                      "permission_scope": "fixture", "values": date + quantities,
                      "returned": {"delivery_date": date, "quantity": quantities}}
            records._collect_result_group(groups, record, columns, bounds)
        add("CRD", ["4", "2"])
        add("Due", ["2", "4"])
        add("CRD", ["4"])
        self.assertEqual([g["count"] for g in groups.values()], [2, 1])
        self.assertEqual(next(iter(groups.values()))["cells"][0], {"2031-04-02": {("CRD", None), ("Due", None)}})
        self.assertEqual(set(next(iter(groups.values()))["cells"][1]), {"2", "4"})

    def test_result_groups_expand_verified_links_and_count_the_unlinked_bucket(self):
        from copy import deepcopy
        def value(prop, raw, name, quote):
            span = {"observation_hash":"h1","quote":quote}
            return {"raw_value":raw,"property_id":prop,"column_name_raw":name,
                    "evidence_spans":[span],"context_spans":[]}
        country = value("origin_country","CN","Origin","CN TX-881 PO-204")
        manufacturer = value("manufacturer_part_number","MF-567","MPN","MF-567")
        def edge(kind, raw, via, prop):
            return {"entity_type":kind,"raw_key":raw,"norm_key":raw.lower(),"via":via,
                    "via_property":prop,"citation_hash":"h1"}
        record = {"kind":"pdf_line","source_observation_id":"o","source_hash":"h1","permission_scope":"blue",
                  "values":[country,manufacturer],"entities":[edge("part","MF-567","value","manufacturer_part_number"),
                         edge("part","TX-881","quote_mention","quote_mention"),
                         edge("purchase_order","PO-204","quote_mention","quote_mention")],
                  "returned":{"part_number":[],"origin_country":[country],"po_number":[]}}
        columns = ["part_number","origin_country","po_number"]
        groups = {}
        records._collect_result_group(groups,record,columns,{},{"origin_country"})
        self.assertEqual(len(groups), 2)
        entries = {next(iter(g["cells"][0])):g for g in groups.values()}
        self.assertEqual(entries["MF-567"]["cells"][0]["MF-567"],{("MPN","value")})
        self.assertEqual(entries["TX-881"]["cells"][0]["TX-881"],{("Origin","quote_mention")})
        self.assertEqual(entries["TX-881"]["cells"][2]["PO-204"],{("Origin","quote_mention")})
        # A direct PO remains the projected PO even when the record also mentions another.
        own = value("po_number","PO-111","Order","PO-111")
        direct = {**record, "values":[*record["values"],own],"returned":{**record["returned"],"po_number":[own]}}
        direct["entities"] = [*record["entities"], edge("purchase_order","PO-111","value","po_number")]
        other = {}
        records._collect_result_group(other,direct,columns,{},{"origin_country"})
        self.assertTrue(all(set(g["cells"][2]) == {"PO-111"} for g in other.values()))
        absent = deepcopy(record)
        absent["entities"] = []
        records._collect_result_group(groups,absent,columns,{},{"origin_country"})
        absent["returned"]["origin_country"][0]["raw_value"] = "China"
        records._collect_result_group(groups,absent,columns,{},{"origin_country"})
        unlinked = next(g for g in groups.values() if None in g["cells"][0])
        self.assertEqual(unlinked["cells"][0][None], {(None,"unlinked_part")})
        self.assertEqual(set(unlinked["cells"][1]), {"CN","China"})
        self.assertEqual(unlinked["count"], 2)
        bad = deepcopy(record)
        bad["entities"][1]["citation_hash"] = "unrelated"
        with self.assertRaisesRegex(ValueError,"missing source"):
            records._collect_result_group({},bad,columns,{},{"origin_country"})

    def test_result_set_first_budget_and_citation_cap(self):
        import time
        from copy import deepcopy
        from formowl_contract import sha256_json
        from formowl_mail.human_uat_orchestrator import _candidate_fact_table_refs, _candidate_table_for_model
        def build(width):
            groups = []
            for i in range(130):
                raw = str(i) + "V" * width
                g = {"count": 1, "cells": [{raw: {("Original", None)}}]}
                if i < 128:
                    g["span"] = {"observation_hash": sha256_json(i), "observation_id": f"o{i}",
                                 "native_locator": {"page": i+1}, "source_extractor_run_id": "run",
                                 "start": 0, "end": 1}
                else:
                    g["citation_limit"] = True
                groups.append(g)
            counts = {"total": 130, "without_projection": 0, "quantity_only": 0,
                      "columns": ["quantity"], "groups": groups}
            item = loader._candidate_fact_table([], {}, sha256_json("pin"), deadline=time.monotonic()+10,
                                               record_total=counts)
            refs = set(item["source_context"]["required_citation_hashes"])
            self.assertEqual(_candidate_fact_table_refs(item, refs), refs)
            projected = _candidate_table_for_model(item)
            self.assertLessEqual(len(json.dumps(projected, ensure_ascii=False).encode()), 48*1024)
            table = json.loads(projected["snippet"].split("\n", 1)[1])
            bad = deepcopy(item)
            label, raw = bad["snippet"].split("\n", 1)
            tampered = json.loads(raw)
            tampered["result_set"]["groups"][0]["count"] += 1
            bad["snippet"] = label + "\n" + json.dumps(tampered, ensure_ascii=False, separators=(",",":"))
            self.assertIsNone(_candidate_fact_table_refs(bad, refs))
            return table
        all_groups = build(0)
        rs = all_groups["result_set"]
        self.assertEqual((rs["total_groups"], rs["shown_groups"], len(all_groups["citations"])), (130,130,128))
        self.assertTrue(all(g["ref"] for g in rs["groups"][:128]))
        self.assertEqual([g["ref"] for g in rs["groups"][128:]], [None, None])
        self.assertIn("2 組 ref=null", all_groups["disclosure"])
        truncated = build(700)
        shown = truncated["result_set"]["shown_groups"]
        self.assertTrue(0 < shown < 130)
        self.assertIn(f"結果集共 130 組，顯示 {shown} 組", truncated["disclosure"])
        self.assertIn("註明未列出的組數", truncated["disclosure"])
        self.assertEqual(truncated["shown"], 0)

    def test_full_detail_fit_keeps_r6_table_and_duplicate_fit_emits_group(self):
        import time
        from formowl_contract import sha256_json
        from formowl_mail.human_uat_orchestrator import _candidate_fact_table_refs
        span = {"observation_hash": sha256_json("obs"), "observation_id":"o",
                "native_locator":{"page":1}, "source_extractor_run_id":"run",
                "quote":"10","start":0,"end":2}
        fact = {"value":"10","raw_property":"Qty","evidence_spans":[span]}
        row = {"row_id":"r1","item_or_row":"r1","fields":{"quantity":[fact]},"_projection_rank":(1,"")}
        selected = {span["observation_hash"]:[{"span":span,"row":row,"field":fact,"property":"quantity"}]}
        base = {"total":1,"without_projection":0,"quantity_only":1}
        group = {"cells":[{"10":{("Qty",None)}}],"count":1,"span":span}
        def render(counts):
            return loader._candidate_fact_table([row], selected,sha256_json("pin"),
                                                deadline=time.monotonic()+10,record_total=counts)
        item = render({**base,"columns":["quantity"],"groups":[group]})
        self.assertEqual(item, render(base))
        self.assertNotIn("result_set", item["snippet"])
        item = render({**base,"total":2,"columns":["quantity"],"groups":[{**group,"count":2}]})
        self.assertEqual(_candidate_fact_table_refs(item, set(selected)), set(selected))
        table = json.loads(item["snippet"].split("\n",1)[1])
        self.assertEqual((table["result_set"]["groups"][0]["count"],table["shown"]),(2,1))

    def test_export_verified_groups_survive_without_borrowed_refs(self):
        import time
        from copy import deepcopy
        from formowl_contract import sha256_json
        from formowl_mail.human_uat_orchestrator import (
            _candidate_fact_table_refs, _TurnCitationPresentation, _validate_evidence_bound_decision,
        )
        digest = sha256_json("observation")
        span = {"observation_hash": digest, "observation_id": "o", "native_locator": {"page": 1},
                "source_extractor_run_id": "run", "quote": "10", "start": 0, "end": 2}
        field = {"value": "10", "raw_property": "Qty", "evidence_spans": [span]}
        row = {"row_id": "r1", "item_or_row": "1", "fields": {"quantity": [field]},
               "_projection_rank": (1, "")}
        selected = {digest: [{"span": span, "row": row, "field": field, "property": "quantity"}]}
        groups = [{"cells": [{value: {("Qty", None, value)}}], "count": 1,
                   "detail_span": span, "representative": rid} for value, rid in (("10", "r1"), ("20", "r2"))]
        counts = {"total": 2, "without_projection": 0, "quantity_only": 2, "columns": ["quantity"],
                  "export_revision": sha256_json("serving revision"), "groups": groups}
        for rows in ([], [row]):
            with self.subTest(rows=len(rows)):
                item = loader._candidate_fact_table(rows, selected, sha256_json("fact pin"),
                    deadline=time.monotonic()+10, record_total=counts)
                refs = {digest} if rows else set()
                self.assertEqual(_candidate_fact_table_refs(item, refs), refs)
                raw = {"status": "partial", "coverage": {"status": "incomplete"},
                       "evidence": [item], "citations": sorted(refs)}
                presentation = _TurnCitationPresentation(set())
                model = presentation.present(compact_evidence_for_model(raw))
                table = json.loads(model["evidence"][0]["snippet"].split("\n", 1)[1])
                shown = table["result_set"]["groups"]
                self.assertEqual(len(shown), 2)
                self.assertEqual([g["values"][0][0]["normalized"] for g in shown], ["10", "20"])
                self.assertEqual(len(table["rows"]), len(rows))
                self.assertIsNone(shown[1]["ref"])
                self.assertEqual(shown[1]["basis"], "export_verified")
                if rows:
                    self.assertEqual(shown[0]["ref"], table["citations"][0]["ref"])
                    self.assertNotIn("basis", shown[0])
                    decision = {"answer": "10 and 20", "coverage_status": "incomplete", "response_kind": "answer",
                                "citation_ids": presentation.decode([table["citations"][0]["citation_hash"]])}
                    _validate_evidence_bound_decision(decision, evidence_results=[raw])
                else:
                    self.assertTrue(all(g["ref"] is None and g["basis"] == "export_verified" for g in shown))
                    with self.assertRaisesRegex(RuntimeError, "omitted citations"):
                        _validate_evidence_bound_decision({"answer": "10 and 20", "coverage_status": "incomplete",
                            "response_kind": "answer", "citation_ids": []}, evidence_results=[raw])
                for change in ({"ref": "c99"}, {"basis": "live"}):
                    bad = deepcopy(item)
                    label, body = bad["snippet"].split("\n", 1)
                    decoded = json.loads(body)
                    decoded["result_set"]["groups"][1].update(change)
                    bad["snippet"] = label + "\n" + json.dumps(decoded)
                    self.assertIsNone(_candidate_fact_table_refs(bad, refs))

    def test_reserve_verified_details_before_truncating_export_groups(self):
        import time
        from formowl_contract import sha256_json
        from formowl_mail.human_uat_orchestrator import _candidate_fact_table_refs, _candidate_table_for_model
        rows, selected, groups = [], {}, []
        for i in range(160):
            rid = f"r{i}"
            value = rid + "v" * 300
            group = {"cells": [{value: {("Qty", None)}}], "count": 1, "representative": rid}
            groups.append(group)
            if i >= 5:
                continue
            digest = sha256_json(rid)
            span = {"observation_hash": digest, "observation_id": rid, "native_locator": {"page": i+1},
                    "source_extractor_run_id": "run", "quote": value, "start": 0, "end": len(value)}
            group["detail_span"] = span
            field = {"value": value, "raw_property": "Qty", "evidence_spans": [span]}
            row = {"row_id": rid, "item_or_row": rid, "_projection_rank": (1, rid),
                   "fields": {"quantity": [field]}}
            rows.append(row)
            selected[digest] = [{"span": span, "row": row, "field": field, "property": "quantity"}]
        for available in (2, 5):
            with self.subTest(available=available):
                item = loader._candidate_fact_table(rows[:available], selected, sha256_json("fact pin"),
                    deadline=time.monotonic()+10, record_total={"export_revision": sha256_json("serving"),
                        "total": len(groups), "without_projection": 0, "quantity_only": len(groups),
                        "columns": ["quantity"], "groups": groups})
                model = _candidate_table_for_model(item)
                self.assertLessEqual(len(json.dumps(model, ensure_ascii=False).encode()), 48*1024)
                table = json.loads(model["snippet"].split("\n", 1)[1])
                refs = {c["citation_hash"] for c in table["citations"]}
                self.assertEqual(_candidate_fact_table_refs(item, refs), refs)
                self.assertEqual(len(table["rows"]), min(available, 3))
                self.assertTrue(3 < table["result_set"]["shown_groups"] < len(groups))
                self.assertEqual(sum(g["ref"] is not None for g in table["result_set"]["groups"]), len(refs))

        # Distinct source records with identical projections still supply the
        # minimum of three details, each with citations to its own source.
        for row in rows:
            row["fields"]["quantity"][0]["value"] = "same"
        group = {"cells": [{"same": {("Qty", None)}}], "count": len(rows),
                 "representative": rows[0]["row_id"], "detail_span": groups[0]["detail_span"]}
        item = loader._candidate_fact_table(rows, selected, sha256_json("fact pin"),
            deadline=time.monotonic()+10, record_total={"export_revision": sha256_json("serving"),
                "total": len(rows), "without_projection": 0, "quantity_only": len(rows),
                "columns": ["quantity"], "groups": [group]})
        refs = set(item["source_context"]["required_citation_hashes"])
        self.assertEqual(_candidate_fact_table_refs(item, refs), refs)
        table = json.loads(item["snippet"].split("\n", 1)[1])
        self.assertEqual((table["shown"], table["represented_records"]), (3, 5))
        self.assertEqual(len({r["item"] for r in table["rows"]}), 3)
        self.assertEqual(table["result_set"]["shown_groups"], 1)

    def test_batched_sealed_rows_keep_digests_and_reject_path_replacement(self):
        import time
        from formowl_contract import ContractValidationError
        from formowl_mail import issue56_sealed_source as owner
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl"
            raw = [json.dumps({"row_id": key}).encode() + b"\n" for key in ("one","two","three")]
            path.write_bytes(b"".join(raw))
            refs = tuple((0,sum(len(x) for x in raw[:i]),len(x),owner._sha256_bytes(x)) for i,x in enumerate(raw))
            rows = owner._CandidateFactRows(((path,owner._candidate_fact_file_identity(path.stat()),()),),
                refs, {}, {"one":0,"two":1,"three":2})
            result = rows.read_selected(["three","one","three"], time.monotonic()+2)
            self.assertEqual(list(result), ["one","three"])
            self.assertEqual(result["three"]["row_id"], "three")
            with self.assertRaises(TimeoutError):
                rows.read_selected(["one"], time.monotonic()-1)
            bad = list(refs)
            bad[0] = (*refs[0][:-1],refs[1][-1])
            with self.assertRaises(ContractValidationError):
                fixtures.replace(rows,references=tuple(bad)).read_selected(["three","one"],time.monotonic()+2)
            original = owner._CandidateFactRows._read
            def replaced(self, index, deadline=None, **kwargs):
                result = original(self, index, deadline, **kwargs)
                new = path.with_suffix(".new")
                new.write_bytes(path.read_bytes())
                new.replace(path)
                return result
            with patch.object(owner._CandidateFactRows,"_read",replaced), self.assertRaises(ContractValidationError):
                rows.read_selected(["one"], time.monotonic()+2)

    def test_native_record_uses_verified_row_group_and_rejects_wrong_cell(self):
        import time
        from formowl_contract import ContractValidationError, sha256_json
        from test_issue56_uat_handler_composition import ProjectionIndependentSourceMcpTests
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, _, _ = ProjectionIndependentSourceMcpTests()._table_lookup(Path(directory))
            row = next(o for o in fixture.observations if o.observation_type=="table_row")
            cells = [o for o in fixture.observations if o.observation_type=="table_cell"
                     and loader._table_row_key(o)==loader._table_row_key(row)]
            def digest(item):
                return sha256_json(item.to_dict())
            record = {"kind":"table_row", "source_hash":digest(row), "source_observation_id":row.observation_id,
                      "permission_scope":row.permission_scope["scope_id"], "values":[{"evidence_spans":[
                          {"observation_id":cell.observation_id, "observation_hash":digest(cell)} for cell in cells]}]}
            budget = {"deadline":time.monotonic()+10,"max_reads":100,"reads":0,
                      "record_families":["mail","attachment_table"],"record_selector":None,
                      "exact_lookup":loader._IngestionExactCellLookup(revision)}
            verified = records._preferred_native_members(record, budget)
            self.assertEqual(set(verified), {digest(o) for o in [row,*cells]})
            self.assertGreater(budget["reads"],len(cells))
            record["values"][0]["evidence_spans"][0]["observation_hash"] = sha256_json("wrong")
            with self.assertRaises(ContractValidationError):
                records._preferred_native_members(record, budget)
