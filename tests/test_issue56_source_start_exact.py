"""Offline source-start cell execution through the established source owners."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, sha256_json
from formowl_gateway import issue56_sealed_source_loader as loader
from formowl_mail import issue56_sealed_source
from formowl_mail.human_uat_orchestrator import (
    UatEvidenceToolRequest, _UatTurnRequestContractBinder, _validated_field_support,
)
from formowl_retrieval.gateway import source_evidence_deadline_scope
from scripts.issue56_source_native_lookup import build_lookup
from test_issue56_uat_handler_composition import _source_start_preparation_fixture
from test_connected_attachment_hybrid_e2e import _formal_xlsx_bytes
import test_issue56_attachment_text_browser_e2e as attachment_fixture


def _native_table_bytes(*, duplicate=False, blank=False, missing_columns=()):
    output = io.BytesIO()
    with ZipFile(io.BytesIO(_formal_xlsx_bytes())) as source, ZipFile(output, "w") as target:
        for member in source.infolist():
            content = source.read(member.filename)
            for old, new in ((b"Category", b"Code"), (b"ROW-FILTER-42", b"ITEM-Q73"), (b"VALUE-7", b"staged")):
                content = content.replace(old, new)
            # Change the second source column independently of the first.
            content = content.replace(b'<tableColumn id="2" name="Code"/>', b'<tableColumn id="2" name="State"/>')
            content = content.replace(b'<c r="B1" t="inlineStr"><is><t>Code</t></is></c>', b'<c r="B1" t="inlineStr"><is><t>State</t></is></c>')
            content = content.replace(b'ref="A1:B2"', b'ref="A1:C2"')
            content = content.replace(b'<tableColumns count="2">', b'<tableColumns count="3">')
            extra_label = b"State" if duplicate else b"Capacity"
            content = content.replace(b'</tableColumns>', b'<tableColumn id="3" name="' + extra_label + b'"/></tableColumns>')
            content = content.replace(b'</c></row>', b'</c><c r="C1" t="inlineStr"><is><t>' + extra_label + b'</t></is></c></row>', 1)
            content = content.replace(b'<c r="B2" t="inlineStr"><is><t>staged</t></is></c></row>',
                                      b'<c r="B2" t="inlineStr"><is><t>staged</t></is></c><c r="C2" t="inlineStr"><is><t>18</t></is></c></row>')
            if blank:
                content = content.replace(b'<c r="C2" t="inlineStr"><is><t>18</t></is></c>', b'<c r="C2"/>')
            for coordinate, value in (("B2", "staged"), ("C2", "18")):
                if coordinate in missing_columns:
                    content = content.replace(
                        f'<c r="{coordinate}" t="inlineStr"><is><t>{value}</t></is></c>'.encode(), b"",
                    )
            target.writestr(member, content)
    return output.getvalue()


def _native_price_quantity_bytes():
    """Literal synthetic source values, not numeric execution or arithmetic."""
    output = io.BytesIO()
    with ZipFile(io.BytesIO(_native_table_bytes())) as source, ZipFile(output, "w") as target:
        for member in source.infolist():
            content = source.read(member.filename)
            for old, new in ((b"ITEM-Q73", b"PART-N62"), (b"State", b"UnitPrice"),
                             (b"Capacity", b"Quantity"), (b"staged", b"12.50")):
                content = content.replace(old, new)
            target.writestr(member, content)
    return output.getvalue()


def _native_prefixed_identifier_bytes():
    """Native numeric value whose source schema supplies the ``PO`` prefix."""
    output = io.BytesIO()
    with ZipFile(io.BytesIO(_native_table_bytes())) as source, ZipFile(output, "w") as target:
        for member in source.infolist():
            content = source.read(member.filename)
            content = content.replace(b"Code", b"PO No.")
            content = content.replace(b"ITEM-Q73", b"470002002")
            target.writestr(member, content)
    return output.getvalue()


class SourceStartExactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def prepare(self, *, inline=False, content=None, mail_text=None, document_text=None):
        options = {"inline_html": content or (
            "<table><tr><th>Code</th><th>State</th><th>Capacity</th></tr>"
            "<tr><td>ITEM-Q73</td><td>staged</td><td>18</td></tr>"
            "<tr><td>ITEM-R84</td><td>review</td><td>27</td></tr></table>"
        )} if inline else {"attachment_content": (
            content or _native_table_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )}
        fixture_options = {"mail_text": mail_text} if mail_text is not None else {}
        if document_text is not None:
            fixture_options["document_text"] = document_text
        fixture = _source_start_preparation_fixture(
            self.root, families=("mail", "document_text") if document_text is not None else ("mail",),
            **options, **fixture_options,
        )
        output = self.root / "lookup"
        build_lookup(directory=fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
                     output_directory=output)
        for name in ("source-lookup-manifest.json", "source-lookup.sqlite"):
            shutil.copyfile(output / name, fixture.directory / name)
        revision = issue56_sealed_source.load_issue56_ingestion_revision(
            fixture.directory, expected_revision_sha256=fixture.preparation_sha256,
        )
        self.assertIsNone(revision.session)
        handler = loader._build_source_start_semantic_handler(revision, mail_tool=inline)
        query = "Find ITEM-Q73 State and Capacity"
        arguments = {
            "query_text": query, "requester_user_id": loader.APPROVER_ACTOR,
            "workspace_id": loader.WORKSPACE_ID, "session_id": "synthetic-exact-source",
            "request_contract": {
                "original_query_hash": sha256_json(query), "query_class": "evidence_lookup",
                "source_family_scope": ["mail" if inline else "attachment_table"],
                "requested_fields": ["State", "Capacity"], "maximum_claim_strength": "cited_evidence",
            },
            "table_query": {"filters": [{"field": "Code", "value": "ITEM-Q73"}],
                            "projection_fields": ["State", "Capacity"]},
        }
        if inline:
            arguments["mail_import_session_id"] = revision.source_records.authorized_mail_import_session_ids[0]
        return fixture, revision, handler, arguments

    def assert_values(self, result):
        self.assertEqual(result["status"], "partial", result)
        self.assertTrue(result["deterministic_exact"])
        exact = result["exact_result"]
        self.assertEqual(exact["status"], "incomplete")
        self.assertFalse(exact["coverage"]["authorized_scope_complete"])
        self.assertFalse(exact["coverage"]["global_scope_complete"])
        values = [(item["field"], item["value"]) for row in exact["items"] for item in row["structured_values"]]
        self.assertEqual(set(values), {("State", "staged"), ("Capacity", "18")})
        self.assertEqual(result["requested_field_coverage"]["missing_fields"], [])
        coverage = dict(result["requested_field_coverage"])
        fingerprint = coverage.pop("coverage_fingerprint")
        self.assertEqual(fingerprint, sha256_json(coverage))
        self.assertEqual(coverage["request_contract_fingerprint"], sha256_json(result["query_agent"]["request_contract"]))
        self.assertEqual(coverage["evidence_citation_hashes"], sorted(item["citation_hash"] for item in result["evidence"]))
        request = UatEvidenceToolRequest(
            query_text="Find ITEM-Q73 State and Capacity",
            request_contract=result["query_agent"]["request_contract"],
        )
        self.assertEqual(_validated_field_support(request, result), {sha256_json("State"), sha256_json("Capacity")})
        self.assertEqual(len(result["evidence"]), 1)
        self.assertTrue(result["citations"])
        self.assertEqual(result["coverage"]["status"], "incomplete")
        self.assertFalse(result["coverage"]["absence_claim"])

    def test_excerpt_contract_reaches_source_but_explicit_inventory_does_not(self):
        case = attachment_fixture.AttachmentTextBrowserTests()
        self.addCleanup(case.doCleanups)
        _root, child, document, revision = case._fixture()
        self.assertIsNone(revision.session)
        self.assertIsNone(revision.graph_build)
        handler = loader._build_source_start_semantic_handler(revision, mail_tool=False)
        cases = (
            ("搜尋郵件附件的 synthetic 段落，列出原文和來源引用。", "mail", child, False),
            ("找出獨立文件的 written owner approval 條款，列出相關原文。", "document_text", document, False),
            ("列出所有郵件附件。", "mail", child, True),
            ("count independent documents", "document_text", document, True),
            ("列出每封授權郵件。", "mail", child, True),
            ("列出每一个授權郵件附件。", "mail", child, True),
            ("列出每一份授權文件。", "document_text", document, True),
            ("列出每条授权文件记录。", "document_text", document, True),
            ("列出每組授權郵件。", "mail", child, True),
            ("每一張授權文件請列舉。", "document_text", document, True),
        )
        for prompt, family, observation, exact in cases:
            with self.subTest(family=family, exact=exact):
                binder = _UatTurnRequestContractBinder(
                    user_text=prompt, authorized_capability_summary=handler.authorized_capability_summary,
                )
                contract = binder.bind({
                    "original_query_hash": sha256_json(prompt), "query_class": "evidence_lookup",
                    "source_family_scope": [family], "requested_fields": ["content"],
                    "maximum_claim_strength": "cited_evidence",
                }, table_query=None)
                with patch.object(loader, "source_evidence_double_check",
                                  wraps=loader.source_evidence_double_check) as recovery:
                    result = handler({
                        "query_text": prompt, "requester_user_id": loader.APPROVER_ACTOR,
                        "workspace_id": loader.WORKSPACE_ID, "session_id": "synthetic-excerpt-intent",
                        "required_terms": [observation.text], "request_contract": contract,
                    })
                if exact:
                    self.assertEqual(contract["query_class"], "exact_set_or_inventory")
                    self.assertEqual(contract["maximum_claim_strength"], "complete_authorized_scope")
                    self.assertEqual(result["status"], "pending_review")
                    self.assertIn("skipped_exact", result["warnings"])
                    self.assertFalse(result["citations"])
                    recovery.assert_not_called()
                else:
                    self.assertTrue(result["citations"], result)
                    self.assertEqual(contract["query_class"], "evidence_lookup")
                    self.assertEqual(contract["maximum_claim_strength"], "cited_evidence")
                    recovery.assert_called_once()
                    trace = result["query_agent"]["context_bundle"]["source_recovery"]
                    self.assertTrue(trace["attempted"])
                    # Graph source-start reports extraction coverage, not the
                    # exact/mail absence_claim field. Require its actual safety
                    # contract: cited evidence, never exhaustive/absence proof.
                    self.assertEqual(result["status"], "ok")
                    self.assertFalse(result["deterministic_exact"])
                    self.assertIsNone(result["exact_result"])
                    self.assertEqual(result["coverage"]["status"], "incomplete")
                    self.assertIs(result["coverage"]["source_completeness_certified"], False)
                    self.assertTrue(any(item["citation_hash"] == sha256_json(observation.to_dict())
                                        and item["snippet"] == observation.text for item in result["evidence"]))

    def test_attachment_typed_cells_without_projection_preserve_row_and_source_citations(self):
        fixture, revision, handler, arguments = self.prepare()
        sealed_before = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in fixture.directory.rglob("*") if path.is_file()}
        with patch.object(loader, "execute_deterministic_source_occurrence_inventory",
                          wraps=loader.execute_deterministic_source_occurrence_inventory) as executor:
            result = handler(arguments)
        self.assertEqual(executor.call_count, 1)
        self.assert_values(result)
        native_hashes = {sha256_json(item.to_dict()) for item in fixture.observations}
        for row in result["exact_result"]["items"]:
            self.assertTrue(set(row["cited_observation_hashes"]) <= native_hashes)
            for value in row["structured_values"]:
                self.assertIn(value["citation_hash"], native_hashes)
                self.assertTrue(value["occurrence_lineage_fingerprint"].startswith("sha256:"))
        self.assertEqual(sealed_before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in sealed_before})
        capabilities = handler.authorized_capability_summary
        self.assertEqual({item["field"] for item in capabilities["projection_fields"]}, {"Code", "State", "Capacity"})
        self.assertTrue(capabilities["query_contract"]["structured_table_query_supported"])
        self.assertFalse(capabilities["query_contract"]["complete_inventory_supported"])
        self.assertFalse(capabilities["query_contract"]["native_formula_recalculation_supported"])
        self.assertEqual(revision.safe_binding["source_authority_fingerprint"], result["evidence"][0]["revision_binding"]["source_authority_fingerprint"])
        arguments["request_contract"].update(
            query_class="exact_set_or_inventory", maximum_claim_strength="complete_authorized_scope",
        )
        self.assert_values(handler(arguments))

    def test_inline_candidate_table_retains_evidence_but_cannot_claim_exact_schema(self):
        _, _, handler, arguments = self.prepare(inline=True)
        result = handler(arguments)
        self.assertEqual(result["status"], "clarification_required")
        self.assertFalse(result["deterministic_exact"])
        self.assertFalse(handler.authorized_capability_summary["query_contract"]["structured_table_query_supported"])
        arguments.pop("table_query")
        arguments["query_text"] = "Find native row evidence"
        arguments["required_terms"] = ["ITEM-Q73"]
        result = handler(arguments)
        self.assertFalse(result.get("deterministic_exact", False))
        self.assertEqual(result["evidence_snippets"][0]["source_type"], "mail_inline_table_row")

    def test_arbitrary_price_quantity_fields_preserve_literal_source_values(self):
        fixture, revision, handler, arguments = self.prepare(content=_native_price_quantity_bytes())
        self.assertIsNone(revision.session)
        self.assertIsNone(revision.graph_build)
        arguments["query_text"] = "Find PART-N62 UnitPrice and Quantity"
        arguments["request_contract"].update(
            original_query_hash=sha256_json(arguments["query_text"]),
            requested_fields=["UnitPrice", "Quantity"],
        )
        arguments["table_query"] = {
            "filters": [{"field": "Code", "value": "PART-N62"}],
            "projection_fields": ["UnitPrice", "Quantity"],
        }
        native_hashes = {sha256_json(item.to_dict()) for item in fixture.observations}
        for explicit in (True, False):
            with self.subTest(explicit_table_query=explicit):
                if not explicit:
                    arguments.pop("table_query")
                result = handler(arguments)
                self.assertTrue(result["deterministic_exact"])
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["requested_field_coverage"]["missing_fields"], [])
                rows = result["exact_result"]["items"]
                self.assertEqual(len(rows), 1)
                values = rows[0]["structured_values"]
                self.assertEqual({(item["field"], item["value"]) for item in values},
                                 {("UnitPrice", "12.50"), ("Quantity", "18")})
                self.assertTrue(all(item["citation_hash"] in native_hashes for item in values))
                self.assertFalse(result["exact_result"]["coverage"]["authorized_scope_complete"])
                self.assertFalse(result["coverage"]["absence_claim"])

    def test_identifier_and_requested_fields_bind_exact_before_lexical_scan(self):
        _, revision, handler, arguments = self.prepare()
        arguments.pop("table_query")
        with patch.object(type(revision.source_records), "scan_authorized_observations", side_effect=AssertionError("lexical scan")):
            self.assert_values(handler(arguments))

    def test_prefixed_identifier_and_second_term_reach_same_native_row(self):
        _, _, handler, arguments = self.prepare(content=_native_prefixed_identifier_bytes())
        arguments.pop("table_query")
        arguments["query_text"] = "Find PO470002002 staged delivery"
        arguments["required_terms"] = ["PO470002002", "staged"]
        arguments["request_contract"].update(
            original_query_hash=sha256_json(arguments["query_text"]),
            requested_fields=["delivery"],
        )

        result = handler(arguments)

        self.assertTrue(result["citations"], result)
        self.assertTrue(result["evidence"], result)
        row = result["evidence"][0]["table_row"]
        values = {(item["field"], item["value"]) for item in row["cells"]}
        self.assertIn(("PO No.", "470002002"), values)
        self.assertIn(("State", "staged"), values)

    def test_automatic_exact_preserves_all_validated_content_constraints(self):
        _, _, handler, arguments = self.prepare()
        arguments.pop("table_query")
        arguments["required_terms"] = ["ITEM-Q73", "approved"]
        rejected = handler(arguments)
        self.assertFalse(rejected["citations"])
        self.assertFalse(rejected.get("requested_field_coverage", {}).get("supported_fields"))
        self.assertFalse(rejected.get("deterministic_exact", False))
        arguments["required_terms"] = ["ITEM-Q73", "staged"]
        self.assert_values(handler(arguments))

    def test_auto_exact_miss_recovers_mail_and_document_in_same_scope_and_budget(self):
        _, revision, handler, arguments = self.prepare(
            mail_text="ITEM-Z95 State is staged and Capacity is 18.",
            document_text="ITEM-Z95 State is staged and Capacity is 18.",
        )
        arguments.pop("table_query")
        arguments["query_text"] = "Find ITEM-Z95 State and Capacity"
        arguments["required_terms"] = ["ITEM-Z95"]
        arguments["request_contract"].update(
            original_query_hash=sha256_json(arguments["query_text"]),
            source_family_scope=["attachment_table", "mail", "document_text"],
        )
        original_deadline = time.monotonic() + 0.4
        with source_evidence_deadline_scope(original_deadline), patch.object(
            loader, "_execute_source_start_table", wraps=loader._execute_source_start_table,
        ) as exact, patch.object(
            type(revision.source_records), "scan_authorized_observations", autospec=True,
            side_effect=type(revision.source_records).scan_authorized_observations,
        ) as source_scan:
            result = handler(arguments)
        self.assertEqual(exact.call_count, 1)
        self.assertTrue(result["query_agent"]["exact_first"]["source_recovery_attempted"])
        self.assertTrue(result["query_agent"]["exact_first"]["all_requested_fields_missing"])
        self.assertTrue(result["citations"])
        self.assertTrue(any("staged" in item["snippet"] for item in result["evidence"]))
        self.assertEqual({call.kwargs["source_family"] for call in source_scan.call_args_list}, {"mail", "document_text"})
        self.assertTrue(all(call.kwargs["deadline_monotonic"] <= original_deadline for call in source_scan.call_args_list))
        self.assertEqual(result["coverage"]["status"], "incomplete")

    def test_unrelated_table_schema_does_not_divert_mail_field_request(self):
        _, revision, handler, arguments = self.prepare(mail_text="ITEM-Z95 Tone is amber.")
        arguments.pop("table_query")
        arguments["query_text"] = "Find ITEM-Z95 Tone"
        arguments["required_terms"] = ["ITEM-Z95"]
        arguments["request_contract"].update(
            original_query_hash=sha256_json(arguments["query_text"]),
            source_family_scope=["attachment_table", "mail"], requested_fields=["Tone"],
        )
        with patch.object(loader, "_execute_source_start_table", side_effect=AssertionError("unrelated schema")):
            result = handler(arguments)
        self.assertTrue(result["citations"])
        self.assertTrue(any("amber" in item["snippet"] for item in result["evidence"]))
        self.assertNotEqual(result["status"], "clarification_required")

    def test_all_missing_cells_recovery_deducts_exact_reads_and_evidence(self):
        _, revision, handler, arguments = self.prepare(
            content=_native_table_bytes(missing_columns=("B2", "C2")),
            mail_text="ITEM-Q73 State is staged and Capacity is 18.",
        )
        arguments.pop("table_query")
        arguments["required_terms"] = ["ITEM-Q73"]
        arguments["page_size"] = 2
        arguments["request_contract"]["source_family_scope"] = ["attachment_table", "mail"]
        original_deadline = time.monotonic() + 0.4
        with source_evidence_deadline_scope(original_deadline), patch.object(
            type(revision.source_records), "scan_authorized_observations", autospec=True,
            side_effect=type(revision.source_records).scan_authorized_observations,
        ) as source_scan:
            result = handler(arguments)
        trace = result["query_agent"]["exact_first"]
        self.assertGreater(trace["scanned_observation_count"], 0)
        self.assertTrue(trace["source_recovery_attempted"])
        self.assertTrue(result["citations"])
        self.assertEqual(len(result["evidence"]), 1)
        self.assertTrue(all(call.kwargs["max_observations"] <= 8192 - trace["scanned_observation_count"]
                            for call in source_scan.call_args_list))
        self.assertTrue(all(call.kwargs["deadline_monotonic"] <= original_deadline
                            for call in source_scan.call_args_list))

    def test_partial_cell_support_is_disclosed_without_automatic_source_recheck(self):
        _, revision, handler, arguments = self.prepare(
            content=_native_table_bytes(missing_columns=("C2",)),
            mail_text="ITEM-Q73 State is staged and Capacity is 18.",
        )
        arguments.pop("table_query")
        arguments["required_terms"] = ["ITEM-Q73"]
        arguments["request_contract"]["source_family_scope"] = ["attachment_table", "mail"]
        with patch.object(type(revision.source_records), "scan_authorized_observations",
                          side_effect=AssertionError("partial support must not recheck")):
            result = handler(arguments)
        self.assertTrue(result["deterministic_exact"])
        self.assertEqual(result["requested_field_coverage"]["supported_fields"], ["State"])
        self.assertEqual(result["requested_field_coverage"]["missing_fields"], ["Capacity"])
        self.assertEqual(result["status"], "partial")

    def test_unknown_alias_and_duplicate_labels_require_clarification(self):
        _, _, handler, arguments = self.prepare(content=_native_table_bytes(duplicate=True))
        arguments["request_contract"]["requested_fields"] = ["State"]
        arguments["table_query"]["projection_fields"] = ["State"]
        self.assertEqual(handler(arguments)["status"], "clarification_required")
        arguments["table_query"]["projection_fields"] = ["Phase"]
        self.assertEqual(handler(arguments)["status"], "clarification_required")

    def test_source_native_explicit_blank_counts_as_field_support_without_fabrication(self):
        fixture, _, handler, arguments = self.prepare(content=_native_table_bytes(blank=True))
        result = handler(arguments)
        self.assertTrue(result["deterministic_exact"])
        self.assertEqual(result["requested_field_coverage"]["missing_fields"], [])
        values = result["exact_result"]["items"][0]["structured_values"]
        blank = next(value for value in values if value["field"] == "Capacity")
        self.assertEqual(blank["value"], "")
        source_cell = next(item for item in fixture.observations if sha256_json(item.to_dict()) == blank["citation_hash"])
        self.assertTrue(source_cell.payload["native"]["explicit_blank"])

    def test_missing_literal_and_expired_budget_cannot_become_absence(self):
        _, revision, handler, arguments = self.prepare()
        arguments["table_query"]["filters"][0]["value"] = "ITEM-Z95"
        result = handler(arguments)
        self.assertEqual(result["status"], "pending_review")
        self.assertFalse(result["citations"])
        self.assertFalse(result["coverage"]["absence_claim"])
        arguments["table_query"]["filters"][0]["value"] = "ITEM-Q73"
        with source_evidence_deadline_scope(time.monotonic() - 1), patch.object(
            type(revision.job_authorities[0]), "load_indexed_observation", side_effect=AssertionError("expired read"),
        ):
            result = handler(arguments)
        self.assertEqual(result["coverage"]["reason"], "deadline")
        self.assertFalse(result["deterministic_exact"])

    def test_tampered_shard_and_denied_actor_fail_before_execution(self):
        _, revision, handler, arguments = self.prepare()
        denied = handler({**arguments, "requester_user_id": "unauthorized-synthetic-user"})
        self.assertEqual(denied["status"], "permission_denied")
        column = loader.source_occurrence_column_capability_hash("code")
        key = loader.source_occurrence_exact_cell_value_hash(column, "ITEM-Q73")
        shard = revision.exact_lookup_directory / "values" / f"{key[7:9]}.jsonl"
        shard.write_bytes(shard.read_bytes() + b"\n")
        with self.assertRaises(ContractValidationError):
            handler(arguments)


if __name__ == "__main__":
    unittest.main()
