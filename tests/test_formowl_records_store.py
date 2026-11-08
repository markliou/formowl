import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

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
