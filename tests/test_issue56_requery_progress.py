"""Generic governed requery progress; synthetic sources and mocked provider only."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
import unittest
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import sha256_json
from formowl_gateway.issue56_uat_runtime import _private_graph_recheck_trace
from formowl_gateway.remote import build_remote_tool_descriptors
from formowl_mail import human_uat_orchestrator as orchestrator
from formowl_retrieval.gateway import SourceEvidenceScan, source_evidence_double_check


def _contract(families):
    return {
        "original_query_hash": sha256_json("synthetic request"),
        "query_class": "evidence_lookup",
        "source_family_scope": list(families),
        "requested_fields": ["category", "owner"],
        "maximum_claim_strength": "cited_evidence",
    }


def _result(citations, *, contract=None, supported=(), prose="Synthetic source context."):
    result = {
        "status": "partial",
        "citations": list(citations),
        "evidence": [
            {"citation_hash": citation, "snippet": prose, "source_family": "document_text"}
            for citation in citations
        ],
    }
    if contract is not None:
        coverage = {
            "request_contract_fingerprint": sha256_json(contract),
            "requested_fields": contract["requested_fields"],
            "supported_fields": list(supported),
            "missing_fields": [field for field in contract["requested_fields"]
                               if field not in supported],
            "evidence_citation_hashes": list(citations),
            "status": "incomplete" if len(supported) < 2 else "verified",
            "absence_claim": False,
        }
        coverage["coverage_fingerprint"] = sha256_json(coverage)
        result["coverage"] = coverage
    return result


class RequeryProgressTests(unittest.TestCase):
    def test_actual_source_start_shortlist_miss_stops_before_second_provider(self):
        from test_issue56_source_query_stability import SourceQueryStabilityTests

        _, handler, arguments = SourceQueryStabilityTests.prepare(self, ("mail", "document_text"))
        self._assert_source_start_shortlist_stops(handler, arguments, "indexed_shortlist_miss")

    def test_actual_native_table_shortlist_stops_before_second_provider(self):
        from test_issue56_source_start_exact import SourceStartExactTests
        from formowl_gateway import issue56_sealed_source_loader as loader

        for inline in (False, True):
            with self.subTest(inline=inline):
                case = SourceStartExactTests()
                case.setUp()
                self.addCleanup(case.doCleanups)
                _, revision, _, arguments = case.prepare(inline=inline)
                self.addCleanup(revision.source_records.runtime_store.close)
                handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
                arguments["table_query"] = None
                arguments["request_contract"]["source_family_scope"] = (
                    ["mail"] if inline else ["mail", "attachment_table"]
                )
                # Both labels are terminal bounded-shortlist misses; the sealed
                # lexical index reports indexed_shortlist_miss for attachment tables.
                self._assert_source_start_shortlist_stops(
                    handler, arguments, ("source_table_shortlist", "indexed_shortlist_miss"),
                )

    def _assert_source_start_shortlist_stops(self, handler, arguments, stop_reason):
        stop_reasons = (stop_reason,) if isinstance(stop_reason, str) else tuple(stop_reason)
        prompt = "Find the review condition for MISSING-Q47 in authorized records."
        contract = {**arguments["request_contract"], "original_query_hash": sha256_json(prompt),
                    "requested_fields": ["review condition"]}
        provider = orchestrator.CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="synthetic-provider-key",
        )
        requests, results = [], []

        def execute(request):
            requests.append(request)
            result = handler({
                **arguments, "query_text": request.query_text,
                "required_terms": list(request.required_terms), "request_contract": request.request_contract,
            })
            recovery = result["query_agent"]["context_bundle"]["source_recovery"]
            self.assertIsNone(request.table_query)
            self.assertEqual(request.request_contract["query_class"], "evidence_lookup")
            self.assertEqual(recovery["scan"]["scanned_observation_count"], 0)
            self.assertIs(recovery["scan"]["complete"], False)
            self.assertIn(recovery["scan"]["stop_reason"], stop_reasons)
            results.append(result)
            return result

        tool_response = {"status": "completed", "output": [{
            "type": "function_call", "name": "query_effective_graph_view", "call_id": "empty-source",
            "arguments": json.dumps({"query_text": prompt, "required_terms": ["MISSING-Q47"],
                                     "request_contract": contract, "table_query": None}),
        }]}
        with mock.patch.object(provider, "_request_response", side_effect=[
            tool_response, AssertionError(f"unnecessary provider continuation after bound {stop_reasons}"),
        ]) as transport:
            outcome = provider.respond(
                history=(), user_text=prompt, latest_evidence=None,
                safety_identifier="synthetic-empty-source", evidence_tool=execute,
                authorized_capability_summary={"source_families": contract["source_family_scope"]},
            )
        transport.assert_called_once()
        self.assertEqual(len(requests), 1)
        result, request = results[0], requests[0]
        recovery = result["query_agent"]["context_bundle"]["source_recovery"]
        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(orchestrator.evidence_citation_ids(result), ())
        self.assertTrue(recovery["attempted"])
        self.assertEqual(set(recovery["warnings"]), {"used", "incomplete"})
        self.assertEqual(recovery["scan"]["scanned_observation_count"], 0)
        self.assertIs(recovery["scan"]["complete"], False)
        self.assertIn(recovery["scan"]["stop_reason"], stop_reasons)
        self.assertEqual(outcome.response_kind, "clarification")
        self.assertEqual(outcome.coverage_status, "incomplete")
        self.assertTrue(outcome.coverage_note)
        self.assertEqual(outcome.citation_ids, ())
        self.assertTrue(orchestrator._source_fallback_exhausted(request, result))
        trace = _private_graph_recheck_trace({
            "response_stage": "payload_validated", "browser_request_sha256": sha256_json("turn"),
            "query_hash": sha256_json(prompt), "mcp_call_index": 1, "citation_count": 0,
            "request_discriminator": {
                "tool_name": "query_effective_graph_view", "query_text_char_count": len(prompt),
                "selector_kind": "none", "selector_present": False, "selector_count": 0,
            },
        }, result)
        self.assertIn(trace["scan_stop_reason"], stop_reasons)
        for section, key, value in (
            ("agent", "original_query_hash", sha256_json("wrong")),
            ("recovery", "query_hash", sha256_json("wrong")),
            ("recovery", "source_family_scope", ["document_text"]),
            ("recovery", "attempted", False),
            ("scan", "stop_reason", "indexed_shortlist"),
            ("result", "status", "error"),
            ("result", "status", "permission_denied"),
            ("result", "citations", ["citation-a"]),
        ):
            with self.subTest(section=section, key=key, value=value):
                changed = copy.deepcopy(result)
                agent = changed["query_agent"]
                recovered = agent["context_bundle"]["source_recovery"]
                {"result": changed, "agent": agent, "recovery": recovered,
                 "scan": recovered["scan"]}[section][key] = value
                self.assertFalse(orchestrator._source_fallback_exhausted(request, changed))
        exact = replace(request, request_contract={
            **request.request_contract, "query_class": "exact_set_or_inventory",
            "maximum_claim_strength": "complete_authorized_scope",
        })
        self.assertFalse(orchestrator._source_fallback_exhausted(exact, result))
        table_request = replace(request, table_query={
            "filters": [{"field": "Code", "value": "MISSING-Q47"}],
            "projection_fields": ["State"],
        })
        self.assertFalse(orchestrator._source_fallback_exhausted(table_request, result))

    def _run(self, families, results):
        payloads, controls = [], []
        prompt = "Find category and owner for cerulean records and cite authorized evidence."
        descriptor = next(
            tool.model_dump(by_alias=True, exclude_none=True)
            for tool in build_remote_tool_descriptors(
                required_scope="formowl.use", enabled_tool_names={"whoami", "query_effective_graph_view"},
            ) if tool.name == "query_effective_graph_view"
        )
        provider = orchestrator.CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="synthetic-provider-key",
        )
        executed = []

        def execute(request):
            result = copy.deepcopy(results[len(executed)])
            if callable(result):
                result = result(request)
            for item in result.get("evidence", []):
                item["source_family"] = families[
                    1 if len(families) > 1 and item["citation_hash"] == "citation-b" else 0
                ]
            executed.append(request)
            return result

        def response(payload):
            payloads.append(copy.deepcopy(payload))
            outputs = [item for item in payload["input"]
                       if item.get("type") == "function_call_output"]
            if outputs:
                control = json.loads(outputs[-1]["output"])["execution_control"]
                controls.append(control)
                if control["stop_reason"] or len(executed) == len(results):
                    citations = orchestrator.evidence_citation_ids(results[0])
                    return {
                        "status": "completed",
                        "output_text": json.dumps({
                            "response_kind": "answer" if citations else "clarification",
                            "answer_text": "Source context is retained; requested support is incomplete.",
                            "display_format": "narrative", "citation_ids": list(citations),
                            "coverage_status": "incomplete",
                            "coverage_note": "Bounded synthetic source coverage remains incomplete.",
                        }),
                    }
            return {
                "status": "completed",
                "output": [{
                    "type": "function_call", "name": "query_effective_graph_view",
                    "call_id": f"synthetic-call-{len(payloads)}",
                    "arguments": json.dumps({
                        "query_text": f"Retrieve cerulean source context using candidate {len(payloads)}.",
                        "required_terms": ["cerulean"], "table_query": None,
                        "request_contract": {
                            **_contract(families), "original_query_hash": sha256_json(prompt),
                        },
                    }),
                }],
            }

        with mock.patch.object(provider, "_request_response", side_effect=response):
            outcome = provider.respond(
                history=(), user_text=prompt, latest_evidence=None,
                safety_identifier="synthetic-requery-session", evidence_tool=execute,
                formowl_tool_descriptor=descriptor,
                authorized_capability_summary={"source_families": list(families)},
            )
        return outcome, executed, controls, payloads

    def test_duplicate_same_and_mixed_citations_ignore_prose_and_order(self):
        for families in (("mail",), ("document_text",), ("mail", "document_text")):
            for first, second in (
                (("citation-a",), ("citation-a",)),
                (("citation-a", "citation-b"), ("citation-b", "citation-a")),
                (("citation-a", "citation-b"), ("citation-b",)),
            ):
                with self.subTest(families=families, first=first, second=second):
                    outcome, executed, controls, payloads = self._run(families, [
                        _result(first), _result(second, prose="Reworded source summary."),
                    ])
                    self.assertEqual(len(executed), 2)
                    self.assertEqual([item["material_progress"] for item in controls], [True, False])
                    self.assertEqual(controls[-1]["stop_reason"], "no_progress")
                    self.assertEqual(payloads[-1]["tools"], [])
                    self.assertEqual(payloads[-1]["tool_choice"], "none")
                    self.assertEqual(outcome.citation_ids, tuple(sorted(first)))
                    self.assertEqual(len(outcome.tool_results), 2)

    def test_new_evidence_same_or_mixed_family_is_seen_before_stop(self):
        for families in (("mail",), ("document_text",), ("mail", "document_text")):
            for fresh in (("citation-b",), ("citation-a", "citation-b")):
                with self.subTest(families=families, fresh=fresh):
                    _, executed, controls, _ = self._run(families, [
                        _result(("citation-a",)), _result(fresh), _result(("citation-a",)),
                    ])
                    self.assertEqual(len(executed), 3)
                    self.assertEqual([item["material_progress"] for item in controls],
                                     [True, True, False])
                    self.assertEqual(controls[-1]["stop_reason"], "no_progress")

    def test_validated_field_support_improves_with_same_citation(self):
        def supported(request):
            return _result(("citation-a",), contract=request.request_contract,
                           supported=("category",))

        _, executed, controls, _ = self._run(("document_text",), [
            _result(("citation-a",)), supported, supported,
        ])
        self.assertEqual(len(executed), 3)
        self.assertEqual([item["material_progress"] for item in controls], [True, True, False])
        self.assertEqual(controls[-1]["stop_reason"], "no_progress")

    def test_uncited_duplicate_keeps_no_progress_stop(self):
        result = {"status": "replan_required", "citations": [],
                  "query_agent": {"external_replan": {"status": "required"}}}
        _, executed, controls, payloads = self._run(("document_text",), [result, {
            **result, "answer": {"text": "Different prose without new outputs."},
        }])
        self.assertEqual(len(executed), 2)
        self.assertFalse(controls[-1]["material_progress"])
        self.assertEqual(controls[-1]["stop_reason"], "no_progress")
        self.assertEqual(payloads[-1]["tools"], [])

    def test_incomplete_validated_exact_support_is_progress_then_duplicate_stops(self):
        def supported(request):
            result = _result(("citation-a",))
            contract = request.request_contract
            result["query_agent"] = {
                "request_contract": {
                    "request_contract_fingerprint": sha256_json(contract),
                    "requested_field_count": 2,
                    "requested_field_hashes": [sha256_json(field) for field in contract["requested_fields"]],
                },
                "context_bundle": {"missing_field_hashes": [sha256_json("owner")]},
                "subqueries": [{"status": "incomplete",
                                "validation_status": "validated_existing_scope_schema_permission"}],
            }
            return result

        _, executed, controls, _ = self._run(("document_text",), [
            _result(("citation-a",)), supported, supported,
        ])
        self.assertEqual(len(executed), 3)
        self.assertEqual([item["material_progress"] for item in controls], [True, True, False])
        self.assertEqual(controls[-1]["stop_reason"], "no_progress")
        request = orchestrator.UatEvidenceToolRequest(
            query_text="Retrieve records.", request_contract=_contract(("document_text",)),
        )
        for failure in ("error", "failed", "permission_denied"):
            result = supported(request)
            result["query_agent"]["subqueries"][0]["status"] = failure
            self.assertEqual(orchestrator._validated_field_support(request, result), set())

    def test_new_rejection_feedback_allows_bounded_repair_without_claiming_evidence(self):
        results = [{
            "status": "replan_required", "citations": [], "query_agent": {
                "external_replan": {"status": "required", "reason_code": reason},
            },
        } for reason in ("synthetic_first_rejection", "synthetic_second_rejection")]
        results.append(_result(("citation-a",)))
        _, executed, controls, _ = self._run(("document_text",), results)
        self.assertEqual(len(executed), 3)
        self.assertEqual([item["material_progress"] for item in controls], [False, False, True])

    def test_mail_coverage_survives_compaction_and_cannot_create_support_from_citations(self):
        contract = _contract(("mail",))
        request = orchestrator.UatEvidenceToolRequest(query_text="Retrieve records.",
                                                     request_contract=contract)
        result = _result(("citation-a",), contract=contract, supported=("category",))
        result["requested_field_coverage"] = result.pop("coverage")
        presented = orchestrator.compact_evidence_for_model(result)
        self.assertEqual(presented["requested_field_coverage"], result["requested_field_coverage"])
        self.assertEqual(orchestrator._validated_field_support(request, presented),
                         {sha256_json("category")})
        result["requested_field_coverage"]["supported_fields"] = []
        result["requested_field_coverage"]["missing_fields"] = ["category", "owner"]
        coverage = result["requested_field_coverage"]
        coverage["coverage_fingerprint"] = sha256_json({
            key: value for key, value in coverage.items() if key != "coverage_fingerprint"
        })
        self.assertEqual(orchestrator._validated_field_support(request, result), set())

    def test_error_after_cited_result_stays_operational_and_retains_evidence(self):
        outcome, _, controls, _ = self._run(("document_text",), [
            _result(("citation-a",)), {"status": "error", "citations": []},
        ])
        self.assertEqual(controls[-1]["stop_reason"], "mcp_unavailable")
        self.assertEqual(outcome.citation_ids, ("citation-a",))

    def test_cited_source_prose_is_not_an_operational_error_marker(self):
        _, executed, controls, _ = self._run(("document_text",), [
            _result(("citation-a",), prose="The source discusses provider_unavailable and mcp_failed."),
            _result(("citation-b",)),
        ])
        self.assertEqual(len(executed), 2)
        self.assertTrue(all(item["material_progress"] for item in controls))
        self.assertTrue(all(item["stop_reason"] is None for item in controls))

    def test_contract_and_literal_table_predicates_have_distinct_fingerprints(self):
        request = orchestrator.UatEvidenceToolRequest(
            query_text="Retrieve native records.", request_contract=_contract(("mail",)),
            table_query={"filters": [{"field": "label", "value": "a b"}],
                         "projection_fields": ["category"]},
        )
        for changes in (
            {"request_contract": _contract(("document_text",))},
            {"table_query": {"filters": [{"field": "label", "value": "ab"}],
                             "projection_fields": ["category"]}},
            {"table_query": {"filters": [{"field": "label", "value": "A B"}],
                             "projection_fields": ["category"]}},
        ):
            other = orchestrator.UatEvidenceToolRequest(**{**request.__dict__, **changes})
            self.assertNotEqual(orchestrator._tool_request_fingerprint(request),
                                orchestrator._tool_request_fingerprint(other))
        for key in ("exact_field", "cursor"):
            left = orchestrator.UatEvidenceToolRequest(**{**request.__dict__, key: "a b"})
            right = orchestrator.UatEvidenceToolRequest(**{**request.__dict__, key: "ab"})
            self.assertNotEqual(orchestrator._tool_request_fingerprint(left),
                                orchestrator._tool_request_fingerprint(right))

    def test_coverage_binding_and_source_blank_are_distinct_from_missing_or_error(self):
        contract = _contract(("document_text",))
        request = orchestrator.UatEvidenceToolRequest(query_text="Retrieve records.",
                                                     request_contract=contract)
        blank = _result(("citation-a",), contract=contract, supported=("category",))
        blank["evidence"][0]["structured_values"] = [["category", "", "citation-a", "lineage"]]
        self.assertEqual(orchestrator._validated_field_support(request, blank),
                         {sha256_json("category")})
        self.assertEqual(blank["coverage"]["missing_fields"], ["owner"])
        for mutation in ("contract", "missing", "binding", "error", "prose"):
            changed = copy.deepcopy(blank)
            if mutation == "contract":
                changed["coverage"]["request_contract_fingerprint"] = sha256_json("other")
            elif mutation == "missing":
                changed["coverage"]["missing_fields"] = []
            elif mutation == "binding":
                changed["coverage"]["evidence_citation_hashes"] = ["unbound-citation"]
            elif mutation == "error":
                changed["status"] = "error"
            else:
                changed.pop("coverage")
                changed["answer"] = {"text": "category is covered"}
            with self.subTest(mutation=mutation):
                self.assertEqual(orchestrator._validated_field_support(request, changed), set())

    def test_graph_field_summary_requires_matching_contract_and_validated_execution(self):
        contract = _contract(("mail", "document_text"))
        request = orchestrator.UatEvidenceToolRequest(query_text="Retrieve records.",
                                                     request_contract=contract)
        result = _result(("citation-a",))
        result["query_agent"] = {
            "request_contract": {
                "request_contract_fingerprint": sha256_json(contract),
                "requested_field_count": 2,
                "requested_field_hashes": [sha256_json(field) for field in contract["requested_fields"]],
            },
            "context_bundle": {"missing_field_hashes": [sha256_json("owner")]},
            "subqueries": [{"status": "ok",
                            "validation_status": "validated_existing_scope_schema_permission"}],
        }
        self.assertEqual(orchestrator._validated_field_support(request, result),
                         {sha256_json("category")})
        result["query_agent"]["subqueries"][0]["validation_status"] = "rejected_existing_validator"
        self.assertEqual(orchestrator._validated_field_support(request, result), set())

    def test_all_missing_only_recheck_policy_with_unrelated_citation(self):
        for family in ("mail", "document_text"):
            for supported in ((), ("category",), ("category", "owner")):
                with self.subTest(family=family, supported=supported):
                    read = mock.Mock(return_value=SourceEvidenceScan((), 0, False, "deadline"))
                    result = source_evidence_double_check(
                        query_class="evidence_lookup", result_query_class="evidence_lookup",
                        initial_status="ok", initial_warnings=(), verified_evidence_count=1,
                        evidence_limit=8, sealed_coverage_complete=False, read_source=read,
                        project_observation=mock.Mock(), requested_fields=("category", "owner"),
                        supported_requested_fields=supported,
                    )
                    self.assertEqual(read.call_count, 0 if supported else 1)
                    if supported:
                        self.assertIsNone(result.scan)
                    else:
                        self.assertFalse(result.scan.complete)
                        self.assertIn("incomplete", result.warnings)

    def test_private_trace_retains_attachment_family_without_raw_fields(self):
        trace = {
            "response_stage": "payload_validated", "browser_request_sha256": sha256_json("turn"),
            "query_hash": sha256_json("query"), "mcp_call_index": 1, "citation_count": 1,
            "request_discriminator": {
                "tool_name": "query_effective_graph_view", "query_text_char_count": 12,
                "selector_kind": "none", "selector_present": False, "selector_count": 0,
            },
        }
        response = {"status": "partial", "query_agent": {"context_bundle": {"source_recovery": {
            "attempted": True, "source_families": ["mail", "attachment_table", "document_text", "secret"],
            "raw_payload": "synthetic-private-content",
        }}}}
        safe = _private_graph_recheck_trace(trace, response)
        self.assertEqual(safe["source_families"], ["attachment_table", "document_text", "mail"])
        self.assertNotIn("synthetic-private-content", json.dumps(safe))
        self.assertNotIn("secret", json.dumps(safe))

    def test_ordinary_chat_still_offers_no_tools(self):
        provider = orchestrator.CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="synthetic-provider-key",
        )
        with mock.patch.object(provider, "_request_response", return_value={
            "status": "completed", "output_text": json.dumps({
                "response_kind": "answer", "answer_text": "Hello.", "display_format": "narrative",
                "citation_ids": [], "coverage_status": "not_applicable", "coverage_note": "",
            }),
        }) as transport:
            evidence = mock.Mock()
            outcome = provider.respond(history=(), user_text="Hello", latest_evidence=None,
                                       safety_identifier="synthetic-chat", evidence_tool=evidence)
        evidence.assert_not_called()
        self.assertEqual(transport.call_args.args[0]["tools"], [])
        self.assertEqual(outcome.answer_text, "Hello.")


if __name__ == "__main__":
    unittest.main()
