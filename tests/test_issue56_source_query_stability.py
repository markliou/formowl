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
                "# Source identity\n\n楓林標籤機 delivery confirmed\n\n"
                "ordinary delivery result\n"
            ),
        )
        authority = revision.source_records.job_authorities[0]
        observations = [
            authority.observation_store.get(reference[1])
            for reference in revision.source_records.observation_references
        ]
        alias_observation = next(item for item in observations if "楓林標籤機" in (item.text or ""))
        observation_hash = sha256_json(alias_observation.to_dict())
        reviewed = replace(
            revision,
            reviewed_source_annotations=({
                "candidate_atom_id": "reviewed-kestrel-atom",
                "target": "Kestrel",
                "identity_bindings": ({
                    "scope_role": "primary", "type_surface": "標籤機",
                    "value_surface": "楓林標籤機",
                },),
                "time_roles": (),
                "property": None,
                "event_type": None,
                "source_hashes": (observation_hash,),
            },),
        )
        query = "Find Kestrel delivery evidence"
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


if __name__ == "__main__":
    unittest.main()
