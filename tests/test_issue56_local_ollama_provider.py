"""Synthetic local-provider checks through the existing governed conversation loop."""
from __future__ import annotations

import io
import json
import unittest
from copy import deepcopy
from unittest import mock

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
from formowl_mail import human_uat_orchestrator as owner


MODEL = "synthetic-gemma4:fixture"
DIGEST = "a" * 64


def decision(citations=()):
    return json.dumps({
        "response_kind": "answer", "answer_text": "Synthetic source status is ready.",
        "display_format": "narrative", "citation_ids": list(citations),
        "coverage_status": "incomplete" if citations else "not_applicable",
        "coverage_note": "Bounded evidence only." if citations else "",
    })


def native(message, **extra):
    return {"model": MODEL, "done": True, "done_reason": "stop",
            "prompt_eval_count": 120, "eval_count": 30, "message": message, **extra}


class LocalOllamaProviderTests(unittest.TestCase):
    def model(self, **extra):
        return owner.CodexResponsesConversationModel(
            base_url="http://127.0.0.1:11435", provider_protocol="ollama_chat",
            model=MODEL, expected_model_digest=DIGEST, **extra,
        )

    def transport(self, responses):
        sent = []
        opener = mock.Mock()

        def open_request(request, **kwargs):
            del kwargs
            if request.full_url.endswith("/api/tags"):
                data = {"models": [{"name": MODEL, "digest": DIGEST}]}
            else:
                self.assertEqual(request.full_url, "http://127.0.0.1:11435/api/chat")
                self.assertIsNone(request.get_header("Authorization"))
                sent.append(json.loads(request.data))
                data = responses.pop(0)
                if isinstance(data, Exception):
                    raise data
            response = mock.MagicMock()
            response.status = 200
            response.read.side_effect = io.BytesIO(json.dumps(data).encode()).read
            response.__enter__.return_value = response
            return response

        opener.open.side_effect = open_request
        patch = mock.patch.object(owner.urllib.request, "build_opener", return_value=opener)
        patch.start()
        self.addCleanup(patch.stop)
        return sent, opener

    def test_chat_uses_native_schema_and_no_credentials_proxy_or_redirect(self):
        sent, opener = self.transport([native({"role": "assistant", "content": decision()})])
        model = self.model()
        model.verify_local_model()
        backend = mock.Mock(side_effect=AssertionError("chat must not execute evidence"))
        outcome = model.respond(history=(), user_text="hello", latest_evidence=None,
                                safety_identifier="local-chat", evidence_tool=backend)
        self.assertEqual(outcome.answer_text, "Synthetic source status is ready.")
        backend.assert_not_called()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["options"], {"num_ctx": 32768, "num_predict": 4096})
        self.assertIn("format", sent[0])
        self.assertNotIn("tools", sent[0])
        self.assertNotIn("tool_choice", sent[0])
        self.assertNotIn("reasoning", sent[0])
        handlers = owner.urllib.request.build_opener.call_args.args
        self.assertTrue(any(isinstance(h, owner.urllib.request.ProxyHandler) and h.proxies == {} for h in handlers))
        self.assertTrue(any(isinstance(h, owner._NoResponsesRedirect) for h in handlers))
        self.assertEqual(opener.open.call_count, 2)  # explicit startup GET + exactly one inference
        usage = outcome.provider_diagnostic["provider_attempts"][0]["local_usage"]
        self.assertEqual(usage["prompt_eval_count"], 120)
        self.assertEqual(usage["eval_count"], 30)

    def test_governed_tool_result_and_existing_final_repair_keep_one_request_per_attempt(self):
        prompt = "Find progress for aster label project in documents."
        # Pass the raw descriptor; the owner adds its own grounding guidance once.
        from formowl_gateway.remote import build_remote_tool_descriptors
        descriptor = next(t.model_dump(by_alias=True, exclude_none=True) for t in
                          build_remote_tool_descriptors(required_scope="formowl.use",
                          enabled_tool_names={"whoami", "query_effective_graph_view"})
                          if t.name == "query_effective_graph_view")
        arguments = {"query_text": "Retrieve progress evidence for aster label project from documents.",
                     "required_terms": ["aster label project"], "request_contract": {
                         "original_query_hash": owner.sha256_json(prompt), "query_class": "evidence_lookup",
                         "source_family_scope": ["document_text"], "requested_fields": ["progress"],
                         "maximum_claim_strength": "cited_evidence"}}
        sent, _ = self.transport([
            native({"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": descriptor["name"], "arguments": arguments}}]}),
            native({"role": "assistant", "content": "```json\n" + decision(["synthetic-citation"]) + "\n```"}),
            native({"role": "assistant", "content": decision(["synthetic-citation"])}),
        ])
        model = self.model()
        model.verify_local_model()
        model.configure_conversation_tools(safety_identifier="local-evidence", tool_descriptors=[descriptor])
        backend = mock.Mock(return_value={"status": "partial", "coverage": {"status": "incomplete"},
            "evidence": [{"citation_hash": "synthetic-citation", "snippet": "Aster label project progress is ready."}],
            "citations": ["synthetic-citation"]})
        outcome = model.respond(history=(), user_text=prompt, latest_evidence=None,
            safety_identifier="local-evidence", evidence_tool=backend,
            formowl_tool_descriptor=descriptor, authorized_capability_summary={"source_families": ["document_text"]})
        backend.assert_called_once()
        self.assertEqual(outcome.citation_ids, ("synthetic-citation",))
        self.assertEqual(len(sent), 3)
        self.assertIn("tools", sent[0])
        self.assertNotIn("format", sent[0])
        self.assertIn("format", sent[1])  # existing cited-result policy forces finalization
        self.assertNotIn("tools", sent[1])
        self.assertNotIn("tools", sent[2])
        self.assertIn("format", sent[2])
        self.assertNotIn(owner._CODEX_MAIL_TOOL_ARGUMENT_GUIDANCE, sent[0]["messages"][0]["content"])
        self.assertNotIn(owner._CODEX_GRAPH_TOOL_ARGUMENT_GUIDANCE, sent[1]["messages"][0]["content"])
        self.assertEqual(sent[1]["messages"][0]["content"], sent[0]["messages"][0]["content"].removesuffix(
            "\n\n" + owner._CODEX_GRAPH_TOOL_ARGUMENT_GUIDANCE))
        self.assertEqual(sent[1]["messages"][1:len(sent[0]["messages"])], sent[0]["messages"][1:])
        tool_call = next(m for m in sent[1]["messages"] if m.get("tool_calls"))
        tool_result = next(m for m in sent[1]["messages"] if m["role"] == "tool")
        self.assertEqual(tool_result["tool_call_id"], tool_call["tool_calls"][0]["id"])
        self.assertEqual(tool_result["tool_name"], descriptor["name"])
        self.assertEqual(outcome.provider_diagnostic["provider_attempt_count"], 3)
        self.assertTrue(outcome.provider_diagnostic["finalization_validation"][-1]["repair_attempted"])

    def test_native_failures_stop_without_evidence_or_outbound_fallback(self):
        failures = [native({"role": "assistant", "content": "{}"}, model="wrong-model"),
                    native({"role": "assistant", "content": "{}"}, done_reason="length"),
                    native({"role": "assistant", "content": "{}"}, prompt_eval_count=32768 - 4096),
                    native({"role": "assistant", "content": "{}"}, truncated=True),
                    native({"role": "assistant", "content": "", "tool_calls": [{"function": {
                        "name": "run_shell", "arguments": {"command": "never executed"}}}]}),
                    native({"role": "assistant", "content": decision(), "tool_calls": {}}),
                    owner.urllib.error.URLError(TimeoutError())]
        reasons = ["model_identity_mismatch", "incomplete_status", "input_context_limit", "input_context_limit",
                   "invalid_tool_call", "invalid_tool_call", "transport_timeout"]
        for response, reason in zip(failures, reasons):
            with self.subTest(response_type=type(response).__name__):
                sent, _ = self.transport([response])
                model = self.model()
                model.verify_local_model()
                backend = mock.Mock()
                outcome = model.respond(history=(), user_text="hello", latest_evidence=None,
                                        safety_identifier="local-failure", evidence_tool=backend)
                backend.assert_not_called()
                self.assertNotEqual(outcome.response_kind, "answer")
                self.assertEqual(len(sent), 1)
                self.assertEqual(outcome.provider_diagnostic["reason_code"], reason)

    def test_all_provider_contexts_project_candidate_hashes_but_binder_receives_full_metadata(self):
        capabilities = {"source_families": ["document_text"], "listing_status": "truncated",
            "projection_field_count": 1000, "returned_projection_field_count": 128,
            "capability_fingerprint": "sha256:" + "b" * 64,
            "projection_fields": [{"field": f"field-{i}", "field_hash": "sha256:" + f"{i:064x}",
                "candidate_hashes": ["sha256:" + "a" * 64, "sha256:" + "c" * 64],
                "structure_status": "source_provided", "authorized_family_row_count": i + 1,
                "label_redacted": False} for i in range(128)]}
        expected = {**capabilities, "projection_fields": [
            {k: v for k, v in entry.items() if k != "candidate_hashes"}
            for entry in capabilities["projection_fields"]]}
        real_binder = owner._UatTurnRequestContractBinder
        for protocol in ("native", "responses", "app_server"):
            with self.subTest(protocol=protocol):
                if protocol == "native":
                    sent, _ = self.transport([native({"role": "assistant", "content": decision()})])
                    model = self.model()
                    model.verify_local_model()
                elif protocol == "responses":
                    model = owner.CodexResponsesConversationModel(
                        base_url="https://synthetic.example.test/v1", api_key="synthetic")
                    model._request_response = mock.Mock(return_value={"status": "completed", "output_text": decision()})
                else:
                    transport = mock.Mock()
                    transport.start_thread.return_value = owner.CodexAppServerThread(
                        thread_id="synthetic-context", model_name="synthetic")
                    transport.run_turn.return_value = owner.CodexAppServerTurn(
                        thread_id="synthetic-context", turn_id="synthetic-turn",
                        final_message=decision(), tool_invocations=())
                    model = owner.CodexAppServerConversationModel(
                        transport, workspace_dir="/tmp/synthetic-aq-context")
                self.addCleanup(model.close)
                backend = mock.Mock()
                with mock.patch.object(owner, "_UatTurnRequestContractBinder", side_effect=real_binder) as received:
                    outcome = model.respond(history=(), user_text="hello", latest_evidence=None,
                        safety_identifier="synthetic-context", evidence_tool=backend,
                        authorized_capability_summary=capabilities)
                backend.assert_not_called()
                self.assertEqual(outcome.answer_text, "Synthetic source status is ready.")
                received.assert_called_once()
                self.assertEqual(received.call_args.kwargs["authorized_capability_summary"], capabilities)
                self.assertTrue(all(entry["candidate_hashes"] for entry in
                    received.call_args.kwargs["authorized_capability_summary"]["projection_fields"]))
                if protocol == "app_server":
                    context = transport.run_turn.call_args.kwargs["additional_context"]["formowl_authorized_capabilities"]["value"]
                else:
                    messages = sent[0]["messages"] if protocol == "native" else model._request_response.call_args.args[0]["input"]
                    context = next(m["content"] for m in messages if isinstance(m.get("content"), str)
                        and m["content"].startswith("Server-authoritative FormOwl capabilities"))
                self.assertEqual(json.loads(context.split("\n", 1)[1]), expected)

    def test_native_http_errors_preserve_status_and_only_fixed_context_classification(self):
        for error_type, expected in (("exceed_context_size_error", "input_context_limit"),
                                     ("invalid_request_error", "http_error")):
            with self.subTest(error_type=error_type):
                body = json.dumps({"error": json.dumps({"error": {"type": error_type,
                    "code": 400, "message": "PRIVATE_RAW_BODY_MUST_NOT_APPEAR",
                    "n_prompt_tokens": 60564, "n_ctx": 32768}})}).encode()
                error = owner.urllib.error.HTTPError("http://127.0.0.1:11435/api/chat", 400,
                    "PRIVATE_RAW_EXCEPTION_MUST_NOT_APPEAR", {}, io.BytesIO(body))
                sent, _ = self.transport([error])
                model = self.model()
                model.verify_local_model()
                backend = mock.Mock()
                outcome = model.respond(history=(), user_text="hello", latest_evidence=None,
                    safety_identifier="synthetic-http400", evidence_tool=backend)
                backend.assert_not_called()
                self.assertEqual(len(sent), 1)
                self.assertEqual(outcome.provider_diagnostic["reason_code"], expected)
                self.assertEqual(outcome.provider_diagnostic["http_status"], 400)
                self.assertNotIn("PRIVATE_RAW", json.dumps(outcome.provider_diagnostic))

    def test_all_provider_offered_contracts_and_backend_use_server_query_hash(self):
        from formowl_gateway.remote import build_remote_tool_descriptors
        descriptor = next(t.model_dump(by_alias=True, exclude_none=True) for t in
                          build_remote_tool_descriptors(required_scope="formowl.use",
                          enabled_tool_names={"whoami", "query_effective_graph_view"})
                          if t.name == "query_effective_graph_view")
        original = deepcopy(descriptor)
        prompt = "Find progress for aster label project in documents."
        expected_hash = "sha256:" + owner.hashlib.sha256(prompt.encode()).hexdigest()
        for protocol in ("native", "responses", "app_server"):
            for proposed_hash in (None, "sha256:short"):
                with self.subTest(protocol=protocol, proposed_hash=proposed_hash):
                    arguments = {"query_text": "Retrieve progress evidence for aster label project from documents.",
                        "required_terms": ["aster label project"], "request_contract": {
                            "query_class": "evidence_lookup", "source_family_scope": ["document_text"],
                            "requested_fields": ["progress"], "maximum_claim_strength": "cited_evidence"}}
                    if proposed_hash is not None:
                        arguments["request_contract"]["original_query_hash"] = proposed_hash
                    backend = mock.Mock(return_value={"status": "partial", "coverage": {"status": "incomplete"},
                        "evidence": [{"citation_hash": "synthetic-citation", "snippet": "Aster label project progress is ready."}],
                        "citations": ["synthetic-citation"]})
                    if protocol == "native":
                        sent, _ = self.transport([
                            native({"role": "assistant", "content": "", "tool_calls": [{"function": {
                                "name": descriptor["name"], "arguments": arguments}}]}),
                            native({"role": "assistant", "content": decision(["synthetic-citation"])})])
                        model = self.model()
                        model.verify_local_model()
                    elif protocol == "responses":
                        model = owner.CodexResponsesConversationModel(
                            base_url="https://synthetic.example.test/v1", api_key="synthetic")
                        model._request_response = mock.Mock(side_effect=[
                            {"status": "completed", "output": [{"type": "function_call", "name": descriptor["name"],
                                "call_id": "synthetic-call", "arguments": json.dumps(arguments)}]},
                            {"status": "completed", "output_text": decision(["synthetic-citation"])}])
                    else:
                        transport = mock.Mock()
                        transport.start_thread.return_value = owner.CodexAppServerThread(
                            thread_id="synthetic-hash", model_name="synthetic")
                        def run_turn(**kwargs):
                            result = kwargs["tool_handler"](descriptor["name"], arguments)
                            return owner.CodexAppServerTurn(thread_id="synthetic-hash", turn_id="synthetic-turn",
                                final_message=decision(["synthetic-citation"]), tool_invocations=(
                                    owner.CodexDynamicToolInvocation(thread_id="synthetic-hash", turn_id="synthetic-turn",
                                        call_id="synthetic-call", tool_name=descriptor["name"], arguments=arguments, result=result),))
                        transport.run_turn.side_effect = run_turn
                        model = owner.CodexAppServerConversationModel(transport, workspace_dir="/tmp/synthetic-aq-hash")
                    self.addCleanup(model.close)
                    outcome = model.respond(history=(), user_text=prompt, latest_evidence=None,
                        safety_identifier="synthetic-hash", evidence_tool=backend, formowl_tool_descriptor=descriptor,
                        authorized_capability_summary={"source_families": ["document_text"]})
                    backend.assert_called_once()
                    self.assertEqual(backend.call_args.args[0].request_contract["original_query_hash"], expected_hash)
                    self.assertEqual(outcome.citation_ids, ("synthetic-citation",))
                    if protocol == "app_server":
                        schema = transport.start_thread.call_args.kwargs["dynamic_tools"][0]["inputSchema"]
                    elif protocol == "native":
                        schema = sent[0]["tools"][0]["function"]["parameters"]
                    else:
                        schema = model._request_response.call_args_list[0].args[0]["tools"][0]["parameters"]
                    contract = schema["properties"]["request_contract"]
                    self.assertNotIn("original_query_hash", contract["properties"])
                    self.assertNotIn("original_query_hash", contract["required"])
                    self.assertEqual(set(contract["required"]), {
                        "query_class", "source_family_scope", "requested_fields", "maximum_claim_strength"})
                    self.assertEqual(descriptor, original)  # real MCP/server schema keeps all five keys

    def test_binder_hash_fill_preserves_frozen_contract_and_backend_hash_rejection(self):
        binder = owner._UatTurnRequestContractBinder(user_text="Find aster progress in documents.",
            authorized_capability_summary={"source_families": ["document_text"]})
        proposal = {"query_class": "evidence_lookup", "source_family_scope": ["document_text"],
            "requested_fields": ["progress"], "maximum_claim_strength": "cited_evidence"}
        bound = binder.bind(proposal, table_query=None)
        self.assertEqual(bound["original_query_hash"], binder._original_query_hash)
        binder._required_term_placement = object()  # exercise existing immutable-contract comparison
        self.assertEqual(binder.bind({**proposal, "original_query_hash": "short"}, table_query=None), bound)
        with self.assertRaises(ContractValidationError):
            binder.bind({**proposal, "requested_fields": ["other"]}, table_query=None)
        fresh = owner._UatTurnRequestContractBinder(user_text="Find aster progress in documents.",
            authorized_capability_summary={"source_families": ["document_text"]})
        with self.assertRaises(ContractValidationError):
            fresh.bind({**proposal, "unknown_key": True}, table_query=None)
        request = owner.UatEvidenceToolRequest(query_text="aster progress", request_contract=bound)
        self.assertFalse(owner._exact_capability_result_bindings_clean([(request, {
            "query_agent": {"original_query_hash": "sha256:" + "f" * 64}})]))
        page_binder = owner._UatTurnRequestContractBinder(user_text="Find aster progress.",
            authorized_capability_summary={"source_families": ["mail"]})
        locator = {"kind": "attachment_page", "page": 2}
        page_binder._native_page = (locator,)
        schema = owner._model_tool_parameters(owner._validated_formowl_tool_descriptor(None),
            request_contract_binder=page_binder)
        self.assertIn("request_contract", schema["required"])
        self.assertIn("native_locator", schema["properties"]["request_contract"]["required"])
        page_proposal = {**proposal, "source_family_scope": ["mail"], "native_locator": locator}
        page_bound = page_binder.bind(page_proposal, table_query=None)
        self.assertEqual(page_binder.bind({**page_proposal, "original_query_hash": "short"}, table_query=None), page_bound)
        with self.assertRaises(ContractValidationError):
            page_binder.bind({**page_proposal, "native_locator": {**locator, "page": 3}}, table_query=None)

    def test_catalog_required_matches_parser_for_all_provider_and_journal_paths(self):
        descriptor = owner._validated_formowl_tool_descriptor(None)
        prompt = "Find progress for aster label project in documents."
        history = (owner.UatConversationMessage(role="user", content=prompt),
                   owner.UatConversationMessage(role="assistant", content="Prior clarification."))
        for protocol in ("native", "responses", "app_server"):
            with self.subTest(protocol=protocol):
                if protocol == "native":
                    sent, _ = self.transport([native({"role": "assistant", "content": decision()}) for _ in range(6)])
                    model = self.model()
                    model.verify_local_model()
                elif protocol == "responses":
                    model = owner.CodexResponsesConversationModel(
                        base_url="https://synthetic.example.test/v1", api_key="synthetic")
                    model._request_response = mock.Mock(return_value={"status": "completed", "output_text": decision()})
                else:
                    transport = mock.Mock()
                    transport.start_thread.side_effect = [owner.CodexAppServerThread(
                        thread_id=f"synthetic-catalog-{n}", model_name="synthetic") for n in (1, 2)]
                    transport.run_turn.side_effect = lambda **kw: owner.CodexAppServerTurn(
                        thread_id=kw["thread_id"], turn_id="synthetic-turn", final_message=decision(), tool_invocations=())
                    model = owner.CodexAppServerConversationModel(transport, workspace_dir="/tmp/synthetic-aq-catalog")
                self.addCleanup(model.close)
                if protocol != "app_server":
                    model.configure_conversation_tools(safety_identifier="synthetic-catalog", tool_descriptors=[descriptor])
                for index, catalog in enumerate(({}, None)):  # is not None includes an empty catalog
                    capabilities = {"source_families": ["document_text"]}
                    turn_descriptor = deepcopy(descriptor)
                    if catalog is not None:
                        capabilities["reviewed_annotation_catalog"] = catalog
                        turn_descriptor["inputSchema"]["required"].append("required_terms")
                    model.respond(history=history if index else (), user_text=prompt, latest_evidence=None,
                        safety_identifier="synthetic-catalog", evidence_tool=mock.Mock(),
                        formowl_tool_descriptor=turn_descriptor, authorized_capability_summary=capabilities)
                    if protocol == "app_server":
                        schema = transport.start_thread.call_args.kwargs["dynamic_tools"][0]["inputSchema"]
                        if index:
                            transport.delete_thread.assert_called_once_with("synthetic-catalog-1")
                            context = transport.run_turn.call_args.kwargs["additional_context"]
                            self.assertEqual(json.loads(context["formowl_recovery_history"]["value"]),
                                [{"role": m.role, "content": m.content} for m in history])
                    elif protocol == "native":
                        schema = sent[index]["tools"][0]["function"]["parameters"]
                        if index:
                            self.assertGreaterEqual(sum(m.get("content") == prompt for m in sent[index]["messages"]), 2)
                            self.assertTrue(any(m["role"] == "assistant" for m in sent[index]["messages"]))
                    else:
                        payload = model._request_response.call_args_list[index].args[0]
                        schema = payload["tools"][0]["parameters"]
                        if index:
                            self.assertGreaterEqual(sum(m.get("content") == prompt for m in payload["input"]), 2)
                            self.assertTrue(any(m.get("role") == "assistant" or m.get("type") == "message" for m in payload["input"]))
                    self.assertEqual("reviewed_annotation_ids" in schema["required"], catalog is not None)
                    self.assertEqual("required_terms" in schema["required"], catalog is not None)
                    self.assertNotIn("request_contract", schema["required"])  # typed expansion remains legal
                    self.assertNotIn("original_query_hash", schema["properties"]["request_contract"]["properties"])
                    binder = owner._UatTurnRequestContractBinder(user_text=prompt, authorized_capability_summary=capabilities)
                    arguments = {"query_text": "Retrieve progress for aster label project from documents.",
                                 "required_terms": ["aster label project"]}
                    if catalog is not None:
                        with self.assertRaisesRegex(ContractValidationError, "annotation decision is required"):
                            owner._parse_tool_request(arguments, tool_descriptor=descriptor, request_contract_binder=binder)
                        self.assertNotIn("reviewed_annotation_ids", arguments)
                    else:
                        owner._parse_tool_request(arguments, tool_descriptor=descriptor, request_contract_binder=binder)
        catalog = {"entries": []}
        catalog["catalog_pin"] = owner.sha256_json(catalog)
        binder = owner._UatTurnRequestContractBinder(user_text=prompt, authorized_capability_summary={
            "source_families": ["document_text"], "reviewed_annotation_catalog": catalog})
        explicit = owner._parse_tool_request({**arguments, "reviewed_annotation_ids": []},
            tool_descriptor=descriptor, request_contract_binder=binder)
        self.assertEqual(explicit.reviewed_annotation_ids, ())
        self.assertEqual(explicit.reviewed_annotation_pin, catalog["catalog_pin"])

    def test_explicit_context_allowlist_preserves_request_and_usage_counts(self):
        for context_limit in (32768, 65536):
            with self.subTest(context_limit=context_limit):
                sent, _ = self.transport([native({"role": "assistant", "content": decision()})])
                model = self.model(ollama_num_ctx=context_limit)
                model.verify_local_model()
                outcome = model.respond(history=(), user_text="hello", latest_evidence=None,
                    safety_identifier="synthetic-context-limit", evidence_tool=mock.Mock())
                self.assertEqual(sent[0]["options"]["num_ctx"], context_limit)
                self.assertEqual(sent[0]["options"]["num_predict"], 4096)
                self.assertEqual(outcome.provider_diagnostic["provider_attempts"][0]["local_usage"]["num_ctx"], context_limit)

    def test_actual_provider_instructions_include_only_active_tool_argument_guidance(self):
        from formowl_gateway.remote import build_remote_tool_descriptors
        tools = {t.name: t.model_dump(by_alias=True, exclude_none=True) for t in
                 build_remote_tool_descriptors(required_scope="formowl.use", enabled_tool_names={
                     "whoami", "query_effective_graph_view", "query_mail_evidence"})}
        for protocol in ("native", "responses", "app_server"):
            for tool_name in ("query_effective_graph_view", "query_mail_evidence"):
                with self.subTest(protocol=protocol, tool=tool_name):
                    descriptor = tools[tool_name]
                    if protocol == "native":
                        sent, _ = self.transport([native({"role": "assistant", "content": decision()}) for _ in range(6)])
                        model = self.model()
                        model.verify_local_model()
                    elif protocol == "responses":
                        model = owner.CodexResponsesConversationModel(
                            base_url="https://synthetic.example.test/v1", api_key="synthetic")
                        model._request_response = mock.Mock(return_value={"status": "completed", "output_text": decision()})
                    else:
                        transport = mock.Mock()
                        transport.start_thread.return_value = owner.CodexAppServerThread(
                            thread_id="synthetic-guidance", model_name="synthetic")
                        transport.run_turn.return_value = owner.CodexAppServerTurn(
                            thread_id="synthetic-guidance", turn_id="synthetic-turn", final_message=decision(), tool_invocations=())
                        model = owner.CodexAppServerConversationModel(transport, workspace_dir="/tmp/synthetic-aq-guidance")
                    self.addCleanup(model.close)
                    if protocol != "app_server":
                        model.configure_conversation_tools(safety_identifier="synthetic-guidance", tool_descriptors=[descriptor])
                    model.respond(history=(), user_text="Find progress for aster label project.", latest_evidence=None,
                        safety_identifier="synthetic-guidance", evidence_tool=mock.Mock(), formowl_tool_descriptor=descriptor,
                        authorized_capability_summary={"source_families": ["mail" if tool_name == "query_mail_evidence" else "document_text"]})
                    if protocol == "native":
                        instructions = sent[0]["messages"][0]["content"]
                        self.assertEqual([t["function"]["name"] for t in sent[0]["tools"]], [tool_name])
                    elif protocol == "responses":
                        payload = model._request_response.call_args_list[0].args[0]
                        instructions = payload["instructions"]
                        self.assertIn(tool_name, [t["name"] for t in payload["tools"]])
                    else:
                        kwargs = transport.start_thread.call_args.kwargs
                        instructions = kwargs["base_instructions"] + "\n" + kwargs["developer_instructions"]
                        self.assertEqual([t["name"] for t in kwargs["dynamic_tools"]], [tool_name])
                    selected, excluded = ((owner._CODEX_MAIL_TOOL_ARGUMENT_GUIDANCE, owner._CODEX_GRAPH_TOOL_ARGUMENT_GUIDANCE)
                        if tool_name == "query_mail_evidence" else
                        (owner._CODEX_GRAPH_TOOL_ARGUMENT_GUIDANCE, owner._CODEX_MAIL_TOOL_ARGUMENT_GUIDANCE))
                    self.assertIn(selected, instructions)
                    self.assertNotIn(excluded, instructions)
                    self.assertIn(owner._SAFE_FINAL_PROSE_GUIDANCE, instructions)
                    self.assertIn(owner._FIELD_ROLE_GROUNDING_GUIDANCE, instructions)

    def test_external_endpoint_credentials_and_context_raise_before_network(self):
        for changes in ({"base_url": "https://external.example.test"}, {"api_key": "forbidden"},
                        {"ollama_num_ctx": 49152}, {"base_url": "http://localhost:11435"}):
            with self.subTest(changes=changes), mock.patch.object(owner.urllib.request, "build_opener") as network:
                values = dict(base_url="http://127.0.0.1:11435", provider_protocol="ollama_chat",
                              model=MODEL, expected_model_digest=DIGEST)
                values.update(changes)
                with self.assertRaises(ContractValidationError):
                    owner.CodexResponsesConversationModel(**values)
                network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
