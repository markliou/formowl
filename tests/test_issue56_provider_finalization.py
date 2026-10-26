from __future__ import annotations

import hashlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
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
        self.assertIn(citation, function_outputs[0]["output"])
        self.assertEqual(headers[0]["Authorization"], "Bearer synthetic-local-provider-key")
        self.assertEqual(headers[1]["Authorization"], "Bearer synthetic-local-provider-key")
        self.assertIsNot(requests[0].get("stream"), True)
        self.assertIs(requests[1]["stream"], True)
        self.assertEqual(headers[1]["Accept"], "text/event-stream")



def setUpModule() -> None:
    import _uat_turn_budget

    _uat_turn_budget.start()


def tearDownModule() -> None:
    import _uat_turn_budget

    _uat_turn_budget.stop()


if __name__ == "__main__":
    unittest.main()
