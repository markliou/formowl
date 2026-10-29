"""Synthetic candidate selection at the existing source presentation boundary."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import sha256_json
from formowl_gateway import issue56_sealed_source_loader as loader
from formowl_mail.human_uat_orchestrator import compact_evidence_for_model, evidence_citation_ids
from formowl_mail.issue56_sealed_source import load_issue56_ingestion_revision
from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
from test_issue56_uat_handler_composition import _source_start_preparation_fixture


class BoundedCandidateSelectionTests(unittest.TestCase):
    @staticmethod
    def mail(name, text, *, message="quoted-message", order="REQ-104"):
        body_hash, header_hash = (sha256_json(name + suffix) for suffix in ("-body", "-header"))
        identity = {"email_message_id": "emailmsg_synthetic_" + message,
                    "message_occurrence_id": "mailocc_synthetic_" + name,
                    "source_scope_fingerprint": sha256_json("synthetic-scope")}
        header = {**identity, "source_type": "mail_message", "citation_hash": header_hash,
                  "occurrence_lineage_fingerprint": sha256_json(name + "-header-lineage"),
                  "snippet": "[outer message headers; same occurrence]\nsubject: " + order,
                  "source_context": {"relationship": "outer_message_header", "anchor_citation_hash": body_hash}}
        return {**identity, "source_type": "mail_body_segment", "citation_hash": body_hash,
                "occurrence_lineage_fingerprint": sha256_json(name + "-body-lineage"),
                "snippet": text, "_mail_parent_header": header}

    @staticmethod
    def row(name, origin, window, *, proven=True):
        return {"citation_hash": sha256_json(name), "snippet": "Synthetic native row.",
                "occurrence_lineage_fingerprint": sha256_json(name + "-lineage"),
                "table_row": {"source_observation_id": "obs_synthetic_" + name,
                              "cells": [{"field": field, "value": value,
                                         "citation_hash": sha256_json(name + field),
                                         "source_proven_field_schema": proven,
                                         "field_truncated": False, "value_truncated": False}
                                        for field, value in (("Code", "ZX-742"), ("Origin", origin), ("Window", window))]}}

    @staticmethod
    def payload(items, *, fields=("Origin", "Window")):
        records, truncated = loader._bounded_mail_header_groups(items, limit=128)
        assert not truncated
        return {"status": "partial", "coverage": {"status": "incomplete"},
                "evidence": records, "citations": [item["citation_hash"] for item in records],
                "requested_field_coverage": {"requested_fields": list(fields), "supported_fields": [],
                                             "missing_fields": list(fields), "status": "incomplete"}}

    def select(self, staged, deferred, *, limit, fields=("Origin", "Window"), deadline=None):
        payload = self.payload(staged, fields=fields)
        original = deepcopy((payload, staged, deferred))
        result = loader._admit_source_model_envelope(
            payload, staged_items=staged, deferred_items=deferred, limit=limit,
            deadline=time.monotonic() + 2 if deadline is None else deadline,
        )
        self.assertEqual((payload, staged, deferred), original)
        display = compact_evidence_for_model(result)
        self.assertLessEqual(len(json.dumps(display, ensure_ascii=False, separators=(",", ":")).encode()), 16384)
        self.assertEqual(set(evidence_citation_ids(result)), set(evidence_citation_ids(display)))
        self.assertLessEqual(len(result["evidence"]), limit)
        return result

    def test_deferred_reply_replaces_one_duplicate_quote_with_its_own_header(self):
        copies = [self.mail(name, "REQ-104: the review is pending.") for name in ("copy-a", "copy-b")]
        reply = self.mail("reply", "REQ-104: review approved; release is 2035-04-09.", message="reply-message")
        result = self.select(copies, [reply], limit=4, fields=("review", "release"))
        self.assertIn(reply["citation_hash"], result["citations"])
        kept = [item for item in copies if item["citation_hash"] in result["citations"]]
        self.assertEqual(len(kept), 1)
        expected, _ = loader._bounded_mail_header_groups([*kept, reply], limit=4)
        self.assertCountEqual(result["evidence"], expected)
        self.assertEqual(result["coverage"]["status"], "incomplete")
        self.assertTrue(result["presentation_truncated"])

    def test_source_proven_all_requested_blank_row_can_yield_to_filled_row(self):
        blank = self.row("blank", "", "")
        filled = self.row("filled", "Northland", "2035-04-09")
        result = self.select([blank], [filled], limit=1)
        self.assertEqual(result["evidence"], [filled])
        self.assertEqual(set(evidence_citation_ids(result)), set(evidence_citation_ids(filled)))
        self.assertEqual(result["coverage"]["status"], "incomplete")
        self.assertTrue(result["presentation_truncated"])

    def test_full_envelope_loss_reconsiders_staged_reply_after_duplicate_quotes(self):
        copies = [self.mail(name, "REQ-104 pending. " + "x" * 3600) for name in ("a", "b")]
        reply = self.mail("reply", "REQ-104 approved. " + "y" * 3600, message="reply")
        staged = [*copies, reply]
        payload = self.payload(staged, fields=("release",))
        payload["coverage"]["reason"] = "Synthetic missing coverage details " + "z" * 2800
        original = deepcopy(payload)
        diagnostic = {}
        compact_evidence_for_model(payload, diagnostic=diagnostic)
        self.assertLess(len(json.dumps(payload["evidence"], ensure_ascii=False).encode()), 16384)
        self.assertEqual(diagnostic["reason_counts"]["group_byte_budget"], 1)
        result = loader._admit_source_model_envelope(
            payload, staged_items=staged, limit=6, deadline=time.monotonic() + 2,
        )
        self.assertIn(reply["citation_hash"], result["citations"])
        self.assertEqual(sum(item["citation_hash"] in result["citations"] for item in copies), 1)
        self.assertEqual(set(evidence_citation_ids(result)),
                         set(evidence_citation_ids(compact_evidence_for_model(result))))
        self.assertEqual(payload, original)
        self.assertEqual(result["coverage"], original["coverage"])
        self.assertTrue(result["presentation_truncated"])

    def test_unknown_headers_or_partial_values_are_not_proved_blank_rows(self):
        filled = self.row("filled", "Northland", "2035-04-09")
        for original in (self.row("unknown", "", "", proven=False), self.row("partial", "Southland", "")):
            with self.subTest(original=original["citation_hash"]):
                result = self.select([original], [filled], limit=1)
                self.assertEqual(result["evidence"], [original])

    def test_equal_words_from_different_orders_are_not_one_quote(self):
        orders = [self.mail("order-a", "The review is pending.", message="order-a", order="REQ-104"),
                  self.mail("order-b", "The review is pending.", message="order-b", order="REQ-205")]
        reply = self.mail("reply", "A different release is approved.", message="order-c", order="REQ-306")
        result = self.select(orders, [reply], limit=4, fields=("review", "release"))
        self.assertEqual(result["evidence"], self.payload(orders)["evidence"])

    def test_unpresentable_or_expired_replacement_keeps_original_evidence(self):
        copies = [self.mail(name, "REQ-104: the review is pending.") for name in ("copy-a", "copy-b")]
        oversized = self.mail("oversized", "x" * 17000, message="reply-message")
        result = self.select(copies, [oversized], limit=4)
        self.assertEqual(result["evidence"], self.payload(copies)["evidence"])
        reply = self.mail("reply", "REQ-104: approved.", message="reply-message")
        expired = self.select(copies, [reply], limit=4, deadline=time.monotonic() - 1)
        self.assertEqual(expired["evidence"], self.payload(copies)["evidence"])

    def test_validated_overflow_survives_an_existing_deferred_prefix_without_reread(self):
        quote = "clienta REQ-104 review pending. " + "quartz " * 700
        pending = "clienta REQ-104 awaiting review."
        reply = "clienta REQ-104 release approved for 2035-04-09."
        with tempfile.TemporaryDirectory() as directory:
            dump = json.dumps
            def archive(value, *args, **kwargs):
                if isinstance(value, dict) and value.get("archive_id") == "archive_source_start":
                    template = value["messages"][0]
                    value = {**value, "messages": [
                        {**template, "subject": "REQ-104", "message_id": "<" + name + "@example.test>",
                         "body": text, "body_hash": sha256_json(text)}
                        for name, text in (("quote", quote), ("quote", quote), ("pending", pending), ("reply", reply))]}
                return dump(value, *args, **kwargs)
            with patch("test_issue56_uat_handler_composition.json.dumps", side_effect=archive):
                fixture = _source_start_preparation_fixture(
                    Path(directory), families=("mail",),
                    # A genuine native family reserves one item; it does not match the query.
                    inline_html="<table><tr><th>Code</th><th>State</th></tr><tr><td>unrelated</td><td>open</td></tr></table>",
                )
            revision = load_issue56_ingestion_revision(fixture.directory, expected_revision_sha256=fixture.preparation_sha256)
            handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
            body = next(item for item in fixture.observations if item.text == reply.rstrip())
            target_hash = sha256_json(body.to_dict())
            seen = []
            original_scan = revision.source_records.scan_authorized_observations
            def scan(**kwargs):
                callback = kwargs["observation_callback"]
                def observe(item, scope):
                    seen.append(item.observation_id)
                    return callback(item, scope)
                # Isolate ordinary candidate retention from the separate neighbor
                # expansion policy. Real hydration and every source guard remain.
                return original_scan(**{**kwargs, "observation_callback": observe,
                                         "context_anchor_callback": lambda *_: False})
            arguments = {"query_text": "Find clienta progress", "required_terms": ["clienta"], "page_size": 4,
                         "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
                         "session_id": "synthetic-retained-candidate", "request_contract": {
                             "original_query_hash": sha256_json("Find clienta progress"),
                             "query_class": "evidence_lookup", "source_family_scope": ["mail"],
                             "requested_fields": ["release"], "maximum_claim_strength": "cited_evidence"}}
            trace = _SourcePhaseTrace({})
            clock = time.monotonic()
            with (patch.object(revision.source_records, "scan_authorized_observations", side_effect=scan) as scans,
                  patch.object(loader.time, "monotonic", return_value=clock), _source_phase_trace_scope(trace)):
                result = handler(arguments)
            self.assertEqual(scans.call_count, 1)
            self.assertEqual(seen.count(body.observation_id), 1)
            self.assertGreater(json.loads(trace.snapshot())["counters"]["deferred"], 0)
            self.assertIn(target_hash, evidence_citation_ids(compact_evidence_for_model(result)))
            self.assertEqual(result["coverage"]["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
