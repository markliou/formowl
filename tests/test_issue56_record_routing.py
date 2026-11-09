import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from formowl_contract import sha256_json
from formowl_gateway import issue56_record_table as records, issue56_sealed_source_loader as loader
from formowl_mail.human_uat_orchestrator import compact_evidence_for_model
from formowl_retrieval.gateway import (
    _SourcePhaseTrace, _source_document_full_read_scope, _source_phase_trace_scope, source_evidence_deadline_scope,
)
import test_issue56_uat_handler_composition as fixtures


class RecordRoutingTests(unittest.TestCase):
    @staticmethod
    def _document_binding(arguments, *, families=("document_text",), first=True):
        public = {key: value for key, value in arguments.items()
                  if key not in {"requester_user_id", "workspace_id", "session_id"}}
        return (arguments["request_contract"]["original_query_hash"], families,
                sha256_json({"name": "query_effective_graph_view", "arguments": public}), first)

    @staticmethod
    def _empty_record_lookup(revision, table_query, contract, capabilities, selector, budget, max_reads, **kwargs):
        budget["record_lookup_queried"] = True
        budget["record_lookup_reason"] = "no_known_entity"
        return (), None

    def test_bound_false_and_mail_provenance_allow_exact_and_implicit_record_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp))
            with patch.object(records, "catalog", return_value={"properties": {"quantity": ["Quantity"]}}):
                handler = loader._build_source_start_semantic_handler(bound, mail_tool=False)
            for explicit in (False, True):
                for families, first in ((("mail",), False), (("mail",), True), (("document_text",), True)):
                    with self.subTest(explicit=explicit, provenance_families=families, first=first):
                        arguments = fixture._arguments(families=("mail", "attachment_table"))
                        if explicit:
                            arguments["table_query"] = {"filters": [{"field": "Asset", "value": "ZX-742"}],
                                                        "projection_fields": ["Ticket"]}
                            arguments["request_contract"].update(query_class="exact_set_or_inventory",
                                maximum_claim_strength="complete_authorized_scope")
                        trace = _SourcePhaseTrace({})
                        with (patch.object(records, "query_records", side_effect=self._empty_record_lookup) as called,
                              _source_document_full_read_scope(self._document_binding(arguments, families=families, first=first)),
                              _source_phase_trace_scope(trace), source_evidence_deadline_scope(time.monotonic()+10)):
                            handler(arguments)
                        called.assert_called_once()
                        self.assertEqual(called.call_args.args[1], arguments.get("table_query"))
                        if not explicit:
                            self.assertEqual(called.call_args.kwargs["required_terms"], ("zx-742",))
                        phase = next(p for p in json.loads(trace.snapshot())["details"] if p.get("name") == "record_store")
                        self.assertTrue(phase["queried"])
                        self.assertEqual(phase["reason"], "no_known_entity")

    def test_only_bound_document_evidence_intent_declines_records_and_performs_full_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures._source_start_preparation_fixture(Path(tmp), families=("document_text",),
                document_text="Completed the design.\n\nNext action is owner review.")
            revision = fixtures.issue56_sealed_source.load_issue56_ingestion_revision(
                fixture.directory, expected_revision_sha256=fixture.preparation_sha256)
            with patch.object(records, "catalog", return_value={"properties": {"quantity": ["Quantity"]}}):
                handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
            for case in ("false", "stale_original", "stale_wire", "exact", "eligible"):
                with self.subTest(case=case):
                    arguments = fixtures.CandidateFactReachabilityTests._arguments(
                        families=("document_text",), terms=("missingcompound",),
                        query_class="exact_set_or_inventory" if case == "exact" else "evidence_lookup")
                    binding = list(self._document_binding(arguments, first=case != "false"))
                    if case == "stale_original":
                        binding[0] = sha256_json("a different original prompt")
                    elif case == "stale_wire":
                        binding[2] = sha256_json("a different MCP request")
                    trace = _SourcePhaseTrace({})
                    with (patch.object(records, "query_records", side_effect=self._empty_record_lookup) as called,
                          _source_document_full_read_scope(tuple(binding)), _source_phase_trace_scope(trace),
                          source_evidence_deadline_scope(time.monotonic()+10)):
                        result = handler(arguments)
                    phase = next(p for p in json.loads(trace.snapshot())["details"] if p.get("name") == "record_store")
                    if case == "eligible":
                        called.assert_not_called()
                        self.assertEqual((phase["state"], phase["reason"], phase["queried"]),
                                         ("declined", "request_constraints", False))
                        recovery = result["query_agent"]["context_bundle"]["source_recovery"]
                        self.assertEqual(recovery["mode"], "small_scope_full_read")
                        self.assertTrue(recovery["scan_complete"])
                        self.assertEqual(len(result["citations"]), 2)
                    else:
                        called.assert_called_once()
                        self.assertEqual((phase["reason"], phase["queried"]), ("no_known_entity", True))
                        self.assertNotIn("small_scope_full_read", json.dumps(result))

    def test_explicit_exact_and_implicit_lookup_use_the_same_record_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp))
            args = fixture._arguments(families=("mail","attachment_table"))
            cap = {"properties": {"quantity": ["Quantity"]}}
            with patch.object(records, "catalog", return_value=cap):
                handler = loader._build_source_start_semantic_handler(bound, mail_tool=False)

            for explicit in (False, True):
                with self.subTest(explicit=explicit):
                    arguments = dict(args)
                    if explicit:
                        arguments["table_query"] = {"filters": [{"field":"Asset","value":"ZX-742"}],
                                                    "projection_fields":["Ticket"]}
                        arguments["request_contract"] = dict(args["request_contract"],
                            query_class="exact_set_or_inventory", maximum_claim_strength="complete_authorized_scope")
                    def lookup(revision, table_query, contract, capabilities, selector, budget, max_reads, **kw):
                        self.assertEqual(table_query, arguments.get("table_query"))
                        if not explicit:
                            self.assertEqual(kw["required_terms"], tuple(t.casefold() for t in args["required_terms"]))
                        rows = list(revision.candidate_fact_rows)
                        for row in rows:
                            row["_projection_rank"] = (1,"")
                        counts = {"total":len(rows), "without_projection":0, "quantity_only":0}
                        budget["record_lookup_queried"] = True
                        budget["record_lookup_reason"] = "matched"
                        return rows,counts
                    trace = _SourcePhaseTrace({})
                    with patch.object(records, "query_records", side_effect=lookup) as called, _source_phase_trace_scope(trace), source_evidence_deadline_scope(time.monotonic()+10):
                        result = handler(arguments)
                    called.assert_called_once()
                    wire = compact_evidence_for_model(result)
                    self.assertEqual(wire["evidence"][0]["source_type"], "candidate_fact_table")
                    self.assertNotIn("record_store", json.dumps(wire))
                    phase = next(p for p in json.loads(trace.snapshot())["details"] if p.get("name")=="record_store")
                    self.assertTrue(phase["queried"])
                    self.assertEqual(phase["reason"], "presented")
                    self.assertGreater(phase["M"], 0)
                    self.assertFalse(result.get("deterministic_exact",False))
                    if not explicit:
                        self.assertTrue(any(e.get("source_type")!="candidate_fact_table" for e in wire["evidence"][1:]))

    def test_validation_guidance_survives_compaction_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp))
            args = fixture._arguments(families=("mail","attachment_table"))
            args["table_query"] = {"filters":[{"field":"bad label","value":"ZX-742"}],"projection_fields":["Ticket"]}
            cap = {"properties":{"quantity":["Qty"]}}
            with patch.object(records,"catalog",return_value=cap), patch.object(records,"query_records",
                    side_effect=records.RecordFieldValidationError(cap)), patch.object(loader,"_execute_source_start_table") as fallback:
                result = loader._build_source_start_semantic_handler(bound,mail_tool=False)(args)
            fallback.assert_not_called()
            wire = compact_evidence_for_model(result)
            self.assertEqual(wire["status"], "clarification_required")
            self.assertIn("quantity", wire["coverage"]["disclosure"])
            self.assertNotIn("bad label", json.dumps(wire))

    def test_rejected_detail_leaves_export_groups_and_unknown_disclosure_count(self):
        from formowl_contract import sha256_json

        with tempfile.TemporaryDirectory() as tmp:
            fixture = fixtures.CandidateFactReachabilityTests()
            bound, _ = fixture._native(Path(tmp))
            args = fixture._arguments(families=("mail", "attachment_table"))
            args["table_query"] = {"filters": [{"field": "Asset", "value": "ZX-742"}],
                                   "projection_fields": ["Ticket"]}
            rows = list(bound.candidate_fact_rows)
            for row in rows:
                row["_projection_rank"] = (1, "")
            groups = [{"cells": [{str(i): {("Ticket", None)}}], "count": 1,
                       "representative": row["row_id"]} for i, row in enumerate(rows)]
            counts = {"total": len(rows), "without_projection": 0, "quantity_only": 0,
                      "columns": ["quantity"], "groups": groups,
                      "export_revision": sha256_json("synthetic serving revision"),
                      "unresolved_value_count_status": "unavailable"}
            render = loader._candidate_fact_table
            rejected = []

            def render_with_unquoted_detail(*args, **kwargs):
                item = render(*args, **kwargs)
                if item and kwargs.get("_counts") is None:
                    label, encoded = item["snippet"].split("\n", 1)
                    table = json.loads(encoded)
                    if table["rows"]:
                        table["rows"][0]["quotes"] = []
                        item["snippet"] = label + "\n" + json.dumps(table, ensure_ascii=False)
                        rejected.append(True)
                return item

            with (patch.object(records, "catalog", return_value={"properties": {}}),
                  patch.object(records, "query_records", return_value=(rows, counts)),
                  patch.object(loader, "_candidate_fact_table", side_effect=render_with_unquoted_detail)):
                raw = loader._build_source_start_semantic_handler(bound, mail_tool=False)(args)
            self.assertTrue(rejected)
            wire = compact_evidence_for_model(raw)
            self.assertFalse(wire["citations"])
            table = json.loads(wire["evidence"][0]["snippet"].split("\n", 1)[1])
            self.assertEqual(table["rows"], [])
            self.assertEqual(table["result_set"]["shown_groups"], len(groups))
            self.assertIn("已列出完整結果集", table["disclosure"])
            self.assertIn("引用本表", table["disclosure"])
            self.assertTrue(all(g["ref"] is None for g in table["result_set"]["groups"]))
            self.assertEqual(table["unresolved_value_count_status"], "unavailable")
            self.assertNotIn("unresolved_value_count", table)
            self.assertIn("筆數未知", table["disclosure"])
