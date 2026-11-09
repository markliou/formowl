from __future__ import annotations

import hashlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import tempfile
import threading
import unittest
import unicodedata
from unittest import mock

import _paths  # noqa: F401
from formowl_gateway.remote import build_remote_tool_descriptors
from formowl_mail.human_uat_orchestrator import (
    CodexResponsesConversationModel,
)
from formowl_mail import human_uat_orchestrator as orchestrator
from formowl_contract import ContractValidationError
from formowl_contract.public_safety import assert_no_public_raw_references
from formowl_gateway.jsonrpc import (
    EVIDENCE_ANCHOR_FIELD_PLANNING_GUIDANCE,
    SOURCE_EVIDENCE_RECHECK_PLANNING_GUIDANCE,
)
from formowl_gateway.issue56_uat_runtime import _browser_projection
from formowl_mail.human_uat_http import _safe_provider_diagnostic


def _decision(*, citation: str) -> str:
    return json.dumps(
        {
            "response_kind": "answer",
            "answer_text": "已整理目前可引用的授權郵件；涵蓋仍不完整。",
            "display_format": "narrative",
            "citation_ids": [citation],
            "coverage_status": "incomplete",
            "coverage_note": "目前結果為授權範圍內的部分證據。",
        },
        separators=(",", ":"),
    )


def _mail_tool_descriptor() -> dict:
    return next(
        tool.model_dump(by_alias=True, exclude_none=True)
        for tool in build_remote_tool_descriptors(
            required_scope="formowl.use",
            enabled_tool_names={"whoami", "query_mail_evidence"},
        )
        if tool.name == "query_mail_evidence"
    )


class Issue56ProviderFinalizationTests(unittest.TestCase):
    def setUp(self):
        from test_issue56_codex_provider_bridge import _use_short_citation_fixtures
        _use_short_citation_fixtures(self)

    def test_only_exact_overload_changes_failed_finalization_message(self):
        busy = "模型服務目前忙碌，請稍後再試"
        parse_failure = "GPT provider 回應未能完成安全解析或結構化驗證；這次最終答案未完成。"
        source_text = "Fictional preserved source explanation."
        fallbacks = (
            (None, busy),
            ("", busy),
            (source_text, busy + "\n" + source_text),
            (source_text + "\n" + parse_failure, source_text + "\n" + busy),
        )
        for kind in ("serverOverloaded", "rateLimitExceeded", "httpConnectionFailed", "unknown"):
            for source_fallback, overload_message in fallbacks:
                with self.subTest(kind=kind, fallback=source_fallback):
                    diagnostic = {"reason_code": "provider_incomplete", "codex_error_kind": kind}
                    with mock.patch.object(orchestrator, "_source_evidence_fallback_text", return_value=source_fallback):
                        outcome = orchestrator._safe_stop_outcome(reason="provider_incomplete", model_name="fictional",
                            evidence_records=(), provider_diagnostic=diagnostic)
                    expected = overload_message if kind == "serverOverloaded" else (
                        source_fallback or orchestrator._safe_stop_message("provider_incomplete"))
                    self.assertEqual(outcome.answer_text, expected)
                    # The existing source table and citations survive; replace only its failure explanation.
                    citation = "sha256:" + "a" * 64
                    response = {"status": "partial", "citations": [citation], "query_agent": {
                        "context_bundle": {"successful_subqueries": [{"evidence": [{
                            "citation_hash": citation, "snippet": "Fictional verified source text."}]}]}}}
                    projected = _browser_projection(outcome, (response,), latest_evidence=None)
                    self.assertIn("Fictional verified source text.", projected["answer"])
                    self.assertEqual(projected["citations"], [citation])
                    self.assertTrue(projected["clarification"].startswith(expected + "\n"))
                    self.assertIn("涵蓋限制：本畫面直接呈現 1 筆本回合可引用資料", projected["clarification"])

    def test_overload_keeps_native_fallback_fields_citations_and_coverage_visible(self):
        citation = "sha256:" + "b" * 64
        request = orchestrator.UatEvidenceToolRequest(query_text="Retrieve the fictional Clienta record.")
        result = {
            "status": "partial",
            "citations": [citation],
            "evidence": [{
                "citation_hash": citation,
                "snippet": "Fictional same-row source; native values are in its cells.",
                "table_row": {"cells": [
                    {"field": "Ticket", "value": "Clienta-Q17", "citation_hash": citation,
                     "structure_status": "candidate_only"},
                    {"field": "State", "value": "reviewed", "citation_hash": citation,
                     "structure_status": "candidate_only"},
                ]},
            }],
        }
        records = ((request, result),)
        outcome = orchestrator._safe_stop_outcome(
            reason="provider_incomplete", model_name="fictional", evidence_records=records,
            provider_diagnostic={"reason_code": "provider_incomplete", "codex_error_kind": "serverOverloaded"},
        )
        projected = _browser_projection(outcome, (result,), latest_evidence=None)
        for text in (outcome.answer_text, outcome.coverage_note, projected["clarification"]):
            self.assertIn("模型服務目前忙碌，請稍後再試", text)
            self.assertIn("Ticket：Clienta-Q17", text)
            self.assertIn("State：reviewed", text)
            self.assertIn("欄位結構待完整驗證", text)
            self.assertIn("本回合涵蓋仍未完成", text)
            self.assertIn("未列出的欄位不代表來源不存在", text)
            self.assertNotIn("GPT provider 回應未能完成安全解析或結構化驗證", text)
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(projected["citations"], [citation])
        self.assertEqual(outcome.coverage_status, "incomplete")
        self.assertEqual(outcome.tool_results, (result,))

    def test_exact_downgrade_disclosure_reaches_both_visible_provider_outcomes(self):
        for provider_kind in ("responses", "app_server"):
            for complete in (False, True):
                with self.subTest(provider=provider_kind, complete=complete):
                    outcome, projected, requests = self._exact_downgrade_turn(provider_kind, complete=complete)
                    self.assertEqual(outcome.coverage_status, "incomplete")
                    self.assertIn("無法做完整清單／確定性計算，以下為引用證據", outcome.coverage_note)
                    self.assertIn("無法做完整清單／確定性計算，以下為引用證據", projected["clarification"])
                    self.assertEqual(projected["citations"], ["sha256:" + "a" * 64])
                    if complete:
                        self.assertEqual(outcome.response_kind, "clarification")
                        self.assertNotEqual(outcome.answer_text, "Clienta ZX-742 is approved.")
                    else:
                        self.assertEqual(outcome.response_kind, "answer")
                        self.assertIn("Clienta ZX-742 is approved.", outcome.answer_text)
                    if provider_kind == "responses":
                        self.assertEqual(len(requests), 3 if complete else 2)
                        self.assertEqual(requests[1]["tool_choice"], "none")
                        wire = next(item["output"] for item in requests[1]["input"] if item.get("type") == "function_call_output")
                        self.assertEqual(json.loads(wire)["data"]["execution_downgrade"]["executed_request_contract"]["maximum_claim_strength"], "cited_evidence")
                        self.assertIn("無法做完整清單／確定性計算，以下為引用證據", wire)

    def _exact_downgrade_turn(self, provider_kind, *, complete):
        from test_issue56_codex_provider_bridge import _RecordingTransport
        user_text = "請列出附件表格中 Clienta ZX-742 的所有 State"
        _, descriptor, arguments, capabilities = self._field_plan(
            family="attachment_table", user_text=user_text, field="State", terms=("zx-742",))
        arguments["query_text"] = "Enumerate source records mentioning Clienta ZX-742."
        citation = "sha256:" + "a" * 64
        disclosure = "無法做完整清單／確定性計算，以下為引用證據"
        results = []
        def evidence_tool(request):
            original = request.request_contract
            result = {
                "status": "partial", "query_hash": orchestrator.sha256_json(request.query_text),
                "coverage": {"status": "incomplete", "absence_claim": False},
                "deterministic_exact": False, "exact_result": None,
                "evidence": [{"citation_hash": citation, "snippet": "Clienta ZX-742 State: approved."}],
                "citations": [citation], "query_agent": {"request_contract": original},
                "execution_downgrade": {
                    "reason": "exact_table_plan_unavailable",
                    "query_hash": orchestrator.sha256_json(request.query_text),
                    "request_contract_fingerprint": orchestrator.sha256_json(original),
                    "required_terms_fingerprint": orchestrator.sha256_json(request.required_terms),
                    "executed_request_contract": {**original, "query_class": "evidence_lookup", "maximum_claim_strength": "cited_evidence"},
                    "disclosure": disclosure,
                },
            }
            results.append(result)
            return result
        draft = {**json.loads(_decision(citation=citation)), "answer_text": "Clienta ZX-742 is approved."}
        if complete:
            draft.update(coverage_status="complete", coverage_note="")
        requests = []
        with tempfile.TemporaryDirectory() as workspace:
            if provider_kind == "app_server":
                transport = _RecordingTransport(calls=[arguments], final_message=json.dumps(draft))
                provider = orchestrator.CodexAppServerConversationModel(transport, workspace_dir=workspace)
                outcome = provider.respond(history=(), user_text=user_text, latest_evidence=None,
                    safety_identifier="synthetic-clienta-downgrade", evidence_tool=evidence_tool,
                    formowl_tool_descriptor=descriptor, authorized_capability_summary=capabilities)
            else:
                provider = CodexResponsesConversationModel(base_url="https://provider.example.test/v1", api_key="synthetic")
                def response(payload):
                    requests.append(copy.deepcopy(payload))
                    if len(requests) == 1:
                        return {"status": "completed", "output": [{"type": "function_call", "call_id": "clienta",
                            "name": "query_effective_graph_view", "arguments": json.dumps(arguments)}]}
                    return {"status": "completed", "output_text": json.dumps(draft)}
                with mock.patch.object(provider, "_request_response", side_effect=response):
                    outcome = provider.respond(history=(), user_text=user_text, latest_evidence=None,
                        safety_identifier="synthetic-clienta-downgrade", evidence_tool=evidence_tool,
                        formowl_tool_descriptor=descriptor, authorized_capability_summary=capabilities)
        self.assertEqual(len(results), 1, repr(outcome))
        self.assertEqual(results[0]["query_agent"]["request_contract"], outcome.tool_request.request_contract)
        return outcome, _browser_projection(outcome, tuple(results), latest_evidence=None), requests

    @staticmethod
    def _split_recovery(request, *, variant=None):
        return {"status": "pending_review", "citations": [], "evidence": [], "query_agent": {
            "status": "replan_required", "stop_reason": "time_budget_exhausted",
            "original_query_hash": request.request_contract["original_query_hash"],
            "request_contract": request.request_contract,
            "context_bundle": {"source_recovery": {
                "artifact_id": "formowl_bounded_source_recovery_v1", "attempted": True,
                "query_hash": orchestrator.sha256_json(request.query_text),
                "source_family_scope": request.request_contract["source_family_scope"],
                "status": "pending_review", "initial_status": "no_answer", "recheck_variant": variant,
                "scan": {"complete": False, "scanned_observation_count": 4, "stop_reason": "observation_limit"},
                "warnings": ["used", "incomplete"],
            }}}}

    def _split_plan(self, *, terms=("aster", "label project"), user_text=None):
        text = user_text or "Find progress for aster label project spare in documents."
        binder, descriptor, arguments, capabilities = self._field_plan(
            family="document_text", user_text=text, field="progress", terms=terms,
        )
        arguments["query_text"] = "Retrieve source evidence: " + text
        request = orchestrator._parse_tool_request(arguments, tool_descriptor=descriptor,
                                                   request_contract_binder=binder)
        return binder, descriptor, arguments, capabilities, request

    def test_split_partition_reconstructs_all_terms_without_stripping_internal_punctuation(self):
        cases = [
            (("ab", "label project"), ("ab", "label", "project"), True),
            (("a", "label， project"), ("a", "label", "project"), True),
            (("label-project",), ("label", "project"), True),
            (("label+project",), ("label", "project"), False),
            (("label.project work",), ("labelproject", "work"), False),
            (("(label project)",), ("label", "project"), False),
            (("label project!",), ("label", "project"), False),
            (("label project",), ("label", "project", "spare"), False),
            (("label project",), ("label",), False),
            (("label project",), ("label", "other"), False),
            (("label project",), ("l", "abel", "project"), False),
            (("abab",), ("ab",), False),
        ]
        for frozen, proposed, expected in cases:
            with self.subTest(frozen=frozen, proposed=proposed):
                self.assertEqual(orchestrator._is_split_only_refinement(frozen, proposed), expected)

    def test_split_binder_is_grounded_atomic_and_refreezes_only_once(self):
        binder, descriptor, arguments, _, request = self._split_plan()
        self.assertTrue(binder.arm_split_refinement(request, self._split_recovery(request), remaining_calls=2))
        original = binder._required_terms
        for terms in (["aster", "label"], ["aster", "label", "spare"],
                      ["aster", "label", "project", "spare"], ["aster", "label", "invented"]):
            with self.subTest(terms=terms), self.assertRaises(ContractValidationError):
                orchestrator._parse_tool_request({**arguments, "required_terms": terms},
                    tool_descriptor=descriptor, request_contract_binder=binder)
            self.assertEqual(binder._required_terms, original)
        # Failure in later query-shape checks must not re-freeze the earlier term proposal.
        with self.assertRaises(ContractValidationError):
            orchestrator._parse_tool_request({**arguments, "page_size": 0,
                "required_terms": ["aster", "label", "project"]},
                tool_descriptor=descriptor, request_contract_binder=binder)
        self.assertEqual(binder._required_terms, original)
        accepted = orchestrator._parse_tool_request({**arguments, "required_terms": ["aster", "label", "project"]},
            tool_descriptor=descriptor, request_contract_binder=binder)
        self.assertEqual(accepted.required_terms, ("aster", "label", "project"))
        self.assertFalse(binder._split_refinement_armed)
        self.assertFalse(binder.arm_split_refinement(accepted, self._split_recovery(accepted), remaining_calls=1))
        with self.assertRaisesRegex(ContractValidationError, "changed within the turn"):
            binder.bind_required_terms(["as", "ter", "label", "project"])

    def test_split_piece_shared_with_a_requested_field_is_not_a_new_field_filter(self):
        text = "請查 Clienta 標籤機專案的專案最新進度"
        binder, descriptor, arguments, _ = self._field_plan(
            family="document_text", user_text=text, field="專案最新進度", terms=("clienta", "標籤機專案"),
        )
        arguments["query_text"] = "Retrieve source evidence: " + text
        request = orchestrator._parse_tool_request(arguments, tool_descriptor=descriptor,
                                                   request_contract_binder=binder)
        split = {**arguments, "required_terms": ["clienta", "標籤機", "專案"]}
        # Outside the one-shot grant the piece is still a field-role overlap.
        with self.assertRaisesRegex(ContractValidationError, "overlaps a requested output field"):
            orchestrator._UatTurnRequestContractBinder(
                user_text=text, authorized_capability_summary={"source_families": ["document_text"]},
            ).bind_required_terms(split["required_terms"], request_contract=arguments["request_contract"])
        self.assertTrue(binder.arm_split_refinement(request, self._split_recovery(request), remaining_calls=2))
        accepted = orchestrator._parse_tool_request(split, tool_descriptor=descriptor, request_contract_binder=binder)
        self.assertEqual(set(accepted.required_terms), {"clienta", "標籤機", "專案"})

    def test_split_protects_existing_identifier_retained_and_shared_reviewed_surfaces(self):
        for identity, proposed, kind in (
            ("AB-1234", ["ab", "1234", "label", "project"], "protected"),
            ("aster works", ["aster", "works", "label", "project"], "reviewed"),
            ("青禾科技", ["青禾", "科技", "label", "project"], "reviewed"),
        ):
            with self.subTest(kind=kind, identity=identity):
                binder, descriptor, arguments, _, request = self._split_plan(
                    terms=(identity, "label project"),
                    user_text=f"Find progress for {identity} label project in documents.",
                )
                if kind == "reviewed":
                    binder._annotation_catalog = {"entries": [{"annotation_id": "synthetic-reviewed", "target": identity}]}
                self.assertTrue(binder.arm_split_refinement(request, self._split_recovery(request), remaining_calls=2))
                with self.assertRaises(ContractValidationError):
                    binder.bind_required_terms(proposed)
                # The same identity may remain whole while another term is split.
                self.assertEqual(binder.bind_required_terms([identity, "label", "project"]),
                                 tuple(sorted((identity.casefold(), "label", "project"))))
        binder, _, _, _, request = self._split_plan()
        binder._reference_binding = {"identifier": "aster"}
        self.assertTrue(binder.arm_split_refinement(request, self._split_recovery(request), remaining_calls=2))
        with self.assertRaises(ContractValidationError):
            binder.bind_required_terms(["as", "ter", "label", "project"])
        binder, _, _, _, request = self._split_plan(terms=("AB-1234 label project",),
            user_text="Find progress for AB-1234 label project in documents.")
        self.assertTrue(binder.arm_split_refinement(request, self._split_recovery(request), remaining_calls=2))
        with self.assertRaises(ContractValidationError):
            binder.bind_required_terms(["ab", "1234", "label", "project"])
        self.assertEqual(binder.bind_required_terms(["ab-1234", "label", "project"]),
                         ("ab-1234", "label", "project"))
        # Unknown names have no invented role classification under the authorized boundary.
        binder, _, _, _, request = self._split_plan(terms=("青禾科技", "label project"),
            user_text="Find progress for 青禾科技 label project in documents.")
        self.assertTrue(binder.arm_split_refinement(request, self._split_recovery(request), remaining_calls=2))
        self.assertEqual(binder.bind_required_terms(["青禾", "科技", "label", "project"]),
                         tuple(sorted(("青禾", "科技", "label", "project"))))

    def test_split_offer_requires_eligible_unchanged_zero_result_and_remaining_budget(self):
        for case in ("null", "missing", "different_variant", "different_fingerprints", "cited", "error",
                     "exact", "table", "comparison", "no_budget", "unattempted"):
            with self.subTest(case=case):
                binder, _, _, _, request = self._split_plan()
                result = self._split_recovery(request)
                recovery = result["query_agent"]["context_bundle"]["source_recovery"]
                if case == "missing":
                    recovery.pop("recheck_variant")
                elif case == "different_variant":
                    recovery["recheck_variant"] = "identity_only"
                elif case == "different_fingerprints":
                    recovery.update(initial_required_terms_fingerprint="first", recheck_required_terms_fingerprint="different")
                elif case == "cited":
                    result["citations"] = ["synthetic-citation"]
                elif case == "error":
                    result["query_agent"]["status"] = "error"
                elif case == "exact":
                    request = orchestrator.replace(request, request_contract={**request.request_contract,
                        "query_class": "exact_set_or_inventory", "maximum_claim_strength":
                        orchestrator.SEMANTIC_CLAIM_STRENGTH_BY_CLASS["exact_set_or_inventory"]})
                elif case == "table":
                    request = orchestrator.replace(request, table_query={
                        "filters": [{"field": "category", "value": "archived"}], "projection_fields": ["category"]})
                elif case == "comparison":
                    binder._comparison_targets = ("ab-123", "cd-456")
                elif case == "unattempted":
                    recovery["attempted"] = False
                expected = case in {"null", "missing"}
                self.assertEqual(binder.arm_split_refinement(request, result,
                    remaining_calls=0 if case == "no_budget" else 2), expected)

    def test_split_loop_one_offer_second_zero_stops_and_invalid_next_proposal_consumes_it(self):
        for case in ("second_zero", "invalid_next", "second_cited", "second_zero_no_recovery"):
            invalid_next = case == "invalid_next"
            with self.subTest(case=case):
                _, descriptor, arguments, capabilities, _ = self._split_plan()
                provider = CodexResponsesConversationModel(base_url="https://provider.example.test/v1", api_key="synthetic-key")
                provider.configure_conversation_tools(safety_identifier="synthetic-split-turn",
                                                      tool_descriptors=[descriptor])
                payloads, requests, stages = [], [], []

                def response(payload):
                    payloads.append(copy.deepcopy(payload))
                    index = len(payloads)
                    self.assertEqual(payload["tools"], payloads[0]["tools"])
                    self.assertEqual(payload["prompt_cache_key"], payloads[0]["prompt_cache_key"])
                    if index > 1:
                        prefix = payloads[-2]["input"]
                        self.assertEqual(payload["input"][:len(prefix)], prefix)
                    if index == 2:
                        envelope = json.loads(next(item["output"] for item in reversed(payload["input"])
                                                   if item.get("type") == "function_call_output"))
                        self.assertIn("split_only_refinement", envelope["execution_control"])
                        self.assertIs(envelope["execution_control"]["split_only_refinement"], True)
                        self.assertTrue(any(item.get("role") == "developer"
                            and item.get("content") == orchestrator._SPLIT_ONLY_REPLAN_GUIDANCE for item in payload["input"]))
                        self.assertIn("identity names whole", orchestrator._SPLIT_ONLY_REPLAN_GUIDANCE)
                    if index == 3:
                        self.assertEqual(case, "second_cited")
                        self.assertEqual(payload["tool_choice"], "none")
                        return {"status": "completed", "output_text": _decision(citation="synthetic-citation")}
                    terms = arguments["required_terms"] if index == 1 else ["aster", "label", "project"]
                    if invalid_next and index == 2:
                        terms = [*terms, "spare"]
                    return {"status": "completed", "output": [{"type": "function_call", "call_id": f"split-call-{index}",
                        "name": descriptor["name"], "arguments": json.dumps({**arguments, "required_terms": terms})}]}

                def backend(request):
                    requests.append(request)
                    if len(requests) == 2 and case == "second_cited":
                        return {"status": "partial", "coverage": {"status": "incomplete"},
                                "evidence": [{"citation_hash": "synthetic-citation", "snippet": "Bounded source evidence."}],
                                "citations": ["synthetic-citation"]}
                    if len(requests) == 2 and case == "second_zero_no_recovery":
                        return {"status": "no_answer", "citations": []}
                    return self._split_recovery(request)

                token = orchestrator._PRIVATE_UAT_CITATION_TRACE.set(stages)
                try:
                    with mock.patch.object(provider, "_request_response", side_effect=response):
                        outcome = provider.respond(history=(),
                            user_text="Find progress for aster label project spare in documents.", latest_evidence=None,
                            safety_identifier="synthetic-split-turn", evidence_tool=backend,
                            formowl_tool_descriptor=descriptor, authorized_capability_summary=capabilities)
                finally:
                    orchestrator._PRIVATE_UAT_CITATION_TRACE.reset(token)
                    provider.close()
                self.assertEqual(outcome.response_kind, "answer" if case == "second_cited" else "clarification")
                self.assertEqual(outcome.citation_ids, ("synthetic-citation",) if case == "second_cited" else ())
                self.assertEqual(len(requests), 1 if invalid_next else 2)
                self.assertEqual(len(payloads), 3 if case == "second_cited" else 2)
                if case == "second_cited":
                    record, = outcome.provider_diagnostic["finalization_validation"]
                    self.assertEqual(record["validation_result"], "passed")
                self.assertEqual([s["status"] for s in stages if s.get("stage") == "split_only_refinement"],
                                 ["offered"] if invalid_next else ["offered", "accepted"])

    def test_split_refinement_reaches_backend_through_runtime_server_binder(self):
        from formowl_gateway import issue56_uat_runtime as runtime

        _, descriptor, arguments, capabilities, _ = self._split_plan()
        text = "Find progress for aster label project spare in documents."
        provider = CodexResponsesConversationModel(base_url="https://provider.example.test/v1", api_key="synthetic-key")
        provider.configure_conversation_tools(safety_identifier="synthetic-split-runtime", tool_descriptors=[descriptor])
        payloads, requests, stages = [], [], []

        def response(payload):
            payloads.append(payload)
            if len(payloads) == 3:
                return {"status": "completed", "output_text": _decision(citation="synthetic-citation")}
            terms = arguments["required_terms"] if len(payloads) == 1 else ["aster", "label", "project"]
            return {"status": "completed", "output": [{"type": "function_call", "call_id": f"split-rt-{len(payloads)}",
                "name": descriptor["name"], "arguments": json.dumps({**arguments, "required_terms": terms})}]}

        def backend(request):
            requests.append(request)
            if len(requests) == 2:
                return {"status": "partial", "coverage": {"status": "incomplete"},
                        "evidence": [{"citation_hash": "synthetic-citation", "snippet": "Bounded source evidence."}],
                        "citations": ["synthetic-citation"]}
            return self._split_recovery(request)

        token = orchestrator._PRIVATE_UAT_CITATION_TRACE.set(stages)
        try:
            with mock.patch.object(provider, "_request_response", side_effect=response):
                _, _, outcome = runtime._run_gpt_query_agent(
                    provider, prompt=text, history=(), latest_evidence=None,
                    safety_identifier="synthetic-split-runtime", formowl_tool_descriptor=descriptor,
                    authorized_capability_summary=capabilities, mcp_call=backend,
                )
        finally:
            orchestrator._PRIVATE_UAT_CITATION_TRACE.reset(token)
            provider.close()
        self.assertEqual(len(requests), 2)
        self.assertEqual(set(requests[1].required_terms), {"aster", "label", "project"})
        self.assertEqual(outcome.citation_ids, ("synthetic-citation",))
        # Only the conversation binder traces; the server binder mirrors silently.
        self.assertEqual([s["status"] for s in stages if s.get("stage") == "split_only_refinement"],
                         ["offered", "accepted"])

    def test_websocket_transport_drop_resends_the_identical_request_once(self):
        for drops in (1, 2):
            with self.subTest(drops=drops):
                _, descriptor, arguments, capabilities, _ = self._split_plan()
                provider = CodexResponsesConversationModel(base_url="https://provider.example.test/v1", api_key="synthetic-key")
                provider.configure_conversation_tools(safety_identifier="synthetic-drop", tool_descriptors=[descriptor])
                payloads, requests = [], []

                def response(payload):
                    payloads.append(copy.deepcopy(payload))
                    if len(payloads) == 1:
                        return {"status": "completed", "output": [{"type": "function_call", "call_id": "drop-call",
                            "name": descriptor["name"], "arguments": json.dumps(arguments)}]}
                    if len(payloads) <= 1 + drops:
                        raise orchestrator._UatProviderFailure(
                            reason_code="transport_error", failure_phase="websocket_read",
                            transport_exception=OSError("synthetic reset"))
                    return {"status": "completed", "output_text": _decision(citation="synthetic-citation")}

                def backend(request):
                    requests.append(request)
                    return {"status": "partial", "coverage": {"status": "incomplete"},
                            "evidence": [{"citation_hash": "synthetic-citation", "snippet": "Bounded source evidence."}],
                            "citations": ["synthetic-citation"]}

                try:
                    with mock.patch.object(provider, "_request_response", side_effect=response):
                        outcome = provider.respond(history=(),
                            user_text="Find progress for aster label project spare in documents.", latest_evidence=None,
                            safety_identifier="synthetic-drop", evidence_tool=backend,
                            formowl_tool_descriptor=descriptor, authorized_capability_summary=capabilities)
                finally:
                    provider.close()
                self.assertEqual(len(requests), 1)
                if drops == 1:
                    self.assertEqual(len(payloads), 3)
                    self.assertEqual(payloads[2]["input"], payloads[1]["input"])
                    self.assertEqual(outcome.response_kind, "answer")
                    self.assertEqual(outcome.citation_ids, ("synthetic-citation",))
                else:
                    # A second drop is not retried again.
                    self.assertEqual(len(payloads), 3)
                    self.assertNotEqual(outcome.response_kind, "answer")

    def test_ignored_required_split_proposal_resends_the_identical_request_once(self):
        for ignores in (1, 2):
            with self.subTest(ignores=ignores):
                _, descriptor, arguments, capabilities, _ = self._split_plan()
                provider = CodexResponsesConversationModel(base_url="https://provider.example.test/v1", api_key="synthetic-key")
                provider.configure_conversation_tools(safety_identifier="synthetic-ignore", tool_descriptors=[descriptor])
                payloads, requests = [], []

                def call(terms):
                    return {"status": "completed", "output": [{"type": "function_call", "call_id": f"ignore-{len(payloads)}",
                        "name": descriptor["name"], "arguments": json.dumps({**arguments, "required_terms": terms})}]}

                def response(payload):
                    payloads.append(copy.deepcopy(payload))
                    index = len(payloads)
                    if index == 1:
                        return call(arguments["required_terms"])
                    if index <= 1 + ignores:
                        self.assertNotEqual(payload["tool_choice"], "auto")
                        return {"status": "completed", "output_text": _decision(citation="synthetic-citation")}
                    if index == 2 + ignores:
                        return call(["aster", "label", "project"])
                    return {"status": "completed", "output_text": _decision(citation="synthetic-citation")}

                def backend(request):
                    requests.append(request)
                    if len(requests) == 2:
                        return {"status": "partial", "coverage": {"status": "incomplete"},
                                "evidence": [{"citation_hash": "synthetic-citation", "snippet": "Bounded source evidence."}],
                                "citations": ["synthetic-citation"]}
                    return self._split_recovery(request)

                try:
                    with mock.patch.object(provider, "_request_response", side_effect=response):
                        outcome = provider.respond(history=(),
                            user_text="Find progress for aster label project spare in documents.", latest_evidence=None,
                            safety_identifier="synthetic-ignore", evidence_tool=backend,
                            formowl_tool_descriptor=descriptor, authorized_capability_summary=capabilities)
                finally:
                    provider.close()
                if ignores == 1:
                    self.assertEqual(payloads[2]["input"], payloads[1]["input"])
                    self.assertEqual(len(requests), 2)
                    self.assertEqual(outcome.citation_ids, ("synthetic-citation",))
                else:
                    # A second ignored requirement keeps the existing zero-evidence stop.
                    self.assertEqual(len(payloads), 3)
                    self.assertEqual(len(requests), 1)
                    self.assertEqual(outcome.citation_ids, ())

    def test_finalization_reason_codes_preserve_stop_classification_and_safe_projection(self):
        valid = json.loads(_decision(citation="synthetic-citation"))
        cases = [
            ("", "no_text", "Codex returned no UAT answer"),
            ("{", "invalid_json", "Codex returned an invalid UAT answer"),
            (json.dumps({**valid, "extra": "private-rejected-draft"}), "key_set_mismatch",
             "Codex returned an invalid UAT answer"),
            (json.dumps({**valid, "citation_ids": "wrong"}), "citation_ids_not_array",
             "Codex returned an invalid UAT answer"),
            (json.dumps({**valid, "answer_text": "x" * (orchestrator._MAX_ANSWER_CHARS + 1)}),
             "answer_text_invalid", "UAT answer text is invalid"),
            (json.dumps({**valid, "coverage_status": "invalid"}), "coverage_status_invalid",
             "UAT coverage status is invalid"),
            (json.dumps({**valid, "citation_ids": ["same", "same"]}), "citation_ids_duplicate",
             "UAT citation identifiers must be unique"),
        ]
        for text, reason, legacy_message in cases:
            with self.subTest(reason=reason):
                with self.assertRaises((ContractValidationError, RuntimeError)) as caught:
                    orchestrator._parse_decision(text)
                self.assertEqual(str(caught.exception), legacy_message)
                self.assertEqual(orchestrator._finalization_validation_reason(caught.exception), reason)
                self.assertEqual(orchestrator._finalization_stop_reason(caught.exception),
                                 orchestrator._finalization_stop_reason(RuntimeError(legacy_message)))
                record = orchestrator._finalization_validation_diagnostic(
                    final_citation_ids=(), available_citation_ids=(),
                    validation_result="parse_rejected", repair_attempted=False, reason_code=reason,
                )
                outcome = orchestrator.UatConversationOutcome(
                    response_kind="clarification", answer_text="Synthetic clarification.",
                    display_format="narrative", model_name="synthetic-model",
                    provider_diagnostic={"finalization_validation": [record]},
                )
                projected = _browser_projection(outcome, (), latest_evidence=None)
                http = _safe_provider_diagnostic(projected["diagnostic"])
                self.assertEqual(http["finalization_validation"][0]["reason_code"], reason)
                for unsafe in ("private-rejected-draft", ["not-a-code"], None):
                    record["reason_code"] = unsafe
                    sanitized = orchestrator.safe_provider_loop_diagnostics({"finalization_validation": [record]})
                    self.assertEqual(sanitized["finalization_validation"][0]["reason_code"], "other")
                del record["reason_code"]
                self.assertNotIn("reason_code", orchestrator.safe_provider_loop_diagnostics(
                    {"finalization_validation": [record]})["finalization_validation"][0])
        self.assertEqual(orchestrator._finalization_validation_reason(RuntimeError("private-rejected-draft")),
                         "other")

    def test_typed_finalization_reasons_distinguish_rules_without_changing_rejection(self):
        binder, descriptor, arguments, _ = self._field_plan(
            family="mail", user_text="Find inspection interval for prism compass.",
            field="inspection interval", terms=("prism compass",),
        )
        request = orchestrator._parse_tool_request(arguments, tool_descriptor=descriptor,
                                                    request_contract_binder=binder)
        valid = {**json.loads(_decision(citation="synthetic-citation")),
                 "coverage_note": "", "field_limitations": []}
        item = {"field_index": 0, "reason": "not_established", "scope": "presented_evidence"}
        cases = [
            ({"coverage_note": "not-empty"}, "coverage_note_not_empty"),
            ({"field_limitations": {}}, "limitations_not_array"),
            ({"field_limitations": [item] * 9}, "limitations_limit"),
            ({"coverage_status": "invalid"}, "coverage_status_invalid"),
            ({"response_kind": "clarification", "field_limitations": [item]}, "clarification_with_limitations"),
            ({"field_limitations": [{**item, "extra": True}]}, "item_keys_invalid"),
            ({"field_limitations": [{**item, "field_index": True}]}, "index_out_of_range"),
            ({"field_limitations": [{**item, "field_index": 1}]}, "index_out_of_range"),
            ({"field_limitations": [item, item]}, "duplicate_index"),
            ({"field_limitations": [{**item, "reason": "invalid"}]}, "reason_invalid"),
            ({"field_limitations": [{**item, "scope": "invalid"}]}, "scope_invalid"),
            ({"field_limitations": [{**item, "scope": "unverified_requested_remainder", "reason": "ambiguous"}]},
             "remainder_reason_invalid"),
            ({"field_limitations": [{**item, "scope": "unverified_requested_remainder"}]}, "remainder_unsupported"),
        ]
        for changes, suffix in cases:
            with self.subTest(reason=suffix):
                with self.assertRaises(RuntimeError) as caught:
                    orchestrator._parse_decision(json.dumps({**valid, **changes}), typed_evidence_notes=True,
                                                 field_request=request)
                reason = "typed_note_" + suffix
                self.assertEqual(orchestrator._finalization_validation_reason(caught.exception), reason)
                self.assertEqual(orchestrator._finalization_stop_reason(caught.exception), "provider_incomplete")
                self.assertEqual(str(caught.exception), "Codex returned unsupported typed remainder scope"
                                 if suffix == "remainder_unsupported" else "Codex returned invalid typed evidence notes")

    def _typed_finalization_turn(self, *, citeable, malformed=False):
        user_text = "Find inspection interval for prism compass in mail."
        _, descriptor, arguments, capabilities = self._field_plan(
            family="mail", user_text=user_text, field="inspection interval", terms=("prism compass",),
        )
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="synthetic-key", typed_evidence_notes=True,
        )
        provider.configure_conversation_tools(safety_identifier="typed-finalization-test",
                                              tool_descriptors=[descriptor])
        evidence = {"status": "ok" if citeable else "no_results", "coverage": {"status": "incomplete"},
                    "mail_import_session_id": "authorized-session", "citations": []}
        citation = "sha256:" + "a" * 64
        if citeable:
            evidence.update({"evidence_snippets": [{"source_observation_id": "synthetic-observation",
                                                    "snippet": "Synthetic inspection interval evidence."}],
                             "citations": [{"citation_id": citation,
                                            "source_observation_id": "synthetic-observation"}]})
        payloads = []

        def response(payload):
            payloads.append(copy.deepcopy(payload))
            self.assertIn("field_limitations", payload["text"]["format"]["schema"]["required"])
            if len(payloads) == 1:
                return {"status": "completed", "output": [{"type": "function_call", "call_id": "synthetic-call",
                        "name": descriptor["name"], "arguments": json.dumps(arguments)}]}
            decision = {**json.loads(_decision(citation=citation)), "coverage_note": "", "field_limitations": []}
            if not citeable:
                decision.update(response_kind="clarification", citation_ids=[])
            if malformed and len(payloads) == 2:
                decision.update(answer_text="private-rejected-draft", field_limitations=[{
                    "field_index": 1, "reason": "ambiguous", "scope": "presented_evidence"}])
            if len(payloads) == 3:
                repair = payload["input"][-1]["content"]
                self.assertIn("typed_note_index_out_of_range", repair)
                self.assertIn("N=1", repair)
                self.assertIn("from 0 through N-1", repair)
                self.assertIn("For clarification, field_limitations must be []", repair)
                self.assertNotIn("private-rejected-draft", json.dumps(payload))
                self.assertEqual(payload["tools"], payloads[0]["tools"])
                self.assertEqual(payload["tool_choice"], "none")
            return {"status": "completed", "output_text": json.dumps(decision)}

        backend = mock.Mock(return_value=evidence)
        try:
            with mock.patch.object(provider, "_request_response", side_effect=response):
                outcome = provider.respond(
                    history=(), user_text=user_text, latest_evidence=None, safety_identifier="typed-finalization-test",
                    evidence_tool=backend, formowl_tool_descriptor=descriptor,
                    authorized_capability_summary=capabilities,
                )
        finally:
            provider.close()
        self.assertEqual(backend.call_count, 1, (outcome.provider_diagnostic, len(payloads)))
        return outcome, payloads

    def test_no_evidence_typed_schema_parses_but_still_safely_stops(self):
        for malformed in (False, True):
            with self.subTest(malformed=malformed):
                outcome, payloads = self._typed_finalization_turn(citeable=False, malformed=malformed)
                self.assertEqual(len(payloads), 2)
                self.assertEqual(outcome.response_kind, "clarification")
                self.assertEqual(outcome.citation_ids, ())
                record, = outcome.provider_diagnostic["finalization_validation"]
                self.assertEqual(record["validation_result"], "parse_rejected" if malformed else "citation_rejected")
                self.assertEqual(record["reason_code"], "typed_note_clarification_with_limitations"
                                 if malformed else "no_citeable_evidence")
                self.assertFalse(record["repair_attempted"])

    def test_typed_finalization_one_repair_gets_current_catalog_rule_without_draft(self):
        outcome, payloads = self._typed_finalization_turn(citeable=True, malformed=True)
        self.assertEqual(len(payloads), 3)
        self.assertEqual(outcome.response_kind, "answer")
        records = outcome.provider_diagnostic["finalization_validation"]
        self.assertEqual([v["validation_result"] for v in records], ["parse_rejected", "passed"])
        self.assertEqual([v["repair_attempted"] for v in records], [False, True])
        self.assertEqual(records[0]["reason_code"], "typed_note_index_out_of_range")

    def _field_plan(self, *, family, user_text, field="category", terms=("cerulean catalog", "category")):
        tool_name = "query_mail_evidence" if family == "mail" else "query_effective_graph_view"
        descriptor = next(
            tool.model_dump(by_alias=True, exclude_none=True)
            for tool in build_remote_tool_descriptors(
                required_scope="formowl.use", enabled_tool_names={"whoami", tool_name},
            ) if tool.name == tool_name
        )
        capabilities = {"source_families": [family]}
        if family == "mail":
            capabilities.update({"mail_selector_kind": "mail_import_session_id",
                                 "authorized_mail_import_session_ids": ["authorized-session"]})
        binder = orchestrator._UatTurnRequestContractBinder(
            user_text=user_text, authorized_capability_summary=capabilities,
        )
        query_class = orchestrator.deterministic_query_class(user_text)
        arguments = {
            "query_text": "Retrieve requested attributes from authorized source evidence.",
            "required_terms": list(terms),
            "request_contract": {
                "original_query_hash": "sha256:" + hashlib.sha256(user_text.encode()).hexdigest(),
                "query_class": query_class, "source_family_scope": [family],
                "requested_fields": [field],
                "maximum_claim_strength": orchestrator.SEMANTIC_CLAIM_STRENGTH_BY_CLASS[query_class],
            },
        }
        if family == "mail":
            arguments["mail_import_session_id"] = "authorized-session"
        return binder, descriptor, arguments, capabilities

    def test_output_projection_terms_reject_without_freeze_then_valid_repair_freezes(self):
        cases = (
            ("Find category for cerulean catalog.", "category", "category", "cerulean catalog"),
            ('Find "category" for cerulean catalog.', "category", "category", "cerulean catalog"),
            ('Find "ＣＡＴＥＧＯＲＹ" for cerulean catalog.', "CaTeGoRy", "ＣＡＴＥＧＯＲＹ", "cerulean catalog"),
            ("查找虛構目錄的「合成標籤」。", "合成標籤", "合成標籤", "虛構目錄"),
        )
        for family in ("mail", "document_text"):
            for user_text, field, output_term, anchor in cases:
                with self.subTest(family=family, field=field, user_text=user_text):
                    binder, descriptor, arguments, _ = self._field_plan(
                        family=family, user_text=user_text, field=field, terms=(anchor, output_term),
                    )
                    with self.assertRaisesRegex(ContractValidationError, "requested output field"):
                        orchestrator._parse_tool_request(
                            arguments, tool_descriptor=descriptor, request_contract_binder=binder,
                        )
                    self.assertIsNone(binder._required_terms)
                    self.assertIsNone(binder._contract)
                    fixed = {**arguments, "required_terms": [anchor]}
                    request = orchestrator._parse_tool_request(
                        fixed, tool_descriptor=descriptor, request_contract_binder=binder,
                    )
                    normalized_anchor = unicodedata.normalize("NFKC", anchor).casefold()
                    self.assertEqual(request.required_terms, (normalized_anchor,))
                    self.assertEqual(binder._required_terms, request.required_terms)
                    self.assertEqual(request.request_contract["requested_fields"], [field])
                    self.assertEqual(request.request_contract["source_family_scope"], [family])
                    repeated = orchestrator._parse_tool_request(
                        fixed, tool_descriptor=descriptor, request_contract_binder=binder,
                    )
                    self.assertEqual(repeated, request)
                    with self.assertRaisesRegex(ContractValidationError, "changed within the turn"):
                        orchestrator._parse_tool_request(
                            {**arguments, "required_terms": [output_term]},
                            tool_descriptor=descriptor, request_contract_binder=binder,
                        )
                    self.assertEqual(binder._required_terms, request.required_terms)

    def test_decorated_fields_reject_provisionally_then_repair_without_losing_anchors(self):
        cases = (
            ("prism compass", "inspection interval", "prism compass's inspection interval"),
            ("林予安", "複核條件", "林予安的複核條件"),
            ("UNIT-T72", "maintenance cadence", "maintenance cadence (UNIT-T72)"),
            ("amber spindle", "inspection interval", "detailed inspection interval"),
            ("木岑", "複核條件", "複核條件補述"),
        )
        for family in ("mail", "document_text"):
            for anchor, field, decorated in cases:
                with self.subTest(family=family, decorated=decorated):
                    binder, descriptor, arguments, _ = self._field_plan(
                        family=family, user_text=f"Find {decorated} for {anchor}.",
                        field=decorated, terms=(anchor, field),
                    )
                    with self.assertRaisesRegex(ContractValidationError, "requested output field"):
                        orchestrator._parse_tool_request(
                            arguments, tool_descriptor=descriptor, request_contract_binder=binder,
                        )
                    self.assertIsNone(binder._contract)
                    self.assertIsNone(binder._required_terms)
                    fixed = {**arguments, "required_terms": [anchor], "request_contract": {
                        **arguments["request_contract"], "requested_fields": [field],
                    }}
                    request = orchestrator._parse_tool_request(
                        fixed, tool_descriptor=descriptor, request_contract_binder=binder,
                    )
                    self.assertEqual(request.required_terms, (anchor.casefold(),))
                    self.assertEqual(request.request_contract["requested_fields"], [field])
                    self.assertEqual(binder._contract, request.request_contract)
                    retry = orchestrator._parse_tool_request(
                        {**fixed, "request_contract": arguments["request_contract"]},
                        tool_descriptor=descriptor, request_contract_binder=binder,
                    )
                    self.assertEqual(retry.request_contract, request.request_contract)

    def test_containment_preserves_identity_substrings_and_explicit_literal_filters(self):
        cases = (
            ("Find annual interval for Ann in the memo.", "annual interval", ("Ann", "memo")),
            ("Find UNIT-T72 details for UNIT in the memo.", "UNIT-T72 details", ("UNIT", "memo")),
            ('Find inspection interval details for prism compass. The content must contain '
             '"inspection interval".', "inspection interval details", ("prism compass", "inspection interval")),
            ("查找林予安的複核條件（說明），內容必須包含「複核條件」字樣。",
             "複核條件（說明）", ("林予安", "複核條件")),
        )
        for family in ("mail", "document_text"):
            for user_text, field, terms in cases:
                with self.subTest(family=family, user_text=user_text):
                    binder, descriptor, arguments, _ = self._field_plan(
                        family=family, user_text=user_text, field=field, terms=terms,
                    )
                    request = orchestrator._parse_tool_request(
                        arguments, tool_descriptor=descriptor, request_contract_binder=binder,
                    )
                    self.assertEqual(request.required_terms, tuple(sorted(term.casefold() for term in terms)))
                    self.assertEqual(request.request_contract["requested_fields"], [field])
            # CJK containment alone cannot distinguish a genuine name from an
            # output label. Clarify the field, keeping the SAME identity term.
            binder, descriptor, arguments, _ = self._field_plan(
                family=family, user_text="查找安禾的平安禾苗紀錄。",
                field="平安禾苗紀錄", terms=("安禾",),
            )
            with self.assertRaisesRegex(ContractValidationError, "requested output field"):
                orchestrator._parse_tool_request(
                    arguments, tool_descriptor=descriptor, request_contract_binder=binder,
                )
            self.assertIsNone(binder._contract)
            self.assertIsNone(binder._required_terms)
            clarified = {**arguments, "request_contract": {
                **arguments["request_contract"], "requested_fields": ["紀錄"],
            }}
            request = orchestrator._parse_tool_request(
                clarified, tool_descriptor=descriptor, request_contract_binder=binder,
            )
            self.assertEqual(request.required_terms, ("安禾",))
            self.assertEqual(request.request_contract["requested_fields"], ["紀錄"])

    def test_invalid_first_tool_shape_cannot_freeze_the_requested_fields(self):
        for family in ("mail", "document_text"):
            with self.subTest(family=family):
                binder, descriptor, arguments, _ = self._field_plan(
                    family=family, user_text="Find inspection interval and gate rationale for prism compass.",
                    field="inspection interval", terms=("prism compass",),
                )
                with self.assertRaises(ContractValidationError):
                    orchestrator._parse_tool_request(
                        {**arguments, "limit" if family == "mail" else "page_size": 0},
                        tool_descriptor=descriptor, request_contract_binder=binder,
                    )
                self.assertIsNone(binder._contract)
                self.assertIsNone(binder._required_terms)
                corrected = {**arguments, "request_contract": {
                    **arguments["request_contract"], "requested_fields": ["inspection interval", "gate rationale"],
                }}
                request = orchestrator._parse_tool_request(
                    corrected, tool_descriptor=descriptor, request_contract_binder=binder,
                )
                self.assertEqual(request.request_contract, corrected["request_contract"])

    def test_explicit_output_label_content_and_value_filters_are_preserved(self):
        cases = (
            ("Require literal category and the value archived in the source.", "category"),
            ('Require literal word "category" and the value archived in the source.', "category"),
            ('The content must contain "category" and archived.', "category"),
            ("Require the value is category and archived.", "category"),
            ("Use only entries where marker=category and archived.", "category"),
            ("內容必須包含「合成標籤」字樣與 archived。", "合成標籤"),
        )
        for family in ("mail", "document_text"):
            for clause, field in cases:
                with self.subTest(family=family, clause=clause):
                    user_text = f"Find {field} for cerulean catalog. {clause}"
                    terms = ("cerulean catalog", field, "archived")
                    binder, descriptor, arguments, _ = self._field_plan(
                        family=family, user_text=user_text, field=field, terms=terms,
                    )
                    request = orchestrator._parse_tool_request(
                        arguments, tool_descriptor=descriptor, request_contract_binder=binder,
                    )
                    self.assertEqual(request.required_terms, tuple(sorted(terms)))
                    with self.assertRaisesRegex(ContractValidationError, "changed within the turn"):
                        orchestrator._parse_tool_request(
                            {**arguments, "required_terms": ["cerulean catalog", field]},
                            tool_descriptor=descriptor, request_contract_binder=binder,
                        )
                    self.assertEqual(binder._required_terms, request.required_terms)
        # The new intent mode must not change source-family quotation semantics.
        self.assertTrue(orchestrator._is_explicit_literal_content_term('Find "mail".', "mail"))
        self.assertFalse(orchestrator._is_explicit_literal_content_term(
            'Find "category" for cerulean catalog.', "category", require_explicit_intent=True,
        ))

    def test_output_field_guard_leaves_exact_and_native_table_plans_unchanged(self):
        for structured in (False, True):
            with self.subTest(structured=structured):
                user_text = ("Find category for cerulean catalog with archived values." if structured else
                             "Count category for cerulean catalog.")
                binder, descriptor, arguments, _ = self._field_plan(family="document_text", user_text=user_text)
                if structured:
                    arguments["table_query"] = {"filters": [{"field": "category", "value": "archived"}],
                                                "projection_fields": ["category"]}
                request = orchestrator._parse_tool_request(
                    arguments, tool_descriptor=descriptor, request_contract_binder=binder,
                )
                self.assertEqual(request.required_terms, ("category", "cerulean catalog"))
                self.assertEqual(request.table_query, arguments.get("table_query"))
                self.assertEqual(request.request_contract["query_class"],
                                 "evidence_lookup" if structured else "exact_set_or_inventory")

    def test_provider_loop_repairs_output_term_before_single_backend_evidence_call(self):
        for family in ("mail", "document_text"):
            with self.subTest(family=family):
                label = "mail" if family == "mail" else "documents"
                anchor, field, decorated = (
                    ("prism compass", "inspection interval", "prism compass's inspection interval")
                    if family == "mail" else ("林予安", "複核條件", "林予安的複核條件")
                )
                user_text = f"Find {decorated} in {label}."
                _, descriptor, arguments, capabilities = self._field_plan(
                    family=family, user_text=user_text, field=decorated, terms=(anchor, field),
                )
                fixed = {**arguments, "required_terms": [anchor], "request_contract": {
                    **arguments["request_contract"], "requested_fields": [field],
                }}
                citation = "sha256:" + "a" * 64
                evidence = {"status": "ok", "coverage": {"status": "incomplete"}}
                if family == "mail":
                    evidence.update({"mail_import_session_id": "authorized-session",
                                     "evidence_snippets": [{"source_observation_id": "synthetic-observation",
                                                            "snippet": f"{anchor}: synthetic source note."}],
                                     "citations": [{"citation_id": citation,
                                                    "source_observation_id": "synthetic-observation"}]})
                else:
                    evidence.update({"evidence": [{"citation_hash": citation,
                                                   "snippet": f"{anchor}: synthetic source note."}],
                                     "citations": [citation]})
                backend = mock.Mock(return_value=evidence)
                provider = CodexResponsesConversationModel(
                    base_url="https://provider.example.test/v1", api_key="synthetic-repair-key",
                )
                payloads, binders = [], []
                real_binder = orchestrator._UatTurnRequestContractBinder

                def make_binder(**kwargs):
                    bound = real_binder(**kwargs)
                    binders.append(bound)
                    return bound

                def response(payload):
                    payloads.append(copy.deepcopy(payload))
                    if len(payloads) <= 2:
                        self.assertEqual(backend.call_count, 0)
                        self.assertIsNone(binders[0]._required_terms)
                        self.assertIsNone(binders[0]._contract)
                        if len(payloads) == 2:
                            control = json.loads(next(item["output"] for item in reversed(payload["input"])
                                                      if item.get("type") == "function_call_output"))
                            self.assertEqual(control["data"]["query_agent"]["external_replan"]["reason_code"],
                                             "invalid_arguments")
                            self.assertEqual(control["execution_control"]["remaining_mcp_calls"], 2)
                            self.assertFalse(control["data"]["citations"])
                        return {"status": "completed", "output": [{
                            "type": "function_call", "call_id": f"synthetic-plan-{len(payloads)}",
                            "name": descriptor["name"],
                            "arguments": json.dumps(arguments if len(payloads) == 1 else fixed),
                        }]}
                    self.assertEqual(len(payloads), 3)
                    self.assertEqual(backend.call_count, 1)
                    self.assertEqual(binders[0]._required_terms, (anchor,))
                    self.assertEqual(binders[0]._contract["requested_fields"], [field])
                    return {"status": "completed", "output_text": _decision(citation=citation)}

                try:
                    with (mock.patch.object(provider, "_request_response", side_effect=response),
                          mock.patch.object(orchestrator, "_UatTurnRequestContractBinder", side_effect=make_binder)):
                        outcome = provider.respond(
                            history=(), user_text=user_text, latest_evidence=None,
                            safety_identifier="synthetic-output-term-repair", evidence_tool=backend,
                            formowl_tool_descriptor=descriptor, authorized_capability_summary=capabilities,
                        )
                    self.assertEqual(outcome.response_kind, "answer",
                                     (outcome.provider_diagnostic, len(payloads), backend.call_count))
                    self.assertEqual(outcome.citation_ids, (citation,))
                    self.assertEqual(len(outcome.tool_requests), 1)
                    self.assertEqual(backend.call_count, 1)
                    self.assertEqual(backend.call_args.args[0].required_terms, (anchor,))
                    self.assertEqual(backend.call_args.args[0].request_contract["requested_fields"], [field])
                    self.assertEqual(outcome.provider_diagnostic["provider_attempt_count"], 3)
                    self.assertEqual(len(outcome.provider_diagnostic["mcp_citation_stages"]), 1)
                    self.assertEqual(outcome.provider_diagnostic["mcp_citation_stages"][0]["call_index"], 2)
                finally:
                    provider.close()

    def test_common_provider_guidance_and_repair_hint_use_shared_planning_contract(self):
        tools = {
            tool.name: tool.model_dump(by_alias=True, exclude_none=True)
            for tool in build_remote_tool_descriptors(
                required_scope="formowl.use",
                enabled_tool_names={"whoami", "query_mail_evidence", "query_effective_graph_view"},
            )
        }
        for name in ("query_mail_evidence", "query_effective_graph_view"):
            for app_server in (False, True):
                with self.subTest(tool=name, app_server=app_server):
                    descriptor = copy.deepcopy(tools[name])
                    base, _ = orchestrator._formowl_instruction_bundle(descriptor, app_server=app_server)
                    self.assertIn(EVIDENCE_ANCHOR_FIELD_PLANNING_GUIDANCE, base)
                    self.assertIn(SOURCE_EVIDENCE_RECHECK_PLANNING_GUIDANCE, base)
                    self.assertNotIn("initial retrieval with zero verified citations", base)
                    self.assertNotIn("{anchor_field_guidance}", base)
                    self.assertEqual(descriptor, tools[name])  # No UAT-only schema fork.
        binder = orchestrator._UatTurnRequestContractBinder(
            user_text="Find category for cerulean catalog.",
            authorized_capability_summary={"source_families": ["mail", "document_text"]},
        )
        policy = binder.trusted_context()["binding_policy"]
        self.assertIn(EVIDENCE_ANCHOR_FIELD_PLANNING_GUIDANCE, policy)
        self.assertIn(SOURCE_EVIDENCE_RECHECK_PLANNING_GUIDANCE, policy)
        hint = orchestrator._execution_control_envelope(
            reason="invalid_arguments", remaining_mcp_calls=1,
        )["data"]["query_agent"]["external_replan"]["repair_hint"]
        self.assertIn(EVIDENCE_ANCHOR_FIELD_PLANNING_GUIDANCE, hint)
        self.assertIn("Preserve any already validated selector and request contract", hint)
        self.assertIn("repair a rejected source scope", hint)
        self.assertIn("required_source_family_scope", hint)

    def test_mail_and_text_anchor_projection_and_explicit_filters_keep_frozen_and_terms(self):
        tools = {
            tool.name: tool.model_dump(by_alias=True, exclude_none=True)
            for tool in build_remote_tool_descriptors(
                required_scope="formowl.use",
                enabled_tool_names={"whoami", "query_mail_evidence", "query_effective_graph_view"},
            )
        }
        for family, tool_name, label in (
            ("mail", "query_mail_evidence", "mail"),
            ("document_text", "query_effective_graph_view", "documents"),
        ):
            for literal_filter in (False, True):
                with self.subTest(family=family, literal_filter=literal_filter):
                    user_text = f"Find category for cerulean catalog in {label}."
                    terms = ["cerulean catalog"]
                    if literal_filter:
                        user_text += " Require literal category and the value archived in the source."
                        terms += ["category", "archived"]
                    capabilities = {"source_families": [family]}
                    if family == "mail":
                        capabilities.update({
                            "mail_selector_kind": "mail_import_session_id",
                            "authorized_mail_import_session_ids": ["authorized-session"],
                        })
                    binder = orchestrator._UatTurnRequestContractBinder(
                        user_text=user_text, authorized_capability_summary=capabilities,
                    )
                    arguments = {
                        "query_text": f"Retrieve the requested category from authorized {label} for cerulean catalog.",
                        "required_terms": terms,
                        "request_contract": {
                            "original_query_hash": "sha256:" + hashlib.sha256(user_text.encode()).hexdigest(),
                            "query_class": "evidence_lookup", "source_family_scope": [family],
                            "requested_fields": ["category"], "maximum_claim_strength": "cited_evidence",
                        },
                    }
                    if family == "mail":
                        arguments["mail_import_session_id"] = "authorized-session"
                    request = orchestrator._parse_tool_request(
                        arguments, tool_descriptor=tools[tool_name], request_contract_binder=binder,
                    )
                    self.assertEqual(request.required_terms, tuple(sorted(terms)))
                    self.assertEqual(request.request_contract["requested_fields"], ["category"])
                    self.assertEqual(request.request_contract["source_family_scope"], [family])
                    repeated = orchestrator._parse_tool_request(
                        arguments, tool_descriptor=tools[tool_name], request_contract_binder=binder,
                    )
                    self.assertEqual(repeated.required_terms, request.required_terms)
                    with self.assertRaisesRegex(ContractValidationError, "changed within the turn"):
                        binder.bind_required_terms(terms[:-1] if literal_filter else [*terms, "category"])

    def _public_safety_turn(
        self, *, unsafe_field="answer_text", repair="safe", deadline=False,
        draft_validation="passed",
    ):
        citation = "sha256:" + "a" * 64
        evidence = {
            "status": "ok",
            "mail_import_session_id": "authorized-session",
            "evidence_snippets": [{
                "source_observation_id": "observation-synthetic",
                "snippet": "Bounded authorized source excerpt.",
            }],
            "citations": [{
                "citation_id": citation,
                "source_observation_id": "observation-synthetic",
            }],
            "coverage": {"status": "incomplete"},
        }
        draft = json.loads(_decision(citation=citation))
        draft[unsafe_field] = "/workspace/private/synthetic-answer.txt"
        if draft_validation == "citation_rejected":
            draft["citation_ids"] = ["sha256:" + "c" * 64]
        elif draft_validation == "coverage_rejected":
            draft["coverage_status"] = "complete"
            draft["coverage_note"] = ""
        requests = []
        clock = [1000.0]
        provider = CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1",
            api_key="synthetic-safety-key",
        )

        def response(payload):
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                if draft_validation != "passed":
                    clock[0] += 2
                return {"status": "completed", "output": [{
                    "type": "function_call",
                    "call_id": "call-safety",
                    "name": "query_mail_evidence",
                    "arguments": json.dumps({
                        "query_text": "authorized evidence",
                        "required_terms": ["authorized evidence"],
                        "mail_import_session_id": "authorized-session",
                        "limit": 10,
                    }),
                }]}
            if len(requests) == 2:
                if draft_validation != "passed":
                    clock[0] += 3
                if deadline:
                    clock[0] += 116
                # Exercise native output items, not just the output_text shortcut:
                # the rejected draft must not be replayed to the provider.
                return {"status": "completed", "output": [{
                    "type": "message", "role": "assistant", "content": [{
                        "type": "output_text", "text": json.dumps(draft),
                    }],
                }]}
            self.assertEqual(len(requests), 3, "Only one repair is permitted")
            self.assertEqual(payload["tools"], [])
            self.assertEqual(payload["tool_choice"], "none")
            self.assertNotIn("/workspace/private", json.dumps(payload))
            repair_reason = {
                "passed": "answer_public_safety_failed",
                "citation_rejected": "citation_validation_failed",
                "coverage_rejected": "coverage_validation_failed",
            }[draft_validation]
            self.assertIn(repair_reason, payload["input"][-1]["content"])
            self.assertLessEqual(provider._active_request_timeout_seconds, 115)
            if draft_validation != "passed":
                self.assertEqual(provider._active_request_timeout_seconds, 110)
            repaired = json.loads(_decision(citation=citation))
            if repair == "unsafe":
                repaired["answer_text"] = draft[unsafe_field]
            elif repair == "bad_coverage":
                repaired["coverage_status"] = "complete"
                repaired["coverage_note"] = ""
            elif repair == "bad_citation":
                repaired["citation_ids"] = ["sha256:" + "b" * 64]
            return {"status": "completed", "output_text": json.dumps(repaired)}

        evidence_tool = mock.Mock(return_value=evidence)
        with (
            mock.patch.object(provider, "_request_response", side_effect=response),
            mock.patch.object(orchestrator.time, "monotonic", side_effect=lambda: clock[0]),
        ):
            outcome = provider.respond(
                history=(), user_text="Find authorized evidence.", latest_evidence=None,
                safety_identifier="synthetic-safety-session", evidence_tool=evidence_tool,
                formowl_tool_descriptor=_mail_tool_descriptor(),
                authorized_capability_summary={
                    "source_families": ["mail"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["authorized-session"],
                },
            )
        self.assertEqual(evidence_tool.call_count, 1)
        projected = _browser_projection(outcome, (evidence,), latest_evidence=None)
        assert_no_public_raw_references(projected, "synthetic_safety_projection")
        self.assertEqual(projected["status"], "partial")
        self.assertEqual(projected["citations"], [citation])
        self.assertTrue(projected["clarification"])
        self.assertNotIn("/workspace/private", json.dumps(projected))
        self.assertNotIn("synthetic-safety-key", json.dumps(outcome.provider_diagnostic))
        # Exercise the HTTP projector as well as the runtime projector.
        http_diagnostic = _safe_provider_diagnostic(projected["diagnostic"])
        self.assertEqual(http_diagnostic["answer_projection_result"],
                         projected["diagnostic"]["answer_projection_result"])
        return outcome, projected, requests

    def test_unsafe_final_answer_gets_one_public_safe_repair(self):
        for unsafe_field in ("answer_text", "coverage_note"):
            with self.subTest(unsafe_field=unsafe_field):
                outcome, projected, requests = self._public_safety_turn(unsafe_field=unsafe_field)
                self.assertEqual(len(requests), 3)
                self.assertEqual(outcome.response_kind, "answer")
                self.assertEqual(outcome.coverage_status, "incomplete")
                diagnostic = projected["diagnostic"]
                self.assertEqual(diagnostic["answer_projection_result"], "repair_recovered")
                validations = diagnostic["finalization_validation"]
                self.assertEqual([v["validation_result"] for v in validations], ["passed", "passed"])
                self.assertEqual([v["repair_attempted"] for v in validations], [False, True])
                self.assertEqual(diagnostic["provider_attempt_count"], 3)

    def test_exhausted_public_safety_repair_preserves_truthful_partial_evidence(self):
        for repair, validation in (("unsafe", "passed"), ("bad_coverage", "coverage_rejected"),
                                   ("bad_citation", "citation_rejected")):
            with self.subTest(repair=repair):
                outcome, projected, requests = self._public_safety_turn(repair=repair)
                self.assertEqual(len(requests), 3)
                self.assertEqual(outcome.response_kind, "clarification")
                self.assertIn("未完成", projected["answer"])
                self.assertIn("Bounded authorized source excerpt.", projected["answer"])
                self.assertIn("未證明已完整", projected["clarification"])
                diagnostic = projected["diagnostic"]
                self.assertEqual(diagnostic["answer_projection_result"], "recovery_exhausted")
                self.assertEqual([v["validation_result"] for v in diagnostic["finalization_validation"]],
                                 ["passed", validation])

    def test_public_safety_repair_does_not_reset_expired_turn_deadline(self):
        outcome, projected, requests = self._public_safety_turn(deadline=True)
        self.assertEqual(len(requests), 2)
        self.assertEqual(outcome.response_kind, "clarification")
        diagnostic = projected["diagnostic"]
        self.assertEqual(diagnostic["reason_code"], "turn_budget_exhausted")
        self.assertEqual(diagnostic["answer_projection_result"], "recovery_exhausted")
        self.assertEqual(diagnostic["provider_attempt_count"], 2)
        self.assertEqual(diagnostic["finalization_validation"][0]["validation_result"], "passed")

    def test_unsafe_draft_with_invalid_citation_or_coverage_is_never_replayed(self):
        for validation in ("citation_rejected", "coverage_rejected"):
            with self.subTest(validation=validation):
                outcome, projected, requests = self._public_safety_turn(draft_validation=validation)
                self.assertEqual(len(requests), 3)
                self.assertEqual(outcome.response_kind, "answer")
                records = projected["diagnostic"]["finalization_validation"]
                self.assertEqual([v["validation_result"] for v in records], [validation, "passed"])
                self.assertEqual([v["repair_attempted"] for v in records], [False, True])
                self.assertEqual(projected["diagnostic"]["provider_attempt_count"], 3)

    def test_ordinary_chat_sends_none_when_no_tools_are_selected(self):
        requests: list[dict] = []
        evidence_calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers["Content-Length"])
                requests.append(json.loads(self.rfile.read(length)))
                body = {
                    "status": "completed",
                    "output_text": json.dumps(
                        {
                            "response_kind": "answer",
                            "answer_text": "你好，我可以協助回答一般問題。",
                            "display_format": "narrative",
                            "citation_ids": [],
                            "coverage_status": "not_applicable",
                            "coverage_note": "",
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
                encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = CodexResponsesConversationModel(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="synthetic-local-provider-key",
            )
            outcome = provider.respond(
                history=(),
                user_text="你好，今天好嗎？",
                latest_evidence=None,
                safety_identifier="ordinary-no-tools-local-session",
                evidence_tool=lambda request: evidence_calls.append(request) or {},
                formowl_tool_descriptor=_mail_tool_descriptor(),
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["tools"], [])
        self.assertEqual(requests[0]["tool_choice"], "none")
        self.assertEqual(evidence_calls, [])

    def test_stateless_mail_finalization_replays_encrypted_reasoning_and_tool_pair(self):
        citation = "citation-provider-finalization"
        requests: list[dict] = []
        headers: list[dict[str, str]] = []
        evidence_requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length))
                requests.append(payload)
                headers.append({key: value for key, value in self.headers.items()})
                if len(requests) == 1:
                    body = {
                        "status": "completed",
                        "output": [
                            {
                                "type": "reasoning",
                                "id": "rs-provider-finalization",
                                "encrypted_content": "opaque-reasoning",
                                "content": [],
                                "summary": [],
                            },
                            {
                                "type": "function_call",
                                "call_id": "call-provider-finalization",
                                "name": "query_mail_evidence",
                                "arguments": json.dumps(
                                    {
                                        "query_text": "把授權郵件整理出來",
                                        "required_terms": ["授權郵件"],
                                        "mail_import_session_id": "authorized-session",
                                        "limit": 100,
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                    }
                else:
                    body = {
                        "status": "completed",
                        "output_text": _decision(citation=citation),
                    }
                is_stream = payload.get("stream") is True
                if is_stream:
                    event = {
                        "type": "response.completed",
                        "response": body,
                    }
                    encoded = (
                        b"event: response.completed\n"
                        + b"data: "
                        + json.dumps(event, ensure_ascii=False).encode("utf-8")
                        + b"\n\n"
                    )
                else:
                    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/event-stream" if is_stream else "application/json",
                )
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        original_prompt = "把授權郵件整理出來"
        try:
            provider = CodexResponsesConversationModel(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="synthetic-local-provider-key",
            )
            outcome = provider.respond(
                history=(),
                user_text=original_prompt,
                latest_evidence=None,
                safety_identifier="provider-finalization-local-session",
                evidence_tool=lambda request: (
                    evidence_requests.append(request)
                    or {
                        "status": "ok",
                        "mail_import_session_id": request.mail_import_session_id,
                        "evidence_snippets": [
                            {
                                "citation_id": citation,
                                "snippet": "bounded governed mail evidence",
                            }
                        ],
                        "citations": [citation],
                    }
                ),
                formowl_tool_descriptor=_mail_tool_descriptor(),
                authorized_capability_summary={
                    "source_families": ["mail"],
                    "mail_selector_kind": "mail_import_session_id",
                    "authorized_mail_import_session_ids": ["authorized-session"],
                },
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(len(evidence_requests), 1)
        self.assertEqual(evidence_requests[0].mail_import_session_id, "authorized-session")
        self.assertEqual(evidence_requests[0].required_terms, ("授權郵件",))
        self.assertIsNone(evidence_requests[0].mail_evidence_bundle_id)
        self.assertEqual(evidence_requests[0].limit, 100)
        self.assertIsNone(evidence_requests[0].table_query)
        self.assertIsNone(evidence_requests[0].exact_inventory_kind)
        self.assertIsNone(evidence_requests[0].exact_field)
        self.assertIsNone(evidence_requests[0].page_size)
        self.assertIsNone(evidence_requests[0].cursor)
        request_contract = evidence_requests[0].request_contract
        self.assertEqual(
            request_contract["original_query_hash"],
            "sha256:" + hashlib.sha256(original_prompt.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(request_contract["query_class"], "evidence_lookup")
        self.assertEqual(request_contract["source_family_scope"], ["mail"])
        self.assertEqual(request_contract["maximum_claim_strength"], "cited_evidence")
        self.assertEqual(len(requests), 2)
        self.assertEqual(
            [tool["name"] for tool in requests[0]["tools"]],
            ["query_mail_evidence"],
        )
        self.assertEqual(
            requests[0]["tool_choice"],
            {"type": "function", "name": "query_mail_evidence"},
        )
        self.assertEqual(requests[1]["tools"], [])
        self.assertEqual(requests[1]["tool_choice"], "none")
        self.assertNotIn(
            "clarify_public_terminology",
            json.dumps(requests[0]["tools"]),
        )
        self.assertEqual(requests[0]["max_output_tokens"], 4096)
        self.assertEqual(
            requests[0]["include"],
            ["reasoning.encrypted_content"],
        )
        self.assertEqual(
            requests[1]["include"],
            ["reasoning.encrypted_content"],
        )
        continuation_input = requests[1]["input"]
        reasoning_items = [
            item for item in continuation_input if item.get("type") == "reasoning"
        ]
        self.assertEqual(len(reasoning_items), 1)
        self.assertEqual(
            reasoning_items[0]["encrypted_content"],
            "opaque-reasoning",
        )
        function_calls = [
            item for item in continuation_input if item.get("type") == "function_call"
        ]
        self.assertEqual(
            [item["call_id"] for item in function_calls],
            ["call-provider-finalization"],
        )
        function_outputs = [
            item
            for item in continuation_input
            if item.get("type") == "function_call_output"
        ]
        self.assertEqual(
            [item["call_id"] for item in function_outputs],
            ["call-provider-finalization"],
        )
        self.assertIn(self.wire_ids[citation], function_outputs[0]["output"])
        self.assertEqual(headers[0]["Authorization"], "Bearer synthetic-local-provider-key")
        self.assertEqual(headers[1]["Authorization"], "Bearer synthetic-local-provider-key")
        self.assertIsNot(requests[0].get("stream"), True)
        self.assertIs(requests[1]["stream"], True)
        self.assertEqual(headers[1]["Accept"], "text/event-stream")



class AppServerFinalizationRepairTests(unittest.TestCase):
    """Same-evidence repair uses real parser/validator and model-visible handles."""

    def _turn(self, *, first="coverage", repair="valid", budget=None, overload=False):
        from test_issue56_codex_provider_bridge import _RecordingTransport

        case = self
        user_text = "Find status for ZX-742 in authorized mail."
        _, descriptor, arguments, capabilities = Issue56ProviderFinalizationTests._field_plan(
            self, family="mail", user_text=user_text, field="status", terms=("zx-742",))
        arguments["query_text"] = "Retrieve status evidence for ZX-742 from authorized mail."
        citation = "sha256:" + "c" * 64
        now = [100.0]
        requests, stages, raw_drafts = [], [], []
        result = {"status": "partial", "coverage": {"status": "incomplete"},
                  "evidence": [{"citation_hash": citation, "snippet": "ZX-742 status: reviewed."}],
                  "citations": [citation]}

        def evidence_tool(request):
            requests.append(request)
            return copy.deepcopy(result)

        class Transport(_RecordingTransport):
            def __init__(self):
                super().__init__(calls=(), final_message="unused")
                self.turns = []
                self.output = None

            def run_turn(self, **kwargs):
                self.turns.append(kwargs)
                index = len(self.turns)
                turn_id = f"turn-{index}"
                invocations = ()
                if index == 1:
                    self.output = kwargs["tool_handler"](descriptor["name"], arguments)
                    case.assertEqual(self.output["trust"], "untrusted_evidence")
                    invocations = (orchestrator.CodexDynamicToolInvocation(
                        kwargs["thread_id"], turn_id, "call-1", descriptor["name"], arguments, self.output),)
                    if overload:
                        raise orchestrator._CodexAppServerProviderFailure(
                            "provider_incomplete", "fixed synthetic overload",
                            provider_diagnostic={"codex_error_kind": "serverOverloaded"},
                            completed_tools=orchestrator._CodexCompletedTools(
                                kwargs["thread_id"], turn_id, invocations, 120.0),
                        )
                else:
                    case.assertIs(kwargs["tools_allowed"], False)
                    case.assertEqual(kwargs["thread_id"], self.turns[0]["thread_id"])
                    case.assertEqual(kwargs["output_schema"], self.turns[0]["output_schema"])
                    case.assertEqual(kwargs["reasoning_effort"], self.turns[0]["reasoning_effort"])
                is_repair = index > (2 if overload else 1)
                variant = repair if is_repair else first
                if is_repair and variant == "provider_failure":
                    raise orchestrator._CodexAppServerProviderFailure(
                        "provider_incomplete", "ZX_742_PROVIDER_PRIVATE",
                        provider_diagnostic={"codex_error_kind": "serverOverloaded"})
                if is_repair and variant == "tool_call":
                    kwargs["tool_handler"](descriptor["name"], arguments)
                handle = self.output["data"]["citations"][0]
                draft = json.loads(_decision(citation=handle))
                draft["answer_text"] = "ZX-742 status: reviewed; only the presented scope is supported."
                if variant == "coverage":
                    # Prose already discloses limits: the structured status still fails.
                    draft.update(coverage_status="complete", answer_text="ZX_742_REJECTED_DRAFT; coverage is limited.")
                elif variant == "disclosure":
                    draft["coverage_note"] = ""
                elif variant == "citation_shape":
                    draft["citation_ids"] = [handle, handle]
                raw = "ZX_742_INVALID_JSON" if variant == "nonrepairable" else json.dumps(draft)
                raw_drafts.append(raw)
                deadline = 110.0 if not overload else 130.0
                if budget == "transport_time":
                    deadline = 99.0
                if budget == "turn_time":
                    now[0] = 1000.0
                    deadline = 2000.0
                return orchestrator.CodexAppServerTurn(
                    kwargs["thread_id"], turn_id, raw, invocations, deadline)

        transport = Transport()
        token = orchestrator._PRIVATE_UAT_CITATION_TRACE.set(stages)
        try:
            with tempfile.TemporaryDirectory() as workspace, mock.patch.object(
                orchestrator.time, "monotonic", side_effect=lambda: now[0]
            ), mock.patch.object(orchestrator, "_MAX_PROVIDER_REQUESTS_PER_TURN",
                                 2 if budget == "overload_attempts" else 1 if budget == "attempts" else 6):
                provider = orchestrator.CodexAppServerConversationModel(transport, workspace_dir=workspace)
                outcome = provider.respond(history=(), user_text=user_text, latest_evidence=None,
                    safety_identifier="zx742-repair", evidence_tool=evidence_tool,
                    formowl_tool_descriptor=descriptor, authorized_capability_summary=capabilities)
        finally:
            orchestrator._PRIVATE_UAT_CITATION_TRACE.reset(token)
        self.assertEqual(len(requests), 1)
        return outcome, transport, stages, raw_drafts, ((requests[0], result),)

    def _assert_original_fallback(self, outcome, records):
        expected = orchestrator._safe_stop_outcome(reason="coverage_validation_failed",
            model_name=outcome.model_name, evidence_records=records)
        for field in ("response_kind", "answer_text", "display_format", "citation_ids", "coverage_status", "coverage_note"):
            self.assertEqual(getattr(outcome, field), getattr(expected, field), field)
        self.assertEqual(outcome.tool_results, expected.tool_results)

    def test_app_server_repair_coverage_in_same_thread_without_tools_or_draft_replay(self):
        outcome, transport, stages, drafts, _ = self._turn()
        self.assertEqual(len(transport.turns), 2)
        self.assertEqual(len(transport.thread_starts), 1)
        self.assertEqual(transport.deleted_threads, [])
        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(outcome.coverage_status, "incomplete")
        self.assertEqual(outcome.citation_ids, ("sha256:" + "c" * 64,))
        repair_call = transport.turns[-1]
        self.assertEqual(repair_call["deadline_monotonic"], 110.0)
        context = json.loads(repair_call["additional_context"]["formowl_finalization_repair"]["value"])
        self.assertEqual(context["reason_code"], "incomplete_coverage_hidden")
        self.assertIn("coverage_status=incomplete", context["rule"])
        self.assertNotIn("ZX_742_REJECTED_DRAFT", json.dumps(repair_call, default=str))
        private = [stage for stage in stages if stage.get("stage") == "finalization_rejected_draft"]
        self.assertEqual([stage["draft"] for stage in private], [drafts[0]])
        self.assertEqual(json.loads(private[0]["draft"])["coverage_status"], "complete")
        records = outcome.provider_diagnostic["finalization_validation"]
        self.assertEqual([record["validation_result"] for record in records], ["coverage_rejected", "passed"])
        self.assertTrue(records[-1]["repair_attempted"])
        self.assertEqual(records[-1]["repair_result"], "passed")
        safe = _safe_provider_diagnostic(outcome.provider_diagnostic)
        projected = _browser_projection(outcome, outcome.tool_results, latest_evidence=None)
        for value in (outcome.provider_diagnostic, safe, projected,
                      orchestrator.safe_provider_loop_diagnostics({"finalization_validation": private})):
            self.assertNotIn("ZX_742_REJECTED_DRAFT", json.dumps(value, default=str))
        self.assertEqual(safe["finalization_validation"][-1]["repair_result"], "passed")

    def test_app_server_one_rejected_repair_preserves_original_fallback(self):
        outcome, transport, stages, drafts, records = self._turn(repair="coverage")
        self.assertEqual(len(transport.turns), 2)
        self.assertEqual(transport.deleted_threads, ["thread-1"])
        self._assert_original_fallback(outcome, records)
        self.assertEqual(outcome.provider_diagnostic["finalization_validation"][-1]["repair_result"], "rejected")
        self.assertEqual([s["draft"] for s in stages if s.get("stage") == "finalization_rejected_draft"], drafts)

    def test_app_server_repair_disclosure_and_citation_shape_use_unchanged_validator(self):
        for first, reason in (("disclosure", "incomplete_coverage_undisclosed"),
                              ("citation_shape", "citation_handle_rejected")):
            with self.subTest(first=first):
                outcome, transport, _, _, _ = self._turn(first=first)
                self.assertEqual(len(transport.turns), 2)
                self.assertEqual(outcome.response_kind, "answer")
                self.assertEqual(outcome.provider_diagnostic["finalization_validation"][0]["reason_code"], reason)
                self.assertEqual(outcome.provider_diagnostic["finalization_validation"][-1]["repair_result"], "passed")

    def test_app_server_unclassified_finalization_does_not_repair(self):
        outcome, transport, _, _, _ = self._turn(first="nonrepairable")
        self.assertEqual(len(transport.turns), 1)
        self.assertEqual(outcome.response_kind, "clarification")
        record, = outcome.provider_diagnostic["finalization_validation"]
        self.assertEqual(record["reason_code"], "invalid_json")
        self.assertFalse(record["repair_attempted"])
        self.assertEqual(record["repair_result"], "not_attempted")

    def test_app_server_exhausted_original_time_or_attempt_budget_does_not_repair(self):
        for budget in ("transport_time", "turn_time", "attempts"):
            with self.subTest(budget=budget):
                outcome, transport, _, _, records = self._turn(budget=budget)
                self.assertEqual(len(transport.turns), 1)
                self._assert_original_fallback(outcome, records)
                self.assertFalse(outcome.provider_diagnostic["finalization_validation"][-1]["repair_attempted"])

    def test_app_server_repair_failure_or_tool_attempt_cannot_replay_tools(self):
        for repair in ("provider_failure", "tool_call"):
            with self.subTest(repair=repair):
                outcome, transport, _, _, records = self._turn(repair=repair)
                self.assertEqual(len(transport.turns), 2)
                self._assert_original_fallback(outcome, records)
                self.assertEqual(outcome.provider_diagnostic["finalization_validation"][-1]["repair_result"], "failed")
                self.assertNotIn("ZX_742_PROVIDER_PRIVATE", json.dumps(outcome.provider_diagnostic))

    def test_app_server_overload_recovery_and_validation_repair_share_remaining_budgets(self):
        for budget, expected in ((None, 3), ("overload_attempts", 2)):
            with self.subTest(budget=budget):
                outcome, transport, _, _, records = self._turn(overload=True, budget=budget)
                self.assertEqual(len(transport.turns), expected)
                self.assertEqual(transport.turns[1]["deadline_monotonic"], 120.0)
                if budget:
                    self._assert_original_fallback(outcome, records)
                    self.assertFalse(outcome.provider_diagnostic["finalization_validation"][-1]["repair_attempted"])
                else:
                    self.assertEqual(transport.turns[2]["deadline_monotonic"], 120.0)
                    self.assertEqual(outcome.response_kind, "answer")
                    self.assertTrue(outcome.provider_diagnostic["finalization_validation"][-1]["repair_attempted"])

    def test_app_server_transport_receipt_preserves_deadline_and_enforces_tools_disabled(self):
        wire = object.__new__(orchestrator.CodexAppServerStdioTransport)
        wire._state_lock = threading.RLock()
        wire._thread_locks, wire._active_turns = {}, {}
        wire._timeout_seconds = 10.0
        wire._fatal_error = False
        wire._closed = False
        starts = []

        def request(method, params, **kwargs):
            self.assertEqual(method, "turn/start")
            starts.append(kwargs)
            wire._deliver_turn_completion({"threadId": params["threadId"], "turn": {
                "id": "turn-deadline", "status": "completed",
                "items": [{"type": "agentMessage", "text": _decision(citation="C1")}],
            }})
            return {"turn": {"id": "turn-deadline"}}

        wire._request = request
        handler = mock.Mock()
        with mock.patch.object(orchestrator.time, "monotonic", return_value=100.0):
            turn = wire.run_turn(thread_id="thread-zx742", user_text="ZX-742", additional_context={},
                output_schema=orchestrator._DECISION_SCHEMA, reasoning_effort="high", client_metadata={},
                tool_handler=handler, tools_allowed=False, deadline_monotonic=105.0)
        self.assertEqual(turn.deadline_monotonic, 105.0)
        self.assertEqual(starts, [{"timeout_seconds": 5.0}])
        context = orchestrator._ActiveTurn(thread_id="thread-zx742", tool_handler=handler, tools_allowed=False)
        context.turn_id = "turn-repair"
        context.turn_ready.set()
        wire._active_turns["thread-zx742"] = context
        wire._send_tool_result = mock.Mock()
        wire._handle_server_request({"id": 1, "method": "item/tool/call", "params": {
            "threadId": "thread-zx742", "turnId": "turn-repair", "callId": "call-hostile",
            "tool": "query_mail_evidence", "arguments": {},
        }})
        handler.assert_not_called()
        wire._send_tool_result.assert_called_once_with(1, success=False, payload={"error": "rejected"})
        self.assertEqual(context.tool_error_kind, "contract")

    def test_app_server_unknown_repair_result_is_dropped_by_safe_projection(self):
        for invalid in ("ZX_742_PRIVATE", {"draft": "ZX_742_PRIVATE"}, ["ZX_742_PRIVATE"]):
            with self.subTest(type=type(invalid).__name__):
                record = orchestrator._finalization_validation_diagnostic(final_citation_ids=(),
                    available_citation_ids=(), validation_result="passed", repair_attempted=True,
                    repair_result=invalid)
                self.assertNotIn("repair_result", record)
                record["repair_result"] = invalid
                safe = orchestrator.safe_provider_loop_diagnostics({"finalization_validation": [record]})
                self.assertNotIn("ZX_742_PRIVATE", json.dumps(safe))


class BoundedDowngradeBindingDiagnosticTests(unittest.TestCase):
    """Fictional neutral identifiers; no private replay data or live providers."""

    @staticmethod
    def _result_for(request):
        contract = request.request_contract
        terms = tuple(sorted(unicodedata.normalize("NFKC", term.strip()).casefold()
                             for term in request.required_terms or ()))
        citation = "sha256:" + "d" * 64
        return {
            "status": "partial", "deterministic_exact": False, "exact_result": None,
            "query_hash": orchestrator.sha256_json(request.query_text),
            "coverage": {"status": "incomplete", "absence_claim": False},
            "citations": [citation],
            "evidence": [{"citation_hash": citation, "snippet": "QR-817 status: pending."}],
            "query_agent": {"request_contract": copy.deepcopy(contract)},
            "execution_downgrade": {
                "reason": "exact_table_plan_unavailable",
                "query_hash": orchestrator.sha256_json(request.query_text),
                "request_contract_fingerprint": orchestrator.sha256_json(contract),
                "required_terms_fingerprint": orchestrator.sha256_json(terms),
                "executed_request_contract": {**copy.deepcopy(contract), "query_class": "evidence_lookup",
                                              "maximum_claim_strength": "cited_evidence"},
                "disclosure": "無法做完整清單／確定性計算，以下為引用證據",
            },
        }

    @classmethod
    def _fixture(cls):
        request = orchestrator.UatEvidenceToolRequest(
            query_text="Enumerate QR-817 status from attachment tables.", required_terms=("qr-817",),
            request_contract={
                "original_query_hash": "sha256:" + "a" * 64,
                "query_class": "exact_set_or_inventory", "source_family_scope": ["attachment_table"],
                "requested_fields": ["status"],
                "maximum_claim_strength": orchestrator.SEMANTIC_CLAIM_STRENGTH_BY_CLASS["exact_set_or_inventory"],
            },
        )
        return request, cls._result_for(request)

    @classmethod
    def _failure_cases(cls):
        # Deliberately malformed backend/request doubles exercise every guard
        # without granting those shapes admission through the actual binder.
        from types import SimpleNamespace
        mutations = [
            ("request", ("request_contract",), None, "request_contract_invalid"),
            ("result", ("execution_downgrade",), [], "downgrade_metadata_invalid"),
            ("request", ("request_contract", "query_class"), "evidence_lookup", "original_query_class_invalid"),
            ("request", ("request_contract", "source_family_scope"), ["mail"], "attachment_scope_missing"),
            ("request", ("request_contract", "native_locator"), None, "native_locator_present"),
            ("result", ("status",), "ok", "result_status_invalid"),
            ("result", ("deterministic_exact",), 0, "deterministic_exact_invalid"),
            ("result", ("exact_result",), {}, "exact_result_present"),
            ("result", ("exact_inventory",), None, "exact_inventory_present"),
            ("result", ("query_agent",), [], "binding_metadata_invalid"),
            ("result", ("execution_downgrade", "extra"), None, "downgrade_keys_invalid"),
        ]
        for key in ("table_query", "exact_inventory_kind", "exact_field", "cursor", "required_term_placement"):
            mutations.append(("request", (key,), {}, key + "_present"))
        for prefix in ((), ("query_agent",)):
            for key, value, code in (
                ("failure_reason", "QR817_PRIVATE_SENTINEL", "binding_failure_reason_present"),
                ("reason_code", "QR817_PRIVATE_SENTINEL", "binding_reason_code_present"),
                ("original_query_hash", "sha256:" + "b" * 64, "binding_original_query_hash_mismatch"),
                ("query_hash", "sha256:" + "b" * 64, "binding_query_hash_mismatch"),
                ("source_family_scope", ["document_text"], "binding_source_family_scope_mismatch"),
                ("request_contract", {}, "binding_request_contract_mismatch"),
                ("warnings", "QR817_PRIVATE_SENTINEL", "binding_warnings_invalid"),
                ("warnings", [42], "binding_warnings_invalid"),
                ("stop_reason", 42, "binding_stop_reason_invalid"),
            ):
                mutations.append(("result", prefix + (key,), value, code))
            for token in ("invalid", "ambiguous", "rejected", "permission", "denied", "error", "failed",
                          "binding_mismatch", "binding_missing"):
                for key in ("warnings", "stop_reason"):
                    value = [token.upper()] if key == "warnings" else token.upper()
                    code = "binding_warning_rejected" if key == "warnings" else "binding_stop_reason_rejected"
                    mutations.append(("result", prefix + (key,), value, code))
        for key, code in (
            ("reason", "downgrade_reason_mismatch"), ("query_hash", "downgrade_query_hash_mismatch"),
            ("request_contract_fingerprint", "downgrade_contract_fingerprint_mismatch"),
            ("required_terms_fingerprint", "downgrade_terms_fingerprint_mismatch"),
            ("executed_request_contract", "downgrade_executed_contract_mismatch"),
            ("disclosure", "downgrade_disclosure_mismatch"),
        ):
            mutations.append(("result", ("execution_downgrade", key), "QR817_PRIVATE_SENTINEL", code))
        for target, path, value, code in mutations:
            request, result = cls._fixture()
            attributes = copy.deepcopy(vars(request))
            parent = attributes if target == "request" else result
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] = value
            yield target + "." + ".".join(path), SimpleNamespace(**attributes), result, code
        for key in cls._fixture()[1]["execution_downgrade"]:
            request, result = cls._fixture()
            del result["execution_downgrade"][key]
            yield "missing." + key, request, result, "downgrade_keys_invalid"

    def test_each_failed_predicate_retains_closed_private_subcode(self):
        decision = json.loads(_decision(citation="sha256:" + "d" * 64))
        seen = set()
        for label, request, result, code in self._failure_cases():
            with self.subTest(predicate=label, code=code):
                self.assertFalse(orchestrator._bounded_exact_downgrade_bound(request, result))
                with self.assertRaises(RuntimeError) as caught:
                    orchestrator._disclose_bounded_exact_downgrade(decision, ((request, result),))
                error = caught.exception
                self.assertEqual(orchestrator._finalization_validation_reason(error), "bounded_downgrade_binding_invalid")
                self.assertEqual(orchestrator._finalization_stop_reason(error), "coverage_validation_failed")
                self.assertEqual(error.binding_failure_code, code)
                stages = []
                token = orchestrator._PRIVATE_UAT_CITATION_TRACE.set(stages)
                try:
                    public = orchestrator._finalization_validation_diagnostic(
                        final_citation_ids=(), available_citation_ids=(), validation_result="coverage_rejected",
                        repair_attempted=False, reason_code=error.reason_code,
                        binding_failure_code=error.binding_failure_code,
                    )
                finally:
                    orchestrator._PRIVATE_UAT_CITATION_TRACE.reset(token)
                self.assertEqual(stages[0]["binding_failure_code"], code)
                self.assertNotIn("binding_failure_code", public)
                self.assertNotIn("QR817_PRIVATE_SENTINEL", json.dumps(stages))
                assert_no_public_raw_references(stages, "rc22_private_diagnostic")
                seen.add(code)
        self.assertEqual(seen, orchestrator._BOUNDED_DOWNGRADE_FAILURE_CODES)

    def test_valid_optional_bindings_and_normalized_terms_keep_acceptance_and_disclosure(self):
        from dataclasses import replace
        for status in ("partial", "pending_review", "incomplete"):
            request, result = self._fixture()
            request = replace(request, required_terms=(" ＱＲ-８１７ ", "bb"))
            result = self._result_for(request)
            result.update(status=status, failure_reason="", reason_code=None, warnings=("incomplete",), stop_reason=None)
            result["query_agent"].update(original_query_hash=request.request_contract["original_query_hash"],
                query_hash=orchestrator.sha256_json(request.query_text), source_family_scope=["attachment_table"],
                failure_reason=None, reason_code="", warnings=[], stop_reason="time_budget_exhausted")
            before = copy.deepcopy(result)
            self.assertTrue(orchestrator._bounded_exact_downgrade_bound(request, result))
            decision = json.loads(_decision(citation=result["citations"][0]))
            disclosed = orchestrator._disclose_bounded_exact_downgrade(decision, ((request, result),))
            self.assertEqual(disclosed, {**decision, "coverage_note":
                orchestrator._BOUNDED_EXACT_DOWNGRADE_DISCLOSURE + "。 " + decision["coverage_note"]})
            self.assertEqual(orchestrator._disclose_bounded_exact_downgrade(disclosed, ((request, result),)), disclosed)
            self.assertEqual(result, before)
            self.assertEqual(orchestrator._disclose_bounded_exact_downgrade(decision, ()), decision)

    def _turn(self, kind, *, broken=False, draft_kind="valid"):
        from test_issue56_codex_provider_bridge import _RecordingTransport
        user_text = "請列出附件表格中 QR-817 的所有 status"
        _, descriptor, arguments, capabilities = Issue56ProviderFinalizationTests._field_plan(
            self, family="attachment_table", user_text=user_text, field="status", terms=("qr-817",))
        arguments["query_text"] = "Enumerate QR-817 status from attachment tables."
        tool_requests, turns, stages = [], [], []
        def evidence_tool(request):
            tool_requests.append(request)
            result = self._result_for(request)
            if broken:
                result["execution_downgrade"]["required_terms_fingerprint"] = "sha256:" + "e" * 64
            return result
        def draft(handle, first):
            value = json.loads(_decision(citation=handle))
            value["answer_text"] = "QR-817 status: pending; only presented evidence is supported."
            if first:
                if draft_kind == "status":
                    value["coverage_status"] = "complete"
                if draft_kind == "note":
                    value["coverage_note"] = ""
                if draft_kind == "citation":
                    value["citation_ids"] = ["C999"]
                if draft_kind == "json":
                    return "QR817_INVALID_JSON"
            return json.dumps(value)

        class Transport(_RecordingTransport):
            def __init__(self):
                super().__init__(calls=(), final_message="unused")
            def run_turn(self, **kwargs):
                turns.append(kwargs)
                index = len(turns)
                invocations = ()
                if index == 1:
                    self.output = kwargs["tool_handler"](descriptor["name"], arguments)
                    invocations = (orchestrator.CodexDynamicToolInvocation(kwargs["thread_id"], "turn-1",
                        "call-1", descriptor["name"], arguments, self.output),)
                handle = self.output["data"]["citations"][0]
                return orchestrator.CodexAppServerTurn(kwargs["thread_id"], f"turn-{index}",
                    draft(handle, index == 1), invocations, kwargs.get("deadline_monotonic"))

        def response(payload):
            turns.append(copy.deepcopy(payload))
            if len(turns) == 1:
                return {"status": "completed", "output": [{"type": "function_call", "call_id": "qr817",
                    "name": descriptor["name"], "arguments": json.dumps(arguments)}]}
            output = next(x["output"] for x in payload["input"] if x.get("type") == "function_call_output")
            handle = json.loads(output)["data"]["citations"][0]
            return {"status": "completed", "output_text": draft(handle, len(turns) == 2)}

        token = orchestrator._PRIVATE_UAT_CITATION_TRACE.set(stages)
        try:
            with tempfile.TemporaryDirectory() as workspace:
                transport = Transport()
                provider = (orchestrator.CodexAppServerConversationModel(transport, workspace_dir=workspace)
                    if kind == "app_server" else CodexResponsesConversationModel(
                        base_url="https://provider.example.test/v1", api_key="synthetic"))
                with mock.patch.object(CodexResponsesConversationModel, "_request_response", side_effect=response):
                    outcome = provider.respond(history=(), user_text=user_text, latest_evidence=None,
                        safety_identifier="qr817-finalization", evidence_tool=evidence_tool,
                        formowl_tool_descriptor=descriptor, authorized_capability_summary=capabilities)
        finally:
            orchestrator._PRIVATE_UAT_CITATION_TRACE.reset(token)
        self.assertEqual(len(tool_requests), 1)
        return outcome, turns, stages

    def test_backend_binding_failure_never_requests_model_repair(self):
        from pathlib import Path
        from formowl_gateway.issue56_uat_runtime import _append_behavior_log
        for kind in ("app_server", "responses"):
            for draft_kind in ("valid", "status", "json"):
                with self.subTest(provider=kind, draft=draft_kind):
                    outcome, turns, stages = self._turn(kind, broken=True, draft_kind=draft_kind)
                    self.assertEqual(len(turns), 1 if kind == "app_server" else 2)
                    self.assertEqual(outcome.response_kind, "clarification")
                    self.assertEqual(outcome.coverage_status, "incomplete")
                    records = outcome.provider_diagnostic["finalization_validation"]
                    self.assertEqual(len(records), 1)
                    self.assertEqual(records[0]["reason_code"], "bounded_downgrade_binding_invalid")
                    self.assertEqual(records[0]["validation_result"], "coverage_rejected")
                    self.assertFalse(records[0]["repair_attempted"])
                    self.assertEqual(_safe_provider_diagnostic(outcome.provider_diagnostic)[
                        "finalization_validation"][0]["reason_code"], "bounded_downgrade_binding_invalid")
                    private = [s for s in stages if s["stage"] == "finalization"]
                    self.assertEqual(private[0]["binding_failure_code"], "downgrade_terms_fingerprint_mismatch")
                    for projected in (outcome.provider_diagnostic, _safe_provider_diagnostic(outcome.provider_diagnostic),
                                      _browser_projection(outcome, outcome.tool_results, latest_evidence=None)):
                        self.assertNotIn("binding_failure_code", json.dumps(projected))
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory) / "trace.jsonl"
                        _append_behavior_log(path, prompt="QR-817", result=None, request_count=1, statuses=("partial",),
                            call_traces=(), failure_sha256=None, provider_diagnostic=outcome.provider_diagnostic,
                            elapsed_ms=1.0, request_id="sha256:" + "f" * 64, citation_stages=stages)
                        saved = json.loads(path.read_text())
                        self.assertFalse(saved.get("content_redacted", False))
                        final = next(s for s in saved["citation_stages"] if s["stage"] == "finalization")
                        self.assertEqual(final["binding_failure_code"], "downgrade_terms_fingerprint_mismatch")

    def test_model_status_disclosure_and_citation_violations_still_get_one_repair(self):
        for kind in ("app_server", "responses"):
            for draft_kind, reason in (("status", "incomplete_coverage_hidden"),
                                       ("note", "incomplete_coverage_undisclosed"),
                                       ("citation", "citation_handle_rejected")):
                with self.subTest(provider=kind, draft=draft_kind):
                    outcome, turns, stages = self._turn(kind, draft_kind=draft_kind)
                    self.assertEqual(len(turns), 2 if kind == "app_server" else 3)
                    self.assertEqual(outcome.response_kind, "answer")
                    self.assertEqual(outcome.coverage_status, "incomplete")
                    self.assertEqual(outcome.citation_ids, ("sha256:" + "d" * 64,))
                    records = outcome.provider_diagnostic["finalization_validation"]
                    self.assertEqual(records[0]["reason_code"], reason)
                    self.assertEqual(records[-1]["validation_result"], "passed")
                    self.assertTrue(records[-1]["repair_attempted"])
                    self.assertNotIn("binding_failure_code", json.dumps(stages))

    def test_valid_downgrade_needs_no_repair_on_either_provider(self):
        for kind in ("app_server", "responses"):
            with self.subTest(provider=kind):
                outcome, turns, _ = self._turn(kind)
                self.assertEqual(len(turns), 1 if kind == "app_server" else 2)
                self.assertEqual(outcome.response_kind, "answer")
                self.assertEqual(outcome.coverage_status, "incomplete")
                self.assertEqual(outcome.citation_ids, ("sha256:" + "d" * 64,))
                self.assertTrue(outcome.coverage_note.startswith(orchestrator._BOUNDED_EXACT_DOWNGRADE_DISCLOSURE))
                record, = outcome.provider_diagnostic["finalization_validation"]
                self.assertEqual(record["validation_result"], "passed")
                self.assertFalse(record["repair_attempted"])

    def test_private_subcode_allowlist_drops_unknown_values(self):
        for value in ("QR817_PRIVATE_SENTINEL", {}, [], None):
            stages = []
            token = orchestrator._PRIVATE_UAT_CITATION_TRACE.set(stages)
            try:
                record = orchestrator._finalization_validation_diagnostic(
                    final_citation_ids=(), available_citation_ids=(), validation_result="coverage_rejected",
                    repair_attempted=False, reason_code="bounded_downgrade_binding_invalid", binding_failure_code=value)
            finally:
                orchestrator._PRIVATE_UAT_CITATION_TRACE.reset(token)
            self.assertNotIn("binding_failure_code", record)
            self.assertNotIn("binding_failure_code", stages[0])


def setUpModule() -> None:
    import _uat_turn_budget

    _uat_turn_budget.start()


def tearDownModule() -> None:
    import _uat_turn_budget

    _uat_turn_budget.stop()


if __name__ == "__main__":
    unittest.main()


class TurnCitationPresentationTests(unittest.TestCase):
    def test_table_handles_are_complete_tokens_and_suffixes_fail_strict_binding(self):
        ids = ["sha256:" + format(i, "064x") for i in range(27)]
        table = {"represented_records": 27, "citations": [
            {"ref": f"c{i+1}", "citation_hash": digest} for i, digest in enumerate(ids)],
            "result_set": {"groups": [{"ref": None, "basis": "export_verified"}]}}
        canonical = {"citations": ids, "evidence": [{
            "source_type": "candidate_fact_table", "citation_hash": ids[0],
            "snippet": "Synthetic candidate table\n" + json.dumps(table)}]}
        before = copy.deepcopy(canonical)
        registry = orchestrator._TurnCitationPresentation(set())
        display = registry.present(canonical)
        shown = json.loads(display["evidence"][0]["snippet"].split("\n", 1)[1])
        handle = display["citations"][17]
        self.assertEqual(shown["citations"][17], {"ref": "c18", "citation_hash": handle})
        self.assertIsNone(shown["result_set"]["groups"][0]["ref"])
        self.assertEqual(canonical, before)
        self.assertIn("handle ends after the decimal ordinal", registry.context())
        decision = json.loads(_decision(citation=handle))
        parsed = orchestrator._parse_decision(json.dumps(decision), citation_presentation=registry)
        orchestrator._validate_evidence_bound_decision(parsed, evidence_results=(canonical,))
        self.assertEqual(parsed["citation_ids"], (ids[17],))
        for suffix in ("x", "a1b2c3d4e5f6g7h8i9j0"):
            with self.subTest(suffix=suffix):
                decision["citation_ids"] = [handle + suffix]
                with self.assertRaises(orchestrator._FinalizationValidationError) as rejected:
                    orchestrator._parse_decision(json.dumps(decision), citation_presentation=registry)
                self.assertEqual(registry.diagnostic()["final_classifications"], ["raw_id_forbidden"])
                repair = orchestrator._final_repair_context(error=rejected.exception,
                    evidence_results=(canonical,), prior_evidence=None, citation_presentation=registry)
                self.assertIn(handle, repair)
                self.assertIn(orchestrator._CITATION_COPY_GUIDANCE, repair)
                self.assertNotIn(handle + suffix, repair)
        # A syntactically valid handle still needs the original governed evidence.
        decision["citation_ids"] = [handle]
        parsed = orchestrator._parse_decision(json.dumps(decision), citation_presentation=registry)
        with self.assertRaisesRegex(RuntimeError, "cited unavailable evidence"):
            orchestrator._validate_evidence_bound_decision(parsed, evidence_results=())

    def test_one_to_one_reuse_and_canonical_snapshot(self):
        registry = orchestrator._TurnCitationPresentation(set())
        original = {"citations": ["clienta-header", "clienta-body"], "evidence": [
            {"citation_hash": "clienta-body", "mail_header_citation_hash": "clienta-header",
             "source_context": {"anchor_citation_hash": "clienta-header"},
             "snippet": "clienta-header remains source prose"}], "query_hash": "unchanged-seal"}
        before = copy.deepcopy(original)
        first = registry.present(original)
        second = registry.present({"citations": ["clienta-body", "maple-third"]})
        self.assertEqual(original, before)
        self.assertRegex(first["citations"][0], r"^C[a-km-np-z2-9]{4}\.[1-9][0-9]*$")
        self.assertEqual(second["citations"][0], first["citations"][1])
        self.assertEqual(len(set(first["citations"] + second["citations"])), 3)
        self.assertEqual(first["evidence"][0]["mail_header_citation_hash"], first["citations"][0])
        self.assertEqual(first["evidence"][0]["source_context"]["anchor_citation_hash"], first["citations"][0])
        self.assertEqual(first["evidence"][0]["snippet"], before["evidence"][0]["snippet"])
        self.assertEqual(first["query_hash"], "unchanged-seal")
        self.assertEqual(registry.decode(second["citations"]), ["clienta-body", "maple-third"])
        self.assertEqual(registry.diagnostic()["new_count"], 1)
        self.assertEqual(registry.diagnostic()["reused_count"], 1)

    def test_exact_citation_values_in_any_display_field_use_the_same_handle(self):
        ids = ["sha256:" + char * 64 for char in "ab"]
        canonical = {"citations": ids, "evidence": [{
            "citation_hash": ids[0], "source_observation_hash": ids[0],
            "custom_metadata": {"arbitrary_key": ids[1], "values": [ids[0], {"nested": ids[1]}]},
            "snippet": ids[0],
        }], "query_hash": "sha256:" + "c" * 64}
        original = copy.deepcopy(canonical)
        registry = orchestrator._TurnCitationPresentation(set())
        display = registry.present(canonical)
        first, second = display["citations"]
        self.assertEqual(display["evidence"][0], {
            "citation_hash": first, "source_observation_hash": first,
            "custom_metadata": {"arbitrary_key": second, "values": [first, {"nested": second}]},
            "snippet": first,
        })
        self.assertEqual(canonical, original)
        self.assertEqual(display["query_hash"], canonical["query_hash"])
        for original_id in ids:
            self.assertNotIn(original_id, json.dumps(display))
        self.assertEqual(registry.decode([first, second]), ids)
        # Whole-value equality only: substrings, case changes and unpresented
        # metadata do not become aliases and source prose is not rewritten.
        nonmatches = {"snippet": "Literal " + ids[0], "case_changed": ids[1].upper(),
                      "unpresented_metadata": "sha256:" + "d" * 64}
        self.assertEqual(registry.references(nonmatches), nonmatches)
        self.assertEqual(registry.diagnostic()["mapping_count"], 2)

    def test_unpresented_forged_duplicate_and_raw_ids_are_rejected(self):
        registry = orchestrator._TurnCitationPresentation(set())
        canonical = orchestrator.compact_evidence_for_model(
            {"citations": ["clienta-first", "hidden-second"]}, item_limit=1)
        handle, = registry.present(canonical)["citations"]
        for values, reason in (([handle.rsplit(".", 1)[0] + ".999"], "unknown_handle"),
                               ([handle, handle], "duplicate_handle"),
                               (["hidden-second"], "raw_id_forbidden"),
                               (["clienta-first"], "raw_id_forbidden")):
            with self.subTest(reason=reason), self.assertRaisesRegex(RuntimeError, "citation"):
                registry.decode(values)
            self.assertIn(reason, registry.diagnostic()["final_classifications"])
        self.assertEqual(registry.diagnostic()["mapping_count"], 1)
        registry._presented.clear()
        with self.assertRaisesRegex(RuntimeError, "citation"):
            registry.decode([handle])
        self.assertEqual(registry.diagnostic()["final_classifications"], ["not_presented"])
        registry._presented.add("clienta-first")
        registry._by_original["clienta-first"] = "inconsistent"
        with self.assertRaisesRegex(RuntimeError, "citation"):
            registry.decode([handle])
        self.assertEqual(registry.diagnostic()["final_classifications"], ["mapping_conflict"])
        with self.assertRaises(RuntimeError):
            orchestrator._parse_decision("malformed", citation_presentation=registry)
        self.assertEqual(registry.diagnostic()["final_classifications"], [])

    def test_retained_scope_collision_reselects_and_old_turn_is_rejected(self):
        retained = set()
        with mock.patch.object(orchestrator.secrets, "choice", side_effect=list("k7q4k7q4m8r5")):
            first = orchestrator._TurnCitationPresentation(retained)
            old, = first.present({"citations": ["clienta"]})["citations"]
            second = orchestrator._TurnCitationPresentation(retained)
        new, = second.present({"citations": ["clienta"]})["citations"]
        self.assertNotEqual(old, new)
        with self.assertRaisesRegex(RuntimeError, "citation"):
            second.decode([old])
        self.assertEqual(second.diagnostic()["final_classifications"], ["wrong_turn_scope"])

    def test_required_prior_original_ids_and_repair_handles(self):
        registry = orchestrator._TurnCitationPresentation(set())
        prior = {"status": "complete", "citations": ["clienta-prior-a", "clienta-prior-b"]}
        handles = registry.present(prior)["citations"]
        decision = json.loads(_decision(citation=handles[0]))
        decision.update(response_kind="render_prior_evidence", coverage_status="complete", coverage_note="")
        parsed = orchestrator._parse_decision(json.dumps(decision), citation_presentation=registry)
        with self.assertRaisesRegex(RuntimeError, "omitted required citations"):
            orchestrator._validate_evidence_bound_decision(parsed, evidence_results=(),
                prior_evidence=prior, required_prior_citations=prior["citations"])
        repair = orchestrator._final_repair_context(error=RuntimeError("citation"),
            evidence_results=(), prior_evidence=prior, required_prior_citations=prior["citations"],
            citation_presentation=registry)
        self.assertTrue(all(handle in repair for handle in handles))
        self.assertTrue(all(original not in repair for original in prior["citations"]))
        decision["citation_ids"] = handles
        parsed = orchestrator._parse_decision(json.dumps(decision), citation_presentation=registry)
        orchestrator._validate_evidence_bound_decision(parsed, evidence_results=(),
            prior_evidence=prior, required_prior_citations=prior["citations"])

    def test_large_presentation_decodes_past_private_diagnostic_cap(self):
        registry = orchestrator._TurnCitationPresentation(set())
        ids = ["sha256:" + format(i, "064x") for i in range(150)]
        handles = registry.present({"citations": ids})["citations"]
        self.assertEqual(registry.decode(handles[-1:]), ids[-1:])
        self.assertEqual(registry.diagnostic()["mapping_count"], 150)
        registry.present({"citations": ["private-clienta-id"]})
        with self.assertRaises(RuntimeError):
            registry.decode(["private-untrusted-draft"])
        diagnostic = registry.diagnostic()
        self.assertNotIn("private-", json.dumps(diagnostic))
        self.assertEqual(diagnostic["final_classifications"], ["raw_id_forbidden"])
