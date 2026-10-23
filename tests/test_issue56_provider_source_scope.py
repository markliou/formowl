"""Source-family planning regressions; no provider or private source required."""
from __future__ import annotations

import hashlib
import json
import unittest
from unittest.mock import Mock, patch

import _paths  # noqa: F401
from formowl_contract import ContractValidationError
from formowl_gateway.remote import build_remote_tool_descriptors
from formowl_mail import human_uat_orchestrator as orchestrator
from formowl_mail.semantic_plan import validate_semantic_request_contract


def _descriptor():
    return next(
        tool.model_dump(by_alias=True, exclude_none=True)
        for tool in build_remote_tool_descriptors(
            required_scope="formowl.use", enabled_tool_names={"whoami", "query_effective_graph_view"},
        ) if tool.name == "query_effective_graph_view"
    )


def _arguments(prompt, families):
    query_class = orchestrator.deterministic_query_class(prompt)
    return {
        "query_text": "Retrieve authorized source text containing orchid with native citations.",
        "required_terms": ["orchid"],
        "request_contract": {
            "original_query_hash": "sha256:" + hashlib.sha256(prompt.encode()).hexdigest(),
            "query_class": query_class, "source_family_scope": families,
            "requested_fields": ["content"],
            "maximum_claim_strength": orchestrator.SEMANTIC_CLAIM_STRENGTH_BY_CLASS[query_class],
        },
    }


class ProviderSourceScopeTests(unittest.TestCase):
    def test_three_available_families_fit_both_schema_and_runtime_contract(self):
        prompt = "Find orchid and cite the authorized evidence."
        families = ["mail", "attachment_table", "document_text"]
        scope_schema = _descriptor()["inputSchema"]["properties"]["request_contract"]["properties"]["source_family_scope"]
        self.assertEqual(scope_schema["maxItems"], 3)
        binder = orchestrator._UatTurnRequestContractBinder(
            user_text=prompt, authorized_capability_summary={"source_families": families},
        )
        request = orchestrator._parse_tool_request(
            _arguments(prompt, families), tool_descriptor=_descriptor(), request_contract_binder=binder,
        )
        self.assertEqual(set(request.request_contract["source_family_scope"]), set(families))
        for rejected in ([], ["mail", "mail"], ["mail", "attachment_table", "document_text", "other"], ["other"]):
            with self.subTest(rejected=rejected), self.assertRaises(ContractValidationError):
                validate_semantic_request_contract(
                    _arguments(prompt, rejected)["request_contract"], available_source_families=families,
                )

    def test_attachment_container_is_not_implicitly_a_native_table(self):
        available = ["mail", "attachment_table", "document_text"]
        # An attachment is a container (SPEC §7): naming mail must not hide the
        # native tables inside mail attachments, so mail-attachment requests
        # keep both attachment-bearing families. Explicit table or independent
        # document wording still narrows the scope as before.
        cases = (
            ("請查郵件附件中 orchid 的段落", ["attachment_table", "mail"]),
            ("Find orchid in mail attachments.", ["attachment_table", "mail"]),
            ("Find orchid in attachments.", ["attachment_table", "mail"]),
            ("Find orchid in an attached document.", ["attachment_table", "mail"]),
            ("Find orchid in an attached PDF document.", ["attachment_table", "mail"]),
            ("Find orchid in a document in mail attachments.", ["attachment_table", "mail"]),
            ("Find orchid in an attached file.", ["attachment_table", "mail"]),
            ("查附件文件中 orchid 的內容", ["attachment_table", "mail"]),
            ("請查郵件附件中的文件內容，找 orchid", ["attachment_table", "mail"]),
            ("請查郵件附件中的文件以及獨立文件，找 orchid", ["attachment_table", "document_text", "mail"]),
            ("查附件中 orchid 的內容", ["attachment_table", "mail"]),
            ("查附件表格中 orchid 的欄位", ["attachment_table"]),
            ("Find orchid in an attachment spreadsheet.", ["attachment_table"]),
            ("Find orchid in an independent document.", ["document_text"]),
            ('Find orchid only in "mail".', ["mail"]),
            ("只查「郵件」中的 orchid 內容", ["mail"]),
            ('Find orchid in an independent document containing the literal word "mail".', ["document_text"]),
            ("在獨立文件中找 orchid 和「郵件」一詞", ["document_text"]),
            ("查附件與獨立文件中 orchid 的內容", ["attachment_table", "document_text", "mail"]),
        )
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                binder = orchestrator._UatTurnRequestContractBinder(
                    user_text=prompt, authorized_capability_summary={"source_families": available},
                )
                self.assertEqual(sorted(binder.trusted_context()["required_source_family_scope"]), expected)
                request = orchestrator._parse_tool_request(
                    _arguments(prompt, expected), tool_descriptor=_descriptor(),
                    request_contract_binder=binder,
                )
                self.assertEqual(sorted(request.request_contract["source_family_scope"]), expected)

    def test_attachment_source_label_is_not_a_content_filter_unless_explicit(self):
        for prompt, term, literal in (
            ("請找郵件附件中的 orchid 段落", "附件", False),
            ("Find orchid in mail attachments.", "attachments", False),
            ("請查郵件附件中的文件內容，找 orchid", "文件", False),
            ("Find orchid in mail attachments with an attached document.", "document", False),
            ("請查郵件附件中的文件內容，找 orchid 與「文件」一詞", "文件", True),
            ("Find orchid in mail attachments with an attached document containing the literal word document.", "document", True),
            ("Find orchid in mail attachments containing the literal word attachments.", "attachments", True),
            ("請找郵件附件中包含「附件」字樣的 orchid 段落", "附件", True),
        ):
            with self.subTest(prompt=prompt):
                binder = orchestrator._UatTurnRequestContractBinder(
                    user_text=prompt, authorized_capability_summary={"source_families": ["mail"]},
                )
                arguments = _arguments(prompt, ["mail"])
                arguments["required_terms"] = [term]
                if literal:
                    request = orchestrator._parse_tool_request(
                        arguments, tool_descriptor=_descriptor(), request_contract_binder=binder,
                    )
                    self.assertEqual(request.required_terms, (term,))
                else:
                    with self.assertRaisesRegex(ContractValidationError, "source-family label"):
                        orchestrator._parse_tool_request(
                            arguments, tool_descriptor=_descriptor(), request_contract_binder=binder,
                        )

    def test_text_attachment_needs_no_table_capability_or_mail_session(self):
        prompt = "請找郵件附件中的文件內容，查 orchid 段落"
        binder = orchestrator._UatTurnRequestContractBinder(
            user_text=prompt, authorized_capability_summary={"source_families": ["mail"]},
        )
        request = orchestrator._parse_tool_request(
            _arguments(prompt, ["mail"]), tool_descriptor=_descriptor(), request_contract_binder=binder,
        )
        self.assertEqual(request.request_contract["source_family_scope"], ["mail"])
        self.assertIsNone(request.mail_import_session_id)
        denied = orchestrator._UatTurnRequestContractBinder(
            user_text=prompt, authorized_capability_summary={"source_families": ["document_text"]},
        )
        with self.assertRaises(ContractValidationError):
            orchestrator._parse_tool_request(
                _arguments(prompt, ["document_text"]), tool_descriptor=_descriptor(), request_contract_binder=denied,
            )

    def test_invalid_table_scope_can_repair_before_one_mcp_call(self):
        prompt = "請查郵件附件中 orchid 的段落"
        capabilities = {"source_families": ["mail", "attachment_table", "document_text"]}
        provider = orchestrator.CodexResponsesConversationModel(
            base_url="https://provider.example.test/v1", api_key="synthetic-key",
        )
        citation = "sha256:" + "a" * 64
        backend = Mock(return_value={
            "status": "ok", "citations": [citation], "coverage": {"status": "incomplete"},
            "evidence": [{"citation_hash": citation, "snippet": "orchid source text"}],
        })
        calls = []

        def respond(payload):
            calls.append(payload)
            if len(calls) <= 2:
                backend.assert_not_called()
                boundary = next(
                    json.loads(item["content"].split("\n", 1)[1])
                    for item in payload["input"]
                    if item.get("role") == "developer"
                    and "immutable FormOwl boundary" in item.get("content", "")
                )
                self.assertEqual(boundary["required_source_family_scope"], ["attachment_table", "mail"])
                if len(calls) == 2:
                    control = json.loads(next(item["output"] for item in reversed(payload["input"])
                                              if item.get("type") == "function_call_output"))
                    self.assertEqual(control["execution_control"]["stop_reason"], "invalid_arguments")
                    self.assertEqual(control["execution_control"]["remaining_mcp_calls"], 2)
                return {"status": "completed", "output": [{
                    "type": "function_call", "call_id": f"scope-{len(calls)}",
                    "name": "query_effective_graph_view",
                    "arguments": json.dumps(_arguments(
                        prompt, ["document_text"] if len(calls) == 1 else ["attachment_table", "mail"],
                    )),
                }]}
            self.assertEqual(len(calls), 3)
            backend.assert_called_once()
            return {"status": "completed", "output_text": json.dumps({
                "response_kind": "answer", "answer_text": "orchid source text",
                "display_format": "narrative", "citation_ids": [citation],
                "coverage_status": "incomplete", "coverage_note": "Only bounded evidence is available.",
            })}

        with patch.object(provider, "_request_response", side_effect=respond):
            outcome = provider.respond(
                history=(), user_text=prompt, latest_evidence=None, safety_identifier="scope-diagnostic",
                evidence_tool=backend, formowl_tool_descriptor=_descriptor(),
                authorized_capability_summary=capabilities,
            )
        self.assertEqual(outcome.response_kind, "answer")
        self.assertEqual(outcome.citation_ids, (citation,))
        self.assertEqual(
            sorted(backend.call_args.args[0].request_contract["source_family_scope"]),
            ["attachment_table", "mail"],
        )
        self.assertEqual(len(outcome.tool_requests), 1)


if __name__ == "__main__":
    unittest.main()
