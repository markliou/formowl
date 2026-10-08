from __future__ import annotations

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import _paths  # noqa: F401
from formowl_contract import (
    SourceInventory, SourceInventoryItem, assert_no_public_raw_references, sha256_json,
    stable_extractor_run_id, to_plain,
)
from formowl_ingestion.extraction import run_extractor
from formowl_ingestion.extractors.mail.pst import (
    NativePstAttachmentExport, NativePstMessageExport, PstMailArchiveExtractor,
    ReadpstSidecarBackfillExtractor, parse_native_pst_message_exports,
)
from formowl_ingestion.jobs import create_ingestion_job, run_ingestion_job
from formowl_ingestion.storage import JobStore, ObservationStore
from formowl_worker.ingestion import IngestionWorker
from test_pst_mail_extractor import _PstExtractionContext, _runner_with_messages


def _xlsx_fixture() -> bytes:
    content = io.BytesIO()
    with ZipFile(content, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Code</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>Value</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>SYN-SIDECAR</t></is></c>'
            '<c r="B2"><v>7</v></c></row></sheetData></worksheet>',
        )
    return content.getvalue()


class IngestionMailSourcePreservationTests(unittest.TestCase):
    def test_malformed_address_header_is_redacted_without_aborting_headers(self) -> None:
        from formowl_ingestion.extractors.mail.pst import _safe_headers

        message = BytesParser(policy=policy.default).parsebytes(
            b"To: Group: <a@b>; trailing-invalid\n"
            b"Subject: retained subject\nX-Ignored: ignored\n\nbody\n"
        )
        warnings: list[str] = []
        headers = _safe_headers(message, warnings=warnings)
        self.assertEqual(headers["to"], "redacted_header")
        self.assertEqual(headers["subject"], "retained subject")
        self.assertNotIn("ignored", headers)
        self.assertIn("pst_parser_header_redacted", warnings)

    def test_malformed_address_header_preserves_source_body_and_attachment(self) -> None:
        context = _PstExtractionContext.create("malformed-address-header")
        export = context.temp_dir / "synthetic-export"
        export.mkdir()
        raw = (
            b"To: Group: <a@b>; trailing-invalid\n"
            b"Subject: retained subject\nMIME-Version: 1.0\n"
            b"Content-Type: multipart/mixed; boundary=BOUNDARY\n\n"
            b"--BOUNDARY\nContent-Type: text/plain\n\nretained body\n"
            b"--BOUNDARY\nContent-Type: application/octet-stream\n"
            b"Content-Disposition: attachment; filename=fixture.bin\n\nbytes\n"
            b"--BOUNDARY--\n"
        )
        (export / "1").write_bytes(raw)
        marker = {"source_fingerprint": context.asset.content_hash}
        (export.parent / "readpst-export-complete.json").write_text(json.dumps(marker))
        result = run_extractor(
            asset=context.asset, object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=PstMailArchiveExtractor(existing_export_root=export),
            config={"ingestion_policy_id": "source_preserving_mail_v2",
                    "existing_export_binding_fingerprint": sha256_json(marker)},
        )
        self.assertEqual(sum(item.observation_type == "email_message"
                             for item in result.observations), 1)
        self.assertTrue(any("retained body" in item.text
                            for item in result.observations
                            if item.observation_type == "email_body_segment"))
        self.assertEqual(sum(item.observation_type == "email_attachment_occurrence"
                             for item in result.observations), 1)
        parent = next(item for item in result.observations
                      if item.observation_type == "email_message")
        self.assertEqual(parent.location["source_content_hash"],
                         "sha256:" + hashlib.sha256(raw).hexdigest())
        self.assertIn("pst_parser_header_redacted", result.extractor_run.warnings)
        self.assertIn("partial_extraction", result.extractor_run.warnings)

    def test_malformed_marked_section_preserves_feed_and_close_suffix(self) -> None:
        from html.parser import HTMLParser
        from formowl_ingestion.extractors.mail.pst import _HtmlTextExtractor

        original = HTMLParser.parse_marked_section
        for value, expected_phase in (
            ("before<![bogus[opaque]]>after", "feed"),
            ("<p title='unterminated>before<![bogus[opaque]]>after", "close"),
            ("before<![bogus suffix", "feed"),
        ):
            with self.subTest(phase=expected_phase):
                phase = "feed"
                seen = []

                def tracked(parser, index, report=1):
                    seen.append(phase)
                    return original(parser, index, report)

                parser = _HtmlTextExtractor()
                with patch.object(HTMLParser, "parse_marked_section", tracked):
                    parser.feed(value)
                    phase = "close"
                    parser.close()
                self.assertIn(expected_phase, seen)
                self.assertIn("before", parser.text())
                self.assertIn("suffix" if "suffix" in value else "after", parser.text())
                self.assertIn("bogus", parser.text())
                self.assertIn("pst_parser_html_marked_section_incomplete", parser.warnings)
                self.assertEqual(parser.tables, [])

    def test_malformed_marked_section_invalidates_only_affected_table(self) -> None:
        from formowl_ingestion.extractors.mail.pst import _HtmlTextExtractor

        parser = _HtmlTextExtractor()
        parser.feed(
            "<table><tr><td>healthy before</td></tr></table>"
            "<table><tr><td>before<![bogus[opaque<table><tr><td>"
            "unproven cell</td></tr></table>]]>after</td></tr></table>"
            "<table><tr><th>healthy after</th></tr></table>"
        )
        parser.close()
        self.assertEqual([table["table_ordinal"] for table in parser.tables], [1, 3])
        self.assertEqual(
            [table["rows"][0]["cells"][0]["value"] for table in parser.tables],
            ["healthy before", "healthy after"],
        )
        self.assertIn("opaque", parser.text())
        self.assertIn("after", parser.text())
        self.assertIn("pst_parser_html_table_unsupported", parser.warnings)
        self.assertIn("pst_parser_html_marked_section_incomplete", parser.warnings)

    def test_malformed_marked_section_fragments_do_not_invent_tables(self) -> None:
        from formowl_ingestion.extractors.mail.pst import _HtmlTextExtractor

        parser = _HtmlTextExtractor()
        parser.feed("before<![bogus[opaque")
        parser.feed(
            "]]>after<table><tr><td>healthy suffix</td></tr></table>"
        )
        parser.close()
        self.assertIn("before", parser.text())
        self.assertIn("opaque", parser.text())
        self.assertIn("after", parser.text())
        self.assertEqual(len(parser.tables), 1)
        self.assertEqual(parser.tables[0]["rows"][0]["cells"][0]["value"],
                         "healthy suffix")
        self.assertIn("pst_parser_html_marked_section_incomplete", parser.warnings)

        unterminated = _HtmlTextExtractor()
        unterminated.feed(
            "before<![bogus[<p>opaque</p><table><tr><td>unproven cell"
            "</td></tr></table>after"
        )
        unterminated.close()
        self.assertIn("before", unterminated.text())
        self.assertIn("after", unterminated.text())
        self.assertEqual(unterminated.tables, [])
        self.assertIn("pst_parser_html_marked_section_incomplete", unterminated.warnings)

    def test_healthy_html_marked_sections_and_table_are_unchanged(self) -> None:
        from formowl_ingestion.extractors.mail.pst import _HtmlTextExtractor

        parser = _HtmlTextExtractor()
        parser.feed(
            "<p>before &amp; after</p><![if support]><table><tr>"
            "<th>Code</th><td rowspan='2'>Value</td></tr>"
            "<tr><td>Other</td></tr></table><![endif]>"
        )
        parser.close()
        self.assertEqual(parser.warnings, [])
        self.assertEqual(len(parser.tables), 1)
        self.assertEqual(parser.tables[0]["rows"][0]["cells"][1]["row_span"], 2)
        self.assertIn("before & after", parser.text())

    def test_marked_section_recovery_does_not_swallow_unrelated_assertions(self) -> None:
        from html.parser import HTMLParser
        from formowl_ingestion.extractors.mail.pst import _HtmlTextExtractor

        with patch.object(HTMLParser, "parse_marked_section",
                          side_effect=AssertionError("unrelated parser invariant")):
            with self.assertRaisesRegex(AssertionError, "unrelated parser invariant"):
                _HtmlTextExtractor().feed("<![bogus[opaque]]>")

    def test_malformed_existing_export_retains_messages_mime_and_attachments(self) -> None:
        context = _PstExtractionContext.create("malformed-html-preservation")
        export = context.temp_dir / "synthetic-export"
        export.mkdir()
        malformed = EmailMessage()
        malformed["Subject"] = "Synthetic malformed body"
        malformed.set_content("alternate plain representation")
        malformed.add_alternative("before<![bogus[opaque]]>after", subtype="html")
        malformed.add_attachment(b"synthetic attachment", maintype="application",
                                 subtype="octet-stream", filename="synthetic.bin")
        healthy = EmailMessage()
        healthy["Subject"] = "Synthetic healthy body"
        healthy.set_content("<table><tr><td>healthy cell</td></tr></table>",
                            subtype="html")
        originals = [malformed.as_bytes(), healthy.as_bytes()]
        for index, raw in enumerate(originals, 1):
            (export / str(index)).write_bytes(raw)
        marker = {"source_fingerprint": context.asset.content_hash}
        (export.parent / "readpst-export-complete.json").write_text(json.dumps(marker))
        result = run_extractor(
            asset=context.asset, object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            adapter=PstMailArchiveExtractor(
                existing_export_root=export,
                runner=lambda *_: self.fail("synthetic existing export must not run readpst"),
            ),
            config={"ingestion_policy_id": "source_preserving_mail_v2",
                    "existing_export_binding_fingerprint": sha256_json(marker)},
        )
        for index, raw in enumerate(originals, 1):
            self.assertEqual((export / str(index)).read_bytes(), raw)
        parents = [item for item in result.observations
                   if item.observation_type == "email_message"]
        self.assertEqual(len(parents), 2)
        self.assertEqual({item.location["source_content_hash"] for item in parents},
                         {"sha256:" + hashlib.sha256(raw).hexdigest() for raw in originals})
        bodies = [item for item in result.observations
                  if item.observation_type == "email_body_segment"]
        self.assertTrue(any("alternate plain representation" in item.text for item in bodies))
        self.assertTrue(any("before" in item.text and "after" in item.text for item in bodies))
        self.assertEqual(sum(item.observation_type == "email_attachment_occurrence"
                             for item in result.observations), 1)
        self.assertEqual(sum(item.observation_type == "table_cell"
                             for item in result.observations), 1)
        self.assertIn("pst_parser_html_marked_section_incomplete", result.extractor_run.warnings)
        self.assertIn("partial_extraction", result.extractor_run.warnings)

    def test_duplicate_merge_declarations_do_not_hide_distinct_overlaps(self) -> None:
        from xml.etree import ElementTree as ET
        from formowl_ingestion.extractors.document.attachment import (
            _merged_ranges, _sheet_rows,
        )

        sheet = ET.fromstring(
            '<worksheet><sheetData><row r="1"><c r="A1"><v>7</v></c>'
            '</row></sheetData><mergeCells><mergeCell ref="A1:B1"/>'
            '<mergeCell ref="A1:B1"/><mergeCell ref="D1:E1"/>'
            '</mergeCells></worksheet>'
        )
        before = ET.tostring(sheet)
        rows = _sheet_rows(sheet, [])
        self.assertEqual(_merged_ranges(sheet), ((1, 1, 2, 1), (4, 1, 5, 1)))
        self.assertEqual(_sheet_rows(sheet, []), rows)
        self.assertEqual(ET.tostring(sheet), before)
        ET.SubElement(sheet.find("mergeCells"), "mergeCell", {"ref": "B1:C1"})
        with self.assertRaisesRegex(ValueError, "worksheet merged ranges overlap"):
            _merged_ranges(sheet)

    def test_missing_sidecar_parent_uses_native_number_and_unknown_headers(self) -> None:
        from formowl_ingestion.extraction import ExtractionInput
        from formowl_ingestion.extractors.mail.pst import _missing_sidecar_parent

        context = _PstExtractionContext.create("missing-sidecar-parent")
        export = context.temp_dir / "numeric-export"
        export.mkdir()
        path = export / "6467"
        raw = (
            b"Received: first\nReceived: second\nReceived: third\n"
            b"invalid unindented continuation\n"
            b"From: not-an-admitted-header@example.test\n"
            b"Date: not-an-admitted-date\n\nsource body\n"
        )
        path.write_bytes(raw)
        source_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        source = ExtractionInput(
            asset=context.asset, object_path=path, extractor_run_id="run_parent_repair",
            config={"prior_ingestion_job_id": "job_original"},
            created_at="2026-09-07T00:00:00+00:00",
        )
        parent, binding = _missing_sidecar_parent(
            path, export_root=export, source_content_hash=source_hash,
            extraction_input=source,
        )
        self.assertEqual(parent.location["message_index"], 6467)
        self.assertEqual(parent.location["message_index_basis"], "readpst_numeric_filename")
        self.assertEqual(parent.location["source_content_hash"], source_hash)
        self.assertEqual(parent.payload["sender"], "")
        self.assertEqual(parent.payload["sent_at"], "")
        self.assertEqual(parent.payload["body_extraction_state"], "not_performed")
        self.assertIn("MissingHeaderBodySeparatorDefect", parent.payload["header_parse_defects"])
        self.assertEqual(binding.parent_observation_id, parent.observation_id)
        self.assertEqual(binding.parent_extractor_run_id, source.extractor_run_id)
        other = export / "9"
        other.write_bytes(raw)
        _missing_sidecar_parent(
            other, export_root=export, source_content_hash=source_hash,
            extraction_input=source,
        )
        again, _ = _missing_sidecar_parent(
            path, export_root=export, source_content_hash=source_hash,
            extraction_input=source,
        )
        self.assertEqual(again.observation_id, parent.observation_id)
        self.assertEqual(path.read_bytes(), raw)

    def test_native_formal_job_materializes_inline_and_native_attachment(self) -> None:
        context = _PstExtractionContext.create("ingestion-native-formal-v2")
        message = EmailMessage()
        message["Subject"] = "Native inline fixture"
        message.set_content("<table><tr><td>Code</td><td>Value</td></tr>"
                            "<tr><td>SYN-NATIVE-2</td><td>Present</td></tr></table>",
                            subtype="html")
        message_path = context.temp_dir / "native.eml"
        message_path.write_bytes(message.as_bytes())
        attachment_path = context.temp_dir / "native.csv"
        attachment_path.write_bytes(b"Code,Value\nSYN-CHILD,7\n")
        message_hash = "sha256:" + hashlib.sha256(message_path.read_bytes()).hexdigest()
        attachment_hash = "sha256:" + hashlib.sha256(attachment_path.read_bytes()).hexdigest()
        locations = [
            ("mail_folder_descriptor_occurrence", {"source_local_key": "folder_1"}),
            ("email_message_occurrence", {"source_local_key": "message_1",
             "parent_source_local_key": "folder_1", "message_content_hash": message_hash}),
            ("email_attachment_occurrence", {"source_local_key": "attachment_1",
             "parent_source_local_key": "message_1", "attachment_content_hash": attachment_hash}),
        ]
        inventory = SourceInventory.create(
            source_asset_id=context.asset.asset_id,
            source_fingerprint=context.asset.content_hash,
            parser_fingerprint=sha256_json("native-fixture"),
            created_at="2026-09-07T09:00:00+00:00",
            items=[SourceInventoryItem.create(
                source_asset_id=context.asset.asset_id, structure_kind=kind,
                content_type="message/rfc822", ordinal=i, processing_state="parsed",
                raw_retention_state="retained", source_fingerprint=context.asset.content_hash,
                parser_fingerprint=sha256_json("native-fixture"),
                permission_scope=to_plain(context.asset.permission_scope), location=location,
            ) for i, (kind, location) in enumerate(locations, 1)],
        )
        manifest_hash = sha256_json("native-manifest-fixture")
        adapter = PstMailArchiveExtractor(
            native_source_inventory=inventory, native_manifest_fingerprint=manifest_hash,
            native_message_exports=[NativePstMessageExport(
                "message_1", "folder_1", "folder_node_1", "message_node_1", "data_node_1",
                message_hash, message_path.stat().st_size, message_path,
                (NativePstAttachmentExport(
                    "attachment_1", "message_1", "attachment_node_1", attachment_hash,
                    attachment_path.stat().st_size, "separate_exported", 1, attachment_path,
                ),),
            )],
            runner=lambda *_: self.fail("native reuse must not invoke readpst"),
        )
        jobs = JobStore(context.temp_dir)
        config = {"native_manifest_fingerprint": manifest_hash, "rebuild_revision": "native_v2"}
        job = create_ingestion_job(asset=context.asset, job_store=jobs,
                                   requested_by="user_owner", extractor_adapters=[adapter], config=config)
        finished = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id, asset_store=context.asset_store,
            job_store=jobs, object_store=context.object_store,
            extractor_run_store=context.run_store, observation_store=context.observation_store,
            extractor_adapters=[adapter], config=config, attachment_asset_store=context.asset_store,
        )
        self.assertEqual(finished.status, "succeeded", finished.error)
        stored = context.observation_store.list()
        self.assertEqual(set(finished.observation_ids), {item.observation_id for item in stored})
        self.assertEqual(len(finished.extractor_run_ids), 2)
        inline = [item for item in stored if item.location.get("source_family") == "mail_inline_table"]
        self.assertEqual(sum(item.observation_type == "table_cell" for item in inline), 4)
        parent = next(item for item in stored if item.observation_type == "email_message")
        self.assertTrue(all(item.location["parent_message_observation_id"] == parent.observation_id
                            for item in inline))

    def test_bound_existing_export_uses_formal_job_without_pst_invocation(self) -> None:
        context = _PstExtractionContext.create("ingestion-existing-export-v2")
        export_root = context.temp_dir / "preserved-export"
        export_root.mkdir()
        message = EmailMessage()
        message["Subject"] = "Existing registered export"
        message.set_content("<table><tr><td>Code</td><td>Value</td></tr>"
                            "<tr><td>SYN-EXPORTED-2</td><td>Retained</td></tr></table>",
                            subtype="html")
        original = message.as_bytes()
        export_file = export_root / "2"
        export_file.write_bytes(original)
        workbook = export_root / "2-detached-source.xlsx"
        workbook_bytes = _xlsx_fixture()
        workbook.write_bytes(workbook_bytes)
        marker = {"source_fingerprint": context.asset.content_hash,
                  "source_stat": {"size_bytes": len(b"!BDN unit fixture")}}
        marker_path = export_root.parent / "readpst-export-complete.json"
        marker_path.write_text(json.dumps(marker))
        adapter = PstMailArchiveExtractor(
            existing_export_root=export_root,
            runner=lambda *_: self.fail("existing-export reuse must not invoke readpst"),
        )
        config = {"ingestion_policy_id": "source_preserving_mail_v2",
                  "existing_export_binding_fingerprint": sha256_json(marker)}
        jobs = JobStore(context.temp_dir)
        job = create_ingestion_job(
            asset=context.asset, job_store=jobs, requested_by="user_owner",
            extractor_adapters=[adapter], config=config,
        )
        finished = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id, asset_store=context.asset_store,
            job_store=jobs, object_store=context.object_store,
            extractor_run_store=context.run_store, observation_store=context.observation_store,
            extractor_adapters=[adapter], config=config,
            attachment_asset_store=context.asset_store,
        )
        self.assertEqual(finished.status, "succeeded")
        self.assertEqual(export_file.read_bytes(), original)
        self.assertEqual(workbook.read_bytes(), workbook_bytes)
        self.assertTrue(marker_path.is_file())
        stored = context.observation_store.list()
        self.assertEqual(
            sum(item.observation_type == "email_message" for item in stored),
            1,
        )
        self.assertEqual(
            sum(
                item.observation_type == "table_cell"
                and item.location.get("source_family") == "mail_inline_table"
                for item in stored
            ),
            4,
        )
        attachment = next(
            item for item in stored if item.observation_type == "email_attachment_occurrence"
        )
        parent = next(item for item in stored if item.observation_type == "email_message")
        self.assertEqual(
            attachment.payload["message_occurrence_id"],
            parent.payload["message_occurrence_id"],
        )
        self.assertEqual(
            attachment.payload["mime_type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        child_asset = context.asset_store.get(attachment.payload["child_asset_id"])
        child_observations = [
            item for item in stored if item.asset_id == child_asset.asset_id
        ]
        self.assertEqual(
            {item.observation_type for item in child_observations},
            {"table_row", "table_cell"},
        )
        self.assertTrue(
            all(
                item.payload["lineage"]["attachment_source_ref"]["source_id"]
                == attachment.payload["source_inventory_item_id"]
                for item in child_observations
            )
        )
        self.assertEqual(len(finished.extractor_run_ids), 2)
        parent_run = next(
            item for item in context.run_store.list() if item.asset_id == context.asset.asset_id
        )
        self.assertIn("pst_existing_export_source_coverage_incomplete", parent_run.warnings)
        self.assertIn("partial_extraction", parent_run.warnings)

    def test_sidecar_backfill_reuses_existing_parent_without_message_regeneration(self) -> None:
        context = _PstExtractionContext.create("ingestion-sidecar-backfill-v1")
        export_root = context.temp_dir / "preserved-export"
        export_root.mkdir()
        message = EmailMessage()
        message["Message-ID"] = "<sidecar-parent@example.test>"
        message["Subject"] = "Existing parent"
        message.set_content("Existing source message.")
        (export_root / "2").write_bytes(message.as_bytes())
        marker = {
            "source_fingerprint": context.asset.content_hash,
            "source_stat": {"size_bytes": len(b"!BDN unit fixture")},
        }
        (export_root.parent / "readpst-export-complete.json").write_text(
            json.dumps(marker)
        )
        old_config = {
            "existing_export_binding_fingerprint": sha256_json(marker),
            "ingestion_policy_id": "source_preserving_mail_v2",
            "revision": "old_without_sidecar",
        }
        old_adapter = PstMailArchiveExtractor(
            version="0.2.1",
            existing_export_root=export_root,
        )
        jobs = JobStore(context.temp_dir)
        old_job = create_ingestion_job(
            asset=context.asset,
            job_store=jobs,
            requested_by="user_owner",
            extractor_adapters=[old_adapter],
            config=old_config,
        )
        old_finished = run_ingestion_job(
            ingestion_job_id=old_job.ingestion_job_id,
            asset_store=context.asset_store,
            job_store=jobs,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            extractor_adapters=[old_adapter],
            config=old_config,
            attachment_asset_store=context.asset_store,
        )
        self.assertEqual(old_finished.status, "succeeded")
        parent = next(
            item
            for item in context.observation_store.list()
            if item.observation_type == "email_message"
        )
        parent_run_id = old_finished.extractor_run_ids[0]
        old_job_snapshot = old_finished.to_dict()

        (export_root / "2-detached-source.xlsx").write_bytes(_xlsx_fixture())
        records = [
            {
                "source_content_hash": parent.location["source_content_hash"],
                "folder_path_hash": parent.location["folder_path_hash"],
                "message_id": parent.location["message_id"],
                "message_index": parent.location["message_index"],
                "parent_observation_id": parent.observation_id,
                "parent_extractor_run_id": parent_run_id,
                "parent_source_inventory_id": parent.location["source_inventory_id"],
                "parent_source_inventory_item_id": (
                    parent.location["source_inventory_item_id"]
                ),
                "archive_id": parent.location["archive_id"],
                "mailbox_id": parent.location["mailbox_id"],
                "message_occurrence_id": parent.location["message_occurrence_id"],
                "thread_id": parent.location["thread_id"],
                "message_fingerprint": parent.payload["message_fingerprint"],
                "existing_attachment_max_index": 0,
            }
        ]
        manifest = {
            "schema_version": 1,
            "source_asset_id": context.asset.asset_id,
            "source_fingerprint": context.asset.content_hash,
            "prior_ingestion_job_id": old_finished.ingestion_job_id,
            "prior_parent_run_id": parent_run_id,
            "prior_job_fingerprint": sha256_json(old_finished.to_dict()),
            "permission_scope_fingerprint": sha256_json(
                to_plain(context.asset.permission_scope)
            ),
            "parent_binding_count": len(records),
            "parent_binding_fingerprint": sha256_json(records),
            "records": records,
        }
        backfill = ReadpstSidecarBackfillExtractor(
            existing_export_root=export_root,
            parent_binding_manifest=manifest,
        )
        backfill_config = {
            "existing_export_binding_fingerprint": sha256_json(marker),
            "parent_binding_manifest_fingerprint": sha256_json(manifest),
            "prior_ingestion_job_id": old_finished.ingestion_job_id,
            "prior_parent_run_id": parent_run_id,
            "prior_job_fingerprint": manifest["prior_job_fingerprint"],
            "attachment_compact_child_results": True,
            "backfill_revision": "sidecar_backfill_v1",
        }
        new_job = create_ingestion_job(
            asset=context.asset,
            job_store=jobs,
            requested_by="user_owner",
            extractor_adapters=[backfill],
            config=backfill_config,
        )
        new_finished = run_ingestion_job(
            ingestion_job_id=new_job.ingestion_job_id,
            asset_store=context.asset_store,
            job_store=jobs,
            object_store=context.object_store,
            extractor_run_store=context.run_store,
            observation_store=context.observation_store,
            extractor_adapters=[backfill],
            config=backfill_config,
            attachment_asset_store=context.asset_store,
        )
        self.assertEqual(new_finished.status, "succeeded", new_finished.error)
        self.assertEqual(jobs.get(old_finished.ingestion_job_id).to_dict(), old_job_snapshot)
        self.assertEqual(len(new_finished.extractor_run_ids), 2)
        new_observations = [
            context.observation_store.get(observation_id)
            for observation_id in new_finished.observation_ids
        ]
        self.assertNotIn(
            "email_message",
            {item.observation_type for item in new_observations},
        )
        attachment = next(
            item
            for item in new_observations
            if item.observation_type == "email_attachment_occurrence"
        )
        self.assertEqual(
            attachment.location["parent_message_observation_id"],
            parent.observation_id,
        )
        self.assertEqual(
            attachment.location["parent_extractor_run_id"],
            parent_run_id,
        )
        child = [
            item
            for item in new_observations
            if item.observation_type in {"table_row", "table_cell"}
        ]
        self.assertTrue(child)
        self.assertTrue(
            all(
                item.payload["lineage"]["attachment_source_ref"]["source_id"]
                == attachment.payload["source_inventory_item_id"]
                for item in child
            )
        )

    @unittest.skipUnless(
        os.environ.get("FORMOWL_RUN_REGISTERED_NATIVE_INGESTION") == "1",
        "explicit registered native-source diagnostic only",
    )
    def test_registered_native_export_new_revision_round_trip(self) -> None:
        """One manifest-selected original export, no PST invocation or corpus scan."""
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / ".issue56-private-native-lineage-v1/native-private-manifest.json").read_bytes())
        snapshot = json.loads((root / ".test-tmp/issue56-native-source-complete-real/snapshot.json").read_bytes())
        inventory = SourceInventory.from_dict(snapshot["source_inventory"])
        self.assertEqual(manifest["source_asset_sha256"], inventory.source_fingerprint)
        self.assertEqual(snapshot["source_asset_sha256"], inventory.source_fingerprint)
        record = manifest["messages"][0]  # source order, no content/query-dependent selection
        item = next(item for item in inventory.items if
                    item.location.get("source_local_key") == record["source_local_key"])
        config = {"ingestion_policy_id": "complete_source_evidence_output_redaction_v1",
                  "diagnostic_scope": "one_registered_native_export_v2"}
        run_id = stable_extractor_run_id(
            asset_id=inventory.source_asset_id,
            extractor_name="pst_mail_archive_extractor", extractor_version="0.2.0",
            extractor_type="mail_archive", input_hash=inventory.source_fingerprint,
            config_hash=sha256_json(config),
        )
        native = NativePstMessageExport(
            source_local_key=record["source_local_key"],
            parent_folder_source_local_key=item.location["parent_source_local_key"],
            pst_folder_node_id=record["pst_folder_node_id"],
            pst_message_node_id=record["pst_message_node_id"],
            pst_message_data_node_id=record["pst_message_data_node_id"],
            message_content_hash=record["message_content_hash"],
            byte_count=record["byte_count"],
            export_path=(root / ".issue56-private-native-lineage-v1/export").joinpath(
                *record["relative_output_path"].split("/")
            ),
            attachments=tuple(NativePstAttachmentExport(
                source_local_key=attachment["source_local_key"],
                parent_message_source_local_key=record["source_local_key"],
                pst_attachment_node_id=attachment["pst_attachment_node_id"],
                attachment_content_hash=attachment["attachment_content_hash"],
                byte_count=attachment["byte_count"],
                export_disposition=attachment["export_disposition"],
                export_occurrence_ordinal=attachment["export_occurrence_ordinal"],
            ) for attachment in record["attachments"]),
        )
        result = parse_native_pst_message_exports(
            [native], source_inventory=inventory, source_asset_id=inventory.source_asset_id,
            source_asset_sha256=inventory.source_fingerprint, extractor_run_id=run_id,
            permission_scope=snapshot["authorization_binding"]["permission_scope"],
            provenance_fingerprint=sha256_json({
                "native_manifest_fingerprint": manifest["manifest_fingerprint"],
                "config": config,
            }),
            created_at="2026-09-07T08:50:00+00:00",
        )
        self.assertEqual(result.message_count, 1)
        self.assertNotIn("pst_parser_body_segment_limit_reached", result.warning_counts)
        with tempfile.TemporaryDirectory(prefix="formowl-native-ingestion-v2-") as temporary:
            store = ObservationStore(temporary)
            for observation in result.observations:
                store.create(observation)
                projection = observation.to_dict()
                projection.pop("extracted_value", None)
                assert_no_public_raw_references(projection)
            restored = ObservationStore(temporary).list()
            self.assertEqual(
                {item.observation_id: item.to_dict() for item in restored},
                {item.observation_id: item.to_dict() for item in result.observations},
            )
        print(json.dumps({
            "diagnostic": "one_registered_native_export_v2",
            "message_count": result.message_count,
            "observation_count": len(result.observations),
            "body_segment_count": result.body_segment_observation_count,
            "inline_table_cell_count": sum(
                item.observation_type == "table_cell" for item in result.observations
            ),
            "warning_counts": result.warning_counts,
            "full_source_coverage_claim": False,
        }))
    def test_normal_job_keeps_mime_tables_and_all_child_run_observation_ids(self) -> None:
        message = EmailMessage()
        message["From"] = "source@example.test"
        message["Subject"] = "Source-preserving ingestion"
        message.set_content("Paragraph one.\n\nTwo.\n\nThree.\n\nFourth paragraph survives.")
        message.add_alternative(
            "<p>HTML-only evidence.</p><table><tr><td>Identifier</td><td>Region</td></tr>"
            "<tr><td>SYN-ROW-17</td><td>North</td></tr></table>",
            subtype="html",
        )
        message.add_attachment(
            b"Identifier,Amount\nSYN-CHILD-9,12\n",
            maintype="application", subtype="octet-stream", filename="values.csv",
        )
        message.add_attachment(
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00",
            maintype="image", subtype="jpeg", filename="image.jpg",
        )
        context = _PstExtractionContext.create("ingestion-mail-mime-preservation")
        adapter = context.adapter_with_runner(_runner_with_messages([message.as_bytes()]))
        jobs = JobStore(context.temp_dir)
        config = {"ingestion_policy_id": "source_preserving_mail_v2"}
        job = create_ingestion_job(
            asset=context.asset, job_store=jobs, requested_by="user_owner",
            extractor_adapters=[adapter], config=config,
        )
        finished = run_ingestion_job(
            ingestion_job_id=job.ingestion_job_id, asset_store=context.asset_store,
            job_store=jobs, object_store=context.object_store,
            extractor_run_store=context.run_store, observation_store=context.observation_store,
            extractor_adapters=[adapter], config=config,
            attachment_asset_store=context.asset_store,
        )
        self.assertEqual(finished.status, "succeeded")
        stored = ObservationStore(context.temp_dir).list()
        self.assertEqual(set(finished.observation_ids), {item.observation_id for item in stored})
        self.assertEqual(set(finished.extractor_run_ids),
                         {item.extractor_run_id for item in context.run_store.list()})
        self.assertEqual(len(finished.extractor_run_ids), 3)
        self.assertTrue(any("attachment_document_unsupported_content" in run.warnings
                            for run in context.run_store.list()))
        bodies = [item for item in stored if item.observation_type == "email_body_segment"]
        self.assertTrue(any("Fourth paragraph" in item.text for item in bodies))
        self.assertTrue(any("HTML-only evidence" in item.text for item in bodies))
        self.assertEqual({item.location["content_type"] for item in bodies},
                         {"text/plain", "text/html"})
        parent = next(item for item in stored if item.observation_type == "email_message")
        inline = [item for item in stored if
                  (item.payload or {}).get("lineage", {}).get("source_family") == "mail_inline_table"]
        self.assertEqual(len(inline), 6)
        self.assertEqual({item.modality for item in inline}, {"document"})
        for item in inline:
            lineage = item.payload["lineage"]
            self.assertEqual(lineage["parent_message_observation_id"], parent.observation_id)
            self.assertEqual(lineage["message_occurrence_id"],
                             parent.location["message_occurrence_id"])
            self.assertEqual(item.asset_id, parent.asset_id)
            self.assertEqual(item.permission_scope, parent.permission_scope)
            self.assertGreater(lineage["mime_ordinal"], lineage["parent_mime_ordinal"])
            self.assertNotIn("parent_attachment_observation_id", lineage)
            self.assertNotIn("child_asset_id", lineage)
            self.assertEqual(item.payload["table_structure"]["structure_status"], "candidate_only")
        row = next(item for item in inline if
                   item.observation_type == "table_row" and item.location["row_index"] == 2)
        self.assertEqual(row.extracted_value, "SYN-ROW-17\tNorth")
        self.assertTrue(any(item.asset_id != parent.asset_id and
                            item.observation_type == "table_cell" for item in stored))

    def test_protected_body_and_cell_values_keep_safe_adjacent_evidence(self) -> None:
        message = EmailMessage()
        message["Subject"] = "Protected source and public projection"
        source = r"Source identifier SYN-KEEP-8. Path C:\private\source.txt belongs here."
        message.set_content(source)
        message.add_alternative(
            "<table><tr><th>Identifier</th><th>Note</th></tr>"
            "<tr><td>SYN-KEEP-8</td><td>Keep this; token=synthetic-test-value</td></tr>"
            "</table>", subtype="html",
        )
        context = _PstExtractionContext.create("ingestion-protected-source-values")
        result = run_extractor(
            asset=context.asset, object_store=context.object_store,
            extractor_run_store=context.run_store, observation_store=context.observation_store,
            adapter=context.adapter_with_runner(_runner_with_messages([message.as_bytes()])),
        )
        body = next(item for item in result.observations if
                    item.observation_type == "email_body_segment" and
                    item.location["content_type"] == "text/plain")
        self.assertEqual(body.extracted_value, source)
        self.assertIn("SYN-KEEP-8", body.text)
        self.assertIn("belongs here", body.text)
        self.assertNotIn("C:\\private", body.text)
        cell = next(item for item in result.observations if
                    item.observation_type == "table_cell" and
                    "synthetic-test-value" in str(item.extracted_value))
        self.assertIn("Keep this", cell.text)
        self.assertNotIn("synthetic-test-value", cell.text)
        for item in result.observations:
            projection = item.to_dict()
            projection.pop("extracted_value", None)
            assert_no_public_raw_references(projection)
        self.assertTrue(context.object_store.verify_object(
            context.asset.object_uri, context.asset.content_hash,
        ))

    def test_worker_materializes_attachment_and_exposes_partial_exclusions(self) -> None:
        message = EmailMessage()
        message["Subject"] = "Explicit processing limits"
        message.set_content("First paragraph.\n\nSecond paragraph.")
        message.add_attachment(
            b"unstructured attachment text", maintype="application",
            subtype="octet-stream", filename="notes.txt",
        )
        message.add_attachment(
            b"A,B\nC,7\n", maintype="application",
            subtype="octet-stream", filename="values.csv",
        )
        message.add_attachment(
            b"x" * 1000, maintype="application",
            subtype="octet-stream", filename="over-budget.bin",
        )
        context = _PstExtractionContext.create("ingestion-worker-source-exclusions")
        adapter = context.adapter_with_runner(_runner_with_messages([message.as_bytes()]))
        jobs = JobStore(context.temp_dir)
        config = {"max_body_segments_per_message": 1, "attachment_max_bytes": 64,
                  "ingestion_policy_id": "source_preserving_mail_v2"}
        job = create_ingestion_job(
            asset=context.asset, job_store=jobs, requested_by="user_owner",
            extractor_adapters=[adapter], config=config,
        )
        worker = IngestionWorker(
            worker_id="worker_source_preservation", asset_store=context.asset_store,
            job_store=jobs, object_store=context.object_store,
            extractor_run_store=context.run_store, observation_store=context.observation_store,
            extractor_adapters=[adapter], config=config,
        )
        worker.run_once()
        finished = jobs.get(job.ingestion_job_id)
        self.assertEqual(finished.status, "succeeded")  # processing, NOT complete-source coverage
        self.assertEqual(len(finished.extractor_run_ids), 4)
        parent_run = next(item for item in context.run_store.list()
                          if item.asset_id == context.asset.asset_id)
        self.assertIn("pst_parser_body_segment_limit_reached", parent_run.warnings)
        self.assertIn("attachment_document_unsupported_content", parent_run.warnings)
        self.assertIn("attachment_document_byte_limit_reached", parent_run.warnings)
        self.assertIn("attachment_child_extraction_incomplete", parent_run.warnings)
        self.assertIn("partial_extraction", parent_run.warnings)
        failed_children = [run for run in context.run_store.list() if run.status == "failed"]
        self.assertEqual(len(failed_children), 1)
        self.assertIn(failed_children[0].extractor_run_id, finished.extractor_run_ids)
        self.assertIsNotNone(context.asset_store.get(failed_children[0].asset_id))
        self.assertEqual(sum(item.observation_type == "table_cell"
                             for item in context.observation_store.list()), 4)
        attachment = next(item for item in context.observation_store.list()
                          if item.observation_type == "email_attachment_occurrence")
        self.assertIsNotNone(context.asset_store.get(attachment.payload["child_asset_id"]))


if __name__ == "__main__":
    unittest.main()
