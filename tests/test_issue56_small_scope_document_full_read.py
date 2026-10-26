"""Small document recovery uses real sealed job authority, without a provider."""
from contextlib import nullcontext
from pathlib import Path
import tempfile
import hashlib
import json
import shutil
import unicodedata
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_contract import sha256_json
from formowl_gateway import issue56_sealed_source_loader as loader
from formowl_mail import human_uat_orchestrator as orchestrator
from formowl_mail import issue56_sealed_source
from formowl_retrieval import gateway

from test_issue56_uat_handler_composition import _source_start_preparation_fixture
from scripts.issue56_source_native_lookup import build_lookup


class SmallScopeDocumentFullReadTests(unittest.TestCase):
    def run_lookup(self, text, *, families=("document_text",), required="missingcompound",
                   incomplete=False, explicit=True, first=True, force_deadline=False, indexed=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        fixture = _source_start_preparation_fixture(
            Path(directory.name), families=families, document_text=text,
        )
        if indexed:
            output = Path(directory.name) / "lookup"
            build_lookup(directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                         output_directory=output)
            for name in ("source-lookup.sqlite", "source-lookup-manifest.json"):
                shutil.copyfile(output / name, fixture.directory / name)
        revision = issue56_sealed_source.load_issue56_ingestion_revision(
            fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
        )
        if indexed:
            self.addCleanup(revision.source_records.runtime_store.close)
        prompt = ("請根據專案文件整理目前的工作狀態、已完成事項與下一步。"
                  if explicit else "整理目前的工作狀態、已完成事項與下一步。")
        original_hash = "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()
        arguments = {
            "query_text": "missingcompound lookup", "required_terms": [required],
            "requester_user_id": loader.APPROVER_ACTOR,
            "workspace_id": loader.WORKSPACE_ID, "session_id": "full-doc-read",
            "request_contract": {"original_query_hash": original_hash,
                "query_class": "evidence_lookup", "source_family_scope": sorted(families),
                "requested_fields": ["status", "next_step"],
                "maximum_claim_strength": "cited_evidence"},
        }
        if incomplete:
            revision.source_records.observation_references.pop()
        scope = getattr(gateway, "_source_document_full_read_scope", None)
        binding = (original_hash, ("document_text",) if explicit else (),
                   sha256_json({"name": "query_effective_graph_view", "arguments": {
                       key: value for key, value in arguments.items()
                       if key not in {"requester_user_id", "workspace_id", "session_id"}}}), first)
        original_scan = revision.source_records.scan_authorized_observations

        def scan(**kwargs):
            if force_deadline and kwargs.get("_complete_document_scope"):
                raise gateway._SourceEvidenceDeadlineExceeded()
            return original_scan(**kwargs)

        with (scope(binding) if scope else nullcontext(),
              patch.object(revision.source_records, "scan_authorized_observations", side_effect=scan)):
            result = loader._build_source_start_semantic_handler(revision, mail_tool=False)(arguments)
        return result, fixture, arguments

    @staticmethod
    def recovery(result):
        return result["query_agent"]["context_bundle"]["source_recovery"]

    def test_full_read_recovers_all_ordered_native_citations(self):
        result, fixture, _ = self.run_lookup("Completed the design.\n\nNext step is owner review.\n")
        self.assertTrue(result["citations"])
        recovery = self.recovery(result)
        self.assertEqual(recovery["mode"], "small_scope_full_read")
        self.assertTrue(recovery["scan_complete"])
        self.assertEqual(recovery["paragraph_count"], 2)
        self.assertEqual(recovery["document_count"], 1)
        self.assertEqual(len(result["evidence"]), 2)
        self.assertEqual([item["snippet"] for item in result["evidence"]],
                         [item.text for item in fixture.observations])
        self.assertTrue(all(item["document_locator"]["line_start"] for item in result["evidence"]))
        self.assertEqual(result["citations"], sorted(sha256_json(item.to_dict()) for item in fixture.observations))

    def test_indexed_shortlist_miss_uses_the_same_complete_sealed_reader(self):
        result, _, _ = self.run_lookup("Completed.\n\nNext action.", indexed=True)
        self.assertEqual(self.recovery(result)["mode"], "small_scope_full_read")
        self.assertEqual(len(result["citations"]), 2)
        self.assertTrue(self.recovery(result)["scan_complete"])

    def test_runtime_derives_private_scope_from_the_original_prompt(self):
        from formowl_gateway.issue56_uat_runtime import _mcp_query_request, _run_gpt_query_agent

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        fixture = _source_start_preparation_fixture(
            Path(directory.name), families=("document_text",), document_text="Completed the design.",
        )
        revision = issue56_sealed_source.load_issue56_ingestion_revision(
            fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
        )
        handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
        prompt = "請根據專案文件整理目前的工作狀態、已完成事項與下一步。"
        request = orchestrator.UatEvidenceToolRequest(
            tool_name="query_effective_graph_view", query_text="查找專案文件，整理工作狀態與下一步。",
            required_terms=("專案文件",), request_contract={
                "original_query_hash": "sha256:" + hashlib.sha256(prompt.encode()).hexdigest(),
                "query_class": "evidence_lookup", "source_family_scope": ["document_text"],
                "requested_fields": ["工作狀態", "下一步"], "maximum_claim_strength": "cited_evidence",
            },
        )
        class LocalModel:
            def respond(model, **kwargs):
                data = kwargs["evidence_tool"](request)
                return orchestrator.UatConversationOutcome(
                    response_kind="answer", answer_text="Design completed.", display_format="narrative",
                    model_name="local-no-provider", citation_ids=tuple(data["citations"]),
                    coverage_status="incomplete", coverage_note="Only bounded document evidence.",
                    tool_requests=(request,), tool_results=(data,),
                )
        def call_tool(bound_request):
            arguments = {**_mcp_query_request(bound_request)["params"]["arguments"],
                         "requester_user_id": loader.APPROVER_ACTOR,
                         "workspace_id": loader.WORKSPACE_ID, "session_id": "runtime-full-read"}
            return handler(arguments)
        _, responses, _ = _run_gpt_query_agent(
            LocalModel(), prompt=prompt, history=(), latest_evidence=None,
            safety_identifier="local-test", formowl_tool_descriptor=None,
            authorized_capability_summary=handler.authorized_capability_summary, mcp_call=call_tool,
        )
        self.assertEqual(len(responses), 1)
        self.assertEqual(self.recovery(responses[0])["mode"], "small_scope_full_read")
        self.assertTrue(responses[0]["citations"])

    def test_all_90_paragraphs_are_presented_before_answer_with_native_citations(self):
        text = "\n\n".join(f"Section {index}. " + "全文內容" * 60 for index in range(90))
        result, _, _ = self.run_lookup(text)
        compact = orchestrator.compact_evidence_for_model(result)
        self.assertEqual(len(compact["evidence"]), 90)
        self.assertEqual(compact["citations"], result["citations"])
        self.assertGreater(len(compact["evidence_batch_ends"]), 1)
        self.assertEqual(compact["evidence_batch_ends"][-1], 90)
        self.assertTrue(self.recovery(compact)["model_read_complete"])
        self.assertEqual(orchestrator.compact_evidence_for_model(compact), compact)
        self.assertIn("已讀完全部 1 份文件", compact["full_read_scope_summary"])
        self.assertEqual("".join(item["snippet"] for item in compact["evidence"]),
                         "".join(item["snippet"] for item in result["evidence"]))

    def test_finalization_renders_whole_document_scope_disclosure(self):
        from formowl_gateway.remote import build_remote_tool_descriptors

        result, _, arguments = self.run_lookup("Completed.\n\nNext action.", required="專案文件")
        descriptor = next(tool.model_dump(by_alias=True, exclude_none=True)
                          for tool in build_remote_tool_descriptors(
                              required_scope="formowl.use", enabled_tool_names={"whoami", "query_effective_graph_view"})
                          if tool.name == "query_effective_graph_view")
        public_arguments = {key: value for key, value in arguments.items()
                            if key not in {"requester_user_id", "workspace_id", "session_id"}}
        model = orchestrator.CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="synthetic-key", typed_evidence_notes=True,
        )
        self.addCleanup(model.close)
        model.configure_conversation_tools(safety_identifier="scope-finalization", tool_descriptors=[descriptor])
        citation = result["citations"][0]
        decision = {"response_kind": "answer", "answer_text": "Design completed.",
                    "display_format": "narrative", "citation_ids": [citation],
                    "coverage_status": "incomplete", "coverage_note": "", "field_limitations": []}
        responses = [
            {"status": "completed", "output": [{"type": "function_call", "call_id": "full-documents",
                "name": "query_effective_graph_view", "arguments": json.dumps(public_arguments)}]},
            {"status": "completed", "output_text": json.dumps(decision)},
        ]
        with patch.object(model, "_request_response", side_effect=responses) as provider:
            outcome = model.respond(
                history=(), user_text="請根據專案文件整理目前的工作狀態、已完成事項與下一步。",
                latest_evidence=None, safety_identifier="scope-finalization", evidence_tool=lambda request: result,
                formowl_tool_descriptor=descriptor, authorized_capability_summary={"source_families": ["document_text"]},
            )
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(outcome.response_kind, "answer")
        self.assertIn("已讀完全部 1 份文件。", outcome.coverage_note)
        self.assertEqual(outcome.citation_ids, (citation,))

    def test_paragraph_cap_preserves_the_existing_split_route(self):
        result, _, arguments = self.run_lookup("\n\n".join("Record." for _ in range(201)))
        self.assertNotIn("mode", self.recovery(result))
        self.assertEqual(self.recovery(result)["full_read_skip_reason"], "paragraph_limit")
        self.assertFalse(result["citations"])
        request = orchestrator.UatEvidenceToolRequest(
            tool_name="query_effective_graph_view", query_text=arguments["query_text"],
            required_terms=("missingcompound",), request_contract=arguments["request_contract"],
        )
        binder = orchestrator._UatTurnRequestContractBinder(
            user_text="請根據專案文件整理目前的工作狀態、已完成事項與下一步。",
            authorized_capability_summary={"source_families": ["document_text"]},
        )
        binder._required_terms = request.required_terms
        self.assertTrue(binder.arm_split_refinement(request, result, remaining_calls=2))

    def test_nfc_character_cap_is_conjunctive(self):
        for text, allowed in (("e\u0301" * 60000, True), ("界" * 60001, False)):
            with self.subTest(normalized_length=len(unicodedata.normalize("NFC", text))):
                result, fixture, _ = self.run_lookup(text)
                recovery = self.recovery(result)
                self.assertEqual(recovery.get("mode") == "small_scope_full_read", allowed)
                if allowed:
                    self.assertEqual(recovery["character_count"], 60000)
                    compact = orchestrator.compact_evidence_for_model(result)
                    self.assertEqual("".join(item["snippet"] for item in compact["evidence"]),
                                     unicodedata.normalize("NFC", text))
                    self.assertEqual(result["citations"], sorted(sha256_json(item.to_dict())
                                                               for item in fixture.observations))
                else:
                    self.assertEqual(recovery["full_read_skip_reason"], "character_limit")
                    self.assertFalse(result["citations"])

    def test_incomplete_bound_inventory_does_not_full_read(self):
        result, _, _ = self.run_lookup("First.\n\nSecond.", incomplete=True)
        self.assertNotIn("mode", self.recovery(result))
        self.assertEqual(self.recovery(result)["full_read_skip_reason"], "source_reference_unavailable")
        self.assertFalse(result["citations"])

    def test_mail_scope_does_not_full_read(self):
        result, _, _ = self.run_lookup("Document.", families=("mail", "document_text"))
        self.assertNotIn("mode", self.recovery(result))
        self.assertFalse(result["citations"])

    def test_existing_citations_do_not_trigger_full_read(self):
        result, _, _ = self.run_lookup("Owner completed the design.", required="owner")
        self.assertTrue(result["citations"])
        self.assertNotIn("mode", self.recovery(result))

    def test_only_raw_prompt_explicit_family_and_first_frozen_query_can_trigger(self):
        for arguments in ({"explicit": False}, {"first": False}):
            with self.subTest(arguments=arguments):
                result, _, _ = self.run_lookup("Document.", **arguments)
                self.assertNotIn("mode", self.recovery(result))
                self.assertFalse(result["citations"])

    def test_deadline_race_preserves_original_result(self):
        result, _, _ = self.run_lookup("Document.", force_deadline=True)
        self.assertNotIn("mode", self.recovery(result))
        self.assertEqual(self.recovery(result)["full_read_skip_reason"], "deadline")
        self.assertFalse(result["citations"])


if __name__ == "__main__":
    unittest.main()
