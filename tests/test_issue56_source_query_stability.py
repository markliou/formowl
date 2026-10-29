"""Synthetic bounded-source scheduling regressions; no live sources/providers."""

from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
import test_issue56_uat_handler_composition as fixtures
from formowl_contract import ContractValidationError, sha256_json
from formowl_gateway import issue56_sealed_source_loader as loader
from formowl_mail.import_workflow import CompletedIngestionJobAuthority
from formowl_mail.issue56_sealed_source import load_issue56_ingestion_revision
from formowl_mail.query import RevisionOwnedMailSourceScan
from formowl_retrieval.gateway import source_evidence_query_terms_scope
from formowl_retrieval.gateway import _SourcePhaseTrace, _SOURCE_PHASE_TRACE, _source_phase_trace_scope
from scripts.issue56_source_native_lookup import build_lookup


class MailDatePriorityTests(unittest.TestCase):
    def prepare_recent(self, dates, *, second_dates=None, identifier="Clienta", topic="甲社", bodies=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        original = json.dumps
        archive_count = [0]

        def archive(value, *args, **kwargs):
            if isinstance(value, dict) and value.get("archive_id") == "archive_source_start":
                template = value["messages"][0]
                current_dates = second_dates if archive_count[0] and second_dates is not None else dates
                archive_count[0] += 1
                value = {**value, "messages": [
                    {**template, "message_id": f"<clienta-{i}@example.test>",
                     "sent_at": date, "body": bodies[i] if bodies is not None else f"{identifier} {topic} status {i}",
                     "body_hash": sha256_json(bodies[i] if bodies is not None else f"{identifier} {topic} status {i}")}
                    for i, date in enumerate(current_dates)
                ]}
            return original(value, *args, **kwargs)

        with patch.object(fixtures.json, "dumps", side_effect=archive):
            fixture = fixtures._source_start_preparation_fixture(
                root, families=("mail", "mail_other") if second_dates is not None else ("mail",))
        output = root / "lookup"
        build_lookup(directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                     output_directory=output)
        dated = root / "dated"
        build_lookup(directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                     output_directory=dated, base_lookup_directory=output, mail_message_dates_only=True)
        for name in ("source-lookup.sqlite", "source-lookup-manifest.json"):
            shutil.copyfile(dated / name, fixture.directory / name)
        revision = load_issue56_ingestion_revision(fixture.directory,
                                                  expected_revision_sha256=fixture.preparation_sha256)
        self.addCleanup(revision.source_records.runtime_store.close)
        prompt = f"查詢郵件 {identifier} {topic}的最新進度"
        arguments = {
            "query_text": f"{identifier} {topic} status", "required_terms": [identifier, topic],
            "requester_user_id": loader.APPROVER_ACTOR, "workspace_id": loader.WORKSPACE_ID,
            "session_id": "synthetic-recency", "page_size": 4,
            "request_contract": {"original_query_hash": "sha256:" + __import__("hashlib").sha256(prompt.encode()).hexdigest(),
                                 "query_class": "evidence_lookup", "source_family_scope": ["mail"],
                                 "requested_fields": ["status"], "maximum_claim_strength": "cited_evidence"},
        }
        return revision, prompt, arguments

    def run_recent(self, revision, prompt, arguments):
        from formowl_mail.issue56_sealed_source import bind_mail_date_priority, mail_date_priority_scope
        public = {key: value for key, value in arguments.items()
                  if key not in {"requester_user_id", "workspace_id", "session_id"}}
        binding = bind_mail_date_priority(user_text=prompt, arguments=public,
                                         tool_name="query_effective_graph_view")
        self.assertIsNotNone(binding)
        with mail_date_priority_scope(binding):
            return loader._build_source_start_semantic_handler(revision, mail_tool=False)(arguments)

    def test_final_provider_evidence_is_newest_and_unknown_date_blocks_latest_claim(self):
        revision, prompt, arguments = self.prepare_recent([
            "2026-01-01T00:00:00+00:00", "2026-01-02T01:00:00+09:00", "2026-01-01T23:00:00+00:00",
        ], identifier="ACME-421")
        result = self.run_recent(revision, prompt, arguments)
        recovery = result["query_agent"]["context_bundle"]["source_recovery"]
        date = recovery["mail_date_priority"]
        self.assertTrue(date["sql_complete"])
        self.assertEqual(date["matching_occurrence_count"], 3)
        self.assertEqual(date["selected_date"], "2026-01-01T23:00:00.000000+00:00")
        self.assertEqual(result["evidence"][0]["mail_date_priority"]["outer_message_date"], date["selected_date"])
        self.assertIn("status 2", result["evidence"][0]["snippet"])
        self.assertFalse(date["predicate_coverage_verified"])
        self.assertFalse(date["latest_claim_verified"])
        self.assertEqual(date["claim_scope"], "在已查到並驗證的相符郵件中，日期最新的一封")
        self.assertIn("索引分詞可能漏掉郵件", date["coverage_note"])
        self.assertEqual(result["status"], "partial")
        self.assertFalse(date["authored_event_time_verified"])
        from formowl_mail.human_uat_orchestrator import compact_evidence_for_model
        compact = compact_evidence_for_model(result)
        self.assertLessEqual(len(json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode()), 16 * 1024)
        self.assertEqual(compact["evidence"][0]["citation_hash"], result["evidence"][0]["citation_hash"])
        self.assertIn(date["selected_parent_citation_hash"], compact["citations"])
        self.assertIn("索引分詞可能漏掉郵件", compact["evidence"][0]["snippet"])
        arguments["page_size"] = 1  # An intact body+header group cannot fit.
        result = self.run_recent(revision, prompt, arguments)
        final = result["query_agent"]["context_bundle"]["source_recovery"]["mail_date_priority"]
        self.assertFalse(final["latest_claim_verified"])
        self.assertFalse(final["selected_message_presented"])
        self.assertIsNone(final["selected_date"])

    def test_context_token_antichain_recovers_literal_match_and_rejects_newer_nonmatch(self):
        from formowl_core import load_issue56_target_mail_tokenizer_profile
        from formowl_contract import stable_resource_contract_id
        from formowl_mail.query import _source_mail_observation_match
        # The fixture occurrence ID excludes body/Date. Put a same-Date
        # rejection before the matching body in its deterministic tie order.
        order = [stable_resource_contract_id("mailocc", "MailMessageOccurrence", {
            "archive_id": "archive_source_start", "mailbox_id": "mailbox_source_start",
            "folder_path_hash": sha256_json("inbox"), "message_id": f"<clienta-{i}@example.test>",
            "message_index": i + 1,
        }) for i in range(2)]
        matching_index = max(range(2), key=lambda i: order[i])
        bodies = ["Clienta 甲社標籤 別項籤機 status" for _ in range(3)]
        bodies[matching_index] = "Clienta 甲社標籤機 status"
        revision, prompt, arguments = self.prepare_recent(
            ["2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"],
            topic="甲社標籤機", bodies=bodies)
        arguments["required_terms"] = ["Clienta", "標籤機"]
        profile = load_issue56_target_mail_tokenizer_profile()
        self.assertIn("標籤機", profile.analyze("標籤機").tokens)
        lookup = revision.source_records.runtime_store
        bodies = lookup._connection.execute(
            "SELECT observation_hash FROM occurrence_helpers WHERE observation_type='email_body_segment'").fetchall()
        matched = []
        for (key,) in bodies:
            helper = lookup.helper_for_hash(key)
            authority = revision.source_records._authority_for_helper(helper)
            item = authority.load_indexed_observation(helper["observation_id"], expected_observation_hash=key,
                                                       expected_job_fingerprint=authority.job_fingerprint)
            present = {row[0] for row in lookup._connection.execute(
                "SELECT token FROM postings WHERE observation_hash=?", (key,))}
            self.assertNotIn("標籤機", present)
            self.assertTrue({"標籤", "籤機"}.issubset(present))
            matched.append(_source_mail_observation_match(
                item, query_terms=set(), required_terms=("clienta", "標籤機"),
                protected_query_tokens=set(), tokenizer_profile=profile) is not None)
        self.assertEqual(sorted(matched), [False, False, True])
        result = self.run_recent(revision, prompt, arguments)
        date = result["query_agent"]["context_bundle"]["source_recovery"]["mail_date_priority"]
        self.assertEqual(date["candidate_occurrence_count"], 3)
        self.assertEqual(date["matching_occurrence_count"], 1)
        self.assertEqual(date["rejected_candidate_count"], 2)
        self.assertEqual(date["rejected_newer_count"], 1)
        self.assertEqual(date["selected_date"], "2026-01-01T00:00:00.000000+00:00")
        self.assertFalse(date["newer_candidates_unvalidated"])
        self.assertIn("甲社標籤機", result["evidence"][0]["snippet"])
        self.assertFalse(date["latest_claim_verified"])
        self.assertEqual(result["status"], "partial")

    def test_all_authorized_selectors_share_one_inventory_and_date_sort(self):
        revision, prompt, arguments = self.prepare_recent(
            ["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"], second_dates=["2026-06-01T00:00:00+00:00"])
        arguments["page_size"] = 2
        lookup = revision.source_records.runtime_store
        with patch.object(lookup, "date_ordered_mail_candidates", wraps=lookup.date_ordered_mail_candidates) as enumerate_postings:
            result = self.run_recent(revision, prompt, arguments)
        self.assertEqual(enumerate_postings.call_count, 1)
        final = result["query_agent"]["context_bundle"]["source_recovery"]["mail_date_priority"]
        self.assertEqual(final["matching_occurrence_count"], 2)
        self.assertEqual(final["selected_date"], "2026-06-01T00:00:00.000000+00:00")
        self.assertTrue(final["selected_message_presented"])
        self.assertEqual(final["unread_known_date_candidate_count"], 1)
        self.assertFalse(final["newer_candidates_unvalidated"])

    def test_latest_binding_preserves_automatic_exact_budget(self):
        import hashlib
        from formowl_mail.issue56_sealed_source import bind_mail_date_priority, mail_date_priority_scope
        from test_issue56_source_start_exact import SourceStartExactTests
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        _, revision, _, arguments = SourceStartExactTests.prepare(self, inline=True)
        lookup = loader._IngestionExactCellLookup(revision)
        revision = replace(revision, reviewed_header_column_hashes=frozenset(
            item["column_hash"] for item in lookup._columns))
        handler = loader._build_source_start_semantic_handler(revision, mail_tool=True)
        arguments.pop("table_query")
        prompt = "Find latest ITEM-Q73 State and Capacity mail"
        arguments["query_text"] = prompt
        arguments["required_terms"] = ["ITEM-Q73"]
        arguments["request_contract"]["original_query_hash"] = "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()
        public = {key: value for key, value in arguments.items()
                  if key not in {"requester_user_id", "workspace_id", "session_id"}}
        binding = bind_mail_date_priority(user_text=prompt, arguments=public, tool_name="query_mail_evidence")
        self.assertIsNotNone(binding)
        budgets = []
        def exact(*args, **kwargs):
            budgets.append(kwargs["source_budget"]["deadline"] - loader.time.monotonic())
            return {"status": "partial", "requested_field_coverage": {"supported_fields": ["State"]}}
        with mail_date_priority_scope(binding), patch.object(loader, "_execute_source_start_table", side_effect=exact):
            handler(arguments)
        self.assertEqual(len(budgets), 1)
        self.assertGreater(budgets[0], 1.5)
        self.assertLessEqual(budgets[0], loader.SOURCE_START_EVIDENCE_TIME_BUDGET_MS / 1000)

    def test_unknown_date_and_small_read_cap_are_incomplete_without_new_budget(self):
        revision, prompt, arguments = self.prepare_recent(["", "2026-01-01T23:00:00+00:00"])
        result = self.run_recent(revision, prompt, arguments)
        date = result["query_agent"]["context_bundle"]["source_recovery"]["mail_date_priority"]
        self.assertEqual(date["unknown_date_count"], 1)
        self.assertFalse(date["date_inventory_complete"])
        self.assertFalse(date["latest_claim_verified"])
        with patch.object(loader, "SOURCE_EVIDENCE_OBSERVATION_LIMIT", 1):
            result = self.run_recent(revision, prompt, arguments)
        recovery = result["query_agent"]["context_bundle"]["source_recovery"]
        self.assertLessEqual(recovery["scan"]["scanned_observation_count"], 1)
        self.assertFalse(recovery["mail_date_priority"]["latest_claim_verified"])
        with patch.object(loader, "SOURCE_EVIDENCE_OBSERVATION_LIMIT", 0), patch.object(
            CompletedIngestionJobAuthority, "load_indexed_observation", side_effect=AssertionError("no reads remain"),
        ):
            result = self.run_recent(revision, prompt, arguments)
        recovery = result["query_agent"]["context_bundle"]["source_recovery"]
        self.assertEqual(recovery["scan"]["scanned_observation_count"], 0)
        self.assertFalse(recovery["mail_date_priority"]["date_inventory_complete"])
        for error in (TimeoutError("source read failed"), OverflowError("source decode failed")):
            with self.subTest(error=type(error).__name__), patch.object(
                CompletedIngestionJobAuthority, "load_indexed_observation", side_effect=error,
            ), self.assertRaises(type(error)):
                self.run_recent(revision, prompt, arguments)


class SourceQueryStabilityTests(unittest.TestCase):
    def prepare(self, families, *, document_text="cerulean"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        fixture = fixtures._source_start_preparation_fixture(
            root, families=families, mail_text="cerulean", document_text=document_text,
        )
        output = root / "lookup"
        build_lookup(directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                     output_directory=output)
        for name in ("source-lookup.sqlite", "source-lookup-manifest.json"):
            shutil.copyfile(output / name, fixture.directory / name)
        revision = load_issue56_ingestion_revision(
            fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
        )
        self.addCleanup(revision.source_records.runtime_store.close)
        handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
        arguments = {
            "query_text": "Find cerulean evidence", "requester_user_id": loader.APPROVER_ACTOR,
            "workspace_id": loader.WORKSPACE_ID, "session_id": "synthetic-query-stability",
            "required_terms": ["cerulean"], "page_size": 10,
            "request_contract": {
                "original_query_hash": sha256_json("Find cerulean evidence"),
                "query_class": "evidence_lookup",
                "source_family_scope": list(dict.fromkeys("mail" if f == "mail_other" else f for f in families)),
                "requested_fields": ["review condition"], "maximum_claim_strength": "cited_evidence",
            },
        }
        return revision, handler, arguments

    def test_slow_mail_family_cannot_spend_document_family_deadline(self):
        revision, handler, arguments = self.prepare(("mail", "document_text"))
        original = type(revision.source_records).scan_authorized_observations
        clock, calls = [10.0], []

        def scan(records, **kwargs):
            calls.append((kwargs["source_family"], kwargs["deadline_monotonic"]))
            if kwargs["source_family"] == "mail":
                clock[0] = kwargs["deadline_monotonic"]
                return RevisionOwnedMailSourceScan((), 3, False, "deadline")
            return original(records, **kwargs)

        with patch.object(loader.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
            type(revision.source_records), "scan_authorized_observations", autospec=True, side_effect=scan,
        ):
            result = handler(arguments)
        self.assertEqual([family for family, _ in calls], ["mail", "document_text"])
        self.assertLess(calls[0][1], calls[1][1])
        # One shared source-start phase budget bounds every family/selector.
        self.assertLessEqual(calls[-1][1], 10.0 + loader.SOURCE_START_EVIDENCE_TIME_BUDGET_MS / 1000)
        self.assertTrue(result["citations"])
        self.assertTrue(any(item.get("document_locator") for item in result["evidence"]))
        self.assertEqual(result["coverage"]["status"], "incomplete")

    def test_slow_first_selector_cannot_spend_second_selector_deadline(self):
        revision, handler, arguments = self.prepare(("mail", "mail_other"))
        original = type(revision.source_records).scan_authorized_observations
        clock, calls = [10.0], []

        def scan(records, **kwargs):
            calls.append((kwargs["mail_import_session_id"], kwargs["deadline_monotonic"], kwargs["max_observations"]))
            if len(calls) == 1:
                clock[0] = kwargs["deadline_monotonic"]
                return RevisionOwnedMailSourceScan((), 3, False, "deadline")
            return original(records, **kwargs)

        with patch.object(loader.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
            type(revision.source_records), "scan_authorized_observations", autospec=True, side_effect=scan,
        ):
            result = handler(arguments)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0][0], calls[1][0])
        self.assertLess(calls[0][1], calls[1][1])
        # One shared source-start phase budget bounds every family/selector.
        self.assertLessEqual(calls[-1][1], 10.0 + loader.SOURCE_START_EVIDENCE_TIME_BUDGET_MS / 1000)
        self.assertLessEqual(calls[1][2], 8192 - 3)
        self.assertTrue(result["citations"])
        self.assertEqual(result["coverage"]["status"], "incomplete")

    def test_shortlisted_mail_parent_already_delivered_for_child_is_not_read_twice(self):
        revision, _, _ = self.prepare(("mail",))
        records = revision.source_records
        authority = records.job_authorities[0]
        sources = [authority.observation_store.get(reference[1]) for reference in records.observation_references]
        body = next(item for item in sources if item.observation_type == "email_body_segment")
        parent = next(item for item in sources if item.observation_type == "email_message")
        for read_cap in (2, 8):
            delivered = []
            with self.subTest(read_cap=read_cap), source_evidence_query_terms_scope(("cerulean",)), patch.object(
                records.runtime_store, "source_family_lexical_lookup",
                return_value=[sha256_json(body.to_dict()), sha256_json(parent.to_dict())],
            ), patch.object(CompletedIngestionJobAuthority, "load_indexed_observation", autospec=True,
                            side_effect=CompletedIngestionJobAuthority.load_indexed_observation) as read:
                scan = records.scan_authorized_observations(
                    source_family="mail", mail_import_session_id=records.authorized_mail_import_session_ids[0],
                    max_observations=read_cap, observation_callback=lambda item, scope: delivered.append(item.observation_id) or True,
                )
            self.assertEqual(delivered, [parent.observation_id, body.observation_id])
            self.assertEqual(read.call_count, 2)
            self.assertEqual(scan.scanned_observation_count, 2)
            self.assertFalse(scan.complete)
            self.assertEqual(scan.stop_reason, "indexed_shortlist")

    def test_annotation_hint_read_summary_survives_full_trace_detail_budget(self):
        revision, handler, arguments = self.prepare(("document_text",))
        authority = revision.source_records.job_authorities[0]
        observation = next(
            authority.observation_store.get(reference[1])
            for reference in revision.source_records.observation_references
            if authority.observation_store.get(reference[1]).text == "cerulean"
        )
        observation_hash = sha256_json(observation.to_dict())
        reviewed = replace(
            revision,
            reviewed_source_annotations=({
                "candidate_atom_id": "reviewed-cerulean-atom",
                "target": "cerulean",
                "identity_bindings": (),
                "time_roles": (),
                "property": None,
                "event_type": None,
                "source_hashes": (observation_hash,),
            },),
        )
        handler = loader._build_source_start_semantic_handler(reviewed, mail_tool=False)
        trace = _SourcePhaseTrace({})
        original_scan = type(reviewed.source_records).scan_authorized_observations

        def fill_trace_after_hint_calculation(records, **kwargs):
            active_trace = _SOURCE_PHASE_TRACE.get()
            for _ in range(256):
                cell = active_trace.phase("fixture_trace_pressure")
                if cell is not None:
                    cell.finish()
            return original_scan(records, **kwargs)

        with _source_phase_trace_scope(trace), patch.object(
            type(reviewed.source_records), "scan_authorized_observations",
            autospec=True, side_effect=fill_trace_after_hint_calculation,
        ):
            result = handler(arguments)

        snapshot = json.loads(trace.snapshot())
        read_summary = next(
            item for item in snapshot["details"]
            if item.get("name") == "annotation_identity_reads"
        )
        self.assertEqual(read_summary["candidate_hash_count"], 1)
        self.assertGreater(read_summary["projected_candidate_count"], 0)
        self.assertGreater(read_summary["predicate_passed_count"], 0)
        self.assertTrue(result["citations"])

    def test_reviewed_identity_surface_passes_without_changing_ordinary_results(self):
        revision, _, arguments = self.prepare(
            ("document_text",),
            document_text=(
                "# Source identity\n\n甲社標籤機 delivery confirmed\n\n"
                "ordinary delivery result\n"
            ),
        )
        authority = revision.source_records.job_authorities[0]
        observations = [
            authority.observation_store.get(reference[1])
            for reference in revision.source_records.observation_references
        ]
        alias_observation = next(item for item in observations if "甲社標籤機" in (item.text or ""))
        observation_hash = sha256_json(alias_observation.to_dict())
        reviewed = replace(
            revision,
            reviewed_source_annotations=({
                "candidate_atom_id": "reviewed-clienta-atom",
                "target": "Clienta",
                "identity_bindings": ({
                    "scope_role": "primary", "type_surface": "標籤機",
                    "value_surface": "甲社標籤機",
                },),
                "time_roles": (),
                "property": None,
                "event_type": None,
                "source_hashes": (observation_hash,),
            },),
        )
        query = "Find Clienta delivery evidence"
        arguments["query_text"] = query
        arguments["required_terms"] = ["delivery"]
        arguments["request_contract"]["original_query_hash"] = sha256_json(query)
        arguments["request_contract"]["requested_fields"] = ["delivery status"]

        ordinary = loader._build_source_start_semantic_handler(revision, mail_tool=False)(arguments)
        trace = _SourcePhaseTrace({})
        with _source_phase_trace_scope(trace):
            annotated = loader._build_source_start_semantic_handler(reviewed, mail_tool=False)(arguments)
        summary = next(
            item for item in json.loads(trace.snapshot())["details"]
            if item.get("name") == "annotation_identity_reads"
        )
        self.assertGreater(summary["predicate_passed_count"], 0)
        self.assertEqual(annotated["citations"], ordinary["citations"])
        self.assertGreaterEqual(len(ordinary["citations"]), 2)

        arguments["required_terms"] = ["overdue"]
        arguments["request_contract"]["requested_fields"] = ["overdue status"]
        arguments["request_contract"]["original_query_hash"] = sha256_json(query)
        rejected_trace = _SourcePhaseTrace({})
        with _source_phase_trace_scope(rejected_trace):
            rejected = loader._build_source_start_semantic_handler(reviewed, mail_tool=False)(arguments)
        reject_summary = next(
            item for item in json.loads(rejected_trace.snapshot())["details"]
            if item.get("name") == "annotation_identity_reads"
        )
        self.assertEqual(reject_summary["predicate_passed_count"], 0)
        self.assertGreater(reject_summary["predicate_rejected_count"], 0)
        self.assertEqual(rejected["citations"], [])

    def test_expanded_wording_and_requested_fields_do_not_change_grounded_shortlist(self):
        revision, handler, arguments = self.prepare(("mail", "document_text"))
        lookup = revision.source_records.runtime_store
        captures, citation_sets = [], []
        for query, field in (("Find cerulean evidence", "review condition"),
                             ("Locate cerulean with a provenance explanation", "decision summary")):
            arguments["query_text"] = query
            arguments["request_contract"].update(original_query_hash=sha256_json(query), requested_fields=[field])
            with patch.object(lookup, "source_family_lexical_lookup", wraps=lookup.source_family_lexical_lookup) as shortlist:
                result = handler(arguments)
            captures.append([(call.args[0], call.kwargs["source_family"]) for call in shortlist.call_args_list])
            citation_sets.append(result["citations"])
            self.assertEqual(result["coverage"]["status"], "incomplete")
            self.assertEqual(result["query_agent"]["context_bundle"]["missing_field_hashes"], [sha256_json(field)])
        self.assertTrue(citation_sets[0])
        self.assertEqual(captures[0], captures[1])
        self.assertEqual(citation_sets[0], citation_sets[1])

    def test_previous_family_reads_do_not_reduce_later_selector_allocations_twice(self):
        revision, handler, arguments = self.prepare(("mail", "mail_other", "document_text"))
        arguments["request_contract"]["source_family_scope"] = ["document_text", "mail"]
        calls = []

        def scan(records, **kwargs):
            calls.append(kwargs["max_observations"])
            consumed = 100 if kwargs["source_family"] == "document_text" else kwargs["max_observations"]
            return RevisionOwnedMailSourceScan((), consumed, False, "indexed_shortlist")

        with patch.object(loader.time, "monotonic", return_value=10.0), patch.object(
            type(revision.source_records), "scan_authorized_observations", autospec=True, side_effect=scan,
        ):
            result = handler(arguments)
        self.assertEqual(calls, [4096, 4046, 4046])
        recovery = result["query_agent"]["context_bundle"]["source_recovery"]
        self.assertEqual(recovery["scan"]["scanned_observation_count"], 8192)
        self.assertFalse(recovery["scan"]["complete"])
        self.assertFalse(result["citations"])
        self.assertNotEqual(result["status"], "not_found")

    def test_duplicate_parent_helper_must_still_match_identity_scope_and_job(self):
        revision, _, _ = self.prepare(("mail",))
        records = revision.source_records
        authority = records.job_authorities[0]
        sources = [authority.observation_store.get(reference[1]) for reference in records.observation_references]
        body = next(item for item in sources if item.observation_type == "email_body_segment")
        parent = next(item for item in sources if item.observation_type == "email_message")
        parent_hash = sha256_json(parent.to_dict())
        helper_for_hash = records.runtime_store.helper_for_hash
        for corrupted in ("identity", "permission", "job"):
            parent_calls = [0]

            def helper(key):
                value = helper_for_hash(key)
                if key != parent_hash:
                    return value
                parent_calls[0] += 1
                if parent_calls[0] == 1:
                    return value  # Genuine parent hydration for the child.
                value = {**value, "reference": dict(value["reference"]),
                         "permission_scope": dict(value["permission_scope"])}
                if corrupted == "identity":
                    value["observation_id"] = body.observation_id
                elif corrupted == "permission":
                    value["permission_scope"]["scope_id"] = "denied-synthetic-scope"
                else:
                    value["reference"]["job_fingerprint"] = "sha256:" + "0" * 64
                return value

            with self.subTest(corrupted=corrupted), source_evidence_query_terms_scope(("cerulean",)), patch.object(
                records.runtime_store, "source_family_lexical_lookup", return_value=[sha256_json(body.to_dict()), parent_hash],
            ), patch.object(records.runtime_store, "helper_for_hash", side_effect=helper):
                with self.assertRaises(ContractValidationError):
                    records.scan_authorized_observations(
                        source_family="mail", mail_import_session_id=records.authorized_mail_import_session_ids[0],
                        max_observations=8, observation_callback=lambda item, scope: True,
                    )


class MailPresentationRecencyIntentTests(unittest.TestCase):
    @staticmethod
    def bind(prompt, *, scope=("mail", "attachment_table"), **changes):
        import hashlib
        from formowl_mail.issue56_sealed_source import bind_mail_date_priority
        arguments = {"query_text": "Find latest Clienta records", "required_terms": ["clienta"],
                     "request_contract": {"original_query_hash": "sha256:" + hashlib.sha256(prompt.encode()).hexdigest(),
                         "query_class": "evidence_lookup", "source_family_scope": list(scope),
                         "requested_fields": ["release"], "maximum_claim_strength": "cited_evidence"}}
        arguments.update(changes)
        return bind_mail_date_priority(user_text=prompt, arguments=arguments, tool_name="query_effective_graph_view")

    def test_general_recency_is_bound_to_presentation_without_new_date_scans(self):
        for phrase in ("最近一次下單", "最後一次出貨", "最后一次採購", "上一次出貨是哪天", "最新進度"):
            with self.subTest(phrase=phrase):
                binding = self.bind("Clienta " + phrase)
                self.assertIsNotNone(binding)
                self.assertEqual(binding.mode, "presentation_tiebreak")
        self.assertEqual(self.bind("Clienta 最後一次出貨", scope=("mail",)).mode, "presentation_tiebreak")
        self.assertEqual(self.bind("Clienta 最新進度", scope=("mail",)).mode, "date_scan")

    def test_positions_windows_literals_and_relative_previous_are_not_latest(self):
        for phrase in ("最後一頁", "最後一欄", "最後一行", "最後一個字", "最近三個月所有訂單",
                       "不要最新", "比較最新和最舊", "查含『最新』字樣", "交貨日期是什麼", "PO 哪天開立",
                       "上一次與這次比較", "指定那筆之前的上一次出貨", "上上次出貨", "最新一欄"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(self.bind("Clienta " + phrase))

    def test_model_rewriting_or_unbound_scope_cannot_grant_recency(self):
        self.assertIsNone(self.bind("Clienta 的資料"))  # query_text above says latest.
        self.assertIsNone(self.bind("Clienta 最新進度", scope=("document_text",)))
        self.assertIsNone(self.bind("Clienta 最新進度", required_terms=["invented"]))
        self.assertIsNone(self.bind("Clienta 最新進度", cursor="synthetic-cursor"))


if __name__ == "__main__":
    unittest.main()
