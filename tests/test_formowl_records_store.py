import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import psycopg
from formowl_contract import sha256_json
from formowl_records import store


def export_row(row_id, fields, *, scope="blue"):
    permission = {"scope_type": "project", "scope_id": scope, "visibility": "shared"}
    revision = sha256_json("revision")
    row = {"artifact_id": "formowl_candidate_fact_row_v1", "review_status": "pending_review",
           "semantic_correctness_verified": False, "row_id": row_id, "fields": {},
           "source_revision_fingerprint": revision, "permission_scope_fingerprint": sha256_json(permission),
           "outer_mail_date": {"status": "verified", "value": "2032-01-02T11:00:00Z", "evidence": []}}
    for prop, raw in fields.items():
        oid = "obs-" + row_id
        span = {"observation_id": oid, "observation_hash": sha256_json(oid), "quote": str(raw),
                "native_locator": {"page": 1, "block_index": 2}}
        row["fields"][prop] = [{"value": raw, "times": [], "evidence_spans": [span],
                                "raw_property": prop + " label", "source_revision_fingerprint": revision,
                                "permission_scope": permission, "permission_scope_fingerprint": sha256_json(permission),
                                "source_observation_ids": [oid], "observation_hashes": {oid: span["observation_hash"]}}]
    return row


def write_export(path, rows):
    mapping = {"properties": list(store.PROPERTY_TYPES)}
    content = b"".join(json.dumps({**r, "mapping_fingerprint": sha256_json(mapping)}).encode() + b"\n" for r in rows)
    (path / "mapping.snapshot.json").write_text(json.dumps(mapping))
    (path / "rows.jsonl").write_bytes(content)
    (path / "manifest.json").write_text(json.dumps({"artifact_id": "formowl_candidate_fact_export_v1",
        "review_status": "pending_review", "semantic_correctness_verified": False, "row_count": len(rows),
        "mapping_fingerprint": sha256_json(mapping), "source_revision": sha256_json("revision"),
        "rows_sha256": "sha256:" + hashlib.sha256(content).hexdigest()}))


@unittest.skipUnless(os.environ.get("FORMOWL_RECORDS_TEST_DSN"), "requires a disposable PostgreSQL database")
class RecordStoreTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(os.environ["FORMOWL_RECORDS_TEST_DSN"])
        self.addCleanup(self.conn.close)
        # Schema and test rows vanish on connection rollback, even on assertion failure.
        self.conn.execute("CREATE SCHEMA r2_fixture")
        self.conn.execute("SET LOCAL search_path TO r2_fixture")
        store.create_schema(connection=self.conn)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)

    def query(self, prop, op, values, scopes=("blue",), **options):
        return store.execute({"filters": [{"property": prop, "op": op, "values": values}], **options},
                             scopes, connection=self.conn)

    def _summary_revision(self, pin, families=None):
        families = families or {}
        def helper(oid):
            return ({"observation_hash": sha256_json(oid), "source_scope_id": "blue",
                     "retrieval_source_family": families.get(oid, "mail")},
                    SimpleNamespace(asset=SimpleNamespace()))
        return SimpleNamespace(safe_binding={"source_revision_sha256": pin},
            authorized_source=SimpleNamespace(source_scope_ids=["blue"]),
            source_records=SimpleNamespace(_helper=helper, observation_hash=lambda oid: sha256_json(oid)))

    def test_raw_name_resolution_uses_entire_pinned_admitted_catalog_and_rejects_collisions(self):
        rows = []
        specifications = [(f"filler-{i}", f"Filler {i}", "blue") for i in range(140)] + [
            ("part", "料\n號", "blue"), ("qty", "ＰＯ\tQty", "blue"),
            ("collision-a", "A B", "blue"), ("collision-b", "AB", "blue"),
            ("hidden", "Hidden Label", "red"), ("stale", "Stale Label", "blue"),
            ("unbound", "Unbound Label", "blue"), ("header", "Header Label", "blue"),
            ("admitted", "Field Name", "blue"), ("rejected", "ＦｉｅｌｄName", "blue")]
        for rid, label, scope in specifications:
            row = export_row(rid, {"supplier": "sample"}, scope=scope)
            row["fields"]["supplier"][0]["raw_property"] = label
            rows.append(row)
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s WHERE record_id='stale'", (sha256_json("stale"),))
        self.conn.execute("UPDATE record SET verified_at_export=false WHERE record_id='unbound'")
        self.conn.execute("UPDATE record SET row_role='header' WHERE record_id='header'")
        def resolve(labels, **options):
            return store.resolve_raw_columns(labels, ["blue"], source_revision_sha256=pin,
                connection=self.conn, **options)
        self.assertEqual(resolve(["料號", "po qty", "filler139"]),
                         {"料號": ["料\n號"], "po qty": ["ＰＯ\tQty"], "filler139": ["Filler 139"]})
        for label in ("hiddenlabel", "stalelabel", "unboundlabel", "headerlabel"):
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "^unavailable raw column$"):
                resolve([label])
        self.assertEqual(resolve(["A B", "AB"]), {"A B": ["A B", "AB"], "AB": ["A B", "AB"]})
        observed = []
        def admit(record):
            observed.append(record["record_id"])
            return record["record_id"] != "rejected"
        self.assertEqual(resolve(["fieldname"], _admit=admit), {"fieldname": ["Field Name"]})
        self.assertEqual(set(observed), {"admitted", "rejected"})
        self.assertEqual(store.field_name_key("ＰＯ\n\tＱＴＹ\u00a0"), store.field_name_key("po qty"))
        native = dict(observation_id="native-name", observation_hash=sha256_json("native-name"),
            table_index=0, row_index=1, permission_scope_id="blue", header_signature=["外部 Ｃｏｄｅ", None],
            cells=[dict(cell_index=0, column_name="外部 Ｃｏｄｅ", observation_hash=sha256_json("native-cell"), text="value"),
                   dict(cell_index=1, column_name=None, observation_hash=sha256_json("unnamed-cell"), text="value")])
        path = self.path / "native.jsonl"
        path.write_text(json.dumps(native)+"\n")
        store.load_native_rows(path, connection=self.conn)
        self.conn.execute("UPDATE record SET verified_at_export=true,source_revision_sha256=%s,export_binding='{}'::jsonb WHERE kind='table_row'", (pin,))
        self.assertEqual(resolve(["外部code"]), {"外部code": ["外部 Ｃｏｄｅ"]})
        self.assertEqual(resolve(["外部code"], _fact_columns=[]), {"外部code": ["外部 Ｃｏｄｅ"]})

    def test_raw_equivalent_spellings_filter_project_and_group_together_without_losing_values(self):
        rows = []
        for rid, label, values in (("a", "Batch Code", ["Alpha"]), ("b", "Batch\nCode", ["Beta"]),
                                   ("c", "Batch Code", ["Gamma", "Delta"])):
            row = export_row(rid, {"supplier": values[0]})
            fact = row["fields"]["supplier"][0]
            row["fields"]["supplier"] = [{**fact, "value": value, "raw_property": label} for value in values]
            rows.append(row)
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        names = ["Batch Code", "Batch\nCode"]
        resolved = store.resolve_raw_columns(["batchcode"], ["blue"], connection=self.conn,
            source_revision_sha256=pin, _fact_columns=names)
        self.assertEqual(set(resolved["batchcode"]), set(names))
        plan = {"filters": [{"property": "column:batchcode", "op": "contains", "values": ["a"]}],
                "return": ["column:batchcode"], "column_variants": {"column:batchcode": resolved["batchcode"]},
                "order_by": "projection_coverage"}
        result = store.execute(plan, ["blue"], connection=self.conn, source_revision_sha256=pin, _result_groups=True)
        self.assertEqual((result["total"], len(result["result_groups"])), (3, 3))
        cells = [v for row in result["rows"] for v in row["returned"]["column:batchcode"]]
        self.assertEqual({v["raw_value"] for v in cells}, {"Alpha", "Beta", "Gamma", "Delta"})
        self.assertEqual({v["column_name_raw"] for v in cells}, set(names))
        self.assertEqual({r["projection_hits"] for r in result["rows"]}, {1})
        # A single physical row cannot silently collapse conflicting headings.
        original = rows[0]["fields"]["supplier"][0]
        rows[0]["fields"]["supplier"].append({**original, "raw_property": "Batch\nCode", "value": "Other"})
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        with self.assertRaisesRegex(ValueError, "^unavailable raw column$"):
            store.execute(plan, ["blue"], connection=self.conn, source_revision_sha256=pin)

    def test_bound_fact_vocabulary_keeps_named_legacy_native_rows_via_equality_superset(self):
        native = []
        for rid, name, value, scope in (("legacy", "Legacy\nCode", "Chosen", "blue"),
                ("other", "Other Label", "Elsewhere", "blue"),
                ("hidden", "Legacy Code", "Chosen", "red")):
            native.append(dict(observation_id=rid, observation_hash=sha256_json(rid), table_index=0, row_index=1,
                permission_scope_id=scope, header_signature=None,
                cells=[dict(cell_index=0, column_name=name, observation_id=rid+"-cell",
                            observation_hash=sha256_json(rid+"-cell"), text=value)]))
        path = self.path / "native.jsonl"
        native.append(dict(observation_id="shadow", observation_hash=sha256_json("shadow"), table_index=0, row_index=1,
            permission_scope_id="red", header_signature=["OtherLabel"],
            cells=[dict(cell_index=0, column_name="OtherLabel", observation_hash=sha256_json("shadow-cell"), text="Elsewhere")]))
        path.write_text("".join(json.dumps(row)+"\n" for row in native))
        store.load_native_rows(path, connection=self.conn)
        pin = sha256_json("serving")
        self.conn.execute("UPDATE record SET verified_at_export=true,source_revision_sha256=%s,export_binding='{}'::jsonb", (pin,))
        self.assertEqual(self.conn.execute("SELECT header_signature_id FROM record WHERE record_id='native:legacy'").fetchone()[0], None)
        filters = [{"property": "column:legacycode", "op": "eq", "values": ["Chosen"]}]
        options = dict(source_revision_sha256=pin, connection=self.conn, _fact_columns=(), _query_filters=filters)
        resolved = store.resolve_raw_columns(["legacycode"], ["blue"], **options)
        self.assertEqual(resolved, {"legacycode": ["Legacy\nCode"]})
        plan = {"filters": filters, "return": ["column:legacycode"],
                "column_variants": {"column:legacycode": resolved["legacycode"]}, "order_by": "projection_coverage"}
        result = store.execute(plan, ["blue"], connection=self.conn, source_revision_sha256=pin, _result_groups=True)
        self.assertEqual((result["total"], len(result["result_groups"])), (1,1))
        self.assertEqual(result["rows"][0]["returned"]["column:legacycode"][0]["raw_value"], "Chosen")
        # Unknown projection existence is checked globally, even when it cannot
        # contribute a value to this equality-selected row.
        self.assertEqual(store.resolve_raw_columns(["OtherLabel"], ["blue"], **options), {"OtherLabel": ["Other Label"]})
        self.assertEqual(store.resolve_raw_columns(["legacycode"], ["blue"], **{**options,"_query_filters":()}),
                         {"legacycode": ["Legacy\nCode"]})

    def test_entity_and_country_queries_are_scoped_counted_and_pageable(self):
        rows = [export_row("a", {"part_number": " Br-41 ", "origin_country": "Canada"}),
                export_row("b", {"manufacturer_part_number": "BR-41", "delivery_date": "2032/3/9"}),
                export_row("c", {"part_number": "br-41"}, scope="red"),
                export_row("d", {"manufacturer_part_number": "other-1"}),
                export_row("e", {"part_number": "other-1"}, scope="red")]
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        plan = {"return": ["delivery_date"], "group_by": "part_number", "limit": 1}
        result = self.query("part_number", "eq", ["BR-41"], **plan)
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["truncated"])
        second = self.query("part_number", "eq", ["Br-41"], **plan, offset=1)
        self.assertFalse(second["truncated"])
        page = {r["record_id"]: r for r in [*result["rows"], *second["rows"]]}
        self.assertEqual(set(page), {"a", "b"})
        self.assertEqual(page["a"]["group_keys"], ["br-41"])
        self.assertEqual(page["b"]["group_keys"], ["br-41"])
        date = page["b"]["returned"]["delivery_date"][0]
        self.assertEqual((date["raw_value"], date["norm_value"]), ("2032/3/9", "2032-03-09"))
        self.assertEqual(date["native_locator"], {"page": 1, "block_index": 2})
        self.assertEqual(date["citation_hash"], sha256_json("obs-b"))
        self.assertEqual(page["a"]["sent_at"], "2032-01-02T11:00:00Z")
        self.assertEqual(self.query("part_number", "eq", ["other-1"])["total"], 0)
        self.assertEqual(self.query("origin_country", "in", ["CA", "FR"])["total"], 1)
        self.assertEqual(self.query("part_number", "contains", ["r-4"])["total"], 2)
        self.assertEqual(self.query("part_number", "contains", ["%"])["total"], 0)
        self.assertEqual(self.query("part_number", "eq", ["br-41"], scopes=[])["total"], 0)
        self.assertEqual(self.query("part_number", "eq", ["br-41"], offset=2)["total"], 2)
        with self.assertRaises(ValueError):
            self.query("part_number OR TRUE", "eq", ["BR-41"])

    def test_known_entity_resolution_is_exact_typed_scoped_and_revision_pinned(self):
        rows = [export_row("part", {"part_number": "AX-703"}),
                export_row("maker", {"manufacturer_part_number": "MF-602"}),
                export_row("order", {"po_number": "PO-204"}),
                export_row("hidden", {"part_number": "HIDE-403"}, scope="red"),
                export_row("cross-part", {"part_number": "CROSS-1"}),
                export_row("cross-order", {"po_number": "CROSS-1"}),
                export_row("no_receipt", {"part_number": "UNBOUND-1"}),
                export_row("wrong_revision", {"part_number": "STALE-1"})]
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        self.conn.execute("UPDATE record SET export_binding=NULL WHERE record_id='no_receipt'")
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s WHERE record_id='wrong_revision'", (sha256_json("old"),))
        def resolve(terms, scopes=("blue",)):
            return store.known_entity_filters(terms, scopes, source_revision_sha256=pin, connection=self.conn)
        filters, ambiguous = resolve(("AX-703", "MF-602", "PO-204", "unknown", "AX-703"))
        self.assertFalse(ambiguous)
        self.assertEqual(filters, [
            {"property": "part_number", "op": "eq", "values": ["ax-703"]},
            {"property": "manufacturer_part_number", "op": "eq", "values": ["mf-602"]},
            {"property": "po_number", "op": "eq", "values": ["po-204"]}])
        self.assertEqual(resolve(("CROSS-1",)), ([], True))
        self.assertEqual(resolve(("HIDE-403", "UNBOUND-1", "STALE-1", "AX-70")), ([], False))
        self.assertEqual(resolve(("AX-703",), ()), ([], False))
        self.assertEqual(resolve(("HIDE-403",), ("red",))[0][0]["values"], ["hide-403"])
        self.conn.execute("UPDATE record SET row_role='header_candidate' WHERE record_id='part'")
        self.assertEqual(resolve(("AX-703",)), ([], False))

    def test_known_entity_resolution_expands_generic_whitespace_tokens_without_guessing(self):
        rows = [export_row("part", {"part_number": "AX-703"}),
                export_row("maker", {"manufacturer_part_number": "MF-602"}),
                export_row("whole", {"part_number": "WHOLE COMPOSITE-408"}),
                export_row("short", {"part_number": "A12"}),
                export_row("numeric", {"po_number": "803715"}),
                export_row("hidden", {"po_number": "930517"}, scope="red"),
                export_row("stale", {"part_number": "STALE-4"}),
                export_row("unbound", {"part_number": "UNBOUND-4"}),
                export_row("header", {"part_number": "HEADER-4"}),
                export_row("cross-part", {"part_number": "CROSS-4"}),
                export_row("cross-order", {"po_number": "CROSS-4"})]
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s WHERE record_id='stale'", (sha256_json("old"),))
        self.conn.execute("UPDATE record SET export_binding=NULL WHERE record_id='unbound'")
        self.conn.execute("UPDATE record SET row_role='header' WHERE record_id='header'")
        before = self.conn.execute("SELECT count(*) FROM entity").fetchone()[0]
        def resolve(terms, **options):
            return store.known_entity_filters(terms, ["blue"], connection=self.conn,
                                              source_revision_sha256=pin, **options)
        # Prefixes have no semantic significance; all matching keys retain AND semantics.
        self.assertEqual(resolve(("reference\u3000ＡＸ－７０３\nMF-602 803715", "AX-703")), ([
            {"property": "part_number", "op": "eq", "values": ["ax-703"]},
            {"property": "manufacturer_part_number", "op": "eq", "values": ["mf-602"]},
            {"property": "po_number", "op": "eq", "values": ["803715"]}], False))
        self.assertEqual(resolve(("WHOLE COMPOSITE-408",))[0][0],
                         {"property": "part_number", "op": "eq", "values": ["whole composite-408"]})
        self.assertEqual(resolve(("reference A12", "reference AX-70", "reference words")), ([], False))
        self.assertEqual(resolve(("A12",))[0][0]["values"], ["a12"])  # Whole-term behavior is retained.
        self.assertEqual(resolve(("reference CROSS-4",)), ([], True))
        self.assertEqual(resolve(("reference CROSS-4",), _admit=lambda r:r["record_id"] == "cross-part"),
                         ([{"property": "part_number", "op": "eq", "values": ["cross-4"]}], False))
        self.assertEqual(resolve(("reference 930517 STALE-4 UNBOUND-4 HEADER-4",)), ([], False))
        self.assertEqual(resolve(("reference AX-703",), _admit=lambda r:False), ([], False))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM entity").fetchone()[0], before)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM entity WHERE norm_key='803715'").fetchone()[0], 0)

    def test_resolved_label_only_disambiguates_new_tokens_and_whole_matches_take_priority(self):
        from formowl_gateway.issue56_record_table import _automatic_plan
        write_export(self.path, [export_row("part", {"part_number": "803715"}),
            export_row("order", {"po_number": "803715"}),
            export_row("whole", {"part_number": "Grounded Code AX-703"}),
            export_row("subtoken", {"po_number": "AX-703"}),
            export_row("maker", {"manufacturer_part_number": "803715"})])
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        fields = {"properties": {"po_number": ["Order Code", "Shared Code"],
            "part_number": ["Part Code", "Shared Code"], "manufacturer_part_number": ["Maker Code"]}}
        def auto(terms, **options):
            return _automatic_plan(terms, fields, ["quantity"], ["blue"], pin, self.conn, **options)
        for label, prop in (("Order Code", "po_number"), ("Part Code", "part_number"),
                            ("Maker Code", "manufacturer_part_number")):
            plan, reason = auto((label + "\u3000803715",))
            self.assertIsNone(reason)
            self.assertEqual(plan["filters"], [{"property": prop, "op": "eq", "values": ["803715"]}])
        for terms in (("803715",), ("reference 803715",), ("Shared Code 803715",),
                      ("Order Code Part Code 803715",), ("Order Code 803715 Part Code",),
                      ("Order Code 803715", "Part Code 803715"),
                      ("Order Code 803715", "Maker Code 803715"), ("803715", "Order Code 803715")):
            with self.subTest(terms=terms):
                self.assertEqual(auto(terms), (None, "ambiguous_entity"))
        self.assertEqual(auto(("Order Code 803715",), admit=lambda r:r["record_id"] == "part"),
                         (None, "no_known_entity"))
        # A full exact field value wins over a differently typed embedded token.
        plan, reason = auto(("Grounded Code AX-703",))
        self.assertIsNone(reason)
        self.assertEqual(plan["filters"], [{"property": "part_number", "op": "eq", "values": ["grounded code ax-703"]}])
        # A prefixed copy does not duplicate an already matched whole key.
        self.assertEqual(auto(("AX-703", "Order Code AX-703"))[0]["filters"],
                         [{"property": "po_number", "op": "eq", "values": ["ax-703"]}])

    def test_numeric_typed_values_resolve_without_manufacturing_entity_edges(self):
        rows = [export_row("numeric-po", {"po_number": "803715"}),
                export_row("other-family", {"part_number": "803715"}),
                export_row("hidden", {"part_number": "803715"}, scope="red")]
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM entity WHERE norm_key='803715'").fetchone()[0], 0)
        def admit(record):
            return record["record_id"] == "numeric-po"
        known = store.known_entity_filters(("803715",), ["blue"], connection=self.conn,
                                          source_revision_sha256=pin, _admit=admit)
        self.assertEqual(known, ([{"property": "po_number", "op": "eq", "values": ["803715"]}], False))
        self.assertEqual(store.known_entity_filters(("803715",), ["blue"], connection=self.conn,
            source_revision_sha256=pin), ([], True))
        self.assertEqual(store.known_entity_filters(("803",), ["blue"], connection=self.conn,
            source_revision_sha256=pin), ([], False))
        result = store.execute({"filters": known[0]}, ["blue"], connection=self.conn,
                               source_revision_sha256=pin, _admit=admit)
        self.assertEqual([row["record_id"] for row in result["rows"]], ["numeric-po"])

    def test_restricted_fact_seeds_cannot_admit_quote_links_or_create_automatic_ambiguity(self):
        rows = [export_row("out-family-part", {"part_number": "AX-703"}),
                export_row("out-family-po", {"po_number": "AX-703"}),
                export_row("other-selector", {"manufacturer_part_number": "AX-703"}),
                export_row("quoted", {"quantity": "10"})]
        rows[-1]["fields"]["quantity"][0]["evidence_spans"][0]["quote"] = "AX-703 10"
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        # Both callbacks model the real same-scope source owner: family admission
        # accepts a manufacturer's seed, but the narrower selector rejects it.
        def family(record):
            return record["record_id"] in {"other-selector", "quoted"}
        def selector(record):
            return record["record_id"] == "quoted"
        common = {"connection": self.conn, "source_revision_sha256": pin, "_restricted": True}
        for prop, admit in (("part_number", family), ("manufacturer_part_number", selector)):
            result = store.execute({"filters": [{"property": prop, "op": "eq", "values": ["AX-703"]}],
                "return": ["quantity"], "order_by": "projection_coverage"}, ["blue"], _admit=admit, **common)
            self.assertEqual(result["total"], 0)
        known = store.known_entity_filters(("AX-703",), ["blue"], source_revision_sha256=pin,
                                           connection=self.conn, _admit=family)
        self.assertEqual(known, ([{"property": "manufacturer_part_number", "op": "eq", "values": ["ax-703"]}], False))
        self.assertEqual(store.known_entity_filters(("AX-703",), ["blue"], source_revision_sha256=pin,
            connection=self.conn, _admit=selector), ([], False))
        # Unrestricted queries still use the original typed link path.
        unrestricted = store.execute({"filters": [{"property": "part_number", "op": "eq", "values": ["AX-703"]}]},
                                     ["blue"], connection=self.conn, source_revision_sha256=pin)
        self.assertIn("quoted", {row["record_id"] for row in unrestricted["rows"]})

    def test_export_pinned_results_require_scope_revision_and_verified_binding(self):
        names = ("eligible", "other_revision", "unverified", "no_receipt", "hidden")
        rows = [export_row(name, {"delivery_date": "2032-03-01"}, scope="red" if name=="hidden" else "blue")
                for name in names]
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        revision = sha256_json("revision")
        from types import SimpleNamespace
        pin = sha256_json("serving")
        bound = SimpleNamespace(safe_binding={"source_revision_sha256":pin},
            authorized_source=SimpleNamespace(source_scope_ids=["blue"]),
            source_records=SimpleNamespace(observation_hash=lambda oid:
                sha256_json("changed") if oid=="obs-other_revision" else sha256_json(oid)))
        self.conn.execute("UPDATE record SET export_binding=NULL WHERE record_id='no_receipt'")
        self.conn.execute("UPDATE record SET verified_at_export=false WHERE record_id='unverified'")
        qualified = store.verify_fact_serving_spans(bound, connection=self.conn)
        self.assertEqual(qualified, {"verified":1, "observation_hash_mismatch":1,
            "outside_scope":1, "missing_export_binding":2})
        self.assertEqual(self.conn.execute("SELECT source_revision_sha256,fact_serving_revision_sha256 FROM record "
                                           "WHERE record_id='eligible'").fetchone(), (revision,pin))
        plan = {"filters":[{"property":"delivery_date","op":"gte","values":["2032-03-01"]}],
                "return":["delivery_date"], "order_by":"projection_coverage"}
        result = store.execute(plan, ["blue"], connection=self.conn, source_revision_sha256=pin, _result_groups=True)
        self.assertEqual([r["record_id"] for r in result["rows"]], ["eligible"])
        self.assertEqual(result["result_groups"][0][1:3], (1, "eligible"))
        self.assertEqual(result["total"], 1)
        self.assertNotIn("export_binding", result["rows"][0])

    def test_interval_compares_one_resolved_value_and_counts_unparsed_values_once(self):
        rows = [export_row(key, {"delivery_date": day, "quantity": qty}) for key, day, qty in (
            ("before","2032-02-29","2"), ("first","2032-03-01","10.25"),
            ("last","2032/3/31","100"), ("after","2032-04-01","101"),
            ("unknown","Q1","unknown"), ("split","2032-02-01","9"))]
        rows[-1]["fields"]["delivery_date"] += export_row("split", {"delivery_date":"2032-04-10"})["fields"]["delivery_date"]
        rows.append(export_row("hidden", {"delivery_date":"pending","quantity":"unknown"}, scope="red"))
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        def interval(prop, lo, hi):
            return store.execute({"filters":[{"property":prop,"op":"gte","values":[lo]},
                                             {"property":prop,"op":"lte","values":[hi]}]}, ["blue"],connection=self.conn)
        for result in (interval("delivery_date","2032-03-01","2032-03-31"), interval("quantity","10.25","100")):
            self.assertEqual({r["record_id"] for r in result["rows"]}, {"first","last"})
            self.assertEqual(result["unresolved_value_count"], 1)
        result = store.execute({"filters":[{"property":"delivery_date","op":"gte","values":["2032-03-01"]}]},
                               ["zulu","blue","blue"], connection=self.conn)
        self.assertEqual(result["unresolved_value_count"], 1)
        result = store.execute({"filters":[{"property":"delivery_date","op":"gte","values":["2032-03-01"]}]},
                               ["red","blue"], connection=self.conn)
        self.assertEqual(result["unresolved_value_count"], 2)
        self.assertEqual(interval("delivery_date","2033-01-01","2033-03-01")["total"],0)
        with self.assertRaisesRegex(ValueError, "date or quantity"):
            interval("supplier", "A","Z")
        with self.assertRaisesRegex(ValueError, "invalid record range bound"):
            interval("delivery_date", "Q1","2032-03-01")

    def test_iso_month_contains_compiles_to_equivalent_indexable_closed_bounds(self):
        for month, last in (("2032-02", "2032-02-29"), ("2031-02", "2031-02-28"), ("9999-12", "9999-12-31")):
            query, params = store._filter_ids({"property": "delivery_date", "op": "contains", "values": [month]})
            self.assertEqual(params, ["delivery_date", month+"-01", last])
            self.assertNotIn("strpos", query.as_string(self.conn))
            self.assertIn("v.value_type='date'", query.as_string(self.conn))
        for fragment in ("03", "2032-3", "2032-13", "0000-01"):
            query, params = store._filter_ids({"property": "delivery_date", "op": "contains", "values": [fragment]})
            self.assertIn("strpos", query.as_string(self.conn))
            self.assertEqual(params, ["delivery_date", fragment])

    def test_partial_normalized_date_contains_preserves_unresolved_scope_counts(self):
        rows = [export_row("match", {"delivery_date": "2032/3/9"}),
                export_row("outside", {"delivery_date": "2032-04-01"}),
                export_row("pending", {"delivery_date": "pending"}),
                export_row("hidden", {"delivery_date": "pending"}, scope="red")]
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        plan = {"filters": [{"property": "delivery_date", "op": "contains", "values": ["2032-03"]}],
                "return": ["delivery_date"], "order_by": "projection_coverage"}
        for reject_pending in (False, True):
            def admit(record):
                return not reject_pending or record["record_id"] != "pending"
            result = store.execute(plan, ["blue"], connection=self.conn, source_revision_sha256=pin,
                _admit=admit, _restricted=True, _native_source_families=["mail", "attachment_table"])
            self.assertEqual([row["record_id"] for row in result["rows"]], ["match"])
            self.assertEqual(result["unresolved_value_count"], int(not reject_pending))
            self.assertEqual(result["rows"][0]["returned"]["delivery_date"][0]["raw_value"], "2032/3/9")

    def test_sealed_native_family_receipts_apply_to_matches_seeds_and_unresolved_dates(self):
        self.assertEqual(store._native_family_scope(["mail", "attachment_table"]), (store.sql.SQL(""), False))
        pin = sha256_json("serving")
        rows = [export_row("fact", {"delivery_date": "pending"})]
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        native = []
        mapping = {}
        for key, prop, part, day, family in (
                ("inline", "part_number", "AX-703", "2032-03-05", "mail_inline_table"),
                ("attached", "manufacturer_part_number", "AX-703", "2032-03-05", "attachment_table"),
                ("inline-pending", "part_number", "AX-704", "pending", "mail_inline_table"),
                ("attached-pending", "part_number", "AX-705", "pending", "attachment_table")):
            names = [prop, "Due"]
            signature = sha256_json(names)
            mapping[signature] = [{"property_id": prop}, {"property_id": "delivery_date"}]
            native.append(dict(observation_id=key, observation_hash=sha256_json(key),
                table_index=0, row_index=len(native)+1, permission_scope_id="blue", header_signature=names,
                source_family=family, row_role="data_candidate", cells=[
                    dict(cell_index=i, column_name=name, observation_id=f"{key}-{i}",
                         observation_hash=sha256_json([key, i]), text=value)
                    for i, (name, value) in enumerate(zip(names, [part, day], strict=True))]))
        path = self.path / "native.jsonl"
        path.write_text("".join(json.dumps(row)+"\n" for row in native))
        store.load_native_rows(path, mapping, connection=self.conn)
        receipt = json.dumps({"exporter_sha256": store._NATIVE_FAMILY_EXPORTER,
                             "shard": "00", "shard_sha256": sha256_json("sealed shard")})
        self.conn.execute("UPDATE record SET verified_at_export=true,source_revision_sha256=%s,export_binding=%s::jsonb "
                          "WHERE kind='table_row'", (pin, receipt))
        with patch("formowl_mail.issue56_sealed_source._authorized_mail_selector_for_asset", return_value=None):
            store.rebuild_unresolved_value_summaries(self._summary_revision(pin, {"obs-fact": "attachment_table"}), connection=self.conn)
        admitted = []
        def admit(record):
            admitted.append(record["record_id"])
            return True
        options = {"connection": self.conn, "source_revision_sha256": pin, "_restricted": True,
                   "_admit": admit, "_native_source_families": ["attachment_table"],
                   "_summary_source_families": ["attachment_table"], "_require_unresolved_summary": True}
        # The only part_number direct seed is inline; its entity link must not
        # propagate into attachment rows after the inline family is rejected.
        result = store.execute({"filters": [{"property": "part_number", "op": "eq", "values": ["AX-703"]}],
            "return": ["delivery_date"], "order_by": "projection_coverage"}, ["blue"], **options)
        self.assertEqual(result["total"], 0)
        self.assertEqual(admitted, [])
        plan = {"filters": [{"property": "delivery_date", "op": "gte", "values": ["2032-03-01"]},
                            {"property": "delivery_date", "op": "lte", "values": ["2032-03-31"]}],
                "return": ["delivery_date"], "order_by": "projection_coverage"}
        result = store.execute(plan, ["blue"], **options)
        self.assertEqual([row["record_id"] for row in result["rows"]], ["native:attached"])
        self.assertEqual(result["unresolved_value_count"], 2)
        self.assertEqual(admitted, [])  # Unresolved fact source admission was sealed offline.
        # The ordinary SQL unresolved count must use the same qualified visible
        # set even without a runtime per-span admission callback.
        plain = store.execute(plan, ["blue"], **{**options, "_restricted": False, "_admit": None})
        self.assertEqual(plain["unresolved_value_count"], 2)
        admitted.clear()
        # A version that has not been audited gets the original source guard.
        self.conn.execute("UPDATE record SET export_binding=jsonb_set(export_binding,'{exporter_sha256}',%s::jsonb) "
                          "WHERE record_id='native:attached'", (json.dumps(sha256_json("other exporter")),))
        store.execute(plan, ["blue"], **options)
        self.assertIn("native:attached", admitted)
        admitted.clear()
        store.execute(plan, ["blue"], **{**options, "_native_source_families": None})
        self.assertIn("native:inline", admitted)
        self.assertIn("native:attached", admitted)
        self.assertNotIn("native:inline-pending", admitted)  # No unresolved disclosure scan.

    def test_grouped_unresolved_summaries_are_scoped_proven_and_never_scan_sources(self):
        rows = [export_row("mail-a", {"delivery_date": "pending"}),
                export_row("mail-b", {"delivery_date": "unknown"}),
                export_row("document", {"delivery_date": "tbd"}),
                export_row("hidden", {"delivery_date": "hidden"}, scope="red")]
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        revision = self._summary_revision(pin, {"obs-document": "document_text"})
        with patch("formowl_mail.issue56_sealed_source._authorized_mail_selector_for_asset", return_value="selector-blue"):
            store.verify_fact_serving_spans(revision, connection=self.conn)
            first = store.rebuild_unresolved_value_summaries(revision, connection=self.conn)
            second = store.rebuild_unresolved_value_summaries(revision, connection=self.conn)
        self.assertEqual(first, second)
        self.assertEqual(first["unresolved_value_count"], 3)
        self.assertEqual(first["unproven_source_value_count"], 0)
        def no_online_source(record):
            self.fail("unresolved count must not read source records")
        plan = {"filters": [{"property": "delivery_date", "op": "gte", "values": ["2032-03-01"]}]}
        options = {"connection": self.conn, "source_revision_sha256": pin, "_restricted": True,
                   "_admit": no_online_source, "_require_unresolved_summary": True,
                   "_summary_source_families": ["mail", "attachment_table"]}
        result = store.execute(plan, ["blue"], **options)
        self.assertEqual((result["total"], result["unresolved_value_count_status"], result["unresolved_value_count"]),
                         (0, "available", 2))
        result = store.execute(plan, ["blue"], **{**options, "_summary_selector": "other-selector"})
        self.assertEqual(result["unresolved_value_count"], 0)
        result = store.execute({"filters": [{"property": "quantity", "op": "gte", "values": ["1"]}]}, ["blue"], **options)
        self.assertEqual((result["unresolved_value_count_status"], result["unresolved_value_count"]), ("available", 0))
        result = store.execute({"filters": [*plan["filters"], {"property": "part_number", "op": "eq", "values": ["UNSEEN-703"]}]},
                               ["blue"], **options)
        self.assertEqual(result["unresolved_value_count_reason"], "unsupported_filters")
        self.assertNotIn("unresolved_value_count", result)
        # A missing positive bucket is not a proven zero.
        self.conn.execute("DELETE FROM record_unresolved_value_summary WHERE property_id='delivery_date'")
        result = store.execute(plan, ["blue"], **options)
        self.assertEqual(result["unresolved_value_count_reason"], "summary_integrity_failure")
        self.assertNotIn("unresolved_value_count", result)

    def test_fact_rebinding_invalidates_prior_scope_pin_coverage_transactionally(self):
        write_export(self.path, [export_row("blue", {"delivery_date": "pending"}),
                                 export_row("red", {"delivery_date": "pending"}, scope="red")])
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        old_pin, new_pin = sha256_json("old serving"), sha256_json("new serving")
        old_revision = self._summary_revision(old_pin)
        old_revision.authorized_source.source_scope_ids = ["blue", "red"]
        def helper(oid):
            return ({"observation_hash": sha256_json(oid), "source_scope_id": oid.removeprefix("obs-"),
                     "retrieval_source_family": "mail"}, SimpleNamespace(asset=SimpleNamespace()))
        old_revision.source_records._helper = helper
        plan = {"filters": [{"property": "delivery_date", "op": "gte", "values": ["2032-03-01"]}]}
        def count(scope, pin):
            return store.execute(plan, [scope], connection=self.conn, source_revision_sha256=pin,
                _require_unresolved_summary=True, _summary_source_families=["mail", "attachment_table"])
        with patch("formowl_mail.issue56_sealed_source._authorized_mail_selector_for_asset", return_value=None):
            store.verify_fact_serving_spans(old_revision, connection=self.conn)
            for scope in ("blue", "red"):
                self.assertEqual(count(scope, old_pin)["unresolved_value_count"], 1)
            new_revision = self._summary_revision(new_pin)
            with self.assertRaisesRegex(RuntimeError, "rollback rebind"):
                with self.conn.transaction():
                    store.verify_fact_serving_spans(new_revision, connection=self.conn)
                    for scope in ("blue", "red"):
                        stale = count(scope, old_pin)
                        self.assertEqual(stale["unresolved_value_count_reason"], "summary_not_current")
                        self.assertNotIn("unresolved_value_count", stale)
                    self.assertEqual(count("blue", new_pin)["unresolved_value_count"], 1)
                    raise RuntimeError("rollback rebind")
            for scope in ("blue", "red"):
                self.assertEqual(count(scope, old_pin)["unresolved_value_count"], 1)
            self.assertEqual(count("blue", new_pin)["unresolved_value_count_reason"], "scope_not_covered")
            store.verify_fact_serving_spans(new_revision, connection=self.conn)
        for scope in ("blue", "red"):
            stale = count(scope, old_pin)
            self.assertEqual(stale["unresolved_value_count_reason"], "summary_not_current")
            self.assertNotIn("unresolved_value_count", stale)
        self.assertIsNone(self.conn.execute("SELECT fact_serving_revision_sha256 FROM record WHERE record_id='red'").fetchone()[0])
        self.assertEqual(count("blue", new_pin)["unresolved_value_count"], 1)

    def test_summary_import_replacement_deletion_and_rollback_are_transactional(self):
        write_export(self.path, [export_row("a", {"delivery_date": "pending"})])
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        revision = self._summary_revision(pin)
        with patch("formowl_mail.issue56_sealed_source._authorized_mail_selector_for_asset", return_value=None):
            store.verify_fact_serving_spans(revision, connection=self.conn)
        plan = {"filters": [{"property": "delivery_date", "op": "gte", "values": ["2032-03-01"]}]}
        options = {"connection": self.conn, "source_revision_sha256": pin, "_require_unresolved_summary": True,
                   "_summary_source_families": ["mail", "attachment_table"]}
        self.assertEqual(store.execute(plan, ["blue"], **options)["unresolved_value_count"], 1)
        with self.assertRaisesRegex(RuntimeError, "rollback fixture"):
            with self.conn.transaction():
                write_export(self.path, [export_row("b", {"delivery_date": "2032-03-09"})])
                store.load_candidate_fact_exports(self.path, connection=self.conn)
                with patch("formowl_mail.issue56_sealed_source._authorized_mail_selector_for_asset", return_value=None):
                    store.verify_fact_serving_spans(revision, connection=self.conn)
                self.assertEqual(store.execute(plan, ["blue"], **options)["unresolved_value_count"], 0)
                raise RuntimeError("rollback fixture")
        self.assertEqual(store.execute(plan, ["blue"], **options)["unresolved_value_count"], 1)
        write_export(self.path, [])
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        with patch("formowl_mail.issue56_sealed_source._authorized_mail_selector_for_asset", return_value=None):
            store.verify_fact_serving_spans(revision, connection=self.conn)
        self.assertEqual(store.execute(plan, ["blue"], **options)["unresolved_value_count"], 0)

    def test_native_loader_bound_revision_preserves_fact_proof_and_legacy_native_stays_unproven(self):
        write_export(self.path, [export_row("fact", {"delivery_date": "pending"})])
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        revision = self._summary_revision(pin)
        plan = {"filters": [{"property": "delivery_date", "op": "gte", "values": ["2032-03-01"]}]}
        options = {"connection": self.conn, "source_revision_sha256": pin, "_require_unresolved_summary": True,
                   "_summary_source_families": ["mail", "attachment_table"]}
        path = self.path / "native.jsonl"
        path.write_text("")
        with patch("formowl_mail.issue56_sealed_source._authorized_mail_selector_for_asset", return_value=None):
            store.verify_fact_serving_spans(revision, connection=self.conn)
            store.load_native_rows(path, connection=self.conn, revision=revision)
        self.assertEqual(store.execute(plan, ["blue"], **options)["unresolved_value_count"], 1)
        store.load_native_rows(path, connection=self.conn)
        self.assertEqual(store.execute(plan, ["blue"], **options)["unresolved_value_count_reason"], "source_scope_unproven")
        legacy = dict(observation_id="legacy-row", observation_hash=sha256_json("legacy-row"),
            table_index=0, row_index=1, permission_scope_id="blue", header_signature=["Due"],
            cells=[dict(cell_index=0,column_name="Due",observation_id="legacy-cell",
                        observation_hash=sha256_json("legacy-cell"),text="pending")])
        path.write_text(json.dumps(legacy)+"\n")
        with patch("formowl_mail.issue56_sealed_source._authorized_mail_selector_for_asset", return_value=None):
            store.load_native_rows(path, {sha256_json(["Due"]): [{"property_id":"delivery_date"}]},
                                   connection=self.conn, revision=revision)
            self.conn.execute("UPDATE record SET verified_at_export=true,source_revision_sha256=%s,export_binding='{}'::jsonb WHERE kind='table_row'", (pin,))
            store.rebuild_unresolved_value_summaries(revision, connection=self.conn)
        result = store.execute(plan, ["blue"], **options)
        self.assertEqual(result["unresolved_value_count_reason"], "source_scope_unproven")
        self.assertNotIn("unresolved_value_count", result)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM record_unresolved_value_summary WHERE NOT source_proven AND NOT selector_proven").fetchone()[0], 1)

    def test_failed_fact_import_rolls_back_summary_invalidation(self):
        write_export(self.path, [export_row("a", {"delivery_date": "pending"})])
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        with patch("formowl_mail.issue56_sealed_source._authorized_mail_selector_for_asset", return_value=None):
            store.verify_fact_serving_spans(self._summary_revision(pin), connection=self.conn)
        before = self.conn.execute("SELECT * FROM record_unresolved_value_summary_coverage ORDER BY property_id").fetchall()
        (self.path / "rows.jsonl").write_text("{invalid fixture\n")
        with self.assertRaises(ValueError):
            store.load_candidate_fact_exports(self.path, connection=self.conn)
        self.assertEqual(self.conn.execute("SELECT * FROM record_unresolved_value_summary_coverage ORDER BY property_id").fetchall(), before)
        result = store.execute({"filters":[{"property":"delivery_date","op":"gte","values":["2032-03-01"]}]},
            ["blue"],connection=self.conn,source_revision_sha256=pin,_require_unresolved_summary=True,
            _summary_source_families=["mail","attachment_table"])
        self.assertEqual(result["unresolved_value_count"], 1)

    def test_required_summary_missing_stale_or_unproven_is_unavailable(self):
        pin = sha256_json("serving")
        plan = {"filters": [{"property": "delivery_date", "op": "gte", "values": ["2032-03-01"]}]}
        options = {"connection": self.conn, "source_revision_sha256": pin, "_require_unresolved_summary": True,
                   "_summary_source_families": ["mail", "attachment_table"]}
        self.assertEqual(store.execute(plan, ["blue"], **options)["unresolved_value_count_status"], "unavailable")
        write_export(self.path, [export_row("a", {"delivery_date": "pending"})])
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        # Structural import counts alone cannot prove source family.
        store.rebuild_unresolved_value_summaries(connection=self.conn)
        result = store.execute(plan, ["blue"], **options)
        self.assertEqual(result["unresolved_value_count_reason"], "source_scope_unproven")
        self.assertNotIn("unresolved_value_count", result)
        store._invalidate_unresolved_summaries(self.conn)
        self.assertEqual(store.execute(plan, ["blue"], **options)["unresolved_value_count_reason"], "summary_not_current")
        self.conn.execute("DROP TABLE record_unresolved_value_summary_coverage")
        self.assertEqual(store.execute(plan, ["blue"], **options)["unresolved_value_count_reason"], "summary_unavailable")

    def test_complete_r1_shards_preserve_partial_headers_and_roll_back_invalid_snapshot(self):
        names = ["Asset", "CRD", "ETD", None]
        row = dict(observation_id="source-row", observation_hash=sha256_json("source-row"),
                   table_index=2, row_index=4, table_id="native-table", source_family="attachment_table",
                   document_id="attach-obs", attachment_observation_id="attach-obs", attachment_asset_id="asset-id",
                   mail_observation_id="mail-obs", mail_message_id="mail-id", sent_at="2031-12-30",
                   row_role="data_candidate", permission_scope_id="blue", header_signature=names,
                   header_signature_hash=sha256_json(names), named_cell_count=3, complete=False)
        row["cells"] = [dict(cell_index=i, column_name=name, observation_id=f"cell-{i}",
                             observation_hash=sha256_json(i), text=text) for i, (name, text) in
                        enumerate(zip(names, ["AX703", "2032/1/4", "2032/1/4", ""], strict=True))]
        blank = dict(row, observation_id="unnamed-row", observation_hash=sha256_json("unnamed-row"),
                     header_signature=[None], header_signature_hash=None, named_cell_count=0,
                     cells=[dict(row["cells"][-1], cell_index=0, observation_id="blank")])
        empty = dict(row, observation_id="empty-row", observation_hash=sha256_json("empty-row"),
                     header_signature=[], header_signature_hash=None, named_cell_count=0, complete=False, cells=[])
        content = b"".join(json.dumps(r).encode() + b"\n" for r in (row, blank, empty))
        shard = self.path / "rows-00.jsonl"
        seal = dict(row_count=3, cell_count=5, size_bytes=len(content), sha256="sha256:" + hashlib.sha256(content).hexdigest())
        shard.write_bytes(content)
        binding = dict(artifact_id="formowl_native_table_records_v1", binding={"source_revision_sha256": sha256_json("r1"), "exporter_sha256":sha256_json("exporter")})
        summary = dict(binding, status="complete", source_binding_validated=True, completed_shards=1, total_shards=1,
                       row_count=3, cell_count=5, row_output_bytes=len(content))
        (self.path / "checkpoint.safe.json").write_text(json.dumps(dict(binding, completed_shards={"00": seal})))
        summary_path = self.path / "summary.safe.json"
        summary_path.write_text(json.dumps(summary))
        mapping = {sha256_json(names): [{"property_id": "part_number"}, {"property_id": "delivery_date", "date_role": "requested"},
                                       {"property_id": "delivery_date", "date_role": "estimated_ship"}, None]}
        self.assertEqual(store.load_native_rows(self.path, mapping, connection=self.conn), {"records": 3, "values": 5})
        self.assertEqual(self.conn.execute("SELECT count(*) FROM record_value WHERE record_id='native:empty-row'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM record WHERE record_id='native:empty-row'").fetchone()[0], 1)
        item = self.query("part_number", "eq", ["AX703"], **{"return": ["delivery_date"]})["rows"][0]
        self.assertEqual(item["native_locator"]["attachment_observation_id"], "attach-obs")
        self.assertEqual(item["native_locator"]["mail_observation_id"], "mail-obs")
        metadata = self.conn.execute("SELECT source_revision_sha256,verified_at_export,export_binding FROM record "
                                     "WHERE record_id='native:empty-row'").fetchone()
        self.assertEqual(metadata, (sha256_json("r1"), True, {"shard":"00", "shard_sha256":seal["sha256"],
                                                            "exporter_sha256":sha256_json("exporter")}))
        dates = item["returned"]["delivery_date"]
        self.assertEqual([(v["column_name_raw"], v["date_role"]) for v in dates], [("CRD", "requested"), ("ETD", "estimated_ship")])
        self.assertEqual(dates[0]["evidence_spans"][0]["observation_id"], "cell-1")
        self.assertEqual(self.conn.execute("SELECT column_name_raw,property_id FROM record_value WHERE record_id='native:unnamed-row'").fetchall(), [(None,None)])
        shard.write_bytes(content.replace(b"2032", b"2033"))
        with self.assertRaisesRegex(ValueError, "shard"):
            store.load_native_rows(self.path, mapping, connection=self.conn)
        summary_path.write_text(json.dumps(dict(summary, status="in_progress")))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            store.load_native_rows(self.path, mapping, connection=self.conn)
        self.assertEqual(self.query("column:CRD", "eq", ["2032/1/4"])["total"], 1)

    def test_nul_in_native_text_is_shown_as_symbol_and_keeps_original_signature(self):
        names = ["P\x00N", "ETD"]
        row = dict(observation_id="nul-row", observation_hash=sha256_json("nul-row"), table_index=0, row_index=1,
                   table_id="t", source_family="attachment_table", row_role="data_candidate",
                   permission_scope_id="blue", header_signature=names, header_signature_hash=sha256_json(names),
                   named_cell_count=2, complete=True)
        row["cells"] = [dict(cell_index=i, column_name=name, observation_id=f"nul-cell-{i}",
                             observation_hash=sha256_json(f"nul-{i}"), text=text)
                        for i, (name, text) in enumerate(zip(names, ["AX\x00703", "2032/1/4"], strict=True))]
        content = json.dumps(row).encode() + b"\n"
        self.assertIn(b"\\u0000", content)
        seal = dict(row_count=1, cell_count=2, size_bytes=len(content), sha256="sha256:" + hashlib.sha256(content).hexdigest())
        (self.path / "rows-00.jsonl").write_bytes(content)
        binding = dict(artifact_id="formowl_native_table_records_v1", binding={"source_revision_sha256": sha256_json("r1")})
        (self.path / "checkpoint.safe.json").write_text(json.dumps(dict(binding, completed_shards={"00": seal})))
        (self.path / "summary.safe.json").write_text(json.dumps(dict(binding, status="complete", source_binding_validated=True,
            completed_shards=1, total_shards=1, row_count=1, cell_count=2, row_output_bytes=len(content))))
        mapping = {sha256_json(names): [{"property_id": "part_number"}, {"property_id": "delivery_date", "date_role": "estimated_ship"}]}
        self.assertEqual(store.load_native_rows(self.path, mapping, connection=self.conn), {"records": 1, "values": 2})
        stored = self.conn.execute("SELECT column_name_raw, raw_value FROM record_value WHERE record_id='native:nul-row' ORDER BY ordinal").fetchall()
        self.assertEqual(stored[0], ("P\u2400N", "AX\u2400703"))
        locator = self.conn.execute("SELECT native_locator FROM record WHERE record_id='native:nul-row'").fetchone()[0]
        self.assertEqual(locator["nul_substituted"], "U+0000 shown as U+2400")
        signature = self.conn.execute("SELECT header_signature_id FROM record WHERE record_id='native:nul-row'").fetchone()[0]
        self.assertEqual(signature, sha256_json(names))

    def test_native_columns_survive_loading_with_and_without_a_mapping(self):
        path = self.path / "native.jsonl"
        names = ["Batch", "Planned", "Note"]
        row = {"observation_id": "r1", "observation_hash": sha256_json("r1"), "table_index": 0, "row_index": 7,
               "mail_message_id": "fictional-message", "sent_at": "2032-02-04", "row_role": "data_candidate",
               "permission_scope_id": "blue", "header_signature": names,
               "cells": [{"cell_index": i, "column_name": name, "observation_hash": sha256_json(name), "text": value}
                         for i, (name, value) in enumerate(zip(names, ["BR-51", "2032/4/1", ""], strict=True))]}
        path.write_text(json.dumps(row) + "\n")
        store.load_native_rows(path, {}, connection=self.conn)
        item = self.query("column:Batch", "eq", ["br-51"])["rows"][0]
        self.assertEqual([v["property_id"] for v in item["values"]], [None] * 3)
        self.assertEqual(item["values"][-1]["raw_value"], "")
        mapping = {sha256_json(names): [{"property_id": "part_number"},
                                       {"property_id": "delivery_date", "date_role": "requested"}, None]}
        store.load_native_rows(path, mapping, connection=self.conn)
        result = self.query("delivery_date", "eq", ["2032-04-01"])
        self.assertEqual(result["total"], 1)
        date = result["rows"][0]["values"][1]
        self.assertEqual((date["date_role"], date["column_name_raw"], date["quote"]), ("requested", "Planned", "2032/4/1"))
        self.assertEqual((date["citation_hash"], date["native_locator"]["cell_index"]), (sha256_json("Planned"), 1))
        self.assertEqual(self.query("column:Planned", "eq", ["2032/4/1"])["total"], 1)

    def test_reloads_replace_atomically_and_keep_all_citations_and_roles(self):
        row = export_row("repeat", {"delivery_date": "2032/3/9"})
        fact = row["fields"]["delivery_date"][0]
        fact["times"] = [{"role": "planned"}, {"role": "actual"}]
        fact["evidence_spans"].append({**fact["evidence_spans"][0], "native_locator": {"page": 2}})
        write_export(self.path, [row])
        for _ in range(2):
            counts = store.load_candidate_fact_exports(self.path, connection=self.conn)
            self.assertEqual(counts, {"records": 1, "values": 1})
        with (self.path / "rows.jsonl").open("ab") as stream:
            stream.write(b" ")
        with self.assertRaises(ValueError):
            store.load_candidate_fact_exports(self.path, connection=self.conn)
        result = self.query("delivery_date", "eq", ["2032-03-09"])
        self.assertEqual(result["total"], 1)
        value = result["rows"][0]["values"][0]
        self.assertEqual(value["date_roles"], ["planned", "actual"])
        self.assertEqual(len(value["evidence_spans"]), 2)

    def test_transitive_overlap_keeps_members_all_values_and_coordinate_boundaries(self):
        other = self.path / "other"
        other.mkdir()
        first = self.path / "first"
        first.mkdir()

        def fragment(rid, prop, interval, scope="blue", field="text", oid="common"):
            row = export_row(rid, {prop: "value"}, scope=scope)
            fact = row["fields"][prop][0]
            digest = sha256_json(oid)
            fact.update(observation_hashes={oid: digest}, source_observation_ids=[oid])
            a, b = interval
            fact["evidence_spans"] = [dict(observation_id=oid, observation_hash=digest, field_path=[field],
                                            native_locator={"page": 1}, start=a, end=b, quote="x" * (b-a))]
            return row

        a = fragment("a", "part_number", (3, 5))
        b = fragment("b", "origin_country", (0, 10))
        c = fragment("c", "quantity", (9, 12))
        d = fragment("d", "po_number", (12, 14))
        e = fragment("e", "quantity", (1, 2), scope="red")
        f = fragment("f", "quantity", (1, 2), field="other")
        g = fragment("g", "quantity", (1, 2), oid="elsewhere")
        write_export(first, [a, c, d])
        write_export(other, [b, e, f, g])
        stats = store.load_candidate_fact_exports(self.path, connection=self.conn)
        self.assertEqual(stats, {"records": 5, "values": 7})
        group = self.query("part_number", "eq", ["value"])["rows"][0]
        self.assertEqual(group["export_row_ids"], ["a", "b", "c"])
        self.assertEqual([(v["export_row_id"], v["property_id"]) for v in group["values"]],
                         [("a", "part_number"), ("b", "origin_country"), ("c", "quantity")])
        # Removing the bridge from just one export must split the component.
        write_export(other, [e, f, g])
        store.load_candidate_fact_exports(other, connection=self.conn)
        self.assertEqual(self.query("part_number", "eq", ["value"])["rows"][0]["export_row_ids"], ["a"])
        self.assertEqual(store.execute({}, ["blue"], connection=self.conn)["total"], 5)

    def test_identifier_tokens_quote_mentions_and_unlinked_group_across_pages(self):
        long_key = "  ＫＸ－４０１ Module board SP-999  "
        seed = export_row("seed", {"part_number": long_key})
        weak = export_row("linked", {"origin_country": "Canada", "delivery_date": "2032/2/9"})
        fact = weak["fields"]["origin_country"][0]
        fact["evidence_spans"].append({**fact["evidence_spans"][0], "quote": "Ordered Kx-401 here"})
        other = export_row("free", {"origin_country": "CA", "po_number": "PO-987"})
        other["fields"]["origin_country"][0]["evidence_spans"][0]["quote"] = "KX-4012 and SECRET-7"
        hidden = export_row("hidden", {"part_number": "SECRET-7"}, scope="red")
        write_export(self.path, [seed, weak, other, hidden])
        store.load_candidate_fact_exports(self.path, connection=self.conn)

        res = self.query("part_number", "eq", ["ＫＸ－４０１"])
        self.assertEqual(res["total"], 2)
        rows = {r["record_id"]: r for r in res["rows"]}
        labels = {e["norm_key"]: e for e in rows["seed"]["entities"]}
        self.assertEqual(set(labels), {"kx-401", "kx-401 module board sp-999"})
        self.assertEqual((labels["kx-401"]["via"], labels["kx-401"]["raw_key"]), ("value", "ＫＸ－４０１"))
        self.assertEqual([(e["norm_key"], e["via"]) for e in rows["linked"]["entities"]],
                         [("kx-401", "quote_mention")])
        self.assertEqual(self.query("part_number", "eq", ["board"])["total"], 0)
        self.assertEqual(self.query("part_number", "eq", [long_key])["total"], 1)
        plan = {"group_by": "part_number", "limit": 1}
        first = self.query("origin_country", "in", ["Canada"], **plan)
        second = self.query("origin_country", "in", ["CA"], **plan, offset=1)
        self.assertEqual((first["total"], first["unlinked_count"], second["unlinked_count"]), (2, 1, 1))
        self.assertEqual(first["rows"][0]["group_keys"], ["未連到料件"])
        self.assertFalse(any(e["entity_type"] == "part" for e in first["rows"][0]["entities"]))
        self.assertEqual(second["rows"][0]["group_keys"], ["kx-401"])

    def test_only_whole_and_leading_identifiers_seed_and_material_memberships_page(self):
        seed = export_row("s", {"part_number": "A123 alpha R789", "origin_country": "Canada"})
        alias = export_row("m", {"manufacturer_part_number": "M456", "origin_country": "CA"})
        known = export_row("k", {"part_number": "words M456", "origin_country": "CA"})
        mention = export_row("w", {"origin_country": "CA"})
        mention["fields"]["origin_country"][0]["evidence_spans"][0]["quote"] = "A123 M456 R789"
        noise = export_row("n", {"part_number": "1234", "manufacturer_part_number": "WORDS", "origin_country": "CA"})
        write_export(self.path, [seed, alias, known, mention, noise])
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        rows = self.query("origin_country", "eq", ["CA"], group_by="料件", limit=2)
        entries = list(rows["rows"])
        while rows["truncated"]:
            rows = self.query("origin_country", "eq", ["Canada"], group_by="料件", offset=len(entries), limit=2)
            entries.extend(rows["rows"])
        self.assertEqual((rows["total"], rows["grouped_total"], rows["unlinked_count"]), (5, 8, 1))
        indexed = {(r["record_id"], r["group_keys"][0]): r["group_via"] for r in entries}
        self.assertEqual(len(indexed), 8)
        self.assertEqual(indexed["k", "m456"], "value")
        self.assertEqual(indexed["w", "m456"], "quote_mention")
        self.assertEqual(indexed["w", "a123"], "quote_mention")
        self.assertIsNone(indexed["n", "未連到料件"])
        self.assertFalse(any(key == "r789" for _, key in indexed))
        self.assertEqual(self.query("part_number", "eq", ["1234"])["total"], 1)

    def test_groups_count_admitted_members_independently_of_detail_limit(self):
        rows = [
            export_row("one", {"origin_country":"Canada", "part_number":"AX-123"}),
            export_row("two", {"origin_country":"CA", "part_number":"AX-123"}),
            export_row("three", {"origin_country":"Canada", "part_number":"BX-987"}),
            export_row("other", {"origin_country":"Canada", "part_number":"ZZ-456"}, scope="red"),
        ]
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        proofs = []
        def admit(record):
            self.assertEqual(record["permission_scope"], "blue")
            self.assertNotIn("raw_value", record["values"][0])
            proofs.append(record["record_id"])
            return record["record_id"] != "three"
        plan = {"filters":[{"property":"origin_country","op":"eq","values":["CA"]}],
                "return":["part_number","origin_country"],"limit":1,"order_by":"projection_coverage"}
        result = store.execute(plan, ["blue"], connection=self.conn, _result_groups=True, _admit=admit)
        self.assertCountEqual(proofs, ["one", "two", "three"])
        self.assertEqual((result["total"], len(result["rows"])), (2, 1))
        self.assertEqual(len(result["result_groups"]), 1)
        signature, count, rid, variants, proved = result["result_groups"][0]
        self.assertEqual((signature,count), ([["AX-123"],[]], 2))
        self.assertIn(rid, {"one","two"})
        self.assertEqual({cell[0] for vector in variants for cell in vector[1]}, {"Canada","CA"})
        self.assertTrue(proved)

    def test_pdf_inherited_spans_do_not_join_independent_item_rows(self):
        def item(rid, label, local, observation):
            row = export_row(rid, {"part_number": "AX-123", "quantity": "10", "supplier": "Header"})
            row["item_or_row"] = label
            for prop, facts in row["fields"].items():
                fact = facts[0]
                oid = "header-observation" if prop == "supplier" else observation
                a, b = (0, 10) if prop == "supplier" else local
                span = dict(observation_id=oid, observation_hash=sha256_json(oid),
                            field_path=["text"], native_locator={"page": 1}, start=a, end=b,
                            quote="x" * (b-a))
                fact.update(evidence_spans=[span], observation_hashes={oid: sha256_json(oid)},
                            source_observation_ids=[oid])
            return row
        # Different extractor row labels can still describe the same local line.
        first = self.path / "first"
        second = self.path / "second"
        first.mkdir()
        second.mkdir()
        rows = [item("a", "line one", (20, 30), "local-one"),
                item("b", "line two", (40, 50), "local-two")]
        write_export(first, rows)
        write_export(second, [item("a-copy", "alternate line label", (20, 30), "local-one")])
        result = store.load_candidate_fact_exports(self.path, connection=self.conn)
        self.assertEqual(result, {"records": 2, "values": 9})
        actual = store.execute({}, ["blue"], connection=self.conn)["rows"]
        self.assertCountEqual([r["export_row_ids"] for r in actual], [["a", "a-copy"], ["b"]])
        self.assertEqual(sum(len(r["values"]) for r in actual), 9)
        self.assertTrue(all(v["evidence_spans"] for r in actual for v in r["values"]))
        # Single-export replacement must retain the row anchors in export_members.
        write_export(second, [item("a-copy", "alternate line label", (20, 30), "local-one")])
        store.load_candidate_fact_exports(second, connection=self.conn)
        self.assertCountEqual([r["export_row_ids"] for r in store.execute({}, ["blue"], connection=self.conn)["rows"]],
                              [["a", "a-copy"], ["b"]])

    def test_result_set_projects_proved_typed_keys_and_normalized_surfaces(self):
        rows = [export_row("own", {"part_number": "AX-123\u2003extra text", "manufacturer_part_number": "BX-987",
                                   "origin_country": "china", "po_number": "123456"}),
                export_row("fallback", {"part_number": "待更新", "manufacturer_part_number": "CX@987",
                                        "origin_country": "CN"}),
                export_row("unicode", {"part_number": "漢a١٢", "origin_country": "China"}),
                export_row("hidden", {"part_number": "HX-123", "origin_country": "China"}, scope="red")]
        write_export(self.path, rows)
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        pin = sha256_json("serving")
        self.conn.execute("UPDATE record SET fact_serving_revision_sha256=%s", (pin,))
        calls = []
        def admit(record):
            calls.append(record["record_id"])
            return True
        plan = {"filters": [{"property": "origin_country", "op": "eq", "values": ["CN"]}],
                "return": ["part_number", "manufacturer_part_number", "origin_country", "po_number"],
                "order_by": "projection_coverage"}
        result = store.execute(plan, ["blue"], connection=self.conn, source_revision_sha256=pin,
                               _admit=admit, _result_groups=True)
        self.assertEqual((result["total"], len(result["rows"])), (3, 3))
        self.assertCountEqual(calls, ["own", "fallback", "unicode"])
        groups = {group[2]: group for group in result["result_groups"]}
        own_signatures = [g[0][:2] for g in result["result_groups"] if g[2] == "own"]
        self.assertCountEqual(own_signatures, [[["AX-123"], []], [[], ["BX-987"]]])
        self.assertEqual(groups["fallback"][0][:2], [["CX@987"], ["CX@987"]])
        self.assertEqual(groups["unicode"][0][:2], [["漢a١٢"], ["漢a١٢"]])
        for signature, count, rid, variants, proved in result["result_groups"]:
            self.assertTrue(proved)
            for vector in variants:
                self.assertEqual(vector[2][0][3], "CN")
                self.assertEqual(vector[3], [])  # Numeric PO has no existing typed edge.
                self.assertTrue(all(len(cell) == 4 for column in vector for cell in column))
        own = next(r for r in result["rows"] if r["record_id"] == "own")
        self.assertIn("AX-123\u2003extra text", [v["raw_value"] for v in own["values"]])
        self.assertIn("123456", [v["raw_value"] for v in own["values"]])
        # An existing numeric PO edge is eligible, without changing seeding.
        eid = self.conn.execute("INSERT INTO entity(entity_type,norm_key) VALUES ('purchase_order','123456') RETURNING entity_id").fetchone()[0]
        proof = next(v for v in own["values"] if v["property_id"] == "po_number")
        self.conn.execute("INSERT INTO record_entity(record_id,entity_id,via_property,raw_key,citation_hash) VALUES ('own',%s,'po_number','123456',%s)",
                          (eid, proof["citation_hash"]))
        result = store.execute(plan, ["blue"], connection=self.conn, source_revision_sha256=pin, _result_groups=True)
        self.assertEqual(result["total"], 3)
        self.assertEqual(next(g for g in result["result_groups"] if g[2] == "own")[0][3], ["123456"])

    def test_result_set_quote_fallback_and_unproved_edges(self):
        write_export(self.path, [export_row("seed", {"part_number": "AX-123"}),
                                 export_row("mention", {"part_number": "待更新", "supplier": "ref\u2003AX-123"})])
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        plan = {"filters": [{"property": "supplier", "op": "eq", "values": ["ref AX-123"]}],
                "return": ["part_number"], "order_by": "projection_coverage"}
        result = store.execute(plan, ["blue"], connection=self.conn, _result_groups=True)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["result_groups"][0][0], [["AX-123"]])
        self.assertEqual(result["result_groups"][0][3][0][0][0][2:], ["quote_mention", "ax-123"])
        self.assertTrue(result["result_groups"][0][4])
        self.conn.execute("UPDATE record_entity SET citation_hash=%s WHERE record_id='mention'", (sha256_json("wrong"),))
        result = store.execute(plan, ["blue"], connection=self.conn, _result_groups=True)
        self.assertEqual(result["total"], 1)
        self.assertFalse(result["result_groups"][0][4])

    def test_result_set_nonidentity_raw_groups_and_unresolved_metadata_are_retained(self):
        write_export(self.path, [export_row("a", {"origin_country": "china", "quantity": "unknown"}),
                                 export_row("b", {"origin_country": "China", "quantity": "10 pcs"})])
        store.load_candidate_fact_exports(self.path, connection=self.conn)
        result = store.execute({"return": ["origin_country", "quantity"], "order_by": "projection_coverage"}, ["blue"],
                               connection=self.conn, _result_groups=True)
        self.assertEqual((result["total"], len(result["result_groups"])), (2, 2))
        cells = {g[2]: g[3][0] for g in result["result_groups"]}
        self.assertEqual(cells["a"][0][0], ["china", "origin_country label", None, "CN"])
        self.assertEqual(cells["b"][0][0], ["China", "origin_country label", None, "CN"])
        self.assertIsNone(cells["a"][1][0][3])
        self.assertEqual(cells["b"][1][0][3], "10")


class EntityProjectionKeyTests(unittest.TestCase):
    def test_existing_seed_shape_is_preserved_except_whitespace_composites(self):
        for raw in ("AX@123", "漢a١٢", " ＡＸ－１２３ ", "ax[123]"):
            key = store.normalize("identifier", raw)["norm"]
            self.assertTrue(store.eligible_entity_projection_key("part", key), raw)
        for raw in ("NEW", "6", "25", "待更新", "D1302 D1303", "AX-123\nmodule", "x" * 65 + "1"):
            key = store.normalize("identifier", raw)["norm"]
            self.assertFalse(store.eligible_entity_projection_key("part", key), raw)
        self.assertTrue(store.eligible_entity_projection_key("purchase_order", "123456"))
        self.assertFalse(store.eligible_entity_projection_key("part", "123456"))


class KnownEntityTermTests(unittest.TestCase):
    def test_eight_maximum_length_terms_expand_within_one_bounded_exact_query(self):
        terms = tuple(" ".join(f"{j}{i:03d}" for i in range(16)) for j in range(8))
        self.assertTrue(all(len(term) <= 80 for term in terms))
        calls = []
        def execute(query, args):
            calls.append(args)
            return SimpleNamespace(fetchall=lambda: [])
        result = store.known_entity_filters(terms, ["blue"], source_revision_sha256=sha256_json("serving"),
                                            connection=SimpleNamespace(execute=execute))
        self.assertEqual(result, ([], False))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0][0]), 136)
        self.assertEqual(calls[0][0], calls[0][1])
        self.assertEqual(calls[0][0][:8], list(terms))
