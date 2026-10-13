from __future__ import annotations

import json
import hashlib
from contextlib import redirect_stderr
import io
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

import _paths  # noqa: F401
from formowl_gateway.issue56_uat_runtime import (
    _run_gpt_query_agent, _ConversationState, _advance_conversation_state,
    Issue56TemporaryLanQueryService,
    _record_failed_conversation_turn,
)
from formowl_mail.human_uat_orchestrator import (
    CodexResponsesConversationModel,
    UatConversationMessage,
    compact_evidence_for_model,
    evidence_citation_ids,
    _UatTurnRequestContractBinder,
    UatConversationOutcome,
    UatEvidenceToolRequest,
)
from formowl_contract import ContractValidationError, sha256_json
from formowl_mail.semantic_plan import deterministic_query_class, is_identifier_reference
from formowl_mail import human_uat_orchestrator as orchestrator


class Issue56UatConversationStabilityTests(unittest.TestCase):
    def test_unsafe_expanded_query_is_rejected_before_mcp_with_private_hash_trace(self):
        prompt = "Find the review condition for UNIT-Q7 in authorized records."
        for suffix in (" / cite evidence", " /private/fixture", " secret=synthetic"):
            with self.subTest(suffix=suffix):
                query = prompt + suffix
                self.assertEqual(deterministic_query_class(prompt), "evidence_lookup")
                with self.assertRaises(ContractValidationError):
                    deterministic_query_class(query)
                model = CodexResponsesConversationModel(
                    base_url="https://synthetic.invalid/v1", api_key="synthetic",
                )
                tool = MagicMock(return_value={"status": "mcp_failed", "citations": []})
                response = {"status": "completed", "output": [{
                    "type": "function_call", "name": "query_effective_graph_view", "call_id": "unsafe-query",
                    "arguments": json.dumps({
                        "query_text": query, "required_terms": ["UNIT-Q7"], "table_query": None,
                        "request_contract": {
                            "original_query_hash": sha256_json(prompt), "query_class": "evidence_lookup",
                            "requested_fields": ["review condition"], "source_family_scope": ["mail"],
                            "maximum_claim_strength": "cited_evidence",
                        },
                    }),
                }]}
                final = {"status": "completed", "output_text": json.dumps({
                    "response_kind": "clarification", "answer_text": "Please clarify the request.",
                    "display_format": "narrative", "citation_ids": [],
                    "coverage_status": "incomplete", "coverage_note": "No verified evidence.",
                })}
                stages = []
                token = orchestrator._PRIVATE_UAT_CITATION_TRACE.set(stages)
                try:
                    with patch.object(model, "_request_response", side_effect=[response, final]) as transport:
                        outcome = model.respond(
                            history=(), user_text=prompt, latest_evidence=None,
                            safety_identifier="synthetic", evidence_tool=tool,
                            authorized_capability_summary={"source_families": ["mail"]},
                        )
                finally:
                    orchestrator._PRIVATE_UAT_CITATION_TRACE.reset(token)
                tool.assert_not_called()
                self.assertEqual(transport.call_count, 2)  # Existing bounded invalid-argument handling.
                self.assertEqual(outcome.response_kind, "clarification")
                rejected = [item for item in stages if item["stage"] == "tool_request_validation"]
                self.assertEqual(len(rejected), 1)
                self.assertEqual(rejected[0]["validation_result"], "unsafe_query_text")
                self.assertEqual(rejected[0]["query_hash"], "sha256:" + hashlib.sha256(query.encode()).hexdigest())
                self.assertNotIn(query, json.dumps(stages))

    def test_existing_bounded_repair_can_replace_unsafe_expansion_and_retrieve_once(self):
        prompt = "Find the review condition for UNIT-Q7 in authorized records."
        safe_query = "Retrieve the review condition for UNIT-Q7 from authorized records."
        original_hash = "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()
        contract = {
            "original_query_hash": original_hash, "query_class": "evidence_lookup",
            "requested_fields": ["review condition"], "source_family_scope": ["mail"],
            "maximum_claim_strength": "cited_evidence",
        }
        citation = "sha256:" + "c" * 64
        responses = [{"status": "completed", "output": [{
            "type": "function_call", "name": "query_effective_graph_view", "call_id": str(index),
            "arguments": json.dumps({
                "query_text": query, "required_terms": ["UNIT-Q7"],
                "request_contract": contract, "table_query": None,
            }),
        }]} for index, query in enumerate((safe_query + " / cite evidence", safe_query))]
        responses.append({"status": "completed", "output_text": json.dumps({
            "response_kind": "answer", "answer_text": "The review condition is verified by the cited record.",
            "display_format": "narrative", "citation_ids": [citation],
            "coverage_status": "incomplete", "coverage_note": "Partial synthetic scope.",
        })})
        model = CodexResponsesConversationModel(base_url="https://synthetic.invalid/v1", api_key="synthetic")
        tool = MagicMock(return_value={
            "status": "partial", "citations": [citation],
            "evidence": [{"citation_hash": citation, "snippet": "UNIT-Q7 review condition is verified."}],
        })
        with patch.object(model, "_request_response", side_effect=responses) as transport:
            outcome = model.respond(
                history=(), user_text=prompt, latest_evidence=None,
                safety_identifier="synthetic", evidence_tool=tool,
                authorized_capability_summary={"source_families": ["mail"]},
            )
        tool.assert_called_once()
        request = tool.call_args.args[0]
        self.assertEqual(request.query_text, safe_query)
        self.assertEqual(request.required_terms, ("unit-q7",))
        self.assertEqual(request.request_contract, contract)
        self.assertEqual(transport.call_count, 3)
        self.assertIn("invalid_arguments", json.dumps(transport.call_args_list[1].args[0]["input"]))
        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(outcome.citation_ids, (citation,))

    def _turn(self, state, prompt, *, query, terms, cited=True, families=("mail",)):
        calls, contexts = [], []
        citation = "sha256:" + "b" * 64

        def respond(**kwargs):
            contexts.append(kwargs)
            binder = _UatTurnRequestContractBinder(
                user_text=kwargs["user_text"],
                authorized_capability_summary=kwargs["authorized_capability_summary"],
            )
            contract = binder.bind(None, table_query=None)
            request = UatEvidenceToolRequest(
                query_text=query, required_terms=terms, request_contract=contract,
            )
            data = kwargs["evidence_tool"](request)
            return UatConversationOutcome(
                response_kind="answer" if cited else "clarification",
                answer_text="Synthetic field evidence." if cited else "No supported field.",
                display_format="narrative", model_name="synthetic",
                citation_ids=(citation,) if cited else (),
                coverage_status="incomplete", coverage_note="Partial fixture scope.",
                tool_requests=(request,), tool_results=(data,),
            )

        def dispatch(request):
            calls.append(request)
            return {"status": "partial", "citations": [citation] if cited else [],
                    "results": [{"snippet": "Synthetic field.", "citations": [citation]}] if cited else []}

        model = SimpleNamespace(respond=MagicMock(side_effect=respond))
        result, responses, outcome = _run_gpt_query_agent(
            model, prompt=prompt, history=state.history, latest_evidence=state.latest_evidence,
            reference_binding=state.reference_binding, safety_identifier="synthetic-session",
            formowl_tool_descriptor=None,
            authorized_capability_summary={"source_families": list(families)}, mcp_call=dispatch,
        )
        _advance_conversation_state(state, prompt=prompt, result=result, outcome=outcome, responses=responses)
        return result, calls, contexts, model

    def _seed(self, state, identifiers=("UNIT-Q7",), *, cited=True):
        prompt = "Find the part supplier for " + " and ".join(identifiers)
        self._turn(state, prompt, query=prompt, terms=identifiers, cited=cited)
        return prompt

    def test_single_validated_anchor_resolves_followup_with_original_hash_and_scope(self):
        state = _ConversationState(expires_at=time.monotonic() + 60)
        prior_prompt = self._seed(state)
        self.assertEqual(state.reference_binding["identifier"], "unit-q7")
        source_hash = "sha256:" + hashlib.sha256(prior_prompt.encode()).hexdigest()
        self.assertEqual(state.reference_binding["source_turn_hash"], source_hash)
        prompt = "Find this part's manufacturer."
        result, calls, contexts, _ = self._turn(
            state, prompt, query="Find manufacturer for UNIT-Q7.", terms=("unit-q7",),
            families=("mail", "document_text"),
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].required_terms, ("unit-q7",))
        self.assertIn("UNIT-Q7", calls[0].query_text)
        self.assertEqual(calls[0].request_contract["original_query_hash"],
                         "sha256:" + hashlib.sha256(prompt.encode()).hexdigest())
        self.assertEqual(calls[0].request_contract["source_family_scope"], ["mail"])
        self.assertEqual(contexts[0]["user_text"], prompt)
        self.assertEqual(state.reference_binding["source_turn_hash"], source_hash)

    def test_fresh_multiple_uncited_and_reset_states_clarify_before_provider_or_tool(self):
        for scenario in ("fresh", "two_ids", "uncited", "reset", "history_only", "changed_scope"):
            with self.subTest(scenario=scenario):
                state = _ConversationState(expires_at=time.monotonic() + 60)
                if scenario != "fresh" and scenario != "history_only":
                    self._seed(state, identifiers=("UNIT-Q7", "UNIT-R9") if scenario == "two_ids" else ("UNIT-Q7",),
                               cited=scenario != "uncited")
                if scenario == "history_only":
                    state.history = (UatConversationMessage(role="assistant", content="Target UNIT-Q7."),)
                if scenario == "reset":
                    service = object.__new__(Issue56TemporaryLanQueryService)
                    service._lock = threading.RLock()
                    service._sessions = {"old-session": state}
                    service._conversation_model = SimpleNamespace(discard_conversation=MagicMock())
                    session_id, _ = service.reset_browser_conversation("old-session")
                    self.assertNotIn("old-session", service._sessions)
                    state = service._sessions[session_id]
                    self.assertIsNone(state.reference_binding)
                result, calls, _, model = self._turn(
                    state, "Find this part's manufacturer.", query="Find the part manufacturer.",
                    terms=("part",), families=("document_text",) if scenario == "changed_scope" else ("mail",),
                )
                self.assertEqual(result["status"], "clarification_required")
                self.assertEqual(calls, [])
                model.respond.assert_not_called()

    def test_new_explicit_id_replaces_retained_anchor(self):
        state = _ConversationState(expires_at=time.monotonic() + 60)
        self._seed(state)
        prompt = "Find this part UNIT-R9's supplier."
        _, calls, contexts, _ = self._turn(state, prompt, query=prompt, terms=("UNIT-R9",))
        self.assertEqual(calls[0].required_terms, ("unit-r9",))
        self.assertNotIn("conversation_reference_binding", contexts[0]["authorized_capability_summary"])
        self.assertEqual(state.reference_binding["identifier"], "unit-r9")

    def test_fullwidth_explicit_id_replaces_retained_anchor(self):
        state = _ConversationState(expires_at=time.monotonic() + 60)
        self._seed(state)
        prompt = "Find this part ＵＮＩＴ－Ｒ９'s manufacturer."
        _, calls, contexts, _ = self._turn(
            state, prompt, query="Find the manufacturer for UNIT-R9.", terms=("UNIT-R9",),
        )
        self.assertEqual(calls[0].required_terms, ("unit-r9",))
        self.assertNotIn("unit-q7", calls[0].query_text.casefold())
        self.assertNotIn("conversation_reference_binding", contexts[0]["authorized_capability_summary"])
        self.assertEqual(state.reference_binding["identifier"], "unit-r9")
        self.assertEqual(state.reference_binding["source_turn_hash"],
                         "sha256:" + hashlib.sha256(prompt.encode()).hexdigest())

    def test_failed_or_uncited_new_turn_clears_anchor(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                state = _ConversationState(expires_at=time.monotonic() + 60)
                self._seed(state)
                if failed:
                    _record_failed_conversation_turn(
                        state, prompt="Find UNIT-R9's supplier.", previous_history=state.history,
                        previous_evidence=state.latest_evidence, previous_turns=state.turns,
                    )
                else:
                    self._seed(state, identifiers=("UNIT-R9",), cited=False)
                self.assertIsNone(state.reference_binding)

    def test_reference_diagnostic_retains_hashes_even_when_tool_arguments_rejected(self):
        state = _ConversationState(expires_at=time.monotonic() + 60)
        self._seed(state)
        binding = dict(state.reference_binding)
        prompt = "Find this part's dispatch window."
        with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(ContractValidationError):
            self._turn(state, prompt, query="Find the part dispatch window.", terms=("part",))
        trace = json.loads(stderr.getvalue())
        self.assertEqual(trace["binding_fingerprint"], sha256_json(binding))
        self.assertEqual(trace["source_turn_hash"], binding["source_turn_hash"])
        self.assertEqual(trace["original_query_hash"], "sha256:" + hashlib.sha256(prompt.encode()).hexdigest())
        for private in ("unit-q7", "UNIT-Q7", prompt, "history"):
            self.assertNotIn(private, stderr.getvalue())

    def test_responses_tool_parser_receives_bound_reference_without_rewriting_prompt(self):
        state = _ConversationState(expires_at=time.monotonic() + 60)
        self._seed(state)
        prompt = "Find this part's manufacturer."
        citation = "sha256:" + "c" * 64
        payloads, calls = [], []
        model = CodexResponsesConversationModel(base_url="https://synthetic.invalid/v1", api_key="synthetic")

        def provider(payload):
            payloads.append(payload)
            if len(payloads) == 1:
                self.assertEqual(payload["input"][-1]["content"], prompt)
                boundaries = [item["content"] for item in payload["input"] if item.get("role") == "developer"]
                self.assertTrue(any(state.reference_binding["source_turn_hash"] in item for item in boundaries))
                self.assertTrue(any("server-validated exception" in item for item in boundaries))
                self.assertIn("server-validated exception", json.dumps(payload["tools"]))
                self.assertIn("both query_text and required_terms", json.dumps(payload["tools"]))
                return {"status": "completed", "output": [{
                    "type": "function_call", "name": "query_effective_graph_view", "call_id": "synthetic-followup",
                    "arguments": json.dumps({
                        "query_text": "Retrieve the manufacturer for UNIT-Q7 from authorized source records.",
                        "required_terms": ["UNIT-Q7"], "table_query": None,
                        "request_contract": {
                            "original_query_hash": "sha256:" + hashlib.sha256(prompt.encode()).hexdigest(),
                            "query_class": "evidence_lookup", "requested_fields": ["manufacturer"],
                            "source_family_scope": ["mail"], "maximum_claim_strength": "cited_evidence",
                        },
                    }),
                }]}
            return {"status": "completed", "output_text": json.dumps({
                "response_kind": "answer", "answer_text": "Synthetic maker.",
                "display_format": "narrative", "citation_ids": [citation],
                "coverage_status": "incomplete", "coverage_note": "Partial fixture scope.",
            })}

        def dispatch(request):
            calls.append(request)
            return {"status": "partial", "citations": [citation],
                    "evidence": [{"citation_hash": citation, "snippet": "UNIT-Q7: Synthetic maker."}]}

        with patch.object(model, "_request_response", side_effect=provider):
            result, _, _ = _run_gpt_query_agent(
                model, prompt=prompt, history=state.history, latest_evidence=state.latest_evidence,
                reference_binding=state.reference_binding, safety_identifier="synthetic-session",
                formowl_tool_descriptor=None, authorized_capability_summary={"source_families": ["mail"]},
                mcp_call=dispatch,
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].required_terms, ("unit-q7",))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(payloads), 2)

    def test_bound_followup_rejects_generic_missing_and_ungrounded_tool_arguments(self):
        for query, terms in (
            ("Find the part manufacturer.", ("unit-q7",)),
            ("Find UNIT-Q7 manufacturer.", ("part",)),
            ("Find UNIT-Q7 manufacturer.", None),
            ("Find UNIT-Q7 manufacturer.", ("unit-q7", "unit-r9")),
            ("Find UNIT-Q7 and UNIT-R9 manufacturer.", ("unit-q7",)),
        ):
            with self.subTest(query=query, terms=terms):
                state = _ConversationState(expires_at=time.monotonic() + 60)
                self._seed(state)
                with self.assertRaises(ContractValidationError):
                    self._turn(state, "Find this part's manufacturer.", query=query, terms=terms)

    def test_reference_only_request_clarifies_before_broad_tool_dispatch(self):
        from types import SimpleNamespace
        calls = []

        def respond(**kwargs):
            request = UatEvidenceToolRequest(
                query_text="Find the manufacturer of the part mentioned earlier.",
                required_terms=("part",),
            )
            kwargs["evidence_tool"](request)
            return UatConversationOutcome(
                response_kind="clarification", answer_text="Target unknown.",
                display_format="narrative", model_name="synthetic",
            )

        model = SimpleNamespace(respond=MagicMock(side_effect=respond))
        result, responses, _ = _run_gpt_query_agent(
            model, prompt="Find this part's manufacturer.", history=(),
            latest_evidence=None, safety_identifier="synthetic-session",
            formowl_tool_descriptor=None,
            authorized_capability_summary={"source_families": ["mail"]},
            mcp_call=lambda request: calls.append(request) or {"status": "pending_review"},
        )
        self.assertEqual(calls, [])
        model.respond.assert_not_called()
        self.assertEqual(result["status"], "clarification_required")
        self.assertEqual(responses, ())

    def test_unbound_coreference_does_not_admit_identifiers_from_history(self):
        # Neither fresh/reset state nor a prior answer is a validated identifier
        # binding. Multiple prior identities cannot be silently disambiguated.
        for prior_ids in ((), ("UNIT-Q7",), ("UNIT-Q7", "UNIT-R9")):
            with self.subTest(prior_ids=prior_ids):
                binder = _UatTurnRequestContractBinder(
                    user_text="Find its part manufacturer.",
                    authorized_capability_summary={"source_families": ["mail"]},
                )
                for identifier in prior_ids or ("UNIT-Q7",):
                    with self.assertRaisesRegex(ContractValidationError, "not grounded"):
                        binder.bind_required_terms([identifier])

    def test_new_explicit_identifier_wins_over_stale_prior_identifier(self):
        binder = _UatTurnRequestContractBinder(
            user_text="Find the manufacturer for UNIT-R9 in the records.",
            authorized_capability_summary={"source_families": ["mail"]},
        )
        with self.assertRaisesRegex(ContractValidationError, "not grounded"):
            binder.bind_required_terms(["UNIT-Q7"])
        self.assertEqual(binder.bind_required_terms(["UNIT-R9"]), ("unit-r9",))

    def test_explicit_identifier_rephrase_keeps_lookup_claim(self):
        for prompt in (
            "Look up country for UNIT-Q7 in the records.",
            "Find the counterpart for UNIT-Q7 in the records.",
            "查 UNIT-Q7 的產地；列出所有來源引用。",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(deterministic_query_class(prompt), "evidence_lookup")

    def test_actual_count_still_requires_exact_execution(self):
        for prompt in ("Count records for UNIT-Q7", "List all parts for UNIT-Q7",
                       "盤點 UNIT-Q7 的全部零件"):
            with self.subTest(prompt=prompt):
                self.assertEqual(deterministic_query_class(prompt), "exact_set_or_inventory")

    def test_chat_after_evidence_does_not_force_a_rejected_tool_call(self):
        citation = "sha256:" + "a" * 64
        prior = {
            "status": "partial", "citations": [citation],
            "results": [{"citations": [citation], "answer": "x" * 18000}],
        }
        self.assertTrue(evidence_citation_ids(prior))
        self.assertFalse(evidence_citation_ids(compact_evidence_for_model(prior, item_limit=8)))
        model = CodexResponsesConversationModel(base_url="https://synthetic.invalid/v1", api_key="synthetic")
        observed = []

        def provider(payload):
            observed.append(payload)
            decision = {
                "response_kind": "answer", "answer_text": "Glad to help.",
                "display_format": "narrative", "citation_ids": [],
                "coverage_status": "not_applicable", "coverage_note": "",
            }
            return {"status": "completed", "output": [], "output_text": json.dumps(decision)}

        with patch.object(model, "_request_response", side_effect=provider):
            result, responses, _ = _run_gpt_query_agent(
                model, prompt="Have a pleasant evening.",
                history=(UatConversationMessage(role="user", content="Look up UNIT-Q7"),),
                latest_evidence=prior, safety_identifier="synthetic-session",
                formowl_tool_descriptor=None, authorized_capability_summary=None,
                mcp_call=lambda request: self.fail("ordinary chat must not dispatch MCP"),
            )
        self.assertEqual(observed[0]["tool_choice"], "none")
        self.assertEqual(observed[0]["tools"], [])
        self.assertEqual(len(observed), 1)
        self.assertEqual(responses, ())
        self.assertEqual(result["status"], "complete")

    def test_reference_mentions_in_ordinary_statements_remain_chat(self):
        from formowl_mail.semantic_plan import requires_workspace_evidence
        for prompt in ("This product looks nice.", "Its color is lovely.", "它的名字很好聽。"):
            with self.subTest(prompt=prompt):
                model = SimpleNamespace(respond=MagicMock(return_value=UatConversationOutcome(
                    response_kind="answer", answer_text="Glad you like it.",
                    display_format="narrative", model_name="synthetic",
                )))
                result, calls, _ = _run_gpt_query_agent(
                    model, prompt=prompt, history=(), latest_evidence=None,
                    safety_identifier="synthetic-session", formowl_tool_descriptor=None,
                    authorized_capability_summary={"source_families": ["mail"]},
                    mcp_call=lambda request: self.fail("chat must not dispatch"),
                )
                self.assertEqual(result["status"], "complete")
                model.respond.assert_called_once()
                self.assertEqual(calls, ())
                self.assertFalse(requires_workspace_evidence(prompt))

    def test_thank_you_after_uncited_miss_remains_chat(self):
        prior = {"status": "pending_review", "citations": []}
        model = CodexResponsesConversationModel(base_url="https://synthetic.invalid/v1", api_key="synthetic")
        provider_result = {"status": "completed", "output_text": json.dumps({
            "response_kind": "answer", "answer_text": "You're welcome.",
            "display_format": "narrative", "citation_ids": [],
            "coverage_status": "not_applicable", "coverage_note": "",
        })}
        with patch.object(model, "_request_response", return_value=provider_result) as provider:
            result, responses, _ = _run_gpt_query_agent(
                model, prompt="Thank you for checking.", history=(), latest_evidence=prior,
                safety_identifier="synthetic-session", formowl_tool_descriptor=None,
                authorized_capability_summary={"source_families": ["mail"]},
                mcp_call=lambda request: self.fail("thank-you must not dispatch MCP"),
            )
        provider.assert_called_once()
        self.assertEqual(provider.call_args.args[0]["tool_choice"], "none")
        self.assertEqual(responses, ())
        self.assertEqual(result["status"], "complete")
        # An explicit unresolved data follow-up is still blocked before model/tool.
        state = _ConversationState(expires_at=time.monotonic() + 60, latest_evidence=prior)
        result, calls, _, model = self._turn(
            state, "Find this part's supplier.", query="Find the part supplier.", terms=("part",),
        )
        self.assertEqual(result["status"], "clarification_required")
        self.assertEqual(calls, [])
        model.respond.assert_not_called()

    def test_reference_data_requests_remain_recognized(self):
        for prompt in ("Find this part's dispatch window.", "What is its category?",
                       "請查詢它的規格。", "這個零件的供應商是誰？"):
            with self.subTest(prompt=prompt):
                self.assertTrue(is_identifier_reference(prompt))


if __name__ == "__main__":
    unittest.main()
