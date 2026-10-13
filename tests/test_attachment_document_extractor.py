from __future__ import annotations

import io
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

import _paths  # noqa: F401
from formowl_contract import (
    Asset, PermissionScope, SourceRef, assert_no_public_raw_references, stable_observation_id,
)
from formowl_ingestion.assets import register_asset_from_local_file
from formowl_ingestion.extraction import ExtractionInput, run_extractor
from formowl_ingestion.extractors.document.attachment import (
    AttachmentDocumentExtractor,
    _looks_like_date_format,
)
from formowl_ingestion.storage import (
    AssetStore,
    ExtractorRunStore,
    FileObjectStore,
    ObservationStore,
    StorageBackendRegistry,
)


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSM_MIME = "application/vnd.ms-excel.sheet.macroenabled.12"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class AttachmentDocumentExtractorTests(unittest.TestCase):
    def test_xlsx_preserves_native_cell_metadata_and_existing_table_interfaces(self) -> None:
        result = self._extract(
            _xlsx_bytes(),
            mime_type=XLSX_MIME,
            filename="native.xlsx",
            config={"parent_asset_id": "asset_parent"},
        )
        self.assertFalse(result.errors)
        self.assertIn("xlsx_formula_recalculation_unverified", result.warnings)
        self.assertIn("xlsx_display_value_unavailable", result.warnings)
        cells = {
            item.location["cell_index"]: item
            for item in result.observations
            if item.observation_type == "table_cell" and item.location["row_index"] == 2
        }
        self.assertEqual(cells[1].text, "SYN-42")
        self.assertEqual(cells[3].text, "2")
        self.assertEqual(cells[3].payload["native"]["formula"], "1+1")
        self.assertEqual(cells[3].payload["native"]["cached_value"], "2")
        self.assertTrue(cells[4].payload["native"]["explicit_blank"])
        self.assertEqual(cells[2].payload["native"]["date_system"], "1900")
        self.assertTrue(cells[2].payload["native"]["date_format_detected"])
        self.assertEqual(cells[1].payload["lineage"]["parent_asset_id"], "asset_parent")
        self.assertEqual(cells[1].location["sheet_name"], "Data")
        for item in result.observations:
            self.assertEqual(
                item.observation_id,
                stable_observation_id(
                    asset_id=item.asset_id,
                    extractor_run_id=item.extractor_run_id,
                    observation_type=item.observation_type,
                    modality=item.modality,
                    location=item.location,
                    text=item.text,
                    payload=item.payload,
                    extracted_value=item.extracted_value,
                ),
            )

    def test_serialized_observations_redact_extracted_value_and_lineage(self) -> None:
        result = self._extract(
            b"password=/tmp/customer-secret/source.pst",
            mime_type="text/plain",
            filename="notes.txt",
            config={
                "parent_asset_id": "asset_parent",
                "parent_source_ref": "/tmp/customer-secret/source.pst",
                "attachment_source_ref": "s3://private-bucket/customer-secret/native.xlsx",
            },
        )
        self.assertFalse(result.errors)
        rendered = str([item.to_dict() for item in result.observations])
        self.assertNotIn("/tmp/customer-secret/source.pst", rendered)
        self.assertNotIn("s3://private-bucket/customer-secret/native.xlsx", rendered)
        self.assertTrue(
            any("redacted" in str(item.extracted_value) for item in result.observations)
        )
        for item in result.observations:
            self.assertEqual(
                item.payload["lineage"],
                {
                    "child_asset_id": "asset_child",
                    "child_content_hash": "sha256:" + "0" * 64,
                    "parent_asset_id": "asset_parent",
                    "parent_source_ref": "[redacted_path]",
                    "attachment_source_ref": "[redacted_internal_locator]",
                },
            )

    def test_plain_utf8_text_uses_paragraph_observations_without_page_claim(self) -> None:
        result = self._extract(
            "First paragraph.\n\nSecond paragraph.".encode(),
            mime_type="text/plain",
            filename="notes.txt",
        )
        self.assertFalse(result.errors)
        self.assertEqual(
            [item.text for item in result.observations], ["First paragraph.", "Second paragraph."]
        )
        self.assertTrue(all("page" not in item.location for item in result.observations))
        self.assertIn("text_page_locations_unavailable", result.warnings)

    def test_declared_plain_text_wins_over_delimiter_sniffing(self) -> None:
        for first_line in ("Heading, with a comma", "Heading\twith a tab"):
            with self.subTest(first_line=first_line):
                result = self._extract(
                    f"{first_line}\nFollowing prose without a matching delimiter.".encode(),
                    mime_type="text/plain",
                    filename="notes.txt",
                )
                self.assertFalse(result.errors)
                self.assertEqual(
                    [item.observation_type for item in result.observations], ["paragraph"]
                )
                self.assertEqual(
                    result.observations[0].text,
                    f"{first_line}\nFollowing prose without a matching delimiter.",
                )

    def test_excel_serial_boundaries_and_date_format_classifier(self) -> None:
        result = self._extract(
            _xlsx_serial_boundary_bytes(), mime_type=XLSX_MIME, filename="dates.xlsx"
        )
        cells = {
            item.location["cell_index"]: item
            for item in result.observations
            if item.observation_type == "table_cell" and item.location["row_index"] == 1
        }
        self.assertEqual(cells[1].payload["native"]["date_value_iso"], "1899-12-31T00:00:00")
        self.assertEqual(cells[2].payload["native"]["date_value_iso"], "1900-01-01T00:00:00")
        self.assertEqual(cells[3].payload["native"]["date_value_iso"], "1900-02-28T00:00:00")
        self.assertIsNone(cells[4].payload["native"]["date_value_iso"])
        self.assertEqual(cells[4].payload["native"]["date_value_status"], "phantom_1900_leap_day")
        self.assertTrue(_looks_like_date_format("yyyy-mm-dd"))
        self.assertFalse(_looks_like_date_format("[h]:mm:ss"))
        self.assertIn("xlsx_1900_phantom_date_serial", result.warnings)

    def test_numeric_precision_and_shared_formula_identity_are_preserved(self) -> None:
        result = self._extract(
            _xlsx_precision_formula_bytes(), mime_type=XLSX_MIME, filename="precision.xlsx"
        )
        row_one = {
            item.location["cell_index"]: item
            for item in result.observations
            if item.observation_type == "table_cell" and item.location["row_index"] == 1
        }
        large = row_one[1].payload["native"]
        decimal = row_one[2].payload["native"]
        shared = row_one[3].payload["native"]
        shared_child = {
            item.location["cell_index"]: item
            for item in result.observations
            if item.observation_type == "table_cell" and item.location["row_index"] == 2
        }[3].payload["native"]
        self.assertEqual(large["raw_value"], "900719925474099312345")
        self.assertEqual(large["typed_value"], 900719925474099312345)
        self.assertEqual(decimal["typed_value"], "0.12345678901234567890")
        self.assertEqual(shared["formula_si"], "2")
        self.assertEqual(shared["formula_status"], "shared_formula")
        self.assertEqual(shared["cached_value_status"], "present")
        self.assertEqual(shared_child["formula_si"], "2")
        self.assertEqual(shared_child["formula_status"], "shared_identity_only")
        self.assertEqual(shared_child["cached_value_status"], "present")
        self.assertIn("xlsx_shared_formula_identity_preserved", result.warnings)

    def test_malformed_pptx_library_shape_returns_stable_error(self) -> None:
        result = self._extract(
            _pptx_bytes(malformed=True), mime_type=PPTX_MIME, filename="bad.pptx"
        )
        self.assertEqual(result.errors, ["attachment_document_pptx_parse_failed"])

    def test_xlsm_dispatches_as_xlsx_and_discloses_macro_boundary(self) -> None:
        result = self._extract(
            _xlsx_bytes(macro_enabled=True),
            mime_type=XLSM_MIME,
            filename="macro.xlsm",
        )
        self.assertFalse(result.errors)
        self.assertIn("xlsx_macro_project_preserved_but_not_extracted", result.warnings)
        self.assertTrue(any(item.observation_type == "table_cell" for item in result.observations))

    def test_docx_and_pptx_emit_child_text_with_native_locations_and_lineage(self) -> None:
        docx_result = self._extract(
            _docx_bytes(),
            mime_type=DOCX_MIME,
            filename="brief.docx",
            config={"parent_asset_id": "parent"},
        )
        self.assertFalse(docx_result.errors)
        self.assertIn("docx_page_locations_unavailable", docx_result.warnings)
        heading = next(
            item for item in docx_result.observations if item.observation_type == "heading"
        )
        self.assertEqual(heading.text, "Project brief")
        self.assertEqual(heading.payload["lineage"]["parent_asset_id"], "parent")
        self.assertTrue(
            any(item.observation_type == "table_row" for item in docx_result.observations)
        )
        pptx_result = self._extract(_pptx_bytes(), mime_type=PPTX_MIME, filename="deck.pptx")
        self.assertFalse(pptx_result.errors)
        slides = [item for item in pptx_result.observations if item.observation_type == "paragraph"]
        self.assertEqual([item.location["slide"] for item in slides], [1, 2])
        self.assertEqual([item.text for item in slides], ["First slide", "Second slide"])

    def test_pdf_text_and_scan_only_paths_are_explicit(self) -> None:
        text_result = self._extract(
            _pdf_bytes("Hello PDF"), mime_type="application/pdf", filename="brief.pdf"
        )
        self.assertFalse(text_result.errors)
        self.assertEqual(text_result.observations[0].text, "Hello PDF")
        scan_result = self._extract(
            _blank_pdf_bytes(), mime_type="application/pdf", filename="scan.pdf"
        )
        self.assertFalse(scan_result.observations)
        self.assertIn("attachment_document_pdf_ocr_required", scan_result.warnings)

    def test_native_pdf_and_independent_utf8_preserve_safe_text_around_redacted_spans(self) -> None:
        pdf_text = "SYN-LEFT Qty 23.75 / / Grade B SYN-RIGHT"
        independent_text = "SYN-LEFT 稽核 café Qty 23.75 / / /私密/樣本.txt Grade B SYN-RIGHT"
        for content, mime_type, filename, expected in (
            (_pdf_bytes(pdf_text), "application/pdf", "fixture.pdf",
             "SYN-LEFT Qty 23.75 [redacted_path] [redacted_path] Grade B SYN-RIGHT"),
            (independent_text.encode(), "text/plain", "independent.txt",
             "SYN-LEFT 稽核 café Qty 23.75 [redacted_path] [redacted_path] [redacted_path] Grade B SYN-RIGHT"),
        ):
            with self.subTest(mime_type=mime_type):
                result = self._run_registered(content, mime_type, filename)
                self.assertEqual(result.extractor_run.status, "succeeded")
                self.assertEqual(len(result.observations), 1)
                observation = result.observations[0]
                self.assertEqual(observation.text, expected)
                self.assertEqual(observation.extracted_value, expected)
                self.assertEqual(observation.payload["value"], expected)
                self.assertEqual(observation.payload["lineage"]["child_content_hash"],
                                 "sha256:" + hashlib.sha256(content).hexdigest())
                self.assertEqual(observation.asset_id, result.extractor_run.asset_id)
                self.assertEqual(observation.extractor_run_id, result.extractor_run.extractor_run_id)
                self.assertEqual(observation.permission_scope, PermissionScope.project("project").to_dict())
                self.assertEqual(observation.location.get("page"), 1 if mime_type == "application/pdf" else None)
                self.assertEqual(observation.observation_id, stable_observation_id(
                    asset_id=observation.asset_id, extractor_run_id=observation.extractor_run_id,
                    observation_type=observation.observation_type, modality=observation.modality,
                    location=observation.location, text=observation.text, payload=observation.payload,
                    extracted_value=observation.extracted_value,
                ))
                assert_no_public_raw_references(observation.to_dict())
                self.assertEqual(AttachmentDocumentExtractor().version(), "0.6.2")
                self.assertEqual(result.extractor_run.extractor_version, "0.6.2")

    def test_pdf_reads_only_admitted_pages_once(self) -> None:
        pages = [Mock(), Mock()]
        pages[0].extract_text.return_value = "Page one"
        pages[1].extract_text.side_effect = AssertionError("page beyond cap was read")
        with patch("pypdf.PdfReader", return_value=Mock(pages=pages, is_encrypted=False)):
            result = self._extract(
                b"%PDF-1.4",
                mime_type="application/pdf",
                filename="brief.pdf",
                config={"attachment_max_pages": 1},
            )
        self.assertFalse(result.errors)
        pages[0].extract_text.assert_called_once()
        pages[1].extract_text.assert_not_called()
        self.assertIn("attachment_document_page_limit_reached", result.warnings)

    def test_unsupported_binary_and_zip_expansion_are_explicit(self) -> None:
        unsupported = self._extract(
            b"\x89PNG\r\n\x1a\n", mime_type="image/png", filename="image.png"
        )
        self.assertFalse(unsupported.observations)
        self.assertIn("attachment_document_unsupported_content", unsupported.warnings)
        bomb = io.BytesIO()
        with ZipFile(bomb, "w", compression=8) as archive:
            archive.writestr("xl/workbook.xml", b"0" * 32768)
        result = self._extract(
            bomb.getvalue(),
            mime_type="application/octet-stream",
            filename="bomb.zip",
            config={"attachment_max_bytes": 2048},
        )
        self.assertIn("attachment_document_parse_failed", result.errors)

    def test_malformed_optional_format_libraries_return_known_parser_errors(self) -> None:
        malformed_xls = self._extract(
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1malformed",
            mime_type="application/vnd.ms-excel",
            filename="bad.xls",
        )
        malformed_pdf = self._extract(
            b"%PDF-1.7\nmalformed", mime_type="application/pdf", filename="bad.pdf"
        )
        self.assertEqual(malformed_xls.errors, ["attachment_document_xls_parse_failed"])
        self.assertEqual(malformed_pdf.errors, ["attachment_document_pdf_parse_failed"])

    def test_supported_mime_capability_is_explicit(self) -> None:
        adapter = AttachmentDocumentExtractor()
        self.assertEqual(adapter.supported_mime_types(), ["*/*"])
        self.assertNotIn("*", adapter.capability_ids())
        self.assertIn("xls", adapter.capability_ids())

    def test_real_xls_fixture_preserves_cells_and_enforces_read_budget(self) -> None:
        try:
            import xlwt
        except ImportError:
            self.skipTest("xlwt is supplied by the formats test image")
        output = io.BytesIO()
        workbook = xlwt.Workbook()
        sheet = workbook.add_sheet("Legacy")
        sheet.write(0, 0, "ID")
        sheet.write(0, 1, "Value")
        sheet.write(1, 0, "SYN-XLS-1")
        sheet.write(1, 1, 7)
        workbook.save(output)
        content = output.getvalue()
        result = self._extract(content, mime_type="application/vnd.ms-excel", filename="legacy.xls")
        self.assertFalse(result.errors)
        self.assertIn("xls_formula_metadata_unavailable", result.warnings)
        self.assertTrue(any(item.text == "SYN-XLS-1" for item in result.observations))
        limited = self._extract(
            content,
            mime_type="application/vnd.ms-excel",
            filename="legacy.xls",
            config={"attachment_max_cells": 1},
        )
        self.assertIn("attachment_document_cell_limit_reached", limited.errors)
        self.assertFalse(limited.observations)

    def test_run_extractor_routes_unknown_children_without_claiming_image_support(self) -> None:
        image = self._run_registered(b"\x89PNG\r\n\x1a\n", "image/png", "photo.png")
        self.assertEqual(image.extractor_run.status, "succeeded")
        self.assertIn("attachment_document_unsupported_content", image.extractor_run.warnings)
        child = self._run_registered(_docx_bytes(), "application/octet-stream", "brief.bin")
        self.assertEqual(child.extractor_run.status, "succeeded")
        self.assertTrue(any(item.observation_type == "heading" for item in child.observations))

    def _extract(
        self, content: bytes, *, mime_type: str, filename: str, config: dict | None = None
    ):
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix) as handle:
            handle.write(content)
            handle.flush()
            asset = Asset.from_dict(
                {
                    "asset_id": "asset_child",
                    "storage_backend_id": "test",
                    "object_uri": "formowl://asset/child",
                    "content_hash": "sha256:" + "0" * 64,
                    "file_size": len(content),
                    "mime_type": mime_type,
                    "created_at": "2026-10-09T00:00:00+00:00",
                    "registered_at": "2026-10-09T00:00:00+00:00",
                    "owner_user_id": "user",
                    "workspace_id": "workspace",
                    "permission_scope": PermissionScope.project("project").to_dict(),
                    "lifecycle_state": "active",
                    "original_filename": filename,
                }
            )
            return AttachmentDocumentExtractor().extract(
                ExtractionInput(
                    asset=asset,
                    object_path=Path(handle.name),
                    extractor_run_id="run_attachment",
                    config=dict(config or {}),
                    created_at="2026-10-09T00:00:00+00:00",
                )
            )

    def _run_registered(self, content: bytes, mime_type: str, filename: str):
        root = _paths.fresh_test_dir("attachment-document-registered")
        incoming = root / filename
        incoming.write_bytes(content)
        registry = StorageBackendRegistry(root)
        backend = registry.register_local_backend(root / "objects", workspace_scope="workspace")
        object_store = FileObjectStore(registry)
        asset = register_asset_from_local_file(
            incoming,
            object_store=object_store,
            asset_store=AssetStore(root),
            storage_backend_id=backend.storage_backend_id,
            workspace_id="workspace",
            owner_user_id="user",
            permission_scope=PermissionScope.project("project"),
            source_ref=SourceRef(
                source_system="test", source_type="attachment", source_id=filename
            ),
            mime_type=mime_type,
        )
        return run_extractor(
            asset=asset,
            object_store=object_store,
            extractor_run_store=ExtractorRunStore(root),
            observation_store=ObservationStore(root),
            adapter=AttachmentDocumentExtractor(),
        )


def _xlsx_bytes(*, macro_enabled: bool = False) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            f"""<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
          <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.{"macroEnabled.main" if macro_enabled else "main"}+xml"/>
          <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
        </Types>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><workbookPr date1904="0"/><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>""",
        )
        archive.writestr(
            "xl/styles.xml",
            """<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
          <row r="1"><c r="A1" t="inlineStr"><is><t>ID</t></is></c><c r="B1" t="inlineStr"><is><t>Date</t></is></c><c r="C1" t="inlineStr"><is><t>Total</t></is></c><c r="D1" t="inlineStr"><is><t>Blank</t></is></c></row>
          <row r="2"><c r="A2" t="inlineStr"><is><t>SYN-42</t></is></c><c r="B2" s="1"><v>45292</v></c><c r="C2"><f>1+1</f><v>2</v></c><c r="D2" s="1"/></row>
        </sheetData></worksheet>""",
        )
        if macro_enabled:
            archive.writestr("xl/vbaProject.bin", b"macro-preserved")
    return output.getvalue()


def _docx_bytes() -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Project brief</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>ID</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>SYN-42</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>7</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>""",
        )
    return output.getvalue()


def _pptx_bytes(*, malformed: bool = False) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            "<p:presentation xmlns:p='p' xmlns:r='r'><p:sldIdLst><p:sldId id='1' r:id='rId2'/><p:sldId id='2' r:id='rId1'/></p:sldIdLst></p:presentation>",
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            "<Relationships xmlns='r'><Relationship Id='rId1' Target='slides/slide2.xml'/><Relationship Id='rId2' Target='slides/slide1.xml'/></Relationships>",
        )
        archive.writestr(
            "ppt/slides/slide2.xml", "<p:s xmlns:p='p' xmlns:a='a'><a:t>Second slide</a:t></p:s>"
        )
        archive.writestr(
            "ppt/slides/slide1.xml",
            "<p:s><a:t>malformed</a:t></p:s>"
            if malformed
            else "<p:s xmlns:p='p' xmlns:a='a'><a:t>First slide</a:t></p:s>",
        )
    return output.getvalue()


def _xlsx_serial_boundary_bytes() -> bytes:
    styles = """<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="2"><numFmt numFmtId="165" formatCode="yyyy-mm-dd"/><numFmt numFmtId="166" formatCode="[h]:mm:ss"/></numFmts><cellXfs count="4"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="165"/><xf numFmtId="166"/></cellXfs></styleSheet>"""
    sheet = """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" s="1"><v>0</v></c><c r="B1" s="1"><v>1</v></c><c r="C1" s="1"><v>59</v></c><c r="D1" s="1"><v>60</v></c><c r="E1" s="2"><v>61</v></c><c r="F1" s="3"><v>60</v></c></row></sheetData></worksheet>"""
    return _xlsx_package(sheet, styles)


def _xlsx_precision_formula_bytes() -> bytes:
    sheet = """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>900719925474099312345</v></c><c r="B1"><v>0.12345678901234567890</v></c><c r="C1"><f t="shared" si="2" ref="C1:C2">A1+B1</f><v>900719925474099312346</v></c></row><row r="2"><c r="C2"><f t="shared" si="2"/><v>900719925474099312347</v></c></row></sheetData></worksheet>"""
    return _xlsx_package(
        sheet,
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs count="1"><xf numFmtId="0"/></cellXfs></styleSheet>',
    )


def _xlsx_package(sheet: str, styles: str) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'><Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/><Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/></Types>",
        )
        archive.writestr(
            "xl/workbook.xml",
            "<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='Data' sheetId='1' r:id='rId1'/></sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Target='worksheets/sheet1.xml'/></Relationships>",
        )
        archive.writestr("xl/styles.xml", styles)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def _pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    result.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    result.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(result)


def _blank_pdf_bytes() -> bytes:
    return _pdf_bytes("")


if __name__ == "__main__":
    unittest.main()
