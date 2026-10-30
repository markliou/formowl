"""Synthetic candidate selection at the existing source presentation boundary."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_gateway import issue56_sealed_source_loader as loader
from formowl_mail.human_uat_orchestrator import compact_evidence_for_model, evidence_citation_ids
from formowl_mail.issue56_sealed_source import load_issue56_ingestion_revision
from formowl_retrieval.gateway import _SourcePhaseTrace, _source_phase_trace_scope
from test_issue56_uat_handler_composition import _source_start_preparation_fixture
import test_issue56_uat_handler_composition as source_fixture


class BoundedCandidateSelectionTests(unittest.TestCase):
    def test_attachment_numeric_multiword_phrase_stays_soft_without_weakening_separate_identifiers(self):
        phrase = "clienta rb3 gen2 frame"
        with tempfile.TemporaryDirectory() as directory:
            _, revision, _, arguments, child, _ = self.attachment_source(
                Path(directory), body_text="Cover note.",
                attachment_text="Clienta ZX-742 release date 2036-02-03.")
            target = sha256_json(child.to_dict())
            with patch.object(source_fixture.issue56_sealed_source, "issue56_reviewed_annotation_catalog",
                              return_value={"catalog_pin": sha256_json("Clienta fictional projection catalog")}):
                handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
            hint = ({target: ("clienta",)}, {"scanned_atom_count": 1, "matched_atom_count": 1,
                    "candidate_hash_count": 1, "term_hashes": (), "cap_reached": False,
                    "atom_scan_truncated": False})
            scan_source = revision.source_records.scan_authorized_observations
            def scan(**kwargs):
                kwargs.pop("additive_observation_hashes", None)
                kwargs.pop("preferred_observation_hashes", None)
                return scan_source(**{**kwargs, "context_anchor_callback": lambda *_: False})
            cases = (
                (["zx-742", phrase], "", True),
                (["zx-743", phrase], "", False),
                (["zx-742", phrase, "rb3"], "", False),
                (["zx-742", phrase], " rb3", False),
                # This whitespace term is one complete protected amount span.
                (["zx-742", phrase, "usd 742"], "", False),
                ([phrase], "", True),
            )
            for route in ("ordinary", "hinted", "reviewed"):
                for required, extra, expected in cases:
                    with self.subTest(route=route, required=required, extra=extra):
                        arguments["required_terms"] = required
                        arguments["query_text"] = "Find " + " ".join(required) + extra + " release date"
                        arguments["request_contract"]["original_query_hash"] = sha256_json(arguments["query_text"])
                        arguments["reviewed_annotation_ids"] = ["candidate_synthetic"] if route == "reviewed" else []
                        original = deepcopy(arguments)
                        with (patch.object(loader, "_server_reviewed_identity_source_hints", return_value=hint if route == "hinted" else ({}, hint[1])),
                              patch.object(loader, "_select_reviewed_annotation_sources", return_value=(("candidate_synthetic",), (target,), "clienta")),
                              patch.object(revision.source_records, "scan_authorized_observations", side_effect=scan),
                              patch.object(loader.time, "monotonic", return_value=time.monotonic())):
                            result = handler(arguments)
                        self.assertEqual(target in result["citations"], expected)
                        if "attachment_literal_policy" in result:
                            self.assertNotIn("usd 742", result["attachment_literal_policy"]["softened_required_terms"])
                        if expected:
                            self.assertEqual(result["attachment_literal_policy"]["softened_required_terms"], [phrase])
                            self.assertEqual(compact_evidence_for_model(result)["attachment_literal_policy"],
                                             result["attachment_literal_policy"])
                            paragraph = next(item for item in result["evidence"] if item["citation_hash"] == target)
                            self.assertEqual(paragraph["snippet"], child.text)
                        self.assertEqual(arguments, original)

    def test_attachment_descriptions_are_disclosed_soft_terms_without_rewriting_request(self):
        with tempfile.TemporaryDirectory() as directory:
            _, revision, _, arguments, child, parent = self.attachment_source(
                Path(directory), attachment_text="Clienta 甲社專案 ZX-742 release date 2036-02-03.")
            arguments["required_terms"] = ["ZX-742", "Clienta", "planned shipping date", "甲社專案"]
            arguments["query_text"] = "Find ZX-742 Clienta 甲社專案 planned shipping date"
            arguments["request_contract"]["original_query_hash"] = sha256_json(arguments["query_text"])
            original = deepcopy(arguments)
            for mail_tool in (False, True):
                with self.subTest(mail_tool=mail_tool):
                    handler = loader._build_source_start_semantic_handler(revision, mail_tool=mail_tool)
                    if mail_tool:
                        arguments["mail_import_session_id"] = revision.source_records.authorized_mail_import_session_ids[0]
                    with patch.object(loader.time, "monotonic", return_value=time.monotonic()):
                        result = handler(arguments)
                    self.assertIn(sha256_json(child.to_dict()), evidence_citation_ids(result))
                    policy = result["attachment_literal_policy"]
                    self.assertEqual(policy, {"source_type": "mail_attachment_text",
                                             "softened_required_terms": ["Clienta", "planned shipping date", "甲社專案"],
                                             "soft_terms_mode": "ranking_only"})
                    display = compact_evidence_for_model(result)
                    self.assertEqual(display["attachment_literal_policy"], policy)
                    self.assertLessEqual(len(json.dumps(display, ensure_ascii=False, separators=(",", ":")).encode()), 16384)
                    records = result.get("evidence", result.get("evidence_snippets"))
                    paragraph = next(item for item in records if item["citation_hash"] == sha256_json(child.to_dict()))
                    self.assertEqual(paragraph["snippet"], child.text)
                    self.assertEqual(paragraph["source_context"]["parent_attachment_observation_hash"], sha256_json(parent.to_dict()))
                    self.assertEqual(arguments["required_terms"], original["required_terms"])
                    self.assertEqual(arguments["request_contract"], original["request_contract"])

    def test_attachment_without_identifier_uses_descriptions_as_soft_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, handler, arguments, child, _ = self.attachment_source(Path(directory))
            arguments["required_terms"] = ["clienta", "planned shipping date"]
            arguments["query_text"] = "Find clienta planned shipping date"
            arguments["request_contract"]["original_query_hash"] = sha256_json(arguments["query_text"])
            with patch.object(loader.time, "monotonic", return_value=time.monotonic()):
                result = handler(arguments)
            self.assertIn(sha256_json(child.to_dict()), result["citations"])
            self.assertEqual(result["attachment_literal_policy"]["softened_required_terms"], arguments["required_terms"])

    def test_attachment_soft_terms_do_not_relax_complete_identifier_literals_or_hints(self):
        with tempfile.TemporaryDirectory() as directory:
            _, revision, handler, arguments, child, _ = self.attachment_source(
                Path(directory), attachment_text="Clienta ZX-742 ZX-ALPHA 742 release date 2036-02-03.")
            with patch.object(source_fixture.issue56_sealed_source, "issue56_reviewed_annotation_catalog",
                              return_value={"catalog_pin": sha256_json("Clienta fictional projection catalog")}):
                handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
            target = sha256_json(child.to_dict())
            # A reviewed identity hint remains independently source-validated.
            hint = ({target: ("clienta",)}, {"scanned_atom_count": 1, "matched_atom_count": 1,
                    "candidate_hash_count": 1, "term_hashes": (), "cap_reached": False,
                    "atom_scan_truncated": False})
            scan_source = revision.source_records.scan_authorized_observations
            def scan(**kwargs):
                # This fictional reader has no runtime SQL helper. Inject only
                # projection hints, retaining its normal guarded hydration.
                kwargs.pop("additive_observation_hashes", None)
                kwargs.pop("preferred_observation_hashes", None)
                return scan_source(**kwargs)
            for route in ("ordinary", "hinted", "reviewed"):
                arguments["reviewed_annotation_ids"] = ["candidate_synthetic"] if route == "reviewed" else []
                for code in ("zx-742", "zx-74", "zx-7429", "zx-743", "7429", "zx-alpha", "zx-alph", "742", "74"):
                    with self.subTest(route=route, code=code):
                        arguments["query_text"] = f"Find Clienta {code} planned shipping date"
                        arguments["required_terms"] = [code, "planned shipping date"]
                        arguments["request_contract"]["original_query_hash"] = sha256_json(arguments["query_text"])
                        with (patch.object(loader, "_server_reviewed_identity_source_hints", return_value=hint if route == "hinted" else ({}, hint[1])),
                              # Exercise projection after reviewed source selection;
                              # this synthetic nomination does not prove governance.
                              patch.object(loader, "_select_reviewed_annotation_sources", return_value=(("candidate_synthetic",), (target,), code)),
                              patch.object(revision.source_records, "scan_authorized_observations", side_effect=scan),
                              patch.object(loader.time, "monotonic", return_value=time.monotonic())):
                            result = handler(arguments)
                        self.assertEqual(target in result["citations"], code in {"zx-742", "zx-alpha", "742"})
                        self.assertIn("attachment_literal_policy", result)
                        self.assertEqual(result["attachment_literal_policy"]["softened_required_terms"], ["planned shipping date"])
            arguments.pop("reviewed_annotation_ids")
            # The ordinary reader still has its original bounded read/time arguments.
            clock = time.monotonic()
            with (patch.object(revision.source_records, "scan_authorized_observations", wraps=revision.source_records.scan_authorized_observations) as scan_call,
                  patch.object(loader.time, "monotonic", return_value=clock)):
                handler(arguments)
            self.assertLessEqual(scan_call.call_args.kwargs["max_observations"], 8192)
            self.assertLessEqual(scan_call.call_args.kwargs["deadline_monotonic"] - clock,
                                 loader.SOURCE_START_EVIDENCE_TIME_BUDGET_MS / 1000)
            self.assertEqual(loader.SOURCE_EVIDENCE_TIME_BUDGET_MS, 500)

    def test_hinted_attachment_rejects_separator_extended_codes_but_accepts_terminal_period(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments, _, _ = self.attachment_source(
                Path(directory), body_text="Cover note.",
                attachment_text="Clienta ZX-742-ALPHA release date.\n\nClienta ZX-742.ALPHA release date.\n\n"
                                "Clienta ZX-742_ALPHA release date.\n\nClienta ZX-742. release date.")
            with patch.object(source_fixture.issue56_sealed_source, "issue56_reviewed_annotation_catalog",
                              return_value={"catalog_pin": sha256_json("Clienta fictional projection catalog")}):
                handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
            children = [item for item in fixture.observations if item.observation_type == "paragraph"]
            hashes = {sha256_json(item.to_dict()) for item in children}
            arguments["query_text"] = "Find Clienta ZX-742 planned shipping date"
            arguments["required_terms"] = ["zx-742", "planned shipping date"]
            arguments["request_contract"]["original_query_hash"] = sha256_json(arguments["query_text"])
            hint = ({key: ("clienta",) for key in hashes}, {"scanned_atom_count": 4, "matched_atom_count": 4,
                    "candidate_hash_count": 4, "term_hashes": (), "cap_reached": False,
                    "atom_scan_truncated": False})
            scan_source = revision.source_records.scan_authorized_observations
            def scan(**kwargs):
                kwargs.pop("additive_observation_hashes", None)
                kwargs.pop("preferred_observation_hashes", None)
                return scan_source(**{**kwargs, "context_anchor_callback": lambda *_: False})
            literal = next(item for item in children if "ZX-742. release" in item.text)
            for route in ("hinted", "reviewed"):
                with self.subTest(route=route):
                    arguments["reviewed_annotation_ids"] = ["candidate_synthetic"] if route == "reviewed" else []
                    with (patch.object(loader, "_server_reviewed_identity_source_hints", return_value=hint),
                          patch.object(loader, "_select_reviewed_annotation_sources", return_value=(("candidate_synthetic",), tuple(hashes), "zx-742")),
                          patch.object(revision.source_records, "scan_authorized_observations", side_effect=scan),
                          patch.object(loader.time, "monotonic", return_value=time.monotonic())):
                        result = handler(arguments)
                    self.assertEqual(set(result["citations"]) & hashes, {sha256_json(literal.to_dict())})

    def test_all_fields_missing_auto_exact_keeps_ordinary_attachment_soft_gate_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            _, revision, _, arguments, child, _ = self.attachment_source(
                Path(directory), attachment_text="Clienta ZX-742 release date 2036-02-03.")
            arguments["query_text"] = "Find Clienta ZX-742 planned shipping date"
            arguments["required_terms"] = ["zx-742", "planned shipping date"]
            arguments["request_contract"]["original_query_hash"] = sha256_json(arguments["query_text"])
            # Isolate the existing exact-first/fallback seam; source hydration
            # below stays real and sealed. Native row semantics are not mocked
            # into a claim of table support.
            exact_lookup = SimpleNamespace(_columns=[{"field": "release date", "inline_table": True}],
                                           capability_fields=(), capability_providers=())
            budgets = []
            def exact(_revision, **kwargs):
                self.assertEqual(kwargs["required_terms"], tuple(sorted(arguments["required_terms"])))
                budgets.append(kwargs["source_budget"])
                kwargs["source_budget"]["reads"] += 1
                return {"status": "pending_review", "requested_field_coverage": {"supported_fields": []}}
            clock = time.monotonic()
            with (patch.object(loader, "_IngestionExactCellLookup", return_value=exact_lookup),
                  patch.object(loader, "_exact_column_applicable", return_value=True)):
                handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
                with (patch.object(loader, "_execute_source_start_table", side_effect=exact) as native,
                      patch.object(revision.source_records, "scan_authorized_observations", wraps=revision.source_records.scan_authorized_observations) as scan,
                      patch.object(loader.time, "monotonic", return_value=clock)):
                    result = handler(arguments)
            self.assertEqual(native.call_count, 1)
            self.assertEqual(scan.call_count, 1)
            self.assertIn(sha256_json(child.to_dict()), result["citations"])
            self.assertEqual(result["attachment_literal_policy"]["softened_required_terms"], ["planned shipping date"])
            self.assertTrue(result["query_agent"]["exact_first"]["all_requested_fields_missing"])
            self.assertEqual(scan.call_args.kwargs["max_observations"], 8191)
            self.assertLessEqual(scan.call_args.kwargs["deadline_monotonic"], budgets[0]["deadline"])

    def test_attachment_descriptive_phrase_changes_bounded_selection_without_new_reads(self):
        weak = "Clienta ZX-742 release date 2036-02-03." + " quartz" * 1150
        strong = "Clienta ZX-742 release date 2036-02-03. planned shipping detail." + " quartz" * 1150
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments, _, _ = self.attachment_source(
                Path(directory), body_text="Cover note.", attachment_text=weak + "\n\n" + strong)
            weak_child = next(item for item in fixture.observations if item.text == weak)
            strong_child = next(item for item in fixture.observations if item.text == strong)
            arguments["required_terms"] = ["zx-742", "clienta"]
            scan_source = revision.source_records.scan_authorized_observations
            def scan(**kwargs):
                return scan_source(**{**kwargs, "context_anchor_callback": lambda *_: False})
            for descriptive, fields in ((False, ["release date"]), (True, ["release date"])):
                with self.subTest(descriptive=descriptive, fields=fields):
                    arguments["required_terms"] = ["zx-742", "clienta"]
                    arguments["request_contract"]["requested_fields"] = fields
                    if descriptive:
                        arguments["required_terms"].append("planned shipping detail")
                    arguments["query_text"] = "Find " + " ".join(arguments["required_terms"]) + " release date"
                    arguments["request_contract"]["original_query_hash"] = sha256_json(arguments["query_text"])
                    trace = _SourcePhaseTrace({})
                    with (patch.object(revision.source_records, "scan_authorized_observations", side_effect=scan) as scans,
                          patch.object(loader.time, "monotonic", return_value=time.monotonic()),
                          _source_phase_trace_scope(trace)):
                        result = handler(arguments)
                    self.assertEqual(scans.call_count, 1)
                    target = strong_child if descriptive else weak_child
                    self.assertIn(sha256_json(target.to_dict()), result["citations"])
                    self.assertEqual(len(result["evidence"]), 2)
                    events = json.loads(trace.snapshot())["details"]
                    self.assertTrue(any(event.get("name") == "admitted" and event.get("observation_hash") == sha256_json(weak_child.to_dict())
                                        for event in events))

    def test_descriptive_softening_does_not_change_plain_mail_or_document_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = _source_start_preparation_fixture(
                Path(directory), families=("mail", "document_text"),
                mail_text="Clienta ZX-742 release date 2036-02-03.",
                document_text="Clienta ZX-742 release date 2036-02-03.")
            revision = load_issue56_ingestion_revision(fixture.directory, expected_revision_sha256=fixture.preparation_sha256)
            handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
            arguments = {"query_text": "Find Clienta ZX-742 planned shipping date", "required_terms": ["zx-742", "planned shipping date"],
                         "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
                         "session_id": "synthetic-strict-description", "request_contract": {
                             "original_query_hash": sha256_json("Find Clienta ZX-742 planned shipping date"),
                             "query_class": "evidence_lookup", "source_family_scope": ["mail", "document_text"],
                             "requested_fields": ["release date"], "maximum_claim_strength": "cited_evidence"}}
            with patch.object(loader.time, "monotonic", return_value=time.monotonic()):
                result = handler(arguments)
            self.assertEqual(result["citations"], [])
            self.assertNotIn("attachment_literal_policy", result)

    @staticmethod
    def attachment_source(root, *, oversized=False, dated=False, body_text=None, attachment_text=None):
        # Fill the synthetic extractor's inventory identity before ingestion
        # writes/seals it. The text parser and source guards remain real.
        run = source_fixture.run_ingestion_job
        def ingest(**kwargs):
            adapter = kwargs["extractor_adapters"][0]
            extract = adapter.extract
            def bound_parent(extraction_input):
                result = extract(extraction_input)
                message = next(item for item in result.observations if item.observation_type == "email_message")
                result.observations[:] = [
                    replace(item, payload={**item.payload,
                                           "source_inventory_item_id": "synthetic-native-table",
                                           "message_fingerprint": message.payload["message_fingerprint"]})
                    if item.observation_type == "email_attachment_occurrence" else item
                    for item in result.observations
                ]
                return result
            with patch.object(adapter, "extract", side_effect=bound_parent):
                return run(**kwargs)
        dump = json.dumps
        def archive(value, *args, **kwargs):
            if dated and isinstance(value, dict) and value.get("archive_id") == "archive_source_start":
                template = value["messages"][0]
                value = {**value, "messages": [
                    {**template, "message_id": "<" + name + "@example.test>", "sent_at": date,
                     "body": text, "body_hash": sha256_json(text)}
                    for name, date, text in (
                        ("new-attachment", "2030-03-01T08:00:00+08:00", "Cover note."),
                        ("old-body", "2020-01-01T00:00:00+00:00", "Clienta pending. Quoted Date: 2099-01-01."),
                        ("middle-body", "2025-01-01T00:00:00+00:00", "Clienta acknowledged."),
                    )]}
            return dump(value, *args, **kwargs)
        text = attachment_text or "Clienta release date 2036-02-03." + (" quartz" * 2600 if oversized else "")
        with (patch.object(source_fixture, "run_ingestion_job", side_effect=ingest),
              patch.object(source_fixture.json, "dumps", side_effect=archive)):
            fixture = _source_start_preparation_fixture(
                root, families=("mail",), mail_text=body_text or "Clienta request is pending.",
                attachment_content=(text.encode(), "text/plain"),
            )
        revision = load_issue56_ingestion_revision(fixture.directory, expected_revision_sha256=fixture.preparation_sha256)
        handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
        arguments = {"query_text": "Find Clienta release date", "required_terms": ["clienta"], "page_size": 2,
                     "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
                     "session_id": "synthetic-attachment-retention", "request_contract": {
                         "original_query_hash": sha256_json("Find Clienta release date"),
                         "query_class": "evidence_lookup", "source_family_scope": ["mail"],
                         "requested_fields": ["release date"], "maximum_claim_strength": "cited_evidence"}}
        child = next(item for item in fixture.observations if item.observation_type == "paragraph")
        parent = next(item for item in fixture.observations if item.observation_type == "email_attachment_occurrence")
        return fixture, revision, handler, arguments, child, parent

    def test_context_byte_overflow_keeps_more_complete_field_labels(self):
        filler = " quartz" * 1150
        weak = "Clienta 甲社專案 ZX-742 742 release window delivery." + filler
        target = "Clienta 甲社專案 ZX-742 742 release date 2036-02-03." + filler
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments, _, parent = self.attachment_source(
                Path(directory), body_text=weak, attachment_text=weak + "\n\n" + target)
            arguments["page_size"] = 6
            arguments["query_text"] = "Find Clienta ZX-742 742 release date"
            arguments["required_terms"] = ["clienta", "zx-742", "742"]
            arguments["request_contract"]["requested_fields"] = ["release date", "delivery window"]
            child = next(item for item in fixture.observations if item.text == target)
            target_hash = sha256_json(child.to_dict())
            captures, seen = [], []
            original_scan = revision.source_records.scan_authorized_observations
            original_envelope = loader._admit_source_model_envelope
            def scan(**kwargs):
                callback = kwargs["observation_callback"]
                def observe(item, scope):
                    seen.append(item.observation_id)
                    return callback(item, scope)
                return original_scan(**{**kwargs, "observation_callback": observe,
                                        "context_anchor_callback": lambda *_: False})
            def envelope(payload, **kwargs):
                captures.append(deepcopy(kwargs))
                return original_envelope(payload, **kwargs)
            trace = _SourcePhaseTrace({})
            with (patch.object(revision.source_records, "scan_authorized_observations", side_effect=scan) as scans,
                  patch.object(loader, "_admit_source_model_envelope", side_effect=envelope),
                  patch.object(loader.time, "monotonic", return_value=time.monotonic()),
                  _source_phase_trace_scope(trace)):
                result = handler(arguments)
            events = json.loads(trace.snapshot())["details"]
            self.assertTrue(any(item.get("name") == "context_limit" and item.get("observation_hash") == target_hash
                                for item in events))
            cached = captures[-1]["deferred_items"]
            self.assertIn(target_hash, {item["citation_hash"] for item in cached})
            self.assertEqual({word for kind, word in captures[-1]["selection_hits"][target_hash] if kind == -1},
                             {"zx-742", "742"})
            cached_records, truncated = loader._bounded_mail_header_groups(cached, limit=6)
            self.assertFalse(truncated)
            self.assertLessEqual(len(json.dumps(cached_records, ensure_ascii=False).encode()), 16384)
            self.assertLessEqual(len(captures[-1]["selection_hits"]), 128)
            self.assertEqual(scans.call_count, 1)
            self.assertEqual(seen.count(child.observation_id), 1)
            self.assertIn(target_hash, result["citations"])
            paragraph = next(item for item in result["evidence"] if item["citation_hash"] == target_hash)
            self.assertEqual(paragraph["snippet"], target)
            self.assertEqual(paragraph["source_context"]["parent_attachment_observation_hash"], sha256_json(parent.to_dict()))
            header = next(item for item in result["evidence"] if item["citation_hash"] == paragraph["mail_header_citation_hash"])
            self.assertEqual(header["source_context"]["anchor_citation_hash"], target_hash)
            display = compact_evidence_for_model(result)
            self.assertEqual(set(evidence_citation_ids(result)), set(evidence_citation_ids(display)))
            self.assertLessEqual(len(json.dumps(display, ensure_ascii=False, separators=(",", ":")).encode()), 16384)
            self.assertEqual(result["query_agent"]["context_bundle"]["missing_field_hashes"],
                             [sha256_json(field) for field in arguments["request_contract"]["requested_fields"]])
            self.assertEqual(result["coverage"]["status"], "incomplete")

    def test_identifier_and_whole_label_coverage_precede_fragmented_field_words(self):
        staged = self.mail("fragmented", "clienta ZX-742 release window delivery.")
        incoming = self.mail("covered", "clienta ZX-742 742 release date.", message="covered")
        token_hits = {(0, "release"), (1, "window"), (1, "delivery")}
        # Private hit namespaces encode distinct literal identifiers (-1) and
        # complete field labels (-2); positive indices retain frozen field tokens.
        for signals in (
            ({(-1, "zx-742")}, {(-1, "zx-742"), (-1, "742")}),
            (set(), {(-2, "release date")}),
        ):
            with self.subTest(signals=signals):
                payload = self.payload([staged])
                hits = {staged["citation_hash"]: token_hits | signals[0],
                        incoming["citation_hash"]: {(0, "release"), (0, "date")} | signals[1]}
                result = loader._admit_source_model_envelope(
                    payload, staged_items=[staged], deferred_items=[incoming], limit=2,
                    deadline=time.monotonic() + 2, selection_hits=hits,
                    overflow_hashes={incoming["citation_hash"]})
                self.assertIn(incoming["citation_hash"], result["citations"])
                self.assertNotIn(staged["citation_hash"], result["citations"])
                self.assertEqual(set(evidence_citation_ids(result)),
                                 set(evidence_citation_ids(compact_evidence_for_model(result))))

    def test_attachment_overflow_replaces_earlier_body_as_one_bound_parent_unit_without_reread(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, revision, handler, arguments, child, parent = self.attachment_source(Path(directory))
            target_hash = sha256_json(child.to_dict())
            body = next(item for item in fixture.observations if item.observation_type == "email_body_segment")
            trace = _SourcePhaseTrace({})
            original_scan = revision.source_records.scan_authorized_observations
            seen = []
            def scan(**kwargs):
                callback = kwargs["observation_callback"]
                def observe(item, scope):
                    seen.append(item.observation_id)
                    return callback(item, scope)
                return original_scan(**{**kwargs, "observation_callback": observe})
            with (patch.object(revision.source_records, "scan_authorized_observations", side_effect=scan) as scans,
                  patch.object(loader.time, "monotonic", return_value=time.monotonic()), _source_phase_trace_scope(trace)):
                result = handler(arguments)
            events = json.loads(trace.snapshot())["details"]
            self.assertTrue(any(x.get("name") == "admitted" and x.get("observation_hash") == sha256_json(body.to_dict()) for x in events))
            self.assertTrue(any(x.get("name") == "context_limit" and x.get("observation_hash") == target_hash for x in events))
            self.assertEqual(scans.call_count, 1)
            self.assertEqual(seen.count(child.observation_id), 1)
            self.assertIn(target_hash, result["citations"])
            self.assertNotIn(sha256_json(body.to_dict()), result["citations"])
            evidence = result["evidence"]
            self.assertEqual(len(evidence), 2)
            paragraph = next(item for item in evidence if item["citation_hash"] == target_hash)
            header = next(item for item in evidence if item["citation_hash"] == paragraph["mail_header_citation_hash"])
            self.assertEqual(paragraph["snippet"], child.text)
            self.assertEqual(paragraph["source_context"]["parent_attachment_observation_hash"], sha256_json(parent.to_dict()))
            self.assertEqual(header["source_context"]["parent_attachment_observation_hash"], sha256_json(parent.to_dict()))
            self.assertEqual(header["source_context"]["anchor_citation_hash"], target_hash)
            self.assertEqual(header["message_occurrence_id"], paragraph["message_occurrence_id"])
            self.assertEqual(paragraph["occurrence_lineage_fingerprint"], loader._attachment_child_lineages(
                {child.observation_id: child, parent.observation_id: parent})[child.observation_id].lineage_fingerprint)
            self.assertEqual(set(evidence_citation_ids(result)), set(evidence_citation_ids(compact_evidence_for_model(result))))
            self.assertTrue(result["presentation_truncated"])
            self.assertEqual(result["coverage"]["status"], "incomplete")

    def test_attachment_reservoir_does_not_publish_missing_parent_or_invalid_child_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            _, revision, handler, arguments, child, _ = self.attachment_source(Path(directory))
            target_hash = sha256_json(child.to_dict())
            original_scan = revision.source_records.scan_authorized_observations
            def missing_parent(**kwargs):
                callback = kwargs["observation_callback"]
                def observe(item, scope):
                    if item.observation_type == "email_attachment_occurrence":
                        return True
                    return callback(item, scope)
                return original_scan(**{**kwargs, "observation_callback": observe})
            with (patch.object(revision.source_records, "scan_authorized_observations", side_effect=missing_parent),
                  patch.object(loader.time, "monotonic", return_value=time.monotonic())):
                result = handler(arguments)
            self.assertNotIn(target_hash, result["citations"])
            # Fault-inject after hydration so this checks the projection's real
            # lineage guard independently of the earlier sealed-hash guard.
            original_scan = revision.source_records.scan_authorized_observations
            def broken_lineage(**kwargs):
                callback = kwargs["observation_callback"]
                def observe(item, scope):
                    if item.observation_id == child.observation_id:
                        item = replace(item, payload={**item.payload, "lineage": {
                            **item.payload["lineage"], "parent_asset_id": "asset_synthetic_mismatch"}})
                    return callback(item, scope)
                return original_scan(**{**kwargs, "observation_callback": observe})
            with (patch.object(revision.source_records, "scan_authorized_observations", side_effect=broken_lineage),
                  patch.object(loader.time, "monotonic", return_value=time.monotonic())):
                with self.assertRaisesRegex(ContractValidationError, "attachment text source hash/parent binding"):
                    handler(arguments)

    def test_attachment_reservoir_keeps_original_when_complete_attachment_cannot_fit(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture, _, handler, arguments, child, _ = self.attachment_source(Path(directory), oversized=True)
            self.assertGreater(len(child.text.encode()), 16384)
            with patch.object(loader.time, "monotonic", return_value=time.monotonic()):
                result = handler(arguments)
            self.assertNotIn(sha256_json(child.to_dict()), result["citations"])
            body = next(item for item in fixture.observations if item.observation_type == "email_body_segment")
            self.assertIn(sha256_json(body.to_dict()), result["citations"])

    def test_newer_zero_score_attachment_survives_reservoir_and_final_acceptance(self):
        import hashlib
        from formowl_mail.issue56_sealed_source import bind_mail_date_priority, mail_date_priority_scope
        with tempfile.TemporaryDirectory() as directory:
            _, revision, handler, arguments, child, _ = self.attachment_source(Path(directory), dated=True)
            target = sha256_json(child.to_dict())
            arguments["request_contract"]["requested_fields"] = ["產地"]  # Every candidate has zero field tokens.
            original_scan = revision.source_records.scan_authorized_observations
            original_envelope = loader._admit_source_model_envelope
            for recent in (False, True):
                prompt = "Clienta 最後一次出貨的產地" if recent else "Clienta 的產地"
                arguments["request_contract"]["original_query_hash"] = "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()
                public = {k: v for k, v in arguments.items() if k not in {"requester_user_id", "workspace_id", "session_id"}}
                binding = bind_mail_date_priority(user_text=prompt, arguments=public, tool_name="query_effective_graph_view")
                seen, captures = [], []
                def scan(**kwargs):
                    callback = kwargs["observation_callback"]
                    def observe(item, scope):
                        seen.append(item.observation_id)
                        return callback(item, scope)
                    return original_scan(**{**kwargs, "observation_callback": observe,
                                            "context_anchor_callback": lambda *_: False})
                def envelope(payload, **kwargs):
                    captures.append(deepcopy(kwargs))
                    return original_envelope(payload, **kwargs)
                with (mail_date_priority_scope(binding),
                      patch.object(revision.source_records, "scan_authorized_observations", side_effect=scan) as scans,
                      patch.object(revision.source_records, "scan_date_ordered_mail", side_effect=AssertionError("no new date scan")),
                      patch.object(loader, "_admit_source_model_envelope", side_effect=envelope),
                      patch.object(loader.time, "monotonic", return_value=time.monotonic())):
                    result = handler(arguments)
                self.assertEqual(scans.call_count, 1)
                self.assertEqual(seen.count(child.observation_id), 1)
                if not recent:
                    self.assertNotIn(target, result["citations"])
                    continue
                self.assertIn(target, result["citations"])
                self.assertIn(target, {x["citation_hash"] for x in captures[-1]["deferred_items"]})
                self.assertTrue(all(not v for v in captures[-1]["selection_hits"].values()))
                self.assertLessEqual(len(captures[-1]["outer_dates"]), 128)
                paragraph = next(x for x in result["evidence"] if x["citation_hash"] == target)
                self.assertEqual(paragraph["snippet"], child.text)
                date_key = (target, paragraph["source_scope_fingerprint"], paragraph["message_occurrence_id"],
                            paragraph["occurrence_lineage_fingerprint"])
                self.assertEqual(captures[-1]["outer_dates"][date_key], "2030-03-01T00:00:00.000000+00:00")
                self.assertEqual(len(result["evidence"]), 2)
                self.assertEqual(set(evidence_citation_ids(result)), set(evidence_citation_ids(compact_evidence_for_model(result))))
                self.assertNotIn("latest_claim_verified", json.dumps(result))
                self.assertNotIn("outer_dates", json.dumps(result))
                self.assertEqual(result["coverage"]["status"], "incomplete")

    def test_recency_secondary_key_preserves_scores_stability_and_guards(self):
        old = self.mail("old", "Clienta source.", message="old")
        new = self.mail("new", "Clienta source.", message="new")
        def identity(item):
            return (item["citation_hash"], item["source_scope_fingerprint"],
                    item["message_occurrence_id"], item["occurrence_lineage_fingerprint"])
        for variant in ("newer", "higher_old_score", "same_date", "unknown", "wrong_lineage", "expired", "oversized", "native"):
            with self.subTest(variant=variant):
                incoming = deepcopy(new)
                staged = [old]
                dates = {identity(old): "2020-01-01T00:00:00.000000+00:00",
                         identity(new): "2030-01-01T00:00:00.000000+00:00"}
                hits = {old["citation_hash"]: set(), new["citation_hash"]: set()}
                if variant == "higher_old_score":
                    hits[old["citation_hash"]] = {(0, "source")}
                if variant == "same_date":
                    dates[identity(new)] = dates[identity(old)]
                if variant == "unknown":
                    dates = {}
                if variant == "wrong_lineage":
                    incoming["occurrence_lineage_fingerprint"] = sha256_json("different-source-binding")
                if variant == "oversized":
                    incoming["snippet"] += "x" * 17000
                if variant == "native":
                    staged.append(self.row("fixed", "Northland", "2035-04-09"))
                payload = self.payload(staged)
                original = deepcopy((payload, staged, incoming, dates))
                result = loader._admit_source_model_envelope(
                    payload, staged_items=staged, deferred_items=[incoming], limit=3 if variant == "native" else 2,
                    deadline=time.monotonic() + (-1 if variant == "expired" else 10),
                    selection_hits=hits, overflow_hashes={incoming["citation_hash"]}, outer_dates=dates,
                )
                self.assertEqual((payload, staged, incoming, dates), original)
                if variant == "newer":
                    self.assertIn(new["citation_hash"], result["citations"])
                    self.assertNotIn(old["citation_hash"], result["citations"])
                else:
                    self.assertEqual(result, payload)

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
